/* Tau's operator pages: Admin and the System map.
   Fetched on first use (pageLoad in app.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns. */
window.TauPage('admin', (T) => {
  'use strict';
  const {
    adminViewOn, api, armed, boardTitle, busy, clock, compact, esc, flash, go, loading, num, phone, poll, root, S, SEP,
    shell, usd, when
  } = T;

  // ---------- admin ----------
  // The admin readout of open positions whose strategy was deleted (repo.orphaned_open_positions).
  const orphanLine = (o) => {
    if (!o || !o.total) return 'None: every open position belongs to a strategy that still exists.';
    const modes = ['paper', 'demo', 'live'].filter((m) => o.by_mode[m]);
    return `${o.total} open position${o.total === 1 ? '' : 's'} (${modes.map((m) => `${m}: ${o.by_mode[m].positions}`).join(', ')}) `
      + `across ${o.users} user${o.users === 1 ? '' : 's'} belong to deleted strategies. The engine no longer settles or flattens them. `
      + modes.map((m) => `${m[0].toUpperCase() + m.slice(1)}: ${usd(o.by_mode[m].cost)} at cost, oldest settles ${when(o.by_mode[m].oldest_close)}.`).join(' ');
  };
  // Broken pages: browser error reports from the last 24h (repo.client_error_groups), grouped by message
  // and page. Every field came from a browser, a signed-out one too, so all of it goes through esc().
  const CE_KIND = { error: 'Uncaught error', rejection: 'Unhandled rejection', api: 'API call failed', view: 'Page bug' };
  // The newest build it came from, and how many older ones (a fix that shipped shows as the old builds only).
  const ceBuild = (v) => (v && v.length ? `build ${esc(v[0])}${v.length > 1 ? ` +${v.length - 1}\u00a0older` : ''}` : 'build unknown');
  const clientErrorTable = (rows) => (!rows || !rows.length ? '<p class="hint">No page errors reported in the last 24 hours.</p>'
    : `<div class="sheet"><table class="table stack t-dep"><thead><tr><th>Error</th><th>Page, theme, build</th><th class="num">Count</th><th>Last seen</th></tr></thead><tbody>${rows.map((r) => `<tr>
      <td class="name" data-lab="Error">${esc(r.message)}<div class="sub-fig">${esc(CE_KIND[r.kind] || r.kind)}${r.at ? `${SEP}${esc(r.at)}` : ''}</div></td>
      <td data-lab="Page, theme, build">${esc(r.path)}<div class="sub-fig">${esc((r.themes || []).join(', ') || '\u2014')}${SEP}${ceBuild(r.versions)}</div></td>
      <td class="num" data-lab="Count">${+r.n || 0}${+r.signed_out ? `<div class="sub-fig">${+r.signed_out} signed out</div>` : ''}</td>
      <td class="hint" data-lab="Last seen">${when(r.last_seen)}<div class="sub-fig">first ${when(r.first_seen)}</div></td></tr>`).join('')}</tbody></table></div>`);
  async function viewAdmin() {
    if (!adminViewOn()) return go('/', true);
    shell('/admin', boardTitle('Admin', 'Operator tools: grant credits and see who has signed up.'), `
      <div class="detail">
        <div>
          <section class="sect"><div class="sect-head"><h2>Page errors</h2><span id="ce-count" class="sect-note"></span></div><div id="client-errors">${loading(80)}</div></section>
          <section class="sect"><div class="sect-head"><h2>Users</h2><span id="ucount" class="sect-note"></span></div><div id="users">${loading(200)}</div></section>
        </div>
        <aside aria-label="Operator controls">
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
          <section class="panel" id="orphans" style="margin-top:14px"><h3>Orphaned positions</h3>
            <p id="o-state" class="hint">Loading…</p>
          </section>
        </aside>
      </div>`);
    const load = async () => {
      const d = await api('/api/admin');
      root.querySelector('#ucount').textContent = `${d.users.length} shown`;
      root.querySelector('#o-state').textContent = orphanLine(d.orphaned_open);
      const ce = d.client_errors || [];
      root.querySelector('#ce-count').textContent = ce.length ? `last 24h${SEP}${ce.reduce((a, r) => a + (+r.n || 0), 0)} reports` : 'last 24h';
      root.querySelector('#client-errors').innerHTML = clientErrorTable(ce);
      root.querySelector('#users').innerHTML = `<div class="sheet"><table class="table stack t-dep"><thead><tr><th>Email</th><th>Name</th><th>Joined</th><th class="num">Balance</th></tr></thead><tbody>${d.users.map((u) => `<tr>
        <td class="name" data-lab="Email">${esc(u.email)}</td><td data-lab="Name">${esc(u.name || '')}</td>
        <td class="hint" data-lab="Joined">${when(u.created_at)}</td><td class="num" data-lab="Balance">${usd(u.balance)}</td></tr>`).join('')}</tbody></table></div>`;
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
        const killShow = (k) => {
      const st = root.querySelector('#k-state'), btn = root.querySelector('#k-btn');
      st.innerHTML = k.on || k.env_on
        ? `<span class="mk on">ON</span> New buys are halted${k.reason ? `: ${esc(k.reason)}` : ''}${k.by ? ` <small class="hint">by ${esc(k.by)}</small>` : ''}${k.env_on ? ' <small class="hint">(also set in the server env)</small>' : ''}`
        : 'Off. Orders flow normally.';
      btn.textContent = k.on ? 'Resume buys' : 'Halt new buys';
      btn.className = k.on ? 'btn primary' : 'btn danger';
      btn.dataset.on = k.on ? '1' : '';
    };
    api('/api/admin/kill-switch').then((k) => { killShow(k); }).catch((err) => { flash('#k-flash', err.message, 'bad'); });
    root.querySelector('#kill').onsubmit = async (e) => {
      e.preventDefault();
      const btn = root.querySelector('#k-btn');
      const run = () => busy(btn, async () => {
        try {
          const k = await api('/api/admin/kill-switch', { on: !btn.dataset.on, reason: root.querySelector('#k-reason').value.trim() });
          killShow(k);
        } catch (err) { flash('#k-flash', err.message, 'bad'); }
      });
      // Halting goes at once; resuming lets new buys flow again, so it asks first.
      return btn.dataset.on ? armed(btn, 'Confirm resume', run) : run();
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
    { id: 'bedrock', x: 40, y: 330, w: 150, label: 'Claude', sub: 'the research agent', ext: 1 },
    { id: 'stripe', x: 40, y: 460, w: 150, label: 'Stripe', sub: 'cards + credits', ext: 1 },
    { id: 'forward', x: 250, y: 30, w: 158, label: 'Forward collector', sub: 'Kalshi book → DB' },
    { id: 'cb_coll', x: 250, y: 150, w: 158, label: 'Coinbase collector', sub: '1-minute candles' },
    { id: 'features', x: 250, y: 270, w: 158, label: 'Feature builder', sub: 'per-minute features' },
    { id: 'web', x: 250, y: 455, w: 158, label: 'Web server', sub: 'pages + API' },
    { id: 'db', x: 490, y: 205, w: 150, label: 'Database', sub: 'one source of truth', big: 1 },
    // Its count takes two lines ("12 running · 30 queued" over "1,204 done"): on one it ran past the box's edge.
    { id: 'agents', x: 720, y: 40, w: 158, h: 82, lines: 2, label: 'Research agents', sub: `app.worker${SEP}hypotheses`, mine: 'your research sessions' },
    { id: 'backtest', x: 720, y: 160, w: 158, label: 'Backtester', sub: 'honest, out-of-sample', mine: 'your strategies' },
    { id: 'sim_engine', x: 720, y: 300, w: 158, label: 'Paper engine', sub: 'simulated fills', mine: 'your paper strategies' },
    { id: 'live_engine', x: 720, y: 460, w: 158, label: 'Live engine', sub: 'real Kalshi orders', mine: 'your live and demo' },
  ];
  // `mine`: the line under a box's name when it counts the reader's own (the server's `mine`: every customer's
  // view). Fleet-wide, "7 strategies tested" read as theirs beside their one session. Until the first read says,
  // a customer's boxes are taken to count their own; only the operator's count every user's.
  const sysSub = (n, L) => (n.mine && (L ? L.mine : !(S.me && S.me.is_admin)) ? n.mine : n.sub);
  const SYS_EDGES = [
    ['kalshi', 'forward'], ['coinbase', 'cb_coll'], ['forward', 'db'], ['cb_coll', 'db'],
    ['forward', 'features'], ['features', 'db'], ['bedrock', 'agents'], ['db', 'agents'],
    ['agents', 'backtest'], ['backtest', 'db'], ['db', 'sim_engine'], ['db', 'live_engine'],
    ['kalshi', 'live_engine'], ['stripe', 'web'], ['web', 'db'], ['db', 'web'],
  ];
  const SYS_DESC = {
    kalshi: 'Kalshi’s REST + websocket feed — the markets, their order books, and settled results. The source of truth we trade against.',
    coinbase: 'Coinbase BTC spot candles — the underlying price the 15-minute and 5pm markets settle on.',
    bedrock: 'Claude, the model behind the research agent: it reads an idea, writes strategy specs, and judges backtests. Metered per token.',
    stripe: 'Card vaulting + credit charges. Agent usage is billed per token against prepaid credits.',
    forward: 'data_pipeline/forward_collector.py — snapshots every live Kalshi market’s book on a tick, into forward_quotes / market_candles / markets.',
    cb_coll: 'data_pipeline/coinbase_collector.py — pulls 1-minute BTC candles into btc_candles_1m.',
    features: 'feature_1m_collector.py — builds the per-minute model features both the sim and live paths read.',
    web: 'app/server.py — the web server: the pages, the JSON API, Google sign-in, sessions, billing, and the admin surfaces.',
    db: 'Every collector writes here and every engine + the app reads here. One source of truth.',
    agents: 'app/worker.py (agents) — claims research/chat runs and drives Claude through the research loop, writing strategies + a live event log.',
    backtest: 'app/trading/backtest.py — runs each hypothesis on data it never saw and applies the deployment gates. Same spec the engines run.',
    sim_engine: 'app/trading/engine.py on paper money — prices from the live book, fills against the shown size, tracks P&L without real orders.',
    live_engine: 'app/trading/engine.py (the same engine) — places real orders: live money in a user’s own Kalshi account, demo on Kalshi’s sandbox. Live money also needs Tau’s live switch on, the user’s own opt-in and enough paper evidence.',
  };
  const sysNode = (id) => SYS_NODES.find((n) => n.id === id);
  const sysH = (n) => n.h || (n.big ? SYS_DBH : SYS_H);
  function sysEdgePath(a, b) {
    const na = sysNode(a), nb = sysNode(b);
    const ha = sysH(na), hb = sysH(nb);
    const x1 = na.x + na.w, y1 = na.y + ha / 2, x2 = nb.x, y2 = nb.y + hb / 2;
    const dx = Math.max(40, (x2 - x1) * 0.5);
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }
  // On a phone the 900-wide map either shrank past reading or scrolled sideways inside its frame (at 390px the
  // research box started at x 537). There the boxes stack by stage, two 158-wide columns in a 340-wide map that
  // fits the column at about its own size: each stage under its caption, a short arrow from each stage into the
  // next in place of the crossing edges, which a stacked map can't draw sensibly.
  const SYS_PW = 340;
  const SYS_TIERS = [
    { cap: 'Outside services', ids: ['kalshi', 'coinbase', 'bedrock', 'stripe'] },
    { cap: 'Collectors and web server', ids: ['forward', 'cb_coll', 'features', 'web'] },
    { cap: '', ids: ['db'] },
    { cap: 'Research and engines', ids: ['agents', 'backtest', 'sim_engine', 'live_engine'] },
  ];
  function sysPhoneLayout() {
    const at = {}, art = [], mid = SYS_PW / 2;
    let y = 8;
    SYS_TIERS.forEach((t, i) => {
      if (i) { art.push(`<path class="sys-tier" d="M${mid},${y - 4} V${y + 10} M${mid - 5},${y + 5} L${mid},${y + 10} L${mid + 5},${y + 5}" />`); y += 16; }
      if (t.cap) { art.push(`<text class="sys-tier-cap" x="8" y="${y + 11}">${esc(t.cap)}</text>`); y += 18; }
      for (let r = 0; r < t.ids.length; r += 2) {
        const row = t.ids.slice(r, r + 2).map(sysNode), hs = row.map((n) => (n.big ? SYS_H : sysH(n)));
        row.forEach((n, j) => { at[n.id] = { x: 8 + j * 166, y, w: t.ids.length === 1 ? SYS_PW - 16 : 158, h: hs[j] }; });
        y += Math.max(...hs) + 8;
      }
    });
    return { at, art: art.join(''), w: SYS_PW, h: y };
  }
  async function viewSystem() {
    const lay = phone() ? sysPhoneLayout() : null;
    const edges = lay ? lay.art : SYS_EDGES.map(([a, b], i) => `<path class="sys-edge" data-e="${a}" id="se${i}" d="${sysEdgePath(a, b)}" />`).join('');
    const nodes = SYS_NODES.map((n) => {
      const at = lay ? lay.at[n.id] : { x: n.x, y: n.y, w: n.w, h: sysH(n) }, h = at.h;
      // A two-line count is a line apiece, each set from metricLines on every read.
      const m = n.lines === 2 ? `<text class="m" data-m="${n.id}"><tspan x="12" y="${h - 26}"></tspan><tspan x="12" y="${h - 12}"></tspan></text>`
        : `<text class="m" x="12" y="${h - 12}" data-m="${n.id}"></text>`;
      return `<g class="sys-node ${n.ext ? 'ext' : ''}" data-id="${n.id}" transform="translate(${at.x},${at.y})" tabindex="0" role="button" aria-label="${esc(n.label)}">
        <rect width="${at.w}" height="${h}" rx="${n.ext ? 9 : 3}"></rect>
        <text class="t" x="12" y="23">${esc(n.label)}</text>
        <text class="s" x="12" y="41" data-s="${n.id}">${esc(sysSub(n))}</text>
        ${m}
        <circle class="pulse" cx="${at.w - 13}" cy="15" r="4"></circle>
      </g>`;
    }).join('');
    shell('/system', boardTitle('System', 'A live map of the pipeline — every box is a real part of the codebase, every line is data flowing. It refreshes on its own so you can see what’s running.'),
      `<div class="sysmap">
         <div class="sys-wrap"><svg viewBox="0 0 ${lay ? `${lay.w} ${lay.h}` : '900 540'}" preserveAspectRatio="xMidYMid meet" id="syssvg"${lay ? ' class="sys-stack"' : ''} aria-label="System map">${edges}${nodes}</svg></div>
         <aside class="sys-side" aria-label="Details and live activity">
           <section class="panel" id="sys-detail"><h2>Pick a box</h2><p class="hint">Click any part of the system to see what it does and what it’s doing right now.</p></section>
           <section class="sect" style="margin-top:16px"><div class="sect-head"><h2>Live activity</h2><span class="sys-live" id="sys-stamp"></span></div><ol class="log sys-feed" id="sys-feed" tabindex="0" aria-label="Live activity"></ol></section>
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
      // Admin-only storage breakdown on the DB node: which tables eat the volume, so a refilling
      // table is visible long before the disk fills (the storage-full outage had no such warning).
      const tbls = (id === 'db' && L && L.top_tables && L.top_tables.length)
        ? `<div class="sys-tables"><b>Largest tables</b><ul>${L.top_tables.map((t) =>
            `<li><span>${esc(t.table)}</span><span>${t.mb >= 1024 ? (t.mb / 1024).toFixed(1) + ' GB' : num(t.mb) + ' MB'}</span></li>`).join('')}</ul></div>`
        : '';
      detail.innerHTML = `<h2>${esc(n.label)}</h2><p class="sys-metric" id="sys-dm">${metricText(id, L) || ''}</p>${L && L.mine ? '<p class="hint">Yours only: other users’ aren’t counted here.</p>' : ''}<p class="hint" style="margin-top:8px">${esc(SYS_DESC[id] || '')}</p>${tbls}${open}`;
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
        `<h2>Modules</h2><ul class="sys-list">${d.modules.map((m) =>
          `<li><a href="#" data-mod="${esc(m.path)}">${esc(m.name)}</a> <span class="sys-dim">${m.symbols} defs${SEP}${m.lines} lines</span>${m.doc ? `<div class="hint">${esc(m.doc)}</div>` : ''}</li>`).join('')}</ul>`);
    };
    const openModule = (id, mod) => {
      codeState = { id, module: mod };
      const label = (sysNode(id) || {}).label || id;
      return codePanel('module=' + encodeURIComponent(mod), (d) => {
        const fn = (f) => `<li><a href="#" data-fn="${esc(f.qual)}" data-fnmod="${esc(mod)}"><code>${esc(f.signature)}</code></a>${f.doc ? `<div class="hint">${esc(f.doc)}</div>` : ''}</li>`;
        const cls = d.classes.map((c) => `<li class="sys-cls"><code>class ${esc(c.name)}</code>${c.doc ? `<div class="hint">${esc(c.doc)}</div>` : ''}<ul class="sys-list">${c.methods.map(fn).join('')}</ul></li>`).join('');
        return crumbs([{ t: label, a: `data-detail="${esc(id)}"` }, { t: 'modules', a: `data-code-open="${esc(id)}"` }, { t: modName(mod) }]) +
          `<h2>${esc(modName(mod))}</h2>` +
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
        `<h2><code>${esc(d.qual)}</code></h2><p class="hint">${esc(modName(mod))}${SEP}line ${d.lineno}</p>` +
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
    // The page knows an outside service is sending only by the collector that reads it: Kalshi's book by the
    // forward collector's heartbeat, Coinbase's candles by its collector's. Nothing on the page reads Claude
    // or Stripe, so their boxes say nothing about a connection (they all read "connected", always green). A
    // collector that stopped greys its service's dot rather than reddening it: the page can't tell whose end failed.
    const SYS_FED = { kalshi: 'forward', coinbase: 'cb_coll' };
    // A row count from the database's own estimate (information_schema): a new or small table's reads 0 or
    // a few hundred off, so the figure shows only once it is large enough to mean something, as "about N",
    // rounded as an estimate deserves (about 988M, not 987.7M), so it fits its box beside the age.
    const aboutRows = (n, unit) => {
      n = +n;
      if (!(n >= 1000)) return '';
      const r = n >= 1e9 ? (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B' : n >= 1e7 ? Math.round(n / 1e6) + 'M'
        : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : Math.round(n / 1e3) + 'k';
      return `about ${r} ${unit}`;
    };
    // A collector's count in a word short enough for its box: "123,456,789 quote rows · 20s ago" ran past it.
    const SYS_UNIT = { forward: 'quotes', cb_coll: 'candles', features: 'rows' };
    // The research box's count as its two lines; every other box's is one.
    const metricLines = (id, L) => (id === 'agents' && L ? [`${num(L.running)} running${SEP}${num(L.queued)} queued`, `${num(L.done)} done`] : [metricText(id, L)]);
    function metricText(id, L) {
      if (!L) return '';
      const n = sysNode(id);
      // An outside service's box counts what Tau has stored from it, when there is any; never "connected".
      if (n && n.ext) return id === 'kalshi' && +L.markets > 0 ? `${compact(+L.markets)} markets${SEP}${num(L.series)} series` : '';
      if (id === 'db') {
        const size = +L.size_mb >= 1024 ? (L.size_mb / 1024).toFixed(0) + ' GB' : +L.size_mb >= 1 ? num(L.size_mb) + ' MB' : '';
        return [size, aboutRows(L.rows, 'rows')].filter(Boolean).join(SEP);
      }
      if (id === 'web') return L.users != null ? `${num(L.users)} users${SEP}serving` : `online${SEP}serving`;
      if (id === 'agents') return metricLines(id, L).join(SEP);
      if (id === 'backtest') return `${num(L.strategies)} strategies tested`;
      const a = L.age == null ? '—' : L.age < 90 ? `${L.age}s ago` : L.age < 5400 ? `${Math.round(L.age / 60)}m ago` : 'stale';
      if (SYS_UNIT[id]) return [aboutRows(L.rows, SYS_UNIT[id]), a].filter(Boolean).join(SEP);
      // Running deployments per mode (the reader's own; every user's for the operator): live money and demo are named apart, never summed.
      if (id === 'sim_engine') return `${num(L.paper)} paper running${SEP}${a}`;
      if (id === 'live_engine') return `${num(L.live)} live${SEP}${num(L.demo)} demo${SEP}${a}`;
      return a;
    }
    // A verdict reads as the run page's plain note (server gate_explain.event_note) when it has one,
    // after the idea's title; else its own message, minus the status word the row doesn't need.
    const sysVerdict = (e) => {
      const n = e.data && e.data.note;
      if (n) return e.data.title ? `${e.data.title}: ${n}` : n;
      return e.message.replace(/^(PASSED|VOID|FAILED)\s*[-–]\s*/, '');
    };
    const load = async () => {
      let d; try { d = await api('/api/admin/system'); } catch (e) { return; }
      S.sysLive = d.nodes;
      SYS_NODES.forEach((n) => {
        const L = d.nodes[n.id]; const g = svg.querySelector(`.sys-node[data-id="${n.id}"]`);
        const mt = svg.querySelector(`[data-m="${n.id}"]`), lines = metricLines(n.id, L), spans = mt ? mt.querySelectorAll('tspan') : [];
        if (spans.length) spans.forEach((t, i) => { t.textContent = lines[i] || ''; }); else if (mt) mt.textContent = lines[0];
        const sb = svg.querySelector(`[data-s="${n.id}"]`), sub = sysSub(n, L); if (sb && sb.textContent !== sub) sb.textContent = sub;
        const fed = SYS_FED[n.id] && d.nodes[SYS_FED[n.id]];
        const st = n.ext ? (fed && fed.age != null && fed.age < 300 ? fresh(fed.age) : 'idle') : (L && 'age' in L) ? fresh(L.age) : (n.id === 'web' || n.id === 'db') ? 'live' : 'idle';
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
      feed.innerHTML = d.events.length ? d.events.map((e) => `<li class="${e.kind === 'error' ? 'error' : ''}"><time>${clock(e.created_at)}</time><span>${e.kind === 'verdict' ? esc(sysVerdict(e)) : esc(e.message)}</span></li>`).join('') : '<li><span class="hint">Quiet right now.</span></li>';
    };
    await load();
    poll(load, 4000);
  }

  return {viewAdmin, viewSystem};
});
