// Explore keeps itself current while it shows, run against each bundle's offline DOM/transport harness (Tau and
// Meridian). The list polls every 15s (paused while the tab is hidden, read at once on coming back to it) and
// rewrites only the rows that moved, so focus, the search box and the sort stay; a failed poll keeps the list up
// and, past two polls, says how old it is. The hot-markets rail polls every 30s and says the same when its reads fail.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return {promise, resolve}; };
const row = (t, mid) => ({t, s: t.split('-')[0], ti: `Game ${t} winner?`, su: 'Home', bid: +(mid - .01).toFixed(2), ask: +(mid + .01).toFixed(2), v24: 900, oi: 50});
const FAIL = () => response({error: 'Something went wrong on our side.'}, 500);

// The interval whose tick asks for `prefix`: the page's own poll.
async function pollOf(f, prefix) {
  for (const tick of [...f.intervals.values()].reverse()) {
    const before = f.requests.length;
    await tick(); await settle();
    if (f.requests.slice(before).some(({path}) => path.startsWith(prefix))) return tick;
  }
  throw new Error('no poll asks for ' + prefix);
}
const flip = async (f, hidden) => { f.document.hidden = hidden; for (const [type, on] of f.documentListeners) if (type === 'visibilitychange') on({}); await settle(); };

