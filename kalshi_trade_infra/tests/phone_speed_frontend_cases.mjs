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

export function phoneSpeedCases({name, frontend, storageFor, railOpenWide, source}) {
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

  test(`${name}: Billing's statement builds its date and count formats once, whatever its length, and reads as toLocaleString did`, async () => {
    const day = (k) => `2026-09-${String(10 + (k % 15)).padStart(2, '0')}`;
    const statement = (n) => ({configured: false, balance: 12.5, spent: 40, spent_7d: 3, spent_24h: 1, pace_days: 7, free_bonus: 20,
      topup_fee_pct: 5.5, cards: [], default_pm: null, auto_reload: false, min_run_balance: 1, spent_7d_by: {},
      math: {days: 30, start: 20, bought: 0, purchases: 0, other: 0, usage: 7.5, end: 12.5}, ledger_cut: false,
      ledger: Array.from({length: n}, (_, k) => ({kind: 'usage', amount: -0.25, memo: 'Model usage', item: 'Research session', model: 'A model',
        calls: 1234 + k, day: day(Math.floor(k / 3)), first_at: `${day(Math.floor(k / 3))}T08:0${k % 3}:00Z`, created_at: `${day(Math.floor(k / 3))}T09:1${k % 3}:00Z`}))});
    // toLocale*String builds a new formatter on every call: count those calls on the page's own dates.
    const made = async (n) => {
      let calls = 0;
      class CountingDate extends Date {
        toLocaleString(...a) { calls++; return super.toLocaleString(...a); }
        toLocaleDateString(...a) { calls++; return super.toLocaleDateString(...a); }
        toLocaleTimeString(...a) { calls++; return super.toLocaleTimeString(...a); }
      }
      const f = frontend({globals: {Date: CountingDate}, fetchImpl: (path) => path.startsWith('/api/billing') ? response(statement(n)) : response({})});
      f.location.pathname = '/billing';
      await f.viewBilling(); await settle();
      f.clearTimers();
      return {built: calls, html: f.root.querySelector('main').innerHTML};
    };
    const short = await made(6), long = await made(300);
    assert.equal(long.built, short.built, 'a longer statement formats no more dates through toLocale*String');
    // The words are the ones toLocale*String gave: the line's clock span and zone, the day's heading, the call count.
    const first = new Date('2026-09-10T08:00:00Z'), last = new Date('2026-09-10T09:10:00Z');
    const clock = {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'};
    assert.ok(long.html.includes(`${first.toLocaleTimeString(undefined, clock)}–${last.toLocaleTimeString(undefined, {...clock, timeZoneName: 'short'})}`));
    const [y, m, dd] = '2026-09-10'.split('-').map(Number);
    assert.ok(long.html.includes(new Date(y, m - 1, dd).toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'})));
    assert.ok(long.html.includes(`${(1234).toLocaleString('en-US')} model calls`));
    // Counts go through one NumberFormat too (Number#toLocaleString('en-US') built one per call).
    assert.doesNotMatch(source, /const num = \(n\) => \(n == null \? '—' : Number\(n\)\.toLocaleString/);
  });
}
