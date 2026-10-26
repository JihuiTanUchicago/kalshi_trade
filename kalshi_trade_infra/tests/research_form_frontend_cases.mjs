// Shared cases, run against each bundle's offline harness (Tau and Meridian): starting a research
// session from the Research form (walked 2026-10-26 on a phone and a desktop, in both themes).
// - The cost hint beside Start followed the model picker only for everyone's figure: once you had
//   sessions of your own it read your figure ("about $1.26 (your recent sessions)") for every model,
//   the cheapest included. It reads your own figure for the model picked (yours_by_model), else
//   everyone's for that model.
// - An error from Start (out of credits, two sessions going) landed under the cost lines, below the
//   fold on a phone: Start looked like it did nothing. It is scrolled into view.
// - A strategy count the browser refuses inside folded Options left Start doing nothing (Chrome: "An
//   invalid form control is not focusable"). Options unfold so the browser can point at it.
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
