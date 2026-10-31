// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): every chart a customer
// sees, fed the series a real account produces at its edges. Walked 2026-10-31 on a seeded account (series empty, one
// point, two, flat, all negative, 10,000 points, with gaps, crossing zero, across the November clock change):
// - a market's price history across the clock change labelled its last time "06:00 EDT", an hour that was EST, and
//   drew a straight line across four days without a price, as if it had climbed steadily;
// - a strategy's 10,000-trade backtest and a 10,000-minute price history drew every point (a 117KB line);
// - a research phase that never fell from a high drew "0" and "0.0×" on top of each other; the return distribution's
//   "break-even" ran off the figure ("eak-even") and its axis said nowhere where it ran;
// - a chart's accessible name said at most where it ended (a sparkline that fell to −$40 and came back to +$2 read
//   "+$2.00 over 30 trades"), a strategy with a demo replay said the backtest "ends at" the replay's figure, and the
//   Overview's closed paper chart read its period as "2026-10-03 through 2026-10-31";
// - a 47¢/48¢ flicker filled the hot rail's trace top to bottom, like a 40¢ move;
// - one null or NaN point drew a whole line as "NaN,NaN".
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 8; i++) await flush(); };
const label = (svg) => (svg.match(/aria-label="([^"]*)"/) || [])[1];
const points = (svg) => [...svg.matchAll(/<polyline points="([^"]*)"/g)].map((m) => m[1].split(' ').map((p) => p.split(',').map(Number)));
const texts = (svg) => [...svg.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => m[1].replace(/⁠/g, ''));
const withZone = async (zone, fn) => {
  const was = process.env.TZ;
  process.env.TZ = zone;
  try { return await fn(); } finally { if (was === undefined) delete process.env.TZ; else process.env.TZ = was; }
};

