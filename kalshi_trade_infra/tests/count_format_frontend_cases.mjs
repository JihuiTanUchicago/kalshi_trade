// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): a plain count a
// customer reads (trades, ideas tested, open positions, closed trades) carries a thousands separator, "1,201",
// as the strategy page's abstract does (num() in app.js and app.meridian.js). Walked 2026-10-28: the Strategies
// list's Trades column and a shared Community card both read "1201".
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
// Text as a reader sees it: no tags or attributes, entities read.
const plain = (html) => html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&');
const big = {pnl: 9876.54, trades: 1201, win_rate: .6, fees: 1, profit_factor: 1.2, max_drawdown: 2, sharpe: .5, roi: .05, days: 9};

export function countFormatCases({name, frontend, detailStrategy, strategyFrontend, fundsData, dashboard}) {
  test(`${name}: the Strategies list counts a row's trades as "1,201", in its Trades column and its paper line`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = f.strategySlip(detailStrategy({id: 46, title: 'Busy', out_of_sample: big, hypotheses_tried: 1201,
      deployed: true, books: ['paper'], real: {pnl: 12.5, trades: 1201, open: 0, mode: 'paper'}}), null, {});
    assert.match(row, /data-lab="Trades">1,201</);
    assert.match(row, /data-lab="Ideas tested"[^>]*>1,201</);
    assert.match(plain(row), /1,201 trades/);
    assert.doesNotMatch(plain(row), /1201/);
    // In the list's Paper P&L column too, as is a removed paper book's count.
    const col = f.strategySlip(detailStrategy({id: 46, title: 'Busy', out_of_sample: big, deployed: true, books: ['paper'],
      real: {pnl: 12.5, trades: 1201, open: 0, mode: 'paper'}, past: {paper: {pnl: 1, trades: 1202, deployments: 1}}}), null, {paper: true});
    const cell = col.match(/data-lab="Paper since deploying">([\s\S]*?)<\/td>/)[1];
    assert.match(plain(cell), /since deploying · 1,201 trades/); assert.match(plain(cell), /Removed from paper: .*1,202 trades/);
    assert.doesNotMatch(plain(col), /1201|1202/);
  });

  test(`${name}: a shared Community card counts its trades as "1,201", whichever figure it shares`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const cards = [
      {kind: 'strategy', id: 42, title: 'Busy', market: 'btc15m', status: 'passed', pnl: 5.5, trades: 1201, win_rate: 0.58, days: 9},
      {kind: 'strategy', id: 42, title: 'Busy', market: 'btc15m', status: 'backtest-only', pnl: 5.5, trades: 1201, win_rate: 0.58, days: 9},
      {kind: 'deployment', id: 7, title: 'Busy', market: 'btc15m', mode: 'paper', realized_pnl: 3.25, closed_trades: 1201, since: '2026-10-01T00:00:00Z'},
      {kind: 'pnl', paper_pnl: 3.25, paper_trades: 1201, live_pnl: 0, live_trades: 1201},
    ];
    for (const card of cards) {
      for (const owner of ['', '@maya']) {
        const text = plain(f.postSnapshot(card, owner));
        assert.match(text, /1,201/, JSON.stringify(card));
        assert.doesNotMatch(text, /1201/, JSON.stringify(card));
      }
    }
  });

  // The Strategies list's figures over the rows (Passed, Void, Rejected) and a Community post's reply count read
  // "1201" beside the rows' "1,201".
  test(`${name}: the Strategies list's figures count its strategies as "1,201"`, async () => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/strategies') ? response({strategies: [], matched: 0,
      counts: {total: 3604, passed: 1201, failed: 1203, failed_no_record: 1, not_cleared: 1204, rejected: 1200}}) : response({}))});
    f.location.pathname = '/strategies'; f.location.search = '?status=';
    await f.viewStrategies(); await settle();
    const figs = plain(f.root.querySelector('#sfigs').innerHTML);
    for (const n of ['1,201', '1,202', '1,200', '1,204', '3,604']) assert.match(figs, new RegExp(n), n);
    assert.doesNotMatch(figs, /\b120[0-4]\b|\b3604\b/);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: a Community post counts its replies as "1,201"`, async () => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/community') ? response({posts: [{id: 1, body: 'Busy thread', author: 'Bob',
      username: 'bob', created_at: '2026-10-17T10:00:00Z', mine: false, comments: 1201, reactions: []}]}) : response({}))});
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const link = f.root.querySelector('[data-act="comments"]');
    assert.equal(link.textContent.trim(), '1,201 replies');
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: the strategy page's details count its trades as "1,201"`, async () => {
    const f = strategyFrontend(detailStrategy({status: 'backtest-only', experiment: null, out_of_sample: big,
      in_sample: {...big, trades: 3300, days: 31}, recent_trades: []}), () => response({}));
    await f.viewStrategy(42); await flush();
    const text = plain(f.root.querySelector('#main').innerHTML);
    assert.match(text, /1,201/); assert.match(text, /3,300/);
    assert.doesNotMatch(text, /\b1201\b|\b3300\b/);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: the Deploy board counts a deployment's closed trades and open positions as "1,201"`, async () => {
    const dep = {id: 1, strategy_id: 1, title: 'Busy', market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
      realized_pnl: 12.5, closed_trades: 1201, open_positions: 1200, unrealized_pnl: null, created_at: '2026-10-01T08:00:00Z',
      curve: [], stake: 5, max_positions: 2000, backtest: {out_of_sample: {pnl: 24.02, trades: 1201}}};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments') return response({deployments: [dep], open_positions: []});
      if (path === '/api/strategies?status=passed') return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const text = plain(f.root.querySelector('#deps').innerHTML);
    assert.match(text, /1,201/); assert.match(text, /1,200/);
    assert.doesNotMatch(text, /\b1201\b|\b1200\b/);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: Research counts ideas tested, its loop card's figures and a session's ideas as "1,201"`, async () => {
    const board = {total: {runs: 1201, explored: 1201, gated: 1201, gate_reach_rate: 0.25, passed: 1201, holdout_passed: 0, cost_usd: 2,
      pipeline_death_share: 0.2}, days: [], trend: null, playbooks: [], scout: [], fix_list: [], data_requests: [],
      paper: {total: {strategies: 1201, trading: 1201, round_trips: 1201, net_pnl: -16.6, live_ready: 0, realization: -0.5}, by_playbook: {}}};
    const run = {id: 8, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea', hypotheses_tried: 1201,
      strategies_passed: 1, spent_usd: 4.2, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit'};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs: [run], counts: {research_running: 0, research_queued: 0, research_paused: 0},
        policy: null, totals: {tried: 1201, passed: 3}, v: 'v1'});
      if (path.startsWith('/api/research/scoreboard')) return response(board);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const figs = plain(f.root.querySelector('#rfigs').innerHTML), card = plain(f.root.querySelector('#rsimo').innerHTML);
    assert.match(figs, /1,201/); assert.doesNotMatch(figs, /1201/);
    assert.match(card, /1,201 passed strategies, 1,201 trading, 1,201 closed trades/); assert.doesNotMatch(card, /1201/);
    const row = plain(f.runRow(run));
    assert.match(row, /1,201/); assert.doesNotMatch(row, /1201/);
    f.clearTimers();
  });

  // A position holds 1,201 contracts as readily as a deployment closes 1,201 trades.
  const pos = {id: 5, deployment_id: 9, strategy_id: 42, title: 'Drift', ticker: 'KXBTC15M-26OCT181230-T1', side: 'yes', qty: 1201,
    entry_price: .38, entry_fee: .04, at_cost: 456.38, cost: 456.42, unrealized: null, mark: null, value: null, mode: 'paper',
    opened_at: '2026-10-25T08:00:00Z', market_close_time: '2030-01-15T17:30:00Z', status: 'open'};

  test(`${name}: Funds counts each book's open positions as "1,201"`, async () => {
    const book = {open_positions: 1201, open_at_cost: 456.38, open_cost: 456.42};
    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(),
      kalshi: {connected: true, key_id: 'k', balance: 50, funding_url: 'https://kalshi.com', ...book},
      demo: {capital: 1000, equity: 1000, realized: 0, closed_trades: 0, ...book},
      paper: {...fundsData().paper, cash: 543.58, equity: 999.96, realized_pnl: 0, closed_trades: 0, ...book}}) : response({})});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const figs = plain(f.root.querySelector('#ffigs').innerHTML).replace(/\s+/g, ' ');
    assert.match(figs, /1,201 open live positions \(\$456\.42 at cost \+ fees\) not included/);
    assert.match(figs, /capital · 1,201 open \(\$456\.42 at cost \+ fees, all of it in Tau’s demo book\)/);
    assert.match(figs, /\$543\.58 cash · 1,201 open \(\$456\.42 at cost \+ fees/);
    assert.doesNotMatch(figs, /\b1201\b/);
    f.clearTimers();
  });

  test(`${name}: a position's quantity reads "×1,201" on Deploy and on the strategy page, held or traded`, async () => {
    const dep = frontend({fetchImpl: (path) => path.startsWith('/api/deployments') ? response({deployments: [], open_positions: [pos]}) : response({})});
    dep.location.pathname = '/deploy';
    await dep.viewDeploy(); await settle();
    const open = dep.root.querySelector('#openpos').innerHTML;
    assert.match(open, /YES ×1,201 @/); assert.doesNotMatch(open, /×1201/);
    dep.clearTimers();
    const s = strategyFrontend(detailStrategy({holdings: [pos], recent_trades: [{opened: '2026-10-25T08:00Z', ticker: pos.ticker,
      side: 'yes', qty: 1201, entry: .38, exit: .52, reason: 'settled', pnl: 168.14}]}), () => response({}));
    await s.viewStrategy(42); await settle();
    const main = s.root.querySelector('#main').innerHTML;
    assert.match(main, /<b>YES ×1,201 @/, 'the Holding right now list');
    assert.match(main, /data-lab="Position">YES ×1,201</, 'the recent trades table');
    assert.doesNotMatch(main, /×1201/);
    s.clearTimers();
  });

  // The Explore market page's "Your positions" table (marketMine): an open and a closed position, each book apart.
  test(`${name}: a position's quantity reads "×1,201" on the Explore market page, open or closed`, async () => {
    const page = {ticker: pos.ticker, series: 'KXBTC15M', title: 'BTC up or down?', sub: '', status: 'active', yes_bid: '0.55',
      yes_ask: '0.57', last: '0.55', volume_24h: '10', open_interest: '10', close_time: '2030-01-15T17:30:00Z', as_of: '2026-10-27T16:00:00Z',
      rules: 'Resolves Yes if up.', period_min: 1, points: [],
      mine: {open: [pos], closed: [{...pos, id: 6, mode: 'demo', side: 'no', qty: 1202, status: 'closed', pnl: 12.02, exit_price: .45, close_reason: 'take_profit'}]}};
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(page) : response({})});
    f.location.pathname = '/explore'; f.location.search = '?m=' + encodeURIComponent(page.ticker);
    await f.viewExplore(); await settle();
    const cells = [...f.root.innerHTML.matchAll(/data-lab="Position">([^<]*)</g)].map((m) => m[1]);
    assert.deepEqual(cells, ['NO ×1,202 @ 38¢', 'YES ×1,201 @ 38¢'], 'the demo book, then paper');
    assert.doesNotMatch(f.root.innerHTML, /×120[12]\b/);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: the strategy page's small-sample caution says "Only 1,201 trades" in plain words, never "n=1201"`, async () => {
    // "n=" is a statistician's shorthand; the line now says what it counts, with the separator.
    const f = strategyFrontend(detailStrategy({out_of_sample: big, in_sample: {...big, trades: 1}, sample_caution: {min_trades: 3000, gate_min_oos_trades: 1500}}), () => response({}));
    await f.viewStrategy(42); await flush();
    const lines = f.root.querySelectorAll('.luck-flag').map((p) => p.textContent);
    assert.ok(lines.some((l) => /Only 1,201 trades — under 3,000, too few to tell skill from luck \(a caution, stricter than the gate’s floor of 1,500\)/.test(l)), lines.join(' | '));
    assert.ok(lines.some((l) => /Only 1 trade — under 3,000,/.test(l)), lines.join(' | '));
    assert.doesNotMatch(lines.join(' '), /n=|\b1201\b|\b3000\b|\b1500\b/);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: Research counts its running, paused and queued sessions as "1,201"`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {research_running: 1201, research_queued: 1202, research_paused: 1203},
        policy: null, totals: {tried: 5, passed: 1}, v: 'v1'});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const status = plain((f.root.querySelector('#research-status') || f.root.querySelector('#rfigs')).innerHTML);
    for (const n of ['1,201', '1,202', '1,203']) assert.match(status, new RegExp(n));
    assert.doesNotMatch(status, /\b120[123]\b/);
    const said = f.root.querySelector('#rstatus .said');
    // Queued sessions are "queued", the word their cards, Status and loop badge use (it said "waiting").
    if (said) { assert.match(plain(said.innerHTML).replace(/\s+/g, ' '), /1,201 agents researching now · 1,203 paused · 1,202 queued/); assert.doesNotMatch(plain(said.innerHTML), /\b120[123]\b/); }
    f.clearTimers();
  });

  test(`${name}: the dashboard counts the demo book's open positions as "1,201"`, async () => {
    const base = dashboard();
    const d = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response({...base, deployments: [],
      demo: {capital: 1000, equity: 1000, realized_pnl: 3.5, closed_trades: 1, open_positions: 1201, running: 1, open_at_cost: 456.38, open_cost: 456.42}})
      : path.startsWith('/api/track-record') ? response({modes: {}})
        : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
    d.S.me.kalshi_dev_connected = true;
    d.location.pathname = '/';
    await d.viewDashboard(); await settle();
    const html = plain(['#main', '#boardbody'].map((sel) => (d.root.querySelector(sel) || {innerHTML: ''}).innerHTML).join(''));
    assert.match(html, /1,201 open/); assert.doesNotMatch(html, /\b1201\b/);
    d.clearTimers();
  });

  // The pre-registered test's minimum sample, its planned tests and the walk-forward chart's per-slice trade count ("Nt")
  // printed the stored integer as it came ("1201 trades", "1201t") under an abstract that says "1,201 trades".
  test(`${name}: the strategy page's minimum sample, planned tests and walk-forward slice counts read "1,201"`, async () => {
    const f = strategyFrontend(detailStrategy({status: 'passed', experiment: {classification: 'deployment_candidate', null_hypothesis: 'No edge.',
      validation: {n_trades: 3, mean_net_return: 0.02, ci_lo: 0.001, ci_hi: 0.04, p_value: 0.02, equity_curve: [[1000, 0.5], [2000, -0.8], [3000, 1.0]]},
      min_sample: 1201, planned_n_tests: 1201, folds: [{from_ts: 1000, to_ts: 2000, n_trades: 1201, mean_net_return: 0.01}]}}), () => response({}));
    await f.viewStrategy(42); await flush();
    const html = f.root.querySelector('#main').innerHTML;
    assert.match(html, /<dt>Minimum sample<\/dt><dd>1,201 trades<\/dd>/);
    assert.match(html, /<dt>Multiple-testing control<\/dt><dd>1,201 planned tests/);
    const chart = html.slice(html.indexOf('Walk-forward windows'), html.indexOf('</svg>', html.indexOf('Walk-forward windows')));
    assert.match(chart, />1,201t</);
    assert.doesNotMatch(plain(html), /\b1201/);
    if (f.clearTimers) f.clearTimers();
  });
}
