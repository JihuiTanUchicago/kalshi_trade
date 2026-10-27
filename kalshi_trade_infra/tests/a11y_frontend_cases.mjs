// Shared cases, run against each bundle's offline harness (Tau and Meridian), from an accessibility pass
// (axe-core plus a live-region watch in Playwright, both themes, 390px and 1280px, 2026-10-27):
// - The autopilot panel's pulse is a polite live region. Each chat poll (3s) rewrote it with the same
//   words, so a screen reader said "Between reviews · 2 on paper" again and again: only a change is written.
// - The research session's foot counted "Researching · 12s" up every second inside a live region, so a
//   screen reader read every tick: the count is not live, and a change of state is said once.
// - A figure's sub-line ("paper money, not real") is a <dd> of its term, not a bare <div> inside the <dl>
//   that a screen reader skipped, so the kind of money is read with the figure.
// - The research and autopilot logs are lists that announce additions (aria-live), not role="log" on
//   the <ol>, which took away the list and its items.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));

export function a11yCases({name, frontend, storageFor, billingPage, cardedBilling}) {
  test(`${name}: the autopilot pulse is written only when its words change, not on every chat poll`, async () => {
    let chat = {messages: [], agent_busy: false};
    const store = new Map([['tau_ap_open', '1']]);
    const f = frontend({storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/chat?')) return response(chat);
      if (path === '/api/models') return response({models: [], default: ''});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7, autopilot: true}};
    f.S.ap = {...f.S.ap, autopilot: true, mode: 'paper', paper_running: 2};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null); await flush(); await flush();
    const pulse = box.querySelector('#apf-pulse');
    assert.equal(pulse.getAttribute('aria-live'), 'polite');
    assert.match(pulse.innerHTML, /Between reviews · 2 on paper/);
    const writes = pulse.writes;
    for (let i = 0; i < 4; i++) { await f.apLoadChat(box, false); await flush(); }
    assert.equal(pulse.writes, writes, 'a poll with the same words left the live region alone');
    // The status read (every 20s) with the same line leaves it alone too.
    f.apUpdate(box, {...f.S.ap});
    assert.equal(pulse.writes, writes);
    // A real change is written, once.
    chat = {messages: [], agent_busy: true};
    await f.apLoadChat(box, false); await f.apLoadChat(box, false); await flush();
    assert.equal(pulse.writes, writes + 1);
    assert.match(pulse.innerHTML, /Working on its next move/);
    chat = {messages: [], agent_busy: false};
    await f.apLoadChat(box, false); await flush();
    assert.equal(pulse.writes, writes + 2);
    assert.match(pulse.innerHTML, /Between reviews/);
  });

  test(`${name}: a research session's seconds count is not read out each second; a change of state is said once`, async () => {
    const f = frontend();
    const section = f.document.createElement('section');
    section.innerHTML = '<ol class="log"></ol><button class="jumplatest"></button><div class="runpulse"></div>';
    f.document.body.appendChild(section);
    const stream = f.runFeed(section), pulse = section.querySelector('.runpulse');
    const said = () => { f.elapse(50); const el = f.document.getElementById('sr-status'); return el ? el.textContent : ''; };
    stream.state('queued', {state: 'queued', seconds: 200, overdue: false});
    for (const tick of [...f.intervals.values()]) tick();
    const label = pulse.querySelector('[data-plabel]');
    if (label) assert.match(label.textContent, /^Queued · 20\ds$/);  // Tau counts the wait in the foot
    assert.equal(said(), '', 'the first paint and the ticks say nothing');
    stream.state('running');
    if (label) {
      assert.equal(said(), 'Researching');
      for (const tick of [...f.intervals.values()]) tick();
      stream.state('running');
      assert.equal(said(), 'Researching', 'the same state again is not said again');
      stream.state('paused');
      assert.equal(said(), 'Paused — resume and it picks up exactly where it left off.');
    } else {
      assert.equal(said(), '');  // Meridian has no foot: its run status is said by the page above
    }
    f.clearTimers();
    // On the page, the foot that ticks is not itself a live region, and the log is a list that announces.
    const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
    const g = frontend({fetchImpl: (path) => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: []}); }});
    await g.viewRun(9);
    const foot = g.root.querySelector('#runpulse');
    if (foot) assert.equal(foot.getAttribute('aria-live'), null);
    const log = g.root.querySelector('#log');
    assert.equal(log.tag, 'ol'); assert.equal(log.getAttribute('role'), null); assert.equal(log.getAttribute('aria-live'), 'polite');
    g.clearTimers();
  });

  test(`${name}: a figure's sub-line belongs to its term, so the kind of money is read with the figure`, async () => {
    const f = billingPage(cardedBilling({balance: 25.71, spent_7d: 100.17, runway_days: 1.7, reload_days: 1.4, pace_days: 7,
      autoreload_threshold: 5, autoreload_charge: 26.38, min_run_balance: 1}));
    await f.viewBilling(); await flush();
    const cells = f.root.querySelectorAll('#bfigs .m');
    assert.ok(cells.length >= 2);
    const subs = f.root.querySelectorAll('#bfigs .sub-fig');
    assert.ok(subs.length >= 1, 'the billing figures carry sub-lines');
    for (const cell of cells) assert.deepEqual(cell.children.map((c) => c.tag).filter((t) => t !== 'dt' && t !== 'dd'), []);
    for (const sub of subs) assert.equal(sub.tag, 'dd');
  });

  test(`${name}: the autopilot activity is a list that announces what is added`, async () => {
    const store = new Map([['tau_ap_open', '1']]);
    const f = frontend({storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/chat?')) return response({messages: [], agent_busy: false});
      if (path === '/api/models') return response({models: [], default: ''});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7}};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null); await flush();
    const msgs = box.querySelector('#apf-messages');
    assert.equal(msgs.tag, 'ol'); assert.equal(msgs.getAttribute('role'), null);
    assert.equal(msgs.getAttribute('aria-live'), 'polite'); assert.equal(msgs.getAttribute('aria-label'), 'Autopilot activity');
  });
}
