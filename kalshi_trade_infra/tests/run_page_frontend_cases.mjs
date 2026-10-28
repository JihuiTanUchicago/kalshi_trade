// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the research
// session page (/research/:id) says how a session ended in the research list's words, names its count
// once ("Tested") and says why the list under it holds fewer, shows the example as free, prints the agent's
// step lines in the server's plain words, and calls the challenger the skeptic's review. Its Time leaves out
// the pauses, a silent session's sentence is said once, the loop's phase line moves past a verdict, the
// research system's explainer is one folded line (no "How it searches" figure), and a void or rejected
// strategy's backtest P&L is muted and says it did not pass.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const AT = '2026-10-25T10:00:00Z';
const ev = (id, kind, message, data = {}) => ({id, kind, message, data, created_at: AT});
// The bundles' separator (SEP in app.js and app.meridian.js; test_separator_line_start.mjs).
const SEP = ' · ';
// A strategy row's Backtest P&L line: the full sentence (its hover, and what a screen reader says) and a phone's short form.
const btLine = (html) => {
  const m = html.match(/<div class="sub-fig bt-sub" title="([^"]*)"><span class="bt-long">([^<]*)<\/span><span class="bt-short" aria-hidden="true">([^<]*)<\/span><\/div>/);
  return m ? {title: m[1], long: m[2], short: m[3]} : null;
};

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

  test(`${name}: a session the server titles is named by that title, not its prompt to the agent`, async () => {
    const floor = 'Research floor: no research started for a while, so pick the most promising angle.';
    let f = await open({status: 'succeeded', brief: 1, by_autopilot: 1, prompt: floor, title: 'New idea picked by the autopilot for Bitcoin 15-minute'});
    const head = f.root.querySelector('#runboard').innerHTML;
    assert.match(head, /New idea picked by the autopilot for Bitcoin 15-minute/); assert.doesNotMatch(head, /Research floor/);
    f = await open({status: 'succeeded', prompt: 'Fade late YES takers', title: null});
    assert.match(f.root.querySelector('#runboard').innerHTML, /Fade late YES takers/);
  });

  test(`${name}: an idea that passed validation and then missed the final holdout says so, not "deploy it"`, async () => {
    const later = [{gate: 'significance', label: 'The edge could be luck on the locked holdout', measured: 'p 0.48', needed: '0.10', next: 'Try a simpler version.'}];
    const fell = {id: 42, title: 'Cheap NO after a spike', status: 'passed', verdict: 'missed_final', market: 'btc15m', direction: 'custom', later_missed: later};
    let f = await open({status: 'succeeded', hypotheses_tried: 1, strategies_passed: 1}, [], [fell]);
    const next = f.root.querySelector('#runnext').innerHTML;
    assert.match(next, /Cheap NO after a spike<\/a> passed its first test on unseen data, then missed the one-time final test \(the edge could be luck on the locked holdout\)\./);
    assert.match(next, /Nothing cleared every check this time\./);
    assert.doesNotMatch(next, /deploy it on paper|Passed:/);
    assert.match(list(f), /the edge could be luck on the locked holdout/i);
    assert.doesNotMatch(list(f), /Open it to deploy on paper/);
    // Beside a strategy that cleared everything, the passed one leads and the other is said after it.
    const ok = {id: 43, title: 'Far-strike fade', status: 'passed', market: 'btc_daily', direction: 'custom'};
    f = await open({status: 'succeeded', hypotheses_tried: 2, strategies_passed: 2}, [], [fell, ok]);
    assert.match(f.root.querySelector('#runnext').innerHTML, /^<p class="run-next">Passed: <a href="\/strategies\/43">Far-strike fade<\/a>\. Open it to deploy it on paper\. <a href="\/strategies\/42">/);
  });

  test(`${name}: an idea the diversification check held back says it was held back and why, not "deploy it"`, async () => {
    const why = [{gate: 'diversification', label: 'Too similar to “Late fade”', measured: 'a 0.93 correlation of daily results with “Late fade”', needed: '0.80 or less', next: 'Point it elsewhere.'}];
    const held = {id: 44, title: 'Late fade, tighter', status: 'passed', verdict: 'held_back', market: 'btc15m', direction: 'custom', later_missed: why};
    let f = await open({status: 'succeeded', hypotheses_tried: 1, strategies_passed: 1}, [], [held]);
    const next = f.root.querySelector('#runnext').innerHTML;
    assert.match(next, /Late fade, tighter<\/a> was held back after passing its tests: too similar to “Late fade”, so it isn’t cleared to trade\./);
    assert.match(next, /Nothing cleared every check this time\./);
    assert.doesNotMatch(next, /deploy it on paper|Passed:|final test/);
    assert.match(list(f), /Held back/); assert.match(list(f), /too similar to “Late fade”/i);
    assert.doesNotMatch(list(f), /Open it to deploy on paper|>Passed</);
    // Beside a true pass: the pass leads, the held-back one is said after it. An older server's held-back
    // idea without its line still says it was held back, in the check's own words.
    const ok = {id: 43, title: 'Far-strike fade', status: 'passed', market: 'btc_daily', direction: 'custom'};
    f = await open({status: 'succeeded', hypotheses_tried: 2, strategies_passed: 2}, [], [{...held, later_missed: undefined}, ok]);
    const both = f.root.querySelector('#runnext').innerHTML;
    assert.match(both, /^<p class="run-next">Passed: <a href="\/strategies\/43">Far-strike fade<\/a>\. Open it to deploy it on paper\. <a href="\/strategies\/44">/);
    assert.match(both, /was held back after passing its tests: too similar to a strategy you already run/);
    // A probation idea held back after passing on paper is stamped Held back, not Void.
    f = await open({status: 'succeeded', hypotheses_tried: 1, strategies_passed: 0}, [], [{...held, status: 'failed'}]);
    assert.match(list(f), /Held back/); assert.doesNotMatch(list(f), />Void</);
    assert.match(f.root.querySelector('#runnext').innerHTML, /was held back after passing its tests/);
  });

  test(`${name}: the Passed figure counts what cleared, and says how many passes a later check left uncleared`, async () => {
    const fell = {id: 42, title: 'Cheap NO after a spike', status: 'passed', verdict: 'missed_final', market: 'btc15m', direction: 'custom'};
    const held = {id: 44, title: 'Late fade, tighter', status: 'passed', verdict: 'held_back', market: 'btc15m', direction: 'custom'};
    const ok = {id: 43, title: 'Far-strike fade', status: 'passed', market: 'btc_daily', direction: 'custom'};
    const passedFig = (f) => f.root.querySelector('#runfigs').innerHTML.match(/<dt class="lab">Passed<\/dt><dd>(.*?)<\/div>/)[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
    // Finished: the run's counter (3) less the two not cleared, as its ideas below are stamped.
    let f = await open({status: 'succeeded', hypotheses_tried: 5, strategies_passed: 3}, [], [fell, held, ok]);
    assert.equal(passedFig(f), '1 2 not cleared');
    assert.match(f.root.querySelector('#runnext').innerHTML, /^<p class="run-next">Passed: <a href="\/strategies\/43">/);
    // Running: counted from its strategy rows, the same way.
    f = await open({status: 'running', hypotheses_tried: 5}, [], [fell, ok]);
    assert.equal(passedFig(f), '1 1 not cleared');
    // Nothing uncleared: the figure stands alone. A probation idea held back on paper never counted as passed.
    f = await open({status: 'succeeded', hypotheses_tried: 2, strategies_passed: 1}, [], [ok, {...held, status: 'failed'}]);
    assert.equal(passedFig(f), '1');
    f = await open({status: 'succeeded', hypotheses_tried: 2, strategies_passed: 2}, [], [fell, held]);
    assert.equal(passedFig(f), '0 2 not cleared');
  });

  test(`${name}: a finished autopilot session says what the autopilot does next, while the switch is on`, async () => {
    const at = async (apOn, run, strategies = [], events = []) => {
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9')
        ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: AT, started_at: AT, ...run}, events, strategies})
        : response({})});
      f.S.me.user.autopilot = apOn;
      await f.viewRun(9); f.clearTimers();
      return f;
    };
    const said = /The autopilot takes these results into its next ideas and starts its next session on its own\./;
    const missed = [{id: 42, title: 'Late fade', status: 'failed', market: 'btc15m', direction: 'custom'}];
    for (const run of [{status: 'succeeded', stop_reason: 'limit'}, {status: 'failed', stop_reason: 'error', error: 'The research model couldn’t be reached just now, so the session stopped.'}]) {
      const f = await at(true, {...run, by_autopilot: 1}, missed);
      const next = f.root.querySelector('#runnext').innerHTML;
      assert.match(next, said, run.status); assert.match(next, /<span data-ap-next>/, run.status);
      // The switch flips off while the page is open: the line hides, as the research nudge does.
      f.S.ap = {autopilot: false, mode: 'off'}; f.paintDashAp();
      const span = f.root.querySelector('[data-ap-next]');
      assert.ok(span, 'the line is found'); assert.equal(span.hidden, true);
    }
    // Off when the page opened: drawn hidden. A session the user started never says it.
    let f = await at(false, {status: 'succeeded', stop_reason: 'limit', by_autopilot: 1}, missed);
    assert.match(f.root.querySelector('#runnext').innerHTML, /<span data-ap-next hidden>/);
    f = await at(true, {status: 'succeeded', stop_reason: 'limit', by_autopilot: 0}, missed);
    assert.doesNotMatch(f.root.querySelector('#runnext').innerHTML, said);
    // Out of credits: the autopilot can't start another, so the line stays off.
    f = await at(true, {status: 'succeeded', run_forever: 1, stop_reason: 'complete', by_autopilot: 1}, missed,
      [ev(1, 'step', 'Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching.')]);
    assert.match(f.root.querySelector('#runnext').innerHTML, /It stopped when your credits ran out/);
    assert.doesNotMatch(f.root.querySelector('#runnext').innerHTML, said);
  });

  test(`${name}: a verdict's figures lead with the average per trade after fees, and name the gate's 90% range`, async () => {
    const stats = {n_trades: 132, mean_net_return: 0.031, p_value: 0.012, ci: {lo: 0.006, hi: 0.058}};
    const f = await open({status: 'succeeded', stop_reason: 'limit'}, [ev(1, 'hypothesis', 'Idea'),
      ev(2, 'verdict', 'PASSED - Idea: validation verdict is gatekeeper-held', {title: 'Idea', status: 'passed', strategy_id: 42, stats})]);
    const log = f.root.querySelector('#log').querySelector('[data-review]').innerHTML;
    assert.match(log, /<dt>Trades<\/dt><dd>132<\/dd><\/div><div><dt>Avg per trade after fees<\/dt><dd>\+3\.1%<\/dd>/);
    assert.match(log, /<dt>Likely average per trade \(90% <span class="nobr">range\)<button[^>]*data-glo="range90"[^]*?<\/dt><dd>0\.6%…5\.8%<\/dd>/);
    assert.doesNotMatch(log, /95% CI/);
  });

  test(`${name}: a verdict's figures are named in plain words, each saying what it measures in a bubble and, on a phone, under it`, async () => {
    const stats = {n_trades: 48, mean_net_return: 0.05, p_value: 0.0042, dsr: 0.97, sharpe: 0.31, ci: {lo: 0.012, hi: 0.094},
      placebo_p: 0.011, max_drawdown: 3.4};
    const f = await open({status: 'succeeded', stop_reason: 'limit'}, [ev(1, 'hypothesis', 'Idea'),
      ev(2, 'verdict', 'PASSED - Idea: validation verdict is gatekeeper-held', {title: 'Idea', status: 'passed', strategy_id: 42, stats})]);
    const grid = f.root.querySelector('#log').querySelector('[data-review]').innerHTML;
    const cells = [...grid.matchAll(/<div><dt>([^]*?)<\/dt><dd>([^<]*)<\/dd>(?:<dd class="hx-why">([^<]*)<\/dd>)?<\/div>/g)]
      .map(([, dt, dd, why]) => [dt.replace(/<button[^]*?<\/button>|<\/?span[^>]*>/g, ''), dd, why || '']);
    // The same figures as before, in the same order; only their names and explanations are new.
    assert.deepEqual(cells.map(([dt, dd]) => [dt, dd]), [
      ['Trades', '48'], ['Avg per trade after fees', '+5.0%'], ['Chance it’s luck (p-value)', '0.004'],
      ['Edge after correcting for many tries (DSR)', '0.97'], ['Steadiness per trade (Sharpe)', '0.31'],
      ['Likely average per trade (90% range)', '1.2%…9.4%'], ['Same test on shuffled outcomes (placebo)', '0.011'],
      ['Worst drop (max drawdown)', '−$3.40']]);
    // Every term of art carries one line saying what it measures, and an info bubble with the same words.
    for (const [dt, , why] of cells.slice(2)) assert.ok(why.length > 40 && /\.$/.test(why), dt);
    assert.equal((grid.match(/<button type="button" class="info" data-glo="(pvalue|dsr|sharpe|range90|placebo|drawdown)"/g) || []).length, 6);
    assert.doesNotMatch(grid, /<dt>(p-value|DSR|Sharpe|Placebo p|Max drawdown|90% range)<\/dt>/);
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
    assert.match(f.root.querySelector('#log').querySelector('[data-review]').innerHTML, /Skeptic’s review · approved<\/span>Plausible/);
    assert.match(log, /Skeptic’s review<\/span>revised - Other: tighten it/);
    assert.doesNotMatch(log, />Challenger/);
  });

  // Walked 2026-10-28: with its stamp and title cut off, the example session's verdict read "no edge, so nothing to
  // deploy." under "Verdict · rejected", and a skeptic's review began "the overshoot has…". Each is its own sentence.
  // Walked 2026-10-28: a cancelled session's status read "Stopped by you" and the line under it "This session was
  // cancelled before it finished."
  test(`${name}: a session you stopped says so in the status's words, not "cancelled"`, async () => {
    const f = await open({status: 'cancelled', stop_reason: 'user'}, [], [{id: 43, title: 'Fade', status: 'rejected', market: 'btc15m', direction: 'momentum'}]);
    assert.match(figs(f), /Stopped by you/);
    const next = f.root.querySelector('.run-next').innerHTML;
    assert.match(next, /^You stopped this session before it finished\. The ideas it tested are listed below\./);
    assert.doesNotMatch(next, /cancel/i);
  });

  test(`${name}: a verdict's and a skeptic's words on an idea's card start as a sentence`, async () => {
    const f = await open({status: 'succeeded'}, [
      ev(1, 'hypothesis', 'Todd’s walk', {thesis: 't'}),
      ev(2, 'challenger', 'Challenger approved - Todd’s walk: the overshoot has a plausible mechanism', {title: 'Todd’s walk', decision: 'approve'}),
      ev(3, 'verdict', 'VOID — Todd’s walk: no edge, so nothing to deploy.', {title: 'Todd’s walk', status: 'rejected'}),
    ]);
    const review = f.root.querySelector('#log').querySelector('[data-review]').innerHTML;
    assert.match(review, /<\/span>The overshoot has a plausible mechanism<\/p>/);
    assert.match(review, /No edge, so nothing to deploy\./);
    assert.doesNotMatch(review, />no edge|>the overshoot/);
  });

  test(`${name}: Time leaves out the pauses the log records, and stops while the session is paused`, async () => {
    const ago = (min) => new Date(Date.now() - min * 60000).toISOString();
    const at = (id, kind, min) => ({id, kind, message: kind, data: {}, created_at: ago(min)});
    const time = (f) => f.root.querySelectorAll('#runfigs .m').find((m) => m.querySelector('dt').textContent === 'Time').textContent;
    // Started 90 min ago, paused 60 min ago and still paused: 30 min, not 2 hr.
    let f = await open({status: 'paused', started_at: ago(90)}, [at(1, 'step', 89), at(2, 'paused', 60)]);
    assert.match(time(f), /^Time30 minnot counting time paused$/);
    // Paused before the worker logged it: the clock stops at its last line.
    f = await open({status: 'paused', started_at: ago(90)}, [at(1, 'step', 89), at(2, 'step', 50)]);
    assert.match(time(f), /^Time40 min$/);
    // Paused for 40 min, resumed and running: the pause is left out.
    f = await open({status: 'running', started_at: ago(70)}, [at(1, 'step', 69), at(2, 'paused', 60), at(3, 'resumed', 20), at(4, 'step', 1)]);
    assert.match(time(f), /^Time30 minnot counting time paused$/);
    // Cancelled while paused: the open pause up to the end is left out.
    f = await open({status: 'cancelled', started_at: ago(60), finished_at: ago(10)}, [at(1, 'step', 59), at(2, 'paused', 50)]);
    assert.match(time(f), /^Time10 minnot counting time paused$/);
    // Never paused: the wall clock, with no note.
    f = await open({status: 'succeeded', started_at: ago(60), finished_at: ago(15)}, [at(1, 'step', 59)]);
    assert.match(time(f), /^Time45 min$/);
  });

  test(`${name}: a silent session says "No word from the agent" once, in the loop panel, in place of its last phase`, async () => {
    const f = await open({status: 'running', wait: {state: 'silent', seconds: 1500, overdue: true}},
      [ev(1, 'step', 'Loading data…'), ev(2, 'verdict', 'VOID - Idea', {title: 'Idea', status: 'failed'})]);
    const shown = ['#runfigs', '#runnext', '#rsiobs [data-livetext]', '#rsiobs [data-phase]', '#rsiobs [data-wait]', '#runpulse', '#log']
      .map((sel) => f.root.querySelector(sel)).filter((el) => el && !el.hidden).map((el) => el.textContent).join('\n');
    assert.equal(shown.split('No word from the agent for 25 min.').length - 1, 1, shown);
    assert.equal(f.root.querySelector('#rsiobs [data-wait]').hidden, false);
    assert.equal(f.root.querySelector('#rsiobs [data-phase]').hidden, true);
  });

  test(`${name}: the loop's phase line moves past a verdict, and an ended session's is hidden behind the badge`, async () => {
    const phase = (f) => f.root.querySelector('#rsiobs [data-phase]');
    const verdict = ev(3, 'verdict', 'VOID - Idea', {title: 'Idea', status: 'failed'});
    let f = await open({status: 'running'}, [ev(1, 'hypothesis', 'Idea'), verdict]);
    assert.equal(phase(f).textContent, 'Verdict in, on to the next step'); assert.equal(phase(f).hidden, false);
    // A verdict with no idea is a note on the session (the data scan), not "Recording the verdict".
    f = await open({status: 'running'}, [ev(1, 'hypothesis', 'Idea'), ev(2, 'verdict', 'Lead scan: control arm, hypotheses first.', {phase: 'leads'})]);
    assert.doesNotMatch(phase(f).textContent, /verdict/i);
    f = await open({status: 'running'}, [verdict, ev(4, 'paused', 'Paused.'), ev(5, 'resumed', 'Resumed.')]);
    assert.equal(phase(f).textContent, 'Back at work');
    f = await open({status: 'running'}, [verdict, ev(4, 'done', '0 of 1 passed.')]);
    assert.equal(phase(f).textContent, 'Wrapping up');
    f = await open({status: 'succeeded', stop_reason: 'limit'}, [verdict, ev(4, 'done', '0 of 1 passed.')]);
    assert.equal(phase(f).hidden, true); assert.equal(badge(f), 'Finished');
  });

  test(`${name}: the research system's explainer is one folded "How research works" line, not a figure on every session`, async () => {
    const at = (status, rsi) => frontend({fetchImpl: (path) => path.startsWith('/api/runs/9')
      ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: AT, started_at: AT, status}, events: [], strategies: [], rsi})
      : response({})});
    const f = at('running', {evolved: false, last_dream: null, min_history: 12});
    await f.viewRun(9); f.clearTimers();
    assert.doesNotMatch(figs(f), /How it searches|Self.tuning|Improved/);
    const box = f.root.querySelector('#rsibox'), disc = box.querySelector('details.rsidisc');
    assert.equal('open' in disc.attributes, false);
    assert.match(disc.querySelector('summary').textContent, /How research works\s*Self-tuning/);
    // Nothing is lost: the explainer and what the first check needs are inside.
    assert.match(box.innerHTML, /The agent is <b>self-tuning<\/b>/);
    assert.match(box.innerHTML, /once at least 12 ideas have been tested/);
    const evolved = at('succeeded', {evolved: true, score: 0.61, base_score: 0.48, summary: 'Prefers ideas near settlement.'});
    await evolved.viewRun(9); evolved.clearTimers();
    assert.doesNotMatch(figs(evolved), /How it searches/);
    const ebox = evolved.root.querySelector('#rsibox').innerHTML;
    assert.match(ebox, /How research works/); assert.match(ebox, /Evolved/);
    assert.match(ebox, /0\.48 <span class="rsi-arrow">→<\/span> 0\.61/); assert.match(ebox, /Prefers ideas near settlement\./);
  });

  test(`${name}: a void or rejected strategy's backtest P&L is muted and says it did not pass`, async () => {
    const f = frontend({fetchImpl: () => response({})});
    const m = (pnl) => ({pnl, trades: 40, win_rate: 0.54});
    const cell = (s) => f.strategySlip({id: 1, title: 'T', thesis: '', market: 'btc15m', direction: 'momentum', ...s}, {})
      .match(/<td class="num" data-lab="Backtest P&amp;L[^"]*">(.*?)<\/td>/s)[1];
    for (const status of ['failed', 'rejected']) {
      const tested = cell({status, out_of_sample: null, in_sample: m(2.1)});
      assert.match(tested, /<span class="pnl-nopass">\+\$2\.10<\/span>/, status);
      assert.doesNotMatch(tested, /class="gain"/, status);
      assert.match(tested, /on the history it searched · did not pass/, status);
      const unseen = cell({status, out_of_sample: m(3), in_sample: m(2.1)});
      assert.match(unseen, /^<span class="pnl-nopass">\+\$3\.00<\/span><div class="sub-fig bt-sub"/, status);
      assert.deepEqual(btLine(unseen), {title: `later-period P&amp;L after the split date\u00a0· unseen data${SEP}did not pass`,
        long: `later-period P&amp;L after the split date\u00a0· unseen data${SEP}did not pass`, short: `later\u00a0period${SEP}unseen\u00a0data${SEP}did\u00a0not\u00a0pass`}, status);
    }
    // Passed and backtest-only keep the money tone and say nothing of the kind.
    const passed = cell({status: 'passed', out_of_sample: m(3)});
    assert.match(passed, /^<span class="gain">\+\$3\.00<\/span><div class="sub-fig bt-sub"[^>]*>(?:<span[^>]*>[^<]*<\/span>){2}<\/div>$/);
    assert.equal(btLine(passed).short, 'later\u00a0period' + SEP + 'unseen\u00a0data');
    const kept = cell({status: 'backtest-only', out_of_sample: null, in_sample: m(2.1)});
    assert.match(kept, /class="gain"/); assert.doesNotMatch(kept, /did not pass/);
  });

  test(`${name}: the strategy list's P&L column says which history each figure covers`, async () => {
    // Walk 2026-10-27: the column read "Unseen P&L" (its glossary: "the P&L that counts") over every strategy
    // researched since the locked holdout, whose figure is from the history the agent searched, marked only
    // "tested only". The column is the backtest's, and each row says which data its figure covers.
    const m = (pnl) => ({pnl, trades: 40, win_rate: 0.54});
    const rows = [{id: 1, title: 'New pass', thesis: '', market: 'btc15m', direction: 'custom', status: 'passed', out_of_sample: null, in_sample: m(8.4), hypotheses_tried: 3},
      {id: 2, title: 'Old pass', thesis: '', market: 'btc15m', direction: 'custom', status: 'passed', out_of_sample: m(5), in_sample: m(2), hypotheses_tried: 6}];
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/strategies?')
      ? response({counts: {total: 2, passed: 2}, matched: 2, pages: 1, strategies: rows}) : response({})});
    await f.viewStrategies(); await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
    const html = f.root.querySelector('#slips').innerHTML;
    assert.match(html, /<th class="num">Backtest P&amp;L<\/th>/);
    assert.doesNotMatch(html, /Unseen P&amp;L|tested only|\(tested\)/);
    assert.match(html, /\+\$8\.40<\/span><div class="sub-fig bt-sub" title="on the history it searched"><span class="bt-long">on the history it searched<\/span><span class="bt-short" aria-hidden="true">history it searched<\/span><\/div>/);
    // A held-out figure is the later period too, as the sort that orders it ("Later-period P&L") says.
    assert.match(html, /\+\$5\.00<\/span><div class="sub-fig bt-sub" title="later-period P&amp;L after the split date\u00a0· unseen data"><span class="bt-long">later-period P&amp;L after the split date\u00a0· unseen data<\/span><span class="bt-short" aria-hidden="true">later\u00a0period\u00a0· unseen\u00a0data<\/span><\/div>/);
    // No figure, no data line.
    assert.doesNotMatch(f.strategySlip({id: 3, title: 'T', thesis: '', market: 'btc15m', status: 'queued', in_sample: {}}, {}), /sub-fig[^"]*"[^>]*>(?:<span[^>]*>)?(?:on|later|history) /);
    f.clearTimers();
  });
  test(`${name}: a session's pass with no gatekeeper record says its figure is later-period, as on the Strategies list`, async () => {
    // The session page renders the same rows (strategySlip on Meridian) from the same server flag, read with its
    // own later checks (no_gatekeeper_record): a pass from the old loose gate never reads "on unseen data" there.
    const m = (pnl) => ({pnl, trades: 40, win_rate: 0.54, days: 30});
    const row = (extra) => ({id: 51, title: 'Loose pass', thesis: '', market: 'btc15m', direction: 'momentum', status: 'passed',
      out_of_sample: m(6.2), in_sample: m(2), ...extra});
    let f = await open({status: 'succeeded', hypotheses_tried: 1, strategies_passed: 1}, [], [row({no_gatekeeper_record: true})]);
    const html = list(f);
    assert.match(html, /Loose pass/); assert.doesNotMatch(html, /unseen data/);
    if (/Backtest P&amp;L/.test(html)) assert.match(html, /later-period P&amp;L over 30 days after the split date, which picked it\u00a0· not held out/);
    f = await open({status: 'succeeded', hypotheses_tried: 1, strategies_passed: 1}, [], [row({})]);
    if (/Backtest P&amp;L/.test(list(f))) assert.match(list(f), /later-period P&amp;L over 30 days after the split date\u00a0· unseen data/);
  });
  test(`${name}: the ideas list says what its count counts`, async () => {
    // Walk 2026-10-27 (Tau, 390px): its head read "1 · 1 more still being tested", a bare figure beside a counted one.
    const rows = [{id: 42, title: 'Late', status: 'failed', market: 'btc15m', direction: 'momentum'}];
    const hyp = (id) => ev(id, 'hypothesis', 'Idea ' + id);
    const f = await open({status: 'running', max_hypotheses: 6, hypotheses_tried: 1}, [1, 2].map(hyp), rows);
    const host = f.root.querySelector('#runideas');
    if (host) assert.match(host.innerHTML, /<p>1 listed · 1 more still being tested · tap one for its story<\/p>/);
    else assert.match(list(f), /1 more idea still being tested/);
  });
}
