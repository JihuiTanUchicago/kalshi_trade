// Shared cases, run against each bundle's offline harness (Tau and Meridian): starting a research
// session from the Research form (walked 2026-10-26 on a phone and a desktop, in both themes).
// - The cost hint beside Start followed the model picker only for everyone's figure: once you had
//   sessions of your own it read your figure ("about $1.26 (your recent sessions)") for every model,
//   the cheapest included. It reads your own figure for the model picked (yours_by_model), else
//   everyone's for that model.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const MODELS = {models: [{key: 'opus', label: 'Claude Opus 4.6'}, {key: 'nova', label: 'Amazon Nova Micro'}], default: 'opus'};

export function researchFormCases({name, frontend}) {
  const form = async ({estimate = {}, me = {}, runs = [], create, search = ''} = {}) => {
    const f = frontend({fetchImpl: (path, options) => {
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
}
