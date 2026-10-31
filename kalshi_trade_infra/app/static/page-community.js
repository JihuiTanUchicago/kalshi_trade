/* The Community page, the shared feed of posts, in both themes.
   Fetched on first use (pageLoad in app.js or app.meridian.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns.
   What one theme draws and the other doesn't goes by the bundle's theme (shared(): theme). */
window.TauPage('community', (T) => {
  'use strict';
  const {
    alert0, api, armed, attachMention, authorLine, BEHIND, bellTime, boardTitle, busy, deploymentMode, esc, flash, ICON, keepZone,
    liveWaitMark, loading, marketShort, mdLite, notice, num, overDays, pageLede, pct, poll, realTrades, refreshed, researchBadge, root, S, SEP,
    settleAt, shell, statusMark, theme, tone, trDay, usd
  } = T;
  // Each theme lays the page and its cards out its own way: Tau's cards print a figure in a line of words and its
  // composer sits under the feed; Meridian's set figures out as labelled terms, under a New post that opens.
  const tau = theme === 'tau';

  // ---------- community ----------
  // A shared figure says what it is: which book (a backtest, paper, demo or live), over what span and on
  // how many trades, each book on its own line. `owner` names the author when the post isn't the viewer's:
  // a strategy page is its owner's alone, so the card says how to get a copy instead of a dead link.
  const snapPnl = tau
    ? (v, n) => (n === 0 ? 'no trades yet' : `<b class="${tone(v)}">${usd(v, true)}</b>${n != null ? ` on ${realTrades(n)}` : ''}`)
    : (v, n) => n === 0 ? '<dd>No trades yet</dd>' : `<dd class="${tone(v)}">${usd(v, true)}${n != null ? `<span class="snap-n">on ${realTrades(n)}</span>` : ''}</dd>`;
  function postSnapshot(snap, owner) {
    if (!snap) return '';
    if (snap.kind === 'pnl') {
      if (tau) {
        return `<div class="snap"><div class="snap-meta">Realized P&amp;L, all time, as of this post</div><div class="snap-row"><span>Paper</span><span>${snapPnl(snap.paper_pnl, snap.paper_trades)}</span></div>
        <div class="snap-row"><span>Live (real money)</span><span>${snapPnl(snap.live_pnl, snap.live_trades)}</span></div></div>`;
      }
      return `<div class="snap snap-pnl"><div class="snap-head"><b>Realized P&amp;L</b><div class="snap-meta-line"><span class="snap-kind">All time, as of this post</span></div></div><dl class="snap-metrics"><div><dt>Paper</dt>${snapPnl(snap.paper_pnl, snap.paper_trades)}</div>
        <div><dt>Live (real money)</dt>${snapPnl(snap.live_pnl, snap.live_trades)}</div></dl></div>`;
    }
    if (snap.kind === 'strategy') {
      // A backtest-only strategy, or a pass the server found no gatekeeper record for (no_gatekeeper_record), has a
      // later-period figure: the slice after the split date that picked it, not held out, as its page and list say.
      const later = snap.status === 'backtest-only' || snap.no_gatekeeper_record;
      // Either kind's figure is "later-period P&L", as the Strategies list's sort names it, and the note under the
      // figures says which, in the family's words: "later period · unseen data" (held out) or "· not held out", as the
      // Deploy hover does. In Tau's figures' line, "…which picked it: not held out: +$12.40" ran two colons into the P&L;
      // a held-out card read "later-period backtest over 9 days on unseen data" in Tau and "Unseen-data P&L" in Meridian.
      // Each piece of the note's pair holds together, so a phone breaks only after the "·": it read "(later / period"
      // and "not / held out" at 360-390px (walked 2026-10-28).
      // A card with no later-period figure ("—") has no note on it, as a Strategies row with no figure has no line
      // under it: "(later period · unseen data)" beside a dash described a figure that wasn't there (walked 2026-10-28).
      // A Void card the server flags (no_gatekeeper_record on a failed one: the first version's simple backtest stored it
      // as failed, never judged on held-out data) says "not held out" too, without "which picked it": nothing picked it.
      // The note ends ", not paper or live trading.": Tau's said only "Backtest…", and a "+$42.17" beside a Passed stamp
      // in a feed of paper and live results could pass for money made (walked 2026-10-30).
      // The author's own card for a strategy they have deleted since (the server's `gone`) is no link: its page said
      // "Not found" (walked 2026-10-31). It says the strategy is gone; the figures stand as shared.
      const gone = snap.gone ? `You${'\u2019'}ve deleted this strategy since, so it no longer opens.` : '';
      const why = snap.pnl == null ? '' : later ? `Backtest${overDays(snap.days)} after the split date${snap.status === 'failed' ? '' : ', which picked it'} (later\u00a0period${SEP}not\u00a0held\u00a0out), not paper or live trading.`
        : `Backtest${overDays(snap.days)} after the split date (later\u00a0period${SEP}unseen\u00a0data), not paper or live trading.`;
      if (tau) {
        const head = `<div class="snap-head"><b>${esc(snap.title)}</b>${statusMark(snap)}${researchBadge(snap)}</div>
        <div class="snap-meta">${esc(marketShort(snap.market))}${SEP}later-period P&amp;L: ${snap.pnl == null ? '—' : usd(snap.pnl, true)}${snap.trades != null ? SEP + realTrades(snap.trades) : ''}${snap.win_rate != null ? SEP + pct(snap.win_rate, false) + ' win' : ''}</div>`;
        if (owner || gone) return `<div class="snap">${head}<div class="snap-note">${why ? why + ' ' : ''}${owner ? `Only ${esc(owner)} can open this strategy. Ask them to share a copy from its page.` : gone}</div></div>`;
        return `<a class="snap" href="/strategies/${snap.id}">${head}${why ? `<div class="snap-note">${why}</div>` : ''}</a>`;
      }
      // A Void, Rejected or missed-final idea's figure is muted in Meridian, as its row on Strategies is: a green
      // "+$42.17" under a Void stamp read as a result. Tau's card prints it untoned.
      const noPass = snap.status === 'failed' || snap.status === 'rejected' || snap.verdict === 'missed_final';
      const note = [why, owner ? `Only ${esc(owner)} can open this strategy; ask them to share a copy from its page.` : gone].filter(Boolean).join(' ');
      const body = `<div class="snap-head"><span class="snap-title"><b>${esc(snap.title)}</b>${statusMark(snap)}${researchBadge(snap)}</span><div class="snap-meta-line"><span class="snap-kind">Strategy</span><span class="snap-meta">${esc(marketShort(snap.market))}</span></div></div><dl class="snap-metrics snap-evidence-metrics"><div class="snap-result"><dt>Later-period P&amp;L</dt><dd class="${noPass ? 'pnl-nopass' : tone(snap.pnl)}">${snap.pnl == null ? '—' : usd(snap.pnl, true)}</dd></div>${snap.trades != null ? `<div class="snap-secondary"><dt>Trades</dt><dd>${num(snap.trades)}</dd></div>` : ''}${snap.win_rate != null ? `<div class="snap-secondary"><dt>Win rate</dt><dd>${pct(snap.win_rate, false)}</dd></div>` : ''}</dl>${note ? `<p class="snap-note">${note}</p>` : ''}`;
      return owner || gone ? `<div class="snap snap-strategy">${body}</div>` : `<a class="snap snap-strategy" href="/strategies/${snap.id}">${body}</a>`;
    }
    if (snap.kind === 'deployment') {
      if (tau) {
        const book = snap.mode === 'live' ? 'live' : snap.mode === 'demo' ? 'demo' : 'paper';
        return `<div class="snap"><div class="snap-head"><b>${esc(snap.title)}</b>${book === 'live' ? '<span class="mk live">Live</span>' + liveWaitMark() : book === 'demo' ? '<span class="mk dep">Demo</span>' : '<span class="mk">Paper</span>'}</div>
        <div class="snap-meta">${esc(marketShort(snap.market))}${SEP}${book}${SEP}realized ${usd(snap.realized_pnl, true)}${snap.closed_trades != null ? SEP + realTrades(snap.closed_trades) : ''}${snap.since ? ' since ' + trDay(Date.parse(snap.since) / 1000) : ''}</div></div>`;
      }
      return `<div class="snap snap-deployment"><div class="snap-head"><span class="snap-title"><b>${esc(snap.title)}</b>${deploymentMode(snap)}${snap.mode === 'live' ? liveWaitMark() : ''}</span><div class="snap-meta-line"><span class="snap-kind">Deployment</span><span class="snap-meta">${esc(marketShort(snap.market))}</span>${snap.since ? `<span class="snap-kind snap-since">since ${trDay(Date.parse(snap.since) / 1000)}</span>` : ''}</div></div><dl class="snap-metrics snap-evidence-metrics"><div class="snap-result"><dt>Realized P&amp;L</dt><dd class="${tone(snap.realized_pnl)}">${usd(snap.realized_pnl, true)}</dd></div><div class="snap-secondary"><dt>Closed trades</dt><dd>${num(snap.closed_trades)}</dd></div></dl></div>`;
    }
    return '';
  }
  // Who a post's strategy card belongs to, when it isn't the viewer's own.
  const snapOwner = (p) => (p.mine ? '' : p.username ? '@' + p.username : p.author || 'its author');
  // The placeholder's letter is the name's first character whole: [0] took half of an emoji's surrogate pair, so a
  // name starting "🦊" showed a broken-glyph box in every reader's feed (walk 2026-10-31). An emoji reads as itself.
  const firstChar = (s) => {
    const t = String(s || '').trim() || '?';
    if (typeof Intl !== 'undefined' && Intl.Segmenter) { for (const g of new Intl.Segmenter().segment(t)) return g.segment; }
    return Array.from(t)[0];
  };
  function avatar(pic, name) {
    const initial = esc(firstChar(name).toUpperCase());
    return pic ? `<img class="pfp" src="${esc(pic)}" alt="" referrerpolicy="no-referrer">` : `<span class="pfp ph" aria-hidden="true">${initial}</span>`;
  }
  // Reactor tooltip: names (+ @handles) are preloaded in the feed payload (reactions_for),
  // so "who reacted" is a pure CSS :hover popover — instant, with zero per-hover fetch.
  function rxWho(rx) {
    const names = rx.names || [];
    if (!names.length) return '';
    const extra = (rx.count || 0) - names.length;
    const list = names.map(esc).join(', ');
    return extra > 0 ? `${list} and ${num(extra)} other${extra > 1 ? 's' : ''}` : list;
  }
  // A pill toggles the reader's own reaction, and says whether it is on (aria-pressed): Tau's showed that only by its
  // colour, so a screen reader heard "🔥, 3" alike whether the reader had reacted or not.
  function rxChip(rx) {
    const who = rxWho(rx);
    return `<button class="rx ${rx.mine ? 'on' : ''}" data-emoji="${esc(rx.emoji)}" aria-pressed="${!!rx.mine}" aria-label="${esc(rx.emoji)}, ${num(rx.count)}${who ? ' — ' + who : ''}">${emojiHtml(rx.emoji)}<span class="n">${num(rx.count)}</span>${who ? `<span class="rxtip" role="tooltip">${who}</span>` : ''}</button>`;
  }
  // Pills for the reactions a post has, then a way to add one: Tau's inline "+", Meridian's React.
  function reactionChips(list) {
    const chips = (list || []).map(rxChip).join('');
    return chips + (tau ? `<button class="rx add" data-react-add aria-label="Add a reaction">${ICON.react}<i class="plus">+</i></button>`
      : '<button class="rx add" data-react-add title="Add a reaction">React</button>');
  }
  const GROUP_WINDOW = 5 * 60 * 1000;  // consecutive posts by one author within 5 min collapse the header
  // A Slack-style message row: avatar gutter + name/@handle/time header, body, attachments,
  // reaction pills, and a bottom-left action row (reply / replies count, plus edit on own posts).
  // A grouped post is a tight continuation of the author above it: no header, its time in the gutter (Tau's shows on
  // hover). Its time says its zone, and its date on another day than today (settleAt): it read a bare "07:49" in no
  // zone, under a header that says "Oct 29" (walked 2026-10-30). In Tau's 42px gutter it wraps, the time on its own
  // line; Meridian's keeps it on one line with its zone (keepZone).
  // A header's time reads as the bell's line that links to it (bellTime): "2h ago" within a day, then "Oct 28, 14:05 EDT",
  // with the full stamp on hover. It said a bare "Oct 28" in no zone and had no stamp at all (walked 2026-10-31).
  function postCard(p, grouped) {
    const replies = p.comments || 0;
    const gutter = grouped ? `<time class="gutter-time" datetime="${esc(p.created_at)}">${tau ? settleAt(p.created_at) : keepZone(settleAt(p.created_at))}</time>` : avatar(p.picture, p.author);
    const head = grouped ? '' : `<div class="post-head"><b>${authorLine(p.author, p.username)}</b><span class="when">${bellTime(p.created_at)}${p.edited ? `${SEP}edited` : ''}</span></div>`;
    const main = `<div class="post-main"><div class="post-body">${mdLite(p.body)}</div>
        ${p.image ? `<a class="post-img" href="${esc(p.image)}" target="_blank" rel="noopener"><img src="${esc(p.image)}" alt="" loading="lazy"></a>` : ''}
        ${postSnapshot(p.snapshot, snapOwner(p))}`;
    const actions = `<div class="post-actions">
          <button class="thread-link" data-act="comments">${tau ? ICON.comment : ''}<span>${replies ? `${num(replies)} ${replies === 1 ? 'reply' : 'replies'}` : 'Reply'}</span></button>
          ${p.mine ? `<button class="thread-link" data-act="edit">${ICON.pencil}<span>Edit</span></button><button class="thread-link" data-act="delete"><span>Delete</span></button>` : ''}
        </div>`;
    if (tau) {
      return `<article class="post${grouped ? ' grouped' : ''}" data-id="${p.id}">
      <div class="post-gutter">${gutter}</div>
      <div class="post-col">
        ${head}
        ${main}</div>
        <div class="reactions">${reactionChips(p.reactions)}</div>
        ${actions}
        <div class="comments" hidden></div>
      </div>
    </article>`;
    }
    return `<article class="post${grouped ? ' grouped' : ''}${p.picture ? ' post-photo' : ''}" data-id="${p.id}">
      <div class="post-gutter">${gutter}</div>
      ${head}
      <div class="post-col">
        ${main}
        <div class="post-footer"><div class="reactions">${reactionChips(p.reactions)}</div>
        ${actions}</div></div>
        <div class="comments" hidden></div>
      </div>
    </article>`;
  }
  // Emoji reactions — a fixed palette (matches the server whitelist). 'tau' is a
  // custom reaction: the Tau mark (Tau's stylesheet shakes it: excitement; Meridian's keeps it still).
  const REACTIONS = ['tau', '👍', '❤️', '🔥', '🚀', '😂', '🎉', '💯', '👀', '🤔', '😮', '😢', '🙌', '🧠', '📈', '📉', '💸', '✅', '❌', '🐂', '🐻', '🐐', '🦍', '🐳', '💎', '🤡', '💀', '🫡', '🌙'];
  const emojiHtml = (e) => e === 'tau' ? `<span class="tau-emoji">${ICON.mark}</span>` : esc(e);
  let emojiPop = null;
  function openEmojiPicker(anchor, onPick) {
    if (emojiPop) emojiPop.remove();
    const pop = document.createElement('div');
    pop.className = 'emoji-pop';
    pop.innerHTML = REACTIONS.map((e) => `<button type="button" class="ep" data-e="${esc(e)}" title="${e === 'tau' ? 'Tau' : ''}">${emojiHtml(e)}</button>`).join('');
    document.body.appendChild(pop); emojiPop = pop;
    const r = anchor.getBoundingClientRect(), gut = 10;
    pop.style.left = Math.min(Math.max(gut, r.left), innerWidth - pop.offsetWidth - gut) + 'px';
    pop.style.top = (r.top - pop.offsetHeight - 6 < gut ? r.bottom + 6 : r.top - pop.offsetHeight - 6) + 'px';
    const close = () => { if (emojiPop) { emojiPop.remove(); emojiPop = null; } document.removeEventListener('click', outside, true); document.removeEventListener('keydown', onEsc); };
    const outside = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); };
    const onEsc = (e) => { if (e.key === 'Escape') close(); };
    pop.addEventListener('click', (e) => { const b = e.target.closest('.ep'); if (b) { onPick(b.dataset.e); close(); } });
    setTimeout(() => { document.addEventListener('click', outside, true); document.addEventListener('keydown', onEsc); }, 0);
  }
  // What an empty feed says, the reader's own posts or everyone's, in each theme's words.
  const FEED_PAGE = 30, FEED_MAX = 300;  // the server's FEED_PAGE and MAX_FEED_POSTS (routes/community.py)
  const EMPTY_MINE = tau ? 'Share a strategy an agent found or how your book is doing — it’ll show up here.'
    : 'Share a strategy an agent found or how your book is doing. It shows up here.';
  const EMPTY_ALL = tau ? 'Be the first. Share a strategy an agent found, drop an idea worth researching, or post how your paper book is doing.'
    : 'Be the first. Share a strategy an agent found, an idea worth researching, or how your paper book is doing.';
  const POST_DRAFT = 'tau_post_draft';  // the composer's unsent post, this tab (app.js forgetDrafts names it too)
  async function viewCommunity() {
    const lede = 'Share a strategy, an idea, or how your money is doing. Like and reply to other traders.';
    const filter = '<div class="chips feed-filter" role="group" aria-label="Filter posts"><button class="chip" type="button" data-feed="all" aria-pressed="true">All posts</button><button class="chip" type="button" data-feed="mine" aria-pressed="false">My posts</button></div>';
    // Show older posts reads the feed again with more of it (FEED_PAGE more each time, up to FEED_MAX): there was no way
    // past the newest 30 but a bell link (walked 2026-10-31). One read, so a refresh repeats or skips no post between pages.
    const feedHtml = `<div id="feed-note"></div>
        <div id="feed">${loading(120)}${loading(120)}</div>
        <div class="feed-more"><button type="button" class="btn sm" data-older hidden>Show older posts</button><div id="older-flash"></div></div>`;
    const composer = `<form class="panel composer-post" id="composer-post"${tau ? '' : ' aria-label="New post"'}>
          <textarea class="input" id="post-body" maxlength="2000" rows="1" aria-label="Write a post" aria-describedby="post-hint" placeholder="${tau ? 'Share an idea or how it’s going…' : 'Write a post…'}"></textarea>
          <div id="photo-preview" hidden><img id="photo-img" alt="Attached photo preview"><button type="button" class="photo-x" id="photo-remove" aria-label="Remove photo">${ICON.cross}</button></div>
          <div class="post-tools">
            <button class="btn sm" type="button" id="photo-btn">${ICON.image}Photo</button>
            <input type="file" id="photo-input" accept="image/png,image/jpeg,image/webp,image/gif" class="vh" tabindex="-1" aria-label="Choose a photo to attach">
            ${tau ? '<label class="field post-strat-f">' : '<label class="field">'}<span class="vh">Attach a strategy</span>
              <select id="post-strat"><option value="">${tau ? 'Attach a strategy… (optional)' : 'Attach strategy'}</option></select></label>
            <button class="btn sm" type="button" data-share="pnl">${ICON.up}Share my P&amp;L</button>
            <button class="btn primary sm" type="submit">Post</button>
          </div>
          <p class="hint post-hint" id="post-hint">Everyone signed in to Tau can read posts and replies. An attached strategy shows its name, market and backtest result, never its rules. Share my P&amp;L posts your paper and live (real money) totals.</p>
          <div id="post-flash"></div>
        </form>`;
    // Tau: the title over the feed and its filter, the composer under the feed. Meridian: the title, filter and lede in
    // one heading, then New post (folded) above the feed.
    shell('/community', tau ? boardTitle('Community', lede) : '', tau ? `
      <div class="feedwrap">
        ${filter}
        ${feedHtml}
        ${composer}
      </div>` : `
      <div class="feedwrap"><div class="community-heading"><h1 class="page">Community</h1>
        ${filter}
        ${pageLede(lede)}
      </div>
        <details class="community-compose"><summary>New post ${ICON.chev}</summary>
        ${composer}
        </details>
        ${feedHtml}
      </div>`);
    // composer auto-grows with the draft (starts one line, caps at the CSS max-height)
    const ta = root.querySelector('#post-body');
    const growTa = () => { ta.style.height = 'auto'; ta.style.height = Math.min(180, ta.scrollHeight) + 'px'; };
    ta.addEventListener('input', growTa);
    attachMention(ta);  // @-mention autocomplete in the composer
    // A post typed before the session ran out is kept for this tab and put back when the same account comes back to
    // the feed: a 401 (a poll's, or Post's own) sends the reader to sign in, and the box came back empty (walk
    // 2026-10-31). It goes once it posts or the box is cleared; signing out forgets it (forgetDrafts).
    const uid = S.me && S.me.user ? S.me.user.id : null;
    try {
      const d = JSON.parse(sessionStorage.getItem(POST_DRAFT) || 'null');
      if (d && d.uid === uid && typeof d.text === 'string' && d.text.trim() && !ta.value) {
        ta.value = d.text.slice(0, 2000); growTa();
        const fold = ta.closest('details'); if (fold) fold.open = true;  // a folded New post opens to show it
      }
    } catch (e) { /* storage off or unreadable: no draft */ }
    const keepPost = () => {
      try { if (ta.value.trim()) sessionStorage.setItem(POST_DRAFT, JSON.stringify({ uid, text: ta.value })); else sessionStorage.removeItem(POST_DRAFT); }
      catch (e) { /* private mode or full: the box still works */ }
    };
    ta.addEventListener('input', keepPost);
    // photo attach
    let pendingImage = null;
    const photoInput = root.querySelector('#photo-input');
    root.querySelector('#photo-btn').onclick = () => photoInput.click();
    photoInput.onchange = () => {
      const f = photoInput.files[0]; if (!f) return;
      if (f.size > 3 * 1024 * 1024) { flash('#post-flash', 'Images must be under 3 MB.', 'bad'); photoInput.value = ''; return; }
      const r = new FileReader();
      r.onload = () => { pendingImage = r.result; root.querySelector('#photo-img').src = r.result; root.querySelector('#photo-preview').hidden = false; };
      r.readAsDataURL(f);
    };
    root.querySelector('#photo-remove').onclick = () => { pendingImage = null; photoInput.value = ''; root.querySelector('#photo-preview').hidden = true; };
    // populate strategy picker with the user's own strategies
    api('/api/strategies').then((d) => {
      const sel = root.querySelector('#post-strat');
      d.strategies.filter((s) => s.status !== 'rejected' || s.title).slice(0, 50).forEach((s) => {
        const o = document.createElement('option'); o.value = s.id; o.textContent = `${s.title} (${STATUS_WORD[s.verdict] || STATUS_WORD[s.status] || s.status})`; sel.appendChild(o);
      });
    }).catch(() => {
      // A list that didn't load says so in the picker: it read "Attach a strategy… (optional)" over no strategies
      // (walk 2026-10-28). The post itself still works.
      const first = root.querySelector('#post-strat option');
      if (first) first.textContent = 'Your strategies didn\u2019t load. Reload the page to attach one.';
    });
    const form = root.querySelector('#composer-post');
    // One post at a time: Post and Share my P&L both lock while either is sent (a second tap on Share
    // my P&L, which busy() didn't lock, posted it twice). A post that landed says so even when the feed
    // doesn't refresh after it, so it isn't posted again.
    const submit = async (kind, ref_id) => {
      const body = root.querySelector('#post-body').value.trim();
      const btn = form.querySelector('[type=submit]'), share = form.querySelector('[data-share="pnl"]');
      if (btn.disabled || share.disabled) return;
      const other = kind === 'pnl' ? btn : share;
      other.disabled = true;
      try {
        await busy(kind === 'pnl' ? share : btn, async () => {
          try {
            const r = await api('/api/community', { body, kind, ref_id, image: pendingImage || undefined });
            root.querySelector('#post-body').value = ''; root.querySelector('#post-strat').value = ''; growTa(); keepPost();
            pendingImage = null; photoInput.value = ''; root.querySelector('#photo-preview').hidden = true;
            // The feed reads again unless a reply is being written in it (an open thread with no words in it closes): the
            // refresh skipped every time a thread was open, so the post didn't show at all (walked 2026-10-31).
            const draft = Array.from(feed.querySelectorAll('.cmt-form input')).some((i) => i.value.trim());
            if (!(await refreshed(load(!draft)))) flash('#post-flash', 'Posted.' + BEHIND, 'good');
            else {
              // The new post takes focus where it landed: Tau's composer sits under a feed whose top it can't see, so a
              // post went up with only the box emptying to say so (walked 2026-10-31).
              const mine = r && feed.querySelector(`.post[data-id="${r.id}"]`);
              if (mine) { mine.setAttribute('tabindex', '-1'); mine.scrollIntoView({ block: 'nearest' }); mine.focus({ preventScroll: true }); }
              else flash('#post-flash', 'Posted.', 'good');
            }
          } catch (e) { flash('#post-flash', e.message, 'bad'); }
        });
      } finally { other.disabled = false; }
    };
    form.onsubmit = (e) => { e.preventDefault(); const ref = root.querySelector('#post-strat').value; submit(ref ? 'strategy' : 'note', ref || undefined); };
    // Share my P&L puts real-money figures in front of everyone: the first press asks, a second posts.
    const shareBtn = form.querySelector('[data-share="pnl"]'), shareHtml = shareBtn.innerHTML;
    shareBtn.onclick = () => armed(shareBtn, 'Confirm: post P&L', () => { shareBtn.innerHTML = shareHtml; return submit('pnl'); });
    const feed = root.querySelector('#feed');
    const renderReactions = (art, list) => { art.querySelector('.reactions').innerHTML = reactionChips(list); };
    // One reaction at a time per post: each send toggles, so a double tap took it straight back off.
    const react = async (pid, art, emoji) => {
      if (art.dataset.reacting) return;
      art.dataset.reacting = '1';
      try { const r = await api(`/api/community/${pid}/react`, { emoji }); renderReactions(art, r.reactions); }
      catch (err) { alert0(err.message); }
      finally { delete art.dataset.reacting; }
    };
    feed.addEventListener('click', async (e) => {
      const retry = e.target.closest('[data-replies-retry]');
      if (retry) { const art = retry.closest('.post'); art.querySelector('.comments').hidden = true; art.querySelector('[data-act="comments"]').click(); return; }
      const addBtn = e.target.closest('[data-react-add]');
      if (addBtn) { const art = addBtn.closest('.post'); openEmojiPicker(addBtn, (emoji) => react(art.dataset.id, art, emoji)); return; }
      const chip = e.target.closest('.rx[data-emoji]');
      if (chip) { const art = chip.closest('.post'); react(art.dataset.id, art, chip.dataset.emoji); return; }
      const act = e.target.closest('[data-act]'); if (!act) return;
      const art = act.closest('.post'); const pid = art.dataset.id;
      // Delete asks once, then takes the post down with its replies; the feed reads again without it.
      if (act.dataset.act === 'delete') {
        armed(act, 'Confirm delete', async () => {
          try { await api(`/api/community/${pid}/delete`, {}); art.remove(); bodies.delete(pid); lastFeed = ''; await refreshed(load(true)); }
          catch (err) { alert0(err.message); }
        });
        return;
      }
      if (act.dataset.act === 'edit') {
        const main = art.querySelector('.post-main'); const bodyEl = main.querySelector('.post-body');
        if (main.querySelector('.edit-form')) return;
        // Edit the text as written: the rendered body has lost its **bold**, `code` and [link](url) marks.
        const current = bodies.has(pid) ? bodies.get(pid) : bodyEl.textContent;
        const ef = document.createElement('form'); ef.className = 'edit-form';
        ef.innerHTML = `<textarea class="input" maxlength="2000">${esc(current)}</textarea><div class="edit-actions"><button class="btn sm" type="button" data-cancel>Cancel</button><button class="btn primary sm" type="submit">Save</button></div><div class="form-flash"></div>`;
        bodyEl.hidden = true; bodyEl.insertAdjacentElement('afterend', ef);
        const ta = ef.querySelector('textarea'); ta.focus(); ta.setSelectionRange(current.length, current.length);
        ef.querySelector('[data-cancel]').onclick = () => { ef.remove(); bodyEl.hidden = false; };
        ef.onsubmit = async (ev) => {
          ev.preventDefault(); const nb = ta.value.trim(); if (!nb) return;
          await busy(ef.querySelector('[type=submit]'), async () => {
            try {
              await api(`/api/community/${pid}/edit`, { body: nb });
              bodies.set(pid, nb); bodyEl.innerHTML = mdLite(nb); bodyEl.hidden = false; ef.remove();
              const w = art.querySelector('.post-head .when'); if (w && !/edited/.test(w.textContent)) w.insertAdjacentHTML('beforeend', `${SEP}edited`);
            } catch (err) { flash(ef.querySelector('.form-flash'), err.message, 'bad'); }
          });
        };
      } else openThread(art, pid);
    });
    // Opens (or closes) a post's thread, and resolves once it is drawn.
    async function openThread(art, pid) {
      const box = art.querySelector('.comments');
      if (!box.hidden) { box.hidden = true; return; }
      box.hidden = false; box.innerHTML = loading(40);
      // A failed read says so: an empty thread under "2 replies" would read as the replies being gone.
      let d;
      try { d = await api(`/api/community/${pid}/comments`); }
      catch (err) { box.innerHTML = `<div class="cmt-err">${notice('Replies didn’t load just now.', 'bad')}<button type="button" class="btn sm" data-replies-retry>Try again</button></div>`; return; }
      const many = d.comments.length > 6;      // search bar once a thread gets long
      const PAGE = 10;
      box.innerHTML = `${many ? '<div class="cmt-search"><input class="input" type="search" placeholder="Search replies…" aria-label="Search replies"><span class="cmt-count"></span></div>' : ''}
        ${d.comments.length > PAGE ? '<button type="button" class="btn sm cmt-more"></button>' : ''}
        <div class="cmt-list">${d.comments.map((c) => `<div class="cmt">${avatar(c.picture, c.author)}<div><b>${authorLine(c.author, c.username)}</b> <span class="when">${bellTime(c.created_at)}</span><p>${mdLite(c.body)}</p></div></div>`).join('')}</div>
        <form class="cmt-form"><input class="input" maxlength="1000" aria-label="Write a reply" placeholder="Write a reply…" required><button class="btn sm" type="submit">Reply</button></form><div class="form-flash"></div>`;
      // Show the latest 10 (newest stay by the reply box); "Load earlier" reveals older in 10s.
      // Search (when present) filters the whole loaded set. ponytail: client-side over the ≤100
      // fetched — add a server offset if a thread ever tops that cap.
      const cmtSearch = box.querySelector('.cmt-search input');
      const count = box.querySelector('.cmt-count');
      const moreBtn = box.querySelector('.cmt-more');
      const items = Array.from(box.querySelectorAll('.cmt-list .cmt'));
      let limit = PAGE;
      const applyView = () => {
        const q = cmtSearch ? cmtSearch.value.trim().toLowerCase() : '';
        let matched = 0;
        items.forEach((el, i) => {
          const hit = !q || el.textContent.toLowerCase().includes(q);
          el.hidden = !hit || (!q && i < items.length - limit);  // keep the newest `limit`
          if (hit) matched++;
        });
        if (count) count.textContent = q ? `${num(matched)} of ${num(items.length)}` : '';
        if (moreBtn) {
          const rest = items.length - limit;
          moreBtn.hidden = !!q || rest <= 0;
          moreBtn.textContent = `Load ${Math.min(PAGE, rest)} earlier`;
        }
      };
      if (cmtSearch) cmtSearch.oninput = applyView;
      if (moreBtn) moreBtn.onclick = () => { limit += PAGE; applyView(); };
      applyView();
      attachMention(box.querySelector('.cmt-form input'));  // @-mention in replies
      box.querySelector('.cmt-form').onsubmit = async (ev) => {
        ev.preventDefault();
        const frm = ev.currentTarget;  // scope to the form — the search box is also an <input> in this box
        const inp = frm.querySelector('input'); const body = inp.value.trim(); if (!body) return;
        await busy(frm.querySelector('button'), async () => {
          try { await api(`/api/community/${pid}/comments`, { body }); inp.value = '';
            // Refresh reply counts and the thread link. The repaint closes every thread, so this one opens again
            // with the new reply in it: walked 2026-10-30, a sent reply vanished with its thread, and only "3 replies"
            // turning "4 replies" said it had gone through.
            // Focus goes back to the reply box of the thread that opened again: the repaint took the old one away, and
            // focus fell to the page's top (walked 2026-10-31).
            if (!(await refreshed(load(true)))) flash(box.querySelector('.form-flash'), 'Reply sent.' + BEHIND, 'good');
            else {
              const again = feed.querySelector(`.post[data-id="${pid}"]`);
              if (again && (again.querySelector('.comments') || {}).hidden) await openThread(again, pid);
              const box2 = again && again.querySelector('.cmt-form input');
              if (box2) box2.focus();
            }
          } catch (err) { flash(box.querySelector('.form-flash'), err.message, 'bad'); }
        });
      };
    }
    // from: the feed starts at a post older than the newest page, when a bell link opened that post.
    let lastFeed = '', mineOnly = false, from = 0, upTo = FEED_PAGE;
    const bodies = new Map();  // post id -> body as written (the source the edit box starts from)
    const load = async (force) => {
      // Never wipe a reply the user is writing: skip the refresh while a reply box is open
      // or anything in the feed is focused (unless this is the first/explicit render).
      if (!force && (feed.querySelector('.cmt-form') || feed.contains(document.activeElement))) return;
      const q = [mineOnly ? 'mine=1' : from ? `before=${from}` : '', upTo > FEED_PAGE ? `limit=${upTo}` : ''].filter(Boolean).join('&');
      const d = await api('/api/community' + (q ? '?' + q : ''));
      d.posts.forEach((p) => bodies.set(String(p.id), p.body));
      // A full read may have more behind it; a short one is the whole feed.
      const more = root.querySelector('[data-older]');
      if (more) more.hidden = d.posts.length < upTo || upTo >= FEED_MAX;
      const html = d.posts.length ? d.posts.map((p, i) => {
        const prev = d.posts[i - 1];  // the post just above (newer) — a run by one author groups under it
        const grouped = !!prev && !!p.username && prev.username === p.username
          && Math.abs(new Date(prev.created_at) - new Date(p.created_at)) < GROUP_WINDOW;
        return postCard(p, grouped);
      }).join('')
        : `<div class="empty"><h3>${mineOnly ? 'You haven’t posted yet' : 'No posts yet'}</h3><p>${mineOnly ? EMPTY_MINE : EMPTY_ALL}</p></div>`;
      if (html === lastFeed) return;  // nothing changed — don't re-render (avoids flicker)
      lastFeed = html;
      feed.innerHTML = html;
    };
    root.querySelectorAll('.feed-filter .chip').forEach((c) => (c.onclick = () => {
      const want = c.dataset.feed === 'mine';
      if (want === mineOnly) return;
      mineOnly = want; from = 0; root.querySelector('#feed-note').innerHTML = ''; upTo = FEED_PAGE;
      root.querySelectorAll('.feed-filter .chip').forEach((x) => x.setAttribute('aria-pressed', String((x.dataset.feed === 'mine') === mineOnly)));
      lastFeed = ''; load(true);
    }));
    // Show older posts: the same read with a page more of it. Focus goes to the first post it added, so a keyboard
    // reader carries on from there.
    const older = root.querySelector('[data-older]');
    older.onclick = async () => {
      if (older.disabled) return;
      const shown = feed.querySelectorAll('.post'), last = shown.length ? +shown[shown.length - 1].dataset.id : Infinity;
      older.disabled = true; root.querySelector('#older-flash').innerHTML = '';
      upTo = Math.min(FEED_MAX, upTo + FEED_PAGE); lastFeed = '';
      try {
        if (!(await refreshed(load(true)))) { upTo -= FEED_PAGE; flash('#older-flash', 'Older posts didn\u2019t load just now. Try again in a moment.', 'bad'); return; }
        const first = Array.from(feed.querySelectorAll('.post')).find((a) => +a.dataset.id < last);
        if (first) { first.setAttribute('tabindex', '-1'); first.focus(); }
      } finally { older.disabled = false; }
    };
    await load(true);
    await openLinkedPost();
    poll(load, 20000);
    // A bell notice about a post opens /community#post-<id>: the feed scrolls to that post with its
    // replies open. One older than the newest page shows the feed from it, with a way back to the
    // latest; one that is gone says so, instead of a feed with no sign of what the notice meant.
    async function openLinkedPost() {
      const m = /^#post-(\d+)$/.exec(location.hash || '') || /^\?post=(\d+)$/.exec(location.search || ''), gen = S.gen;
      if (!m) return;
      const pid = m[1], find = () => feed.querySelector(`.post[data-id="${pid}"]`);
      if (!find()) {
        let older = null;
        try { older = await api(`/api/community?before=${+pid + 1}`); } catch (e) { return; }  // the feed above still stands
        if (gen !== S.gen) return;
        if (older.posts.length && String(older.posts[0].id) === pid) {
          from = +pid + 1; lastFeed = ''; await load(true);
          const note = root.querySelector('#feed-note');
          note.innerHTML = `<div class="feed-from">${notice('Showing posts from the one you opened.', '', true)}<button type="button" class="btn sm" data-latest>Latest posts</button></div>`;
          note.querySelector('[data-latest]').onclick = () => {
            from = 0; upTo = FEED_PAGE; note.innerHTML = ''; history.replaceState(null, '', '/community'); lastFeed = ''; load(true);
          };
        }
      }
      const art = find();
      if (!art) {
        // Focus goes to the line that says so, as it does to the post when there is one: it stayed on the page's top.
        const note = root.querySelector('#feed-note');
        note.innerHTML = `<div class="feed-from" tabindex="-1">${notice('That post isn’t here any more. Its author may have removed it.', '', true)}</div>`;
        note.querySelector('.feed-from').focus({ preventScroll: true });
        return;
      }
      art.classList.add('post-target'); art.setAttribute('tabindex', '-1');
      art.scrollIntoView({ block: 'start' }); art.focus({ preventScroll: true });
      // A reply or a mention is what the notice was about: open the thread it is in.
      if ((art.querySelector('.comments') || {}).hidden) art.querySelector('[data-act="comments"]').click();
    }
  }
  // The picker names a strategy as its row on Strategies stamps it: a pass a later check left uncleared
  // (`verdict`) read "(passed)" here and Missed final test there.
  const STATUS_WORD = { passed: 'passed', failed: 'void', rejected: 'rejected', missed_final: 'missed the final test', held_back: 'held back' };

  return {viewCommunity};
});
