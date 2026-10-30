// Shared cases, run against each bundle's offline harness (Tau and Meridian), from a signed-in walk of the money pages
// (Dashboard, Deploy, a deployed strategy, Funds, Billing, Settings) at 390px and 1280px in both themes, 2026-10-30,
// with one strategy on paper and on demo:
// - Deploy's paper figure was labelled "Realized" beside "Demo realized": the bare word read as the board's total,
//   demo included. Beside a demo figure it says "Paper realized"; paper alone keeps "Realized".
// - An open position's unrealized P&L on the strategy page and the dashboard gave no time for its mark, where Deploy's
//   says "as of 05:31 UTC": with the engine stopped, a mark hours old read as this minute's. Each says when its mark
//   was read, and a position with no mark yet says so with no time.
// - A mark hours old still read as fresh as one from a minute ago beside its "as of" time. Once a mark is older than
//   three minutes (MARK_OLD_S: the engine marks every ~15-20s pass) its figure is dimmed and its "as of" says how long
//   ago in words ("as of 3 hours ago"), on the strategy page, the dashboard and Deploy; its time is in a title and in
//   text a screen reader reads. A fresh mark gives its time and is not dimmed (stale_mark_frontend_cases.mjs has more).
// - The Closed P&L chart's date axis read "Oct 29, Oct 30, Oct 30" with two days of data: its middle tick fell on the
//   second day's midnight. Each date is on an axis once, and a curve inside one day labels it once.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const MARKETS = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes'}];
// Today's time alone, or another day's date with it, always with a zone (settleAt).
const AT = '(?:[A-Z][a-z]{2} \\d{1,2}, )?\\d\\d:\\d\\d \\S+';
const pos = (extra) => ({title: 'Fade', ticker: 'KXBTC15M-26OCT301815-15', side: 'yes', qty: 12, entry_price: .41, entry_fee: .17, cost: 5.09,
  at_cost: 4.92, mark: .47, value: 5.64, unrealized: .55, mark_ts: new Date(Date.now() - 150e3).toISOString(), mode: 'paper', deployment_id: 1,
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
    assert.match(both, /Paper realized, listed below \+\$5\.08 paper money, not real/);
    assert.match(both, /Demo realized, listed below \+\$2\.14/);
    // Never one figure across the two books.
    assert.doesNotMatch(both, /\$7\.22/);
    const paper = await figs([dep(1, 'paper', 5.08)]);
    assert.match(paper, /Realized, listed below \+\$5\.08 paper money, not real/);
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
    assert.ok(lines[1].includes(markClock(marked.mark_ts) + ' '), 'the mark two and a half minutes ago gives its own time, not now');
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
  test(`${name}: an old mark says how long ago it was read in words, and a fresh one gives its time and no age`, async () => {
    const old = pos({id: 1, mark_ts: new Date(Date.now() - 3 * 3600e3).toISOString()}), fresh = pos({id: 2, mode: 'demo', qty: 5, cost: 2.17, unrealized: .13, mark_ts: new Date(Date.now() - 50e3).toISOString()});
    const sf = strategyFrontend(detailStrategy({holdings: [fresh, old]}), () => response({})); sf.S.me.markets = MARKETS;
    await sf.viewStrategy(42); await settle();
    const lines = sf.root.querySelectorAll('.holdlist .holdlist-figs').map((el) => el.textContent.replace(/\s+/g, ' '));
    assert.match(lines[0], new RegExp('Unrealized \\+\\$0\\.13 as of ' + AT));
    assert.doesNotMatch(lines[0], /ago/);
    assert.match(lines[1], /Unrealized \+\$0\.55 as of 3 hours ago/);
    if (sf.clearTimers) sf.clearTimers();

    const data = {...dashboard(), open_positions: [old, {...fresh, ticker: 'KXBTC15M-26OCT301830-30'}], recent_closed: []};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.markets = MARKETS;
    await f.viewDashboard(); await settle();
    const stubs = f.root.querySelectorAll('#dash-open .stub');
    const texts = (stubs.length ? stubs : f.root.querySelectorAll('tr.open-position')).map((el) => el.textContent.replace(/\s+/g, ' '));
    assert.equal(texts.length, 2);
    assert.match(texts[0], /as of 3 hours ago/);
    // Its "opened 39m ago" is the position's age, not its mark's: the mark's time stands alone.
    assert.match(texts[1], new RegExp('as of ' + AT));
    assert.doesNotMatch(texts[1], /as of \d+ \w+ ago/);
    if (f.clearTimers) f.clearTimers();

    const dep = {id: 1, strategy_id: 3, title: 'Fade', market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
      realized_pnl: 0, closed_trades: 0, open_positions: 2, unrealized_pnl: .68, created_at: '2026-10-30T05:00:00Z', curve: [], stake: 5,
      max_positions: 20, backtest: {out_of_sample: null}};
    const d = frontend({fetchImpl: (path) => path.startsWith('/api/deployments')
      ? response({open_positions: [old, {...fresh, mode: 'paper', ticker: 'KXBTC15M-26OCT301830-30'}], deployments: [dep]}) : response({})});
    d.S.me.markets = MARKETS; d.location.pathname = '/deploy';
    await d.viewDeploy(); await settle(); if (d.clearTimers) d.clearTimers();
    const cells = d.root.querySelectorAll('.pos-unreal').map((el) => el.textContent.replace(/\s+/g, ' '));
    assert.equal(cells.length, 2);
    assert.match(cells[0], /as of 3 hours ago/);
    assert.match(cells[1], new RegExp('as of ' + AT + '$'));
  });

  test(`${name}: a chart's date axis names each day once`, () => {
    const f = frontend();
    const noon = (d) => Date.parse(d + 'T12:00:00Z') / 1000;
    const axis = (svg, height) => {
      f.root.innerHTML = svg;
      return f.root.querySelectorAll('svg.chart text').filter((t) => t.getAttribute('y') === String(height - 6)).map((t) => t.textContent);
    };
    const unique = (dates) => assert.equal(new Set(dates).size, dates.length, dates.join(', '));
    // Two days of closed P&L (the dashboard's chart, drawn as paper in Meridian): "Oct 29, Oct 30", not "Oct 29, Oct 30, Oct 30".
    const two = axis(f.equityChart([[noon('2026-10-29'), 1], [noon('2026-10-30'), 3]], null, null, {paper: true, height: 180, endLabel: false}), 180)
      .concat(axis(f.equityChart([[noon('2026-10-29'), 1], [noon('2026-10-30'), 3]], null, null, {paper: true, height: 180, endLabel: false}), 236));
    assert.equal(two.length, 2, two.join(', ')); unique(two);
    assert.match(two[0], /29/); assert.match(two[1], /30/);
    // Three days keep their middle tick.
    const three = [[noon('2026-10-28'), 1], [noon('2026-10-29'), 2], [noon('2026-10-30'), 3]];
    const paper3 = axis(f.equityChart(three, null, null, {paper: true, height: 180}), 180).concat(axis(f.equityChart(three, null, null, {paper: true, height: 180}), 236));
    unique(paper3); assert.ok(paper3.length >= 2);
    // A backtest curve inside one day labels it once, as the drawdown plot beside it does.
    const t = noon('2026-10-30');
    const hours = [[t, 0], [t + 3600, 1], [t + 7200, 2]];
    const one = axis(f.equityChart(hours, null, null, {width: 760}), 236);
    assert.equal(one.length, 1, one.join(', '));
    const under = axis(f.rpUnderwater(hours), 180);
    assert.equal(under.length, 1, under.join(', '));
    // Days apart, both ends are named.
    const apart = axis(f.equityChart([[noon('2026-10-20'), 0], [noon('2026-10-30'), 2]], null, null, {width: 760}), 236);
    assert.equal(apart.length, 2); unique(apart);
  });

  // The Closed P&L chart's middle date sat at the span's midpoint: with two days that was the second day's midnight
  // ("Oct 29, Oct 30, Oct 30"), with four a midnight between two points. Its dates are its own days, each once, ends
  // in place, none running into the next, at a phone's width and a desktop's. Tau has no Closed P&L chart: its
  // equityChart names the two ends, and passes the same checks.
  test(`${name}: the Closed P&L chart's dates are its own days, each once, for a day, two days, a week and months`, () => {
    const f = frontend();
    const DAY = 86400, noonOf = (d) => Date.parse(d + 'T12:00:00Z') / 1000;
    const daily = (from, n, step = 1) => Array.from({length: n}, (_, i) => [noonOf(from) + i * step * DAY, i % 3 - 1]);
    const named = (t) => [{}, {year: 'numeric'}].map((y) => new Date(t * 1000).toLocaleDateString(undefined, {month: 'short', day: 'numeric', ...y, timeZone: 'UTC'}));
    const ticks = (curve, width) => {
      f.root.innerHTML = f.equityChart(curve, null, null, {paper: true, width, height: 180, endLabel: false});
      // The date axis: y is the chart's height less 6 (Meridian takes the height asked for, Tau draws 236 high).
      return f.root.querySelectorAll('svg.chart text').filter((t) => ['174', '230'].includes(t.getAttribute('y')))
        .map((t) => ({label: t.textContent, x: +t.getAttribute('x'), anchor: t.getAttribute('text-anchor') || 'start'}));
    };
    const reach = ({label, x, anchor}) => { const w = label.length * 6; return anchor === 'end' ? [x - w, x] : anchor === 'middle' ? [x - w / 2, x + w / 2] : [x, x + w]; };
    const cases = [['two days', daily('2026-10-29', 2)], ['a week', daily('2026-10-24', 7)], ['a month', daily('2026-10-01', 30)],
      ['three months, a close every third day', daily('2026-08-02', 30, 3)], ['across a new year', daily('2025-12-20', 30)]];
    const counts = {};
    for (const width of [280, 358, 760]) {
      for (const [what, curve] of cases) {
        const got = ticks(curve, width), labels = got.map((t) => t.label), where = `${what} at ${width}: ${labels.join(', ')}`;
        assert.equal(new Set(labels).size, labels.length, where);
        assert.ok(labels.length >= 2, where);
        // Every date is one of the curve's days, the first and last at the ends.
        const days = curve.map(([t]) => named(t));
        assert.ok(labels.every((l) => days.some((d) => d.includes(l))), where);
        assert.ok(named(curve[0][0]).includes(labels[0]) && named(curve[curve.length - 1][0]).includes(labels[labels.length - 1]), where);
        // Left to right, no label runs into the next.
        for (let i = 1; i < got.length; i++) assert.ok(reach(got[i - 1])[1] <= reach(got[i])[0], where);
        counts[`${what} ${width}`] = labels.length;
      }
    }
    // One day: a curve inside a day names it once.
    assert.equal(ticks([[noonOf('2026-10-30'), 0], [noonOf('2026-10-30') + 3600, 1]], 760).length, 1);
    if (name === 'Meridian') {
      // A wide chart spreads dates between its ends; a phone's keeps at least the ends.
      assert.equal(counts['two days 760'], 2);
      assert.ok(counts['a week 760'] >= 4, JSON.stringify(counts));
      assert.equal(counts['a month 760'], 5, JSON.stringify(counts));
      assert.ok(counts['a month 358'] >= 3, JSON.stringify(counts));
      // Across a new year each date names its year.
      assert.ok(ticks(daily('2025-12-20', 30), 760).every((t) => /20(25|26)/.test(t.label)));
    }
  });
}
