// Shared cases, run against each bundle's offline harness (Tau and Meridian): a write that hangs says so.
// A write Tau hasn't answered kept its spinner until the edge's 504, with no word. After 20s the pressed
// control's area says "Still waiting for Tau to confirm…". Display only: the write is never aborted, sent
// again or given a deadline, and the note goes the moment the write answers.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const NOTE = 'Still waiting for Tau to confirm…';
const notes = (el) => el.querySelectorAll('.wait-note').filter((n) => n.isConnected);
// A write the server holds until land() (as a hung box would, up to the edge's 504).
const hung = () => { let answer; const p = new Promise((resolve) => { answer = resolve; }); return {p, land: (data = {ok: true}) => answer(response(data))}; };
const dep = (overrides = {}) => ({id: 1, strategy_id: 1, title: 'Dep one', market: 'btc15m', mode: 'paper', status: 'running',
  status_reason: null, realized_pnl: 1, closed_trades: 5, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z',
  curve: [], stake: 5, max_positions: 1, backtest: {out_of_sample: null}, ...overrides});

export function writeWaitCases({name, frontend, billingPage, cardedBilling, storageFor, postRequests}) {
  // The note's rules, the same for every write: none before 20s, one beside the control at 20s, no
  // abort signal and no second send, and gone once the write answers.
  const waitsThenGoes = async (f, control, write, path, scope = f.root) => {
    f.elapse(19999);
    assert.equal(notes(scope).length, 0, 'nothing before 20s');
    f.elapse(20000);
    const shown = notes(scope);
    assert.deepEqual(shown.map((n) => n.textContent), [NOTE]);
    assert.equal(shown[0].parentElement, control().parentElement, "in the pressed control's area");
    const sent = postRequests(f).filter((r) => r.path === path);
    assert.equal(sent.length, 1, 'never sent again');
    assert.equal(sent[0].options.signal, undefined, 'no client deadline on a write');
    write.land(); await settle();
    assert.equal(notes(scope).length, 0, 'gone once the write answers');
    assert.equal(shown[0].isConnected, false);
  };

  test(`${name}: Pause on Deploy that hangs says Tau hasn't confirmed after 20s, and the word goes when it answers`, async () => {
    const write = hung();
    let paused = false;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments' || path.startsWith('/api/deployments?')) return response({deployments: [dep({status: paused ? 'paused' : 'running'})], open_positions: []});
      if (path === '/api/deployments/1/pause') return write.p.then((r) => { paused = true; return r; });
      if (path === '/api/strategies?status=passed') return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const pause = f.root.querySelector('#deps [data-act="pause"]');
    pause.onclick(); await settle();
    assert.ok(pause.classList.contains('busy'));
    await waitsThenGoes(f, () => pause, write, '/api/deployments/1/pause');
    assert.ok(f.root.querySelector('#deps [data-act="resume"]'), 'the action still lands as before');
    f.clearTimers();
  });

  test(`${name}: Remove on Deploy keeps its note on the button a poll repainted while it waits`, async () => {
    const write = hung();
    let reads = 0;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments' || path.startsWith('/api/deployments?')) {
        reads++;  // a trade closed between reads, so each read repaints the board
        return response({deployments: [dep({closed_trades: 5 + reads})], open_positions: []});
      }
      if (path === '/api/deployments/1/stop') return write.p;
      if (path === '/api/strategies?status=passed') return response({counts: {passed: 1}});
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const first = f.root.querySelector('#deps [data-dep="1"][data-act="stop"]');
    first.onclick(); f.elapse(500); first.onclick(); await settle();  // the armed confirm, then the send
    assert.equal(postRequests(f).length, 1);
    f.elapse(20000);
    assert.equal(notes(f.root).length, 1);
    for (const tick of [...f.intervals.values()]) await tick();
    await settle();
    const now = f.root.querySelector('#deps [data-dep="1"][data-act="stop"]');
    assert.notEqual(now, first, 'the poll repainted the row');
    assert.deepEqual(notes(f.root).map((n) => n.textContent), [NOTE]);
    assert.equal(notes(f.root)[0].parentElement, now.parentElement, 'beside the repainted button');
    write.land(); await settle();
    assert.equal(notes(f.root).length, 0);
    f.clearTimers();
  });

  test(`${name}: a chat send that hangs says Tau hasn't confirmed after 20s, and the word goes when it answers`, async () => {
    const write = hung(), store = new Map([['tau_ap_open', '1']]);
    const f = frontend({storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/chat?')) return response({messages: [], agent_busy: false});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/chat') return write.p;
      return response({});
    }});
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7, autopilot: false}};
    f.S.ap = {...f.S.ap, autopilot: false, mode: 'off'};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null);
    await settle();
    const ta = box.querySelector('#apf-msg'), form = box.querySelector('#apf-composer');
    ta.value = 'Only trade on paper this week'; ta.listeners.get('input')();
    const sending = form.onsubmit({preventDefault() {}}); await settle();
    await waitsThenGoes(f, () => form.querySelector('button'), write, '/api/chat', box);
    await sending;
    f.clearTimers();
  });

  test(`${name}: Buy credits that hangs says Tau hasn't confirmed after 20s, and the word goes when it answers`, async () => {
    const write = hung();
    const f = billingPage(cardedBilling(), [], {'/api/billing/topup': () => write.p.then(() => response({ok: true, balance: 32.5, charged: 21.1}))});
    await f.viewBilling(); await settle();
    const btn = f.root.querySelector('#topup-btn');
    btn.onclick({currentTarget: btn}); await settle();
    await waitsThenGoes(f, () => btn, write, '/api/billing/topup');
    assert.match(f.root.querySelector('#topup-flash').innerHTML, /Added \$20\.00 in credits/);
    f.clearTimers();
  });

  test(`${name}: the auto-reload switch that hangs says Tau hasn't confirmed after 20s, beside the switch`, async () => {
    const write = hung();
    const f = billingPage(cardedBilling(), [], {'/api/billing/auto-reload': () => write.p});
    await f.viewBilling(); await settle();
    const sw = f.root.querySelector('#autoreload');
    sw.checked = false;
    const saving = sw.onchange(); await settle();
    assert.equal(sw.disabled, true);
    await waitsThenGoes(f, () => sw.closest('.switch'), write, '/api/billing/auto-reload');
    await saving;
    assert.equal(sw.disabled, false);
    f.clearTimers();
  });

  // The autopilot switch's writes, while the card and the panel repaint around them (the 15s board poll,
  // the 20s status read): a hung Turn on came back pressable with its note gone, and a hung flip of the
  // panel switch was put back to the old state by the next status read, with no word.
  const apDash = () => ({paper: {equity: 1000, cash: 1000, open_at_cost: 0, total_pnl: 0, realized_pnl: 0}, live: {connected: false},
    demo: {equity: 1000, capital: 1000}, deployments: [], open_positions: [], recent_closed: [], freshness: {btc: null},
    agents: {research_running: 0, research_queued: 0}});
  const apFetch = (write, status) => (path) => {
    if (path === '/api/dashboard') return response(apDash());
    if (path === '/api/settings') return write.p;
    if (path === '/api/autopilot/status') return response(status());
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    return response({});
  };

  test(`${name}: a Turn on autopilot that hangs stays pressed, with its note, on the card a poll repainted`, async () => {
    const write = hung();
    const f = frontend({fetchImpl: apFetch(write, () => ({autopilot: false, mode: 'off'}))});
    f.S.me = {...f.S.me, user: {...f.S.me.user, autopilot: false}};
    f.S.ap = {autopilot: false, mode: 'off'};
    f.location.pathname = '/';
    await f.viewDashboard(); await settle();
    const first = f.root.querySelector('#dash-ap [data-apcard="on"]');
    const turning = first.onclick(); await settle();
    f.elapse(20000);
    f.paintDashAp();  // what the board poll and the status read do
    const now = f.root.querySelector('#dash-ap [data-apcard="on"]');
    assert.notEqual(now, first, 'the card repainted');
    assert.ok(now.classList.contains('busy')); assert.equal(now.disabled, true);
    assert.deepEqual(notes(f.root).map((n) => n.textContent), [NOTE]);
    assert.equal(notes(f.root)[0].parentElement, now.parentElement, 'beside the repainted button');
    assert.equal(postRequests(f).filter((r) => r.path === '/api/settings').length, 1, 'never sent again');
    write.land(response({error: 'Not allowed'}, 400)); await turning; await settle();
    const after = f.root.querySelector('#dash-ap [data-apcard="on"]');
    assert.equal(after.disabled, false); assert.equal(after.classList.contains('busy'), false);
    assert.equal(notes(f.root).length, 0);
    f.clearTimers();
  });

  test(`${name}: the panel's autopilot switch stays where it was flipped while Tau hasn't answered, and says so after 20s`, async () => {
    const write = hung(), store = new Map([['tau_ap_open', '1']]);
    let landed = false;
    write.p.then(() => { landed = true; });
    const f = frontend({storage: storageFor(store), fetchImpl: apFetch(write, () => (landed ? {autopilot: false, mode: 'off'} : {autopilot: true, mode: 'paper'}))});
    f.S.me = {...f.S.me, user: {...f.S.me.user, id: 7, autopilot: true}};
    f.S.ap = {autopilot: true, mode: 'paper'};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, f.S.ap); await settle();
    const sw = box.querySelector('#apf-apswitch');
    sw.checked = false;
    const flipping = sw.onchange(); await settle();
    f.renderAutopilot(box, {autopilot: true, mode: 'paper'});  // a status read that left before the write landed
    assert.equal(sw.checked, false, 'not put back by the status read'); assert.equal(sw.disabled, true);
    await waitsThenGoes(f, () => sw.closest('.switch'), write, '/api/settings', box);
    await flipping;
    assert.equal(sw.disabled, false); assert.equal(f.S.me.user.autopilot, false);
    f.clearTimers();
  });

  // The edge gave up on a switch (its 502 page): Tau may have switched it. It said "Reload the page to
  // check"; the card and the panel read the switch again within half a minute, so the words point there.
  test(`${name}: an autopilot switch the edge answered with a 502 says Tau didn't confirm and where to look`, async () => {
    const UNSURE = 'Tau didn’t confirm this, so autopilot may or may not have switched. Its status here updates within half a minute; check it before you try again.';
    const edge = {p: Promise.resolve({ok: false, status: 502, json: async () => { throw new SyntaxError('not JSON'); }})};
    const f = frontend({fetchImpl: apFetch(edge, () => ({autopilot: false, mode: 'off'}))});
    f.S.me = {...f.S.me, user: {...f.S.me.user, autopilot: false}};
    f.S.ap = {autopilot: false, mode: 'off'};
    f.location.pathname = '/';
    await f.viewDashboard(); await settle();
    await f.root.querySelector('#dash-ap [data-apcard="on"]').onclick(); await settle();
    assert.equal(f.root.querySelector('#dash-ap .apcard-err').innerHTML, UNSURE);
    assert.equal(postRequests(f).filter((r) => r.path === '/api/settings').length, 1, 'never sent again');
    f.clearTimers();

    const store = new Map([['tau_ap_open', '1']]);
    const g = frontend({storage: storageFor(store), fetchImpl: apFetch(edge, () => ({autopilot: true, mode: 'paper'}))});
    g.S.me = {...g.S.me, user: {...g.S.me.user, id: 7, autopilot: true}};
    const box = g.document.createElement('div'); box.id = 'autopilot-float'; g.document.body.appendChild(box);
    g.renderAutopilot(box, {autopilot: true, mode: 'paper'}); await settle();
    const sw = box.querySelector('#apf-apswitch');
    sw.checked = false; await sw.onchange(); await settle();
    assert.match(box.querySelector('#apf-flash').innerHTML, /Tau didn’t confirm this, so autopilot may or may not have switched\. Its status here updates within half a minute; check it before you try again\./);
    assert.doesNotMatch(box.querySelector('#apf-flash').innerHTML, /Reload the page/);
    assert.equal(sw.checked, true, 'back at what Tau last said');
    g.clearTimers();
  });
}
