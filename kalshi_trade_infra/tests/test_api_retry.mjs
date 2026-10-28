// api() retries a GET through a restart (fetch rejects, or CloudFront answers 502/503/504),
// and never retries a write. Both bundles share the contract.
import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

function loadApi(file) {
  const src = readFileSync(new URL('../app/static/' + file, import.meta.url), 'utf8');
  const pick = (re) => { const m = src.match(re); assert.ok(m, file + ': ' + re); return m[0]; };
  const code = [
    pick(/class ApiError extends Error \{[^\n]*\}/),
    pick(/const STALE = [^\n]*/),
    pick(/const TRANSIENT = [^\n]*/),
    pick(/const READ_MS = [^\n]*/),
    pick(/const sleep = [^\n]*/),
    pick(/const failText = [\s\S]*?;\n/),
    pick(/const reportBroken = [^\n]*/),
    pick(/const apiBroke = [^\n]*/),
    pick(/async function api\(path, body, cfg\) \{[\s\S]*?\n  \}\n/),
    'globalThis.api = api;',
  ].join('\n');
  const calls = [];
  const replies = [];
  const reports = [];
  const deadlines = [];
  const signals = [];
  const ctx = {
    window: {__tauReport: (kind, err) => reports.push([kind, err])},
    S: {gen: 1, me: {}}, go: () => {}, clearTimeout: () => {}, AbortController,
    // The retry back-off passes at once; a read's deadline (READ_MS) is held in `deadlines` for a test to fire.
    setTimeout: (fn, ms) => { if (ms >= 10000) { deadlines.push(fn); return 1; } fn(); return 0; },
    fetch: async (path, opts) => { calls.push(opts.method || 'GET'); signals.push(opts.signal || null); const r = replies.shift(); if (r instanceof Error) throw r; return r; },
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return {api: ctx.api, calls, replies, reports, ctx, deadlines, signals};
}
const reply = (status, data = {}) => ({ok: status < 400, status, json: async () => data});
// CloudFront's own 5xx page is HTML, so json() throws.
const edge = (status) => ({ok: false, status, json: async () => { throw new SyntaxError('Unexpected token <'); }});

for (const file of ['app.js', 'app.meridian.js']) {
  test(file + ': a GET rides out a restart', async () => {
    const t = loadApi(file);
    t.replies.push(new TypeError('Failed to fetch'), edge(502), reply(200, {ok: 1}));
    assert.deepEqual(await t.api('/api/dashboard'), {ok: 1});
    assert.equal(t.calls.length, 3);
  });

  test(file + ': a GET gives up after two retries with the real error', async () => {
    const t = loadApi(file);
    t.replies.push(edge(503), edge(504), edge(503));
    await assert.rejects(t.api('/api/dashboard'), (e) => e.status === 503 && /503/.test(e.message));
    assert.equal(t.calls.length, 3);
  });

  test(file + ': a JSON 503 is Tau answering, so it is final', async () => {
    const t = loadApi(file);
    t.replies.push(reply(503, {error: 'source unavailable'}));
    await assert.rejects(t.api('/api/strategies/42'), (e) => e.status === 503 && e.message === 'source unavailable');
    assert.equal(t.calls.length, 1);
  });

  test(file + ': app errors and writes are not retried', async () => {
    const t = loadApi(file);
    t.replies.push(reply(500, {error: 'boom'}));
    await assert.rejects(t.api('/api/dashboard'), (e) => e.status === 500);
    t.replies.push(edge(502));
    await assert.rejects(t.api('/api/settings', {a: 1}), (e) => e.status === 502);
    t.replies.push(new TypeError('Failed to fetch'));
    await assert.rejects(t.api('/api/settings', {a: 1}), (e) => e.status === 0);
    assert.deepEqual(t.calls, ['GET', 'POST', 'POST']);
  });
}

// A failure never shows the browser's or the edge's own text, and a write Tau may have taken says to
// check before trying again (deploys and orders are never retried for the user).
for (const file of ['app.js', 'app.meridian.js']) {
  test(file + ': a 200 whose body is not JSON is a plain failure, not an empty answer', async () => {
    const t = loadApi(file);
    t.replies.push({ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected end of JSON input'); }});
    await assert.rejects(t.api('/api/dashboard'), (e) => e.status === 200 && e.message === 'Tau’s reply didn’t come through whole. Try again.');
    t.replies.push(reply(200, null));
    await assert.rejects(t.api('/api/dashboard'), (e) => !/JSON|null|undefined/.test(e.message));
    assert.equal(t.calls.length, 2);
  });

  test(file + ': a read that can’t reach Tau says so with a curly apostrophe', () => {
    // Walk 2026-10-28: the read-side failures wrote "Can't" and "didn't" with straight apostrophes.
    const t = loadApi(file);
    assert.equal(vm.runInContext('failText(0, false)', t.ctx), 'Can’t reach Tau. Check your connection.');
  });

  test(file + ': an HTML error page or a 429 reads as plain words', async () => {
    const t = loadApi(file);
    t.replies.push(edge(500));
    await assert.rejects(t.api('/api/dashboard'), (e) => e.status === 500 && e.message === 'Tau is having trouble right now (500). Try again in a moment.');
    t.replies.push({ok: false, status: 429, json: async () => { throw new SyntaxError('Unexpected token <'); }});
    await assert.rejects(t.api('/api/dashboard'), (e) => e.status === 429 && /Try again in a minute/.test(e.message));
    t.replies.push(reply(429, {error: 'You can run up to 5 deployments at once.'}));
    await assert.rejects(t.api('/api/deployments', {strategy_id: 1}), (e) => e.message === 'You can run up to 5 deployments at once.');
  });

  test(file + ': a write with no answer says it may have gone through, once, with no retry', async () => {
    const t = loadApi(file);
    const unsure = (e) => /may or may not have gone through/.test(e.message) && /check before you try again/.test(e.message);
    t.replies.push(new TypeError('Failed to fetch'));
    await assert.rejects(t.api('/api/deployments', {strategy_id: 1, mode: 'paper'}), (e) => e.status === 0 && unsure(e));
    t.replies.push(edge(504));
    await assert.rejects(t.api('/api/deployments', {strategy_id: 1, mode: 'paper'}), (e) => e.status === 504 && unsure(e));
    t.replies.push({ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected end of JSON input'); }});
    await assert.rejects(t.api('/api/chat', {content: 'hi'}), unsure);
    // Tau's own JSON error is an answer: it says what happened, not "check".
    t.replies.push(reply(500, {error: "Something went wrong on our side. It’s been logged."}));
    await assert.rejects(t.api('/api/chat', {content: 'hi'}), (e) => !unsure(e));
    assert.deepEqual(t.calls, ['POST', 'POST', 'POST', 'POST']);
  });
}

// A failure the page shows as an error is reported to the operator's readout (boot.js's
// window.__tauReport): no reply, a 5xx, or a reply that isn't JSON. Never a 4xx, a 401, our own
// timeout, or a GET that rode out a restart. The path goes without its query, ids as :id.
for (const file of ['app.js', 'app.meridian.js']) {
  test(file + ': an API call that broke is reported once it fails, with the route and no query', async () => {
    const t = loadApi(file);
    t.replies.push(new TypeError('Failed to fetch'), edge(502), reply(200, {ok: 1}));
    await t.api('/api/dashboard');
    assert.deepEqual(t.reports, []);  // retried through a restart: the page never showed an error
    t.replies.push(reply(500, {error: 'boom'}));
    await assert.rejects(t.api('/api/strategies/42/live-readiness?email=a@b.co&token=x'));
    t.replies.push(new TypeError('Failed to fetch'));
    await assert.rejects(t.api('/api/deployments/7/stop', {secret: 'form value'}));
    t.replies.push({ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected end of JSON input'); }});
    await assert.rejects(t.api('/api/runs/12', {content: 'hi'}));
    assert.deepEqual(t.reports, [['api', 'GET /api/strategies/:id/live-readiness failed (500)'],
      ['api', 'POST /api/deployments/:id/stop got no reply'], ['api', 'POST /api/runs/:id replied with no JSON']]);
    assert.doesNotMatch(JSON.stringify(t.reports), /email|token|secret|form value|a@b/);
  });

  test(file + ': an answer (4xx, 401) or our own timeout is not reported', async () => {
    const t = loadApi(file);
    t.replies.push(reply(400, {error: 'Pick a market.'}), reply(404, {error: 'No such run.'}), reply(429, {error: 'slow down'}));
    for (let i = 0; i < 3; i++) await assert.rejects(t.api('/api/runs', {x: 1}));
    t.replies.push(reply(401, {error: 'Please sign in.'}));
    await assert.rejects(t.api('/api/me'));
    t.ctx.fetch = (path, opts) => new Promise((resolve, reject) => opts.signal.addEventListener('abort', () => reject(new Error('aborted'))));
    t.ctx.setTimeout = (fn) => { Promise.resolve().then(fn); return 0; };
    await assert.rejects(t.api('/api/me', undefined, {timeoutMs: 5}), (e) => e.status === 0);
    assert.deepEqual(t.reports, []);
  });

  test(file + ': a reporter that throws, or none at all, never changes the error the page gets', async () => {
    for (const w of [{__tauReport: () => { throw new Error('reporter broke'); }}, {}]) {
      const t = loadApi(file);
      t.ctx.window = w;
      t.replies.push(reply(503, {error: 'source unavailable'}));
      await assert.rejects(t.api('/api/strategies/42'), (e) => e.status === 503 && e.message === 'source unavailable');
    }
  });
}

// A read the network swallows (no answer, no error) gives up at READ_MS and says so, so the page shows its
// Try again instead of a skeleton for good. A write keeps waiting: Tau may still be doing it.
for (const file of ['app.js', 'app.meridian.js']) {
  test(file + ': a read that never answers gives up once, with words and no retry', async () => {
    const t = loadApi(file);
    t.ctx.fetch = (path, opts) => { t.calls.push(opts.method || 'GET'); return new Promise((resolve, reject) => opts.signal.addEventListener('abort', () => reject(new Error('aborted')))); };
    const read = t.api('/api/deployments');
    await Promise.resolve();
    assert.equal(t.deadlines.length, 1);
    t.deadlines[0]();
    await assert.rejects(read, (e) => e.status === 0 && e.message === 'Tau is taking too long to respond.');
    assert.deepEqual(t.calls, ['GET']);
    assert.deepEqual(t.reports, []);
  });

  test(file + ': a read that answers in time keeps its deadline from firing; a write has none', async () => {
    const t = loadApi(file);
    t.replies.push(reply(200, {ok: 1}), reply(200, {id: 1}));
    assert.deepEqual(await t.api('/api/deployments'), {ok: 1});
    assert.ok(t.signals[0], 'the read is sent with a deadline');
    assert.deepEqual(await t.api('/api/deployments/7/pause', {}), {id: 1});
    assert.equal(t.signals[1], null, 'a write is never cut short');
    assert.equal(t.deadlines.length, 1);
  });
}
