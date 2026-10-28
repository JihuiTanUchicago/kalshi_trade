/* Tau client. Vanilla JS, no build step.
   Every string that came from a user, an agent or the market goes through esc(). */
(() => {
  'use strict';

  const root = document.getElementById('app');
  const S = { me: null, timers: [], gen: 0, perps: null };

  // ---------- brand mark ----------
  const TAU_MARK = '<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="15" fill="#15161A"/><path d="M18 24h28M32 24v22" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/><circle cx="32" cy="48" r="3.5" fill="#F05A28"/></svg>';

  // ---------- icons (one stroke, one weight) ----------
  const I = (d, extra = '') => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
  const ICON = {
    mark: TAU_MARK,
    dashboard: I('<rect x="3" y="4" width="18" height="7" rx="1"/><path d="M3 15h7v5H3zM14 15h7v5h-7z"/>'),
    research: I('<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 6 6M8 10.5h5M10.5 8v5"/>'),
    search: I('<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>'),
    strategies: I('<path d="M5 3h14v18l-2.3-1.6L14.3 21 12 19.4 9.7 21l-2.4-1.6L5 21z"/><path d="M9 8h6M9 12h6"/>'),
    deploy: I('<rect x="3" y="4" width="18" height="12" rx="1"/><path d="M8 20h8M12 16v4M7 12l3-3 2 2 4-4"/>'),
    funds: I('<path d="M3 7h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 7l12-3v3M16 13.5h2"/>'),
    up: I('<path d="M12 19V5M6 11l6-6 6 6"/>'),
    down: I('<path d="M12 5v14M6 13l6 6 6-6"/>'),
    check: I('<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16 9.8"/>'),
    cross: I('<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>'),
    warn: I('<path d="M12 3 2 21h20z"/><path d="M12 10v5M12 18v.01"/>'),
    send: I('<path d="M4 12 20 4l-6 16-3-7z"/>'),
    plus: I('<path d="M12 5v14M5 12h14"/>'),
    ext: I('<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'),
    cube: TAU_MARK,
    heart: I('<path d="M12 20s-7-4.35-9.5-8.5C.5 7.5 3 4.5 6.2 4.5c2 0 3.2 1.2 3.8 2.3.6-1.1 1.8-2.3 3.8-2.3 3.2 0 5.7 3 3.7 7C19 15.65 12 20 12 20z"/>'),
    comment: I('<path d="M21 12a8 8 0 0 1-11.5 7.2L3 21l1.8-6.5A8 8 0 1 1 21 12z"/>'),
    share: I('<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v13"/>'),
    community: I('<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0M17 11a3 3 0 1 0-2-5.2M16.5 20a6 6 0 0 0-1.6-4"/>'),
    spark2: I('<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>'),
    gate: I('<path d="M5 21V8l7-4 7 4v13M9 21v-6h6v6"/>'),
    paper2: I('<path d="M6 2h9l3 3v17H6z"/><path d="M15 2v3h3M9 12h6M9 16h6"/>'),
    key: I('<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8 2 2M16 7l2 2"/>'),
    mail: I('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>'),
    pencil: I('<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
    image: I('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5L5 21"/>'),
    card: I('<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>'),
    credits: I('<circle cx="12" cy="12" r="9"/><path d="M14.5 9.5a3 3 0 1 0 0 5M12 7v10"/>'),
    admin: I('<path d="M12 2 4 5v6c0 5 3.5 8 8 11 4.5-3 8-6 8-11V5z"/><path d="m9 12 2 2 4-4"/>'),
    info: I('<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.7v.3"/>'),
    react: I('<circle cx="12" cy="12" r="9"/><path d="M8.5 14.5a4 4 0 0 0 7 0"/><path d="M9 9.5v.01M15 9.5v.01"/>'),
    chev: I('<path d="m6 9 6 6 6-6"/>'),
    at: I('<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>'),
    google: '<svg viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>',
  };

  // ---------- glossary (info bubbles) ----------
  // Plain-language definitions for the jargon the agent produces. Keep each to a
  // sentence or two; "plain language first, numbers second".
  const GLOSSARY = {
    passed: ['Passed', 'Cleared every gate on data the agent never saw while searching. Only passed strategies can be deployed.'],
    void: ['Void', 'The strategy was good enough in-sample to be tested on unseen data — but it failed at least one gate there. A real candidate that didn’t hold up.'],
    rejected: ['Rejected', 'Cut during the in-sample search, before the unseen-data test ever ran. The agent didn’t spend an out-of-sample test on it.'],
    unseen: ['Later-period P&L (unseen data)', 'What the strategy made in the backtest after its split date, on a held-out slice of history the agent never looked at while searching, so the result can’t be curve-fit. This is the backtest figure that counts.'],
    laterperiod: ['Later-period P&L', 'What the strategy made in the backtest after its split date. That later stretch is what picked it, so unlike unseen data it wasn’t held out: a weaker test.'],
    insample: ['In-sample', 'The history the agent iterates on. Strong in-sample numbers are easy to overfit, so they only shortlist a strategy — they never pass it.'],
    gate: ['Gates', 'The pass/fail checks a strategy must clear on unseen data: it makes money, trades often enough to judge, and its wins outweigh losses after fees.'],
    pace: ['Backtest estimate', 'What these same closed trades would have made if each had earned the strategy’s backtest average per trade after its split date. For a strategy with a gatekeeper record, that data was held out: the agent never saw it. For one without (backtest only, or a pass from the old backtest gate), it is the later period that picked it, so not held out. Compare it with Realized: well below it means trading is falling short of the test.'],
    // A research verdict's figures, each named in plain words with its term of art after it (statGrid).
    pvalue: ['Chance it’s luck (p-value)', 'How likely a strategy with no edge after fees would have done this well on this data by chance. Lower is better.'],
    dsr: ['Edge after correcting for many tries (DSR)', 'The deflated Sharpe ratio: how likely the edge is real once every idea tried is counted, since trying many ideas makes one look good by luck. Closer to 1 is better.'],
    sharpe: ['Steadiness per trade (Sharpe)', 'The average return per trade after fees divided by how much trade returns swing. Higher means steadier gains.'],
    range90: ['Likely average per trade (90% range)', 'Where the true average return per trade after fees most likely sits, 9 times in 10. A range wholly above 0% is what a real edge shows.'],
    placebo: ['Same test on shuffled outcomes (placebo)', 'The same test run on outcomes redrawn at random, so they hold no signal: how often they did at least as well. Lower means the signal, not luck, did the work.'],
    drawdown: ['Worst drop (max drawdown)', 'The biggest fall in P&amp;L from a high point to a later low during the test.'],
    realized: ['Realized', 'Profit or loss on trades that have closed, sold or settled when the market resolved, after the fees they paid. A closed trade’s figure doesn’t change.'],
    unrealized: ['Unrealized', 'What the positions still open would gain or lose if sold now, at the price Kalshi’s order book offers, after what they cost including fees. An estimate: it moves with the market until they close.'],
    instantfill: ['Instant fill', 'An early kind of paper trade that filled the whole order at the quoted price, without checking how many contracts Kalshi’s order book offered there. Too easy to count as evidence, so the track record and the count toward live leave it out.'],
    paperfills: ['Paper fills', 'Paper trades against Kalshi’s live order book: it buys at the ask and sells at the bid, pays Kalshi’s trading fee on every fill, and fills only the contracts offered at that price. A contract held to the end settles at $1 or $0. It doesn’t model the price moving in the second or two before a real order lands. Where a page shows an estimate after typical live slippage, it takes 0.5¢ a contract off each time an order fills to allow for that.'],
  };
  // What every paper P&L figure includes, said beside it (services/customer_text.PAPER_NET; the bubble
  // above is its PAPER_FILLS). Paper already fills at the ask and bid and pays Kalshi's fee.
  const PAPER_NET = 'after Kalshi fees and the spread';
  // What it leaves out is the price moving before a real order lands. Beside the paper headline figures (the
  // dashboard's, the strategy page's "Since deploying" and its ladder, the track record's paper tab, the
  // Strategies list's paper card, Deploy's paper Realized, the autopilot's paper figures), the server's
  // slippage_estimate (trading_core/domain/slippage.py) says what they might have been after it: muted, an
  // estimate with its assumption, never in place of the P&L. Paper only: live and demo never carry one.
  // slipTip says the same words as a title, where a figure sits inside a line about another book.
  const slipText = (e) => (e && e.pnl != null && Number.isFinite(+e.pnl)
    ? `≈ ${usd(e.pnl, true)} after typical live slippage (estimate: ${+e.per_fill_cents}¢ a contract each time an order fills)` : '');
  const slipEst = (e) => (slipText(e) ? `<span class="slip-est">${slipText(e)}</span>` : '');
  const slipTip = (e) => (slipText(e) ? ` title="${esc(slipText(e))}"` : '');
  // One drawn marker; a single top-layer popover serves them all (no clipping in tables).
  const glo = (key) => `<button type="button" class="info" data-glo="${key}" aria-label="What does “${GLOSSARY[key][0]}” mean?">${ICON.info}</button>`;
  // Text, its glossary button, then a separator (SEP's "·" and space). Chrome breaks a line after an inline button
  // even before a no-break space, so "· since Oct 20" and "· 1 open" began lines, and before the button, which then
  // began one: the text's last word, the button and its "·" stay together (.nobr), and the line still ends on "·".
  const gloSep = (key, before = '') => {
    const i = before.lastIndexOf(' ') + 1;
    return `${before.slice(0, i)}<span class="nobr">${before.slice(i)}${glo(key)}\u00a0\u00b7</span> `;
  };
  // A label with its marker: the last word and the marker never break apart, so the marker can't wrap onto a line of its own.
  const gl = (label, key) => { const i = label.lastIndexOf(' '); return `${label.slice(0, i + 1)}<span class="nobr">${label.slice(i + 1)}${glo(key)}</span>`; };
  function setupGlossary() {
    const pop = document.createElement('div');
    pop.className = 'glossary-pop'; pop.setAttribute('role', 'tooltip'); pop.id = 'glossary-pop'; pop.hidden = true;
    document.body.appendChild(pop);
    let current = null;
    const place = (mark) => {
      const r = mark.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight, gut = 12;
      let left = Math.min(Math.max(gut, r.left + r.width / 2 - pw / 2), innerWidth - pw - gut);
      let top = r.top - ph - 8;
      pop.classList.toggle('below', top < gut);
      if (top < gut) top = r.bottom + 8;
      pop.style.left = left + 'px'; pop.style.top = top + 'px';
    };
    const show = (mark) => {
      const g = GLOSSARY[mark.dataset.glo]; if (!g) return;
      current = mark; pop.innerHTML = `<b>${esc(g[0])}</b><span>${g[1]}</span>`;
      pop.hidden = false; mark.setAttribute('aria-describedby', 'glossary-pop'); place(mark);
    };
    const hide = () => { if (!current) return; current.removeAttribute('aria-describedby'); current = null; pop.hidden = true; };
    document.addEventListener('pointerover', (e) => { const m = e.target.closest('.info'); if (m) show(m); });
    document.addEventListener('pointerout', (e) => { const m = e.target.closest('.info'); if (m && m === current && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('.info') === m)) hide(); });
    document.addEventListener('focusin', (e) => { const m = e.target.closest && e.target.closest('.info'); if (m) show(m); else if (current && !e.target.closest('.glossary-pop')) hide(); });
    document.addEventListener('click', (e) => { const m = e.target.closest('.info'); if (m) { e.preventDefault(); (current === m) ? hide() : show(m); } else hide(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });
    addEventListener('scroll', hide, true); addEventListener('resize', hide);
  }

  // ---------- formatting ----------
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  // The separator between pieces of one line: a no-break space, "·", then a plain space, so a line that wraps ends on
  // "·" and the next never starts with it (" ·\u00a0" glued it to what followed: "· 3 trades" began lines at 390px).
  // Joins (`.join(SEP)`) and template pieces (`${a}${SEP}${b}`) on every page use it; page files get it from shared().
  const SEP = '\u00a0\u00b7 ';
  // A server line made of pieces joined by a plain " · " (a position's entry and exit, services/trade_why.py),
  // escaped, with each of its separators as SEP: at 390px a line began "· Holds to settlement". The API keeps
  // its plain text, so CSV and other readers are unchanged.
  const sepLine = (s) => esc(s).split(' \u00b7 ').join(SEP);
  // Inline markdown on ALREADY-ESCAPED text (so there is never raw HTML in the output).
  // Each marker needs its closing partner to fire, so a half-typed `**foo` or `` `foo `` from a
  // mid-stream token stays literal until it closes — the property the streaming feed relies on.
  // Only http(s) links — never javascript:/data: — so there is no XSS surface.
  const mdInline = (t) => {
    t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    t = t.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
    t = t.replace(/(^|[^\w])_([^_\n]+)_(?![\w])/g, '$1<i>$2</i>');   // _italic_ (never snake_case)
    t = t.replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener nofollow">$1</a>');
    t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener nofollow">$2</a>');
    // @handle mentions (not inside an email: the class blocks a word char before @)
    t = t.replace(/(^|[^\w@])@([a-z0-9_]{2,32})/gi, '$1<span class="mention">@$2</span>');
    return t;
  };
  // One-line-ish markdown: inline subset + hard line breaks. Used for devlog detail and log lines.
  const mdLite = (s) => mdInline(esc(s)).replace(/\n/g, '<br>');

  // Block-level safe markdown for the streaming research feed (the agent's think-aloud prose):
  // paragraphs, numbered/bullet lists, headings (as a bold line), fenced code, plus every mdInline
  // mark. Hostile-input safe: text is escaped per line before any tag is built, so no model token
  // can inject HTML. Streaming-safe: an UNCLOSED ``` fence renders as a literal line (not an eaten
  // tail), and an unterminated inline marker stays literal — the dangling bit resolves on the next
  // flush once its closer streams in. (The thinking card already stops echoing at the first fence,
  // so the fenced path is for robustness / reuse, and never collides with specHtml's code figure.)
  const MD_ROW = /^\s*\|.*\|\s*$/, MD_RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
  const feedMd = (src) => {
    const lines = String(src == null ? '' : src).split('\n');
    const out = [];
    let para = [], list = null;
    const flushPara = () => { if (para.length) { out.push('<p>' + para.map((l) => mdInline(esc(l))).join('<br>') + '</p>'); para = []; } };
    const flushList = () => { if (list) { out.push('<' + list.tag + '>' + list.items.map((it) => '<li>' + it + '</li>').join('') + '</' + list.tag + '>'); list = null; } };
    const flush = () => { flushPara(); flushList(); };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/^\s*```/.test(line)) {
        let j = i + 1;
        while (j < lines.length && !/^\s*```\s*$/.test(lines[j])) j++;
        if (j < lines.length) {   // closed fence -> code block; otherwise fall through (literal)
          flush();
          out.push('<pre class="md-code"><code>' + esc(lines.slice(i + 1, j).join('\n')) + '</code></pre>');
          i = j; continue;
        }
      }
      if (/^\s*$/.test(line)) { flush(); continue; }
      // A table (a |row|, then its |---| rule) becomes a real table in a box that scrolls sideways on a
      // phone. Until the rule line streams in, the row stays a literal line.
      if (MD_ROW.test(line) && MD_RULE.test(lines[i + 1] || '')) {
        flush();
        const cells = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => mdInline(esc(c.trim())));
        const rows = [];
        let j = i + 2;
        while (j < lines.length && MD_ROW.test(lines[j])) rows.push(cells(lines[j++]));
        out.push('<div class="md-table"><table><thead><tr>' + cells(line).map((c) => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>'
          + rows.map((r) => '<tr>' + r.map((c) => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>');
        i = j - 1; continue;
      }
      const h = line.match(/^\s{0,3}#{1,6}\s+(.*)$/);
      if (h) { flush(); out.push('<p class="md-h"><b>' + mdInline(esc(h[1])) + '</b></p>'); continue; }
      const ol = line.match(/^\s*(\d{1,9})[.)]\s+(.*)$/);
      if (ol) { flushPara(); if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] }; } list.items.push(mdInline(esc(ol[2]))); continue; }
      const ul = line.match(/^\s*[-*]\s+(.*)$/);
      if (ul) { flushPara(); if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; } list.items.push(mdInline(esc(ul[1]))); continue; }
      flushList(); para.push(line);
    }
    flush();
    return out.join('');
  };
  // "Jihui Tan @tanjihui" — the handle muted next to the display name.
  const authorLine = (name, uname) => `${esc(name || 'Trader')}${uname ? ` <span class="uhandle">@${esc(uname)}</span>` : ''}`;
  // Slack-style @-autocomplete on a textarea/input: type @ + letters -> a candidate list,
  // click or Enter to insert @handle. A popover is positioned under the field (fixed).
  function attachMention(el) {
    if (!el || el._mention) return; el._mention = true;
    let box = null, items = [], active = -1, token = null;
    const close = () => { if (box) box.remove(); box = null; items = []; active = -1; token = null; };
    const tokenAtCaret = () => {
      const text = el.value.slice(0, el.selectionStart);
      const m = /@([a-z0-9_]*)$/i.exec(text);
      return m ? { q: m[1], start: el.selectionStart - m[1].length - 1, end: el.selectionStart } : null;
    };
    const render = () => {
      if (!box) { box = document.createElement('div'); box.className = 'mention-pop'; document.body.appendChild(box); }
      const r = el.getBoundingClientRect();
      box.style.cssText = `position:fixed;left:${Math.round(r.left)}px;top:${Math.round(r.bottom + 2)}px;width:${Math.round(Math.min(300, Math.max(180, r.width)))}px;z-index:50;`;
      box.innerHTML = items.map((u, i) => `<button type="button" class="mention-opt ${i === active ? 'on' : ''}" data-u="${esc(u.username)}"><b>@${esc(u.username)}</b>${u.name ? ` <span>${esc(u.name)}</span>` : ''}</button>`).join('');
      box.querySelectorAll('.mention-opt').forEach((b) => { b.onmousedown = (e) => { e.preventDefault(); pick(b.dataset.u); }; });
    };
    const pick = (uname) => {
      if (!token) return;
      const before = el.value.slice(0, token.start), after = el.value.slice(token.end);
      el.value = `${before}@${uname} ${after}`;
      const caret = before.length + uname.length + 2;
      el.setSelectionRange(caret, caret); el.focus();
      close(); el.dispatchEvent(new Event('input'));
    };
    el.addEventListener('input', async () => {
      token = tokenAtCaret();
      if (!token) return close();
      try { const d = await api('/api/users/mention?q=' + encodeURIComponent(token.q), undefined, { keep: true }); items = d.users || []; }
      catch (e) { return close(); }
      if (!items.length) return close();
      active = 0; render();
    });
    el.addEventListener('keydown', (e) => {
      if (!box || !items.length) return;
      if (e.key === 'ArrowDown') { active = (active + 1) % items.length; render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { active = (active - 1 + items.length) % items.length; render(); e.preventDefault(); }
      else if (e.key === 'Enter' && active >= 0) { pick(items[active].username); e.preventDefault(); }
      else if (e.key === 'Escape') close();
    });
    el.addEventListener('blur', () => setTimeout(close, 150));
  }
  // Hover tooltip for a reaction chip: who reacted, with "and N others" when the list is capped.
  const rxTitle = (rx) => {
    const names = rx.names || [];
    if (!names.length) return '';
    const extra = (rx.count || 0) - names.length;
    return extra > 0 ? `${names.join(', ')} and ${extra} other${extra > 1 ? 's' : ''}` : names.join(', ');
  };
  const fmt2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmt0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  // An amount to `places` decimals, rounded half up from the decimal the server sent, as Billing rounds
  // (Decimal, half up): 0.105 is 0.10499999… as a float, so toFixed(2) said $0.10 beside Billing's $0.11.
  const halfUp = (v, places = 2) => {
    const a = Math.abs(+v), s = String(a);
    if (!Number.isFinite(a)) return +v;
    const r = /e/i.test(s) ? Math.round(a * 10 ** places) : Math.round(Number(s + 'e' + places));
    return Math.sign(+v) * r / 10 ** places;
  };
  // "−" and "+" may end a line before "$" (both are prefix characters to a line breaker), so "−" ended a line
  // and "$13.56" began the next. A word joiner (WJ, U+2060: invisible, zero width) keeps the sign on its amount
  // wherever usd() is drawn. It is for the screen only: an attribute, the tab title and anything copied take
  // plain() text (copyPlain), and CSV downloads come from the server.
  const WJ = '\u2060';
  const plain = (s) => String(s == null ? '' : s).replace(/\u2060/g, '');
  const usd = (v, signed = false) => {
    if (v == null || Number.isNaN(+v)) return '—';
    const n = +v;
    const s = '$' + (Math.abs(n) >= 100000 ? fmt0.format(Math.abs(n)) : fmt2.format(Math.abs(halfUp(n))));
    if (n < 0) return '−' + WJ + s;
    return signed && n > 0 ? '+' + WJ + s : s;
  };
  const pct = (v, signed = true) => (v == null ? '—' : (v < 0 ? '−' : signed && v > 0 ? '+' : '') + Math.abs(v * 100).toFixed(1) + '%');
  // Kalshi quotes some markets in tenths of a cent: 0.1¢ read as 0¢ and a 99.9¢ bid as 100¢.
  const cents = (v) => (v == null ? '—' : Math.round(v * 1000) / 10 + '¢');
  const isPerpetual = (s) => s.kind === 'perpetual' || s.market === 'btc_perp' || s.key === 'btc_perp' || (s.spec && s.spec.market === 'btc_perp');
  const researchOnly = (s) => s.research_only === true || isPerpetual(s);
  const researchBadge = (s) => researchOnly(s) ? '<span class="mk quiet">Research only</span>' : '';
  // Whether live trading is open on this server (/api/me's live_trading_available: the server's live switch).
  // While it is closed the engine places no live orders: it pauses a running live deployment the next time it
  // checks the market ("Live trading is not enabled on this server yet."), the server refuses Resume on a live
  // one, and Tau can't sell what a live deployment holds, which stays open until its market settles.
  const liveOpen = () => !!(S.me && S.me.live_trading_available);
  // A connected key's cash with no live trading from Tau: it said "Your Kalshi cash \u2014 real money untouched",
  // and didn't say why (live trading closed) or by what. Display only: the live switch is the server's.
  const LIVE_IDLE = () => liveOpen() ? 'Your real money at Kalshi: Tau hasn\u2019t placed a live trade yet'
    : 'Your real money at Kalshi: live trading isn\u2019t open yet, so Tau places no trades there';
  const LIVE_CLOSED = 'Live trading isn’t open yet.';
  // A deployment marked running that places no orders, in plain words ({tag, state, why}), or null: a live one
  // while live trading is closed, or a Bitcoin perpetual one (research-only: the engine trades none in any
  // book). Its row, the board's counts and the dashboard say so, never "Running" or "on live money".
  const depIdle = (d) => {
    if (!d || d.status !== 'running') return null;
    if (isPerpetual(d)) return { tag: 'Not trading', state: 'Not trading: research only', why: 'Bitcoin perpetuals are research-only, so this places no orders.' };
    if (d.mode !== 'live' || liveOpen()) return null;
    const n = +d.open_positions || 0;
    const held = n ? `, and Tau can’t sell ${n === 1 ? 'its open position, which stays open until its market settles' : `its ${n} open positions, which stay open until their markets settle`}` : '';
    return { tag: 'Waiting', state: LIVE_WAITING, why: `${LIVE_NO_ORDERS}${held}. Tau pauses it the next time it checks the market.` };
  };
  const LIVE_WAITING = 'Waiting: live trading isn’t open yet', LIVE_NO_ORDERS = 'Live trading isn’t open yet, so this places no orders';
  // Live deployments counted running that place no orders, as Deploy's Money figure counts them.
  const liveIdleCount = (n) => `${n} live, placing no orders: live trading isn’t open yet`;
  // The autopilot panel's Running figure shares a row with another figure (two to a row on a phone), where
  // the count above wrapped to four lines: there it reads "1 live (waiting)", the reason in its hover and
  // screen-reader text (the panel's story says it in full on its own line).
  const liveIdleShort = (n) => {
    const why = `live trading isn’t open yet, so ${n === 1 ? 'it places' : 'they place'} no orders`;
    return `<span class="apf-live-wait" title="${why.charAt(0).toUpperCase() + why.slice(1)}.">${n} live (waiting)<span class="vh">: ${why}</span></span>`;
  };
  // A "Live" badge on a list or card while live trading is closed (a strategy's books, a shared deployment):
  // the badge waits beside it, in depIdle's words, and a line under it says why on a phone too ('' while open).
  const liveWaitMark = () => liveOpen() ? '' : ` <span class="mk quiet live-wait" title="${LIVE_CLOSED}">Waiting<span class="vh">: live trading isn’t open yet</span></span>`;
  const liveWaitLine = () => liveOpen() ? '' : `<div class="sub-fig live-wait-why">${LIVE_NO_ORDERS}.</div>`;
  // The live switch rides the board's and the dashboard's polled answers (live_trading_available, in their
  // version), so an open tab follows a flip without a reload or a read of /api/me.
  const followLive = (d) => { if (d && typeof d.live_trading_available === 'boolean' && S.me) S.me.live_trading_available = d.live_trading_available; return d; };
  // Resume the server refuses (a live deployment while live trading is closed, a Bitcoin perpetual one) is
  // offered disabled, saying why, as a demo copy waiting on its paper run is (the server's resume_block).
  const resumeBlock = (d) => d.resume_block || (isPerpetual(d) ? 'Bitcoin perpetuals are research-only and can’t be resumed for trading.'
    : d.mode === 'live' && !liveOpen() ? LIVE_CLOSED : null);
  // A strategy written as code (the server's kind "code") runs only in the research sandbox: the server
  // refuses to deploy it in any mode, so its page offers no deploy button and says what to do instead.
  const CODE_RESEARCH_ONLY = 'Strategies written as code run only in the research sandbox, even after passing every check: paper, demo and live trading run rule-based strategies only. To trade this idea, ask for a rule-based version in a new research session.';
  const perpsPrice = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6});
  const tradePrice = (v, perpetual) => perpetual ? (!['number', 'string'].includes(typeof v) || String(v).trim() === '' || !Number.isFinite(Number(v)) ? '—' : perpsPrice.format(Number(v))) : cents(v);
  const PERPS_SCENARIO = 'Research scenario: at most 1× capital, fixed 12 bps taker fees and 5 bps adverse slippage per fill, plus settled funding. These are uncalibrated cost assumptions; fills use the next bar’s open. No margin or liquidation model. Short losses can exceed capital.';
  const tone = (v) => (v > 0 ? 'gain' : v < 0 ? 'loss' : '');
  const when = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    const s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return dateFmt(d, MON_DAY);
  };
  // A bell item's time: relative within the day, then the day and clock ("Oct 24, 14:05"), not a bare
  // date; the full stamp with its zone rides on hover.
  const bellTime = (iso) => {
    const d = new Date(iso || NaN);
    if (!Number.isFinite(d.getTime())) return '';
    const shown = Date.now() - d.getTime() < 86400000 ? when(iso) : dateFmt(d, DAY_CLOCK);
    return `<time datetime="${esc(iso)}" title="${esc(dateFmt(d, LOG_STAMP))}">${esc(shown)}</time>`;
  };
  // Each date format is built once and reused: toLocaleString with options builds a new formatter on
  // every call, and a 600-event research log spent ~0.3s of a phone's first paint on its clocks (and
  // Billing's 300-line statement ~0.15s on its clock times and counts, the bell ~10ms on every page).
  // Same options, same words: toLocaleDateString/TimeString/String only add defaults when the options
  // name no date or time field, and each constant below names one.
  const fmts = new Map();
  const dateFmt = (d, o) => {
    if (!Number.isFinite(d.getTime())) return 'Invalid Date';  // what toLocaleString says; format() throws
    let f = fmts.get(o);  // keyed by the options object: pass a constant
    if (!f) { f = new Intl.DateTimeFormat(undefined, o); fmts.set(o, f); }
    return f.format(d);
  };
  const CLOCK = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
  const CLOCK_ZONE = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' };
  const MON_DAY = { month: 'short', day: 'numeric' };
  const DAY_CLOCK = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
  const WEEKDAY_DAY = { weekday: 'short', month: 'short', day: 'numeric' };
  const YEAR_DAY = { year: 'numeric', month: 'short', day: 'numeric' };
  const UTC_MONTH = { year: 'numeric', month: 'short', timeZone: 'UTC' };
  const LOG_STAMP = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' };
  const clock = (iso) => dateFmt(new Date(iso), CLOCK);
  // The reader's zone ("EDT"), for a line that says once which zone the bare clock times are in.
  const tzName = () => { try { return (new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName') || {}).value || ''; } catch (e) { return ''; } };
  // A run log line's time: the bare clock fits the rail; the date and zone ride on hover and to a
  // screen reader (a run-until-stopped session spans days, and "06:07" named neither).
  const logTime = (iso) => `<time datetime="${esc(iso || '')}" title="${esc(dateFmt(new Date(iso), LOG_STAMP))}">${clock(iso)}</time>`;
  // When an open contract settles: the time alone today, the date too on any other day, and always the
  // zone. A bare "21:17" read as today in no stated zone, and a daily close settling tomorrow looked due.
  const settleAt = (iso) => {
    const d = new Date(iso || NaN);
    if (!Number.isFinite(d.getTime())) return '—';
    const today = d.toDateString() === new Date().toDateString();
    return dateFmt(d, today ? CLOCK_ZONE : LOG_STAMP);
  };  // fits the 40px log rail; '10:31 AM' wrapped to 'AM'
  // A time with its zone on one line: the market page's "Closes Oct 28, 02:45" left "UTC" alone on the next.
  const keepZone = (t) => String(t).replace(/ (?=\S+$)/, '\u00a0');
  const fmtCount = new Intl.NumberFormat('en-US');  // what Number#toLocaleString('en-US') builds on every call
  const num = (n) => (n == null ? '—' : fmtCount.format(Number(n)));
  // Compact count for tight spaces (system-map node metrics): 1.1M, 352k, 940.
  const compact = (n) => (n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : num(n));
  // Text cut to at most n characters at a word's end, with an ellipsis: a cut never splits a word ("each
  // fift…"), and a cut that ends on a comma or dash drops it. One word longer than n is cut at n. Only a
  // plain space is a place to cut: a no-break space (keepZone, whole) keeps its words together.
  const clipWords = (s, n) => {
    const t = String(s == null ? '' : s).replace(/[ \t\r\n]+/g, ' ').trim();
    if (t.length <= n) return t;
    const head = t.slice(0, n + 1);  // one past: a space there means the nth character ends a word
    const cut = / /.test(head.slice(1)) ? head.replace(/ [^ ]*$/, '') : t.slice(0, n);
    return cut.replace(/[ ,;:.\u2013\u2014-]+$/, '') + '\u2026';
  };
  const age = (sec) => (sec == null ? 'never' : sec < 90 ? sec + 's' : sec < 5400 ? Math.round(sec / 60) + 'm' : sec < 172800 ? Math.round(sec / 3600) + 'h' : Math.round(sec / 86400) + 'd');
  // A market by the catalog's label. A key the catalog no longer lists (a retired market) reads "Unlisted market",
  // never the raw key, as the autopilot card says one (apMarketName).
  const marketLabel = (k) => { const m = S.me && (S.me.markets || []).find((x) => x.key === k); return m && m.label ? m.label : 'Unlisted market'; };
  // Short, consistent chip labels for every market; unknown keys fall back to the
  // server's full label, never the raw key (keeps the market chips uniform).
  const MKT_SHORT = {
    // Each coin says the contract and its close, not just the coin and an hour ("BTC 5pm" was every kind),
    // with no " · " inside: lists and chips join labels with it, and "BTC above $X · 5pm ET" read as two.
    btc15m: 'BTC 15-min up/down', btc15m_tick: 'BTC 15-min up/down, per second', btc_perp: 'BTC perpetual, no expiry',
    btc_daily: 'BTC above $X at 5pm ET', eth15m: 'ETH 15-min up/down', eth_daily: 'ETH above $X at 5pm ET',
    sol15m: 'SOL 15-min up/down', sol_daily: 'SOL above $X at 5pm ET', xrp15m: 'XRP 15-min up/down', xrp_daily: 'XRP above $X at 5pm ET',
    doge15m: 'DOGE 15-min up/down', near15m: 'NEAR 15-min up/down', zec15m: 'ZEC 15-min up/down', hype15m: 'HYPE 15-min up/down',
    nba_game: 'NBA winner', nfl_game: 'NFL winner', nhl_game: 'NHL winner',
    ncaaf_game: 'NCAAF winner', mlb_game: 'MLB winner', epl_game: 'EPL result',
    high_ny: 'NYC high temp',
    tao_sn64: 'SN64 Chutes', tao_sn19: 'SN19 Nineteen', tao_sn8: 'SN8 PTN',
    tao_sn4: 'SN4 Targon', tao_sn56: 'SN56 Gradients',
  };
  // Order the research picker groups by how often they're used; unknown categories fall to the end.
  const MKT_CATS = ['Crypto', 'Sports', 'Economics', 'Commodities', 'Science and Technology', 'Climate and Weather', 'Weather', 'Bittensor'];
  // Category sort shared by the research picker and the strategies market filter.
  const catOrder = (a, b) => { const ia = MKT_CATS.indexOf(a), ib = MKT_CATS.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b); };
  const marketShort = (k) => (!k ? 'Agent’s choice' : MKT_SHORT[k] || marketLabel(k));
  // A market named on its own, in a sentence or as a row's market ("Bitcoin up or down in 15 minutes"), by its full
  // label, as Billing's lines and every position name it; the short one stays for chips and meta lines joined by
  // " · ". The autopilot said "Researching BTC 15-min up/down" and Deploy's rows "BTC 15-min up/down" above
  // positions in "Bitcoin up or down in 15 minutes". A key the catalog doesn't list reads as marketShort does.
  const marketFull = (k) => { const m = k && ((S.me && S.me.markets) || []).find((x) => x.key === k); return m && m.label ? m.label : marketShort(k); };
  // The readable market a contract ticker belongs to, by its series prefix (KXBTCD-26OCT2617-T68499.99 is
  // "Bitcoin above $68,499.99 at 5pm ET"), so an open position never shows only the raw ticker. Unknown: ''.
  // A market kept to one close hour (close_hour_et: the 5pm close of the KXBTCD ladder) owns only the
  // contracts whose event closes then: KXBTCD-26OCT2700 is the midnight contract, which no strategy trades.
  const contractHour = (ticker) => { const m = /^[^-]+-\d{2}[A-Z]{3}\d{2}(\d{2})(?:-|$)/.exec(String(ticker || '')); return m ? +m[1] : null; };
  // An ET hour as a close says it: "noon", "midnight", "9am", "5pm".
  const hourET = (h) => (h === 12 ? 'noon' : h === 0 ? 'midnight' : `${h % 12}${h < 12 ? 'am' : 'pm'}`);
  const contractMkt = (ticker) => ((S.me && S.me.markets) || []).find((x) => x.series && String(ticker || '').startsWith(x.series + '-')
    && (x.close_hour_et == null || contractHour(ticker) === x.close_hour_et));
  // A ladder market's label says "$X" for the strike; one contract says its own (-T68499.99), as its rules do,
  // to its last decimal: an XRP strike runs to four (-T2.4599), and num() rounds past three.
  const strikeIn = (label, ticker) => { const k = /-T(\d+)(\.\d+)?$/.exec(String(ticker || '')); return k ? label.replace('$X', '$' + num(k[1]) + (k[2] || '')) : label; };
  // Bitcoin series the app shows (Explore, the hot rail, a market page, a position held at Kalshi) that no
  // market here covers: KXBTC's hourly price ranges. Each still says its contract and close as the markets above
  // do, [chip, name], never the raw series or another market's label. Every series of services/btc_spot.py's
  // BTC_SERIES is a market's or here (test_every_bitcoin_series_the_app_shows_has_a_label).
  const SERIES_SHORT = { KXBTC: ['BTC range at {h} ET', 'Bitcoin range at {h} ET'] };
  // Another hour of a ladder a market here keeps to one close (KXBTCD-26OCT2612, the noon "Bitcoin above $X"
  // contract, beside btc_daily's 5pm): never that market's label, which names the wrong close, but the same
  // words at its own hour read from the ticker, [chip, name] as SERIES_SHORT: "BTC above $X at noon ET".
  const offHour = (ticker, h) => {
    const sib = ((S.me && S.me.markets) || []).find((x) => x.series && x.close_hour_et != null && String(ticker || '').startsWith(x.series + '-'));
    if (!sib || h == null) return null;
    const at = ` at ${hourET(sib.close_hour_et)} ET`, to = ` at ${hourET(h)} ET`;
    const pair = [marketShort(sib.key), sib.label || marketShort(sib.key)];
    return pair.every((l) => l.includes(at)) ? pair.map((l) => l.replace(at, to)) : null;
  };
  const seriesLabel = (ticker, i) => {
    const h = contractHour(ticker), s = SERIES_SHORT[String(ticker || '').split('-')[0]];
    if (s && h != null) return s[i].replace('{h}', hourET(h));
    const o = offHour(ticker, h);
    return o ? o[i] : '';
  };
  // A range contract's own bucket (-B113250, its centre) or end (-T114999.99) in its name; another hour of a
  // ladder its own strike, as its market's label would ("Bitcoin above $68,499.99 at noon ET").
  const rangeName = (ticker) => {
    const name = seriesLabel(ticker, 1), k = /-([BT])(\d+)(\.\d+)?$/.exec(String(ticker || ''));
    if (!name.startsWith('Bitcoin range ')) return strikeIn(name, ticker);
    if (!k) return name;
    const at = '$' + num(k[2]) + (k[3] || ''), close = name.replace(/^Bitcoin range /, '');
    return k[1] === 'B' ? `Bitcoin in the bucket around ${at} ${close}` : `Bitcoin range end at ${at}, ${close.replace(/^at /, '')}`;
  };
  const contractMarket = (ticker) => { const m = contractMkt(ticker); return m ? strikeIn(m.label || marketShort(m.key), ticker) : rangeName(ticker); };
  // A position's contract as people name it: its market's plain label with its own strike ("Bitcoin above
  // $68,499.99 at 5pm ET"), else the market it was traded on (`key`, its deployment's), else "Kalshi contract".
  // The ticker (KXBTC15M-26OCT262100-00) carries the raw series key, so it is never the headline: kalshiRef
  // sets it on a small line, there to find the contract on Kalshi.
  const contractName = (ticker, key) => contractMarket(ticker) || (key ? strikeIn(marketFull(key), ticker) : 'Kalshi contract');
  // A contract, by its plain name, that opens its market page (price, settlement rules, your positions in it).
  const contractLink = (ticker, key) => `<a href="/explore?m=${encodeURIComponent(ticker)}">${esc(contractName(ticker, key))}</a>`;
  const kalshiRef = (ticker) => `<span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">${esc(ticker)}</span></span>`;
  // A contract (a hot-markets row's `t`) as the app names its market ("BTC 15-min"), or its SERIES_SHORT or
  // other-hour chip ("BTC range at 5pm ET", "BTC above $X at noon ET"); '' for any other, so a chip is left off
  // rather than the raw series or another hour's market.
  const contractShort = (ticker) => { const m = contractMkt(ticker); return m ? marketShort(m.key) : seriesLabel(ticker, 0); };
  // Link a strategy's market to its Kalshi series page.
  const marketKalshiUrl = (k) => { const m = (S.me && S.me.markets || []).find((x) => x.key === k); return m && m.series ? `https://kalshi.com/markets/${m.series.toLowerCase()}` : null; };
  const dirLabel = (k) => { if (!k) return 'Session'; const d = S.me && S.me.directions.find((x) => x.key === k); return d ? d.label : String(k).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()); };
  // The server's title for a session whose prompt is an instruction to the agent (the autopilot's research
  // floor), else the idea as typed.
  const sessionTitle = (r) => r.title ? r.title : (r.prompt && r.prompt.trim()) ? r.prompt.trim() : (dirLabel(r.direction) + SEP + marketShort(r.market));

  // The research market picker: ONE list in the live-row style (name \u00b7 sparkline \u00b7 mid \u00b7
  // 24h volume), grouped by category, with Agent's choice leading as the default. Every row is
  // a <label> wrapping one radio in a single group (name="market"), so the posted value is
  // byte-identical to the old flat picker, selection is fully native (click the row, or arrow
  // across the group), and ":checked" drives the selected skin. The live figures are folded in
  // afterwards from /api/research/context; a row with no backtest history yet (has_data=false)
  // is shown dimmed and flagged "History still building", never hidden, so the whole universe shows.
  function mktRow(m) {
    const pending = m.has_data === false;  // no collected history yet -> still backfilling
    const face = `<span class="mktrow-face">
        <span class="mktrow-name">${esc(marketShort(m.key))}${researchBadge(m)}</span>
        <span class="mktrow-spark" data-spark aria-hidden="true"></span>
        <span class="mktrow-last" data-last>${pending ? '' : '<b class="fig sm">\u2014</b>'}</span>
        <span class="mktrow-vol" data-vol>${pending ? 'History still building' : ''}</span>
      </span>`;
    return `<label class="mktrow${pending ? ' pending' : ''}" data-key="${esc(m.key)}"${pending ? ' title="History still building \u2014 research may find nothing yet."' : ''}>
      <input type="radio" name="market" value="${esc(m.key)}" class="mktrow-r">${face}</label>`;
  }
  function marketPicker(markets) {
    const groups = {};
    markets.forEach((m) => { (groups[m.category] || (groups[m.category] = [])).push(m); });
    const cats = Object.keys(groups).sort(catOrder);
    const find = markets.length > 8;
    const lead = `<div class="mkt-lead"><label class="mktrow lead" data-key=""><input type="radio" name="market" value="" class="mktrow-r" checked><span class="mktrow-face"><span class="mktrow-name">Agent\u2019s choice</span><small class="mktrow-sub">The agent picks the market that best fits your idea.</small></span></label></div>`;
    return `<div class="mktpick">
      ${find ? `<div class="mkt-find">${ICON.search}<label class="vh" for="mktfind">Filter markets</label><input class="input" type="search" id="mktfind" placeholder="Filter markets\u2026" autocomplete="off"></div>` : ''}
      ${lead}
      ${cats.map((c, i) => `<details class="mkt-group"${cats.length === 1 ? ' open' : ''}><summary class="mkt-group-h"><span class="mkt-chev" aria-hidden="true">${ICON.chev}</span>${esc(c)}<span class="mkt-count">${groups[c].length}</span></summary><div class="mkt-rows">${groups[c].map(mktRow).join('')}</div></details>`).join('')}
      <p class="mkt-none hint" hidden role="status">No market matches that filter.</p>
    </div>`;
  }
  // Fold one live-context row into its market's row: sparkline, mid + 24h change, 24h volume.
  function fillLiveRow(scope, m) {
    const face = scope.querySelector(`.mktrow[data-key="${m.key}"] .mktrow-face`);
    if (!face) return;
    const tr = m.trace || [], dC = tr.length >= 2 ? Math.round((tr[tr.length - 1] - tr[0]) * 100) : 0;
    const dir = dC > 0 ? 'pos' : dC < 0 ? 'neg' : '';
    face.querySelector('[data-spark]').innerHTML = hotChart(tr);
    face.querySelector('[data-last]').innerHTML = `<b class="fig sm">${m.mid == null ? '\u2014' : cents(m.mid)}</b>${dC ? `<span class="mktrow-delta ${dir}">${dC > 0 ? '+' : '\u2212'}${Math.abs(dC)}\u00a2</span>` : ''}`;
    face.querySelector('[data-vol]').textContent = `${kfmt(m.vol24)} vol${SEP}24h`;
    face.dataset.live = '1';
  }
  // Ready markets (has_data) with nothing in the live feed right now: say so plainly instead
  // of leaving the row blank. Pending (backfilling) rows keep their own label.
  function markQuietRows(scope) {
    scope.querySelectorAll('.mktrow:not(.lead):not(.pending) .mktrow-face:not([data-live]) [data-vol]')
      .forEach((v) => { if (!v.textContent) v.textContent = 'No live quote'; });
  }
  // Live filter for the picker; no-op when the list was short enough to render no search box.
  function wireMarketPicker(scope) {
    const find = scope.querySelector('#mktfind');
    if (!find) return;
    const groups = [...scope.querySelectorAll('.mkt-group')];
    const none = scope.querySelector('.mkt-none');
    find.addEventListener('input', () => {
      const q = find.value.trim().toLowerCase();
      let shown = 0;
      groups.forEach((g) => {
        const cat = (g.querySelector('.mkt-group-h').textContent || '').toLowerCase();
        let any = false;
        g.querySelectorAll('.mktrow').forEach((o) => {
          const hit = !q || cat.includes(q) || o.textContent.toLowerCase().includes(q);
          o.hidden = !hit; if (hit) { any = true; shown++; }
        });
        g.hidden = !any;
        g.open = !!q && any;  // expand matching groups while filtering; collapse again when cleared
      });
      if (none) none.hidden = shown > 0;
    });
  }

  // ---------- API ----------
  class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
  // A read started by a page the user has since left never settles, so the old page can't paint
  // over the new one (or arm its poll there). Widgets that outlive a page pass { keep: true }.
  const STALE = () => new Promise(() => {});
  const TRANSIENT = new Set([502, 503, 504]), RETRY_MS = [700, 1800];
  // How long a read waits before the page says it failed and offers Try again: the edge gives up on the
  // server at 30s too. Writes wait as long as it takes, since Tau may still be doing them.
  const READ_MS = 30000;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // What a failed request says when Tau sent no words of its own (the edge's HTML error page, a cut-off
  // reply, no network): plain words, never the page itself. A write that Tau may have taken anyway (no
  // reply, or the edge's 5xx) says so, so nobody deploys or sends twice by trying again blind.
  const failText = (status, write) => write && (!status || status >= 500)
    ? "Tau didn't confirm this, so it may or may not have gone through. Reload the page to check before you try again."
    : !status ? "Can't reach Tau. Check your connection."
    : status === 429 ? 'Tau is getting a lot of requests right now. Try again in a minute.'
    : status >= 500 ? `Tau is having trouble right now (${status}). Try again in a moment.`
    // A 4xx with no words of Tau's own (an edge page in front of it): what to do, not just the code.
    : `Tau couldn't do that (${status}). Reload the page and try again.`;
  // A failure the page shows as an error goes to the operator's readout on /admin (boot.js sends it).
  // An API call that broke: no reply (not our own timeout), the server's 5xx, or a reply that isn't
  // JSON. A 4xx is Tau answering, not a broken page. The path goes without its query, ids as :id.
  const reportBroken = (kind, err) => { try { if (typeof window.__tauReport === 'function') window.__tauReport(kind, err); } catch (e) { /* best-effort */ } };
  const apiBroke = (path, write, what) => reportBroken('api', `${write ? 'POST' : 'GET'} ${String(path).split('?')[0].replace(/\/\d+(?=\/|$)/g, '/:id')} ${what}`);
  async function api(path, body, cfg) {
    // A signed-in shell carries the page's first reads ([{url, body}], app/web/shell_reads.py; boot.js
    // parks them): the first render takes each in place of that one request, once, instead of waiting a
    // round trip for it.
    const carried = body === undefined ? window.__TAU_FIRST__ : null;
    if (carried) {
      if (S.gen > 1 || !Array.isArray(carried)) window.__TAU_FIRST__ = null;  // the first page has gone: never an old answer later
      else { const i = carried.findIndex((r) => r && r.url === path); if (i >= 0) return carried.splice(i, 1)[0].body; }
    }
    // A read the shell named to start early (boot.js: a carried read's "then"): the first page's ask takes it,
    // once, in place of its first fetch; a later page never gets an old answer.
    let early = null;
    if (body === undefined && window.__TAU_EARLY__) {
      if (S.gen > 1) window.__TAU_EARLY__ = null;
      else if (window.__TAU_EARLY__[path]) { early = window.__TAU_EARLY__[path]; delete window.__TAU_EARLY__[path]; }
    }
    const gen = S.gen, scoped = body === undefined && !(cfg && cfg.keep);
    const opts = { credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-Recursive'] = '1';
      opts.body = JSON.stringify(body);
    }
    // Optional timeout (used on the boot /api/me call so a slow/overloaded server can't hang the
    // whole app on a blank screen). AbortController fires an abort the fetch rejects on. A read with
    // none of its own gets READ_MS: one the network swallowed left its page's skeleton up for good.
    let ctl, tid;
    const limit = (cfg && cfg.timeoutMs) || (body === undefined ? READ_MS : 0);
    if (limit) { ctl = new AbortController(); opts.signal = ctl.signal; tid = setTimeout(() => ctl.abort(), limit); }
    let res;
    // A GET that hits a restart (a deploy takes the server away for a second, and CloudFront
    // answers 502/503/504 with its own non-JSON page) retries twice before the page shows an
    // error. A JSON error is Tau itself answering, so it is final. Writes never retry.
    for (let attempt = 0; ; attempt++) {
      try {
        res = await (early && attempt === 0
          ? Promise.race([early, new Promise((_, no) => { if (ctl) ctl.signal.addEventListener('abort', () => no(new Error('timed out'))); })])
          : fetch(path, opts));
      }
      catch (e) {
        if (scoped && gen !== S.gen) { if (tid) clearTimeout(tid); return STALE(); }
        if (body === undefined && attempt < 2 && !(ctl && ctl.signal.aborted)) { await sleep(RETRY_MS[attempt]); continue; }
        if (tid) clearTimeout(tid);
        if (!(ctl && ctl.signal.aborted)) apiBroke(path, body !== undefined, 'got no reply');
        throw new ApiError(0, body !== undefined ? failText(0, true) : ctl && ctl.signal.aborted ? "Tau is taking too long to respond." : failText(0));
      }
      if (body === undefined && attempt < 2 && TRANSIENT.has(res.status)) {
        let parsed = null;
        try { parsed = await res.json(); } catch (e) { /* CloudFront's error page */ }
        if (!parsed || typeof parsed !== 'object') { await sleep(RETRY_MS[attempt]); continue; }
        res = {ok: res.ok, status: res.status, json: async () => parsed};
      }
      break;
    }
    if (tid) clearTimeout(tid);
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON: the edge's error page, or a reply cut off */ }
    if (scoped && gen !== S.gen) return STALE();
    // Several reads can come back 401 at once: the first one goes to sign-in and keeps the page as next.
    // A session that ended mid-use says so on the sign-in page (a write: that it wasn't saved), instead of
    // dropping the reader on the landing page with no word why.
    if (res.status === 401 && path !== '/api/me') { if (S.me) S.sessionEnded = body !== undefined ? 'write' : 'read'; S.me = null; if (location.pathname !== '/signin') go(signinPath(), true); throw new ApiError(401, 'Please sign in.'); }
    const said = data && typeof data === 'object' && typeof data.error === 'string' && data.error;
    if (!res.ok) {
      if (res.status >= 500) apiBroke(path, body !== undefined, `failed (${res.status})`);
      throw new ApiError(res.status, said || failText(res.status, body !== undefined));
    }
    // A 200 whose body isn't JSON (cut off, or a proxy's page) is a failure, not an empty answer: pages
    // built on {} showed the browser's own TypeError text.
    if (!data || typeof data !== 'object') {
      apiBroke(path, body !== undefined, 'replied with no JSON');
      throw new ApiError(res.status, body !== undefined ? failText(0, true) : "Tau's reply didn't come through whole. Try again.");
    }
    return data;
  }

  // ---------- router ----------
  const routes = [
    [/^\/signin$/, viewSignin],
    [/^\/(?:dashboard)?$/, viewDashboard],
    [/^\/research$/, viewResearch],
    [/^\/research\/(\d+)$/, viewRun],
    [/^\/example$/, viewExample],  // the seeded example session, wherever it is
    [/^\/strategies$/, viewStrategies],
    [/^\/strategies\/(\d+)$/, viewStrategy],
    [/^\/deploy$/, viewDeploy],
    [/^\/community$/, viewCommunity],
    [/^\/explore$/, viewExplore],
    [/^\/(?:billing|settings\/billing)$/, viewBilling],
    [/^\/admin$/, viewAdmin],
    [/^\/(?:system|settings\/system)$/, viewSystem],
    [/^\/(?:funds|settings\/account)$/, viewFunds],
    [/^\/devlog$/, viewDevLog],
    [/^\/track-record$/, () => go('/#track-record', true)],  // the record moved onto the dashboard
    [/^\/settings(?:\/theme)?$/, viewSettings],  // Meridian's settings URLs land on the same pages
    [/^\/terms$/, viewTerms],
    [/^\/privacy$/, viewPrivacy],
  ];
  // Public routes: viewable signed-OUT, so the boot guard must not force /api/me + a signin bounce.
  const PUBLIC = new Set(['/signin', '/terms', '/privacy']);
  // The tab a path's own page marks as current (shell's `active`). A page that failed to load ("Something went
  // wrong", "Not found") keeps it marked, where it marked none and the reader lost which section they were in.
  const SECTION_OF = { '/dashboard': '/', '/example': '/research', '/settings/account': '/funds', '/settings/system': '/system', '/settings/billing': '/billing', '/settings/theme': '/settings' };
  const sectionOf = (path) => SECTION_OF[path] || path.replace(/\/\d+$/, '');
  const phone = () => !!(window.matchMedia && window.matchMedia('(max-width: 760px)').matches);
  // A scroll the page animates jumps instead for a reader who asked for less motion.
  const smooth = () => (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth');
  // On a phone the section tabs scroll sideways in one row. Mark the edges that have more tabs past
  // them (more-l / more-r on the nav), so the CSS fades and points only those edges, and the hint goes
  // away once the last tab is in view.
  let tabResize = false;
  function tabEdges(tabs) {
    const nav = tabs && tabs.parentElement;
    if (!nav) return;
    const mark = () => {
      const max = (tabs.scrollWidth || 0) - (tabs.clientWidth || 0);
      nav.classList.toggle('more-l', max > 2 && tabs.scrollLeft > 2);
      nav.classList.toggle('more-r', max > 2 && tabs.scrollLeft < max - 2);
    };
    tabs.addEventListener('scroll', mark, { passive: true });
    if (!tabResize) {
      tabResize = true;
      addEventListener('resize', () => { const t = document.querySelector('.services-in'); if (t && t.dispatchEvent) t.dispatchEvent(new Event('scroll')); });
    }
    mark();
  }
  // Signed out on a deep link: carry the page through Google sign-in (/auth/google?next=, checked by
  // the server) so the visitor lands back on it instead of on the dashboard.
  // A post link (/community#post-<id>, from the bell or an email) carries its post as ?post=<id>: the
  // server takes no #fragment back from sign-in, and the feed opens either one.
  const linkedPostQuery = () => { const m = location.pathname === '/community' && /^#post-(\d+)$/.exec(location.hash || ''); return m ? '?post=' + m[1] : location.search; };
  const signinPath = () => /^\/(?:|signin|dashboard)$/.test(location.pathname) ? '/signin' : '/signin?next=' + encodeURIComponent(location.pathname + linkedPostQuery());
  const signinNext = () => { const n = new URLSearchParams(location.search).get('next'); return n && n[0] === '/' && n[1] !== '/' ? '?next=' + encodeURIComponent(n) : ''; };
  function go(path, replace) {
    if (replace) history.replaceState(null, '', path); else history.pushState(null, '', path);
    render();
  }
  window.addEventListener('popstate', render);
  document.addEventListener('click', (e) => {
    // In-page "#id" links scroll to their target: letting the hash navigate fires popstate, whose
    // re-render dropped the reader back at the top of the page.
    // Skip to content goes to where the page's content starts, its heading (pageStart).
    const h = e.target.closest('a[href^="#"]');
    const to = h && (h.classList.contains('skip') ? pageStart() : h.getAttribute('href').length > 1 && document.getElementById(h.getAttribute('href').slice(1)));
    if (to) {
      // A link to a fold (Funds' Connect Kalshi) opens it as well.
      if (to.tagName === 'DETAILS') to.open = true;
      e.preventDefault(); to.scrollIntoView({ behavior: smooth(), block: 'start' });
      // Focus follows the scroll (Skip to content), so the next Tab starts from the target, not from the link.
      if (!to.hasAttribute('tabindex')) to.setAttribute('tabindex', '-1');
      to.focus({ preventScroll: true }); return;
    }
    const a = e.target.closest('a[href^="/"]');
    if (!a || a.target || e.metaKey || e.ctrlKey || e.shiftKey || a.hasAttribute('download') || a.dataset.native != null) return;
    e.preventDefault();
    go(a.getAttribute('href'));
  });

  function clearTimers() { if (S.perps) { S.perps.destroy(); S.perps = null; } S.timers.forEach(clearInterval); S.timers = []; }
  // A poll goes easy on a struggling server. It runs one read at a time, where a hung read used to
  // stack a new one every tick (every 2s on a run page). A read that hangs past 15s is aborted and
  // counts as a failure. After each failure in a row it sits out twice as many ticks, up to two
  // minutes, before it tries again; the first success puts it back on its interval.
  const POLL_READ = { timeoutMs: 15000 }, POLL_MAX_GAP = 120000;
  // Once a poll's last good read is older than about two of its intervals and it is still failing,
  // the figures it painted stay up but say how old they are. The next good read clears the note.
  const staleAfter = (ms) => Math.max(2 * ms, 10000);
  const staleText = (at) => `Last updated ${age(Math.max(0, Math.round((Date.now() - at) / 1000)))} ago, retrying`;
  function paced(read, ms, note) {
    let busy = false, fails = 0, wait = 0, okAt = Date.now();
    const mark = () => { if (note) note((busy || fails) && Date.now() - okAt > staleAfter(ms) ? okAt : null); };
    // wake (the browser came back online) skips what is left of the back-off.
    return (wake) => {
      if (wake === true && !busy) wait = 0;
      if (busy || wait > 0) { if (!busy) wait--; mark(); return null; }
      busy = true;
      // The read starts now, not a microtask later: a page left in between must not start it.
      let run; try { run = Promise.resolve(read(POLL_READ)); } catch (e) { run = Promise.reject(e); }
      return run.then(
        () => { fails = 0; okAt = Date.now(); },
        () => { fails++; wait = Math.min(2 ** fails, Math.ceil(POLL_MAX_GAP / ms)) - 1; },
      ).finally(() => { busy = false; mark(); });
    };
  }
  // noteId names the page's quiet "Last updated 2m ago, retrying" line beside the figures it polls.
  function poll(fn, ms, noteId) {
    const gen = S.gen;
    const tick = paced(fn, ms, noteId && ((at) => { const el = document.getElementById(noteId); if (el) el.textContent = at ? staleText(at) : ''; }));
    const id = setInterval(() => { if (!document.hidden && gen === S.gen) tick(); }, ms);
    S.timers.push(id);
    wakers.add(() => { if (gen !== S.gen) return false; if (!document.hidden) tick(true); });
  }
  // Back online: polls read now instead of sitting out their back-off (up to two minutes of old
  // figures), and a page or panel that failed to load tries again. A waker returns false once its
  // page is gone.
  const wakers = new Set();
  const wake = () => wakers.forEach((w) => { if (w() === false) wakers.delete(w); });
  // The phone says it has no network (a tunnel, a lift): a line above the page says so at once. A page
  // only said so a poll or two later ("Last updated 30s ago, retrying"), or as "Something went wrong"
  // on the next tap. It goes by itself once the network is back.
  const OFFLINE = 'You’re offline. Tau keeps what it last showed and catches up when you’re back.';
  const offline = () => typeof navigator !== 'undefined' && navigator.onLine === false;
  function netBar() {
    let bar = document.getElementById('netbar');
    if (!offline()) { if (bar) bar.remove(); return; }
    if (bar || !document.body) return;
    bar = document.createElement('div');
    bar.id = 'netbar'; bar.className = 'netbar'; bar.setAttribute('role', 'status'); bar.textContent = OFFLINE;
    document.body.insertBefore(bar, root);
  }
  window.addEventListener('offline', netBar);
  window.addEventListener('online', () => {
    netBar();
    wake();
    if (document.getElementById('bootretry')) { render(); return; }
    root.querySelectorAll('.load-fail [data-retry]').forEach((b) => b.click());
  });
  // Back on the tab after a while: polls sit out while it is hidden, so its figures may be hours old,
  // and they stood as current until the next tick (15s on the dashboard, a minute for the record).
  // They read now. A glance away and back (WAKE_AWAY_MS or less) reads nothing new.
  const WAKE_AWAY_MS = 5000;
  let hiddenAt = 0;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt && Date.now() - hiddenAt > WAKE_AWAY_MS) wake();
    hiddenAt = 0;
  });
  // SPA deploys only take effect on a full reload. Check the server's build hash on each
  // navigation (throttled); if it changed, offer a one-click reload instead of silent staleness.
  let _verAt = Date.now();  // the page just loaded this build: the first check waits, not the boot
  async function checkVersion() {
    if (!window.__BUILD__ || Date.now() - _verAt < 30000 || document.getElementById('verbar')) return;
    _verAt = Date.now();
    try {
      const d = await api('/api/version', undefined, { keep: true });
      if (d && d.v && d.v !== window.__BUILD__) {
        const bar = document.createElement('div');
        bar.id = 'verbar'; bar.className = 'verbar';
        bar.innerHTML = `<span>A new version of Tau is ready.</span><button id="verreload" class="btn sm">Reload</button>`;
        document.body.appendChild(bar);
        bar.querySelector('#verreload').onclick = () => location.reload(true);
      }
    } catch (e) { /* best-effort */ }
  }

  // A new page in the app names itself in the tab title and puts keyboard focus on its heading, as a
  // full page load would: a screen reader says where it landed, and Tab starts from the page instead of
  // from the link the repaint removed. The first page of a visit and a repaint of the same page leave
  // focus alone, and so does a page that already put focus somewhere (a field it opened).
  let shownPath = null;
  function pageArrived(path) {
    const h = root.querySelector('h1'), tab = root.querySelector('.services [aria-current="page"]');
    // The signed-out landing keeps the plain product name; its headline is not a page name.
    // plain(): the tab title is read and copied as text, so it carries no word joiner (usd()).
    const name = root.querySelector('.services') ? plain((h && h.textContent) || (tab && tab.textContent) || '').replace(/\s+/g, ' ').trim() : '';
    document.title = name ? `${clipWords(name, 59)}${SEP}Tau` : 'Tau';
    const moved = shownPath !== null && shownPath !== path;
    shownPath = path;
    const a = document.activeElement, top = pageStart();
    if (moved && top && top.focus && (!a || a === document.body)) top.focus({ preventScroll: true });
  }
  // Where a page's content starts: the h1 that opens <main>, above the page's money figures, made
  // focusable for a script. A page with no h1 in <main> (the landing) starts at #main.
  function pageStart() {
    const h = root.querySelector('main h1');
    if (!h) return document.getElementById('main');
    if (h.getAttribute('tabindex') == null) h.setAttribute('tabindex', '-1');
    return h;
  }
  async function render() {
    clearTimers();
    checkVersion();
    const gen = ++S.gen;
    window.scrollTo(0, 0);
    // On a phone the open autopilot panel fills the screen, so moving to a page closes it.
    if (phone()) { try { localStorage.setItem('tau_ap_open', '0'); } catch (e) { /* private mode */ } }
    const path = location.pathname;
    if (path === '/signin') { const f = document.getElementById('autopilot-float'); if (f) f.remove(); }
    const match = routes.map(([re, fn]) => [path.match(re), fn]).find(([m]) => m);
    if (!S.me && !PUBLIC.has(path)) {
      // Boot: don't sit on a blank white page if /api/me is slow. Paint a branded splash after a
      // short delay (so a fast boot never flashes it), and time the call out. A 401 means genuinely
      // signed out (-> signin); ANY other failure (slow/overloaded/offline) is transient, so show a
      // retry screen instead of spuriously bouncing a signed-in user to signin.
      let splashTid = root.firstChild ? null : setTimeout(() => { if (!S.me) root.innerHTML = bootSplash(); }, 250);
      // A signed-in shell carries /api/me's reply (boot.js parks it), so the page's reads start now. Once only.
      const carried = window.__TAU_ME__; window.__TAU_ME__ = null;
      try { S.me = carried && carried.user ? carried : await api('/api/me', undefined, { timeoutMs: 12000 }); }
      catch (e) {
        if (splashTid) clearTimeout(splashTid);
        if (e.status === 401) { S.signedOutAt = Date.now(); return go(signinPath(), true); }
        return bootFail();
      }
      if (splashTid) clearTimeout(splashTid);
      // Adopt the account's saved theme on a fresh device (server wins), reloading once into it.
      const server = (S.me.user && S.me.user.ui_theme) || 'tau';
      let local = 'tau'; try { local = localStorage.getItem('tau_ui') || 'tau'; } catch (e) {}
      if (server !== local && !sessionStorage.getItem('_themesync')) {
        try { sessionStorage.setItem('_themesync', '1'); localStorage.setItem('tau_ui', server); } catch (e) {}
        return location.reload();
      }
    }
    if (!match) return go('/', true);
    root.setAttribute('aria-busy', 'true');
    try { await match[1](...match[0].slice(1)); } catch (e) {
      if (gen === S.gen && e.status === 404) {
        // A deleted or mistyped strategy or session: Try again can't bring it back, so offer its list.
        const up = path.replace(/\/\d+$/, ''), label = { '/strategies': 'All strategies', '/research': 'All research sessions' }[up];
        shell(sectionOf(path), boardTitle('Not found'), `<div class="load-fail">${notice(e.message, 'bad')}<a class="btn sm" href="${label ? up : '/'}">${label || 'Dashboard'}</a></div>`);
      } else if (gen === S.gen && e.status !== 401) {
        // Offline, it isn't "something went wrong": the page loads by itself once the network is back
        // (the online handler presses Try again).
        const off = e.status === 0 && offline();
        shell(sectionOf(path), boardTitle(off ? 'You’re offline' : 'Something went wrong'), loadFail(off ? 'This page loads by itself once you’re back online.' : errText(e)));
        root.querySelector('[data-retry]').onclick = () => render();
      }
    }
    if (gen !== S.gen) return;  // the user moved on while this page loaded
    root.setAttribute('aria-busy', 'false');
    pageArrived(path);
    pagePrefetch();
    paymentGate().catch(() => {});
  }

  // Global blocking modal: a signed-in user with no card on file can't use Tau
  // until they add one (the agent is metered per token). Same look as the
  // waitlist modal, but with Stripe's Payment Element (card + Apple/Google Pay).
  let payModal = null, payCarousel = null;
  // The showcase reel on the modal's left — reuses the landing scene builders.
  const PAY_SHOW = [
    ['strat', 'Research, not guesswork', 'Every idea is backtested on data it never saw. Only strategies that clear every gate can trade.'],
    ['deploy', 'Deploy and watch it work', 'Paper money first, then your own Kalshi key. Every fill settles in real time.'],
    ['agent', 'Or let it run on autopilot', 'RSI mode researches, backtests, and deploys on its own — and never touches live money without you.'],
  ];
  function closePay() {
    if (payCarousel) { clearInterval(payCarousel); payCarousel = null; }
    sceneTimers.forEach(clearTimeout); sceneTimers = [];
    if (payModal) { payModal.remove(); payModal = null; }
  }
  async function paymentGate() {
    if (!S.me || location.pathname === '/signin' || !S.me.needs_card) { closePay(); return; }
    if (payModal) return;  // already up
    const dlg = document.createElement('dialog');
    payModal = dlg;
    dlg.className = 'wl-modal pay-modal';
    dlg.innerHTML = `
      <div class="pay-split">
        <aside class="pay-show" aria-label="What Tau does">
          <div class="pay-show-top">${ICON.mark}<span>Tau</span></div>
          <div class="pay-stage-wrap"><div class="pay-dot-head"><span></span><span></span><span></span></div><div class="pay-stage" id="pay-stage"></div></div>
          <div class="pay-cap" id="pay-cap"></div>
          <div class="pay-dots" id="pay-dots"></div>
        </aside>
        <form class="wl-inner pay-right" id="payform">
          <h2>Add a payment method</h2>
          <p class="wl-sub">Tau bills its research agent from a credit balance. Save a card and we'll add $${S.me.free_bonus} in free credits.</p>
          <div id="pay-el" class="pay-el">${loading(120)}</div>
          <p class="wl-note pay-terms" id="pay-terms" hidden></p>
          <div id="pay-hint"></div>
          <div class="pay-foot">
            <button class="pill solid wl-submit" type="submit" id="pay-submit">Save payment method</button>
            <button class="pay-signout linkish" type="button" data-signout>Sign out instead</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(dlg);
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute('open', '');
    dlg.addEventListener('cancel', (e) => e.preventDefault());  // Esc can't dismiss
    dlg.querySelector('[data-signout]').onclick = async () => {
      if (await signOut(dlg.querySelector('#pay-hint'))) { closePay(); go('/signin'); }
    };
    // Animated showcase reel on the left.
    const stage = dlg.querySelector('#pay-stage'), cap = dlg.querySelector('#pay-cap'), dots = dlg.querySelector('#pay-dots');
    dots.innerHTML = PAY_SHOW.map((s, i) => `<button type="button" class="pay-dot${i === 0 ? ' on' : ''}" aria-label="${esc(s[1])}"></button>`).join('');
    let sIdx = -1;
    const show = (i) => {
      sIdx = (i + PAY_SHOW.length) % PAY_SHOW.length;
      const [key, h, p] = PAY_SHOW[sIdx];
      sceneTimers.forEach(clearTimeout); sceneTimers = [];
      stage.innerHTML = '<div class="demo-body"></div>';
      SCENE[key](stage.querySelector('.demo-body'));
      stage.classList.remove('in'); void stage.offsetWidth; stage.classList.add('in');
      cap.innerHTML = `<h3>${h}</h3><p>${p}</p>`;
      dots.querySelectorAll('.pay-dot').forEach((d, j) => d.classList.toggle('on', j === sIdx));
    };
    const advance = () => show(sIdx + 1);
    const autoPlay = !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    const restart = () => { if (autoPlay) { clearInterval(payCarousel); payCarousel = setInterval(advance, 5400); } };
    // Clicking a dot jumps to that picture and resets the auto-advance timer.
    dots.querySelectorAll('.pay-dot').forEach((d, i) => { d.setAttribute('aria-label', `Show example ${i + 1}`); d.onclick = () => { show(i); restart(); }; });
    advance();
    restart();
    const hint = dlg.querySelector('#pay-hint');
    // Save tapped before the card form is up (Stripe's script is slow on a phone) submitted the bare form:
    // the page reloaded to "/?" and the form started over, with no word why. Until it is up, Save says so.
    dlg.querySelector('#payform').onsubmit = (e) => { e.preventDefault(); hint.innerHTML = '<p class="wl-note" role="status">The card form is still loading. Enter your card once it appears.</p>'; };
    try {
      const state = await api('/api/billing', undefined, { keep: true });
      if (!state.configured) { dlg.querySelector('#pay-el').innerHTML = ''; hint.innerHTML = '<p class="wl-err">Payments aren’t enabled on this server yet.</p>'; dlg.querySelector('#pay-submit').setAttribute('aria-disabled', 'true'); dlg.querySelector('#payform').onsubmit = (e) => e.preventDefault(); return; }
      // What the card will be charged, before it is saved: nothing now, and auto-reload is on by default.
      // The charge is split as Billing splits it: "$21.10 for $20.00 more" left the $1.10 unexplained.
      const terms = dlg.querySelector('#pay-terms');
      const split = state.topup_fee_pct != null ? `: ${usd(state.autoreload_amount)} of credits plus the ${state.topup_fee_pct}% purchase fee` : ` for ${usd(state.autoreload_amount)} more`;
      terms.textContent = 'Saving the card charges nothing.' + (state.auto_reload && state.autoreload_charge
        ? ` Auto-reload is on: when your credits fall to ${usd(state.autoreload_threshold)}, we charge the card ${usd(state.autoreload_charge)}${split}. You can turn it off on Billing.` : '');
      terms.hidden = false;
      const Stripe = await loadStripe();
      const sp = Stripe(state.publishable_key);
      const si = await api('/api/billing/setup-intent', {});
      const elements = sp.elements({ clientSecret: si.client_secret, appearance: { theme: 'flat', variables: { fontFamily: 'Archivo, sans-serif', colorPrimary: '#191B16', borderRadius: '10px' } } });
      // Trim the form: no billing address (not needed to save a card), wallets on.
      const pe = elements.create('payment', { layout: 'tabs', wallets: { applePay: 'auto', googlePay: 'auto' }, fields: { billingDetails: { address: { country: 'never' } } } });
      dlg.querySelector('#pay-el').innerHTML = '';
      pe.mount('#pay-el');
      hint.innerHTML = '';  // the form is up: a "still loading" from an early tap no longer holds
      dlg.querySelector('#payform').onsubmit = (e) => {
        e.preventDefault();
        busy(dlg.querySelector('#pay-submit'), async () => {
          hint.innerHTML = '';
          let r;
          try {
            // return_url is required because the config allows redirect methods; with
            // redirect:'if_required' a card never actually redirects, so we stay on-page.
            r = await sp.confirmSetup({ elements, redirect: 'if_required', confirmParams: { return_url: location.origin + '/billing', payment_method_data: { billing_details: { address: { country: 'US' } } } } });
          } catch (err) { hint.innerHTML = `<p class="wl-err">${esc(stripeFail(err))}</p>`; return; }
          if (r.error) { hint.innerHTML = `<p class="wl-err">${esc(stripeFail(r.error))}</p>`; return; }
          try { await api('/api/billing/card-added', { payment_method_id: r.setupIntent.payment_method }); } catch (err) { hint.innerHTML = `<p class="wl-err">${esc(err.message)}</p>`; return; }
          // The card is saved: a failed re-read of the account must not leave the wall up over it.
          S.me = await api('/api/me', undefined, { keep: true }).catch(() => Object.assign({}, S.me, { needs_card: false }));
          closePay();
          render();
        });
      };
    } catch (err) {
      // The card form didn't load (no network, Stripe's script blocked, Tau busy). Save can't work, and it
      // used to submit the bare form and reload with no word why: it says what happened and becomes Try again.
      dlg.querySelector('#pay-el').innerHTML = '';
      hint.innerHTML = `<p class="wl-err">${esc(cardFormFail(err))}</p>`;
      const again = dlg.querySelector('#pay-submit');
      again.textContent = 'Try again';
      dlg.querySelector('#payform').onsubmit = (e) => { e.preventDefault(); closePay(); paymentGate(); };
    }
  }
  // Why the card form isn't there: Tau's own words for something it refused, otherwise what to do.
  // Stripe's own words reach the user only about the card itself (declined, number incomplete): Stripe
  // writes those for the cardholder. Anything else it says (an expired form, an outage, a thrown error)
  // names its own internals, so the user reads what to do instead.
  const stripeFail = (e) => e && (e.type === 'card_error' || e.type === 'validation_error') && e.message ? e.message
    : 'Your card couldn\u2019t be saved just now. Reload the page and add it again.';
  const cardFormFail = (err) => err instanceof ApiError && err.status >= 400 && err.status < 500 ? err.message
    : 'The card form didn\u2019t load. Check your connection, or allow js.stripe.com if a blocker is on, then try again.';

  // ---------- shell ----------
  const NAV = [['/', 'Dashboard', 'dashboard'], ['/research', 'Research', 'research'], ['/strategies', 'Strategies', 'strategies'], ['/explore', 'Explore', 'explore'], ['/deploy', 'Deploy', 'deploy'], ['/community', 'Community', 'community'], ['/funds', 'Funds', 'funds'], ['/devlog', 'Dev Logs', 'devlog']];
  // The operator can flip into a plain-user view. Only their own account is an
  // admin at all (server decides); the toggle just hides the admin surface so
  // they can see what a normal user sees. Default: admin view on.
  const isAdmin = () => !!(S.me && S.me.is_admin);
  const adminViewOn = () => isAdmin() && localStorage.getItem('tau_admin_off') !== '1';
  let bellReq = null, bellReqAt = 0, bellFresh = null;
  // The autopilot panel's status read (every 20s, on every signed-in page) keeps the bell current too:
  // at most once a minute it re-reads the list, with no timer of its own.
  const BELL_EVERY_MS = 60000;
  function bellTick() {
    if (!bellFresh || Date.now() - bellReqAt < BELL_EVERY_MS) return;
    bellReq = api('/api/notifications', undefined, { keep: true }); bellReqAt = Date.now();
    bellReq.then((d) => bellFresh && bellFresh(d)).catch(() => {});  // best-effort, like the first read
  }
  // A list that filled up while the user was away opens with what it holds, by kind (the server's
  // unread_kinds): a week back, seven "Autopilot put ... on paper" lines ran past the first screen
  // before the pause among them. Shown from BELL_SUM_MIN new notices; the lines below are unchanged.
  const BELL_SUM_MIN = 4;
  const BELL_SUM = [['deployed', (n) => `${n === 1 ? '1 strategy' : num(n) + ' strategies'} put on paper`],
    ['paused', (n) => `${num(n)} paused`], ['passed', (n) => `${num(n)} passed ${n === 1 ? 'its' : 'their'} paper test`],
    ['live_ready', (n) => `${num(n)} ready for live`], ['reload_failed', () => 'auto-reload couldn\u2019t charge your card'],
    ['comment', (n) => `${num(n)} comment${n === 1 ? '' : 's'}`], ['mention', (n) => `${num(n)} mention${n === 1 ? '' : 's'}`],
    ['share', (n) => `${num(n)} shared with you`]];
  function bellSummary(d) {
    const by = d.unread_kinds || {};
    if (!(d.unread >= BELL_SUM_MIN) || !Object.keys(by).length) return '';
    const parts = BELL_SUM.filter(([k]) => by[k] > 0).map(([k, say]) => say(+by[k]));
    const rest = Object.entries(by).filter(([k]) => !BELL_SUM.some(([b]) => b === k)).reduce((a, [, n]) => a + n, 0);
    if (rest) parts.push(`${num(rest)} other${rest === 1 ? '' : 's'}`);
    return `<p class="bell-sum">${num(d.unread)} new: ${parts.join(SEP)}</p>`;
  }
  async function wireBell() {
    const wrap = root.querySelector('.bell-wrap');
    if (!wrap) return;
    const trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
    const dot = wrap.querySelector('.bell-dot'), list = wrap.querySelector('#bell-list');
    const head = wrap.querySelector('.bell-head');
    // The new items stay marked while the list is open (they are read on the server as it opens), so
    // the reader can see what came in since last time; closing it clears the marks.
    const close = () => {
      menu.hidden = true; trig.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', onDoc, true);
      list.querySelectorAll('.notif.unread').forEach((n) => n.classList.remove('unread'));
      list.querySelectorAll('.notif-new, .bell-sum').forEach((n) => n.remove());
      const c = head.querySelector('.bell-new'); if (c) c.remove();
    };
    const onDoc = (e) => { if (!wrap.contains(e.target)) close(); };
    // A notice the server grouped (the same kind about the same page, in a row) says how many more it
    // stands for. One without a page to open is plain text, not a link to nowhere.
    const item = (n) => {
      const inner = `${n.read ? '' : '<span class="vh notif-new">New: </span>'}${esc(n.body)}${n.more ? `<span class="notif-more">and ${n.more} more like this</span>` : ''}${bellTime(n.created_at)}`;
      return /^\/(?!\/)/.test(n.link || '') ? `<a class="notif ${n.read ? '' : 'unread'}" href="${esc(n.link)}">${inner}</a>` : `<p class="notif ${n.read ? '' : 'unread'}">${inner}</p>`;
    };
    const paint = (d) => {
      dot.hidden = !d.unread;
      trig.setAttribute('aria-label', d.unread ? `Notifications, ${d.unread} unread` : 'Notifications');  // the dot alone is colour
      head.innerHTML = '<b>Notifications</b>' + (d.unread ? `<span class="bell-new">${d.unread} new</span>` : '');
      // Empty, it says what rings it: through a new user's first research session it said only "No notifications yet."
      list.innerHTML = d.items.length ? bellSummary(d) + d.items.map(item).join('') : '<p class="bell-empty">No notifications yet. It rings when a strategy goes on paper or is paused, passes its paper test or is ready for live, and if auto-reload can\u2019t charge your card.</p>';
    };
    // A list that didn't load still opens, says so and offers Try again; the next read (bellTick) fills it
    // too. It used to leave the bell dead for the rest of the visit: a tap did nothing and no dot ever came.
    let data = null;
    const unloaded = () => { list.innerHTML = '<p class="bell-empty">Notifications didn\u2019t load just now. <button type="button" class="btn sm" data-bell-retry>Try again</button></p>'; };
    // Focus goes into the list (its first notice, or the list itself when it is empty), so Tab and a
    // screen reader carry on from what just opened; Esc brings it back to the bell.
    const focusIn = () => (list.querySelector('a.notif') || menu).focus({ preventScroll: true });
    // An open list is read from here on, also for a repaint that reuses this reply; the marks clear on close.
    // A mark that didn't save puts the dot back: the server still has them unread, and they came back
    // unread on the next page while the bell said nothing was new. The next open tries once more; nothing
    // retries on its own.
    const seen = () => {
      if (menu.hidden || !data || !data.unread) return;
      const was = data, unread = data.unread, fresh = data.items.filter((n) => !n.read);
      data.unread = 0; fresh.forEach((n) => { n.read = true; }); dot.hidden = true; trig.setAttribute('aria-label', 'Notifications');
      api('/api/notifications/read', {}).catch(() => {
        if (data !== was) return;  // a newer read already says what the server has
        data.unread = unread; fresh.forEach((n) => { n.read = false; });
        if (menu.hidden) paint(data); else { dot.hidden = false; trig.setAttribute('aria-label', `Notifications, ${unread} unread`); }
      });
    };
    const load = async () => {
      // The shell is often painted twice in a row (instant page switch, then content): one read serves both.
      if (!bellReq || Date.now() - bellReqAt > 2000) { bellReq = api('/api/notifications', undefined, { keep: true }); bellReqAt = Date.now(); }
      try { data = await bellReq; paint(data); return true; } catch (e) { if (!data) unloaded(); return false; }  // bell is best-effort
    };
    await load();
    // Autopilot pauses or readies a strategy while the page sits open: the dot shows it within a minute,
    // without a reload (bellTick). An open list is left as the reader sees it, unless it never loaded.
    bellFresh = (d) => { if (menu.hidden || !data) { data = d; paint(d); seen(); } };
    trig.onclick = async (e) => {
      e.stopPropagation();
      if (!menu.hidden) { close(); return; }
      if (data && data.unread && !list.querySelector('.notif.unread')) paint(data);  // a mark that didn't save: new again
      menu.hidden = false; trig.setAttribute('aria-expanded', 'true'); document.addEventListener('click', onDoc, true);
      focusIn();
      seen();
    };
    // Focus waits on the list itself while it reads: the browser blurs a button that goes disabled or is
    // painted over, and focus leaving the bell closes the list.
    const retry = async (btn) => {
      if (btn.dataset.busy) return;
      btn.dataset.busy = '1';
      menu.focus({ preventScroll: true });
      bellReqAt = 0;  // a fresh read, not the one that just failed
      if (await load()) { focusIn(); seen(); } else { const b = list.querySelector('[data-bell-retry]'); if (b) b.focus({ preventScroll: true }); }
    };
    // Esc closes the list and gives focus back to the bell.
    wrap.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) { close(); trig.focus(); } });
    // Tabbing past the last notification left the list open behind the page, where Esc (bound here) no
    // longer reached it: focus leaving the bell closes the list, as a click outside already does.
    wrap.addEventListener('focusout', (e) => { if (!menu.hidden && !wrap.contains(e.relatedTarget)) close(); });
    // Opening a notice closes the list first, so its click-outside listener doesn't outlive the page.
    list.addEventListener('click', (e) => {
      const again = e.target.closest('[data-bell-retry]');
      if (again) retry(again); else if (e.target.closest('a.notif')) close();
    });
  }

  function shell(active, board, main) {
    document.body.classList.remove('landing-body');
    const u = S.me.user;
    const here = (NAV.concat([['/admin', 'Admin'], ['/system', 'System']]).find(([href]) => href === active) || ['', ''])[1];
    const items = NAV.concat([['/system', 'System', 'system']]).concat(adminViewOn() ? [['/admin', 'Admin', 'admin']] : []);
    const nav = items.map(([href, label]) => `<a class="svc-link" href="${href}" ${active === href ? 'aria-current="page"' : ''}>${label}</a>`).join('');
    const adminToggle = isAdmin()
      ? `<button class="admin-toggle" data-action="admintoggle" role="switch" aria-checked="${adminViewOn()}" title="${adminViewOn() ? 'Admin mode on \u2014 click to view as a user' : 'Admin mode off \u2014 click to show admin'}"><span class="admin-track"><span class="admin-knob"></span></span>Admin</button><span class="sep">\u00b7</span>`
      : '';
    // <main> starts at the board, the page's h1 and its money figures, and #main is the page below them.
    root.innerHTML = `
      <header class="masthead"><div class="masthead-in">
        <p class="wordmark"><a href="/">${ICON.mark}<span>Tau</span></a></p>
        <span class="asof">${adminToggle}<span class="bell-wrap"><button class="bell-trig" data-action="bell" aria-controls="bell-menu" aria-expanded="false" aria-label="Notifications"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg><span class="bell-dot" hidden></span></button><span class="bell-menu" id="bell-menu" role="region" aria-label="Notifications" tabindex="-1" hidden><div class="bell-head"><b>Notifications</b></div><div class="bell-list" id="bell-list"></div></span></span><span class="profile"><button class="profile-trig" data-action="profile" aria-haspopup="true" aria-expanded="false">${esc(u.name || u.email)}<svg class="profile-chev" width="9" height="9" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg></button><span class="profile-menu" hidden><a href="/settings">Settings</a><a href="/billing">Billing</a><a href="/terms">Terms</a><a href="/privacy">Privacy</a><button class="profile-item" data-action="signout">Sign out</button></span></span></span>
      </div></header>
      <nav class="services" aria-label="Sections"><div class="services-in">${nav}</div></nav>
      <main class="wrap">
        <div id="boardbody">${board}</div>
        <div id="main" tabindex="-1">${main}</div>
      </main>`;
    root.querySelectorAll('[data-action="signout"]').forEach((b) => (b.onclick = async () => {
      if (await signOut(signOutNote())) return go('/signin');
      // The menu closes so the note under it shows, and keyboard focus goes back to the menu's button.
      const menu = root.querySelector('.profile-menu'), trig = root.querySelector('.profile-trig');
      if (menu) menu.hidden = true;
      if (trig) { trig.setAttribute('aria-expanded', 'false'); trig.focus(); }
    }));
    const prof = root.querySelector('.profile');
    if (prof) {
      const trig = prof.querySelector('.profile-trig'), menu = prof.querySelector('.profile-menu');
      const close = () => { menu.hidden = true; trig.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', onDoc, true); };
      const onDoc = (e) => { if (!prof.contains(e.target)) close(); };
      trig.onclick = (e) => {
        e.stopPropagation();
        if (menu.hidden) { menu.hidden = false; trig.setAttribute('aria-expanded', 'true'); document.addEventListener('click', onDoc, true); }
        else close();
      };
      prof.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) { close(); trig.focus(); } });
      // As with the bell: Tabbing out of the menu closes it, so it is never left open with Esc out of reach.
      prof.addEventListener('focusout', (e) => { if (!menu.hidden && !prof.contains(e.relatedTarget)) close(); });
    }
    wireBell();
    // Phones scroll the section tabs in one row; bring the current one into view.
    const tabs = root.querySelector('.services-in'), curTab = tabs && tabs.querySelector('[aria-current="page"]');
    // Show the tab before the current one whole, not a clipped letter of it, so the row reads as scrollable.
    if (tabs && curTab && phone()) { const prev = curTab.previousElementSibling; tabs.scrollLeft = prev ? Math.max(0, prev.offsetLeft - tabs.offsetLeft - 4) : 0; }
    if (tabs) tabEdges(tabs);
    const at = root.querySelector('[data-action="admintoggle"]');
    if (at) at.onclick = () => {
      const turningOff = adminViewOn();
      localStorage.setItem('tau_admin_off', turningOff ? '1' : '0');
      if (turningOff && location.pathname === '/admin') go('/', true); else render();
    };
    mountHotRail();
    mountAutopilot();
  }
  const boardTitle = (title, sub = '') => `<div class="board-title"><h1 class="page">${esc(title)}</h1>${sub ? `<p class="deck">${sub}</p>` : ''}</div>`;
  async function viewDevLog() {
    shell('/devlog', boardTitle('Dev Logs', 'What we’ve shipped, and what’s next. Updated as we build.'), loading(260));
    let d;
    try { d = await api('/api/devlog'); } catch (e) { root.querySelector('#main').innerHTML = notice(e.message, 'bad'); return; }
    const planned = (d.planned || []).map((p) => `<li class="dl-item planned">
        <span class="dl-dot" aria-hidden="true"></span>
        <div class="dl-body"><h3 class="dl-what">${esc(p.title)}</h3>${p.detail ? `<p class="dl-detail">${mdLite(p.detail)}</p>` : ''}</div>
      </li>`).join('');
    const shipped = (d.shipped || []).map((s) => `<li class="dl-item">
        <span class="dl-date">${esc(s.date)}</span>
        <div class="dl-body"><h3 class="dl-what">${esc(s.title)}</h3>${s.detail ? `<p class="dl-detail">${mdLite(s.detail)}</p>` : ''}</div>
      </li>`).join('');
    const shippedCount = (d.shipped || []).length;
    let tab; try { tab = localStorage.getItem('tau_devlog_tab'); } catch (e) { /* private mode */ }
    if (tab !== 'shipped') tab = 'planned';  // default to what's next
    root.querySelector('#main').innerHTML = `
      <div class="chips dl-tabs" role="group" aria-label="Dev Logs view">
        <button class="chip" type="button" data-dltab="planned" aria-pressed="${tab === 'planned'}">Up next</button>
        <button class="chip" type="button" data-dltab="shipped" aria-pressed="${tab === 'shipped'}">Shipped${SEP}${shippedCount}</button>
      </div>
      <section class="sect dl-panel" data-dlpanel="planned"${tab === 'planned' ? '' : ' hidden'}><div class="sect-head"><h2>Shipping next</h2><p>Most-wanted first</p></div>
        <ul class="dl-list">${planned || '<li class="hint">Nothing queued.</li>'}</ul></section>
      <section class="sect dl-panel" data-dlpanel="shipped"${tab === 'shipped' ? '' : ' hidden'}><div class="sect-head"><h2>Shipped</h2><p>${shippedCount} updates</p></div>
        <ul class="dl-list">${shipped || '<li class="hint">Nothing shipped yet.</li>'}</ul></section>`;
    const setTab = (t) => {
      root.querySelectorAll('[data-dltab]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.dltab === t)));
      root.querySelectorAll('[data-dlpanel]').forEach((p) => (p.hidden = p.dataset.dlpanel !== t));
      try { localStorage.setItem('tau_devlog_tab', t); } catch (e) { /* private mode */ }
    };
    root.querySelectorAll('[data-dltab]').forEach((b) => (b.onclick = () => setTab(b.dataset.dltab)));
  }
  const THEMES = [
    { key: 'tau', name: 'Tau', desc: 'The full interface — every feature, the station-timetable look.' },
    { key: 'meridian', name: 'Meridian', desc: 'A lighter redesign of the dashboard, settings and markets.' },
  ];
  const themeName = (key) => (THEMES.find((t) => t.key === key) || THEMES[0]).name;
  // Set for the one reload after a saved switch, so the new theme's Settings says the switch took.
  const THEME_SAVED = 'tau_theme_saved';
  // Settings' email switch. It writes app_users.email_opt_out, the field the unsubscribe link in
  // community emails also sets; the server checks it before every optional email. Perps safety
  // alerts and the failed auto-reload email never read it, and the copy says so.
  const emailState = (off) => off
    ? 'Off. Tau doesn’t email you about replies to your posts, mentions of your @name, new community posts, or a paper strategy that’s ready for live trading. The bell in Tau still shows replies, mentions and ready-for-live notices.'
    : 'On. Tau emails you about replies to your posts, mentions of your @name, new community posts (at most one email every 4 hours), and a paper strategy that’s ready for live trading.';
  function emailSettings() {
    const u = (S.me && S.me.user) || {};
    const off = !!u.email_opt_out;
    return `<section class="sect email-settings"><div class="section-head"><h2>Email</h2><p>${u.email ? 'Sent to ' + esc(u.email) : 'Sent to your sign-in address'}</p></div>
        <div class="email-pref">
          <label class="switch"><input type="checkbox" id="email-optional" role="switch" aria-describedby="email-state"${off ? '' : ' checked'}><span>Updates and community email</span></label>
          <div id="email-flash"></div>
          <p class="hint" id="email-state">${esc(emailState(off))}</p>
          <p class="hint email-always"><b>Always sent:</b> safety alerts about a Bitcoin perps account you trade through Tau: a position that doesn’t match Tau’s orders, a position near liquidation, or heavy margin use. They protect real money, so this switch doesn’t stop them. Also an email when an auto-reload of your credits fails, since research pauses when they run out.</p>
        </div>
      </section>`;
  }
  function wireEmailSettings() {
    const sw = root.querySelector('#email-optional');
    if (!sw) return;
    sw.onchange = async () => {
      const off = !sw.checked;
      sw.disabled = true;
      try {
        const r = await api('/api/email-preferences', { email_opt_out: off });
        if (S.me && S.me.user) S.me.user.email_opt_out = !!r.email_opt_out;
        flash('#email-flash', r.email_opt_out ? 'Optional email is off. Safety alerts still come.' : 'Optional email is on.', 'good');
      } catch (e) { flash('#email-flash', errText(e), 'bad'); }
      const now = !!(S.me && S.me.user && S.me.user.email_opt_out);
      sw.disabled = false; sw.checked = !now;
      const state = root.querySelector('#email-state');
      if (state) state.textContent = emailState(now);
    };
  }
  async function viewSettings() {
    const current = window.__TAU_UI__ === 'meridian' ? 'meridian' : 'tau';
    shell('/settings', boardTitle('Settings', 'How Tau looks and works for you.'), `
      <section class="sect"><div class="section-head"><h2>Theme</h2><p>Changes the whole interface</p></div>
        <div class="theme-pick" role="radiogroup" aria-label="Theme">
          ${THEMES.map((t) => `<button type="button" class="theme-opt${t.key === current ? ' on' : ''}" role="radio" aria-checked="${t.key === current}" tabindex="${t.key === current ? 0 : -1}" data-theme="${t.key}">
              <span class="theme-meta"><b>${esc(t.name)}</b><span>${esc(t.desc)}</span></span>
              <span class="theme-mark" aria-hidden="true">${ICON.check}</span>
            </button>`).join('')}
        </div>
        <p class="hint" style="margin-top:12px">Switching theme reloads Tau and changes how every page looks, wherever you sign in. You can switch back here anytime.</p>
        <div id="theme-flash"></div>
      </section>
      ${emailSettings()}`);
    wireEmailSettings();
    root.querySelectorAll('[data-theme]').forEach((b) => (b.onclick = () => {
      const key = b.dataset.theme;
      if (key === current) return;
      busy(b, async () => {
        // The account's theme is saved first: a signed-in page is served in the account's theme, so a
        // switch whose save failed reloaded straight back into this one, with no word why.
        try { await api('/api/ui-theme', { theme: key }); } catch (e) {
          flash('#theme-flash', `Your theme is still ${themeName(current)}: Tau didn’t confirm the switch. Try again in a moment.`, 'bad');
          return;
        }
        try { localStorage.setItem('tau_ui', key); sessionStorage.setItem(THEME_SAVED, key); } catch (e) { /* private mode */ }
        // The shell links the theme from this cookie (the server set it too, on the save above).
        document.cookie = `tau_ui=${key}; Path=/; Max-Age=34560000; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
        location.reload();
      });
    }));
    const opts = root.querySelectorAll('[data-theme]');
    opts.forEach((b, i) => (b.onkeydown = (e) => {
      const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      opts[(i + step + opts.length) % opts.length].focus();
    }));
    let saved = null;
    try { saved = sessionStorage.getItem(THEME_SAVED); sessionStorage.removeItem(THEME_SAVED); } catch (e) { /* private mode */ }
    if (saved === current) flash('#theme-flash', `Theme set to ${themeName(current)}. It’s saved to your account, so it applies wherever you sign in.`, 'good');
  }
  // One measured cell. Money direction rides a tint field behind the figure
  // (opts.v), never a colour on the digits and never the reserved signal red.
  // Its sub-line ("paper money, not real") is a second <dd> of the same term: as a bare <div> in the <dl>
  // it fell outside the list, and a screen reader read the figure without what kind of money it is.
  const fig = (label, value, opts = {}) =>
    `<div class="m ${opts.cls || ''}"><dt class="lab">${label}</dt><dd><span class="fig ${opts.v > 0 ? 'tint pos' : opts.v < 0 ? 'tint neg' : ''}">${value}</span></dd>${opts.small ? `<dd class="sub-fig">${opts.small}</dd>` : ''}</div>`;
  // A Kalshi cash figure a shell's first read couldn't name without waiting on Kalshi (shell_reads.py) comes
  // pending: it reads Checking\u2026, never $0, and a figure the server read earlier shows only with its age.
  // `failed` is the follow-up read for it not coming back: plain words, never the error. Funds and the
  // dashboard draw it so. cashFig: [figure, the line under it] for a connected key's pending or failed cash,
  // else null. cashRead: that follow-up for one book (live | demo), asked on its own so neither waits on the
  // other's Kalshi read; it resolves to `b` with its figure, or marked failed (its last figure kept).
  const CASH_FAILED = 'Tau couldn\u2019t check your Kalshi cash just now. Reload in a minute to try again.';
  // cashNow: a pending cash whose last figure was read under CASH_RECENT_MS ago (the server's memo only just ran
  // out, its follow-up already asked) is drawn as current, with its read time, not as "checking": once a minute
  // an open page flicked to "Read 1m ago; checking\u2026" and back. Only an older figure shows its age that way.
  // The answer itself keeps its pending mark, so the follow-up is still asked. Draw from cashNow(b), ask from b.
  const CASH_RECENT_MS = 120000;
  const cashNow = (b) => {
    if (!b || !b.pending || b.last_balance == null) return b;
    if (!(Date.now() - new Date(b.last_balance_at).getTime() < CASH_RECENT_MS)) return b;
    const { pending, last_balance, last_balance_at, ...kept } = b;
    return { ...kept, balance: last_balance, balance_at: last_balance_at };
  };
  // cashAt: when a figure Kalshi answered was read ("Read from Kalshi 2m ago"), or '' with no read time.
  const cashAt = (b) => b && b.balance_at ? `Read from Kalshi ${when(b.balance_at)}` : '';
  const cashFig = (b) => b.pending ? (b.last_balance != null ? [usd(b.last_balance), `Read ${when(b.last_balance_at)}; checking Kalshi for the latest\u2026`] : ['Checking\u2026', 'Asking Kalshi for your real cash now.'])
    : b.failed ? (b.last_balance != null ? [usd(b.last_balance), `Read ${when(b.last_balance_at)}. ${CASH_FAILED}`] : ['Unavailable', CASH_FAILED]) : null;
  const cashRead = (b, book) => api('/api/funds/cash?book=' + book).then((c) => {
    const { pending, last_balance, last_balance_at, ...kept } = b;
    return { ...kept, connected: c.connected !== false, balance: c.balance == null ? null : c.balance, balance_at: c.balance_at };
  }, () => ({ ...b, pending: false, failed: true }));
  // The demo cash a pending demo-funds check waits on (the dashboard's demo health, the autopilot's idle line,
  // the Deploy board's and the strategy page's demo line): one ask at a time, shared, so they read it once (on a
  // first load, the read boot.js started). Resolves once it is back, read or not; the check is then read again,
  // from the server's memo.
  let demoAsk = null;
  const demoCashRead = () => demoAsk || (demoAsk = api('/api/funds/cash?book=demo', undefined, { keep: true })
    .catch(() => {}).then(() => { demoAsk = null; }));
  const dirTag = () => '';
  // quiet: the words go out through announce(), so the notice leaves off its own live role (read once).
  // Tau's words that send someone to Funds ("... on the Funds page ...": an engine pause reason, a deploy
  // or live-autopilot refusal) name it as a link to Funds' Connect Kalshi; it was plain text, with nothing to
  // press. Takes text already escaped (esc), so only these fixed words become markup and whatever else the
  // server said stays escaped.
  const fundsLinked = (html) => String(html).replace(/\b(?:the )?Funds page\b/, '<a href="/funds#connect-kalshi">$&</a>');
  const notice = (msg, kind = '', quiet) => `<div class="notice ${kind}"${quiet ? '' : ` role="${kind === 'bad' ? 'alert' : 'status'}"`}>${kind === 'good' ? ICON.check : ICON.warn}<span>${fundsLinked(esc(msg))}</span></div>`;
  // A failed load says so and offers a retry, instead of leaving a skeleton up for good.
  const loadFail = (msg) => `<div class="load-fail">${notice(msg, 'bad')}<button type="button" class="btn sm" data-retry>Try again</button></div>`;
  // A page's own bug (a TypeError on a reply it didn't expect) is not something to print to the user.
  // It is reported (reportBroken), so a page that breaks this way shows up on /admin.
  const errText = (e) => (e instanceof ApiError ? e.message : (reportBroken('view', e), 'Something went wrong on this page. Try again.'));
  const loading = (h = 160) => `<div class="skeleton" style="height:${h}px" aria-label="Loading"></div>`;
  // Boot screens: shown only while /api/me is in flight (splash) or after it timed out / failed
  // transiently (fail). Reuses the landing wordmark + spinner so it's on-world with zero new look.
  const bootSplash = () => `<div class="boot"><div class="lbrand">${ICON.mark}<span>Tau</span></div><div class="lspin" aria-label="Loading Tau"></div></div>`;
  function bootFail(msg = 'Tau is taking longer than usual to load — it may be briefly busy.') {
    root.innerHTML = `<div class="boot"><div class="lbrand">${ICON.mark}<span>Tau</span></div>
      <p class="boot-msg">${msg}</p>
      <button class="btn" id="bootretry">Try again</button></div>`;
    const b = document.getElementById('bootretry');
    if (b) b.onclick = () => { b.disabled = true; render(); };
  }

  // arm-to-confirm: the first press arms for 5s, a second press fires. The second press counts only once
  // ARM_HOLD has passed: a fast double-click armed with its first click and fired with its second, so
  // "Remove" stopped a deployment without the confirm ever being read. Until then the button is 'wait'
  // and a press does nothing. A held Enter's key repeats are refused too (guardArmedRepeat). Each arming
  // has its own turn, so an earlier arming's 5s reset can't disarm a later one early.
  const ARM_HOLD = 500;
  const armTurns = new WeakMap();
  function armed(btn, label, fire) {
    if (btn.dataset.armed === '1') {
      const t = armTurns.get(btn);
      btn.dataset.armed = ''; btn.classList.remove('armed'); armTurns.delete(btn);
      const done = fire();
      // An action that failed left its button saying "Confirm …", where a press only armed it again: once
      // the action answers it reads as before, unless the action relabelled it or it was armed again.
      Promise.resolve(done).finally(() => { if (t && !btn.dataset.armed && btn.textContent === t.label) btn.innerHTML = t.orig; }).catch(() => {});
      return done;
    }
    if (btn.dataset.armed === 'wait') return;
    const orig = btn.innerHTML, turn = { orig, label };
    armTurns.set(btn, turn);
    btn.dataset.armed = 'wait'; btn.classList.add('armed'); btn.textContent = label;
    announce(`${label}: press again within 5 seconds.`);
    setTimeout(() => { if (armTurns.get(btn) === turn && btn.dataset.armed === 'wait') btn.dataset.armed = '1'; }, ARM_HOLD);
    setTimeout(() => { if (armTurns.get(btn) === turn && btn.dataset.armed) { btn.dataset.armed = ''; btn.classList.remove('armed'); btn.innerHTML = orig; armTurns.delete(btn); } }, 5000);
  }
  // Copying from a page copies plain text: usd()'s word joiner stays on the screen, so a pasted "−$13.56" is
  // just that, never with an invisible character in it that a sheet or a search would trip on.
  function copyPlain() {
    if (!document.addEventListener) return;
    document.addEventListener('copy', (e) => {
      const sel = window.getSelection && window.getSelection();
      const text = sel ? String(sel) : '';
      if (!text.includes(WJ) || !e.clipboardData) return;
      const box = document.createElement('div');
      for (let i = 0; i < sel.rangeCount; i++) box.appendChild(sel.getRangeAt(i).cloneContents());
      e.clipboardData.setData('text/plain', plain(text));
      e.clipboardData.setData('text/html', plain(box.innerHTML));
      e.preventDefault();
    });
  }
  // Holding Enter on a button repeats its click: the first arms, a repeat past ARM_HOLD would confirm.
  // While any confirm is armed, a repeated Enter (not a fresh press) activates nothing.
  function guardArmedRepeat() {
    if (!document.addEventListener) return;
    document.addEventListener('keydown', (e) => {
      if (!e.repeat || e.key !== 'Enter' || (e.target && e.target.tagName === 'TEXTAREA')) return;
      if (document.querySelector('[data-armed="1"], [data-armed="wait"]')) e.preventDefault();
    }, true);
  }
  // A write that hangs (Tau hasn't answered; the edge gives up with a 504 after a minute) kept its spinner
  // with no word. After WAIT_NOTE_MS the pressed control's area says Tau hasn't confirmed yet. Display
  // only: it cancels, aborts and retries nothing, and goes the moment the write answers. waitNote(el)
  // starts the clock and returns what takes the note away; its place(twin) moves it to a repainted copy.
  const WAIT_NOTE_MS = 20000;
  const WAIT_NOTE = 'Still waiting for Tau to confirm…';
  function waitNote(el) {
    const notes = [];
    let anchor = el, shown = false;
    const place = (at) => {
      const host = at && at.isConnected && at.parentElement;
      if (!host || notes.some((n) => n.isConnected && n.parentElement === host)) return;
      const n = document.createElement('span');
      n.className = 'wait-note'; n.textContent = WAIT_NOTE;
      host.appendChild(n); notes.push(n);
    };
    const tid = setTimeout(() => { shown = true; place(anchor); announce(WAIT_NOTE); }, WAIT_NOTE_MS);
    const stop = () => { clearTimeout(tid); shown = false; notes.splice(0).forEach((n) => n.remove()); };
    stop.place = (at) => { anchor = at; if (shown) place(at); };
    return stop;
  }
  // A control that goes disabled is blurred by the browser, which dropped keyboard focus to the top of
  // the page on every busy action (Turn on autopilot, Buy credits, Start session, Verify and connect):
  // focus goes back to the button once it is enabled again, unless the action moved focus itself or
  // repainted the button away.
  async function busy(btn, fn, waited = waitNote(btn)) {
    const had = document.activeElement === btn;
    btn.classList.add('busy'); btn.disabled = true;
    try { return await fn(); } finally {
      waited();
      btn.classList.remove('busy'); btn.disabled = false;
      const a = document.activeElement;
      if (had && btn.isConnected && (!a || a === document.body) && btn.focus) btn.focus({ preventScroll: true });
    }
  }
  // After a write lands, the page re-reads to show it. That read failing is not the write failing: shown
  // as the write's error, a top-up that went through read as one that didn't, and invited buying twice.
  // refreshed() says whether the re-read came back; a write that landed says so either way, plus BEHIND.
  const refreshed = (p) => Promise.resolve(p).then(() => true, () => false);
  const BEHIND = ' The page didn’t refresh, so reload to see it.';
  // A write on Funds (add, withdraw, reset, reload, a key) repaints the whole page, and keyboard focus
  // fell to the top with the control that had it, though the result was announced. Note that control
  // first (its form and field name or button kind, or its id), then put focus on its repainted twin, or
  // on `fallback` when the write replaced it (Disconnect once a key connects, the Key ID field once it
  // is removed). Only when focus was on a control and nothing else has taken it since.
  async function holdFocus(fallback, fn) {
    const a = document.activeElement, form = a && a.closest ? a.closest('form[id]') : null;
    const name = a && a.getAttribute ? a.getAttribute('name') : null, kind = a && a.dataset ? a.dataset.kind : null;
    const sel = !a || a === document.body ? '' : form ? `#${form.id} ${name ? `[name="${name}"]` : kind ? `[data-kind="${kind}"]` : 'button'}` : a.id ? '#' + a.id : '';
    try { return await fn(); } finally {
      const now = document.activeElement;
      if (sel && (!now || now === document.body || !now.isConnected)) {
        const el = root.querySelector(sel) || (fallback ? root.querySelector(fallback) : null);
        if (el && el.focus) el.focus({ preventScroll: true });
      }
    }
  }
  // A poll repaints a region only when its markup changed. The Deploy board rewrote every row and
  // every open position each 10s even when nothing moved: ~190ms of layout and style a poll on a
  // phone-speed CPU at 30 deployments and 60 positions, and an armed "Confirm stop" was reset. The
  // markup is kept per element, so a new view's elements (shell) always paint.
  const painted = new WeakMap();
  function paint(el, html) {
    if (!el || painted.get(el) === html) return;
    painted.set(el, html);
    // A poll that redraws the page's heading while it holds focus (pageStart) leaves focus on the new one.
    const a = document.activeElement, top = !!(a && a.tagName === 'H1' && el.contains && el.contains(a));
    el.innerHTML = html;
    if (top && !a.isConnected) { const h = pageStart(); if (h && h.focus) h.focus({ preventScroll: true }); }
  }
  // A list repaints row by row: while its rows are the same ones in the same order, only a row whose
  // markup changed is rewritten (a running session's spend moved, and the other 49 sessions stay as they
  // are). `rows` is [[key, markup]], each markup one element. Any other change rewrites the whole list.
  const paintedRows = new WeakMap();
  function paintRows(el, rows, empty) {
    if (!el) return;
    const keys = rows.map(([k]) => k).join(' '), was = paintedRows.get(el);
    if (!rows.length || !was || was.keys !== keys || el.children.length !== rows.length) {
      paintedRows.set(el, rows.length ? { keys, html: rows.map(([, h]) => h) } : null);
      paint(el, rows.length ? rows.map(([, h]) => h).join('') : empty);
      return;
    }
    rows.forEach(([, h], i) => { if (was.html[i] !== h) { was.html[i] = h; el.children[i].outerHTML = h; } });
    painted.set(el, was.html.join(''));
  }
  // The dashboard and Deploy board polls send back the version of their last full answer (?v=). While the
  // answer is unchanged the server says {same: true} with only what moves between writes: each open
  // position's mark (the engine stamps it every tick), each deployment's unrealized P&L from those marks,
  // the data ages and the start of the "since your last visit" window (services.page_poll). They go back over the kept answer by id, which makes the
  // answer a fresh poll would have got; the page draws it as it draws any answer.
  function pollAnswer(kept, got) {
    if (!got || !got.same || !kept) return got;
    const marks = got.marks || {}, unreal = got.unrealized || {};
    const d = { ...kept,
      open_positions: (kept.open_positions || []).map((p) => (marks[p.id] ? { ...p, ...marks[p.id] } : p)),
      deployments: (kept.deployments || []).map((x) => (x.id in unreal ? { ...x, unrealized_pnl: unreal[x.id] } : x)) };
    if (got.freshness) d.freshness = got.freshness;
    if (got.since_at !== undefined && kept.since) d.since = { ...kept.since, at: got.since_at };
    return d;
  }
  function flash(where, msg, kind) {
    const el = typeof where === 'string' ? root.querySelector(where) : where;
    if (el) { el.innerHTML = notice(msg, kind, true); announce(msg, kind === 'bad'); }
  }
  // Two live regions for the whole app, in the page from boot (a region added along with its words is
  // often not read out): news (a deploy landed, a confirm is armed) goes to the polite one, an error to
  // the assertive one. Emptying first lets the same words be read again.
  function setupAnnouncer() {
    if (!document.body || !document.createElement) return;
    [['sr-status', 'polite'], ['sr-alert', 'assertive']].forEach(([id, level]) => {
      if (document.getElementById(id)) return;
      const el = document.createElement('div');
      el.id = id; el.className = 'vh'; el.setAttribute('aria-live', level); el.setAttribute('aria-atomic', 'true');
      document.body.appendChild(el);
    });
  }
  // Sign out. A sign-out Tau didn't confirm (no reply, or its 5xx) left the session in place, yet the page
  // went to sign-in, which sent the still-signed-in reader straight back to the dashboard with no word why:
  // it says so where it was pressed and stays. A 401 means the session had already ended.
  const SIGNOUT_FAIL = 'You’re still signed in: Tau didn’t confirm the sign-out. Check your connection and try again.';
  async function signOut(where) {
    try { await api('/api/logout', {}); }
    catch (e) { if (e.status !== 401) { flash(where, SIGNOUT_FAIL, 'bad'); return false; } }
    S.me = null;
    return true;
  }
  // The profile menu's sign-out note, at the top of the page.
  function signOutNote() {
    const m = root.querySelector('#main');
    if (!m) return null;
    let n = m.querySelector('#signout-flash');
    if (!n) { n = document.createElement('div'); n.id = 'signout-flash'; if (m.prepend) m.prepend(n); else m.appendChild(n); }
    if (n.scrollIntoView) n.scrollIntoView({ block: 'nearest' });
    return n;
  }
  function announce(msg, urgent) {
    if (!msg) return;
    setupAnnouncer();
    const el = document.getElementById(urgent ? 'sr-alert' : 'sr-status');
    if (!el) return;
    el.textContent = '';
    setTimeout(() => { el.textContent = msg; }, 50);
  }
  // A repaint that replaces the control holding keyboard focus puts focus on its copy (same id, or same
  // tag, class and link), so a poll or a toggle does not drop a keyboard user at the top of the page.
  function keepFocus(host, repaint) {
    const a = document.activeElement;
    const had = a && a !== host && host.contains && host.contains(a) ? a : null;
    repaint();
    if (!had || had.isConnected) return;
    const cls = String(had.className || '').split(/\s+/)[0], href = had.getAttribute('href');
    const key = had.id ? '#' + had.id : had.tagName.toLowerCase() + (cls ? '.' + cls : '') + (href ? `[href="${href.replace(/"/g, '\\"')}"]` : '');
    let next = null; try { next = host.querySelector(key); } catch (e) { /* a selector the page cannot read */ }
    if (next && next.focus) next.focus({ preventScroll: true });
  }

  // ---------- charts ----------
  // Registered scale: every sparkline in a set shares one dollar axis, so
  // slips compare at a glance instead of each filling its own box.
  function registry(curves) {
    let lo = 0, hi = 0;
    curves.forEach((c) => (c || []).forEach(([, v]) => { lo = Math.min(lo, v); hi = Math.max(hi, v); }));
    if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
    return { lo, hi };
  }
  // Each mode's deployments share one axis, so paper's dollars never squash live's or demo's.
  function curveRegs(deps) {
    const by = {};
    deps.forEach((d) => (by[d.mode] = by[d.mode] || []).push(d.curve));
    return Object.fromEntries(Object.entries(by).map(([mode, curves]) => [mode, registry(curves)]));
  }
  // A deployment's cumulative realized P&L, oldest trade first: a zero baseline and a line coloured
  // by where it ends. `trades` is the closed-trade count for the label: a long curve arrives cut down
  // to 120 points that keep its ends and every dip and peak. Nothing under two points.
  function spark(curve, reg, trades) {
    if (!curve || curve.length < 2) return '';
    const W = 80, H = 24;
    reg = reg || registry([curve]);
    const t0 = curve[0][0], t1 = curve[curve.length - 1][0];
    const x = t1 > t0 ? (p) => ((p[0] - t0) / (t1 - t0)) * W : (p, i) => (i / (curve.length - 1)) * W;
    const y = (v) => H - 2 - ((v - reg.lo) / (reg.hi - reg.lo)) * (H - 4);
    const pts = curve.map((p, i) => `${x(p, i).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
    const last = curve[curve.length - 1][1], n = trades == null ? curve.length : +trades;
    const label = `Cumulative P&L, ${usd(last, true)} over ${n} trade${n === 1 ? '' : 's'}`;
    return `<svg class="spark ${last > 0 ? 'up' : last < 0 ? 'down' : 'flat'}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" preserveAspectRatio="none" role="img" aria-label="${esc(plain(label))}"><line class="spark-zero" x1="0" x2="${W}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" vector-effect="non-scaling-stroke"/><polyline points="${pts}" vector-effect="non-scaling-stroke"/></svg>`;
  }
  // devCurve (optional): a second, realized series replayed read-only against
  // the Kalshi demo environment. Drawn dashed in the accent colour with a legend
  // so "Simulated" and "Kalshi dev" read apart. Omitting it keeps the old chart.
  // Draw at the column's real width on a narrow screen: a 760-wide chart shrunk to a phone has 4px labels.
  const chartWidth = () => { const m = root.querySelector('#main'), w = m && m.clientWidth; return w > 0 && w < 760 ? Math.max(300, w) : 760; };
  function equityChart(curve, cutoffIso, devCurve, options = {}) {
    const W = options.width || 760, H = 236, L = 52, R = 10, T = 30, B = 26;
    if (!curve || curve.length < 2) return `<div class="empty"><p>Not enough trades to draw an equity curve.</p></div>`;
    const dev0 = devCurve && devCurve.length > 1 ? devCurve : null;
    // Anchor the real demo-replay to the simulated line at its first timestamp, so both read as
    // cumulative P&L from the same point — the real line diverges from the sim there instead of
    // floating near $0 and looking like a disconnected stub.
    let dev = dev0;
    if (dev0) {
      const dt0 = dev0[0][0];
      let simAt = curve[0][1];
      for (const [t, v] of curve) { if (t <= dt0) simAt = v; else break; }
      const off = simAt - dev0[0][1];
      dev = dev0.map(([t, v]) => [t, v + off]);
    }
    const all = dev ? curve.concat(dev) : curve;
    const t0 = Math.min(...all.map((p) => p[0])), t1 = Math.max(...all.map((p) => p[0]));
    const vals = all.map((p) => p[1]);
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const cut = cutoffIso ? Date.parse(cutoffIso) / 1000 : null;
    const cx = cut && cut > t0 && cut < t1 ? x(cut) : null;
    const line = (c) => c.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const LEVELS = [lo, (lo + hi) / 2, hi];
    const ticks = LEVELS.map((v) => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${usd(v)}</text>`).join('');
    // The grey line across the plot is $0, break-even: unlabelled, a curve that dipped under it read against ticks
    // like −$24.72 and $26.69, with nothing saying where it had gained or lost. It gets its own label unless a
    // tick already sits on it or so close the two would overlap.
    const zeroTick = lo < 0 && hi > 0 && LEVELS.every((v) => Math.abs(y(v) - y(0)) >= 14) ? `<text class="chart-zero" x="${L - 8}" y="${y(0) + 4}" text-anchor="end">$0</text>` : '';
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const legend = dev ? `<g transform="translate(${L},${T - 12})">
        <line x1="0" x2="16" y1="0" y2="0" stroke="var(--ink)" stroke-width="2"/><text x="20" y="4" style="fill:var(--ink-2)">Simulated</text>
        <line x1="92" x2="108" y1="0" y2="0" stroke="var(--l-accent, #F05A28)" stroke-width="2" stroke-dasharray="5 4"/><text x="112" y="4" style="fill:var(--ink-2)">Kalshi dev (real)</text>
      </g>` : '';
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative profit and loss over the backtest${dev ? ', with a realized Kalshi demo-environment curve' : ''}; ends at ${plain(usd(vals[vals.length - 1], true))}">
      ${cx ? `<rect class="chart-later" x="${cx}" y="${T}" width="${W - R - cx}" height="${H - T - B}" fill="var(--chart-later)"/>
              <line x1="${cx}" x2="${cx}" y1="${T}" y2="${H - B}" stroke="var(--ink-3)" stroke-dasharray="4 4"/>
              ${unseenLabel(cx, W - R, T - 10, options.cutLabel, dev ? L + 112 + 'Kalshi dev (real)'.length * 7 + 8 : 0)}` : ''}
      <line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--rule-2)"/>
      ${ticks}${zeroTick}
      <text x="${L}" y="${H - 6}">${day(t0)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>
      <polyline points="${line(curve)}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round"/>
      ${dev ? `<polyline points="${line(dev)}" fill="none" stroke="var(--l-accent, #F05A28)" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>` : ''}
      ${legend}
    </svg>`;
  }

  // The underwater drawdown plot: the research paper's third figure, and the track record's.
  // `drawn`: a drawdown series the server already built from every trade (the track record sends
  // one, since its equity curve is thinned and could have lost the peak a drop started from).
  // `fmt` labels the worst drop: dollars for the track record, stakes for a research phase.
  function rpUnderwater(curve, drawn, fmt = usd) {
    const src = drawn || curve;
    if (!src || src.length < 2) return `<div class="rp-empty">No equity curve to derive drawdown from.</div>`;
    let peak = -Infinity; const dd = drawn || curve.map(([t, v]) => { peak = Math.max(peak, v); return [t, v - peak]; });
    const W = 340, H = 180, L = 54, R = 10, T = 14, B = 32;  // B leaves the date labels their own line
    // The same time span and date labels as the equity curve drawn above it, so the two line up.
    const span = curve && curve.length > 1 ? curve : src;
    const t0 = Math.min(span[0][0], src[0][0]), t1 = Math.max(span[span.length - 1][0], src[src.length - 1][0]);
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const minDd = Math.min(0, ...dd.map((p) => p[1])), lo = minDd < 0 ? minDd : -0.5;
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (0 - lo)) * (H - T - B);
    const curvePts = dd.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const area = `${curvePts} ${x(dd[dd.length - 1][0]).toFixed(1)},${y(0).toFixed(1)} ${x(dd[0][0]).toFixed(1)},${y(0).toFixed(1)}`;
    const maxDd = fmt(minDd);
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Underwater drawdown plot from ${day(t0)} to ${day(t1)}; worst drawdown ${plain(maxDd)}">
      <polygon points="${area}" fill="var(--signal-wash)" stroke="none"/>
      <polyline points="${curvePts}" fill="none" stroke="var(--signal)" stroke-width="1.6"/>
      <line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="var(--rule-2)"/>
      <text x="${L - 8}" y="${(y(0) + 4).toFixed(1)}" text-anchor="end">0</text>
      <text x="${L - 8}" y="${(y(minDd) + 4).toFixed(1)}" text-anchor="end">${maxDd}</text>
      <text x="${L}" y="${H - 6}">${day(t0)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>
    </svg>`;
  }

  // ---------- timetable rows ----------
  // State is a word in a mark, never colour alone. Signal red appears only on
  // states that need the user: a paused deployment and live money.
  const MARK = {
    passed: ['on', 'Passed'], failed: ['', 'Void'], rejected: ['quiet', 'Rejected'], queued: ['quiet', 'Testing'],
    paused: ['armed', 'Paused'], stopped: ['quiet', 'Stopped'], 'backtest-only': ['armed', 'Backtest only'],
  };
  const mark = (key, live) => {
    if (key === 'running') return live ? '<span class="mk live">Live</span>' : '<span class="mk">Paper</span>';
    const [cls, label] = MARK[key] || ['', key];
    return `<span class="mk ${cls}">${esc(label)}</span>`;
  };
  // A strategy's stamp: its status, unless a later check its status leaves out says otherwise (the server's
  // `verdict`, as its page shows it). A validation pass whose one-time locked holdout failed, or that the
  // diversification check after it held back, kept "Passed" on the lists; a probation strategy held back
  // after passing on paper kept its "Void".
  const VERDICT = { missed_final: ['mk', 'Missed final test'], held_back: ['mk quiet', 'Held back'] };
  const statusMark = (s) => VERDICT[s.verdict] ? `<span class="${VERDICT[s.verdict][0]}">${VERDICT[s.verdict][1]}</span>` : mark(s.status);
  const money = (v) => `<span class="${tone(v)}">${usd(v, true)}</span>`;
  // "Ideas tested": how many ideas the research session that found a strategy tested, it included. The column
  // read "Tried" over "1 of 18", which said neither what was tried nor where (Meridian calls it Ideas tested).
  const TRIED_TIP = 'Every idea the research session that found it tested, this one included';
  const STRAT_HEAD = (pick) => `<thead><tr>${pick ? '<th class="pickcol"><input type="checkbox" id="pick-all" aria-label="Select all deployable"></th>' : ''}<th>Strategy</th><th>Market</th><th class="num">Backtest P&amp;L</th><th class="num">Trades</th><th class="num">Win</th><th class="num" title="${TRIED_TIP}">Ideas tested</th><th>Status</th></tr></thead>`;
  const strategyTable = (rows, pick) => `<div class="sheet"><table class="stack t-strat">${STRAT_HEAD(pick)}<tbody>${rows}</tbody></table></div>`;
  // Bulk deploy offers only passed strategies that aren't already running: ticking one that is
  // would start a second deployment of the same rules and double its positions. A pass a later check
  // left uncleared (`verdict`: Missed final test, Held back) is left out too; its own page says why.
  const bulkDeployable = (s) => s.status === 'passed' && !s.verdict && !researchOnly(s) && !s.deployed;
  // What a deployed strategy has actually done, beside its backtest columns.
  // The server sends one book (live, else paper, else demo) and a paper strategy's demo book beside it
  // under r.demo, so sandbox dollars are never added to paper ones.
  const realTrades = (n) => `${n} trade${n === 1 ? '' : 's'}`;
  // How long a backtest window ran (its metrics' `days`), so a P&L or return says over what span.
  const overDays = (d) => !(+d > 0) ? '' : +d < 1 ? ' in under a day' : ` over ${num(Math.round(+d))} day${Math.round(+d) === 1 ? '' : 's'}`;
  // A deployment as a customer knows it: by its book and state, never by its row id.
  const BOOK_NAME = { live: 'Live', demo: 'Demo', paper: 'Paper' };
  const bookName = (d) => BOOK_NAME[d.mode] || esc(d.mode);
  // Under "Deploy on paper" while a paper deployment of it is still on (running or paused).
  const paperAgain = (deps) => deps.some((d) => d.mode === 'paper' && d.status !== 'stopped')
    ? '<p class="hint paper-again">It already runs on paper. Deploying it again starts a second copy of the same rules, which doubles its paper positions.</p>' : '';
  // The example session (and its strategies) every account is seeded with: the server flags it
  // `example`, leaves it out of every headline count, and the lists say the app ran it for free.
  const EXAMPLE_NOTE = 'An example Tau ran for you when you signed up. It cost you nothing.';
  const EXAMPLE_TAG = `<span class="mk quiet example-tag" title="${EXAMPLE_NOTE}">Example</span>`;
  // A session the autopilot started (the server's by_autopilot: a brief run, Billing's "Autopilot research").
  // Unmarked, a new user found sessions on Research they never started and could not tell they were
  // the autopilot at work.
  const AP_RUN_NOTE = 'The autopilot started this session.';
  const AP_RUN_TAG = `<span class="mk quiet ap-run-tag" title="${AP_RUN_NOTE}">Autopilot</span>`;
  // A strategy the autopilot found (the server's by_autopilot: from a session it started), so a user who
  // runs both can tell its finds from their own on the list.
  const AP_STRAT_TAG = `<span class="mk quiet ap-run-tag" title="Found in a research session the autopilot started.">Autopilot</span>`;
  const runTag = (r) => r.example ? ' ' + EXAMPLE_TAG : +r.by_autopilot ? ' ' + AP_RUN_TAG : '';
  // The run page's kind of session: its direction, and who started it when the autopilot did.
  const runKind = (r) => +r.by_autopilot && !r.example ? (r.direction ? dirLabel(r.direction) + SEP : '') + 'Started by autopilot' : dirLabel(r.direction);
  // What each figure is net of, as the dashboard and Deploy say it: "+$1.00 on paper since deploying" left out that
  // Kalshi's fees (and, on paper, the spread) were already taken off.
  const realNet = (mode) => (mode === 'paper' ? PAPER_NET : 'after Kalshi fees');
  // A paper book whose closed trades were all instant fills (the server's `instant_only`, counted as the track record
  // counts them) says so: the track record leaves those trades out and names the strategy on a row saying so, while
  // "+$3.80 on paper since deploying \u00b7 2 trades" here read as a record.
  const realInstant = (r) => `${r.trades === 1 ? 'Its only trade was an instant fill' : `All ${num(r.trades)} of its trades were instant fills`}, left out of the track record\u00a0· ${money(r.pnl)} on paper\u00a0· ${realNet('paper')}`;
  // Some of them instant fills (the server's `instant_fills`, the same split): the count says how many, so "2 trades"
  // no longer reads as the record beside a track record that counts 1 and says 1 instant fill was left out.
  const realSome = (r) => (r.mode === 'paper' && +r.instant_fills > 0 && +r.instant_fills < r.trades
    ? `, ${num(+r.instant_fills)} of them ${+r.instant_fills === 1 ? 'an instant fill' : 'instant fills'}, left out of the track record` : '');
  // A paper card's book also says it after typical live slippage (the server's slippage_estimate), on a line of
  // its own under the figure; a live card shows live money and a demo line beside paper is never estimated.
  const realFig = (r) => r ? `<div class="sub-fig real-fig">${r.trades && r.instant_only && r.mode === 'paper' ? realInstant(r) : r.trades ? `${money(r.pnl)} ${r.mode === 'demo' ? 'on demo ' : r.mode === 'paper' ? 'on paper ' : ''}since deploying\u00a0· ${realTrades(r.trades)}${realSome(r)}\u00a0· ${realNet(r.mode)}` : r.mode === 'demo' ? 'No closed demo trades yet' : r.mode === 'paper' ? 'No closed paper trades yet' : 'No closed trades yet'}</div>${r.mode === 'paper' && r.trades && slipEst(r.slippage_estimate) ? `<div class="sub-fig real-fig real-slip">${slipEst(r.slippage_estimate)}</div>` : ''}${r.demo ? `<div class="sub-fig real-fig">Demo: ${r.demo.trades ? `${money(r.demo.pnl)}\u00a0· ${realTrades(r.demo.trades)}\u00a0· ${realNet('demo')}` : 'no closed trades yet'}</div>` : ''}` : '';
  // The books a deployed strategy runs in now (the server's `books`: live, paper, demo), named on its
  // badge: "Deployed" alone left a paper, a demo and a paper-and-demo strategy looking the same.
  const bookLive = (s) => !!s.deploy_live || (Array.isArray(s.books) && s.books.includes('live'));
  const bookBadge = (s) => {
    const books = Array.isArray(s.books) ? s.books : [], live = bookLive(s);
    const rest = books.filter((m) => m === 'paper' || m === 'demo');
    const text = live ? ['Live', ...rest].join(' + ') : rest.length ? 'On ' + rest.join(' + ') : 'Deployed';
    // A live book while live trading is closed places no orders: the badge says it waits (liveWaitMark), unless
    // its row already says Paused.
    return `<span class="mk ${live ? 'live' : 'dep'}">${text}</span>${live && !(s.real && s.real.paused) ? liveWaitMark() : ''}`;
  };
  // What its removed deployments made, one line per book (the server's `past`), never added to the
  // book it runs in now: a removed strategy read as if it had never traded.
  // Its removed paper trades that were instant fills (the server's `instant_fills`, the track record's split): the
  // track record leaves them out, while "Removed from paper: +$0.75 \u00b7 2 trades" read as its count.
  const pastInstant = (m, p, n) => {
    const k = +p.instant_fills || 0;
    if (m !== 'paper' || !(k > 0) || !(n > 0)) return '';
    return k >= n ? `, ${n === 1 ? 'an instant fill' : 'all instant fills'}, left out of the track record`
      : `, ${num(k)} of them ${k === 1 ? 'an instant fill' : 'instant fills'}, left out of the track record`;
  };
  const pastFig = (past) => past && typeof past === 'object' ? ['live', 'paper', 'demo'].filter((m) => past[m]).map((m) => {
    const p = past[m], n = +p.trades || 0;
    return `<div class="sub-fig real-fig past-fig">Removed from ${m}: ${n ? `${money(+p.pnl || 0)}\u00a0· ${realTrades(n)}${pastInstant(m, p, n)}` : 'no closed trades'}</div>`;
  }).join('') : '';
  function strategySlip(s, reg, opts = {}) {
    const oos = s.out_of_sample, ins = s.in_sample || {};
    const m = oos || ins;
    // A void or rejected idea's backtest P&L read as a green "+$2.10" beside its Void stamp: it is muted
    // and says the idea did not pass, so a gain on the data it was built on never reads as a result. So is
    // one that passed validation and then missed its final test.
    const missedFinal = s.verdict === 'missed_final', noPass = s.status === 'failed' || s.status === 'rejected' || missedFinal;
    // Which history the figure covers, on every row: the column read "Unseen P&L" ("the P&L that counts")
    // over figures from the history the agent searched, marked only "tested only". A strategy researched
    // since the locked holdout keeps its unseen numbers with the gatekeeper, so most rows are that kind.
    // And over how long: "+$6.20 on unseen data" beside "58% win" said neither period nor pace (its page says both).
    // A backtest-only strategy (the old loose gate) has no gatekeeper record: its out_of_sample is the backtest's
    // later slice, which that gate picked it on, so it is "later-period", never unseen (as its page says, #590). So is
    // a passed one the server found no gatekeeper record for (no_gatekeeper_record, from the list's or the session page's own reads).
    // A held-out row's figure is the backtest after its split date too, so it says "later-period", as the sort
    // ("Later-period P&L") that orders it does: it read "on unseen data" under a sort named otherwise. Its last piece
    // says which kind, in the family's words ("later period · unseen data" / "· not held out", as the short form, the
    // Deploy hover and the strategy page say): it read "…, on unseen data" and "…, which picked it: not held out".
    // A phone's stacked card puts the line in a third of the row under "BACKTEST P&L": the sentence ran about five
    // lines there, and said "P&L" again under the label. It reads the short form ("later period · 9 days · not held
    // out"); the full sentence is its hover and what a screen reader says (bt-long, hidden on a phone only visually).
    const later = oos && (s.status === 'backtest-only' || s.no_gatekeeper_record);
    const verdictWord = missedFinal ? 'missed the final test' : noPass ? 'did not pass' : '';
    // The count and its unit hold together ("30 / days" broke across a phone's lines).
    const spanDays = (d) => !(+d > 0) ? '' : +d < 1 ? 'under a day' : `${num(Math.round(+d))}\u00a0day${Math.round(+d) === 1 ? '' : 's'}`;
    const longSub = [...(m.pnl == null ? [] : later ? [`later-period P&amp;L${overDays(m.days)} after the split date, which picked it`, 'not held out']
      : oos ? [`later-period P&amp;L${overDays(m.days)} after the split date`, 'unseen data'] : ['on the history it searched' + overDays(m.days)]), verdictWord].filter(Boolean).join(SEP);
    // Each short phrase holds together, so a narrow card breaks only at a separator ("unseen / data" split it).
    const shortSub = [...(m.pnl == null ? [] : [oos ? 'later\u00a0period' : 'history it searched', spanDays(m.days), later ? 'not\u00a0held\u00a0out' : oos ? 'unseen\u00a0data' : '']),
      verdictWord === 'did not pass' ? 'did\u00a0not\u00a0pass' : verdictWord].filter(Boolean).join(SEP);
    const pnlSub = !longSub ? '' : shortSub.replace(/\u00a0/g, ' ') === longSub.replace(/\u00a0/g, ' ') ? `<div class="sub-fig">${longSub}</div>`
      : `<div class="sub-fig bt-sub" title="${longSub}"><span class="bt-long">${longSub}</span><span class="bt-short" aria-hidden="true">${shortSub}</span></div>`;
    const tried = s.hypotheses_tried ? num(s.hypotheses_tried) : s.parent_id ? 'Adjustment' : '\u2014';
    const name = opts.nolink ? esc(s.title) : `<a href="/strategies/${s.id}">${esc(s.title)}</a>`;
    const pickCell = opts.pick ? (bulkDeployable(s)
      ? `<td class="pickcol" data-lab="Deploy"><input type="checkbox" class="pick" data-id="${s.id}" aria-label="Select for deployment"></td>`
      : '<td class="pickcol" data-lab=""></td>') : '';
    return `<tr class="${opts.land ? 'washed' : ''}">${pickCell}
      <td class="name" data-lab="">${name}${s.shared_from ? ` <span class="shared-flag">${ICON.share}${esc(s.shared_from)}</span>` : ''}${s.example ? ' ' + EXAMPLE_TAG : s.by_autopilot ? ' ' + AP_STRAT_TAG : ''}<div class="sub-fig cellwrap">${mdInline(esc(s.thesis))}</div></td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(s.market))}\u00a0· ${esc(dirLabel(s.direction))}</span></td>
      <td class="num" data-lab="Backtest P&amp;L">${m.pnl == null ? '\u2014' : noPass ? `<span class="pnl-nopass">${usd(m.pnl, true)}</span>` : money(m.pnl)}${pnlSub}</td>
      <td class="num" data-lab="Trades">${m.trades == null ? '\u2014' : m.trades}</td>
      <td class="num" data-lab="Win">${pct(m.win_rate, false)}</td>
      <td class="num${tried === '\u2014' ? ' nil' : ''}" data-lab="Ideas tested" title="${TRIED_TIP}">${esc(tried)}</td>
      <td class="act st" data-lab="Status">${statusMark(s)}${researchBadge(s)}${s.deployed && !researchOnly(s) ? ` ${bookBadge(s)}${s.real && s.real.paused ? ' ' + mark('paused') : ''}${bookLive(s) ? liveWaitLine() : ''}${realFig(s.real)}` : ''}${researchOnly(s) ? '' : pastFig(s.past)}</td>
    </tr>`;
  }
  // The Backtest estimate cell's hover text: a strategy with a gatekeeper record's held-out figure. Both say
  // "later period · unseen data" / "· not held out" as the Details line and lists do: a held-out row's read "on unseen data".
  const PACE_TIP = 'What these same closed trades would have made at the backtest’s average per trade after its split date (later period\u00a0· unseen data)';
  // A backtest-only strategy's row (the server's backtest_only): its backtest's later slice picked it, so not unseen.
  const PACE_TIP_LATER = 'What these same closed trades would have made at the backtest’s average per trade after its split date, which picked it (later period\u00a0· not held out)';
  // The column's header covers both kinds of row, so it says which is which (its glossary marker says the same at
  // more length); it read "on unseen data" over rows whose figure is later-period.
  const PACE_HEAD_TIP = 'What these same closed trades would have made at the backtest’s average per trade after its split date: held out for a strategy with a gatekeeper record, later-period (the slice that picked it) for one without';
  const DEP_HEAD = (controls) => `<thead><tr><th>Strategy</th><th>Market</th><th>Status</th><th class="num">${gl('Realized', 'realized')}</th><th class="num">${gl('Unrealized', 'unrealized')}</th><th class="num">Trades</th><th class="num" title="${PACE_HEAD_TIP}">${gl('Backtest estimate', 'pace')}</th><th>Since</th>${controls ? '<th class="act"><span class="vh">Actions</span></th>' : ''}</tr></thead>`;
  // Paused deployments need the user ("Resume or remove it on Deploy" sends them here), so they lead.
  const pausedFirst = (ds) => [...ds].sort((a, b) => (b.status === 'paused') - (a.status === 'paused'));
  const deploymentTable = (rows, controls) => `<div class="sheet dep-sheet"><table class="stack t-dep">${DEP_HEAD(controls)}<tbody>${rows}</tbody></table></div>`;
  // One plain line on how a book is doing against its backtest, written by the server
  // (services/backtest_check.py): that book's realized per-trade P&L and win rate against the
  // backtest's, "too early to tell" under 10 trades. One book per line; books are never added up.
  // Each signed amount stays on one line (a phone would otherwise break between the minus and the $).
  const btCheckLine = (c, tag = 'div') => c && c.line ? `<${tag} class="sub-fig bt-check bt-${esc(c.verdict)}">${esc(c.line).replace(/[+\u2212]\$[\d,]+\.\d\d/g, (m) => `<span class="amt">${m}</span>`)}</${tag}>` : '';
  // A paper row's strategy record toward the live check (the server's `road`: all its paper
  // deployments, counted as the strategy page's Road to live counts them) and when the trades, events
  // and hours could be in at its pace; once they are, which checks still refuse it (`failing`).
  const ROAD_FAILING = { candidate: 'clearance to trade', legacy_trades: 'trade count', legacy_pnl: 'P&amp;L', net_pnl: 'P&amp;L', edge: 'edge', recent: 'recent form', demo: 'demo record' };
  // When, in words (also the strategy page's Road to live).
  const roadDays = (d) => d < 1 ? 'under a day' : d < 1.5 ? 'about a day' : `about ${Math.round(d)} days`;
  const roadLine = (d) => {
    const r = d.road;
    if (!r) return '';
    const parts = [[r.trades, r.trades_needed, 'trades'], [r.events, r.events_needed, 'events'], [Math.floor(r.span_hours), r.span_needed_hours, 'hours']]
      .filter(([have, need]) => have < need).map(([have, need, unit]) => `<span class="nobr">${num(have)}/${num(need)}\u00a0${unit}</span>`);
    // Each "9/30 trades" piece stays whole (.nobr) and each "·" ends its line (a no-break space before it, a
    // plain one after): at 390px a line began "· 9/20 events".
    let text;
    if (parts.length) text = parts.join('\u00a0· ') + (!r.running ? '\u00a0· paused, so not growing' : r.eta_days != null ? `\u00a0· enough in ${roadDays(r.eta_days)} at its pace` : '');
    else if (!r.failing) text = 'trades, events and hours are in';
    else if (!r.failing.length) text = 'every check cleared. Live money only if you deploy it there';
    else {
      const names = [...new Set(r.failing.map((k) => ROAD_FAILING[k] || esc(k.replace(/_/g, ' '))))];
      text = `trades, events and hours are in; ${names.length} check${names.length === 1 ? '' : 's'} left: ${names.join(', ')}`;
    }
    return `<div class="sub-fig road-line">Its paper record toward live: ${text}</div>`;
  };
  // A demo row says what it is: Kalshi's sandbox with play money, a copy of its paper run when it has
  // one, there to prove the order path before live. Its fills differ from paper's because the demo
  // book is thin, which is also why its P&L is no evidence of the edge (paper keeps that job).
  // A deployment's sizing on its Deploy row. A spec stored without sizing sends stake and max_positions
  // as null: the row says the stake is not set and leaves out the cap, instead of "$ a trade, up to  open".
  const depSizing = (d) => [d.stake != null ? `$${esc(d.stake)} a trade` : 'Stake not set',
    d.max_positions != null ? `up to ${esc(d.max_positions)} open` : ''].filter(Boolean).join(', ');
  // A demo copy the demo-copy sync paused waits on its paper deployment: Resume would be paused again
  // at the sync's next pass, so it is offered disabled with the server's reason (resume_block), which
  // the row's status line also says.
  const resumeButton = (d, why = resumeBlock(d)) => `<button class="btn sm" data-dep="${d.id}" data-act="resume"${why ? ` disabled title="${esc(why)}"` : ''}>Resume<span class="vh"> ${esc(d.title)}${why ? ': ' + esc(why) : ''}</span></button>`;
  // A paper row's closed trades that were instant fills (the server's `instant_fills`: its closed trades less those
  // filled through the simulated order book, the track record's split). "2 closed" sat beside "0/30 trades" toward
  // live with no word why: the track record leaves those trades out, and so does the count of realistic paper trades
  // toward live (paper_evidence). Display only: what counts toward live is the server's alone. The term carries its
  // bubble, glued to the note's last word, as the track record's and the autopilot card's instant-fill notes do.
  const depInstant = (d) => {
    const k = +d.instant_fills || 0, n = +d.closed_trades || 0;
    if (d.mode !== 'paper' || !(k > 0) || !(n > 0)) return '';
    const lead = k >= n ? (n === 1 ? 'Its 1 closed trade was an instant fill' : `All ${num(n)} of its closed trades were instant fills`)
      : `${num(k)} of its ${num(n)} closed trades ${k === 1 ? 'was an instant fill' : 'were instant fills'}`;
    return `<div class="sub-fig dep-instant">${gl(`${lead}, left out of the track record and of the count of realistic paper trades toward live.`, 'instantfill')}</div>`;
  };
  const demoRowLine = (d) => d.mode !== 'demo' ? '' : `<div class="sub-fig demo-row">${d.demo_copy ? 'Demo copy of its paper run: the same rules on Kalshi’s sandbox, with play money' : 'On Kalshi’s sandbox, with play money'}. It proves orders place, fill and book before live money; the demo book is thin, so fills differ from paper’s.</div>`;
  function deploymentSlip(d, regs, controls) {
    const exp = d.backtest && d.backtest.out_of_sample;
    // Realized beside what the backtest's unseen-data average per trade says the same trades should
    // have made: the comparable number, not the backtest's own total over a different trade count.
    // Before the first close it names the book that has none ("no paper trades closed yet"): a bare
    // "no closed trades" under "Backtest estimate" read as if the backtest itself had no trades.
    const pace = exp && +exp.trades > 0 ? (+exp.pnl || 0) / +exp.trades : null;
    const live = d.mode === 'live', idle = depIdle(d);
    // No Unrealized figure says why, as Meridian's monitor row does: nothing open, or open with no price yet.
    // A bare "—" said neither.
    // A paused row names its book too: "Paused" alone didn't say whether real money had stopped.
    const modeTag = live ? '<span class="mk live">LIVE</span>' : d.mode === 'demo' ? '<span class="mk dep">DEMO</span>' : '<span class="mk">PAPER</span>';
    const actions = controls ? `<td class="act" data-lab="">
        ${d.status === 'running' ? `<button class="btn sm" data-dep="${d.id}" data-act="pause" data-open="${+d.open_positions || 0}">Pause<span class="vh"> ${esc(d.title)}</span></button>` : ''}
        ${d.status === 'paused' ? resumeButton(d) : ''}
        <button class="btn sm danger" data-dep="${d.id}" data-act="stop" data-open="${+d.open_positions || 0}">Remove<span class="vh"> ${esc(d.title)}</span></button></td>` : '';
    return `<tr class="${live ? 'live-row' : ''}">
      <td class="name" data-lab=""><a href="/strategies/${d.strategy_id}">${esc(d.title)}</a>
        <div class="sub-fig">${depSizing(d)}${d.status !== 'running' && (d.status_why || d.status_reason) ? SEP + fundsLinked(esc(d.status_why || d.status_reason)) : ''}</div>${idle ? `<div class="sub-fig dep-idle">${esc(idle.why)}</div>` : ''}${demoRowLine(d)}${btCheckLine(d.backtest_check)}${depInstant(d)}${roadLine(d)}</td>
      <td data-lab="Market"><span class="tick">${esc(marketFull(d.market))}</span></td>
      <td data-lab="Status">${idle ? `<span class="mk quiet">${idle.tag}</span> ${modeTag}` : d.status === 'running' ? modeTag : `${mark(d.status, live)} ${modeTag}`}</td>
      <td class="num" data-lab="Realized">${realizedCell(d)}${spark(d.curve, regs && regs[d.mode], d.closed_trades)}</td>
      <td class="num" data-lab="Unrealized">${d.unrealized_pnl == null ? `<span class="sub-fig">${+d.open_positions ? 'Unavailable' : 'None open'}</span>` : money(d.unrealized_pnl)}${d.unrealized_pnl != null && d.open_positions ? '<div class="sub-fig">est.</div>' : ''}</td>
      <td class="num" data-lab="Trades">${d.closed_trades}${d.open_positions ? `<div class="sub-fig">+${d.open_positions} open</div>` : ''}</td>
      <td class="num" data-lab="Backtest estimate" title="${d.backtest_only ? PACE_TIP_LATER : PACE_TIP}">${pace == null ? '\u2014' : d.closed_trades ? `${usd(pace * d.closed_trades, true)}<div class="sub-fig">same ${d.closed_trades} trade${d.closed_trades === 1 ? '' : 's'}</div>` : `<span class="sub-fig">${live ? 'no live trades closed yet' : d.mode === 'demo' ? 'no demo trades closed yet' : 'no paper trades closed yet'}</span>`}</td>
      <td data-lab="Since">${when(d.created_at)}</td>
      ${actions}
    </tr>`;
  }
  // One action per deployment at a time: a second press, or a poll's repainted copy of the button,
  // waits for the first to come back instead of sending again. The board re-reading after an action
  // that landed is not the action: when only the re-read fails, the action is confirmed with a word to
  // reload (it read as an error and invited a second press), and the button, still offering what was
  // just done, stays locked until the board repaints. A poll that repaints the board while an action is
  // on its way draws that deployment's buttons locked, the pressed one still busy: they read as idle
  // before, and a press on them did nothing.
  // A Deploy action or a deploy Tau didn't confirm (no reply, the edge's 5xx page, a reply cut off) may
  // have landed. "Reload the page to check" sent a phone user to reload, and a blind second press could
  // pause twice or start a second copy (nothing on the server refuses a second deploy): the words say
  // where the answer shows up. A press while the phone says it is offline never leaves it, so that one
  // says it wasn't sent. Nothing is ever sent again on its own; a write is never aborted or timed out.
  const unconfirmed = (e) => e instanceof ApiError && e.message === failText(0, true);
  const NOT_SENT = 'You\u2019re offline, so this wasn\u2019t sent. Try again once you\u2019re back online.';
  const DEP_ROW_CHECK = 'This deployment\u2019s row shows what Tau has and reads again within 10 seconds; check it before you press again.';
  const DEP_UNSURE = {
    pause: 'Tau didn\u2019t confirm the pause, so it may or may not have gone through. ' + DEP_ROW_CHECK,
    resume: 'Tau didn\u2019t confirm the resume, so it may or may not have gone through. ' + DEP_ROW_CHECK,
    stop: 'Tau didn\u2019t confirm the removal, so it may or may not have gone through. If it did, the deployment leaves this list within 10 seconds; check before you press again.',
    // The strategy page: its Stop deployment, and its Deploy buttons, which go to Deploy once they land.
    stopAll: 'Tau didn\u2019t confirm the stop, so it may or may not have gone through. Deploy shows whether it is still running; check there before you press again.',
    deploy: 'Tau didn\u2019t confirm the deploy, so it may or may not have gone through. If it did, it shows on Deploy within a few seconds; check there before you deploy again, since a second deploy runs a second copy.',
  };
  const depSaid = (e, act) => (unconfirmed(e) && DEP_UNSURE[act]) || e.message;
  const depWrite = (path, body) => (offline() ? Promise.reject(new ApiError(0, NOT_SENT)) : api(path, body));
  const depSending = new Map();  // deployment id -> the action on its way
  const depWaits = new Map();  // deployment id -> its action's waitNote, so a repainted button keeps the note
  // A failed action said why only in #flash, at the top of the board: on a phone, a row pressed a screen
  // or more below it looked like a press that did nothing. The row says it too (alert0 already announced
  // it), through the 10s poll's repaints, while the row still offers that action: once the row has moved
  // on (paused, or gone) the note goes with it, as it does on the row's next press or another page.
  const depNotes = new Map();  // deployment id -> {act, msg, gen}
  function depNotePlace(scope) {
    depNotes.forEach((n, id) => {
      const btn = scope.querySelector(`[data-dep="${id}"][data-act="${n.act}"]`);
      if (n.gen !== S.gen || (!btn && scope.querySelector(`[data-dep="${id}"]`))) { depNotes.delete(id); return; }
      const row = btn && (btn.closest('tr') || btn.closest('.dep-monitor'));
      const host = row ? row.querySelector('td.name') || row : btn && btn.parentElement;
      if (!host || host.querySelector('.dep-said')) return;
      const note = document.createElement('p');
      note.className = 'dep-said error-text'; note.setAttribute('data-dep-said', id); note.textContent = n.msg;
      host.appendChild(note);
    });
  }
  function depNoteSay(id, act, msg) {
    root.querySelectorAll(`[data-dep-said="${id}"]`).forEach((n) => n.remove());
    if (msg) { depNotes.set(id, { act, msg, gen: S.gen }); depNotePlace(root); } else depNotes.delete(id);
  }
  function bindDeploymentActions(scope, after) {
    scope.querySelectorAll('[data-dep]').forEach((btn) => {
      const going = depSending.get(btn.dataset.dep);
      if (going) {
        if (!btn.disabled) { btn.disabled = true; btn.dataset.sending = '1'; }
        if (going === btn.dataset.act) { btn.classList.add('busy'); if (depWaits.has(btn.dataset.dep)) depWaits.get(btn.dataset.dep).place(btn); }
      }
      btn.onclick = () => {
        const id = btn.dataset.dep, act = btn.dataset.act;
        if (depSending.has(id) || btn.disabled) return;
        const run = async () => {
          if (depSending.has(id)) return;
          if (offline()) { alert0(NOT_SENT); depNoteSay(id, act, NOT_SENT); return; }
          depNoteSay(id, act, '');
          depSending.set(id, act);
          const waited = waitNote(btn);
          depWaits.set(id, waited);
          let fresh = null;
          try {
            await busy(btn, async () => {
              try { await api(`/api/deployments/${id}/${act}`, {}).finally(waited); }
              catch (e) {
                alert0(depSaid(e, act)); depNoteSay(id, act, depSaid(e, act));
                if (unconfirmed(e)) Promise.resolve().then(after).catch(() => {});
                return;
              }
              fresh = await refreshed(after());
            }, waited);
          } finally {
            depSending.delete(id); depWaits.delete(id);
            root.querySelectorAll(`[data-dep="${id}"]`).forEach((b) => {
              b.classList.remove('busy');
              if (b.dataset.sending) { delete b.dataset.sending; b.disabled = false; }
            });
          }
          if (fresh === null) return;
          if (!fresh) btn.disabled = true;
          depActed(id, act, fresh);
        };
        // Pause and Remove sell what the deployment holds (the engine flattens a paused or stopped one):
        // with positions open, the first press says so and the second sends it.
        const open = +btn.dataset.open || 0;
        if (act === 'stop') armed(btn, open ? `Remove and sell ${open} open?` : 'Confirm stop', run);
        else if (act === 'pause' && open) armed(btn, `Pause and sell ${open} open?`, run);
        else run();
      };
    });
    depNotePlace(scope);
  }
  const DEP_DONE = { pause: 'Deployment paused.', resume: 'Deployment resumed.', stop: 'Deployment removed.' };
  // After Pause, Resume or Remove the board is repainted without the pressed button: say what happened,
  // and put focus on that deployment's next control, or at the top of the page once its row is gone.
  // A board that didn't repaint (fresh false) shows it done, with a word to reload.
  function depActed(id, act, fresh = true) {
    if (fresh) announce(DEP_DONE[act]); else alert0(DEP_DONE[act] + BEHIND, 'good');
    const a = document.activeElement;
    if (a && a !== document.body && a.isConnected !== false) return;
    const next = root.querySelector(`[data-dep="${id}"]`) || document.getElementById('main');
    if (next && next.focus) next.focus({ preventScroll: true });
  }
  // An action's error notice replaces the last one: a run page's Pause failing on each press stacked
  // a new notice per press. #flash holds one notice; on a page without it, the last one is removed.
  function alert0(msg, kind = 'bad') {
    const host = root.querySelector('#flash') || root.querySelector('#main');
    if (!host) return;
    if (host.id === 'flash') host.innerHTML = notice(msg, kind, true);
    else {
      const prev = host.querySelector('[data-alert0]');
      if (prev) prev.remove();
      const el = document.createElement('div');
      el.innerHTML = notice(msg, kind, true);
      el.firstChild.setAttribute('data-alert0', '');
      host.prepend(el.firstChild);
    }
    announce(msg, kind === 'bad');
  }

  // Why an idea did not pass: one row per gate it missed (server services.gate_explain), each with
  // what was measured, what was needed and one thing to try next. The server keeps each figure with
  // its unit (no-break spaces), so a phone wraps the words, never a number away from its label.
  function whyFailedHtml(lines) {
    if (!Array.isArray(lines) || !lines.length) return '';
    return `<ul class="why-failed">${lines.map((l) => `<li><b class="wf-label">${esc(l.label)}</b><span class="wf-fig">Measured ${esc(l.measured)}; needed ${esc(l.needed)}.</span><span class="wf-next"><b>Try next:</b> ${esc(l.next)}</span></li>`).join('')}</ul>`;
  }

  // ---------- landing (pre-login) ----------
  const FEATURES = [
    ['spark2', 'Idea to strategies', 'Describe an idea in a sentence. An agent turns it into several concrete, testable strategies.'],
    ['gate', 'Honest backtest gate', 'Every strategy is tested on data the agent never saw. Only ones that beat fees out of sample can trade.'],
    ['paper2', 'Paper money first', 'Start with $1,000 of practice money. Watch a strategy work on the live market before risking a cent.'],
    ['research', 'Shows its homework', 'Each strategy carries its thesis, its seen vs. unseen results, and how many ideas were tried to find it.'],
    ['comment', 'An agent co-pilot', 'Chat to adjust a live strategy. Every change is re-backtested before it is suggested, or applied on autopilot.'],
    ['key', 'Your own account', 'Live trading runs in your own Kalshi account with your own key. We never hold your funds.'],
  ];
  const FAQ = [
    ['What is Tau?', 'Tau is a self-improving research desk for Kalshi’s Bitcoin markets. You describe an idea; an agent researches it, writes concrete strategies, backtests each one on data it never saw, and lets you deploy the ones that pass — on paper first, then live in your own account.'],
    ['What markets does it cover?', 'Right now, Kalshi’s Bitcoin markets: the 15-minute contracts and the daily close at 5pm EDT. More markets will follow.'],
    ['How much does it cost?', 'Tau is free during this research preview.'],
    ['How do deposits and withdrawals work?', 'Paper money is simulated and free to add or remove. Live trading uses your own Kalshi account — you fund and withdraw at Kalshi, and Tau only places the trades for strategies you deploy. We never hold your money.'],
    ['How safe is this?', 'Paper trading risks nothing. Live trading is off by default and takes a deliberate, confirmed step; strategies have hard loss guards that pause them automatically, and your Kalshi key is encrypted and never shared.'],
  ];
  // ---------- public legal pages (viewable signed in OR out) ----------
  // In app-legal.js, fetched on first use (page files, at the end of this file). They draw without the
  // app's shell, signed out too, so they wait on the boot splash instead of a skeleton (pageView).
  function viewTerms() { return pageView('legal', 'viewTerms', null, []); }
  function viewPrivacy() { return pageView('legal', 'viewPrivacy', null, []); }

  // Said once, on the sign-in page a 401 sent the reader to; sign-in brings them back to the same page.
  function sessionEndedText() {
    const why = S.sessionEnded; S.sessionEnded = null;
    return why === 'write' ? 'You were signed out, so that last change wasn\u2019t saved. Sign in to go back to the page and try it again.'
      : why ? 'You were signed out. Sign in to go back to the page you were on.' : '';
  }
  async function viewSignin() {
    const hr = document.getElementById('hotrail'); if (hr) hr.remove();
    document.body.classList.remove('hot-open');
    // Boot just got a 401 and redirected here: don't wait on a second /api/me before painting the landing page.
    const justSignedOut = S.signedOutAt && Date.now() - S.signedOutAt < 5000;
    if (!S.me && !justSignedOut) { try { S.me = await api('/api/me'); } catch (e) { /* signed out: stay here */ } }
    if (S.me) return go('/', true);
    const q = new URLSearchParams(location.search);
    const err = q.get('error');
    const msg = { cancelled: 'Sign-in was cancelled.', expired: 'That sign-in link expired. Try again.', google: "Google couldn't confirm your account. Please try again." }[err] || sessionEndedText();
    const nextQ = signinNext();
    document.body.classList.add('landing-body');
    root.innerHTML = `
      <div class="landing">
        <header class="lnav">
          <a class="lbrand" href="/">${ICON.mark}<span>Tau</span></a>
          <div class="lnav-actions">
            <a class="pill solid" href="/auth/google${nextQ}" data-native>Sign in</a>
          </div>
        </header>
        <section class="lhero">
          <div class="lhero-copy">
            <h1>RSI for Trading.</h1>
            <p class="lsub">Recursive self-improvement, pointed at the market: an agent researches strategies, tests each on data it never saw, learns from every result, and trades only the ones that pass — in your own Kalshi account.</p>
            ${msg ? `<div class="lnotice">${esc(msg)}</div>` : ''}
            <div class="lcta" id="lcta">
              <a class="pill solid lg" href="/auth/google${nextQ}" data-native>${ICON.google}Continue with Google</a>
            </div>
            <p class="lfine">Free to start — you'll get $1,000 of paper money to research and test strategies. Live trading is optional and runs in your own Kalshi account.</p>
          </div>
          <div class="demo" id="demo" aria-hidden="true">
            <div class="demo-bar"><i></i><i></i><i></i><span class="demo-url">tau ·\u00a0research</span>
              <button class="replay" id="demo-replay" type="button">${ICON.plus}<span>Replay</span></button></div>
            <div class="demo-body" id="demo-body"></div>
          </div>
        </section>
        <main id="main">
          <div class="scenes">
            <div class="scene" data-scene="strat">
              <div class="scene-copy">
                <span class="eyebrow">${ICON.strategies}See the homework</span>
                <h2>Open any strategy and see its proof.</h2>
                <p>The thesis in plain words, the equity curve, the result on data the agent never saw, and every gate it had to clear. Nothing is a black box.</p>
              </div>
              <div class="demo"><div class="demo-bar"><i></i><i></i><i></i><span class="demo-url">tau ·\u00a0strategy</span></div><div class="demo-body"></div></div>
            </div>
            <div class="scene rev" data-scene="deploy">
              <div class="scene-copy">
                <span class="eyebrow">${ICON.deploy}Deploy &amp; monitor</span>
                <h2>Go live, and watch every trade.</h2>
                <p>Flip a passed strategy from paper to live in your own Kalshi account. Positions and P&amp;L stream in as it trades — and a loss guard pauses it automatically if it goes wrong.</p>
              </div>
              <div class="demo"><div class="demo-bar"><i></i><i></i><i></i><span class="demo-url">tau ·\u00a0deploy</span></div><div class="demo-body"></div></div>
            </div>
            <div class="scene" data-scene="agent">
              <div class="scene-copy">
                <span class="eyebrow">${ICON.spark2}RSI agent mode</span>
                <h2>Or let the agent run the whole desk.</h2>
                <p>Turn on autopilot and the agent researches, backtests, and deploys on its own — a loop that keeps hunting for edge. Every move is written down, and it never touches live money without you.</p>
              </div>
              <div class="demo"><div class="demo-bar"><i></i><i></i><i></i><span class="demo-url">tau ·\u00a0autopilot</span></div><div class="demo-body"></div></div>
            </div>
          </div>
          <footer class="lfoot">
            <a class="lbrand" href="/">${ICON.mark}<span>Tau</span></a>
            <div class="lfoot-links"><a href="/terms">Terms</a><a href="/privacy">Privacy</a><span>Research preview</span><span>© 2026 Tau</span></div>
          </footer>
        </main>
      </div>`;
    startDemo();
    setupScenes();
    root.querySelector('#demo-replay').onclick = startDemo;
  }

  // The hero demo: an idea is typed, the agent discovers strategies, each is stamped.
  const DEMO_IDEA_TEXT = 'Sell overpriced tails in last hour before 5pm close';
  const DEMO_STRATS = [
    ['Fade the far tails', 'volatility ·\u00a0fees in', 'pass', '+$38 unseen'],
    ['Sell only when calm', 'vol filter', 'pass', '+$21 unseen'],
    ['Press every strike', 'no filter', 'void', '−$44 unseen'],
    ['Chase the move', 'momentum', 'void', '−$12 unseen'],
  ];
  let demoTimers = [];
  function startDemo() {
    const body = root.querySelector('#demo-body');
    if (!body) return;
    demoTimers.forEach(clearTimeout); demoTimers = [];
    const at = (ms, fn) => demoTimers.push(setTimeout(fn, ms));
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // The bubble and status each carry a hidden "ghost" holding their final/longest
    // content, so the box reserves that full height from the first frame and the live
    // text (typed / swapped in) can never grow the container. The ghost reflows with
    // the real font, so there is no measurement to get wrong.
    body.innerHTML = `
      <div class="demo-prompt"><span class="you">J</span><div class="demo-bubble" id="demo-bubble"><span class="ghost" aria-hidden="true">${esc(DEMO_IDEA_TEXT)}</span><span class="live" id="demo-live"><span class="caret"></span></span></div></div>
      <div class="demo-status" id="demo-status"><span class="ghost" aria-hidden="true">${ICON.check}2 of 4 passed every gate — ready to deploy on paper.</span><span class="live" id="demo-stlive"></span></div>
      <div class="demo-cards" id="demo-cards"></div>`;
    const live = body.querySelector('#demo-live');
    const status = body.querySelector('#demo-stlive');
    const cards = body.querySelector('#demo-cards');
    // Build every card now (hidden) so the window holds its full height from the
    // first frame and never resizes as the research "arrives".
    const cardEls = DEMO_STRATS.map((d) => {
      const [t, meta, mk, pnl] = d;
      const el = document.createElement('div');
      el.className = 'dcard';
      el.innerHTML = `<b>${esc(t)}</b><span class="dmk ${mk === 'pass' ? 'pass' : 'void'}">${mk === 'pass' ? 'Passed' : 'Void'}</span><span class="dmeta">${esc(meta)} ·\u00a0${esc(pnl)}</span>`;
      cards.appendChild(el);
      return el;
    });
    const type = (i) => {
      if (i <= DEMO_IDEA_TEXT.length) {
        live.innerHTML = esc(DEMO_IDEA_TEXT.slice(0, i)) + '<span class="caret"></span>';
        at(reduce ? 0 : 34, () => type(i + 1));
      } else {
        live.textContent = DEMO_IDEA_TEXT;
        research();
      }
    };
    const research = () => {
      status.innerHTML = `<span class="dspin"></span>Agent researching the idea…`;
      at(1100, () => { status.innerHTML = `<span class="dspin"></span>Writing strategies and backtesting on unseen data…`; });
      // Reveal the pre-built cards one at a time; the box is already full height.
      cardEls.forEach((el, k) => reduce ? el.classList.add('in') : at(1900 + k * 560, () => el.classList.add('in')));
      at(1900 + DEMO_STRATS.length * 560 + 300, () => {
        status.innerHTML = `${ICON.check}2 of 4 passed every gate — ready to deploy on paper.`;
      });
    };
    if (reduce) { live.textContent = DEMO_IDEA_TEXT; research(); } else type(0);
  }

  // Scroll-triggered product-moment animations on the landing.
  let sceneObs = null, sceneTimers = [];
  const sAt = (ms, fn) => sceneTimers.push(setTimeout(fn, ms));
  const SCENE = {
    strat(body) {
      body.innerHTML = `<div class="sc-strat">
        <div class="head"><b>Fade the far tails</b><span class="mk on">Passed</span></div>
        <div class="sc-curve"><svg viewBox="0 0 100 40" preserveAspectRatio="none">
          <rect class="seen" x="60" y="0" width="40" height="40"></rect>
          <line class="cut" x1="60" y1="0" x2="60" y2="40"></line>
          <polyline class="ln" pathLength="100" points="0,35 12,31 22,33 32,24 42,27 54,18 60,19 70,11 80,15 90,6 100,4"></polyline>
        </svg></div>
        <div class="sc-split"><div><span>Tested (in-sample)</span><b class="gain">+$31.02</b></div><div><span>Never seen</span><b class="gain">+$6.50</b></div></div>
        <div class="sc-gates">
          <div>${ICON.check}Makes money on unseen data</div>
          <div>${ICON.check}Enough unseen trades to judge</div>
          <div>${ICON.check}Wins outweigh losses after fees</div>
        </div></div>`;
      const gates = body.querySelectorAll('.sc-gates div');
      gates.forEach((g, i) => sAt(900 + i * 320, () => g.classList.add('in')));
    },
    deploy(body) {
      body.innerHTML = `<div class="sc-dep">
        <div class="row"><b>Fade the far tails</b><span class="sc-flip" id="sc-flip">Paper</span></div>
        <div class="sc-pos" id="sc-pos"></div>
        <div class="sc-pnl"><span>Realized today</span><b id="sc-pnl">+$0.00</b></div>
      </div>`;
      const pos = body.querySelector('#sc-pos'), flip = body.querySelector('#sc-flip'), pnlEl = body.querySelector('#sc-pnl');
      sAt(700, () => { flip.classList.add('live'); flip.textContent = 'Live'; });
      const rows = [['YES ×12 @ 58¢', 3.2], ['YES ×9 @ 61¢', 1.8], ['NO ×14 @ 40¢', -0.9], ['YES ×11 @ 55¢', 2.3]];
      let pnl = 0;
      rows.forEach((r, i) => sAt(1300 + i * 620, () => {
        const el = document.createElement('div'); el.className = 'p in';
        el.innerHTML = `<b>${r[0]}</b><b class="${r[1] >= 0 ? 'gain' : 'loss'}">${r[1] >= 0 ? '+' : '−'}$${Math.abs(r[1]).toFixed(2)}</b><small>settled ·\u00a0paper → live</small>`;
        pos.appendChild(el); pos.scrollTop = pos.scrollHeight;
        pnl += r[1]; pnlEl.textContent = (pnl >= 0 ? '+' : '−') + '$' + Math.abs(pnl).toFixed(2);
        pnlEl.className = pnl >= 0 ? 'gain' : 'loss';
      }));
    },
    agent(body) {
      body.innerHTML = `<div class="sc-ap">
        <div class="toggle" id="sc-ap"><div><b>RSI agent mode — autopilot</b><small>Research, backtest, and deploy on its own</small></div><div class="sw"></div></div>
        <div class="sc-loop" id="sc-loop"></div>
      </div>`;
      const loop = body.querySelector('#sc-loop');
      sAt(600, () => body.querySelector('#sc-ap').classList.add('on'));
      const steps = [
        ['spin', 'Researching momentum into the close…'],
        ['check', "Found <b>Lean into the move</b> — passed every gate"],
        ['dot', 'Deployed on paper ·\u00a0watching it trade'],
        ['spin', 'Researching mean reversion…'],
        ['check', "Found <b>Fade the overreaction</b> — passed"],
        ['dot', 'Autopilot running ·\u00a02 strategies live on paper'],
      ];
      let shown = [];
      steps.forEach((st, i) => sAt(1200 + i * 820, () => {
        shown.forEach((e) => { const s = e.querySelector('.spinwrap'); if (s) s.remove(); });
        const el = document.createElement('div'); el.className = 'l in' + (st[0] === 'spin' ? ' spin' : '');
        const lead = st[0] === 'check' ? ICON.check : '<span class="dot"></span>';
        el.innerHTML = lead + '<span>' + st[1] + '</span>';
        loop.appendChild(el); shown.push(el); loop.scrollTop = loop.scrollHeight;
      }));
    },
  };
  function setupScenes() {
    sceneTimers.forEach(clearTimeout); sceneTimers = [];
    if (sceneObs) sceneObs.disconnect();
    const scenes = root.querySelectorAll('.scene[data-scene]');
    if (!('IntersectionObserver' in window)) { scenes.forEach((s) => SCENE[s.dataset.scene](s.querySelector('.demo-body'))); return; }
    const played = new WeakSet();
    sceneObs = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting && !played.has(en.target)) { played.add(en.target); SCENE[en.target.dataset.scene](en.target.querySelector('.demo-body')); }
        else if (!en.isIntersecting) played.delete(en.target);  // replay when scrolled back
      });
    }, { threshold: 0.45 });
    scenes.forEach((s) => sceneObs.observe(s));
  }

  // ---------- dashboard ----------
  const DASH_ROWS = 5;  // rows per dashboard list before it links to the full page
  async function viewDashboard() {
    shell('/', loading(120), loading(320));
    // The track record is its own read: asked for now, beside the board, instead of after the board
    // has painted (it waited the whole dashboard read before it started). Drawn below the board, so
    // asked only where dashTrackRecord can put it.
    const trWrap = root.querySelector('#main') && root.querySelector('#main').parentNode;
    const trFirst = trWrap && trWrap.appendChild ? api('/api/track-record', undefined, { keep: true }) : null;
    if (trFirst) trFirst.catch(() => {});  // a failure is drawn by dashTrackRecord, with its retry
    S.trReread = null;  // set by dashTrackRecord once this view's record is mounted
    let booksSeen = null;  // each book's closed and open trade counts at the last poll
    // A new account (no session of its own yet) with the autopilot off: its card, the page's one primary
    // button, goes above the strip, which has nothing to report yet. Below it, Turn on autopilot sat under
    // the fold on a phone, behind five rows of "No"s. Decided at the visit's first paint and kept for the
    // visit, so the card doesn't jump down under the strip once it is switched on.
    let apFirst = null;
    const gen = S.gen;
    const visitAt = visitStart();
    let kept = null;  // the last full answer, whose version the poll sends back (pollAnswer)
    // `filled`: the kept answer with its pending cash filled in (fillCash); else /api/dashboard is read.
    // `afterDemo`: this read follows a demo cash read (fillCash), so a demo check still pending waits for the poll.
    const load = async (cfg, filled, afterDemo) => {
      const q = [visitAt ? 'since=' + visitAt : '', kept && kept.v ? 'v=' + encodeURIComponent(kept.v) : ''].filter(Boolean).join('&');
      const got = filled || await api('/api/dashboard' + (q ? '?' + q : ''), undefined, cfg);
      const d = followLive(pollAnswer(kept, got));
      if (!got.same) kept = got;
      setVisit(visitAt, Math.floor(Date.now() / 1000));  // still here: this visit's last-seen moves on
      S.dashNoSessions = !!(d.since && d.since.own_sessions === false);
      if (apFirst == null) apFirst = S.dashNoSessions && !(S.me.user && S.me.user.autopilot);
      const depsWas = S.dashDeps, paperWas = S.dashOnPaper;
      S.dashDeps = d.deployments.length;  // the empty track record's button reads it (trackRecordPanel)
      S.dashOnPaper = d.deployments.filter((x) => x.mode === 'paper' && x.status === 'running').length;  // and its copy reads this
      // The record below polls once a minute: a trade this poll saw open or close re-reads it now (the
      // server rebuilds a cached record the board has moved past), and a first deployment repaints its
      // empty copy, which reads S.dashDeps and S.dashOnPaper.
      const books = ['paper', 'demo', 'live'].map((m) => (d[m] ? `${d[m].closed_trades}/${d[m].open_positions}` : '')).join(' ');
      if (booksSeen != null && books !== booksSeen && S.trReread) S.trReread();
      else if ((depsWas !== S.dashDeps || paperWas !== S.dashOnPaper) && trAp && trAp.host.isConnected) trAp.repaint();
      booksSeen = books;
      const p = d.paper;
      // Realized P&L (all-time + today) and open count for one money bucket; a tasteful
      // zero line when the bucket has no activity so an empty card never looks broken.
      // The figure above it is Kalshi's cash for the whole account; this line is Tau's own trades.
      const mSub = (b, zero) => (b.open_positions || b.running || b.realized_pnl) ? `Tau trades: ${b.open_positions} open${b.open_positions ? ' (not in cash)' : ''}${SEP}${usd(b.realized_pnl, true)} realized all time${SEP}${usd(b.today_pnl, true)} realized today (UTC)` : zero;
      const hasLive = d.deployments.some((x) => x.mode === 'live' && x.status !== 'stopped');
      // Demo is Kalshi's sandbox, not paper: with a demo deployment on, "Paper money only" mislabelled it.
      const hasDemo = d.deployments.some((x) => x.mode === 'demo' && x.status !== 'stopped');
      // A new account's paper book has never been used: say so instead of "$0.00 at cost · $0.00 all time".
      // Its P&L is realized from closed trades, the figure the track record, Deploy and the strategy page show.
      const paperUsed = p.open_positions || p.closed_trades || p.total_pnl || d.deployments.some((x) => x.mode === 'paper');
      // Collector lag is the operator's to fix, so only the admin view shows it (red "needs you" told
      // every user something was wrong that they couldn't act on).
      const stale = adminViewOn() && (d.freshness.btc == null || d.freshness.btc > 2700);
      const agentsBusy = d.agents.research_running + d.agents.research_queued;
      // A deployment that places no orders (depIdle: live while live trading is closed) isn't counted running.
      const idle = d.deployments.filter(depIdle).length;
      const running = d.deployments.filter((x) => x.status === 'running').length - idle;
      const paused = d.deployments.filter((x) => x.status === 'paused').length;
      const needs = stale || paused > 0;
      const said = [
        hasLive ? `${liveOpen() ? 'Live money on' : 'Live trading isn\u2019t open yet'}: ${usd(d.live.realized_pnl, true)} realized all time${liveOpen() ? '' : ' on live money'}` : hasDemo ? 'No real money: paper and demo' : 'Paper money only',
        running ? `${running} strateg${running > 1 ? 'ies' : 'y'} running` : idle || paused ? '' : 'Nothing deployed',
        idle ? `${idle} placing no orders` : '',
        // Paused rows list first; with nothing else on, the count is the whole story and Deploy is where to act on it.
        paused ? `<a class="needs-link" href="${running || idle ? '#dash-deps' : '/deploy'}"><em>${paused} paused, needs you</em></a>` : '',
        agentsBusy ? `${agentsBusy} agent${agentsBusy > 1 ? 's' : ''} researching` : '',
        stale ? `<em>${d.freshness.btc == null ? 'No backtest history yet' : 'Backtest history stale ' + age(d.freshness.btc)}</em>` : '',
      ].filter(Boolean).join('<span class="sep">/</span>');
      // A live cash still being checked reads Checking\u2026 (or its last figure, with its age), never $0 (cashFig).
      // Drawn from cashNow: a pending cash read under two minutes ago shows as current while its follow-up is out.
      const lv = cashNow(d.live);
      const liveCf = lv.connected && cashFig(lv);
      // While autopilot is off its card's "Turn on autopilot" is the one primary button on the page.
      const board = `
        <h1 class="vh">Dashboard</h1>
        <div class="statusline ${needs ? 'needs' : ''}"><p class="said">${said}</p><a class="btn${S.me.user.autopilot ? ' primary' : ''}" href="/research">New research</a></div>
        ${apFirst ? '' : sinceStrip(d, '#dash-deps')}
        <section id="dash-ap" class="apcard" aria-label="Autopilot"></section>${apFirst ? sinceStrip(d, '#dash-deps') : ''}
        <dl class="figures measure">
          ${fig('<span class="mk live">Real</span> Kalshi cash', lv.connected ? (liveCf ? liveCf[0] : lv.balance == null ? 'Unavailable' : usd(lv.balance)) : 'Not connected', { small: (lv.connected ? (liveCf ? [liveCf[1], mSub(lv, '')].filter(Boolean).join(SEP) : lv.balance == null ? ['Couldn\u2019t read your Kalshi balance just now', mSub(lv, '')].filter(Boolean).join(SEP) : [cashAt(lv), mSub(lv, LIVE_IDLE())].filter(Boolean).join(SEP)) : 'Connect your Kalshi account on <a href="/funds#connect-kalshi">Funds</a> to trade real money') + tradesCsv('live', lv) })}
          ${(demoKeyless(d.demo) ? fig(`<span class="mk dep">Demo</span> ${DEMO_BOOK}`, 'No demo key', { small: DEMO_NO_KEY }) : fig(`<span class="mk dep">Demo</span> ${DEMO_BOOK}`, usd(d.demo.equity), { v: d.demo.realized_pnl, small: `${d.demo.health ? demoHealthLine(d.demo.health) + '<br>' : ''}${(d.demo.open_positions || d.demo.running || d.demo.realized_pnl) ? `${usd(d.demo.capital)} capital${SEP}${d.demo.open_positions} open${SEP}${usd(d.demo.realized_pnl, true)} realized ${demoSpan(d.demo)}, after Kalshi fees` : `${usd(d.demo.capital)} capital${SEP}no demo strategies yet`}${SEP}${DEMO_WHAT}${tradesCsv('demo', d.demo)}` }))}
          ${fig('<span class="mk">Paper</span> Simulation', usd(p.equity), { v: p.realized_pnl, small: paperUsed ? `${usd(p.cash)} cash${hasOpen(p) ? `${SEP}${openCost(p)}${inBalance(p) ? ', ' + inBalance(p) : ''}` : ''}${SEP}${hasClosed(p) ? `<span class="amt">${usd(p.realized_pnl, true)}</span> realized all time, ${tradesCsv('paper', p, 'paperfills', PAPER_NET)}${slipEst(p.slippage_estimate)}` : PAPER_NO_CLOSE}` : `${usd(p.cash)} of practice money${SEP}no paper strategies yet` })}
        </dl><p class="stale-note" id="dash-stale" role="status"></p>${d.live.connected && d.live.open_positions ? `<p class="recon ${(d.reconcile && d.reconcile.length) ? 'warn' : 'ok'}">${(d.reconcile && d.reconcile.length) ? reconWarn(d.reconcile) : `${ICON.check} Live book reconciled with Kalshi`}</p>` : ''}`;
      const regs = curveRegs(d.deployments);
      // The dashboard is a summary: the first few deployments (paused ones, which need the user, then
      // real money, demo, paper) and a link to Deploy for the rest. Six phone cards ran ~1,400px.
      const depRank = (x) => x.status === 'paused' ? 0 : x.mode === 'live' ? 1 : x.mode === 'demo' ? 2 : 3;
      const dashDeps = [...d.deployments].sort((a, b) => depRank(a) - depRank(b)).slice(0, DASH_ROWS);
      const more = (n, what) => n > DASH_ROWS ? `<a class="stub-all" href="/deploy">See all ${n} ${what} on Deploy \u2192</a>` : '';
      const deps = d.deployments.length
        ? deploymentTable(dashDeps.map((x) => deploymentSlip(x, regs, true)).join(''), true) + more(d.deployments.length, 'deployments')  // same controls as Deploy
        : `<div id="deps-empty" data-on="${S.me.user && S.me.user.autopilot ? 1 : 0}">${depsEmpty(S.me.user && S.me.user.autopilot)}</div>`;
      // An open position says what it would sell for now and the gain in it ("+$0.48" alone read as
      // banked), or its cost with its fee (Deploy's "Cost + fee") until the engine's first price.
      const depMarket = (r) => (d.deployments.find((x) => x.id === r.deployment_id) || {}).market;
      const stubs = (rows, closed) => rows.length
        ? rows.map((r) => `<div class="stub"><b>${esc(r.side.toUpperCase())} ${esc(r.qty)} × ${cents(+r.entry_price)}</b>
            <span>${closed ? money(+r.pnl) : (r.unrealized != null ? (r.value != null ? `worth ${usd(r.value)} (${money(r.unrealized)})` : money(r.unrealized)) : openCost({ open_cost: r.cost, open_at_cost: r.at_cost != null ? r.at_cost : r.qty * r.entry_price }))}</span>
            <small>${esc(r.title)}\u00a0· <span class="pos-name">${contractLink(r.ticker, depMarket(r))}</span>${closed ? '' : `\u00a0· settles ${settleAt(r.market_close_time)}`}\u00a0· ${r.mode === 'live' ? 'LIVE' : r.mode === 'demo' ? 'DEMO' : 'PAPER'}\u00a0· ${when(closed ? r.closed_at : r.opened_at)}</small>${r.why ? `<small class="stub-why">${sepLine(r.why)}</small>` : ''}</div>`).join('')
        : `<p class="hint">${closed ? 'No settled trades yet.' : 'No open positions.'}</p>`;
      const main = `<div class="dash-wrap"><div class="dash">
          <div>
            <section class="sect"><div class="sect-head"><h2>Deployed</h2></div><div id="dash-deps">${deps}</div></section>
          </div>
          <aside aria-label="Positions">
            <section class="panel" id="dash-open"><h3>Open positions</h3>${stubs(d.open_positions.slice(0, DASH_ROWS), false)}${more(d.open_positions.length, 'open positions')}</section>
            <section class="panel"><h3>Settled lately</h3>${stubs(d.recent_closed.slice(0, DASH_ROWS), true)}${d.recent_closed.length ? '<a class="stub-all" href="#track-record">Every closed trade, with net P&amp;L, is in the track record \u2193</a>' : ''}</section>
          </aside>
        </div></div>`;
      paint(root.querySelector('#boardbody'), board);  // the 15s poll repaints only what changed
      paint(root.querySelector('#main'), main);
      S.dashPaper = p;
      paintDashAp();
      const dd = root.querySelector('#dash-deps');
      if (dd) bindDeploymentActions(dd, load);  // pause/resume/stop from the dashboard, same as Deploy
      if (!filled && !got.same) fillCash(got, afterDemo);  // every fresh answer: the first, a visit's, the poll's
    };
    // /api/dashboard never waits on Kalshi (the shell's read, a visit's and the 15s poll's alike): a live cash
    // the server hadn't read in the last minute comes pending, drawn as Checking\u2026 (never $0; an older figure
    // only with its age). Once drawn, the cash is asked on its own (on a first load boot.js has started that
    // read beside the bundle) and filled in; one that fails says so in plain words. A demo-funds check that
    // waited on the demo cash is read again once that cash is back (the autopilot's idle line does the same in
    // refreshAutopilot). A newer poll answer supersedes all of it.
    const fillCash = (first, afterDemo) => {
      if (!first || first.same) return;
      const asks = [];
      if (first.live && first.live.pending) {
        asks.push(cashRead(first.live, 'live').then((live) => {
          if (gen !== S.gen || kept !== first) return;
          // The key went in the meantime: read it all afresh. Otherwise only the cash changed.
          return (live.connected ? load(null, { ...first, live }) : load()).catch(() => {});
        }));
      }
      if (!(first.demo && first.demo.health_pending) || afterDemo) return;
      asks.push(demoCashRead());
      Promise.all(asks).then(() => {
        if (gen === S.gen && kept && kept.v === first.v) load(undefined, undefined, true).catch(() => {});
      });
    };
    await load();
    poll(load, 15000, 'dash-stale');
    dashTrackRecord(trFirst);
  }

  // ---------- research ----------
  // In app-research.js, fetched on first use (page files, at the end of this file).
  function viewResearch() { return pageView('research', 'viewResearch', '/research', []); }
  function viewRun(id) { return pageView('research', 'viewRun', '/research', [id]); }

  // ---------- strategies ----------
  // In app-strategies.js with the research paper, fetched on first use (page files, at the end of this file).
  function viewStrategies() { return pageView('strategies', 'viewStrategies', '/strategies', []); }
  function viewStrategy(id) { return pageView('strategies', 'viewStrategy', '/strategies', [id]); }

  // ---------- deploy + chat ----------
  const deployedNote = (n) => `Deployed on ${n.mode}: ${n.title}. It trades only when its rule fires, ${n.mode === 'demo' ? 'on Kalshi’s demo exchange with no real money' : 'against live prices with paper money'}, so the first trade can take a while. Its trades show up here and on the Dashboard.`;
  // An open position with no mark yet (the engine prices it on its next tick) says so in its Unrealized cell, as a
  // deployment row does: a bare "—" there said nothing, and a screen reader read it as "dash". Deploy's open
  // positions and a market page's own positions; the dashboard's cards show the position's cost until then.
  const NO_MARK = '<span class="no-mark">Unavailable</span>';
  async function viewDeploy() {
    // Autopilot + the agent chat now live in the floating window (reachable from every view),
    // so Deploy is just the board: what's trading and the open positions.
    shell('/deploy', boardTitle('Deploy', 'Your strategies trading now.') +
      '<dl class="figures measure" id="dfigs" style="margin-top:14px"></dl><p class="stale-note" id="dep-stale" role="status"></p>', `
      <div class="deploy-board"><div id="flash"></div><div id="demo-health"></div><div id="dep-ap"></div><div id="deps">${loading(260)}</div>
        <section class="section"><div class="section-head"><h2>Open positions</h2></div><div id="openpos"></div></section>
      </div>`);
    // Just deployed from a strategy page: say it worked and what happens next, once (the new row
    // reads 0 trades until its rule fires, which looked like nothing had happened).
    if (S.deployed) { flash('#flash', deployedNote(S.deployed), 'good'); S.deployed = null; }
    // An empty board asks once, in the background, how many strategies have passed: with none, "See
    // passed strategies" opened an empty list too, so the button starts a session instead. Until it
    // knows (or if the read fails) the board keeps that button.
    let passedN = null, askedPassed = false;
    let kept = null;  // the last full answer, whose version the 10s poll sends back (pollAnswer)
    const gen = S.gen;
    // `afterDemo`: this read follows the demo cash read a pending demo check asked for, so a check still
    // pending then waits for the poll (one re-read, never a loop).
    const loadBoard = async (cfg, afterDemo) => {
      const got = await api('/api/deployments' + (kept && kept.v ? '?v=' + encodeURIComponent(kept.v) : ''));
      const d = withUnrealized(followLive(pollAnswer(kept, got)));
      if (!got.same) kept = got;
      if (!d.deployments.length && !askedPassed) {
        askedPassed = true;
        api('/api/strategies?status=passed').then((r) => {
          passedN = r && r.counts ? +r.counts.passed || 0 : null;
          if (passedN === 0) loadBoard().catch(() => {});
        }, () => {});
      }
      const running = d.deployments.filter((x) => x.status === 'running');
      const depAp = root.querySelector('#dep-ap');
      paint(depAp, d.deployments.length ? apNudge('Want it to find and deploy more like this?', 'and it researches ideas and puts the ones that pass on paper by itself.') : '');
      // Live, paper and demo results are never summed into one figure: each book gets its own, and its
      // label says it sums the deployments listed below. A removed deployment leaves the list but not the
      // book, so the server sends each book's removed total (realized_by_book) and, for paper and live,
      // the two together: the dashboard's all-time figure, so the two pages reconcile to the cent.
      const books = d.realized_by_book || {};
      const sumPnl = (xs) => xs.reduce((a, x) => a + x.realized_pnl, 0);
      const listed = (m, xs) => (books[m] ? books[m].listed : sumPnl(xs));
      const removedNote = (m) => {
        const b = books[m];
        if (!b || !b.removed_deployments) return '';
        // A signed amount keeps its sign: at 390px "· −" ended one line and "$0.30 from 1 removed deployment" began the next.
        return `\u00a0· <span class="nobr">${usd(b.removed, true)}</span> from ${num(b.removed_deployments)} removed deployment${b.removed_deployments === 1 ? '' : 's'}${b.all != null ? `, <span class="nobr">${usd(b.all, true)}</span> in all` : ''}`;
      };
      const listedLab = (lab, xs) => (xs.length ? `${lab}, deployments listed below` : lab);
      // A book with no closed trade yet, listed or removed, has no P&L: it says "None yet" and when one shows, as the
      // dashboard's and the autopilot's paper P&L do, never a $0.00 that reads as trading flat.
      const noneYet = (m, xs) => !listed(m, xs) && xs.every((x) => !+x.closed_trades && !+x.realized_pnl) && !(books[m] && +books[m].removed_deployments);
      const realizedFig = (m, xs, v) => (noneYet(m, xs) ? 'None yet' : usd(v, true));
      const noneLine = (m, xs) => (noneYet(m, xs) ? `\u00a0· shows once a ${m} trade closes` : '');
      const byMode = (m) => d.deployments.filter((x) => x.mode === m);
      const liveDeps = byMode('live'), paperDeps = byMode('paper'), demoDeps = byMode('demo');
      const liveRealized = listed('live', liveDeps), paperRealized = listed('paper', paperDeps), demoRealized = listed('demo', demoDeps);
      // The listed paper deployments' figure after typical live slippage (the server's, beside `listed` only).
      const paperSlip = books.paper && books.paper.slippage_estimate;
      // Running and placing orders: a live deployment while live trading is closed, or a Bitcoin perpetual
      // one, is marked running but places none (depIdle), so it is counted apart, never as on live money.
      const active = running.filter((x) => !depIdle(x)), idle = running.length - active.length;
      const live = active.filter((x) => x.mode === 'live'), liveIdle = running.filter((x) => x.mode === 'live' && depIdle(x)).length;
      const runDemo = active.some((x) => x.mode === 'demo'), runPaper = active.some((x) => x.mode === 'paper');
      // Open positions per book, never one count across books. A book with none is left out, except
      // live while live trading is on (or a live deployment is listed), so "0 live" reads as a fact. A
      // no-break space keeps each "3 paper" whole when the figure wraps on a phone.
      const liveOn = !!(S.me && S.me.live_trading_available) || liveDeps.length > 0;
      const openSplit = ['paper', 'demo', 'live'].map((m) => [m, d.open_positions.filter((p) => (p.mode || 'paper') === m).length])
        .filter(([m, n]) => n || (m === 'live' && liveOn)).map(([m, n]) => `${num(n)}\u00a0${m}`).join('\u00a0· ') || 'None';
      paint(root.querySelector('#dfigs'), fig('Running', active.length, { small: `${d.deployments.length - running.length} paused${idle ? `${SEP}${idle} placing no orders` : ''}` }) +
        (liveDeps.length
          ? fig(listedLab('Live realized', liveDeps), realizedFig('live', liveDeps, liveRealized), { v: liveRealized, small: `real money${removedNote('live')}${noneLine('live', liveDeps)}\u00a0· after Kalshi fees${paperDeps.length ? `\u00a0· ${paperSlip ? `<span class="slip-tip"${slipTip(paperSlip)}>${usd(paperRealized, true)}</span>` : usd(paperRealized, true)} on paper from the deployments listed, counted apart, ${gl(PAPER_NET, 'paperfills')}` : ''}` })
          : paperDeps.length || !demoDeps.length ? fig(listedLab('Realized', paperDeps), realizedFig('paper', paperDeps, paperRealized), { v: paperRealized, small: `paper money, not real${removedNote('paper')}${noneLine('paper', paperDeps)}\u00a0· ${gl(PAPER_NET, 'paperfills')}${slipEst(paperSlip)}` }) : '') +
        (demoDeps.length ? fig(listedLab('Demo realized', demoDeps), realizedFig('demo', demoDeps, demoRealized), { v: demoRealized, small: `${DEMO_WHAT}${removedNote('demo')}${noneLine('demo', demoDeps)}\u00a0· after Kalshi fees` }) : '') +
        fig('Open positions', openSplit) +
        fig('Money', live.length ? '<span class="mk live">Live</span>' : runDemo ? `${runPaper ? '<span class="mk">Paper</span> ' : ''}<span class="mk dep">Demo</span>` : '<span class="mk">Paper</span>', { small: live.length ? `${live.length} on live money` : liveIdle ? liveIdleCount(liveIdle) : 'nothing on live money' }));
      const regs = curveRegs(d.deployments);
      paint(root.querySelector('#deps'), d.deployments.length ? deploymentTable(pausedFirst(d.deployments).map((x) => deploymentSlip(x, regs, true)).join(''), true)
        : `<div class="empty"><h3>Nothing deployed</h3><p>${passedN === 0 ? 'Nothing has passed yet. A strategy goes on the board once it passes every test in a research session, paper first.' : 'Open a passed strategy and post it to the board. Paper first: it trades the live market with paper money.'}</p>${S.me && S.me.user && S.me.user.autopilot ? '<p>Autopilot is on: strategies that pass every research test deploy here on their own, on paper.</p>' : ''}${apNudge('Rather not pick strategies yourself?', 'and it deploys the ones that pass, on paper.')}${passedN === 0 ? '<a class="btn" href="/research?new=1">Start a research session</a>' : '<a class="btn" href="/strategies">See passed strategies</a>'}</div>`);
      paint(root.querySelector('#demo-health'), d.demo_health ? `<div class="notice bad" role="status">${ICON.warn}<span>${demoHealthLine(d.demo_health)}</span></div>` : '');
      // The board's read never waits on Kalshi: a demo check that needs the demo cash while the server's memo
      // isn't kept comes demo_health_pending (a line from a figure read under two minutes ago stands meanwhile).
      // The page asks the demo cash (shared with the dashboard's and the autopilot's asks; on a first load, the
      // read boot.js started), then reads the board again, once.
      if (!got.same && got.demo_health_pending && !afterDemo) {
        demoCashRead().then(() => { if (gen === S.gen && kept === got) loadBoard(undefined, true).catch(() => {}); });
      }
      bindDeploymentActions(root.querySelector('#deps'), loadBoard);
      const depMarket = (p) => (d.deployments.find((x) => x.id === p.deployment_id) || {}).market;
      // Every open position says its book, paper included: a paper row had no mark beside a Demo one, so on a
      // board holding both, its Cost + fee read as nobody's money (or real money).
      const posBook = (p) => p.mode === 'live' ? '<span class="mk live">Live</span>' : p.mode === 'demo' ? '<span class="mk dep">Demo</span>' : '<span class="mk">Paper</span>';
      // Each Unrealized figure says when its mark was read (the engine's mark_ts, the time with its zone, as Settles is):
      // the column had no "as of" time. A figure the answer gives no time for is still its last mark's, and says so.
      const posMarked = (p) => `<div class="sub-fig">${p.mark_ts ? 'as of ' + settleAt(p.mark_ts) : 'at the last mark'}</div>`;
      // The figure and its time are one block: a phone's stacked card set the time on a row of its own under the
      // card's labels, one more row a position; it sits under its figure, in the Unrealized cell.
      const posUnreal = (p) => `<div class="pos-unreal">${money(p.unrealized)}${posMarked(p)}</div>`;
      paint(root.querySelector('#openpos'), d.open_positions.length ? `<table class="table stack"><thead><tr><th>Strategy</th><th>Market</th><th>Side</th><th class="num">Cost + fee</th><th class="num">Unrealized</th><th class="num">Settles</th></tr></thead><tbody>
        ${d.open_positions.map((p) => `<tr><td class="name" data-lab="Strategy">${esc(p.title)} ${posBook(p)}</td><td class="pos-name" data-lab="Market">${contractLink(p.ticker, depMarket(p))}<div class="sub-fig">${kalshiRef(p.ticker)}</div>${p.why ? `<div class="sub-fig pos-why">${sepLine(p.why)}</div>` : ''}</td><td data-lab="Side">${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(+p.entry_price)}</td><td class="num" data-lab="Cost + fee">${usd(p.cost != null ? p.cost : p.qty * p.entry_price + +p.entry_fee)}</td><td class="num" data-lab="Unrealized">${p.unrealized == null ? NO_MARK : posUnreal(p)}</td><td class="num" data-lab="Settles">${settleAt(p.market_close_time)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="hint">No open positions.</p>');
    };
    await loadBoard();
    poll(loadBoard, 10000, 'dep-stale');
  }

  // ---------- track record ----------
  // What an allocator would check: realized results from closed trades only, one money bucket at a
  // time (live, demo and paper never mix), every figure next to the sample it rests on. All math is
  // server-side (app/trading/track_record.py); this only lays it out.
  const TR_MODES = [['live', 'Live'], ['demo', 'Demo'], ['paper', 'Paper']];
  // The headline names its book and its window: scrolled past the tabs, "+$5.61" alone could be any book's.
  const trBook = (key) => (TR_MODES.find(([k]) => k === key) || [key, key])[1];
  const trFix = (v, dp = 2) => (v == null ? '—' : (+v).toFixed(dp).replace('-', '\u2212'));  // a true minus, as usd() prints
  const trDay = (ts) => (ts ? dateFmt(new Date(ts * 1000), YEAR_DAY) : '—');
  const trMonth = (k) => { const [y, m] = k.split('-'); return dateFmt(new Date(Date.UTC(+y, +m - 1, 15)), UTC_MONTH); };
  const trCi = (ci, f) => (ci ? `95%: ${f(ci[0])} to ${f(ci[1])}` : 'needs 2+ trades for a range');
  // A deployment the user removed is "Removed from paper" here, as on Deploy (its Remove button) and on the
  // Strategies list: the table called the same thing "Stopped".
  const TR_STATUS = { paused: () => 'Paused', stopped: (key) => `Removed from ${key}` };
  const TR_EDGE = { positive: ['Edge', 'on'], negative: ['Losing', 'live'], unclear: ['Unproven', ''], thin: ['Too few', 'quiet'] };
  // A first batch of trades often settles in the same second (one 15-minute close), which drew the
  // whole record as a vertical line. When every close falls within a minute, space the points one
  // per trade instead; the date labels stay true.
  const trCurve = (c) => (c && c.length > 1 && c[c.length - 1][0] - c[0][0] < 60) ? c.map(([t, v], i) => [c[0][0] + i, v]) : c;
  // Above 400 trades the server draws each stretch's lowest and highest point (track_record.thin_min_max), so
  // the caption stops claiming one point per trade; the figures beside it still count every trade.
  const trCurveCap = (m) => (m.curve || []).length < (m.trades || 0)
    ? `Cumulative net P&amp;L over all ${num(m.trades)} trades, drawn from each stretch’s lowest and highest point so no dip is skipped.`
    : 'Cumulative net P&amp;L, one point per closed trade.';
  // What the left-out instant fills made, and which way it moves the realized P&L the dashboard, Funds and Deploy show
  // (they count every closed trade): the record read −$24.72 under a −$19.90 "realized all time" for the same paper
  // book, with nothing saying the gap was one instant fill's +$4.82.
  const trLeftGap = (m) => {
    const v = +m.excluded_instant_pnl || 0, n = m.excluded_instant_fills;
    return !v ? '.' : `: ${usd(v, true)}. The realized P&L on the Dashboard, Funds and Deploy counts ${n === 1 ? 'it' : 'them'}, so it reads ${usd(Math.abs(v))} ${v > 0 ? 'higher' : 'lower'} than this record.`;
  };
  // A strategy row's share of them, so its figures meet its Strategies list line ("+$74.33 · 27 trades" beside 26 here).
  // A strategy whose only trades were instant fills (the server's `instant_only`) has a row of its own, last, so it is
  // named beside what they made instead of only in the book's caveat: none of its figures is in the record's totals.
  const trInstantOnly = (r) => {
    const n = +r.excluded_instant_fills || 0;
    return `<div class="sub-fig">${gl(`${n === 1 ? 'Its only trade was an instant fill' : `All ${num(n)} of its trades were instant fills`}, left out of this record (${usd(+r.excluded_instant_pnl || 0, true)})`, 'instantfill')}</div>`;
  };
  const trRowLeft = (r) => (r.instant_only ? trInstantOnly(r) : r.excluded_instant_fills ? `<div class="sub-fig">${gl(`${num(r.excluded_instant_fills)} instant fill${r.excluded_instant_fills === 1 ? '' : 's'} left out${+r.excluded_instant_pnl ? ` (${usd(+r.excluded_instant_pnl, true)})` : ''}`, 'instantfill')}</div>` : '');
  // The span a return is over, as the sample line counts it (track_record.sample_read): a return with no period read
  // the same for a week as for a year once the headline's "since" had scrolled away.
  const trOver = (m) => (m.span_days == null ? '' : (() => { const d = Math.max(1, Math.round(+m.span_days)); return ` over ${num(d)} day${d === 1 ? '' : 's'}`; })());
  function trackRecordPanel(m, key, th) {
    const caveats = [];
    if (m.excluded_instant_fills) caveats.push({html: `${gl(`${num(m.excluded_instant_fills)} instant-fill paper trade${m.excluded_instant_fills === 1 ? '' : 's'} left out (${INSTANT_WHY})`, 'instantfill')}${esc(trLeftGap(m))}`});
    if (m.open_trades) caveats.push(`${num(m.open_trades)} open trade${m.open_trades === 1 ? '' : 's'} (${usd(m.open_cost)} at cost + fees) ${m.open_trades === 1 ? 'joins the record when it closes' : 'join the record when they close'}.`
      // A part-sold trade's sold slice is realized (the dashboard counts it) but waits here for the rest.
      + (m.open_realized_pnl ? ` Part of ${m.open_trades === 1 ? 'it' : 'them'} is already sold: ${usd(m.open_realized_pnl, true)} realized, not yet in these figures.` : ''));
    if (key === 'live' && m.trades) caveats.push('Live results count only the trades Tau placed, net of Kalshi fees. Your Kalshi cash also moves with deposits, withdrawals and anything you trade yourself.');
    if (key === 'demo' && m.trades) caveats.push('Demo trades are real fills on Kalshi’s sandbox exchange with simulated money. Reloading the demo account doesn’t reset this record, so it can differ from the realized P&L since reload on Funds.');
    // A caveat is text, escaped here, or {html} when it carries a glossary bubble (the instant-fill one).
    const cav = caveats.length ? `<p class="hint tr-caveat">${caveats.map((c) => (typeof c === 'string' ? esc(c) : c.html)).join(' ')}</p>` : '';
    if (!m.trades) {
      // Paper only: the live and demo tabs keep their own copy.
      const apOn = key === 'paper' && !!(S.me && S.me.user && S.me.user.autopilot);
      // Something already runs on paper (the dashboard's board counts it): asking for a deploy just made
      // read as if it hadn't taken. Say it's running and why the record waits.
      const onPaper = key === 'paper' && !apOn && S.dashOnPaper > 0 ? S.dashOnPaper : 0;
      const how = key === 'live' ? 'Deploy a strategy that has proven itself on paper to live money, and its closed trades show up here.'
        : key === 'demo' ? 'Deploy a strategy to the Kalshi demo exchange to build a record with real fills and no real money.'
        : apOn ? 'Autopilot runs the strategies that pass every research test on paper, with pretend money. Every closed trade is recorded here.'
        : onPaper ? `${onPaper === 1 ? 'Your strategy is' : `${num(onPaper)} strategies are`} running on paper. ${onPaper === 1 ? 'It trades' : 'Each trades'} only when its rule fires, so the first trade can take a while. Every closed trade is recorded here.`
        // A new account with no session of its own has no passed strategy to deploy: "Deploy a passed strategy"
        // sat over a "Start a research session" button. It says where a paper strategy comes from instead.
        : S.dashDeps === 0 && S.dashNoSessions ? 'Nothing has run on paper yet: a strategy gets there by passing its tests in a research session. Every closed trade is recorded here.'
        : 'Deploy a passed strategy on paper. Every closed trade is recorded here.';
      // With nothing deployed (the dashboard's board says so), Deploy is an empty board too and sent a
      // new user Deploy → Strategies → Research; the button goes straight to the step that comes first.
      const first = key === 'paper' && !apOn && S.dashDeps === 0;
      // Nothing deployed yet: the dashboard's autopilot card above already offers the switch, so the
      // record doesn't offer it a second time.
      const go = apOn ? '<a class="btn" href="/research">See its research</a>'
        : first ? (S.dashNoSessions ? '<a class="btn" href="/research?new=1">Start a research session</a>' : '<a class="btn" href="/strategies">See passed strategies</a>')
        : `<a class="btn" href="/deploy">${onPaper ? 'See it on Deploy' : 'Go to Deploy'}</a>`;
      // Instant-fill paper trades are closed but left out (caveat below): "No closed paper trades" denied
      // trades the user can see on Deploy, so the heading says none count yet instead.
      const none = m.excluded_instant_fills ? `No ${esc(m.label.toLowerCase())} trades in the record yet` : `No closed ${esc(m.label.toLowerCase())} trades yet`;
      return `<div class="empty"><h3>${none}</h3><p>${how}</p>${key === 'paper' && !first ? apNudge('Rather not pick strategies yourself?', 'and it runs the ones that pass on paper. Their trades fill this record.') : ''}${go}</div>${cav}`;
    }
    const s = m.sample;
    const good = s.level === 'solid' && s.edge === 'positive';
    const figs = `<dl class="figures measure tr-figs">
      ${fig(`${trBook(key)} net P&amp;L`, usd(m.net_pnl, true), { v: m.net_pnl, cls: 'lead', small: `${key === 'paper' ? (m.first_trade_at ? gloSep('paperfills', `${PAPER_NET} (${usd(m.fees)} in fees)`) : gl(`${PAPER_NET} (${usd(m.fees)} in fees)`, 'paperfills')) : `after ${usd(m.fees)} in fees${m.first_trade_at ? SEP : ''}`}${m.first_trade_at ? `since ${trDay(m.first_trade_at)}` : ''}${key === 'paper' ? slipEst(m.slippage_estimate) : ''}` })}
      ${fig('Return', pct(m.return), { v: m.return, small: `on ${usd(m.capital)} capital required${trOver(m)}${m.annualized_return != null ? `${SEP}${pct(m.annualized_return)} a year` : ''}` })}
      ${fig('Max drawdown', m.max_drawdown ? usd(-m.max_drawdown) : usd(0), { small: m.max_drawdown_pct != null ? `${pct(m.max_drawdown_pct, false)} of capital` : '' })}
      ${fig('Sharpe', trFix(m.sharpe), { small: m.sharpe == null ? `shown after ${th.min_sharpe_days} days` : `PSR ${pct(m.psr, false)}${SEP}Sortino ${trFix(m.sortino)}` })}
      ${fig('Win rate', pct(m.win_rate, false), { small: trCi(m.win_rate_ci, (v) => pct(v, false)) })}
      ${fig('Trades', num(m.trades), { small: `${num(m.wins)} won${SEP}${num(m.losses)} lost` })}
      ${fig('Avg trade', usd(m.avg_trade, true), { v: m.avg_trade, small: trCi(m.avg_trade_ci, (v) => usd(v, true)) })}
      ${fig('Profit factor', trFix(m.profit_factor), { small: 'winning trades ÷ losing trades, after fees' })}
    </dl>`;
    const risk = `<dl class="kv tr-kv">
      <dt>Average win</dt><dd>${usd(m.avg_win, true)}</dd><dt>Average loss</dt><dd>${usd(m.avg_loss, true)}</dd>
      <dt>Best trade</dt><dd>${usd(m.best, true)}</dd><dt>Worst trade</dt><dd>${usd(m.worst, true)}</dd>
      <dt>Gross P&amp;L before fees</dt><dd>${usd(m.gross_pnl, true)}</dd><dt>Fees paid</dt><dd>${usd(m.fees)}</dd>
      <dt>Current drawdown</dt><dd>${m.current_drawdown ? usd(-m.current_drawdown) : 'At a high'}</dd>
      <dt>Longest drawdown</dt><dd>${trFix(m.longest_drawdown_days, 1)} days</dd>
      <dt>First trade</dt><dd>${trDay(m.first_trade_at)}</dd><dt>Calendar days (UTC)</dt><dd>${num(m.days)}</dd>
    </dl>`;
    // A month with no closes keeps its row (the server sends every month through this one), saying so
    // instead of a $0.00 that reads as if it traded flat.
    const months = m.monthly.map((r) => `<tr><td class="name" data-lab="Month">${esc(trMonth(r.month))}</td>
      <td class="num" data-lab="Net P&amp;L">${r.trades ? money(r.pnl) : '<span class="tr-none">No trades</span>'}</td><td class="num" data-lab="Trades">${num(r.trades)}</td>
      <td class="num" data-lab="Win rate">${r.trades ? pct(r.win_rate, false) : '\u2014'}</td></tr>`).join('');
    const strats = m.strategies.map((r) => {
      const [tag, cls] = r.instant_only ? ['Left out', 'quiet'] : TR_EDGE[r.edge] || TR_EDGE.unclear;
      // A removed or deleted strategy stays in the table (and every figure); it says so instead of
      // reading like one still trading. A deleted one has no page left to link to.
      const st = r.removed ? `${r.market ? `${esc(marketShort(r.market))}${SEP}` : ''}removed from ${esc(key)}, then deleted` : TR_STATUS[r.status] ? TR_STATUS[r.status](esc(key)) : '';
      return `<tr><td class="name" data-lab="Strategy">${r.removed ? esc(r.title) : `<a href="/strategies/${+r.strategy_id}">${esc(r.title)}</a>`}${st ? `<div class="sub-fig">${st}</div>` : ''}${trRowLeft(r)}</td>
        <td data-lab="Read"><span class="mk ${cls}">${tag}</span></td>
        <td class="num" data-lab="Trades">${num(r.trades)}${r.open_trades ? ` <span class="sub-fig">+${num(r.open_trades)} open</span>` : ''}</td>
        <td class="num" data-lab="Net P&amp;L">${r.instant_only ? '<span class="tr-none">Not in the record</span>' : money(r.net_pnl)}</td>
        <td class="num" data-lab="Win rate">${pct(r.win_rate, false)}</td>
        <td class="num" data-lab="Avg trade">${usd(r.avg_trade, true)}</td>
        <td class="num" data-lab="Max drawdown">${r.instant_only ? '\u2014' : r.max_drawdown ? usd(-r.max_drawdown) : usd(0)}</td>
        <td class="num" data-lab="Last trade">${trDay(r.last_trade_at)}</td></tr>`;
    }).join('');
    return `${notice(s.text, good ? 'good' : '')}${cav}${figs}
      <div class="rp-figs">
        <div class="rp-fig wide"><h3>Equity curve</h3>${equityChart(trCurve(m.curve), null, null, { width: chartWidth() })}<div class="cap">${trCurveCap(m)}</div></div>
        <div class="rp-fig"><h3>Drawdown (underwater)</h3>${rpUnderwater(trCurve(m.curve), m.underwater && trCurve(m.underwater))}</div>
        <div class="rp-fig"><h3>Risk and trade detail</h3>${risk}</div>
      </div>
      <section class="section"><div class="section-head"><h2>By month</h2><p>UTC calendar months</p></div>
        <div class="sheet"><table class="table stack"><thead><tr><th>Month</th><th class="num">Net P&amp;L</th><th class="num">Trades</th><th class="num">Win rate</th></tr></thead><tbody>${months}</tbody></table></div></section>
      <section class="section"><div class="section-head"><h2>By strategy</h2><p>Removed ones included${SEP}“Too few” means under ${th.min_trades} trades</p></div>
        <div class="sheet"><table class="table stack"><thead><tr><th>Strategy</th><th>Read</th><th class="num">Trades</th><th class="num">Net P&amp;L</th><th class="num">Win rate</th><th class="num">Avg trade</th><th class="num">Max drawdown</th><th class="num">Last trade</th></tr></thead><tbody>${strats}</tbody></table></div></section>`;
  }
  // Lives on the dashboard (Todd, 2026-10-25): its own request below the live board, so the 15s
  // dashboard poll never waits on it and never wipes it. The server caches it 60s per user.
  async function mountTrackRecord(host, last, pending) {
    const d = await (pending || api('/api/track-record', undefined, { keep: true }));
    if (!host.isConnected || (last && last.at === d.generated_at)) return;
    if (last) last.at = d.generated_at;
    let tab; try { tab = localStorage.getItem('tau_tr_tab'); } catch (e) { /* private mode */ }
    if (!d.modes[tab]) tab = d.default_mode;
    // When these figures were worked out, in the head where they are read: it sat at the foot of the closed method
    // note, so a record the minute poll could no longer refresh read as current. A failing poll says so under the tabs.
    host.innerHTML = `<div class="section-head"><h2>Track record</h2><p>Realized results from closed trades. Nothing here is a backtest. <span class="tr-asof">Figures as of ${esc(settleAt(new Date(d.generated_at * 1000).toISOString()))}</span></p></div>
      <div class="chips tr-tabs" role="group" aria-label="Money type">
        ${TR_MODES.map(([k, label]) => `<button class="chip" type="button" data-trtab="${k}" aria-pressed="${k === tab}">${label}${SEP}${num(d.modes[k].trades)}</button>`).join('')}
      </div>
      <p class="stale-note" id="tr-stale" role="status"></p>
      <div class="trpanel"></div>
      <details class="tr-method"><summary>How these numbers are computed</summary>
        <ul>${d.method.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>
        <p class="hint">Past results do not predict future returns.</p></details>`;
    const setTab = (t) => {
      host.querySelectorAll('[data-trtab]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.trtab === t)));
      host.querySelector('.trpanel').innerHTML = trackRecordPanel(d.modes[t], t, d.thresholds);
      // The empty paper record's copy depends on the autopilot switch; syncApCopy repaints it on a flip
      // (the record itself only repaints when the server's 60s cache moves, so it kept "Go to Deploy").
      trAp = { host, on: apSwitchOn(), repaint: () => setTab(t) };
      try { localStorage.setItem('tau_tr_tab', t); } catch (e) { /* private mode */ }
    };
    host.querySelectorAll('[data-trtab]').forEach((b) => (b.onclick = () => setTab(b.dataset.trtab)));
    setTab(tab);
  }
  async function dashTrackRecord(pending) {
    const gen = S.gen, mainEl = root.querySelector('#main'), wrap = mainEl && mainEl.parentNode;
    if (!wrap || !wrap.appendChild) return;
    const host = document.createElement('section');
    host.className = 'sect dash-track'; host.id = 'track-record'; host.innerHTML = loading(260);
    wrap.appendChild(host);  // after #main, the page's last child, so the board's repaint never touches it
    const last = { at: null };
    // A failed first read offers a retry; before, the record stayed an error until a reload.
    const first = async () => {
      const read = pending; pending = null;  // the view's own read once; a retry asks again
      try { await mountTrackRecord(host, last, read); } catch (e) {
        if (gen !== S.gen) return;
        host.innerHTML = loadFail(errText(e));
        host.querySelector('[data-retry]').onclick = () => { host.innerHTML = loading(260); return first(); };
        return;
      }
      if (gen !== S.gen) return;
      if (location.hash === '#track-record') host.scrollIntoView();
      S.trReread = () => mountTrackRecord(host, last).catch(() => {});  // the dashboard poll's re-read
      poll(() => mountTrackRecord(host, last), 60000, 'tr-stale');
    };
    await first();
  }

  // ---------- funds ----------
  // In app-funds.js, fetched on first use (page files, at the end of this file).
  function viewFunds() { return pageView('funds', 'viewFunds', '/funds', []); }

  // ---------- community ----------
  // In app-community.js, fetched on first use (page files, at the end of this file).
  function viewCommunity() { return pageView('community', 'viewCommunity', '/community', []); }

  // ---------- billing ----------
  function loadStripe() {
    return new Promise((res, rej) => {
      if (window.Stripe) return res(window.Stripe);
      const sc = document.createElement('script'); sc.src = 'https://js.stripe.com/v3/';
      sc.onload = () => res(window.Stripe); sc.onerror = () => rej(new Error('Could not load Stripe.'));
      document.head.appendChild(sc);
    });
  }
  // -- Explore + Hot Markets --------------------------------------------------
  const midOf = (m) => { const b = +m.bid, a = +m.ask; if (b > 0 && a > 0) return (b + a) / 2; const l = +m.last; return l > 0 ? l : null; };
  // Many markets share one event title (every strike of "Bitcoin price on Oct 14?"), so the
  // strike sub-title is what tells them apart.
  // The yes subtitle only when it adds something: "Minnesota wins · Minnesota" and "Will Bitcoin be
  // above $200000 by Jan 1…? · Above $200000" repeated the title. A contract the feed sends untitled is named
  // as a position is (contractName: its market's words, else "Kalshi contract"), never by its raw ticker.
  // A multi-game combo's title is Kalshi's legs run together ("yes Denver,yes Boston,no Over 220.5 points scored"): each
  // leg gets its space after the comma and the line starts with a capital, as every other title does. Any other title as sent.
  const comboTitle = (t) => /^(?:yes|no) [^,]+(?:,\s*(?:yes|no) [^,]+)+$/i.test(t) ? t.split(/,\s*/).join(', ').replace(/^./, (c) => c.toUpperCase()) : t;
  const mktLabel = (m) => { const t = comboTitle((m.ti || '').trim()), s = (m.su || '').trim(); return s && !t.toLowerCase().includes(s.toLowerCase()) ? (t ? `${t}${SEP}${s}` : s) : (t || contractName(m.t)); };
  const kalshiUrl = (m) => `https://kalshi.com/markets/${encodeURIComponent((m.s || '').toLowerCase())}`;
  const kfmt = (n) => { n = +n || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n)); };
  const sinceMin = (iso) => { if (!iso) return '—'; const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000); return s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + 'm ago' : s < 172800 ? Math.round(s / 3600) + 'h ago' : Math.round(s / 86400) + 'd ago'; };

  // A run past the reaper's limit (the server's run.wait / agent_wait / review_wait, timed on the
  // server so a reload doesn't restart the count) is said plainly instead of under a spinner.
  const waitSpan = (s) => { const m = Math.max(1, Math.floor((+s || 0) / 60)); return m < 90 ? m + ' min' : Math.round(m / 60) + ' hr'; };
  function runWaitLine(w) {
    const t = waitSpan(w.seconds);
    if (w.state === 'queued') {
      const ahead = +w.ahead || 0;
      return `Still waiting for a free research worker (${t}). ${ahead ? `${ahead === 1 ? '1 session is' : num(ahead) + ' sessions are'} ahead of it; it starts` : 'It’s next in line and starts'} when one frees up.`;
    }
    return `No word from the agent for ${t}. A session this quiet is normally interrupted and resumed from its last checkpoint.`;
  }

  function priceChart(points) {
    if (!points || points.length < 2) return '<div class="empty"><h3>Not enough history yet</h3><p>This market is new or thinly traded — its price curve fills in as it trades.</p></div>';
    // The SVG scales to its box, labels too: drawn 760 wide, a phone's ~320px chart shrank its 10.5px axis
    // labels to under 5px. On a phone it's drawn near the size it shows at, so the cents and times stay legible.
    const W = phone() ? 340 : 760, H = phone() ? 220 : 260, pl = 44, pr = 14, pt = 14, pb = 26, iw = W - pl - pr, ih = H - pt - pb;
    const ts = points.map((p) => p.t), t0 = Math.min(...ts), t1 = Math.max(...ts), tr = (t1 - t0) || 1;
    const x = (t) => pl + (t - t0) / tr * iw, y = (v) => pt + (1 - v) * ih;
    const grid = [0, .25, .5, .75, 1].map((v) => `<line x1="${pl}" y1="${y(v).toFixed(1)}" x2="${W - pr}" y2="${y(v).toFixed(1)}" class="pc-grid"/><text x="${pl - 8}" y="${(y(v) + 3).toFixed(1)}" class="pc-ylab">${Math.round(v * 100)}¢</text>`).join('');
    const line = points.map((p) => `${x(p.t).toFixed(1)},${y(p.yes).toFixed(1)}`).join(' ');
    // A chart within one day gets clock times (a 15-minute market read "10/26 … 10/26"), one over a few
    // days the date and clock, and the right-hand label names the reader's zone, as every time on the
    // market page does.
    const md = (t) => { const d = new Date(t * 1000); return `${d.getMonth() + 1}/${d.getDate()}`; };
    const fmt = new Date(t0 * 1000).toDateString() === new Date(t1 * 1000).toDateString() ? (t) => clock(t * 1000)
      : tr < 3 * 86400 ? (t) => `${md(t)} ${clock(t * 1000)}` : md;
    const zone = tzName();
    return `<svg class="pchart" viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Yes price history, ${esc(fmt(t0))} to ${esc(fmt(t1))}${zone ? ' ' + esc(zone) : ''}">${grid}<polyline points="${line}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><text x="${pl}" y="${H - 6}" class="pc-xlab">${fmt(t0)}</text><text x="${W - pr}" y="${H - 6}" class="pc-xlab" text-anchor="end">${fmt(t1)}${zone ? ' ' + esc(zone) : ''}</text></svg>`;
  }
  // Kalshi's market status in words: "active" read as jargon, and "finalized" never said it had settled.
  // Kalshi's settlement rules, shown as Kalshi wrote them but typeset: an apostrophe after a letter is curly
  // ("CF Benchmarks' index" read with a straight one), and a clock time keeps its AM/PM and zone ("before 5" ended
  // a line and "PM EDT" began the next). Words and figures are untouched.
  const rulesText = (t) => String(t || '').replace(/(\w)'/g, '$1\u2019').replace(/(\d) ([AP]M)\b/g, '$1\u00a0$2')
    .replace(/\b([AP]M) (E[SD]T|ET|C[SD]T|UTC)\b/g, '$1\u00a0$2');
  const MKT_STATUS = { initialized: 'Not open yet', unopened: 'Not open yet', active: 'Open for trading', open: 'Open for trading', paused: 'Trading paused', closed: 'Closed, result pending', determined: 'Result in, paying out', settled: 'Settled', finalized: 'Settled' };
  // The reader's own positions in this contract, one block per money book: paper, demo and live
  // money are never added into one figure. Each strategy links to its page.
  function marketMine(d) {
    if (d.mine == null) return '<p class="hint">Your positions in this market didn’t load. Reload the page to try again.</p>';
    const all = [...d.mine.open, ...d.mine.closed];
    if (!all.length) return '<p class="hint">None of your strategies holds or has traded this contract.</p>';
    const BOOK = { live: ['<span class="mk live">Live</span>', 'real money'], demo: ['<span class="mk dep">Demo</span>', 'Kalshi’s demo exchange, no real money'], paper: ['<span class="mk">Paper</span>', 'paper money, not real'] };
    return ['live', 'demo', 'paper'].map((mode) => {
      const xs = all.filter((p) => (p.mode || 'paper') === mode);
      if (!xs.length) return '';
      const op = xs.filter((p) => p.status === 'open'), cl = xs.filter((p) => p.status !== 'open');
      const marked = op.filter((p) => p.unrealized != null);
      const lastMark = marked.map((p) => p.mark_ts).filter(Boolean).sort().pop();
      const sum = [op.length ? `${op.length} open at cost + fees ${usd(op.reduce((a, p) => a + p.cost, 0))}${marked.length ? `${SEP}unrealized ${money(marked.reduce((a, p) => a + p.unrealized, 0))} (est. at the current bid${lastMark ? ', marked ' + when(lastMark) : ''})` : `${SEP}awaiting first mark`}` : '',
        cl.length ? `${cl.length} closed${SEP}realized ${money(cl.reduce((a, p) => a + (+p.pnl || 0), 0))}` : ''].filter(Boolean).join(SEP);
      const rows = xs.map((p) => `<tr><td class="name" data-lab="Strategy">${p.strategy_id && p.title ? `<a href="/strategies/${+p.strategy_id}">${esc(p.title)}</a>` : esc(p.title || 'Deleted strategy')}</td><td data-lab="Position">${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(+p.entry_price)}</td><td class="num" data-lab="Cost + fee">${usd(p.cost)}</td><td class="num" data-lab="${p.status === 'open' ? 'Unrealized' : 'Realized'}">${p.status === 'open' ? (p.unrealized == null ? NO_MARK : money(p.unrealized)) : money(+p.pnl || 0)}</td><td data-lab="Status">${p.status === 'open' ? `Open, settles ${settleAt(p.market_close_time)}` : `Closed (${esc(exitWord(p.close_reason))}) @ ${cents(+p.exit_price)}`}</td></tr>`).join('');
      return `<div class="mk-book"><p class="mk-book-h">${BOOK[mode][0]} ${BOOK[mode][1]}</p><p class="hint">${sum}</p><div class="sheet"><table class="table stack"><thead><tr><th>Strategy</th><th>Position</th><th class="num">Cost + fee</th><th class="num">P&amp;L</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
    }).join('');
  }
  // What to do next from a market page: research it (the market picked in the form) or open your
  // strategies on it, when it's one Tau researches; otherwise say so, rather than leave a dead end.
  // "Your <market> strategies" shows only when the server says the reader has one there (`my_markets`): it
  // showed to a reader with none, and opened an empty list.
  function marketNext(ticker, mine) {
    const m = contractMkt(ticker);
    // Another hour of a ladder Tau researches at one close (an hourly Bitcoin contract): point at that close.
    const sib = !m && ((S.me && S.me.markets) || []).find((x) => x.series && x.close_hour_et != null && String(ticker || '').startsWith(x.series + '-'));
    const h = sib && sib.close_hour_et;
    if (sib) return `<p class="hint mk-next">Tau researches only the ${hourET(h)} ET close of this ladder, so your strategies don’t trade this contract. <a href="/research?new=1&amp;market=${encodeURIComponent(sib.key)}">Research ${esc(marketShort(sib.key))}</a></p>`;
    if (!m) return '<p class="hint mk-next">Tau doesn’t research this market, so your strategies can’t trade it. <a href="/research?new=1">See the markets it researches</a></p>';
    const k = encodeURIComponent(m.key);
    const own = (mine || []).includes(m.key) ? `<a class="btn sm" href="/strategies?market=${k}">Your ${esc(marketShort(m.key))} strategies</a>` : '';
    return `<p class="mk-next"><a class="btn sm primary" href="/research?new=1&amp;market=${k}">Research ${esc(marketShort(m.key))}</a>${own}</p>`;
  }
  // A Bitcoin contract's page says where Bitcoin is against its strike, from the price the collectors
  // stored (/api/explore/spot). It is its own read, started with the market's, and fills its own section,
  // so a slow one never holds the page. An old price stays up and says how old it is.
  const BTC_CONTRACT = /^KXBTC(?:15M|D)?-./;
  // Spot and strikes to the cent: usd() rounds six figures to the dollar, which drew a $112,999.99 strike
  // as $113,000 beside a distance to it in cents.
  const btcUsd = (v) => '$' + fmt2.format(+v);
  // A 15-minute window's line is what Kalshi's own name for it calls it ("Target Price: $X"): its section, figure and
  // placeholder say "target price"; every other Bitcoin contract keeps "strike".
  const M15_CONTRACT = /^KXBTC15M-/;
  const spotSect = (ticker) => '<section class="sect" id="mk-spot"><div class="sect-head"><h2>Bitcoin vs the ' + (M15_CONTRACT.test(ticker || '') ? 'target price' : 'strike') + '</h2><p>Latest stored price, refreshed every 15s</p></div><div id="mk-spot-body"><p class="hint">Reading Bitcoin’s latest stored price…</p></div><p class="stale-note" id="mk-spot-stale" role="status"></p></section>';
  const spotAge = (s) => (s < 60 ? s + 's ago' : s < 5400 ? Math.round(s / 60) + ' min ago' : s < 172800 ? Math.round(s / 3600) + ' hr ago' : Math.round(s / 86400) + ' days ago');
  const spotOld = (s) => (s < 5400 ? Math.max(2, Math.round(s / 60)) + ' min' : s < 172800 ? Math.round(s / 3600) + ' hr' : Math.round(s / 86400) + ' days');
  const leftText = (s) => (s < 60 ? 'Under a minute' : s < 3600 ? Math.floor(s / 60) + ' min' : s < 172800 ? `${Math.floor(s / 3600)} hr ${Math.floor((s % 3600) / 60)} min` : Math.floor(s / 86400) + ' days');
  // A 15-minute window's start price is in the contract's own name ("Target Price: $113,512.08", the title line the
  // page heads with) before the collector stores its record: the section said "This window's start price isn't stored
  // yet" under that heading. With no stored strike it is read from there and says so; which side pays stays with
  // the rules, as for any strike read without its record. Spot is measured against it as the server measures a line.
  const TARGET_IN = /\btarget price:?\s*\$\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?/i;
  // A contract name's "Target Price: $113,512.08" stays on one line, label and amount together: the hot rail's
  // narrow column at 1280px ended a line on "Target Price:" with its amount on the next (or cut it off).
  // Takes escaped HTML and returns it with the phrase in a .nobr span, its space a no-break one.
  const glueTarget = (html) => String(html).replace(/\b(target price:?)\s+(\$\s*[\d,]+(?:\.\d+)?)/gi, '<span class="nobr">$1\u00a0$2</span>');
  function titleStrike(d) {
    const t = [d && d.sub, d && d.title].map((x) => TARGET_IN.exec(String(x || ''))).find(Boolean);
    const value = t ? +(t[1].replace(/,/g, '') + (t[2] || '')) : NaN;
    return value > 0 ? { kind: 'line', value, lo: null, hi: null, inclusive: false, from: 'title' } : null;
  }
  const lineVs = (price, value) => {
    const diff = Math.round((price - value) * 100) / 100;
    return { side: diff > 0 ? 'above' : diff < 0 ? 'below' : 'at', diff, pct: Math.round(diff / value * 1e5) / 1e3, yes: null };
  };
  function marketSpot(s, d) {
    const sp = s.spot && s.spot.price != null ? s.spot : null, stored = s.strike && s.strike.value != null ? s.strike : null;
    const k = stored || titleStrike(d);
    const m15 = M15_CONTRACT.test((d && d.ticker) || s.ticker || '');
    // A target read from the contract's title is named as the title and Explore's list name it: "target price".
    const line = m15 || (k && k.from === 'title') ? 'target price' : 'strike', Line = line[0].toUpperCase() + line.slice(1);
    const v = stored ? (s.vs && s.vs.side ? s.vs : null) : k && sp ? lineVs(+sp.price, k.value) : null;
    const bucket = k && k.kind === 'range', edges = bucket && k.lo != null && k.hi != null;
    const now = sp ? fig('Bitcoin now', btcUsd(sp.price), sp.stale ? { small: `Spot feed is ${spotOld(+sp.age_s || 0)} old`, cls: 'fig-behind' } : { small: `Coinbase${SEP}${spotAge(+sp.age_s || 0)}` })
      : fig('Bitcoin now', '—', { small: 'No stored price in the last day' });
    const strike = !k ? fig(Line, '—', { small: m15 ? 'This window’s start price isn’t stored yet' : 'Not stored for this contract' })
      : edges ? fig('Bucket', `${btcUsd(k.lo)} to ${btcUsd(k.hi)}`, { small: 'Yes if Bitcoin settles inside it' })
      : bucket ? fig('Bucket centre', btcUsd(k.value), { small: 'its edges aren’t stored' })
      : k.from === 'title' ? fig(Line, btcUsd(k.value), { small: 'Read from the contract’s title' })
      : fig(Line, btcUsd(k.value), { small: k.kind === 'above' || k.kind === 'below' ? `Yes if Bitcoin settles ${k.inclusive ? 'at or ' : ''}${k.kind}\u00a0it` : 'Kalshi’s rules say which side pays' });
    // Which side of the strike (or the bucket's edge it is outside of) spot is on, by how much, and which
    // side of the contract that is when the strike says.
    const where = !v ? '' : edges ? (v.side === 'below' ? 'below its floor' : 'above its top') : bucket ? v.side + ' its centre' : `${v.side} the ${line}`;
    const yes = v && v.yes === true ? 'on the Yes side' : v && v.yes === false ? 'on the No side' : '';
    // Measured from an old price, the label says so beside the figure, not only under Bitcoin's.
    const lab = (l) => (sp && sp.stale ? `${l}, ${spotAge(+sp.age_s || 0)}` : l);
    const vs = !v ? '' : v.side === 'inside' ? fig(lab('Spot vs bucket'), 'Inside', { small: `${usd(v.to_lo)} above its floor${SEP}${usd(v.to_hi)} below its top${SEP}on the Yes side` })
      : v.side === 'at' ? fig(lab('Spot vs ' + line), 'At the ' + line, { small: yes })
      : fig(lab(edges ? 'Spot vs bucket' : bucket ? 'Spot vs centre' : 'Spot vs ' + line), usd(v.diff, true), { small: [`${Math.abs(+v.pct || 0).toFixed(2)}% ${where}`, yes].filter(Boolean).join(SEP) });
    const left = s.secs_left == null ? fig('Time left', '—') : fig('Time left', s.secs_left > 0 ? leftText(s.secs_left) : 'Closed', { small: s.close_time ? 'closes ' + keepZone(settleAt(s.close_time)) : '' });
    return `<dl class="figures measure">${now}${strike}${vs}${left}</dl><p class="hint mk-spot-note">Kalshi settles on the CF Benchmarks Bitcoin index averaged over the last minute before the close; Coinbase’s price usually sits within a few dollars of it.</p>`;
  }
  function mountSpot(ticker, first, d) {
    const path = '/api/explore/spot?ticker=' + encodeURIComponent(ticker);
    const show = (s) => {
      const el = root.querySelector('#mk-spot-body');
      if (!el) return;
      el.innerHTML = s.failed ? `<p class="hint">${esc(s.failed)} <button class="btn sm" type="button" data-spot-retry>Try again</button></p>` : marketSpot(s, d);
      const b = el.querySelector('[data-spot-retry]');
      if (b) b.onclick = () => spotRead(ticker).then(show);
    };
    first.then(show);
    // One poll per page, though a retry of the market draws the page again; a failed poll keeps the last figures.
    // Those figures carry the age Tau read them at ("Coinbase · 12s ago"), which stood still while the poll
    // failed: once it has failed for about two polls, a line under them says how old they really are.
    if (S.spotPoll !== S.gen) { S.spotPoll = S.gen; poll((cfg) => api(path, undefined, cfg).then(show), 15000, 'mk-spot-stale'); }
  }
  const spotRead = (ticker) => api('/api/explore/spot?ticker=' + encodeURIComponent(ticker)).catch((e) => ({ failed: errText(e) }));
  const MKT_GONE = 'Kalshi has no market at this link. It may have been taken down, or the link is incomplete. Find it again on Explore.';
  async function viewMarketDetail(ticker) {
    shell('/explore', boardTitle('Market'), loading(300));
    const spotReq = BTC_CONTRACT.test(ticker || '') ? spotRead(ticker) : null;
    let d;
    try { d = await api('/api/explore/market?ticker=' + encodeURIComponent(ticker)); }
    catch (e) {
      // A market Kalshi doesn't have (404) won't come back on a retry: it says so in words, without the raw code
      // from the link ("Kalshi has no market KXNOPE-…"), and offers only the way back to Explore.
      const gone = e.status === 404;
      root.querySelector('#main').innerHTML = notice(gone ? MKT_GONE : e.message, 'bad') + `<p style="margin-top:12px">${gone ? '' : '<button class="btn sm" type="button" id="mk-retry">Try again</button> '}<a class="btn sm" href="/explore">← Back to Explore</a></p>`;
      if (!gone) root.querySelector('#mk-retry').onclick = () => viewMarketDetail(ticker);
      return;
    }
    const mid = midOf({ bid: d.yes_bid, ask: d.yes_ask, last: d.last });
    const label = mktLabel({ ti: d.title, su: d.sub, t: d.ticker });
    const gran = d.period_min >= 1440 ? 'daily' : d.period_min >= 60 ? 'hourly' : 'per-minute';
    // Kalshi's "candles" are a trader's word: the chart says how often it has a price ("A price each minute").
    const GRAN_EACH = { daily: 'A price each day', hourly: 'A price each hour', 'per-minute': 'A price each minute' };
    const fmtT = (t) => new Date(t * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    // The price says what it is (a Yes pays $1, so 42¢ is about a 42% chance), the book it comes from,
    // and when it was read; the Explore feed's snapshot (Kalshi unreachable) says how old it is.
    const bid = +d.yes_bid, ask = +d.yes_ask;
    const priceSub = [mid == null ? '' : `≈\u00a0${Math.round(mid * 100)}% chance of Yes`, bid > 0 && ask > 0 ? `bid\u00a0${cents(bid)}\u00a0/ ask\u00a0${cents(ask)}` : '',
      d.as_of ? (d.snapshot ? `Explore snapshot, ${sinceMin(d.as_of)}` : `as\u00a0of\u00a0${keepZone(settleAt(d.as_of))}`) : ''].filter(Boolean).join(SEP);
    const settled = d.result === 'yes' || d.result === 'no';
    const kalshiLink = `https://kalshi.com/markets/${encodeURIComponent((d.series || '').toLowerCase())}`;
    // The line under the name says what the code is, as a position does (kalshiRef): "Kalshi contract KX…", not a bare ticker.
    shell('/explore', boardTitle(label, esc([contractMarket(d.ticker), MKT_STATUS[d.status] || d.status || 'Market'].filter(Boolean).join(SEP)) + (d.ticker ? SEP + kalshiRef(d.ticker) : '')) +
      '<dl class="figures measure" style="margin-top:14px">' +
        (settled ? fig('Result', d.result === 'yes' ? 'Yes' : 'No', { small: d.result === 'yes' ? 'each Yes contract paid $1' : 'each No contract paid $1' })
          : fig('Yes price', mid == null ? '—' : cents(mid), { small: priceSub })) + fig('24h volume', num(Math.round(+d.volume_24h || 0)), { small: 'contracts traded' }) +
        fig('Open interest', num(Math.round(+d.open_interest || 0)), { small: 'contracts held' }) + fig('Closes', keepZone(settleAt(d.close_time))) + '</dl>' + marketNext(d.ticker, d.my_markets), `${spotReq && !settled ? spotSect(d.ticker || ticker) : ''}
      <section class="sect"><div class="sect-head"><h2>Your positions here</h2><p>Each money book on its own</p></div>${marketMine(d)}</section>
      <section class="sect"><div class="sect-head"><h2>How it settles</h2><p>${d.settles_at ? `Result expected ${settleAt(d.settles_at)}` : 'Kalshi’s rules'}</p></div>
        ${d.rules ? `<p class="mk-rules">${esc(rulesText(d.rules))}</p>${d.rules_more ? `<p class="hint mk-rules">${esc(rulesText(d.rules_more))}</p>` : ''}`
          : `<p class="hint mk-rules">Kalshi’s settlement rules didn’t come with this snapshot. <a href="${kalshiLink}" target="_blank" rel="noopener">Read them on Kalshi ↗</a></p>`}</section>
      <section class="sect"><div class="sect-head"><h2>Price history</h2><p>Yes price${d.history_unavailable ? '' : `${SEP}${GRAN_EACH[gran]}, from Kalshi`}</p></div>
        <div class="pchart-wrap">${d.history_unavailable
          ? '<div class="empty"><h3>Price history didn’t load</h3><p>Kalshi didn’t send it just now. The figures above are from the latest market snapshot.</p><button class="btn sm" type="button" id="mk-retry">Try again</button></div>'
          : priceChart(d.points)}</div></section>
      <section class="sect"><div class="sect-head"><h2>Raw data</h2><p>${d.history_unavailable ? 'Not loaded' : `${num(d.points.length)} ${gran} points${d.points.length ? `${SEP}newest first` : ''}`}</p></div>
        <div id="rawsect"></div></section>
      <div class="xpage"><a class="btn sm" href="/explore">← Back to Explore</a>
        <span class="xpage-acts"><button class="btn sm" id="dl-csv" ${d.points.length ? '' : 'disabled'}>Download CSV</button>
        <a class="btn sm" href="${kalshiLink}" target="_blank" rel="noopener">View on Kalshi ↗</a></span></div>`);
    const retry = root.querySelector('#mk-retry');
    if (retry) retry.onclick = () => viewMarketDetail(ticker);
    if (spotReq && !settled) mountSpot(ticker, spotReq, d);
    const pts = d.points.slice().reverse();  // newest first
    const PER = 25; let pg = 0;
    const rawEl = root.querySelector('#rawsect');
    const renderRaw = () => {
      if (!pts.length) { rawEl.innerHTML = `<div class="empty"><p>${d.history_unavailable ? 'None to show: Kalshi didn’t send this market’s price history just now. Try again under Price history.' : 'Kalshi has no price history for this market yet.'}</p></div>`; return; }
      const pages = Math.max(1, Math.ceil(pts.length / PER));
      const rows = pts.slice(pg * PER, (pg + 1) * PER).map((p) => `<tr><td class="tick">${fmtT(p.t)}</td><td class="num">${cents(p.yes)}</td><td class="num">${num(Math.round(p.vol || 0))}</td></tr>`).join('');
      rawEl.innerHTML = `<div class="sheet"><table><thead><tr><th>Time (${esc(tzName() || 'local')})</th><th class="num">Yes price</th><th class="num">Volume</th></tr></thead><tbody>${rows}</tbody></table></div>
        <div class="xpage">${pg > 0 ? `<button class="btn sm" data-rp="${pg - 1}">← Prev</button>` : '<span></span>'}<span class="lab">Page ${pg + 1} of ${num(pages)}${SEP}${num(pts.length)} points</span>${pg + 1 < pages ? `<button class="btn sm" data-rp="${pg + 1}">Next →</button>` : '<span></span>'}</div>`;
      rawEl.querySelectorAll('[data-rp]').forEach((b) => b.onclick = () => { pg = +b.dataset.rp; renderRaw(); window.scrollTo({ top: rawEl.offsetTop - 80, behavior: smooth() }); });
    };
    renderRaw();
    const dl = root.querySelector('#dl-csv');
    if (dl) dl.onclick = () => {
      const csv = 'time_utc,unix_ts,yes_price,volume\n' + d.points.map((p) => `${new Date(p.t * 1000).toISOString()},${p.t},${p.yes},${Math.round(p.vol || 0)}`).join('\n');
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
      const a = document.createElement('a'); a.href = url; a.download = `${d.ticker}.csv`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
  }

  // Explore's rows and the hot rail say how far stored Bitcoin is from a contract's strike (the server's `vs`,
  // from one shared spot read): "+$420 · 0.4%" is spot $420 (0.4%) above it, a bucket's is to its nearer
  // edge, and a bucket spot sits in reads "in range". Without a fresh spot no row carries one, and the line
  // above the list says why (spotListNote).
  // A 15-minute window's row measures from the target price in its own name, the one its market page shows
  // (titleStrike) until a strike is stored; the server says so (`vs.from`), and the row names it the same way.
  const VS_TITLE = 'Target price from the contract’s title, as on its market page';
  // A 15-minute window's line is its target price whether it was read from the title or stored (M15_CONTRACT, as
  // its market page says it): a stored one read "Spot vs strike" on Explore beside "Target price" on its page.
  const vsTarget = (m) => !!((m.vs && m.vs.from === 'title') || M15_CONTRACT.test(m.t || ''));
  const vsText = (v, m) => (v.side === 'inside' ? 'in range' : v.side === 'at' ? (vsTarget(m || { vs: v }) ? 'at the target price' : 'at the strike')
    : `${+v.diff < 0 ? '−' : '+'}${WJ}$${num(Math.round(Math.abs(+v.diff)))}${SEP}${Math.abs(+v.pct || 0).toFixed(Math.abs(+v.pct || 0) < 0.1 ? 2 : 1)}%`);
  const vsLab = (m) => (vsTarget(m) ? 'Spot vs target price' : /^KXBTC-.+-B[\d.]+$/.test(m.t) ? 'Spot vs bucket' : 'Spot vs strike');
  const vsHtml = (m) => (m.vs ? `<span class="xspot"${m.vs.from === 'title' ? ` title="${VS_TITLE}"` : ''}>${vsLab(m)} <b>${vsText(m.vs, m)}</b></span>` : '');
  // The line names what the rows shown measure from: a list of 15-minute windows only said "Distances to the strike"
  // over rows that each said "target price". Both kinds on one list name both. The rows with a figure count; with
  // no figure to show (an old or missing spot), the Bitcoin rows that would have one: a 15-minute window's only with
  // the target in its name (TARGET_IN), as the server reads it when no strike is stored.
  const spotFrom = (ms) => {
    const all = ms || [], vs = all.filter((m) => m.vs);
    const btc = vs.length ? vs : all.filter((m) => BTC_CONTRACT.test(m.t || '') && (!M15_CONTRACT.test(m.t) || TARGET_IN.test(`${m.su || ''} ${m.ti || ''}`)));
    const m15 = btc.filter(vsTarget).length;
    return !m15 ? 'the strike' : m15 === btc.length ? 'the target price' : 'the strike or target price';
  };
  const spotListNote = (s, ms) => {
    if (s === undefined) return '';
    const to = 'distances to ' + spotFrom(ms);
    return s && s.failed ? `Bitcoin’s latest stored price didn’t load, so ${to} are left out.`
      : !s ? `No Bitcoin price stored in the last day, so ${to} are left out.`
      : s.stale ? `Bitcoin’s spot feed is ${spotOld(+s.age_s || 0)} old, so ${to} are left out until it catches up.`
      : `${to.charAt(0).toUpperCase() + to.slice(1)} are from Bitcoin at ${btcUsd(s.price)} (Coinbase, ${spotAge(+s.age_s || 0)}).`;
  };

  // Explore's empty and failed states: what happened, and a way to ask again. Each sits directly under the
  // page's h1, so its heading is an h2 (styled as the other empty states' h3).
  const EXPLORE_WAIT = 'The market list refreshes about once a minute and hasn’t come in yet. Try again shortly.';
  // Explore's list polls every 15s. The feed itself moves about once a minute; the 15s is for the Bitcoin rows'
  // distance to spot, which the collector stores every 20s. The server answers from its cached feed and one spot
  // read shared by every reader for 5s (about 2ms a call, never a Kalshi call), as fast as the market page's spot.
  const EXPLORE_POLL_MS = 15000;
  // Before the server's first copy of the market feed there is no list and no time: "Markets tracked 0" read
  // as Kalshi having no markets. The figures say the feed hasn't come in yet instead.
  const exploreNoFeed = (d) => !d.at && !+d.total;
  const EXPLORE_NO_FEED = fig('Market feed', 'Not in yet', { small: 'the market list arrives about once a minute' });
  const exploreEmpty = (title, text) => `<div class="empty"><h2>${esc(title)}</h2><p>${esc(text)}</p><button class="btn sm" type="button" data-xretry>Try again</button></div>`;
  async function viewExplore() {
    const q = new URLSearchParams(location.search);
    if (q.get('m')) return viewMarketDetail(q.get('m'));
    const f = { q: q.get('q') || '', sort: ['v24', 'oi', 'last'].includes(q.get('sort')) ? q.get('sort') : 'v24', page: Math.max(0, +(q.get('page') || 0)) };
    shell('/explore', boardTitle('Explore', 'Every market Tau is tracking right now, across crypto, politics, sports, weather and more, hottest first. Prices refresh each minute.') +
      '<dl class="figures measure" id="xfigs" style="margin-top:14px"></dl><p class="stale-note" id="xstale" role="status"></p>', `
      <div class="section-head filters">
        <label class="field xsearch" style="margin:0"><span class="vh">Search markets</span>
          <input class="input" id="xq" type="search" placeholder="Search markets" value="${esc(f.q)}" autocomplete="off"></label>
        <div class="chips" role="group" aria-label="Sort by">${[['v24', 'Hottest'], ['oi', 'Open interest'], ['last', 'Price']].map(([v, l]) => `<button class="chip" data-sort="${v}" aria-pressed="${f.sort === v}">${l}</button>`).join('')}</div>
      </div>
      <div id="xbody" style="margin-top:16px">${loading(240)}</div>`);
    const body = root.querySelector('#xbody'), figs = root.querySelector('#xfigs');
    const sync = () => history.replaceState(null, '', '/explore?' + new URLSearchParams({ q: f.q, sort: f.sort, page: String(f.page) }));
    // "Live now" was the hottest markets the list carries, not what's live; Matching shows only when a
    // search narrows the list. The list refreshes each minute, so an older one says it's behind.
    const figsHtml = (d) => {
      if (exploreNoFeed(d)) return EXPLORE_NO_FEED;
      const atMs = Date.parse(d.at || ''), behind = Number.isFinite(atMs) && Date.now() - atMs > 180000;
      return fig('Markets tracked', num(d.total)) + fig('In this list', num(d.shown), { small: 'the most traded' }) + (f.q ? fig('Matching', num(d.matched)) : '') +
        fig('Prices updated', sinceMin(d.at), behind ? { small: 'Behind: prices normally refresh each minute', cls: 'fig-behind' } : {});
    };
    // The list stays current while it shows (EXPLORE_POLL_MS, paused while the tab is hidden, read at once on
    // coming back to it). A poll (`cfg`) rewrites only the rows that moved, so scroll, focus, the search box and
    // the sort stay as they are. A failed poll keeps the list up with its age counting on, and past two polls
    // the line under the figures says how old it is. Only the newest read draws: a poll answering after a
    // search doesn't put the old list back.
    let seq = 0, shown = null;
    const load = async (cfg) => {
      const mine = ++seq;
      let d;
      try { d = await api('/api/explore?' + new URLSearchParams({ q: f.q, sort: f.sort, page: String(f.page) }), undefined, cfg); }
      catch (e) {
        if (mine !== seq) return;
        if (cfg) { if (shown) paint(figs, figsHtml(shown)); throw e; }
        shown = null; paint(body, exploreEmpty('Markets didn’t load', e.message)); body.querySelector('[data-xretry]').onclick = () => load(); return;
      }
      if (mine !== seq) return;
      paint(figs, figsHtml(d));
      if (!d.markets.length) {
        // No search and no markets is the feed not having arrived yet, not a search that missed.
        shown = null;
        if (f.q) paint(body, `<div class="empty"><h2>No markets match “${esc(f.q)}”</h2><p>Try a broader search, or clear it to see the hottest markets.</p></div>`);
        else { paint(body, exploreEmpty('No markets to show yet', EXPLORE_WAIT)); body.querySelector('[data-xretry]').onclick = () => load(); }
        return;
      }
      shown = d;
      const rows = d.markets.map((m) => {
        const mid = midOf(m);
        // The market as the app names it and when the contract closes (`ct`, read from a timed event's
        // ticker), never the raw event key: that's what tells "every strike of Bitcoin at 5pm" apart from
        // the next hour's ladder, and a 15-minute contract from the one after it.
        // Each piece holds together, so the chip breaks only after its "·": at 390px "UTC" sat alone on a line.
        const tag = [contractShort(m.t), m.ct ? 'closes ' + settleAt(m.ct) : ''].filter(Boolean).map((x) => `<span class="nobr">${esc(x)}</span>`).join(SEP);
        return [m.t, `<tr><td class="name"><a href="/explore?m=${encodeURIComponent(m.t)}">${esc(mktLabel(m))}</a>${tag ? ` <span class="mk quiet">${tag}</span>` : ''}${vsHtml(m)}</td>
          <td class="num" data-lab="Yes price">${mid == null ? '—' : cents(mid)}</td><td class="num" data-lab="24h volume">${num(Math.round(+m.v24 || 0))}</td><td class="num" data-lab="Open interest">${num(Math.round(+m.oi || 0))}</td>
          <td class="num xlink" data-lab="Kalshi"><a href="${kalshiUrl(m)}" target="_blank" rel="noopener" aria-label="Open on Kalshi">${ICON.ext}</a></td></tr>`];
      });
      const pages = Math.max(1, Math.ceil(d.matched / d.per)), note = spotListNote(d.spot, d.markets);
      keepFocus(body, () => {
        paint(body, '<div id="xnote"></div><div class="sheet"><table class="stack t-explore"><thead><tr><th>Market</th><th class="num">Yes price</th><th class="num">24h volume</th><th class="num">Open interest</th><th class="num" aria-label="Link"></th></tr></thead><tbody id="xrows"></tbody></table></div><div id="xpager"></div>');
        paint(body.querySelector('#xnote'), note ? `<p class="hint xspot-note${d.spot && !d.spot.stale && !d.spot.failed ? '' : ' behind'}">${esc(note)}</p>` : '');
        paintRows(body.querySelector('#xrows'), rows);
        paint(body.querySelector('#xpager'), pages > 1 ? `<div class="xpage">${f.page > 0 ? `<button class="btn sm" data-pg="${f.page - 1}">${ICON.up ? '' : ''}← Prev</button>` : '<span></span>'}<span class="lab">Page ${f.page + 1} of ${num(pages)}</span>${f.page + 1 < pages ? `<button class="btn sm" data-pg="${f.page + 1}">Next →</button>` : '<span></span>'}</div>` : '');
      });
      body.querySelectorAll('[data-pg]').forEach((b) => b.onclick = () => { f.page = +b.dataset.pg; sync(); window.scrollTo({ top: 0, behavior: smooth() }); load(); });
    };
    let t; root.querySelector('#xq').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); f.page = 0; sync(); load(); }, 220); });
    root.querySelectorAll('[data-sort]').forEach((b) => b.onclick = () => { f.sort = b.dataset.sort; f.page = 0; root.querySelectorAll('[data-sort]').forEach((o) => o.setAttribute('aria-pressed', o === b)); sync(); load(); });
    await load();
    poll(load, EXPLORE_POLL_MS, 'xstale');
  }

  // Hot Markets left rail: persistent (open/closed survives page switches), refreshes every 30s while it shows.
  // A rail whose reads fail keeps its rows, and once they are two reads old it says how old ("Last updated 1m
  // ago, retrying"), where it kept them with no word.
  const HOT_POLL_MS = 30000;
  const hotStaleText = () => (S.hot && S.hotFail && S.hotAt && Date.now() - S.hotAt > staleAfter(HOT_POLL_MS) ? staleText(S.hotAt) : '');
  // On a phone the rail is hidden (Explore covers it): an open rail would cover the whole page.
  const hotOpen = () => !phone() && localStorage.getItem('tau_hotrail') !== '0';
  const hotShown = () => !phone();  // app.css hides the rail under 761px, the width phone() asks
  let hotLoop = false, hotMoving = 0;
  let apLoop = false, apReq = null;

  // ---------- floating autopilot window ----------
  const apExpanded = () => localStorage.getItem('tau_ap_open') === '1';
  function mountAutopilot() {
    if (!S.me || !S.me.user) return;
    let box = document.getElementById('autopilot-float');
    if (!box) { box = document.createElement('div'); box.id = 'autopilot-float'; box.className = 'apf'; document.body.appendChild(box); }
    renderAutopilot(box, S.ap);
    const stale = !S.ap || !S.apAt || Date.now() - S.apAt > 18000;
    if (stale) refreshAutopilot(box, true);
    if (!apLoop) {
      // Background tabs don't poll (each status read is ~14 queries); coming back refreshes a stale one.
      apLoop = true;
      const tick = paced((cfg) => refreshAutopilot(document.getElementById('autopilot-float'), false, cfg).then((ok) => { if (!ok) throw new Error('Autopilot status read failed'); }), 20000, apPaintStale);
      setInterval(() => { if (document.getElementById('autopilot-float') && !document.hidden) tick(); }, 20000);
      wakers.add(() => { if (document.getElementById('autopilot-float') && !document.hidden) tick(true); });
      document.addEventListener('visibilitychange', () => {
        const b = document.getElementById('autopilot-float');
        if (b && !document.hidden && (!S.apAt || Date.now() - S.apAt > 18000)) refreshAutopilot(b, true);
      });
      // Re-check the pill against the page's buttons once a frame at most, as the page moves under it.
      addEventListener('scroll', yieldSoon, { passive: true }); addEventListener('resize', yieldSoon);
      document.addEventListener('toggle', yieldSoon, true); document.addEventListener('input', yieldSoon, true);
      // Tabbing onto a stepped-aside pill brings it back (apYield keeps a focused pill shown).
      document.addEventListener('focusin', yieldSoon, true); document.addEventListener('focusout', yieldSoon, true);
      // The page also moves under a still pill when it paints (the dashboard's figures land after the shell).
      if (typeof MutationObserver === 'function') new MutationObserver(yieldSoon).observe(document.body, { childList: true, subtree: true });
    }
  }
  // Resolves true when the status read landed. The loop backs off on false; other callers ignore it.
  // The status never waits on Kalshi: an idle line that needs the demo cash comes idle_pending, and is read
  // again once that cash is back (demoCashRead), once (`afterDemo`); a check still pending waits for the poll.
  async function refreshAutopilot(box, share = false, cfg, afterDemo) {
    // Pages that paint the shell twice (instant switch, then content) share one in-flight read;
    // a refresh after a change always reads fresh.
    let req = share && apReq;
    if (!req) { req = apReq = api('/api/autopilot/status', undefined, { keep: true, ...cfg }); req.finally(() => { if (apReq === req) apReq = null; }).catch(() => {}); }
    try {
      S.ap = await req; S.apAt = Date.now(); S.apFailing = false;
      // The status read is the switch's truth (another tab or device may have flipped it); copy that
      // reads S.me.user.autopilot, like the empty paper track record, follows it through syncApCopy.
      if (S.me && S.me.user && typeof S.ap.autopilot === 'boolean') S.me.user.autopilot = S.ap.autopilot;
      renderAutopilot(box, S.ap); paintDashAp(); bellTick();
      if (S.ap.idle_pending && !afterDemo) demoCashRead().then(() => refreshAutopilot(document.getElementById('autopilot-float'), false, undefined, true));
    }
    catch (e) { S.apFailing = true; apPaintStale(); return false; }  // best-effort: never block the app
    return true;
  }
  // The autopilot's figures (the panel's and the dashboard card's) say how old they are once its
  // status read has been failing for about two polls; the next good read clears it.
  const apStale = () => S.apFailing && S.apAt && Date.now() - S.apAt > staleAfter(20000) ? staleText(S.apAt) : '';
  function apPaintStale() {
    const text = apStale();
    ['apf-stale', 'dash-ap-stale'].forEach((id) => { const el = document.getElementById(id); if (el) el.textContent = text; });
  }
  // Demo P&L restarts at a reload (before_reload holds what came before), unlike the track record.
  function demoSpan(dm) { return dm && dm.before_reload ? 'since reload' : 'all time'; }

  // An action as a link: the server's {label, href}. One off the site opens in a new tab and says so.
  function actionLink(h) {
    const a = h && h.action;
    if (!a || !a.href) return '';
    const ext = /^https?:\/\//.test(a.href);
    return ` <a href="${esc(a.href)}"${ext ? ' target="_blank" rel="noopener"' : ''}>${esc(a.label)}${ext ? ' \u2197' : ''}</a>`;
  }
  // Why the demo book can't trade (the server's demo health: no demo key, or a Kalshi demo account too
  // empty for one order), as one plain line and the one thing to do. A running demo book with capital
  // and a P&L looks healthy while Kalshi refuses every order it sends, so this goes where demo shows.
  // "Since your last visit" on the dashboard. The boundary lives in a cookie, tau_visit=<since>.<seen>
  // (epoch seconds): dashboard opens less than 30 minutes apart are one visit, and a new visit starts
  // where the last one was last seen. No cookie yet (first visit on this device): since is 0 and the
  // server answers for the last 24 hours.
  const VISIT_GAP = 1800;
  function visitCookie() {
    try { const m = /(?:^|;\s*)tau_visit=(\d+)\.(\d+)/.exec(String(document.cookie || '')); return m ? [+m[1], +m[2]] : null; } catch (e) { return null; }
  }
  function setVisit(since, seen) {
    try { document.cookie = `tau_visit=${since || 0}.${seen}; path=/; max-age=7776000; SameSite=Lax`; } catch (e) { /* cookies blocked */ }
  }
  function visitStart() {
    const now = Math.floor(Date.now() / 1000), c = visitCookie();
    const at = !c ? null : now - c[1] > VISIT_GAP ? c[1] : (c[0] || null);
    setVisit(at, now);
    return at;
  }
  // The strip itself, from /api/dashboard's `since` block and the page's own deployments: each book's
  // realized P&L (never added together), what passed, what the autopilot changed, and what needs the
  // user, linking to it. `pausedHref` is where this page lists its paused deployments.
  const AP_DID = [['deploy', 'put %s on paper'], ['pause', 'paused %s'], ['resume', 'resumed %s'], ['stop', 'removed %s'], ['adjust', 'adjusted %s'], ['research', 'started %s']];
  const CREDITS_WARN_DAYS = 3;  // the strip warns when credits last fewer days than this (server: CREDIT_RUNWAY_WARN_DAYS)
  // A deployment's pause reason, short: no "Autopilot:" prefix, no closing period, cut at a word.
  const shortReason = (r) => {
    const s = String(r).replace(/^Autopilot:\s*/, '').replace(/\.\s*$/, '');
    return clipWords(s, 110);
  };
  // The strip's Autopilot row when it made no moves: just the switch, which syncApCopy keeps current.
  // Its newest move being the switch itself (the status read's last_action) means it was switched on and
  // has made no move yet: "On. It made no changes." read as a dud the moment the switch was pressed.
  const sinceApWord = (on) => {
    if (!on) return 'Off.';
    const la = S.ap && S.ap.autopilot ? S.ap.last_action : null;
    return la && la.at && apMoveText(la) === 'Autopilot switched on'
      ? `Switched on ${sinceMin(la.at)}. Its moves show up here as it makes them.` : 'On. It made no changes.';
  };
  // Where the sessions counted in "N research sessions started" are now (the server sends {status: n}),
  // so a session still queued isn't offered as if its ideas had been judged: "still queued", "all
  // running", "1 running, 2 finished". `point` (nothing passed) adds the link: what each idea missed
  // once any finished, else where to follow them.
  const SINCE_RUN_STATES = [['queued', 'queued'], ['running', 'running'], ['paused', 'paused'], ['succeeded', 'finished'], ['failed', 'failed'], ['stopped', 'stopped']];
  function sinceRunsState(runs, started, point) {
    const n = (k) => k === 'stopped' ? (runs.stopped || 0) + (runs.cancelled || 0) : runs[k] || 0;
    const known = SINCE_RUN_STATES.reduce((a, [k]) => a + n(k), 0);
    const parts = SINCE_RUN_STATES.filter(([k]) => n(k)).map(([k, w]) => [n(k), w]);
    if (started > known) parts.push([started - known, 'finished']);  // a status this list doesn't know has ended
    const solo = parts.length === 1 && parts[0][1];
    const state = solo ? (started === 1 ? (['queued', 'running'].includes(solo) ? 'still ' + solo : solo) : 'all ' + solo)
      : parts.map(([c, w]) => `${num(c)} ${w}`).join(', ');
    if (!point) return state;
    return state + (n('succeeded') ? ', <a href="/research">see what each idea missed</a>'
      : n('queued') || n('running') || n('paused') ? `, <a href="/research">follow ${started === 1 ? 'it' : 'them'} on Research</a>` : '');
  }
  // Each book's since-visit figure split by the strategy that traded it (the server's by_deployment, the
  // same rows, best first), shown for a book where two or more traded: "Paper −$24.19" alone hid that the
  // running strategy made money and the paused one lost it. Each share stays inside its own book.
  const SINCE_SPLIT_SHOWN = 3;
  function sinceSplit(d, books) {
    const by = (d.since && d.since.by_deployment) || {};
    return books.map(([m, label]) => {
      const rows = Array.isArray(by[m]) ? by[m] : [];
      if (rows.length < 2) return '';
      const item = (r) => {
        const dep = (d.deployments || []).find((x) => +x.id === +r.deployment_id);
        // A removed deployment isn't listed: the server names its strategy (title null once that was deleted too).
        const name = dep ? `<a href="/strategies/${encodeURIComponent(dep.strategy_id)}">${esc(dep.title)}</a>`
          : r.removed && r.title ? `<a href="/strategies/${encodeURIComponent(r.strategy_id)}">${esc(r.title)}</a> <span class="since-sub">(removed deployment)</span>`
          : r.removed ? 'a deleted strategy' : 'a removed strategy';
        const p = +r.pnl || 0;
        return `${name} <span class="nobr"><span class="${p < 0 ? 'neg' : p > 0 ? 'pos' : ''}">${usd(p, true)}</span> on ${num(r.trades)}</span>`;
      };
      const more = rows.length - SINCE_SPLIT_SHOWN;
      return `<div class="since-split" data-book="${m}">${books.length > 1 ? `<span class="since-sub">${label}:</span> ` : ''}${rows.slice(0, SINCE_SPLIT_SHOWN).map(item).join('<span class="sep">·</span>')}${more > 0 ? `<span class="sep">·</span><span class="since-sub">${num(more)} more</span>` : ''}</div>`;
    }).join('');
  }
  function sinceStrip(d, pausedHref) {
    const s = d.since;
    if (!s) return '';
    const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : many}`;
    const books = [['live', 'Live'], ['demo', 'Demo'], ['paper', 'Paper']].filter(([m]) =>
      ((s.books || {})[m] || {}).trades || d.deployments.some((x) => x.mode === m && x.status !== 'stopped'));
    const money = books.length ? books.map(([m, label]) => {
      const b = s.books[m] || { pnl: 0, trades: 0 };
      // The book's name and its signed amount never break apart (a phone wraps the rest of the line).
      return `<span class="since-book" data-book="${m}">${b.trades
        ? `<span class="nobr"><b>${label}</b> <span class="${b.pnl < 0 ? 'neg' : b.pnl > 0 ? 'pos' : ''}">${usd(b.pnl, true)}</span></span> on ${plural(b.trades, 'trade', 'trades')}${m === 'live' ? ' (real money)' : m === 'paper' ? `, ${PAPER_NET}` : ''}`
        : `<b>${label}</b>: no trades closed yet`}</span>`;
    }).join('<span class="sep">·</span>') + sinceSplit(d, books) : 'No trades closed.';
    const pass = s.passed || { n: 0, items: [] }, runs = s.runs || {};
    const started = Object.values(runs).reduce((a, n) => a + n, 0), failed = runs.failed || 0;
    // A strategy that passed its paper forward test or became ready for live did so days after it was
    // created, so `passed` never lists it: the server reads those from the bell (`milestones`, strategy
    // ids), and the page names each from its own deployments.
    const ms = s.milestones || {}, named = (sid) => {
      const dep = d.deployments.find((x) => +x.strategy_id === +sid);
      return `<a href="/strategies/${encodeURIComponent(sid)}">${esc(dep ? dep.title : 'Strategy ' + sid)}</a>`;
    };
    const fwd = (ms.passed || []).slice(0, 3).map(named);
    const fwdText = `${fwd.join(', ')} passed ${fwd.length === 1 ? 'its' : 'their'} paper forward test: ${fwd.length === 1 ? 'a candidate' : 'candidates'} for live`;
    // A pass a later check left uncleared (the server's not_cleared: its one-time holdout then failed, or
    // the diversification check held it back) is named apart, as its page and the lists stamp it: the
    // strip counted it among "2 strategies passed".
    // Past the passes the server judges (`more`), each count is at least that many: "500+", never a wrong exact one.
    const atLeast = pass.more ? '+' : '';
    const fell = pass.not_cleared || [], NOT_CLEARED = { missed_final: 'missed the final test', held_back: 'held back' };
    const fellText = fell.length ? ` Not cleared to trade: ${fell.map((x) => `<a href="/strategies/${encodeURIComponent(x.id)}">${esc(x.title)}</a> (${NOT_CLEARED[x.verdict] || 'held back'})`).join(', ')}${pass.not_cleared_n > fell.length ? `, ${num(pass.not_cleared_n - fell.length)}${atLeast} more` : ''}.` : '';
    // A brand-new account has nothing of its own to report yet: point at the finished example, up top.
    const found = s.own_sessions === false && !pass.n && !fwd.length ? `No sessions of your own yet. <a href="/example" data-example>See an example session first</a>` : ((pass.n
      ? `${num(pass.n)}${atLeast} ${pass.n === 1 && !atLeast ? 'strategy' : 'strategies'} passed: ${pass.items.map((x) => `<a href="/strategies/${encodeURIComponent(x.id)}">${esc(x.title)}</a>`).join(', ')}${pass.n > pass.items.length || atLeast ? `, <a href="/strategies">${num(pass.n - pass.items.length)}${atLeast} more</a>` : ''}`
      : fwd.length ? fwdText : 'Nothing new passed') + (started ? `<span class="since-sub">${SEP}${plural(started, 'research session', 'research sessions')} started, ${sinceRunsState(runs, started, !pass.n)}</span>` : '') + '.' + (pass.n && fwd.length ? ` ${fwdText}.` : '') + fellText);
    const ap = s.autopilot || {}, apOn = !!(S.me && S.me.user && S.me.user.autopilot);
    const known = new Set(AP_DID.map(([k]) => k));
    const did = AP_DID.filter(([k]) => ap[k]).map(([k, w]) => w.replace('%s', k === 'research' ? plural(ap[k], 'research session', 'research sessions') : num(ap[k])));
    const other = Object.entries(ap).filter(([k]) => !known.has(k)).reduce((a, [, n]) => a + n, 0);
    if (other) did.push('made ' + plural(other, 'other change', 'other changes'));
    // A loss guard's pause is the engine's, not an autopilot move (the server's auto_paused, from the bell):
    // said here too, since one resumed or removed since is in no other line of the strip.
    const guarded = (s.auto_paused || []).length;
    const auto = (did.length ? `It ${did.join(', ')}.` : `<span data-since-ap>${sinceApWord(apOn)}</span>`)
      + (guarded ? ` ${plural(guarded, 'strategy was', 'strategies were')} paused automatically to stop a loss.` : '');
    const needs = (ms.live_ready || []).slice(0, 3).map((sid) => `${named(sid)} is ready for live trading. Going live is your call.`);
    // A demo book paused for its missing demo key says the reason once: the demo line below says what it needs,
    // with "Add it on the Funds page" as its link. The row said the engine's "Add your Kalshi demo (sandbox) key on
    // the Funds page to run this on demo" and the next line said it again. Any other reason that sends someone to
    // Funds links "the Funds page" as the Deploy row does (fundsLinked).
    const keyNeed = !!(d.demo && d.demo.health && d.demo.health.code === 'demo_key');
    needs.push(...d.deployments.filter((x) => x.status === 'paused').slice(0, 3).map((x) => {
      const why = x.status_why || x.status_reason;
      const said = why && !(keyNeed && x.mode === 'demo' && /demo \(sandbox\) key/.test(why));
      return `<a href="${pausedHref}">${esc(x.title)}</a> is paused${said ? `<span class="since-sub">: ${fundsLinked(esc(shortReason(why)))}</span>` : ''}`;
    }));
    const pausedN = d.deployments.filter((x) => x.status === 'paused').length;
    if (pausedN > 3) needs.push(`<a href="${pausedHref}">${num(pausedN - 3)} more paused</a>`);
    if (d.demo && d.demo.health) needs.push(d.demo.health.need ? `Demo can’t trade: it needs ${esc(d.demo.health.need)}.${actionLink(d.demo.health)}` : demoHealthLine(d.demo.health));
    if (d.reconcile && d.reconcile.length) needs.push(`${plural(d.reconcile.length, 'live position disagrees', 'live positions disagree')} with Kalshi. <a href="/funds">Check Funds</a>`);
    if (failed) needs.push(`<a href="/research">${plural(failed, 'research session', 'research sessions')} failed</a>`);
    // Under the floor a research session needs, nothing new researches (autopilot included) until they add credits.
    const me = S.me || {};
    const low = me.billing_enabled && !me.needs_card && me.min_run_balance != null && me.credit_balance < me.min_run_balance;
    if (low)
      needs.push(`Credits are at ${usd(me.credit_balance)}: new research needs ${usd(me.min_run_balance)} to start. ${me.reload_failed
        ? 'Auto-reload couldn’t charge your card. <a href="/billing">Update your card and add credits</a>' : '<a href="/billing">Add credits</a>'}`);
    // Before the pause, not after: with auto-reload off, the week's pace runs the balance out within
    // CREDITS_WARN_DAYS (the server's CREDIT_RUNWAY_WARN_DAYS, which the autopilot panel warns on).
    const spent = me.billing_enabled ? s.spent : null, wk = spent ? +spent.week || 0 : 0;
    const left = (+me.credit_balance || 0) - (+me.min_run_balance || 0);  // research pauses under the floor, not at $0
    const runway = wk > 0 && left > 0 ? left / (wk / 7) : null;
    if (spent && !low && !me.needs_card && !me.auto_reload && runway != null && runway < CREDITS_WARN_DAYS)
      needs.push(`${pausesIn(runway)} <a href="/billing">Add credits or turn on auto-reload</a>`);
    // What the time away cost, in credits: real money, so its own row, never added to a book above.
    // Until a card was ever charged (the server's card_charged) every credit spent was a free one, and
    // "real money" beside a new user's first cents read as a charge to their card.
    const paid = creditsPaid(spent && spent.card_charged);
    // A card charged while they were away (the server's charges, reloads of them auto-reload's): the time
    // away's real-money moment, which only Billing's statement told. Credits bought, never netted with spent.
    const charges = spent ? +spent.charges || 0 : 0, reloads = spent ? +spent.reloads || 0 : 0;
    const bought = !charges ? '' : `; ${reloads === charges ? `auto-reload charged your card ${charges === 1 ? 'once' : charges === 2 ? 'twice' : num(charges) + ' times'} for`
      : reloads ? `${plural(charges, 'card charge', 'card charges')} (${num(reloads)} by auto-reload) bought` : 'you bought'} <b>${usd(spent.bought)}</b> of credits`;
    const cost = spent ? `${+spent.since >= 0.01 ? `<b>${usd(spent.since)}</b> of credits spent` : 'No credits spent'}${bought}<span class="since-sub">${paid ? SEP + paid : ''}${SEP}${usd(me.credit_balance || 0)} left${SEP}<a href="/billing">Billing</a></span>` : '';
    const row = (k, v, cls) => `<div class="since-row${cls ? ' ' + cls : ''}"><dt>${k}</dt><dd>${v}</dd></div>`;
    return `<section class="since" id="dash-since" aria-label="${s.first ? 'Last 24 hours' : 'Since your last visit'}">
      <h2 class="since-h">${s.first ? 'Last 24 hours' : `Since your last visit <span class="since-at">${esc(when(s.at))}</span>`}</h2>
      <dl class="since-list">${row('Money', money)}${cost ? row('Cost', cost) : ''}${row('New results', found)}${row('Autopilot', auto)}${row('Needs you', needs.length ? needs.join('<br>') : 'Nothing.', needs.length ? 'needs' : '')}</dl></section>`;
  }
  function demoHealthLine(h) { return h ? `<span class="demo-health">${esc(h.line)}${actionLink(h)}</span>` : ''; }
  // The reconciler found live positions Tau's book and Kalshi disagree on. Tau has no portfolio page:
  // name the contracts and point at the two lists to compare, Tau's open positions and Kalshi's own.
  function reconWarn(rows) {
    const ticks = [...new Set(rows.map((r) => r.ticker))];
    const named = ticks.slice(0, 3).map(esc).join(', ') + (ticks.length > 3 ? ` and ${ticks.length - 3} more` : '');
    return `\u26a0 <span>${rows.length} live position${rows.length === 1 ? '' : 's'} disagree${rows.length === 1 ? 's' : ''} with Kalshi (${named}). Compare <a href="#dash-open">Tau\u2019s open positions</a> with the positions in your Kalshi account.</span>`;
  }
  // One mode's closed trades as a CSV, offered only where that mode has some, so the reader can
  // check its P&L line by line. The server never mixes modes in one file.
  // `before`, the text ahead of it, and `info`, the key of a glossary button after that text: the button comes first,
  // glued to its last word and the separator (gloSep).
  function tradesCsv(mode, b, info = '', before = '') {
    const has = b && b.closed_trades > 0, link = has ? `<a class="csv-link" href="/api/trades.csv?mode=${mode}" download>Download trades (CSV)</a>` : '';
    if (info) return (has ? gloSep(info, before) : before + glo(info)) + link;
    return before + (has ? SEP : '') + link;
  }
  // What demo is, for a reader who has never used it: real exchange fills, pretend money.
  const DEMO_WHAT = 'real fills on Kalshi’s sandbox, not real money';
  // The demo figure's one name, on every page that shows it (the dashboard, Funds): Tau's own book, never a balance
  // at Kalshi. The dashboard called it "Demo Sandbox" (Meridian: "Demo balance") beside Funds' "Tau's demo book".
  const DEMO_BOOK = 'Tau\u2019s demo book';
  // The demo figure is Tau's own book, not a balance at Kalshi: the capital Tau sets for demo (app_users.demo_capital,
  // $1,000 for a new account) plus its closed demo trades. Without a demo key nothing can trade on it, and a new
  // account's dashboard said "Demo sandbox $1,000.00" while Funds said a key was needed: a book with no key that
  // never traded shows no figure. One that traded (its key since removed) keeps its record. An /api/me that
  // doesn't say keeps the figure. Funds passes its own key read.
  const demoUnused = (b) => !!b && !+b.open_positions && !+b.running && !+b.closed_trades && !+(b.realized_pnl != null ? b.realized_pnl : b.realized) && !+b.before_reload;
  const demoKeyless = (b, key = S.me && S.me.kalshi_dev_connected) => key === false && demoUnused(b);
  const DEMO_NO_KEY = 'Connect a Kalshi demo key on <a href="/funds#connect-kalshi">Funds</a> to trade its sandbox (play money)';
  // An open position's cost, on the one basis every page names it: contracts x entry price plus the entry fee, as
  // Deploy's and the strategy page's "Cost + fee" (a row's `cost`, a book's `open_cost`). The dashboard and Funds said
  // "$1.90 at cost" for a position Deploy showed at "$1.94". An answer without it names its figure as before fees.
  const openBasis = (b) => b.open_cost != null ? 'cost + fees' : 'cost before fees';
  const openFig = (b) => usd(b.open_cost != null ? b.open_cost : b.open_at_cost);
  const openCost = (b) => `${openFig(b)} at ${openBasis(b)}`;
  // A book or deployment with no closed trade has no realized P&L yet: the first paper deployment's dashboard read
  // "$0.00 at cost + fees · $0.00 realized all time" and its Deploy row "$0.00" under Deploy's own "Realized: None
  // yet". Until a trade closes it says so in Funds' words; nothing open leaves the open cost out, as Funds does.
  const hasClosed = (b) => !!(+b.closed_trades || +b.realized_pnl);
  const PAPER_NO_CLOSE = 'P&amp;L shows once a paper trade closes';
  const hasOpen = (b) => !!(+b.open_positions || +b.open_cost || +b.open_at_cost);
  // An unknown realized (null) keeps its dash: only a known zero with nothing closed reads None yet.
  const realizedCell = (d, none = '<span class="sub-fig">None yet</span>') => d.realized_pnl == null || hasClosed(d) ? money(d.realized_pnl) : none;
  // Paper's balance counts an open position at its price (contracts x entry price): the fee is already spent. When
  // the two differ, the part in the balance is said, so cash plus it is the balance.
  const inBalance = (b, what = 'the balance') => b.open_cost != null && b.open_at_cost != null && Math.abs(b.open_cost - b.open_at_cost) >= 0.005
    ? `${usd(b.open_at_cost)} of it in ${what}` : '';
  // Dashboard autopilot card: the one-click way in while autopilot is off, and once it's on a
  // plain "what is it doing, is it making money" strip. Painted from the float's status poll
  // (S.ap) plus the dashboard's paper book (S.dashPaper), so it never needs its own request.
  // A Turn on still waiting for Tau: the 15s board poll and the 20s status read repaint the card, and
  // the button came back pressable with its note gone, so a hung switch looked like a press that did
  // nothing. The repainted button stays busy, with the note, until the write answers (apTurning).
  let apTurning = null;
  function apCardOn(b) {
    const waited = apTurning = waitNote(b);
    return busy(b, apTurnOn, waited).finally(() => {
      apTurning = null;
      const card = document.getElementById('dash-ap'), now = card && card.querySelector('[data-apcard="on"]');
      if (now && now !== b) { now.classList.remove('busy'); now.disabled = false; }
    });
  }
  function paintDashAp() {
    const host = document.getElementById('dash-ap');
    if (!S.me || !S.me.user) return;
    const d = S.ap, on = d ? d.autopilot : !!S.me.user.autopilot;
    syncApCopy(on);
    if (!host) return;
    if (!on) {
      host.className = 'apcard';
      host.innerHTML = `<div class="apcard-main"><span class="apcard-kick"><span class="apf-dot" aria-hidden="true"></span>Autopilot off</span>
        <h2>Let the autopilot trade for you</h2>
        <p>It picks markets, tests ideas on data it never saw, and runs the ones that pass on paper money. Every move shows up in its activity feed. Real money stays off until you turn it on separately.</p>${apCostLine()}${d && Array.isArray(d.focus) ? `<p class="ap-focus">${apFocusLine(d.focus, 'data-apcard="focus"')}</p>` : ''}</div>
        <div class="apcard-act"><button type="button" class="btn primary" data-apcard="on">Turn on autopilot</button><a class="apcard-alt" href="/research">or research by hand</a></div>
        <p class="apcard-err error-text" role="alert"></p>`;
      const b = host.querySelector('[data-apcard="on"]');
      if (apTurning) { b.classList.add('busy'); b.disabled = true; apTurning.place(b); }
      b.onclick = () => apCardOn(b);
      apBindFocus(host);
      return;
    }
    if (!d) { host.className = 'apcard on'; host.innerHTML = ''; return; }  // on, status still loading
    const m = AP_MODE[d.mode] || AP_MODE.paper, r = d.research || {}, prog = d.paper_progress;
    // A live one while live trading is closed places no orders: counted apart, as Deploy counts it.
    const liveIdle = liveOpen() ? 0 : +d.live_running || 0;
    // Each book by name, as the panel's Running figure says it: "Strategies running 2" didn't say which money they trade.
    const running = [[(+d.live_running || 0) - liveIdle, 'live'], [+d.demo_running || 0, 'demo'], [+d.paper_running || 0, 'paper']]
      .filter(([n]) => n > 0).map(([n, book]) => `${n}\u00a0${book}`).join(SEP);
    // Realized, as the paper card, the track record, Deploy and the strategy page count it. The equity
    // change (total_pnl) is a fourth number: it takes off open positions' entry fees and drops every
    // trade before a reset, so "Paper P&L" read $5.19 here beside a $5.61 track record.
    const pnl = S.dashPaper ? S.dashPaper.realized_pnl : null;
    // Each cell's note sits on its own line (a block <small>), with a space before it: read as text (a screen
    // reader's line, a copy, a page's text) the figure ran into it, "0 of 30 realistic paper tradesinstant-fill …".
    // A paper book that has never closed a trade has no P&L yet: "$0.00" read as a result to a new account.
    const paperNone = pnl != null && !+S.dashPaper.closed_trades && !+pnl;
    const cells = [
      d.live_running ? ['Live realized today (UTC)', `${money(d.today_live_pnl || 0)} <small>real money, after Kalshi fees</small>`] : ['Paper P&amp;L, realized all time', pnl == null ? '—' : paperNone ? 'None yet <small>no paper trade has closed</small>' : `${money(pnl)} <small>${PAPER_NET}</small>${slipEst(S.dashPaper.slippage_estimate)}`],
      ['Strategies running', `${running || 'None yet'}${liveIdle ? ` <small>${liveIdleCount(liveIdle)}</small>` : ''}`],
      d.week ? null : ['Ideas this week', `${Number(r.tested_7d || 0).toLocaleString('en-US')} tested${SEP}${r.passed_7d || 0} passed${+r.not_cleared_7d ? `, ${num(r.not_cleared_7d)} not cleared` : ''}`],
      prog ? ['Furthest on paper', `<a href="/strategies/${Number(prog.strategy_id)}" title="${esc(prog.title || 'Paper strategy')}">${paperCount(prog)}</a> <small>${gl(PAPER_COUNT_WHY, 'instantfill')}</small>`]
        : ['Last check-in', d.reviewing ? 'Reviewing now' : d.last_review_at ? sinceMin(d.last_review_at) : 'Starting up'],
    ].filter(Boolean);
    const now = d.billing_blocked
      ? (d.billing_reason === 'card' ? 'Paused: <a href="/billing">add a payment method</a> so it can keep researching.' + apStillTrading(d)
        : apReloadFailed(d) ? `Paused: ${AP_CARD_FIX}${apStillTrading(d)}`
        : `Paused: ${apFloorText()} <a href="/billing">Add credits</a> and it picks up on its own.${apStillTrading(d)}`)
      : d.idle ? apIdleHtml(d.idle, 'data-apcard="idle-focus"') + apMeanwhile(d) : esc(apStory(d)[0] || 'Autopilot is on.');
    host.className = 'apcard on' + (m.cls ? ' ' + m.cls : '') + (d.billing_blocked ? ' warn' : '');
    host.innerHTML = `<div class="apcard-main"><span class="apcard-kick"><span class="apf-dot" aria-hidden="true"></span>${esc(m.label)}</span>
        <p class="apcard-now">${now}</p>${apLastHtml(d.last_action)}${Array.isArray(d.focus) ? `
        <p class="ap-focus">${apFocusLine(d.focus, 'data-apcard="focus"')}</p>` : ''}
        <dl class="apcard-figs">${cells.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl><p class="stale-note" id="dash-ap-stale" role="status">${apStale()}</p>${apWeek(d.week, d)}</div>
      <div class="apcard-act"><button type="button" class="btn" data-apcard="open">Open autopilot</button></div>`;
    host.querySelector('[data-apcard="open"]').onclick = () => apOpen();
    const idleFocus = host.querySelector('[data-apcard="idle-focus"]');
    if (idleFocus) idleFocus.onclick = () => { apOpen(); apShowFocus(document.getElementById('autopilot-float')); };
    apBindFocus(host);
  }
  // The autopilot's latest move (the server's last_action: its newest system line about itself) as one
  // line, what and when: the card said "Last move 12m ago" and never what the move was. The line's first
  // sentence, without the "Autopilot" lead-in or Markdown; the switch note reads as the switch. The time
  // is relative, with the clock time and zone on hover.
  function apMoveText(la) {
    const raw = String((la && la.text) || '').replace(/[*_`]+/g, '').replace(/\s+/g, ' ').trim();
    const flip = /^(LIVE )?autopilot is (ON|OFF)\b/i.exec(raw);
    if (flip) return `${flip[1] ? 'Live autopilot' : 'Autopilot'} switched ${/on/i.test(flip[2]) ? 'on' : 'off'}`;
    // A strategy's name can hold " — " ("Fade tails — v2"), where the line is cut to its first clause:
    // "I left Fade tails — v2 running: ..." read "I left Fade tails." The server lists the names in the
    // line that hold one (la.titles); each is held whole, as a placeholder, through the cuts.
    const names = (la && Array.isArray(la.titles) ? la.titles : []).map(String).filter((n) => n && raw.includes(n));
    const whole = (s) => s.replace(/\uE000(\d+)\uE001/g, (all, i) => names[i]);
    let t = names.reduce((s, n, i) => s.split(n).join('\uE000' + i + '\uE001'), raw);
    t = t.replace(/^Autopilot:?\s+(?=[a-z])/, '').split(/(?<=[.!?])\s| — /)[0].replace(/[.!?]$/, '');
    // The forward gate's verdict line leads with a label and carries its stats in brackets; cut to the
    // label alone it read "Last move: Paper forward gate". Say the verdict instead.
    // The live-ready and paper-standout lines start with their once-only marker ("[live-ready #12]").
    t = t.replace(/^\[[a-z-]+ #\d+\]\s*/, '').replace(/^Paper forward gate: (.+?) PASSED\b.*$/, '$1 passed its paper forward test')
      .replace(/^Paper forward gate: (.+?) passed on paper\b.*$/, '$1 passed on paper, not added to the candidates')
      .replace(/^Paper forward gate: (.+?) did not pass\b.*$/, '$1 did not pass its paper forward test');
    // agent.act names a research session's market by its key ("on btc15m"); say it the way the app does.
    const keys = new Set(((S.me && S.me.markets) || []).map((m) => m.key));
    t = t.replace(/\bon ([a-z0-9_]+)$/, (all, k) => keys.has(k) || MKT_SHORT[k] ? 'on ' + marketShort(k) : all);
    if (whole(t).length > 90 && t.indexOf(': ') > 10) t = t.slice(0, t.indexOf(': '));
    t = whole(t);
    t = clipWords(t, 90);
    return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
  }
  function apLastHtml(la) {
    const text = apMoveText(la);
    if (!text || !la.at) return '';
    return `<p class="ap-last">Last move <time datetime="${esc(la.at)}" title="${esc(settleAt(la.at))}">${sinceMin(la.at)}</time>: ${esc(text)}.</p>`;
  }
  // What it is doing right now in a word or two, for the pill on every page: "researching",
  // "reviewing", "2 on paper", or "paused" while billing stops it. '' when there's nothing to add.
  // A market the autopilot names (the status read's research list, and its story, which quotes that
  // list): the app's own label. The server sends a market's label, or the run's raw key when the
  // catalog no longer lists it ("btc15m", a series like "KXBTCD"); a listed market, key or series, reads
  // as its full label (marketFull, as Billing's research lines say it), a key only the app knows as its
  // short label, and a key nothing knows as "an unlisted market", never the raw key.
  const AP_PICKING = "a market it’s still picking";
  function apMarketName(n) {
    const s = String(n || '');
    const m = ((S.me && S.me.markets) || []).find((x) => x.key === s || x.label === s || (x.series && x.series.toUpperCase() === s.toUpperCase()));
    if (m) return marketFull(m.key);
    if (MKT_SHORT[s]) return MKT_SHORT[s];
    // A label has a space or mixed case ("Chicago high temp"); a key is one case, no spaces.
    if (!/^[\w.-]+$/.test(s) || (s !== s.toLowerCase() && s !== s.toUpperCase())) return s;
    return contractMarket(s) || 'an unlisted market';
  }
  const apMarketNames = (d) => [...new Set(((d && d.research && d.research.active) || []).map((n) => n === AP_PICKING ? n : apMarketName(n)))];
  // The card leads with why its paper strategies hold nothing (d.idle). The autopilot keeps working
  // meanwhile, and the card never said so: someone back after a day read "Nothing open right now" and
  // not that a research session was running. Paper-waiting lines only (the others already say it).
  const AP_IDLE_PAPER = new Set(['flat', 'starting', 'waiting', 'market_closed']);
  function apMeanwhile(d) {
    if (!d || !d.idle || !AP_IDLE_PAPER.has(d.idle.code)) return '';
    const all = apMarketNames(d), names = all.filter((n) => n !== AP_PICKING);
    if (!all.length) return d.reviewing ? " Meanwhile it’s reviewing the markets to pick its next move." : '';
    if (!names.length) return " Meanwhile it’s picking a market to research.";
    const said = names.length === 1 ? names[0] : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
    return ` Meanwhile it’s researching ${esc(said)}.`;
  }
  // The server's story lines with each raw key it quoted from the research list said as apMarketName does.
  function apStory(d) {
    const raw = [...new Set((d && d.research && d.research.active) || [])].filter((n) => n !== AP_PICKING && apMarketName(n) !== n);
    return ((d && d.story) || []).map((line) => raw.reduce((t, n) =>
      t.replace(new RegExp('(^|[^\\w-])' + n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?![\\w-])', 'g'), (all, pre) => pre + apMarketName(n)), String(line)));
  }
  function apDoing(d) {
    if (!d || !d.autopilot) return '';
    if (d.billing_blocked) return 'paused';
    if (d.research && (d.research.active || []).length) return 'researching';
    if (d.reviewing) return 'reviewing';
    return d.paper_running ? `${d.paper_running} on paper` : '';
  }
  // The pill's label: in paper mode the word for what it is doing takes the place of "paper" (each one
  // is paper-only or no money at all); the live modes keep their label, so LIVE always shows.
  function apPillLabel(d, m) {
    const doing = d && d.mode === 'paper' ? apDoing(d) : '';
    return doing ? `Autopilot${SEP}` + doing : m.label;
  }
  // Why autopilot isn't trading right now (the server's d.idle): one plain line, plus the action to
  // take when there is one (a link, or the focus control). The card and the panel both lead with it.
  function apIdleHtml(idle, focusAttr) {
    const a = idle.action;
    const act = !a ? '' : a.href ? actionLink(idle)
      : a.do === 'focus' ? ` <button type="button" ${focusAttr}>${esc(a.label)}</button>` : '';
    return esc(idle.line) + act;
  }
  // The market focus is binding on research, deploys and the picker, so it reads as a plain line on
  // the card and the panel, with a Change that opens the control (it lives in "Model and markets").
  function apFocusText(focus) {
    const f = focus || [];
    if (!f.length) return 'any market';
    const preset = AP_FOCUS.find(([v]) => v && v === f.join(','));
    if (preset) return preset[1].replace(/ only$/, '');
    const keys = new Set(((S.me && S.me.markets) || []).map((m) => m.key));
    return f.map((t) => FOCUS_WORDS[t] || (keys.has(t) ? marketShort(t) : t.charAt(0).toUpperCase() + t.slice(1).replace(/[-_]/g, ' '))).join(', ');
  }
  // A coin or family in words, as the server's chat lines say it (agent.FOCUS_WORDS): "Focus: Btc, eth" read the raw tokens.
  const FOCUS_WORDS = { btc: 'Bitcoin', eth: 'Ethereum', sol: 'Solana', xrp: 'XRP', doge: 'Dogecoin', hype: 'Hyperliquid', near: 'NEAR',
    zec: 'Zcash', tao: 'Bittensor', 'crypto-perpetuals': 'Crypto perpetuals', 'weather-high': 'Daily high temperatures' };
  const apFocusLine = (focus, attr) => `Focus: ${esc(apFocusText(focus))} <button type="button" ${attr}>Change</button>`;
  function apBindFocus(host) {
    const b = host.querySelector('[data-apcard="focus"]');
    if (b) b.onclick = () => { apOpen(); apShowFocus(document.getElementById('autopilot-float')); };
  }
  function apFocusPaint(box, focus) {
    const fline = box.querySelector('#apf-focusline'); if (!fline) return;
    const key = (focus || []).join(',');
    if (fline.dataset.cur !== key) { fline.dataset.cur = key; fline.innerHTML = apFocusLine(focus, 'data-ap="focus"'); const b = fline.querySelector('[data-ap="focus"]'); if (b) b.onclick = () => apShowFocus(box); }
    fline.hidden = false;
  }
  // Open "Model and markets" and put the reader on the focus select.
  function apShowFocus(box) {
    if (!box || !apExpanded()) return;
    // Opened just now, the panel may still be fetching its file: the focus control is there once it has run.
    if (!PAGES.autopilot) { pageLoad('autopilot').then(() => apShowFocus(box), () => {}); return; }
    const prefs = box.querySelector('.apf-prefs'); if (prefs) prefs.open = true;
    const sel = box.querySelector('#apf-focus'); if (sel && sel.focus) sel.focus();
  }
  // The autopilot's last 7 days (d.week). Credits are spend and paper P&L is not, so they are two
  // labelled figures, never added together. Research counts every session; paper counts only the
  // strategies the autopilot put on paper itself (the server attributes them by their deploy record).
  // What spent credits were, beside a spend: real money only once the payload says a card was ever charged
  // for credits (the server's card_charged true), free ones while it says none was (false). The autopilot's
  // week said "real money" under a new user's first cents while the strip above it said the card hadn't been
  // charged; and with payments off Billing sends no card_charged at all, and the week still said "real money"
  // under free-credit research spend. Unknown claims nothing ('' here): each caller says what it was spent on.
  const creditsPaid = (charged) => charged === true ? 'real money' : charged === false ? 'free credits so far: your card hasn’t been charged' : '';
  // The week's "Credits spent on research" figure. Its heading already says what it was spent on, so the figure is
  // just the amount ("$0.84"), and "None yet" while nothing was ("$0.00 research spend" said it twice). Beside it:
  // who paid (creditsPaid: real money only once card_charged is true) and the check-ins.
  function apWeekSpent(w, spend, checkins) {
    const researched = +w.research_credits >= 0.005 || !!w.research_under_cent;
    const ci = checkins ? `${spend(w.checkin_credits, w.checkin_under_cent)} on its check-ins` : '';
    const paid = researched || checkins ? creditsPaid(w.card_charged) : '';
    const note = (researched ? [paid, ci && `plus ${ci}`] : [ci && `but ${ci}`, paid]).filter(Boolean).join(SEP);
    return `${researched ? spend(w.research_credits, w.research_under_cent) : 'None yet'}${note ? ` <small>${note}</small>` : ''}`;
  }
  function apWeek(w, d) {
    if (!w) return '';
    const pnl = +w.paper_pnl || 0, trades = +w.paper_trades || 0;
    // A first day's week is all zeros: a block of $0.00 and 0 under two paragraphs explaining them. Until
    // something is in it, it is one line. A paused one keeps its credits line, which says why it paused.
    // A figure that spent something but shows $0.00 says "under $0.01", as Billing's split does (the server's
    // research_under_cent and checkin_under_cent); the figures themselves are Billing's parts.
    const spend = (v, under) => (under && !(+v >= 0.005) ? 'under $0.01' : usd(v || 0));
    const checkins = +w.checkin_credits >= 0.01 || !!w.checkin_under_cent;
    const empty = !(+w.research_credits >= 0.005) && !w.research_under_cent && !(+w.checkin_credits >= 0.005) && !w.checkin_under_cent
      && !+w.tested && !+w.passed && !+w.not_cleared && !+w.paper_started && !trades && !pnl;
    // Its first session already running is not "once it starts": the card said so beside "It started 1 research
    // session" in Last 24 hours. While one runs (the status's research.active) it says that instead.
    const researching = !!(d && d.research && d.research.active && d.research.active.length);
    if (empty) return `<section class="ap-week ap-week-empty" aria-label="Autopilot, last 7 days"><p class="ap-week-none"><b>Last 7 days:</b> ${researching
      ? 'a research session is running and none has finished yet. What it tests, puts on paper and spends shows here as it goes.'
      : 'nothing yet. Its research, paper strategies and credits spent show here once it starts.'}</p>${d && (d.billing_blocked || d.reload_failed) ? apCreditsLeft(w, d) : ''}</section>`;
    return `<section class="ap-week" aria-label="Autopilot, last 7 days"><h3>Last 7 days</h3><dl>
      <div><dt>Credits spent on research</dt><dd>${apWeekSpent(w, spend, checkins)}</dd></div>
      <div><dt>Ideas</dt><dd>${Number(w.tested || 0).toLocaleString('en-US')} tested${SEP}${Number(w.passed || 0).toLocaleString('en-US')} passed${+w.not_cleared ? `, ${num(w.not_cleared)} not cleared` : ''}</dd></div>
      <div><dt>Autopilot put on paper</dt><dd>${Number(w.paper_started || 0)} strateg${+w.paper_started === 1 ? 'y' : 'ies'} <small>not counting yours</small></dd></div>
      <div><dt>Autopilot’s paper P&amp;L</dt><dd>${!trades && !pnl ? 'None yet <small>none of its paper trades has closed</small>' : `<span class="${pnl < 0 ? 'neg' : pnl > 0 ? 'pos' : ''}">${usd(pnl, true)}</span> <small>paper, not real money, ${PAPER_NET}${SEP}${trades} closed trade${trades === 1 ? '' : 's'}</small>${slipEst(w.paper_slippage_estimate)}`}</dd></div>
    </dl>${apCreditsLeft(w, d)}<p class="ap-week-note">Research counts every session, yours and the autopilot’s. The two paper rows count only what the autopilot put on paper itself; strategies you deploy yourself count in the running total and on the Deploy page, not here.</p></section>`;
  }
  // Why a credits pause happened, in the server's figure: research needs this much to start.
  // Paused for credits while auto-reload is on and its last charge failed (the status's reload_failed,
  // Billing's banner text): the card is the next step, since "add credits" goes on the same card.
  const apReloadFailed = (d) => !!(d && d.billing_blocked && d.billing_reason !== 'card' && d.reload_failed);
  // Auto-reload fires only on a charge, and nothing is charged while research is paused: a new card
  // alone does not restart it, so the step is the card and then credits.
  const AP_CARD_FIX = 'auto-reload couldn’t charge your card. <a href="/billing">Update your card and add credits on Billing</a>, and research picks up on its own.';
  const apFloorText = () => (S.me && S.me.min_run_balance != null ? `starting research needs ${usd(S.me.min_run_balance)} in credits.` : 'it’s out of credits.');
  // A billing pause stops the autopilot's research and check-ins; the engine keeps trading what is
  // already deployed (credits never gate a trade). "Paused" alone read as if every strategy had stopped.
  const apStillTrading = (d) => {
    const n = (liveOpen() ? +d.live_running || 0 : 0) + (+d.demo_running || 0) + (+d.paper_running || 0);  // live places no orders while closed
    return n ? ` ${n === 1 ? 'The strategy already running keeps' : `The ${n} strategies already running keep`} trading.` : '';
  };
  // Beside the week's spend: what is left, how long it lasts at that pace (the Billing page's runway),
  // and the only limit there is. Autopilot has no spending budget of its own: it researches until the
  // balance is under what a session needs to start, then pauses. Once it has paused (the status's
  // billing_blocked, the worker's own gate) the line says so, without the pace: nothing is being
  // spent. The next status read after credits land puts the running copy back.
  function apCreditsLeft(w, d) {
    const me = S.me;
    if (!w || w.credits_left == null || !me || !me.billing_enabled) return '';
    if (apReloadFailed(d))
      return `<p class="ap-week-left">Credits left: <b>${usd(w.credits_left)}</b>. Research is paused: auto-reload failed. ${esc(d.reload_failed)} <a href="/billing">Update your card and add credits on Billing</a>.</p>`;
    if (d && d.billing_blocked) {
      const why = d.billing_reason === 'card' ? 'until you add a payment method'
        : me.min_run_balance != null ? `until you add credits: a session needs ${usd(me.min_run_balance)} to start` : 'until you add credits';
      return `<p class="ap-week-left">Credits left: <b>${usd(w.credits_left)}</b>. Research is paused ${why}. <a href="/billing">Billing</a> lists every charge.</p>`;
    }
    // A first-day account has no pace yet, and one under a week old reads its pace per day so far
    // (the server's pace_days): its first minutes' spend over 7 days read "over 3 months".
    // With auto-reload on, the next thing at this pace is a card charge, not a pause (the server's reload_days).
    const at = w.pace_days != null && w.pace_days < 7 ? 'its pace so far' : 'this week’s pace';
    const reloadIn = !!me.auto_reload && w.reload_days != null && !(d && d.reload_failed);
    const pace = reloadIn ? `; at ${at} auto-reload adds ${usd(me.auto_reload.amount)} ${inDays(w.reload_days)} (card charged ${usd(me.auto_reload.charge)})`
      : w.runway_days != null ? `, ${runwayLabel(w.runway_days).toLowerCase()} at ${at}`
      : paceTooSoon(w.pace_days, (+w.research_credits || 0) + (+w.checkin_credits || 0)) ? ', too soon to say how long they last: its first day sets the pace' : '';
    // "Uses credits until your balance is under $1.00, then pauses (auto-reload adds $20.00 at $5.00)" read
    // as a pause; with auto-reload on the balance never gets there, the card is charged again and again.
    // A card just declined reads as no auto-reload: the floor is what stops it then.
    const ar = d && d.reload_failed ? null : me.auto_reload;
    const cap = ar ? `each time your balance falls to ${usd(ar.threshold)}, auto-reload charges your card${reloadIn ? '' : ` ${usd(ar.charge)} for ${usd(ar.amount)} more`} and research carries on.${me.min_run_balance != null ? ` With auto-reload off, it pauses when your balance is under ${usd(me.min_run_balance)}.` : ''}`
      : `it uses credits${me.min_run_balance != null ? ` until your balance is under ${usd(me.min_run_balance)}, then pauses` : ''}.`;
    return `<p class="ap-week-left">Credits left: <b>${usd(w.credits_left)}</b>${pace}. It has no daily spending cap: ${cap}${d && d.reload_failed ? ` <b>Auto-reload failed.</b> ${esc(d.reload_failed)} <a href="/billing">Update your card</a>.` : ''} <a href="/billing">Billing</a> lists every charge.</p>`;
  }
  // What switching it on costs, said before the click: the agent's runs spend credits, and with
  // auto-reload on the saved card is charged when they run low. Payments off on this server: no line.
  function apCostLine() {
    const me = S.me;
    if (!me || !me.billing_enabled) return '';
    const ar = me.auto_reload;
    // Already under what a session needs to start: switched on, it would sit paused from the start.
    if (!ar && !me.needs_card && me.min_run_balance != null && me.credit_balance < me.min_run_balance)
      return `<p class="apcard-cost">It uses your credits while it’s on. You have ${usd(me.credit_balance)}, under the ${usd(me.min_run_balance)} a research session needs to start, so it waits until you <a href="/billing">add credits</a>. Turn it off any time.</p>`;
    return `<p class="apcard-cost">It uses your credits while it’s on (${usd(me.credit_balance)} left)${ar
      ? `. When they fall to ${usd(ar.threshold)}, auto-reload charges your card ${usd(ar.charge)} for ${usd(ar.amount)} more. Turn it off any time, or change auto-reload on <a href="/billing">Billing</a>.`
      : ' and pauses when they run out. Turn it off any time.'}</p>`;
  }
  function apOpen() {
    try { localStorage.setItem('tau_ap_open', '1'); } catch (e) { /* private mode */ }
    const box = document.getElementById('autopilot-float');
    if (box) renderAutopilot(box, S.ap);
  }
  // One-click autopilot line for empty states; the [data-research-ap] click handler turns it on.
  // The empty Deployed box speaks to the autopilot switch; with autopilot on, its button asked for
  // work the autopilot is already doing. It follows the switch live (syncApCopy). It says only that
  // autopilot is on: the card above says what it is doing, and "is researching" contradicted a card
  // reporting a stale check-in or a billing pause.
  // A brand-new user (no research session of their own) gets the finished example first: one tap,
  // free, from the strip up top (sinceStrip). /example looks up the seeded example session
  // (/api/runs/example) and opens it in place.
  // On Research it is a plain button, so Start session stays the page's one primary action, and it is
  // left out when they came to start one (?new=1: "Describe your own idea" on the example itself, or
  // "Try another idea"): they have just seen it.
  function exampleLine(runs) {
    const ex = (runs || []).find((r) => r.example), own = (runs || []).filter((r) => !r.example).length;
    if (/[?&]new=1\b/.test(location.search)) return '';
    return ex && !own ? `<p class="research-ex"><a class="btn ex-cta" href="/research/${encodeURIComponent(ex.id)}" data-example>See an example session first</a> <span>A finished session Tau ran for you when you signed up, from idea to verdict. It cost you nothing.</span></p>` : '';
  }
  async function viewExample() {
    shell('/research', '', loading(200));
    // Its own lookup: /api/runs lists only the newest 50 sessions, so past that the example fell off it.
    const d = await api('/api/runs/example').catch(() => null);
    go(d && d.id ? '/research/' + d.id : '/research', true);
  }
  // /api/deployments sends each open position's mark but not the per-deployment sum the dashboard
  // sends, so a row read "+1 open" with Unrealized "—" above a table pricing that same position. Add it
  // the way the dashboard does: that one deployment's marked positions, never across deployments or books.
  function withUnrealized(d) {
    const by = {};
    for (const p of d.open_positions || []) {
      if (p.unrealized != null && p.deployment_id != null) by[p.deployment_id] = Math.round(((by[p.deployment_id] || 0) + +p.unrealized) * 100) / 100;
    }
    for (const x of d.deployments || []) if (x.unrealized_pnl == null && by[x.id] != null) x.unrealized_pnl = by[x.id];
    return d;
  }
  // Paper trades toward the target: "12 of 30 paper trades", and once past it "67 paper trades (30 needed)".
  // Why "realistic" counts fewer trades than the paper book beside it: the track record's words. "0 of 30 realistic
  // paper trades" sat next to "Paper +$8.72 on 12 trades" with no reason given.
  const INSTANT_WHY = 'fills real execution would not get';
  const PAPER_COUNT_WHY = `instant-fill paper trades left out (${INSTANT_WHY})`;
  const paperCount = (p) => +p.trades >= +p.trades_needed ? `${num(+p.trades)} realistic paper trades (${num(+p.trades_needed)} needed)` : `${num(+p.trades)} of ${num(+p.trades_needed)} realistic paper trades`;
  // A backtest trade's exit, in words (backtest.py / spec.exit_signal reasons); an unknown one loses its underscores.
  const EXIT_WORD = { settled: 'settled', take_profit: 'take-profit', stop_loss: 'stop-loss', stop: 'stop', edge_gone: 'edge gone', signal: 'signal', exit: 'signal', mark: 'marked at end' };
  const exitWord = (r) => r == null ? '' : EXIT_WORD[r] || String(r).replace(/_/g, ' ');
  // The equity chart's label over its unseen-data window. `words` (longest first) names another window: a strategy
  // with no gatekeeper record has no unseen window, only the backtest's later slice, which its loose gate used to pick it.
  const unseenLabel = (cx, right, y, words = [`LATER PERIOD${SEP}UNSEEN DATA →`, `LATER${SEP}UNSEEN →`, 'LATER →'], clearOf = 0) => {
    // In the strategy page's words ("Later period (unseen data)"): it read "UNSEEN →" over that heading. Measured at about
    // 7px a character in the chart’s 11px capitals: the full or short words in place right of the cut where they fit, else the short
    // words pinned to the chart's right edge, clear of the demo-replay legend (clearOf, its right end) on a phone. Only
    // where even those would run into the legend does it take the last, shortest words.
    const room = right - cx - 8, wide = (t) => t.length * 7;
    const inPlace = words.slice(0, 2).find((t) => room >= wide(t));
    if (inPlace) return `<text x="${cx + 8}" y="${y}" style="fill:var(--ink-2)">${inPlace}</text>`;
    const pinned = words.slice(1).find((t) => right - wide(t) >= clearOf) || words[words.length - 1];
    return `<text x="${right}" y="${y}" text-anchor="end" style="fill:var(--ink-2)">${pinned}</text>`;
  };
  // On a phone, a secondary section (method, raw lists, what-if, share, remove) folds behind its
  // title, closed; wider screens render it as before. Money figures and verdicts never fold.
  const fold = (title, html) => html ? `<details class="fold"${phone() ? '' : ' open'}><summary class="fold-h">${title}</summary>${html}</details>` : '';
  // For that new user the box adds no button of its own: it repeated the strip's example link as a
  // second primary button, next to the autopilot card's Turn on autopilot and "or research by hand".
  function depsEmpty(on) {
    return S.dashNoSessions ? (on
      ? `<div class="empty"><h3>Nothing deployed yet</h3><p>Autopilot is on. Strategies that pass every research test land here on paper first, with no real money.</p></div>`
      : `<div class="empty"><h3>Nothing deployed yet</h3><p>Turn on autopilot above, or research an idea yourself.</p></div>`) : on
      ? `<div class="empty"><h3>Nothing deployed yet</h3><p>Autopilot is on. Strategies that pass every research test land here on paper first, with no real money.</p><a class="btn" href="/research">See its research</a></div>`
      : `<div class="empty"><h3>Nothing deployed yet</h3><p>Turn on autopilot above and the strategies that pass every research test on data they never saw land here on their own, on paper first. Or research an idea yourself.</p><a class="btn" href="/research">Research an idea</a></div>`;
  }
  // Copy that depends on the switch follows it without a reload, so turning autopilot on doesn't leave
  // "Turn on autopilot above" or a Turn on nudge under a card that already says it's on.
  let trAp = null;  // the mounted track record's tab, to repaint when the switch flips
  const apSwitchOn = () => !!(S.me && S.me.user && S.me.user.autopilot);
  function syncApCopy(on) {
    const box = document.getElementById('deps-empty');
    if (box && box.dataset.on !== (on ? '1' : '0')) { box.dataset.on = on ? '1' : '0'; box.innerHTML = depsEmpty(on); }
    if (document.body) document.body.querySelectorAll('.research-ap').forEach((p) => { p.hidden = on; });
    if (document.body) document.body.querySelectorAll('[data-ap-next]').forEach((n) => { n.hidden = !on; });
    if (document.body) document.body.querySelectorAll('[data-ap-off]').forEach((n) => { n.hidden = on; });
    if (document.body) document.body.querySelectorAll('[data-since-ap]').forEach((n) => { n.textContent = sinceApWord(on); });
    if (trAp && trAp.host.isConnected && trAp.on !== apSwitchOn()) trAp.repaint();
  }
  function apNudge(lead, rest) {
    return S.me && S.me.user && !S.me.user.autopilot ? `<p class="research-ap">${lead} <button type="button" data-research-ap>Turn on autopilot</button> ${rest}</p>` : '';
  }
  // Research page nudge: the same one-click switch as the dashboard card.
  document.addEventListener('click', (e) => {
    const b = e.target.closest && e.target.closest('[data-research-ap]');
    if (!b) return;
    busy(b, async () => {
      await apTurnOn();
      const p = b.closest('.research-ap');
      if (p && S.me.user.autopilot) { p.textContent = 'Autopilot is on. Every idea it tries shows up in the autopilot panel.'; p.hidden = false; }
    });
  });
  // A switch Tau didn't confirm (no reply, or the edge's 5xx page) may have landed. "Reload the page to
  // check" sent a phone user to reload: the card and the panel read the switch again within half a
  // minute (the board poll, the status read), so the words point there.
  const AP_UNSURE = 'Tau didn\u2019t confirm this, so autopilot may or may not have switched. Its status here updates within half a minute; check it before you try again.';
  const apSaid = (e) => (e instanceof ApiError && e.message === failText(0, true) ? AP_UNSURE : e.message);
  async function apTurnOn() {
    try { await api('/api/settings', { autopilot: true }); }
    catch (e) { const card = document.getElementById('dash-ap'), err = card && card.querySelector('.apcard-err'); if (err) err.innerHTML = esc(apSaid(e)); else alert0(apSaid(e)); return; }
    S.me.user.autopilot = true;
    if (S.ap) S.ap = Object.assign({}, S.ap, { autopilot: true, mode: S.ap.mode === 'off' ? 'paper' : S.ap.mode });
    paintDashAp();
    // The card (or the nudge) repaints without the pressed button, so a reader heard nothing and a
    // keyboard user was left at the top of the page: say what changed, then follow it to the control
    // that replaced it — the open panel's close button, else the card's Open autopilot.
    announce('Autopilot is on. It researches and trades on paper by itself; every move shows up in the autopilot panel.');
    // The open panel's file first (app-autopilot.js), so its Model and markets is there to open below.
    if (!phone()) { await pageLoad('autopilot').catch(() => {}); apOpen(); }  // on a phone the open panel fills the screen; the card already says it's on
    const box = document.getElementById('autopilot-float');
    if (box && apExpanded()) { const prefs = box.querySelector('.apf-prefs'); if (prefs) prefs.open = true; }
    if (box) await refreshAutopilot(box);
    // After the status read's repaint, so the control focus lands on is the one that stays.
    const card = document.getElementById('dash-ap');
    const to = (box && apExpanded() && box.querySelector('.apf-x')) || (card && card.querySelector('[data-apcard="open"]'));
    if (to && to.focus) to.focus({ preventScroll: true });
  }
  const AP_PENDING_ON = { label: 'Autopilot on', cls: 'paper' };  // switch on, mode not read yet
  const AP_MODE = {
    off: { label: 'Autopilot off', cls: '' },
    paper: { label: `Autopilot${SEP}paper`, cls: 'paper' },
    'live-armed': { label: `Autopilot${SEP}live armed`, cls: 'live' },
    live: { label: `Autopilot${SEP}LIVE`, cls: 'live' },
  };
  // The open panel (its controls, the activity feed and the chat) is in app-autopilot.js, fetched the
  // first time it opens (page files, at the end of this file): every page draws the pill, few open it.
  // Until the file has run, the panel shows its head over a skeleton, and the pill's next render
  // builds it. A file that doesn't arrive says so in the panel, with Try again.
  function apBuildShell(box) {
    if (PAGES.autopilot) return PAGES.autopilot.apBuildShell(box);
    if (box.dataset.shell === 'loading') return;
    const m = (S.ap && AP_MODE[S.ap.mode]) || AP_MODE.off;
    box.dataset.shell = 'loading'; box.apPill = '';
    box.className = 'apf open' + (m.cls ? ' ' + m.cls : '');
    box.setAttribute('role', 'region'); box.setAttribute('aria-label', 'Autopilot');
    box.innerHTML = `<div class="apf-head"><span class="apf-dot" aria-hidden="true"></span><b id="apf-label">${esc(m.label)}</b>
      <button type="button" class="apf-x" data-ap="toggle" aria-label="Collapse autopilot">${ICON.cross || '×'}</button></div>
      <div class="apf-top">${loading(320)}</div>`;
    box.querySelector('.apf-x').onclick = (e) => apAction(box, 'toggle', e);
    const waiting = () => box.dataset.shell === 'loading' && apExpanded() && document.getElementById('autopilot-float') === box;
    pageLoad('autopilot').then(() => {
      if (!waiting()) return;
      const a = document.activeElement, hadFocus = !!(a && a !== document.body && box.contains(a));
      renderAutopilot(box, S.ap);
      const x = hadFocus && box.querySelector('.apf-x'); if (x && x.focus) x.focus({ preventScroll: true });
    }, () => {
      if (!waiting()) return;
      box.dataset.shell = 'failed';
      const top = box.querySelector('.apf-top');
      top.innerHTML = loadFail('The autopilot panel didn’t load. Check your connection and try again.');
      top.querySelector('[data-retry]').onclick = () => renderAutopilot(box, S.ap);
    });
  }
  function apUpdate(box, d) { if (PAGES.autopilot) PAGES.autopilot.apUpdate(box, d); }
  function apStopChat() { if (PAGES.autopilot) PAGES.autopilot.apStopChat(); }
  function renderAutopilot(box, d) {
    if (!apExpanded()) {
      apStopChat();
      // Before the first status read lands (or if it fails), go by the saved switch: an autopilot
      // user's pill read "Autopilot off" on every page load until then.
      const m = d ? (AP_MODE[d.mode] || AP_MODE.off) : (S.me && S.me.user && S.me.user.autopilot ? AP_PENDING_ON : AP_MODE.off);
      box.className = 'apf' + (m.cls ? ' ' + m.cls : '');
      box.dataset.shell = '';
      const tip = d && d.autopilot ? (apStory(d)[0] || '') : '';
      const pill = `<button type="button" class="apf-pill" data-ap="toggle" aria-expanded="false"${tip ? ` title="${esc(tip)}"` : ''}>
        <span class="apf-dot" aria-hidden="true"></span><span class="apf-pill-label">${esc(apPillLabel(d, m))}</span>${ICON.chev || ''}</button>`;
      // The 20s status read repaints the pill only when it changed (a screen reader re-read a focused pill
      // each time), and a repaint or the panel closing leaves focus on the pill.
      if (box.apPill === pill && box.querySelector('.apf-pill')) { yieldSoon(); return; }
      box.apPill = pill;
      if (box.removeAttribute) { box.removeAttribute('role'); box.removeAttribute('aria-label'); }
      const a = document.activeElement, hadFocus = !!(a && a !== document.body && box.contains && box.contains(a));
      box.innerHTML = pill;
      const pb = box.querySelector('.apf-pill');
      if (hadFocus && pb && pb.focus) pb.focus({ preventScroll: true });
      box.querySelector('[data-ap]').onclick = (e) => apAction(box, 'toggle', e);
      yieldSoon();
      return;
    }
    if (box.dataset.shell !== 'expanded') apBuildShell(box);
    apUpdate(box, d);
  }
  // The collapsed pill floats over the bottom-right corner, which is where pages put their actions:
  // on Research it sat on the Start session row (desktop) and covered the button (phone), and walks
  // found it on Billing's Add credits note, the run page's Pause and Cancel, and Funds' fields.
  // While it would cover anything you can press or type in, or a figure (a balance, a P&L, a stacked
  // card's number, a list's value), or the dashboard's autopilot card (which already says what the
  // pill would), it fades and lets clicks through, and comes back once that scrolls away. The body's
  // bottom padding (app.css) leaves a clear strip under every page's last row, so scrolling to the
  // foot of any page brings it back. Only what shows through counts: a figure clipped out of view by
  // its panel, or under the masthead, is not covered. Focus on the pill (keyboard) keeps it shown.
  // The open panel is left alone: the user opened it. A status mark counts too: on a 390px phone the pill sat on
  // the first Deploy card's Status marks ("Paused", "Paper"), which say which money a row is and whether it trades.
  // So does a stacked card's Market line (Strategies, Deploy) and a page's or section's heading: on a 390px phone the
  // pill sat on "ETH 15-min up/down · Volatility mispricing" as the list scrolled, and on a market page's "Price
  // history · Yes price · Kalshi hourly candles" as it opened.
  const AP_UNDER = ['a[href]', 'button', 'input', 'select', 'textarea', 'summary', '.switch', '[role="button"]', '[role="tab"]',
    '.figures .m', '.fig', 'td.num', 'dd', '.mk', '#dash-ap', 'td[data-lab="Market"]', '.board-title', '.sect-head'];
  const AP_UNDER_SEL = AP_UNDER.join(', ');
  // apYield hit-tests the page (elementsFromPoint), which lays it out and pre-paints it then and there. Run
  // from the pill's render, inside a page's first render, it fixed Research half drawn on a phone: the list
  // that moves above the form a moment later counted as a layout shift of 0.68, though no frame showed
  // it. It runs once a frame at most, once the page has drawn.
  let yieldQueued = false;
  const yieldSoon = () => {
    if (yieldQueued) return;
    yieldQueued = true;
    (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : (f) => setTimeout(f, 16))(() => { yieldQueued = false; apYield(); });
  };
  function apYield() {
    const box = document.getElementById('autopilot-float'), pill = box && box.querySelector('.apf-pill');
    if (!pill || !pill.getBoundingClientRect) { if (box) box.classList.remove('yield'); return; }
    const a = document.activeElement;
    if (a && a !== document.body && box.contains(a)) { box.classList.remove('yield'); return; }
    const p = pill.getBoundingClientRect(), pad = 8;
    const L = p.left - pad, R = p.right + pad, T = p.top - pad, B = p.bottom + pad;
    // Is the element what shows at any of five points of its overlap with the pill (the pill aside)?
    const shows = (el, r) => {
      if (typeof document.elementsFromPoint !== 'function') return true;
      const x0 = Math.max(r.left, L), x1 = Math.min(r.right, R), y0 = Math.max(r.top, T), y1 = Math.min(r.bottom, B);
      return [[(x0 + x1) / 2, (y0 + y1) / 2], [x0 + 1, y0 + 1], [x1 - 1, y0 + 1], [x0 + 1, y1 - 1], [x1 - 1, y1 - 1]].some(([x, y]) => {
        const top = document.elementsFromPoint(x, y).find((n) => !box.contains(n));
        return !!top && el.contains(top);
      });
    };
    // What can show of an element is its box cut to every ancestor that clips what overflows it. A long
    // research log scrolls inside its own box: its rows out of view sat under the pill and each one cost
    // a hit test (elementsFromPoint is slow on a phone), though the log hides them. Cut first, test after.
    const clips = new Map(), styleOf = typeof getComputedStyle === 'function' ? getComputedStyle : null;
    const visible = (el, r) => {
      if (!styleOf) return r;
      let { left, right, top, bottom } = r;
      for (let a = el.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
        let c = clips.get(a);
        if (c === undefined) {
          const st = styleOf(a);
          c = { rect: st.overflowX !== 'visible' || st.overflowY !== 'visible' ? a.getBoundingClientRect() : null, fixed: st.position === 'fixed' };
          clips.set(a, c);
        }
        if (c.rect) { left = Math.max(left, c.rect.left); right = Math.min(right, c.rect.right); top = Math.max(top, c.rect.top); bottom = Math.min(bottom, c.rect.bottom); }
        if (c.fixed) break;  // what is above a fixed box doesn't clip it
      }
      return { left, right, top, bottom, width: Math.max(0, right - left) };
    };
    const over = (r) => !!(r && r.width && r.right > L && r.left < R && r.bottom > T && r.top < B);
    // One pass over the page (it was one per kind of thing), stopping at the first thing it covers.
    let covers = false;
    for (const el of document.body.querySelectorAll(AP_UNDER_SEL)) {
      if (box.contains(el)) continue;
      const r = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
      if (!over(r)) continue;
      const v = styleOf && styleOf(el).position === 'fixed' ? r : visible(el, r);
      if (over(v) && shows(el, v)) { covers = true; break; }
    }
    box.classList.toggle('yield', covers);
  }
  const AP_FOCUS = [['', 'Any market'], ['crypto', 'Crypto only'], ['btc', 'Bitcoin only'], ['sports', 'Sports only']];
  // Why live autopilot can't be enabled yet (ordered), or '' when all gates pass.
  function apLiveBlock(d) {
    if (!d) return '';
    if (!d.autopilot) return 'Live autopilot can only be turned on after autopilot (paper) is on. It moves a strategy to real money only after the strategy has proven itself on paper, and autopilot is what runs it there. ';
    if (!d.live_enabled) return 'Live trading isn’t available on this server yet. ';  // no live button then, just this line
    if (!d.kalshi_connected) return 'Connect your Kalshi key on the Funds page first. ';
    return '';
  }
  // apLiveBlock's line as the panel shows it: "the Funds page" links to Funds' Connect Kalshi (fundsLinked).
  const apLiveBlockHtml = (d) => fundsLinked(esc(apLiveBlock(d)));
  // Read out as well as shown: the live switch, the kill switch and an unmet gate answered only in
  // print, so a reader heard nothing after pressing them. A refused press ("Connect your Kalshi key on the
  // Funds page first.", the gate's words or the server's) links "the Funds page" (fundsLinked).
  function apFlash(box, msg, kind) {
    const f = box.querySelector('#apf-flash');
    if (f) f.innerHTML = `<p class="${kind === 'bad' ? 'error-text' : 'hint'}">${fundsLinked(esc(msg))}</p>`;
    if (msg) announce(msg, kind === 'bad');
  }
  async function apAction(box, action, e) {
    if (action === 'toggle') {
      const opening = !apExpanded();
      localStorage.setItem('tau_ap_open', opening ? '1' : '0'); renderAutopilot(box, S.ap);
      // Opened, focus goes into the panel (its close button comes first); closed, back to the pill.
      const to = opening && box.querySelector('.apf-x'); if (to && to.focus) to.focus({ preventScroll: true });
      return;
    }
    if (action === 'livearm') {
      const reason = apLiveBlock(S.ap);
      if (reason) return apFlash(box, reason.trim(), 'bad');  // don't open the confirm if a gate is unmet
      const f = box.querySelector('#apf-confirm'); if (f) { f.hidden = false; f.confirm.focus(); } return;
    }
    if (action === 'livetoggle') {
      try { await api('/api/autopilot/live', { on: false }); } catch (err) { return apFlash(box, err.message, 'bad'); }
      refreshAutopilot(box);
    }
    if (action === 'kill') {
      // The shared two-step confirm: its own arming here let a fast double-click kill with no confirm.
      const btn = e && (e.currentTarget || e.target);
      if (!btn || !btn.dataset) return;
      return armed(btn, 'Confirm kill', async () => {
        try { const r = await api('/api/autopilot/kill', {}); apFlash(box, `Killed — ${r.paused} live deployment(s) paused.`); } catch (err) { return apFlash(box, err.message, 'bad'); }
        refreshAutopilot(box);
      });
    }
  }
  function hotChart(h) {
    if (!h || h.length < 2) return '<div class="hot-chart none"></div>';
    const W = 104, H = 30, p = 3, lo = Math.min(...h), hi = Math.max(...h), rng = hi - lo || 1;
    const pts = h.map((v, i) => `${(i / (h.length - 1) * (W - p * 2) + p).toFixed(1)},${(H - p - (v - lo) / rng * (H - p * 2)).toFixed(1)}`);
    const [ex, ey] = pts[pts.length - 1].split(',');
    return `<svg class="hot-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true"><polyline points="${pts.join(' ')}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${ex}" cy="${ey}" r="1.9" fill="currentColor"/></svg>`;
  }
  // When a hot market closes (`ct`, as Explore's rows say it) and, for a Bitcoin contract, how far spot is
  // from its strike; a rail with no fresh spot says why above its rows, as the list does.
  const hotWhen = (m) => (m.ct || m.vs ? `<span class="hot-when">${m.ct ? `<span>Closes ${esc(settleAt(m.ct))}</span>` : ''}${vsHtml(m)}</span>` : '');
  const hotSpotNote = (d) => (d && d.spot !== undefined && (!d.spot || d.spot.stale || d.spot.failed) ? `<p class="hot-note">${esc(spotListNote(d.spot, d.markets))}</p>` : '');
  function hotRowHtml(m) {
    const mid = midOf(m), h = m.h || [], delta = h.length >= 2 ? h[h.length - 1] - h[0] : 0;
    const dCents = Math.round(delta * 100), dir = dCents > 0 ? 'pos' : dCents < 0 ? 'neg' : '';
    return `<a class="hot-row" href="${kalshiUrl(m)}" target="_blank" rel="noopener">
      <span class="hot-title">${glueTarget(esc(mktLabel(m)))}</span>${hotWhen(m)}
      <span class="hot-mid">${hotChart(h)}<span class="hot-price"><b class="fig">${mid == null ? '—' : cents(mid)}</b>${dCents ? `<span class="hot-delta ${dir}">${dCents > 0 ? '+' : '−'}${Math.abs(dCents)}¢</span>` : ''}</span></span>
      <span class="hot-foot">${contractShort(m.t) ? `<span class="mk quiet">${esc(contractShort(m.t))}</span>` : ''}<span class="hot-vol">${kfmt(m.v24)} vol${SEP}24h</span>${ICON.ext}</span></a>`;
  }
  function renderHotRail() {
    const rail = document.getElementById('hotrail'); if (!rail) return;
    const open = hotOpen();
    const d = S.hot;
    const rows = d && d.markets && d.markets.length ? hotSpotNote(d) + d.markets.map(hotRowHtml).join('')
      : `<div class="hot-empty">${d ? 'Warming up: the hottest markets show here within a minute.' : S.hotFail ? 'Hot markets didn\u2019t load. Retrying shortly.' : loading(120)}</div>`;
    keepFocus(rail, () => { rail.innerHTML = `<button class="hot-tab" data-hot="toggle" aria-expanded="${open}" aria-label="${open ? 'Collapse hot markets' : 'Expand hot markets'}"><span class="hot-tab-label">Hot markets</span><span class="hot-chev">${open ? '‹' : '›'}</span></button>
      <div class="hot-panel">
        <div class="hot-head"><div><span class="hot-kicker">Hot markets</span><span class="hot-now"><span class="hot-dot"></span>Right now</span></div><button class="hot-x" data-hot="toggle" aria-label="Collapse hot markets">‹</button></div>
        <p class="stale-note" id="hot-stale" role="status">${hotStaleText()}</p>
        <div class="hot-list">${rows}</div>
        <div class="hot-ft">${d && d.at ? 'Updated ' + sinceMin(d.at) + SEP : ''}<a href="/explore">See all markets →</a></div>
      </div>`; });
    rail.querySelectorAll('[data-hot="toggle"]').forEach((b) => b.onclick = (e) => {
      if (e.currentTarget.classList.contains('hot-tab') && open) return; // the spine only expands
      const next = !hotOpen(); localStorage.setItem('tau_hotrail', next ? '1' : '0');
      // It slides only when you open or close it (hot-moving, app.css): a page load draws it where it is.
      document.body.classList.add('hot-moving'); clearTimeout(hotMoving); hotMoving = setTimeout(() => document.body.classList.remove('hot-moving'), 300);
      document.body.classList.toggle('hot-open', next); renderHotRail();
      const to = rail.querySelector(next ? '.hot-x' : '.hot-tab'); if (to && to.focus) to.focus({ preventScroll: true });
    });
    rail.querySelector('.hot-ft a') && (rail.querySelector('.hot-ft a').onclick = (e) => { e.preventDefault(); go('/explore'); });
  }
  // Resolves false when the read failed. The rail is repainted anyway, so its age line counts on from
  // the last snapshot's own time instead of saying "just now" for as long as reads fail.
  // One read at a time: a page that paints its shell twice (the instant switch, then its content) mounts
  // the rail twice, and Research asked for the same snapshot twice on every load.
  let hotReq = null;
  function refreshHot() {
    if (!hotReq) {
      hotReq = (async () => {
        try { S.hot = await api('/api/explore/hot', undefined, { keep: true }); S.hotFail = false; S.hotAt = Date.now(); renderHotRail(); return true; } catch (e) { S.hotFail = true; renderHotRail(); return false; }
      })();
      hotReq.then(() => { hotReq = null; });
    }
    return hotReq;
  }
  // The rail is read only while it shows (hotShown), on mounting, every HOT_POLL_MS (backing off while reads
  // fail), when it comes into view and on coming back to the tab. Hidden, nothing on the page uses the snapshot,
  // and it was one of every page's first reads on a phone.
  const hotSoon = () => { if (hotShown() && (!S.hot || !S.hotAt || Date.now() - S.hotAt > HOT_POLL_MS - 5000)) refreshHot(); };
  function mountHotRail() {
    if (!S.me || !S.me.user) return;
    document.body.classList.toggle('hot-open', hotOpen());
    if (!document.getElementById('hotrail')) { const a = document.createElement('aside'); a.className = 'hotrail'; a.id = 'hotrail'; a.setAttribute('aria-label', 'Hot markets'); document.body.appendChild(a); }
    renderHotRail();
    hotSoon();
    if (!hotLoop) { hotLoop = true;
      const tick = paced(() => refreshHot().then((ok) => { if (!ok) throw new Error('hot markets'); }), HOT_POLL_MS, () => { const el = document.getElementById('hot-stale'); if (el) el.textContent = hotStaleText(); });
      setInterval(() => { if (!document.hidden && document.getElementById('hotrail') && hotShown()) tick(); }, HOT_POLL_MS);
      wakers.add(() => { if (!document.hidden && document.getElementById('hotrail') && hotShown()) tick(true); });
      // A window widened past phone width shows the rail: it reads then.
      const wide = window.matchMedia && window.matchMedia('(max-width: 760px)');
      if (wide && wide.addEventListener) wide.addEventListener('change', () => { if (document.getElementById('hotrail')) hotSoon(); }); }
  }

  const KIND_LABEL = { bonus: 'Welcome credits', topup: 'Added credits', autoreload: 'Auto-reload', usage: 'Agent usage', admin_grant: 'Credits from Tau support' };
  // /api/me is read once per page load, and the since-strip, the research form and the autopilot card
  // read its balance and card: after a top-up they kept saying "Credits are at $0.40" until a reload.
  // Each Billing read copies its own figures over (the same reads /api/me makes), and a moved balance
  // re-reads the autopilot status at once, so a credits pause clears without waiting for its next poll.
  function syncMeBilling(d) {
    const me = S.me;
    if (!me || !d || !d.configured) return;
    const moved = me.credit_balance !== d.balance;
    me.credit_balance = d.balance;
    me.needs_card = !d.default_pm;
    const reloadWas = JSON.stringify(me.auto_reload || null);
    me.auto_reload = d.auto_reload && d.default_pm ? { amount: Math.max(d.min_reload_amount, d.autoreload_amount),
      charge: d.autoreload_charge, threshold: Math.max(d.min_reload_threshold, d.autoreload_threshold) } : null;
    // As /api/me reads it: a failed reload counts only while it can be why credits are short.
    me.reload_failed = d.reload_failed && me.auto_reload && d.balance <= me.auto_reload.threshold ? d.reload_failed.text : null;
    const box = document.getElementById('autopilot-float');
    if (moved && box && me.user && me.user.autopilot) refreshAutopilot(box);
    // A changed auto-reload (the user's own save on Billing) repaints the autopilot card's line from
    // what is already here: no status read needed.
    else if (reloadWas !== JSON.stringify(me.auto_reload) && box && S.ap) { renderAutopilot(box, S.ap); paintDashAp(); }
  }
  // How long the balance lasts at last week's spend, counted to where research pauses (under
  // min_run_balance), which autopilot users need more than the one-time welcome credit.
  // The low-credit warning (the dashboard's Needs you, the autopilot panel): days until research pauses.
  const pausesIn = (days) => `Research pauses ${days < 1 ? 'within a day' : inDays(days)} at this week’s pace, when credits fall under ${usd(S.me && S.me.min_run_balance != null ? S.me.min_run_balance : 0)}.`;
  const runwayLabel = (days) => days < 1 ? 'Under a day' : days > 90 ? 'Over 3 months' : `About ${Math.round(days)} day${Math.round(days) === 1 ? '' : 's'}`;
  // The spend a runway is read at. The server's pace_days is how many days the week's spend covers: the
  // account's age, at most 7. Under a day there is no pace yet (a first session's minutes, divided by
  // 7, read "over 3 months"); under a week it is per day so far. An older server sends none: the week.
  const paceTooSoon = (days, spent) => days != null && days < 1 && +spent > 0;
  const paceDay = (spent, days) => +spent > 0 && !(days != null && days < 1) ? +spent / (days != null ? Math.min(7, days) : 7) : null;
  const paceWords = (spent, days) => days != null && days < 7 ? `${usd(paceDay(spent, days))} a day so far` : `${usd(spent)} a week`;
  // What the card pays for `credits` plus the purchase fee, to the cent as the server charges it
  // (billing.topup_charge_cents: exact decimal, half up), worked in whole cents: $19 x 1.055 as a float
  // read $20.04 before the press while the card paid $20.05.
  const topupCharge = (credits, feePct) => {
    const c = Math.round(+credits * 100), bp = Math.round(+feePct * 100);  // cents; the fee in hundredths of a percent
    return Math.floor((c * (10000 + bp) + 5000) / 10000) / 100;
  };
  // A days figure as when something happens: "in about 2 days", "in under a day".
  const inDays = (days) => 'in ' + runwayLabel(days).toLowerCase();
  // In app-billing.js, fetched on first use (page files, at the end of this file).
  function viewBilling() { return pageView('billing', 'viewBilling', '/billing', []); }

  // ---------- admin ----------
  // In app-admin.js, fetched on first use (page files, at the end of this file).
  function viewAdmin() { return pageView('admin', 'viewAdmin', '/admin', []); }
  function viewSystem() { return pageView('admin', 'viewSystem', '/system', []); }

  // ---------- page files ----------
  // Code only some pages use ships in its own file (app-<name>.js), so a cold load downloads and
  // compiles only what its page draws: on a phone's slow network every 10KB of bundle held the first
  // figure back about 55ms. The page shell names each file's version (#tau-boot data-tau-pages,
  // app/web/page_modules.py) and preloads the one its page needs, so that file arrives beside this
  // bundle instead of a round trip after it. Once the first page has painted, the others are
  // prefetched at idle, so moving between pages stays a read away. A file that doesn't arrive fails
  // its page as a failed read does: the error, and Try again fetches the file afresh.
  const PAGES = {};  // name -> the views its file returned, once it has run
  const pageWaits = {};  // name -> its load in flight
  const PAGE_WAIT_MS = 20000, PAGE_PREFETCH_MS = 3000;
  const PAGE_FAIL = 'This page didn\u2019t load. Check your connection and try again.';
  // Each file's version from the page shell ("research:<hash>,strategies:<hash>"), or none without one.
  function pageVersions() {
    const boot = document.getElementById('tau-boot'), out = {};
    String((boot && boot.dataset && boot.dataset.tauPages) || '').split(',').forEach((p) => {
      const [name, v] = p.split(':');
      if (/^[a-z]+$/.test(name || '')) out[name] = /^[0-9a-f]+$/.test(v || '') ? v : '';
    });
    return out;
  }
  // Without a version (an older shell) the file is still found, revalidated instead of cached for good.
  const pageSrc = (name, v = pageVersions()[name]) => '/static/app-' + name + '.js' + (v ? '?v=' + v : '');
  // A page's own scripts and stylesheets beside its file (#tau-boot data-page-assets, page_modules.ASSETS):
  // Funds' native perps account, and the broker and Alpaca paper files kept with it. No shell links them
  // and the page never waits on them: its file asks for them once it has drawn (pageAssets), they start
  // loading once that frame has painted, each once, and the page mounts what needs them when they are in.
  // On a phone's slow network the Funds shell's copies held its first figure back: three render-blocking
  // stylesheets, and three deferred scripts the bundle ran behind. One that fails leaves its part out and
  // never fails the page; the next ask fetches it afresh.
  const assetWaits = {};  // url -> its load, settled or in flight
  const pageAssetSrcs = (name) => {
    const boot = document.getElementById('tau-boot');
    return String((boot && boot.dataset && boot.dataset.pageAssets) || '').split(' ')
      .map((p) => /^([a-z]+):(?:\/static\/)?([a-z.-]+\.(?:js|css)\?v=[0-9a-f]+)$/.exec(p)).filter((m) => m && m[1] === name).map((m) => '/static/' + m[2]);
  };
  const assetHere = (src) => [...document.querySelectorAll(/\.css\?/.test(src) ? 'link[rel="stylesheet"]' : 'script[src]')]
    .some((el) => el.getAttribute(/\.css\?/.test(src) ? 'href' : 'src') === src);
  // After the frame being drawn has painted: a frame's callbacks run ahead of its paint, a timeout set there after it.
  const afterPaint = (fn) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : (f) => setTimeout(f, 16))(() => setTimeout(fn, 0));
  function pageAssets(name) {
    return new Promise((resolve) => afterPaint(resolve)).then(() => Promise.all(pageAssetSrcs(name).map((src) => assetWaits[src] || (assetWaits[src] = assetHere(src) ? Promise.resolve() : new Promise((resolve) => {
      const css = /\.css\?/.test(src), el = document.createElement(css ? 'link' : 'script');
      let tid = null;
      const done = (ok) => {
        clearTimeout(tid); el.onload = el.onerror = null;
        if (!ok) { delete assetWaits[src]; apiBroke(src, false, 'did not load'); }
        resolve();
      };
      el.onload = () => done(true);
      el.onerror = () => done(false);
      tid = setTimeout(() => done(false), PAGE_WAIT_MS);
      if (css) { el.rel = 'stylesheet'; el.href = src; } else el.src = src;
      document.head.appendChild(el);
    })))));
  }
  // What this bundle's page files use from it, by name, made once (the first file to run). A file that
  // asks for a name this build doesn't share (a file from another build) throws as it runs, instead of
  // drawing with undefined, and its page fails with Try again.
  let shareMap = null;
  const shared = () => shareMap || (shareMap = new Proxy({
    actionLink, adminViewOn, alert0, announce, SEP, sepLine, gloSep, WJ, plain, AP_CARD_FIX, AP_FOCUS, AP_MODE, AP_PICKING, apAction, apSaid, depSaid, depWrite,
    apExpanded, apFlash, apFloorText, apFocusPaint, apFocusText, api, apIdleHtml, ApiError, apLastHtml, apLiveBlock, apLiveBlockHtml, fundsLinked,
    apMarketNames, apNudge, apReloadFailed, apShowFocus, apStale, apStillTrading, apStory, apSwitchOn,
    apWeek, armed, attachMention, authorLine, BEHIND, boardTitle, bookName, btCheckLine, bulkDeployable,
    busy, cardFormFail, cashAt, cashFig, cashNow, cashRead, catOrder, cents, chartWidth, clearTimers, clock, CLOCK, CLOCK_ZONE,
    clipWords, CODE_RESEARCH_ONLY, compact, contractLink, contractMarket, contractName, depIdle, kalshiRef, liveIdleCount, liveIdleShort, liveOpen, liveWaitMark, dateFmt, DEMO_BOOK, DEMO_WHAT, demoCashRead, demoHealthLine, demoKeyless, inBalance, openBasis, openCost, openFig,
    demoSpan, DEP_DONE, depActed, dirLabel, equityChart, errText, esc, EXAMPLE_NOTE, EXAMPLE_TAG,
    exampleLine, exitWord, failText, feedMd, fig, fillLiveRow, flash, fmt0, fold, gl, glo, GLOSSARY, go,
    halfUp, holdFocus, ICON, isPerpetual, KIND_LABEL, loadFail, loading, loadStripe, logTime, mark,
    marketKalshiUrl, marketLabel, marketPicker, marketShort, markQuietRows, mdLite, MKT_SHORT, money,
    notice, num, overDays, paced, paceDay, paceTooSoon, paceWords, pageAssets, paint, paintDashAp, painted, paintRows,
    paperAgain, PAPER_NET, paperCount, slipEst, slipTip, PAPER_COUNT_WHY, pausesIn, pct, PERPS_SCENARIO, phone, poll, realTrades, refreshAutopilot,
    refreshed, registry, render, researchBadge, researchOnly, roadDays, root, rpUnderwater, runKind,
    runTag, runWaitLine, runwayLabel, S, sessionTitle, settleAt, shell, sinceMin, smooth, statusMark,
    strategySlip, strategyTable, stripeFail, syncMeBilling, tone, topupCharge, tradePrice, trDay, tzName,
    usd, waitNote, waitSpan, wakers, WEEKDAY_DAY, when, whyFailedHtml, wireMarketPicker
  }, { get: (all, k) => { if (!(k in all)) throw new Error('A page file asks for ' + String(k) + ', which this build does not share.'); return all[k]; } }));
  // A page file calls this as it runs: make(shared()) returns the file's views. Once per name.
  window.TauPage = (name, make) => { if (!PAGES[name]) PAGES[name] = make(shared()); };
  function pageLoad(name) {
    if (pageWaits[name]) return pageWaits[name];
    if (PAGES[name]) return Promise.resolve(PAGES[name]);
    const src = pageSrc(name);
    return (pageWaits[name] = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      let tid = null;
      const settle = (ok) => {
        clearTimeout(tid); s.onload = s.onerror = null;
        delete pageWaits[name];
        if (ok && PAGES[name]) return void resolve(PAGES[name]);
        if (s.parentNode) s.parentNode.removeChild(s);
        apiBroke(src, false, 'did not load');
        reject(new ApiError(0, PAGE_FAIL));
      };
      s.onload = () => settle(true);
      s.onerror = () => settle(false);
      tid = setTimeout(() => settle(false), PAGE_WAIT_MS);
      s.src = src;
      document.head.appendChild(s);
    }));
  }
  // The router's stand-in for a view in a page file: the view itself once the file has run; until then
  // the page's skeleton under its nav, the file, and the view, unless the user has moved on meanwhile.
  // A page without the app's shell (nav null: Terms and Privacy, signed out too) waits as boot does,
  // on the splash after a moment, and a file that doesn't arrive says so there with Try again.
  async function pageView(name, view, nav, args) {
    if (!PAGES[name] || pageWaits[name]) {
      const gen = S.gen;
      if (nav) {
        shell(nav, loading(120), loading(320));
        await pageLoad(name);
      } else {
        const tid = setTimeout(() => { if (gen === S.gen) root.innerHTML = bootSplash(); }, 250);
        try { await pageLoad(name); } catch (e) { if (gen === S.gen) bootFail(PAGE_FAIL); return; } finally { clearTimeout(tid); }
      }
      if (gen !== S.gen) return;
    }
    return PAGES[name][view](...args);
  }
  // Once, after the first page has painted: the other page files at the lowest priority
  // (rel=prefetch, into the browser's cache), so a first visit to each page doesn't wait on its file.
  let pagesPrefetched = false;
  function pagePrefetch() {
    if (pagesPrefetched) return;
    pagesPrefetched = true;
    const all = pageVersions();
    if (!Object.keys(all).length || !document.head) return;
    setTimeout(() => {
      for (const [name, v] of Object.entries(all)) {
        if (PAGES[name] || pageWaits[name]) continue;
        for (const href of [pageSrc(name, v), ...pageAssetSrcs(name).filter((src) => !assetWaits[src] && !assetHere(src))]) {
          const l = document.createElement('link');
          l.rel = 'prefetch'; l.href = href;
          document.head.appendChild(l);
        }
      }
    }, PAGE_PREFETCH_MS);
  }

  setupAnnouncer();
  guardArmedRepeat();
  copyPlain();
  netBar();
  setupGlossary();
  render();
})();
