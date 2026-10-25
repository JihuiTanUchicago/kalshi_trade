// Shared cases run against each bundle's established offline DOM/transport harness.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));

export function perpsFrontendCases({name, frontend, detailStrategy, strategyFrontend, postRequests}) {
  const detail = overrides => detailStrategy({
    market: 'btc_perp', kind: 'perpetual', research_only: true,
    dataset: {start: '2026-10-01', end: '2026-10-17', out_of_sample_from: '2026-10-12'},
    recent_trades: [{opened: '2026-10-17T10:00Z', ticker: 'SYNTHBTC', side: 'long', qty: '1.25',
      entry: '7.123456', exit: '7.56789', reason: 'window_end', pnl: .5}],
    ...overrides,
  });
  const noExecution = f => {
    for (const id of ['dep-paper', 'dep-demo', 'dep-live', 'live-confirm', 'whatif', 'stop-dep']) {
      assert.equal(f.root.querySelector('#' + id), null, id + ' must be absent');
    }
    assert.equal(f.requests.some(({path}) => /dev-curve|whatif/.test(path)), false);
    assert.equal(postRequests(f).length, 0);
  };

  test(`${name}: return on capital names the capital only when the result has one`, async () => {
    const figs = async (extra) => {
      const f = strategyFrontend(detailStrategy({market: 'btc15m', kind: undefined, research_only: false, ...extra}));
      await f.viewStrategy(42); await flush();
      const el = f.root.querySelector('#figs') || f.root.querySelector('main');
      return el.innerHTML;
    };
    assert.doesNotMatch(await figs({}), /\$0 at risk/);
    assert.match(await figs({capital: 100}), /\$100 at risk at most/);
  });

  test(`${name}: passed perpetual detail is research only with USD prices and fixed scenario costs`, async () => {
    const input = detail(), before = JSON.stringify(input);
    const f = strategyFrontend(input); await f.viewStrategy(42); await flush();
    const output = f.root.querySelector('main').innerHTML;
    for (const label of ['Research only', 'Perpetual research scenario', 'Entry (USD)', 'Exit (USD)',
      '$7.123456', '$7.56789', 'fixed 12 bps', '5 bps adverse slippage per fill', 'settled funding',
      'uncalibrated cost assumptions', 'Short losses can exceed capital']) assert.ok(output.includes(label), label);
    assert.doesNotMatch(output, /Kalshi demo replay|Kalshi dev \(real\)|Every simulated fill pays the ask or bid|They can deploy it like their own|¢/);
    assert.match(output, /research-only copy/); assert.match(output, /cannot be deployed/);
    assert.equal(JSON.stringify(input), before);
    noExecution(f);
  });

  test(`${name}: native market fallback and server kind both block deployment for every saved status`, async () => {
    for (const identity of [
      {market: 'btc_perp', kind: undefined, research_only: false},
      {market: 'native_bitcoin', kind: 'perpetual', research_only: undefined},
    ]) for (const status of ['passed', 'failed', 'rejected', 'backtest-only']) {
      const f = strategyFrontend(detail({...identity, status, experiment: null, deployed: true,
        deployments: [{id: 1, mode: 'live', status: 'running'}],
        holdings: [{ticker: 'SYNTHBTC', side: 'long', qty: 1, entry_price: 7, mode: 'live'}]}));
      await f.viewStrategy(42); await flush();
      assert.match(f.root.querySelector('main').innerHTML, /Research only/);
      assert.doesNotMatch(f.root.querySelector('main').innerHTML, /Holding right now|Already deployed:|View deployments|Deploying it is your decision/);
      noExecution(f);
    }
  });

  test(`${name}: an explicit research-only server flag hides all deployment controls`, async () => {
    const f = strategyFrontend(detailStrategy({research_only: true}));
    await f.viewStrategy(42);
    for (const id of ['dep-paper', 'dep-demo', 'dep-live', 'live-confirm']) assert.equal(f.root.querySelector('#' + id), null);
    assert.match(f.root.querySelector('main').innerHTML, /Research only/);
  });

  test(`${name}: mixed bulk selection deploys only the eligible binary strategy`, async () => {
    const list = [detail(), detailStrategy({id: 43, title: 'Binary fixture'})];
    const f = frontend({fetchImpl: (path, options) => {
      if (path.startsWith('/api/strategies?')) return response({counts: {total: 2, passed: 2}, matched: 2, pages: 1, strategies: list});
      if (path === '/api/deployments') return response(options.method === 'POST' ? {id: 9} : {deployments: [], open_positions: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewStrategies(); await flush();
    assert.match(f.root.querySelector('#slips').innerHTML, /Research only/);
    const picks = f.root.querySelectorAll('.pick');
    assert.equal(picks.length, 1); assert.equal(picks[0].dataset.id, '43');
    const all = f.root.querySelector('#pick-all'); all.checked = true; all.onclick();
    assert.equal(picks[0].checked, true);
    const deploy = f.root.querySelector('#bulk-dep'); await deploy.onclick({target: deploy}); await flush();
    assert.deepEqual(postRequests(f).map(({path, options}) => [path, JSON.parse(options.body)]),
      [['/api/deployments', {strategy_id: 43, mode: 'paper'}]]);
  });

  test(`${name}: the strategy page shows what it has done since deploying, per mode`, async () => {
    const deployments = [
      {id: 1, mode: 'paper', status: 'stopped', realized_pnl: 2.5, closed_trades: 4, open_positions: 0, created_at: '2026-10-20T08:00:00Z'},
      {id: 2, mode: 'paper', status: 'running', realized_pnl: -1.25, closed_trades: 3, open_positions: 2, created_at: '2026-10-24T08:00:00Z'},
      {id: 3, mode: 'demo', status: 'running', realized_pnl: 0, closed_trades: 0, open_positions: 0, created_at: '2026-10-25T08:00:00Z'},
    ];
    const f = strategyFrontend(detailStrategy({deployments}));
    await f.viewStrategy(42); await flush();
    const html = f.root.querySelector('main').innerHTML;
    assert.match(html, /Since deploying/);
    assert.match(html, /Paper<\/span> <span class="[^"]*">\+\$1\.25<\/span> realized over 7 closed trades · 2 open/);
    assert.match(html, /Demo<\/span> No closed trades yet/);
    assert.ok(html.indexOf('>Demo<') < html.indexOf('>Paper<'), 'demo before paper');
    // Unseen-data backtest: +$12 over 6 trades at a $5 stake = $2 a trade, so 7 paper trades -> +$14.
    assert.match(html, /backtest's unseen-data pace, 7 trades would have made \+\$14\.00 · too few trades to judge yet/);
    assert.equal((html.match(/real-pace/g) || []).length, 1, 'no pace line for a mode with no closed trades');
    // Scaled to each deployment's own stake: 10 trades at $10 a trade -> 10 x $2 x 2 = +$40, enough to judge.
    const big = strategyFrontend(detailStrategy({deployments: [{id: 4, mode: 'live', status: 'running', realized_pnl: 30, closed_trades: 10, open_positions: 0, stake: 10}]}));
    await big.viewStrategy(42); await flush();
    const bigHtml = big.root.querySelector('main').innerHTML;
    assert.match(bigHtml, /10 trades would have made \+\$40\.00<\/p>/);
    assert.doesNotMatch(html, /real-paused/);
    const paused = strategyFrontend(detailStrategy({deployments: [{id: 5, mode: 'paper', status: 'paused', status_reason: 'Lost $12.00, more than the <guard>.', realized_pnl: -12, closed_trades: 9, open_positions: 0}]}));
    await paused.viewStrategy(42); await flush();
    assert.match(paused.root.querySelector('main').innerHTML, /<b>Paused<\/b> Lost \$12\.00, more than the &lt;guard&gt;\. <a href="\/deploy">Resume or remove it on Deploy<\/a>/);
    const untested = strategyFrontend(detailStrategy({out_of_sample: null, deployments}));
    await untested.viewStrategy(42); await flush();
    assert.doesNotMatch(untested.root.querySelector('main').innerHTML, /real-pace/);
    const none = strategyFrontend(detailStrategy({deployments: []}));
    await none.viewStrategy(42); await flush();
    assert.doesNotMatch(none.root.querySelector('main').innerHTML, /Since deploying/);
  });

  test(`${name}: bulk selection skips a strategy that is already deployed`, async () => {
    const list = [detailStrategy({id: 44, title: 'Running fixture', deployed: true}), detailStrategy({id: 45, title: 'Idle fixture'})];
    const f = frontend({fetchImpl: path => {
      assert.ok(path.startsWith('/api/strategies?'));
      return response({counts: {total: 2, passed: 2}, matched: 2, pages: 1, strategies: list});
    }});
    await f.viewStrategies(); await flush();
    const picks = f.root.querySelectorAll('.pick');
    assert.equal(picks.length, 1); assert.equal(picks[0].dataset.id, '45');
    list[1].deployed = true;  // every strategy on the page running: no selection column at all
    assert.doesNotMatch(f.strategySlip(list[0], null, {pick: true}), /Select for deployment/);
  });

  test(`${name}: a deployed strategy row shows its real P&L beside the backtest`, async () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = s => f.strategySlip(detailStrategy({id: 46, title: 'Row fixture', ...s}), null, {});
    assert.match(row({deployed: true, real: {pnl: 1.67, trades: 5, open: 1}}), /\+\$1\.67<\/span> since deploying · 5 trades/);
    assert.match(row({deployed: true, real: {pnl: 0, trades: 1, open: 0}}), /since deploying · 1 trade</);
    assert.match(row({deployed: true, real: {pnl: 0, trades: 0, open: 2}}), /No closed trades yet/);
    assert.doesNotMatch(row({}), /real-fig/);
    assert.match(row({deployed: true, real: {pnl: -12, trades: 9, open: 0, paused: true}}), /Deployed<\/span> <span class="mk armed">Paused<\/span>/);
    assert.doesNotMatch(row({deployed: true, real: {pnl: 1, trades: 1, open: 0, paused: false}}), />Paused</);
    // A research-only perpetual never shows a real record, even if one leaks in.
    assert.doesNotMatch(f.strategySlip(detail({deployed: true, real: {pnl: 3, trades: 2, open: 0}}), null, {}), /real-fig/);
  });

  test(`${name}: a strategy row keeps its demo (sandbox) book beside paper, never added in`, async () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = real => f.strategySlip(detailStrategy({id: 48, title: 'Books fixture', deployed: true, real}), null, {});
    const both = row({pnl: 1, trades: 3, open: 1, mode: 'paper', demo: {pnl: -0.5, trades: 2, open: 0}});
    assert.match(both, /\+\$1\.00<\/span> since deploying · 3 trades/);
    assert.match(both, /Demo: <span class="[^"]*">−\$0\.50<\/span> · 2 trades/);
    assert.doesNotMatch(both, /\$0\.50<\/span> since deploying/);
    assert.match(row({pnl: 2, trades: 1, open: 0, mode: 'demo'}), /\+\$2\.00<\/span> on demo since deploying · 1 trade</);
    assert.match(row({pnl: 0, trades: 0, open: 1, mode: 'demo'}), /No closed demo trades yet/);
    assert.match(row({pnl: 0, trades: 0, open: 1, mode: 'paper', demo: {pnl: 0, trades: 0, open: 1}}), /Demo: no closed trades yet/);
  });

  test(`${name}: the demo track record says it is real sandbox fills that a reload doesn't reset`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const m = {trades: 3, wins: 2, losses: 1, label: 'Kalshi demo', net_pnl: 4, fees: 0.2, monthly: [], strategies: [], curve: [],
      sample: {level: 'thin', edge: 'unclear', text: 'Too early to judge.'}};
    const th = {min_sharpe_days: 14, min_trades: 30};
    const demo = f.trackRecordPanel(m, 'demo', th);
    assert.match(demo, /real fills on Kalshi’s sandbox exchange with simulated money/);
    assert.match(demo, /Reloading the demo account doesn’t reset this record/);
    assert.doesNotMatch(f.trackRecordPanel({...m, label: 'Paper'}, 'paper', th), /sandbox/);
  });

  test(`${name}: the Deploy board never adds paper dollars to real ones`, async () => {
    const dep = (id, mode, pnl) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode, status: 'running', status_reason: null,
      realized_pnl: pnl, closed_trades: 1, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1, backtest: {}});
    const board = async deployments => {
      const f = frontend({fetchImpl: path => {
        if (path === '/api/deployments') return response({deployments, open_positions: []});
        return response({});
      }});
      await f.viewDeploy(); await flush(); await flush();
      return f.root.querySelector('#dfigs').innerHTML;
    };
    const mixed = await board([dep(1, 'live', 2), dep(2, 'paper', 40), dep(3, 'demo', -10)]);
    assert.match(mixed, /Live realized/); assert.match(mixed, /\+\$2\.00/);
    // Live, paper and demo each get their own figure: no $30 (paper + demo) and no $32 (all three).
    assert.match(mixed, /\+\$40\.00 on paper, counted apart/);
    assert.match(mixed, /Demo realized[\s\S]*−\$10\.00[\s\S]*real fills on Kalshi’s sandbox, not real money/);
    assert.doesNotMatch(mixed, /\$30|\$32|paper and demo/);
    const practice = await board([dep(2, 'paper', 40), dep(3, 'demo', -10)]);
    assert.match(practice, /\+\$40\.00[\s\S]*paper money, not real/); assert.match(practice, /Demo realized[\s\S]*−\$10\.00/);
    assert.doesNotMatch(practice, /\$30/);
    assert.match(practice, /<span class="mk">Paper<\/span> <span class="mk dep">Demo<\/span>/);
    const demoOnly = await board([dep(3, 'demo', -10)]);
    assert.match(demoOnly, /Demo realized/); assert.doesNotMatch(demoOnly, /paper money/);
    assert.match(demoOnly, /<span class="mk dep">Demo<\/span>/); assert.doesNotMatch(demoOnly, /mk">Paper/);
    const paper = await board([dep(2, 'paper', 40)]);
    assert.match(paper, /Realized/); assert.doesNotMatch(paper, /Live realized/); assert.match(paper, /paper money, not real/);
  });

  test(`${name}: Deploy lists paused deployments first, otherwise in server order`, async () => {
    const dep = (id, status) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode: 'paper', status, status_reason: status === 'paused' ? 'loss guard' : null,
      realized_pnl: 0, closed_trades: 0, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1, backtest: {}});
    const deployments = [dep(1, 'running'), dep(2, 'running'), dep(3, 'paused'), dep(4, 'running')];
    const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments, open_positions: []}) : response({})});
    await f.viewDeploy(); await flush(); await flush();
    const order = [...f.root.querySelector('#deps').innerHTML.matchAll(/href="\/strategies\/(\d+)"/g)].map(m => m[1]).filter((v, i, a) => a.indexOf(v) === i);
    assert.deepEqual(order, ['3', '1', '2', '4']);
    assert.deepEqual(deployments.map(d => d.id), [1, 2, 3, 4]);  // the API payload itself is untouched
  });

  test(`${name}: the Deployed chip counts strategies with an active deployment`, async () => {
    const f = frontend({fetchImpl: () => response({counts: {total: 3, passed: 3, deployed: 2}, matched: 3, pages: 1, strategies: [detailStrategy({id: 48})]})});
    await f.viewStrategies(); await flush();
    assert.equal(f.root.querySelector('[data-toggle="deployed"]').textContent, 'Deployed (2)');
  });

  test(`${name}: an empty Deploy board with autopilot on says passed strategies deploy on their own`, async () => {
    for (const on of [true, false]) {
      const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [], open_positions: []}) : response({})});
      f.S.me.user.autopilot = on;
      await f.viewDeploy(); await flush(); await flush();
      assert.equal(/deploy here on their own/.test(f.root.querySelector('#deps').innerHTML), on);
    }
  });

  test(`${name}: an empty strategy list with autopilot on says it is on, not "start a session"`, async () => {
    for (const [on, total] of [[true, 2], [false, 2], [true, 0], [false, 0]]) {
      const f = frontend({fetchImpl: () => response({counts: {total, passed: 0, rejected: total}, matched: 0, pages: 1, strategies: []})});
      f.S.me.user.autopilot = on;
      await f.viewStrategies(); await flush();
      const html = f.root.querySelector('#slips').innerHTML;
      assert.equal(/See its research/.test(html), on, `autopilot ${on}, ${total} strategies`);
      assert.equal(/Autopilot (keeps researching|is on\. The strategies it finds will land here)/.test(html), on);
      // Not "is researching": the autopilot panel may be reporting a stale check-in or a billing pause.
      assert.doesNotMatch(html, /is researching/);
      if (!on) assert.match(html, /Go to Research|New session/);
    }
  });

  test(`${name}: a failed strategies load offers a retry instead of a stuck skeleton`, async () => {
    let down = true;
    const f = frontend({fetchImpl: path => {
      assert.ok(path.startsWith('/api/strategies?'));
      if (down) return response({error: 'Tau is restarting. Try again in a moment.'}, 502);
      return response({counts: {total: 1, passed: 1}, matched: 1, pages: 1, strategies: [detailStrategy({id: 47, title: 'Back fixture'})]});
    }});
    await f.viewStrategies(); await flush();
    const slips = f.root.querySelector('#slips');
    assert.match(slips.innerHTML, /Tau is restarting/); assert.match(slips.innerHTML, /Try again/);
    down = false; await slips.querySelector('[data-retry]').onclick(); await flush();
    assert.match(f.root.querySelector('#slips').innerHTML, /Back fixture/);
    assert.doesNotMatch(f.root.querySelector('#slips').innerHTML, /Try again/);
  });

  test(`${name}: a perpetual-only inventory has no bulk selection or false live status`, async () => {
    const list = [detail({deployed: true, deploy_live: true})];
    const f = frontend({fetchImpl: path => {
      assert.ok(path.startsWith('/api/strategies?'));
      return response({counts: {total: 1, passed: 1}, matched: 1, pages: 1, strategies: list});
    }});
    await f.viewStrategies(); await flush();
    assert.equal(f.root.querySelector('#pick-all'), null); assert.equal(f.root.querySelector('.pick'), null);
    assert.equal(f.root.querySelector('#bulkbar').hidden, true);
    const output = f.strategySlip(list[0], null, {pick: true});
    assert.match(output, /Research only/); assert.doesNotMatch(output, /Select for deployment|>Live<|>Deployed</);
    assert.equal(postRequests(f).length, 0);
  });

  test(`${name}: malformed or missing perpetual prices stay unknown rather than displaying zero`, async () => {
    for (const value of [null, undefined, '', '   ', 'bad', true, []]) {
      const input = detail(); input.recent_trades[0].entry = value; input.recent_trades[0].exit = value;
      const f = strategyFrontend(input); await f.viewStrategy(42);
      const cells = f.root.querySelector('table.table.stack tbody tr').querySelectorAll('td.num');
      assert.equal(cells[0].textContent, '—'); assert.match(cells[1].textContent, /^—/);
      assert.doesNotMatch(f.root.querySelector('main').innerHTML, /NaN|undefined/);
    }
  });

  test(`${name}: a refused detail read cannot expose controls or trigger demo data`, async () => {
    const f = frontend({fetchImpl: path => {
      assert.equal(path, '/api/strategies/42');
      return response({error: 'Native perpetual source unavailable'}, 503);
    }});
    await assert.rejects(f.viewStrategy(42), /Native perpetual source unavailable/);
    noExecution(f);
  });

  test(`${name}: rejected sharing preserves research limits and escapes the error`, async () => {
    const f = strategyFrontend(detail(), (path, options) => {
      assert.equal(path, '/api/strategies/42/share');
      assert.deepEqual(JSON.parse(options.body), {email: 'fixture@example.invalid'});
      return response({error: '<unsafe> synthetic share refusal'}, 403);
    });
    await f.viewStrategy(42);
    const form = f.root.querySelector('#share-form'); form.onsubmit({preventDefault() {}}); await flush();
    assert.equal(postRequests(f).length, 0); assert.match(f.root.querySelector('#shareflash').innerHTML, /Enter an email first/);
    f.root.querySelector('#share-email').value = 'fixture@example.invalid';
    form.onsubmit({preventDefault() {}}); await flush();
    assert.equal(postRequests(f).length, 1);
    assert.match(f.root.querySelector('#shareflash').innerHTML, /&lt;unsafe&gt; synthetic share refusal/);
    assert.doesNotMatch(f.root.querySelector('#shareflash').innerHTML, /<unsafe>/);
    assert.equal(f.root.querySelector('#dep-paper'), null);
    assert.match(f.root.querySelector('main').innerHTML, /research-only copy/);
  });

  test(`${name}: research picker and shared snapshots carry the perpetual restriction`, () => {
    const f = frontend();
    const markets = [{key: 'btc_perp', category: 'Crypto', has_data: false},
      {key: 'btc15m', category: 'Crypto', has_data: true}];
    f.root.innerHTML = f.marketPicker(markets);
    assert.match(f.root.querySelector('[data-key="btc_perp"]').innerHTML, /Research only/);
    assert.doesNotMatch(f.root.querySelector('[data-key="btc15m"]').innerHTML, /Research only/);
    const snapshot = f.postSnapshot({kind: 'strategy', id: 42, title: '<unsafe>', market: 'btc_perp', status: 'passed'});
    assert.match(snapshot, /Research only/); assert.match(snapshot, /&lt;unsafe&gt;/);
    assert.doesNotMatch(snapshot, /<unsafe>|NaN|undefined/);
  });
}
