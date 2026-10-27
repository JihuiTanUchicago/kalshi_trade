// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the dashboard's
// 15s poll and the Deploy board's 10s poll send back the version of their last full answer; a "same"
// answer is drawn from the kept one with the marks (and each deployment's unrealized P&L, and the data
// ages) it carries put back, so an open position's value still moves, and nothing else is rewritten.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const dep = (over = {}) => ({id: 1, strategy_id: 1, title: 'Fade tails', market: 'btc15m', mode: 'paper', status: 'running',
  status_reason: null, realized_pnl: 3.5, closed_trades: 8, wins: 5, open_positions: 1, unrealized_pnl: null,
  created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 4, backtest: {out_of_sample: null}, ...over});
const pos = (over = {}) => ({id: 11, deployment_id: 1, title: 'Fade tails', ticker: 'KXBTC15M-26OCT2612-T98', side: 'yes', qty: 4,
  entry_price: .4, entry_fee: .07, mode: 'paper', opened_at: '2026-10-26T11:40:00Z', market_close_time: '2026-10-26T13:00:00Z',
  mark_price: .45, mark: .45, value: 1.8, unrealized: .13, mark_ts: '2026-10-26T12:00:00Z', why: null, ...over});
const marks = (m, ts) => ({11: {mark_price: m, mark: m, value: Math.round(4 * m * 100) / 100, unrealized: Math.round((4 * m - 1.67) * 100) / 100, mark_ts: ts}});

// The interval whose tick asks for `prefix`: the page's own poll.
async function pollOf(f, prefix) {
  for (const tick of [...f.intervals.values()].reverse()) {
    const before = f.requests.length;
    await tick(); await settle();
    if (f.requests.slice(before).some(({path}) => path.startsWith(prefix))) return tick;
  }
  throw new Error('no poll asks for ' + prefix);
}

