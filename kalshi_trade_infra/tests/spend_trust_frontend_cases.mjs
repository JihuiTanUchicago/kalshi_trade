// Shared cases, run against each bundle's offline harness (Tau and Meridian): what research costs against the
// credits a customer has, walked 2026-10-28 as a paying customer at 390px and 1280px in both themes.
// - The research form said "usually costs about $4.05" beside a $1.40 balance and nothing more: it now says the
//   usual session is more than the credits on hand, so it may stop short, and what to do first. Not said
//   while auto-reload tops the balance up, nor under the research floor (the form's own note says that).
// - A finished session's page said "Cost $3.43 from your credits" and nothing showed what the form had said
//   sessions like it usually cost: the cost now sits beside that figure, from the same estimate read.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const MODELS = {models: [{key: 'opus', label: 'Claude Opus 4.6'}, {key: 'nova', label: 'Amazon Nova Micro'}], default: 'opus'};
const AT = '2026-10-25T10:00:00Z';
const ESTIMATE = {yours: 4.05, yours_by_model: {opus: 4.05}, sessions: 4, typical: {opus: 3.9, nova: 0.03},
  per_hour: {yours: null, yours_by_model: {}, typical: {}}};

export function spendTrustCases({name, frontend}) {
  const form = async (me) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/models') return response(MODELS);
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/research/estimate') return response(ESTIMATE);
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null, v: 'v1'});
      if (path.startsWith('/api/research/scoreboard')) return response({});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, min_run_balance: 1, auto_reload: null, reload_failed: null, ...me};
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research'; f.location.search = '';
    await f.viewResearch(); await settle();
    return f;
  };
  const cost = (f) => f.root.querySelector('#rcost').textContent;
  const setForever = (f, on) => { const rf = f.root.querySelector('#runforever'); rf.checked = on; rf.dispatchEvent({type: 'change'}); };
  const pick = (f, key) => { const m = f.root.querySelector('#rmodel'); m.value = key; m.dispatchEvent({type: 'change'}); };

  test(`${name}: the research form says when a usual session costs more than the credits on hand`, async () => {
    const f = await form({credit_balance: 1.4});
    pick(f, 'opus');
    setForever(f, false);
    assert.equal(cost(f), 'A session like this usually takes about $4.05 from your credits (your recent sessions on this model). '
      + 'That’s more than the $1.40 you have, so it may stop short when your credits run out. Add credits or turn on auto-reload on Billing first.');
    setForever(f, true);
    assert.match(cost(f), /^Each round of ideas usually costs about \$4\.05 \(your recent sessions on this model\); it keeps starting new rounds until you stop it\. That’s more than the \$1\.40 you have, so it may stop in its first round when your credits run out\. Add credits or turn on auto-reload on Billing first\./);
    assert.match(cost(f), /It stops by itself if your credits run out\.$/);
    // A model whose usual session the balance covers says nothing more.
    pick(f, 'nova');
    assert.doesNotMatch(cost(f), /more than the/);
    assert.doesNotMatch(cost(f), /list price|margin/i);
    f.clearTimers();
  });

  test(`${name}: the form's short-of-credits line waits for what applies: auto-reload, a declined card, the floor`, async () => {
    // Auto-reload on and working: the card tops the balance up at its trigger, so nothing is short.
    let f = await form({credit_balance: 1.4, auto_reload: {amount: 20, threshold: 5, charge: 21.1}});
    setForever(f, false);
    assert.doesNotMatch(cost(f), /more than the/);
    f.clearTimers();
    // Auto-reload on but its card was declined: the card is the step, not "turn on auto-reload".
    f = await form({credit_balance: 1.4, auto_reload: {amount: 20, threshold: 5, charge: 21.1}, reload_failed: 'It couldn’t add $20.00 in credits.'});
    setForever(f, false);
    assert.match(cost(f), /That’s more than the \$1\.40 you have, so it may stop short when your credits run out\. Auto-reload couldn’t charge your card: update it and add credits on Billing first\.$/);
    f.clearTimers();
    // Under the research floor the form's own note says it can't start; the cost line doesn't repeat it.
    f = await form({credit_balance: 0.4});
    setForever(f, false);
    assert.doesNotMatch(cost(f), /more than the/);
    assert.match(f.root.querySelector('#rlow').textContent, /\$0\.40 in credits/);
    f.clearTimers();
    // Payments off: nothing is short.
    f = await form({credit_balance: 0, billing_enabled: false});
    setForever(f, false);
    assert.doesNotMatch(cost(f), /more than the/);
    f.clearTimers();
  });

  const run = async (over, estimate = ESTIMATE) => {
    const asked = [];
    const f = frontend({fetchImpl: (path) => {
      asked.push(path);
      if (path.startsWith('/api/runs/9')) return response({run: {id: 9, prompt: 'Mean reversion on wide spreads', market: 'btc15m',
        created_at: AT, started_at: AT, finished_at: AT, status: 'succeeded', stop_reason: 'limit', model: 'opus', run_forever: 0,
        spent_usd: 3.43, hypotheses_tried: 8, ...over}, events: [], strategies: []});
      if (path === '/api/research/estimate') return estimate instanceof Error ? response({error: 'down'}, 500) : response(estimate);
      return response({});
    }});
    await f.viewRun(9); await settle(); f.clearTimers();
    return {f, asked, figs: f.root.querySelector('#runfigs').textContent};
  };

  test(`${name}: a finished session's cost sits beside what sessions like it usually cost`, async () => {
    let {figs} = await run({});
    assert.match(figs, /Cost\s*\$3\.43\s*from your credits\s·\ssessions like it usually cost about \$4\.05/);
    // No figure of the user's own for its model: everyone's for that model, as the form reads it.
    ({figs} = await run({}, {yours: null, yours_by_model: {}, typical: {opus: 3.9}}));
    assert.match(figs, /from your credits\s·\ssessions like it usually cost about \$3\.90/);
    // Nothing to hold it against: the cost stands alone, and a failed read says nothing either.
    for (const est of [{yours_by_model: {}, typical: {}}, new Error('down')]) {
      ({figs} = await run({}, est));
      assert.match(figs, /Cost\s*\$3\.43\s*from your credits/);
      assert.doesNotMatch(figs, /usually cost/);
    }
  });

  test(`${name}: only a session that ran its set size is compared, and only once it is done`, async () => {
    for (const over of [
      {run_forever: 1, stop_reason: 'complete'},             // a run-until-stopped session has no set size
      {status: 'cancelled', stop_reason: 'user'},           // stopped by you partway
      {example: true, spent_usd: 0},                         // the free example
      {status: 'running', stop_reason: null, finished_at: null},
    ]) {
      const {figs, asked} = await run(over);
      assert.doesNotMatch(figs, /usually cost/, JSON.stringify(over));
      assert.equal(asked.includes('/api/research/estimate'), false, JSON.stringify(over));
    }
  });
}
