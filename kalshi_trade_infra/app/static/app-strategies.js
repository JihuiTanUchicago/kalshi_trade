/* Tau's strategy pages: the list, and one strategy with its research paper.
   Fetched on first use (pageLoad in app.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns. */
window.TauPage('strategies', (T) => {
  'use strict';
  const {
    actionLink, announce, api, ApiError, apNudge, armed, BEHIND, boardTitle, bookName, btCheckLine, bulkDeployable, busy,
    catOrder, cents, chartWidth, CODE_RESEARCH_ONLY, contractLink, contractName, DEMO_BOOK, demoCashRead, demoHealthLine, DEP_DONE, depIdle,
    depActed, depSaid, depWrite, dirLabel, equityChart, errText, esc, EXAMPLE_NOTE, EXAMPLE_TAG, exitWord, fig, flash, fmt0, fold, fundsLinked,
    gl, glo, go, ICON, isPerpetual, kalshiRef, liveOpen, liveWaitMark, loadFail, loading, mark, marketKalshiUrl, marketLabel, marketShort, mdLite,
    money, notice, num, overDays, paperAgain, PAPER_NET, pct, PERPS_SCENARIO, refreshed, registry, render, researchBadge,
    researchOnly, roadDays, root, rpUnderwater, S, settleAt, shell, slipEst, smooth, statusMark, strategySlip, strategyTable,
    tone, tradePrice, usd, when, whyFailedHtml
  } = T;

  // ---------- strategy research paper (RESEARCH_PIPELINE_DESIGN.md §D) ----------
  // Charts are inline SVG built here (CSP is script-src 'self'; no inline <script>).
  // Phase colours reuse Kursbuch tokens: in-sample = muted ink, validation = ink,
  // holdout = signal red (the one decisive, one-time forward test). Every colour is
  // paired with a text label, never carried by colour alone.
  // A per-trade net return (net P&L over what the trade cost) as a percent of its stake: the unit the
  // gatekeeper judges and the "What it missed" lines use. It read as cents ("+3.10¢"), which it isn't.
  const rpRet = (v) => (v == null ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(2) + '%');
  // Under the equity chart while its demo-replay line loads (seconds on a cold server): the rest of the
  // page is already drawn, and this says the chart has one more line coming.
  const DEV_PENDING = (win = 'unseen') => `<p class="hint dev-pending" id="dev-pending"><span class="skeleton" aria-hidden="true"></span>Replaying the ${win} window against Kalshi’s demo book…</p>`;
  const rpProb = (v, d = 3) => (v == null ? '—' : Number(v).toFixed(d));
  const rpInt = (v) => (v == null ? '—' : num(v));
  const rpText = (v) => esc(v == null ? '' : String(v));
  const rpHuman = (k) => String(k).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  // The gatekeeper's pre-registration names its metric and test in code words; say them plainly.
  const rpPlain = (t) => String(t).replace(/\bmean_net_return_per_trade\b/g, 'average net return per trade, after fees')
    .replace(/\bstationary_bootstrap( one-sided)?/g, (m, one) => (one ? 'one-sided ' : '') + 'bootstrap test (resamples its trades in blocks)').replace(/\balpha from\b/g, 'significance bar from')
    .replace(/\b([a-z]+)_([a-z_]+)\b/g, (m) => m.replace(/_/g, ' '));
  // The pre-registration's cost assumptions as the agent stores them (agent.py): every Kalshi strategy's page read
  // "Fee: kalshi_taker · Fill: ask/bid". Said in words; a value with no words here reads as rpPlain says it.
  const RP_COST = { kalshi_taker: 'Kalshi’s taker fee on every fill', 'ask/bid': 'buys at the ask, sells at the bid',
    next_open: 'the next bar’s open', finalized_payments_as_cost_only: 'settled funding payments, counted only as a cost' };
  const rpCost = (v) => (typeof v === 'string' ? RP_COST[v] || rpPlain(v) : String(v));
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
      note = `<div class="cap">Average net return per trade, as % of its stake. The holdout’s is ${shr >= 0 ? shr + '% smaller' : Math.abs(shr) + '% larger'} than validation’s — ${shr >= 100 ? 'the edge did not hold up on fresh data' : shr >= 40 ? 'heavy shrinkage, a sign the validation edge was partly luck' : 'it held up on fresh data'}.</div>`;
    }
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Validation versus locked holdout average net return per trade">
      <line x1="${L}" x2="${W - R}" y1="${zero.toFixed(1)}" y2="${zero.toFixed(1)}" stroke="var(--rule-2)"/>${cells}
    </svg>${note}`;
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

  function rpConclusion(cls, onPaper) {
    // A probation strategy's forward evidence is its one paper judgment, not the locked holdout: its page
    // said it "held up on the locked holdout", which it never faced.
    if (onPaper && cls === 'forward_validated') return ['good', 'Forward-validated on paper. It fell short on validation, then passed its one pre-registered judgment on its own paper trades.'];
    if (onPaper && cls === 'deployment_candidate') return ['good', 'Deployment candidate. It passed its one pre-registered judgment on its own paper trades, and is different enough from your deployed strategies to add something new.'];
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
    if (exp.cost_assumptions && typeof exp.cost_assumptions === 'object') pre.push(['Cost assumptions', Object.entries(exp.cost_assumptions).map(([k, v]) => `${rpHuman(k)}: ${rpCost(v)}`).join(' ·\u00a0')]);
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
        ])}<div class="cap">Running total of each trade’s net return, counted in stakes: +2× means it made twice what one trade puts in, after fees. Each phase is its own run on data the agent never saw; the dashed divider marks the one-way handoff from validation to the locked holdout.</div></div>
        <div class="rp-fig"><h5>Validation vs holdout</h5>${rpShrinkage(v.mean_net_return, exp.holdout ? exp.holdout.mean_net_return : null)}</div>
        <div class="rp-fig"><h5>Drawdown (underwater)</h5>${rpUnderwater(rpCum(v.equity_curve), null, rpStakes)}<div class="cap">Validation, counted in stakes: the deepest drop from a running high.</div></div>
        <div class="rp-fig wide"><h5>Per-trade return distribution</h5>${rpReturnDist((v.equity_curve || []).map((p) => +p[1]), v.ci_lo, v.ci_hi, v.mean_net_return)}<div class="cap">Bars: the net return of each validation trade, as % of its stake. Shaded band: the 90% bootstrap confidence interval of the mean. Dashed line: the mean. A band entirely right of break-even means the edge clears fees.</div></div>
        <div class="rp-fig wide"><h5>Walk-forward windows</h5>${rpWalkforward(exp.folds)}<div class="cap">The validation window cut into consecutive slices, with each slice’s average net return per trade (as % of its stake) and its trade count. The same sign in most slices is robustness; one slice carrying the whole edge is a warning.</div></div>
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
    const [vtone, words] = rpConclusion(exp.classification, !!(exp.paper && !h));
    const chip = { good: 'on', sig: 'armed', quiet: 'quiet' }[vtone] || '';
    parts.verdict += `<div class="rp-verdict ${vtone}"><span class="mk ${chip}">${esc(rpHuman(exp.classification || 'unknown'))}</span><p>${words}</p></div>`;
    return parts;
  }

  // ---------- strategies ----------
  async function viewStrategies() {
    const q = new URLSearchParams(location.search);
    const f = { status: q.has('status') ? q.get('status') : '', market: q.get('market') || '', q: q.get('q') || '', deployed: q.get('deployed') === '1' ? '1' : '', sort: q.get('sort') === 'best' ? 'best' : '' };
    shell('/strategies', boardTitle('Strategies', 'Every strategy your agents researched. Passed strategies on deployable markets can be deployed; void ones stay here so you can see what didn’t work.') +
      '<dl class="figures measure" id="sfigs" style="margin-top:14px"></dl>', `
      <div class="section-head filters stratfilters">
        <div class="chips" role="group" aria-label="Status">${[['', 'Kept'], ['passed', 'Passed'], ['not_cleared', 'Not cleared'], ['backtest-only', 'Backtest only'], ['failed', 'Void'], ['rejected', 'Rejected']].map(([v, l]) => `<button class="chip" data-f="status" data-v="${v}"${v === 'not_cleared' && f.status !== v ? ' hidden' : ''} aria-pressed="${f.status === v}">${l}</button>`).join('')}
          <button class="chip" data-toggle="deployed" aria-pressed="${f.deployed === '1'}">Deployed</button></div>
        ${(() => { const by = {}; S.me.markets.forEach((m) => (by[m.category] || (by[m.category] = [])).push(m)); const cs = Object.keys(by).sort(catOrder); return `<label class="vh" for="strat-market">Market</label><select class="input strat-mkt" id="strat-market" aria-label="Filter by market"><option value="">All markets</option>${cs.map((c) => `<optgroup label="${esc(c)}">${by[c].map((m) => `<option value="${esc(m.key)}"${f.market === m.key ? ' selected' : ''}>${esc(marketShort(m.key))}</option>`).join('')}</optgroup>`).join('')}</select>`; })()}
        <label class="vh" for="strat-sort">Sort</label><select class="input strat-mkt strat-sort" id="strat-sort" aria-label="Sort strategies">${[['', 'Newest first'], ['best', 'P&amp;L on data it never saw']].map(([v, l]) => `<option value="${v}"${f.sort === v ? ' selected' : ''}>${l}</option>`).join('')}</select>
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
    // "P&L on data it never saw" (highest first: the out-of-sample backtest P&L, gate_explain.step_note's words
    // for that test) orders the whole list server-side (it is paged), and rides in the URL like
    // the filters, so a reload or a shared link keeps it.
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
        slipsEl.innerHTML = loadFail(errText(e));
        slipsEl.querySelector('[data-retry]').onclick = () => load();
        return;
      }
      // A remembered page past the end (the list shrank since) starts again at the first.
      if (sp > 0 && d.matched && !(d.strategies || []).length) { sp = 0; history.replaceState(null, '', location.pathname + location.search.replace(/([?&])page=\d+&?/, '$1').replace(/[?&]$/, '')); return load(); }
      const counts = d.counts || {}, total = counts.total || 0, c = (st) => counts[st] || 0;
      // Under the Deployed toggle every counted strategy passed (only passed ones deploy), so its rate read
      // a meaningless 100%: it is left out there rather than shown.
      const rate = total && !f.deployed ? c('passed') / total : null;
      root.querySelector('#sfigs').innerHTML = fig(gl('Passed', 'passed'), c('passed'), { small: c('not_cleared') ? `${num(c('not_cleared'))} more passed but ${c('not_cleared') === 1 ? 'wasn’t' : 'weren’t'} cleared to trade` : '' }) + fig(gl('Void on unseen data', 'void'), c('failed')) + fig(gl('Rejected in testing', 'rejected'), c('rejected')) +
        // Its denominator said: Research's rate is of every idea tested (most never become a strategy), so the
        // two pages read 8.6% and 12.0% for one account with nothing saying why.
        fig('Pass rate', rate != null ? pct(rate, false) : '—', { small: f.deployed ? 'not with Deployed on: only passed strategies deploy' : rate != null ? `of the ${num(total)} strateg${total === 1 ? 'y' : 'ies'} here` : '' });
      const kept = total - c('failed') - c('rejected');
      root.querySelectorAll('[data-f="status"]').forEach((b) => { const v = b.dataset.v; b.textContent = v ? `${CLABEL[v]} (${c(v)})` : `Kept (${kept})`; if (v === 'not_cleared') b.hidden = !c(v) && f.status !== v; });
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

  // One book's listed deployments summed: the server's exact total (book_totals, the strategies list's
  // own figure) when it sends one. Adding the rows' rounded figures here could read a cent off the list.
  function bookTotal(s, mode, ds) {
    const t = s.book_totals && s.book_totals[mode];
    if (t) return { pnl: +t.pnl || 0, trades: +t.trades || 0, open: +t.open || 0, instant: +t.instant_fills || 0, slip: t.slippage_estimate };
    return { pnl: ds.reduce((a, d) => a + (+d.realized_pnl || 0), 0), trades: ds.reduce((a, d) => a + (+d.closed_trades || 0), 0),
      open: ds.reduce((a, d) => a + (+d.open_positions || 0), 0) };
  }

  // How many of a paper book's `n` closed trades were instant fills (`k`, the server's book_totals.paper.instant_fills,
  // split as the track record splits them): "+$3.80 realized over 2 closed trades" said nothing of the one the track
  // record leaves out. The live check's count of realistic paper trades (paper_evidence) leaves them out too.
  // Display only: what counts toward live is the server's alone.
  const instantNote = (k, n, cls) => (!(k > 0) || !(n > 0) ? '' : `<p class="${cls}">${k >= n
    ? (n === 1 ? 'This trade was an instant fill' : `All ${num(n)} of these trades were instant fills`)
    : `${num(k)} of these ${num(n)} trades ${k === 1 ? 'was an instant fill' : 'were instant fills'}`}, filled whole at the quoted price without the simulated order book. The track record leaves ${k === 1 ? 'it' : 'them'} out, and so does the count of realistic paper trades toward live.</p>`);
  // What the strategy has actually done since it was deployed, per mode (live, demo, paper), from
  // its deployments' realized P&L. The page otherwise shows only the backtest.
  function realRecord(s) {
    // What the same trades would have made at the unseen-data backtest's average, scaled to each
    // deployment's stake, so "is it doing what the test said?" has an answer beside the real P&L.
    const oos = s.out_of_sample, stake = +s.stake;
    // A paused deployment (often paused automatically, and the bell links here) says so and why.
    const pausedLine = (ds) => {
      const p = ds.find((d) => d.status === 'paused');
      return p ? `<p class="real-paused"><b>Paused</b>${(p.status_why || p.status_reason) ? ': ' + fundsLinked(esc((p.status_why || p.status_reason).replace(/\.$/, ''))) + '.' : ''} <a href="/deploy">Resume or remove it on Deploy</a></p>` : '';
    };
    // Paper counts its realistic fills only (each deployment's closed trades less its `instant_fills`), as the
    // server's backtest check and the count toward live do: "2 trades would have made" counted the instant fill
    // the note above says the track record leaves out. A book of instant fills alone has no line.
    const pace = (ds, n) => {
      if (!n || !oos || !(+oos.trades > 0) || !(stake > 0)) return '';
      const per = (+oos.pnl || 0) / +oos.trades;
      const real = (d) => Math.max(0, (+d.closed_trades || 0) - (d.mode === 'paper' ? +d.instant_fills || 0 : 0));
      const m = ds.reduce((a, d) => a + real(d), 0);
      if (!m) return '';
      const exp = ds.reduce((a, d) => a + real(d) * per * ((+d.stake || stake) / stake), 0);
      return `<p class="sub-fig real-pace">At the backtest’s ${!s.experiment && ['passed', 'backtest-only'].includes(s.status) ? 'later-period' : 'unseen-data'} pace, ${m} trade${m === 1 ? '' : 's'}${m < n ? ' on realistic fills' : ''} would have made ${usd(exp, true)}${m < 10 ? ' ·\u00a0too few trades to judge yet' : ''}</p>`;
    };
    // A server that compares each book with the backtest sends backtest_checks; it replaces the pace line.
    const checks = Array.isArray(s.backtest_checks) ? s.backtest_checks : null;
    const order = ['live', 'demo', 'paper'], label = { live: 'Live', demo: 'Demo', paper: 'Paper' }, cls = { live: 'live', demo: 'dep', paper: '' };
    // Which money each line is and what it is net of. Only paper said it ("after Kalshi fees and the spread"):
    // "Demo +$1.16 realized" read like real money and like a figure before fees, and an open position's cost
    // isn't in it. The engine takes every fill's Kalshi fee off a demo or live trade's P&L.
    const BOOK_NET = { live: 'real money, after Kalshi fees', demo: `after Kalshi fees, in ${DEMO_BOOK}: not real money`, paper: PAPER_NET };
    const lines = order.map((mode) => {
      const ds = (s.deployments || []).filter((d) => d.mode === mode);
      if (!ds.length) return '';
      const { pnl, trades: n, open, instant, slip } = bookTotal(s, mode, ds);
      // "deployed Oct 18" stays whole (.nobr): at 390px in Meridian "deployed" ended a line and "Oct 18" began the next.
      const since = ds.map((d) => d.created_at).filter(Boolean).sort()[0];
      return `<p><span class="mk ${cls[mode]}">${label[mode]}</span>${mode === 'live' && ds.some((d) => d.status === 'running') ? liveWaitMark() : ''} ${n ? `${money(pnl)} realized over ${n} closed trade${n === 1 ? '' : 's'}, ${BOOK_NET[mode]}${mode === 'paper' ? glo('paperfills') : ''}` : 'No closed trades yet'}${open ? ` ·\u00a0${open} open, counted once ${open === 1 ? 'it closes' : 'they close'}` : ''}${since ? ` ·\u00a0<span class="nobr">deployed ${when(since)}</span>` : ''}</p>${mode === 'paper' && n && slipEst(slip) ? `<p class="sub-fig real-slip">${slipEst(slip)}</p>` : ''}${mode === 'paper' ? instantNote(instant, n, 'sub-fig real-instant') : ''}${checks ? btCheckLine(checks.find((c) => c.mode === mode), 'p') : pace(ds, n)}${pausedLine(ds)}`;
    }).join('');
    // Removed deployments leave the list (and the lines above) but keep their record: one short line,
    // newest first, each with its own book, dates and realized P&L (books never added together), and,
    // as the lines above, which money it was and what it is net of (BOOK_NET).
    const past = Array.isArray(s.past_deployments) ? s.past_deployments : [];
    // One with no closed trades has no P&L to net of fees: it says so, as the lines above do, and which money
    // it was, instead of "$0.00 over 0 closed trades" with no book.
    const BOOK_MONEY = { live: 'real money', demo: `in ${DEMO_BOOK}: not real money`, paper: 'not real money' };
    const pastFig = (p) => (+p.closed_trades
      ? `${money(p.realized_pnl)} over ${num(p.closed_trades)} closed trade${+p.closed_trades === 1 ? '' : 's'}${BOOK_NET[p.mode] ? `, ${BOOK_NET[p.mode]}` : ''}`
      : `no closed trades${BOOK_MONEY[p.mode] ? `, ${BOOK_MONEY[p.mode]}` : ''}`);
    const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '—');
    // Deployed and removed the same day read "Oct 27–Oct 27" (walked 2026-10-27): one date says it.
    const daySpan = (from, to) => (day(from) === day(to) ? day(from) : `${day(from)}\u2013${day(to)}`);
    const pastLine = past.length ? `<p class="sub-fig past-deps"><b>Past deployments:</b> ${past.slice(0, 3).map((p) => `${label[p.mode] || esc(p.mode)} ${daySpan(p.created_at, p.removed_at)}, ${pastFig(p)}`).join(' ·\u00a0')}${past.length > 3 ? ` ·\u00a0${num(past.length - 3)} earlier` : ''}</p>` : '';
    return lines || pastLine ? `<section class="real-record" aria-label="Since deploying"><h3 class="paper-h">Since deploying</h3>${lines}${pastLine}</section>` : '';
  }
  // Road to live in words, from the checks the server sends (live-readiness): what is left, each with
  // what it has and what it needs, and when the trades, events and hours could be in at the pace it
  // trades (the server's `pace`). Real money never follows on its own: it takes the user's own step.
  // Three places, so a p of 0.104 never reads "0.10" beside "needs 0.10 or lower".
  const roadP = (v) => v == null ? '—' : v < 0.001 ? 'under 0.001' : (+v).toFixed(3);
  // A signed figure in the sentence stays on one line: "(now \u2212$13.56)" broke between the minus and the $ on a phone.
  const roadAmt = (v) => `<span class="amt">${usd(v, true)}</span>`;
  const roadClear = (r) => !!(r.deployment_candidate && r.paper && r.paper.ready);
  function roadLeft(r, s) {
    const p = r.paper, c = p.checks || {}, left = [];
    const more = (have, need, unit) => `${num(Math.max(0, need - have))} more ${unit} (${num(have)} of ${num(need)})`;
    const demoOn = (s.deployments || []).some((d) => d.mode === 'demo' && d.status !== 'stopped');
    if (!r.deployment_candidate) left.push('the gatekeeper’s clearance');
    if (c.realistic_trades === false) left.push(more(+p.trades, +p.trades_needed, 'paper trades'));
    if (c.legacy_pnl === false) left.push(`paper P&amp;L with every fill at $0 or above (now ${roadAmt(p.legacy_pnl)})`);
    if (c.events === false) left.push(more(+p.events, +p.events_needed, 'events'));
    if (c.net_pnl === false) left.push(`net P&amp;L above $0 (now ${roadAmt(p.net_pnl)})`);
    if (c.span === false) left.push(`${num(Math.ceil(p.span_needed_hours - p.span_hours))}h more of record (${num(Math.floor(p.span_hours))}h of ${num(p.span_needed_hours)}h)`);
    if (c.edge === false) left.push(p.p_value == null ? 'the edge test, run once the trades and events are in' : `a clearer edge (p ${roadP(p.p_value)}, needs ${p.p_value_needed.toFixed(2)} or lower)`);
    if (c.recent === false) left.push(`its newer trades above $0 (now ${roadAmt(p.recent_net_pnl)})`);
    if (c.demo === false) {
      left.push(+p.demo_orders < +p.demo_orders_needed ? more(+p.demo_orders, +p.demo_orders_needed, 'demo orders') + (demoOn ? '' : ' on a demo deployment')
        : p.demo_unresolved ? `${num(p.demo_unresolved)} lost demo order${p.demo_unresolved === 1 ? '' : 's'} accounted for`
        : (p.demo_mismatched_tickers || []).length ? 'a demo book that matches the demo exchange'
        : 'a check of its demo book against the demo exchange in the last 24h');
    }
    // A failing check this page doesn't name is said in the server's own words, "the Funds page" linked (fundsLinked).
    if (!left.length && !roadClear(r)) left.push(fundsLinked(esc(p.why || r.blocking || 'a check this page can’t name')));
    return left;
  }
  function roadSummary(r, s, liveWhy, total, apPaper) {
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
        : `It isn’t running on paper, so its record isn’t growing${+p.trades ? `. Its ${num(p.trades)} earlier paper trade${+p.trades === 1 ? '' : 's'} still count` : ''}. ${apPaper ? `<span data-ap-next${S.me.user.autopilot ? '' : ' hidden'}>The autopilot puts it on paper at its next check-in.</span><span data-ap-off${S.me.user.autopilot ? ' hidden' : ''}>Deploy it on paper to add to it.</span>` : 'Deploy it on paper to add to it.'}`}</p>`);
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
  function ladderLines(s, { canDeploy, demoWhy, road, apPaper }) {
    const deps = s.deployments || [];
    // A paused book is still on its rung (deploying it there again would double its positions): it says paused.
    const running = LADDER.filter(([m]) => deps.some((d) => d.mode === m && d.status !== 'stopped'));
    const books = running.map(([m, label, cls]) => {
      const ds = deps.filter((d) => d.mode === m);
      const { trades: n, pnl, instant } = bookTotal(s, m, ds);
      const stats = `${num(n)} closed trade${n === 1 ? '' : 's'} ·\u00a0${money(pnl)} realized${m === 'paper' && n ? `, ${PAPER_NET}` : ''}`;
      // A demo book Kalshi refuses every order for is not "running": it says why, and what to do.
      if (m === 'demo' && s.demo_health) return `<p><span class="mk ${cls}">${label}</span> ${stats} ·\u00a0${demoHealthLine(s.demo_health)}</p>`;
      const runs = ds.some((d) => d.status === 'running');
      // Its demo check is still reading the demo cash (demo_health_pending): not "running" until that is in.
      const state = !runs ? 'paused' : m === 'live' && !liveOpen() ? 'waiting: live trading isn\u2019t open yet, so it places no orders'
        : m === 'demo' && s.demo_health_pending ? 'checking your Kalshi demo account\u2026' : 'running';
      return `<p><span class="mk ${cls}">${label}</span> ${state} ·\u00a0${stats}</p>${m === 'paper' ? instantNote(instant, n, 'hint rung-instant') : ''}`;
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
    if (!next) need = liveOpen() ? 'Top rung: it trades live money.' : 'Top rung: live money, but live trading isn\u2019t open yet, so it places no orders.';
    else if (!canDeploy) need = '';
    else if (next[0] === 'paper') {
      // One the autopilot puts on paper itself says so while the switch is on (syncApCopy follows a flip).
      const on = !!(S.me && S.me.user && S.me.user.autopilot), hand = 'nothing needed. Deploy it on paper below.';
      need = 'Next rung, paper: ' + (apPaper ? `<span data-ap-next${on ? '' : ' hidden'}>the autopilot puts it there at its next check-in.</span><span data-ap-off${on ? ' hidden' : ''}>${hand}</span>` : hand);
    }
    else if (next[0] === 'demo') need = (demoWhy ? 'Next rung, demo: needs your Kalshi demo (sandbox) key on the <a href="/funds#connect-kalshi">Funds page</a>.'
      : s.demo_health ? `Next rung, demo: needs ${esc(s.demo_health.need)}.${actionLink(s.demo_health)}`
        // Its demo cash is being read (demo_health_pending): not yet "nothing needed".
        : s.demo_health_pending ? 'Next rung, demo: checking your Kalshi demo account…' : 'Next rung, demo: nothing needed. Deploy it on demo below.')
      + ' Demo runs the same rules on Kalshi’s sandbox with play money, to prove its orders place, fill and book before live money.';
    else if (road) {
      const left = roadLeft(road, s);
      need = `Next rung, live: ${roadClear(road) ? 'its record clears every check. It trades live money only once you deploy it there' : `${left.length} check${left.length === 1 ? '' : 's'} left, first ${left[0]}`}.`;
    }
    return books.join('') + (need ? `<p class="hint">${need}</p>` : '');
  }
  // A validation pass keeps the status "passed" when a later check fails: the one-time locked holdout, or
  // the diversification check after it. A probation strategy that passed its one paper judgment and was
  // then held back by that check keeps its Void. The server's `verdict` says which, and why_failed names
  // the check (an answer without `verdict` is read from it). The page stamped it Passed, offered Deploy on
  // paper up top and said nothing, or "Passed. It cleared every check", or Void over its validation miss.
  const laterVerdict = (s, missed) => s.verdict || (s.status === 'passed' && missed
    ? (missed[0].gate === 'diversification' ? 'held_back' : 'missed_final') : undefined);
  const heldBack = (s) => s.verdict === 'held_back';
  // The verdict in one line near the top of a strategy page: whether it passed and on what held-out
  // evidence, or the check it missed. The full evidence stays in Verdict, which on a phone is many
  // screens down; a Void strategy's page read "returned $3.10 on unseen data" up top and said why it
  // failed only there.
  function verdictGlance(s, missed) {
    const exp = s.experiment, h = exp && exp.holdout, v = exp && exp.validation, p = exp && exp.paper;
    const lc = (t) => String(t).charAt(0).toLowerCase() + String(t).slice(1);
    let lead, words;
    if (missed && s.status !== 'passed' && heldBack(s)) {
      lead = 'Held back.';
      words = `It fell short on its first test on unseen data, so it went on paper on probation, and passed its one judgment there${p && p.n_trades != null ? ` (${num(p.n_trades)} paper trades)` : ''}, but it is ${lc(missed[0].label)}, so the gatekeeper didn’t clear it to trade. Verdict, below, has what was measured.`;
    } else if (missed && ['failed', 'rejected'].includes(s.status)) {
      lead = s.status === 'failed' ? 'Void.' : 'Rejected.';
      words = `It missed ${missed.length === 1 ? 'a check' : missed.length + ' checks'}: ${lc(missed[0].label)}${missed.length > 1 ? `, and ${missed.length - 1} more` : ''}. Verdict, below, has what was measured and what to try next.`;
    } else if (missed && s.status === 'passed' && heldBack(s)) {
      lead = 'Held back.';
      words = `It held up on data it had never seen, the one-time locked holdout included, but it is ${lc(missed[0].label)}, so the gatekeeper didn’t clear it to trade. Verdict, below, has what was measured.`;
    } else if (missed && s.status === 'passed') {
      lead = 'Missed the final test.';
      words = `It passed its first test on unseen data${v && v.n_trades != null ? ` (${num(v.n_trades)} trades)` : ''}, then missed the one-time final test on the locked holdout: ${lc(missed[0].label)}${missed.length > 1 ? `, and ${missed.length - 1} more` : ''}. Verdict, below, has what was measured.`;
    } else if (s.status === 'passed' && h && h.n_trades != null && ['deployment_candidate', 'forward_validated'].includes(exp.classification)) {
      lead = 'Passed.';
      words = `It cleared every check, including the one-time locked holdout: ${num(h.n_trades)} trades on data it had never seen${h.mean_net_return != null ? `, averaging ${rpRet(h.mean_net_return)} of the stake per trade after fees` : ''}.`;
    } else if (s.status === 'passed' && !h && p && p.n_trades != null && exp.classification === 'deployment_candidate') {
      lead = 'Passed on paper.';
      words = `It fell short on its first test on unseen data, then passed its one judgment on its own paper trades (${num(p.n_trades)}) and every check after it.`;
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
    const missed = Array.isArray(s.why_failed) && s.why_failed.length ? s.why_failed : null;
    s.verdict = laterVerdict(s, missed);
    const passedAll = s.status === 'passed' && !missed;
    const ins = s.in_sample || {}, oos = s.out_of_sample;
    // A research session's strategy is judged by the gatekeeper on its validation window (the experiment's
    // record): that is its unseen-data result. Only an older backtest carries out_of_sample, so the figure
    // read "Rejected before the unseen test" beside Passed and the held-out evidence further down.
    const held = !oos && s.experiment && s.experiment.validation && s.experiment.validation.n_trades != null ? s.experiment.validation : null;
    // No gatekeeper record (a "passed" row with none, or backtest-only): nothing on the page is held out. Its
    // out_of_sample, when it has one, is the old backtest's later slice, which that loose gate used to pick it
    // (its numbers also went back to the agent), so it is "after the split date", never "the agent never saw".
    // With none, its only figures are in-sample and the unseen-data figure is left out. Display only.
    const hasExp = !!s.experiment;
    const splitOnly = !hasExp && ['passed', 'backtest-only'].includes(s.status);
    const cutWords = splitOnly ? { cutLabel: ['AFTER THE SPLIT DATE →', 'LATER →'] } : {};
    const oosHead = splitOnly ? 'After the split date (not held out)' : 'Never seen (out-of-sample)';
    const splitFig = (r) => r.out_of_sample ? fig('Later-period P&L', usd(r.out_of_sample.pnl, true), { v: r.out_of_sample.pnl,
      small: `${r.out_of_sample.trades} trades${overDays(r.out_of_sample.days)} after the split date, which picked it: not held out` }) : '';
    const heldFig = (h, label) => fig(label, h.net_pnl != null ? usd(h.net_pnl, true) : rpRet(h.mean_net_return), { v: h.net_pnl != null ? h.net_pnl : h.mean_net_return,
      small: `${h.net_pnl != null ? '' : 'per trade, '}after fees, over ${num(h.n_trades)} trade${h.n_trades === 1 ? '' : 's'} the agent never saw` });
    const heldWords = (h) => `On ${num(h.n_trades)} trade${h.n_trades === 1 ? '' : 's'} of data the agent never saw while iterating, it ${h.net_pnl != null ? `${+h.net_pnl >= 0 ? 'made ' + usd(h.net_pnl) : 'lost ' + usd(Math.abs(h.net_pnl))} after fees${h.mean_net_return != null ? ` (${rpRet(h.mean_net_return)} of the stake per trade)` : ''}` : `averaged ${rpRet(h.mean_net_return)} of the stake per trade after fees`}${s.hypotheses_tried ? `, one of ${num(s.hypotheses_tried)} ideas tested this run` : ''}.`;
    const figsFor = (r) => (splitOnly ? splitFig(r) : held && !r.out_of_sample ? heldFig(held, 'Unseen-data P&L') : fig('Unseen-data P&L', r.out_of_sample ? usd(r.out_of_sample.pnl, true) : '—', { v: r.out_of_sample && r.out_of_sample.pnl, small: r.out_of_sample ? `${r.out_of_sample.trades} trades${overDays(r.out_of_sample.days)} the agent never saw` : 'Rejected before the unseen test' })) +
      fig('In-sample P&L', r.in_sample ? usd(r.in_sample.pnl, true) : '—', { v: r.in_sample && r.in_sample.pnl, small: r.in_sample ? `${r.in_sample.trades} trades on the history it searched` : 'No in-sample result recorded' }) +
      fig('Return on capital', r.out_of_sample ? pct(r.out_of_sample.roi) : '—', { small: [r.out_of_sample && overDays(r.out_of_sample.days) ? (splitOnly ? 'After the split date' : 'Unseen data') + overDays(r.out_of_sample.days) : '', r.capital ? `$${fmt0.format(r.capital)} at risk at most` : ''].filter(Boolean).join(' ·\u00a0') }) +
      // "Ideas tested", the session's count, as Meridian and the strategy lists say it: "Hypotheses tested 1 of 18"
      // said neither word the other pages use nor what the 1 was.
      fig('Ideas tested', s.hypotheses_tried != null ? num(s.hypotheses_tried) : '—', { small: s.hypotheses_tried == null ? 'Count unavailable.' : `in the session that found it${passedAll ? '; this is the one that passed' : ''}. More ideas tried, more chance one passes by luck (multiple testing).` });
    // A strategy from the seeded example session says so here too, as the lists and its run page do.
    // Its title is the heading: a customer never sees its internal id (the zero-padded "No. 00002" it led with).
    root.querySelector('.board-title').outerHTML = boardTitle(s.title,
      `${s.example ? EXAMPLE_TAG + ' ' : ''}${esc(marketShort(s.market))} ·\u00a0${esc(dirLabel(s.direction))}${s.example ? ' \u00b7\u00a0' + EXAMPLE_NOTE : ''}`);
    root.querySelector('#figs').innerHTML = figsFor(s);
    const canDeploy = !restricted && ['passed', 'failed', 'rejected'].includes(s.status);
    // Why a strategy was rejected (never reached the unseen-data gate) — stated honestly: a
    // profitable idea with too few trades is rejected on sample size, not for "losing money".
    const rejectReason = (st) => {
      const i = st.in_sample || {};
      // The server's first missed check says why when it knows (the skeptic's review, the pre-test screen):
      // "ranked below the handful of finalists" read beside "The skeptic's review didn't pass it". Plain text.
      const w = Array.isArray(st.why_failed) && st.why_failed[0];
      if (w && w.label) return String(w.label).charAt(0).toLowerCase() + String(w.label).slice(1) + '.';
      if (i.trades != null && i.trades < 5) return `it made ${usd(i.pnl, true)} in testing, but over just ${i.trades} trade${i.trades === 1 ? '' : 's'} — a finalist needs at least 5, too few to trust.`;
      if (i.pnl != null && +i.pnl <= 0) return `it lost money in testing (${usd(i.pnl, true)}).`;
      return 'it ranked below the handful of finalists we tested on unseen data.';
    };
    const liveWhy = !S.me.live_trading_available ? 'Live trading isn’t open yet.' : !S.me.kalshi_connected ? 'Connect Kalshi on the <a href="/funds#connect-kalshi">Funds page</a> first.' : (s.side !== 'yes' && !S.me.no_side_live_enabled) ? 'NO-side live trading is still being validated on the demo sandbox — deploy this on demo or paper for now.' : '';
    // Both are fixed strings (no user data), so they render as HTML with a link to Funds.
    const demoWhy = !S.me.kalshi_dev_connected ? 'Add your Kalshi demo (sandbox) key on the <a href="/funds#connect-kalshi">Funds page</a> first.' : '';
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
        <dt>Sharpe (daily)</dt><dd>${m.sharpe == null ? '—' : m.sharpe}</dd></dl>${luckFlag(m)}` : held ? '<p class="hint">Its test on unseen data is the validation-window evidence above.</p>' : splitOnly ? '<p class="hint">No result after the split date recorded: its only figures are from the history it searched.</p>' : `<p class="hint">Not tested on unseen data — ${esc(rejectReason(s))}</p>`;
    // The backtest's stored gate names say "unseen data"; with no gatekeeper record that slice is the data after the
    // split date, which these gates picked it on (display only: the stored names are unchanged).
    const gateName = (n) => splitOnly ? String(n).replace(/\bunseen data\b/g, 'data after the split date').replace(/\bunseen trades\b/g, 'trades after the split date') : n;
    const gatesHtml = (gs) => gs && gs.length ? `<ul class="gates">${gs.map((g) => `<li class="${g.ok ? 'ok' : 'no'}">${g.ok ? ICON.check : ICON.cross}<span>${esc(gateName(g.name))}<small>needs ${esc(g.threshold)}</small></span><span class="v">${typeof g.value === 'number' && /\$|drawdown|money/i.test(g.name + g.threshold) ? usd(g.value) : esc(g.value == null ? '—' : g.value)}</span></li>`).join('')}</ul>` : '<p class="hint">No gate results recorded for this strategy. Gates only run for finalists that made money in testing.</p>';
    const trades = (s.recent_trades || []).length ? `<div class="sheet"><table class="table stack t-unseen"><thead><tr><th>Opened</th><th>Market</th><th>Side</th><th class="num">Entry${perpetual ? ' (USD)' : ''}</th><th class="num">Exit${perpetual ? ' (USD)' : ''}</th><th class="num">P&amp;L</th></tr></thead><tbody>
        ${s.recent_trades.map((t) => `<tr><td data-lab="Opened">${t.opened ? esc(new Date(t.opened.replace('Z', ':00Z')).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' })) : '—'}</td><td class="pos-name" data-lab="Market">${esc(contractName(t.ticker, s.market))}<div class="sub-fig">${kalshiRef(t.ticker)}</div></td><td data-lab="Side">${t.side ? esc(t.side.toUpperCase()) : '—'} ×${t.qty}</td><td class="num" data-lab="Entry">${tradePrice(t.entry, perpetual)}</td><td class="num" data-lab="Exit">${tradePrice(t.exit, perpetual)} <small class="hint">${esc(exitWord(t.reason))}</small></td><td class="num ${tone(t.pnl)}" data-lab="P&amp;L">${usd(t.pnl, true)}</td></tr>`).join('')}
      </tbody></table></div>` : `<p class="hint">No ${splitOnly ? 'later-period' : 'unseen-data'} trades to show.</p>`;
    const activeDeps = restricted ? [] : s.deployments.filter((d) => d.status !== 'stopped');
    // Stopped deployments can still hold positions; the server refuses the delete until they close.
    const delBlock = restricted ? null : (s.delete_block || null);
    const kUrl = marketKalshiUrl(s.market);
    const mktLink = kUrl ? `<a href="${kUrl}" target="_blank" rel="noopener">${esc(marketLabel(s.market))} ↗</a>` : esc(marketLabel(s.market));
    // ---- the strategy dossier, composed as a research paper (abstract → mechanism →
    // methodology → results → verdict). Each section renders only when it has content, so a
    // pre-pipeline strategy with no ledger row falls back to its rule + backtest + plain verdict.
    const rp = researchPaper(s.experiment);
    const filed = (() => { try { return new Date(s.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); } catch (e) { return ''; } })();
    const abResult = splitOnly ? (oos
      ? `After the backtest’s split date it ${+oos.pnl >= 0 ? 'returned ' + usd(oos.pnl) : 'lost ' + usd(Math.abs(oos.pnl))} over ${num(oos.trades)} trade${oos.trades === 1 ? '' : 's'}. That later slice is what picked it, so it isn’t held-out evidence.`
      : 'It has no held-out result: its only figures are from the history it searched.')
      : oos
      ? `On unseen data the agent never touched while iterating, it ${+oos.pnl >= 0 ? 'returned ' + usd(oos.pnl) : 'lost ' + usd(Math.abs(oos.pnl))} over ${num(oos.trades)} trade${oos.trades === 1 ? '' : 's'}${s.hypotheses_tried ? (passedAll ? `, and cleared the gate as one of ${num(s.hypotheses_tried)} ideas tested this run` : `, one of ${num(s.hypotheses_tried)} ideas tested this run`) : ''}.`
      : held ? heldWords(held)
      : `It was ${s.status === 'rejected' ? 'rejected before reaching' : 'not advanced to'} the unseen-data test${s.hypotheses_tried ? ` — one of ${num(s.hypotheses_tried)} ideas tried this run` : ''}.`;
    const dataBlock = s.dataset ? `<div class="paper-sub"><h4 class="paper-h">Data &amp; partitioning</h4>
          <dl class="rp-grid">
            <div><dt>Market</dt><dd>${mktLink}</dd></div>
            <div><dt>Direction</dt><dd>${esc(dirLabel(s.direction))}</dd></div>
            <div><dt>History window</dt><dd>${esc((s.dataset.start || '').slice(0, 10)) || '—'} → ${esc((s.dataset.end || '').slice(0, 10)) || '—'}</dd></div>
            <div><dt>${splitOnly ? 'Split date' : 'Unseen (held out) from'}</dt><dd>${esc((s.dataset.out_of_sample_from || '').slice(0, 10)) || '—'}</dd></div>
          </dl>
          <p class="rp-sub" style="margin-top:8px">${perpetual ? 'The agent only saw the research partition. ' + PERPS_SCENARIO : (splitOnly ? 'The rule was fit on data before the split date; the data after it picked the rule, so none of it is held out. ' : 'The agent only ever saw data before the held-out date. ') + "Every simulated fill pays the ask or bid plus Kalshi’s taker fee — results are net of fees or they do not count."}</p></div>` : '';
    // What it does, in plain words: the paper's first section. It sat inside the Methodology fold,
    // which a phone opens closed, under the pre-registration, so the rule took digging to find.
    const ruleBlock = `${(s.rules || []).length ? `<ul class="rules">${s.rules.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
          <details class="raw"><summary>Exact machine spec (JSON)</summary><pre>${esc(JSON.stringify(s.spec, null, 2))}</pre></details>`;
    const methodologyBody = rp.methodology + dataBlock + (perpetual && !s.dataset ? `<p class="hint">${PERPS_SCENARIO}</p>` : '');
    const resultsBody = rp.results
      + `<div class="paper-sub"><h4 class="paper-h">${perpetual ? 'Perpetual research scenario' : hasExp ? 'Backtest &amp; Kalshi demo replay' : 'Backtest'}</h4>
          ${hasExp ? '<p class="rp-sub" style="margin-top:0">These are the agent’s own in-sample/replay numbers. The in-sample column is optimistically biased — the rule was fit on exactly this data — so trust the held-out validation-window evidence above, not the column below.</p>' : ''}
          <div id="sheet-results">
            <div id="equity-wrap">${s.equity ? equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from, null, { width: chartWidth(), ...cutWords }) : ''}${!perpetual && s.equity && oos ? DEV_PENDING(splitOnly ? 'later' : 'unseen') : ''}</div>
            <div class="split"><div><h4>Tested on (in-sample)</h4>${s.in_sample ? metricRows(ins) : '<p class="hint">No in-sample result recorded.</p>'}</div><div><h4>${oosHead}</h4>${metricRows(oos)}</div></div>
          </div></div>`
      + fold(`Most recent ${splitOnly ? 'later-period' : 'unseen'} trades`, `<div class="paper-sub"><h4 class="paper-h">Most recent ${splitOnly ? 'later-period' : 'unseen'} trades</h4>${trades}</div>`);
    let verdictBody = rp.verdict;
    if (!hasExp) {
      const btOnly = ['sig', 'armed', 'Backtest only', 'Backtest-only — never put through statistical validation (no pre-registration, one-time holdout, or multiple-testing control). These numbers come from a sample too small to separate skill from luck. ' + (perpetual ? 'This market remains research only.' : restricted ? 'Agent-written code stays in research.' : 'It can’t be deployed: only a strategy put through those checks can be.')];
      const vmap = {
        // No experiment resolved (by experiment_id OR strategy_id) means NO gatekeeper record
        // exists — so this was NOT validated, whatever the status says. Never claim it "cleared
        // the gatekeeper" (that would be a lie); flag the missing record honestly. A correctly
        // validated 'passed' always has an experiment and takes the rich path above, not this one.
        passed: ['sig', 'armed', 'Not validated (record missing)', 'Marked passed, but no statistical-gatekeeper record (pre-registration, validation, holdout) can be found for it, so nothing on this page is held-out evidence: ' + (oos ? 'its figures come from the history it searched and from the data after the split date, which picked it.' : 'its only figures are from the history it searched.') + ' Treat it as unvalidated.'],
        'backtest-only': btOnly,
        failed: ['sig', 'armed', 'Void', 'It reached the unseen-data gate and failed it, so it was not validated.'],
        rejected: ['quiet', 'quiet', 'Rejected', 'Rejected — ' + rejectReason(s)],
      };
      const [vt, chip, label, words] = vmap[s.status] || ['quiet', 'quiet', rpHuman(s.status), 'Awaiting a recorded verdict.'];
      verdictBody = `<div class="rp-verdict ${vt}"><span class="mk ${chip}">${esc(label)}</span><p>${esc(words)}</p></div>`;
    }
    if (missed) verdictBody += `<div class="paper-sub"><h4 class="paper-h">What it missed, and what to try next</h4>${whyFailedHtml(missed)}</div>`;
    // On a phone the Deploy panel sits below the whole paper, screens down. A validated passed
    // strategy (one with its gatekeeper record) that isn't on paper yet gets its primary action up
    // top too; same call as #dep-paper. Wide screens hide it (the panel is beside the paper there).
    // One that missed a later check, or one already on paper, doesn't get it. One the autopilot puts on
    // paper itself (the server's autopilot_paper) says so in its place while the switch is on, and follows
    // a flip (syncApCopy): a copy deployed by hand as well doubles its positions.
    const onPaper = activeDeps.find((d) => d.mode === 'paper');
    const quickPaper = canDeploy && passedAll && hasExp && !onPaper;
    const apOn = !!(S.me && S.me.user && S.me.user.autopilot), apPaper = quickPaper && !!s.autopilot_paper;
    const apOff = apPaper ? ` data-ap-off${apOn ? ' hidden' : ''}` : '';
    const apLine = apPaper ? `<p class="hint ap-paper" data-ap-next${apOn ? '' : ' hidden'}>The autopilot is putting this on paper at its next check-in, so there is nothing for you to deploy. <a href="/deploy">Deploy</a> shows it once it’s there.</p>` : '';
    const quickHtml = quickPaper ? `<div class="strat-quick" id="strat-quick">${apLine}<button class="btn primary" id="dep-paper-quick"${apOff}>Deploy on paper</button><p class="hint"${apOff}>Paper trades with pretend money against live prices, so nothing real is at risk. Demo and live are in Deploy, further down.</p><div id="depflash-quick"></div></div>` : '';
    const ladder = restricted ? '' : ladderLines(s, { canDeploy, demoWhy, apPaper });
    // Already on paper (running or paused): where to find it, beside the button and its second-copy warning.
    const paperHere = onPaper ? `<p class="hint on-paper">${onPaper.status === 'paused' ? 'Its paper deployment is paused. <a href="/deploy">Resume it on Deploy</a>.' : 'It runs on paper. <a href="/deploy">See it on Deploy</a>.'}</p>` : '';
    // The page heading above the paper says its title, market and direction (boardTitle), so the paper's header
    // says only when it was filed, under a heading a screen reader's outline keeps; it said the title twice.
    const paperSec = (title, body) => body ? `<section class="paper-sec"><h3 class="paper-sec-t">${title}</h3><div class="paper-sec-body">${body}</div></section>` : '';
    root.querySelector('#main').innerHTML = `
      <div id="flash"></div>
      <div class="detail">
        <div>
          <article class="sheet-doc paper">
            <header class="paper-head">
              ${filed ? `<div class="paper-cite"><span>Filed ${esc(filed)}</span></div>` : ''}
              <h2 class="vh">The research</h2>
              <div class="paper-byline">${statusMark(s)}${researchBadge(s)}${s.shared_from ? ` <span class="mk shared">${ICON.share}Shared by ${esc(s.shared_from)}</span>` : ''}</div>
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
        <aside aria-label="Deploy and gates">
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
            // Beside a Live or Demo row a paper one says Paper too: untagged, it read as the real-money book.
            return `<section class="panel"><h3>Holding right now</h3>
            <ul class="holdlist">${s.holdings.map((p) => `<li><div class="pos-name">${contractLink(p.ticker, s.market)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : p.mode === 'demo' ? '<span class="mk dep">Demo</span>' : books.length > 1 ? '<span class="mk">Paper</span>' : ''}</div><div class="sub-fig">${kalshiRef(p.ticker)}</div>
              <div class="holdlist-figs"><b>${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(p.entry_price)}</b><span>Cost + fee ${usd(p.cost)}</span><span>Unreal. ${p.unrealized == null ? '—' : money(p.unrealized)}</span><span>Settles ${settleAt(p.market_close_time)}</span></div>${p.why ? `<div class="sub-fig pos-why">${esc(p.why)}</div>` : ''}</li>`).join('')}</ul>
            <p class="hint" style="margin-top:8px">${books.map(bookLine).join('<br>')}</p></section>`;
          })() : ''}
          ${ladder ? `<section class="panel" id="ladder"><h3>Paper → demo → live</h3><div class="rung-books" id="ladder-body">${ladder}</div></section>` : ''}
          <section class="panel"><h3>${restricted ? 'Research only' : 'Deploy'}</h3>
            ${canDeploy ? `<div style="display:grid;gap:10px">
                ${missed && s.verdict ? `<div class="notice bad">${ICON.warn}<span>${heldBack(s) ? 'Held back' : 'Missed the final test'}: ${esc(missed[0].label.charAt(0).toLowerCase() + missed[0].label.slice(1))}${missed.length > 1 ? `, and ${missed.length - 1} more check${missed.length > 2 ? 's' : ''} missed` : ''} (see Verdict). It wasn’t cleared to trade, so it can’t go live, and putting it on paper is your call.</span></div>` : ''}
                ${s.status !== 'passed' && !(missed && s.verdict) ? `<div class="notice bad">${ICON.warn}<span>${missed ? `${s.status === 'failed' ? 'Void' : 'Rejected'}: ${esc(missed[0].label.charAt(0).toLowerCase() + missed[0].label.slice(1))}${missed.length > 1 ? `, and ${missed.length - 1} more check${missed.length > 2 ? 's' : ''} missed` : ''} (see Verdict).` : s.status === 'failed' ? 'Void: it failed the unseen-data gate.' : `Rejected: ${esc(rejectReason(s))}`} It wasn’t validated, so deploying it — on paper or live — is your call and your risk.</span></div>` : ''}
                ${apLine}<button class="btn" id="dep-paper"${apOff}>Deploy on paper</button>${paperAgain(activeDeps)}${paperHere}
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
            ${!restricted && s.deployments.length ? `<p class="hint" style="margin-top:12px">Already deployed: ${s.deployments.map((d) => `${bookName(d)} (${esc(depIdle(d) ? depIdle(d).state.toLowerCase() : d.status)})`).join(', ')}. <a href="/deploy">See them on the Deploy page</a></p>` : ''}
            ${kUrl ? `<p class="hint" style="margin-top:12px"><a href="${kUrl}" target="_blank" rel="noopener">Open ${esc(marketShort(s.market))} on Kalshi ↗</a></p>` : ''}
          </section>
          ${!restricted && passedAll ? `<section class="panel" id="road-live"><h3>Road to live</h3><div id="road-live-body"><p class="hint">Checking…</p></div></section>` : ''}
          <section class="panel"><h3>Gates</h3><div id="gates">${gatesHtml(s.gates)}</div></section>
          ${!perpetual && s.status !== 'rejected' ? fold('What if…', `<section class="panel" id="whatif"><h3>What if…</h3>
            <p class="hint" style="margin-bottom:6px">Move a dial and the whole sheet re-runs.</p>
            <div class="dial"><div class="top"><label class="label" for="wf">Fees</label><output id="wfo">1.0×</output></div><input type="range" id="wf" min="0" max="3" step="0.25" value="1"></div>
            <div class="dial"><div class="top"><label class="label" for="ws">Slippage per fill</label><output id="wso">0.0¢</output></div><input type="range" id="ws" min="0" max="5" step="0.1" value="0"></div>
            ${s.stake != null ? `<div class="dial"><div class="top"><label class="label" for="wk">Stake per trade</label><output id="wko">$${esc(s.stake)}</output></div><input type="range" id="wk" min="1" max="200" step="1" value="${Math.min(200, s.stake)}"></div>` : ''}
            <div id="wflash" aria-live="polite"></div>
          </section>`) : ''}
          ${fold('Share', `<section class="panel"><h3>Share</h3>
            <p class="hint" style="margin-bottom:8px">${restricted ? 'Share a research-only copy using their Tau sign-in email. It keeps the same simulation limits and cannot be deployed.' : 'Send a copy to a friend by the email they sign in with. They can deploy it like their own — sharing can’t be undone.'}</p>
            <form id="share-form" style="display:grid;gap:8px">
              <input class="input" id="share-email" type="email" autocomplete="off" placeholder="friend@email.com" aria-label="Friend’s email">
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
    // never blocks the view; absent -> the chart simply stays sim-only. Until it answers,
    // the chart carries its own pending line (DEV_PENDING), gone with or without a curve.
    if (!perpetual && s.equity && oos) (async () => {
      const pending = root.querySelector('#dev-pending');
      try {
        const r = await api('/api/strategies/' + s.id + '/dev-curve');
        const wrap = root.querySelector('#equity-wrap');
        if (wrap && r && r.dev_curve && r.dev_curve.length > 1) {
          const sl = r.slippage, sc = (v) => (v >= 0 ? '+' : '') + v.toFixed(1) + '¢';
          wrap.innerHTML = equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from, r.dev_curve, { width: chartWidth(), ...cutWords })
            + `<p class="hint" style="margin-top:6px">Dashed line: the ${splitOnly ? 'later' : 'unseen'} window replayed read-only against Kalshi’s demo environment${r.capped ? ` (first ${r.contracts} contracts)` : ''} — real demo order-book prices, scored with the same fees. No orders are placed.</p>`
            + (sl ? `<p class="hint" style="margin-top:4px;font-variant-numeric:tabular-nums">Real demo-book slippage: <b>${sc(sl.entry_cents)}</b> entry${sl.exit_cents != null ? ` / <b>${sc(sl.exit_cents)}</b> exit` : ''} over ${sl.n_trades} aligned trade${sl.n_trades === 1 ? '' : 's'} (positive means real fills were worse). <button type="button" class="btn sm" id="apply-slip">Apply to what-if</button></p>` : '');
          if (sl) {
            const perFill = Math.max(0, Math.min(5, sl.exit_cents != null ? (sl.entry_cents + sl.exit_cents) / 2 : sl.entry_cents));
            const ws = root.querySelector('#ws'), wso = root.querySelector('#wso'), ab = root.querySelector('#apply-slip');
            if (ws) { ws.value = perFill; if (wso) wso.textContent = perFill.toFixed(1) + '¢'; }   // pre-fill the knob with the measured number
            if (ab && ws) ab.onclick = () => { ws.value = perFill; ws.dispatchEvent(new Event('input')); };
          }
        }
      } catch (e) { /* demo replay is best-effort; leave the sim-only chart */ } finally { if (pending) pending.remove(); }
    })();
    // Road to live: the strategy's own checks, the ones the deploy paths enforce (gatekeeper, realistic
    // paper record, demo record), with progress, what is left and when the counts could be in. How it
    // then reaches real money (the user's own step) is said apart, never as a check that runs by itself.
    // Best-effort and fetched after the page, like the dev curve.
    let roadNow;  // Road to live once read: the ladder is drawn with it
    const roadRead = async () => {
      try {
        const r = await api('/api/strategies/' + s.id + '/live-readiness');
        roadNow = r;
        const lb = root.querySelector('#ladder-body');
        if (lb) lb.innerHTML = ladderLines(s, { canDeploy, demoWhy, road: r, apPaper });
        const p = r.paper, c = p.checks;
        const rows = [
          { name: 'Gatekeeper cleared', threshold: 'holdout + diversification', ok: r.deployment_candidate, value: r.deployment_candidate ? 'yes' : 'no' },
          { name: 'Realistic paper trades', threshold: p.trades_needed + '+', ok: c.realistic_trades, value: p.trades + ' / ' + p.trades_needed },
          ...(c.legacy_pnl === false ? [{ name: 'Paper P&L, every fill', threshold: '$0 or above', ok: false, value: p.legacy_pnl }] : []),
          { name: 'Net, ' + PAPER_NET, threshold: 'above $0', ok: c.net_pnl, value: p.net_pnl },
          { name: 'Separate events', threshold: (p.events_needed || 20) + '+', ok: c.events, value: p.events == null ? '—' : p.events + ' / ' + (p.events_needed || 20) },
          { name: 'First to last paper trade', threshold: p.span_needed_hours + 'h+', ok: c.span, value: Math.round(p.span_hours) + 'h / ' + p.span_needed_hours + 'h' },
          { name: 'Edge is not luck', threshold: 'p ≤ ' + p.p_value_needed.toFixed(2), ok: c.edge, value: roadP(p.p_value) },
          { name: 'Still working lately', threshold: 'newer half above $0', ok: c.recent, value: p.recent_trades ? p.recent_net_pnl : '—' },
          { name: 'Clean demo record', threshold: (p.demo_orders_needed || 20) + '+ demo orders, book matches', ok: c.demo, value: p.demo_orders == null ? '—' : p.demo_orders + ' / ' + p.demo_orders_needed },
        ];
        const auto = r.live_autopilot && r.live_autopilot.ok;
        const body = root.querySelector('#road-live-body');
        if (body) body.innerHTML = roadSummary(r, s, liveWhy, rows.length, apPaper) + gatesHtml(rows)
          + (p.realization != null ? `<p class="hint" style="margin-top:6px;font-variant-numeric:tabular-nums">${p.realization < 0 ? `Paper is <b>losing money</b> per trade, while the backtest made money on ${splitOnly ? 'the data after its split date' : 'unseen data'}.` : `Paper earns <b>${Math.round(p.realization * 100)}%</b> of the backtest’s ${splitOnly ? 'later-period' : 'unseen-data'} P&amp;L per trade.`}</p>` : '')
          + `<p class="hint" style="margin-top:6px">Paper counts only fills simulated against the live order book (bought at the ask, sold at the bid, after Kalshi fees), from every paper run of this strategy, removed ones included, so these figures are not its realized P&amp;L above. Clearing every check never starts real money by itself: you deploy it with live money and type LIVE${auto ? ', or live autopilot, which you turned on, may do it within your caps' : ''}. Live trading on this server: ${S.me.live_trading_available ? 'open' : 'not open yet'}. Your Kalshi key: ${S.me.kalshi_connected ? 'connected' : 'not connected'}.</p>`;
      } catch (e) {
        // A read that failed (a bad connection) says why and offers Try again: it said "unavailable" for the
        // rest of the visit, and only a reload asked again.
        const body = root.querySelector('#road-live-body');
        if (!body) return;
        const why = e instanceof ApiError ? e.message : 'Live readiness is unavailable right now.';
        body.innerHTML = `<p class="hint">${esc(why)} <button class="btn sm" type="button" data-road-retry>Try again</button></p>`;
        body.querySelector('[data-road-retry]').onclick = () => { body.innerHTML = '<p class="hint">Checking…</p>'; return roadRead(); };
      }
    };
    if (root.querySelector('#road-live-body')) roadRead();
    // The ladder's demo check never waits on Kalshi: one that needs the demo cash while the server's memo isn't
    // kept comes demo_health_pending. The page asks the demo cash (one ask, shared with the other pages'), then
    // reads the strategy again, once, and redraws only the ladder. Still unknown after that (or that read failed),
    // the rung reads as before: an unknown demo cash is never a problem.
    if (s.demo_health_pending && !restricted) {
      const gen = S.gen;
      const redraw = (again) => {
        if (gen !== S.gen) return;
        if (again) s.demo_health = again.demo_health;
        s.demo_health_pending = false;
        const lb = root.querySelector('#ladder-body');
        if (lb) lb.innerHTML = ladderLines(s, { canDeploy, demoWhy, road: roadNow, apPaper });
      };
      demoCashRead().then(() => (gen === S.gen ? api('/api/strategies/' + s.id) : null)).then(redraw, () => redraw(null));
    }
    for (const [sel, fl] of [['#dep-paper', '#depflash'], ['#dep-paper-quick', '#depflash-quick']]) {
      const depPaper = root.querySelector(sel);
      if (depPaper) depPaper.onclick = () => busy(depPaper, async () => {
        try { await depWrite('/api/deployments', { strategy_id: s.id, mode: 'paper' }); S.deployed = { mode: 'paper', title: s.title }; go('/deploy'); } catch (e) { flash(fl, depSaid(e, 'deploy'), 'bad'); }
      });
    }
    const depDemo = root.querySelector('#dep-demo');
    if (depDemo) depDemo.onclick = () => { if (demoWhy) return; busy(depDemo, async () => {
      try { await depWrite('/api/deployments', { strategy_id: s.id, mode: 'demo' }); S.deployed = { mode: 'demo', title: s.title }; go('/deploy'); } catch (e) { flash('#depflash', depSaid(e, 'deploy'), 'bad'); }
    }); };
    const stopDep = root.querySelector('#stop-dep');
    if (stopDep) stopDep.onclick = () => armed(stopDep, 'Confirm stop', () => busy(stopDep, async () => {
      try { for (const d of activeDeps) await depWrite(`/api/deployments/${d.id}/stop`, {}); } catch (e) { flash('#delflash', depSaid(e, 'stopAll'), 'bad'); return; }
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
        try { await depWrite('/api/deployments', { strategy_id: s.id, mode: 'live', confirm: lc.confirm.value.trim() }); go('/deploy'); } catch (err) { flash('#depflash', depSaid(err, 'deploy'), 'bad'); }
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
            root.querySelector('#sheet-results').innerHTML = equityChart(r.equity, s.dataset && s.dataset.out_of_sample_from, null, { width: chartWidth(), ...cutWords }) +
              `<div class="split"><div><h4>Tested on (in-sample)</h4>${metricRows(r.in_sample)}</div><div><h4>${oosHead}</h4>${metricRows(r.out_of_sample)}</div></div>`;
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

  return {viewStrategies, viewStrategy};
});
