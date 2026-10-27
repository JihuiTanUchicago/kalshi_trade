// Shared cases, run against each bundle's offline harness (Tau and Meridian): a brand-new customer's first hour,
// walked on 2026-10-27 at 390px and 1280px from sign-up through the first research session, the first paper
// deployment and the first closed paper trade. Each case is a place where the page said something the account
// hadn't done yet, or showed a figure as $0.00 where "None yet" is what is true.
import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));

export function newUserCases({name, frontend, detailStrategy, strategyFrontend}) {
  const meridian = name === 'Meridian';

  // A research session's strategy has no Return on capital, so its page shows three figures. Meridian's grid had four
  // columns and left an empty slot at the end; it now takes the count, on first paint and after a what-if redraw.
  test(`${name}: a strategy page's figure row says how many figures it holds, so three fill the row`, {skip: !meridian}, async () => {
    const exp = {classification: 'deployment_candidate', validation: {n_trades: 132, net_pnl: 20.46, mean_net_return: 0.031}};
    const result = {in_sample: {pnl: 5, trades: 40}, out_of_sample: null, equity: [[100, 0], [300, 5]], gates: [], passed: true};
    const f = strategyFrontend(detailStrategy({status: 'passed', out_of_sample: null, experiment: exp}), () => response(result));
    await f.viewStrategy(42); await flush();
    const figs = f.root.querySelector('#figs');
    assert.equal(figs.querySelectorAll('dt').length, 3);
    assert.equal(figs.getAttribute('data-cols'), '3');
    const wi = f.root.querySelector('#whatif');
    wi.querySelector('#wf').value = '0'; wi.querySelector('#ws').value = '0';
    wi.querySelector('#wf').oninput();
    await [...f.timeouts.values()].at(-1)();
    assert.equal(f.root.querySelector('#figs').getAttribute('data-cols'), '3');
    // An older backtest's strategy keeps its four.
    const old = strategyFrontend(detailStrategy({status: 'passed'}), () => response({}));
    await old.viewStrategy(42); await flush();
    assert.equal(old.root.querySelector('#figs').getAttribute('data-cols'), '4');
    // The stylesheet lays three out in three columns on a wide screen; a phone keeps its two.
    const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
    assert.match(css, /@media \(min-width: 721px\) \{ \.detail #figs\.measure\[data-cols="3"\] \{ grid-template-columns: repeat\(3, minmax\(0, 1fr\)\); \} \}/);
  });
}
