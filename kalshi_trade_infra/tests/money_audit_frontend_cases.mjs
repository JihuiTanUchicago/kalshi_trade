// Shared cases, run against each bundle's offline harness (Tau and Meridian), from the cross-page money audit of
// 2026-10-31: one account with paper, demo and live books (open and closed trades, some marked, a removed deployment,
// a deleted strategy, a paused live run, credits bought and spent) read on every page in both themes at 390px and 1366px.
// Each figure of one quantity must read the same on every page that shows it:
// - The strategy page's per-book holdings line added its rows' rounded costs: two positions of $1.005 with fee read
//   "at cost + fees $2.02" beside the dashboard's, Funds' and the track record's "$2.01" for the same two positions. It
//   says the server's book figure (holdings_books, views._open_book: the exact sum, rounded once).
// - Meridian's Closed P&L added each day's P&L as floats: -$0.1315 and -$0.6135 read -$0.74 beside the dashboard's and
//   Funds' -$0.75 (and -$0.0036, -$0.1314 read -$0.13 beside -$0.14). It sums them exactly (sum4) before rounding once.
// - Meridian's "Recently closed 7 paper · 2 demo · 3 live" counted only the latest 12 closed trades, beside the track
//   record's 14, 3 and 5 for the same books. When the books hold more than the list shows, it says "latest 12: …".
// test_cross_page_money_db.py pins the server's side of the same figures against a real MySQL.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const text = (html) => String(html).replace(/<[^>]*>/g, '').replace(/⁠/g, '').replace(/\s+/g, ' ');

export function moneyAuditCases({name, frontend, strategyFrontend, detailStrategy, dashboard}) {
  test(`${name}: the strategy page's holdings line says each book's open cost as the dashboard and Funds do`, async () => {
    // Two paper positions of 3 x 31.5¢ + 6¢ fee: $1.005 each, so each row reads $1.01 and the book $2.01 (not $2.02).
    const held = (id, extra = {}) => ({id, ticker: `KXBTC15M-26OCT311245-4${id}`, side: 'no', qty: 3, entry_price: 0.315, mode: 'paper',
      cost: 1.01, at_cost: 0.95, mark: 0.6, value: 1.2, unrealized: 0.19, mark_ts: new Date(Date.now() - 30e3).toISOString(),
      market_close_time: new Date(Date.now() + 9 * 60e3).toISOString(), ...extra});
    const live = held(3, {mode: 'live', qty: 2, entry_price: 0.4805, cost: 0.99, at_cost: 0.96, unrealized: 0.22});
    const f = strategyFrontend(detailStrategy({holdings: [held(1), held(2), live],
      holdings_books: {paper: {open_positions: 2, open_at_cost: 1.89, open_cost: 2.01}, live: {open_positions: 1, open_at_cost: 0.96, open_cost: 0.99}}}),
    () => response({}));
    f.S.me.markets = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes'}];
    await f.viewStrategy(42); await settle();
    const line = text(f.root.querySelectorAll('p.hint').map((el) => el.innerHTML).find((h) => /open position/.test(h)) || '');
    assert.match(line, /Paper: 2 open positions at cost \+ fees \$2\.01/);
    assert.doesNotMatch(line, /\$2\.02/);
    // Each book its own figure: live's never added to paper's.
    assert.match(line, /Live: 1 open position at cost \+ fees \$0\.99/);
    assert.doesNotMatch(line, /\$3\.00|\$3\.01/);
    // The rows themselves keep their own rounded cost.
    assert.equal(f.root.querySelectorAll('.holdlist-figs').filter((el) => /Cost \+ fee \$1\.01/.test(text(el.innerHTML))).length, 2);
    if (f.clearTimers) f.clearTimers();
  });

  if (name !== 'Meridian') return;

  test(`${name}: the Closed P&L figure sums its days exactly, as the dashboard's realized figure does`, async () => {
    const data = dashboard({paper: {realized_pnl: -0.14, daily: [{d: '2026-10-29', pnl: -0.0036}, {d: '2026-10-30', pnl: -0.1314}]}});
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/dashboard') ? response(data) : response({autopilot: false, mode: 'off'}))});
    await f.viewDashboard(); await settle(); if (f.clearTimers) f.clearTimers();
    const fig = text(f.root.querySelector('#paper-performance summary strong').innerHTML);
    assert.equal(fig, '−$0.14');
    assert.ok(-0.0036 + -0.1314 > -0.135, 'the floats added read a hair over -0.135, which rounded to -$0.13');
  });

  test(`${name}: Recently closed says its split is the latest trades when the books hold more`, async () => {
    const row = (id, mode) => ({id, ticker: `KXBTC15M-26OCT301200-0${id}`, title: 'Fade', side: 'no', qty: 3, entry_price: 0.4, mode,
      pnl: 0.25, deployment_id: id, market_close_time: '2026-10-30T12:00:00Z', opened_at: '2026-10-30T11:48:00Z', closed_at: '2026-10-30T12:00:00Z'});
    const head = async (closed, rows) => {
      const data = dashboard({paper: {closed_trades: closed.paper}, live: {closed_trades: closed.live}, demo: {closed_trades: closed.demo}, recent_closed: rows});
      const f = frontend({fetchImpl: (path) => (path.startsWith('/api/dashboard') ? response(data) : response({autopilot: false, mode: 'off'}))});
      await f.viewDashboard(); await settle(); if (f.clearTimers) f.clearTimers();
      return text(f.root.querySelector('#recent-settlements > summary').innerHTML);
    };
    const mixed = [row(1, 'paper'), row(2, 'paper'), row(3, 'live')];
    // 14 paper and 5 live closed trades in the books, three listed: the split is the latest three's, and says so.
    assert.match(await head({paper: 14, live: 5, demo: 0}, mixed), /^Recently closed latest 3: 2 paper · 1 live All books$/);
    // One book: "latest 2" and its book.
    assert.match(await head({paper: 14, live: 0, demo: 0}, mixed.slice(0, 2)), /^Recently closed latest 2 Paper$/);
    // Every closed trade listed: the split is the books' counts, as before.
    assert.match(await head({paper: 2, live: 1, demo: 0}, mixed), /^Recently closed 2 paper · 1 live All books$/);
  });
}
