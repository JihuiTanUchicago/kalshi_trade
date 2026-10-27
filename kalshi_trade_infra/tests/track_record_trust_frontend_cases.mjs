// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): what a Bitcoin trader deciding
// whether to trust the dashboard's track record needs it to say. Its figures reconcile with the realized P&L every other
// page shows for the same book.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const TH = {min_sharpe_days: 14, min_trades: 30};
const plain = (html) => html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ');
const stratRow = (o) => ({strategy_id: 3, title: 'Fade the 15-minute Bitcoin overshoot', market: 'btc15m', trades: 26, open_trades: 1,
  net_pnl: 69.51, win_rate: 0.692, avg_trade: 2.67, max_drawdown: 18.58, last_trade_at: 1793000000, edge: 'thin', status: 'running',
  removed: false, excluded_instant_fills: 0, excluded_instant_pnl: 0, ...o});
export const paperBook = (o = {}) => ({trades: 55, wins: 27, losses: 28, label: 'Paper', net_pnl: -24.72, fees: 14.37, gross_pnl: -10.35,
  return: -0.209, capital: 118.51, max_drawdown: 102.81, max_drawdown_pct: 0.868, sharpe: -1.22, sortino: -1.51, psr: 0.365,
  win_rate: 0.491, win_rate_ci: [0.364, 0.619], avg_trade: -0.45, avg_trade_ci: [-2.56, 1.66], profit_factor: 0.89,
  first_trade_at: 1790800000, days: 28, open_trades: 2, open_cost: 12.9, open_realized_pnl: 0, excluded_instant_fills: 1, excluded_instant_pnl: 4.82,
  curve: [[1790800000, -5.28], [1791500000, 78.09], [1793000000, -24.72]], underwater: [[1790800000, -5.28], [1791500000, 0], [1793000000, -102.81]],
  monthly: [{month: '2026-10', pnl: -19.44, trades: 54, win_rate: 0.5}], current_drawdown: 102.81, longest_drawdown_days: 16.1,
  sample: {level: 'early', edge: 'unclear', text: 'Early read: 55 trades over 27 days.'},
  strategies: [stratRow({excluded_instant_fills: 1, excluded_instant_pnl: 4.82}), stratRow({strategy_id: 5, title: 'Bitcoin daily strike drift',
    trades: 9, open_trades: 0, net_pnl: -21.04})], ...o});

export function trackRecordTrustCases({name, frontend}) {
  test(`${name}: the track record says what its left-out instant fills made, so it meets the realized P&L on every other page`, () => {
    // The paper card said "−$19.90 realized all time" above a record of −$24.72 for the same book, and the strategy list
    // "+$74.33 · 27 trades" beside the record's +$69.51 on 26: the gap was one instant fill's +$4.82, named nowhere.
    const f = frontend({fetchImpl: () => { throw new Error('offline'); }});
    const html = f.trackRecordPanel(paperBook(), 'paper', TH);
    const cav = plain(html.match(/<p class="hint tr-caveat">[\s\S]*?<\/p>/)[0]);
    assert.match(cav, /1 instant-fill paper trade left out \(fills real execution would not get\): \+\$4\.82\. The realized P&L on the dashboard, Funds and Deploy counts it, so it reads \$4\.82 higher than this record\./);
    // A loss left out reads the other way; none made or lost says nothing more.
    const lost = plain(f.trackRecordPanel(paperBook({excluded_instant_fills: 2, excluded_instant_pnl: -3.1}), 'paper', TH));
    assert.match(lost, /2 instant-fill paper trades left out \(fills real execution would not get\): −\$3\.10\. The realized P&L on the dashboard, Funds and Deploy counts them, so it reads \$3\.10 lower than this record\./);
    const flat = plain(f.trackRecordPanel(paperBook({excluded_instant_pnl: 0}), 'paper', TH));
    assert.match(flat, /1 instant-fill paper trade left out \(fills real execution would not get\)\. 2 open trades/);
    // The strategy's own row says its share, beside its 26 trades; a row with none left out says nothing.
    const rows = html.match(/<tr><td class="name" data-lab="Strategy">[\s\S]*?<\/tr>/g);
    assert.match(rows[0], /Fade the 15-minute Bitcoin overshoot<\/a><div class="sub-fig">1 instant fill left out \(\+\$4\.82\)<\/div><\/td>/);
    assert.doesNotMatch(rows[1], /left out/);
  });
}