export function explorePollCases({name, frontend, storageFor, railOpenWide}) {
  const open = async () => {
    const state = {markets: [row('KXA-1', .40), row('KXB-1', .50), row('KXC-1', .60)], failing: false, hold: null, skew: 0};
    const f = frontend({fetchImpl: (path) => {
      if (!path.startsWith('/api/explore?')) return response({});
      if (state.hold && path === '/api/explore?q=&sort=v24&page=0') return state.hold.promise;
      if (state.failing) return FAIL();
      const q = new URLSearchParams(path.split('?')[1]).get('q');
      const markets = state.markets.filter((m) => !q || m.t.toLowerCase().includes(q));
      return response({at: new Date(Date.now() + state.skew).toISOString(), total: 41000, shown: 3, matched: markets.length, page: 0, per: 40, sort: 'v24', markets});
    }});
    f.location.pathname = '/explore'; f.location.search = '';
    await f.viewExplore(); await settle();
    const rows = () => f.root.querySelector('#xrows').children;
    const asked = () => f.requests.filter(({path}) => path.startsWith('/api/explore?')).map(({path}) => path);
    // The page's clock and the feed's move together.
    const shift = (ms) => { state.skew += ms; f.shiftClock(ms); };
    return {f, state, rows, asked, shift};
  };
  const focusOn = (f, el) => { el.focus(); f.document.activeElement = el; };
  const hasFocus = (f, el) => el.focused === true || f.document.activeElement === el;

  test(`${name}: Explore's list follows the feed every 15s, rewriting only the row that moved and keeping focus, search and sort`, async () => {
    const {f, state, rows, asked} = await open();
    const poll = await pollOf(f, '/api/explore?');
    assert.equal(asked().at(-1), '/api/explore?q=&sort=v24&page=0');
    // Unchanged: nothing is rewritten.
    const tbody = f.root.querySelector('#xrows'), writes = tbody.writes, first = [...rows()];
    await poll(); await settle();
    assert.equal(tbody.writes, writes); assert.deepEqual([...rows()], first);

    // The middle row's price moved while a keyboard user sat on its link, with words typed in the search box.
    const search = f.root.querySelector('#xq');
    search.value = 'gam';
    focusOn(f, first[1].querySelector('a'));
    state.markets = [row('KXA-1', .40), row('KXB-1', .55), row('KXC-1', .60)];
    await poll(); await settle();
    const now = [...rows()];
    assert.equal(now[0], first[0]); assert.equal(now[2], first[2]);  // the rows that didn't move are the same elements
    assert.notEqual(now[1], first[1]);
    assert.match(now[1].textContent, /55¢/); assert.doesNotMatch(now[1].textContent, /50¢/);
    assert.ok(hasFocus(f, now[1].querySelector('a')), 'focus stays on the moved row’s link');
    assert.equal(f.root.querySelector('#xq'), search); assert.equal(search.value, 'gam');

    // A sort the reader picked stays picked: the poll asks for it.
    f.root.querySelector('[data-sort="oi"]').onclick(); await settle();
    await poll(); await settle();
    assert.equal(asked().at(-1), '/api/explore?q=&sort=oi&page=0');
    f.clearTimers();
  });

  test(`${name}: a failed Explore poll keeps the list up and says how old it is; hidden it reads nothing, and back on the tab it reads at once`, async () => {
    const {f, state, rows, asked, shift} = await open();
    const poll = await pollOf(f, '/api/explore?');
    const note = () => f.root.querySelector('#xstale').textContent;
    const fresh = () => f.root.querySelector('#xfigs').textContent;
    state.failing = true;
    await poll(); await settle();
    assert.equal(note(), '', 'one failed poll says nothing yet');
    shift(100e3);
    await poll(); await settle();  // backing off: no read, but the line says how old the list is
    assert.equal(note(), 'Last updated 2m ago, retrying');
    await poll(); await settle();  // the next read fails too: the age beside the figures counts on from the list's time
    assert.match(fresh(), /Prices updated\s*2m ago/);
    assert.equal(rows().length, 3, 'the list stays up');
    assert.doesNotMatch(f.root.querySelector('#xbody').innerHTML, /didn’t load/);

    // Hidden: no reads, however many ticks.
    state.failing = false;
    await flip(f, true);
    const before = asked().length;
    for (let i = 0; i < 8; i++) await poll();
    await settle();
    assert.equal(asked().length, before);
    // Back on the tab after a while: it reads at once, past its back-off, and the note goes.
    shift(60e3);
    await flip(f, false);
    assert.equal(asked().length, before + 1);
    assert.equal(note(), '');
    assert.match(fresh(), /Prices updated\s*just now/);
    f.clearTimers();
  });

  test(`${name}: an Explore poll that answers after a search never puts the old list back`, async () => {
    const {f, state, rows} = await open();
    const poll = await pollOf(f, '/api/explore?');
    state.hold = deferred();
    poll(); await settle();  // a poll for the unsearched list, still waiting
    f.root.querySelector('#xq').listeners.get('input')({target: {value: 'kxc'}});
    f.elapse(300); await settle();
    assert.equal(rows().length, 1);
    state.hold.resolve(response({at: new Date().toISOString(), total: 41000, shown: 3, matched: 3, page: 0, per: 40, sort: 'v24', markets: state.markets}));
    await settle();
    assert.equal(rows().length, 1, 'the search’s answer stays');
    assert.match(rows()[0].textContent, /KXC-1/);
    f.clearTimers();
  });

  test(`${name}: the hot-markets rail polls every 30s and, while its reads fail, keeps its rows and says how old they are`, async () => {
    let failing = false;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/explore/hot') return failing ? FAIL() : response({at: new Date().toISOString(), markets: [{...row('KXA-1', .4), h: [.4, .5]}, {...row('KXB-1', .5), h: [.5, .4]}]});
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {}, policy: null, totals: {tried: 0, passed: 0}, v: 'v1'});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }, storage: storageFor(new Map(railOpenWide)), matchMedia: () => ({matches: false})});
    f.S.hot = null; f.S.hotAt = 0;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const rail = () => f.document.getElementById('hotrail'), note = () => (rail().querySelector('#hot-stale') || {textContent: ''}).textContent;
    const reads = () => f.requests.filter(({path}) => path === '/api/explore/hot').length;
    assert.equal(rail().querySelectorAll('.hot-row').length, 2);
    const tick = await pollOf(f, '/api/explore/hot');
    failing = true;
    await tick(); await settle();
    assert.equal(rail().querySelectorAll('.hot-row').length, 2, 'a failed read keeps the rows');
    assert.equal(note(), '');
    f.shiftClock(61e3);
    await tick(); await settle();  // backing off: no read, and the line says how old the rows are
    assert.equal(note(), 'Last updated 61s ago, retrying');
    assert.equal(rail().querySelectorAll('.hot-row').length, 2);
    // Hidden: no reads. Back on the tab after a while, it reads at once and the line goes.
    failing = false;
    await flip(f, true);
    const before = reads();
    for (let i = 0; i < 6; i++) await tick();
    await settle();
    assert.equal(reads(), before);
    f.shiftClock(60e3);
    await flip(f, false);
    assert.equal(reads(), before + 1);
    assert.equal(note(), '');
    f.clearTimers();
  });
}
