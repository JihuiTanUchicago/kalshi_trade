// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): a customer who stayed six
// months. Walked 2026-10-30 on a seeded paper ledger of ~300 entries: Funds' paper history held the newest 50 (about
// two days) and said "The latest 50 entries." with no way to the rest. "Show older entries" reads the 50 before the
// oldest one shown (/api/funds/ledger?before=), clicked and never polled; the poll keeps them under its newest page.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 8; i++) await flush(); };
const plain = (html) => html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/⁠/g, '').replace(/\s+/g, ' ').trim();
// Entry `id` of a ledger whose ids run 1..top (a buy every other entry, a sale between), newest first.
const entry = (id) => ({id, kind: 'trade', amount: id % 2 ? -1.25 : 2.5, created_at: new Date(Date.UTC(2026, 4, 1) + id * 36e5 * 14).toISOString(),
  memo: id % 2 ? `Bought 5 YES KXBTC15M-26OCT241200-00 @ 0.25 (#${id})` : `Sold 5 YES KXBTC15M-26OCT241200-00 @ 0.50 (take_profit, #${id})`});
const page = (top, n) => Array.from({length: Math.max(0, Math.min(n, top))}, (_, k) => entry(top - k));

// The interval whose tick asks for /api/funds: the page's own 30s poll.
async function fundsPoll(f) {
  for (const tick of [...f.intervals.values()].reverse()) {
    const before = f.requests.length;
    await tick(); await settle();
    if (f.requests.slice(before).some(({path}) => path === '/api/funds')) return tick;
  }
  throw new Error('no poll asks for /api/funds');
}

