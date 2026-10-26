// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the research
// session page (/research/:id) says how a session ended in the research list's words, names its count
// once ("Tested") and says why the list under it holds fewer, shows the example as free, prints the agent's
// step lines in the server's plain words, and calls the challenger the skeptic's review.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const AT = '2026-10-25T10:00:00Z';
const ev = (id, kind, message, data = {}) => ({id, kind, message, data, created_at: AT});

export function runPageCases({name, frontend}) {
  const open = async (run, events = [], strategies = []) => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9')
      ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: AT, started_at: AT, ...run}, events, strategies})
      : response({})});
    await f.viewRun(9); f.clearTimers();
    return f;
  };
  const figs = (f) => f.root.querySelector('#runfigs').textContent;
  // Tau lists the ideas under #runideas, Meridian its strategy table under #run-artifacts.
  const list = (f) => (f.root.querySelector('#runideas') || f.root.querySelector('#run-artifacts')).innerHTML;
  const badge = (f) => f.root.querySelector('#rsiobs [data-livetext]').textContent;

  test(`${name}: a finished session's status and loop badge say why it stopped, in the research list's words`, async () => {
    for (const [run, said] of [
      [{status: 'succeeded', stop_reason: 'limit'}, 'Finished'],
      [{status: 'succeeded', run_forever: 1, stop_reason: 'complete'}, 'Finished'],
      [{status: 'cancelled', stop_reason: 'user'}, 'Stopped by you'],
      [{status: 'failed', stop_reason: 'error'}, 'Stopped on an error'],
      [{status: 'stopped', stop_reason: 'interrupted', error: 'Interrupted: the worker stopped.'}, 'Interrupted'],
      [{status: 'stopped', stop_reason: 'no_data'}, 'Nothing to research'],
      [{status: 'succeeded'}, 'Finished'],  // an older server without stop_reason
    ]) {
      const f = await open(run);
      assert.match(figs(f), new RegExp(said), JSON.stringify(run));
      assert.doesNotMatch(figs(f), /\bDone\b|Cancelled|Failed/, JSON.stringify(run));
      assert.equal(badge(f), said, JSON.stringify(run));
    }
    // Out of credits comes from the log's step, on the figure and the badge alike.
    const f = await open({status: 'succeeded', run_forever: 1, stop_reason: 'complete'},
      [ev(1, 'step', 'Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching.')]);
    assert.match(figs(f), /Out of credits/); assert.equal(badge(f), 'Out of credits');
  });

  test(`${name}: the count is "Tested", and the list under it says why it holds fewer`, async () => {
    const hyp = (id) => ev(id, 'hypothesis', 'Idea ' + id);
    const rows = [{id: 42, title: 'Late', status: 'failed', market: 'btc15m', direction: 'momentum'},
      {id: 43, title: 'Fade', status: 'rejected', market: 'btc15m', direction: 'momentum'}];
    let f = await open({status: 'succeeded', hypotheses_tried: 3, strategies_passed: 0}, [1, 2, 3].map(hyp), rows);
    assert.match(figs(f), /Tested\s*3/); assert.doesNotMatch(figs(f), /Hypotheses/);
    assert.match(list(f), /1 more (idea )?dropped before testing/);
    f = await open({status: 'running', max_hypotheses: 6, hypotheses_tried: 1}, [1, 2, 3, 4].map(hyp), rows);
    assert.match(list(f), /2 more (ideas )?still being tested/);
    f = await open({status: 'succeeded', hypotheses_tried: 2}, [1, 2].map(hyp), rows);
    assert.doesNotMatch(list(f), /dropped before testing|still being tested/);
  });

  test(`${name}: the example's cost says it was free, not "from your credits"`, async () => {
    let f = await open({status: 'succeeded', example: true, spent_usd: 0});
    assert.match(figs(f), /\$0\.00\s*free: Tau ran it for you/); assert.doesNotMatch(figs(f), /from your credits/);
    f = await open({status: 'succeeded', spent_usd: 1.84});
    assert.match(figs(f), /\$1\.84\s*from your credits/);
  });

  test(`${name}: a step line shows the server's plain words, and the challenger reads as the skeptic's review`, async () => {
    const plan = 'Plan: explore up to 6 hypotheses, refining each round on the in-sample results, then gate the best on data never seen.';
    const f = await open({status: 'succeeded'}, [
      ev(1, 'step', plan, {note: 'Plan: try up to 6 ideas, sharpen each one on past data, then test the best on data it hasn’t seen.'}),
      ev(2, 'step', 'Loaded 30 days of **Bitcoin** history.'),
      ev(3, 'hypothesis', 'Momentum', {thesis: 't'}),
      ev(4, 'challenger', 'Challenger approved - Momentum: plausible', {title: 'Momentum', decision: 'approve'}),
      ev(5, 'challenger', 'Challenger revised - Other: tighten it', {title: 'Other', decision: 'revise'}),
      ev(6, 'done', '1 of 2 hypotheses passed every gate.', {note: '1 of 2 ideas passed every check.'}),
    ]);
    const log = [...f.root.querySelector('#log').children].map((li) => li.innerHTML).join('\n');
    assert.match(log, /Plan: try up to 6 ideas/); assert.doesNotMatch(log, /in-sample|gate the best/);
    assert.match(log, /<b>Bitcoin<\/b>/);  // a step without a note keeps its own (markdown) words
    assert.match(log, /1 of 2 ideas passed every check\./); assert.doesNotMatch(log, /passed every gate/);
    assert.match(f.root.querySelector('#log').querySelector('[data-review]').innerHTML, /Skeptic’s review · approved<\/span>plausible/);
    assert.match(log, /Skeptic’s review<\/span>revised - Other: tighten it/);
    assert.doesNotMatch(log, />Challenger/);
  });
}
