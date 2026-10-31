/* Explore, in both themes: every market Tau is tracking (the list at /explore, its search, sort, Bitcoin choice and
   pages, kept current while it shows) and one market's own page (/explore?m=TICKER: its price, your positions in it,
   how it settles, its price history, and Bitcoin against the strike for a Bitcoin contract). The hot-markets rail (on
   every page) and the close clock (Dashboard's positions use it too) stay in each bundle.
   Fetched on first use (pageLoad in app.js or app.meridian.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns.
   What one theme draws and the other doesn't goes by the bundle's theme (shared(): theme). */
window.TauPage('explore', (T) => {
  'use strict';
  const {
    announce, api, boardTitle, BTC_CONTRACT, cents, clock, closeClock, closeLeft, comboTitle, compactCondition, curveWords, finitePts, thinCurve,
    contractMarket, contractMkt, contractShort, errText, esc, exitWord, EXPLORE_NO_FEED, EXPLORE_WAIT, exploreEmpty,
    exploreNoBtc, exploreNoFeed, exploreShowChips, fig, hourET, ICON, kalshiRef, kalshiUrl, keepFocus, keepZone,
    liveClose, loading, markedAt, marketShort, marketSpot, markFig, markOld, midOf, MKT_GONE, MKT_STATUS, mktLabel,
    money, NO_MARK, NOT_MARKED, markedOf, notice, num, pageLede, paint, paintRows, phone, poll, retried, root, rulesText, S, SEP,
    settleAt, shell, sinceMin, smooth, spotListNote, spotSect, strikeIn, sum4, theme, tzName, usd, vsHtml, when
  } = T;
  // Each theme heads the list, sets out its figures, its rows and its sort its own way (Meridian's rows carry its
  // Context column and the Yes bid and ask), and says a market page short of history in its own words; the reads,
  // the polls, the pages, the way back and the market page are the same in both.
  const tau = theme === 'tau';

  // ---------- explore ----------
  function priceChart(points) {
    // [time, Yes price] pairs, oldest first; a point with no finite time or price is left out (finitePts).
    const pts = finitePts((points || []).map((p) => p && [p.t, p.yes])).map(([t, v]) => [+t, +v]).sort((a, b) => a[0] - b[0]);
    if (pts.length < 2) return tau ? '<div class="empty"><h3>Not enough history yet</h3><p>This market is new or thinly traded — its price curve fills in as it trades.</p></div>'
      : '<div class="empty"><h3>Not enough price history</h3></div>';
    // The SVG scales to its box, labels too: drawn 760 wide, a phone's ~320px chart shrank its 10.5px axis
    // labels to under 5px. On a phone it's drawn near the size it shows at, so the cents and times stay legible.
    const W = phone() ? 340 : 760, H = phone() ? 220 : 260, pl = 44, pr = 14, pt = 14, pb = 26, iw = W - pl - pr, ih = H - pt - pb;
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0], tr = (t1 - t0) || 1;
    const x = (t) => pl + (t - t0) / tr * iw, y = (v) => pt + (1 - v) * ih;
    const grid = [0, .25, .5, .75, 1].map((v) => `<line x1="${pl}" y1="${y(v).toFixed(1)}" x2="${W - pr}" y2="${y(v).toFixed(1)}" class="pc-grid"/><text x="${pl - 8}" y="${(y(v) + 3).toFixed(1)}" class="pc-ylab">${Math.round(v * 100)}¢</text>`).join('');
    // A stretch with no price at all (over ten times the series' usual spacing) breaks the line, with a faint dashed
    // link across it: a straight line drawn across four days without a price read as a steady climb nobody traded.
    const steps = pts.slice(1).map((p, i) => p[0] - pts[i][0]).sort((a, b) => a - b), usual = steps[steps.length >> 1] || 0;
    const segs = [[pts[0]]];
    for (let i = 1; i < pts.length; i++) {
      if (usual > 0 && pts[i][0] - pts[i - 1][0] > 10 * usual) segs.push([]);
      segs[segs.length - 1].push(pts[i]);
    }
    // A long series is drawn at about two points a pixel, each run keeping its low and high (thinCurve): ten thousand
    // minute prices drew a 114KB line.
    const xy = (p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`;
    const lines = segs.map((seg) => (seg.length > 1 ? `<polyline points="${thinCurve(seg, 2 * iw).map(xy).join(' ')}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>`
      : `<circle cx="${x(seg[0][0]).toFixed(1)}" cy="${y(seg[0][1]).toFixed(1)}" r="1.8" fill="currentColor"/>`)).join('');
    const links = segs.slice(1).map((seg, i) => { const a = segs[i][segs[i].length - 1], b = seg[0]; return `<line x1="${x(a[0]).toFixed(1)}" y1="${y(a[1]).toFixed(1)}" x2="${x(b[0]).toFixed(1)}" y2="${y(b[1]).toFixed(1)}" stroke="currentColor" stroke-opacity=".35" stroke-width="1" stroke-dasharray="3 4"/>`; }).join('');
    // A chart within one day gets clock times (a 15-minute market read "10/26 … 10/26"), one over a few
    // days the date and clock, and the right-hand label names the reader's zone, as every time on the
    // market page does. The zone is the one in force at each end: across the November clock change the last
    // time read "06:00 EDT", an hour that was EST, so the left end names its own zone when the two differ.
    const md = (t) => { const d = new Date(t * 1000); return `${d.getMonth() + 1}/${d.getDate()}`; };
    const fmt = new Date(t0 * 1000).toDateString() === new Date(t1 * 1000).toDateString() ? (t) => clock(t * 1000)
      : tr < 3 * 86400 ? (t) => `${md(t)} ${clock(t * 1000)}` : md;
    const z0 = tzName(t0 * 1000), z1 = tzName(t1 * 1000);
    const left = `${fmt(t0)}${z0 && z0 !== z1 ? ' ' + z0 : ''}`, right = `${fmt(t1)}${z1 ? ' ' + z1 : ''}`;
    // Its name says the span, the first and last price, and the low and high with when each came (curveWords), in
    // the zone of each time: it said only the span.
    const at = (t) => (tr < 3 * 86400 ? `${md(t)} ${clock(t * 1000)}${tzName(t * 1000) ? ' ' + tzName(t * 1000) : ''}` : md(t));
    const breaks = segs.length - 1;
    const name = `Yes price history, ${curveWords(pts, cents, at)}${breaks ? `; the line breaks where there was no price for a while (${num(breaks)} time${breaks === 1 ? '' : 's'})` : ''}`;
    return `<svg class="pchart" viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(name)}">${grid}${links}${lines}<text x="${pl}" y="${H - 6}" class="pc-xlab">${esc(left)}</text><text x="${W - pr}" y="${H - 6}" class="pc-xlab" text-anchor="end">${esc(right)}</text></svg>`;
  }
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
      // The sum is as old as its oldest mark: once that is old the figure is dimmed and says how old (markFig), and
      // so is each old row's figure.
      const oldest = marked.map((p) => p.mark_ts).filter((t) => Number.isFinite(Date.parse(t))).sort((a, b) => Date.parse(a) - Date.parse(b))[0];
      const part = markedOf(marked.length, op.length);  // some open marked, some not: the sum says how many it covers
      const sum = [op.length ? `${num(op.length)} open at cost + fees ${usd(op.reduce((a, p) => a + p.cost, 0))}${marked.length ? `${SEP}unrealized ${markFig(oldest, money(marked.reduce((a, p) => a + p.unrealized, 0)))}${part ? ` on ${part}` : ''} (est. at the current bid${markOld(oldest) ? ', ' + markedAt(oldest, 'marked') : lastMark ? ', marked ' + when(lastMark) : ''})${part ? `${SEP}${num(op.length - marked.length)} ${NOT_MARKED.toLowerCase()}` : ''}` : `${SEP}${NOT_MARKED.toLowerCase()}`}` : '',
        cl.length ? `${num(cl.length)} closed${SEP}realized ${money(sum4(cl.map((p) => p.pnl)))}` : ''].filter(Boolean).join(SEP);
      const rows = xs.map((p) => `<tr><td class="name" data-lab="Strategy">${p.strategy_id && p.title ? `<a href="/strategies/${+p.strategy_id}">${esc(p.title)}</a>` : esc(p.title || 'Deleted strategy')}</td><td data-lab="Position">${esc(p.side.toUpperCase())} ×${num(p.qty)} @ ${cents(+p.entry_price)}</td><td class="num" data-lab="Cost + fee">${usd(p.cost)}</td><td class="num" data-lab="${p.status === 'open' ? 'Unrealized' : 'Realized'}">${p.status === 'open' ? (p.unrealized == null ? NO_MARK : markFig(p.mark_ts, money(p.unrealized)) + (markOld(p.mark_ts) ? `<div class="sub-fig">${markedAt(p.mark_ts)}</div>` : '')) : money(+p.pnl || 0)}</td><td data-lab="Status">${p.status === 'open' ? liveClose(p.market_close_time, 'pos') : `Closed (${esc(exitWord(p.close_reason))}) @ ${cents(+p.exit_price)}`}</td></tr>`).join('');
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
    // The button is on one contract's page, so it names that contract's strike as the line under the heading does
    // ("Research BTC $113,000 or above at 5pm ET"), not the family's words; the session it starts researches the market.
    return `<p class="mk-next"><a class="btn sm primary" href="/research?new=1&amp;market=${k}">Research ${esc(strikeIn(marketShort(m.key), ticker))}</a>${own}</p>`;
  }
  function mountSpot(ticker, first, d) {
    const path = '/api/explore/spot?ticker=' + encodeURIComponent(ticker);
    const show = (s) => {
      const el = root.querySelector('#mk-spot-body');
      if (!el) return;
      // A failed read names what didn't load (it said only "Something went wrong on our side."), unless Tau's own words do.
      const why = s.failed && (/didn\u2019t load/.test(s.failed) ? s.failed : `Bitcoin\u2019s latest stored price didn\u2019t load. ${s.failed}`) + ' Everything else on this page did.';
      el.innerHTML = s.failed ? `<p class="hint">${esc(why)} <button class="btn sm" type="button" data-spot-retry>Try again</button></p>` : marketSpot(s, d);
      // One read a press (a double tap asked twice), and focus goes into what came in, or to the new Try again; the
      // repaint dropped it to the page's body (walk 2026-10-31).
      const b = el.querySelector('[data-spot-retry]');
      if (b) b.onclick = () => {
        if (b.disabled) return;
        b.disabled = true;
        return spotRead(ticker).then(show).then(() => { const box = root.querySelector('#mk-spot-body'); if (box) retried(box, box.querySelector('[data-spot-retry]')); });
      };
    };
    first.then(show);
    // One poll per page, though a retry of the market draws the page again; a failed poll keeps the last figures.
    // Those figures carry the age Tau read them at ("Coinbase · 12s ago"), which stood still while the poll
    // failed: once it has failed for about two polls, a line under them says how old they really are.
    if (S.spotPoll !== S.gen) { S.spotPoll = S.gen; poll((cfg) => api(path, undefined, cfg).then(show), 15000, 'mk-spot-stale'); }
  }
  const spotRead = (ticker) => api('/api/explore/spot?ticker=' + encodeURIComponent(ticker)).catch((e) => ({ failed: errText(e) }));
  async function viewMarketDetail(ticker) {
    shell('/explore', boardTitle('Market'), loading(300));
    const spotReq = BTC_CONTRACT.test(ticker || '') ? spotRead(ticker) : null;
    // Try again (the market, or its price history) draws the whole page again, and focus fell to the page's body: it
    // goes to the market's heading, or to the new Try again when the read failed again (walk 2026-10-31).
    const again = () => viewMarketDetail(ticker)
      .then(() => retried(root.querySelector('main'), root.querySelector('#mk-retry') || root.querySelector('main h1')));
    let d;
    try { d = await api('/api/explore/market?ticker=' + encodeURIComponent(ticker)); }
    catch (e) {
      // A market Kalshi doesn't have (404) won't come back on a retry: it says so in words, without the raw code
      // from the link ("Kalshi has no market KXNOPE-…"), and offers only the way back to Explore.
      const gone = e.status === 404;
      root.querySelector('#main').innerHTML = notice(gone ? MKT_GONE : e.message, 'bad') + `<p style="margin-top:12px">${gone ? '' : '<button class="btn sm" type="button" id="mk-retry">Try again</button> '}<a class="btn sm" href="${esc(exploreBackHref())}">← Back to Explore</a></p>`;
      if (!gone) root.querySelector('#mk-retry').onclick = again;
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
    // A contract nobody has traded and nobody quotes both sides of read only "— as of 01:36": it says so, and shows
    // the one side of the book there is.
    const quote = bid > 0 && ask > 0 ? `bid\u00a0${cents(bid)}\u00a0/ ask\u00a0${cents(ask)}` : ask > 0 ? `no bid\u00a0/ ask\u00a0${cents(ask)}` : bid > 0 ? `bid\u00a0${cents(bid)}\u00a0/ no ask` : '';
    // A price under half a cent read "≈ 0% chance of Yes" and one over 99.5¢ "≈ 100%", odds Kalshi's book doesn't give.
    const chance = (p) => { const n = Math.round(p * 100); return n < 1 ? 'under\u00a01%' : n > 99 ? 'over\u00a099%' : `≈\u00a0${n}%`; };
    const priceSub = [mid == null ? 'No trades yet' : `${chance(mid)} chance of Yes`, quote,
      d.as_of ? (d.snapshot ? `Explore snapshot, ${sinceMin(d.as_of)}` : `as\u00a0of\u00a0${keepZone(settleAt(d.as_of))}`) : ''].filter(Boolean).join(SEP);
    const settled = d.result === 'yes' || d.result === 'no';
    // The close, counting down from when Tau read the market (as_of; the feed's snapshot is older, so it counts from
    // the reader's clock); a closed or settled market's figure reads "Closed", not "Closes" at a time already past.
    const closeSkew = d.as_of && !d.snapshot ? (Date.now() - Date.parse(d.as_of)) / 1000 || 0 : 0;
    const closedNow = settled || ['closed', 'determined', 'settled', 'finalized'].includes(d.status) || (d.close_time && closeLeft(d.close_time, closeSkew) <= 0);
    const closesFig = !d.close_time ? fig('Closes', '—') : closedNow ? fig('Closed', keepZone(settleAt(d.close_time)))
      : fig(liveClose(d.close_time, 'lab', { skew: closeSkew }), keepZone(settleAt(d.close_time)), { small: liveClose(d.close_time, 'in', { skew: closeSkew }) });
    const kalshiLink = `https://kalshi.com/markets/${encodeURIComponent((d.series || '').toLowerCase())}`;
    // The line under the name says what the code is, as a position does (kalshiRef): "Kalshi contract KX…", not a bare ticker.
    // An open market's status follows the same clock as its Closes figure (closeClock), flipping to "Closed, result
    // pending" once the close passes; Kalshi's own closed and settled statuses stay as Kalshi sent them.
    const statusLine = d.close_time && (d.status === 'active' || d.status === 'open') ? liveClose(d.close_time, 'status', { skew: closeSkew })
      : esc(MKT_STATUS[d.status] || d.status || 'Market');
    // The way back sits at the top as well as the foot: on a 390px phone the foot's "Back to Explore" was about three
    // screens down. Both go to the list this tab last showed, its filter kept (exploreBackHref).
    shell('/explore', `<p class="mk-back"><a href="${esc(exploreBackHref())}">← Back to Explore</a></p>` + boardTitle(label, [esc(contractMarket(d.ticker)), statusLine].filter(Boolean).join(SEP) + (d.ticker ? SEP + kalshiRef(d.ticker) : '')) +
      '<dl class="figures measure" style="margin-top:14px">' +
        (settled ? fig('Result', d.result === 'yes' ? 'Yes' : 'No', { small: d.result === 'yes' ? 'each Yes contract paid $1' : 'each No contract paid $1' })
          : fig('Yes price', mid == null ? '—' : cents(mid), { small: priceSub })) + fig('24h volume', num(Math.round(+d.volume_24h || 0)), { small: 'contracts traded' }) +
        fig('Open interest', num(Math.round(+d.open_interest || 0)), { small: 'contracts held' }) + closesFig + '</dl>' + marketNext(d.ticker, d.my_markets), `${spotReq && !settled ? spotSect(d.ticker || ticker) : ''}
      <section class="sect"><div class="sect-head"><h2>Your positions here</h2><p>Each money book on its own</p></div>${marketMine(d)}</section>
      <section class="sect"><div class="sect-head"><h2>How it settles</h2><p>${settled ? `Settled${SEP}${d.result === 'yes' ? 'Yes' : 'No'}` : d.settles_at ? `Result expected ${settleAt(d.settles_at)}` : 'Kalshi’s rules'}</p></div>
        ${d.rules ? `<p class="mk-rules">${esc(rulesText(d.rules))}</p>${d.rules_more ? `<p class="hint mk-rules">${esc(rulesText(d.rules_more))}</p>` : ''}`
          : `<p class="hint mk-rules">Kalshi’s settlement rules didn’t come with this snapshot. <a href="${kalshiLink}" target="_blank" rel="noopener">Read them on Kalshi ↗</a></p>`}</section>
      <section class="sect"><div class="sect-head"><h2>Price history</h2><p>Yes price${d.history_unavailable ? '' : `${SEP}${GRAN_EACH[gran]}, from Kalshi`}</p></div>
        <div class="pchart-wrap">${d.history_unavailable
          ? '<div class="empty"><h3>Price history didn’t load</h3><p>Kalshi didn’t send it just now. The figures above are from the latest market snapshot.</p><button class="btn sm" type="button" id="mk-retry">Try again</button></div>'
          : priceChart(d.points)}</div></section>
      <section class="sect"><div class="sect-head"><h2>Raw data</h2><p>${d.history_unavailable ? 'Not loaded' : `${num(d.points.length)} ${gran} point${d.points.length === 1 ? '' : 's'}${d.points.length ? `${SEP}newest first` : ''}`}</p></div>
        <div id="rawsect"></div></section>
      <div class="xpage"><a class="btn sm" href="${esc(exploreBackHref())}">← Back to Explore</a>
        <span class="xpage-acts"><button class="btn sm" id="dl-csv" ${d.points.length ? '' : 'disabled'}>Download CSV</button>
        <a class="btn sm" href="${kalshiLink}" target="_blank" rel="noopener">View on Kalshi ↗</a></span></div>`);
    const retry = root.querySelector('#mk-retry');
    if (retry) retry.onclick = again;
    closeClock();
    if (spotReq && !settled) mountSpot(ticker, spotReq, d);
    const pts = d.points.slice().reverse();  // newest first
    const PER = 25; let pg = 0;
    const rawEl = root.querySelector('#rawsect');
    const renderRaw = () => {
      if (!pts.length) { rawEl.innerHTML = `<div class="empty"><p>${d.history_unavailable ? 'None to show: Kalshi didn’t send this market’s price history just now. Try again under Price history.' : 'Kalshi has no price history for this market yet.'}</p></div>`; return; }
      const pages = Math.max(1, Math.ceil(pts.length / PER));
      // Its heading named one zone ("Time (EDT)") over prices from both sides of the November clock change: across
      // one, each time says its own zone and the heading says none.
      const zones = new Set([tzName(pts[0].t * 1000), tzName(pts[pts.length - 1].t * 1000)]), each = zones.size > 1;
      const rows = pts.slice(pg * PER, (pg + 1) * PER).map((p) => `<tr><td class="tick">${fmtT(p.t)}${each ? ' ' + esc(tzName(p.t * 1000)) : ''}</td><td class="num">${cents(p.yes)}</td><td class="num">${num(Math.round(p.vol || 0))}</td></tr>`).join('');
      rawEl.innerHTML = `<div class="sheet"><table><thead><tr><th>${each ? 'Time' : `Time (${esc(tzName(pts[0].t * 1000) || 'local')})`}</th><th class="num">Yes price</th><th class="num">Volume</th></tr></thead><tbody>${rows}</tbody></table></div>
        <div class="xpage">${pg > 0 ? `<button class="btn sm" data-rp="${pg - 1}">← Prev</button>` : '<span></span>'}<span class="lab">Page ${pg + 1} of ${num(pages)}${SEP}${num(pts.length)} point${pts.length === 1 ? '' : 's'}</span>${pg + 1 < pages ? `<button class="btn sm" data-rp="${pg + 1}">Next →</button>` : '<span></span>'}</div>`;
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

  // Explore's list polls every 15s. The feed itself moves about once a minute; the 15s is for the Bitcoin rows'
  // distance to spot, which the collector stores every 20s. The server answers from its cached feed and one spot
  // read shared by every reader for 5s (about 2ms a call, never a Kalshi call), as fast as the market page's spot.
  const EXPLORE_POLL_MS = 15000;
  const exploreParams = (f) => new URLSearchParams({ q: f.q, sort: f.sort, page: String(f.page), ...(f.btc ? { show: 'bitcoin' } : {}) });
  // Where a market page's "Back to Explore" goes: the Explore list this tab last showed, with its search, sort, page and
  // Bitcoin choice. It went to /explore, which dropped them: a reader who picked Bitcoin came back to every market. Kept
  // for the tab (sessionStorage), so a reload of the market page keeps it; a tab that never showed the list gets Explore.
  const XBACK = 'tau_xback';
  let xBack = '';
  const exploreKeep = (f) => { xBack = '/explore?' + exploreParams(f); try { sessionStorage.setItem(XBACK, xBack); } catch (e) { /* private mode */ } };
  const exploreBackHref = () => {
    let h = xBack;
    if (!h) try { h = sessionStorage.getItem(XBACK) || ''; } catch (e) { /* private mode */ }
    return /^\/explore\?/.test(h) && !new URLSearchParams(h.slice(9)).has('m') ? h : '/explore';
  };
  async function viewExplore() {
    const q = new URLSearchParams(location.search);
    if (q.get('m')) return viewMarketDetail(q.get('m'));
    const f = { q: q.get('q') || '', sort: ['v24', 'oi', 'last'].includes(q.get('sort')) ? q.get('sort') : 'v24', page: Math.max(0, +(q.get('page') || 0)), btc: q.get('show') === 'bitcoin' };
    // Tau heads the list with its figures under the title and its sort as chips over the list; Meridian keeps its
    // figures in the filter row and sorts by its table's column heads.
    if (tau) shell('/explore', boardTitle('Explore', 'Every market Tau is tracking right now, across crypto, politics, sports, weather and more, hottest first. Prices refresh each minute.') +
      '<dl class="figures measure" id="xfigs" style="margin-top:14px"></dl><p class="stale-note" id="xstale" role="status"></p>', `
      <div class="section-head filters">
        <label class="field xsearch" style="margin:0"><span class="vh">Search markets</span>
          <input class="input" id="xq" type="search" placeholder="Search markets" value="${esc(f.q)}" autocomplete="off"></label>
        ${exploreShowChips(f.btc)}
        <div class="chips" role="group" aria-label="Sort by">${[['v24', 'Hottest'], ['oi', 'Open interest'], ['last', 'Price']].map(([v, l]) => `<button class="chip" data-sort="${v}" aria-pressed="${f.sort === v}">${l}</button>`).join('')}</div>
      </div>
      <div id="xbody" style="margin-top:16px">${loading(240)}</div>`);
    else shell('/explore', `<div class="board-title explore-heading"><h1 class="page">Explore</h1>${pageLede('Every market Tau is tracking right now, across crypto, politics, sports, weather and more, hottest first. Prices refresh each minute.')}
      <div class="section-head filters explore-filters">
        <label class="field xsearch" style="margin:0"><span class="vh">Search markets</span>
          <input class="input" id="xq" type="search" placeholder="Search markets" value="${esc(f.q)}" autocomplete="off"></label>
        ${exploreShowChips(f.btc)}
        <div class="figures measure" id="xfigs"></div>
      </div></div>`, `<p class="stale-note" id="xstale" role="status"></p><div id="xbody">${loading(240)}</div>`);
    const body = root.querySelector('#xbody'), figs = root.querySelector('#xfigs'), staleNote = root.querySelector('#xstale'), gen = S.gen;
    // Kalshi sends 0 for a side nobody quotes (a closed contract, or no orders on that side): a closed row read
    // "Bid 0¢ · Ask 0¢", a Yes on offer for nothing. A side at 0 reads "—" and says why, as the market page's
    // "no bid / ask 5¢" does (its Yes price, the midpoint, already skips a 0 side).
    const quoteSide = (value, none) => {
      if (typeof value !== 'number' && typeof value !== 'string') return '—';
      if (typeof value === 'string' && !value.trim()) return '—';
      if (!Number.isFinite(+value)) return '—';
      return +value > 0 ? cents(+value) : `<span title="${none}"><span aria-hidden="true">—</span><span class="vh">${none}</span></span>`;
    };
    const sync = () => { exploreKeep(f); history.replaceState(null, '', '/explore?' + exploreParams(f)); };
    exploreKeep(f);
    // "Live now" was the hottest markets the list carries, not what's live; Matching shows only when a
    // search narrows the list. The list refreshes each minute, so an older one says it's behind.
    const figsHtml = (d) => {
      if (exploreNoFeed(d)) return EXPLORE_NO_FEED;
      const atMs = Date.parse(d.at || ''), behind = Number.isFinite(atMs) && Date.now() - atMs > 180000;
      return fig('Markets tracked', num(d.total)) + fig('In this list', num(d.shown), { small: 'the most traded' }) + (f.q ? fig('Matching', num(d.matched)) : f.btc ? fig('Bitcoin markets', num(d.matched)) : '') +
        fig('Prices updated', sinceMin(d.at), behind ? { small: 'Behind: prices normally refresh each minute', cls: 'fig-behind' } : {});
    };
    // How old the prices are, as Tau says it ("Prices updated 2m ago"); past three minutes it says the list is behind.
    // The snapshot's own time is the age's hover: "6m ago" beside a raw "2026-10-28 00:12:19 UTC" said it twice.
    const paintFigs = tau ? (d) => paint(figs, figsHtml(d)) : (d) => {
      if (exploreNoFeed(d)) { paint(figs, '<dl class="explore-counts">' + EXPLORE_NO_FEED + '</dl>'); return; }
      const snapshotAt = d.at ? Date.parse(d.at) : NaN;
      const snapshotOld = !Number.isFinite(snapshotAt) || Date.now() - snapshotAt > 180000;
      paint(figs, '<dl class="explore-counts">' + fig('In this list', num(d.shown)) + (d.total !== d.shown ? fig('Tracked', num(d.total)) : '') + (f.btc && !f.q ? fig('Bitcoin markets', num(d.matched)) : f.q || d.matched !== d.shown ? fig('Matching', num(d.matched)) : '') + '</dl><dl class="explore-freshness">' + fig('Prices updated', Number.isFinite(snapshotAt) ? `<time class="snapshot-age" datetime="${esc(d.at)}" title="${esc(new Date(snapshotAt).toISOString().replace('T', ' ').replace('.000Z', ' UTC').replace('Z', ' UTC'))}">${sinceMin(d.at)}</time>${snapshotOld ? '<span class="snapshot-behind">Behind: prices normally refresh each minute</span>' : ''}` : 'Time unavailable', { cls: 'snapshot-time' + (Number.isFinite(snapshotAt) ? (snapshotOld ? ' snapshot-old' : '') : ' snapshot-unknown') }) + '</dl>');
      figs.querySelector('.snapshot-time').setAttribute('title', Number.isFinite(snapshotAt) ? 'Source snapshot: ' + d.at : 'Source snapshot time unavailable');
    };
    // The list stays current while it shows (EXPLORE_POLL_MS, paused while the tab is hidden, read at once on
    // coming back to it). A poll (`cfg`) rewrites only the rows that moved, so scroll, focus, the search box and
    // the sort stay as they are. A failed poll keeps the list up with its age counting on, and past two polls
    // the line under the figures says how old it is. Only the newest read draws: a poll answering after a
    // search doesn't put the old list back.
    let seq = 0, shown = null;
    // The list's Try again: the list drew over the button, and focus fell to the page's body. The list has no heading of
    // its own, so focus goes to the page's (Explore), or to the new Try again when the read failed again.
    const reread = () => load().then(() => retried(body, root.querySelector('main h1')));
    // `typed`: the read a search typed asked for. The list changed under the box with nothing said (the figures aren't a
    // live region: their age ticks on every poll), so that read says how many markets match, or that none do.
    const load = async (cfg, typed) => {
      const mine = ++seq;
      let d;
      try { d = await api('/api/explore?' + exploreParams(f), undefined, cfg); }
      catch (e) {
        if (mine !== seq || !tau && gen !== S.gen) return;
        if (cfg) { if (shown) paintFigs(shown); throw e; }
        // Said aloud too (failure walk 2026-10-31): the failed list was a plain heading, and a screen reader that
        // pressed Try again, or opened the page, heard nothing at all.
        // Its "Last updated 30s ago, retrying" line read over a list that never loaded: it stays hidden while the failed
        // state shows (the polls go on retrying under it) and comes back with the next good read.
        shown = null; staleNote.hidden = true; paint(body, exploreEmpty('Markets didn’t load', e.message)); body.querySelector('[data-xretry]').onclick = reread;
        announce(`Markets didn’t load. ${e.message}`, true); return;
      }
      if (mine !== seq || !tau && gen !== S.gen) return;
      staleNote.hidden = false;
      paintFigs(d);
      if (typed && f.q) announce(d.markets.length ? `${num(d.matched)} ${+d.matched === 1 ? 'market matches' : 'markets match'} “${f.q}”.` : `No markets match “${f.q}”.`);
      if (!d.markets.length) {
        // No search and no markets is the feed not having arrived yet, not a search that missed. With the feed in,
        // an empty Bitcoin list is no Bitcoin market open, and says so.
        shown = null;
        if (f.btc && !exploreNoFeed(d)) {
          paint(body, exploreNoBtc(f.q));
          const again = body.querySelector('[data-xretry]');
          if (again) again.onclick = reread;
          body.querySelector('[data-xall]').onclick = () => setShow(false);
        } else if (f.q) paint(body, `<div class="empty"><h2>No markets match “${esc(f.q)}”</h2><p>Try a broader search, or clear it to see the hottest markets.</p></div>`);
        else { paint(body, exploreEmpty('No markets to show yet', EXPLORE_WAIT)); body.querySelector('[data-xretry]').onclick = reread; }
        return;
      }
      shown = d;
      const rows = d.markets.map((m) => {
        const mid = midOf(m);
        if (tau) {
          // The market as the app names it and when the contract closes (`ct`, read from a timed event's
          // ticker), never the raw event key: that's what tells "every strike of Bitcoin at 5pm" apart from
          // the next hour's ladder, and a 15-minute contract from the one after it.
          // Each piece holds together, so the chip breaks only after its "·": at 390px "UTC" sat alone on a line.
          const short = contractShort(m.t);
          const tag = [short ? `<span class="nobr">${esc(short)}</span>` : '', m.ct ? liveClose(m.ct, 'chip', { cls: 'nobr' }) : ''].filter(Boolean).join(SEP);
          return [m.t, `<tr><td class="name"><a href="/explore?m=${encodeURIComponent(m.t)}">${esc(mktLabel(m))}</a>${tag ? ` <span class="mk quiet">${tag}</span>` : ''}${vsHtml(m)}</td>
          <td class="num" data-lab="Yes price">${mid == null ? '—' : cents(mid)}</td><td class="num" data-lab="24h volume">${num(Math.round(+m.v24 || 0))}</td><td class="num" data-lab="Open interest">${num(Math.round(+m.oi || 0))}</td>
          <td class="num xlink" data-lab="Kalshi"><a href="${kalshiUrl(m)}" target="_blank" rel="noopener" aria-label="Open on Kalshi">${ICON.ext}</a></td></tr>`];
        }
        // Meridian's row: the event and its condition, its Context column, and the Yes bid and ask.
        // A phone's stacked row labels its prices in Tau's words ("Yes price", "Yes bid", "Yes ask"): "YES Price" mixed capitals.
        const label = mktLabel(m);
        const title = comboTitle((m.ti || '').trim()), condition = (m.su || '').trim();
        const separateCondition = condition && title && condition !== title ? condition : '';
        const conditionDisplay = compactCondition(separateCondition);
        const titleParts = title.split(' · ');
        const eventDisplay = titleParts.length > 1 ? `<strong>${esc(titleParts[0])}</strong>` : esc(title);
        // Under the name, the market as the app names it (contractShort: "BTC above set price at noon ET"), as Tau's
        // Explore chips it, then when the contract closes. The raw ticker (KXBTCD-26OCT2812-T112999.99) carries the
        // series key, so a row never prints it, as Tau's rows don't: the market page names it on its own line.
        // The link is named by what it shows (axe label-content-name-mismatch): its aria-label read the source wording
        // first ("… · $113,000 or above") where the row shows "≥ $113,000", so voice control couldn't say what it saw, and
        // its close went stale under the ticking one. A shortened condition keeps the source's words beside it, for a
        // screen reader only. A space parts each piece (a flex or grid item draws none), so they never run together.
        const chip = contractShort(m.t);
        const spoken = conditionDisplay !== separateCondition ? `<span class="vh"> (${esc(separateCondition)})</span>` : '';
        const contractLink = `<a class="market-name single" href="/explore?m=${encodeURIComponent(m.t)}">${separateCondition ? `<span class="market-identity-line"><span class="market-event" title="${esc(title)}">${eventDisplay}</span> <strong>${esc(conditionDisplay)}</strong>${spoken}</span>` : `<strong>${esc(title || condition || label)}</strong>`}${chip ? ` <span class="market-chip"><span class="mk quiet">${esc(chip)}</span></span>` : ''}${m.ct ? ' ' + liveClose(m.ct, 'chip', { cap: true, cls: 'market-close' }) : ''}</a>${vsHtml(m)}`;
        return [m.t, `<tr>${separateCondition ? `<td class="name market-contract">${contractLink}</td><td class="market-context-cell" data-lab="Context">${titleParts.length > 1 ? `<span class="market-context" title="${esc(title)}">${esc(titleParts.slice(1).join(SEP))}</span>` : '<span class="unavailable" title="No separate context in source title"><span aria-hidden="true">—</span><span class="vh">No separate context</span></span>'}</td>` : `<td class="name" colspan="2">${contractLink}</td>`}
          <td class="num yes-price" data-lab="Yes price">${mid == null ? '—' : cents(mid)}</td><td class="num quote-side quote-bid" data-lab="Yes bid">${quoteSide(m.bid, 'No bid')}</td><td class="num quote-side quote-ask" data-lab="Yes ask">${quoteSide(m.ask, 'No ask')}</td><td class="num market-volume" data-lab="24h volume">${num(Math.round(+m.v24 || 0))}</td><td class="num market-interest" data-lab="Open interest">${num(Math.round(+m.oi || 0))}</td>
          <td class="num xlink"><a href="${kalshiUrl(m)}" target="_blank" rel="noopener" aria-label="Open on Kalshi">${ICON.ext}</a></td></tr>`];
      });
      const pages = Math.max(1, Math.ceil(d.matched / d.per)), note = spotListNote(d.spot, d.markets);
      const sortHead =(key, label, criterion = label, rowspan = 1) => `<th scope="col"${rowspan > 1 ? ` rowspan="${rowspan}"` : ''} class="num${key === 'last' ? ' quote-head' : ''}" aria-sort="${f.sort === key ? 'descending' : 'none'}"><button type="button" data-sort="${key}" title="Sort by ${criterion.toLowerCase()}" aria-label="Sort by ${criterion.toLowerCase()}">${label}${f.sort === key ? ' <span aria-hidden="true">↓</span>' : ''}</button></th>`;
      const sortFocused = !tau && body.querySelector('[data-sort]:focus')?.dataset.sort;
      keepFocus(body, () => {
        paint(body, tau ? '<div id="xnote"></div><div class="sheet"><table class="stack t-explore"><thead><tr><th>Market</th><th class="num">Yes price</th><th class="num">24h volume</th><th class="num">Open interest</th><th class="num"><span class="vh">Link</span></th></tr></thead><tbody id="xrows"></tbody></table></div><div id="xpager"></div>'
          : `<div id="xnote"></div><div class="sheet"><table class="t-explore"><colgroup><col style="width:33.3333333333%"><col style="width:13.8888888889%"></colgroup><colgroup><col style="width:9.7222222222%"><col style="width:7.6388888889%"><col style="width:7.6388888889%"></colgroup><colgroup><col style="width:12.5%"><col style="width:12.5%"><col style="width:2.7777777778%"></colgroup><thead><tr><th scope="col" rowspan="2" class="contract-head">Market / contract</th><th scope="col" rowspan="2" title="Additional context from the market title">Context</th><th scope="colgroup" colspan="3" class="price-group">YES</th>${sortHead('v24', '24h volume', '24h volume', 2)}${sortHead('oi', 'Open interest', 'Open interest', 2)}<th scope="col" rowspan="2" class="num"><span class="vh">Link</span></th></tr><tr>${sortHead('last', 'Price')}<th scope="col" class="num quote-head">Bid</th><th scope="col" class="num quote-head quote-head-ask">Ask</th></tr></thead><tbody id="xrows"></tbody></table></div><div id="xpager"></div>`);
        paint(body.querySelector('#xnote'), note ? `<p class="hint xspot-note${d.spot && !d.spot.stale && !d.spot.failed ? '' : ' behind'}">${esc(note)}</p>` : '');
        paintRows(body.querySelector('#xrows'), rows);
        paint(body.querySelector('#xpager'), pages > 1 ? `<div class="xpage">${f.page > 0 ? `<button class="btn sm" data-pg="${f.page - 1}">${ICON.up ? '' : ''}← Prev</button>` : '<span></span>'}<span class="lab">Page ${f.page + 1} of ${num(pages)}</span>${f.page + 1 < pages ? `<button class="btn sm" data-pg="${f.page + 1}">Next →</button>` : '<span></span>'}</div>` : '');
      });
      body.querySelectorAll('[data-pg]').forEach((b) => b.onclick = () => { f.page = +b.dataset.pg; sync(); window.scrollTo({ top: 0, behavior: smooth() }); load(); });
      if (!tau) {
        body.querySelectorAll('[data-sort]').forEach((b) => b.onclick = () => { f.sort = b.dataset.sort; f.page = 0; sync(); load(); });
        if (sortFocused) Array.from(body.querySelectorAll('[data-sort]')).find(b => b.dataset.sort === sortFocused)?.focus({ preventScroll: true });
      }
    };
    let t; root.querySelector('#xq').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); f.page = 0; sync(); load(undefined, true); }, 220); });
    if (tau) root.querySelectorAll('[data-sort]').forEach((b) => b.onclick = () => { f.sort = b.dataset.sort; f.page = 0; root.querySelectorAll('[data-sort]').forEach((o) => o.setAttribute('aria-pressed', o === b)); sync(); load(); });
    const setShow = (btc) => { f.btc = btc; f.page = 0; root.querySelectorAll('[data-show]').forEach((o) => o.setAttribute('aria-pressed', String(btc === (o.dataset.show === 'bitcoin')))); sync(); load(); };
    root.querySelectorAll('[data-show]').forEach((b) => b.onclick = () => setShow(b.dataset.show === 'bitcoin'));
    await load();
    // The rows' closes ("in 3 min", "closed") are worked out afresh on each poll, and the close clock rewrites them (and
    // the hot rail's) every 5s between polls: walked 2026-10-31 with the polls failing, a row and the rail said "in under
    // a minute" for a contract that had closed a minute before.
    closeClock();
    poll(load, EXPLORE_POLL_MS, 'xstale');
  }
  return {viewExplore};
});
