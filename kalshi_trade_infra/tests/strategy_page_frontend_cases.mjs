// Strategy page (/strategies/:id) cases, run against each bundle's offline DOM/transport harness.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));

export function strategyPageCases({name, frontend, detailStrategy, strategyFrontend, postRequests}) {
  const open = async (overrides) => {
    const f = strategyFrontend(detailStrategy(overrides), () => response({}));
    await f.viewStrategy(42); await flush();
    return f;
  };
  const main = f => f.root.querySelector('#main').innerHTML;

  test(`${name}: a code strategy offers no deploy button the server would refuse, and says what to do`, async () => {
    for (const status of ['passed', 'failed', 'backtest-only']) {
      const f = await open({kind: 'code', research_only: true, status, rules: ['Agent-authored quant code.'],
        experiment: {classification: 'deployment_candidate'}});
      for (const id of ['dep-paper', 'dep-paper-quick', 'dep-demo', 'dep-live', 'live-confirm', 'road-live']) {
        assert.equal(f.root.querySelector('#' + id), null, `${status}: #${id} must be absent`);
      }
      assert.match(main(f), /Research only/);
      assert.match(main(f), /run only in the research sandbox/);
      assert.match(main(f), /rule-based version in a new research session/);
      assert.doesNotMatch(main(f), /Perpetual strategies stay in research|Deploying it is your decision/);
      assert.equal(f.requests.some(({path}) => /live-readiness/.test(path)), false);
      assert.equal(postRequests(f).length, 0);
    }
    // A rule-based passed strategy keeps its deploy buttons.
    const rule = await open({status: 'passed'});
    assert.ok(rule.root.querySelector('#dep-paper'));
  });

  // Every Kalshi strategy's pre-registration stores {fee: 'kalshi_taker', fill: 'ask/bid'} (agent.py), and its page
  // printed them as stored: "Fee: kalshi_taker · Fill: ask/bid".
  test(`${name}: the pre-registered cost assumptions read in words, never the stored codes`, async () => {
    const f = await open({status: 'passed', experiment: {classification: 'deployment_candidate', null_hypothesis: 'No edge.',
      cost_assumptions: {fee: 'kalshi_taker', fill: 'ask/bid'}}});
    assert.match(main(f), /<dt>Cost assumptions<\/dt><dd>Fee: Kalshi(?:’|&#39;|')s taker fee on every fill ·\u00a0Fill: buys at the ask, sells at the bid<\/dd>/);
    assert.doesNotMatch(main(f), /kalshi_taker|ask\/bid/);
    const perp = await open({status: 'passed', experiment: {classification: 'deployment_candidate', null_hypothesis: 'No edge.',
      cost_assumptions: {fill: 'next_open', funding: 'finalized_payments_as_cost_only', scenario: 'some_new_code', lookback_minutes: 60}}});
    assert.match(main(perp), /Fill: the next bar’s open ·\u00a0Funding: settled funding payments, counted only as a cost ·\u00a0Scenario: some new code ·\u00a0Lookback minutes: 60/);
    assert.doesNotMatch(main(perp), /next_open|finalized_payments|some_new_code/);
  });

  test(`${name}: the research figures read the stored per-trade returns, in stakes and % of stake`, async () => {
    // The gatekeeper stores a phase as its per-trade net returns, not a running total.
    const val = [[1000, 0.5], [2000, -0.8], [3000, 1.0]], hold = [[4000, 0.25], [5000, -0.05]];
    const f = await open({status: 'passed', experiment: {classification: 'deployment_candidate',
      validation: {n_trades: 3, mean_net_return: 0.02, ci_lo: 0.001, ci_hi: 0.04, p_value: 0.02, equity_curve: val},
      holdout: {n_trades: 2, mean_net_return: 0.01, p_value: 0.04, consumed: true, equity_curve: hold},
      folds: [{from_ts: 1000, to_ts: 2000, n_trades: 2, mean_net_return: -0.15}]}});
    const html = main(f);
    const between = (a, b) => html.slice(html.indexOf(a), html.indexOf(b, html.indexOf(a)));
    const equity = between('Equity by phase', 'Validation vs holdout');
    // Running totals 0.5, −0.3, 0.7 (validation): ticks in stakes, never dollars.
    assert.match(equity, /\+0\.7×|\+1\.2×/); assert.doesNotMatch(equity, /\$/);
    // The deepest drop is 0.8 stakes (from +0.5 down to −0.3), not a dollar figure.
    assert.match(between('Drawdown (underwater)', 'Per-trade return distribution'), /−0\.8×/);
    // Returns read as % of the stake, not cents; the two held-out averages are compared.
    const vs = between('Validation vs holdout', 'Drawdown (underwater)');
    assert.match(vs, /\+2\.00%/); assert.match(vs, /\+1\.00%/); assert.match(vs, /50% smaller than validation/);
    assert.doesNotMatch(between('Validation-window evidence', 'The one-time locked holdout'), /¢|In-sample vs validation|research fold/);
    assert.match(html, /Net return per trade<\/div><div class="val">\+2\.00%/);
    // A walk-forward slice is labelled by its own date (the gatekeeper's from_ts), not "W1".
    assert.doesNotMatch(between('Walk-forward windows', 'Backtest'), />W1</);
  });

  test(`${name}: the verdict reads near the top: what passed it, or the check it missed`, async () => {
    const top = html => html.slice(0, html.indexOf('paper-body'));
    const lines = [{gate: 'significance', label: 'The edge could be luck on the locked holdout', measured: 'p 0.58', needed: '0.10', next: 'Try again.'},
      {gate: 'net_edge', label: 'Loses money after fees on the locked holdout', measured: 'x', needed: 'y', next: 'Z.'}];
    const failed = await open({status: 'failed', why_failed: lines, experiment: {classification: 'inconclusive',
      validation: {n_trades: 58, mean_net_return: 0.022}, holdout: {n_trades: 31, mean_net_return: -0.004, consumed: true}}});
    assert.match(top(main(failed)), /<b>Void\.<\/b> It missed 2 checks: the edge could be luck on the locked holdout, and 1 more\./);
    const passed = await open({status: 'passed', experiment: {classification: 'deployment_candidate',
      validation: {n_trades: 64, mean_net_return: 0.031}, holdout: {n_trades: 34, mean_net_return: 0.024, consumed: true}}});
    assert.match(top(main(passed)), /<b>Passed\.<\/b> It cleared every check, including the one-time locked holdout: 34 trades on data it had never seen, averaging \+2\.40% of the stake per trade after fees\./);
    const pending = await open({status: 'passed', experiment: {classification: 'statistically_supported', validation: {n_trades: 40}, holdout: null}});
    assert.match(top(main(pending)), /<b>Passed validation\.<\/b> It cleared the checks on 40 trades it had never seen; the one-time locked holdout hasn’t run yet\./);
    // Labels are escaped like every other server string.
    const evil = await open({status: 'rejected', why_failed: [{...lines[0], label: '<img src=x>'}], experiment: {classification: 'rejected'}});
    assert.doesNotMatch(main(evil), /<img src=x>/);
  });

  test(`${name}: a research strategy's unseen-data figure and abstract read its held-out record`, async () => {
    // A research session stores no backtest out_of_sample: its unseen-data result is the gatekeeper's
    // validation record, and the page read "Rejected before the unseen test" beside Passed.
    const exp = {classification: 'deployment_candidate', validation: {n_trades: 132, net_pnl: 20.46, mean_net_return: 0.031},
      holdout: {n_trades: 64, mean_net_return: 0.024, consumed: true}};
    const f = await open({status: 'passed', out_of_sample: null, experiment: exp});
    const figs = f.root.querySelector('#figs').innerHTML;
    assert.match(figs, /\+\$20\.46/); assert.match(figs, /after fees, over 132 trades the agent never saw/);
    assert.doesNotMatch(figs + main(f), /Rejected before the unseen test|Not tested out-of-sample|not advanced to the unseen-data test/);
    assert.match(main(f), /On 132 trades of data the agent never saw while iterating, it made \$20\.46 after fees \(\+3\.10% of the stake per trade\), one of 5 ideas tested this run\./);
    // Too few trades to judge: the loss and the count it had, still not "rejected before the test".
    const few = await open({status: 'failed', out_of_sample: null, experiment: {classification: 'inconclusive', validation: {n_trades: 38, net_pnl: -1.2}}});
    assert.match(main(few), /On 38 trades of data the agent never saw while iterating, it lost \$1\.20 after fees, one of 5 ideas/);
    assert.doesNotMatch(main(few), /rejected before reaching the unseen-data test/);
    // An older strategy with a backtest keeps its out_of_sample figure; one never tested still says so.
    const legacy = await open({status: 'passed', experiment: exp});
    assert.doesNotMatch(legacy.root.querySelector('#figs').innerHTML, /132 trades/);
    const never = await open({status: 'rejected', out_of_sample: null, experiment: {classification: 'rejected'}});
    assert.match(main(never), /rejected before reaching the unseen-data test/);
  });

  test(`${name}: a rejected strategy says the check it missed, not "ranked below the finalists"`, async () => {
    const skeptic = [{gate: 'challenger', label: "The skeptic's review didn't pass it", measured: 'an objection', needed: 'a reason', next: 'Say who pays.'}];
    const f = await open({status: 'rejected', out_of_sample: null, experiment: null, why_failed: skeptic});
    assert.match(main(f), /Rejected — the skeptic&#39;s review didn&#39;t pass it\.|Rejected — the skeptic's review didn't pass it\./);
    assert.match(main(f), /Not tested on unseen data — the skeptic(&#39;|')s review didn(&#39;|')t pass it\./);
    assert.doesNotMatch(main(f), /ranked below the handful of finalists/);
    // A label is text: escaped where the page writes it as HTML.
    const evil = await open({status: 'rejected', out_of_sample: null, experiment: null, why_failed: [{...skeptic[0], label: '<img src=x>'}]});
    assert.doesNotMatch(main(evil), /<img src=x>/);
    // With no missed check from the server it keeps its own reason.
    const old = await open({status: 'rejected', out_of_sample: null, experiment: null, why_failed: [], in_sample: {trades: 40, pnl: -2}});
    assert.match(main(old), /it lost money in testing/);
    // A research strategy's never-seen column points at its validation record, which it was tested on.
    const held = await open({status: 'failed', out_of_sample: null, why_failed: [],
      experiment: {classification: 'inconclusive', validation: {n_trades: 38, net_pnl: 1.1}}});
    assert.match(main(held), /Its test on unseen data is the validation-window evidence above\./);
    assert.doesNotMatch(main(held), /Not tested on unseen data/);
  });

  test(`${name}: a backtest-only strategy says it can't be deployed, as the server refuses it`, async () => {
    const f = await open({status: 'backtest-only', experiment: null});
    assert.doesNotMatch(main(f), /Deploying it is your decision/);
    assert.match(main(f), /It can’t be deployed: only a strategy put through those checks can be\./);
    assert.match(main(f), /A backtest-only strategy can’t be deployed: it never went through the held-out checks\./);
    assert.equal(f.root.querySelector('#dep-paper'), null);
  });

  test(`${name}: what it does, in plain words, is the paper's first section, outside the Methodology fold`, async () => {
    const f = await open({status: 'passed', rules: ['Buys YES contracts when its fair value beats the price by at least 6¢.', 'Only when the 5-minute return is above +0.40%.'],
      experiment: {classification: 'deployment_candidate', mechanism: 'Late chasers overpay.', planned_test: 'bootstrap'},
      dataset: {start: '2026-09-24T00:00Z', end: '2026-10-24T00:00Z', out_of_sample_from: '2026-10-15T00:00Z'}});
    const html = main(f), body = html.slice(html.indexOf('paper-body'));
    const first = body.indexOf('<section class="paper-sec">');
    assert.match(body.slice(first, first + 160), /What it does, in plain words/);
    assert.ok(body.indexOf('Only when the 5-minute return is above +0.40%.') < body.indexOf('Mechanism &amp; hypothesis'));
    const methodology = html.slice(html.indexOf('<summary class="fold-h">Methodology'));
    assert.ok(methodology.length > 0 && methodology.includes('Data &amp; partitioning'));
    assert.doesNotMatch(methodology.slice(0, methodology.indexOf('</details>', methodology.indexOf('Data &amp; partitioning'))), /class="rules"/);
  });

  test(`${name}: the research paper's statistics and test names come with plain words`, async () => {
    const f = await open({status: 'failed', experiment: {classification: 'inconclusive', registered_at: '2026-10-20T10:00:00Z',
      primary_metric: 'mean_net_return_per_trade', planned_test: 'stationary_bootstrap one-sided, alpha from LORD++',
      planned_n_tests: 37, correction_method: 'LORD++', n_trials_audited: 37,
      validation: {n_trades: 58, mean_net_return: 0.022, p_value: 0.03, psr: 0.95, dsr: 0.88, fdr_alpha_i: 0.05, fdr_reject: true, placebo_p: 0.03},
      holdout: {n_trades: 31, mean_net_return: -0.004, p_value: 0.58, consumed: true}}});
    const html = main(f);
    for (const raw of ['mean_net_return_per_trade', 'stationary_bootstrap', 'FDR α spent', 'rejects the null', 'label-shuffle', 'roll to fresh forward data', 'alpha budget', 'false-discovery budget']) {
      assert.ok(!html.includes(raw), `still shows ${raw}`);
    }
    assert.match(html, /average net return per trade, after fees/);
    assert.match(html, /one-sided bootstrap test \(resamples its trades in blocks\), significance bar from LORD\+\+/);
    assert.match(html, /37 planned tests · LORD\+\+ \(a false-discovery control: it keeps count of every idea tested, so lucky passes stay rare\)/);
    assert.match(html, /chance a rule with no edge does this well; lower is better/);
    assert.match(html, /p-value needed<\/div><div class="val">0\.0500<\/div><div class="sub">the bar its p-value had to clear; it cleared it/);
    assert.match(html, /used once, as designed: it can’t be re-run on this data/);
    const bh = await open({status: 'passed', experiment: {classification: 'statistically_supported', correction_method: 'BH', planned_n_tests: 4}});
    assert.match(main(bh), /4 planned tests · Benjamini–Hochberg/);
  });

  test(`${name}: the ladder keeps the rung validation reached when the holdout then failed`, async () => {
    const f = await open({status: 'failed', experiment: {classification: 'inconclusive',
      validation: {classification: 'statistically_supported', n_trades: 58}, holdout: {classification: 'inconclusive', n_trades: 31, consumed: true}}});
    const ladder = main(f).slice(main(f).indexOf('Where it reached on the ladder'));
    assert.match(ladder, /<div class="rung lit"><div class="r-n">Rung 2<\/div><div class="r-t">Stat\. supported/);
    assert.match(ladder, /<b>Inconclusive<\/b> on the locked holdout — it reached Stat\. supported in validation, then its edge did not hold up\./);
    // A strategy rejected in validation still reads as never advancing.
    const r = await open({status: 'failed', experiment: {classification: 'rejected', validation: {classification: 'rejected', n_trades: 20}}});
    assert.match(main(r), /this hypothesis did not advance the ladder/); assert.doesNotMatch(main(r), /rung lit/);
  });

  test(`${name}: the page is drawn while the demo replay loads, the chart says its line is coming, then drops that`, async () => {
    for (const answer of [{dev_curve: [[200, 1], [300, 2]]}, {dev_curve: null, reason: 'unavailable'}, 'fails']) {
      let release;
      const gate = new Promise((resolve) => { release = resolve; });
      const f = frontend({fetchImpl: async (path) => {
        if (path === '/api/strategies/42') return response(detailStrategy({status: 'passed'}));
        if (path === '/api/strategies/42/dev-curve') {
          await gate;
          if (answer === 'fails') return response({error: 'Server error.'}, 500);  // Tau answering: final, no retry
          return response(answer);
        }
        return response({});
      }});
      await f.viewStrategy(42); await flush();
      const pending = f.root.querySelector('#dev-pending');
      assert.ok(pending, 'pending line under the chart');
      assert.match(pending.outerHTML || main(f), /Replaying the unseen window against Kalshi's demo book/);
      assert.match(main(f), /<span class="skeleton" aria-hidden="true"><\/span>/);
      for (const id of ['equity-wrap', 'gates', 'dep-paper']) assert.ok(f.root.querySelector('#' + id), `#${id} drawn first`);
      release();
      for (let i = 0; i < 6; i++) await flush();
      assert.equal(pending.removed, true, `${JSON.stringify(answer)}: pending line removed`);
      if (answer.dev_curve) assert.match(f.root.querySelector('#equity-wrap').innerHTML, /Dashed line: the unseen window replayed/);
    }
    // No unseen window to replay: no pending line at all.
    const none = await open({status: 'rejected', out_of_sample: null});
    assert.equal(none.root.querySelector('#dev-pending'), null);
  });

  // A validation pass keeps the status "passed" when a later check fails; the server's why_failed names it.
  const val = {classification: 'statistically_supported', n_trades: 150, mean_net_return: 0.026};
  const holdoutMiss = [{gate: 'significance', label: 'The edge could be luck on the locked holdout', measured: 'p-value 0.480', needed: '0.050 or lower', next: 'Try a simpler version.'}];
  const tooSimilar = [{gate: 'diversification', label: 'Too similar to “<b>BTC</b> fade”', measured: 'a 0.93 correlation of daily results with “<b>BTC</b> fade”', needed: '0.80 or less', next: 'Point it elsewhere.'}];
  const stamp = f => (f.root.querySelector('.paper-byline') || f.root.querySelector('.strategy-pagehead')).innerHTML;

  test(`${name}: a strategy that passed validation and then missed the final test never reads Passed`, async () => {
    const f = await open({status: 'passed', out_of_sample: null, why_failed: holdoutMiss, experiment: {classification: 'rejected', validation: val,
      holdout: {classification: 'rejected', n_trades: 71, mean_net_return: -0.003, p_value: 0.48, consumed: true}}});
    const html = main(f);
    assert.match(stamp(f), /<span class="mk">Missed final test<\/span>/); assert.doesNotMatch(stamp(f), />Passed</);
    assert.match(html, /<b>Missed the final test\.<\/b> It passed its first test on unseen data \(150 trades\), then missed the one-time final test on the locked holdout: the edge could be luck on the locked holdout\./);
    assert.doesNotMatch(html, /<b>Passed|cleared every check|this is the one that passed|cleared the gate as one of/);
    // No Deploy on paper up top and no Road to live (it can never be cleared); the panel says why before its button.
    assert.equal(f.root.querySelector('#dep-paper-quick'), null); assert.equal(f.root.querySelector('#road-live'), null);
    assert.ok(f.root.querySelector('#dep-paper'));
    assert.match(html, /Missed the final test: the edge could be luck on the locked holdout \(see Verdict\)\. It wasn’t cleared to trade, so it can’t go live, and putting it on paper is your call\./);
    assert.ok(html.indexOf('Missed the final test: the edge') < html.indexOf('id="dep-paper"'));
    assert.equal(f.requests.some(({path}) => /live-readiness/.test(path)), false);
  });

  test(`${name}: a strategy the diversification check held back says so, named, never "cleared every check"`, async () => {
    const f = await open({status: 'passed', out_of_sample: null, why_failed: tooSimilar, experiment: {classification: 'forward_validated', promoted: false,
      validation: val, holdout: {classification: 'forward_validated', n_trades: 64, mean_net_return: 0.024, p_value: 0.01, consumed: true}}});
    const html = main(f);
    assert.match(stamp(f), /<span class="mk quiet">Held back<\/span>/); assert.doesNotMatch(stamp(f), />Passed</);
    assert.match(html, /<b>Held back\.<\/b> It held up on data it had never seen, the one-time locked holdout included, but it is too similar to “&lt;b&gt;BTC&lt;\/b&gt; fade”, so the gatekeeper didn’t clear it to trade\./);
    assert.doesNotMatch(html, /<b>Passed|cleared every check|<b>BTC<\/b>/);
    assert.equal(f.root.querySelector('#dep-paper-quick'), null); assert.equal(f.root.querySelector('#road-live'), null);
    assert.match(html, /Held back: too similar to “&lt;b&gt;BTC&lt;\/b&gt; fade” \(see Verdict\)\./);
  });

  test(`${name}: a probation strategy held back after passing on paper says so, not Void over its validation miss`, async () => {
    const paper = {classification: 'forward_validated', n_trades: 60, mean_net_return: 0.021, p_value: 0.01};
    const near = {classification: 'inconclusive', n_trades: 18, mean_net_return: 0.012, p_value: null};
    const f = await open({status: 'failed', verdict: 'held_back', out_of_sample: null, why_failed: tooSimilar,
      experiment: {classification: 'forward_validated', promoted: false, validation: near, holdout: null, paper}});
    const html = main(f);
    assert.match(stamp(f), /<span class="mk quiet">Held back<\/span>/); assert.doesNotMatch(stamp(f), />Void</);
    assert.match(html, /<b>Held back\.<\/b> It fell short on its first test on unseen data, so it went on paper on probation, and passed its one judgment there \(60 paper trades\), but it is too similar to “&lt;b&gt;BTC&lt;\/b&gt; fade”, so the gatekeeper didn’t clear it to trade\./);
    // Its forward evidence is the paper judgment: the verdict never says it held up on the locked holdout.
    assert.match(html, /Forward-validated on paper\. It fell short on validation, then passed its one pre-registered judgment on its own paper trades\./);
    assert.doesNotMatch(html, /<b>Void\.|held up on the locked holdout|It wasn’t validated|<b>BTC<\/b>/);
    assert.match(html, /Held back: too similar to “&lt;b&gt;BTC&lt;\/b&gt; fade” \(see Verdict\)\. It wasn’t cleared to trade, so it can’t go live/);
    assert.equal(f.root.querySelector('#dep-paper-quick'), null); assert.equal(f.root.querySelector('#road-live'), null);
    // Once the diversification check promotes it, it passed on paper and says so.
    const ok = await open({status: 'passed', why_failed: [], out_of_sample: null,
      experiment: {classification: 'deployment_candidate', promoted: true, validation: near, holdout: null, paper}});
    assert.match(stamp(ok), /<span class="mk on">Passed<\/span>/);
    assert.match(main(ok), /<b>Passed on paper\.<\/b> It fell short on its first test on unseen data, then passed its one judgment on its own paper trades \(60\) and every check after it\./);
    assert.doesNotMatch(main(ok), /<b>Passed validation|held up on the one-time locked holdout/);
  });

  test(`${name}: a true pass keeps its stamp, summary, Deploy on paper up top and Road to live`, async () => {
    const f = await open({status: 'passed', why_failed: [], experiment: {classification: 'deployment_candidate', promoted: true, validation: val,
      holdout: {classification: 'forward_validated', n_trades: 64, mean_net_return: 0.024, consumed: true}}});
    assert.match(stamp(f), /<span class="mk on">Passed<\/span>/);
    assert.match(main(f), /<b>Passed\.<\/b> It cleared every check, including the one-time locked holdout/);
    assert.ok(f.root.querySelector('#dep-paper-quick')); assert.ok(f.root.querySelector('#dep-paper')); assert.ok(f.root.querySelector('#road-live'));
    assert.doesNotMatch(main(f), /data-ap-next|data-ap-off|notice bad/);
    // A plain reject keeps its own stamp and notice.
    const r = await open({status: 'rejected', why_failed: holdoutMiss, experiment: {classification: 'rejected'}});
    assert.match(stamp(r), /<span class="mk quiet">Rejected<\/span>/); assert.match(main(r), /<b>Rejected\.<\/b>/);
    assert.doesNotMatch(main(r), /Missed final test|Held back/);
  });

  test(`${name}: a pass the autopilot puts on paper itself says so in place of Deploy on paper, and follows the switch`, async () => {
    const detail = {status: 'passed', why_failed: [], autopilot_paper: true, experiment: {classification: 'deployment_candidate', promoted: true, validation: val,
      holdout: {classification: 'forward_validated', n_trades: 64, mean_net_return: 0.024, consumed: true}}};
    const f = strategyFrontend(detailStrategy(detail), () => response({}));
    f.S.me.user.autopilot = true;
    await f.viewStrategy(42); await flush();
    const said = /The autopilot is putting this on paper at its next check-in, so there is nothing for you to deploy\./;
    assert.match(f.root.querySelector('#strat-quick').innerHTML, said);
    assert.equal(f.root.querySelector('#dep-paper-quick').hidden, true); assert.equal(f.root.querySelector('#dep-paper').hidden, true);
    assert.match(main(f), /Next rung, paper: <span data-ap-next>the autopilot puts it there at its next check-in\.<\/span><span data-ap-off hidden>/);
    // The switch flips off while the page is open: the buttons come back and the line hides.
    f.S.ap = {autopilot: false, mode: 'off'}; f.paintDashAp();
    assert.equal(f.root.querySelector('#dep-paper-quick').hidden, false); assert.equal(f.root.querySelector('#dep-paper').hidden, false);
    for (const n of f.root.querySelectorAll('[data-ap-next]')) assert.equal(n.hidden, true);
    // Off when the page opened: the buttons as before, the line drawn hidden.
    const g = strategyFrontend(detailStrategy(detail), () => response({}));
    await g.viewStrategy(42); await flush();
    assert.equal(g.root.querySelector('#dep-paper').hidden, false);
    assert.match(main(g), /<p class="hint ap-paper" data-ap-next hidden>/);
  });

  test(`${name}: the ideas-tested figure says "Ideas tested" over the session's count, in the words the lists use`, async () => {
    // Walk 2026-10-27: Tau's figure read "Hypotheses tested 1 of 18" while Meridian and both strategy lists
    // said "Ideas tested" over 18; Meridian's abstract still said "hypotheses tested this run".
    const f = await open({status: 'passed', hypotheses_tried: 18});
    const figs = f.root.querySelector('#figs').textContent;
    assert.match(figs, /Ideas tested\s*18\s*in the session that found it/);
    assert.doesNotMatch(figs, /1 of 18/);
    assert.doesNotMatch(main(f) + figs, /hypotheses tested/i);
    assert.match(main(f), /18 ideas tested this run/);
    const none = await open({status: 'passed', hypotheses_tried: null});
    assert.match(none.root.querySelector('#figs').textContent, /Ideas tested\s*—\s*Count unavailable\./);
  });

  test(`${name}: since deploying, each book says which money it is and that fees are in, and open positions aren't`, async () => {
    // Walk 2026-10-27: only the paper line said what its P&L was net of. "Demo +$1.16 realized over 3 closed
    // trades · 1 open" said neither that it was Tau's demo book (not real money) nor that Kalshi's fees were in.
    const deployments = [
      {id: 1, mode: 'demo', status: 'running', realized_pnl: 1.16, closed_trades: 3, open_positions: 1, created_at: '2026-10-27T08:00:00Z'},
      {id: 2, mode: 'live', status: 'running', realized_pnl: -2.5, closed_trades: 2, open_positions: 2, created_at: '2026-10-27T08:00:00Z'},
      {id: 3, mode: 'paper', status: 'running', realized_pnl: 6.86, closed_trades: 6, open_positions: 0, created_at: '2026-10-27T08:00:00Z'}];
    const f = await open({status: 'passed', deployments});
    const lines = [...f.root.querySelectorAll('.real-record p')].map((p) => p.textContent.replace(/\s+/g, ' '));
    const line = (mode) => lines.find((t) => t.startsWith(mode)) || '';
    assert.match(line('Demo'), /^Demo \+\$1\.16 realized over 3 closed trades, after Kalshi fees, in Tau’s demo book: not real money · 1 open, counted once it closes/);
    assert.match(line('Live'), /−\$2\.50 realized over 2 closed trades, real money, after Kalshi fees · 2 open, counted once they close/);
    assert.match(line('Paper'), /\+\$6\.86 realized over 6 closed trades, after Kalshi fees and the spread/);
    assert.doesNotMatch(line('Paper'), /real money|demo book/);
    // Each book on its own line: never one figure across them.
    assert.doesNotMatch(lines.join(' '), /\$5\.52|\$4\.36/);
  });

  test(`${name}: past deployments say which money each was and that fees are in, as the lines above do`, async () => {
    // "Demo Sep 28–Oct 1, −$1.50 over 1 closed trade" said neither that it was Tau's demo book (not real money)
    // nor that Kalshi's fees were taken off, where the "Since deploying" line above it now says both.
    const past_deployments = [
      {id: 9, mode: 'live', created_at: '2026-10-02T08:00:00+00:00', removed_at: '2026-10-20T08:00:00+00:00', realized_pnl: 3.25, closed_trades: 4},
      {id: 8, mode: 'demo', created_at: '2026-09-28T08:00:00+00:00', removed_at: '2026-10-01T08:00:00+00:00', realized_pnl: -1.5, closed_trades: 1},
      {id: 7, mode: 'paper', created_at: '2026-09-20T08:00:00+00:00', removed_at: '2026-09-21T08:00:00+00:00', realized_pnl: 5.72, closed_trades: 14}];
    const f = await open({status: 'passed', deployments: [], past_deployments});
    const text = f.root.querySelector('.past-deps').textContent.replace(/\s+/g, ' ');
    const parts = text.replace(/^Past deployments: /, '').split(' · ');
    assert.equal(parts.length, 3);
    assert.match(parts[0], /^Live Oct 2–Oct 20, \+\$3\.25 over 4 closed trades, real money, after Kalshi fees$/);
    assert.match(parts[1], /^Demo Sep 28–Oct 1, −\$1\.50 over 1 closed trade, after Kalshi fees, in Tau’s demo book: not real money$/);
    assert.match(parts[2], /^Paper Sep 20–Sep 21, \+\$5\.72 over 14 closed trades, after Kalshi fees and the spread$/);
    assert.doesNotMatch(parts[2], /real money|demo book/);
    // Each book apart: never one figure across them.
    assert.doesNotMatch(text, /\$7\.47|\$1\.75|\$4\.22/);
  });

  test(`${name}: a past deployment with no closed trades says so, with which money it was, not "$0.00 over 0 closed trades"`, async () => {
    // It read "Demo Sep 28–Oct 1, $0.00 over 0 closed trades" with no book, under lines that say both.
    const past_deployments = [
      {id: 9, mode: 'live', created_at: '2026-10-02T08:00:00+00:00', removed_at: '2026-10-20T08:00:00+00:00', realized_pnl: 0, closed_trades: 0},
      {id: 8, mode: 'demo', created_at: '2026-09-28T08:00:00+00:00', removed_at: '2026-10-01T08:00:00+00:00', realized_pnl: 0, closed_trades: 0},
      {id: 7, mode: 'paper', created_at: '2026-09-20T08:00:00+00:00', removed_at: '2026-09-21T08:00:00+00:00', realized_pnl: 0, closed_trades: 0}];
    const f = await open({status: 'passed', deployments: [], past_deployments});
    const text = f.root.querySelector('.past-deps').textContent.replace(/\s+/g, ' ');
    const parts = text.replace(/^Past deployments: /, '').split(' · ');
    assert.equal(parts.length, 3);
    assert.match(parts[0], /^Live Oct 2–Oct 20, no closed trades, real money$/);
    assert.match(parts[1], /^Demo Sep 28–Oct 1, no closed trades, in Tau’s demo book: not real money$/);
    assert.match(parts[2], /^Paper Sep 20–Sep 21, no closed trades, not real money$/);
    assert.doesNotMatch(text, /\$0\.00|0 closed trades|after Kalshi fees/);  // nothing to net of fees
    // One with closed trades beside it keeps its figure and its fees.
    const g = await open({status: 'passed', deployments: [], past_deployments: [past_deployments[1],
      {id: 6, mode: 'demo', created_at: '2026-09-10T08:00:00+00:00', removed_at: '2026-09-12T08:00:00+00:00', realized_pnl: -1.5, closed_trades: 1}]});
    assert.match(g.root.querySelector('.past-deps').textContent.replace(/\s+/g, ' '),
      /Demo Sep 28–Oct 1, no closed trades, in Tau’s demo book: not real money · Demo Sep 10–Sep 12, −\$1\.50 over 1 closed trade, after Kalshi fees, in Tau’s demo book: not real money$/);
  });

  test(`${name}: Road to live that didn't load says why and offers Try again, which fills it`, async () => {
    const road = {ready: false, deployment_candidate: true, live_autopilot: {ok: false},
      paper: {trades: 12, trades_needed: 30, net_pnl: 3.4, events: 12, events_needed: 20, span_hours: 50, span_needed_hours: 48,
        p_value: 0.2, p_value_needed: 0.1, recent_trades: 6, recent_net_pnl: 1, realization: null, demo_orders: 7, demo_orders_needed: 20,
        checks: {realistic_trades: false, net_pnl: true, events: false, span: true, edge: false, recent: true}}};
    let reads = 0;
    const f = strategyFrontend(detailStrategy({status: 'passed'}), (path) => {
      if (path === '/api/strategies/42/live-readiness') return ++reads === 1 ? response({error: 'Tau is busy. Try again in a moment.'}, 500) : response(road);
      return response({});
    });
    await f.viewStrategy(42); await flush(); await flush();
    const body = () => f.root.querySelector('#road-live-body');
    assert.match(body().innerHTML, /Tau is busy\. Try again in a moment\./);
    assert.doesNotMatch(body().innerHTML, /unavailable/);
    await body().querySelector('[data-road-retry]').onclick(); await flush(); await flush();
    assert.equal(reads, 2);
    assert.match(body().innerHTML, /Realistic paper trades/);
    assert.equal(body().querySelector('[data-road-retry]'), null);
    if (f.clearTimers) f.clearTimers();
  });
}
