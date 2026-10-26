// Shared cases, run against each bundle's offline harness (Tau and Meridian): the autopilot chat's
// composer and proposals (walked 2026-10-26 on a phone and a desktop with the model stubbed).
// - A message half typed survives a reload: kept per account in this browser until it is sent.
// - The line under the composer says what the agent may do with a message (on: act within your
//   limits; off: suggest, for your Approve) and, with payments on, that each message is paid from
//   credits and what the last one cost (the chat read's turn_cost).
// - Out of credits, the failed send links to Billing and keeps the message.
// - A pause proposal says, before Approve, that pausing sells what the strategy holds.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const AT = '2026-10-26T21:00:00Z';
const DRAFT = 'tau_ap_draft:7';

export function chatPanelCases({name, frontend, storageFor}) {
  const panel = async ({chat = () => [], turnCost, post, store = new Map(), me = {}, autopilot = false} = {}) => {
    store.set('tau_ap_open', '1');
    const f = frontend({storage: storageFor(store), fetchImpl: (path, options) => {
      if (path.startsWith('/api/chat?')) {
        const d = {messages: chat(), agent_busy: false};
        if (turnCost !== undefined) d.turn_cost = turnCost;
        return response(d);
      }
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/chat' && post) return post(options);
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, ...me, user: {...(f.S.me && f.S.me.user), id: 7, autopilot}};
    f.S.ap = {...f.S.ap, autopilot, mode: autopilot ? 'paper' : 'off'};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null);
    await flush(); await flush();
    return {f, box, store, ta: box.querySelector('#apf-msg'), form: box.querySelector('#apf-composer'),
      cost: () => box.querySelector('#apf-cost').textContent};
  };
  const type = (ta, text) => { ta.value = text; ta.listeners.get('input')(); };

  test(`${name}: a message half typed in the autopilot chat comes back after a reload, until it is sent`, async () => {
    const store = new Map(), sent = [];
    let p = await panel({store});
    assert.equal(p.ta.value, '');
    type(p.ta, 'Focus on Bitcoin, and');
    assert.equal(store.get(DRAFT), 'Focus on Bitcoin, and');
    p = await panel({store, post: (options) => { sent.push(JSON.parse(options.body)); return response({id: 3}); }});  // the reload
    assert.equal(p.ta.value, 'Focus on Bitcoin, and');
    type(p.ta, 'Focus on Bitcoin, and only on paper');
    await p.form.onsubmit({preventDefault() {}}); await flush();
    assert.deepEqual(sent, [{content: 'Focus on Bitcoin, and only on paper'}]);
    assert.equal(p.ta.value, ''); assert.equal(store.get(DRAFT), '');  // sent: nothing comes back
    p = await panel({store});
    assert.equal(p.ta.value, '');
  });

  test(`${name}: the line under the composer says what a message may do and what the last one cost`, async () => {
    const billed = {billing_enabled: true};
    let p = await panel({me: billed, turnCost: 0.153});
    assert.equal(p.cost(), 'Any change it suggests waits for your Approve. Each message is paid from your credits. Your last one cost $0.15.');
    assert.equal(p.box.querySelector('#apf-cost').hidden, false);
    p = await panel({me: billed, turnCost: 0.153, autopilot: true});
    assert.equal(p.cost(), 'It may act on what you ask, within your limits. Each message is paid from your credits. Your last one cost $0.15.');
    p = await panel({me: billed, turnCost: null});  // no answered message yet
    assert.equal(p.cost(), 'Any change it suggests waits for your Approve. Each message is paid from your credits.');
    p = await panel({me: billed, turnCost: 0});  // a turn that failed before the model ran
    assert.match(p.cost(), /Your last one cost nothing\.$/);
    p = await panel({me: billed, turnCost: 0.004});  // under half a cent is not "$0.00"
    assert.match(p.cost(), /Your last one cost under \$0\.01\.$/);
    p = await panel({me: {billing_enabled: false}, turnCost: 0.153});  // payments off: nothing is billed
    assert.equal(p.cost(), 'Any change it suggests waits for your Approve.');
    // A poll without turn_cost keeps the figure the last read gave.
    let calls = 0;
    p = await panel({me: billed, chat: () => (calls++, []), turnCost: 0.42});
    assert.match(p.cost(), /\$0\.42\.$/);
  });

  test(`${name}: out of credits, the failed send links to Billing and keeps the message`, async () => {
    const store = new Map();
    const p = await panel({store, me: {billing_enabled: true}, post: () => response({error: "You're out of credits. Add credits on the Billing tab to keep chatting with the agent."}, 402)});
    type(p.ta, 'Anything new?');
    await p.form.onsubmit({preventDefault() {}}); await flush();
    const err = p.box.querySelector('#apf-err');
    assert.equal(err.hidden, false);
    assert.match(err.innerHTML, /^You&#39;re out of credits\.|^You're out of credits\./);
    assert.match(err.innerHTML, /<a href="\/billing">Open Billing<\/a>$/);
    assert.equal(p.ta.value, 'Anything new?'); assert.equal(store.get(DRAFT), 'Anything new?');
  });

  test(`${name}: a pause proposal says Approve sells what the strategy holds, in its book`, async () => {
    const line = (o) => ({id: o.id, role: 'system', content: 'Proposed to pause BTC fade.', created_at: AT, proposal_id: o.id,
      proposal_kind: o.kind, proposal_status: 'pending', deployment_mode: o.mode});
    const p = await panel({chat: () => [line({id: 1, kind: 'pause', mode: 'paper'}), line({id: 2, kind: 'pause', mode: 'live'}),
      line({id: 3, kind: 'resume', mode: 'paper'})]});
    const asks = p.box.querySelectorAll('.apf-ask').map((el) => el.textContent);
    assert.deepEqual(asks, [
      'Approve pauses this strategy, which runs on paper, with practice money, and sells anything it holds.',
      'Approve pauses this strategy, which runs LIVE, with real money in your Kalshi account, and sells anything it holds.',
      'Approve restarts this strategy, which runs on paper, with practice money.',
    ]);
  });
}
