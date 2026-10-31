// Shared cases from the status walk (2026-10-31: the System page and the Dev Logs as a customer, a healthy system, a
// feed 20 minutes stale, a research backlog, an engine days quiet), run against each bundle's offline harness.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const SEP = ' · ';
// What settleAt says for a moment: the clock and zone today, the date too on another day.
const fmt = (o) => new Intl.DateTimeFormat(undefined, o);
const CLOCK_ZONE = fmt({hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'});
const LOG_STAMP = fmt({month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'});
const at = (ms) => { const d = new Date(ms); return (d.toDateString() === new Date().toDateString() ? CLOCK_ZONE : LOG_STAMP).format(d); };

export function statusWalkCases({name, frontend}) {
  const EXT = {kalshi: {kind: 'ext', series: 1, markets: 1}, coinbase: {kind: 'ext'}, bedrock: {kind: 'ext'}, stripe: {kind: 'ext'}};
  const open = async (nodes, now, reads) => {
    const f = frontend({fetchImpl: (path) => {
      if (path !== '/api/admin/system') return response({});
      return reads ? reads() : response({nodes, events: [], now});
    }});
    await f.viewSystem(); await settle();
    return f;
  };
  const pick = (f, id) => { f.root.querySelector(`.sys-node[data-id="${id}"]`).dispatchEvent({type: 'click'}); return f.root.querySelector('#sys-ds'); };
  const metric = (f, id) => f.root.querySelector(`[data-m="${id}"]`).textContent;
  const st = (f, id) => f.root.querySelector(`.sys-node[data-id="${id}"]`).getAttribute('data-st');

  // A feed 20 minutes behind read "20m ago" in its box and details, the same words as a running one but for the dot's
  // colour, and the engine three days quiet read "3d ago". Each box with a heartbeat now says its state in words in
  // its details, with the clock time and zone it was last heard from once it is late; an outside service says when
  // Tau last had data from it. The read's time names its zone ("updated 12:11" named none).
  test(`${name}: a System box says in words when its part is stale, since when and in which zone`, async () => {
    const nowMs = Date.now(), now = new Date(nowMs).toISOString();
    const f = await open({...EXT, web: {up: true, users: 1}, db: {rows: 0, size_mb: 3},
      forward: {age: 120, rows: 0}, cb_coll: {age: 1200, rows: 0}, features: {age: 20, rows: 0},
      agents: {running: 1, queued: 30, done: 13, mine: true}, backtest: {strategies: 1, mine: true},
      sim_engine: {age: 3 * 86400, paper: 1, mine: true}, live_engine: {age: 3 * 86400, live: 0, demo: 0, mine: true}}, now);
    assert.equal(f.root.querySelector('#sys-stamp').textContent, `updated ${at(nowMs)}`);
    assert.equal(pick(f, 'cb_coll').textContent, `Stale since ${at(nowMs - 1200e3)} (20 minutes ago).`);
    assert.equal(pick(f, 'coinbase').textContent, `No new data from Coinbase since ${at(nowMs - 1200e3)} (20 minutes ago). The page can’t tell whose end stopped.`);
    assert.equal(pick(f, 'forward').textContent, `Running late: last heard from at ${at(nowMs - 120e3)}, 2 minutes ago.`);
    assert.equal(pick(f, 'kalshi').textContent, 'Tau had new data from Kalshi API 2 minutes ago.');
    assert.equal(pick(f, 'features').textContent, 'Running: last heard from 20 seconds ago.');
    assert.equal(pick(f, 'sim_engine').textContent, `Stale since ${at(nowMs - 3 * 86400e3)} (3 days ago).`);
    assert.match(pick(f, 'sim_engine').textContent, /^Stale since [A-Z][a-z]{2} \d{1,2}, /, 'a day that is not today says its date');
    for (const id of ['bedrock', 'stripe', 'db', 'web', 'agents', 'backtest']) assert.equal(pick(f, id), null, `${id} has no heartbeat to state`);
    // Counts of one read as one: "1 strategies tested", "1 markets".
    assert.equal(metric(f, 'backtest'), '1 strategy tested');
    assert.equal(metric(f, 'kalshi'), `1 market${SEP}1 series`);
    assert.equal(metric(f, 'web'), `1 user${SEP}serving`);
    f.clearTimers();
  });

  test(`${name}: a System box with no heartbeat yet says so`, async () => {
    const f = await open({...EXT, forward: {age: null, rows: 0}}, new Date().toISOString());
    assert.equal(pick(f, 'forward').textContent, 'Not heard from yet.');
    assert.equal(pick(f, 'kalshi').textContent, 'Tau hasn’t had data from Kalshi API yet.');
    f.clearTimers();
  });

  // While reads failed, the poll backed off (up to two minutes) and every box kept the ages of the last good read: a
  // feed read "6s ago" with a green dot for as long as the page couldn't ask. The ages now grow from that read, the
  // dot follows them, and the next good read takes over.
  test(`${name}: while System reads fail, the boxes' ages grow from the last good read`, async () => {
    let fail = false;
    const nowMs = Date.now(), now = new Date(nowMs).toISOString();
    const f = await open(null, now, () => (fail ? response({error: 'unavailable'}, 503)
      : response({nodes: {...EXT, cb_coll: {age: 6, rows: 0}, sim_engine: {age: 3, paper: 1, mine: true}}, events: [], now})));
    assert.equal(metric(f, 'cb_coll'), '6s ago'); assert.equal(st(f, 'cb_coll'), 'live');
    assert.equal(f.S.timers.length, 2, 'the poll and the clock that ages the boxes');
    const [readTick, ageTick] = f.S.timers.map((id) => f.intervals.get(id));
    pick(f, 'cb_coll');
    ageTick(); await settle();
    assert.equal(metric(f, 'cb_coll'), '6s ago', 'a read a moment old stands as it is');
    fail = true;
    f.shiftClock(120e3);
    readTick(); await settle();
    ageTick(); await settle();
    assert.equal(metric(f, 'cb_coll'), '2m ago'); assert.equal(st(f, 'cb_coll'), 'warn');
    assert.equal(metric(f, 'sim_engine'), `1 paper running${SEP}2m ago`);
    assert.equal(f.root.querySelector('#sys-ds').textContent, `Running late: last heard from at ${at(nowMs - 6e3)}, 2 minutes ago.`,
      'the time it was last heard from stays put as its age grows');
    f.shiftClock(600e3);
    ageTick(); await settle();
    assert.equal(metric(f, 'cb_coll'), '12m ago'); assert.equal(st(f, 'cb_coll'), 'down');
    assert.equal(f.root.querySelector('#sys-ds').textContent, `Stale since ${at(nowMs - 6e3)} (12 minutes ago).`);
    f.clearTimers();
  });

  // The Dev Logs' count of shipped entries read "1 updates" for one, and ran its digits together past a thousand.
  test(`${name}: the Dev Logs count their shipped entries in words that agree`, async () => {
    for (const [n, said, chip] of [[1, '1 update', '1'], [1204, '1,204 updates', '1,204']]) {
      const shipped = Array.from({length: n}, (_, i) => ({date: '2026-10-31', title: 'Entry ' + i, detail: ''}));
      const f = frontend({fetchImpl: (path) => (path === '/api/devlog' ? response({planned: [], shipped}) : response({}))});
      await f.viewDevLog(); await settle();
      assert.equal(f.root.querySelector('[data-dlpanel="shipped"] .sect-head p').textContent, said);
      assert.equal(f.root.querySelector('[data-dltab="shipped"]').textContent, `Shipped${SEP}${chip}`);
      f.clearTimers();
    }
  });
}
