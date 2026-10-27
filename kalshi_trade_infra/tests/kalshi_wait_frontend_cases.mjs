// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the pages that show a
// Kalshi figure never wait on Kalshi for it. The Deploy board and the strategy page get a demo check that needs the
// demo cash as pending, and ask /api/funds/cash?book=demo, then read again once; a pending cash whose last figure
// is under two minutes old is drawn as current while its follow-up is out (no "checking" flicker once a minute);
// a demo key's save says its balance is being checked, then names it.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const asked = (f, prefix) => f.requests.filter(({path}) => path.startsWith(prefix)).length;
const tick = async (f) => { for (const t of [...f.intervals.values()]) t(); await settle(); };
const ago = (ms) => new Date(Date.now() - ms).toISOString();
const held = () => { let open; const p = new Promise((resolve) => { open = resolve; }); return [p, open]; };

const demoFunds = {code: 'demo_funds', need: 'demo funds: your Kalshi demo account has $0.00',
  line: "Demo isn't trading: your Kalshi demo account has $0.00. Add demo funds on Kalshi's demo site.",
  action: {label: 'Open Kalshi demo', href: 'https://demo.kalshi.co'}};
const demoDep = {id: 2, strategy_id: 2, title: 'Dep 2', market: 'btc15m', mode: 'demo', status: 'running', status_reason: null,
  realized_pnl: 0, closed_trades: 0, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [],
  stake: 5, max_positions: 1, backtest: {}};

