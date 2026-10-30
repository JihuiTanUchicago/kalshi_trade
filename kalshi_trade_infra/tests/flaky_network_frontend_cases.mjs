// Shared cases, run against each bundle's offline harness (Tau and Meridian): a phone on a bad connection
// (a train, a lift). The page says it is offline at once and stops saying so once the network is back,
// and a page that couldn't load while offline says that, not "Something went wrong".
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const OFFLINE = 'You’re offline. Tau keeps what it last showed and catches up when you’re back.';

// The browser's window events and navigator.onLine, as a phone losing and finding its network sets them.
function network() {
  const nav = {onLine: true}, listeners = new Map();
  const win = {addEventListener: (name, callback) => listeners.set(name, [...(listeners.get(name) || []), callback])};
  const fire = (name) => { nav.onLine = name === 'online'; (listeners.get(name) || []).forEach((callback) => callback()); };
  return {nav, win, fire};
}

export function flakyNetworkCases({name, frontend}) {
  test(`${name}: going offline puts one line above the page at once, and it goes by itself once the network is back`, async () => {
    const net = network();
    const f = frontend({win: net.win, globals: {navigator: net.nav}, fetchImpl: () => response({})});
    assert.equal(f.document.getElementById('netbar'), null, 'nothing while online');
    net.fire('offline');
    const bar = f.document.getElementById('netbar');
    assert.ok(bar, 'shown the moment the phone says it is offline');
    assert.equal(bar.textContent, OFFLINE);
    assert.equal(bar.getAttribute('role'), 'status');
    assert.equal(f.document.body.children.indexOf(bar), f.document.body.children.indexOf(f.root) - 1, 'just above the page');
    net.fire('offline');
    assert.equal(f.document.body.children.filter((c) => c.attributes && c.attributes.id === 'netbar').length, 1, 'one line, however often it fires');
    net.fire('online');
    assert.equal(bar.removed, true, 'gone once the network is back');
    f.clearTimers();
  });

  test(`${name}: a page that couldn't load while offline says so and that it loads by itself, not "Something went wrong"`, async () => {
    for (const offline of [true, false]) {
      const net = network();
      net.nav.onLine = !offline;
      const f = frontend({win: net.win, globals: {navigator: net.nav}, fetchImpl: (path) => {
        if (path.startsWith('/api/deployments')) throw new TypeError('Failed to fetch');
        return response({});
      }});
      f.location.pathname = '/deploy';
      const rendering = f.render();
      for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }  // the read's two quick retries
      await rendering; await settle();
      const page = f.root.innerHTML;
      if (offline) {
        assert.match(page, /You’re offline/);
        assert.match(page, /This page loads by itself once you’re back online\./);
        assert.doesNotMatch(page, /Something went wrong/);
      } else {
        assert.match(page, /This page didn’t load/);
        assert.match(page, /Can’t reach Tau\. Check your connection\./);
      }
      assert.ok(f.root.querySelector('[data-retry]'), 'Try again stays');
      f.clearTimers();
    }
  });

  // Walk 2026-10-28 (each read failing as JSON 500, HTML 500 and no reply): a failed list said only "Something went
  // wrong on our side." under the page's own filters, and never which part hadn't come.
  test(`${name}: a list that didn't load names itself, says the rest of the page did, and gives no status code`, async () => {
    for (const [answer, why] of [[() => response({error: 'Something went wrong on our side. It’s been logged.'}, 500), 'Something went wrong on our side. It’s been logged.'],
      [() => ({ok: false, status: 500, json: async () => { throw new SyntaxError('Unexpected token <'); }}), 'Tau is having trouble right now. Try again in a moment.']]) {
      const f = frontend({fetchImpl: (asked) => (asked.startsWith('/api/strategies') ? answer() : response({}))});
      f.location.pathname = '/strategies';
      const rendering = f.render();
      for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }
      await rendering; await settle();
      const slips = f.root.querySelector('#slips');
      assert.equal(slips.querySelector('.notice').textContent.trim(), `Your strategies didn’t load. ${why} Everything else on this page did.`);
      assert.ok(slips.querySelector('[data-retry]'), 'Try again');
      assert.doesNotMatch(f.root.textContent, /\(500\)|undefined|null|NaN|\[object/);
      f.clearTimers();
    }
  });

  test(`${name}: a page that failed to load keeps its section's tab marked, as the page itself would`, async () => {
    for (const [path, status, tab] of [['/deploy', 500, '/deploy'], ['/research/5', 500, '/research'], ['/strategies/12', 404, '/strategies'], ['/dashboard', 500, '/']]) {
      const f = frontend({fetchImpl: (asked) => {
        if (/^\/api\/(deployments|research\/5|strategies\/12|dashboard)/.test(asked)) return response({error: 'Something went wrong on our side.'}, status);
        return response({});
      }});
      f.location.pathname = path;
      const rendering = f.render();
      for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }
      await rendering; await settle();
      assert.match(f.root.innerHTML, status === 404 ? /Not found/ : /This page didn’t load/, path);
      const marked = f.root.querySelectorAll('a.svc-link').filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.getAttribute('href'));
      assert.deepEqual(marked, [tab], path);
      f.clearTimers();
    }
  });

  // Walk 2026-10-28: a Research page whose scoreboard read failed showed the older "Self-improving research engine"
  // card as if it were the current read, and said nothing about the failure.
  test(`${name}: research results that didn't load say so with Try again, not the older engine card`, async () => {
    const BOARD = {total: {runs: 2, explored: 10, gated: 3, passed: 1, cost_usd: 2, gate_reach_rate: 0.3, pipeline_death_share: 0.2}};
    for (const [fail, why] of [[() => response({error: 'Something went wrong on our side. It’s been logged.'}, 500), 'Something went wrong on our side. It’s been logged.'],
      [() => ({ok: false, status: 403, json: async () => { throw new SyntaxError('Unexpected token <'); }}), 'Tau couldn’t load this. Reload the page and try again.']]) {
      let down = true, asked = 0;
      const f = frontend({fetchImpl: (path) => {
        if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}], default: 'opus'});
        if (path.startsWith('/api/research/scoreboard')) { asked++; return down ? fail() : response(BOARD); }
        // An evolved policy: the older card had something to show, so it stood in for the failed read.
        if (path.startsWith('/api/runs')) return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: {evolved: true, base_score: 1, score: 2}, totals: {tried: 4, passed: 1}});
        return response({});
      }});
      f.S.me.user.autopilot = false;
      f.location.pathname = '/research';
      await f.viewResearch(); await settle();
      const host = f.root.querySelector('#rsimo');
      assert.equal(host.querySelector('.notice').textContent.trim(), `Your research results didn’t load. ${why} Everything else on this page did.`);
      assert.doesNotMatch(host.textContent, /Self-improving research engine|\(403\)|\(500\)|undefined|null|NaN/);
      assert.ok(f.root.querySelector('#dispatch'), 'the form is there');
      down = false;
      await host.querySelector('[data-retry]').onclick(); await settle();
      assert.equal(asked, 2, 'Try again reads it once more');
      assert.match(host.textContent, /Is research getting better\?/);
      assert.doesNotMatch(host.textContent, /didn’t load|Self-improving research engine/);
      f.clearTimers();
    }
  });

  // A refresh that failed with a board up kept the board and said nothing, so it read as current. One quiet line
  // above it says so, as the bell's does ("Couldn’t refresh. Showing … from N min ago." with Try again), and the
  // next read that comes back takes it away.
  test(`${name}: research results kept after a failed refresh say how old they are, with Try again`, async () => {
    const BOARD = {total: {runs: 2, explored: 10, gated: 3, passed: 1, cost_usd: 2, gate_reach_rate: 0.3, pipeline_death_share: 0.2}};
    let down = false, asked = 0;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}], default: 'opus'});
      if (path.startsWith('/api/research/scoreboard')) { asked++; return down ? response({error: 'Something went wrong on our side. It’s been logged.'}, 500) : response(BOARD); }
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {research_running: 0, research_queued: 0}, totals: {tried: 4, passed: 1}});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const host = f.root.querySelector('#rsimo');
    assert.match(host.textContent, /Is research getting better\?/);
    assert.equal(host.querySelector('.loop-stale'), null, 'nothing while the board is current');
    // Three minutes on, the next refresh fails: the board stays, and says how old it is.
    down = true;
    f.shiftClock(3 * 60000); [...f.intervals.values()].forEach((tick) => tick()); await settle();
    assert.equal(asked, 2, 'it read the board again');
    const line = host.querySelector('.loop-stale');
    assert.ok(line, 'a line says the board is kept');
    assert.equal(line.textContent, 'Couldn’t refresh. Showing your research results from 3 min ago. Try again');
    assert.equal(line.getAttribute('role'), 'status');
    assert.match(host.textContent, /Is research getting better\?/);
    assert.doesNotMatch(host.textContent, /\(500\)|undefined|null|NaN|didn’t load/);
    // Try again reads it once more; back, the line goes.
    down = false;
    const before = asked;
    await host.querySelector('[data-loop-retry]').onclick(); await settle();
    assert.equal(asked, before + 1, 'Try again reads it once more');
    assert.equal(host.querySelector('.loop-stale'), null);
    assert.match(host.textContent, /Is research getting better\?/);
    f.clearTimers();
  });
}
