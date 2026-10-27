// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian), for three
// things a new user caught the pages disagreeing on:
// - one credits charge reads the same cents everywhere: half up from its decimal, as Billing rounds
//   (0.105 is 0.10499999… as a float, so toFixed(2) and Python's round() said $0.10 beside $0.11);
// - a session silent past the reaper's limit, which the counts leave out of Running, says Silent, not
//   Researching beside "Running 0";
// - a session that ended with no strategy to list says why it stopped, not "each strategy below".
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const run = (over) => ({id: 1, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea',
  hypotheses_tried: 9, strategies_passed: 0, spent_usd: 4.2, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit', ...over});
const billing = (o) => ({balance: 19.885, spent: 0.12, spent_7d: 0.12, spent_24h: 0.12, spent_7d_by: {autopilot_research: 0.12},
  runway_days: null, free_bonus: 20, cards: [], configured: false, topup_fee_pct: 5, autoreload_amount: 20, autoreload_threshold: 5,
  min_reload_amount: 5, min_reload_threshold: 1, min_topup: 5, max_topup: 1000, ledger: [], ...o});

export function trustGlitchCases({name, frontend}) {
  const research = (runs, counts) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/runs') return response({runs, counts: {research_running: 0, research_queued: 0, research_paused: 0, ...counts}, policy: null, totals: {tried: 9, passed: 0}});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    return f;
  };
  const listed = (f) => ['#runs', '#active-research'].map((s) => (f.root.querySelector(s) || {}).innerHTML || '').join('');

  test(`${name}: one charge reads the same cents on Billing, the research list and the autopilot panel`, async () => {
    // Billing: a line is the ledger's exact amount, and a day's sum adds the lines in the ledger's six
    // places. As floats, 0.114993 + 0.000007 is 0.11499999999999999, which read $0.11 beside $0.12.
    const f = frontend({fetchImpl: () => response(billing({math: {days: 30, start: 0, bought: 0, purchases: 0, other: 20, usage: 0.12, end: 19.89},
      ledger: [{kind: 'usage', item: 'Autopilot research', model: 'Claude Opus 4.6', amount: -0.114993, calls: 3, day: '2026-10-25', created_at: '2026-10-25T09:00:00Z'},
        {kind: 'usage', item: 'Autopilot research', model: 'Claude Opus 4.6', amount: -0.000007, calls: 1, day: '2026-10-25', created_at: '2026-10-25T07:00:00Z'},
        {kind: 'usage', item: 'Research session', model: 'Claude Opus 4.6', amount: -0.105, calls: 2, day: '2026-10-24', created_at: '2026-10-24T09:00:00Z'}]}))});
    await f.viewBilling(); await settle();
    const page = f.root.querySelector('#main').innerHTML;
    assert.deepEqual([...page.matchAll(/(\$[\d.]+) used/g)].map((m) => m[1]), ['$0.12', '$0.11']);  // Oct 25, Oct 24
    assert.match(page, /−\$0\.11/);  // the $0.105 line, half up
    assert.match(page, /−\$0\.000/);  // a charge under half a cent still shows three places
    assert.match(page, /<dt>Agent usage<\/dt><dd>−\$0\.12<\/dd>/);
    // The research list and the run page: a session's cost, half up from what the server sent.
    for (const [spent, said] of [[0.105, '$0.11'], [1.005, '$1.01'], [0.104999, '$0.10'], [0.11, '$0.11']]) {
      assert.ok(f.runRow(run({spent_usd: spent})).includes(`Cost: ${said}`), String(spent));
    }
    // The autopilot panel's research line said "$" + toFixed(2): $0.10 for the same $0.105.
    const box = f.document.createElement('div');
    box.innerHTML = '<dl id="apf-stats"></dl>';
    f.apUpdate(box, {autopilot: false, research: {active: [], tested_7d: 3, passed_7d: 0, cost_7d: 0.105}, story: []});
    const stats = box.querySelector('#apf-stats').innerHTML;
    assert.match(stats, /3 ideas tested this week, 0 passed, \$0\.11 spent/);
    assert.doesNotMatch(stats, /\$0\.10/);
    assert.doesNotMatch(stats, /not cleared/);
    // passed_7d counts only passes cleared to trade; the ones a later check left uncleared are said apart.
    f.apUpdate(box, {autopilot: false, research: {active: [], tested_7d: 3, passed_7d: 1, not_cleared_7d: 2, cost_7d: 0.105}, story: []});
    assert.match(box.querySelector('#apf-stats').innerHTML, /3 ideas tested this week, 1 passed, 2 not cleared, \$0\.11 spent/);
    // The panel's last 7 days says the same.
    box.innerHTML = '<dl id="apf-stats"></dl><div id="apf-week"></div>';
    const week = {research_credits: 0.11, tested: 3, passed: 1, not_cleared: 2, paper_started: 0, paper_pnl: 0, paper_trades: 0};
    f.apUpdate(box, {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 3, passed_7d: 1, not_cleared_7d: 2, cost_7d: 0.105}, week, story: []});
    assert.match(box.querySelector('#apf-week').innerHTML, /<dt>Ideas<\/dt><dd>3 tested · 1 passed, 2 not cleared<\/dd>/);
    f.apUpdate(box, {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 3, passed_7d: 1, cost_7d: 0.105}, week: {...week, not_cleared: 0}, story: []});
    assert.doesNotMatch(box.querySelector('#apf-week').innerHTML, /not cleared/);
    f.clearTimers();
  });

  test(`${name}: a session gone silent past the reaper's limit says Silent beside "Running 0", not Researching`, async () => {
    const silent = run({id: 10, status: 'running', stop_reason: null, spent_usd: 0.5, started_at: '2026-10-25T08:00:00Z',
      wait: {state: 'silent', seconds: 1500, overdue: true}});
    let f = research([silent, run({id: 3})], {research_running: 0});
    await f.viewResearch(); await settle();
    let html = listed(f);
    assert.match(html, /Silent 25 min/);
    assert.doesNotMatch(html, /Researching/);
    f.clearTimers();
    // One that is beating is counted and says Researching; a queued one past the limit says how long it has waited.
    f = research([run({id: 11, status: 'running', stop_reason: null, wait: null}), run({id: 12, status: 'queued', stop_reason: null,
      wait: {state: 'queued', seconds: 4000, overdue: true}})], {research_running: 1, research_queued: 1});
    await f.viewResearch(); await settle();
    html = listed(f);
    assert.match(html, /Researching/);
    assert.match(html, /Waiting 66 min/);
    assert.doesNotMatch(html, /Silent/);
    f.clearTimers();
    // The row's own words, from the server's wait, whichever row it is.
    assert.match(f.runRow(silent), /Silent 25 min/);
    assert.doesNotMatch(f.runRow({...silent, wait: {state: 'silent', seconds: 1500, overdue: false}}), /Silent/);
  });

  test(`${name}: a session that ended with no strategy says why it stopped, not "each strategy below"`, async () => {
    const at = async (r, strategies = [], events = []) => {
      const f = frontend({fetchImpl: () => response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: '2026-10-25T10:00:00Z', ...r}, events, strategies})});
      await f.viewRun(9); f.clearTimers();
      return f.root.querySelector('#runnext').innerHTML;
    };
    for (const [r, said] of [
      [{status: 'stopped', stop_reason: 'interrupted', error: 'Explored 0 hypotheses, then the session was interrupted and stopped.'}, /It was interrupted before any strategy reached the checks, and it couldn’t be resumed\./],
      [{status: 'stopped', stop_reason: 'no_data', error: 'This market has no settled <b>contracts</b> to research yet.'}, /This market has no settled &lt;b&gt;contracts&lt;\/b&gt; to research yet\./],
      [{status: 'stopped', stop_reason: 'no_data'}, /This market has nothing to research yet, so the session stopped before testing anything\./],
      [{status: 'succeeded', stop_reason: 'complete', run_forever: 1}, /It ran out of new ideas to try before any strategy reached the checks\./],
      [{status: 'succeeded', stop_reason: 'limit'}, /No strategy from this session reached the checks, so there are none to list\./],
      [{status: 'succeeded'}, /This session ended before any strategy reached the checks\./],  // an older server
    ]) {
      const next = await at(r);
      assert.match(next, said, JSON.stringify(r));
      assert.match(next, /<a href="\/research\?new=1">Try another idea<\/a>/);
      assert.doesNotMatch(next, /below|which check it missed/, JSON.stringify(r));
    }
    // Out of credits with nothing listed: the credits line, and no list to point at.
    const credits = await at({status: 'succeeded', run_forever: 1, stop_reason: 'complete'}, [],
      [{id: 7, kind: 'step', message: 'Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching.', created_at: '2026-10-25T11:00:00Z'}]);
    assert.match(credits, /It stopped when your credits ran out\. <a href="\/billing">Add credits<\/a>, then start a new session to keep researching\. No strategy reached the checks before then\./);
    assert.doesNotMatch(credits, /below/);
    // With strategies to list, the line still points at them.
    assert.match(await at({status: 'stopped', stop_reason: 'interrupted'}, [{id: 43, title: 'Fade', status: 'rejected'}]), /which check it missed/);
  });
}
