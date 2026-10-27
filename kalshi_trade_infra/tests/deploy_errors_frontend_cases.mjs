// Shared cases, run against each bundle's offline harness (Tau and Meridian): the Deploy page when things
// go wrong, and how it reads.
// - A Pause, Resume or Remove Tau didn't confirm (the edge's 502/504 page, or no reply) says it may have
//   gone through and where to check (the row), never "Reload the page"; the board reads again at once
//   (a read), and the action itself is sent once, never again on its own. Tau's own words stay as said.
// - A press while the phone says it is offline sends nothing and says so.
// - The strategy page's Deploy on paper, its Stop deployment, and bulk deploy say the same about Deploy.
// - The paper-net phrase is said once, where it explains a paper figure: the headline, not every row.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const edge = (status) => ({ok: false, status, json: async () => { throw new SyntaxError('not JSON'); }});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const PAPER_NET = 'after Kalshi fees and the spread', PAPER_NET_SHORT = 'net of fees and spread';
const ROW = 'This deployment’s row shows what Tau has and reads again within 10 seconds; check it before you press again.';
const UNSURE = {
  pause: 'Tau didn’t confirm the pause, so it may or may not have gone through. ' + ROW,
  resume: 'Tau didn’t confirm the resume, so it may or may not have gone through. ' + ROW,
  stop: 'Tau didn’t confirm the removal, so it may or may not have gone through. If it did, the deployment leaves this list within 10 seconds; check before you press again.',
};
const DEPLOY_UNSURE = 'Tau didn’t confirm the deploy, so it may or may not have gone through. If it did, it shows on Deploy within a few seconds; check there before you deploy again, since a second deploy runs a second copy.';
const NOT_SENT = 'You’re offline, so this wasn’t sent. Try again once you’re back online.';
const dep = (overrides = {}) => ({id: 1, strategy_id: 1, title: 'Dep one', market: 'btc15m', mode: 'paper', status: 'running',
  status_reason: null, realized_pnl: 1, closed_trades: 5, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z',
  curve: [], stake: 5, max_positions: 1, backtest: {out_of_sample: null}, ...overrides});
const count = (text, phrase) => text.split(phrase).length - 1;

