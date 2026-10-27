/* Meridian's Funds page: the Kalshi keys and the native perps account.
   Fetched on first use (pageLoad in app.meridian.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns. */
window.TauPage('funds', (T) => {
  'use strict';
  const {
    api, armed, BEHIND, boardTitle, busy, cashFig, cashNow, cashRead, contractName, DEMO_BOOK, DEMO_WHAT, demoKeyless, demoSpan, esc, fig, flash, holdFocus, ICON, inBalance, kalshiRef, liveOpen, loading, openCost, pageAssets, PAPER_NET,
    paint, painted, poll, refreshed, root, S, SEP, settleAt, shell, tone, usd, when
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
  // Funds shows two demo figures, each named for what it is: Tau's demo book (the capital Tau sets, app_users.demo_capital,
  // plus closed demo trades) and the cash in the reader's own account on Kalshi's sandbox, which the demo key reads.
  // Both were "balance", side by side with different amounts.
  // DEMO_BOOK is the bundle's (the dashboard names the figure the same).
  const DEMO_CASH = 'Kalshi demo account cash';
  // How you know it worked: the existing balance read, right under the panel title. No balance means Kalshi
  // didn't answer for this key just now (Kalshi down, or the key deleted there), so it gets no check mark.
  // `at` is when the balance memo was read (the server's balance_at), so the line says how old it is.
  const keyOk = (bal, kind, at) => bal == null
    ? `<p class="key-ok key-unread"><b>Key saved</b> (Kalshi didn’t send a balance for it just now)</p><p class="hint key-diff">If this lasts, the key may have been deleted on ${KALSHI_KEYS[kind === 'demo' ? 'demo' : 'live'].site}: ${kind === 'demo' ? 'remove it' : 'disconnect it'} and connect a new one.</p>`
    : `<p class="key-ok"><b>Connected ✓</b> (${kind === 'demo' ? DEMO_CASH : 'balance'} ${usd(bal)}${at ? ', read ' + when(at) : ''})</p>`;
  // Kalshi refuses orders from a demo account with no cash, and a new one starts empty. Tau's demo balance is
  // Tau's own figure, so a $0.00 here would otherwise read as harmless.
  // `from` is the demo cash the autopilot's demo copies wait for (server: demo_twins), so a balance
  // under it says why no copy starts, not only an empty one.
  const demoEmpty = (bal, from) => bal == null ? '' : bal < 0.005 ? `<div class="notice" role="status">${ICON.warn}<span>Your Kalshi demo account has $0.00, so Kalshi refuses demo orders. Add demo funds in your account on ${extLink(KALSHI_KEYS.demo.join, 'demo.kalshi.co')} (play money, not real). Tau’s demo book above is Tau’s own bookkeeping and doesn’t fund it.</span></div>`
    : from && bal < from ? `<div class="notice" role="status">${ICON.warn}<span>Your Kalshi demo account has ${usd(bal)}. Demo copies of your paper strategies start once it holds ${usd(from)}: add play money in your account on ${extLink(KALSHI_KEYS.demo.join, 'demo.kalshi.co')} (not real). Tau’s demo book above is Tau’s own bookkeeping and doesn’t fund it.</span></div>` : '';

  // What the demo key's save says: Kalshi took the key, and its balance once the follow-up has it (never an error's text).
  const DEV_OK = 'Kalshi\u2019s demo exchange confirmed the key.';
  const DEV_CHECKING = `Connected \u2713. ${DEV_OK} Checking its balance\u2026`;
  const devSaid = (b) => b && b.balance != null ? `Connected \u2713 (${DEMO_CASH} ${usd(b.balance)}). ${DEV_OK}`
    : b && b.failed ? `Connected \u2713. ${DEV_OK} Tau couldn\u2019t read its balance just now. Reload in a minute to try again.`
    : `Connected \u2713. ${DEV_OK}`;
  // Each Funds figure says what it leaves out: a book's open positions, by count and cost with fees (the bundle's
  // openCost: Deploy's and the dashboard's "Cost + fee"). Paper's balance holds them at their price, so its line
  // also says how much of that is in the balance (inBalance). An API without the counts says nothing rather than "0 open".
  // `held` says where that money sits. Tau's demo book is its capital plus closed demo trades (server demo_equity), so an
  // open demo position's whole cost is still inside it (DEMO_HELD): "1 open ($2.93 at cost + fees)" didn't say where.
  // Each book says its own; none is added to another's.
  const openAt = (b, held) => b.open_positions ? `${b.open_positions} open (${openCost(b)}${held ? ', ' + held : ''})${SEP}` : '';
  const DEMO_HELD = `all of it in ${DEMO_BOOK}`;
  const openLeft = (b, mode) => b.open_positions == null ? 'Open positions not included'
    : b.open_positions ? `${b.open_positions} open ${mode} position${b.open_positions === 1 ? '' : 's'} (${openCost(b)}) not included` : `No open ${mode} positions`;
  // What each book has made: its realized P&L from closed trades, the figure the dashboard, Deploy and the
  // track record show, never added to another book's. Before a book's first close it says when one shows.
  // An API without the figure says nothing. Demo's is since its last reload, as on the dashboard.
  // Each says what it is net of, as Deploy's and the strategy page's do: every book's P&L is after Kalshi's fees, and
  // paper's after the spread too (PAPER_NET). It said "+$9.77 realized all time" beside Deploy's "after Kalshi fees".
  const BOOK_NET = { paper: PAPER_NET, demo: 'after Kalshi fees', live: 'after Kalshi fees' };
  const bookPnl = (b, mode, pnl = b.realized_pnl, span = 'all time') => b.closed_trades == null ? ''
    : b.closed_trades ? `${usd(pnl, true)} realized ${span}, ${BOOK_NET[mode]}${SEP}` : `P&amp;L shows once a ${mode} trade closes${SEP}`;
  // With live trading closed (the server's live switch, liveOpen) "shows once a live trade closes" read as if one could.
  const livePnl = (k) => k.closed_trades == null ? '' : k.closed_trades ? ` Tau\u2019s live trades: ${usd(k.realized_pnl, true)} realized all time, ${BOOK_NET.live}.`
    : k.connected ? (liveOpen() ? ' Tau\u2019s live P&amp;L shows once a live trade closes.' : ' Live trading isn\u2019t open yet, so Tau places no live trades.') : '';
  // The Kalshi cash line's last part, a sentence of its own: it ended "No open live positions" with no stop.
  // With live trading closed and nothing open it says nothing: "No open live positions." came right after "Live
  // trading isn’t open yet", which had already said it.
  const liveLeft = (k) => !liveOpen() && k.open_positions != null && !+k.open_positions ? '' : ' ' + openLeft(k, 'live') + '.';
  // Not connected: the Kalshi cash figure links to the live key's form, in Connect Kalshi while no key of either
  // kind is in (its fold), else in the page. It said "Connect a key to trade real money" with nowhere to go
  // (Meridian said nothing at all).
  const connectLive = (kd) => `<a href="${kd.connected ? '#kalshi' : '#connect-kalshi'}">Connect a Kalshi key</a> below to trade real money`;
  const KALSHI_UNREAD = 'Kalshi didn\u2019t answer just now. Reload in a minute to try again.';
  // A key's cash the shell's first read couldn't name without waiting on Kalshi (shell_reads.py) comes
  // pending (the bundle's cashFig and cashRead, which the dashboard shares): it reads Checking\u2026, never $0,
  // and a figure the server read earlier shows only with its age; a follow-up that fails says so plainly.
  const lastRead = (b) => `${usd(b.last_balance)}, read ${when(b.last_balance_at)}`;
  // The key line under a panel title, and the Cash at Kalshi cell, in the same states; keyOk otherwise.
  const cashName = (kind) => kind === 'demo' ? DEMO_CASH : 'balance';
  const keyLine = (b, kind) => b.pending ? `<p class="key-ok key-unread"><b>Key saved</b> (${b.last_balance != null ? cashName(kind) + ' ' + lastRead(b) + '; checking for the latest' : kind === 'demo' ? 'checking your Kalshi demo account cash' : 'checking your balance at Kalshi'}\u2026)</p>`
    : b.failed ? `<p class="key-ok key-unread"><b>Key saved</b> (${b.last_balance != null ? cashName(kind) + ' ' + lastRead(b) + '; ' : ''}Tau couldn\u2019t check it just now. Reload in a minute to try again.)</p>`
    : keyOk(b.balance, kind, b.balance_at);
  const cashCell = (b) => b.pending ? (b.last_balance != null ? `${lastRead(b)}; checking\u2026` : 'Checking\u2026')
    : b.failed ? (b.last_balance != null ? `${lastRead(b)}; couldn\u2019t check it just now` : 'Couldn\u2019t check it just now')
    : b.balance == null ? 'Couldn\u2019t read it just now' : usd(b.balance);
  // The demo key's line: its $0 or short-balance notice only from a figure Kalshi just sent.
  const demoLine = (kd) => keyLine(kd, 'demo') + (kd.pending || kd.failed ? '' : demoEmpty(kd.balance, kd.copies_from));
  // A paper history line in plain words. The engine writes prices as dollars ("@ 0.40") and exit reasons as
  // codes ("stop_loss"); a settled row's $0.00 read as nothing happening when the contract lost. Display only:
  // the stored memo and the amount are unchanged.
  const ledgerWhat = (r) => {
    const memo = String(r.memo || r.kind || '').replace(/ (@|->) (\d*\.\d+)/g, (m, w, p) => ` ${w === '@' ? 'at' : '\u2192'} ${Math.round(+p * 100)}\u00a2`)
      .replace(/\(([a-z]+(?:_[a-z]+)+)/g, (m, c) => '(' + c.replace(/_/g, ' '));
    const settled = r.kind === 'settlement' ? (+r.amount > 0 ? `${SEP}won, paid $1 a contract` : `${SEP}lost, paid $0`) : '';
    // The contract goes by its plain name, as an open position does (contractName: "Bitcoin up or down in 15
    // minutes"); its ticker carries the raw series key, so it moves to the small line under it (kalshiRef).
    const t = LEDGER_TICKER.exec(memo);
    const said = t ? esc(memo.slice(0, t.index)) + esc(contractName(t[0])) + esc(memo.slice(t.index + t[0].length)) : esc(memo);
    // The words and the settled note are one inline run: the stacked cell is a flex row, so the note was an item
    // of its own and at 390px "· won, paid $1 a contract" began a line under "settled YES".
    return `<span class="ledger-said">${said}${settled ? `<span class="hint">${settled}</span>` : ''}</span>` + (t ? `<div class="sub-fig">${kalshiRef(t[0])}</div>` : '');
  };
  // A Kalshi contract ticker in a memo: its series, then the event's date (KXBTCD-26OCT2617-T114999.99).
  const LEDGER_TICKER = /\b[A-Z][A-Z0-9]*-\d{2}[A-Z]{3}\d{2}(?:[A-Z0-9.-]*[A-Z0-9])?/;
  // When cash moved: the clock and its zone, with the date on any day but today (settleAt), never a bare "Oct 24".
  const ledgerAt = (iso) => `<time datetime="${esc(iso || '')}">${esc(settleAt(iso))}</time>`;
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
    // /api/funds never waits on Kalshi: a key's cash the server hadn't read in the last minute comes pending, in
    // the shell's read, a visit's and the poll's alike. Once the page has drawn, each book's cash is asked for
    // on its own (neither waits on the other's Kalshi read) and drawn into the figures and its spots in the
    // panels. One that fails says so. A later full read (a write, the poll) supersedes it.
    let shown = null;
    // cashAsk: each book's follow-up for the answer last read in full, resolving to its cash once back (the demo
    // key's save says its balance from it).
    let cashAsk = {};
    // A poll that lands while a follow-up is out and doesn't repaint the panels (nothing in them moved, or someone
    // is using them) asks no follow-up of its own, yet becomes the answer shown: the follow-up still out then
    // lands on it while it has the same key's cash pending (its fill was dropped until the next read). A read
    // that asked its own follow-up (a repaint, a write) takes that one instead.
    const landed = (b, next) => {
      if (next.failed) return { ...b, pending: false, failed: true };
      const { pending, last_balance, last_balance_at, ...kept } = b;
      return { ...kept, connected: next.connected, balance: next.balance, balance_at: next.balance_at };
    };
    const fillCash = (d) => { cashAsk = {}; [['live', 'kalshi'], ['demo', 'kalshi_dev']].forEach(([book, key]) => {
      const b = d[key];
      if (!b || !b.pending) return;
      const fill = (next) => {
        if (gen !== S.gen) return;
        const s = shown && shown[key];
        const now = shown === d ? d : cashAsk[book] === ask && s && s.pending && s.key_id === b.key_id ? shown : null;
        if (!now) return;
        now[key] = landed(now[key], next);
        // The key went in the meantime: read it all afresh. Otherwise only the cash changed.
        (next.connected ? load(null, now) : load()).catch(() => {});
      };
      const ask = cashAsk[book] = cashRead(b, book).then((next) => { fill(next); return next; });
    }); };
    // After a demo key's save: its cash is read after the save (the old key's was forgotten), so the flash says the
    // balance is being checked and then names it once that follow-up is back, unless something else has been said
    // there since. `now` is the page's read after the save (pending: its follow-up is in cashAsk.demo).
    const devFlash = (now, fresh) => {
      const kd = now && now.kalshi_dev, behind = fresh ? '' : BEHIND;
      const ask = kd && kd.pending ? cashAsk.demo : null;
      if (!ask) { flash('#kdflash', devSaid(kd) + behind, 'good'); return; }
      flash('#kdflash', DEV_CHECKING + behind, 'good');
      ask.then((b) => {
        const el = root.querySelector('#kdflash .notice span');
        if (gen === S.gen && el && el.textContent === DEV_CHECKING + behind) flash('#kdflash', devSaid(b) + behind, 'good');
      });
    };
    // /funds#connect-kalshi (the "connect a demo key on Funds" links elsewhere) opens Connect Kalshi on the page's first
    // paint and brings it into view. An account with a key has no fold: the link goes to the key form it lacks.
    let linked = location.hash !== '#connect-kalshi';
    const openLinked = (host) => {
      if (linked) return;
      linked = true;
      const fold = host.querySelector('#connect-kalshi'), form = host.querySelector('#kalshi, #kalshi-dev');
      const to = fold || (form && form.closest('section'));
      if (fold) fold.open = true;
      if (to && to.scrollIntoView) to.scrollIntoView({ block: 'start' });
    };
    // `got`: the page's own answer with a key's cash filled in (fillCash); else /api/funds is read.
    const load = async (cfg, got) => {
      const d = got || await api('/api/funds', undefined, cfg);
      if (gen !== S.gen) return;
      shown = d;
      // Drawn from cashNow: a pending cash read under two minutes ago shows as current while its follow-up is out.
      const k = cashNow(d.kalshi);
      const kd = cashNow(d.kalshi_dev || { connected: false });
      const dm = d.demo || { capital: 0, equity: 0, realized: 0 };
      // No demo key and a demo book that never traded: no demo figure (the bundle's demoKeyless). Its line named the
      // sandbox twice ("to trade Kalshi’s sandbox · real fills on Kalshi’s sandbox, not real money").
      const DEMO_SANDBOX = 'real fills, not real money';
      const demoNone = demoKeyless(dm, !!kd.connected);
      const cf = k.connected && cashFig(k);
      paint(root.querySelector('#ffigs'), fig('Kalshi cash', k.connected ? (cf ? cf[0] : k.balance == null ? 'Unavailable' : usd(k.balance)) : 'Not connected', { cls: 'lead', small: !k.connected ? connectLive(kd) + (livePnl(k) ? '.' + livePnl(k) : '') : cf ? `${cf[1]}${livePnl(k)}${liveLeft(k)}` : k.balance == null ? KALSHI_UNREAD + livePnl(k) : `Real money at Kalshi${k.balance_at ? ', read ' + when(k.balance_at) : ''}.${livePnl(k)}${liveLeft(k)}` }) +
        (!demoNone ? fig(DEMO_BOOK, usd(dm.equity), { small: `${usd(dm.capital)} ${dm.before_reload ? 'capital at last reload' : 'starting capital'}${SEP}${openAt(dm, DEMO_HELD)}${bookPnl(dm, 'demo', dm.realized, demoSpan(dm))}${kd.connected ? '' : `needs a demo key${SEP}`}${DEMO_WHAT}` }) : fig(DEMO_BOOK, 'No demo key', { small: `<a href="#connect-kalshi">Connect a demo key</a> below to trade Kalshi’s sandbox: ${DEMO_SANDBOX}` })) +
        fig('Paper balance', usd(d.paper.equity == null ? d.paper.cash : d.paper.equity), { small: `${usd(d.paper.cash)} cash${SEP}${openAt(d.paper, inBalance(d.paper))}${bookPnl(d.paper, 'paper')}`.replace(/\u00a0\u00b7 $/, '') }));
      // A new account (no Kalshi key of either kind) reads Paper first, the account the autopilot trades, and the
      // key forms fold under Connect Kalshi: it opened on the live-key form and the demo key's steps. An account
      // with a key keeps live, demo, paper.
      const keyless = !k.connected && !kd.connected, sub = keyless ? 'funds-sub' : 'panel';
      const liveSec = `<section class="${sub}">
          <h2>Kalshi account (live money)</h2>
          ${k.connected ? `
            <div data-cash="live-ok">${keyLine(k, 'live')}</div><dl class="kv"><dt>API key</dt><dd>${esc(k.key_id)}</dd><dt>Cash at Kalshi</dt><dd data-cash="live-cell">${cashCell(k)}</dd></dl>
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
        </section>`;
      const demoSec = `<section class="${sub}">
          <h2>Kalshi demo (sandbox) account</h2>
          ${!demoNone ? `
          <dl class="kv"><dt>${DEMO_BOOK}</dt><dd>${usd(dm.equity)}</dd><dt>${dm.before_reload ? 'Capital at last reload' : 'Starting capital'}</dt><dd>${usd(dm.capital)}</dd><dt>Realized ${demoSpan(dm)}</dt><dd class="${tone(dm.realized)}">${usd(dm.realized, true)}</dd></dl>
          <p class="lede" style="margin-bottom:14px">Real orders on Kalshi’s sandbox exchange, to prove the order path before live money. The sandbox book is thin, so its fills and P&amp;L are no evidence of the edge; paper keeps that job. The money is simulated. Reloading changes Tau’s demo book only and starts realized P&amp;L since reload at $0.00; the track record still counts every closed demo trade.</p>
          <form id="demo" class="amount">
            <label class="field"><span>Reload to</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="1000"></label>
            <button class="btn" type="submit">Reload demo</button>
          </form>
          <div id="dmflash" style="margin-top:10px"></div>
          ` : `
          <p class="lede" style="margin-bottom:14px">Real orders on Kalshi’s sandbox exchange, to prove the order path before live money. The sandbox book is thin, so its fills and P&amp;L are no evidence of the edge; paper keeps that job. Tau’s demo book and its reload show here once a demo key is connected.</p>
          `}
          <h3 style="margin-top:24px">Demo key</h3>
          ${kd.connected ? `
            <div data-cash="demo-ok">${demoLine(kd)}</div><dl class="kv"><dt>Demo key</dt><dd>${esc(kd.key_id)}</dd></dl>
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
        </section>`;
      const paperSec = `<section class="panel">
          <h2>Paper account (simulation)</h2>
          <p class="lede" style="margin-bottom:14px">Simulated funds. No real orders.</p>
          <form id="paper" class="amount">
            <label class="field"><span>Amount</span><input class="input" name="amount" type="number" min="1" max="100000" step="0.01" inputmode="decimal" required placeholder="500"></label>
            <button class="btn" data-kind="deposit" type="submit">Add</button>
            <button class="btn ghost" data-kind="withdraw" type="submit">Withdraw</button>
            <button class="btn ghost" data-kind="reset" type="submit">Reset to amount</button>
          </form>
          <div id="pflash" style="margin-top:10px"></div>
        </section>`;
      const accounts = keyless ? paperSec + `<details class="panel funds-connect" id="connect-kalshi"><summary><span class="funds-connect-h">Connect Kalshi</span><span class="hint">For live money, or Kalshi’s demo sandbox. The autopilot trades paper, which needs neither.</span></summary>${liveSec}${demoSec}</details>`
        : liveSec + demoSec + paperSec;
      const host = root.querySelector('#main'), main = `<div id="flash"></div><div class="funds">
        <div class="funds-col funds-manage">
        ${accounts}
        </div>
        <div class="funds-col funds-history">
        ${S.me.perps_live_available ? '<section id="kalshi-perps-live" aria-label="Bitcoin perpetual trading"></section>' : ''}
        <section class="panel">
          <h2>Paper history</h2>
          <p class="hint ledger-how">${LEDGER_HOW}${d.paper.ledger.length >= 50 ? ' The latest 50 entries.' : ''}</p>
          <table class="table stack t-ledger"><thead><tr><th>When</th><th>What</th><th class="num">Amount</th></tr></thead><tbody>
            ${d.paper.ledger.map((r) => `<tr><td class="hint lead-cell" data-lab="When">${ledgerAt(r.created_at)}</td><td class="name" data-lab="What">${ledgerWhat(r)}</td><td class="num ${tone(+r.amount)}" data-lab="Amount">${usd(r.amount, true)}</td></tr>`).join('')}
          </tbody></table>
        </section>
        </div></div>`;
      if (got) {
        // Only the cash changed: its spots are filled in place, so what someone is typing, an armed confirm or
        // the perps box stay as they are.
        const spots = { 'live-ok': () => keyLine(k, 'live'), 'live-cell': () => cashCell(k), 'demo-ok': () => demoLine(kd) };
        host.querySelectorAll('[data-cash]').forEach((el) => { const f = spots[el.dataset.cash]; if (f) el.innerHTML = f(); });
        painted.set(host, main);
        return d;
      }
      if (cfg && (painted.get(host) === main || S.perps || inUse(host))) return;
      // A poll's redraw keeps Connect Kalshi open if it was.
      const connectOpen = !!(host.querySelector('#connect-kalshi') || {}).open;
      host.innerHTML = main; painted.set(host, main);
      if (connectOpen && host.querySelector('#connect-kalshi')) host.querySelector('#connect-kalshi').open = true;
      openLinked(host);
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
          try { await api('/api/kalshi-dev-key', { key_id: kdf.key_id.value, private_key: kdf.private_key.value }); if (gen !== S.gen) return; S.me.kalshi_dev_connected = true; let now = null; const fresh = await refreshed(load().then((d) => { now = d; })); if (gen === S.gen) devFlash(now, fresh); } catch (err) { if (gen === S.gen) flash('#kdflash', err.message, 'bad'); }
        }));
      };
      const dvc = root.querySelector('#dev-disconnect');
      if (dvc) dvc.onclick = () => armed(dvc, 'Confirm remove', () => holdFocus('#kalshi-dev [name="key_id"]', () => busy(dvc, async () => {
        try { await api('/api/kalshi-dev-key/delete', {}); if (gen !== S.gen) return; S.me.kalshi_dev_connected = false; const fresh = await refreshed(load()); if (gen === S.gen) flash('#kdflash', 'Demo key removed. Tau deleted its copy; delete the key on demo.kalshi.co too if you’re done with it.' + (fresh ? '' : BEHIND), 'good'); } catch (err) { if (gen === S.gen) flash('#kdflash', err.message, 'bad'); }
      })));
      if (!got) fillCash(d);  // every fresh read: the first, a visit's, the poll's and a write's
      return d;
    };
    try { await load(); } catch (err) { if (gen === S.gen) throw err; }
    if (gen === S.gen) poll(load, 30000, 'funds-stale');
  }

  return {viewFunds};
});
