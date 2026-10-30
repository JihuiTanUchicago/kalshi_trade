// Explore (/explore, its list, and a market's page, /explore?m=TICKER) draws byte for byte what it drew before it
// became one file for both themes (page-explore.js, shared page files step: each bundle, app.js and app.meridian.js,
// held its theme's own copy). Each state below is drawn in the offline harness, at desk and phone width, on one fixed
// clock, zone and locale, and its whole DOM (every string the page wrote, every element's attributes and
// hidden/checked/value/focus state), every read and write it sent, what it kept for the tab (sessionStorage) and where
// it went are compared with the snapshot taken from the two bundles before the move. The repo keeps each state's
// fingerprint (explore_parity.json, a sha256 of the state's whole record), not the records themselves.
//
// A change that means to alter Explore's markup writes the records out before and after it, to see what moved:
//   TAU_DUMP_EXPLORE_SNAPSHOTS=/some/dir node --test tests/test_frontend_merge.mjs tests/test_meridian_workspace.mjs
// and then takes the fingerprints again (TAU_WRITE_EXPLORE_SNAPSHOTS=1, one test file at a time: both write the one file).
import assert from './assert_text.mjs';
import {createHash} from 'node:crypto';
import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {test} from 'node:test';

const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

// The element tree as the page left it: one line per element (its tag, attributes, and the state a script sets
// as a property), and the markup of every element a script wrote into, so text between children is in too.
function dump(el) {
  const out = [];
  const walk = (e, depth) => {
    const pad = '  '.repeat(depth);
    const attrs = Object.entries(e.attributes).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).map(([k, v]) => ` ${k}=${JSON.stringify(v)}`).join('');
    const state = [e.hidden ? 'hidden' : '', e.checked ? 'checked' : '', e.disabled ? 'disabled' : '', e.focused ? 'focused' : '', e.value ? 'value=' + JSON.stringify(e.value) : '',
      Object.keys(e.style || {}).length ? 'style=' + JSON.stringify(e.style) : '', e.text !== undefined ? 'text=' + JSON.stringify(e.text) : ''].filter(Boolean).join(' ');
    out.push(`${pad}<${e.tag}${attrs}>${state ? ' {' + state + '}' : ''}`);
    if (e.writes) out.push(`${pad}  html=${JSON.stringify(e.html || '')}`);
    if (e.outer !== undefined) out.push(`${pad}  outer=${JSON.stringify(e.outer)}`);
    e.children.forEach(c => walk(c, depth + 1));
  };
  walk(el, 0);
  return out.join('\n');
}

const SNAP = new URL('./explore_parity.json', import.meta.url);
const sha = (o) => createHash('sha256').update(JSON.stringify(o)).digest('hex');

// One clock, zone and locale for every draw, so a record is the page's alone: the reader's zone and locale show in
// every close, "as of" and chart label. Each draw gets its own Date (the harness's shiftClock moves Date.now).
const NOW = Date.parse('2026-10-26T12:00:00Z');
const at = (ms) => new Date(NOW + ms).toISOString();
const fixedDate = () => {
  const Real = Date;
  class D extends Real {
    constructor(...a) { super(...(a.length ? a : [D.now()])); }
    static now() { return NOW; }
    toLocaleString(l, o) { return super.toLocaleString(l ?? 'en-US', o); }
    toLocaleDateString(l, o) { return super.toLocaleDateString(l ?? 'en-US', o); }
    toLocaleTimeString(l, o) { return super.toLocaleTimeString(l ?? 'en-US', o); }
  }
  return D;
};
const fixedIntl = Object.create(Intl, {
  DateTimeFormat: {value: function DateTimeFormat(l, o) { return new Intl.DateTimeFormat(l ?? 'en-US', o); }},
});

const MARKETS = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET', category: 'Crypto', close_hour_et: 17},
  {key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes', category: 'Crypto'},
  {key: 'nba_game', series: 'KXNBAGAME', label: 'NBA game winner', category: 'Sports'}];
const row = (t, over = {}) => ({t, s: t.split('-')[0], ti: 'Bitcoin price on Oct 26, 2026 at 5pm EDT?', su: '', bid: .48, ask: .52, last: .5, v24: 9012.4, oi: 504,
  ct: at(5 * 3600e3), ...over});
