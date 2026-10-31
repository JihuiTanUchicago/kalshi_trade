// Shared cases, run against each bundle's offline harness (Tau and Meridian): what the autopilot will cost, said
// before and right after it is switched on. New-customer walk 2026-10-31: the dashboard's autopilot card said only
// "It uses your credits while it's on ($X left)", and after a first session "too soon to say how long they last",
// while the Research page already said what a session usually costs. The card, the panel and the autopilot's week
// now say the Research page's own figure (core's sessionEstimate on /api/research/estimate) for the autopilot's
// model, in credits, as typical and never a quote, and how many sessions the balance covers at that rate. With no
// figure for that model nothing new is said. Display only: what is charged doesn't change.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const text = (html) => html.replace(/<button[\s\S]*?<\/button>/g, '').replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
// Placeholder model names: the picker's labels are the customer's words for them.
const MODELS = {models: [{key: 'mdl_a', label: 'Deep Model'}, {key: 'mdl_b', label: 'Quick Model'}], default: 'mdl_a'};
const TYPICAL = {yours: null, yours_by_model: {}, sessions: 0, typical: {mdl_a: 0.85}, per_hour: {yours: null, yours_by_model: {}, typical: {}}};
const OWN = {...TYPICAL, yours: 1.23, yours_by_model: {mdl_a: 1.23}, sessions: 4};
const OFF = {autopilot: false, mode: 'off', model: 'mdl_a', focus: []};
const TODAY = 'It uses your credits while it’s on ($5.00 left) and pauses when they run out. Turn it off any time.';
const ME = {billing_enabled: true, needs_card: false, credit_balance: 5, min_run_balance: 1, auto_reload: null, reload_failed: null, models: MODELS};
const FIRST_WEEK = {research_credits: 0.42, tested: 1, passed: 0, not_cleared: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0,
  checkin_credits: 0.02, credits_left: 19.56, runway_days: null, reload_days: null, pace_days: 0.01};
const EMPTY_WEEK = {research_credits: 0, tested: 0, passed: 0, not_cleared: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0,
  checkin_credits: 0, credits_left: 5, runway_days: null, reload_days: null, pace_days: 0.001};
const figure = (s) => (/usually (?:costs|takes) about (\$[\d,.]+)/.exec(s) || [])[1];

