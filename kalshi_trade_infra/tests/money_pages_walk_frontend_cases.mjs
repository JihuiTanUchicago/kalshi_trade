// Shared cases, run against each bundle's offline harness (Tau and Meridian), from a signed-in walk of the money pages
// (Dashboard, Deploy, a deployed strategy, Funds, Billing, Settings) at 390px and 1280px in both themes, 2026-10-30,
// with one strategy on paper and on demo:
// - Deploy's paper figure was labelled "Realized" beside "Demo realized": the bare word read as the board's total,
//   demo included. Beside a demo figure it says "Paper realized"; paper alone keeps "Realized".
// - An open position's unrealized P&L on the strategy page and the dashboard gave no time for its mark, where Deploy's
//   says "as of 05:31 UTC": with the engine stopped, a mark hours old read as this minute's. Each says when its mark
//   was read, and a position with no mark yet says so with no time.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const MARKETS = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes'}];
// Today's time alone, or another day's date with it, always with a zone (settleAt).
const AT = '(?:[A-Z][a-z]{2} \\d{1,2}, )?\\d\\d:\\d\\d \\S+';
const pos = (extra) => ({title: 'Fade', ticker: 'KXBTC15M-26OCT301815-15', side: 'yes', qty: 12, entry_price: .41, entry_fee: .17, cost: 5.09,
  at_cost: 4.92, mark: .47, value: 5.64, unrealized: .55, mark_ts: new Date(Date.now() - 3 * 3600e3).toISOString(), mode: 'paper', deployment_id: 1,
  opened_at: '2026-10-30T05:20:00Z', market_close_time: new Date(Date.now() + 9 * 60e3).toISOString(), ...extra});
const markClock = (iso) => { const d = new Date(iso); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };

export function moneyPagesWalkCases({name, frontend, strategyFrontend, detailStrategy, dashboard}) {
  test(`${name}: Deploy's paper realized figure says Paper beside a demo one, and Realized alone`, async () => {
    const dep = (id, mode, pnl) => ({id, strategy_id: 3, title: 'Fade', market: 'btc15m', mode, status: 'running', status_reason: null,
      realized_pnl: pnl, closed_trades: 2, open_positions: 1, unrealized_pnl: null, created_at: '2026-10-30T05:00:00Z', curve: [], stake: 5,
      max_positions: 20, backtest: {out_of_sample: null}});
    const figs = async (deployments) => {
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/deployments') ? response({open_positions: [], deployments}) : response({})});
      f.location.pathname = '/deploy';
      await f.viewDeploy(); await settle(); if (f.clearTimers) f.clearTimers();
      return f.root.querySelector('#dfigs').innerHTML.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ');
    };
    const both = await figs([dep(1, 'paper', 5.08), dep(2, 'demo', 2.14)]);
    assert.match(both, /Paper realized, deployments listed below \+\$5\.08 paper money, not real/);
    assert.match(both, /Demo realized, deployments listed below \+\$2\.14/);
    // Never one figure across the two books.
    assert.doesNotMatch(both, /\$7\.22/);
    const paper = await figs([dep(1, 'paper', 5.08)]);
    assert.match(paper, /Realized, deployments listed below \+\$5\.08 paper money, not real/);
    assert.doesNotMatch(paper, /Paper realized/);
  });

  test(`${name}: the strategy page's holding says when its unrealized figure was marked, and an unmarked one gives no time`, async () => {
    const marked = pos({id: 1}), demo = pos({id: 2, mode: 'demo', qty: 5, cost: 2.17, unrealized: .13, mark_ts: new Date(Date.now() - 50e3).toISOString()});
    const unmarked = pos({id: 3, unrealized: null, mark: null, value: null, mark_ts: null});
    const f = strategyFrontend(detailStrategy({holdings: [demo, marked, unmarked]}), () => response({})); f.S.me.markets = MARKETS;
    await f.viewStrategy(42); await settle();
    const lines = f.root.querySelectorAll('.holdlist .holdlist-figs').map((el) => el.textContent.replace(/\s+/g, ' '));
    assert.equal(lines.length, 3);
    assert.match(lines[0], new RegExp('Unrealized \\+\\$0\\.13 as of ' + AT));
    assert.match(lines[1], new RegExp('Unrealized \\+\\$0\\.55 as of ' + AT));
    assert.ok(lines[1].includes(markClock(marked.mark_ts) + ' '), 'the mark three hours ago gives its own time, not now');
    assert.match(lines[2], /Unrealized not marked yet/);
    assert.doesNotMatch(lines[2], /as of/);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: the dashboard's open position says when its unrealized figure was marked; an unmarked one gives no time`, async () => {
    const marked = pos({id: 1}), unmarked = pos({id: 2, ticker: 'KXBTC15M-26OCT301830-30', side: 'no', unrealized: null, mark: null, value: null, mark_ts: null});
    const data = {...dashboard(), open_positions: [marked, unmarked], recent_closed: []};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.markets = MARKETS;
    await f.viewDashboard(); await settle();
    const stubs = f.root.querySelectorAll('#dash-open .stub');
    let texts;
    if (stubs.length) {
      // Tau: one panel line a position; its worth's time rides on its small line.
      texts = stubs.map((el) => el.textContent.replace(/\s+/g, ' '));
      assert.match(texts[0], new RegExp('worth \\$5\\.64 \\(\\+\\$0\\.55\\)[\\s\\S]*worth as of ' + AT));
    } else {
      // Meridian: the Overview's positions table; the time sits under the Unrealized P&L.
      texts = f.root.querySelectorAll('tr.open-position').map((el) => el.textContent.replace(/\s+/g, ' '));
      assert.match(texts[0], new RegExp('\\+\\$0\\.55 ?as of ' + AT));
    }
    assert.equal(texts.length, 2);
    assert.ok(texts[0].includes(markClock(marked.mark_ts) + ' '));
    assert.doesNotMatch(texts[1], /as of/);
    if (f.clearTimers) f.clearTimers();
  });
}
