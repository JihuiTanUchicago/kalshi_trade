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
      return {built: calls, html: f.root.querySelector('#main').innerHTML};
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

  test(`${name}: the first render takes the page's first read from the shell, once, and polls as before`, async () => {
    const f = frontend({fetchImpl: researchTransport()});
    f.location.pathname = '/research';
    f.window.__TAU_FIRST__ = [{url: '/api/runs', body: {...runsAnswer, totals: {tried: 41, passed: 4}, v: 'shell'}}];
    await f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/runs'), 0, 'no round trip for what the shell carried');
    assert.match(f.root.querySelector('#rfigs').innerHTML, /41/);
    assert.equal(f.window.__TAU_FIRST__.length, 0, 'taken once');
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.deepEqual(f.requests.filter(({path}) => path.startsWith('/api/runs')).map(({path}) => path), ['/api/runs?since=shell']);
    f.clearTimers();
  });

  test(`${name}: Research draws its loop card in its first render from the board the shell carries`, async () => {
    // Drawn a round trip after the session list, the card pushed the list down the screen (shell_reads.py
    // carries the board while the server keeps one).
    const board = {total: {runs: 2, explored: 10, gated: 4, passed: 1, cost_usd: 2, gate_reach_rate: 0.4, pipeline_death_share: 0.5}, days: []};
    const f = frontend({fetchImpl: researchTransport()});
    f.location.pathname = '/research';
    f.window.__TAU_FIRST__ = [{url: '/api/runs', body: {...runsAnswer, totals: {tried: 10, passed: 1}}}, {url: '/api/research/scoreboard?days=14', body: board}];
    await f.viewResearch();
    assert.match(f.root.querySelector('#rsimo').innerHTML, /Ideas tried/, 'the card is drawn with the list');
    await settle();
    assert.equal(asked(f, '/api/research/scoreboard'), 0, 'no round trip for what the shell carried');
    assert.equal(asked(f, '/api/runs'), 0);
    assert.equal(f.window.__TAU_FIRST__.length, 0, 'both taken once');
    f.clearTimers();
  });

  test(`${name}: Billing draws its figures from the read the shell carries for its time zone, and asks when the zone moved`, async () => {
    const bill = {configured: false, balance: 12.5, spent: 40, spent_7d: 3, spent_24h: 1, pace_days: 7, free_bonus: 20, topup_fee_pct: 5.5,
      cards: [], default_pm: null, auto_reload: false, min_run_balance: 1, spent_7d_by: {}, ledger: [], ledger_cut: false,
      math: {days: 30, start: 20, bought: 0, purchases: 0, other: 0, usage: 7.5, end: 12.5}};
    const tz = new Date().getTimezoneOffset();
    // The shell names the URL from the tau_tz cookie boot.js keeps (shell_reads.py): the page's own URL.
    let f = frontend({fetchImpl: (path) => path.startsWith('/api/billing') ? response(bill) : response({})});
    f.location.pathname = '/billing';
    f.window.__TAU_FIRST__ = [{url: '/api/billing?tz=' + tz, body: {...bill, balance: 31.25}}];
    await f.viewBilling(); await settle();
    assert.equal(asked(f, '/api/billing'), 0, 'no round trip for what the shell carried');
    assert.match(f.root.querySelector('#bfigs').innerHTML, /\$31\.25/);
    assert.equal(f.window.__TAU_FIRST__.length, 0, 'taken once');
    f.clearTimers();
    // The offset changed since the cookie was written (a clock change): another URL, so the page asks.
    f = frontend({fetchImpl: (path) => path.startsWith('/api/billing') ? response(bill) : response({})});
    f.location.pathname = '/billing';
    f.window.__TAU_FIRST__ = [{url: '/api/billing?tz=' + (tz + 60), body: {...bill, balance: 31.25}}];
    await f.viewBilling(); await settle();
    assert.deepEqual(f.requests.filter(({path}) => path.startsWith('/api/billing')).map(({path}) => path), ['/api/billing?tz=' + tz]);
    assert.match(f.root.querySelector('#bfigs').innerHTML, /\$12\.50/);
    f.clearTimers();
  });

  test(`${name}: a carried read is used only for its own URL and only by the first page`, async () => {
    let f = frontend({fetchImpl: researchTransport()});
    f.location.pathname = '/research';
    f.window.__TAU_FIRST__ = [{url: '/api/deployments', body: {deployments: []}}];
    await f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/runs'), 1, 'another URL: the page asks for its own');
    // The first page has gone (a later render): the carried read is dropped, never shown late.
    f.S.gen = 2;
    await f.api('/api/notifications');
    assert.equal(f.window.__TAU_FIRST__, null);
    f.clearTimers();

    // The dashboard asks with ?since= from its visit cookie; the shell names the same URL (shell_reads.py).
    const now = Math.floor(Date.now() / 1000), start = now - 4000;
    const dash = {paper: {equity: 1001.6, cash: 1000, open_at_cost: 1.6, total_pnl: 1.6, closed_trades: 8, open_positions: 0,
      realized_pnl: 3.5, today_pnl: 0, running: 0, daily: []}, live: {connected: false, closed_trades: 0, open_positions: 0, realized_pnl: 0},
    demo: {equity: 1000, capital: 1000, realized_pnl: 0, closed_trades: 0, open_positions: 0}, deployments: [], open_positions: [],
    recent_closed: [], reconcile: [], freshness: {btc: 30, engine: 4}, agents: {research_running: 0, research_queued: 0}, v: 'd1'};
    f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(dash);
      if (path.startsWith('/api/track-record')) return response({modes: {}});
      return researchTransport()(path);
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/';
    f.document.cookie = `tau_visit=${start}.${now - 60}`;  // back within half an hour: the visit goes on from its start
    // With the autopilot status its card draws from, above the figures, at the same time as them.
    const status = {autopilot: false, mode: 'off'};
    f.S.ap = null; f.S.apAt = 0;
    f.window.__TAU_FIRST__ = [{url: '/api/dashboard?since=' + start, body: dash}, {url: '/api/autopilot/status', body: status}];
    await f.viewDashboard(); await settle();
    assert.equal(asked(f, '/api/dashboard'), 0, 'the page asked for the URL the shell carried');
    assert.equal(asked(f, '/api/autopilot/status'), 0);
    assert.equal(f.S.ap, status);
    assert.match(f.root.querySelector('#boardbody').innerHTML + f.root.querySelector('#main').innerHTML, /\$1,001\.60/);
    f.clearTimers();
  });
}
