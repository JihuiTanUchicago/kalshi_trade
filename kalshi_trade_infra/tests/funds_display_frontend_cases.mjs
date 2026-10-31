// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian), from a walk of Funds across
// account states (walk 2026-10-31): a pair trade's paper history line names both contracts in plain words, never the
// second's raw ticker, and says the engine's pair words plainly; the demo book's figure says Kalshi refuses demo orders
// while the Kalshi demo account is empty; a poll that can't read lets each cash "read …" age instead of saying "just
// now" under the stale note; and a cash spot redrawn under focus gives focus back to the same link.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const MARKETS = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes'},
  {key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET', close_hour_et: 17}];

export function fundsDisplayCases({name, frontend, fundsData}) {
  test(`${name}: Funds' paper history names both contracts of a pair trade in plain words, each ticker on its small line`, async () => {
    // "Bought 3 pair Bitcoin $113,000 or above at 5pm ET/KXBTCD-26OCT3117-T113999.99 (pair)": only the first ticker was
    // renamed, so the second's raw series key stood in the words, and "unhedged" and "pair leg left naked" were the
    // engine's jargon. Display only: the stored memo and the amount are unchanged.
    const A = 'KXBTCD-26OCT3117-T112999.99', B = 'KXBTCD-26OCT3117-T113999.99';
    const ledger = [
      {id: 4, created_at: '2026-10-31T12:54:00Z', kind: 'trade', memo: `Bought 1 YES ${A} (pair leg left naked)`, amount: -0.41},
      {id: 3, created_at: '2026-10-31T12:49:00Z', kind: 'trade', memo: `Unwound 1 unhedged YES ${A} (pair)`, amount: -0.12},
      {id: 2, created_at: '2026-10-31T12:44:00Z', kind: 'trade', memo: `Bought 3 pair ${A}/${B} (pair)`, amount: -1.8},
      {id: 1, created_at: '2026-10-31T12:40:00Z', kind: 'trade', memo: `Bought 1 pair ${A}/${B} (pair)`, amount: -0.6},
    ];
    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(), paper: {cash: 996.07, ledger}}) : response({})});
    f.S.me.markets = MARKETS;
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const rows = [...f.root.querySelectorAll('.t-ledger tbody tr')];
    const said = rows.map((tr) => tr.querySelector('.ledger-said').textContent);
    const refs = rows.map((tr) => [...tr.querySelectorAll('.kalshi-ref')].map((r) => r.textContent.replace(/\s+/g, ' ')));
    assert.match(said[2], /^Bought 3 pairs: Bitcoin \$113,000 or above at 5pm ET and Bitcoin \$114,000 or above at 5pm ET$/);
    assert.deepEqual(refs[2], [`Kalshi contract ${A}`, `Kalshi contract ${B}`]);
    assert.match(said[3], /^Bought 1 pair: /);
    assert.match(said[1], /^Closed 1 unmatched YES Bitcoin \$113,000 or above at 5pm ET \(pair\)$/);
    assert.match(said[0], /^Bought 1 YES Bitcoin \$113,000 or above at 5pm ET \(one side of a pair; the other side didn’t fill\)$/);
    for (const s of said) assert.doesNotMatch(s, /KX[A-Z0-9]+-|unhedged|naked|\/K/);
    // A repeated contract is listed once under its line.
    assert.equal(refs[1].length, 1);
    f.clearTimers();
  });

  test(`${name}: Funds' demo book figure says Kalshi refuses demo orders while the Kalshi demo account has $0.00`, async () => {
    // The figure read "$1,000.00 starting capital · P&L shows once a demo trade closes" as if demo could trade, with the
    // notice a screen and more below it on a phone. Only from a figure Kalshi sent: never while checking or failed.
    const NOTE = /Kalshi refuses demo orders while your Kalshi demo account has \$0\.00 \(Demo key, below\)/;
    const at = new Date().toISOString();
    for (const [dev, said] of [
      [{balance: 0, balance_at: at}, true], [{balance: 250, balance_at: at}, false], [{balance: null, pending: true}, false],
      [{balance: null}, false]]) {
      const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response({...fundsData(),
        demo: {capital: 1000, equity: 1000, realized: 0, closed_trades: 0, open_positions: 0, open_at_cost: 0, open_cost: 0},
        kalshi_dev: {connected: true, key_id: 'DEVK…5678', copies_from: 100, ...dev}})
        : new Promise(() => {})});  // a pending check's follow-up stays out
      f.location.pathname = '/funds';
      await f.viewFunds(); await settle();
      const fig = [...f.root.querySelectorAll('#ffigs div.m')][1].textContent.replace(/\s+/g, ' ');
      assert.match(fig, /Tau’s demo book/);
      if (said) assert.match(fig, NOTE); else assert.doesNotMatch(fig, NOTE);
      f.clearTimers();
    }
  });

  test(`${name}: a Funds poll that can't read leaves the cash read times aging, never "read just now" under a stale note`, async () => {
    // Walked with /api/funds failing for two minutes: "Last updated 2m ago, retrying" sat under Kalshi cash's "read just
    // now" and the keys' "(balance $2,345.67, read just now)". The failed poll redraws the answer shown, asking nothing more.
    let fail = false;
    const at = new Date().toISOString();
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/funds/cash')) return new Promise(() => {});
      if (path === '/api/funds') return fail ? response({error: 'Tau is busy. Try again.'}, 503) : response({...fundsData(),
        kalshi: {connected: true, key_id: 'LIVE…0002', balance: 2345.67, balance_at: at, funding_url: 'https://kalshi.com/account/funding',
          open_positions: 0, open_at_cost: 0, closed_trades: 0, realized_pnl: 0},
        kalshi_dev: {connected: true, key_id: 'DEVK…5678', balance: 250, balance_at: at}});
      return response({});
    }});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const live = () => [...f.root.querySelectorAll('#ffigs div.m')][0].textContent.replace(/\s+/g, ' ');
    const spot = (k) => f.root.querySelector(`[data-cash="${k}"]`).textContent;
    assert.match(live(), /read just now\./);
    assert.match(spot('demo-ok'), /read just now\)/);
    fail = true;
    f.shiftClock(5 * 60000);
    const before = f.requests.filter(({path}) => path === '/api/funds').length;
    for (const t of [...f.intervals.values()]) t();
    await settle();
    assert.equal(f.requests.filter(({path}) => path === '/api/funds').length, before + 1, 'the poll asks once; the redraw asks nothing');
    assert.match(live(), /\$2,345\.67[\s\S]*read 5m ago\./);
    assert.doesNotMatch(live(), /just now/);
    assert.match(spot('live-ok'), /\(balance \$2,345\.67, read 5m ago\)/);
    assert.match(spot('demo-ok'), /Kalshi demo account cash \$250\.00, read 5m ago\)/);
    f.clearTimers();
  });

  test(`${name}: a Funds cash spot redrawn under focus gives it back to the same link, and one drawn the same is left alone`, async () => {
    let fail = false;
    const at = new Date().toISOString();
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/funds/cash')) return new Promise(() => {});
      if (path === '/api/funds') return fail ? response({error: 'Tau is busy. Try again.'}, 503)
        : response({...fundsData(), kalshi_dev: {connected: true, key_id: 'DEVK…5678', balance: 0, balance_at: at, copies_from: 100}});
      return response({});
    }});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const ok = f.root.querySelector('[data-cash="demo-ok"]');
    const demoLink = () => [...ok.querySelectorAll('a')].find((a) => /^https:\/\/demo\.kalshi\.co/.test(a.getAttribute('href')));
    const link = demoLink();
    assert.ok(link, 'the $0 notice links demo.kalshi.co');
    link.focus(); f.document.activeElement = link;  // the Tau harness's focus() doesn't move activeElement
    fail = true;
    const poll = () => { for (const t of [...f.intervals.values()]) t(); };
    poll(); await settle();
    assert.equal(demoLink(), link, 'drawn the same: the very link stays');
    f.shiftClock(5 * 60000);
    poll(); await settle();  // sat out: the back-off after one failed read
    poll(); await settle();
    const back = demoLink();
    assert.match(ok.textContent, /read 5m ago/);
    assert.notEqual(back, link, 'the spot was drawn again');
    assert.ok(back.focused || f.document.activeElement === back, 'focus is back on the same link');
    f.clearTimers();
  });
}
