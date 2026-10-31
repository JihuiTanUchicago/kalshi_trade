/* Tau's shared core: the pure helpers both themes draw with alike, written once. Vanilla JS, no build step.
   The page runs it before the theme's bundle (app.js or app.meridian.js), which takes each helper from
   window.TauCore under its own name, so a fix here reaches Tau and Meridian at once. Only what reads no page,
   no account and no theme lives here: escaping, money, counts, dates and times, markdown, the icons and the
   glossary's words, and the words and pieces both themes draw alike (P&L lines, the track record's, Explore's,
   the autopilot's). A helper that draws one theme's way stays in that theme's bundle. Every string that came
   from a user, an agent or the market goes through esc(). */
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
  // A bare link and an @handle are found only in text, never inside a tag this built: a post's
  // "[x](https://a(https://b/onmouseover=…)" autolinked the inner https:// inside the first link's href, and
  // its quote closed that href, so the rest of the post's words became an attribute (an event handler) on
  // another reader's page; "https://x.com/@bob" put a mention's quoted class inside the href. A link's own
  // words (its label, a bare link's text) are left as they are.
  const MD_AUTO = /<[^>]*>|(?<=^|[\s(])https?:\/\/[^\s<)]+|(?<![\w@])@[a-zA-Z0-9_]{2,32}/g;
  const mdInline = (t) => {
    t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    t = t.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
    t = t.replace(/(^|[^\w])_([^_\n]+)_(?![\w])/g, '$1<i>$2</i>');   // _italic_ (never snake_case)
    t = t.replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s<>"]+)\)/g, '<a href="$2" target="_blank" rel="noopener nofollow">$1</a>');
    // Bare links, and @handle mentions (not inside an email: a word char before @ blocks it)
    let inLink = false;
    return t.replace(MD_AUTO, (m) => {
      if (m[0] === '<') { if (/^<a\s/.test(m)) inLink = true; else if (m === '</a>') inLink = false; return m; }
      if (inLink) return m;
      return m[0] === '@' ? `<span class="mention">${m}</span>` : `<a href="${m}" target="_blank" rel="noopener nofollow">${m}</a>`;
    });
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
  // A share to one decimal of a percent, its sign the shown figure's (−0.0001 read "−0.0%"). Grouped in thousands as
  // the dollar figures beside it are: a strategy's return on capital read "+1582.3%" (walked 2026-10-30).
  const fmt1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const pct = (v, signed = true) => {
    if (v == null) return '—';
    const n = halfUp(+v * 100, 1);
    return (n < 0 ? '−' : signed && n > 0 ? '+' : '') + fmt1.format(Math.abs(n)) + '%';
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
    // Past a day it names its zone ("Oct 27, 22:26 EDT"), as the trade list's clock does: the bare clock didn't say whose.
    // One from another year names it ("Sep 26, 2025, 09:34 EDT"): a year-old notice read as this September's.
    const stamp = dateFmt(d, d.getFullYear() === new Date().getFullYear() ? LOG_STAMP : LOG_STAMP_YEAR);
    const shown = Date.now() - d.getTime() < 86400000 ? when(iso) : stamp;
    return `<time datetime="${esc(iso)}" title="${esc(stamp)}">${esc(shown)}</time>`;
  };
  // What a grouped bell line stands for past its own words, from the server's `more`, `alike`, `from` and
  // `from_more` (app/services/bell.py), as text (the caller escapes it: the names are people's own). "and 3 more
  // like this" only when all of them say the same words: over replies from three people it read as if the shown
  // one's author had written them all, and over a strategy's earlier pause (another reason, maybe another book)
  // as the same pause again. Replies and mentions say whom the rest are from.
  const BELL_MORE = { comment: ['reply', 'replies', 'to this post'], mention: ['mention', 'mentions', 'on this post'],
    paused: ['earlier pause', 'earlier pauses', 'of this strategy'], reload_failed: ['earlier failed auto-reload', 'earlier failed auto-reloads', ''] };
  const bellMore = (n) => {
    const k = +(n && n.more) || 0;
    if (!k) return '';
    if (n.alike !== false) return `and ${num(k)} more like this`;
    const [one, many, about] = BELL_MORE[n.kind] || ['earlier notice', 'earlier notices', 'about this'];
    const names = (Array.isArray(n.from) ? n.from : []).map(String).filter(Boolean), rest = +n.from_more || 0;
    if (names.length && rest > 0) names.push(`${num(rest)} other${rest === 1 ? '' : 's'}`);
    const from = !names.length ? '' : `, from ${names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]}`;
    const more = n.kind === 'comment' || n.kind === 'mention' ? 'more ' : '';
    return `and ${num(k)} ${more}${k === 1 ? one : many}${about ? ' ' + about : ''}${from}`;
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
  const WEEKDAY_DAY = { weekday: 'short', month: 'short', day: 'numeric' };
  const YEAR_DAY = { year: 'numeric', month: 'short', day: 'numeric' };
  const UTC_MONTH = { year: 'numeric', month: 'short', timeZone: 'UTC' };
  const LOG_STAMP = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' };
  const LOG_STAMP_YEAR = { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' };
  const clock = (iso) => dateFmt(new Date(iso), CLOCK);
  // The reader's zone ("EDT"), for a line that says once which zone the bare clock times are in. `at` (epoch ms)
  // names the zone in force then: a market's price history across the November clock change labelled its last
  // time "06:00 EDT", an hour that was EST.
  const tzName = (at) => { try { return (new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(at == null ? new Date() : new Date(at)).find((p) => p.type === 'timeZoneName') || {}).value || ''; } catch (e) { return ''; } };
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
  // A volume in a narrow column (the hot rail): "9.0k", "1.2M". A count that rounds up into the next unit takes it:
  // 999,960 read "1000.0k" and 999.6 "1000" (walked 2026-10-31).
  const kfmt = (n) => { n = +n || 0; return n >= 999950 ? (n / 1e6).toFixed(1) + 'M' : n >= 999.5 ? (n / 1e3).toFixed(1) + 'k' : String(Math.round(n)); };
  const sinceMin = (iso) => { if (!iso) return '—'; const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000); return s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + 'm ago' : s < 172800 ? Math.round(s / 3600) + 'h ago' : Math.round(s / 86400) + 'd ago'; };

  // ---------- paper P&L words ----------
  // What every paper P&L figure includes, said beside it (services/customer_text.PAPER_NET; the glossary's
  // paperfills bubble, below, is its PAPER_FILLS). Paper already fills at the ask and bid and pays Kalshi's fee.
  const PAPER_NET = 'after Kalshi fees and the spread';
  // An open position the engine hasn't priced yet (it marks it on its next tick), in one phrase on every page: Deploy's
  // rows and open positions, the dashboard's, a market page's and the strategy page's. It read "Unavailable", "—",
  // "not marked yet" and "awaiting first mark" for the same thing. Display only: how a mark is read is unchanged.
  const NOT_MARKED = 'Not marked yet';
  // A book's unrealized P&L summed over only some of its open positions (the rest not marked yet) says how many it
  // covers: "2 open positions at cost + fees $2.47 · unrealized +$0.30" read as both positions' figure when only one
  // was priced. "1 of 2" when some but not all are marked, '' otherwise. Display only: no figure changes.
  const markedOf = (marked, open) => (+marked > 0 && +marked < +open ? `${fmtCount.format(+marked)} of ${fmtCount.format(+open)}` : '');
  // What it leaves out is the price moving before a real order lands. Beside the paper headline figures (the
  // dashboard's, the strategy page's "Since deploying" and its ladder, the track record's paper tab, the
  // Strategies list's paper card, Deploy's paper Realized, the autopilot's paper figures, the dashboard strip's paper
  // book, Funds' paper balance and a finished session's "Paper since deploying"), the server's
  // slippage_estimate (trading_core/domain/slippage.py) says what they might have been after it: muted, an
  // estimate with its assumption, never in place of the P&L. Paper only: live and demo never carry one.
  // slipTip says the same words as a title, where a figure sits inside a line about another book.
  const slipText = (e) => (e && e.pnl != null && Number.isFinite(+e.pnl)
    ? `≈ ${usd(e.pnl, true)} after typical live slippage (estimate: ${+e.per_fill_cents}¢ a contract each time an order fills)` : '');
  const slipEst = (e) => (slipText(e) ? `<span class="slip-est">${slipText(e)}</span>` : '');
  const slipTip = (e) => (slipText(e) ? ` title="${esc(slipText(e))}"` : '');

  // ---------- brand mark, icons and the glossary ----------
  // The brand mark, then the icons: one stroke, one weight.
  const TAU_MARK = '<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="15" fill="#15161A"/><path d="M18 24h28M32 24v22" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/><circle cx="32" cy="48" r="3.5" fill="#F05A28"/></svg>';
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
  // The glossary's words (info bubbles); each bundle's setupGlossary draws the bubble.
  // Plain-language definitions for the jargon the agent produces. Keep each to a
  // sentence or two; "plain language first, numbers second".
  // Void and Rejected say "the history the agent searched" for in-sample, and never out-of-sample: the strategies list's
  // bubbles are the first place a new account meets them, and those words are defined nowhere it looks (walk 2026-10-31).
  const GLOSSARY = {
    passed: ['Passed', 'Cleared every gate on data the agent never saw while searching. Only passed strategies can be deployed.'],
    void: ['Void', 'The strategy did well enough on the history the agent searched to be tested on unseen data, but it failed at least one gate there. A real candidate that didn’t hold up.'],
    rejected: ['Rejected', 'Cut while the agent was still searching, on the history it searches, before any test on unseen data. It never reached that test.'],
    unseen: ['Later-period P&L (unseen data)', 'What the strategy made in the backtest after its split date, on a held-out slice of history the agent never looked at while searching, so the result can’t be curve-fit. This is the backtest figure that counts.'],
    laterperiod: ['Later-period P&L', 'What the strategy made in the backtest after its split date. That later stretch is what picked it, so unlike unseen data it wasn’t held out: a weaker test.'],
    // A Void strategy's later stretch picked nothing: the first version's simple backtest judged it there, it failed, and
    // nothing says the stretch was held out ("what picked it" was wrong for it). Its page's bubble says this instead.
    latervoid: ['Later-period P&L', 'What the strategy made in the backtest after its split date, where it failed its checks. There’s no record that stretch was held out, so unlike unseen data it isn’t held-out evidence.'],
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
    // The estimate beside a paper figure on the dashboard (slipEstGl): "≈ after typical live slippage" said nothing of
    // what slippage is to a new account. Its meaning is the owner's: an estimate beside paper P&L, never in its place.
    slippage: ['After typical live slippage', 'A real order can fill at a worse price than the one quoted, because the price moves in the second or two before it lands. Paper trades don’t pay for that, so this estimate takes a little off each fill (the amount it names) to show roughly what live trading might have made. It is only an estimate: the paper P&amp;L beside it is the figure, and the checks toward live use that figure.'],
    stake: ['Stake', 'How much a strategy spends on each trade it opens. “Stake not set” means the deployment’s saved rules carry no trade size, so there is no amount to show.'],
  };
  // The stretch of time each paper P&L figure on the dashboard counts, said first and in these words in both themes: the
  // strip's Money row, the money band, the autopilot card, its week and its panel's day. A new account met three paper
  // figures on one screen (the last 24 hours, all time, and today in UTC) with nothing saying why they differed.
  // Display only: every figure is the server's, as before.
  const PNL_WINDOW = { day: 'Last 24 hours', visit: 'Since your last visit', week: 'Last 7 days', today: 'Today (UTC)', all: 'Since you started' };
  const pnlWin = (k) => `<span class="pnl-win">${PNL_WINDOW[k]}:</span>`;
  // On the dashboard (its money band, the autopilot card, its week and its panel's day) the estimate carries the
  // slippage bubble (slipText from the core), glued to its last word. The other pages keep slipEst as it was.
  const slipEstGl = (e) => (slipText(e) ? `<span class="slip-est">${gl(slipText(e), 'slippage')}</span>` : '');
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

  // ---------- live trading not open yet, in words ----------
  const LIVE_CLOSED = 'Live trading isn’t open yet.';
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

  // ---------- prices, marks and market names ----------
  // The catalog's own labels (marketLabel and the names built on it) stay in each bundle, which reads the catalog.
  const perpsPrice = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6});
  const tradePrice = (v, perpetual) => perpetual ? (!['number', 'string'].includes(typeof v) || String(v).trim() === '' || !Number.isFinite(Number(v)) ? '—' : perpsPrice.format(Number(v))) : cents(v);
  // A mark's "as of" (HTML): a fresh one gives its time and zone (settleAt). An old one says its age in words ("as of
  // 14 min ago", short enough for a phone's stacked card), and its time and what an old mark means ride in a title
  // and in text a screen reader reads. "as of 05:31 UTC, 3h ago" beside an undimmed figure still read as current.
  const markedAt = (iso, lead = 'as of') => {
    if (!markOld(iso)) return `${lead} ${esc(settleAt(iso))}`;
    const why = `Last marked ${settleAt(iso)}. No newer price has come in, so this figure may be out of date.`;
    return `<span class="mark-age" title="${esc(why)}">${lead} ${apAgo(iso)}<span class="vh"> (${esc(why)})</span></span>`;
  };
  // Short, consistent chip labels for every market; unknown keys fall back to the
  // server's full label, never the raw key (keeps the market chips uniform).
  const MKT_SHORT = {
    // Each coin says the contract and its close, not just the coin and an hour ("BTC 5pm" was every kind),
    // with no " · " inside: lists and chips join labels with it, and "BTC above $X · 5pm ET" read as two.
    // A 5pm ladder says its strike in words, as the server's customer_label does ("a set price"; a chip drops the "a"
    // to fit a phone row's 30 characters), never "$X": walked 2026-10-30, Explore's chips read "BTC ABOVE $X AT 5PM ET".
    // A contract fills its own strike in (strikeIn).
    btc15m: 'BTC 15-min up/down', btc15m_tick: 'BTC 15-min up/down, per second', btc_perp: 'BTC perpetual, no expiry',
    btc_daily: 'BTC above set price at 5pm ET', eth15m: 'ETH 15-min up/down', eth_daily: 'ETH above set price at 5pm ET',
    sol15m: 'SOL 15-min up/down', sol_daily: 'SOL above set price at 5pm ET', xrp15m: 'XRP 15-min up/down', xrp_daily: 'XRP above set price at 5pm ET',
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
  // No market picked: the agent chooses. Said as a market ("Any market (agent’s choice)"), since a header or
  // row shows it beside other labels ("Agent’s choice · Session" didn’t say it was the market). Display only:
  // the stored market stays empty and the research model is sent nothing new.
  const NO_MARKET = 'Any market (agent’s choice)';
  // ---------- a market's two names ----------
  // Every market has one long name and one short name, and every page says it by one of the two, from here:
  //   long  (mktLong): the server's customer_label (app/trading/markets.py), sent as the catalog's `label` (me.markets)
  //         or, for a market the catalog leaves out (the perpetual while perps are closed), me.market_names. For a
  //         sentence, a row's or a page's own market, a position. The server's feed, chat, bell and email lines say it too.
  //   short (mktShort): MKT_SHORT above, for chips, filters and meta lines joined by " · ".
  // Each falls back to the other, and a key neither knows reads UNLISTED_MARKET, never the raw key; no market at all
  // is NO_MARKET. Walked 2026-10-31: one market read "BTC 15-min up/down", "Bitcoin 15-minute" and "Bitcoin up or
  // down in 15 minutes", and a perpetual strategy's page "BTC perpetual, no expiry" over a Market line "Unlisted market".
  // `me` is the bundle's signed-in answer (S.me); nothing here reads the page.
  const UNLISTED_MARKET = 'Unlisted market';
  const mktCatalog = (k, me) => {
    const m = k && me && (me.markets || []).find((x) => x.key === k);
    return (m && m.label) || (k && me && me.market_names && me.market_names[k]) || '';
  };
  const mktLong = (k, me) => (!k ? NO_MARKET : mktCatalog(k, me) || MKT_SHORT[k] || UNLISTED_MARKET);
  const mktShort = (k, me) => (!k ? NO_MARKET : MKT_SHORT[k] || mktCatalog(k, me) || UNLISTED_MARKET);
  // Whether a key is a market the app can name (a line quoting one by its key can be said in words).
  const mktKnown = (k, me) => !!(k && (MKT_SHORT[k] || mktCatalog(k, me)));
  // The readable market a contract ticker belongs to, by its series prefix (KXBTCD-26OCT2617-T68499.99 is
  // "Bitcoin $68,500 or above at 5pm ET", as Kalshi names it), so an open position never shows only the raw ticker. Unknown: ''.
  // A market kept to one close hour (close_hour_et: the 5pm close of the KXBTCD ladder) owns only the
  // contracts whose event closes then: KXBTCD-26OCT2700 is the midnight contract, which no strategy trades.
  const contractHour = (ticker) => { const m = /^[^-]+-\d{2}[A-Z]{3}\d{2}(\d{2})(?:-|$)/.exec(String(ticker || '')); return m ? +m[1] : null; };
  // An ET hour as a close says it: "noon", "midnight", "9am", "5pm".
  const hourET = (h) => (h === 12 ? 'noon' : h === 0 ? 'midnight' : `${h % 12}${h < 12 ? 'am' : 'pm'}`);
  // A ladder market's label says "a set price" for the strike; one contract says its own (-T68499.99), as its rules
  // do, to its last decimal: an XRP strike runs to four (-T2.4599), and num() rounds past three.
  const LADDER_WORDS = /above (?:a )?set price/;
  const strikeIn = (label, ticker) => {
    const k = /-T(\d+)(\.\d+)?$/.exec(String(ticker || ''));
    if (!k) return label;
    // A KXBTCD -T contract is Yes when Bitcoin ends above its strike (services/btc_spot.py contract_strike), and
    // Kalshi names one whose strike is a cent under a whole dollar by that dollar: -T112999.99 is "$113,000 or
    // above", the market page's heading. Walked 2026-10-30: the line under that heading said "Bitcoin above
    // $112,999.99 at 5pm ET", two prices for one line. Display only: the ticker and the stored strike are unchanged.
    // Any other strike, and a KXBTC -T end (the ticker doesn't say which way it points), keeps its exact figure.
    if (/^KXBTCD-/.test(String(ticker)) && k[2] === '.99' && LADDER_WORDS.test(label)) return label.replace(LADDER_WORDS, `$${num(+k[1] + 1)} or above`);
    return label.replace(LADDER_WORDS, 'above $' + num(k[1]) + (k[2] || ''));
  };
  // Bitcoin series the app shows (Explore, the hot rail, a market page, a position held at Kalshi) that no
  // market here covers: KXBTC's hourly price ranges. Each still says its contract and close as the markets above
  // do, [chip, name], never the raw series or another market's label. Every series of services/btc_spot.py's
  // BTC_SERIES is a market's or here (test_every_bitcoin_series_the_app_shows_has_a_label).
  const SERIES_SHORT = { KXBTC: ['BTC range at {h} ET', 'Bitcoin range at {h} ET'] };
  const kalshiRef = (ticker) => `<span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">${esc(ticker)}</span></span>`;

  // ---------- page pieces ----------
  const boardTitle = (title, sub = '') => `<div class="board-title"><h1 class="page">${esc(title)}</h1>${sub ? `<p class="deck">${sub}</p>` : ''}</div>`;
  // What a page is for, in one line under its name, in Tau's words and Research's lede style. Deploy and Settings
  // opened on their figures or a form with no word on what the page holds.
  const pageLede = (text) => `<p class="lede page-lede">${text}</p>`;
  // Settings' email switch. It writes app_users.email_opt_out, the field the unsubscribe link in
  // community emails also sets; the server checks it before every optional email. Perps safety
  // alerts and the failed auto-reload email never read it, and the copy says so.
  // `open` is the server's live switch (liveOpen): closed, that email says the strategy waits on paper, so the line
  // names it as the email does ("cleared every paper-to-live check"), never "ready for live trading".
  const emailState = (off, open = true) => {
    const ready = open ? 'a paper strategy that’s ready for live trading' : 'a paper strategy that clears every paper-to-live check';
    return off
      ? `Off. Tau doesn’t email you about replies to your posts, mentions of your @name, new community posts, or ${ready}. The bell in Tau still shows replies, mentions and ${open ? 'ready-for-live notices' : 'those paper-to-live notices'}.`
      : `On. Tau emails you about replies to your posts, mentions of your @name, new community posts (at most one email every 4 hours), and ${ready}.`;
  };
  // One measured cell. Money direction rides a tint field behind the figure
  // (opts.v), never a colour on the digits and never the reserved signal red.
  // Its sub-line ("paper money, not real") is a second <dd> of the same term: as a bare <div> in the <dl>
  // it fell outside the list, and a screen reader read the figure without what kind of money it is.
  const fig = (label, value, opts = {}) =>
    `<div class="m ${opts.cls || ''}"><dt class="lab">${label}</dt><dd><span class="fig ${opts.v > 0 ? 'tint pos' : opts.v < 0 ? 'tint neg' : ''}">${value}</span></dd>${opts.small ? `<dd class="sub-fig">${opts.small}</dd>` : ''}</div>`;
  // quiet: the words go out through announce(), so the notice leaves off its own live role (read once).
  // Tau's words that send someone to Funds ("... on the Funds page ...": an engine pause reason, a deploy
  // or live-autopilot refusal) name it as a link to Funds' Connect Kalshi; it was plain text, with nothing to
  // press. Takes text already escaped (esc), so only these fixed words become markup and whatever else the
  // server said stays escaped.
  const fundsLinked = (html) => String(html).replace(/\b(?:the )?Funds page\b/, '<a href="/funds#connect-kalshi">$&</a>');
  const notice = (msg, kind = '', quiet) => `<div class="notice ${kind}"${quiet ? '' : ` role="${kind === 'bad' ? 'alert' : 'status'}"`}>${kind === 'good' ? ICON.check : ICON.warn}<span>${fundsLinked(esc(msg))}</span></div>`;
  // A failed load says so and offers a retry, instead of leaving a skeleton up for good.
  // A section whose own read failed on a page that otherwise loaded names itself and says the rest is there
  // (`what`): the dashboard's track record said only "Something went wrong on our side." (walk 2026-10-28).
  const loadFail = (msg, what) => `<div class="load-fail">${notice(what ? `${what} didn\u2019t load. ${msg} Everything else on this page did.` : msg, 'bad')}<button type="button" class="btn sm" data-retry>Try again</button></div>`;
  const loading = (h = 160) => `<div class="skeleton" style="height:${h}px" aria-label="Loading"></div>`;
  // Boot screens: shown only while /api/me is in flight (splash) or after it timed out or failed for a
  // reason other than being signed out (fail). Reuses the landing wordmark + spinner so it's on-world with zero new look.
  const bootSplash = () => `<div class="boot"><div class="lbrand">${ICON.mark}<span>Tau</span></div><div class="lspin" aria-label="Loading Tau"></div></div>`;
  const BEHIND = ' The page didn’t refresh, so reload to see it.';

  // ---------- charts ----------
  // The points of a [time, value] series a chart can draw: a null, NaN or Infinity time or value is left out. One
  // such point made the whole polyline "NaN,NaN …" (nothing drawn) and an axis label "$NaN".
  const finitePts = (curve) => (Array.isArray(curve) ? curve : []).filter((p) => p && p[0] != null && p[1] != null && Number.isFinite(+p[0]) && Number.isFinite(+p[1]));
  // A long series cut to about `n` points for drawing: the first and last kept exactly, and each run between keeps
  // its lowest and highest point in time order, so every dip and peak that can show at that width still does. A
  // 10,000-trade backtest drew a 117KB polyline, a dozen points to each pixel. A series of `n` or fewer is as given.
  function thinCurve(curve, n) {
    if (!curve || curve.length <= n) return curve;
    const runs = Math.max(1, Math.floor((n - 2) / 2)), inner = curve.length - 2, out = [curve[0]];
    for (let r = 0; r < runs; r++) {
      const a = 1 + Math.floor((r * inner) / runs), b = 1 + Math.floor(((r + 1) * inner) / runs);
      if (b <= a) continue;
      let lo = a, hi = a;
      for (let i = a + 1; i < b; i++) { if (curve[i][1] < curve[lo][1]) lo = i; if (curve[i][1] > curve[hi][1]) hi = i; }
      if (lo === hi) out.push(curve[lo]); else out.push(curve[Math.min(lo, hi)], curve[Math.max(lo, hi)]);
    }
    out.push(curve[curve.length - 1]);
    return out;
  }
  // A chart's figures in words, for its accessible name: when it runs, where it starts and ends, and its low and
  // high with when each came ("from Oct 3 to Oct 31: starts at $0.00, ends at +$12.40; low −$3.10 (Oct 4), high
  // +$15.00 (Oct 28)"). A chart's name said what it was and, at most, where it ended: a screen reader heard
  // nothing of a deep dip on the way. `fmt` writes a value (dollars, stakes, cents), `day` a time.
  function curveWords(curve, fmt, day) {
    const pts = finitePts(curve);
    if (!pts.length) return '';
    let lo = pts[0], hi = pts[0];
    pts.forEach((p) => { if (+p[1] < +lo[1]) lo = p; if (+p[1] > +hi[1]) hi = p; });
    const a = pts[0], b = pts[pts.length - 1], f = (v) => plain(fmt(+v));
    const span = day(a[0]) === day(b[0]) ? `on ${day(a[0])}` : `from ${day(a[0])} to ${day(b[0])}`;
    const range = f(lo[1]) === f(hi[1]) ? `flat at ${f(lo[1])}` : `low ${f(lo[1])} (${day(lo[0])}), high ${f(hi[1])} (${day(hi[0])})`;
    return `${span}: starts at ${f(a[1])}, ends at ${f(b[1])}; ${range}`;
  }
  // The box a price trace (the hot rail's, a market picker row's: Yes prices, 0 to 1) is drawn in. Each filled its
  // box between its own low and high, so a market that ticked 1¢ drew the same full-height swing as one that moved
  // 40¢, and a 47¢/48¢ flicker read as a crash and a rally. The box spans at least 10¢, centred on the trace and
  // kept inside 0–100¢: a flat trace is a flat line and a 1¢ tick a small step.
  function traceScale(h) {
    const lo0 = Math.min(...h), hi0 = Math.max(...h), span = Math.max(0.1, hi0 - lo0);
    let lo = (lo0 + hi0) / 2 - span / 2;
    if (lo0 >= 0 && hi0 <= 1) lo = Math.max(0, Math.min(1 - span, lo));
    return { lo, hi: lo + span };
  }
  // Registered scale: every sparkline in a set shares one dollar axis, so
  // slips compare at a glance instead of each filling its own box.
  function registry(curves) {
    let lo = 0, hi = 0;
    curves.forEach((c) => finitePts(c).forEach(([, v]) => { lo = Math.min(lo, +v); hi = Math.max(hi, +v); }));
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
  // Its name says its low and high as well as where it ends (a curve that fell to −$40 and recovered to +$2 was
  // read "+$2.00 over 30 trades"), and, given the deployment's `mode`, which money it is: a sparkline is read out
  // on its own, away from the row's Paper / Demo / Live mark.
  const SPARK_BOOK = { paper: 'Paper', demo: 'Demo', live: 'Live' };
  function spark(curve, reg, trades, mode) {
    curve = finitePts(curve);
    if (curve.length < 2) return '';
    const W = 80, H = 24;
    reg = reg || registry([curve]);
    const t0 = +curve[0][0], t1 = +curve[curve.length - 1][0];
    const x = t1 > t0 ? (p) => ((p[0] - t0) / (t1 - t0)) * W : (p, i) => (i / (curve.length - 1)) * W;
    const y = (v) => H - 2 - ((v - reg.lo) / (reg.hi - reg.lo)) * (H - 4);
    const pts = curve.map((p, i) => `${x(p, i).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');
    const last = +curve[curve.length - 1][1], n = trades == null ? curve.length : +trades;
    const vals = curve.map((p) => +p[1]), lo = Math.min(...vals), hi = Math.max(...vals);
    const range = lo === hi ? `flat at ${usd(lo, true)}` : `low ${usd(lo, true)}, high ${usd(hi, true)}`;
    const label = `${SPARK_BOOK[mode] ? SPARK_BOOK[mode] + ' cumulative' : 'Cumulative'} P&L, ${usd(last, true)} over ${num(n)} trade${n === 1 ? '' : 's'}; ${range}`;
    return `<svg class="spark ${last > 0 ? 'up' : last < 0 ? 'down' : 'flat'}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" preserveAspectRatio="none" role="img" aria-label="${esc(plain(label))}"><line class="spark-zero" x1="0" x2="${W}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" vector-effect="non-scaling-stroke"/><polyline points="${pts}" vector-effect="non-scaling-stroke"/></svg>`;
  }
  // The underwater drawdown plot: the research paper's third figure, and the track record's.
  // `drawn`: a drawdown series the server already built from every trade (the track record sends
  // one, since its equity curve is thinned and could have lost the peak a drop started from).
  // `fmt` labels the worst drop: dollars for the track record, stakes for a research phase.
  // `opts.words` (a research phase's figure): its name says its span and its worst drop with when that came; a
  // series that never fell from a high says so, under one zero label, where "0" and "0.0×" were drawn on top of
  // each other; and the zero carries the unit (fmt(0)). The track record's figure keeps its own name and labels.
  function rpUnderwater(curve, drawn, fmt = usd, opts = {}) {
    if (curve) curve = finitePts(curve);
    if (drawn) drawn = finitePts(drawn);
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
    const maxDd = fmt(minDd), words = !!opts.words, none = words && !(minDd < 0);
    const worstAt = dd.reduce((w, p) => (p[1] < w[1] ? p : w), dd[0])[0];
    const name = !words ? `Underwater drawdown plot from ${day(t0)} to ${day(t1)}; worst drawdown ${plain(maxDd)}`
      : `Underwater drawdown plot ${day(t0) === day(t1) ? `on ${day(t0)}` : `from ${day(t0)} to ${day(t1)}`}; ${none ? 'it never fell from a running high' : `worst drawdown ${plain(maxDd)} (${day(worstAt)})`}`;
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${words ? esc(name) : name}">
      <polygon points="${area}" fill="var(--signal-wash)" stroke="none"/>
      <polyline points="${curvePts}" fill="none" stroke="var(--signal)" stroke-width="1.6"/>
      <line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="var(--rule-2)"/>
      <text x="${L - 8}" y="${(y(0) + 4).toFixed(1)}" text-anchor="end">${words ? plain(fmt(0)) : '0'}</text>
      ${none ? `<text x="${((L + W - R) / 2).toFixed(1)}" y="${(y(lo / 2) + 4).toFixed(1)}" text-anchor="middle">No drawdown</text>` : `<text x="${L - 8}" y="${(y(minDd) + 4).toFixed(1)}" text-anchor="end">${maxDd}</text>`}
      <text x="${L}" y="${H - 6}">${day(t0)}</text>${day(t1) === day(t0) ? '' : `<text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>`}
    </svg>`;
  }

  // ---------- timetable rows: stamps, and paper and real P&L in words ----------
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
  // The Paper P&L column (paperCell, below), only on a list with a row that has a paper book now or had one.
  const PAPER_TIP = 'What it has made on paper (pretend money) since you deployed it, after Kalshi fees and the spread. Never added to its demo or live money.';
  // What a deployed strategy has actually done, beside its backtest columns.
  // The server sends one book (live, else paper, else demo) and a paper strategy's demo book beside it
  // under r.demo, so sandbox dollars are never added to paper ones.
  const realTrades = (n) => `${num(n)} trade${n === 1 ? '' : 's'}`;
  // How long a backtest window ran (its metrics' `days`), so a P&L or return says over what span.
  const overDays = (d) => !(+d > 0) ? '' : +d < 1 ? ' in under a day' : ` over ${num(Math.round(+d))} day${Math.round(+d) === 1 ? '' : 's'}`;
  // A deployment as a customer knows it: by its book and state, never by its row id.
  const BOOK_NAME = { live: 'Live', demo: 'Demo', paper: 'Paper' };
  const bookName = (d) => BOOK_NAME[d.mode] || esc(d.mode);
  // Its book as the mark beside its name: LIVE, Demo or Paper.
  const deploymentMode = (d) => d.mode === 'live' ? '<span class="mk live">LIVE</span>' : d.mode === 'demo' ? '<span class="mk dep">Demo</span>' : '<span class="mk">Paper</span>';
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
  // What each figure is net of, as the dashboard and Deploy say it: "+$1.00 on paper since deploying" left out that
  // Kalshi's fees (and, on paper, the spread) were already taken off.
  // A live book says it is real money, as the strategy page's Since deploying does: on the Strategies list a live row
  // read "+$0.27 since deploying" beside rows saying "on demo" and "on paper" (walk 2026-10-30).
  const realNet = (mode) => (mode === 'paper' ? PAPER_NET : mode === 'live' ? 'real money, after Kalshi fees' : 'after Kalshi fees');
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
  const realFig = (r) => r ? `<div class="sub-fig real-fig">${r.trades && r.instant_only && r.mode === 'paper' ? realInstant(r) : r.trades ? `${money(r.pnl)} ${r.mode === 'demo' ? 'on demo ' : r.mode === 'paper' ? 'on paper ' : r.mode === 'live' ? 'on live ' : ''}since deploying\u00a0· ${realTrades(r.trades)}${realSome(r)}\u00a0· ${realNet(r.mode)}` : r.mode === 'demo' ? 'No closed demo trades yet' : r.mode === 'paper' ? 'No closed paper trades yet' : r.mode === 'live' ? 'No closed live trades yet' : 'No closed trades yet'}</div>${r.mode === 'paper' && r.trades && slipEst(r.slippage_estimate) ? `<div class="sub-fig real-fig real-slip">${slipEst(r.slippage_estimate)}</div>` : ''}${realDemo(r)}` : '';
  // A paper book's demo book beside it (the server's real.demo): its own line, never added in.
  const realDemo = (r) => r && r.demo ? `<div class="sub-fig real-fig">Demo: ${r.demo.trades ? `${money(r.demo.pnl)}\u00a0· ${realTrades(r.demo.trades)}\u00a0· ${realNet('demo')}` : 'no closed trades yet'}</div>` : '';
  // The books a deployed strategy runs in now (the server's `books`: live, paper, demo), named on its
  // badge: "Deployed" alone left a paper, a demo and a paper-and-demo strategy looking the same.
  const bookLive = (s) => !!s.deploy_live || (Array.isArray(s.books) && s.books.includes('live'));
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
  // Paper money since deploying, beside the backtest (walk 2026-10-30, "is the autopilot making money?"): the list's
  // rows led with the backtest figure and kept the paper result at the far end of the Status cell, and a strategy page
  // led with green backtest figures over its "Since deploying" record further down. A row whose shown book is paper
  // (the server's `real` in paper mode), or that was removed from paper (`past.paper`), shows that paper money in a
  // Paper P&L column of its own; its demo and live books keep their lines in Status, never added in. A live row's
  // server record is its live book alone, so its paper book is on its page.
  const paperBook = (s) => (!researchOnly(s) && s.deployed && s.real && s.real.mode === 'paper' ? s.real : null);
  const paperBeside = (s) => !researchOnly(s) && !!s.deployed && !!s.real && s.real.mode === 'live' && Array.isArray(s.books) && s.books.includes('paper');
  const pastPaper = (s) => (!researchOnly(s) && s.past && typeof s.past === 'object' && s.past.paper ? s.past.paper : null);
  // Whether a list needs the column: a row with a paper book now or one removed from paper.
  const paperShown = (s) => !!(paperBook(s) || paperBeside(s) || pastPaper(s));
  // One paper book in a line ({pnl, trades, instant_fills}, as the server's book totals send it), for the strategy page's
  // head and a finished session's "Already deployed": paper money net of Kalshi fees and the spread, with its instant
  // fills counted as the track record leaves them out. Never demo or live money. A book that carries the server's
  // slippage_estimate (a finished session's `real`, as the Strategies list's) says it under the line, as the list's
  // paper card does: the session's "Already deployed" line said the paper money with no estimate beside it.
  const paperSince = (r) => `<b>Paper since deploying:</b> ${+r.trades ? `${money(+r.pnl || 0)}\u00a0· ${realTrades(+r.trades)}${pastInstant('paper', r, +r.trades)}\u00a0· ${PAPER_NET}${slipEst(r.slippage_estimate)}` : 'no closed paper trades yet'}`;
  // The cell's estimate line: under every paper figure the cell shows, its instant-fill book's too, as the strategy
  // page's Since deploying says it for the same book (an instant-fill book's cell had none while its page did).
  const slipLine = (r) => (slipEst(r.slippage_estimate) ? `<div class="sub-fig real-fig real-slip">${slipEst(r.slippage_estimate)}</div>` : '');
  // The column's cell: the paper figure first, as the Backtest P&L cell leads with its own, then what it covers. On a phone
  // the stacked card names it (data-lab) under the backtest's figures.
  const paperCell = (s) => {
    const r = paperBook(s), p = pastPaper(s);
    const now = !r ? '' : !r.trades ? '<div class="sub-fig real-fig">No closed paper trades yet</div>'
      : r.instant_only ? `${money(r.pnl)}<div class="sub-fig real-fig">${r.trades === 1 ? 'Its only trade was an instant fill' : `All ${num(r.trades)} of its trades were instant fills`}, left out of the track record\u00a0· ${PAPER_NET}</div>${slipLine(r)}`
      : `${money(r.pnl)}<div class="sub-fig real-fig">since deploying\u00a0· ${realTrades(r.trades)}${realSome(r)}\u00a0· ${PAPER_NET}</div>${slipLine(r)}`;
    const beside = !r && paperBeside(s) ? `<div class="sub-fig real-fig"><a href="/strategies/${s.id}">Its paper book is on its page</a></div>` : '';
    const body = now + beside + (p ? pastFig({ paper: p }) : '');
    return `<td class="num paper-col${body ? '' : ' nil'}" data-lab="Paper since deploying">${body || '\u2014'}</td>`;
  };
  // The Status cell's own record beside a Paper P&L column: everything but the paper book the column shows. Meridian's
  // session row whose next line already says its paper record (opts.paperNext, "Already deployed · Paper since deploying")
  // keeps only its demo line here, so the paper figure isn't said twice.
  const statusReal = (s, col) => (col && paperBook(s) ? realDemo(s.real) : realFig(s.real));
  const statusPast = (s, col) => {
    if (!col || !pastPaper(s)) return pastFig(s.past);
    const { paper, ...rest } = s.past;
    return pastFig(rest);
  };
  // Paused deployments need the user ("Resume or remove it on Deploy" sends them here), so they lead.
  const pausedFirst = (ds) => [...ds].sort((a, b) => (b.status === 'paused') - (a.status === 'paused'));
  // One plain line on how a book is doing against its backtest, written by the server
  // (services/backtest_check.py): that book's realized per-trade P&L and win rate against the
  // backtest's, "too early to tell" under 10 trades. One book per line; books are never added up.
  // Each signed amount stays on one line (a phone would otherwise break between the minus and the $).
  const btCheckLine = (c, tag = 'div') => c && c.line ? `<${tag} class="sub-fig bt-check bt-${esc(c.verdict)}">${esc(c.line).replace(/[+\u2212]\$[\d,]+\.\d\d/g, (m) => `<span class="amt">${m}</span>`)}</${tag}>` : '';
  // A paper row's strategy record toward the live check (the server's `road`: all its paper
  // deployments, counted as the strategy page's Road to live counts them) and when the trades, events
  // and hours could be in at its pace; once they are, which checks still refuse it (`failing`).
  const ROAD_FAILING = { candidate: 'clearance to trade', legacy_trades: 'trade count', legacy_pnl: 'P&amp;L', net_pnl: 'P&amp;L', edge: 'edge', recent: 'recent form', demo: 'demo record' };
  // What an event is, on the record's "0/20 separate events": the events check's own reason (research.agent).
  const ROAD_EVENTS_TIP = 'Trades on strikes of one event count as one bet, so the record needs trades from 20+ separate events';
  // When, in words (also the strategy page's Road to live).
  const roadDays = (d) => d < 1 ? 'under a day' : d < 1.5 ? 'about a day' : `about ${Math.round(d)} days`;
  // `open` is the server's live switch (the bundle's liveOpen()): closed, a live deployment places no orders, so a
  // record that clears every check says live trading isn't open yet, never that deploying it is all that's left.
  const roadLine = (d, open) => {
    const r = d.road;
    if (!r) return '';
    const parts = [[r.trades, r.trades_needed, 'trades'], [r.events, r.events_needed, 'separate\u00a0events'], [Math.floor(r.span_hours), r.span_needed_hours, 'hours']]
      .filter(([have, need]) => have < need).map(([have, need, unit]) => `<span class="nobr"${unit === 'separate\u00a0events' ? ` title="${ROAD_EVENTS_TIP}"` : ''}>${num(have)}/${num(need)}\u00a0${unit}</span>`);
    // Each "9/30 trades" piece stays whole (.nobr) and each "·" ends its line (a no-break space before it, a
    // plain one after): at 390px a line began "· 9/20 events".
    let text;
    if (parts.length) text = parts.join('\u00a0· ') + (!r.running ? '\u00a0· paused, so not growing' : r.eta_days != null ? `\u00a0· enough in ${roadDays(r.eta_days)} at its pace` : '');
    else if (!r.failing) text = 'trades, events and hours are in';
    else if (!r.failing.length) text = open ? 'every check cleared. Live money only if you deploy it there' : 'every check cleared, but live trading isn’t open yet';
    else {
      const names = [...new Set(r.failing.map((k) => ROAD_FAILING[k] || esc(k.replace(/_/g, ' '))))];
      text = `trades, events and hours are in; ${names.length} check${names.length === 1 ? '' : 's'} left: ${names.join(', ')}`;
    }
    return `<div class="sub-fig road-line">Its paper record toward live: ${text}</div>`;
  };
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

  // ---------- Explore, market pages and the hot rail ----------
  const midOf = (m) => { const b = +m.bid, a = +m.ask; if (b > 0 && a > 0) return (b + a) / 2; const l = +m.last; return l > 0 ? l : null; };
  // Many markets share one event title (every strike of "Bitcoin price on Oct 14?"), so the
  // strike sub-title is what tells them apart.
  // The yes subtitle only when it adds something: "Minnesota wins · Minnesota" and "Will Bitcoin be
  // above $200000 by Jan 1…? · Above $200000" repeated the title. A contract the feed sends untitled is named
  // as a position is (contractName: its market's words, else "Kalshi contract"), never by its raw ticker.
  // A multi-game combo's title is Kalshi's legs run together ("yes Denver,yes Boston,no Over 220.5 points scored"): each
  // leg gets its space after the comma and the line starts with a capital, as every other title does. Any other title as sent.
  const comboTitle = (t) => /^(?:yes|no) [^,]+(?:,\s*(?:yes|no) [^,]+)+$/i.test(t) ? t.split(/,\s*/).join(', ').replace(/^./, (c) => c.toUpperCase()) : t;
  const kalshiUrl = (m) => `https://kalshi.com/markets/${encodeURIComponent((m.s || '').toLowerCase())}`;
  const marketHref = (ticker) => `/explore?m=${encodeURIComponent(ticker || '')}`;
  // Kalshi's market status in words: "active" read as jargon, and "finalized" never said it had settled.
  // Kalshi's settlement rules, shown as Kalshi wrote them but typeset: an apostrophe after a letter is curly
  // ("CF Benchmarks' index" read with a straight one), and a clock time keeps its AM/PM and zone ("before 5" ended
  // a line and "PM EDT" began the next). Words and figures are untouched.
  const rulesText = (t) => String(t || '').replace(/(\w)'/g, '$1\u2019').replace(/(\d) ([AP]M)\b/g, '$1\u00a0$2')
    .replace(/\b([AP]M) (E[SD]T|ET|C[SD]T|UTC)\b/g, '$1\u00a0$2');
  // An open market is open on Kalshi: under a market page's name "Open for trading" read as trading open in Tau, which
  // places no trade from Explore.
  const MKT_STATUS = { initialized: 'Not open yet', unopened: 'Not open yet', active: 'Open on Kalshi', open: 'Open on Kalshi', paused: 'Trading paused', closed: 'Closed, result pending', determined: 'Result in, paying out', settled: 'Settled', finalized: 'Settled' };
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
  // A contract's close as the page shows it, kept current while the page is open (closeClock), never only at load.
  // Walked 2026-10-28 with a 15-minute window three minutes from its close: its Explore row and page said "closes
  // 01:39 CDT" with no time left, and went on saying so after 01:39 had passed. A row says how long is left inside
  // the last hour and "closed" once it has passed; the page's Closes figure counts down under the time. `skew` (s)
  // lines the reader's clock up with the server's when it read (as_of, the spot read's secs_left).
  // Whole seconds, so the milliseconds between the read and the draw never tip an exact minute over (a 4320 s
  // read drawn 2 ms later read "1 hr 11 min").
  const closeLeft = (iso, skew) => Math.round((Date.parse(iso || '') - Date.now()) / 1000 + (+skew || 0));
  // A countdown's number keeps its unit (a no-break space): Meridian's hot rail at 1280px ended a line on "in 58"
  // with "min" on the next.
  const soonText = (s) => (s < 60 ? 'under a minute' : leftText(s).replace(/(\d) /g, '$1\u00a0'));
  const CLOSE_FORM = {
    // The time keeps its zone (keepZone): the hot rail and a row's chip ended a line on "05:00" with "UTC" on the next.
    chip: (iso, s) => (s > 0 ? `closes ${keepZone(settleAt(iso))}${s < 3600 ? `${SEP}in ${soonText(s)}` : ''}` : `closed ${keepZone(settleAt(iso))}`),
    left: (iso, s) => (s > 0 ? leftText(s) : 'Closed'),
    when: (iso, s) => `${s > 0 ? 'closes' : 'closed'} ${keepZone(settleAt(iso))}`,
    // The market page's close figure's own label: walked 2026-10-30, a page left open past the close read "Closes 04:35 EDT"
    // over "Closed, result pending" until a reload. It turns to "Closed" with the line under it, as a page opened after the
    // close (or a settled market) already reads.
    lab: (iso, s) => (s > 0 ? 'Closes' : 'Closed'),
    in: (iso, s) => (s <= 0 ? 'Closed, result pending' : s < 172800 ? 'in ' + soonText(s) : ''),
    // The status line under a market page's name: an open market's "Open for trading" read on after its close until a
    // reload, beside a Closes figure already saying "Closed, result pending". Only an open status follows the clock.
    status: (iso, s) => (s > 0 ? MKT_STATUS.open : MKT_STATUS.closed),
    // An open position's settle line (a row still held, not yet settled). Walked 2026-10-30, a 15-minute contract past
    // its close read "Open, settles 04:15 UTC" on its market page and "Settles 04:15 UTC" on its strategy, a time
    // already gone: once the close passes it says the market has closed and the result is pending, in the status
    // line's words. Only the words change: the position, its book and its figures are the server's. A row with no
    // close time (NaN) keeps its "—". `pos` is the market page's Status cell, `settles` the strategy page's holding
    // (capped) and the dashboard's position line, `settleTime` Deploy's Settles column.
    pos: (iso, s) => (s > 0 || Number.isNaN(s) ? `Open, settles ${settleAt(iso)}` : MKT_STATUS.closed),
    settles: (iso, s) => (s > 0 || Number.isNaN(s) ? `settles ${settleAt(iso)}` : 'closed, result pending'),
    settleTime: (iso, s) => (s > 0 || Number.isNaN(s) ? settleAt(iso) : MKT_STATUS.closed),
  };
  const closeWords = (iso, form, skew, cap) => { const t = CLOSE_FORM[form](iso, closeLeft(iso, skew)); return cap ? t.charAt(0).toUpperCase() + t.slice(1) : t; };
  // The clock's attributes on an element of the caller's own (Deploy's Settles cell is the cell itself).
  const closeData = (iso, form, skew = 0, cap = false) => ` data-close="${esc(iso || '')}" data-form="${form}"${skew ? ` data-skew="${Math.round(skew)}"` : ''}${cap ? ' data-cap="1"' : ''}`;
  const liveClose = (iso, form, { skew = 0, cap = false, cls = '' } = {}) => `<span${cls ? ` class="${cls}"` : ''}${closeData(iso, form, skew, cap)}>${esc(closeWords(iso, form, skew, cap))}</span>`;
  // A distance under 0.01% read "0.00%" beside "−$5": it says so.
  const pctText = (p, dp) => { const a = Math.abs(+p || 0); return a > 0 && a < 0.005 ? 'under 0.01%' : a.toFixed(dp) + '%'; };
  // A 15-minute window's start price is in the contract's own name ("Target Price: $113,512.08", the title line the
  // page heads with) before the collector stores its record: the section said "This window's start price isn't stored
  // yet" under that heading. With no stored strike it is read from there and says so; which side pays stays with
  // the rules, as for any strike read without its record. Spot is measured against it as the server measures a line.
  const TARGET_IN = /\btarget price:?\s*\$\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?/i;
  // A contract name's "Target Price: $113,512.08" stays on one line, label and amount together: the hot rail's
  // narrow column at 1280px ended a line on "Target Price:" with its amount on the next (or cut it off).
  // Takes escaped HTML and returns it with the phrase in a .nobr span, its space a no-break one.
  const glueTarget = (html) => String(html).replace(/\b(target price:?)\s+(\$\s*[\d,]+(?:\.\d+)?)/gi, '<span class="nobr">$1\u00a0$2</span>');
  // A strike condition in a contract's name, short: "$113,000 or above" reads "≥ $113,000" and "Below $90" "< $90" (a
  // row's condition beside its event, and the hot rail's).
  const compactCondition = label => label.replace(/^(\$[\d,]+(?:\.\d+)?) or above$/i, '≥ $1').replace(/^(\$[\d,]+(?:\.\d+)?) or below$/i, '≤ $1').replace(/^Above (\$[\d,]+(?:\.\d+)?)$/i, '> $1').replace(/^Below (\$[\d,]+(?:\.\d+)?)$/i, '< $1');
  function titleStrike(d) {
    const t = [d && d.sub, d && d.title].map((x) => TARGET_IN.exec(String(x || ''))).find(Boolean);
    const value = t ? +(t[1].replace(/,/g, '') + (t[2] || '')) : NaN;
    return value > 0 ? { kind: 'line', value, lo: null, hi: null, inclusive: false, from: 'title' } : null;
  }
  const lineVs = (price, value) => {
    const diff = Math.round((price - value) * 100) / 100;
    return { side: diff > 0 ? 'above' : diff < 0 ? 'below' : 'at', diff, pct: Math.round(diff / value * 1e5) / 1e3, yes: null };
  };
  // Kalshi names an above/below Bitcoin contract by its threshold ("$113,000 or above", the heading of its page and
  // its row's name), while the strike it stores is the cent under it (112,999.99, Yes when Bitcoin ends above it).
  // Walked 2026-10-30: a page headed "$113,000 or above" said "Strike $112,999.99" under it, two prices for one line.
  // Where the name's threshold is the strike's (the same, or a cent past it on the side that pays) the strike and the
  // distance read in the name's terms: measured from $113,000, spot at $113,000.00 is "at" it, on the Yes side, and
  // $112,999.99 a cent below it, on the No side, as against the stored strike. `inclusive` null takes either.
  const HEAD_LINE = /\$\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s+or\s+(above|below)\b/i;
  function headLine(texts, value, kind, inclusive) {
    const h = texts.map((x) => HEAD_LINE.exec(String(x || ''))).find(Boolean);
    if (!h || !(+value > 0)) return null;
    const dir = h[3].toLowerCase(), at = +(h[1].replace(/,/g, '') + (h[2] || ''));
    if (kind !== 'line' && kind !== dir) return null;
    const gap = Math.round((at - value) * 100), past = dir === 'above' ? 1 : -1;
    if (!(inclusive === true ? gap === 0 : inclusive === false ? gap === past : gap === 0 || gap === past)) return null;
    return { value: at, dir, shift: gap / 100, text: '$' + (h[2] ? fmt2 : fmt0).format(at) };
  }
  // Spot against the strike (the server's `vs`) restated against the name's threshold: the same price, a cent apart.
  const vsFromHead = (v, hl) => {
    if (!hl || !v || !['above', 'below', 'at'].includes(v.side)) return v;
    const diff = Math.round((+v.diff - hl.shift) * 100) / 100;
    return { ...v, side: diff > 0 ? 'above' : diff < 0 ? 'below' : 'at', diff: diff || 0, pct: diff / hl.value * 100 || 0 };
  };
  function marketSpot(s, d) {
    const sp = s.spot && s.spot.price != null ? s.spot : null, stored = s.strike && s.strike.value != null ? s.strike : null;
    const k = stored || titleStrike(d);
    const m15 = M15_CONTRACT.test((d && d.ticker) || s.ticker || '');
    // A target read from the contract's title is named as the title and Explore's list name it: "target price".
    const line = m15 || (k && k.from === 'title') ? 'target price' : 'strike', Line = line[0].toUpperCase() + line.slice(1);
    const hl = stored && ['above', 'below', 'line'].includes(k.kind) ? headLine([d && d.sub, d && d.title], k.value, k.kind, k.kind === 'line' ? null : !!k.inclusive) : null;
    const v = vsFromHead(stored ? (s.vs && s.vs.side ? s.vs : null) : k && sp ? lineVs(+sp.price, k.value) : null, hl);
    const bucket = k && k.kind === 'range', edges = bucket && k.lo != null && k.hi != null;
    const now = sp ? fig('Bitcoin now', btcUsd(sp.price), sp.stale ? { small: `Spot feed is ${spotOld(+sp.age_s || 0)} old`, cls: 'fig-behind' } : { small: `Coinbase${SEP}${spotAge(+sp.age_s || 0)}` })
      : fig('Bitcoin now', '—', { small: 'No stored price in the last day' });
    const strike = !k ? fig(Line, '—', { small: m15 ? 'This window’s start price isn’t stored yet' : 'Not stored for this contract' })
      : edges ? fig('Bucket', `${btcUsd(k.lo)} to ${btcUsd(k.hi)}`, { small: 'Yes if Bitcoin settles inside it' })
      : bucket ? fig('Bucket centre', btcUsd(k.value), { small: 'its edges aren’t stored' })
      : k.from === 'title' ? fig(Line, btcUsd(k.value), { small: 'Read from the contract’s title' })
      : hl ? fig(Line, hl.text, { small: `Yes at ${hl.text} or\u00a0${hl.dir}` })
      : fig(Line, btcUsd(k.value), { small: k.kind === 'above' || k.kind === 'below' ? `Yes if Bitcoin settles ${k.inclusive ? 'at or ' : ''}${k.kind}\u00a0it` : 'Kalshi’s rules say which side pays' });
    // Which side of the strike (or the bucket's edge it is outside of) spot is on, by how much, and which
    // side of the contract that is when the strike says.
    const where = !v ? '' : edges ? (v.side === 'below' ? 'below its floor' : 'above its top') : bucket ? v.side + ' its centre' : `${v.side} the ${line}`;
    const yes = v && v.yes === true ? 'on the Yes side' : v && v.yes === false ? 'on the No side' : '';
    // Measured from an old price, the label says so beside the figure, not only under Bitcoin's.
    const lab = (l) => (sp && sp.stale ? `${l}, ${spotAge(+sp.age_s || 0)}` : l);
    const skew = s.close_time ? s.secs_left - (Date.parse(s.close_time) - Date.now()) / 1000 : 0;
    // Once the close has passed, Bitcoin's price no longer decides the contract (Kalshi settles on the index before the
    // close): walked 2026-10-30, a closed 15-minute window's page went on saying "+$71.87 · on the Yes side" from spot
    // a minute after its close, read as the result. It says so instead of measuring spot against the line.
    const closed = s.secs_left === 0 || (!!s.close_time && closeLeft(s.close_time, skew) <= 0);
    const vs = closed ? fig(edges ? 'Spot vs bucket' : bucket ? 'Spot vs centre' : 'Spot vs ' + line, '—', { small: 'Closed: Bitcoin’s price since the close doesn’t change the result' })
      : !v ? '' : v.side === 'inside' ? fig(lab('Spot vs bucket'), 'Inside', { small: `${usd(v.to_lo)} above its floor${SEP}${usd(v.to_hi)} below its top${SEP}on the Yes side` })
      : v.side === 'at' ? fig(lab('Spot vs ' + line), 'At the ' + line, { small: yes })
      : fig(lab(edges ? 'Spot vs bucket' : bucket ? 'Spot vs centre' : 'Spot vs ' + line), usd(v.diff, true), { small: [`${pctText(v.pct, 2)} ${where}`, yes].filter(Boolean).join(SEP) });
    const left = s.secs_left == null ? fig('Time left', '—') : !s.close_time ? fig('Time left', s.secs_left > 0 ? leftText(s.secs_left) : 'Closed')
      : fig('Time left', liveClose(s.close_time, 'left', { skew }), { small: liveClose(s.close_time, 'when', { skew }) });
    return `<dl class="figures measure">${now}${strike}${vs}${left}</dl><p class="hint mk-spot-note">Kalshi settles on the CF Benchmarks Bitcoin index averaged over the last minute before the close; Coinbase’s price usually sits within a few dollars of it.</p>`;
  }
  const MKT_GONE = 'Kalshi has no market at this link. It may have been taken down, or the link is incomplete. Find it again on Explore.';
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
    : `${+v.diff < 0 ? '−' : '+'}${WJ}$${num(Math.round(Math.abs(+v.diff)))}${SEP}${pctText(v.pct, Math.abs(+v.pct || 0) < 0.1 ? 2 : 1)}`);
  const vsLab = (m) => (vsTarget(m) ? 'Spot vs target price' : /^KXBTC-.+-B[\d.]+$/.test(m.t) ? 'Spot vs bucket' : 'Spot vs strike');
  // A row whose close has passed shows no distance: Bitcoin's price after the close doesn't decide the contract (Kalshi
  // settles on the index before it). Walked 2026-10-30, a closed 15-minute row said "Closed 04:15 UTC · Spot vs target
  // price +$72", read as its result. Worked out at each draw, as the row's close is.
  // Measured as its market page measures it: from the threshold in the row's name ("$113,000 or above") where that is
  // the ticker's strike or a cent past it (headLine), so a row and its page agree at the line.
  const rowHead = (m) => { const t = /^KXBTCD?-[A-Z0-9]+-T(\d+(?:\.\d+)?)$/.exec(m.t || ''); return t && m.vs.from !== 'title' ? headLine([m.su, m.ti], +t[1], 'line', null) : null; };
  const rowVs = (m) => (m.vs && !(m.ct && closeLeft(m.ct) <= 0) ? vsFromHead(m.vs, rowHead(m)) : null);
  const vsHtml = (m) => { const v = rowVs(m); return v ? `<span class="xspot"${v.from === 'title' ? ` title="${VS_TITLE}"` : ''}>${vsLab(m)} <b>${vsText(v, m)}</b></span>` : ''; };
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
  // Before the server's first copy of the market feed there is no list and no time: "Markets tracked 0" (Meridian:
  // "Available markets 0" and "Time unavailable") read as Kalshi having no markets. The figures say the feed hasn't
  // come in yet instead.
  const exploreNoFeed = (d) => !d.at && !+d.total;
  const EXPLORE_NO_FEED = fig('Market feed', 'Not in yet', { small: 'the market list arrives about once a minute' });
  const exploreEmpty = (title, text) => `<div class="empty"><h2>${esc(title)}</h2><p>${esc(text)}</p><button class="btn sm" type="button" data-xretry>Try again</button></div>`;
  // Explore's Bitcoin filter (?show=bitcoin, kept with the search and sort): the server keeps the contracts of the
  // Bitcoin series it reads spot for (btc_spot.BTC_SERIES, as BTC_CONTRACT), so the list pages over Bitcoin alone.
  const EXPLORE_SHOW = [['all', 'All markets'], ['bitcoin', 'Bitcoin']];
  const exploreShowChips = (btc) => `<div class="chips xshow" role="group" aria-label="Show">${EXPLORE_SHOW.map(([v, l]) => `<button class="chip" type="button" data-show="${v}" aria-pressed="${btc === (v === 'bitcoin')}">${l}</button>`).join('')}</div>`;
  // A Bitcoin list with nothing in it says so in plain words, with the way back to every market; one a search emptied
  // offers to clear the search (page-explore.js wires data-xclear), as its words say.
  const exploreNoBtc = (q) => `<div class="empty"><h2>${q ? `No Bitcoin markets match “${esc(q)}”` : 'No Bitcoin markets are open right now'}</h2><p>${q ? 'Try a broader search, or clear it to see every open Bitcoin market.' : 'Kalshi opens new Bitcoin markets through the day, and they show here within about a minute.'}</p><p>${q ? '<button class="btn sm" type="button" data-xclear>Clear search</button> ' : '<button class="btn sm" type="button" data-xretry>Try again</button> '}<button class="btn sm" type="button" data-xall>Show all markets</button></p></div>`;
  // When a hot market closes (`ct`, as Explore's rows say it) and, for a Bitcoin contract, how far spot is
  // from its strike; a rail with no fresh spot says why above its rows, as the list does.
  const hotWhen = (m) => (m.ct || rowVs(m) ? `<span class="hot-when">${m.ct ? liveClose(m.ct, 'chip', { cap: true }) : ''}${vsHtml(m)}</span>` : '');
  // The hot rail's figure is named as Explore's column and the market page name it ("Yes price"; Meridian's said
  // "Midpoint quote", Tau's nothing), and one from the last trade (one side quoted, or none) says so.
  const hotPriceWord = (m) => ((+m.bid > 0 && +m.ask > 0) || midOf(m) == null ? 'Yes price' : 'Yes price, from the last trade');
  const hotSpotNote = (d) => (d && d.spot !== undefined && (!d.spot || d.spot.stale || d.spot.failed) ? `<p class="hot-note">${esc(spotListNote(d.spot, d.markets))}</p>` : '');

  // ---------- research runs ----------
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
  // A session's number among the user's own (the server's `seq`: 1 is their first), never the global run
  // id, which read "Session 8" on someone's first session. The example and an answer without it get none.
  const sessionNo = (r) => r && +r.seq > 0 ? `Session ${num(+r.seq)}` : '';

  // ---------- the dashboard's since-your-last-visit strip ----------
  // Demo P&L restarts at a reload (before_reload holds what came before), unlike the track record.
  function demoSpan(dm) { return dm && dm.before_reload ? 'since reload' : 'all time'; }
  // What a demo (or live) figure is net of, as Deploy, Funds and the strategy page say it beside their own.
  const FEES_NET = 'after Kalshi fees';
  // The demo book's capital, named as Funds names it on every page that shows it: the dashboard's "$1,000.00 capital"
  // sat beside Funds' "Starting capital $1,000.00" (Meridian's Funds: "starting capital"), and kept saying "capital"
  // after a reload while Funds said "Capital at last reload" (walk 2026-10-31).
  const demoCapital = (dm) => `${usd(dm.capital)} ${dm.before_reload ? 'capital at last reload' : 'starting capital'}`;
  // A demo book's realized P&L, or before its first close (closed_trades 0, all time) when one shows, as Funds says it:
  // the dashboard read "$0.00 realized all time" beside Funds' "P&L shows once a demo trade closes". An answer
  // without the count keeps its figure.
  const DEMO_NO_CLOSE = 'P&amp;L shows once a demo trade closes';
  const demoNoClose = (dm) => dm.closed_trades != null && !+dm.closed_trades;
  const demoPnl = (dm, pnl) => demoNoClose(dm) ? DEMO_NO_CLOSE : `${usd(pnl, true)} realized ${demoSpan(dm)}, ${FEES_NET}`;
  // What the since-your-last-visit strip's book line is net of: paper's spread and fees, demo's fees in play money
  // ("Demo +$0.67 on 1 trade" said nothing beside paper's "after Kalshi fees and the spread"), live's real money.
  // Live says its fees too (the engine takes every fill's Kalshi fee off a live trade's P&L), as paper and demo say theirs.
  const sinceNote = (m) => (m === 'live' ? ` (real money), ${FEES_NET}` : m === 'paper' ? `, ${PAPER_NET}` : m === 'demo' ? ` (play money), ${FEES_NET}` : '');
  // An action as a link: the server's {label, href}. One off the site opens in a new tab and says so.
  function actionLink(h) {
    const a = h && h.action;
    if (!a || !a.href) return '';
    const ext = /^https?:\/\//.test(a.href);
    return ` <a href="${esc(a.href)}"${ext ? ' target="_blank" rel="noopener"' : ''}>${esc(a.label)}${ext ? ' \u2197' : ''}</a>`;
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
    // One session that has since ended reads "started, now finished": "1 research session started, finished" read
    // as two verbs with no subject between them (walk 2026-10-31).
    const state = solo ? (started === 1 ? (['queued', 'running'].includes(solo) ? 'still ' : 'now ') + solo : 'all ' + solo)
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
  // The paper book's line in the strip says its estimate after typical live slippage (the server's, for the trades
  // it closed in the strip's window) under it, as every other paper figure on the dashboard does (slipEstGl). Paper
  // is the strip's last book, so the line sits right under its figure; live and demo never carry one.
  // Whether a book closed a trade today (UTC), from what the dashboard already holds: its newest closed trades
  // (recent_closed: every book's, newest first) and the book's all-time count (closed_trades). true or false when
  // they can tell, null when they can't (the newest rows all closed today and none of them is this book's), so the
  // page keeps the server's figure then. Day 4 of a new account read "Today (UTC): $0.00 realized" with its last
  // trade two days back, as if today's trading had broken even (walk 2026-10-31). Display only.
  const closedToday = (rows, mode, closedAll, now = Date.now()) => {
    const day = Math.floor(now / 864e5) * 864e5, at = (r) => Date.parse(r && r.closed_at);
    const list = Array.isArray(rows) ? rows : [], mine = list.filter((r) => r && r.mode === mode);
    if (mine.some((r) => at(r) >= day)) return true;
    if (mine.length >= (+closedAll || 0)) return false;
    const last = list[list.length - 1];
    return last && at(last) < day ? false : null;
  };
  const sinceSlip = (b) => (b && b.paper && +b.paper.trades ? slipEstGl(b.paper.slippage_estimate) : '');
  // Two or more links in a row ("A, B, C, 1 more"): to a thumb they stack one under another (.since-links, app.css),
  // each its own 44px, where on a line they reached into one another.
  const sinceLinks = (links) => (links.length > 1 ? `<span class="since-links">${links.join(', ')}</span>` : links.join(''));
  function demoHealthLine(h) { return h ? `<span class="demo-health">${esc(h.line)}${actionLink(h)}</span>` : ''; }
  // One mode's closed trades as a CSV, offered only where that mode has some, so the reader can
  // check its P&L line by line. The server never mixes modes in one file.
  // `before`, the text ahead of it, and `info`, the key of a glossary button after that text: the button comes first,
  // glued to its last word and the separator (gloSep).
  // Tau's dashboard shows a link per book, all three reading "Download trades (CSV)": a screen reader's list of links
  // gave three alike, so each says its book after the words it shows (walked 2026-10-31).
  function tradesCsv(mode, b, info = '', before = '') {
    const has = b && b.closed_trades > 0;
    const link = has ? `<a class="csv-link" href="/api/trades.csv?mode=${mode}" download>Download trades (CSV)<span class="vh"> for the ${mode} book</span></a>` : '';
    if (info) return (has ? gloSep(info, before) : before + glo(info)) + link;
    return before + (has ? SEP : '') + link;
  }

  // ---------- autopilot words ----------
  // What it is doing right now in a word or two, for the pill on every page: "researching",
  // "reviewing", "2 on paper", or "paused" while billing stops it. '' when there's nothing to add.
  // A market the autopilot names (the status read's research list, and its story, which quotes that
  // list): the app's own label. The server sends a market's long name (markets.customer_name), or "an unlisted
  // market"; an older line quoted the run's raw key ("btc15m", a series like "KXBTCD"). A market the app can
  // name, by key, label or series, reads by its long name (mktLong, as Billing's research lines say it), and a
  // key nothing knows as "an unlisted market", never the raw key.
  const AP_PICKING = "a market it’s still picking";
  // The card leads with why its paper strategies hold nothing (d.idle). The autopilot keeps working
  // meanwhile, and the card never said so: someone back after a day read "Nothing open right now" and
  // not that a research session was running. Paper-waiting lines only (the others already say it).
  const AP_IDLE_PAPER = new Set(['flat', 'starting', 'waiting', 'market_closed']);
  function apDoing(d) {
    if (!d || !d.autopilot) return '';
    if (d.billing_blocked) return 'paused';
    if (d.research && (d.research.active || []).length) return 'researching';
    if (d.reviewing) return 'reviewing';
    return d.paper_running ? `${num(d.paper_running)} on paper` : '';
  }
  // The pill's label: in paper mode the word for what it is doing takes the place of "paper" (each one
  // is paper-only or no money at all); the live modes keep their label, so LIVE always shows.
  function apPillLabel(d, m) {
    const doing = d && d.mode === 'paper' ? apDoing(d) : '';
    return doing ? `Autopilot${SEP}` + doing : m.label;
  }
  // "At its next check-in" said nothing of when. Its time can't be known: the worker's heartbeat runs on its
  // own timer, skips a user it just reviewed, waits for a free worker and spaces idle users out, and a finished
  // research session starts one at once. So the copy gives the status's usual cadence (checkin_every_min) and
  // how long ago the last one ran (last_review_at), never a time; nothing while none is coming (off, a billing
  // pause) or the status isn't read yet. The [data-ap-when] spans follow each status read (syncApCopy).
  function apAgo(iso) {
    const m = Math.max(0, (Date.now() - Date.parse(iso)) / 60000);
    return !(m >= 0) ? '' : m < 1.5 ? 'just now' : m < 90 ? `${Math.round(m)} min ago`
      : m < 2880 ? `${Math.round(m / 60)} hours ago` : `${Math.round(m / 1440)} days ago`;
  }
  // The usual cadence under a "Last check-in" figure (the card's and the panel's), or nothing.
  function apEvery(d, cls = '') {
    return d && +d.checkin_every_min > 0 && !d.reviewing ? ` <small${cls ? ` class="${cls}"` : ''}>usually every ${num(+d.checkin_every_min)} min</small>` : '';
  }
  // A coin or family in words, as the server's chat lines say it (agent.FOCUS_WORDS): "Focus: Btc, eth" read the raw tokens.
  const FOCUS_WORDS = { btc: 'Bitcoin', eth: 'Ethereum', sol: 'Solana', xrp: 'XRP', doge: 'Dogecoin', hype: 'Hyperliquid', near: 'NEAR',
    zec: 'Zcash', tao: 'Bittensor', 'crypto-perpetuals': 'Crypto perpetuals', 'weather-high': 'Daily high temperatures' };
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
  // Paper trades toward the target: "12 of 30 paper trades", and once past it "67 paper trades (30 needed)".
  // Why "realistic" counts fewer trades than the paper book beside it: the track record's words. "0 of 30 realistic
  // paper trades" sat next to "Paper +$8.72 on 12 trades" with no reason given.
  const INSTANT_WHY = 'fills real execution would not get';
  const PAPER_COUNT_WHY = `instant-fill paper trades left out (${INSTANT_WHY})`;
  const paperCount = (p) => +p.trades >= +p.trades_needed ? `${num(+p.trades)} realistic paper trades (${num(+p.trades_needed)} needed)` : `${num(+p.trades)} of ${num(+p.trades_needed)} realistic paper trades`;
  // A backtest trade's exit, in words (backtest.py / spec.exit_signal reasons); an unknown one loses its underscores.
  const EXIT_WORD = { settled: 'settled', take_profit: 'take-profit', stop_loss: 'stop-loss', stop: 'stop', edge_gone: 'edge gone', signal: 'signal', exit: 'signal', mark: 'marked at end' };
  const exitWord = (r) => r == null ? '' : EXIT_WORD[r] || String(r).replace(/_/g, ' ');
  const AP_FOCUS = [['', 'Any market'], ['crypto', 'Crypto only'], ['btc', 'Bitcoin only'], ['sports', 'Sports only']];

  // ---------- credits and runway in words ----------
  const KIND_LABEL = { bonus: 'Welcome credits', topup: 'Added credits', autoreload: 'Auto-reload', usage: 'Agent usage', admin_grant: 'Credits from Tau support' };
  const runwayLabel = (days) => days < 1 ? 'Under a day' : days > 90 ? 'Over 3 months' : `About ${Math.round(days)} day${Math.round(days) === 1 ? '' : 's'}`;
  // The spend a runway is read at. The server's pace_days is how many days the week's spend covers: the
  // account's age, at most 7. Under a day there is no pace yet (a first session's minutes, divided by
  // 7, read "over 3 months"); under a week it is per day so far. An older server sends none: the week.
  const paceTooSoon = (days, spent) => days != null && days < 1 && +spent > 0;
  const paceDay = (spent, days) => +spent > 0 && !(days != null && days < 1) ? +spent / (days != null ? Math.min(7, days) : 7) : null;
  const paceWords = (spent, days) => days != null && days < 7 ? `${usd(paceDay(spent, days))} a day so far` : `${usd(spent)} a week`;
  // A days figure as when something happens: "in about 2 days", "in under a day".
  const inDays = (days) => 'in ' + runwayLabel(days).toLowerCase();

  // ---------- what a research session usually costs ----------
  // The research form's figure for one model, from /api/research/estimate: the user's own median on that model
  // (yours_by_model; an older server sends only "yours", their own on any model), else the typical one for that
  // model. {v, own} or null, `own` being 'model', true or false as the form's costBasis reads it. The research
  // form and the autopilot's cost line both read it here, so the two pages can't show different figures.
  const sessionEstimate = (est, key) => {
    if (!est || !key) return null;
    const byModel = est.yours_by_model, mine = byModel ? byModel[key] : est.yours;
    if (mine != null) return { v: +mine, own: byModel ? 'model' : true };
    const typical = (est.typical || {})[key];
    return typical == null ? null : { v: +typical, own: false };
  };
  // What switching the autopilot on is likely to cost, in the customer's credits: the research form's figure for
  // the autopilot's model (`label`, the model picker's name for it), and how many such sessions the balance covers
  // at that rate. Typical, never a quote; credits only, never beside a P&L. '' with payments off or no figure.
  // Under the floor a session needs, the line beside it already says it waits for credits: only the figure.
  // With auto-reload on (and its card not declined), what each reload buys at that rate instead of a pause.
  const apSessionCost = (e, label, me) => {
    if (!e || !(e.v > 0) || !me || !me.billing_enabled) return '';
    const own = e.own ? 'your recent sessions' : 'recent sessions';
    const basis = label ? `${own} on ${esc(label)}` : e.own === true ? own : `${own} on its model`;
    const sessions = (n) => `about ${num(n)} session${n === 1 ? '' : 's'}`;
    const covers = (amt) => Math.floor((halfUp(+amt || 0) + 1e-9) / e.v);
    let s = `A research session usually costs about ${usd(e.v)} in credits (${basis}; typical, not a quote).`;
    const bal = +me.credit_balance || 0, ar = me.reload_failed ? null : me.auto_reload;
    if (me.min_run_balance != null && bal < +me.min_run_balance && !ar) return s;
    const n = covers(bal), k = ar ? covers(ar.amount) : 0;
    // The count is research sessions only: the autopilot's check-ins between them spend credits too, so it says so
    // rather than read as a promise of N sessions.
    const also = ' The autopilot\u2019s check-ins between sessions use some credits too.';
    if (ar) return s + (n >= 1 ? ` At that rate your ${usd(bal)} covers ${sessions(n)}${k >= 1 ? `, and each ${usd(ar.amount)} auto-reload about ${num(k)} more` : ''}.${also}`
      : k >= 1 ? ` At that rate each ${usd(ar.amount)} auto-reload covers ${sessions(k)}.${also}` : '');
    return s + (n >= 1 ? ` At that rate your ${usd(bal)} lasts ${sessions(n)}.${also}`
      : ` That’s more than the ${usd(bal)} you have, so a session may stop short when your credits run out.`);
  };

  // ---------- a list read a page at a time ----------
  // A list whose newest page is polled and whose older pages are read on request (Funds' paper history: "Show older
  // entries") keeps its older rows under each fresh newest page only while the two still join: `kept` (rows read
  // before, by id, newest first) must share a row with `first` (the fresh newest page), or rows that came in between
  // could be missing. Returns the kept rows older than all of `first`, newest first, once each; [] when `first` holds
  // every row (shorter than `page`: a paper reset leaves one); null when they no longer join (a reset, or more than a
  // page came in between), and the list starts again from its newest page.
  const olderRows = (first, kept, page) => {
    if (first.length < page || !kept.length) return [];
    const ids = new Set(first.map((r) => r.id));
    if (!kept.some((r) => ids.has(r.id))) return null;
    const low = Math.min(...first.map((r) => +r.id)), seen = new Set();
    return kept.filter((r) => +r.id < low && !seen.has(r.id) && seen.add(r.id)).sort((a, b) => b.id - a.id);
  };

  window.TauCore = Object.freeze({
    esc, SEP, sepLine, mdInline, mdLite, feedMd, authorLine, fmt0, halfUp, WJ, plain, usd, pct, cents, isPerpetual,
    researchOnly, researchBadge, tone, when, bellTime, bellMore, dateFmt, CLOCK, CLOCK_ZONE, LOG_STAMP, WEEKDAY_DAY, clock, tzName,
    logTime, settleAt, markOld, markFig, keepZone, num, compact, clipWords, age, sum4, money, kfmt, sinceMin,
    PAPER_NET, NOT_MARKED, markedOf, slipEst, slipTip, ICON, GLOSSARY, PNL_WINDOW, pnlWin, slipEstGl, glo, gloSep, gl,
    LIVE_CLOSED, LIVE_WAITING, LIVE_NO_ORDERS, liveIdleCount, liveIdleShort, tradePrice, markedAt,
    catOrder, mktLong, mktShort, mktKnown, contractHour, hourET, strikeIn, SERIES_SHORT, kalshiRef, boardTitle, emailState, fig,
    fundsLinked, notice, loadFail, loading, bootSplash, BEHIND, finitePts, thinCurve, curveWords, traceScale, registry, curveRegs, spark, rpUnderwater, mark,
    statusMark, PAPER_TIP, realTrades, overDays, bookName, EXAMPLE_NOTE, EXAMPLE_TAG, AP_STRAT_TAG, runTag, bookLive,
    paperShown, paperSince, paperCell, statusReal, statusPast, pausedFirst, btCheckLine, roadDays, roadLine,
    depInstant, demoRowLine, TR_MODES, trBook, trFix, trDay, trMonth, trCi, TR_STATUS, TR_EDGE, trCurve, trCurveCap,
    trLeftGap, trRowLeft, trOver, midOf, comboTitle, kalshiUrl, marketHref, rulesText, MKT_STATUS, BTC_CONTRACT,
    spotSect, closeLeft, closeWords, closeData, liveClose, TARGET_IN, glueTarget, compactCondition, marketSpot, MKT_GONE, vsText, vsLab,
    rowVs, vsHtml, spotListNote, EXPLORE_WAIT, exploreNoFeed, EXPLORE_NO_FEED, exploreEmpty, exploreShowChips,
    exploreNoBtc, hotWhen, hotSpotNote, hotPriceWord, waitSpan, runWaitLine, demoSpan, FEES_NET, demoCapital, demoNoClose,
    demoPnl, sinceNote, actionLink, AP_DID, CREDITS_WARN_DAYS, shortReason, sinceRunsState, sinceSplit, sinceSlip, closedToday, sinceLinks, demoHealthLine, tradesCsv, AP_PICKING, AP_IDLE_PAPER,
    apPillLabel, apAgo, apEvery, FOCUS_WORDS, creditsPaid, apWeekSpent, INSTANT_WHY, PAPER_COUNT_WHY, paperCount,
    exitWord, AP_FOCUS, KIND_LABEL, runwayLabel, paceTooSoon, paceDay, paceWords, inDays, sessionEstimate, apSessionCost,
    pageLede, deploymentMode, sessionNo, olderRows
  });
})();