export function autopilotCostCases({name, frontend, dashboard, apStatus}) {
  // The dashboard with the autopilot's status `status` and the estimate `est` (a function: a failing read throws).
  const dash = async (status, est, me = {}) => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(dashboard());
      if (path === '/api/autopilot/status') return response(status);
      if (path === '/api/research/estimate') return est();
      if (path === '/api/models') return response(MODELS);
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, ...ME, ...me};
    f.S.me.user.autopilot = !!status.autopilot; f.S.ap = status;
    await f.viewDashboard(); await settle();
    f.S.ap = status; f.paintDashAp(); await settle();
    return f;
  };
  const card = (f) => text(f.root.querySelector('#dash-ap').innerHTML);
  const estReads = (f) => f.requests.filter(({path}) => path === '/api/research/estimate').length;
  const research = async (est, me = {}) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/models') return response(MODELS);
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/research/estimate') return response(est);
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null, v: 'v1'});
      if (path.startsWith('/api/research/scoreboard')) return response({});
      if (path === '/api/autopilot/status') return response(OFF);
      if (path.startsWith('/api/dashboard')) return response(dashboard());
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, ...ME, ...me};
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    return f;
  };

  test(`${name}: autopilot off, the card says what a session on its model usually costs and how many the credits cover`, async () => {
    const f = await dash(OFF, () => response(TYPICAL));
    const c = card(f);
    assert.ok(c.includes(TODAY), c);  // today's line, unchanged
    assert.ok(c.includes('A research session usually costs about $0.85 in credits (recent sessions on Deep Model; typical, not a quote). '
      + 'At that rate your $5.00 lasts about 5 sessions. The autopilot\u2019s check-ins between sessions use some credits too.'), c);
    assert.doesNotMatch(c, /list price|margin|×|\bx2\b|mdl_/i);
    // Credits only: never beside the paper P&L.
    assert.doesNotMatch(f.root.querySelector('#dash-ap .apcard-main').innerHTML.split('A research session')[1], /P&amp;L|realized/);
    f.clearTimers();
  });

  test(`${name}: the card's figure is the Research page's estimate for the same model, your own or everyone's`, async () => {
    for (const est of [TYPICAL, OWN]) {
      const r = await research(est);
      const page = figure(r.root.querySelector('#rcost').textContent);
      r.clearTimers();
      const f = await dash(OFF, () => response(est));
      const shown = figure(card(f));
      assert.ok(page, 'the Research page shows a figure');
      assert.equal(shown, page);
      if (est === OWN) assert.ok(card(f).includes('(your recent sessions on Deep Model; typical, not a quote)'), card(f));
      f.clearTimers();
    }
    // A Research page read keeps its estimate for the card: one source, no second read.
    const r = await research(OWN);
    assert.equal(figure(r.root.querySelector('#rcost').textContent), '$1.23');
    r.S.ap = OFF; r.S.me.user.autopilot = false;
    const reads = estReads(r);
    r.location.pathname = '/'; await r.viewDashboard(); await settle(); r.S.ap = OFF; r.paintDashAp(); await settle();
    assert.equal(figure(card(r)), '$1.23');
    assert.equal(estReads(r), reads);
    r.clearTimers();
  });

  test(`${name}: a model with no estimate, payments off or a failed read keep today's card word for word`, async () => {
    for (const [status, est, me] of [[{...OFF, model: 'mdl_b'}, () => response(TYPICAL), {}], [OFF, () => response({...TYPICAL, typical: {}}), {}],
      [OFF, () => response({error: 'Something went wrong on our side.'}, 500), {}], [OFF, () => response(TYPICAL), {billing_enabled: false}]]) {
      const f = await dash(status, est, me);
      assert.doesNotMatch(card(f), /usually costs|typical, not a quote|sessions\./);
      if (me.billing_enabled !== false) assert.equal(text(f.root.querySelector('#dash-ap .apcard-cost').innerHTML), TODAY);
      f.clearTimers();
    }
  });

  test(`${name}: the estimate is read once while a line can use it, kept 10 minutes, never on the status poll`, async () => {
    const f = await dash(OFF, () => response(TYPICAL));
    assert.equal(estReads(f), 1);
    for (let i = 0; i < 3; i++) { f.paintDashAp(); await settle(); }
    assert.equal(estReads(f), 1);
    f.shiftClock(10 * 60 * 1000 + 1);
    f.paintDashAp(); await settle();
    assert.equal(estReads(f), 2);
    f.clearTimers();
    // With payments off it is never read.
    const g = await dash(OFF, () => response(TYPICAL), {billing_enabled: false});
    assert.equal(estReads(g), 0);
    g.clearTimers();
  });

  test(`${name}: under the floor, with auto-reload, or short of one session, the line says so in credits`, async () => {
    let f = await dash(OFF, () => response(TYPICAL), {credit_balance: 0.6});
    assert.ok(card(f).includes('A research session usually costs about $0.85 in credits (recent sessions on Deep Model; typical, not a quote).'), card(f));
    assert.doesNotMatch(card(f), /At that rate|more than the/);  // the line above it already says it waits for credits
    f.clearTimers();
    f = await dash(OFF, () => response(TYPICAL), {credit_balance: 20, auto_reload: {amount: 20, charge: 21.1, threshold: 5}});
    assert.ok(card(f).includes('At that rate your $20.00 covers about 23 sessions, and each $20.00 auto-reload about 23 more.'), card(f));
    f.clearTimers();
    f = await dash(OFF, () => response({...TYPICAL, typical: {mdl_a: 4.05}}), {credit_balance: 1.4});
    assert.ok(card(f).includes('That’s more than the $1.40 you have, so a session may stop short when your credits run out.'), card(f));
    f.clearTimers();
    f = await dash(OFF, () => response({...TYPICAL, typical: {mdl_a: 4.05}}), {credit_balance: 5});
    assert.ok(card(f).includes('At that rate your $5.00 lasts about 1 session.'), card(f));
    f.clearTimers();
  });

  test(`${name}: right after switching on and after a first session, the week says the typical cost in place of a pace`, async () => {
    const on = {...apStatus, model: 'mdl_a', billing_blocked: false};
    // Just switched on: nothing in the week yet.
    let f = await dash({...on, week: EMPTY_WEEK}, () => response(TYPICAL));
    const empty = f.root.querySelector('#dash-ap .ap-week');
    assert.match(text(empty.innerHTML), /nothing yet\. Its research, paper strategies and credits spent show here once it starts\.\s?A research session usually costs about \$0\.85 in credits \(recent sessions on Deep Model; typical, not a quote\)\. At that rate your \$5\.00 lasts about 5 sessions\. The autopilot\u2019s check-ins between sessions use some credits too\.$/);
    f.clearTimers();
    // After one session, on its first day.
    f = await dash({...on, week: FIRST_WEEK}, () => response(TYPICAL), {credit_balance: 19.56});
    assert.match(f.root.querySelector('#dash-ap .ap-week-left').innerHTML, /^Credits left: <b>\$19\.56<\/b>, too soon to say how long they last: its first day sets the pace\. A research session usually costs about \$0\.85 in credits \(recent sessions on Deep Model; typical, not a quote\)\. At that rate your \$19\.56 lasts about 23 sessions\. The autopilot\u2019s check-ins between sessions use some credits too\. It has no daily spending cap: it uses credits until your balance is under \$1\.00, then pauses\./);
    // Once it has a pace of its own, that pace is what it says.
    f.S.ap = {...on, week: {...FIRST_WEEK, runway_days: 9.8, pace_days: 2}}; f.paintDashAp();
    assert.doesNotMatch(f.root.querySelector('#dash-ap .ap-week-left').innerHTML, /usually costs/);
    f.clearTimers();
    // No estimate for its model: the first day's words as before.
    f = await dash({...on, model: 'mdl_b', week: FIRST_WEEK}, () => response(TYPICAL), {credit_balance: 19.56});
    assert.match(f.root.querySelector('#dash-ap .ap-week-left').innerHTML, /^Credits left: <b>\$19\.56<\/b>, too soon to say how long they last: its first day sets the pace\. It has no daily spending cap/);
    f.clearTimers();
  });

  test(`${name}: the open panel says it beside its switch while off, and in its week once on`, async () => {
    const f = frontend({fetchImpl: (path) => path === '/api/research/estimate' ? response(TYPICAL) : response({messages: [], models: []})});
    f.S.me = {...f.S.me, ...ME};
    f.S.me.user.autopilot = false;
    const box = new (f.root.constructor)('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl><div id="apf-week"></div>';
    await f.apUpdate(box, OFF); await settle();
    await f.apUpdate(box, OFF); await settle();
    assert.equal(text(box.querySelector('#apf-week').innerHTML),
      'A research session usually costs about $0.85 in credits (recent sessions on Deep Model; typical, not a quote). At that rate your $5.00 lasts about 5 sessions. The autopilot\u2019s check-ins between sessions use some credits too.');
    // A model with no figure: nothing, as before.
    await f.apUpdate(box, {...OFF, model: 'mdl_b'}); await settle();
    assert.equal(box.querySelector('#apf-week').innerHTML, '');
    f.S.me.user.autopilot = true;
    await f.apUpdate(box, {...apStatus, model: 'mdl_a', week: FIRST_WEEK}); await settle();
    assert.match(box.querySelector('#apf-week').innerHTML, /its first day sets the pace\. A research session usually costs about \$0\.85 in credits/);
    f.clearTimers();
  });
}

