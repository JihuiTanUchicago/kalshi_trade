// Explore's list and the hot-markets rail, run against each bundle's offline DOM/transport harness: a
// Bitcoin contract's row says how far stored spot is from its strike (the server's `vs`), a bucket spot
// sits in says "in range", and without a fresh spot the figures are left out under one line that says why.
// Hot markets also say when they close (`ct`), as Explore's rows do. Every row, in either list, is named by
// its title and market chip, never by its raw ticker.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

const SPOT = {price: 113420, at: '2026-10-27T11:00:00Z', age_s: 4, stale: false};
const row = (t, over = {}) => ({t, s: t.split('-')[0], ti: 'Bitcoin price on Oct 27, 2026 at 5pm EDT?', su: '', bid: .48, ask: .52, v24: 900, oi: 50,
  ct: '2026-10-27T21:00:00Z', ...over});
const ROWS = [row('KXBTCD-26OCT2717-T112999.99', {su: '$113,000 or above', vs: {side: 'above', diff: 420.01, pct: 0.372}}),
  row('KXBTCD-26OCT2717-T114000', {su: '$114,000.01 or above', vs: {side: 'below', diff: -580, pct: -0.509}}),
  row('KXBTC-26OCT2717-B113250', {su: '$113,000 to 113,499.99', vs: {side: 'inside', diff: 0, pct: 0}}),
  row('KXBTC-26OCT2717-B113750', {su: '$113,500 to 113,999.99', vs: {side: 'below', diff: -80, pct: -0.07}}),
  row('KXBTC15M-26OCT271145-45', {ti: 'BTC price up in next 15 mins?'}),
  row('KXNBAGAME-26OCT26MINDEN-MIN', {s: 'KXNBAGAME', ti: 'Minnesota at Denver Winner?', su: 'Minnesota', ct: null})];

