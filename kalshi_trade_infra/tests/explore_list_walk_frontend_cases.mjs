// Explore's list as a reader meets it (walk 2026-10-31, both themes, 390px and 1366px, stubbed feeds of hundreds of
// markets), run against each bundle's offline DOM/transport harness (Tau and Meridian):
// - a page past the list's end (a kept link, or the last page while a refresh shortened the list) shows the last page,
//   not "No markets to show yet … hasn't come in yet" with no pager;
// - a search that missed has a Clear search to press, which keeps the reader in the box and brings the list back;
// - a count the feed didn't send reads "—" (as the market page's), not 0; a Yes price from the last trade says so;
// - Next and Prev take focus to the new page's first market, not to "← Prev";
// - a poll that reorders the rows keeps the row the reader is on where it was on screen;
// - the hot rail names its figure "Yes price", as the list and the market page do.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const row = (t, over = {}) => ({t, s: t.split('-')[0], ti: `Game ${t} winner?`, su: 'Home', bid: .49, ask: .51, last: .5, v24: 900, oi: 50, ...over});
const page = (markets, over = {}) => ({at: new Date().toISOString(), total: 41000, shown: 500, matched: markets.length, page: 0, per: 40, sort: 'v24', markets, ...over});
const hasFocus = (f, el) => !!el && (el.focused === true || f.document.activeElement === el);

// The interval whose tick asks for `prefix`: the page's own poll.
async function pollOf(f, prefix) {
  for (const tick of [...f.intervals.values()].reverse()) {
    const before = f.requests.length;
    await tick(); await settle();
    if (f.requests.slice(before).some(({path}) => path.startsWith(prefix))) return tick;
  }
  throw new Error('no poll asks for ' + prefix);
}

