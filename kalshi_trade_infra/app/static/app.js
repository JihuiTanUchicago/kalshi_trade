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
    unseen: ['Unseen data', 'A held-out slice of history the agent never looks at while searching, so the result can’t be curve-fit. This is the P&L that counts.'],
    insample: ['In-sample', 'The history the agent iterates on. Strong in-sample numbers are easy to overfit, so they only shortlist a strategy — they never pass it.'],
    gate: ['Gates', 'The pass/fail checks a strategy must clear on unseen data: it makes money, trades often enough to judge, and its wins outweigh losses after fees.'],
    pace: ['Backtest estimate', 'What these same closed trades would have made if each had earned the strategy’s backtest average per trade on unseen data. Compare it with Realized: well below it means trading is falling short of the test.'],
  };
  // One drawn marker; a single top-layer popover serves them all (no clipping in tables).
  const glo = (key) => `<button type="button" class="info" data-glo="${key}" aria-label="What does “${GLOSSARY[key][0]}” mean?">${ICON.info}</button>`;
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
  const usd = (v, signed = false) => {
    if (v == null || Number.isNaN(+v)) return '—';
    const n = +v;
    const s = '$' + (Math.abs(n) >= 100000 ? fmt0.format(Math.abs(n)) : fmt2.format(Math.abs(halfUp(n))));
    if (n < 0) return '−' + s;
    return signed && n > 0 ? '+' + s : s;
  };
  const pct = (v, signed = true) => (v == null ? '—' : (v < 0 ? '−' : signed && v > 0 ? '+' : '') + Math.abs(v * 100).toFixed(1) + '%');
  // Kalshi quotes some markets in tenths of a cent: 0.1¢ read as 0¢ and a 99.9¢ bid as 100¢.
  const cents = (v) => (v == null ? '—' : Math.round(v * 1000) / 10 + '¢');
  const isPerpetual = (s) => s.kind === 'perpetual' || s.market === 'btc_perp' || s.key === 'btc_perp' || (s.spec && s.spec.market === 'btc_perp');
  const researchOnly = (s) => s.research_only === true || isPerpetual(s);
  const researchBadge = (s) => researchOnly(s) ? '<span class="mk quiet">Research only</span>' : '';
  // A strategy written as code (the server's kind "code") runs only in the research sandbox: the server
  // refuses to deploy it in any mode, so its page offers no deploy button and says what to do instead.
  const CODE_RESEARCH_ONLY = 'Strategies written as code run only in the research sandbox, even after passing every check: paper, demo and live trading run rule-based strategies only. To trade this idea, ask for a rule-based version in a new research session.';
  const perpsPrice = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6});
  const tradePrice = (v, perpetual) => perpetual ? (!['number', 'string'].includes(typeof v) || String(v).trim() === '' || !Number.isFinite(Number(v)) ? '—' : perpsPrice.format(Number(v))) : cents(v);
  const PERPS_SCENARIO = 'Research scenario: at most 1× capital, fixed 12 bps taker fees and 5 bps adverse slippage per fill, plus settled funding. These are uncalibrated cost assumptions; fills use the next bar’s open. No margin or liquidation model. Short losses can exceed capital.';
  const tone = (v) => (v > 0 ? 'gain' : v < 0 ? 'loss' : '');
  const serial = (n) => 'No. ' + String(n).padStart(5, '0');
  const when = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    const s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };
  // A bell item's time: relative within the day, then the day and clock ("Oct 24, 14:05"), not a bare
  // date; the full stamp with its zone rides on hover.
  const bellTime = (iso) => {
    const d = new Date(iso || NaN);
    if (!Number.isFinite(d.getTime())) return '';
    const day = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
    const shown = Date.now() - d.getTime() < 86400000 ? when(iso) : d.toLocaleString(undefined, day);
    return `<time datetime="${esc(iso)}" title="${esc(d.toLocaleString(undefined, { ...day, timeZoneName: 'short' }))}">${esc(shown)}</time>`;
  };
  // Each date format is built once and reused: toLocaleString with options builds a new formatter on
  // every call, and a 600-event research log spent ~0.3s of a phone's first paint on its clocks.
  const fmts = new Map();
  const dateFmt = (d, o) => {
    if (!Number.isFinite(d.getTime())) return 'Invalid Date';  // what toLocaleString says; format() throws
    let f = fmts.get(o);  // keyed by the options object: pass a constant
    if (!f) { f = new Intl.DateTimeFormat(undefined, o); fmts.set(o, f); }
    return f.format(d);
  };
  const CLOCK = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };
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
    return d.toLocaleString(undefined, { ...(today ? {} : { month: 'short', day: 'numeric' }), hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' });
  };  // fits the 40px log rail; '10:31 AM' wrapped to 'AM'
  const num = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US'));
  // Compact count for tight spaces (system-map node metrics): 1.1M, 352k, 940.
  const compact = (n) => (n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : num(n));
  const age = (sec) => (sec == null ? 'never' : sec < 90 ? sec + 's' : sec < 5400 ? Math.round(sec / 60) + 'm' : sec < 172800 ? Math.round(sec / 3600) + 'h' : Math.round(sec / 86400) + 'd');
  const marketLabel = (k) => ((S.me && S.me.markets.find((m) => m.key === k)) || { label: k }).label;
  // Short, consistent chip labels for every market; unknown keys fall back to the
  // server's full label, never the raw key (keeps the market chips uniform).
  const MKT_SHORT = {
    btc15m: 'BTC 15-min', btc15m_tick: 'BTC 15-min ·\u00a0per second', btc_perp: 'BTC perp', btc_daily: 'BTC 5pm', eth15m: 'ETH 15-min', eth_daily: 'ETH 5pm',
    sol15m: 'SOL 15-min', sol_daily: 'SOL 5pm', xrp15m: 'XRP 15-min', xrp_daily: 'XRP 5pm',
    doge15m: 'DOGE 15-min', near15m: 'NEAR 15-min', zec15m: 'ZEC 15-min', hype15m: 'HYPE 15-min',
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
  // The readable market a contract ticker belongs to, by its series prefix (KXBTCD-26OCT2617-T68499.99 is
  // "Bitcoin daily close, 5pm EDT"), so an open position never shows only the raw ticker. Unknown: ''.
  const contractMkt = (ticker) => ((S.me && S.me.markets) || []).find((x) => x.series && String(ticker || '').startsWith(x.series + '-'));
  const contractMarket = (ticker) => {
    const m = contractMkt(ticker);
    return m ? (m.label || marketShort(m.key)) : '';
  };
  // A contract ticker that opens its market page (price, settlement rules, your positions in it).
  const contractLink = (ticker) => `<a href="/explore?m=${encodeURIComponent(ticker)}">${esc(ticker)}</a>`;
  // A Kalshi series (KXBTC15M, a hot-markets row's `s`) as the app names its market ("BTC 15-min"); '' for a
  // series no market here covers, so a chip is left off rather than showing the raw series.
  const seriesMarket = (s) => {
    const m = s && ((S.me && S.me.markets) || []).find((x) => x.series && x.series.toUpperCase() === String(s).toUpperCase());
    return m ? marketShort(m.key) : '';
  };
  // Link a strategy's market to its Kalshi series page.
  const marketKalshiUrl = (k) => { const m = (S.me && S.me.markets || []).find((x) => x.key === k); return m && m.series ? `https://kalshi.com/markets/${m.series.toLowerCase()}` : null; };
  const dirLabel = (k) => { if (!k) return 'Session'; const d = S.me && S.me.directions.find((x) => x.key === k); return d ? d.label : String(k).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()); };
  const sessionTitle = (r) => (r.prompt && r.prompt.trim()) ? r.prompt.trim() : (dirLabel(r.direction) + ' \u00b7\u00a0' + marketShort(r.market));

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
    face.querySelector('[data-vol]').textContent = `${kfmt(m.vol24)} vol \u00b7\u00a024h`;
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
    const gen = S.gen, scoped = body === undefined && !(cfg && cfg.keep);
    const opts = { credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-Recursive'] = '1';
      opts.body = JSON.stringify(body);
    }
    // Optional timeout (used on the boot /api/me call so a slow/overloaded server can't hang the
    // whole app on a blank screen). AbortController fires an abort the fetch rejects on.
    let ctl, tid;
    if (cfg && cfg.timeoutMs) { ctl = new AbortController(); opts.signal = ctl.signal; tid = setTimeout(() => ctl.abort(), cfg.timeoutMs); }
    let res;
    // A GET that hits a restart (a deploy takes the server away for a second, and CloudFront
    // answers 502/503/504 with its own non-JSON page) retries twice before the page shows an
    // error. A JSON error is Tau itself answering, so it is final. Writes never retry.
    for (let attempt = 0; ; attempt++) {
      try { res = await fetch(path, opts); }
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
  const signinPath = () => /^\/(?:|signin|dashboard)$/.test(location.pathname) ? '/signin' : '/signin?next=' + encodeURIComponent(location.pathname + location.search);
  const signinNext = () => { const n = new URLSearchParams(location.search).get('next'); return n && n[0] === '/' && n[1] !== '/' ? '?next=' + encodeURIComponent(n) : ''; };
  function go(path, replace) {
    if (replace) history.replaceState(null, '', path); else history.pushState(null, '', path);
    render();
  }
  window.addEventListener('popstate', render);
  document.addEventListener('click', (e) => {
    // In-page "#id" links scroll to their target: letting the hash navigate fires popstate, whose
    // re-render dropped the reader back at the top of the page.
    const h = e.target.closest('a[href^="#"]');
    const to = h && h.getAttribute('href').length > 1 && document.getElementById(h.getAttribute('href').slice(1));
    if (to) {
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
  window.addEventListener('online', () => {
    wakers.forEach((w) => { if (w() === false) wakers.delete(w); });
    if (document.getElementById('bootretry')) { render(); return; }
    root.querySelectorAll('.load-fail [data-retry]').forEach((b) => b.click());
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

  // A new page in the app names itself in the tab title and puts keyboard focus at its top (<main>), as a
  // full page load would: a screen reader says where it landed, and Tab starts from the page instead of
  // from the link the repaint removed. The first page of a visit and a repaint of the same page leave
  // focus alone, and so does a page that already put focus somewhere (a field it opened).
  let shownPath = null;
  function pageArrived(path) {
    const h = root.querySelector('h1'), tab = root.querySelector('.services [aria-current="page"]');
    // The signed-out landing keeps the plain product name; its headline is not a page name.
    const name = root.querySelector('.services') ? ((h && h.textContent) || (tab && tab.textContent) || '').replace(/\s+/g, ' ').trim() : '';
    document.title = name ? `${name.length > 60 ? name.slice(0, 59) + '\u2026' : name} \u00b7\u00a0Tau` : 'Tau';
    const moved = shownPath !== null && shownPath !== path;
    shownPath = path;
    const a = document.activeElement, main = document.getElementById('main');
    if (moved && main && main.focus && (!a || a === document.body)) main.focus({ preventScroll: true });
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
        shell('', boardTitle('Not found'), `<div class="load-fail">${notice(e.message, 'bad')}<a class="btn sm" href="${label ? up : '/'}">${label || 'Dashboard'}</a></div>`);
      } else if (gen === S.gen && e.status !== 401) {
        shell('', boardTitle('Something went wrong'), loadFail(errText(e)));
        root.querySelector('[data-retry]').onclick = () => render();
      }
    }
    if (gen !== S.gen) return;  // the user moved on while this page loaded
    root.setAttribute('aria-busy', 'false');
    pageArrived(path);
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
        <aside class="pay-show">
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
    try {
      const state = await api('/api/billing', undefined, { keep: true });
      if (!state.configured) { dlg.querySelector('#pay-el').innerHTML = ''; hint.innerHTML = '<p class="wl-err">Payments aren’t enabled on this server yet.</p>'; dlg.querySelector('#pay-submit').setAttribute('aria-disabled', 'true'); return; }
      // What the card will be charged, before it is saved: nothing now, and auto-reload is on by default.
      const terms = dlg.querySelector('#pay-terms');
      terms.textContent = 'Saving the card charges nothing.' + (state.auto_reload && state.autoreload_charge
        ? ` Auto-reload is on: when your credits fall to ${usd(state.autoreload_threshold)}, we charge the card ${usd(state.autoreload_charge)} for ${usd(state.autoreload_amount)} more. You can turn it off on Billing.` : '');
      terms.hidden = false;
      const Stripe = await loadStripe();
      const sp = Stripe(state.publishable_key);
      const si = await api('/api/billing/setup-intent', {});
      const elements = sp.elements({ clientSecret: si.client_secret, appearance: { theme: 'flat', variables: { fontFamily: 'Archivo, sans-serif', colorPrimary: '#191B16', borderRadius: '10px' } } });
      // Trim the form: no billing address (not needed to save a card), wallets on.
      const pe = elements.create('payment', { layout: 'tabs', wallets: { applePay: 'auto', googlePay: 'auto' }, fields: { billingDetails: { address: { country: 'never' } } } });
      dlg.querySelector('#pay-el').innerHTML = '';
      pe.mount('#pay-el');
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
      list.querySelectorAll('.notif-new').forEach((n) => n.remove());
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
      list.innerHTML = d.items.length ? d.items.map(item).join('') : '<p class="bell-empty">No notifications yet.</p>';
    };
    let data = { unread: 0, items: [] };
    // The shell is often painted twice in a row (instant page switch, then content): one read serves both.
    if (!bellReq || Date.now() - bellReqAt > 2000) { bellReq = api('/api/notifications', undefined, { keep: true }); bellReqAt = Date.now(); }
    try { data = await bellReq; paint(data); } catch (e) { return; }  // bell is best-effort
    // Autopilot pauses or readies a strategy while the page sits open: the dot shows it within a minute,
    // without a reload (bellTick). An open list is left as the reader sees it.
    bellFresh = (d) => { if (menu.hidden) { data = d; paint(d); } };
    trig.onclick = async (e) => {
      e.stopPropagation();
      if (!menu.hidden) { close(); return; }
      menu.hidden = false; trig.setAttribute('aria-expanded', 'true'); document.addEventListener('click', onDoc, true);
      // Focus goes into the list (its first notice, or the list itself when it is empty), so Tab and a
      // screen reader carry on from what just opened; Esc brings it back to the bell.
      (list.querySelector('a.notif') || menu).focus({ preventScroll: true });
      if (data.unread) {
        // Read from here on, also for a repaint that reuses this reply; the marks clear on close.
        data.unread = 0; data.items.forEach((n) => { n.read = true; }); dot.hidden = true; trig.setAttribute('aria-label', 'Notifications');
        api('/api/notifications/read', {}).catch(() => {});
      }
    };
    // Esc closes the list and gives focus back to the bell.
    wrap.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) { close(); trig.focus(); } });
    // Tabbing past the last notification left the list open behind the page, where Esc (bound here) no
    // longer reached it: focus leaving the bell closes the list, as a click outside already does.
    wrap.addEventListener('focusout', (e) => { if (!menu.hidden && !wrap.contains(e.relatedTarget)) close(); });
    // Opening a notice closes the list first, so its click-outside listener doesn't outlive the page.
    list.addEventListener('click', (e) => { if (e.target.closest('a.notif')) close(); });
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
    root.innerHTML = `
      <header class="masthead"><div class="masthead-in">
        <p class="wordmark"><a href="/">${ICON.mark}<span>Tau</span></a></p>
        <span class="asof">${adminToggle}<span class="bell-wrap"><button class="bell-trig" data-action="bell" aria-controls="bell-menu" aria-expanded="false" aria-label="Notifications"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg><span class="bell-dot" hidden></span></button><span class="bell-menu" id="bell-menu" role="region" aria-label="Notifications" tabindex="-1" hidden><div class="bell-head"><b>Notifications</b></div><div class="bell-list" id="bell-list"></div></span></span><span class="profile"><button class="profile-trig" data-action="profile" aria-haspopup="true" aria-expanded="false">${esc(u.name || u.email)}<svg class="profile-chev" width="9" height="9" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg></button><span class="profile-menu" hidden><a href="/settings">Settings</a><a href="/billing">Billing</a><a href="/terms">Terms</a><a href="/privacy">Privacy</a><button class="profile-item" data-action="signout">Sign out</button></span></span></span>
      </div></header>
      <nav class="services" aria-label="Sections"><div class="services-in">${nav}</div></nav>
      <div class="wrap">
        <div id="boardbody">${board}</div>
        <main id="main" tabindex="-1">${main}</main>
      </div>`;
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
    try { d = await api('/api/devlog'); } catch (e) { root.querySelector('main').innerHTML = notice(e.message, 'bad'); return; }
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
    root.querySelector('main').innerHTML = `
      <div class="chips dl-tabs" role="group" aria-label="Dev Logs view">
        <button class="chip" type="button" data-dltab="planned" aria-pressed="${tab === 'planned'}">Up next</button>
        <button class="chip" type="button" data-dltab="shipped" aria-pressed="${tab === 'shipped'}">Shipped ·\u00a0${shippedCount}</button>
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
  const fig = (label, value, opts = {}) =>
    `<div class="m ${opts.cls || ''}"><dt class="lab">${label}</dt><dd><span class="fig ${opts.v > 0 ? 'tint pos' : opts.v < 0 ? 'tint neg' : ''}">${value}</span></dd>${opts.small ? `<div class="sub-fig">${opts.small}</div>` : ''}</div>`;
  const dirTag = () => '';
  // quiet: the words go out through announce(), so the notice leaves off its own live role (read once).
  const notice = (msg, kind = '', quiet) => `<div class="notice ${kind}"${quiet ? '' : ` role="${kind === 'bad' ? 'alert' : 'status'}"`}>${kind === 'good' ? ICON.check : ICON.warn}<span>${esc(msg)}</span></div>`;
  // A failed load says so and offers a retry, instead of leaving a skeleton up for good.
  const loadFail = (msg) => `<div class="load-fail">${notice(msg, 'bad')}<button type="button" class="btn sm" data-retry>Try again</button></div>`;
  // A page's own bug (a TypeError on a reply it didn't expect) is not something to print to the user.
  // It is reported (reportBroken), so a page that breaks this way shows up on /admin.
  const errText = (e) => (e instanceof ApiError ? e.message : (reportBroken('view', e), 'Something went wrong on this page. Try again.'));
  const loading = (h = 160) => `<div class="skeleton" style="height:${h}px" aria-label="Loading"></div>`;
  // Boot screens: shown only while /api/me is in flight (splash) or after it timed out / failed
  // transiently (fail). Reuses the landing wordmark + spinner so it's on-world with zero new look.
  const bootSplash = () => `<div class="boot"><div class="lbrand">${ICON.mark}<span>Tau</span></div><div class="lspin" aria-label="Loading Tau"></div></div>`;
  function bootFail() {
    root.innerHTML = `<div class="boot"><div class="lbrand">${ICON.mark}<span>Tau</span></div>
      <p class="boot-msg">Tau is taking longer than usual to load — it may be briefly busy.</p>
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
    if (btn.dataset.armed === '1') { btn.dataset.armed = ''; btn.classList.remove('armed'); armTurns.delete(btn); return fire(); }
    if (btn.dataset.armed === 'wait') return;
    const orig = btn.innerHTML, turn = {};
    armTurns.set(btn, turn);
    btn.dataset.armed = 'wait'; btn.classList.add('armed'); btn.textContent = label;
    announce(`${label}: press again within 5 seconds.`);
    setTimeout(() => { if (armTurns.get(btn) === turn && btn.dataset.armed === 'wait') btn.dataset.armed = '1'; }, ARM_HOLD);
    setTimeout(() => { if (armTurns.get(btn) === turn && btn.dataset.armed) { btn.dataset.armed = ''; btn.classList.remove('armed'); btn.innerHTML = orig; armTurns.delete(btn); } }, 5000);
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
  // A control that goes disabled is blurred by the browser, which dropped keyboard focus to the top of
  // the page on every busy action (Turn on autopilot, Buy credits, Start session, Verify and connect):
  // focus goes back to the button once it is enabled again, unless the action moved focus itself or
  // repainted the button away.
  async function busy(btn, fn) {
    const had = document.activeElement === btn;
    btn.classList.add('busy'); btn.disabled = true;
    try { return await fn(); } finally {
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
    el.innerHTML = html;
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
    return `<svg class="spark ${last > 0 ? 'up' : last < 0 ? 'down' : 'flat'}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}"><line class="spark-zero" x1="0" x2="${W}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" vector-effect="non-scaling-stroke"/><polyline points="${pts}" vector-effect="non-scaling-stroke"/></svg>`;
  }
  // devCurve (optional): a second, realized series replayed read-only against
  // the Kalshi demo environment. Drawn dashed in the accent colour with a legend
  // so "Simulated" and "Kalshi dev" read apart. Omitting it keeps the old chart.
  // Draw at the column's real width on a narrow screen: a 760-wide chart shrunk to a phone has 4px labels.
  const chartWidth = () => { const m = root.querySelector('main'), w = m && m.clientWidth; return w > 0 && w < 760 ? Math.max(300, w) : 760; };
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
    const ticks = [lo, (lo + hi) / 2, hi].map((v) => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${usd(v)}</text>`).join('');
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const legend = dev ? `<g transform="translate(${L},${T - 12})">
        <line x1="0" x2="16" y1="0" y2="0" stroke="var(--ink)" stroke-width="2"/><text x="20" y="4" style="fill:var(--ink-2)">Simulated</text>
        <line x1="92" x2="108" y1="0" y2="0" stroke="var(--l-accent, #F05A28)" stroke-width="2" stroke-dasharray="5 4"/><text x="112" y="4" style="fill:var(--ink-2)">Kalshi dev (real)</text>
      </g>` : '';
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative profit and loss over the backtest${dev ? ', with a realized Kalshi demo-environment curve' : ''}; ends at ${usd(vals[vals.length - 1], true)}">
      ${cx ? `<rect x="${cx}" y="${T}" width="${W - R - cx}" height="${H - T - B}" fill="var(--stock-raised)"/>
              <line x1="${cx}" x2="${cx}" y1="${T}" y2="${H - B}" stroke="var(--ink-3)" stroke-dasharray="4 4"/>
              ${unseenLabel(cx, W - R, T - 10)}` : ''}
      <line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--rule-2)"/>
      ${ticks}
      <text x="${L}" y="${H - 6}">${day(t0)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>
      <polyline points="${line(curve)}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round"/>
      ${dev ? `<polyline points="${line(dev)}" fill="none" stroke="var(--l-accent, #F05A28)" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>` : ''}
      ${legend}
    </svg>`;
  }

  // ---------- strategy research paper (RESEARCH_PIPELINE_DESIGN.md §D) ----------
  // Charts are inline SVG built here (CSP is script-src 'self'; no inline <script>).
  // Phase colours reuse Kursbuch tokens: in-sample = muted ink, validation = ink,
  // holdout = signal red (the one decisive, one-time forward test). Every colour is
  // paired with a text label, never carried by colour alone.
  // A per-trade net return (net P&L over what the trade cost) as a percent of its stake: the unit the
  // gatekeeper judges and the "What it missed" lines use. It read as cents ("+3.10¢"), which it isn't.
  const rpRet = (v) => (v == null ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(2) + '%');
  const rpProb = (v, d = 3) => (v == null ? '—' : Number(v).toFixed(d));
  const rpInt = (v) => (v == null ? '—' : num(v));
  const rpText = (v) => esc(v == null ? '' : String(v));
  const rpHuman = (k) => String(k).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  // The gatekeeper's pre-registration names its metric and test in code words; say them plainly.
  const rpPlain = (t) => String(t).replace(/\bmean_net_return_per_trade\b/g, 'average net return per trade, after fees')
    .replace(/\bstationary_bootstrap( one-sided)?/g, (m, one) => (one ? 'one-sided ' : '') + 'bootstrap test (resamples its trades in blocks)').replace(/\balpha from\b/g, 'significance bar from')
    .replace(/\b([a-z]+)_([a-z_]+)\b/g, (m) => m.replace(/_/g, ' '));
  const LORD_WORDS = ' (a false-discovery control: it keeps count of every idea tested, so lucky passes stay rare)';
  const rpStamp = (iso) => { try { return new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch (e) { return String(iso); } };
  // The gatekeeper stores each phase as its per-trade net returns ([ts, return] per trade), not a running
  // total. The equity and drawdown figures add them up, counted in stakes (+2× = twice one trade's stake);
  // the distribution plots each one. They were drawn as a dollar curve, and the distribution as the
  // differences between neighbouring trades.
  const rpCum = (series) => { let c = 0; return (series || []).map(([t, r]) => [t, (c += +r || 0)]); };
  const rpStakes = (v) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1) + '×';
  const RP_MECH = { who_pays: 'Who pays', why_not_arbitraged: 'Why it isn’t arbitraged', when: 'When it fires', why_persists: 'Why it persists' };
  const RP_RUNGS = [['promising', 'Promising'], ['statistically_supported', 'Stat. supported'], ['forward_validated', 'Forward-validated'], ['deployment_candidate', 'Deployment candidate']];
  const RP_RANK = { rejected: -1, inconclusive: 0, promising: 1, statistically_supported: 2, forward_validated: 3, deployment_candidate: 4 };

  // `reached`: the validation verdict. A strategy that cleared validation and then failed the holdout
  // has the holdout's verdict as its latest, so the ladder lit no rung, as if it never got past research.
  function rpLadder(cls, reached, where) {
    const rank = Math.max(RP_RANK[cls] == null ? 0 : RP_RANK[cls], RP_RANK[reached] || 0);
    const got = rank > 0 && rank > (RP_RANK[cls] || 0) ? RP_RUNGS[rank - 1][1] : '';
    const rungs = RP_RUNGS.map(([k, label], i) => {
      const r = i + 1, state = r === rank ? 'lit' : r < rank ? 'done' : '';
      return `<div class="rung ${state}"><div class="r-n">Rung ${r}</div><div class="r-t">${esc(label)}</div></div>`;
    }).join('');
    let terminal = '';
    if (got && (cls === 'rejected' || cls === 'inconclusive')) terminal = `<div class="rp-terminal${cls === 'inconclusive' ? ' quiet' : ''}"><span><b>${cls === 'rejected' ? 'Rejected' : 'Inconclusive'}</b> ${esc(where || 'at its last check')} — it reached ${esc(got)} in validation, then its edge did not hold up.</span></div>`;
    else if (cls === 'rejected') terminal = `<div class="rp-terminal"><span><b>Rejected</b> — this hypothesis did not advance the ladder.</span></div>`;
    else if (cls === 'inconclusive') terminal = `<div class="rp-terminal quiet"><span><b>Inconclusive</b> — tested, but the evidence was too weak to move it up.</span></div>`;
    return `<div class="ladder">${rungs}</div>${terminal}`;
  }

  // 1. equity by phase — each phase its own OOS run, colour + labelled, one axis.
  function rpPhaseEquity(phases) {
    phases = phases.filter((p) => p.curve && p.curve.length > 1);
    if (!phases.length) return `<div class="rp-empty">No phase equity curves recorded yet.</div>`;
    const W = 720, H = 200, L = 48, R = 10, T = 16, B = 24;
    const pts = [].concat(...phases.map((p) => p.curve));
    const t0 = Math.min(...pts.map((q) => q[0])), t1 = Math.max(...pts.map((q) => q[0]));
    const vals = pts.map((q) => q[1]);
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const line = (c, col) => `<polyline points="${c.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ')}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>`;
    const ticks = [lo, (lo + hi) / 2, hi].map((v) => `<text x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${rpStakes(v)}</text>`).join('');
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const bounds = phases.slice(1).map((p) => { const bx = x(p.curve[0][0]).toFixed(1); return `<line x1="${bx}" x2="${bx}" y1="${T}" y2="${H - B}" stroke="var(--rule-2)" stroke-dasharray="3 4"/>`; }).join('');
    const legend = `<div class="rp-legend">${phases.map((p) => `<span><i style="background:${p.color}"></i>${esc(p.label)}</span>`).join('')}</div>`;
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Running total of net return per trade, counted in stakes, by research phase: ${esc(phases.map((p) => p.label).join(', '))}">
      <line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="var(--rule-2)"/>
      ${ticks}
      <text x="${L}" y="${H - 6}">${day(t0)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>
      ${bounds}${phases.map((p) => line(p.curve, p.color)).join('')}
    </svg>${legend}`;
  }

  // 2. validation vs locked holdout mean: did the edge hold up on data it had never met? (This compared
  // "in-sample" with validation, but its in-sample bar was the validation slices' own average.)
  function rpShrinkage(valMean, holdMean) {
    const bars = [];
    if (valMean != null) bars.push(['Validation', valMean, 'var(--ink)']);
    if (holdMean != null) bars.push(['Holdout', holdMean, 'var(--signal)']);
    if (!bars.length) return `<div class="rp-empty">No validation or holdout average to compare.</div>`;
    const W = 340, H = 180, T = 24, Bm = 30, L = 10, R = 10;
    const mags = bars.map((b) => b[1]);
    let lo = Math.min(0, ...mags), hi = Math.max(0, ...mags);
    if (hi - lo < 1e-4) { hi += 0.005; lo -= 0.005; }
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - Bm);
    const zero = y(0), slot = (W - L - R) / bars.length, bw = Math.min(64, slot * 0.5);
    const cells = bars.map((b, i) => {
      const cx = L + slot * i + slot / 2, top = Math.min(y(b[1]), zero), h = Math.max(1, Math.abs(y(b[1]) - zero));
      return `<rect x="${(cx - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${b[2]}" rx="3"/>
        <text x="${cx.toFixed(1)}" y="${(b[1] >= 0 ? top - 6 : top + h + 14).toFixed(1)}" text-anchor="middle" style="fill:var(--ink)">${rpRet(b[1])}</text>
        <text x="${cx.toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(b[0])}</text>`;
    }).join('');
    let note = holdMean == null ? '<div class="cap">The locked holdout hasn’t run yet, so there is nothing to compare the validation average with.</div>' : '';
    if (valMean != null && holdMean != null && valMean > 0) {
      const shr = Math.round((1 - holdMean / valMean) * 100);
      note = `<div class="cap">Average net return per trade, as % of its stake. The holdout's is ${shr >= 0 ? shr + '% smaller' : Math.abs(shr) + '% larger'} than validation's — ${shr >= 100 ? 'the edge did not hold up on fresh data' : shr >= 40 ? 'heavy shrinkage, a sign the validation edge was partly luck' : 'it held up on fresh data'}.</div>`;
    }
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Validation versus locked holdout average net return per trade">
      <line x1="${L}" x2="${W - R}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}" stroke="var(--rule-2)"/>${cells}
    </svg>${note}`;
  }

  // 3. underwater drawdown.
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
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Underwater drawdown plot from ${day(t0)} to ${day(t1)}; worst drawdown ${maxDd}">
      <polygon points="${area}" fill="var(--signal-wash)" stroke="none"/>
      <polyline points="${curvePts}" fill="none" stroke="var(--signal)" stroke-width="1.6"/>
      <line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="var(--rule-2)"/>
      <text x="${L - 8}" y="${(y(0) + 4).toFixed(1)}" text-anchor="end">0</text>
      <text x="${L - 8}" y="${(y(minDd) + 4).toFixed(1)}" text-anchor="end">${maxDd}</text>
      <text x="${L}" y="${H - 6}">${day(t0)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>
    </svg>`;
  }

  // 4. per-trade return distribution with the bootstrap CI band + break-even line.
  function rpReturnDist(returns, ciLo, ciHi, mean) {
    returns = (returns || []).filter((v) => v != null && isFinite(v));
    if (returns.length < 3) return `<div class="rp-empty">Too few trades to plot a return distribution.</div>`;
    const W = 720, H = 200, L = 20, R = 12, T = 16, B = 26;
    let lo = Math.min(...returns), hi = Math.max(...returns);
    lo = Math.min(lo, 0, ciLo == null ? 0 : ciLo); hi = Math.max(hi, 0, ciHi == null ? 0 : ciHi);
    if (hi - lo < 1e-6) { hi += 0.01; lo -= 0.01; }
    const bins = Math.min(29, Math.max(9, Math.round(Math.sqrt(returns.length)))), bwid = (hi - lo) / bins, counts = new Array(bins).fill(0);
    returns.forEach((v) => { let b = Math.floor((v - lo) / bwid); if (b >= bins) b = bins - 1; if (b < 0) b = 0; counts[b]++; });
    const maxC = Math.max(...counts), base = H - B;
    const px = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
    const py = (c) => T + (1 - c / maxC) * (base - T);
    const band = (ciLo != null && ciHi != null) ? `<rect x="${px(ciLo).toFixed(1)}" y="${T}" width="${Math.max(1, px(ciHi) - px(ciLo)).toFixed(1)}" height="${(base - T).toFixed(1)}" fill="var(--stock-raised)"/>` : '';
    const gap = 2, barW = Math.max(1, (W - L - R) / bins - gap);
    const bars = counts.map((c, i) => c ? `<rect x="${(px(lo + i * bwid) + gap / 2).toFixed(1)}" y="${py(c).toFixed(1)}" width="${barW.toFixed(1)}" height="${(base - py(c)).toFixed(1)}" fill="var(--ink)"/>` : '').join('');
    const zeroLine = `<line x1="${px(0).toFixed(1)}" x2="${px(0).toFixed(1)}" y1="${T}" y2="${base}" stroke="var(--rule-2)"/><text x="${px(0).toFixed(1)}" y="${H - 8}" text-anchor="middle">break-even</text>`;
    const meanLine = mean != null ? `<line x1="${px(mean).toFixed(1)}" x2="${px(mean).toFixed(1)}" y1="${T}" y2="${base}" stroke="var(--signal)" stroke-width="1.5" stroke-dasharray="4 3"/>` : '';
    const legend = `<div class="rp-legend"><span><i style="background:var(--ink)"></i>Per-trade net return</span>${ciLo != null ? `<span><i style="background:var(--stock-raised);border:1px solid var(--rule-2)"></i>90% CI of the mean</span>` : ''}${mean != null ? `<span><i class="dash" style="color:var(--signal)"></i>Mean</span>` : ''}</span></div>`;
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Distribution of per-trade net profit and loss with the bootstrap confidence interval of the mean and the break-even line">
      ${band}${bars}${zeroLine}${meanLine}
    </svg>${legend}`;
  }

  // 5. walk-forward windows — per-fold return.
  function rpWalkforward(folds) {
    folds = (folds || []).filter((f) => f && f.mean_net_return != null);
    if (!folds.length) return `<div class="rp-empty">No walk-forward folds recorded.</div>`;
    const W = 720, H = 190, L = 40, R = 12, T = 16, B = 34;
    const mags = folds.map((f) => f.mean_net_return);
    let lo = Math.min(0, ...mags), hi = Math.max(0, ...mags);
    if (hi - lo < 1e-6) { hi += 0.01; lo -= 0.01; }
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B), zero = y(0);
    const slot = (W - L - R) / folds.length, bw = Math.min(54, slot * 0.6);
    const day = (t) => t ? new Date(t > 1e11 ? t : t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '';
    const cells = folds.map((f, i) => {
      const cx = L + slot * i + slot / 2, v = f.mean_net_return, top = Math.min(y(v), zero), h = Math.max(1, Math.abs(y(v) - zero)), col = v >= 0 ? 'var(--ink)' : 'var(--signal)';
      return `<rect x="${(cx - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${col}" rx="3"/>
        <text x="${cx.toFixed(1)}" y="${(v >= 0 ? top - 5 : top + h + 13).toFixed(1)}" text-anchor="middle" style="fill:var(--ink)">${rpRet(v)}</text>
        <text x="${cx.toFixed(1)}" y="${H - 18}" text-anchor="middle">${esc(day(f.from_ts || f.from) || ('W' + (i + 1)))}</text>
        <text x="${cx.toFixed(1)}" y="${H - 6}" text-anchor="middle" style="fill:var(--ink-3)">${f.n_trades != null ? f.n_trades + 't' : ''}</text>`;
    }).join('');
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Average net return per trade in each slice of the validation window">
      <line x1="${L}" x2="${W - R}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}" stroke="var(--rule-2)"/>${cells}
    </svg>`;
  }

  function rpConclusion(cls) {
    const m = {
      deployment_candidate: ['good', 'Deployment candidate. It cleared validation on data it had never seen, held up on the one-time locked holdout, and is different enough from your deployed strategies to add something new.'],
      forward_validated: ['good', 'Forward-validated. It passed validation and then held up on the locked holdout, which is evaluated exactly once — the strongest evidence this pipeline produces.'],
      statistically_supported: ['', 'Statistically supported. Its validation edge passed the significance, deflated-Sharpe and placebo checks, but it has not yet faced the one-time locked holdout.'],
      promising: ['', 'Promising. An in-research edge that has not yet faced the validation partition.'],
      inconclusive: ['quiet', 'Inconclusive. The evidence was too weak, or the sample too small, to show an edge that isn’t luck.'],
      rejected: ['sig', 'Rejected. It failed in-research, lacked a credible mechanism, or was indistinguishable from its placebo. It is kept on the record so the next search does not repeat it.'],
    };
    return m[cls] || ['quiet', 'Awaiting a recorded verdict.'];
  }

  // Build the §D research-ledger evidence as composable paper fragments, so the detail
  // page can file each under its canonical research-paper section (Mechanism, Methodology,
  // Results, Verdict) alongside the always-present backtest. Returns an all-empty object for
  // strategies with no ledger row (pre-pipeline) — additive by design, never a regression.
  function researchPaper(exp) {
    const parts = { mechanism: '', methodology: '', results: '', verdict: '' };
    if (!exp) return parts;
    const sub = (title, body) => `<div class="paper-sub"><h4 class="paper-h">${title}</h4>${body}</div>`;
    // Mechanism & hypothesis — who is on the other side, and what would disprove it.
    const mech = exp.mechanism;
    if (mech) {
      let body;
      if (typeof mech === 'object') {
        const known = ['who_pays', 'why_not_arbitraged', 'when', 'why_persists'].filter((k) => mech[k] != null);
        const extra = Object.keys(mech).filter((k) => !RP_MECH[k] && mech[k] != null);
        body = `<dl class="rp-grid">${known.concat(extra).map((k) => `<div><dt>${esc(RP_MECH[k] || rpHuman(k))}</dt><dd>${rpText(mech[k])}</dd></div>`).join('')}</dl>`;
      } else body = `<p class="rp-prose">${rpText(mech)}</p>`;
      parts.mechanism += sub('Who is on the other side, and why the edge persists', body);
    }
    if (exp.falsification_criteria || exp.negative_control) {
      let body = '';
      if (exp.falsification_criteria) body += `<p class="rp-prose">${rpText(exp.falsification_criteria)}</p>`;
      if (exp.negative_control) body += `<p class="rp-sub"><b>Negative control:</b> ${rpText(exp.negative_control)}</p>`;
      parts.mechanism += sub('What would disprove it', body);
    }
    if (exp.competing_explanations) parts.mechanism += sub('Competing explanations', `<p class="rp-prose">${rpText(exp.competing_explanations)}</p>`);
    // Methodology — the pre-registered, frozen test.
    const pre = [];
    if (exp.null_hypothesis) pre.push(['Null hypothesis', exp.null_hypothesis]);
    if (exp.alt_hypothesis) pre.push(['Alternative', exp.alt_hypothesis]);
    if (exp.primary_metric) pre.push(['Primary metric', rpPlain(exp.primary_metric)]);
    if (exp.planned_test) pre.push(['Planned test', rpPlain(exp.planned_test)]);
    if (exp.min_sample != null) pre.push(['Minimum sample', exp.min_sample + ' trades']);
    if (exp.planned_n_tests != null || exp.correction_method) pre.push(['Multiple-testing control', `${exp.planned_n_tests != null ? exp.planned_n_tests + ' planned tests ·\u00a0' : ''}${exp.correction_method ? (exp.correction_method === 'BH' ? 'Benjamini–Hochberg (a false-discovery control across the ideas tested together)' : rpPlain(exp.correction_method) + (/LORD/.test(exp.correction_method) ? LORD_WORDS : '')) : '—'}`]);
    if (exp.cost_assumptions && typeof exp.cost_assumptions === 'object') pre.push(['Cost assumptions', Object.entries(exp.cost_assumptions).map(([k, v]) => `${rpHuman(k)}: ${v}`).join(' ·\u00a0')]);
    if (pre.length) {
      const reg = exp.registered_at ? `<p class="rp-reg">Pre-registered <b>${esc(rpStamp(exp.registered_at))}</b> — before any validation number was computed. The frozen rule and its test could not be changed after the results came in.</p>` : '';
      parts.methodology += sub('The pre-registered test', `<dl class="rp-grid">${pre.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${rpText(v)}</dd></div>`).join('')}</dl>${reg}`);
    }
    // A figure is red exactly when the gate that judges it missed: the server judges each one with
    // the gatekeeper's own thresholds (services.gate_explain, the same checks as "What it missed"),
    // so no cutoff is restated here. A figure no gate judges, or one the server didn't judge, stays ink.
    const tints = exp.gate_tints || {};
    const tint = (phase, k) => ((tints[phase] || {})[k] === 'fail' ? 'sig' : '');
    // Results — the rigorous validation-window evidence.
    const v = exp.validation;
    if (v) {
      const stat = (k, val, cls, sb) => `<div class="rp-stat"><div class="k">${esc(k)}</div><div class="val${cls ? ' ' + cls : ''}">${val}</div>${sb ? `<div class="sub">${esc(sb)}</div>` : ''}</div>`;
      const ciTxt = (v.ci_lo != null && v.ci_hi != null) ? `90% CI ${rpRet(v.ci_lo)} to ${rpRet(v.ci_hi)}` : '';
      const stats = [
        stat('Net return per trade', rpRet(v.mean_net_return), tint('validation', 'mean_net_return'), 'average, as % of its stake' + (ciTxt ? ' ·\u00a0' + ciTxt : '')),
        stat('Bootstrap p-value', rpProb(v.p_value), tint('validation', 'p_value'), 'chance a rule with no edge does this well; lower is better'),
        stat('PSR', rpProb(v.psr), '', 'probability its true risk-adjusted return (Sharpe) is above 0'),
        stat('DSR', rpProb(v.dsr), tint('validation', 'dsr'), 'the same, discounted for the many ideas tried'),
        stat('Trials audited', rpInt(exp.n_trials_audited), '', 'ideas tested on this data; more ideas, more lucky passes'),
        stat('p-value needed', rpProb(v.fdr_alpha_i, 4), '', 'the bar its p-value had to clear' + (v.fdr_reject == null ? '' : v.fdr_reject ? '; it cleared it' : '; it missed it')),
        stat('Placebo p-value', rpProb(v.placebo_p), tint('validation', 'placebo_p'), 'chance shuffled outcomes do as well; lower is better'),
        stat('Trades', rpInt(v.n_trades), tint('validation', 'n_trades'), 'on the validation window'),
      ].join('');
      const figs = `<div class="rp-figs">
        <div class="rp-fig wide"><h5>Equity by phase</h5>${rpPhaseEquity([
          { key: 'validation', label: 'Validation', color: 'var(--ink)', curve: rpCum(v.equity_curve) },
          { key: 'holdout', label: 'Holdout', color: 'var(--signal)', curve: exp.holdout && rpCum(exp.holdout.equity_curve) },
        ])}<div class="cap">Running total of each trade's net return, counted in stakes: +2× means it made twice what one trade puts in, after fees. Each phase is its own run on data the agent never saw; the dashed divider marks the one-way handoff from validation to the locked holdout.</div></div>
        <div class="rp-fig"><h5>Validation vs holdout</h5>${rpShrinkage(v.mean_net_return, exp.holdout ? exp.holdout.mean_net_return : null)}</div>
        <div class="rp-fig"><h5>Drawdown (underwater)</h5>${rpUnderwater(rpCum(v.equity_curve), null, rpStakes)}<div class="cap">Validation, counted in stakes: the deepest drop from a running high.</div></div>
        <div class="rp-fig wide"><h5>Per-trade return distribution</h5>${rpReturnDist((v.equity_curve || []).map((p) => +p[1]), v.ci_lo, v.ci_hi, v.mean_net_return)}<div class="cap">Bars: the net return of each validation trade, as % of its stake. Shaded band: the 90% bootstrap confidence interval of the mean. Dashed line: the mean. A band entirely right of break-even means the edge clears fees.</div></div>
        <div class="rp-fig wide"><h5>Walk-forward windows</h5>${rpWalkforward(exp.folds)}<div class="cap">The validation window cut into consecutive slices, with each slice's average net return per trade (as % of its stake) and its trade count. The same sign in most slices is robustness; one slice carrying the whole edge is a warning.</div></div>
      </div>`;
      parts.results += sub('Validation-window evidence', `<p class="rp-sub" style="margin-top:0">The agent searched and tuned on earlier data (in-sample). These numbers come from the validation window after it: data the agent never saw while searching.</p><div class="rp-stats">${stats}</div>${figs}`);
    }
    // Verdict — the ladder, the one-time locked holdout, and the gatekeeper's conclusion.
    parts.verdict += `<div class="paper-sub"><h4 class="paper-h">Where it reached on the ladder</h4>${rpLadder(exp.classification, exp.validation && exp.validation.classification, exp.holdout ? 'on the locked holdout' : '')}</div>`;
    const h = exp.holdout;
    const holdBody = h ? `<div class="rp-stats">
      <div class="rp-stat"><div class="k">Net return per trade</div><div class="val${tint('holdout', 'mean_net_return') ? ' sig' : ''}">${rpRet(h.mean_net_return)}</div><div class="sub">average, as % of its stake${h.ci_lo != null && h.ci_hi != null ? ' ·\u00a090% CI ' + rpRet(h.ci_lo) + ' to ' + rpRet(h.ci_hi) : ''}</div></div>
      <div class="rp-stat"><div class="k">Bootstrap p-value</div><div class="val${tint('holdout', 'p_value') ? ' sig' : ''}">${rpProb(h.p_value)}</div></div>
      <div class="rp-stat"><div class="k">Trades</div><div class="val${tint('holdout', 'n_trades') ? ' sig' : ''}">${rpInt(h.n_trades)}</div></div>
      <div class="rp-stat"><div class="k">Holdout</div><div class="val">${h.consumed ? 'Consumed' : 'Open'}</div><div class="sub">${h.consumed ? 'used once, as designed: it can’t be re-run on this data' : 'not used yet'}</div></div>
    </div>` : `<div class="rp-empty">Not yet evaluated on the locked holdout. The holdout is spent only once, on strategies that already passed validation — so an empty holdout here is expected until then.</div>`;
    parts.verdict += sub('The one-time locked holdout', holdBody);
    const [vtone, words] = rpConclusion(exp.classification);
    const chip = { good: 'on', sig: 'armed', quiet: 'quiet' }[vtone] || '';
    parts.verdict += `<div class="rp-verdict ${vtone}"><span class="mk ${chip}">${esc(rpHuman(exp.classification || 'unknown'))}</span><p>${words}</p></div>`;
    return parts;
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
  const money = (v) => `<span class="${tone(v)}">${usd(v, true)}</span>`;
  const STRAT_HEAD = (pick) => `<thead><tr>${pick ? '<th class="pickcol"><input type="checkbox" id="pick-all" aria-label="Select all deployable"></th>' : ''}<th>Strategy</th><th>Market</th><th class="num">Unseen P&amp;L${glo('unseen')}</th><th class="num">Trades</th><th class="num">Win</th><th>Tried</th><th>Status</th></tr></thead>`;
  const strategyTable = (rows, pick) => `<div class="sheet"><table class="stack t-strat">${STRAT_HEAD(pick)}<tbody>${rows}</tbody></table></div>`;
  // Bulk deploy offers only passed strategies that aren't already running: ticking one that is
  // would start a second deployment of the same rules and double its positions.
  const bulkDeployable = (s) => s.status === 'passed' && !researchOnly(s) && !s.deployed;
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
  const runTag = (r) => r.example ? ' ' + EXAMPLE_TAG : +r.by_autopilot ? ' ' + AP_RUN_TAG : '';
  // The run page's kind of session: its direction, and who started it when the autopilot did.
  const runKind = (r) => +r.by_autopilot && !r.example ? (r.direction ? dirLabel(r.direction) + ' \u00b7\u00a0' : '') + 'Started by autopilot' : dirLabel(r.direction);
  const realFig = (r) => r ? `<div class="sub-fig real-fig">${r.trades ? `${money(r.pnl)} ${r.mode === 'demo' ? 'on demo ' : r.mode === 'paper' ? 'on paper ' : ''}since deploying \u00b7\u00a0${realTrades(r.trades)}` : r.mode === 'demo' ? 'No closed demo trades yet' : r.mode === 'paper' ? 'No closed paper trades yet' : 'No closed trades yet'}</div>${r.demo ? `<div class="sub-fig real-fig">Demo: ${r.demo.trades ? `${money(r.demo.pnl)} \u00b7\u00a0${realTrades(r.demo.trades)}` : 'no closed trades yet'}</div>` : ''}` : '';
  function strategySlip(s, reg, opts = {}) {
    const oos = s.out_of_sample, ins = s.in_sample || {};
    const m = oos || ins;
    // A void or rejected idea's backtest P&L read as a green "+$2.10" beside its Void stamp: it is muted
    // and says the idea did not pass, so a gain on the data it was built on never reads as a result.
    const noPass = s.status === 'failed' || s.status === 'rejected';
    const pnlSub = [oos ? '' : 'tested only', noPass ? 'did not pass' : ''].filter(Boolean).join(' \u00b7\u00a0');
    const tried = s.hypotheses_tried ? `1 of ${s.hypotheses_tried}` : s.parent_id ? 'Adjustment' : '\u2014';
    const name = opts.nolink ? esc(s.title) : `<a href="/strategies/${s.id}">${esc(s.title)}</a>`;
    const pickCell = opts.pick ? (bulkDeployable(s)
      ? `<td class="pickcol" data-lab="Deploy"><input type="checkbox" class="pick" data-id="${s.id}" aria-label="Select for deployment"></td>`
      : '<td class="pickcol" data-lab=""></td>') : '';
    return `<tr class="${opts.land ? 'washed' : ''}">${pickCell}
      <td class="name" data-lab="">${name}${s.shared_from ? ` <span class="shared-flag">${ICON.share}${esc(s.shared_from)}</span>` : ''}${s.example ? ' ' + EXAMPLE_TAG : ''}<div class="sub-fig cellwrap">${mdInline(esc(s.thesis))}</div></td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(s.market))} \u00b7\u00a0${esc(dirLabel(s.direction))}</span></td>
      <td class="num" data-lab="${oos ? 'Backtest P&amp;L (unseen)' : 'Backtest P&amp;L (tested)'}">${m.pnl == null ? '\u2014' : noPass ? `<span class="pnl-nopass">${usd(m.pnl, true)}</span>` : money(m.pnl)}${pnlSub ? `<div class="sub-fig">${pnlSub}</div>` : ''}</td>
      <td class="num" data-lab="Trades">${m.trades == null ? '\u2014' : m.trades}</td>
      <td class="num" data-lab="Win">${pct(m.win_rate, false)}</td>
      <td data-lab="Tried"${tried === '\u2014' ? ' class="nil"' : ''}>${esc(tried)}</td>
      <td class="act st" data-lab="Status">${mark(s.status)}${researchBadge(s)}${s.deployed && !researchOnly(s) ? ` <span class="mk ${s.deploy_live ? 'live' : 'dep'}">${s.deploy_live ? 'Live' : 'Deployed'}</span>${s.real && s.real.paused ? ' ' + mark('paused') : ''}${realFig(s.real)}` : ''}</td>
    </tr>`;
  }
  // The Backtest estimate column's hover text (its header's glossary marker says the same at more length).
  const PACE_TIP = 'What these same closed trades would have made at the backtest’s average per trade on unseen data';
  const DEP_HEAD = (controls) => `<thead><tr><th>Strategy</th><th>Market</th><th>Status</th><th class="num">Realized</th><th class="num">Unrealized</th><th class="num">Trades</th><th class="num" title="${PACE_TIP}">${gl('Backtest estimate', 'pace')}</th><th>Since</th>${controls ? '<th class="act"><span class="vh">Actions</span></th>' : ''}</tr></thead>`;
  // Paused deployments need the user ("Resume or remove it on Deploy" sends them here), so they lead.
  const pausedFirst = (ds) => [...ds].sort((a, b) => (b.status === 'paused') - (a.status === 'paused'));
  const deploymentTable = (rows, controls) => `<div class="sheet"><table class="stack t-dep">${DEP_HEAD(controls)}<tbody>${rows}</tbody></table></div>`;
  // One plain line on how a book is doing against its backtest, written by the server
  // (services/backtest_check.py): that book's realized per-trade P&L and win rate against the
  // backtest's, "too early to tell" under 10 trades. One book per line; books are never added up.
  // Each signed amount stays on one line (a phone would otherwise break between the minus and the $).
  const btCheckLine = (c, tag = 'div') => c && c.line ? `<${tag} class="sub-fig bt-check bt-${esc(c.verdict)}">${esc(c.line).replace(/[+\u2212]\$[\d,]+\.\d\d/g, (m) => `<span class="amt">${m}</span>`)}</${tag}>` : '';
  // A paper row's strategy record toward the live check (the server's `road`: all its paper
  // deployments, counted as the strategy page's Road to live counts them) and when the trades, events
  // and hours could be in at its pace; once they are, which checks still refuse it (`failing`).
  const ROAD_FAILING = { candidate: 'gatekeeper', legacy_trades: 'trade count', legacy_pnl: 'P&amp;L', net_pnl: 'P&amp;L', edge: 'edge', recent: 'recent form', demo: 'demo record' };
  const roadLine = (d) => {
    const r = d.road;
    if (!r) return '';
    const parts = [[r.trades, r.trades_needed, 'trades'], [r.events, r.events_needed, 'events'], [Math.floor(r.span_hours), r.span_needed_hours, 'hours']]
      .filter(([have, need]) => have < need).map(([have, need, unit]) => `${num(have)}/${num(need)}\u00a0${unit}`);
    let text;
    if (parts.length) text = parts.join(' ·\u00a0') + (!r.running ? ' ·\u00a0paused, so not growing' : r.eta_days != null ? ` ·\u00a0enough in ${roadDays(r.eta_days)} at its pace` : '');
    else if (!r.failing) text = 'trades, events and hours are in';
    else if (!r.failing.length) text = 'its record clears every check. Live money only if you deploy it there';
    else {
      const names = [...new Set(r.failing.map((k) => ROAD_FAILING[k] || esc(k.replace(/_/g, ' '))))];
      text = `trades, events and hours are in; ${names.length} check${names.length === 1 ? '' : 's'} left: ${names.join(', ')}`;
    }
    return `<div class="sub-fig road-line">Toward live: ${text}</div>`;
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
  const resumeButton = (d) => `<button class="btn sm" data-dep="${d.id}" data-act="resume"${d.resume_block ? ` disabled title="${esc(d.resume_block)}"` : ''}>Resume<span class="vh"> ${esc(d.title)}${d.resume_block ? ': ' + esc(d.resume_block) : ''}</span></button>`;
  const demoRowLine = (d) => d.mode !== 'demo' ? '' : `<div class="sub-fig demo-row">${d.demo_copy ? 'Demo copy of its paper run: the same rules on Kalshi’s sandbox, with play money' : 'On Kalshi’s sandbox, with play money'}. It proves orders place, fill and book before live money; the demo book is thin, so fills differ from paper’s.</div>`;
  function deploymentSlip(d, regs, controls) {
    const exp = d.backtest && d.backtest.out_of_sample;
    // Realized beside what the backtest's unseen-data average per trade says the same trades should
    // have made: the comparable number, not the backtest's own total over a different trade count.
    // Before the first close it names the book that has none ("no paper trades closed yet"): a bare
    // "no closed trades" under "Backtest estimate" read as if the backtest itself had no trades.
    const pace = exp && +exp.trades > 0 ? (+exp.pnl || 0) / +exp.trades : null;
    const live = d.mode === 'live';
    // A paused row names its book too: "Paused" alone didn't say whether real money had stopped.
    const modeTag = live ? '<span class="mk live">LIVE</span>' : d.mode === 'demo' ? '<span class="mk dep">DEMO</span>' : '<span class="mk">PAPER</span>';
    const actions = controls ? `<td class="act" data-lab="">
        ${d.status === 'running' ? `<button class="btn sm" data-dep="${d.id}" data-act="pause" data-open="${+d.open_positions || 0}">Pause<span class="vh"> ${esc(d.title)}</span></button>` : ''}
        ${d.status === 'paused' ? resumeButton(d) : ''}
        <button class="btn sm danger" data-dep="${d.id}" data-act="stop" data-open="${+d.open_positions || 0}">Remove<span class="vh"> ${esc(d.title)}</span></button></td>` : '';
    return `<tr class="${live ? 'live-row' : ''}">
      <td class="name" data-lab=""><a href="/strategies/${d.strategy_id}">${esc(d.title)}</a>
        <div class="sub-fig">${depSizing(d)}${d.status !== 'running' && (d.status_why || d.status_reason) ? ' \u00b7\u00a0' + esc(d.status_why || d.status_reason) : ''}</div>${demoRowLine(d)}${btCheckLine(d.backtest_check)}${roadLine(d)}</td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(d.market))}</span></td>
      <td data-lab="Status">${d.status === 'running' ? modeTag : `${mark(d.status, live)} ${modeTag}`}</td>
      <td class="num" data-lab="Realized">${money(d.realized_pnl)}${spark(d.curve, regs && regs[d.mode], d.closed_trades)}</td>
      <td class="num" data-lab="Unrealized">${d.unrealized_pnl == null ? '<span class="sub-fig">—</span>' : money(d.unrealized_pnl)}${d.unrealized_pnl != null && d.open_positions ? '<div class="sub-fig">est.</div>' : ''}</td>
      <td class="num" data-lab="Trades">${d.closed_trades}${d.open_positions ? `<div class="sub-fig">+${d.open_positions} open</div>` : ''}</td>
      <td class="num" data-lab="Backtest estimate" title="${PACE_TIP}">${pace == null ? '\u2014' : d.closed_trades ? `${usd(pace * d.closed_trades, true)}<div class="sub-fig">same ${d.closed_trades} trade${d.closed_trades === 1 ? '' : 's'}</div>` : `<span class="sub-fig">${live ? 'no live trades closed yet' : d.mode === 'demo' ? 'no demo trades closed yet' : 'no paper trades closed yet'}</span>`}</td>
      <td data-lab="Since">${when(d.created_at)}</td>
      ${actions}
    </tr>`;
  }
  // One action per deployment at a time: a second press, or a poll's repainted copy of the button,
  // waits for the first to come back instead of sending again. The board re-reading after an action
  // that landed is not the action: when only the re-read fails, the action is confirmed with a word to
  // reload (it read as an error and invited a second press), and the button, still offering what was
  // just done, stays locked until the board repaints.
  const depSending = new Set();
  function bindDeploymentActions(scope, after) {
    scope.querySelectorAll('[data-dep]').forEach((btn) => {
      btn.onclick = () => {
        const id = btn.dataset.dep, act = btn.dataset.act;
        if (depSending.has(id) || btn.disabled) return;
        const run = async () => {
          if (depSending.has(id)) return;
          depSending.add(id);
          let fresh = null;
          try {
            await busy(btn, async () => {
              try { await api(`/api/deployments/${id}/${act}`, {}); } catch (e) { alert0(e.message); return; }
              fresh = await refreshed(after());
            });
          } finally { depSending.delete(id); }
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
  }
  const DEP_DONE = { pause: 'Deployment paused.', resume: 'Deployment resumed.', stop: 'Deployment stopped.' };
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
    const host = root.querySelector('#flash') || root.querySelector('main');
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
  const LEGAL_CONTACT = 'tanjihui@tau-trading.com';
  const LEGAL_UPDATED = 'October 20, 2026';
  const sec = (h, ...ps) => `<h2>${h}</h2>${ps.map((p) => `<p>${p}</p>`).join('')}`;
  function legalShell(title, bodyHtml) {
    clearTimers();
    document.body.classList.add('landing-body');
    // Links out of the legal pages load the app afresh: boot.js serves these pages in Tau for
    // everyone, so a Meridian user has to reload to get their own theme back.
    const away = S.me ? '<a class="legal-away" href="/" data-native>Dashboard</a>' : '<a class="legal-away" href="/signin" data-native>Sign in</a>';
    root.innerHTML = `<div class="legal-wrap">
      <header class="legal-top"><a class="lbrand" href="/" data-native>${ICON.mark}<span>Tau</span></a>
        <nav class="legal-nav"><a href="/terms">Terms</a><a href="/privacy">Privacy</a>${away}</nav></header>
      <main class="legal" id="main">
        <h1>${title}</h1><p class="legal-updated">Last updated ${LEGAL_UPDATED}</p>
        ${bodyHtml}
        <footer class="legal-foot"><a href="/terms">Terms of Service</a> ·\u00a0<a href="/privacy">Privacy Policy</a> ·\u00a0<span>© 2026 Tau</span></footer>
      </main></div>`;
    // Public pages skip the boot /api/me, so a signed-in reader was offered "Sign in". Ask quietly
    // (a 401 here never redirects) and point the link at the dashboard when there is a session.
    if (!S.me) api('/api/me').then((me) => {
      const a = root.querySelector('.legal-away');
      if (me && me.user && a) { a.setAttribute('href', '/'); a.textContent = 'Dashboard'; }
    }).catch(() => {});
  }
  async function viewTerms() {
    legalShell('Terms of Service',
      sec('1. Agreement', `By accessing or using Tau (the “Service”), you agree to these Terms of Service. If you do not agree, do not use the Service.`) +
      sec('2. What Tau is', `Tau is software that helps you research, backtest, and automate trading strategies for prediction markets offered by Kalshi. Tau can place trades in a Kalshi account you connect, using credentials you provide. Tau is a software tool — it is not a broker-dealer, exchange, investment adviser, or fiduciary, and it does not hold your funds.`) +
      sec('3. Not financial advice', `Tau’s research, backtests, scores, and generated strategies are informational only. They are not investment, financial, legal, or tax advice, and are not a recommendation to enter into any trade. Backtested and simulated results are hypothetical and do not guarantee future performance. All trading decisions are your own and your sole responsibility.`) +
      sec('4. Eligibility', `You must be at least 18 years old and able to form a binding contract, and you may use the Service only where trading on prediction markets is lawful for you. You are responsible for complying with Kalshi’s terms and all laws that apply to you.`) +
      sec('5. Your account', `You sign in with Google. You are responsible for keeping your account secure and for all activity under it. Live trading uses your own Kalshi API credentials, which you choose to provide; Tau places trades only for strategies you deploy and never takes custody of your funds.`) +
      sec('6. Trading risk', `Trading on prediction markets involves substantial risk, including the total loss of the funds you commit. Only trade with money you can afford to lose. Paper and demo modes are simulated and involve no real money.`) +
      sec('7. Fees and billing', `Some features may require paid credits. Where paid features are enabled, you authorize charges through our payment processor (Stripe) for the credits or usage described in the app, and credits are consumed as the agent performs work for you. Pricing may change, and any changes will be reflected in the app.`) +
      sec('8. Acceptable use', `You agree not to use the Service unlawfully; not to abuse, reverse-engineer, disrupt, or overload it; and not to use it to violate the rules of Kalshi or any exchange, venue, or third party.`) +
      sec('9. Intellectual property', `Tau and its software, content, and branding are owned by its operator; you receive a limited, non-exclusive, non-transferable license to use the Service. Content and inputs you submit remain yours, and you grant us a license to process them solely to operate and improve the Service.`) +
      sec('10. Disclaimers', `The Service is provided “as is” and “as available,” without warranties of any kind, express or implied, including merchantability, fitness for a particular purpose, availability, accuracy, or profitability.`) +
      sec('11. Limitation of liability', `To the maximum extent permitted by law, the operator of Tau is not liable for any trading losses or for any indirect, incidental, special, consequential, or punitive damages arising from your use of the Service. Our total liability for any claim is limited to the amount you paid us for the Service in the three months before the claim.`) +
      sec('12. Termination', `We may suspend or terminate access for any violation of these Terms or to protect the Service or its users. You may stop using the Service at any time.`) +
      sec('13. Changes', `We may update these Terms from time to time. Material changes will be posted here with a new “last updated” date, and your continued use of the Service means you accept the updated Terms.`) +
      sec('14. Contact', `Questions about these Terms: <a href="mailto:${LEGAL_CONTACT}">${LEGAL_CONTACT}</a>.`));
  }
  async function viewPrivacy() {
    legalShell('Privacy Policy',
      sec('Overview', `This policy explains what information Tau collects, how we use it, and the choices you have. By using Tau you agree to this policy.`) +
      sec('Information we collect', `<strong>Account information</strong> — your name and email address from Google sign-in. <strong>Usage data</strong> — the research sessions, strategies, settings, and interactions you create in the app. <strong>Payment information</strong> — processed by our payment provider (Stripe); we do not store your full card number. <strong>Trading credentials</strong> — if you connect live trading, your Kalshi API key, stored encrypted. <strong>Technical data</strong> — standard logs such as IP address and browser type.`) +
      sec('How we use it', `To provide and operate the Service; to run your research and backtests; to process billing; to secure, maintain, and improve the Service; and to communicate with you about your account.`) +
      sec('AI processing', `Your research inputs and prompts are processed by our AI provider (Anthropic, via Amazon Bedrock) to generate research and strategies. Please do not include sensitive personal information in research prompts.`) +
      sec('How we share it', `We do not sell your personal information. We share it only with the service providers that run Tau — Google (sign-in), Stripe (payments), Amazon Web Services (hosting), and Anthropic / Amazon Bedrock (AI) — and when required by law or to protect the Service and its users.`) +
      sec('Cookies and local storage', `We use a session cookie to keep you signed in and your browser’s local storage for preferences such as your theme. We do not use third-party advertising cookies.`) +
      sec('Data retention', `We keep your information while your account is active and for as long as needed to operate the Service and meet legal and security obligations.`) +
      sec('Security', `We protect sensitive credentials with encryption and apply reasonable safeguards. No method of storage or transmission is completely secure, so we cannot guarantee absolute security.`) +
      sec('Your choices', `You can access, correct, or delete your information by contacting us. You can disconnect live trading and sign out at any time.`) +
      sec('Children', `Tau is not directed to, and may not be used by, anyone under 18.`) +
      sec('Changes', `We may update this policy; we will post changes here with a new “last updated” date.`) +
      sec('Contact', `Questions about privacy or your data: <a href="mailto:${LEGAL_CONTACT}">${LEGAL_CONTACT}</a>.`));
  }

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
    const trWrap = root.querySelector('main') && root.querySelector('main').parentNode;
    const trFirst = trWrap && trWrap.appendChild ? api('/api/track-record', undefined, { keep: true }) : null;
    if (trFirst) trFirst.catch(() => {});  // a failure is drawn by dashTrackRecord, with its retry
    S.trReread = null;  // set by dashTrackRecord once this view's record is mounted
    let booksSeen = null;  // each book's closed and open trade counts at the last poll
    const visitAt = visitStart();
    let kept = null;  // the last full answer, whose version the poll sends back (pollAnswer)
    const load = async (cfg) => {
      const q = [visitAt ? 'since=' + visitAt : '', kept && kept.v ? 'v=' + encodeURIComponent(kept.v) : ''].filter(Boolean).join('&');
      const got = await api('/api/dashboard' + (q ? '?' + q : ''), undefined, cfg);
      const d = pollAnswer(kept, got);
      if (!got.same) kept = got;
      setVisit(visitAt, Math.floor(Date.now() / 1000));  // still here: this visit's last-seen moves on
      S.dashNoSessions = !!(d.since && d.since.own_sessions === false);
      const depsWas = S.dashDeps;
      S.dashDeps = d.deployments.length;  // the empty track record's button reads it (trackRecordPanel)
      // The record below polls once a minute: a trade this poll saw open or close re-reads it now (the
      // server rebuilds a cached record the board has moved past), and a first deployment repaints its
      // empty copy, which reads S.dashDeps.
      const books = ['paper', 'demo', 'live'].map((m) => (d[m] ? `${d[m].closed_trades}/${d[m].open_positions}` : '')).join(' ');
      if (booksSeen != null && books !== booksSeen && S.trReread) S.trReread();
      else if (depsWas !== S.dashDeps && trAp && trAp.host.isConnected) trAp.repaint();
      booksSeen = books;
      const p = d.paper;
      // Realized P&L (all-time + today) and open count for one money bucket; a tasteful
      // zero line when the bucket has no activity so an empty card never looks broken.
      // The figure above it is Kalshi's cash for the whole account; this line is Tau's own trades.
      const mSub = (b, zero) => (b.open_positions || b.running || b.realized_pnl) ? `Tau trades: ${b.open_positions} open${b.open_positions ? ' (not in cash)' : ''} ·\u00a0${usd(b.realized_pnl, true)} realized all time ·\u00a0${usd(b.today_pnl, true)} realized today (UTC)` : zero;
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
      const running = d.deployments.filter((x) => x.status === 'running').length;
      const paused = d.deployments.filter((x) => x.status === 'paused').length;
      const needs = stale || paused > 0;
      const said = [
        hasLive ? `Live money on: ${usd(d.live.realized_pnl, true)} realized all time` : hasDemo ? 'No real money: paper and demo' : 'Paper money only',
        running ? `${running} strateg${running > 1 ? 'ies' : 'y'} running` : 'Nothing deployed',
        paused ? `<a class="needs-link" href="#dash-deps"><em>${paused} paused, needs you</em></a>` : '',  // paused rows list first
        agentsBusy ? `${agentsBusy} agent${agentsBusy > 1 ? 's' : ''} researching` : '',
        stale ? `<em>${d.freshness.btc == null ? 'No backtest history yet' : 'Backtest history stale ' + age(d.freshness.btc)}</em>` : '',
      ].filter(Boolean).join('<span class="sep">/</span>');
      // While autopilot is off its card's "Turn on autopilot" is the one primary button on the page.
      const board = `
        <h1 class="vh">Dashboard</h1>
        <div class="statusline ${needs ? 'needs' : ''}"><p class="said">${said}</p><a class="btn${S.me.user.autopilot ? ' primary' : ''}" href="/research">New research</a></div>
        ${sinceStrip(d, '#dash-deps')}
        <section id="dash-ap" class="apcard" aria-label="Autopilot"></section>
        <dl class="figures measure">
          ${fig('<span class="mk live">Real</span> Kalshi cash', d.live.connected ? (d.live.balance == null ? 'Unavailable' : usd(d.live.balance)) : 'Not connected', { small: (d.live.connected ? (d.live.balance == null ? ['Couldn\u2019t read your Kalshi balance just now', mSub(d.live, '')].filter(Boolean).join(' \u00b7\u00a0') : (d.live.balance_at ? `Read from Kalshi ${when(d.live.balance_at)} \u00b7\u00a0` : '') + mSub(d.live, 'Your Kalshi cash \u2014 real money untouched')) : 'Connect your Kalshi account on <a href="/funds">Funds</a> to trade real money') + tradesCsv('live', d.live) })}
          ${fig('<span class="mk dep">Demo</span> Sandbox', usd(d.demo.equity), { v: d.demo.realized_pnl, small: `${d.demo.health ? demoHealthLine(d.demo.health) + '<br>' : ''}${(d.demo.open_positions || d.demo.running || d.demo.realized_pnl) ? `${usd(d.demo.capital)} capital \u00b7\u00a0${d.demo.open_positions} open \u00b7\u00a0${usd(d.demo.realized_pnl, true)} P&amp;L ${demoSpan(d.demo)}` : `${usd(d.demo.capital)} capital \u00b7\u00a0no demo strategies yet`} \u00b7\u00a0${DEMO_WHAT}${tradesCsv('demo', d.demo)}` })}
          ${fig('<span class="mk">Paper</span> Simulation', usd(p.equity), { v: p.realized_pnl, small: paperUsed ? `${usd(p.cash)} cash \u00b7\u00a0${usd(p.open_at_cost)} at cost \u00b7\u00a0<span class="amt">${usd(p.realized_pnl, true)}</span> realized all time${tradesCsv('paper', p)}` : `${usd(p.cash)} of practice money \u00b7\u00a0no paper strategies yet` })}
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
      // banked), or its cost until the engine's first price.
      const stubs = (rows, closed) => rows.length
        ? rows.map((r) => `<div class="stub"><b>${esc(r.side.toUpperCase())} ${esc(r.qty)} × ${cents(+r.entry_price)}</b>
            <span>${closed ? money(+r.pnl) : (r.unrealized != null ? (r.value != null ? `worth ${usd(r.value)} (${money(r.unrealized)})` : money(r.unrealized)) : `${usd(r.qty * r.entry_price)} at cost`)}</span>
            <small>${esc(r.title)} ·\u00a0<span class="tick">${esc(r.ticker)}</span> ·\u00a0${r.mode === 'live' ? 'LIVE' : r.mode === 'demo' ? 'DEMO' : 'PAPER'} ·\u00a0${when(closed ? r.closed_at : r.opened_at)}</small>${r.why ? `<small class="stub-why">${esc(r.why)}</small>` : ''}</div>`).join('')
        : `<p class="hint">${closed ? 'No settled trades yet.' : 'No open positions.'}</p>`;
      const main = `<div class="dash-wrap"><div class="dash">
          <div>
            <section class="sect"><div class="sect-head"><h2>Deployed</h2></div><div id="dash-deps">${deps}</div></section>
          </div>
          <aside>
            <section class="panel" id="dash-open"><h3>Open positions</h3>${stubs(d.open_positions.slice(0, DASH_ROWS), false)}${more(d.open_positions.length, 'open positions')}</section>
            <section class="panel"><h3>Settled lately</h3>${stubs(d.recent_closed.slice(0, DASH_ROWS), true)}${d.recent_closed.length ? '<a class="stub-all" href="#track-record">Every closed trade, with net P&amp;L, is in the track record \u2193</a>' : ''}</section>
          </aside>
        </div></div>`;
      paint(root.querySelector('#boardbody'), board);  // the 15s poll repaints only what changed
      paint(root.querySelector('main'), main);
      S.dashPaper = p;
      paintDashAp();
      const dd = root.querySelector('#dash-deps');
      if (dd) bindDeploymentActions(dd, load);  // pause/resume/stop from the dashboard, same as Deploy
    };
    await load();
    poll(load, 15000, 'dash-stale');
    dashTrackRecord(trFirst);
  }

  // ---------- research ----------
  // The RSI loop made legible on the index: the engine rewrites its own search policy and keeps
  // the new one only if it beats the old on the user's own history. Same card language as the run
  // page. Hidden on a brand-new account (no history to evolve from yet).
  function renderRsiMomentum(host, pol, tried) {
    if (!host) return;
    if (!pol || (!pol.evolved && !tried)) { paint(host, ''); return; }
    const delta = (pol.base_score != null && pol.score != null)
      ? `<span class="rsi-score">${pol.base_score} <span class="rsi-arrow">→</span> ${pol.score}</span>` : '';
    const tag = pol.evolved ? '<span class="rsi-tag">Evolved</span>' : '<span class="rsi-tag quiet">Self-tuning</span>';
    const body = pol.evolved
      ? `<p>The engine <b>rewrote its own search policy</b> from your history — and it beats the default.</p>
         ${pol.summary ? `<p class="rsi-what"><b>What it changed:</b> ${esc(pol.summary)}</p>` : ''}
         <p class="rsi-last">Generalization score ${delta}${pol.evolved_at ? ' ·\u00a0adopted ' + when(pol.evolved_at) : ''} <span class="rsi-note">(higher = catches more real out-of-sample winners, scored over shuffled orderings so it can't overfit)</span></p>`
      : `<p>After each cycle the engine <b>tries new ways of choosing which ideas to test</b> and keeps one only if it would have found more real winners in your own history — scored over shuffled orderings, so it can't overfit. It gets better the more you run it.</p>`;
    // Demoted to a compact, collapsible line so the research page leads with the form, not panels.
    paint(host, `<details class="rsidisc">
      <summary class="rsidisc-cap"><b class="rsi-badge">RSI</b><span class="rsidisc-t">Self-improving research engine</span>${tag}${pol.evolved && delta ? `<span class="rsidisc-delta">${delta}</span>` : ''}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
      <div class="rsidisc-body">${body}</div>
    </details>`);
  }
  // The research loop's own report card (GET /api/research/scoreboard, app/research/rsi.py): is research
  // getting better, what it has learned per market family (playbooks under A/B test), where the
  // free scan points it next, and which ideas the pipeline (not the market) killed. Fetched at
  // most once a minute; the 5s page poll re-renders from the cached board.
  const LOOP_FAMILY = { 'weather-high': 'Daily high temps', 'weather-low': 'Daily low temps', crypto: 'Crypto' };
  const loopFamily = (f) => LOOP_FAMILY[f] || (f ? f.charAt(0).toUpperCase() + f.slice(1).replace(/-/g, ' ') : '');
  const LOOP_TAG = { feature_unavailable: 'feature missing', no_data: 'no data', zero_trades: 'never traded', fee_floor: 'under the fee', loses: 'loses money', spec_invalid: 'spec rejected', missing_context: 'needs data we lack', thin_sample: 'too few examples', no_signal: 'no signal', wrong_fit: 'wrong for this market', other: 'other' };
  const loopRate = (r) => (r == null ? '—' : Math.round(r * 100) + '%');
  const rsiLoop = { board: null, at: 0, inflight: false };
  async function renderResearchLoop(host, pol, tried) {
    if (!host) return;
    if (!rsiLoop.inflight && Date.now() - rsiLoop.at > 60000) {
      rsiLoop.inflight = true;
      try { rsiLoop.board = await api('/api/research/scoreboard?days=14', undefined, { keep: true }); rsiLoop.at = Date.now(); }
      catch (e) { rsiLoop.at = Date.now(); /* keep the last board; the old card still renders */ }
      finally { rsiLoop.inflight = false; }
    }
    const b = rsiLoop.board;
    if (!b || !b.total || !b.total.runs) { renderRsiMomentum(host, pol, tried); return; }
    const t = b.total, tr = b.trend;
    const delta = tr ? `<span class="rsi-score">${loopRate(tr.before.gate_reach_rate)} <span class="rsi-arrow">→</span> ${loopRate(tr.after.gate_reach_rate)}</span>` : '';
    const tag = tr ? (tr.better ? '<span class="rsi-tag">Improving</span>' : '<span class="rsi-tag quiet">Not improving yet</span>') : '<span class="rsi-tag quiet">Learning</span>';
    const perIdea = t.explored ? usd(t.cost_usd / t.explored) : '—';
    const figs = `<dl class="figures measure loop-figs">${fig('Ideas tried', t.explored, { small: `${t.runs} session${t.runs === 1 ? '' : 's'} ·\u00a014 days` })}${fig('Reached the gate', t.gated, { small: `${loopRate(t.gate_reach_rate)} of ideas` })}${fig('Passed', t.passed, { small: t.holdout_passed ? `${t.holdout_passed} held out` : 'every gate' })}${fig('Spend', usd(t.cost_usd), { small: `${perIdea} per idea` })}${fig('Killed by our pipeline', loopRate(t.pipeline_death_share), { small: 'of dropped ideas' })}</dl>`;
    const trendP = tr
      ? `<p class="loop-trend">${tr.better ? 'Getting better.' : 'Not better yet.'} The newer ${tr.after.runs} session${tr.after.runs === 1 ? '' : 's'} took ${loopRate(tr.after.gate_reach_rate)} of ${tr.after.explored} ideas to the statistical gate, against ${loopRate(tr.before.gate_reach_rate)} of ${tr.before.explored} before.</p>`
      : `<p class="loop-trend">Each session's ideas are counted from first draft to final verdict. A before/after trend appears once there are 16 ideas to compare.</p>`;
    const maxIdeas = Math.max(1, ...(b.days || []).map((d) => d.explored));
    const days = (b.days || []).length > 1 ? `<div class="loop-days" role="img" aria-label="Ideas per day and how many reached the gate">${b.days.slice(-14).map((d) => `<span class="loop-day" title="${esc(d.day)}: ${d.explored} ideas, ${d.gated} reached the gate"><i class="all" style="height:${Math.max(4, Math.round(40 * d.explored / maxIdeas))}px"></i><i class="hit" style="height:${d.gated ? Math.max(3, Math.round(40 * d.gated / maxIdeas)) : 0}px"></i></span>`).join('')}</div><p class="loop-legend"><i class="all"></i>ideas per day <i class="hit"></i>reached the gate</p>` : '';
    const pt = b.paper && b.paper.total, byPb = (b.paper && b.paper.by_playbook) || {};
    const paperP = pt && pt.strategies ? `<p class="loop-trend">On paper against the live book: ${pt.strategies} passed strateg${pt.strategies === 1 ? 'y' : 'ies'}, ${pt.trading} trading, ${pt.round_trips} round trip${pt.round_trips === 1 ? '' : 's'}, net ${usd(pt.net_pnl, true)}${pt.realization == null ? '' : pt.realization < 0 ? ', losing money where the backtest expected a profit' : `, earning ${Math.round(pt.realization * 100)}% of what the backtest expected`}${pt.live_ready ? ` ·\u00a0${pt.live_ready} ready for live` : ''}.</p>` : '';
    const fams = {};
    (b.playbooks || []).forEach((p) => { (fams[p.family] = fams[p.family] || {})[p.status] = p; });
    const pbRows = Object.keys(fams).sort().map((f) => {
      const a = fams[f].active, c = fams[f].candidate;
      const paper = (p) => { const q = byPb[p.id] || byPb[String(p.id)]; return q && q.round_trips ? ` ·\u00a0on paper ${q.round_trips} trips, ${usd(q.net_pnl, true)}` : ''; };
      const rec = (p) => (p.ideas ? `${p.reached} of ${p.ideas} ideas reached the gate` : 'no ideas yet') + paper(p);
      const act = a ? `<b>v${a.version}</b> in use${a.version ? '' : ' (no lessons yet)'} ·\u00a0${rec(a)}` : '';
      const cand = c ? `<br><b>v${c.version}</b> on trial ·\u00a0${rec(c)}${c.p_better != null ? ` ·\u00a0${Math.round(c.p_better * 100)}% likely better` : ''}${c.changes ? `<span class="loop-why">What changed: ${esc(c.changes)}</span>` : ''}` : '';
      const text = (c && c.text) || (a && a.text) || '';
      return `<li><span class="loop-k">${esc(loopFamily(f))}</span><span class="loop-v">${act}${cand}${text ? `<details class="loop-pb"><summary>Read the playbook</summary><pre>${esc(text)}</pre></details>` : ''}</span></li>`;
    }).join('');
    const scout = (b.scout || []).slice(0, 5).map((s) => `<li><span class="loop-k">${esc(marketShort(s.market))}</span><span class="loop-v">${esc(s.best_what || '')} ·\u00a0${s.best_net_c != null ? (s.best_net_c > 0 ? '+' : '') + s.best_net_c.toFixed(1) + '¢' : ''} net per contract ·\u00a0${s.best_z != null ? s.best_z.toFixed(1) : '—'} SE</span></li>`).join('');
    const fixes = (b.fix_list || []).slice(0, 5).map((x) => `<li><span class="loop-k">${esc(marketShort(x.market))}</span><span class="loop-v"><b>${esc(LOOP_TAG[x.tag] || x.tag)}</b> × ${x.count}${x.example ? `<span class="loop-why">${esc(String(x.example).slice(0, 180))}</span>` : ''}</span></li>`).join('');
    const REQ_KIND = { history: 'more settled history', micro: 'order-book feature', ticks: 'per-second data' };
    const REQ_STATE = { open: 'collecting', ready: 'data arrived', requeued: 'idea re-tested', expired: 'gave up' };
    const reqs = (b.data_requests || []).slice(0, 6).map((r) => `<li><span class="loop-k">${esc(marketShort(r.market))}</span><span class="loop-v"><b>${esc(REQ_KIND[r.kind] || r.kind)}${r.need ? ' ·\u00a0' + esc(r.need) : ''}</b> ·\u00a0${esc(REQ_STATE[r.status] || r.status)}${r.requeued_run_id ? ` ·\u00a0<a href="/research/${r.requeued_run_id}">session</a>` : ''}${r.idea_title ? `<span class="loop-why">For: ${esc(r.idea_title)}</span>` : ''}${r.status !== 'requeued' && r.note ? `<span class="loop-why">${esc(r.note)}</span>` : ''}</span></li>`).join('');
    const sect = (h, sub, items) => items ? `<div class="loop-sect"><h4>${h}</h4><p class="loop-sub">${sub}</p><ul class="loop-list">${items}</ul></div>` : '';
    const tn = b.tournament, tnEnt = tn ? (tn.entrants || []).filter((r) => r.strategy_id).sort((x, y) => y.weight - x.weight) : [];
    const tnCash = tn ? (tn.entrants || []).find((r) => !r.strategy_id) : null;
    const tnRows = tnEnt.slice(0, 8).map((r) => `<li><span class="loop-k">${esc(marketShort(r.market))}</span><span class="loop-v"><b>${Math.round(r.weight * 100)}% of the book</b> ·\u00a0${esc(r.title || '')} ·\u00a0${r.trips} bet${r.trips === 1 ? '' : 's'}, ${usd(r.net_pnl, true)} ·\u00a0${Math.round((r.p_positive || 0) * 100)}% likely to make money${r.verdict ? `<span class="loop-why">Retiring: ${esc(r.verdict)}</span>` : ''}</span></li>`).join('')
      + (tnEnt.length && tnCash ? `<li><span class="loop-k">Cash</span><span class="loop-v"><b>${Math.round(tnCash.weight * 100)}% of the book</b> ·\u00a0held back until an entrant beats zero</span></li>` : '');
    const tnSub = tn && tn.pooled ? `Every near miss trades on paper at once, and a bandit moves a ${usd(tn.book.capital)} practice book toward what earns. All entrants together: ${tn.pooled.trips} of the ${tn.pooled.target} independent bets the gate needs${tn.pooled.days_to_target != null ? `, about ${Math.round(tn.pooled.days_to_target)} days to go at ${tn.pooled.per_day} a day` : ''}${tn.pooled.mean_return != null ? `, averaging ${(tn.pooled.mean_return * 100).toFixed(1)}% of stake a bet` : ''}. Book so far: ${usd(tn.book.pnl, true)} over ${tn.book.trips} trade${tn.book.trips === 1 ? '' : 's'}.` : '';
    const body = figs + trendP + days + paperP
      + sect('Paper tournament', tnSub, tnRows)
      + sect('What it has learned', 'After every session the loop rewrites a playbook for that kind of market from its verdicts. A rewrite is tried on new sessions and kept only if more of its ideas reach the gate.', pbRows)
      + sect('Where it looks next', 'A free scan of every market for prices that disagree with how they settle, after fees. Leads steer research; they still have to pass on unseen data.', scout)
      + sect('Ideas our pipeline killed', 'Dropped because of missing data or features, not because the market said no. This is the fix list.', fixes)
      + sect('Data it asked for', 'Crypto ideas that died for lack of data start a collection, and the idea is re-tested once the data exists (autopilot on, at most once each).', reqs)
      + (pol && pol.evolved ? `<p class="rsi-last">Finalist policy evolved from your history${pol.base_score != null && pol.score != null ? ` ·\u00a0score ${pol.base_score} → ${pol.score}` : ''}.</p>` : '');
    const open = !!host.querySelector('details.rsidisc[open]');
    const focused = !!host.querySelector('details.rsidisc > summary:focus');
    const inner = [...host.querySelectorAll('details.loop-pb')].map((d) => d.open);
    // The 5s poll re-renders from the kept board: the card is rebuilt only when its markup changed.
    paint(host, `<details class="rsidisc loop"${open ? ' open' : ''}>
      <summary class="rsidisc-cap"><b class="rsi-badge">RSI</b><span class="rsidisc-t">Is research getting better?</span>${tag}${delta ? `<span class="rsidisc-delta">${delta} reach the gate</span>` : ''}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
      <div class="rsidisc-body">${body}</div>
    </details>`);
    host.querySelectorAll('details.loop-pb').forEach((d, i) => { if (inner[i] && !d.open) d.open = true; });
    if (focused) host.querySelector('details.rsidisc > summary').focus({ preventScroll: true });
  }
  // Figure 1 -- the real Tau research pipeline, drawn as a styled node-and-connector flow (no
  // ASCII, no monospace). Stages verified against the code: agent.py (proposer + challenger),
  // partitions.py (60/25/15 split with purge + embargo), gatekeeper.py (the test battery and
  // its rejected/inconclusive verdicts), dreaming.py (the Tau-RSI exploration-policy loop).
  // Collapsible, so a repeat user can fold it and get straight to the form.
  const FLOW_RIGHT = '<svg class="flow-arrow" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
  const LOOP_ICON = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 4v5h-5"/></svg>';
  const fnode = (k, d, opts = {}) => `<div class="node${opts.cls ? ' ' + opts.cls : ''}"><span class="node-k">${k}</span>${opts.extra || ''}<span class="node-d">${d}</span></div>`;
  // The connector reads left→right in the horizontal flow; CSS rotates it to point
  // down when the row stacks vertically at phone width.
  const flowLink = `<div class="flow-link">${FLOW_RIGHT}</div>`;
  const fphase = (n) => `<div class="flow-phase"><span>${n}</span></div>`;
  // A phase label plus its nodes, laid out as a horizontal row (far less vertical space
  // than a single tall column); the row wraps on narrow screens, stacks at phone width.
  const fstage = (phase, nodes) => `<section class="flow-stage">${fphase(phase)}<div class="flow-row">${nodes.join(flowLink)}</div></section>`;
  function pipelineFigure() {
    const gates = ['Bootstrap CI', 'PSR', 'DSR ·\u00a0deflated by trial count', 'Placebo / null', 'LORD++ FDR budget', 'Purged walk-forward', 'Benjamini–Hochberg'];
    return `<details class="pipefig">
      <summary class="pipecap"><b>Figure 1</b> <span class="pipecap-t">The Tau research pipeline</span><span class="pipecap-hint">how your idea becomes a deployable, evidence-backed strategy</span><span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
      <div class="flow">
        ${fstage('Propose', [
          fnode('Idea', 'Your hypothesis, in a sentence.', { cls: 'node-in' }),
          fnode('Proposer', 'An agent writes several concrete, testable strategy specs. A challenger vets each one — approve, revise, or reject — before a cent of held-out data is spent.', { cls: 'node-proposer' }),
          fnode('Pre-register &amp; freeze', 'The hypothesis, its metric, and its test are fixed and hashed before the agent sees any held-out data — so a result can’t be fitted after the fact.'),
        ])}
        <div class="unseen-cut"><span>Unseen by the agent below</span></div>
        ${fstage('Test on unseen data', [
          fnode('Partition the history', 'A purge + embargo gap sits at every cut, so no trade straddles a boundary. The agent only ever iterates on Research.', { cls: 'partnode', extra: '<div class="partbar" aria-hidden="true"><span class="pb res" style="flex:60"></span><span class="pb val" style="flex:25"></span><span class="pb hold" style="flex:15"></span></div><div class="partleg"><span><i class="sw res"></i>Research 60%</span><span><i class="sw val"></i>Validation 25%</span><span><i class="sw hold"></i>Locked holdout 15%</span></div>' }),
          fnode('Backtest, net of fees', 'Every spec is simulated after real Kalshi taker fees. A gross edge that fees eat does not count.'),
          fnode('Statistical gatekeeper', 'A battery of tests on the validation window, corrected for how many ideas were tried. A real edge has to clear all of them at once.', { cls: 'gate-node', extra: `<div class="gate-tests">${gates.map((g) => `<span class="gt">${g}</span>`).join('')}</div><div class="gate-out"><span class="gout-lead">Most ideas exit here —</span><span class="gout">Rejected</span><span class="gout">Inconclusive</span><span class="gout-note">logged to an immutable ledger, so the trial count stays honest</span></div>` }),
        ])}
        ${fstage('Confirm', [
          fnode('One-time holdout', 'The locked 15% is spent once, and only for a finalist the validation window already supported.'),
          fnode('Marginal-contribution check', 'It must add something new — low correlation (|ρ| ≤ 0.80) to the strategies you already run.'),
          fnode('<span class="mk on">Passed</span> Deployment candidate', 'An edge that survived every check on data it never saw.', { cls: 'pass-node' }),
        ])}
        ${fstage('Trade', [
          fnode('Paper first', 'Proven on paper with realistic fills: 30+ closed trades from 20+ separate events over 48h+, net up, a statistically clear edge that is still working. Only then can anything touch real money.'),
          fnode('<span class="mk">Gated</span> Live money', 'Only in your own Kalshi account, and only when you explicitly arm it. Off by default.', { cls: 'live-node' }),
        ])}
        <div class="rsi-loopback">
          <span class="loopback-arc" aria-hidden="true"></span>
          <span class="loopback-label"><span class="loop-ico">${LOOP_ICON}</span><span class="loopback-txt"><b>Tau-RSI loop</b> — the evolved exploration policy feeds back into the Proposer</span></span>
        </div>
      </div>
      <p class="rsi-loop"><span><b>How the loop learns.</b> After each cycle the engine re-scores and <b>rewrites its own exploration policy</b> from your history — graded on how well it generalizes to unseen data across many shuffled replays — then feeds the improved policy back to the Proposer, so the next batch explores smarter.</span></p>
    </details>`;
  }
  // A run-until-stopped session is one session that keeps exploring a fresh round of ideas, so its
  // figure is per round (a finished set-size session is about one round); a set-size one is per session.
  function sessionCostLine(v, forever, own) {
    const basis = own ? 'your recent sessions' : 'recent sessions on this model';
    return forever
      ? `Each round of ideas usually costs about ${usd(v)} (${basis}); it keeps starting new rounds until you stop it.`
      : `A session like this usually takes about ${usd(v)} from your credits (${basis}).`;
  }
  // Run-until-stopped has no natural size, so say its pace: about what an hour costs at recent rates
  // (/api/research/estimate per_hour, the user's own else the model's typical) and how long the
  // balance covers that. It stops by itself only when credits run out, unless auto-reload tops up.
  function foreverRateLine(hourly, own, me) {
    let s = hourly == null ? '' : `At recent rates it costs about ${usd(hourly)} an hour (${own ? 'your recent sessions' : 'recent sessions on this model'}).`;
    if (!me || !me.billing_enabled) return s;
    const bal = +me.credit_balance || 0, h = hourly > 0 ? bal / hourly : null;
    if (h != null && bal > 0) s += ` Your ${usd(bal)} covers ${h < 1 ? 'less than an hour' : h < 48 ? `about ${Math.round(h)} hour${Math.round(h) === 1 ? '' : 's'}` : `about ${Math.round(h / 24)} days`}.`;
    const ar = me.auto_reload;
    // What auto-reload charges the card is said with it (credits plus the purchase fee), and a declined
    // reload card is not promised as a top-up: the session stops when credits run out.
    return (s + (ar && me.reload_failed ? ' Auto-reload couldn’t charge your card, so it stops by itself if your credits run out.'
      : ar ? ` Auto-reload adds ${usd(ar.amount)} when your balance falls to ${usd(ar.threshold)}, charging your card ${usd(ar.charge)}.`
      : ' It stops by itself if your credits run out.')).trim();
  }
  // A research idea typed before the session ran out is kept for this tab (sessionStorage) and put back
  // when the same account signs in and lands on the same page; a 401 sends the reader to sign in and
  // the box used to come back empty. It is dropped once the session starts or the box is cleared.
  const DRAFT_KEY = 'tau_research_draft';
  function keepDraft(ta) {
    const uid = S.me && S.me.user ? S.me.user.id : null, path = location.pathname;
    try {
      const d = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || 'null');
      if (d && d.uid === uid && d.path === path && typeof d.text === 'string' && !ta.value) ta.value = d.text.slice(0, 1000);
    } catch (e) { /* storage off or unreadable: no draft */ }
    const save = () => {
      try {
        if (ta.value.trim()) sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ uid, path, text: ta.value }));
        else sessionStorage.removeItem(DRAFT_KEY);
      } catch (e) { /* private mode or full: the box still works */ }
    };
    ta.addEventListener('input', save);
    return { save, drop: () => { try { sessionStorage.removeItem(DRAFT_KEY); } catch (e) { /* nothing kept */ } } };
  }
  async function viewResearch() {
    const me = S.me;
    const DEMO_PROMPT = "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances";
    shell('/research', '', loading(320));  // switch pages at once; the model list can be slow
    // /api/me carries the model list, so the page's own reads below don't wait a round trip on it.
    const mdl = (me && me.models) || await api('/api/models').catch(() => ({ models: [], default: '' }));
    const modelOpts = (mdl.models || []).map((m) => `<option value="${esc(m.key)}"${m.key === mdl.default ? ' selected' : ''}${m.available === false ? ' disabled' : ''}>${esc(m.label)}${m.available === false ? ' (access pending)' : ''}</option>`).join('');
    shell('/research', boardTitle('Research', 'A self-improving research engine for Kalshi markets \u2014 describe an idea, it writes strategies and tests each on data it never saw.'), `
      ${S.me.user && !S.me.user.autopilot ? `<p class="research-ap">Rather not write ideas yourself? <button type="button" data-research-ap>Turn on autopilot</button> and it picks ideas and researches them on its own, on paper.</p>` : ''}
      <div id="rexample"></div>
      <form class="panel dispatch" id="dispatch">
        <h3>${ICON.spark2}New research session</h3>
        ${me.needs_card ? `<div class="notice" role="status">${ICON.warn}<span>Add a payment method to start researching. Your $${me.free_bonus} in free credits unlock the moment a card is on file — you won't be charged until they run out. <a href="/billing">Add a card →</a></span></div>` : ''}
        ${(!me.needs_card && me.billing_enabled && me.credit_balance < me.min_run_balance) ? `<div class="notice" role="status">${ICON.warn}<span>You have ${usd(me.credit_balance)} in credits — a research session needs at least ${usd(me.min_run_balance)} to start. ${me.reload_failed ? 'Auto-reload couldn’t charge your card. <a href="/billing">Update your card and add credits →</a>' : '<a href="/billing">Add credits →</a>'}</span></div>` : ''}
        <label class="field"><span>Describe your idea</span>
          <textarea class="input" name="prompt" maxlength="1000" rows="3" required placeholder="Write your own — e.g. &quot;Sell overpriced tails in the last hour before the 5pm close.&quot;"></textarea></label>
        <details class="dispatch-opts" id="ropts"${phone() ? '' : ' open'}><summary><span class="dispatch-opts-t">Options</span><span class="dispatch-opts-sum" id="ropts-sum"></span></summary><div class="dispatch-opts-body">
        <div class="dispatch-tune">
          ${modelOpts ? `<label class="field"><span>Model</span>
            <select class="input" name="model" id="rmodel">${modelOpts}</select></label>` : ''}
          <label class="field"><span>Strategies to test</span>
            <input class="input" type="number" name="max_hypotheses" id="maxhyp" min="1" max="1000" value="10"></label>
          <label class="switch tune-sw"><input type="checkbox" name="run_forever" id="runforever" checked><span>Let it run until I stop it</span></label>
        </div>
        <fieldset class="field mkt-field" style="border:0;padding:0;margin:0"><legend class="label" style="margin-bottom:8px">Market</legend>
          ${marketPicker(me.markets)}
        </fieldset>
        </div></details>
        <div class="dispatch-go">
          <a class="chip ex" href="/example" data-ex-open title="Opens the finished example session; nothing runs">See the demo — Todd's random walk</a>
          <button type="button" class="linkish ex-run" data-ex="${esc(DEMO_PROMPT)}">or run it yourself</button>
          <button class="btn primary go" type="submit" ${me.needs_card ? 'aria-disabled="true"' : ''}>${ICON.spark2}Start session</button>
        </div>
        <p class="hint ex-cost" id="ex-cost" hidden></p>
        <p class="hint go-cost" id="rcost" hidden></p>
        <div id="dflash"></div>
        <p class="hint" id="rf-hint">A session takes a few minutes and keeps running if you leave this page.</p>
      </form>
      <div class="rengine" id="rengine">
        <div class="statusline" id="rstatus"><p class="said"></p></div>
        <dl class="figures measure" id="rfigs"></dl><p class="stale-note" id="runs-stale" role="status"></p>
        <div id="rsimo"></div>
      </div>
      ${pipelineFigure()}
      <section class="sect"><div class="sect-head"><h2>Your sessions</h2><p id="rcount"></p></div>
        <div id="flash"></div><div class="runs" id="runs">${loading(70)}${loading(70)}</div></section>`);
    const form = root.querySelector('#dispatch');
    wireMarketPicker(form);
    const wantMkt = new URLSearchParams(location.search).get('market');
    const pickMkt = wantMkt && [...form.querySelectorAll('input[name=market]')].find((r) => r.value === wantMkt);
    if (pickMkt) {
      pickMkt.checked = true;
      const grp = pickMkt.closest('details'); if (grp) grp.open = true;
      const opts = form.querySelector('#ropts'); if (opts) opts.open = true;
    }
    // Model, depth and market fold behind "Options" on a phone (closed while at their defaults), so
    // Start session sits right under the idea. The summary line says what will run.
    const optsSum = form.querySelector('#ropts-sum');
    const syncOpts = () => {
      if (!optsSum) return;
      const msel = form.querySelector('#rmodel'), rfx = form.querySelector('#runforever'), mhx = form.querySelector('#maxhyp');
      const mo = msel ? [...msel.options].find((o) => o.value === msel.value) : null;
      const pick = [...form.querySelectorAll('input[name=market]')].find((r) => r.checked);
      const row = pick && pick.value ? pick.closest('.mktrow') : null, nm = row && row.querySelector('.mktrow-name');
      optsSum.textContent = [mo ? mo.textContent.trim() : '', rfx && rfx.checked ? 'runs until you stop it' : `${(mhx && mhx.value) || 10} strategies`,
        nm ? nm.textContent.trim() : 'agent\u2019s choice of market'].filter(Boolean).join(' \u00b7\u00a0');
    };
    form.addEventListener('change', syncOpts); syncOpts();
    const ta = form.querySelector('textarea[name=prompt]');
    const draft = keepDraft(ta);
    // "Run it yourself" fills the box with the example's idea and says plainly that it's a new, paid
    // session (with the usual cost beside Start when there's one); the demo link opens the finished one.
    root.querySelectorAll('[data-ex]').forEach((b) => (b.onclick = () => {
      ta.value = b.dataset.ex; ta.focus(); draft.save();
      const note = form.querySelector('#ex-cost'), rc = form.querySelector('#rcost');
      if (!note) return;
      note.hidden = false;
      note.textContent = !me.billing_enabled ? 'This starts a new session from scratch. The example already shows how this idea ends.'
        : `This starts a new session that uses your credits; the example already shows how this idea ends.${rc && !rc.hidden && rc.textContent ? ' ' + rc.textContent : ''}`;
    }));
    const rf = form.querySelector('#runforever'), mh = form.querySelector('#maxhyp');
    let syncCost = () => {};  // the cost line below follows the run-forever switch too
    if (rf && mh) {
      const rh = form.querySelector('#rf-hint');
      const syncRf = () => { mh.disabled = rf.checked; mh.style.opacity = rf.checked ? '.4' : ''; if (rh) rh.textContent = rf.checked ? 'Runs until you stop it, using credits as it goes. It keeps running if you leave this page.' : 'A session takes a few minutes and keeps running if you leave this page.'; };
      rf.addEventListener('change', () => { syncRf(); syncCost(); }); syncRf();  // default on -> depth dimmed
    }
    // What a session usually costs, beside Start: real ledger debits from /api/research/estimate,
    // the user's own median or else the typical one for the chosen model. No data, no line.
    (() => {
      const rc = form.querySelector('#rcost'), msel = form.querySelector('#rmodel');
      if (!rc) return;
      let est = null;
      const sync = syncCost = () => {
        const own = !!est && est.yours != null, key = (msel && msel.value) || mdl.default;
        const v = !est ? null : own ? est.yours : (est.typical || {})[key];
        const forever = !!(rf && rf.checked), ph = (est && est.per_hour) || {};
        const hourly = ph.yours != null ? ph.yours : (ph.typical || {})[key];
        const pace = forever && (v != null || hourly != null) ? foreverRateLine(hourly == null ? null : +hourly, ph.yours != null, me) : '';
        // No ledger figure for this model (or the read failed): with payments on, still say how it
        // is billed and that it can be stopped, rather than leaving the cost blank.
        const none = v == null && !pace && me.billing_enabled ? 'No cost estimate for this model yet. It\u2019s charged to your credits as it runs, and you can stop it any time from its session page.' : '';
        rc.hidden = v == null && !pace && !none;
        rc.textContent = [v == null ? '' : sessionCostLine(+v, forever, own), pace, none].filter(Boolean).join(' ');
      };
      if (msel) msel.addEventListener('change', sync);
      api('/api/research/estimate').then((d) => { est = d; }, () => { est = null; }).then(sync);
    })();
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (me.needs_card) { flash('#dflash', 'Add a payment method on the Billing tab first.', 'bad'); go('/billing'); return; }
      const fd = new FormData(form);
      const btn = form.querySelector('button[type=submit]');
      draft.save();
      await busy(btn, async () => {
        try {
          const r = await api('/api/runs', {
            market: fd.get('market'), prompt: fd.get('prompt'),
            max_hypotheses: Number(fd.get('max_hypotheses')) || undefined,
            run_forever: fd.get('run_forever') === 'on',
            model: fd.get('model') || undefined,
          });
          draft.drop();
          go('/research/' + r.id);
        } catch (err) { flash('#dflash', err.message, 'bad'); }
      });
    };
    // Live market context: fold the shared book onto each picker row (read-only). Rows with no
    // live quote right now are labelled once the feed resolves; the picker works either way.
    (async () => {
      try {
        const c = await api('/api/research/context');
        (c.markets || []).forEach((m) => fillLiveRow(form, m));
      } catch (e) { /* no feed yet -> the picker still works blind */ }
      markQuietRows(form);
    })();
    // The poll sends back the version of its last full answer; while nothing the list shows has moved the
    // server answers {same: true} from two reads, and the page repaints from the answer it kept (its
    // relative times still move). Each region is rewritten only when its markup changed.
    let kept = null;
    const load = async () => {
      const got = await api('/api/runs' + (kept && kept.v ? '?since=' + encodeURIComponent(kept.v) : ''));
      const d = got.same && kept ? kept : (kept = got);
      // All-time totals from the server; the 50 newest runs undercount a busy autopilot.
      const tried = d.totals ? d.totals.tried : d.runs.reduce((a, r) => a + (r.hypotheses_tried || 0), 0);
      const passed = d.totals ? d.totals.passed : d.runs.reduce((a, r) => a + (r.strategies_passed || 0), 0);
      // A paused session holds one of the two session slots but isn't researching: it says paused.
      const running = d.counts.research_running, queued = d.counts.research_queued, paused = d.counts.research_paused || 0;
      const said = running || paused
        ? `${[running ? `<em>${running}</em> agent${running > 1 ? 's' : ''} researching now` : '', paused ? `<em>${paused}</em> paused` : '', queued ? `<em>${queued}</em> waiting` : ''].filter(Boolean).join(' ·\u00a0')} — <em>${tried}</em> hypotheses tested, <em>${passed}</em> through every gate.`
        : tried
          ? `Your engine has tested <em>${tried}</em> hypotheses and kept <em>${passed}</em> that beat every gate. ${S.me.user && S.me.user.autopilot ? 'Autopilot starts its next run on its own; <a href="#dispatch">add an idea</a> to steer it.' : '<a href="#dispatch">Seed another idea</a> to keep hunting.'}`
          : `<a href="#dispatch">Describe an idea</a> — the engine turns it into strategies and tests each on data it never saw.`;
      paint(root.querySelector('#rstatus .said'), said);
      paint(root.querySelector('#rfigs'), fig('Researching now', running, { small: paused ? `${paused} paused` : '' }) + fig('Waiting', queued) +
        fig('Hypotheses tested', tried) + fig(gl('Passed every gate', 'gate'), passed, { small: tried ? `${pct(passed / tried, false)} pass rate` : '' }));
      renderResearchLoop(root.querySelector('#rsimo'), d.policy, tried);
      // The seeded example is listed but isn't the user's: it doesn't count as a run of theirs.
      const own = d.runs.filter((r) => !r.example).length, examples = d.runs.length - own;
      const rex = root.querySelector('#rexample'), exHtml = exampleLine(d.runs);
      if (rex && rex.dataset.h !== exHtml) { rex.dataset.h = exHtml; rex.innerHTML = exHtml; }
      const exRun = d.runs.find((r) => r.example), exOpen = root.querySelector('[data-ex-open]');
      if (exOpen) { const hide = !exRun || !!exHtml; if (exOpen.hidden !== hide) exOpen.hidden = hide; if (exRun && exOpen.getAttribute('href') !== '/research/' + exRun.id) exOpen.setAttribute('href', '/research/' + exRun.id); }
      // Phones: progress before the form, unless they came here to start one ("Try another idea", ?new=1).
      const mainEl = root.querySelector('#main'); if (mainEl) mainEl.classList.toggle('runs-first', own > 0 && !/[?&]new=1\b/.test(location.search));
      paint(root.querySelector('#rcount'), esc([own ? `${own} run${own > 1 ? 's' : ''}` : '', examples ? `${examples} example` : ''].filter(Boolean).join(' \u00b7\u00a0')));
      const newest = d.runs.find((r) => !r.example);
      paintRows(root.querySelector('#runs'), d.runs.map((r) => [r.id, runRow(r, r === newest)]),
        `<div class="empty"><h3>No sessions yet</h3><p>Describe an idea above. The agent will turn it into several strategies, test each one on data it never saw, and mark each Passed or Void.</p></div>`);
    };
    await load();
    poll(load, 5000, 'runs-stale');
  }
  // What a run has taken from credits (the ledger rows billed to it, `spent_usd` from the server).
  // A run still going says "so far"; a finished one states its cost.
  const runLive = (r) => r.status === 'running' || r.status === 'queued' || r.status === 'paused';
  // Which model a session uses and how far it goes, beside its market on the run page: it never said
  // either. model_label is the model's customer name from the server (the run's key is NULL for the
  // default model); run_forever is the form's "Let it run until I stop it", else its strategy count.
  const runSetup = (r) => [r.model_label ? esc(r.model_label) : '',
    r.run_forever ? (runLive(r) ? 'Runs until you stop it' : 'Ran until stopped')
      : r.max_hypotheses ? `Up to ${num(r.max_hypotheses)} strateg${+r.max_hypotheses === 1 ? 'y' : 'ies'}` : ''].filter(Boolean).join(' \u00b7\u00a0');
  const runSpent = (r) => r.spent_usd == null ? '' : `${runLive(r) ? 'Spent so far' : 'Cost'}: ${usd(r.spent_usd)}`;
  // A queued or running session past the reaper's limit (the server's run.wait), its seconds moved on by
  // the time since that answer: the list counts a silent session out of "Running", so its row says
  // "Silent 25 min" as the run page does, not "Researching" beside "Running 0".
  const runLate = (r) => {
    const w = r.wait;
    if (!w || !w.overdue || (r.status !== 'running' && r.status !== 'queued')) return null;
    if (w.got == null) w.got = Date.now();
    return { ...w, seconds: (+w.seconds || 0) + Math.round((Date.now() - w.got) / 1000) };
  };
  const lateLabel = (w) => (w.state === 'queued' ? 'Waiting ' : 'Silent ') + waitSpan(w.seconds);
  // Why a finished session stopped, from the server (services.run_stop). A run-until-stopped session
  // that used up the credits ends "succeeded" and read like one that finished; a cancelled or failed
  // one said "Cancelled" or "Failed" without who or what stopped it.
  const RUN_STOP = { credits: 'Out of credits', user: 'Stopped by you', error: 'Stopped on an error', limit: 'Finished', complete: 'Finished' };
  // `newest`: the user's newest session. When it ran out of credits its card offers Add credits, beside
  // the card (a link can't sit inside the card's own link); older ones only say so.
  function runRow(r, newest) {
    const why = RUN_STOP[r.stop_reason] || '', late = runLate(r);
    const state = late ? lateLabel(late) : r.status === 'running' ? 'Researching<span class="working" aria-label="in process"></span>'
      : r.status === 'queued' ? 'Waiting<span class="working" aria-label="in process"></span>'
      : r.status === 'succeeded' ? `${why ? why + ' \u00b7\u00a0' : ''}<span class="${r.strategies_passed ? 'gain' : ''}">${r.strategies_passed} of ${r.hypotheses_tried} passed</span>`
      : r.status === 'stopped' ? `Explored ${r.hypotheses_tried} hypothes${r.hypotheses_tried === 1 ? 'is' : 'es'}${r.strategies_passed ? ` ·\u00a0<span class="gain">${r.strategies_passed} passed</span>` : ''}`
      : r.status === 'paused' ? 'Paused'  // fell through to a red "Failed" while it waited on Resume
      : r.status === 'cancelled' ? (why || 'Cancelled') : `<span class="loss">${why || 'Failed'}</span>`;
    // status band: a thin color rule so passed/void/failed reads at a glance. A `stopped` run (frozen,
    // interrupted, or capped) is neutral (void), NOT red — only a real error is `fail`.
    const band = r.status === 'succeeded' ? (r.strategies_passed ? 'ok' : 'void') : r.status === 'failed' ? 'fail' : (r.status === 'cancelled' || r.status === 'stopped') ? 'void' : 'live';
    const card = `<a class="run-card ${band}" href="/research/${r.id}">
      <span class="run-title"><b title="${esc(sessionTitle(r))}">${esc(sessionTitle(r))}</b>${runTag(r)}</span>
      <span class="run-meta">${esc(marketShort(r.market))}${r.example ? ' \u00b7\u00a0' + EXAMPLE_NOTE : r.spent_usd != null ? ' \u00b7\u00a0' + runSpent(r) : ''}${r.error ? ' \u00b7\u00a0' + esc(r.error) : ''}</span>
      <span class="run-foot"><span class="run-state">${state}</span><span class="run-when">${when(r.created_at)}</span></span></a>`;
    return newest === true && r.stop_reason === 'credits' ? `<div class="run-cell">${card}<a class="run-add" href="/billing">Add credits<span class="vh"> to keep researching</span></a></div>` : card;
  }

  // ======================================================================
  // Live research feed — a Claude-Code-style streaming agent log.
  // Shared, BYTE-IDENTICAL across both themes (app.js / app.meridian.js). A running session
  // streams its reasoning here as it happens: each thought, each hypothesis + thesis, each
  // backtest result, the challenger's verdict and the gatekeeper's classification land as nodes
  // on a timetable rail. Newest at the bottom like a terminal; the view sticks to the latest
  // only while the reader is already at the foot, so scrolling up to read never gets yanked back.
  // Polling (every 2s) drives it — no SSE, so it works under `script-src 'self'`.
  // ======================================================================
  const RUN_LANE = { step: 'thought', thinking: 'think', hypothesis: 'action', challenger: 'review', verdict: 'result', done: 'done', paused: 'state', resumed: 'state', error: 'alert' };

  function runMechText(m) {
    if (!m || typeof m !== 'object') return '';
    const v = m.why || m.mechanism || m.edge || m.rationale || m.because;
    return typeof v === 'string' ? v : '';
  }

  // The economic mechanism, as the structured four-part case the proposer pre-registers (who is
  // on the other side, why it isn't arbitraged, when, why it persists) — or the older free-text form.
  function mechHtml(m) {
    if (!m || typeof m !== 'object') { const s = runMechText(m); return s ? `<p class="hx-why">${esc(s)}</p>` : ''; }
    const rows = [['Who pays', m.who_pays], ['Not arbitraged because', m.why_not_arbitraged], ['When', m.when], ['Why it persists', m.why_persists]].filter(([, v]) => v);
    if (!rows.length) { const s = runMechText(m); return s ? `<p class="hx-why">${esc(s)}</p>` : ''; }
    return `<dl class="hx-mech">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`;
  }

  // Render the strategy spec as what it actually IS, so a fitted model never masquerades as a
  // flat if-else threshold. Three shapes: a learned DSL model (model.kind logistic/calibration —
  // a fitted P(YES) model, shown with its features/weights), an agent-authored code model (real
  // Python, fit-on-research-and-frozen), or a plain threshold rule (the house GBM — unchanged).
  // The execution gates (side, price band, time-to-settle, spread, exit) and sizing are real
  // trade bounds and render identically for every shape.
  function specHtml(spec) {
    if (!spec || typeof spec !== 'object') return '';
    const row = (k, v) => (v == null || v === '') ? '' : `<dt>${k}</dt><dd>${esc(v)}</dd>`;
    const c = (v) => Math.round(v * 100) + '¢';
    const sz = spec.sizing || {};
    const sizing = `$${sz.stake != null ? sz.stake : 5} per trade ·\u00a0up to ${sz.max_positions != null ? sz.max_positions : 20} at once`;
    const codeFig = (src) => `<figure class="hx-code"><figcaption>Strategy code <span>Python ·\u00a0research sandbox only</span></figcaption><pre><code>${esc(src)}</code></pre></figure>`;

    // Code strategy: an arbitrary fitted model in the sandbox, not threshold fields. Show it as
    // one, keep the real source (and note the frozen fit, if the research run froze params in).
    if (spec.code) {
      const fit = (spec.params != null && spec.params !== '') ? ' ·\u00a0fit on research, frozen' : '';
      return `<dl class="hx-spec"><dt>Signal</dt><dd class="hx-model">custom code model${fit}</dd>
        ${row('Sizing', sizing)}</dl>${codeFig(spec.code)}`;
    }

    const e = spec.entry || {}, x = spec.exit || {}, m = spec.model || {};
    // Execution gates — the real trade bounds, identical for every spec shape.
    const bounds = [];
    if (e.min_price != null || e.max_price != null) bounds.push(`price ${e.min_price != null ? c(e.min_price) : '0¢'}–${e.max_price != null ? c(e.max_price) : '100¢'}`);
    if (e.min_tte_min != null || e.max_tte_min != null) bounds.push(`${e.min_tte_min != null ? e.min_tte_min : 0}–${e.max_tte_min != null ? e.max_tte_min : '∞'} min to settle`);
    if (e.max_spread != null) bounds.push(`spread ≤ ${c(e.max_spread)}`);
    const exit = [];
    if (x.take_profit != null) exit.push(`take profit at ${c(x.take_profit)}`);
    if (x.stop_loss != null) exit.push(`stop at ${c(x.stop_loss)}`);
    if (x.min_edge_to_hold != null) exit.push(`hold while edge ≥ ${pct(x.min_edge_to_hold, false)}`);
    const filters = (spec.filters && spec.filters.length)
      ? spec.filters.map((f) => typeof f === 'string' ? f : JSON.stringify(f)).join('; ') : '';
    const side = row('Side', (spec.side || 'yes').toUpperCase());
    const edge = e.min_edge != null ? `P(YES) edge ≥ ${pct(e.min_edge, false)}` : '';

    // Learned DSL model (logistic / calibration): a FITTED fair-value model, not a threshold.
    if (m.kind === 'logistic' || m.kind === 'calibration') {
      const feats = Array.isArray(m.features) ? m.features.filter(Boolean) : [];
      const signal = m.kind === 'calibration'
        ? 'fitted calibration of the market&rsquo;s own mid'
        : `fitted logistic${feats.length ? ' over ' + feats.map((f) => `<span class="hx-feat">${esc(f)}</span>`).join(', ') : ''}`;
      const coef = Array.isArray(m.coef) ? m.coef : [];
      // Compact fitted weights, only when they are present and line up with the named features.
      const weights = (coef.length && coef.length === feats.length && coef.every((n) => typeof n === 'number'))
        ? `<dt>Fitted weights</dt><dd class="hx-weights">${feats.map((f, i) => `<span class="hx-feat">${esc(f)}</span> ×${coef[i].toFixed(2)}`).join(' ·\u00a0')}${typeof m.intercept === 'number' ? ` ·\u00a0intercept ${m.intercept.toFixed(2)}` : ''}</dd>`
        : '';
      return `<dl class="hx-spec">
        ${side}
        <dt>Signal</dt><dd class="hx-model">${signal}${edge ? ' — enter when ' + edge : ''}</dd>
        ${weights}
        ${row('Only when', bounds.join(' ·\u00a0'))}
        ${row('Exit', exit.join(' ·\u00a0') || 'hold to settlement')}
        ${row('Regime filter', filters)}
        ${row('Sizing', sizing)}</dl>`;
    }

    // Plain DSL threshold strategy (house GBM / rules) — unchanged.
    const entry = [];
    if (edge) entry.push(`edge ≥ ${pct(e.min_edge, false)}`);
    entry.push(...bounds);
    return `<dl class="hx-spec">
      ${side}
      ${row('Enter when', entry.join(' ·\u00a0') || 'any priced contract')}
      ${row('Exit', exit.join(' ·\u00a0') || 'hold to settlement')}
      ${row('Regime filter', filters)}
      ${row('Sizing', sizing)}</dl>`;
  }

  // Why an idea did not pass: one row per gate it missed (server services.gate_explain), each with
  // what was measured, what was needed and one thing to try next. The server keeps each figure with
  // its unit (no-break spaces), so a phone wraps the words, never a number away from its label.
  function whyFailedHtml(lines) {
    if (!Array.isArray(lines) || !lines.length) return '';
    return `<ul class="why-failed">${lines.map((l) => `<li><b class="wf-label">${esc(l.label)}</b><span class="wf-fig">Measured ${esc(l.measured)}; needed ${esc(l.needed)}.</span><span class="wf-next"><b>Try next:</b> ${esc(l.next)}</span></li>`).join('')}</ul>`;
  }

  // The gatekeeper's numbers for the reader (their own result) — never fed back to the generator.
  function statGrid(s) {
    if (!s) return '';
    const num = (v, dp) => (v == null || typeof v !== 'number') ? null : v.toFixed(dp == null ? 2 : dp);
    const p = (v) => v == null ? null : (v < 0.001 ? '<0.001' : num(v, 3));
    const cells = [];
    const add = (k, v) => { if (v != null && v !== '') cells.push(`<div><dt>${k}</dt><dd>${v}</dd></div>`); };
    add('Trades', s.n_trades != null ? String(s.n_trades) : null);
    add('p-value', p(s.p_value));
    add('DSR', num(s.dsr));
    add('Sharpe', num(s.sharpe));
    if (s.ci && (s.ci.lo != null || s.ci.hi != null)) add('95% CI', `${pct(s.ci.lo, false)}…${pct(s.ci.hi, false)}`);
    add('Placebo p', p(s.placebo_p));
    if (s.max_drawdown != null) add('Max drawdown', usd(-Math.abs(s.max_drawdown), true));
    return cells.length ? `<dl class="hx-stats">${cells.join('')}</dl>` : '';
  }

  // A progressively-filled hypothesis card: intuition (thesis) and the in-sample stat sit in the
  // open; "Show the homework" expands the mechanism, the real spec/code, and the falsification +
  // placebo. The challenger's critique and the gatekeeper's stamped verdict are grafted onto the
  // SAME card as those events arrive, so a reader follows one strategy intuition → code → critique
  // → verdict rather than hunting across scattered log lines.
  function hypothesisCard(ev) {
    const d = ev.data || {};
    const ins = d.in_sample || {};
    const title = ev.message;
    const li = document.createElement('li');
    li.className = 'ln lane-action hx';
    const stat = (ins && ins.trades != null)
      ? `<span class="say-stat">On the history it searched: ${usd(ins.pnl, true)} ·\u00a0${ins.trades} trade${ins.trades === 1 ? '' : 's'}${glo('insample')}</span>` : '';
    const home = [mechHtml(d.mechanism), specHtml(d.spec),
      d.falsification ? `<p class="hx-fine"><b>Falsified if</b> ${esc(d.falsification)}</p>` : '',
      d.negative_control ? `<p class="hx-fine"><b>Placebo that should fail</b> ${esc(d.negative_control)}</p>` : ''].filter(Boolean).join('');
    li.innerHTML = `${logTime(ev.created_at)}<span class="node" aria-hidden="true"></span><div class="say">
      <div class="hx-head"><span class="say-kind">Hypothesis</span><b class="say-title">${esc(title)}</b><span class="hx-stamp pending" data-stamp>Testing<span class="working" aria-hidden="true"></span></span></div>
      ${d.thesis ? `<span class="say-sub">${esc(d.thesis)}</span>` : ''}${stat}
      ${home ? `<details class="hx-more"><summary>Show the homework</summary><div class="hx-body">${home}</div></details>` : ''}
      <div class="hx-review" data-review hidden></div></div>`;
    const stampEl = li.querySelector('[data-stamp]');
    const reviewEl = li.querySelector('[data-review]');
    const strip = (s, re) => (s || '').replace(re, '');
    return {
      li, title,
      challenger(e2) {
        const dec = (e2.data || {}).decision || 'review';
        const reason = strip(strip(e2.message, /^Challenger\s+\w+\s+[-–]\s*/i), new RegExp('^' + title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ':\\s*'));
        reviewEl.hidden = false;
        reviewEl.insertAdjacentHTML('beforeend', `<p class="hx-crit"><span class="hx-tag">Skeptic’s review ·\u00a0${esc(REVIEW_SAID[dec] || dec)}</span>${esc(reason)}</p>`);
      },
      verdict(e2) {
        const dd = e2.data || {};
        const cls = dd.status === 'passed' ? 'pass' : (dd.status === 'rejected' || dd.status === 'abandoned') ? 'rej' : 'void';
        const label = dd.status === 'passed' ? 'PASSED' : dd.status === 'rejected' ? 'REJECTED' : dd.status === 'abandoned' ? 'DROPPED' : 'VOID';
        li.classList.remove('lane-action'); li.classList.add('lane-' + cls);
        stampEl.className = 'hx-stamp ' + cls;
        // A PASSED hypothesis has a strategy page: link both its title and an explicit "View
        // strategy →" affordance in the verdict row. VOID/REJECTED have no page, so stay unlinked.
        const href = cls === 'pass' && dd.strategy_id ? `/strategies/${dd.strategy_id}` : '';
        stampEl.innerHTML = href ? `<a href="${href}">${label}</a>` : label;
        if (href) {
          const t = li.querySelector('.say-title');
          if (t) t.innerHTML = `<a class="hx-titlelink" href="${href}">${esc(title)}</a>`;
        }
        const rest = strip(e2.message, /^(PASSED|VOID|FAILED|REJECTED)(\s*\(challenger\))?\s*[-–]\s*/);
        const tail = rest.indexOf(':') >= 0 ? rest.slice(rest.indexOf(':') + 1).trim() : '';
        const why = whyFailedHtml(dd.why_failed);  // the gates it missed replace the gatekeeper's raw note
        // The server's plain sentence stands in for a message written for the ledger ("validation
        // verdict is gatekeeper-held (classification=...)"); a dropped idea says why it was dropped.
        const said = dd.note || (dd.status === 'abandoned' && dd.why) || tail;
        if (dd.strategy_id != null) li.dataset.sid = dd.strategy_id;  // "Ideas tested" jumps here
        reviewEl.hidden = false;
        reviewEl.insertAdjacentHTML('beforeend', `<div class="hx-verdict"><span class="hx-tag ${cls}">Verdict ·\u00a0${label.toLowerCase()}</span>${GLOSSARY[label.toLowerCase()] ? glo(label.toLowerCase()) : ''}${why ? why : said ? `<span class="hx-vtext">${esc(said)}</span>` : ''}${statGrid(dd.stats)}${href ? `<a class="hx-viewstrat" href="${href}">View strategy →</a>` : ''}</div>`);
      },
      // A passed idea's later checks (the one-time locked holdout, then whether it adds something new
      // to what the user runs) land on its own card; they were loose lines stamped VOID.
      stage(e2) { reviewEl.hidden = false; reviewEl.insertAdjacentHTML('beforeend', stageHtml(e2.data || {})); },
    };
  }
  // One later check of a passed idea in plain words: which check, whether it held, and why not.
  function stageHtml(dd) {
    const why = whyFailedHtml(dd.why_failed), ok = !why && !dd.skipped;
    const name = dd.phase === 'holdout' ? 'Locked holdout' : 'Adds something new';
    return `<div class="hx-verdict"><span class="hx-tag ${ok ? 'pass' : 'void'}">${name} ·\u00a0${ok ? 'held' : dd.skipped ? 'not run' : 'missed'}</span>${why || (dd.note ? `<span class="hx-vtext">${esc(dd.note)}</span>` : '')}</div>`;
  }

  // A live "thinking" card: the proposer's reasoning streams in as the agent writes it, with a
  // ticking elapsed clock and a caret, so the multi-minute generation call is visibly ALIVE rather
  // than a silent "Researching…". Once the prose turns into the JSON spec we stop echoing raw
  // tokens (the structured spec lands in each hypothesis card instead) and show a quiet "drafting".
  function thinkController(block, at) {
    const li = document.createElement('li');
    li.className = 'ln lane-think think';
    li.innerHTML = `${logTime(at)}<span class="node" aria-hidden="true"></span><div class="say">
      <div class="hx-head"><span class="say-kind">Thinking</span><span class="think-el" data-el>0s</span></div>
      <div class="think-body" data-body></div>
      <div class="think-draft" data-draft hidden>drafting the strategy spec<span class="ell" aria-hidden="true"></span></div>
      <span class="caret" data-caret aria-hidden="true"></span></div>`;
    const body = li.querySelector('[data-body]');
    const elEl = li.querySelector('[data-el]');
    const draft = li.querySelector('[data-draft]');
    const caret = li.querySelector('[data-caret]');
    let raw = '';
    const started = Date.now();
    const tick = setInterval(() => { elEl.textContent = Math.round((Date.now() - started) / 1000) + 's'; }, 1000);
    S.timers.push(tick);
    return {
      li, block,
      feed(text) {
        raw += text || '';
        // Stop echoing once the JSON spec begins — a ```fence (what we ask for), a line-led brace,
        // or a bare {" object start — the structured spec lands in the hypothesis cards instead.
        const cut = raw.search(/```|\n\s*\{|\{\s*"/);
        body.innerHTML = feedMd((cut >= 0 ? raw.slice(0, cut) : raw).trim());
        draft.hidden = cut < 0;
        caret.hidden = cut >= 0;
      },
      // A thought replayed from the log (opened after it was written) never ticked: it said "0s".
      seal() { clearInterval(tick); caret.remove(); draft.hidden = true; li.classList.add('sealed'); if (elEl.textContent === '0s') elEl.hidden = true; if (!raw.trim()) li.remove(); },
    };
  }
  // An idea still "Testing" when its session ended (failed, cancelled, out of credits) kept its
  // spinner for good, as if the stopped session were still on it. It gets no verdict now.
  function settlePending(log) {
    log.querySelectorAll('[data-stamp]').forEach((s) => {
      if (!s.classList.contains('pending')) return;
      s.className = 'hx-stamp void'; s.textContent = 'Not finished';
    });
  }

  // Controller over a .runfeed section: streams the thinking card, grafts challenger/verdict onto
  // their hypothesis card, appends everything else newest-at-bottom with an enter animation, sticks
  // to the latest only when already at the foot, raises a "jump to latest" chip when scrolled up,
  // and drives the live "researching… (Ns)" pulse so it never looks frozen between polls.
  // The second model that reads each idea before its test, by what it does (the verdicts already say
  // "The skeptic's review didn't pass it"), and its call in words, not the agent's codes.
  const REVIEW_SAID = { approve: 'approved', revise: 'asked for changes', reject: 'turned it down' };
  function runFeed(section) {
    const log = section.querySelector('.log');
    const jump = section.querySelector('.jumplatest');
    const pulse = section.querySelector('.runpulse');
    let unseen = 0, first = true, appended = 0, pulseSt = null, pulseKey = '', lastAt = Date.now(), queuedAt = null;
    const cards = new Map();   // hypothesis title -> card controller (most recent wins on a title clash)
    const settled = new Map(); // title -> card whose verdict is in: its holdout / diversification checks land on it
    let think = null;          // the currently-open thinking card, if any
    const atBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 60;
    const toLatest = () => { log.scrollTop = log.scrollHeight; unseen = 0; jump.hidden = true; };
    log.addEventListener('scroll', () => { if (atBottom()) { unseen = 0; jump.hidden = true; } });
    jump.onclick = toLatest;
    const sealThink = () => { if (think) { think.seal(); think = null; } };
    const add = (el) => { if (!first) el.classList.add('in'); log.appendChild(el); appended++; };
    // A long session's first paint keeps only its latest rows in the page and holds the rest behind
    // "Show N earlier entries" at the top: laying out and painting 600 events took a phone ~1.5s.
    // Held rows are built (a late verdict still lands on its card); they just wait outside the page.
    const KEEP_ROWS = 60;
    let earlier = null;
    function foldEarlier() {
      const rows = Array.from(log.children);
      if (rows.length <= KEEP_ROWS + 20) return;
      earlier = rows.slice(0, rows.length - KEEP_ROWS);
      earlier.forEach((el) => el.remove());
      const li = document.createElement('li');
      li.className = 'log-earlier';
      li.innerHTML = `<button type="button" class="btn small">Show ${num(earlier.length)} earlier entries</button>`;
      li.querySelector('button').onclick = () => showEarlier(true);
      log.insertBefore(li, log.firstChild);
    }
    // Puts the held rows back above what is on screen, which stays where it was.
    function showEarlier(focus) {
      if (!earlier) return;
      const rows = earlier, btn = log.querySelector('.log-earlier'), ref = btn ? btn.nextSibling : log.firstChild;
      earlier = null;
      const was = ref ? ref.offsetTop : 0, top = log.scrollTop;
      const frag = document.createDocumentFragment();
      rows.forEach((el) => frag.appendChild(el));
      log.insertBefore(frag, ref);
      if (btn) btn.remove();
      // Instantly, not with the log's smooth scrolling, and the same whether or not the browser
      // anchored the scroll itself.
      log.style.scrollBehavior = 'auto';
      log.scrollTop = top + ((ref ? ref.offsetTop : 0) - was);
      log.style.scrollBehavior = '';
      // Focus goes to the newest revealed entry (the button it pressed is gone), just above the view.
      const last = rows[rows.length - 1];
      if (focus && last && last.focus) { last.setAttribute('tabindex', '-1'); last.focus({ preventScroll: true }); }
    }

    function dispatch(ev) {
      lastAt = Date.now();
      if (ev.kind === 'thinking') {
        const block = (ev.data || {}).block || 0;
        if (think && think.block !== block) sealThink();
        if ((ev.data || {}).end) { sealThink(); return; }
        if (!think) { think = thinkController(block, ev.created_at); add(think.li); }
        think.feed(ev.message);
        return;
      }
      sealThink();  // any structured event ends the current train of thought
      if (ev.kind === 'hypothesis') {
        const card = hypothesisCard(ev); cards.set(card.title, card); add(card.li);
      } else if (ev.kind === 'challenger') {
        const card = cards.get((ev.data || {}).title); card ? card.challenger(ev) : add(runEventEl(ev));
      } else if (ev.kind === 'verdict') {
        const card = cards.get((ev.data || {}).title);
        const later = /^(holdout|forward)$/.test((ev.data || {}).phase || '') && settled.get((ev.data || {}).title);
        if (later) later.stage(ev);
        else if (card) { card.verdict(ev); cards.delete(card.title); settled.set(card.title, card); } else add(runEventEl(ev));
      } else {
        add(runEventEl(ev));
      }
    }

    // Count up the seconds since the last event every second (independent of the 2s poll) so a
    // long call that isn't streaming still reads as working, not stuck.
    const ptick = setInterval(() => {
      if (pulse.hidden || pulseSt === 'paused' || pulseSt === 'done' || pulse.classList.contains('late')) return;
      const secs = Math.round((Date.now() - (pulseSt === 'queued' && queuedAt != null ? queuedAt : lastAt)) / 1000);
      const lab = pulse.querySelector('[data-plabel]');
      if (lab && secs >= 3) lab.textContent = `${pulseSt === 'queued' ? 'Queued' : 'Researching'} ·\u00a0${secs}s`;
    }, 1000);
    S.timers.push(ptick);

    return {
      reveal: () => showEarlier(false),  // a jump to an older card shows the held rows first
      push(events) {
        if (!events || !events.length) return;
        const ph = log.querySelector('.log-empty'); if (ph) ph.remove();
        const stick = first || atBottom();
        appended = 0;
        events.forEach((ev) => { try { dispatch(ev); } catch (e) { /* one bad event must not break the feed */ } });
        if (first) foldEarlier();
        if (stick) toLatest();
        else if (appended) { unseen += appended; jump.hidden = false; jump.textContent = unseen + ' new ↓'; }
        first = false;
      },
      state(st, wait) {  // 'queued' | 'running' | 'paused' | 'done'; wait = the server's run.wait
        if (st === 'done') { pulseSt = st; sealThink(); settlePending(log); pulse.hidden = true; return; }
        const stick = atBottom();
        pulse.hidden = false;
        // Count the queue from the server's clock: "Queued · 19s" restarted on every reload.
        queuedAt = st === 'queued' && wait && wait.state === 'queued' ? Date.now() - wait.seconds * 1000 : null;
        // An overdue run's sentence ("No word from the agent for 25 min. …") is said once, in the loop panel
        // above, as on Meridian: it sat there and again here. The log's foot says the state in the badge's words.
        const late = st !== 'paused' && wait && wait.overdue ? (wait.state === 'queued' ? 'Waiting ' : 'Silent ') + waitSpan(wait.seconds) : '';
        if (st + late !== pulseKey) {
          pulseKey = st + late;
          pulse.className = 'runpulse' + (st === 'paused' ? ' paused' : late ? ' late' : '');
          pulse.innerHTML = st === 'paused'
            ? '<span class="pulse-bar" aria-hidden="true"></span><span>Paused — resume and it picks up exactly where it left off.</span>'
            : late ? `<span class="apf-idle-dot" aria-hidden="true"></span><span>${esc(late)}</span>`
            : st === 'queued'
              ? '<span class="working" aria-hidden="true"></span><span data-plabel>Queued — waiting for a free agent to pick this up…</span>'
              : '<span class="working" aria-hidden="true"></span><span data-plabel>Researching<span class="ell" aria-hidden="true"></span></span>';
        }
        pulseSt = st;
        if (stick) toLatest();
      },
    };
  }

  // Build one feed node (<li>) for the kinds that are NOT a hypothesis card or a streaming thought:
  // steps, the RSI/dreaming notes, pause/resume, errors, and the fallback standalone verdict.
  function runEventEl(ev) {
    const li = document.createElement('li');
    const data = ev.data || {};
    let lane = RUN_LANE[ev.kind] || 'thought';
    let inner;
    if (ev.kind === 'verdict' && !data.title) {
      inner = esc(data.note || ev.message);  // a note on the session (the data scan, the model tiering), not an idea's verdict
      lane = 'thought';
    } else if (ev.kind === 'verdict' && /^(holdout|forward)$/.test(data.phase || '')) {
      lane = (data.why_failed && data.why_failed.length) || data.skipped ? 'void' : 'pass';
      inner = `<b>${esc(data.title)}</b>${stageHtml(data)}`;
    } else if (ev.kind === 'verdict') {
      const st = data.status, sid = data.strategy_id;
      lane = st === 'passed' ? 'pass' : (st === 'rejected' || st === 'abandoned') ? 'rej' : 'void';
      const tag = st === 'passed' ? '<b class="verdict pass">PASSED</b>'
        : st === 'rejected' ? '<b class="verdict rej">REJECTED</b>'
        : st === 'abandoned' ? '<b class="verdict rej">DROPPED</b>'
        : '<b class="verdict void">VOID</b>';
      const rest = ev.message.replace(/^(PASSED|VOID|FAILED|REJECTED|NOT TESTED)(\s*\(challenger\))?\s*[-–]\s*/, '');
      const title = data.title || rest;
      const tail = data.note ? ': ' + data.note : st === 'abandoned' && data.why ? ' — ' + data.why
        : rest.startsWith(title) ? rest.slice(title.length) : '';  // keep the ": …" explanation as text
      const titleHtml = sid ? `<a href="/strategies/${sid}">${esc(title)}</a>` : `<b>${esc(title)}</b>`;
      const why = whyFailedHtml(data.why_failed);
      inner = `${tag} ${titleHtml}${why ? '' : esc(tail)}${why}`;
    } else if (ev.kind === 'challenger') {
      inner = `<span class="say-kind">Skeptic’s review</span>${esc(ev.message.replace(/^Challenger\s+/, ''))}`;
    } else if (/^(Dreaming:|Research policy evolved:)/.test(ev.message)) {
      lane = 'rsi';
      inner = `<b class="rsi-badge">RSI</b> ${esc(plainDream(ev.message))}`;
    } else if (ev.kind === 'paused' || ev.kind === 'resumed') {
      inner = `<span class="say-kind">${ev.kind === 'paused' ? 'Paused' : 'Resumed'}</span>${esc(ev.message)}`;
    } else {
      // The server's plain sentence for a step written in the ledger's terms ("Froze 2 finalists; ...
      // validation budget"), else the step itself: inline markdown (bold/code/italic/links), escaped.
      inner = (ev.kind === 'step' || ev.kind === 'done') && data.note ? esc(data.note) : mdLite(ev.message);
    }
    li.className = 'ln lane-' + lane + (lane === 'rsi' ? ' rsi-event' : '');
    li.innerHTML = `${logTime(ev.created_at)}<span class="node" aria-hidden="true"></span><div class="say">${inner}</div>`;
    return li;
  }

  // ======================================================================
  // RSI loop observatory — the self-improving cycle, made legible and alive.
  // A station-line of the four stages (explore → backtest → gate → dream,
  // looping back), a current-phase + liveness readout driven off the NEWEST
  // event's own timestamp (so "active Ns ago" is honest and flips to a quiet
  // state on its own between polls), and — when the stream carries a
  // parent→child hypothesis lineage — a discovery tree that grows as children
  // branch from winners. Tolerant of unknown event kinds: a kind it doesn't
  // know keeps the last stage lit and shows a humanised label, so the new
  // backend phase events never break it; it just gets richer as they land.
  // ======================================================================
  const RSI_STAGES = [['explore', 'Explore'], ['backtest', 'Backtest'], ['gate', 'Check'], ['dream', 'Improve']];
  // event kind -> [loop stage, human phase label]. New kinds the backend adds just fall through.
  const RSI_PHASE = {
    'run-start': ['explore', 'Starting up'], 'data-loaded': ['explore', 'Data loaded'],
    'proposing': ['explore', 'Proposing hypotheses'], 'developing-thesis': ['explore', 'Developing a thesis'],
    'thinking': ['explore', 'Thinking it through'], 'step': ['explore', 'Working'],
    'hypothesis': ['backtest', 'Backtesting a hypothesis'], 'challenger': ['backtest', 'Challenging the result'],
    'gating': ['gate', 'Gating on unseen data'], 'verdict': ['gate', 'Verdict in, on to the next step'],
    'dreaming': ['dream', 'Tuning how it searches'],
  };
  // The phase line read "Recording the verdict" for as long as the agent then worked without a line (nine
  // minutes into the next idea's backtest), and kept it through a resume or the session's last line.
  // A verdict is done when it is logged, so the line says the agent moved on; a verdict with no idea
  // (the data scan, the model tiering) is a note on the session, read as a step; and these say where it is.
  const RSI_SAID = { paused: 'Paused', resumed: 'Back at work', done: 'Wrapping up' };
  const SX = { explore: 80, backtest: 240, gate: 400, dream: 560 };  // viewBox-x of each station (= flex-cell centres: 12.5/37.5/62.5/87.5% of 640)
  // The engine's own words for its self-tuning step ("Dreaming:", "Research policy evolved:"), said plainly.
  const plainDream = (m) => String(m || '').replace(/^Dreaming:/, 'Tuning how it searches:').replace(/^Research policy evolved:/, 'Search improved:');
  const prettyKind = (k) => String(k || '').replace(/[-_]/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  // Liberal id/parent extraction so the tree survives whatever the backend names its lineage fields.
  const hypId = (d) => d.hyp_id != null ? d.hyp_id : d.id != null ? d.id : d.node_id != null ? d.node_id : null;
  const hypParent = (d) => d.parent_id != null ? d.parent_id : d.parent != null ? d.parent : d.parent_hyp_id != null ? d.parent_hyp_id : d.parent_title != null ? d.parent_title : null;

  function rsiObservatory(host) {
    const station = ([s]) => `<g class="rsi-st" data-stage="${s}"><circle class="rsi-ring" cx="${SX[s]}" cy="50" r="17"></circle><circle class="rsi-dot" cx="${SX[s]}" cy="50" r="7.5"></circle></g>`;
    const link = (a, b, into) => `<line class="rsi-link" data-into="${into}" x1="${SX[a] + 18}" y1="50" x2="${SX[b] - 18}" y2="50"></line>`;
    host.innerHTML = `
      <div class="rsiobs-head"><h2>The research loop</h2>
        <span class="rsiobs-live is-wait" data-live><span class="rsiobs-pdot"></span><span data-livetext>Spinning up…</span></span></div>
      <div class="rsiobs-loop">
        <svg class="rsi-rail" viewBox="0 0 640 72" role="img" aria-label="The research loop: explore, backtest, check, improve — and back again.">
          <path class="rsi-arc" data-into="explore" d="M560 42 C 560 6, 80 6, 80 42"></path>
          ${link('explore', 'backtest', 'backtest')}${link('backtest', 'gate', 'gate')}${link('gate', 'dream', 'dream')}
          ${RSI_STAGES.map(station).join('')}</svg>
        <div class="rsi-labels">${RSI_STAGES.map(([s, l]) => `<span class="rsi-lab" data-stage="${s}">${l}</span>`).join('')}</div></div>
      <p class="rsiobs-phase" data-phase>Waiting for the agent to start.</p>
      <p class="rsiobs-phase rsiobs-wait" data-wait hidden></p>
      <figure class="rsiobs-tree" data-tree hidden><figcaption>Discovery tree <span>how each winner seeded the next</span></figcaption>
        <div class="rsiobs-treewrap"><svg class="rsiobs-treesvg" data-treesvg></svg></div></figure>`;

    const liveWrap = host.querySelector('[data-live]'), liveText = host.querySelector('[data-livetext]');
    const phaseEl = host.querySelector('[data-phase]'), treeFig = host.querySelector('[data-tree]'), treeSvg = host.querySelector('[data-treesvg]');
    const groups = {}, labs = {};
    RSI_STAGES.forEach(([s]) => { groups[s] = host.querySelector(`.rsi-st[data-stage="${s}"]`); labs[s] = host.querySelector(`.rsi-lab[data-stage="${s}"]`); });
    const links = host.querySelectorAll('.rsi-link, .rsi-arc');
    const fired = new Set();
    let stage = null, lastAt = Date.now(), runState = 'queued', wait = null, waitAt = 0;
    const waitEl = host.querySelector('[data-wait]');
    let waitHidPhase = false;
    let doneRun = null;
    const waitNow = () => (wait ? { ...wait, seconds: wait.seconds + Math.round((Date.now() - waitAt) / 1000) } : null);
    const nodes = [], byId = new Map(), byTitle = new Map(); let hasLineage = false, lastCount = -1;

    function paintStages() {
      const live = runState === 'running';
      RSI_STAGES.forEach(([s]) => {
        const on = live && s === stage, done = !on && fired.has(s);
        groups[s].classList.toggle('is-active', on); groups[s].classList.toggle('is-done', done);
        labs[s].classList.toggle('is-active', on); labs[s].classList.toggle('is-done', done);
      });
      links.forEach((l) => l.classList.toggle('is-flow', live && l.getAttribute('data-into') === stage));
    }

    function paintLive() {
      host.classList.remove('is-quiet');
      const w = ['queued', 'running'].includes(runState) ? waitNow() : null, late = !!(w && w.overdue);
      waitEl.hidden = !late;
      if (late) waitEl.textContent = runWaitLine(w);
      // An overdue run's wait line takes the phase line's place: a queued one's says what "Waiting for the
      // agent to start." said, and more; a silent one's last phase ("Working") sat over "No word from the agent".
      if (late) { phaseEl.hidden = true; waitHidPhase = true; }
      else if (waitHidPhase) { waitHidPhase = false; phaseEl.hidden = !['queued', 'running', 'paused'].includes(runState); }
      if (late && runState === 'queued') { liveWrap.className = 'rsiobs-live is-stall'; liveText.textContent = 'Waiting ' + waitSpan(w.seconds); return; }
      if (late) { host.classList.add('is-quiet'); liveWrap.className = 'rsiobs-live is-stall'; liveText.textContent = 'Silent ' + waitSpan(w.seconds); return; }
      if (runState === 'paused') { liveWrap.className = 'rsiobs-live is-paused'; liveText.textContent = 'Paused'; return; }
      if (runState === 'queued') { liveWrap.className = 'rsiobs-live is-wait'; liveText.textContent = 'Queued'; return; }
      if (runState !== 'running') { liveWrap.className = 'rsiobs-live is-done'; liveText.textContent = doneRun ? runDoneText(doneRun) : runState === 'succeeded' ? 'Finished' : runState === 'cancelled' ? 'Stopped by you' : 'Stopped'; return; }
      const secs = Math.max(0, Math.round((Date.now() - lastAt) / 1000)), stalled = secs >= 75;
      host.classList.toggle('is-quiet', stalled);
      liveWrap.className = 'rsiobs-live' + (stalled ? ' is-stall' : '');
      // A backtest or a long model call can go minutes without a line while the server still hears from the
      // worker (a silent one is caught above, from the server's own clock). Raw seconds read "quiet 13246s —
      // likely a long model call" three hours on; the age reads in minutes and hours, as on Meridian.
      const age = secs < 60 ? `${secs}s` : secs < 3600 ? `${Math.floor(secs / 60)} min` : `${Math.floor(secs / 3600)} hr`;
      liveText.textContent = secs < 6 ? 'live' : stalled ? `Last step ${age} ago ·\u00a0still working` : `active ${age} ago`;
    }
    // 1s ticker keeps "Ns ago" honest between the 2s polls and flips to the quiet state on its own.
    S.timers.push(setInterval(paintLive, 1000));

    // ponytail: naive tidy-tree relayout on every change — O(n), fine for the tens of hypotheses a run makes.
    function tree() {
      if (!hasLineage || nodes.length === lastCount) return;
      lastCount = nodes.length; treeFig.hidden = false;
      const kids = new Map();
      nodes.forEach((n) => { const p = (n.parent != null && byId.has(n.parent)) ? n.parent : null; n._p = p; if (p != null) (kids.get(p) || kids.set(p, []).get(p)).push(n); });
      let slot = 0, maxD = 0;
      const place = (n) => { const ch = kids.get(n.id) || []; maxD = Math.max(maxD, n.depth); if (!ch.length) { n._x = slot++; } else { ch.forEach(place); n._x = (ch[0]._x + ch[ch.length - 1]._x) / 2; } };
      nodes.filter((n) => n._p == null).forEach(place);
      const COL = 52, ROW = 54, PX = 24, PY = 22;
      const x = (n) => PX + n._x * COL, y = (n) => PY + n.depth * ROW;
      const w = Math.max((slot - 1) * COL + PX * 2, 140), h = Math.max(PY * 2 + maxD * ROW, 64);
      treeSvg.setAttribute('viewBox', `0 0 ${w} ${h}`); treeSvg.style.width = w + 'px'; treeSvg.style.height = h + 'px';
      let edges = '', dots = '';
      nodes.forEach((n) => {
        if (n._p != null) { const p = byId.get(n._p); edges += `<path class="rsi-tedge" d="M${x(p)} ${y(p) + 9} C ${x(p)} ${y(p) + ROW / 2}, ${x(n)} ${y(n) - ROW / 2}, ${x(n)} ${y(n) - 9}"></path>`; }
        dots += `<g class="rsi-tnode is-${n.status || 'pending'}${n._new ? ' pop' : ''}"><circle cx="${x(n)}" cy="${y(n)}" r="8"></circle><title>${esc(n.title)}${n.status ? ' — ' + n.status : ''}</title></g>`;
        n._new = false;
      });
      treeSvg.innerHTML = edges + dots;
    }

    return {
      push(events, state, run) {
        wait = (run && run.wait) || null; waitAt = Date.now();
        doneRun = run || doneRun;  // the badge of a finished run says why it stopped, as the Status figure does
        runState = state || runState;
        (events || []).forEach((ev) => {
          const d = ev.data || {};
          lastAt = Date.parse(ev.created_at) || Date.now();   // newest event's own clock drives liveness
          const kind = ev.kind === 'verdict' && !d.title ? 'step' : ev.kind;
          let ph = RSI_PHASE[kind];
          if (!ph && /^(Dreaming:|Research policy evolved:)/.test(ev.message || '')) ph = ['dream', plainDream(ev.message).split(':')[0]];
          if (ph) { stage = ph[0]; fired.add(stage); phaseEl.textContent = ph[1]; }
          else if (kind) phaseEl.textContent = RSI_SAID[kind] || prettyKind(kind);  // unknown kind: keep stage lit, show a readable label
          if (ev.kind === 'hypothesis') {
            const id = hypId(d), key = id != null ? id : ev.message;
            if (!byId.has(key)) { const n = { id: key, parent: hypParent(d), title: ev.message, depth: 0, status: null, _new: true }; nodes.push(n); byId.set(key, n); byTitle.set(ev.message, n); }
            const n = byId.get(key);
            if (n.parent != null) {
              if (!byId.has(n.parent) && byTitle.has(n.parent)) n.parent = byTitle.get(n.parent).id;  // parent given by title → resolve to its id
              const par = byId.get(n.parent);
              if (par) { n.depth = par.depth + 1; hasLineage = true; }
            }
          } else if (ev.kind === 'verdict') {
            const id = hypId(d), n = (id != null && byId.get(id)) || (d.title && byTitle.get(d.title)) || null;
            if (n) n.status = d.status === 'passed' ? 'pass' : d.status === 'rejected' ? 'rej' : 'void';
          }
        });
        // A finished run's last phase ("Recording the verdict") read as still working; the live
        // badge already says Finished / Cancelled / Stopped, as on Meridian.
        phaseEl.hidden = !['queued', 'running', 'paused'].includes(runState);
        paintStages(); paintLive(); tree();
      },
    };
  }

  // Interrupt & continue: the obvious control cluster for a research run. Running → Pause;
  // Paused → Resume (the primary action); every active state can Cancel. Finished shows the
  // way onward. Pause/Resume are reversible so they act immediately; Cancel is armed to confirm.
  // The run page polls every 2s and called this each time: the repaint undid an armed "Confirm cancel"
  // before the second press could land, and re-enabled a Pause still in flight (a second POST, then a
  // "Only a running session can be paused" error). The buttons repaint only when the status changes.
  const CANCEL_BTN = '<button class="btn danger small" id="cancel" title="Ends the session for good. What it has spent stays charged; ideas it already tested are kept.">Cancel</button>';
  function runControls(host, id, status, reload) {
    if (host.dataset.st === status) return;
    host.dataset.st = status;
    if (status === 'paused') {
      host.innerHTML = '<span class="runact"><button class="btn small primary" id="resume">Resume</button>' + CANCEL_BTN + '</span>';
      host.querySelector('#resume').onclick = (e) => busy(e.currentTarget, async () => { await api(`/api/runs/${id}/resume`, {}).catch((er) => alert0(er.message)); await reload(); });
    } else if (status === 'running') {
      host.innerHTML = '<span class="runact"><button class="btn small" id="pause" title="Holds the session where it is until you resume it.">Pause</button>' + CANCEL_BTN + '</span>';
      host.querySelector('#pause').onclick = (e) => busy(e.currentTarget, async () => { await api(`/api/runs/${id}/pause`, {}).catch((er) => alert0(er.message)); await reload(); });
    } else if (status === 'queued') {
      host.innerHTML = '<span class="runact">' + CANCEL_BTN + '</span>';
    } else {
      host.innerHTML = status === 'succeeded' ? '<a class="btn small" href="/strategies">All strategies</a>' : '';
      return;
    }
    const cancel = host.querySelector('#cancel');
    cancel.onclick = () => armed(cancel, 'Confirm cancel', () => busy(cancel, async () => { await api(`/api/runs/${id}/cancel`, {}).catch((er) => alert0(er.message)); await reload(); }));
  }

  // A session's time at work. The agent logs "paused" when it stops at a checkpoint and "resumed" when it
  // goes on (agent.run_research); "Time" counted the wall clock from the start, so a paused session's
  // figure kept climbing while it waited on Resume. The pauses are left out, and a paused session's clock
  // stops where it paused (at its last line, before the worker has logged the pause).
  // pz carries { ms: closed pauses, since: an open pause's start, last: the newest line } across polls.
  function runPauses(pz, ev) {
    const t = Date.parse(ev.created_at);
    if (!t) return;
    if (ev.kind === 'paused' && pz.since == null) pz.since = t;
    else if (ev.kind === 'resumed' && pz.since != null) { pz.ms += Math.max(0, t - pz.since); pz.since = null; }
    pz.last = t;
  }
  function runWorked(r, pz, now = Date.now()) {
    const started = r.started_at ? Date.parse(r.started_at) : null;
    if (!started) return null;
    const end = r.finished_at ? Date.parse(r.finished_at) : r.status === 'paused' ? (pz.since != null ? pz.since : pz.last || now) : now;
    const open = pz.since != null && end > pz.since ? end - pz.since : 0;
    return Math.max(0, (end - started - pz.ms - open) / 1000);
  }
  // A run-until-stopped session that used up the credits ends as a finished one (agent.run_research
  // logs this step, then wraps up): the page said "Done" and "Try another idea", and the reason sat
  // in the log. The step's own words mark it, so sessions that ended this way before say so too.
  const runOutOfCredits = (ev) => !!ev && ev.kind === 'step' && /^Paused — out of credits\b/.test(ev.message || '');
  // How far along and what it found, live. The run's own counters move once per round of ideas (a
  // run-until-stopped round is several ideas), so a running session read "3 hypotheses" while its
  // log showed nine, and "Passed …" beside a passed idea listed under it. Its log and its strategy
  // rows are current; a set-size session also says how many it will test.
  function runCountFigs(r, active, tried, strategies) {
    const n = Math.max(+r.hypotheses_tried || 0, tried || 0);
    const cap = active && !r.run_forever && +r.max_hypotheses ? `of up to ${num(r.max_hypotheses)}` : '';
    const passed = active ? (strategies || []).filter((s) => s.status === 'passed').length : r.strategies_passed;
    return fig('Tested', n, { small: cap }) + fig('Passed', passed == null ? '—' : passed);
  }
  // A finished session's status, in the research list's words (RUN_STOP, from the server's stop_reason):
  // the list said "Finished" or "Stopped by you" and this page "Done" or "Cancelled" for the same session,
  // and an interrupted one read only "Stopped". A run-until-stopped session that used up the credits is
  // read from its log (runOutOfCredits), since the run page's server answer can't tell.
  const RUN_DONE = { interrupted: 'Interrupted', no_data: 'Nothing to research' };
  const runDoneText = (r) => r.out_of_credits ? 'Out of credits' : RUN_STOP[r.stop_reason] || RUN_DONE[r.stop_reason]
    || (r.status === 'succeeded' ? 'Finished' : r.status === 'stopped' ? 'Stopped' : r.status === 'cancelled' ? 'Stopped by you' : 'Stopped on an error');
  // A session that ended with no strategy to list says why it stopped (the server's stop_reason,
  // services.run_stop): "Each strategy below says which check it missed" sat over an empty list.
  const RUN_EMPTY = {
    interrupted: 'It was interrupted before any strategy reached the checks, and it couldn’t be resumed.',
    no_data: 'This market has nothing to research yet, so the session stopped before testing anything.',
    complete: 'It ran out of new ideas to try before any strategy reached the checks.',
    limit: 'No strategy from this session reached the checks, so there are none to list.',
  };
  const runEmpty = (r) => (r.stop_reason === 'no_data' && r.error ? esc(r.error) : RUN_EMPTY[r.stop_reason] || 'This session ended before any strategy reached the checks.');
  // What to do once a session ends. The example's log ended on "now describe a real idea" with no way
  // to do it, and a session that passed something left it two screens down on a phone, under the log.
  function runNext(r, strategies) {
    if (r.example) return `<p class="run-next">That’s what a session looks like. <a class="btn primary" href="/research?new=1">Describe your own idea</a></p>`;
    const passed = (strategies || []).filter((s) => s.status === 'passed');
    const credits = r.out_of_credits ? 'It stopped when your credits ran out. <a href="/billing">Add credits</a>, then start a new session to keep researching. ' : '';
    if (passed.length) {
      const links = passed.slice(0, 3).map((s) => `<a href="/strategies/${s.id}">${esc(s.title)}</a>`).join(', ');
      const more = passed.length > 3 ? ` and <a href="/strategies?status=passed">${passed.length - 3} more</a>` : '';
      // The autopilot deploys what it finds on paper itself, and its finished session still said "Open it
      // to deploy it on paper": the strategy page then warned that a second copy doubles the positions.
      const deployed = passed.filter((s) => s.deployed).length;
      const way = deployed === passed.length ? ` ${passed.length === 1 ? 'It is' : 'They are'} already deployed. <a href="/deploy">See ${passed.length === 1 ? 'it' : 'them'} on Deploy</a>.`
        : deployed ? ` ${num(deployed)} ${deployed === 1 ? 'is' : 'are'} already deployed; open another to deploy it on paper.`
        : ` Open ${passed.length === 1 ? 'it' : 'one'} to deploy it on paper.`;
      return `<p class="run-next">${credits}${passed.length === 1 ? 'Passed' : passed.length + ' passed'}: ${links}${more}.${way}</p>`;
    }
    // A failed or cancelled session said nothing: the reason sat in a folded log, the way on nowhere.
    // The server's reason is written for the customer; one that already says the session stopped
    // stands alone ("…stopped on an error. …so the session stopped.").
    if (r.status === 'failed') return `<p class="run-next">${r.error && /\bstopped\b/.test(r.error) ? esc(r.error) : `This session stopped on an error.${r.error ? ' ' + esc(r.error) : ''}`} <a href="/research?new=1">Start a new session</a></p>`;
    if (r.status === 'cancelled') return `<p class="run-next">This session was cancelled before it finished.${(strategies || []).length ? ' The ideas it tested are listed below.' : ''} <a href="/research?new=1">Try another idea</a></p>`;
    const none = !(strategies || []).length;
    if (credits) return `<p class="run-next">${credits}${none ? 'No strategy reached the checks before then.' : 'Nothing passed before then; each idea below says which check it missed.'}</p>`;
    if (none && (r.status === 'succeeded' || r.status === 'stopped')) return `<p class="run-next">${runEmpty(r)} <a href="/research?new=1">Try another idea</a></p>`;
    if (r.status === 'succeeded' || r.status === 'stopped') return `<p class="run-next">Nothing passed this time. Most ideas don’t. Each idea below says which check it missed; tap one for what to try next. <a href="/research?new=1">Try another idea</a></p>`;
    return '';
  }
  // The foot of a finished session, under the log's last line. The way on sat only above the log, a
  // phone's length of scrolling back up: the example's last line said to describe a real idea, and a
  // session where nothing passed ended on its last missed idea. Plain buttons: the line above keeps
  // the page's one primary action. One that ran out of credits ends on adding them (autopilot would
  // wait on credits too).
  function runEnd(r, strategies) {
    if (r.example) return `<p class="run-end"><a class="btn" href="/research?new=1">Describe your own idea</a></p>`;
    if (r.status !== 'succeeded' && r.status !== 'stopped') return '';
    if (r.out_of_credits) return '<div class="run-end"><a class="btn" href="/billing">Add credits</a></div>';
    if ((strategies || []).some((s) => s.status === 'passed')) return '';
    return `<div class="run-end"><a class="btn" href="/research?new=1">Try another idea</a>${apNudge('Rather not write ideas yourself?', 'and it picks ideas and researches them on its own, on paper.')}</div>`;
  }
  // What the session tried, one row per idea: its outcome and, for a miss, the first check it missed
  // in plain words. Each idea's outcome sat only in the log, a scroll box that held 200+ lines on a
  // long session; a title jumps to its card there. Passed ideas lead; past six, the rest fold.
  const IDEA_STAMP = { passed: ['pass', 'Passed'], failed: ['void', 'Void'], rejected: ['rej', 'Rejected'], 'backtest-only': ['rej', 'Backtest only'] };
  // An idea the agent dropped while building it never becomes a strategy, and one still being tested has
  // none yet: the Tested figure counted them and this list didn't ("Tested 5" over "4"), so the gap is said.
  const ideasGap = (n, listed, active) => n > listed ? ` ·\u00a0${num(n - listed)} more ${active ? 'still being tested' : 'dropped before testing'}` : '';
  function runIdeas(strategies, whyBySid, open, gap = '') {
    const list = (strategies || []).slice().sort((a, b) => (b.status === 'passed') - (a.status === 'passed'));
    if (!list.length) return '';
    const row = (s) => {
      const [cls, label] = IDEA_STAMP[s.status] || ['', 'Testing'];
      const why = whyBySid.get(s.id) || [];
      const said = s.status === 'passed' ? (s.deployed ? '<a href="/deploy">Already deployed: see it on Deploy</a>'
        : `<a href="/strategies/${s.id}">Open it to deploy on paper</a>`)
        : why.length ? `${esc(why[0].label)}${why.length > 1 ? ` ·\u00a0${why.length - 1} more check${why.length > 2 ? 's' : ''}` : ''}` : '';
      return `<li><span class="hx-stamp ${cls}">${label}</span><button type="button" class="ri-title" data-goto="${s.id}">${esc(s.title)}</button>${said ? `<span class="ri-why">${said}</span>` : ''}</li>`;
    };
    const SHOW = 6;
    return `<section class="run-ideas"><div class="section-head"><h2>Ideas tested</h2><p>${list.length}${gap} ·\u00a0tap one for its story</p></div>
      <ol class="ri-list">${list.slice(0, SHOW).map(row).join('')}</ol>${list.length > SHOW
        ? `<details class="ri-rest"${open ? ' open' : ''}><summary>Show all ${list.length}</summary><ol class="ri-list">${list.slice(SHOW).map(row).join('')}</ol></details>` : ''}</section>`;
  }
  async function viewRun(id) {
    // Pause and Cancel (and their error notice) sit beside the title, as on Meridian: at the Agent log
    // heading they were a screen below the spend figure on a phone.
    shell('/research', '<div class="run-header"><div id="runboard">' + boardTitle('Research run') + '</div><span id="runact"></span></div><div id="flash"></div><dl class="figures measure run-figs" id="runfigs" style="margin-top:14px"></dl><div id="runnext"></div><div id="runideas"></div><p class="stale-note" id="run-stale" role="status"></p>', `
      <div id="rsibox"></div>
      <div id="rsiobs" class="rsiobs"></div>
      <section><div class="section-head"><h2>Agent log</h2></div>
        <p class="hint" style="margin:2px 0 10px">Watch the agent reason in real time — each hypothesis, backtest and verdict as it happens. Every strategy links to its full result once its outcome is in; see them all on the <a href="/strategies">Strategies</a> page.${tzName() ? ` Times are ${esc(tzName())}.` : ''}</p>
        <div class="runfeed" id="runfeed"><ol class="log stream" id="log" role="log" aria-label="Agent reasoning log"><li class="log-empty" data-empty>Waiting for the first event — the agent is spinning up. The loop above shows the phase it's in.</li></ol><button class="jumplatest" id="jumplatest" type="button" hidden>new ↓</button><div class="runpulse" id="runpulse" aria-live="polite" hidden></div></div><div id="runend"></div></section>`);
    let after = 0, tried = 0, outOfCredits = false;
    const pauses = { ms: 0, since: null, last: null };
    const whyBySid = new Map();  // strategy id -> the checks its verdict missed, kept across polls
    const ideasEl = root.querySelector('#runideas');
    ideasEl.addEventListener('click', (e) => {
      const b = e.target.closest('[data-goto]');
      if (!b) return;
      const find = () => root.querySelector(`#log li[data-sid="${b.dataset.goto}"]`);
      let card = find();
      if (!card) { stream.reveal(); card = find(); }  // its card may be among the held earlier rows
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' }); else go('/strategies/' + b.dataset.goto);
    });
    const stream = runFeed(root.querySelector('#runfeed'));
    const obs = rsiObservatory(root.querySelector('#rsiobs'));
    const load = async (cfg) => {
      const d = await api(`/api/runs/${id}?after=${after}`, undefined, cfg);
      const r = d.run;
      const active = r.status === 'running' || r.status === 'queued' || r.status === 'paused';
      d.events.forEach((ev) => {
        after = Math.max(after, ev.id); if (ev.kind === 'hypothesis') tried++;
        runPauses(pauses, ev);
        if (runOutOfCredits(ev)) outOfCredits = true;
        const dd = ev.data || {};
        if (ev.kind === 'verdict' && dd.strategy_id != null && Array.isArray(dd.why_failed) && dd.why_failed.length) whyBySid.set(dd.strategy_id, dd.why_failed);
      });
      r.out_of_credits = outOfCredits && !active;
      // The 2s poll repaints only what changed: rewriting the same title and figures each time made
      // the phone lay the page out again (and the autopilot pill re-check what it covers).
      paint(root.querySelector('#runboard'), boardTitle(sessionTitle(r), `${esc(marketShort(r.market))} \u00b7\u00a0${runKind(r)}${r.example ? ' \u00b7\u00a0' + EXAMPLE_NOTE : runSetup(r) ? ' \u00b7\u00a0' + runSetup(r) : ''}`));
      const worked = runWorked(r, pauses);
      const late = r.wait && r.wait.overdue ? r.wait : null;
      const statusText = late ? (late.state === 'queued' ? 'Waiting ' : 'Silent ') + waitSpan(late.seconds)
        : r.status === 'queued' ? 'Waiting<span class="working" aria-label="in process"></span>'
        : r.status === 'paused' ? 'Paused'
        : r.status === 'running' ? 'Researching<span class="working" aria-label="in process"></span>'
        : runDoneText(r);
      paint(root.querySelector('#runfigs'),
        fig('Status', statusText) +
        fig('Time', worked == null ? '—' : waitSpan(worked), { small: pauses.ms || pauses.since != null ? 'not counting time paused' : '' }) +
        (r.spent_usd != null ? fig(active ? 'Spent so far' : 'Cost', usd(r.spent_usd), { small: r.example ? 'free: Tau ran it for you' : 'from your credits' }) : '') +
        runCountFigs(r, active, tried, d.strategies));
      const next = root.querySelector('#runnext');
      paint(next, active ? '' : runNext(r, d.strategies));
      // Painted only when it changes: a finished run still polls, and a repaint would undo the
      // autopilot line's "on" note or a press in flight.
      const endEl = root.querySelector('#runend'), endHtml = active ? '' : runEnd(r, d.strategies);
      if (endEl && endEl.dataset.h !== endHtml) { endEl.dataset.h = endHtml; endEl.innerHTML = endHtml; }
      const rsibox = root.querySelector('#rsibox');
      if (rsibox && d.rsi) {
        const delta = (d.rsi.base_score != null && d.rsi.score != null)
          ? `<span class="rsi-score">${d.rsi.base_score} <span class="rsi-arrow">→</span> ${d.rsi.score}</span>` : '';
        // The adopted policy is arbitrary agent-evolved Python with no structured decision record
        // behind it, so a raw-source dump isn't inspection — the human "What it changed" summary
        // and the generalization-score delta below are the faithful, readable account.
        // "How it searches: Self-tuning" sat among this session's figures and the explainer open under its
        // ideas on every session, though both describe the research system, not the session: they are one
        // folded "How research works" line (closed on every screen), its tag saying whether the search has
        // improved. A reader's open or close holds across the 2s repaint.
        const prev = rsibox.querySelector('details.rsidisc'), expanded = prev ? prev.open : false;
        const focused = !!rsibox.querySelector('details.rsidisc > summary:focus');
        const rsiHtml = `<details class="rsidisc rsi-run"${expanded ? ' open' : ''}><summary class="rsidisc-cap"><b class="rsi-badge">RSI</b><span class="rsidisc-t">How research works</span>${d.rsi.evolved ? '<span class="rsi-tag">Evolved</span>' : '<span class="rsi-tag quiet">Self-tuning</span>'}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary><div class="rsidisc-body">
          ${d.rsi.evolved
            ? `<p>This agent <b>rewrote its own search policy</b> from your history — and it beats the default.</p>
               ${d.rsi.summary ? `<p class="rsi-what"><b>What it changed:</b> ${esc(d.rsi.summary)}</p>` : ''}
               <p class="rsi-last">Generalization score ${delta}${d.rsi.evolved_at ? ' ·\u00a0adopted ' + when(d.rsi.evolved_at) : ''} <span class="rsi-note">(higher = catches more real out-of-sample winners, scored over shuffled orderings so it can't overfit)</span></p>`
            : `<p>The agent is <b>self-tuning</b>: after each research cycle it tries new ways of choosing which ideas to test, and keeps one only if it would have found more real winners in your own history (scored over shuffled orderings, so it can't overfit).</p>
               ${d.rsi.last_dream ? `<p class="rsi-last"><b>Last check${d.rsi.last_dream_at ? ' ·\u00a0' + when(d.rsi.last_dream_at) : ''}:</b> ${esc(d.rsi.last_dream)}</p>` : `<p class="rsi-last">No check yet. The first one runs at the end of a session, once at least ${d.rsi.min_history || 12} ideas have been tested.</p>`}`}
          </div></details>`;
        if (rsibox.dataset.h !== rsiHtml) { rsibox.dataset.h = rsiHtml; rsibox.innerHTML = rsiHtml; }
        if (focused) rsibox.querySelector('summary').focus({ preventScroll: true });
      }
      runControls(root.querySelector('#runact'), id, r.status, load);
      // Painted only when it changes, so a poll never closes "Show all" or drops a focused title.
      const gap = ideasGap(Math.max(+r.hypotheses_tried || 0, tried), (d.strategies || []).length, active);
      const ideasKey = runIdeas(d.strategies, whyBySid, false, gap);
      if (ideasEl.dataset.h !== ideasKey) { ideasEl.dataset.h = ideasKey; ideasEl.innerHTML = runIdeas(d.strategies, whyBySid, !!ideasEl.querySelector('details[open]'), gap); }
      stream.push(d.events);
      stream.state(active ? r.status : 'done', r.wait);
      obs.push(d.events, r.status, r);
      if (!active) clearTimers();
    };
    await load();
    poll(load, 2000, 'run-stale');
  }
  const DIR_BRIEF = (k) => ((S.me.directions.find((d) => d.key === k)) || { brief: '' }).brief;

  // ---------- strategies ----------
  async function viewStrategies() {
    const q = new URLSearchParams(location.search);
    const f = { status: q.has('status') ? q.get('status') : '', market: q.get('market') || '', q: q.get('q') || '', deployed: q.get('deployed') === '1' ? '1' : '' };
    shell('/strategies', boardTitle('Strategies', 'Every strategy your agents researched. Passed strategies on deployable markets can be deployed; void ones stay here so you can see what didn’t work.') +
      '<dl class="figures measure" id="sfigs" style="margin-top:14px"></dl>', `
      <div class="section-head filters stratfilters">
        <div class="chips" role="group" aria-label="Status">${[['', 'Kept'], ['passed', 'Passed'], ['backtest-only', 'Backtest only'], ['failed', 'Void'], ['rejected', 'Rejected']].map(([v, l]) => `<button class="chip" data-f="status" data-v="${v}" aria-pressed="${f.status === v}">${l}</button>`).join('')}
          <button class="chip" data-toggle="deployed" aria-pressed="${f.deployed === '1'}">Deployed</button></div>
        ${(() => { const by = {}; S.me.markets.forEach((m) => (by[m.category] || (by[m.category] = [])).push(m)); const cs = Object.keys(by).sort(catOrder); return `<label class="vh" for="strat-market">Market</label><select class="input strat-mkt" id="strat-market" aria-label="Filter by market"><option value="">All markets</option>${cs.map((c) => `<optgroup label="${esc(c)}">${by[c].map((m) => `<option value="${esc(m.key)}"${f.market === m.key ? ' selected' : ''}>${esc(marketShort(m.key))}</option>`).join('')}</optgroup>`).join('')}</select>`; })()}
        <div class="searchwrap"><input class="input" id="strat-q" type="search" placeholder="Search name or thesis…" value="${esc(f.q)}" aria-label="Search strategies"></div>
      </div>
      <div id="bulkbar" class="bulkbar" hidden></div>
      <div id="slips" style="margin-top:16px">${loading(240)}</div>`);
    const applyFilters = () => {
      const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== '' || false));
      if (!f.status) p.set('status', '');
      go('/strategies?' + p.toString(), true);
    };
    root.querySelectorAll('[data-f]').forEach((b) => { b.onclick = () => { f[b.dataset.f] = b.dataset.v; applyFilters(); }; });
    const marketSel = root.querySelector('#strat-market');
    if (marketSel) marketSel.onchange = () => { f.market = marketSel.value; applyFilters(); };
    const depToggle = root.querySelector('[data-toggle="deployed"]');
    if (depToggle) depToggle.onclick = () => { f.deployed = f.deployed === '1' ? '' : '1'; applyFilters(); };
    const sq = root.querySelector('#strat-q');
    if (sq) sq.onchange = () => { const v = sq.value.trim(); if (v !== f.q) { f.q = v; applyFilters(); } };
    // Paginate server-side at 50/page — a run_forever session can produce far more than the old
    // 500-row cap, and the figures/chip counts come from a real COUNT(*), not the fetched page.
    const CLABEL = { passed: 'Passed', 'backtest-only': 'Backtest only', failed: 'Void', rejected: 'Rejected' };
    const slipsEl = root.querySelector('#slips');
    let sp = 0;
    const load = async () => {
      slipsEl.innerHTML = loading(240);
      const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== ''));
      p.set('page', sp);
      let d;
      try { d = await api('/api/strategies?' + p.toString()); } catch (e) {
        if (e.status === 401) throw e;
        slipsEl.innerHTML = loadFail(errText(e));
        slipsEl.querySelector('[data-retry]').onclick = () => load();
        return;
      }
      const counts = d.counts || {}, total = counts.total || 0, c = (st) => counts[st] || 0;
      root.querySelector('#sfigs').innerHTML = fig(gl('Passed', 'passed'), c('passed')) + fig(gl('Void on unseen data', 'void'), c('failed')) + fig(gl('Rejected in testing', 'rejected'), c('rejected')) +
        fig('Pass rate', total ? pct(c('passed') / total, false) : '—');
      const kept = total - c('failed') - c('rejected');
      root.querySelectorAll('[data-f="status"]').forEach((b) => { const v = b.dataset.v; b.textContent = v ? `${CLABEL[v]} (${c(v)})` : `Kept (${kept})`; });
      const depChip = root.querySelector('[data-toggle="deployed"]');
      if (depChip && counts.deployed != null) depChip.textContent = `Deployed (${counts.deployed})`;
      if (!d.matched) {
        const noneKept = total && !kept && !f.status && !f.q && !f.market && !f.deployed;  // a new user's default view, not a filter miss
        // With autopilot on, the empty list says it is on instead of asking for a session (not "researching":
        // the autopilot panel may be reporting a stale check-in or a billing pause).
        const apOn = !!(S.me && S.me.user && S.me.user.autopilot);
        slipsEl.innerHTML = `<div class="empty"><h3>Nothing here yet</h3><p>${noneKept ? 'None of your strategies has passed its tests yet. Most ideas fail; the ones that pass land here.' : total ? 'Try another filter.' : apOn ? 'Autopilot is on. The strategies it finds will land here.' : 'Start a research session and the strategies it finds will land here.'}${noneKept && apOn ? ' Autopilot keeps researching on its own.' : ''}</p>${total && !noneKept ? '' : `${apNudge('Rather not write ideas yourself?', 'and it researches on its own, on paper.')}<a class="btn" href="/research">${apOn ? 'See its research' : 'Go to Research'}</a>`}</div>`;
        return;
      }
      const list = d.strategies, reg = registry(list.map((s) => s.equity));
      const anyPassed = list.some(bulkDeployable);
      slipsEl.innerHTML = strategyTable(list.map((s) => strategySlip(s, reg, { pick: anyPassed })).join(''), anyPassed)
        + (d.pages > 1 ? `<div class="xpage">${sp > 0 ? `<button class="btn sm" data-sp="${sp - 1}">← Prev</button>` : '<span></span>'}<span class="lab">Page ${sp + 1} of ${num(d.pages)} ·\u00a0${num(d.matched)} strategies</span>${sp + 1 < d.pages ? `<button class="btn sm" data-sp="${sp + 1}">Next →</button>` : '<span></span>'}</div>` : '');
      slipsEl.querySelectorAll('[data-sp]').forEach((b) => b.onclick = () => { sp = +b.dataset.sp; load(); window.scrollTo({ top: 0, behavior: smooth() }); });
      wireBulk();
    };
    // Multi-select deploy (paper only; live stays per-strategy behind the typed-LIVE gate).
    // Selection is per page — ponytail: cross-page selection is YAGNI for a 50-row page.
    const bar = root.querySelector('#bulkbar');
    const picks = () => Array.from(slipsEl.querySelectorAll('.pick'));
    const selected = () => picks().filter((c) => c.checked).map((c) => +c.dataset.id);
    const bulkDeploy = async () => {
      const ids = selected();
      if (!ids.length) return;
      let ok = 0; const errs = [];
      for (const id of ids) {
        try { await api('/api/deployments', { strategy_id: id, mode: 'paper' }); ok++; } catch (e) { errs.push(e.message); }
      }
      if (ok && !errs.length) { go('/deploy'); return; }
      flash('#bulkflash', `${ok} deployed${errs.length ? ` ·\u00a0${errs.length} failed: ${errs[0]}` : ''}`, errs.length ? 'bad' : 'good');
      if (ok) load();
    };
    const syncBar = () => {
      const pickAll = root.querySelector('#pick-all');
      const n = selected().length;
      if (!n) { bar.hidden = true; bar.innerHTML = ''; return; }
      bar.hidden = false;
      bar.innerHTML = `<span class="lab">${n} selected</span><button class="btn sm" id="bulk-dep">Deploy ${n} on paper</button><button class="btn sm ghost" id="bulk-clear">Clear</button><span id="bulkflash"></span>`;
      root.querySelector('#bulk-dep').onclick = (e) => busy(e.target, bulkDeploy);
      root.querySelector('#bulk-clear').onclick = () => { picks().forEach((c) => c.checked = false); if (pickAll) pickAll.checked = false; syncBar(); };
    };
    const wireBulk = () => {
      const pickAll = root.querySelector('#pick-all');
      if (pickAll) pickAll.onclick = () => { picks().forEach((c) => c.checked = pickAll.checked); syncBar(); };
      picks().forEach((c) => c.onchange = () => { if (pickAll && !c.checked) pickAll.checked = false; syncBar(); });
      syncBar();
    };
    load();
  }

  // What the strategy has actually done since it was deployed, per mode (live, demo, paper), from
  // its deployments' realized P&L. The page otherwise shows only the backtest.
  function realRecord(s) {
    // What the same trades would have made at the unseen-data backtest's average, scaled to each
    // deployment's stake, so "is it doing what the test said?" has an answer beside the real P&L.
    const oos = s.out_of_sample, stake = +s.stake;
    // A paused deployment (often paused automatically, and the bell links here) says so and why.
    const pausedLine = (ds) => {
      const p = ds.find((d) => d.status === 'paused');
      return p ? `<p class="real-paused"><b>Paused</b>${(p.status_why || p.status_reason) ? ': ' + esc((p.status_why || p.status_reason).replace(/\.$/, '')) + '.' : ''} <a href="/deploy">Resume or remove it on Deploy</a></p>` : '';
    };
    const pace = (ds, n) => {
      if (!n || !oos || !(+oos.trades > 0) || !(stake > 0)) return '';
      const per = (+oos.pnl || 0) / +oos.trades;
      const exp = ds.reduce((a, d) => a + (+d.closed_trades || 0) * per * ((+d.stake || stake) / stake), 0);
      return `<p class="sub-fig real-pace">At the backtest's unseen-data pace, ${n} trade${n === 1 ? '' : 's'} would have made ${usd(exp, true)}${n < 10 ? ' ·\u00a0too few trades to judge yet' : ''}</p>`;
    };
    // A server that compares each book with the backtest sends backtest_checks; it replaces the pace line.
    const checks = Array.isArray(s.backtest_checks) ? s.backtest_checks : null;
    const order = ['live', 'demo', 'paper'], label = { live: 'Live', demo: 'Demo', paper: 'Paper' }, cls = { live: 'live', demo: 'dep', paper: '' };
    const lines = order.map((mode) => {
      const ds = (s.deployments || []).filter((d) => d.mode === mode);
      if (!ds.length) return '';
      const pnl = ds.reduce((a, d) => a + (+d.realized_pnl || 0), 0), n = ds.reduce((a, d) => a + (+d.closed_trades || 0), 0);
      const open = ds.reduce((a, d) => a + (+d.open_positions || 0), 0);
      const since = ds.map((d) => d.created_at).filter(Boolean).sort()[0];
      return `<p><span class="mk ${cls[mode]}">${label[mode]}</span> ${n ? `${money(pnl)} realized over ${n} closed trade${n === 1 ? '' : 's'}` : 'No closed trades yet'}${open ? ` ·\u00a0${open} open` : ''}${since ? ` ·\u00a0deployed ${when(since)}` : ''}</p>${checks ? btCheckLine(checks.find((c) => c.mode === mode), 'p') : pace(ds, n)}${pausedLine(ds)}`;
    }).join('');
    // Removed deployments leave the list (and the lines above) but keep their record: one short line,
    // newest first, each with its own book, dates and realized P&L (books never added together).
    const past = Array.isArray(s.past_deployments) ? s.past_deployments : [];
    const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '—');
    const pastLine = past.length ? `<p class="sub-fig past-deps"><b>Past deployments:</b> ${past.slice(0, 3).map((p) => `${label[p.mode] || esc(p.mode)} ${day(p.created_at)}\u2013${day(p.removed_at)}, ${money(p.realized_pnl)} over ${num(p.closed_trades)} closed trade${p.closed_trades === 1 ? '' : 's'}`).join(' ·\u00a0')}${past.length > 3 ? ` ·\u00a0${num(past.length - 3)} earlier` : ''}</p>` : '';
    return lines || pastLine ? `<section class="real-record" aria-label="Since deploying"><h3 class="paper-h">Since deploying</h3>${lines}${pastLine}</section>` : '';
  }
  // Road to live in words, from the checks the server sends (live-readiness): what is left, each with
  // what it has and what it needs, and when the trades, events and hours could be in at the pace it
  // trades (the server's `pace`). Real money never follows on its own: it takes the user's own step.
  const roadDays = (d) => d < 1 ? 'under a day' : d < 1.5 ? 'about a day' : `about ${Math.round(d)} days`;
  // Three places, so a p of 0.104 never reads "0.10" beside "needs 0.10 or lower".
  const roadP = (v) => v == null ? '—' : v < 0.001 ? 'under 0.001' : (+v).toFixed(3);
  const roadClear = (r) => !!(r.deployment_candidate && r.paper && r.paper.ready);
  function roadLeft(r, s) {
    const p = r.paper, c = p.checks || {}, left = [];
    const more = (have, need, unit) => `${num(Math.max(0, need - have))} more ${unit} (${num(have)} of ${num(need)})`;
    const demoOn = (s.deployments || []).some((d) => d.mode === 'demo' && d.status !== 'stopped');
    if (!r.deployment_candidate) left.push('the gatekeeper’s clearance');
    if (c.realistic_trades === false) left.push(more(+p.trades, +p.trades_needed, 'paper trades'));
    if (c.legacy_pnl === false) left.push(`paper P&amp;L with every fill at $0 or above (now ${usd(p.legacy_pnl, true)})`);
    if (c.events === false) left.push(more(+p.events, +p.events_needed, 'events'));
    if (c.net_pnl === false) left.push(`net P&amp;L above $0 (now ${usd(p.net_pnl, true)})`);
    if (c.span === false) left.push(`${num(Math.ceil(p.span_needed_hours - p.span_hours))}h more of record (${num(Math.floor(p.span_hours))}h of ${num(p.span_needed_hours)}h)`);
    if (c.edge === false) left.push(p.p_value == null ? 'the edge test, run once the trades and events are in' : `a clearer edge (p ${roadP(p.p_value)}, needs ${p.p_value_needed.toFixed(2)} or lower)`);
    if (c.recent === false) left.push(`its newer trades above $0 (now ${usd(p.recent_net_pnl, true)})`);
    if (c.demo === false) {
      left.push(+p.demo_orders < +p.demo_orders_needed ? more(+p.demo_orders, +p.demo_orders_needed, 'demo orders') + (demoOn ? '' : ' on a demo deployment')
        : p.demo_unresolved ? `${num(p.demo_unresolved)} lost demo order${p.demo_unresolved === 1 ? '' : 's'} accounted for`
        : (p.demo_mismatched_tickers || []).length ? 'a demo book that matches the demo exchange'
        : 'a check of its demo book against the demo exchange in the last 24h');
    }
    // A failing check this page doesn't name is said in the server's own words.
    if (!left.length && !roadClear(r)) left.push(esc(p.why || r.blocking || 'a check this page can’t name'));
    return left;
  }
  function roadSummary(r, s, liveWhy, total) {
    const p = r.paper, c = p.checks || {}, pace = r.pace, left = roadLeft(r, s);
    const lines = [];
    if (roadClear(r)) {
      lines.push(`<p class="road-sum"><b>Its record clears every check.</b> It still trades paper money only. ${liveWhy ? 'Before it can go live: ' + liveWhy : 'Moving it to live money is your call: Deploy with live money, then type LIVE.'}</p>`);
    } else {
      lines.push(`<p class="road-sum"><b>${left.length} of ${total} check${total === 1 ? '' : 's'} left</b> before it may trade real money: ${left.join('; ')}.</p>`);
      const counts = c.realistic_trades === false || c.events === false || c.span === false;
      const paused = (s.deployments || []).some((d) => d.mode === 'paper' && d.status === 'paused');
      const tpd = pace && pace.trades_per_day;
      if (pace && !pace.running) lines.push(`<p class="hint">${paused ? 'Its paper deployment is paused, so its record isn’t growing. <a href="/deploy">Resume it on Deploy</a>.'
        : `It isn’t running on paper, so its record isn’t growing${+p.trades ? `. Its ${num(p.trades)} earlier paper trade${+p.trades === 1 ? '' : 's'} still count` : ''}. Deploy it on paper to add to it.`}</p>`);
      else if (pace && counts && pace.eta_days != null) lines.push(`<p class="hint road-eta">At its ${pace.rate_from === 'paper' ? 'paper' : 'backtest'} pace (${tpd >= 1 ? `about ${num(Math.round(tpd))} trade${Math.round(tpd) === 1 ? '' : 's'} a day` : 'under one trade a day'}), it could have the trades, events and hours in <b>${roadDays(pace.eta_days)}</b>. The P&amp;L, edge and demo checks are judged on that record, and it may not pass them.</p>`);
      else if (pace && counts) lines.push('<p class="hint road-eta">It hasn’t traded enough yet to estimate when it could have the trades, events and hours.</p>');
    }
    return lines.join('');
  }
  // Where a strategy sits on the paper → demo → live ladder: one line per book it runs in now, each
  // with its own closed trades and realized P&L (never added to another book's), then one line on what
  // the next rung needs. The live rung's needs come from Road to live (live-readiness); until that data
  // is in, or when there is none, that line is left out rather than guessed.
  const LADDER = [['paper', 'Paper', ''], ['demo', 'Demo', 'dep'], ['live', 'Live', 'live']];
  function ladderLines(s, { canDeploy, demoWhy, road }) {
    const deps = s.deployments || [];
    // A paused book is still on its rung (deploying it there again would double its positions): it says paused.
    const running = LADDER.filter(([m]) => deps.some((d) => d.mode === m && d.status !== 'stopped'));
    const books = running.map(([m, label, cls]) => {
      const ds = deps.filter((d) => d.mode === m);
      const n = ds.reduce((a, d) => a + (+d.closed_trades || 0), 0), pnl = ds.reduce((a, d) => a + (+d.realized_pnl || 0), 0);
      const stats = `${num(n)} closed trade${n === 1 ? '' : 's'} ·\u00a0${money(pnl)} realized`;
      // A demo book Kalshi refuses every order for is not "running": it says why, and what to do.
      if (m === 'demo' && s.demo_health) return `<p><span class="mk ${cls}">${label}</span> ${stats} ·\u00a0${demoHealthLine(s.demo_health)}</p>`;
      return `<p><span class="mk ${cls}">${label}</span> ${ds.some((d) => d.status === 'running') ? 'running' : 'paused'} ·\u00a0${stats}</p>`;
    });
    // Paper proves the edge, demo the order path: say so under the demo book, with its settled demo
    // orders against what the live check needs once Road to live is in.
    const p = road && road.paper;
    if (books.length && running.some(([m]) => m === 'demo')) {
      const orders = p && p.demo_orders_needed ? ` Live needs ${num(p.demo_orders_needed)}+ settled demo orders: ${num(p.demo_orders || 0)} so far.` : '';
      books.splice(running.findIndex(([m]) => m === 'demo') + 1, 0, `<p class="hint rung-demo">Paper tests the edge; demo tests the order path on Kalshi’s sandbox with play money. Its book is thin, so demo fills and P&amp;L differ from paper’s.${orders}</p>`);
    }
    const next = LADDER[running.length ? LADDER.indexOf(running[running.length - 1]) + 1 : 0];
    let need = '';
    if (!next) need = 'Top rung: it trades live money.';
    else if (!canDeploy) need = '';
    else if (next[0] === 'paper') need = 'Next rung, paper: nothing needed. Deploy it on paper below.';
    else if (next[0] === 'demo') need = (demoWhy ? 'Next rung, demo: needs your Kalshi demo (sandbox) key on the <a href="/funds">Funds page</a>.'
      : s.demo_health ? `Next rung, demo: needs ${esc(s.demo_health.need)}.${actionLink(s.demo_health)}` : 'Next rung, demo: nothing needed. Deploy it on demo below.')
      + ' Demo runs the same rules on Kalshi’s sandbox with play money, to prove its orders place, fill and book before live money.';
    else if (road) {
      const left = roadLeft(road, s);
      need = `Next rung, live: ${roadClear(road) ? 'its record clears every check. It trades live money only once you deploy it there' : `${left.length} check${left.length === 1 ? '' : 's'} left, first ${left[0]}`}.`;
    }
    return books.join('') + (need ? `<p class="hint">${need}</p>` : '');
  }
  // The verdict in one line near the top of a strategy page: whether it passed and on what held-out
  // evidence, or the check it missed. The full evidence stays in Verdict, which on a phone is many
  // screens down; a Void strategy's page read "returned $3.10 on unseen data" up top and said why it
  // failed only there.
  function verdictGlance(s, missed) {
    const exp = s.experiment, h = exp && exp.holdout, v = exp && exp.validation;
    const lc = (t) => String(t).charAt(0).toLowerCase() + String(t).slice(1);
    let lead, words;
    if (missed && ['failed', 'rejected'].includes(s.status)) {
      lead = s.status === 'failed' ? 'Void.' : 'Rejected.';
      words = `It missed ${missed.length === 1 ? 'a check' : missed.length + ' checks'}: ${lc(missed[0].label)}${missed.length > 1 ? `, and ${missed.length - 1} more` : ''}. Verdict, below, has what was measured and what to try next.`;
    } else if (s.status === 'passed' && h && h.n_trades != null && ['deployment_candidate', 'forward_validated'].includes(exp.classification)) {
      lead = 'Passed.';
      words = `It cleared every check, including the one-time locked holdout: ${num(h.n_trades)} trades on data it had never seen${h.mean_net_return != null ? `, averaging ${rpRet(h.mean_net_return)} of the stake per trade after fees` : ''}.`;
    } else if (s.status === 'passed' && v && v.n_trades != null && !h) {
      lead = 'Passed validation.';
      words = `It cleared the checks on ${num(v.n_trades)} trades it had never seen; the one-time locked holdout hasn’t run yet.`;
    } else if (s.status === 'backtest-only') {
      lead = 'Backtest only.';
      words = 'It never went through the held-out checks, so its only evidence is the backtest below.';
    } else return '';
    return `<p class="paper-ab-result verdict-glance"><b>${esc(lead)}</b> ${esc(words)}</p>`;
  }

  async function viewStrategy(id) {
    shell('/strategies', boardTitle('Strategy') + '<dl class="figures measure" id="figs" style="margin-top:14px"></dl>', loading(420));
    const s = await api('/api/strategies/' + id);
    const perpetual = isPerpetual(s), restricted = researchOnly(s);
    const ins = s.in_sample || {}, oos = s.out_of_sample;
    const figsFor = (r) => fig('Unseen-data P&L', r.out_of_sample ? usd(r.out_of_sample.pnl, true) : '—', { v: r.out_of_sample && r.out_of_sample.pnl, small: r.out_of_sample ? `${r.out_of_sample.trades} trades${overDays(r.out_of_sample.days)} the agent never saw` : 'Rejected before the unseen test' }) +
      fig('In-sample P&L', r.in_sample ? usd(r.in_sample.pnl, true) : '—', { v: r.in_sample && r.in_sample.pnl, small: r.in_sample ? `${r.in_sample.trades} trades on the history it searched` : 'No in-sample result recorded' }) +
      fig('Return on capital', r.out_of_sample ? pct(r.out_of_sample.roi) : '—', { small: [r.out_of_sample && overDays(r.out_of_sample.days) ? 'Unseen data' + overDays(r.out_of_sample.days) : '', r.capital ? `$${fmt0.format(r.capital)} at risk at most` : ''].filter(Boolean).join(' ·\u00a0') }) +
      fig('Hypotheses tested', s.hypotheses_tried ? `1 of ${s.hypotheses_tried}` : '—', { small: s.hypotheses_tried ? `The agent tested ${num(s.hypotheses_tried)} distinct ideas this run${s.status === 'passed' ? '; this is the one that passed' : ''}. More tries → higher chance one passes by luck (multiple testing).` : 'How many ideas the agent tried to find this one.' });
    // A strategy from the seeded example session says so here too, as the lists and its run page do.
    root.querySelector('.board-title').outerHTML = boardTitle(serial(s.id) + ' ·\u00a0' + marketShort(s.market),
      `${s.example ? EXAMPLE_TAG + ' ' : ''}${esc(dirLabel(s.direction))}${s.example ? ' \u00b7\u00a0' + EXAMPLE_NOTE : ''}`);
    root.querySelector('#figs').innerHTML = figsFor(s);
    const canDeploy = !restricted && ['passed', 'failed', 'rejected'].includes(s.status);
    // Why a strategy was rejected (never reached the unseen-data gate) — stated honestly: a
    // profitable idea with too few trades is rejected on sample size, not for "losing money".
    const rejectReason = (st) => {
      const i = st.in_sample || {};
      if (i.trades != null && i.trades < 5) return `it made ${usd(i.pnl, true)} in testing, but over just ${i.trades} trade${i.trades === 1 ? '' : 's'} — a finalist needs at least 5, too few to trust.`;
      if (i.pnl != null && +i.pnl <= 0) return `it lost money in testing (${usd(i.pnl, true)}).`;
      return 'it ranked below the handful of finalists we tested on unseen data.';
    };
    const liveWhy = !S.me.live_trading_available ? 'Live trading isn’t open yet.' : !S.me.kalshi_connected ? 'Connect Kalshi on the <a href="/funds">Funds page</a> first.' : (s.side !== 'yes' && !S.me.no_side_live_enabled) ? 'NO-side live trading is still being validated on the demo sandbox — deploy this on demo or paper for now.' : '';
    // Both are fixed strings (no user data), so they render as HTML with a link to Funds.
    const demoWhy = !S.me.kalshi_dev_connected ? 'Add your Kalshi demo (sandbox) key on the <a href="/funds">Funds page</a> first.' : '';
    // Overfit/luck tells on a raw backtest column: a tiny sample, a perfect win rate, no losing
    // trades (profit factor runs away), or an implausibly high daily Sharpe are the classic
    // signatures of a number too good to be real. Flag them inline so a raw backtest is never
    // read as a tradable edge. The sample bar comes from the server (the app's one "too few to tell
    // skill from luck" level), a caution stricter than the gate's own trade floor, so the line names both.
    const caution = s.sample_caution || {};
    const luckFlag = (m) => {
      if (!m) return '';
      const r = [];
      if (m.trades != null && caution.min_trades != null && m.trades < caution.min_trades) r.push(`n=${m.trades} — under ${caution.min_trades} trades, too few to tell skill from luck${caution.gate_min_oos_trades != null ? ` (a caution, stricter than the gate’s floor of ${caution.gate_min_oos_trades})` : ''}`);
      if (m.win_rate === 1) r.push('100% win rate — an overfit signature, not an edge');
      if (typeof m.profit_factor === 'number' && m.profit_factor >= 99) r.push('no losing trades in sample — profit factor is meaningless');
      if (typeof m.sharpe === 'number' && m.sharpe >= 3) r.push(`Sharpe ${m.sharpe} is implausibly high for a real net edge`);
      return r.length ? `<p class="hint luck-flag">⚠ ${esc(r.join(' ·\u00a0'))}</p>` : '';
    };
    const metricRows = (m) => m ? `<dl>
        <dt>P&amp;L after fees</dt><dd class="${tone(m.pnl)}">${usd(m.pnl, true)}</dd>
        <dt>Trades</dt><dd>${m.trades}${m.trades_per_day != null ? ` <small class="hint">(${m.trades_per_day}/day)</small>` : ''}</dd>
        <dt>Win rate</dt><dd>${pct(m.win_rate, false)}</dd>
        <dt>Fees paid</dt><dd>${usd(m.fees)}</dd>
        <dt>Profit factor</dt><dd>${m.profit_factor == null ? '—' : m.profit_factor}</dd>
        <dt>Worst drawdown</dt><dd>${usd(m.max_drawdown)}</dd>
        <dt>Sharpe (daily)</dt><dd>${m.sharpe == null ? '—' : m.sharpe}</dd></dl>${luckFlag(m)}` : `<p class="hint">Not tested on unseen data — ${rejectReason(s)}</p>`;
    const gatesHtml = (gs) => gs && gs.length ? `<ul class="gates">${gs.map((g) => `<li class="${g.ok ? 'ok' : 'no'}">${g.ok ? ICON.check : ICON.cross}<span>${esc(g.name)}<small>needs ${esc(g.threshold)}</small></span><span class="v">${typeof g.value === 'number' && /\$|drawdown|money/i.test(g.name + g.threshold) ? usd(g.value) : esc(g.value == null ? '—' : g.value)}</span></li>`).join('')}</ul>` : '<p class="hint">No gate results recorded for this strategy. Gates only run for finalists that made money in testing.</p>';
    const trades = (s.recent_trades || []).length ? `<div class="sheet"><table class="table stack t-unseen"><thead><tr><th>Opened</th><th>Contract</th><th>Side</th><th class="num">Entry${perpetual ? ' (USD)' : ''}</th><th class="num">Exit${perpetual ? ' (USD)' : ''}</th><th class="num">P&amp;L</th></tr></thead><tbody>
        ${s.recent_trades.map((t) => `<tr><td data-lab="Opened">${t.opened ? esc(new Date(t.opened.replace('Z', ':00Z')).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })) : '—'}</td><td class="tick" data-lab="Contract">${esc(t.ticker)}</td><td data-lab="Side">${t.side ? esc(t.side.toUpperCase()) : '—'} ×${t.qty}</td><td class="num" data-lab="Entry">${tradePrice(t.entry, perpetual)}</td><td class="num" data-lab="Exit">${tradePrice(t.exit, perpetual)} <small class="hint">${esc(exitWord(t.reason))}</small></td><td class="num ${tone(t.pnl)}" data-lab="P&amp;L">${usd(t.pnl, true)}</td></tr>`).join('')}
      </tbody></table></div>` : '<p class="hint">No unseen-data trades to show.</p>';
    const activeDeps = restricted ? [] : s.deployments.filter((d) => d.status !== 'stopped');
    // Stopped deployments can still hold positions; the server refuses the delete until they close.
    const delBlock = restricted ? null : (s.delete_block || null);
    const kUrl = marketKalshiUrl(s.market);
    const mktLink = kUrl ? `<a href="${kUrl}" target="_blank" rel="noopener">${esc(marketLabel(s.market))} ↗</a>` : esc(marketLabel(s.market));
    // ---- the strategy dossier, composed as a research paper (abstract → mechanism →
    // methodology → results → verdict). Each section renders only when it has content, so a
    // pre-pipeline strategy with no ledger row falls back to its rule + backtest + plain verdict.
    const rp = researchPaper(s.experiment);
    const hasExp = !!s.experiment;
    const filed = (() => { try { return new Date(s.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); } catch (e) { return ''; } })();
    const abResult = oos
      ? `On unseen data the agent never touched while iterating, it ${+oos.pnl >= 0 ? 'returned ' + usd(oos.pnl) : 'lost ' + usd(Math.abs(oos.pnl))} over ${num(oos.trades)} trade${oos.trades === 1 ? '' : 's'}${s.hypotheses_tried ? (s.status === 'passed' ? `, and cleared the gate as one of ${num(s.hypotheses_tried)} ideas tested this run` : `, one of ${num(s.hypotheses_tried)} ideas tested this run`) : ''}.`
      : `It was ${s.status === 'rejected' ? 'rejected before reaching' : 'not advanced to'} the unseen-data test${s.hypotheses_tried ? ` — one of ${num(s.hypotheses_tried)} ideas tried this run` : ''}.`;
    const dataBlock = s.dataset ? `<div class="paper-sub"><h4 class="paper-h">Data &amp; partitioning</h4>
          <dl class="rp-grid">
            <div><dt>Market</dt><dd>${mktLink}</dd></div>
            <div><dt>Direction</dt><dd>${esc(dirLabel(s.direction))}</dd></div>
            <div><dt>History window</dt><dd>${esc((s.dataset.start || '').slice(0, 10)) || '—'} → ${esc((s.dataset.end || '').slice(0, 10)) || '—'}</dd></div>
            <div><dt>Unseen (held out) from</dt><dd>${esc((s.dataset.out_of_sample_from || '').slice(0, 10)) || '—'}</dd></div>
          </dl>
          <p class="rp-sub" style="margin-top:8px">${perpetual ? 'The agent only saw the research partition. ' + PERPS_SCENARIO : "The agent only ever saw data before the held-out date. Every simulated fill pays the ask or bid plus Kalshi's taker fee — results are net of fees or they do not count."}</p></div>` : '';
    // What it does, in plain words: the paper's first section. It sat inside the Methodology fold,
    // which a phone opens closed, under the pre-registration, so the rule took digging to find.
    const ruleBlock = `${(s.rules || []).length ? `<ul class="rules">${s.rules.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
          <details class="raw"><summary>Exact machine spec (JSON)</summary><pre>${esc(JSON.stringify(s.spec, null, 2))}</pre></details>`;
    const methodologyBody = rp.methodology + dataBlock + (perpetual && !s.dataset ? `<p class="hint">${PERPS_SCENARIO}</p>` : '');
    const resultsBody = rp.results
      + `<div class="paper-sub"><h4 class="paper-h">${perpetual ? 'Perpetual research scenario' : hasExp ? 'Backtest &amp; Kalshi demo replay' : 'Backtest'}</h4>
          ${hasExp ? '<p class="rp-sub" style="margin-top:0">These are the agent\'s own in-sample/replay numbers. The in-sample column is optimistically biased — the rule was fit on exactly this data — so trust the held-out validation-window evidence above, not the column below.</p>' : ''}
          <div id="sheet-results">
            <div id="equity-wrap">${s.equity ? equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from, null, { width: chartWidth() }) : ''}</div>
            <div class="split"><div><h4>Tested on (in-sample)</h4>${s.in_sample ? metricRows(ins) : '<p class="hint">No in-sample result recorded.</p>'}</div><div><h4>Never seen (out-of-sample)</h4>${metricRows(oos)}</div></div>
          </div></div>`
      + fold('Most recent unseen trades', `<div class="paper-sub"><h4 class="paper-h">Most recent unseen trades</h4>${trades}</div>`);
    let verdictBody = rp.verdict;
    if (!hasExp) {
      const btOnly = ['sig', 'armed', 'Backtest only', 'Backtest-only — never put through statistical validation (no pre-registration, one-time holdout, or multiple-testing control). These numbers come from a sample too small to separate skill from luck. ' + (perpetual ? 'This market remains research only.' : restricted ? 'Agent-written code stays in research.' : 'It can’t be deployed: only a strategy put through those checks can be.')];
      const vmap = {
        // No experiment resolved (by experiment_id OR strategy_id) means NO gatekeeper record
        // exists — so this was NOT validated, whatever the status says. Never claim it "cleared
        // the gatekeeper" (that would be a lie); flag the missing record honestly. A correctly
        // validated 'passed' always has an experiment and takes the rich path above, not this one.
        passed: ['sig', 'armed', 'Not validated (record missing)', 'Marked passed, but no statistical-gatekeeper record (pre-registration, validation, holdout) can be found for it — so the backtest figures on this page are in-sample only, not held-out evidence. Treat it as unvalidated; the row is being reclassified to backtest-only.'],
        'backtest-only': btOnly,
        failed: ['sig', 'armed', 'Void', 'It reached the unseen-data gate and failed it, so it was not validated.'],
        rejected: ['quiet', 'quiet', 'Rejected', 'Rejected — ' + rejectReason(s)],
      };
      const [vt, chip, label, words] = vmap[s.status] || ['quiet', 'quiet', rpHuman(s.status), 'Awaiting a recorded verdict.'];
      verdictBody = `<div class="rp-verdict ${vt}"><span class="mk ${chip}">${esc(label)}</span><p>${esc(words)}</p></div>`;
    }
    const missed = Array.isArray(s.why_failed) && s.why_failed.length ? s.why_failed : null;
    if (missed) verdictBody += `<div class="paper-sub"><h4 class="paper-h">What it missed, and what to try next</h4>${whyFailedHtml(missed)}</div>`;
    const ladder = restricted ? '' : ladderLines(s, { canDeploy, demoWhy });
    // On a phone the Deploy panel sits below the whole paper, screens down. A validated passed
    // strategy (one with its gatekeeper record) that isn't on paper yet gets its primary action up
    // top too; same call as #dep-paper. Wide screens hide it (the panel is beside the paper there).
    const quickPaper = canDeploy && s.status === 'passed' && hasExp && !activeDeps.some((d) => d.mode === 'paper');
    const quickHtml = quickPaper ? `<div class="strat-quick" id="strat-quick"><button class="btn primary" id="dep-paper-quick">Deploy on paper</button><p class="hint">Paper trades with pretend money against live prices, so nothing real is at risk. Demo and live are in Deploy, further down.</p><div id="depflash-quick"></div></div>` : '';
    const paperSec = (title, body) => body ? `<section class="paper-sec"><h3 class="paper-sec-t">${title}</h3><div class="paper-sec-body">${body}</div></section>` : '';
    root.querySelector('main').innerHTML = `
      <div id="flash"></div>
      <div class="detail">
        <div>
          <article class="sheet-doc paper">
            <header class="paper-head">
              <div class="paper-cite"><span>${esc(serial(s.id))}</span><span>${esc(marketShort(s.market))} ·\u00a0${esc(dirLabel(s.direction))}</span>${filed ? `<span>Filed ${esc(filed)}</span>` : ''}</div>
              <h2 class="paper-title">${esc(s.title)}</h2>
              <div class="paper-byline">${mark(s.status)}${researchBadge(s)}${s.shared_from ? ` <span class="mk shared">${ICON.share}Shared by ${esc(s.shared_from)}</span>` : ''}</div>
            </header>
            ${quickHtml}
            <section class="paper-abstract">
              <h3 class="paper-h">Abstract</h3>
              <p class="paper-ab">${mdLite(s.thesis)}</p>
              <p class="paper-ab-result">${abResult}</p>
              ${verdictGlance(s, missed)}
            </section>
            ${restricted ? '' : realRecord(s)}
            <div class="paper-body">
              ${paperSec('What it does, in plain words', ruleBlock)}
              ${paperSec('Mechanism &amp; hypothesis', rp.mechanism)}
              ${fold('Methodology', paperSec('Methodology', methodologyBody))}
              ${paperSec('Results', resultsBody)}
              ${paperSec('Verdict', verdictBody)}
            </div>
          </article>
        </div>
        <aside>
          ${!restricted && s.holdings && s.holdings.length ? (() => {
            // One summary per money book: a strategy can hold on paper and demo (or live) at once, and
            // their cost and unrealized P&L are never added together. A single book reads as before.
            const books = ['live', 'demo', 'paper'].map((m) => s.holdings.filter((p) => (p.mode || 'paper') === m)).filter((xs) => xs.length);
            const bookLine = (xs) => {
              const marked = xs.filter((p) => p.unrealized != null), unreal = marked.reduce((a, p) => a + p.unrealized, 0);
              const lead = books.length > 1 ? ({ live: 'Live', demo: 'Demo', paper: 'Paper' })[xs[0].mode || 'paper'] + ': ' : '';
              return `${lead}${xs.length} open position${xs.length === 1 ? '' : 's'} at cost + fees ${usd(xs.reduce((a, p) => a + p.cost, 0))}${marked.length ? ` ·\u00a0unrealized ${money(unreal)} (est., mark-to-market on the current bid)` : ' ·\u00a0awaiting first mark'}.`;
            };
            // A list, not a five-column table: in the sidebar the table clipped everything after Position.
            return `<section class="panel"><h3>Holding right now</h3>
            <ul class="holdlist">${s.holdings.map((p) => `<li><div class="tick">${contractLink(p.ticker)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : p.mode === 'demo' ? '<span class="mk dep">Demo</span>' : ''}</div>${contractMarket(p.ticker) ? `<div class="sub-fig pos-mkt">${esc(contractMarket(p.ticker))}</div>` : ''}
              <div class="holdlist-figs"><b>${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(p.entry_price)}</b><span>Cost + fee ${usd(p.cost)}</span><span>Unreal. ${p.unrealized == null ? '—' : money(p.unrealized)}</span><span>Settles ${settleAt(p.market_close_time)}</span></div>${p.why ? `<div class="sub-fig pos-why">${esc(p.why)}</div>` : ''}</li>`).join('')}</ul>
            <p class="hint" style="margin-top:8px">${books.map(bookLine).join('<br>')}</p></section>`;
          })() : ''}
          ${ladder ? `<section class="panel" id="ladder"><h3>Paper → demo → live</h3><div class="rung-books" id="ladder-body">${ladder}</div></section>` : ''}
          <section class="panel"><h3>${restricted ? 'Research only' : 'Deploy'}</h3>
            ${canDeploy ? `<div style="display:grid;gap:10px">
                ${s.status !== 'passed' ? `<div class="notice bad">${ICON.warn}<span>${missed ? `${s.status === 'failed' ? 'Void' : 'Rejected'}: ${esc(missed[0].label.charAt(0).toLowerCase() + missed[0].label.slice(1))}${missed.length > 1 ? `, and ${missed.length - 1} more check${missed.length > 2 ? 's' : ''} missed` : ''} (see Verdict).` : s.status === 'failed' ? 'Void: it failed the unseen-data gate.' : `Rejected: ${rejectReason(s)}`} It wasn’t validated, so deploying it — on paper or live — is your call and your risk.</span></div>` : ''}
                <button class="btn" id="dep-paper">Deploy on paper</button>${paperAgain(activeDeps)}
                ${fold('Demo &amp; live', `<div class="fold-body" style="display:grid;gap:10px">
                <button class="btn ghost" id="dep-demo" ${demoWhy ? 'aria-disabled="true"' : ''}>Deploy on demo (sandbox)</button>
                ${demoWhy ? `<p class="hint">${demoWhy}</p>` : '<p class="hint">Trades Kalshi’s demo exchange with your own demo key — real order-book fills, no real money.</p>'}
                <button class="btn ghost" id="dep-live" ${liveWhy ? 'aria-disabled="true"' : ''}>Deploy with live money</button>
                ${liveWhy ? `<p class="hint">${liveWhy}</p>` : ''}
                <form id="live-confirm" hidden style="display:grid;gap:8px">
                  <p class="hint">This trades real money in your Kalshi account. Type <b>LIVE</b> to confirm.</p>
                  <input class="input" name="confirm" autocomplete="off" aria-label="Type LIVE to confirm">
                  <button class="btn" type="submit">Confirm live deployment</button>
                </form></div>`)}
                <div id="depflash"></div>
              </div>` : restricted ? `<p class="hint">${perpetual ? 'Perpetual strategies stay in research, including after passing the statistical gates. Paper, demo and live deployment are unavailable.' : CODE_RESEARCH_ONLY}</p>` : `<p class="hint">${s.status === 'backtest-only' ? 'A backtest-only strategy can’t be deployed: it never went through the held-out checks. To test this idea properly, ask for it in a new research session.' : 'This strategy isn’t ready to deploy yet.'}</p>`}
            ${!restricted && s.deployments.length ? `<p class="hint" style="margin-top:12px">Already deployed: ${s.deployments.map((d) => `${bookName(d)} (${esc(d.status)})`).join(', ')}. <a href="/deploy">See them on the Deploy page</a></p>` : ''}
            ${kUrl ? `<p class="hint" style="margin-top:12px"><a href="${kUrl}" target="_blank" rel="noopener">Open ${esc(marketShort(s.market))} on Kalshi ↗</a></p>` : ''}
          </section>
          ${!restricted && s.status === 'passed' ? `<section class="panel" id="road-live"><h3>Road to live</h3><div id="road-live-body"><p class="hint">Checking…</p></div></section>` : ''}
          <section class="panel"><h3>Gates</h3><div id="gates">${gatesHtml(s.gates)}</div></section>
          ${!perpetual && s.status !== 'rejected' ? fold('What if…', `<section class="panel" id="whatif"><h3>What if…</h3>
            <p class="hint" style="margin-bottom:6px">Move a dial and the whole sheet re-runs.</p>
            <div class="dial"><div class="top"><label class="label" for="wf">Fees</label><output id="wfo">1.0×</output></div><input type="range" id="wf" min="0" max="3" step="0.25" value="1"></div>
            <div class="dial"><div class="top"><label class="label" for="ws">Slippage per fill</label><output id="wso">0.0¢</output></div><input type="range" id="ws" min="0" max="5" step="0.1" value="0"></div>
            ${s.stake != null ? `<div class="dial"><div class="top"><label class="label" for="wk">Stake per trade</label><output id="wko">$${esc(s.stake)}</output></div><input type="range" id="wk" min="1" max="200" step="1" value="${Math.min(200, s.stake)}"></div>` : ''}
            <div id="wflash" aria-live="polite"></div>
          </section>`) : ''}
          ${fold('Share', `<section class="panel"><h3>Share</h3>
            <p class="hint" style="margin-bottom:8px">${restricted ? 'Share a research-only copy using their Tau sign-in email. It keeps the same simulation limits and cannot be deployed.' : "Send a copy to a friend by the email they sign in with. They can deploy it like their own — sharing can't be undone."}</p>
            <form id="share-form" style="display:grid;gap:8px">
              <input class="input" id="share-email" type="email" autocomplete="off" placeholder="friend@email.com" aria-label="Friend's email">
              <button class="btn sm" type="submit">Share strategy</button>
            </form><div id="shareflash"></div>
          </section>`)}
          ${fold('Remove', `<section class="panel"><h3>Remove</h3>
            <p class="hint" style="margin-bottom:8px" id="del-why">Delete this strategy from your inventory. ${activeDeps.length ? 'Stop its deployment first — you can do it right here.' : delBlock ? esc(delBlock) : 'This can’t be undone.'}</p>
            <div style="display:grid;gap:8px">
              ${activeDeps.length ? `<button class="btn sm danger" id="stop-dep">Stop deployment${activeDeps.length > 1 ? 's' : ''} (${activeDeps.map((d) => bookName(d).toLowerCase()).join(', ')})</button>` : ''}
              <button class="btn sm danger" id="del-strat" ${activeDeps.length || delBlock ? 'aria-disabled="true" aria-describedby="del-why"' : ''}>Delete strategy</button>
            </div><div id="delflash"></div>
          </section>`)}
        </aside>
      </div>`;
    // Second equity line: the strategy's unseen window replayed read-only against
    // the Kalshi demo environment. Fetched after the page so a slow/absent demo
    // never blocks the view; absent -> the chart simply stays sim-only.
    if (!perpetual && s.equity && oos) (async () => {
      try {
        const r = await api('/api/strategies/' + s.id + '/dev-curve');
        const wrap = root.querySelector('#equity-wrap');
        if (wrap && r && r.dev_curve && r.dev_curve.length > 1) {
          const sl = r.slippage, sc = (v) => (v >= 0 ? '+' : '') + v.toFixed(1) + '¢';
          wrap.innerHTML = equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from, r.dev_curve, { width: chartWidth() })
            + `<p class="hint" style="margin-top:6px">Dashed line: the unseen window replayed read-only against Kalshi's demo environment${r.capped ? ` (first ${r.contracts} contracts)` : ''} — real demo order-book prices, scored with the same fees. No orders are placed.</p>`
            + (sl ? `<p class="hint" style="margin-top:4px;font-variant-numeric:tabular-nums">Real demo-book slippage: <b>${sc(sl.entry_cents)}</b> entry${sl.exit_cents != null ? ` / <b>${sc(sl.exit_cents)}</b> exit` : ''} over ${sl.n_trades} aligned trade${sl.n_trades === 1 ? '' : 's'} (positive means real fills were worse). <button type="button" class="btn sm" id="apply-slip">Apply to what-if</button></p>` : '');
          if (sl) {
            const perFill = Math.max(0, Math.min(5, sl.exit_cents != null ? (sl.entry_cents + sl.exit_cents) / 2 : sl.entry_cents));
            const ws = root.querySelector('#ws'), wso = root.querySelector('#wso'), ab = root.querySelector('#apply-slip');
            if (ws) { ws.value = perFill; if (wso) wso.textContent = perFill.toFixed(1) + '¢'; }   // pre-fill the knob with the measured number
            if (ab && ws) ab.onclick = () => { ws.value = perFill; ws.dispatchEvent(new Event('input')); };
          }
        }
      } catch (e) { /* demo replay is best-effort; leave the sim-only chart */ }
    })();
    // Road to live: the strategy's own checks, the ones the deploy paths enforce (gatekeeper, realistic
    // paper record, demo record), with progress, what is left and when the counts could be in. How it
    // then reaches real money (the user's own step) is said apart, never as a check that runs by itself.
    // Best-effort and fetched after the page, like the dev curve.
    if (root.querySelector('#road-live-body')) (async () => {
      try {
        const r = await api('/api/strategies/' + s.id + '/live-readiness');
        const lb = root.querySelector('#ladder-body');
        if (lb) lb.innerHTML = ladderLines(s, { canDeploy, demoWhy, road: r });
        const p = r.paper, c = p.checks;
        const rows = [
          { name: 'Gatekeeper cleared', threshold: 'holdout + diversification', ok: r.deployment_candidate, value: r.deployment_candidate ? 'yes' : 'no' },
          { name: 'Realistic paper trades', threshold: p.trades_needed + '+', ok: c.realistic_trades, value: p.trades + ' / ' + p.trades_needed },
          ...(c.legacy_pnl === false ? [{ name: 'Paper P&L, every fill', threshold: '$0 or above', ok: false, value: p.legacy_pnl }] : []),
          { name: 'Net after fees', threshold: 'above $0', ok: c.net_pnl, value: p.net_pnl },
          { name: 'Separate events', threshold: (p.events_needed || 20) + '+', ok: c.events, value: p.events == null ? '—' : p.events + ' / ' + (p.events_needed || 20) },
          { name: 'First to last paper trade', threshold: p.span_needed_hours + 'h+', ok: c.span, value: Math.round(p.span_hours) + 'h / ' + p.span_needed_hours + 'h' },
          { name: 'Edge is not luck', threshold: 'p ≤ ' + p.p_value_needed.toFixed(2), ok: c.edge, value: roadP(p.p_value) },
          { name: 'Still working lately', threshold: 'newer half above $0', ok: c.recent, value: p.recent_trades ? p.recent_net_pnl : '—' },
          { name: 'Clean demo record', threshold: (p.demo_orders_needed || 20) + '+ demo orders, book matches', ok: c.demo, value: p.demo_orders == null ? '—' : p.demo_orders + ' / ' + p.demo_orders_needed },
        ];
        const auto = r.live_autopilot && r.live_autopilot.ok;
        const body = root.querySelector('#road-live-body');
        if (body) body.innerHTML = roadSummary(r, s, liveWhy, rows.length) + gatesHtml(rows)
          + (p.realization != null ? `<p class="hint" style="margin-top:6px;font-variant-numeric:tabular-nums">${p.realization < 0 ? 'Paper is <b>losing money</b> per trade, while the backtest made money on unseen data.' : `Paper earns <b>${Math.round(p.realization * 100)}%</b> of the backtest's unseen-data P&amp;L per trade.`}</p>` : '')
          + `<p class="hint" style="margin-top:6px">Paper counts only fills simulated against the live order book. Clearing every check never starts real money by itself: you deploy it with live money and type LIVE${auto ? ', or live autopilot, which you turned on, may do it within your caps' : ''}. Live trading on this server: ${S.me.live_trading_available ? 'open' : 'not open yet'}. Your Kalshi key: ${S.me.kalshi_connected ? 'connected' : 'not connected'}.</p>`;
      } catch (e) {
        const body = root.querySelector('#road-live-body');
        if (body) body.innerHTML = '<p class="hint">Live readiness is unavailable right now.</p>';
      }
    })();
    for (const [sel, fl] of [['#dep-paper', '#depflash'], ['#dep-paper-quick', '#depflash-quick']]) {
      const depPaper = root.querySelector(sel);
      if (depPaper) depPaper.onclick = () => busy(depPaper, async () => {
        try { await api('/api/deployments', { strategy_id: s.id, mode: 'paper' }); S.deployed = { mode: 'paper', title: s.title }; go('/deploy'); } catch (e) { flash(fl, e.message, 'bad'); }
      });
    }
    const depDemo = root.querySelector('#dep-demo');
    if (depDemo) depDemo.onclick = () => { if (demoWhy) return; busy(depDemo, async () => {
      try { await api('/api/deployments', { strategy_id: s.id, mode: 'demo' }); S.deployed = { mode: 'demo', title: s.title }; go('/deploy'); } catch (e) { flash('#depflash', e.message, 'bad'); }
    }); };
    const stopDep = root.querySelector('#stop-dep');
    if (stopDep) stopDep.onclick = () => armed(stopDep, 'Confirm stop', () => busy(stopDep, async () => {
      try { for (const d of activeDeps) await api(`/api/deployments/${d.id}/stop`, {}); } catch (e) { flash('#delflash', e.message, 'bad'); return; }
      // Stopped. The page re-reads to show it; a re-read that fails says the stop landed, not the error.
      const gen = S.gen;
      if (await refreshed(viewStrategy(s.id))) { depActed(null, 'stop'); return; }
      if (gen !== S.gen) return;
      shell('/strategies', boardTitle('Strategy'), `<div class="load-fail">${notice(DEP_DONE.stop + BEHIND, 'good')}<button type="button" class="btn sm" data-retry>Reload</button></div>`);
      root.querySelector('[data-retry]').onclick = () => render();
      announce(DEP_DONE.stop + BEHIND);
    }));
    const delStrat = root.querySelector('#del-strat');
    if (delStrat) delStrat.onclick = () => {
      if (activeDeps.length) { flash('#delflash', 'Stop its deployment first (button above).', 'bad'); return; }
      if (delBlock) { flash('#delflash', delBlock, 'bad'); return; }
      armed(delStrat, 'Confirm delete', () => busy(delStrat, async () => {
        try { await api(`/api/strategies/${s.id}/delete`, {}); go('/strategies'); } catch (e) { flash('#delflash', e.message, 'bad'); }
      }));
    };
    const shareForm = root.querySelector('#share-form');
    if (shareForm) shareForm.onsubmit = (e) => {
      e.preventDefault();
      const email = root.querySelector('#share-email').value.trim();
      if (!email) { flash('#shareflash', 'Enter an email first.', 'bad'); return; }
      busy(shareForm.querySelector('button'), async () => {
        try {
          const r = await api(`/api/strategies/${s.id}/share`, { email });
          root.querySelector('#share-email').value = '';
          flash('#shareflash', r.already ? 'They already have this strategy.' : 'Shared — they’ll see it in their inventory.', 'good');
        } catch (err) { flash('#shareflash', err.message, 'bad'); }
      });
    };
    const depLive = root.querySelector('#dep-live');
    if (depLive) depLive.onclick = () => { if (!liveWhy) { const f = root.querySelector('#live-confirm'); f.hidden = false; if (f.confirm && f.confirm.focus) f.confirm.focus(); } };
    const lc = root.querySelector('#live-confirm');
    if (lc) lc.onsubmit = (e) => {
      e.preventDefault();
      busy(lc.querySelector('button'), async () => {
        try { await api('/api/deployments', { strategy_id: s.id, mode: 'live', confirm: lc.confirm.value.trim() }); go('/deploy'); } catch (err) { flash('#depflash', err.message, 'bad'); }
      });
    };
    const wi = root.querySelector('#whatif');
    if (wi) {
      let t = null, seq = 0;
      const update = () => {
        // A strategy stored without sizing (stake null) has no stake dial: the re-run keeps its own sizing.
        const wk = wi.querySelector('#wk');
        const fee = +wi.querySelector('#wf').value, slip = +wi.querySelector('#ws').value, stake = wk ? +wk.value : s.stake;
        wi.querySelector('#wfo').textContent = fee.toFixed(2).replace(/0$/, '') + '×';
        wi.querySelector('#wso').textContent = slip.toFixed(1) + '¢';
        if (wk) wi.querySelector('#wko').textContent = '$' + stake;
        clearTimeout(t);
        t = setTimeout(async () => {
          const mine = ++seq;
          root.querySelector('#sheet-results').style.opacity = '.55';
          try {
            const r = await api(`/api/strategies/${s.id}/whatif`, { fee_multiplier: fee, slippage_cents: slip, ...(wk ? { stake } : {}) });
            if (mine !== seq) return;
            root.querySelector('#sheet-results').innerHTML = equityChart(r.equity, s.dataset && s.dataset.out_of_sample_from, null, { width: chartWidth() }) +
              `<div class="split"><div><h4>Tested on (in-sample)</h4>${metricRows(r.in_sample)}</div><div><h4>Never seen (out-of-sample)</h4>${metricRows(r.out_of_sample)}</div></div>`;
            root.querySelector('#gates').innerHTML = gatesHtml(r.gates);
            root.querySelector('#figs').innerHTML = figsFor({ ...r });
            wi.querySelector('#wflash').innerHTML = (fee === 1 && slip === 0 && stake === s.stake) ? '' : notice(r.passed ? 'Still passes every gate under these conditions.' : 'Would fail at least one gate under these conditions.', r.passed ? 'good' : 'bad');
          } catch (e) { wi.querySelector('#wflash').innerHTML = notice(e.message, 'bad'); }
          root.querySelector('#sheet-results').style.opacity = '';
        }, 250);
      };
      wi.querySelectorAll('input[type=range]').forEach((r) => (r.oninput = update));
    }
  }

  // ---------- deploy + chat ----------
  const deployedNote = (n) => `Deployed on ${n.mode}: ${n.title}. It trades only when its rule fires, ${n.mode === 'demo' ? 'on Kalshi’s demo exchange with no real money' : 'against live prices with paper money'}, so the first trade can take a while. Its trades show up here and on your dashboard.`;
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
    const loadBoard = async () => {
      const got = await api('/api/deployments' + (kept && kept.v ? '?v=' + encodeURIComponent(kept.v) : ''));
      const d = withUnrealized(pollAnswer(kept, got));
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
        return ` ·\u00a0${usd(b.removed, true)} from ${num(b.removed_deployments)} removed deployment${b.removed_deployments === 1 ? '' : 's'}${b.all != null ? `, ${usd(b.all, true)} in all` : ''}`;
      };
      const listedLab = (lab, xs) => (xs.length ? `${lab}, deployments listed below` : lab);
      const byMode = (m) => d.deployments.filter((x) => x.mode === m);
      const liveDeps = byMode('live'), paperDeps = byMode('paper'), demoDeps = byMode('demo');
      const liveRealized = listed('live', liveDeps), paperRealized = listed('paper', paperDeps), demoRealized = listed('demo', demoDeps);
      const live = d.deployments.filter((x) => x.mode === 'live' && x.status === 'running');
      const runDemo = running.some((x) => x.mode === 'demo'), runPaper = running.some((x) => x.mode === 'paper');
      // Open positions per book, never one count across books. A book with none is left out, except
      // live while live trading is on (or a live deployment is listed), so "0 live" reads as a fact. A
      // no-break space keeps each "3 paper" whole when the figure wraps on a phone.
      const liveOn = !!(S.me && S.me.live_trading_available) || liveDeps.length > 0;
      const openSplit = ['paper', 'demo', 'live'].map((m) => [m, d.open_positions.filter((p) => (p.mode || 'paper') === m).length])
        .filter(([m, n]) => n || (m === 'live' && liveOn)).map(([m, n]) => `${num(n)}\u00a0${m}`).join(' ·\u00a0') || 'None';
      paint(root.querySelector('#dfigs'), fig('Running', running.length, { small: `${d.deployments.length - running.length} paused` }) +
        (liveDeps.length
          ? fig(listedLab('Live realized', liveDeps), usd(liveRealized, true), { v: liveRealized, small: `real money${removedNote('live')}${paperDeps.length ? ` ·\u00a0${usd(paperRealized, true)} on paper from the deployments listed, counted apart` : ''}` })
          : paperDeps.length || !demoDeps.length ? fig(listedLab('Realized', paperDeps), usd(paperRealized, true), { v: paperRealized, small: `paper money, not real${removedNote('paper')}` }) : '') +
        (demoDeps.length ? fig(listedLab('Demo realized', demoDeps), usd(demoRealized, true), { v: demoRealized, small: `${DEMO_WHAT}${removedNote('demo')}` }) : '') +
        fig('Open positions', openSplit) +
        fig('Money', live.length ? '<span class="mk live">Live</span>' : runDemo ? `${runPaper ? '<span class="mk">Paper</span> ' : ''}<span class="mk dep">Demo</span>` : '<span class="mk">Paper</span>', { small: live.length ? `${live.length} on live money` : 'nothing on live money' }));
      const regs = curveRegs(d.deployments);
      paint(root.querySelector('#deps'), d.deployments.length ? deploymentTable(pausedFirst(d.deployments).map((x) => deploymentSlip(x, regs, true)).join(''), true)
        : `<div class="empty"><h3>Nothing deployed</h3><p>${passedN === 0 ? 'Nothing has passed yet. A strategy goes on the board once it passes every test in a research session, paper first.' : 'Open a passed strategy and post it to the board. Paper first: it trades the live market with paper money.'}</p>${S.me && S.me.user && S.me.user.autopilot ? '<p>Autopilot is on: strategies that pass every research test deploy here on their own, on paper.</p>' : ''}${apNudge('Rather not pick strategies yourself?', 'and it deploys the ones that pass, on paper.')}${passedN === 0 ? '<a class="btn" href="/research?new=1">Start a research session</a>' : '<a class="btn" href="/strategies">See passed strategies</a>'}</div>`);
      paint(root.querySelector('#demo-health'), d.demo_health ? `<div class="notice bad" role="status">${ICON.warn}<span>${demoHealthLine(d.demo_health)}</span></div>` : '');
      bindDeploymentActions(root.querySelector('#deps'), loadBoard);
      paint(root.querySelector('#openpos'), d.open_positions.length ? `<table class="table stack"><thead><tr><th>Strategy</th><th>Contract</th><th>Side</th><th class="num">Cost + fee</th><th class="num">Unreal.</th><th class="num">Settles</th></tr></thead><tbody>
        ${d.open_positions.map((p) => `<tr><td class="name" data-lab="Strategy">${esc(p.title)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : p.mode === 'demo' ? '<span class="mk dep">Demo</span>' : ''}</td><td class="tick" data-lab="Contract">${contractLink(p.ticker)}${contractMarket(p.ticker) ? `<div class="sub-fig pos-mkt">${esc(contractMarket(p.ticker))}</div>` : ''}${p.why ? `<div class="sub-fig pos-why">${esc(p.why)}</div>` : ''}</td><td data-lab="Side">${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(+p.entry_price)}</td><td class="num" data-lab="Cost + fee">${usd(p.qty * p.entry_price + +p.entry_fee)}</td><td class="num" data-lab="Unrealized">${p.unrealized == null ? '—' : money(p.unrealized)}</td><td class="num" data-lab="Settles">${settleAt(p.market_close_time)}</td></tr>`).join('')}</tbody></table>`
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
  const trDay = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—');
  const trMonth = (k) => { const [y, m] = k.split('-'); return new Date(Date.UTC(+y, +m - 1, 15)).toLocaleDateString(undefined, { year: 'numeric', month: 'short', timeZone: 'UTC' }); };
  const trCi = (ci, f) => (ci ? `95%: ${f(ci[0])} to ${f(ci[1])}` : 'needs 2+ trades for a range');
  const TR_STATUS = { paused: 'Paused', stopped: 'Stopped' };
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
  function trackRecordPanel(m, key, th) {
    const caveats = [];
    if (m.excluded_instant_fills) caveats.push(`${num(m.excluded_instant_fills)} instant-fill paper trade${m.excluded_instant_fills === 1 ? '' : 's'} left out (fills real execution would not get).`);
    if (m.open_trades) caveats.push(`${num(m.open_trades)} open trade${m.open_trades === 1 ? '' : 's'} (${usd(m.open_at_cost)} at cost) ${m.open_trades === 1 ? 'joins the record when it closes' : 'join the record when they close'}.`
      // A part-sold trade's sold slice is realized (the dashboard counts it) but waits here for the rest.
      + (m.open_realized_pnl ? ` Part of ${m.open_trades === 1 ? 'it' : 'them'} is already sold: ${usd(m.open_realized_pnl, true)} realized, not yet in these figures.` : ''));
    if (key === 'live' && m.trades) caveats.push('Live results count only the trades Tau placed, net of Kalshi fees. Your Kalshi cash also moves with deposits, withdrawals and anything you trade yourself.');
    if (key === 'demo' && m.trades) caveats.push('Demo trades are real fills on Kalshi’s sandbox exchange with simulated money. Reloading the demo account doesn’t reset this record, so it can differ from P&L since reload.');
    const cav = caveats.length ? `<p class="hint tr-caveat">${caveats.map(esc).join(' ')}</p>` : '';
    if (!m.trades) {
      // Paper only: the live and demo tabs keep their own copy.
      const apOn = key === 'paper' && !!(S.me && S.me.user && S.me.user.autopilot);
      const how = key === 'live' ? 'Deploy a strategy that has proven itself on paper to live money, and its closed trades show up here.'
        : key === 'demo' ? 'Deploy a strategy to the Kalshi demo exchange to build a record with real fills and no real money.'
        : apOn ? 'Autopilot runs the strategies that pass every research test on paper, with pretend money. Every closed trade is recorded here.'
        : 'Deploy a passed strategy on paper. Every closed trade is recorded here.';
      // With nothing deployed (the dashboard's board says so), Deploy is an empty board too and sent a
      // new user Deploy → Strategies → Research; the button goes straight to the step that comes first.
      const first = key === 'paper' && !apOn && S.dashDeps === 0;
      // Nothing deployed yet: the dashboard's autopilot card above already offers the switch, so the
      // record doesn't offer it a second time.
      const go = apOn ? '<a class="btn" href="/research">See its research</a>'
        : first ? (S.dashNoSessions ? '<a class="btn" href="/research?new=1">Start a research session</a>' : '<a class="btn" href="/strategies">See passed strategies</a>')
        : '<a class="btn" href="/deploy">Go to Deploy</a>';
      // Instant-fill paper trades are closed but left out (caveat below): "No closed paper trades" denied
      // trades the user can see on Deploy, so the heading says none count yet instead.
      const none = m.excluded_instant_fills ? `No ${esc(m.label.toLowerCase())} trades in the record yet` : `No closed ${esc(m.label.toLowerCase())} trades yet`;
      return `<div class="empty"><h3>${none}</h3><p>${how}</p>${key === 'paper' && !first ? apNudge('Rather not pick strategies yourself?', 'and it runs the ones that pass on paper. Their trades fill this record.') : ''}${go}</div>${cav}`;
    }
    const s = m.sample;
    const good = s.level === 'solid' && s.edge === 'positive';
    const figs = `<dl class="figures measure tr-figs">
      ${fig(`${trBook(key)} net P&amp;L`, usd(m.net_pnl, true), { v: m.net_pnl, cls: 'lead', small: `after ${usd(m.fees)} in fees${m.first_trade_at ? ` \u00b7\u00a0since ${trDay(m.first_trade_at)}` : ''}` })}
      ${fig('Return', pct(m.return), { v: m.return, small: `on ${usd(m.capital)} capital required${m.annualized_return != null ? ` ·\u00a0${pct(m.annualized_return)} a year` : ''}` })}
      ${fig('Max drawdown', m.max_drawdown ? usd(-m.max_drawdown) : usd(0), { small: m.max_drawdown_pct != null ? `${pct(m.max_drawdown_pct, false)} of capital` : '' })}
      ${fig('Sharpe', trFix(m.sharpe), { small: m.sharpe == null ? `shown after ${th.min_sharpe_days} days` : `PSR ${pct(m.psr, false)} ·\u00a0Sortino ${trFix(m.sortino)}` })}
      ${fig('Win rate', pct(m.win_rate, false), { small: trCi(m.win_rate_ci, (v) => pct(v, false)) })}
      ${fig('Trades', num(m.trades), { small: `${num(m.wins)} won ·\u00a0${num(m.losses)} lost` })}
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
      const [tag, cls] = TR_EDGE[r.edge] || TR_EDGE.unclear;
      // A stopped or removed strategy stays in the table (and every figure); it says so instead of
      // reading like one still trading. A removed one has no page left to link to.
      const st = r.removed ? `${r.market ? `${esc(marketShort(r.market))} ·\u00a0` : ''}stopped, then removed` : TR_STATUS[r.status];
      return `<tr><td class="name" data-lab="Strategy">${r.removed ? esc(r.title) : `<a href="/strategies/${+r.strategy_id}">${esc(r.title)}</a>`}${st ? `<div class="sub-fig">${st}</div>` : ''}</td>
        <td data-lab="Read"><span class="mk ${cls}">${tag}</span></td>
        <td class="num" data-lab="Trades">${num(r.trades)}${r.open_trades ? ` <span class="sub-fig">+${num(r.open_trades)} open</span>` : ''}</td>
        <td class="num" data-lab="Net P&amp;L">${money(r.net_pnl)}</td>
        <td class="num" data-lab="Win rate">${pct(r.win_rate, false)}</td>
        <td class="num" data-lab="Avg trade">${usd(r.avg_trade, true)}</td>
        <td class="num" data-lab="Max drawdown">${r.max_drawdown ? usd(-r.max_drawdown) : usd(0)}</td>
        <td class="num" data-lab="Last trade">${trDay(r.last_trade_at)}</td></tr>`;
    }).join('');
    return `${notice(s.text, good ? 'good' : '')}${cav}${figs}
      <div class="rp-figs">
        <div class="rp-fig wide"><h5>Equity curve</h5>${equityChart(trCurve(m.curve), null, null, { width: chartWidth() })}<div class="cap">${trCurveCap(m)}</div></div>
        <div class="rp-fig"><h5>Drawdown (underwater)</h5>${rpUnderwater(trCurve(m.curve), m.underwater && trCurve(m.underwater))}</div>
        <div class="rp-fig"><h5>Risk and trade detail</h5>${risk}</div>
      </div>
      <section class="section"><div class="section-head"><h2>By month</h2><p>UTC calendar months</p></div>
        <div class="sheet"><table class="table stack"><thead><tr><th>Month</th><th class="num">Net P&amp;L</th><th class="num">Trades</th><th class="num">Win rate</th></tr></thead><tbody>${months}</tbody></table></div></section>
      <section class="section"><div class="section-head"><h2>By strategy</h2><p>Stopped ones included ·\u00a0“Too few” means under ${th.min_trades} trades</p></div>
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
    host.innerHTML = `<div class="section-head"><h2>Track record</h2><p>Realized results from closed trades. Nothing here is a backtest.</p></div>
      <div class="chips tr-tabs" role="group" aria-label="Money type">
        ${TR_MODES.map(([k, label]) => `<button class="chip" type="button" data-trtab="${k}" aria-pressed="${k === tab}">${label} ·\u00a0${num(d.modes[k].trades)}</button>`).join('')}
      </div>
      <div class="trpanel"></div>
      <details class="tr-method"><summary>How these numbers are computed</summary>
        <ul>${d.method.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>
        <p class="hint">Updated ${esc(clock(new Date(d.generated_at * 1000).toISOString()))}. Past results do not predict future returns.</p></details>`;
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
    const gen = S.gen, mainEl = root.querySelector('main'), wrap = mainEl && mainEl.parentNode;
    if (!wrap || !wrap.appendChild) return;
    const host = document.createElement('section');
    host.className = 'sect dash-track'; host.id = 'track-record'; host.innerHTML = loading(260);
    wrap.appendChild(host);  // after <main>, its last child, so the board's repaint never touches it
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
      poll(() => mountTrackRecord(host, last), 60000);
    };
    await first();
  }

  // ---------- funds ----------
  // ---------- Kalshi keys (Funds) ----------
  // Where each key comes from. Kalshi's demo is its own site, with its own login and play money, and a
  // key only works on the site that made it, so each box names its site and links its key page.
  const KALSHI_KEYS = {
    live: { site: 'kalshi.com', keys: 'https://kalshi.com/account/profile' },
    demo: { site: 'demo.kalshi.co', keys: 'https://demo.kalshi.co/account/profile', join: 'https://demo.kalshi.co/' },
    guide: 'https://docs.kalshi.com/getting_started/api_keys',
  };
  const extLink = (href, text) => `<a href="${href}" target="_blank" rel="noopener">${text}</a>`;
  function keySteps(kind) {
    const k = KALSHI_KEYS[kind], demo = kind === 'demo';
    const open = demo
      ? `<li>Kalshi’s demo is a separate site with its own login and play money. ${extLink(k.join, 'Sign up or sign in at demo.kalshi.co')} (free).</li><li>There, open ${extLink(k.keys, 'your demo profile')}, find API Keys and click Create New API Key.</li>`
      : `<li>On Kalshi, open ${extLink(k.keys, 'your profile')}, find API Keys and click Create New API Key.</li>`;
    return `<ol class="steps key-steps">${open}<li>Kalshi shows a <b>Key ID</b> (like <span class="nobr">a952bcbe-ec3b-…</span>) and downloads a <b>private key</b> file (.key), once. Keep the file; if it’s lost, make a new key.</li><li>Paste the Key ID below and choose the .key file (or paste its text). We check it with ${demo ? 'the demo exchange' : 'Kalshi'}, then store it encrypted; it is never shown again.</li></ol>
      <p class="hint key-diff">${demo ? 'A demo key trades play money on Kalshi’s sandbox. A real-money key from kalshi.com won’t work here.' : 'A live key trades your real money. A key made on demo.kalshi.co won’t work here: add it under Demo key.'} ${extLink(KALSHI_KEYS.guide, 'Kalshi’s guide to API keys')}</p>`;
  }
  // Plain words for the usual mix-ups, before anything is sent. Fixed text only: it never echoes the key.
  function keyProblem(kid, pem, kind) {
    kid = String(kid || '').trim(); pem = String(pem || '').trim();
    const where = kind === 'demo' ? 'the API keys page on demo.kalshi.co' : 'the API keys page on kalshi.com';
    if (/PRIVATE KEY|PUBLIC KEY/.test(kid) || kid.length > 128) return 'That’s the key file’s text; it goes in the Private key box. The Key ID is the short code shown next to the key on Kalshi, like a952bcbe-ec3b-….';
    if (!kid) return `Paste the Key ID: the short code shown next to the key on ${where}.`;
    if (!pem) return 'Paste the private key, or choose the .key file Kalshi downloaded.';
    if (/^[0-9a-f]{8}-[0-9a-f-]{8,}$/i.test(pem)) return 'That looks like the Key ID; it goes in the Key ID box. The private key is the .key file Kalshi downloaded.';
    if (/PUBLIC KEY/.test(pem)) return 'That’s a public key. Tau needs the private key: the .key file Kalshi downloaded when you created the key.';
    if (!/-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(pem)) return 'That isn’t a private key. Paste the whole .key file Kalshi downloaded, from its -----BEGIN line to its -----END line, or choose the file.';
    if (!/-----END [A-Z ]*PRIVATE KEY-----/.test(pem)) return 'That private key is cut off: it should end with an -----END … PRIVATE KEY----- line. Choose the .key file instead of copying it.';
    return '';
  }
  // How you know it worked: the existing balance read, right under the panel title. No balance means Kalshi
  // didn't answer for this key just now (Kalshi down, or the key deleted there), so it gets no check mark.
  // `at` is when the balance memo was read (the server's balance_at), so the line says how old it is.
  const keyOk = (bal, kind, at) => bal == null
    ? `<p class="key-ok key-unread"><b>Key saved</b> (Kalshi didn’t send a balance for it just now)</p><p class="hint key-diff">If this lasts, the key may have been deleted on ${KALSHI_KEYS[kind === 'demo' ? 'demo' : 'live'].site}: ${kind === 'demo' ? 'remove it' : 'disconnect it'} and connect a new one.</p>`
    : `<p class="key-ok"><b>Connected ✓</b> (balance ${usd(bal)}${at ? ', read ' + when(at) : ''})${kind === 'demo' ? ' <span class="hint">in your Kalshi demo account</span>' : ''}</p>`;
  // Kalshi refuses orders from a demo account with no cash, and a new one starts empty. Tau's demo balance is
  // Tau's own figure, so a $0.00 here would otherwise read as harmless.
  // `from` is the demo cash the autopilot's demo copies wait for (server: demo_twins), so a balance
  // under it says why no copy starts, not only an empty one.
  const demoEmpty = (bal, from) => bal == null ? '' : bal < 0.005 ? `<div class="notice" role="status">${ICON.warn}<span>Your Kalshi demo account has $0.00, so Kalshi refuses demo orders. Add demo funds in your account on ${extLink(KALSHI_KEYS.demo.join, 'demo.kalshi.co')} (play money, not real). Tau’s demo balance above is Tau’s own figure and doesn’t fund it.</span></div>`
    : from && bal < from ? `<div class="notice" role="status">${ICON.warn}<span>Your Kalshi demo account has ${usd(bal)}. Demo copies of your paper strategies start once it holds ${usd(from)}: add play money in your account on ${extLink(KALSHI_KEYS.demo.join, 'demo.kalshi.co')} (not real). Tau’s demo balance above is Tau’s own figure and doesn’t fund it.</span></div>` : '';

  // Each Funds figure says what it leaves out: a book's open positions, by count and cost (contracts x entry,
  // the dashboard's "at cost"). An API without the counts says nothing rather than "0 open".
  const openAt = (b) => b.open_positions ? `${b.open_positions} open (${usd(b.open_at_cost)} at cost) ·\u00a0` : '';
  const openLeft = (b, mode) => b.open_positions == null ? 'Open positions not included'
    : b.open_positions ? `${b.open_positions} open ${mode} position${b.open_positions === 1 ? '' : 's'} (${usd(b.open_at_cost)} at cost) not included` : `No open ${mode} positions`;
  // What each book has made: its realized P&L from closed trades, the figure the dashboard, Deploy and the
  // track record show, never added to another book's. Before a book's first close it says when one shows.
  // An API without the figure says nothing. Demo's is since its last reload, as on the dashboard.
  const bookPnl = (b, mode, pnl = b.realized_pnl, span = 'all time') => b.closed_trades == null ? ''
    : b.closed_trades ? `${usd(pnl, true)} realized ${span} \u00b7\u00a0` : `P&amp;L shows once a ${mode} trade closes \u00b7\u00a0`;
  const livePnl = (k) => k.closed_trades == null ? '' : k.closed_trades ? ` Tau\u2019s live trades: ${usd(k.realized_pnl, true)} realized all time.`
    : k.connected ? ' Tau\u2019s live P&amp;L shows once a live trade closes.' : '';
  const KALSHI_UNREAD = 'Kalshi didn\u2019t answer just now. Reload in a minute to try again.';
  // A paper history line in plain words. The engine writes prices as dollars ("@ 0.40") and exit reasons as
  // codes ("stop_loss"); a settled row's $0.00 read as nothing happening when the contract lost. Display only:
  // the stored memo and the amount are unchanged.
  const ledgerWhat = (r) => {
    const memo = String(r.memo || r.kind || '').replace(/ (@|->) (\d*\.\d+)/g, (m, w, p) => ` ${w === '@' ? 'at' : '\u2192'} ${Math.round(+p * 100)}\u00a2`)
      .replace(/\(([a-z]+(?:_[a-z]+)+)/g, (m, c) => '(' + c.replace(/_/g, ' '));
    const settled = r.kind === 'settlement' ? (+r.amount > 0 ? ' \u00b7\u00a0won, paid $1 a contract' : ' \u00b7\u00a0lost, paid $0') : '';
    return esc(memo) + (settled ? `<span class="hint">${settled}</span>` : '');
  };
  // Fees and settlement, once, in plain words, where the cash moves.
  const LEDGER_HOW = 'Cash in and out of your paper account, newest first. A buy takes the contracts\u2019 price plus Kalshi\u2019s fee, as a real order would. When a market settles, each winning contract pays $1 and each losing one pays $0; a sale before then pays the price it sold at, less the fee. A trade\u2019s P&amp;L is what it brought back less everything it cost, fees included.';
  async function viewFunds() {
    const gen = S.gen;
    shell('/funds', boardTitle('Funds') + '<dl class="figures measure" id="ffigs" style="margin-top:14px"></dl>', loading(300));
    root.querySelector('.wrap').classList.add('funds-page');
    const load = async () => {
      const d = await api('/api/funds');
      if (gen !== S.gen) return;
      const k = d.kalshi;
      const kd = d.kalshi_dev || { connected: false };
      const dm = d.demo || { capital: 0, equity: 0, realized: 0 };
      root.querySelector('#ffigs').innerHTML = fig('Kalshi cash', k.connected ? (k.balance == null ? 'Unavailable' : usd(k.balance)) : 'Not connected', { cls: 'lead', small: !k.connected ? 'Connect a key to trade real money' + (livePnl(k) ? '.' + livePnl(k) : '') : k.balance == null ? KALSHI_UNREAD + livePnl(k) : `Your real cash at Kalshi${k.balance_at ? ', read ' + when(k.balance_at) : ''}.${livePnl(k)} ${openLeft(k, 'live')}` }) +
        fig('Demo balance', usd(dm.equity), { small: `${usd(dm.capital)} capital ·\u00a0${openAt(dm)}${bookPnl(dm, 'demo', dm.realized, demoSpan(dm))}${kd.connected ? '' : 'needs a demo key ·\u00a0'}${DEMO_WHAT}` }) +
        fig('Paper balance', usd(d.paper.equity == null ? d.paper.cash : d.paper.equity), { small: `${usd(d.paper.cash)} cash ·\u00a0${openAt(d.paper)}${bookPnl(d.paper, 'paper')}practice money` });
      root.querySelector('main').innerHTML = `<div id="flash"></div><div class="funds">
        <div class="funds-col funds-manage">
        <section class="panel">
          <h3>Kalshi account (live money)</h3>
          ${k.connected ? `
            ${keyOk(k.balance, 'live', k.balance_at)}<dl class="kv"><dt>API key</dt><dd>${esc(k.key_id)}</dd><dt>Cash at Kalshi</dt><dd>${k.balance == null ? 'Couldn’t read it just now' : usd(k.balance)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">This is your real Kalshi balance. Deposits and withdrawals happen at Kalshi, in your own account — we never hold your money. Tau only places trades for strategies you deploy live. To use a different key, disconnect this one and connect the new one.</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <a class="btn" href="${esc(k.funding_url)}" target="_blank" rel="noopener">Deposit or withdraw at Kalshi ${ICON.ext}</a>
              <button class="btn danger" id="disconnect">Disconnect</button>
            </div>` : `
            <p class="lede" style="margin-bottom:12px">Live trading runs in your own Kalshi account, so we never hold your money and can’t add it for you. Connect an API key to see your real balance and trade real money.</p>
            ${keySteps('live')}
            <form id="kalshi" style="display:grid;gap:12px">
              <label class="field"><span>Key ID</span><input class="input" name="key_id" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" required placeholder="like a952bcbe-ec3b-4b5b-…"></label>
              <label class="field"><span>Private key</span><textarea class="input" name="private_key" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
              <label class="key-file"><span>Or choose the downloaded key file</span><input type="file" accept=".key,.pem,.txt,text/plain" data-keyfile></label>
              <button class="btn" type="submit">Verify and connect</button>
            </form>`}
          <div id="kflash" style="margin-top:10px"></div>
        </section>
        <section class="panel">
          <h3>Kalshi demo (sandbox) account</h3>
          <dl class="kv"><dt>Demo balance</dt><dd>${usd(dm.equity)}</dd><dt>${dm.before_reload ? 'Capital at last reload' : 'Starting capital'}</dt><dd>${usd(dm.capital)}</dd><dt>P&amp;L ${demoSpan(dm)}</dt><dd class="${tone(dm.realized)}">${usd(dm.realized, true)}</dd></dl>
          <p class="lede" style="margin-bottom:14px">Demo places real orders on Kalshi’s sandbox exchange, to prove the order path before live money. The sandbox book is thin, so its fills and P&amp;L are no evidence of the edge; paper keeps that job. The money is ours to set: reload it to any amount; this never touches your Kalshi demo account’s balance. A reload starts P&amp;L since reload at $0.00; the track record still counts every closed demo trade.</p>
          <form id="demo" class="amount">
            <label class="field"><span>Reload to</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="1000"></label>
            <button class="btn" type="submit">Reload demo</button>
          </form>
          <div id="dmflash" style="margin-top:10px"></div>
          <h3 style="margin-top:24px">Demo key</h3>
          ${kd.connected ? `
            ${keyOk(kd.balance, 'demo', kd.balance_at)}${demoEmpty(kd.balance, kd.copies_from)}<dl class="kv"><dt>Demo key</dt><dd>${esc(kd.key_id)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">Demo deployments trade Kalshi’s sandbox exchange with this key — real order-book fills, no real money. Your demo key is stored separately from your live key and is never used for live trading. To use a different demo key, remove this one and connect the new one.</p>
            <button class="btn danger" id="dev-disconnect">Remove demo key</button>` : `
            <p class="lede" style="margin-bottom:12px">Connect a Kalshi <b>demo</b> API key to deploy strategies on the sandbox exchange: play money, no real money. Demo is the step between paper and live: it proves orders place, fill and book, and live needs a clean demo record. It’s kept separate from your live key.</p>
            ${keySteps('demo')}
            <form id="kalshi-dev" style="display:grid;gap:12px">
              <label class="field"><span>Demo key ID</span><input class="input" name="key_id" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" required placeholder="like a952bcbe-ec3b-4b5b-…"></label>
              <label class="field"><span>Demo private key</span><textarea class="input" name="private_key" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
              <label class="key-file"><span>Or choose the downloaded key file</span><input type="file" accept=".key,.pem,.txt,text/plain" data-keyfile></label>
              <button class="btn" type="submit">Verify and connect demo</button>
            </form>`}
          <div id="kdflash" style="margin-top:10px"></div>
        </section>
        <section class="panel">
          <h3>Paper account (simulation)</h3>
          <p class="lede" style="margin-bottom:14px">App-controlled practice money. Add funds, take some out, or reset to a fresh starting balance. Paper strategies trade the real market with it, so results are realistic, but nothing real is at stake.</p>
          <form id="paper" class="amount">
            <label class="field"><span>Amount</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="500"></label>
            <button class="btn" data-kind="deposit" type="submit">Add</button>
            <button class="btn ghost" data-kind="withdraw" type="submit">Withdraw</button>
            <button class="btn ghost" data-kind="reset" type="submit">Reset to amount</button>
          </form>
          <div id="pflash" style="margin-top:10px"></div>
        </section>
        ${S.me.perps_live_available ? '<section id="kalshi-perps-live" aria-label="Bitcoin perpetual trading"></section>' : ''}
        </div>
        <div class="funds-col funds-history">
        <section class="panel">
          <h3>Paper history</h3>
          <p class="hint ledger-how">${LEDGER_HOW}${d.paper.ledger.length >= 50 ? ' The latest 50 entries.' : ''}</p>
          <table class="table stack t-ledger"><thead><tr><th>When</th><th>What</th><th class="num">Amount</th></tr></thead><tbody>
            ${d.paper.ledger.map((r) => `<tr><td class="hint lead-cell" data-lab="When">${when(r.created_at)}</td><td class="name" data-lab="What">${ledgerWhat(r)}</td><td class="num ${tone(+r.amount)}" data-lab="Amount">${usd(r.amount, true)}</td></tr>`).join('')}
          </tbody></table>
        </section>
        </div></div>`;
      if (S.perps) { S.perps.destroy(); S.perps = null; }
      const perpsHost = root.querySelector('#kalshi-perps-live');
      if (window.TAU_PERPS_LIVE && perpsHost) S.perps = window.TAU_PERPS_LIVE.mount(perpsHost, {api, proposalId: new URLSearchParams(location.search).get('perps_proposal')});
      const df = root.querySelector('#demo');
      if (df) df.onsubmit = async (e) => {
        e.preventDefault();
        await holdFocus(null, () => busy(df.querySelector('button'), async () => {
          try { await api('/api/funds/demo', { amount: +df.amount.value }); const fresh = await refreshed(load()); flash('#dmflash', 'Demo account reloaded.' + (fresh ? '' : BEHIND), 'good'); } catch (err) { flash('#dmflash', err.message, 'bad'); }
        }));
      };
      const pf = root.querySelector('#paper');
      let kind = 'deposit';
      pf.querySelectorAll('button').forEach((b) => (b.onclick = () => (kind = b.dataset.kind)));
      // Each button names the amount it will move, so "Reset to" never reads as a dangling label.
      const PAPER_VERB = { deposit: 'Add', withdraw: 'Withdraw', reset: 'Reset to' };
      const amt = pf.querySelector('input[name=amount]');
      const syncPaper = () => {
        const v = +amt.value;
        pf.querySelectorAll('button').forEach((b) => { b.textContent = v > 0 ? `${PAPER_VERB[b.dataset.kind]} ${usd(v)}` : b.dataset.kind === 'reset' ? 'Reset to amount' : PAPER_VERB[b.dataset.kind]; });
      };
      amt.addEventListener('input', syncPaper);
      pf.onsubmit = async (e) => {
        e.preventDefault();
        // Reset wipes the paper ledger and history, so it asks first; Add and Withdraw go at once.
        const k = kind, btn = pf.querySelector(`[data-kind="${k}"]`);
        const run = () => holdFocus(null, () => busy(btn, async () => {
          try { await api('/api/funds/paper', { kind: k, amount: +pf.amount.value }); const fresh = await refreshed(load()); flash('#pflash', (k === 'deposit' ? 'Added to your paper account.' : k === 'withdraw' ? 'Withdrawn from your paper account.' : 'Paper account reset.') + (fresh ? '' : BEHIND), 'good'); } catch (err) { flash('#pflash', err.message, 'bad'); }
        }));
        return k === 'reset' ? armed(btn, 'Confirm reset', run) : run();
      };
      // The downloaded .key file fills the box, so nobody has to open it in an editor (hard on a phone).
      root.querySelectorAll('[data-keyfile]').forEach((inp) => (inp.onchange = async () => {
        const f = inp.files && inp.files[0], box = inp.form && inp.form.private_key;
        if (!f || !box) return;
        const text = f.size <= 20000 ? (await f.text()).trim() : '';
        const where = inp.form.id === 'kalshi' ? '#kflash' : '#kdflash';
        if (!/-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(text)) { inp.value = ''; flash(where, 'That file doesn\u2019t look like a private key. Choose the .key file Kalshi downloaded.', 'bad'); return; }
        box.value = text;
        const fl = root.querySelector(where); if (fl) fl.innerHTML = '';
      }));
      const kf = root.querySelector('#kalshi');
      if (kf) kf.onsubmit = async (e) => {
        e.preventDefault();
        const bad = keyProblem(kf.key_id.value, kf.private_key.value, 'live');
        if (bad) { flash('#kflash', bad, 'bad'); return; }
        await holdFocus('#disconnect', () => busy(kf.querySelector('button'), async () => {
          try { const r = await api('/api/kalshi-key', { key_id: kf.key_id.value, private_key: kf.private_key.value }); S.me.kalshi_connected = true; const fresh = await refreshed(load()); flash('#kflash', (r && r.balance != null ? `Connected ✓ (balance ${usd(r.balance)}). Kalshi confirmed the key.` : 'Connected ✓. Kalshi confirmed the key.') + (fresh ? '' : BEHIND), 'good'); } catch (err) { flash('#kflash', err.message, 'bad'); }
        }));
      };
      const dc = root.querySelector('#disconnect');
      if (dc) dc.onclick = () => armed(dc, 'Confirm disconnect', () => holdFocus('#kalshi [name="key_id"]', () => busy(dc, async () => {
        try { await api('/api/kalshi-key/delete', {}); S.me.kalshi_connected = false; const fresh = await refreshed(load()); flash('#kflash', 'Disconnected. Tau deleted its copy of the key; the key itself stays valid until you delete it on kalshi.com.' + (fresh ? '' : BEHIND), 'good'); } catch (err) { flash('#kflash', err.message, 'bad'); }
      })));
      const kdf = root.querySelector('#kalshi-dev');
      if (kdf) kdf.onsubmit = async (e) => {
        e.preventDefault();
        const bad = keyProblem(kdf.key_id.value, kdf.private_key.value, 'demo');
        if (bad) { flash('#kdflash', bad, 'bad'); return; }
        await holdFocus('#dev-disconnect', () => busy(kdf.querySelector('button'), async () => {
          try { await api('/api/kalshi-dev-key', { key_id: kdf.key_id.value, private_key: kdf.private_key.value }); S.me.kalshi_dev_connected = true; let now = null; const fresh = await refreshed(load().then((d) => { now = d; })); const bal = now && now.kalshi_dev && now.kalshi_dev.balance; flash('#kdflash', (bal != null ? `Connected ✓ (balance ${usd(bal)}). Kalshi’s demo exchange confirmed the key.` : 'Connected ✓. Kalshi’s demo exchange confirmed the key.') + (fresh ? '' : BEHIND), 'good'); } catch (err) { flash('#kdflash', err.message, 'bad'); }
        }));
      };
      const dvc = root.querySelector('#dev-disconnect');
      if (dvc) dvc.onclick = () => armed(dvc, 'Confirm remove', () => holdFocus('#kalshi-dev [name="key_id"]', () => busy(dvc, async () => {
        try { await api('/api/kalshi-dev-key/delete', {}); S.me.kalshi_dev_connected = false; const fresh = await refreshed(load()); flash('#kdflash', 'Demo key removed. Tau deleted its copy; delete the key on demo.kalshi.co too if you’re done with it.' + (fresh ? '' : BEHIND), 'good'); } catch (err) { flash('#kdflash', err.message, 'bad'); }
      })));
      return d;
    };
    await load();
  }

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
      const head = `<div class="snap-head"><b>${esc(snap.title)}</b>${mark(snap.status)}${researchBadge(snap)}</div>
        <div class="snap-meta">${esc(marketShort(snap.market))} ·\u00a0backtest on unseen data${overDays(snap.days)}: ${snap.pnl == null ? '—' : usd(snap.pnl, true)}${snap.trades != null ? ' ·\u00a0' + realTrades(snap.trades) : ''}${snap.win_rate != null ? ' ·\u00a0' + pct(snap.win_rate, false) + ' win' : ''}</div>`;
      return owner ? `<div class="snap">${head}<div class="snap-note">Only ${esc(owner)} can open this strategy. Ask them to share a copy from its page.</div></div>`
        : `<a class="snap" href="/strategies/${snap.id}">${head}</a>`;
    }
    if (snap.kind === 'deployment') {
      const book = snap.mode === 'live' ? 'live' : snap.mode === 'demo' ? 'demo' : 'paper';
      return `<div class="snap"><div class="snap-head"><b>${esc(snap.title)}</b>${book === 'live' ? '<span class="mk live">Live</span>' : book === 'demo' ? '<span class="mk dep">Demo</span>' : '<span class="mk">Paper</span>'}</div>
        <div class="snap-meta">${esc(marketShort(snap.market))} ·\u00a0${book} ·\u00a0realized ${usd(snap.realized_pnl, true)}${snap.closed_trades != null ? ' ·\u00a0' + realTrades(snap.closed_trades) : ''}${snap.since ? ' since ' + trDay(Date.parse(snap.since) / 1000) : ''}</div></div>`;
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
        ${grouped ? '' : `<div class="post-head"><b>${authorLine(p.author, p.username)}</b><span class="when">${when(p.created_at)}${p.edited ? ' ·\u00a0edited' : ''}</span></div>`}
        <div class="post-main"><div class="post-body">${mdLite(p.body)}</div>
        ${p.image ? `<a class="post-img" href="${esc(p.image)}" target="_blank" rel="noopener"><img src="${esc(p.image)}" alt="" loading="lazy"></a>` : ''}
        ${postSnapshot(p.snapshot, snapOwner(p))}</div>
        <div class="reactions">${reactionChips(p.reactions)}</div>
        <div class="post-actions">
          <button class="thread-link" data-act="comments">${ICON.comment}<span>${replies ? `${replies} ${replies === 1 ? 'reply' : 'replies'}` : 'Reply'}</span></button>
          ${p.mine ? `<button class="thread-link" data-act="edit">${ICON.pencil}<span>Edit</span></button>` : ''}
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
          <textarea class="input" id="post-body" maxlength="2000" rows="1" aria-label="Write a post" placeholder="Share an idea, a strategy, or how it's going…"></textarea>
          <div id="photo-preview" hidden><img id="photo-img" alt="Attached photo preview"><button type="button" class="photo-x" id="photo-remove" aria-label="Remove photo">${ICON.cross}</button></div>
          <div class="post-tools">
            <button class="btn sm" type="button" id="photo-btn">${ICON.image}Photo</button>
            <input type="file" id="photo-input" accept="image/png,image/jpeg,image/webp,image/gif" class="vh" tabindex="-1" aria-label="Choose a photo to attach">
            <label class="field post-strat-f"><span class="vh">Attach a strategy</span>
              <select id="post-strat"><option value="">Attach a strategy… (optional)</option></select></label>
            <button class="btn sm" type="button" data-share="pnl">${ICON.up}Share my P&amp;L</button>
            <button class="btn primary sm" type="submit">Post</button>
          </div>
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
        const o = document.createElement('option'); o.value = s.id; o.textContent = `${s.title} (${STATUS_WORD[s.status] || s.status})`; sel.appendChild(o);
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
    form.querySelector('[data-share="pnl"]').onclick = () => submit('pnl');
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
              const w = art.querySelector('.post-head .when'); if (w && !/edited/.test(w.textContent)) w.textContent += ' ·\u00a0edited';
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
      const m = /^#post-(\d+)$/.exec(location.hash), gen = S.gen;
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
  const STATUS_WORD = { passed: 'passed', failed: 'void', rejected: 'rejected' };

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
  // above $200000 by Jan 1…? · Above $200000" repeated the title.
  const mktLabel = (m) => { const t = (m.ti || '').trim(), s = (m.su || '').trim(); return s && !t.toLowerCase().includes(s.toLowerCase()) ? (t ? `${t} ·\u00a0${s}` : s) : (t || m.t); };
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
    const W = 760, H = 260, pl = 44, pr = 14, pt = 14, pb = 26, iw = W - pl - pr, ih = H - pt - pb;
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
      const sum = [op.length ? `${op.length} open at cost + fees ${usd(op.reduce((a, p) => a + p.cost, 0))}${marked.length ? ` ·\u00a0unrealized ${money(marked.reduce((a, p) => a + p.unrealized, 0))} (est. at the current bid${lastMark ? ', marked ' + when(lastMark) : ''})` : ' ·\u00a0awaiting first mark'}` : '',
        cl.length ? `${cl.length} closed ·\u00a0realized ${money(cl.reduce((a, p) => a + (+p.pnl || 0), 0))}` : ''].filter(Boolean).join(' ·\u00a0');
      const rows = xs.map((p) => `<tr><td class="name" data-lab="Strategy">${p.strategy_id && p.title ? `<a href="/strategies/${+p.strategy_id}">${esc(p.title)}</a>` : esc(p.title || 'Deleted strategy')}</td><td data-lab="Position">${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(+p.entry_price)}</td><td class="num" data-lab="Cost + fee">${usd(p.cost)}</td><td class="num" data-lab="${p.status === 'open' ? 'Unrealized' : 'Realized'}">${p.status === 'open' ? (p.unrealized == null ? '—' : money(p.unrealized)) : money(+p.pnl || 0)}</td><td data-lab="Status">${p.status === 'open' ? `Open, settles ${settleAt(p.market_close_time)}` : `Closed (${esc(exitWord(p.close_reason))}) @ ${cents(+p.exit_price)}`}</td></tr>`).join('');
      return `<div class="mk-book"><p class="mk-book-h">${BOOK[mode][0]} ${BOOK[mode][1]}</p><p class="hint">${sum}</p><div class="sheet"><table class="table stack"><thead><tr><th>Strategy</th><th>Position</th><th class="num">Cost + fee</th><th class="num">P&amp;L</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
    }).join('');
  }
  // What to do next from a market page: research it (the market picked in the form) or open your
  // strategies on it, when it's one Tau researches; otherwise say so, rather than leave a dead end.
  function marketNext(ticker) {
    const m = contractMkt(ticker);
    if (!m) return '<p class="hint mk-next">Tau doesn’t research this market, so your strategies can’t trade it. <a href="/research?new=1">See the markets it researches</a></p>';
    const k = encodeURIComponent(m.key);
    return `<p class="mk-next"><a class="btn sm primary" href="/research?new=1&amp;market=${k}">Research ${esc(marketShort(m.key))}</a><a class="btn sm" href="/strategies?market=${k}">Your ${esc(marketShort(m.key))} strategies</a></p>`;
  }
  async function viewMarketDetail(ticker) {
    shell('/explore', boardTitle('Market'), loading(300));
    let d;
    try { d = await api('/api/explore/market?ticker=' + encodeURIComponent(ticker)); }
    catch (e) {
      root.querySelector('main').innerHTML = notice(e.message, 'bad') + `<p style="margin-top:12px"><button class="btn sm" type="button" id="mk-retry">Try again</button> <a class="btn sm" href="/explore">← Back to Explore</a></p>`;
      root.querySelector('#mk-retry').onclick = () => viewMarketDetail(ticker);
      return;
    }
    const mid = midOf({ bid: d.yes_bid, ask: d.yes_ask, last: d.last });
    const label = mktLabel({ ti: d.title, su: d.sub, t: d.ticker });
    const gran = d.period_min >= 1440 ? 'daily' : d.period_min >= 60 ? 'hourly' : 'per-minute';
    const fmtT = (t) => new Date(t * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    // The price says what it is (a Yes pays $1, so 42¢ is about a 42% chance), the book it comes from,
    // and when it was read; the Explore feed's snapshot (Kalshi unreachable) says how old it is.
    const bid = +d.yes_bid, ask = +d.yes_ask;
    const priceSub = [mid == null ? '' : `≈\u00a0${Math.round(mid * 100)}% chance of Yes`, bid > 0 && ask > 0 ? `bid ${cents(bid)} / ask ${cents(ask)}` : '',
      d.as_of ? (d.snapshot ? `Explore snapshot, ${sinceMin(d.as_of)}` : `as of ${settleAt(d.as_of)}`) : ''].filter(Boolean).join(' ·\u00a0');
    const settled = d.result === 'yes' || d.result === 'no';
    const kalshiLink = `https://kalshi.com/markets/${encodeURIComponent((d.series || '').toLowerCase())}`;
    shell('/explore', boardTitle(label, esc([contractMarket(d.ticker), MKT_STATUS[d.status] || d.status || 'Market', d.ticker].filter(Boolean).join(' ·\u00a0'))) +
      '<dl class="figures measure" style="margin-top:14px">' +
        (settled ? fig('Result', d.result === 'yes' ? 'Yes' : 'No', { small: d.result === 'yes' ? 'each Yes contract paid $1' : 'each No contract paid $1' })
          : fig('Yes price', mid == null ? '—' : cents(mid), { small: priceSub })) + fig('24h volume', num(Math.round(+d.volume_24h || 0)), { small: 'contracts traded' }) +
        fig('Open interest', num(Math.round(+d.open_interest || 0)), { small: 'contracts held' }) + fig('Closes', settleAt(d.close_time)) + '</dl>' + marketNext(d.ticker), `
      <section class="sect"><div class="sect-head"><h2>Your positions here</h2><p>Each money book on its own</p></div>${marketMine(d)}</section>
      <section class="sect"><div class="sect-head"><h2>How it settles</h2><p>${d.settles_at ? `Result expected ${settleAt(d.settles_at)}` : 'Kalshi’s rules'}</p></div>
        ${d.rules ? `<p class="mk-rules">${esc(d.rules)}</p>${d.rules_more ? `<p class="hint mk-rules">${esc(d.rules_more)}</p>` : ''}`
          : `<p class="hint mk-rules">Kalshi’s settlement rules didn’t come with this snapshot. <a href="${kalshiLink}" target="_blank" rel="noopener">Read them on Kalshi ↗</a></p>`}</section>
      <section class="sect"><div class="sect-head"><h2>Price history</h2><p>Yes price${d.history_unavailable ? '' : ` ·\u00a0Kalshi ${gran} candles`}</p></div>
        <div class="pchart-wrap">${d.history_unavailable
          ? '<div class="empty"><h3>Price history didn’t load</h3><p>Kalshi didn’t send it just now. The figures above are from the latest market snapshot.</p><button class="btn sm" type="button" id="mk-retry">Try again</button></div>'
          : priceChart(d.points)}</div></section>
      <section class="sect"><div class="sect-head"><h2>Raw data</h2><p>${d.history_unavailable ? 'Not loaded' : `${num(d.points.length)} ${gran} points${d.points.length ? ' ·\u00a0newest first' : ''}`}</p></div>
        <div id="rawsect"></div></section>
      <div class="xpage"><a class="btn sm" href="/explore">← Back to Explore</a>
        <span class="xpage-acts"><button class="btn sm" id="dl-csv" ${d.points.length ? '' : 'disabled'}>Download CSV</button>
        <a class="btn sm" href="${kalshiLink}" target="_blank" rel="noopener">View on Kalshi ↗</a></span></div>`);
    const retry = root.querySelector('#mk-retry');
    if (retry) retry.onclick = () => viewMarketDetail(ticker);
    const pts = d.points.slice().reverse();  // newest first
    const PER = 25; let pg = 0;
    const rawEl = root.querySelector('#rawsect');
    const renderRaw = () => {
      if (!pts.length) { rawEl.innerHTML = `<div class="empty"><p>${d.history_unavailable ? 'Waiting on Kalshi for the candles.' : 'No candles recorded for this market yet.'}</p></div>`; return; }
      const pages = Math.max(1, Math.ceil(pts.length / PER));
      const rows = pts.slice(pg * PER, (pg + 1) * PER).map((p) => `<tr><td class="tick">${fmtT(p.t)}</td><td class="num">${cents(p.yes)}</td><td class="num">${num(Math.round(p.vol || 0))}</td></tr>`).join('');
      rawEl.innerHTML = `<div class="sheet"><table><thead><tr><th>Time (${esc(tzName() || 'local')})</th><th class="num">Yes price</th><th class="num">Volume</th></tr></thead><tbody>${rows}</tbody></table></div>
        <div class="xpage">${pg > 0 ? `<button class="btn sm" data-rp="${pg - 1}">← Prev</button>` : '<span></span>'}<span class="lab">Page ${pg + 1} of ${num(pages)} ·\u00a0${num(pts.length)} points</span>${pg + 1 < pages ? `<button class="btn sm" data-rp="${pg + 1}">Next →</button>` : '<span></span>'}</div>`;
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

  // Explore's empty and failed states: what happened, and a way to ask again.
  const EXPLORE_WAIT = 'The market list refreshes about once a minute and hasn’t come in yet. Try again shortly.';
  const exploreEmpty = (title, text) => `<div class="empty"><h3>${esc(title)}</h3><p>${esc(text)}</p><button class="btn sm" type="button" data-xretry>Try again</button></div>`;
  async function viewExplore() {
    const q = new URLSearchParams(location.search);
    if (q.get('m')) return viewMarketDetail(q.get('m'));
    const f = { q: q.get('q') || '', sort: ['v24', 'oi', 'last'].includes(q.get('sort')) ? q.get('sort') : 'v24', page: Math.max(0, +(q.get('page') || 0)) };
    shell('/explore', boardTitle('Explore', 'Every market Tau is tracking right now — the live book across crypto, politics, sports, weather and more, hottest first. Prices refresh each minute.') +
      '<dl class="figures measure" id="xfigs" style="margin-top:14px"></dl>', `
      <div class="section-head filters">
        <label class="field xsearch" style="margin:0"><span class="vh">Search markets</span>
          <input class="input" id="xq" type="search" placeholder="Search markets, series, tickers…" value="${esc(f.q)}" autocomplete="off"></label>
        <div class="chips" role="group" aria-label="Sort by">${[['v24', 'Hottest'], ['oi', 'Open interest'], ['last', 'Price']].map(([v, l]) => `<button class="chip" data-sort="${v}" aria-pressed="${f.sort === v}">${l}</button>`).join('')}</div>
      </div>
      <div id="xbody" style="margin-top:16px">${loading(240)}</div>`);
    const body = root.querySelector('#xbody'), figs = root.querySelector('#xfigs');
    const sync = () => history.replaceState(null, '', '/explore?' + new URLSearchParams({ q: f.q, sort: f.sort, page: String(f.page) }));
    const load = async () => {
      let d;
      try { d = await api('/api/explore?' + new URLSearchParams({ q: f.q, sort: f.sort, page: String(f.page) })); }
      catch (e) { body.innerHTML = exploreEmpty('Markets didn’t load', e.message); body.querySelector('[data-xretry]').onclick = load; return; }
      // "Live now" was the hottest markets the list carries, not what's live; Matching shows only when a
      // search narrows the list. The list refreshes each minute, so an older one says it's behind.
      const atMs = Date.parse(d.at || ''), behind = Number.isFinite(atMs) && Date.now() - atMs > 180000;
      figs.innerHTML = fig('Markets tracked', num(d.total)) + fig('In this list', num(d.shown), { small: 'the most traded' }) + (f.q ? fig('Matching', num(d.matched)) : '') +
        fig('Prices updated', sinceMin(d.at), behind ? { small: 'Behind: prices normally refresh each minute', cls: 'fig-behind' } : {});
      if (!d.markets.length) {
        // No search and no markets is the feed not having arrived yet, not a search that missed.
        if (f.q) body.innerHTML = `<div class="empty"><h3>No markets match “${esc(f.q)}”</h3><p>Try a broader search, or clear it to see the hottest markets.</p></div>`;
        else { body.innerHTML = exploreEmpty('No markets to show yet', EXPLORE_WAIT); body.querySelector('[data-xretry]').onclick = load; }
        return;
      }
      const rows = d.markets.map((m) => {
        const mid = midOf(m);
        return `<tr><td class="name"><a href="/explore?m=${encodeURIComponent(m.t)}">${esc(mktLabel(m))}</a>${m.ev || m.s ? ` <span class="mk quiet">${esc(m.ev || m.s)}</span>` : ''}</td>
          <td class="num" data-lab="Yes price">${mid == null ? '—' : cents(mid)}</td><td class="num" data-lab="24h volume">${num(Math.round(+m.v24 || 0))}</td><td class="num" data-lab="Open int.">${num(Math.round(+m.oi || 0))}</td>
          <td class="num xlink" data-lab="Kalshi"><a href="${kalshiUrl(m)}" target="_blank" rel="noopener" aria-label="Open on Kalshi">${ICON.ext}</a></td></tr>`;
      }).join('');
      const pages = Math.max(1, Math.ceil(d.matched / d.per));
      body.innerHTML = `<div class="sheet"><table class="stack t-explore"><thead><tr><th>Market</th><th class="num">Yes price</th><th class="num">24h volume</th><th class="num">Open int.</th><th class="num" aria-label="Link"></th></tr></thead><tbody>${rows}</tbody></table></div>
        ${pages > 1 ? `<div class="xpage">${f.page > 0 ? `<button class="btn sm" data-pg="${f.page - 1}">${ICON.up ? '' : ''}← Prev</button>` : '<span></span>'}<span class="lab">Page ${f.page + 1} of ${num(pages)}</span>${f.page + 1 < pages ? `<button class="btn sm" data-pg="${f.page + 1}">Next →</button>` : '<span></span>'}</div>` : ''}`;
      body.querySelectorAll('[data-pg]').forEach((b) => b.onclick = () => { f.page = +b.dataset.pg; sync(); window.scrollTo({ top: 0, behavior: smooth() }); load(); });
    };
    let t; root.querySelector('#xq').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); f.page = 0; sync(); load(); }, 220); });
    root.querySelectorAll('[data-sort]').forEach((b) => b.onclick = () => { f.sort = b.dataset.sort; f.page = 0; root.querySelectorAll('[data-sort]').forEach((o) => o.setAttribute('aria-pressed', o === b)); sync(); load(); });
    await load();
  }

  // Hot Markets left rail: persistent (open/closed survives page switches), refreshes each minute.
  // On a phone the rail is hidden (Explore covers it): an open rail would cover the whole page.
  const hotOpen = () => !phone() && localStorage.getItem('tau_hotrail') !== '0';
  let hotLoop = false;
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
      let yieldQueued = false;
      const yieldSoon = () => { if (yieldQueued) return; yieldQueued = true; requestAnimationFrame(() => { yieldQueued = false; apYield(); }); };
      addEventListener('scroll', yieldSoon, { passive: true }); addEventListener('resize', yieldSoon);
      document.addEventListener('toggle', yieldSoon, true); document.addEventListener('input', yieldSoon, true);
      // Tabbing onto a stepped-aside pill brings it back (apYield keeps a focused pill shown).
      document.addEventListener('focusin', yieldSoon, true); document.addEventListener('focusout', yieldSoon, true);
      // The page also moves under a still pill when it paints (the dashboard's figures land after the shell).
      if (typeof MutationObserver === 'function') new MutationObserver(yieldSoon).observe(document.body, { childList: true, subtree: true });
    }
  }
  // Resolves true when the status read landed. The loop backs off on false; other callers ignore it.
  async function refreshAutopilot(box, share = false, cfg) {
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
  const AP_DID = [['deploy', 'put %s on paper'], ['pause', 'paused %s'], ['resume', 'resumed %s'], ['stop', 'stopped %s'], ['adjust', 'adjusted %s'], ['research', 'started %s']];
  const CREDITS_WARN_DAYS = 3;  // the strip warns when credits last fewer days than this (server: CREDIT_RUNWAY_WARN_DAYS)
  // A deployment's pause reason, short: no "Autopilot:" prefix, no closing period, cut at a word.
  const shortReason = (r) => {
    const s = String(r).replace(/^Autopilot:\s*/, '').replace(/\.\s*$/, '');
    return s.length <= 110 ? s : s.slice(0, 110).replace(/\s+\S*$/, '') + '\u2026';
  };
  // The strip's Autopilot row when it made no moves: just the switch, which syncApCopy keeps current.
  const sinceApWord = (on) => on ? 'On. It made no changes.' : 'Off.';
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
        const name = dep ? `<a href="/strategies/${encodeURIComponent(dep.strategy_id)}">${esc(dep.title)}</a>` : 'a removed strategy';
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
        ? `<span class="nobr"><b>${label}</b> <span class="${b.pnl < 0 ? 'neg' : b.pnl > 0 ? 'pos' : ''}">${usd(b.pnl, true)}</span></span> on ${plural(b.trades, 'trade', 'trades')}${m === 'live' ? ' (real money)' : ''}`
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
    // A brand-new account has nothing of its own to report yet: point at the finished example, up top.
    const found = s.own_sessions === false && !pass.n && !fwd.length ? `No sessions of your own yet. <a href="/example" data-example>See an example session first</a>` : ((pass.n
      ? `${plural(pass.n, 'strategy', 'strategies')} passed: ${pass.items.map((x) => `<a href="/strategies/${encodeURIComponent(x.id)}">${esc(x.title)}</a>`).join(', ')}${pass.n > pass.items.length ? `, <a href="/strategies">${num(pass.n - pass.items.length)} more</a>` : ''}`
      : fwd.length ? fwdText : 'Nothing new passed') + (started ? ` <span class="since-sub">· ${plural(started, 'research session', 'research sessions')} started, ${sinceRunsState(runs, started, !pass.n)}</span>` : '') + '.' + (pass.n && fwd.length ? ` ${fwdText}.` : ''));
    const ap = s.autopilot || {}, apOn = !!(S.me && S.me.user && S.me.user.autopilot);
    const known = new Set(AP_DID.map(([k]) => k));
    const did = AP_DID.filter(([k]) => ap[k]).map(([k, w]) => w.replace('%s', k === 'research' ? plural(ap[k], 'research session', 'research sessions') : num(ap[k])));
    const other = Object.entries(ap).filter(([k]) => !known.has(k)).reduce((a, [, n]) => a + n, 0);
    if (other) did.push('made ' + plural(other, 'other change', 'other changes'));
    const auto = did.length ? `It ${did.join(', ')}.` : `<span data-since-ap>${sinceApWord(apOn)}</span>`;
    const needs = (ms.live_ready || []).slice(0, 3).map((sid) => `${named(sid)} is ready for live trading. Going live is your call.`);
    needs.push(...d.deployments.filter((x) => x.status === 'paused').slice(0, 3)
      .map((x) => `<a href="${pausedHref}">${esc(x.title)}</a> is paused${x.status_why || x.status_reason ? `<span class="since-sub">: ${esc(shortReason(x.status_why || x.status_reason))}</span>` : ''}`));
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
    const cost = spent ? `${+spent.since >= 0.01 ? `<b>${usd(spent.since)}</b> of credits spent` : 'No credits spent'}<span class="since-sub"> \u00b7\u00a0real money \u00b7\u00a0${usd(me.credit_balance || 0)} left \u00b7\u00a0<a href="/billing">Billing</a></span>` : '';
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
  function tradesCsv(mode, b) {
    return b && b.closed_trades > 0 ? ` \u00b7\u00a0<a class="csv-link" href="/api/trades.csv?mode=${mode}" download>Download trades (CSV)</a>` : '';
  }
  // What demo is, for a reader who has never used it: real exchange fills, pretend money.
  const DEMO_WHAT = 'real fills on Kalshi’s sandbox, not real money';
  // Dashboard autopilot card: the one-click way in while autopilot is off, and once it's on a
  // plain "what is it doing, is it making money" strip. Painted from the float's status poll
  // (S.ap) plus the dashboard's paper book (S.dashPaper), so it never needs its own request.
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
      b.onclick = () => busy(b, apTurnOn);
      apBindFocus(host);
      return;
    }
    if (!d) { host.className = 'apcard on'; host.innerHTML = ''; return; }  // on, status still loading
    const m = AP_MODE[d.mode] || AP_MODE.paper, r = d.research || {}, prog = d.paper_progress;
    const running = (d.live_running || 0) + (d.demo_running || 0) + (d.paper_running || 0);
    // Realized, as the paper card, the track record, Deploy and the strategy page count it. The equity
    // change (total_pnl) is a fourth number: it takes off open positions' entry fees and drops every
    // trade before a reset, so "Paper P&L" read $5.19 here beside a $5.61 track record.
    const pnl = S.dashPaper ? S.dashPaper.realized_pnl : null;
    const cells = [
      d.live_running ? ['Live realized today (UTC)', money(d.today_live_pnl || 0)] : ['Paper P&amp;L, realized all time', pnl == null ? '—' : money(pnl)],
      ['Strategies running', running ? String(running) : 'None yet'],
      d.week ? null : ['Ideas this week', `${Number(r.tested_7d || 0).toLocaleString('en-US')} tested ·\u00a0${r.passed_7d || 0} passed`],
      prog ? ['Furthest on paper', `<a href="/strategies/${Number(prog.strategy_id)}" title="${esc(prog.title || 'Paper strategy')}">${paperCount(prog)}</a>`]
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
    if (t.length > 90) t = t.slice(0, 90).replace(/\s+\S*$/, '') + '\u2026';
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
  // catalog no longer lists it ("btc15m", a series like "KXBTCD"); a key reads as the short label,
  // a series as its market's, and a key nothing knows as "an unlisted market", never the raw key.
  const AP_PICKING = "a market it's still picking";
  function apMarketName(n) {
    const s = String(n || '');
    if (MKT_SHORT[s]) return MKT_SHORT[s];
    const m = ((S.me && S.me.markets) || []).find((x) => x.key === s || (x.series && x.series.toUpperCase() === s.toUpperCase()));
    if (m) return marketShort(m.key);
    // A label has a space or mixed case ("Bitcoin daily close, 5pm EDT"); a key is one case, no spaces.
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
    if (!all.length) return d.reviewing ? " Meanwhile it's reviewing the markets to pick its next move." : '';
    if (!names.length) return " Meanwhile it's picking a market to research.";
    const said = names.length === 1 ? names[0] : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
    return ` Meanwhile it's researching ${esc(said)}.`;
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
    return doing ? 'Autopilot ·\u00a0' + doing : m.label;
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
    return f.map((t) => keys.has(t) ? marketShort(t) : t.charAt(0).toUpperCase() + t.slice(1).replace(/-/g, ' ')).join(', ');
  }
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
    const prefs = box.querySelector('.apf-prefs'); if (prefs) prefs.open = true;
    const sel = box.querySelector('#apf-focus'); if (sel && sel.focus) sel.focus();
  }
  // The autopilot's last 7 days (d.week). Credits are real money and paper P&L is not, so they are two
  // labelled figures, never added together. Research counts every session; paper counts only the
  // strategies the autopilot put on paper itself (the server attributes them by their deploy record).
  function apWeek(w, d) {
    if (!w) return '';
    const pnl = +w.paper_pnl || 0, trades = +w.paper_trades || 0;
    return `<section class="ap-week" aria-label="Autopilot, last 7 days"><h3>Last 7 days</h3><dl>
      <div><dt>Credits spent on research</dt><dd>${usd(w.research_credits || 0)} <small>real money${+w.checkin_credits >= 0.01 ? ` · plus ${usd(w.checkin_credits)} on its check-ins` : ''}</small></dd></div>
      <div><dt>Ideas</dt><dd>${Number(w.tested || 0).toLocaleString('en-US')} tested ·\u00a0${Number(w.passed || 0).toLocaleString('en-US')} passed</dd></div>
      <div><dt>Autopilot put on paper</dt><dd>${Number(w.paper_started || 0)} strateg${+w.paper_started === 1 ? 'y' : 'ies'} <small>not counting yours</small></dd></div>
      <div><dt>Autopilot's paper P&amp;L</dt><dd><span class="${pnl < 0 ? 'neg' : pnl > 0 ? 'pos' : ''}">${usd(pnl, true)}</span> <small>paper, not real money ·\u00a0${trades} closed trade${trades === 1 ? '' : 's'}</small></dd></div>
    </dl>${apCreditsLeft(w, d)}<p class="ap-week-note">Research counts every session, yours and the autopilot's. The two paper rows count only what the autopilot put on paper itself; strategies you deploy yourself count in the running total and on the Deploy page, not here.</p></section>`;
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
    const n = (+d.live_running || 0) + (+d.demo_running || 0) + (+d.paper_running || 0);
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
    const floor = me.min_run_balance != null ? ` until your balance is under ${usd(me.min_run_balance)}, then pauses` : '';
    return `<p class="ap-week-left">Credits left: <b>${usd(w.credits_left)}</b>${pace}. It has no daily spending cap: it uses credits${floor}${me.auto_reload && !reloadIn ? ` (auto-reload adds ${usd(me.auto_reload.amount)} at ${usd(me.auto_reload.threshold)})` : ''}.${d && d.reload_failed ? ` <b>Auto-reload failed.</b> ${esc(d.reload_failed)} <a href="/billing">Update your card</a>.` : ''} <a href="/billing">Billing</a> lists every charge.</p>`;
  }
  // What switching it on costs, said before the click: the agent's runs spend credits, and with
  // auto-reload on the saved card is charged when they run low. Payments off on this server: no line.
  function apCostLine() {
    const me = S.me;
    if (!me || !me.billing_enabled) return '';
    const ar = me.auto_reload;
    // Already under what a session needs to start: switched on, it would sit paused from the start.
    if (!ar && !me.needs_card && me.min_run_balance != null && me.credit_balance < me.min_run_balance)
      return `<p class="apcard-cost">It uses your credits while it's on. You have ${usd(me.credit_balance)}, under the ${usd(me.min_run_balance)} a research session needs to start, so it waits until you <a href="/billing">add credits</a>. Turn it off any time.</p>`;
    return `<p class="apcard-cost">It uses your credits while it's on (${usd(me.credit_balance)} left)${ar
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
  const paperCount = (p) => +p.trades >= +p.trades_needed ? `${num(+p.trades)} paper trades (${num(+p.trades_needed)} needed)` : `${num(+p.trades)} of ${num(+p.trades_needed)} paper trades`;
  // A backtest trade's exit, in words (backtest.py / spec.exit_signal reasons); an unknown one loses its underscores.
  const EXIT_WORD = { settled: 'settled', take_profit: 'take-profit', stop_loss: 'stop-loss', stop: 'stop', edge_gone: 'edge gone', signal: 'signal', exit: 'signal', mark: 'marked at end' };
  const exitWord = (r) => r == null ? '' : EXIT_WORD[r] || String(r).replace(/_/g, ' ');
  // The equity chart's label over its unseen-data window: the full words when they fit, else
  // "UNSEEN →", pinned to the chart's right edge when even that would run past it.
  const unseenLabel = (cx, right, y) => {
    const room = right - cx - 8, text = room >= 150 ? 'UNSEEN BY THE AGENT →' : 'UNSEEN →';
    return room >= 64 ? `<text x="${cx + 8}" y="${y}" style="fill:var(--ink-2)">${text}</text>`
      : `<text x="${right}" y="${y}" text-anchor="end" style="fill:var(--ink-2)">${text}</text>`;
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
  async function apTurnOn() {
    try { await api('/api/settings', { autopilot: true }); }
    catch (e) { const card = document.getElementById('dash-ap'), err = card && card.querySelector('.apcard-err'); if (err) err.innerHTML = esc(e.message); else alert0(e.message); return; }
    S.me.user.autopilot = true;
    if (S.ap) S.ap = Object.assign({}, S.ap, { autopilot: true, mode: S.ap.mode === 'off' ? 'paper' : S.ap.mode });
    paintDashAp();
    // The card (or the nudge) repaints without the pressed button, so a reader heard nothing and a
    // keyboard user was left at the top of the page: say what changed, then follow it to the control
    // that replaced it — the open panel's close button, else the card's Open autopilot.
    announce('Autopilot is on. It researches and trades on paper by itself; every move shows up in the autopilot panel.');
    if (!phone()) apOpen();  // on a phone the open panel fills the screen; the card already says it's on
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
    paper: { label: 'Autopilot ·\u00a0paper', cls: 'paper' },
    'live-armed': { label: 'Autopilot ·\u00a0live armed', cls: 'live' },
    live: { label: 'Autopilot ·\u00a0LIVE', cls: 'live' },
  };
  // The float is the single home for autopilot: the on/off toggle, live controls, and the agent
  // chat. The expanded shell is built ONCE; the 20s status poll updates only dynamic bits so it
  // never wipes the chat/composer. apChatTimer polls chat (3s) only while expanded.
  let apChatLastId = 0, apChatTimer = null, apFeedFirst = true, apFeedDay = '';
  // The feed's day line: the rail's times are the reader's clock, so each day starts with its date and zone.
  const tzShort = () => { try { return (new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName') || {}).value || ''; } catch (e) { return ''; } };
  function apDayLi(iso) {
    const d = new Date(iso), li = document.createElement('li'), today = new Date();
    const yest = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    const label = d.toDateString() === today.toDateString() ? 'Today' : d.toDateString() === yest.toDateString() ? 'Yesterday'
      : d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    li.className = 'ap-day';
    li.textContent = label + (tzShort() ? ' ·\u00a0times in ' + tzShort() : '');
    return li;
  }
  // A send or a decision that failed says why just above the composer. alert0 put it at the top of the
  // page, under the panel, and a phone's full-screen sheet hid it altogether.
  function apErr(box, msg, billing) {
    const el = box.querySelector('#apf-err');
    if (!el) { if (msg) alert0(msg); return; }
    // Out of credits (402) says where to add them, as a link, not "the Billing tab" to go and find.
    if (msg && billing) el.innerHTML = `${esc(msg)} <a href="/billing">Open Billing</a>`;
    else el.textContent = msg || '';
    el.hidden = !msg;
  }
  // The line under the composer: what the agent may do with a message, and what one costs. The cost is
  // the server's turn_cost (what the newest answered message debited), kept from the last read that had it.
  let apTurnCost;
  const AP_DRAFT = () => 'tau_ap_draft:' + ((S.me && S.me.user && S.me.user.id) || '');
  function apCostPaint(box) {
    const el = box.querySelector('#apf-cost'); if (!el) return;
    const me = S.me || {}, on = S.ap ? S.ap.autopilot : !!(me.user && me.user.autopilot);
    const what = on ? 'It may act on what you ask, within your limits.' : 'Any change it suggests waits for your Approve.';
    const c = apTurnCost, last = c == null ? '' : c === 0 ? ' Your last one cost nothing.'
      : c < 0.005 ? ' Your last one cost under $0.01.' : ` Your last one cost ${usd(c)}.`;
    el.textContent = what + (me.billing_enabled ? ' Each message is paid from your credits.' + last : '');
    el.hidden = false;
  }
  function apStopChat() { if (apChatTimer) { clearInterval(apChatTimer); apChatTimer = null; } apChatWake = null; }
  let apChatWake = null;
  wakers.add(() => { if (apChatWake && !document.hidden) apChatWake(); });
  // The autopilot's autonomous moves, keyed by the proposal kind on a system line — the clear,
  // plain verb a reader scans ("Promoted", "Tuned"), plus the timeline lane that tints the node.
  // No proposal on a system line = a review/holding/blocked note (nothing was changed).
  const AP_ACT = {
    research: 'Research', deploy: 'Promoted to paper', deploy_live: 'Promoted to live',
    adjust: 'Tuned strategy', set_risk: 'Tuned risk', set_exec: 'Tuned execution',
    pause: 'Paused', resume: 'Resumed',
    alpaca_paper: 'Alpaca paper order',
    kalshi_perps_live: 'Bitcoin perps live order',
  };
  // A proposal still waiting on you is headed by what it asks, not the done verb above: "Paused" and
  // "Promoted to paper" sat over Approve and Decline, as if it had already happened. Its line under
  // that says what Approve does and in which book (paper, demo or live) before anyone presses it.
  const AP_ASK = {
    deploy: 'Asks to put on paper', adjust: 'Asks to tune a strategy', pause: 'Asks to pause', resume: 'Asks to resume',
    set_risk: 'Asks to change risk limits', set_exec: 'Asks to change execution limits',
  };
  const AP_BOOK = { paper: 'on paper, with practice money', demo: 'on demo, Kalshi\u2019s sandbox with no real money', live: 'LIVE, with real money in your Kalshi account' };
  function apApproveLine(m) {
    const k = m.proposal_kind, book = AP_BOOK[m.deployment_mode];
    const verb = { pause: 'pauses', resume: 'restarts', adjust: 'swaps the tuned version into' }[k];
    // A pause sells what the strategy holds (the engine flattens a paused deployment), as Deploy's Pause says.
    const sells = k === 'pause' ? ', and sells anything it holds' : '';
    if (verb) return book ? { text: `Approve ${verb} this strategy, which runs ${book}${sells}.`, live: m.deployment_mode === 'live' } : null;
    if (k === 'deploy') return { text: 'Approve starts it on paper, with practice money. Nothing trades real money.' };
    if (k === 'set_risk' || k === 'set_exec') return { text: 'Approve applies these limits to every strategy you run, live ones included.' };
    return null;
  }
  // One feed entry, rendered with the SAME research-session parts (.ln timeline rail, .say card,
  // feedMd markdown, lane tint) so the autopilot reads as one family with the research log —
  // a legible end-to-end session, not a cramped chat. m.content is Markdown; m.stage/m.strategy/
  // m.detail are OPTIONAL structured fields the backend can add later (see the note in PLAN.md).
  function apFeedLi(m) {
    const li = document.createElement('li');
    const t = `<time datetime="${esc(m.created_at)}" title="${esc(settleAt(m.created_at))}">${clock(m.created_at)}</time><span class="node" aria-hidden="true"></span>`;
    if (m.role === 'user') {
      li.className = 'ln lane-state apf-you';
      li.innerHTML = `${t}<div class="say"><span class="say-kind">You</span>${mdLite(m.content)}</div>`;
      return li;
    }
    if (m.role !== 'system') {   // the agent's think-aloud reasoning
      li.className = 'ln lane-think apf-think';
      li.innerHTML = `${t}<div class="say"><span class="say-kind">Agent</span><div class="apf-md">${feedMd(m.content)}</div></div>`;
      return li;
    }
    // A system line = an autopilot action (or a blocked/holding note).
    // The switch notes ("Autopilot is ON: …") were labelled Reviewed, so a new user's first feed line
    // said it had reviewed something seconds after the click, before any review ran.
    const flip = !m.proposal_kind && /^(LIVE )?autopilot is (ON|OFF)\b/i.exec(m.content || '');
    const st = m.proposal_status;
    // Your own decision and a failed answer are not reviews: both read "Reviewed" here.
    const said = /^You (approved|declined) the proposal/.test(m.content || '') ? 'Your decision'
      : /^The agent hit an error/.test(m.content || '') ? 'No answer' : '';
    // Asked in chat to pause a strategy on paper under a day (or a tournament entrant), the agent's reply
    // can suggest pausing it, and then this line says "I left it running": under "Reviewed" it read as
    // the same voice taking it back. It is the autopilot's own rule (agent.act), so it is headed as
    // that, and says that your own Pause on Deploy still stops it.
    const rule = !m.proposal_kind && /^I left .+ running: it (?:has been on paper for only|is a paper tournament entrant)/.test(m.content || '');
    // The engine's own loss guard or drawdown limit paused a strategy (the server says it by name,
    // customer_text.auto_pause_line): no review ran, so it isn't headed "Reviewed".
    const guard = !m.proposal_kind && /^Paused (?:your (?:paper|demo|live) strategy .+|one of your strategies) automatically\b/.test(m.content || '');
    const kind = (st === 'pending' && AP_ASK[m.proposal_kind]) || AP_ACT[m.proposal_kind]
      || (flip ? (flip[1] ? 'Live autopilot ' : 'Autopilot ') + (/on/i.test(flip[2]) ? 'on' : 'off')
        : said || (rule ? 'Autopilot’s rule: kept running' : guard ? 'Paused automatically' : 'Reviewed'));
    const own = rule ? '<p class="apf-ask apf-rule">To stop it anyway, pause it yourself on <a href="/deploy">Deploy</a>.</p>' : '';
    const lane = !m.proposal_id ? 'state' : st === 'pending' ? 'review' : st === 'applied' ? 'action' : 'void';
    const stamp = st === 'applied' ? `<span class="hx-stamp pass">${m.proposal_kind === 'alpaca_paper' ? 'Approved' : 'Applied'}</span>`
      : st === 'declined' || st === 'rejected' ? '<span class="hx-stamp rej">Declined</span>' : '';
    const stage = m.stage ? `<span class="hx-tag">${esc(m.stage)}</span>` : '';
    const title = m.strategy ? `<b class="say-title">${esc(m.strategy)}</b>` : '';
    const detail = m.detail ? `<details class="hx-more"><summary>Show the detail</summary><div class="hx-body"><div class="apf-md">${feedMd(m.detail)}</div></div></details>` : '';
    const ask = st === 'pending' ? apApproveLine(m) : null;
    const ctl = (m.proposal_id && st === 'pending')
      ? `${ask ? `<p class="apf-ask${ask.live ? ' live' : ''}">${esc(ask.text)}</p>` : ''}<div class="proposal" data-prop="${m.proposal_id}"><button class="btn small" data-decide="approve">${m.proposal_kind === 'kalshi_perps_live' ? 'Review live order' : 'Approve'}</button><button class="btn ghost small" data-decide="reject">Decline</button></div>` : '';
    li.className = 'ln lane-' + lane + ' apf-act';
    li.innerHTML = `${t}<div class="say">
      <div class="hx-head"><span class="say-kind">${esc(kind)}</span>${title}${stage}${stamp}</div>
      <div class="apf-md">${feedMd(m.content)}</div>${own}${detail}${ctl}</div>`;
    return li;
  }
  // Resolves false when the read failed (the chat poll backs off on it; other callers ignore it).
  // `follow`: 'end' brings the newest line into view (you just sent one), 'keep' holds the reader's place
  // through a full repaint (a decision mid-history). Otherwise it follows only a reader already at the end.
  // On a phone the open panel is one scroll (app.css), so the sheet is what scrolls there, not the feed:
  // a sent message and its answer landed below the fold, under a sheet still showing the controls.
  async function apLoadChat(box, full, cfg, follow) {
    const msgs = box.querySelector('#apf-messages'); if (!msgs) return;
    let d; try { d = await api('/api/chat?after=' + (full ? 0 : apChatLastId), undefined, { keep: true, ...cfg }); }
    catch (e) {
      // Nothing painted yet: say the feed didn't load rather than leave it blank. The poll retries.
      if (!msgs.children.length) msgs.innerHTML = '<li class="ap-empty ap-fail">Couldn\u2019t load the autopilot\u2019s activity. Retrying.</li>';
      return false;
    }
    msgs.querySelectorAll('.ap-fail').forEach((n) => n.remove());
    const atEnd = (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 70;
    const sheet = box.scrollHeight > box.clientHeight + 1;
    const stick = follow === 'end' || (full && follow !== 'keep') || atEnd(msgs);
    const stickSheet = follow === 'end' || (!full && sheet && atEnd(box));
    const kept = [msgs.scrollTop, box.scrollTop];
    if (full) { msgs.innerHTML = ''; apChatLastId = 0; apFeedFirst = true; apFeedDay = ''; }
    const empty = msgs.querySelector('.ap-empty'); if (empty && d.messages.length) empty.remove();
    msgs.querySelectorAll('.apf-typing').forEach((n) => n.remove());
    d.messages.forEach((m) => {
      if (m.id <= apChatLastId) return;  // a slow read that lands after a newer one already painted it
      apChatLastId = Math.max(apChatLastId, m.id);
      const day = new Date(m.created_at).toDateString();
      if (day !== apFeedDay) { apFeedDay = day; msgs.appendChild(apDayLi(m.created_at)); }
      const li = apFeedLi(m);
      if (!apFeedFirst) li.classList.add('in');   // backlog lands silently; new moves rise in
      msgs.appendChild(li);
    });
    if (d.messages.length) apFeedFirst = false;
    if ('turn_cost' in d) { apTurnCost = d.turn_cost; apCostPaint(box); }
    if (!msgs.children.length) msgs.innerHTML = '<li class="ap-empty">No autopilot activity yet. While it\u2019s on, it checks in on its own schedule: it reviews what\u2019s running, starts research, and puts the strategies that pass every research test on paper (pretend money). It trades real money only if you also turn on live autopilot. Each move lands here as it happens. Message it below to steer.</li>';
    // The live pulse — the research session's "working" signal, scoped to the operation.
    const pulse = box.querySelector('#apf-pulse');
    if (pulse) {
      pulse.hidden = false;
      pulse.className = 'runpulse apf-pulse-row';
      // Past the reaper's limit the spinner would claim work nobody is doing; say how long instead.
      const w = d.agent_wait;
      pulse.innerHTML = w
        ? `<span class="apf-idle-dot" aria-hidden="true"></span><span>${w.state === 'queued' ? 'Waiting for a free worker' : 'No word from it'} for ${waitSpan(w.seconds)}, longer than usual</span>`
        : d.agent_busy
        ? '<span class="working" aria-hidden="true"></span><span>Working on its next move<span class="ell" aria-hidden="true"></span></span>'
        : `<span class="apf-idle-dot" aria-hidden="true"></span><span data-ap-idle>${esc(apIdleLine(box))}</span>`;
    }
    if (stick) msgs.scrollTop = msgs.scrollHeight; else if (follow === 'keep') msgs.scrollTop = kept[0];
    if (stickSheet) box.scrollTop = box.scrollHeight; else if (follow === 'keep') box.scrollTop = kept[1];
    return true;
  }
  // Idle pulse copy: lead with the autopilot's most recent move (from the status poll, always
  // available even if chat is slow), else a plain "on a schedule" line.
  function apIdleLine(box) {
    const d = S.ap, la = d && d.last_action;
    const last = la && la.at ? ' ·\u00a0last move ' + sinceMin(la.at) : '';
    if (!(d ? d.autopilot : apSwitchOn())) return 'Off: it acts only when you message it' + last;
    const now = apNowWord(d);
    return now + last + (now === 'Idle' ? ' — reviews run on a schedule' : '');
  }
  // The pulse's lead: what the status read says it is doing, so it never reads "Idle" over research.
  function apNowWord(d) {
    if (!d) return 'Idle';
    if (d.billing_blocked) return 'Paused until it can pay for research';
    const names = apMarketNames(d), picked = names.filter((n) => n !== AP_PICKING);
    if (names.length) return picked.length ? 'Researching ' + picked.join(' ·\u00a0') : 'Picking a market to research';
    if (d.reviewing) return 'Reviewing the markets';
    // Between reviews with strategies on paper is not idle: they trade on their own between its moves.
    return d.paper_running ? `Between reviews ·\u00a0${d.paper_running} on paper` : 'Idle';
  }
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
      if (box.apPill === pill && box.querySelector('.apf-pill')) { apYield(); return; }
      box.apPill = pill;
      if (box.removeAttribute) { box.removeAttribute('role'); box.removeAttribute('aria-label'); }
      const a = document.activeElement, hadFocus = !!(a && a !== document.body && box.contains && box.contains(a));
      box.innerHTML = pill;
      const pb = box.querySelector('.apf-pill');
      if (hadFocus && pb && pb.focus) pb.focus({ preventScroll: true });
      box.querySelector('[data-ap]').onclick = (e) => apAction(box, 'toggle', e);
      apYield();
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
  // The open panel is left alone: the user opened it.
  const AP_UNDER = ['a[href]', 'button', 'input', 'select', 'textarea', 'summary', '.switch', '[role="button"]', '[role="tab"]',
    '.figures .m', '.fig', 'td.num', 'dd', '#dash-ap'];
  const AP_UNDER_SEL = AP_UNDER.join(', ');
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
  // The open panel is a full-screen sheet under this width (app.css: `.apf.open { inset: 0 }`), which is
  // not phone(): between the two it still sits beside the page.
  const apSheet = () => !!(window.matchMedia && window.matchMedia('(max-width: 600px)').matches);
  const AP_TABBABLE = 'a[href], button, input, select, textarea, summary, [tabindex]';
  function apSheetTab(box, e) {
    // What Tab would actually reach: enabled, in the tab order, and drawn (a folded fieldset or a
    // hidden confirm form has no box).
    const items = [...box.querySelectorAll(AP_TABBABLE)].filter((el) => !el.disabled && el.getAttribute('tabindex') !== '-1'
      && (el.offsetWidth || el.offsetHeight || el === document.activeElement));
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1], a = document.activeElement;
    if (e.shiftKey ? a === first : a === last) { e.preventDefault(); (e.shiftKey ? last : first).focus({ preventScroll: true }); }
  }
  function apBuildShell(box) {
    box.dataset.shell = 'expanded'; box.apPill = '';
    box.setAttribute('role', 'region'); box.setAttribute('aria-label', 'Autopilot');
    // Esc closes the open panel, and focus goes back to the pill. As a full-screen sheet the panel
    // covers the page, so Tab stays inside it instead of walking controls nobody can see.
    box.onkeydown = (e) => {
      if (e.key === 'Escape' && apExpanded()) { e.stopPropagation(); apAction(box, 'toggle'); return; }
      if (e.key === 'Tab' && apSheet() && apExpanded()) apSheetTab(box, e);
    };
    box.innerHTML = `
      <div class="apf-head"><span class="apf-dot" aria-hidden="true"></span><b id="apf-label"></b>
        <button type="button" class="apf-x" data-ap="toggle" aria-label="Collapse autopilot">${ICON.cross || '×'}</button></div>
      <div class="apf-top">
        <div class="autopilot" id="apf-ap">
          <span id="apf-ap-copy"></span>
          <label class="switch"><span class="vh">Autopilot</span><input type="checkbox" id="apf-apswitch"></label>
        </div>
        <dl class="apf-stats" id="apf-stats"></dl>
        <p class="stale-note" id="apf-stale" role="status"></p>
        <div id="apf-last"></div>
        <div id="apf-week"></div>
        <div class="apf-story" id="apf-story" aria-live="polite"></div>
        <p class="ap-focus" id="apf-focusline" hidden></p>
        <details class="apf-prefs"><summary>Model and markets</summary>
          <label class="field apf-model"><span>Autopilot model</span>
            <select class="input" id="apf-model" aria-label="Autopilot model"></select></label>
          <label class="field apf-model"><span>Markets it may trade</span>
            <select class="input" id="apf-focus" aria-label="Markets the autopilot may research and trade"></select></label>
        </details>
        <div class="apf-gates hint" id="apf-gates"></div>
        <div id="apf-flash"></div>
        <div class="apf-controls" id="apf-controls"></div>
        <form id="apf-confirm" hidden>
          <p class="hint">The agent will trade <b>real money</b> on its own, within your caps + loss guard. Type <b>LIVE AUTOPILOT</b>.</p>
          <input class="input" name="confirm" autocomplete="off" aria-label="Type LIVE AUTOPILOT to confirm">
          <button class="btn sm" type="submit">Confirm live autopilot</button>
        </form>
      </div>
      <div class="apf-session">
        <div class="apf-session-head"><span class="say-kind">Activity feed</span><span class="apf-session-sub">everything the autopilot does, end to end</span></div>
        <ol class="log stream apf-log" id="apf-messages" role="log" aria-label="Autopilot activity" aria-live="polite"></ol>
        <div class="runpulse apf-pulse-row" id="apf-pulse" aria-live="polite" hidden></div>
      </div>
      <form class="composer apf-composer-row" id="apf-composer">
        <p class="apf-err" id="apf-err" role="alert" hidden></p>
        <label class="vh" for="apf-msg">Message the agent</label>
        <textarea class="input" id="apf-msg" rows="1" maxlength="2000" placeholder="What should it focus on?" aria-label="Message the autopilot" aria-describedby="apf-cost"></textarea>
        <button class="btn" type="submit" aria-label="Send">${ICON.send}</button>
        <p class="apf-cost" id="apf-cost" hidden></p>
      </form>`;
    box.querySelector('.apf-x').onclick = (e) => apAction(box, 'toggle', e);
    box.querySelector('#apf-confirm').onsubmit = (e) => { e.preventDefault(); apEnableLive(box, box.querySelector('#apf-confirm').confirm.value.trim()); };
    const sw = box.querySelector('#apf-apswitch');
    sw.onchange = async () => {
      const on = sw.checked;
      // One flip, like the dashboard card and the empty-page nudges: paper-only and undone by flipping
      // back. Real money keeps its own typed LIVE AUTOPILOT confirm below.
      // The switch locks until Tau answers: two quick flips that both failed left it showing on while
      // autopilot was off. A failure puts it back to the saved state and says why in the panel, next to
      // it (the page under a phone's full-screen panel can't be seen).
      sw.disabled = true; apNote(box, '');
      let saved = false;
      // Locking the switch blurs it, so focus goes back to it once it unlocks (the panel is the only
      // thing on screen on a phone, and the page behind it is where focus used to land).
      try { await api('/api/settings', { autopilot: on }); S.me.user.autopilot = on; saved = true; }
      catch (e) { sw.checked = !!(S.me && S.me.user && S.me.user.autopilot); apNote(box, e.message); }
      finally {
        sw.disabled = false;
        const a = document.activeElement;
        if ((!a || a === document.body) && sw.isConnected && sw.focus) sw.focus({ preventScroll: true });
      }
      if (!saved) return;
      // The switch's new state is said out loud: its label and the copy beside it change silently.
      announce(on ? 'Autopilot is on. It researches and trades on paper by itself.' : 'Autopilot is off. It only suggests ideas for you to approve.');
      // Right after switching on, show where it may trade, so the focus is a choice and not a default nobody saw.
      if (on) { const prefs = box.querySelector('.apf-prefs'); if (prefs) prefs.open = true; }
      if (S.ap) S.ap = Object.assign({}, S.ap, { autopilot: on, mode: !on ? 'off' : S.ap.mode === 'off' ? 'paper' : S.ap.mode });
      paintDashAp();  // copy that follows the switch flips now, not on the next status read
      refreshAutopilot(box);
    };
    const msgs = box.querySelector('#apf-messages');
    msgs.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-decide]'); if (!b) return;
      const prop = b.closest('[data-prop]'), pid = prop.dataset.prop;
      // One decision per proposal: Approve and Decline both lock while it is sent (a tap on the other
      // one used to send it too), and stay locked once it lands until the repaint shows the stamp.
      if (prop.dataset.deciding) return;
      prop.dataset.deciding = '1';
      const btns = [...prop.querySelectorAll('button')];
      btns.forEach((x) => { x.disabled = true; });
      b.classList.add('busy');
      apErr(box, '');
      try {
        const result = await api(`/api/proposals/${pid}/${b.dataset.decide}`, {});
        if (result.review_required && result.review_url === `/funds?perps_proposal=${pid}`) { go(result.review_url); return; }
      } catch (err) {
        apErr(box, err.message);
        btns.forEach((x) => { x.disabled = false; });
        delete prop.dataset.deciding;
      } finally { b.classList.remove('busy'); }
      await apLoadChat(box, true, undefined, 'keep');  // the stamp, or the state it was already decided to
    });
    const cf = box.querySelector('#apf-composer'), ta = box.querySelector('#apf-msg');
    // A message half typed survives a reload (or the panel closing): kept in this browser, per account,
    // until it is sent.
    const keepDraft = (v) => { try { localStorage.setItem(AP_DRAFT(), v); } catch (e) { /* private mode */ } };
    try { ta.value = localStorage.getItem(AP_DRAFT()) || ''; } catch (e) { /* private mode */ }
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px'; keepDraft(ta.value); });
    apCostPaint(box);
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); cf.requestSubmit(); } });
    cf.onsubmit = async (e) => {
      e.preventDefault(); const content = ta.value.trim(); if (!content || cf.dataset.sending) return;
      // Enter submits even while the Send button is disabled, so a second Enter during a slow send
      // sent the message again: one send at a time.
      cf.dataset.sending = '1';
      apErr(box, '');
      try {
        await busy(cf.querySelector('button'), async () => { try { await api('/api/chat', { content }); ta.value = ''; ta.style.height = ''; keepDraft(''); await apLoadChat(box, false, undefined, 'end'); } catch (err) { apErr(box, err.message, err.status === 402); } });
      } finally { delete cf.dataset.sending; }
    };
    apLoadChat(box, true);
    apStopChat();
    // One read at a time, backing off while they fail: a hung or down server used to get three reads
    // every 3s (each tick plus its retries), stacking while they hung.
    const chatTick = paced((cfg) => {
      const b = document.getElementById('autopilot-float');
      return b && apLoadChat(b, false, cfg).then((ok) => { if (ok === false) throw new Error('Chat read failed'); });
    }, 3000);
    apChatWake = () => chatTick(true);
    apChatTimer = setInterval(() => { const b = document.getElementById('autopilot-float'); if (b && apExpanded()) { if (!document.hidden) chatTick(); } else apStopChat(); }, 3000);
    // Market focus: binding on research, deploys and the paper funnel (server enforces it).
    (() => {
      const sel = box.querySelector('#apf-focus'); if (!sel) return;
      sel.onchange = async () => {
        if (sel.disabled) return;
        const prev = sel.dataset.cur || '';
        sel.disabled = true;
        const current = () => box.isConnected !== false && box.querySelector('#apf-focus') === sel;
        try {
          const r = await api('/api/autopilot/focus', { focus: sel.value ? sel.value.split(',') : [] });
          if (S.ap) S.ap.focus = r.focus;
          if (current()) { apFocusOptions(sel, r.focus); apFocusPaint(box, r.focus); apLoadChat(box); }
          paintDashAp();
        } catch (e) { if (current()) { sel.value = prev; apNote(box, e.message); } }
        finally { if (current()) sel.disabled = false; }
      };
      apFocusOptions(sel, (S.ap && S.ap.focus) || []);
    })();
    // The autopilot's research, review and chat share its saved model preference.
    (async () => {
      const sel = box.querySelector('#apf-model'); if (!sel) return;
      const current = () => box.isConnected !== false && box.querySelector('#apf-model') === sel;
      const mdl = await api('/api/models', undefined, { keep: true }).catch(() => ({ models: [], default: '' }));
      if (!current()) return;
      const cur = (S.ap && S.ap.model) || mdl.default;
      sel.innerHTML = (mdl.models || []).map((m) => `<option value="${esc(m.key)}"${m.key === cur ? ' selected' : ''}${m.available === false ? ' disabled' : ''}>${esc(m.label)}${m.available === false ? ' (access pending)' : ''}</option>`).join('');
      sel.onchange = async () => {
        if (!current() || sel.disabled) return;
        sel.disabled = true;
        try { const r = await api('/api/autopilot/model', { model: sel.value }); if (current() && S.ap) S.ap.model = r.model; }
        catch (e) { if (current()) { sel.value = (S.ap && S.ap.model) || cur; apNote(box, e.message); } }
        finally { if (current()) sel.disabled = false; }
      };
    })();
  }
  const AP_FOCUS = [['', 'Any market'], ['crypto', 'Crypto only'], ['btc', 'Bitcoin only'], ['sports', 'Sports only']];
  function apFocusOptions(sel, focus) {
    const cur = (focus || []).join(',');
    const opts = AP_FOCUS.some(([v]) => v === cur) ? AP_FOCUS : AP_FOCUS.concat([[cur, 'Only ' + (focus || []).join(', ')]]);
    sel.innerHTML = opts.map(([v, label]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`).join('');
    sel.dataset.cur = cur;
  }
  function apUpdate(box, d) {
    const m = (d && AP_MODE[d.mode]) || AP_MODE.off;
    box.className = 'apf open' + (m.cls ? ' ' + m.cls : '');
    const label = box.querySelector('#apf-label'); if (label) label.textContent = m.label;
    const on = d ? d.autopilot : (S.me.user && S.me.user.autopilot);
    const ap = box.querySelector('#apf-ap'); if (ap) ap.classList.toggle('on', !!on);
    const sw = box.querySelector('#apf-apswitch'); if (sw && document.activeElement !== sw) sw.checked = !!on;
    apCostPaint(box);
    const copy = box.querySelector('#apf-ap-copy');
    if (copy) copy.innerHTML = on
      ? '<b>Autopilot</b>Researches, deploys and tunes paper strategies on its own, and adjusts your risk &amp; execution controls within safe bounds. It never touches live money without the step below.'
      : '<b>Autopilot</b>Off: it only suggests ideas and changes, and you approve each one. Flip the switch to let it research and trade on paper by itself.';
    if (!d) return;
    // Plain-language summary from the server (what it's doing, why no trades yet, what live needs).
    const story = box.querySelector('#apf-story');
    if (story) {
      // The billing pause has its own line under the switch, so the idle line skips it.
      story.innerHTML = (d.idle && !d.billing_blocked ? `<p class="apf-idle">${apIdleHtml(d.idle, 'data-ap="idle-focus"')}</p>` : '')
        + apStory(d).map((line) => `<p>${esc(line)}</p>`).join('');
      const idleFocus = story.querySelector('[data-ap="idle-focus"]');
      if (idleFocus) idleFocus.onclick = () => apShowFocus(box);
    }
    // Live figures once real money is armed or running. A paper-only panel used to show "Live P&L
    // today $0.00" and a loss budget that can't apply to it, and nothing about the paper book it has.
    const liveInPlay = !!(d.autopilot_live || d.live_running);
    const pnl = (liveInPlay ? d.today_live_pnl : d.today_paper_pnl) || 0;
    const stats = box.querySelector('#apf-stats');
    // Count running strategies across every mode, not just paper — a lone demo strategy
    // used to read as "0 paper", which looked like nothing was running. Match the dashboard.
    const runParts = [
      d.live_running ? `<span class="apf-live">${d.live_running} live</span>` : '',
      d.demo_running ? `${d.demo_running} demo` : '',
      d.paper_running ? `${d.paper_running} paper` : '',
    ].filter(Boolean);
    const runTotal = (d.live_running || 0) + (d.demo_running || 0) + (d.paper_running || 0);
    // The figures sit above the story so "is it making money?" reads first, and the Research row only
    // shows when there's no story (billing pause), since the story already says what research did.
    // Short figures share a row (as many columns as there are figures, two on a phone, the odd
    // one out spanning); the sentence-length ones get full-width rows, so no cell sits empty.
    const short = [
      `<dt>Running</dt><dd>${runTotal ? runParts.join(' ·\u00a0') : 'None'}</dd>`,
      `<dt>${liveInPlay ? 'Live' : 'Paper'} realized today (UTC)</dt><dd class="${pnl < 0 ? 'neg' : (pnl > 0 ? 'pos' : '')}">${usd(pnl, true)}</dd>`,
    ].concat(liveInPlay ? [`<dt>Loss budget left</dt><dd>${usd(d.loss_headroom)} / ${usd(d.daily_loss_limit)}</dd>`] : [])
      // A queued or running review is not a finished one: right after switching on, "Last reviewed just now" claimed a review that hadn't run.
      // Named as on the dashboard's autopilot card ("Last check-in"): the panel said "Last reviewed" beside it.
      .concat(d.review_wait ? [`<dt>Check-in</dt><dd>${d.review_wait.state === 'queued' ? 'Waiting' : 'Silent'} ${waitSpan(d.review_wait.seconds)}</dd>`]
        : d.reviewing ? ['<dt>Last check-in</dt><dd>Reviewing now</dd>'] : d.last_review_at ? [`<dt>Last check-in</dt><dd>${sinceMin(d.last_review_at)}</dd>`] : []);
    if (stats) {
      stats.dataset.cols = short.length;
      stats.innerHTML = short.map((c, i) => `<div${short.length % 2 && i === short.length - 1 ? ' class="apf-tail"' : ''}>${c}</div>`).join('') + `
      ${liveInPlay ? `<div class="apf-wide apf-budget"><dt>Loss budget</dt><dd>Counts live losses booked since 00:00 UTC. Live also stops if your Kalshi account falls ${usd(d.daily_loss_limit)} in a day, open positions included.</dd></div>` : ''}
      ${d.research && !(d.story || []).length ? `<div class="apf-wide"><dt>Research</dt><dd>${d.research.active.length ? 'Researching ' + esc(apMarketNames(d).join(' ·\u00a0')) : 'Not researching right now'} ·\u00a0${Number(d.research.tested_7d).toLocaleString('en-US')} ideas tested this week, ${d.research.passed_7d} passed${d.research.cost_7d ? ', ' + usd(d.research.cost_7d) + ' spent' : ''}</dd></div>` : ''}
      ${d.paper_progress ? `<div class="apf-wide"><dt>Furthest on paper</dt><dd><a href="/strategies/${d.paper_progress.strategy_id}">${esc(d.paper_progress.title || 'Paper strategy')}</a> ·\u00a0${paperCount(d.paper_progress)} ·\u00a0${usd(d.paper_progress.net_pnl, true)}</dd></div>` : ''}`;
    }
    const staleEl = box.querySelector('#apf-stale'); if (staleEl) staleEl.textContent = apStale();
    // The feed's idle pulse reads the status too; repaint it now rather than on the next chat poll.
    const idleEl = box.querySelector('[data-ap-idle]'); if (idleEl) idleEl.textContent = apIdleLine(box);
    const lastEl = box.querySelector('#apf-last'); if (lastEl) lastEl.innerHTML = d.autopilot ? apLastHtml(d.last_action) : '';
    const week = box.querySelector('#apf-week'); if (week) week.innerHTML = d.autopilot ? apWeek(d.week, d) : '';
    const msel = box.querySelector('#apf-model'); if (msel && msel.options.length && d.model && document.activeElement !== msel && !msel.disabled) msel.value = d.model;
    if (Array.isArray(d.focus)) apFocusPaint(box, d.focus);
    const fsel = box.querySelector('#apf-focus');
    if (fsel && Array.isArray(d.focus) && document.activeElement !== fsel && !fsel.disabled && fsel.dataset.cur !== d.focus.join(',')) apFocusOptions(fsel, d.focus);
    const gates = box.querySelector('#apf-gates');
    if (gates) {
      if (d.billing_blocked) {
        // Autopilot is on but can't spend — tell the user WHY it's quiet (so it doesn't look broken).
        gates.innerHTML = d.billing_reason === 'card'
          ? 'Autopilot is paused — <a href="/billing">add a payment method</a> to let it run.' + apStillTrading(d)
          : apReloadFailed(d) ? `Autopilot is paused: ${AP_CARD_FIX}${apStillTrading(d)}`
          : `Autopilot is paused: ${apFloorText()} <a href="/billing">Add credits</a> and it picks up on its own.${apStillTrading(d)}`;
        gates.classList.add('warn');
      } else if (d.credits_low_days != null) {
        gates.innerHTML = `${pausesIn(d.credits_low_days)} <a href="/billing">Add credits or turn on auto-reload</a>.`;
        gates.classList.add('warn');
      } else {
        gates.textContent = apLiveBlock(d) || apLiveArmed(d);
        gates.classList.remove('warn');
      }
    }
    const controls = box.querySelector('#apf-controls');
    if (controls) {
      // A paper-only user sees no red Kill and no greyed live button: Kill appears once real money
      // is armed or running, and the live step once autopilot is on (the gate line says why not yet).
      controls.innerHTML = `${d.autopilot_live
        ? `<button class="btn sm" data-ap="livetoggle" data-on="0">Turn off live</button>`
        : d.autopilot && d.live_enabled ? `<button class="btn sm" data-ap="livearm" ${d.kalshi_connected ? '' : 'aria-disabled="true"'}>Enable live autopilot</button>` : ''}
        ${d.autopilot_live || d.live_running ? '<button class="btn sm danger" data-ap="kill">Kill</button>' : ''}
        <a class="btn sm ghost" href="/deploy">See what's trading</a>`;
      controls.querySelectorAll('[data-ap]').forEach((b) => (b.onclick = (e) => apAction(box, b.dataset.ap, e)));
    }
  }
  // Live armed with nothing live yet reads as "is it trading real money?", so say it outright.
  const apLiveArmed = (d) => d.autopilot_live && !d.live_running ? 'Live autopilot is armed. No strategy is trading real money yet.' : '';
  // Why live autopilot can't be enabled yet (ordered), or '' when all gates pass.
  function apLiveBlock(d) {
    if (!d) return '';
    if (!d.autopilot) return 'Live autopilot can only be turned on after autopilot (paper) is on. It moves a strategy to real money only after the strategy has proven itself on paper, and autopilot is what runs it there. ';
    if (!d.live_enabled) return 'Live trading isn’t available on this server yet. ';  // no live button then, just this line
    if (!d.kalshi_connected) return 'Connect your Kalshi key on the Funds page first. ';
    return '';
  }
  // Read out as well as shown: the live switch, the kill switch and an unmet gate answered only in
  // print, so a reader heard nothing after pressing them.
  function apFlash(box, msg, kind) {
    const f = box.querySelector('#apf-flash');
    if (f) f.innerHTML = `<p class="${kind === 'bad' ? 'error-text' : 'hint'}">${esc(msg)}</p>`;
    if (msg) announce(msg, kind === 'bad');
  }
  // A setting in the panel (the switch, model, markets) that didn't save says why in the panel, read out
  // at once; '' clears it before the next try.
  function apNote(box, msg) {
    const f = box.querySelector('#apf-flash');
    if (!f) { if (msg) alert0(msg); return; }
    f.innerHTML = msg ? `<p class="error-text">${esc(msg)}</p>` : '';
    if (msg) announce(msg, true);
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
  async function apEnableLive(box, confirm) {
    try { await api('/api/autopilot/live', { on: true, confirm }); apFlash(box, 'Live autopilot is on.'); }
    catch (err) { return apFlash(box, err.message, 'bad'); }
    refreshAutopilot(box);
  }
  function hotChart(h) {
    if (!h || h.length < 2) return '<div class="hot-chart none"></div>';
    const W = 104, H = 30, p = 3, lo = Math.min(...h), hi = Math.max(...h), rng = hi - lo || 1;
    const pts = h.map((v, i) => `${(i / (h.length - 1) * (W - p * 2) + p).toFixed(1)},${(H - p - (v - lo) / rng * (H - p * 2)).toFixed(1)}`);
    const [ex, ey] = pts[pts.length - 1].split(',');
    return `<svg class="hot-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true"><polyline points="${pts.join(' ')}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${ex}" cy="${ey}" r="1.9" fill="currentColor"/></svg>`;
  }
  function hotRowHtml(m) {
    const mid = midOf(m), h = m.h || [], delta = h.length >= 2 ? h[h.length - 1] - h[0] : 0;
    const dCents = Math.round(delta * 100), dir = dCents > 0 ? 'pos' : dCents < 0 ? 'neg' : '';
    return `<a class="hot-row" href="${kalshiUrl(m)}" target="_blank" rel="noopener">
      <span class="hot-title">${esc(mktLabel(m))}</span>
      <span class="hot-mid">${hotChart(h)}<span class="hot-price"><b class="fig">${mid == null ? '—' : cents(mid)}</b>${dCents ? `<span class="hot-delta ${dir}">${dCents > 0 ? '+' : '−'}${Math.abs(dCents)}¢</span>` : ''}</span></span>
      <span class="hot-foot">${seriesMarket(m.s) ? `<span class="mk quiet">${esc(seriesMarket(m.s))}</span>` : ''}<span class="hot-vol">${kfmt(m.v24)} vol ·\u00a024h</span>${ICON.ext}</span></a>`;
  }
  function renderHotRail() {
    const rail = document.getElementById('hotrail'); if (!rail) return;
    const open = hotOpen();
    const d = S.hot;
    const rows = d && d.markets && d.markets.length ? d.markets.map(hotRowHtml).join('')
      : `<div class="hot-empty">${d ? 'Warming up — the live book fills in a minute.' : S.hotFail ? 'Hot markets didn\u2019t load. Retrying in a minute.' : loading(120)}</div>`;
    keepFocus(rail, () => { rail.innerHTML = `<button class="hot-tab" data-hot="toggle" aria-expanded="${open}" aria-label="${open ? 'Collapse hot markets' : 'Expand hot markets'}"><span class="hot-tab-label">Hot markets</span><span class="hot-chev">${open ? '‹' : '›'}</span></button>
      <div class="hot-panel">
        <div class="hot-head"><div><span class="hot-kicker">Hot markets</span><span class="hot-now"><span class="hot-dot"></span>Right now</span></div><button class="hot-x" data-hot="toggle" aria-label="Collapse hot markets">‹</button></div>
        <div class="hot-list">${rows}</div>
        <div class="hot-ft">${d && d.at ? 'Updated ' + sinceMin(d.at) : ''} ·\u00a0<a href="/explore">See all markets →</a></div>
      </div>`; });
    rail.querySelectorAll('[data-hot="toggle"]').forEach((b) => b.onclick = (e) => {
      if (e.currentTarget.classList.contains('hot-tab') && open) return; // the spine only expands
      const next = !hotOpen(); localStorage.setItem('tau_hotrail', next ? '1' : '0');
      document.body.classList.toggle('hot-open', next); renderHotRail();
      const to = rail.querySelector(next ? '.hot-x' : '.hot-tab'); if (to && to.focus) to.focus({ preventScroll: true });
    });
    rail.querySelector('.hot-ft a') && (rail.querySelector('.hot-ft a').onclick = (e) => { e.preventDefault(); go('/explore'); });
  }
  // Resolves false when the read failed. The rail is repainted anyway, so its age line counts on from
  // the last snapshot's own time instead of saying "just now" for as long as reads fail.
  async function refreshHot() {
    try { S.hot = await api('/api/explore/hot', undefined, { keep: true }); S.hotFail = false; renderHotRail(); return true; } catch (e) { S.hotFail = true; renderHotRail(); return false; }
  }
  function mountHotRail() {
    if (!S.me || !S.me.user) return;
    document.body.classList.toggle('hot-open', hotOpen());
    if (!document.getElementById('hotrail')) { const a = document.createElement('aside'); a.className = 'hotrail'; a.id = 'hotrail'; document.body.appendChild(a); }
    renderHotRail();
    const stale = !S.hot || !S.hotAt || Date.now() - S.hotAt > 55000;
    if (stale) refreshHot().then((ok) => { if (ok) S.hotAt = Date.now(); });
    if (!hotLoop) { hotLoop = true; setInterval(() => { if (!document.hidden && document.getElementById('hotrail')) refreshHot().then((ok) => { if (ok) S.hotAt = Date.now(); }); }, 60000);
      wakers.add(() => { if (!document.hidden && document.getElementById('hotrail') && S.hotFail) refreshHot().then((ok) => { if (ok) S.hotAt = Date.now(); }); }); }
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
  async function viewBilling() {
    shell('/billing', boardTitle('Billing', 'Credits pay for agent research and chat, billed per token for the model you pick. Paper and live trading themselves are free. The <a href="/research">research form</a> shows what a session usually costs before you start.') +
      '<dl class="figures measure" id="bfigs" style="margin-top:14px"></dl><p class="hint bill-split" id="bsplit"></p>', loading(360));
    let stripe = null, card = null;
    const load = async () => {
      const d = await api('/api/billing?tz=' + new Date().getTimezoneOffset());  // the statement's days are yours
      syncMeBilling(d);
      // Below the research floor no new research starts, so the balance reads as a problem, not a gain.
      const low = d.configured && d.min_run_balance != null && d.balance < d.min_run_balance;
      root.querySelector('#bfigs').innerHTML =
        fig('Credit balance', usd(d.balance), { v: low || d.balance < 0 ? -1 : (d.balance > 0 ? 1 : 0) }) +
        fig('Spent, last 7 days', usd(d.spent_7d), { small: [d.spent_24h != null ? `${usd(d.spent_24h)} in the last 24 hours` : '', `${usd(d.spent)} all time`].filter(Boolean).join(' · ') }) +
        // How long it lasts means until research pauses (under min_run_balance; with payments off nothing
        // pauses, so until $0), and with auto-reload on, when the card is next charged and for how much:
        // "Credits last about 2 days" in red beside auto-reload read as a stop that auto-reload prevents,
        // and at $2.40 it was a day late.
        (low ? fig('Research', 'Paused', { v: -1, small: `a session needs ${usd(d.min_run_balance)} to start` })
          : d.reload_days != null && d.auto_reload && !d.reload_failed
          ? fig('Next auto-reload in', runwayLabel(d.reload_days), { small: `adds ${usd(Math.max(d.min_reload_amount, d.autoreload_amount))}, card charged ${usd(d.autoreload_charge)}, at ${paceWords(d.spent_7d, d.pace_days)}` })
          : d.runway_days != null
          ? fig(d.configured ? 'Research pauses in' : 'Credits last', runwayLabel(d.runway_days), { v: d.runway_days < 3 ? -1 : 0, small: `at ${paceWords(d.spent_7d, d.pace_days)}${d.configured && d.min_run_balance != null ? `, when credits fall under ${usd(d.min_run_balance)}` : ''}` })
          : paceTooSoon(d.pace_days, d.spent_7d) && d.balance > 0 ? fig('Credits last', 'Too soon to tell', { small: 'your first day of research sets the pace' })
          : fig('Welcome credit', usd(d.free_bonus), { small: 'one-time, free' }));
      const split = spendSplit(d.spent_7d_by);
      root.querySelector('#bsplit').innerHTML = split ? `Last 7 days: ${split}.` : '';
      const feeNote = `Credits plus a ${d.topup_fee_pct}% purchase fee.`;
      const payCard = d.cards.find((c) => c.id === d.default_pm) || d.cards[0];
      const payName = payCard ? `your ${esc((payCard.brand || 'card').toUpperCase())} •••• ${esc(payCard.last4 || '')}` : 'your card';
      const reloadWhen = (on, amount, threshold) => on
        ? `<b>On.</b> When a research or chat charge takes your balance to ${usd(threshold)} or less, we charge ${payName} for ${usd(amount)} of credits plus the ${d.topup_fee_pct}% purchase fee.`
        : d.min_run_balance != null
          ? `<b>Off.</b> Below ${usd(d.min_run_balance)} no new research starts and autopilot pauses; a session already running stops at $0. Add credits and it all picks up again.`
          : '<b>Off.</b> When your credits run low, new research sessions won’t start until you add more.';
      // Out of credits (under the floor a research session needs): say what stopped and the next step.
      const apOn = !!(S.me && S.me.user && S.me.user.autopilot);
      const lowNote = !low ? '' : `<div class="notice" role="status">${ICON.warn}<span>${d.balance <= 0 ? 'You’re out of credits' : `You have ${usd(d.balance)} in credits`}. New research needs at least ${usd(d.min_run_balance)} to start, so none is starting${apOn ? ' and autopilot is paused' : ''}. ${
        !d.cards.length ? 'Add a card, then add credits.' : d.auto_reload && d.reload_failed ? 'Auto-reload couldn’t charge your card (see below). Update the card first, then add credits here: they go on the same card.' : d.auto_reload ? 'Auto-reload is on but hasn’t topped you up: add credits here, or check your card.' : 'Add credits here, or turn on auto-reload so it doesn’t stop again.'}${apOn ? ' Autopilot picks up again on its own.' : ''}</span></div>`;
      const cardLines = d.cards.length
        ? `<table class="table stack t-dep"><thead><tr><th>Card</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody>${d.cards.map((c) => `<tr>
            <td class="name" data-lab="Card">${esc((c.brand || 'card').toUpperCase())} •••• ${esc(c.last4 || '')}</td>
            <td data-lab="Expires">${String(c.exp_month).padStart(2, '0')}/${c.exp_year}</td>
            <td data-lab="Status">${c.id === d.default_pm ? '<span class="mk on">Default</span>' : '<span class="mk quiet">Backup</span>'}</td>
            <td class="act" data-lab="">${d.cards.length > 1 ? `<button class="btn sm danger" data-remove="${c.id}">Remove</button>` : '<span class="hint">Only card</span>'}</td></tr>`).join('')}</tbody></table>`
        : '<p class="hint">No card on file. Add one to buy credits or turn on auto-reload.</p>';
      const main = !d.configured
        ? `<div class="notice">${ICON.warn}<span>Payments aren’t enabled on this server yet. You can still use your free credits.</span></div>
           <section class="sect"><div class="sect-head"><h2>Credits &amp; usage</h2><a class="btn sm" href="/api/billing/receipt" download>Download receipt (CSV)</a></div>${ledgerTable(d)}</section>`
        : `${lowNote}<div class="detail bill-detail">
            <div>
              <section class="panel"><h3>Payment method</h3><div id="cards">${cardLines}</div>
                <div id="card-add" style="margin-top:14px">
                  <div class="field"><span>${d.cards.length ? 'Add another card' : 'Add a card'}</span><div id="card-el" class="card-el"></div></div>
                  <div id="card-flash"></div>
                  <button class="btn" id="save-card" style="margin-top:10px">Save card</button>
                </div>
                ${reloadFailNote(d)}
                <div class="autorel-row">
                  <label class="switch"><input type="checkbox" id="autoreload" ${d.auto_reload ? 'checked' : ''}><span>Auto-reload</span></label>
                  <button type="button" class="autorel-edit" id="autorel-edit" aria-expanded="false" aria-controls="autorel-config"><span id="autorel-sum">Reload $${d.autoreload_amount} at $${d.autoreload_threshold}</span><span class="chev">${ICON.chev}</span></button>
                </div>
                <p class="hint autorel-when" id="autorel-when">${reloadWhen(d.auto_reload, d.autoreload_amount, d.autoreload_threshold)}</p>
                <div class="autorel-config" id="autorel-config" hidden>
                  <p class="autorel-line">Reload <input class="input xs" id="reload-amt" type="number" min="${d.min_reload_amount}" step="1" value="${d.autoreload_amount}"> dollars when my balance drops to <input class="input xs" id="reload-thr" type="number" min="${d.min_reload_threshold}" step="1" value="${d.autoreload_threshold}"> dollars.</p>
                  <p class="hint" id="autorel-flash" style="margin-top:4px">Minimum $${d.min_reload_amount} reload, $${d.min_reload_threshold} trigger.</p>
                </div>
              </section>
              <section class="sect"><div class="sect-head"><h2>Credits &amp; usage</h2><a class="btn sm" href="/api/billing/receipt" download>Download receipt (CSV)</a></div>${ledgerTable(d)}</section>
            </div>
            <aside>
              <section class="panel"><h3>Add credits</h3>
                <label class="field"><span>Amount (USD)</span><input class="input" id="topup-amt" type="number" min="${d.min_topup}" max="${d.max_topup}" step="1" value="20"></label>
                <p class="hint" id="topup-note" style="margin-top:8px">${feeNote}</p>
                <button class="btn primary" id="topup-btn" style="margin-top:12px;width:100%" ${d.cards.length ? '' : 'aria-disabled="true"'}>Buy credits</button>
                ${d.cards.length ? '' : '<p class="hint" style="margin-top:8px">Add a card first.</p>'}
                <div id="topup-flash"></div>
              </section>
            </aside>
          </div>`;
      root.querySelector('main').innerHTML = `<div id="flash"></div>${main}`;
      if (!d.configured) return;
      // top-up fee preview
      const amt = root.querySelector('#topup-amt'), note = root.querySelector('#topup-note');
      // At the user's own pace, how long the amount being bought would last: picks the amount for them.
      const perDay = paceDay(d.spent_7d, d.pace_days);
      const lasts = (v) => (perDay && v > 0) ? ` At your pace (${paceWords(d.spent_7d, d.pace_days)}) that's ${runwayLabel(v / perDay).toLowerCase()} of research.` : '';
      // Out of range, it says the range before the press (the server refuses it in the same words).
      const upd = () => { const v = +amt.value || 0; note.textContent = v < d.min_topup || v > d.max_topup
        ? `Add between ${usd(d.min_topup)} and ${usd(d.max_topup)} in credits.`
        : `You'll pay ${usd(topupCharge(v, d.topup_fee_pct))} (${usd(v)} credits + ${d.topup_fee_pct}% fee).${lasts(v)}`; };
      amt.oninput = upd; upd();
      root.querySelector('#topup-btn').onclick = (e) => {
        if (e.currentTarget.getAttribute('aria-disabled')) { flash('#topup-flash', 'Add a card first.', 'bad'); return; }
        busy(e.currentTarget, async () => {
          const credits = +amt.value;
          try {
            const r = await api('/api/billing/topup', { amount: credits });
            const fresh = await refreshed(load());  // refresh balance + ledger, then confirm into the fresh panel
            flash('#topup-flash', `Added ${usd(credits)} in credits. You paid ${usd(r.charged != null ? r.charged : topupCharge(credits, d.topup_fee_pct))} — ${usd(credits)} plus the ${d.topup_fee_pct}% fee. New balance is ${usd(r.balance)}.` + (fresh ? '' : BEHIND), 'good');
          } catch (err) { flash('#topup-flash', err.message, 'bad'); }
        });
      };
      const arBox = root.querySelector('#autoreload'), arAmt = root.querySelector('#reload-amt'), arThr = root.querySelector('#reload-thr');
      const arEdit = root.querySelector('#autorel-edit'), arCfg = root.querySelector('#autorel-config'), arSum = root.querySelector('#autorel-sum');
      arEdit.onclick = () => { const open = arCfg.hidden; arCfg.hidden = !open; arEdit.setAttribute('aria-expanded', String(open)); };
      // "Update card" on a failed auto-reload: the card form above, the same save-card flow; saving
      // a card clears the failure on the server.
      let cardPe = null;
      const arFix = root.querySelector('#autorel-fix');
      if (arFix) arFix.onclick = () => { const add = root.querySelector('#card-add'); if (add.scrollIntoView) add.scrollIntoView({ block: 'center', behavior: 'smooth' }); if (cardPe && cardPe.focus) cardPe.focus(); };
      // What Tau last saved. A save that fails puts the switch, both amounts and the summary back to it:
      // the summary kept saying On after a switch-on failed, and a failed amount change flipped the
      // switch off on screen while auto-reload stayed on. The controls lock until Tau answers, so two
      // quick flips can't land out of order.
      let arSaved = { on: !!d.auto_reload, amount: d.autoreload_amount, threshold: d.autoreload_threshold };
      const arPaint = (on, amount, threshold) => {
        arBox.checked = on; arAmt.value = amount; arThr.value = threshold;
        arSum.textContent = `Reload $${amount} at $${threshold}`;
        const fail = root.querySelector('#autorel-fail'); if (fail) fail.hidden = !on;
        root.querySelector('#autorel-when').innerHTML = reloadWhen(on, amount, threshold);
      };
      const saveAutoReload = async () => {
        const on = arBox.checked;
        const amount = Math.max(d.min_reload_amount, +arAmt.value || d.min_reload_amount);
        const threshold = Math.max(d.min_reload_threshold, +arThr.value || d.min_reload_threshold);
        arPaint(on, amount, threshold);
        [arBox, arAmt, arThr].forEach((x) => { x.disabled = true; });
        try {
          const r = await api('/api/billing/auto-reload', { on, amount, threshold });
          arSaved = { on, amount, threshold };
          // The autopilot card and the research form read the saved auto-reload from S.me (a Billing read
          // refreshes it): a save refreshes it too, or they said the old amount until the next read.
          Object.assign(d, { auto_reload: on, autoreload_amount: amount, autoreload_threshold: threshold },
            r && r.autoreload_charge != null ? { autoreload_charge: r.autoreload_charge } : {});
          syncMeBilling(d);
          flash('#autorel-flash', on ? `On ·\u00a0reloads ${usd(amount)} at ${usd(threshold)}.` : 'Auto-reload off.', 'good');
        } catch (err) { arPaint(arSaved.on, arSaved.amount, arSaved.threshold); flash('#autorel-flash', err.message, 'bad'); }
        finally { [arBox, arAmt, arThr].forEach((x) => { x.disabled = false; }); }
      };
      arBox.onchange = saveAutoReload;
      arAmt.onchange = arThr.onchange = () => { if (arBox.checked) saveAutoReload(); };
      root.querySelectorAll('[data-remove]').forEach((b) => (b.onclick = () => armed(b, 'Confirm remove', () => busy(b, async () => {
        try { await api('/api/billing/remove-card', { payment_method_id: b.dataset.remove }); if (!(await refreshed(load()))) flash('#flash', 'Card removed.' + BEHIND, 'good'); } catch (err) { alert0(err.message); }
      }))));
      // Stripe Payment Element (card + Apple Pay / Google Pay, Link off) — same
      // flow as the sign-in modal, so saving actually works with the config SI.
      try {
        const Stripe = await loadStripe();
        const sp = Stripe(d.publishable_key);
        const si = await api('/api/billing/setup-intent', {});
        const elements = sp.elements({ clientSecret: si.client_secret, appearance: { theme: 'flat', variables: { fontFamily: 'Archivo, sans-serif', colorPrimary: '#191B16', borderRadius: '10px' } } });
        const pe = elements.create('payment', { layout: 'tabs', wallets: { applePay: 'auto', googlePay: 'auto' }, fields: { billingDetails: { address: { country: 'never' } } } });
        pe.mount('#card-el');
        cardPe = pe;
        root.querySelector('#save-card').onclick = (e) => busy(e.currentTarget, async () => {
          flash('#card-flash', '', '');
          let r;
          try { r = await sp.confirmSetup({ elements, redirect: 'if_required', confirmParams: { return_url: location.origin + '/billing', payment_method_data: { billing_details: { address: { country: 'US' } } } } }); }
          catch (err) { flash('#card-flash', stripeFail(err), 'bad'); return; }
          if (r.error) { flash('#card-flash', stripeFail(r.error), 'bad'); return; }
          try { await api('/api/billing/card-added', { payment_method_id: r.setupIntent.payment_method }); }
          catch (err) { flash('#card-flash', err.message, 'bad'); return; }
          flash('#card-flash', 'Card saved.', 'good'); await load();
        });
      } catch (err) { flash('#card-flash', cardFormFail(err).replace('then try again', 'then reload the page'), 'bad'); }
    };
    await load();
  }
  // What a ledger line is, under its name: usage is one model call (the memo names the model), and credits
  // bought show the credits, while the card paid those plus the purchase fee. Amounts are the server's.
  // A charge under a cent (one short model call) shows three decimals instead of a misleading −$0.00.
  const ledgerAmount = (v) => { const n = +v; return n && Math.abs(n) < 0.005 ? (n < 0 ? '−' : '+') + '$' + Math.abs(halfUp(n, 3)).toFixed(3) : usd(v, true); };
  const USAGE_PREFIX = /^Agent usage\s\u00b7\s/;  // the server's memo, "Agent usage" then a middle dot
  // A usage line: what it was for (`item`: research session, autopilot research or check-in, chat)
  // over the model's name (`model`). The server sends both and never the model's internal id.
  // A usage line is one session's calls on one day: it links the research session it paid for and says
  // how many model calls it adds up. A card purchase says what the card paid and its Stripe reference.
  function ledgerNote(r, feePct) {
    if (r.kind === 'usage') {
      const model = r.model ? esc(r.model) : r.memo && !r.item ? esc(r.memo.replace(USAGE_PREFIX, '')) : '';
      return [r.session ? `<a href="/research/${+r.session.id}">${esc(sessionTitle(r.session))}</a>` : '', model,
        +r.calls > 1 ? `${num(r.calls)} model calls` : ''].filter(Boolean).join(' · ');
    }
    if (r.kind === 'topup' || r.kind === 'autoreload') {
      const paid = r.card_charge != null ? `Card charged ${usd(r.card_charge)}` : 'Card charged';
      return (feePct != null ? `${paid}: ${usd(r.amount)} credits plus the ${esc(feePct)}% purchase fee` : paid)
        + (r.stripe_ref ? ` · Stripe ref <span class="ref">${esc(r.stripe_ref)}</span>` : '');
    }
    return '';
  }
  // The time of a line, or the span of a session's calls that day, in the viewer's clock.
  const clockAt = (iso, zone) => { const d = new Date(iso || NaN); return Number.isFinite(d.getTime()) ? d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23', ...(zone ? { timeZoneName: 'short' } : {}) }) : '—'; };
  const lineWhen = (r) => r.first_at && r.first_at !== r.created_at ? `${clockAt(r.first_at)}–${clockAt(r.created_at, true)}` : clockAt(r.created_at, true);
  // A statement day ('2026-10-26', the viewer's day from the server) as a heading: "Today" or "Mon, Oct 26".
  const ledgerDay = (day) => {
    const [y, m, dd] = String(day).split('-').map(Number), d = new Date(y, m - 1, dd);
    if (!Number.isFinite(d.getTime())) return esc(day);
    return d.toDateString() === new Date().toDateString() ? 'Today' : d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  };
  // How the balance came to be over the statement's days (/api/billing math): the balance then, plus
  // credits bought, plus other credits, minus agent usage, is the balance now. The server sends cents
  // that add up. Only what was bought and debited, never a rate.
  function billMath(m) {
    if (!m) return '';
    const rows = [[`Balance ${m.days} days ago`, usd(m.start)],
      [`Credits bought${m.purchases ? ` (${m.purchases} card charge${m.purchases === 1 ? '' : 's'})` : ''}`, usd(m.bought, true)],
      ...(+m.other ? [['Welcome and other credits', usd(m.other, true)]] : []),
      ['Agent usage', usd(-m.usage)], ['Balance now', usd(m.end)]];
    return `<dl class="bill-math">${rows.map(([k, v], i) => `<div${i === rows.length - 1 ? ' class="total"' : ''}><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
  }
  // The last auto-reload failed (/api/billing reload_failed): when, what it tried to add and why, in the
  // user's words, with a way to the card form. Shown by the auto-reload switch while it is on; '' when
  // the last auto-reload didn't fail. The server clears it when one succeeds or a card is saved.
  function reloadFailNote(d) {
    const f = d && d.reload_failed;
    if (!f || !f.text) return '';
    return `<div class="notice bad autorel-fail" id="autorel-fail" role="status"${d.auto_reload ? '' : ' hidden'}>${ICON.warn}<span><b>Auto-reload failed</b> <time datetime="${esc(f.at)}">${settleAt(f.at)}</time>. ${esc(f.text)}<button type="button" class="btn sm" id="autorel-fix">Update card</button></span></div>`;
  }
  // The week's usage by what spent it (/api/billing spent_7d_by), biggest first; '' when nothing did.
  const SPEND_SOURCE = { research: 'your research sessions', autopilot_research: 'autopilot research', autopilot_review: 'autopilot check-ins', chat: 'chat', other: 'other agent calls' };
  const spendSplit = (by) => Object.entries(by || {}).filter(([k, v]) => SPEND_SOURCE[k] && +v >= 0.005)
    .sort((a, b) => b[1] - a[1]).map(([k, v]) => `${SPEND_SOURCE[k]} ${usd(v)}`).join(' \u00b7\u00a0');
  // Billing's statement (/api/billing ledger): the last days, newest first, under a heading per day that
  // says what the day used and added. Each usage line is one session's model calls that day.
  function ledgerTable(d) {
    const rows = d.ledger || [], feePct = d.topup_fee_pct;
    if (!rows.length) return billMath(d.math) + '<p class="hint">No credit activity yet.</p>';
    const days = [];
    rows.forEach((r) => { const last = days[days.length - 1]; if (last && last.day === (r.day || '')) last.rows.push(r); else days.push({ day: r.day || '', rows: [r] }); });
    const line = (r) => `<tr>
      <td class="hint" data-lab="When"><time datetime="${esc(r.created_at)}">${r.day ? lineWhen(r) : settleAt(r.created_at)}</time></td>
      <td class="name" data-lab="Item">${esc((r.kind === 'usage' && r.item) || KIND_LABEL[r.kind] || r.kind)}${ledgerNote(r, feePct) ? `<div class="sub-fig">${ledgerNote(r, feePct)}</div>` : ''}</td>
      <td class="num" data-lab="Amount"><span class="${r.amount >= 0 ? 'gain' : ''}">${ledgerAmount(r.amount)}</span></td></tr>`;
    const head = (g) => {
      // Summed in millionths (the ledger's six places): a float sum can land a hair under a half cent.
      const micros = (rows) => rows.reduce((s, r) => s + Math.round(r.amount * 1e6), 0) / 1e6;
      const used = -micros(g.rows.filter((r) => r.kind === 'usage'));
      const added = micros(g.rows.filter((r) => r.kind !== 'usage'));
      return `<tr class="ledger-day"><td colspan="3" data-lab="Day"><b>${ledgerDay(g.day)}</b><span class="day-sum">${[used >= 0.005 ? `${usd(used)} used` : '', added ? `${usd(added, true)} credits` : ''].filter(Boolean).join(' · ')}</span></td></tr>`;
    };
    const key = d.math ? `Last ${d.math.days} days, newest first. Each research line is one session's model calls that day; open it to see the session. The receipt has every call and every card charge.`
      : 'Newest first. The receipt has every line, with exact amounts.';
    return `${billMath(d.math)}<p class="hint ledger-key">${key}</p><div class="sheet"><table class="table stack t-dep t-ledger"><thead><tr><th>When</th><th>Item</th><th class="num">Amount</th></tr></thead><tbody>${
      days.map((g) => (g.day ? head(g) : '') + g.rows.map(line).join('')).join('')}</tbody></table></div>${d.ledger_cut ? '<p class="hint">Older days are in the receipt.</p>' : ''}`;
  }

  // ---------- admin ----------
  // The admin readout of open positions whose strategy was deleted (repo.orphaned_open_positions).
  const orphanLine = (o) => {
    if (!o || !o.total) return 'None: every open position belongs to a strategy that still exists.';
    const modes = ['paper', 'demo', 'live'].filter((m) => o.by_mode[m]);
    return `${o.total} open position${o.total === 1 ? '' : 's'} (${modes.map((m) => `${m}: ${o.by_mode[m].positions}`).join(', ')}) `
      + `across ${o.users} user${o.users === 1 ? '' : 's'} belong to deleted strategies. The engine no longer settles or flattens them. `
      + modes.map((m) => `${m[0].toUpperCase() + m.slice(1)}: ${usd(o.by_mode[m].cost)} at cost, oldest settles ${when(o.by_mode[m].oldest_close)}.`).join(' ');
  };
  // Broken pages: browser error reports from the last 24h (repo.client_error_groups), grouped by message
  // and page. Every field came from a browser, a signed-out one too, so all of it goes through esc().
  const CE_KIND = { error: 'Uncaught error', rejection: 'Unhandled rejection', api: 'API call failed', view: 'Page bug' };
  // The newest build it came from, and how many older ones (a fix that shipped shows as the old builds only).
  const ceBuild = (v) => (v && v.length ? `build ${esc(v[0])}${v.length > 1 ? ` +${v.length - 1}\u00a0older` : ''}` : 'build unknown');
  const clientErrorTable = (rows) => (!rows || !rows.length ? '<p class="hint">No page errors reported in the last 24 hours.</p>'
    : `<div class="sheet"><table class="table stack t-dep"><thead><tr><th>Error</th><th>Page, theme, build</th><th class="num">Count</th><th>Last seen</th></tr></thead><tbody>${rows.map((r) => `<tr>
      <td class="name" data-lab="Error">${esc(r.message)}<div class="sub-fig">${esc(CE_KIND[r.kind] || r.kind)}${r.at ? ` \u00b7\u00a0${esc(r.at)}` : ''}</div></td>
      <td data-lab="Page, theme, build">${esc(r.path)}<div class="sub-fig">${esc((r.themes || []).join(', ') || '\u2014')} \u00b7\u00a0${ceBuild(r.versions)}</div></td>
      <td class="num" data-lab="Count">${+r.n || 0}${+r.signed_out ? `<div class="sub-fig">${+r.signed_out} signed out</div>` : ''}</td>
      <td class="hint" data-lab="Last seen">${when(r.last_seen)}<div class="sub-fig">first ${when(r.first_seen)}</div></td></tr>`).join('')}</tbody></table></div>`);
  async function viewAdmin() {
    if (!adminViewOn()) return go('/', true);
    shell('/admin', boardTitle('Admin', 'Operator tools: grant credits and see who has signed up.'), `
      <div class="detail">
        <div>
          <section class="sect"><div class="sect-head"><h2>Page errors</h2><span id="ce-count" class="sect-note"></span></div><div id="client-errors">${loading(80)}</div></section>
          <section class="sect"><div class="sect-head"><h2>Users</h2><span id="ucount" class="sect-note"></span></div><div id="users">${loading(200)}</div></section>
        </div>
        <aside>
          <form class="panel" id="grant"><h3>Grant credits</h3>
            <label class="field"><span>User email</span><input class="input" id="g-email" type="email" placeholder="someone@example.com" required></label>
            <label class="field" style="margin-top:10px"><span>Amount (USD, can be negative)</span><input class="input" id="g-amt" type="number" step="1" value="25" required></label>
            <button class="btn primary" type="submit" style="margin-top:12px;width:100%">Grant</button>
            <div id="g-flash"></div>
            <p class="hint" style="margin-top:8px">The user must have signed in at least once.</p>
          </form>
          <form class="panel" id="kill" style="margin-top:14px"><h3>Kill switch</h3>
            <p id="k-state" class="hint">Loading…</p>
            <label class="field"><span>Reason</span><input class="input" id="k-reason" type="text" maxlength="200" placeholder="why you are halting"></label>
            <button class="btn danger" type="submit" id="k-btn" style="margin-top:12px;width:100%">Halt new buys</button>
            <div id="k-flash"></div>
            <p class="hint" style="margin-top:8px">Stops every new live and demo buy within about 5 seconds. Exits always run.</p>
          </form>
          <section class="panel" id="orphans" style="margin-top:14px"><h3>Orphaned positions</h3>
            <p id="o-state" class="hint">Loading…</p>
          </section>
        </aside>
      </div>`);
    const load = async () => {
      const d = await api('/api/admin');
      root.querySelector('#ucount').textContent = `${d.users.length} shown`;
      root.querySelector('#o-state').textContent = orphanLine(d.orphaned_open);
      const ce = d.client_errors || [];
      root.querySelector('#ce-count').textContent = ce.length ? `last 24h \u00b7\u00a0${ce.reduce((a, r) => a + (+r.n || 0), 0)} reports` : 'last 24h';
      root.querySelector('#client-errors').innerHTML = clientErrorTable(ce);
      root.querySelector('#users').innerHTML = `<div class="sheet"><table class="table stack t-dep"><thead><tr><th>Email</th><th>Name</th><th>Joined</th><th class="num">Balance</th></tr></thead><tbody>${d.users.map((u) => `<tr>
        <td class="name" data-lab="Email">${esc(u.email)}</td><td data-lab="Name">${esc(u.name || '')}</td>
        <td class="hint" data-lab="Joined">${when(u.created_at)}</td><td class="num" data-lab="Balance">${usd(u.balance)}</td></tr>`).join('')}</tbody></table></div>`;
    };
    root.querySelector('#grant').onsubmit = async (e) => {
      e.preventDefault();
      await busy(e.target.querySelector('[type=submit]'), async () => {
        try {
          const r = await api('/api/admin/grant', { email: root.querySelector('#g-email').value.trim(), amount: +root.querySelector('#g-amt').value });
          flash('#g-flash', `Granted. ${esc(r.email)} balance: ${usd(r.balance)}.`, 'good'); await load();
        } catch (err) { flash('#g-flash', err.message, 'bad'); }
      });
    };
        const killShow = (k) => {
      const st = root.querySelector('#k-state'), btn = root.querySelector('#k-btn');
      st.innerHTML = k.on || k.env_on
        ? `<span class="mk on">ON</span> New buys are halted${k.reason ? `: ${esc(k.reason)}` : ''}${k.by ? ` <small class="hint">by ${esc(k.by)}</small>` : ''}${k.env_on ? ' <small class="hint">(also set in the server env)</small>' : ''}`
        : 'Off. Orders flow normally.';
      btn.textContent = k.on ? 'Resume buys' : 'Halt new buys';
      btn.className = k.on ? 'btn primary' : 'btn danger';
      btn.dataset.on = k.on ? '1' : '';
    };
    api('/api/admin/kill-switch').then((k) => { killShow(k); }).catch((err) => { flash('#k-flash', err.message, 'bad'); });
    root.querySelector('#kill').onsubmit = async (e) => {
      e.preventDefault();
      const btn = root.querySelector('#k-btn');
      const run = () => busy(btn, async () => {
        try {
          const k = await api('/api/admin/kill-switch', { on: !btn.dataset.on, reason: root.querySelector('#k-reason').value.trim() });
          killShow(k);
        } catch (err) { flash('#k-flash', err.message, 'bad'); }
      });
      // Halting goes at once; resuming lets new buys flow again, so it asks first.
      return btn.dataset.on ? armed(btn, 'Confirm resume', run) : run();
    };
    await load();
  }

  // ---------- system map ----------
  // A curated signal-flow graph of the real architecture (the design is stable,
  // so the topology is hand-laid for legibility); live telemetry is overlaid so
  // the map shows what the running codebase is doing right now.
  const SYS_H = 66, SYS_DBH = 110;
  const SYS_NODES = [
    { id: 'kalshi', x: 40, y: 40, w: 150, label: 'Kalshi API', sub: 'markets + order book', ext: 1 },
    { id: 'coinbase', x: 40, y: 150, w: 150, label: 'Coinbase', sub: 'BTC spot price', ext: 1 },
    { id: 'bedrock', x: 40, y: 330, w: 150, label: 'Claude ·\u00a0Bedrock', sub: 'the research agent', ext: 1 },
    { id: 'stripe', x: 40, y: 460, w: 150, label: 'Stripe', sub: 'cards + credits', ext: 1 },
    { id: 'forward', x: 250, y: 30, w: 158, label: 'Forward collector', sub: 'Kalshi book → DB' },
    { id: 'cb_coll', x: 250, y: 150, w: 158, label: 'Coinbase collector', sub: '1-minute candles' },
    { id: 'features', x: 250, y: 270, w: 158, label: 'Feature builder', sub: 'per-minute features' },
    { id: 'web', x: 250, y: 455, w: 158, label: 'Web server', sub: 'app.server ·\u00a0SPA + API' },
    { id: 'db', x: 490, y: 205, w: 150, label: 'Database', sub: 'RDS MySQL', big: 1 },
    { id: 'agents', x: 720, y: 40, w: 158, label: 'Research agents', sub: 'app.worker ·\u00a0hypotheses' },
    { id: 'backtest', x: 720, y: 160, w: 158, label: 'Backtester', sub: 'honest, out-of-sample' },
    { id: 'sim_engine', x: 720, y: 300, w: 158, label: 'Paper engine', sub: 'simulated fills' },
    { id: 'live_engine', x: 720, y: 460, w: 158, label: 'Live engine', sub: 'real Kalshi orders' },
  ];
  const SYS_EDGES = [
    ['kalshi', 'forward'], ['coinbase', 'cb_coll'], ['forward', 'db'], ['cb_coll', 'db'],
    ['forward', 'features'], ['features', 'db'], ['bedrock', 'agents'], ['db', 'agents'],
    ['agents', 'backtest'], ['backtest', 'db'], ['db', 'sim_engine'], ['db', 'live_engine'],
    ['kalshi', 'live_engine'], ['stripe', 'web'], ['web', 'db'], ['db', 'web'],
  ];
  const SYS_DESC = {
    kalshi: 'Kalshi’s REST + websocket feed — the markets, their order books, and settled results. The source of truth we trade against.',
    coinbase: 'Coinbase BTC spot candles — the underlying price the 15-minute and 5pm markets settle on.',
    bedrock: 'Claude on Amazon Bedrock. The agent that reads an idea, writes strategy specs, and judges backtests. Metered per token.',
    stripe: 'Card vaulting + credit charges. Agent usage is billed per token against prepaid credits.',
    forward: 'data_pipeline/forward_collector.py — snapshots every live Kalshi market’s book on a tick, into forward_quotes / market_candles / markets.',
    cb_coll: 'data_pipeline/coinbase_collector.py — pulls 1-minute BTC candles into btc_candles_1m.',
    features: 'feature_1m_collector.py — builds the per-minute model features both the sim and live paths read.',
    web: 'app/server.py — the stdlib HTTP server: the SPA, the JSON API, Google sign-in, sessions, billing, and the admin surfaces.',
    db: 'Amazon RDS MySQL. Every collector writes here and every engine + the app reads here. One source of truth.',
    agents: 'app/worker.py (agents) — claims research/chat runs and drives Claude through the research loop, writing strategies + a live event log.',
    backtest: 'app/trading/backtest.py — runs each hypothesis on data it never saw and applies the deployment gates. Same spec the engines run.',
    sim_engine: 'app/trading/engine.py on paper money — prices from the live book, fills against the shown size, tracks P&L without real orders.',
    live_engine: 'app/trading/engine.py (the same engine) — places real orders: live money in a user’s own Kalshi account, demo on Kalshi’s sandbox. Live money also needs Tau’s live switch on, the user’s own opt-in and enough paper evidence.',
  };
  const sysNode = (id) => SYS_NODES.find((n) => n.id === id);
  function sysEdgePath(a, b) {
    const na = sysNode(a), nb = sysNode(b);
    const ha = na.big ? SYS_DBH : na.ext ? SYS_H : SYS_H, hb = nb.big ? SYS_DBH : SYS_H;
    const x1 = na.x + na.w, y1 = na.y + ha / 2, x2 = nb.x, y2 = nb.y + hb / 2;
    const dx = Math.max(40, (x2 - x1) * 0.5);
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }
  async function viewSystem() {
    const edges = SYS_EDGES.map(([a, b], i) => `<path class="sys-edge" data-e="${a}" id="se${i}" d="${sysEdgePath(a, b)}" />`).join('');
    const nodes = SYS_NODES.map((n) => {
      const h = n.big ? SYS_DBH : SYS_H;
      return `<g class="sys-node ${n.ext ? 'ext' : ''}" data-id="${n.id}" transform="translate(${n.x},${n.y})" tabindex="0" role="button" aria-label="${esc(n.label)}">
        <rect width="${n.w}" height="${h}" rx="${n.ext ? 9 : 3}"></rect>
        <text class="t" x="12" y="23">${esc(n.label)}</text>
        <text class="s" x="12" y="41">${esc(n.sub)}</text>
        <text class="m" x="12" y="${h - 12}" data-m="${n.id}"></text>
        <circle class="pulse" cx="${n.w - 13}" cy="15" r="4"></circle>
      </g>`;
    }).join('');
    shell('/system', boardTitle('System', 'A live map of the pipeline — every box is a real part of the codebase, every line is data flowing. It refreshes on its own so you can see what’s running.'),
      `<div class="sysmap">
         <div class="sys-wrap"><svg viewBox="0 0 900 540" preserveAspectRatio="xMidYMid meet" id="syssvg" aria-label="System map">${edges}${nodes}</svg></div>
         <aside class="sys-side">
           <section class="panel" id="sys-detail"><h3>Pick a box</h3><p class="hint">Click any part of the system to see what it does and what it’s doing right now.</p></section>
           <section class="sect" style="margin-top:16px"><div class="sect-head"><h2>Live activity</h2><span class="sys-live" id="sys-stamp"></span></div><ol class="log sys-feed" id="sys-feed"></ol></section>
         </aside>
       </div>`);
    const svg = root.querySelector('#syssvg');
    const detail = root.querySelector('#sys-detail');
    // Drill-down: component -> module -> function. `codeState` holds where we
    // are; while it's set, the 4s poll must not stomp the panel with showDetail.
    let codeState = null;  // null = component overview; else {id, module?}
    const showDetail = (id) => {
      codeState = null;
      const n = sysNode(id), L = S.sysLive && S.sysLive[id];
      const open = n.ext ? '' : `<p style="margin-top:12px"><button class="btn sm" data-code-open="${esc(id)}">Open the code ›</button></p>`;
      // Admin-only storage breakdown on the DB node: which tables eat the volume, so a refilling
      // table is visible long before the disk fills (the storage-full outage had no such warning).
      const tbls = (id === 'db' && L && L.top_tables && L.top_tables.length)
        ? `<div class="sys-tables"><b>Largest tables</b><ul>${L.top_tables.map((t) =>
            `<li><span>${esc(t.table)}</span><span>${t.mb >= 1024 ? (t.mb / 1024).toFixed(1) + ' GB' : num(t.mb) + ' MB'}</span></li>`).join('')}</ul></div>`
        : '';
      detail.innerHTML = `<h3>${esc(n.label)}</h3><p class="sys-metric" id="sys-dm">${metricText(id, L) || ''}</p><p class="hint" style="margin-top:8px">${esc(SYS_DESC[id] || '')}</p>${tbls}${open}`;
    };
    const modName = (p) => p.split('/').pop();
    const crumbs = (parts) => `<nav class="sys-crumb">${parts.map((p, i) =>
      i === parts.length - 1 ? `<span>${esc(p.t)}</span>` : `<a href="#" ${p.a}>${esc(p.t)}</a> ›`).join(' ')}</nav>`;
    const codePanel = async (q, render) => {
      detail.innerHTML = '<p class="hint">Loading…</p>';
      let d; try { d = await api('/api/system/code?' + q); } catch (e) { detail.innerHTML = `<p class="hint">${esc(e.message)}</p>`; return null; }
      detail.innerHTML = render(d);
      return d;
    };
    const openModules = (id) => {
      codeState = { id };
      const label = (sysNode(id) || {}).label || id;
      return codePanel('component=' + encodeURIComponent(id), (d) =>
        crumbs([{ t: label, a: `data-detail="${esc(id)}"` }, { t: 'modules' }]) +
        `<h3>Modules</h3><ul class="sys-list">${d.modules.map((m) =>
          `<li><a href="#" data-mod="${esc(m.path)}">${esc(m.name)}</a> <span class="sys-dim">${m.symbols} defs ·\u00a0${m.lines} lines</span>${m.doc ? `<div class="hint">${esc(m.doc)}</div>` : ''}</li>`).join('')}</ul>`);
    };
    const openModule = (id, mod) => {
      codeState = { id, module: mod };
      const label = (sysNode(id) || {}).label || id;
      return codePanel('module=' + encodeURIComponent(mod), (d) => {
        const fn = (f) => `<li><a href="#" data-fn="${esc(f.qual)}" data-fnmod="${esc(mod)}"><code>${esc(f.signature)}</code></a>${f.doc ? `<div class="hint">${esc(f.doc)}</div>` : ''}</li>`;
        const cls = d.classes.map((c) => `<li class="sys-cls"><code>class ${esc(c.name)}</code>${c.doc ? `<div class="hint">${esc(c.doc)}</div>` : ''}<ul class="sys-list">${c.methods.map(fn).join('')}</ul></li>`).join('');
        return crumbs([{ t: label, a: `data-detail="${esc(id)}"` }, { t: 'modules', a: `data-code-open="${esc(id)}"` }, { t: modName(mod) }]) +
          `<h3>${esc(modName(mod))}</h3>` +
          (d.functions.length ? `<ul class="sys-list">${d.functions.map(fn).join('')}</ul>` : '') +
          (cls ? `<ul class="sys-list">${cls}</ul>` : '') +
          (d.functions.length || cls ? '' : '<p class="hint">No top-level functions or classes.</p>');
      });
    };
    const openFunction = (id, mod, qual) => {
      codeState = { id, module: mod };
      const label = (sysNode(id) || {}).label || id;
      const refs = (list) => list.length ? `<ul class="sys-list">${list.map((r) =>
        `<li><a href="#" data-fn="${esc(r.qual)}" data-fnmod="${esc(r.module)}">${esc(r.qual)}</a> <span class="sys-dim">${esc(modName(r.module))}</span></li>`).join('')}</ul>` : '<p class="hint">None found in the mapped source.</p>';
      return codePanel('module=' + encodeURIComponent(mod) + '&func=' + encodeURIComponent(qual), (d) =>
        crumbs([{ t: label, a: `data-detail="${esc(id)}"` }, { t: 'modules', a: `data-code-open="${esc(id)}"` }, { t: modName(mod), a: `data-mod="${esc(mod)}"` }, { t: d.name }]) +
        `<h3><code>${esc(d.qual)}</code></h3><p class="hint">${esc(modName(mod))} ·\u00a0line ${d.lineno}</p>` +
        `<pre class="sys-src"><code>${esc(d.source)}</code></pre>` +
        `<h3 style="margin-top:14px">Calls (callees)</h3>${refs(d.callees)}` +
        `<h3 style="margin-top:14px">Called by (callers)</h3>${refs(d.callers)}`);
    };
    detail.addEventListener('click', (e) => {
      const a = e.target.closest('[data-code-open],[data-mod],[data-fn],[data-detail]');
      if (!a || !detail.contains(a)) return;
      e.preventDefault();
      if (a.dataset.detail != null) showDetail(a.dataset.detail);
      else if (a.dataset.codeOpen != null) openModules(a.dataset.codeOpen);
      else if (a.dataset.fn != null) openFunction((codeState && codeState.id), a.dataset.fnmod, a.dataset.fn);
      else if (a.dataset.mod != null) openModule((codeState && codeState.id), a.dataset.mod);
    });
    svg.querySelectorAll('.sys-node').forEach((g) => {
      const act = () => { svg.querySelectorAll('.sys-node.sel').forEach((x) => x.classList.remove('sel')); g.classList.add('sel'); showDetail(g.dataset.id); };
      g.addEventListener('click', act);
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(); } });
    });
    const fresh = (age) => age == null ? 'down' : age < 75 ? 'live' : age < 300 ? 'warn' : 'down';
    function metricText(id, L) {
      if (!L) return '';
      const n = sysNode(id);
      if (n && n.ext) {
        if (id === 'kalshi' && L.markets) return `${num(L.markets)} markets ·\u00a0${L.series} series`;
        return 'connected';
      }
      if (id === 'db') return `${L.size_mb >= 1024 ? (L.size_mb / 1024).toFixed(0) + ' GB' : num(L.size_mb) + ' MB'} ·\u00a0${compact(L.rows)} rows`;
      if (id === 'web') return L.users != null ? `${num(L.users)} users ·\u00a0serving` : 'online ·\u00a0serving';
      if (id === 'agents') return `${L.running} running ·\u00a0${L.queued} queued ·\u00a0${num(L.done)} done`;
      if (id === 'backtest') return `${num(L.strategies)} strategies tested`;
      if (L.ext) return 'connected';
      const a = L.age == null ? '—' : L.age < 90 ? `${L.age}s ago` : L.age < 5400 ? `${Math.round(L.age / 60)}m ago` : 'stale';
      if (id === 'forward') return `${num(L.rows)} ${L.unit} ·\u00a0${a}`;
      if (id === 'cb_coll' || id === 'features') return `${num(L.rows)} ${L.unit} ·\u00a0${a}`;
      // Running deployments per mode (every user's): live money and demo are named apart, never summed.
      if (id === 'sim_engine') return `${num(L.paper)} paper running ·\u00a0${a}`;
      if (id === 'live_engine') return `${num(L.live)} live ·\u00a0${num(L.demo)} demo ·\u00a0${a}`;
      return a;
    }
    // A verdict reads as the run page's plain note (server gate_explain.event_note) when it has one,
    // after the idea's title; else its own message, minus the status word the row doesn't need.
    const sysVerdict = (e) => {
      const n = e.data && e.data.note;
      if (n) return e.data.title ? `${e.data.title}: ${n}` : n;
      return e.message.replace(/^(PASSED|VOID|FAILED)\s*[-–]\s*/, '');
    };
    const load = async () => {
      let d; try { d = await api('/api/admin/system'); } catch (e) { return; }
      S.sysLive = d.nodes;
      SYS_NODES.forEach((n) => {
        const L = d.nodes[n.id]; const g = svg.querySelector(`.sys-node[data-id="${n.id}"]`);
        const mt = svg.querySelector(`[data-m="${n.id}"]`); if (mt) mt.textContent = metricText(n.id, L);
        const st = n.ext ? 'live' : (L && 'age' in L) ? fresh(L.age) : (n.id === 'web' || n.id === 'db') ? 'live' : 'idle';
        g.setAttribute('data-st', st);
      });
      // light up edges whose source is live
      svg.querySelectorAll('.sys-edge').forEach((p) => {
        const src = svg.querySelector(`.sys-node[data-id="${p.dataset.e}"]`);
        p.classList.toggle('active', !!src && (src.getAttribute('data-st') === 'live'));
      });
      const sel = svg.querySelector('.sys-node.sel'); if (sel && !codeState) showDetail(sel.dataset.id);
      root.querySelector('#sys-stamp').textContent = 'updated ' + clock(d.now);
      const feed = root.querySelector('#sys-feed');
      feed.innerHTML = d.events.length ? d.events.map((e) => `<li class="${e.kind === 'error' ? 'error' : ''}"><time>${clock(e.created_at)}</time><span>${e.kind === 'verdict' ? esc(sysVerdict(e)) : esc(e.message)}</span></li>`).join('') : '<li><span class="hint">Quiet right now.</span></li>';
    };
    await load();
    poll(load, 4000);
  }

  setupAnnouncer();
  guardArmedRepeat();
  setupGlossary();
  render();
})();
