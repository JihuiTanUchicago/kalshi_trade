/* The Strategies list, in both themes: every strategy the user's agents researched, its filters, figures and
   bulk paper deploy. One strategy's own page (its research paper and its Deploy panel) stays each theme's own,
   in app-strategy.js and app.meridian-strategy.js.
   Fetched on first use (pageLoad in app.js or app.meridian.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns.
   What one theme draws and the other doesn't goes by the bundle's theme (shared(): theme). */
window.TauPage('strategies', (T) => {
  'use strict';
  const {
    api, apNudge, boardTitle, bulkDeployable, busy, catOrder, depSaid, depWrite, errText, esc, fig, flash, gl, go, ICON, loadFail,
    loading, marketShort, num, pageLede, paperShown, pct, registry, root, S, SEP, shell, smooth, strategySlip, strategyTable, theme
  } = T;
  // Each theme heads the list its own way and says an empty list in its own words; the filters, figures, rows and
  // bulk deploy are the same in both.
  const tau = theme === 'tau';

  // The market filter's markets: every one the research picker offers (as the other options, whether or not this
  // account has a strategy on it), and the Bitcoin perpetual when that list leaves it out (its research closed on this
  // server): a customer's perpetual strategies still list, and they couldn't be filtered to. A market a link filters
  // to that neither has is offered too, so the select says what the list is filtered to (it read "All markets").
  // Each option reads its market's customer label (marketShort), never the key.
  const PERP = 'btc_perp';
  const filterMarkets = (markets, picked) => {
    const out = (markets || []).slice(), has = (k) => out.some((m) => m.key === k);
    if (!has(PERP)) out.push({ key: PERP, category: 'Crypto perpetuals' });
    if (picked && !has(picked)) out.push({ key: picked, category: 'Other' });
    return out;
  };

  // ---------- strategies ----------
  async function viewStrategies() {
    const q = new URLSearchParams(location.search);
    const f = { status: q.has('status') ? q.get('status') : '', market: q.get('market') || '', q: q.get('q') || '', deployed: q.get('deployed') === '1' ? '1' : '', sort: q.get('sort') === 'best' ? 'best' : '' };
    // Tau's head sets its figures out under the title; Meridian's folds them under the pass rate (#strategy-passrate).
    const head = tau ? boardTitle('Strategies', 'Every strategy your agents researched. Passed strategies on deployable markets can be deployed; void ones stay here so you can see what didn’t work.') +
      '<dl class="figures measure" id="sfigs" style="margin-top:14px"></dl>'
      : `<div class="board-title strategy-heading"><h1 class="page">Strategies</h1><details class="strategy-summary"><summary><span id="strategy-passrate">Research results</span> ${ICON.chev}</summary><dl class="figures measure" id="sfigs"></dl></details>${pageLede('Every strategy your agents researched. Passed strategies on deployable markets can be deployed; void ones stay here so you can see what didn’t work.')}</div>`;
    shell('/strategies', head, `
      <div class="section-head filters stratfilters">
        <div class="chips" role="group" aria-label="Status">${[['', 'Kept'], ['passed', 'Passed'], ['not_cleared', 'Not cleared'], ['backtest-only', 'Backtest only'], ['failed', 'Void'], ['rejected', 'Rejected']].map(([v, l]) => `<button class="chip" data-f="status" data-v="${v}"${v === 'not_cleared' && f.status !== v ? ' hidden' : ''}${tau || v ? '' : ' title="Passed and backtest-only strategies"'} aria-pressed="${f.status === v}">${l}</button>`).join('')}
          <button class="chip" data-toggle="deployed" aria-pressed="${f.deployed === '1'}">Deployed</button></div>
        ${(() => { const by = {}; filterMarkets(S.me.markets, f.market).forEach((m) =>(by[m.category] || (by[m.category] = [])).push(m)); const cs = Object.keys(by).sort(catOrder); return `<label class="vh" for="strat-market">Market</label><select class="input strat-mkt" id="strat-market" aria-label="Filter by market"><option value="">All markets</option>${cs.map((c) => `<optgroup label="${esc(c)}">${by[c].map((m) => `<option value="${esc(m.key)}"${f.market === m.key ? ' selected' : ''}>${esc(marketShort(m.key))}</option>`).join('')}</optgroup>`).join('')}</select>`; })()}
        <label class="vh" for="strat-sort">Sort</label><select class="input strat-mkt strat-sort" id="strat-sort" aria-label="Sort strategies">${[['', 'Newest first'], ['best', 'Later-period P&amp;L']].map(([v, l]) => `<option value="${v}"${f.sort === v ? ' selected' : ''}>${l}</option>`).join('')}</select>
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
    // "Later-period P&L" (highest first: the backtest P&L after the split date, the Backtest P&L column's figure)
    // orders the whole list server-side (it is paged), and rides in the URL like the filters, so a reload or a
    // shared link keeps it. Not "P&L on data it never saw": it sorts a later-period row (passed with no gatekeeper
    // record, or backtest only) by the same figure, and that slice picked it. Held-out data is after the split too.
    const sortSel = root.querySelector('#strat-sort');
    if (sortSel) sortSel.onchange = () => { f.sort = sortSel.value === 'best' ? 'best' : ''; applyFilters(); };
    const depToggle = root.querySelector('[data-toggle="deployed"]');
    if (depToggle) depToggle.onclick = () => { f.deployed = f.deployed === '1' ? '' : '1'; applyFilters(); };
    const sq = root.querySelector('#strat-q');
    if (sq) sq.onchange = () => { const v = sq.value.trim(); if (v !== f.q) { f.q = v; applyFilters(); } };
    // Paginate server-side at 50/page — a run_forever session can produce far more than the old
    // 500-row cap, and the figures/chip counts come from a real COUNT(*), not the fetched page.
    // Passed counts only true passes: one a later check left uncleared (Missed final test, Held back) keeps the
    // stored status "passed", and the server counts and lists it under Not cleared, a chip shown once one exists.
    // "Void on unseen data" leaves out the void ones with no gatekeeper record (the server's failed_no_record, from its
    // count): the first version's simple backtest stored them as failed, never judged on held-out data. Its note counts
    // them, as Passed's counts the ones not cleared; the Void chip still lists every void row.
    const CLABEL = { passed: 'Passed', not_cleared: 'Not cleared', 'backtest-only': 'Backtest only', failed: 'Void', rejected: 'Rejected' };
    const slipsEl = root.querySelector('#slips');
    let sp = Math.max(0, (parseInt(q.get('page'), 10) || 1) - 1);
    const load = async () => {
      slipsEl.innerHTML = loading(240);
      const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== ''));
      p.set('page', sp);
      let d;
      try { d = await api('/api/strategies?' + p.toString()); } catch (e) {
        if (e.status === 401) throw e;
        slipsEl.innerHTML = loadFail(errText(e), 'Your strategies');
        slipsEl.querySelector('[data-retry]').onclick = () => load();
        return;
      }
      // A remembered page past the end (the list shrank since) starts again at the first.
      if (sp > 0 && d.matched && !(d.strategies || []).length) { sp = 0; history.replaceState(null, '', location.pathname + location.search.replace(/([?&])page=\d+&?/, '$1').replace(/[?&]$/, '')); return load(); }
      const counts = d.counts || {}, total = counts.total || 0, c = (st) => counts[st] || 0;
      // Under the Deployed toggle every counted strategy passed (only passed ones deploy), so its rate read
      // a meaningless 100%: it is left out there rather than shown.
      const rate = total && !f.deployed ? c('passed') / total : null;
      root.querySelector('#sfigs').innerHTML = fig(gl('Passed', 'passed'), num(c('passed')), { small: c('not_cleared') ? `${num(c('not_cleared'))} more passed but ${c('not_cleared') === 1 ? 'wasn’t' : 'weren’t'} cleared to trade` : '' }) + fig(gl('Void on unseen data', 'void'), num(c('failed') - c('failed_no_record')), { small: c('failed_no_record') ? `${num(c('failed_no_record'))} more ${c('failed_no_record') === 1 ? 'was' : 'were'} void on a backtest that wasn’t held out` : '' }) + fig(gl('Rejected in testing', 'rejected'), num(c('rejected'))) +
        // Its denominator said: Research's rate is of every idea tested (most never become a strategy), so the
        // two pages read 8.6% and 12.0% for one account with nothing saying why. With nothing tested yet (a new
        // account, or a market with none) it says so, where it read a bare "—".
        fig('Pass rate', rate != null ? pct(rate, false) : f.deployed ? '—' : 'None yet', { small: f.deployed ? 'not with Deployed on: only passed strategies deploy' : rate != null ? `of the ${num(total)} strateg${total === 1 ? 'y' : 'ies'} here` : 'shows once a strategy here is tested' });
      if (!tau) root.querySelector('#strategy-passrate').textContent = rate != null ? `${pct(rate, false)} pass rate, of the ${num(total)} strateg${total === 1 ? 'y' : 'ies'} here` : 'Research results';
      const kept = total - c('failed') - c('rejected');
      // Each chip counts the rows it lists. The seeded example's strategies are out of the figures above, but a chip
      // lists them (marked Example): "Rejected (0)" opened on the two example rows (walked 2026-10-31). The server
      // counts them per status (counts.examples) and lists the kept ones under Kept, as its matched total does.
      // Grouped in thousands as every count is: a busy autopilot's "Kept (1234)".
      const ex = counts.examples || {}, exN = (st) => +ex[st] || 0;
      const exKept = Object.keys(ex).filter((st) => st !== 'failed' && st !== 'rejected').reduce((a, st) => a + exN(st), 0);
      root.querySelectorAll('[data-f="status"]').forEach((b) => { const v = b.dataset.v; b.textContent = v ? `${CLABEL[v]} (${num(c(v) + exN(v))})` : `Kept (${num(kept + exKept)})`; if (v === 'not_cleared') b.hidden = !c(v) && !exN(v) && f.status !== v; });
      const depChip = root.querySelector('[data-toggle="deployed"]');
      if (depChip && counts.deployed != null) depChip.textContent = `Deployed (${num(counts.deployed)})`;
      if (!d.matched) {
        // A new user's default view, not a filter miss. The Passed filter with nothing passed is that view too: the
        // dashboard's "See passed strategies" lands there after a first session where every idea failed, and
        // "Try another filter" left it with no next step.
        const noneKept = total && !f.q && !f.market && !f.deployed && (f.status ? f.status === 'passed' && !c('passed') : !kept);
        // A search, market or Deployed filter narrows the counts too, so one that matches nothing reads total 0: it is a
        // filter miss, never a new account's list. A search for "zzz" read "Autopilot is on. The strategies it finds will
        // land here" over 74 strategies (walked 2026-10-31).
        const missed = !!(total || f.q || f.market || f.deployed);
        // With autopilot on, the empty list says it is on instead of asking for a session (not "researching":
        // the autopilot panel may be reporting a stale check-in or a billing pause).
        const apOn = !!(S.me && S.me.user && S.me.user.autopilot);
        // Each theme's own words: Tau's "Nothing here yet" over what to do next, Meridian's heading that says which
        // empty it is, with New session for a new account.
        slipsEl.innerHTML = tau
          ? `<div class="empty"><h3>Nothing here yet</h3><p>${noneKept ? 'None of your strategies has passed its tests yet. Most ideas fail; the ones that pass land here.' : missed ? 'Try another filter.' : apOn ? 'Autopilot is on. The strategies it finds will land here.' : 'Start a research session and the strategies it finds will land here.'}${noneKept && apOn ? ' Autopilot keeps researching on its own.' : ''}</p>${missed && !noneKept ? '' : `${apNudge('Rather not write ideas yourself?', 'and it researches on its own, on paper.')}<a class="btn" href="/research">${apOn ? 'See its research' : 'Go to Research'}</a>`}</div>`
          : `<div class="empty"><h3>${noneKept ? 'No strategy has passed yet' : missed ? 'No matching strategies' : 'No strategies yet'}</h3>${noneKept ? `<p>Most ideas fail their tests; the ones that pass land here.${apOn ? ' Autopilot keeps researching on its own.' : ''}</p>` : missed ? '<p>Try another filter.</p>' : apOn ? '<p>Autopilot is on. The strategies it finds will land here.</p>' : '<p>Every strategy a research session writes lands here, with its test on data it never saw. Start a session to find your first.</p>'}${missed && !noneKept ? '' : `${apNudge('Rather not write ideas yourself?', 'and it researches on its own, on paper.')}${apOn ? '<a class="btn" href="/research">See its research</a>' : '<a class="btn" href="/research?new=1">New session</a>'}`}</div>`;
        return;
      }
      const list = d.strategies, reg = registry(list.map((s) => s.equity));
      const anyPassed = list.some(bulkDeployable);
      // A Paper P&L column beside the backtest's, when a row on this page has a paper book now or had one.
      const paperCol = list.some(paperShown);
      // Each bundle's strategyTable: Meridian's also takes whether the table is a research session's (here, never).
      const rows = list.map((s) => strategySlip(s, reg, { pick: anyPassed, paper: paperCol })).join('');
      slipsEl.innerHTML = (tau ? strategyTable(rows, anyPassed, paperCol) : strategyTable(rows, anyPassed, false, paperCol))
        + (d.pages > 1 ? `<div class="xpage">${sp > 0 ? `<button class="btn sm" data-sp="${sp - 1}">← Prev</button>` : '<span></span>'}<span class="lab">Page ${sp + 1} of ${num(d.pages)}${SEP}${num(d.matched)} strategies</span>${sp + 1 < d.pages ? `<button class="btn sm" data-sp="${sp + 1}">Next →</button>` : '<span></span>'}</div>` : '');
      slipsEl.querySelectorAll('[data-sp]').forEach((b) => b.onclick = () => {
        sp = +b.dataset.sp;
        const u = new URLSearchParams(location.search);
        if (sp) u.set('page', sp + 1); else u.delete('page');
        history.replaceState(null, '', '/strategies' + (u.toString() ? '?' + u.toString() : ''));
        load(); window.scrollTo({ top: 0, behavior: smooth() });
      });
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
        try { await depWrite('/api/deployments', { strategy_id: id, mode: 'paper' }); ok++; } catch (e) { errs.push(depSaid(e, 'deploy')); }
      }
      if (ok && !errs.length) { go('/deploy'); return; }
      flash('#bulkflash', `${ok} deployed${errs.length ? `${SEP}${errs.length} failed: ${errs[0]}` : ''}`, errs.length ? 'bad' : 'good');
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

  return {viewStrategies};
});
