// Shared cases, run against each bundle's offline harness (Tau and Meridian): the signed-in app on a bad connection.
// Walked 2026-10-31 in Chromium at 390x844 and 1366x900 with slow 3G (2.5s a request), reads that hang 30s, the
// connection dropping mid-page, a server restart (the edge's 502 for 20s) and a laptop lid (the tab hidden two hours
// with its timers frozen):
// - a placeholder said nothing while a read was out: a grey box whose aria-label="Loading" no screen reader reads;
// - a page (or the Strategies list, the dashboard's track record) that didn't load in a restart stayed "didn't load"
//   after the server was back, until someone pressed Try again;
// - back from the lid, polled figures hours old stood as current while their refresh was out (seconds on a slow line);
// - the autopilot poll sent a second status read beside one already out.
// Writes are not here to retry: api() never retries, aborts or times one out (test_api_retry.mjs).
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
// A page drawn again from the router waits on more than one turn (its file, the bell): enough turns for it to land.
const drain = async () => { for (let i = 0; i < 5; i++) await settle(); };
const flip = async (f, hidden) => { f.document.hidden = hidden; for (const [type, on] of f.documentListeners) if (type === 'visibilitychange') on({}); await settle(); };
// The recovery timer, with the page's Try again buttons given the DOM's click() (which runs their onclick): the
// harness's elements have none (or a stand-in another case gave them). Set on each button itself, never on the
// shared Element prototype.
const recovery = (f) => {
  const cb = [...f.intervals.values()].find((c) => String(c).includes('.load-fail [data-retry]'));
  return cb && (() => { f.root.querySelectorAll('.load-fail [data-retry]').forEach((b) => { b.click = () => b.onclick(); }); return cb(); });
};
const recoveries = (f) => [...f.intervals.values()].filter((c) => String(c).includes('.load-fail [data-retry]')).length;
const SERVER_ERR = () => response({error: 'Something went wrong on our side. It’s been logged.'}, 500);

