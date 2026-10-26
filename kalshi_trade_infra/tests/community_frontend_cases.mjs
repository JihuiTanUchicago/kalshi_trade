// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian):
// - the composer says, before anything is posted, who reads a post and what an attached strategy and
//   Share my P&L show (its rules never; paper and live totals, each named);
// - Share my P&L asks once before it posts real-money figures for everyone, and a second press posts;
// - a signed-out link to a post (/community#post-<id>, from the bell or an email) carries the post
//   through sign-in as ?post=<id>, and the feed opens that post from either form.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const sent = f => f.requests.filter(({options}) => options && options.method === 'POST');
const post = (id, over = {}) => ({id, body: 'Post ' + id, author: 'Bob', username: 'bob', created_at: '2026-10-17T10:00:00Z',
  mine: false, comments: 1, reactions: [], ...over});

export function communityCases({name, frontend}) {
  const community = (posts = []) => {
    const f = frontend({fetchImpl: (path, options) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community' && options && options.method === 'POST') return response({id: 99});
      if (path.startsWith('/api/community')) return response({posts});
      return response({});
    }});
    const proto = Object.getPrototypeOf(f.root);
    if (!('scrollIntoView' in proto)) proto.scrollIntoView = function (o) { this.scrolledTo = o; };
    if (!('click' in proto)) proto.click = function () { this.clicked = true; };
    f.location.pathname = '/community';
    return f;
  };

  test(`${name}: the composer says who reads a post and what a share shows, and Share my P&L asks before it posts`, async () => {
    const f = community();
    await f.viewCommunity(); await settle();
    const hint = f.root.querySelector('#post-hint');
    assert.ok(hint, 'the composer carries a line on who reads posts');
    assert.match(hint.textContent, /Everyone signed in to Tau can read posts and replies\./);
    assert.match(hint.textContent, /attached strategy shows its name, market and backtest result, never its rules/);
    assert.match(hint.textContent, /Share my P&(amp;)?L posts your paper and live \(real money\) totals/);
    assert.equal(f.root.querySelector('#post-body').getAttribute('aria-describedby'), 'post-hint');

    const share = f.root.querySelector('[data-share="pnl"]'), label = share.innerHTML;
    await share.onclick(); await settle();
    assert.equal(sent(f).length, 0, 'the first press only asks');
    assert.match(share.textContent, /Confirm: post P&L/);
    f.elapse(500); await share.onclick(); await settle();
    const posted = sent(f);
    assert.equal(posted.length, 1);
    assert.equal(posted[0].path, '/api/community');
    assert.equal(JSON.parse(posted[0].options.body).kind, 'pnl');
    assert.equal(share.innerHTML, label, 'the button reads Share my P&L again after it posts');
  });

  test(`${name}: a signed-out link to a post signs in back to that post, and the feed opens it from ?post=`, async () => {
    const out = frontend({fetchImpl: path => path === '/api/me' ? response({error: 'Please sign in.'}, 401) : response({})});
    out.S.me = null; out.location.pathname = '/community'; out.location.hash = '#post-11';
    await out.render(); await settle();
    assert.deepEqual(out.navigations, ['/signin?next=%2Fcommunity%3Fpost%3D11']);
    const google = out.root.querySelectorAll('a[data-native]').map(a => a.getAttribute('href')).filter(h => h.startsWith('/auth/google'));
    assert.deepEqual([...new Set(google)], ['/auth/google?next=%2Fcommunity%3Fpost%3D11']);

    // Any other page keeps its own path and query; a #post- on it is not a post link.
    const other = frontend({fetchImpl: path => path === '/api/me' ? response({error: 'Please sign in.'}, 401) : response({})});
    other.S.me = null; other.location.pathname = '/strategies/42'; other.location.hash = '#post-11';
    await other.render(); await settle();
    assert.deepEqual(other.navigations, ['/signin?next=%2Fstrategies%2F42']);

    // Back from sign-in on /community?post=11: that post is marked and its replies open.
    const f = community([post(12), post(11)]);
    f.location.search = '?post=11';
    await f.viewCommunity(); await settle();
    const art = f.root.querySelector('.post[data-id="11"]');
    assert.ok(art.classList.contains('post-target'));
    assert.equal(art.querySelector('[data-act="comments"]').clicked, true);
  });
}
