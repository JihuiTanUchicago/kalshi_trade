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
}
