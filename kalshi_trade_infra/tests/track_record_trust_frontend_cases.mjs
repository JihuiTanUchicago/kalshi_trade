// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): what a Bitcoin trader deciding
// whether to trust the dashboard's track record needs it to say. Its figures reconcile with the realized P&L every other
// page shows for the same book.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

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

export function trackRecordTrustCases({name, frontend, Element, dashboard}) {
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

  test(`${name}: a strategy whose only paper trades were instant fills has its own row, saying so, outside the record's figures`, () => {
    // Its trades were named only in the book's caveat: the by-strategy table had no row for it at all.
    const f = frontend({fetchImpl: () => { throw new Error('offline'); }});
    const only = stratRow({strategy_id: 8, title: 'Bitcoin hourly fade', trades: 0, open_trades: 0, net_pnl: 0, win_rate: null,
      avg_trade: null, avg_trade_ci: null, max_drawdown: 0, last_trade_at: null, excluded_instant_fills: 2, excluded_instant_pnl: 3.81,
      instant_only: true});
    const book = paperBook({excluded_instant_fills: 3, excluded_instant_pnl: 8.63, strategies: [...paperBook().strategies, only]});
    const html = f.trackRecordPanel(book, 'paper', TH);
    const rows = html.match(/<tr><td class="name" data-lab="Strategy">[\s\S]*?<\/tr>/g);
    assert.equal(rows.length, 3);
    const row = plain(rows[2]);
    assert.match(rows[2], /Bitcoin hourly fade<\/a><div class="sub-fig">All 2 of its trades were instant fills, left out of this record \(\+\$3\.81\)<\/div><\/td>/);
    assert.match(rows[2], /<td data-lab="Read"><span class="mk quiet">Left out<\/span><\/td>/);
    assert.match(row, /Not in the record/);
    assert.doesNotMatch(row, /Too few|\$0\.00/, 'no figure reads as a record of $0 on 0 trades');
    // One fill reads as one; the book's headline figures are the record's alone.
    const one = plain(f.trackRecordPanel(paperBook({strategies: [stratRow({...only, excluded_instant_fills: 1, excluded_instant_pnl: -1.2})]}), 'paper', TH));
    assert.match(one, /Its only trade was an instant fill, left out of this record \(−\$1\.20\)/);
    assert.match(plain(html), /Paper net P&L −\$24\.72/);
  });

  test(`${name}: the track record says when its figures were worked out, in its head, and when its minute poll stops landing`, async () => {
    // The read time sat at the foot of the closed "How these numbers are computed" note, so a record its poll could no
    // longer refresh read as current.
    const at = Date.UTC(2026, 9, 27, 17, 31) / 1000;
    const tr = {generated_at: at, default_mode: 'paper', method: ['A trade is one entry fill.'], thresholds: TH,
      modes: {live: {trades: 0, label: 'Live money'}, demo: {trades: 0, label: 'Kalshi demo'}, paper: paperBook()}};
    let failTrack = false;
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response(dashboard())
      : path === '/api/track-record' ? (failTrack ? response({error: 'Tau is restarting.'}, 500) : response(tr))
        : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
    Object.defineProperty(Element.prototype, 'parentNode', {get() { return this.parent; }, configurable: true});
    try {
      await f.viewDashboard(); await settle();
      const host = f.root.querySelector('#track-record');
      const head = host.querySelector('.section-head').innerHTML;
      const when = new Date(at * 1000);
      const hhmm = `${String(when.getHours()).padStart(2, '0')}:${String(when.getMinutes()).padStart(2, '0')}`;
      assert.match(head, new RegExp(`<span class="tr-asof">Figures as of [^<]*${hhmm}[^<]*</span>`));
      assert.doesNotMatch(host.querySelector('.tr-method').innerHTML, /Updated/, 'said once, where it is read');
      const note = () => f.document.getElementById('tr-stale');
      assert.equal(note().textContent, '');
      // The record's minute poll fails for a while: the line under the tabs says how old the figures are.
      failTrack = true;
      f.shiftClock(5 * 60000);
      for (let i = 0; i < 2; i++) { for (const tick of [...f.intervals.values()]) tick(); await settle(); }  // the next minute's tick
      assert.match(note().textContent, /^Last updated 5m ago, retrying$/);
    } finally {
      delete Element.prototype.parentNode;
      f.clearTimers();
    }
  });

  test(`${name}: a return says the period it is over, on the track record and on the Strategies list`, () => {
    const f = frontend({fetchImpl: () => { throw new Error('offline'); }});
    // The record's Return read "−20.9% on $118.51 capital required", with its period only on the P&L figure beside it.
    const ret = plain(f.trackRecordPanel(paperBook({span_days: 27.4}), 'paper', TH)).match(/Return −20\.9% ([^]*?) Max drawdown/)[1];
    assert.equal(ret, 'on $118.51 capital required over 27 days');
    assert.match(plain(f.trackRecordPanel(paperBook({span_days: 0.2}), 'paper', TH)), /on \$118\.51 capital required over 1 day /);
    // A strategy's backtest P&L on the list said "on unseen data" beside a win rate, over no stated span.
    const s = {id: 3, title: 'Fade the 15-minute Bitcoin overshoot', thesis: 'A rule.', market: 'btc15m', direction: 'both', status: 'passed',
      out_of_sample: {pnl: 6.2, trades: 48, win_rate: 0.58, days: 30.2}, in_sample: {pnl: 21, trades: 120, win_rate: 0.61, days: 90}};
    assert.match(f.strategySlip(s, {}), /<div class="sub-fig">on unseen data over 30 days<\/div>/);
    assert.match(f.strategySlip({...s, out_of_sample: null}), /<div class="sub-fig">on the history it searched over 90 days<\/div>/);
    assert.match(f.strategySlip({...s, out_of_sample: {...s.out_of_sample, days: null}}), /<div class="sub-fig">on unseen data<\/div>/);
  });

  test(`${name}: the equity curve labels its break-even line when the record has been both above and below it`, () => {
    // The track record's curve read "$78.09 / $26.69 / −$24.72" beside an unlabelled grey line: where $0 sat was a guess.
    const f = frontend({fetchImpl: () => { throw new Error('offline'); }});
    const svg = f.equityChart(paperBook().curve, null, null, {width: 760});
    const labels = [...svg.matchAll(/<text[^>]*text-anchor="end">([^<]*)<\/text>/g)].map((m) => m[1]);
    assert.deepEqual(labels.slice(0, 3), ['−$24.72', '$26.69', '$78.09']);
    const zero = svg.match(/<text class="chart-zero" x="44" y="([\d.]+)" text-anchor="end">\$0<\/text>/);
    assert.ok(zero, 'the $0 line is labelled');
    // On the zero line itself: the label sits where the grey line is drawn.
    const lineY = +svg.match(/<line x1="52" x2="750" y1="([\d.]+)" y2="[\d.]+" stroke="var\(--rule-2\)"\/>/)[1];
    assert.ok(Math.abs(+zero[1] - (lineY + 4)) < 0.01, `${zero[1]} vs ${lineY}`);
    // Never on a curve that stays on one side (its low or high tick is $0 then), nor crowding a tick next to it.
    assert.doesNotMatch(f.equityChart([[1, 0], [2, 5], [3, 12]], null, null, {width: 760}), /chart-zero/);
    assert.doesNotMatch(f.equityChart([[1, -0.4], [2, 60], [3, 80]], null, null, {width: 760}), /chart-zero/);
  });
}