export function exploreListWalkCases({name, frontend}) {
  const open = async (reply, {search = '', win} = {}) => {
    const f = frontend({search, win, fetchImpl: (path) => (path.startsWith('/api/explore?') ? reply(new URLSearchParams(path.split('?')[1])) : response({}))});
    f.location.pathname = '/explore'; f.location.search = search;
    await f.viewExplore(); await settle();
    const asked = () => f.requests.filter(({path}) => path.startsWith('/api/explore?')).map(({path}) => Object.fromEntries(new URLSearchParams(path.split('?')[1])));
    const links = () => f.root.querySelectorAll('#xrows tr').map((tr) => tr.querySelector('a').getAttribute('href').replace('/explore?m=', ''));
    return {f, asked, links};
  };

  test(`${name}: a page past the list's end shows its last page, never "hasn't come in yet", on opening and when a refresh shortens the list`, async () => {
    let total = 90;  // three pages of 40
    const all = () => Array.from({length: total}, (_, i) => row(`KX${i}-1`));
    const {f, asked, links} = await open((q) => { const p = +q.get('page'); return response(page(all().slice(p * 40, p * 40 + 40), {matched: total, page: p})); }, {search: '?page=7'});
    assert.deepEqual(asked().map((q) => q.page), ['7', '2'], 'a kept link to page 8 reads page 3, the last');
    assert.equal(links().length, 10); assert.equal(links()[0], 'KX80-1');
    assert.match(f.root.querySelector('#xpager').textContent, /Page 3 of 3/);
    assert.equal(f.location.search, '?q=&sort=v24&page=2', 'the address says the page it shows');
    assert.doesNotMatch(f.root.querySelector('#xbody').textContent, /hasn’t come in yet|No markets to show/);
    // On the last page, the next refresh's list is a page shorter: the poll shows the new last page.
    total = 70;
    const poll = await pollOf(f, '/api/explore?');
    await poll(); await settle();
    assert.equal(asked().at(-1).page, '1'); assert.equal(links()[0], 'KX40-1'); assert.equal(links().length, 30);
    assert.match(f.root.querySelector('#xpager').textContent, /Page 2 of 2/);
    // A list with nothing in it at all is still said as the feed not having arrived.
    total = 0;
    await poll(); await settle(); await poll(); await settle();
    assert.equal(f.root.querySelector('#xbody .empty h2').textContent, 'No markets to show yet');
    f.clearTimers();
  });

  test(`${name}: a search that missed offers Clear search, which empties the box, keeps the reader in it and brings the list back`, async () => {
    const {f, asked, links} = await open((q) => response(page(q.get('q') ? [] : [row('KXA-1'), row('KXB-1')], {matched: q.get('q') ? 0 : 2})), {search: '?q=Minesota'});
    const box = f.root.querySelector('#xq');
    assert.equal(box.value, 'Minesota');
    const clear = f.root.querySelector('#xbody [data-xclear]');
    assert.ok(clear, 'the empty state has a button to press');
    assert.equal(clear.textContent, 'Clear search');
    await clear.onclick(); await settle();
    assert.equal(box.value, ''); assert.ok(hasFocus(f, box), 'focus is in the search box, to type again');
    assert.deepEqual(asked().at(-1), {q: '', sort: 'v24', page: '0'});
    assert.deepEqual(links(), ['KXA-1', 'KXB-1']);
    assert.equal(f.location.search, '?q=&sort=v24&page=0');
    // The Bitcoin list a search emptied offers the same, beside Show all markets.
    const g = await open((q) => response(page([], {matched: 0})), {search: '?show=bitcoin&q=Minnesota'});
    const btc = g.f.root.querySelector('#xbody');
    assert.match(btc.querySelector('h2').textContent, /No Bitcoin markets match/);
    assert.deepEqual(btc.querySelectorAll('button').map((b) => b.textContent), ['Clear search', 'Show all markets']);
    await btc.querySelector('[data-xclear]').onclick(); await settle();
    assert.deepEqual(g.asked().at(-1), {q: '', sort: 'v24', page: '0', show: 'bitcoin'}, 'the Bitcoin choice stays');
    f.clearTimers(); g.f.clearTimers();
  });

  test(`${name}: a count the feed didn't send reads "—", not 0, and a Yes price from the last trade says so`, async () => {
    const {f} = await open(() => response(page([
      row('KXQUOTED-1'),
      row('KXLAST-1', {bid: 0, ask: 0, last: .62}),
      row('KXASK-1', {bid: 0, ask: .07, last: .3}),
      row('KXNONE-1', {bid: 0, ask: 0, last: 0}),
      row('KXNOVOL-1', {v24: undefined, oi: null}),
      row('KXZERO-1', {v24: 0, oi: 0}),
      row('KXBLANK-1', {v24: '', oi: 'n/a'}),
    ])));
    const cells = f.root.querySelectorAll('#xrows tr').map((tr) => [tr.querySelector('[data-lab="Yes price"]').textContent,
      tr.querySelector('[data-lab="24h volume"]').textContent, tr.querySelector('[data-lab="Open interest"]').textContent]);
    assert.deepEqual(cells, [
      ['50¢', '900', '50'],
      ['62¢last trade', '900', '50'],
      ['30¢last trade', '900', '50'],
      ['—', '900', '50'],
      ['50¢', '—Not sent', '—Not sent'],
      ['50¢', '0', '0'],
      ['50¢', '—Not sent', '—Not sent'],
    ]);
    assert.doesNotMatch(f.root.querySelector('#xrows').innerHTML, /NaN|undefined|n\/a/);
    f.clearTimers();
  });

  test(`${name}: Next and Prev take focus to the new page's first market, not to the pager's "← Prev"`, async () => {
    const {f, asked} = await open((q) => { const p = +q.get('page'); return response(page(Array.from({length: 40}, (_, i) => row(`KXP${p}R${i}-1`)), {matched: 120, page: p})); });
    const next = f.root.querySelector('#xpager [data-pg]');
    assert.match(next.textContent, /Next/);
    next.focus(); if (f.document.activeElement !== undefined) f.document.activeElement = next;
    await next.onclick(); await settle();
    assert.equal(asked().at(-1).page, '1');
    const first = f.root.querySelector('#xrows a');
    assert.equal(first.getAttribute('href'), '/explore?m=KXP1R0-1');
    assert.ok(hasFocus(f, first), 'focus is on the first market of page 2');
    assert.equal(first.focusOptions && first.focusOptions.preventScroll, true);
    if (f.document.activeElement !== undefined) assert.equal(f.document.activeElement, first, 'not left on "← Prev"');
    f.clearTimers();
  });

  test(`${name}: a poll that reorders the rows keeps the row the reader is on where it was on screen; at the top, or on a read the reader asked for, nothing moves`, async () => {
    let order = ['KXA-1', 'KXB-1', 'KXC-1', 'KXD-1', 'KXE-1'];
    const scrolls = [], win = {scrollY: 600, innerHeight: 900, scrollBy: (x, y) => scrolls.push([x, y])};
    const {f, links} = await open(() => response(page(order.map((t) => row(t)))), {win});
    // Rows 50px tall, the list's top 500px down the page: scrolled 600px, row C (index 2) is the first in view.
    const pw = f.window || f.win;  // the page's own window (the harness copies `win` into it)
    const proto = Object.getPrototypeOf(f.root), had = Object.prototype.hasOwnProperty.call(proto, 'getBoundingClientRect');
    proto.getBoundingClientRect = function () {
      if (this.tag !== 'tr' || !this.parent || this.parent.attributes.id !== 'xrows') return {top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0};
      const top = 500 + this.parent.children.indexOf(this) * 50 - pw.scrollY;
      return {top, bottom: top + 50, left: 0, right: 800, width: 800, height: 50};
    };
    try {
      const poll = await pollOf(f, '/api/explore?');
      scrolls.length = 0;
      // A new market climbs to the top and C drops two places: C is now 3 rows lower, so the page scrolls 150px with it.
      order = ['KXN-1', 'KXA-1', 'KXB-1', 'KXD-1', 'KXE-1', 'KXC-1'];
      await poll(); await settle();
      assert.deepEqual(links(), order);
      assert.deepEqual(scrolls, [[0, 150]]);
      // The same rows in the same places: nothing to hold.
      scrolls.length = 0;
      await poll(); await settle();
      assert.deepEqual(scrolls, []);
      // The reader is on E's link (index 4, in view): E is held, not the first row in view.
      const e = f.root.querySelectorAll('#xrows tr')[4].querySelector('a');
      e.focus(); f.document.activeElement = e;
      order = ['KXE-1', 'KXN-1', 'KXA-1', 'KXB-1', 'KXD-1', 'KXC-1'];
      await poll(); await settle();
      assert.deepEqual(scrolls, [[0, -200]]);
      // A row the poll took off the page holds nothing; at the top of the page nothing is held either.
      scrolls.length = 0;
      f.document.activeElement = f.document.body;
      order = ['KXZ-1', 'KXY-1'];
      await poll(); await settle();
      assert.deepEqual(scrolls, []);
      pw.scrollY = 0; order = ['KXY-1', 'KXZ-1'];
      await poll(); await settle();
      assert.deepEqual(scrolls, []);
      // A sort the reader picked draws a new list where it draws it: no hold.
      pw.scrollY = 600; order = ['KXZ-1', 'KXY-1'];
      f.root.querySelector('[data-sort="oi"]').onclick(); await settle();
      assert.deepEqual(scrolls, []);
    } finally {
      if (!had) delete proto.getBoundingClientRect;
      f.clearTimers();
    }
  });

  test(`${name}: the hot rail names its figure "Yes price", and one from the last trade says so`, async () => {
    const f = frontend({fetchImpl: () => response({})});
    f.root.innerHTML = '<aside id="hotrail"></aside>';
    f.S.hot = {at: new Date().toISOString(), markets: [row('KXQ-1', {h: [.4, .5]}), row('KXL-1', {bid: 0, ask: 0, last: .62, h: [.6, .62]}), row('KXN-1', {bid: 0, ask: 0, last: 0, h: [.1, .1]})]};
    f.renderHotRail();
    const prices = f.root.querySelectorAll('.hot-row .hot-price');
    assert.deepEqual(prices.map((p) => p.getAttribute('title')), ['Yes price', 'Yes price, from the last trade', 'Yes price']);
    assert.doesNotMatch(f.root.querySelector('#hotrail').innerHTML, /Midpoint quote/);
    f.clearTimers();
  });
}
