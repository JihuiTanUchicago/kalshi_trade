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
    const main = f.root.querySelector('main').textContent;
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
    f.clearTimers();
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
}
