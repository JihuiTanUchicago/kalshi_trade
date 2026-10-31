// Shared cases, run against each bundle's offline harness (Tau and Meridian): signing in as a different account in
// another tab. The session cookie is the browser's, so the stale tab's next read comes back as the new account. The
// server names the account on every reply (X-Tau-Account, app/server.py _send_json); a reply that isn't the tab's
// account never paints under the tab's name. The tab reloads into the account now signed in and says why there.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
// A reply as fetch gives it, with the account the server read it as.
const reply = (data, account, status = 200) => ({ok: status < 400, status, json: async () => data,
  headers: {get: (name) => (String(name).toLowerCase() === 'x-tau-account' && account != null ? String(account) : null)}});
// sessionStorage, kept in a Map the check can read.
const sessionMap = (init = {}) => {
  const m = new Map(Object.entries(init));
  return {m, store: {getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k)}};
};
// Whether a promise has settled after the microtasks run: a dropped reply never does.
const settled = async (p) => { let done = false; p.then(() => { done = true; }, () => { done = true; }); await settle(); return done; };
const MOVED = 'You signed in to a different account in another tab, so this tab switched to it too.';

export function accountSwitchCases({name, frontend}) {
  test(`${name}: a read that comes back as another account never paints, and the tab reloads into that account`, async () => {
    const s = sessionMap({tau_research_draft: 'fade the open', tau_post_draft: 'hello'});
    const f = frontend({session: s.store, fetchImpl: () => reply({deployments: [{id: 1, title: 'Not yours'}]}, 8)});
    f.S.timers.push(99999);  // a poll the page set (an id: clearTimers clears it with the page's clearInterval)
    const dropped = f.api('/api/deployments');
    assert.equal(await settled(dropped), false, 'the other account’s figures never reach the page');
    assert.equal(f.reloads.length, 1, 'the tab reloads into the account now signed in');
    assert.equal(s.m.get('tau_account_moved'), 'read');
    assert.equal(s.m.has('tau_research_draft') || s.m.has('tau_post_draft'), false, 'the old account’s unsent words don’t follow it over');
    assert.equal(f.S.timers.length, 0, 'its polls stop');
    // Every reply after that is dropped too, even one that names this tab's account (a read sent before the switch).
    const f2 = frontend({session: s.store, fetchImpl: (path) => reply({ok: true}, path === '/api/a' ? 8 : 7)});
    assert.equal(await settled(f2.api('/api/a')), false);
    assert.equal(await settled(f2.api('/api/b')), false);
    assert.equal(f2.reloads.length, 1, 'one reload, however many replies come back');
  });

  test(`${name}: a reply as this tab's own account, or with no account named, is used as before`, async () => {
    for (const account of [7, null]) {
      const f = frontend({fetchImpl: () => reply({ok: 'mine'}, account)});
      assert.deepEqual({...(await f.api('/api/deployments'))}, {ok: 'mine'});
      assert.equal(f.reloads.length, 0);
    }
    // Signed out (the boot read of /api/me, before the tab knows its account): nothing to compare, nothing dropped.
    const g = frontend({fetchImpl: () => reply({user: {id: 8}}, 8)});
    g.S.me = null;
    assert.equal((await g.api('/api/me')).user.id, 8);
    assert.equal(g.reloads.length, 0);
  });

  test(`${name}: a write that comes back as another account is sent once and the note says where it went`, async () => {
    for (const [status, why] of [[200, 'saved'], [404, 'unsaved'], [500, 'unconfirmed']]) {
      const s = sessionMap();
      const f = frontend({session: s.store, fetchImpl: () => reply(status < 400 ? {ok: true} : {error: 'No such strategy.'}, 8, status)});
      const p = f.api('/api/community', {body: 'draft'});
      assert.equal(await settled(p), false);
      for (let i = 0; i < 3; i++) await settle();
      assert.equal(f.requests.filter((r) => r.options && r.options.method === 'POST').length, 1, 'never sent again');
      assert.equal(s.m.get('tau_account_moved'), why);
      assert.equal(f.reloads.length, 1);
    }
  });

  test(`${name}: after that reload the page says once, at its top, that the tab switched account`, async () => {
    const texts = {
      read: MOVED,
      saved: MOVED + ' Your last change was saved to this account, not the one the tab showed before.',
      unsaved: MOVED + ' Your last change wasn’t saved.',
      unconfirmed: MOVED + ' Tau didn’t confirm your last change, so check this account before you try it again.',
    };
    for (const [why, text] of Object.entries(texts)) {
      const s = sessionMap({tau_account_moved: why, _themesync: '1'});
      const f = frontend({session: s.store, fetchImpl: () => reply({}, 8)});
      f.S.me = null;
      f.window.__TAU_ME__ = {user: {id: 8, name: 'New account', ui_theme: name === 'Meridian' ? 'meridian' : 'tau'}, markets: [], directions: []};
      f.location.pathname = '/settings';
      await f.render(); await settle();
      const note = f.root.querySelector('#account-flash');
      assert.ok(note, 'the note is on the page');
      assert.match(note.innerHTML, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
      assert.equal(s.m.has('tau_account_moved'), false, 'said once');
      assert.equal(f.reloads.length, 0);
      f.clearTimers();
    }
  });
}
