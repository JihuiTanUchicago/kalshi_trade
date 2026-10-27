/* Tau's Billing page: credits, the card and the statement.
   Fetched on first use (pageLoad in app.js), which hands this function what the
   bundle shares with its page files (shared()); the router calls the views it returns. */
window.TauPage('billing', (T) => {
  'use strict';
  const {
    alert0, api, armed, BEHIND, boardTitle, busy, cardFormFail, CLOCK, CLOCK_ZONE, dateFmt, esc, fig, flash,
    halfUp, ICON, KIND_LABEL, loading, loadStripe, num, paceDay, paceTooSoon, paceWords, paint, poll, refreshed,
    root, runwayLabel, S, SEP, sessionTitle, settleAt, shell, stripeFail, syncMeBilling, topupCharge, usd, waitNote, WJ,
    WEEKDAY_DAY
  } = T;

  async function viewBilling() {
    const gen = S.gen;
    shell('/billing', boardTitle('Billing', 'Credits pay for agent research and chat, billed per token for the model you pick. Paper and live trading themselves are free. The <a href="/research">research form</a> shows what a session usually costs before you start.') +
      '<dl class="figures measure" id="bfigs" style="margin-top:14px"></dl><p class="hint bill-split" id="bsplit"></p><p class="stale-note" id="bill-stale" role="status"></p>', loading(360));
    let stripe = null, card = null;
    // Below the research floor no new research starts, so the balance reads as a problem. Otherwise it is
    // neutral: credits are not profit, and wore the green a P&L gain wears.
    const isLow = (d) => d.configured && d.min_run_balance != null && d.balance < d.min_run_balance;
    // Out of credits (under the floor a research session needs): say what stopped and the next step.
    const lowNote = (d) => {
      const apOn = !!(S.me && S.me.user && S.me.user.autopilot);
      return !isLow(d) ? '' : `<div class="notice" role="status">${ICON.warn}<span>${d.balance <= 0 ? 'You’re out of credits' : `You have ${usd(d.balance)} in credits`}. New research needs at least ${usd(d.min_run_balance)} to start, so none is starting${apOn ? ' and autopilot is paused' : ''}. ${
        !d.cards.length ? 'Add a card, then add credits.' : d.auto_reload && d.reload_failed ? 'Auto-reload couldn’t charge your card (see below). Update the card first, then add credits here: they go on the same card.' : d.auto_reload ? 'Auto-reload is on but hasn’t topped you up: add credits here, or check your card.' : 'Add credits here, or turn on auto-reload so it doesn’t stop again.'}${apOn ? ' Autopilot picks up again on its own.' : ''}</span></div>`;
    };
    // The figures, the week's split and the out-of-credits note: drawn by the page's read and again by its poll.
    const paintFigs = (d) => {
      const low = isLow(d);
      paint(root.querySelector('#bfigs'),
        // Until a card was ever charged for credits (the server's card_charged), the balance is free credits: a
        // new user read $19.16 with no word that their card hadn't been charged.
        fig('Credit balance', usd(d.balance), { v: low || d.balance < 0 ? -1 : 0, small: d.card_charged === false && d.balance > 0 ? 'free credits so far: your card hasn’t been charged' : undefined }) +
        fig('Spent, last 7 days', usd(d.spent_7d), { small: [d.spent_24h != null ? `${usd(d.spent_24h)} in the last 24 hours` : '', `${usd(d.spent)} all time`].filter(Boolean).join(SEP) }) +
        // How long it lasts means until research pauses (under min_run_balance; with payments off nothing
        // pauses, so until $0), and with auto-reload on, when the card is next charged and for how much:
        // "Credits last about 2 days" in red beside auto-reload read as a stop that auto-reload prevents,
        // and at $2.40 it was a day late.
        (low ? fig('Research', 'Paused', { v: -1, small: `a session needs ${usd(d.min_run_balance)} to start` })
          : d.reload_days != null && d.auto_reload && !d.reload_failed
          ? fig('Next auto-reload in', runwayLabel(d.reload_days), { small: `adds ${usd(Math.max(d.min_reload_amount, d.autoreload_amount))}, card charged ${usd(d.autoreload_charge)}, at ${paceWords(d.spent_7d, d.pace_days)}` })
          : d.runway_days != null
          ? fig(d.configured ? 'Research pauses in' : 'Credits last', runwayLabel(d.runway_days), { v: d.runway_days < 3 ? -1 : 0, small: `at ${paceWords(d.spent_7d, d.pace_days)}${d.configured && d.min_run_balance != null ? `, when credits fall under ${usd(d.min_run_balance)}` : ''}` })
          : paceTooSoon(d.pace_days, d.spent_7d) && d.balance > 0 ? fig('Credits last', 'Too soon to tell', { small: 'your first day of research sets the pace' })
          : fig('Welcome credit', usd(d.free_bonus), { small: 'one-time, free' })));
      const split = spendSplit(d.spent_7d_by, d.spent_7d_under_cent);
      paint(root.querySelector('#bsplit'), split ? `Last 7 days: ${split}.` : '');
      const note = root.querySelector('#blow'); if (note) paint(note, lowNote(d));
    };
    let shown = null;  // the read the page shows; the poll keeps its figures current
    const load = async () => {
      const d = await api('/api/billing?tz=' + new Date().getTimezoneOffset());  // the statement's days are yours
      syncMeBilling(d);
      shown = d;
      paintFigs(d);
      const feeNote = `Credits plus a ${d.topup_fee_pct}% purchase fee.`;
      const payCard = d.cards.find((c) => c.id === d.default_pm) || d.cards[0];
      const payName = payCard ? `your ${esc((payCard.brand || 'card').toUpperCase())} •••• ${esc(payCard.last4 || '')}` : 'your card';
      const reloadWhen = (on, amount, threshold) => on
        ? `<b>On.</b> When a research or chat charge takes your balance to ${usd(threshold)} or less, we charge ${payName} for ${usd(amount)} of credits plus the ${d.topup_fee_pct}% purchase fee.`
        : d.min_run_balance != null
          ? `<b>Off.</b> Below ${usd(d.min_run_balance)} no new research starts and autopilot pauses; a session already running stops at $0. Add credits and it all picks up again.`
          : '<b>Off.</b> When your credits run low, new research sessions won’t start until you add more.';
      const cardLines = d.cards.length
        ? `<table class="table stack t-dep"><thead><tr><th>Card</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody>${d.cards.map((c) => `<tr>
            <td class="name" data-lab="Card">${esc((c.brand || 'card').toUpperCase())} •••• ${esc(c.last4 || '')}</td>
            <td data-lab="Expires">${String(c.exp_month).padStart(2, '0')}/${c.exp_year}</td>
            <td data-lab="Status">${c.id === d.default_pm ? '<span class="mk on">Default</span>' : '<span class="mk quiet">Backup</span>'}</td>
            <td class="act" data-lab="">${d.cards.length > 1 ? `<button class="btn sm danger" data-remove="${c.id}">Remove</button>` : '<span class="hint">Only card</span>'}</td></tr>`).join('')}</tbody></table>`
        : '<p class="hint">No card on file. Add one to buy credits or turn on auto-reload.</p>';
      const main = !d.configured
        ? `<div class="notice">${ICON.warn}<span>Payments aren’t enabled on this server yet. You can still use your free credits.</span></div>
           <section class="sect"><div class="sect-head"><h2>Credits &amp; usage</h2><a class="btn sm" href="/api/billing/receipt" download>Download receipt (CSV)</a></div><div id="bledger">${ledgerTable(d)}</div></section>`
        : `<div id="blow">${lowNote(d)}</div><div class="detail bill-detail">
            <div>
              <section class="panel"><h3>Payment method</h3><div id="cards">${cardLines}</div>
                <div id="card-add" style="margin-top:14px">
                  <div class="field"><span>${d.cards.length ? 'Add another card' : 'Add a card'}</span><div id="card-el" class="card-el"></div></div>
                  <div id="card-flash"></div>
                  <button class="btn" id="save-card" style="margin-top:10px">Save card</button>
                </div>
                ${reloadFailNote(d)}
                <div class="autorel-row">
                  <label class="switch"><input type="checkbox" id="autoreload" ${d.auto_reload ? 'checked' : ''}><span>Auto-reload</span></label>
                  <button type="button" class="autorel-edit" id="autorel-edit" aria-expanded="false" aria-controls="autorel-config"><span id="autorel-sum">Reload $${d.autoreload_amount} at $${d.autoreload_threshold}</span><span class="chev">${ICON.chev}</span></button>
                </div>
                <p class="hint autorel-when" id="autorel-when">${reloadWhen(d.auto_reload, d.autoreload_amount, d.autoreload_threshold)}</p>
                <div class="autorel-config" id="autorel-config" hidden>
                  <p class="autorel-line">Reload <input class="input xs" id="reload-amt" type="number" min="${d.min_reload_amount}" step="1" value="${d.autoreload_amount}"> dollars when my balance drops to <input class="input xs" id="reload-thr" type="number" min="${d.min_reload_threshold}" step="1" value="${d.autoreload_threshold}"> dollars.</p>
                  <p class="hint" id="autorel-flash" style="margin-top:4px">Minimum $${d.min_reload_amount} reload, $${d.min_reload_threshold} trigger.</p>
                </div>
              </section>
              <section class="sect"><div class="sect-head"><h2>Credits &amp; usage</h2><a class="btn sm" href="/api/billing/receipt" download>Download receipt (CSV)</a></div><div id="bledger">${ledgerTable(d)}</div></section>
            </div>
            <aside aria-label="Add credits">
              <section class="panel"><h3>Add credits</h3>
                <label class="field"><span>Amount (USD)</span><input class="input" id="topup-amt" type="number" min="${d.min_topup}" max="${d.max_topup}" step="1" value="20"></label>
                <p class="hint" id="topup-note" style="margin-top:8px">${feeNote}</p>
                <button class="btn primary" id="topup-btn" style="margin-top:12px;width:100%" ${d.cards.length ? '' : 'aria-disabled="true"'}>Buy credits</button>
                ${d.cards.length ? '' : '<p class="hint" style="margin-top:8px">Add a card first.</p>'}
                <div id="topup-flash"></div>
              </section>
            </aside>
          </div>`;
      root.querySelector('#main').innerHTML = `<div id="flash"></div>${main}`;
      if (!d.configured) return;
      // top-up fee preview
      const amt = root.querySelector('#topup-amt'), note = root.querySelector('#topup-note');
      // At the user's own pace, how long the amount being bought would last: picks the amount for them.
      const perDay = paceDay(d.spent_7d, d.pace_days);
      const lasts = (v) => (perDay && v > 0) ? ` At your pace (${paceWords(d.spent_7d, d.pace_days)}) that's ${runwayLabel(v / perDay).toLowerCase()} of research.` : '';
      // Out of range, it says the range before the press (the server refuses it in the same words).
      const upd = () => { const v = +amt.value || 0; note.textContent = v < d.min_topup || v > d.max_topup
        ? `Add between ${usd(d.min_topup)} and ${usd(d.max_topup)} in credits.`
        : `You'll pay ${usd(topupCharge(v, d.topup_fee_pct))} (${usd(v)} credits + ${d.topup_fee_pct}% fee).${lasts(v)}`; };
      amt.oninput = upd; upd();
      root.querySelector('#topup-btn').onclick = (e) => {
        if (e.currentTarget.getAttribute('aria-disabled')) { flash('#topup-flash', 'Add a card first.', 'bad'); return; }
        const waited = waitNote(e.currentTarget);
        busy(e.currentTarget, async () => {
          const credits = +amt.value;
          try {
            const r = await api('/api/billing/topup', { amount: credits }).finally(waited);
            const fresh = await refreshed(load());  // refresh balance + ledger, then confirm into the fresh panel
            flash('#topup-flash', `Added ${usd(credits)} in credits. You paid ${usd(r.charged != null ? r.charged : topupCharge(credits, d.topup_fee_pct))} — ${usd(credits)} plus the ${d.topup_fee_pct}% fee. New balance is ${usd(r.balance)}.` + (fresh ? '' : BEHIND), 'good');
          } catch (err) { flash('#topup-flash', err.message, 'bad'); }
        }, waited);
      };
      const arBox = root.querySelector('#autoreload'), arAmt = root.querySelector('#reload-amt'), arThr = root.querySelector('#reload-thr');
      const arEdit = root.querySelector('#autorel-edit'), arCfg = root.querySelector('#autorel-config'), arSum = root.querySelector('#autorel-sum');
      arEdit.onclick = () => { const open = arCfg.hidden; arCfg.hidden = !open; arEdit.setAttribute('aria-expanded', String(open)); };
      // "Update card" on a failed auto-reload: the card form above, the same save-card flow; saving
      // a card clears the failure on the server.
      let cardPe = null;
      const arFix = root.querySelector('#autorel-fix');
      if (arFix) arFix.onclick = () => { const add = root.querySelector('#card-add'); if (add.scrollIntoView) add.scrollIntoView({ block: 'center', behavior: 'smooth' }); if (cardPe && cardPe.focus) cardPe.focus(); };
      // What Tau last saved. A save that fails puts the switch, both amounts and the summary back to it:
      // the summary kept saying On after a switch-on failed, and a failed amount change flipped the
      // switch off on screen while auto-reload stayed on. The controls lock until Tau answers, so two
      // quick flips can't land out of order.
      let arSaved = { on: !!d.auto_reload, amount: d.autoreload_amount, threshold: d.autoreload_threshold };
      const arPaint = (on, amount, threshold) => {
        arBox.checked = on; arAmt.value = amount; arThr.value = threshold;
        arSum.textContent = `Reload $${amount} at $${threshold}`;
        const fail = root.querySelector('#autorel-fail'); if (fail) fail.hidden = !on;
        root.querySelector('#autorel-when').innerHTML = reloadWhen(on, amount, threshold);
      };
      const saveAutoReload = async () => {
        const on = arBox.checked;
        const amount = Math.max(d.min_reload_amount, +arAmt.value || d.min_reload_amount);
        const threshold = Math.max(d.min_reload_threshold, +arThr.value || d.min_reload_threshold);
        arPaint(on, amount, threshold);
        [arBox, arAmt, arThr].forEach((x) => { x.disabled = true; });
        const waited = waitNote(arBox.closest('.switch') || arBox);
        try {
          const r = await api('/api/billing/auto-reload', { on, amount, threshold }).finally(waited);
          arSaved = { on, amount, threshold };
          // The autopilot card and the research form read the saved auto-reload from S.me (a Billing read
          // refreshes it): a save refreshes it too, or they said the old amount until the next read.
          Object.assign(d, { auto_reload: on, autoreload_amount: amount, autoreload_threshold: threshold },
            r && r.autoreload_charge != null ? { autoreload_charge: r.autoreload_charge } : {});
          syncMeBilling(d);
          flash('#autorel-flash', on ? `On${SEP}reloads ${usd(amount)} at ${usd(threshold)}.` : 'Auto-reload off.', 'good');
        } catch (err) { arPaint(arSaved.on, arSaved.amount, arSaved.threshold); flash('#autorel-flash', err.message, 'bad'); }
        finally { [arBox, arAmt, arThr].forEach((x) => { x.disabled = false; }); }
      };
      arBox.onchange = saveAutoReload;
      arAmt.onchange = arThr.onchange = () => { if (arBox.checked) saveAutoReload(); };
      root.querySelectorAll('[data-remove]').forEach((b) => (b.onclick = () => armed(b, 'Confirm remove', () => busy(b, async () => {
        try { await api('/api/billing/remove-card', { payment_method_id: b.dataset.remove }); if (!(await refreshed(load()))) flash('#flash', 'Card removed.' + BEHIND, 'good'); } catch (err) { alert0(err.message); }
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
        cardPe = pe;
        root.querySelector('#save-card').onclick = (e) => busy(e.currentTarget, async () => {
          flash('#card-flash', '', '');
          let r;
          try { r = await sp.confirmSetup({ elements, redirect: 'if_required', confirmParams: { return_url: location.origin + '/billing', payment_method_data: { billing_details: { address: { country: 'US' } } } } }); }
          catch (err) { flash('#card-flash', stripeFail(err), 'bad'); return; }
          if (r.error) { flash('#card-flash', stripeFail(r.error), 'bad'); return; }
          try { await api('/api/billing/card-added', { payment_method_id: r.setupIntent.payment_method }); }
          catch (err) { flash('#card-flash', err.message, 'bad'); return; }
          flash('#card-flash', 'Card saved.', 'good'); await load();
        });
      } catch (err) { flash('#card-flash', cardFormFail(err).replace('then try again', 'then reload the page'), 'bad'); }
    };
    // Open, the page's figures follow the balance as research and chat spend it and auto-reload adds to it:
    // every 30s it reads the figures alone, from the database, never Stripe's card list (the page's own read
    // waits on Stripe for a paying account). When the balance moved, the statement comes along too, so its
    // sum still ends at the balance shown. The card form, top-up and auto-reload controls are left as they are.
    const refresh = async (cfg) => {
      const was = shown;
      if (!was) return;
      let f = await api('/api/billing/figures', undefined, cfg);
      if (f.balance !== was.balance) f = await api('/api/billing/figures?statement=1&tz=' + new Date().getTimezoneOffset(), undefined, cfg);
      if (gen !== S.gen || shown !== was) return;  // left, or a write's re-read drew the page meanwhile
      Object.assign(was, f);
      syncMeBilling(was);
      paintFigs(was);
      const ledger = root.querySelector('#bledger');
      if (f.ledger && ledger) paint(ledger, ledgerTable(was));
    };
    await load();
    poll(refresh, 30000, 'bill-stale');
  }
  // What a ledger line is, under its name: usage is one model call (the memo names the model), and credits
  // bought show the credits, while the card paid those plus the purchase fee. Amounts are the server's.
  // A charge under a cent (one short model call) shows three decimals instead of a misleading −$0.00.
  const ledgerAmount = (v) => { const n = +v; return n && Math.abs(n) < 0.005 ? (n < 0 ? '−' : '+') + WJ + '$' + Math.abs(halfUp(n, 3)).toFixed(3) : usd(v, true); };
  const USAGE_PREFIX = /^Agent usage\s\u00b7\s/;  // the server's memo, "Agent usage" then a middle dot
  // A usage line: what it was for (`item`: research session, autopilot research or check-in, chat)
  // over the model's name (`model`). The server sends both and never the model's internal id.
  // A usage line is one session's calls on one day: it links the research session it paid for and says
  // how many model calls it adds up. A card purchase says what the card paid and its Stripe reference.
  function ledgerNote(r, feePct) {
    if (r.kind === 'usage') {
      const model = r.model ? esc(r.model) : r.memo && !r.item ? esc(r.memo.replace(USAGE_PREFIX, '')) : '';
      return [r.session ? `<a href="/research/${+r.session.id}">${esc(sessionTitle(r.session))}</a>` : '', model,
        +r.calls > 1 ? `${num(r.calls)} model calls` : ''].filter(Boolean).join(SEP);
    }
    if (r.kind === 'topup' || r.kind === 'autoreload') {
      const paid = r.card_charge != null ? `Card charged ${usd(r.card_charge)}` : 'Card charged';
      return (feePct != null ? `${paid}: ${usd(r.amount)} credits plus the ${esc(feePct)}% purchase fee` : paid)
        + (r.stripe_ref ? `${SEP}Stripe ref <span class="ref">${esc(r.stripe_ref)}</span>` : '');
    }
    return '';
  }
  // The time of a line, or the span of a session's calls that day, in the viewer's clock.
  const clockAt = (iso, zone) => { const d = new Date(iso || NaN); return Number.isFinite(d.getTime()) ? dateFmt(d, zone ? CLOCK_ZONE : CLOCK) : '—'; };
  const lineWhen = (r) => r.first_at && r.first_at !== r.created_at ? `${clockAt(r.first_at)}–${clockAt(r.created_at, true)}` : clockAt(r.created_at, true);
  // A statement day ('2026-10-26', the viewer's day from the server) as a heading: "Today" or "Mon, Oct 26".
  const ledgerDay = (day) => {
    const [y, m, dd] = String(day).split('-').map(Number), d = new Date(y, m - 1, dd);
    if (!Number.isFinite(d.getTime())) return esc(day);
    return d.toDateString() === new Date().toDateString() ? 'Today' : dateFmt(d, WEEKDAY_DAY);
  };
  // How the balance came to be over the statement's days (/api/billing math): the balance then, plus
  // credits bought, plus other credits, minus agent usage, is the balance now. The server sends cents
  // that add up. Only what was bought and debited, never a rate.
  function billMath(m) {
    if (!m) return '';
    // An account younger than the statement starts from when it joined (the server's `joined`), not "30 days ago".
    const rows = [[m.joined ? 'Balance when you joined' : `Balance ${m.days} days ago`, usd(m.start)],
      [`Credits bought${m.purchases ? ` (${m.purchases} card charge${m.purchases === 1 ? '' : 's'})` : ''}`, usd(m.bought, true)],
      ...(+m.other ? [['Welcome and other credits', usd(m.other, true)]] : []),
      ['Agent usage', usd(-m.usage)], ['Balance now', usd(m.end)]];
    return `<dl class="bill-math">${rows.map(([k, v], i) => `<div${i === rows.length - 1 ? ' class="total"' : ''}><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
  }
  // The last auto-reload failed (/api/billing reload_failed): when, what it tried to add and why, in the
  // user's words, with a way to the card form. Shown by the auto-reload switch while it is on; '' when
  // the last auto-reload didn't fail. The server clears it when one succeeds or a card is saved.
  function reloadFailNote(d) {
    const f = d && d.reload_failed;
    if (!f || !f.text) return '';
    return `<div class="notice bad autorel-fail" id="autorel-fail" role="status"${d.auto_reload ? '' : ' hidden'}>${ICON.warn}<span><b>Auto-reload failed</b> <time datetime="${esc(f.at)}">${settleAt(f.at)}</time>. ${esc(f.text)}<button type="button" class="btn sm" id="autorel-fix">Update card</button></span></div>`;
  }
  // The week's usage by what spent it (/api/billing spent_7d_by), biggest first; '' when nothing did. The server
  // sends the parts in cents that add up to "Spent, last 7 days" (rounded each on its own they read $38.85 +
  // $0.18 + $0.18 under $39.22), and names a part that spent something but rounds to $0.00 in
  // spent_7d_under_cent: it reads "under $0.01", last, instead of being left out.
  const SPEND_SOURCE = { research: 'your research sessions', autopilot_research: 'autopilot research', autopilot_review: 'autopilot check-ins', chat: 'chat', other: 'other agent calls' };
  const spendSplit = (by, under) => {
    const tiny = (Array.isArray(under) ? under : []).filter((k) => SPEND_SOURCE[k] && !(+(by || {})[k] >= 0.005));
    return [...Object.entries(by || {}).filter(([k, v]) => SPEND_SOURCE[k] && +v >= 0.005)
      .sort((a, b) => b[1] - a[1]).map(([k, v]) => `${SPEND_SOURCE[k]} ${usd(v)}`),
    ...tiny.map((k) => `${SPEND_SOURCE[k]} under $0.01`)].join(SEP);
  };
  // Billing's statement (/api/billing ledger): the last days, newest first, under a heading per day that
  // says what the day used and added. Each usage line is one session's model calls that day.
  // Usage in cents that add up (largest remainder): each day's "used" is the sum of the lines under it, and the
  // days add up to the statement's "Agent usage" when no day was cut. Rounded each on its own, "Fri $6.99 used"
  // sat over −$6.96 and −$0.04, and the days summed a cent short of the usage above. Every figure stays within a
  // cent of its exact amount; a line under a cent keeps its three places (and the day counts it). Exact amounts
  // are in the receipt. Returns a Map of line -> cents and day -> cents, or null to show each rounded alone.
  const halfCents = (micros) => Math.floor((micros + 5000) / 1e4);
  function apportion(micros, cents) {
    const base = micros.map((v) => Math.floor(v / 1e4));
    let left = cents - base.reduce((a, b) => a + b, 0);
    if (left < 0 || left > micros.length) return micros.map(halfCents);
    micros.map((v, i) => [v % 1e4, i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]).forEach(([, i]) => { if (left > 0) { base[i] += 1; left -= 1; } });
    return base;
  }
  function usageCents(d, days) {
    if (days.some((g) => !g.day)) return null;
    const used = (r) => Math.round(-r.amount * 1e6);
    const usage = days.map((g) => g.rows.filter((r) => r.kind === 'usage'));
    if (usage.some((rs) => rs.some((r) => used(r) < 0))) return null;
    const exact = usage.map((rs) => rs.reduce((a, r) => a + used(r), 0));
    const total = !d.ledger_cut && d.math && d.math.usage != null ? Math.round(+d.math.usage * 100) : null;
    const dayCents = total == null ? exact.map(halfCents) : apportion(exact, total);
    const out = new Map();
    days.forEach((g, i) => {
      out.set(g, dayCents[i]);
      const whole = usage[i].filter((r) => used(r) >= 5000), part = usage[i].filter((r) => used(r) < 5000);
      const each = apportion(whole.map(used), dayCents[i] - halfCents(part.reduce((a, r) => a + used(r), 0)));
      // A line of half a cent or more never shows $0.00: that day keeps each line rounded on its own.
      const fair = each.every((c) => c > 0);
      whole.forEach((r, j) => out.set(r, fair ? each[j] : halfCents(used(r))));
    });
    return out;
  }
  function ledgerTable(d) {
    const rows = d.ledger || [], feePct = d.topup_fee_pct;
    if (!rows.length) return billMath(d.math) + '<p class="hint">No credit activity yet.</p>';
    const days = [];
    rows.forEach((r) => { const last = days[days.length - 1]; if (last && last.day === (r.day || '')) last.rows.push(r); else days.push({ day: r.day || '', rows: [r] }); });
    const cents = usageCents(d, days);
    // Credits added (a top-up, an auto-reload, the welcome bonus) are not profit: their amount is credit-in, a
    // tone of its own, never the green a P&L gain wears. A debit is credit-out and keeps its minus sign.
    const line = (r) => `<tr>
      <td class="hint" data-lab="When"><time datetime="${esc(r.created_at)}">${r.day ? lineWhen(r) : settleAt(r.created_at)}</time></td>
      <td class="name" data-lab="Item">${esc((r.kind === 'usage' && r.item) || KIND_LABEL[r.kind] || r.kind)}${ledgerNote(r, feePct) ? `<div class="sub-fig">${ledgerNote(r, feePct)}</div>` : ''}</td>
      <td class="num" data-lab="Amount"><span class="${r.amount >= 0 ? 'credit-in' : 'credit-out'}">${ledgerAmount(cents && cents.has(r) ? -cents.get(r) / 100 : r.amount)}</span></td></tr>`;
    const head = (g) => {
      // Summed in millionths (the ledger's six places): a float sum can land a hair under a half cent.
      const micros = (rows) => rows.reduce((s, r) => s + Math.round(r.amount * 1e6), 0) / 1e6;
      const used = cents ? cents.get(g) / 100 : -micros(g.rows.filter((r) => r.kind === 'usage'));
      const added = micros(g.rows.filter((r) => r.kind !== 'usage'));
      return `<tr class="ledger-day"><td colspan="3" data-lab="Day"><b>${ledgerDay(g.day)}</b><span class="day-sum">${[used >= 0.005 ? `${usd(used)} used` : '', added ? `${usd(added, true)} credits` : ''].filter(Boolean).join(SEP)}</span></td></tr>`;
    };
    const key = d.math ? `Last ${d.math.days} days, newest first. Each research line is one session's model calls that day; open it to see the session. Lines are rounded to the cent so they add up to their day; the receipt has every call and every card charge, exactly.`
      : 'Newest first. The receipt has every line, with exact amounts.';
    return `${billMath(d.math)}<p class="hint ledger-key">${key}</p><div class="sheet"><table class="table stack t-dep t-ledger"><thead><tr><th>When</th><th>Item</th><th class="num">Amount</th></tr></thead><tbody>${
      days.map((g) => (g.day ? head(g) : '') + g.rows.map(line).join('')).join('')}</tbody></table></div>${d.ledger_cut ? '<p class="hint">Older days are in the receipt.</p>' : ''}`;
  }

  return {viewBilling};
});
