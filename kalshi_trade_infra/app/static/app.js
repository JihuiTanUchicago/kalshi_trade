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
  // Minimal safe markdown: escape first (so output has no raw HTML), then a tiny subset.
  // Only http(s) links — never javascript:/data: — so there's no XSS surface.
  const mdLite = (s) => {
    let t = esc(s);
    t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    t = t.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
    t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
    t = t.replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener nofollow">$1</a>');
    t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener nofollow">$2</a>');
    return t.replace(/\n/g, '<br>');
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
  const MKT_SHORT = { btc15m: 'BTC 15-min', btc_daily: 'BTC 5pm', eth15m: 'ETH 15-min', eth_daily: 'ETH 5pm', sol_daily: 'SOL 5pm', xrp_daily: 'XRP 5pm' };
  const marketShort = (k) => (!k ? 'Agent’s choice' : MKT_SHORT[k] || marketLabel(k));
  // Link a strategy's market to its Kalshi series page.
  const marketKalshiUrl = (k) => { const m = (S.me && S.me.markets || []).find((x) => x.key === k); return m && m.series ? `https://kalshi.com/markets/${m.series.toLowerCase()}` : null; };
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
    [/^\/explore$/, viewExplore],
    [/^\/billing$/, viewBilling],
    [/^\/admin$/, viewAdmin],
    [/^\/system$/, viewSystem],
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
  const NAV = [['/', 'Dashboard', 'dashboard'], ['/research', 'Research', 'research'], ['/strategies', 'Strategies', 'strategies'], ['/explore', 'Explore', 'explore'], ['/deploy', 'Deploy', 'deploy'], ['/community', 'Community', 'community'], ['/funds', 'Funds', 'funds']];
  // The operator can flip into a plain-user view. Only their own account is an
  // admin at all (server decides); the toggle just hides the admin surface so
  // they can see what a normal user sees. Default: admin view on.
  const isAdmin = () => !!(S.me && S.me.is_admin);
  const adminViewOn = () => isAdmin() && localStorage.getItem('tau_admin_off') !== '1';
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
        <span class="asof">${adminToggle}<span class="profile"><button class="profile-trig" data-action="profile" aria-haspopup="true" aria-expanded="false">${esc(u.name || u.email)}<svg class="caret" width="9" height="9" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.3"/></svg></button><span class="profile-menu" hidden><a href="/billing">Billing</a><button class="profile-item" data-action="signout">Sign out</button></span></span></span>
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
    const at = root.querySelector('[data-action="admintoggle"]');
    if (at) at.onclick = () => {
      const turningOff = adminViewOn();
      localStorage.setItem('tau_admin_off', turningOff ? '1' : '0');
      if (turningOff && location.pathname === '/admin') go('/', true); else render();
    };
    mountHotRail();
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
  // devCurve (optional): a second, realized series replayed read-only against
  // the Kalshi demo environment. Drawn dashed in the accent colour with a legend
  // so "Simulated" and "Kalshi dev" read apart. Omitting it keeps the old chart.
  function equityChart(curve, cutoffIso, devCurve) {
    const W = 760, H = 236, L = 52, R = 10, T = 30, B = 26;
    if (!curve || curve.length < 2) return `<div class="empty"><p>Not enough trades to draw an equity curve.</p></div>`;
    const dev = devCurve && devCurve.length > 1 ? devCurve : null;
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
  const STRAT_HEAD = (pick) => `<thead><tr>${pick ? '<th class="pickcol"><input type="checkbox" id="pick-all" aria-label="Select all deployable"></th>' : ''}<th>Strategy</th><th>Market</th><th class="num">Unseen P&amp;L${glo('unseen')}</th><th class="num">Trades</th><th class="num">Win</th><th>Tried</th><th>Status</th></tr></thead>`;
  const strategyTable = (rows, pick) => `<div class="sheet"><table class="stack t-strat">${STRAT_HEAD(pick)}<tbody>${rows}</tbody></table></div>`;
  function strategySlip(s, reg, opts = {}) {
    const oos = s.out_of_sample, ins = s.in_sample || {};
    const m = oos || ins;
    const tried = s.hypotheses_tried ? `1 of ${s.hypotheses_tried}` : s.parent_id ? 'Adjustment' : '\u2014';
    const name = opts.nolink ? esc(s.title) : `<a href="/strategies/${s.id}">${esc(s.title)}</a>`;
    const pickCell = opts.pick ? (s.status === 'passed'
      ? `<td class="pickcol" data-lab="Deploy"><input type="checkbox" class="pick" data-id="${s.id}" aria-label="Select for deployment"></td>`
      : '<td class="pickcol" data-lab=""></td>') : '';
    return `<tr class="${opts.land ? 'washed' : ''}">${pickCell}
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
    const hr = document.getElementById('hotrail'); if (hr) hr.remove();
    document.body.classList.remove('hot-open');
    if (!S.me) { try { S.me = await api('/api/me'); } catch (e) { /* signed out: stay here */ } }
    if (S.me) return go('/', true);
    const q = new URLSearchParams(location.search);
    const err = q.get('error');
    const msg = q.has('pending')
      ? "You're on the waitlist — we'll email you the moment you're approved. (Access is invite-only right now.)"
      : { cancelled: 'Sign-in was cancelled.', expired: 'That sign-in link expired. Try again.', google: "Google couldn't confirm your account. We may not have added you to the waitlist yet." }[err];
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
    const DEMO_PROMPT = "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances";
    const mdl = await api('/api/models').catch(() => ({ models: [], default: '' }));
    const modelOpts = (mdl.models || []).map((m) => `<option value="${esc(m.key)}"${m.key === mdl.default ? ' selected' : ''}>${esc(m.label)}</option>`).join('');
    shell('/research', boardTitle('Research', 'Describe an idea. An agent turns it into a research session \u2014 several concrete strategies it backtests on data it never saw, and only the ones that pass can trade.') +
      '<dl class="figures measure" id="rfigs" style="margin-top:14px"></dl>', `
      <form class="panel dispatch" id="dispatch">
        <h3>Start a research session</h3>
        ${me.needs_card ? `<div class="notice" role="status">${ICON.warn}<span>Add a payment method to start researching. Your $${me.free_bonus} in free credits unlock the moment a card is on file — you won't be charged until they run out. <a href="/billing">Add a card →</a></span></div>` : ''}
        <label class="field"><span>Describe your idea</span>
          <textarea class="input" name="prompt" maxlength="1000" rows="3" required placeholder="Bro idk just give me a trading strategy frfr&#10;&#10;…or be specific: &quot;Sell overpriced tails in the last hour before the 5pm close.&quot;"></textarea></label>
        <div class="dispatch-tune" style="display:flex;gap:20px;flex-wrap:wrap;align-items:center;margin-top:2px">
          ${modelOpts ? `<label class="field" style="margin:0"><span>Model</span>
            <select class="input" name="model" id="rmodel" style="width:184px">${modelOpts}</select></label>` : ''}
          <label class="field" style="margin:0"><span>Strategies to test</span>
            <input class="input" type="number" name="max_hypotheses" id="maxhyp" min="1" max="50" value="10" style="width:92px"></label>
          <label class="switch" style="margin-top:18px"><input type="checkbox" name="run_forever" id="runforever" checked><span>Let it run until I stop it</span></label>
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end;justify-content:space-between">
          <fieldset class="field" style="border:0;padding:0;margin:0"><legend class="label" style="margin-bottom:6px">Market</legend>
            <div class="choice"><label><input type="radio" name="market" value="" checked><span class="opt"><b>Agent's choice</b></span></label>${me.markets.map((m) => `<label><input type="radio" name="market" value="${m.key}"><span class="opt"><b>${esc(marketShort(m.key))}</b></span></label>`).join('')}</div>
          </fieldset>
          <button class="btn primary" type="submit" ${me.needs_card ? 'aria-disabled="true"' : ''}>${ICON.spark2}Start session</button>
        </div>
        <div class="chips" aria-label="Try the demo"><button type="button" class="chip ex" data-ex="${esc(DEMO_PROMPT)}">${ICON.spark2}Try the demo \u2014 Todd's random walk</button></div>
        <div id="dflash"></div>
        <p class="hint">A session takes a few minutes and keeps running if you leave this page.</p>
      </form>
      <section class="sect"><div class="sect-head"><h2>Your sessions</h2><p id="rcount"></p></div>
        <div id="flash"></div><div class="runs" id="runs">${loading(70)}${loading(70)}</div></section>`);
    root.querySelectorAll('[data-ex]').forEach((b) => { b.onclick = () => { const t = root.querySelector('textarea[name=prompt]'); t.value = b.dataset.ex; t.focus(); }; });
    const form = root.querySelector('#dispatch');
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
    const load = async () => {
      const d = await api('/api/runs');
      const tried = d.runs.reduce((a, r) => a + (r.hypotheses_tried || 0), 0);
      const passed = d.runs.reduce((a, r) => a + (r.strategies_passed || 0), 0);
      root.querySelector('#rfigs').innerHTML = fig('Researching now', d.counts.research_running) + fig('Waiting', d.counts.research_queued) +
        fig('Hypotheses tested', tried) + fig('Passed every gate' + glo('gate'), passed, { small: tried ? `${pct(passed / tried, false)} pass rate` : '' });
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
      : r.status === 'cancelled' ? 'Cancelled' : '<span class="loss">Failed</span>';
    // status band: a thin color rule so passed/void/failed reads at a glance
    const band = r.status === 'succeeded' ? (r.strategies_passed ? 'ok' : 'void') : r.status === 'failed' ? 'fail' : r.status === 'cancelled' ? 'void' : 'live';
    return `<a class="run-card ${band}" href="/research/${r.id}">
      <span class="run-title"><b>${esc(sessionTitle(r))}</b></span>
      <span class="run-meta">${esc(marketShort(r.market))}${r.error ? ' \u00b7 ' + esc(r.error) : ''}</span>
      <span class="run-foot"><span class="run-state">${state}</span><span class="run-when">${when(r.created_at)}</span></span></a>`;
  }

  async function viewRun(id) {
    shell('/research', '<div id="runboard">' + boardTitle('Research run') + '</div><dl class="figures measure" id="runfigs" style="margin-top:14px"></dl>', `
      <div class="printer">
        <section><div class="section-head"><h2>Agent log</h2><span id="runact"></span></div><div id="flash"></div><ol class="log" id="log" aria-live="polite"></ol></section>
        <section><div class="section-head"><h2>Hypotheses</h2><p>Best unseen P&L first</p></div>
          <div id="feed">${strategyTable('')}</div></section>
      </div>`);
    let after = 0, tried = 0, lastFeedSig = '';
    const load = async () => {
      const d = await api(`/api/runs/${id}?after=${after}`);
      const r = d.run;
      const active = r.status === 'running' || r.status === 'queued';
      root.querySelector('#runboard').innerHTML = boardTitle(sessionTitle(r), `${esc(marketShort(r.market))} \u00b7 ${dirLabel(r.direction)}`);
      const started = r.started_at ? Date.parse(r.started_at) : null;
      const end = r.finished_at ? Date.parse(r.finished_at) : Date.now();
      root.querySelector('#runfigs').innerHTML =
        fig('Status', active ? (r.status === 'queued' ? 'Waiting<span class="working" aria-label="in process"></span>' : 'Researching<span class="working" aria-label="in process"></span>') : r.status === 'succeeded' ? 'Done' : r.status === 'cancelled' ? 'Cancelled' : 'Failed') +
        fig('Time', started ? Math.max(0, Math.round((end - started) / 60000)) + ' min' : '—') +
        fig('Hypotheses', r.hypotheses_tried || tried) + fig('Passed', active ? '…' : r.strategies_passed);
      root.querySelector('#runact').innerHTML = active ? '<button class="btn danger small" id="cancel">Cancel run</button>' : (r.status === 'succeeded' ? '<a class="btn small" href="/strategies">All strategies</a>' : '');
      const cancel = root.querySelector('#cancel');
      if (cancel) cancel.onclick = () => armed(cancel, 'Confirm cancel', () => busy(cancel, async () => { await api(`/api/runs/${id}/cancel`, {}).catch((e) => alert0(e.message)); await load(); }));
      const log = root.querySelector('#log');
      const feed = root.querySelector('#feed');
      d.events.forEach((ev) => {
        after = Math.max(after, ev.id);
        const li = document.createElement('li');
        li.className = ev.kind;
        let inner;
        if (ev.kind === 'hypothesis') {
          inner = 'Tested <b>' + esc(ev.message) + '</b>';
        } else if (ev.kind === 'verdict') {
          const st = ev.data && ev.data.status;
          const tag = st === 'passed' ? '<b class="verdict pass">PASSED</b>'
            : st === 'rejected' ? '<b class="verdict rej">REJECTED</b>'
            : '<b class="verdict void">VOID</b>';
          inner = tag + ' ' + esc(ev.message.replace(/^(PASSED|VOID|FAILED|REJECTED)\s*[-–]\s*/, ''));
        } else {
          inner = esc(ev.message);
        }
        li.innerHTML = `<time>${clock(ev.created_at)}</time><span>${inner}</span>`;
        log.prepend(li);  // newest on top (each new poll batch, ascending ids, lands above older)
        if (ev.kind === 'hypothesis') tried++;
      });
      // Always show gated strategies sorted by unseen P&L (highest first); deployable above
      // void above rejected. Re-sorts live each poll as a research chunk clears the gate.
      const shownPnl = (s) => { const m = (s.out_of_sample && s.out_of_sample.pnl != null) ? s.out_of_sample : (s.in_sample || {}); return m.pnl != null ? +m.pnl : -Infinity; };
      const tier = (s) => (s.status === 'passed' ? 0 : s.status === 'failed' ? 1 : 2);
      const sorted = (d.strategies || []).slice().sort((a, b) => (tier(a) - tier(b)) || (shownPnl(b) - shownPnl(a)));
      const top = sorted.slice(0, 50);  // cap render — a run_forever session can produce hundreds
      // Only re-render when the set actually changed — re-writing innerHTML every poll makes it blink.
      const sig = top.map((s) => `${s.id}:${s.status}:${shownPnl(s)}`).join('|') + '#' + (active ? 1 : 0) + '#' + sorted.length;
      if (sig !== lastFeedSig) {
        lastFeedSig = sig;
        const reg = registry(top.map((s) => s.equity));
        feed.innerHTML = top.length
          ? strategyTable(top.map((s) => strategySlip(s, reg, { land: true })).join('')) + (sorted.length > 50 ? `<p class="hint" style="margin-top:12px">Showing the top 50 of ${num(sorted.length)} by unseen P&L. See all on the <a href="/strategies">Strategies</a> page.</p>` : '')
          : `<div class="empty"><h3>${active ? 'Testing' : 'No results'}</h3><p>${active ? 'Strategies appear here as each batch clears the unseen-data gate — best unseen P&L on top.' : 'This run produced no strategies.'}</p></div>`;
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
    const f = { status: q.has('status') ? q.get('status') : '', market: q.get('market') || '' };
    shell('/strategies', boardTitle('Strategies', 'Every strategy your agents researched. Passed ones can be deployed; void ones stay here so you can see what didn’t work.') +
      '<dl class="figures measure" id="sfigs" style="margin-top:14px"></dl>', `
      <div class="section-head filters">
        <div class="chips" role="group" aria-label="Status">${[['', 'All'], ['passed', 'Passed'], ['failed', 'Void'], ['rejected', 'Rejected']].map(([v, l]) => `<button class="chip" data-f="status" data-v="${v}" aria-pressed="${f.status === v}">${l}</button>`).join('')}</div>
        <div class="chips" role="group" aria-label="Market">${[['', 'Both markets'], ...S.me.markets.map((m) => [m.key, marketShort(m.key)])].map(([v, l]) => `<button class="chip" data-f="market" data-v="${v}" aria-pressed="${f.market === v}">${esc(l)}</button>`).join('')}</div>
      </div>
      <div id="bulkbar" class="bulkbar" hidden></div>
      <div id="slips" style="margin-top:16px">${loading(240)}</div>`);
    root.querySelectorAll('[data-f]').forEach((b) => {
      b.onclick = () => {
        f[b.dataset.f] = b.dataset.v;
        const p = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== '' || false));
        if (!f.status) p.set('status', '');
        go('/strategies?' + p.toString(), true);
      };
    });
    // Paginate server-side at 50/page — a run_forever session can produce far more than the old
    // 500-row cap, and the figures/chip counts come from a real COUNT(*), not the fetched page.
    const CLABEL = { passed: 'Passed', failed: 'Void', rejected: 'Rejected' };
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
      root.querySelectorAll('[data-f="status"]').forEach((b) => { const v = b.dataset.v; b.textContent = v ? `${CLABEL[v]} (${c(v)})` : `All (${total})`; });
      if (!d.matched) {
        slipsEl.innerHTML = `<div class="empty"><h3>Nothing here yet</h3><p>${total ? 'Try another filter.' : 'Start a research session and the strategies it finds will land here.'}</p>${total ? '' : '<a class="btn" href="/research">Go to Research</a>'}</div>`;
        return;
      }
      const list = d.strategies, reg = registry(list.map((s) => s.equity));
      const anyPassed = list.some((s) => s.status === 'passed');
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
    const ins = s.in_sample || {}, oos = s.out_of_sample;
    const figsFor = (r) => fig('Unseen-data P&L', r.out_of_sample ? usd(r.out_of_sample.pnl, true) : '—', { v: r.out_of_sample && r.out_of_sample.pnl, small: r.out_of_sample ? `${r.out_of_sample.trades} trades the agent never saw` : 'Rejected before the unseen test' }) +
      fig('In-sample P&L', usd(r.in_sample.pnl, true), { v: r.in_sample.pnl, small: `${r.in_sample.trades} trades` }) +
      fig('Return on capital', r.out_of_sample ? pct(r.out_of_sample.roi) : '—', { small: `$${fmt0.format(r.capital || 0)} at risk at most` }) +
      fig('Hypotheses tested', s.hypotheses_tried ? `1 of ${s.hypotheses_tried}` : '—', { small: s.hypotheses_tried ? `The agent tested ${num(s.hypotheses_tried)} distinct ideas this run; this is the one that passed. More tries → higher chance one passes by luck (multiple testing).` : 'How many ideas the agent tried to find this one.' });
    root.querySelector('.board-title').outerHTML = boardTitle(serial(s.id) + ' · ' + marketShort(s.market), esc(dirLabel(s.direction)));
    root.querySelector('#figs').innerHTML = figsFor(s);
    const canDeploy = ['passed', 'failed', 'rejected'].includes(s.status);  // the user decides; status is a warning, not a block
    // Why a strategy was rejected (never reached the unseen-data gate) — stated honestly: a
    // profitable idea with too few trades is rejected on sample size, not for "losing money".
    const rejectReason = (st) => {
      const i = st.in_sample || {};
      if (i.trades != null && i.trades < 5) return `it made ${usd(i.pnl, true)} in testing, but over just ${i.trades} trade${i.trades === 1 ? '' : 's'} — a finalist needs at least 5, too few to trust.`;
      if (i.pnl != null && +i.pnl <= 0) return `it lost money in testing (${usd(i.pnl, true)}).`;
      return 'it ranked below the handful of finalists we tested on unseen data.';
    };
    const liveWhy = !S.me.live_trading_available ? 'Live trading isn’t open yet.' : !S.me.kalshi_connected ? 'Connect Kalshi on the Funds page first.' : s.side !== 'yes' ? 'Live supports YES-only strategies for now.' : '';
    const metricRows = (m) => m ? `<dl>
        <dt>P&amp;L after fees</dt><dd class="${tone(m.pnl)}">${usd(m.pnl, true)}</dd>
        <dt>Trades</dt><dd>${m.trades}${m.trades_per_day != null ? ` <small class="hint">(${m.trades_per_day}/day)</small>` : ''}</dd>
        <dt>Win rate</dt><dd>${pct(m.win_rate, false)}</dd>
        <dt>Fees paid</dt><dd>${usd(m.fees)}</dd>
        <dt>Profit factor</dt><dd>${m.profit_factor == null ? '—' : m.profit_factor}</dd>
        <dt>Worst drawdown</dt><dd>${usd(m.max_drawdown)}</dd>
        <dt>Sharpe (daily)</dt><dd>${m.sharpe == null ? '—' : m.sharpe}</dd></dl>` : `<p class="hint">Not tested on unseen data — ${rejectReason(s)}</p>`;
    const gatesHtml = (gs) => gs ? `<ul class="gates">${gs.map((g) => `<li class="${g.ok ? 'ok' : 'no'}">${g.ok ? ICON.check : ICON.cross}<span>${esc(g.name)}<small>needs ${esc(g.threshold)}</small></span><span class="v">${typeof g.value === 'number' && /\$|drawdown|money/i.test(g.name + g.threshold) ? usd(g.value) : esc(g.value == null ? '—' : g.value)}</span></li>`).join('')}</ul>` : '<p class="hint">Gates only run for finalists that made money in testing.</p>';
    const trades = (s.recent_trades || []).length ? `<table class="table stack"><thead><tr><th>Opened</th><th>Contract</th><th>Side</th><th class="num">Entry</th><th class="num">Exit</th><th class="num">P&amp;L</th></tr></thead><tbody>
        ${s.recent_trades.map((t) => `<tr><td>${esc(new Date(t.opened.replace('Z', ':00Z')).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }))}</td><td class="tick">${esc(t.ticker)}</td><td>${esc(t.side.toUpperCase())} ×${t.qty}</td><td class="num">${cents(t.entry)}</td><td class="num">${cents(t.exit)} <small class="hint">${esc(t.reason)}</small></td><td class="num ${tone(t.pnl)}">${usd(t.pnl, true)}</td></tr>`).join('')}
      </tbody></table>` : '<p class="hint">No unseen-data trades to show.</p>';
    const activeDeps = s.deployments.filter((d) => d.status !== 'stopped');  // must be stopped before delete
    const kUrl = marketKalshiUrl(s.market);
    const mktLink = kUrl ? `<a href="${kUrl}" target="_blank" rel="noopener">${esc(marketLabel(s.market))} ↗</a>` : esc(marketLabel(s.market));
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
              <div id="equity-wrap">${s.equity ? equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from) : ''}</div>
              <div class="split"><div><h4>Tested on (in-sample)</h4>${metricRows(ins)}</div><div><h4>Never seen (out-of-sample)</h4>${metricRows(oos)}</div></div>
            </div>
            ${s.dataset ? `<p class="hint" style="margin-top:12px">${mktLink}. History: ${esc(s.dataset.start.slice(0, 10))} to ${esc(s.dataset.end.slice(0, 10))}. The agent only saw data before ${esc((s.dataset.out_of_sample_from || '').slice(0, 10))}. Every fill pays the ask or bid plus Kalshi's taker fee.</p>` : ''}
            <h3 class="sheet-h">Latest unseen trades</h3>${trades}
            <details class="raw"><summary>Exact spec</summary><pre>${esc(JSON.stringify(s.spec, null, 2))}</pre></details>
          </article>
        </div>
        <aside>
          ${s.holdings && s.holdings.length ? `<section class="panel"><h3>Holding right now</h3>
            <div class="sheet"><table class="table stack t-dep"><thead><tr><th>Contract</th><th>Position</th><th class="num">Cost</th><th class="num">Settles</th></tr></thead><tbody>
            ${s.holdings.map((p) => `<tr><td class="tick" data-lab="Contract">${esc(p.ticker)} ${p.mode === 'live' ? '<span class="mk live">Live</span>' : ''}</td><td data-lab="Position">${esc(p.side.toUpperCase())} ×${p.qty} @ ${cents(p.entry_price)}</td><td class="num" data-lab="Cost">${usd(p.cost)}</td><td class="num" data-lab="Settles">${clock(p.market_close_time)}</td></tr>`).join('')}
            </tbody></table></div>
            <p class="hint" style="margin-top:8px">${s.holdings.length} open position${s.holdings.length === 1 ? '' : 's'} at cost ${usd(s.holdings.reduce((a, p) => a + p.cost, 0))}. Live mark-to-market P&L is coming soon.</p></section>` : ''}
          <section class="panel"><h3>Deploy</h3>
            ${canDeploy ? `<div style="display:grid;gap:10px">
                ${s.status !== 'passed' ? `<div class="notice bad">${ICON.warn}<span>${s.status === 'failed' ? 'Void: it failed the unseen-data gate.' : `Rejected: ${rejectReason(s)}`} It wasn’t validated, so deploying it — on paper or live — is your call and your risk.</span></div>` : ''}
                <button class="btn" id="dep-paper">Deploy on paper</button>
                <button class="btn ghost" id="dep-live" ${liveWhy ? 'aria-disabled="true"' : ''}>Deploy with live money</button>
                ${liveWhy ? `<p class="hint">${esc(liveWhy)}</p>` : ''}
                <form id="live-confirm" hidden style="display:grid;gap:8px">
                  <p class="hint">This trades real money in your Kalshi account. Type <b>LIVE</b> to confirm.</p>
                  <input class="input" name="confirm" autocomplete="off" aria-label="Type LIVE to confirm">
                  <button class="btn" type="submit">Confirm live deployment</button>
                </form>
                <div id="depflash"></div>
              </div>` : '<p class="hint">This strategy isn’t ready to deploy yet.</p>'}
            ${s.deployments.length ? `<p class="hint" style="margin-top:12px">Already deployed: ${s.deployments.map((d) => `#${d.id} (${esc(d.mode)}, ${esc(d.status)})`).join(', ')}. <a href="/deploy">Open the board</a></p>` : ''}
            ${kUrl ? `<p class="hint" style="margin-top:12px"><a href="${kUrl}" target="_blank" rel="noopener">Open ${esc(marketShort(s.market))} on Kalshi ↗</a></p>` : ''}
          </section>
          <section class="panel"><h3>Remove</h3>
            <p class="hint" style="margin-bottom:8px">Delete this strategy from your inventory. ${activeDeps.length ? 'Stop its deployment first — you can do it right here.' : 'This can’t be undone.'}</p>
            <div style="display:grid;gap:8px">
              ${activeDeps.length ? `<button class="btn sm danger" id="stop-dep">Stop deployment${activeDeps.length > 1 ? 's' : ''} (${activeDeps.map((d) => '#' + d.id).join(', ')})</button>` : ''}
              <button class="btn sm danger" id="del-strat" ${activeDeps.length ? 'aria-disabled="true"' : ''}>Delete strategy</button>
            </div><div id="delflash"></div>
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
    // Second equity line: the strategy's unseen window replayed read-only against
    // the Kalshi demo environment. Fetched after the page so a slow/absent demo
    // never blocks the view; absent -> the chart simply stays sim-only.
    if (s.equity && oos) (async () => {
      try {
        const r = await api('/api/strategies/' + s.id + '/dev-curve');
        const wrap = root.querySelector('#equity-wrap');
        if (wrap && r && r.dev_curve && r.dev_curve.length > 1) {
          wrap.innerHTML = equityChart(s.equity, s.dataset && s.dataset.out_of_sample_from, r.dev_curve)
            + `<p class="hint" style="margin-top:6px">Dashed line: the unseen window replayed read-only against Kalshi's demo environment${r.capped ? ` (first ${r.contracts} contracts)` : ''} — real demo order-book prices, scored with the same fees. No orders are placed.</p>`;
        }
      } catch (e) { /* demo replay is best-effort; leave the sim-only chart */ }
    })();
    const depPaper = root.querySelector('#dep-paper');
    if (depPaper) depPaper.onclick = () => busy(depPaper, async () => {
      try { await api('/api/deployments', { strategy_id: s.id, mode: 'paper' }); go('/deploy'); } catch (e) { flash('#depflash', e.message, 'bad'); }
    });
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
      <div class="post-head">${avatar(p.picture, p.author)}<div><b>${esc(p.author)}</b><span class="when">${when(p.created_at)}${p.edited ? ' · edited' : ''}</span></div></div>
      <div class="post-main"><p class="post-body">${mdLite(p.body)}</p>
      ${p.image ? `<a class="post-img" href="${esc(p.image)}" target="_blank" rel="noopener"><img src="${esc(p.image)}" alt="" loading="lazy"></a>` : ''}
      ${postSnapshot(p.snapshot)}</div>
      <div class="post-actions">
        ${reactionBar(p)}
        <button class="pact" data-act="comments">${ICON.comment}<span class="c">${p.comments || ''}</span></button>
        ${p.mine ? `<button class="pact" data-act="edit">${ICON.pencil}<span>Edit</span></button>` : ''}
      </div>
      <div class="comments" hidden></div>
    </article>`;
  }
  // Emoji reactions — a fixed palette (matches the server whitelist). 'tau' is a
  // custom reaction: the Tau mark, animated (a shaking "T" = excitement).
  const REACTIONS = ['tau', '👍', '❤️', '🔥', '🚀', '😂', '🎉', '💯', '👀', '🤔', '😮', '😢', '🙌', '🧠', '📈', '📉', '💸', '✅', '❌', '🐂', '🐻', '🐐', '🦍', '🐳', '💎', '🤡', '💀', '🫡', '🌙'];
  const emojiHtml = (e) => e === 'tau' ? `<span class="tau-emoji">${ICON.mark}</span>` : esc(e);
  function reactionBar(p) {
    const chips = (p.reactions || []).map((rx) => `<button class="rx ${rx.mine ? 'on' : ''}" data-emoji="${esc(rx.emoji)}">${emojiHtml(rx.emoji)}<span class="n">${rx.count}</span></button>`).join('');
    return `<span class="reactions">${chips}<button class="rx add" data-react-add aria-label="Add a reaction">${ICON.react}<i class="plus">+</i></button></span>`;
  }
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
        <form class="panel composer-post" id="composer-post">
          <textarea class="input" id="post-body" maxlength="2000" rows="2" placeholder="Share an idea, a strategy, or how it's going…"></textarea>
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
        <div class="chips feed-filter" role="group" aria-label="Filter posts"><button class="chip" type="button" data-feed="all" aria-pressed="true">All posts</button><button class="chip" type="button" data-feed="mine" aria-pressed="false">My posts</button></div>
        <div id="feed">${loading(120)}${loading(120)}</div>
      </div>`);
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
          root.querySelector('#post-body').value = ''; root.querySelector('#post-strat').value = '';
          pendingImage = null; photoInput.value = ''; root.querySelector('#photo-preview').hidden = true;
          await load();
        } catch (e) { flash('#post-flash', e.message, 'bad'); }
      });
    };
    form.onsubmit = (e) => { e.preventDefault(); const ref = root.querySelector('#post-strat').value; submit(ref ? 'strategy' : 'note', ref || undefined); };
    form.querySelector('[data-share="pnl"]').onclick = () => submit('pnl');
    const feed = root.querySelector('#feed');
    const renderReactions = (art, list) => {
      const bar = art.querySelector('.reactions');
      bar.innerHTML = (list || []).map((rx) => `<button class="rx ${rx.mine ? 'on' : ''}" data-emoji="${esc(rx.emoji)}">${emojiHtml(rx.emoji)}<span class="n">${rx.count}</span></button>`).join('')
        + `<button class="rx add" data-react-add aria-label="Add a reaction">${ICON.react}<i class="plus">+</i></button>`;
    };
    const react = async (pid, art, emoji) => {
      try { const r = await api(`/api/community/${pid}/react`, { emoji }); renderReactions(art, r.reactions); }
      catch (err) { alert0(err.message); }
    };
    feed.addEventListener('click', async (e) => {
      const rx = e.target.closest('.rx');
      if (rx) {
        const art = rx.closest('.post'); const pid = art.dataset.id;
        if (rx.dataset.reactAdd !== undefined) { openEmojiPicker(rx, (emoji) => react(pid, art, emoji)); }
        else if (rx.dataset.emoji) { react(pid, art, rx.dataset.emoji); }
        return;
      }
      const btn = e.target.closest('.pact'); if (!btn) return;
      const art = btn.closest('.post'); const pid = art.dataset.id;
      if (btn.dataset.act === 'like') {
        try {
          const r = await api(`/api/community/${pid}/like`, {});
          btn.classList.toggle('on', r.liked); btn.setAttribute('aria-pressed', r.liked);
          const c = btn.querySelector('.c'); const n = (parseInt(c.textContent || '0', 10) || 0) + (r.liked ? 1 : -1);
          c.textContent = n > 0 ? n : '';
        } catch (err) { alert0(err.message); }
      } else if (btn.dataset.act === 'edit') {
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
        box.innerHTML = `${d.comments.map((c) => `<div class="cmt">${avatar(c.picture, c.author)}<div><b>${esc(c.author)}</b> <span class="when">${when(c.created_at)}</span><p>${mdLite(c.body)}</p></div></div>`).join('')}
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
    let lastFeed = '', mineOnly = false;
    const load = async (force) => {
      // Never wipe a reply the user is writing: skip the refresh while a reply box is open
      // or anything in the feed is focused (unless this is the first/explicit render).
      if (!force && (feed.querySelector('.cmt-form') || feed.contains(document.activeElement))) return;
      const d = await api('/api/community' + (mineOnly ? '?mine=1' : ''));
      const html = d.posts.length ? d.posts.map(postCard).join('')
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
  const sinceMin = (iso) => { if (!iso) return '—'; const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000); return s < 90 ? 'just now' : Math.round(s / 60) + 'm ago'; };

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
           <section class="sect"><div class="sect-head"><h2>Credits &amp; usage</h2></div>${ledgerTable(d.ledger)}</section>`
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
              <section class="sect"><div class="sect-head"><h2>Credits &amp; usage</h2></div>${ledgerTable(d.ledger)}</section>
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
    shell('/admin', boardTitle('Admin', 'Operator tools: grant credits and see who has signed up or joined the waitlist.'), `
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
        </aside>
      </div>`);
    const load = async () => {
      const d = await api('/api/admin');
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
          try { await api('/api/admin/waitlist', { email: b.dataset.email, action: b.dataset.wl }); await load(); }
          catch (err) { alert0(err.message); }
        });
      }));
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
