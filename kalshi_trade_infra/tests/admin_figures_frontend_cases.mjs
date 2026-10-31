// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the operator's
// figures on Admin and the System map (page-admin.js, one file for both themes), walked 2026-10-31 against a
// seeded fleet.
// - the Users count says how many accounts there are in all: the table lists the newest 100 and "100 shown"
//   said nothing of the rest; its money column says it is the credit balance, not paper money;
// - an orphaned position's oldest close reads with its date and zone: when() read one still to come as
//   "just now" and one long past as "settles Oct 20" (it is overdue: "was due");
// - a heartbeat past 90 minutes says how old it is: "stale" read the same for 2 hours and 3 days;
// - a feed line from another day says its day: every line was a bare clock, so days-old lines read as today's.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const ago = (s) => new Date(Date.now() - s * 1000).toISOString();

export function adminFigureCases({name, frontend}) {
  const adminPage = (data) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/admin') return response({waitlist: [], client_errors: [], orphaned_open: null, ...data});
      if (path === '/api/admin/kill-switch') return response({on: false, reason: '', by: '', env_on: false});
      return response({});
    }});
    f.S.me.is_admin = true;
    return f;
  };
  const users = (n) => Array.from({length: n}, (_, i) => ({id: n - i, email: `u${n - i}@example.invalid`, name: '', created_at: ago(86400 * i), balance: 20}));

  test(`${name}: Admin's Users count says how many accounts there are in all, and its money column is the credit balance`, async () => {
    const full = adminPage({users: users(100), users_total: 1234});
    await full.viewAdmin(); await settle();
    assert.equal(full.root.querySelector('#ucount').textContent, 'newest 100 of 1,234');
    const heads = full.root.querySelectorAll('#users thead th').map((th) => th.textContent);
    assert.deepEqual(heads, ['Email', 'Name', 'Joined', 'Credit balance']);
    assert.match(full.root.querySelector('#users').innerHTML, /data-lab="Credit balance">\$20\.00</);
    full.clearTimers();
    const few = adminPage({users: users(3), users_total: 3});
    await few.viewAdmin(); await settle();
    assert.equal(few.root.querySelector('#ucount').textContent, '3 in all');
    few.clearTimers();
  });

  test(`${name}: Admin's orphaned positions give the oldest close's date and zone, "was due" once it has passed`, async () => {
    const soon = new Date(Date.now() + 3 * 3600 * 1000).toISOString(), past = ago(10 * 86400);
    const f = adminPage({users: [], users_total: 0, orphaned_open: {total: 3, users: 1, by_mode: {
      paper: {positions: 2, users: 1, cost: 6, oldest_close: soon}, live: {positions: 1, users: 1, cost: 3, oldest_close: past}}}});
    await f.viewAdmin(); await settle();
    const line = f.root.querySelector('#o-state').textContent;
    assert.doesNotMatch(line, /just now/);
    assert.match(line, /Paper: \$6\.00 at cost, oldest settles \d\d:\d\d \S+\./);
    assert.match(line, /Live: \$3\.00 at cost, oldest was due [A-Z][a-z]{2} \d{1,2}, \d\d:\d\d \S+\./);
    assert.match(line, /3 open positions \(paper: 2, live: 1\)/);  // counts per mode; never one money figure for both
    f.clearTimers();
  });

  test(`${name}: the System map says how old a stalled feed's heartbeat is, and a feed line from another day its day`, async () => {
    const nodes = {forward: {age: 12, rows: 0}, cb_coll: {age: 7200, rows: 0}, features: {age: 3 * 86400 + 60, rows: 0},
      sim_engine: {age: 5400, paper: 1}, live_engine: {age: 5400, live: 1, demo: 2}};
    const events = [{kind: 'step', message: 'Backtesting idea 1.', created_at: ago(30)},
      {kind: 'done', message: '0 of 6 ideas passed every check.', created_at: ago(3 * 86400)}];
    const f = frontend({fetchImpl: (path) => (path === '/api/admin/system' ? response({nodes, events, now: new Date().toISOString()}) : response({}))});
    await f.viewSystem(); await settle();
    const m = (id) => f.root.querySelector(`[data-m="${id}"]`).textContent.replace(/\s+/g, ' ');  // SEP holds no-break spaces
    assert.equal(m('forward'), '12s ago');
    assert.equal(m('cb_coll'), '2h ago');
    assert.equal(m('features'), '3d ago');
    assert.equal(m('sim_engine'), '1 paper running · 2h ago');
    assert.equal(m('live_engine'), '1 live · 2 demo · 2h ago');
    const times = f.root.querySelectorAll('#sys-feed time');
    assert.match(times[0].textContent, /^\d\d:\d\d$/);  // today's: the clock, its date and zone on hover
    assert.match(times[1].textContent, /^[A-Z][a-z]{2} \d{1,2}$/);  // three days ago: the day
    assert.match(times[1].getAttribute('title'), /\d\d:\d\d/);
    f.clearTimers();
  });
}