export function deployErrorCases({name, frontend, strategyFrontend, detailStrategy, postRequests}) {
  // A board with one deployment whose action answers with `answer` (a response, or a thrown error).
  const board = async ({status = 'running', answer, globals = {}}) => {
    let reads = 0;
    const f = frontend({globals, fetchImpl: (path) => {
      if (path === '/api/deployments' || path.startsWith('/api/deployments?')) { reads++; return response({deployments: [dep({status})], open_positions: []}); }
      if (/^\/api\/deployments\/1\/(pause|resume|stop)$/.test(path)) return answer();
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    return {f, reads: () => reads};
  };
  const press = async (f, act) => {
    const btn = f.root.querySelector(`#deps [data-dep="1"][data-act="${act}"]`);
    btn.onclick();
    if (act === 'stop') { f.elapse(500); btn.onclick(); }  // Remove's armed confirm, then the send
    for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }  // the board's read retries, if any
    await settle();
  };
  const flashOf = (f) => f.root.querySelector('#flash').innerHTML;
  const sends = (f, act) => postRequests(f).filter((r) => r.path === `/api/deployments/1/${act}`);

  for (const [act, status] of [['pause', 'running'], ['resume', 'paused'], ['stop', 'running']]) {
    test(`${name}: a ${act} on Deploy that Tau didn't confirm says it may have gone through and to check the row`, async () => {
      for (const [how, answer] of [['502', () => edge(502)], ['504', () => edge(504)], ['dropped', () => { throw new TypeError('Failed to fetch'); }]]) {
        const {f, reads} = await board({status, answer});
        const before = reads();
        await press(f, act);
        const flash = flashOf(f);
        assert.match(flash, /notice bad/, how);
        assert.ok(flash.includes(UNSURE[act]), `${how}: ${flash}`);
        assert.doesNotMatch(flash, /Reload the page/, how);
        assert.equal(sends(f, act).length, 1, `${how}: sent once, never again on its own`);
        assert.equal(sends(f, act)[0].options.signal, undefined, `${how}: no deadline on the write`);
        assert.ok(reads() > before, `${how}: the board reads again at once, so the row shows what Tau has`);
        // The row says it too: on a phone the notice at the top of the board is a screen or more away.
        const said = f.root.querySelector('#deps').querySelectorAll('.dep-said');
        assert.deepEqual(said.map((n) => n.textContent), [UNSURE[act]], how);
        const again = f.root.querySelector(`#deps [data-dep="1"][data-act="${act}"]`);
        assert.equal(again.disabled, false, `${how}: the button is free again`);
        assert.ok(!again.classList.contains('busy'), how);
        f.clearTimers();
      }
    });
  }

  test(`${name}: a failed action's word stays on its row through the poll's repaints, and goes once the row moves on`, async () => {
    let paused = false, reads = 0, sent = 0;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments' || path.startsWith('/api/deployments?')) {
        reads++;  // a trade closed between reads, so each read repaints the board
        return response({deployments: [dep({status: paused ? 'paused' : 'running', closed_trades: 5 + reads}), dep({id: 2, strategy_id: 2, title: 'Dep two'})], open_positions: []});
      }
      if (path === '/api/deployments/1/pause') { sent++; if (sent === 1) { paused = false; return edge(502); } paused = true; return response({ok: true}); }
      return response({});
    }});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    await press(f, 'pause');
    const notes = () => f.root.querySelector('#deps').querySelectorAll('.dep-said').map((n) => n.textContent);
    assert.deepEqual(notes(), [UNSURE.pause]);
    for (const tick of [...f.intervals.values()]) await tick();
    await settle();
    assert.deepEqual(notes(), [UNSURE.pause], 'kept through the poll that repainted the board');
    assert.equal(f.root.querySelector('#deps [data-dep="2"]').closest('tr') && f.root.querySelector('#deps [data-dep="2"]').closest('tr').innerHTML.includes('dep-said'), false, 'only on its own row');
    // The next press clears it; once the pause lands the row offers Resume, and no note is left.
    await press(f, 'pause');
    assert.equal(sent, 2);
    assert.deepEqual(notes(), []);
    assert.ok(f.root.querySelector('#deps [data-dep="1"][data-act="resume"]'));
    f.clearTimers();
  });

  test(`${name}: a Deploy action Tau refused in its own words still says them, with no re-read`, async () => {
    const {f, reads} = await board({answer: () => response({error: 'Tau is restarting. Try again in a minute.'}, 503)});
    const before = reads();
    await press(f, 'pause');
    assert.match(flashOf(f), /Tau is restarting\. Try again in a minute\./);
    assert.doesNotMatch(flashOf(f), /may or may not/);
    assert.equal(reads(), before);
    f.clearTimers();
  });

  test(`${name}: a Deploy action pressed while offline sends nothing and says it wasn't sent`, async () => {
    const nav = {onLine: true};
    const {f} = await board({answer: () => response({ok: true}), globals: {navigator: nav}});
    nav.onLine = false;
    await press(f, 'pause');
    await press(f, 'stop');
    assert.equal(postRequests(f).length, 0);
    assert.ok(flashOf(f).includes(NOT_SENT));
    // Back online: the same press goes, once.
    nav.onLine = true;
    await press(f, 'pause');
    assert.equal(sends(f, 'pause').length, 1);
    f.clearTimers();
  });

  test(`${name}: Deploy on paper that Tau didn't confirm says to check Deploy before deploying again`, async () => {
    for (const answer of [() => edge(502), () => { throw new TypeError('Failed to fetch'); }]) {
      const f = strategyFrontend(detailStrategy({status: 'passed'}), (path) => (path === '/api/deployments' ? answer() : response({})));
      await f.viewStrategy(42); await settle();
      const btn = f.root.querySelector('#dep-paper');
      await btn.onclick(); await settle();
      const said = f.root.querySelector('#depflash').innerHTML;
      assert.ok(said.includes(DEPLOY_UNSURE), said);
      assert.doesNotMatch(said, /Reload the page/);
      assert.equal(postRequests(f).filter((r) => r.path === '/api/deployments').length, 1, 'sent once');
      assert.equal(btn.disabled, false);
      assert.equal(f.location.pathname === '/deploy', false, 'stays on the strategy page');
      f.clearTimers();
    }
    // A refusal in Tau's own words is kept.
    const g = strategyFrontend(detailStrategy({status: 'passed'}), (path) => (path === '/api/deployments' ? response({error: 'Add a payment method first.'}, 400) : response({})));
    await g.viewStrategy(42); await settle();
    await g.root.querySelector('#dep-paper').onclick(); await settle();
    assert.match(g.root.querySelector('#depflash').innerHTML, /Add a payment method first\./);
    g.clearTimers();
  });

  test(`${name}: Deploy on paper pressed while offline sends nothing and says so`, async () => {
    const detail = detailStrategy({status: 'passed'});
    const f = frontend({globals: {navigator: {onLine: false}}, fetchImpl: (path) => {
      if (path === '/api/strategies/42') return response(detail);
      if (path === '/api/strategies/42/dev-curve') return response({dev_curve: []});
      return response({});
    }});
    await f.viewStrategy(42); await settle();
    await f.root.querySelector('#dep-paper').onclick(); await settle();
    assert.equal(postRequests(f).filter((r) => r.path === '/api/deployments').length, 0);
    assert.ok(f.root.querySelector('#depflash').innerHTML.includes(NOT_SENT));
    f.clearTimers();
  });

  test(`${name}: the strategy page's Stop deployment that Tau didn't confirm says to check Deploy`, async () => {
    const f = strategyFrontend(detailStrategy({deployments: [{id: 5, mode: 'paper', status: 'running'}]}),
      (path) => (path === '/api/deployments/5/stop' ? edge(502) : response({})));
    await f.viewStrategy(42); await settle();
    const stop = f.root.querySelector('#stop-dep');
    stop.onclick(); f.elapse(500); await stop.onclick(); await settle();
    const said = f.root.querySelector('#delflash').innerHTML;
    assert.match(said, /Tau didn’t confirm the stop, so it may or may not have gone through\. Deploy shows whether it is still running; check there before you press again\./);
    assert.equal(postRequests(f).length, 1);
    f.clearTimers();
  });

  // The paper-net phrase: once on the board, beside the paper figure it explains. A row said it in its
  // sizing line and again in its backtest line, under a headline that already said it.
  const deploys = async (body) => {
    const f = frontend({fetchImpl: (path) => (path === '/api/deployments' ? response({open_positions: [], ...body}) : response({}))});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle(); f.clearTimers();
    const rows = f.root.querySelector('#deps').innerHTML;
    return {figs: f.root.querySelector('#dfigs').innerHTML, rows,
      row: (id) => rows.split('<tr').find((r) => r.includes(`data-dep="${id}"`))};
  };
  const btLine = `Ahead of its backtest on paper: 20 trades across all its paper runs: +$0.40/trade ${PAPER_NET_SHORT} vs backtest +$0.15/trade. Above the usual range for 20 trades (+$0.20 to +$0.30).`;

  test(`${name}: Deploy says the paper P&L is net of fees and the spread once, in the headline, not on every row`, async () => {
    const paper = await deploys({deployments: [dep({id: 1}), dep({id: 2, strategy_id: 2, title: 'Dep two', closed_trades: 20,
      backtest_check: {mode: 'paper', verdict: 'ahead', line: btLine}}), dep({id: 3, strategy_id: 3, title: 'Dep three', mode: 'demo'})]});
    assert.equal(count(paper.figs, PAPER_NET), 1, 'the headline paper figure says it once');
    assert.equal(count(paper.rows, PAPER_NET), 0, 'no row repeats it');
    assert.equal(count(paper.row(1), PAPER_NET_SHORT), 0);
    // A row's backtest line says it beside its own per-trade paper figure, once.
    assert.equal(count(paper.row(2), PAPER_NET_SHORT), 1);
    assert.equal(count(paper.row(3), PAPER_NET_SHORT) + count(paper.row(3), PAPER_NET), 0, 'demo says nothing of the kind');
    // A board led by live money says it beside the paper amount it names, once; live money never gets it.
    const live = await deploys({deployments: [dep({id: 1, mode: 'live', realized_pnl: 2}), dep({id: 2, strategy_id: 2, title: 'Dep two', realized_pnl: 40})]});
    assert.match(live.figs, /real money · after Kalshi fees · \+\$40\.00 on paper from the deployments listed, counted apart, after Kalshi fees and the spread/);
    assert.equal(count(live.figs, PAPER_NET), 1);
    assert.equal(count(live.rows, PAPER_NET), 0);
  });

  test(`${name}: Deploy's open positions figure keeps each dot with the book before it, so a wrapped line never starts with one`, async () => {
    const pos = (mode) => ({title: 'Dep', ticker: 'KXBTC15M-26OCT271315-15', side: 'yes', qty: 1, entry_price: 0.4, entry_fee: 0.01, mode, unrealized: null,
      market_close_time: '2026-10-28T07:45:00Z'});
    const {figs} = await deploys({deployments: [dep(), dep({id: 2, strategy_id: 2, mode: 'demo'}), dep({id: 3, strategy_id: 3, mode: 'live'})],
      open_positions: [pos('paper'), pos('paper'), pos('demo')]});
    const shown = figs.match(/Open positions<\/dt><dd><span class="fig ">([^<]*)<\/span>/)[1];
    assert.equal(shown, '2 paper · 1 demo · 0 live');
  });
}