export function kalshiWaitCases({name, frontend, detailStrategy}) {
  // ---------- the Deploy board ----------
  const boardFrontend = (answers, demoCash = () => response({book: 'demo', connected: true, balance: 0})) => {
    let n = 0;
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/deployments')) {
        // The server's answer now; "same" when the page already has its version (services.page_poll).
        const now = answers(n++);
        return response(path.includes('v=' + encodeURIComponent(now.v)) ? {v: now.v, same: true, marks: {}, unrealized: {}} : now);
      }
      if (path === '/api/funds/cash?book=demo') return demoCash();
      if (path.startsWith('/api/strategies?status=passed')) return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    return f;
  };
  const board = (over) => ({deployments: [demoDep], open_positions: [], demo_health: null, ...over});

  test(`${name}: the Deploy board's pending demo check reads the demo cash once and the board once more`, async () => {
    // The server read nothing from Kalshi: pending. Once the demo cash is in, its memo answers the check.
    let read = false;
    const f = boardFrontend(() => read ? board({demo_health: demoFunds, v: 'b2'}) : board({demo_health_pending: true, v: 'b1'}),
      () => { read = true; return response({book: 'demo', connected: true, balance: 0}); });
    await f.viewDeploy(); await settle();
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1, 'the pending check asked for the demo cash');
    assert.equal(asked(f, '/api/deployments'), 2, 'and read the board again once it was in');
    assert.match(f.root.querySelector('#demo-health').innerHTML, /your Kalshi demo account has \$0\.00/);
    // The 10s poll: unchanged ("same"), nothing more to ask.
    await tick(f);
    assert.equal(asked(f, '/api/deployments'), 3);
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
    f.clearTimers();
  });

  test(`${name}: a Deploy board still pending after its demo cash read waits for the poll, never a loop`, async () => {
    const f = boardFrontend((n) => board({demo_health_pending: true, v: 'p' + n}));
    await f.viewDeploy(); await settle();
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
    assert.equal(asked(f, '/api/deployments'), 2);
    assert.equal(f.root.querySelector('#demo-health').innerHTML, '', 'an unknown demo cash is never a problem');
    f.clearTimers();
  });

  test(`${name}: a Deploy board with nothing pending never asks for the demo cash`, async () => {
    const f = boardFrontend(() => board({demo_health: demoFunds, v: 'k1'}));
    await f.viewDeploy(); await settle();
    await tick(f);
    assert.equal(asked(f, '/api/funds/cash'), 0);
    assert.match(f.root.querySelector('#demo-health').innerHTML, /has \$0\.00/);
    f.clearTimers();
  });

  test(`${name}: the Deploy board takes the demo cash read the shell started early (boot.js)`, async () => {
    const f = boardFrontend(() => board({demo_health: demoFunds, v: 'b2'}));
    f.window.__TAU_FIRST__ = [{url: '/api/deployments', body: board({demo_health_pending: true, v: 'b1'}), then: ['/api/funds/cash?book=demo']}];
    f.window.__TAU_EARLY__ = {'/api/funds/cash?book=demo': Promise.resolve(response({book: 'demo', connected: true, balance: 0}))};
    await f.viewDeploy(); await settle();
    assert.equal(asked(f, '/api/funds/cash'), 0, 'the shell started it');
    assert.equal(asked(f, '/api/deployments'), 1, 'one read after the carried one');
    assert.match(f.root.querySelector('#demo-health').innerHTML, /has \$0\.00/);
    f.clearTimers();
  });

  // ---------- the strategy page ----------
  test(`${name}: the strategy page's pending demo rung reads the demo cash, then the strategy once, and redraws the ladder`, async () => {
    const paper = {id: 1, mode: 'paper', status: 'running', closed_trades: 4, realized_pnl: 1.9, open_positions: 0, stake: 5, created_at: '2026-10-20T08:00:00Z'};
    const [demoHeld, answerDemo] = held();
    let reads = 0;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/strategies/42') {
        reads++;
        return response(detailStrategy(reads === 1 ? {deployments: [paper], demo_health: null, demo_health_pending: true}
          : {deployments: [paper], demo_health: demoFunds}));
      }
      if (path === '/api/strategies/42/dev-curve') return response({dev_curve: []});
      if (path === '/api/funds/cash?book=demo') return demoHeld.then(() => response({book: 'demo', connected: true, balance: 0}));
      return response({error: 'down'}, 503);
    }});
    await f.viewStrategy(42); await settle();
    const ladder = () => f.root.querySelector('#ladder-body').innerHTML;
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
    assert.match(ladder(), /Next rung, demo: checking your Kalshi demo account…/, 'not "nothing needed" while it is unknown');
    assert.doesNotMatch(ladder(), /nothing needed/);
    answerDemo(); await settle();
    assert.equal(reads, 2, 'read once more, once the demo cash was in');
    assert.match(ladder(), /Next rung, demo: needs demo funds: your Kalshi demo account has \$0\.00\./);
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
    f.clearTimers && f.clearTimers();
  });

  test(`${name}: a strategy page whose demo rung isn't pending, or stays unknown, never loops`, async () => {
    const paper = {id: 1, mode: 'paper', status: 'running', closed_trades: 4, realized_pnl: 1.9, open_positions: 0, stake: 5, created_at: '2026-10-20T08:00:00Z'};
    for (const [over, demoReads, pageReads] of [[{demo_health: null}, 0, 1], [{demo_health: null, demo_health_pending: true}, 1, 2]]) {
      let reads = 0;
      const f = frontend({fetchImpl: (path) => {
        if (path === '/api/strategies/42') { reads++; return response(detailStrategy({deployments: [paper], ...over})); }
        if (path === '/api/strategies/42/dev-curve') return response({dev_curve: []});
        if (path === '/api/funds/cash?book=demo') return response({error: 'Traceback: RuntimeError'}, 500);
        return response({error: 'down'}, 503);
      }});
      await f.viewStrategy(42); await settle();
      assert.equal(asked(f, '/api/funds/cash?book=demo'), demoReads);
      assert.equal(reads, pageReads);
      // Still unknown after its one re-read: the rung reads as it always has for an unknown demo cash.
      assert.match(f.root.querySelector('#ladder-body').innerHTML, /Next rung, demo: nothing needed/);
      assert.doesNotMatch(f.root.querySelector('#main').innerHTML, /Traceback|RuntimeError/);
      f.clearTimers && f.clearTimers();
    }
  });

  test(`${name}: a demo book on the strategy ladder says its demo account is being checked, not "running", while its check is pending`, async () => {
    const paper = {id: 1, mode: 'paper', status: 'running', closed_trades: 4, realized_pnl: 1.9, open_positions: 0, stake: 5, created_at: '2026-10-20T08:00:00Z'};
    const demo = {id: 3, mode: 'demo', status: 'running', closed_trades: 0, realized_pnl: 0, open_positions: 0, stake: 5, created_at: '2026-10-21T08:00:00Z'};
    for (const [after, said] of [[null, /<span class="mk dep">Demo<\/span> running\u00a0· /],
      [demoFunds, /<span class="mk dep">Demo<\/span> no closed trades yet\u00a0· .*demo-health">Demo isn&#39;t trading: your Kalshi demo account has \$0\.00/]]) {
      const [demoHeld, answerDemo] = held();
      let reads = 0;
      const f = frontend({fetchImpl: (path) => {
        if (path === '/api/strategies/42') {
          reads++;
          return response(detailStrategy(reads === 1 ? {deployments: [paper, demo], demo_health: null, demo_health_pending: true}
            : {deployments: [paper, demo], demo_health: after}));
        }
        if (path === '/api/strategies/42/dev-curve') return response({dev_curve: []});
        if (path === '/api/funds/cash?book=demo') return demoHeld.then(() => response({book: 'demo', connected: true, balance: 0}));
        return response({error: 'down'}, 503);
      }});
      await f.viewStrategy(42); await settle();
      const ladder = () => f.root.querySelector('#ladder-body').innerHTML;
      assert.match(ladder(), /<span class="mk dep">Demo<\/span> checking your Kalshi demo account…\u00a0· /);
      assert.doesNotMatch(ladder(), /Demo<\/span> running/, 'not "running" before its demo check is in');
      assert.match(ladder(), /<span class="mk ?">Paper<\/span> running\u00a0· /, 'the paper book is unaffected');
      answerDemo(); await settle();
      assert.equal(reads, 2);
      assert.match(ladder(), said);
      assert.doesNotMatch(ladder(), /checking your Kalshi demo account/);
      f.clearTimers && f.clearTimers();
    }
  });

  // ---------- no "checking" flicker under two minutes ----------
  const dashAnswer = (live, v) => ({
    paper: {equity: 1001.6, cash: 1000, open_at_cost: 1.6, total_pnl: 1.6, closed_trades: 8, open_positions: 0,
      realized_pnl: 3.5, today_pnl: 0, running: 0, daily: []},
    live: {connected: true, balance: null, funding_url: 'https://kalshi.com/account/funding', closed_trades: 0,
      open_positions: 0, open_at_cost: 0, realized_pnl: 0, today_pnl: 0, running: 0, ...live},
    demo: {equity: 1000, capital: 1000, realized_pnl: 0, closed_trades: 0, open_positions: 0, health: null},
    deployments: [], open_positions: [], recent_closed: [], reconcile: [], freshness: {btc: 30, engine: 4},
    agents: {research_running: 0, research_queued: 0}, v});
  const dashCash = (f) => {
    const box = [...f.root.querySelectorAll('div.m')].find((el) => /Kalshi cash/.test(el.textContent));
    return box ? box.textContent.replace(/\s+/g, ' ') : '';
  };

  test(`${name}: the dashboard poll that finds the cash memo just run out keeps the figure, no "checking", while it reads`, async () => {
    let answer = dashAnswer({balance: 1234.56, balance_at: ago(5000)}, 'k1');
    const [liveHeld, answerLive] = held();
    let liveReads = 0;  // the first follow-up is held, then answered; a later one stays out
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard')
      ? response(path.includes('v=' + answer.v) ? {v: answer.v, same: true, marks: {}, unrealized: {}} : answer)
      : path === '/api/funds/cash?book=live' ? (++liveReads === 1 ? liveHeld.then(() => response({book: 'live', connected: true, balance: 1300, balance_at: ago(0)})) : new Promise(() => {}))
        : path.startsWith('/api/track-record') ? response({modes: {}})
          : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
    f.S.me.user.autopilot = false; f.S.ap = null; f.S.apAt = 0;
    f.location.pathname = '/';
    await f.viewDashboard(); await settle();
    assert.match(dashCash(f), /Kalshi cash ?\$1,234\.56/);
    // A minute on: the poll's answer is pending, its last figure read 61s ago. The follow-up is out (held).
    answer = dashAnswer({pending: true, last_balance: 1234.56, last_balance_at: ago(61000)}, 'p2');
    await tick(f);
    assert.equal(asked(f, '/api/funds/cash?book=live'), 1, 'the follow-up is still asked');
    assert.match(dashCash(f), /Kalshi cash ?\$1,234\.56/);
    assert.doesNotMatch(dashCash(f), /[Cc]hecking|Asking Kalshi|Read 1m ago/);
    answerLive(); await settle();
    assert.match(dashCash(f), /Kalshi cash ?\$1,300\.00/);
    // Truly stale (over two minutes): its age and the check are said.
    answer = dashAnswer({pending: true, last_balance: 1300, last_balance_at: ago(3 * 60000)}, 'p3');
    await tick(f);
    assert.match(dashCash(f), /\$1,300\.00 ?Read 3m ago; checking Kalshi for the latest…/);
    f.clearTimers();
  });

  test(`${name}: the dashboard's Kalshi cash figure says when Kalshi's figure was read`, async () => {
    for (const [live, said] of [
      [{balance: 1234.56, balance_at: ago(5 * 60000)}, /Kalshi cash ?\$1,234\.56 ?Read from Kalshi 5m ago · Your real money at Kalshi: Tau hasn’t placed a live trade yet/],
      [{balance: 1234.56, balance_at: ago(5 * 60000), closed_trades: 2, realized_pnl: 1.5, open_positions: 1},
        /\$1,234\.56 ?Read from Kalshi 5m ago · Tau trades: 1 open/],
      [{balance: 1234.56}, /Kalshi cash ?\$1,234\.56 ?Your real money at Kalshi: Tau hasn’t placed a live trade yet/],
    ]) {
      const answer = dashAnswer(live, 'r1');
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response(answer)
        : path.startsWith('/api/track-record') ? response({modes: {}})
          : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
      f.S.me.user.autopilot = false; f.S.ap = null; f.S.apAt = 0;
      f.location.pathname = '/';
      await f.viewDashboard(); await settle();
      assert.match(dashCash(f), said);
      assert.equal(asked(f, '/api/funds/cash'), 0, 'a kept figure asks no follow-up');
      f.clearTimers();
    }
  });

  const fundsAnswer = (kalshi, dev) => ({
    kalshi: {connected: true, balance: null, key_id: 'LIVE…1234', funding_url: 'https://kalshi.com/account/funding',
      closed_trades: 1, realized_pnl: -1.25, open_positions: 0, open_at_cost: 0, ...kalshi},
    kalshi_dev: {connected: true, balance: null, key_id: 'DEVK…5678', copies_from: 100, ...dev},
    demo: {capital: 1000, equity: 1003.5, realized: 3.5, closed_trades: 1, open_positions: 0, open_at_cost: 0},
    paper: {cash: 2001.75, equity: 2001.75, realized_pnl: 5.61, closed_trades: 2, open_positions: 0, open_at_cost: 0,
      ledger: [{created_at: '2026-10-17T10:00:00Z', memo: 'Paper deposit', amount: 1000}]},
  });
  const liveFig = (f) => f.root.querySelector('#ffigs').querySelectorAll('div.m')[0].textContent.replace(/\s+/g, ' ');

  test(`${name}: a connected live key says live trading isn’t open while it isn’t, on the dashboard and Funds`, async () => {
    // Walk 2026-10-27 (a live key connected, live trading closed): Funds read "Tau’s live P&L shows once a live trade
    // closes. No open live positions", as if a live trade could close, with no stop at the end; the dashboard read
    // "Your Kalshi cash — real money untouched", untouched by what it didn’t say.
    for (const open of [false, true]) {
      const answer = dashAnswer({balance: 250, balance_at: ago(5000)}, 'r9');
      const d = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response(answer)
        : path.startsWith('/api/track-record') ? response({modes: {}})
          : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
      d.S.me.live_trading_available = open; d.S.me.user.autopilot = false; d.S.ap = null; d.S.apAt = 0;
      d.location.pathname = '/';
      await d.viewDashboard(); await settle();
      assert.match(dashCash(d), open ? /Your real money at Kalshi: Tau hasn’t placed a live trade yet/
        : /Your real money at Kalshi: live trading isn’t open yet, so Tau places no trades there/);
      assert.doesNotMatch(dashCash(d), /untouched/);
      d.clearTimers();
      const f = frontend({fetchImpl: () => response({})});
      f.S.me.live_trading_available = open;
      f.location.pathname = '/funds';
      f.window.__TAU_FIRST__ = [{url: '/api/funds', body: fundsAnswer({balance: 250, balance_at: ago(5000), closed_trades: 0, realized_pnl: 0})}];
      await f.viewFunds(); await settle();
      assert.match(liveFig(f), open ? /Tau’s live P&(amp;)?L shows once a live trade closes\. No open live positions\.\s*$/
        : /Live trading isn’t open yet, so Tau places no live trades\.\s*$/);
      // Walk 2026-10-27: closed, with nothing open, it went on "No open live positions.", which the sentence before had said.
      if (!open) assert.doesNotMatch(liveFig(f), /No open live positions/);
      f.clearTimers();
    }
    // Something still open at Kalshi is said whether or not live trading is open.
    const f = frontend({fetchImpl: () => response({})});
    f.S.me.live_trading_available = false;
    f.location.pathname = '/funds';
    f.window.__TAU_FIRST__ = [{url: '/api/funds', body: fundsAnswer({balance: 250, balance_at: ago(5000), closed_trades: 0, realized_pnl: 0,
      open_positions: 1, open_at_cost: 2.93})}];
    await f.viewFunds(); await settle();
    assert.match(liveFig(f), /Live trading isn’t open yet, so Tau places no live trades\. 1 open live position \(\$2\.93 at cost[^)]*\) not included\.\s*$/);
    f.clearTimers();
  });
  const spot = (f, name) => f.root.querySelector(`[data-cash="${name}"]`).innerHTML;

  test(`${name}: Funds draws a cash read under two minutes ago as current while its follow-up is out, an older one as checking`, async () => {
    for (const [age, current] of [[61000, true], [110000, true], [130000, false]]) {
      const at = ago(age);
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/funds/cash') ? new Promise(() => {}) : response({})});
      f.location.pathname = '/funds';
      f.window.__TAU_FIRST__ = [{url: '/api/funds', body: fundsAnswer({pending: true, last_balance: 900, last_balance_at: at},
        {pending: true, last_balance: 250, last_balance_at: at})}];
      await f.viewFunds(); await settle();
      assert.equal(asked(f, '/api/funds/cash?book=live'), 1, 'the follow-up is asked either way');
      assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
      if (current) {
        assert.match(liveFig(f), /Kalshi cash ?\$900\.00 ?Your real cash at Kalshi, read 1m ago\.|Kalshi cash ?\$900\.00 ?Real money at Kalshi, read 1m ago\./, String(age));
        assert.doesNotMatch(liveFig(f), /[Cc]hecking/);
        assert.equal(spot(f, 'live-cell'), '$900.00');
        assert.match(spot(f, 'demo-ok'), /Connected ✓<\/b> \(Kalshi demo account cash \$250\.00, read 1m ago\)/);
      } else {
        assert.match(liveFig(f), /Kalshi cash ?\$900\.00 ?Read 2m ago; checking Kalshi for the latest…/);
        assert.equal(spot(f, 'live-cell'), '$900.00, read 2m ago; checking…');
        assert.match(spot(f, 'demo-ok'), /Kalshi demo account cash \$250\.00, read 2m ago; checking for the latest…/);
      }
      f.clearTimers();
    }
  });

  test(`${name}: a Funds poll that lands while a cash follow-up is out and doesn't repaint still gets that follow-up's figure`, async () => {
    for (const typing of [false, true]) {
      const [liveHeld, answerLive] = held();
      const [demoHeld, answerDemo] = held();
      let polls = 0;
      const f = frontend({fetchImpl: (path) => {
        if (path === '/api/funds') { polls++; return response(fundsAnswer({pending: true}, {pending: true})); }
        if (path === '/api/funds/cash?book=live') return liveHeld.then(() => response({book: 'live', connected: true, balance: 1300, balance_at: ago(0)}));
        if (path === '/api/funds/cash?book=demo') return demoHeld.then(() => response({book: 'demo', connected: true, balance: 250, balance_at: ago(0)}));
        return response({});
      }});
      f.location.pathname = '/funds';
      await f.viewFunds(); await settle();
      assert.match(liveFig(f), /Kalshi cash ?Checking…/);
      assert.equal(asked(f, '/api/funds/cash?book=live'), 1);
      if (typing) f.root.querySelector('#paper input[name=amount]').value = '25';  // someone is using the panels
      // The 30s poll: the same pending answer, so the panels aren't repainted and no follow-up of its own is asked.
      await tick(f);
      assert.equal(polls, 2, 'the poll read Funds');
      assert.equal(asked(f, '/api/funds/cash?book=live'), 1, 'no second follow-up');
      assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
      answerLive(); answerDemo(); await settle();
      assert.match(liveFig(f), /Kalshi cash ?\$1,300\.00/, 'the follow-up out at the poll lands');
      assert.doesNotMatch(liveFig(f), /[Cc]hecking/);
      assert.equal(spot(f, 'live-cell'), '$1,300.00');
      assert.match(spot(f, 'demo-ok'), /Kalshi demo account cash \$250\.00/);
      assert.equal(polls, 2, 'filled in place, not read again');
      if (typing) assert.equal(f.root.querySelector('#paper input[name=amount]').value, '25', 'what was typed stays');
      f.clearTimers();
    }
  });

  test(`${name}: a follow-up out at a poll never fills a newer answer that has its own figure`, async () => {
    const [liveHeld, answerLive] = held();
    let polls = 0;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/funds') {
        polls++;
        return response(polls === 1 ? fundsAnswer({pending: true}, {connected: false}) : fundsAnswer({balance: 1500, balance_at: ago(0)}, {connected: false}));
      }
      if (path === '/api/funds/cash?book=live') return liveHeld.then(() => response({book: 'live', connected: true, balance: 1300, balance_at: ago(0)}));
      return response({});
    }});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    await tick(f);
    assert.match(liveFig(f), /Kalshi cash ?\$1,500\.00/);
    answerLive(); await settle();
    assert.match(liveFig(f), /Kalshi cash ?\$1,500\.00/, 'the newer figure stands');
    f.clearTimers();
  });

  // ---------- the demo key's save ----------
  test(`${name}: saving a demo key says its balance is being checked, then names it once the follow-up is back`, async () => {
    const PEM = '-----BEGIN RSA PRIVATE KEY-----\nMIIEsecretsecretsecret\n-----END RSA PRIVATE KEY-----';
    const KID = 'a952bcbe-ec3b-4b5b-b8f9-11dae589608c';
    for (const [answer, said] of [
      [() => response({book: 'demo', connected: true, balance: 250, balance_at: ago(0)}),
        /Connected ✓ \(Kalshi demo account cash \$250\.00\)\. Kalshi’s demo exchange confirmed the key\./],
      [() => response({error: 'Traceback (most recent call last): RuntimeError: demo read timed out'}, 500),
        /Connected ✓\. Kalshi’s demo exchange confirmed the key\. Tau couldn’t read its balance just now\. Reload in a minute to try again\./],
    ]) {
      let saved = false;
      const [demoHeld, answerDemo] = held();
      const f = frontend({fetchImpl: (path) => {
        if (path === '/api/funds') return response(fundsAnswer({connected: false}, saved ? {pending: true} : {connected: false}));
        if (path === '/api/kalshi-dev-key') { saved = true; return response({ok: true}); }
        if (path === '/api/funds/cash?book=demo') return demoHeld.then(answer);
        return response({});
      }});
      f.location.pathname = '/funds';
      await f.viewFunds(); await settle();
      const form = f.root.querySelector('#kalshi-dev');
      form.key_id = {value: KID}; form.private_key = {value: PEM};
      await form.onsubmit({preventDefault() {}}); await settle();
      const flashText = () => f.root.querySelector('#kdflash').innerHTML;
      assert.match(flashText(), /class="notice good"/);
      assert.match(flashText(), /Connected ✓\. Kalshi’s demo exchange confirmed the key\. Checking its balance…/);
      assert.equal(asked(f, '/api/funds/cash?book=demo'), 1, 'one read of the new key’s demo cash');
      answerDemo(); await settle();
      assert.match(flashText(), said);
      assert.doesNotMatch(flashText(), /Checking|Traceback|RuntimeError|timed out|MIIE/);
      f.clearTimers();
    }
  });

  test(`${name}: a demo key's balance that comes back after something else was said there leaves that alone`, async () => {
    let saved = false;
    const [demoHeld, answerDemo] = held();
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/funds') return response(fundsAnswer({connected: false}, saved ? {pending: true} : {connected: false}));
      if (path === '/api/kalshi-dev-key') { saved = true; return response({ok: true}); }
      if (path === '/api/funds/cash?book=demo') return demoHeld.then(() => response({book: 'demo', connected: true, balance: 250}));
      return response({});
    }});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const form = f.root.querySelector('#kalshi-dev');
    form.key_id = {value: 'a952bcbe-ec3b-4b5b-b8f9-11dae589608c'}; form.private_key = {value: '-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----'};
    await form.onsubmit({preventDefault() {}}); await settle();
    f.root.querySelector('#kdflash').innerHTML = '<div class="notice good"><span>Something newer.</span></div>';
    answerDemo(); await settle();
    assert.match(f.root.querySelector('#kdflash').innerHTML, /Something newer\./);
    f.clearTimers();
  });
}
