// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the demo book (Kalshi's
// sandbox, play money) reads the same on every page that shows it. Its capital is named as Funds names it ("starting
// capital", "capital at last reload"), before its first close it says when its P&L shows rather than "$0.00 realized",
// and each demo figure says what it is net of (walk 2026-10-31: the dashboard said "$1,000.00 capital" and "$0.00
// realized all time" beside Funds' "Starting capital" and "P&L shows once a demo trade closes"; Funds' own box said
// "Realized all time $0.00" under that line; the since-visit strip and the ladder's demo rung named no fees).
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const words = (html) => html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ');

export function demoBookCases({name, frontend, fundsData, dashboard, detailStrategy, strategyFrontend}) {
  const demoDep = {id: 7, strategy_id: 42, title: 'Fresh copy', market: 'btc15m', mode: 'demo', status: 'running', status_reason: null,
    stake: 5, max_positions: 4, realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 1, curve: [], created_at: '2026-10-29T08:00:00Z', demo_copy: true};
  const dash = async (demo, extra = {}) => {
    const base = dashboard();
    const d = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response({...base, demo, deployments: [demoDep], ...extra})
      : path.startsWith('/api/track-record') ? response({modes: {}})
        : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
    d.S.me.kalshi_dev_connected = true;
    d.location.pathname = '/';
    await d.viewDashboard(); await settle();
    const html = ['#main', '#boardbody'].map((sel) => (d.root.querySelector(sel) || {innerHTML: ''}).innerHTML).join('');
    d.clearTimers();
    return html;
  };
  const funds = async (demo) => {
    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(), demo,
      kalshi_dev: {connected: true, key_id: 'DEVK…5678', balance: 250, balance_at: new Date().toISOString()}}) : response({})});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const out = {figs: f.root.querySelector('#ffigs').innerHTML, main: f.root.querySelector('#main').innerHTML};
    f.clearTimers();
    return out;
  };
  const book = {open_positions: 1, open_at_cost: 0.94, open_cost: 0.98};

  test(`${name}: the dashboard's demo book names its capital as Funds does, before and after a reload`, async () => {
    for (const [before_reload, cap] of [[0, 'starting capital'], [0.15, 'capital at last reload']]) {
      const html = await dash({capital: 500, equity: 500.36, realized_pnl: 0.36, today_pnl: 0.36, closed_trades: 3, running: 1, ...book, before_reload});
      assert.match(words(html), new RegExp(`\\$500\\.00 ${cap} · 1 open · \\+\\u2060?\\$0\\.36 realized ${before_reload ? 'since reload' : 'all time'}, after Kalshi fees · real fills on Kalshi’s sandbox, not real money`));
      assert.doesNotMatch(words(html), /\$500\.00 capital ·/);
      const f = await funds({capital: 500, equity: 500.36, realized: 0.36, closed_trades: 3, ...book, before_reload});
      assert.match(words(f.figs), new RegExp(`\\$500\\.00 ${cap} · 1 open`));
      assert.match(f.main, new RegExp(`<dt>${cap[0].toUpperCase() + cap.slice(1)}</dt><dd>\\$500\\.00</dd>`));
    }
    // A book that never traded says so, in the same words.
    assert.match(words(await dash({capital: 1000, equity: 1000, realized_pnl: 0, closed_trades: 0, open_positions: 0, running: 0}, {deployments: []})),
      /\$1,000\.00 starting capital · no demo strategies yet · real fills on Kalshi’s sandbox, not real money/);
  });

  test(`${name}: a demo book with no closed trade says when its P&L shows, never "$0.00 realized", on the dashboard and Funds`, async () => {
    const html = words(await dash({capital: 1000, equity: 1000, realized_pnl: 0, today_pnl: 0, closed_trades: 0, running: 1, ...book, before_reload: 0}));
    assert.match(html, /\$1,000\.00 starting capital · 1 open · P&L shows once a demo trade closes · real fills on Kalshi’s sandbox, not real money/);
    assert.doesNotMatch(html, /\$0\.00 realized/);
    const f = await funds({capital: 1000, equity: 1000, realized: 0, closed_trades: 0, ...book, before_reload: 0});
    assert.match(words(f.figs), /P&L shows once a demo trade closes/);
    // Funds' demo box under it: "Realized all time $0.00" beside that line read as a result.
    assert.match(f.main, /<dt>Realized all time<\/dt><dd class="[^"]*">None yet<\/dd>/);
    assert.doesNotMatch(f.main, /<dt>Realized all time<\/dt><dd[^>]*>\$0\.00/);
    // Once one closes, the figure, as before.
    const done = await funds({capital: 1000, equity: 1002.78, realized: 2.78, closed_trades: 4, ...book, before_reload: 0});
    assert.match(done.main, /<dt>Realized all time<\/dt><dd class="[^"]*">\+⁠?\$2\.78<\/dd>/);
    assert.match(words(await dash({capital: 1000, equity: 1002.78, realized_pnl: 2.78, today_pnl: 0, closed_trades: 4, running: 1, ...book, before_reload: 0})),
      /\$1,000\.00 starting capital · 1 open · \+⁠?\$2\.78 realized all time, after Kalshi fees/);
  });

  test(`${name}: the since-visit strip's demo line says it is play money, net of Kalshi fees, as paper's says its own`, async () => {
    const since = {at: '2026-10-30T08:00:00+00:00', first: false, books: {paper: {pnl: 0.62, trades: 1}, demo: {pnl: 0.67, trades: 1}, live: {pnl: 0, trades: 0}},
      passed: {n: 0, items: []}, autopilot: {}, runs: {}};
    const paperDep = {...demoDep, id: 6, mode: 'paper', demo_copy: false};
    const html = await dash({capital: 1000, equity: 1000.67, realized_pnl: 0.67, today_pnl: 0.67, closed_trades: 1, running: 1, ...book}, {since, deployments: [paperDep, demoDep]});
    const strip = (/<section class="since" id="dash-since"[\s\S]*?<\/section>/.exec(html) || [''])[0];
    assert.match(strip, /data-book="demo"><span class="nobr"><b>Demo<\/b> <span class="pos">\+⁠?\$0\.67<\/span><\/span> on 1 trade \(play money\), after Kalshi fees<\/span>/);
    assert.match(strip, /data-book="paper">[^]*? on 1 trade, after Kalshi fees and the spread<\/span>/);
    assert.doesNotMatch(strip, /\$1\.29|real money/);  // never summed with paper, never called real money
  });

  test(`${name}: the ladder's demo rung says its realized is after Kalshi fees, as the paper rung says its own`, async () => {
    const d = (id, mode, closed_trades, realized_pnl) => ({id, mode, status: 'running', closed_trades, realized_pnl, open_positions: 0, stake: 5, created_at: '2026-10-20T08:00:00Z'});
    const s = strategyFrontend(detailStrategy({deployments: [d(1, 'paper', 2, -0.07), d(2, 'demo', 2, -0.29)]}), () => response({}));
    await s.viewStrategy(42); await settle();
    const ladder = s.root.querySelector('#ladder-body').innerHTML;
    s.clearTimers && s.clearTimers();
    assert.match(ladder, /<span class="mk dep">Demo<\/span> running · 2 closed trades · (?:<span[^>]*>)?−⁠?\$0\.29(?:<\/span>)? realized, after Kalshi fees<\/p>/);
    assert.match(ladder, /Paper<\/span> running · 2 closed trades · (?:<span[^>]*>)?−⁠?\$0\.07(?:<\/span>)? realized, after Kalshi fees and the spread/);
    // Before its first close a rung has nothing to be net of.
    const fresh = strategyFrontend(detailStrategy({deployments: [d(1, 'paper', 0, 0), d(2, 'demo', 0, 0)]}), () => response({}));
    await fresh.viewStrategy(42); await settle();
    assert.match(fresh.root.querySelector('#ladder-body').innerHTML, /Demo<\/span> running · no closed trades yet<\/p>/);
    fresh.clearTimers && fresh.clearTimers();
  });
}
