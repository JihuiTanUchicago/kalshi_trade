// Shared cases, run against each bundle's offline harness (Tau and Meridian): what credits cost, how long
// they last and what happens next, as Billing and the autopilot card say it.
// - A top-up's price is the card's charge to the cent (the server's half-up decimal, not a float sum), an
//   amount out of range says the range before the press, and the confirmation states what was charged.
// - "How long credits last" counts to where research pauses, and with auto-reload on it says when the card
//   is next charged and for how much, instead of a red "Credits last" that auto-reload prevents.
// - A credits pause while the auto-reload card is declined names the card as the step, everywhere.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const FAILED = 'It couldn’t add $25.00 in credits. Your card was declined for insufficient funds. Try another card.';

export function creditsCases({name, frontend, billingPage, cardedBilling, dashboard, apStatus}) {
  test(`${name}: the top-up price is what the card pays to the cent, and an amount out of range says the range first`, async () => {
    const f = billingPage(cardedBilling(), [], {'/api/billing/topup': () => response({ok: true, balance: 26.4213, charged: 20.05})});
    await f.viewBilling(); await flush();
    const amt = f.root.querySelector('#topup-amt'), note = () => f.root.querySelector('#topup-note').textContent;
    // $19 plus 5.5% is $20.045: the card pays $20.05, where 19 * 1.055 as a float read $20.04.
    amt.value = '19'; amt.oninput();
    assert.match(note(), /^You'll pay \$20\.05 \(\$19\.00 credits \+ 5\.5% fee\)\./);
    amt.value = '37'; amt.oninput();
    assert.match(note(), /^You'll pay \$39\.04 \(\$37\.00 credits/);  // 39.035 half up
    for (const v of ['3', '2000']) {
      amt.value = v; amt.oninput();
      assert.equal(note(), 'Add between $5.00 and $1,000.00 in credits.');
    }
    amt.value = '19'; amt.oninput();
    const btn = f.root.querySelector('#topup-btn');
    await btn.onclick({currentTarget: btn}); await flush();
    assert.match(f.root.querySelector('#topup-flash').innerHTML, /Added \$19\.00 in credits\. You paid \$20\.05 — \$19\.00 plus the 5\.5% fee\. New balance is \$26\.42\./);
  });

  test(`${name}: Billing says when auto-reload next charges the card, or when research pauses, not a stop auto-reload prevents`, async () => {
    let f = billingPage(cardedBilling({balance: 25.71, spent_7d: 100.17, runway_days: 1.7, reload_days: 1.4, pace_days: 7,
      autoreload_threshold: 5, autoreload_charge: 26.38, min_run_balance: 1}));
    await f.viewBilling(); await flush();
    let figs = f.root.querySelector('#bfigs').textContent;
    assert.match(figs, /Next auto-reload in\s*About 1 day\s*adds \$25\.00, card charged \$26\.38, at \$100\.17 a week/);
    assert.doesNotMatch(figs, /Credits last|Research pauses/);
    // Auto-reload off: counted to the pause, and it says where that is.
    f = billingPage(cardedBilling({balance: 2.4, spent_7d: 10.5, runway_days: 0.9, reload_days: null, pace_days: 7, auto_reload: false, min_run_balance: 1}));
    await f.viewBilling(); await flush();
    figs = f.root.querySelector('#bfigs').textContent;
    assert.match(figs, /Research pauses in\s*Under a day\s*at \$10\.50 a week, when credits fall under \$1\.00/);
    // Under the floor: research is paused, said once, with what a session needs.
    f = billingPage(cardedBilling({balance: 0.62, spent_7d: 17.5, runway_days: null, reload_days: null, min_run_balance: 1,
      reload_failed: {at: '2026-10-26T21:49:00Z', text: FAILED}}));
    await f.viewBilling(); await flush();
    assert.match(f.root.querySelector('#bfigs').textContent, /Research\s*Paused\s*a session needs \$1\.00 to start/);
    const main = f.root.querySelector('#main').textContent;
    assert.match(main, /Auto-reload couldn’t charge your card \(see below\)\. Update the card first, then add credits here: they go on the same card\./);
    assert.doesNotMatch(main, /hasn’t topped you up/);
  });

  const apPage = async (status, me) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/dashboard') return response(dashboard());
      if (path === '/api/autopilot/status') return response(status);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 25.71, min_run_balance: 1, ...me};
    f.S.me.user.autopilot = true; f.S.ap = status;
    await f.viewDashboard(); await flush();
    f.S.ap = status; f.paintDashAp();
    return f;
  };
  const week = {research_credits: 100.01, tested: 3, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0,
    checkin_credits: 0.09, credits_left: 25.71, runway_days: 1.7, reload_days: 1.4, pace_days: 7};

  test(`${name}: the autopilot card says when auto-reload next charges the card and what the card pays`, async () => {
    const f = await apPage({...apStatus, week}, {auto_reload: {amount: 25, charge: 26.38, threshold: 5}});
    const line = f.root.querySelector('#dash-ap .ap-week-left').innerHTML;
    assert.match(line, /^Credits left: <b>\$25\.71<\/b>; at this week’s pace auto-reload adds \$25\.00 in about 1 day \(card charged \$26\.38\)\./);
    assert.doesNotMatch(line, /about 2 days at/);
    // With auto-reload on research never pauses at the floor: the card is charged each time instead.
    assert.match(line, /It has no daily spending cap: each time your balance falls to \$5\.00, auto-reload charges your card and research carries on\. With auto-reload off, it pauses when your balance is under \$1\.00\. <a href="\/billing">Billing<\/a> lists every charge\./);
    assert.doesNotMatch(line, /then pauses/);
    f.clearTimers();
  });

  test(`${name}: on a first day with auto-reload on, the card says the card is charged again and again, not that research pauses`, async () => {
    const first = {...week, research_credits: 0.42, checkin_credits: 0.02, credits_left: 19.56, runway_days: null, reload_days: null, pace_days: 0.01};
    const f = await apPage({...apStatus, week: first}, {credit_balance: 19.56, auto_reload: {amount: 20, charge: 21.1, threshold: 5}});
    const line = f.root.querySelector('#dash-ap .ap-week-left').innerHTML;
    assert.match(line, /^Credits left: <b>\$19\.56<\/b>, too soon to say how long they last: its first day sets the pace\. It has no daily spending cap: each time your balance falls to \$5\.00, auto-reload charges your card \$21\.10 for \$20\.00 more and research carries on\. With auto-reload off, it pauses when your balance is under \$1\.00\./);
    assert.doesNotMatch(line, /then pauses|auto-reload adds/);
    f.clearTimers();
    // Auto-reload off: the floor is the stop.
    const g = await apPage({...apStatus, week: first}, {credit_balance: 19.56, auto_reload: null});
    assert.match(g.root.querySelector('#dash-ap .ap-week-left').innerHTML, /It has no daily spending cap: it uses credits until your balance is under \$1\.00, then pauses\. <a href="\/billing">/);
    g.clearTimers();
  });

  test(`${name}: a credits pause with a declined auto-reload card names the card and then credits as the step`, async () => {
    const status = {...apStatus, billing_blocked: true, billing_reason: 'credits', reload_failed: FAILED,
      week: {...week, credits_left: 0.62, runway_days: null, reload_days: null}};
    const f = await apPage(status, {credit_balance: 0.62, auto_reload: {amount: 25, charge: 26.38, threshold: 5}});
    const card = f.root.querySelector('#dash-ap').innerHTML;
    assert.match(card, /Paused: auto-reload couldn’t charge your card\. <a href="\/billing">Update your card and add credits on Billing<\/a>, and research picks up on its own\./);
    assert.match(f.root.querySelector('#dash-ap .ap-week-left').innerHTML,
      /^Credits left: <b>\$0\.62<\/b>\. Research is paused: auto-reload failed\. It couldn’t add \$25\.00 in credits\. Your card was declined for insufficient funds\. Try another card\. <a href="\/billing">Update your card and add credits on Billing<\/a>\.$/);
    assert.doesNotMatch(card, /<a href="\/billing">Add credits<\/a> and it picks up/);
    f.clearTimers();
    // No failure on record: the plain credits pause, as before.
    const g = await apPage({...status, reload_failed: null}, {credit_balance: 0.62, auto_reload: null});
    assert.match(g.root.querySelector('#dash-ap').innerHTML, /Paused: starting research needs \$1\.00 in credits\. <a href="\/billing">Add credits<\/a> and it picks up on its own\./);
    g.clearTimers();
  });

  test(`${name}: Billing's statement adds up: the lines under a day to its "used", and the days to the usage above`, async () => {
    // Walk 2026-10-27, a few days of autopilot research: each figure rounded half up on its own, so "Sun $7.98 used"
    // sat over −$7.95 and −$0.02, and the days added up a cent short of "Agent usage −$12.99".
    const use = (amount, day, item) => ({kind: 'usage', amount, item, model: 'Claude Opus 4.6', calls: 40, day,
      created_at: `${day}T15:00:00Z`, first_at: `${day}T11:00:00Z`});
    const f = billingPage(cardedBilling({
      math: {days: 30, start: 0, bought: 50, purchases: 1, other: 0, usage: 12.99, end: 37.01},
      ledger: [use(-7.9545, '2026-10-24', 'Autopilot research'), use(-0.0245, '2026-10-24', 'Autopilot check-in'),
        use(-0.0031, '2026-10-24', 'Research session'), use(-2.0049, '2026-10-23', 'Autopilot research'),
        use(-3.0049, '2026-10-22', 'Autopilot research'),
        {kind: 'topup', amount: 50, day: '2026-10-22', created_at: '2026-10-22T09:00:00Z', first_at: '2026-10-22T09:00:00Z', card_charge: 52.75}],
      ledger_cut: false}));
    await f.viewBilling(); await flush();
    const cents = (t) => Math.round(+t.replace(/[^\d.]/g, '') * 100);
    const days = [];
    for (const tr of f.root.querySelectorAll('#bledger tbody tr')) {
      const sum = tr.querySelector('.day-sum');
      if (sum) { days.push({used: cents((sum.textContent.match(/\$([\d.,]+) used/) || [, '0'])[1]), lines: []}); continue; }
      const amt = tr.querySelector('td.num').textContent;
      if (amt.startsWith('−')) days[days.length - 1].lines.push(amt);
    }
    assert.equal(days.length, 3);
    for (const d of days) {
      // The whole-cent lines plus any line under a cent (shown to three places) round to the day's "used".
      const shown = d.lines.reduce((a, t) => a + +t.replace(/[^\d.]/g, ''), 0);
      assert.equal(Math.round(shown * 100), d.used, `${d.lines.join(' + ')} = ${d.used / 100}`);
    }
    assert.deepEqual(days.map((d) => d.used), [798, 201, 300]);
    assert.equal(days.reduce((a, d) => a + d.used, 0), 1299);  // the days are the statement's usage
    assert.match(f.root.querySelector('.bill-math').textContent, /Agent usage\s*−\$12\.99/);
    assert.deepEqual(days[0].lines, ['−$7.96', '−$0.02', '−$0.003']);  // each within a cent of its exact amount
    assert.match(f.root.querySelector('.ledger-key').textContent, /rounded to the cent so they add up to their day; the receipt has every call/);
    // With older days cut off, the days can't be held to the month's usage, but each still adds up.
    const cut = billingPage(cardedBilling({math: {days: 30, start: 0, bought: 0, purchases: 0, other: 0, usage: 99.99, end: 1},
      ledger: [use(-7.9545, '2026-10-24', 'Autopilot research'), use(-0.0245, '2026-10-24', 'Autopilot check-in')], ledger_cut: true}));
    await cut.viewBilling(); await flush();
    assert.match(cut.root.querySelector('#bledger').textContent, /\$7\.98 used[\s\S]*−\$7\.96[\s\S]*−\$0\.02/);
  });
}

