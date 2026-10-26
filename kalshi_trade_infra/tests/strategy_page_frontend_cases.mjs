// Strategy page (/strategies/:id) cases, run against each bundle's offline DOM/transport harness.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));

export function strategyPageCases({name, detailStrategy, strategyFrontend, postRequests}) {
  const open = async (overrides) => {
    const f = strategyFrontend(detailStrategy(overrides), () => response({}));
    await f.viewStrategy(42); await flush();
    return f;
  };
  const main = f => f.root.querySelector('main').innerHTML;

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
}
