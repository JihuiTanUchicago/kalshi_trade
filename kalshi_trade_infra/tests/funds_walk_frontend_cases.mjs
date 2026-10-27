// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian), from a Bitcoin trader's
// walk of Funds and Deploy: the paper history names each contract in plain words with its ticker on a small line,
// and says when cash moved with a clock and its zone; the autopilot panel says research under half a cent cost
// "under $0.01"; every open position on Deploy names its book; a book with no closed trade reads "None yet"; and
// Funds' Kalshi cash, not connected, links to the live key's form.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const MARKETS = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes'},
  {key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above $X at 5pm ET', close_hour_et: 17}];

export function fundsWalkCases({name, frontend, fundsData}) {
  test(`${name}: Funds' paper history names each contract in plain words and says when cash moved, with its zone`, async () => {
    // The history led every row with the raw ticker (KXBTC15M-26OCT241200-00, the series key and all), which wrapped
    // over four lines on a phone, and dated a row "Oct 24" with no time or zone.
    const ledger = [
      {created_at: '2026-10-26T21:00:00Z', kind: 'settlement', memo: 'KXBTCD-26OCT2617-T114999.99 settled YES', amount: 12},
      {created_at: '2026-10-26T14:12:00Z', kind: 'trade', memo: 'Sold 8 YES KXBTC15M-26OCT261000-00 @ 0.58 (take_profit)', amount: 4.5},
      {created_at: '2026-10-24T16:00:00Z', kind: 'trade', memo: 'Bought 5 YES KXBTC15M-26OCT241200-00 @ 0.30', amount: -1.58},
      {created_at: '2026-10-24T15:00:00Z', kind: 'deposit', memo: 'Starting paper balance', amount: 1000},
    ];
    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(), paper: {cash: 1014.92, ledger}}) : response({})});
    f.S.me.markets = MARKETS;
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const rows = [...f.root.querySelectorAll('.t-ledger tbody tr')].map((tr) => tr.innerHTML);
    const what = (r) => r.replace(/<span class="kalshi-ref">[\s\S]*?<\/span><\/span>/g, '');
    assert.match(rows[0], /Bitcoin above \$114,999\.99 at 5pm ET settled YES<span class="hint">\u00a0· won, paid \$1 a contract<\/span>/);
    assert.match(rows[1], /Sold 8 YES Bitcoin up or down in 15 minutes at 58¢ \(take profit\)/);
    assert.match(rows[2], /Bought 5 YES Bitcoin up or down in 15 minutes at 30¢/);
    // The ticker is still there to find the contract on Kalshi, on its own small line, never the headline.
    assert.match(rows[2], /<div class="sub-fig"><span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">KXBTC15M-26OCT241200-00<\/span><\/span><\/div>/);
    for (const r of rows.slice(0, 3)) assert.doesNotMatch(what(r), /KXBTC/);
    assert.match(rows[3], /Starting paper balance/);
    assert.doesNotMatch(rows[3], /kalshi-ref/);
    // When: a clock with its zone (and the day), never a bare date.
    for (const [i, iso] of [[0, '2026-10-26T21:00:00Z'], [2, '2026-10-24T16:00:00Z']]) {
      assert.match(rows[i], new RegExp(`<time datetime="${iso}">[^<]*\\d\\d:\\d\\d [A-Z+\\-0-9:]+</time>`), rows[i]);
    }
    f.clearTimers();
  });

  test(`${name}: the autopilot panel's Research line says research under half a cent cost "under $0.01", not nothing`, async () => {
    // The server rounds the week's research to the cent, so $0.003 came as 0 and the line left the spend out,
    // as if research were free; Billing names such a part "under $0.01".
    const f = frontend({fetchImpl: () => response({})});
    const box = f.document.createElement('div');
    box.innerHTML = '<dl id="apf-stats"></dl>';
    const line = (research) => {
      f.apUpdate(box, {autopilot: false, research: {active: [], tested_7d: 3, passed_7d: 0, ...research}, story: []});
      return box.querySelector('#apf-stats').innerHTML;
    };
    assert.match(line({cost_7d: 0, cost_7d_under_cent: true}), /3 ideas tested this week, 0 passed, under \$0\.01 spent/);
    assert.match(line({cost_7d: 0.004}), /0 passed, under \$0\.01 spent/);  // an unrounded figure says the same, never $0.00
    assert.doesNotMatch(line({cost_7d: 0.004}), /\$0\.00/);
    assert.match(line({cost_7d: 0.12}), /0 passed, \$0\.12 spent/);
    assert.doesNotMatch(line({cost_7d: 0}), /spent/);  // nothing debited: nothing said
    f.clearTimers();
  });

  test(`${name}: every open position on Deploy says its book, paper included`, async () => {
    // A demo row carried "Demo" and a live one "Live", but a paper row had no mark, so on a board holding paper
    // and demo positions the paper row's Cost + fee said nothing of which money it was.
    const pos = (id, mode) => ({id, deployment_id: id, strategy_id: id, title: 'Dep ' + id, ticker: 'KXBTC15M-26OCT271715-15', side: 'yes',
      qty: 5, entry_price: .44, entry_fee: .09, cost: 2.29, unrealized: null, mode, opened_at: '2026-10-27T16:50:00Z',
      market_close_time: '2030-01-15T17:30:00Z', status: 'open'});
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/deployments')
      ? response({deployments: [], open_positions: [pos(1, 'paper'), pos(2, 'demo'), pos(3, 'live')]}) : response({})});
    f.S.me.markets = MARKETS;
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const rows = [...f.root.querySelectorAll('#openpos tbody tr')].map((tr) => tr.innerHTML);
    assert.equal(rows.length, 3);
    const marks = rows.map((r) => (/<td class="name" data-lab="Strategy">[^<]*<span class="mk[^"]*">([^<]*)<\/span><\/td>/.exec(r) || [])[1]);
    assert.deepEqual(marks, ['Paper', 'Demo', 'Live']);
    f.clearTimers();
  });

  test(`${name}: Deploy's Realized says "None yet" for a book with no closed trade, never a $0.00 that reads as flat`, async () => {
    // A new account's Deploy said "Realized $0.00 · paper money, not real" before any trade had closed, while the
    // dashboard and the autopilot say "None yet" for the same book.
    const dep = (id, mode, closed, pnl) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode, status: 'running', status_reason: null,
      realized_pnl: pnl, closed_trades: closed, open_positions: 1, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5,
      max_positions: 1, backtest: {out_of_sample: null}});
    const figs = async (body) => {
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/deployments') ? response({open_positions: [], ...body}) : response({})});
      f.location.pathname = '/deploy';
      await f.viewDeploy(); await settle(); f.clearTimers();
      return f.root.querySelector('#dfigs').innerHTML.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ');
    };
    const fresh = await figs({deployments: []});
    assert.match(fresh, /Realized None yet paper money, not real · shows once a paper trade closes/);
    assert.doesNotMatch(fresh, /\$0\.00/);
    assert.match(await figs({deployments: [dep(1, 'paper', 0, 0)]}), /Realized, deployments listed below None yet paper money, not real · shows once a paper trade closes/);
    assert.match(await figs({deployments: [dep(1, 'demo', 0, 0)]}), /Demo realized, deployments listed below None yet [^·]*not real money · shows once a demo trade closes/);
    // A book that has closed trades keeps its figure, even an even $0.00.
    const even = await figs({deployments: [dep(1, 'paper', 2, 0)]});
    assert.match(even, /Realized, deployments listed below \$0\.00 paper money/);
    assert.doesNotMatch(even, /None yet|shows once/);
    // A book whose closed trades are all on removed deployments has a figure too.
    const removed = await figs({deployments: [dep(1, 'paper', 0, 0)], realized_by_book: {paper: {listed: 0, removed: 1.5, removed_deployments: 1, all: 1.5}}});
    assert.doesNotMatch(removed, /None yet/);
  });

  test(`${name}: Funds' Kalshi cash, not connected, links to the live key's form`, async () => {
    // Tau said "Connect a key to trade real money" with no link and Meridian said nothing: a dead end at the top of
    // the page. It links to the live key form: in Connect Kalshi (opened) while no key is in, else on the page.
    for (const [dev, href, target] of [[{connected: false}, '#connect-kalshi', 'connect-kalshi'], [{connected: true, key_id: 'DEVK…5678', balance: 250, balance_at: new Date().toISOString()}, '#kalshi', 'kalshi']]) {
      const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(), kalshi_dev: dev}) : response({})});
      f.location.pathname = '/funds'; f.location.hash = '';
      await f.viewFunds(); await settle();
      const link = f.root.querySelector('#ffigs').querySelectorAll('a').find((a) => a.textContent === 'Connect a Kalshi key');
      assert.ok(link, JSON.stringify(dev));
      assert.equal(link.getAttribute('href'), href);
      assert.ok(f.root.querySelector('#' + target), `${href} is on the page`);
      assert.match(f.root.querySelector('#ffigs').textContent, /Connect a Kalshi key below to trade real money/);
      f.clearTimers();
    }
  });
}
