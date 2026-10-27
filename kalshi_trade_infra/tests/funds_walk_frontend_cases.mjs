// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian), from a Bitcoin trader's
// walk of Funds and Deploy: the paper history names each contract in plain words with its ticker on a small line,
// and says when cash moved with a clock and its zone.
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
    assert.match(rows[0], /Bitcoin above \$114,999\.99 at 5pm ET settled YES<span class="hint"> ·\u00a0won, paid \$1 a contract<\/span>/);
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
}
