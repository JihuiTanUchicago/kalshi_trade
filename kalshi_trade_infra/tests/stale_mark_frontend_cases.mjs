// Shared cases, run against each bundle's offline harness (Tau and Meridian). An open position's unrealized P&L is
// priced from its mark, the last price the engine read for it. With the engine stopped, or a thin contract with no
// bid, the mark stops moving, and its figure still read as this minute's: undimmed, with an "as of" clock time a reader
// had to check against their own clock. Past three minutes (MARK_OLD_S in each bundle: the engine marks on every
// ~15-20s pass and stops trusting a mark at 90s) the figure is dimmed (.mark-old) and its "as of" says how long ago in
// words ("as of 3 hours ago"), with its time and what it means in a title and in text a screen reader reads. Wherever
// an open position's figure is shown: Deploy's positions and deployment rows, the dashboard, the strategy page and a
// market page. Display only: every figure is the server's, unchanged.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const MARKETS = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes'}];
const ago = (s) => new Date(Date.now() - s * 1000).toISOString();
const OLD = 3 * 3600;  // the engine stopped three hours ago
const pos = (extra) => ({id: 1, title: 'Fade', ticker: 'KXBTC15M-26OCT301815-15', side: 'yes', qty: 12, entry_price: .41, entry_fee: .17, cost: 5.09,
  at_cost: 4.92, mark: .47, value: 5.64, unrealized: .55, mark_ts: ago(20), mode: 'paper', deployment_id: 1, strategy_id: 3, status: 'open',
  opened_at: '2026-10-30T05:20:00Z', market_close_time: new Date(Date.now() + 9 * 60e3).toISOString(), ...extra});
const dep = (extra) => ({id: 1, strategy_id: 3, title: 'Fade', market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
  realized_pnl: 0, closed_trades: 0, open_positions: 2, unrealized_pnl: .68, created_at: '2026-10-30T05:00:00Z', curve: [], stake: 5,
  max_positions: 20, backtest: {out_of_sample: null}, ...extra});
const words = (el) => el.textContent.replace(/\s+/g, ' ').trim();
// An old mark's "as of": its age in words, its time in the title and in screen reader text.
const assertOldAge = (el, age) => {
  const marked = el.querySelector('.mark-age');
  assert.ok(marked, 'an old mark says how old it is');
  assert.match(words(marked), new RegExp(`as of ${age}`));
  assert.match(marked.getAttribute('title'), /^Last marked \S.*\. No newer price has come in, so this figure may be out of date\.$/);
  assert.match(words(marked.querySelector('.vh')), /Last marked .+ may be out of date/);
};

