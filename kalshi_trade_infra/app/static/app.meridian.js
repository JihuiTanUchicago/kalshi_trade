/* Tau client. Vanilla JS, no build step.
   Every string that came from a user, an agent or the market goes through esc(). */
(() => {
  'use strict';

  // The pure helpers both themes share (escaping, money, counts, dates and times, markdown, icons, the glossary's
  // words, P&L lines, the track record's, Explore's and the autopilot's words) are in the shared core, core.js, which
  // the page runs before this bundle. Each keeps its name here, so the code below calls it as before.
  const {
    esc, SEP, sepLine, mdLite, feedMd, authorLine, fmt0, halfUp, WJ, plain, usd, pct, cents, isPerpetual,
    researchOnly, researchBadge, tone, when, bellTime, dateFmt, CLOCK, CLOCK_ZONE, LOG_STAMP, WEEKDAY_DAY, clock, tzName,
    logTime, settleAt, markOld, markFig, keepZone, num, compact, clipWords, age, sum4, money, kfmt, sinceMin,
    PAPER_NET, NOT_MARKED, slipEst, slipTip, ICON, GLOSSARY, PNL_WINDOW, pnlWin, slipEstGl, glo, gloSep, gl,
    LIVE_CLOSED, LIVE_WAITING, LIVE_NO_ORDERS, liveIdleCount, liveIdleShort, tradePrice, markedAt, MKT_SHORT,
    catOrder, NO_MARKET, contractHour, hourET, strikeIn, SERIES_SHORT, kalshiRef, boardTitle, emailState, fig,
    fundsLinked, notice, loadFail, loading, bootSplash, BEHIND, registry, curveRegs, spark, rpUnderwater, mark,
    statusMark, PAPER_TIP, realTrades, overDays, bookName, EXAMPLE_NOTE, EXAMPLE_TAG, AP_STRAT_TAG, runTag, bookLive,
    paperShown, paperSince, paperCell, statusReal, statusPast, pausedFirst, btCheckLine, roadDays, roadLine,
    depInstant, demoRowLine, TR_MODES, trBook, trFix, trDay, trMonth, trCi, TR_STATUS, TR_EDGE, trCurve, trCurveCap,
    trLeftGap, trRowLeft, trOver, midOf, comboTitle, kalshiUrl, marketHref, rulesText, MKT_STATUS, BTC_CONTRACT,
    spotSect, closeLeft, closeWords, closeData, liveClose, TARGET_IN, glueTarget, compactCondition, marketSpot, MKT_GONE, vsText, vsLab,
    rowVs, vsHtml, spotListNote, EXPLORE_WAIT, exploreNoFeed, EXPLORE_NO_FEED, exploreEmpty, exploreShowChips,
    exploreNoBtc, hotWhen, hotSpotNote, waitSpan, runWaitLine, demoSpan, FEES_NET, demoCapital, demoNoClose, demoPnl, sinceNote, actionLink, AP_DID, CREDITS_WARN_DAYS,
    shortReason, sinceRunsState, sinceSplit, sinceSlip, sinceLinks, demoHealthLine, tradesCsv, AP_PICKING, AP_IDLE_PAPER,
    apPillLabel, apAgo, apEvery, FOCUS_WORDS, creditsPaid, apWeekSpent, INSTANT_WHY, PAPER_COUNT_WHY, paperCount,
    exitWord, AP_FOCUS, KIND_LABEL, runwayLabel, paceTooSoon, paceDay, paceWords, inDays, pageLede, deploymentMode,
    sessionNo, olderRows
  } = window.TauCore;

  const root = document.getElementById('app');
  const S = { me: null, timers: [], gen: 0, perps: null };

  // ---------- glossary (info bubbles; the words are in core.js) ----------
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
    // A scroll shuts the bubble, except one whose marker has focus, which follows its marker: Tab onto a marker below
    // the fold scrolls it into view, and that scroll shut the bubble the focus had just opened.
    addEventListener('scroll', () => { if (current && document.activeElement === current) place(current); else hide(); }, true);
    addEventListener('resize', hide);
  }

  // ---------- formatting (its pure helpers are in core.js) ----------
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
  // Whether live trading is open on this server (/api/me's live_trading_available: the server's live switch).
  // While it is closed the engine places no live orders: it pauses a running live deployment the next time it
  // checks the market ("Live trading is not enabled on this server yet."), the server refuses Resume on a live
  // one, and Tau can't sell what a live deployment holds, which stays open until its market settles.
  const liveOpen = () => !!(S.me && S.me.live_trading_available);
  // A connected key's cash with no live trading from Tau: it said "Your Kalshi cash \u2014 real money untouched",
  // and didn't say why (live trading closed) or by what. Display only: the live switch is the server's.
  const LIVE_IDLE = () => liveOpen() ? 'Your real money at Kalshi: Tau hasn\u2019t placed a live trade yet'
    : 'Your real money at Kalshi: live trading isn\u2019t open yet, so Tau places no trades there';
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
  const PERPS_SCENARIO = 'Research scenario: at most 1× capital, fixed 12 bps taker fees and 5 bps adverse slippage per fill, plus settled funding. These are uncalibrated cost assumptions; fills use the next bar’s open. No margin or liquidation model. Short losses can exceed capital.';
  // A market by the catalog's label. A key the catalog no longer lists (a retired market) reads "Unlisted market",
  // never the raw key, as the autopilot card says one (apMarketName).
  const marketLabel = (k) => { const m = S.me && (S.me.markets || []).find((x) => x.key === k); return m && m.label ? m.label : 'Unlisted market'; };
  const marketShort = (k) => (!k ? NO_MARKET : MKT_SHORT[k] || marketLabel(k));
  // A market named on its own, in a sentence or as a row's market ("Bitcoin up or down in 15 minutes"), by its full
  // label, as Billing's lines and every position name it; the short one stays for chips and meta lines joined by
  // " · ". The autopilot said "Researching BTC 15-min up/down" and Deploy's rows "BTC 15-min up/down" above
  // positions in "Bitcoin up or down in 15 minutes". A key the catalog doesn't list reads as marketShort does.
  const marketFull = (k) => { const m = k && ((S.me && S.me.markets) || []).find((x) => x.key === k); return m && m.label ? m.label : marketShort(k); };
  const contractMkt = (ticker) => ((S.me && S.me.markets) || []).find((x) => x.series && String(ticker || '').startsWith(x.series + '-')
    && (x.close_hour_et == null || contractHour(ticker) === x.close_hour_et));
  // Another hour of a ladder a market here keeps to one close (KXBTCD-26OCT2612, the noon "Bitcoin above a set price"
  // contract, beside btc_daily's 5pm): never that market's label, which names the wrong close, but the same
  // words at its own hour read from the ticker, [chip, name] as SERIES_SHORT: "BTC above set price at noon ET".
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
  // A position's contract as people name it: its market's plain label with its own strike ("Bitcoin $68,500
  // or above at 5pm ET"), else the market it was traded on (`key`, its deployment's), else "Kalshi contract".
  // The ticker (KXBTC15M-26OCT262100-00) carries the raw series key, so it is never the headline: kalshiRef
  // sets it on a small line, there to find the contract on Kalshi.
  const contractName = (ticker, key) => contractMarket(ticker) || (key ? strikeIn(marketFull(key), ticker) : 'Kalshi contract');
  // A contract, by its plain name, that opens its market page (price, settlement rules, your positions in it).
  const contractLink = (ticker, key) => `<a href="/explore?m=${encodeURIComponent(ticker)}">${esc(contractName(ticker, key))}</a>`;
  // A contract (a hot-markets row's `t`) as the app names its market ("BTC 15-min"), or its SERIES_SHORT or
  // other-hour chip ("BTC range at 5pm ET", "BTC above set price at noon ET"); '' for any other, so a chip is left off
  // rather than the raw series or another hour's market.
  const contractShort = (ticker) => { const m = contractMkt(ticker); return m ? marketShort(m.key) : seriesLabel(ticker, 0); };
  // Link a strategy's market to its Kalshi series page.
  const marketKalshiUrl = (k) => { const m = (S.me && S.me.markets || []).find((x) => x.key === k); return m && m.series ? `https://kalshi.com/markets/${m.series.toLowerCase()}` : null; };
  const dirLabel = (k) => { if (!k) return 'Session'; const d = S.me && S.me.directions.find((x) => x.key === k); return d ? d.label : String(k).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()); };
  // The server's title for a session whose prompt is an instruction to the agent (the autopilot's research
  // floor), else the idea as typed.
  // `market` false leaves the market out of an untitled session's title, for a row whose own Market column names
  // it: the research list read "Session · BTC 15-min up/down" beside a Market column saying "BTC 15-min up/down".
  const sessionTitle = (r, market = true) => r.title ? r.title : (r.prompt && r.prompt.trim()) ? r.prompt.trim() : (dirLabel(r.direction) + (market ? SEP + marketShort(r.market) : ''));

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
  // A read's 5xx names no code: the reader can't act on "(500)", and the operator's readout (apiBroke) has it.
  const failText = (status, write) => write && (!status || status >= 500)
    ? "Tau didn't confirm this, so it may or may not have gone through. Reload the page to check before you try again."
    : !status ? 'Can’t reach Tau. Check your connection.'
    : status === 429 ? 'Tau is getting a lot of requests right now. Try again in a minute.'
    : status >= 500 ? 'Tau is having trouble right now. Try again in a moment.'
    // A 4xx with no words of Tau's own (an edge page in front of it): what to do, not just the code. A read
    // names no code either (it put "Tau couldn't do that (403)" over a section that hadn't loaded); a write's
    // line is unchanged.
    : !write ? 'Tau couldn’t load this. Reload the page and try again.'
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
    // Optional timeout (a poll passes one so a hung read is aborted and counted as a failure).
    // AbortController fires an abort the fetch rejects on. A read with none of its own gets READ_MS:
    // one the network swallowed left its page's skeleton up for good.
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
      throw new ApiError(res.status, body !== undefined ? failText(0, true) : 'Tau’s reply didn’t come through whole. Try again.');
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
    [/^\/settings(?:\/theme)?$/, viewSettings],
  ];
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
    let busy = false, fails = 0, wait = 0, okAt = Date.now(), wokeAt = 0;
    const mark = () => { if (note) note((busy || fails) && Date.now() - okAt > staleAfter(ms) ? okAt : null); };
    // wake (the browser came back online) skips what is left of the back-off.
    return (wake) => {
      if (wake === true && !busy) wait = 0;
      // Back on the tab it read at once (wake): the interval's next tick, due within half an interval, would
      // ask the same again a second or two later, so it sits that one out.
      if (wake !== true && wokeAt && !busy && !fails && Date.now() - wokeAt < ms / 2) { wokeAt = 0; mark(); return null; }
      if (busy || wait > 0) { if (!busy) wait--; mark(); return null; }
      busy = true; wokeAt = wake === true ? Date.now() : 0;
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
  // A new page in the app names itself in the tab title and puts keyboard focus on its heading, as a
  // full page load would: a screen reader says where it landed, and Tab starts from the page instead of
  // from the link the repaint removed. The first page of a visit and a repaint of the same page leave
  // focus alone, and so does a page that already put focus somewhere (a field it opened).
  // A control that draws its page again in the same place (a Strategies filter chip, its market or sort select)
  // gets focus back on its new copy: the repaint dropped a keyboard user at the top of the page, Tab going from
  // the first link. Another view of one page (Explore's list to a market and back, /explore?m=) is a new page,
  // and its heading takes focus, as a page change does. `was`: the control that had focus, by its id or data-*.
  let shownPath = null, shownAt = null;
  function focusKey(el) {
    if (!el || el === document.body || !el.getAttribute || (root.contains && !root.contains(el)) || (el.closest && el.closest('#autopilot-float'))) return null;
    if (el.id) return /^[A-Za-z][\w-]*$/.test(el.id) ? '#' + el.id : null;
    const data = Object.keys(el.dataset || {}).map((k) => `[data-${k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase())}="${String(el.dataset[k]).replace(/["\\\]]/g, '')}"]`).join('');
    return data ? el.tagName.toLowerCase() + data : null;
  }
  function pageArrived(path, was) {
    const h = root.querySelector('h1'), tab = root.querySelector('.services [aria-current="page"]');
    // The signed-out landing keeps the plain product name; its headline is not a page name.
    // plain(): the tab title is read and copied as text, so it carries no word joiner (usd()).
    const name = root.querySelector('.services') ? plain((h && h.textContent) || (tab && tab.textContent) || '').replace(/\s+/g, ' ').trim() : '';
    document.title = name ? `${clipWords(name, 59)}${SEP}Tau` : 'Tau';
    const at = path + location.search, again = shownPath === path, moved = shownAt !== null && shownAt !== at;
    shownPath = path; shownAt = at;
    const a = document.activeElement, top = pageStart();
    if (!again && !moved || (a && a !== document.body && a.isConnected !== false)) return;
    const back = again && was ? root.querySelector(was) : null;
    const to = back && back.focus && !back.disabled && !back.hidden ? back : moved ? top : null;
    if (to && to.focus) to.focus({ preventScroll: true });
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
    const was = focusKey(document.activeElement);
    clearTimers();
    const gen = ++S.gen;
    window.scrollTo(0, 0);
    // On a phone the open autopilot panel fills the screen, so moving to a page closes it. Focus left in it (a
    // link in the panel, its X) goes with it, so the new page's heading takes focus (pageArrived leaves focus that
    // is somewhere), not the pill the closing panel would hand it to.
    if (phone()) {
      try { localStorage.setItem('tau_ap_open', '0'); } catch (e) { /* private mode */ }
      const f = document.getElementById('autopilot-float'), a = document.activeElement;
      if (f && a && f.contains(a) && shownPath !== location.pathname && a.blur) a.blur();
    }
    // The panel that switching autopilot on opened by itself (desktop) folds to its pill on the next page: left
    // open, it covered half of that page, the nav links under it and the research form (walk 2026-10-28). A panel
    // the reader opened stays open.
    if (S.apAutoOpen && S.apAutoOpen !== location.pathname) { S.apAutoOpen = null; try { localStorage.setItem('tau_ap_open', '0'); } catch (e) { /* private mode */ } }
    const path = location.pathname;
    if (path === '/signin') { const f = document.getElementById('autopilot-float'); if (f) f.remove(); }
    // A sheet closed above hands the page back before it draws, so the new page's heading can take focus.
    apInertPage();
    const match = routes.map(([re, fn]) => [path.match(re), fn]).find(([m]) => m);
    if (!S.me && path !== '/signin') {
      // Boot: a 401 means signed out (-> signin). Any other failure (slow, overloaded, offline) is
      // passing, so say so with a retry instead of sending a signed-in user to sign in. A splash shows
      // after 250ms, so a fast boot never flashes it, and the read gives up after 12s.
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
        shell(sectionOf(path), boardTitle(off ? 'You’re offline' : 'This page didn’t load'), loadFail(off ? 'This page loads by itself once you’re back online.' : errText(e)));
        root.querySelector('[data-retry]').onclick = () => render();
      }
    }
    if (gen !== S.gen) return;  // the user moved on while this page loaded
    root.setAttribute('aria-busy', 'false');
    pageArrived(path, was);
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
          <div class="pay-stage-wrap"><div class="pay-stage" id="pay-stage"></div></div>
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
  let bellReq = null, bellReqAt = 0, bellOkAt = 0, bellFresh = null, bellStale = null;
  // The autopilot panel's status read (every 20s, on every signed-in page) keeps the bell current too:
  // at most once a minute it re-reads the list, with no timer of its own.
  const BELL_EVERY_MS = 60000;
  // Opening the bell reads the list again when the one it keeps is older than this (see trig.onclick).
  const BELL_OPEN_FRESH_MS = 15000;
  function bellTick() {
    if (!bellFresh || Date.now() - bellReqAt < BELL_EVERY_MS) return;
    bellRead();
    // best-effort, like the first read; one that fails says the list kept may be out of date (bellStale)
    bellReq.then((d) => bellFresh && bellFresh(d), () => bellStale && bellStale()).catch(() => {});
  }
  // One read of the list; bellOkAt is when the newest one that came back was asked.
  function bellRead() {
    const at = bellReqAt = Date.now();
    bellReq = api('/api/notifications', undefined, { keep: true });
    bellReq.then(() => { bellOkAt = at; }, () => {});
    return bellReq;
  }
  // A list that filled up while the user was away opens with what it holds, by kind (the server's
  // unread_kinds): a week back, seven "Autopilot put ... on paper" lines ran past the first screen
  // before the pause among them. Shown from BELL_SUM_MIN new notices; the lines below are unchanged.
  const BELL_SUM_MIN = 4;
  // A live-ready notice while live trading is closed (liveOpen) waits on paper, as the notice itself says: "ready for live" read as if it could go live.
  const BELL_SUM = [['deployed', (n) => `${n === 1 ? '1 strategy' : num(n) + ' strategies'} put on paper`],
    ['paused', (n) => `${num(n)} paused`], ['passed', (n) => `${num(n)} passed ${n === 1 ? 'its' : 'their'} paper test`],
    ['live_ready', (n) => `${num(n)} ${liveOpen() ? 'ready for live' : 'cleared every paper-to-live check'}`], ['reload_failed', () => 'auto-reload couldn\u2019t charge your card'],
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
    const head = wrap.querySelector('.bell-head'), staleEl = wrap.querySelector('.bell-stale');
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
    // stands for. One without a page to open is plain text, not a link to nowhere. One about a strategy
    // that is no longer the user's (the server's `gone`: deleted since, as a shared copy can be) says so,
    // as text: its link opened "Not found" (walk 2026-10-31).
    const BELL_GONE = 'This strategy is no longer in your list.';
    const item = (n) => {
      const inner = `${n.read ? '' : '<span class="vh notif-new">New: </span>'}${esc(n.body)}${n.gone ? `<span class="notif-more">${BELL_GONE}</span>` : ''}${n.more ? `<span class="notif-more">and ${num(n.more)} more like this</span>` : ''}${bellTime(n.created_at)}`;
      return !n.gone && /^\/(?!\/)/.test(n.link || '') ? `<a class="notif ${n.read ? '' : 'unread'}" href="${esc(n.link)}">${inner}</a>` : `<p class="notif ${n.read ? '' : 'unread'}">${inner}</p>`;
    };
    const paint = (d) => {
      dot.hidden = !d.unread;
      trig.setAttribute('aria-label', d.unread ? `Notifications, ${num(d.unread)} unread` : 'Notifications');  // the dot alone is colour
      head.innerHTML = '<b>Notifications</b>' + (d.unread ? `<span class="bell-new">${num(d.unread)} new</span>` : '');
      // Empty, it says what rings it: through a new user's first research session it said only "No notifications yet."
      list.innerHTML = d.items.length ? bellSummary(d) + d.items.map(item).join('') : `<p class="bell-empty">No notifications yet. It rings when a strategy goes on paper or is paused, passes its paper test or ${liveOpen() ? 'is ready for live' : 'clears every paper-to-live check'}, and if auto-reload can\u2019t charge your card.</p>`;
    };
    // A list that didn't load still opens, says so and offers Try again; the next read (bellTick) fills it
    // too. It used to leave the bell dead for the rest of the visit: a tap did nothing and no dot ever came.
    let data = null, dataAt = 0;
    // A refresh that failed with a list up kept the list and said nothing, so it read as current. One quiet
    // line above the list says it may be out of date, only after a failed refresh, and the next read that
    // comes back takes it away (walk 2026-10-28).
    const ago = () => { const m = Math.max(1, Math.round((Date.now() - dataAt) / 60000)); if (m < 60) return `${m} min ago`; const h = Math.round(m / 60); return `${h} hour${h === 1 ? '' : 's'} ago`; };
    const stale = (on) => {
      if (!staleEl) return;
      if (on && data) staleEl.innerHTML = `Couldn\u2019t refresh. Showing notifications from ${ago()}. <button type="button" class="bell-again" data-bell-retry>Try again</button>`;
      else staleEl.innerHTML = '';
      staleEl.hidden = !(on && data);
    };
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
        if (menu.hidden) paint(data); else { dot.hidden = false; trig.setAttribute('aria-label', `Notifications, ${num(unread)} unread`); }
      });
    };
    const load = async () => {
      // The shell is often painted twice in a row (instant page switch, then content): one read serves both.
      // A list that came back under a minute ago serves the next page's bell too, since the autopilot's read
      // keeps it current within the minute (bellTick): every page change read it again. One that failed is read again.
      const kept = bellReq && bellOkAt === bellReqAt ? BELL_EVERY_MS : 2000;
      if (!bellReq || Date.now() - bellReqAt > kept) bellRead();
      const at = bellReqAt;
      try { data = await bellReq; dataAt = at; paint(data); stale(false); return true; } catch (e) { if (!data) unloaded(); else stale(true); return false; }  // bell is best-effort
    };
    // The bell opens while its list is still reading (walk 2026-10-28: on a slow reply a tap did nothing until
    // the read came back, up to READ_MS), so it says it is loading, and the list fills in where it stands.
    if (!data && !list.children.length) list.innerHTML = '<p class="bell-empty">Loading notifications\u2026</p>';
    load().then((ok) => { if (ok) seen(); });
    // Autopilot pauses or readies a strategy while the page sits open: the dot shows it within a minute,
    // without a reload (bellTick). An open list is left as the reader sees it, unless it never loaded.
    bellFresh = (d) => { if (menu.hidden || !data) { data = d; dataAt = Date.now(); paint(d); stale(false); seen(); } };
    bellStale = () => stale(true);
    trig.onclick = async (e) => {
      e.stopPropagation();
      if (!menu.hidden) { close(); return; }
      if (data && data.unread && !list.querySelector('.notif.unread')) paint(data);  // a mark that didn't save: new again
      if (staleEl && !staleEl.hidden) stale(true);  // its "3 min ago" as of now
      menu.hidden = false; trig.setAttribute('aria-expanded', 'true'); document.addEventListener('click', onDoc, true);
      // A list read a while ago is read again as it opens: the bell's own read comes at most once a minute, so a
      // strategy the autopilot had just put on paper (the dashboard already said so) opened as “No notifications
      // yet” (walk 2026-10-28). The kept list shows at once; focus waits on the list while it reads, as Try again's does.
      const old = data && Date.now() - dataAt > BELL_OPEN_FRESH_MS;
      if (old) menu.focus({ preventScroll: true }); else focusIn();
      seen();
      if (!old) return;
      bellReqAt = 0;
      if (await load() && !menu.hidden) { focusIn(); seen(); }
    };
    // Focus waits on the list itself while it reads: the browser blurs a button that goes disabled or is
    // painted over, and focus leaving the bell closes the list.
    const retry = async (btn) => {
      if (btn.dataset.busy) return;
      btn.dataset.busy = '1';
      menu.focus({ preventScroll: true });
      bellReqAt = 0;  // a fresh read, not the one that just failed
      if (await load()) { focusIn(); seen(); } else { const b = menu.querySelector('[data-bell-retry]'); if (b) b.focus({ preventScroll: true }); }
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
    if (staleEl) staleEl.addEventListener('click', (e) => { const again = e.target.closest('[data-bell-retry]'); if (again) retry(again); });
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
    // <main> starts at the board, the page's h1 and its money figures, and #main is the page below them.
    root.innerHTML = `
      <header class="masthead"><div class="masthead-in">
        <div class="brand-controls"><span class="market-control"></span><p class="wordmark"><a href="/">${ICON.mark}<span>Tau</span></a></p></div>
        <nav class="services" aria-label="Sections"><div class="services-in">${nav}</div></nav>
        <span class="asof">${adminToggle}<span class="bell-wrap"><button class="bell-trig" data-action="bell" aria-controls="bell-menu" aria-expanded="false" aria-label="Notifications"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg><span class="bell-dot" hidden></span></button><span class="bell-menu" id="bell-menu" role="region" aria-label="Notifications" tabindex="-1" hidden><div class="bell-head"><b>Notifications</b></div><p class="bell-stale" hidden></p><div class="bell-list" id="bell-list"></div></span></span><span class="profile"><button class="profile-trig" data-action="profile" aria-haspopup="true" aria-expanded="false"><span class="profile-name" title="${esc(u.name || u.email)}">${esc(u.name || u.email)}</span><svg class="profile-chev" width="9" height="9" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg></button><span class="profile-menu" hidden><a href="/funds">Funds</a><a href="/settings">Settings</a><a href="/billing">Billing</a><a href="/devlog">Dev Logs</a><a href="/system">System</a>${adminViewOn() ? '<a href="/admin">Admin</a>' : ''}<button class="profile-item" data-action="signout">Sign out</button></span></span></span>
      </div></header>
      <div class="workspace"><aside class="hotrail" id="hotrail" aria-label="Hot markets"></aside><main class="wrap">
        <div id="boardbody">${board}</div>
        <div id="main" tabindex="-1">${main}</div>
      </main></div>`;
    // The section tabs scroll sideways on a phone; bring the current one into view.
    const tabs = root.querySelector('.services-in'), here0 = tabs && tabs.querySelector('[aria-current="page"]');
    if (here0 && here0.offsetLeft + here0.offsetWidth > tabs.clientWidth) tabs.scrollLeft = here0.offsetLeft - 16;
    if (tabs) tabEdges(tabs);
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
    const at = root.querySelector('[data-action="admintoggle"]');
    if (at) at.onclick = () => {
      const turningOff = adminViewOn();
      localStorage.setItem('tau_admin_off', turningOff ? '1' : '0');
      if (turningOff && location.pathname === '/admin') go('/', true); else render();
    };
    mountHotRail();
    mountAutopilot();
  }
  const ledeTitle = (title, text) => `<div class="board-title"><h1 class="page">${esc(title)}</h1>${pageLede(text)}</div>`;
  async function viewDevLog() {
    shell('/devlog', boardTitle('Dev Logs'), loading(260));
    let d;
    try { d = await api('/api/devlog'); } catch (e) { root.querySelector('#main').innerHTML = notice(e.message, 'bad'); return; }
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
    root.querySelector('#main').innerHTML = `
      <div class="chips dl-tabs" role="group" aria-label="Dev Logs view">
        <button class="chip" type="button" data-dltab="planned" aria-pressed="${tab === 'planned'}">Up next</button>
        <button class="chip" type="button" data-dltab="shipped" aria-pressed="${tab === 'shipped'}">Shipped${SEP}${shippedCount}</button>
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
  const themeName = (key) => (THEMES.find((t) => t.key === key) || THEMES[0]).name;
  // Set for the one reload after a saved switch, so the new theme's Settings says the switch took.
  const THEME_SAVED = 'tau_theme_saved';
  function emailSettings() {
    const u = (S.me && S.me.user) || {};
    const off = !!u.email_opt_out;
    return `<section class="sect email-settings"><div class="section-head"><h2>Email</h2><p>${u.email ? 'Sent to ' + esc(u.email) : 'Sent to your sign-in address'}</p></div>
        <div class="email-pref">
          <label class="switch"><input type="checkbox" id="email-optional" role="switch" aria-describedby="email-state"${off ? '' : ' checked'}><span>Updates and community email</span></label>
          <div id="email-flash"></div>
          <p class="hint" id="email-state">${esc(emailState(off, liveOpen()))}</p>
          <p class="hint email-always"><b>Always sent:</b> safety alerts about a Bitcoin perps account you trade through Tau: a position that doesn’t match Tau’s orders, a position near liquidation, or heavy margin use. They protect real money, so this switch doesn’t stop them. Also an email when an auto-reload of your credits fails, since research pauses when they run out.</p>
        </div>
      </section>`;
  }
  // Settings' Account section: who is signed in, and where the rest of the account lives. Name and email come from
  // Google (sign-in refreshes them), so they read as facts with where to change them; the Kalshi keys and the card
  // are changed on Funds and Billing, which Settings named nowhere (walk 2026-10-30: "where do I manage my key?").
  function accountSettings() {
    const me = S.me || {}, u = me.user || {};
    const keys = `${me.kalshi_connected ? 'Live key connected' : 'No live key'}${SEP}${me.kalshi_dev_connected ? 'demo key connected' : 'no demo key'}`;
    const row = (label, value) => `<div><dt>${label}</dt><dd>${value}</dd></div>`;
    return `<section class="sect account-settings"><div class="section-head"><h2>Account</h2><p>Signed in with Google</p></div>
        <dl class="acct-rows">
          ${row('Name', u.name ? esc(u.name) : 'Not set')}
          ${row('Email', u.email ? esc(u.email) : 'Not set')}
          ${u.username ? row('Community name', '@' + esc(u.username)) : ''}
          ${row('Kalshi keys', `<span>${keys}</span><a href="/funds#connect-kalshi">Manage keys on Funds</a>`)}
          ${row('Credits and card', '<a href="/billing">Billing</a>')}
        </dl>
        <p class="hint acct-hint">Your name and email come from your Google account. Change them there, and Tau shows the new ones the next time you sign in.</p>
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
      if (state) state.textContent = emailState(now, liveOpen());
    };
  }
  async function viewSettings() {
    const current = window.__TAU_UI__ === 'meridian' ? 'meridian' : 'tau';
    shell('/settings', ledeTitle('Settings', 'How Tau looks and works for you.'), `
      <section class="sect theme-settings"><div class="section-head"><h2>Theme</h2></div>
        <div class="theme-pick" role="radiogroup" aria-label="Theme">
          ${THEMES.map((t) => `<button type="button" class="theme-opt${t.key === current ? ' on' : ''}" role="radio" aria-checked="${t.key === current}" tabindex="${t.key === current ? 0 : -1}" data-theme="${t.key}">
              <span class="theme-meta"><b>${esc(t.name)}</b></span>
              <span class="theme-mark" aria-hidden="true">${ICON.check}</span>
            </button>`).join('')}
        </div>
        <p class="hint" style="margin-top:12px;max-width:420px">Changes how every page looks, wherever you sign in. Switching reloads Tau; you can switch back here anytime.</p>
        <div id="theme-flash"></div>
      </section>
      ${emailSettings()}
      ${accountSettings()}`);
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
  // A page's own bug (a TypeError on a reply it didn't expect) is not something to print to the user.
  // It is reported (reportBroken), so a page that breaks this way shows up on /admin.
  const errText = (e) => (e instanceof ApiError ? e.message : (reportBroken('view', e), 'Something went wrong on this page. Try again.'));
  function bootFail() {
    root.innerHTML = `<div class="boot"><div class="lbrand">${ICON.mark}<span>Tau</span></div>
      <p class="boot-msg">Tau is taking longer than usual to load. It may be briefly busy.</p>
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
    forgetDrafts();
    return true;
  }
  // Signing out leaves nothing of the reader's own words on the device: the research idea not yet started
  // (page-research.js, this tab) and the autopilot message not yet sent (page-autopilot.js, kept per account).
  // A session that ended by itself keeps them, so signing back in finds them where they were.
  function forgetDrafts() {
    try { sessionStorage.removeItem('tau_research_draft'); } catch (e) { /* private mode */ }
    try {
      const mine = [];
      for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.indexOf('tau_ap_draft:') === 0) mine.push(k); }
      mine.forEach((k) => localStorage.removeItem(k));
    } catch (e) { /* private mode */ }
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
  // A Try again (a read) that brings in what failed draws over its notice, the button with it, and keyboard focus fell
  // to the page's body (Billing's saved cards, System's map, Explore's list, the dashboard's autopilot card). Once the
  // read is done, focus goes into what came in: `head` (a selector in `box`, or an element), else the first heading in
  // `box`, else `box` itself, made focusable for a script, as a page change hands its h1 focus (pageStart). A retry that
  // failed again leaves its Try again in `box`, and focus goes there. Only when focus was lost: a button the read left
  // in place (busy() gives it focus back) or a control the reader moved to keeps it.
  const RETRY_BTN = '[data-retry], [data-xretry], [data-apcard="again"]';
  function retried(box, head) {
    const a = document.activeElement;
    if (!box || box.isConnected === false || (a && a !== document.body && a.isConnected !== false)) return;
    const named = typeof head === 'string' ? box.querySelector(head) : head;
    const to = box.querySelector(RETRY_BTN) || named || box.querySelector('h1, h2, h3') || box;
    if (!/^(?:BUTTON|A|INPUT|SELECT|TEXTAREA)$/.test(to.tagName) && to.getAttribute('tabindex') == null) to.setAttribute('tabindex', '-1');
    if (to.focus) to.focus({ preventScroll: true });
  }

  // ---------- charts ----------
  // devCurve (optional): a second, realized series replayed read-only against
  // the Kalshi demo environment. Drawn dashed in the accent colour with a legend
  // so "Simulated" and "Kalshi dev" read apart. Omitting it keeps the old chart.
  // Draw at the column's real width on a narrow screen: a 760-wide chart shrunk to a phone has 4px labels.
  const chartWidth = () => { const m = root.querySelector('#main'), w = m && m.clientWidth; return w > 0 && w < 760 ? Math.max(300, w) : 760; };
  // The equity chart's label over its unseen-data window. `words` (longest first) names another window: a strategy
  // with no gatekeeper record has no unseen window, only the backtest's later slice, which its loose gate used to pick it.
  const unseenLabel = (cx, right, y, words = [`Later period${SEP}unseen data →`, `Later${SEP}unseen →`, 'Later →'], clearOf = 0) => {
    // In the strategy page's words ("Later period (unseen data)"): it read "Unseen →" over that heading. Measured at about
    // 6px a character in the chart’s 11px face: the full or short words in place right of the cut where they fit, else the short
    // words pinned to the chart's right edge, clear of the demo-replay legend (clearOf, its right end) on a phone. Only
    // where even those would run into the legend does it take the last, shortest words.
    const room = right - cx - 8, wide = (t) => t.length * 6;
    const inPlace = words.slice(0, 2).find((t) => room >= wide(t));
    if (inPlace) return `<text x="${cx + 8}" y="${y}" style="fill:var(--ink-2)">${inPlace}</text>`;
    const pinned = words.slice(1).find((t) => right - wide(t) >= clearOf) || words[words.length - 1];
    return `<text x="${right}" y="${y}" text-anchor="end" style="fill:var(--ink-2)">${pinned}</text>`;
  };
  // The y-axis labels sit right-aligned in a 52-unit gutter left of the plot. A strategy page's chart over $1,000
  // ("$1,584.53") ran past the chart's left edge and read ",584.53" (walked 2026-10-30, a six-month account). With
  // `fit` the gutter widens to the widest label (~6.5 units a character at the chart's 11px); a chart whose labels
  // already fit keeps 52.
  const tickGutter = (labels, fit) => (fit ? Math.max(52, Math.ceil(12 + 6.5 * Math.max(0, ...labels.map((t) => t.length)))) : 52);
  function equityChart(curve, cutoffIso, devCurve, options = {}) {
    const W = options.width || 760, H = options.height || 236, R = 10, T = options.paper ? 16 : 30, B = 26;
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
    const levels = [lo, (lo + hi) / 2, hi];
    const wholePaperAxis = options.paper && levels.every(Number.isInteger);
    const tickText = (v) => (wholePaperAxis ? `${v < 0 ? '−' : ''}$${num(Math.abs(v))}` : usd(v));
    const L = tickGutter(levels.map((v) => plain(tickText(v))), options.fit);
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const cut = cutoffIso ? Date.parse(cutoffIso) / 1000 : null;
    const cx = cut && cut > t0 && cut < t1 ? x(cut) : null;
    const line = (c) => c.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const reference = options.paper ? levels.filter(v => v !== 0).map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--rule)"/>`).join('') : '';
    const ticks = levels.map((v) => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${tickText(v)}</text>`).join('');
    // The grey line across the plot is $0, break-even: unlabelled, a curve that dipped under it read against ticks
    // like −$24.72 and $26.69, with nothing saying where it had gained or lost. It gets its own label unless a
    // tick already sits on it or so close the two would overlap.
    const zeroTick = lo < 0 && hi > 0 && levels.every((v) => Math.abs(y(v) - y(0)) >= 14) ? `<text class="chart-zero" x="${L - 8}" y="${y(0) + 4}" text-anchor="end">$0</text>` : '';
    // The paper chart across a new year names the year on each date ("Dec 30, 2025"): "Jan 4" read as before "Dec 30".
    const years = options.paper && new Date(t0 * 1000).getUTCFullYear() !== new Date(t1 * 1000).getUTCFullYear();
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', ...(years ? { year: 'numeric' } : {}), ...(options.paper ? { timeZone: 'UTC' } : {}) });
    // Each date on the axis once, under a point of the curve. The paper chart's middle tick sat at the span's midpoint,
    // which with two days of closed P&L fell on the second day's midnight ("Oct 29, Oct 30, Oct 30"), and with four on a
    // midnight between two points. Its dates are now the curve's own days, evenly spread (one for each ~90px of axis,
    // two to five): each lands on a point, no date is repeated, and a label that would run into its neighbour is left
    // out. The ends keep their places. One day is labelled once; a week reads every day or two; a month or more about
    // weekly or wider. Backtest curves and the track record keep their two ends, as before.
    const dateTicks = () => {
      const pts = options.paper ? curve.map((p) => p[0]) : [t0, t1];
      const want = options.paper ? Math.max(2, Math.min(5, Math.floor((W - L - R) / 90) + 1)) : 2;
      const picks = [...new Set(Array.from({ length: want }, (_, j) => {
        const at = t0 + (j / (want - 1)) * (t1 - t0);
        return pts.reduce((best, t, i) => (Math.abs(t - at) < Math.abs(pts[best] - at) ? i : best), 0);
      }))].map((i) => ({ t: pts[i], label: day(pts[i]) }));
      const ends = [picks[0], picks[picks.length - 1]].filter((tick, i, two) => i === 0 || tick.label !== two[0].label);
      // Where each label reaches: the first starts at the axis, the last ends at it, the rest centre on their point.
      const width = (label) => label.length * 7;
      const reach = (tick, k, last) => (k === 0 ? [L, L + width(tick.label)] : last ? [W - R - width(tick.label), W - R]
        : [x(tick.t) - width(tick.label) / 2, x(tick.t) + width(tick.label) / 2]);
      const kept = [ends[0]];
      for (const tick of picks.slice(1, -1)) {
        const [lo, hi] = reach(tick, kept.length, false), prev = reach(kept[kept.length - 1], kept.length - 1, false);
        const end = ends.length > 1 ? reach(ends[1], 1, true) : [Infinity];
        if (!kept.some((k) => k.label === tick.label) && tick.label !== ends[ends.length - 1].label && lo >= prev[1] + 12 && hi <= end[0] - 12) kept.push(tick);
      }
      if (ends.length > 1) kept.push(ends[1]);
      return kept.map((tick, k) => ({ ...tick, k, last: k > 0 && k === kept.length - 1 }));
    };
    const dates = dateTicks().map(({ t, label, k, last }) => (k === 0 ? `<text x="${L}" y="${H - 6}">${label}</text>`
      : last ? `<text x="${W - R}" y="${H - 6}" text-anchor="end">${label}</text>` : `<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${label}</text>`)).join('');
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
      const label = `${day(t)}${SEP}${usd(value, true)}`;
      return `<g class="chart-sample" data-time="${t}" tabindex="0" role="img" aria-label="${esc(plain(label))}">
        <rect x="${left}" y="${T}" width="${Math.max(0, right - left)}" height="${H - T - B}" fill="transparent"/>
        <g class="chart-reading" aria-hidden="true"><line x1="${px}" x2="${px}" y1="${T}" y2="${H - B}" stroke="var(--rule-2)" stroke-dasharray="2 3"/><circle cx="${px}" cy="${py}" r="3" fill="var(--ink)"/>
          <rect x="${boxX}" y="${boxY}" width="${boxWidth}" height="26" fill="var(--stock-raised)" stroke="var(--rule-2)"/><text x="${boxX + 8}" y="${boxY + 17}">${esc(label)}</text></g></g>`;
    }).join('') : '';
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="${options.paper ? 'group' : 'img'}" aria-label="${esc(plain(options.label || `Cumulative profit and loss over the backtest${dev ? ', with a realized Kalshi demo-environment curve' : ''}; ends at ${usd(vals[vals.length - 1], true)}`))}">
      ${cx ? `<rect x="${cx}" y="${T}" width="${W - R - cx}" height="${H - T - B}" fill="var(--stock-raised)"/>
              <line x1="${cx}" x2="${cx}" y1="${T}" y2="${H - B}" stroke="var(--ink-3)" stroke-dasharray="4 4"/>
              ${unseenLabel(cx, W - R, T - 10, options.cutLabel, dev ? L + 112 + 'Kalshi dev (real)'.length * 6 + 8 : 0)}` : ''}
      <line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--rule-2)"/>
      ${reference}${ticks}${zeroTick}${dates}${endLabel}
      <polyline points="${line(curve)}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round"/>
      ${dev ? `<polyline points="${line(dev)}" fill="none" stroke="var(--l-accent, #F05A28)" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>` : ''}
      ${legend}
      ${inspect}
    </svg>`;
  }

  // ---------- timetable rows ----------
  // `inRun`: the table sits on its own session's page, where every row's "Ideas tested" was that session's
  // count again (a running session's counter, behind the Tested figure above it), so the column is left out.
  const STRAT_HEAD = (pick, inRun, paper) => `<thead><tr>${pick ? '<th class="pickcol"><input type="checkbox" id="pick-all" aria-label="Select all deployable"><span class="vh pick-head">Select</span></th>' : ''}<th>Strategy</th><th>Market</th><th class="num">Backtest P&amp;L</th><th class="num">Trades</th><th class="num">Win</th>${paper ? `<th class="num" title="${PAPER_TIP}">Paper P&amp;L</th>` : ''}${inRun ? '' : '<th class="num" title="Every idea this research session tested, the passing one included">Ideas tested</th>'}<th>Status</th></tr></thead>`;
  const strategyTable = (rows, pick, inRun, paper) => `<div class="sheet"><table class="stack t-strat">${STRAT_HEAD(pick, inRun, paper)}<tbody>${rows}</tbody></table></div>`;
  // Bulk deploy offers only passed strategies that aren't already running: ticking one that is
  // would start a second deployment of the same rules and double its positions. A pass a later check
  // left uncleared (`verdict`: Missed final test, Held back) is left out too; its own page says why.
  const bulkDeployable = (s) => s.status === 'passed' && !s.verdict && !researchOnly(s) && !s.deployed;
  // Under "Deploy on paper" while a paper deployment of it is still on (running or paused).
  const paperAgain = (deps) => deps.some((d) => d.mode === 'paper' && d.status !== 'stopped')
    ? '<p class="hint paper-again">It already runs on paper. Deploying it again starts a second copy of the same rules, which doubles its paper positions.</p>' : '';
  // The run page's kind of session: its direction, and who started it when the autopilot did.
  const runKind = (r) => +r.by_autopilot && !r.example ? (r.direction ? dirLabel(r.direction) + SEP : '') + 'Started by autopilot' : dirLabel(r.direction);
  const bookBadge = (s) => {
    const books = Array.isArray(s.books) ? s.books : [], live = bookLive(s);
    const rest = books.filter((m) => m === 'paper' || m === 'demo');
    const text = live ? ['Live', ...rest].join(' + ') : rest.length ? 'On ' + rest.join(' + ') : 'Deployed';
    // A live book while live trading is closed places no orders: the badge says it waits (liveWaitMark), unless
    // its row already says Paused.
    return `<span class="mk ${live ? 'live' : 'dep'}">${text}</span>${live && !(s.real && s.real.paused) ? liveWaitMark() : ''}`;
  };
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
    // a passed one the server found no gatekeeper record for (no_gatekeeper_record, from the list's or the session page's own reads),
    // and a void one it found none for (the first version's simple backtest stored it as failed, never judged on held-out
    // data): its later slice is "not held out" too, without "which picked it", since nothing picked it.
    // A held-out row's figure is the backtest after its split date too, so it says "later-period", as the sort
    // ("Later-period P&L") that orders it does: it read "on unseen data" under a sort named otherwise. Its last piece
    // says which kind, in the family's words ("later period · unseen data" / "· not held out", as the short form, the
    // Deploy hover and the strategy page say): it read "…, on unseen data" and "…, which picked it: not held out".
    // A phone's stacked card puts the line in a third of the row under "BACKTEST P&L": the sentence ran about five
    // lines there, and said "P&L" again under the label. It reads the short form ("later period · 9 days · not held
    // out"); the full sentence is its hover and what a screen reader says (bt-long, hidden on a phone only visually).
    // Its qualifier holds together as the short form's does: a desktop row broke "· not / held out" (walked 2026-10-28).
    const later = oos && (s.status === 'backtest-only' || s.no_gatekeeper_record);
    const verdictWord = missedFinal ? 'missed the final test' : noPass ? 'did not pass' : '';
    // The count and its unit hold together ("30 / days" broke across a phone's lines).
    const spanDays = (d) => !(+d > 0) ? '' : +d < 1 ? 'under a day' : `${num(Math.round(+d))}\u00a0day${Math.round(+d) === 1 ? '' : 's'}`;
    const longSub = [...(m.pnl == null ? [] : later ? [`later-period P&amp;L${overDays(m.days)} after the split date${noPass ? '' : ', which picked it'}`, 'not\u00a0held\u00a0out']
      : oos ? [`later-period P&amp;L${overDays(m.days)} after the split date`, 'unseen\u00a0data'] : ['on the history it searched' + overDays(m.days)]), verdictWord].filter(Boolean).join(SEP);
    // Each short phrase holds together, so a narrow card breaks only at a separator ("unseen / data" split it).
    const shortSub = [...(m.pnl == null ? [] : [oos ? 'later\u00a0period' : 'history it searched', spanDays(m.days), later ? 'not\u00a0held\u00a0out' : oos ? 'unseen\u00a0data' : '']),
      verdictWord === 'did not pass' ? 'did\u00a0not\u00a0pass' : verdictWord].filter(Boolean).join(SEP);
    const pnlSub = !longSub ? '' : shortSub.replace(/\u00a0/g, ' ') === longSub.replace(/\u00a0/g, ' ') ? `<div class="sub-fig">${longSub}</div>`
      : `<div class="sub-fig bt-sub" title="${longSub}"><span class="bt-long">${longSub}</span><span class="bt-short" aria-hidden="true">${shortSub}</span></div>`;
    const tried = s.hypotheses_tried != null ? num(s.hypotheses_tried) : s.parent_id ? 'Adjustment' : '\u2014';
    const name = opts.nolink ? esc(s.title) : `<a href="/strategies/${s.id}">${esc(s.title)}</a>`;
    const missed = Array.isArray(opts.missed) && opts.missed.length ? `<div class="slip-missed">${whyFailedHtml(opts.missed.slice(0, 1))}${opts.missed.length > 1 ? `<a class="sub-fig" href="/strategies/${s.id}">${opts.missed.length - 1} more check${opts.missed.length > 2 ? 's' : ''} on its page</a>` : ''}</div>` : '';
    const pickCell = opts.pick ? (bulkDeployable(s)
      ? `<td class="pickcol" data-lab="Deploy"><input type="checkbox" class="pick" data-id="${s.id}" aria-label="Select ${esc(s.title)} for deployment"></td>`
      : '<td class="pickcol" data-lab=""></td>') : '';
    return `<tr class="${opts.land ? 'washed' : ''}">${pickCell}
      <td class="name" data-lab="">${name}${s.shared_from ? ` <span class="shared-flag">${ICON.share}${esc(s.shared_from)}</span>` : ''}${s.example ? ' ' + EXAMPLE_TAG : s.by_autopilot ? ' ' + AP_STRAT_TAG : ''}${missed}${opts.next ? `<div class="slip-next">${opts.next}</div>` : ''}</td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(s.market))}\u00a0· ${esc(dirLabel(s.direction))}</span></td>
      <td class="num" data-lab="Backtest P&amp;L">${m.pnl == null ? '\u2014' : noPass ? `<span class="pnl-nopass">${usd(m.pnl, true)}</span>` : money(m.pnl)}${pnlSub}</td>
      <td class="num" data-lab="Trades">${m.trades == null ? '\u2014' : num(m.trades)}</td>
      <td class="num" data-lab="Win">${pct(m.win_rate, false)}</td>
      ${opts.paper ? paperCell(s) : ''}
      ${opts.inRun ? '' : `<td class="num${tried === '\u2014' ? ' nil' : ''}" data-lab="Ideas tested">${esc(tried)}</td>`}
      <td class="act st" data-lab="Status">${statusMark(s)}${researchBadge(s)}${s.deployed && !researchOnly(s) ? ` ${bookBadge(s)}${s.real && s.real.paused ? ' ' + mark('paused') : ''}${bookLive(s) ? liveWaitLine() : ''}${statusReal(s, opts.paper || opts.paperNext)}` : ''}${researchOnly(s) ? '' : statusPast(s, opts.paper)}</td>
    </tr>`;
  }
  const DEP_HEAD = (controls) => `<thead><tr><th>Strategy</th><th>Status</th><th class="num">${gl('Realized P&amp;L', 'realized')}</th><th class="num">${gl('Unrealized', 'unrealized')}</th><th class="num">Trades</th>${controls ? '<th class="act"><span class="vh">Actions</span></th>' : ''}</tr></thead>`;
  const deploymentTable = (rows, controls) => `<div class="sheet"><table class="stack t-dep">${DEP_HEAD(controls)}<tbody>${rows}</tbody></table></div>`;
  const deploymentRemove = (d) => `<button class="btn sm danger" data-dep="${esc(d.id)}" data-act="stop" data-open="${+d.open_positions || 0}">Remove<span class="vh"> ${esc(d.title)}</span></button>`;
  // A demo copy the demo-copy sync paused waits on its paper deployment: Resume would be paused again
  // at the sync's next pass, so it is offered disabled with the server's reason (resume_block), which
  // the row's status line also says.
  const resumeButton = (d, why = resumeBlock(d)) => `<button class="btn sm" data-dep="${d.id}" data-act="resume"${why ? ` disabled title="${esc(why)}"` : ''}>Resume<span class="vh"> ${esc(d.title)}${why ? ': ' + esc(why) : ''}</span></button>`;
  const deploymentActions = (d, remove = true) => `<div class="deployment-actions">
    ${d.status === 'running' ? `<button class="btn sm" data-dep="${d.id}" data-act="pause" data-open="${+d.open_positions || 0}">Pause<span class="vh"> ${esc(d.title)}</span></button>` : ''}
    ${d.status === 'paused' ? resumeButton(d) : ''}
    ${remove ? deploymentRemove(d) : ''}</div>`;
  // What the deployment's closed trades would have made at the unseen-data backtest's average per
  // trade: the number to hold realized P&L against (the backtest total covers a different trade count).
  const backtestPace = (d) => {
    const oos = d.backtest && d.backtest.out_of_sample, n = +d.closed_trades || 0;
    if (!oos || !(+oos.trades > 0) || !n) return '';
    return `Backtest estimate ${usd((+oos.pnl || 0) / +oos.trades * n, true)} for the same ${num(n)} trade${n === 1 ? '' : 's'}${SEP}`;
  };
  // Each fact keeps its label with its value (.dep-fact never wraps inside): "· Deployed" ended one line and
  // "Oct 18" began the next, on a phone and in the Deploy table's name column on a desktop.
  // A strategy from a research session keeps its unseen result with the gatekeeper, not in its backtest: its row read
  // "Unseen P&L —" as though it had none. The fact shows only with a backtest figure to give. A backtest-only strategy's
  // (the server's backtest_only) is its backtest's later slice, which picked it: "not held out", never unseen. Either
  // is the backtest after its split date, so both say "Later-period P&L" and then which kind, as the Strategies list
  // does ("later period · unseen data" / "· not held out"): a held-out row read "Unseen P&L" here alone. Its hover
  // says the same pair as Tau's Backtest estimate hover; only the backtest-only one had one ("…which picked it: not held out").
  const DEP_FACT_TIP = 'After its split date (later period\u00a0· unseen data)';
  const DEP_FACT_TIP_LATER = 'After its split date, which picked it (later period\u00a0· not held out)';
  // A Void strategy with no gatekeeper record (the server's void_no_record, with backtest_only): not held out either,
  // but nothing picked it, so its hover leaves that out, as its Strategies row and page do. It read "unseen data".
  const DEP_FACT_TIP_VOID = 'After its split date (later period\u00a0· not held out)';
  const deploymentEvidence = (d, manage = false) => `<details class="dep-evidence" data-deployment="${esc(d.id)}"><summary aria-label="Backtest and deployment details">Details</summary><div>${backtestPace(d)}${d.backtest && d.backtest.out_of_sample ? `<span class="dep-fact" title="${d.void_no_record ? DEP_FACT_TIP_VOID : d.backtest_only ? DEP_FACT_TIP_LATER : DEP_FACT_TIP}">Later-period P&amp;L ${usd(d.backtest.out_of_sample.pnl, true)}</span>${SEP}<span class="nobr">${d.backtest_only ? 'not\u00a0held\u00a0out' : 'unseen\u00a0data'}${glo(d.void_no_record ? 'latervoid' : d.backtest_only ? 'laterperiod' : 'unseen')}</span>${SEP}` : ''}<span class="dep-fact">Deployed ${when(d.created_at)}</span>${manage ? `<div class="deployment-actions">${deploymentRemove(d)}</div>` : ''}</div></details>`;
  // A demo row says what it is: Kalshi's sandbox with play money, a copy of its paper run when it has
  // one, there to prove the order path before live. Its fills differ from paper's because the demo
  // book is thin, which is also why its P&L is no evidence of the edge (paper keeps that job).
  // A deployment's sizing on its Deploy row and monitor card. A spec stored without sizing sends stake and
  // max_positions as null: it says the stake is not set and leaves out the cap, instead of "$ / trade".
  // The stake is money: whole dollars as "$25", anything else to the cent as every amount is ("$12.5 / trade" read
  // beside "$12.50"s, walk 2026-10-31). A value that isn't a number is shown as stored, escaped.
  const stakeFig = (v) => (Number.isFinite(+v) ? (Number.isInteger(+v) ? '$' + num(+v) : usd(+v)) : `$${esc(v)}`);
  const depStake = (d) => d.stake != null ? `${stakeFig(d.stake)} / trade` : gl('Stake not set', 'stake');
  const depCap = (d) => d.max_positions != null ? `Max ${esc(d.max_positions)} open` : '';
  // A running deployment's state: "Running", or what it is waiting on when it places no orders (depIdle).
  const depState = (d, live) => d.status !== 'running' ? mark(d.status, live)
    : depIdle(d) ? `<span class="deployment-state idle">${esc(depIdle(d).state)}</span>` : '<span class="deployment-state">Running</span>';
  const depIdleLine = (d) => depIdle(d) ? `<div class="sub-fig dep-idle">${esc(depIdle(d).why)}</div>` : '';
  // The row's market, stake and cap: "$5 / trade" and "Max 2 open" each stay whole (.nobr) and each "·" ends its
  // line: at 390px "Max 2" ended a line and "open" began the next.
  function deploymentSlip(d, controls, regs) {
    const live = d.mode === 'live';
    const modeTag = deploymentMode(d);
    const actions = controls ? `<td class="act" data-lab="">${deploymentActions(d)}</td>` : '';
    return `<tr class="${live ? 'live-row' : ''}">
      <td class="name" data-lab=""><a href="/strategies/${d.strategy_id}">${esc(d.title)}</a>
        <div class="dep-meta"><span class="sub-fig">${[esc(marketFull(d.market)), depStake(d), depCap(d)].filter(Boolean).map((t, i) => (i ? `<span class="nobr">${t}</span>` : t)).join('\u00a0\u00b7 ')}${d.status !== 'running' && (d.status_why || d.status_reason) ? '\u00a0\u00b7 ' + fundsLinked(esc(d.status_why || d.status_reason)) : ''}</span>
        ${deploymentEvidence(d)}</div>${depIdleLine(d)}${demoRowLine(d)}${btCheckLine(d.backtest_check)}${depInstant(d)}${roadLine(d, liveOpen())}</td>
      <td data-lab="Status">${depState(d, live)}<div class="sub-fig">${modeTag}</div></td>
      <td class="num" data-lab="Realized">${realizedCell(d)}${spark(d.curve, regs && regs[d.mode], d.closed_trades)}</td>
      <td class="num" data-lab="Unrealized">${d.unrealized_pnl == null ? `<span class="sub-fig">${+d.open_positions ? NOT_MARKED : 'None open'}</span>` : markFig(d.oldest_mark_ts, money(d.unrealized_pnl))}${d.unrealized_pnl != null && d.open_positions ? ` <div class="sub-fig">est.${markOld(d.oldest_mark_ts) ? ' ' + markedAt(d.oldest_mark_ts) : ''}</div>` : ''}</td>
      <td class="num" data-lab="Trades">${num(d.closed_trades)} closed${d.open_positions ? ` <div class="sub-fig">${num(d.open_positions)} open</div>` : ''}</td>
      ${actions}
    </tr>`;
  }
  // A dashboard card's setup and limits lines, inline one after the other: the stake and the cap each stay whole
  // (.nobr) and each "·" ends its line. The limits line began " · Max 2 open" with a plain space, so at 390px
  // "· Max 2 open" could start a line.
  // A demo or live monitor's Realized P&L says its book and fees, as the strategy page's book lines do: "+$2.17"
  // under "Demo · Running" didn't say it was Tau's demo book, not real money, or after Kalshi's fees.
  const monitorNet = (mode) => mode === 'live' ? 'real money, after Kalshi fees' : mode === 'demo' ? `after Kalshi fees, in ${DEMO_BOOK}: not real money` : '';
  // Its Unrealized, like a Deploy row's, is dimmed and says how old its oldest mark is once that is old (withMarkAge).
  function deploymentMonitor(d, anchor = false, regs = null) {
    const live = d.mode === 'live';
    return `<article ${anchor ? 'id="dash-paused" ' : ''}class="dep-monitor${live ? ' live-row' : ''}">
      <header><h3><a href="/strategies/${d.strategy_id}">${esc(d.title)}</a></h3><span class="monitor-state"><span class="monitor-mode">${deploymentMode(d)}</span><span aria-hidden="true">·</span>${depState(d, live)}</span></header>
      <div class="monitor-config"><div class="monitor-summary"><p class="monitor-setup">${esc(marketFull(d.market))}${SEP}<span class="nobr">${depStake(d)}</span></p><div class="monitor-limits"><span>${depCap(d) ? `${SEP}<span class="nobr">${depCap(d)}</span>` : ''}${d.status !== 'running' && (d.status_why || d.status_reason) ? SEP + fundsLinked(esc(d.status_why || d.status_reason)) : ''}</span></div></div>${depIdleLine(d)}${demoRowLine(d)}${depInstant(d)}</div>
      <dl class="monitor-metrics">
        <div class="monitor-realized"><dt>Realized P&amp;L</dt><dd>${realizedCell(d, '<span class="unavailable">None yet</span>')}${spark(d.curve, regs && regs[d.mode], d.closed_trades)}</dd>${d.mode === 'paper' ? `<dd class="sub-fig paper-net">${gl(PAPER_NET, 'paperfills')}</dd>` : d.closed_trades ? `<dd class="sub-fig book-net">${monitorNet(d.mode)}</dd>` : ''}</div>
        <div class="monitor-unrealized"><dt>${d.unrealized_pnl != null && d.open_positions ? 'Unrealized (est.)' : 'Unrealized P&amp;L'}</dt><dd>${d.unrealized_pnl == null ? `<span class="unavailable">${+d.open_positions ? NOT_MARKED : 'None open'}</span>` : markFig(d.oldest_mark_ts, money(d.unrealized_pnl))}</dd>${d.unrealized_pnl != null && markOld(d.oldest_mark_ts) ? `<dd class="sub-fig mark-when">${markedAt(d.oldest_mark_ts)}</dd>` : ''}</div>
      </dl>
      <div class="monitor-footer"><dl class="monitor-counts"><div><dt>Closed / open</dt><dd aria-label="${num(d.closed_trades)} closed trades, ${num(d.open_positions || 0)} open positions">${num(d.closed_trades)} / ${num(d.open_positions || 0)}</dd></div></dl><div class="monitor-controls">${deploymentActions(d, false)}${deploymentEvidence(d, true)}</div></div>
    </article>`;
  }
  function replaceDeploymentContent(host, html) {
    if (!host || painted.get(host) === html) return;
    painted.set(host, html);
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
    const msg = q.has('pending')
      ? "You're on the waitlist — we'll email you the moment you're approved. (Access is invite-only right now.)"
      : { cancelled: 'Sign-in was cancelled.', expired: 'That sign-in link expired. Try again.', google: "Google couldn't confirm your account. We may not have added you to the waitlist yet." }[err] || sessionEndedText();
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
      const d = withMarkAge(followLive(pollAnswer(kept, got)));
      if (!got.same) kept = got;
      if (gen !== S.gen) return;
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
      const mSub = (b, zero) => (b.open_positions || b.running || b.realized_pnl) ? `Tau trades: ${num(b.open_positions)} open${b.open_positions ? ' (not in cash)' : ''}${SEP}${usd(b.realized_pnl, true)} realized all time${SEP}${usd(b.today_pnl, true)} realized today (UTC)` : zero;
      const hasLive = d.deployments.some((x) => x.mode === 'live' && x.status !== 'stopped');
      const paperWorkspace = !hasLive && d.open_positions.concat(d.recent_closed, d.deployments).every(x => x.mode === 'paper');
      const sharedPaperRunning = d.deployments.length > 0 && d.deployments.every(x => x.mode === 'paper' && x.status === 'running');
      // Collector lag is the operator's to fix, so only the admin view shows it (red "needs you" told
      // every user something was wrong that they couldn't act on). It stays red there: no Bitcoin spot candles, or
      // none for 45 minutes, means the collector is down and new backtests run on missing prices. It names the feed it
      // means: "No backtest history yet" beside a passed strategy read as that strategy having no backtest (walked 2026-10-30).
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
        hasLive ? `${liveOpen() ? 'Live money on' : 'Live trading isn\u2019t open yet'}: ${usd(d.live.realized_pnl, true)} realized all time${liveOpen() ? '' : ' on live money'}` : '',
        paused ? `<a class="needs-link" href="#dash-paused"><em>${num(paused)} paused, needs you</em></a>` : '',
        stale ? `<em>${d.freshness.btc == null ? 'No Bitcoin price history collected yet' : 'Bitcoin price history ' + age(d.freshness.btc) + ' behind'}</em>` : '',
      ].filter(Boolean).join('<span class="sep">/</span>');
      // A live cash still being checked reads Checking\u2026 (or its last figure, with its age), never $0 (cashFig).
      // Drawn from cashNow: a pending cash read under two minutes ago shows as current while its follow-up is out.
      const lv = cashNow(d.live);
      const liveCf = lv.connected && cashFig(lv);
      // A connected key's real cash is never behind the Accounts menu: with paper leading the band (no live
      // deployment, the usual case while live is closed), it sits under the paper figure as its own figure, never
      // added to it, and says when Kalshi was read, as Tau's dashboard does. Only a missing key stays in the menu.
      const cashInBand = !hasLive && lv.connected;
      const liveFigure = fig('Kalshi cash', lv.connected ? (liveCf ? liveCf[0] : lv.balance == null ? 'Unavailable' : usd(lv.balance)) : 'Not connected', { cls: cashInBand ? 'kalshi-cash' : '', small: (lv.connected ? (liveCf ? [liveCf[1], mSub(lv, '')].filter(Boolean).join(SEP) : lv.balance == null ? ['Couldn\u2019t read your Kalshi balance just now', mSub(lv, '')].filter(Boolean).join(SEP) : [cashAt(lv), mSub(lv, LIVE_IDLE())].filter(Boolean).join(SEP)) : '<a href="/funds#connect-kalshi">Connect Kalshi</a>') + tradesCsv('live', lv) });
      // Each live figure in the band names its book, as "Live realized today (UTC)" does: beside a positions table headed
      // "2 paper · 1 live", a bare "Open positions 1" didn't say it counted only the live book (walked 2026-10-30).
      const liveSummary = `<div class="m live-summary"><dt class="lab vh">Kalshi cash</dt><dd class="portfolio-numbers"><div class="portfolio-group"><div><span class="lab" aria-hidden="true">Kalshi cash</span><strong class="fig${!lv.connected || (liveCf ? lv.last_balance == null : lv.balance == null) ? ' balance-state' : ''}">${lv.connected ? (liveCf ? liveCf[0] : lv.balance == null ? 'Unavailable' : usd(lv.balance)) : 'Not connected'}</strong><span class="portfolio-return">${lv.connected ? (liveCf ? `${liveCf[1]}${SEP}${money(lv.realized_pnl)} realized all time by Tau trades` : lv.balance == null ? `Couldn\u2019t read your Kalshi balance just now${SEP}${money(lv.realized_pnl)} realized all time by Tau trades` : [cashAt(lv), `${money(lv.realized_pnl)} realized all time by Tau trades`].filter(Boolean).join(SEP)) : '<a href="/funds#connect-kalshi">Connect Kalshi</a>'}${tradesCsv('live', lv)}</span></div><div class="portfolio-detail"><span class="lab">Live realized today (UTC)</span><strong>${money(lv.today_pnl)}</strong></div></div><div class="portfolio-group"><div class="portfolio-detail"><span class="lab">Live open positions</span><strong>${esc(lv.open_positions)}</strong></div><div class="portfolio-detail"><span class="lab">Live open at ${openBasis(lv)}, not in cash</span><strong>${openFig(lv)}</strong></div></div></dd></div>`;
      const demoFigure = (demoKeyless(d.demo) ? fig(DEMO_BOOK, 'No demo key', { small: DEMO_NO_KEY }) : fig(DEMO_BOOK, usd(d.demo.equity), { v: d.demo.realized_pnl, small: `${d.demo.health ? demoHealthLine(d.demo.health) + '<br>' : ''}${(d.demo.open_positions || d.demo.running || d.demo.realized_pnl || d.demo.closed_trades) ? `${demoCapital(d.demo)}${SEP}${num(d.demo.open_positions)} open${SEP}${demoPnl(d.demo, d.demo.realized_pnl)}` : `${demoCapital(d.demo)}${SEP}no demo strategies yet`}${SEP}${DEMO_WHAT}${tradesCsv('demo', d.demo)}` }));
      // Tau's own dashboard says "practice money" beside the paper figure; here the $1,000 "Available cash" said nothing, so a
      // newcomer could take it for real money.
      // A book that has never been used has no realized P&L yet (Tau's dashboard says "no paper strategies yet"):
      // "Realized P&L, all time $0.00" and "Realized today $0.00" read as results to a new account, and so did
      // "Open at cost + fees $0.00" beside them: nothing has ever been open. A book that has traded keeps its figure.
      const paperNew = !(p.open_positions || p.closed_trades || p.total_pnl || d.deployments.some((x) => x.mode === 'paper'));
      // The day's realized figure names its book ("Paper realized today", "Live realized today"): beside a Kalshi cash
      // band, a bare "Realized today (UTC) −$0.57" didn't say it was paper's (walked 2026-10-27 with a live key).
      const paperFigure = `<div class="m paper-summary"><dt class="lab vh">Paper portfolio</dt><dd class="portfolio-numbers"><div class="portfolio-group"><div><span class="lab" aria-hidden="true">Paper portfolio</span><strong class="fig">${usd(p.equity)}</strong><span class="portfolio-return"><span class="nobr">Practice money, not real</span>\u00a0· ${paperNew ? '<span class="nobr">no paper strategies yet</span>' : !hasClosed(p) ? '<span class="nobr">P&amp;L shows once a paper trade closes</span>' : `${pnlWin('all')} <span class="nobr">realized P&amp;L${glo('realized')} ${money(p.realized_pnl)}</span>\u00a0· <span class="nobr">${PAPER_NET}${glo('paperfills')}</span>${tradesCsv('paper', p)}${slipEstGl(p.slippage_estimate)}`}</span></div><div class="portfolio-detail"><span class="lab">${pnlWin('today')} paper realized</span><strong>${!hasClosed(p) ? 'None yet' : money(p.today_pnl)}</strong></div></div><div class="portfolio-group"><div class="portfolio-detail"><span class="lab">Available cash</span><strong>${usd(p.cash)}</strong></div><div class="portfolio-detail"><span class="lab">Open at ${openBasis(p)}</span><strong>${paperNew ? 'None yet' : hasOpen(p) ? openFig(p) : 'None open'}</strong>${inBalance(p, 'the portfolio') ? `<span class="sub-fig">${inBalance(p, 'the portfolio')}</span>` : ''}</div></div></dd></div>`;
      const board = `
        ${said ? `<div class="statusline dashboard-status ${needs ? 'needs' : ''}"><p class="said">${said}</p></div>` : ''}
        ${d.demo.health ? `<div class="notice bad" role="status">${ICON.warn}<span>${demoHealthLine(d.demo.health)}</span></div>` : ''}
        ${d.live.connected && d.live.open_positions ? `<p class="recon ${(d.reconcile && d.reconcile.length) ? 'warn' : 'ok'}">${(d.reconcile && d.reconcile.length) ? reconWarn(d.reconcile) : `${ICON.check} Live book reconciled with Kalshi`}</p>` : ''}
        <div class="pagehead"><div class="overview-heading"><h1 class="page">Dashboard</h1></div><div class="page-actions"><details class="other-accounts" id="other-accounts"${accountsOpen ? ' open' : ''}><summary>Accounts ${ICON.chev}</summary><dl>${hasLive ? paperFigure : cashInBand ? '' : liveFigure}${demoFigure}</dl></details>${agentsBusy ? `<a class="research-activity" href="/research">${agentsBusy} agent${agentsBusy > 1 ? 's' : ''} researching</a>` : ''}</div></div>`;
      const firstPaused = d.deployments.find((x) => x.status === 'paused');
      const depRegs = curveRegs(d.deployments);  // the status line's "paused, needs you" jumps here
      const deps = d.deployments.length
        ? `<div class="dep-register">${d.deployments.map((x) => deploymentMonitor(x, x === firstPaused, depRegs)).join('')}</div>`
        : `<div id="deps-empty" data-on="${S.me.user && S.me.user.autopilot ? 1 : 0}">${depsEmpty(S.me.user && S.me.user.autopilot)}</div>`;
      const positionMarket = r => contractMkt(r.ticker);
      const depMarket = (r) => (d.deployments.find((x) => x.id === r.deployment_id) || {}).market;
      // An open position's Unrealized P&L says when its mark was read (the engine's mark_ts), as Deploy's does: with
      // the engine stopped, a mark hours old read as this minute's. An old mark's figure is dimmed and says how old.
      const positions = (rows, closed) => rows.map((r) => {
        const name = contractName(r.ticker, depMarket(r));
        const close = r.market_close_time && new Date(r.market_close_time);
        const expiry = close && Number.isFinite(close.getTime()) ? close.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' }) : '';
        // An open row whose market has already closed says so under its expiry, in the words Tau's dashboard, Deploy and
        // the market page use. Walked 2026-10-30: a live position still held a day after its close read only "Oct 29,
        // 07:48 UTC" under Expiry, a date that read as still to come. Words only: the row, its book and figures are the server's.
        const pastClose = !closed && expiry && close.getTime() <= Date.now();
        // The row's name reads as it shows, market then book (axe label-content-name-mismatch), then its strategy: it read
        // "market · strategy · Demo" over a row that shows "market … Demo", whose words ran together ("minutesDemo") with
        // nothing between them. The grid still places each where it was (a space between grid items draws nothing).
        return `<tr class="${closed ? 'settled-position' : 'open-position'}">
        <td class="name"><details class="position-details" data-position="${closed ? 'closed' : 'open'}-${esc(r.id)}"><summary aria-label="${esc(name)}${SEP}${r.mode === 'live' ? 'LIVE' : r.mode === 'demo' ? 'Demo' : 'Paper'}${SEP}${esc(r.title)}">${ICON.chev}<span class="position-market">${esc(name)}</span> <span class="position-mode">${r.mode === 'live' ? '<span class="mk live">LIVE</span>' : r.mode === 'demo' ? 'Demo' : 'Paper'}</span> <span class="position-title vh">${esc(r.title)}</span></summary><div class="sub-fig">${kalshiRef(r.ticker)}${SEP}${esc(r.title)}<span class="position-opened">${closed ? 'Closed' : 'Opened'} ${when(closed ? r.closed_at : r.opened_at)}</span>${r.why ? `<span class="position-why">${sepLine(r.why)}</span>` : ''}${close && Number.isFinite(close.getTime()) ? `<span class="position-absolute">Expires ${esc(close.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'long', hourCycle: 'h23' }))}</span>` : ''}${!closed && r.unrealized == null ? `<span class="position-mark-note">Unrealized: ${NOT_MARKED.toLowerCase()}</span>` : ''}</div></details></td>
        <td class="position-size-cell"><span class="position-size"><span class="position-side">${esc(r.side.toUpperCase())}</span><span aria-hidden="true"> × </span><span class="position-quantity"><span class="vh">Quantity </span>${esc(r.qty)}</span></span></td>
        <td class="position-expiry-cell">${expiry ? `<time class="position-expiry" datetime="${esc(close.toISOString())}">${esc(expiry)}</time>${pastClose ? `<span class="position-expired">${MKT_STATUS.closed}</span>` : ''}` : '<span class="unavailable" title="Expiry unavailable"><span aria-hidden="true">—</span><span class="vh">Expiry unavailable</span></span>'}</td>
        <td class="num position-entry">${cents(+r.entry_price)}</td>
        ${closed ? '' : `<td class="num"><span class="position-cost">${usd(r.cost != null ? r.cost : r.at_cost != null ? r.at_cost : r.qty * r.entry_price)}</span></td>`}
        <td class="num"><span class="position-pnl">${closed ? money(+r.pnl) : (r.unrealized != null ? markFig(r.mark_ts, money(r.unrealized)) : NO_MARK)}</span>${!closed && r.unrealized != null && r.mark_ts ? `<span class="position-marked">${markedAt(r.mark_ts)}</span>` : ''}</td>
        </tr>`;
      }).join('');
      const paperOnly = (rows) => rows.length && rows.every(r => r.mode === 'paper');
      // Which books a list of positions covers, beside its count. It sits under the Paper portfolio band, beside the
      // band's paper-only "Open at cost + fees": "Open positions 3" with a Demo row among them read as three paper
      // positions. One book names it; more than one says "All books" and counts each book apart, never one
      // count across books (as Deploy's "Open positions" figure does). Only counts: no money is added up here.
      const BOOK_WORD = { paper: 'Paper', demo: 'Demo', live: 'Live' };
      const bookCount = (rows) => {
        const modes = [...new Set(rows.map((r) => r.mode))];
        if (modes.length <= 1) return { n: num(rows.length), book: BOOK_WORD[modes[0]] || '' };
        const split = ['paper', 'demo', 'live'].map((m) => [m, rows.filter((r) => r.mode === m).length]).filter(([, n]) => n)
          .map(([m, n]) => `${num(n)}\u00a0${m}`);
        const other = rows.filter((r) => !BOOK_WORD[r.mode]).length;
        if (other) split.push(`${num(other)}\u00a0other`);
        return { n: split.join('\u00a0\u00b7 '), book: 'All books' };
      };
      const bookHead = (rows) => { const c = bookCount(rows); return { n: c.n, book: c.book ? ` <span class="position-group-mode">${c.book}</span>` : '' }; };
      const openHead = bookHead(d.open_positions), closedHead = bookHead(d.recent_closed);
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
        return `<div class="sheet"><table class="t-positions" data-paper-only="${onlyPaper}"><colgroup>${widths.map(width => `<col style="width:${width / 808 * 100}%">`).join('')}</colgroup><thead><tr><th scope="col">Market / contract</th><th scope="col">Position</th><th scope="col">Expiry</th><th scope="col" class="num">Entry</th>${closed ? '' : '<th scope="col" class="num">Cost + fee</th>'}<th scope="col" class="num" title="${closed ? 'Realized result after settlement' : 'Estimated from the latest stored bid'}">${closed ? 'Realized' : 'Unrealized'} P&amp;L</th></tr></thead>${bodies}</table></div>`;
      };
      const days = (p.daily || []).slice(-30);
      let periodPnl = 0;
      const periodCurve = days.map(day => [Date.parse(day.d + 'T12:00:00Z') / 1000, periodPnl += +day.pnl]);
      const paperPlot = (width) => equityChart(periodCurve, null, null, { width: Math.max(280, width || root.querySelector('#main').clientWidth), height: 180, paper: true, fit: true, endLabel: false, label: `Cumulative closed paper profit and loss from ${days[0].d} through ${days[days.length - 1].d}; ends at ${usd(periodPnl, true)}` });
      const periodLabel = days.length > 1 ? new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'}).formatRange(new Date(days[0].d + 'T12:00:00Z'), new Date(days[days.length - 1].d + 'T12:00:00Z')) : '';
      const performance = days.length > 1 ? `<details class="overview-performance" id="paper-performance"${performanceOpen ? ' open' : ''}><summary><span class="performance-heading"><span class="performance-caption"><h2>Closed P&amp;L</h2>${ICON.chev}</span><strong class="${tone(periodPnl)}" title="Cumulative closed P&L over this period">${usd(periodPnl, true)}</strong></span><span class="performance-meta"><span class="performance-mode"><span class="performance-mode-prefix">Paper${SEP}</span>cumulative, ${PAPER_NET}</span><span class="sect-note" title="${esc(days[0].d)} – ${esc(days[days.length - 1].d)}">${esc(periodLabel)}</span></span></summary><div class="paper-plot">${paperPlot()}</div></details>` : '';
      const main = `${apFirst ? '' : sinceStrip(d, '#dash-paused')}<section id="dash-ap" class="apcard" aria-label="Autopilot"></section>${apFirst ? sinceStrip(d, '#dash-paused') : ''}<div class="dash${paperWorkspace ? ' paper-workspace' : ''}"><div class="dash-layout">
        <section class="account-band"><dl class="figures measure dashboard-figures ${hasLive ? 'live-primary' : ''}">${hasLive ? liveSummary : paperFigure + (cashInBand ? liveFigure : '')}</dl><p class="stale-note" id="dash-stale" role="status"></p></section>
        <section class="positions-ledger" id="dash-open"><div class="sect-head"><h2>Open positions <span class="section-count">${openHead.n}</span>${openHead.book}</h2></div>
          ${d.open_positions.length ? positionTable(d.open_positions, false) : '<p class="hint">No open positions.</p>'}
          ${d.recent_closed.length ? `<details class="recent-settlements" id="recent-settlements"${settlementsOpen ? ' open' : ''}><summary>Recent settlements <span>${closedHead.n}</span>${closedHead.book}</summary>${positionTable(d.recent_closed, true)}</details>` : ''}
        </section><div class="dash-analysis">${performance}<section class="sect deployed-monitor${sharedPaperRunning ? ' shared-paper-running' : ''}"><div class="sect-head"><div class="monitor-heading"><h2>Deployed strategies <span class="section-count">${num(d.deployments.length)}</span></h2>${sharedPaperRunning ? '<span class="monitor-context">Paper</span>' : ''}${d.deployments.length ? '<a href="/research?new=1" class="btn">New research</a>' : ''}</div></div><div id="dash-deps">${deps}</div></section></div></div></div>`;
      paint(root.querySelector('#boardbody'), board);  // the 15s poll repaints only what changed
      if (accountsFocused) root.querySelector('#other-accounts > summary').focus({ preventScroll: true });
      keepApCard(() => replaceDeploymentContent(root.querySelector('#main'), main));
      S.dashPaper = p;
      S.dashPaused = d.deployments.filter((x) => x.status === 'paused').length;
      paintDashAp();
      resizePaperChart = days.length > 1 ? () => {
        const plot = root.querySelector('.paper-plot');
        if (plot) {
          const focused = plot.querySelector('.chart-sample:focus')?.dataset.time;
          paint(plot, paperPlot(plot.clientWidth));
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
    if (gen !== S.gen) return;
    poll(load, 15000, 'dash-stale');
    dashTrackRecord(trFirst);
  }

  // ---------- research ----------
  // In page-research.js (one for both themes), fetched on first use (page files, at the end of this file).
  function viewResearch() { return pageView('research', 'viewResearch', '/research', []); }
  function viewRun(id) { return pageView('research', 'viewRun', '/research', [id]); }

  // ---------- strategies ----------
  // The list is in page-strategies.js (one for both themes); one strategy's page, with its research paper and its
  // Deploy panel, in app.meridian-strategy.js. Each fetched on first use (page files, at the end of this file).
  function viewStrategies() { return pageView('strategies', 'viewStrategies', '/strategies', []); }
  function viewStrategy(id) { return pageView('strategy', 'viewStrategy', '/strategies', [id]); }

  // ---------- deploy + chat ----------
  const deployedNote = (n) => `Deployed on ${n.mode}: ${n.title}. It trades only when its rule fires, ${n.mode === 'demo' ? 'on Kalshi’s demo exchange with no real money' : 'against live prices with paper money'}, so the first trade can take a while. Its trades show up here and on the Dashboard.`;
  // An open position with no mark yet (the engine prices it on its next tick): a dash, kept to fit the table's cell, that
  // a screen reader hears and a hover shows as "Not marked yet" (NOT_MARKED, every page's phrase). The dashboard's
  // positions, Deploy's and a market page's own; a bare "—" on the last two said nothing, and was read aloud as "dash".
  const NO_MARK = `<span class="unavailable" title="${NOT_MARKED}"><span aria-hidden="true">—</span><span class="vh">${NOT_MARKED}</span></span>`;
  async function viewDeploy() {
    // Autopilot + the agent chat now live in the floating window (reachable from every view),
    // so Deploy is just the board: what's trading and the open positions.
    shell('/deploy', ledeTitle('Deploy', 'Your strategies trading now.') +
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
      const d = withMarkAge(withUnrealized(followLive(pollAnswer(kept, got))));
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
      const listedLab = (lab, xs) => (xs.length ? `${lab}, listed below` : lab);
      // A book with no closed trade yet, listed or removed, has no P&L: it says "None yet", never a $0.00 that reads
      // as trading flat. Its line keeps what the figure is (paper, not real; after fees and the spread) and no more: at
      // 390px "· shows once a paper trade closes" made it five lines under a figure that already says None yet.
      const noneYet = (m, xs) => !listed(m, xs) && xs.every((x) => !+x.closed_trades && !+x.realized_pnl) && !(books[m] && +books[m].removed_deployments);
      const realizedFig = (m, xs, v) => (noneYet(m, xs) ? 'None yet' : usd(v, true));
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
      paint(root.querySelector('#dfigs'), fig('Running', num(active.length), { small: `${num(d.deployments.length - running.length)} paused${idle ? `${SEP}${idle} placing no orders` : ''}` }) +
        (liveDeps.length
          ? fig(listedLab('Live realized', liveDeps), realizedFig('live', liveDeps, liveRealized), { v: liveRealized, small: `real money${removedNote('live')}\u00a0· after Kalshi fees${paperDeps.length ? `\u00a0· ${paperSlip ? `<span class="slip-tip"${slipTip(paperSlip)}>${usd(paperRealized, true)}</span>` : usd(paperRealized, true)} on paper from the deployments listed, counted apart, ${gl(PAPER_NET, 'paperfills')}` : ''}` })
          // Beside a Demo realized figure the paper one names its book: a bare "Realized" next to "Demo realized" read
          // as the board's total, demo included. Paper alone keeps "Realized".
          : paperDeps.length || !demoDeps.length ? fig(listedLab(demoDeps.length ? 'Paper realized' : 'Realized', paperDeps), realizedFig('paper', paperDeps, paperRealized), { v: paperRealized, small: `paper money, not real${removedNote('paper')}\u00a0· ${gl(PAPER_NET, 'paperfills')}${slipEst(paperSlip)}` }) : '') +
        (demoDeps.length ? fig(listedLab('Demo realized', demoDeps), realizedFig('demo', demoDeps, demoRealized), { v: demoRealized, small: `${DEMO_WHAT}${removedNote('demo')}\u00a0· after Kalshi fees${noneYet('demo', demoDeps) ? '' : DEMO_RELOAD_KEPT}` }) : '') +
        fig('Open positions', openSplit) +
        // Money says plainly what runs: "PAPER · nothing on live money" read oddly (walk 2026-10-30). A live deployment
        // listed but not running (paused) keeps "nothing running" on live money: it may still hold live positions.
        fig('Money', live.length ? '<span class="mk live">Live</span>' : runDemo ? `${runPaper ? '<span class="mk">Paper</span> ' : ''}<span class="mk dep">Demo</span>` : '<span class="mk">Paper</span>', { small: live.length ? `${live.length} on live money` : liveIdle ? liveIdleCount(liveIdle) : liveDeps.length ? 'Nothing running on live money' : runDemo ? (runPaper ? 'Paper and demo only, nothing live' : 'Demo only, nothing live') : 'Paper money only, nothing live' }));
      const regs = curveRegs(d.deployments);
      replaceDeploymentContent(root.querySelector('#deps'), d.deployments.length ? deploymentTable(pausedFirst(d.deployments).map((x) => deploymentSlip(x, true, regs)).join(''), true)
        : `<div class="empty"><h3>Nothing deployed</h3><p>${passedN === 0 ? 'Nothing has passed yet. A strategy goes on the board once it passes every test in a research session, paper first.' : 'Open a passed strategy and deploy it here. Paper first: it trades the live market with paper money.'}</p>${S.me && S.me.user && S.me.user.autopilot ? '<p>Autopilot is on: strategies that pass every research test deploy here on their own, on paper.</p>' : ''}${apNudge('Rather not pick strategies yourself?', 'and it deploys the ones that pass, on paper.')}${passedN === 0 ? '<a class="btn" href="/research?new=1">New session</a>' : '<a class="btn" href="/strategies?status=passed">See passed strategies</a>'}</div>`);
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
      const posMarked = (p) => `<div class="sub-fig">${p.mark_ts ? markedAt(p.mark_ts) : 'at the last mark'}</div>`;
      // The figure and its time are one block: a phone's stacked card set the time on a row of its own under the
      // card's labels, one more row a position; it sits under its figure, in the Unrealized cell. An old mark's figure
      // is dimmed and its time says how old (markFig, markedAt).
      const posUnreal = (p) => `<div class="pos-unreal">${markFig(p.mark_ts, money(p.unrealized))}${posMarked(p)}</div>`;
      paint(root.querySelector('#openpos'), d.open_positions.length ? `<table class="table stack"><thead><tr><th>Strategy</th><th>Market</th><th>Side</th><th class="num">Cost + fee</th><th class="num">Unrealized</th><th class="num">Settles</th></tr></thead><tbody>
        ${d.open_positions.map((p) => `<tr><td class="name" data-lab="Strategy">${esc(p.title)} ${posBook(p)}</td><td class="pos-name" data-lab="Market">${contractLink(p.ticker, depMarket(p))}<div class="sub-fig">${kalshiRef(p.ticker)}</div>${p.why ? `<div class="sub-fig pos-why">${sepLine(p.why)}</div>` : ''}</td><td data-lab="Side">${esc(p.side.toUpperCase())} ×${num(p.qty)} @ ${cents(+p.entry_price)}</td><td class="num" data-lab="Cost + fee">${usd(p.cost != null ? p.cost : p.qty * p.entry_price + +p.entry_fee)}</td><td class="num" data-lab="Unrealized">${p.unrealized == null ? NO_MARK : posUnreal(p)}</td><td class="num"${closeData(p.market_close_time, 'settleTime')} data-lab="Settles">${esc(closeWords(p.market_close_time, 'settleTime'))}</td></tr>`).join('')}</tbody></table>`
        : '<p class="hint">No open positions.</p>');
    };
    await loadBoard();
    closeClock();  // each open position's Settles flips to "Closed, result pending" at its close, between polls
    poll(loadBoard, 10000, 'dep-stale');
  }

  // ---------- track record ----------
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
        : first ? (S.dashNoSessions ? '<a class="btn" href="/research?new=1">New session</a>' : '<a class="btn" href="/strategies?status=passed">See passed strategies</a>')
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
      ${fig('Return', pct(m.return), { v: m.return == null ? null : halfUp(m.return, 3), small: `on ${usd(m.capital)} capital required${trOver(m)}${m.annualized_return != null ? `${SEP}${pct(m.annualized_return)} a year` : ''}` })}
      ${fig('Max drawdown', m.max_drawdown ? usd(-m.max_drawdown) : usd(0), { small: m.max_drawdown_pct != null ? `${pct(m.max_drawdown_pct, false)} of capital` : '' })}
      ${fig('Sharpe', trFix(m.sharpe), { small: m.sharpe == null ? `shown after ${th.min_sharpe_days} days` : `PSR ${pct(m.psr, false)}${SEP}Sortino ${trFix(m.sortino)}` })}
      ${fig('Win rate', pct(m.win_rate, false), { small: trCi(m.win_rate_ci, (v) => pct(v, false)) })}
      ${fig('Trades', num(m.trades), { small: `${num(m.wins)} won${SEP}${num(m.losses)} lost` })}
      ${fig('Avg trade', usd(m.avg_trade, true), { v: m.avg_trade == null ? null : halfUp(m.avg_trade), small: trCi(m.avg_trade_ci, (v) => usd(v, true)) })}
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
      <section class="section"><div class="section-head"><h2>By strategy</h2><p>Removed ones included${SEP}“Too few” means under ${num(th.min_trades)} trades</p></div>
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
        host.innerHTML = loadFail(errText(e), 'Your track record');
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
  // In app.meridian-funds.js, fetched on first use (page files, at the end of this file).
  function viewFunds() { return pageView('funds', 'viewFunds', '/funds', []); }

  // ---------- community ----------
  // In page-community.js (one for both themes), fetched on first use (page files, at the end of this file).
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
  const mktLabel = (m) => { const t = comboTitle((m.ti || '').trim()), s = (m.su || '').trim(); return s && !t.toLowerCase().includes(s.toLowerCase()) ? (t ? `${t}${SEP}${s}` : s) : (t || contractName(m.t)); };
  // Explore, its list and one market's page, is in page-explore.js (one for both themes), fetched on first use (page
  // files, at the end of this file). The close clock below stays here: positions and the hot rail use it too.
  function viewExplore() { return pageView('explore', 'viewExplore', '/explore', []); }
  // The market page's clock: every 5s it rewrites each close on the page and the hot rail. Explore's rows and the
  // rail work theirs out afresh on each of their polls.
  function closeClock() {
    if (S.closeClock === S.gen) return;
    const gen = S.closeClock = S.gen;
    S.timers.push(setInterval(() => {
      if (gen !== S.gen || document.hidden) return;
      [root, document.getElementById('hotrail')].filter(Boolean).flatMap((box) => [...box.querySelectorAll('[data-close]')]).forEach((el) => {
        const t = closeWords(el.getAttribute('data-close'), el.getAttribute('data-form'), el.getAttribute('data-skew'), el.getAttribute('data-cap'));
        if (el.textContent !== t) el.textContent = t;
      });
    }, 5000));
  }

  // Hot Markets left rail: persistent (open/closed survives page switches), refreshes every 30s while it shows.
  // A rail whose reads fail keeps its rows, and once they are two reads old it says how old ("Last updated 1m
  // ago, retrying"), where it kept them with no word.
  const HOT_POLL_MS = 30000;
  const hotStaleText = () => (S.hot && S.hotFail && S.hotAt && Date.now() - S.hotAt > staleAfter(HOT_POLL_MS) ? staleText(S.hotAt) : '');
  const hotOpen = () => {
    const saved = localStorage.getItem('tau_hotrail');
    return saved === '1';
  };
  const hotShown = () => hotOpen();  // closed, app.meridian.css hides the rail at every width
  let hotLoop = false;
  let apLoop = false, apReq = null;

  // ---------- floating autopilot window ----------
  const apExpanded = () => localStorage.getItem('tau_ap_open') === '1';
  // A status read under half the poll's interval ago: the poll's tick has nothing new to ask.
  const apFresh = () => !!S.apAt && !S.apFailing && Date.now() - S.apAt < 10000;
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
      // A page that mounts the panel reads a status over 18s old, just before this tick was due: the tick then
      // skips (apFresh), where it read the status again a second or two later.
      setInterval(() => { if (document.getElementById('autopilot-float') && !document.hidden && !apFresh()) tick(); }, 20000);
      wakers.add(() => { if (document.getElementById('autopilot-float') && !document.hidden) tick(true); });
      document.addEventListener('visibilitychange', () => {
        const b = document.getElementById('autopilot-float');
        if (b && !document.hidden && (!S.apAt || Date.now() - S.apAt > 18000)) refreshAutopilot(b, true);
      });
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
    catch (e) {
      S.apFailing = true; apPaintStale();
      if (!S.ap) paintDashAp();  // the dashboard card, on with no status yet, says it didn't load
      // Never read: an open panel says the status didn't load (apUpdate), and its Try again is given back.
      if (!S.ap && box && apExpanded()) renderAutopilot(box, null);
      return false;
    }  // best-effort: never block the app
    return true;
  }
  // The autopilot's figures (the panel's and the dashboard card's) say how old they are once its
  // status read has been failing for about two polls; the next good read clears it.
  const apStale = () => S.apFailing && S.apAt && Date.now() - S.apAt > staleAfter(20000) ? staleText(S.apAt) : '';
  function apPaintStale() {
    const text = apStale();
    ['apf-stale', 'dash-ap-stale'].forEach((id) => { const el = document.getElementById(id); if (el) el.textContent = text; });
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
  // The strip's Autopilot row when it made no moves: just the switch, which syncApCopy keeps current.
  // Its newest move being the switch itself (the status read's last_action) means it was switched on and
  // has made no move yet: "On. It made no changes." read as a dud the moment the switch was pressed.
  const sinceApWord = (on) => {
    if (!on) return 'Off.';
    const la = S.ap && S.ap.autopilot ? S.ap.last_action : null;
    return la && la.at && apMoveText(la) === 'Autopilot switched on'
      ? `Switched on ${sinceMin(la.at)}. Its moves show up here as it makes them.` : 'On. It made no changes.';
  };
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
        ? `<span class="nobr"><b>${label}</b> <span class="${b.pnl < 0 ? 'neg' : b.pnl > 0 ? 'pos' : ''}">${usd(b.pnl, true)}</span></span> on ${plural(b.trades, 'trade', 'trades')}${sinceNote(m)}`
        : `<b>${label}</b>: no trades closed yet`}</span>`;
    }).join('<span class="sep">·</span>') + sinceSlip(s.books) + sinceSplit(d, books) : 'No trades closed.';
    const pass = s.passed || { n: 0, items: [] }, runs = s.runs || {};
    const started = Object.values(runs).reduce((a, n) => a + n, 0), failed = runs.failed || 0;
    // A strategy that passed its paper forward test or became ready for live did so days after it was
    // created, so `passed` never lists it: the server reads those from the bell (`milestones`, strategy
    // ids). Each is named by its own title (the server's `names`, from its strategy row, cut at its first
    // " — " as the autopilot panel cuts one), else by its deployment's here: one with no deployment listed
    // read "Strategy 10", an internal id. One with no title left (deleted) is "a strategy", with no link.
    const ms = s.milestones || {}, names = s.names || {}, named = (sid, i) => {
      const dep = d.deployments.find((x) => +x.strategy_id === +sid), title = names[sid] || (dep && dep.title);
      return title ? `<a href="/strategies/${encodeURIComponent(sid)}">${esc(title)}</a>` : i ? 'a strategy' : 'A strategy';
    };
    const fwd = (ms.passed || []).slice(0, 3).map(named);
    const fwdText = `${sinceLinks(fwd)} passed ${fwd.length === 1 ? 'its' : 'their'} paper forward test: ${fwd.length === 1 ? 'a candidate' : 'candidates'} for live`;
    // A pass a later check left uncleared (the server's not_cleared: its one-time holdout then failed, or
    // the diversification check held it back) is named apart, as its page and the lists stamp it: the
    // strip counted it among "2 strategies passed".
    // Past the passes the server judges (`more`), each count is at least that many: "500+", never a wrong exact one.
    const atLeast = pass.more ? '+' : '';
    const fell = pass.not_cleared || [], NOT_CLEARED = { missed_final: 'missed the final test', held_back: 'held back' };
    const fellText = fell.length ? ` Not cleared to trade: ${fell.map((x) => `<a href="/strategies/${encodeURIComponent(x.id)}">${esc(x.title)}</a> (${NOT_CLEARED[x.verdict] || 'held back'})`).join(', ')}${pass.not_cleared_n > fell.length ? `, ${num(pass.not_cleared_n - fell.length)}${atLeast} more` : ''}.` : '';
    // A brand-new account has nothing of its own to report yet: point at the finished example, up top.
    const found = s.own_sessions === false && !pass.n && !fwd.length ? `No sessions of your own yet. <a href="/example" data-example>See an example session first</a>` : ((pass.n
      ? `${num(pass.n)}${atLeast} ${pass.n === 1 && !atLeast ? 'strategy' : 'strategies'} passed: ${sinceLinks([...pass.items.map((x) => `<a href="/strategies/${encodeURIComponent(x.id)}">${esc(x.title)}</a>`), ...(pass.n > pass.items.length || atLeast ? [`<a href="/strategies">${num(pass.n - pass.items.length)}${atLeast} more</a>`] : [])])}`
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
    // While the server's live switch is closed a live-ready strategy stays on paper and a promote is refused: the
    // strip said "is ready for live trading. Going live is your call." beside a bell that said it waits (walk 2026-10-31).
    const needs = (ms.live_ready || []).slice(0, 3).map((sid) => liveOpen() ? `${named(sid)} is ready for live trading. Going live is your call.`
      : `${named(sid)} cleared every paper-to-live check. Live trading isn\u2019t open yet, so it stays on paper and nothing trades real money.`);
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
    // At Billing's pace (the server's pace_days: the days the week's spend covers, the account's age up to 7, and a
    // first day's spend counted as one day's, as the panel's warning counts it), to a tenth of a day as theirs is:
    // over 7 days, a two-day-old account's pause read days later here than on Billing and the autopilot panel.
    const pace = spent && spent.pace_days != null ? Math.max(1, Math.min(7, +spent.pace_days)) : 7;
    const runway = wk > 0 && left > 0 ? Math.round(left / (wk / pace) * 10) / 10 : null;
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
    const cost = spent ? `${+spent.since >= 0.01 ? `<b>${usd(spent.since)}</b> of credits spent` : spent.since_under_cent ? '<b>Under $0.01</b> of credits spent' : 'No credits spent'}${bought}<span class="since-sub">${paid ? SEP + paid : ''}${SEP}${usd(me.credit_balance || 0)} left${SEP}<a href="/billing">Billing</a></span>` : '';
    const row = (k, v, cls) => `<div class="since-row${cls ? ' ' + cls : ''}"><dt>${k}</dt><dd>${v}</dd></div>`;
    // The Money row leads with its window, as every paper figure on the dashboard does (PNL_WINDOW): beside the
    // autopilot card's "Since you started", its figures read as the same paper P&L.
    const win = s.first ? 'day' : 'visit';
    return `<section class="since" id="dash-since" aria-label="${PNL_WINDOW[win]}">
      <h2 class="since-h">${s.first ? PNL_WINDOW.day : `${PNL_WINDOW.visit} <span class="since-at">${esc(when(s.at))}</span>`}</h2>
      <dl class="since-list">${row('Money', `${pnlWin(win)} ${money}`)}${cost ? row('Cost', cost) : ''}${row('New results', found)}${row('Autopilot', auto)}${row('Needs you', needs.length ? needs.join('<br>') : 'Nothing.', needs.length ? 'needs' : '')}</dl></section>`;
  }
  // The reconciler found live positions Tau's book and Kalshi disagree on. Tau has no portfolio page:
  // name the contracts and point at the two lists to compare, Tau's open positions and Kalshi's own.
  function reconWarn(rows) {
    const ticks = [...new Set(rows.map((r) => r.ticker))];
    const named = ticks.slice(0, 3).map(esc).join(', ') + (ticks.length > 3 ? ` and ${ticks.length - 3} more` : '');
    return `\u26a0 <span>${rows.length} live position${rows.length === 1 ? '' : 's'} disagree${rows.length === 1 ? 's' : ''} with Kalshi (${named}). Compare <a href="#dash-open">Tau\u2019s open positions</a> with the positions in your Kalshi account.</span>`;
  }
  // What demo is, for a reader who has never used it: real exchange fills, pretend money.
  const DEMO_WHAT = 'real fills on Kalshi’s sandbox, not real money';
  // Deploy's demo realized sums every closed trade of the demo deployments listed, as their rows, the strategy page
  // and the track record do; the dashboard's and Funds' demo book counts from the last reload. Beside a
  // dashboard reading "+$1.24 realized since reload" it read +$1.00 and didn't say why the two differ.
  const DEMO_RELOAD_KEPT = '\u00a0· a demo reload doesn’t reset it, so it can differ from the demo book’s P&amp;L since reload';
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
  // A book or deployment with no closed trade has no realized P&L yet: the first paper deployment's Overview read
  // "Realized P&L, all time $0.00", "Realized today $0.00" and "Open at cost + fees $0.00", and its Deploy row "$0.00"
  // under Deploy's own "Realized: None yet". Until a trade closes each says so; nothing open says "None open".
  const hasClosed = (b) => !!(+b.closed_trades || +b.realized_pnl);
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
  // A poll repaints the autopilot card (every 15 seconds) and its panel's figures and week (each status read) whole. The
  // week's "How these are counted" stays as the reader left it, open or shut, and focus stays on the control it was on
  // (that summary, a term's info button, the card's button): the disclosure shut, and focus fell back to the page,
  // under a keyboard or screen-reader user. Unchanged markup isn't written again. `html(open)` draws the block with the
  // disclosure open or shut.
  const repainted = new WeakMap();
  function repaintKeep(host, html) {
    const how = host.querySelector('.ap-week-how'), out = html(!!(how && how.open));
    if (repainted.get(host) === out) return;
    const a = document.activeElement, mine = a && a !== host && host.contains && host.contains(a) ? a : null;
    const ds = (mine && mine.dataset) || {};
    const sel = !mine ? '' : how && mine === how.querySelector('summary') ? '.ap-week-how summary'
      : ds.glo ? `[data-glo="${ds.glo}"]` : ds.apcard ? `[data-apcard="${ds.apcard}"]` : '';
    const nth = sel ? [...host.querySelectorAll(sel)].indexOf(mine) : -1;
    repainted.set(host, out);
    host.innerHTML = out;
    const back = nth >= 0 && [...host.querySelectorAll(sel)][nth];
    if (back && back.focus) back.focus({ preventScroll: true });
  }
  // The card itself sits in a block a poll rewrites whole when anything in it moved (Tau's board, Meridian's #main).
  // `write` rewrites that block; the same card is then put back in its new place, with what the reader had open in it
  // and the focus they had there, before paintDashAp repaints it. It came back drawn afresh, shut and unfocused.
  function keepApCard(write) {
    const card = document.getElementById('dash-ap'), a = document.activeElement;
    const had = card && a && a !== card && card.contains && card.contains(a) ? a : null;
    write();
    const fresh = document.getElementById('dash-ap');
    if (!card || !fresh || fresh === card || !fresh.replaceWith) return;
    fresh.replaceWith(card);
    if (had && had.focus) had.focus({ preventScroll: true });
  }
  function apCardOn(b) {
    const waited = apTurning = waitNote(b);
    return busy(b, apTurnOn, waited).finally(() => {
      apTurning = null;
      const card = document.getElementById('dash-ap'), now = card && card.querySelector('[data-apcard="on"]');
      if (now && now !== b) { now.classList.remove('busy'); now.disabled = false; }
    });
  }
  const AP_CARD_UNREAD = 'Autopilot is on, but its latest status didn\u2019t load. Tau keeps trying.';
  function paintDashAp() {
    const host = document.getElementById('dash-ap');
    if (!S.me || !S.me.user) return;
    const d = S.ap, on = d ? d.autopilot : !!S.me.user.autopilot;
    syncApCopy(on);
    if (!host) return;
    if (!on) {
      // With live trading closed (liveOpen) nothing can turn real money on: "until you turn it on separately" read as if one could.
      host.className = 'apcard'; repainted.delete(host);
      host.innerHTML = `<div class="apcard-main"><span class="apcard-kick"><span class="apf-dot" aria-hidden="true"></span>Autopilot off</span>
        <h2>Let the autopilot trade for you</h2>
        <p>It picks markets, tests ideas on data it never saw, and runs the ones that pass on paper money. Every move shows up in its activity feed. ${liveOpen() ? 'Real money stays off until you turn it on separately.' : 'Real money stays off: live trading isn\u2019t open yet.'}</p>${apCostLine()}${d && Array.isArray(d.focus) ? `<p class="ap-focus">${apFocusLine(d.focus, 'data-apcard="focus"')}</p>` : ''}</div>
        <div class="apcard-act"><button type="button" class="btn primary" data-apcard="on">Turn on autopilot</button><a class="apcard-alt" href="/research">or research by hand</a></div>
        <p class="apcard-err error-text" role="alert"></p>`;
      const b = host.querySelector('[data-apcard="on"]');
      if (apTurning) { b.classList.add('busy'); b.disabled = true; apTurning.place(b); }
      b.onclick = () => apCardOn(b);
      apBindFocus(host);
      return;
    }
    // On with no status yet: still loading (an empty card), or its read failed. That card stayed empty for good,
    // with nothing to say why or to try again (failure walk 2026-10-31); it says so now, with Try again (a read).
    if (!d) {
      host.className = 'apcard on';
      repaintKeep(host, () => S.apFailing ? `<div class="apcard-main">${notice(AP_CARD_UNREAD)}<button type="button" class="btn sm" data-apcard="again">Try again</button></div>` : '');
      const again = host.querySelector('[data-apcard="again"]');
      // Back, the card (named Autopilot) takes focus: the button went with the notice. The card itself, not its first
      // heading: that is "Last 7 days", halfway down it, and a screen reader heard that with no word of the autopilot.
      if (again) again.onclick = () => busy(again, () => refreshAutopilot(document.getElementById('autopilot-float'))).then(() => { const card = document.getElementById('dash-ap'); retried(card, card); });
      return;
    }
    const m = AP_MODE[d.mode] || AP_MODE.paper, r = d.research || {}, prog = d.paper_progress;
    // A live one while live trading is closed places no orders: counted apart, as Deploy counts it.
    const liveIdle = liveOpen() ? 0 : +d.live_running || 0;
    // Its realized figure is the live book's while a live strategy places orders, or while one settled a trade today
    // (today_live_pnl). Live trading closed with nothing live realized today, the only live strategy waits: "Live
    // realized today (UTC) $0.00" read as live money at work, so it shows the paper book, as with no live strategy.
    // One book either way, never the two summed.
    const liveFig = !!d.live_running && (liveOpen() || !!+d.today_live_pnl);
    // Each book by name, as the panel's Running figure says it: "Strategies running 2" didn't say which money they trade.
    const running = [[(+d.live_running || 0) - liveIdle, 'live'], [+d.demo_running || 0, 'demo'], [+d.paper_running || 0, 'paper']]
      .filter(([n]) => n > 0).map(([n, book]) => `${num(n)}\u00a0${book}`).join(SEP);
    // Realized, as the paper portfolio, the Closed P&L chart, the track record, Deploy and the strategy
    // page count it. The equity change (total_pnl) took off open positions' entry fees and dropped every
    // trade before a reset, so "All-time P&L +$5.19" sat beside "Closed P&L +$5.61" for one book.
    const pnl = S.dashPaper ? S.dashPaper.realized_pnl : null;
    // Each cell's note sits on its own line (a block <small>), with a space before it: read as text (a screen
    // reader's line, a copy, a page's text) the figure ran into it, "0 of 30 realistic paper tradesinstant-fill …".
    // A paper book that has never closed a trade has no P&L yet: "$0.00" read as a result to a new account.
    const paperNone = pnl != null && !+S.dashPaper.closed_trades && !+pnl;
    const cells = [
      liveFig ? ['Live realized today (UTC)', `${money(d.today_live_pnl || 0)} <small>real money, after Kalshi fees</small>`] : [`${pnlWin('all')} ${gl('paper P&amp;L, realized', 'realized')}`, pnl == null ? '—' : paperNone ? 'None yet <small>no paper trade has closed</small>' : `${money(pnl)} <small>${PAPER_NET}</small>${slipEstGl(S.dashPaper.slippage_estimate)}`],
      // With strategies paused (the dashboard's deployments, S.dashPaused) it says so: "None yet" read as nothing ever
      // having run beside the header's "2 paused, needs you" (walk 2026-10-31).
      ['Strategies running', `${running || (S.dashPaused ? `None${SEP}${num(S.dashPaused)} paused` : 'None yet')}${liveIdle ? ` <small>${liveIdleCount(liveIdle)}</small>` : ''}`],
      d.week ? null : ['Ideas, last 7 days', `${Number(r.tested_7d || 0).toLocaleString('en-US')} tested${SEP}${r.passed_7d || 0} passed${+r.not_cleared_7d ? `, ${num(r.not_cleared_7d)} not cleared` : ''}`],
      prog ? ['Furthest on paper', `<a href="/strategies/${Number(prog.strategy_id)}" title="${esc(prog.title || 'Paper strategy')}">${paperCount(prog)}</a> <small>${gl(PAPER_COUNT_WHY, 'instantfill')}</small>`]
        : ['Last check-in', d.reviewing ? 'Reviewing now' : d.last_review_at ? sinceMin(d.last_review_at) + apEvery(d) : 'Starting up'],
    ].filter(Boolean);
    const now = d.billing_blocked
      ? (d.billing_reason === 'card' ? 'Paused: <a href="/billing">add a payment method</a> so it can keep researching.' + apStillTrading(d)
        : apReloadFailed(d) ? `Paused: ${AP_CARD_FIX}${apStillTrading(d)}`
        : `Paused: ${apFloorText()} <a href="/billing">Add credits</a> and it picks up on its own.${apStillTrading(d)}`)
      : d.idle ? apIdleHtml(d.idle, 'data-apcard="idle-focus"', d) + apMeanwhile(d) : esc(apStory(d)[0] || 'Autopilot is on.');
    host.className = 'apcard on' + (m.cls ? ' ' + m.cls : '') + (d.billing_blocked ? ' warn' : '');
    repaintKeep(host, (open) => `<div class="apcard-main"><span class="apcard-kick"><span class="apf-dot" aria-hidden="true"></span>${esc(m.label)}</span>
        <p class="apcard-now">${now}</p>${apLastHtml(d.last_action)}${Array.isArray(d.focus) ? `
        <p class="ap-focus">${apFocusLine(d.focus, 'data-apcard="focus"')}</p>` : ''}
        <dl class="apcard-figs">${cells.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl><p class="stale-note" id="dash-ap-stale" role="status">${apStale()}</p>${apWeek(d.week, d, open)}</div>
      <div class="apcard-act"><button type="button" class="btn" data-apcard="open">Open autopilot</button></div>`);
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
  function apMarketName(n) {
    const s = String(n || '');
    const m = ((S.me && S.me.markets) || []).find((x) => x.key === s || x.label === s || (x.series && x.series.toUpperCase() === s.toUpperCase()));
    if (m) return marketFull(m.key);
    if (MKT_SHORT[s]) return MKT_SHORT[s];
    // A label has a space or mixed case ("Chicago high temp"); a key is one case, no spaces.
    if (!/^[\w.-]+$/.test(s) || (s !== s.toLowerCase() && s !== s.toUpperCase())) return s;
    return contractMarket(s) || 'an unlisted market';
  }
  // The sessions researching now: the status's research.active less those still queued to start (research.queued).
  // "Researching Ethereum · Bitcoin" named a session waiting for a free worker beside the two running (walk 2026-10-31).
  const apResearching = (d) => {
    const r = (d && d.research) || {}, q = [...(r.queued || [])];
    return (r.active || []).filter((n) => { const i = q.indexOf(n); if (i < 0) return true; q.splice(i, 1); return false; });
  };
  const apQueued = (d) => ((d && d.research && d.research.queued) || []).length;
  const apMarketNames = (d) => [...new Set(apResearching(d).map((n) => n === AP_PICKING ? n : apMarketName(n)))];
  function apMeanwhile(d) {
    if (!d || !d.idle || !AP_IDLE_PAPER.has(d.idle.code)) return '';
    const all = apMarketNames(d), names = all.filter((n) => n !== AP_PICKING);
    if (!all.length && apQueued(d)) return ` Meanwhile ${apQueued(d) === 1 ? 'a research session is' : `${apQueued(d)} research sessions are`} queued to start.`;
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
  // Why autopilot isn't trading right now (the server's d.idle): one plain line, plus the action to
  // take when there is one (a link, or the focus control). The card and the panel both lead with it.
  // A strategy cleared for paper waits for the next review ("to_deploy"): the line says how often those come.
  function apIdleHtml(idle, focusAttr, d = S.ap) {
    const a = idle.action;
    const act = !a ? '' : a.href ? actionLink(idle)
      : a.do === 'focus' ? ` <button type="button" ${focusAttr}>${esc(a.label)}</button>` : '';
    const when = idle.code === 'to_deploy' ? apCadence(d) : '';
    return esc(idle.line) + (when ? ` <span class="ap-when">Check-ins: ${when}.</span>` : '') + act;
  }
  function apCadence(d = S.ap) {
    if (!d || !d.autopilot || d.billing_blocked || !(+d.checkin_every_min > 0)) return '';
    if (d.reviewing) return 'one is under way now';
    if (d.review_wait && d.review_wait.state === 'queued') return 'one is queued for a free worker';
    const ago = d.last_review_at && !d.review_wait ? apAgo(d.last_review_at) : '';
    return `usually every ${num(+d.checkin_every_min)} min${ago ? `; last one ${ago}` : ''}`;
  }
  function apWhen() { const c = apCadence(); return c ? ` (${c})` : ''; }
  function apWhenSpan() { return `<span data-ap-when>${apWhen()}</span>`; }
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
  function apWeek(w, d, open = false) {
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
    if (empty) return `<section class="ap-week ap-week-empty" aria-label="Autopilot, last 7 days"><p class="ap-week-none"><b>${PNL_WINDOW.week}:</b> ${researching
      ? 'a research session is running and none has finished yet. What it tests, puts on paper and spends shows here as it goes.'
      : 'nothing yet. Its research, paper strategies and credits spent show here once it starts.'}</p>${d && (d.billing_blocked || d.reload_failed) ? apCreditsLeft(w, d) : ''}</section>`;
    // Its note on what each row counts is folded under "How these are counted": shown whole, it read as a dense
    // paragraph under the figures to a new account. Its words are unchanged inside.
    return `<section class="ap-week" aria-label="Autopilot, last 7 days"><h3>${PNL_WINDOW.week}</h3><dl>
      <div><dt>Credits spent on research</dt><dd>${apWeekSpent(w, spend, checkins)}</dd></div>
      <div><dt>Ideas</dt><dd>${Number(w.tested || 0).toLocaleString('en-US')} tested${SEP}${Number(w.passed || 0).toLocaleString('en-US')} passed${+w.not_cleared ? `, ${num(w.not_cleared)} not cleared` : ''}</dd></div>
      <div><dt>Autopilot put on paper</dt><dd>${Number(w.paper_started || 0)} strateg${+w.paper_started === 1 ? 'y' : 'ies'} <small>not counting yours</small></dd></div>
      <div><dt>${pnlWin('week')} autopilot’s paper P&amp;L</dt><dd>${!trades && !pnl ? 'None yet <small>none of its paper trades has closed</small>' : `<span class="${pnl < 0 ? 'neg' : pnl > 0 ? 'pos' : ''}">${usd(pnl, true)}</span> <small>paper, not real money, ${PAPER_NET}${SEP}${num(trades)} closed trade${trades === 1 ? '' : 's'}</small>${slipEstGl(w.paper_slippage_estimate)}`}</dd></div>
    </dl>${apCreditsLeft(w, d)}<details class="ap-week-how"${open ? ' open' : ''}><summary>How these are counted</summary><p class="ap-week-note">Research counts every session, yours and the autopilot’s. The two paper rows count only what the autopilot put on paper itself; strategies you deploy yourself count in the running total and on the Deploy page, not here.</p></details></section>`;
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
    return n ? ` ${n === 1 ? 'The strategy already running keeps' : `The ${num(n)} strategies already running keep`} trading.` : '';
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
    const at = w.pace_days != null && w.pace_days < 7 ? 'its pace so far' : 'the last 7 days’ pace';
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
    S.apAutoOpen = null;  // opened by the reader: it stays open from page to page
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
  // A deployment's Unrealized sums its open positions' marks, so it is as old as the oldest of them. Each deployment
  // gets that mark's time (oldest_mark_ts) from the open positions the answer already carries, for its row to dim the
  // figure and say how old once that mark is (markFig, markedAt). Display only: no figure changes.
  function withMarkAge(d) {
    const oldest = {};
    for (const p of d.open_positions || []) {
      const ms = Date.parse(p.mark_ts || '');
      if (p.unrealized != null && p.deployment_id != null && Number.isFinite(ms) && !(Date.parse(oldest[p.deployment_id]) <= ms)) oldest[p.deployment_id] = p.mark_ts;
    }
    return { ...d, deployments: (d.deployments || []).map((x) => (oldest[x.id] ? { ...x, oldest_mark_ts: oldest[x.id] } : x)) };
  }
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
      : `<div class="empty"><h3>Nothing deployed yet</h3><p>Turn on autopilot above and the strategies that pass every research test on data they never saw land here on their own, on paper first. Or research an idea yourself.</p><a class="btn" href="/research?new=1">Research an idea</a></div>`;
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
    if (document.body) document.body.querySelectorAll('[data-ap-when]').forEach((n) => { const t = apWhen(); if (n.textContent !== t) n.textContent = t; });
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
    // The open panel's file first (page-autopilot.js), so its Model and markets is there to open below.
    if (!phone()) { await pageLoad('autopilot').catch(() => {}); apOpen(); S.apAutoOpen = location.pathname; }  // on a phone the open panel fills the screen; the card already says it's on
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
  // The open panel (its controls, the activity feed and the chat) is in page-autopilot.js,
  // fetched the first time it opens (page files, at the end of this file): every page draws the pill,
  // few open it. Until the file has run, the panel shows its head over a skeleton, and the pill's next
  // render builds it. A file that doesn't arrive says so in the panel, with Try again.
  function apBuildShell(box) {
    if (PAGES.autopilot) return PAGES.autopilot.apBuildShell(box);
    if (box.dataset.shell === 'loading') return;
    const m = (S.ap && AP_MODE[S.ap.mode]) || AP_MODE.off;
    box.dataset.shell = 'loading'; box.apPill = '';
    box.className = 'apf open' + (m.cls ? ' ' + m.cls : '');
    box.setAttribute('role', 'region'); box.setAttribute('aria-label', 'Autopilot panel');
    box.innerHTML = `<div class="apf-head"><b id="apf-label">${esc(m.label)}</b>
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
  // On a phone the open panel is a full-screen sheet (app.meridian.css: `.apf.open { inset: 0 }` under 601px). Tab
  // stays inside it (page-autopilot.js), but a screen reader's swipe walked on past its last control into the
  // page hidden under it. While the sheet is up, everything beside it is inert: each sibling on the way up from the
  // panel (in the masthead) to <body>, so the rest of the masthead, the page and the rail, except the live regions
  // announce() speaks through. Closing it (its X, Esc, the pill, a page change) or widening the window past a sheet
  // hands the page back. A panel beside the page (desktop) leaves the page alone.
  function apInertPage() {
    const box = document.getElementById('autopilot-float'), body = document.body;
    const sheet = !!(box && box.isConnected && apExpanded() && window.matchMedia && window.matchMedia('(max-width: 600px)').matches);
    const want = new Set();
    if (sheet) for (let el = box; el.parentElement && el !== body; el = el.parentElement) {
      for (const sib of [...el.parentElement.children]) if (sib !== el && !sib.hasAttribute('aria-live')) want.add(sib);
    }
    // Only what this put there comes off: an element inert for its own reasons stays inert.
    for (const el of [...body.querySelectorAll('[data-ap-inert]')]) if (!want.has(el)) { el.removeAttribute('inert'); el.removeAttribute('data-ap-inert'); }
    want.forEach((el) => { if (!el.hasAttribute('inert')) { el.setAttribute('inert', ''); el.setAttribute('data-ap-inert', ''); } });
  }
  addEventListener('resize', apInertPage);
  function renderAutopilot(box, d) {
    apInertPage();
    if (!apExpanded()) {
      apStopChat();
      // Before the first status read lands (or if it fails), go by the saved switch: an autopilot
      // user's pill read "Autopilot off" on every page load until then.
      const m = d ? (AP_MODE[d.mode] || AP_MODE.off) : (S.me && S.me.user && S.me.user.autopilot ? AP_PENDING_ON : AP_MODE.off);
      box.className = 'apf' + (m.cls ? ' ' + m.cls : '');
      box.dataset.shell = '';
      const tip = d && d.autopilot ? (apStory(d)[0] || '') : '';
      const pill = `<button type="button" class="apf-pill" data-ap="toggle" aria-expanded="false" title="${esc(tip || 'Autonomous research and deployment. Existing strategies run independently.')}">
        <span class="apf-pill-label">${esc(apPillLabel(d, m))}</span>${ICON.chev || ''}</button>`;
      // The 20s status read repaints the pill only when it changed (a screen reader re-read a focused pill
      // each time), and a repaint or the panel closing leaves focus on the pill.
      if (box.apPill === pill && box.querySelector('.apf-pill')) return;
      box.apPill = pill;
      if (box.removeAttribute) { box.removeAttribute('role'); box.removeAttribute('aria-label'); }
      const a = document.activeElement, hadFocus = !!(a && a !== document.body && box.contains && box.contains(a));
      box.innerHTML = pill;
      const pb = box.querySelector('.apf-pill');
      if (hadFocus && pb && pb.focus) pb.focus({ preventScroll: true });
      box.querySelector('[data-ap]').onclick = (e) => apAction(box, 'toggle', e);
      return;
    }
    if (box.dataset.shell !== 'expanded') apBuildShell(box);
    apUpdate(box, d);
  }
  // Why live autopilot can't be enabled yet (ordered), or '' when all gates pass.
  function apLiveBlock(d) {
    if (!d) return '';
    if (!d.autopilot) return 'Live autopilot can only be turned on after autopilot (paper) is on. It moves a strategy to real money only after the strategy has proven itself on paper, and autopilot is what runs it there. ';
    if (!d.live_enabled) return 'Live trading isn’t open yet. ';  // no live button then, just this line
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
      S.apAutoOpen = null;
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
    if (!h || h.length < 2) return '';
    const W = 104, H = 30, p = 3, lo = Math.min(...h), hi = Math.max(...h), rng = hi - lo || 1;
    const pts = h.map((v, i) => `${(i / (h.length - 1) * (W - p * 2) + p).toFixed(1)},${(H - p - (v - lo) / rng * (H - p * 2)).toFixed(1)}`);
    return `<svg class="hot-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true"><polyline points="${pts.join(' ')}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }
  // A condition too wide for the rail's ~80px name column beside the volume takes a row of its own (.hot-cond-wide):
  // a 15-minute window's "Target Price: $113,512.08", and a range bucket's "$113,000 to 113,499.99", which was cut to
  // "$113,000 to 1…", so the rail's buckets of one ladder read alike with their tops gone.
  const condWide = (su) => TARGET_IN.test(su) || /\$\s*[\d,]+(?:\.\d+)?\s+to\s+\$?\s*[\d,]+/i.test(su);
  function hotRowHtml(m) {
    const compactName = contractShort(m.t) || comboTitle((m.ti || '').trim()) || contractName(m.t);
    const when = (m.ct ? `${SEP}${esc(closeWords(m.ct, 'chip', 0, true))}` : '') + (rowVs(m) ? `${SEP}${vsLab(m)} ${vsText(rowVs(m), m)}` : '');
    const mid = midOf(m), h = m.h || [], delta = h.length >= 2 ? h[h.length - 1] - h[0] : 0;
    const dCents = Math.round(delta * 100), dir = dCents > 0 ? 'pos' : dCents < 0 ? 'neg' : '';
    // A row opens the market's own page in Tau, as Explore's rows do: it opened Kalshi in a new tab, away from the
    // countdown, the spot section and the reader's positions there.
    return `<a class="hot-row" href="${marketHref(m.t)}" aria-label="${esc([mktLabel(m), contractShort(m.t)].filter(Boolean).join(SEP))}${SEP}${mid == null ? 'Quote unavailable' : cents(mid)}${dCents ? `${SEP}${dCents > 0 ? '+' : '−'}${Math.abs(dCents)}¢ across available history` : ''}${SEP}${kfmt(m.v24)} volume over 24 hours${plain(when)}">
      <span class="hot-quote"><span class="hot-title" title="${esc(mktLabel(m))}"><strong>${esc(compactName)}</strong>${m.su && m.su.trim() !== (m.ti || '').trim() ? `<span${condWide(m.su) ? ' class="hot-cond-wide"' : ''}>${glueTarget(esc(compactCondition(m.su)))}</span>` : ''}</span><span class="hot-price" title="Midpoint quote"><b class="fig">${mid == null ? '—' : cents(mid)}</b>${dCents ? `<span class="hot-delta ${dir}" title="Change across available price history">${dCents > 0 ? '+' : '−'}${Math.abs(dCents)}¢</span>` : ''}</span></span>
      <span class="hot-foot"><span class="hot-meta"><span class="hot-vol" title="24-hour volume">${kfmt(m.v24)}${SEP}24h</span></span></span>${hotWhen(m)}</a>`;
  }
  function renderHotRail() {
    const rail = document.getElementById('hotrail'); if (!rail) return;
    const open = hotOpen();
    const d = S.hot;
    const snapshotAt = d && d.at ? Date.parse(d.at) : NaN;
    const snapshotAge = Number.isFinite(snapshotAt) ? Math.max(0, (Date.now() - snapshotAt) / 1000) : null;
    rail.classList.toggle('is-stale', !!d && (snapshotAge == null || snapshotAge > 180));
    // The narrow rail says its rows are a few reads old in place of their age line, not in a line of its own.
    const stale = hotStaleText();
    const freshness = stale ? `<span class="hot-freshness is-old" id="hot-stale" role="status">${esc(stale)}</span>` : d ? `<span class="hot-freshness${snapshotAge == null || snapshotAge > 180 ? ' is-old' : ''}" title="Market snapshot time${snapshotAge > 180 ? `${SEP}More than 3 minutes old` : ''}">${snapshotAge == null ? 'Update time unavailable' : `${snapshotAge > 180 ? `Behind${SEP}updated` : 'Updated'} ${esc(sinceMin(d.at))}`}</span>` : '';
    const rows = d && d.markets && d.markets.length ? hotSpotNote(d) + d.markets.map(hotRowHtml).join('')
      : `<div class="hot-empty">${d ? 'Warming up: the hottest markets show here within a minute.' : S.hotFail ? 'Hot markets didn\u2019t load. Retrying shortly.' : loading(120)}</div>`;
    const control = root.querySelector('.market-control');
    const toggle = `<button class="hot-tab" data-hot="toggle" aria-expanded="${open}" aria-controls="hotrail" aria-label="${open ? 'Collapse hot markets' : 'Expand hot markets'}" title="Hot markets"><span class="hot-tab-label">Hot markets</span><svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="2.5" y="3.5" width="15" height="13" rx="1.5"/><path d="M7.5 4v12"/></svg></button>`;
    if (control) {
      const button = control.querySelector('[data-hot="toggle"]');
      if (button) {
        button.setAttribute('aria-expanded', String(open));
        button.setAttribute('aria-label', open ? 'Collapse hot markets' : 'Expand hot markets');
      } else control.innerHTML = toggle;
    }
    keepFocus(rail, () => { rail.innerHTML = `${control ? '' : toggle}
      <div class="hot-panel">
        <div class="hot-head"><div><span class="hot-kicker">Hot markets</span>${freshness}</div></div>
        <div class="hot-list">${rows}</div>
        <div class="hot-ft"><a href="/explore">See all markets →</a></div>
      </div>`; });
    root.querySelectorAll('[data-hot="toggle"]').forEach((b) => b.onclick = () => {
      const next = !hotOpen(); localStorage.setItem('tau_hotrail', next ? '1' : '0');
      document.body.classList.toggle('hot-open', next); renderHotRail(); hotSoon();
      if (resizePaperChart) resizePaperChart();
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
  const hotFresh = () => !!S.hotAt && !S.hotFail && Date.now() - S.hotAt < HOT_POLL_MS / 2;
  const hotSoon = () => { if (hotShown() && (!S.hot || !S.hotAt || Date.now() - S.hotAt > HOT_POLL_MS - 5000)) refreshHot(); };
  function mountHotRail() {
    if (!S.me || !S.me.user) return;
    document.body.classList.toggle('hot-open', hotOpen());
    if (!document.getElementById('hotrail')) { const a = document.createElement('aside'); a.className = 'hotrail'; a.id = 'hotrail'; a.setAttribute('aria-label', 'Hot markets'); document.body.appendChild(a); }
    renderHotRail();
    hotSoon();
    if (!hotLoop) { hotLoop = true;
      const tick = paced(() => refreshHot().then((ok) => { if (!ok) throw new Error('hot markets'); }), HOT_POLL_MS, () => { if (hotStaleText() || document.getElementById('hot-stale')) renderHotRail(); });
      // A page that mounts the rail reads a snapshot over 25s old, just before this tick was due: the tick then
      // skips, where it read the same snapshot again a few seconds later.
      setInterval(() => { if (!document.hidden && document.getElementById('hotrail') && hotShown() && !hotFresh()) tick(); }, HOT_POLL_MS);
      wakers.add(() => { if (!document.hidden && document.getElementById('hotrail') && hotShown()) tick(true); });
      // A window widened past phone width shows the rail: it reads then.
      const wide = window.matchMedia && window.matchMedia('(max-width: 760px)');
      if (wide && wide.addEventListener) wide.addEventListener('change', () => { if (document.getElementById('hotrail')) hotSoon(); }); }
  }

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
  const pausesIn = (days) => `Research pauses ${days < 1 ? 'within a day' : inDays(days)} at the last 7 days’ pace, when credits fall under ${usd(S.me && S.me.min_run_balance != null ? S.me.min_run_balance : 0)}.`;
  // What the card pays for `credits` plus the purchase fee, to the cent as the server charges it
  // (billing.topup_charge_cents: exact decimal, half up), worked in whole cents: $19 x 1.055 as a float
  // read $20.04 before the press while the card paid $20.05.
  const topupCharge = (credits, feePct) => {
    const c = Math.round(+credits * 100), bp = Math.round(+feePct * 100);  // cents; the fee in hundredths of a percent
    return Math.floor((c * (10000 + bp) + 5000) / 10000) / 100;
  };
  // In app.meridian-billing.js, fetched on first use (page files, at the end of this file).
  function viewBilling() { return pageView('billing', 'viewBilling', '/billing', []); }

  // ---------- admin ----------
  // In page-admin.js (one for both themes), fetched on first use (page files, at the end of this file).
  function viewAdmin() { return pageView('admin', 'viewAdmin', '/admin', []); }
  function viewSystem() { return pageView('admin', 'viewSystem', '/system', []); }

  // ---------- page files ----------
  // Code only some pages use ships in its own file (app.meridian-<name>.js), so a cold load downloads and
  // compiles only what its page draws: on a phone's slow network every 10KB of bundle held the first
  // figure back about 55ms. The page shell names each file's version (#tau-boot data-mer-pages,
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
    String((boot && boot.dataset && boot.dataset.merPages) || '').split(',').forEach((p) => {
      const [name, v] = p.split(':');
      if (/^[a-z]+$/.test(name || '')) out[name] = /^[0-9a-f]+$/.test(v || '') ? v : '';
    });
    return out;
  }
  // The page files both themes load (page-<name>.js, page_modules.SHARED): what this theme draws its own way in
  // them comes from shared() (theme).
  const PAGE_SHARED = ['autopilot', 'admin', 'community', 'research', 'strategies', 'explore'];
  // Without a version (an older shell) the file is still found, revalidated instead of cached for good.
  const pageSrc = (name, v = pageVersions()[name]) => '/static/' + (PAGE_SHARED.includes(name) ? 'page-' : 'app.meridian-') + name + '.js' + (v ? '?v=' + v : '');
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
    BTC_CONTRACT, closeLeft, closeWords, comboTitle, compactCondition, contractMkt, contractShort, EXPLORE_NO_FEED, EXPLORE_WAIT,
    exploreEmpty, exploreNoBtc, exploreNoFeed, exploreShowChips, hourET, kalshiUrl, keepFocus, marketSpot, midOf, MKT_GONE,
    MKT_STATUS, mktLabel, NO_MARK, rulesText, spotListNote, spotSect, strikeIn, sum4, vsHtml,
    actionLink, adminViewOn, alert0, announce, SEP, sepLine, gloSep, WJ, plain, AP_CARD_FIX, AP_FOCUS, AP_MODE, AP_PICKING, apAction, apSaid, depSaid, depWrite,
    apExpanded, apFlash, apFloorText, apFocusPaint, apFocusText, api, apIdleHtml, ApiError, apLastHtml, apLiveBlock, apLiveBlockHtml, fundsLinked,
    apMarketNames, apQueued, apNudge, apReloadFailed, apShowFocus, apStale, apStillTrading, apStory, apSwitchOn, apEvery, apWhenSpan,
    apWeek, armed, attachMention, authorLine, BEHIND, boardTitle, bookName, btCheckLine, bulkDeployable, pageLede,
    busy, cardFormFail, cashAt, cashFig, cashNow, cashRead, catOrder, cents, chartWidth, clearTimers, clock, CLOCK, CLOCK_ZONE, LOG_STAMP, closeClock, liveClose,
    clipWords, CODE_RESEARCH_ONLY, compact, contractLink, contractMarket, contractName, depIdle, kalshiRef, liveIdleCount, liveIdleShort, liveOpen, liveWaitMark, dateFmt, DEMO_BOOK, DEMO_WHAT, demoCashRead, demoHealthLine, demoKeyless, demoCapital, demoNoClose, demoPnl, FEES_NET, inBalance, openBasis, openCost, openFig, demoSpan,
    DEP_DONE, depActed, deploymentMode, dirLabel, equityChart, errText, esc, EXAMPLE_NOTE, EXAMPLE_TAG,
    exampleLine, exitWord, failText, feedMd, fig, fillLiveRow, flash, fmt0, fold, gl, glo, GLOSSARY, go, halfUp,
    holdFocus, ICON, isPerpetual, KIND_LABEL, loadFail, loading, loadStripe, logTime, mark, marketKalshiUrl,
    marketLabel, marketPicker, marketShort, markQuietRows, mdLite, MKT_SHORT, money, notice, num, olderRows, overDays,
    paced, paceDay, paceTooSoon, paceWords, pageAssets, paint, paintDashAp, painted, paintRows, paperAgain, PAPER_NET, NOT_MARKED, paperCount, paperShown, paperSince, slipEst, slipEstGl, slipTip, PAPER_COUNT_WHY, PNL_WINDOW, pnlWin, repaintKeep, retried,
    pausesIn, pct, PERPS_SCENARIO, phone, poll, realTrades, refreshAutopilot, refreshed, registry, render,
    researchBadge, researchOnly, roadDays, root, rpUnderwater, runKind, runTag, runWaitLine, runwayLabel, S,
    sessionNo, sessionTitle, settleAt, keepZone, markedAt, markFig, markOld, shell, sinceMin, smooth, statusMark, strategySlip, strategyTable,
    stripeFail, syncMeBilling, theme: 'meridian', tone, topupCharge, tradePrice, trDay, tzName, usd, waitNote, waitSpan, wakers,
    WEEKDAY_DAY, when, whyFailedHtml, wireMarketPicker
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
  async function pageView(name, view, nav, args) {
    if (!PAGES[name] || pageWaits[name]) {
      const gen = S.gen;
      shell(nav, loading(120), loading(320));
      await pageLoad(name);
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
