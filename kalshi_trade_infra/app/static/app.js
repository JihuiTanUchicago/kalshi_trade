/* Tau client. Vanilla JS, no build step.
   Every string that came from a user, an agent or the market goes through esc(). */
(() => {
  'use strict';

  const root = document.getElementById('app');
  const S = { me: null, timers: [], gen: 0 };

  // ---------- brand mark ----------
  const TAU_MARK = '<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="15" fill="#15161A"/><path d="M18 24h28M32 24v22" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/><circle cx="32" cy="48" r="3.5" fill="#F05A28"/></svg>';

  // ---------- icons (one stroke, one weight) ----------
  const I = (d, extra = '') => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
  const ICON = {
    mark: TAU_MARK,
    dashboard: I('<rect x="3" y="4" width="18" height="7" rx="1"/><path d="M3 15h7v5H3zM14 15h7v5h-7z"/>'),
    research: I('<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 6 6M8 10.5h5M10.5 8v5"/>'),
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
    at: I('<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>'),
    google: '<svg viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>',
  };

  // ---------- formatting ----------
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
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
  const age = (sec) => (sec == null ? 'never' : sec < 90 ? sec + 's' : sec < 5400 ? Math.round(sec / 60) + 'm' : sec < 172800 ? Math.round(sec / 3600) + 'h' : Math.round(sec / 86400) + 'd');
  const marketLabel = (k) => ((S.me && S.me.markets.find((m) => m.key === k)) || { label: k }).label;
  const marketShort = (k) => (k === 'btc15m' ? 'BTC 15-min' : k === 'btc_daily' ? 'BTC 5pm' : k);
  const dirLabel = (k) => { if (!k) return 'Session'; const d = S.me && S.me.directions.find((x) => x.key === k); return d ? d.label : String(k).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()); };
  const sessionTitle = (r) => (r.prompt && r.prompt.trim()) ? r.prompt.trim() : (dirLabel(r.direction) + ' \u00b7 ' + marketShort(r.market));

  // ---------- API ----------
  class ApiError extends Error { constructor(status, msg) { super(msg); this.status = status; } }
  async function api(path, body) {
    const opts = { credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-Recursive'] = '1';
      opts.body = JSON.stringify(body);
    }
    let res;
    try { res = await fetch(path, opts); } catch (e) { throw new ApiError(0, "Can't reach Tau. Check your connection."); }
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
    [/^\/funds$/, viewFunds],
  ];
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

  function clearTimers() { S.timers.forEach(clearInterval); S.timers = []; }
  function poll(fn, ms) {
    const gen = S.gen;
    const id = setInterval(() => { if (!document.hidden && gen === S.gen) fn().catch(() => {}); }, ms);
    S.timers.push(id);
  }
  async function render() {
    clearTimers();
    S.gen++;
    window.scrollTo(0, 0);
    const path = location.pathname;
    const match = routes.map(([re, fn]) => [path.match(re), fn]).find(([m]) => m);
    if (!S.me && path !== '/signin') {
      try { S.me = await api('/api/me'); } catch (e) { return go('/signin', true); }
    }
    if (!match) return go('/', true);
    root.setAttribute('aria-busy', 'true');
    try { await match[1](...match[0].slice(1)); } catch (e) { if (e.status !== 401) shell('', boardTitle('Something went wrong'), notice(e.message, 'bad')); }
    root.setAttribute('aria-busy', 'false');
  }

  // ---------- shell ----------
  const NAV = [['/', 'Dashboard', 'dashboard'], ['/research', 'Research', 'research'], ['/strategies', 'Strategies', 'strategies'], ['/deploy', 'Deploy', 'deploy'], ['/community', 'Community', 'community'], ['/funds', 'Funds', 'funds']];
  function shell(active, board, main) {
    document.body.classList.remove('landing-body');
    const u = S.me.user;
    const here = (NAV.find(([href]) => href === active) || ['', ''])[1];
    const nav = NAV.map(([href, label]) => `<a class="svc-link" href="${href}" ${active === href ? 'aria-current="page"' : ''}>${label}</a>`).join('');
    root.innerHTML = `
      <header class="masthead"><div class="masthead-in">
        <p class="wordmark"><a href="/">${ICON.mark}<span>Tau</span></a></p>
        <span class="asof">${esc(u.name || u.email)}<span class="sep">\u00b7</span><button class="linkish" data-action="signout">Sign out</button></span>
      </div></header>
      <nav class="services" aria-label="Sections"><div class="services-in">${nav}</div></nav>
      <div class="wrap">
        <div id="boardbody">${board}</div>
        <main id="main" tabindex="-1">${main}</main>
      </div>`;
    root.querySelector('[data-action="signout"]').onclick = async () => { await api('/api/logout', {}).catch(() => {}); S.me = null; go('/signin'); };
  }
  const boardTitle = (title, sub = '') => `<div class="board-title"><h1 class="page">${esc(title)}</h1>${sub ? `<p class="deck">${sub}</p>` : ''}</div>`;
  // One measured cell. Money direction rides a tint field behind the figure
  // (opts.v), never a colour on the digits and never the reserved signal red.
  const fig = (label, value, opts = {}) =>
    `<div class="m ${opts.cls || ''}"><dt class="lab">${label}</dt><dd><span class="fig ${opts.v > 0 ? 'tint pos' : opts.v < 0 ? 'tint neg' : ''}">${value}</span></dd>${opts.small ? `<div class="sub-fig">${opts.small}</div>` : ''}</div>`;
  const dirTag = () => '';
  const notice = (msg, kind = '') => `<div class="notice ${kind}" role="${kind === 'bad' ? 'alert' : 'status'}">${kind === 'good' ? ICON.check : ICON.warn}<span>${esc(msg)}</span></div>`;
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
  function equityChart(curve, cutoffIso) {
    const W = 760, H = 236, L = 52, R = 10, T = 30, B = 26;
    if (!curve || curve.length < 2) return `<div class="empty"><p>Not enough trades to draw an equity curve.</p></div>`;
    const t0 = curve[0][0], t1 = curve[curve.length - 1][0];
    const vals = curve.map((p) => p[1]);
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const cut = cutoffIso ? Date.parse(cutoffIso) / 1000 : null;
    const cx = cut && cut > t0 && cut < t1 ? x(cut) : null;
    const pts = curve.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const ticks = [lo, (lo + hi) / 2, hi].map((v) => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${usd(v)}</text>`).join('');
    const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative profit and loss over the backtest; ends at ${usd(vals[vals.length - 1], true)}">
      ${cx ? `<rect x="${cx}" y="${T}" width="${W - R - cx}" height="${H - T - B}" fill="var(--stock-raised)"/>
              <line x1="${cx}" x2="${cx}" y1="${T}" y2="${H - B}" stroke="var(--ink-3)" stroke-dasharray="4 4"/>
              <text x="${cx + 8}" y="${T - 10}" style="fill:var(--ink-2)">UNSEEN BY THE AGENT →</text>` : ''}
      <line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--rule-2)"/>
      ${ticks}
      <text x="${L}" y="${H - 6}">${day(t0)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${day(t1)}</text>
      <polyline points="${pts}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round"/>
    </svg>`;
  }

  // ---------- timetable rows ----------
  // State is a word in a mark, never colour alone. Signal red appears only on
  // states that need the user: a paused deployment and live money.
  const MARK = {
    passed: ['on', 'Passed'], failed: ['', 'Void'], rejected: ['quiet', 'Rejected'], queued: ['quiet', 'Testing'],
    paused: ['armed', 'Paused'], stopped: ['quiet', 'Stopped'],
  };
  const mark = (key, live) => {
    if (key === 'running') return live ? '<span class="mk live">Live</span>' : '<span class="mk">Paper</span>';
    const [cls, label] = MARK[key] || ['', key];
    return `<span class="mk ${cls}">${esc(label)}</span>`;
  };
  const money = (v) => `<span class="${tone(v)}">${usd(v, true)}</span>`;
  const STRAT_HEAD = '<thead><tr><th>Strategy</th><th>Market</th><th class="num">Unseen P&amp;L</th><th class="num">Trades</th><th class="num">Win</th><th>Tried</th><th>Status</th></tr></thead>';
  const strategyTable = (rows) => `<div class="sheet"><table class="stack t-strat">${STRAT_HEAD}<tbody>${rows}</tbody></table></div>`;
  function strategySlip(s, reg, opts = {}) {
    const oos = s.out_of_sample, ins = s.in_sample || {};
    const m = oos || ins;
    const tried = s.hypotheses_tried ? `1 of ${s.hypotheses_tried}` : s.parent_id ? 'Adjustment' : '\u2014';
    const name = opts.nolink ? esc(s.title) : `<a href="/strategies/${s.id}">${esc(s.title)}</a>`;
    return `<tr class="${opts.land ? 'washed' : ''}">
      <td class="name" data-lab="">${name}<div class="sub-fig cellwrap">${esc(s.thesis)}</div></td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(s.market))} \u00b7 ${esc(dirLabel(s.direction))}</span></td>
      <td class="num" data-lab="${oos ? 'Unseen P&amp;L' : 'Tested P&amp;L'}">${m.pnl == null ? '\u2014' : money(m.pnl)}${oos ? '' : '<div class="sub-fig">tested only</div>'}</td>
      <td class="num" data-lab="Trades">${m.trades == null ? '\u2014' : m.trades}</td>
      <td class="num" data-lab="Win">${pct(m.win_rate, false)}</td>
      <td data-lab="Tried">${esc(tried)}</td>
      <td class="act" data-lab="">${mark(s.status)}</td>
    </tr>`;
  }
  const DEP_HEAD = (controls) => `<thead><tr><th>Strategy</th><th>Market</th><th>Status</th><th class="num">Realized</th><th class="num">Trades</th><th class="num">Backtest unseen</th><th>Since</th>${controls ? '<th></th>' : ''}</tr></thead>`;
  const deploymentTable = (rows, controls) => `<div class="sheet"><table class="stack t-dep">${DEP_HEAD(controls)}<tbody>${rows}</tbody></table></div>`;
  function deploymentSlip(d, reg, controls) {
    const exp = d.backtest && d.backtest.out_of_sample;
    const live = d.mode === 'live';
    const actions = controls ? `<td class="act" data-lab="">
        ${d.status === 'running' ? `<button class="btn sm" data-dep="${d.id}" data-act="pause">Pause</button>` : ''}
        ${d.status === 'paused' ? `<button class="btn sm" data-dep="${d.id}" data-act="resume">Resume</button>` : ''}
        <button class="btn sm danger" data-dep="${d.id}" data-act="stop">Stop</button></td>` : '';
    return `<tr class="${live ? 'live-row' : ''}">
      <td class="name" data-lab=""><a href="/strategies/${d.strategy_id}">${esc(d.title)}</a>
        <div class="sub-fig">$${esc(d.stake)} a trade, up to ${esc(d.max_positions)} open${d.status !== 'running' && d.status_reason ? ' \u00b7 ' + esc(d.status_reason) : ''}</div></td>
      <td data-lab="Market"><span class="tick">${esc(marketShort(d.market))}</span></td>
      <td data-lab="Status">${mark(d.status, live)}</td>
      <td class="num" data-lab="Realized">${money(d.realized_pnl)}${d.curve && d.curve.length > 1 ? spark(d.curve, reg, 'Realized profit and loss') : ''}</td>
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
  async function viewSignin() {
    if (!S.me) { try { S.me = await api('/api/me'); } catch (e) { /* signed out: stay here */ } }
    if (S.me) return go('/', true);
    const err = new URLSearchParams(location.search).get('error');
    const msg = { cancelled: 'Sign-in was cancelled.', expired: 'That sign-in link expired. Try again.', google: "Google couldn't confirm your account. We may not have added you to the waitlist yet." }[err];
    document.body.classList.add('landing-body');
    root.innerHTML = `
      <div class="landing">
        <header class="lnav">
          <a class="lbrand" href="/">${ICON.mark}<span>Tau</span></a>
          <div class="lnav-actions">
            <a class="pill" href="/auth/google" data-native>Sign in</a>
            <button class="pill solid" data-action="waitlist-top">Join waitlist</button>
          </div>
        </header>
        <section class="lhero">
          <div class="lhero-copy">
            <h1>Turn an idea into a strategy that trades for you.</h1>
            <p class="lsub">Describe what you want to trade. An agent researches it, tests every idea on data it never saw, and only the strategies that pass can trade.</p>
            ${msg ? `<div class="lnotice">${esc(msg)}</div>` : ''}
            <div class="lcta" id="lcta">
              <a class="pill solid lg" href="/auth/google" data-native>${ICON.google}Continue with Google</a>
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
  const DEMO_IDEA_TEXT = 'Sell overpriced tails in the last hour before the 5pm close';
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
    body.innerHTML = `
      <div class="demo-prompt"><span class="you">J</span><div class="demo-bubble" id="demo-bubble"><span class="caret"></span></div></div>
      <div class="demo-status" id="demo-status"></div>
      <div class="demo-cards" id="demo-cards"></div>`;
    const bubble = body.querySelector('#demo-bubble');
    const status = body.querySelector('#demo-status');
    const cards = body.querySelector('#demo-cards');
    const type = (i) => {
      if (i <= DEMO_IDEA_TEXT.length) {
        bubble.innerHTML = esc(DEMO_IDEA_TEXT.slice(0, i)) + '<span class="caret"></span>';
        at(reduce ? 0 : 34, () => type(i + 1));
      } else {
        bubble.textContent = DEMO_IDEA_TEXT;
        research();
      }
    };
    const research = () => {
      status.innerHTML = `<span class="dspin"></span>Agent researching the idea…`;
      at(1100, () => { status.innerHTML = `<span class="dspin"></span>Writing strategies and backtesting on unseen data…`; });
      DEMO_STRATS.forEach((d, k) => at(1900 + k * 560, () => {
        const [t, meta, mk, pnl] = d;
        const el = document.createElement('div');
        el.className = 'dcard'; el.style.animationDelay = '0ms';
        el.innerHTML = `<b>${esc(t)}</b><span class="dmk ${mk === 'pass' ? 'pass' : 'void'}">${mk === 'pass' ? 'Passed' : 'Void'}</span><span class="dmeta">${esc(meta)} · ${esc(pnl)}</span>`;
        cards.appendChild(el);
      }));
      at(1900 + DEMO_STRATS.length * 560 + 300, () => {
        status.innerHTML = `${ICON.check}2 of 4 passed every gate — ready to deploy on paper.`;
      });
    };
    if (reduce) { bubble.textContent = DEMO_IDEA_TEXT; research(); } else type(0);
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
        pos.appendChild(el);
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
        loop.appendChild(el); shown.push(el);
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
          ${fig('Paper account value', usd(p.equity), { small: `${usd(p.cash)} cash \u00b7 ${usd(p.open_at_cost)} open at cost` })}
          ${fig('Today', usd(p.today_pnl, true), { v: p.today_pnl })}
          ${fig('All time', usd(p.total_pnl, true), { v: p.total_pnl, small: `${pct(p.roi)} on ${usd(p.deposited)} put in` })}
          ${fig('Open positions', d.open_positions.length, { small: stale ? '' : `history ${age(d.freshness.btc)} old` })}
        </dl>`;
      const reg = registry(d.deployments.map((x) => x.curve));
      const deps = d.deployments.length
        ? deploymentTable(d.deployments.map((x) => deploymentSlip(x, reg, false)).join(''), false)
        : `<div class="empty"><h3>Nothing deployed yet</h3><p>Agents research strategies and test each one on data they never saw. The ones that pass every gate can be deployed here, on paper first.</p><a class="btn" href="/research">Dispatch your first agent</a></div>`;
      const days = d.paper.daily.slice(-30);
      const maxAbs = Math.max(1, ...days.map((x) => Math.abs(+x.pnl)));
      const bars = days.length
        ? `<div class="bars-wrap"><div class="bars" role="img" aria-label="Daily profit and loss, last ${days.length} days">${days.map((x) => `<span class="${+x.pnl >= 0 ? 'up' : 'down'}" style="height:${Math.max(2, (Math.abs(+x.pnl) / maxAbs) * 36)}px" title="${esc(x.d)}: ${usd(x.pnl, true)}"></span>`).join('')}</div></div>`
        : '<p class="hint">Daily results appear once your strategies close trades.</p>';
      const stubs = (rows, closed) => rows.length
        ? rows.map((r) => `<div class="stub"><b>${esc(r.side.toUpperCase())} ${esc(r.qty)} × ${cents(+r.entry_price)}</b>
            <span>${closed ? money(+r.pnl) : usd(r.qty * r.entry_price)}</span>
            <small>${esc(r.title)} · <span class="tick">${esc(r.ticker)}</span> · ${r.mode === 'live' ? 'LIVE' : 'paper'} · ${when(closed ? r.closed_at : r.opened_at)}</small></div>`).join('')
        : `<p class="hint">${closed ? 'No settled trades yet.' : 'No open positions.'}</p>`;
      const main = `<div class="dash">
          <div>
            <section class="sect"><div class="sect-head"><h2>Deployed</h2>${d.deployments.some((x) => x.curve && x.curve.length > 1) ? '<span class="sect-note">Sparklines share one dollar scale</span>' : ''}</div>${deps}</section>
          </div>
          <aside>
            <section class="panel"><h3>Daily P&amp;L</h3>${bars}</section>
            <section class="panel"><h3>Open positions</h3>${stubs(d.open_positions, false)}</section>
            <section class="panel"><h3>Settled lately</h3>${stubs(d.recent_closed, true)}</section>
          </aside>
        </div>`;
      root.querySelector('#boardbody').innerHTML = board;
      root.querySelector('main').innerHTML = main;
    };
    await load();
    poll(load, 15000);
  }

  // ---------- research ----------
  async function viewResearch() {
    const me = S.me;
    const EXAMPLES = ["Sell overpriced tails in the last hour before the 5pm close", "Lean with Bitcoin's momentum into settlement when volatility is low", "Buy cheap longshots under 15\u00a2 when the model says they're underpriced", "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances"];
    shell('/research', boardTitle('Research', 'Describe an idea. An agent turns it into a research session \u2014 several concrete strategies it backtests on data it never saw, and only the ones that pass can trade.') +
      '<dl class="figures measure" id="rfigs" style="margin-top:14px"></dl>', `
      <form class="panel dispatch" id="dispatch">
        <h3>Start a research session</h3>
        <label class="field"><span>Describe your idea</span>
          <textarea class="input" name="prompt" maxlength="1000" rows="3" required placeholder="e.g. Sell overpriced tails in the last hour before the 5pm close"></textarea></label>
        <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end;justify-content:space-between">
          <fieldset class="field" style="border:0;padding:0;margin:0"><legend class="label" style="margin-bottom:6px">Market</legend>
            <div class="choice">${me.markets.map((m, i) => `<label><input type="radio" name="market" value="${m.key}" ${i === 0 ? 'checked' : ''}><span class="opt"><b>${esc(marketShort(m.key))}</b></span></label>`).join('')}</div>
          </fieldset>
          <button class="btn primary" type="submit">${ICON.spark2}Start session</button>
        </div>
        <div class="chips" aria-label="Example ideas">${EXAMPLES.map((x) => `<button type="button" class="chip" data-ex="${esc(x)}">${esc(x.length > 46 ? x.slice(0, 44) + '\u2026' : x)}</button>`).join('')}</div>
        <div id="dflash"></div>
        <p class="hint">A session takes a few minutes and keeps running if you leave this page.</p>
      </form>
      <section class="sect"><div class="sect-head"><h2>Your sessions</h2><p id="rcount"></p></div>
        <div id="flash"></div><div class="runs" id="runs">${loading(70)}${loading(70)}</div></section>`);
    root.querySelectorAll('[data-ex]').forEach((b) => { b.onclick = () => { const t = root.querySelector('textarea[name=prompt]'); t.value = b.dataset.ex; t.focus(); }; });
    const form = root.querySelector('#dispatch');
    form.onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const btn = form.querySelector('button[type=submit]');
      await busy(btn, async () => {
        try {
          const r = await api('/api/runs', { market: fd.get('market'), prompt: fd.get('prompt') });
          go('/research/' + r.id);
        } catch (err) { flash('#dflash', err.message, 'bad'); }
      });
    };
    const load = async () => {
      const d = await api('/api/runs');
      const tried = d.runs.reduce((a, r) => a + (r.hypotheses_tried || 0), 0);
      const passed = d.runs.reduce((a, r) => a + (r.strategies_passed || 0), 0);
      root.querySelector('#rfigs').innerHTML = fig('Researching now', d.counts.research_running) + fig('Waiting', d.counts.research_queued) +
        fig('Hypotheses tested', tried) + fig('Passed every gate', passed, { small: tried ? `${pct(passed / tried, false)} pass rate` : '' });
      root.querySelector('#rcount').textContent = d.runs.length ? `${d.runs.length} run${d.runs.length > 1 ? 's' : ''}` : '';
      root.querySelector('#runs').innerHTML = d.runs.length ? d.runs.map(runRow).join('')
        : `<div class="empty"><h3>No sessions yet</h3><p>Describe an idea above. The agent will turn it into several strategies, test each one on data it never saw, and mark each Passed or Void.</p></div>`;
    };
    await load();
    poll(load, 5000);
  }
  function runRow(r) {
    const active = r.status === 'running' || r.status === 'queued';
    const state = r.status === 'running' ? '<span class="pulse"></span>Researching'
      : r.status === 'queued' ? 'Waiting'
      : r.status === 'succeeded' ? `<span class="${r.strategies_passed ? 'gain' : ''}">${r.strategies_passed} of ${r.hypotheses_tried} passed</span>`
      : r.status === 'cancelled' ? 'Cancelled' : '<span class="loss">Failed</span>';
    return `<a class="run-row" href="/research/${r.id}">
      <span class="what"><b>${esc(sessionTitle(r))}</b><small>${esc(marketShort(r.market))}${r.error ? ' \u00b7 ' + esc(r.error) : ''}</small></span>
      <span class="state">${state}</span>
      <span class="when">${when(r.created_at)}</span></a>`;
  }

  async function viewRun(id) {
    shell('/research', '<div id="runboard">' + boardTitle('Research run') + '</div><dl class="figures measure" id="runfigs" style="margin-top:14px"></dl>', `
      <div class="printer">
        <section><div class="section-head"><h2>Agent log</h2><span id="runact"></span></div><div id="flash"></div><ol class="log" id="log" aria-live="polite"></ol></section>
        <section><div class="section-head"><h2>Hypotheses</h2><p>Newest first</p></div>
          <div id="feed">${strategyTable('')}</div></section>
      </div>`);
    let after = 0, shownStrategies = false;
    const hyp = [];
    const load = async () => {
      const d = await api(`/api/runs/${id}?after=${after}`);
      const r = d.run;
      const active = r.status === 'running' || r.status === 'queued';
      root.querySelector('#runboard').innerHTML = boardTitle(sessionTitle(r), `${esc(marketShort(r.market))} \u00b7 ${dirLabel(r.direction)}`);
      const started = r.started_at ? Date.parse(r.started_at) : null;
      const end = r.finished_at ? Date.parse(r.finished_at) : Date.now();
      root.querySelector('#runfigs').innerHTML =
        fig('Status', active ? (r.status === 'queued' ? 'Waiting' : 'Researching') : r.status === 'succeeded' ? 'Done' : r.status === 'cancelled' ? 'Cancelled' : 'Failed') +
        fig('Time', started ? Math.max(0, Math.round((end - started) / 60000)) + ' min' : '—') +
        fig('Hypotheses', r.hypotheses_tried || hyp.length) + fig('Passed', active ? '…' : r.strategies_passed);
      root.querySelector('#runact').innerHTML = active ? '<button class="btn danger small" id="cancel">Cancel run</button>' : (r.status === 'succeeded' ? '<a class="btn small" href="/strategies">All strategies</a>' : '');
      const cancel = root.querySelector('#cancel');
      if (cancel) cancel.onclick = () => armed(cancel, 'Confirm cancel', () => busy(cancel, async () => { await api(`/api/runs/${id}/cancel`, {}).catch((e) => alert0(e.message)); await load(); }));
      const log = root.querySelector('#log');
      const feed = root.querySelector('#feed');
      d.events.forEach((ev) => {
        after = Math.max(after, ev.id);
        const li = document.createElement('li');
        li.className = ev.kind;
        li.innerHTML = `<time>${clock(ev.created_at)}</time><span>${ev.kind === 'hypothesis' ? 'Tested <b>' + esc(ev.message) + '</b>' : esc(ev.message)}</span>`;
        log.appendChild(li);
        if (ev.kind === 'hypothesis' && !shownStrategies) {
          const s = { id: hyp.length + 1, market: r.market, direction: r.direction, title: ev.message, thesis: ev.data.thesis, status: 'queued', in_sample: ev.data.in_sample, created_at: ev.created_at };
          hyp.push(s);
          feed.querySelector('tbody').insertAdjacentHTML('afterbegin', strategySlip(s, null, { nolink: true, land: true }));
        }
      });
      if (r.status === 'succeeded' && !shownStrategies) {
        shownStrategies = true;
        const reg = registry(d.strategies.map((s) => s.equity));
        const order = { passed: 0, failed: 1, rejected: 2 };
        const sorted = d.strategies.slice().sort((a, b) => order[a.status] - order[b.status]);
        feed.innerHTML = strategyTable(sorted.map((s) => strategySlip(s, reg, { land: true })).join(''));
      }
      if (!active) clearTimers();
    };
    await load();
    poll(load, 2000);
  }
  const DIR_BRIEF = (k) => ((S.me.directions.find((d) => d.key === k)) || { brief: '' }).brief;

  // ---------- strategies ----------
  async function viewStrategies() {
    const q = new URLSearchParams(location.search);
    const f = { status: q.get('status') || 'passed', market: q.get('market') || '' };
    shell('/strategies', boardTitle('Strategies', 'Every strategy your agents researched. Passed ones can be deployed; void ones stay here so you can see what didn’t work.') +
      '<dl class="figures measure" id="sfigs" style="margin-top:14px"></dl>', `
      <div class="section-head">
        <div class="chips" role="group" aria-label="Status">${[['passed', 'Passed'], ['failed', 'Void'], ['rejected', 'Rejected'], ['', 'All']].map(([v, l]) => `<button class="chip" data-f="status" data-v="${v}" aria-pressed="${f.status === v}">${l}</button>`).join('')}</div>
        <div class="chips" role="group" aria-label="Market">${[['', 'Both markets'], ...S.me.markets.map((m) => [m.key, marketShort(m.key)])].map(([v, l]) => `<button class="chip" data-f="market" data-v="${v}" aria-pressed="${f.market === v}">${esc(l)}</button>`).join('')}</div>
      </div>
      <div id="slips" style="margin-top:16px">${loading(240)}</div>`);
    root.querySelectorAll('[data-f]').forEach((b) => {
      b.onclick = () => {
        f[b.dataset.f] = b.dataset.v;
        const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== '' || false));
        if (!f.status) p.set('status', '');
        go('/strategies?' + p.toString(), true);
      };
    });
    const [all, d] = await Promise.all([api('/api/strategies'), api('/api/strategies?' + new URLSearchParams(f))]);
    const count = (st) => all.strategies.filter((s) => s.status === st).length;
    root.querySelector('#sfigs').innerHTML = fig('Passed', count('passed')) + fig('Void on unseen data', count('failed')) + fig('Rejected in testing', count('rejected')) +
      fig('Pass rate', all.strategies.length ? pct(count('passed') / all.strategies.length, false) : '—');
    const reg = registry(d.strategies.map((s) => s.equity));
    root.querySelector('#slips').innerHTML = d.strategies.length ? strategyTable(d.strategies.map((s) => strategySlip(s, reg)).join(''))
      : `<div class="empty"><h3>Nothing here yet</h3><p>${all.strategies.length ? 'Try another filter.' : 'Start a research session and the strategies it finds will land here.'}</p>${all.strategies.length ? '' : '<a class="btn" href="/research">Go to Research</a>'}</div>`;
  }

  async function viewStrategy(id) {
    shell('/strategies', boardTitle('Strategy') + '<dl class="figures measure" id="figs" style="margin-top:14px"></dl>', loading(420));
    const s = await api('/api/strategies/' + id);
    const ins = s.in_sample || {}, oos = s.out_of_sample;
    const figsFor = (r) => fig('Unseen-data P&L', r.out_of_sample ? usd(r.out_of_sample.pnl, true) : '—', { v: r.out_of_sample && r.out_of_sample.pnl, small: r.out_of_sample ? `${r.out_of_sample.trades} trades the agent never saw` : 'Rejected before the unseen test' }) +
      fig('In-sample P&L', usd(r.in_sample.pnl, true), { v: r.in_sample.pnl, small: `${r.in_sample.trades} trades` }) +
      fig('Return on capital', r.out_of_sample ? pct(r.out_of_sample.roi) : '—', { small: `$${fmt0.format(r.capital || 0)} at risk at most` }) +
      fig('Tried to find it', s.hypotheses_tried ? `1 of ${s.hypotheses_tried}` : '—', { small: 'More tries means weaker evidence' });
    root.querySelector('.board-title').outerHTML = boardTitle(serial(s.id) + ' · ' + marketShort(s.market), esc(dirLabel(s.direction)));
    root.querySelector('#figs').innerHTML = figsFor(s);
    const canDeploy = s.status === 'passed';
    const liveWhy = !S.me.live_trading_available ? 'Live trading isn’t open yet.' : !S.me.kalshi_connected ? 'Connect Kalshi on the Funds page first.' : s.side !== 'yes' ? 'Live supports YES-only strategies for now.' : '';
    const metricRows = (m) => m ? `<dl>
        <dt>P&amp;L after fees</dt><dd class="${tone(m.pnl)}">${usd(m.pnl, true)}</dd>
        <dt>Trades</dt><dd>${m.trades}${m.trades_per_day != null ? ` <small class="hint">(${m.trades_per_day}/day)</small>` : ''}</dd>
        <dt>Win rate</dt><dd>${pct(m.win_rate, false)}</dd>
        <dt>Fees paid</dt><dd>${usd(m.fees)}</dd>
        <dt>Profit factor</dt><dd>${m.profit_factor == null ? '—' : m.profit_factor}</dd>
        <dt>Worst drawdown</dt><dd>${usd(m.max_drawdown)}</dd>
        <dt>Sharpe (daily)</dt><dd>${m.sharpe == null ? '—' : m.sharpe}</dd></dl>` : '<p class="hint">Not run: it lost money in testing, so it never got to see unseen data.</p>';
    const gatesHtml = (gs) => gs ? `<ul class="gates">${gs.map((g) => `<li class="${g.ok ? 'ok' : 'no'}">${g.ok ? ICON.check : ICON.cross}<span>${esc(g.name)}<small>needs ${esc(g.threshold)}</small></span><span class="v">${typeof g.value === 'number' && /\$|drawdown|money/i.test(g.name + g.threshold) ? usd(g.value) : esc(g.value == null ? '—' : g.value)}</span></li>`).join('')}</ul>` : '<p class="hint">Gates only run for finalists that made money in testing.</p>';
    const trades = (s.recent_trades || []).length ? `<table class="table stack"><thead><tr><th>Opened</th><th>Contract</th><th>Side</th><th class="num">Entry</th><th class="num">Exit</th><th class="num">P&amp;L</th></tr></thead><tbody>
        ${s.recent_trades.map((t) => `<tr><td>${esc(new Date(t.opened.replace('Z', ':00Z')).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }))}</td><td class="tick">${esc(t.ticker)}</td><td>${esc(t.side.toUpperCase())} ×${t.qty}</td><td class="num">${cents(t.entry)}</td><td class="num">${cents(t.exit)} <small class="hint">${esc(t.reason)}</small></td><td class="num ${tone(t.pnl)}">${usd(t.pnl, true)}</td></tr>`).join('')}
      </tbody></table>` : '<p class="hint">No unseen-data trades to show.</p>';
    root.querySelector('main').innerHTML = `
      <div id="flash"></div>
      <div class="detail">
        <div>
          <article class="sheet-doc">
            <p class="doc-mark">${mark(s.status)}</p>
            <h2>${esc(s.title)}</h2>
            <p class="thesis">${esc(s.thesis)}</p>
            <h3 class="sheet-h">The rule, in plain words</h3>
            <ul class="rules">${s.rules.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>
            <div id="sheet-results">
              ${s.equity ? equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from) : ''}
              <div class="split"><div><h4>Tested on (in-sample)</h4>${metricRows(ins)}</div><div><h4>Never seen (out-of-sample)</h4>${metricRows(oos)}</div></div>
            </div>
            ${s.dataset ? `<p class="hint" style="margin-top:12px">${esc(marketLabel(s.market))}. History: ${esc(s.dataset.start.slice(0, 10))} to ${esc(s.dataset.end.slice(0, 10))}. The agent only saw data before ${esc((s.dataset.out_of_sample_from || '').slice(0, 10))}. Every fill pays the ask or bid plus Kalshi's taker fee.</p>` : ''}
            <h3 class="sheet-h">Latest unseen trades</h3>${trades}
            <details class="raw"><summary>Exact spec</summary><pre>${esc(JSON.stringify(s.spec, null, 2))}</pre></details>
          </article>
        </div>
        <aside>
          <section class="panel"><h3>Deploy</h3>
            ${canDeploy ? `<div style="display:grid;gap:10px">
                <button class="btn" id="dep-paper">Deploy on paper</button>
                <button class="btn ghost" id="dep-live" ${liveWhy ? 'aria-disabled="true"' : ''}>Deploy with live money</button>
                ${liveWhy ? `<p class="hint">${esc(liveWhy)}</p>` : ''}
                <form id="live-confirm" hidden style="display:grid;gap:8px">
                  <p class="hint">This trades real money in your Kalshi account. Type <b>LIVE</b> to confirm.</p>
                  <input class="input" name="confirm" autocomplete="off" aria-label="Type LIVE to confirm">
                  <button class="btn" type="submit">Confirm live deployment</button>
                </form>
                <div id="depflash"></div>
              </div>` : `<p class="hint">${s.status === 'failed' ? 'Void: it failed at least one gate on data the agent never saw, so it can’t be deployed.' : 'Rejected: it lost money in testing and was never a finalist.'}</p>`}
            ${s.deployments.length ? `<p class="hint" style="margin-top:12px">Already deployed: ${s.deployments.map((d) => `#${d.id} (${esc(d.mode)}, ${esc(d.status)})`).join(', ')}. <a href="/deploy">Open the board</a></p>` : ''}
          </section>
          <section class="panel"><h3>Gates</h3><div id="gates">${gatesHtml(s.gates)}</div></section>
          ${s.status !== 'rejected' ? `<section class="panel" id="whatif"><h3>What if…</h3>
            <p class="hint" style="margin-bottom:6px">Move a dial and the whole sheet re-runs.</p>
            <div class="dial"><div class="top"><label class="label" for="wf">Fees</label><output id="wfo">1.0×</output></div><input type="range" id="wf" min="0" max="3" step="0.25" value="1"></div>
            <div class="dial"><div class="top"><label class="label" for="ws">Slippage per fill</label><output id="wso">0¢</output></div><input type="range" id="ws" min="0" max="5" step="1" value="0"></div>
            <div class="dial"><div class="top"><label class="label" for="wk">Stake per trade</label><output id="wko">$${esc(s.stake)}</output></div><input type="range" id="wk" min="1" max="200" step="1" value="${Math.min(200, s.stake)}"></div>
            <div id="wflash" aria-live="polite"></div>
          </section>` : ''}
        </aside>
      </div>`;
    const depPaper = root.querySelector('#dep-paper');
    if (depPaper) depPaper.onclick = () => busy(depPaper, async () => {
      try { await api('/api/deployments', { strategy_id: s.id, mode: 'paper' }); go('/deploy'); } catch (e) { flash('#depflash', e.message, 'bad'); }
    });
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
        wi.querySelector('#wso').textContent = slip + '¢';
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
    const u = S.me.user;
    shell('/deploy', boardTitle('Deploy', 'Your strategies trading now. Talk to the agent to adjust them.') +
      '<dl class="figures measure" id="dfigs" style="margin-top:14px"></dl>', `
      <div class="seg" role="group" aria-label="View"><button aria-pressed="true" data-view="board">Board</button><button aria-pressed="false" data-view="chat">Agent chat</button></div>
      <div class="deploy" data-view="board" id="deploy">
        <div class="deploy-board"><div id="flash"></div><div id="deps">${loading(260)}</div>
          <section class="section"><div class="section-head"><h2>Open positions</h2></div><div id="openpos"></div></section>
        </div>
        <section class="chat" aria-label="Agent chat">
          <div class="chat-head">
            <div class="t"><h2>Agent</h2><span class="hint" id="agentstate"></span></div>
            <div class="autopilot ${u.autopilot ? 'on' : ''}" id="ap">
              <span><b>Autopilot</b>${u.autopilot ? 'The agent adjusts and deploys paper strategies without asking. It can always pause; it never touches live money.' : 'Off. The agent proposes changes and you approve them.'}</span>
              <label class="switch"><span class="vh">Autopilot</span><input type="checkbox" id="apswitch" ${u.autopilot ? 'checked' : ''}></label>
            </div>
          </div>
          <div class="messages" id="messages" aria-live="polite"></div>
          <form class="composer" id="composer">
            <label class="vh" for="msg">Message the agent</label>
            <textarea class="input" id="msg" rows="1" maxlength="2000" placeholder="Message the agent…"></textarea>
            <button class="btn" type="submit" aria-label="Send">${ICON.send}</button>
          </form>
        </section>
      </div>`);
    const wrap = root.querySelector('#deploy');
    root.querySelectorAll('.seg button').forEach((b) => (b.onclick = () => {
      wrap.dataset.view = b.dataset.view;
      root.querySelectorAll('.seg button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    }));
    const sw = root.querySelector('#apswitch');
    sw.onchange = async () => {
      const on = sw.checked;
      if (on && !confirmAutopilot.armed) { sw.checked = false; confirmAutopilot.armed = true; root.querySelector('#ap span').innerHTML = '<b>Turn on autopilot?</b>Flip again to confirm. The agent will act on paper strategies without asking you first.'; setTimeout(() => (confirmAutopilot.armed = false), 6000); return; }
      confirmAutopilot.armed = false;
      try { await api('/api/settings', { autopilot: on }); S.me.user.autopilot = on; } catch (e) { sw.checked = !on; alert0(e.message); }
      viewDeployRefreshAP();
      loadChat();
    };
    const viewDeployRefreshAP = () => {
      const ap = root.querySelector('#ap');
      const on = S.me.user.autopilot;
      ap.classList.toggle('on', on);
      ap.querySelector('span').innerHTML = on ? '<b>Autopilot</b>The agent adjusts and deploys paper strategies without asking. It can always pause; it never touches live money.' : '<b>Autopilot</b>Off. The agent proposes changes and you approve them.';
    };
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
      root.querySelector('#openpos').innerHTML = d.open_positions.length ? `<table class="table stack"><thead><tr><th>Strategy</th><th>Contract</th><th>Side</th><th class="num">Cost</th><th class="num">Settles</th></tr></thead><tbody>
        ${d.open_positions.map((p) => `<tr><td>${esc(p.title)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : ''}</td><td class="tick">${esc(p.ticker)}</td><td>${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(+p.entry_price)}</td><td class="num">${usd(p.qty * p.entry_price + +p.entry_fee)}</td><td class="num">${clock(p.market_close_time)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="hint">No open positions.</p>';
    };
    let lastId = 0;
    const msgs = root.querySelector('#messages');
    const renderMsg = (m) => {
      const who = m.role === 'user' ? 'You' : m.role === 'agent' ? 'Agent' : 'Tau';
      const prop = m.proposal_id ? `<div class="proposal" data-prop="${m.proposal_id}">${m.proposal_status === 'pending'
        ? `<button class="btn small" data-decide="approve">Approve</button><button class="btn ghost small" data-decide="reject">Decline</button>`
        : `<span class="state ${m.proposal_status === 'applied' ? 'gain' : ''}">${m.proposal_status === 'applied' ? 'Applied' : 'Declined'}</span>`}</div>` : '';
      return `<div class="msg ${m.role}" data-id="${m.id}"><span class="who">${who} · ${clock(m.created_at)}</span>${esc(m.content)}${prop}</div>`;
    };
    const loadChat = async (full) => {
      const d = await api('/api/chat?after=' + (full ? 0 : lastId));
      const nearBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 80;
      if (full) msgs.innerHTML = '';
      msgs.querySelector('.typing') && msgs.querySelector('.typing').remove();
      d.messages.forEach((m) => { lastId = Math.max(lastId, m.id); msgs.insertAdjacentHTML('beforeend', renderMsg(m)); });
      if (!msgs.children.length) msgs.innerHTML = `<div class="msg system">Ask anything about your deployments: "How is the volatility strategy doing?" or "Make it more selective." The agent backtests every change before suggesting it.</div>`;
      if (d.agent_busy) msgs.insertAdjacentHTML('beforeend', '<div class="typing" aria-label="Agent is thinking"><i></i><i></i><i></i></div>');
      root.querySelector('#agentstate').textContent = d.agent_busy ? 'thinking…' : '';
      if (nearBottom || full) msgs.scrollTop = msgs.scrollHeight;
      return d.agent_busy;
    };
    msgs.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-decide]');
      if (!b) return;
      const pid = b.closest('[data-prop]').dataset.prop;
      await busy(b, async () => {
        try { await api(`/api/proposals/${pid}/${b.dataset.decide}`, {}); await loadChat(true); await loadBoard(); } catch (err) { alert0(err.message); }
      });
    });
    const form = root.querySelector('#composer');
    const ta = root.querySelector('#msg');
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(160, ta.scrollHeight) + 'px'; });
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
    form.onsubmit = async (e) => {
      e.preventDefault();
      const content = ta.value.trim();
      if (!content) return;
      await busy(form.querySelector('button'), async () => {
        try { await api('/api/chat', { content }); ta.value = ''; ta.style.height = ''; await loadChat(); } catch (err) { alert0(err.message); }
      });
    };
    await Promise.all([loadBoard(), loadChat(true)]);
    poll(loadBoard, 10000);
    poll(() => loadChat(), 3000);
  }
  const confirmAutopilot = { armed: false };

  // ---------- funds ----------
  async function viewFunds() {
    shell('/funds', boardTitle('Funds') + '<dl class="figures measure" id="ffigs" style="margin-top:14px"></dl>', loading(300));
    const load = async () => {
      const d = await api('/api/funds');
      const k = d.kalshi;
      root.querySelector('#ffigs').innerHTML = fig('Paper cash', usd(d.paper.cash), { cls: 'lead', small: 'Practice money for paper trading' }) +
        fig('Kalshi cash', k.connected ? (k.balance == null ? 'Unavailable' : usd(k.balance)) : 'Not connected', { small: k.connected ? `Key ${esc(k.key_id)}` : 'Needed only for live trading' }) +
        fig('Money held by Tau', '$0.00', { small: 'Live funds stay in your Kalshi account' });
      root.querySelector('main').innerHTML = `<div id="flash"></div><div class="funds">
        <section class="panel">
          <h3>Paper account</h3>
          <p class="lede" style="margin-bottom:14px">Add or take out practice money. Paper strategies trade the real market with it, so results are realistic, but nothing real is at stake.</p>
          <form id="paper" class="amount">
            <label class="field"><span>Amount</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="500"></label>
            <button class="btn" data-kind="deposit" type="submit">Add</button>
            <button class="btn ghost" data-kind="withdraw" type="submit">Withdraw</button>
          </form>
          <div id="pflash" style="margin-top:10px"></div>
          <h3 style="margin-top:24px">History</h3>
          <table class="table stack"><thead><tr><th>When</th><th>What</th><th class="num">Amount</th></tr></thead><tbody>
            ${d.paper.ledger.map((r) => `<tr><td class="hint lead-cell">${when(r.created_at)}</td><td>${esc(r.memo || r.kind)}</td><td class="num ${tone(+r.amount)}">${usd(r.amount, true)}</td></tr>`).join('')}
          </tbody></table>
        </section>
        <section class="panel">
          <h3>Kalshi account (live money)</h3>
          ${k.connected ? `
            <dl class="kv"><dt>API key</dt><dd>${esc(k.key_id)}</dd><dt>Cash at Kalshi</dt><dd>${k.balance == null ? 'Couldn’t read it just now' : usd(k.balance)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">Deposits and withdrawals happen at Kalshi, in your own account. Tau only places trades for strategies you deploy live.</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <a class="btn" href="${esc(k.funding_url)}" target="_blank" rel="noopener">Deposit or withdraw at Kalshi ${ICON.ext}</a>
              <button class="btn danger" id="disconnect">Disconnect</button>
            </div>` : `
            <p class="lede" style="margin-bottom:12px">Live trading runs in your own Kalshi account, so we never hold your money. Connect an API key to enable it.</p>
            <ol class="steps"><li>On Kalshi, open Account → API keys and create a key.</li><li>Copy the key ID and download the private key file.</li><li>Paste both below. We encrypt the private key and check it with Kalshi before saving.</li></ol>
            <form id="kalshi" style="display:grid;gap:12px">
              <label class="field"><span>Key ID</span><input class="input" name="key_id" autocomplete="off" spellcheck="false" required></label>
              <label class="field"><span>Private key</span><textarea class="input" name="private_key" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
              <button class="btn" type="submit">Verify and connect</button>
            </form>`}
          <div id="kflash" style="margin-top:10px"></div>
        </section></div>`;
      const pf = root.querySelector('#paper');
      let kind = 'deposit';
      pf.querySelectorAll('button').forEach((b) => (b.onclick = () => (kind = b.dataset.kind)));
      pf.onsubmit = async (e) => {
        e.preventDefault();
        const btn = pf.querySelector(`[data-kind="${kind}"]`);
        await busy(btn, async () => {
          try { await api('/api/funds/paper', { kind, amount: +pf.amount.value }); await load(); flash('#pflash', kind === 'deposit' ? 'Added to your paper account.' : 'Withdrawn from your paper account.', 'good'); } catch (err) { flash('#pflash', err.message, 'bad'); }
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
      return `<a class="snap" href="/strategies/${snap.id}"><div class="snap-head"><b>${esc(snap.title)}</b>${mark(snap.status)}</div>
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
  function postCard(p) {
    return `<article class="post" data-id="${p.id}">
      <div class="post-head">${avatar(p.picture, p.author)}<div><b>${esc(p.author)}</b><span class="when">${when(p.created_at)}</span></div></div>
      ${p.body ? `<p class="post-body">${esc(p.body)}</p>` : ''}
      ${postSnapshot(p.snapshot)}
      <div class="post-actions">
        <button class="pact like ${p.liked ? 'on' : ''}" data-act="like" aria-pressed="${p.liked}">${ICON.heart}<span class="c">${p.likes || ''}</span></button>
        <button class="pact" data-act="comments">${ICON.comment}<span class="c">${p.comments || ''}</span></button>
      </div>
      <div class="comments" hidden></div>
    </article>`;
  }
  async function viewCommunity() {
    shell('/community', boardTitle('Community', 'Share a strategy, an idea, or how your money is doing. Like and reply to other traders.'), `
      <div class="feedwrap">
        <form class="panel composer-post" id="composer-post">
          <textarea class="input" id="post-body" maxlength="2000" rows="2" placeholder="Share an idea, a strategy, or how it's going…"></textarea>
          <div class="post-tools">
            <label class="field" style="min-width:0;flex:1"><span class="vh">Attach a strategy</span>
              <select id="post-strat"><option value="">Attach a strategy… (optional)</option></select></label>
            <button class="btn sm" type="button" data-share="pnl">${ICON.up}Share my P&amp;L</button>
            <button class="btn primary sm" type="submit">Post</button>
          </div>
          <div id="post-flash"></div>
        </form>
        <div id="feed">${loading(120)}${loading(120)}</div>
      </div>`);
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
          await api('/api/community', { body, kind, ref_id });
          root.querySelector('#post-body').value = ''; root.querySelector('#post-strat').value = '';
          await load();
        } catch (e) { flash('#post-flash', e.message, 'bad'); }
      });
    };
    form.onsubmit = (e) => { e.preventDefault(); const ref = root.querySelector('#post-strat').value; submit(ref ? 'strategy' : 'note', ref || undefined); };
    form.querySelector('[data-share="pnl"]').onclick = () => submit('pnl');
    const feed = root.querySelector('#feed');
    feed.addEventListener('click', async (e) => {
      const btn = e.target.closest('.pact'); if (!btn) return;
      const art = btn.closest('.post'); const pid = art.dataset.id;
      if (btn.dataset.act === 'like') {
        try {
          const r = await api(`/api/community/${pid}/like`, {});
          btn.classList.toggle('on', r.liked); btn.setAttribute('aria-pressed', r.liked);
          const c = btn.querySelector('.c'); const n = (parseInt(c.textContent || '0', 10) || 0) + (r.liked ? 1 : -1);
          c.textContent = n > 0 ? n : '';
        } catch (err) { alert0(err.message); }
      } else {
        const box = art.querySelector('.comments');
        if (!box.hidden) { box.hidden = true; return; }
        box.hidden = false; box.innerHTML = loading(40);
        const d = await api(`/api/community/${pid}/comments`).catch(() => ({ comments: [] }));
        box.innerHTML = `${d.comments.map((c) => `<div class="cmt">${avatar(c.picture, c.author)}<div><b>${esc(c.author)}</b> <span class="when">${when(c.created_at)}</span><p>${esc(c.body)}</p></div></div>`).join('')}
          <form class="cmt-form"><input class="input" maxlength="1000" placeholder="Write a reply…" required><button class="btn sm" type="submit">Reply</button></form>`;
        box.querySelector('.cmt-form').onsubmit = async (ev) => {
          ev.preventDefault();
          const inp = box.querySelector('input'); const body = inp.value.trim(); if (!body) return;
          await busy(box.querySelector('button'), async () => {
            try { await api(`/api/community/${pid}/comments`, { body }); inp.value = '';
              const cc = art.querySelector('[data-act="comments"] .c'); cc.textContent = (parseInt(cc.textContent || '0', 10) || 0) + 1;
              box.hidden = true; box.innerHTML = '';
            } catch (err) { alert0(err.message); }
          });
        };
      }
    });
    const load = async () => {
      const d = await api('/api/community');
      feed.innerHTML = d.posts.length ? d.posts.map(postCard).join('')
        : `<div class="empty"><h3>No posts yet</h3><p>Be the first. Share a strategy an agent found, drop an idea worth researching, or post how your paper book is doing.</p></div>`;
    };
    await load();
    poll(load, 20000);
  }
  const STATUS_WORD = { passed: 'passed', failed: 'void', rejected: 'rejected' };

  render();
})();
