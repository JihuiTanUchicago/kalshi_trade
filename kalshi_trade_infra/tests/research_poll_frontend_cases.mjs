// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the Research
// list's 5s poll sends back the version of its last answer, repaints nothing when the server says the
// list is unchanged, and when one session moved rewrites that session's row alone.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const run = (over) => ({id: 1, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea',
  hypotheses_tried: 9, strategies_passed: 1, spent_usd: 4.2, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit', ...over});
const counts = {research_running: 1, research_queued: 0, research_paused: 0};

export function researchPollCases({name, frontend}) {
  test(`${name}: the research list poll repaints nothing while the list is unchanged, then only the row that moved`, async () => {
    const runs = [run({id: 9, status: 'running', stop_reason: null, spent_usd: 0.5, created_at: '2026-10-26T08:00:00Z'}),
      run({id: 8, spent_usd: 1.25}), run({id: 7, spent_usd: 2})];
    let answer = {runs, counts, policy: null, totals: {tried: 27, passed: 3}, v: 'v1'};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response(answer);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const list = f.root.querySelector('#runs'), figs = f.root.querySelector('#rfigs');
    const row = (id) => list.children.find((el) => el.getAttribute('href') === `/research/${id}`);
    const before = {list: list.writes, figs: figs.writes, r8: row(8), r7: row(7)};
    assert.ok(before.r8 && before.r7, 'each finished session is a row of its own');
    assert.match(before.r8.innerHTML, /\$1\.25/);
    const poll = [...f.intervals.values()].at(-1);
    const asked = () => f.requests.filter(({path}) => path.startsWith('/api/runs')).at(-1).path;

    // Unchanged: the server answers "same"; the page sends back the version and rewrites nothing.
    answer = {v: 'v1', same: true};
    await poll(); await settle();
    assert.equal(asked(), '/api/runs?since=v1');
    assert.equal(list.writes, before.list); assert.equal(figs.writes, before.figs);
    assert.equal(row(8), before.r8); assert.equal(row(7), before.r7);
    assert.match(f.root.querySelector('#rfigs').innerHTML, /27/);  // still the kept answer's figures

    // One session's spend moved: its row alone is rewritten, the others stay the same elements.
    answer = {runs: [runs[0], {...runs[1], spent_usd: 1.5}, runs[2]], counts, policy: null, totals: {tried: 27, passed: 3}, v: 'v2'};
    await poll(); await settle();
    assert.equal(asked(), '/api/runs?since=v1');
    assert.equal(list.writes, before.list, 'the list itself is not rewritten');
    assert.notEqual(row(8), before.r8); assert.match(row(8).innerHTML, /\$1\.50/);
    assert.equal(row(7), before.r7);
    assert.equal(figs.writes, before.figs, 'the figures did not change');

    // A new session changes which rows there are: the list is rewritten, and the next poll sends v3.
    answer = {runs: [run({id: 10, status: 'queued', stop_reason: null, spent_usd: 0, created_at: '2026-10-26T09:00:00Z'}), ...answer.runs],
      counts: {...counts, research_queued: 1}, policy: null, totals: {tried: 27, passed: 3}, v: 'v3'};
    await poll(); await settle();
    assert.equal(asked(), '/api/runs?since=v2');
    assert.equal(list.writes, before.list + 1);
    answer = {v: 'v3', same: true};
    await poll(); await settle();
    assert.equal(asked(), '/api/runs?since=v3');
    assert.equal(list.writes, before.list + 1);
    f.clearTimers();
  });
}
