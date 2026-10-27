// Shared cases, run against each bundle's offline harness (Tau and Meridian): a phone on a bad connection
// (a train, a lift). The page says it is offline at once and stops saying so once the network is back,
// and a page that couldn't load while offline says that, not "Something went wrong".
import assert from 'node:assert/strict';
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
        assert.match(page, /Something went wrong/);
        assert.match(page, /Can&#39;t reach Tau\. Check your connection\./);
      }
      assert.ok(f.root.querySelector('[data-retry]'), 'Try again stays');
      f.clearTimers();
    }
  });
}
