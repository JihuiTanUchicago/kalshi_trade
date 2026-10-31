// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian):
// - a theme switch saves to the account before it reloads: a save Tau didn't confirm stays on this
//   theme and says so (the signed-in page is served in the account's theme, so reloading anyway put
//   the reader back where they were with no word why); a saved one says so once, after the reload;
// - the theme radios: the checked one is the tab stop and the arrow keys move between them;
// - Sign out that Tau didn't confirm stays on the page and says the reader is still signed in, from
//   the profile menu and from the card wall's "Sign out instead"; a confirmed one (or a session that
//   had already ended) goes to sign-in.
// - Settings names the account (Google name and email, community name) and links to where the Kalshi keys
//   and the card are managed;
// - a confirmed sign-out forgets the unsent research, community and autopilot drafts on the device; one Tau didn’t confirm
//   keeps them;
// - the card wall's Save tapped before the card form is up says the form is still loading, and never
//   submits the bare form (which reloaded the page to "/?" and started the form over).
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const posts = f => f.requests.filter(({options}) => options && options.method === 'POST').map(({path}) => path);
// Each harness records focus its own way: Tau marks the element, Meridian moves document.activeElement.
const hasFocus = (f, el) => el.focused === true || f.document.activeElement === el;
const sessionStore = (init = {}) => {
  const m = new Map(Object.entries(init));
  return {map: m, getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k)};
};

