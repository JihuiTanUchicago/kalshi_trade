// boot.js's page error reports: an uncaught error, an unhandled rejection, or a failure the app bundle
// passes to window.__tauReport goes to POST /api/client-errors, at most 5 per page load, each distinct
// one once, with nothing that could identify a person, and the reporter itself can never throw or loop.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const BOOT = readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8');
const ORIGIN = 'https://tau.example';

function page({fetchImpl, pathname = '/strategies/42', search = '?email=a@b.co&token=abc', theme = 'meridian', build = '9fea608a94'} = {}) {
  const listeners = {}, sent = [];
  const window = {__TAU_UI__: theme, __BUILD__: build,
    addEventListener: (name, cb) => { (listeners[name] = listeners[name] || []).push(cb); }};
  const context = {
    window, location: {pathname, search, origin: ORIGIN},
    document: {getElementById: () => null},  // no theme bootstrap element: only the reporter runs
    fetch: fetchImpl || ((url, opts) => { sent.push({url, opts, body: JSON.parse(opts.body)}); return Promise.resolve({ok: true}); }),
  };
  vm.runInNewContext(BOOT, context);
  const fire = (name, ev) => (listeners[name] || []).forEach((cb) => cb(ev));
  return {window, listeners, sent, context,
    error: (error, filename = ORIGIN + '/static/app.meridian.js?v=9fea608a94', lineno = 120, colno = 7) =>
      fire('error', {error, message: error && error.message, filename, lineno, colno}),
    reject: (reason) => fire('unhandledrejection', {reason})};
}

test('an uncaught error is sent once, as a keepalive POST with the CSRF header and only what locates it', () => {
  const p = page();
  p.error(new TypeError("Cannot read properties of undefined (reading 'pnl')"));
  assert.equal(p.sent.length, 1);
  const {url, opts, body} = p.sent[0];
  assert.equal(url, '/api/client-errors');
  assert.equal(opts.method, 'POST'); assert.equal(opts.keepalive, true); assert.equal(opts.credentials, 'same-origin');
  assert.equal(opts.headers['X-Recursive'], '1'); assert.equal(opts.headers['Content-Type'], 'application/json');
  assert.deepEqual(body, {kind: 'error', message: "TypeError: Cannot read properties of undefined (reading 'pnl')",
    src: 'app.meridian.js', line: 120, col: 7, path: '/strategies/:id', theme: 'meridian', ver: '9fea608a94'});
});

test('identical reports are sent once, and a page load sends at most five', () => {
  const p = page();
  for (let i = 0; i < 3; i++) p.error(new Error('same bug'));
  assert.equal(p.sent.length, 1);
  for (let i = 0; i < 10; i++) p.reject(new Error('bug ' + i));
  assert.equal(p.sent.length, 5);
  p.window.__tauReport('api', 'GET /api/dashboard failed (500)');
  assert.equal(p.sent.length, 5);
});

test('no personal data: no query string, form value, email, key, token or long number, and a long message is cut', () => {
  const p = page({pathname: '/research/123'});
  p.reject(new Error('Bad reply from /api/runs?user=a@b.co&key=1 for jane.doe+x@gmail.com key sk_live_4eC39HqLyjWDarjtT1zdp7dc card 4242424242424242'));
  p.reject({password: 'hunter2', email: 'a@b.co', toString: () => 'hunter2'});
  p.reject('word '.repeat(1000));
  p.reject(undefined);
  const all = JSON.stringify(p.sent.map((s) => s.body));
  assert.doesNotMatch(all, /a@b\.co|jane|gmail|sk_live|4242424242|hunter2|user=|key=1|\?|token|email=/);
  assert.equal(p.sent[0].body.message, 'Bad reply from /api/runs for <email> key <redacted> card <n>');
  assert.equal(p.sent[1].body.message, 'A non-Error value (object)');
  assert.equal(p.sent[2].body.message.length, 300);
  assert.equal(p.sent[3].body.message, 'A non-Error value (undefined)');
  for (const {body} of p.sent) {
    assert.deepEqual(Object.keys(body), ['kind', 'message', 'src', 'line', 'col', 'path', 'theme', 'ver']);
    assert.equal(body.path, '/research/:id');
  }
});

test("a rejection's script position comes from its stack, as a file name with no query", () => {
  const p = page({theme: 'tau'});
  const e = new Error('nope');
  e.stack = 'Error: nope\n    at viewRun (https://tau.example/static/app.js?v=abc:4512:19)\n    at render (https://tau.example/static/app.js?v=abc:600:3)';
  p.reject(e);
  assert.deepEqual([p.sent[0].body.src, p.sent[0].body.line, p.sent[0].body.col, p.sent[0].body.theme], ['app.js', 4512, 19, 'tau']);
});

test('the app bundle reports through window.__tauReport as api or view', () => {
  const p = page();
  p.window.__tauReport('api', 'GET /api/strategies/:id failed (503)');
  p.window.__tauReport('anything', new RangeError('Invalid time value'));
  assert.deepEqual(p.sent.map((s) => [s.body.kind, s.body.message]),
    [['api', 'GET /api/strategies/:id failed (503)'], ['view', 'RangeError: Invalid time value']]);
});

test("another origin's opaque error or a browser extension's is not reported", () => {
  const p = page();
  p.listeners.error[0]({message: 'Script error.', filename: '', lineno: 0, colno: 0, error: null});
  p.error(new Error('from an extension'), 'chrome-extension://abc/content.js');
  p.error(new Error('from stripe'), 'https://js.stripe.com/v3/');
  assert.equal(p.sent.length, 0);
});

test('the reporter never throws and never reports itself, whatever the transport or the error does', async () => {
  let unhandled = 0;
  const onUnhandled = () => { unhandled++; };
  process.on('unhandledRejection', onUnhandled);
  try {
    const throwing = page({fetchImpl: () => { throw new TypeError('fetch blew up'); }});
    assert.doesNotThrow(() => throwing.error(new Error('a')));
    const rejecting = page({fetchImpl: () => Promise.reject(new TypeError('Failed to fetch'))});
    assert.doesNotThrow(() => rejecting.error(new Error('b')));
    const none = page(); none.context.fetch = undefined;
    assert.doesNotThrow(() => none.window.__tauReport('view', new Error('c')));
    const hostile = page();
    const evil = {get message() { throw new Error('getter'); }, get stack() { throw new Error('getter'); }};
    assert.doesNotThrow(() => hostile.reject(evil));
    assert.doesNotThrow(() => hostile.listeners.error[0](undefined));
    assert.doesNotThrow(() => hostile.listeners.unhandledrejection[0](undefined));
    // A transport that itself reports (or fails into a report) can't loop: one request, not a cascade.
    let calls = 0;
    const loop = page({fetchImpl: () => { calls++; loop.window.__tauReport('view', new Error('inner ' + calls)); throw new Error('send failed'); }});
    loop.error(new Error('outer'));
    assert.equal(calls, 1);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(unhandled, 0);
  } finally {
    process.off('unhandledRejection', onUnhandled);
  }
});

test('the page shell keeps working when the browser has no addEventListener or location', () => {
  assert.doesNotThrow(() => vm.runInNewContext(BOOT, {window: {}, document: {getElementById: () => null}}));
  const window = {};
  vm.runInNewContext(BOOT, {window, document: {getElementById: () => null}, fetch: () => Promise.resolve()});
  assert.doesNotThrow(() => window.__tauReport('view', new Error('no location')));
});
