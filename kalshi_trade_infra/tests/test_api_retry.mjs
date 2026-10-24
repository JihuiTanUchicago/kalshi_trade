// api() retries a GET through a restart (fetch rejects, or CloudFront answers 502/503/504),
// and never retries a write. Both bundles share the contract.
import assert from 'node:assert/strict';
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
    pick(/const sleep = [^\n]*/),
    pick(/async function api\(path, body, cfg\) \{[\s\S]*?\n  \}\n/),
    'globalThis.api = api;',
  ].join('\n');
  const calls = [];
  const replies = [];
  const ctx = {
    S: {gen: 1, me: {}}, go: () => {}, setTimeout: (fn) => { fn(); return 0; }, clearTimeout: () => {}, AbortController,
    fetch: async (path, opts) => { calls.push(opts.method || 'GET'); const r = replies.shift(); if (r instanceof Error) throw r; return r; },
  };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return {api: ctx.api, calls, replies};
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
