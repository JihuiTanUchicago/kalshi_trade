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
