// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian):
// - the bell lists a grouped notice with how many more it stands for, a notice with no page as plain
//   text, and moves focus into the list when it opens;
// - the autopilot status read brings new notices to the bell within a minute, without a reload.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const ago = ms => new Date(Date.now() - ms).toISOString();
const notesRead = f => f.requests.filter(({path}) => path === '/api/notifications').length;

export function bellCases({name, frontend}) {
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
}
