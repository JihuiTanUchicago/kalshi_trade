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

  // Walk 2026-10-31: a name starting with an emoji put half of its surrogate pair in the avatar, a broken-glyph box.
  test(`${name}: an avatar's placeholder letter is the name's first character whole, an emoji as itself`, async () => {
    const f = community([post(13, {author: '🦊 Fox Mulder', username: 'fox'}), post(12, {author: 'مريم', username: 'maryam'}),
      post(11, {author: 'ada', username: 'ada'})]);
    await f.viewCommunity(); await settle();
    const letter = id => f.root.querySelector(`.post[data-id="${id}"] .pfp.ph`).textContent;
    assert.equal(letter(13), '🦊');
    assert.equal(letter(12), 'م');
    assert.equal(letter(11), 'A');
    for (const id of [13, 12, 11]) assert.doesNotMatch(letter(id), /[\uD800-\uDFFF]/u);
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

  // Walk 2026-10-31: the session ended while a post was being written (a feed poll's 401, or Post's own) and sign-in
  // brought the reader back to an empty box. The post is kept for the tab and put back for the same account.
  test(`${name}: a post typed when the session ran out is there again after sign-in, for that account only, and goes once it posts`, async () => {
    const m = new Map();
    const session = {map: m, getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k)};
    const open = (uid, posted = []) => {
      const f = frontend({session, fetchImpl: (path, options) => {
        if (path === '/api/strategies') return response({strategies: []});
        if (path === '/api/community' && options && options.method === 'POST') { posted.push(JSON.parse(options.body).body); return response({id: 99}); }
        if (path.startsWith('/api/community')) return response({posts: []});
        return response({});
      }});
      f.S.me.user.id = uid;
      f.location.pathname = '/community';
      return f;
    };
    const f = open(7);
    await f.viewCommunity(); await settle();
    const ta = f.root.querySelector('#post-body');
    ta.value = 'Half a thought about @Carol and BTC closes';
    ta.dispatchEvent({type: 'input'});
    assert.equal(JSON.parse(m.get('tau_post_draft')).text, 'Half a thought about @Carol and BTC closes');
    f.clearTimers();

    // Signed back in on the same tab: the box has it (Meridian's folded New post opens to show it).
    const posted = [];
    const g = open(7, posted);
    await g.viewCommunity(); await settle();
    assert.equal(g.root.querySelector('#post-body').value, 'Half a thought about @Carol and BTC closes');
    const fold = g.root.querySelector('.community-compose');
    if (fold) assert.equal(fold.open, true);
    // Another account on this tab never sees it.
    const other = open(9);
    await other.viewCommunity(); await settle();
    assert.equal(other.root.querySelector('#post-body').value || '', '');
    other.clearTimers();
    // Posted: it goes.
    await g.root.querySelector('#composer-post').onsubmit({preventDefault() {}}); await settle();
    assert.deepEqual(posted, ['Half a thought about @Carol and BTC closes']);
    assert.equal(m.has('tau_post_draft'), false);
    g.clearTimers();
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

  // The first version's simple backtest stored strategies as Void with no gatekeeper record. Their cards said "(later
  // period · unseen data)"; the feed now flags them (no_gatekeeper_record on a failed card), and they say "not held
  // out" as their Strategies row and page do, without "which picked it": nothing picked a void one.
  test(`${name}: a shared Void strategy with no gatekeeper record says not held out, never unseen data`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const card = {kind: 'strategy', id: 42, title: 'Old void', market: 'btc15m', status: 'failed', pnl: -1.5, trades: 40, win_rate: 0.41, days: 9};
    for (const owner of ['', '@maya']) {
      const html = f.postSnapshot({...card, no_gatekeeper_record: true}, owner);
      assert.match(html, /Backtest over 9 days after the split date \(later\u00a0period\u00a0· not\u00a0held\u00a0out\)[.,]/, owner);
      assert.doesNotMatch(html, /unseen|picked it|never saw/i, owner);
      assert.match(html, /Void/);
    }
    // A Void card with its record (the gatekeeper's inconclusive verdict), or from a feed that sends no flag, keeps its words.
    assert.match(f.postSnapshot(card, ''), /after the split date \(later\u00a0period\u00a0· unseen\u00a0data\)/);
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
    // Walk 2026-10-30: Tau's card said only "Backtest…" under "+$42.17" and a Passed stamp, in a feed of paper and live
    // results; Meridian's said "not paper or live trading". Every card with a figure says so now, for its owner and anyone.
    for (const over of [{}, {no_gatekeeper_record: true}, {status: 'backtest-only'}, {status: 'failed', no_gatekeeper_record: true}]) {
      for (const owner of ['', '@maya']) {
        assert.match(f.postSnapshot({...card, ...over}, owner), /\), not paper or live trading\./, JSON.stringify(over) + owner);
      }
    }
    // A Void, Rejected or missed-final idea's figure is never green: Meridian's card toned "+$42.17" under a Void
    // stamp, where its row on Strategies mutes it.
    for (const over of [{status: 'failed'}, {status: 'rejected'}, {verdict: 'missed_final'}]) {
      const html = f.postSnapshot({...card, pnl: 42.17, ...over}, '');
      assert.match(html, /\+\$42\.17/); assert.doesNotMatch(html, /class="[^"]*\b(gain|loss)\b[^"]*">\+\$42\.17/, JSON.stringify(over));
    }
  });
  test(`${name}: a sent reply shows in its thread, which opens again after the feed repaints`, async () => {
    // Walk 2026-10-30: the repaint after a reply closed every thread, so the reply vanished with its thread and only
    // "3 replies" turning "4 replies" said it had gone through.
    let count = 1;
    const replies = [{body: 'First', author: 'Ana', username: 'ana', created_at: '2026-10-17T10:00:00Z'}];
    const f = frontend({fetchImpl: (path, options) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community/11/comments' && options && options.method === 'POST') {
        replies.push({body: JSON.parse(options.body).body, author: 'Dev', username: 'dev', created_at: '2026-10-17T10:05:00Z'}); count += 1;
        return response({ok: true});
      }
      if (path === '/api/community/11/comments') return response({comments: replies.slice()});
      if (path.startsWith('/api/community')) return response({posts: [post(11, {comments: count})]});
      return response({});
    }});
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const feed = f.root.querySelector('#feed');
    const proto = Object.getPrototypeOf(f.root), had = Object.prototype.hasOwnProperty.call(proto, 'click'), was = proto.click;
    proto.click = function () { return feed.listeners.get('click')({target: this}); };
    try {
      await feed.querySelector('[data-act="comments"]').click(); await settle();
      const form = feed.querySelector('.post[data-id="11"] .cmt-form');
      form.querySelector('input').value = 'Thanks, @ana';
      await form.onsubmit({preventDefault() {}, currentTarget: form}); await settle();
      assert.deepEqual(sent(f).map(({path}) => path), ['/api/community/11/comments']);
      const art = feed.querySelector('.post[data-id="11"]');
      assert.match(art.querySelector('[data-act="comments"]').textContent, /2 replies/);
      assert.equal(art.querySelector('.comments').hidden, false, 'the thread is open again');
      assert.match(art.querySelector('.cmt-list').textContent, /Thanks, /);
      assert.ok(art.querySelector('.cmt-form'), 'with its reply box');
    } finally { if (had) proto.click = was; else delete proto.click; }
  });
  test(`${name}: a grouped post's time says its zone, and its date on another day than today`, async () => {
    // Walk 2026-10-30 (Meridian at 390px most of all): a post grouped under its author's header showed a bare "07:49",
    // with no zone and no date, under a header that says "Oct 17". It reads as settleAt does: the date on another day.
    const now = Date.now(), iso = (ms) => new Date(ms).toISOString();
    const posts = [post(14, {created_at: iso(now - 60000)}), post(13, {created_at: iso(now - 120000)}),
      post(12, {created_at: '2026-10-17T10:02:00Z'}), post(11, {created_at: '2026-10-17T10:00:00Z'})];
    const f = community(posts);
    await f.viewCommunity(); await settle();
    const feed = f.root.querySelector('#feed');
    const at = (id) => feed.querySelector(`.post[data-id="${id}"]`);
    assert.ok(at(13).querySelector('.gutter-time') && at(11).querySelector('.gutter-time'), 'each run groups under its header');
    assert.equal(at(14).querySelector('.gutter-time'), null, 'a header post keeps its avatar, no gutter time');
    assert.equal(at(12).querySelector('.gutter-time'), null);
    const time = (id) => at(id).querySelector('.gutter-time');
    const shown = (id) => time(id).textContent.replace(/ /g, ' ');
    const stamp = (s, o) => new Intl.DateTimeFormat(undefined, o).format(new Date(s));
    const zone = (s) => new Intl.DateTimeFormat(undefined, {timeZoneName: 'short'}).formatToParts(new Date(s)).find((p) => p.type === 'timeZoneName').value;
    // Another day: the date, the clock and the zone, as a market's close says them.
    assert.equal(shown(11), stamp(posts[3].created_at, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'}));
    assert.ok(shown(11).endsWith(' ' + zone(posts[3].created_at)), shown(11));
    // Today: the clock and its zone (just after midnight the minute before falls on yesterday, with its date).
    assert.ok(shown(13).includes(stamp(posts[1].created_at, {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'})), shown(13));
    assert.ok(shown(13).endsWith(' ' + zone(posts[1].created_at)), shown(13));
    assert.equal(time(13).getAttribute('datetime'), posts[1].created_at);
  });
  // A reaction pill toggles the reader's own reaction. Tau's said whether it was on only by its colour, so a screen
  // reader heard "🔥, 2" alike either way: each pill says it (aria-pressed), and again once a press has toggled it.
  test(`${name}: a reaction pill says whether the reaction is the reader's own, before and after a press`, async () => {
    let reactions = [{emoji: '🔥', count: 2, mine: false, names: ['Ann', 'Bob']}, {emoji: 'tau', count: 1, mine: true, names: ['Offline fixture']}];
    const f = frontend({fetchImpl: (path, options) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community/5/react') {
        assert.deepEqual(JSON.parse(options.body), {emoji: '🔥'});
        reactions = [{...reactions[0], count: 3, mine: true}, reactions[1]];
        return response({reactions});
      }
      if (path.startsWith('/api/community')) return response({posts: [post(5, {reactions})]});
      return response({});
    }});
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const feed = f.root.querySelector('#feed');
    const pressed = () => feed.querySelectorAll('.rx[data-emoji]').map((b) => [b.dataset.emoji, b.getAttribute('aria-pressed'), b.classList.contains('on')]);
    assert.deepEqual(pressed(), [['🔥', 'false', false], ['tau', 'true', true]]);
    feed.listeners.get('click')({target: feed.querySelector('.rx[data-emoji]')}); await settle();
    assert.deepEqual(pressed(), [['🔥', 'true', true], ['tau', 'true', true]]);
    assert.equal(feed.querySelector('[data-react-add]').hasAttribute('aria-pressed'), false, 'Add a reaction is an action, not a toggle');
    f.clearTimers();
  });

  // Keyboard and screen-reader walk 2026-10-31: the emoji picker opened at the end of the page with focus left on
  // "Add a reaction", so Tab went on to the next post and never reached an emoji; Esc left focus where it was; the button
  // never said it had opened anything; and a pick (or a press of a pill) drew the chips again and dropped focus to the top.
  test(`${name}: the emoji picker takes focus, moves by arrow, hands focus back on Esc or a pick, and says it is open`, async () => {
    let reactions = [{emoji: '🔥', count: 1, mine: false, names: ['Ann']}];
    const f = frontend({globals: {innerWidth: 1366}, fetchImpl: (path, options) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community/5/react') {
        const {emoji} = JSON.parse(options.body);
        reactions = emoji === '🔥' ? [{...reactions[0], count: 2, mine: true}] : [...reactions, {emoji, count: 1, mine: true, names: ['Me']}];
        return response({reactions});
      }
      if (path.startsWith('/api/community')) return response({posts: [post(5, {reactions})]});
      return response({});
    }});
    const proto = Object.getPrototypeOf(f.root);
    if (!('getBoundingClientRect' in proto)) proto.getBoundingClientRect = () => ({left: 100, right: 140, top: 400, bottom: 428, width: 40, height: 28});
    // Both harnesses: focus moves document.activeElement, as a browser's does.
    const focus0 = proto.focus;
    proto.focus = function (o) { focus0.call(this, o); f.document.activeElement = this; };
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const feed = f.root.querySelector('#feed');
    const add = () => feed.querySelector('.post[data-id="5"] [data-react-add]');
    const pop = () => f.document.body.querySelectorAll('.emoji-pop').filter((p) => p.isConnected).at(-1);
    const docKey = (key) => { const ev = {key, preventDefault() {}}; for (const [n, cb] of f.documentListeners) if (n === 'keydown') cb(ev); };
    const opener = add();
    assert.equal(opener.getAttribute('aria-expanded'), 'false', 'it says it opens something, shut');
    feed.listeners.get('click')({target: opener}); await settle();
    const p = pop();
    assert.ok(p, 'the picker opened');
    assert.equal(p.getAttribute('role'), 'group');
    assert.equal(p.getAttribute('aria-label'), 'Pick a reaction');
    assert.equal(opener.getAttribute('aria-expanded'), 'true');
    const eps = p.querySelectorAll('.ep');
    assert.equal(f.document.activeElement, eps[0], 'focus is on the first emoji');
    assert.equal(eps[0].getAttribute('aria-label'), 'Tau', 'the Tau mark has a name');
    let stopped = 0;
    p.listeners.get('keydown')({key: 'ArrowRight', preventDefault() { stopped++; }});
    assert.equal(f.document.activeElement, eps[1]);
    p.listeners.get('keydown')({key: 'ArrowDown', preventDefault() { stopped++; }});
    assert.equal(f.document.activeElement, eps[6], 'down is a row of five on');
    p.listeners.get('keydown')({key: 'End', preventDefault() { stopped++; }});
    assert.equal(f.document.activeElement, eps.at(-1));
    assert.equal(stopped, 3);
    f.elapse(0);  // the picker listens for Esc from the next tick
    docKey('Escape');
    assert.equal(p.isConnected, false, 'Esc closes it');
    assert.equal(opener.getAttribute('aria-expanded'), 'false');
    assert.equal(f.document.activeElement, opener, 'focus is back on Add a reaction');
    // Tab inside the picker closes it and leaves from the button (the key is not stopped).
    feed.listeners.get('click')({target: opener}); await settle();
    const p2 = pop(); let tabStopped = false;
    p2.listeners.get('keydown')({key: 'Tab', preventDefault() { tabStopped = true; }});
    assert.equal(p2.isConnected, false); assert.equal(tabStopped, false);
    assert.equal(f.document.activeElement, opener);
    // A pick reacts, the chips are drawn again, and focus lands on the new Add a reaction.
    feed.listeners.get('click')({target: opener}); await settle();
    const p3 = pop();
    p3.listeners.get('click')({target: p3.querySelectorAll('.ep')[1]}); await settle();
    assert.equal(p3.isConnected, false);
    assert.deepEqual(feed.querySelectorAll('.post[data-id="5"] .rx[data-emoji]').map((b) => b.dataset.emoji), ['🔥', '👍']);
    assert.notEqual(add(), opener, 'the chips were drawn again');
    assert.equal(f.document.activeElement, add());
    assert.equal(add().getAttribute('aria-expanded'), 'false');
    // A pill pressed from the keyboard keeps focus on the same pill once the chips are drawn again.
    const fire = feed.querySelector('.post[data-id="5"] .rx[data-emoji="🔥"]');
    fire.focus();
    feed.listeners.get('click')({target: fire}); await settle();
    const fire2 = feed.querySelector('.post[data-id="5"] .rx[data-emoji="🔥"]');
    assert.notEqual(fire2, fire);
    assert.equal(fire2.getAttribute('aria-pressed'), 'true');
    assert.equal(f.document.activeElement, fire2);
    f.clearTimers();
  });

  test(`${name}: a post's reply link says whether its replies are open`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community/5/comments') return response({comments: [{author: 'Ann', body: 'Hi', created_at: '2026-10-17T10:00:00Z'}]});
      if (path.startsWith('/api/community')) return response({posts: [post(5)]});
      return response({});
    }});
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const feed = f.root.querySelector('#feed');
    const link = feed.querySelector('.post[data-id="5"] [data-act="comments"]');
    assert.equal(link.getAttribute('aria-expanded'), 'false');
    feed.listeners.get('click')({target: link}); await settle();
    assert.equal(link.getAttribute('aria-expanded'), 'true');
    assert.equal(feed.querySelector('.post[data-id="5"] .comments').hidden, false);
    feed.listeners.get('click')({target: link}); await settle();
    assert.equal(link.getAttribute('aria-expanded'), 'false');
    f.clearTimers();
  });

  // Walked 2026-10-31 (both themes, 1280 and 390px, as three customers): the fixes below each failed before.
  // Tau's harness marks a focused element (focused); Meridian's moves document.activeElement.
  const focusedOn = (f, el) => !!el && (el.focused === true || f.document.activeElement === el);
  const patched = (f) => {
    const proto = Object.getPrototypeOf(f.root);
    if (!('scrollIntoView' in proto)) proto.scrollIntoView = function (o) { this.scrolledTo = o; };
    return f;
  };
  const many = (n, top = 100) => Array.from({length: n}, (_, i) => post(top - i, {username: i % 2 ? 'ann' : 'bob', created_at: new Date(Date.UTC(2026, 9, 1, 0, 0) - i * 3600e3).toISOString()}));

  test(`${name}: Show older posts reads the feed again with a page more, with no repeat or gap, and focus goes to the first older post`, async () => {
    // There was no way past the newest 30 posts but a bell link.
    const all = many(45), reads = [];
    const f = patched(frontend({fetchImpl: (path, options) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path.startsWith('/api/community') && !(options && options.method)) {
        reads.push(path);
        const q = new URLSearchParams(path.split('?')[1] || '');
        return response({posts: all.slice(0, Math.min(+(q.get('limit') || 30), 300))});
      }
      return response({});
    }}));
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const ids = () => f.root.querySelectorAll('#feed .post').map((a) => +a.dataset.id);
    const older = f.root.querySelector('[data-older]');
    assert.equal(ids().length, 30);
    assert.equal(older.hidden, false, 'a full page offers older posts');
    assert.match(older.textContent, /Show older posts/);
    await older.onclick(); await settle();
    assert.equal(reads.at(-1), '/api/community?limit=60', 'one read of the newest 60, so a refresh skips or repeats none');
    assert.deepEqual(ids(), all.map((p) => p.id));
    assert.equal(older.hidden, true, 'a short read is the whole feed');
    assert.ok(focusedOn(f, f.root.querySelector('.post[data-id="70"]')), 'focus is on the first post it added');
    // The refresh keeps them: it reads the same 60, not the newest 30 again.
    reads.length = 0;
    f.root.querySelector('.feed-filter .chip[data-feed="mine"]').onclick(); await settle();
    assert.equal(reads.at(-1), '/api/community?mine=1', 'a filter starts again from one page');
    f.clearTimers();
  });

  test(`${name}: a sent reply puts focus back in its thread's reply box, and a new post takes focus where it landed`, async () => {
    let count = 1, posts = [post(11, {comments: count})];
    const replies = [{body: 'First', author: 'Ana', username: 'ana', created_at: '2026-10-17T10:00:00Z'}];
    const f = patched(frontend({fetchImpl: (path, options) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community/11/comments' && options && options.method === 'POST') { replies.push({body: 'Hi', author: 'Dev', username: 'dev', created_at: '2026-10-17T10:05:00Z'}); count += 1; posts = [post(11, {comments: count})]; return response({ok: true}); }
      if (path === '/api/community/11/comments') return response({comments: replies.slice()});
      if (path === '/api/community' && options && options.method === 'POST') { posts = [post(12, {mine: true, body: JSON.parse(options.body).body}), ...posts]; return response({id: 12}); }
      if (path.startsWith('/api/community')) return response({posts});
      return response({});
    }}));
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const feed = f.root.querySelector('#feed');
    feed.listeners.get('click')({target: feed.querySelector('.post[data-id="11"] [data-act="comments"]')}); await settle();
    const form = feed.querySelector('.post[data-id="11"] .cmt-form');
    form.querySelector('input').value = 'Hi';
    await form.onsubmit({preventDefault() {}, currentTarget: form}); await settle();
    const box = feed.querySelector('.post[data-id="11"] .cmt-form input');
    assert.ok(box && box !== form.querySelector('input'), 'the thread opened again with a new reply box');
    assert.ok(focusedOn(f, box), 'focus is in the reply box, not fallen to the page top');
    // An empty open thread doesn't hold the feed back: the new post shows, and has focus.
    f.root.querySelector('#post-body').value = 'gm';
    await f.root.querySelector('#composer-post').onsubmit({preventDefault() {}}); await settle();
    const mine = feed.querySelector('.post[data-id="12"]');
    assert.ok(mine, 'the new post is in the feed');
    assert.ok(focusedOn(f, mine), 'focus is on the new post');
    assert.equal(mine.getAttribute('tabindex'), '-1');
    f.clearTimers();
  });

  test(`${name}: a post's and a reply's time say the date, clock and zone past a day, with the full stamp on hover`, async () => {
    // A header said a bare "Oct 17" with no clock, zone or stamp; the bell line linking to it says "Oct 17, 10:00 EDT".
    const iso = '2026-10-17T10:00:00Z';
    const f = patched(frontend({fetchImpl: (path) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path === '/api/community/11/comments') return response({comments: [{body: 'x', author: 'Ana', username: 'ana', created_at: iso}]});
      if (path.startsWith('/api/community')) return response({posts: [post(11, {created_at: iso})]});
      return response({});
    }}));
    f.location.pathname = '/community';
    await f.viewCommunity(); await settle();
    const stamp = new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'}).format(new Date(iso));
    const feed = f.root.querySelector('#feed');
    const head = feed.querySelector('.post[data-id="11"] .post-head time');
    assert.ok(head, 'the header time is a <time>');
    assert.equal(head.getAttribute('datetime'), iso);
    assert.equal(head.getAttribute('title'), stamp);
    assert.equal(head.textContent, stamp);
    feed.listeners.get('click')({target: feed.querySelector('[data-act="comments"]')}); await settle();
    const reply = feed.querySelector('.cmt .when time');
    assert.ok(reply && reply.textContent === stamp, 'a reply says it the same way');
    f.clearTimers();
  });

  test(`${name}: the author's card for a strategy they deleted since is no link and says so; a notice for a removed post takes focus to what says it`, async () => {
    const f = patched(frontend({fetchImpl: (path) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path.startsWith('/api/community')) return response({posts: [post(12)]});
      return response({});
    }}));
    const card = {kind: 'strategy', title: 'Gone', market: 'btc15m', status: 'passed', pnl: 5.5, trades: 48, win_rate: 0.58, days: 9};
    const html = f.postSnapshot({...card, gone: true}, '');
    assert.doesNotMatch(html, /<a |href=/, 'its page said "Not found"');
    assert.match(html, /You’ve deleted this strategy since, so it no longer opens\./);
    assert.match(html, /\+\$5\.50/, 'the figures stand as shared');
    assert.match(f.postSnapshot({...card, id: 42}, ''), /href="\/strategies\/42"/, 'one still there links its page');
    f.location.pathname = '/community'; f.location.hash = '#post-77';
    await f.viewCommunity(); await settle();
    const note = f.root.querySelector('#feed-note .feed-from');
    assert.match(note.textContent, /That post isn’t here any more/);
    assert.ok(focusedOn(f, note), 'focus is on the line saying the post is gone');
    f.clearTimers();
  });
}
