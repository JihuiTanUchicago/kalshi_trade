// Shared cases, run against each bundle's offline harness (Tau and Meridian), from a money-trust walk as a user
// with paper and demo books, closed trades and open positions (390px and 1280px, both themes, 2026-10-28):
// - The track record's By strategy table read "−$0.00" as the Avg trade of a strategy $0.004 down over two trades,
//   beside its "$0.00" Net P&L: a sign on a figure that reads as no money, and its tint said a loss. Every
//   amount's sign (and tint) is now the shown amount's, rounded as shown; a share's too ("−0.0%").
// - A market page totalled each book's closed trades by adding their P&L floats in the browser: −0.0036 and
//   −0.1314 (−0.1350 exactly, but −0.13499999… as floats) read "realized −$0.13" beside the track record's −$0.14
//   for the same two trades.
//   It sums the stored 4-place amounts exactly, then rounds once, half up (trading_core/domain/money.py).
// - Deploy's "Demo realized" (every closed trade of the demo deployments listed: +$1.00) sat beside a dashboard
//   and Funds reading "+$1.24 realized since reload" for the same book, with nothing saying why. It says a
//   demo reload doesn't reset it.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const TH = {min_sharpe_days: 14, min_trades: 30};
const text = (html) => html.replace(/<[^>]*>/g, '').replace(/⁠/g, '');

export function moneyAgreementCases({name, frontend, marketPage = true}) {
  test(`${name}: a fraction of a cent either way reads $0.00 with no sign and no loss tint, on every track record figure`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = (o) => ({strategy_id: 4, title: 'Fade', market: 'btc_daily', trades: 2, open_trades: 0, net_pnl: 0, win_rate: 0.5,
      avg_trade: -0.002, max_drawdown: 0.5, last_trade_at: 1790000000, edge: 'thin', status: 'paused', removed: false, ...o});
    const m = {trades: 4, wins: 2, losses: 2, label: 'Paper', net_pnl: -0.004, fees: 0.28, curve: [], days: 3,
      avg_trade: -0.001, return: -0.0001, capital: 4.1, max_drawdown: 0.5, max_drawdown_pct: 0.12,
      monthly: [{month: '2026-10', pnl: -0.004, trades: 4, win_rate: 0.5}],
      sample: {level: 'thin', edge: 'unclear', text: 'Too early to judge.'},
      strategies: [row({}), row({strategy_id: 5, title: 'Drift', avg_trade: 0.004, net_pnl: 0.008, status: 'running'})]};
    const html = f.trackRecordPanel(m, 'paper', TH);
    const shown = text(html);
    assert.doesNotMatch(shown, /[−+-]\$0\.00/);
    assert.doesNotMatch(shown, /[−+-]0\.0%/);
    // The lead figures: no tint on a figure that shows no money or no return.
    assert.match(html, /<dt class="lab">Avg trade<\/dt><dd><span class="fig ">\$0\.00<\/span>/);
    assert.match(html, /<dt class="lab">Return<\/dt><dd><span class="fig ">0\.0%<\/span>/);
    // Net P&L in the tables: $0.00, not coloured as a gain or a loss.
    assert.doesNotMatch(html, /<span class="(?:gain|loss)">\$0\.00<\/span>/);
    // A real amount keeps its sign and tint.
    const loss = f.trackRecordPanel({...m, avg_trade: -0.25, net_pnl: -1, strategies: [row({avg_trade: -0.25, net_pnl: -0.5})]}, 'paper', TH);
    assert.match(loss, /<dt class="lab">Avg trade<\/dt><dd><span class="fig tint neg">−\$0\.25<\/span>/);
    assert.match(loss, /<span class="loss">−\$0\.50<\/span>/);
  });

  if (marketPage) {
    test(`${name}: a market page totals a book's closed trades to the cent the track record shows, half up`, async () => {
      const closed = (pnl, id) => ({id, mode: 'paper', strategy_id: 4, title: 'Fade', side: 'no', qty: 4, entry_price: 0.45, cost: 1.87,
        status: 'closed', pnl, exit_price: 0.4, close_reason: 'settled', market_close_time: '2026-10-26T21:00:00Z'});
      const page = {ticker: 'KXBTCD-26OCT2617-T113499.99', series: 'KXBTCD', title: 'Bitcoin price at 5pm EDT?', status: 'active',
        yes_bid: '0.55', yes_ask: '0.57', last: '0.55', points: [], period_min: 1, as_of: '2026-10-26T11:00:00Z',
        mine: {open: [], closed: [closed(-0.0036, 1), closed(-0.1314, 2)]}};
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(page) : response({})});
      f.S.me.markets = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET'}];
      await f.viewMarketDetail(page.ticker); await settle();
      const shown = text(f.root.innerHTML);
      assert.match(shown, /2 closed\s·\s+realized −\$0\.14/);
      assert.doesNotMatch(shown, /realized −\$0\.13/);
    });
  }

  test(`${name}: Deploy's demo realized says a demo reload doesn't reset it, so it can differ from the demo book's figure`, async () => {
    const dep = (o) => ({id: 1, strategy_id: 1, title: 'Fade', market: 'btc15m', mode: 'demo', status: 'running', status_reason: null,
      realized_pnl: 1, closed_trades: 5, open_positions: 1, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z',
      curve: [], stake: 5, max_positions: 4, backtest: {out_of_sample: null}, ...o});
    const board = async (body) => {
      const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({open_positions: [], ...body}) : response({})});
      f.location.pathname = '/deploy';
      await f.viewDeploy(); await settle();
      f.clearTimers();
      return text(f.root.querySelector('#dfigs').innerHTML);
    };
    const traded = await board({deployments: [dep({}), dep({id: 2, mode: 'paper', realized_pnl: 3.71, closed_trades: 12})],
      realized_by_book: {demo: {listed: 1, removed: 0, removed_deployments: 0}, paper: {listed: 3.71, removed: 0, removed_deployments: 0, all: 3.71}}});
    assert.match(traded, /Demo realized, deployments listed below\+\$1\.00real fills on Kalshi’s sandbox, not real money · after Kalshi fees · a demo reload doesn’t reset it, so it can differ from the demo book’s P&amp;L since reload/);
    // Paper says nothing of a reload; the two books are never summed (+$4.71).
    assert.doesNotMatch(traded.slice(0, traded.indexOf('Demo realized')), /reload/);
    assert.doesNotMatch(traded, /\$4\.71/);
    // A demo book with no closed trade yet has no figure to explain.
    const fresh = await board({deployments: [dep({realized_pnl: 0, closed_trades: 0})], realized_by_book: {demo: {listed: 0, removed: 0, removed_deployments: 0}}});
    assert.match(fresh, /None yet/);
    assert.doesNotMatch(fresh, /reload/);
  });
}