// A declined auto-reload card where credits run short outside the autopilot card: the dashboard's Needs
// you and the research form name the card as the step, and the research form's forever line says what
// auto-reload charges the card instead of promising a top-up the card refuses.
export function declinedCardCases({name, frontend, dashboard}) {
  const declined = {credit_balance: 0.62, auto_reload: {amount: 25, charge: 26.38, threshold: 5}, reload_failed: FAILED};

  test(`${name}: under the research floor with a declined reload card, Needs you says to update the card`, async () => {
    const since = {at: '2026-10-19T08:00:00+00:00', first: false, books: {paper: {pnl: 0, trades: 0}},
      passed: {n: 0, items: []}, autopilot: {}, runs: {succeeded: 1}, spent: {since: 2.5, week: 17.5}, milestones: {}};
    const strip = async (me) => {
      const f = frontend({fetchImpl: (path) => {
        if (path.startsWith('/api/dashboard')) return response({...dashboard(), since});
        if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
        throw new Error('Unexpected offline request: ' + path);
      }});
      f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, min_run_balance: 1, ...me};
      await f.viewDashboard(); await flush();
      return f.root.querySelector('#dash-since').innerHTML;
    };
    assert.match(await strip(declined), /Credits are at \$0\.62: new research needs \$1\.00 to start\. Auto-reload couldn’t charge your card\. <a href="\/billing">Update your card and add credits<\/a>/);
    assert.match(await strip({...declined, reload_failed: null}), /Credits are at \$0\.62: new research needs \$1\.00 to start\. <a href="\/billing">Add credits<\/a>/);
  });

  const research = (me) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}], default: 'opus'});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/research/estimate') return response({yours: null, sessions: 0, typical: {}, per_hour: {yours: null, typical: {opus: 3}}});
      if (path === '/api/runs') return response({runs: [], counts: {research_running: 0, research_queued: 0, research_paused: 0}, policy: null});
      if (path.startsWith('/api/research/scoreboard')) return response({total: {runs: 0}});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, min_run_balance: 1, ...me};
    return f;
  };

  test(`${name}: the research form says what auto-reload charges the card, and not to count on a declined one`, async () => {
    let f = research({credit_balance: 100, auto_reload: {amount: 20, charge: 21.1, threshold: 5}});
    await f.viewResearch(); await flush(); await flush();
    assert.match(f.root.querySelector('#rcost').textContent, /Auto-reload adds \$20\.00 when your balance falls to \$5\.00, charging your card \$21\.10\.$/);
    f = research(declined);
    await f.viewResearch(); await flush(); await flush();
    assert.match(f.root.querySelector('#rcost').textContent, /Auto-reload couldn’t charge your card, so it stops by itself if your credits run out\.$/);
    assert.doesNotMatch(f.root.querySelector('#rcost').textContent, /Auto-reload adds/);
    assert.match(f.root.querySelector('#dispatch .notice').innerHTML,
      /a research session needs at least \$1\.00 to start\. Auto-reload couldn’t charge your card\. <a href="\/billing">Update your card and add credits →<\/a>/);
  });
}
