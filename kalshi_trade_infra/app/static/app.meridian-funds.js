/* Meridian's Funds page: the Kalshi keys and the native perps account.
   Fetched on first use (pageLoad in app.meridian.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns. */
window.TauPage('funds', (T) => {
  'use strict';
  const {
    api, armed, BEHIND, boardTitle, busy, DEMO_WHAT, demoSpan, esc, fig, flash, holdFocus, ICON, loading, pageAssets,
    paint, painted, poll, refreshed, root, S, shell, tone, usd, when
  } = T;

  // ---------- funds ----------
  // ---------- Kalshi keys (Funds) ----------
  // Where each key comes from. Kalshi's demo is its own site, with its own login and play money, and a
  // key only works on the site that made it, so each box names its site and links its key page.
  const KALSHI_KEYS = {
    live: { site: 'kalshi.com', keys: 'https://kalshi.com/account/profile' },
    demo: { site: 'demo.kalshi.co', keys: 'https://demo.kalshi.co/account/profile', join: 'https://demo.kalshi.co/' },
    guide: 'https://docs.kalshi.com/getting_started/api_keys',
  };
  const extLink = (href, text) => `<a href="${href}" target="_blank" rel="noopener">${text}</a>`;
  function keySteps(kind) {
    const k = KALSHI_KEYS[kind], demo = kind === 'demo';
    const open = demo
      ? `<li>Kalshi’s demo is a separate site with its own login and play money. ${extLink(k.join, 'Sign up or sign in at demo.kalshi.co')} (free).</li><li>There, open ${extLink(k.keys, 'your demo profile')}, find API Keys and click Create New API Key.</li>`
      : `<li>On Kalshi, open ${extLink(k.keys, 'your profile')}, find API Keys and click Create New API Key.</li>`;
    return `<ol class="steps key-steps">${open}<li>Kalshi shows a <b>Key ID</b> (like <span class="nobr">a952bcbe-ec3b-…</span>) and downloads a <b>private key</b> file (.key), once. Keep the file; if it’s lost, make a new key.</li><li>Paste the Key ID below and choose the .key file (or paste its text). We check it with ${demo ? 'the demo exchange' : 'Kalshi'}, then store it encrypted; it is never shown again.</li></ol>
      <p class="hint key-diff">${demo ? 'A demo key trades play money on Kalshi’s sandbox. A real-money key from kalshi.com won’t work here.' : 'A live key trades your real money. A key made on demo.kalshi.co won’t work here: add it under Demo key.'} ${extLink(KALSHI_KEYS.guide, 'Kalshi’s guide to API keys')}</p>`;
  }
  // Plain words for the usual mix-ups, before anything is sent. Fixed text only: it never echoes the key.
  function keyProblem(kid, pem, kind) {
    kid = String(kid || '').trim(); pem = String(pem || '').trim();
    const where = kind === 'demo' ? 'the API keys page on demo.kalshi.co' : 'the API keys page on kalshi.com';
    if (/PRIVATE KEY|PUBLIC KEY/.test(kid) || kid.length > 128) return 'That’s the key file’s text; it goes in the Private key box. The Key ID is the short code shown next to the key on Kalshi, like a952bcbe-ec3b-….';
    if (!kid) return `Paste the Key ID: the short code shown next to the key on ${where}.`;
    if (!pem) return 'Paste the private key, or choose the .key file Kalshi downloaded.';
    if (/^[0-9a-f]{8}-[0-9a-f-]{8,}$/i.test(pem)) return 'That looks like the Key ID; it goes in the Key ID box. The private key is the .key file Kalshi downloaded.';
    if (/PUBLIC KEY/.test(pem)) return 'That’s a public key. Tau needs the private key: the .key file Kalshi downloaded when you created the key.';
    if (!/-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(pem)) return 'That isn’t a private key. Paste the whole .key file Kalshi downloaded, from its -----BEGIN line to its -----END line, or choose the file.';
    if (!/-----END [A-Z ]*PRIVATE KEY-----/.test(pem)) return 'That private key is cut off: it should end with an -----END … PRIVATE KEY----- line. Choose the .key file instead of copying it.';
    return '';
  }
  // How you know it worked: the existing balance read, right under the panel title. No balance means Kalshi
  // didn't answer for this key just now (Kalshi down, or the key deleted there), so it gets no check mark.
  // `at` is when the balance memo was read (the server's balance_at), so the line says how old it is.
  const keyOk = (bal, kind, at) => bal == null
    ? `<p class="key-ok key-unread"><b>Key saved</b> (Kalshi didn’t send a balance for it just now)</p><p class="hint key-diff">If this lasts, the key may have been deleted on ${KALSHI_KEYS[kind === 'demo' ? 'demo' : 'live'].site}: ${kind === 'demo' ? 'remove it' : 'disconnect it'} and connect a new one.</p>`
    : `<p class="key-ok"><b>Connected ✓</b> (balance ${usd(bal)}${at ? ', read ' + when(at) : ''})${kind === 'demo' ? ' <span class="hint">in your Kalshi demo account</span>' : ''}</p>`;
  // Kalshi refuses orders from a demo account with no cash, and a new one starts empty. Tau's demo balance is
  // Tau's own figure, so a $0.00 here would otherwise read as harmless.
  // `from` is the demo cash the autopilot's demo copies wait for (server: demo_twins), so a balance
  // under it says why no copy starts, not only an empty one.
  const demoEmpty = (bal, from) => bal == null ? '' : bal < 0.005 ? `<div class="notice" role="status">${ICON.warn}<span>Your Kalshi demo account has $0.00, so Kalshi refuses demo orders. Add demo funds in your account on ${extLink(KALSHI_KEYS.demo.join, 'demo.kalshi.co')} (play money, not real). Tau’s demo balance above is Tau’s own figure and doesn’t fund it.</span></div>`
    : from && bal < from ? `<div class="notice" role="status">${ICON.warn}<span>Your Kalshi demo account has ${usd(bal)}. Demo copies of your paper strategies start once it holds ${usd(from)}: add play money in your account on ${extLink(KALSHI_KEYS.demo.join, 'demo.kalshi.co')} (not real). Tau’s demo balance above is Tau’s own figure and doesn’t fund it.</span></div>` : '';

  // Each Funds figure says what it leaves out: a book's open positions, by count and cost (contracts x entry,
  // the dashboard's "at cost"). An API without the counts says nothing rather than "0 open".
  const openAt = (b) => b.open_positions ? `${b.open_positions} open (${usd(b.open_at_cost)} at cost) ·\u00a0` : '';
  const openLeft = (b, mode) => b.open_positions == null ? 'Open positions not included'
    : b.open_positions ? `${b.open_positions} open ${mode} position${b.open_positions === 1 ? '' : 's'} (${usd(b.open_at_cost)} at cost) not included` : `No open ${mode} positions`;
  // What each book has made: its realized P&L from closed trades, the figure the dashboard, Deploy and the
  // track record show, never added to another book's. Before a book's first close it says when one shows.
  // An API without the figure says nothing. Demo's is since its last reload, as on the dashboard.
  const bookPnl = (b, mode, pnl = b.realized_pnl, span = 'all time') => b.closed_trades == null ? ''
    : b.closed_trades ? `${usd(pnl, true)} realized ${span} ·\u00a0` : `P&amp;L shows once a ${mode} trade closes ·\u00a0`;
  const livePnl = (k) => k.closed_trades == null ? '' : k.closed_trades ? ` Tau\u2019s live trades: ${usd(k.realized_pnl, true)} realized all time.`
    : k.connected ? ' Tau\u2019s live P&amp;L shows once a live trade closes.' : '';
  const KALSHI_UNREAD = 'Kalshi didn\u2019t answer just now. Reload in a minute to try again.';
  // A paper history line in plain words. The engine writes prices as dollars ("@ 0.40") and exit reasons as
  // codes ("stop_loss"); a settled row's $0.00 read as nothing happening when the contract lost. Display only:
  // the stored memo and the amount are unchanged.
  const ledgerWhat = (r) => {
    const memo = String(r.memo || r.kind || '').replace(/ (@|->) (\d*\.\d+)/g, (m, w, p) => ` ${w === '@' ? 'at' : '\u2192'} ${Math.round(+p * 100)}\u00a2`)
      .replace(/\(([a-z]+(?:_[a-z]+)+)/g, (m, c) => '(' + c.replace(/_/g, ' '));
    const settled = r.kind === 'settlement' ? (+r.amount > 0 ? ' \u00b7\u00a0won, paid $1 a contract' : ' \u00b7\u00a0lost, paid $0') : '';
    return esc(memo) + (settled ? `<span class="hint">${settled}</span>` : '');
  };
  // Fees and settlement, once, in plain words, where the cash moves.
  const LEDGER_HOW = 'Cash in and out of your paper account, newest first. A buy takes the contracts\u2019 price plus Kalshi\u2019s fee, as a real order would. When a market settles, each winning contract pays $1 and each losing one pays $0; a sale before then pays the price it sold at, less the fee. A trade\u2019s P&amp;L is what it brought back less everything it cost, fees included.';
  async function viewFunds() {
    const gen = S.gen;
    shell('/funds', boardTitle('Funds') + '<dl class="figures measure" id="ffigs" style="margin-top:14px"></dl><p class="stale-note" id="funds-stale" role="status"></p>', loading(300));
    root.querySelector('.wrap').classList.add('funds-page');
    // While the page is open its figures follow Kalshi's cash and the books (every 30s; the Kalshi and demo
    // cash are each read at most once a minute on the server, as on the dashboard). A write re-reads it all.
    // The poll (cfg) redraws the panels below only when a figure in them moved and nobody is using them:
    // a field with focus or something typed, a press on its way or waiting for its confirm, or what an action
    // just said. The perps panel keeps its own state, so the poll leaves it alone.
    const FLASHES = ['#flash', '#kflash', '#dmflash', '#pflash', '#kdflash'];
    const inUse = (el) => {
      const a = document.activeElement;
      return !!(a && a !== document.body && el.contains(a)) || [...el.querySelectorAll('input, textarea')].some((x) => x.value)
        || !!el.querySelector('.busy, .armed') || FLASHES.some((sel) => { const x = el.querySelector(sel); return !!(x && x.innerHTML); });
    };
    // The perps box mounts once its script is in. Funds' own files (the perps account, and the broker and
    // Alpaca paper files kept with it) start loading once the figures have painted, never ahead of them
    // (pageAssets): on a phone's slow network the shell's copies held the first figure back.
    const mountPerps = () => {
      const perpsHost = root.querySelector('#kalshi-perps-live');
      if (gen === S.gen && !S.perps && window.TAU_PERPS_LIVE && perpsHost) S.perps = window.TAU_PERPS_LIVE.mount(perpsHost, {api, proposalId: new URLSearchParams(location.search).get('perps_proposal')});
    };
    const load = async (cfg) => {
      const d = await api('/api/funds', undefined, cfg);
      if (gen !== S.gen) return;
      const k = d.kalshi;
      const kd = d.kalshi_dev || { connected: false };
      const dm = d.demo || { capital: 0, equity: 0, realized: 0 };
      paint(root.querySelector('#ffigs'), fig('Kalshi cash', k.connected ? (k.balance == null ? 'Unavailable' : usd(k.balance)) : 'Not connected', { cls: 'lead', small: !k.connected ? livePnl(k).trim() : k.balance == null ? KALSHI_UNREAD + livePnl(k) : `Real money at Kalshi${k.balance_at ? ', read ' + when(k.balance_at) : ''}.${livePnl(k)} ${openLeft(k, 'live')}` }) +
        fig('Demo balance', usd(dm.equity), { small: `${usd(dm.capital)} ${dm.before_reload ? 'capital at last reload' : 'starting capital'} ·\u00a0${openAt(dm)}${bookPnl(dm, 'demo', dm.realized, demoSpan(dm))}${kd.connected ? '' : 'needs a demo key ·\u00a0'}${DEMO_WHAT}` }) +
        fig('Paper balance', usd(d.paper.equity == null ? d.paper.cash : d.paper.equity), { small: `${usd(d.paper.cash)} cash ·\u00a0${openAt(d.paper)}${bookPnl(d.paper, 'paper')}`.replace(/ ·\u00a0$/, '') }));
      const host = root.querySelector('#main'), main = `<div id="flash"></div><div class="funds">
        <div class="funds-col funds-manage">
        <section class="panel">
          <h2>Kalshi account (live money)</h2>
          ${k.connected ? `
            ${keyOk(k.balance, 'live', k.balance_at)}<dl class="kv"><dt>API key</dt><dd>${esc(k.key_id)}</dd><dt>Cash at Kalshi</dt><dd>${k.balance == null ? 'Couldn’t read it just now' : usd(k.balance)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">Funds stay in your Kalshi account. Manage deposits and withdrawals at Kalshi. To change keys, disconnect and connect the new one.</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <a class="btn" href="${esc(k.funding_url)}" target="_blank" rel="noopener">Deposit or withdraw at Kalshi ${ICON.ext}</a>
              <button class="btn danger" id="disconnect">Disconnect</button>
            </div>` : `
            <p class="lede" style="margin-bottom:12px">Connect your Kalshi account for live trading. Funds stay at Kalshi.</p>
            <details class="connection-help" open><summary>Key setup</summary>${keySteps('live')}</details>
            <form id="kalshi" style="display:grid;gap:12px">
              <label class="field"><span>Key ID</span><input class="input" name="key_id" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" required placeholder="like a952bcbe-ec3b-4b5b-…"></label>
              <label class="field"><span>Private key</span><textarea class="input" name="private_key" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
              <label class="key-file"><span>Or choose the downloaded key file</span><input type="file" accept=".key,.pem,.txt,text/plain" data-keyfile></label>
              <button class="btn" type="submit">Verify and connect</button>
            </form>`}
          <div id="kflash" style="margin-top:10px"></div>
        </section>
        <section class="panel">
          <h2>Kalshi demo (sandbox) account</h2>
          <dl class="kv"><dt>Demo balance</dt><dd>${usd(dm.equity)}</dd><dt>${dm.before_reload ? 'Capital at last reload' : 'Starting capital'}</dt><dd>${usd(dm.capital)}</dd><dt>Realized ${demoSpan(dm)}</dt><dd class="${tone(dm.realized)}">${usd(dm.realized, true)}</dd></dl>
          <p class="lede" style="margin-bottom:14px">Real orders on Kalshi’s sandbox exchange, to prove the order path before live money. The sandbox book is thin, so its fills and P&amp;L are no evidence of the edge; paper keeps that job. The money is simulated. Reloading changes Tau’s balance only and starts realized P&amp;L since reload at $0.00; the track record still counts every closed demo trade.</p>
          <form id="demo" class="amount">
            <label class="field"><span>Reload to</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="1000"></label>
            <button class="btn" type="submit">Reload demo</button>
          </form>
          <div id="dmflash" style="margin-top:10px"></div>
          <h3 style="margin-top:24px">Demo key</h3>
          ${kd.connected ? `
            ${keyOk(kd.balance, 'demo', kd.balance_at)}${demoEmpty(kd.balance, kd.copies_from)}<dl class="kv"><dt>Demo key</dt><dd>${esc(kd.key_id)}</dd></dl>
            <p class="lede" style="margin-bottom:14px">Sandbox orders only. Demo and live keys are stored separately. To change keys, remove this one and connect the new one.</p>
            <button class="btn danger" id="dev-disconnect">Remove demo key</button>` : `
            <p class="lede" style="margin-bottom:12px">Connect a Kalshi <b>demo</b> key for sandbox orders. No real money. Demo is the step between paper and live: it proves orders place, fill and book, and live needs a clean demo record.</p>
            <details class="connection-help" open><summary>Key setup</summary>${keySteps('demo')}</details>
            <form id="kalshi-dev" style="display:grid;gap:12px">
              <label class="field"><span>Demo key ID</span><input class="input" name="key_id" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" required placeholder="like a952bcbe-ec3b-4b5b-…"></label>
              <label class="field"><span>Demo private key</span><textarea class="input" name="private_key" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" required placeholder="-----BEGIN RSA PRIVATE KEY-----"></textarea></label>
              <label class="key-file"><span>Or choose the downloaded key file</span><input type="file" accept=".key,.pem,.txt,text/plain" data-keyfile></label>
              <button class="btn" type="submit">Verify and connect demo</button>
            </form>`}
          <div id="kdflash" style="margin-top:10px"></div>
        </section>
        <section class="panel">
          <h2>Paper account (simulation)</h2>
          <p class="lede" style="margin-bottom:14px">Simulated funds. No real orders.</p>
          <form id="paper" class="amount">
            <label class="field"><span>Amount</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="500"></label>
            <button class="btn" data-kind="deposit" type="submit">Add</button>
            <button class="btn ghost" data-kind="withdraw" type="submit">Withdraw</button>
            <button class="btn ghost" data-kind="reset" type="submit">Reset to amount</button>
          </form>
          <div id="pflash" style="margin-top:10px"></div>
        </section>
        </div>
        <div class="funds-col funds-history">
        ${S.me.perps_live_available ? '<section id="kalshi-perps-live" aria-label="Bitcoin perpetual trading"></section>' : ''}
        <section class="panel">
          <h2>Paper history</h2>
          <p class="hint ledger-how">${LEDGER_HOW}${d.paper.ledger.length >= 50 ? ' The latest 50 entries.' : ''}</p>
          <table class="table stack t-ledger"><thead><tr><th>When</th><th>What</th><th class="num">Amount</th></tr></thead><tbody>
            ${d.paper.ledger.map((r) => `<tr><td class="hint lead-cell" data-lab="When">${when(r.created_at)}</td><td class="name" data-lab="What">${ledgerWhat(r)}</td><td class="num ${tone(+r.amount)}" data-lab="Amount">${usd(r.amount, true)}</td></tr>`).join('')}
          </tbody></table>
        </section>
        </div></div>`;
      if (cfg && (painted.get(host) === main || S.perps || inUse(host))) return;
      host.innerHTML = main; painted.set(host, main);
      if (S.perps) { S.perps.destroy(); S.perps = null; }
      if (window.TAU_PERPS_LIVE) mountPerps(); else pageAssets('funds').then(mountPerps);
      const df = root.querySelector('#demo');
      if (df) df.onsubmit = async (e) => {
        e.preventDefault();
        await holdFocus(null, () => busy(df.querySelector('button'), async () => {
          try { await api('/api/funds/demo', { amount: +df.amount.value }); if (gen !== S.gen) return; const fresh = await refreshed(load()); if (gen === S.gen) flash('#dmflash', 'Demo account reloaded.' + (fresh ? '' : BEHIND), 'good'); } catch (err) { if (gen === S.gen) flash('#dmflash', err.message, 'bad'); }
        }));
      };
      const pf = root.querySelector('#paper');
      let kind = 'deposit';
      pf.querySelectorAll('button').forEach((b) => (b.onclick = () => (kind = b.dataset.kind)));
      // Each button names the amount it will move, so "Reset to" never reads as a dangling label.
      const PAPER_VERB = { deposit: 'Add', withdraw: 'Withdraw', reset: 'Reset to' };
      const amt = pf.querySelector('input[name=amount]');
      const syncPaper = () => {
        const v = +amt.value;
        pf.querySelectorAll('button').forEach((b) => { b.textContent = v > 0 ? `${PAPER_VERB[b.dataset.kind]} ${usd(v)}` : b.dataset.kind === 'reset' ? 'Reset to amount' : PAPER_VERB[b.dataset.kind]; });
      };
      amt.addEventListener('input', syncPaper);
      pf.onsubmit = async (e) => {
        e.preventDefault();
        // Reset wipes the paper ledger and history, so it asks first; Add and Withdraw go at once.
        const k = kind, btn = pf.querySelector(`[data-kind="${k}"]`);
        const run = () => holdFocus(null, () => busy(btn, async () => {
          try { await api('/api/funds/paper', { kind: k, amount: +pf.amount.value }); if (gen !== S.gen) return; const fresh = await refreshed(load()); if (gen === S.gen) flash('#pflash', (k === 'deposit' ? 'Added to your paper account.' : k === 'withdraw' ? 'Withdrawn from your paper account.' : 'Paper account reset.') + (fresh ? '' : BEHIND), 'good'); } catch (err) { if (gen === S.gen) flash('#pflash', err.message, 'bad'); }
        }));
        return k === 'reset' ? armed(btn, 'Confirm reset', run) : run();
      };
      // The downloaded .key file fills the box, so nobody has to open it in an editor (hard on a phone).
      root.querySelectorAll('[data-keyfile]').forEach((inp) => (inp.onchange = async () => {
        const f = inp.files && inp.files[0], box = inp.form && inp.form.private_key;
        if (!f || !box) return;
        const text = f.size <= 20000 ? (await f.text()).trim() : '';
        const where = inp.form.id === 'kalshi' ? '#kflash' : '#kdflash';
        if (!/-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(text)) { inp.value = ''; flash(where, 'That file doesn\u2019t look like a private key. Choose the .key file Kalshi downloaded.', 'bad'); return; }
        box.value = text;
        const fl = root.querySelector(where); if (fl) fl.innerHTML = '';
      }));
      const kf = root.querySelector('#kalshi');
      if (kf) kf.onsubmit = async (e) => {
        e.preventDefault();
        const bad = keyProblem(kf.key_id.value, kf.private_key.value, 'live');
        if (bad) { flash('#kflash', bad, 'bad'); return; }
        await holdFocus('#disconnect', () => busy(kf.querySelector('button'), async () => {
          try { const r = await api('/api/kalshi-key', { key_id: kf.key_id.value, private_key: kf.private_key.value }); if (gen !== S.gen) return; S.me.kalshi_connected = true; const fresh = await refreshed(load()); if (gen === S.gen) flash('#kflash', (r && r.balance != null ? `Connected ✓ (balance ${usd(r.balance)}). Kalshi confirmed the key.` : 'Connected ✓. Kalshi confirmed the key.') + (fresh ? '' : BEHIND), 'good'); } catch (err) { if (gen === S.gen) flash('#kflash', err.message, 'bad'); }
        }));
      };
      const dc = root.querySelector('#disconnect');
      if (dc) dc.onclick = () => armed(dc, 'Confirm disconnect', () => holdFocus('#kalshi [name="key_id"]', () => busy(dc, async () => {
        try { await api('/api/kalshi-key/delete', {}); if (gen !== S.gen) return; S.me.kalshi_connected = false; const fresh = await refreshed(load()); if (gen === S.gen) flash('#kflash', 'Disconnected. Tau deleted its copy of the key; the key itself stays valid until you delete it on kalshi.com.' + (fresh ? '' : BEHIND), 'good'); } catch (err) { if (gen === S.gen) flash('#kflash', err.message, 'bad'); }
      })));
      const kdf = root.querySelector('#kalshi-dev');
      if (kdf) kdf.onsubmit = async (e) => {
        e.preventDefault();
        const bad = keyProblem(kdf.key_id.value, kdf.private_key.value, 'demo');
        if (bad) { flash('#kdflash', bad, 'bad'); return; }
        await holdFocus('#dev-disconnect', () => busy(kdf.querySelector('button'), async () => {
          try { await api('/api/kalshi-dev-key', { key_id: kdf.key_id.value, private_key: kdf.private_key.value }); if (gen !== S.gen) return; S.me.kalshi_dev_connected = true; let now = null; const fresh = await refreshed(load().then((d) => { now = d; })); const bal = now && now.kalshi_dev && now.kalshi_dev.balance; if (gen === S.gen) flash('#kdflash', (bal != null ? `Connected ✓ (balance ${usd(bal)}). Kalshi’s demo exchange confirmed the key.` : 'Connected ✓. Kalshi’s demo exchange confirmed the key.') + (fresh ? '' : BEHIND), 'good'); } catch (err) { if (gen === S.gen) flash('#kdflash', err.message, 'bad'); }
        }));
      };
      const dvc = root.querySelector('#dev-disconnect');
      if (dvc) dvc.onclick = () => armed(dvc, 'Confirm remove', () => holdFocus('#kalshi-dev [name="key_id"]', () => busy(dvc, async () => {
        try { await api('/api/kalshi-dev-key/delete', {}); if (gen !== S.gen) return; S.me.kalshi_dev_connected = false; const fresh = await refreshed(load()); if (gen === S.gen) flash('#kdflash', 'Demo key removed. Tau deleted its copy; delete the key on demo.kalshi.co too if you’re done with it.' + (fresh ? '' : BEHIND), 'good'); } catch (err) { if (gen === S.gen) flash('#kdflash', err.message, 'bad'); }
      })));
      return d;
    };
    try { await load(); } catch (err) { if (gen === S.gen) throw err; }
    if (gen === S.gen) poll(load, 30000, 'funds-stale');
  }

  return {viewFunds};
});
