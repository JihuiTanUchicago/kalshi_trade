// Shared cases from a new customer's first week, run against each bundle's offline harness (Tau and Meridian).
// Walk 2026-10-31, five stages from sign-up to a Kalshi demo key: on day 4 the dashboard read "Today (UTC): $0.00
// realized" with the last paper trade two days back, as if today's trading had broken even, and its strip read
// "Paper: no trades closed yet" over four closed trades; on day 6 Road to live read "Paper earns 832% of the backtest's
// P&L per trade" on 7 trades, beside "too early to tell against the backtest". Display only: every figure is the
// server's, unchanged.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const text = (html) => html.replace(/<button[\s\S]*?<\/button>/g, '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
const DAY = 864e5;
const dayStart = () => Math.floor(Date.now() / DAY) * DAY;
const iso = (ms) => new Date(ms).toISOString();
const closed = (mode, at, extra = {}) => ({id: Math.round(at / 1000) % 100000, ticker: 'KXBTC15M-26OCT290145-45', title: 'Late-rush fade',
  side: 'yes', qty: 5, entry_price: 0.4, mode, pnl: 0.5, market_close_time: iso(at), opened_at: iso(at - 9 * 60e3), closed_at: iso(at), ...extra});

export function firstWeekCases({name, frontend, dashboard, detailStrategy, strategyFrontend}) {
  const tau = name === 'Tau';
  const dep = {id: 2, strategy_id: 11, title: 'Late-rush fade', market: 'btc15m', mode: 'paper', status: 'running', stake: 5, max_positions: 20,
    realized_pnl: 0.57, unrealized_pnl: null, closed_trades: 4, open_positions: 0, curve: [], created_at: iso(dayStart() - 4 * DAY)};
  const board = (recent, paper = {}) => {
    const base = dashboard();
    return {...base, deployments: [dep], recent_closed: recent,
      paper: {...base.paper, equity: 1000.57, cash: 1000.57, open_at_cost: 0, open_positions: 0, total_pnl: 0.57, realized_pnl: 0.57,
        closed_trades: recent.filter((r) => r.mode === 'paper').length, today_pnl: 0, ...paper}};
  };
  const paperToday = async (data) => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({messages: [], models: []});
    }});
    await f.viewDashboard(); await settle();
    const all = text(f.root.querySelector('.figures').innerHTML);
    if (f.clearTimers) f.clearTimers();
    const m = tau ? /Today \(UTC\): ([^·]*?)(?: after| Strategy|$)/.exec(all) : /Today \(UTC\): paper realized (\S+(?: yet)?)/.exec(all);
    assert.ok(m, all);
    return m[1].trim();
  };

  test(`${name}: a day with no paper trade closed yet says so, never "$0.00 realized" for today`, async () => {
    const twoDays = dayStart() - 2 * DAY + 3600e3;
    const older = [closed('paper', twoDays), closed('paper', twoDays - 8 * 3600e3), closed('paper', twoDays - 16 * 3600e3), closed('paper', twoDays - 24 * 3600e3)];
    // Every paper trade is listed and none closed today.
    assert.equal(await paperToday(board(older)), tau ? 'no trades closed yet' : 'None yet');
    // More paper trades than are listed, but the oldest listed row closed before today: none today either.
    assert.equal(await paperToday(board(older, {closed_trades: 40})), tau ? 'no trades closed yet' : 'None yet');
  });

  test(`${name}: a paper trade closed today keeps the day's figure, even one that broke even, and a list that can't tell keeps it too`, async () => {
    const today = [closed('paper', dayStart()), closed('paper', dayStart() - DAY)];
    assert.match(await paperToday(board(today)), tau ? /^\$0\.00 realized,$/ : /^\$0\.00$/);
    assert.match(await paperToday(board(today, {today_pnl: 1.25})), tau ? /^\+\$1\.25 realized,$/ : /^\+\$1\.25$/);
    // The twelve newest closed trades are all another book's and all closed today, with older paper trades unlisted: the
    // page can't tell, so the server's figure stands.
    const busy = Array.from({length: 12}, (_, i) => closed('demo', dayStart() + i * 1000));
    assert.match(await paperToday(board(busy, {closed_trades: 4})), tau ? /^\$0\.00 realized,$/ : /^\$0\.00$/);
  });

  test(`${name}: the strip's book with trades closed before the window says "no trades closed", a new one "…yet"`, async () => {
    const f = frontend({fetchImpl: () => response({messages: [], models: []})});
    const since = {at: iso(dayStart() - DAY), first: true, books: {paper: {pnl: 0, trades: 0}}, passed: {n: 0, items: []}, autopilot: {}, runs: {}};
    const strip = (closedTrades) => f.sinceStrip({...board([]), paper: {...board([]).paper, closed_trades: closedTrades}, since}, '#dash-deps');
    assert.match(strip(4), /<span class="since-book" data-book="paper"><b>Paper<\/b>: no trades closed<\/span>/);
    assert.match(strip(0), /<span class="since-book" data-book="paper"><b>Paper<\/b>: no trades closed yet<\/span>/);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: Road to live leaves out the share of the backtest's P&L while the paper book is too early to compare`, async () => {
    const road = {ready: false, deployment_candidate: true, live_autopilot: {ok: false},
      paper: {trades: 7, trades_needed: 30, net_pnl: 1.91, events: 7, events_needed: 20, span_hours: 48, span_needed_hours: 48,
        p_value: null, p_value_needed: 0.1, recent_trades: 3, recent_net_pnl: 0.52, realization: 8.32, demo_orders: 0, demo_orders_needed: 20,
        checks: {realistic_trades: false, net_pnl: true, events: false, span: true, edge: false, recent: true, demo: false}}};
    const bt = (verdict, trades) => ({mode: 'paper', trades, verdict, per_trade: 0.27, win_rate: 0.57, backtest_per_trade: 0.03,
      line: verdict === 'early' ? `On paper: ${trades} completed trades so far across all its paper runs, realistic fills only; too early to tell against the backtest (it takes about 10).` : 'Ahead of its backtest on paper.'});
    const body = async (checks) => {
      const f = strategyFrontend(detailStrategy({status: 'passed', backtest_checks: checks}), (path) => response(path === '/api/strategies/42/live-readiness' ? road : {}));
      await f.viewStrategy(42); await flush(); await flush();
      const html = f.root.querySelector('#road-live-body').innerHTML;
      if (f.clearTimers) f.clearTimers();
      return html;
    };
    const early = await body([bt('early', 7)]);
    assert.match(early, /Realistic paper trades/);
    assert.doesNotMatch(early, /Paper earns|832%/);
    // Once the book has enough trades to compare, the hint is back.
    assert.match(await body([bt('ahead', 12)]), /Paper earns <b>832%<\/b> of the backtest/);
    // An older server that sends no backtest checks keeps it as before.
    assert.match(await body(undefined), /Paper earns <b>832%<\/b> of the backtest/);
  });
}