const ROWS = [
  row('KXBTCD-26OCT2617-T112999.99', {su: '$113,000 or above', vs: {side: 'above', diff: 420.01, pct: 0.372}}),
  row('KXBTCD-26OCT2617-T114000', {su: '$114,000.01 or above', bid: 0, ask: .03, vs: {side: 'below', diff: -580, pct: -0.509}}),
  row('KXBTC-26OCT2617-B113250', {ti: 'Bitcoin price range at 5pm EDT?', su: '$113,000 to 113,499.99', bid: '', ask: 0, vs: {side: 'inside', diff: 0, pct: 0}}),
  row('KXBTC15M-26OCT261215-15', {ti: 'BTC price up in next 15 mins?', su: 'Target Price: $113,512.08', ct: at(15 * 60e3), vs: {side: 'below', diff: -92.08, pct: -0.081, from: 'title'}}),
  row('KXNBAGAME-26OCT26MINDEN-MIN', {s: 'KXNBAGAME', ti: 'Pro Basketball · Minnesota at Denver Winner?', su: 'Minnesota', ct: null, bid: null, ask: 'x'}),
  row('KXFEDDECISION-26DEC-H0', {s: 'KXFEDDECISION', ti: 'Fed decision in Dec 2026?', su: 'Fed decision in Dec 2026?', ct: at(-60e3), v24: 0, oi: null}),
  row('KXUNTITLED-26OCT26', {s: 'KXUNTITLED', ti: '', su: '', ct: at(36 * 3600e3), bid: .99, ask: 1, last: null}),
  row('KXHIGHNY-26OCT26-B70', {s: 'KXHIGHNY', ti: 'Highest temperature in NYC today?', su: '<b>70° to 71°</b>', bid: .2, ask: .24}),
];
const SPOT = {price: 113420, at: at(-4000), age_s: 4, stale: false};
const feed = (o = {}) => ({at: at(-30000), total: 41230, shown: 8, matched: 8, page: 0, per: 40, sort: 'v24', markets: ROWS, spot: SPOT, ...o});
const NO_FEED = {at: null, total: 0, shown: 0, matched: 0, page: 0, per: 40, sort: 'v24', markets: []};

// One contract's page (/api/explore/market) and its Bitcoin spot (/api/explore/spot).
const BTC = 'KXBTCD-26OCT2617-T112999.99';
const points = (n, from = NOW / 1000 - 60 * n) => Array.from({length: n}, (_, i) => ({t: from + 60 * i, yes: +(0.4 + (i % 7) / 50).toFixed(2), vol: i % 3 ? 2.6 : 0}));
const pos = (over) => ({strategy_id: 61, title: 'Momentum <b>one</b>', side: 'yes', qty: 3, entry_price: 0.41, cost: 1.27, status: 'open', mode: 'paper',
  market_close_time: at(5 * 3600e3), unrealized: 0.12, mark_ts: at(-20000), ...over});
const MINE = {open: [pos({}), pos({strategy_id: 62, title: 'Old mark', mark_ts: at(-3 * 3600e3), unrealized: -0.3}), pos({strategy_id: null, title: null, unrealized: null, mark_ts: null}),
  pos({mode: 'demo', strategy_id: 63, title: 'On demo', side: 'no', qty: 1, entry_price: 0.6, cost: 0.62}), pos({mode: 'live', strategy_id: 64, title: 'Live one', cost: 2.1, qty: 5})],
closed: [pos({status: 'closed', strategy_id: 61, pnl: 0.42, exit_price: 0.55, close_reason: 'take_profit'}), pos({status: 'settled', mode: 'demo', strategy_id: 63, title: 'On demo', pnl: -0.6, exit_price: 0, close_reason: 'settled'})]};
const market = (o = {}) => ({ticker: BTC, series: 'KXBTCD', title: 'Bitcoin price at 5pm EDT?', sub: '$113,000 or above', status: 'active',
  yes_bid: '0.55', yes_ask: '0.57', last: '0.55', volume_24h: '15234.6', open_interest: '40211', close_time: at(5 * 3600e3), settles_at: at(5.5 * 3600e3),
  as_of: at(-2000), rules: 'If the price is above 112999.99 at 5pm EDT, the market resolves to Yes.', rules_more: 'CF Benchmarks <b>BRTI</b>.', period_min: 1,
  points: points(60), mine: {open: [], closed: []}, my_markets: [], ...o});
