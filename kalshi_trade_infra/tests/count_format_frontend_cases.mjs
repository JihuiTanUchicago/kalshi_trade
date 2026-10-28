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

export function countFormatCases({name, frontend, detailStrategy, strategyFrontend}) {
  test(`${name}: the Strategies list counts a row's trades as "1,201", in its Trades column and its paper line`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = f.strategySlip(detailStrategy({id: 46, title: 'Busy', out_of_sample: big, hypotheses_tried: 1201,
      deployed: true, books: ['paper'], real: {pnl: 12.5, trades: 1201, open: 0, mode: 'paper'}}), null, {});
    assert.match(row, /data-lab="Trades">1,201</);
    assert.match(row, /data-lab="Ideas tested"[^>]*>1,201</);
    assert.match(plain(row), /1,201 trades/);
    assert.doesNotMatch(plain(row), /1201/);
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
}
