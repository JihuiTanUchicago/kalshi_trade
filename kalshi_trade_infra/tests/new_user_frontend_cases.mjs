// Shared cases, run against each bundle's offline harness (Tau and Meridian): a brand-new customer's first hour,
// walked on 2026-10-27 at 390px and 1280px from sign-up through the first research session, the first paper
// deployment and the first closed paper trade. Each case is a place where the page said something the account
// hadn't done yet, or showed a figure as $0.00 where "None yet" is what is true.
import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));

const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const firstDep = (o = {}) => ({id: 1, strategy_id: 11, title: 'Momentum after sharp moves', market: 'btc15m', mode: 'paper', status: 'running',
  status_reason: null, realized_pnl: 0, closed_trades: 0, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-27T22:05:34Z',
  curve: [], stake: 5, max_positions: 4, backtest: {out_of_sample: {trades: 60, pnl: 0.9}, capital: 10}, ...o});

export function newUserCases({name, frontend, detailStrategy, strategyFrontend, dashboard}) {
  const meridian = name === 'Meridian';

  // The first paper deployment, before its first trade closes. Deploy's summary said "Realized: None yet" above a row
  // reading "$0.00", and the dashboard's card (Meridian's monitor) said "$0.00" too. Once a trade closes it is a figure.
  test(`${name}: a deployment with no closed trade reads "None yet" for its realized P&L, on Deploy and the dashboard`, async () => {
    for (const [d, said] of [[firstDep(), /None yet/], [firstDep({realized_pnl: 5.73, closed_trades: 1}), /\+\$5\.73/]]) {
      const f = frontend({fetchImpl: (path) => {
        if (path === '/api/deployments') return response({deployments: [d], open_positions: []});
        if (path === '/api/dashboard') return response({...dashboard(), deployments: [d]});
        return response({});
      }});
      f.location.pathname = '/deploy';
      await f.viewDeploy(); await settle();
      const cell = f.root.querySelector('#deps td[data-lab="Realized"]').innerHTML;
      assert.match(cell, said); assert.doesNotMatch(cell, d.closed_trades ? /None yet/ : /\$0\.00/);
      f.location.pathname = '/';
      await f.viewDashboard(); await settle();
      const dash = meridian ? f.root.querySelector('.monitor-realized dd').innerHTML : f.root.querySelector('#dash-deps td[data-lab="Realized"]').innerHTML;
      assert.match(dash, said); assert.doesNotMatch(dash, d.closed_trades ? /None yet/ : /\$0\.00/);
    }
  });

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
