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
}
