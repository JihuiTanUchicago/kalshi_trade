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
  const usd = (v, signed = false) => {
    if (v == null || Number.isNaN(+v)) return '—';
    const n = +v;
    const s = '$' + (Math.abs(n) >= 100000 ? fmt0.format(Math.abs(n)) : fmt2.format(Math.abs(n)));
    if (n < 0) return '−' + s;
    return signed && n > 0 ? '+' + s : s;
  };
  const pct = (v, signed = true) => (v == null ? '—' : (v < 0 ? '−' : signed && v > 0 ? '+' : '') + Math.abs(v * 100).toFixed(1) + '%');
  // Kalshi quotes some markets in tenths of a cent: 0.1¢ read as 0¢ and a 99.9¢ bid as 100¢.
  const cents = (v) => (v == null ? '—' : Math.round(v * 1000) / 10 + '¢');
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
  const clock = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const num = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US'));
  // Compact count for tight spaces (system-map node metrics): 1.1M, 352k, 940.
  const compact = (n) => (n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : num(n));
  const age = (sec) => (sec == null ? 'never' : sec < 90 ? sec + 's' : sec < 5400 ? Math.round(sec / 60) + 'm' : sec < 172800 ? Math.round(sec / 3600) + 'h' : Math.round(sec / 86400) + 'd');
  const marketLabel = (k) => ((S.me && S.me.markets.find((m) => m.key === k)) || { label: k }).label;
  // Short, consistent chip labels for every market; unknown keys fall back to the
  // server's full label, never the raw key (keeps the market chips uniform).
  const MKT_SHORT = {
    btc15m: 'BTC 15-min', btc15m_tick: 'BTC 15-min · per second', btc_perp: 'BTC perp', btc_daily: 'BTC 5pm', eth15m: 'ETH 15-min', eth_daily: 'ETH 5pm',
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
    const lead = `<div class="mkt-lead"><label class="mktrow lead" data-key=""><input type="radio" name="market" value="" class="mktrow-r" checked><span class="mktrow-face"><span class="mktrow-name">Agent\u2019s choice</span></span></label></div>`;
    return `<div class="mktpick">
      ${find ? `<div class="mkt-find">${ICON.search}<label class="vh" for="mktfind">Filter markets</label><input class="input" type="search" id="mktfind" placeholder="Filter markets\u2026" autocomplete="off"></div>` : ''}
      ${lead}
      ${cats.map((c, i) => `<details class="mkt-group"><summary class="mkt-group-h"><span class="mkt-chev" aria-hidden="true">${ICON.chev}</span>${esc(c)}<span class="mkt-count">${groups[c].length}</span></summary><div class="mkt-rows">${groups[c].map(mktRow).join('')}</div></details>`).join('')}
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
  // A read started by a page the user has since left never settles, so the old page can't paint
  // over the new one (or arm its poll there). Widgets that outlive a page pass { keep: true }.
  const STALE = () => new Promise(() => {});
  const TRANSIENT = new Set([502, 503, 504]), RETRY_MS = [700, 1800];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function api(path, body, cfg) {
    const gen = S.gen, scoped = body === undefined && !(cfg && cfg.keep);
    const opts = { credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-Recursive'] = '1';
      opts.body = JSON.stringify(body);
    }
    // Optional timeout (a poll passes one so a hung read is aborted and counted as a failure).
    // AbortController fires an abort the fetch rejects on.
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
        throw new ApiError(0, ctl && ctl.signal.aborted ? "Tau is taking too long to respond." : "Can't reach Tau. Check your connection.");
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
    let data = {};
    try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
    if (scoped && gen !== S.gen) return STALE();
    if (res.status === 401 && path !== '/api/me') { S.me = null; go(signinPath(), true); throw new ApiError(401, 'Please sign in.'); }
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
    [/^\/(?:billing|settings\/billing)$/, viewBilling],
    [/^\/admin$/, viewAdmin],
    [/^\/(?:system|settings\/system)$/, viewSystem],
    [/^\/(?:funds|settings\/account)$/, viewFunds],
    [/^\/devlog$/, viewDevLog],
    [/^\/track-record$/, () => go('/#track-record', true)],  // the record moved onto the dashboard
    [/^\/settings(?:\/theme)?$/, viewSettings],
  ];
  const phone = () => !!(window.matchMedia && window.matchMedia('(max-width: 760px)').matches);
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
    if (to) { e.preventDefault(); to.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
    const a = e.target.closest('a[href^="/"]');
    if (!a || a.target || e.metaKey || e.ctrlKey || e.shiftKey || a.hasAttribute('download') || a.dataset.native != null) return;
    e.preventDefault();
    go(a.getAttribute('href'));
  });

  let resizePaperChart = null;
  window.addEventListener('resize', () => { if (resizePaperChart) resizePaperChart(); });
  function clearTimers() { if (S.perps) { S.perps.destroy(); S.perps = null; } resizePaperChart = null; S.timers.forEach(clearInterval); S.timers = []; }
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
    return () => {
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
  }
  async function render() {
    clearTimers();
    const gen = ++S.gen;
    window.scrollTo(0, 0);
    // On a phone the open autopilot panel fills the screen, so moving to a page closes it.
    if (phone()) { try { localStorage.setItem('tau_ap_open', '0'); } catch (e) { /* private mode */ } }
    const path = location.pathname;
    if (path === '/signin') { const f = document.getElementById('autopilot-float'); if (f) f.remove(); }
    const match = routes.map(([re, fn]) => [path.match(re), fn]).find(([m]) => m);
    if (!S.me && path !== '/signin') {
      try { S.me = await api('/api/me'); } catch (e) { if (e.status === 401) S.signedOutAt = Date.now(); return go(signinPath(), true); }
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
        shell('', boardTitle('Something went wrong'), loadFail(e.message));
        root.querySelector('[data-retry]').onclick = () => render();
      }
    }
    if (gen !== S.gen) return;  // the user moved on while this page loaded
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
          <div class="pay-stage-wrap"><div class="pay-stage" id="pay-stage"></div></div>
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
      const state = await api('/api/billing', undefined, { keep: true });
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
          S.me = await api('/api/me', undefined, { keep: true });
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
  let bellReq = null, bellReqAt = 0;
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
    // The shell is often painted twice in a row (instant page switch, then content): one read serves both.
    if (!bellReq || Date.now() - bellReqAt > 2000) { bellReq = api('/api/notifications', undefined, { keep: true }); bellReqAt = Date.now(); }
    try { data = await bellReq; paint(data); } catch (e) { return; }  // bell is best-effort
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
    const nav = items.filter(([href]) => !['/funds', '/devlog', '/system', '/admin'].includes(href)).map(([href, label]) => `<a class="svc-link" href="${href}" ${active === href ? 'aria-current="page"' : ''}>${label}</a>`).join('');
    const adminToggle = isAdmin()
      ? `<button class="admin-toggle" data-action="admintoggle" role="switch" aria-checked="${adminViewOn()}" title="${adminViewOn() ? 'Admin mode on \u2014 click to view as a user' : 'Admin mode off \u2014 click to show admin'}"><span class="admin-track"><span class="admin-knob"></span></span>Admin</button><span class="sep">\u00b7</span>`
      : '';
    // Keep the automation conversation alive when replacing the page shell.
    const autopilot = document.getElementById('autopilot-float');
    if (autopilot) document.body.appendChild(autopilot);
    root.innerHTML = `
      <header class="masthead"><div class="masthead-in">
        <div class="brand-controls"><span class="market-control"></span><p class="wordmark"><a href="/">${ICON.mark}<span>Tau</span></a></p></div>
        <nav class="services" aria-label="Sections"><div class="services-in">${nav}</div></nav>
        <span class="asof">${adminToggle}<span class="bell-wrap"><button class="bell-trig" data-action="bell" aria-haspopup="true" aria-expanded="false" aria-label="Notifications"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg><span class="bell-dot" hidden></span></button><span class="bell-menu" hidden><div class="bell-head"><b>Notifications</b></div><div class="bell-list" id="bell-list"></div></span></span><span class="profile"><button class="profile-trig" data-action="profile" aria-haspopup="true" aria-expanded="false"><span class="profile-name" title="${esc(u.name || u.email)}">${esc(u.name || u.email)}</span><svg class="profile-chev" width="9" height="9" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg></button><span class="profile-menu" hidden><a href="/funds">Funds</a><a href="/settings">Settings</a><a href="/billing">Billing</a><a href="/devlog">Dev Logs</a><a href="/system">System</a>${adminViewOn() ? '<a href="/admin">Admin</a>' : ''}<button class="profile-item" data-action="signout">Sign out</button></span></span></span>
      </div></header>
      <div class="workspace"><aside class="hotrail" id="hotrail" aria-label="Hot markets"></aside><div class="wrap">
        <div id="boardbody">${board}</div>
        <main id="main" tabindex="-1">${main}</main>
      </div></div>`;
    // The section tabs scroll sideways on a phone; bring the current one into view.
    const tabs = root.querySelector('.services-in'), here0 = tabs && tabs.querySelector('[aria-current="page"]');
    if (here0 && here0.offsetLeft + here0.offsetWidth > tabs.clientWidth) tabs.scrollLeft = here0.offsetLeft - 16;
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
    shell('/devlog', boardTitle('Dev Logs'), loading(260));
    let d;
    try { d = await api('/api/devlog'); } catch (e) { root.querySelector('main').innerHTML = notice(e.message, 'bad'); return; }
    const planned = (d.planned || []).map((p) => `<li class="dl-item planned">
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
      <section class="sect dl-panel" data-dlpanel="planned"${tab === 'planned' ? '' : ' hidden'}><div class="sect-head"><h2>Shipping next</h2></div>
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
    shell('/settings', boardTitle('Settings'), `
      <section class="sect theme-settings"><div class="section-head"><h2>Theme</h2></div>
        <div class="theme-pick" role="radiogroup" aria-label="Theme">
          ${THEMES.map((t) => `<button type="button" class="theme-opt${t.key === current ? ' on' : ''}" role="radio" aria-checked="${t.key === current}" data-theme="${t.key}">
              <span class="theme-meta"><b>${esc(t.name)}</b></span>
              <span class="theme-mark" aria-hidden="true">${ICON.check}</span>
            </button>`).join('')}
        </div>
        <div id="theme-flash" class="hint" role="status"></div>
      </section>`);
    root.querySelectorAll('[data-theme]').forEach((b) => (b.onclick = () => {
      const key = b.dataset.theme;
      if (key === current) return;
      busy(b, async () => {
        try { localStorage.setItem('tau_ui', key); } catch (e) { /* private mode */ }
        // The shell links the theme from this cookie (the server sets it too, on the save below).
        document.cookie = `tau_ui=${key}; Path=/; Max-Age=34560000; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
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
  // A failed load says so and offers a retry, instead of leaving a skeleton up for good.
  const loadFail = (msg) => `<div class="load-fail">${notice(msg, 'bad')}<button type="button" class="btn sm" data-retry>Try again</button></div>`;
  const loading = (h = 160) => `<div class="skeleton" style="height:${h}px" aria-label="Loading"></div>`;

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
    const W = options.width || 760, H = options.height || 236, L = 52, R = 10, T = options.paper ? 16 : 30, B = 26;
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
    if (options.paper) {
      // Round only the display domain; saved observations and all backtest charts stay intact.
      const span = hi - lo, rough = span * 1.08 / 3;
      const magnitude = 10 ** Math.floor(Math.log10(rough));
      const step = [1, 2, 2.5, 5, 10].find(n => n >= rough / magnitude) * magnitude;
      lo = Math.floor((lo < 0 ? lo - span * .08 : lo) / step) * step;
      hi = Math.ceil((hi > 0 ? hi + span * .08 : hi) / step) * step;
    }
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const cut = cutoffIso ? Date.parse(cutoffIso) / 1000 : null;
    const cx = cut && cut > t0 && cut < t1 ? x(cut) : null;
    const line = (c) => c.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const levels = [lo, (lo + hi) / 2, hi];
    const reference = options.paper ? levels.filter(v => v !== 0).map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--rule)"/>`).join('') : '';
    const wholePaperAxis = options.paper && levels.every(Number.isInteger);
    const ticks = levels.map((v) => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${wholePaperAxis ? `${v < 0 ? '−' : ''}$${num(Math.abs(v))}` : usd(v)}</text>`).join('');
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', ...(options.paper ? { timeZone: 'UTC' } : {}) });
    const dates = options.paper ? [t0, (t0 + t1) / 2, t1].map((t, i) => `<text x="${x(t)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}">${day(t)}</text>`).join('') : `<text x="${L}" y="${H - 6}">${day(t0)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>`;
    const endLabel = options.paper && options.endLabel !== false ? `<text class="chart-end ${tone(curve[curve.length - 1][1])}" x="${W - R}" y="${Math.max(12, Math.min(H - B - 6, y(curve[curve.length - 1][1]) - 10))}" text-anchor="end">${usd(curve[curve.length - 1][1], true)}</text>` : '';
    const legend = dev ? `<g transform="translate(${L},${T - 12})">
        <line x1="0" x2="16" y1="0" y2="0" stroke="var(--ink)" stroke-width="2"/><text x="20" y="4" style="fill:var(--ink-2)">Simulated</text>
        <line x1="92" x2="108" y1="0" y2="0" stroke="var(--l-accent, #F05A28)" stroke-width="2" stroke-dasharray="5 4"/><text x="112" y="4" style="fill:var(--ink-2)">Kalshi dev (real)</text>
      </g>` : '';
    const inspect = options.paper ? curve.map(([t, value], i) => {
      const px = x(t), py = y(value), boxWidth = 148;
      const left = i ? (x(curve[i - 1][0]) + px) / 2 : L;
      const right = i < curve.length - 1 ? (px + x(curve[i + 1][0])) / 2 : W - R;
      const boxX = Math.max(L, Math.min(W - R - boxWidth, px + 8));
      const boxY = py < T + 32 ? T + 8 : T;
      const label = `${day(t)} · ${usd(value, true)}`;
      return `<g class="chart-sample" data-time="${t}" tabindex="0" role="img" aria-label="${esc(label)}">
        <rect x="${left}" y="${T}" width="${Math.max(0, right - left)}" height="${H - T - B}" fill="transparent"/>
        <g class="chart-reading" aria-hidden="true"><line x1="${px}" x2="${px}" y1="${T}" y2="${H - B}" stroke="var(--rule-2)" stroke-dasharray="2 3"/><circle cx="${px}" cy="${py}" r="3" fill="var(--ink)"/>
          <rect x="${boxX}" y="${boxY}" width="${boxWidth}" height="26" fill="var(--stock-raised)" stroke="var(--rule-2)"/><text x="${boxX + 8}" y="${boxY + 17}">${esc(label)}</text></g></g>`;
    }).join('') : '';
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="${options.paper ? 'group' : 'img'}" aria-label="${esc(options.label || `Cumulative profit and loss over the backtest${dev ? ', with a realized Kalshi demo-environment curve' : ''}; ends at ${usd(vals[vals.length - 1], true)}`)}">
      ${cx ? `<rect x="${cx}" y="${T}" width="${W - R - cx}" height="${H - T - B}" fill="var(--stock-raised)"/>
              <line x1="${cx}" x2="${cx}" y1="${T}" y2="${H - B}" stroke="var(--ink-3)" stroke-dasharray="4 4"/>
              <text x="${cx + 8}" y="${T - 10}" style="fill:var(--ink-2)">Out-of-sample →</text>` : ''}
      <line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--rule-2)"/>
      ${reference}${ticks}${dates}${endLabel}
      <polyline points="${line(curve)}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round"/>
      ${dev ? `<polyline points="${line(dev)}" fill="none" stroke="var(--l-accent, #F05A28)" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>` : ''}
      ${legend}
      ${inspect}
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
  // `drawn`: a drawdown series the server already built from every trade (the track record sends
  // one, since its equity curve is thinned and could have lost the peak a drop started from).
  function rpUnderwater(curve, drawn) {
    const src = drawn || curve;
    if (!src || src.length < 2) return `<div class="rp-empty">No equity curve to derive drawdown from.</div>`;
    let peak = -Infinity; const dd = drawn || curve.map(([t, v]) => { peak = Math.max(peak, v); return [t, v - peak]; });
    const W = 340, H = 180, L = 54, R = 10, T = 14, B = 22;
    const t0 = src[0][0], t1 = src[src.length - 1][0];
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
  const STRAT_HEAD = (pick) => `<thead><tr>${pick ? '<th class="pickcol"><input type="checkbox" id="pick-all" aria-label="Select all deployable"></th>' : ''}<th>Strategy</th><th>Market</th><th class="num">Unseen P&amp;L${glo('unseen')}</th><th class="num">Trades</th><th class="num">Win</th><th class="num" title="Total hypotheses tested in this research run">Run trials</th><th>Status</th></tr></thead>`;
  const strategyTable = (rows, pick) => `<div class="sheet"><table class="stack t-strat">${STRAT_HEAD(pick)}<tbody>${rows}</tbody></table></div>`;
  // Bulk deploy offers only passed strategies that aren't already running: ticking one that is
  // would start a second deployment of the same rules and double its positions.
  const bulkDeployable = (s) => s.status === 'passed' && !researchOnly(s) && !s.deployed;
  // What a deployed strategy has actually done, beside its backtest columns.
  // The server sends one book (live, else paper, else demo) and a paper strategy's demo book beside it
  // under r.demo, so sandbox dollars are never added to paper ones.
  const realTrades = (n) => `${n} trade${n === 1 ? '' : 's'}`;
  // The example session (and its strategies) every account is seeded with: the server flags it
  // `example`, leaves it out of every headline count, and the lists say the app ran it for free.
  const EXAMPLE_NOTE = 'An example Tau ran for you when you signed up. It cost you nothing.';
  const EXAMPLE_TAG = `<span class="mk quiet example-tag" title="${EXAMPLE_NOTE}">Example</span>`;
  const realFig = (r) => r ? `<div class="sub-fig real-fig">${r.trades ? `${money(r.pnl)} ${r.mode === 'demo' ? 'on demo ' : ''}since deploying \u00b7 ${realTrades(r.trades)}` : r.mode === 'demo' ? 'No closed demo trades yet' : 'No closed trades yet'}</div>${r.demo ? `<div class="sub-fig real-fig">Demo: ${r.demo.trades ? `${money(r.demo.pnl)} \u00b7 ${realTrades(r.demo.trades)}` : 'no closed trades yet'}</div>` : ''}` : '';
  function strategySlip(s, reg, opts = {}) {
    const oos = s.out_of_sample, ins = s.in_sample || {};
    const m = oos || ins;
    const tried = s.hypotheses_tried != null ? num(s.hypotheses_tried) : s.parent_id ? 'Adjustment' : '\u2014';
    const name = opts.nolink ? esc(s.title) : `<a href="/strategies/${s.id}">${esc(s.title)}</a>`;
    const pickCell = opts.pick ? (bulkDeployable(s)
      ? `<td class="pickcol" data-lab="Deploy"><input type="checkbox" class="pick" data-id="${s.id}" aria-label="Select for deployment"></td>`
      : '<td class="pickcol" data-lab=""></td>') : '';
    return `<tr class="${opts.land ? 'washed' : ''}">${pickCell}
      <td class="name" data-lab=""><span class="strategy-ref">${esc(String(s.id).padStart(4, '0'))}</span>${name}${s.shared_from ? ` <span class="shared-flag">${ICON.share}${esc(s.shared_from)}</span>` : ''}${s.example ? ' ' + EXAMPLE_TAG : ''}</td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(s.market))} \u00b7 ${esc(dirLabel(s.direction))}</span></td>
      <td class="num" data-lab="${oos ? 'Backtest P&amp;L (unseen)' : 'Backtest P&amp;L (tested)'}">${m.pnl == null ? '\u2014' : money(m.pnl)}${oos ? '' : '<div class="sub-fig">tested only</div>'}</td>
      <td class="num" data-lab="Trades">${m.trades == null ? '\u2014' : m.trades}</td>
      <td class="num" data-lab="Win">${pct(m.win_rate, false)}</td>
      <td class="num${tried === '\u2014' ? ' nil' : ''}" data-lab="Run trials">${esc(tried)}</td>
      <td class="act" data-lab="">${mark(s.status)}${researchBadge(s)}${s.deployed && !researchOnly(s) ? ` <span class="mk ${s.deploy_live ? 'live' : 'dep'}">${s.deploy_live ? 'Live' : 'Deployed'}</span>${s.real && s.real.paused ? ' ' + mark('paused') : ''}${realFig(s.real)}` : ''}</td>
    </tr>`;
  }
  const DEP_HEAD = (controls) => `<thead><tr><th>Strategy</th><th>Status</th><th class="num">Realized P&amp;L</th><th class="num">Unrealized</th><th class="num">Trades</th>${controls ? '<th class="act"><span class="vh">Actions</span></th>' : ''}</tr></thead>`;
  // Paused deployments need the user ("Resume or remove it on Deploy" sends them here), so they lead.
  const pausedFirst = (ds) => [...ds].sort((a, b) => (b.status === 'paused') - (a.status === 'paused'));
  const deploymentTable = (rows, controls) => `<div class="sheet"><table class="stack t-dep">${DEP_HEAD(controls)}<tbody>${rows}</tbody></table></div>`;
  const deploymentMode = (d) => d.mode === 'live' ? '<span class="mk live">LIVE</span>' : d.mode === 'demo' ? '<span class="mk dep">Demo</span>' : '<span class="mk">Paper</span>';
  const deploymentRemove = (d) => `<button class="btn sm danger" data-dep="${esc(d.id)}" data-act="stop">Remove</button>`;
  const deploymentActions = (d, remove = true) => `<div class="deployment-actions">
    ${d.status === 'running' ? `<button class="btn sm" data-dep="${d.id}" data-act="pause">Pause</button>` : ''}
    ${d.status === 'paused' ? `<button class="btn sm" data-dep="${d.id}" data-act="resume">Resume</button>` : ''}
    ${remove ? deploymentRemove(d) : ''}</div>`;
  // What the deployment's closed trades would have made at the unseen-data backtest's average per
  // trade: the number to hold realized P&L against (the backtest total covers a different trade count).
  const backtestPace = (d) => {
    const oos = d.backtest && d.backtest.out_of_sample, n = +d.closed_trades || 0;
    if (!oos || !(+oos.trades > 0) || !n) return '';
    return `Backtest pace ${usd((+oos.pnl || 0) / +oos.trades * n, true)} for the same ${n} trade${n === 1 ? '' : 's'} · `;
  };
  const deploymentEvidence = (d, manage = false) => `<details class="dep-evidence" data-deployment="${esc(d.id)}"><summary aria-label="Backtest and deployment details">Details</summary><div>${backtestPace(d)}Unseen P&amp;L ${d.backtest && d.backtest.out_of_sample ? usd(d.backtest.out_of_sample.pnl, true) : '\u2014'} · Deployed ${when(d.created_at)}${manage ? `<div class="deployment-actions">${deploymentRemove(d)}</div>` : ''}</div></details>`;
  function deploymentSlip(d, controls, regs) {
    const live = d.mode === 'live';
    const modeTag = deploymentMode(d);
    const actions = controls ? `<td class="act" data-lab="">${deploymentActions(d)}</td>` : '';
    return `<tr class="${live ? 'live-row' : ''}">
      <td class="name" data-lab=""><a href="/strategies/${d.strategy_id}">${esc(d.title)}</a>
        <div class="dep-meta"><span class="sub-fig">${esc(marketShort(d.market))} · $${esc(d.stake)} / trade · Max ${esc(d.max_positions)} open${d.status !== 'running' && d.status_reason ? ' \u00b7 ' + esc(d.status_reason) : ''}</span>
        ${deploymentEvidence(d)}</div></td>
      <td data-lab="Status">${d.status === 'running' ? '<span class="deployment-state">Running</span>' : mark(d.status, live)}<div class="sub-fig">${modeTag}</div></td>
      <td class="num" data-lab="Realized">${money(d.realized_pnl)}${spark(d.curve, regs && regs[d.mode], d.closed_trades)}</td>
      <td class="num" data-lab="Unrealized">${d.unrealized_pnl == null ? '<span class="sub-fig">—</span>' : money(d.unrealized_pnl)}${d.unrealized_pnl != null && d.open_positions ? ' <div class="sub-fig">est.</div>' : ''}</td>
      <td class="num" data-lab="Trades">${d.closed_trades} closed${d.open_positions ? ` <div class="sub-fig">${d.open_positions} open</div>` : ''}</td>
      ${actions}
    </tr>`;
  }
  function deploymentMonitor(d, anchor = false, regs = null) {
    const live = d.mode === 'live';
    return `<article ${anchor ? 'id="dash-paused" ' : ''}class="dep-monitor${live ? ' live-row' : ''}">
      <header><h3><a href="/strategies/${d.strategy_id}">${esc(d.title)}</a></h3><span class="monitor-state"><span class="monitor-mode">${deploymentMode(d)}</span><span aria-hidden="true">·</span>${d.status === 'running' ? '<span class="deployment-state">Running</span>' : mark(d.status, live)}</span></header>
      <div class="monitor-config"><div class="monitor-summary"><p class="monitor-setup">${esc(marketShort(d.market))} · $${esc(d.stake)} / trade</p><div class="monitor-limits"><span>· Max ${esc(d.max_positions)} open${d.status !== 'running' && d.status_reason ? ' · ' + esc(d.status_reason) : ''}</span></div></div></div>
      <dl class="monitor-metrics">
        <div class="monitor-realized"><dt>Realized P&amp;L</dt><dd>${money(d.realized_pnl)}${spark(d.curve, regs && regs[d.mode], d.closed_trades)}</dd></div>
        <div class="monitor-unrealized"><dt>${d.unrealized_pnl != null && d.open_positions ? 'Unrealized (est.)' : 'Unrealized P&amp;L'}</dt><dd>${d.unrealized_pnl == null ? '<span class="unavailable">Unavailable</span>' : money(d.unrealized_pnl)}</dd></div>
      </dl>
      <div class="monitor-footer"><dl class="monitor-counts"><div><dt>Closed / open</dt><dd aria-label="${esc(d.closed_trades)} closed trades, ${esc(d.open_positions || 0)} open positions">${esc(d.closed_trades)} / ${esc(d.open_positions || 0)}</dd></div></dl><div class="monitor-controls">${deploymentActions(d, false)}${deploymentEvidence(d, true)}</div></div>
    </article>`;
  }
  function replaceDeploymentContent(host, html) {
    const kinds = [['.dep-evidence', 'deployment'], ['.position-details', 'position']];
    const state = kinds.map(([selector, key]) => ({ selector, key,
      opened: new Set(Array.from(host.querySelectorAll(selector + '[open]'), d => d.dataset[key])),
      focused: host.querySelector(selector + ' > summary:focus')?.parentElement.dataset[key],
    }));
    host.innerHTML = html;
    state.forEach(({selector, key, opened, focused}) => host.querySelectorAll(selector).forEach(d => {
      d.open = opened.has(d.dataset[key]);
      if (d.dataset[key] === focused) d.querySelector('summary').focus({ preventScroll: true });
    }));
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
  async function viewSignin() {
    const hr = document.getElementById('hotrail'); if (hr) hr.remove();
    document.body.classList.remove('hot-open');
    // Boot just got a 401 and redirected here: don't wait on a second /api/me before painting the landing page.
    const justSignedOut = S.signedOutAt && Date.now() - S.signedOutAt < 5000;
    if (!S.me && !justSignedOut) { try { S.me = await api('/api/me'); } catch (e) { /* signed out: stay here */ } }
    if (S.me) return go('/', true);
    const q = new URLSearchParams(location.search);
    const err = q.get('error');
    const msg = q.has('pending')
      ? "You're on the waitlist — we'll email you the moment you're approved. (Access is invite-only right now.)"
      : { cancelled: 'Sign-in was cancelled.', expired: 'That sign-in link expired. Try again.', google: "Google couldn't confirm your account. We may not have added you to the waitlist yet." }[err];
    const nextQ = signinNext();
    document.body.classList.add('landing-body');
    root.innerHTML = `
      <div class="landing">
        <header class="lnav">
          <a class="lbrand" href="/">${ICON.mark}<span>Tau</span></a>
          <div class="lnav-actions">
            <a class="pill" href="/auth/google${nextQ}" data-native>Sign in</a>
            <button class="pill solid" data-action="waitlist-top">Join waitlist</button>
          </div>
        </header>
        <section class="lhero">
          <div class="lhero-copy">
            <h1>RSI for Trading.</h1>
            <p class="lsub">Recursive self-improvement, pointed at the market: an agent researches strategies, tests each on data it never saw, learns from every result, and trades only the ones that pass — in your own Kalshi account.</p>
            ${msg ? `<div class="lnotice">${esc(msg)}</div>` : ''}
            <div class="lcta" id="lcta">
              <a class="pill solid lg" href="/auth/google${nextQ}" data-native>${ICON.google}Continue with Google</a>
              <button class="pill lg" data-action="waitlist-open">Join waitlist</button>
            </div>
            <p class="lfine">Access is invite-only right now. Join the waitlist and we'll email you when a spot opens. You'll start with $1,000 of paper money; live trading is optional and runs in your own Kalshi account.</p>
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
            <div class="lfoot-links"><button class="linkish" data-action="waitlist-top">Join waitlist</button><span>Research preview</span><span>© 2026 Tau</span></div>
          </footer>
        </main>
      </div>`;
    startDemo();
    setupScenes();
    root.querySelector('#demo-replay').onclick = startDemo;
    const dlg = document.createElement('dialog');
    dlg.className = 'wl-modal';
    dlg.innerHTML = `
      <form method="dialog" class="wl-inner" id="wlform">
        <button class="wl-x" type="button" data-close aria-label="Close">${ICON.cross}</button>
        <h2>Join the waitlist</h2>
        <p class="wl-sub">We're opening access to Tau in batches. Leave your email to get an invitation.</p>
        <label class="field"><span>Email</span>
          <span class="wl-ifield">${ICON.mail}<input id="wlemail" type="email" inputmode="email" autocomplete="email" placeholder="you@example.com" required></span></label>
        <p class="wl-note">We'll email you when your spot is ready. We never share your address.</p>
        <label class="field"><span>Twitter handle <small>(optional)</small></span>
          <span class="wl-ifield">${ICON.at}<input id="wlhandle" type="text" autocomplete="off" placeholder="yourhandle"></span></label>
        <div id="wlhint"></div>
        <button class="pill solid wl-submit" type="submit">Join waitlist</button>
      </form>`;
    root.querySelector('.landing').appendChild(dlg);
    const openWaitlist = () => {
      const hint = dlg.querySelector('#wlhint'); hint.innerHTML = '';
      if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
      setTimeout(() => dlg.querySelector('#wlemail').focus(), 50);
    };
    const close = () => { dlg.open && (dlg.close ? dlg.close() : dlg.removeAttribute('open')); };
    dlg.querySelector('[data-close]').onclick = close;
    dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });  // backdrop click
    dlg.querySelector('#wlform').onsubmit = async (e) => {
      e.preventDefault();
      const email = dlg.querySelector('#wlemail').value.trim();
      const note = dlg.querySelector('#wlhandle').value.trim();
      await busy(dlg.querySelector('.wl-submit'), async () => {
        try {
          await api('/api/waitlist', { email, note: note ? ('Twitter: ' + note) : '' });
          dlg.querySelector('.wl-inner').innerHTML = `<button class="wl-x" type="button" data-close aria-label="Close">${ICON.cross}</button>
            <div class="wl-done">${ICON.check}<h2>You're on the list</h2><p>We'll email <b>${esc(email)}</b> when your spot is ready.</p>
            <button class="pill solid" type="button" data-close>Done</button></div>`;
          dlg.querySelectorAll('[data-close]').forEach((b) => (b.onclick = close));
        } catch (err) { dlg.querySelector('#wlhint').innerHTML = `<p class="wlhint bad">${esc(err.message)}</p>`; }
      });
    };
    root.querySelectorAll('[data-action="waitlist-open"],[data-action="waitlist-top"]').forEach((b) => (b.onclick = openWaitlist));
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
    const gen = S.gen;
    const load = async (cfg) => {
      const d = await api('/api/dashboard', undefined, cfg);
      if (gen !== S.gen) return;
      const p = d.paper;
      // Realized P&L (all-time + today) and open count for one money bucket; a tasteful
      // zero line when the bucket has no activity so an empty card never looks broken.
      // The figure above it is Kalshi's cash for the whole account; this line is Tau's own trades.
      const mSub = (b, zero) => (b.open_positions || b.running || b.realized_pnl) ? `Tau trades: ${b.open_positions} open${b.open_positions ? ' (not in cash)' : ''} · ${usd(b.realized_pnl, true)} realized all time · ${usd(b.today_pnl, true)} realized today (UTC)` : zero;
      const hasLive = d.deployments.some((x) => x.mode === 'live' && x.status !== 'stopped');
      const paperWorkspace = !hasLive && d.open_positions.concat(d.recent_closed, d.deployments).every(x => x.mode === 'paper');
      const sharedPaperRunning = d.deployments.length > 0 && d.deployments.every(x => x.mode === 'paper' && x.status === 'running');
      // Collector lag is the operator's to fix, so only the admin view shows it (red "needs you" told
      // every user something was wrong that they couldn't act on).
      const stale = adminViewOn() && (d.freshness.btc == null || d.freshness.btc > 2700);
      const agentsBusy = d.agents.research_running + d.agents.research_queued;
      const paused = d.deployments.filter((x) => x.status === 'paused').length;
      const needs = stale || paused > 0;
      const accountsOpen = !!root.querySelector('#other-accounts[open]');
      const accountsFocused = !!root.querySelector('#other-accounts > summary:focus');
      const performanceState = root.querySelector('#paper-performance');
      const performanceOpen = performanceState ? performanceState.open : true;
      const performanceFocused = !!root.querySelector('#paper-performance > summary:focus');
      const sampleFocused = root.querySelector('.chart-sample:focus')?.dataset.time;
      const settlementsOpen = !!root.querySelector('#recent-settlements[open]');
      const settlementsFocused = !!root.querySelector('#recent-settlements > summary:focus');
      const said = [
        hasLive ? `Live money on: ${usd(d.live.realized_pnl, true)} realized all time` : '',
        paused ? `<a class="needs-link" href="#dash-paused"><em>${paused} paused, needs you</em></a>` : '',
        stale ? `<em>${d.freshness.btc == null ? 'No backtest history yet' : 'Backtest history stale ' + age(d.freshness.btc)}</em>` : '',
      ].filter(Boolean).join('<span class="sep">/</span>');
      const liveFigure = fig('Kalshi cash', d.live.connected ? (d.live.balance == null ? 'Unavailable' : usd(d.live.balance)) : 'Not connected', { small: (d.live.connected ? (d.live.balance == null ? 'Couldn\u2019t read your Kalshi balance just now' : mSub(d.live, 'Your Kalshi cash \u2014 real money untouched')) : '<a href="/funds">Connect Kalshi</a>') + tradesCsv('live', d.live) });
      const liveSummary = `<div class="m live-summary"><dt class="lab vh">Kalshi cash</dt><dd class="portfolio-numbers"><div class="portfolio-group"><div><span class="lab" aria-hidden="true">Kalshi cash</span><strong class="fig${!d.live.connected || d.live.balance == null ? ' balance-state' : ''}">${d.live.connected ? (d.live.balance == null ? 'Unavailable' : usd(d.live.balance)) : 'Not connected'}</strong><span class="portfolio-return">${d.live.connected ? (d.live.balance == null ? 'Couldn\u2019t read your Kalshi balance just now' : `${money(d.live.realized_pnl)} realized all time by Tau trades`) : '<a href="/funds">Connect Kalshi</a>'}${tradesCsv('live', d.live)}</span></div><div class="portfolio-detail"><span class="lab">Realized today (UTC)</span><strong>${money(d.live.today_pnl)}</strong></div></div><div class="portfolio-group"><div class="portfolio-detail"><span class="lab">Open positions</span><strong>${esc(d.live.open_positions)}</strong></div><div class="portfolio-detail"><span class="lab">Open at cost, not in cash</span><strong>${usd(d.live.open_at_cost)}</strong></div></div></dd></div>`;
      const demoFigure = fig('Demo balance', usd(d.demo.equity), { v: d.demo.realized_pnl, small: `${(d.demo.open_positions || d.demo.running || d.demo.realized_pnl) ? `${usd(d.demo.capital)} capital \u00b7 ${d.demo.open_positions} open \u00b7 ${usd(d.demo.realized_pnl, true)} P&amp;L ${demoSpan(d.demo)}` : `${usd(d.demo.capital)} capital · No demo deployments`} \u00b7 ${DEMO_WHAT}${tradesCsv('demo', d.demo)}` });
      const paperFigure = `<div class="m paper-summary"><dt class="lab vh">Paper portfolio</dt><dd class="portfolio-numbers"><div class="portfolio-group"><div><span class="lab" aria-hidden="true">Paper portfolio</span><strong class="fig">${usd(p.equity)}</strong><span class="portfolio-return">${p.reset_at ? 'P&amp;L since reset' : 'All-time P&amp;L'} ${money(p.total_pnl)}${tradesCsv('paper', p)}</span></div><div class="portfolio-detail"><span class="lab">Realized today (UTC)</span><strong>${money(p.today_pnl)}</strong></div></div><div class="portfolio-group"><div class="portfolio-detail"><span class="lab">Available cash</span><strong>${usd(p.cash)}</strong></div><div class="portfolio-detail"><span class="lab">Open at cost</span><strong>${usd(p.open_at_cost)}</strong></div></div></dd></div>`;
      const board = `
        ${said ? `<div class="statusline dashboard-status ${needs ? 'needs' : ''}"><p class="said">${said}</p></div>` : ''}
        ${d.live.connected && d.live.open_positions ? `<p class="recon ${(d.reconcile && d.reconcile.length) ? 'warn' : 'ok'}">${(d.reconcile && d.reconcile.length) ? `\u26a0 ${d.reconcile.length} live position${d.reconcile.length === 1 ? '' : 's'} disagree with Kalshi \u2014 check your Portfolio` : `${ICON.check} Live book reconciled with Kalshi`}</p>` : ''}
        <div class="pagehead"><div class="overview-heading"><h1 class="page">Overview</h1></div><div class="page-actions"><details class="other-accounts" id="other-accounts"${accountsOpen ? ' open' : ''}><summary>Accounts ${ICON.chev}</summary><dl>${hasLive ? paperFigure : liveFigure}${demoFigure}</dl></details>${agentsBusy ? `<a class="research-activity" href="/research">${agentsBusy} agent${agentsBusy > 1 ? 's' : ''} researching</a>` : ''}</div></div>`;
      const firstPaused = d.deployments.find((x) => x.status === 'paused');
      const depRegs = curveRegs(d.deployments);  // the status line's "paused, needs you" jumps here
      const deps = d.deployments.length
        ? `<div class="dep-register">${d.deployments.map((x) => deploymentMonitor(x, x === firstPaused, depRegs)).join('')}</div>`
        : `<div id="deps-empty" data-on="${S.me.user && S.me.user.autopilot ? 1 : 0}">${depsEmpty(S.me.user && S.me.user.autopilot)}</div>`;
      const positionMarket = r => (S.me.markets || []).find(m => m.series && r.ticker.startsWith(m.series + '-'));
      const positions = (rows, closed) => rows.map((r) => {
        const market = positionMarket(r);
        const contract = market ? `<span class="position-prefix">${esc(market.series + '-')}</span>${esc(r.ticker.slice(market.series.length + 1))}` : esc(r.ticker);
        const close = r.market_close_time && new Date(r.market_close_time);
        const expiry = close && Number.isFinite(close.getTime()) ? close.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',  }) : '';
        return `<tr class="${closed ? 'settled-position' : 'open-position'}">
        <td class="name"><details class="position-details" data-position="${closed ? 'closed' : 'open'}-${esc(r.id)}"><summary aria-label="${market ? `${esc(market.label || marketShort(market.key))} · ` : ''}${esc(r.title)} · ${esc(r.ticker)} · ${r.mode === 'live' ? 'LIVE' : r.mode === 'demo' ? 'Demo' : 'Paper'}">${ICON.chev}<span class="position-title vh">${esc(r.title)}</span><span class="position-mode">${r.mode === 'live' ? '<span class="mk live">LIVE</span>' : r.mode === 'demo' ? 'Demo' : 'Paper'}</span>${market ? `<span class="position-market">${esc(market.label || marketShort(market.key))}</span>` : ''}<span class="position-contract">${contract}</span></summary><div class="sub-fig">${esc(r.ticker)} · ${esc(r.title)}<span class="position-opened">${closed ? 'Closed' : 'Opened'} ${when(closed ? r.closed_at : r.opened_at)}</span>${close && Number.isFinite(close.getTime()) ? `<span class="position-absolute">Expires ${esc(close.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'long', hourCycle: 'h23' }))}</span>` : ''}${!closed && r.unrealized == null ? '<span class="position-mark-note">Unrealized P&amp;L unavailable</span>' : ''}</div></details></td>
        <td class="position-size-cell"><span class="position-size"><span class="position-side">${esc(r.side.toUpperCase())}</span><span aria-hidden="true"> × </span><span class="position-quantity"><span class="vh">Quantity </span>${esc(r.qty)}</span></span></td>
        <td class="position-expiry-cell">${expiry ? `<time class="position-expiry" datetime="${esc(close.toISOString())}">${esc(expiry)}</time>` : '<span class="unavailable" title="Expiry unavailable"><span aria-hidden="true">—</span><span class="vh">Expiry unavailable</span></span>'}</td>
        <td class="num position-entry">${cents(+r.entry_price)}</td>
        ${closed ? '' : `<td class="num"><span class="position-cost">${usd(r.qty * r.entry_price)}</span></td>`}
        <td class="num"><span class="position-pnl">${closed ? money(+r.pnl) : (r.unrealized != null ? money(r.unrealized) : '<span class="unavailable" title="Unrealized P&amp;L unavailable"><span aria-hidden="true">—</span><span class="vh">Unavailable</span></span>')}</span></td>
        </tr>`;
      }).join('');
      const paperOnly = (rows) => rows.length && rows.every(r => r.mode === 'paper');
      const positionTable = (rows, closed) => {
        const onlyPaper = !!paperOnly(rows);
        const widths = closed ? [332, 100, 160, 88, 128] : [300, 92, 112, 80, 96, 128];
        const groups = [];
        rows.forEach(row => {
          const market = positionMarket(row), previous = groups[groups.length - 1];
          const deploymentId = row.deployment_id;
          const knownDeployment = (typeof deploymentId === 'number' && Number.isSafeInteger(deploymentId) && deploymentId > 0)
            || (typeof deploymentId === 'string' && /^[1-9]\d*$/.test(deploymentId));
          // Attribution is a view over adjacent records, never a merge of unknown deployments.
          const canGroup = knownDeployment && market && typeof row.title === 'string' && row.title.length > 0
            && ['paper', 'demo', 'live'].includes(row.mode);
          if (canGroup && previous && previous.deploymentId === deploymentId && previous.title === row.title
              && previous.mode === row.mode && previous.market === market) previous.rows.push(row);
          else groups.push({market, deploymentId, title: row.title, mode: row.mode, rows: [row]});
        });
        const bodies = groups.map(group => `<tbody><tr class="position-family"><th scope="rowgroup" colspan="${widths.length}"><span class="position-attribution">${group.market ? `<span class="position-family-name vh">${esc(group.market.label || marketShort(group.market.key))}</span>` : ''}<span class="position-strategy">${esc(group.title)}</span><span class="position-attribution-mode">${group.mode === 'live' ? '<span class="mk live">LIVE</span>' : group.mode === 'demo' ? 'Demo' : 'Paper'}</span></span></th></tr>${positions(group.rows, closed)}</tbody>`).join('');
        return `<div class="sheet"><table class="t-positions" data-paper-only="${onlyPaper}"><colgroup>${widths.map(width => `<col style="width:${width / 808 * 100}%">`).join('')}</colgroup><thead><tr><th scope="col">Market / contract</th><th scope="col">Position</th><th scope="col">Expiry</th><th scope="col" class="num">Entry</th>${closed ? '' : '<th scope="col" class="num">Cost</th>'}<th scope="col" class="num" title="${closed ? 'Realized result after settlement' : 'Estimated from the latest stored bid'}">${closed ? 'Realized' : 'Unrealized'} P&amp;L</th></tr></thead>${bodies}</table></div>`;
      };
      const days = (p.daily || []).slice(-30);
      let periodPnl = 0;
      const periodCurve = days.map(day => [Date.parse(day.d + 'T12:00:00Z') / 1000, periodPnl += +day.pnl]);
      const paperPlot = (width) => equityChart(periodCurve, null, null, { width: Math.max(280, width || root.querySelector('main').clientWidth), height: 180, paper: true, endLabel: false, label: `Cumulative closed paper profit and loss from ${days[0].d} through ${days[days.length - 1].d}; ends at ${usd(periodPnl, true)}` });
      const periodLabel = days.length > 1 ? new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'}).formatRange(new Date(days[0].d + 'T12:00:00Z'), new Date(days[days.length - 1].d + 'T12:00:00Z')) : '';
      const performance = days.length > 1 ? `<details class="overview-performance" id="paper-performance"${performanceOpen ? ' open' : ''}><summary><span class="performance-heading"><span class="performance-caption"><h2>Closed P&amp;L</h2>${ICON.chev}</span><strong class="${tone(periodPnl)}" title="Cumulative closed P&L over this period">${usd(periodPnl, true)}</strong></span><span class="performance-meta"><span class="performance-mode"><span class="performance-mode-prefix">Paper · </span>cumulative</span><span class="sect-note" title="${esc(days[0].d)} – ${esc(days[days.length - 1].d)}">${esc(periodLabel)}</span></span></summary><div class="paper-plot">${paperPlot()}</div></details>` : '';
      const main = `<section id="dash-ap" class="apcard" aria-label="Autopilot"></section><div class="dash${paperWorkspace ? ' paper-workspace' : ''}"><div class="dash-layout">
        <section class="account-band"><dl class="figures measure dashboard-figures ${hasLive ? 'live-primary' : ''}">${hasLive ? liveSummary : paperFigure}</dl><p class="stale-note" id="dash-stale" role="status"></p></section>
        <section class="positions-ledger"><div class="sect-head"><h2>Open positions <span class="section-count">${d.open_positions.length}</span>${paperOnly(d.open_positions) ? ' <span class="position-group-mode">Paper</span>' : ''}</h2></div>
          ${d.open_positions.length ? positionTable(d.open_positions, false) : '<p class="hint">No open positions.</p>'}
          ${d.recent_closed.length ? `<details class="recent-settlements" id="recent-settlements"${settlementsOpen ? ' open' : ''}><summary>Recent settlements <span>${d.recent_closed.length}</span>${paperOnly(d.recent_closed) ? ' <span class="position-group-mode">Paper</span>' : ''}</summary>${positionTable(d.recent_closed, true)}</details>` : ''}
        </section><div class="dash-analysis">${performance}<section class="sect deployed-monitor${sharedPaperRunning ? ' shared-paper-running' : ''}"><div class="sect-head"><div class="monitor-heading"><h2>Deployed strategies <span class="section-count">${d.deployments.length}</span></h2>${sharedPaperRunning ? '<span class="monitor-context">Paper</span>' : ''}${d.deployments.length ? '<a href="/research?new=1" class="btn">New research</a>' : ''}</div></div><div id="dash-deps">${deps}</div></section></div></div></div>`;
      root.querySelector('#boardbody').innerHTML = board;
      if (accountsFocused) root.querySelector('#other-accounts > summary').focus({ preventScroll: true });
      replaceDeploymentContent(root.querySelector('main'), main);
      S.dashPaper = p;
      paintDashAp();
      resizePaperChart = days.length > 1 ? () => {
        const plot = root.querySelector('.paper-plot');
        if (plot) {
          const focused = plot.querySelector('.chart-sample:focus')?.dataset.time;
          plot.innerHTML = paperPlot(plot.clientWidth);
          if (focused) Array.from(plot.querySelectorAll('.chart-sample')).find(s => s.dataset.time === focused)?.focus({ preventScroll: true });
        }
      } : null;
      if (resizePaperChart) {
        resizePaperChart();
        root.querySelector('#paper-performance').ontoggle = resizePaperChart;
      }
      if (performanceFocused && performance) root.querySelector('#paper-performance > summary').focus({ preventScroll: true });
      if (sampleFocused && performance) Array.from(root.querySelectorAll('.chart-sample')).find(s => s.dataset.time === sampleFocused)?.focus({ preventScroll: true });
      if (settlementsFocused && d.recent_closed.length) root.querySelector('#recent-settlements > summary').focus({ preventScroll: true });
      const dd = root.querySelector('#dash-deps');
      if (dd) bindDeploymentActions(dd, load);  // pause/resume/stop from the dashboard, same as Deploy
    };
    await load();
    if (gen !== S.gen) return;
    poll(load, 15000, 'dash-stale');
    dashTrackRecord();
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
        <span class="win-pnl"><span class="lab">Backtest P&amp;L (unseen)</span><span class="fig sm ${pnl > 0 ? 'tint pos' : pnl < 0 ? 'tint neg' : ''}">${pnl == null ? '—' : usd(pnl, true)}</span></span>
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
      : `<p>New search policies are scored against the current policy over shuffled history. Only an improvement is adopted.</p>`;
    // Demoted to a compact, collapsible line so the research page leads with the form, not panels.
    const expanded = !!host.querySelector('details[open]');
    const focused = !!host.querySelector('details > summary:focus');
    host.innerHTML = `<details class="rsidisc"${expanded ? ' open' : ''}>
      <summary class="rsidisc-cap"><b class="rsi-badge">RSI</b><span class="rsidisc-t">Self-improving research engine</span>${tag}${pol.evolved && delta ? `<span class="rsidisc-delta">${delta}</span>` : ''}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
      <div class="rsidisc-body">${body}</div>
    </details>`;
    if (focused) host.querySelector('summary').focus({ preventScroll: true });
  }
  // The research loop's own report card (GET /api/research/scoreboard, app/rsi.py): is research
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
    const figs = `<dl class="figures measure loop-figs">${fig('Ideas tried', t.explored, { small: `${t.runs} session${t.runs === 1 ? '' : 's'} · 14 days` })}${fig('Reached the gate', t.gated, { small: `${loopRate(t.gate_reach_rate)} of ideas` })}${fig('Passed', t.passed, { small: t.holdout_passed ? `${t.holdout_passed} held out` : 'every gate' })}${fig('Spend', usd(t.cost_usd), { small: `${perIdea} per idea` })}${fig('Killed by our pipeline', loopRate(t.pipeline_death_share), { small: 'of dropped ideas' })}</dl>`;
    const trendP = tr
      ? `<p class="loop-trend">${tr.better ? 'Getting better.' : 'Not better yet.'} The newer ${tr.after.runs} session${tr.after.runs === 1 ? '' : 's'} took ${loopRate(tr.after.gate_reach_rate)} of ${tr.after.explored} ideas to the statistical gate, against ${loopRate(tr.before.gate_reach_rate)} of ${tr.before.explored} before.</p>`
      : `<p class="loop-trend">Each session's ideas are counted from first draft to final verdict. A before/after trend appears once there are 16 ideas to compare.</p>`;
    const maxIdeas = Math.max(1, ...(b.days || []).map((d) => d.explored));
    const days = (b.days || []).length > 1 ? `<div class="loop-days" role="img" aria-label="Ideas per day and how many reached the gate">${b.days.slice(-14).map((d) => `<span class="loop-day" title="${esc(d.day)}: ${d.explored} ideas, ${d.gated} reached the gate"><i class="all" style="height:${Math.max(4, Math.round(40 * d.explored / maxIdeas))}px"></i><i class="hit" style="height:${d.gated ? Math.max(3, Math.round(40 * d.gated / maxIdeas)) : 0}px"></i></span>`).join('')}</div><p class="loop-legend"><i class="all"></i>ideas per day <i class="hit"></i>reached the gate</p>` : '';
    const pt = b.paper && b.paper.total, byPb = (b.paper && b.paper.by_playbook) || {};
    const paperP = pt && pt.strategies ? `<p class="loop-trend">On paper against the live book: ${pt.strategies} passed strateg${pt.strategies === 1 ? 'y' : 'ies'}, ${pt.trading} trading, ${pt.round_trips} round trip${pt.round_trips === 1 ? '' : 's'}, net ${usd(pt.net_pnl, true)}${pt.realization == null ? '' : pt.realization < 0 ? ', losing money where the backtest expected a profit' : `, earning ${Math.round(pt.realization * 100)}% of what the backtest expected`}${pt.live_ready ? ` · ${pt.live_ready} ready for live` : ''}.</p>` : '';
    const fams = {};
    (b.playbooks || []).forEach((p) => { (fams[p.family] = fams[p.family] || {})[p.status] = p; });
    const pbRows = Object.keys(fams).sort().map((f) => {
      const a = fams[f].active, c = fams[f].candidate;
      const paper = (p) => { const q = byPb[p.id] || byPb[String(p.id)]; return q && q.round_trips ? ` · on paper ${q.round_trips} trips, ${usd(q.net_pnl, true)}` : ''; };
      const rec = (p) => (p.ideas ? `${p.reached} of ${p.ideas} ideas reached the gate` : 'no ideas yet') + paper(p);
      const act = a ? `<b>v${a.version}</b> in use${a.version ? '' : ' (no lessons yet)'} · ${rec(a)}` : '';
      const cand = c ? `<br><b>v${c.version}</b> on trial · ${rec(c)}${c.p_better != null ? ` · ${Math.round(c.p_better * 100)}% likely better` : ''}${c.changes ? `<span class="loop-why">What changed: ${esc(c.changes)}</span>` : ''}` : '';
      const text = (c && c.text) || (a && a.text) || '';
      return `<li><span class="loop-k">${esc(loopFamily(f))}</span><span class="loop-v">${act}${cand}${text ? `<details class="loop-pb"><summary>Read the playbook</summary><pre>${esc(text)}</pre></details>` : ''}</span></li>`;
    }).join('');
    const scout = (b.scout || []).slice(0, 5).map((s) => `<li><span class="loop-k">${esc(marketShort(s.market))}</span><span class="loop-v">${esc(s.best_what || '')} · ${s.best_net_c != null ? (s.best_net_c > 0 ? '+' : '') + s.best_net_c.toFixed(1) + '¢' : ''} net per contract · ${s.best_z != null ? s.best_z.toFixed(1) : '—'} SE</span></li>`).join('');
    const fixes = (b.fix_list || []).slice(0, 5).map((x) => `<li><span class="loop-k">${esc(marketShort(x.market))}</span><span class="loop-v"><b>${esc(LOOP_TAG[x.tag] || x.tag)}</b> × ${x.count}${x.example ? `<span class="loop-why">${esc(String(x.example).slice(0, 180))}</span>` : ''}</span></li>`).join('');
    const REQ_KIND = { history: 'more settled history', micro: 'order-book feature', ticks: 'per-second data' };
    const REQ_STATE = { open: 'collecting', ready: 'data arrived', requeued: 'idea re-tested', expired: 'gave up' };
    const reqs = (b.data_requests || []).slice(0, 6).map((r) => `<li><span class="loop-k">${esc(marketShort(r.market))}</span><span class="loop-v"><b>${esc(REQ_KIND[r.kind] || r.kind)}${r.need ? ' · ' + esc(r.need) : ''}</b> · ${esc(REQ_STATE[r.status] || r.status)}${r.requeued_run_id ? ` · <a href="/research/${r.requeued_run_id}">session</a>` : ''}${r.idea_title ? `<span class="loop-why">For: ${esc(r.idea_title)}</span>` : ''}${r.status !== 'requeued' && r.note ? `<span class="loop-why">${esc(r.note)}</span>` : ''}</span></li>`).join('');
    const sect = (h, sub, items) => items ? `<div class="loop-sect"><h4>${h}</h4><p class="loop-sub">${sub}</p><ul class="loop-list">${items}</ul></div>` : '';
    const tn = b.tournament, tnEnt = tn ? (tn.entrants || []).filter((r) => r.strategy_id).sort((x, y) => y.weight - x.weight) : [];
    const tnCash = tn ? (tn.entrants || []).find((r) => !r.strategy_id) : null;
    const tnRows = tnEnt.slice(0, 8).map((r) => `<li><span class="loop-k">${esc(marketShort(r.market))}</span><span class="loop-v"><b>${Math.round(r.weight * 100)}% of the book</b> · ${esc(r.title || '')} · ${r.trips} bet${r.trips === 1 ? '' : 's'}, ${usd(r.net_pnl, true)} · ${Math.round((r.p_positive || 0) * 100)}% likely to make money${r.verdict ? `<span class="loop-why">Retiring: ${esc(r.verdict)}</span>` : ''}</span></li>`).join('')
      + (tnEnt.length && tnCash ? `<li><span class="loop-k">Cash</span><span class="loop-v"><b>${Math.round(tnCash.weight * 100)}% of the book</b> · held back until an entrant beats zero</span></li>` : '');
    const tnSub = tn && tn.pooled ? `Every near miss trades on paper at once, and a bandit moves a ${usd(tn.book.capital)} practice book toward what earns. All entrants together: ${tn.pooled.trips} of the ${tn.pooled.target} independent bets the gate needs${tn.pooled.days_to_target != null ? `, about ${Math.round(tn.pooled.days_to_target)} days to go at ${tn.pooled.per_day} a day` : ''}${tn.pooled.mean_return != null ? `, averaging ${(tn.pooled.mean_return * 100).toFixed(1)}% of stake a bet` : ''}. Book so far: ${usd(tn.book.pnl, true)} over ${tn.book.trips} trade${tn.book.trips === 1 ? '' : 's'}.` : '';
    const body = figs + trendP + days + paperP
      + sect('Paper tournament', tnSub, tnRows)
      + sect('What it has learned', 'After every session the loop rewrites a playbook for that kind of market from its verdicts. A rewrite is tried on new sessions and kept only if more of its ideas reach the gate.', pbRows)
      + sect('Where it looks next', 'A free scan of every market for prices that disagree with how they settle, after fees. Leads steer research; they still have to pass on unseen data.', scout)
      + sect('Ideas our pipeline killed', 'Dropped because of missing data or features, not because the market said no. This is the fix list.', fixes)
      + sect('Data it asked for', 'Crypto ideas that died for lack of data start a collection, and the idea is re-tested once the data exists (autopilot on, at most once each).', reqs)
      + (pol && pol.evolved ? `<p class="rsi-last">Finalist policy evolved from your history${pol.base_score != null && pol.score != null ? ` · score ${pol.base_score} → ${pol.score}` : ''}.</p>` : '');
    const open = !!host.querySelector('details.rsidisc[open]');
    const focused = !!host.querySelector('details.rsidisc > summary:focus');
    const inner = [...host.querySelectorAll('details.loop-pb')].map((d) => d.open);
    host.innerHTML = `<details class="rsidisc loop"${open ? ' open' : ''}>
      <summary class="rsidisc-cap"><b class="rsi-badge">RSI</b><span class="rsidisc-t">Is research getting better?</span>${tag}${delta ? `<span class="rsidisc-delta">${delta} reach the gate</span>` : ''}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
      <div class="rsidisc-body">${body}</div>
    </details>`;
    host.querySelectorAll('details.loop-pb').forEach((d, i) => { if (inner[i]) d.open = true; });
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
    const gates = ['Bootstrap CI', 'PSR', 'DSR · deflated by trial count', 'Placebo / null', 'LORD++ FDR budget', 'Purged walk-forward', 'Benjamini–Hochberg'];
    return `<details class="pipefig">
      <summary class="pipecap"><span class="pipecap-t">Research process</span><span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
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
      : `Usually about ${usd(v)} (${basis}).`;
  }
  async function viewResearch() {
    const me = S.me;
    const DEMO_PROMPT = "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances";
    shell('/research', '', loading(320));  // switch pages at once; the model list can be slow
    const mdl = await api('/api/models').catch(() => ({ models: [], default: '' }));
    const modelOpts = (mdl.models || []).map((m) => `<option value="${esc(m.key)}"${m.key === mdl.default ? ' selected' : ''}${m.available === false ? ' disabled' : ''}>${esc(m.label)}${m.available === false ? ' (access pending)' : ''}</option>`).join('');
    shell('/research', '', `
      <div class="research-page"><h1 class="page">Research</h1>${S.me.user && !S.me.user.autopilot ? `<p class="research-ap">Rather not write ideas yourself? <button type="button" data-research-ap>Turn on autopilot</button> and it picks ideas and researches them on its own, on paper.</p>` : ''}<div class="research-work"><div id="active-research"></div><div id="rsimo"></div></div><details class="research-create" id="research-create"${new URLSearchParams(location.search).get('new') === '1' ? ' open' : ''}><summary class="btn primary">New session</summary><div class="research-compose"><form class="panel dispatch" id="dispatch">

        ${me.needs_card ? `<div class="notice" role="status">${ICON.warn}<span>Add a payment method to start researching. Your $${me.free_bonus} in free credits unlock the moment a card is on file — you won't be charged until they run out. <a href="/billing">Add a card →</a></span></div>` : ''}
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
          <button type="button" class="chip ex" data-ex="${esc(DEMO_PROMPT)}" title="Todd's random walk: fills the idea without starting a session">Use demo idea</button>
          <button class="btn primary go" type="submit" ${me.needs_card ? 'aria-disabled="true"' : ''}>Start session</button>
        </div>
        <p class="hint go-cost" id="rcost" hidden></p>
        <div id="dflash"></div>
        <p class="hint" id="rf-hint">A session takes a few minutes and keeps running if you leave this page.</p>
      </form>${pipelineFigure()}</div></details><section class="research-history sect"><div class="sect-head research-archive-heading"><h2>Recent sessions <span id="rcount"></span></h2><div class="rengine" id="rengine"><section class="research-total" aria-label="All sessions, including active"><h3>All sessions</h3><dl class="figures measure" id="rfigs"></dl><dl class="figures measure research-status" id="research-status"></dl></section></div></div>
        <div class="run-columns" aria-hidden="true"><span>Hypothesis / session</span><span>Market</span><span>Created</span><span>Outcome</span></div><div id="flash"></div><div class="runs" id="runs">${loading(70)}${loading(70)}</div></section></div>`);
    const form = root.querySelector('#dispatch');
    wireMarketPicker(form);
    const ta = form.querySelector('textarea[name=prompt]');
    root.querySelectorAll('[data-ex]').forEach((b) => (b.onclick = () => { ta.value = b.dataset.ex; ta.focus(); }));
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
        const own = !!est && est.yours != null;
        const v = !est ? null : own ? est.yours : (est.typical || {})[(msel && msel.value) || mdl.default];
        rc.hidden = v == null;
        rc.textContent = v == null ? '' : sessionCostLine(+v, !!(rf && rf.checked), own);
      };
      if (msel) msel.addEventListener('change', sync);
      api('/api/research/estimate').then((d) => { est = d; }, () => { est = null; }).then(sync);
    })();
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
      // All-time totals from the server; the 50 newest runs undercount a busy autopilot.
      const tried = d.totals ? d.totals.tried : d.runs.reduce((a, r) => a + (r.hypotheses_tried || 0), 0);
      const passed = d.totals ? d.totals.passed : d.runs.reduce((a, r) => a + (r.strategies_passed || 0), 0);
      const running = d.counts.research_running, queued = d.counts.research_queued;
      root.querySelector('#research-status').innerHTML = fig('Running', running) + fig('Queued', queued);
      root.querySelector('#rfigs').innerHTML = fig('Passed' + glo('gate'), passed) + fig('Tested', tried);
      root.querySelector('#rfigs').setAttribute('title', tried ? `${pct(passed / tried, false)} of ${num(tried)} tested` : 'No strategies tested');
      renderResearchLoop(root.querySelector('#rsimo'), d.policy, tried);
      const active = d.runs.find((r) => r.status === 'running') || d.runs.find((r) => r.status === 'queued') || d.runs.find((r) => r.status === 'paused');
      root.querySelector('#active-research').innerHTML = active ? `<section class="active-research active-${esc(active.status)}">
        <div class="active-head"><h2 class="active-prompt" title="${esc(sessionTitle(active))}">${esc(sessionTitle(active))}</h2></div>
        <div class="active-meta"><div class="active-session"><span class="active-state">${active.status === 'paused' ? 'Paused' : active.status === 'queued' ? 'Queued' : 'Researching'}</span><b>Session ${esc(active.id)}</b></div><span>${esc(marketShort(active.market))}</span>${active.started_at ? `<span>Started ${when(active.started_at)}</span>` : ''}</div>
        <aside class="active-aside"><a class="active-open btn primary" href="/research/${active.id}">Open session <span aria-hidden="true">→</span></a><dl class="active-foot"><div><dt>Tested</dt><dd>${active.hypotheses_tried || 0}</dd></div><div><dt>Passed</dt><dd>${active.strategies_passed || 0}</dd></div></dl></aside>
      </section>` : '';
      const history = active ? d.runs.filter((r) => r.id !== active.id) : d.runs;
      // The seeded example is listed but isn't the user's: it doesn't count as a session of theirs.
      const own = history.filter((r) => !r.example).length;
      root.querySelector('#rcount').textContent = own ? String(own) : '';
      root.querySelector('#runs').innerHTML = history.length ? history.map(runRow).join('')
        : `<div class="empty"><h3>${active ? 'No earlier sessions' : 'No sessions yet'}</h3></div>`;
    };
    await load();
    poll(load, 5000);
  }
  // What a run has taken from credits (the ledger rows billed to it, `spent_usd` from the server).
  // A run still going says "so far"; a finished one states its cost.
  const runLive = (r) => r.status === 'running' || r.status === 'queued' || r.status === 'paused';
  const runSpent = (r) => r.spent_usd == null ? '' : `${runLive(r) ? 'Spent so far' : 'Cost'}: ${usd(r.spent_usd)}`;
  function runRow(r) {
    const state = r.status === 'running' ? 'Researching'
      : r.status === 'queued' ? 'Waiting'
      : r.status === 'succeeded' ? `<span class="${r.strategies_passed ? 'gain' : ''}"><span class="run-ratio" aria-label="${esc(r.strategies_passed)} of ${esc(r.hypotheses_tried)}"><b class="run-passed">${r.strategies_passed}</b><span aria-hidden="true">/</span><b class="run-tested">${r.hypotheses_tried}</b></span> <span class="run-denominator">passed</span></span>`
      : r.status === 'paused' ? 'Paused'
      : r.status === 'cancelled' ? 'Cancelled' : '<span class="loss">Failed</span>';
    // status band: a thin color rule so passed/void/failed reads at a glance
    const band = r.status === 'succeeded' ? (r.strategies_passed ? 'ok' : 'void') : r.status === 'failed' ? 'fail' : r.status === 'cancelled' ? 'void' : 'live';
    return `<a class="run-card ${band}" href="/research/${r.id}">
      <span class="run-identity"><span class="run-title" title="${esc(sessionTitle(r))}"><b>${esc(sessionTitle(r))}</b>${r.example ? ' ' + EXAMPLE_TAG : ''}${r.error ? `<span class="run-error">${esc(r.error)}</span>` : ''}</span><span class="run-meta-group"><span class="run-id">Session ${esc(r.id)}</span><span class="run-meta"><span class="vh">Market </span>${esc(marketShort(r.market))}${r.example ? ' \u00b7 ' + EXAMPLE_NOTE : r.spent_usd != null ? ' \u00b7 ' + runSpent(r) : ''}</span><span class="run-when"><span class="vh">Created </span>${when(r.created_at)}</span></span></span><span class="run-state"><span class="vh">Outcome </span>${state}</span></a>`;
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
      <div class="hx-head"><b class="say-title">${esc(title)}</b><span class="hx-stamp pending" data-stamp>Testing</span></div>
      ${d.thesis ? `<span class="say-sub">${esc(d.thesis)}</span>` : ''}${stat}
      ${home ? `<details class="hx-more"><summary>Method &amp; specification</summary><div class="hx-body">${home}</div></details>` : ''}
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
        const label = dd.status === 'passed' ? 'Passed' : dd.status === 'rejected' ? 'Rejected' : 'Void';
        li.classList.remove('lane-action'); li.classList.add('lane-' + cls);
        stampEl.className = 'hx-stamp ' + cls;
        // A passed hypothesis opens its strategy through the title. The verdict is
        // status text; one destination does not need three repeated links.
        const href = cls === 'pass' && dd.strategy_id ? `/strategies/${dd.strategy_id}` : '';
        stampEl.textContent = label;
        if (href) {
          const t = li.querySelector('.say-title');
          if (t) t.innerHTML = `<a class="hx-titlelink" href="${href}">${esc(title)}</a>`;
        }
        const rest = strip(e2.message, /^(PASSED|VOID|FAILED|REJECTED)(\s*\(challenger\))?\s*[-–]\s*/);
        const tail = rest.indexOf(':') >= 0 ? rest.slice(rest.indexOf(':') + 1).trim() : '';
        reviewEl.hidden = false;
        reviewEl.insertAdjacentHTML('beforeend', `<div class="hx-verdict"><span class="hx-tag ${cls}">Gatekeeper</span>${tail ? `<span class="hx-vtext">${esc(tail)}</span>` : ''}${statGrid(dd.stats)}</div>`);
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
  // Run state and source-event age are reported by the observatory above the log.
  function runFeed(section) {
    const log = section.querySelector('.log');
    const jump = section.querySelector('.jumplatest');
    let unseen = 0, first = true, appended = 0, stateSeen = false;
    const cards = new Map();   // hypothesis title -> card controller (most recent wins on a title clash)
    let think = null;          // the currently-open thinking card, if any
    const atBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 60;
    const toLatest = () => { log.scrollTop = log.scrollHeight; unseen = 0; jump.hidden = true; };
    log.addEventListener('scroll', () => { if (atBottom()) { unseen = 0; jump.hidden = true; } });
    jump.onclick = toLatest;
    const sealThink = () => { if (think) { think.seal(); think = null; } };
    const add = (el) => { if (!first) el.classList.add('in'); log.appendChild(el); appended++; };

    function dispatch(ev) {
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
      state(st) {
        // A saved completed run reads as a document. A live run keeps its
        // existing scroll viewport on completion so reading/jump state survives.
        if (!stateSeen) section.classList.toggle('is-complete', st === 'done');
        stateSeen = true;
        if (st === 'done') sealThink();
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
  const RSI_STAGES = [['explore', 'Explore'], ['backtest', 'Backtest'], ['gate', 'Validate'], ['dream', 'Refine']];
  // event kind -> [loop stage, human phase label]. New kinds the backend adds just fall through.
  const RSI_PHASE = {
    'run-start': ['explore', 'Starting up'], 'data-loaded': ['explore', 'Data loaded'],
    'proposing': ['explore', 'Proposing hypotheses'], 'developing-thesis': ['explore', 'Developing a thesis'],
    'thinking': ['explore', 'Thinking it through'], 'step': ['explore', 'Working'],
    'hypothesis': ['backtest', 'Backtesting a hypothesis'], 'challenger': ['backtest', 'Challenging the result'],
    'gating': ['gate', 'Gating on unseen data'], 'verdict': ['gate', 'Recording the verdict'],
    'dreaming': ['dream', 'Refining the search policy'],
  };
  const prettyKind = (k) => String(k || '').replace(/[-_]/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  // Liberal id/parent extraction so the tree survives whatever the backend names its lineage fields.
  const hypId = (d) => d.hyp_id != null ? d.hyp_id : d.id != null ? d.id : d.node_id != null ? d.node_id : null;
  const hypParent = (d) => d.parent_id != null ? d.parent_id : d.parent != null ? d.parent : d.parent_hyp_id != null ? d.parent_hyp_id : d.parent_title != null ? d.parent_title : null;

  function rsiObservatory(host) {
    host.innerHTML = `
      <details class="rsi-progress" open><summary class="rsiobs-head"><h2>Research progress</h2>
        <span class="rsiobs-live is-wait" data-live><span data-livetext>Spinning up…</span></span>${ICON.chev}</summary>
      <ol class="rsi-labels" aria-label="Research cycle: explore, backtest, validate, refine, then repeat">${RSI_STAGES.map(([s, l]) => `<li class="rsi-lab" data-stage="${s}">${l}</li>`).join('')}</ol>
      <p class="rsiobs-phase" data-phase>Waiting for the agent to start.</p>
      <p class="rsiobs-phase rsiobs-wait" data-wait hidden></p>
      <figure class="rsiobs-tree" data-tree hidden><figcaption>Discovery tree</figcaption>
        <div class="rsiobs-treewrap"><svg class="rsiobs-treesvg" data-treesvg></svg></div></figure></details>`;

    const liveWrap = host.querySelector('[data-live]'), liveText = host.querySelector('[data-livetext]');
    const phaseEl = host.querySelector('[data-phase]'), treeFig = host.querySelector('[data-tree]'), treeSvg = host.querySelector('[data-treesvg]');
    const progress = host.querySelector('.rsi-progress');
    const labs = {};
    RSI_STAGES.forEach(([s]) => { labs[s] = host.querySelector(`.rsi-lab[data-stage="${s}"]`); });
    const fired = new Set();
    let stage = null, lastAt = Date.now(), runState = 'queued', initialUpdate = true, wait = null, waitAt = 0;
    const waitEl = host.querySelector('[data-wait]');
    let waitHidPhase = false;
    const waitNow = () => (wait ? { ...wait, seconds: wait.seconds + Math.round((Date.now() - waitAt) / 1000) } : null);
    const nodes = [], byId = new Map(), byTitle = new Map(); let hasLineage = false, lastCount = -1;

    function paintStages() {
      const live = runState === 'running';
      RSI_STAGES.forEach(([s]) => {
        const on = live && s === stage, done = !on && fired.has(s);
        labs[s].classList.toggle('is-active', on); labs[s].classList.toggle('is-done', done);
        if (on) labs[s].setAttribute('aria-current', 'step'); else labs[s].removeAttribute('aria-current');
      });
    }

    function paintLive() {
      host.classList.remove('is-quiet');
      const w = ['queued', 'running'].includes(runState) ? waitNow() : null, late = !!(w && w.overdue);
      waitEl.hidden = !late;
      if (late) waitEl.textContent = runWaitLine(w);
      // An overdue queued run's wait line says what "Waiting for the agent to start." said, and more.
      if (late && runState === 'queued') { phaseEl.hidden = true; waitHidPhase = true; }
      else if (waitHidPhase) { waitHidPhase = false; phaseEl.hidden = !['queued', 'running', 'paused'].includes(runState); }
      if (late && runState === 'queued') { liveWrap.className = 'rsiobs-live is-stall'; liveText.textContent = 'Waiting ' + waitSpan(w.seconds); return; }
      if (late) { host.classList.add('is-quiet'); liveWrap.className = 'rsiobs-live is-stall'; liveText.textContent = 'Silent ' + waitSpan(w.seconds); return; }
      if (runState === 'paused') { liveWrap.className = 'rsiobs-live is-paused'; liveText.textContent = 'Paused'; return; }
      if (runState === 'queued') { liveWrap.className = 'rsiobs-live is-wait'; liveText.textContent = 'Queued'; return; }
      if (runState !== 'running') { liveWrap.className = 'rsiobs-live is-done'; liveText.textContent = runState === 'succeeded' ? 'Finished' : runState === 'cancelled' ? 'Cancelled' : 'Stopped'; return; }
      const secs = Math.max(0, Math.round((Date.now() - lastAt) / 1000)), stalled = secs >= 75;
      host.classList.toggle('is-quiet', stalled);
      liveWrap.className = 'rsiobs-live' + (stalled ? ' is-stall' : '');
      const age = secs < 60 ? `${secs}s` : secs < 3600 ? `${Math.floor(secs / 60)}m` : `${Math.floor(secs / 3600)}h`;
      liveText.textContent = secs < 6 ? 'Just updated' : `Last event ${age} ago`;
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
        const firstUpdate = initialUpdate;
        initialUpdate = false;
        runState = state || runState;
        (events || []).forEach((ev) => {
          const d = ev.data || {};
          lastAt = Date.parse(ev.created_at) || Date.now();   // newest event's own clock drives liveness
          let ph = RSI_PHASE[ev.kind];
          if (!ph && /^(Dreaming:|Research policy evolved:)/.test(ev.message || '')) ph = ['dream', ev.message.split(':')[0]];
          if (ph) { stage = ph[0]; fired.add(stage); phaseEl.textContent = ph[1]; phaseEl.hidden = ev.kind === 'step'; }
          else if (ev.kind && ev.kind !== 'done') { phaseEl.textContent = prettyKind(ev.kind); phaseEl.hidden = false; }  // unknown kind: keep stage lit, show a readable label
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
        if (!['queued', 'running', 'paused'].includes(runState)) {
          phaseEl.hidden = true;
          if (firstUpdate) progress.open = false;
        }
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
    shell('/research', '<div class="run-header"><div id="runboard">' + boardTitle('Research run') + '</div><span id="runact"></span></div><dl class="figures measure" id="runfigs" style="margin-top:14px"></dl><p class="stale-note" id="run-stale" role="status"></p>', `
      <div id="flash"></div>
      <section class="run-artifacts" id="run-artifacts" hidden></section>
      <div id="rsibox"></div>
      <div id="rsiobs" class="rsiobs"></div>
      <details class="run-history" id="run-history" open><summary class="section-head"><h2>Agent log</h2>${ICON.chev}</summary>
        <div class="runfeed" id="runfeed"><ol class="log stream" id="log" role="log" aria-label="Agent reasoning log"><li class="log-empty" data-empty>Waiting for the first event.</li></ol><button class="jumplatest" id="jumplatest" type="button" hidden>new ↓</button></div></details>`);
    let after = 0, tried = 0, runActive = true, loaded = false;
    const stream = runFeed(root.querySelector('#runfeed'));
    const obs = rsiObservatory(root.querySelector('#rsiobs'));
    const load = async (cfg) => {
      const d = await api(`/api/runs/${id}?after=${after}`, undefined, cfg);
      const r = d.run;
      const active = r.status === 'running' || r.status === 'queued' || r.status === 'paused';
      runActive = active;
      root.querySelector('#runboard').innerHTML = boardTitle(sessionTitle(r), `${esc(marketShort(r.market))} \u00b7 ${dirLabel(r.direction)}${r.example ? ' \u00b7 ' + EXAMPLE_NOTE : ''}`);
      const started = r.started_at ? Date.parse(r.started_at) : null;
      const end = r.finished_at ? Date.parse(r.finished_at) : Date.now();
      const late = r.wait && r.wait.overdue ? r.wait : null;
      const statusText = late ? (late.state === 'queued' ? 'Waiting ' : 'Silent ') + waitSpan(late.seconds)
        : r.status === 'queued' ? 'Waiting'
        : r.status === 'paused' ? 'Paused'
        : r.status === 'running' ? 'Researching'
        : r.status === 'succeeded' ? 'Done' : r.status === 'cancelled' ? 'Cancelled' : 'Failed';
      root.querySelector('#runfigs').innerHTML =
        fig('Status', statusText) +
        fig('Time', started ? Math.max(0, Math.round((end - started) / 60000)) + ' min' : '—') +
        (r.spent_usd != null ? fig(active ? 'Spent so far' : 'Cost', usd(r.spent_usd), { small: 'from your credits' }) : '') +
        fig('Hypotheses', r.hypotheses_tried || tried) + fig('Passed', r.strategies_passed == null ? '—' : r.strategies_passed);
      const artifacts = root.querySelector('#run-artifacts'), strategies = d.strategies || [];
      const focusedArtifact = artifacts.querySelector('a:focus')?.getAttribute('href');
      artifacts.hidden = !strategies.length;
      const artifactHtml = strategies.length ? `<div class="sect-head"><h2>Strategies <span class="section-count">${strategies.length}</span></h2></div>${strategyTable(strategies.map(s => strategySlip(s)).join(''), false)}` : '';
      if (artifacts.innerHTML !== artifactHtml) artifacts.innerHTML = artifactHtml;
      if (focusedArtifact) Array.from(artifacts.querySelectorAll('a')).find(a => a.getAttribute('href') === focusedArtifact)?.focus({ preventScroll: true });
      if (!loaded && !active) root.querySelector('#run-history').open = false;
      loaded = true;
      const rsibox = root.querySelector('#rsibox');
      if (rsibox && d.rsi) {
        const expanded = !!rsibox.querySelector('details[open]');
        const focused = !!rsibox.querySelector('details > summary:focus');
        const delta = (d.rsi.base_score != null && d.rsi.score != null)
          ? `<span class="rsi-score">${d.rsi.base_score} <span class="rsi-arrow">→</span> ${d.rsi.score}</span>` : '';
        // The adopted policy is arbitrary agent-evolved Python with no structured decision record
        // behind it, so a raw-source dump isn't inspection — the human "What it changed" summary
        // and the generalization-score delta below are the faithful, readable account.
        rsibox.innerHTML = `<details class="rsidisc"${expanded ? ' open' : ''}><summary class="rsidisc-cap">Research policy ${d.rsi.evolved ? '<span class="rsi-tag">Evolved</span>' : '<span class="rsi-tag quiet">Self-tuning</span>'}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary><div class="rsidisc-body">
          ${d.rsi.evolved
            ? `<p>This agent <b>rewrote its own search policy</b> from your history — and it beats the default.</p>
               ${d.rsi.summary ? `<p class="rsi-what"><b>What it changed:</b> ${esc(d.rsi.summary)}</p>` : ''}
               <p class="rsi-last">Generalization score ${delta}${d.rsi.evolved_at ? ' · adopted ' + when(d.rsi.evolved_at) : ''} <span class="rsi-note">(higher = catches more real out-of-sample winners, scored over shuffled orderings so it can't overfit)</span></p>`
            : `<p>The agent is <b>self-tuning</b>: after each research cycle it dreams up new search strategies and keeps one only if it beats the current policy on your own history (scored over shuffled orderings, so it can't overfit).</p>
               ${d.rsi.last_dream ? `<p class="rsi-last"><b>Last check${d.rsi.last_dream_at ? ' · ' + when(d.rsi.last_dream_at) : ''}:</b> ${esc(d.rsi.last_dream)}</p>` : `<p class="rsi-last">No check yet. The first one runs at the end of a session, once at least ${d.rsi.min_history || 12} ideas have been tested.</p>`}`}
          </div></details>`;
        if (focused) rsibox.querySelector('summary').focus({ preventScroll: true });
      }
      runControls(root.querySelector('#runact'), id, r.status, load);
      d.events.forEach((ev) => { after = Math.max(after, ev.id); if (ev.kind === 'hypothesis') tried++; });
      stream.push(d.events);
      stream.state(active ? r.status : 'done');
      obs.push(d.events, r.status, r);
      if (!active) clearTimers();
    };
    await load();
    if (runActive) poll(load, 2000, 'run-stale');
  }
  const DIR_BRIEF = (k) => ((S.me.directions.find((d) => d.key === k)) || { brief: '' }).brief;

  // ---------- strategies ----------
  async function viewStrategies() {
    const q = new URLSearchParams(location.search);
    const f = { status: q.has('status') ? q.get('status') : '', market: q.get('market') || '', q: q.get('q') || '', deployed: q.get('deployed') === '1' ? '1' : '' };
    shell('/strategies', `<div class="board-title strategy-heading"><h1 class="page">Strategies</h1><details class="strategy-summary"><summary><span id="strategy-passrate">Research results</span> ${ICON.chev}</summary><dl class="figures measure" id="sfigs"></dl></details></div>`, `
      <div class="section-head filters stratfilters">
        <div class="chips" role="group" aria-label="Status">${[['', 'Kept'], ['passed', 'Passed'], ['backtest-only', 'Backtest only'], ['failed', 'Void'], ['rejected', 'Rejected']].map(([v, l]) => `<button class="chip" data-f="status" data-v="${v}"${v ? '' : ' title="Passed and backtest-only strategies"'} aria-pressed="${f.status === v}">${l}</button>`).join('')}
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
        slipsEl.innerHTML = loadFail(e.message);
        slipsEl.querySelector('[data-retry]').onclick = () => load();
        return;
      }
      const counts = d.counts || {}, total = counts.total || 0, c = (st) => counts[st] || 0;
      root.querySelector('#sfigs').innerHTML = fig('Passed' + glo('passed'), c('passed')) + fig('Void on unseen data' + glo('void'), c('failed')) + fig('Rejected in testing' + glo('rejected'), c('rejected')) +
        fig('Pass rate', total ? pct(c('passed') / total, false) : '—');
      root.querySelector('#strategy-passrate').textContent = total ? `${pct(c('passed') / total, false)} pass rate` : 'Research results';
      const kept = total - c('failed') - c('rejected');
      root.querySelectorAll('[data-f="status"]').forEach((b) => { const v = b.dataset.v; b.textContent = v ? `${CLABEL[v]} (${c(v)})` : `Kept (${kept})`; });
      const depChip = root.querySelector('[data-toggle="deployed"]');
      if (depChip && counts.deployed != null) depChip.textContent = `Deployed (${counts.deployed})`;
      if (!d.matched) {
        const noneKept = total && !kept && !f.status && !f.q && !f.market && !f.deployed;  // a new user's default view, not a filter miss
        // With autopilot on, the empty list says it is on instead of asking for a session (not "researching":
        // the autopilot panel may be reporting a stale check-in or a billing pause).
        const apOn = !!(S.me && S.me.user && S.me.user.autopilot);
        slipsEl.innerHTML = `<div class="empty"><h3>${noneKept ? 'No strategy has passed yet' : total ? 'No matching strategies' : 'No strategies yet'}</h3>${noneKept ? `<p>Most ideas fail their tests; the ones that pass land here.${apOn ? ' Autopilot keeps researching on its own.' : ''}</p>` : !total && apOn ? '<p>Autopilot is on. The strategies it finds will land here.</p>' : ''}${total && !noneKept ? '' : `${apNudge('Rather not write ideas yourself?', 'and it researches on its own, on paper.')}${apOn ? '<a class="btn" href="/research">See its research</a>' : '<a class="btn" href="/research?new=1">New session</a>'}`}</div>`;
        return;
      }
      const list = d.strategies, reg = registry(list.map((s) => s.equity));
      const anyPassed = list.some(bulkDeployable);
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

  // What the strategy has actually done since it was deployed, per mode (live, demo, paper), from
  // its deployments' realized P&L. The page otherwise shows only the backtest.
  function realRecord(s) {
    // What the same trades would have made at the unseen-data backtest's average, scaled to each
    // deployment's stake, so "is it doing what the test said?" has an answer beside the real P&L.
    const oos = s.out_of_sample, stake = +s.stake;
    // A paused deployment (often paused automatically, and the bell links here) says so and why.
    const pausedLine = (ds) => {
      const p = ds.find((d) => d.status === 'paused');
      return p ? `<p class="real-paused"><b>Paused</b>${p.status_reason ? ' ' + esc(p.status_reason) : ''} <a href="/deploy">Resume or remove it on Deploy</a></p>` : '';
    };
    const pace = (ds, n) => {
      if (!n || !oos || !(+oos.trades > 0) || !(stake > 0)) return '';
      const per = (+oos.pnl || 0) / +oos.trades;
      const exp = ds.reduce((a, d) => a + (+d.closed_trades || 0) * per * ((+d.stake || stake) / stake), 0);
      return `<p class="sub-fig real-pace">At the backtest's unseen-data pace, ${n} trade${n === 1 ? '' : 's'} would have made ${usd(exp, true)}${n < 10 ? ' · too few trades to judge yet' : ''}</p>`;
    };
    const order = ['live', 'demo', 'paper'], label = { live: 'Live', demo: 'Demo', paper: 'Paper' }, cls = { live: 'live', demo: 'dep', paper: '' };
    const lines = order.map((mode) => {
      const ds = (s.deployments || []).filter((d) => d.mode === mode);
      if (!ds.length) return '';
      const pnl = ds.reduce((a, d) => a + (+d.realized_pnl || 0), 0), n = ds.reduce((a, d) => a + (+d.closed_trades || 0), 0);
      const open = ds.reduce((a, d) => a + (+d.open_positions || 0), 0);
      const since = ds.map((d) => d.created_at).filter(Boolean).sort()[0];
      return `<p><span class="mk ${cls[mode]}">${label[mode]}</span> ${n ? `${money(pnl)} realized over ${n} closed trade${n === 1 ? '' : 's'}` : 'No closed trades yet'}${open ? ` · ${open} open` : ''}${since ? ` · deployed ${when(since)}` : ''}</p>${pace(ds, n)}${pausedLine(ds)}`;
    }).join('');
    return lines ? `<section class="real-record" aria-label="Since deploying"><h3 class="paper-h">Since deploying</h3>${lines}</section>` : '';
  }
  async function viewStrategy(id) {
    shell('/strategies', boardTitle('Strategy'), loading(420));
    const s = await api('/api/strategies/' + id);
    const perpetual = isPerpetual(s), restricted = researchOnly(s);
    const filed = (() => { try { return new Date(s.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); } catch (e) { return ''; } })();
    const ins = s.in_sample || {}, oos = s.out_of_sample;
    const figsFor = (r) => fig('Out-of-sample P&L', r.out_of_sample ? usd(r.out_of_sample.pnl, true) : '—', { v: r.out_of_sample && r.out_of_sample.pnl, small: r.out_of_sample ? `${r.out_of_sample.trades} trades` : 'Not tested out-of-sample' }) +
      fig('In-sample P&L', usd(r.in_sample.pnl, true), { v: r.in_sample.pnl, small: `${r.in_sample.trades} trades` }) +
      fig('Return on capital', r.out_of_sample ? pct(r.out_of_sample.roi) : '—', { small: r.capital ? `$${fmt0.format(r.capital)} at risk at most` : '' }) +
      fig('Run trials', s.hypotheses_tried != null ? num(s.hypotheses_tried) : '—', { small: s.hypotheses_tried == null ? 'Trial count unavailable.' : '' });
    // A strategy from the seeded example session says so here too, as the lists and its run page do.
    root.querySelector('.board-title').outerHTML = `<div class="board-title strategy-pagehead"><h1 class="page">${esc(s.title)}</h1><p class="deck"><span>${esc(serial(s.id))} · ${esc(marketShort(s.market))} · ${esc(dirLabel(s.direction))}</span>${filed ? `<span>Filed ${esc(filed)}</span>` : ''}${mark(s.status)}${researchBadge(s)}${s.example ? `${EXAMPLE_TAG}<span class="example-note">${EXAMPLE_NOTE}</span>` : ''}</p></div>`;
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
    const gatesHtml = (gs) => gs && gs.length ? `<ul class="gates">${gs.map((g) => `<li class="${g.ok ? 'ok' : 'no'}">${g.ok ? ICON.check : ICON.cross}<span>${esc(g.name)}<small>needs ${esc(g.threshold)}</small></span><span class="v">${typeof g.value === 'number' && /\$|drawdown|money/i.test(g.name + g.threshold) ? usd(g.value) : esc(g.value == null ? '—' : g.value)}</span></li>`).join('')}</ul>` : '<p class="hint">No gate results recorded for this strategy. Gates only run for finalists that made money in testing.</p>';
    const trades = (s.recent_trades || []).length ? `<table class="table stack"><thead><tr><th>Opened</th><th>Contract</th><th>Side</th><th class="num">Entry${perpetual ? ' (USD)' : ''}</th><th class="num">Exit${perpetual ? ' (USD)' : ''}</th><th class="num">P&amp;L</th></tr></thead><tbody>
        ${s.recent_trades.map((t) => `<tr><td data-lab="Opened">${esc(new Date(t.opened.replace('Z', ':00Z')).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }))}</td><td class="tick" data-lab="Contract">${esc(t.ticker)}</td><td data-lab="Side">${esc(t.side.toUpperCase())} ×${t.qty}</td><td class="num" data-lab="Entry">${tradePrice(t.entry, perpetual)}</td><td class="num" data-lab="Exit">${tradePrice(t.exit, perpetual)} <small class="hint">${esc(t.reason)}</small></td><td class="num ${tone(t.pnl)}" data-lab="P&amp;L">${usd(t.pnl, true)}</td></tr>`).join('')}
      </tbody></table>` : '<p class="hint">No unseen trades.</p>';
    const activeDeps = restricted ? [] : s.deployments.filter((d) => d.status !== 'stopped');
    const kUrl = marketKalshiUrl(s.market);
    const mktLink = kUrl ? `<a href="${kUrl}" target="_blank" rel="noopener">${esc(marketLabel(s.market))} ↗</a>` : esc(marketLabel(s.market));
    // ---- the strategy dossier, composed as a research paper (abstract → mechanism →
    // methodology → results → verdict). Each section renders only when it has content, so a
    // pre-pipeline strategy with no ledger row falls back to its rule + backtest + plain verdict.
    const rp = researchPaper(s.experiment);
    const hasExp = !!s.experiment;
    const abResult = oos
      ? `On out-of-sample data, it ${+oos.pnl >= 0 ? 'returned ' + usd(oos.pnl) : 'lost ' + usd(Math.abs(oos.pnl))} over ${num(oos.trades)} trade${oos.trades === 1 ? '' : 's'}${s.hypotheses_tried ? (s.status === 'passed' ? `. Selected from ${num(s.hypotheses_tried)} hypotheses tested this run` : `. One of ${num(s.hypotheses_tried)} hypotheses tested this run`) : ''}.`
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
      + `<div class="paper-sub">${perpetual ? '<h4 class="paper-h">Perpetual research scenario</h4>' : hasExp ? '<h4 class="paper-h">Backtest &amp; Kalshi demo replay</h4>' : ''}
          ${hasExp ? '<p class="rp-sub" style="margin-top:0">These are the agent\'s own in-sample/replay numbers. The in-sample column is optimistically biased — the rule was fit on exactly this data — so trust the held-out validation-window evidence above, not the column below.</p>' : ''}
          <div id="sheet-results">
            <div id="equity-wrap">${s.equity ? equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from, null, { width: chartWidth() }) : ''}</div>
            <div class="split"><div><h4>In-sample</h4>${metricRows(ins)}</div><div><h4>Out-of-sample</h4>${metricRows(oos)}</div></div>
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
        passed: ['sig', 'armed', 'Not validated (record missing)', 'Marked passed, but no statistical-gatekeeper record (pre-registration, validation, holdout) can be found for it — so the backtest figures on this page are in-sample only, not held-out evidence. Treat it as unvalidated; the row is being reclassified to backtest-only.'],
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
            ${!hasExp ? `<div class="legacy-verdict">${verdictBody}</div>` : ''}
            <dl class="figures measure" id="figs">${figsFor(s)}</dl>
            ${restricted ? '' : realRecord(s)}
            ${s.shared_from ? `<div class="paper-byline"><span class="mk shared">${ICON.share}Shared by ${esc(s.shared_from)}</span></div>` : ''}
            <section class="paper-abstract" aria-label="Strategy hypothesis">
              <p class="paper-ab">${mdLite(s.thesis)}</p>
              <details class="saved-result"><summary>Saved result</summary><p class="paper-ab-result">${abResult}</p>${s.hypotheses_tried != null ? '<p class="hint">More trials increase the chance of false positives.</p>' : ''}</details>
            </section>
            <div class="paper-body">
              ${paperSec('Mechanism &amp; hypothesis', rp.mechanism)}
              ${paperSec(hasExp ? 'Results' : 'Backtest results', resultsBody)}
              ${paperSec('Methodology', methodologyBody)}
              ${hasExp ? paperSec('Verdict', verdictBody) : ''}
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
              return `${lead}${xs.length} open position${xs.length === 1 ? '' : 's'} at cost ${usd(xs.reduce((a, p) => a + p.cost, 0))}${marked.length ? ` · unrealized ${money(unreal)} (est., mark-to-market on the current bid)` : ' · awaiting first mark'}.`;
            };
            // A list, not a five-column table: in the sidebar the table clipped everything after Position.
            return `<section class="panel"><h3>Holding right now</h3>
            <ul class="holdlist">${s.holdings.map((p) => `<li><div class="tick">${esc(p.ticker)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : p.mode === 'demo' ? '<span class="mk dep">Demo</span>' : ''}</div>
              <div class="holdlist-figs"><b>${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(p.entry_price)}</b><span>Cost ${usd(p.cost)}</span><span>Unreal. ${p.unrealized == null ? '—' : money(p.unrealized)}</span><span>Settles ${clock(p.market_close_time)}</span></div></li>`).join('')}</ul>
            <p class="hint" style="margin-top:8px">${books.map(bookLine).join('<br>')}</p></section>`;
          })() : ''}
          <section class="panel"><h3>${restricted ? 'Research only' : 'Deploy'}</h3>
            ${!restricted && s.deployments.length ? `<div class="strategy-deployments"><p class="hint">${s.deployments.map((d) => `#${d.id} · ${esc(d.mode)} · ${esc(d.status)}`).join('<br>')}</p><a class="btn${activeDeps.length ? ' primary' : ''}" href="/deploy">View deployments</a></div>` : ''}
            ${canDeploy ? `<div style="display:grid;gap:10px">
                ${s.status !== 'passed' ? `<div class="notice bad">${ICON.warn}<span>${s.status === 'failed' ? 'Void: it failed the unseen-data gate.' : `Rejected: ${rejectReason(s)}`} It wasn’t validated, so deploying it — on paper or live — is your call and your risk.</span></div>` : ''}
                <button class="btn${activeDeps.length ? '' : ' primary'}" id="dep-paper">Deploy on paper</button>
                <details class="deployment-environments"><summary>Demo &amp; live</summary><div class="deployment-environments-body">
                <button class="btn ghost" id="dep-demo" ${demoWhy ? 'aria-disabled="true"' : ''}>Deploy on demo (sandbox)</button>
                ${demoWhy ? `<p class="hint">${demoWhy}</p>` : '<p class="hint">Trades Kalshi’s demo exchange with your own demo key — real order-book fills, no real money.</p>'}
                <button class="btn ghost" id="dep-live" ${liveWhy ? 'aria-disabled="true"' : ''}>Deploy with live money</button>
                ${liveWhy ? `<p class="hint">${liveWhy}</p>` : ''}
                <form id="live-confirm" hidden style="display:grid;gap:8px">
                  <p class="hint">This trades real money in your Kalshi account. Type <b>LIVE</b> to confirm.</p>
                  <input class="input" name="confirm" autocomplete="off" aria-label="Type LIVE to confirm">
                  <button class="btn" type="submit">Confirm live deployment</button>
                </form>
                </div></details>
                <div id="depflash"></div>
              </div>` : restricted ? '<p class="hint">Perpetual strategies stay in research, including after passing the statistical gates. Paper, demo and live deployment are unavailable.</p>' : '<p class="hint">This strategy isn’t ready to deploy yet.</p>'}
            ${kUrl ? `<p class="hint" style="margin-top:12px"><a href="${kUrl}" target="_blank" rel="noopener">Open ${esc(marketShort(s.market))} on Kalshi ↗</a></p>` : ''}
          </section>
          ${!restricted && s.status === 'passed' ? `<section class="panel" id="road-live"><h3>Road to live</h3><div id="road-live-body"><p class="hint">Checking…</p></div></section>` : ''}
          <section class="panel"><h3>Gates</h3><div id="gates">${gatesHtml(s.gates)}</div></section>
          ${!perpetual && s.status !== 'rejected' ? `<section class="panel" id="whatif"><h3>Sensitivity</h3>

            <div class="dial"><div class="top"><label class="label" for="wf">Fees</label><output id="wfo">1.0×</output></div><input type="range" id="wf" min="0" max="3" step="0.25" value="1"></div>
            <div class="dial"><div class="top"><label class="label" for="ws">Slippage per fill</label><output id="wso">0.0¢</output></div><input type="range" id="ws" min="0" max="5" step="0.1" value="0"></div>
            <div class="dial"><div class="top"><label class="label" for="wk">Stake per trade</label><output id="wko">$${esc(s.stake)}</output></div><input type="range" id="wk" min="1" max="200" step="1" value="${Math.min(200, s.stake)}"></div>
            <div id="wflash" aria-live="polite"></div>
          </section>` : ''}
          <details class="strategy-management"><summary>Manage strategy</summary>
          <section class="panel"><h3>Remove</h3>
            <p class="hint" style="margin-bottom:8px">${activeDeps.length ? 'Stop its deployments before deleting.' : 'Permanently deletes this strategy.'}</p>
            <div style="display:grid;gap:8px">
              ${activeDeps.length ? `<button class="btn sm danger" id="stop-dep">Stop deployment${activeDeps.length > 1 ? 's' : ''} (${activeDeps.map((d) => '#' + d.id).join(', ')})</button>` : ''}
              <button class="btn sm danger" id="del-strat" ${activeDeps.length ? 'aria-disabled="true"' : ''}>Delete strategy</button>
            </div><div id="delflash"></div>
          </section>
          <section class="panel"><h3>Share</h3>
            <p class="hint" style="margin-bottom:8px">${restricted ? 'Share a research-only copy using their Tau sign-in email. It keeps the same simulation limits and cannot be deployed.' : 'Use their Tau sign-in email. They keep a permanent copy.'}</p>
            <form id="share-form" style="display:grid;gap:8px">
              <input class="input" id="share-email" type="email" autocomplete="off" placeholder="friend@email.com" aria-label="Friend's email">
              <button class="btn sm" type="submit">Share strategy</button>
            </form><div id="shareflash"></div>
          </section>
          </details>
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
          { name: 'Separate events', threshold: (p.events_needed || 20) + '+', ok: c.events, value: p.events == null ? '—' : p.events },
          { name: 'First to last paper trade', threshold: p.span_needed_hours + 'h+', ok: c.span, value: Math.round(p.span_hours) + 'h' },
          { name: 'Edge is not luck', threshold: 'p ≤ ' + p.p_value_needed.toFixed(2), ok: c.edge, value: pv },
          { name: 'Still working lately', threshold: 'newer half above $0', ok: c.recent, value: p.recent_trades ? p.recent_net_pnl : '—' },
          { name: 'Live autopilot', threshold: 'on, key, under daily loss', ok: r.live_autopilot.ok, value: r.live_autopilot.ok ? 'ready' : 'off' },
        ];
        const body = root.querySelector('#road-live-body');
        if (body) body.innerHTML = gatesHtml(rows)
          + (p.realization != null ? `<p class="hint" style="margin-top:6px;font-variant-numeric:tabular-nums">${p.realization < 0 ? 'Paper is <b>losing money</b> per trade, while the backtest made money on unseen data.' : `Paper earns <b>${Math.round(p.realization * 100)}%</b> of the backtest's unseen-data P&amp;L per trade.`}</p>` : '')
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
            root.querySelector('#sheet-results').innerHTML = equityChart(r.equity, s.dataset && s.dataset.out_of_sample_from, null, { width: chartWidth() }) +
              `<div class="split"><div><h4>In-sample</h4>${metricRows(r.in_sample)}</div><div><h4>Out-of-sample</h4>${metricRows(r.out_of_sample)}</div></div>`;
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
    shell('/deploy', boardTitle('Deploy') +
      '<dl class="figures measure" id="dfigs" style="margin-top:14px"></dl>', `
      <div class="deploy-board"><div id="flash"></div><div id="deps">${loading(260)}</div>
        <section class="section"><div class="section-head"><h2>Open positions</h2></div><div id="openpos"></div></section>
      </div>`);
    const loadBoard = async () => {
      const d = await api('/api/deployments');
      const running = d.deployments.filter((x) => x.status === 'running');
      // Live, paper and demo results are never summed into one figure: each book gets its own. Removed
      // deployments aren't listed, so their P&L isn't here (the dashboard and track record keep it).
      const sumPnl = (xs) => xs.reduce((a, x) => a + x.realized_pnl, 0);
      const byMode = (m) => d.deployments.filter((x) => x.mode === m);
      const liveDeps = byMode('live'), paperDeps = byMode('paper'), demoDeps = byMode('demo');
      const liveRealized = sumPnl(liveDeps), paperRealized = sumPnl(paperDeps), demoRealized = sumPnl(demoDeps);
      const live = d.deployments.filter((x) => x.mode === 'live' && x.status === 'running');
      const runDemo = running.some((x) => x.mode === 'demo'), runPaper = running.some((x) => x.mode === 'paper');
      root.querySelector('#dfigs').innerHTML = fig('Running', running.length, { small: `${d.deployments.length - running.length} paused` }) +
        (liveDeps.length
          ? fig('Live realized', usd(liveRealized, true), { v: liveRealized, small: paperDeps.length ? `real money, strategies listed below · ${usd(paperRealized, true)} on paper, counted apart` : 'real money, strategies listed below' })
          : paperDeps.length || !demoDeps.length ? fig('Realized', usd(paperRealized, true), { v: paperRealized, small: 'paper money, not real · strategies listed below' }) : '') +
        (demoDeps.length ? fig('Demo realized', usd(demoRealized, true), { v: demoRealized, small: `${DEMO_WHAT} · strategies listed below` }) : '') +
        fig('Open positions', d.open_positions.length) +
        fig('Money', live.length ? '<span class="mk live">Live</span>' : runDemo ? `${runPaper ? '<span class="mk">Paper</span> ' : ''}<span class="mk dep">Demo</span>` : '<span class="mk">Paper</span>', { small: live.length ? `${live.length} on live money` : 'nothing on live money' });
      const regs = curveRegs(d.deployments);
      replaceDeploymentContent(root.querySelector('#deps'), d.deployments.length ? deploymentTable(pausedFirst(d.deployments).map((x) => deploymentSlip(x, true, regs)).join(''), true)
        : `<div class="empty"><h3>Nothing deployed</h3>${S.me && S.me.user && S.me.user.autopilot ? '<p>Autopilot is on: strategies that pass every gate deploy here on their own, on paper.</p>' : ''}${apNudge('Rather not pick strategies yourself?', 'and it deploys the ones that pass, on paper.')}<a class="btn" href="/strategies?status=passed">See passed strategies</a></div>`);
      bindDeploymentActions(root.querySelector('#deps'), loadBoard);
      root.querySelector('#openpos').innerHTML = d.open_positions.length ? `<table class="table stack"><thead><tr><th>Strategy</th><th>Contract</th><th>Side</th><th class="num">Cost + fee</th><th class="num">Unreal.</th><th class="num">Settles</th></tr></thead><tbody>
        ${d.open_positions.map((p) => `<tr><td class="name" data-lab="Strategy">${esc(p.title)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : p.mode === 'demo' ? '<span class="mk dep">Demo</span>' : ''}</td><td class="tick" data-lab="Contract">${esc(p.ticker)}</td><td data-lab="Side">${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(+p.entry_price)}</td><td class="num" data-lab="Cost + fee">${usd(p.qty * p.entry_price + +p.entry_fee)}</td><td class="num" data-lab="Unrealized">${p.unrealized == null ? '—' : money(p.unrealized)}</td><td class="num" data-lab="Settles">${clock(p.market_close_time)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="hint">No open positions.</p>';
    };
    await loadBoard();
    poll(loadBoard, 10000);
  }

  // ---------- track record ----------
  // What an allocator would check: realized results from closed trades only, one money bucket at a
  // time (live, demo and paper never mix), every figure next to the sample it rests on. All math is
  // server-side (app/track_record.py); this only lays it out.
  const TR_MODES = [['live', 'Live'], ['demo', 'Demo'], ['paper', 'Paper']];
  const trFix = (v, dp = 2) => (v == null ? '—' : (+v).toFixed(dp));
  const trDay = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—');
  const trMonth = (k) => { const [y, m] = k.split('-'); return new Date(Date.UTC(+y, +m - 1, 15)).toLocaleDateString(undefined, { year: 'numeric', month: 'short', timeZone: 'UTC' }); };
  const trCi = (ci, f) => (ci ? `95%: ${f(ci[0])} to ${f(ci[1])}` : 'needs 2+ trades for a range');
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
    if (m.open_trades) caveats.push(`${num(m.open_trades)} open trade${m.open_trades === 1 ? '' : 's'} (${usd(m.open_at_cost)} at cost) join the record when they close.`
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
        : apOn ? 'Autopilot runs the strategies that pass every gate on paper. Every closed trade is recorded here.'
        : 'Deploy a passed strategy on paper. Every closed trade is recorded here.';
      const go = apOn ? '<a class="btn" href="/research">See its research</a>' : '<a class="btn" href="/deploy">Go to Deploy</a>';
      return `<div class="empty"><h3>No closed ${esc(m.label.toLowerCase())} trades yet</h3><p>${how}</p>${key === 'paper' ? apNudge('Rather not pick strategies yourself?', 'and it runs the ones that pass on paper. Their trades fill this record.') : ''}${go}</div>${cav}`;
    }
    const s = m.sample;
    const good = s.level === 'solid' && s.edge === 'positive';
    const figs = `<dl class="figures measure tr-figs">
      ${fig('Net P&amp;L', usd(m.net_pnl, true), { v: m.net_pnl, cls: 'lead', small: `after ${usd(m.fees)} in fees` })}
      ${fig('Return', pct(m.return), { v: m.return, small: `on ${usd(m.capital)} capital required${m.annualized_return != null ? ` · ${pct(m.annualized_return)} a year` : ''}` })}
      ${fig('Max drawdown', m.max_drawdown ? usd(-m.max_drawdown) : usd(0), { small: m.max_drawdown_pct != null ? `${pct(m.max_drawdown_pct, false)} of capital` : '' })}
      ${fig('Sharpe', trFix(m.sharpe), { small: m.sharpe == null ? `shown after ${th.min_sharpe_days} days` : `PSR ${pct(m.psr, false)} · Sortino ${trFix(m.sortino)}` })}
      ${fig('Win rate', pct(m.win_rate, false), { small: trCi(m.win_rate_ci, (v) => pct(v, false)) })}
      ${fig('Trades', num(m.trades), { small: `${num(m.wins)} won · ${num(m.losses)} lost` })}
      ${fig('Avg trade', usd(m.avg_trade, true), { v: m.avg_trade, small: trCi(m.avg_trade_ci, (v) => usd(v, true)) })}
      ${fig('Profit factor', trFix(m.profit_factor), { small: 'gross wins ÷ gross losses' })}
    </dl>`;
    const risk = `<dl class="kv tr-kv">
      <dt>Average win</dt><dd>${usd(m.avg_win, true)}</dd><dt>Average loss</dt><dd>${usd(m.avg_loss, true)}</dd>
      <dt>Best trade</dt><dd>${usd(m.best, true)}</dd><dt>Worst trade</dt><dd>${usd(m.worst, true)}</dd>
      <dt>Gross P&amp;L before fees</dt><dd>${usd(m.gross_pnl, true)}</dd><dt>Fees paid</dt><dd>${usd(m.fees)}</dd>
      <dt>Current drawdown</dt><dd>${m.current_drawdown ? usd(-m.current_drawdown) : 'At a high'}</dd>
      <dt>Longest drawdown</dt><dd>${trFix(m.longest_drawdown_days, 1)} days</dd>
      <dt>First trade</dt><dd>${trDay(m.first_trade_at)}</dd><dt>Days of history</dt><dd>${num(m.days)}</dd>
    </dl>`;
    const months = m.monthly.map((r) => `<tr><td class="name" data-lab="Month">${esc(trMonth(r.month))}</td>
      <td class="num" data-lab="Net P&amp;L">${money(r.pnl)}</td><td class="num" data-lab="Trades">${num(r.trades)}</td>
      <td class="num" data-lab="Win rate">${pct(r.win_rate, false)}</td></tr>`).join('');
    const strats = m.strategies.map((r) => {
      const [tag, cls] = TR_EDGE[r.edge] || TR_EDGE.unclear;
      return `<tr><td class="name" data-lab="Strategy"><a href="/strategies/${+r.strategy_id}">${esc(r.title)}</a></td>
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
      <section class="section"><div class="section-head"><h2>By strategy</h2><p>“Too few” means under ${th.min_trades} trades</p></div>
        <div class="sheet"><table class="table stack"><thead><tr><th>Strategy</th><th>Read</th><th class="num">Trades</th><th class="num">Net P&amp;L</th><th class="num">Win rate</th><th class="num">Avg trade</th><th class="num">Max drawdown</th><th class="num">Last trade</th></tr></thead><tbody>${strats}</tbody></table></div></section>`;
  }
  // Lives on the dashboard (Todd, 2026-10-25): its own request below the live board, so the 15s
  // dashboard poll never waits on it and never wipes it. The server caches it 60s per user.
  async function mountTrackRecord(host, last) {
    const d = await api('/api/track-record', undefined, { keep: true });
    if (!host.isConnected || (last && last.at === d.generated_at)) return;
    if (last) last.at = d.generated_at;
    let tab; try { tab = localStorage.getItem('tau_tr_tab'); } catch (e) { /* private mode */ }
    if (!d.modes[tab]) tab = d.default_mode;
    host.innerHTML = `<div class="section-head"><h2>Track record</h2><p>Realized results from closed trades. Nothing here is a backtest.</p></div>
      <div class="chips tr-tabs" role="group" aria-label="Money type">
        ${TR_MODES.map(([k, label]) => `<button class="chip" type="button" data-trtab="${k}" aria-pressed="${k === tab}">${label} · ${num(d.modes[k].trades)}</button>`).join('')}
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
  async function dashTrackRecord() {
    const gen = S.gen, mainEl = root.querySelector('main'), wrap = mainEl && mainEl.parentNode;
    if (!wrap || !wrap.appendChild) return;
    const host = document.createElement('section');
    host.className = 'sect dash-track'; host.id = 'track-record'; host.innerHTML = loading(260);
    wrap.appendChild(host);  // after <main>, its last child, so the board's repaint never touches it
    const last = { at: null };
    // A failed first read offers a retry; before, the record stayed an error until a reload.
    const first = async () => {
      try { await mountTrackRecord(host, last); } catch (e) {
        if (gen !== S.gen) return;
        host.innerHTML = loadFail(e.message);
        host.querySelector('[data-retry]').onclick = () => { host.innerHTML = loading(260); return first(); };
        return;
      }
      if (gen !== S.gen) return;
      if (location.hash === '#track-record') host.scrollIntoView();
      poll(() => mountTrackRecord(host, last), 60000);
    };
    await first();
  }

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
      root.querySelector('#ffigs').innerHTML = fig('Kalshi cash', k.connected ? (k.balance == null ? 'Unavailable' : usd(k.balance)) : 'Not connected', { cls: 'lead', small: k.connected ? 'Real money at Kalshi, open positions not included' : '' }) +
        fig('Demo balance', usd(dm.equity), { small: `${usd(dm.capital)} ${dm.before_reload ? 'capital at last reload' : 'starting capital'} · ${DEMO_WHAT}` }) +
        fig('Paper cash', usd(d.paper.cash));
      root.querySelector('main').innerHTML = `<div id="flash"></div><div class="funds">
        <div class="funds-col funds-manage">
        <section class="panel">
          <h3>Kalshi account (live money)</h3>
          ${k.connected ? `
            <dl class="kv"><dt>API key</dt><dd>${esc(k.key_id)}</dd><dt>Cash at Kalshi</dt><dd>${k.balance == null ? 'Couldn’t read it just now' : usd(k.balance)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">Funds stay in your Kalshi account. Manage deposits and withdrawals at Kalshi.</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <a class="btn" href="${esc(k.funding_url)}" target="_blank" rel="noopener">Deposit or withdraw at Kalshi ${ICON.ext}</a>
              <button class="btn danger" id="disconnect">Disconnect</button>
            </div>` : `
            <p class="lede" style="margin-bottom:12px">Connect your Kalshi account for live trading. Funds stay at Kalshi.</p>
            <details class="connection-help"><summary>Key setup</summary><ol class="steps"><li>On Kalshi, open <a href="https://kalshi.com/account/profile" target="_blank" rel="noopener">your profile</a>, find API Keys and click Create New API Key.</li><li>Copy the key ID and download the private key file.</li><li>Paste the key ID below and choose the key file (or paste its text). We encrypt the private key and check it with Kalshi before saving.</li></ol></details>
            <form id="kalshi" style="display:grid;gap:12px">
              <label class="field"><span>Key ID</span><input class="input" name="key_id" autocomplete="off" spellcheck="false" required></label>
              <label class="field"><span>Private key</span><textarea class="input" name="private_key" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
              <label class="key-file"><span>Or choose the downloaded key file</span><input type="file" accept=".key,.pem,.txt,text/plain" data-keyfile></label>
              <button class="btn" type="submit">Verify and connect</button>
            </form>`}
          <div id="kflash" style="margin-top:10px"></div>
        </section>
        <section class="panel">
          <h3>Kalshi demo (sandbox) account</h3>
          <dl class="kv"><dt>Demo balance</dt><dd>${usd(dm.equity)}</dd><dt>${dm.before_reload ? 'Capital at last reload' : 'Starting capital'}</dt><dd>${usd(dm.capital)}</dd><dt>P&amp;L ${demoSpan(dm)}</dt><dd class="${tone(dm.realized)}">${usd(dm.realized, true)}</dd></dl>
          <p class="lede" style="margin-bottom:14px">Real orders on Kalshi’s sandbox exchange, so fills and slippage are real; the money is simulated. Reloading changes Tau’s balance only and starts P&amp;L since reload at $0.00; the track record still counts every closed demo trade.</p>
          <form id="demo" class="amount">
            <label class="field"><span>Reload to</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="1000"></label>
            <button class="btn" type="submit">Reload demo</button>
          </form>
          <div id="dmflash" style="margin-top:10px"></div>
          <h3 style="margin-top:24px">Demo key</h3>
          ${kd.connected ? `
            <dl class="kv"><dt>Demo key</dt><dd>${esc(kd.key_id)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">Sandbox orders only. Demo and live keys are stored separately.</p>
            <button class="btn danger" id="dev-disconnect">Remove demo key</button>` : `
            <p class="lede" style="margin-bottom:12px">Connect a Kalshi <b>demo</b> key for sandbox orders. No real money.</p>
            <details class="connection-help"><summary>Key setup</summary><ol class="steps"><li>Sign in at demo.kalshi.co and open Account → API keys.</li><li>Copy the key ID and download the private key file.</li><li>Paste the key ID below and choose the key file (or paste its text). We encrypt the private key and check it against the demo exchange before saving.</li></ol></details>
            <form id="kalshi-dev" style="display:grid;gap:12px">
              <label class="field"><span>Demo key ID</span><input class="input" name="key_id" autocomplete="off" spellcheck="false" required></label>
              <label class="field"><span>Demo private key</span><textarea class="input" name="private_key" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
              <label class="key-file"><span>Or choose the downloaded key file</span><input type="file" accept=".key,.pem,.txt,text/plain" data-keyfile></label>
              <button class="btn" type="submit">Verify and connect demo</button>
            </form>`}
          <div id="kdflash" style="margin-top:10px"></div>
        </section>
        <section class="panel">
          <h3>Paper account (simulation)</h3>
          <p class="lede" style="margin-bottom:14px">Simulated funds. No real orders.</p>
          <form id="paper" class="amount">
            <label class="field"><span>Amount</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="500"></label>
            <button class="btn" data-kind="deposit" type="submit">Add</button>
            <button class="btn ghost" data-kind="withdraw" type="submit">Withdraw</button>
            <button class="btn ghost" data-kind="reset" type="submit">Reset to amount</button>
          </form>
          <div id="pflash" style="margin-top:10px"></div>
        </section>
        </div>
        <div class="funds-col funds-history">
        <section id="kalshi-perps-live" aria-label="Bitcoin perpetual trading"></section>
        <section class="panel">
          <h3>Paper history</h3>
          <table class="table stack t-ledger"><thead><tr><th>When</th><th>What</th><th class="num">Amount</th></tr></thead><tbody>
            ${d.paper.ledger.map((r) => `<tr><td class="hint lead-cell">${when(r.created_at)}</td><td class="name">${esc(r.memo || r.kind)}</td><td class="num ${tone(+r.amount)}">${usd(r.amount, true)}</td></tr>`).join('')}
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
          try { await api('/api/funds/demo', { amount: +df.amount.value }); if (gen !== S.gen) return; await load(); if (gen === S.gen) flash('#dmflash', 'Demo account reloaded.', 'good'); } catch (err) { if (gen === S.gen) flash('#dmflash', err.message, 'bad'); }
        });
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
        const btn = pf.querySelector(`[data-kind="${kind}"]`);
        await busy(btn, async () => {
          try { await api('/api/funds/paper', { kind, amount: +pf.amount.value }); if (gen !== S.gen) return; await load(); if (gen === S.gen) flash('#pflash', kind === 'deposit' ? 'Added to your paper account.' : kind === 'withdraw' ? 'Withdrawn from your paper account.' : 'Paper account reset.', 'good'); } catch (err) { if (gen === S.gen) flash('#pflash', err.message, 'bad'); }
        });
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
        await busy(kf.querySelector('button'), async () => {
          try { await api('/api/kalshi-key', { key_id: kf.key_id.value, private_key: kf.private_key.value }); if (gen !== S.gen) return; S.me.kalshi_connected = true; await load(); if (gen === S.gen) flash('#kflash', 'Connected. Kalshi confirmed the key.', 'good'); } catch (err) { if (gen === S.gen) flash('#kflash', err.message, 'bad'); }
        });
      };
      const dc = root.querySelector('#disconnect');
      if (dc) dc.onclick = () => armed(dc, 'Confirm disconnect', () => busy(dc, async () => {
        try { await api('/api/kalshi-key/delete', {}); if (gen !== S.gen) return; S.me.kalshi_connected = false; await load(); } catch (err) { if (gen === S.gen) flash('#kflash', err.message, 'bad'); }
      }));
      const kdf = root.querySelector('#kalshi-dev');
      if (kdf) kdf.onsubmit = async (e) => {
        e.preventDefault();
        await busy(kdf.querySelector('button'), async () => {
          try { await api('/api/kalshi-dev-key', { key_id: kdf.key_id.value, private_key: kdf.private_key.value }); if (gen !== S.gen) return; S.me.kalshi_dev_connected = true; await load(); if (gen === S.gen) flash('#kdflash', 'Connected. Kalshi’s demo exchange confirmed the key.', 'good'); } catch (err) { if (gen === S.gen) flash('#kdflash', err.message, 'bad'); }
        });
      };
      const dvc = root.querySelector('#dev-disconnect');
      if (dvc) dvc.onclick = () => armed(dvc, 'Confirm remove', () => busy(dvc, async () => {
        try { await api('/api/kalshi-dev-key/delete', {}); if (gen !== S.gen) return; S.me.kalshi_dev_connected = false; await load(); } catch (err) { if (gen === S.gen) flash('#kdflash', err.message, 'bad'); }
      }));
    };
    try { await load(); } catch (err) { if (gen === S.gen) throw err; }
  }

  // ---------- community ----------
  function postSnapshot(snap) {
    if (!snap) return '';
    if (snap.kind === 'pnl') {
      return `<div class="snap snap-pnl"><div class="snap-head"><b>Realized P&amp;L</b></div><dl class="snap-metrics"><div><dt>Paper</dt><dd class="${tone(snap.paper_pnl)}">${usd(snap.paper_pnl, true)}</dd></div>
        <div><dt>Live</dt><dd class="${tone(snap.live_pnl)}">${usd(snap.live_pnl, true)}</dd></div></dl></div>`;
    }
    if (snap.kind === 'strategy') {
      return `<a class="snap snap-strategy" href="/strategies/${snap.id}"><div class="snap-head"><span class="snap-title"><b>${esc(snap.title)}</b>${mark(snap.status)}${researchBadge(snap)}</span><div class="snap-meta-line"><span class="snap-kind">Strategy</span><span class="snap-meta">${esc(marketShort(snap.market))}</span></div></div><dl class="snap-metrics snap-evidence-metrics"><div class="snap-result"><dt>Out-of-sample P&amp;L</dt><dd class="${tone(snap.pnl)}">${snap.pnl == null ? '—' : usd(snap.pnl, true)}</dd></div>${snap.trades != null ? `<div class="snap-secondary"><dt>Trades</dt><dd>${esc(snap.trades)}</dd></div>` : ''}${snap.win_rate != null ? `<div class="snap-secondary"><dt>Win rate</dt><dd>${pct(snap.win_rate, false)}</dd></div>` : ''}</dl></a>`;
    }
    if (snap.kind === 'deployment') {
      return `<div class="snap snap-deployment"><div class="snap-head"><span class="snap-title"><b>${esc(snap.title)}</b>${deploymentMode(snap)}</span><div class="snap-meta-line"><span class="snap-kind">Deployment</span><span class="snap-meta">${esc(marketShort(snap.market))}</span></div></div><dl class="snap-metrics snap-evidence-metrics"><div class="snap-result"><dt>Realized P&amp;L</dt><dd class="${tone(snap.realized_pnl)}">${usd(snap.realized_pnl, true)}</dd></div><div class="snap-secondary"><dt>Closed trades</dt><dd>${esc(snap.closed_trades)}</dd></div></dl></div>`;
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
    return `<button class="rx ${rx.mine ? 'on' : ''}" data-emoji="${esc(rx.emoji)}" aria-pressed="${!!rx.mine}" aria-label="${esc(rx.emoji)}, ${rx.count}${who ? ' — ' + who : ''}">${emojiHtml(rx.emoji)}<span class="n">${rx.count}</span>${who ? `<span class="rxtip" role="tooltip">${who}</span>` : ''}</button>`;
  }
  // Existing reactions and an explicit action to open the palette.
  function reactionChips(list) {
    const chips = (list || []).map(rxChip).join('');
    return chips + `<button class="rx add" data-react-add aria-label="Add a reaction" title="Add a reaction">React</button>`;
  }
  const GROUP_WINDOW = 5 * 60 * 1000;  // consecutive posts by one author within 5 min collapse the header
  // A Slack-style message row: avatar gutter + name/@handle/time header, body, attachments,
  // reaction pills, and a bottom-left action row (reply / replies count, plus edit on own posts).
  // A grouped post is a tight continuation of the author above it: no header, a hover-only time.
  function postCard(p, grouped) {
    const replies = p.comments || 0;
    return `<article class="post${grouped ? ' grouped' : ''}${p.picture ? ' post-photo' : ''}" data-id="${p.id}">
      <div class="post-gutter">${grouped ? `<time class="gutter-time">${clock(p.created_at)}</time>` : avatar(p.picture, p.author)}</div>
      ${grouped ? '' : `<div class="post-head"><b>${authorLine(p.author, p.username)}</b><span class="when">${when(p.created_at)}${p.edited ? ' · edited' : ''}</span></div>`}
      <div class="post-col">
        <div class="post-main"><div class="post-body">${mdLite(p.body)}</div>
        ${p.image ? `<a class="post-img" href="${esc(p.image)}" target="_blank" rel="noopener"><img src="${esc(p.image)}" alt="" loading="lazy"></a>` : ''}
        ${postSnapshot(p.snapshot)}
        <div class="post-footer"><div class="reactions">${reactionChips(p.reactions)}</div>
        <div class="post-actions">
          <button class="thread-link" data-act="comments"><span>${replies ? `${replies} ${replies === 1 ? 'reply' : 'replies'}` : 'Reply'}</span></button>
          ${p.mine ? `<button class="thread-link" data-act="edit">${ICON.pencil}<span>Edit</span></button>` : ''}
        </div></div></div>
        <div class="comments" hidden></div>
      </div>
    </article>`;
  }
  // Emoji reactions — a fixed palette (matches the server whitelist). 'tau' is a
  // custom reaction: the static Tau mark.
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
    shell('/community', '', `
      <div class="feedwrap"><div class="community-heading"><h1 class="page">Community</h1>
        <div class="chips feed-filter" role="group" aria-label="Filter posts"><button class="chip" type="button" data-feed="all" aria-pressed="true">All posts</button><button class="chip" type="button" data-feed="mine" aria-pressed="false">My posts</button></div>
      </div>
        <details class="community-compose"><summary>New post ${ICON.chev}</summary>
        <form class="panel composer-post" id="composer-post" aria-label="New post">
          <textarea class="input" id="post-body" maxlength="2000" rows="1" aria-label="Write a post" placeholder="Write a post…"></textarea>
          <div id="photo-preview" hidden><img id="photo-img" alt="Attached photo preview"><button type="button" class="photo-x" id="photo-remove" aria-label="Remove photo">${ICON.cross}</button></div>
          <div class="post-tools">
            <button class="btn sm" type="button" id="photo-btn">${ICON.image}Photo</button>
            <input type="file" id="photo-input" accept="image/png,image/jpeg,image/webp,image/gif" class="vh">
            <label class="field"><span class="vh">Attach a strategy</span>
              <select id="post-strat"><option value="">Attach strategy</option></select></label>
            <button class="btn sm" type="button" data-share="pnl">${ICON.up}Share my P&amp;L</button>
            <button class="btn primary sm" type="submit">Post</button>
          </div>
          <div id="post-flash"></div>
        </form>
        </details>
        <div id="feed">${loading(120)}${loading(120)}</div>
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
        : `<div class="empty"><h3>${mineOnly ? 'You haven’t posted yet' : 'No posts yet'}</h3><p>${mineOnly ? 'Share a strategy an agent found or how your book is doing. It shows up here.' : 'Be the first. Share a strategy an agent found, an idea worth researching, or how your paper book is doing.'}</p></div>`;
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
  // The yes subtitle only when it adds something: "Minnesota wins · Minnesota" and "Will Bitcoin be
  // above $200000 by Jan 1…? · Above $200000" repeated the title.
  const mktLabel = (m) => { const t = (m.ti || '').trim(), s = (m.su || '').trim(); return s && !t.toLowerCase().includes(s.toLowerCase()) ? (t ? `${t} · ${s}` : s) : (t || m.t); };
  const compactCondition = label => label.replace(/^(\$[\d,]+(?:\.\d+)?) or above$/i, '≥ $1').replace(/^(\$[\d,]+(?:\.\d+)?) or below$/i, '≤ $1').replace(/^Above (\$[\d,]+(?:\.\d+)?)$/i, '> $1').replace(/^Below (\$[\d,]+(?:\.\d+)?)$/i, '< $1');
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
    if (!points || points.length < 2) return '<div class="empty"><h3>Not enough price history</h3></div>';
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
    catch (e) {
      root.querySelector('main').innerHTML = notice(e.message, 'bad') + `<p style="margin-top:12px"><button class="btn sm" type="button" id="mk-retry">Try again</button> <a class="btn sm" href="/explore">← Back to Explore</a></p>`;
      root.querySelector('#mk-retry').onclick = () => viewMarketDetail(ticker);
      return;
    }
    const mid = midOf({ bid: d.yes_bid, ask: d.yes_ask, last: d.last });
    const label = mktLabel({ ti: d.title, su: d.sub, t: d.ticker });
    const closes = d.close_time ? new Date(d.close_time).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '—';
    const gran = d.period_min >= 1440 ? 'daily' : d.period_min >= 60 ? 'hourly' : 'per-minute';
    const fmtT = (t) => new Date(t * 1000).toLocaleString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    shell('/explore', boardTitle(label, `${d.series} · ${d.status || 'market'} · ${d.ticker}`) +
      '<dl class="figures measure" style="margin-top:14px">' +
        fig('Yes price', mid == null ? '—' : cents(mid)) + fig('24h volume', num(Math.round(+d.volume_24h || 0))) +
        fig('Open interest', num(Math.round(+d.open_interest || 0))) + fig('Closes', closes) + '</dl>', `
      <section class="sect"><div class="sect-head"><h2>Price history</h2><p>Yes price${d.history_unavailable ? '' : ` · Kalshi ${gran} candles`}</p></div>
        <div class="pchart-wrap">${d.history_unavailable
          ? '<div class="empty"><h3>Price history didn’t load</h3><p>Kalshi didn’t send it just now. The figures above are from the latest market snapshot.</p><button class="btn sm" type="button" id="mk-retry">Try again</button></div>'
          : priceChart(d.points)}</div></section>
      <section class="sect"><div class="sect-head"><h2>Raw data</h2><p>${d.history_unavailable ? 'Not loaded' : `${num(d.points.length)} ${gran} points${d.points.length ? ' · newest first' : ''}`}</p></div>
        <div id="rawsect"></div></section>
      <div class="xpage"><a class="btn sm" href="/explore">← Back to Explore</a>
        <span class="xpage-acts"><button class="btn sm" id="dl-csv" ${d.points.length ? '' : 'disabled'}>Download CSV</button>
        <a class="btn sm" href="https://kalshi.com/markets/${encodeURIComponent((d.series || '').toLowerCase())}" target="_blank" rel="noopener">View on Kalshi ↗</a></span></div>`);
    const retry = root.querySelector('#mk-retry');
    if (retry) retry.onclick = () => viewMarketDetail(ticker);
    const pts = d.points.slice().reverse();  // newest first
    const PER = 100; let pg = 0;
    const rawEl = root.querySelector('#rawsect');
    const renderRaw = () => {
      if (!pts.length) { rawEl.innerHTML = `<div class="empty"><p>${d.history_unavailable ? 'Waiting on Kalshi for the candles.' : 'No candles recorded for this market yet.'}</p></div>`; return; }
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
    shell('/explore', `<div class="board-title explore-heading"><h1 class="page">Explore</h1>
      <div class="section-head filters explore-filters">
        <label class="field xsearch" style="margin:0"><span class="vh">Search markets</span>
          <input class="input" id="xq" type="search" placeholder="Search markets" value="${esc(f.q)}" autocomplete="off"></label>
        <div class="figures measure" id="xfigs"></div>
      </div></div>`, `<div id="xbody">${loading(240)}</div>`);
    const body = root.querySelector('#xbody'), figs = root.querySelector('#xfigs'), gen = S.gen;
    const quoteSide = value => {
      if (typeof value !== 'number' && typeof value !== 'string') return '—';
      if (typeof value === 'string' && !value.trim()) return '—';
      return Number.isFinite(+value) ? cents(+value) : '—';
    };
    let seq = 0;
    const sync = () => history.replaceState(null, '', '/explore?' + new URLSearchParams({ q: f.q, sort: f.sort, page: String(f.page) }));
    const load = async () => {
      const mine = ++seq;
      const d = await api('/api/explore?' + new URLSearchParams({ q: f.q, sort: f.sort, page: String(f.page) }));
      if (mine !== seq || gen !== S.gen) return;
      const snapshotAt = d.at ? Date.parse(d.at) : NaN;
      const snapshotOld = !Number.isFinite(snapshotAt) || Date.now() - snapshotAt > 180000;
      figs.innerHTML = '<dl class="explore-counts">' + fig('Available markets', num(d.shown)) + (d.total !== d.shown ? fig('Tracked', num(d.total)) : '') + (f.q || d.matched !== d.shown ? fig('Matching', num(d.matched)) : '') + '</dl><dl class="explore-freshness">' + fig(Number.isFinite(snapshotAt) && snapshotOld ? 'Stale snapshot' : 'Snapshot', Number.isFinite(snapshotAt) ? `<span class="snapshot-age">${sinceMin(d.at)}</span><time datetime="${esc(d.at)}">${esc(new Date(snapshotAt).toISOString().replace('T', ' ').replace('.000Z', ' UTC').replace('Z', ' UTC'))}</time>` : 'Time unavailable', { cls: 'snapshot-time' + (Number.isFinite(snapshotAt) ? (snapshotOld ? ' snapshot-old' : '') : ' snapshot-unknown') }) + '</dl>';
      figs.querySelector('.snapshot-time').setAttribute('title', Number.isFinite(snapshotAt) ? 'Source snapshot: ' + d.at : 'Source snapshot time unavailable');
      if (!d.markets.length) { body.innerHTML = `<div class="empty"><h3>No markets match “${esc(f.q)}”</h3></div>`; return; }
      const rows = d.markets.map((m) => {
        const mid = midOf(m);
        const label = mktLabel(m);
        const title = (m.ti || '').trim(), condition = (m.su || '').trim();
        const separateCondition = condition && title && condition !== title ? condition : '';
        const conditionDisplay = compactCondition(separateCondition);
        const titleParts = title.split(' · ');
        const eventDisplay = titleParts.length > 1 ? `<strong>${esc(titleParts[0])}</strong>` : esc(title);
        const contractLink = `<a class="market-name single" href="/explore?m=${encodeURIComponent(m.t)}" aria-label="${esc(label === m.t ? label : label + ' · ' + m.t)}" title="${esc(m.t)}">${separateCondition ? `<span class="market-identity-line"><span class="market-event" title="${esc(title)}">${eventDisplay}</span><strong>${esc(conditionDisplay)}</strong></span>` : `<strong>${esc(title || condition || m.t)}</strong>`}<span class="market-ref">${esc(m.t)}</span></a>`;
        return `<tr>${separateCondition ? `<td class="name market-contract">${contractLink}</td><td class="market-context-cell" data-lab="Context">${titleParts.length > 1 ? `<span class="market-context" title="${esc(title)}">${esc(titleParts.slice(1).join(' · '))}</span>` : '<span class="unavailable" title="No separate context in source title"><span aria-hidden="true">—</span><span class="vh">No separate context</span></span>'}</td>` : `<td class="name" colspan="2">${contractLink}</td>`}
          <td class="num yes-price" data-lab="YES Price">${mid == null ? '—' : cents(mid)}</td><td class="num quote-side quote-bid" data-lab="YES Bid">${quoteSide(m.bid)}</td><td class="num quote-side quote-ask" data-lab="YES Ask">${quoteSide(m.ask)}</td><td class="num market-volume" data-lab="24h volume">${num(Math.round(+m.v24 || 0))}</td><td class="num market-interest" data-lab="Open interest">${num(Math.round(+m.oi || 0))}</td>
          <td class="num xlink"><a href="${kalshiUrl(m)}" target="_blank" rel="noopener" aria-label="Open on Kalshi">${ICON.ext}</a></td></tr>`;
      }).join('');
      const pages = Math.max(1, Math.ceil(d.matched / d.per));
      const sortHead = (key, label, criterion = label, rowspan = 1) => `<th scope="col"${rowspan > 1 ? ` rowspan="${rowspan}"` : ''} class="num${key === 'last' ? ' quote-head' : ''}" aria-sort="${f.sort === key ? 'descending' : 'none'}"><button type="button" data-sort="${key}" title="Sort by ${criterion.toLowerCase()}" aria-label="Sort by ${criterion.toLowerCase()}">${label}${f.sort === key ? ' <span aria-hidden="true">↓</span>' : ''}</button></th>`;
      const sortFocused = body.querySelector('[data-sort]:focus')?.dataset.sort;
      body.innerHTML = `<div class="sheet"><table class="t-explore"><colgroup><col style="width:33.3333333333%"><col style="width:13.8888888889%"></colgroup><colgroup><col style="width:9.7222222222%"><col style="width:7.6388888889%"><col style="width:7.6388888889%"></colgroup><colgroup><col style="width:12.5%"><col style="width:12.5%"><col style="width:2.7777777778%"></colgroup><thead><tr><th scope="col" rowspan="2" class="contract-head">Market / contract</th><th scope="col" rowspan="2" title="Additional context from the market title">Context</th><th scope="colgroup" colspan="3" class="price-group">YES</th>${sortHead('v24', '24h volume', '24h volume', 2)}${sortHead('oi', 'Open interest', 'Open interest', 2)}<th scope="col" rowspan="2" class="num" aria-label="Link"></th></tr><tr>${sortHead('last', 'Price', 'last trade price')}<th scope="col" class="num quote-head">Bid</th><th scope="col" class="num quote-head quote-head-ask">Ask</th></tr></thead><tbody>${rows}</tbody></table></div>
        ${pages > 1 ? `<div class="xpage">${f.page > 0 ? `<button class="btn sm" data-pg="${f.page - 1}">${ICON.up ? '' : ''}← Prev</button>` : '<span></span>'}<span class="lab">Page ${f.page + 1} of ${num(pages)}</span>${f.page + 1 < pages ? `<button class="btn sm" data-pg="${f.page + 1}">Next →</button>` : '<span></span>'}</div>` : ''}`;
      body.querySelectorAll('[data-pg]').forEach((b) => b.onclick = () => { f.page = +b.dataset.pg; sync(); window.scrollTo({ top: 0, behavior: 'smooth' }); load(); });
      body.querySelectorAll('[data-sort]').forEach((b) => b.onclick = () => { f.sort = b.dataset.sort; f.page = 0; sync(); load(); });
      if (sortFocused) Array.from(body.querySelectorAll('[data-sort]')).find(b => b.dataset.sort === sortFocused)?.focus({ preventScroll: true });
    };
    let t; root.querySelector('#xq').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); f.page = 0; sync(); load(); }, 220); });
    await load();
  }

  // Hot Markets left rail: persistent (open/closed survives page switches), refreshes each minute.
  const hotOpen = () => {
    const saved = localStorage.getItem('tau_hotrail');
    return saved === '1';
  };
  let hotLoop = false;
  let apLoop = false, apReq = null;

  // ---------- floating autopilot window ----------
  const apExpanded = () => localStorage.getItem('tau_ap_open') === '1';
  function mountAutopilot() {
    if (!S.me || !S.me.user) return;
    let box = document.getElementById('autopilot-float');
    if (!box) { box = document.createElement('div'); box.id = 'autopilot-float'; box.className = 'apf'; document.body.appendChild(box); }
    root.querySelector('.masthead-in').appendChild(box);
    renderAutopilot(box, S.ap);
    const stale = !S.ap || !S.apAt || Date.now() - S.apAt > 18000;
    if (stale) refreshAutopilot(box, true);
    if (!apLoop) {
      // Background tabs don't poll (each status read is ~14 queries); coming back refreshes a stale one.
      apLoop = true;
      const tick = paced((cfg) => refreshAutopilot(document.getElementById('autopilot-float'), false, cfg).then((ok) => { if (!ok) throw new Error('Autopilot status read failed'); }), 20000, apPaintStale);
      setInterval(() => { if (document.getElementById('autopilot-float') && !document.hidden) tick(); }, 20000);
      document.addEventListener('visibilitychange', () => {
        const b = document.getElementById('autopilot-float');
        if (b && !document.hidden && (!S.apAt || Date.now() - S.apAt > 18000)) refreshAutopilot(b, true);
      });
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
      renderAutopilot(box, S.ap); paintDashAp();
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
  // The paper book's equity P&L (dashboard total_pnl) restarts when the account is reset, so it reads
  // "since reset" then; the track record keeps every closed trade and would otherwise disagree.
  function paperSpan(p) { return p && p.reset_at ? 'since reset' : 'all time'; }
  // Demo P&L restarts at a reload (before_reload holds what came before), unlike the track record.
  function demoSpan(dm) { return dm && dm.before_reload ? 'since reload' : 'all time'; }
  // One mode's closed trades as a CSV, offered only where that mode has some, so the reader can
  // check its P&L line by line. The server never mixes modes in one file.
  function tradesCsv(mode, b) {
    return b && b.closed_trades > 0 ? ` \u00b7 <a class="csv-link" href="/api/trades.csv?mode=${mode}" download>Download trades (CSV)</a>` : '';
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
    const pnl = S.dashPaper ? S.dashPaper.total_pnl : null;
    const cells = [
      d.live_running ? ['Live realized today (UTC)', money(d.today_live_pnl || 0)] : ['Paper P&amp;L, ' + paperSpan(S.dashPaper), pnl == null ? '—' : money(pnl)],
      ['Strategies running', running ? String(running) : 'None yet'],
      d.week ? null : ['Ideas this week', `${Number(r.tested_7d || 0).toLocaleString('en-US')} tested · ${r.passed_7d || 0} passed`],
      prog ? ['Furthest on paper', `<a href="/strategies/${Number(prog.strategy_id)}" title="${esc(prog.title || 'Paper strategy')}">${prog.trades} of ${prog.trades_needed} paper trades</a>`]
        : ['Last move', d.reviewing ? 'Reviewing now' : d.last_action && d.last_action.at ? sinceMin(d.last_action.at) : (d.last_review_at ? 'Reviewed ' + sinceMin(d.last_review_at) : 'Starting up')],
    ].filter(Boolean);
    const now = d.billing_blocked
      ? `Paused: <a href="/billing">${d.billing_reason === 'card' ? 'add a payment method' : 'add credits'}</a> so it can keep researching.`
      : d.idle ? apIdleHtml(d.idle, 'data-apcard="idle-focus"') : esc((d.story && d.story[0]) || 'Autopilot is on.');
    host.className = 'apcard on' + (m.cls ? ' ' + m.cls : '') + (d.billing_blocked ? ' warn' : '');
    host.innerHTML = `<div class="apcard-main"><span class="apcard-kick"><span class="apf-dot" aria-hidden="true"></span>${esc(m.label)}</span>
        <p class="apcard-now">${now}</p>${Array.isArray(d.focus) ? `
        <p class="ap-focus">${apFocusLine(d.focus, 'data-apcard="focus"')}</p>` : ''}
        <dl class="apcard-figs">${cells.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl><p class="stale-note" id="dash-ap-stale" role="status">${apStale()}</p>${apWeek(d.week)}</div>
      <div class="apcard-act"><button type="button" class="btn" data-apcard="open">Open autopilot</button></div>`;
    host.querySelector('[data-apcard="open"]').onclick = () => apOpen();
    const idleFocus = host.querySelector('[data-apcard="idle-focus"]');
    if (idleFocus) idleFocus.onclick = () => { apOpen(); apShowFocus(document.getElementById('autopilot-float')); };
    apBindFocus(host);
  }
  // Why autopilot isn't trading right now (the server's d.idle): one plain line, plus the action to
  // take when there is one (a link, or the focus control). The card and the panel both lead with it.
  function apIdleHtml(idle, focusAttr) {
    const a = idle.action;
    const act = !a ? '' : a.href ? ` <a href="${esc(a.href)}">${esc(a.label)}</a>`
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
  function apWeek(w) {
    if (!w) return '';
    const pnl = +w.paper_pnl || 0, trades = +w.paper_trades || 0;
    return `<section class="ap-week" aria-label="Autopilot, last 7 days"><h3>Last 7 days</h3><dl>
      <div><dt>Credits spent on research</dt><dd>${usd(w.research_credits || 0)} <small>real money</small></dd></div>
      <div><dt>Ideas</dt><dd>${Number(w.tested || 0).toLocaleString('en-US')} tested · ${Number(w.passed || 0).toLocaleString('en-US')} passed</dd></div>
      <div><dt>Started on paper</dt><dd>${Number(w.paper_started || 0)} strateg${+w.paper_started === 1 ? 'y' : 'ies'}</dd></div>
      <div><dt>Paper P&amp;L</dt><dd><span class="${pnl < 0 ? 'neg' : pnl > 0 ? 'pos' : ''}">${usd(pnl, true)}</span> <small>paper, not real money · ${trades} closed trade${trades === 1 ? '' : 's'}</small></dd></div>
    </dl><p class="ap-week-note">Research counts every session, yours and the autopilot's. Paper counts only the strategies the autopilot put on paper itself.</p></section>`;
  }
  // What switching it on costs, said before the click: the agent's runs spend credits, and with
  // auto-reload on the saved card is charged when they run low. Payments off on this server: no line.
  function apCostLine() {
    const me = S.me;
    if (!me || !me.billing_enabled) return '';
    const ar = me.auto_reload;
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
  function depsEmpty(on) {
    return on
      ? `<div class="empty"><h3>Nothing deployed yet</h3><p>Autopilot is on. Strategies that pass every gate land here on paper first, with no real money.</p><a class="btn" href="/research">See its research</a></div>`
      : `<div class="empty"><h3>Nothing deployed yet</h3><p>Turn on autopilot above and the strategies that pass every gate on data they never saw land here on their own, on paper first. Or start a session yourself.</p><a class="btn" href="/research?new=1">New session</a></div>`;
  }
  // Copy that depends on the switch follows it without a reload, so turning autopilot on doesn't leave
  // "Turn on autopilot above" or a Turn on nudge under a card that already says it's on.
  let trAp = null;  // the mounted track record's tab, to repaint when the switch flips
  const apSwitchOn = () => !!(S.me && S.me.user && S.me.user.autopilot);
  function syncApCopy(on) {
    const box = document.getElementById('deps-empty');
    if (box && box.dataset.on !== (on ? '1' : '0')) { box.dataset.on = on ? '1' : '0'; box.innerHTML = depsEmpty(on); }
    if (document.body) document.body.querySelectorAll('.research-ap').forEach((p) => { p.hidden = on; });
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
    if (!phone()) apOpen();  // on a phone the open panel fills the screen; the card already says it's on
    const box = document.getElementById('autopilot-float');
    if (box && apExpanded()) { const prefs = box.querySelector('.apf-prefs'); if (prefs) prefs.open = true; }
    if (box) await refreshAutopilot(box);
  }
  const AP_PENDING_ON = { label: 'Autopilot on', cls: 'paper' };  // switch on, mode not read yet
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
    // The switch notes ("Autopilot is ON: …") were labelled Reviewed, so a new user's first feed line
    // said it had reviewed something seconds after the click, before any review ran.
    const flip = !m.proposal_kind && /^(LIVE )?autopilot is (ON|OFF)\b/i.exec(m.content || '');
    const kind = AP_ACT[m.proposal_kind] || (flip ? (flip[1] ? 'Live autopilot ' : 'Autopilot ') + (/on/i.test(flip[2]) ? 'on' : 'off') : 'Reviewed');
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
    let d; try { d = await api('/api/chat?after=' + (full ? 0 : apChatLastId), undefined, { keep: true }); } catch (e) { return; }
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
    if (!msgs.children.length) msgs.innerHTML = '<li class="ap-empty">No autopilot activity yet.</li>';
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
        : `<span>${apIdleLine(box)}</span>`;
    }
    if (stick) msgs.scrollTop = msgs.scrollHeight;
  }
  // Idle pulse copy: lead with the autopilot's most recent move (from the status poll, always
  // available even if chat is slow), else a plain "on a schedule" line.
  function apIdleLine(box) {
    const la = S.ap && S.ap.last_action;
    if (la && la.at) return 'Idle · last move ' + sinceMin(la.at);
    return 'Idle';
  }
  function renderAutopilot(box, d) {
    if (!apExpanded()) {
      apStopChat();
      // Before the first status read lands (or if it fails), go by the saved switch: an autopilot
      // user's pill read "Autopilot off" on every page load until then.
      const m = d ? (AP_MODE[d.mode] || AP_MODE.off) : (S.me && S.me.user && S.me.user.autopilot ? AP_PENDING_ON : AP_MODE.off);
      box.className = 'apf' + (m.cls ? ' ' + m.cls : '');
      box.dataset.shell = '';
      box.innerHTML = `<button type="button" class="apf-pill" data-ap="toggle" aria-expanded="false" title="Autonomous research and deployment. Existing strategies run independently.">
        <span class="apf-pill-label">${esc(m.label)}</span>${ICON.chev || ''}</button>`;
      box.querySelector('[data-ap]').onclick = (e) => apAction(box, 'toggle', e);
      return;
    }
    if (box.dataset.shell !== 'expanded') apBuildShell(box);
    apUpdate(box, d);
  }
  function apBuildShell(box) {
    box.dataset.shell = 'expanded';
    box.innerHTML = `
      <div class="apf-head"><b id="apf-label"></b>
        <button type="button" class="apf-x" data-ap="toggle" aria-label="Collapse">${ICON.cross || '×'}</button></div>
      <div class="apf-top">
        <div class="autopilot" id="apf-ap">
          <span id="apf-ap-copy"></span>
          <label class="switch"><span class="vh">Autopilot</span><input type="checkbox" id="apf-apswitch"></label>
        </div>
        <dl class="apf-stats" id="apf-stats"></dl>
        <p class="stale-note" id="apf-stale" role="status"></p>
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
        <div class="apf-session-head"><span class="say-kind">Activity feed</span></div>
        <ol class="log stream apf-log" id="apf-messages" role="log" aria-label="Autopilot activity" aria-live="polite"></ol>
        <div class="runpulse apf-pulse-row" id="apf-pulse" aria-live="polite" hidden></div>
      </div>
      <form class="composer apf-composer-row" id="apf-composer">
        <label class="vh" for="apf-msg">Message the agent</label>
        <textarea class="input" id="apf-msg" rows="1" maxlength="2000" placeholder="What should it focus on?" aria-label="Message the autopilot"></textarea>
        <button class="btn" type="submit" aria-label="Send">${ICON.send}</button>
      </form>`;
    box.querySelector('.apf-x').onclick = (e) => apAction(box, 'toggle', e);
    box.querySelector('#apf-confirm').onsubmit = (e) => { e.preventDefault(); apEnableLive(box, box.querySelector('#apf-confirm').confirm.value.trim()); };
    const sw = box.querySelector('#apf-apswitch');
    sw.onchange = async () => {
      const on = sw.checked;
      // One flip, like the dashboard card and the empty-page nudges: paper-only and undone by flipping
      // back. Real money keeps its own typed LIVE AUTOPILOT confirm below.
      try { await api('/api/settings', { autopilot: on }); S.me.user.autopilot = on; } catch (e) { sw.checked = !on; alert0(e.message); return; }
      // Right after switching on, show where it may trade, so the focus is a choice and not a default nobody saw.
      if (on) { const prefs = box.querySelector('.apf-prefs'); if (prefs) prefs.open = true; }
      if (S.ap) S.ap = Object.assign({}, S.ap, { autopilot: on, mode: !on ? 'off' : S.ap.mode === 'off' ? 'paper' : S.ap.mode });
      paintDashAp();  // copy that follows the switch flips now, not on the next status read
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
    apChatTimer = setInterval(() => { const b = document.getElementById('autopilot-float'); if (b && apExpanded()) { if (!document.hidden) apLoadChat(b); } else apStopChat(); }, 3000);
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
        } catch (e) { if (current()) { sel.value = prev; alert0(e.message); } }
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
        catch (e) { if (current()) { sel.value = (S.ap && S.ap.model) || cur; alert0(e.message); } }
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
    const copy = box.querySelector('#apf-ap-copy');
    if (copy) copy.innerHTML = on
      ? '<b>Autopilot</b>Researches, deploys and tunes paper strategies on its own, and adjusts your risk &amp; execution controls within safe bounds. It never touches live money without the step below.'
      : '<b>Autopilot</b>Off — the agent only proposes (research, deploys, risk/execution/parameter changes); you approve each one.';
    if (!d) return;
    // Plain-language summary from the server (what it's doing, why no trades yet, what live needs).
    const story = box.querySelector('#apf-story');
    if (story) {
      // The billing pause has its own line under the switch, so the idle line skips it.
      story.innerHTML = (d.idle && !d.billing_blocked ? `<p class="apf-idle">${apIdleHtml(d.idle, 'data-ap="idle-focus"')}</p>` : '')
        + (d.story || []).map((line) => `<p>${esc(line)}</p>`).join('');
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
      `<dt>Running</dt><dd>${runTotal ? runParts.join(' · ') : 'None'}</dd>`,
      `<dt>${liveInPlay ? 'Live' : 'Paper'} realized today (UTC)</dt><dd class="${pnl < 0 ? 'neg' : (pnl > 0 ? 'pos' : '')}">${usd(pnl, true)}</dd>`,
    ].concat(liveInPlay ? [`<dt>Loss budget left</dt><dd>${usd(d.loss_headroom)} / ${usd(d.daily_loss_limit)}</dd>`] : [])
      // A queued or running review is not a finished one: right after switching on, "Last reviewed just now" claimed a review that hadn't run.
      .concat(d.review_wait ? [`<dt>Review</dt><dd>${d.review_wait.state === 'queued' ? 'Waiting' : 'Silent'} ${waitSpan(d.review_wait.seconds)}</dd>`]
        : d.reviewing ? ['<dt>Review</dt><dd>In progress</dd>'] : d.last_review_at ? [`<dt>Last reviewed</dt><dd>${sinceMin(d.last_review_at)}</dd>`] : []);
    if (stats) {
      stats.dataset.cols = short.length;
      stats.innerHTML = short.map((c, i) => `<div${short.length % 2 && i === short.length - 1 ? ' class="apf-tail"' : ''}>${c}</div>`).join('') + `
      ${liveInPlay ? `<div class="apf-wide apf-budget"><dt>Loss budget</dt><dd>Counts live losses booked since 00:00 UTC. Live also stops if your Kalshi account falls ${usd(d.daily_loss_limit)} in a day, open positions included.</dd></div>` : ''}
      ${d.research && !(d.story || []).length ? `<div class="apf-wide"><dt>Research</dt><dd>${d.research.active.length ? 'Researching ' + esc([...new Set(d.research.active)].join(' · ')) : 'Not researching right now'} · ${Number(d.research.tested_7d).toLocaleString('en-US')} ideas tested this week, ${d.research.passed_7d} passed${d.research.cost_7d ? ', $' + Number(d.research.cost_7d).toFixed(2) + ' spent' : ''}</dd></div>` : ''}
      ${d.paper_progress ? `<div class="apf-wide"><dt>Furthest on paper</dt><dd><a href="/strategies/${d.paper_progress.strategy_id}">${esc(d.paper_progress.title || 'Paper strategy')}</a> · ${d.paper_progress.trades}/${d.paper_progress.trades_needed} paper trades · ${usd(d.paper_progress.net_pnl, true)}</dd></div>` : ''}`;
    }
    const staleEl = box.querySelector('#apf-stale'); if (staleEl) staleEl.textContent = apStale();
    const week = box.querySelector('#apf-week'); if (week) week.innerHTML = d.autopilot ? apWeek(d.week) : '';
    const msel = box.querySelector('#apf-model'); if (msel && msel.options.length && d.model && document.activeElement !== msel && !msel.disabled) msel.value = d.model;
    if (Array.isArray(d.focus)) apFocusPaint(box, d.focus);
    const fsel = box.querySelector('#apf-focus');
    if (fsel && Array.isArray(d.focus) && document.activeElement !== fsel && !fsel.disabled && fsel.dataset.cur !== d.focus.join(',')) apFocusOptions(fsel, d.focus);
    const gates = box.querySelector('#apf-gates');
    if (gates) {
      // Say why autopilot is quiet (or soon will be) here too, not only on the dashboard card.
      if (d.billing_blocked) {
        gates.innerHTML = `Autopilot is paused. <a href="/billing">${d.billing_reason === 'card' ? 'Add a payment method' : 'Add credits'}</a> to let it keep researching.`;
        gates.classList.add('warn');
      } else if (d.credits_low_days != null) {
        gates.innerHTML = `Credits run out ${d.credits_low_days < 1 ? 'within a day' : 'in about ' + Math.round(d.credits_low_days) + ' day' + (Math.round(d.credits_low_days) === 1 ? '' : 's')} at this week's pace, then research pauses. <a href="/billing">Add credits or turn on auto-reload</a>.`;
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
        <a class="btn sm ghost" href="/deploy">Open board</a>`;
      controls.querySelectorAll('[data-ap]').forEach((b) => (b.onclick = (e) => apAction(box, b.dataset.ap, e)));
    }
  }
  // Live armed with nothing live yet reads as "is it trading real money?", so say it outright.
  const apLiveArmed = (d) => d.autopilot_live && !d.live_running ? 'Live autopilot is armed. No strategy is trading real money yet.' : '';
  // Why live autopilot can't be enabled yet (ordered), or '' when all gates pass.
  function apLiveBlock(d) {
    if (!d) return '';
    if (!d.autopilot) return 'Turn on autopilot first — live autopilot builds on it. ';
    if (!d.live_enabled) return 'Live trading isn’t available on this server yet. ';  // no live button then, just this line
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
    if (!h || h.length < 2) return '';
    const W = 104, H = 30, p = 3, lo = Math.min(...h), hi = Math.max(...h), rng = hi - lo || 1;
    const pts = h.map((v, i) => `${(i / (h.length - 1) * (W - p * 2) + p).toFixed(1)},${(H - p - (v - lo) / rng * (H - p * 2)).toFixed(1)}`);
    return `<svg class="hot-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true"><polyline points="${pts.join(' ')}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }
  function hotRowHtml(m) {
    const catalog = (S.me.markets || []).find(c => c.series && c.series === m.s);
    const compactName = catalog ? marketShort(catalog.key) : ((m.ti || '').trim() || m.t);
    const mid = midOf(m), h = m.h || [], delta = h.length >= 2 ? h[h.length - 1] - h[0] : 0;
    const dCents = Math.round(delta * 100), dir = dCents > 0 ? 'pos' : dCents < 0 ? 'neg' : '';
    return `<a class="hot-row" href="${kalshiUrl(m)}" target="_blank" rel="noopener" aria-label="${esc(mktLabel(m))} · ${esc(m.t)} · ${mid == null ? 'Quote unavailable' : cents(mid)}${dCents ? ` · ${dCents > 0 ? '+' : '−'}${Math.abs(dCents)}¢ across available history` : ''} · ${kfmt(m.v24)} volume over 24 hours · Opens Kalshi in a new tab">
      <span class="hot-quote"><span class="hot-title" title="${esc(mktLabel(m))}"><strong>${esc(compactName)}</strong>${m.su && m.su.trim() !== (m.ti || '').trim() ? `<span>${esc(compactCondition(m.su))}</span>` : ''}</span><span class="hot-price" title="Midpoint quote"><b class="fig">${mid == null ? '—' : cents(mid)}</b>${dCents ? `<span class="hot-delta ${dir}" title="Change across available price history">${dCents > 0 ? '+' : '−'}${Math.abs(dCents)}¢</span>` : ''}</span></span>
      <span class="hot-foot"><span class="hot-meta"><span class="vh">${esc(m.s || '')}</span><span class="hot-vol" title="24-hour volume">${kfmt(m.v24)} · 24h</span></span><span class="vh">Opens Kalshi in a new tab</span></span></a>`;
  }
  function renderHotRail() {
    const rail = document.getElementById('hotrail'); if (!rail) return;
    const open = hotOpen();
    const d = S.hot;
    const snapshotAt = d && d.at ? Date.parse(d.at) : NaN;
    const snapshotAge = Number.isFinite(snapshotAt) ? Math.max(0, (Date.now() - snapshotAt) / 1000) : null;
    rail.classList.toggle('is-stale', !!d && (snapshotAge == null || snapshotAge > 180));
    const freshness = d ? `<span class="hot-freshness${snapshotAge == null || snapshotAge > 180 ? ' is-old' : ''}" title="Market snapshot time${snapshotAge > 180 ? ' · More than 3 minutes old' : ''}">${snapshotAge == null ? 'Snapshot time unavailable' : `${snapshotAge > 180 ? 'Stale' : 'Snapshot'} · ${esc(sinceMin(d.at))}`}</span>` : '';
    const rows = d && d.markets && d.markets.length ? d.markets.map(hotRowHtml).join('')
      : `<div class="hot-empty">${d ? 'Warming up — the live book fills in a minute.' : loading(120)}</div>`;
    const control = root.querySelector('.market-control');
    const toggle = `<button class="hot-tab" data-hot="toggle" aria-expanded="${open}" aria-controls="hotrail" aria-label="${open ? 'Collapse hot markets' : 'Expand hot markets'}" title="Hot markets"><span class="hot-tab-label">Hot markets</span><svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="2.5" y="3.5" width="15" height="13" rx="1.5"/><path d="M7.5 4v12"/></svg></button>`;
    if (control) {
      const button = control.querySelector('[data-hot="toggle"]');
      if (button) {
        button.setAttribute('aria-expanded', String(open));
        button.setAttribute('aria-label', open ? 'Collapse hot markets' : 'Expand hot markets');
      } else control.innerHTML = toggle;
    }
    rail.innerHTML = `${control ? '' : toggle}
      <div class="hot-panel">
        <div class="hot-head"><div><span class="hot-kicker">Hot markets</span>${freshness}</div></div>
        <div class="hot-list">${rows}</div>
        <div class="hot-ft"><a href="/explore">See all markets →</a></div>
      </div>`;
    root.querySelectorAll('[data-hot="toggle"]').forEach((b) => b.onclick = () => {
      const next = !hotOpen(); localStorage.setItem('tau_hotrail', next ? '1' : '0');
      document.body.classList.toggle('hot-open', next); renderHotRail();
      if (resizePaperChart) resizePaperChart();
    });
    rail.querySelector('.hot-ft a') && (rail.querySelector('.hot-ft a').onclick = (e) => { e.preventDefault(); go('/explore'); });
  }
  async function refreshHot() {
    try { S.hot = await api('/api/explore/hot', undefined, { keep: true }); renderHotRail(); } catch (e) {}
  }
  function mountHotRail() {
    if (!S.me || !S.me.user) return;
    document.body.classList.toggle('hot-open', hotOpen());
    if (!document.getElementById('hotrail')) { const a = document.createElement('aside'); a.className = 'hotrail'; a.id = 'hotrail'; document.body.appendChild(a); }
    renderHotRail();
    const stale = !S.hot || !S.hotAt || Date.now() - S.hotAt > 55000;
    if (stale) refreshHot().then(() => { S.hotAt = Date.now(); });
    if (!hotLoop) { hotLoop = true; setInterval(() => { if (!document.hidden && document.getElementById('hotrail')) refreshHot().then(() => { S.hotAt = Date.now(); }); }, 60000); }
  }

  const KIND_LABEL = { bonus: 'Welcome credits', topup: 'Added credits', autoreload: 'Auto-reload', usage: 'Agent usage', admin_grant: 'Admin grant' };
  // How long the balance lasts at last week's spend. Research pauses at $0, so autopilot users
  // need this more than the one-time welcome credit.
  const runwayLabel = (days) => days < 1 ? 'Under a day' : days > 90 ? 'Over 3 months' : `About ${Math.round(days)} day${Math.round(days) === 1 ? '' : 's'}`;
  async function viewBilling() {
    const gen = S.gen;
    shell('/billing', boardTitle('Billing') + '<details class="billing-pricing"><summary>Credit pricing</summary><p>Credits pay for research and chat, billed per token for the model you pick. Paper and live trading are free.</p></details>' +
      '<dl class="figures measure" id="bfigs" style="margin-top:14px"></dl>', loading(360));
    let stripe = null, card = null;
    const load = async () => {
      const d = await api('/api/billing');
      if (gen !== S.gen) return;
      root.querySelector('#bfigs').innerHTML =
        fig('Credit balance', usd(d.balance), { v: d.balance < 0 ? -1 : 0 }) +
        fig('Spent on usage', usd(d.spent)) +
        (d.runway_days != null
          ? fig('Credits last', runwayLabel(d.runway_days), { v: d.runway_days < 3 ? -1 : 0, small: `at ${usd(d.spent_7d)} a week` })
          : fig('Welcome credit', usd(d.free_bonus)));
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
      // At the user's own pace, how long the amount being bought would last: picks the amount for them.
      const lasts = (v) => (+d.spent_7d > 0 && v > 0) ? ` At your pace (${usd(d.spent_7d)} a week) that's ${runwayLabel(v / (d.spent_7d / 7)).toLowerCase()} of research.` : '';
      const upd = () => { const v = +amt.value || 0; note.textContent = `You'll pay ${usd(v * (1 + fee))} (${usd(v)} credits + ${d.topup_fee_pct}% fee).${lasts(v)}`; };
      amt.oninput = upd; upd();
      root.querySelector('#topup-btn').onclick = (e) => {
        if (e.currentTarget.getAttribute('aria-disabled')) { flash('#topup-flash', 'Add a card first.', 'bad'); return; }
        busy(e.currentTarget, async () => {
          const credits = +amt.value;
          try {
            const r = await api('/api/billing/topup', { amount: credits });
            if (gen !== S.gen) return;
            await load();  // refresh balance + ledger, then confirm into the fresh panel
            if (gen === S.gen) flash('#topup-flash', `Added ${usd(credits)} in credits. You paid ${usd(credits * (1 + fee))} — ${usd(credits)} plus the ${d.topup_fee_pct}% fee. New balance is ${usd(r.balance)}.`, 'good');
          } catch (err) { if (gen === S.gen) flash('#topup-flash', err.message, 'bad'); }
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
          if (gen === S.gen) flash('#autorel-flash', arBox.checked ? `On · reloads ${usd(amount)} at ${usd(threshold)}.` : 'Auto-reload off.', 'good');
        } catch (err) { arBox.checked = !arBox.checked; if (gen === S.gen) flash('#autorel-flash', err.message, 'bad'); }
      };
      arBox.onchange = saveAutoReload;
      arAmt.onchange = arThr.onchange = () => { if (arBox.checked) saveAutoReload(); };
      root.querySelectorAll('[data-remove]').forEach((b) => (b.onclick = () => armed(b, 'Confirm remove', () => busy(b, async () => {
        try { await api('/api/billing/remove-card', { payment_method_id: b.dataset.remove }); if (gen === S.gen) await load(); } catch (err) { if (gen === S.gen) alert0(err.message); }
      }))));
      // Stripe Payment Element (card + Apple Pay / Google Pay, Link off) — same
      // flow as the sign-in modal, so saving actually works with the config SI.
      try {
        const Stripe = await loadStripe();
        if (gen !== S.gen) return;
        const sp = Stripe(d.publishable_key);
        const si = await api('/api/billing/setup-intent', {});
        if (gen !== S.gen) return;
        const elements = sp.elements({ clientSecret: si.client_secret, appearance: { theme: 'flat', variables: { fontFamily: 'Archivo, sans-serif', colorPrimary: '#191B16', borderRadius: '10px' } } });
        const pe = elements.create('payment', { layout: 'tabs', wallets: { applePay: 'auto', googlePay: 'auto' }, fields: { billingDetails: { address: { country: 'never' } } } });
        pe.mount('#card-el');
        root.querySelector('#save-card').onclick = (e) => busy(e.currentTarget, async () => {
          flash('#card-flash', '', '');
          let r;
          try { r = await sp.confirmSetup({ elements, redirect: 'if_required', confirmParams: { return_url: location.origin + '/billing', payment_method_data: { billing_details: { address: { country: 'US' } } } } }); }
          catch (err) { if (gen === S.gen) flash('#card-flash', err.message || 'Could not save the card.', 'bad'); return; }
          if (gen !== S.gen) return;
          if (r.error) { flash('#card-flash', r.error.message, 'bad'); return; }
          try { await api('/api/billing/card-added', { payment_method_id: r.setupIntent.payment_method }); }
          catch (err) { if (gen === S.gen) flash('#card-flash', err.message, 'bad'); return; }
          if (gen !== S.gen) return;
          flash('#card-flash', 'Card saved.', 'good'); await load();
        });
      } catch (err) { if (gen === S.gen) flash('#card-flash', err.message, 'bad'); }
    };
    try { await load(); } catch (err) { if (gen === S.gen) throw err; }
  }
  function ledgerTable(rows) {
    if (!rows.length) return '<p class="hint">No credit activity yet.</p>';
    return `<div class="sheet"><table class="table stack t-dep t-ledger"><thead><tr><th>When</th><th>Item</th><th class="num">Amount</th></tr></thead><tbody>${rows.map((r) => `<tr>
      <td class="hint" data-lab="When">${when(r.created_at)}</td>
      <td class="name" data-lab="Item">${esc(KIND_LABEL[r.kind] || r.kind)}${r.memo && r.kind === 'usage' ? `<div class="sub-fig">${esc(r.memo)}</div>` : ''}</td>
      <td class="num" data-lab="Amount"><span class="${r.amount >= 0 ? 'gain' : ''}">${usd(r.amount, true)}</span></td></tr>`).join('')}</tbody></table></div>`;
  }

  // ---------- admin ----------
  async function viewAdmin() {
    if (!adminViewOn()) return go('/', true);
    const gen = S.gen;
    shell('/admin', boardTitle('Admin'), `
      <div class="detail">
        <div>
          <section class="sect"><div class="sect-head"><h2>Users</h2><span id="ucount" class="sect-note"></span></div><div id="users">${loading(200)}</div></section>
          <section class="sect"><div class="sect-head"><h2>Waitlist</h2></div><div id="waitlist"></div></section>
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
      if (gen !== S.gen) return;
      root.querySelector('#ucount').textContent = `${d.users.length} shown`;
      root.querySelector('#users').innerHTML = `<div class="sheet"><table class="table stack t-dep"><thead><tr><th>Email</th><th>Name</th><th>Joined</th><th class="num">Balance</th></tr></thead><tbody>${d.users.map((u) => `<tr>
        <td class="name" data-lab="Email">${esc(u.email)}</td><td data-lab="Name">${esc(u.name || '')}</td>
        <td class="hint" data-lab="Joined">${when(u.created_at)}</td><td class="num" data-lab="Balance">${usd(u.balance)}</td></tr>`).join('')}</tbody></table></div>`;
      root.querySelector('#waitlist').innerHTML = d.waitlist.length
        ? `<div class="sheet"><table class="table stack t-dep"><thead><tr><th>Email</th><th>Note</th><th>When</th><th>Status</th><th></th></tr></thead><tbody>${d.waitlist.map((w) => `<tr>
          <td class="name" data-lab="Email">${esc(w.email)}</td><td data-lab="Note">${esc(w.note || '')}</td><td class="hint" data-lab="When">${when(w.created_at)}</td>
          <td data-lab="Status">${w.status === 'approved' ? '<span class="mk on">Approved</span> <small class="hint">awaiting their sign-in</small>' : 'Requested'}</td>
          <td class="act" data-lab="">${w.status === 'approved' ? '' : `<button class="btn sm" data-wl="approve" data-email="${esc(w.email)}">Approve</button>`}<button class="btn sm danger" data-wl="remove" data-email="${esc(w.email)}">Remove</button></td></tr>`).join('')}</tbody></table></div>`
        : '<p class="hint">No waitlist requests.</p>';
      root.querySelectorAll('#waitlist [data-wl]').forEach((b) => (b.onclick = async () => {
        await busy(b, async () => {
          try { await api('/api/admin/waitlist', { email: b.dataset.email, action: b.dataset.wl }); if (gen === S.gen) await load(); }
          catch (err) { if (gen === S.gen) alert0(err.message); }
        });
      }));
    };
    root.querySelector('#grant').onsubmit = async (e) => {
      e.preventDefault();
      await busy(e.target.querySelector('[type=submit]'), async () => {
        try {
          const r = await api('/api/admin/grant', { email: root.querySelector('#g-email').value.trim(), amount: +root.querySelector('#g-amt').value });
          if (gen !== S.gen) return;
          flash('#g-flash', `Granted. ${esc(r.email)} balance: ${usd(r.balance)}.`, 'good'); await load();
        } catch (err) { if (gen === S.gen) flash('#g-flash', err.message, 'bad'); }
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
    api('/api/admin/kill-switch').then((k) => { if (gen !== S.gen) return; killShow(k); }).catch((err) => { if (gen === S.gen) flash('#k-flash', err.message, 'bad'); });
    root.querySelector('#kill').onsubmit = async (e) => {
      e.preventDefault();
      const btn = root.querySelector('#k-btn');
      await busy(btn, async () => {
        try {
          const k = await api('/api/admin/kill-switch', { on: !btn.dataset.on, reason: root.querySelector('#k-reason').value.trim() });
          if (gen !== S.gen) return; killShow(k);
        } catch (err) { if (gen === S.gen) flash('#k-flash', err.message, 'bad'); }
      });
    };
    try { await load(); } catch (err) { if (gen === S.gen) throw err; }
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
    const gen = S.gen;
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
    shell('/system', boardTitle('System'),
      `<div id="sys-error"></div><div class="sysmap">
         <div class="sys-wrap"><svg viewBox="0 0 900 540" preserveAspectRatio="xMidYMid meet" id="syssvg" aria-label="System map">${edges}${nodes}</svg></div>
         <aside class="sys-side">
           <section class="panel" id="sys-detail"><h3>Select a component</h3></section>
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
      detail.innerHTML = `<h3>${esc(n.label)}</h3><p class="sys-metric" id="sys-dm">${metricText(id, L) || ''}</p><p class="hint" style="margin-top:8px">${esc(SYS_DESC[id] || '')}</p>${open}`;
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
      let d;
      try { d = await api('/api/admin/system'); }
      catch (err) { if (gen === S.gen && err.status !== 401) flash('#sys-error', err.message, 'bad'); return; }
      if (gen !== S.gen) return;
      root.querySelector('#sys-error').innerHTML = '';
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
    if (gen === S.gen) poll(load, 4000);
  }

  setupGlossary();
  render();
})();