export function exploreSpotListCases({name, frontend, storageFor, railOpenWide}) {
  const list = async (answer) => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore?') ? response({at: new Date().toISOString(), total: 6, shown: 6, matched: 6, page: 0, per: 40, sort: 'v24', ...answer}) : response({}))});
    f.location.pathname = '/explore'; f.location.search = '';
    await f.viewExplore(); await settle();
    const body = f.root.querySelector('#xbody');
    return {f, body, rows: body.querySelectorAll('tbody tr'), note: body.querySelector('.xspot-note')};
  };

  test(`${name}: Explore's Bitcoin rows say how far fresh spot is from each strike, signed, and "in range" for the bucket spot sits in`, async () => {
    const {f, rows, note} = await list({markets: ROWS, spot: SPOT});
    const spot = rows.map((r) => r.querySelector('.xspot'));
    // The figure keeps its "·" with the percent (a no-break space), so it never wraps between the two.
    assert.deepEqual(spot.slice(0, 4).map((s) => s.textContent.replace(/ /g, ' ')), ['Spot vs strike +$420 · 0.4%', 'Spot vs strike −$580 · 0.5%', 'Spot vs bucket in range', 'Spot vs bucket −$80 · 0.07%']);
    // Inside the name cell, under the name: the list keeps its columns, and a stacked phone row needs no extra label.
    assert.ok(rows.slice(0, 4).every((r) => /class="xspot"/.test(r.querySelector('td.name').innerHTML)));
    assert.equal(rows[0].querySelectorAll('td').length, rows[5].querySelectorAll('td').length, 'no column of its own');
    assert.equal(spot[4], null, 'a 15-minute window has no strike in its ticker, so no figure');
    assert.equal(spot[5], null, 'a market that isn’t Bitcoin is untouched');
    assert.equal(note.textContent, 'Distances to the strike are from Bitcoin at $113,420.00 (Coinbase, 4s ago).');
    assert.doesNotMatch(note.getAttribute('class'), /behind/);
    assert.deepEqual(f.requests.map(({path}) => path).filter((p) => p.startsWith('/api/explore')), ['/api/explore?q=&sort=v24&page=0'], 'no read per row');
    f.clearTimers();
  });

  // A 15-minute window's market page reads "Target Price: $113,512.08" from the contract's name when no strike is
  // stored, but its Explore row showed no distance. The server now measures the row from that target and says so
  // (`vs.from`); the row names it "target price", with the market page's own words on hover, never "strike".
  test(`${name}: a 15-minute row measures from the target price in its title, named as its market page names it`, async () => {
    const m15 = row('KXBTC15M-26OCT271145-45', {ti: 'BTC price up in next 15 mins?', su: 'Target Price: $113,512.08', vs: {side: 'below', diff: -92.08, pct: -0.081, from: 'title'}});
    const {f, rows} = await list({markets: [m15, ROWS[0]], spot: SPOT});
    const spot = rows.map((r) => r.querySelector('.xspot'));
    assert.equal(spot[0].textContent.replace(/\u00a0/g, ' '), 'Spot vs target price −$92 · 0.08%');
    assert.equal(spot[0].getAttribute('title'), 'Target price from the contract’s title, as on its market page');
    assert.match(rows[0].querySelector('td.name').textContent, /Target Price: \$113,512\.08/, 'the target it measures from shows in the row');
    assert.equal(spot[1].textContent.replace(/\u00a0/g, ' '), 'Spot vs strike +$420 · 0.4%');
    assert.equal(spot[1].getAttribute('title'), null);
    f.clearTimers();
    const at = await list({markets: [{...m15, vs: {side: 'at', diff: 0, pct: 0, from: 'title'}}], spot: SPOT});
    assert.equal(at.rows[0].querySelector('.xspot').textContent, 'Spot vs target price at the target price');
    at.f.clearTimers();
    // The hot rail reads it the same way.
    const {f: g, el} = await rail({markets: [{...m15, h: [.4, .5]}], spot: SPOT});
    assert.match(el.querySelector('.hot-when').textContent, /Spot vs target price −\$92 ·\s0\.08%$/);
    const label = el.querySelector('.hot-row').getAttribute('aria-label');
    if (label) assert.match(label, /Spot vs target price −\$92/);
    g.clearTimers();
  });

  test(`${name}: an old, missing or failed spot leaves the figures out and says why in one line above the list`, async () => {
    const strip = (ms) => ms.map(({vs, ...m}) => m);  // the server sends no `vs` then
    for (const [spot, words] of [[{...SPOT, age_s: 840, stale: true}, 'Bitcoin’s spot feed is 14 min old, so distances to the strike are left out until it catches up.'],
      [null, 'No Bitcoin price stored in the last day, so distances to the strike are left out.'],
      [{failed: true}, 'Bitcoin’s latest stored price didn’t load, so distances to the strike are left out.']]) {
      const {f, body, note} = await list({markets: strip(ROWS), spot});
      assert.equal(note.textContent, words);
      assert.match(note.getAttribute('class'), /\bbehind\b/);
      assert.equal(body.querySelectorAll('.xspot').length, 0);
      assert.equal(body.querySelectorAll('.xspot-note').length, 1);
      f.clearTimers();
    }
  });

  test(`${name}: a list with no Bitcoin strike on it has no spot line and no figures`, async () => {
    const {f, body, note} = await list({markets: [ROWS[5]]});
    assert.equal(note, null);
    assert.equal(body.querySelectorAll('.xspot').length, 0);
    assert.doesNotMatch(body.innerHTML, /Spot vs|Bitcoin at/);
    f.clearTimers();
  });

  const rail = async (hot) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/explore/hot') return response({at: new Date().toISOString(), ...hot});
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {}, policy: null, totals: {tried: 0, passed: 0}, v: 'v1'});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }, storage: storageFor(new Map(railOpenWide)), matchMedia: () => ({matches: false})});
    f.S.hot = null; f.S.hotAt = 0;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    return {f, el: f.document.getElementById('hotrail')};
  };

  test(`${name}: the hot-markets rail says when each market closes and how far spot is from a Bitcoin strike`, async () => {
    const {f, el} = await rail({markets: ROWS.map((m) => ({...m, h: [.4, .5]})), spot: SPOT});
    const rows = el.querySelectorAll('.hot-row');
    assert.equal(rows.length, 6);
    const when = rows.map((r) => r.querySelector('.hot-when'));
    assert.match(when[0].textContent, /^Closes .*\d.*Spot vs strike \+\$420 ·\s0\.4%$/);
    assert.match(when[2].textContent, /Spot vs bucket in range$/);
    assert.match(when[4].textContent, /^Closes .*\d/);  // every market with a close says it, not only Bitcoin's
    assert.doesNotMatch(when[4].textContent, /Spot/);
    assert.equal(when[5], null, 'a game with no hour in its ticker says no close');
    // Read out with the row, where the row is named for a screen reader as a whole.
    const label = rows[0].getAttribute('aria-label');
    if (label) assert.match(label, /Closes .*Spot vs strike \+\$420 ·\s0\.4%/);
    assert.equal(el.querySelector('.hot-note'), null, 'a fresh spot needs no line');
    f.clearTimers();
  });

  // Every row leads with a plain name and the market chip the rest of the app uses, never the raw ticker.
  // Meridian printed the ticker (KXBTCD-26OCT2812-T112999.99) as a line of each row with no chip, and both
  // themes named an untitled contract by its ticker (Explore, the hot rail).
  const NAMED = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above $X at 5pm ET', category: 'Crypto', close_hour_et: 17},
    {key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin 15-minute up/down', category: 'Crypto'}];
  const NAME_ROWS = [row('KXBTCD-26OCT2812-T112999.99', {ti: 'Bitcoin price at 12pm EDT?', su: '$113,000 or above', ct: '2026-10-28T16:00:00Z'}),
    row('KXBTCD-26OCT2817-T112999.99', {ti: 'Bitcoin price at 5pm EDT?', su: '$113,000 or above'}),
    row('KXBTC-26OCT2817-B113250', {ti: 'Bitcoin price range at 5pm EDT?', su: '$113,000 to 113,499.99'}),
    row('KXBTC15M-26OCT271145-45', {ti: 'BTC price up in next 15 mins?'}),
    row('KXFEDDECISION-26DEC-H0', {s: 'KXFEDDECISION', ti: '', su: '', ct: null})];
  const CHIPS = ['BTC above $X at noon ET', 'BTC above $X at 5pm ET', 'BTC range at 5pm ET', 'BTC 15-min up/down', null];
  const TICKER = /KX[A-Z0-9]+-\w/;

  test(`${name}: Explore's rows lead with the plain name and the market chip, never the raw ticker or series`, async () => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore?') ? response({at: new Date().toISOString(), total: 5, shown: 5, matched: 5, page: 0, per: 40, sort: 'v24', markets: NAME_ROWS}) : response({}))});
    f.S.me.markets = NAMED;
    f.location.pathname = '/explore'; f.location.search = '';
    await f.viewExplore(); await settle();
    const rows = f.root.querySelectorAll('#xbody tbody tr');
    assert.equal(rows.length, 5);
    rows.forEach((r, i) => {
      const cell = r.querySelector('td.name'), link = cell.querySelector('a[href^="/explore?m="]');
      assert.doesNotMatch(cell.textContent, TICKER, `row ${i} prints no ticker`);
      assert.doesNotMatch(link.getAttribute('aria-label') || '', TICKER, `row ${i} reads out no ticker`);
      assert.doesNotMatch(link.getAttribute('title') || '', TICKER);
      const chip = cell.querySelector('.mk');
      if (CHIPS[i]) assert.ok(chip && chip.textContent.startsWith(CHIPS[i]), `row ${i} has its market chip`);
      else assert.equal(chip, null, 'no chip rather than the raw series');
    });
    assert.match(rows[4].querySelector('td.name').textContent, /Kalshi contract/, 'an untitled contract is named as a position is');
    f.clearTimers();
  });

  test(`${name}: the hot rail names an untitled contract plainly and never reads out its ticker`, async () => {
    const {f, el} = await rail({markets: NAME_ROWS.map((m) => ({...m, h: [.4, .5]}))});
    const rows = el.querySelectorAll('.hot-row');
    assert.equal(rows.length, 5);
    rows.forEach((r, i) => {
      assert.doesNotMatch(r.textContent, TICKER, `hot row ${i} shows no ticker`);
      assert.doesNotMatch(r.getAttribute('aria-label') || '', TICKER, `hot row ${i} reads out no ticker`);
    });
    assert.match(rows[4].textContent, /Kalshi contract/);
    f.clearTimers();
  });

  test(`${name}: with an old spot the rail leaves the figures out and says the feed's age once`, async () => {
    const {f, el} = await rail({markets: ROWS.map(({vs, ...m}) => ({...m, h: [.4, .5]})), spot: {...SPOT, age_s: 840, stale: true}});
    assert.equal(el.querySelectorAll('.hot-note').length, 1);
    assert.match(el.querySelector('.hot-note').textContent, /^Bitcoin’s spot feed is 14 min old/);
    assert.equal(el.querySelectorAll('.xspot').length, 0);
    assert.match(el.querySelectorAll('.hot-when')[0].textContent, /^Closes /, 'the close times stay');
    f.clearTimers();
  });
}
