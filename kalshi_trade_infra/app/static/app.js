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
  };
  // One drawn marker; a single top-layer popover serves them all (no clipping in tables).
  const glo = (key) => `<button type="button" class="info" data-glo="${key}" aria-label="What does “${GLOSSARY[key][0]}” mean?">${ICON.info}</button>`;
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
      try { const d = await api('/api/users/mention?q=' + encodeURIComponent(token.q)); items = d.users || []; }
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
  const usd = (v, signed = false) => {
    if (v == null || Number.isNaN(+v)) return '—';
    const n = +v;
    const s = '$' + (Math.abs(n) >= 100000 ? fmt0.format(Math.abs(n)) : fmt2.format(Math.abs(n)));
    if (n < 0) return '−' + s;
    return signed && n > 0 ? '+' + s : s;
  };
  const pct = (v, signed = true) => (v == null ? '—' : (v < 0 ? '−' : signed && v > 0 ? '+' : '') + Math.abs(v * 100).toFixed(1) + '%');
  const cents = (v) => (v == null ? '—' : Math.round(v * 100) + '¢');
  const isPerpetual = (s) => s.kind === 'perpetual' || s.market === 'btc_perp' || s.key === 'btc_perp' || (s.spec && s.spec.market === 'btc_perp');
  const researchOnly = (s) => s.research_only === true || isPerpetual(s);
  const researchBadge = (s) => researchOnly(s) ? '<span class="mk quiet">Research only</span>' : '';
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
  const clock = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  const num = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US'));
  // Compact count for tight spaces (system-map node metrics): 1.1M, 352k, 940.
  const compact = (n) => (n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : num(n));
  const age = (sec) => (sec == null ? 'never' : sec < 90 ? sec + 's' : sec < 5400 ? Math.round(sec / 60) + 'm' : sec < 172800 ? Math.round(sec / 3600) + 'h' : Math.round(sec / 86400) + 'd');
  const marketLabel = (k) => ((S.me && S.me.markets.find((m) => m.key === k)) || { label: k }).label;
  // Short, consistent chip labels for every market; unknown keys fall back to the
  // server's full label, never the raw key (keeps the market chips uniform).
  const MKT_SHORT = {
    btc15m: 'BTC 15-min', btc_daily: 'BTC 5pm', eth15m: 'ETH 15-min', eth_daily: 'ETH 5pm',
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
  // Link a strategy's market to its Kalshi series page.
  const marketKalshiUrl = (k) => { const m = (S.me && S.me.markets || []).find((x) => x.key === k); return m && m.series ? `https://kalshi.com/markets/${m.series.toLowerCase()}` : null; };
  const dirLabel = (k) => { if (!k) return 'Session'; const d = S.me && S.me.directions.find((x) => x.key === k); return d ? d.label : String(k).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()); };
  const sessionTitle = (r) => (r.prompt && r.prompt.trim()) ? r.prompt.trim() : (dirLabel(r.direction) + ' \u00b7 ' + marketShort(r.market));

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
    face.querySelector('[data-vol]').textContent = `${kfmt(m.vol24)} vol \u00b7 24h`;
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
  async function api(path, body, cfg) {
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
    try { res = await fetch(path, opts); }
    catch (e) { throw new ApiError(0, ctl && ctl.signal.aborted ? "Tau is taking too long to respond." : "Can't reach Tau. Check your connection."); }
    finally { if (tid) clearTimeout(tid); }
    let data = {};
    try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
    if (res.status === 401 && path !== '/api/me') { go('/signin'); throw new ApiError(401, 'Please sign in.'); }
    if (!res.ok) throw new ApiError(res.status, data.error || 'Request failed (' + res.status + ').');
    return data;
  }

  // ---------- router ----------
  const routes = [
    [/^\/signin$/, viewSignin],
    [/^\/(?:dashboard)?$/, viewDashboard],
    [/^\/research$/, viewResearch],
    [/^\/research\/(\d+)$/, viewRun],
    [/^\/strategies$/, viewStrategies],
    [/^\/strategies\/(\d+)$/, viewStrategy],
    [/^\/deploy$/, viewDeploy],
    [/^\/community$/, viewCommunity],
    [/^\/explore$/, viewExplore],
    [/^\/billing$/, viewBilling],
    [/^\/admin$/, viewAdmin],
    [/^\/system$/, viewSystem],
    [/^\/(?:funds|settings\/account)$/, viewFunds],
    [/^\/devlog$/, viewDevLog],
    [/^\/settings$/, viewSettings],
    [/^\/terms$/, viewTerms],
    [/^\/privacy$/, viewPrivacy],
  ];
  // Public routes: viewable signed-OUT, so the boot guard must not force /api/me + a signin bounce.
  const PUBLIC = new Set(['/signin', '/terms', '/privacy']);
  function go(path, replace) {
    if (replace) history.replaceState(null, '', path); else history.pushState(null, '', path);
    render();
  }
  window.addEventListener('popstate', render);
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[href^="/"]');
    if (!a || a.target || e.metaKey || e.ctrlKey || e.shiftKey || a.hasAttribute('download') || a.dataset.native != null) return;
    e.preventDefault();
    go(a.getAttribute('href'));
  });

  function clearTimers() { if (S.perps) { S.perps.destroy(); S.perps = null; } S.timers.forEach(clearInterval); S.timers = []; }
  function poll(fn, ms) {
    const gen = S.gen;
    const id = setInterval(() => { if (!document.hidden && gen === S.gen) fn().catch(() => {}); }, ms);
    S.timers.push(id);
  }
  // SPA deploys only take effect on a full reload. Check the server's build hash on each
  // navigation (throttled); if it changed, offer a one-click reload instead of silent staleness.
  let _verAt = 0;
  async function checkVersion() {
    if (!window.__BUILD__ || Date.now() - _verAt < 30000 || document.getElementById('verbar')) return;
    _verAt = Date.now();
    try {
      const d = await api('/api/version');
      if (d && d.v && d.v !== window.__BUILD__) {
        const bar = document.createElement('div');
        bar.id = 'verbar'; bar.className = 'verbar';
        bar.innerHTML = `<span>A new version of Tau is ready.</span><button id="verreload" class="btn sm">Reload</button>`;
        document.body.appendChild(bar);
        bar.querySelector('#verreload').onclick = () => location.reload(true);
      }
    } catch (e) { /* best-effort */ }
  }

  async function render() {
    clearTimers();
    checkVersion();
    S.gen++;
    window.scrollTo(0, 0);
    const path = location.pathname;
    if (path === '/signin') { const f = document.getElementById('autopilot-float'); if (f) f.remove(); }
    const match = routes.map(([re, fn]) => [path.match(re), fn]).find(([m]) => m);
    if (!S.me && !PUBLIC.has(path)) {
      // Boot: don't sit on a blank white page if /api/me is slow. Paint a branded splash after a
      // short delay (so a fast boot never flashes it), and time the call out. A 401 means genuinely
      // signed out (-> signin); ANY other failure (slow/overloaded/offline) is transient, so show a
      // retry screen instead of spuriously bouncing a signed-in user to signin.
      let splashTid = root.firstChild ? null : setTimeout(() => { if (!S.me) root.innerHTML = bootSplash(); }, 250);
      try { S.me = await api('/api/me', undefined, { timeoutMs: 12000 }); }
      catch (e) {
        if (splashTid) clearTimeout(splashTid);
        if (e.status === 401) return go('/signin', true);
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
    try { await match[1](...match[0].slice(1)); } catch (e) { if (e.status !== 401) shell('', boardTitle('Something went wrong'), notice(e.message, 'bad')); }
    root.setAttribute('aria-busy', 'false');
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
          <p class="wl-sub">Tau meters the agent by the token. Add a card now, and we'll give you $${S.me.free_bonus} in credits — free.</p>
          <div id="pay-el" class="pay-el">${loading(120)}</div>
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
      await api('/api/logout', {}).catch(() => {}); S.me = null; closePay(); go('/signin');
    };
    // Animated showcase reel on the left.
    const stage = dlg.querySelector('#pay-stage'), cap = dlg.querySelector('#pay-cap'), dots = dlg.querySelector('#pay-dots');
    dots.innerHTML = PAY_SHOW.map((_, i) => `<button type="button" class="pay-dot${i === 0 ? ' on' : ''}"></button>`).join('');
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
      const state = await api('/api/billing');
      if (!state.configured) { dlg.querySelector('#pay-el').innerHTML = ''; hint.innerHTML = '<p class="wl-err">Payments aren’t enabled on this server yet.</p>'; dlg.querySelector('#pay-submit').setAttribute('aria-disabled', 'true'); return; }
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
          } catch (err) { hint.innerHTML = `<p class="wl-err">${esc(err.message || 'Could not save the card.')}</p>`; return; }
          if (r.error) { hint.innerHTML = `<p class="wl-err">${esc(r.error.message)}</p>`; return; }
          try { await api('/api/billing/card-added', { payment_method_id: r.setupIntent.payment_method }); } catch (err) { hint.innerHTML = `<p class="wl-err">${esc(err.message)}</p>`; return; }
          S.me = await api('/api/me');
          closePay();
          render();
        });
      };
    } catch (err) { dlg.querySelector('#pay-el').innerHTML = ''; hint.innerHTML = `<p class="wl-err">${esc(err.message)}</p>`; }
  }

  // ---------- shell ----------
  const NAV = [['/', 'Dashboard', 'dashboard'], ['/research', 'Research', 'research'], ['/strategies', 'Strategies', 'strategies'], ['/explore', 'Explore', 'explore'], ['/deploy', 'Deploy', 'deploy'], ['/community', 'Community', 'community'], ['/funds', 'Funds', 'funds'], ['/devlog', 'Dev Logs', 'devlog']];
  // The operator can flip into a plain-user view. Only their own account is an
  // admin at all (server decides); the toggle just hides the admin surface so
  // they can see what a normal user sees. Default: admin view on.
  const isAdmin = () => !!(S.me && S.me.is_admin);
  const adminViewOn = () => isAdmin() && localStorage.getItem('tau_admin_off') !== '1';
  async function wireBell() {
    const wrap = root.querySelector('.bell-wrap');
    if (!wrap) return;
    const trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
    const dot = wrap.querySelector('.bell-dot'), list = wrap.querySelector('#bell-list');
    const close = () => { menu.hidden = true; trig.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', onDoc, true); };
    const onDoc = (e) => { if (!wrap.contains(e.target)) close(); };
    const paint = (d) => {
      dot.hidden = !d.unread;
      list.innerHTML = d.items.length
        ? d.items.map((n) => `<a class="notif ${n.read ? '' : 'unread'}" href="${n.link || '#'}">${esc(n.body)}<time>${when(n.created_at)}</time></a>`).join('')
        : '<p class="bell-empty">No notifications yet.</p>';
    };
    let data = { unread: 0, items: [] };
    try { data = await api('/api/notifications'); paint(data); } catch (e) { return; }  // bell is best-effort
    trig.onclick = async (e) => {
      e.stopPropagation();
      if (!menu.hidden) { close(); return; }
      menu.hidden = false; trig.setAttribute('aria-expanded', 'true'); document.addEventListener('click', onDoc, true);
      if (data.unread) {
        data.unread = 0; dot.hidden = true;
        list.querySelectorAll('.notif.unread').forEach((n) => n.classList.remove('unread'));
        api('/api/notifications/read', {}).catch(() => {});
      }
    };
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
        <span class="asof">${adminToggle}<span class="bell-wrap"><button class="bell-trig" data-action="bell" aria-haspopup="true" aria-expanded="false" aria-label="Notifications"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg><span class="bell-dot" hidden></span></button><span class="bell-menu" hidden><div class="bell-head"><b>Notifications</b></div><div class="bell-list" id="bell-list"></div></span></span><span class="profile"><button class="profile-trig" data-action="profile" aria-haspopup="true" aria-expanded="false">${esc(u.name || u.email)}<svg class="profile-chev" width="9" height="9" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg></button><span class="profile-menu" hidden><a href="/settings">Settings</a><a href="/billing">Billing</a><a href="/terms">Terms</a><a href="/privacy">Privacy</a><button class="profile-item" data-action="signout">Sign out</button></span></span></span>
      </div></header>
      <nav class="services" aria-label="Sections"><div class="services-in">${nav}</div></nav>
      <div class="wrap">
        <div id="boardbody">${board}</div>
        <main id="main" tabindex="-1">${main}</main>
      </div>`;
    root.querySelectorAll('[data-action="signout"]').forEach((b) => (b.onclick = async () => { await api('/api/logout', {}).catch(() => {}); S.me = null; go('/signin'); }));
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
    }
    wireBell();
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
        <button class="chip" type="button" data-dltab="shipped" aria-pressed="${tab === 'shipped'}">Shipped · ${shippedCount}</button>
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
  async function viewSettings() {
    const current = window.__TAU_UI__ === 'meridian' ? 'meridian' : 'tau';
    shell('/settings', boardTitle('Settings', 'How Tau looks and works for you.'), `
      <section class="sect"><div class="section-head"><h2>Theme</h2><p>Changes the whole interface</p></div>
        <div class="theme-pick" role="radiogroup" aria-label="Theme">
          ${THEMES.map((t) => `<button type="button" class="theme-opt${t.key === current ? ' on' : ''}" role="radio" aria-checked="${t.key === current}" data-theme="${t.key}">
              <span class="theme-meta"><b>${esc(t.name)}</b><span>${esc(t.desc)}</span></span>
              <span class="theme-mark" aria-hidden="true">${ICON.check}</span>
            </button>`).join('')}
        </div>
        <div id="theme-flash" class="hint" style="margin-top:12px">Switching theme reloads Tau. You can switch back here anytime.</div>
      </section>`);
    root.querySelectorAll('[data-theme]').forEach((b) => (b.onclick = () => {
      const key = b.dataset.theme;
      if (key === current) return;
      busy(b, async () => {
        try { localStorage.setItem('tau_ui', key); } catch (e) { /* private mode */ }
        try { await api('/api/ui-theme', { theme: key }); } catch (e) { /* local still applies */ }
        location.reload();
      });
    }));
  }
  // One measured cell. Money direction rides a tint field behind the figure
  // (opts.v), never a colour on the digits and never the reserved signal red.
  const fig = (label, value, opts = {}) =>
    `<div class="m ${opts.cls || ''}"><dt class="lab">${label}</dt><dd><span class="fig ${opts.v > 0 ? 'tint pos' : opts.v < 0 ? 'tint neg' : ''}">${value}</span></dd>${opts.small ? `<div class="sub-fig">${opts.small}</div>` : ''}</div>`;
  const dirTag = () => '';
  const notice = (msg, kind = '') => `<div class="notice ${kind}" role="${kind === 'bad' ? 'alert' : 'status'}">${kind === 'good' ? ICON.check : ICON.warn}<span>${esc(msg)}</span></div>`;
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

  // arm-to-confirm: first click arms for 5s, second click fires
  function armed(btn, label, fire) {
    if (btn.dataset.armed === '1') { btn.dataset.armed = ''; btn.classList.remove('armed'); return fire(); }
    const orig = btn.innerHTML;
    btn.dataset.armed = '1'; btn.classList.add('armed'); btn.textContent = label;
    setTimeout(() => { if (btn.dataset.armed === '1') { btn.dataset.armed = ''; btn.classList.remove('armed'); btn.innerHTML = orig; } }, 5000);
  }
  async function busy(btn, fn) {
    btn.classList.add('busy'); btn.disabled = true;
    try { return await fn(); } finally { btn.classList.remove('busy'); btn.disabled = false; }
  }
  function flash(where, msg, kind) {
    const el = typeof where === 'string' ? root.querySelector(where) : where;
    if (el) el.innerHTML = notice(msg, kind);
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
  function spark(curve, reg, label) {
    const W = 300, H = 46;
    if (!curve || curve.length < 2) {
      return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="No closed trades yet"><line x1="0" x2="${W}" y1="${H / 2}" y2="${H / 2}" stroke="var(--rule-2)" stroke-dasharray="3 4"/></svg>`;
    }
    const t0 = curve[0][0], t1 = curve[curve.length - 1][0] || t0 + 1;
    const x = (t) => ((t - t0) / Math.max(1, t1 - t0)) * W;
    const y = (v) => H - 3 - ((v - reg.lo) / (reg.hi - reg.lo)) * (H - 6);
    const pts = curve.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const last = curve[curve.length - 1][1];
    const color = 'var(--ink)';
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}: ${usd(last, true)}">
      <line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="var(--rule-2)" stroke-dasharray="3 4" vector-effect="non-scaling-stroke"/>
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
  }
  // devCurve (optional): a second, realized series replayed read-only against
  // the Kalshi demo environment. Drawn dashed in the accent colour with a legend
  // so "Simulated" and "Kalshi dev" read apart. Omitting it keeps the old chart.
  function equityChart(curve, cutoffIso, devCurve) {
    const W = 760, H = 236, L = 52, R = 10, T = 30, B = 26;
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
              <text x="${cx + 8}" y="${T - 10}" style="fill:var(--ink-2)">UNSEEN BY THE AGENT →</text>` : ''}
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
  const rpCent = (v) => (v == null ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(2) + '¢');
  const rpProb = (v, d = 3) => (v == null ? '—' : Number(v).toFixed(d));
  const rpInt = (v) => (v == null ? '—' : num(v));
  const rpText = (v) => esc(v == null ? '' : String(v));
  const rpHuman = (k) => String(k).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  const rpStamp = (iso) => { try { return new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch (e) { return String(iso); } };
  const rpDiffs = (curve) => (!curve || curve.length < 2) ? [] : curve.slice(1).map((p, i) => p[1] - curve[i][1]);
  const RP_MECH = { who_pays: 'Who pays', why_not_arbitraged: 'Why it isn’t arbitraged', when: 'When it fires', why_persists: 'Why it persists' };
  const RP_RUNGS = [['promising', 'Promising'], ['statistically_supported', 'Stat. supported'], ['forward_validated', 'Forward-validated'], ['deployment_candidate', 'Deployment candidate']];
  const RP_RANK = { rejected: -1, inconclusive: 0, promising: 1, statistically_supported: 2, forward_validated: 3, deployment_candidate: 4 };

  function rpLadder(cls) {
    const rank = RP_RANK[cls] == null ? 0 : RP_RANK[cls];
    const rungs = RP_RUNGS.map(([k, label], i) => {
      const r = i + 1, state = r === rank ? 'lit' : r < rank ? 'done' : '';
      return `<div class="rung ${state}"><div class="r-n">Rung ${r}</div><div class="r-t">${esc(label)}</div></div>`;
    }).join('');
    let terminal = '';
    if (cls === 'rejected') terminal = `<div class="rp-terminal"><span><b>Rejected</b> — this hypothesis did not advance the ladder.</span></div>`;
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
    const ticks = [lo, (lo + hi) / 2, hi].map((v) => `<text x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${usd(v)}</text>`).join('');
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const bounds = phases.slice(1).map((p) => { const bx = x(p.curve[0][0]).toFixed(1); return `<line x1="${bx}" x2="${bx}" y1="${T}" y2="${H - B}" stroke="var(--rule-2)" stroke-dasharray="3 4"/>`; }).join('');
    const legend = `<div class="rp-legend">${phases.map((p) => `<span><i style="background:${p.color}"></i>${esc(p.label)}</span>`).join('')}</div>`;
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative net profit and loss over time by research phase: ${esc(phases.map((p) => p.label).join(', '))}">
      <line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="var(--rule-2)"/>
      ${ticks}
      <text x="${L}" y="${H - 6}">${day(t0)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>
      ${bounds}${phases.map((p) => line(p.curve, p.color)).join('')}
    </svg>${legend}`;
  }

  // 2. in-sample vs validation mean — shrinkage.
  function rpShrinkage(isMean, oosMean) {
    const bars = [];
    if (isMean != null) bars.push(['In-sample', isMean, 'var(--ink-3)']);
    if (oosMean != null) bars.push(['Validation', oosMean, 'var(--ink)']);
    if (!bars.length) return `<div class="rp-empty">No in-sample / validation means to compare.</div>`;
    const W = 340, H = 180, T = 24, Bm = 30, L = 10, R = 10;
    const mags = bars.map((b) => b[1]);
    let lo = Math.min(0, ...mags), hi = Math.max(0, ...mags);
    if (hi - lo < 1e-4) { hi += 0.005; lo -= 0.005; }
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - Bm);
    const zero = y(0), slot = (W - L - R) / bars.length, bw = Math.min(64, slot * 0.5);
    const cells = bars.map((b, i) => {
      const cx = L + slot * i + slot / 2, top = Math.min(y(b[1]), zero), h = Math.max(1, Math.abs(y(b[1]) - zero));
      return `<rect x="${(cx - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${b[2]}" rx="3"/>
        <text x="${cx.toFixed(1)}" y="${(b[1] >= 0 ? top - 6 : top + h + 14).toFixed(1)}" text-anchor="middle" style="fill:var(--ink)">${rpCent(b[1])}</text>
        <text x="${cx.toFixed(1)}" y="${H - 8}" text-anchor="middle">${esc(b[0])}</text>`;
    }).join('');
    let note = '';
    if (isMean != null && oosMean != null && isMean !== 0) {
      const shr = Math.round((1 - oosMean / isMean) * 100);
      note = `<div class="cap">Validation edge is ${shr >= 0 ? shr + '% smaller' : Math.abs(shr) + '% larger'} than in-sample — ${shr >= 40 ? 'heavy shrinkage, a sign the in-sample fit was partly luck' : 'modest shrinkage'}.</div>`;
    }
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="In-sample versus validation mean net return per trade">
      <line x1="${L}" x2="${W - R}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}" stroke="var(--rule-2)"/>${cells}
    </svg>${note}`;
  }

  // 3. underwater drawdown.
  function rpUnderwater(curve) {
    if (!curve || curve.length < 2) return `<div class="rp-empty">No equity curve to derive drawdown from.</div>`;
    let peak = -Infinity; const dd = curve.map(([t, v]) => { peak = Math.max(peak, v); return [t, v - peak]; });
    const W = 340, H = 180, L = 44, R = 10, T = 14, B = 22;
    const t0 = curve[0][0], t1 = curve[curve.length - 1][0];
    const minDd = Math.min(0, ...dd.map((p) => p[1])), lo = minDd < 0 ? minDd : -0.5;
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (0 - lo)) * (H - T - B);
    const curvePts = dd.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const area = `${curvePts} ${x(t1).toFixed(1)},${y(0).toFixed(1)} ${x(t0).toFixed(1)},${y(0).toFixed(1)}`;
    const maxDd = usd(minDd);
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Underwater drawdown plot; worst drawdown ${maxDd}">
      <polygon points="${area}" fill="var(--signal-wash)" stroke="none"/>
      <polyline points="${curvePts}" fill="none" stroke="var(--signal)" stroke-width="1.6"/>
      <line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="var(--rule-2)"/>
      <text x="${L - 8}" y="${(y(0) + 4).toFixed(1)}" text-anchor="end">0</text>
      <text x="${L - 8}" y="${(y(minDd) + 4).toFixed(1)}" text-anchor="end">${maxDd}</text>
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
    const legend = `<div class="rp-legend"><span><i style="background:var(--ink)"></i>Per-trade net P&amp;L</span>${ciLo != null ? `<span><i style="background:var(--stock-raised);border:1px solid var(--rule-2)"></i>90% CI of the mean</span>` : ''}${mean != null ? `<span><i class="dash" style="color:var(--signal)"></i>Mean</span>` : ''}</span></div>`;
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
        <text x="${cx.toFixed(1)}" y="${(v >= 0 ? top - 5 : top + h + 13).toFixed(1)}" text-anchor="middle" style="fill:var(--ink)">${rpCent(v)}</text>
        <text x="${cx.toFixed(1)}" y="${H - 18}" text-anchor="middle">${esc(day(f.from) || ('W' + (i + 1)))}</text>
        <text x="${cx.toFixed(1)}" y="${H - 6}" text-anchor="middle" style="fill:var(--ink-3)">${f.n_trades != null ? f.n_trades + 't' : ''}</text>`;
    }).join('');
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Mean net return per trade across each purged walk-forward research fold">
      <line x1="${L}" x2="${W - R}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}" stroke="var(--rule-2)"/>${cells}
    </svg>`;
  }

  function rpConclusion(cls) {
    const m = {
      deployment_candidate: ['good', 'Deployment candidate. It cleared validation under the audited false-discovery budget, survived the one-time locked holdout, and is diverse enough from the deployed book to add something new.'],
      forward_validated: ['good', 'Forward-validated. It passed validation and then held up on the locked holdout, which is evaluated exactly once — the strongest evidence this pipeline produces.'],
      statistically_supported: ['', 'Statistically supported. The validation edge survives multiple-testing correction and the deflated-Sharpe test, but has not yet been spent against the locked holdout.'],
      promising: ['', 'Promising. An in-research edge that has not yet faced the validation partition.'],
      inconclusive: ['quiet', 'Inconclusive. The evidence was too weak, or the sample too small, to move the verdict — and no alpha budget was spent claiming it works.'],
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
    if (exp.primary_metric) pre.push(['Primary metric', exp.primary_metric]);
    if (exp.planned_test) pre.push(['Planned test', exp.planned_test]);
    if (exp.min_sample != null) pre.push(['Minimum sample', exp.min_sample + ' trades']);
    if (exp.planned_n_tests != null || exp.correction_method) pre.push(['Multiple-testing control', `${exp.planned_n_tests != null ? exp.planned_n_tests + ' planned tests · ' : ''}${exp.correction_method || '—'}`]);
    if (exp.cost_assumptions && typeof exp.cost_assumptions === 'object') pre.push(['Cost assumptions', Object.entries(exp.cost_assumptions).map(([k, v]) => `${rpHuman(k)}: ${v}`).join(' · ')]);
    if (pre.length) {
      const reg = exp.registered_at ? `<p class="rp-reg">Pre-registered <b>${esc(rpStamp(exp.registered_at))}</b> — before any validation number was computed. The frozen rule and its test could not be changed after the results came in.</p>` : '';
      parts.methodology += sub('The pre-registered test', `<dl class="rp-grid">${pre.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${rpText(v)}</dd></div>`).join('')}</dl>${reg}`);
    }
    // Results — the rigorous validation-window evidence.
    const v = exp.validation;
    if (v) {
      const stat = (k, val, cls, sb) => `<div class="rp-stat"><div class="k">${esc(k)}</div><div class="val${cls ? ' ' + cls : ''}">${val}</div>${sb ? `<div class="sub">${esc(sb)}</div>` : ''}</div>`;
      const ciTxt = (v.ci_lo != null && v.ci_hi != null) ? `90% CI ${rpCent(v.ci_lo)} to ${rpCent(v.ci_hi)}` : '';
      const stats = [
        stat('Mean net return / trade', rpCent(v.mean_net_return), (v.mean_net_return != null && v.mean_net_return > 0 ? '' : 'sig'), ciTxt),
        stat('Bootstrap p-value', rpProb(v.p_value), (v.p_value != null && v.p_value <= 0.1 ? '' : 'sig'), 'one-sided, autocorr-robust'),
        stat('PSR', rpProb(v.psr), '', 'prob. true Sharpe > 0'),
        stat('DSR', rpProb(v.dsr), (v.dsr != null && v.dsr >= 0.95 ? '' : 'sig'), 'deflated for selection'),
        stat('Trials audited', rpInt(exp.n_trials_audited), '', 'competed for this evidence'),
        stat('FDR α spent', rpProb(v.fdr_alpha_i, 4), '', v.fdr_reject == null ? '' : (v.fdr_reject ? 'rejects the null' : 'does not reject')),
        stat('Placebo p-value', rpProb(v.placebo_p), (v.placebo_p != null && v.placebo_p < 0.1 ? 'sig' : ''), 'label-shuffle control'),
        stat('Trades', rpInt(v.n_trades), '', 'on the validation window'),
      ].join('');
      const isMean = (exp.folds && exp.folds.length) ? exp.folds.reduce((a, f) => a + (f.mean_net_return || 0), 0) / exp.folds.length : null;
      const figs = `<div class="rp-figs">
        <div class="rp-fig wide"><h5>Equity by phase</h5>${rpPhaseEquity([
          { key: 'validation', label: 'Validation', color: 'var(--ink)', curve: v.equity_curve },
          { key: 'holdout', label: 'Holdout', color: 'var(--signal)', curve: exp.holdout && exp.holdout.equity_curve },
        ])}<div class="cap">Each phase is its own out-of-sample run; the dashed divider marks the one-way handoff from validation to the locked holdout.</div></div>
        <div class="rp-fig"><h5>In-sample vs validation</h5>${rpShrinkage(isMean, v.mean_net_return)}</div>
        <div class="rp-fig"><h5>Drawdown (underwater)</h5>${rpUnderwater(v.equity_curve)}</div>
        <div class="rp-fig wide"><h5>Per-trade return distribution</h5>${rpReturnDist(rpDiffs(v.equity_curve), v.ci_lo, v.ci_hi, v.mean_net_return)}<div class="cap">Bars: the net P&amp;L of each validation trade. Shaded band: the 90% bootstrap confidence interval of the mean. Dashed line: the mean. A band entirely right of break-even means the edge clears fees.</div></div>
        <div class="rp-fig wide"><h5>Walk-forward windows</h5>${rpWalkforward(exp.folds)}<div class="cap">Mean net return per purged/embargoed research fold — a consistent sign across windows is robustness; one window carrying the whole edge is a warning.</div></div>
      </div>`;
      parts.results += sub('Validation-window evidence', `<p class="rp-sub" style="margin-top:0">The window the agent iterated against is in-sample; these are the numbers from the held-out validation partition, under the audited false-discovery budget.</p><div class="rp-stats">${stats}</div>${figs}`);
    }
    // Verdict — the ladder, the one-time locked holdout, and the gatekeeper's conclusion.
    parts.verdict += `<div class="paper-sub"><h4 class="paper-h">Where it reached on the ladder</h4>${rpLadder(exp.classification)}</div>`;
    const h = exp.holdout;
    const holdBody = h ? `<div class="rp-stats">
      <div class="rp-stat"><div class="k">Mean net return / trade</div><div class="val${h.mean_net_return != null && h.mean_net_return > 0 ? '' : ' sig'}">${rpCent(h.mean_net_return)}</div><div class="sub">${h.ci_lo != null && h.ci_hi != null ? '90% CI ' + rpCent(h.ci_lo) + ' to ' + rpCent(h.ci_hi) : ''}</div></div>
      <div class="rp-stat"><div class="k">Bootstrap p-value</div><div class="val">${rpProb(h.p_value)}</div></div>
      <div class="rp-stat"><div class="k">Trades</div><div class="val">${rpInt(h.n_trades)}</div></div>
      <div class="rp-stat"><div class="k">Holdout</div><div class="val${h.consumed ? ' sig' : ''}">${h.consumed ? 'Consumed' : 'Open'}</div><div class="sub">${h.consumed ? 'spent — roll to fresh forward data' : 'evaluations remain'}</div></div>
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
  function strategySlip(s, reg, opts = {}) {
    const oos = s.out_of_sample, ins = s.in_sample || {};
    const m = oos || ins;
    const tried = s.hypotheses_tried ? `1 of ${s.hypotheses_tried}` : s.parent_id ? 'Adjustment' : '\u2014';
    const name = opts.nolink ? esc(s.title) : `<a href="/strategies/${s.id}">${esc(s.title)}</a>`;
    const pickCell = opts.pick ? (s.status === 'passed' && !researchOnly(s)
      ? `<td class="pickcol" data-lab="Deploy"><input type="checkbox" class="pick" data-id="${s.id}" aria-label="Select for deployment"></td>`
      : '<td class="pickcol" data-lab=""></td>') : '';
    return `<tr class="${opts.land ? 'washed' : ''}">${pickCell}
      <td class="name" data-lab="">${name}${s.shared_from ? ` <span class="shared-flag">${ICON.share}${esc(s.shared_from)}</span>` : ''}<div class="sub-fig cellwrap">${esc(s.thesis)}</div></td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(s.market))} \u00b7 ${esc(dirLabel(s.direction))}</span></td>
      <td class="num" data-lab="${oos ? 'Unseen P&amp;L' : 'Tested P&amp;L'}">${m.pnl == null ? '\u2014' : money(m.pnl)}${oos ? '' : '<div class="sub-fig">tested only</div>'}</td>
      <td class="num" data-lab="Trades">${m.trades == null ? '\u2014' : m.trades}</td>
      <td class="num" data-lab="Win">${pct(m.win_rate, false)}</td>
      <td data-lab="Tried">${esc(tried)}</td>
      <td class="act" data-lab="">${mark(s.status)}${researchBadge(s)}${s.deployed && !researchOnly(s) ? ` <span class="mk ${s.deploy_live ? 'live' : 'dep'}">${s.deploy_live ? 'Live' : 'Deployed'}</span>` : ''}</td>
    </tr>`;
  }
  const DEP_HEAD = (controls) => `<thead><tr><th>Strategy</th><th>Market</th><th>Status</th><th class="num">Realized</th><th class="num">Unrealized</th><th class="num">Trades</th><th class="num">Backtest unseen</th><th>Since</th>${controls ? '<th></th>' : ''}</tr></thead>`;
  const deploymentTable = (rows, controls) => `<div class="sheet"><table class="stack t-dep">${DEP_HEAD(controls)}<tbody>${rows}</tbody></table></div>`;
  function deploymentSlip(d, reg, controls) {
    const exp = d.backtest && d.backtest.out_of_sample;
    const live = d.mode === 'live';
    const modeTag = live ? '<span class="mk live">LIVE</span>' : d.mode === 'demo' ? '<span class="mk dep">DEMO</span>' : '<span class="mk">PAPER</span>';
    const actions = controls ? `<td class="act" data-lab="">
        ${d.status === 'running' ? `<button class="btn sm" data-dep="${d.id}" data-act="pause">Pause</button>` : ''}
        ${d.status === 'paused' ? `<button class="btn sm" data-dep="${d.id}" data-act="resume">Resume</button>` : ''}
        <button class="btn sm danger" data-dep="${d.id}" data-act="stop">Remove</button></td>` : '';
    return `<tr class="${live ? 'live-row' : ''}">
      <td class="name" data-lab=""><a href="/strategies/${d.strategy_id}">${esc(d.title)}</a>
        <div class="sub-fig">$${esc(d.stake)} a trade, up to ${esc(d.max_positions)} open${d.status !== 'running' && d.status_reason ? ' \u00b7 ' + esc(d.status_reason) : ''}</div></td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(d.market))}</span></td>
      <td data-lab="Status">${d.status === 'running' ? modeTag : mark(d.status, live)}</td>
      <td class="num" data-lab="Realized">${money(d.realized_pnl)}</td>
      <td class="num" data-lab="Unrealized">${d.unrealized_pnl == null ? '<span class="sub-fig">—</span>' : money(d.unrealized_pnl)}${d.unrealized_pnl != null && d.open_positions ? '<div class="sub-fig">est.</div>' : ''}</td>
      <td class="num" data-lab="Trades">${d.closed_trades}${d.open_positions ? `<div class="sub-fig">+${d.open_positions} open</div>` : ''}</td>
      <td class="num" data-lab="Backtest unseen">${exp ? usd(exp.pnl, true) : '\u2014'}</td>
      <td data-lab="Since">${when(d.created_at)}</td>
      ${actions}
    </tr>`;
  }
  function bindDeploymentActions(scope, after) {
    scope.querySelectorAll('[data-dep]').forEach((btn) => {
      btn.onclick = () => {
        const run = () => busy(btn, async () => {
          try { await api(`/api/deployments/${btn.dataset.dep}/${btn.dataset.act}`, {}); await after(); } catch (e) { alert0(e.message); }
        });
        if (btn.dataset.act === 'stop') armed(btn, 'Confirm stop', run); else run();
      };
    });
  }
  function alert0(msg) {
    const host = root.querySelector('#flash') || root.querySelector('main');
    const el = document.createElement('div');
    el.innerHTML = notice(msg, 'bad');
    host.prepend(el.firstChild);
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
    const away = S.me ? '<a href="/">Dashboard</a>' : '<a href="/signin">Sign in</a>';
    root.innerHTML = `<div class="legal-wrap">
      <header class="legal-top"><a class="lbrand" href="/">${ICON.mark}<span>Tau</span></a>
        <nav class="legal-nav"><a href="/terms">Terms</a><a href="/privacy">Privacy</a>${away}</nav></header>
      <main class="legal" id="main">
        <h1>${title}</h1><p class="legal-updated">Last updated ${LEGAL_UPDATED}</p>
        ${bodyHtml}
        <footer class="legal-foot"><a href="/terms">Terms of Service</a> · <a href="/privacy">Privacy Policy</a> · <span>© 2026 Tau</span></footer>
      </main></div>`;
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

  async function viewSignin() {
    const hr = document.getElementById('hotrail'); if (hr) hr.remove();
    document.body.classList.remove('hot-open');
    if (!S.me) { try { S.me = await api('/api/me'); } catch (e) { /* signed out: stay here */ } }
    if (S.me) return go('/', true);
    const q = new URLSearchParams(location.search);
    const err = q.get('error');
    const msg = { cancelled: 'Sign-in was cancelled.', expired: 'That sign-in link expired. Try again.', google: "Google couldn't confirm your account. Please try again." }[err];
    document.body.classList.add('landing-body');
    root.innerHTML = `
      <div class="landing">
        <header class="lnav">
          <a class="lbrand" href="/">${ICON.mark}<span>Tau</span></a>
          <div class="lnav-actions">
            <a class="pill solid" href="/auth/google" data-native>Sign in</a>
          </div>
        </header>
        <section class="lhero">
          <div class="lhero-copy">
            <h1>RSI for Trading.</h1>
            <p class="lsub">Recursive self-improvement, pointed at the market: an agent researches strategies, tests each on data it never saw, learns from every result, and trades only the ones that pass — in your own Kalshi account.</p>
            ${msg ? `<div class="lnotice">${esc(msg)}</div>` : ''}
            <div class="lcta" id="lcta">
              <a class="pill solid lg" href="/auth/google" data-native>${ICON.google}Continue with Google</a>
            </div>
            <p class="lfine">Free to start — you'll get $1,000 of paper money to research and test strategies. Live trading is optional and runs in your own Kalshi account.</p>
          </div>
          <div class="demo" id="demo" aria-hidden="true">
            <div class="demo-bar"><i></i><i></i><i></i><span class="demo-url">tau · research</span>
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
              <div class="demo"><div class="demo-bar"><i></i><i></i><i></i><span class="demo-url">tau · strategy</span></div><div class="demo-body"></div></div>
            </div>
            <div class="scene rev" data-scene="deploy">
              <div class="scene-copy">
                <span class="eyebrow">${ICON.deploy}Deploy &amp; monitor</span>
                <h2>Go live, and watch every trade.</h2>
                <p>Flip a passed strategy from paper to live in your own Kalshi account. Positions and P&amp;L stream in as it trades — and a loss guard pauses it automatically if it goes wrong.</p>
              </div>
              <div class="demo"><div class="demo-bar"><i></i><i></i><i></i><span class="demo-url">tau · deploy</span></div><div class="demo-body"></div></div>
            </div>
            <div class="scene" data-scene="agent">
              <div class="scene-copy">
                <span class="eyebrow">${ICON.spark2}RSI agent mode</span>
                <h2>Or let the agent run the whole desk.</h2>
                <p>Turn on autopilot and the agent researches, backtests, and deploys on its own — a loop that keeps hunting for edge. Every move is written down, and it never touches live money without you.</p>
              </div>
              <div class="demo"><div class="demo-bar"><i></i><i></i><i></i><span class="demo-url">tau · autopilot</span></div><div class="demo-body"></div></div>
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
    ['Fade the far tails', 'volatility · fees in', 'pass', '+$38 unseen'],
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
      el.innerHTML = `<b>${esc(t)}</b><span class="dmk ${mk === 'pass' ? 'pass' : 'void'}">${mk === 'pass' ? 'Passed' : 'Void'}</span><span class="dmeta">${esc(meta)} · ${esc(pnl)}</span>`;
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
        el.innerHTML = `<b>${r[0]}</b><b class="${r[1] >= 0 ? 'gain' : 'loss'}">${r[1] >= 0 ? '+' : '−'}$${Math.abs(r[1]).toFixed(2)}</b><small>settled · paper → live</small>`;
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
        ['dot', 'Deployed on paper · watching it trade'],
        ['spin', 'Researching mean reversion…'],
        ['check', "Found <b>Fade the overreaction</b> — passed"],
        ['dot', 'Autopilot running · 2 strategies live on paper'],
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
  async function viewDashboard() {
    shell('/', loading(120), loading(320));
    const load = async () => {
      const d = await api('/api/dashboard');
      const p = d.paper;
      // Realized P&L (all-time + today) and open count for one money bucket; a tasteful
      // zero line when the bucket has no activity so an empty card never looks broken.
      const mSub = (b, zero) => (b.open_positions || b.running || b.realized_pnl) ? `${b.open_positions} open · ${usd(b.realized_pnl, true)} all time · ${usd(b.today_pnl, true)} today` : zero;
      const hasLive = d.deployments.some((x) => x.mode === 'live' && x.status !== 'stopped');
      const stale = d.freshness.btc == null || d.freshness.btc > 2700;
      const agentsBusy = d.agents.research_running + d.agents.research_queued;
      const running = d.deployments.filter((x) => x.status === 'running').length;
      const paused = d.deployments.filter((x) => x.status === 'paused').length;
      const needs = stale || paused > 0;
      const said = [
        hasLive ? `Live money on: ${usd(d.live.realized_pnl, true)} realized` : 'Paper money only',
        running ? `${running} strateg${running > 1 ? 'ies' : 'y'} running` : 'Nothing deployed',
        paused ? `<em>${paused} paused, needs you</em>` : '',
        agentsBusy ? `${agentsBusy} agent${agentsBusy > 1 ? 's' : ''} researching` : '',
        stale ? `<em>Backtest history stale ${age(d.freshness.btc)}</em>` : '',
      ].filter(Boolean).join('<span class="sep">/</span>');
      const board = `
        <div class="statusline ${needs ? 'needs' : ''}"><p class="said">${said}</p><a class="btn primary" href="/research">New research</a></div>
        <dl class="figures measure">
          ${fig('<span class="mk live">Real</span> Live money', d.live.connected ? (d.live.balance == null ? 'Unavailable' : usd(d.live.balance)) : 'Not connected', { small: d.live.connected ? (d.live.balance == null ? 'Couldn\u2019t read your Kalshi balance just now' : mSub(d.live, 'Your Kalshi cash \u2014 real money untouched')) : 'Connect your Kalshi account on Funds to trade real money' })}
          ${fig('<span class="mk dep">Demo</span> Sandbox', usd(d.demo.equity), { v: d.demo.realized_pnl, small: (d.demo.open_positions || d.demo.running || d.demo.realized_pnl) ? `${usd(d.demo.capital)} capital \u00b7 ${d.demo.open_positions} open \u00b7 ${usd(d.demo.realized_pnl, true)} P&amp;L` : `${usd(d.demo.capital)} capital \u00b7 no demo strategies yet` })}
          ${fig('<span class="mk">Paper</span> Simulation', usd(p.equity), { v: p.total_pnl, small: `${usd(p.cash)} cash \u00b7 ${usd(p.open_at_cost)} at cost \u00b7 ${usd(p.total_pnl, true)} all time` })}
        </dl>${d.live.connected && d.live.open_positions ? `<p class="recon ${(d.reconcile && d.reconcile.length) ? 'warn' : 'ok'}">${(d.reconcile && d.reconcile.length) ? `\u26a0 ${d.reconcile.length} live position${d.reconcile.length === 1 ? '' : 's'} disagree with Kalshi \u2014 check your Portfolio` : `${ICON.check} Live book reconciled with Kalshi`}</p>` : ''}`;
      const reg = registry(d.deployments.map((x) => x.curve));
      const deps = d.deployments.length
        ? deploymentTable(d.deployments.map((x) => deploymentSlip(x, reg, true)).join(''), true)  // same controls as Deploy
        : `<div class="empty"><h3>Nothing deployed yet</h3><p>Agents research strategies and test each one on data they never saw. The ones that pass every gate can be deployed here, on paper first.</p><a class="btn" href="/research">Dispatch your first agent</a></div>`;
      const stubs = (rows, closed) => rows.length
        ? rows.map((r) => `<div class="stub"><b>${esc(r.side.toUpperCase())} ${esc(r.qty)} × ${cents(+r.entry_price)}</b>
            <span>${closed ? money(+r.pnl) : (r.unrealized != null ? money(r.unrealized) : usd(r.qty * r.entry_price))}</span>
            <small>${esc(r.title)} · <span class="tick">${esc(r.ticker)}</span> · ${r.mode === 'live' ? 'LIVE' : r.mode === 'demo' ? 'DEMO' : 'PAPER'} · ${when(closed ? r.closed_at : r.opened_at)}</small></div>`).join('')
        : `<p class="hint">${closed ? 'No settled trades yet.' : 'No open positions.'}</p>`;
      const main = `<div class="dash">
          <div>
            <section class="sect"><div class="sect-head"><h2>Deployed</h2></div><div id="dash-deps">${deps}</div></section>
          </div>
          <aside>
            <section class="panel"><h3>Open positions</h3>${stubs(d.open_positions, false)}</section>
            <section class="panel"><h3>Settled lately</h3>${stubs(d.recent_closed, true)}</section>
          </aside>
        </div>`;
      root.querySelector('#boardbody').innerHTML = board;
      root.querySelector('main').innerHTML = main;
      const dd = root.querySelector('#dash-deps');
      if (dd) bindDeploymentActions(dd, load);  // pause/resume/stop from the dashboard, same as Deploy
    };
    await load();
    poll(load, 15000);
  }

  // ---------- research ----------
  // "Build on what's worked": the user's best passed edges, one click from a deeper search line.
  function winCard(s) {
    const oos = s.out_of_sample;
    const pnl = oos && oos.pnl != null ? oos.pnl : null;
    return `<div class="win-card">
      <a class="win-title" href="/strategies/${s.id}"><b>${esc(s.title)}</b></a>
      <span class="win-meta">${esc(marketShort(s.market))} · ${esc(dirLabel(s.direction))}</span>
      <div class="win-foot">
        <span class="win-pnl"><span class="lab">Unseen P&amp;L</span><span class="fig sm ${pnl > 0 ? 'tint pos' : pnl < 0 ? 'tint neg' : ''}">${pnl == null ? '—' : usd(pnl, true)}</span></span>
        <span class="win-act"><a class="btn sm" href="/strategies/${s.id}">Open</a><button class="btn sm primary" type="button" data-dig="${s.id}">${ICON.spark2}Dig deeper</button></span>
      </div></div>`;
  }
  // The RSI loop made legible on the index: the engine rewrites its own search policy and keeps
  // the new one only if it beats the old on the user's own history. Same card language as the run
  // page. Hidden on a brand-new account (no history to evolve from yet).
  function renderRsiMomentum(host, pol, tried) {
    if (!host) return;
    if (!pol || (!pol.evolved && !tried)) { host.innerHTML = ''; return; }
    const delta = (pol.base_score != null && pol.score != null)
      ? `<span class="rsi-score">${pol.base_score} <span class="rsi-arrow">→</span> ${pol.score}</span>` : '';
    const tag = pol.evolved ? '<span class="rsi-tag">Evolved</span>' : '<span class="rsi-tag quiet">Self-tuning</span>';
    const body = pol.evolved
      ? `<p>The engine <b>rewrote its own search policy</b> from your history — and it beats the default.</p>
         ${pol.summary ? `<p class="rsi-what"><b>What it changed:</b> ${esc(pol.summary)}</p>` : ''}
         <p class="rsi-last">Generalization score ${delta}${pol.evolved_at ? ' · adopted ' + when(pol.evolved_at) : ''} <span class="rsi-note">(higher = catches more real out-of-sample winners, scored over shuffled orderings so it can't overfit)</span></p>`
      : `<p>After each cycle the engine <b>dreams up new search strategies</b> and keeps one only if it beats the current policy on your own history — scored over shuffled orderings, so it can't overfit. It gets better the more you run it.</p>`;
    // Demoted to a compact, collapsible line so the research page leads with the form, not panels.
    host.innerHTML = `<details class="rsidisc">
      <summary class="rsidisc-cap"><b class="rsi-badge">RSI</b><span class="rsidisc-t">Self-improving research engine</span>${tag}${pol.evolved && delta ? `<span class="rsidisc-delta">${delta}</span>` : ''}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
      <div class="rsidisc-body">${body}</div>
    </details>`;
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
    const gates = ['Bootstrap CI', 'PSR', 'DSR · deflated by trial count', 'Placebo / null', 'LORD++ FDR budget', 'Purged walk-forward', 'Benjamini–Hochberg'];
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
          fnode('Paper first', 'Proven on paper — at least 8 closed trades and non-negative P&amp;L — before anything touches real money.'),
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
  async function viewResearch() {
    const me = S.me;
    const DEMO_PROMPT = "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances";
    const mdl = await api('/api/models').catch(() => ({ models: [], default: '' }));
    const modelOpts = (mdl.models || []).map((m) => `<option value="${esc(m.key)}"${m.key === mdl.default ? ' selected' : ''}>${esc(m.label)}</option>`).join('');
    shell('/research', boardTitle('Research', 'A self-improving research engine for Bitcoin markets \u2014 describe an idea, it writes strategies and tests each on data it never saw.'), `
      <form class="panel dispatch" id="dispatch">
        <h3>${ICON.spark2}New research session</h3>
        ${me.needs_card ? `<div class="notice" role="status">${ICON.warn}<span>Add a payment method to start researching. Your $${me.free_bonus} in free credits unlock the moment a card is on file — you won't be charged until they run out. <a href="/billing">Add a card →</a></span></div>` : ''}
        ${(!me.needs_card && me.billing_enabled && me.credit_balance < me.min_run_balance) ? `<div class="notice" role="status">${ICON.warn}<span>You have $${me.credit_balance.toFixed(2)} in credits — a research session needs at least $${me.min_run_balance.toFixed(2)} to start. <a href="/billing">Add credits →</a></span></div>` : ''}
        <label class="field"><span>Describe your idea</span>
          <textarea class="input" name="prompt" maxlength="1000" rows="3" required placeholder="Write your own — e.g. &quot;Sell overpriced tails in the last hour before the 5pm close.&quot;"></textarea></label>
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
        <div class="dispatch-go">
          <button type="button" class="chip ex" data-ex="${esc(DEMO_PROMPT)}" title="Fill the box with a tiny runnable demo idea">Try the demo — Todd's random walk</button>
          <button class="btn primary go" type="submit" ${me.needs_card ? 'aria-disabled="true"' : ''}>${ICON.spark2}Start session</button>
        </div>
        <div id="dflash"></div>
        <p class="hint">A session takes a few minutes and keeps running if you leave this page.</p>
      </form>
      <div class="rengine" id="rengine">
        <div class="statusline" id="rstatus"><p class="said"></p></div>
        <dl class="figures measure" id="rfigs"></dl>
        <div id="rsimo"></div>
      </div>
      ${pipelineFigure()}
      <section class="sect"><div class="sect-head"><h2>Your sessions</h2><p id="rcount"></p></div>
        <div id="flash"></div><div class="runs" id="runs">${loading(70)}${loading(70)}</div></section>`);
    const form = root.querySelector('#dispatch');
    wireMarketPicker(form);
    const ta = form.querySelector('textarea[name=prompt]');
    root.querySelectorAll('[data-ex]').forEach((b) => (b.onclick = () => { ta.value = b.dataset.ex; ta.focus(); }));
    const rf = form.querySelector('#runforever'), mh = form.querySelector('#maxhyp');
    if (rf && mh) {
      const syncRf = () => { mh.disabled = rf.checked; mh.style.opacity = rf.checked ? '.4' : ''; };
      rf.addEventListener('change', syncRf); syncRf();  // default on -> depth dimmed
    }
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (me.needs_card) { flash('#dflash', 'Add a payment method on the Billing tab first.', 'bad'); go('/billing'); return; }
      const fd = new FormData(form);
      const btn = form.querySelector('button[type=submit]');
      await busy(btn, async () => {
        try {
          const r = await api('/api/runs', {
            market: fd.get('market'), prompt: fd.get('prompt'),
            max_hypotheses: Number(fd.get('max_hypotheses')) || undefined,
            run_forever: fd.get('run_forever') === 'on',
            model: fd.get('model') || undefined,
          });
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
    const load = async () => {
      const d = await api('/api/runs');
      const tried = d.runs.reduce((a, r) => a + (r.hypotheses_tried || 0), 0);
      const passed = d.runs.reduce((a, r) => a + (r.strategies_passed || 0), 0);
      const running = d.counts.research_running, queued = d.counts.research_queued;
      const said = running
        ? `<em>${running}</em> agent${running > 1 ? 's' : ''} researching now${queued ? ` · <em>${queued}</em> waiting` : ''} — <em>${tried}</em> hypotheses tested, <em>${passed}</em> through every gate.`
        : tried
          ? `Your engine has tested <em>${tried}</em> hypotheses and kept <em>${passed}</em> that beat every gate. Seed another idea to keep hunting.`
          : `Describe an idea below — the engine turns it into strategies and tests each on data it never saw.`;
      root.querySelector('#rstatus .said').innerHTML = said;
      root.querySelector('#rfigs').innerHTML = fig('Researching now', running) + fig('Waiting', queued) +
        fig('Hypotheses tested', tried) + fig('Passed every gate' + glo('gate'), passed, { small: tried ? `${pct(passed / tried, false)} pass rate` : '' });
      renderRsiMomentum(root.querySelector('#rsimo'), d.policy, tried);
      root.querySelector('#rcount').textContent = d.runs.length ? `${d.runs.length} run${d.runs.length > 1 ? 's' : ''}` : '';
      root.querySelector('#runs').innerHTML = d.runs.length ? d.runs.map(runRow).join('')
        : `<div class="empty"><h3>No sessions yet</h3><p>Describe an idea above. The agent will turn it into several strategies, test each one on data it never saw, and mark each Passed or Void.</p></div>`;
    };
    await load();
    poll(load, 5000);
  }
  function runRow(r) {
    const state = r.status === 'running' ? 'Researching<span class="working" aria-label="in process"></span>'
      : r.status === 'queued' ? 'Waiting<span class="working" aria-label="in process"></span>'
      : r.status === 'succeeded' ? `<span class="${r.strategies_passed ? 'gain' : ''}">${r.strategies_passed} of ${r.hypotheses_tried} passed</span>`
      : r.status === 'stopped' ? `Explored ${r.hypotheses_tried} hypothes${r.hypotheses_tried === 1 ? 'is' : 'es'}${r.strategies_passed ? ` · <span class="gain">${r.strategies_passed} passed</span>` : ''}`
      : r.status === 'cancelled' ? 'Cancelled' : '<span class="loss">Failed</span>';
    // status band: a thin color rule so passed/void/failed reads at a glance. A `stopped` run (frozen,
    // interrupted, or capped) is neutral (void), NOT red — only a real error is `fail`.
    const band = r.status === 'succeeded' ? (r.strategies_passed ? 'ok' : 'void') : r.status === 'failed' ? 'fail' : (r.status === 'cancelled' || r.status === 'stopped') ? 'void' : 'live';
    return `<a class="run-card ${band}" href="/research/${r.id}">
      <span class="run-title"><b>${esc(sessionTitle(r))}</b></span>
      <span class="run-meta">${esc(marketShort(r.market))}${r.error ? ' \u00b7 ' + esc(r.error) : ''}</span>
      <span class="run-foot"><span class="run-state">${state}</span><span class="run-when">${when(r.created_at)}</span></span></a>`;
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
    const sizing = `$${sz.stake != null ? sz.stake : 5} per trade · up to ${sz.max_positions != null ? sz.max_positions : 20} at once`;
    const codeFig = (src) => `<figure class="hx-code"><figcaption>Strategy code <span>Python · research sandbox only</span></figcaption><pre><code>${esc(src)}</code></pre></figure>`;

    // Code strategy: an arbitrary fitted model in the sandbox, not threshold fields. Show it as
    // one, keep the real source (and note the frozen fit, if the research run froze params in).
    if (spec.code) {
      const fit = (spec.params != null && spec.params !== '') ? ' · fit on research, frozen' : '';
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
        ? `<dt>Fitted weights</dt><dd class="hx-weights">${feats.map((f, i) => `<span class="hx-feat">${esc(f)}</span> ×${coef[i].toFixed(2)}`).join(' · ')}${typeof m.intercept === 'number' ? ` · intercept ${m.intercept.toFixed(2)}` : ''}</dd>`
        : '';
      return `<dl class="hx-spec">
        ${side}
        <dt>Signal</dt><dd class="hx-model">${signal}${edge ? ' — enter when ' + edge : ''}</dd>
        ${weights}
        ${row('Only when', bounds.join(' · '))}
        ${row('Exit', exit.join(' · ') || 'hold to settlement')}
        ${row('Regime filter', filters)}
        ${row('Sizing', sizing)}</dl>`;
    }

    // Plain DSL threshold strategy (house GBM / rules) — unchanged.
    const entry = [];
    if (edge) entry.push(`edge ≥ ${pct(e.min_edge, false)}`);
    entry.push(...bounds);
    return `<dl class="hx-spec">
      ${side}
      ${row('Enter when', entry.join(' · ') || 'any priced contract')}
      ${row('Exit', exit.join(' · ') || 'hold to settlement')}
      ${row('Regime filter', filters)}
      ${row('Sizing', sizing)}</dl>`;
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
      ? `<span class="say-stat">In-sample ${usd(ins.pnl, true)} · ${ins.trades} trade${ins.trades === 1 ? '' : 's'}</span>` : '';
    const home = [mechHtml(d.mechanism), specHtml(d.spec),
      d.falsification ? `<p class="hx-fine"><b>Falsified if</b> ${esc(d.falsification)}</p>` : '',
      d.negative_control ? `<p class="hx-fine"><b>Placebo that should fail</b> ${esc(d.negative_control)}</p>` : ''].filter(Boolean).join('');
    li.innerHTML = `<time>${clock(ev.created_at)}</time><span class="node" aria-hidden="true"></span><div class="say">
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
        reviewEl.insertAdjacentHTML('beforeend', `<p class="hx-crit"><span class="hx-tag">Challenger · ${esc(dec)}</span>${esc(reason)}</p>`);
      },
      verdict(e2) {
        const dd = e2.data || {};
        const cls = dd.status === 'passed' ? 'pass' : dd.status === 'rejected' ? 'rej' : 'void';
        const label = dd.status === 'passed' ? 'PASSED' : dd.status === 'rejected' ? 'REJECTED' : 'VOID';
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
        reviewEl.hidden = false;
        reviewEl.insertAdjacentHTML('beforeend', `<div class="hx-verdict"><span class="hx-tag ${cls}">Gatekeeper · ${label.toLowerCase()}</span>${tail ? `<span class="hx-vtext">${esc(tail)}</span>` : ''}${statGrid(dd.stats)}${href ? `<a class="hx-viewstrat" href="${href}">View strategy →</a>` : ''}</div>`);
      },
    };
  }

  // A live "thinking" card: the proposer's reasoning streams in as the agent writes it, with a
  // ticking elapsed clock and a caret, so the multi-minute generation call is visibly ALIVE rather
  // than a silent "Researching…". Once the prose turns into the JSON spec we stop echoing raw
  // tokens (the structured spec lands in each hypothesis card instead) and show a quiet "drafting".
  function thinkController(block, at) {
    const li = document.createElement('li');
    li.className = 'ln lane-think think';
    li.innerHTML = `<time>${clock(at)}</time><span class="node" aria-hidden="true"></span><div class="say">
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
      seal() { clearInterval(tick); caret.remove(); draft.hidden = true; li.classList.add('sealed'); if (!raw.trim()) li.remove(); },
    };
  }

  // Controller over a .runfeed section: streams the thinking card, grafts challenger/verdict onto
  // their hypothesis card, appends everything else newest-at-bottom with an enter animation, sticks
  // to the latest only when already at the foot, raises a "jump to latest" chip when scrolled up,
  // and drives the live "researching… (Ns)" pulse so it never looks frozen between polls.
  function runFeed(section) {
    const log = section.querySelector('.log');
    const jump = section.querySelector('.jumplatest');
    const pulse = section.querySelector('.runpulse');
    let unseen = 0, first = true, appended = 0, pulseSt = null, lastAt = Date.now();
    const cards = new Map();   // hypothesis title -> card controller (most recent wins on a title clash)
    let think = null;          // the currently-open thinking card, if any
    const atBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 60;
    const toLatest = () => { log.scrollTop = log.scrollHeight; unseen = 0; jump.hidden = true; };
    log.addEventListener('scroll', () => { if (atBottom()) { unseen = 0; jump.hidden = true; } });
    jump.onclick = toLatest;
    const sealThink = () => { if (think) { think.seal(); think = null; } };
    const add = (el) => { if (!first) el.classList.add('in'); log.appendChild(el); appended++; };

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
        if (card) { card.verdict(ev); cards.delete(card.title); } else add(runEventEl(ev));
      } else {
        add(runEventEl(ev));
      }
    }

    // Count up the seconds since the last event every second (independent of the 2s poll) so a
    // long call that isn't streaming still reads as working, not stuck.
    const ptick = setInterval(() => {
      if (pulse.hidden || pulseSt === 'paused' || pulseSt === 'done') return;
      const secs = Math.round((Date.now() - lastAt) / 1000);
      const lab = pulse.querySelector('[data-plabel]');
      if (lab && secs >= 3) lab.textContent = `${pulseSt === 'queued' ? 'Queued' : 'Researching'} · ${secs}s`;
    }, 1000);
    S.timers.push(ptick);

    return {
      push(events) {
        if (!events || !events.length) return;
        const ph = log.querySelector('.log-empty'); if (ph) ph.remove();
        const stick = first || atBottom();
        appended = 0;
        events.forEach((ev) => { try { dispatch(ev); } catch (e) { /* one bad event must not break the feed */ } });
        if (stick) toLatest();
        else if (appended) { unseen += appended; jump.hidden = false; jump.textContent = unseen + ' new ↓'; }
        first = false;
      },
      state(st) {  // 'queued' | 'running' | 'paused' | 'done'
        if (st === 'done') { pulseSt = st; sealThink(); pulse.hidden = true; return; }
        const stick = atBottom();
        pulse.hidden = false;
        if (st !== pulseSt) {
          pulse.className = 'runpulse' + (st === 'paused' ? ' paused' : '');
          pulse.innerHTML = st === 'paused'
            ? '<span class="pulse-bar" aria-hidden="true"></span><span>Paused — resume and it picks up exactly where it left off.</span>'
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
    if (ev.kind === 'verdict') {
      const st = data.status, sid = data.strategy_id;
      lane = st === 'passed' ? 'pass' : st === 'rejected' ? 'rej' : 'void';
      const tag = st === 'passed' ? '<b class="verdict pass">PASSED</b>'
        : st === 'rejected' ? '<b class="verdict rej">REJECTED</b>'
        : '<b class="verdict void">VOID</b>';
      const rest = ev.message.replace(/^(PASSED|VOID|FAILED|REJECTED)(\s*\(challenger\))?\s*[-–]\s*/, '');
      const title = data.title || rest;
      const tail = rest.startsWith(title) ? rest.slice(title.length) : '';  // keep the ": …" explanation as text
      const titleHtml = sid ? `<a href="/strategies/${sid}">${esc(title)}</a>` : `<b>${esc(title)}</b>`;
      inner = `${tag} ${titleHtml}${esc(tail)}`;
    } else if (ev.kind === 'challenger') {
      inner = `<span class="say-kind">Challenger</span>${esc(ev.message.replace(/^Challenger\s+/, ''))}`;
    } else if (/^(Dreaming:|Research policy evolved:)/.test(ev.message)) {
      lane = 'rsi';
      inner = `<b class="rsi-badge">RSI</b> ${esc(ev.message)}`;
    } else if (ev.kind === 'paused' || ev.kind === 'resumed') {
      inner = `<span class="say-kind">${ev.kind === 'paused' ? 'Paused' : 'Resumed'}</span>${esc(ev.message)}`;
    } else {
      inner = mdLite(ev.message);   // step notes: inline markdown (bold/code/italic/links), escaped
    }
    li.className = 'ln lane-' + lane + (lane === 'rsi' ? ' rsi-event' : '');
    li.innerHTML = `<time>${clock(ev.created_at)}</time><span class="node" aria-hidden="true"></span><div class="say">${inner}</div>`;
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
  const RSI_STAGES = [['explore', 'Explore'], ['backtest', 'Backtest'], ['gate', 'Gate'], ['dream', 'Dream']];
  // event kind -> [loop stage, human phase label]. New kinds the backend adds just fall through.
  const RSI_PHASE = {
    'run-start': ['explore', 'Starting up'], 'data-loaded': ['explore', 'Data loaded'],
    'proposing': ['explore', 'Proposing hypotheses'], 'developing-thesis': ['explore', 'Developing a thesis'],
    'thinking': ['explore', 'Thinking it through'], 'step': ['explore', 'Working'],
    'hypothesis': ['backtest', 'Backtesting a hypothesis'], 'challenger': ['backtest', 'Challenging the result'],
    'gating': ['gate', 'Gating on unseen data'], 'verdict': ['gate', 'Recording the verdict'],
    'dreaming': ['dream', 'Dreaming a better search'],
  };
  const SX = { explore: 80, backtest: 240, gate: 400, dream: 560 };  // viewBox-x of each station (= flex-cell centres: 12.5/37.5/62.5/87.5% of 640)
  const prettyKind = (k) => String(k || '').replace(/[-_]/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  // Liberal id/parent extraction so the tree survives whatever the backend names its lineage fields.
  const hypId = (d) => d.hyp_id != null ? d.hyp_id : d.id != null ? d.id : d.node_id != null ? d.node_id : null;
  const hypParent = (d) => d.parent_id != null ? d.parent_id : d.parent != null ? d.parent : d.parent_hyp_id != null ? d.parent_hyp_id : d.parent_title != null ? d.parent_title : null;

  function rsiObservatory(host) {
    const station = ([s]) => `<g class="rsi-st" data-stage="${s}"><circle class="rsi-ring" cx="${SX[s]}" cy="50" r="17"></circle><circle class="rsi-dot" cx="${SX[s]}" cy="50" r="7.5"></circle></g>`;
    const link = (a, b, into) => `<line class="rsi-link" data-into="${into}" x1="${SX[a] + 18}" y1="50" x2="${SX[b] - 18}" y2="50"></line>`;
    host.innerHTML = `
      <div class="rsiobs-head"><h2>The RSI loop</h2>
        <span class="rsiobs-live is-wait" data-live><span class="rsiobs-pdot"></span><span data-livetext>Spinning up…</span></span></div>
      <div class="rsiobs-loop">
        <svg class="rsi-rail" viewBox="0 0 640 72" role="img" aria-label="The research loop: explore, backtest, gate, dream — and back again.">
          <path class="rsi-arc" data-into="explore" d="M560 42 C 560 6, 80 6, 80 42"></path>
          ${link('explore', 'backtest', 'backtest')}${link('backtest', 'gate', 'gate')}${link('gate', 'dream', 'dream')}
          ${RSI_STAGES.map(station).join('')}</svg>
        <div class="rsi-labels">${RSI_STAGES.map(([s, l]) => `<span class="rsi-lab" data-stage="${s}">${l}</span>`).join('')}</div></div>
      <p class="rsiobs-phase" data-phase>Waiting for the agent to start.</p>
      <figure class="rsiobs-tree" data-tree hidden><figcaption>Discovery tree <span>how each winner seeded the next</span></figcaption>
        <div class="rsiobs-treewrap"><svg class="rsiobs-treesvg" data-treesvg></svg></div></figure>`;

    const liveWrap = host.querySelector('[data-live]'), liveText = host.querySelector('[data-livetext]');
    const phaseEl = host.querySelector('[data-phase]'), treeFig = host.querySelector('[data-tree]'), treeSvg = host.querySelector('[data-treesvg]');
    const groups = {}, labs = {};
    RSI_STAGES.forEach(([s]) => { groups[s] = host.querySelector(`.rsi-st[data-stage="${s}"]`); labs[s] = host.querySelector(`.rsi-lab[data-stage="${s}"]`); });
    const links = host.querySelectorAll('.rsi-link, .rsi-arc');
    const fired = new Set();
    let stage = null, lastAt = Date.now(), runState = 'queued';
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
      if (runState === 'paused') { liveWrap.className = 'rsiobs-live is-paused'; liveText.textContent = 'Paused'; return; }
      if (runState === 'queued') { liveWrap.className = 'rsiobs-live is-wait'; liveText.textContent = 'Queued'; return; }
      if (runState !== 'running') { liveWrap.className = 'rsiobs-live is-done'; liveText.textContent = runState === 'succeeded' ? 'Finished' : runState === 'cancelled' ? 'Cancelled' : 'Stopped'; return; }
      const secs = Math.max(0, Math.round((Date.now() - lastAt) / 1000)), stalled = secs >= 75;
      host.classList.toggle('is-quiet', stalled);
      liveWrap.className = 'rsiobs-live' + (stalled ? ' is-stall' : '');
      liveText.textContent = stalled ? `quiet ${secs}s — likely a long model call` : secs < 6 ? 'live' : `active ${secs}s ago`;
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
        runState = state || runState;
        (events || []).forEach((ev) => {
          const d = ev.data || {};
          lastAt = Date.parse(ev.created_at) || Date.now();   // newest event's own clock drives liveness
          let ph = RSI_PHASE[ev.kind];
          if (!ph && /^(Dreaming:|Research policy evolved:)/.test(ev.message || '')) ph = ['dream', ev.message.split(':')[0]];
          if (ph) { stage = ph[0]; fired.add(stage); phaseEl.textContent = ph[1]; }
          else if (ev.kind && ev.kind !== 'done') phaseEl.textContent = prettyKind(ev.kind);  // unknown kind: keep stage lit, show a readable label
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
        paintStages(); paintLive(); tree();
      },
    };
  }

  // Interrupt & continue: the obvious control cluster for a research run. Running → Pause;
  // Paused → Resume (the primary action); every active state can Cancel. Finished shows the
  // way onward. Pause/Resume are reversible so they act immediately; Cancel is armed to confirm.
  function runControls(host, id, status, reload) {
    if (status === 'paused') {
      host.innerHTML = '<span class="runact"><button class="btn small primary" id="resume">Resume</button><button class="btn danger small" id="cancel">Cancel</button></span>';
      host.querySelector('#resume').onclick = (e) => busy(e.currentTarget, async () => { await api(`/api/runs/${id}/resume`, {}).catch((er) => alert0(er.message)); await reload(); });
    } else if (status === 'running') {
      host.innerHTML = '<span class="runact"><button class="btn small" id="pause">Pause</button><button class="btn danger small" id="cancel">Cancel</button></span>';
      host.querySelector('#pause').onclick = (e) => busy(e.currentTarget, async () => { await api(`/api/runs/${id}/pause`, {}).catch((er) => alert0(er.message)); await reload(); });
    } else if (status === 'queued') {
      host.innerHTML = '<span class="runact"><button class="btn danger small" id="cancel">Cancel</button></span>';
    } else {
      host.innerHTML = status === 'succeeded' ? '<a class="btn small" href="/strategies">All strategies</a>' : '';
      return;
    }
    const cancel = host.querySelector('#cancel');
    cancel.onclick = () => armed(cancel, 'Confirm cancel', () => busy(cancel, async () => { await api(`/api/runs/${id}/cancel`, {}).catch((er) => alert0(er.message)); await reload(); }));
  }

  async function viewRun(id) {
    shell('/research', '<div id="runboard">' + boardTitle('Research run') + '</div><dl class="figures measure" id="runfigs" style="margin-top:14px"></dl>', `
      <div id="rsibox"></div>
      <div id="rsiobs" class="rsiobs"></div>
      <section><div class="section-head"><h2>Agent log</h2><span id="runact"></span></div><div id="flash"></div>
        <p class="hint" style="margin:2px 0 10px">Watch the agent reason in real time — each hypothesis, backtest and verdict as it happens. Every strategy links to its full result once its outcome is in; see them all on the <a href="/strategies">Strategies</a> page.</p>
        <div class="runfeed" id="runfeed"><ol class="log stream" id="log" role="log" aria-label="Agent reasoning log"><li class="log-empty" data-empty>Waiting for the first event — the agent is spinning up. The loop above shows the phase it's in.</li></ol><button class="jumplatest" id="jumplatest" type="button" hidden>new ↓</button><div class="runpulse" id="runpulse" aria-live="polite" hidden></div></div></section>`);
    let after = 0, tried = 0;
    const stream = runFeed(root.querySelector('#runfeed'));
    const obs = rsiObservatory(root.querySelector('#rsiobs'));
    const load = async () => {
      const d = await api(`/api/runs/${id}?after=${after}`);
      const r = d.run;
      const active = r.status === 'running' || r.status === 'queued' || r.status === 'paused';
      root.querySelector('#runboard').innerHTML = boardTitle(sessionTitle(r), `${esc(marketShort(r.market))} \u00b7 ${dirLabel(r.direction)}`);
      const started = r.started_at ? Date.parse(r.started_at) : null;
      const end = r.finished_at ? Date.parse(r.finished_at) : Date.now();
      const statusText = r.status === 'queued' ? 'Waiting<span class="working" aria-label="in process"></span>'
        : r.status === 'paused' ? 'Paused'
        : r.status === 'running' ? 'Researching<span class="working" aria-label="in process"></span>'
        : r.status === 'succeeded' ? 'Done' : r.status === 'stopped' ? 'Stopped'
        : r.status === 'cancelled' ? 'Cancelled' : 'Failed';
      root.querySelector('#runfigs').innerHTML =
        fig('Status', statusText) +
        fig('Time', started ? Math.max(0, Math.round((end - started) / 60000)) + ' min' : '—') +
        fig('Hypotheses', r.hypotheses_tried || tried) + fig('Passed', active ? '…' : r.strategies_passed) +
        fig('RSI policy', d.rsi && d.rsi.evolved ? 'Evolved' : 'Self-tuning',
            { small: d.rsi && d.rsi.evolved ? `generalization score ${d.rsi.score}` : 'dreams a better search each run' });
      const rsibox = root.querySelector('#rsibox');
      if (rsibox && d.rsi) {
        const delta = (d.rsi.base_score != null && d.rsi.score != null)
          ? `<span class="rsi-score">${d.rsi.base_score} <span class="rsi-arrow">→</span> ${d.rsi.score}</span>` : '';
        // The adopted policy is arbitrary agent-evolved Python with no structured decision record
        // behind it, so a raw-source dump isn't inspection — the human "What it changed" summary
        // and the generalization-score delta below are the faithful, readable account.
        rsibox.innerHTML = `<div class="rsi-card"><div class="rsi-head"><b class="rsi-badge">RSI</b> Self-improving research ${d.rsi.evolved ? '<span class="rsi-tag">Evolved</span>' : '<span class="rsi-tag quiet">Self-tuning</span>'}</div>
          ${d.rsi.evolved
            ? `<p>This agent <b>rewrote its own search policy</b> from your history — and it beats the default.</p>
               ${d.rsi.summary ? `<p class="rsi-what"><b>What it changed:</b> ${esc(d.rsi.summary)}</p>` : ''}
               <p class="rsi-last">Generalization score ${delta}${d.rsi.evolved_at ? ' · adopted ' + when(d.rsi.evolved_at) : ''} <span class="rsi-note">(higher = catches more real out-of-sample winners, scored over shuffled orderings so it can't overfit)</span></p>`
            : `<p>The agent is <b>self-tuning</b>: after each research cycle it dreams up new search strategies and keeps one only if it beats the current policy on your own history (scored over shuffled orderings, so it can't overfit).</p>
               ${d.rsi.last_dream ? `<p class="rsi-last"><b>Last check${d.rsi.last_dream_at ? ' · ' + when(d.rsi.last_dream_at) : ''}:</b> ${esc(d.rsi.last_dream)}</p>` : '<p class="rsi-last">The first result appears at the end of a research cycle.</p>'}`}
          </div>`;
      }
      runControls(root.querySelector('#runact'), id, r.status, load);
      d.events.forEach((ev) => { after = Math.max(after, ev.id); if (ev.kind === 'hypothesis') tried++; });
      stream.push(d.events);
      stream.state(active ? r.status : 'done');
      obs.push(d.events, r.status, r);
      if (!active) clearTimers();
    };
    await load();
    poll(load, 2000);
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
      const d = await api('/api/strategies?' + p.toString());
      const counts = d.counts || {}, total = counts.total || 0, c = (st) => counts[st] || 0;
      root.querySelector('#sfigs').innerHTML = fig('Passed' + glo('passed'), c('passed')) + fig('Void on unseen data' + glo('void'), c('failed')) + fig('Rejected in testing' + glo('rejected'), c('rejected')) +
        fig('Pass rate', total ? pct(c('passed') / total, false) : '—');
      const kept = total - c('failed') - c('rejected');
      root.querySelectorAll('[data-f="status"]').forEach((b) => { const v = b.dataset.v; b.textContent = v ? `${CLABEL[v]} (${c(v)})` : `Kept (${kept})`; });
      if (!d.matched) {
        slipsEl.innerHTML = `<div class="empty"><h3>Nothing here yet</h3><p>${total ? 'Try another filter.' : 'Start a research session and the strategies it finds will land here.'}</p>${total ? '' : '<a class="btn" href="/research">Go to Research</a>'}</div>`;
        return;
      }
      const list = d.strategies, reg = registry(list.map((s) => s.equity));
      const anyPassed = list.some((s) => s.status === 'passed' && !researchOnly(s));
      slipsEl.innerHTML = strategyTable(list.map((s) => strategySlip(s, reg, { pick: anyPassed })).join(''), anyPassed)
        + (d.pages > 1 ? `<div class="xpage">${sp > 0 ? `<button class="btn sm" data-sp="${sp - 1}">← Prev</button>` : '<span></span>'}<span class="lab">Page ${sp + 1} of ${num(d.pages)} · ${num(d.matched)} strategies</span>${sp + 1 < d.pages ? `<button class="btn sm" data-sp="${sp + 1}">Next →</button>` : '<span></span>'}</div>` : '');
      slipsEl.querySelectorAll('[data-sp]').forEach((b) => b.onclick = () => { sp = +b.dataset.sp; load(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
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
      flash('#bulkflash', `${ok} deployed${errs.length ? ` · ${errs.length} failed: ${esc(errs[0])}` : ''}`, errs.length ? 'bad' : 'good');
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

  async function viewStrategy(id) {
    shell('/strategies', boardTitle('Strategy') + '<dl class="figures measure" id="figs" style="margin-top:14px"></dl>', loading(420));
    const s = await api('/api/strategies/' + id);
    const perpetual = isPerpetual(s), restricted = researchOnly(s);
    const ins = s.in_sample || {}, oos = s.out_of_sample;
    const figsFor = (r) => fig('Unseen-data P&L', r.out_of_sample ? usd(r.out_of_sample.pnl, true) : '—', { v: r.out_of_sample && r.out_of_sample.pnl, small: r.out_of_sample ? `${r.out_of_sample.trades} trades the agent never saw` : 'Rejected before the unseen test' }) +
      fig('In-sample P&L', usd(r.in_sample.pnl, true), { v: r.in_sample.pnl, small: `${r.in_sample.trades} trades` }) +
      fig('Return on capital', r.out_of_sample ? pct(r.out_of_sample.roi) : '—', { small: `$${fmt0.format(r.capital || 0)} at risk at most` }) +
      fig('Hypotheses tested', s.hypotheses_tried ? `1 of ${s.hypotheses_tried}` : '—', { small: s.hypotheses_tried ? `The agent tested ${num(s.hypotheses_tried)} distinct ideas this run; this is the one that passed. More tries → higher chance one passes by luck (multiple testing).` : 'How many ideas the agent tried to find this one.' });
    root.querySelector('.board-title').outerHTML = boardTitle(serial(s.id) + ' · ' + marketShort(s.market), esc(dirLabel(s.direction)));
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
    const liveWhy = !S.me.live_trading_available ? 'Live trading isn’t open yet.' : !S.me.kalshi_connected ? 'Connect Kalshi on the Funds page first.' : (s.side !== 'yes' && !S.me.no_side_live_enabled) ? 'NO-side live trading is still being validated on the demo sandbox — deploy this on demo or paper for now.' : '';
    const demoWhy = !S.me.kalshi_dev_connected ? 'Add your Kalshi demo (sandbox) key on the Funds page first.' : '';
    // Overfit/luck tells on a raw backtest column: a tiny sample, a perfect win rate, no losing
    // trades (profit factor runs away), or an implausibly high daily Sharpe are the classic
    // signatures of a number too good to be real. Flag them inline so a raw backtest is never
    // read as a tradable edge.
    const luckFlag = (m) => {
      if (!m) return '';
      const r = [];
      if (m.trades != null && m.trades < 30) r.push(`n=${m.trades} — too few trades to tell skill from luck`);
      if (m.win_rate === 1) r.push('100% win rate — an overfit signature, not an edge');
      if (typeof m.profit_factor === 'number' && m.profit_factor >= 99) r.push('no losing trades in sample — profit factor is meaningless');
      if (typeof m.sharpe === 'number' && m.sharpe >= 3) r.push(`Sharpe ${m.sharpe} is implausibly high for a real net edge`);
      return r.length ? `<p class="hint luck-flag">⚠ ${esc(r.join(' · '))}</p>` : '';
    };
    const metricRows = (m) => m ? `<dl>
        <dt>P&amp;L after fees</dt><dd class="${tone(m.pnl)}">${usd(m.pnl, true)}</dd>
        <dt>Trades</dt><dd>${m.trades}${m.trades_per_day != null ? ` <small class="hint">(${m.trades_per_day}/day)</small>` : ''}</dd>
        <dt>Win rate</dt><dd>${pct(m.win_rate, false)}</dd>
        <dt>Fees paid</dt><dd>${usd(m.fees)}</dd>
        <dt>Profit factor</dt><dd>${m.profit_factor == null ? '—' : m.profit_factor}</dd>
        <dt>Worst drawdown</dt><dd>${usd(m.max_drawdown)}</dd>
        <dt>Sharpe (daily)</dt><dd>${m.sharpe == null ? '—' : m.sharpe}</dd></dl>${luckFlag(m)}` : `<p class="hint">Not tested on unseen data — ${rejectReason(s)}</p>`;
    const gatesHtml = (gs) => gs ? `<ul class="gates">${gs.map((g) => `<li class="${g.ok ? 'ok' : 'no'}">${g.ok ? ICON.check : ICON.cross}<span>${esc(g.name)}<small>needs ${esc(g.threshold)}</small></span><span class="v">${typeof g.value === 'number' && /\$|drawdown|money/i.test(g.name + g.threshold) ? usd(g.value) : esc(g.value == null ? '—' : g.value)}</span></li>`).join('')}</ul>` : '<p class="hint">Gates only run for finalists that made money in testing.</p>';
    const trades = (s.recent_trades || []).length ? `<table class="table stack"><thead><tr><th>Opened</th><th>Contract</th><th>Side</th><th class="num">Entry${perpetual ? ' (USD)' : ''}</th><th class="num">Exit${perpetual ? ' (USD)' : ''}</th><th class="num">P&amp;L</th></tr></thead><tbody>
        ${s.recent_trades.map((t) => `<tr><td>${esc(new Date(t.opened.replace('Z', ':00Z')).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }))}</td><td class="tick">${esc(t.ticker)}</td><td>${esc(t.side.toUpperCase())} ×${t.qty}</td><td class="num">${tradePrice(t.entry, perpetual)}</td><td class="num">${tradePrice(t.exit, perpetual)} <small class="hint">${esc(t.reason)}</small></td><td class="num ${tone(t.pnl)}">${usd(t.pnl, true)}</td></tr>`).join('')}
      </tbody></table>` : '<p class="hint">No unseen-data trades to show.</p>';
    const activeDeps = restricted ? [] : s.deployments.filter((d) => d.status !== 'stopped');
    const kUrl = marketKalshiUrl(s.market);
    const mktLink = kUrl ? `<a href="${kUrl}" target="_blank" rel="noopener">${esc(marketLabel(s.market))} ↗</a>` : esc(marketLabel(s.market));
    // ---- the strategy dossier, composed as a research paper (abstract → mechanism →
    // methodology → results → verdict). Each section renders only when it has content, so a
    // pre-pipeline strategy with no ledger row falls back to its rule + backtest + plain verdict.
    const rp = researchPaper(s.experiment);
    const hasExp = !!s.experiment;
    const filed = (() => { try { return new Date(s.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); } catch (e) { return ''; } })();
    const abResult = oos
      ? `On unseen data the agent never touched while iterating, it ${+oos.pnl >= 0 ? 'returned ' + usd(oos.pnl) : 'lost ' + usd(Math.abs(oos.pnl))} over ${num(oos.trades)} trade${oos.trades === 1 ? '' : 's'}${s.hypotheses_tried ? `, the one idea of ${num(s.hypotheses_tried)} tested this run that cleared the gate` : ''}.`
      : `It was ${s.status === 'rejected' ? 'rejected before reaching' : 'not advanced to'} the unseen-data test${s.hypotheses_tried ? ` — one of ${num(s.hypotheses_tried)} ideas tried this run` : ''}.`;
    const dataBlock = s.dataset ? `<div class="paper-sub"><h4 class="paper-h">Data &amp; partitioning</h4>
          <dl class="rp-grid">
            <div><dt>Market</dt><dd>${mktLink}</dd></div>
            <div><dt>Direction</dt><dd>${esc(dirLabel(s.direction))}</dd></div>
            <div><dt>History window</dt><dd>${esc(s.dataset.start.slice(0, 10))} → ${esc(s.dataset.end.slice(0, 10))}</dd></div>
            <div><dt>Unseen (held out) from</dt><dd>${esc((s.dataset.out_of_sample_from || '').slice(0, 10)) || '—'}</dd></div>
          </dl>
          <p class="rp-sub" style="margin-top:8px">${perpetual ? 'The agent only saw the research partition. ' + PERPS_SCENARIO : "The agent only ever saw data before the held-out date. Every simulated fill pays the ask or bid plus Kalshi's taker fee — results are net of fees or they do not count."}</p></div>` : '';
    const ruleBlock = `<div class="paper-sub"><h4 class="paper-h">The decision rule, in plain words</h4>
          <ul class="rules">${s.rules.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>
          <details class="raw"><summary>Exact machine spec (JSON)</summary><pre>${esc(JSON.stringify(s.spec, null, 2))}</pre></details></div>`;
    const methodologyBody = rp.methodology + ruleBlock + dataBlock + (perpetual && !s.dataset ? `<p class="hint">${PERPS_SCENARIO}</p>` : '');
    const resultsBody = rp.results
      + `<div class="paper-sub"><h4 class="paper-h">${perpetual ? 'Perpetual research scenario' : hasExp ? 'Backtest &amp; Kalshi demo replay' : 'Backtest'}</h4>
          ${hasExp ? '<p class="rp-sub" style="margin-top:0">These are the agent\'s own in-sample/replay numbers. The in-sample column is optimistically biased — the rule was fit on exactly this data — so trust the held-out validation-window evidence above, not the column below.</p>' : ''}
          <div id="sheet-results">
            <div id="equity-wrap">${s.equity ? equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from) : ''}</div>
            <div class="split"><div><h4>Tested on (in-sample)</h4>${metricRows(ins)}</div><div><h4>Never seen (out-of-sample)</h4>${metricRows(oos)}</div></div>
          </div></div>`
      + `<div class="paper-sub"><h4 class="paper-h">Most recent unseen trades</h4>${trades}</div>`;
    let verdictBody = rp.verdict;
    if (!hasExp) {
      const btOnly = ['sig', 'armed', 'Backtest only', 'Backtest-only — never put through statistical validation (no pre-registration, one-time holdout, or multiple-testing control). These numbers come from a sample too small to separate skill from luck. ' + (restricted ? 'This market remains research only.' : 'Deploying it is your decision and your risk.')];
      const vmap = {
        // No experiment resolved (by experiment_id OR strategy_id) means NO gatekeeper record
        // exists — so this was NOT validated, whatever the status says. Never claim it "cleared
        // the gatekeeper" (that would be a lie); flag the missing record honestly. A correctly
        // validated 'passed' always has an experiment and takes the rich path above, not this one.
        passed: ['sig', 'armed', 'Not validated (record missing)', 'Marked passed, but no statistical-gatekeeper record (pre-registration, validation, holdout) can be found for it — so the numbers below are the in-sample backtest only, not held-out evidence. Treat it as unvalidated; the row is being reclassified to backtest-only.'],
        'backtest-only': btOnly,
        failed: ['sig', 'armed', 'Void', 'It reached the unseen-data gate and failed it, so it was not validated.'],
        rejected: ['quiet', 'quiet', 'Rejected', 'Rejected — ' + rejectReason(s)],
      };
      const [vt, chip, label, words] = vmap[s.status] || ['quiet', 'quiet', rpHuman(s.status), 'Awaiting a recorded verdict.'];
      verdictBody = `<div class="rp-verdict ${vt}"><span class="mk ${chip}">${esc(label)}</span><p>${esc(words)}</p></div>`;
    }
    const paperSec = (title, body) => body ? `<section class="paper-sec"><h3 class="paper-sec-t">${title}</h3><div class="paper-sec-body">${body}</div></section>` : '';
    root.querySelector('main').innerHTML = `
      <div id="flash"></div>
      <div class="detail">
        <div>
          <article class="sheet-doc paper">
            <header class="paper-head">
              <div class="paper-cite"><span>${esc(serial(s.id))}</span><span>${esc(marketShort(s.market))} · ${esc(dirLabel(s.direction))}</span>${filed ? `<span>Filed ${esc(filed)}</span>` : ''}</div>
              <h2 class="paper-title">${esc(s.title)}</h2>
              <div class="paper-byline">${mark(s.status)}${researchBadge(s)}${s.shared_from ? ` <span class="mk shared">${ICON.share}Shared by ${esc(s.shared_from)}</span>` : ''}</div>
            </header>
            <section class="paper-abstract">
              <h3 class="paper-h">Abstract</h3>
              <p class="paper-ab">${mdLite(s.thesis)}</p>
              <p class="paper-ab-result">${abResult}</p>
            </section>
            <div class="paper-body">
              ${paperSec('Mechanism &amp; hypothesis', rp.mechanism)}
              ${paperSec('Methodology', methodologyBody)}
              ${paperSec('Results', resultsBody)}
              ${paperSec('Verdict', verdictBody)}
            </div>
          </article>
        </div>
        <aside>
          ${!restricted && s.holdings && s.holdings.length ? (() => {
            const marked = s.holdings.filter((p) => p.unrealized != null);
            const unreal = marked.reduce((a, p) => a + p.unrealized, 0);
            return `<section class="panel"><h3>Holding right now</h3>
            <div class="sheet"><table class="table stack t-dep"><thead><tr><th>Contract</th><th>Position</th><th class="num">Cost</th><th class="num">Unreal.</th><th class="num">Settles</th></tr></thead><tbody>
            ${s.holdings.map((p) => `<tr><td class="tick" data-lab="Contract">${esc(p.ticker)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : p.mode === 'demo' ? '<span class="mk dep">Demo</span>' : ''}</td><td data-lab="Position">${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(p.entry_price)}</td><td class="num" data-lab="Cost">${usd(p.cost)}</td><td class="num" data-lab="Unreal.">${p.unrealized == null ? '<span class="sub-fig">—</span>' : money(p.unrealized)}</td><td class="num" data-lab="Settles">${clock(p.market_close_time)}</td></tr>`).join('')}
            </tbody></table></div>
            <p class="hint" style="margin-top:8px">${s.holdings.length} open position${s.holdings.length === 1 ? '' : 's'} at cost ${usd(s.holdings.reduce((a, p) => a + p.cost, 0))}${marked.length ? ` · unrealized ${money(unreal)} (est., mark-to-market on the current bid)` : ' · awaiting first mark'}.</p></section>`;
          })() : ''}
          <section class="panel"><h3>${restricted ? 'Research only' : 'Deploy'}</h3>
            ${canDeploy ? `<div style="display:grid;gap:10px">
                ${s.status !== 'passed' ? `<div class="notice bad">${ICON.warn}<span>${s.status === 'failed' ? 'Void: it failed the unseen-data gate.' : `Rejected: ${rejectReason(s)}`} It wasn’t validated, so deploying it — on paper or live — is your call and your risk.</span></div>` : ''}
                <button class="btn" id="dep-paper">Deploy on paper</button>
                <button class="btn ghost" id="dep-demo" ${demoWhy ? 'aria-disabled="true"' : ''}>Deploy on demo (sandbox)</button>
                ${demoWhy ? `<p class="hint">${esc(demoWhy)}</p>` : '<p class="hint">Trades Kalshi’s demo exchange with your own demo key — real order-book fills, no real money.</p>'}
                <button class="btn ghost" id="dep-live" ${liveWhy ? 'aria-disabled="true"' : ''}>Deploy with live money</button>
                ${liveWhy ? `<p class="hint">${esc(liveWhy)}</p>` : ''}
                <form id="live-confirm" hidden style="display:grid;gap:8px">
                  <p class="hint">This trades real money in your Kalshi account. Type <b>LIVE</b> to confirm.</p>
                  <input class="input" name="confirm" autocomplete="off" aria-label="Type LIVE to confirm">
                  <button class="btn" type="submit">Confirm live deployment</button>
                </form>
                <div id="depflash"></div>
              </div>` : restricted ? '<p class="hint">Perpetual strategies stay in research, including after passing the statistical gates. Paper, demo and live deployment are unavailable.</p>' : '<p class="hint">This strategy isn’t ready to deploy yet.</p>'}
            ${!restricted && s.deployments.length ? `<p class="hint" style="margin-top:12px">Already deployed: ${s.deployments.map((d) => `#${d.id} (${esc(d.mode)}, ${esc(d.status)})`).join(', ')}. <a href="/deploy">Open the board</a></p>` : ''}
            ${kUrl ? `<p class="hint" style="margin-top:12px"><a href="${kUrl}" target="_blank" rel="noopener">Open ${esc(marketShort(s.market))} on Kalshi ↗</a></p>` : ''}
          </section>
          <section class="panel"><h3>Remove</h3>
            <p class="hint" style="margin-bottom:8px">Delete this strategy from your inventory. ${activeDeps.length ? 'Stop its deployment first — you can do it right here.' : 'This can’t be undone.'}</p>
            <div style="display:grid;gap:8px">
              ${activeDeps.length ? `<button class="btn sm danger" id="stop-dep">Stop deployment${activeDeps.length > 1 ? 's' : ''} (${activeDeps.map((d) => '#' + d.id).join(', ')})</button>` : ''}
              <button class="btn sm danger" id="del-strat" ${activeDeps.length ? 'aria-disabled="true"' : ''}>Delete strategy</button>
            </div><div id="delflash"></div>
          </section>
          <section class="panel"><h3>Share</h3>
            <p class="hint" style="margin-bottom:8px">${restricted ? 'Share a research-only copy using their Tau sign-in email. It keeps the same simulation limits and cannot be deployed.' : "Send a copy to a friend by the email they sign in with. They can deploy it like their own — sharing can't be undone."}</p>
            <form id="share-form" style="display:grid;gap:8px">
              <input class="input" id="share-email" type="email" autocomplete="off" placeholder="friend@email.com" aria-label="Friend's email">
              <button class="btn sm" type="submit">Share strategy</button>
            </form><div id="shareflash"></div>
          </section>
          <section class="panel"><h3>Gates</h3><div id="gates">${gatesHtml(s.gates)}</div></section>
          ${!restricted && s.status === 'passed' ? `<section class="panel" id="road-live"><h3>Road to live</h3><div id="road-live-body"><p class="hint">Checking…</p></div></section>` : ''}
          ${!perpetual && s.status !== 'rejected' ? `<section class="panel" id="whatif"><h3>What if…</h3>
            <p class="hint" style="margin-bottom:6px">Move a dial and the whole sheet re-runs.</p>
            <div class="dial"><div class="top"><label class="label" for="wf">Fees</label><output id="wfo">1.0×</output></div><input type="range" id="wf" min="0" max="3" step="0.25" value="1"></div>
            <div class="dial"><div class="top"><label class="label" for="ws">Slippage per fill</label><output id="wso">0.0¢</output></div><input type="range" id="ws" min="0" max="5" step="0.1" value="0"></div>
            <div class="dial"><div class="top"><label class="label" for="wk">Stake per trade</label><output id="wko">$${esc(s.stake)}</output></div><input type="range" id="wk" min="1" max="200" step="1" value="${Math.min(200, s.stake)}"></div>
            <div id="wflash" aria-live="polite"></div>
          </section>` : ''}
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
          wrap.innerHTML = equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from, r.dev_curve)
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
    // Road to live: the exact gates the deploy paths enforce (gatekeeper, realistic paper record,
    // live autopilot), with progress. Best-effort and fetched after the page, like the dev curve.
    if (root.querySelector('#road-live-body')) (async () => {
      try {
        const r = await api('/api/strategies/' + s.id + '/live-readiness');
        const p = r.paper, c = p.checks;
        const pv = p.p_value == null ? '—' : p.p_value.toFixed(2);
        const rows = [
          { name: 'Gatekeeper cleared', threshold: 'holdout + diversification', ok: r.deployment_candidate, value: r.deployment_candidate ? 'yes' : 'no' },
          { name: 'Realistic paper trades', threshold: p.trades_needed + '+', ok: c.realistic_trades, value: p.trades + ' / ' + p.trades_needed },
          { name: 'Net after fees', threshold: 'above $0', ok: c.net_pnl, value: p.net_pnl },
          { name: 'Paper track record', threshold: p.span_needed_hours + 'h+', ok: c.span, value: Math.round(p.span_hours) + 'h' },
          { name: 'Edge is not luck', threshold: 'p ≤ ' + p.p_value_needed.toFixed(2), ok: c.edge, value: pv },
          { name: 'Live autopilot', threshold: 'on, key, under daily loss', ok: r.live_autopilot.ok, value: r.live_autopilot.ok ? 'ready' : 'off' },
        ];
        const body = root.querySelector('#road-live-body');
        if (body) body.innerHTML = gatesHtml(rows)
          + (p.realization != null ? `<p class="hint" style="margin-top:6px;font-variant-numeric:tabular-nums">Paper earns <b>${Math.round(p.realization * 100)}%</b> of the backtest's unseen-data P&amp;L per trade.</p>` : '')
          + `<p class="hint" style="margin-top:6px">${r.ready ? 'Every gate is clear. Autopilot may move this to live money within your caps.' : 'Blocked: ' + esc(r.blocking) + '.'} Paper counts only fills simulated against the live order book.</p>`;
      } catch (e) {
        const body = root.querySelector('#road-live-body');
        if (body) body.innerHTML = '<p class="hint">Live readiness is unavailable right now.</p>';
      }
    })();
    const depPaper = root.querySelector('#dep-paper');
    if (depPaper) depPaper.onclick = () => busy(depPaper, async () => {
      try { await api('/api/deployments', { strategy_id: s.id, mode: 'paper' }); go('/deploy'); } catch (e) { flash('#depflash', e.message, 'bad'); }
    });
    const depDemo = root.querySelector('#dep-demo');
    if (depDemo) depDemo.onclick = () => { if (demoWhy) return; busy(depDemo, async () => {
      try { await api('/api/deployments', { strategy_id: s.id, mode: 'demo' }); go('/deploy'); } catch (e) { flash('#depflash', e.message, 'bad'); }
    }); };
    const stopDep = root.querySelector('#stop-dep');
    if (stopDep) stopDep.onclick = () => armed(stopDep, 'Confirm stop', () => busy(stopDep, async () => {
      try { for (const d of activeDeps) await api(`/api/deployments/${d.id}/stop`, {}); viewStrategy(s.id); } catch (e) { flash('#delflash', e.message, 'bad'); }
    }));
    const delStrat = root.querySelector('#del-strat');
    if (delStrat) delStrat.onclick = () => {
      if (activeDeps.length) { flash('#delflash', 'Stop its deployment first (button above).', 'bad'); return; }
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
    if (depLive) depLive.onclick = () => { if (!liveWhy) root.querySelector('#live-confirm').hidden = false; };
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
        const fee = +wi.querySelector('#wf').value, slip = +wi.querySelector('#ws').value, stake = +wi.querySelector('#wk').value;
        wi.querySelector('#wfo').textContent = fee.toFixed(2).replace(/0$/, '') + '×';
        wi.querySelector('#wso').textContent = slip.toFixed(1) + '¢';
        wi.querySelector('#wko').textContent = '$' + stake;
        clearTimeout(t);
        t = setTimeout(async () => {
          const mine = ++seq;
          root.querySelector('#sheet-results').style.opacity = '.55';
          try {
            const r = await api(`/api/strategies/${s.id}/whatif`, { fee_multiplier: fee, slippage_cents: slip, stake });
            if (mine !== seq) return;
            root.querySelector('#sheet-results').innerHTML = equityChart(r.equity, s.dataset && s.dataset.out_of_sample_from) +
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
  async function viewDeploy() {
    // Autopilot + the agent chat now live in the floating window (reachable from every view),
    // so Deploy is just the board: what's trading and the open positions.
    shell('/deploy', boardTitle('Deploy', 'Your strategies trading now.') +
      '<dl class="figures measure" id="dfigs" style="margin-top:14px"></dl>', `
      <div class="deploy-board"><div id="flash"></div><div id="deps">${loading(260)}</div>
        <section class="section"><div class="section-head"><h2>Open positions</h2></div><div id="openpos"></div></section>
      </div>`);
    const loadBoard = async () => {
      const d = await api('/api/deployments');
      const running = d.deployments.filter((x) => x.status === 'running');
      const realized = d.deployments.reduce((a, x) => a + x.realized_pnl, 0);
      const live = d.deployments.filter((x) => x.mode === 'live' && x.status === 'running');
      root.querySelector('#dfigs').innerHTML = fig('Running', running.length, { small: `${d.deployments.length - running.length} paused` }) +
        fig('Realized', usd(realized, true), { v: realized, small: 'all deployments, paper and live' }) +
        fig('Open positions', d.open_positions.length) +
        fig('Money', live.length ? '<span class="mk live">Live</span>' : '<span class="mk">Paper</span>', { small: live.length ? `${live.length} on live money` : 'nothing on live money' });
      const reg = registry(d.deployments.map((x) => x.curve));
      root.querySelector('#deps').innerHTML = d.deployments.length ? deploymentTable(d.deployments.map((x) => deploymentSlip(x, reg, true)).join(''), true)
        : `<div class="empty"><h3>Nothing deployed</h3><p>Open a passed strategy and post it to the board. Paper first: it trades the live market with paper money.</p><a class="btn" href="/strategies">See passed strategies</a></div>`;
      bindDeploymentActions(root.querySelector('#deps'), loadBoard);
      root.querySelector('#openpos').innerHTML = d.open_positions.length ? `<table class="table stack"><thead><tr><th>Strategy</th><th>Contract</th><th>Side</th><th class="num">Cost</th><th class="num">Unreal.</th><th class="num">Settles</th></tr></thead><tbody>
        ${d.open_positions.map((p) => `<tr><td>${esc(p.title)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : p.mode === 'demo' ? '<span class="mk dep">Demo</span>' : ''}</td><td class="tick">${esc(p.ticker)}</td><td>${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(+p.entry_price)}</td><td class="num">${usd(p.qty * p.entry_price + +p.entry_fee)}</td><td class="num">${p.unrealized == null ? '<span class="sub-fig">—</span>' : money(p.unrealized)}</td><td class="num">${clock(p.market_close_time)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="hint">No open positions.</p>';
    };
    await loadBoard();
    poll(loadBoard, 10000);
  }
  const confirmAutopilot = { armed: false };

  // ---------- funds ----------
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
      root.querySelector('#ffigs').innerHTML = fig('Live money', k.connected ? (k.balance == null ? 'Unavailable' : usd(k.balance)) : 'Not connected', { cls: 'lead', small: k.connected ? 'Your real cash at Kalshi' : 'Connect a key to trade real money' }) +
        fig('Demo balance', usd(dm.equity), { small: `${usd(dm.capital)} capital · app-controlled` }) +
        fig('Paper cash', usd(d.paper.cash), { small: 'Practice money for paper trading' });
      root.querySelector('main').innerHTML = `<div id="flash"></div><div class="funds">
        <div class="funds-col funds-manage">
        <section class="panel">
          <h3>Kalshi account (live money)</h3>
          ${k.connected ? `
            <dl class="kv"><dt>API key</dt><dd>${esc(k.key_id)}</dd><dt>Cash at Kalshi</dt><dd>${k.balance == null ? 'Couldn’t read it just now' : usd(k.balance)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">This is your real Kalshi balance. Deposits and withdrawals happen at Kalshi, in your own account — we never hold your money. Tau only places trades for strategies you deploy live.</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <a class="btn" href="${esc(k.funding_url)}" target="_blank" rel="noopener">Deposit or withdraw at Kalshi ${ICON.ext}</a>
              <button class="btn danger" id="disconnect">Disconnect</button>
            </div>` : `
            <p class="lede" style="margin-bottom:12px">Live trading runs in your own Kalshi account, so we never hold your money and can’t add it for you. Connect an API key to see your real balance and trade real money.</p>
            <ol class="steps"><li>On Kalshi, open Account → API keys and create a key.</li><li>Copy the key ID and download the private key file.</li><li>Paste both below. We encrypt the private key and check it with Kalshi before saving.</li></ol>
            <form id="kalshi" style="display:grid;gap:12px">
              <label class="field"><span>Key ID</span><input class="input" name="key_id" autocomplete="off" spellcheck="false" required></label>
              <label class="field"><span>Private key</span><textarea class="input" name="private_key" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
              <button class="btn" type="submit">Verify and connect</button>
            </form>`}
          <div id="kflash" style="margin-top:10px"></div>
        </section>
        <section class="panel">
          <h3>Kalshi demo (sandbox) account</h3>
          <dl class="kv"><dt>Demo balance</dt><dd>${usd(dm.equity)}</dd><dt>Starting capital</dt><dd>${usd(dm.capital)}</dd><dt>P&amp;L since reload</dt><dd class="${tone(dm.realized)}">${usd(dm.realized, true)}</dd></dl>
          <p class="lede" style="margin-bottom:14px">Demo places real orders on Kalshi’s sandbox for real fills, so slippage is realistic — but the money is ours to set. Reload it to any amount; this never touches your real demo-account balance.</p>
          <form id="demo" class="amount">
            <label class="field"><span>Reload to</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="1000"></label>
            <button class="btn" type="submit">Reload demo</button>
          </form>
          <div id="dmflash" style="margin-top:10px"></div>
          <h3 style="margin-top:24px">Demo key</h3>
          ${kd.connected ? `
            <dl class="kv"><dt>Demo key</dt><dd>${esc(kd.key_id)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">Demo deployments trade Kalshi’s sandbox exchange with this key — real order-book fills, no real money. Your demo key is stored separately from your live key and is never used for live trading.</p>
            <button class="btn danger" id="dev-disconnect">Remove demo key</button>` : `
            <p class="lede" style="margin-bottom:12px">Connect a Kalshi <b>demo</b> API key to deploy strategies on the sandbox exchange — real market fills, no real money. It’s kept separate from your live key.</p>
            <ol class="steps"><li>Sign in at demo.kalshi.co and open Account → API keys.</li><li>Copy the key ID and download the private key file.</li><li>Paste both below. We encrypt the private key and check it against the demo exchange before saving.</li></ol>
            <form id="kalshi-dev" style="display:grid;gap:12px">
              <label class="field"><span>Demo key ID</span><input class="input" name="key_id" autocomplete="off" spellcheck="false" required></label>
              <label class="field"><span>Demo private key</span><textarea class="input" name="private_key" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
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
            <button class="btn ghost" data-kind="reset" type="submit">Reset to</button>
          </form>
          <div id="pflash" style="margin-top:10px"></div>
        </section>
        ${S.me.perps_live_available ? '<section id="kalshi-perps-live" aria-label="Bitcoin perpetual trading"></section>' : ''}
        </div>
        <div class="funds-col funds-history">
        <section class="panel">
          <h3>Paper history</h3>
          <table class="table stack"><thead><tr><th>When</th><th>What</th><th class="num">Amount</th></tr></thead><tbody>
            ${d.paper.ledger.map((r) => `<tr><td class="hint lead-cell">${when(r.created_at)}</td><td>${esc(r.memo || r.kind)}</td><td class="num ${tone(+r.amount)}">${usd(r.amount, true)}</td></tr>`).join('')}
          </tbody></table>
        </section>
        </div></div>`;
      if (S.perps) { S.perps.destroy(); S.perps = null; }
      const perpsHost = root.querySelector('#kalshi-perps-live');
      if (window.TAU_PERPS_LIVE && perpsHost) S.perps = window.TAU_PERPS_LIVE.mount(perpsHost, {api, proposalId: new URLSearchParams(location.search).get('perps_proposal')});
      const df = root.querySelector('#demo');
      if (df) df.onsubmit = async (e) => {
        e.preventDefault();
        await busy(df.querySelector('button'), async () => {
          try { await api('/api/funds/demo', { amount: +df.amount.value }); await load(); flash('#dmflash', 'Demo account reloaded.', 'good'); } catch (err) { flash('#dmflash', err.message, 'bad'); }
        });
      };
      const pf = root.querySelector('#paper');
      let kind = 'deposit';
      pf.querySelectorAll('button').forEach((b) => (b.onclick = () => (kind = b.dataset.kind)));
      pf.onsubmit = async (e) => {
        e.preventDefault();
        const btn = pf.querySelector(`[data-kind="${kind}"]`);
        await busy(btn, async () => {
          try { await api('/api/funds/paper', { kind, amount: +pf.amount.value }); await load(); flash('#pflash', kind === 'deposit' ? 'Added to your paper account.' : kind === 'withdraw' ? 'Withdrawn from your paper account.' : 'Paper account reset.', 'good'); } catch (err) { flash('#pflash', err.message, 'bad'); }
        });
      };
      const kf = root.querySelector('#kalshi');
      if (kf) kf.onsubmit = async (e) => {
        e.preventDefault();
        await busy(kf.querySelector('button'), async () => {
          try { await api('/api/kalshi-key', { key_id: kf.key_id.value, private_key: kf.private_key.value }); S.me.kalshi_connected = true; await load(); flash('#kflash', 'Connected. Kalshi confirmed the key.', 'good'); } catch (err) { flash('#kflash', err.message, 'bad'); }
        });
      };
      const dc = root.querySelector('#disconnect');
      if (dc) dc.onclick = () => armed(dc, 'Confirm disconnect', () => busy(dc, async () => {
        try { await api('/api/kalshi-key/delete', {}); S.me.kalshi_connected = false; await load(); } catch (err) { flash('#kflash', err.message, 'bad'); }
      }));
      const kdf = root.querySelector('#kalshi-dev');
      if (kdf) kdf.onsubmit = async (e) => {
        e.preventDefault();
        await busy(kdf.querySelector('button'), async () => {
          try { await api('/api/kalshi-dev-key', { key_id: kdf.key_id.value, private_key: kdf.private_key.value }); S.me.kalshi_dev_connected = true; await load(); flash('#kdflash', 'Connected. Kalshi’s demo exchange confirmed the key.', 'good'); } catch (err) { flash('#kdflash', err.message, 'bad'); }
        });
      };
      const dvc = root.querySelector('#dev-disconnect');
      if (dvc) dvc.onclick = () => armed(dvc, 'Confirm remove', () => busy(dvc, async () => {
        try { await api('/api/kalshi-dev-key/delete', {}); S.me.kalshi_dev_connected = false; await load(); } catch (err) { flash('#kdflash', err.message, 'bad'); }
      }));
    };
    await load();
  }

  // ---------- community ----------
  function postSnapshot(snap) {
    if (!snap) return '';
    if (snap.kind === 'pnl') {
      return `<div class="snap"><div class="snap-row"><span>Paper P&amp;L</span><b class="${tone(snap.paper_pnl)}">${usd(snap.paper_pnl, true)}</b></div>
        <div class="snap-row"><span>Live P&amp;L</span><b class="${tone(snap.live_pnl)}">${usd(snap.live_pnl, true)}</b></div></div>`;
    }
    if (snap.kind === 'strategy') {
      return `<a class="snap" href="/strategies/${snap.id}"><div class="snap-head"><b>${esc(snap.title)}</b>${mark(snap.status)}${researchBadge(snap)}</div>
        <div class="snap-meta">${esc(marketShort(snap.market))} · unseen ${snap.pnl == null ? '—' : usd(snap.pnl, true)}${snap.trades != null ? ' · ' + snap.trades + ' trades' : ''}${snap.win_rate != null ? ' · ' + pct(snap.win_rate, false) + ' win' : ''}</div></a>`;
    }
    if (snap.kind === 'deployment') {
      return `<div class="snap"><div class="snap-head"><b>${esc(snap.title)}</b>${mark(snap.mode === 'live' ? 'running' : 'running', snap.mode === 'live')}</div>
        <div class="snap-meta">${esc(marketShort(snap.market))} · ${snap.mode === 'live' ? 'live' : 'paper'} · realized ${usd(snap.realized_pnl, true)} · ${snap.closed_trades} trades</div></div>`;
    }
    return '';
  }
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
        ${grouped ? '' : `<div class="post-head"><b>${authorLine(p.author, p.username)}</b><span class="when">${when(p.created_at)}${p.edited ? ' · edited' : ''}</span></div>`}
        <div class="post-main"><div class="post-body">${mdLite(p.body)}</div>
        ${p.image ? `<a class="post-img" href="${esc(p.image)}" target="_blank" rel="noopener"><img src="${esc(p.image)}" alt="" loading="lazy"></a>` : ''}
        ${postSnapshot(p.snapshot)}</div>
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
        <div id="feed">${loading(120)}${loading(120)}</div>
        <form class="panel composer-post" id="composer-post">
          <textarea class="input" id="post-body" maxlength="2000" rows="1" placeholder="Share an idea, a strategy, or how it's going…"></textarea>
          <div id="photo-preview" hidden><img id="photo-img" alt="Attached photo preview"><button type="button" class="photo-x" id="photo-remove" aria-label="Remove photo">${ICON.cross}</button></div>
          <div class="post-tools">
            <button class="btn sm" type="button" id="photo-btn">${ICON.image}Photo</button>
            <input type="file" id="photo-input" accept="image/png,image/jpeg,image/webp,image/gif" class="vh">
            <label class="field" style="min-width:0;flex:1"><span class="vh">Attach a strategy</span>
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
    const submit = async (kind, ref_id) => {
      const body = root.querySelector('#post-body').value.trim();
      const btn = form.querySelector('[type=submit]');
      await busy(btn, async () => {
        try {
          await api('/api/community', { body, kind, ref_id, image: pendingImage || undefined });
          root.querySelector('#post-body').value = ''; root.querySelector('#post-strat').value = ''; growTa();
          pendingImage = null; photoInput.value = ''; root.querySelector('#photo-preview').hidden = true;
          await load();
        } catch (e) { flash('#post-flash', e.message, 'bad'); }
      });
    };
    form.onsubmit = (e) => { e.preventDefault(); const ref = root.querySelector('#post-strat').value; submit(ref ? 'strategy' : 'note', ref || undefined); };
    form.querySelector('[data-share="pnl"]').onclick = () => submit('pnl');
    const feed = root.querySelector('#feed');
    const renderReactions = (art, list) => { art.querySelector('.reactions').innerHTML = reactionChips(list); };
    const react = async (pid, art, emoji) => {
      try { const r = await api(`/api/community/${pid}/react`, { emoji }); renderReactions(art, r.reactions); }
      catch (err) { alert0(err.message); }
    };
    feed.addEventListener('click', async (e) => {
      const addBtn = e.target.closest('[data-react-add]');
      if (addBtn) { const art = addBtn.closest('.post'); openEmojiPicker(addBtn, (emoji) => react(art.dataset.id, art, emoji)); return; }
      const chip = e.target.closest('.rx[data-emoji]');
      if (chip) { const art = chip.closest('.post'); react(art.dataset.id, art, chip.dataset.emoji); return; }
      const act = e.target.closest('[data-act]'); if (!act) return;
      const art = act.closest('.post'); const pid = art.dataset.id;
      if (act.dataset.act === 'like') {
        try {
          const r = await api(`/api/community/${pid}/like`, {});
          act.classList.toggle('on', r.liked); act.setAttribute('aria-pressed', r.liked);
          const c = act.querySelector('.c'); const n = (parseInt(c.textContent || '0', 10) || 0) + (r.liked ? 1 : -1);
          c.textContent = n > 0 ? n : '';
        } catch (err) { alert0(err.message); }
      } else if (act.dataset.act === 'edit') {
        const main = art.querySelector('.post-main'); const bodyEl = main.querySelector('.post-body');
        if (main.querySelector('.edit-form')) return;
        const current = bodyEl.textContent;
        const ef = document.createElement('form'); ef.className = 'edit-form';
        ef.innerHTML = `<textarea class="input" maxlength="2000">${esc(current)}</textarea><div class="edit-actions"><button class="btn sm" type="button" data-cancel>Cancel</button><button class="btn primary sm" type="submit">Save</button></div>`;
        bodyEl.hidden = true; bodyEl.insertAdjacentElement('afterend', ef);
        const ta = ef.querySelector('textarea'); ta.focus(); ta.setSelectionRange(current.length, current.length);
        ef.querySelector('[data-cancel]').onclick = () => { ef.remove(); bodyEl.hidden = false; };
        ef.onsubmit = async (ev) => {
          ev.preventDefault(); const nb = ta.value.trim(); if (!nb) return;
          await busy(ef.querySelector('[type=submit]'), async () => {
            try {
              await api(`/api/community/${pid}/edit`, { body: nb });
              bodyEl.textContent = nb; bodyEl.hidden = false; ef.remove();
              const w = art.querySelector('.post-head .when'); if (w && !/edited/.test(w.textContent)) w.textContent += ' · edited';
            } catch (err) { alert0(err.message); }
          });
        };
      } else {
        const box = art.querySelector('.comments');
        if (!box.hidden) { box.hidden = true; return; }
        box.hidden = false; box.innerHTML = loading(40);
        const d = await api(`/api/community/${pid}/comments`).catch(() => ({ comments: [] }));
        const many = d.comments.length > 6;      // search bar once a thread gets long
        const PAGE = 10;
        box.innerHTML = `${many ? '<div class="cmt-search"><input class="input" type="search" placeholder="Search replies…" aria-label="Search replies"><span class="cmt-count"></span></div>' : ''}
          ${d.comments.length > PAGE ? '<button type="button" class="btn sm cmt-more"></button>' : ''}
          <div class="cmt-list">${d.comments.map((c) => `<div class="cmt">${avatar(c.picture, c.author)}<div><b>${authorLine(c.author, c.username)}</b> <span class="when">${when(c.created_at)}</span><p>${mdLite(c.body)}</p></div></div>`).join('')}</div>
          <form class="cmt-form"><input class="input" maxlength="1000" placeholder="Write a reply…" required><button class="btn sm" type="submit">Reply</button></form>`;
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
              await load(true);  // refresh reply counts + thread affordance (also re-collapses the thread)
            } catch (err) { alert0(err.message); }
          });
        };
      }
    });
    let lastFeed = '', mineOnly = false;
    const load = async (force) => {
      // Never wipe a reply the user is writing: skip the refresh while a reply box is open
      // or anything in the feed is focused (unless this is the first/explicit render).
      if (!force && (feed.querySelector('.cmt-form') || feed.contains(document.activeElement))) return;
      const d = await api('/api/community' + (mineOnly ? '?mine=1' : ''));
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
      mineOnly = want;
      root.querySelectorAll('.feed-filter .chip').forEach((x) => x.setAttribute('aria-pressed', String((x.dataset.feed === 'mine') === mineOnly)));
      lastFeed = ''; load(true);
    }));
    await load(true);
    poll(load, 20000);
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
  const mktLabel = (m) => { const t = (m.ti || '').trim(), s = (m.su || '').trim(); return s && s !== t ? (t ? `${t} · ${s}` : s) : (t || m.t); };
  const kalshiUrl = (m) => `https://kalshi.com/markets/${encodeURIComponent((m.s || '').toLowerCase())}`;
  const kfmt = (n) => { n = +n || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n)); };
  const sinceMin = (iso) => { if (!iso) return '—'; const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000); return s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + 'm ago' : s < 172800 ? Math.round(s / 3600) + 'h ago' : Math.round(s / 86400) + 'd ago'; };

  function priceChart(points) {
    if (!points || points.length < 2) return '<div class="empty"><h3>Not enough history yet</h3><p>This market is new or thinly traded — its price curve fills in as it trades.</p></div>';
    const W = 760, H = 260, pl = 44, pr = 14, pt = 14, pb = 26, iw = W - pl - pr, ih = H - pt - pb;
    const ts = points.map((p) => p.t), t0 = Math.min(...ts), t1 = Math.max(...ts), tr = (t1 - t0) || 1;
    const x = (t) => pl + (t - t0) / tr * iw, y = (v) => pt + (1 - v) * ih;
    const grid = [0, .25, .5, .75, 1].map((v) => `<line x1="${pl}" y1="${y(v).toFixed(1)}" x2="${W - pr}" y2="${y(v).toFixed(1)}" class="pc-grid"/><text x="${pl - 8}" y="${(y(v) + 3).toFixed(1)}" class="pc-ylab">${Math.round(v * 100)}¢</text>`).join('');
    const line = points.map((p) => `${x(p.t).toFixed(1)},${y(p.yes).toFixed(1)}`).join(' ');
    const fmt = (t) => { const d = new Date(t * 1000); return `${d.getMonth() + 1}/${d.getDate()}`; };
    return `<svg class="pchart" viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Yes price history">${grid}<polyline points="${line}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><text x="${pl}" y="${H - 6}" class="pc-xlab">${fmt(t0)}</text><text x="${W - pr}" y="${H - 6}" class="pc-xlab" text-anchor="end">${fmt(t1)}</text></svg>`;
  }
  async function viewMarketDetail(ticker) {
    shell('/explore', boardTitle('Market'), loading(300));
    let d;
    try { d = await api('/api/explore/market?ticker=' + encodeURIComponent(ticker)); }
    catch (e) { root.querySelector('main').innerHTML = notice(e.message, 'bad') + `<p style="margin-top:12px"><a class="btn sm" href="/explore">← Back to Explore</a></p>`; return; }
    const mid = midOf({ bid: d.yes_bid, ask: d.yes_ask, last: d.last });
    const label = mktLabel({ ti: d.title, su: d.sub, t: d.ticker });
    const closes = d.close_time ? new Date(d.close_time).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—';
    const gran = d.period_min >= 1440 ? 'daily' : d.period_min >= 60 ? 'hourly' : 'per-minute';
    const fmtT = (t) => new Date(t * 1000).toLocaleString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    shell('/explore', boardTitle(label, `${d.series} · ${d.status || 'market'} · ${d.ticker}`) +
      '<dl class="figures measure" style="margin-top:14px">' +
        fig('Yes price', mid == null ? '—' : cents(mid)) + fig('24h volume', num(Math.round(+d.volume_24h || 0))) +
        fig('Open interest', num(Math.round(+d.open_interest || 0))) + fig('Closes', closes) + '</dl>', `
      <section class="sect"><div class="sect-head"><h2>Price history</h2><p>Yes price · Kalshi ${gran} candles</p></div>
        <div class="pchart-wrap">${priceChart(d.points)}</div></section>
      <section class="sect"><div class="sect-head"><h2>Raw data</h2><p>${num(d.points.length)} ${gran} points${d.points.length ? ' · newest first' : ''}</p></div>
        <div id="rawsect"></div></section>
      <div class="xpage"><a class="btn sm" href="/explore">← Back to Explore</a>
        <span><button class="btn sm" id="dl-csv" ${d.points.length ? '' : 'disabled'}>Download CSV</button>
        <a class="btn sm" href="https://kalshi.com/markets/${encodeURIComponent((d.series || '').toLowerCase())}" target="_blank" rel="noopener" style="margin-left:8px">View on Kalshi ↗</a></span></div>`);
    const pts = d.points.slice().reverse();  // newest first
    const PER = 100; let pg = 0;
    const rawEl = root.querySelector('#rawsect');
    const renderRaw = () => {
      if (!pts.length) { rawEl.innerHTML = '<div class="empty"><p>No candles recorded for this market yet.</p></div>'; return; }
      const pages = Math.max(1, Math.ceil(pts.length / PER));
      const rows = pts.slice(pg * PER, (pg + 1) * PER).map((p) => `<tr><td class="tick">${fmtT(p.t)}</td><td class="num">${cents(p.yes)}</td><td class="num">${num(Math.round(p.vol || 0))}</td></tr>`).join('');
      rawEl.innerHTML = `<div class="sheet"><table><thead><tr><th>Time (UTC)</th><th class="num">Yes price</th><th class="num">Volume</th></tr></thead><tbody>${rows}</tbody></table></div>
        <div class="xpage">${pg > 0 ? `<button class="btn sm" data-rp="${pg - 1}">← Prev</button>` : '<span></span>'}<span class="lab">Page ${pg + 1} of ${num(pages)} · ${num(pts.length)} points</span>${pg + 1 < pages ? `<button class="btn sm" data-rp="${pg + 1}">Next →</button>` : '<span></span>'}</div>`;
      rawEl.querySelectorAll('[data-rp]').forEach((b) => b.onclick = () => { pg = +b.dataset.rp; renderRaw(); window.scrollTo({ top: rawEl.offsetTop - 80, behavior: 'smooth' }); });
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
      const d = await api('/api/explore?' + new URLSearchParams({ q: f.q, sort: f.sort, page: String(f.page) }));
      figs.innerHTML = fig('Markets tracked', num(d.total)) + fig('Live now', num(d.shown)) + fig('Matching', num(d.matched)) + fig('Updated', sinceMin(d.at));
      if (!d.markets.length) { body.innerHTML = `<div class="empty"><h3>No markets match “${esc(f.q)}”</h3><p>Try a broader search, or clear it to see the hottest markets.</p></div>`; return; }
      const rows = d.markets.map((m) => {
        const mid = midOf(m);
        return `<tr><td class="name"><a href="/explore?m=${encodeURIComponent(m.t)}">${esc(mktLabel(m))}</a>${m.s ? ` <span class="mk quiet">${esc(m.s)}</span>` : ''}</td>
          <td class="num">${mid == null ? '—' : cents(mid)}</td><td class="num">${num(Math.round(+m.v24 || 0))}</td><td class="num">${num(Math.round(+m.oi || 0))}</td>
          <td class="num xlink"><a href="${kalshiUrl(m)}" target="_blank" rel="noopener" aria-label="Open on Kalshi">${ICON.ext}</a></td></tr>`;
      }).join('');
      const pages = Math.max(1, Math.ceil(d.matched / d.per));
      body.innerHTML = `<div class="sheet"><table><thead><tr><th>Market</th><th class="num">Yes price</th><th class="num">24h volume</th><th class="num">Open int.</th><th class="num" aria-label="Link"></th></tr></thead><tbody>${rows}</tbody></table></div>
        ${pages > 1 ? `<div class="xpage">${f.page > 0 ? `<button class="btn sm" data-pg="${f.page - 1}">${ICON.up ? '' : ''}← Prev</button>` : '<span></span>'}<span class="lab">Page ${f.page + 1} of ${num(pages)}</span>${f.page + 1 < pages ? `<button class="btn sm" data-pg="${f.page + 1}">Next →</button>` : '<span></span>'}</div>` : ''}`;
      body.querySelectorAll('[data-pg]').forEach((b) => b.onclick = () => { f.page = +b.dataset.pg; sync(); window.scrollTo({ top: 0, behavior: 'smooth' }); load(); });
    };
    let t; root.querySelector('#xq').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); f.page = 0; sync(); load(); }, 220); });
    root.querySelectorAll('[data-sort]').forEach((b) => b.onclick = () => { f.sort = b.dataset.sort; f.page = 0; root.querySelectorAll('[data-sort]').forEach((o) => o.setAttribute('aria-pressed', o === b)); sync(); load(); });
    await load();
  }

  // Hot Markets left rail: persistent (open/closed survives page switches), refreshes each minute.
  const hotOpen = () => localStorage.getItem('tau_hotrail') !== '0';
  let hotLoop = false;
  let apLoop = false;

  // ---------- floating autopilot window ----------
  const apExpanded = () => localStorage.getItem('tau_ap_open') === '1';
  function mountAutopilot() {
    if (!S.me || !S.me.user) return;
    let box = document.getElementById('autopilot-float');
    if (!box) { box = document.createElement('div'); box.id = 'autopilot-float'; box.className = 'apf'; document.body.appendChild(box); }
    renderAutopilot(box, S.ap);
    const stale = !S.ap || !S.apAt || Date.now() - S.apAt > 18000;
    if (stale) refreshAutopilot(box);
    if (!apLoop) { apLoop = true; setInterval(() => { const b = document.getElementById('autopilot-float'); if (b) refreshAutopilot(b); }, 20000); }
  }
  async function refreshAutopilot(box) {
    try { S.ap = await api('/api/autopilot/status'); S.apAt = Date.now(); renderAutopilot(box, S.ap); }
    catch (e) { /* floating window is best-effort; never block the app */ }
  }
  const AP_MODE = {
    off: { label: 'Autopilot off', cls: '' },
    paper: { label: 'Autopilot · paper', cls: 'paper' },
    'live-armed': { label: 'Autopilot · live armed', cls: 'live' },
    live: { label: 'Autopilot · LIVE', cls: 'live' },
  };
  // The float is the single home for autopilot: the on/off toggle, live controls, and the agent
  // chat. The expanded shell is built ONCE; the 20s status poll updates only dynamic bits so it
  // never wipes the chat/composer. apChatTimer polls chat (3s) only while expanded.
  let apChatLastId = 0, apChatTimer = null, apFeedFirst = true;
  function apStopChat() { if (apChatTimer) { clearInterval(apChatTimer); apChatTimer = null; } }
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
  // One feed entry, rendered with the SAME research-session parts (.ln timeline rail, .say card,
  // feedMd markdown, lane tint) so the autopilot reads as one family with the research log —
  // a legible end-to-end session, not a cramped chat. m.content is Markdown; m.stage/m.strategy/
  // m.detail are OPTIONAL structured fields the backend can add later (see the note in PLAN.md).
  function apFeedLi(m) {
    const li = document.createElement('li');
    const t = `<time>${clock(m.created_at)}</time><span class="node" aria-hidden="true"></span>`;
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
    const kind = AP_ACT[m.proposal_kind] || 'Reviewed';
    const st = m.proposal_status;
    const lane = !m.proposal_id ? 'state' : st === 'pending' ? 'review' : st === 'applied' ? 'action' : 'void';
    const stamp = st === 'applied' ? `<span class="hx-stamp pass">${m.proposal_kind === 'alpaca_paper' ? 'Approved' : 'Applied'}</span>`
      : st === 'declined' || st === 'rejected' ? '<span class="hx-stamp rej">Declined</span>' : '';
    const stage = m.stage ? `<span class="hx-tag">${esc(m.stage)}</span>` : '';
    const title = m.strategy ? `<b class="say-title">${esc(m.strategy)}</b>` : '';
    const detail = m.detail ? `<details class="hx-more"><summary>Show the detail</summary><div class="hx-body"><div class="apf-md">${feedMd(m.detail)}</div></div></details>` : '';
    const ctl = (m.proposal_id && st === 'pending')
      ? `<div class="proposal" data-prop="${m.proposal_id}"><button class="btn small" data-decide="approve">${m.proposal_kind === 'kalshi_perps_live' ? 'Review live order' : 'Approve'}</button><button class="btn ghost small" data-decide="reject">Decline</button></div>` : '';
    li.className = 'ln lane-' + lane + ' apf-act';
    li.innerHTML = `${t}<div class="say">
      <div class="hx-head"><span class="say-kind">${esc(kind)}</span>${title}${stage}${stamp}</div>
      <div class="apf-md">${feedMd(m.content)}</div>${detail}${ctl}</div>`;
    return li;
  }
  async function apLoadChat(box, full) {
    const msgs = box.querySelector('#apf-messages'); if (!msgs) return;
    let d; try { d = await api('/api/chat?after=' + (full ? 0 : apChatLastId)); } catch (e) { return; }
    const stick = full || msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 70;
    if (full) { msgs.innerHTML = ''; apChatLastId = 0; apFeedFirst = true; }
    const empty = msgs.querySelector('.ap-empty'); if (empty && d.messages.length) empty.remove();
    msgs.querySelectorAll('.apf-typing').forEach((n) => n.remove());
    d.messages.forEach((m) => {
      apChatLastId = Math.max(apChatLastId, m.id);
      const li = apFeedLi(m);
      if (!apFeedFirst) li.classList.add('in');   // backlog lands silently; new moves rise in
      msgs.appendChild(li);
    });
    if (d.messages.length) apFeedFirst = false;
    if (!msgs.children.length) msgs.innerHTML = '<li class="ap-empty">No autopilot activity yet. On its own schedule it reviews every deployment and open position, then works the whole pipeline end to end — researching angles, clearing strategies through the gates, promoting to paper or live, and tuning risk, execution and model params. Each move lands here as it happens. Message it below to steer.</li>';
    // The live pulse — the research session's "working" signal, scoped to the operation.
    const pulse = box.querySelector('#apf-pulse');
    if (pulse) {
      pulse.hidden = false;
      pulse.className = 'runpulse apf-pulse-row';
      pulse.innerHTML = d.agent_busy
        ? '<span class="working" aria-hidden="true"></span><span>Working the operation<span class="ell" aria-hidden="true"></span></span>'
        : `<span class="apf-idle-dot" aria-hidden="true"></span><span>${apIdleLine(box)}</span>`;
    }
    if (stick) msgs.scrollTop = msgs.scrollHeight;
  }
  // Idle pulse copy: lead with the autopilot's most recent move (from the status poll, always
  // available even if chat is slow), else a plain "on a schedule" line.
  function apIdleLine(box) {
    const la = S.ap && S.ap.last_action;
    if (la && la.at) return 'Idle · last move ' + sinceMin(la.at) + ' — reviews run on a schedule';
    return 'Idle — reviews run automatically on a schedule';
  }
  function renderAutopilot(box, d) {
    if (!apExpanded()) {
      apStopChat();
      const m = (d && AP_MODE[d.mode]) || AP_MODE.off;
      box.className = 'apf' + (m.cls ? ' ' + m.cls : '');
      box.dataset.shell = '';
      box.innerHTML = `<button type="button" class="apf-pill" data-ap="toggle" aria-expanded="false">
        <span class="apf-dot" aria-hidden="true"></span><span class="apf-pill-label">${esc(m.label)}</span>${ICON.chev || ''}</button>`;
      box.querySelector('[data-ap]').onclick = (e) => apAction(box, 'toggle', e);
      return;
    }
    if (box.dataset.shell !== 'expanded') apBuildShell(box);
    apUpdate(box, d);
  }
  function apBuildShell(box) {
    box.dataset.shell = 'expanded';
    box.innerHTML = `
      <div class="apf-head"><span class="apf-dot" aria-hidden="true"></span><b id="apf-label"></b>
        <button type="button" class="apf-x" data-ap="toggle" aria-label="Collapse">${ICON.cross || '×'}</button></div>
      <div class="apf-top">
        <div class="autopilot" id="apf-ap">
          <span id="apf-ap-copy"></span>
          <label class="switch"><span class="vh">Autopilot</span><input type="checkbox" id="apf-apswitch"></label>
        </div>
        <dl class="apf-stats" id="apf-stats"></dl>
        <label class="field apf-model"><span>Autopilot model</span>
          <select class="input" id="apf-model" aria-label="Autopilot model"></select></label>
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
        <div class="apf-session-head"><span class="say-kind">Live session</span><span class="apf-session-sub">everything the autopilot does, end to end</span></div>
        <ol class="log stream apf-log" id="apf-messages" role="log" aria-label="Autopilot activity" aria-live="polite"></ol>
        <div class="runpulse apf-pulse-row" id="apf-pulse" aria-live="polite" hidden></div>
      </div>
      <form class="composer apf-composer-row" id="apf-composer">
        <label class="vh" for="apf-msg">Message the agent</label>
        <textarea class="input" id="apf-msg" rows="1" maxlength="2000" placeholder="Tell the autopilot what to focus on…"></textarea>
        <button class="btn" type="submit" aria-label="Send">${ICON.send}</button>
      </form>`;
    box.querySelector('.apf-x').onclick = (e) => apAction(box, 'toggle', e);
    box.querySelector('#apf-confirm').onsubmit = (e) => { e.preventDefault(); apEnableLive(box, box.querySelector('#apf-confirm').confirm.value.trim()); };
    const sw = box.querySelector('#apf-apswitch');
    sw.onchange = async () => {
      const on = sw.checked;
      if (on && !confirmAutopilot.armed) { sw.checked = false; confirmAutopilot.armed = true; box.querySelector('#apf-ap-copy').innerHTML = '<b>Turn on autopilot?</b>Flip again to confirm. The agent will act on paper strategies without asking you first.'; setTimeout(() => (confirmAutopilot.armed = false), 6000); return; }
      confirmAutopilot.armed = false;
      try { await api('/api/settings', { autopilot: on }); S.me.user.autopilot = on; } catch (e) { sw.checked = !on; alert0(e.message); return; }
      refreshAutopilot(box);
    };
    const msgs = box.querySelector('#apf-messages');
    msgs.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-decide]'); if (!b) return;
      const pid = b.closest('[data-prop]').dataset.prop;
      await busy(b, async () => { try { const result = await api(`/api/proposals/${pid}/${b.dataset.decide}`, {}); if (result.review_required && result.review_url === `/funds?perps_proposal=${pid}`) { go(result.review_url); return; } await apLoadChat(box, true); } catch (err) { alert0(err.message); } });
    });
    const cf = box.querySelector('#apf-composer'), ta = box.querySelector('#apf-msg');
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px'; });
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); cf.requestSubmit(); } });
    cf.onsubmit = async (e) => {
      e.preventDefault(); const content = ta.value.trim(); if (!content) return;
      await busy(cf.querySelector('button'), async () => { try { await api('/api/chat', { content }); ta.value = ''; ta.style.height = ''; await apLoadChat(box); } catch (err) { alert0(err.message); } });
    };
    apLoadChat(box, true);
    apStopChat();
    apChatTimer = setInterval(() => { const b = document.getElementById('autopilot-float'); if (b && apExpanded()) apLoadChat(b); else apStopChat(); }, 3000);
    // The autopilot's research, review and chat share its saved model preference.
    (async () => {
      const sel = box.querySelector('#apf-model'); if (!sel) return;
      const current = () => box.isConnected !== false && box.querySelector('#apf-model') === sel;
      const mdl = await api('/api/models').catch(() => ({ models: [], default: '' }));
      if (!current()) return;
      const cur = (S.ap && S.ap.model) || mdl.default;
      sel.innerHTML = (mdl.models || []).map((m) => `<option value="${esc(m.key)}"${m.key === cur ? ' selected' : ''}>${esc(m.label)}</option>`).join('');
      sel.onchange = async () => {
        if (!current() || sel.disabled) return;
        sel.disabled = true;
        try { const r = await api('/api/autopilot/model', { model: sel.value }); if (current() && S.ap) S.ap.model = r.model; }
        catch (e) { if (current()) { sel.value = (S.ap && S.ap.model) || cur; alert0(e.message); } }
        finally { if (current()) sel.disabled = false; }
      };
    })();
  }
  function apUpdate(box, d) {
    const m = (d && AP_MODE[d.mode]) || AP_MODE.off;
    box.className = 'apf open' + (m.cls ? ' ' + m.cls : '');
    const label = box.querySelector('#apf-label'); if (label) label.textContent = m.label;
    const on = d ? d.autopilot : (S.me.user && S.me.user.autopilot);
    const ap = box.querySelector('#apf-ap'); if (ap) ap.classList.toggle('on', !!on);
    const sw = box.querySelector('#apf-apswitch'); if (sw && document.activeElement !== sw) sw.checked = !!on;
    const copy = box.querySelector('#apf-ap-copy');
    if (copy && !confirmAutopilot.armed) copy.innerHTML = on
      ? '<b>Autopilot</b>Researches, deploys and tunes paper strategies on its own, and adjusts your risk &amp; execution controls within safe bounds. It never touches live money without the step below.'
      : '<b>Autopilot</b>Off — the agent only proposes (research, deploys, risk/execution/parameter changes); you approve each one.';
    if (!d) return;
    const pnl = d.today_live_pnl || 0;
    const stats = box.querySelector('#apf-stats');
    // Count running strategies across every mode, not just paper — a lone demo strategy
    // used to read as "0 paper", which looked like nothing was running. Match the dashboard.
    const runParts = [
      d.live_running ? `<span class="apf-live">${d.live_running} live</span>` : '',
      d.demo_running ? `${d.demo_running} demo` : '',
      d.paper_running ? `${d.paper_running} paper` : '',
    ].filter(Boolean);
    const runTotal = (d.live_running || 0) + (d.demo_running || 0) + (d.paper_running || 0);
    if (stats) stats.innerHTML = `
      <div><dt>Running</dt><dd>${runTotal ? runParts.join(' · ') : 'None'}</dd></div>
      <div><dt>Live P&amp;L today</dt><dd class="${pnl < 0 ? 'neg' : (pnl > 0 ? 'pos' : '')}">${usd(pnl, true)}</dd></div>
      <div><dt>Loss budget left</dt><dd>${usd(d.loss_headroom)} / ${usd(d.daily_loss_limit)}</dd></div>
      ${d.research ? `<div><dt>Research</dt><dd>${d.research.active.length ? esc(d.research.active.join(' · ')) : 'Idle'} · ${d.research.tested_7d} ideas tested, ${d.research.passed_7d} passed this week</dd></div>` : ''}
      ${d.paper_progress ? `<div><dt>Closest to live</dt><dd><a href="/strategies/${d.paper_progress.strategy_id}">${esc(d.paper_progress.title || 'Paper strategy')}</a> · ${d.paper_progress.trades}/${d.paper_progress.trades_needed} paper trades · ${usd(d.paper_progress.net_pnl, true)}</dd></div>` : ''}
      ${d.last_review_at ? `<div><dt>Last reviewed</dt><dd>${sinceMin(d.last_review_at)}</dd></div>` : ''}`;
    const msel = box.querySelector('#apf-model'); if (msel && msel.options.length && d.model && document.activeElement !== msel && !msel.disabled) msel.value = d.model;
    const gates = box.querySelector('#apf-gates');
    if (gates) {
      if (d.billing_blocked) {
        // Autopilot is on but can't spend — tell the user WHY it's quiet (so it doesn't look broken).
        gates.innerHTML = d.billing_reason === 'card'
          ? 'Autopilot is paused — <a href="/billing">add a payment method</a> to let it run.'
          : 'Autopilot is paused — <a href="/billing">add credits</a> to let it keep researching.';
        gates.classList.add('warn');
      } else {
        gates.textContent = apLiveBlock(d);
        gates.classList.remove('warn');
      }
    }
    const controls = box.querySelector('#apf-controls');
    if (controls) {
      controls.innerHTML = `${d.autopilot_live
        ? `<button class="btn sm" data-ap="livetoggle" data-on="0">Turn off live</button>`
        : `<button class="btn sm" data-ap="livearm" ${(d.live_enabled && d.kalshi_connected && d.autopilot) ? '' : 'aria-disabled="true"'}>Enable live autopilot</button>`}
        <button class="btn sm danger" data-ap="kill">Kill</button>
        <a class="btn sm ghost" href="/deploy">Open board</a>`;
      controls.querySelectorAll('[data-ap]').forEach((b) => (b.onclick = (e) => apAction(box, b.dataset.ap, e)));
    }
  }
  // Why live autopilot can't be enabled yet (ordered), or '' when all gates pass.
  function apLiveBlock(d) {
    if (!d) return '';
    if (!d.autopilot) return 'Turn on autopilot first — live autopilot builds on it. ';
    if (!d.live_enabled) return 'Live trading is off on this server. ';
    if (!d.kalshi_connected) return 'Connect your Kalshi key on the Funds page first. ';
    return '';
  }
  function apFlash(box, msg, kind) { const f = box.querySelector('#apf-flash'); if (f) f.innerHTML = `<p class="${kind === 'bad' ? 'error-text' : 'hint'}">${esc(msg)}</p>`; }
  async function apAction(box, action, e) {
    if (action === 'toggle') { localStorage.setItem('tau_ap_open', apExpanded() ? '0' : '1'); renderAutopilot(box, S.ap); return; }
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
      if (e && e.target && e.target.dataset.armed !== '1') { e.target.dataset.armed = '1'; e.target.textContent = 'Confirm kill'; setTimeout(() => { if (e.target) { e.target.dataset.armed = ''; e.target.textContent = 'Kill'; } }, 4000); return; }
      try { const r = await api('/api/autopilot/kill', {}); apFlash(box, `Killed — ${r.paused} live deployment(s) paused.`); } catch (err) { return apFlash(box, err.message, 'bad'); }
      refreshAutopilot(box);
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
      <span class="hot-foot"><span class="mk quiet">${esc(m.s || '')}</span><span class="hot-vol">${kfmt(m.v24)} vol · 24h</span>${ICON.ext}</span></a>`;
  }
  function renderHotRail() {
    const rail = document.getElementById('hotrail'); if (!rail) return;
    const open = hotOpen();
    const d = S.hot;
    const rows = d && d.markets && d.markets.length ? d.markets.map(hotRowHtml).join('')
      : `<div class="hot-empty">${d ? 'Warming up — the live book fills in a minute.' : loading(120)}</div>`;
    rail.innerHTML = `<button class="hot-tab" data-hot="toggle" aria-expanded="${open}" aria-label="${open ? 'Collapse hot markets' : 'Expand hot markets'}"><span class="hot-tab-label">Hot markets</span><span class="hot-chev">${open ? '‹' : '›'}</span></button>
      <div class="hot-panel">
        <div class="hot-head"><div><span class="hot-kicker">Hot markets</span><span class="hot-now"><span class="hot-dot"></span>Right now</span></div><button class="hot-x" data-hot="toggle" aria-label="Collapse">‹</button></div>
        <div class="hot-list">${rows}</div>
        <div class="hot-ft">${d && d.at ? 'Updated ' + sinceMin(d.at) : ''} · <a href="/explore">See all markets →</a></div>
      </div>`;
    rail.querySelectorAll('[data-hot="toggle"]').forEach((b) => b.onclick = (e) => {
      if (e.currentTarget.classList.contains('hot-tab') && open) return; // the spine only expands
      const next = !hotOpen(); localStorage.setItem('tau_hotrail', next ? '1' : '0');
      document.body.classList.toggle('hot-open', next); renderHotRail();
    });
    rail.querySelector('.hot-ft a') && (rail.querySelector('.hot-ft a').onclick = (e) => { e.preventDefault(); go('/explore'); });
  }
  async function refreshHot() {
    try { S.hot = await api('/api/explore/hot'); renderHotRail(); } catch (e) {}
  }
  function mountHotRail() {
    if (!S.me || !S.me.user) return;
    document.body.classList.toggle('hot-open', hotOpen());
    if (!document.getElementById('hotrail')) { const a = document.createElement('aside'); a.className = 'hotrail'; a.id = 'hotrail'; document.body.appendChild(a); }
    renderHotRail();
    const stale = !S.hot || !S.hotAt || Date.now() - S.hotAt > 55000;
    if (stale) refreshHot().then(() => { S.hotAt = Date.now(); });
    if (!hotLoop) { hotLoop = true; setInterval(() => { if (document.getElementById('hotrail')) refreshHot().then(() => { S.hotAt = Date.now(); }); }, 60000); }
  }

  const KIND_LABEL = { bonus: 'Welcome credits', topup: 'Added credits', autoreload: 'Auto-reload', usage: 'Agent usage', admin_grant: 'Admin grant' };
  async function viewBilling() {
    shell('/billing', boardTitle('Billing', 'Credits pay for agent research and chat, billed per token at model list price. Paper and live trading themselves are free.') +
      '<dl class="figures measure" id="bfigs" style="margin-top:14px"></dl>', loading(360));
    let stripe = null, card = null;
    const load = async () => {
      const d = await api('/api/billing');
      root.querySelector('#bfigs').innerHTML =
        fig('Credit balance', usd(d.balance), { v: d.balance > 0 ? 1 : (d.balance < 0 ? -1 : 0) }) +
        fig('Spent on usage', usd(d.spent), { small: 'at model list price' }) +
        fig('Welcome credit', usd(d.free_bonus), { small: 'one-time, free' });
      const feeNote = `Credits plus a ${d.topup_fee_pct}% purchase fee.`;
      const cardLines = d.cards.length
        ? `<table class="table stack t-dep"><thead><tr><th>Card</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody>${d.cards.map((c) => `<tr>
            <td class="name" data-lab="Card">${esc((c.brand || 'card').toUpperCase())} •••• ${esc(c.last4 || '')}</td>
            <td data-lab="Expires">${String(c.exp_month).padStart(2, '0')}/${c.exp_year}</td>
            <td data-lab="Status">${c.id === d.default_pm ? '<span class="mk on">Default</span>' : '<span class="mk quiet">Backup</span>'}</td>
            <td class="act" data-lab="">${d.cards.length > 1 ? `<button class="btn sm danger" data-remove="${c.id}">Remove</button>` : '<span class="hint">Only card</span>'}</td></tr>`).join('')}</tbody></table>`
        : '<p class="hint">No card on file. Add one to buy credits or turn on auto-reload.</p>';
      const main = !d.configured
        ? `<div class="notice">${ICON.warn}<span>Payments aren’t enabled on this server yet. You can still use your free credits.</span></div>
           <section class="sect"><div class="sect-head"><h2>Credits &amp; usage</h2><a class="btn sm" href="/api/billing/receipt" download>Download receipt</a></div>${ledgerTable(d.ledger)}</section>`
        : `<div class="detail">
            <div>
              <section class="panel"><h3>Payment method</h3><div id="cards">${cardLines}</div>
                <div id="card-add" style="margin-top:14px">
                  <div class="field"><span>${d.cards.length ? 'Add another card' : 'Add a card'}</span><div id="card-el" class="card-el"></div></div>
                  <div id="card-flash"></div>
                  <button class="btn" id="save-card" style="margin-top:10px">Save card</button>
                </div>
                <div class="autorel-row">
                  <label class="switch"><input type="checkbox" id="autoreload" ${d.auto_reload ? 'checked' : ''}><span>Auto-reload</span></label>
                  <button type="button" class="autorel-edit" id="autorel-edit" aria-expanded="false" aria-controls="autorel-config"><span id="autorel-sum">Reload $${d.autoreload_amount} at $${d.autoreload_threshold}</span><span class="chev">${ICON.chev}</span></button>
                </div>
                <div class="autorel-config" id="autorel-config" hidden>
                  <p class="autorel-line">Reload <input class="input xs" id="reload-amt" type="number" min="${d.min_reload_amount}" step="1" value="${d.autoreload_amount}"> dollars when my balance drops to <input class="input xs" id="reload-thr" type="number" min="${d.min_reload_threshold}" step="1" value="${d.autoreload_threshold}"> dollars.</p>
                  <p class="hint" id="autorel-flash" style="margin-top:4px">Minimum $${d.min_reload_amount} reload, $${d.min_reload_threshold} trigger.</p>
                </div>
              </section>
              <section class="sect"><div class="sect-head"><h2>Credits &amp; usage</h2><a class="btn sm" href="/api/billing/receipt" download>Download receipt</a></div>${ledgerTable(d.ledger)}</section>
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
      const fee = d.topup_fee_pct / 100;
      const upd = () => { const v = +amt.value || 0; note.textContent = `You'll pay ${usd(v * (1 + fee))} (${usd(v)} credits + ${d.topup_fee_pct}% fee).`; };
      amt.oninput = upd; upd();
      root.querySelector('#topup-btn').onclick = (e) => {
        if (e.currentTarget.getAttribute('aria-disabled')) { flash('#topup-flash', 'Add a card first.', 'bad'); return; }
        busy(e.currentTarget, async () => {
          const credits = +amt.value;
          try {
            const r = await api('/api/billing/topup', { amount: credits });
            await load();  // refresh balance + ledger, then confirm into the fresh panel
            flash('#topup-flash', `Added ${usd(credits)} in credits. You paid ${usd(credits * (1 + fee))} — ${usd(credits)} plus the ${d.topup_fee_pct}% fee. New balance is ${usd(r.balance)}.`, 'good');
          } catch (err) { flash('#topup-flash', err.message, 'bad'); }
        });
      };
      const arBox = root.querySelector('#autoreload'), arAmt = root.querySelector('#reload-amt'), arThr = root.querySelector('#reload-thr');
      const arEdit = root.querySelector('#autorel-edit'), arCfg = root.querySelector('#autorel-config'), arSum = root.querySelector('#autorel-sum');
      arEdit.onclick = () => { const open = arCfg.hidden; arCfg.hidden = !open; arEdit.setAttribute('aria-expanded', String(open)); };
      const saveAutoReload = async () => {
        const amount = Math.max(d.min_reload_amount, +arAmt.value || d.min_reload_amount);
        const threshold = Math.max(d.min_reload_threshold, +arThr.value || d.min_reload_threshold);
        arAmt.value = amount; arThr.value = threshold;
        arSum.textContent = `Reload $${amount} at $${threshold}`;
        try {
          await api('/api/billing/auto-reload', { on: arBox.checked, amount, threshold });
          flash('#autorel-flash', arBox.checked ? `On · reloads ${usd(amount)} at ${usd(threshold)}.` : 'Auto-reload off.', 'good');
        } catch (err) { arBox.checked = !arBox.checked; flash('#autorel-flash', err.message, 'bad'); }
      };
      arBox.onchange = saveAutoReload;
      arAmt.onchange = arThr.onchange = () => { if (arBox.checked) saveAutoReload(); };
      root.querySelectorAll('[data-remove]').forEach((b) => (b.onclick = () => armed(b, 'Confirm remove', () => busy(b, async () => {
        try { await api('/api/billing/remove-card', { payment_method_id: b.dataset.remove }); await load(); } catch (err) { alert0(err.message); }
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
        root.querySelector('#save-card').onclick = (e) => busy(e.currentTarget, async () => {
          flash('#card-flash', '', '');
          let r;
          try { r = await sp.confirmSetup({ elements, redirect: 'if_required', confirmParams: { return_url: location.origin + '/billing', payment_method_data: { billing_details: { address: { country: 'US' } } } } }); }
          catch (err) { flash('#card-flash', err.message || 'Could not save the card.', 'bad'); return; }
          if (r.error) { flash('#card-flash', r.error.message, 'bad'); return; }
          try { await api('/api/billing/card-added', { payment_method_id: r.setupIntent.payment_method }); }
          catch (err) { flash('#card-flash', err.message, 'bad'); return; }
          flash('#card-flash', 'Card saved.', 'good'); await load();
        });
      } catch (err) { flash('#card-flash', err.message, 'bad'); }
    };
    await load();
  }
  function ledgerTable(rows) {
    if (!rows.length) return '<p class="hint">No credit activity yet.</p>';
    return `<div class="sheet"><table class="table stack t-dep"><thead><tr><th>When</th><th>Item</th><th class="num">Amount</th></tr></thead><tbody>${rows.map((r) => `<tr>
      <td class="hint" data-lab="When">${when(r.created_at)}</td>
      <td class="name" data-lab="Item">${esc(KIND_LABEL[r.kind] || r.kind)}${r.memo && r.kind === 'usage' ? `<div class="sub-fig">${esc(r.memo)}</div>` : ''}</td>
      <td class="num" data-lab="Amount"><span class="${r.amount >= 0 ? 'gain' : ''}">${usd(r.amount, true)}</span></td></tr>`).join('')}</tbody></table></div>`;
  }

  // ---------- admin ----------
  async function viewAdmin() {
    if (!adminViewOn()) return go('/', true);
    shell('/admin', boardTitle('Admin', 'Operator tools: grant credits and see who has signed up.'), `
      <div class="detail">
        <div>
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
        </aside>
      </div>`);
    const load = async () => {
      const d = await api('/api/admin');
      root.querySelector('#ucount').textContent = `${d.users.length} shown`;
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
      await busy(btn, async () => {
        try {
          const k = await api('/api/admin/kill-switch', { on: !btn.dataset.on, reason: root.querySelector('#k-reason').value.trim() });
          killShow(k);
        } catch (err) { flash('#k-flash', err.message, 'bad'); }
      });
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
    { id: 'bedrock', x: 40, y: 330, w: 150, label: 'Claude · Bedrock', sub: 'the research agent', ext: 1 },
    { id: 'stripe', x: 40, y: 460, w: 150, label: 'Stripe', sub: 'cards + credits', ext: 1 },
    { id: 'forward', x: 250, y: 30, w: 158, label: 'Forward collector', sub: 'Kalshi book → DB' },
    { id: 'cb_coll', x: 250, y: 150, w: 158, label: 'Coinbase collector', sub: '1-minute candles' },
    { id: 'features', x: 250, y: 270, w: 158, label: 'Feature builder', sub: 'per-minute features' },
    { id: 'web', x: 250, y: 455, w: 158, label: 'Web server', sub: 'app.server · SPA + API' },
    { id: 'db', x: 490, y: 205, w: 150, label: 'Database', sub: 'RDS MySQL', big: 1 },
    { id: 'agents', x: 720, y: 40, w: 158, label: 'Research agents', sub: 'app.worker · hypotheses' },
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
    backtest: 'app/backtest.py — runs each hypothesis on data it never saw and applies the deployment gates. Same spec the engines run.',
    sim_engine: 'app/worker.py (engine) on paper money — prices from the live book, books fills, tracks P&L without real orders.',
    live_engine: 'live_trading_engine.py — places real orders in a user’s own Kalshi account. Gated off until explicitly authorised.',
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
          `<li><a href="#" data-mod="${esc(m.path)}">${esc(m.name)}</a> <span class="sys-dim">${m.symbols} defs · ${m.lines} lines</span>${m.doc ? `<div class="hint">${esc(m.doc)}</div>` : ''}</li>`).join('')}</ul>`);
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
        `<h3><code>${esc(d.qual)}</code></h3><p class="hint">${esc(modName(mod))} · line ${d.lineno}</p>` +
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
        if (id === 'kalshi' && L.markets) return `${num(L.markets)} markets · ${L.series} series`;
        return 'connected';
      }
      if (id === 'db') return `${L.size_mb >= 1024 ? (L.size_mb / 1024).toFixed(0) + ' GB' : num(L.size_mb) + ' MB'} · ${compact(L.rows)} rows`;
      if (id === 'web') return L.users != null ? `${num(L.users)} users · serving` : 'online · serving';
      if (id === 'agents') return `${L.running} running · ${L.queued} queued · ${num(L.done)} done`;
      if (id === 'backtest') return `${num(L.strategies)} strategies tested`;
      if (L.ext) return 'connected';
      const a = L.age == null ? '—' : L.age < 90 ? `${L.age}s ago` : L.age < 5400 ? `${Math.round(L.age / 60)}m ago` : 'stale';
      if (id === 'forward') return `${num(L.rows)} ${L.unit} · ${a}`;
      if (id === 'cb_coll' || id === 'features') return `${num(L.rows)} ${L.unit} · ${a}`;
      if (id === 'sim_engine') return `${num(L.trades)} fills · ${a}`;
      if (id === 'live_engine') return `${L.deployments} live · ${a}`;
      return a;
    }
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
      feed.innerHTML = d.events.length ? d.events.map((e) => `<li class="${e.kind === 'error' ? 'error' : ''}"><time>${clock(e.created_at)}</time><span>${e.kind === 'verdict' ? esc(e.message.replace(/^(PASSED|VOID|FAILED)\s*[-–]\s*/, '')) : esc(e.message)}</span></li>`).join('') : '<li><span class="hint">Quiet right now.</span></li>';
    };
    await load();
    poll(load, 4000);
  }

  setupGlossary();
  render();
})();
