// Shared cases, run against each bundle's offline harness (Tau and Meridian): starting a research
// session from the Research form (walked 2026-10-26 on a phone and a desktop, in both themes).
// - The cost hint beside Start followed the model picker only for everyone's figure: once you had
//   sessions of your own it read your figure ("about $1.26 (your recent sessions)") for every model,
//   the cheapest included. It reads your own figure for the model picked (yours_by_model), else
//   everyone's for that model.
// - An error from Start (out of credits, two sessions going) landed under the cost lines, below the
//   fold on a phone: Start looked like it did nothing. It is scrolled into view.
// - Under the credits a session needs, Start's refusal repeated the form's own low-credit note in the
//   server's words (walked 2026-10-27). The note moves beside Start instead: said once.
// - A strategy count the browser refuses inside folded Options left Start doing nothing (Chrome: "An
//   invalid form control is not focusable"). Options unfold so the browser can point at it.
// - Arriving from Explore with ?market= for a market the picker doesn't offer (perpetuals off) left
//   Agent's choice picked and said nothing. It says the market isn't open for research right now.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const MODELS = {models: [{key: 'opus', label: 'Claude Opus 4.6'}, {key: 'nova', label: 'Amazon Nova Micro'}], default: 'opus'};

export function researchFormCases({name, frontend}) {
  const form = async ({estimate = {}, me = {}, runs = [], create, search = '', globals} = {}) => {
    const f = frontend({globals, fetchImpl: (path, options) => {
      if (path === '/api/models') return response(MODELS);
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/research/estimate') return response(estimate);
      if (path === '/api/runs' && options && options.method === 'POST') return create(JSON.parse(options.body));
      if (path.startsWith('/api/runs')) return response({runs, counts: {research_running: 0, research_queued: 0}, policy: null, v: 'v1'});
      if (path.startsWith('/api/research/scoreboard')) return response({});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, ...me};
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research'; f.location.search = search;
    await f.viewResearch(); await settle();
    return f;
  };
  const pick = (f, key) => { const m = f.root.querySelector('#rmodel'); m.value = key; m.dispatchEvent({type: 'change'}); };

  test(`${name}: the cost beside Start follows the model picked, your own figure only for a model you used`, async () => {
    const f = await form({me: {billing_enabled: true, credit_balance: 23.53, auto_reload: null}, estimate: {
      yours: 1.26, yours_by_model: {opus: 1.26}, sessions: 4, typical: {opus: 1.4, nova: 0.03},
      per_hour: {yours: 0.48, yours_by_model: {opus: 0.48}, typical: {nova: 0.01}}}});
    const cost = () => f.root.querySelector('#rcost').textContent;
    pick(f, 'opus');
    assert.equal(cost(), 'Each round of ideas usually costs about $1.26 (your recent sessions on this model); it keeps starting new rounds until you stop it. '
      + 'At recent rates it costs about $0.48 an hour (your recent sessions on this model). Your $23.53 covers about 2 days. It stops by itself if your credits run out.');
    // Before: the same "$1.26 (your recent sessions)" and "$0.48 an hour" beside Amazon Nova Micro.
    pick(f, 'nova');
    assert.equal(cost(), 'Each round of ideas usually costs about $0.03 (recent sessions on this model); it keeps starting new rounds until you stop it. '
      + 'At recent rates it costs about $0.01 an hour (recent sessions on this model). Your $23.53 covers about 98 days. It stops by itself if your credits run out.');
    const rf = f.root.querySelector('#runforever'); rf.checked = false; rf.dispatchEvent({type: 'change'});
    assert.equal(cost(), 'A session like this usually takes about $0.03 from your credits (recent sessions on this model).');
    pick(f, 'opus');
    assert.equal(cost(), 'A session like this usually takes about $1.26 from your credits (your recent sessions on this model).');
    assert.doesNotMatch(cost(), /list price|margin/i);
    f.clearTimers();
  });

  test(`${name}: an error from Start is brought into view, and a bad count in folded Options unfolds them`, async () => {
    const asked = [];
    const f = await form({globals: {FormData}, create: (body) => { asked.push(body); return response({error: 'You need at least $1.00 in credits to start a research session. Add credits on the Billing tab.'}, 402); }});
    const dispatch = f.root.querySelector('#dispatch'), said = f.root.querySelector('#dflash'), scrolled = [];
    said.scrollIntoView = (how) => scrolled.push(how);
    f.root.querySelector('textarea[name=prompt]').value = 'Buy YES when Bitcoin is up over the past five minutes';
    await dispatch.onsubmit({preventDefault() {}}); await settle();
    assert.equal(asked.length, 1);
    assert.match(said.innerHTML, /You need at least \$1\.00 in credits/);
    // Before: the line landed under the cost hints, below the fold on a phone, and nothing moved.
    assert.equal(JSON.stringify(scrolled), '[{"block":"nearest"}]');
    // A count the browser refuses (0, or over 1,000) while Options are folded: the browser fires "invalid"
    // and can't point at a hidden field, so Start did nothing. Options unfold for it.
    const opts = f.root.querySelector('#ropts'); opts.open = false;
    dispatch.dispatchEvent({type: 'invalid', target: f.root.querySelector('#maxhyp')});
    assert.equal(opts.open, true);
    f.clearTimers();
  });

  test(`${name}: Start refused for low credits says so once, beside Start, not again under the form's own note`, async () => {
    let refuse = {status: 402, error: 'You need at least $1.00 in credits to start a research session. Add credits on the Billing tab.'};
    const f = await form({globals: {FormData}, me: {billing_enabled: true, needs_card: false, credit_balance: 0.49, min_run_balance: 1, reload_failed: null},
      create: () => response({error: refuse.error}, refuse.status)});
    const dispatch = f.root.querySelector('#dispatch'), said = f.root.querySelector('#dflash');
    said.scrollIntoView = () => {};
    const warnings = () => dispatch.querySelectorAll('.notice').filter((n) => !n.removed && /credits/.test(n.innerHTML));
    assert.equal(warnings().length, 1);
    f.root.querySelector('textarea[name=prompt]').value = 'Buy YES when Bitcoin is up over the past five minutes';
    for (let press = 0; press < 2; press++) {
      await dispatch.onsubmit({preventDefault() {}}); await settle();
      // Before: the form's note up top and, under Start, the server's "You need at least $1.00 in credits".
      const [one] = warnings();
      assert.equal(warnings().length, 1);
      assert.ok(said.contains(one));
      assert.match(said.innerHTML, /You have \$0\.49 in credits — a research session needs at least \$1\.00 to start\. <a href="\/billing">Add credits →<\/a>/);
      assert.match(said.innerHTML, /class="notice bad" id="rlow" role="alert"/);
      assert.doesNotMatch(said.innerHTML, /on the Billing tab/);
    }
    // Refused for something else (two sessions going): the server's words, as before.
    refuse = {status: 429, error: 'You already have 2 research sessions going (paused ones count).'};
    await dispatch.onsubmit({preventDefault() {}}); await settle();
    assert.match(said.innerHTML, /You already have 2 research sessions going/);
    f.clearTimers();
  });

  // A Start Tau didn't confirm (the edge's 502 page, no reply on a train) may have started a session:
  // it said "Reload the page to check", where the sessions on this page already show it within seconds.
  test(`${name}: a Start Tau didn't confirm says where the session would show up, keeps the idea, and sends once`, async () => {
    const asked = [];
    const f = await form({globals: {FormData}, create: (body) => { asked.push(body); return {ok: false, status: 502, json: async () => { throw new SyntaxError('not JSON'); }}; }});
    const dispatch = f.root.querySelector('#dispatch'), said = f.root.querySelector('#dflash');
    said.scrollIntoView = () => {};
    const idea = f.root.querySelector('textarea[name=prompt]');
    idea.value = 'Fade the last-minute spike before a 15-minute close';
    await dispatch.onsubmit({preventDefault() {}}); await settle();
    assert.equal(asked.length, 1, 'never sent again');
    assert.match(said.innerHTML, /Tau didn’t confirm the session started\. If it did, it shows up in your sessions on this page within a few seconds; check there before you start it again\./);
    assert.doesNotMatch(said.innerHTML, /Reload the page/);
    assert.equal(idea.value, 'Fade the last-minute spike before a 15-minute close');
    f.clearTimers();
  });

  test(`${name}: arriving from Explore with a market the picker doesn't offer says so instead of quietly letting the agent choose`, async () => {
    const markets = [{key: 'btc15m', label: 'Bitcoin 15-minute', category: 'Crypto', has_data: true},
      {key: 'eth15m', label: 'Ethereum 15-minute', category: 'Crypto', has_data: true}];
    // The harness has no radio groups: the picked market is the checked row that isn't Agent's choice.
    const picked = (f) => f.root.querySelectorAll('input[name=market]').find((r) => r.checked && r.value) || {value: ''};
    const sum = (f) => f.root.querySelector('#ropts-sum').textContent;
    // A market it offers: picked, Options open, no note.
    let f = await form({me: {markets}, search: '?new=1&market=eth15m'});
    assert.equal(picked(f).value, 'eth15m');
    assert.equal(f.root.querySelector('#ropts').open, true);
    assert.equal(f.root.querySelector('.mkt-missing'), null);
    f.clearTimers();
    // Before: Agent's choice stayed picked and nothing said the perpetual wasn't there.
    f = await form({me: {markets}, search: '?new=1&market=btc_perp'});
    assert.equal(picked(f).value, '');
    assert.equal(f.root.querySelector('#ropts').open, true);
    assert.equal(f.root.querySelector('.mkt-missing').textContent,
      'BTC perpetual, no expiry isn’t open for research right now, so the agent picks the market unless you choose one here.');
    assert.match(sum(f), /agent’s choice of market \(BTC perpetual, no expiry isn’t open for research right now\)$/);
    f.clearTimers();
    // A key it doesn't know is never shown as typed.
    f = await form({me: {markets}, search: '?new=1&market=KXFOO%3Cb%3E'});
    assert.equal(f.root.querySelector('.mkt-missing').textContent,
      'The market you picked isn’t open for research right now, so the agent picks the market unless you choose one here.');
    assert.doesNotMatch(f.root.querySelector('#dispatch').innerHTML, /KXFOO/);
    f.clearTimers();
  });

  test(`${name}: models you can't pick yet come last as "coming soon", and the demo link never reads as a fragment`, async () => {
    const run = (over) => ({id: 1, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea',
      hypotheses_tried: 9, strategies_passed: 1, spent_usd: 4.2, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit', ...over});
    const models = {models: [{key: 'next', label: 'Claude Opus 5.5', available: false}, ...MODELS.models], default: 'opus'};
    let f = await form({me: {models}});
    const labels = f.root.querySelector('#rmodel').options.map((o) => o.textContent);
    // Before: "Claude Opus 5.5 (access pending)" led the list, above the default.
    assert.deepEqual(labels, ['Claude Opus 4.6', 'Amazon Nova Micro', 'Claude Opus 5.5 (coming soon)']);
    assert.ok('disabled' in f.root.querySelector('#rmodel').options[2].attributes);
    assert.doesNotMatch(f.root.querySelector('#dispatch').innerHTML, /access pending/);
    // No example session to open: the demo link is hidden, and its partner said "or run it yourself" alone.
    const ex = () => f.root.querySelector('button[data-ex]').textContent;
    assert.equal(f.root.querySelector('[data-ex-open]').hidden, true);
    assert.equal(ex(), 'Run the demo idea yourself');
    f.clearTimers();
    // With the demo link showing (an example and sessions of your own), the pair reads as one line.
    f = await form({me: {models}, runs: [run({id: 4, seq: 1}), run({id: 3, example: true, direction: 'random_walk'})]});
    assert.equal(f.root.querySelector('[data-ex-open]').hidden, false);
    assert.equal(ex(), 'or run it yourself');
    f.clearTimers();
  });
}

// What the browser's FormData reads off the form, for the offline harness: the checked radio and
// checkbox, else each named field's value.
class FormData {
  constructor(form) { this.form = form; }
  get(name) {
    const el = this.form.querySelectorAll(`[name=${name}]`).find((e) => !['radio', 'checkbox'].includes(e.attributes.type) || e.checked);
    return !el ? null : el.attributes.type === 'checkbox' ? 'on' : el.value;
  }
}