export function fundsHistoryCases({name, frontend, fundsData}) {
  // A server holding `top()` entries: /api/funds lists the newest 50, /api/funds/ledger the 50 before `before`.
  const server = (state) => (path) => {
    if (path.startsWith('/api/funds/ledger?before=')) {
      state.asked.push(path);
      if (state.fail) { state.fail = false; return response({error: 'Something went wrong on our side. Try again.'}, 500); }
      const before = +path.split('=')[1], ids = Array.from({length: state.top}, (_, k) => state.top - k).filter((id) => id < before && id >= state.floor);
      return response({ledger: ids.slice(0, 50).map(entry), more: ids.length > 50});
    }
    if (path === '/api/funds') {
      const ids = Array.from({length: state.top - state.floor + 1}, (_, k) => state.top - k);
      return response({...fundsData(), paper: {cash: 1234.56, equity: 1240.06, realized_pnl: 12.5, closed_trades: 40, open_positions: 0, ledger: ids.slice(0, 50).map(entry)}});
    }
    return response({});
  };
  const rows = (f) => [...f.root.querySelectorAll('.t-ledger tbody tr')];
  const ids = (f) => rows(f).map((tr) => +/#(\d+)\)/.exec(tr.innerHTML)[1]);
  const button = (f) => f.root.querySelector('#ledger-older-btn');
  const click = async (f) => { await f.root.querySelector('#ledger-older').onclick({target: button(f)}); await settle(); };
  // A click hands focus to the first entry it listed, and the poll leaves Funds as it is while the reader is in it
  // (as it did while focus sat on the button): the reader moves on before a poll is to redraw the history.
  const focusedOn = (f, el) => el.focused === true || f.document.activeElement === el;
  const away = (f) => { f.document.activeElement = f.document.body; };

  test(`${name}: Funds' paper history shows older entries on request, 50 at a time, to the first one`, async () => {
    const state = {top: 160, floor: 1, asked: []};
    const f = frontend({fetchImpl: server(state)});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    const figs = f.root.querySelector('#ffigs').innerHTML;
    assert.deepEqual(ids(f), page(160, 50).map((r) => r.id));
    assert.match(f.root.querySelector('.ledger-how').textContent, /The latest 50 entries\.$/);
    assert.ok(button(f), 'a "Show older entries" button under the newest 50');
    assert.equal(plain(button(f).innerHTML), 'Show older entries');
    // No entry id where the customer reads: the button names none, nor does any row's markup outside its memo.
    assert.doesNotMatch(f.root.querySelector('#ledger-older').innerHTML, /\d/);
    const first = rows(f).at(-1).innerHTML;

    await click(f);
    assert.deepEqual(state.asked, ['/api/funds/ledger?before=111'], 'the 50 before the oldest one shown');
    assert.deepEqual(ids(f), page(160, 100).map((r) => r.id), 'the older 50 are listed under the newest, in order');
    assert.match(f.root.querySelector('.ledger-how').textContent, /The latest 100 entries\.$/);
    // Each older row is drawn as a newest-page row is, with its phone labels.
    for (const tr of rows(f)) assert.deepEqual(tr.children.map((td) => td.attributes['data-lab']), ['When', 'What', 'Amount']);
    assert.match(rows(f)[50].innerHTML, /Sold 5 YES [^<]* at 50¢ \(take profit, #110\)/);
    const same = frontend({fetchImpl: server({top: 110, floor: 1, asked: []})});
    same.location.pathname = '/funds';
    await same.viewFunds(); await settle();
    assert.equal(rows(f)[49].innerHTML, first);
    assert.equal(rows(f)[50].innerHTML, rows(same)[0].innerHTML, 'entry 110 on an older page reads as it does on a newest page');
    // The figures come from their own read: an older page moves none of them.
    assert.equal(f.root.querySelector('#ffigs').innerHTML, figs);

    // Focus is on the first entry just listed (#110), not left on the button the new rows pushed off the screen.
    assert.ok(focusedOn(f, rows(f)[50]), 'focus is on the first older entry');
    assert.equal(rows(f)[50].getAttribute('tabindex'), '-1');

    // The poll keeps them; new entries come in on top and the ones that slid off the newest page stay, once each.
    away(f);
    const poll = await fundsPoll(f);
    assert.deepEqual(ids(f), page(160, 100).map((r) => r.id));
    state.top = 163; await poll(); await settle();
    assert.deepEqual(ids(f), page(163, 103).map((r) => r.id));
    assert.ok(!state.asked.some((p) => p !== '/api/funds/ledger?before=111'), 'the poll never asks for an older page');

    await click(f);
    assert.equal(state.asked.at(-1), '/api/funds/ledger?before=61');
    await click(f);
    assert.equal(state.asked.at(-1), '/api/funds/ledger?before=11');
    assert.deepEqual(ids(f), page(163, 163).map((r) => r.id), 'every entry, newest first, each once');
    // The server said no more: the button goes, and the end says so in plain words.
    assert.equal(button(f), null);
    assert.equal(plain(f.root.querySelector('#ledger-older').innerHTML), 'That’s every entry in your paper history.');
    assert.doesNotMatch(f.root.querySelector('.ledger-how').textContent, /latest/);
    assert.equal(state.asked.length, 3);
    await poll(); await settle();
    assert.equal(rows(f).length, 163);
    assert.equal(state.asked.length, 3);
    f.clearTimers(); same.clearTimers();
  });

  test(`${name}: a paper history that fits the newest page offers no older one`, async () => {
    const state = {top: 12, floor: 1, asked: []};
    const f = frontend({fetchImpl: server(state)});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    assert.equal(rows(f).length, 12);
    assert.equal(button(f), null);
    assert.equal(f.root.querySelector('#ledger-older').innerHTML, '');
    assert.doesNotMatch(f.root.querySelector('.ledger-how').textContent, /latest/);
    f.clearTimers();
  });

  test(`${name}: a reset drops the older entries it wiped, and an older read that fails says so and can be tried again`, async () => {
    const state = {top: 120, floor: 1, asked: [], fail: true};
    const f = frontend({fetchImpl: server(state)});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    await click(f);
    assert.equal(rows(f).length, 50);
    assert.match(f.root.querySelector('#lflash').innerHTML, /Something went wrong on our side/);
    assert.ok(button(f), 'the button stays to try again');
    await click(f);
    assert.equal(rows(f).length, 100);
    assert.equal(f.root.querySelector('#lflash').innerHTML, '');
    // Reset: the ledger is wiped and restarts with one deposit; the older rows the page held are gone with it.
    away(f);
    const poll = await fundsPoll(f);
    state.floor = state.top = 121; await poll(); await settle();
    assert.deepEqual(ids(f), [121]);
    assert.equal(button(f), null);
    // Over a page of new entries between two reads: they no longer join, so the history starts again from its newest.
    state.top = 300; await poll(); await settle();
    assert.equal(rows(f).length, 50);
    assert.ok(button(f));
    await click(f);
    assert.equal(state.asked.at(-1), '/api/funds/ledger?before=251');
    away(f);
    state.top = 400; await poll(); await settle();
    assert.deepEqual(ids(f), page(400, 50).map((r) => r.id));
    f.clearTimers();
  });

  test(`${name}: the core keeps older rows under a fresh newest page only while the two join`, () => {
    const {olderRows} = frontend({fetchImpl: () => response({})}).window.TauCore;
    const ids = (rs) => rs && Array.from(rs, (r) => r.id);  // the page's arrays are of its own realm
    assert.deepEqual(ids(olderRows(page(60, 50), page(58, 58).concat(page(30, 30)), 50)), page(10, 10).map((r) => r.id), 'older than the newest page, once each');
    assert.deepEqual(ids(olderRows(page(5, 5), page(58, 100), 50)), [], 'a short newest page holds every row');
    assert.equal(olderRows(page(200, 50), page(58, 100), 50), null, 'no row in common: they no longer join');
    assert.deepEqual(ids(olderRows(page(60, 50), [], 50)), []);
  });
}
