// Shared cases from the Tau-vs-Meridian fact audit (walk 2026-10-31), run against each bundle's offline harness. One rich
// account (paper and demo books, the demo copy paused by its loss guard, a deployed pass in a finished session) read in
// both themes at 390 and 1366 px, and the facts each page said compared:
// - the dashboard's demo card said only "realized all time" while the server sent the demo book's today_pnl, which the
//   paper card's "Today (UTC)" line and the live book's figure both say for theirs (neither theme said demo's);
// - Tau's finished session row for a deployed pass said its paper record only, where Meridian's session table said its
//   demo book too ("Demo: -$14.99 · 8 trades"), and a demo-only or live record not at all;
// - a demo book paused by its loss guard read as running on the Strategies list and the session page, in both themes:
//   "On paper + demo" over "Demo: -$14.99 · 8 trades", beside a dashboard saying "1 paused, needs you".
// Display only: every figure is the server's, unchanged, and no book is added to another.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const text = (html) => html.replace(/<button[\s\S]*?<\/button>/g, '').replace(/<[^>]*>/g, ' ').replace(/⁠/g, '').replace(/\s+/g, ' ').trim();
const DAY = 864e5;
const dayStart = () => Math.floor(Date.now() / DAY) * DAY;
const iso = (ms) => new Date(ms).toISOString();
const closed = (mode, at, extra = {}) => ({id: Math.round(at / 1000) % 100000, ticker: 'KXBTC15M-26OCT290145-45', title: 'Late-rush fade',
  side: 'yes', qty: 6, entry_price: 0.42, mode, pnl: -2.66, market_close_time: iso(at), opened_at: iso(at - 9 * 60e3), closed_at: iso(at), ...extra});