export function badConnectionCases({name, frontend}) {
  test(`${name}: a placeholder says it is loading, in words a screen reader reads, and that it is slow past 8s`, async () => {
    const f = frontend({fetchImpl: () => new Promise(() => {})});  // every read hangs
    f.location.pathname = '/devlog';
    f.render(); await settle();
    const box = f.root.querySelector('.skeleton');
    assert.ok(box, 'a placeholder while the read is out');
    assert.equal(box.getAttribute('role'), 'status');
    assert.equal(box.getAttribute('aria-label'), null, 'no label on a plain box: the words are its text');
    assert.match(box.textContent, /^Loading…/);
    assert.match(box.querySelector('.skel-late').textContent, /This is taking longer than usual\./);
    f.clearTimers();
  });

  test(`${name}: a page that didn't load in a server restart loads again by itself, backing off, one try at a time, never while hidden, focus kept`, async () => {
    let up = false;
    const f = frontend({fetchImpl: (path) => (path === '/api/devlog' ? (up ? response({shipped: [{date: '2026-10-30', title: 'Faster pages'}], planned: []}) : SERVER_ERR()) : response({}))});
    const reads = () => f.requests.filter((r) => r.path === '/api/devlog').length;
    f.location.pathname = '/devlog';
    await f.render(); await settle();
    assert.match(f.root.innerHTML, /This page didn’t load/);
    assert.equal(reads(), 1);
    let tick = recovery(f);
    assert.ok(tick, 'the failed page tries again by itself');
    tick(); f.shiftClock(4000); tick(); await drain();
    assert.equal(reads(), 1, 'not before 5s');
    // Focus sat on the failed page's heading (where a page change puts it): the try draws the page again, and focus
    // goes to the new heading, not the top of the document.
    const h1 = f.root.querySelector('main h1');
    f.document.activeElement = h1;
    f.shiftClock(2000); tick(); await drain();
    assert.equal(reads(), 2, 'one try at 5s');
    assert.match(f.root.innerHTML, /This page didn’t load/);
    const h1b = f.root.querySelector('main h1');
    assert.notEqual(h1b, h1, 'drawn again');
    assert.ok(h1b.focused || f.document.activeElement === h1b, 'focus on the page heading drawn again');
    // Still down: the next try waits twice as long, and only one timer runs (the page drawn again cleared the first).
    tick = recovery(f);
    assert.equal(recoveries(f), 1);
    tick(); f.shiftClock(8000); tick(); await drain();
    assert.equal(reads(), 2, 'backing off: 10s this time');
    // Hidden (a laptop lid): no try, however long; back on the tab, the next tick tries.
    f.document.hidden = true;
    f.shiftClock(2 * 3600e3); tick(); tick(); await drain();
    assert.equal(reads(), 2, 'nothing while the tab is hidden');
    f.document.hidden = false;
    up = true;
    tick(); await drain(); for (let i = 0; i < 4; i++) await settle();
    assert.equal(reads(), 3);
    assert.match(f.root.querySelector('#main').innerHTML, /Faster pages/);
    assert.equal(f.root.querySelector('[data-retry]'), null);
    assert.equal(recoveries(f), 0, 'a page that loaded has no retry timer');
    f.clearTimers();
  });

  test(`${name}: signing in through a server restart (the boot read failing) tries again by itself`, async () => {
    let up = false;
    const f = frontend({fetchImpl: (path) => (path === '/api/me' ? (up ? response({user: {id: 7, name: 'Back'}, markets: [], directions: []}) : response({error: 'Down.'}, 503)) : response({}))});
    const reads = () => f.requests.filter((r) => r.path === '/api/me').length;
    f.S.me = null; f.location.pathname = '/devlog';
    await f.render(); await drain();
    assert.ok(f.root.querySelector('#bootretry'), 'the boot screen with Try again');
    const before = reads();
    const cb = [...f.intervals.values()].find((c) => String(c).includes('#bootretry'));
    assert.ok(cb, 'it tries again by itself');
    const tick = () => { const b = f.root.querySelector('#bootretry'); if (b) b.click = () => b.onclick(); return cb(); };
    up = true;
    tick(); f.shiftClock(6000); tick(); await drain();
    assert.equal(reads(), before + 1, 'one boot read');
    assert.equal(f.root.querySelector('#bootretry'), null);
    f.clearTimers();
  });

  test(`${name}: a page that didn't load for a reason a retry can't fix (a 404, a 403) does not try again by itself`, async () => {
    for (const status of [404, 403]) {
      const f = frontend({fetchImpl: (path) => (path === '/api/devlog' ? response({error: 'No.'}, status) : response({}))});
      f.location.pathname = '/devlog';
      await f.render(); await settle();
      assert.equal(recoveries(f), 0, String(status));
      f.clearTimers();
    }
  });

  test(`${name}: the Strategies list that didn't load in a restart loads again by itself, and keeps focus where it was`, async () => {
    let up = false;
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/strategies')) return up ? response({strategies: [], counts: {total: 0}, matched: 0}) : SERVER_ERR();
      return response({});
    }});
    const reads = () => f.requests.filter((r) => r.path.startsWith('/api/strategies')).length;
    f.location.pathname = '/strategies';
    await f.render(); await settle();
    const slips = f.root.querySelector('#slips');
    assert.match(slips.textContent, /Your strategies didn’t load/);
    const before = reads();
    const tick = recovery(f);
    assert.ok(tick);
    up = true;
    tick(); f.shiftClock(6000); tick(); await drain();
    assert.equal(reads(), before + 1, 'one read');
    tick(); await drain();
    assert.equal(reads(), before + 1, 'and no second while nothing failed');
    assert.equal(slips.querySelector('.load-fail'), null);
    f.clearTimers();
  });

  test(`${name}: back from hours away, polled figures say how old they are while their refresh is out, and the note goes when it lands`, async () => {
    let hang = null;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}], default: 'opus'});
      if (path.startsWith('/api/runs')) {
        const body = {runs: [], counts: {research_running: 0, research_queued: 0}, totals: {tried: 4, passed: 1}};
        return hang ? new Promise((resolve) => { hang = () => resolve(response(body)); }) : response(body);
      }
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const note = () => f.root.querySelector('#runs-stale').textContent;
    assert.equal(note(), '');
    await flip(f, true);
    f.shiftClock(2 * 3600e3);
    hang = true;
    await flip(f, false);  // back on the tab: the poll reads at once, slowly
    assert.equal(typeof hang, 'function', 'the refresh is out');
    assert.equal(note(), 'Last updated 2h ago, retrying', 'two hours old, said so while the refresh is out');
    hang(); await settle();
    assert.equal(note(), '', 'current again once it lands');
    f.clearTimers();
  });

  test(`${name}: the autopilot poll shares a status read already out instead of sending a second`, async () => {
    let answer = null;
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/autopilot/status') return new Promise((resolve) => { answer = () => resolve(response({mode: 'off'})); });
      return response({});
    }});
    f.location.pathname = '/';
    f.S.apAt = Date.now() - 19e3;  // over 18s old: the page mounting the panel reads it
    f.render(); await settle();
    const reads = () => f.requests.filter((r) => r.path === '/api/autopilot/status').length;
    assert.equal(reads(), 1);
    const tick = [...f.intervals.values()].find((cb) => String(cb).includes("getElementById('autopilot-float') && !document.hidden && !apFresh()"));
    f.shiftClock(20e3); tick(); await drain();
    assert.equal(reads(), 1, 'the poll waits on the read already out');
    answer(); await settle();
    f.clearTimers();
  });
}
