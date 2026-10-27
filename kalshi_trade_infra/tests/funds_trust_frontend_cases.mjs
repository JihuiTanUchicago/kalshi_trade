// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): Funds names its two demo
// figures for what they are (Tau's demo book, the Kalshi demo account's cash); an open position's cost is one figure,
// with its fee, on the dashboard, Funds, Deploy and the strategy page; /funds#connect-kalshi opens Connect Kalshi, and
// the links that send someone to add a key go there.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const text = (el) => el.textContent.replace(/\s+/g, ' ');
// The harness elements have no layout: a check that something was brought into view records the call (and the
// in-page link's focus hand-off gets the attribute read it needs).
const watchScroll = (f) => {
  const proto = Object.getPrototypeOf(f.root), seen = [];
  proto.scrollIntoView = function () { seen.push(this.id || this.tag); };
  const hadHas = 'hasAttribute' in proto;
  if (!hadHas) proto.hasAttribute = function (k) { return k in this.attributes; };
  return {seen, done: () => { delete proto.scrollIntoView; if (!hadHas) delete proto.hasAttribute; }};
};

export function fundsTrustCases({name, frontend, fundsData, dashboard, detailStrategy, strategyFrontend}) {
  // ---------- two demo figures, two names ----------
  test(`${name}: Funds names Tau's demo book and the Kalshi demo account's cash, never two figures both called balance`, async () => {
    for (const balance of [250, 0]) {
      const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(),
        demo: {capital: 1000, equity: 1003.5, realized: 3.5, closed_trades: 1, open_positions: 0, open_at_cost: 0, open_cost: 0},
        kalshi_dev: {connected: true, key_id: 'DEVK…5678', balance, balance_at: new Date().toISOString()}}) : response({})});
      f.location.pathname = '/funds';
      await f.viewFunds(); await settle();
      const figs = text(f.root.querySelector('#ffigs')), main = f.root.querySelector('#main').innerHTML;
      assert.match(figs, /Tau’s demo book ?\$1,003\.50/);
      assert.match(main, /<dt>Tau’s demo book<\/dt><dd>\$1,003\.50<\/dd>/);
      assert.match(f.root.querySelector('[data-cash="demo-ok"]').innerHTML,
        new RegExp(`Connected ✓</b> \\(Kalshi demo account cash \\$${balance}\\.00, read just now\\)`));
      assert.doesNotMatch(figs + main, /Demo balance|\(balance \$|demo balance above/);
      if (!balance) assert.match(main, /Tau’s demo book above is Tau’s own bookkeeping and doesn’t fund it\./);
      f.clearTimers();
    }
  });

  test(`${name}: the dashboard names the demo figure Tau's demo book, as Funds does, keyed or not`, async () => {
    // Tau's dashboard said "Demo Sandbox" and Meridian's "Demo balance" for the figure Funds calls Tau's demo book.
    const demo = {capital: 1000, equity: 1003.5, realized_pnl: 3.5, closed_trades: 1, open_positions: 0, running: 1, open_at_cost: 0, open_cost: 0};
    const page = async (key, book) => {
      const base = dashboard();
      const d = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response({...base, demo: book, deployments: []})
        : path.startsWith('/api/track-record') ? response({modes: {}})
          : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
      d.S.me.kalshi_dev_connected = key;
      d.location.pathname = '/';
      await d.viewDashboard(); await settle();
      const html = ['#main', '#boardbody'].map((sel) => (d.root.querySelector(sel) || {innerHTML: ''}).innerHTML).join('');
      d.clearTimers();
      return html;
    };
    const label = (html) => [...html.matchAll(/<dt class="lab[^"]*">((?:(?!<\/dt>).)*)<\/dt>/g)].map((m) => m[1].replace(/<[^>]*>/g, '').trim());
    const keyed = await page(true, demo);
    assert.ok(label(keyed).some((l) => /Tau’s demo book$/.test(l)), label(keyed).join(' | '));
    assert.match(keyed.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' '), /Tau’s demo book \$1,003\.50/);
    const keyless = await page(false, {capital: 1000, equity: 1000});
    assert.match(keyless.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' '), /Tau’s demo book No demo key/);
    for (const html of [keyed, keyless]) assert.doesNotMatch(html, /Demo balance|Demo<\/span> Sandbox|>Sandbox</);
    // Funds, the same book: the same name.
    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(), demo: {...demo, realized: 3.5}}) : response({})});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    assert.match(text(f.root.querySelector('#ffigs')), /Tau’s demo book ?\$1,003\.50/);
    f.clearTimers();
  });

  // ---------- one cost basis ----------
  const pos = {id: 5, deployment_id: 9, strategy_id: 42, title: 'Drift', ticker: 'KXBTC15M-26OCT181230-T1', side: 'yes', qty: 5,
    entry_price: .38, entry_fee: .04, at_cost: 1.9, cost: 1.94, unrealized: null, mark: null, value: null, mode: 'paper',
    opened_at: '2026-10-25T08:00:00Z', market_close_time: '2030-01-15T17:30:00Z', status: 'open'};
  const book = {open_positions: 1, open_at_cost: 1.9, open_cost: 1.94};

  test(`${name}: an open position's cost is one figure with its fee on the dashboard, Funds, Deploy and the strategy page`, async () => {
    // Deploy and the strategy page already said "Cost + fee $1.94"; the dashboard and Funds said "$1.90 at cost".
    const dep = frontend({fetchImpl: (path) => path.startsWith('/api/deployments') ? response({deployments: [], open_positions: [pos]}) : response({})});
    dep.location.pathname = '/deploy';
    await dep.viewDeploy(); await settle();
    assert.match(dep.root.querySelector('#openpos').innerHTML, /data-lab="Cost \+ fee">\$1\.94</);
    dep.clearTimers();
    const s = strategyFrontend(detailStrategy({holdings: [pos]}), () => response({}));
    await s.viewStrategy(42); await settle();
    assert.match(s.root.querySelector('#main').innerHTML, /Cost \+ fee \$1\.94/);
    s.clearTimers();

    const base = dashboard();
    const data = {...base, paper: {...base.paper, cash: 998.06, equity: 999.96, realized_pnl: 0, closed_trades: 0, ...book},
      open_positions: [pos], deployments: []};
    const d = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response(data)
      : path.startsWith('/api/track-record') ? response({modes: {}})
        : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
    d.location.pathname = '/';
    await d.viewDashboard(); await settle();
    const dash = ['#boardbody', '#main'].map((sel) => (d.root.querySelector(sel) || {innerHTML: ''}).innerHTML).join('');
    if (name === 'Tau') {
      assert.match(dash, /<span>\$1\.94 at cost \+ fees<\/span>/, 'the unmarked position row');
      assert.match(dash, /\$998\.06 cash · \$1\.94 at cost \+ fees, \$1\.90 of it in the balance · /, 'the paper figure');
    } else {
      assert.match(dash, /<th scope="col" class="num">Cost \+ fee<\/th>/);
      assert.match(dash, /<span class="position-cost">\$1\.94<\/span>/, 'the position row');
      assert.match(dash, /<span class="lab">Open at cost \+ fees<\/span><strong>\$1\.94<\/strong><span class="sub-fig">\$1\.90 of it in the portfolio<\/span>/);
    }
    assert.doesNotMatch(dash, /\$1\.90 at cost|>\$1\.90</);
    d.clearTimers();

    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(),
      kalshi: {connected: true, key_id: 'k', balance: 50, funding_url: 'https://kalshi.com', ...book},
      demo: {capital: 1000, equity: 1000, realized: 0, closed_trades: 0, ...book},
      paper: {...fundsData().paper, cash: 998.06, equity: 999.96, realized_pnl: 0, closed_trades: 0, ...book}}) : response({})});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const figs = text(f.root.querySelector('#ffigs'));
    assert.match(figs, /1 open live position \(\$1\.94 at cost \+ fees\) not included/);
    // Tau's demo book is its capital plus closed demo trades: an open demo position's whole cost is still inside it,
    // and the line says so (it said only "1 open ($1.94 at cost + fees)"). It never says paper's balance or Kalshi's cash.
    assert.match(figs, /capital · 1 open \(\$1\.94 at cost \+ fees, all of it in Tau’s demo book\) ·/);
    assert.doesNotMatch(figs, /\$1\.90 of it in Tau’s demo book|all of it in the balance/);
    // Paper's balance is cash plus the position at its price ($998.06 + $1.90): the line says which part that is.
    assert.match(figs, /\$998\.06 cash · 1 open \(\$1\.94 at cost \+ fees, \$1\.90 of it in the balance\)/);
    assert.doesNotMatch(figs, /\$1\.90 at cost/);
    f.clearTimers();
  });

  // ---------- the Connect Kalshi link ----------
  test(`${name}: /funds#connect-kalshi opens Connect Kalshi and brings it into view; plain /funds leaves it folded`, async () => {
    const view = async (hash, d = fundsData()) => {
      const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response(d) : response({})});
      f.location.pathname = '/funds'; f.location.hash = hash;
      const scroll = watchScroll(f);
      try { await f.viewFunds(); await settle(); } finally { scroll.done(); }
      return {f, seen: scroll.seen};
    };
    let {f, seen} = await view('#connect-kalshi');
    assert.equal(f.root.querySelector('#connect-kalshi').open, true);
    assert.deepEqual(seen, ['connect-kalshi']);
    // A later redraw (the 30s poll) never opens it again once the reader has folded it.
    f.root.querySelector('#connect-kalshi').open = false;
    for (const t of [...f.intervals.values()]) t();
    await settle();
    assert.ok(!f.root.querySelector('#connect-kalshi').open);
    f.clearTimers();
    ({f, seen} = await view(''));
    assert.ok(!f.root.querySelector('#connect-kalshi').open, 'folded without the link');
    assert.deepEqual(seen, []);
    f.clearTimers();
    // An account with a live key has no fold: the link goes to the demo key form it lacks.
    ({f, seen} = await view('#connect-kalshi', {...fundsData(), kalshi: {connected: true, key_id: 'k', balance: 5, funding_url: 'https://kalshi.com'}}));
    assert.equal(f.root.querySelector('#connect-kalshi'), null);
    assert.equal(seen.length, 1);
    assert.ok(f.root.querySelector('#kalshi-dev').closest('section'));
    f.clearTimers();
  });

  test(`${name}: Funds' own "Connect a demo key" link opens the fold in place`, async () => {
    // A new account: no key of either kind, a demo book that never traded (so no demo figure, only the link).
    const fresh = {...fundsData(), demo: {capital: 1000, equity: 1000, realized: 0}};
    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response(fresh) : response({})});
    f.location.pathname = '/funds'; f.location.hash = '';
    await f.viewFunds(); await settle();
    const link = f.root.querySelectorAll('a').find((a) => a.getAttribute('href') === '#connect-kalshi' && a.textContent === 'Connect a demo key');
    assert.ok(link, 'the keyless demo figure links to Connect Kalshi');
    assert.equal(link.textContent, 'Connect a demo key');
    const [, onClick] = f.documentListeners.find(([type, cb]) => type === 'click' && String(cb).includes('a[href^="#"]'));
    const scroll = watchScroll(f);
    try { onClick({target: link, preventDefault() {}}); } finally { scroll.done(); }
    assert.equal(f.root.querySelector('#connect-kalshi').open, true);
    assert.deepEqual(scroll.seen, ['connect-kalshi']);
    f.clearTimers();
  });

  test(`${name}: the links that say to add a Kalshi key go to Funds' Connect Kalshi`, async () => {
    // The dashboard's demo figure for an account with no demo key (DEMO_NO_KEY).
    const base = dashboard();
    const d = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response({...base, demo: {equity: 1000, capital: 1000}, deployments: []})
      : path.startsWith('/api/track-record') ? response({modes: {}})
        : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
    d.S.me.kalshi_dev_connected = false; d.S.me.kalshi_connected = false;
    d.location.pathname = '/';
    await d.viewDashboard(); await settle();
    const dash = d.root.querySelector('#main').innerHTML + (d.root.querySelector('#boardbody') || {innerHTML: ''}).innerHTML;
    assert.match(dash, /Connect a Kalshi demo key on <a href="\/funds#connect-kalshi">Funds<\/a>/);
    assert.match(dash, /<a href="\/funds#connect-kalshi">(?:Funds|Connect Kalshi)<\/a>/);
    assert.doesNotMatch(dash, /<a href="\/funds">(?:Funds|Connect Kalshi)<\/a>/);
    d.clearTimers();
    // The strategy page's ladder and deploy notes for an account with neither key.
    const s = strategyFrontend(detailStrategy({status: 'passed'}), () => response({}));
    s.S.me.kalshi_dev_connected = false; s.S.me.kalshi_connected = false;
    await s.viewStrategy(42); await settle();
    const page = s.root.querySelector('#main').innerHTML;
    assert.match(page, /key on the <a href="\/funds#connect-kalshi">Funds page<\/a>/);
    assert.doesNotMatch(page, /<a href="\/funds">Funds page<\/a>/);
    s.clearTimers();
  });
}