export function themeFactsCases({name, frontend, dashboard}) {
  const dep = (mode, extra = {}) => ({id: mode === 'demo' ? 4 : 2, strategy_id: 5, title: 'Late-rush fade', market: 'btc15m', mode, status: 'running',
    stake: 5, max_positions: 4, realized_pnl: mode === 'demo' ? -14.99 : 3.31, unrealized_pnl: null, closed_trades: mode === 'demo' ? 8 : 13,
    open_positions: 0, curve: [], created_at: iso(dayStart() - 9 * DAY), ...extra});
  const board = (demo, recent) => {
    const base = dashboard();
    return {...base, deployments: [dep('paper'), dep('demo', {status: 'paused', status_reason: 'Lost $14.99, more than the $10.00 guard.'})],
      recent_closed: recent,
      paper: {...base.paper, equity: 1003.31, cash: 1003.31, open_at_cost: 0, open_positions: 0, total_pnl: 3.31, realized_pnl: 3.31,
        closed_trades: 13, today_pnl: 1.75},
      demo: {closed_trades: 8, open_at_cost: 0, open_cost: 0, open_positions: 0, running: 0, realized_pnl: -14.99, capital: 1000,
        equity: 985.01, total_pnl: -14.99, roi: -0.015, before_reload: 0, health: null, ...demo}};
  };
  const demoCard = async (data) => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({messages: [], models: []});
    }});
    await f.viewDashboard(); await settle();
    if (f.clearTimers) f.clearTimers();
    // The demo card: the figure whose small line names the demo book's capital (Tau's figures band; Meridian's Accounts menu).
    const cards = Array.from(f.root.querySelectorAll('.m')).map((m) => m.innerHTML).filter((h) => /starting capital|capital at last reload/.test(h));
    assert.equal(cards.length, 1, 'one demo card');
    return text(cards[0]);
  };

  test(`${name}: the demo card says the demo book's realized today (UTC), as the paper card says paper's`, async () => {
    const today = [closed('demo', dayStart() + 60e3), closed('paper', dayStart() + 30e3, {pnl: 2.86}), closed('demo', dayStart() - DAY)];
    const card = await demoCard(board({today_pnl: -5.56}, today));
    assert.match(card, /−\$14\.99 realized all time, after Kalshi fees/);
    assert.match(card, /Today \(UTC\): −\$5\.56 realized, after Kalshi fees/);
    // Demo money only: never paper's day (+$1.75), nor the two added (−$3.81).
    assert.doesNotMatch(card, /\$1\.75|\$3\.81/);
  });

  test(`${name}: a demo day with nothing closed yet says so, and a book with no close says no day at all`, async () => {
    const older = Array.from({length: 8}, (_, i) => closed('demo', dayStart() - (i + 1) * DAY));
    const none = await demoCard(board({today_pnl: 0}, older));
    assert.match(none, /Today \(UTC\): no trades closed yet/);
    assert.doesNotMatch(none, /Today \(UTC\): \$0\.00/);
    // A demo trade closed today that broke even keeps its $0.00.
    const even = await demoCard(board({today_pnl: 0}, [closed('demo', dayStart() + 1000, {pnl: 0}), ...older]));
    assert.match(even, /Today \(UTC\): \$0\.00 realized, after Kalshi fees/);
    // Before the book's first close: its P&L line waits, and so does its day.
    const fresh = await demoCard(board({today_pnl: 0, closed_trades: 0, realized_pnl: 0, total_pnl: 0, open_positions: 1, running: 1}, []));
    assert.match(fresh, /P&(amp;)?L shows once a demo trade closes/);
    assert.doesNotMatch(fresh, /Today \(UTC\)/);
    // An answer without the day (an older server) adds nothing.
    assert.doesNotMatch(await demoCard(board({today_pnl: undefined}, older)), /Today \(UTC\)/);
  });

  const AT = '2026-10-25T10:00:00Z';
  const session = async (real) => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9')
      ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: AT, started_at: AT, status: 'succeeded', stop_reason: 'limit',
        hypotheses_tried: 9, strategies_passed: 1}, events: [],
      strategies: [{id: 5, title: 'Late-rush fade', status: 'passed', market: 'btc15m', direction: 'momentum',
        in_sample: {pnl: 6.4, trades: 212}, out_of_sample: {pnl: 2.1, trades: 64, days: 8}, deployed: true,
        books: real.mode === 'paper' && real.demo ? ['paper', 'demo'] : [real.mode], real}]})
      : response({})});
    await f.viewRun(9); f.clearTimers();
    return text((f.root.querySelector('#runideas') || f.root.querySelector('#run-artifacts')).innerHTML);
  };

  test(`${name}: a finished session's deployed pass says its demo book beside its paper record, paused when it is`, async () => {
    const paperDemo = {pnl: 3.31, trades: 13, open: 1, paused: false, live: false, mode: 'paper', demo: {pnl: -14.99, trades: 8, open: 1, paused: true}};
    const said = await session(paperDemo);
    assert.match(said, /Paper since deploying: \+\$3\.31 · 13 trades/);
    assert.match(said, /Demo \(paused\): −\$14\.99 · 8 trades · after Kalshi fees/);
    assert.doesNotMatch(said, /\$11\.68|\$18\.30/);  // paper and demo are never added
    // A running demo book says no pause.
    assert.match(await session({...paperDemo, demo: {pnl: -14.99, trades: 8, open: 1}}), /Demo: −\$14\.99 · 8 trades · after Kalshi fees/);
    // A demo-only record says its book, and never calls itself paper.
    const demoOnly = await session({pnl: -14.99, trades: 8, open: 1, paused: true, live: false, mode: 'demo'});
    assert.match(demoOnly, /−\$14\.99 on demo since deploying · 8 trades · after Kalshi fees/);
    assert.match(demoOnly, /paused/i);
    assert.doesNotMatch(demoOnly, /Paper since deploying/);
  });

  test(`${name}: the Strategies list's demo line says a paused demo book is paused`, async () => {
    const card = {id: 5, title: 'Late-rush fade', thesis: 'Fade the late rush.', status: 'passed', market: 'btc15m', direction: 'momentum',
      in_sample: {pnl: 6.4, trades: 212}, out_of_sample: {pnl: 2.1, trades: 64, days: 8, win_rate: 0.56}, hypotheses_tried: 9, deployed: true,
      books: ['paper', 'demo'], real: {pnl: 3.31, trades: 13, open: 1, paused: false, live: false, mode: 'paper', demo: {pnl: -14.99, trades: 8, open: 1, paused: true}}};
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/strategies') ? response({strategies: [card], matched: 1,
      counts: {total: 1, passed: 1, failed: 0, failed_no_record: 0, not_cleared: 0, rejected: 0}}) : response({}))});
    f.location.pathname = '/strategies'; f.location.search = '';
    await f.viewStrategies(); await settle();
    if (f.clearTimers) f.clearTimers();
    const all = text(f.root.querySelector('#slips').innerHTML);
    assert.match(all, /Demo \(paused\): −\$14\.99 · 8 trades · after Kalshi fees/);
  });
}
