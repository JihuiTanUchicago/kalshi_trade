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
    assert.match(html, /Paper<\/span> <span class="[^"]*">\+\$1\.25<\/span> realized over 7 closed trades ·\u00a02 open/);
    assert.match(html, /Demo<\/span> No closed trades yet/);
    assert.ok(html.indexOf('>Demo<') < html.indexOf('>Paper<'), 'demo before paper');
    // Unseen-data backtest: +$12 over 6 trades at a $5 stake = $2 a trade, so 7 paper trades -> +$14.
    assert.match(html, /backtest's unseen-data pace, 7 trades would have made \+\$14\.00 ·\u00a0too few trades to judge yet/);
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
    assert.match(row({deployed: true, real: {pnl: 1.67, trades: 5, open: 1}}), /\+\$1\.67<\/span> since deploying ·\u00a05 trades/);
    assert.match(row({deployed: true, real: {pnl: 0, trades: 1, open: 0}}), /since deploying ·\u00a01 trade</);
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
    assert.match(both, /\+\$1\.00<\/span> since deploying ·\u00a03 trades/);
    assert.match(both, /Demo: <span class="[^"]*">−\$0\.50<\/span> ·\u00a02 trades/);
    assert.doesNotMatch(both, /\$0\.50<\/span> since deploying/);
    assert.match(row({pnl: 2, trades: 1, open: 0, mode: 'demo'}), /\+\$2\.00<\/span> on demo since deploying ·\u00a01 trade</);
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
    assert.doesNotMatch(f.trackRecordPanel({...m, label: 'Paper'}, 'paper', th), /sandbox|trades Tau placed/);
    // The live tab is Tau's own book, which Kalshi cash is not.
    const live = f.trackRecordPanel({...m, label: 'Live money'}, 'live', th);
    assert.match(live, /Live results count only the trades Tau placed, net of Kalshi fees\. Your Kalshi cash also moves with deposits/);
    assert.doesNotMatch(live, /sandbox/);
  });

  test(`${name}: a thinned track record curve says how it was drawn, a full one says one point per trade`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const th = {min_sharpe_days: 14, min_trades: 30};
    const m = (trades, points) => ({trades, wins: trades, losses: 0, label: 'Paper', net_pnl: trades, fees: 0, monthly: [], strategies: [],
      curve: Array.from({length: points}, (_, i) => [1760000000 + i * 3600, i + 1]), sample: {level: 'solid', edge: 'positive', text: 'Solid.'}});
    assert.match(f.trackRecordPanel(m(50, 50), 'paper', th), /Cumulative net P&amp;L, one point per closed trade\./);
    const thinned = f.trackRecordPanel(m(5000, 400), 'paper', th);
    assert.match(thinned, /over all 5,000 trades, drawn from each stretch’s lowest and highest point so no dip is skipped/);
    assert.doesNotMatch(thinned, /one point per closed trade/);
  });

  test(`${name}: a strategy holding on paper, demo and live sums each book apart, never all together`, async () => {
    const h = (mode, cost, unrealized) => ({ticker: 'KXBTC15M-' + mode, side: 'yes', qty: 2, entry_price: 0.4, cost, unrealized, mode,
      market_close_time: '2026-10-25T07:45:00Z'});
    const holdings = [h('paper', 4, 1), h('paper', 2, null), h('demo', 8, -3), h('live', 0.8, 0.2)];
    const f = strategyFrontend(detailStrategy({holdings, deployed: true, deployments: [{id: 1, mode: 'paper', status: 'running'},
      {id: 2, mode: 'demo', status: 'running'}, {id: 3, mode: 'live', status: 'running'}]}));
    await f.viewStrategy(42); await flush();
    const main = f.root.querySelector('main').innerHTML;
    const hint = main.slice(main.indexOf('<p class="hint" style="margin-top:8px">'), main.indexOf('</p>', main.indexOf('<p class="hint" style="margin-top:8px">')));
    assert.match(hint, /Live: 1 open position at cost \$0\.80 ·\u00a0unrealized (?:<span[^>]*>)?\+\$0\.20/);
    assert.match(hint, /Demo: 1 open position at cost \$8\.00 ·\u00a0unrealized (?:<span[^>]*>)?−\$3\.00/);
    assert.match(hint, /Paper: 2 open positions at cost \$6\.00 ·\u00a0unrealized (?:<span[^>]*>)?\+\$1\.00/);
    assert.doesNotMatch(hint, /4 open positions|\$14\.80|−\$1\.80/);  // the cross-book totals it used to print
    f.clearTimers && f.clearTimers();
    // One book alone reads as before, with no label.
    const g = strategyFrontend(detailStrategy({holdings: [h('paper', 4, 1)], deployed: true, deployments: [{id: 1, mode: 'paper', status: 'running'}]}));
    await g.viewStrategy(42); await flush();
    assert.match(g.root.querySelector('main').innerHTML, />1 open position at cost \$4\.00 ·\u00a0unrealized (?:<span[^>]*>)?\+\$1\.00(?:<\/span>)? \(est\./);
    g.clearTimers && g.clearTimers();
  });

  test(`${name}: an open trade that is partly sold says what it already realized outside the record`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const th = {min_sharpe_days: 14, min_trades: 30};
    const m = {trades: 4, wins: 2, losses: 2, label: 'Paper', net_pnl: 3, fees: 0, monthly: [], strategies: [], curve: [],
      open_trades: 1, open_at_cost: 6, open_realized_pnl: -1.66, sample: {level: 'thin', edge: 'unclear', text: 'Too early.'}};
    assert.match(f.trackRecordPanel(m, 'paper', th),
      /1 open trade \(\$6\.00 at cost\) join the record when they close\. Part of it is already sold: −\$1\.66 realized, not yet in these figures\./);
    assert.doesNotMatch(f.trackRecordPanel({...m, open_realized_pnl: 0}, 'paper', th), /already sold/);
  });

  test(`${name}: the track record underwater chart draws the server's drawdown series, not one derived from the thinned curve`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const th = {min_sharpe_days: 14, min_trades: 30};
    // The thinned equity curve lost the $50 peak, so it only ever rises; the server's series has the drop.
    const m = {trades: 5000, wins: 1, losses: 1, label: 'Paper', net_pnl: 100, fees: 0, monthly: [], strategies: [], max_drawdown: 50,
      curve: [[1760000000, 0], [1760003600, 0], [1760007200, 100], [1760010800, 100]],
      underwater: [[1760000000, 0], [1760005400, -50], [1760010800, 0]], sample: {level: 'solid', edge: 'positive', text: 'Solid.'}};
    assert.match(f.trackRecordPanel(m, 'paper', th), /Underwater drawdown plot; worst drawdown −\$50\.00/);
    // An older payload without the series still derives one from the curve.
    assert.match(f.trackRecordPanel({...m, underwater: undefined}, 'paper', th), /Underwater drawdown plot; worst drawdown \$0\.00/);
  });

  test(`${name}: the seeded example's strategies and session say the app ran them for free`, async () => {
    const f = frontend({fetchImpl: path => {
      assert.equal(path, '/api/runs/5?after=0');
      return response({run: {id: 5, prompt: 'Random walk', status: 'succeeded', market: 'btc15m', direction: 'random_walk', example: true,
        hypotheses_tried: 2, strategies_passed: 0, spent_usd: 0, created_at: '2026-10-17T10:00:00Z'}, events: [], strategies: []});
    }});
    const tag = /<span class="mk quiet example-tag" title="An example Tau ran for you when you signed up\. It cost you nothing\.">Example<\/span>/;
    assert.match(f.strategySlip(detailStrategy({id: 49, title: 'Walk', example: true}), null, {}), tag);
    assert.doesNotMatch(f.strategySlip(detailStrategy({id: 50, title: 'Mine'}), null, {}), /example-tag/);
    await f.viewRun(5);
    assert.match(f.root.querySelector('#runboard').innerHTML, /An example Tau ran for you when you signed up\. It cost you nothing\./);
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

  test(`${name}: the Deploy board counts open positions per book, never all together`, async () => {
    const dep = (id, mode) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode, status: 'running', status_reason: null,
      realized_pnl: 0, closed_trades: 0, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1, backtest: {}});
    const pos = (mode) => ({title: 'Dep', ticker: 'KXBTC15M-' + mode, side: 'yes', qty: 1, entry_price: 0.4, entry_fee: 0.01, mode, unrealized: null, market_close_time: '2026-10-25T07:45:00Z'});
    const openFig = async (deployments, open_positions, liveOn) => {
      const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments, open_positions}) : response({})});
      f.S.me.live_trading_available = liveOn;
      await f.viewDeploy(); await flush(); await flush();
      const m = f.root.querySelector('#dfigs').innerHTML.match(/Open positions<\/dt><dd><span class="fig ">([^<]*)<\/span>/);
      f.clearTimers && f.clearTimers();
      assert.ok(m, 'the open positions figure renders');
      // Each book's number and name are joined by a no-break space so a phone never splits them.
      assert.doesNotMatch(m[1], /\d /);
      return m[1].replace(/ /g, ' ');
    };
    const mixed = [pos('paper'), pos('paper'), pos('demo'), pos('paper')];
    assert.equal(await openFig([dep(1, 'paper'), dep(2, 'demo')], mixed, true), '3 paper · 1 demo · 0 live');
    // Live off: a book with nothing open is left out, live too.
    assert.equal(await openFig([dep(1, 'paper'), dep(2, 'demo')], mixed, false), '3 paper · 1 demo');
    assert.equal(await openFig([dep(1, 'paper')], [pos('paper'), pos('live')], false), '1 paper · 1 live');
    // A listed live deployment keeps live in the figure even with the server switch off.
    assert.equal(await openFig([dep(1, 'paper'), dep(3, 'live')], [pos('paper')], false), '1 paper · 0 live');
    assert.equal(await openFig([], [], false), 'None');
    assert.equal(await openFig([], [], true), '0 live');
  });

  test(`${name}: the strategy ladder gives each running book its own line and says what the next rung needs`, async () => {
    const d = (id, mode, closed_trades, realized_pnl, status = 'running') => ({id, mode, status, closed_trades, realized_pnl, open_positions: 0, stake: 5, created_at: '2026-10-20T08:00:00Z'});
    const readiness = {ready: false, blocking: 'it needs 30+ closed paper trades on realistic fills first (has 12)', deployment_candidate: true, live_autopilot: {ok: false},
      paper: {trades: 12, trades_needed: 30, net_pnl: 3.4, events: 12, events_needed: 20, span_hours: 50, span_needed_hours: 48,
        p_value: 0.2, p_value_needed: 0.1, recent_trades: 6, recent_net_pnl: 1, realization: null,
        checks: {realistic_trades: false, net_pnl: true, events: false, span: true, edge: false, recent: true}}};
    const ladder = async (overrides, road, me = {}) => {
      const f = strategyFrontend(detailStrategy(overrides), path => {
        if (path === '/api/strategies/42/live-readiness') return road ? response(road) : response({error: 'down'}, 503);
        return response({});
      });
      Object.assign(f.S.me, me);
      await f.viewStrategy(42); await flush(); await flush();
      const el = f.root.querySelector('#ladder-body');
      f.clearTimers && f.clearTimers();
      return el ? el.innerHTML : null;
    };
    const both = await ladder({deployments: [d(1, 'paper', 12, 3.4), d(2, 'demo', 5, -1.2), d(3, 'paper', 2, 1, 'paused')]}, readiness);
    // Paper's own trades and P&L (the paused paper deployment is still paper's book), demo's apart.
    assert.match(both, /<span class="mk ">Paper<\/span> running ·\u00a014 closed trades ·\u00a0(?:<span[^>]*>)?\+\$4\.40/);
    assert.match(both, /<span class="mk dep">Demo<\/span> running ·\u00a05 closed trades ·\u00a0(?:<span[^>]*>)?−\$1\.20/);
    assert.doesNotMatch(both, /19 closed|\$3\.20|\$5\.60/);  // what a sum across books would read
    assert.match(both, /Next rung, live: blocked because it needs 30\+ closed paper trades on realistic fills first \(has 12\)\./);
    assert.ok(both.indexOf('Paper</span>') < both.indexOf('Demo</span>'), 'books run up the ladder in order');
    // Without Road to live data the live rung is left out, not guessed.
    const noRoad = await ladder({deployments: [d(1, 'paper', 12, 3.4), d(2, 'demo', 5, -1.2)]}, null);
    assert.match(noRoad, /Demo<\/span> running/); assert.doesNotMatch(noRoad, /Next rung/);
    const unvalidated = await ladder({status: 'failed', deployments: [d(2, 'demo', 5, -1.2)]}, readiness);
    assert.doesNotMatch(unvalidated, /Next rung, live/);
    assert.match(await ladder({deployments: [d(2, 'demo', 5, -1.2)]}, {...readiness, ready: true}), /Next rung, live: every gate is clear\./);
    // Paper only: the next rung is demo, and it names the missing demo key.
    assert.match(await ladder({deployments: [d(1, 'paper', 0, 0)]}, readiness, {kalshi_dev_connected: false}),
      /Paper<\/span> running ·\u00a00 closed trades[\s\S]*Next rung, demo: needs your Kalshi demo \(sandbox\) key/);
    assert.match(await ladder({deployments: [d(1, 'paper', 0, 0)]}, readiness), /Next rung, demo: nothing needed/);
    // Nothing running yet; a paused book is not running.
    const idle = await ladder({deployments: [d(1, 'paper', 2, 1, 'paused')]}, readiness);
    assert.doesNotMatch(idle, /running/); assert.match(idle, /Next rung, paper: nothing needed/);
    assert.match(await ladder({deployments: [d(1, 'paper', 1, 1), d(4, 'live', 3, 0.5)]}, readiness), /Live<\/span> running ·\u00a03 closed trades[\s\S]*Top rung: it trades live money\./);
    // Research-only strategies have no ladder at all.
    assert.equal(await ladder({research_only: true, deployments: [d(1, 'paper', 1, 1)]}, readiness), null);
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