const spot = (o = {}) => ({ticker: BTC, spot: {price: 113420, at: at(-4000), age_s: 4, stale: false},
  strike: {kind: 'above', value: 112999.99, lo: null, hi: null, inclusive: false, from: 'ticker'},
  vs: {side: 'above', diff: 420.01, pct: 0.372, yes: true}, close_time: at(5 * 3600e3), secs_left: 18000, as_of: at(-1000), ...o});

// Presses that both themes' pages offer under the same selector.
const click = async (f, sel) => { const b = f.root.querySelector(sel); assert.ok(b, sel); await b.onclick({target: b, preventDefault() {}}); await settle(); };
const type = async (f, words) => { const q = f.root.querySelector('#xq'); q.value = words; q.listeners.get('input')({target: q}); f.elapse(220); await settle(); };
// The interval ticks the page set (its polls and the close clock), oldest first.
const ticks = async (f) => { for (const tick of [...f.intervals.values()]) { await tick(); await settle(); } };

export function exploreParityCases({name, frontend}) {
  const theme = name === 'Tau' ? 'tau' : 'meridian';
  // name -> {search, list(path, n), market(path, n), spot(path, n), keep, act(f, snap)}: each draws the page, then
  // does what `act` says. Without its own answers a state reads the feed above, BTC's page and its spot.
  const STATES = {
    // The list.
    'the feed not in yet': {list: () => response(NO_FEED)},
    'no markets yet, the feed in': {list: () => response(feed({markets: [], shown: 0, matched: 0}))},
    'the hottest markets': {},
    'a list two polls behind, spot stale': {list: () => response(feed({at: at(-10 * 60e3), spot: {...SPOT, stale: true, age_s: 900}}))},
    'a list with no time, spot failed': {list: () => response(feed({at: '', total: 8, spot: {failed: true}}))},
    'a list whose spot is missing': {list: () => response(feed({spot: null, total: 8, matched: 5}))},
    'a search with results': {search: '?q=bitcoin&sort=v24&page=0', list: () => response(feed({matched: 4, markets: ROWS.slice(0, 4)}))},
    'a search that matches none': {search: '?q=%3Cnone%3E', list: () => response(feed({matched: 0, shown: 0, markets: []}))},
    'Bitcoin only': {search: '?show=bitcoin', list: () => response(feed({matched: 4, markets: ROWS.slice(0, 4)}))},
    'Bitcoin only, none open': {search: '?show=bitcoin', list: () => response(feed({matched: 0, shown: 0, markets: []}))},
    'Bitcoin only, a search that matches none': {search: '?show=bitcoin&q=zzz', list: () => response(feed({matched: 0, shown: 0, markets: []}))},
    'sorted by open interest': {search: '?sort=oi', list: () => response(feed({sort: 'oi'}))},
    'sorted by price, a bad sort and page ignored': {search: '?sort=last&page=-3', list: () => response(feed({sort: 'last'}))},
    'an unknown sort': {search: '?sort=nope', list: () => response(feed())},
    'page 2 of 3': {search: '?page=1', list: () => response(feed({matched: 100, page: 1}))},
    'the last page': {search: '?page=2', list: () => response(feed({matched: 100, page: 2, markets: ROWS.slice(0, 2)}))},
    'a read that failed': {list: () => response({error: 'Something went wrong on our side. It’s been logged.'}, 500)},
    'a read that failed, then Try again': {list: (path, n) => (n === 1 ? response({error: 'Bad request.'}, 400) : response(feed())),
      act: async (f) => { await click(f, '#xbody [data-xretry]'); }},
    'no markets yet, then Try again': {list: (path, n) => response(n === 1 ? NO_FEED : feed()), act: async (f) => { await click(f, '[data-xretry]'); }},
    'Bitcoin none open, Try again and Show all': {search: '?show=bitcoin', list: (path) => response(/show=bitcoin/.test(path) ? feed({matched: 0, shown: 0, markets: []}) : feed()),
      act: async (f, snap) => { await click(f, '[data-xretry]'); snap(); await click(f, '[data-xall]'); }},
    'sort pressed': {act: async (f, snap) => { await click(f, '[data-sort="oi"]'); snap(); await click(f, '[data-sort="last"]'); snap(); await click(f, '[data-sort="v24"]'); }},
    'show chips pressed': {act: async (f, snap) => { await click(f, '[data-show="bitcoin"]'); snap(); await click(f, '[data-show="all"]'); }},
    'a search typed, then cleared': {list: (path) => response(/q=btc/.test(path) ? feed({matched: 2, markets: ROWS.slice(0, 2)}) : feed()),
      act: async (f, snap) => { await type(f, '  btc '); snap(); await type(f, ''); }},
    'next and previous page': {search: '?page=1', list: (path) => response(feed({matched: 100, page: +new URLSearchParams(path.split('?')[1]).get('page')})),
      act: async (f, snap) => { await click(f, '[data-pg="2"]'); snap(); await click(f, '[data-pg="1"]'); snap(); await click(f, '[data-pg="0"]'); }},
    'a poll that moves one row': {list: (path, n) => response(n === 1 ? feed() : feed({at: at(-5000), markets: [ROWS[0], {...ROWS[1], bid: .1, ask: .12}, ...ROWS.slice(2)]})),
      act: async (f) => { const link = f.root.querySelector('#xrows a'); link.focus(); f.document.activeElement = link; await ticks(f); }},
    'polls that fail': {list: (path, n) => (n === 1 ? response(feed()) : response({error: 'Something went wrong on our side.'}, 500)),
      act: async (f, snap) => { await ticks(f); snap(); f.shiftClock(60000); await ticks(f); await ticks(f); snap(); f.shiftClock(120000); await ticks(f); await ticks(f); await ticks(f); }},
    'a poll that answers after a search': {list: (path, n) => response(n === 2 ? feed() : feed({matched: 1, markets: ROWS.slice(4, 5)})),
      act: async (f) => { const q = f.root.querySelector('#xq'); q.value = 'nba'; q.listeners.get('input')({target: q}); await ticks(f); f.elapse(220); await settle(); }},
    // A market's page.
    'a Bitcoin market, spot against its strike': {search: '?m=' + BTC, market: () => response(market({my_markets: ['btc_daily'], mine: MINE}))},
    'a Bitcoin market whose spot failed, then Try again': {search: '?m=' + BTC, spot: (path, n) => (n === 1 ? response({error: 'Something went wrong on our side.'}, 500) : response(spot())),
      act: async (f) => { await click(f, '[data-spot-retry]'); }},
    'a Bitcoin market whose spot is stale': {search: '?m=' + BTC, spot: () => response(spot({spot: {price: 113420, at: at(-15 * 60e3), age_s: 900, stale: true}}))},
    'a 15-minute window, its target price': {search: '?m=KXBTC15M-26OCT261215-15', market: () => response(market({ticker: 'KXBTC15M-26OCT261215-15', series: 'KXBTC15M', title: 'BTC price up in next 15 mins?', sub: 'Target Price: $113,512.08', close_time: at(15 * 60e3)})),
      spot: () => response(spot({ticker: 'KXBTC15M-26OCT261215-15', strike: {kind: 'above', value: 113512.08, inclusive: true, from: 'title'}, vs: {side: 'below', diff: -92.08, pct: -0.081, yes: false}}))},
    'a market without a strike Tau doesn’t research': {search: '?m=KXFEDDECISION-26DEC-H0', market: () => response(market({ticker: 'KXFEDDECISION-26DEC-H0', series: 'KXFEDDECISION', title: 'Fed decision in Dec 2026?', sub: 'Hike 0bps', period_min: 1440, points: points(9)}))},
    'another hour of the ladder': {search: '?m=KXBTCD-26OCT2612-T68499.99', market: () => response(market({ticker: 'KXBTCD-26OCT2612-T68499.99', title: 'Bitcoin price at 12pm EDT?', sub: '$68,500 or above', period_min: 60}))},
    'an untitled contract, no trades, no quotes': {search: '?m=KXNBAGAME-X', market: () => response(market({ticker: 'KXNBAGAME-X', series: 'KXNBAGAME', title: '', sub: '', yes_bid: '0', yes_ask: '0', last: null, volume_24h: null, open_interest: undefined, close_time: null, as_of: null, rules: '', rules_more: '', points: []}))},
    'one side quoted': {search: '?m=KXNBAGAME-Y', market: () => response(market({ticker: 'KXNBAGAME-Y', series: 'KXNBAGAME', title: 'Minnesota at Denver Winner?', sub: 'Minnesota', yes_bid: '0', yes_ask: '0.05', last: null, points: points(1)}))},
    'the other side quoted, a snapshot': {search: '?m=KXNBAGAME-Z', market: () => response(market({ticker: 'KXNBAGAME-Z', series: 'KXNBAGAME', title: 'Denver?', sub: 'Denver', yes_bid: '0.3', yes_ask: '0', snapshot: true, as_of: at(-7 * 60e3), points: points(2)}))},
    'a market past its close': {search: '?m=' + BTC, market: () => response(market({close_time: at(-60e3), status: 'active'}))},
    'a closed market': {search: '?m=' + BTC, market: () => response(market({status: 'closed', close_time: at(-3600e3)}))},
    'a settled market, Yes': {search: '?m=' + BTC, market: () => response(market({status: 'settled', result: 'yes', close_time: at(-3600e3), mine: MINE}))},
    'a settled market, No': {search: '?m=KXFEDDECISION-26DEC-H0', market: () => response(market({ticker: 'KXFEDDECISION-26DEC-H0', series: 'KXFEDDECISION', status: 'finalized', result: 'no', close_time: at(-86400e3)}))},
    'a paused market': {search: '?m=KXFEDDECISION-26DEC-H0', market: () => response(market({ticker: 'KXFEDDECISION-26DEC-H0', series: 'KXFEDDECISION', status: 'paused'}))},
    'positions that didn’t load': {search: '?m=' + BTC, market: () => response(market({mine: null}))},
    'price history that didn’t load, then Try again': {search: '?m=' + BTC, market: (path, n) => response(n === 1 ? market({history_unavailable: true, points: []}) : market()),
      act: async (f) => { await click(f, '#mk-retry'); }},
    'a market read that failed, then Try again': {search: '?m=' + BTC, market: (path, n) => (n === 1 ? response({error: 'Something went wrong on our side. It’s been logged.'}, 502) : response(market())),
      act: async (f) => { await click(f, '#mk-retry'); }},
    'a market Kalshi doesn’t have': {search: '?m=KXNOPE-1', market: () => response({error: 'Kalshi has no market KXNOPE-1.'}, 404)},
    'raw data pages': {search: '?m=' + BTC, market: () => response(market({points: points(130)})),
      act: async (f, snap) => { await click(f, '[data-rp="1"]'); snap(); await click(f, '[data-rp="2"]'); snap(); await click(f, '[data-rp="1"]'); }},
    'a day of hourly history': {search: '?m=' + BTC, market: () => response(market({period_min: 60, points: points(48).map((p, i) => ({...p, t: NOW / 1000 - 3600 * (48 - i)}))}))},
    'the close clock and the spot poll': {search: '?m=' + BTC, act: async (f, snap) => { f.shiftClock(3 * 3600e3); await ticks(f); snap(); f.shiftClock(2 * 3600e3 + 1000); await ticks(f); }},
    // From the list to a market and back: the way back keeps the list's search, sort, page and Bitcoin choice.
    'the list, then a market, its way back kept': {search: '?q=btc&sort=oi&page=1&show=bitcoin', act: async (f) => {
      f.S.gen++; f.clearTimers(); f.location.search = '?m=' + BTC; await f.viewExplore(); await settle(); }},
    'a market whose tab kept a way back': {search: '?m=' + BTC, keep: '/explore?q=nba&sort=last&page=0'},
    'a market whose tab kept a market as the way back': {search: '?m=' + BTC, keep: '/explore?m=KXA-1'},
    'a market whose tab kept another page': {search: '?m=' + BTC, keep: '/strategies?x=1'},
  };

  const draw = async (state, phone) => {
    const n = {list: 0, market: 0, spot: 0};
    const answer = {list: state.list || (() => response(feed())), market: state.market || (() => response(market())), spot: state.spot || (() => response(spot()))};
    const kept = [];
    const store = new Map(state.keep ? [['tau_xback', state.keep]] : []);
    const session = {getItem: (k) => store.get(k) ?? null, setItem: (k, v) => { kept.push([k, String(v)]); store.set(k, String(v)); }, removeItem: (k) => store.delete(k)};
    const which = (path) => (path.startsWith('/api/explore?') ? 'list' : path.startsWith('/api/explore/market?') ? 'market' : path.startsWith('/api/explore/spot?') ? 'spot' : null);
    const f = frontend({session, matchMedia: () => ({matches: phone, addEventListener() {}, removeEventListener() {}}), globals: {Date: fixedDate(), Intl: fixedIntl},
      fetchImpl: (path, options) => { const k = which(path); return k ? answer[k](path, ++n[k], options) : response({}); }});
    f.S.me.markets = MARKETS;
    f.location.pathname = '/explore'; f.location.search = state.search ?? '';
    const drawing = f.viewExplore();
    for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }
    await drawing; await settle();
    // What it drew, then each step of what `act` does (snap), then what was left once it was done.
    const doms = [dump(f.document.body)];
    if (state.act) {
      await state.act(f, () => doms.push(dump(f.document.body)));
      for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }
      doms.push(dump(f.document.body));
    }
    const requests = f.requests.map(({path, options}) => [path, (options && options.method) || 'GET', (options && options.body) || null]);
    const shot = {doms, requests, navigations: f.navigations, kept};
    f.clearTimers();
    return shot;
  };

  test(`${name}: Explore, its list and a market's page, draws what it drew before it was one file for both themes, in every state and at both widths`, async () => {
    const zone = process.env.TZ;
    process.env.TZ = 'UTC';
    try {
      const shots = {};
      for (const [label, state] of Object.entries(STATES)) {
        for (const [width, phone] of [['desk', false], ['phone', true]]) shots[`${label} @ ${width}`] = await draw(state, phone);
      }
      // The same state drawn twice is the same (no clock or order in it), so a difference below is the page's.
      assert.deepEqual(await draw(STATES['the hottest markets'], false), shots['the hottest markets @ desk']);
      assert.deepEqual(await draw(STATES['a Bitcoin market, spot against its strike'], true), shots['a Bitcoin market, spot against its strike @ phone']);
      // Each state drew Explore (its list or a market's page), not a page-file failure.
      for (const [key, shot] of Object.entries(shots)) {
        assert.doesNotMatch(shot.doms.join('\n'), /load-fail/, key);
        assert.match(shot.doms[0], /id="xbody"|mk-back|Back to Explore/, key);
      }
      const dir = process.env.TAU_DUMP_EXPLORE_SNAPSHOTS;
      if (dir) { mkdirSync(dir, {recursive: true}); writeFileSync(`${dir}/${theme}.json`, JSON.stringify(shots, null, 1) + '\n'); }
      const got = Object.fromEntries(Object.entries(shots).map(([key, shot]) => [key, sha(shot)]));
      if (process.env.TAU_WRITE_EXPLORE_SNAPSHOTS) {
        const all = existsSync(SNAP) ? JSON.parse(readFileSync(SNAP, 'utf8')) : {};
        all[theme] = got;
        writeFileSync(SNAP, JSON.stringify(Object.fromEntries(Object.keys(all).sort().map((k) => [k, all[k]])), null, 1) + '\n');
        return;
      }
      assert.ok(existsSync(SNAP), 'the fingerprints are in the repo');
      const want = JSON.parse(readFileSync(SNAP, 'utf8'))[theme];
      assert.deepEqual(Object.keys(got), Object.keys(want), 'the same states');
      for (const key of Object.keys(want)) assert.equal(got[key], want[key], `${name}: ${key} draws otherwise than before`);
    } finally {
      if (zone === undefined) delete process.env.TZ; else process.env.TZ = zone;
    }
  });
}
