// Shared cases, run against each bundle's offline harness (Tau and Meridian): the autopilot chat's
// composer and proposals (walked 2026-10-26 on a phone and a desktop with the model stubbed).
// - A message half typed survives a reload: kept per account in this browser until it is sent.
// - The line under the composer says what the agent may do with a message (on: act within your
//   limits; off: suggest, for your Approve) and, with payments on, that each message is paid from
//   credits and what the last one cost (the chat read's turn_cost).
// - Out of credits, the failed send links to Billing and keeps the message.
// - A send Tau didn't confirm says the message shows in the chat if it went through (the chat's next read
//   shows it), never to reload the page.
// - A pause proposal says, before Approve, that pausing sells what the strategy holds.
// - "Last move" keeps a strategy name that holds " — " whole (it read "I left Fade the late spike."),
//   using the names the server lists in la.titles, and shows the engine's own pause by name.
// - Asked to pause a strategy on paper under a day, the agent's reply can suggest pausing it and the
//   next line says "I left it running". That line is headed as the autopilot's own rule, not
//   "Reviewed", and says your own Pause on Deploy still stops it.
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

  test(`${name}: a send Tau didn't confirm says the message shows in the chat if it went through, not to reload`, async () => {
    // It said "Reload the page to check", but the open chat reads every few seconds and shows the message once it lands.
    const UNSURE = 'Tau didn’t confirm your message. If it went through, it shows up in the chat in a few seconds; if it doesn’t, send it again.';
    for (const post of [() => Promise.reject(new TypeError('Failed to fetch')),  // no reply at all
      () => ({ok: false, status: 502, json: async () => { throw new SyntaxError('Unexpected token <'); }})]) {  // the edge's page
      let landed = [];
      const p = await panel({post, chat: () => landed});
      type(p.ta, 'Pause the BTC fade');
      await p.form.onsubmit({preventDefault() {}}); await flush();
      const err = p.box.querySelector('#apf-err');
      assert.equal(err.hidden, false);
      assert.equal(err.textContent, UNSURE);
      assert.doesNotMatch(err.textContent, /[Rr]eload/);
      assert.equal(p.ta.value, 'Pause the BTC fade');  // kept, for a send again if it never shows
      // It did land: the chat's next read shows it, as the line said.
      landed = [{id: 41, role: 'user', content: 'Pause the BTC fade', created_at: AT}];
      for (const tick of [...p.f.intervals.values()]) tick();
      await flush(); await flush();
      assert.ok(p.box.querySelector('#apf-messages').children.some((li) => /Pause the BTC fade/.test(li.innerHTML)));
    }
    // Tau's own words for a failure stay as Tau said them.
    const q = await panel({post: () => response({error: 'Messages are limited to 2,000 characters.'}, 400)});
    type(q.ta, 'x');
    await q.form.onsubmit({preventDefault() {}}); await flush();
    assert.equal(q.box.querySelector('#apf-err').textContent, 'Messages are limited to 2,000 characters.');
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

  const SPIKE = 'Fade the late spike — Bitcoin 15m', TAILS = 'Fade tails — v2';
  const KEPT = (title) => `I left ${title} running: it has been on paper for only 3.2 hours, and paper costs nothing `
    + 'while it builds the record the live gate needs (at least 24 hours before I pause it).';

  test(`${name}: the last move keeps a strategy name with a dash whole, and says the engine's pause by name`, async () => {
    const p = await panel({autopilot: true});
    const move = (text, titles) => p.f.apMoveText({text, at: AT, titles});
    // Before: "I left Fade the late spike" (cut at the name's dash).
    assert.equal(move(KEPT(SPIKE), [SPIKE]), `I left ${SPIKE} running`);
    assert.equal(move(KEPT(TAILS), [TAILS]), `I left ${TAILS} running`);  // a lowercase word after the dash too
    // The engine's pause, as the server says it (customer_text.auto_pause_line): the name, never "#12".
    assert.equal(move(`Paused your paper strategy ${TAILS} automatically: it lost $12.00, more than its $10.00 loss guard.`, [TAILS]),
      `Paused your paper strategy ${TAILS} automatically`);
    assert.equal(move('Paused your paper strategy Rain automatically: it lost $3.00, more than its $2.50 loss guard.'),
      'Paused your paper strategy Rain automatically');  // the reason, past 90 characters, is left to the feed
    // A clause after a dash outside any name is still cut, and a name the line doesn't hold changes nothing.
    assert.equal(move('Started a fresh research session on a market — same gates as any run.', [TAILS]),
      'Started a fresh research session on a market');
    assert.equal(move(`Autopilot paused ${TAILS}. It lost 22% of its money.`, [TAILS]), `Paused ${TAILS}`);
    // The line under the panel's pulse, as painted.
    p.f.apUpdate(p.box, {autopilot: true, mode: 'paper', research: {active: []}, last_action: {text: KEPT(SPIKE), at: AT, titles: [SPIKE]}});
    assert.match(p.box.querySelector('#apf-last').textContent, new RegExp(`: I left ${SPIKE} running\\.$`));
  });

  test(`${name}: "Furthest on paper" ends its net before the instant-fill note, never running one into the other`, async () => {
    // Walk 2026-10-27: the panel read "+$15.26 net on them instant-fill paper trades left out (...)" with nothing between.
    const p = await panel({autopilot: true});
    p.f.apUpdate(p.box, {autopilot: true, mode: 'paper', research: {active: []},
      paper_progress: {strategy_id: 3, title: 'Momentum', trades: 22, trades_needed: 30, net_pnl: 15.26, strategies: 1}});
    const stats = p.box.querySelector('#apf-stats');
    const dd = stats.querySelectorAll('dd').find((el) => /Momentum/.test(el.textContent));
    assert.ok(dd, stats.innerHTML);
    const said = dd.textContent.replace(/\s+/g, ' ');
    assert.match(said, /22 of 30 realistic paper trades · \+\$15\.26 net on them\. Instant-fill paper trades left out \(fills real execution would not get\)\.$/);
    assert.doesNotMatch(said, /net on them instant-fill/);
  });

  test(`${name}: autopilot keeping a young paper strategy reads as its own rule after the agent's suggestion`, async () => {
    const p = await panel({autopilot: true, chat: () => [
      {id: 1, role: 'user', content: `Pause ${TAILS}.`, created_at: AT},
      {id: 2, role: 'agent', content: `It has made no trades yet, so I suggest pausing it.`, created_at: AT},
      {id: 3, role: 'system', content: KEPT(TAILS), created_at: AT},
      {id: 4, role: 'system', content: 'Market focus set to btc.', created_at: AT},
    ]});
    const kinds = p.box.querySelector('#apf-messages').querySelectorAll('.say-kind').map((el) => el.textContent);
    assert.deepEqual(kinds, ['You', 'Agent', 'Autopilot’s rule: kept running', 'Market focus']);
    const own = p.box.querySelectorAll('.apf-rule');
    assert.equal(own.length, 1);
    assert.equal(own[0].textContent, 'To stop it anyway, pause it yourself on Deploy.');
    assert.match(own[0].innerHTML, /<a href="\/deploy">Deploy<\/a>/);
    // A tournament entrant the autopilot keeps is the same rule.
    const q = await panel({autopilot: true, chat: () => [{id: 5, role: 'system', created_at: AT, content:
      `I left ${TAILS} running: it is a paper tournament entrant with 3 of 20 independent events ($1.20 net of fees and spread), and the tournament retires it on its own once the data can judge it.`}]});
    assert.deepEqual(q.box.querySelector('#apf-messages').querySelectorAll('.say-kind').map((el) => el.textContent), ['Autopilot’s rule: kept running']);
  });

  test(`${name}: the engine's pause in the feed reads by the strategy's name, headed as a pause, not a review`, async () => {
    // The server says the line by name (customer_text.chat_rows); before, the feed showed "Paused deployment
    // #12 automatically. Lost $12.00, more than the $10.00 guard (...)" under "Reviewed".
    const said = `Paused your paper strategy ${TAILS} automatically: it lost $12.00, more than its $10.00 loss guard.`;
    const p = await panel({autopilot: true, chat: () => [
      {id: 1, role: 'system', content: said, created_at: AT},
      {id: 2, role: 'system', content: 'Paused one of your strategies automatically.', created_at: AT},
      {id: 3, role: 'system', content: 'Autopilot paused Rain: it hit its loss guard.', created_at: AT},
    ]});
    const feed = p.box.querySelector('#apf-messages');
    assert.deepEqual(feed.querySelectorAll('.say-kind').map((el) => el.textContent), ['Paused automatically', 'Paused automatically', 'Reviewed']);
    const html = feed.querySelectorAll('.apf-md').map((el) => el.innerHTML).join('\n');
    assert.ok(html.includes(TAILS) && html.includes('more than its $10.00 loss guard'), html);
    assert.doesNotMatch(html, /deployment #|#\d/);
  });

  // Walked 2026-10-27: changing the market focus, deploying from the Deploy page, the kill switch, the engine's
  // stop-loss sale and its daily loss stops each landed in the feed under "Reviewed", seconds after a click
  // when no review had run.
  test(`${name}: lines no review wrote are headed as what they are, not "Reviewed"`, async () => {
    const lines = [
      'Market focus set to Bitcoin.',
      'Market focus cleared.',
      'Market focus set to Bitcoin. Autopilot will research, deploy and trade only these from now on.',
      `Deployed ${TAILS} on paper.`,
      'Kill switch: live autopilot off, 1 live deployment(s) paused.',
      `Sold a NO position of your paper strategy ${TAILS} automatically: it fell 42.0% below its cost, past your 40.0% stop. The rest of the strategy keeps trading.`,
      'Live autopilot auto-disabled: today\'s live loss $51.00 hit your $50.00 daily limit. Pausing live deployments.',
      'Live trading stopped: your Kalshi account is down $60.00 today (equity $940.00), past your $50.00 daily limit. Live autopilot is off and live deployments are paused.',
      'Autopilot paused Rain: it hit its loss guard.',
    ];
    const p = await panel({autopilot: true, chat: () => lines.map((content, i) => ({id: i + 1, role: 'system', content, created_at: AT}))});
    const kinds = p.box.querySelector('#apf-messages').querySelectorAll('.say-kind').map((el) => el.textContent);
    assert.deepEqual(kinds, ['Market focus', 'Market focus', 'Market focus', 'You deployed', 'Kill switch', 'Sold automatically',
      'Live stopped', 'Live stopped', 'Reviewed']);
  });
}
