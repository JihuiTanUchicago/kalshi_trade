// Shared cases, run against each bundle's offline harness (Tau and Meridian): a brand-new customer's first hour,
// walked on 2026-10-27 at 390px and 1280px from sign-up through the first research session, the first paper
// deployment and the first closed paper trade. Each case is a place where the page said something the account
// hadn't done yet, or showed a figure as $0.00 where "None yet" is what is true.
import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));

const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const firstDep = (o = {}) => ({id: 1, strategy_id: 11, title: 'Momentum after sharp moves', market: 'btc15m', mode: 'paper', status: 'running',
  status_reason: null, realized_pnl: 0, closed_trades: 0, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-27T22:05:34Z',
  curve: [], stake: 5, max_positions: 4, backtest: {out_of_sample: {trades: 60, pnl: 0.9}, capital: 10}, ...o});

export function newUserCases({name, frontend, detailStrategy, strategyFrontend, dashboard, billingPage, cardedBilling, apStatus}) {
  const meridian = name === 'Meridian';
  const pageFile = (page) => readFileSync(new URL(`../app/static/${meridian ? 'app.meridian-' : 'app-'}${page}.js`, import.meta.url), 'utf8');

  const session = (o) => ({id: 9, status: 'running', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Momentum after sharp Bitcoin moves',
    hypotheses_tried: 0, strategies_passed: 0, spent_usd: 0, error: null, created_at: '2026-10-27T22:03:00Z', started_at: '2026-10-27T22:03:00Z',
    stop_reason: null, by_autopilot: 1, brief: 1, run_forever: 1, ...o});
  const example = session({id: 4, status: 'succeeded', example: true, by_autopilot: 0, hypotheses_tried: 2, spent_usd: null,
    prompt: 'Example idea', created_at: '2026-10-27T21:57:00Z', stop_reason: 'limit'});
  const researchPage = async (runs, autopilot) => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs, counts: {research_running: runs.filter((r) => r.status === 'running').length, research_queued: 0, research_paused: 0},
        policy: null, totals: {tried: 0, passed: 0}, v: 'v1'});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot, mode: autopilot ? 'paper' : 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = autopilot;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    return f;
  };

  // With autopilot on, Research said nothing about it: "Researching now 0" while it reviewed, and Strategies' "See its
  // research" led here to the example alone. It says where its sessions show up; with autopilot off, the nudge stays.
  test(`${name}: Research with autopilot on says where its sessions show up`, async () => {
    const shown = (el) => !!el && el.getAttribute('hidden') === null && !el.hidden;
    const on = await researchPage([example], true);
    const line = on.root.querySelector('.research-ap-on');
    assert.equal(line.textContent, 'Autopilot is on: the sessions it starts are listed below with an Autopilot tag. You can still start a session of your own.');
    assert.ok(shown(line), 'shown while autopilot is on');
    // Its own class: the switch's copy sync hides every .research-ap (the Turn on nudge) once autopilot is on.
    assert.ok(!line.classes.has('research-ap'));
    // Off: the nudge shows and the line is drawn hidden, for the switch's copy sync ([data-ap-next]) to show once it is on.
    const off = await researchPage([example], false);
    assert.match(off.root.querySelector('#main').innerHTML, /Rather not write ideas yourself\?/);
    const hiddenLine = off.root.querySelector('.research-ap-on');
    assert.ok(!shown(hiddenLine)); assert.notEqual(hiddenLine.getAttribute('data-ap-next'), null);
  });

  // A first autopilot session before its first model call is billed: its row and its page read "Spent so far: $0.00".
  test(`${name}: a running session that has spent nothing says so, not "Spent so far: $0.00"`, async () => {
    const f = await researchPage([session(), example], true);
    const main = ['#runs', '#active-research'].map((s) => f.root.querySelector(s)).filter(Boolean).map((el) => el.innerHTML + el.children.map((c) => c.innerHTML).join('')).join('');
    assert.match(main, /Spent so far(?::|<\/dt><dd>) ?(?:nothing yet|None yet)/);
    assert.doesNotMatch(main, /Spent so far(?::|<\/dt><dd>) ?\$0\.00/);
    // Meridian's example row keeps its note under its title, not crammed into the narrow Market column.
    if (meridian) {
      const row = f.root.querySelector('#runs').children.find((el) => el.getAttribute('href') === '/research/4');
      assert.match(row.querySelector('.run-note').textContent, /An example Tau ran for you when you signed up\. It cost you nothing\./);
      assert.doesNotMatch(row.querySelector('.run-meta').textContent, /An example/);
    }
    const page = async (r) => {
      const g = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9') ? response({run: r, events: [], strategies: []}) : response({})});
      await g.viewRun(9); await flush(); g.clearTimers();
      return g.root.querySelector('#runfigs').textContent;
    };
    assert.match(await page(session()), /Spent so far\s*None yet/);
    assert.match(await page(session({spent_usd: 0.003})), /Spent so far\s*under \$0\.01/);
    assert.match(await page(session({spent_usd: 0.4})), /Spent so far\s*\$0\.40/);
    assert.match(await page(session({status: 'succeeded', spent_usd: 0.83, hypotheses_tried: 2, strategies_passed: 1, finished_at: '2026-10-27T22:05:00Z'})), /Cost\s*\$0\.83/);
  });

  // Autopilot's first session running: Last 24 hours said "It started 1 research session" while the card's week said
  // "nothing yet ... once it starts". While a session runs (and nothing in the week has landed) it says that.
  test(`${name}: the autopilot card's empty week says a session is running instead of "once it starts"`, async () => {
    const zero = {research_credits: 0, tested: 0, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0,
      checkin_credits: 0, credits_left: 20, runway_days: null, pace_days: 0.01, card_charged: false};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/dashboard') return response(dashboard());
      if (path === '/api/autopilot/status') return response({...apStatus, week: zero});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      return response({});
    }});
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    const week = () => f.root.querySelector('#dash-ap .ap-week').textContent.trim();
    f.S.ap = {...apStatus, week: zero, research: {...apStatus.research, active: ['Bitcoin up or down in 15 minutes']}}; f.paintDashAp();
    assert.equal(week(), 'Last 7 days: a research session is running and none has finished yet. What it tests, puts on paper and spends shows here as it goes.');
    f.S.ap = {...apStatus, week: zero, research: {...apStatus.research, active: []}}; f.paintDashAp();
    assert.match(week(), /^Last 7 days: nothing yet\. Its research, paper strategies and credits spent show here once it starts\.$/);
    f.clearTimers();
  });

  // A new account with autopilot off and no session of its own: the empty paper record said "Deploy a passed strategy
  // on paper" over a "Start a research session" button, and it had no passed strategy. It says where one comes from.
  test(`${name}: an empty paper record doesn't ask a new account to deploy a strategy it doesn't have`, () => {
    const f = frontend(), th = {min_sharpe_days: 30};
    f.S.me = {user: {autopilot: false}};
    f.S.dashDeps = 0; f.S.dashNoSessions = true;
    const fresh = f.trackRecordPanel({trades: 0, label: 'Paper'}, 'paper', th);
    assert.match(fresh, /Nothing has run on paper yet: a strategy gets there by passing its tests in a research session\. Every closed trade is recorded here\./);
    assert.match(fresh, /href="\/research\?new=1">(?:Start a research session|New session)</);
    assert.doesNotMatch(fresh, /Deploy a passed strategy/);
    // With a session of its own (a passed strategy may be waiting), it still points at deploying one.
    f.S.dashNoSessions = false;
    assert.match(f.trackRecordPanel({trades: 0, label: 'Paper'}, 'paper', th), /Deploy a passed strategy on paper\./);
  });

  // A new account has spent nothing: Billing read "Spent, last 7 days $0.00 · $0.00 in the last 24 hours · $0.00 all
  // time" under its free credits. It says none yet and what will draw on them; once something is spent, the figures.
  test(`${name}: Billing says nothing is spent yet on a new account, not three $0.00 figures`, async () => {
    const welcome = [{kind: 'bonus', amount: 20, memo: 'Welcome credits', created_at: '2026-10-27T21:57:00Z'}];
    let f = billingPage(cardedBilling({balance: 20, spent: 0, spent_7d: 0, spent_24h: 0, runway_days: null, pace_days: null, card_charged: false, ledger: welcome}));
    await f.viewBilling(); await flush();
    let figs = f.root.querySelector('#bfigs').textContent;
    assert.match(figs, /Spent so far\s*None yet\s*research sessions and chat draw on your credits as they run/);
    assert.doesNotMatch(figs, /\$0\.00|Spent, last 7 days/);
    // Walk 2026-10-28: the welcome credit says what it is in both themes (Meridian's had no line under it).
    assert.match(figs, /Welcome credit\s*\$\d+\.00\s*one-time, free/);
    f = billingPage(cardedBilling({spent: 0.83, spent_7d: 0.83, spent_24h: 0.83}));
    await f.viewBilling(); await flush();
    figs = f.root.querySelector('#bfigs').textContent;
    assert.match(figs, /Spent, last 7 days\s*\$0\.83\s*\$0\.83 in the last 24 hours · \$0\.83 all time/);
    // The statement's key ("one session’s model calls") and the research form's card note write a curly apostrophe.
    assert.match(pageFile('billing'), /one session’s model calls that day/);
    assert.doesNotMatch(pageFile('billing') + pageFile('research'), /one session's model calls that day; open it|won't be charged until/);
  });

  // The first paper deployment, before its first trade closes. Deploy's summary said "Realized: None yet" above a row
  // reading "$0.00", and the dashboard's card (Meridian's monitor) said "$0.00" too. Once a trade closes it is a figure.
  test(`${name}: a deployment with no closed trade reads "None yet" for its realized P&L, on Deploy and the dashboard`, async () => {
    for (const [d, said] of [[firstDep(), /None yet/], [firstDep({realized_pnl: 5.73, closed_trades: 1}), /\+\$5\.73/]]) {
      const f = frontend({fetchImpl: (path) => {
        if (path === '/api/deployments') return response({deployments: [d], open_positions: []});
        if (path === '/api/dashboard') return response({...dashboard(), deployments: [d]});
        return response({});
      }});
      f.location.pathname = '/deploy';
      await f.viewDeploy(); await settle();
      const cell = f.root.querySelector('#deps td[data-lab="Realized"]').innerHTML;
      assert.match(cell, said); assert.doesNotMatch(cell, d.closed_trades ? /None yet/ : /\$0\.00/);
      f.location.pathname = '/';
      await f.viewDashboard(); await settle();
      const dash = meridian ? f.root.querySelector('.monitor-realized dd').innerHTML : f.root.querySelector('#dash-deps td[data-lab="Realized"]').innerHTML;
      assert.match(dash, said); assert.doesNotMatch(dash, d.closed_trades ? /None yet/ : /\$0\.00/);
    }
  });

  // A research session's strategy has no Return on capital, so its page shows three figures. Meridian's grid had four
  // columns and left an empty slot at the end; it now takes the count, on first paint and after a what-if redraw.
  test(`${name}: a strategy page's figure row says how many figures it holds, so three fill the row`, {skip: !meridian}, async () => {
    const exp = {classification: 'deployment_candidate', validation: {n_trades: 132, net_pnl: 20.46, mean_net_return: 0.031}};
    const result = {in_sample: {pnl: 5, trades: 40}, out_of_sample: null, equity: [[100, 0], [300, 5]], gates: [], passed: true};
    const f = strategyFrontend(detailStrategy({status: 'passed', out_of_sample: null, experiment: exp}), () => response(result));
    await f.viewStrategy(42); await flush();
    const figs = f.root.querySelector('#figs');
    assert.equal(figs.querySelectorAll('dt').length, 3);
    assert.equal(figs.getAttribute('data-cols'), '3');
    const wi = f.root.querySelector('#whatif');
    wi.querySelector('#wf').value = '0'; wi.querySelector('#ws').value = '0';
    wi.querySelector('#wf').oninput();
    await [...f.timeouts.values()].at(-1)();
    assert.equal(f.root.querySelector('#figs').getAttribute('data-cols'), '3');
    // An older backtest's strategy keeps its four.
    const old = strategyFrontend(detailStrategy({status: 'passed'}), () => response({}));
    await old.viewStrategy(42); await flush();
    assert.equal(old.root.querySelector('#figs').getAttribute('data-cols'), '4');
    // The stylesheet lays three out in three columns on a wide screen; a phone keeps its two.
    const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
    assert.match(css, /@media \(min-width: 721px\) \{ \.detail #figs\.measure\[data-cols="3"\] \{ grid-template-columns: repeat\(3, minmax\(0, 1fr\)\); \} \}/);
  });

  // Walk 2026-10-28: a first session, just started, waits for the worker. Its Time figure was a bare "—" beside
  // "Status: Waiting", and Tau's empty log ended "the phase it's in" with a straight apostrophe.
  test(`${name}: a session that hasn't started yet says so in its Time figure, not a bare dash`, async () => {
    const page = async (r) => {
      const g = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9') ? response({run: r, events: [], strategies: []}) : response({})});
      await g.viewRun(9); await flush(); g.clearTimers();
      return g;
    };
    let g = await page(session({status: 'queued', started_at: null}));
    assert.match(g.root.querySelector('#runfigs').textContent, /Time\s*Not started yet/);
    assert.doesNotMatch(g.root.querySelector('#runfigs').textContent, /Time\s*—/);
    assert.doesNotMatch(g.root.querySelector('#log').textContent, /[a-z]'[a-z]/);
    g = await page(session({status: 'cancelled', started_at: null, finished_at: '2026-10-27T22:04:00Z', stop_reason: 'user'}));
    assert.match(g.root.querySelector('#runfigs').textContent, /Time\s*Never started/);
    // The research loop's explainer ("so it can’t overfit"), open on Research and a session page, writes curly ones too.
    assert.doesNotMatch(pageFile('research'), /phase it's in|can't overfit/);
    assert.match(pageFile('research'), /so it can’t overfit/);
  });

  // Walk 2026-10-28: a new account's Strategies page read "Pass rate —" under three zeros.
  test(`${name}: Strategies with nothing tested yet says the pass rate shows later, not a bare dash`, async () => {
    const list = async (counts) => {
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/strategies?') ? response({strategies: [], matched: 0, counts}) : response({})});
      f.location.pathname = '/strategies';
      await f.viewStrategies(); await settle();
      return f.root.querySelector('#sfigs').textContent;
    };
    const empty = await list({total: 0});
    assert.match(empty, /Pass rate\s*None yet\s*shows once a strategy here is tested/);
    assert.doesNotMatch(empty, /Pass rate\s*—/);
    assert.match(await list({total: 4, passed: 1, failed: 2, rejected: 1}), /Pass rate\s*25\.0%\s*of the 4 strategies here/);
  });
}
