// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian):
// - the bell lists a grouped notice with how many more it stands for, a notice with no page as plain
//   text, and moves focus into the list when it opens;
// - the autopilot status read brings new notices to the bell within a minute, without a reload;
// - a list that didn't load still opens and says so, with Try again, and the next read fills it;
// - a refresh that failed with a list up keeps it and says quietly how old it is, with Try again (only then);
// - marking the list read that didn't save puts the dot back, and only the next open tries once more;
// - a bell link to a post opens the feed at that post with its replies, shows the feed from that post
//   when it is older than the newest page, and says so when the post is gone.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const ago = ms => new Date(Date.now() - ms).toISOString();
const notesRead = f => f.requests.filter(({path}) => path === '/api/notifications').length;
const post = (id, over = {}) => ({id, body: 'Post ' + id, author: 'Bob', username: 'bob', created_at: '2026-10-17T10:00:00Z',
  mine: true, comments: 1, reactions: [], ...over});

export function bellCases({name, frontend, detailStrategy}) {
  const dashboard = (notifications, extra = () => undefined) => frontend({notifications, fetchImpl: (path) => {
    const hit = extra(path);
    if (hit) return hit;
    if (path === '/api/notifications/read') return response({ok: true});
    if (path === '/api/autopilot/status') return response({mode: 'off'});
    return response({});
  }});

  test(`${name}: a grouped notice says how many more it stands for, one with no page is text, and opening moves focus in`, async () => {
    const f = dashboard({unread: 1, items: [
      {id: 9, kind: 'comment', body: 'Ana commented on your post.', link: '/community#post-4', created_at: ago(60e3), read: false, more: 2},
      {id: 5, kind: 'share', body: 'An old notice.', link: null, created_at: ago(2 * 86400e3), read: true, more: 0},
    ]});
    f.location.pathname = '/';
    await f.render(); await settle();
    const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
    const links = wrap.querySelectorAll('a.notif');
    assert.equal(links.length, 1);
    assert.equal(links[0].getAttribute('href'), '/community#post-4');
    assert.match(links[0].innerHTML, /<span class="notif-more">and 2 more like this<\/span>/);
    const plain = wrap.querySelectorAll('p.notif');
    assert.equal(plain.length, 1); assert.match(plain[0].textContent, /An old notice\./);
    assert.doesNotMatch(plain[0].innerHTML, /more like this/);
    // A disclosure, not a menu: the button names what it controls and the list is a labelled region.
    assert.equal(trig.getAttribute('aria-controls'), 'bell-menu'); assert.equal(trig.getAttribute('aria-haspopup'), null);
    assert.equal(menu.getAttribute('role'), 'region'); assert.equal(menu.getAttribute('aria-label'), 'Notifications');
    await trig.onclick({stopPropagation() {}});
    assert.equal(menu.hidden, false);
    assert.equal(links[0].focusOptions && links[0].focusOptions.preventScroll, true);  // focus went to the first notice
    await trig.onclick({stopPropagation() {}});

    // Nothing to open: focus goes to the list itself, which says it is empty.
    const g = dashboard({unread: 0, items: []});
    g.location.pathname = '/';
    await g.render(); await settle();
    const gm = g.root.querySelector('.bell-menu');
    await g.root.querySelector('.bell-trig').onclick({stopPropagation() {}});
    assert.equal(gm.focusOptions && gm.focusOptions.preventScroll, true);
    assert.match(gm.querySelector('.bell-empty').textContent, /No notifications yet/);
    // Empty, it says what will ring it, so a quiet first hour doesn't read as a broken bell.
    assert.match(gm.querySelector('.bell-empty').textContent, /It rings when a strategy goes on paper or is paused, passes its paper test or is ready for live, and if auto-reload can’t charge your card\./);
  });

  test(`${name}: with live trading closed the bell's summary and empty line name a live-ready notice as the notice does, never "ready for live"`, async () => {
    // The server's live switch closed (/api/me's live_trading_available): a strategy that clears every check waits on
    // paper, and its notice says "cleared every paper-to-live check". The summary over the list said "2 ready for live".
    const items = [1, 2, 3, 4].map((i) => ({id: i, kind: i < 3 ? 'live_ready' : 'paused', body: `Notice ${i}.`, link: null, created_at: ago(i * 60e3), read: false, more: 0}));
    const sum = async (open) => {
      const f = dashboard({unread: 4, items, unread_kinds: {live_ready: 2, paused: 2}});
      f.S.me.live_trading_available = open; f.location.pathname = '/';
      await f.render(); await settle();
      const el = f.root.querySelector('.bell-sum');
      f.clearTimers && f.clearTimers();
      return el ? el.textContent : '';
    };
    const shut = await sum(false);
    assert.match(shut, /2 cleared every paper-to-live check/);
    assert.doesNotMatch(shut, /ready for live/);
    assert.match(await sum(true), /2 ready for live/);  // open: as before
    const empty = async (open) => {
      const g = dashboard({unread: 0, items: []});
      g.S.me.live_trading_available = open; g.location.pathname = '/';
      await g.render(); await settle();
      const el = g.root.querySelector('.bell-empty');
      g.clearTimers && g.clearTimers();
      return el.textContent;
    };
    const closedEmpty = await empty(false);
    assert.match(closedEmpty, /It rings when a strategy goes on paper or is paused, passes its paper test or clears every paper-to-live check, and if auto-reload can’t charge your card\./);
    assert.doesNotMatch(closedEmpty, /ready for live/);
    assert.match(await empty(true), /passes its paper test or is ready for live, and/);
  });

  // Walk 2026-10-31: "131 new: 50 strategies put on paper · 50 comments": the lead counted every unread notice, the
  // parts only the newest 100 the server read (unread_kinds_of). Past that window the summary says which it covers.
  test(`${name}: the bell's summary says its parts cover the newest notices when more are unread than it read`, async () => {
    const items = [1, 2, 3, 4].map((i) => ({id: i, kind: i % 2 ? 'deployed' : 'comment', body: `Notice ${i}.`, link: null, created_at: ago(i * 60e3), read: false, more: 0}));
    const sum = async (d) => {
      const f = dashboard({items, ...d}); f.location.pathname = '/';
      await f.render(); await settle();
      const el = f.root.querySelector('.bell-sum');
      f.clearTimers && f.clearTimers();
      return el ? el.textContent : '';
    };
    assert.equal(await sum({unread: 131, unread_kinds: {deployed: 50, comment: 50}, unread_kinds_of: 100}),
      '131 new; the newest 100: 50 strategies put on paper\u00a0· 50 comments');
    // Every unread one counted in the parts: as before.
    assert.equal(await sum({unread: 6, unread_kinds: {deployed: 4, comment: 2}, unread_kinds_of: 100}),
      '6 new: 4 strategies put on paper\u00a0· 2 comments');
  });

  test(`${name}: a notice about a strategy no longer in the list says so as text, and a big count is grouped`, async () => {
    // Walk 2026-10-31: a shared strategy the user later deleted, and a forward-test pass of one deleted since,
    // linked to "Not found". The server marks them gone; the line says so and opens nothing.
    const f = dashboard({unread: 1234, items: [
      {id: 9, kind: 'share', body: 'Sam shared the strategy “Drift” with you.', link: '/strategies/14', created_at: ago(60e3), read: false, more: 0, gone: true},
      {id: 8, kind: 'passed', body: '“Fade” passed the paper forward gate.', link: '/strategies/6', created_at: ago(120e3), read: false, more: 0, gone: false},
    ]});
    f.location.pathname = '/';
    await f.render(); await settle();
    const wrap = f.root.querySelector('.bell-wrap');
    const links = wrap.querySelectorAll('a.notif');
    assert.deepEqual(links.map((a) => a.getAttribute('href')), ['/strategies/6']);
    const plain = wrap.querySelectorAll('p.notif');
    assert.equal(plain.length, 1);
    assert.match(plain[0].innerHTML, /Sam shared the strategy “Drift” with you\.<span class="notif-more">This strategy is no longer in your list\.<\/span>/);
    assert.doesNotMatch(plain[0].innerHTML, /strategies\/14/);
    // Counts carry their thousands separator, on screen and to a screen reader.
    assert.equal(wrap.querySelector('.bell-trig').getAttribute('aria-label'), 'Notifications, 1,234 unread');
    assert.match(wrap.querySelector('.bell-head').innerHTML, /<span class="bell-new">1,234 new<\/span>/);
  });

  // Walk 2026-10-31: "Bob replied to your post. and 3 more like this" stood for replies from Dana, Carol and Bob, and
  // a live pause's line for an earlier paper pause with another reason. "like this" only when they say the same.
  test(`${name}: a grouped line says "more like this" only when they say the same, and whom replies and mentions are from`, async () => {
    const at = ago(60e3), row = (id, kind, more, over) => ({id, kind, body: `Notice ${id}.`, link: `/x/${id}`, created_at: at, read: true, more, ...over});
    const f = dashboard({unread: 0, items: [
      row(9, 'comment', 3, {alike: false, from: ['Dana <b>x</b>', 'Carol', 'Bob'], from_more: 2}),
      row(8, 'mention', 1, {alike: false, from: ['Bob'], from_more: 0}),
      row(7, 'comment', 1, {alike: true, from: ['Carol'], from_more: 0}),
      row(6, 'paused', 1, {alike: false, from: [], from_more: 0}),
      row(5, 'reload_failed', 2, {alike: false, from: [], from_more: 0}),
      row(4, 'share', 1, {alike: false, from: [], from_more: 0}),
      row(3, 'comment', 2, {alike: false, from: [], from_more: 0}),
      row(2, 'passed', 0, {alike: true, from: [], from_more: 0}),
    ]});
    f.location.pathname = '/';
    await f.render(); await settle();
    const more = f.root.querySelectorAll('#bell-list .notif').map((n) => (n.querySelector('.notif-more') || {innerHTML: ''}).innerHTML);
    assert.deepEqual(more, [
      'and 3 more replies to this post, from Dana &lt;b&gt;x&lt;/b&gt;, Carol, Bob and 2 others',
      'and 1 more mention on this post, from Bob',
      'and 1 more like this',
      'and 1 earlier pause of this strategy',
      'and 2 earlier failed auto-reloads',
      'and 1 earlier notice about this',
      'and 2 more replies to this post',
      '']);
  });

  test(`${name}: a list with older notices past its lines says so under them, and an old notice names its year`, async () => {
    const old = ago(400 * 86400e3), recent = ago(2 * 86400e3);
    const year = (iso) => String(new Date(iso).getFullYear()), thisYear = String(new Date().getFullYear());
    const list = async (d) => {
      const f = dashboard(d); f.location.pathname = '/';
      await f.render(); await settle();
      return f.root.querySelector('#bell-list');
    };
    let el = await list({unread: 0, older: true, items: [
      {id: 2, kind: 'deployed', body: 'Recent.', link: '/strategies/2', created_at: recent, read: true, more: 0},
      {id: 1, kind: 'deployed', body: 'Old.', link: '/strategies/1', created_at: old, read: true, more: 0}]});
    const older = el.querySelector('.bell-older');
    assert.ok(older);
    assert.equal(older.textContent, 'Older notices aren’t listed here.');
    assert.equal(older.tagName, 'P');
    const times = el.querySelectorAll('a.notif time');
    assert.match(times[1].textContent, new RegExp(`\\b${year(old)}\\b`));
    assert.match(times[1].getAttribute('title'), new RegExp(`\\b${year(old)}\\b`));
    if (year(recent) === thisYear) assert.doesNotMatch(times[0].textContent, new RegExp(`\\b${thisYear}\\b`));  // this year's: as before
    el = await list({unread: 0, older: false, items: [{id: 2, kind: 'deployed', body: 'Recent.', link: '/strategies/2', created_at: recent, read: true, more: 0}]});
    assert.equal(el.querySelector('.bell-older'), null);
    el = await list({unread: 0, older: true, items: []});  // empty is empty, whatever it says
    assert.equal(el.querySelector('.bell-older'), null);
  });

  test(`${name}: a pause notice opens its strategy at Since deploying, focused, and a page without it at its heading`, async () => {
    if (!detailStrategy) return;
    const dep = {id: 3, mode: 'live', status: 'paused', status_reason: 'Live is down $4.20 over its first 6 closed trades.', realized_pnl: -4.2,
      closed_trades: 6, open_positions: 0, created_at: '2026-10-18T08:00:00Z'};
    const open = async (deployments, hash) => {
      const f = frontend({fetchImpl: (path) => path === '/api/strategies/42' ? response(detailStrategy({deployments})) : response({deployments: [], open_positions: []})});
      f.location.pathname = '/deploy';
      await f.render(); await settle();
      f.location.pathname = '/strategies/42'; f.location.hash = hash;  // the bell's link, as go() opens it
      await f.render(); await settle();
      return f;
    };
    let f = await open([dep], '#since-deploying');
    const spot = f.root.querySelector('#since-deploying');
    assert.ok(spot, 'the strategy lists its deployments');
    assert.equal(spot.focusOptions && spot.focusOptions.preventScroll, true, 'focus lands on what the notice is about');
    assert.equal(spot.getAttribute('tabindex'), '-1');
    assert.equal(f.root.querySelector('main h1').focusOptions, undefined, 'not on the heading screens above it');
    if (f.clearTimers) f.clearTimers();
    // Deployed no more (removed since): the page starts at its heading, as any page change does.
    f = await open([], '#since-deploying');
    assert.equal(f.root.querySelector('#since-deploying'), null);
    assert.equal(f.root.querySelector('main h1').focusOptions.preventScroll, true);
    if (f.clearTimers) f.clearTimers();
    // Only the bell's parts are taken: another hash on the page leaves focus to the heading.
    f = await open([dep], '#main');
    assert.equal(f.root.querySelector('main h1').focusOptions.preventScroll, true);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: a notice that arrives while the page sits open reaches the bell within a minute, without a reload`, async () => {
    const notes = {unread: 0, items: []};
    const f = dashboard(notes);
    f.location.pathname = '/';
    await f.render(); await settle();
    const dot = f.root.querySelector('.bell-dot');
    assert.equal(dot.hidden, true); assert.equal(notesRead(f), 1);
    notes.unread = 1;
    notes.items.push({id: 12, kind: 'paused', body: '“Edge” was paused automatically.', link: '/strategies/7', created_at: ago(5e3), read: false, more: 0});
    const ticks = () => [...f.intervals.values()].forEach(tick => tick());
    ticks(); await settle();
    assert.equal(notesRead(f), 1);  // the autopilot's 20s read doesn't re-read the bell every time
    f.shiftClock(61e3); ticks(); await settle();
    assert.equal(notesRead(f), 2);
    assert.equal(dot.hidden, false);
    assert.equal(f.root.querySelector('.bell-trig').getAttribute('aria-label'), 'Notifications, 1 unread');
    assert.match(f.root.querySelector('a.notif.unread').textContent, /was paused automatically/);
  });

  test(`${name}: a bell whose list didn't load still opens, says so, and Try again or the next read fills it`, async () => {
    const unread = {unread: 1, items: [{id: 3, kind: 'deploy', body: 'Edge made a trade.', link: '/deploy', created_at: ago(60e3), read: false, more: 0}]};
    let failing = true;
    const f = dashboard(() => (failing ? response({error: 'Something went wrong on our side.'}, 500) : response(structuredClone(unread))));
    f.location.pathname = '/';
    await f.render(); await settle();
    const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
    const list = wrap.querySelector('#bell-list');
    await trig.onclick({stopPropagation() {}});
    assert.equal(menu.hidden, false);  // it used to do nothing at all
    assert.match(list.textContent, /didn.t load just now/);
    const again = list.querySelector('[data-bell-retry]');
    assert.ok(again);
    failing = false;
    list.listeners.get('click')({target: again});
    await settle();
    assert.match(list.querySelector('a.notif').textContent, /Edge made a trade/);
    assert.equal(menu.hidden, false);
    assert.equal(f.requests.filter(({path}) => path === '/api/notifications/read').length, 1);  // read as it shows

    // Left closed, the autopilot's read within the minute brings the dot back without a tap.
    failing = true;
    const g = dashboard(() => (failing ? response({error: 'Something went wrong on our side.'}, 500) : response(structuredClone(unread))));
    g.location.pathname = '/';
    await g.render(); await settle();
    assert.equal(g.root.querySelector('.bell-dot').hidden, true);
    failing = false;
    g.shiftClock(61e3); [...g.intervals.values()].forEach(tick => tick()); await settle();
    assert.equal(g.root.querySelector('.bell-dot').hidden, false);
    assert.equal(g.root.querySelector('.bell-trig').getAttribute('aria-label'), 'Notifications, 1 unread');
    // A list that never loaded has no "couldn't refresh" line: it says it didn't load.
    assert.equal(g.root.querySelector('.bell-stale').hidden, true);
  });

  // Walk 2026-10-28: a refresh that failed kept the last list and said nothing, so it read as current.
  test(`${name}: a refresh that failed keeps the list and says quietly how old it is, with Try again; only then`, async () => {
    const notes = {unread: 0, items: [{id: 3, kind: 'deploy', body: 'Edge made a trade.', link: '/deploy', created_at: ago(60e3), read: true, more: 0}]};
    let failing = false;
    const f = dashboard(() => (failing ? response({error: 'Something went wrong on our side.'}, 500) : response(structuredClone(notes))));
    f.location.pathname = '/';
    await f.render(); await settle();
    const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
    const line = wrap.querySelector('.bell-stale'), ticks = () => [...f.intervals.values()].forEach(tick => tick());
    assert.equal(line.hidden, true, 'nothing after a read that came back');
    f.shiftClock(61e3); ticks(); await settle();
    assert.equal(notesRead(f), 2); assert.equal(line.hidden, true, 'nor after a refresh that came back');
    failing = true;
    f.shiftClock(3 * 60e3); ticks(); await settle();
    assert.equal(notesRead(f), 3);
    assert.equal(line.hidden, false);
    assert.equal(line.textContent.trim(), 'Couldn’t refresh. Showing notifications from 3 min ago. Try again');
    assert.equal(line.getAttribute('role'), null, 'quiet: not an alert');
    assert.match(wrap.querySelector('a.notif').textContent, /Edge made a trade/, 'the list it had stays');
    assert.doesNotMatch(line.textContent, /went wrong|\(500\)|undefined|NaN/);
    // Opened later, it says how old the list is as of then. Opening reads it again (the list is minutes old,
    // first_session_frontend_cases.mjs); that read failing too keeps the list and the line.
    f.shiftClock(2 * 60e3);
    await trig.onclick({stopPropagation() {}}); await settle();
    assert.equal(menu.hidden, false);
    assert.equal(notesRead(f), 4);
    assert.match(line.textContent, /from 5 min ago\./);
    assert.match(wrap.querySelector('a.notif').textContent, /Edge made a trade/);
    // Try again that fails again keeps the line (and the list); one that comes back takes the line away.
    const press = () => line.listeners.get('click')({target: line.querySelector('[data-bell-retry]')});
    press(); await settle();
    assert.equal(notesRead(f), 5); assert.equal(line.hidden, false);
    assert.ok(wrap.querySelector('a.notif'));
    failing = false;
    notes.items.unshift({id: 4, kind: 'paused', body: '“Edge” was paused automatically.', link: '/strategies/7', created_at: ago(5e3), read: false, more: 0});
    notes.unread = 1;
    press(); await settle();
    assert.equal(notesRead(f), 6);
    assert.equal(line.hidden, true);
    assert.equal(line.textContent, '');
    assert.match(wrap.querySelector('#bell-list').textContent, /was paused automatically/);
    // Nothing reads on its own because of the failure: no extra reads beyond the ones above.
    assert.deepEqual(f.requests.filter(({path}) => path === '/api/notifications').length, 6);
  });

  // Walk 2026-10-28: with /api/notifications slow (8s), a tap on the bell did nothing until the read came back.
  test(`${name}: the bell opens while its list is still reading, says so, and fills in where it stands`, async () => {
    let answer;
    const pending = new Promise((resolve) => { answer = resolve; });
    const f = dashboard(() => pending);
    f.location.pathname = '/';
    await f.render(); await settle();
    const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
    const list = wrap.querySelector('#bell-list');
    assert.equal(typeof trig.onclick, 'function', 'the bell answers a tap before its list has come back');
    await trig.onclick({stopPropagation() {}});
    assert.equal(menu.hidden, false);
    assert.equal(list.textContent, 'Loading notifications…');
    assert.equal(f.requests.filter(({path}) => path === '/api/notifications/read').length, 0, 'nothing to mark read yet');
    answer(response({unread: 1, items: [{id: 3, kind: 'deploy', body: 'Edge made a trade.', link: '/deploy', created_at: ago(60e3), read: false, more: 0}]}));
    await settle();
    assert.match(list.querySelector('a.notif').textContent, /Edge made a trade/);
    assert.equal(menu.hidden, false);
    assert.equal(f.requests.filter(({path}) => path === '/api/notifications/read').length, 1, 'read as it shows, open');
  });

  test(`${name}: marking the list read that didn't save puts the dot back, and the next open tries once more`, async () => {
    // The dot cleared on screen and the items came back unread on the next page: the bell said nothing was new.
    const notes = () => response(structuredClone({unread: 2, items: [
      {id: 8, kind: 'paused', body: '“Edge” was paused automatically.', link: '/strategies/7', created_at: ago(30e3), read: false, more: 0},
      {id: 7, kind: 'deploy', body: 'Edge made a trade.', link: '/deploy', created_at: ago(90e3), read: false, more: 0},
      {id: 2, kind: 'share', body: 'An old notice.', link: null, created_at: ago(2 * 86400e3), read: true, more: 0}]}));
    let saves = true;
    const marks = (f) => f.requests.filter(({path}) => path === '/api/notifications/read').length;
    const f = dashboard(notes, (path) => path === '/api/notifications/read'
      ? (saves ? response({ok: true}) : response({error: 'Something went wrong on our side.'}, 500)) : undefined);
    f.location.pathname = '/';
    await f.render(); await settle();
    const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig'), dot = wrap.querySelector('.bell-dot');
    const open = async () => { await trig.onclick({stopPropagation() {}}); await settle(); };
    assert.equal(dot.hidden, false);
    saves = false;
    await open();
    assert.equal(marks(f), 1);
    assert.equal(dot.hidden, false);  // back, as the server still has them
    assert.equal(trig.getAttribute('aria-label'), 'Notifications, 2 unread');
    await open();  // closes; nothing tries again on its own
    assert.equal(dot.hidden, false);
    f.shiftClock(61e3); [...f.intervals.values()].forEach((tick) => tick()); await settle();  // the minute's read
    assert.equal(marks(f), 1);
    assert.equal(dot.hidden, false);

    // The next open shows them as new again and tries once more; this time it saves.
    saves = true;
    await open();
    assert.equal(wrap.querySelectorAll('.notif.unread').length, 2);
    assert.equal(marks(f), 2);
    assert.equal(dot.hidden, true); assert.equal(trig.getAttribute('aria-label'), 'Notifications');
    await open(); await open();  // nothing unread: no mark to send
    assert.equal(marks(f), 2);
    assert.equal(dot.hidden, true);
  });

  const community = (posts, older) => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community') return response({posts});
      if (path.startsWith('/api/community?before=')) return response({posts: older(+path.split('=')[1])});
      return response({});
    }});
    const proto = Object.getPrototypeOf(f.root);
    if (!('scrollIntoView' in proto)) proto.scrollIntoView = function (o) { this.scrolledTo = o; };
    if (!('click' in proto)) proto.click = function () { this.clicked = true; };
    return f;
  };

  test(`${name}: a bell link to a post opens the feed at it with its replies, from further back, or says it is gone`, async () => {
    // In the newest page: that post is marked, focused and its replies are opened.
    let f = community([post(12), post(11)], () => []);
    f.location.hash = '#post-11';
    await f.viewCommunity(); await settle();
    let art = f.root.querySelector('.post[data-id="11"]');
    assert.ok(art.classList.contains('post-target')); assert.equal(art.focusOptions && art.focusOptions.preventScroll, true);
    assert.equal(art.querySelector('[data-act="comments"]').clicked, true);
    assert.equal(f.root.querySelector('#feed-note').innerHTML, '');
    assert.equal(f.requests.filter(({path}) => path.startsWith('/api/community?before=')).length, 0);

    // Older than the newest page: the feed starts at it and offers the latest posts again.
    f = community([post(40), post(39)], (before) => [post(before - 1), post(before - 2)]);
    f.location.hash = '#post-5';
    await f.viewCommunity(); await settle();
    art = f.root.querySelector('.post[data-id="5"]');
    assert.ok(art && art.classList.contains('post-target'));
    const note = f.root.querySelector('#feed-note');
    assert.match(note.textContent, /Showing posts from the one you opened/);
    const latest = note.querySelector('[data-latest]');
    latest.onclick(); await settle();
    assert.equal(note.innerHTML, '');
    assert.ok(f.root.querySelector('.post[data-id="40"]'));
    assert.equal(f.requests.at(-1).path, '/api/community');

    // Gone: the feed stays, and says the post isn't there any more.
    f = community([post(40)], () => [post(3)]);
    f.location.hash = '#post-7';
    await f.viewCommunity(); await settle();
    assert.match(f.root.querySelector('#feed-note').textContent, /That post isn’t here any more/);
    assert.ok(f.root.querySelector('.post[data-id="40"]'));
  });
}
