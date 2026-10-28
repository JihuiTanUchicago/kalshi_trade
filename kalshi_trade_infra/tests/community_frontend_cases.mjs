// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian):
// - the composer says, before anything is posted, who reads a post and what an attached strategy and
//   Share my P&L show (its rules never; paper and live totals, each named);
// - Share my P&L asks once before it posts real-money figures for everyone, and a second press posts;
// - the author can delete their own post (asks once); no one else sees Delete on it;
// - a signed-out link to a post (/community#post-<id>, from the bell or an email) carries the post
//   through sign-in as ?post=<id>, and the feed opens that post from either form.
import assert from './assert_text.mjs';
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

  test(`${name}: the author can delete their own post, after a second press, and the feed reads again without it`, async () => {
    let feed = [post(12, {mine: true}), post(11)];
    const f = frontend({fetchImpl: (path, options) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community/12/delete') { feed = feed.filter(p => p.id !== 12); return response({ok: true}); }
      if (path.startsWith('/api/community')) return response({posts: feed});
      return response({});
    }});
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    assert.equal(f.root.querySelector('.post[data-id="11"] [data-act="delete"]'), null, 'no Delete on another trader’s post');
    const del = f.root.querySelector('.post[data-id="12"] [data-act="delete"]');
    assert.match(del.textContent, /Delete/);
    const click = () => f.root.querySelector('#feed').listeners.get('click')({target: del});
    await click(); await settle();
    assert.equal(sent(f).length, 0, 'the first press only asks');
    assert.match(del.textContent, /Confirm delete/);
    f.elapse(500); await click(); await settle();
    assert.deepEqual(sent(f).map(({path}) => path), ['/api/community/12/delete']);
    assert.equal(f.root.querySelector('.post[data-id="12"]'), null);
    assert.ok(f.root.querySelector('.post[data-id="11"]'));
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

  test(`${name}: a strategy a later check left uncleared reads as its row does, in the picker and on its card`, async () => {
    const mine = [{id: 41, title: 'Cleared', status: 'passed'}, {id: 42, title: 'Missed', status: 'passed', verdict: 'missed_final'},
      {id: 43, title: 'Held', status: 'passed', verdict: 'held_back'}, {id: 44, title: 'Paper held', status: 'failed', verdict: 'held_back'},
      {id: 45, title: 'Noise', status: 'failed'}];
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/strategies') return response({strategies: mine});
      if (path.startsWith('/api/community')) return response({posts: []});
      return response({});
    }});
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const options = f.root.querySelector('#post-strat').querySelectorAll('option').slice(1);
    assert.deepEqual(options.map(o => o.textContent), ['Cleared (passed)', 'Missed (missed the final test)', 'Held (held back)',
      'Paper held (held back)', 'Noise (void)']);
    // The shared card stamps the verdict the server froze into it; an older card, or one without, keeps its status.
    const card = {kind: 'strategy', id: 42, title: 'Missed', market: 'btc15m', status: 'passed', pnl: 3.1, trades: 40, win_rate: 0.6, days: 9};
    const head = html => html.slice(0, html.indexOf('</b>') + 200);
    assert.match(head(f.postSnapshot({...card, verdict: 'missed_final'}, '')), /<span class="mk">Missed final test<\/span>/);
    assert.doesNotMatch(f.postSnapshot({...card, verdict: 'missed_final'}, ''), />Passed</);
    assert.match(f.postSnapshot({...card, verdict: 'held_back'}, '@bob'), /<span class="mk quiet">Held back<\/span>/);
    assert.match(f.postSnapshot(card, ''), /<span class="mk on">Passed<\/span>/);
  });
  test(`${name}: a strategy list that didn't load says so in the picker, and the composer still posts`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/strategies') return response({error: 'Something went wrong on our side. It’s been logged.'}, 500);
      if (path.startsWith('/api/community')) return response({posts: []});
      return response({});
    }});
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const options = f.root.querySelector('#post-strat').querySelectorAll('option');
    assert.deepEqual(options.map((o) => o.textContent), ['Your strategies didn’t load. Reload the page to attach one.']);
    assert.ok(f.root.querySelector('#composer-post [type=submit]'));
  });
  test(`${name}: a shared strategy with no gatekeeper record calls its figure later-period, never unseen`, () => {
    // Walk 2026-10-27: a pass from the old loose gate (the server's no_gatekeeper_record) and a backtest-only
    // strategy read "on unseen data" / "Unseen-data P&L" on the card, where its page and list say later-period.
    const f = frontend({fetchImpl: () => response({})});
    const card = {kind: 'strategy', id: 42, title: 'Loose', market: 'btc15m', status: 'passed', pnl: 5.5, trades: 48, win_rate: 0.58, days: 9};
    for (const over of [{no_gatekeeper_record: true}, {status: 'backtest-only'}]) {
      const html = f.postSnapshot({...card, ...over}, '@maya');
      assert.match(html, /later-period/i, JSON.stringify(over));
      // In the strategy page's words: the split date picked it, so it isn't held out.
      assert.match(html, /after the split date, which picked it \(later\u00a0period\u00a0· not\u00a0held\u00a0out\)[.,]/);
      // One colon before the figure: "…not held out: +$5.50" ran the reason into the P&L.
      assert.doesNotMatch(html, /not held out:/);
      assert.doesNotMatch(html, /unseen|never saw/i, JSON.stringify(over));
    }
    // The author's own card, a link, says it too.
    const own = f.postSnapshot({...card, no_gatekeeper_record: true}, '');
    assert.match(own, /^<a [^>]*href="\/strategies\/42"/); assert.match(own, /Backtest over 9 days after the split date, which picked it \(later\u00a0period\u00a0· not\u00a0held\u00a0out\)/);
    const kept = f.postSnapshot(card, '@maya');
    // A held-out one is later-period too, as the Strategies list's row and sort say, and says it was unseen data.
    assert.match(kept, /after the split date \(later\u00a0period\u00a0· unseen\u00a0data\)/); assert.match(kept, /later-period/i);
    assert.doesNotMatch(kept, /not[ \u00a0]held[ \u00a0]out|which picked it/);
  });

  test(`${name}: a shared strategy card names its backtest figure as the Strategies list does, held out or not`, () => {
    // Walk 2026-10-28: the list and its sort say "Later-period P&L"; a held-out card said "backtest on unseen data" in
    // Tau and "Unseen-data P&L" in Meridian. One family now: later period, plus unseen data or not held out, with
    // "·" bound to the word before it (SEP), as the Deploy hover says it; "on unseen data" and "picked it: not held
    // out" were the last of the older words.
    const f = frontend({fetchImpl: () => response({})});
    const card = {kind: 'strategy', id: 42, title: 'Kept', market: 'btc15m', status: 'passed', pnl: 5.5, trades: 48, win_rate: 0.58, days: 9};
    for (const over of [{}, {no_gatekeeper_record: true}, {status: 'backtest-only'}]) {
      const html = f.postSnapshot({...card, ...over}, '');
      assert.match(html, /[Ll]ater-period P&amp;L/, JSON.stringify(over));
      // Each piece of the pair holds together, so a phone breaks only after the "\u00b7" (it read "(later / period").
      assert.match(html, over.no_gatekeeper_record || over.status ? /\(later\u00a0period\u00a0· not\u00a0held\u00a0out\)/ : /\(later\u00a0period\u00a0· unseen\u00a0data\)/, JSON.stringify(over));
      assert.doesNotMatch(html, /later-period backtest|on unseen data|\(held out\)|picked it:|Unseen-data P&|never saw|out-of-sample/, JSON.stringify(over));
      // Its span is said once, and the figure is a signed amount.
      assert.equal((html.match(/over 9 days/g) || []).length, 1); assert.match(html, /\+\$5\.50/);
    }
    // Walk 2026-10-28: a held-out card with no later-period figure read "—" beside "(later period · unseen data)", a
    // note on a figure that wasn't there. With no figure there is no note, as a Strategies row with none has no line.
    for (const over of [{}, {no_gatekeeper_record: true}, {status: 'backtest-only'}, {status: 'rejected'}]) {
      for (const owner of ['', '@maya']) {
        const html = f.postSnapshot({...card, ...over, pnl: null}, owner);
        assert.match(html, /—/, JSON.stringify(over));
        assert.doesNotMatch(html, /later\u00a0period|unseen\u00a0data|not\u00a0held\u00a0out|split date|over 9 days/, JSON.stringify(over));
        if (owner) assert.match(html, /Only @maya can open this strategy[.;] [Aa]sk them to share a copy from its page\./);
        else assert.doesNotMatch(html, /snap-note/, JSON.stringify(over));
      }
    }
    // A Void, Rejected or missed-final idea's figure is never green: Meridian's card toned "+$42.17" under a Void
    // stamp, where its row on Strategies mutes it.
    for (const over of [{status: 'failed'}, {status: 'rejected'}, {verdict: 'missed_final'}]) {
      const html = f.postSnapshot({...card, pnl: 42.17, ...over}, '');
      assert.match(html, /\+\$42\.17/); assert.doesNotMatch(html, /class="[^"]*\b(gain|loss)\b[^"]*">\+\$42\.17/, JSON.stringify(over));
    }
  });
}
