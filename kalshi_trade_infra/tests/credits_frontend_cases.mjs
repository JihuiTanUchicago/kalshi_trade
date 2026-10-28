// Shared cases, run against each bundle's offline harness (Tau and Meridian): what credits cost, how long
// they last and what happens next, as Billing and the autopilot card say it.
// - A top-up's price is the card's charge to the cent (the server's half-up decimal, not a float sum), an
//   amount out of range says the range before the press, and the confirmation states what was charged.
// - "How long credits last" counts to where research pauses, and with auto-reload on it says when the card
//   is next charged and for how much, instead of a red "Credits last" that auto-reload prevents.
// - A credits pause while the auto-reload card is declined names the card as the step, everywhere.
import assert from './assert_text.mjs';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';

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
    assert.match(note(), /^You’ll pay \$20\.05 \(\$19\.00 credits \+ 5\.5% fee\)\./);
    amt.value = '37'; amt.oninput();
    assert.match(note(), /^You’ll pay \$39\.04 \(\$37\.00 credits/);  // 39.035 half up
    for (const v of ['3', '2000']) {
      amt.value = v; amt.oninput();
      assert.equal(note(), 'Add between $5.00 and $1,000.00 in credits.');
    }
    amt.value = '19'; amt.oninput();
    const btn = f.root.querySelector('#topup-btn');
    await btn.onclick({currentTarget: btn}); await flush();
    assert.match(f.root.querySelector('#topup-flash').innerHTML, /Added \$19\.00 in credits\. You paid \$20\.05 — \$19\.00 plus the 5\.5% fee\. New balance is \$26\.42\./);
  });

  test(`${name}: Billing's week split adds up to the week shown, and a part under a cent says so instead of vanishing`, async () => {
    // Walk 2026-10-27: "$38.85 + $0.18 + $0.18" sat under "Spent, last 7 days $39.22", and $0.0004 of other agent
    // calls was left out. The server now sends the parts in cents that add up (credit_split) and names the one
    // that rounds to $0.00.
    const f = billingPage(cardedBilling({spent_7d: 39.22, spent_24h: 3.1, min_run_balance: 1,
      spent_7d_by: {research: 0, autopilot_research: 38.85, autopilot_review: 0.19, chat: 0.18, other: 0},
      spent_7d_under_cent: ['other']}));
    await f.viewBilling(); await flush();
    const split = f.root.querySelector('#bsplit').textContent;
    assert.equal(split, 'Last 7 days: autopilot research $38.85 · autopilot check-ins $0.19 · chat $0.18 · other agent calls under $0.01.');
    const shown = [...split.matchAll(/(?<!under )\$(\d+\.\d\d)/g)].reduce((a, m) => a + Math.round(+m[1] * 100), 0);
    assert.match(f.root.querySelector('#bfigs').textContent, /Spent, last 7 days\s*\$39\.22/);
    assert.equal(shown, 3922);  // the parts shown are the week shown
    assert.doesNotMatch(split, /your research sessions/);  // nothing spent: not named
    // A server without the field keeps the old split: nothing new is named.
    const old = billingPage(cardedBilling({spent_7d_by: {research: 1.2, chat: 0}}));
    await old.viewBilling(); await flush();
    assert.equal(old.root.querySelector('#bsplit').textContent, 'Last 7 days: your research sessions $1.20.');
  });

  test(`${name}: Billing's credit balance is a neutral figure, not a P&L gain's green, and still red when it stops research`, async () => {
    // Credits are not profit: Tau's $25.71 balance wore the green a P&L gain wears (tint pos).
    const tone = async (o) => {
      const f = billingPage(cardedBilling(o));
      await f.viewBilling(); await flush();
      return f.root.querySelector('#bfigs .m:first-child .fig').className;
    };
    assert.doesNotMatch(await tone({balance: 25.71, min_run_balance: 1}), /tint|pos|gain/);
    assert.match(await tone({balance: 0.4, min_run_balance: 1}), /tint neg/);  // under the research floor
    assert.match(await tone({balance: -0.3, min_run_balance: 1}), /tint neg/);
  });

  test(`${name}: the statement's credits added wear their own neutral tone, not a P&L gain's, and a debit still reads as one`, async () => {
    // Top-ups, auto-reloads and the welcome bonus were drawn in the `gain` class, the one a P&L gain wears.
    const at = (day) => ({day, created_at: `${day}T09:00:00Z`, first_at: `${day}T09:00:00Z`});
    const f = billingPage(cardedBilling({ledger_cut: false, ledger: [
      {kind: 'usage', amount: -1.25, item: 'Autopilot research', model: 'Claude Opus 4.6', calls: 3, ...at('2026-10-26')},
      {kind: 'autoreload', amount: 25, card_charge: 26.38, ...at('2026-10-26')},
      {kind: 'topup', amount: 10, card_charge: 10.55, ...at('2026-10-25')},
      {kind: 'bonus', amount: 20, memo: 'Welcome credits', ...at('2026-10-24')}]}));
    await f.viewBilling(); await flush();
    const amounts = [...f.root.querySelectorAll('#bledger tbody tr')].filter((tr) => !tr.querySelector('.day-sum'))
      .map((tr) => { const m = tr.querySelector('td.num').innerHTML.match(/^<span class="([^"]*)">([^<]*)<\/span>$/) || []; return {cls: m[1], text: m[2]}; });
    assert.equal(amounts.length, 4);
    assert.deepEqual(amounts.map((a) => a.cls), ['credit-out', 'credit-in', 'credit-in', 'credit-in']);
    for (const a of amounts) assert.doesNotMatch(a.cls, /gain|loss|pos|neg/);
    assert.deepEqual(amounts.map((a) => a.text), ['−$1.25', '+$25.00', '+$10.00', '+$20.00']);
    // The theme's stylesheet draws both in neutral ink: no P&L green on a credit line.
    const css = readFileSync(new URL(`../app/static/${name === 'Meridian' ? 'app.meridian.css' : 'app.css'}`, import.meta.url), 'utf8');
    const rules = css.match(/[^{}]*\.credit-(?:in|out)[^{}]*\{[^}]*\}/g) || [];
    assert.ok(rules.length);
    for (const r of rules) assert.doesNotMatch(r, /gain-ink|--pos|--up|#0E5C33|#365D3B/i);
    assert.match(css, /\.t-ledger \.credit-in, \.t-ledger \.credit-out \{ color: var\(--ink\);/);
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

  test(`${name}: the autopilot card says "under $0.01" for a sliver of spend, as Billing does, not $0.00`, async () => {
    // Billing's split read "autopilot check-ins under $0.01" while the card dropped the check-ins (or said $0.00
    // of research) for the same week. The server names a figure that spent something but rounds to $0.00.
    const spent = (w) => f.root.querySelector('#dash-ap .ap-week dl dd').textContent.replace(/\s+/g, ' ');
    let f = await apPage({...apStatus, week: {...week, research_credits: 20.01, checkin_credits: 0, checkin_under_cent: true}}, {});
    assert.match(spent(), /^\$20\.01 plus under \$0\.01 on its check-ins$/);
    f.clearTimers();
    f = await apPage({...apStatus, week: {...week, research_credits: 0, research_under_cent: true, checkin_credits: 0.09}}, {});
    assert.match(spent(), /^under \$0\.01 plus \$0\.09 on its check-ins$/);
    assert.doesNotMatch(spent(), /\$0\.00/);
    f.clearTimers();
    // Only a sliver spent, nothing else this week: not "nothing yet" beside Billing's "under $0.01".
    const sliver = {research_credits: 0, tested: 0, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0,
      checkin_credits: 0, checkin_under_cent: true, credits_left: 20, runway_days: null, pace_days: 7};
    f = await apPage({...apStatus, week: sliver}, {});
    assert.doesNotMatch(f.root.querySelector('#dash-ap .ap-week').textContent, /nothing yet/);
    assert.match(spent(), /^None yet but under \$0\.01 on its check-ins$/);
    f.clearTimers();
    // No flag (nothing spent, or an older server): the figures as before, no check-ins named at $0.
    f = await apPage({...apStatus, week: {...week, checkin_credits: 0}}, {});
    assert.match(spent(), /^\$100\.01$/);
    f.clearTimers();
    // Nothing spent on research while the week has other figures: "None yet", never "$0.00 research spend", and
    // no word on who paid for nothing, whatever card_charged says.
    for (const charged of [true, false, undefined]) {
      f = await apPage({...apStatus, week: {...week, research_credits: 0, checkin_credits: 0, card_charged: charged}}, {});
      assert.equal(spent(), 'None yet');
      f.clearTimers();
    }
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

  test(`${name}: a Billing day whose only use was under a cent says "under $0.01 used", not a bare date`, async () => {
    // Walk 2026-10-28: a day with one short chat (−$0.004) showed its date and nothing beside it.
    const f = billingPage(cardedBilling({
      math: {days: 30, start: 20, bought: 0, purchases: 0, other: 0, usage: 0, end: 20},
      ledger: [{kind: 'usage', amount: -0.0043, item: 'Chat', model: 'Claude Sonnet 4.6', calls: 1, day: '2026-10-26',
        created_at: '2026-10-26T15:00:00Z', first_at: '2026-10-26T15:00:00Z'}],
      ledger_cut: false}));
    await f.viewBilling(); await flush();
    assert.equal(f.root.querySelector('#bledger .day-sum').textContent, 'under $0.01 used');
    assert.equal(f.root.querySelector('#bledger td.num').textContent, '−\u2060$0.004');
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

  test(`${name}: a new subscriber's statement starts when they joined, not "30 days ago"`, async () => {
    const math = {days: 30, start: 0, bought: 0, purchases: 0, other: 20, usage: 0, end: 20};
    const ledger = [{kind: 'bonus', amount: 20, memo: 'Welcome credits', day: '2026-10-27', created_at: '2026-10-27T15:40:00Z', first_at: '2026-10-27T15:40:00Z'}];
    const f = billingPage(cardedBilling({math: {...math, joined: true}, ledger, ledger_cut: false}));
    await f.viewBilling(); await flush();
    const sum = f.root.querySelector('.bill-math').textContent;
    assert.match(sum, /^Balance when you joined\s*\$0\.00/);
    assert.doesNotMatch(sum, /30 days ago/);
    const aged = billingPage(cardedBilling({math, ledger, ledger_cut: false}));
    await aged.viewBilling(); await flush();
    assert.match(aged.root.querySelector('.bill-math').textContent, /^Balance 30 days ago\s*\$0\.00/);
  });

  // Walk 2026-10-27, out of credits and running low: Billing's top-up line read "You'll pay $21.00 ... that's about
  // 20 days of research" with straight apostrophes under a notice that wrote them curly. Every line a customer reads
  // when credits run out or run low writes an apostrophe curly, and none prices credits against a list price or a markup.
  test(`${name}: out of credits and running low, Billing and the autopilot card write apostrophes curly and never say "list price"`, async () => {
    const straight = /[A-Za-z]'[A-Za-z]/, pricing = /list price|mark-?up|margin/i;
    const read = (text, where) => {
      assert.doesNotMatch(text, straight, `${where}: ${text.match(straight)}`);
      assert.doesNotMatch(text, pricing, where);
    };
    for (const o of [{balance: 0, auto_reload: false}, {balance: 0.62, auto_reload: true},
      {balance: 0.62, auto_reload: true, reload_failed: {at: '2026-10-26T21:49:00Z', text: FAILED}}]) {
      const f = billingPage(cardedBilling({spent_7d: 7, pace_days: 7, runway_days: null, reload_days: null, min_run_balance: 1, ...o}));
      await f.viewBilling(); await flush();
      const amt = f.root.querySelector('#topup-amt'); amt.value = '20'; amt.oninput();
      const main = f.root.querySelector('#main').textContent;
      assert.match(main, o.balance <= 0 ? /You’re out of credits\./ : /You have \$0\.62 in credits\./);
      assert.match(f.root.querySelector('#topup-note').textContent, /^You’ll pay \$21\.\d\d \(\$20\.00 credits \+ [\d.]+% fee\)\. At your pace \(\$7\.00 a week\) that’s about 20 days of research\.$/);
      read(main, `Billing at ${o.balance}`);
      read(f.root.querySelector('#bfigs').textContent, 'Billing figures');
    }
    for (const [status, me] of [
      [{...apStatus, billing_blocked: true, billing_reason: 'credits', week: {...week, credits_left: 0, runway_days: null, reload_days: null}}, {credit_balance: 0}],
      [{...apStatus, billing_blocked: true, billing_reason: 'credits', reload_failed: FAILED, week: {...week, credits_left: 0.62, runway_days: null, reload_days: null}},
        {credit_balance: 0.62, auto_reload: {amount: 25, charge: 26.38, threshold: 5}}],
      [{...apStatus, credits_low_days: 1.5, week: {...week, reload_days: null}}, {credit_balance: 3}]]) {
      const f = await apPage(status, me);
      read(f.root.querySelector('#dash-ap').textContent, `autopilot card ${status.billing_blocked ? 'paused' : 'low'}`);
      f.clearTimers();
    }
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
