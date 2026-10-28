/* Meridian's Research pages: the session list and a session's page.
   Fetched on first use (pageLoad in app.meridian.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns. */
window.TauPage('research', (T) => {
  'use strict';
  const {
    alert0, announce, api, ApiError, apNudge, armed, boardTitle, busy, clearTimers, errText, loadFail, esc, EXAMPLE_NOTE, exampleLine,
    failText, feedMd, fig, fillLiveRow, flash, gl, glo, GLOSSARY, go, ICON, loading, logTime, marketPicker, marketShort,
    markQuietRows, mdLite, MKT_SHORT, num, paint, paintRows, pct, phone, poll, root, runKind, runTag,
    runWaitLine, S, SEP, sessionNo, sessionTitle, shell, strategySlip, strategyTable, tzName, usd, waitSpan, when,
    whyFailedHtml, wireMarketPicker
  } = T;

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
         <p class="rsi-last">Generalization score ${delta}${pol.evolved_at ? `${SEP}adopted ` + when(pol.evolved_at) : ''} <span class="rsi-note">(higher = catches more real out-of-sample winners, scored over shuffled orderings so it can’t overfit)</span></p>`
      : `<p>New search policies are scored against the current policy over shuffled history. Only an improvement is adopted.</p>`;
    // Demoted to a compact, collapsible line so the research page leads with the form, not panels.
    const expanded = !!host.querySelector('details[open]');
    const focused = !!host.querySelector('details > summary:focus');
    paint(host, `<details class="rsidisc"${expanded ? ' open' : ''}>
      <summary class="rsidisc-cap"><b class="rsi-badge">RSI</b><span class="rsidisc-t">Self-improving research engine</span>${tag}${pol.evolved && delta ? `<span class="rsidisc-delta">${delta}</span>` : ''}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
      <div class="rsidisc-body">${body}</div>
    </details>`);
    if (focused) host.querySelector('summary').focus({ preventScroll: true });
  }
  // The research loop's own report card (GET /api/research/scoreboard, app/research/rsi.py): is research
  // getting better, what it has learned per market family (playbooks under A/B test), where the
  // free scan points it next, and which ideas the pipeline (not the market) killed. Fetched at
  // most once a minute; the 5s page poll re-renders from the cached board.
  const LOOP_FAMILY = { 'weather-high': 'Daily high temps', 'weather-low': 'Daily low temps', crypto: 'Crypto' };
  const loopFamily = (f) => LOOP_FAMILY[f] || (f ? f.charAt(0).toUpperCase() + f.slice(1).replace(/-/g, ' ') : '');
  const LOOP_TAG = { feature_unavailable: 'feature missing', no_data: 'no data', zero_trades: 'never traded', fee_floor: 'under the fee', loses: 'loses money', spec_invalid: 'spec rejected', missing_context: 'needs data we lack', thin_sample: 'too few examples', no_signal: 'no signal', wrong_fit: 'wrong for this market', other: 'other' };
  const loopRate = (r) => (r == null ? '—' : Math.round(r * 100) + '%');
  // failed: what the last read said when it failed (cleared by the next read that comes back).
  // okAt: when the board on hand came back, for the line a failed refresh puts above it.
  const rsiLoop = { board: null, at: 0, okAt: 0, req: null, failed: null };
  // The board's read, at most once a minute and one at a time. The Research page starts it as it opens,
  // beside the session list: asked from the list's first paint, it waited a whole round trip for the list.
  function rsiLoopRead() {
    if (!rsiLoop.req && Date.now() - rsiLoop.at > 60000) {
      rsiLoop.req = api('/api/research/scoreboard?days=14', undefined, { keep: true })
        .then((b) => { rsiLoop.board = b; rsiLoop.okAt = Date.now(); rsiLoop.failed = null; }, (e) => { rsiLoop.failed = errText(e); /* a board read before is kept */ })
        .finally(() => { rsiLoop.at = Date.now(); rsiLoop.req = null; });
    }
    return rsiLoop.req;
  }
  async function renderResearchLoop(host, pol, tried) {
    if (!host) return;
    const reading = rsiLoopRead();
    if (reading) await reading;
    const b = rsiLoop.board;
    // A board that never came says so, with Try again: it fell back to the older "Self-improving research
    // engine" card as if that were the current read, and said nothing (walk 2026-10-28).
    if (!b && rsiLoop.failed) {
      paint(host, loadFail(rsiLoop.failed, 'Your research results'));
      const again = host.querySelector('[data-retry]');
      if (again) again.onclick = () => { rsiLoop.at = 0; paint(host, loading(56)); renderResearchLoop(host, pol, tried); };
      return;
    }
    if (!b || !b.total || !b.total.runs) { renderRsiMomentum(host, pol, tried); return; }
    // A refresh that failed with a board up kept it and said nothing, so it read as current. One quiet line above the
    // card says so, as the bell's does, with Try again; the next read that comes back takes it away.
    const loopAgo = () => { const m = Math.max(1, Math.round((Date.now() - rsiLoop.okAt) / 60000)); if (m < 60) return `${num(m)} min ago`; const h = Math.round(m / 60); return `${num(h)} hour${h === 1 ? '' : 's'} ago`; };
    const staleLine = rsiLoop.failed && rsiLoop.okAt ? `<p class="stale-note loop-stale" role="status">Couldn’t refresh. Showing your research results from ${loopAgo()}. <button type="button" class="stale-again" data-loop-retry>Try again</button></p>` : '';
    const t = b.total, tr = b.trend;
    const delta = tr ? `<span class="rsi-score">${loopRate(tr.before.gate_reach_rate)} <span class="rsi-arrow">→</span> ${loopRate(tr.after.gate_reach_rate)}</span>` : '';
    const tag = tr ? (tr.better ? '<span class="rsi-tag">Improving</span>' : '<span class="rsi-tag quiet">Not improving yet</span>') : '<span class="rsi-tag quiet">Learning</span>';
    const perIdea = t.explored ? usd(t.cost_usd / t.explored) : '—';
    const figs = `<dl class="figures measure loop-figs">${fig('Ideas tried', num(t.explored), { small: `${num(t.runs)} session${t.runs === 1 ? '' : 's'}${SEP}14 days` })}${fig('Reached the gate', num(t.gated), { small: `${loopRate(t.gate_reach_rate)} of ideas` })}${fig('Passed', num(t.passed), { small: t.holdout_passed ? `${num(t.holdout_passed)} held out` : 'every gate' })}${fig('Spend', usd(t.cost_usd), { small: `${perIdea} per idea` })}${fig('Killed by our pipeline', loopRate(t.pipeline_death_share), { small: 'of dropped ideas' })}</dl>`;
    const trendP = tr
      ? `<p class="loop-trend">${tr.better ? 'Getting better.' : 'Not better yet.'} The newer ${num(tr.after.runs)} session${tr.after.runs === 1 ? '' : 's'} took ${loopRate(tr.after.gate_reach_rate)} of ${num(tr.after.explored)} ideas to the statistical gate, against ${loopRate(tr.before.gate_reach_rate)} of ${num(tr.before.explored)} before.</p>`
      : `<p class="loop-trend">Each session’s ideas are counted from first draft to final verdict. A before/after trend appears once there are 16 ideas to compare.</p>`;
    const maxIdeas = Math.max(1, ...(b.days || []).map((d) => d.explored));
    const days = (b.days || []).length > 1 ? `<div class="loop-days" role="img" aria-label="Ideas per day and how many reached the gate">${b.days.slice(-14).map((d) => `<span class="loop-day" title="${esc(d.day)}: ${num(d.explored)} ideas, ${num(d.gated)} reached the gate"><i class="all" style="height:${Math.max(4, Math.round(40 * d.explored / maxIdeas))}px"></i><i class="hit" style="height:${d.gated ? Math.max(3, Math.round(40 * d.gated / maxIdeas)) : 0}px"></i></span>`).join('')}</div><p class="loop-legend"><i class="all"></i>ideas per day <i class="hit"></i>reached the gate</p>` : '';
    const pt = b.paper && b.paper.total, byPb = (b.paper && b.paper.by_playbook) || {};
    const paperP = pt && pt.strategies ? `<p class="loop-trend">On paper at the market’s real prices: ${num(pt.strategies)} passed strateg${pt.strategies === 1 ? 'y' : 'ies'}, ${num(pt.trading)} trading, ${num(pt.round_trips)} closed trade${pt.round_trips === 1 ? '' : 's'}, net ${usd(pt.net_pnl, true)}${pt.realization == null ? '' : pt.realization < 0 ? ', losing money where the backtest expected a profit' : `, earning ${Math.round(pt.realization * 100)}% of what the backtest expected`}${pt.live_ready ? `${SEP}${num(pt.live_ready)} ready for live` : ''}.</p>` : '';
    const fams = {};
    (b.playbooks || []).forEach((p) => { (fams[p.family] = fams[p.family] || {})[p.status] = p; });
    const pbRows = Object.keys(fams).sort().map((f) => {
      const a = fams[f].active, c = fams[f].candidate;
      const paper = (p) => { const q = byPb[p.id] || byPb[String(p.id)]; return q && q.round_trips ? `${SEP}on paper ${num(q.round_trips)} closed trade${q.round_trips === 1 ? '' : 's'}, ${usd(q.net_pnl, true)}` : ''; };
      const rec = (p) => (p.ideas ? `${num(p.reached)} of ${num(p.ideas)} ideas reached the gate` : 'no ideas yet') + paper(p);
      const act = a ? `<b>v${a.version}</b> in use${a.version ? '' : ' (no lessons yet)'}${SEP}${rec(a)}` : '';
      const cand = c ? `<br><b>v${c.version}</b> on trial${SEP}${rec(c)}${c.p_better != null ? `${SEP}${Math.round(c.p_better * 100)}% likely better` : ''}${c.changes ? `<span class="loop-why">What changed: ${esc(c.changes)}</span>` : ''}` : '';
      const text = (c && c.text) || (a && a.text) || '';
      return `<li><span class="loop-k">${esc(loopFamily(f))}</span><span class="loop-v">${act}${cand}${text ? `<details class="loop-pb"><summary>Read the playbook</summary><pre>${esc(text)}</pre></details>` : ''}</span></li>`;
    }).join('');
    const scout = (b.scout || []).slice(0, 5).map((s) => `<li><span class="loop-k">${esc(marketShort(s.market))}</span><span class="loop-v">${esc(s.best_what || '')}${SEP}${s.best_net_c != null ? (s.best_net_c > 0 ? '+' : '') + s.best_net_c.toFixed(1) + '¢' : ''} net per contract${SEP}${s.best_z != null ? s.best_z.toFixed(1) : '—'} SE</span></li>`).join('');
    const fixes = (b.fix_list || []).slice(0, 5).map((x) => `<li><span class="loop-k">${esc(marketShort(x.market))}</span><span class="loop-v"><b>${esc(LOOP_TAG[x.tag] || LOOP_TAG.other)}</b> × ${num(x.count)}${x.example ? `<span class="loop-why">${esc(String(x.example).slice(0, 180))}</span>` : ''}</span></li>`).join('');
    const REQ_KIND = { history: 'more settled history', micro: 'order-book feature', ticks: 'per-second data' };
    const REQ_STATE = { open: 'collecting', ready: 'data arrived', requeued: 'idea re-tested', expired: 'gave up' };
    const reqs = (b.data_requests || []).slice(0, 6).map((r) => `<li><span class="loop-k">${esc(marketShort(r.market))}</span><span class="loop-v"><b>${esc(REQ_KIND[r.kind] || 'more data')}${r.need ? SEP + esc(r.need) : ''}</b>${SEP}${esc(REQ_STATE[r.status] || 'requested')}${r.requeued_run_id ? `${SEP}<a href="/research/${r.requeued_run_id}">session</a>` : ''}${r.idea_title ? `<span class="loop-why">For: ${esc(r.idea_title)}</span>` : ''}${r.status !== 'requeued' && r.note ? `<span class="loop-why">${esc(r.note)}</span>` : ''}</span></li>`).join('');
    const sect = (h, sub, items) => items ? `<div class="loop-sect"><h4>${h}</h4><p class="loop-sub">${sub}</p><ul class="loop-list">${items}</ul></div>` : '';
    const tn = b.tournament, tnEnt = tn ? (tn.entrants || []).filter((r) => r.strategy_id).sort((x, y) => y.weight - x.weight) : [];
    const tnCash = tn ? (tn.entrants || []).find((r) => !r.strategy_id) : null;
    const tnRows = tnEnt.slice(0, 8).map((r) => `<li><span class="loop-k">${esc(marketShort(r.market))}</span><span class="loop-v"><b>${Math.round(r.weight * 100)}% of the book</b>${SEP}${esc(r.title || '')}${SEP}${num(r.trips)} bet${r.trips === 1 ? '' : 's'}, ${usd(r.net_pnl, true)}${SEP}${Math.round((r.p_positive || 0) * 100)}% likely to make money${r.verdict ? `<span class="loop-why">Falling short: ${esc(r.verdict)}</span>` : ''}</span></li>`).join('')
      + (tnEnt.length && tnCash ? `<li><span class="loop-k">Cash</span><span class="loop-v"><b>${Math.round(tnCash.weight * 100)}% of the book</b>${SEP}held back until a strategy shows it makes money</span></li>` : '');
    const tnSub = tn && tn.pooled ? `Every strategy on paper takes part at once, and a ${usd(tn.book.capital).replace(/\.00$/, '')} practice book shifts toward the ones that earn. Together they have ${num(tn.pooled.trips)} of the ${num(tn.pooled.target)} separate bets it takes to judge them${tn.pooled.days_to_target != null ? `, about ${Math.round(tn.pooled.days_to_target)} days to go at ${tn.pooled.per_day} a day` : ''}${tn.pooled.mean_return != null ? `, averaging ${pct(tn.pooled.mean_return)} of the stake a bet` : ''}. ${tn.book.trips ? `Practice book so far: ${usd(tn.book.pnl, true)} over ${num(tn.book.trips)} trade${tn.book.trips === 1 ? '' : 's'}.` : 'The practice book has no trades yet.'}` : '';
    const body = figs + trendP + days + paperP
      + sect('Paper tournament', tnSub, tnRows)
      + sect('What it has learned', 'After every session the loop rewrites a playbook for that kind of market from its verdicts. A rewrite is tried on new sessions and kept only if more of its ideas reach the gate.', pbRows)
      + sect('Where it looks next', 'A free scan of every market for prices that disagree with how they settle, after fees. Leads steer research; they still have to pass on unseen data.', scout)
      + sect('Ideas our pipeline killed', 'Dropped because of missing data or features, not because the market said no. This is the fix list.', fixes)
      + sect('Data it asked for', 'Crypto ideas that died for lack of data start a collection, and the idea is re-tested once the data exists (autopilot on, at most once each).', reqs)
      + (pol && pol.evolved ? `<p class="rsi-last">Finalist policy evolved from your history${pol.base_score != null && pol.score != null ? `${SEP}score ${pol.base_score} → ${pol.score}` : ''}.</p>` : '');
    const open = !!host.querySelector('details.rsidisc[open]');
    const focused = !!host.querySelector('details.rsidisc > summary:focus');
    const inner = [...host.querySelectorAll('details.loop-pb')].map((d) => d.open);
    // The 5s poll re-renders from the kept board: the card is rebuilt only when its markup changed.
    paint(host, `${staleLine}<details class="rsidisc loop"${open ? ' open' : ''}>
      <summary class="rsidisc-cap"><b class="rsi-badge">RSI</b><span class="rsidisc-t">Is research getting better?</span>${tag}${delta ? `<span class="rsidisc-delta">${delta} reach the gate</span>` : ''}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary>
      <div class="rsidisc-body">${body}</div>
    </details>`);
    const again = host.querySelector('[data-loop-retry]');
    if (again) again.onclick = () => { rsiLoop.at = 0; return renderResearchLoop(host, pol, tried); };
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
    const gates = ['Bootstrap CI', 'PSR', `DSR${SEP}deflated by trial count`, 'Placebo / null', 'LORD++ FDR budget', 'Purged walk-forward', 'Benjamini–Hochberg'];
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
          fnode('Adds something new', 'Its daily returns can’t move too closely with a strategy that already passed here on the same market (correlation |ρ| ≤ 0.80). A near-copy adds nothing.'),
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
  // `own`: true for the user's own sessions on any model (an older server's "yours"), 'model' for their
  // own sessions on the model picked (yours_by_model), false for everyone's on that model.
  const costBasis = (own) => own === 'model' ? 'your recent sessions on this model' : own ? 'your recent sessions' : 'recent sessions on this model';
  function sessionCostLine(v, forever, own) {
    const basis = costBasis(own);
    return forever
      ? `Each round of ideas usually costs about ${usd(v)} (${basis}); it keeps starting new rounds until you stop it.`
      : `A session like this usually takes about ${usd(v)} from your credits (${basis}).`;
  }
  // Run-until-stopped has no natural size, so say its pace: about what an hour costs at recent rates
  // (/api/research/estimate per_hour, the user's own else the model's typical) and how long the
  // balance covers that. It stops by itself only when credits run out, unless auto-reload tops up.
  function foreverRateLine(hourly, own, me) {
    let s = hourly == null ? '' : `At recent rates it costs about ${usd(hourly)} an hour (${costBasis(own)}).`;
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
    rsiLoopRead();  // the loop card's board, read beside the session list below
    // /api/me carries the model list, so the page's own reads below don't wait a round trip on it.
    const mdl = (me && me.models) || await api('/api/models').catch(() => ({ models: [], default: '' }));
    // Arriving with ?market= (Explore's "Research <market>") for a market the picker doesn't offer right now
    // (perpetuals switched off, a venue with no data yet) left Agent's choice picked and said nothing, so the
    // session ran on whatever market the agent chose. It says so, where the market is picked and in the
    // Options line. A key it doesn't know is never shown as typed.
    const wantMkt = new URLSearchParams(location.search).get('market');
    const wantRow = wantMkt ? (me.markets || []).find((m) => m.key === wantMkt) : null;
    const notOpen = wantMkt && !wantRow ? `${MKT_SHORT[wantMkt] || 'The market you picked'} isn\u2019t open for research right now` : '';
    // Under the credits a session needs to start, the form says so up top. Start refused for it (402) moves
    // that note beside Start instead of adding the server's own words under it: the same warning twice.
    const lowSaid = `You have ${usd(me.credit_balance)} in credits — a research session needs at least ${usd(me.min_run_balance)} to start.`;
    const lowNote = (kind) => `<div class="notice${kind ? ' ' + kind : ''}" id="rlow" role="${kind === 'bad' ? 'alert' : 'status'}">${ICON.warn}<span>${lowSaid} ${me.reload_failed ? 'Auto-reload couldn’t charge your card. <a href="/billing">Update your card and add credits →</a>' : '<a href="/billing">Add credits →</a>'}</span></div>`;
    // Models you can't pick yet go after the ones you can, and say "coming soon": they led the list as
    // "(access pending)", four greyed-out rows above the default.
    const modelOpts = (mdl.models || []).filter((m) => m.available !== false).concat((mdl.models || []).filter((m) => m.available === false))
      .map((m) => `<option value="${esc(m.key)}"${m.key === mdl.default ? ' selected' : ''}${m.available === false ? ' disabled' : ''}>${esc(m.label)}${m.available === false ? ' (coming soon)' : ''}</option>`).join('');
    shell('/research', '', `
      <div class="research-page"><h1 class="page">Research</h1><p class="lede research-lede">Describe an idea and a session turns it into strategies, then tests each on data it never saw. The ones that pass can trade on paper.</p>${S.me.user && !S.me.user.autopilot ? `<p class="research-ap">Rather not write ideas yourself? <button type="button" data-research-ap>Turn on autopilot</button> and it picks ideas and researches them on its own, on paper.</p>` : ''}${S.me.user ? `<p class="research-ap-on" data-ap-next${S.me.user.autopilot ? '' : ' hidden'}>Autopilot is on: the sessions it starts are listed below with an Autopilot tag. You can still start a session of your own.</p>` : ''}<div id="rexample"></div><div class="research-work"><div id="active-research"></div><div id="rsimo"></div></div><details class="research-create" id="research-create"${new URLSearchParams(location.search).get('new') === '1' ? ' open' : ''}><summary class="btn primary">New session</summary><div class="research-compose"><form class="panel dispatch" id="dispatch">

        ${me.needs_card ? `<div class="notice" role="status">${ICON.warn}<span>Add a payment method to start researching. Your $${me.free_bonus} in free credits unlock the moment a card is on file — you won’t be charged until they run out. <a href="/billing">Add a card →</a></span></div>` : ''}
        ${(!me.needs_card && me.billing_enabled && me.credit_balance < me.min_run_balance) ? lowNote('') : ''}
        <label class="field"><span>Describe your idea</span>
          <textarea class="input" name="prompt" maxlength="1000" rows="3" required placeholder="Write your own — e.g. “Sell overpriced tails in the last hour before the 5pm close.”"></textarea></label>
        <details class="dispatch-opts" id="ropts"${phone() ? '' : ' open'}><summary><span class="dispatch-opts-t">Options</span><span class="dispatch-opts-sum" id="ropts-sum"></span></summary><div class="dispatch-opts-body">
        <div class="dispatch-tune">
          ${modelOpts ? `<label class="field"><span>Model</span>
            <select class="input" name="model" id="rmodel">${modelOpts}</select></label>` : ''}
          <label class="field"><span>Strategies to test</span>
            <input class="input" type="number" name="max_hypotheses" id="maxhyp" min="1" max="1000" value="10"></label>
          <label class="switch tune-sw"><input type="checkbox" name="run_forever" id="runforever" checked><span>Let it run until I stop it</span></label>
        </div>
        <fieldset class="field mkt-field" style="border:0;padding:0;margin:0"><legend class="label" style="margin-bottom:8px">Market</legend>
          ${notOpen ? `<p class="hint mkt-missing" role="status">${esc(notOpen)}, so the agent picks the market unless you choose one here.</p>` : ''}
          ${marketPicker(me.markets)}
        </fieldset>
        </div></details>
        <div class="dispatch-go">
          <a class="chip ex" href="/example" data-ex-open title="Opens the finished example session; nothing runs">See the demo session</a>
          <button type="button" class="linkish ex-run" data-ex="${esc(DEMO_PROMPT)}">or run it yourself</button>
          <button class="btn primary go" type="submit" ${me.needs_card ? 'aria-disabled="true"' : ''}>Start session</button>
        </div>
        <p class="hint ex-cost" id="ex-cost" hidden></p>
        <p class="hint go-cost" id="rcost" hidden></p>
        <div id="dflash"></div>
        <p class="hint" id="rf-hint">A session takes a few minutes and keeps running if you leave this page.</p>
      </form>${pipelineFigure()}</div></details><section class="research-history sect"><div class="sect-head research-archive-heading"><h2>Recent sessions <span id="rcount"></span></h2><div class="rengine" id="rengine"><section class="research-total" aria-label="All sessions, including active"><h3>All sessions</h3><dl class="figures measure" id="rfigs"></dl><dl class="figures measure research-status" id="research-status"></dl><p class="stale-note" id="runs-stale" role="status"></p></section></div></div>
        <div class="run-columns" aria-hidden="true"><span>Hypothesis / session</span><span>Market</span><span>Created</span><span>Outcome</span></div><div id="flash"></div><div class="runs" id="runs">${loading(70)}${loading(70)}</div></section></div>`);
    const form = root.querySelector('#dispatch');
    wireMarketPicker(form);
    const pickMkt = wantRow && [...form.querySelectorAll('input[name=market]')].find((r) => r.value === wantMkt);
    if (pickMkt) {
      pickMkt.checked = true;
      const grp = pickMkt.closest('details'); if (grp) grp.open = true;
    }
    if (pickMkt || notOpen) { const opts = form.querySelector('#ropts'); if (opts) opts.open = true; }
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
        nm ? nm.textContent.trim() : notOpen ? `agent\u2019s choice of market (${notOpen})` : 'agent\u2019s choice of market'].filter(Boolean).join(SEP);
    };
    form.addEventListener('change', syncOpts); syncOpts();
    // A field the browser won't accept (0 or 5,000 strategies) inside folded Options: it can't show its
    // message on a hidden field, so Start did nothing. Unfold Options so the browser points at it.
    form.addEventListener('invalid', () => { const o = form.querySelector('#ropts'); if (o && !o.open) o.open = true; }, true);
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
      let est = null, estFailed = false;
      const sync = syncCost = () => {
        // The user's own figure for the model picked (yours_by_model): "yours" pooled every model, so a
        // history on the default model read beside the cheapest one too. An older server sends "yours" alone.
        const key = (msel && msel.value) || mdl.default, byModel = est && est.yours_by_model;
        const mine = !est ? null : byModel ? byModel[key] : est.yours, own = mine != null && (byModel ? 'model' : true);
        const v = !est ? null : own ? mine : (est.typical || {})[key];
        const forever = !!(rf && rf.checked), ph = (est && est.per_hour) || {};
        const myRate = ph.yours_by_model ? ph.yours_by_model[key] : ph.yours, ownRate = myRate != null && (ph.yours_by_model ? 'model' : true);
        const hourly = ownRate ? myRate : (ph.typical || {})[key];
        const pace = forever && (v != null || hourly != null) ? foreverRateLine(hourly == null ? null : +hourly, ownRate, me) : '';
        // No ledger figure for this model (or the read failed): with payments on, still say how it
        // is billed and that it can be stopped, rather than leaving the cost blank.
        // A read that failed says so: "No cost estimate for this model yet" claimed there was none (walk 2026-10-28).
        const none = v == null && !pace && me.billing_enabled ? (estFailed ? 'The cost estimate didn\u2019t load. ' : 'No cost estimate for this model yet. ') + 'It\u2019s charged to your credits as it runs, and you can stop it any time from its session page.' : '';
        rc.hidden = v == null && !pace && !none;
        rc.textContent = [v == null ? '' : sessionCostLine(+v, forever, own), pace, none].filter(Boolean).join(' ');
      };
      if (msel) msel.addEventListener('change', sync);
      api('/api/research/estimate').then((d) => { est = d; }, () => { est = null; estFailed = true; }).then(sync);
    })();
    // A start Tau didn't confirm may have landed: the sessions on this page read every 5s, so the words
    // point there instead of at a reload (the typed idea is kept either way).
    const RUN_UNSURE = 'Tau didn\u2019t confirm the session started. If it did, it shows up in your sessions on this page within a few seconds; check there before you start it again.';
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
        } catch (err) {
          const said = form.querySelector('#dflash'), low = err.status === 402 && form.querySelector('#rlow');
          if (low && said) { low.remove(); said.innerHTML = lowNote('bad'); announce(lowSaid, true); }
          else flash('#dflash', err instanceof ApiError && err.message === failText(0, true) ? RUN_UNSURE : err.message, 'bad');
          // The error sits under the cost lines: on a phone that is below the fold, so Start looked
          // like it did nothing (out of credits, two sessions already going). Bring it into view.
          if (said && said.scrollIntoView) said.scrollIntoView({ block: 'nearest' });
        }
      });
    };
    // Live market context: fold the shared book onto each picker row (read-only). Rows with no
    // live quote right now are labelled once the feed resolves; the picker works either way.
    (async () => {
      try {
        const c = await api('/api/research/context');
        (c.markets || []).forEach((m) => fillLiveRow(form, m));
        // Only an answer says a row has no live quote: a read that failed said it of every market (walk 2026-10-28).
        markQuietRows(form);
      } catch (e) { /* no feed yet -> the picker still works blind */ }
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
      // Passed counts only what was cleared to trade: a pass a later check left uncleared (Missed final test,
      // Held back) is counted apart (`not_cleared`), as each session row and the Strategies list count it.
      const passed = d.totals ? d.totals.passed : d.runs.reduce((a, r) => a + runPassed(r).ok, 0);
      const fell = d.totals ? +d.totals.not_cleared || 0 : d.runs.reduce((a, r) => a + runPassed(r).fell, 0);
      // A paused session holds one of the two session slots but isn't running: it says paused.
      const running = d.counts.research_running, queued = d.counts.research_queued, paused = d.counts.research_paused || 0;
      paint(root.querySelector('#research-status'), fig('Running', num(running)) + (paused ? fig('Paused', num(paused)) : '') + fig('Queued', num(queued)));
      const rfigs = root.querySelector('#rfigs'), rtitle = tried ? `${pct(passed / tried, false)} of ${num(tried)} tested, all time` : 'No strategies tested';
      // All time, every session (the server's totals), while the autopilot panel's figures are its last 7 days:
      // each says its window.
      paint(rfigs, fig(gl('Passed', 'gate'), num(passed), { small: [ALL_TIME, fell ? `${num(fell)} more passed but ${fell === 1 ? 'wasn’t' : 'weren’t'} cleared to trade` : ''].filter(Boolean).join(SEP) }) + fig('Tested', num(tried), { small: ALL_TIME }));
      if (rfigs.getAttribute('title') !== rtitle) rfigs.setAttribute('title', rtitle);
      renderResearchLoop(root.querySelector('#rsimo'), d.policy, tried);
      // The card's "Spent so far" names its credits, as the session rows and the session page do, and keeps the
      // amount whole: a bare "$1.84" in this row of counts read as a result.
      const active = d.runs.find((r) => r.status === 'running') || d.runs.find((r) => r.status === 'queued') || d.runs.find((r) => r.status === 'paused');
      paint(root.querySelector('#active-research'), active ? `<section class="active-research active-${esc(active.status)}">
        <div class="active-head"><h2 class="active-prompt" title="${esc(sessionTitle(active))}">${esc(sessionTitle(active))}</h2></div>
        <div class="active-meta"><div class="active-session"><span class="active-state">${runLate(active) ? lateLabel(runLate(active)) : active.status === 'paused' ? 'Paused' : active.status === 'queued' ? 'Queued' : 'Researching'}</span>${sessionNo(active) ? `<b>${sessionNo(active)}</b>` : ''}${runTag(active)}</div><span>${esc(marketShort(active.market))}</span>${active.started_at ? `<span>Started ${when(active.started_at)}</span>` : ''}</div>
        <aside class="active-aside" aria-label="Session progress"><a class="active-open btn primary" href="/research/${active.id}">Open session <span aria-hidden="true">→</span></a><dl class="active-foot"><div><dt>Tested</dt><dd>${num(active.hypotheses_tried || 0)}</dd></div><div><dt>Passed</dt><dd>${num(runPassed(active).ok)}</dd></div>${runPassed(active).fell ? `<div><dt>Not cleared</dt><dd>${num(runPassed(active).fell)}</dd></div>` : ''}${active.spent_usd != null ? `<div><dt>Spent so far</dt><dd>${+active.spent_usd > 0 ? `<span class="nobr">${spentSoFar(active.spent_usd)}</span>${CRED}` : spentSoFar(active.spent_usd)}</dd></div>` : ''}</dl></aside>
      </section>` : '');
      const history = active ? d.runs.filter((r) => r.id !== active.id) : d.runs;
      // The seeded example is listed but isn't the user's: it doesn't count as a session of theirs.
      const own = history.filter((r) => !r.example).length;
      const rex = root.querySelector('#rexample'), exHtml = exampleLine(d.runs);
      if (rex && rex.dataset.h !== exHtml) { rex.dataset.h = exHtml; rex.innerHTML = exHtml; }
      const exRun = d.runs.find((r) => r.example), exOpen = root.querySelector('[data-ex-open]');
      if (exOpen) { const hide = !exRun || !!exHtml; if (exOpen.hidden !== hide) exOpen.hidden = hide; if (exRun && exOpen.getAttribute('href') !== '/research/' + exRun.id) exOpen.setAttribute('href', '/research/' + exRun.id); }
      // "or run it yourself" follows the demo link; with the link hidden (no example, or the example's own
      // line is up top) it stood alone beside Start and read as a fragment.
      const exRunBtn = root.querySelector('button[data-ex]');
      if (exRunBtn) { const t = exOpen && !exOpen.hidden ? 'or run it yourself' : 'Run the demo idea yourself'; if (exRunBtn.textContent !== t) exRunBtn.textContent = t; }
      // The heading counts what it lists: "Recent sessions 1" sat over two rows, the example one of them. The user's
      // own count stays bare and the example is named apart ("1 · 1 example"), as Tau's "1 session · 1 example".
      const examples = history.length - own;
      paint(root.querySelector('#rcount'), [own ? String(own) : '', examples ? `${examples} example${examples > 1 ? 's' : ''}` : ''].filter(Boolean).join(SEP));
      // The newest of all (the active one when one runs: then no older row offers Add credits).
      const newest = d.runs.find((r) => !r.example);
      paintRows(root.querySelector('#runs'), history.map((r) => [r.id, runRow(r, r === newest)]),
        `<div class="empty"><h3>${active ? 'No earlier sessions' : 'No sessions yet'}</h3></div>`);
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
      : r.max_hypotheses ? `Up to ${num(r.max_hypotheses)} strateg${+r.max_hypotheses === 1 ? 'y' : 'ies'}` : ''].filter(Boolean).join(SEP);
  // What a session still going has spent. Before its first model call is billed that is nothing, not a $0.00 figure
  // (a first autopilot session read "Spent so far: $0.00" on its row and its page); a sliver says "under $0.01".
  const spentSoFar = (v, none = 'None yet') => (+v >= 0.005 ? usd(v) : +v > 0 ? 'under $0.01' : none);
  // It names the credits it came from, as the session page does ("from your credits"): a bare "Cost: $3.12" sat
  // in a list a reader could take for a loss.
  // The unit is its own span, so the 120px Market column breaks before it and keeps "Cost: $3.12" whole (.run-cred).
  const CRED = '<span class="run-cred"> in\u00a0credits</span>';
  const runSpent = (r) => r.spent_usd == null ? '' : runLive(r) ? `Spent so far: ${spentSoFar(r.spent_usd, 'nothing yet')}${+r.spent_usd > 0 ? CRED : ''}` : `Cost: ${usd(r.spent_usd)}${CRED}`;
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
  // A session's passes as its page counts them: its counter less those a later check left uncleared
  // (`not_cleared` from the server: the one-time holdout then failed, or the diversification check held it
  // back, stamped Missed final test and Held back on its page). The row read "2 of 10 passed" over a
  // session whose page said "Passed 1" and "1 not cleared".
  // The Research headline's window: its totals count every session ever (the server's totals).
  const ALL_TIME = 'all time';
  const runPassed = (r) => {
    const all = +r.strategies_passed || 0, fell = Math.min(all, +r.not_cleared || 0);
    return { ok: all - fell, fell };
  };
  // `newest`: the user's newest session. When it ran out of credits its row offers Add credits, under
  // the row (a link can't sit inside the row's own link); older ones only say so.
  // Its market, then what it cost: in the desktop Market column the cost takes its own line, whole ("Cost:" ended
  // one line and "$0.06" began the next), and the example's note sits under its title, where a session's number
  // goes, instead of cut to "An example Tau ran f…" in that 120px column.
  function runRow(r, newest) {
    const why = RUN_STOP[r.stop_reason] || '', { ok, fell } = runPassed(r);
    // A `stopped` session (interrupted, or a market with nothing to research yet) reads like a
    // finished one: it fell through to a red "Failed". The uncleared passes are their own line, outside the
    // green ratio: "0/2 passed, 1 not" broke before "cleared" and read as if nothing had passed.
    const late = runLate(r);
    const state = late ? lateLabel(late) : r.status === 'running' ? 'Researching'
      : r.status === 'queued' ? 'Waiting'
      : r.status === 'succeeded' || r.status === 'stopped' ? `<span class="${ok ? 'gain' : ''}"><span class="run-ratio" aria-label="${num(ok)} of ${num(r.hypotheses_tried)}"><b class="run-passed">${num(ok)}</b><span aria-hidden="true">/</span><b class="run-tested">${num(r.hypotheses_tried)}</b></span> <span class="run-denominator">passed</span></span>${fell ? `<span class="run-denominator run-fell">+${num(fell)} passed, not cleared</span>` : ''}${r.status === 'succeeded' && why ? `<span class="run-why">${why}</span>` : ''}`
      : r.status === 'paused' ? 'Paused'
      : r.status === 'cancelled' ? (why || 'Cancelled') : `<span class="loss">${why || 'Failed'}</span>`;
    // status band: a thin color rule so passed/void/failed reads at a glance; only a real error is `fail`
    const band = r.status === 'succeeded' ? (ok ? 'ok' : 'void') : r.status === 'failed' ? 'fail' : (r.status === 'cancelled' || r.status === 'stopped') ? 'void' : 'live';
    // The example's note sits under its title: in the narrow Market column it was cut to "An example Tau ran f…".
    const card = `<a class="run-card ${band}" href="/research/${r.id}">
      <span class="run-identity"><span class="run-title" title="${esc(sessionTitle(r))}"><b>${esc(sessionTitle(r))}</b>${runTag(r)}${r.example ? `<span class="run-note">${EXAMPLE_NOTE}</span>` : ''}${r.error ? `<span class="run-error">${esc(r.error)}</span>` : ''}</span><span class="run-meta-group">${sessionNo(r) ? `<span class="run-id">${sessionNo(r)}</span>` : ''}<span class="run-meta"><span class="vh">Market </span>${esc(marketShort(r.market))}${!r.example && r.spent_usd != null ? `<span class="run-cost"><span class="run-sep">${SEP}</span>${runSpent(r)}</span>` : ''}</span><span class="run-when"><span class="vh">Created </span>${when(r.created_at)}</span></span></span><span class="run-state"><span class="vh">Outcome </span>${state}</span></a>`;
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
    const sizing = `$${sz.stake != null ? sz.stake : 5} per trade${SEP}up to ${sz.max_positions != null ? sz.max_positions : 20} at once`;
    const codeFig = (src) => `<figure class="hx-code"><figcaption>Strategy code <span>Python${SEP}research sandbox only</span></figcaption><pre><code>${esc(src)}</code></pre></figure>`;

    // Code strategy: an arbitrary fitted model in the sandbox, not threshold fields. Show it as
    // one, keep the real source (and note the frozen fit, if the research run froze params in).
    if (spec.code) {
      const fit = (spec.params != null && spec.params !== '') ? `${SEP}fit on research, frozen` : '';
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
        ? `<dt>Fitted weights</dt><dd class="hx-weights">${feats.map((f, i) => `<span class="hx-feat">${esc(f)}</span> ×${coef[i].toFixed(2)}`).join(SEP)}${typeof m.intercept === 'number' ? `${SEP}intercept ${m.intercept.toFixed(2)}` : ''}</dd>`
        : '';
      return `<dl class="hx-spec">
        ${side}
        <dt>Signal</dt><dd class="hx-model">${signal}${edge ? ' — enter when ' + edge : ''}</dd>
        ${weights}
        ${row('Only when', bounds.join(SEP))}
        ${row('Exit', exit.join(SEP) || 'hold to settlement')}
        ${row('Regime filter', filters)}
        ${row('Sizing', sizing)}</dl>`;
    }

    // Plain DSL threshold strategy (house GBM / rules) — unchanged.
    const entry = [];
    if (edge) entry.push(`edge ≥ ${pct(e.min_edge, false)}`);
    entry.push(...bounds);
    return `<dl class="hx-spec">
      ${side}
      ${row('Enter when', entry.join(SEP) || 'any priced contract')}
      ${row('Exit', exit.join(SEP) || 'hold to settlement')}
      ${row('Regime filter', filters)}
      ${row('Sizing', sizing)}</dl>`;
  }

  // The gatekeeper's numbers for the reader (their own result) — never fed back to the generator. Its range
  // is the bootstrap's at gatekeeper.ALPHA (0.10), the 90% range the gate and the strategy page name: it read
  // "95% CI". The average per trade after fees leads, as on the strategy page: the card showed no result.
  // Each figure is named in plain words with its term of art after it, and says what it measures: in the
  // card's info bubble, and on a phone in a line under the figure (.hx-why), since a bubble there
  // covers the number it explains.
  function statGrid(s) {
    if (!s) return '';
    const num = (v, dp) => (v == null || typeof v !== 'number') ? null : v.toFixed(dp == null ? 2 : dp);
    const p = (v) => v == null ? null : (v < 0.001 ? '<0.001' : num(v, 3));
    const cells = [];
    const add = (k, v) => { if (v != null && v !== '') cells.push(`<div><dt>${GLOSSARY[k] ? gl(GLOSSARY[k][0], k) : k}</dt><dd>${v}</dd>${GLOSSARY[k] ? `<dd class="hx-why">${GLOSSARY[k][1]}</dd>` : ''}</div>`); };
    add('Trades', s.n_trades != null ? String(s.n_trades) : null);
    add('Avg per trade after fees', typeof s.mean_net_return === 'number' ? pct(s.mean_net_return) : null);
    add('pvalue', p(s.p_value));
    add('dsr', num(s.dsr));
    add('sharpe', num(s.sharpe));
    if (s.ci && (s.ci.lo != null || s.ci.hi != null)) add('range90', `${pct(s.ci.lo, false)}…${pct(s.ci.hi, false)}`);
    add('placebo', p(s.placebo_p));
    if (s.max_drawdown != null) add('drawdown', usd(-Math.abs(s.max_drawdown), true));
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
      ? `<span class="say-stat">On the history it searched: ${usd(ins.pnl, true)}${SEP}${num(ins.trades)} trade${ins.trades === 1 ? '' : 's'}${glo('insample')}</span>` : '';
    const home = [mechHtml(d.mechanism), specHtml(d.spec),
      d.falsification ? `<p class="hx-fine"><b>Falsified if</b> ${esc(d.falsification)}</p>` : '',
      d.negative_control ? `<p class="hx-fine"><b>Placebo that should fail</b> ${esc(d.negative_control)}</p>` : ''].filter(Boolean).join('');
    li.innerHTML = `${logTime(ev.created_at)}<span class="node" aria-hidden="true"></span><div class="say">
      <div class="hx-head"><b class="say-title">${esc(title)}</b><span class="hx-stamp pending" data-stamp>Testing</span></div>
      ${d.thesis ? `<span class="say-sub">${esc(d.thesis)}</span>` : ''}${stat}
      ${home ? `<details class="hx-more"><summary>Method &amp; specification</summary><div class="hx-body">${home}</div></details>` : ''}
      <div class="hx-review" data-review hidden></div></div>`;
    const stampEl = li.querySelector('[data-stamp]');
    const reviewEl = li.querySelector('[data-review]');
    const strip = (s, re) => (s || '').replace(re, '');
    // What follows a verdict's or the skeptic's tag is a sentence of its own: with the stamp and title cut off, the
    // example session's verdict read "no edge, so nothing to deploy." and a review "the overshoot has…" (walked 2026-10-28).
    const upper1 = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
    return {
      li, title,
      challenger(e2) {
        const dec = (e2.data || {}).decision || 'review';
        const reason = strip(strip(e2.message, /^Challenger\s+\w+\s+[-–]\s*/i), new RegExp('^' + title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ':\\s*'));
        reviewEl.hidden = false;
        reviewEl.insertAdjacentHTML('beforeend', `<p class="hx-crit"><span class="hx-tag">Skeptic’s review${SEP}${esc(REVIEW_SAID[dec] || dec)}</span>${esc(upper1(reason))}</p>`);
      },
      verdict(e2) {
        const dd = e2.data || {};
        const cls = dd.status === 'passed' ? 'pass' : (dd.status === 'rejected' || dd.status === 'abandoned') ? 'rej' : 'void';
        const label = dd.status === 'passed' ? 'Passed' : dd.status === 'rejected' ? 'Rejected' : dd.status === 'abandoned' ? 'Dropped' : 'Void';
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
        const why = whyFailedHtml(dd.why_failed);  // the gates it missed replace the gatekeeper's raw note
        // The server's plain sentence stands in for a message written for the ledger ("validation
        // verdict is gatekeeper-held (classification=...)"); a dropped idea says why it was dropped.
        const said = upper1(dd.note || (dd.status === 'abandoned' && dd.why) || tail);
        reviewEl.hidden = false;
        reviewEl.insertAdjacentHTML('beforeend', `<div class="hx-verdict"><span class="hx-tag ${cls}">Verdict</span>${why ? why : said ? `<span class="hx-vtext">${esc(said)}</span>` : ''}${statGrid(dd.stats)}</div>`);
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
    return `<div class="hx-verdict"><span class="hx-tag ${ok ? 'pass' : 'void'}">${name}${SEP}${ok ? 'held' : dd.skipped ? 'not run' : 'missed'}</span>${why || (dd.note ? `<span class="hx-vtext">${esc(dd.note)}</span>` : '')}</div>`;
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
  // Run state and source-event age are reported by the observatory above the log.
  // The second model that reads each idea before its test, by what it does (the verdicts already say
  // "The skeptic's review didn't pass it"), and its call in words, not the agent's codes.
  const REVIEW_SAID = { approve: 'approved', revise: 'asked for changes', reject: 'turned it down' };
  function runFeed(section) {
    const log = section.querySelector('.log');
    const jump = section.querySelector('.jumplatest');
    let unseen = 0, first = true, appended = 0, stateSeen = false;
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
      state(st) {
        // A saved completed run reads as a document. A live run keeps its
        // existing scroll viewport on completion so reading/jump state survives.
        if (!stateSeen) section.classList.toggle('is-complete', st === 'done');
        stateSeen = true;
        if (st === 'done') { sealThink(); settlePending(log); }
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
  const RSI_STAGES = [['explore', 'Explore'], ['backtest', 'Backtest'], ['gate', 'Validate'], ['dream', 'Refine']];
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
  // The engine's own words for its self-tuning step ("Dreaming:", "Research policy evolved:"), said plainly.
  const plainDream = (m) => String(m || '').replace(/^Dreaming:/, 'Tuning how it searches:').replace(/^Research policy evolved:/, 'Search improved:');
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
    let waitHidPhase = false, phaseStep = false;
    let doneRun = null;
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
      // An overdue run's wait line takes the phase line's place: a queued one's says what "Waiting for the
      // agent to start." said, and more; a silent one's last phase ("Working") sat over "No word from the agent".
      if (late) { phaseEl.hidden = true; waitHidPhase = true; }
      else if (waitHidPhase) { waitHidPhase = false; phaseEl.hidden = !['queued', 'running', 'paused'].includes(runState) || phaseStep; }
      if (late && runState === 'queued') { liveWrap.className = 'rsiobs-live is-stall'; liveText.textContent = 'Waiting ' + waitSpan(w.seconds); return; }
      if (late) { host.classList.add('is-quiet'); liveWrap.className = 'rsiobs-live is-stall'; liveText.textContent = 'Silent ' + waitSpan(w.seconds); return; }
      if (runState === 'paused') { liveWrap.className = 'rsiobs-live is-paused'; liveText.textContent = 'Paused'; return; }
      if (runState === 'queued') { liveWrap.className = 'rsiobs-live is-wait'; liveText.textContent = 'Queued'; return; }
      if (runState !== 'running') { liveWrap.className = 'rsiobs-live is-done'; liveText.textContent = doneRun ? runDoneText(doneRun) : runState === 'succeeded' ? 'Finished' : runState === 'cancelled' ? 'Stopped by you' : 'Stopped'; return; }
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
        doneRun = run || doneRun;  // the badge of a finished run says why it stopped, as the Status figure does
        const firstUpdate = initialUpdate;
        initialUpdate = false;
        runState = state || runState;
        (events || []).forEach((ev) => {
          const d = ev.data || {};
          lastAt = Date.parse(ev.created_at) || Date.now();   // newest event's own clock drives liveness
          const kind = ev.kind === 'verdict' && !d.title ? 'step' : ev.kind;
          let ph = RSI_PHASE[kind];
          if (!ph && /^(Dreaming:|Research policy evolved:)/.test(ev.message || '')) ph = ['dream', plainDream(ev.message).split(':')[0]];
          if (ph) { stage = ph[0]; fired.add(stage); phaseEl.textContent = ph[1]; phaseEl.hidden = phaseStep = kind === 'step'; }
          else if (kind) { phaseEl.textContent = RSI_SAID[kind] || prettyKind(kind); phaseEl.hidden = phaseStep = false; }  // unknown kind: keep stage lit, show a readable label
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
  // rows are current; a set-size session also says how many it will test. A pass a later check left
  // uncleared (`verdict`: Missed final test, Held back) keeps the status "passed" and its place in the run's
  // counter, so "Passed 3" sat over ideas stamped otherwise below: it is counted apart, as not cleared.
  function runCountFigs(r, active, tried, strategies) {
    const n = Math.max(+r.hypotheses_tried || 0, tried || 0);
    const cap = active && !r.run_forever && +r.max_hypotheses ? `of up to ${num(r.max_hypotheses)}` : '';
    const fell = (strategies || []).filter((s) => s.status === 'passed' && s.verdict).length;
    const all = active ? (strategies || []).filter((s) => s.status === 'passed').length : r.strategies_passed;
    const passed = all == null ? null : Math.max(0, all - fell);
    return fig('Tested', num(n), { small: cap }) + fig('Passed', passed == null ? '—' : num(passed), { small: fell ? `${num(fell)} not cleared` : '' });
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
  // An idea that passed validation and then missed its one-time locked holdout keeps the status "passed", and
  // so does one the diversification check after the holdout held back; a probation idea held back after
  // passing on paper keeps its Void. The server says which (`verdict`) and sends what it missed or what held
  // it back (later_missed, the lines its strategy page shows). The page said "Passed: … Open it to deploy it
  // on paper" over a final test it had failed, and over a pass the gatekeeper didn't clear to trade.
  const laterLines = (s) => (Array.isArray(s.later_missed) ? s.later_missed : []);
  const laterMissed = (s) => s.verdict === 'missed_final' && laterLines(s).length > 0;
  const heldBack = (s) => s.verdict === 'held_back';
  const cleared = (s) => s.status === 'passed' && !s.verdict;
  const lcFirst = (t) => String(t).charAt(0).toLowerCase() + String(t).slice(1);
  const heldWhy = (s) => (laterLines(s).length ? esc(lcFirst(laterLines(s)[0].label)) : 'too similar to a strategy you already run');
  // What the autopilot does next, at the end of a session it started: the page ended on "Try another idea"
  // as if the reader had to. A finished session hands straight back to the autopilot, which starts the next
  // one itself (worker.enqueue_review_after_research, and the research floor when nothing has started for a
  // while). Shown only while the switch is on, and syncApCopy follows a flip.
  const apNext = (r) => +r.by_autopilot && !r.example ? ` <span data-ap-next${S.me && S.me.user && S.me.user.autopilot ? '' : ' hidden'}>The autopilot takes these results into its next ideas and starts its next session on its own.</span>` : '';
  function runNext(r, strategies) {
    if (r.example) return `<p class="run-next">That’s what a session looks like. <a class="btn primary" href="/research?new=1">Describe your own idea</a></p>`;
    const passed = (strategies || []).filter(cleared);
    const fell = (strategies || []).filter(laterMissed), held = (strategies || []).filter(heldBack);
    const named = (xs) => xs.slice(0, 3).map((s) => `<a href="/strategies/${s.id}">${esc(s.title)}</a>`).join(', ');
    const fellLine = [fell.length ? `${named(fell)} passed ${fell.length === 1 ? 'its' : 'their'} first test on unseen data, then missed the one-time final test (${esc(lcFirst(fell[0].later_missed[0].label))}).` : '',
      held.length ? `${named(held)} ${held.length === 1 ? 'was' : 'were'} held back after passing ${held.length === 1 ? 'its' : 'their'} tests: ${heldWhy(held[0])}, so ${held.length === 1 ? 'it isn’t' : 'they aren’t'} cleared to trade.` : ''].filter(Boolean).join(' ');
    const nothing = fellLine ? 'Nothing cleared every check' : 'Nothing passed';
    const credits = r.out_of_credits ? 'It stopped when your credits ran out. <a href="/billing">Add credits</a>, then start a new session to keep researching. ' : '';
    if (passed.length) {
      const links = passed.slice(0, 3).map((s) => `<a href="/strategies/${s.id}">${esc(s.title)}</a>`).join(', ');
      const more = passed.length > 3 ? ` and <a href="/strategies?status=passed">${passed.length - 3} more</a>` : '';
      // The autopilot deploys what it finds on paper itself, and its finished session still said "Open it
      // to deploy it on paper": the strategy page then warned that a second copy doubles the positions.
      const deployed = passed.filter((s) => s.deployed).length;
      // Before its next check-in the autopilot hasn't deployed them yet, and the line asked for a deploy
      // by hand all the same. The server marks the ones it will put on paper itself (autopilot_next).
      const auto = passed.filter((s) => !s.deployed && s.autopilot_next).length;
      const way = deployed === passed.length ? ` ${passed.length === 1 ? 'It is' : 'They are'} already deployed. <a href="/deploy">See ${passed.length === 1 ? 'it' : 'them'} on Deploy</a>.`
        : auto && deployed + auto === passed.length ? ` ${deployed ? `${num(deployed)} ${deployed === 1 ? 'is' : 'are'} already deployed; the autopilot puts the ${auto === 1 ? 'other' : 'others'}` : `The autopilot puts ${auto === 1 ? 'it' : 'them'}`} on paper itself at its next check-in, so there is nothing for you to deploy. <a href="/deploy">Deploy</a> shows ${auto === 1 ? 'it' : 'them'} once ${auto === 1 ? 'it is' : 'they are'} there.`
        : deployed ? ` ${num(deployed)} ${deployed === 1 ? 'is' : 'are'} already deployed; open another to deploy it on paper.`
        : ` Open ${passed.length === 1 ? 'it' : 'one'} to deploy it on paper.`;
      return `<p class="run-next">${credits}${passed.length === 1 ? 'Passed' : passed.length + ' passed'}: ${links}${more}.${way}${fellLine ? ' ' + fellLine : ''}</p>`;
    }
    // A failed or cancelled session said nothing: the reason sat in a folded log, the way on nowhere.
    // The server's reason is written for the customer; one that already says the session stopped
    // stands alone ("…stopped on an error. …so the session stopped.").
    if (r.status === 'failed') return `<p class="run-next">${r.error && /\bstopped\b/.test(r.error) ? esc(r.error) : `This session stopped on an error.${r.error ? ' ' + esc(r.error) : ''}`}${apNext(r)} <a href="/research?new=1">Start a new session</a></p>`;
    // In the status figure's and the list's words ("Stopped by you"): it said "cancelled" right under it.
    if (r.status === 'cancelled') return `<p class="run-next">You stopped this session before it finished.${(strategies || []).length ? ' The ideas it tested are listed below.' : ''} <a href="/research?new=1">Try another idea</a></p>`;
    const none = !(strategies || []).length;
    if (credits) return `<p class="run-next">${credits}${none ? 'No strategy reached the checks before then.' : `${fellLine ? fellLine + ' ' : ''}${nothing} before then; each strategy below says which check it missed.`}</p>`;
    if (none && (r.status === 'succeeded' || r.status === 'stopped')) return `<p class="run-next">${runEmpty(r)}${apNext(r)} <a href="/research?new=1">Try another idea</a></p>`;
    if (r.status === 'succeeded' || r.status === 'stopped') return `<p class="run-next">${fellLine ? fellLine + ' ' : ''}${nothing} this time. Most ideas don’t. Each strategy below says which check it missed and what to try next.${apNext(r)} <a href="/research?new=1">Try another idea</a></p>`;
    return '';
  }
  // The foot of a finished session. The way on sat only above the list and the log: the example's
  // log ended on its last line saying to describe a real idea, and a session where nothing passed
  // ended on its last missed idea. The example's goes under the log's last line, the others under
  // the last strategy card. Plain buttons: the line above keeps the page's one primary action.
  function runEnd(r, strategies) {
    if (r.example) return `<p class="run-end"><a class="btn" href="/research?new=1">Describe your own idea</a></p>`;
    if (r.status !== 'succeeded' && r.status !== 'stopped') return '';
    if (r.out_of_credits) return '<div class="run-end"><a class="btn" href="/billing">Add credits</a></div>';
    if ((strategies || []).some(cleared)) return '';
    return `<div class="run-end"><a class="btn" href="/research?new=1">Try another idea</a>${apNudge('Rather not write ideas yourself?', 'and it picks ideas and researches them on its own, on paper.')}</div>`;
  }
  async function viewRun(id) {
    shell('/research', '<div class="run-header"><div id="runboard">' + boardTitle('Research run') + '</div><span id="runact"></span></div><dl class="figures measure" id="runfigs" style="margin-top:14px"></dl><div id="runnext"></div><p class="stale-note" id="run-stale" role="status"></p>', `
      <div id="flash"></div>
      <section class="run-artifacts" id="run-artifacts" hidden></section><div id="runend"></div>
      <div id="rsibox"></div>
      <div id="rsiobs" class="rsiobs"></div>
      <details class="run-history" id="run-history" open><summary class="section-head"><h2>Agent log</h2>${ICON.chev}</summary>${tzName() ? `<p class="hint" style="margin:0 0 8px">Times are ${esc(tzName())}.</p>` : ''}
        <div class="runfeed" id="runfeed"><ol class="log stream" id="log" aria-live="polite" aria-label="Agent reasoning log"><li class="log-empty" data-empty>Waiting for the first event.</li></ol><button class="jumplatest" id="jumplatest" type="button" hidden>new ↓</button></div><div id="runend-log"></div></details>`);
    let after = 0, tried = 0, runActive = true, loaded = false, outOfCredits = false;
    const pauses = { ms: 0, since: null, last: null };
    // A long session's strategy cards (40+, a screen each on a phone) buried the agent log under
    // them: the first few show, the rest behind "Show all". On a phone eight cards were still ~2,000px
    // (a run-until-stopped session's "Research progress" and log sat four screens down), so it shows four.
    const STRAT_SHOW = phone() ? 4 : 8;
    let showAllStrats = false;
    const whyBySid = new Map();  // strategy id -> the gates its verdict missed, kept across polls
    const stream = runFeed(root.querySelector('#runfeed'));
    const obs = rsiObservatory(root.querySelector('#rsiobs'));
    root.querySelector('#run-artifacts').addEventListener('click', (e) => { if (e.target.closest('[data-allstrats]')) { showAllStrats = true; load(); } });
    const load = async (cfg) => {
      const d = await api(`/api/runs/${id}?after=${after}`, undefined, cfg);
      const r = d.run;
      const active = r.status === 'running' || r.status === 'queued' || r.status === 'paused';
      runActive = active;
      (d.events || []).forEach((ev) => {
        after = Math.max(after, ev.id); if (ev.kind === 'hypothesis') tried++;
        runPauses(pauses, ev);
        if (runOutOfCredits(ev)) outOfCredits = true;
        const dd = ev.data || {};
        if (ev.kind === 'verdict' && dd.strategy_id != null && Array.isArray(dd.why_failed) && dd.why_failed.length) whyBySid.set(dd.strategy_id, dd.why_failed);
      });
      r.out_of_credits = outOfCredits && !active;
      // The 2s poll repaints only what changed: rewriting the same title and figures each time made
      // the phone lay the page out again (and the autopilot pill re-check what it covers).
      paint(root.querySelector('#runboard'), boardTitle(sessionTitle(r), `${esc(marketShort(r.market))}${SEP}${runKind(r)}${r.example ? SEP + EXAMPLE_NOTE : runSetup(r) ? SEP + runSetup(r) : ''}`));
      const worked = runWorked(r, pauses);
      const late = r.wait && r.wait.overdue ? r.wait : null;
      const statusText = late ? (late.state === 'queued' ? 'Waiting ' : 'Silent ') + waitSpan(late.seconds)
        : r.status === 'queued' ? 'Waiting'
        : r.status === 'paused' ? 'Paused'
        : r.status === 'running' ? 'Researching'
        : runDoneText(r);
      paint(root.querySelector('#runfigs'),
        fig('Status', statusText) +
        fig('Time', worked == null ? (active ? 'Not started yet' : 'Never started') : waitSpan(worked), { small: pauses.ms || pauses.since != null ? 'not counting time paused' : '' }) +
        (r.spent_usd != null ? fig(active ? 'Spent so far' : 'Cost', active ? spentSoFar(r.spent_usd) : usd(r.spent_usd), { small: r.example ? 'free: Tau ran it for you' : 'from your credits' }) : '') +
        runCountFigs(r, active, tried, d.strategies));
      const next = root.querySelector('#runnext');
      paint(next, active ? '' : runNext(r, d.strategies));
      // Painted only when it changes, so a repaint never undoes the autopilot line's "on" note.
      const endHtml = active ? '' : runEnd(r, d.strategies);
      [['#runend', r.example ? '' : endHtml], ['#runend-log', r.example ? endHtml : '']].forEach(([sel, html]) => {
        const el = root.querySelector(sel);
        if (el && el.dataset.h !== html) { el.dataset.h = html; el.innerHTML = html; }
      });
      // Passed ideas lead the list: a long session's one pass sat mid-way down 40 cards on a phone.
      // An idea dropped while it was built never becomes a strategy, and one still being tested has none yet:
      // "Tested 5" sat over "Strategies 4" with nothing to say why.
      const gapN = Math.max(+r.hypotheses_tried || 0, tried) - (d.strategies || []).length;
      const gap = gapN > 0 ? `${num(gapN)} more idea${gapN === 1 ? '' : 's'} ${active ? 'still being tested' : 'dropped before testing'}.` : '';
      const artifacts = root.querySelector('#run-artifacts'), strategies = (d.strategies || []).slice().sort((a, b) => cleared(b) - cleared(a));
      const focusedArtifact = artifacts.querySelector('a:focus')?.getAttribute('href');
      artifacts.hidden = !strategies.length;
      const artifactHtml = strategies.length ? `<div class="sect-head"><h2>Strategies <span class="section-count">${num(strategies.length)}</span></h2>${gap ? `<p class="hint">${gap}</p>` : ''}</div>${strategyTable(strategies.slice(0, showAllStrats ? undefined : STRAT_SHOW).map(s => strategySlip(s, undefined, { inRun: true, missed: laterMissed(s) || heldBack(s) ? laterLines(s) : s.status === 'passed' ? null : whyBySid.get(s.id) })).join(''), false, true)}${!showAllStrats && strategies.length > STRAT_SHOW ? `<button type="button" class="btn small" data-allstrats style="margin-top:12px">Show all ${num(strategies.length)}</button>` : ''}` : '';
      // Compared with what was last written, not with innerHTML: the browser's serialization never matched
      // the template (&nbsp;, quoting), so the table was rebuilt every 2s.
      paint(artifacts, artifactHtml);
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
        paint(rsibox, `<details class="rsidisc"${expanded ? ' open' : ''}><summary class="rsidisc-cap">How research works ${d.rsi.evolved ? '<span class="rsi-tag">Evolved</span>' : '<span class="rsi-tag quiet">Self-tuning</span>'}<span class="pipechev" aria-hidden="true">${ICON.chev}</span></summary><div class="rsidisc-body">
          ${d.rsi.evolved
            ? `<p>This agent <b>rewrote its own search policy</b> from your history — and it beats the default.</p>
               ${d.rsi.summary ? `<p class="rsi-what"><b>What it changed:</b> ${esc(d.rsi.summary)}</p>` : ''}
               <p class="rsi-last">Generalization score ${delta}${d.rsi.evolved_at ? `${SEP}adopted ` + when(d.rsi.evolved_at) : ''} <span class="rsi-note">(higher = catches more real out-of-sample winners, scored over shuffled orderings so it can’t overfit)</span></p>`
            : `<p>The agent is <b>self-tuning</b>: after each research cycle it tries new ways of choosing which ideas to test, and keeps one only if it would have found more real winners in your own history (scored over shuffled orderings, so it can’t overfit).</p>
               ${d.rsi.last_dream ? `<p class="rsi-last"><b>Last check${d.rsi.last_dream_at ? SEP + when(d.rsi.last_dream_at) : ''}:</b> ${esc(d.rsi.last_dream)}</p>` : `<p class="rsi-last">No check yet. The first one runs at the end of a session, once at least ${d.rsi.min_history || 12} ideas have been tested.</p>`}`}
          </div></details>`);
        if (focused) rsibox.querySelector('summary').focus({ preventScroll: true });
      }
      runControls(root.querySelector('#runact'), id, r.status, load);
      stream.push(d.events);
      stream.state(active ? r.status : 'done');
      obs.push(d.events, r.status, r);
      if (!active) clearTimers();
    };
    await load();
    if (runActive) poll(load, 2000, 'run-stale');
  }
  const DIR_BRIEF = (k) => ((S.me.directions.find((d) => d.key === k)) || { brief: '' }).brief;

  return {viewResearch, viewRun};
});