export function chartTrustCases({name, frontend, detailStrategy, strategyFrontend, traces}) {
  test(`${name}: an equity chart leaves out null and NaN points, and draws a 10,000-trade backtest at about two points a pixel`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const holed = f.equityChart([[100, 0], [200, null], [300, NaN], [400, 3], ['x', 2], [500, Infinity], [600, 5]], null, null, {width: 760});
    assert.doesNotMatch(holed, /NaN|Infinity|undefined/);
    assert.equal(points(holed)[0].length, 3);
    assert.match(f.equityChart([[100, null], [200, 3]], null, null, {width: 760}), /Not enough trades to draw an equity curve/);
    // 10,000 trades with one deep dip and one high peak in the middle: the line is thinned, its ends and both extremes
    // stay, and the axis still runs from the dip to the peak.
    const big = Array.from({length: 10000}, (_, i) => [1000 + i * 60, i === 4321 ? -250 : i === 7777 ? 900 : Math.sin(i / 50) * 20]);
    const svg = f.equityChart(big, null, null, {width: 760});
    const line = points(svg)[0], W = 760, L = 52;
    assert.ok(line.length <= 2 * (W - L - 10) + 4 && line.length > 400, String(line.length));
    assert.ok(svg.length < 40000, String(svg.length));
    const ys = line.map((p) => p[1]);
    assert.equal(Math.min(...ys), 30, 'the peak (the top of the axis) is drawn');
    assert.equal(Math.max(...ys), 236 - 26, 'the dip (the bottom of the axis) is drawn');
    assert.equal(line[0][0], L); assert.equal(line[line.length - 1][0], W - 10);
    assert.ok(texts(svg).includes('−$250.00') && texts(svg).includes('$900.00'), texts(svg).join(' | '));
    // The track record's curve (at most 400 points) is drawn point for point, as before.
    const tr = Array.from({length: 400}, (_, i) => [1000 + i * 60, i % 7]);
    assert.equal(points(f.equityChart(tr, null, null, {width: 760}))[0].length, 400);
  });

  test(`${name}: a strategy page's equity chart names its span, start, end, low and high, and a demo replay never sets its end`, async () => {
    const equity = [[1761500000, 0], [1761600000, -4.5], [1761700000, 12.25], [1761800000, 8]];
    const f = strategyFrontend(detailStrategy({equity, status: 'backtest-only', experiment: null}), () => response({}));
    await f.viewStrategy(42); await settle();
    const svg = f.root.querySelector('#equity-wrap').innerHTML;
    const name0 = label(svg);
    assert.match(name0, /^Cumulative profit and loss over the backtest, (?:with a realized Kalshi demo-environment curve, )?from [A-Z][a-z]{2} \d+ to [A-Z][a-z]{2} \d+: starts at \$0\.00, ends at \+\$8\.00; low −\$4\.50 \([A-Z][a-z]{2} \d+\), high \+\$12\.25 \([A-Z][a-z]{2} \d+\)$/);
    assert.doesNotMatch(name0, /⁠|NaN|undefined/);
    // A replay (drawn dashed, anchored to the backtest line) ends elsewhere: the name's "ends at" is the backtest's.
    const withDev = f.equityChart(equity, null, [[1761600000, 0], [1761800000, 30]], {width: 760});
    assert.match(label(withDev), /; ends at \+\$8\.00$/);
    assert.match(label(f.equityChart(equity, null, [[1761600000, 0], [1761800000, 30]], {width: 760, words: true})), /ends at \+\$8\.00; low −\$4\.50/);
    f.clearTimers();
  });

  test(`${name}: the research figures: a phase that never fell says so once, break-even stays inside, each name says the figures`, async () => {
    const experiment = {classification: 'statistically_supported',
      validation: {equity_curve: Array.from({length: 12}, (_, i) => [1761500000 + i * 3600, 0.05 + (i % 3) * 0.01]), n_trades: 12,
        mean_net_return: 0.06, ci_lo: 0.04, ci_hi: 0.08},
      holdout: {equity_curve: [[1761600000, 0.1], [1761603600, -0.3], [1761607200, 0.0]], n_trades: 3, mean_net_return: -0.05},
      folds: [{from_ts: 1761500000, mean_net_return: 0.03, n_trades: 6}, {from_ts: 1761520000, mean_net_return: -0.01, n_trades: 6}]};
    const f = strategyFrontend(detailStrategy({experiment}), () => response({}));
    await f.viewStrategy(42); await settle();
    const figs = f.root.querySelector('.rp-figs');
    const html = figs.innerHTML;
    const find = (re) => (html.match(new RegExp(`<svg class="chart"[^>]*aria-label="${re}[^"]*"[^>]*>[\\s\\S]*?</svg>`)) || [])[0];
    // Underwater: every validation trade made money, so it never fell from a high.
    const under = find('Underwater drawdown plot');
    assert.ok(under, html.slice(0, 400));
    assert.match(label(under), /^Underwater drawdown plot from [A-Z][a-z]{2} \d+ to [A-Z][a-z]{2} \d+; it never fell from a running high$|^Underwater drawdown plot on [A-Z][a-z]{2} \d+; it never fell from a running high$/);
    const ut = texts(under);
    assert.deepEqual(ut.filter((t) => /×|^0$/.test(t)), ['0.0×'], 'one zero label, with its unit');
    assert.ok(ut.includes('No drawdown'));
    // Distribution: every return is above zero, so break-even sits on the left edge; its label stays in the figure,
    // and the axis says where it ends.
    const dist = find('Distribution of');
    assert.match(label(dist), /^Distribution of 12 per-trade net returns, as % of the stake, from \+5\.00% to \+7\.00%; mean \+6\.00%, 90% confidence interval of the mean \+4\.00% to \+8\.00%; the break-even line is at 0%$/);
    const be = dist.match(/<text x="([\d.]+)"[^>]*>break-even<\/text>/);
    assert.ok(be && +be[1] - 'break-even'.length * 3.25 >= 20, dist);
    assert.ok(texts(dist).includes('+8.00%'), texts(dist).join(' | '));
    // Equity by phase and walk-forward: each phase, each slice, in words.
    const phase = find('Running total of net return per trade');
    assert.match(label(phase), /by research phase\. Validation, (?:from|on) [^:]+: starts at \+0\.1×, ends at \+0\.7×; low \+0\.1× \([^)]+\), high \+0\.7× \([^)]+\)\. Holdout, (?:from|on) [^:]+: starts at \+0\.1×, ends at −0\.2×; low −0\.2× \([^)]+\), high \+0\.1× \([^)]+\)$/);
    assert.match(label(find('Average net return per trade')), /in each slice of the validation window: [A-Z][a-z]{2} \d+ \+3\.00% over 6 trades, [A-Z][a-z]{2} \d+ −1\.00% over 6 trades$/);
    assert.doesNotMatch(html, /NaN|undefined|Infinity/);
    f.clearTimers();
  });

  test(`${name}: the track record's underwater figure keeps its own name and its bare "0"`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const svg = f.rpUnderwater([[1761500000, 1], [1761600000, 2], [1761700000, 3]]);
    assert.match(label(svg), /^Underwater drawdown plot from [^;]+; worst drawdown \$0\.00$/);
    assert.ok(texts(svg).includes('0') && !texts(svg).includes('No drawdown'));
    // A null point in a series no longer draws NaN.
    assert.doesNotMatch(f.rpUnderwater([[1761500000, 1], [1761600000, null], [1761700000, 3], [1761800000, 0]]), /NaN/);
  });

  test(`${name}: a deployment's sparkline leaves out a null point and names its book, low and high`, async () => {
    const dep = (id, mode, curve, closed) => ({id, strategy_id: id, title: 'Spark ' + id, market: 'btc15m', mode, status: 'running', stake: 5,
      max_positions: 2, backtest: {out_of_sample: null}, created_at: '2026-10-17T10:00:00Z', realized_pnl: 2, unrealized_pnl: null,
      closed_trades: closed, open_positions: 0, curve});
    const f = frontend({fetchImpl: (path) => path === '/api/deployments'
      ? response({open_positions: [], deployments: [dep(1, 'demo', [[1760000000, -40], [1760003600, null], [1760007200, 2]], 30), dep(2, 'paper', [[1760000000, 0], [1760003600, 0]], 2)]})
      : response({})});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const html = f.root.querySelector('#deps').innerHTML;
    const sparks = [...html.matchAll(/<svg class="spark[^"]*"[^>]*aria-label="([^"]*)"[^>]*>[\s\S]*?<\/svg>/g)];
    assert.deepEqual(sparks.map((m) => m[1]).sort(), ['Demo cumulative P&amp;L, +$2.00 over 30 trades; low −$40.00, high +$2.00', 'Paper cumulative P&amp;L, $0.00 over 2 trades; flat at $0.00']);
    assert.doesNotMatch(html, /NaN/);
    f.clearTimers();
  });

  // `traces(hs)`: the bundle's price-trace svgs for these price series (Tau's hot rail rows; Meridian's market picker).
  test(`${name}: a market's price trace is drawn in a box at least 10¢ tall, so a 1¢ flicker is a small step`, async () => {
    const html = (await traces([[0.47, 0.47, 0.48, null, 0.47], [0.2, 0.6]])).join('');
    const [flicker, move] = [...html.matchAll(/<svg class="hot-chart"[\s\S]*?<\/svg>/g)].map((m) => points(m[0])[0]);
    const span = (pts) => Math.max(...pts.map((p) => p[1])) - Math.min(...pts.map((p) => p[1]));
    assert.equal(flicker.length, 4, 'the null price is left out');
    assert.ok(span(flicker) < 3, `a 1¢ tick spans ${span(flicker)} of the trace's 24`);
    assert.ok(span(move) > 23, 'a 40¢ move still fills the box');
    assert.doesNotMatch(html, /NaN/);
  });

  test(`${name}: a market's price history names each end's zone across the clock change, breaks at a gap, and says its figures`, async () => {
    await withZone('America/New_York', async () => {
      const start = Date.UTC(2026, 9, 31, 20) / 1000;  // 16:00 EDT; the clocks go back at 06:00 UTC on Nov 1
      const pts = Array.from({length: 40}, (_, i) => ({t: start + i * 3600, yes: i === 20 ? 0.2 : i === 9 ? 0.8 : 0.5, vol: 1}))
        .filter((p, i) => i <= 25 || i >= 38);  // twelve hours with no price
      pts.splice(3, 0, {t: start + 3 * 3600 + 60, yes: null, vol: 0});
      const page = {ticker: 'KXBTCD-26NOV0217-T112999.99', series: 'KXBTCD', title: 'Bitcoin price at 5pm EST?', status: 'active',
        yes_bid: '0.46', yes_ask: '0.49', last: '0.47', points: pts, period_min: 60, as_of: '2026-11-02T11:00:00Z', mine: {open: [], closed: []}};
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(page) : response({})});
      await f.viewMarketDetail(page.ticker); await settle();
      const svg = f.root.querySelector('.pchart-wrap').innerHTML;
      assert.doesNotMatch(svg, /NaN|undefined/);
      assert.deepEqual(texts(svg).slice(-2), ['10/31 16:00 EDT', '11/2 06:00 EST']);
      assert.equal(points(svg).length, 2, 'the line breaks across the hours with no price');
      assert.match(svg, /stroke-dasharray="3 4"/);
      assert.match(label(svg), /^Yes price history, from 10\/31 16:00 EDT to 11\/2 06:00 EST: starts at 50¢, ends at 50¢; low 20¢ \(11\/1 11:00 EST\), high 80¢ \(11\/1 01:00 EDT\); the line breaks where there was no price for a while \(1 time\)$/);
      // The raw table names each time's zone, since the prices span the change.
      const table = f.root.querySelector('#rawsect').innerHTML;
      assert.match(table, /<th>Time<\/th>/);
      assert.match(table, /EST<\/td>/);
      f.clearTimers();
    });
  });

  test(`${name}: a 10,000-minute price history is drawn at about two points a pixel`, async () => {
    const t0 = 1761400000;
    const page = {ticker: 'KXBTCD-26OCT2617-T112999.99', series: 'KXBTCD', title: 'Bitcoin price?', status: 'active', yes_bid: '0.46', yes_ask: '0.49',
      last: '0.47', period_min: 1, as_of: '2026-10-26T11:00:00Z', mine: {open: [], closed: []},
      points: Array.from({length: 10000}, (_, i) => ({t: t0 + i * 60, yes: i === 5000 ? 0.99 : 0.4 + (i % 10) / 100, vol: 1}))};
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(page) : response({})});
    await f.viewMarketDetail(page.ticker); await settle();
    const svg = f.root.querySelector('.pchart-wrap').innerHTML;
    const line = points(svg)[0];
    assert.ok(line.length <= 2 * (760 - 44 - 14) + 4, String(line.length));
    assert.ok(svg.length < 30000, String(svg.length));
    assert.match(label(svg), /high 99¢/);
    f.clearTimers();
  });
}
