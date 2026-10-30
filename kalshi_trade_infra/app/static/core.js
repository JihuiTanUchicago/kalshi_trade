/* Tau's shared core: the pure helpers both themes draw with alike, written once. Vanilla JS, no build step.
   The page runs it before the theme's bundle (app.js or app.meridian.js), which takes each helper from
   window.TauCore under its own name, so a fix here reaches Tau and Meridian at once. Only what reads no page,
   no account and no theme lives here: escaping, money, counts, dates and times, markdown. A helper that draws
   one theme's way stays in that theme's bundle. Every string that came from a user, an agent or the market
   goes through esc(). */
(() => {
  'use strict';

  // ---------- escaping, separators and markdown ----------
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

  // ---------- money, shares and prices ----------
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
  // The sign is the shown amount's, rounded as shown: −0.002 read "−$0.00" (the track record's Avg trade for a
  // strategy a fraction of a cent down), a sign on a figure that reads as no money either way.
  const usd = (v, signed = false) => {
    if (v == null || Number.isNaN(+v)) return '—';
    const n = Math.abs(+v) >= 100000 ? Math.round(+v) : halfUp(+v);
    const s = '$' + (Math.abs(n) >= 100000 ? fmt0.format(Math.abs(n)) : fmt2.format(Math.abs(n)));
    if (n < 0) return '−' + WJ + s;
    return signed && n > 0 ? '+' + WJ + s : s;
  };
  // A share to one decimal of a percent, its sign the shown figure's (−0.0001 read "−0.0%").
  const pct = (v, signed = true) => {
    if (v == null) return '—';
    const n = halfUp(+v * 100, 1);
    return (n < 0 ? '−' : signed && n > 0 ? '+' : '') + Math.abs(n).toFixed(1) + '%';
  };
  // Kalshi quotes some markets in tenths of a cent: 0.1¢ read as 0¢ and a 99.9¢ bid as 100¢.
  const cents = (v) => (v == null ? '—' : Math.round(v * 1000) / 10 + '¢');
  const isPerpetual = (s) => s.kind === 'perpetual' || s.market === 'btc_perp' || s.key === 'btc_perp' || (s.spec && s.spec.market === 'btc_perp');
  const researchOnly = (s) => s.research_only === true || isPerpetual(s);
  const researchBadge = (s) => researchOnly(s) ? '<span class="mk quiet">Research only</span>' : '';
  const tone = (v) => (v > 0 ? 'gain' : v < 0 ? 'loss' : '');

  // ---------- dates and times ----------
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
  // An open position's mark (the last price the engine read for it) is old past MARK_OLD_S. The engine stamps every
  // open position's mark on each pass over the markets, and each pass ends with a 15s sleep (TICK_SECONDS), so a mark
  // is normally under 20s old; one slow Kalshi read (20s timeout, 429 backoff) can stretch a pass toward a minute.
  // The engine stops trusting a mark for its risk triggers at 90s (MARK_MAX_AGE_SECONDS), and the chat calls the
  // engine stopped at 5 minutes (ENGINE_STALE_SECONDS). Three minutes is twice the engine's gate and several slow
  // passes, so a running feed never trips it (a minute of this device's clock running fast included), while a stopped
  // engine or a contract that lost its bid trips it three minutes on, at the page's next poll. Display only: the
  // figure is the same either way.
  const MARK_OLD_S = 180;
  const markOld = (iso) => { const ms = Date.parse(iso || ''); return Number.isFinite(ms) && (Date.now() - ms) / 1000 > MARK_OLD_S; };
  // A figure an old mark priced, dimmed (.mark-old): undimmed, an hours-old figure read as this minute's.
  const markFig = (iso, html) => (markOld(iso) ? `<span class="mark-old">${html}</span>` : html);
  // A time with its zone on one line: the market page's "Closes Oct 28, 02:45" left "UTC" alone on the next.
  const keepZone = (t) => String(t).replace(/ (?=\S+$)/, '\u00a0');

  // ---------- counts and text ----------
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

  // ---------- stored money and counts ----------
  // Stored money (4 places: a position's pnl, fees, prices) summed exactly, as the server's SUM is, before usd()
  // rounds it once, half up. Adding the floats drifted: −0.0036 + −0.1314 is −0.13499…, which read −$0.13 beside
  // the track record's −$0.14 for the same two trades.
  const sum4 = (xs) => xs.reduce((a, v) => a + Math.round((+v || 0) * 1e4), 0) / 1e4;
  const money = (v) => `<span class="${tone(v == null ? v : halfUp(+v))}">${usd(v, true)}</span>`;
  const kfmt = (n) => { n = +n || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n)); };
  const sinceMin = (iso) => { if (!iso) return '—'; const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000); return s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + 'm ago' : s < 172800 ? Math.round(s / 3600) + 'h ago' : Math.round(s / 86400) + 'd ago'; };

  // ---------- paper P&L words ----------
  // What every paper P&L figure includes, said beside it (services/customer_text.PAPER_NET; the bundles'
  // paperfills bubble is its PAPER_FILLS). Paper already fills at the ask and bid and pays Kalshi's fee.
  const PAPER_NET = 'after Kalshi fees and the spread';
  // An open position the engine hasn't priced yet (it marks it on its next tick), in one phrase on every page: Deploy's
  // rows and open positions, the dashboard's, a market page's and the strategy page's. It read "Unavailable", "—",
  // "not marked yet" and "awaiting first mark" for the same thing. Display only: how a mark is read is unchanged.
  const NOT_MARKED = 'Not marked yet';
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

  window.TauCore = Object.freeze({
    esc, SEP, sepLine, mdInline, mdLite, feedMd, authorLine, fmt2, fmt0, halfUp, WJ, plain, usd, pct, cents,
    isPerpetual, researchOnly, researchBadge, tone, when, bellTime, dateFmt, CLOCK, CLOCK_ZONE, WEEKDAY_DAY,
    YEAR_DAY, UTC_MONTH, clock, tzName, logTime, settleAt, markOld, markFig, keepZone, num, compact, clipWords, age,
    sum4, money, kfmt, sinceMin, PAPER_NET, NOT_MARKED, slipText, slipEst, slipTip
  });
})();