export function staleMarkCases({name, frontend, strategyFrontend, detailStrategy, dashboard}) {
  const deploy = async (positions, deployments = [dep()]) => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/deployments') ? response({open_positions: positions, deployments}) : response({})});
    f.S.me.markets = MARKETS; f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle(); if (f.clearTimers) f.clearTimers();
    return f;
  };

  test(`${name}: a mark under three minutes old gives its time undimmed; past three minutes it is dimmed and says how old`, async () => {
    const f = await deploy([pos({id: 1, mark_ts: ago(150)}), pos({id: 2, ticker: 'KXBTC15M-26OCT301830-30', mark_ts: ago(240)})]);
    const cells = f.root.querySelectorAll('#openpos .pos-unreal');
    assert.equal(cells.length, 2);
    // Two and a half minutes: a slow pass or two of a running engine, not an old price.
    assert.equal(cells[0].querySelectorAll('.mark-old').length, 0);
    assert.equal(cells[0].querySelectorAll('.mark-age').length, 0);
    assert.match(words(cells[0]), /^\+\$0\.55 ?as of (?:[A-Z][a-z]{2} \d{1,2}, )?\d\d:\d\d \S+$/);
    // Four minutes: twice the engine's own 90s gate and more.
    assert.equal(cells[1].querySelectorAll('.mark-old').length, 1);
    assert.match(words(cells[1].querySelector('.mark-old')), /^\+\$0\.55$/);
    assertOldAge(cells[1], '4 min ago');
  });

  test(`${name}: Deploy dims an old mark's figure and a deployment's Unrealized as old as its oldest mark`, async () => {
    const f = await deploy([pos({id: 1, mark_ts: ago(OLD)}), pos({id: 2, ticker: 'KXBTC15M-26OCT301830-30', unrealized: .13}),
      pos({id: 3, deployment_id: 2, ticker: 'KXBTC15M-26OCT301845-45', unrealized: .1})],
    [dep(), dep({id: 2, title: 'Drift', unrealized_pnl: .1, open_positions: 1})]);
    const cells = f.root.querySelectorAll('#openpos .pos-unreal');
    assert.equal(cells.length, 3);
    assert.equal(cells[0].querySelectorAll('.mark-old').length, 1);
    assertOldAge(cells[0], '3 hours ago');
    assert.equal(cells[1].querySelectorAll('.mark-old').length, 0);
    // A deployment's Unrealized sums its marks, so one old mark makes the sum old: "est. as of 3 hours ago".
    const rows = f.root.querySelectorAll('#deps td[data-lab="Unrealized"]');
    assert.equal(rows.length, 2);
    assert.match(words(rows[0].querySelector('.mark-old')), /^\+\$0\.68$/);
    assert.match(words(rows[0]), /est\. as of 3 hours ago/);
    assertOldAge(rows[0], '3 hours ago');
    // Every mark of the other deployment is fresh: its figure reads as before.
    assert.equal(rows[1].querySelectorAll('.mark-old').length, 0);
    assert.match(words(rows[1]), /^\+\$0\.10 ?est\.$/);
  });

  test(`${name}: the dashboard dims an old mark's figure and its deployment's Unrealized, and says how old`, async () => {
    const data = {...dashboard(), deployments: [dep()], open_positions: [pos({id: 1, mark_ts: ago(OLD)}), pos({id: 2, ticker: 'KXBTC15M-26OCT301830-30'})], recent_closed: []};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.markets = MARKETS;
    await f.viewDashboard(); await settle(); if (f.clearTimers) f.clearTimers();
    const stubs = f.root.querySelectorAll('#dash-open .stub');
    const rows = stubs.length ? stubs : f.root.querySelectorAll('tr.open-position');
    assert.equal(rows.length, 2);
    // Tau's line dims what the position is worth and its gain; Meridian's row its Unrealized P&L.
    assert.match(words(rows[0].querySelector('.mark-old')), stubs.length ? /^worth \$5\.64 \(\+\$0\.55\)$/ : /^\+\$0\.55$/);
    assertOldAge(rows[0], '3 hours ago');
    if (stubs.length) assert.match(words(rows[0]), /worth as of 3 hours ago/);
    assert.equal(rows[1].querySelectorAll('.mark-old').length, 0);
    assert.equal(rows[1].querySelectorAll('.mark-age').length, 0);
    // The deployment's Unrealized: Tau's row on the dashboard, Meridian's monitor.
    const unreal = f.root.querySelector('#dash-deps td[data-lab="Unrealized"]') || f.root.querySelector('.monitor-unrealized');
    assert.ok(unreal);
    assert.match(words(unreal.querySelector('.mark-old')), /^\+\$0\.68$/);
    assertOldAge(unreal, '3 hours ago');
  });

  test(`${name}: the strategy page dims an old holding and its book's unrealized sum, and says how old`, async () => {
    const holdings = [pos({id: 1, mark_ts: ago(OLD)}), pos({id: 2, ticker: 'KXBTC15M-26OCT301830-30', unrealized: .13})];
    const f = strategyFrontend(detailStrategy({holdings}), () => response({})); f.S.me.markets = MARKETS;
    await f.viewStrategy(42); await settle(); if (f.clearTimers) f.clearTimers();
    const lines = f.root.querySelectorAll('.holdlist .holdlist-figs');
    assert.equal(lines.length, 2);
    assert.match(words(lines[0].querySelector('.mark-old')), /^\+\$0\.55$/);
    assertOldAge(lines[0], '3 hours ago');
    assert.equal(lines[1].querySelectorAll('.mark-old').length, 0);
    // The book's line sums both marks: as old as the older one.
    const book = f.root.querySelectorAll('p.hint').find((p) => /open positions at cost/.test(words(p)));
    assert.match(words(book.querySelector('.mark-old')), /^\+\$0\.68$/);
    assert.match(words(book), /unrealized \+\$0\.68 \(est\., mark-to-market on the current bid, as of 3 hours ago/);
    assertOldAge(book, '3 hours ago');
  });

  test(`${name}: a market page dims an old mark's figure and its book's unrealized sum, and says how old`, async () => {
    const page = {ticker: 'KXBTC15M-26OCT301815-15', series: 'KXBTC15M', title: 'BTC up or down?', status: 'active',
      yes_bid: '0.47', yes_ask: '0.49', last: '0.47', points: [], period_min: 1, as_of: ago(60),
      mine: {open: [pos({id: 1, mark_ts: ago(OLD)}), pos({id: 2, strategy_id: 4, title: 'Drift', unrealized: .13})], closed: []}};
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(page) : response({})});
    f.S.me.markets = MARKETS;
    await f.viewMarketDetail(page.ticker); await settle(); if (f.clearTimers) f.clearTimers();
    const cells = f.root.querySelectorAll('.mk-book td[data-lab="Unrealized"]');
    assert.equal(cells.length, 2);
    assert.match(words(cells[0].querySelector('.mark-old')), /^\+\$0\.55$/);
    assertOldAge(cells[0], '3 hours ago');
    assert.equal(cells[1].querySelectorAll('.mark-old').length, 0);
    const sum = f.root.querySelector('.mk-book p.hint');
    assert.match(words(sum.querySelector('.mark-old')), /^\+\$0\.68$/);
    assert.match(words(sum), /\(est\. at the current bid, marked 3 hours ago/);
  });

  // A sum over only some of a book's (or a deployment's) open positions, the rest not marked yet, says how many it
  // covers: "2 open positions at cost + fees $10.18 · unrealized +$0.55" read as both positions' figure when only one
  // had a price (walked 2026-10-31). Every figure is the server's; only the words around it change.
  test(`${name}: an unrealized sum over some of the open positions says how many it covers`, async () => {
    const half = [pos({id: 1}), pos({id: 2, ticker: 'KXBTC15M-26OCT301830-30', mark: null, value: null, unrealized: null, mark_ts: null})];
    // Deploy: the deployment's row says "1 of 2 marked" under its estimate; one with every position marked doesn't.
    const f = await deploy([...half, pos({id: 3, deployment_id: 2, ticker: 'KXBTC15M-26OCT301845-45', unrealized: .1})],
      [dep({unrealized_pnl: null}), dep({id: 2, title: 'Drift', unrealized_pnl: .1, open_positions: 1})]);
    const rows = f.root.querySelectorAll('#deps td[data-lab="Unrealized"]');
    assert.equal(rows.length, 2);
    assert.match(words(rows[0]), /^\+\$0\.55 ?est\. · 1 of 2 marked$/);
    assert.match(words(rows[1]), /^\+\$0\.10 ?est\.$/);
    // The dashboard: Tau's deployment row, Meridian's monitor.
    const data = {...dashboard(), deployments: [dep({unrealized_pnl: .55})], open_positions: half, recent_closed: []};
    const g = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    g.S.me.markets = MARKETS;
    await g.viewDashboard(); await settle(); if (g.clearTimers) g.clearTimers();
    const unreal = g.root.querySelector('#dash-deps td[data-lab="Unrealized"]') || g.root.querySelector('.monitor-unrealized');
    assert.match(words(unreal), /\+\$0\.55.*1 of 2 marked/);
    // The strategy page's book line: the sum, how many it covers, and how many wait for a price.
    const sp = strategyFrontend(detailStrategy({holdings: half}), () => response({})); sp.S.me.markets = MARKETS;
    await sp.viewStrategy(42); await settle(); if (sp.clearTimers) sp.clearTimers();
    const book = sp.root.querySelectorAll('p.hint').find((p) => /open positions at cost/.test(words(p)));
    assert.match(words(book), /^Paper: 2 open positions at cost \+ fees \$10\.18 · unrealized \+\$0\.55 on 1 of 2 \(est\., mark-to-market on the current bid\) · 1 not marked yet\.$/);
    // Every position marked: the line reads as before, with no count.
    const all = strategyFrontend(detailStrategy({holdings: [pos({id: 1}), pos({id: 2, ticker: 'KXBTC15M-26OCT301830-30', unrealized: .13})]}), () => response({}));
    all.S.me.markets = MARKETS;
    await all.viewStrategy(42); await settle(); if (all.clearTimers) all.clearTimers();
    const full = all.root.querySelectorAll('p.hint').find((p) => /open positions at cost/.test(words(p)));
    assert.doesNotMatch(words(full), / of 2|not marked/);
    // A market page's book line.
    const page = {ticker: 'KXBTC15M-26OCT301815-15', series: 'KXBTC15M', title: 'BTC up or down?', status: 'active',
      yes_bid: '0.47', yes_ask: '0.49', last: '0.47', points: [], period_min: 1, as_of: ago(60), mine: {open: half, closed: []}};
    const m = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(page) : response({})});
    m.S.me.markets = MARKETS;
    await m.viewMarketDetail(page.ticker); await settle(); if (m.clearTimers) m.clearTimers();
    assert.match(words(m.root.querySelector('.mk-book p.hint')), /unrealized \+\$0\.55 on 1 of 2 \(est\. at the current bid[^)]*\) · 1 not marked yet/);
  });
}