export function settingsCases({name, frontend, current, storageFor, cardWallOpts}) {
  const other = current === 'tau' ? 'meridian' : 'tau';
  const label = {tau: 'Tau', meridian: 'Meridian'};

  test(`${name}: with live trading closed the email switch names the live-ready email as the email names itself, never "ready for live trading"`, async () => {
    // The server's live switch closed: that email's subject is "“…” cleared every paper-to-live check" and it says the
    // strategy stays on paper. Open, the line is as before.
    const line = async (open, stored) => {
      const f = frontend({fetchImpl: path => { throw new Error('Settings reads nothing on open: ' + path); }});
      f.S.me.live_trading_available = open;
      f.S.me.user = {...f.S.me.user, email: 'owner@example.invalid', email_opt_out: stored};
      await f.viewSettings();
      return f.root.querySelector('#email-state').textContent;
    };
    const on = await line(false, false), off = await line(false, true);
    assert.match(on, /^On\. Tau emails you about replies to your posts, mentions of your @name, new community posts \(at most one email every 4 hours\), and a paper strategy that clears every paper-to-live check\.$/);
    assert.match(off, /^Off\. Tau doesn’t email you about replies to your posts, mentions of your @name, new community posts, or a paper strategy that clears every paper-to-live check\. The bell in Tau still shows replies, mentions and those paper-to-live notices\.$/);
    for (const t of [on, off]) assert.doesNotMatch(t, /ready for live|ready-for-live/);
    assert.match(await line(true, false), /and a paper strategy that’s ready for live trading\.$/);
    assert.match(await line(true, true), /The bell in Tau still shows replies, mentions and ready-for-live notices\.$/);
  });

  test(`${name}: a theme switch whose save fails stays on this theme, says so, and changes nothing on the device`, async () => {
    const local = new Map([['tau_ui', current]]), session = sessionStore();
    const f = frontend({storage: storageFor(local), session, fetchImpl: path => {
      assert.equal(path, '/api/ui-theme'); return response({error: 'Synthetic preference outage'}, 503);
    }});
    await f.viewSettings();
    await f.root.querySelector(`[data-theme="${other}"]`).onclick(); await settle();
    assert.deepEqual(posts(f), ['/api/ui-theme']);
    assert.deepEqual(f.reloads, []);
    assert.equal(local.get('tau_ui'), current); assert.equal(session.map.size, 0);
    const said = f.root.querySelector('#theme-flash').innerHTML;
    assert.match(said, new RegExp(`Your theme is still ${label[current]}: Tau didn’t confirm the switch\\. Try again in a moment\\.`));
    assert.match(said, /class="notice bad"/);
    assert.doesNotMatch(said, /Synthetic preference outage/);
    assert.equal(f.root.querySelector(`[data-theme="${current}"]`).getAttribute('aria-checked'), 'true');
  });

  test(`${name}: a saved theme switch reloads once, and the new theme's Settings says it took, once`, async () => {
    const local = new Map([['tau_ui', current]]), session = sessionStore();
    const f = frontend({storage: storageFor(local), session, fetchImpl: (path, options) => {
      assert.equal(path, '/api/ui-theme'); return response({ok: true, theme: JSON.parse(options.body).theme});
    }});
    await f.viewSettings();
    assert.equal(f.root.querySelector('#theme-flash').innerHTML, '');
    // The hint says what a switch affects, apart from the flash a switch writes over.
    assert.match(f.root.querySelector('.sect').innerHTML, /<p class="hint"[^>]*>[^<]*wherever you sign in[^<]*<\/p>/);
    await f.root.querySelector(`[data-theme="${other}"]`).onclick(); await settle();
    assert.deepEqual(posts(f), ['/api/ui-theme']);
    assert.deepEqual(f.reloads, [true]);
    assert.equal(local.get('tau_ui'), other); assert.equal(session.map.get('tau_theme_saved'), other);
    // The reload lands in the theme it saved (this bundle stands in for it with the note set to its own theme).
    const after = sessionStore({tau_theme_saved: current});
    const g = frontend({session: after, fetchImpl: path => { throw new Error('Settings reads nothing on open: ' + path); }});
    await g.viewSettings();
    assert.match(g.root.querySelector('#theme-flash').innerHTML,
      new RegExp(`class="notice good".*Theme set to ${label[current]}\\. It’s saved to your account, so it applies wherever you sign in\\.`));
    assert.equal(after.map.size, 0);
    await g.viewSettings();
    assert.equal(g.root.querySelector('#theme-flash').innerHTML, '');
    // A note for the other theme (its reload never landed there) says nothing here.
    const stale = frontend({session: sessionStore({tau_theme_saved: other})});
    await stale.viewSettings();
    assert.equal(stale.root.querySelector('#theme-flash').innerHTML, '');
  });

  test(`${name}: the theme radios have one tab stop, the checked one, and the arrow keys move between them`, async () => {
    const f = frontend();
    await f.viewSettings();
    const [first, second] = f.root.querySelectorAll('[data-theme]');
    const mine = f.root.querySelector(`[data-theme="${current}"]`), theirs = f.root.querySelector(`[data-theme="${other}"]`);
    assert.equal(mine.getAttribute('tabindex'), '0'); assert.equal(theirs.getAttribute('tabindex'), '-1');
    for (const [from, key, to] of [[first, 'ArrowDown', second], [first, 'ArrowRight', second], [second, 'ArrowDown', first], [first, 'ArrowUp', second], [second, 'ArrowLeft', first]]) {
      from.focus(); from.focused = false; to.focused = false;
      let stopped = false;
      from.onkeydown({key, preventDefault: () => { stopped = true; }});
      assert.equal(hasFocus(f, to), true, `${key} moves focus`); assert.equal(stopped, true);
    }
    first.focus(); first.focused = false; second.focused = false;
    let stopped = false;
    first.onkeydown({key: 'Tab', preventDefault: () => { stopped = true; }});
    assert.equal(stopped, false); assert.equal(hasFocus(f, second), false);
    assert.deepEqual(posts(f), []);  // moving between them saves nothing
  });

  for (const [what, reply, out] of [
    ['got no reply', () => { throw new Error('Synthetic offline'); }, false],
    ['Tau failed (5xx)', () => response({error: "Something went wrong on our side. It’s been logged."}, 500), false],
    ['Tau confirmed', () => response({ok: true}), true],
    ['the session had already ended (401)', () => response({error: 'Please sign in.'}, 401), true],
  ]) {
    test(`${name}: Sign out in the profile menu when ${what}`, async () => {
      // After sign-out the app reads /api/me once more on its way to sign-in: signed out, it answers 401.
      const f = frontend({fetchImpl: path => (path === '/api/logout' ? reply() : path === '/api/me' ? response({error: 'Please sign in.'}, 401) : response({}))});
      f.location.pathname = '/settings';
      await f.viewSettings();
      const menu = f.root.querySelector('.profile-menu'), trig = f.root.querySelector('.profile-trig');
      menu.hidden = false; trig.setAttribute('aria-expanded', 'true');
      await f.root.querySelector('[data-action="signout"]').onclick(); await settle();
      assert.deepEqual(posts(f).filter(p => p === '/api/logout'), ['/api/logout']);
      if (out) {
        assert.equal(f.S.me, null);
        assert.ok(f.navigations.includes('/signin') || f.location.pathname === '/signin', 'goes to sign-in');
        return;
      }
      assert.ok(f.S.me && f.S.me.user, 'still signed in');
      assert.ok(!f.navigations.includes('/signin'), 'stays on the page');
      const note = f.root.querySelector('#main').querySelector('#signout-flash');
      assert.match(note.innerHTML, /class="notice bad".*You’re still signed in: Tau didn’t confirm the sign-out\. Check your connection and try again\./);
      assert.doesNotMatch(note.innerHTML, /logged/);
      assert.equal(menu.hidden, true); assert.equal(trig.getAttribute('aria-expanded'), 'false'); assert.equal(hasFocus(f, trig), true);
      // A second failure replaces the note instead of stacking another.
      await f.root.querySelector('[data-action="signout"]').onclick(); await settle();
      assert.equal(f.root.querySelector('#main').querySelectorAll('#signout-flash').length, 1);
    });
  }

  for (const [what, reply, out] of [
    ['got no reply', () => { throw new Error('Synthetic offline'); }, false],
    ['Tau confirmed', () => response({ok: true}), true],
  ]) {
    test(`${name}: the card wall's "Sign out instead" when ${what}`, async () => {
      const f = frontend({...cardWallOpts(), fetchImpl: path => {
        if (path === '/api/logout') return reply();
        if (path === '/api/me') return response({error: 'Please sign in.'}, 401);
        if (/^\/api\/billing(\?|$)/.test(path)) return response({configured: true, publishable_key: 'synthetic-only', auto_reload: false,
          balance: 0, spent: 0, free_bonus: 20, ledger: [], cards: []});
        if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
        return response({});
      }});
      f.location.pathname = '/'; Object.assign(f.S.me, {needs_card: true, free_bonus: 20});
      await f.paymentGate(); await settle();
      const dlg = f.document.body.querySelector('.pay-modal');
      await dlg.querySelector('[data-signout]').onclick(); await settle();
      if (out) {
        assert.equal(f.S.me, null); assert.equal(dlg.removed, true);
        assert.ok(f.navigations.includes('/signin') || f.location.pathname === '/signin', 'goes to sign-in');
        return;
      }
      assert.ok(f.S.me && f.S.me.needs_card, 'still signed in'); assert.notEqual(dlg.removed, true);
      assert.ok(!f.navigations.includes('/signin'));
      assert.match(dlg.querySelector('#pay-hint').innerHTML, /You’re still signed in: Tau didn’t confirm the sign-out\./);
    });
  }

  test(`${name}: the card wall's Save tapped before the card form is up says it is loading instead of reloading the page`, async () => {
    let answer;
    const billingRead = new Promise((resolve) => { answer = resolve; });
    const f = frontend({...cardWallOpts(), fetchImpl: path => {
      if (/^\/api\/billing(\?|$)/.test(path)) return billingRead;
      if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
      return response({});
    }});
    f.location.pathname = '/'; Object.assign(f.S.me, {needs_card: true, free_bonus: 20});
    const gate = f.paymentGate(); await settle();
    const dlg = f.document.body.querySelector('.pay-modal'), hint = () => dlg.querySelector('#pay-hint').innerHTML;
    let prevented = false;
    dlg.querySelector('#payform').onsubmit({preventDefault: () => { prevented = true; }});
    assert.equal(prevented, true, 'the bare form never submits');
    assert.match(hint(), /The card form is still loading\. Enter your card once it appears\./);
    assert.ok(!posts(f).includes('/api/billing/card-added'));
    // Once the form is up, the note goes and Save is the real save again.
    answer(response({configured: true, publishable_key: 'synthetic-only', auto_reload: false, balance: 0, spent: 0, free_bonus: 20}));
    await gate; await settle();
    assert.equal(hint(), '');
  });

  test(`${name}: Settings says who is signed in and links to where the Kalshi keys and the card are managed`, async () => {
    const f = frontend({fetchImpl: path => { throw new Error('Settings reads nothing on open: ' + path); }});
    Object.assign(f.S.me.user, {name: 'Ada <b>Lovelace</b>', email: 'ada@example.invalid', username: 'ada'});
    Object.assign(f.S.me, {kalshi_connected: false, kalshi_dev_connected: true});
    await f.viewSettings();
    const acct = f.root.querySelector('.account-settings').innerHTML;
    assert.match(acct, /<h2>Account<\/h2><p>Signed in with Google<\/p>/);
    assert.match(acct, /<dt>Name<\/dt><dd>Ada &lt;b&gt;Lovelace&lt;\/b&gt;<\/dd>/);
    assert.match(acct, /<dt>Email<\/dt><dd>ada@example\.invalid<\/dd>/);
    assert.match(acct, /<dt>Community name<\/dt><dd>@ada<\/dd>/);
    assert.match(acct, /<dt>Kalshi keys<\/dt><dd><span>No live key · demo key connected<\/span><a href="\/funds#connect-kalshi">Manage keys on Funds<\/a><\/dd>/);
    assert.match(acct, /<dt>Credits and card<\/dt><dd><a href="\/billing">Billing<\/a><\/dd>/);
    assert.match(acct, /Your name and email come from your Google account\. Change them there, and Tau shows the new ones the next time you sign in\./);
    // The theme stays the page's first section (its hint is what a switch writes beside).
    assert.match(f.root.querySelector('.sect').innerHTML, /data-theme=/);
    // A key on both, and no community name yet: it says so, and leaves the row out.
    const g = frontend();
    Object.assign(g.S.me, {kalshi_connected: true, kalshi_dev_connected: false});
    await g.viewSettings();
    const second = g.root.querySelector('.account-settings').innerHTML;
    assert.match(second, /Live key connected · no demo key/);
    assert.doesNotMatch(second, /Community name/);
  });

  for (const [what, reply, out] of [
    ['Tau confirmed', () => response({ok: true}), true],
    ['the session had already ended (401)', () => response({error: 'Please sign in.'}, 401), true],
    ['got no reply', () => { throw new Error('Synthetic offline'); }, false],
  ]) {
    test(`${name}: Sign out when ${what} ${out ? 'forgets' : 'keeps'} the unsent research, community and autopilot drafts on this device`, async () => {
      const local = new Map([['tau_ui', current], ['tau_tr_tab', 'paper'], ['tau_ap_draft:7', 'my unsent message'], ['tau_ap_draft:9', 'an older account’s']]);
      const session = sessionStore({tau_research_draft: JSON.stringify({uid: 7, path: '/research', text: 'my idea'}),
        tau_post_draft: JSON.stringify({uid: 7, text: 'my unsent post'})});
      const f = frontend({storage: storageFor(local), session,
        fetchImpl: path => (path === '/api/logout' ? reply() : path === '/api/me' ? response({error: 'Please sign in.'}, 401) : response({}))});
      f.location.pathname = '/settings';
      await f.viewSettings();
      await f.root.querySelector('[data-action="signout"]').onclick(); await settle();
      // The device's own settings (theme, a remembered tab) stay either way.
      assert.equal(local.get('tau_ui'), current); assert.equal(local.get('tau_tr_tab'), 'paper');
      if (out) {
        assert.deepEqual([...local.keys()].filter(k => k.startsWith('tau_ap_draft:')), []);
        assert.equal(session.map.has('tau_research_draft'), false);
        assert.equal(session.map.has('tau_post_draft'), false);
        return;
      }
      assert.equal(local.get('tau_ap_draft:7'), 'my unsent message');
      assert.ok(session.map.has('tau_research_draft'));
      assert.ok(session.map.has('tau_post_draft'));
    });
  }
}