export function moneyPollCases({name, frontend}) {
  test(`${name}: the dashboard poll sends back its version, and a "same" answer moves only the open position's value`, async () => {
    const dash = (over = {}) => ({paper: {equity: 1001.6, cash: 1000, open_at_cost: 1.6, total_pnl: 1.6, closed_trades: 8, open_positions: 1,
      realized_pnl: 3.5, today_pnl: 0, running: 1, daily: []}, live: {connected: false, closed_trades: 0, open_positions: 0, realized_pnl: 0},
    demo: {equity: 1000, capital: 1000, realized_pnl: 0, closed_trades: 0, open_positions: 0}, deployments: [dep({unrealized_pnl: .13})],
    open_positions: [pos()], recent_closed: [], reconcile: [], freshness: {btc: 30, engine: 4}, agents: {research_running: 0, research_queued: 0},
    v: 'd1', ...over});
    let answer = dash();
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(answer);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      if (path.startsWith('/api/track-record')) return response({modes: {}});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    await f.viewDashboard(); await settle();
    const asked = () => f.requests.filter(({path}) => path.startsWith('/api/dashboard')).at(-1).path;
    assert.doesNotMatch(asked(), /[?&]v=/);
    const board = f.root.querySelector('#boardbody'), main = f.root.querySelector('#main');
    const shown = () => board.innerHTML + main.innerHTML;  // the money figures, wherever the theme puts them
    assert.match(main.innerHTML, /\+\$0\.13/);  // the position and its deployment, marked at 45¢
    const boardWrites = board.writes;

    // The engine marked the position up; nothing else moved: the server says "same" with the marks.
    answer = {v: 'd1', same: true, marks: marks(.52, '2026-10-26T12:00:15Z'), unrealized: {1: .41}, freshness: {btc: 45, engine: 2}};
    const poll = await pollOf(f, '/api/dashboard');
    assert.match(asked(), /[?&]v=d1(&|$)/);
    assert.doesNotMatch(main.innerHTML, /\+\$0\.13/);
    assert.match(main.innerHTML, /\+\$0\.41/);  // both, from the marks the "same" answer carried
    assert.equal(board.writes, boardWrites, 'the money figures above did not change');
    assert.match(shown(), /\$1,001\.60/);  // still the kept answer's paper equity

    // Unchanged again: the same version goes back, and nothing is rewritten.
    const mainWrites = main.writes;
    await poll(); await settle();
    assert.match(asked(), /[?&]v=d1(&|$)/);
    assert.equal(main.writes, mainWrites); assert.equal(board.writes, boardWrites);

    // A trade closed: the full answer is drawn and kept, and the next poll sends its version.
    answer = dash({paper: {...dash().paper, equity: 1002.4, total_pnl: 2.4, closed_trades: 9, open_positions: 0, open_at_cost: 0},
      open_positions: [], deployments: [dep({open_positions: 0, closed_trades: 9})], v: 'd2'});
    await poll(); await settle();
    assert.match(asked(), /[?&]v=d1(&|$)/);
    assert.match(shown(), /\$1,002\.40/);
    assert.doesNotMatch(main.innerHTML, /\+\$0\.(13|41)/);
    answer = {v: 'd2', same: true, marks: {}, unrealized: {1: null}, freshness: {btc: 50, engine: 3}};
    await poll(); await settle();
    assert.match(asked(), /[?&]v=d2(&|$)/);
    assert.match(shown(), /\$1,002\.40/);
    f.clearTimers();
  });

  test(`${name}: the Deploy board poll sends back its version, and a "same" answer reprices the open position and its row`, async () => {
    const full = (over = {}) => ({deployments: [dep()], open_positions: [pos()], recent_closed: [], demo_health: null, v: 'b1', ...over});
    let answer = full();
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/deployments')) return response(answer);
      if (path === '/api/strategies?status=passed') return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const asked = () => f.requests.filter(({path}) => path.startsWith('/api/deployments')).at(-1).path;
    assert.equal(asked(), '/api/deployments');
    const deps = f.root.querySelector('#deps'), open = f.root.querySelector('#openpos'), figs = f.root.querySelector('#dfigs');
    assert.match(open.innerHTML, /\+\$0\.13/); assert.match(deps.innerHTML, /\+\$0\.13/);
    const figWrites = figs.writes;

    // Marked up, nothing else moved: both the position and its deployment's row say +$0.41.
    answer = {v: 'b1', same: true, marks: marks(.52, '2026-10-26T12:00:15Z'), unrealized: {1: null}};
    const poll = await pollOf(f, '/api/deployments');
    assert.equal(asked(), '/api/deployments?v=b1');
    assert.match(open.innerHTML, /\+\$0\.41/); assert.doesNotMatch(open.innerHTML, /\+\$0\.13/);
    assert.match(deps.innerHTML, /\+\$0\.41/); assert.doesNotMatch(deps.innerHTML, /\+\$0\.13/);
    assert.equal(figs.writes, figWrites);

    // The same marks again: nothing is rewritten.
    const writes = [deps.writes, open.writes];
    await poll(); await settle();
    assert.deepEqual([deps.writes, open.writes, figs.writes], [...writes, figWrites]);

    // Paused: the full answer is drawn, and the next poll sends its version.
    answer = full({deployments: [dep({status: 'paused', status_reason: 'By you'})], v: 'b2'});
    await poll(); await settle();
    assert.equal(asked(), '/api/deployments?v=b1');
    assert.ok(deps.querySelector('[data-act="resume"]'));
    answer = {v: 'b2', same: true, marks: marks(.45, '2026-10-26T12:00:30Z'), unrealized: {1: null}};
    await poll(); await settle();
    assert.equal(asked(), '/api/deployments?v=b2');
    assert.ok(deps.querySelector('[data-act="resume"]'));
    assert.match(open.innerHTML, /\+\$0\.13/);
    f.clearTimers();
  });
}
