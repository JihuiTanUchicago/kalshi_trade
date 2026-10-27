/* Tau's Community page: the shared feed of posts.
   Fetched on first use (pageLoad in app.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns. */
window.TauPage('community', (T) => {
  'use strict';
  const {
    alert0, api, armed, attachMention, authorLine, BEHIND, boardTitle, busy, clock, esc, flash, ICON, liveWaitMark, loading,
    marketShort, mdLite, notice, overDays, pct, poll, realTrades, refreshed, researchBadge, root, S, SEP, shell,
    statusMark, tone, trDay, usd, when
  } = T;

  // ---------- community ----------
  // A shared figure says what it is: which book (a backtest, paper, demo or live), over what span and on
  // how many trades, each book on its own line. `owner` names the author when the post isn't the viewer's:
  // a strategy page is its owner's alone, so the card says how to get a copy instead of a dead link.
  const snapPnl = (v, n) => (n === 0 ? 'no trades yet' : `<b class="${tone(v)}">${usd(v, true)}</b>${n != null ? ` on ${realTrades(n)}` : ''}`);
  function postSnapshot(snap, owner) {
    if (!snap) return '';
    if (snap.kind === 'pnl') {
      return `<div class="snap"><div class="snap-meta">Realized P&amp;L, all time, as of this post</div><div class="snap-row"><span>Paper</span><span>${snapPnl(snap.paper_pnl, snap.paper_trades)}</span></div>
        <div class="snap-row"><span>Live (real money)</span><span>${snapPnl(snap.live_pnl, snap.live_trades)}</span></div></div>`;
    }
    if (snap.kind === 'strategy') {
      // A backtest-only strategy, or a pass the server found no gatekeeper record for (no_gatekeeper_record), has a
      // later-period figure: the slice after the split date that picked it, not held out, as its page and list say.
      const later = snap.status === 'backtest-only' || snap.no_gatekeeper_record;
      const head = `<div class="snap-head"><b>${esc(snap.title)}</b>${statusMark(snap)}${researchBadge(snap)}</div>
        <div class="snap-meta">${esc(marketShort(snap.market))}${SEP}${later ? `later-period backtest${overDays(snap.days)} after the split date, not held out` : `backtest on unseen data${overDays(snap.days)}`}: ${snap.pnl == null ? '—' : usd(snap.pnl, true)}${snap.trades != null ? SEP + realTrades(snap.trades) : ''}${snap.win_rate != null ? SEP + pct(snap.win_rate, false) + ' win' : ''}</div>`;
      return owner ? `<div class="snap">${head}<div class="snap-note">Only ${esc(owner)} can open this strategy. Ask them to share a copy from its page.</div></div>`
        : `<a class="snap" href="/strategies/${snap.id}">${head}</a>`;
    }
    if (snap.kind === 'deployment') {
      const book = snap.mode === 'live' ? 'live' : snap.mode === 'demo' ? 'demo' : 'paper';
      return `<div class="snap"><div class="snap-head"><b>${esc(snap.title)}</b>${book === 'live' ? '<span class="mk live">Live</span>' + liveWaitMark() : book === 'demo' ? '<span class="mk dep">Demo</span>' : '<span class="mk">Paper</span>'}</div>
        <div class="snap-meta">${esc(marketShort(snap.market))}${SEP}${book}${SEP}realized ${usd(snap.realized_pnl, true)}${snap.closed_trades != null ? SEP + realTrades(snap.closed_trades) : ''}${snap.since ? ' since ' + trDay(Date.parse(snap.since) / 1000) : ''}</div></div>`;
    }
    return '';
  }
  // Who a post's strategy card belongs to, when it isn't the viewer's own.
  const snapOwner = (p) => (p.mine ? '' : p.username ? '@' + p.username : p.author || 'its author');
  function avatar(pic, name) {
    const initial = esc((name || '?').trim()[0].toUpperCase());
    return pic ? `<img class="pfp" src="${esc(pic)}" alt="" referrerpolicy="no-referrer">` : `<span class="pfp ph" aria-hidden="true">${initial}</span>`;
  }
  // Reactor tooltip: names (+ @handles) are preloaded in the feed payload (reactions_for),
  // so "who reacted" is a pure CSS :hover popover — instant, with zero per-hover fetch.
  function rxWho(rx) {
    const names = rx.names || [];
    if (!names.length) return '';
    const extra = (rx.count || 0) - names.length;
    const list = names.map(esc).join(', ');
    return extra > 0 ? `${list} and ${extra} other${extra > 1 ? 's' : ''}` : list;
  }
  function rxChip(rx) {
    const who = rxWho(rx);
    return `<button class="rx ${rx.mine ? 'on' : ''}" data-emoji="${esc(rx.emoji)}" aria-label="${esc(rx.emoji)}, ${rx.count}${who ? ' — ' + who : ''}">${emojiHtml(rx.emoji)}<span class="n">${rx.count}</span>${who ? `<span class="rxtip" role="tooltip">${who}</span>` : ''}</button>`;
  }
  // Pills for the reactions a post has, plus an always-present inline "+" to add one.
  function reactionChips(list) {
    const chips = (list || []).map(rxChip).join('');
    return chips + `<button class="rx add" data-react-add aria-label="Add a reaction">${ICON.react}<i class="plus">+</i></button>`;
  }
  const GROUP_WINDOW = 5 * 60 * 1000;  // consecutive posts by one author within 5 min collapse the header
  // A Slack-style message row: avatar gutter + name/@handle/time header, body, attachments,
  // reaction pills, and a bottom-left action row (reply / replies count, plus edit on own posts).
  // A grouped post is a tight continuation of the author above it: no header, a hover-only time.
  function postCard(p, grouped) {
    const replies = p.comments || 0;
    return `<article class="post${grouped ? ' grouped' : ''}" data-id="${p.id}">
      <div class="post-gutter">${grouped ? `<time class="gutter-time">${clock(p.created_at)}</time>` : avatar(p.picture, p.author)}</div>
      <div class="post-col">
        ${grouped ? '' : `<div class="post-head"><b>${authorLine(p.author, p.username)}</b><span class="when">${when(p.created_at)}${p.edited ? `${SEP}edited` : ''}</span></div>`}
        <div class="post-main"><div class="post-body">${mdLite(p.body)}</div>
        ${p.image ? `<a class="post-img" href="${esc(p.image)}" target="_blank" rel="noopener"><img src="${esc(p.image)}" alt="" loading="lazy"></a>` : ''}
        ${postSnapshot(p.snapshot, snapOwner(p))}</div>
        <div class="reactions">${reactionChips(p.reactions)}</div>
        <div class="post-actions">
          <button class="thread-link" data-act="comments">${ICON.comment}<span>${replies ? `${replies} ${replies === 1 ? 'reply' : 'replies'}` : 'Reply'}</span></button>
          ${p.mine ? `<button class="thread-link" data-act="edit">${ICON.pencil}<span>Edit</span></button><button class="thread-link" data-act="delete"><span>Delete</span></button>` : ''}
        </div>
        <div class="comments" hidden></div>
      </div>
    </article>`;
  }
  // Emoji reactions — a fixed palette (matches the server whitelist). 'tau' is a
  // custom reaction: the Tau mark, animated (a shaking "T" = excitement).
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
  async function viewCommunity() {
    shell('/community', boardTitle('Community', 'Share a strategy, an idea, or how your money is doing. Like and reply to other traders.'), `
      <div class="feedwrap">
        <div class="chips feed-filter" role="group" aria-label="Filter posts"><button class="chip" type="button" data-feed="all" aria-pressed="true">All posts</button><button class="chip" type="button" data-feed="mine" aria-pressed="false">My posts</button></div>
        <div id="feed-note"></div>
        <div id="feed">${loading(120)}${loading(120)}</div>
        <form class="panel composer-post" id="composer-post">
          <textarea class="input" id="post-body" maxlength="2000" rows="1" aria-label="Write a post" aria-describedby="post-hint" placeholder="Share an idea or how it’s going…"></textarea>
          <div id="photo-preview" hidden><img id="photo-img" alt="Attached photo preview"><button type="button" class="photo-x" id="photo-remove" aria-label="Remove photo">${ICON.cross}</button></div>
          <div class="post-tools">
            <button class="btn sm" type="button" id="photo-btn">${ICON.image}Photo</button>
            <input type="file" id="photo-input" accept="image/png,image/jpeg,image/webp,image/gif" class="vh" tabindex="-1" aria-label="Choose a photo to attach">
            <label class="field post-strat-f"><span class="vh">Attach a strategy</span>
              <select id="post-strat"><option value="">Attach a strategy… (optional)</option></select></label>
            <button class="btn sm" type="button" data-share="pnl">${ICON.up}Share my P&amp;L</button>
            <button class="btn primary sm" type="submit">Post</button>
          </div>
          <p class="hint post-hint" id="post-hint">Everyone signed in to Tau can read posts and replies. An attached strategy shows its name, market and backtest result, never its rules. Share my P&amp;L posts your paper and live (real money) totals.</p>
          <div id="post-flash"></div>
        </form>
      </div>`);
    // composer auto-grows with the draft (starts one line, caps at the CSS max-height)
    const ta = root.querySelector('#post-body');
    const growTa = () => { ta.style.height = 'auto'; ta.style.height = Math.min(180, ta.scrollHeight) + 'px'; };
    ta.addEventListener('input', growTa);
    attachMention(ta);  // @-mention autocomplete in the composer
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
    }).catch(() => {});
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
            await api('/api/community', { body, kind, ref_id, image: pendingImage || undefined });
            root.querySelector('#post-body').value = ''; root.querySelector('#post-strat').value = ''; growTa();
            pendingImage = null; photoInput.value = ''; root.querySelector('#photo-preview').hidden = true;
            if (!(await refreshed(load()))) flash('#post-flash', 'Posted.' + BEHIND, 'good');
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
              const w = art.querySelector('.post-head .when'); if (w && !/edited/.test(w.textContent)) w.textContent += `${SEP}edited`;
            } catch (err) { flash(ef.querySelector('.form-flash'), err.message, 'bad'); }
          });
        };
      } else {
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
          <div class="cmt-list">${d.comments.map((c) => `<div class="cmt">${avatar(c.picture, c.author)}<div><b>${authorLine(c.author, c.username)}</b> <span class="when">${when(c.created_at)}</span><p>${mdLite(c.body)}</p></div></div>`).join('')}</div>
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
          if (count) count.textContent = q ? `${matched} of ${items.length}` : '';
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
              // refresh reply counts + thread affordance (also re-collapses the thread)
              if (!(await refreshed(load(true)))) flash(box.querySelector('.form-flash'), 'Reply sent.' + BEHIND, 'good');
            } catch (err) { flash(box.querySelector('.form-flash'), err.message, 'bad'); }
          });
        };
      }
    });
    // from: the feed starts at a post older than the newest page, when a bell link opened that post.
    let lastFeed = '', mineOnly = false, from = 0;
    const bodies = new Map();  // post id -> body as written (the source the edit box starts from)
    const load = async (force) => {
      // Never wipe a reply the user is writing: skip the refresh while a reply box is open
      // or anything in the feed is focused (unless this is the first/explicit render).
      if (!force && (feed.querySelector('.cmt-form') || feed.contains(document.activeElement))) return;
      const d = await api('/api/community' + (mineOnly ? '?mine=1' : from ? `?before=${from}` : ''));
      d.posts.forEach((p) => bodies.set(String(p.id), p.body));
      const html = d.posts.length ? d.posts.map((p, i) => {
        const prev = d.posts[i - 1];  // the post just above (newer) — a run by one author groups under it
        const grouped = !!prev && !!p.username && prev.username === p.username
          && Math.abs(new Date(prev.created_at) - new Date(p.created_at)) < GROUP_WINDOW;
        return postCard(p, grouped);
      }).join('')
        : `<div class="empty"><h3>${mineOnly ? 'You haven’t posted yet' : 'No posts yet'}</h3><p>${mineOnly ? 'Share a strategy an agent found or how your book is doing — it’ll show up here.' : 'Be the first. Share a strategy an agent found, drop an idea worth researching, or post how your paper book is doing.'}</p></div>`;
      if (html === lastFeed) return;  // nothing changed — don't re-render (avoids flicker)
      lastFeed = html;
      feed.innerHTML = html;
    };
    root.querySelectorAll('.feed-filter .chip').forEach((c) => (c.onclick = () => {
      const want = c.dataset.feed === 'mine';
      if (want === mineOnly) return;
      mineOnly = want; from = 0; root.querySelector('#feed-note').innerHTML = '';
      root.querySelectorAll('.feed-filter .chip').forEach((x) => x.setAttribute('aria-pressed', String((x.dataset.feed === 'mine') === mineOnly)));
      lastFeed = ''; load(true);
    }));
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
            from = 0; note.innerHTML = ''; history.replaceState(null, '', '/community'); lastFeed = ''; load(true);
          };
        }
      }
      const art = find();
      if (!art) {
        root.querySelector('#feed-note').innerHTML = `<div class="feed-from">${notice('That post isn’t here any more. Its author may have removed it.', '', true)}</div>`;
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
