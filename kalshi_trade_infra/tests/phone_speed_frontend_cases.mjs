// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): what a page
// asks the server for while it loads, so a phone on a slow network waits on as few round trips as it can.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const counts = {research_running: 0, research_queued: 0, research_paused: 0};
const runsAnswer = {runs: [], counts, policy: null, totals: {tried: 0, passed: 0}, v: 'v1'};
const researchTransport = (over = {}) => (path) => {
  if (over[path.split('?')[0]]) return over[path.split('?')[0]](path);
  if (path.startsWith('/api/runs')) return response(runsAnswer);
  if (path === '/api/explore/hot') return response({markets: [], at: '2026-10-26T08:00:00Z'});
  if (path === '/api/research/context') return response({markets: []});
  if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
  return response({});
};
const asked = (f, prefix) => f.requests.filter(({path}) => path.startsWith(prefix)).length;

export function phoneSpeedCases({name, frontend, storageFor, railOpenWide}) {
  test(`${name}: hot markets are read once while the rail shows, and not at all while it is hidden`, async () => {
    // Shown: the rail is open on a wide screen. Research paints its shell twice; one read, not two.
    let f = frontend({fetchImpl: researchTransport(), storage: storageFor(new Map(railOpenWide)), matchMedia: () => ({matches: false})});
    f.S.hot = null; f.S.hotAt = 0;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/explore/hot'), 1, 'one read for one page');
    assert.equal(f.S.hot.at, '2026-10-26T08:00:00Z');
    f.clearTimers();

    // Hidden: a phone (Tau hides the rail under 761px) with the rail closed (Meridian hides a closed rail).
    f = frontend({fetchImpl: researchTransport(), storage: storageFor(new Map()), matchMedia: () => ({matches: true})});
    f.S.hot = null; f.S.hotAt = 0;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/explore/hot'), 0, 'nothing on the page shows the snapshot');
    // Nor each minute while it stays hidden: the page's own polls still run.
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.equal(asked(f, '/api/explore/hot'), 0);
    assert.ok(asked(f, '/api/runs') >= 2, 'the session list still polls');
    f.clearTimers();
  });

  test(`${name}: Research asks for the loop's scoreboard beside its session list, not after it`, async () => {
    let answerRuns;
    const runsHeld = new Promise((resolve) => { answerRuns = resolve; });
    const board = {total: {runs: 2, explored: 10, gated: 4, passed: 1, cost_usd: 2, gate_reach_rate: 0.4, pipeline_death_share: 0.5}, days: []};
    const f = frontend({fetchImpl: researchTransport({
      '/api/runs': () => runsHeld.then(() => response(runsAnswer)),
      '/api/research/scoreboard': () => response(board),
    })});
    f.location.pathname = '/research';
    const page = f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/runs'), 1);
    assert.equal(asked(f, '/api/research/scoreboard'), 1, 'asked while the session list is still on its way');
    answerRuns(); await page; await settle();
    assert.equal(asked(f, '/api/research/scoreboard'), 1, 'and read once for the page');
    assert.match(f.root.querySelector('#rsimo').innerHTML, /Ideas tried/, 'the loop card draws the board');
    // The 5s poll draws from the kept board inside the minute: no second read.
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.equal(asked(f, '/api/research/scoreboard'), 1);
    f.clearTimers();
  });
}
