// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the dashboard's
// 15s poll and the Deploy board's 10s poll send back the version of their last full answer; a "same"
// answer is drawn from the kept one with the marks (and each deployment's unrealized P&L, and the data
// ages) it carries put back, so an open position's value still moves, and nothing else is rewritten.
// Funds and Billing poll too (every 30s, paused while hidden, backing off and saying how old their figures
// are while reads fail). Billing's poll reads the figures alone, never the Stripe card list, and the
// statement only when the balance moved; Funds redraws its panels only while nobody is using them.
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

export function moneyPollCases({name, frontend, stripe = () => ({})}) {
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

  // Walk 2026-10-27: the open positions board's Unrealized column had no "as of" time. Each figure says when its mark
  // was read (the engine's mark_ts, with its zone, as Settles is), the time moves with the marks a "same" answer
  // carries, an unmarked position stays "—" with no time, and a figure the answer gives no time for says it is
  // the last mark's.
  test(`${name}: the Deploy board's open positions say when each Unrealized figure was marked`, async () => {
    // The page's own format for a time (settleAt): the clock and zone today, the date too on any other day.
    const at = (iso) => { const d = new Date(iso), today = d.toDateString() === new Date().toDateString();
      return new Intl.DateTimeFormat(undefined, today ? {hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'}
        : {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'}).format(d); };
    const unmarked = pos({id: 12, mark_price: null, mark: null, value: null, unrealized: null, mark_ts: null});
    let answer = {deployments: [dep({open_positions: 2})], open_positions: [pos(), unmarked], recent_closed: [], demo_health: null, v: 'b1'};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/deployments')) return response(answer);
      if (path === '/api/strategies?status=passed') return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const open = f.root.querySelector('#openpos');
    const cells = () => [...open.innerHTML.matchAll(/data-lab="Unrealized">(.*?)<\/td>/g)].map((m) => m[1].replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim());
    assert.deepEqual(cells(), [`+$0.13 as of ${at('2026-10-26T12:00:00Z')}`, '—']);

    // Marked again: the figure and its time move together.
    answer = {v: 'b1', same: true, marks: marks(.52, '2026-10-26T12:05:15Z'), unrealized: {1: null}};
    await pollOf(f, '/api/deployments');
    assert.deepEqual(cells(), [`+$0.41 as of ${at('2026-10-26T12:05:15Z')}`, '—']);
    f.clearTimers();

    // An answer that gives the figure without its time: it is still the last mark's, and says only that.
    answer = {deployments: [dep()], open_positions: [pos({mark_ts: undefined})], recent_closed: [], demo_health: null, v: 'b3'};
    const g = frontend({fetchImpl: (path) => (path.startsWith('/api/deployments') ? response(answer) : response({}))});
    g.location.pathname = '/deploy';
    await g.viewDeploy(); await settle();
    assert.match(g.root.querySelector('#openpos').innerHTML, /\+\$0\.13(<\/span>)?<div class="sub-fig">at the last mark<\/div>/);
    g.clearTimers();
  });

  test(`${name}: back on the tab after a while, the Deploy board reads at once instead of standing on old figures`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/deployments')) return response({deployments: [dep()], open_positions: [pos()], recent_closed: [], demo_health: null, v: 'b1'});
      if (path === '/api/strategies?status=passed') return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const reads = () => f.requests.filter(({path}) => path.startsWith('/api/deployments')).length;
    const flip = async (hidden) => { f.document.hidden = hidden; for (const [type, on] of f.documentListeners) if (type === 'visibilitychange') on({}); await settle(); };
    const before = reads();
    // A glance at another tab and back reads nothing new.
    await flip(true); f.shiftClock(2e3); await flip(false);
    assert.equal(reads(), before);
    // An hour away: the board reads as the tab shows, with no tick of its 10s poll.
    await flip(true); f.shiftClock(3600e3); await flip(false);
    assert.equal(reads(), before + 1);
    f.clearTimers();
  });
  // Billing's page read, as the server sends it for an account with a saved card (configured, Stripe's cards).
  const bill = (o = {}) => ({configured: true, publishable_key: 'synthetic-only', balance: 12.5, spent: 7.5, spent_7d: 3.5, spent_24h: 0.5,
    runway_days: 20, reload_days: null, pace_days: 7, free_bonus: 20, topup_fee_pct: 5.5, autoreload_threshold: 5, autoreload_amount: 20,
    autoreload_charge: 21.1, min_reload_amount: 20, min_reload_threshold: 5, min_topup: 5, max_topup: 1000, default_pm: 'pm_1',
    auto_reload: false, reload_failed: null, min_run_balance: 1, spent_7d_by: {research: 3.5},
    cards: [{id: 'pm_1', brand: 'visa', last4: '4242', exp_month: 4, exp_year: 2029}],
    ledger: [{kind: 'usage', item: 'Research session', model: 'Model A', amount: -0.5, calls: 3, day: '2026-10-27', created_at: '2026-10-27T10:00:00Z'}],
    ledger_cut: false, math: {days: 30, start: 0, bought: 20, purchases: 1, other: 0, usage: 7.5, end: 12.5}, ...o});
  // /api/billing/figures: the same, without the cards and the statement.
  const figures = (d) => { const {cards, ledger, ledger_cut, math, ...rest} = d; return rest; };

  test(`${name}: Billing's figures follow the balance while it is open, never from Stripe, and say how old they are when reads fail`, async () => {
    let now = bill(), failing = false;
    const f = frontend({...stripe(), fetchImpl: (path) => {
      if (path.startsWith('/api/billing?')) return response(bill());
      if (path.startsWith('/api/billing/figures')) {
        if (failing) return response({error: 'Something went wrong on our side.'}, 500);
        return response(path.includes('statement=1') ? {...figures(now), ledger: now.ledger, ledger_cut: false, math: now.math} : figures(now));
      }
      if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
      return response({});
    }});
    f.S.me = {...f.S.me, billing_enabled: true};
    await f.viewBilling(); await settle();
    const main = f.root.querySelector('#main'), figs = () => f.root.querySelector('#bfigs').textContent;
    const pageReads = () => f.requests.filter(({path}) => path.startsWith('/api/billing?') || path === '/api/billing/setup-intent').length;
    const asked = (from) => f.requests.slice(from).map(({path}) => path.replace(/tz=-?\d+/, 'tz=N'));
    assert.match(figs(), /\$12\.50/);
    const mainWrites = main.writes, reads = pageReads();

    // Nothing moved but the day's spend: one figures read, the figures redrawn, the page below left as it is.
    now = bill({spent_24h: 0.9});
    let from = f.requests.length;
    const poll = await pollOf(f, '/api/billing/figures');
    assert.deepEqual(asked(from), ['/api/billing/figures']);
    assert.match(figs(), /\$0\.90 in the last 24 hours/);
    assert.equal(main.writes, mainWrites);

    // A research charge moved the balance: the statement comes along, so its sum ends at the balance shown.
    now = bill({balance: 11.75, spent_7d: 4.25, spent_24h: 1.65, math: {days: 30, start: 0, bought: 20, purchases: 1, other: 0, usage: 8.25, end: 11.75},
      ledger: [{kind: 'usage', item: 'Chat', model: 'Model A', amount: -0.75, calls: 1, day: '2026-10-27', created_at: '2026-10-27T11:00:00Z'}, ...bill().ledger]});
    from = f.requests.length;
    await poll(); await settle();
    assert.deepEqual(asked(from), ['/api/billing/figures', '/api/billing/figures?statement=1&tz=N']);
    assert.match(figs(), /\$11\.75/); assert.doesNotMatch(figs(), /\$12\.50/);
    assert.match(f.root.querySelector('#bledger').innerHTML, /Chat[\s\S]*−\$0\.75/);
    assert.match(f.root.querySelector('#bledger').innerHTML, /\$11\.75/);  // the statement's sum, to the balance shown
    assert.equal(f.S.me.credit_balance, 11.75);
    assert.equal(main.writes, mainWrites);  // the card form, top-up and auto-reload controls stay as they are
    assert.equal(pageReads(), reads);  // never Stripe's card list, never a new card form

    // Reads failing: the figures stay up and, past two intervals, say how old they are.
    failing = true;
    await poll(); await settle();
    f.shiftClock(61e3); await poll(); await settle();
    assert.match(f.root.querySelector('#bill-stale').textContent, /^Last updated 61s ago, retrying$/);
    assert.match(figs(), /\$11\.75/);
    // Hidden: no reads at all.
    failing = false; f.document.hidden = true;
    from = f.requests.length;
    for (let i = 0; i < 6; i++) await poll();
    await settle();
    assert.deepEqual(asked(from), []);
    f.document.hidden = false;
    f.clearTimers();
  });

  test(`${name}: Funds' figures follow the books while it is open, and the panels below wait while you use them`, async () => {
    const book = (cash, lines = []) => ({kalshi: {connected: false}, kalshi_dev: {connected: false}, demo: {capital: 1000, equity: 1001, realized: 1},
      paper: {cash, equity: cash, ledger: [...lines, {created_at: '2026-10-17T10:00:00Z', memo: 'Paper deposit', amount: 1000}]}});
    let now = book(1000), failing = false;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/funds') return failing ? response({error: 'Something went wrong on our side.'}, 500) : response(now);
      return response({});
    }});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const main = f.root.querySelector('#main'), figs = () => f.root.querySelector('#ffigs').textContent;
    assert.match(figs(), /\$1,000\.00/);
    let writes = main.writes;

    // Unchanged: nothing below is rewritten.
    const poll = await pollOf(f, '/api/funds');
    assert.equal(main.writes, writes);
    // A paper trade settled: the figures and the panels below (the paper history) both show it.
    now = book(1012.5, [{created_at: '2026-10-27T11:00:00Z', memo: 'Settled YES', amount: 12.5}]);
    await poll(); await settle();
    assert.match(figs(), /\$1,012\.50/);
    assert.equal(main.writes, writes + 1); writes = main.writes;
    assert.match(main.innerHTML, /Settled YES/);

    // An amount typed in a form: the figures above still move, the form under the user's hands does not.
    const field = f.root.querySelector('#main').querySelectorAll('input').find((x) => x.attributes.name === 'amount');
    field.value = '50';
    now = book(1020, [{created_at: '2026-10-27T11:30:00Z', memo: 'Settled NO', amount: 7.5}, ...book(1012.5, [{created_at: '2026-10-27T11:00:00Z', memo: 'Settled YES', amount: 12.5}]).paper.ledger.slice(0, 1)]);
    await poll(); await settle();
    assert.match(figs(), /\$1,020\.00/);
    assert.equal(main.writes, writes); assert.equal(field.value, '50');
    // Cleared, the next read brings the panels up to date.
    field.value = '';
    await poll(); await settle();
    assert.equal(main.writes, writes + 1);
    assert.match(main.innerHTML, /Settled NO/);

    // Failing reads: the figures stay up and say how old they are.
    failing = true;
    await poll(); await settle();
    f.shiftClock(61e3); await poll(); await settle();
    assert.match(f.root.querySelector('#funds-stale').textContent, /^Last updated 61s ago, retrying$/);
    assert.match(figs(), /\$1,020\.00/);
    // Hidden: no reads.
    failing = false; f.document.hidden = true;
    const before = f.requests.length;
    for (let i = 0; i < 6; i++) await poll();
    await settle();
    assert.equal(f.requests.length, before);
    f.document.hidden = false;
    f.clearTimers();
  });
}
