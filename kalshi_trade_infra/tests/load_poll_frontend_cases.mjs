// What a signed-in page reads, and when, run against each bundle's offline DOM/transport harness (Tau and
// Meridian). Measured 2026-10-28 on a seeded local account in Chromium (both themes):
// - moving between pages read the bell's list again on every page, though the autopilot's read keeps it
//   current within a minute: a list read under a minute ago serves the next page (one that failed is read again);
// - a page that mounted the autopilot panel on a status over 18s old read it, and the panel's 20s poll read it
//   again a second or two later; the hot-markets rail did the same at 25s of its 30s. A tick under half its
//   interval after a good read now asks nothing;
// - back on the tab, a poll read at once and its next tick, due a second or two later, read the same again;
// - a finished research session (Tau) was read once more by its 2s poll, which then stopped.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const reads = (f, path) => f.requests.filter((r) => r.path === path && !(r.options && r.options.method === 'POST')).length;
const flip = async (f, hidden) => { f.document.hidden = hidden; for (const [type, on] of f.documentListeners) if (type === 'visibilitychange') on({}); await settle(); };
const intervalOf = (f, text) => [...f.intervals.values()].find((cb) => String(cb).includes(text));

export function loadPollCases({name, frontend, storageFor, railOpenWide}) {
  const page = (notifications, extra = () => undefined) => frontend({notifications, fetchImpl: (path) => {
    const hit = extra(path);
    if (hit) return hit;
    if (path === '/api/notifications/read') return response({ok: true});
    if (path === '/api/autopilot/status') return response({mode: 'off'});
    return response({});
  }});

  test(`${name}: moving between pages reads the bell once a minute at most, and again after a read that failed`, async () => {
    const f = page({unread: 1, items: [{id: 4, kind: 'paused', body: 'Edge was paused.', link: '/deploy', created_at: new Date().toISOString(), read: false, more: 0}]});
    f.location.pathname = '/';
    await f.render(); await settle();
    assert.equal(reads(f, '/api/notifications'), 1);
    // Three more pages within the minute: each bell shows the list kept, with its dot.
    for (const path of ['/', '/', '/']) {
      f.shiftClock(15e3); f.location.pathname = path;
      await f.render(); await settle();
    }
    assert.equal(reads(f, '/api/notifications'), 1);
    assert.equal(f.root.querySelector('.bell-dot').hidden, false);
    assert.match(f.root.querySelector('a.notif.unread').textContent, /Edge was paused/);
    // The kept list is 45s old: opening the bell reads it again (it is older than the 15s an open allows).
    await f.root.querySelector('.bell-trig').onclick({stopPropagation() {}}); await settle();
    assert.equal(reads(f, '/api/notifications'), 2);
    // Past the minute, the next page reads it again.
    f.shiftClock(61e3);
    await f.render(); await settle();
    assert.equal(reads(f, '/api/notifications'), 3);

    // A list that didn't load is read again on the next page, past the 2s a repaint shares.
    let failing = true;
    const g = page(() => (failing ? response({error: 'Something went wrong on our side.'}, 500) : response({unread: 0, items: []})));
    g.location.pathname = '/';
    await g.render(); await settle();
    assert.equal(reads(g, '/api/notifications'), 1);
    failing = false;
    g.shiftClock(3e3);
    await g.render(); await settle();
    assert.equal(reads(g, '/api/notifications'), 2);
    assert.match(g.root.querySelector('.bell-empty').textContent, /No notifications yet/);
  });

  test(`${name}: the autopilot poll skips a tick right after a page read the status, and reads on the one after`, async () => {
    const f = page({unread: 0, items: []});
    f.location.pathname = '/';
    f.S.apAt = Date.now() - 19e3;  // over 18s old: the page mounting the panel reads it
    await f.render(); await settle();
    assert.equal(reads(f, '/api/autopilot/status'), 1);
    const tick = intervalOf(f, "getElementById('autopilot-float') && !document.hidden && !apFresh()");
    assert.ok(tick, 'the panel polls');
    f.shiftClock(1e3); tick(); await settle();  // the poll's tick, due a second later, asks nothing new
    assert.equal(reads(f, '/api/autopilot/status'), 1);
    f.shiftClock(20e3); tick(); await settle();
    assert.equal(reads(f, '/api/autopilot/status'), 2);
    // A read that failed is never skipped: the next tick asks again (backing off as before).
    f.S.apFailing = true; f.S.apAt = Date.now();
    tick(); await settle();
    assert.equal(reads(f, '/api/autopilot/status'), 3);
  });

  test(`${name}: the hot-markets rail skips its tick right after mounting read the snapshot`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/explore/hot') return response({at: new Date().toISOString(), markets: []});
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {}, policy: null, totals: {tried: 0, passed: 0}, v: 'v1'});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }, storage: storageFor(new Map(railOpenWide)), matchMedia: () => ({matches: false})});
    f.S.hot = {markets: []}; f.S.hotAt = Date.now() - 26e3;  // over 25s old: mounting reads it
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    assert.equal(reads(f, '/api/explore/hot'), 1);
    const tick = intervalOf(f, 'hotShown() && !hotFresh()');
    assert.ok(tick, 'the rail polls');
    f.shiftClock(4e3); tick(); await settle();
    assert.equal(reads(f, '/api/explore/hot'), 1);
    f.shiftClock(30e3); tick(); await settle();
    assert.equal(reads(f, '/api/explore/hot'), 2);
    f.clearTimers();
  });

  test(`${name}: back on the tab a poll reads once; its next tick, due right after, asks nothing new`, async () => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore?')
      ? response({at: new Date().toISOString(), total: 1, shown: 0, matched: 0, page: 0, per: 40, sort: 'v24', markets: []})
      : response({})});
    f.location.pathname = '/explore'; f.location.search = '';
    await f.viewExplore(); await settle();
    const asked = () => f.requests.filter(({path}) => path.startsWith('/api/explore?')).length;
    const tick = f.intervals.get(f.S.timers.at(-1));
    assert.equal(asked(), 1);
    await flip(f, true);
    for (let i = 0; i < 5; i++) tick();
    await settle();
    assert.equal(asked(), 1, 'hidden: no reads');
    f.shiftClock(120e3);
    await flip(f, false);
    assert.equal(asked(), 2, 'back on the tab: one read at once');
    f.shiftClock(2e3); tick(); await settle();
    assert.equal(asked(), 2, 'the tick a moment later asks nothing new');
    f.shiftClock(15e3); tick(); await settle();
    assert.equal(asked(), 3, 'and the poll carries on');
    f.clearTimers();
  });

  test(`${name}: a finished research session is read once, with no poll left running`, async () => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9')
      ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', status: 'succeeded', stop_reason: 'limit',
        created_at: '2026-10-25T10:00:00Z', started_at: '2026-10-25T10:00:00Z', finished_at: '2026-10-25T10:20:00Z'}, events: [], strategies: []})
      : response({})});
    await f.viewRun(9); await settle();
    const runReads = () => f.requests.filter(({path}) => path.startsWith('/api/runs/9')).length;
    assert.equal(runReads(), 1);
    assert.equal(f.S.timers.length, 0);
    f.shiftClock(10e3);
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.equal(runReads(), 1);
  });
}
