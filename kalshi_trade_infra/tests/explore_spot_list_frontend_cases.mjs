// Explore's list and the hot-markets rail, run against each bundle's offline DOM/transport harness: a
// Bitcoin contract's row says how far stored spot is from its strike (the server's `vs`), a bucket spot
// sits in says "in range", and without a fresh spot the figures are left out under one line that says why.
// Hot markets also say when they close (`ct`), as Explore's rows do. Every row, in either list, is named by
// its title and market chip, never by its raw ticker.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

// Closes a few hours from now: a close already past reads "Closed" (the market page's and Explore's own walk, 2026-10-28).
const LATER = new Date(Date.now() + 5 * 3600e3).toISOString().replace(/\.\d+Z$/, 'Z');
const SPOT = {price: 113420, at: '2026-10-27T11:00:00Z', age_s: 4, stale: false};
const row = (t, over = {}) => ({t, s: t.split('-')[0], ti: 'Bitcoin price on Oct 27, 2026 at 5pm EDT?', su: '', bid: .48, ask: .52, v24: 900, oi: 50,
  ct: LATER, ...over});
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
    assert.match(el.querySelector('.hot-when').textContent, /Spot vs target price −\$92\u00a0· 0\.08%$/);
    const label = el.querySelector('.hot-row').getAttribute('aria-label');
    if (label) assert.match(label, /Spot vs target price −\$92/);
    g.clearTimers();
  });

  // A 15-minute window's market page names its line "Target price" whether it is read from the title or stored, but
  // its Explore row (and the hot rail) said "Spot vs strike" once a strike was stored (no `vs.from: 'title'`).
  test(`${name}: a 15-minute row with a stored strike still says target price, as its market page does`, async () => {
    const m15 = row('KXBTC15M-26OCT271145-45', {ti: 'BTC price up in next 15 mins?', su: 'Target Price: $113,512.08', vs: {side: 'below', diff: -92.08, pct: -0.081}});
    const {f, rows} = await list({markets: [m15, ROWS[0]], spot: SPOT});
    const spot = rows.map((r) => r.querySelector('.xspot'));
    assert.equal(spot[0].textContent.replace(/ /g, ' '), 'Spot vs target price −$92 · 0.08%');
    assert.equal(spot[0].getAttribute('title'), null, 'a stored line is not read from the title');
    assert.equal(spot[1].textContent.replace(/ /g, ' '), 'Spot vs strike +$420 · 0.4%', 'a daily contract keeps "strike"');
    f.clearTimers();
    const at = await list({markets: [{...m15, vs: {side: 'at', diff: 0, pct: 0, from: 'record'}}], spot: SPOT});
    assert.equal(at.rows[0].querySelector('.xspot').textContent, 'Spot vs target price at the target price');
    at.f.clearTimers();
    const {f: g, el} = await rail({markets: [{...m15, h: [.4, .5]}], spot: SPOT});
    assert.match(el.querySelector('.hot-when').textContent, /Spot vs target price −\$92\u00a0· 0\.08%$/);
    const label = el.querySelector('.hot-row').getAttribute('aria-label');
    if (label) assert.match(label, /Spot vs target price −\$92/);
    assert.doesNotMatch(el.textContent + (label || ''), /strike/);
    g.clearTimers();
  });

  // A list of 15-minute windows only said "Distances to the strike are from Bitcoin at …" over rows that each said
  // "Spot vs target price". The line names what the rows shown measure from, both when the list holds both, and a
  // 15-minute row with a stored strike is its target price too, as its market page says it.
  test(`${name}: the line above the list names what its rows measure from, target price for 15-minute windows`, async () => {
    const m15 = (t, vs) => row(t, {ti: 'BTC price up in next 15 mins?', su: 'Target Price: $113,512.08', vs});
    const titled = m15('KXBTC15M-26OCT271145-45', {side: 'below', diff: -92.08, pct: -0.081, from: 'title'});
    const stored = m15('KXBTC15M-26OCT271200-00', {side: 'above', diff: 40, pct: 0.035});
    const only15 = await list({markets: [titled, stored, ROWS[5]], spot: SPOT});
    assert.equal(only15.note.textContent, 'Distances to the target price are from Bitcoin at $113,420.00 (Coinbase, 4s ago).');
    assert.deepEqual(only15.rows.slice(0, 2).map((r) => r.querySelector('.xspot').textContent.replace(/ /g, ' ')),
      ['Spot vs target price −$92 · 0.08%', 'Spot vs target price +$40 · 0.04%'], 'a stored 15-minute strike is its target price too');
    assert.doesNotMatch(only15.body.innerHTML, /strike/i);
    only15.f.clearTimers();
    const atStored = await list({markets: [{...stored, vs: {side: 'at', diff: 0, pct: 0}}], spot: SPOT});
    assert.equal(atStored.rows[0].querySelector('.xspot').textContent, 'Spot vs target price at the target price');
    atStored.f.clearTimers();
    const both = await list({markets: [titled, ROWS[0]], spot: SPOT});
    assert.equal(both.note.textContent, 'Distances to the strike or target price are from Bitcoin at $113,420.00 (Coinbase, 4s ago).');
    both.f.clearTimers();
    // A 15-minute row with no figure (no target in its name) leaves the line to the rows that have one.
    const strikes = await list({markets: [ROWS[4], ROWS[0]], spot: SPOT});
    assert.equal(strikes.note.textContent, 'Distances to the strike are from Bitcoin at $113,420.00 (Coinbase, 4s ago).');
    strikes.f.clearTimers();
    // With no figure to show, the line names what the Bitcoin rows would measure from.
    const old = await list({markets: [{...titled, vs: undefined}], spot: {...SPOT, age_s: 840, stale: true}});
    assert.equal(old.note.textContent, 'Bitcoin’s spot feed is 14 min old, so distances to the target price are left out until it catches up.');
    old.f.clearTimers();
    const {f: g, el} = await rail({markets: [{...titled, vs: undefined, h: [.4, .5]}], spot: null});
    assert.equal(el.querySelector('.hot-note').textContent, 'No Bitcoin price stored in the last day, so distances to the target price are left out.');
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
    assert.match(when[0].textContent, /^Closes .*\d.*Spot vs strike \+\$420\u00a0· 0\.4%$/);
    assert.match(when[2].textContent, /Spot vs bucket in range$/);
    assert.match(when[4].textContent, /^Closes .*\d/);  // every market with a close says it, not only Bitcoin's
    assert.doesNotMatch(when[4].textContent, /Spot/);
    assert.equal(when[5], null, 'a game with no hour in its ticker says no close');
    // Read out with the row, where the row is named for a screen reader as a whole.
    const label = rows[0].getAttribute('aria-label');
    if (label) assert.match(label, /Closes .*Spot vs strike \+\$420\u00a0· 0\.4%/);
    assert.equal(el.querySelector('.hot-note'), null, 'a fresh spot needs no line');
    f.clearTimers();
  });

  // Every row leads with a plain name and the market chip the rest of the app uses, never the raw ticker.
  // Meridian printed the ticker (KXBTCD-26OCT2812-T112999.99) as a line of each row with no chip, and both
  // themes named an untitled contract by its ticker (Explore, the hot rail).
  const NAMED = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET', category: 'Crypto', close_hour_et: 17},
    {key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin 15-minute up/down', category: 'Crypto'}];
  const NAME_ROWS = [row('KXBTCD-26OCT2812-T112999.99', {ti: 'Bitcoin price at 12pm EDT?', su: '$113,000 or above', ct: LATER}),
    row('KXBTCD-26OCT2817-T112999.99', {ti: 'Bitcoin price at 5pm EDT?', su: '$113,000 or above'}),
    row('KXBTC-26OCT2817-B113250', {ti: 'Bitcoin price range at 5pm EDT?', su: '$113,000 to 113,499.99'}),
    row('KXBTC15M-26OCT271145-45', {ti: 'BTC price up in next 15 mins?'}),
    row('KXFEDDECISION-26DEC-H0', {s: 'KXFEDDECISION', ti: '', su: '', ct: null})];
  const CHIPS = ['BTC above set price at noon ET', 'BTC above set price at 5pm ET', 'BTC range at 5pm ET', 'BTC 15-min up/down', null];
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

  // Walked 2026-10-28 in both themes: Tau's search box asked for "series, tickers" (words a new customer doesn't
  // have) and its column read "Open int." where Meridian's and the market page's read "Open interest".
  test(`${name}: Explore's search box and open-interest column read in the same plain words in both themes`, async () => {
    const {f, rows} = await list({markets: ROWS});
    assert.equal(f.root.querySelector('#xq').getAttribute('placeholder'), 'Search markets');
    const labs = rows[0].querySelectorAll('td').map((td) => td.getAttribute('data-lab'));
    assert.ok(labs.includes('Open interest'), labs.join(', '));
    assert.ok(!labs.includes('Open int.'));
    assert.doesNotMatch(f.root.querySelector('#xbody thead').textContent, /Open int\./);
    f.clearTimers();
  });

  // Walked 2026-10-28: before the feed came in, the rail said "Warming up — the live book fills in a minute":
  // "live book" is a trader's phrase, and reads like the live-money book.
  test(`${name}: the hot rail before the feed comes in says what will show there, in plain words`, async () => {
    const {f, el} = await rail({at: null, markets: []});
    assert.equal(el.querySelector('.hot-empty').textContent, 'Warming up: the hottest markets show here within a minute.');
    assert.doesNotMatch(el.textContent, /live book/);
    // With no feed time there is nothing before the link: Tau's footer read "· See all markets →".
    assert.match(el.querySelector('.hot-ft').textContent.trim(), /^See all markets →$/);
    f.clearTimers();
    const {f: h, el: full} = await rail({markets: ROWS.map((m) => ({...m, h: [.4, .5]}))});
    assert.doesNotMatch(full.querySelector('.hot-ft').textContent.trim(), /^·/);
    h.clearTimers();
    const {f: g} = await list({markets: ROWS});
    assert.doesNotMatch(g.root.textContent, /live book/, 'nor does Explore’s own heading');
    g.clearTimers();
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

  // Walked 2026-10-30: a hot-markets row opened Kalshi in a new tab, where the same contract's Explore row opens its
  // page in Tau (the countdown, spot against the strike, the reader's own positions). The row now opens that page.
  test(`${name}: a hot-markets row opens the market's page in Tau, as its Explore row does`, async () => {
    const {f, el} = await rail({markets: NAME_ROWS.map((m) => ({...m, h: [.4, .5]}))});
    const rows = el.querySelectorAll('.hot-row');
    assert.equal(rows.length, 5);
    rows.forEach((r, i) => {
      assert.equal(r.getAttribute('href'), '/explore?m=' + encodeURIComponent(NAME_ROWS[i].t), `hot row ${i}`);
      assert.equal(r.getAttribute('target'), null, 'opens in place, not a new tab');
      assert.doesNotMatch(r.innerHTML + (r.getAttribute('aria-label') || ''), /kalshi\.com|Opens Kalshi|new tab/);
    });
    // The page's own link handler takes it there in place.
    const clicks = f.documentListeners.filter(([type]) => type === 'click').map(([, cb]) => cb);
    let prevented = false;
    const target = rows[0].querySelector('.hot-title');
    for (const cb of clicks) cb({target, preventDefault: () => { prevented = true; }});
    await settle();
    assert.equal(prevented, true);
    assert.equal(f.navigations.at(-1), '/explore?m=' + encodeURIComponent(NAME_ROWS[0].t));
    assert.equal(f.location.search, '?m=' + encodeURIComponent(NAME_ROWS[0].t));
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

  // Walked 2026-10-28 with a 15-minute window three minutes from its close: its row said "closes 01:39 CDT" with no
  // time left, said the same once 01:39 had passed, and a $5 distance read "0.00%".
  test(`${name}: an Explore row in its last hour says how long is left, counts down with the list, and says closed once past`, async () => {
    const at = (s) => new Date(Date.now() + s * 1000).toISOString();
    const markets = [row('KXBTC15M-26OCT280239-39', {ti: 'BTC price up in next 15 mins?', su: 'Target Price: $113,165.84', ct: at(190),
      vs: {side: 'below', diff: -4.6, pct: -0.004, from: 'title'}}), row('KXBTCD-26OCT2803-T112999.99', {su: '$113,000 or above', ct: at(-120)}),
      row('KXBTCD-26OCT2817-T112999.99', {su: '$113,000 or above', ct: at(5 * 3600)})];
    const {f, rows} = await list({markets, spot: SPOT});
    const close = () => f.root.querySelectorAll('#xbody tbody tr').map((r) => r.querySelector('[data-close]').textContent.replace(/ /g, ' '));
    const [soon, past, later] = close();
    assert.match(soon, /^closes \S.* · in 3 min$/i);
    assert.match(past, /^closed \S/i); assert.doesNotMatch(past, / in /);
    assert.match(later, /^closes \S/i); assert.doesNotMatch(later, / in /, 'a close hours off needs no count');
    assert.equal(rows[0].querySelector('.xspot').textContent.replace(/ /g, ' '), 'Spot vs target price −$5 · under 0.01%');
    // The list's own poll works the count out again: a minute on it reads 2 min, and past the close "closed".
    f.shiftClock(60000); for (const run of [...f.intervals.values()]) await run(); await settle();
    assert.match(close()[0], /^closes \S.* · in 2 min$/i);
    f.shiftClock(150000); for (const run of [...f.intervals.values()]) await run(); await settle();
    assert.match(close()[0], /^closed \S/i);
    f.clearTimers();
  });

  // Explore's Bitcoin filter: one "All markets / Bitcoin" choice beside the search, read by the server (?show=bitcoin
  // keeps the Bitcoin series' contracts) and kept in the address with the search and sort, so a reload keeps it.
  const BTC_ROWS = ROWS.slice(0, 5);
  const explore = async (search, answer) => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore?') ? response({at: new Date().toISOString(), total: 6, shown: 6, page: 0, per: 40, sort: 'v24',
      ...(typeof answer === 'function' ? answer(path) : answer)}) : response({}))});
    f.location.pathname = '/explore'; f.location.search = search;
    await f.viewExplore(); await settle();
    return {f, asked: () => f.requests.map(({path}) => path).filter((p) => p.startsWith('/api/explore?'))};
  };
  const pressed = (f) => f.root.querySelectorAll('[data-show]').map((b) => [b.textContent, b.getAttribute('aria-pressed')]);
  const byShow = (path) => (path.includes('show=bitcoin') ? {markets: BTC_ROWS, matched: 5, show: 'bitcoin', spot: SPOT} : {markets: ROWS, matched: 6, show: 'all', spot: SPOT});

  test(`${name}: Explore's Bitcoin choice shows only Bitcoin markets, and All markets puts every market back`, async () => {
    const {f, asked} = await explore('', byShow);
    const group = f.root.querySelector('.xshow');
    assert.equal(group.getAttribute('role'), 'group'); assert.equal(group.getAttribute('aria-label'), 'Show');
    assert.deepEqual(pressed(f), [['All markets', 'true'], ['Bitcoin', 'false']]);
    assert.deepEqual(asked(), ['/api/explore?q=&sort=v24&page=0'], 'every market until Bitcoin is picked');
    f.root.querySelector('[data-show="bitcoin"]').onclick(); await settle();
    assert.equal(asked().at(-1), '/api/explore?q=&sort=v24&page=0&show=bitcoin');
    assert.equal(f.location.search, '?q=&sort=v24&page=0&show=bitcoin', 'the choice is kept in the address');
    assert.deepEqual(pressed(f), [['All markets', 'false'], ['Bitcoin', 'true']]);
    assert.equal(f.root.querySelectorAll('#xbody tbody tr').length, 5);
    assert.match(f.root.querySelector('#xfigs').textContent, /Bitcoin markets\s*5/);
    // The list's poll keeps asking for Bitcoin, and a sort or search keeps it too.
    for (const run of [...f.intervals.values()]) await run(); await settle();
    assert.equal(asked().at(-1), '/api/explore?q=&sort=v24&page=0&show=bitcoin');
    f.root.querySelectorAll('[data-sort="oi"]')[0].onclick(); await settle();
    assert.equal(asked().at(-1), '/api/explore?q=&sort=oi&page=0&show=bitcoin');
    f.root.querySelector('[data-show="all"]').onclick(); await settle();
    assert.equal(asked().at(-1), '/api/explore?q=&sort=oi&page=0');
    assert.equal(f.location.search, '?q=&sort=oi&page=0');
    assert.deepEqual(pressed(f), [['All markets', 'true'], ['Bitcoin', 'false']]);
    assert.equal(f.root.querySelectorAll('#xbody tbody tr').length, 6);
    assert.doesNotMatch(f.root.querySelector('#main').textContent, /KXBTC|show=|BTC_SERIES/);
    f.clearTimers();
  });

  test(`${name}: a reload of Explore with Bitcoin picked keeps Bitcoin, the search and the sort`, async () => {
    const {f, asked} = await explore('?q=5pm&sort=oi&page=0&show=bitcoin', byShow);
    assert.deepEqual(asked(), ['/api/explore?q=5pm&sort=oi&page=0&show=bitcoin']);
    assert.deepEqual(pressed(f), [['All markets', 'false'], ['Bitcoin', 'true']]);
    // Any other value is every market, never an error.
    const g = await explore('?show=nonsense', byShow);
    assert.deepEqual(g.asked(), ['/api/explore?q=&sort=v24&page=0']);
    assert.deepEqual(pressed(g.f), [['All markets', 'true'], ['Bitcoin', 'false']]);
    f.clearTimers(); g.f.clearTimers();
  });

  test(`${name}: with no Bitcoin market open, Explore says so plainly and offers every market`, async () => {
    const {f, asked} = await explore('?show=bitcoin', (path) => (path.includes('show=bitcoin') ? {markets: [], matched: 0, show: 'bitcoin'} : {markets: ROWS, matched: 6}));
    const empty = f.root.querySelector('#xbody .empty');
    assert.equal(empty.querySelector('h2').textContent, 'No Bitcoin markets are open right now');
    assert.equal(empty.querySelector('p').textContent, 'Kalshi opens new Bitcoin markets through the day, and they show here within about a minute.');
    assert.doesNotMatch(empty.textContent, /KX|series|show=|error|null|undefined/i);
    empty.querySelector('[data-xretry]').onclick(); await settle();
    assert.equal(asked().at(-1), '/api/explore?q=&sort=v24&page=0&show=bitcoin', 'Try again asks for Bitcoin again');
    f.root.querySelector('#xbody [data-xall]').onclick(); await settle();
    assert.equal(asked().at(-1), '/api/explore?q=&sort=v24&page=0');
    assert.deepEqual(pressed(f), [['All markets', 'true'], ['Bitcoin', 'false']]);
    assert.equal(f.root.querySelectorAll('#xbody tbody tr').length, 6);
    f.clearTimers();
    // A search that finds no Bitcoin market says that, not that none is open.
    const s = await explore('?q=ethereum&show=bitcoin', {markets: [], matched: 0, show: 'bitcoin'});
    assert.equal(s.f.root.querySelector('#xbody .empty h2').textContent, 'No Bitcoin markets match “ethereum”');
    assert.ok(s.f.root.querySelector('#xbody [data-xall]'), 'a way back to every market');
    s.f.clearTimers();
    // Before the feed's first copy there is no list at all: that says the list hasn't come in, not that Bitcoin is closed.
    const n = await explore('?show=bitcoin', {at: null, total: 0, shown: 0, markets: [], matched: 0});
    assert.equal(n.f.root.querySelector('#xbody .empty h2').textContent, 'No markets to show yet');
    n.f.clearTimers();
  });

  // Walk 2026-10-30: a 15-minute row a minute past its close said "Closed 04:15 UTC · Spot vs target price +$72", read as
  // its result, though Bitcoin's price after the close doesn't decide it. A row past its close shows no distance, on
  // Explore's list and on the hot rail; an open row beside it keeps its own.
  test(`${name}: a Bitcoin row past its close shows no distance from spot, on the list and the rail`, async () => {
    const PAST = new Date(Date.now() - 60e3).toISOString().replace(/\.\d+Z$/, 'Z');
    const shut = row('KXBTC15M-26OCT300015-15', {ti: 'BTC price up in next 15 mins?', su: 'Target Price: $113,180.52', ct: PAST, vs: {side: 'above', diff: 71.87, pct: 0.064}});
    const {f, rows, note} = await list({markets: [shut, ROWS[0]], spot: SPOT});
    assert.equal(rows[0].querySelector('.xspot'), null);
    assert.match(rows[0].querySelector('td.name').textContent, /closed \S/i, 'it still says it closed');
    assert.doesNotMatch(rows[0].textContent, /\+\$72|Spot vs/);
    assert.equal(rows[1].querySelector('.xspot').textContent.replace(/ /g, ' '), 'Spot vs strike +$420 · 0.4%');
    assert.ok(note, 'the open row still measures from the spot the note names');
    f.clearTimers();
    const {f: g, el} = await rail({markets: [shut, ROWS[0]].map((m) => ({...m, h: [.4, .5]})), spot: SPOT});
    const hot = el.querySelectorAll('.hot-row');
    assert.match(hot[0].querySelector('.hot-when').textContent, /^Closed \S/);
    assert.doesNotMatch(hot[0].textContent + (hot[0].getAttribute('aria-label') || ''), /Spot vs|\+\$72/);
    assert.match(hot[1].querySelector('.hot-when').textContent, /Spot vs strike \+\$420/);
    g.clearTimers();
  });

  // Walk 2026-10-30: Explore → Bitcoin → a Bitcoin market, then the page's own "← Back to Explore" went to /explore, which
  // dropped the Bitcoin choice (and the search and sort): the reader came back to every market. It now returns to the
  // list the reader left, kept for the tab so a reload of the market page keeps it too.
  test(`${name}: a market page's Back to Explore returns to the Bitcoin list the reader left`, async () => {
    const T = 'KXBTCD-26OCT2717-T112999.99';
    const market = {ticker: T, series: 'KXBTCD', title: 'Bitcoin price on Oct 27, 2026 at 5pm EDT?', sub: '$113,000 or above', points: [], yes_bid: '0.48', yes_ask: '0.52', close_time: LATER, status: 'active'};
    const fetchImpl = (path) => (path.startsWith('/api/explore?') ? response({at: new Date().toISOString(), total: 6, shown: 6, page: 0, per: 40, sort: 'oi', ...byShow(path)})
      : path.startsWith('/api/explore/market?') ? (path.includes('KXGONE') ? response({error: 'Kalshi has no market here.'}, 404) : response(market)) : response({}));
    const tab = new Map(), session = {getItem: (k) => tab.get(k) ?? null, setItem: (k, v) => tab.set(k, String(v)), removeItem: (k) => tab.delete(k)};
    const back = (f) => f.root.querySelectorAll('a').find((a) => /Back to Explore/.test(a.textContent)).getAttribute('href').replace(/&amp;/g, '&');
    const f = frontend({fetchImpl, session});
    f.location.pathname = '/explore'; f.location.search = '?q=5pm&sort=oi&page=0&show=bitcoin';
    await f.viewExplore(); await settle();
    f.location.search = '?m=' + T;
    await f.viewMarketDetail(T); await settle();
    assert.equal(back(f), '/explore?q=5pm&sort=oi&page=0&show=bitcoin', 'Bitcoin, the search and the sort are still on');
    // Walked 2026-10-30 at 390px: the only way back sat at the foot, about three screens down. A small link at the top
    // goes to the same list, filter kept, beside the foot's.
    const backs = f.root.querySelectorAll('a').filter((a) => /Back to Explore/.test(a.textContent)).map((a) => a.getAttribute('href').replace(/&amp;/g, '&'));
    assert.deepEqual(backs, ['/explore?q=5pm&sort=oi&page=0&show=bitcoin', '/explore?q=5pm&sort=oi&page=0&show=bitcoin'], 'one at the top, one at the foot');
    assert.ok(f.root.querySelector('.mk-back a'), 'the top one is above the page title');
    assert.match(f.root.innerHTML, /class="mk-back"[^]*class="board-title"/);
    f.clearTimers();
    // A reload of the market page in the same tab keeps it, and so does the page Kalshi has no market for.
    const g = frontend({fetchImpl, session});
    await g.viewMarketDetail(T); await settle();
    assert.equal(back(g), '/explore?q=5pm&sort=oi&page=0&show=bitcoin');
    await g.viewMarketDetail('KXGONE-1'); await settle();
    assert.equal(back(g), '/explore?q=5pm&sort=oi&page=0&show=bitcoin');
    g.clearTimers();
    // Picking All markets again is what Back returns to.
    const a = frontend({fetchImpl, session});
    a.location.pathname = '/explore'; a.location.search = '?show=bitcoin';
    await a.viewExplore(); await settle();
    a.root.querySelector('[data-show="all"]').onclick(); await settle();
    await a.viewMarketDetail(T); await settle();
    assert.equal(back(a), '/explore?q=&sort=v24&page=0');
    a.clearTimers();
    // A tab that never showed the list (a shared link), or storage that throws, goes to Explore as it opens.
    const h = frontend({fetchImpl});
    await h.viewMarketDetail(T); await settle();
    assert.equal(back(h), '/explore');
    h.clearTimers();
    const odd = frontend({fetchImpl, session: {getItem: () => '/explore?m=KXBTCD-X', setItem() { throw new Error('private mode'); }}});
    await odd.viewMarketDetail(T); await settle();
    assert.equal(back(odd), '/explore', 'never back to a market page');
    odd.clearTimers();
  });

  // Walked 2026-10-30: a page headed "$113,000 or above" measured spot from its stored strike, $112,999.99. A row named
  // the same way measures as its page now does, from $113,000 (the name's threshold, a cent past the strike), so the two
  // agree on which side of the line spot is: at $113,000.00 spot is at it, at $112,999.99 a cent under it.
  test(`${name}: a row named "$113,000 or above" measures from $113,000, as its market page does`, async () => {
    const T = 'KXBTCD-26OCT2717-T112999.99';
    const named = (vs, su = '$113,000 or above') => row(T, {su, vs});
    const {f, rows} = await list({markets: [named({side: 'above', diff: 0.01, pct: 0}), named({side: 'at', diff: 0, pct: 0}),
      named({side: 'above', diff: 500.5, pct: 0.443}), named({side: 'above', diff: 500.5, pct: 0.443}, '$113,500 or above')], spot: SPOT});
    const spot = rows.map((r) => r.querySelector('.xspot').textContent.replace(/⁠/g, '').replace(/ /g, ' '));
    assert.equal(spot[0], 'Spot vs strike at the strike', 'spot at $113,000.00 is at the line, not above it');
    assert.equal(spot[1], 'Spot vs strike −$0 · under 0.01%', 'spot at $112,999.99 is under the line, not at it');
    assert.equal(spot[2], 'Spot vs strike +$500 · 0.4%', '$500.49 over $113,000, as its page says, not $500.50 over $112,999.99');
    assert.equal(spot[3], 'Spot vs strike +$501 · 0.4%', 'a name whose figure isn’t the strike’s keeps the stored strike');
    f.clearTimers();
    const {f: g, el} = await rail({markets: [{...named({side: 'above', diff: 500.5, pct: 0.443}), h: [.4, .5]}], spot: SPOT});
    assert.match(el.querySelector('.hot-when').textContent, /Spot vs strike \+⁠?\$500 · 0\.4%$/);
    const label = el.querySelector('.hot-row').getAttribute('aria-label');
    if (label) assert.match(label, /Spot vs strike \+⁠?\$500\b/);
    g.clearTimers();
  });

  // Meridian's hot rail at 1280px wrapped "Closes 05:00 UTC · in 58 min" between "58" and "min": the countdown's number
  // keeps its unit, on the rail and on Explore's rows.
  test(`${name}: a close inside the hour counts down with its number and unit together, on the rail and the list`, async () => {
    const soon = row('KXBTCD-26OCT2717-T112999.99', {su: '$113,000 or above', ct: new Date(Date.now() + 58.5 * 60e3).toISOString()});
    const {f, el} = await rail({markets: [{...soon, h: [.4, .5]}]});
    const when = el.querySelector('.hot-when').textContent;
    assert.match(when, /in 58 min/);
    assert.doesNotMatch(when, /58 min/);
    f.clearTimers();
    const {f: g, rows} = await list({markets: [soon]});
    assert.match(rows[0].querySelector('td.name').textContent, /in 58 min/);
    g.clearTimers();
  });

  // A close chip's time keeps its zone (keepZone, as the market page's Closes figure does): the rail and a row ended a line
  // on "05:00" with "UTC" alone on the next. Today's close ("05:00 UTC") and another day's ("Oct 28, 05:00 UTC") alike.
  test(`${name}: a close chip keeps its time and zone together, on the rail and the list`, async () => {
    const soon = row('KXBTCD-26OCT2717-T112999.99', {su: '$113,000 or above', ct: new Date(Date.now() + 30 * 60e3).toISOString()});
    const far = row('KXBTCD-26OCT2717-T113999.99', {su: '$114,000 or above', ct: new Date(Date.now() + 3 * 86400e3).toISOString()});
    const together = (text, what) => {
      assert.match(text, /\d{2}:\d{2} [A-Z][\w+:-]*/, `${what}: the zone follows its time with a no-break space`);
      assert.doesNotMatch(text, /\d{2}:\d{2} [A-Z]/, `${what}: no break before the zone`);
    };
    const {f, el} = await rail({markets: [{...soon, h: [.4, .5]}, {...far, h: [.4, .5]}]});
    const when = el.querySelectorAll('.hot-when');
    assert.equal(when.length, 2);
    when.forEach((w, i) => together(w.textContent, `rail row ${i}`));
    f.clearTimers();
    const {f: g, rows} = await list({markets: [soon, far]});
    assert.equal(rows.length, 2);
    rows.forEach((r, i) => together(r.querySelector('td.name [data-form="chip"]').textContent, `list row ${i}`));
    g.clearTimers();
  });

  // A row Kalshi sent no name for is named by Tau's label, which reads the strike as Kalshi names it: a KXBTCD -T strike a
  // cent under a whole dollar is "$113,000 or above" (Yes above it, btc_spot.contract_strike), any other keeps its figure.
  test(`${name}: an untitled Bitcoin row names its strike as Kalshi does, "$113,000 or above"`, async () => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore?') ? response({at: new Date().toISOString(), total: 3, shown: 3, matched: 3, page: 0, per: 40, sort: 'v24',
      markets: [row('KXBTCD-26OCT2717-T112999.99', {ti: '', su: ''}), row('KXBTCD-26OCT2717-T114000', {ti: '', su: ''}), row('KXBTCD-26OCT2712-T112999.99', {ti: '', su: ''})]}) : response({}))});
    f.S.me.markets = NAMED;
    f.location.pathname = '/explore'; f.location.search = '';
    await f.viewExplore(); await settle();
    const names = f.root.querySelectorAll('#xbody tbody tr').map((r) => r.querySelector('td.name a[href^="/explore?m="]'));
    const text = (a) => (a.querySelector('strong') || a).textContent;
    assert.equal(text(names[0]), 'Bitcoin $113,000 or above at 5pm ET');
    assert.equal(text(names[1]), 'Bitcoin above $114,000 at 5pm ET');
    assert.equal(text(names[2]), 'Bitcoin $113,000 or above at noon ET');
    // Display only: the row still opens the contract by its own ticker.
    assert.equal(names[0].getAttribute('href'), '/explore?m=KXBTCD-26OCT2717-T112999.99');
    f.clearTimers();
  });
}
