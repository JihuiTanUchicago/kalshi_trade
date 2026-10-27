// Shared cases, run against each bundle's offline harness (Tau and Meridian): the paper book's "after typical
// live slippage" estimate (the server's slippage_estimate, trading_core/domain/slippage.py). Owner, 2026-10-27:
// paper P&L stays exactly as it is, and next to it a clearly labelled estimate. Paper fills buy at the ask and
// sell at the bid and pay Kalshi's fee, but fill at a quote up to 2s old, so they never pay for the price moving
// before a real order lands (0.2-0.55c a contract a fill on Kalshi's books). The estimate rides beside paper
// realized P&L on the dashboard, the strategy page's "Since deploying" and the track record's paper tab: muted,
// never tinted, never in place of a figure, and never on live or demo.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {paperBook as trackBook} from './track_record_trust_frontend_cases.mjs';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const plain = (html) => html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ');
const EST = {pnl: 3.1, per_fill_cents: 0.5};
export const SAID = '≈ +$3.10 after typical live slippage (estimate: 0.5¢ a contract each time an order fills)';
const estSpans = (html) => html.match(/<span class="slip-est">[^<]*<\/span>/g) || [];
const TH = {min_sharpe_days: 14, min_trades: 30};

export function slippageEstimateCases({name, frontend, strategyFrontend, detailStrategy, dashboard}) {
  const board = async (paper, extra = {}) => {
    const base = dashboard();
    const data = {...base, ...extra, paper: {...base.paper, realized_pnl: 3.2, closed_trades: 4, open_positions: 0, ...paper}};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    await f.viewDashboard(); await flush(); await flush();
    return ['#boardbody', '#main'].map((sel) => f.root.querySelector(sel)).filter(Boolean).map((el) => el.innerHTML).join('');
  };

  test(`${name}: the dashboard's paper figure says the estimate beside its realized P&L, muted, which stays as it was`, async () => {
    const html = await board({slippage_estimate: EST});
    const text = plain(html).replace(/ /g, ' ');
    assert.ok(text.includes(SAID), 'the estimate in plain words, with its assumption');
    assert.match(text, /\+\$3\.20/, 'paper realized P&L is still the figure');
    const spans = estSpans(html);
    assert.equal(spans.length, 1);
    // Muted, its own line: no tint class, never inside the figure itself.
    assert.doesNotMatch(spans[0], /tint|pos|neg|gain|loss/);
    assert.doesNotMatch(html, /<span class="fig[^"]*">[^<]*≈/);
    // It reads as an estimate, never as P&L.
    assert.doesNotMatch(spans[0], /P&amp;L|P&L|realized/);
    // Without one (no closed paper trade yet, or an older server), nothing is said.
    assert.equal(estSpans(await board({slippage_estimate: null})).length, 0);
    assert.equal(estSpans(await board({})).length, 0);
  });

  test(`${name}: a paper loss reads as a bigger loss, and live and demo never carry an estimate`, async () => {
    const html = await board({realized_pnl: -1.25, slippage_estimate: {pnl: -1.37, per_fill_cents: 0.5}},
      {demo: {...dashboard().demo, realized_pnl: 4, slippage_estimate: {pnl: 3.9, per_fill_cents: 0.5}},
       live: {...dashboard().live, connected: true, balance: 50, realized_pnl: 7, slippage_estimate: {pnl: 6.9, per_fill_cents: 0.5}}});
    const spans = estSpans(html).map((s) => plain(s).replace(/ /g, ' ').trim());
    assert.deepEqual(spans, ['≈ −$1.37 after typical live slippage (estimate: 0.5¢ a contract each time an order fills)']);
    assert.doesNotMatch(html, /\$6\.90|\$3\.90/, 'live and demo figures are never estimated');
  });

  test(`${name}: the strategy page's Since deploying says it under the paper line only`, async () => {
    const deployments = [
      {id: 1, mode: 'paper', status: 'running', realized_pnl: 3.2, closed_trades: 4, open_positions: 0, created_at: '2026-10-27T08:00:00Z'},
      {id: 2, mode: 'live', status: 'running', realized_pnl: 5, closed_trades: 2, open_positions: 0, created_at: '2026-10-27T08:00:00Z'},
      {id: 3, mode: 'demo', status: 'running', realized_pnl: 0.4, closed_trades: 1, open_positions: 0, created_at: '2026-10-27T08:00:00Z'}];
    const open = async (paper) => {
      const f = strategyFrontend(detailStrategy({status: 'passed', deployments, book_totals: {
        paper: {pnl: 3.2, trades: 4, open: 0, ...paper}, live: {pnl: 5, trades: 2, open: 0}, demo: {pnl: 0.4, trades: 1, open: 0}}}), () => response({}));
      await f.viewStrategy(42); await flush();
      return f.root.querySelector('.real-record');
    };
    const rec = await open({slippage_estimate: EST});
    const lines = [...rec.querySelectorAll('p')].map((p) => p.textContent.replace(/ /g, ' ').replace(/\s+/g, ' ').trim());
    const at = lines.findIndex((t) => t.startsWith('Paper'));
    assert.match(lines[at], /^Paper \+\$3\.20 realized over 4 closed trades, after Kalshi fees and the spread/);
    assert.equal(lines[at + 1], SAID, 'right under the paper line');
    assert.equal(lines.filter((t) => t.includes('after typical live slippage')).length, 1, 'never under live or demo');
    assert.match(rec.innerHTML, /<p class="sub-fig real-slip"><span class="slip-est">/);
    assert.equal(estSpans((await open({})).innerHTML).length, 0);
  });

  test(`${name}: the track record's paper tab says it under its net P&L; live and demo tabs don't`, () => {
    const f = frontend({fetchImpl: () => { throw new Error('offline'); }});
    const paper = f.trackRecordPanel(trackBook({net_pnl: 3.2, slippage_estimate: EST}), 'paper', TH);
    const text = plain(paper).replace(/ /g, ' ');
    assert.ok(text.includes(SAID));
    assert.match(text, /Paper net P&L \+\$3\.20/);
    assert.equal(estSpans(paper).length, 1);
    for (const key of ['live', 'demo']) {
      assert.equal(estSpans(f.trackRecordPanel(trackBook({net_pnl: 3.2, label: key, slippage_estimate: EST}), key, TH)).length, 0, key);
    }
    assert.equal(estSpans(f.trackRecordPanel(trackBook({net_pnl: 3.2, slippage_estimate: null}), 'paper', TH)).length, 0);
  });

  // The rest of the paper headline figures (owner, 2026-10-27: the same labelled estimate beside each).
  const said = (html) => estSpans(html).map((s) => plain(s).trim());

  test(`${name}: the Strategies list's paper card says it under its since-deploying line; live and demo lines don't`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = (s) => f.strategySlip(detailStrategy({id: 46, title: 'List fixture', deployed: true, ...s}), null, {});
    const paper = row({books: ['paper', 'demo'], real: {pnl: 3.2, trades: 4, open: 0, mode: 'paper', slippage_estimate: EST,
      demo: {pnl: 0.4, trades: 1, open: 0}}});
    assert.deepEqual(said(paper), [SAID]);
    assert.match(paper, /\+\$3\.20<\/span> on paper since deploying[\s\S]*<div class="sub-fig real-fig real-slip"><span class="slip-est">≈/);
    // Under the paper line, before the demo one: it is the paper book's.
    assert.ok(paper.indexOf('slip-est') < paper.indexOf('Demo:'));
    // A live card, a paper card with no closed trade yet, or an older server's: nothing said.
    assert.equal(said(row({books: ['live'], deploy_live: true, real: {pnl: 5, trades: 2, open: 0, mode: 'live', live: true, slippage_estimate: EST}})).length, 0);
    assert.equal(said(row({books: ['paper'], real: {pnl: 0, trades: 0, open: 0, mode: 'paper', slippage_estimate: EST}})).length, 0);
    assert.equal(said(row({books: ['paper'], real: {pnl: 3.2, trades: 4, open: 0, mode: 'paper'}})).length, 0);
  });

  const DEP = (o) => ({id: 1, strategy_id: 1, title: 'Dep one', market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
    realized_pnl: 3.2, closed_trades: 4, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5,
    max_positions: 1, backtest: {out_of_sample: null}, ...o});
  const deployBoard = async (body) => {
    const f = frontend({fetchImpl: (path) => path === '/api/deployments' ? response({open_positions: [], ...body}) : response({})});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await flush(); await flush(); await flush();
    f.clearTimers();
    return f.root.querySelector('#dfigs').innerHTML;
  };

  test(`${name}: Deploy's paper Realized says it under the figure; inside the live figure's line it is the paper amount's title`, async () => {
    const paper = await deployBoard({deployments: [DEP()], realized_by_book: {paper: {listed: 3.2, removed: 0, removed_deployments: 0, all: 3.2, slippage_estimate: EST}}});
    assert.deepEqual(said(paper), [SAID]);
    assert.match(plain(paper), /\+\$3\.20/);
    assert.doesNotMatch(estSpans(paper)[0], /tint|pos|neg/);
    // An older server (no estimate): nothing.
    assert.equal(said(await deployBoard({deployments: [DEP()], realized_by_book: {paper: {listed: 3.2, removed: 0, removed_deployments: 0, all: 3.2}}})).length, 0);
    // With a live deployment the paper figure is a phrase in the live figure's line: no line under the live figure,
    // the paper amount carries the words as its title instead. The live and demo books never carry one.
    const live = await deployBoard({deployments: [DEP({id: 2, mode: 'live', realized_pnl: 2}), DEP(), DEP({id: 3, mode: 'demo', realized_pnl: 1})],
      realized_by_book: {live: {listed: 2, removed: 0, removed_deployments: 0, all: 2, slippage_estimate: EST},
        paper: {listed: 3.2, removed: 0, removed_deployments: 0, all: 3.2, slippage_estimate: EST},
        demo: {listed: 1, removed: 0, removed_deployments: 0, slippage_estimate: EST}}});
    assert.equal(said(live).length, 0);
    const tips = [...live.matchAll(/<span class="slip-tip" title="([^"]*)">([^<]*)<\/span> on paper/g)];
    assert.equal(tips.length, 1);
    assert.equal(plain(tips[0][1]).trim(), SAID);
    assert.equal(tips[0][2], '+$3.20');
  });

  test(`${name}: the autopilot card's paper P&L and its week's say it; the panel's paper day says it, the live day never`, async () => {
    const week = {research_credits: 1, checkin_credits: 0, tested: 3, passed: 1, not_cleared: 0, paper_started: 1, paper_trades: 4,
      paper_pnl: 3.2, card_charged: false, paper_slippage_estimate: EST};
    const status = {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 3, passed_7d: 1}, paper_running: 1, demo_running: 0,
      live_running: 0, today_paper_pnl: 1.2, today_live_pnl: 0, today_paper_slippage_estimate: {pnl: 1.15, per_fill_cents: 0.5},
      focus: [], idle: null, story: ['It is trading on paper.'], week};
    const book = {...dashboard(), paper: {...dashboard().paper, realized_pnl: 3.2, closed_trades: 4, total_pnl: 3.2, today_pnl: 1.2,
      open_positions: 0, slippage_estimate: {pnl: 3.05, per_fill_cents: 0.5}}};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(book);
      if (path === '/api/autopilot/status') return response(status);
      return response({messages: [], models: []});
    }});
    f.S.me.user.autopilot = true; f.S.ap = status;
    await f.viewDashboard(); for (let i = 0; i < 6; i++) await flush();
    f.S.ap = status; f.paintDashAp();
    const card = f.root.querySelector('#dash-ap').innerHTML;
    f.clearTimers();
    const cell = /<dt>Paper P&amp;L, realized all time<\/dt><dd>(.*?)<\/dd>/.exec(card)[1];
    assert.deepEqual(said(cell), [SAID.replace('+$3.10', '+$3.05')], 'the dashboard’s own estimate, beside the dashboard’s figure');
    const wk = /<dt>Autopilot’s paper P&amp;L<\/dt><dd>(.*?)<\/dd>/.exec(card)[1];
    assert.deepEqual(said(wk), [SAID]);
    assert.match(wk, /4 closed trades<\/small><span class="slip-est">/);

    const panel = async (st) => {
      const g = frontend({fetchImpl: () => response({messages: [], models: []})});
      g.S.me.user.autopilot = true;
      const box = new (g.root.constructor)('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl>';
      await g.apUpdate(box, st); for (let i = 0; i < 6; i++) await flush();
      g.clearTimers();
      return box.querySelector('#apf-stats').innerHTML;
    };
    const day = /<dt>Paper realized today \(UTC\)<\/dt><dd[^>]*>(.*?)<\/dd>/.exec(await panel(status))[1];
    assert.deepEqual(said(day), [SAID.replace('+$3.10', '+$1.15')]);
    assert.match(day, /^\+\$1\.20 <small class="apf-note">paper, after Kalshi fees and the spread<\/small><span class="slip-est">/);
    // Live in play: the day is live money, never estimated, whatever the answer carries.
    const live = /<dt>Live realized today \(UTC\)<\/dt><dd[^>]*>(.*?)<\/dd>/.exec(await panel({...status, autopilot_live: true, live_running: 1, today_live_pnl: 2}))[1];
    assert.equal(said(live).length, 0);
    // No paper trade closed today: the server sends none, and nothing is said.
    assert.equal(said(/<dt>Paper realized today \(UTC\)<\/dt><dd[^>]*>(.*?)<\/dd>/.exec(await panel({...status, today_paper_pnl: 0, today_paper_slippage_estimate: null}))[1]).length, 0);
  });

  test(`${name}: the strategy page's ladder says it under its paper rung only`, async () => {
    const deployments = [
      {id: 1, mode: 'paper', status: 'running', realized_pnl: 3.2, closed_trades: 4, open_positions: 0, created_at: '2026-10-27T08:00:00Z'},
      {id: 3, mode: 'demo', status: 'running', realized_pnl: 0.4, closed_trades: 1, open_positions: 0, created_at: '2026-10-27T08:00:00Z'}];
    const open = async (paper) => {
      const f = strategyFrontend(detailStrategy({status: 'passed', deployments, book_totals: {
        paper: {pnl: 3.2, trades: 4, open: 0, ...paper}, demo: {pnl: 0.4, trades: 1, open: 0, slippage_estimate: EST}}}), () => response({}));
      await f.viewStrategy(42); await flush();
      return f.root.querySelector('#ladder-body');
    };
    const ladder = await open({slippage_estimate: EST});
    const lines = [...ladder.querySelectorAll('p')].map((p) => p.textContent.replace(/\s+/g, ' ').trim());
    const at = lines.findIndex((t) => t.startsWith('Paper'));
    assert.match(lines[at], /4 closed trades · \+\$3\.20 realized, after Kalshi fees and the spread/);
    assert.equal(lines[at + 1], SAID, 'right under the paper rung');
    assert.equal(lines.filter((t) => t.includes('after typical live slippage')).length, 1, 'never under demo');
    assert.match(ladder.innerHTML, /<p class="rung-slip"><span class="slip-est">/);
    assert.equal(said((await open({})).innerHTML).length, 0);
  });
}
