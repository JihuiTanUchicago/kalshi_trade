// Shared cases, run against each bundle's offline harness (Tau and Meridian): a new user's first hour.
// A first session the autopilot already put on paper does not ask for a second deploy; a credit balance
// on an account minutes old does not claim "over 3 months at this week's pace", and one a few days old
// states its pace per day so far; the autopilot panel names its check-in as the dashboard card does.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const AT = '2026-10-25T10:00:00Z';

export function firstHourCases({name, frontend, billingPage, cardedBilling, dashboard, apStatus, fundsData}) {
  const run = async (strategies) => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9')
      ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', brief: 1, status: 'succeeded', hypotheses_tried: 2,
        strategies_passed: 1, created_at: AT, started_at: AT}, events: [], strategies})
      : response({})});
    await f.viewRun(9); f.clearTimers();
    return f.root.querySelector('#runnext').innerHTML;
  };
  const passed = (o) => ({id: 42, title: 'Momentum', status: 'passed', market: 'btc15m', direction: 'momentum', deployed: false, ...o});

  test(`${name}: a finished session whose passed strategy is already deployed says so instead of asking to deploy it`, async () => {
    let next = await run([passed({deployed: true}), {id: 43, title: 'Fade', status: 'rejected', market: 'btc15m', direction: 'momentum'}]);
    assert.match(next, /Passed: <a href="\/strategies\/42">Momentum<\/a>\. It is already deployed\. <a href="\/deploy">See it on Deploy<\/a>\./);
    assert.doesNotMatch(next, /to deploy it on paper/);
    next = await run([passed()]);
    assert.match(next, /Passed: <a href="\/strategies\/42">Momentum<\/a>\. Open it to deploy it on paper\./);
    next = await run([passed({deployed: true}), passed({id: 44, title: 'Other'})]);
    assert.match(next, /2 passed: .*\. 1 is already deployed; open another to deploy it on paper\./);
  });

  test(`${name}: a passed strategy the autopilot is about to put on paper does not ask for a deploy by hand`, async () => {
    let next = await run([passed({autopilot_next: true})]);
    assert.match(next, /Passed: <a href="\/strategies\/42">Momentum<\/a>\. The autopilot puts it on paper itself at its next check-in, so there is nothing for you to deploy\. <a href="\/deploy">Deploy<\/a> shows it once it is there\./);
    assert.doesNotMatch(next, /Open it to deploy/);
    next = await run([passed({deployed: true}), passed({id: 44, title: 'Other', autopilot_next: true})]);
    assert.match(next, /2 passed: .*\. 1 is already deployed; the autopilot puts the other on paper itself at its next check-in/);
    // One it will not take (outside the focus, say) still asks.
    next = await run([passed({autopilot_next: true}), passed({id: 44, title: 'Other'})]);
    assert.match(next, /2 passed: .*\. Open one to deploy it on paper\./);
  });

  test(`${name}: Billing does not project a first day's spend over a week, and states a young account's pace per day`, async () => {
    // Twelve minutes old, $0.44 spent: the server sends no runway and pace_days under 1.
    let f = billingPage(cardedBilling({balance: 19.56, spent_7d: 0.44, runway_days: null, pace_days: 0.01}));
    await f.viewBilling(); await flush();
    let figs = f.root.querySelector('#bfigs').textContent;
    assert.match(figs, /Credits last\s*Too soon to tell\s*your first day of research sets the pace/);
    assert.doesNotMatch(figs, /Over 3 months|a week/);
    const amt = f.root.querySelector('#topup-amt'); amt.value = '20'; amt.oninput();
    assert.doesNotMatch(f.root.querySelector('#topup-note').textContent, /At your pace|3 months/);
    // Two days old, $8 spent: $4 a day so far, and the buy line reads the same pace.
    f = billingPage(cardedBilling({balance: 12, spent_7d: 8, runway_days: 3, pace_days: 2}));
    await f.viewBilling(); await flush();
    figs = f.root.querySelector('#bfigs').textContent;
    assert.match(figs, /Research pauses in\s*About 3 days\s*at \$4\.00 a day so far/);
    const amt2 = f.root.querySelector('#topup-amt'); amt2.value = '20'; amt2.oninput();
    assert.match(f.root.querySelector('#topup-note').textContent, /At your pace \(\$4\.00 a day so far\) that's about 5 days of research\./);
    // A week-old account (or an older server with no pace_days) keeps the week's words.
    for (const o of [{pace_days: 7}, {}]) {
      f = billingPage(cardedBilling(o));
      await f.viewBilling(); await flush();
      assert.match(f.root.querySelector('#bfigs').textContent, /Research pauses in\s*About 5 days\s*at \$9\.80 a week/);
    }
  });

  test(`${name}: the autopilot card says it is too soon to tell how long credits last on a first day, and "its pace so far" after`, async () => {
    const week = {research_credits: 0.42, tested: 1, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0,
      checkin_credits: 0.02, credits_left: 19.56, runway_days: null, pace_days: 0.01};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/dashboard') return response(dashboard());
      if (path === '/api/autopilot/status') return response({...apStatus, week});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 19.56, min_run_balance: 1, auto_reload: null};
    f.S.me.user.autopilot = true; f.S.ap = {...apStatus, week};
    await f.viewDashboard(); await flush();
    f.S.ap = {...apStatus, week}; f.paintDashAp();
    const line = () => f.root.querySelector('#dash-ap .ap-week-left').innerHTML;
    assert.match(line(), /^Credits left: <b>\$19\.56<\/b>, too soon to say how long they last: its first day sets the pace\. It has no daily spending cap/);
    assert.doesNotMatch(line(), /3 months|this week’s pace/);
    f.S.ap = {...apStatus, week: {...week, runway_days: 9.8, pace_days: 2}}; f.paintDashAp();
    assert.match(line(), /^Credits left: <b>\$19\.56<\/b>, about 10 days at its pace so far\./);
    f.S.ap = {...apStatus, week: {...week, runway_days: 9.8, pace_days: 7}}; f.paintDashAp();
    assert.match(line(), /about 10 days at this week’s pace\./);
    f.clearTimers();
  });

  test(`${name}: the autopilot's week calls free credits free until a card was ever charged, as the strip above it does`, async () => {
    const week = {research_credits: 0.84, tested: 2, passed: 1, paper_started: 0, paper_pnl: 0, paper_trades: 0,
      checkin_credits: 0, credits_left: 19.16, runway_days: null, pace_days: 0.01};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/dashboard') return response(dashboard());
      if (path === '/api/autopilot/status') return response({...apStatus, week});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 19.16, min_run_balance: 1, auto_reload: null};
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    const spent = () => f.root.querySelector('#dash-ap .ap-week dd').textContent;
    f.S.ap = {...apStatus, week: {...week, card_charged: false}}; f.paintDashAp();
    assert.match(spent(), /^\$0\.84 free credits so far: your card hasn’t been charged$/);
    assert.doesNotMatch(spent(), /real money/);
    // Once a card was charged, or from a server that doesn't say: real money, as before.
    for (const charged of [true, undefined]) {
      f.S.ap = {...apStatus, week: {...week, card_charged: charged}}; f.paintDashAp();
      assert.match(spent(), /^\$0\.84 real money$/);
    }
    f.clearTimers();
  });

  test(`${name}: switched on a moment ago, the strip's Autopilot row says so instead of "It made no changes"`, async () => {
    const flip = {text: 'Autopilot is ON: the agent may research, deploy and tune paper strategies.', at: new Date().toISOString()};
    let status = {...apStatus, autopilot: false, mode: 'off', last_action: null};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response({...dashboard(), since: {at: '2026-10-25T08:00:00+00:00', first: true,
        books: {}, passed: {n: 0, items: []}, autopilot: {}, runs: {}, own_sessions: false}});
      if (path === '/api/settings') return response({ok: true});
      if (path === '/api/autopilot/status') return response(status);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = false; f.S.ap = null;
    await f.viewDashboard(); await flush();
    const row = () => f.root.querySelector('#dash-since [data-since-ap]').textContent;
    assert.equal(row(), 'Off.');
    status = {...apStatus, autopilot: true, last_action: flip};
    await f.root.querySelector('#dash-ap [data-apcard="on"]').onclick(); await flush(); await flush();
    assert.equal(row(), 'Switched on just now. Its moves show up here as it makes them.');
    // Once it has made a move of its own, the switch is no longer the news.
    status = {...status, last_action: {text: 'Started a fresh research session on Bitcoin.', at: flip.at}};
    f.S.ap = status; f.paintDashAp();
    assert.equal(row(), 'On. It made no changes.');
    f.clearTimers();
  });

  test(`${name}: on a new account with the autopilot off, its card comes before the empty strip, and stays there once on`, async () => {
    const order = async ({own, on}) => {
      let status = on ? {...apStatus, autopilot: true} : {...apStatus, autopilot: false, mode: 'off'};
      const f = frontend({fetchImpl: (path) => {
        if (path.startsWith('/api/dashboard')) return response({...dashboard(), since: {at: '2026-10-25T08:00:00+00:00', first: true,
          books: {}, passed: {n: 0, items: []}, autopilot: {}, runs: {}, own_sessions: own}});
        if (path === '/api/settings') { status = {...apStatus, autopilot: true}; return response({ok: true}); }
        if (path === '/api/autopilot/status') return response(status);
        if (path === '/api/models') return response({models: [], default: ''});
        if (path.startsWith('/api/chat')) return response({messages: []});
        return response({});
      }});
      f.S.me.user.autopilot = on; f.S.ap = null;
      await f.viewDashboard(); await flush();
      // The two sections' places in the markup that holds them both.
      const html = () => f.root.querySelector('#dash-ap').parentElement.innerHTML, at = () => [html().indexOf('id="dash-ap"'), html().indexOf('id="dash-since"')];
      return {f, at};
    };
    // Brand new and off: Turn on autopilot is the first thing under the status line.
    const fresh = await order({own: false, on: false});
    let [ap, since] = fresh.at();
    assert.ok(ap > 0 && since > ap, 'the card leads');
    // Switched on, then the board's poll repaints: the card keeps its place for the rest of the visit.
    await fresh.f.root.querySelector('#dash-ap [data-apcard="on"]').onclick(); await flush(); await flush();
    for (const tick of [...fresh.f.intervals.values()]) { await tick(); await flush(); }
    [ap, since] = fresh.at();
    assert.ok(ap > 0 && since > ap, 'still leads after the switch and a poll');
    fresh.f.clearTimers();
    // Anyone with a session of their own, or with the autopilot on, reads the strip first, as before.
    for (const o of [{own: true, on: false}, {own: false, on: true}]) {
      const {f, at} = await order(o);
      [ap, since] = at();
      assert.ok(since > 0 && ap > since, JSON.stringify(o));
      f.clearTimers();
    }
  });

  test(`${name}: Billing says under the balance that it is free credits until the card was ever charged`, async () => {
    const balanceFig = async (o) => {
      const f = billingPage(cardedBilling({balance: 19.16, spent_7d: 0.84, runway_days: null, pace_days: 0.01, ...o}));
      await f.viewBilling(); await flush();
      return f.root.querySelector('#bfigs .m').textContent;
    };
    assert.match(await balanceFig({card_charged: false}), /Credit balance\s*\$19\.16\s*free credits so far: your card hasn’t been charged/);
    // Charged once, from a server that doesn't say, or with nothing left: no such line.
    for (const o of [{card_charged: true}, {}, {card_charged: false, balance: 0}])
      assert.doesNotMatch(await balanceFig(o), /free credits so far/, JSON.stringify(o));
  });

  test(`${name}: the autopilot card's week is one line until something is in it`, async () => {
    const zero = {research_credits: 0, tested: 0, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0,
      checkin_credits: 0, credits_left: 20, runway_days: null, pace_days: 0.01, card_charged: false};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/dashboard') return response(dashboard());
      if (path === '/api/autopilot/status') return response({...apStatus, week: zero});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 20, min_run_balance: 1, auto_reload: null};
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    const week = () => f.root.querySelector('#dash-ap .ap-week');
    f.S.ap = {...apStatus, week: zero}; f.paintDashAp();
    assert.equal(week().textContent.trim(), 'Last 7 days: nothing yet. Its research, paper strategies and credits spent show here once it starts.');
    assert.equal(week().querySelector('dl'), null);
    assert.equal(week().querySelector('.ap-week-note'), null);
    // Paused for want of a card: its reason stays in view under the one line.
    f.S.ap = {...apStatus, week: zero, billing_blocked: true, billing_reason: 'card'}; f.paintDashAp();
    assert.match(week().textContent, /nothing yet[\s\S]*Research is paused until you add a payment method/);
    // A first session's cents, or a check-in, fill the block in as before.
    for (const o of [{research_credits: 0.02}, {tested: 1}, {checkin_credits: 0.01}]) {
      f.S.ap = {...apStatus, week: {...zero, ...o}}; f.paintDashAp();
      assert.ok(week().querySelector('dl'), JSON.stringify(o));
      assert.doesNotMatch(week().textContent, /nothing yet/, JSON.stringify(o));
    }
    f.clearTimers();
  });

  test(`${name}: Explore before the market feed arrives says so instead of counting 0 markets`, async () => {
    const explore = async (d) => {
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore?') ? response(d) : response({})});
      f.location.pathname = '/explore'; f.location.search = '';
      await f.viewExplore(); await flush(); await flush();
      const figs = f.root.querySelector('#xfigs').textContent;
      f.clearTimers();
      return figs;
    };
    const none = await explore({at: null, total: 0, shown: 0, matched: 0, page: 0, per: 40, markets: []});
    assert.match(none, /Market feed\s*Not in yet/);
    assert.doesNotMatch(none, /Markets tracked|In this list|Available markets|Time unavailable|\b0\b/);
    // Once it is in, the counts and its time are back.
    const at = new Date(Date.now() - 60000).toISOString();
    const some = await explore({at, total: 1200, shown: 1, matched: 1, page: 0, per: 40,
      markets: [{t: 'KXFED-26DEC-T4.00', ti: 'Fed rate above 4%', yb: 0.4, ya: 0.42, v24: 10, oi: 5}]});
    assert.match(some, /1,200/);
    assert.doesNotMatch(some, /Not in yet/);
  });

  test(`${name}: Funds for an account with no Kalshi key leads with Paper and folds the key forms under Connect Kalshi`, async () => {
    const page = async (o) => {
      const d = {...fundsData(), ...o};
      const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response(d) : response({})});
      await f.viewFunds(); await flush();
      const html = f.root.querySelector('#main').innerHTML;
      f.clearTimers();
      return {f, at: (s) => html.indexOf(s)};
    };
    // No key of either kind: Paper first, then one closed Connect Kalshi holding the live and demo forms.
    const fresh = await page({});
    const connect = fresh.f.root.querySelector('#connect-kalshi');
    assert.ok(connect, 'Connect Kalshi is there');
    assert.ok(!connect.open, 'and closed');
    assert.match(connect.querySelector('summary').textContent, /^Connect Kalshi/);
    assert.ok(fresh.at('Paper account (simulation)') >= 0 && fresh.at('Paper account (simulation)') < fresh.at('id="connect-kalshi"'), 'Paper leads');
    assert.ok(fresh.at('id="connect-kalshi"') < fresh.at('Kalshi account (live money)') && fresh.at('Kalshi account (live money)') < fresh.at('Kalshi demo (sandbox) account'), 'the key forms are in it');
    assert.ok(connect.querySelector('#kalshi') && connect.querySelector('#kalshi-dev'), 'both key forms sit in the disclosure');
    // A live key, or a demo key alone: today's order (live, demo, paper), no disclosure.
    for (const keys of [{kalshi: {connected: true, key_id: 'k1', balance: 12}}, {kalshi_dev: {connected: true, key_id: 'k2', balance: 5}}]) {
      const keyed = await page(keys);
      assert.equal(keyed.f.root.querySelector('#connect-kalshi'), null, JSON.stringify(keys));
      assert.ok(keyed.at('Kalshi account (live money)') < keyed.at('Kalshi demo (sandbox) account') && keyed.at('Kalshi demo (sandbox) account') < keyed.at('Paper account (simulation)'), JSON.stringify(keys));
    }
  });
}