// Billing's "Credits last" on a first day (no pace yet) said only "Too soon to tell" while the dashboard's autopilot
// card already said what a session usually costs and how many the balance covers. The tile now says the card's own
// line (apSessionLine: the same estimate, model and rounding) once the estimate is there, and today's words without one.
export function billingCostCases({name, frontend, dashboard, billingPage, cardedBilling}) {
  const FIRST = {balance: 19.56, spent_7d: 0.44, runway_days: null, reload_days: null, pace_days: 0.01, auto_reload: false};
  const LINE = /A research session usually costs.*?(?:too\.|run out\.|typical, not a quote\)\.)$/;
  const TODAY_TILE = 'Credits last Too soon to tell your first day of research sets the pace';
  const page = async (o, est, me = {}, ap = OFF) => {
    const f = billingPage(cardedBilling({...FIRST, ...o}), [], {'/api/research/estimate': est});
    f.S.me = {...f.S.me, ...ME, ...me}; f.S.me.user.autopilot = false; f.S.ap = ap;
    await f.viewBilling(); await settle();
    return f;
  };
  const tile = (f) => {
    const m = [...f.root.querySelectorAll('#bfigs .m')].find((x) => /Credits last/.test(x.textContent));
    return m ? m.innerHTML.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim() : '';
  };
  // The dashboard card's line, for the balance and auto-reload Billing synced onto the page state.
  const cardLine = async (est, me) => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(dashboard());
      if (path === '/api/autopilot/status') return response(OFF);
      if (path === '/api/research/estimate') return est();
      if (path === '/api/models') return response(MODELS);
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, ...ME, ...me}; f.S.me.user.autopilot = false; f.S.ap = OFF;
    await f.viewDashboard(); await settle(); f.S.ap = OFF; f.paintDashAp(); await settle();
    const s = [...f.root.querySelectorAll('#dash-ap .apcard-cost')].map((p) => text(p.innerHTML)).find((t) => t.startsWith('A research session'));
    f.clearTimers();
    return s;
  };

  test(`${name}: Billing's first-day "Credits last" says the dashboard card's own line, figure for figure`, async () => {
    for (const [o, est] of [[{}, TYPICAL], [{}, OWN], [{auto_reload: true}, TYPICAL], [{balance: 1.4}, {...TYPICAL, typical: {mdl_a: 4.05}}],
      [{balance: 5}, {...TYPICAL, typical: {mdl_a: 4.05}}]]) {
      const f = await page(o, () => response(est));
      const t = tile(f), shown = (LINE.exec(t) || [])[0];
      assert.ok(t.startsWith('Credits last Too soon to tell Your first day of research sets the pace. A research session usually costs about'), t);
      // Billing put its balance and auto-reload on the page state; the card reads the same.
      const same = await cardLine(() => response(est), {credit_balance: f.S.me.credit_balance, auto_reload: f.S.me.auto_reload});
      assert.ok(same, 'the dashboard card says a cost line');
      assert.equal(shown, same);
      assert.doesNotMatch(t, /list price|margin|mdl_|P&L/i);
      f.clearTimers();
    }
    const f = await page({}, () => response(TYPICAL));
    assert.equal(tile(f), 'Credits last Too soon to tell Your first day of research sets the pace. A research session usually costs about $0.85 in credits '
      + '(recent sessions on Deep Model; typical, not a quote). At that rate your $19.56 lasts about 23 sessions. The autopilot\u2019s check-ins between sessions use some credits too.');
    // A sentence, not a figure's note: alone on its row at phone width, the tile takes the row (app.css m-wide).
    assert.match(f.root.querySelector('#bfigs').innerHTML, /<div class="m m-wide"><dt class="lab">Credits last<\/dt>/);
    f.clearTimers();
    const r = await page({auto_reload: true}, () => response(TYPICAL));
    assert.ok(tile(r).includes('At that rate your $19.56 covers about 23 sessions, and each $25.00 auto-reload about 29 more.'), tile(r));
    r.clearTimers();
  });

  test(`${name}: with no estimate for the autopilot's model, payments off or a failed read, Billing keeps "Too soon to tell" word for word`, async () => {
    for (const [est, me, ap] of [[() => response(TYPICAL), {}, {...OFF, model: 'mdl_b'}], [() => response({...TYPICAL, typical: {}}), {}, OFF],
      [() => response({error: 'Something went wrong on our side.'}, 500), {}, OFF], [() => response(TYPICAL), {billing_enabled: false}, OFF]]) {
      const f = await page({}, est, me, ap);
      assert.equal(tile(f), TODAY_TILE);
      f.clearTimers();
    }
    // A balance with a pace of its own says that pace, and reads no estimate.
    const f = await page({runway_days: 9.8, pace_days: 2}, () => response(TYPICAL));
    assert.doesNotMatch(text(f.root.querySelector('#bfigs').innerHTML), /usually costs|Too soon/);
    assert.equal(f.requests.filter(({path}) => path === '/api/research/estimate').length, 0);
    f.clearTimers();
  });

  test(`${name}: Billing's tile fills in when the estimate lands, and follows the autopilot's model once its status is read`, async () => {
    let land;
    const f = await page({}, () => new Promise((resolve) => { land = () => resolve(response(TYPICAL)); }), {}, null);
    assert.equal(tile(f), TODAY_TILE);
    land(); await settle();
    assert.match(tile(f), /At that rate your \$19\.56 lasts about 23 sessions\./);
    // The status arrives: its model has no figure, so the tile goes back to today's words, as the card does.
    f.S.ap = {...OFF, model: 'mdl_b'}; f.paintDashAp(); await settle();
    assert.equal(tile(f), TODAY_TILE);
    // One estimate read for all of it: kept 10 minutes, as the card keeps it.
    assert.equal(f.requests.filter(({path}) => path === '/api/research/estimate').length, 1);
    f.clearTimers();
  });
}
