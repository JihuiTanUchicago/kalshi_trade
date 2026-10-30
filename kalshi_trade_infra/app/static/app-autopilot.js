/* Tau's autopilot panel, open: its controls, the activity feed and the chat.
   Fetched the first time the panel opens (pageLoad in app.js), which hands this function what the
   bundle shares with its page files (shared()); the pill (renderAutopilot) calls what it returns. */
window.TauPage('autopilot', (T) => {
  'use strict';
  const {
    alert0, announce, AP_CARD_FIX, AP_FOCUS, AP_MODE, AP_PICKING, apAction, apExpanded, apSaid, apFlash, apFloorText,
    apFocusPaint, apFocusText, api, apIdleHtml, ApiError, apLastHtml, apLiveBlock, apLiveBlockHtml, apMarketNames, apReloadFailed, apShowFocus,
    apEvery, apStale, apStillTrading, apStory, apSwitchOn, apWeek, busy, clock, esc, failText, feedMd, gl, go, ICON, mdLite, num,
    liveIdleCount, liveIdleShort, liveOpen, paced, paintDashAp, paperCount, PAPER_COUNT_WHY, PAPER_NET, pausesIn, refreshAutopilot, S, SEP, settleAt, sinceMin, slipEst, usd, waitNote, waitSpan,
    wakers
  } = T;

  // The float is the single home for autopilot: the on/off toggle, live controls, and the agent
  // chat. The expanded shell is built ONCE; the 20s status poll updates only dynamic bits so it
  // never wipes the chat/composer. apChatTimer polls chat (3s) only while expanded.
  let apChatLastId = 0, apChatTimer = null, apFeedFirst = true, apFeedDay = '';
  // The feed's day line: the rail's times are the reader's clock, so each day starts with its date and zone.
  const tzShort = () => { try { return (new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName') || {}).value || ''; } catch (e) { return ''; } };
  function apDayLi(iso) {
    const d = new Date(iso), li = document.createElement('li'), today = new Date();
    const yest = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    const label = d.toDateString() === today.toDateString() ? 'Today' : d.toDateString() === yest.toDateString() ? 'Yesterday'
      : d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    li.className = 'ap-day';
    li.textContent = label + (tzShort() ? `${SEP}times in ` + tzShort() : '');
    return li;
  }
  // A send or a decision that failed says why just above the composer. alert0 put it at the top of the
  // page, under the panel, and a phone's full-screen sheet hid it altogether.
  // A send Tau didn't confirm (no reply, or the edge's 5xx) may have landed. Reloading isn't the check: the
  // chat reads every few seconds while it is open, so a message that went through shows up in it.
  const sendUnsure = (err) => err instanceof ApiError && err.message === failText(0, true);
  const CHAT_UNSURE = 'Tau didn\u2019t confirm your message. If it went through, it shows up in the chat in a few seconds; if it doesn\u2019t, send it again.';
  function apErr(box, msg, billing) {
    const el = box.querySelector('#apf-err');
    if (!el) { if (msg) alert0(msg); return; }
    // Out of credits (402) says where to add them, as a link, not "the Billing tab" to go and find.
    if (msg && billing) el.innerHTML = `${esc(msg)} <a href="/billing">Open Billing</a>`;
    else el.textContent = msg || '';
    el.hidden = !msg;
  }
  // The line under the composer: what the agent may do with a message, and what one costs. The cost is
  // the server's turn_cost (what the newest answered message debited), kept from the last read that had it.
  let apTurnCost;
  const AP_DRAFT = () => 'tau_ap_draft:' + ((S.me && S.me.user && S.me.user.id) || '');
  function apCostPaint(box) {
    const el = box.querySelector('#apf-cost'); if (!el) return;
    const me = S.me || {}, on = S.ap ? S.ap.autopilot : !!(me.user && me.user.autopilot);
    const what = on ? 'It may act on what you ask, within your limits.' : 'Any change it suggests waits for you to approve it.';
    const c = apTurnCost, last = c == null ? '' : c === 0 ? ' Your last one cost nothing.'
      : c < 0.005 ? ' Your last one cost under $0.01.' : ` Your last one cost ${usd(c)}.`;
    el.textContent = what + (me.billing_enabled ? ' Each message is paid from your credits.' + last : '');
    el.hidden = false;
  }
  function apStopChat() { if (apChatTimer) { clearInterval(apChatTimer); apChatTimer = null; } apChatWake = null; }
  let apChatWake = null;
  wakers.add(() => { if (apChatWake && !document.hidden) apChatWake(); });
  // The autopilot's autonomous moves, keyed by the proposal kind on a system line — the clear,
  // plain verb a reader scans ("Promoted", "Tuned"), plus the timeline lane that tints the node.
  // No proposal on a system line = a review/holding/blocked note (nothing was changed).
  const AP_ACT = {
    research: 'Research', deploy: 'Promoted to paper', deploy_live: 'Promoted to live',
    adjust: 'Tuned strategy', set_risk: 'Tuned risk', set_exec: 'Tuned execution',
    pause: 'Paused', resume: 'Resumed',
    alpaca_paper: 'Alpaca paper order',
    kalshi_perps_live: 'Bitcoin perps live order',
  };
  // A proposal still waiting on you is headed by what it asks, not the done verb above: "Paused" and
  // "Promoted to paper" sat over Approve and Decline, as if it had already happened. Its line under
  // that says what Approve does and in which book (paper, demo or live) before anyone presses it.
  const AP_ASK = {
    deploy: 'Asks to put on paper', adjust: 'Asks to tune a strategy', pause: 'Asks to pause', resume: 'Asks to resume',
    set_risk: 'Asks to change risk limits', set_exec: 'Asks to change execution limits',
  };
  const AP_BOOK = { paper: 'on paper, with practice money', demo: 'on demo, Kalshi\u2019s sandbox with no real money', live: 'LIVE, with real money in your Kalshi account' };
  function apApproveLine(m) {
    const k = m.proposal_kind, book = AP_BOOK[m.deployment_mode];
    const verb = { pause: 'pauses', resume: 'restarts', adjust: 'swaps the tuned version into' }[k];
    // A pause sells what the strategy holds (the engine flattens a paused deployment), as Deploy's Pause says.
    const sells = k === 'pause' ? ', and sells anything it holds' : '';
    if (verb) return book ? { text: `Approve ${verb} this strategy, which runs ${book}${sells}.`, live: m.deployment_mode === 'live' } : null;
    if (k === 'deploy') return { text: 'Approve starts it on paper, with practice money. Nothing trades real money.' };
    if (k === 'set_risk' || k === 'set_exec') return { text: 'Approve applies these limits to every strategy you run, live ones included.' };
    return null;
  }
  // Lines no review wrote, headed as what they are. Each sat under "Reviewed": your own market focus and kill
  // switch, a deploy from the Deploy page, and the engine's stop-loss sale and daily loss stops (the server says
  // those in words, customer_text.chat_rows).
  const AP_OTHER = [
    [/^Market focus (?:set to|cleared)\b/, 'Market focus'],
    [/^Deployed .+ on (?:paper|LIVE money|the demo \(sandbox\) exchange)\.$/, 'You deployed'],
    [/^Kill switch:/, 'Kill switch'],
    [/^Sold an? (?:YES|NO) position of .+ automatically:/, 'Sold automatically'],
    [/^(?:Live autopilot auto-disabled|Live trading stopped):/, 'Live stopped'],
  ];
  // One feed entry, rendered with the SAME research-session parts (.ln timeline rail, .say card,
  // feedMd markdown, lane tint) so the autopilot reads as one family with the research log —
  // a legible end-to-end session, not a cramped chat. m.content is Markdown; m.stage/m.strategy/
  // m.detail are OPTIONAL structured fields the backend can add later (see the note in PLAN.md).
  // The agent's reply is shown as it said it, typeset: an apostrophe inside a word is curly ("Bitcoin’s", "can’t"), as
  // every line Tau writes is. Code (fenced or `inline`) and the reader's own lines are left exactly as typed.
  const apTypeset = (s) => String(s == null ? '' : s).split(/(```[\s\S]*?```|`[^`\n]*`)/)
    .map((part, i) => (i % 2 ? part : part.replace(/([A-Za-z])'(?=[A-Za-z])/g, '$1\u2019'))).join('');
  function apFeedLi(m) {
    const li = document.createElement('li');
    const t = `<time datetime="${esc(m.created_at)}" title="${esc(settleAt(m.created_at))}">${clock(m.created_at)}</time><span class="node" aria-hidden="true"></span>`;
    if (m.role === 'user') {
      li.className = 'ln lane-state apf-you';
      li.innerHTML = `${t}<div class="say"><span class="say-kind">You</span>${mdLite(m.content)}</div>`;
      return li;
    }
    if (m.role !== 'system') {   // the agent's think-aloud reasoning
      li.className = 'ln lane-think apf-think';
      li.innerHTML = `${t}<div class="say"><span class="say-kind">Agent</span><div class="apf-md">${feedMd(apTypeset(m.content))}</div></div>`;
      return li;
    }
    // A system line = an autopilot action (or a blocked/holding note).
    // The switch notes ("Autopilot is ON: …") were labelled Reviewed, so a new user's first feed line
    // said it had reviewed something seconds after the click, before any review ran.
    const flip = !m.proposal_kind && /^(LIVE )?autopilot is (ON|OFF)\b/i.exec(m.content || '');
    const st = m.proposal_status;
    // Your own decision and a failed answer are not reviews: both read "Reviewed" here.
    const said = /^You (approved|declined) the proposal/.test(m.content || '') ? 'Your decision'
      : /^The agent hit an error/.test(m.content || '') ? 'No answer' : '';
    // Asked in chat to pause a strategy on paper under a day (or a tournament entrant), the agent's reply
    // can suggest pausing it, and then this line says "I left it running": under "Reviewed" it read as
    // the same voice taking it back. It is the autopilot's own rule (agent.act), so it is headed as
    // that, and says that your own Pause on Deploy still stops it.
    // (A tournament entrant's line reads "it is in its paper test" since customer_text.tournament_line says it plainly.)
    const rule = !m.proposal_kind && /^I left .+ running: it (?:has been on paper for only|is a paper tournament entrant|is in its paper test)/.test(m.content || '');
    // The engine's own loss guard or drawdown limit paused a strategy (the server says it by name,
    // customer_text.auto_pause_line): no review ran, so it isn't headed "Reviewed".
    const guard = !m.proposal_kind && /^Paused (?:your (?:paper|demo|live) strategy .+|one of your strategies) automatically\b/.test(m.content || '');
    const other = !m.proposal_kind && (AP_OTHER.find(([rx]) => rx.test(m.content || '')) || [])[1];
    const kind = (st === 'pending' && AP_ASK[m.proposal_kind]) || AP_ACT[m.proposal_kind]
      || (flip ? (flip[1] ? 'Live autopilot ' : 'Autopilot ') + (/on/i.test(flip[2]) ? 'on' : 'off')
        : said || (rule ? 'Autopilot’s rule: kept running' : guard ? 'Paused automatically' : other || 'Reviewed'));
    const own = rule ? '<p class="apf-ask apf-rule">To stop it anyway, pause it yourself on <a href="/deploy">Deploy</a>.</p>' : '';
    const lane = !m.proposal_id ? 'state' : st === 'pending' ? 'review' : st === 'applied' ? 'action' : 'void';
    const stamp = st === 'applied' ? `<span class="hx-stamp pass">${m.proposal_kind === 'alpaca_paper' ? 'Approved' : 'Applied'}</span>`
      : st === 'declined' || st === 'rejected' ? '<span class="hx-stamp rej">Declined</span>' : '';
    const stage = m.stage ? `<span class="hx-tag">${esc(m.stage)}</span>` : '';
    const title = m.strategy ? `<b class="say-title">${esc(m.strategy)}</b>` : '';
    const detail = m.detail ? `<details class="hx-more"><summary>Show the detail</summary><div class="hx-body"><div class="apf-md">${feedMd(m.detail)}</div></div></details>` : '';
    const ask = st === 'pending' ? apApproveLine(m) : null;
    const ctl = (m.proposal_id && st === 'pending')
      ? `${ask ? `<p class="apf-ask${ask.live ? ' live' : ''}">${esc(ask.text)}</p>` : ''}<div class="proposal" data-prop="${m.proposal_id}"><button class="btn small" data-decide="approve">${m.proposal_kind === 'kalshi_perps_live' ? 'Review live order' : 'Approve'}</button><button class="btn ghost small" data-decide="reject">Decline</button></div>` : '';
    li.className = 'ln lane-' + lane + ' apf-act';
    li.innerHTML = `${t}<div class="say">
      <div class="hx-head"><span class="say-kind">${esc(kind)}</span>${title}${stage}${stamp}</div>
      <div class="apf-md">${feedMd(m.content)}</div>${own}${detail}${ctl}</div>`;
    return li;
  }
  // Resolves false when the read failed (the chat poll backs off on it; other callers ignore it).
  // `follow`: 'end' brings the newest line into view (you just sent one), 'keep' holds the reader's place
  // through a full repaint (a decision mid-history). Otherwise it follows only a reader already at the end.
  // On a phone the open panel is one scroll (app.css), so the sheet is what scrolls there, not the feed:
  // a sent message and its answer landed below the fold, under a sheet still showing the controls.
  async function apLoadChat(box, full, cfg, follow) {
    const msgs = box.querySelector('#apf-messages'); if (!msgs) return;
    let d; try { d = await api('/api/chat?after=' + (full ? 0 : apChatLastId), undefined, { keep: true, ...cfg }); }
    catch (e) {
      // Nothing painted yet: say the feed didn't load rather than leave it blank. The poll retries.
      // Try again reads now: the poll backs off while reads fail (walk 2026-10-28: still "Retrying." 5s after Tau was back).
      if (!msgs.children.length) {
        msgs.innerHTML = '<li class="ap-empty ap-fail">Couldn\u2019t load the autopilot\u2019s activity. Retrying. <button type="button" class="btn sm" data-ap-chat-retry>Try again</button></li>';
        const again = msgs.querySelector('[data-ap-chat-retry]');
        if (again) again.onclick = () => { again.disabled = true; apLoadChat(box, true); };
      }
      return false;
    }
    msgs.querySelectorAll('.ap-fail').forEach((n) => n.remove());
    const atEnd = (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 70;
    const sheet = box.scrollHeight > box.clientHeight + 1;
    const stick = follow === 'end' || (full && follow !== 'keep') || atEnd(msgs);
    const stickSheet = follow === 'end' || (!full && sheet && atEnd(box));
    const kept = [msgs.scrollTop, box.scrollTop];
    if (full) { msgs.innerHTML = ''; apChatLastId = 0; apFeedFirst = true; apFeedDay = ''; }
    const empty = msgs.querySelector('.ap-empty'); if (empty && d.messages.length) empty.remove();
    msgs.querySelectorAll('.apf-typing').forEach((n) => n.remove());
    let moved = false;
    d.messages.forEach((m) => {
      if (m.id <= apChatLastId) return;  // a slow read that lands after a newer one already painted it
      apChatLastId = Math.max(apChatLastId, m.id);
      if (!full && m.role === 'system') moved = true;
      const day = new Date(m.created_at).toDateString();
      if (day !== apFeedDay) { apFeedDay = day; msgs.appendChild(apDayLi(m.created_at)); }
      const li = apFeedLi(m);
      if (!apFeedFirst) li.classList.add('in');   // backlog lands silently; new moves rise in
      msgs.appendChild(li);
    });
    if (d.messages.length) apFeedFirst = false;
    // A move that just landed in the feed (a change it made from your message, a pause, a sale) changes the
    // figures above it: they are read again now, not on the next 20s status poll. "Last move 6m ago" and the
    // old running count sat over a risk change the feed showed seconds before.
    if (moved) refreshAutopilot(box);
    if ('turn_cost' in d) { apTurnCost = d.turn_cost; apCostPaint(box); }
    if (!msgs.children.length) msgs.innerHTML = '<li class="ap-empty">No autopilot activity yet. While it\u2019s on, it checks in on its own schedule: it reviews what\u2019s running, starts research, and puts the strategies that pass every research test on paper (pretend money). It trades real money only if you also turn on live autopilot. Each move lands here as it happens. Message it below to steer.</li>';
    // The live pulse — the research session's "working" signal, scoped to the operation.
    const pulse = box.querySelector('#apf-pulse');
    if (pulse) {
      pulse.hidden = false;
      pulse.className = 'runpulse apf-pulse-row';
      // Past the reaper's limit the spinner would claim work nobody is doing; say how long instead.
      const w = d.agent_wait;
      // The pulse is a polite live region and this runs on every chat poll (3s): rewriting the same words
      // made a screen reader say "Between reviews · 2 on paper" again each time. Only a change is written.
      // What it says leaves out the minutes that tick ("last move 4m ago", "for 6m"): the shown line, hidden
      // from the reader, keeps counting, and its words go out only when the status itself changes.
      const waitWho = w && (w.state === 'queued' ? 'Waiting for a free worker' : 'No word from it');
      const idle = !w && !d.agent_busy ? apIdleLine(box) : null;
      const shown = w ? `${waitWho} for ${waitSpan(w.seconds)}, longer than usual` : idle;
      const say = w ? `${waitWho} for longer than usual` : d.agent_busy ? 'Working on its next move' : apIdleLine(box, true);
      if (pulse.apSaid !== say) {
        pulse.apSaid = say;
        pulse.innerHTML = w
          ? `<span class="apf-idle-dot" aria-hidden="true"></span><span data-ap-shown aria-hidden="true">${shown}</span><span class="vh">${say}</span>`
          : d.agent_busy
          ? '<span class="working" aria-hidden="true"></span><span>Working on its next move<span class="ell" aria-hidden="true"></span></span>'
          : `<span class="apf-idle-dot" aria-hidden="true"></span><span data-ap-idle data-ap-shown aria-hidden="true">${esc(idle)}</span><span class="vh">${esc(say)}</span>`;
      } else {
        const tick = pulse.querySelector('[data-ap-shown]');
        if (tick && shown != null && tick.textContent !== shown) tick.textContent = shown;
      }
    }
    if (stick) msgs.scrollTop = msgs.scrollHeight; else if (follow === 'keep') msgs.scrollTop = kept[0];
    if (stickSheet) box.scrollTop = box.scrollHeight; else if (follow === 'keep') box.scrollTop = kept[1];
    return true;
  }
  // Idle pulse copy: lead with the autopilot's most recent move (from the status poll, always
  // available even if chat is slow), else a plain "on a schedule" line.
  // `spoken` leaves out how long ago the last move was, for the pulse's live region.
  function apIdleLine(box, spoken) {
    const d = S.ap, la = d && d.last_action;
    const last = la && la.at && !spoken ? `${SEP}last move ` + sinceMin(la.at) : '';
    if (!(d ? d.autopilot : apSwitchOn())) return 'Off: it acts only when you message it' + last;
    // Its status not read (or the read failed): on, and no more. "Idle — reviews run on a schedule" was a guess.
    if (!d) return 'On';
    const now = apNowWord(d);
    return now + last + (now === 'Idle' ? ' — reviews run on a schedule' : '');
  }
  // The pulse's lead: what the status read says it is doing, so it never reads "Idle" over research.
  function apNowWord(d) {
    if (!d) return 'Idle';
    if (d.billing_blocked) return 'Paused until it can pay for research';
    const names = apMarketNames(d), picked = names.filter((n) => n !== AP_PICKING);
    if (names.length) return picked.length ? 'Researching ' + picked.join(SEP) : 'Picking a market to research';
    if (d.reviewing) return 'Reviewing the markets';
    // Between reviews with strategies on paper is not idle: they trade on their own between its moves.
    return d.paper_running ? `Between reviews${SEP}${num(d.paper_running)} on paper` : 'Idle';
  }
  // The open panel is a full-screen sheet under this width (app.css: `.apf.open { inset: 0 }`), which is
  // not phone(): between the two it still sits beside the page.
  const apSheet = () => !!(window.matchMedia && window.matchMedia('(max-width: 600px)').matches);
  const AP_TABBABLE = 'a[href], button, input, select, textarea, summary, [tabindex]';
  function apSheetTab(box, e) {
    // What Tab would actually reach: enabled, in the tab order, and drawn (a folded fieldset or a
    // hidden confirm form has no box).
    const items = [...box.querySelectorAll(AP_TABBABLE)].filter((el) => !el.disabled && el.getAttribute('tabindex') !== '-1'
      && (el.offsetWidth || el.offsetHeight || el === document.activeElement));
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1], a = document.activeElement;
    if (e.shiftKey ? a === first : a === last) { e.preventDefault(); (e.shiftKey ? last : first).focus({ preventScroll: true }); }
  }
  function apBuildShell(box) {
    box.dataset.shell = 'expanded'; box.apPill = '';
    box.setAttribute('role', 'region'); box.setAttribute('aria-label', 'Autopilot');
    // Esc closes the open panel, and focus goes back to the pill. As a full-screen sheet the panel
    // covers the page, so Tab stays inside it instead of walking controls nobody can see.
    box.onkeydown = (e) => {
      if (e.key === 'Escape' && apExpanded()) { e.stopPropagation(); apAction(box, 'toggle'); return; }
      if (e.key === 'Tab' && apSheet() && apExpanded()) apSheetTab(box, e);
    };
    box.innerHTML = `
      <div class="apf-head"><span class="apf-dot" aria-hidden="true"></span><b id="apf-label"></b>
        <button type="button" class="apf-x" data-ap="toggle" aria-label="Collapse autopilot">${ICON.cross || '×'}</button></div>
      <div class="apf-top">
        <div class="autopilot" id="apf-ap">
          <span id="apf-ap-copy"></span>
          <label class="switch"><span class="vh">Autopilot</span><input type="checkbox" id="apf-apswitch"></label>
        </div>
        <dl class="apf-stats" id="apf-stats"></dl>
        <p class="stale-note" id="apf-stale" role="status"></p>
        <div id="apf-last"></div>
        <div id="apf-week"></div>
        <div class="apf-story" id="apf-story" aria-live="polite"></div>
        <p class="ap-focus" id="apf-focusline" hidden></p>
        <details class="apf-prefs"><summary>Model and markets</summary>
          <label class="field apf-model"><span>Autopilot model</span>
            <select class="input" id="apf-model" aria-label="Autopilot model"></select></label>
          <label class="field apf-model"><span>Markets it may trade</span>
            <select class="input" id="apf-focus" aria-label="Markets the autopilot may research and trade"></select></label>
        </details>
        <div class="apf-gates hint" id="apf-gates"></div>
        <div id="apf-flash"></div>
        <div class="apf-controls" id="apf-controls"></div>
        <form id="apf-confirm" hidden>
          <p class="hint">The agent will trade <b>real money</b> on its own, within your caps + loss guard. Type <b>LIVE AUTOPILOT</b>.</p>
          <input class="input" name="confirm" autocomplete="off" aria-label="Type LIVE AUTOPILOT to confirm">
          <button class="btn sm" type="submit">Confirm live autopilot</button>
        </form>
      </div>
      <div class="apf-session">
        <div class="apf-session-head"><span class="say-kind">Activity feed</span><span class="apf-session-sub">everything the autopilot does, end to end</span></div>
        <ol class="log stream apf-log" id="apf-messages" aria-label="Autopilot activity" aria-live="polite"></ol>
        <div class="runpulse apf-pulse-row" id="apf-pulse" aria-live="polite" hidden></div>
      </div>
      <form class="composer apf-composer-row" id="apf-composer">
        <p class="apf-err" id="apf-err" role="alert" hidden></p>
        <label class="vh" for="apf-msg">Message the agent</label>
        <textarea class="input" id="apf-msg" rows="1" maxlength="2000" placeholder="What should it focus on?" aria-label="Message the autopilot" aria-describedby="apf-cost"></textarea>
        <button class="btn" type="submit" aria-label="Send">${ICON.send}</button>
        <p class="apf-cost" id="apf-cost" hidden></p>
      </form>`;
    box.querySelector('.apf-x').onclick = (e) => apAction(box, 'toggle', e);
    box.querySelector('#apf-confirm').onsubmit = (e) => { e.preventDefault(); apEnableLive(box, box.querySelector('#apf-confirm').confirm.value.trim()); };
    const sw = box.querySelector('#apf-apswitch');
    sw.onchange = async () => {
      const on = sw.checked;
      // One flip, like the dashboard card and the empty-page nudges: paper-only and undone by flipping
      // back. Real money keeps its own typed LIVE AUTOPILOT confirm below.
      // The switch locks until Tau answers: two quick flips that both failed left it showing on while
      // autopilot was off. A failure puts it back to the saved state and says why in the panel, next to
      // it (the page under a phone's full-screen panel can't be seen).
      sw.disabled = true; apNote(box, '');
      // Until Tau answers, the 20s status read leaves the switch where it was flipped (apUpdate): it put
      // the switch back to the old state with no word while the write was still out. After 20s the
      // switch says Tau hasn't confirmed yet.
      const waited = waitNote(sw.closest('.switch') || sw);
      S.apSwitching = { on, waited };
      let saved = false;
      // Locking the switch blurs it, so focus goes back to it once it unlocks (the panel is the only
      // thing on screen on a phone, and the page behind it is where focus used to land).
      try { await api('/api/settings', { autopilot: on }).finally(waited); S.me.user.autopilot = on; saved = true; }
      catch (e) { sw.checked = !!(S.me && S.me.user && S.me.user.autopilot); apNote(box, apSaid(e)); }
      finally {
        S.apSwitching = null;
        const now = box.querySelector('#apf-apswitch');
        if (now && now !== sw) { now.checked = sw.checked; now.disabled = false; }
        sw.disabled = false;
        const a = document.activeElement;
        if ((!a || a === document.body) && sw.isConnected && sw.focus) sw.focus({ preventScroll: true });
      }
      if (!saved) return;
      // The switch's new state is said out loud: its label and the copy beside it change silently.
      announce(on ? 'Autopilot is on. It researches and trades on paper by itself.' : 'Autopilot is off. It only suggests ideas for you to approve.');
      // Right after switching on, show where it may trade, so the focus is a choice and not a default nobody saw.
      if (on) { const prefs = box.querySelector('.apf-prefs'); if (prefs) prefs.open = true; }
      if (S.ap) S.ap = Object.assign({}, S.ap, { autopilot: on, mode: !on ? 'off' : S.ap.mode === 'off' ? 'paper' : S.ap.mode });
      paintDashAp();  // copy that follows the switch flips now, not on the next status read
      if (S.ap && box.querySelector('#apf-apswitch') === sw) apUpdate(box, S.ap);  // the panel's own figures too
      refreshAutopilot(box);
    };
    const msgs = box.querySelector('#apf-messages');
    msgs.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-decide]'); if (!b) return;
      const prop = b.closest('[data-prop]'), pid = prop.dataset.prop;
      // One decision per proposal: Approve and Decline both lock while it is sent (a tap on the other
      // one used to send it too), and stay locked once it lands until the repaint shows the stamp.
      if (prop.dataset.deciding) return;
      prop.dataset.deciding = '1';
      const btns = [...prop.querySelectorAll('button')];
      btns.forEach((x) => { x.disabled = true; });
      b.classList.add('busy');
      apErr(box, '');
      try {
        const result = await api(`/api/proposals/${pid}/${b.dataset.decide}`, {});
        if (result.review_required && result.review_url === `/funds?perps_proposal=${pid}`) { go(result.review_url); return; }
        // An approved pause, resume or deploy changes what is running: the figures and the card follow now.
        refreshAutopilot(box);
      } catch (err) {
        apErr(box, err.message);
        btns.forEach((x) => { x.disabled = false; });
        delete prop.dataset.deciding;
      } finally { b.classList.remove('busy'); }
      await apLoadChat(box, true, undefined, 'keep');  // the stamp, or the state it was already decided to
    });
    const cf = box.querySelector('#apf-composer'), ta = box.querySelector('#apf-msg');
    // A message half typed survives a reload (or the panel closing): kept in this browser, per account,
    // until it is sent.
    const keepDraft = (v) => { try { localStorage.setItem(AP_DRAFT(), v); } catch (e) { /* private mode */ } };
    try { ta.value = localStorage.getItem(AP_DRAFT()) || ''; } catch (e) { /* private mode */ }
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px'; keepDraft(ta.value); });
    apCostPaint(box);
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); cf.requestSubmit(); } });
    cf.onsubmit = async (e) => {
      e.preventDefault(); const content = ta.value.trim(); if (!content || cf.dataset.sending) return;
      // Enter submits even while the Send button is disabled, so a second Enter during a slow send
      // sent the message again: one send at a time.
      cf.dataset.sending = '1';
      apErr(box, '');
      try {
        const send = cf.querySelector('button'), waited = waitNote(send);
        await busy(send, async () => { try { await api('/api/chat', { content }).finally(waited); ta.value = ''; ta.style.height = ''; keepDraft(''); await apLoadChat(box, false, undefined, 'end'); } catch (err) { apErr(box, sendUnsure(err) ? CHAT_UNSURE : err.message, err.status === 402); } }, waited);
      } finally { delete cf.dataset.sending; }
    };
    apLoadChat(box, true);
    apStopChat();
    // One read at a time, backing off while they fail: a hung or down server used to get three reads
    // every 3s (each tick plus its retries), stacking while they hung.
    const chatTick = paced((cfg) => {
      const b = document.getElementById('autopilot-float');
      return b && apLoadChat(b, false, cfg).then((ok) => { if (ok === false) throw new Error('Chat read failed'); });
    }, 3000);
    apChatWake = () => chatTick(true);
    apChatTimer = setInterval(() => { const b = document.getElementById('autopilot-float'); if (b && apExpanded()) { if (!document.hidden) chatTick(); } else apStopChat(); }, 3000);
    // Market focus: binding on research, deploys and the paper funnel (server enforces it).
    (() => {
      const sel = box.querySelector('#apf-focus'); if (!sel) return;
      sel.onchange = async () => {
        if (sel.disabled) return;
        const prev = sel.dataset.cur || '';
        sel.disabled = true;
        const current = () => box.isConnected !== false && box.querySelector('#apf-focus') === sel;
        try {
          const r = await api('/api/autopilot/focus', { focus: sel.value ? sel.value.split(',') : [] });
          if (S.ap) S.ap.focus = r.focus;
          if (current()) { apFocusOptions(sel, r.focus); apFocusPaint(box, r.focus); apLoadChat(box); }
          paintDashAp();
        } catch (e) { if (current()) { sel.value = prev; apNote(box, e.message); } }
        finally { if (current()) sel.disabled = false; }
      };
      apFocusOptions(sel, (S.ap && S.ap.focus) || []);
    })();
    // The autopilot's research, review and chat share its saved model preference.
    (async () => {
      const sel = box.querySelector('#apf-model'); if (!sel) return;
      const current = () => box.isConnected !== false && box.querySelector('#apf-model') === sel;
      const mdl = await api('/api/models', undefined, { keep: true }).catch(() => ({ models: [], default: '' }));
      if (!current()) return;
      const cur = (S.ap && S.ap.model) || mdl.default;
      sel.innerHTML = (mdl.models || []).filter((m) => m.available !== false).concat((mdl.models || []).filter((m) => m.available === false))
        .map((m) => `<option value="${esc(m.key)}"${m.key === cur ? ' selected' : ''}${m.available === false ? ' disabled' : ''}>${esc(m.label)}${m.available === false ? ' (coming soon)' : ''}</option>`).join('');
      sel.onchange = async () => {
        if (!current() || sel.disabled) return;
        sel.disabled = true;
        try { const r = await api('/api/autopilot/model', { model: sel.value }); if (current() && S.ap) S.ap.model = r.model; }
        catch (e) { if (current()) { sel.value = (S.ap && S.ap.model) || cur; apNote(box, e.message); } }
        finally { if (current()) sel.disabled = false; }
      };
    })();
  }
  function apFocusOptions(sel, focus) {
    const cur = (focus || []).join(',');
    const opts = AP_FOCUS.some(([v]) => v === cur) ? AP_FOCUS : AP_FOCUS.concat([[cur, 'Only ' + apFocusText(focus)]]);
    sel.innerHTML = opts.map(([v, label]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`).join('');
    sel.dataset.cur = cur;
  }
  // The note after "Furthest on paper"'s net, as its own sentence: it ran on from "+$15.26 net on them" into
  // "instant-fill paper trades left out" with nothing between.
  const PAPER_COUNT_WHY_SAID = PAPER_COUNT_WHY.charAt(0).toUpperCase() + PAPER_COUNT_WHY.slice(1) + '.';
  // The idle line ends with what it is doing right now, the story's own first sentence ("Nothing is on paper
  // yet: ... It's reviewing the markets to pick its next move." over "Right now it's reviewing the markets to
  // pick its next move."): under it, the panel said it twice in a row. Said once, the rest of that line kept.
  function apStoryUnderIdle(d, idleShown) {
    const lines = apStory(d), raw = String(((d && d.story) || [])[0] || '');
    const cut = (s) => { const i = s.indexOf('. '); return i < 0 ? [s.replace(/\.$/, ''), ''] : [s.slice(0, i), s.slice(i + 2)]; };
    const doing = cut(raw)[0].replace(/^Right now /, '');
    if (!idleShown || !lines.length || !doing || !String(d.idle.line || '').includes(doing.charAt(0).toUpperCase() + doing.slice(1))) return lines;
    const rest = cut(lines[0])[1].trim();
    return (rest ? [rest] : []).concat(lines.slice(1));
  }
  function apUpdate(box, d) {
    const on = d ? d.autopilot : (S.me.user && S.me.user.autopilot);
    // Before its status has been read (or when that read failed), the head goes by the saved switch, as the pill
    // does: it said "Autopilot off" over a switch that was on (walk 2026-10-28, status read failing).
    const m = (d && AP_MODE[d.mode]) || (!d && on ? { label: 'Autopilot on', cls: 'paper' } : AP_MODE.off);
    box.className = 'apf open' + (m.cls ? ' ' + m.cls : '');
    const label = box.querySelector('#apf-label'); if (label) label.textContent = m.label;
    const ap = box.querySelector('#apf-ap'); if (ap) ap.classList.toggle('on', !!on);
    // A flip still waiting for Tau keeps the switch where it was flipped, locked, with its note: the
    // status read may have left before the write landed (and the panel may have been built again).
    const sw = box.querySelector('#apf-apswitch'), flip = S.apSwitching;
    if (sw && flip) { sw.checked = flip.on; sw.disabled = true; flip.waited.place(sw.closest('.switch') || sw); }
    else if (sw && document.activeElement !== sw) sw.checked = !!on;
    apCostPaint(box);
    const copy = box.querySelector('#apf-ap-copy');
    if (copy) copy.innerHTML = on
      ? '<b>Autopilot</b>Researches, deploys and tunes paper strategies on its own, and adjusts your risk &amp; execution controls within safe bounds. It never touches live money without the step below.'
      : '<b>Autopilot</b>Off: it only suggests ideas and changes, and you approve each one. Flip the switch to let it research and trade on paper by itself.';
    if (!d) {
      // A status read that failed says so, with Try again, instead of a panel with no figures and nothing said.
      const st = box.querySelector('#apf-story');
      if (st) {
        st.innerHTML = S.apFailing ? '<p class="apf-fail">The autopilot\u2019s status didn\u2019t load, so its figures are left out. The switch shows how you last set it. <button type="button" class="btn sm" data-ap-status-retry>Try again</button></p>' : '';
        const again = st.querySelector('[data-ap-status-retry]');
        if (again) again.onclick = () => { again.disabled = true; refreshAutopilot(box); };
      }
      return;
    }
    // Plain-language summary from the server (what it's doing, why no trades yet, what live needs).
    const story = box.querySelector('#apf-story');
    if (story) {
      // The billing pause has its own line under the switch, so the idle line skips it.
      const idleShown = !!(d.idle && !d.billing_blocked);
      story.innerHTML = (idleShown ? `<p class="apf-idle">${apIdleHtml(d.idle, 'data-ap="idle-focus"', d)}</p>` : '')
        + apStoryUnderIdle(d, idleShown).map((line) => `<p>${esc(line)}</p>`).join('');
      const idleFocus = story.querySelector('[data-ap="idle-focus"]');
      if (idleFocus) idleFocus.onclick = () => apShowFocus(box);
    }
    // Live figures once real money is armed or running. A paper-only panel used to show "Live P&L
    // today $0.00" and a loss budget that can't apply to it, and nothing about the paper book it has.
    const liveInPlay = !!(d.autopilot_live || d.live_running);
    const pnl = (liveInPlay ? d.today_live_pnl : d.today_paper_pnl) || 0;
    // The live loss budget stops live trading; while live trading is closed nothing live trades, so it isn't shown
    // (a live position still settling counts in Live realized today).
    const budgetShown = liveInPlay && liveOpen();
    const stats = box.querySelector('#apf-stats');
    // Count running strategies across every mode, not just paper — a lone demo strategy
    // used to read as "0 paper", which looked like nothing was running. Match the dashboard.
    // A live one while live trading is closed places no orders, and says so, as Deploy's Money figure does.
    const runParts = [
      d.live_running ? (liveOpen() ? `<span class="apf-live">${d.live_running} live</span>` : liveIdleShort(d.live_running)) : '',
      d.demo_running ? `${num(d.demo_running)}\u00a0demo` : '',
      d.paper_running ? `${num(d.paper_running)}\u00a0paper` : '',
    ].filter(Boolean);
    const runTotal = (d.live_running || 0) + (d.demo_running || 0) + (d.paper_running || 0);
    // The figures sit above the story so "is it making money?" reads first, and the Research row only
    // shows when there's no story (billing pause), since the story already says what research did.
    // Short figures share a row (as many columns as there are figures, two on a phone, the odd
    // one out spanning); the sentence-length ones get full-width rows, so no cell sits empty.
    const short = [
      `<dt>Running</dt><dd>${runTotal ? runParts.join(SEP) : 'None'}</dd>`,
      // With nothing on paper and nothing realized today, there is no day's P&L to show: "$0.00" read as a result.
      // The figure says which money it is and that fees are in, as the dashboard card and Deploy say it.
      `<dt>${liveInPlay ? 'Live' : 'Paper'} realized today (UTC)</dt><dd class="${pnl < 0 ? 'neg' : (pnl > 0 ? 'pos' : '')}">${!liveInPlay && !pnl && !+d.paper_running ? 'Nothing on paper' : `${usd(pnl, true)} <small class="apf-note">${liveInPlay ? 'real money, after Kalshi fees' : 'paper, ' + PAPER_NET}</small>${liveInPlay ? '' : slipEst(d.today_paper_slippage_estimate)}`}</dd>`,
    ].concat(budgetShown ? [`<dt>Loss budget left</dt><dd>${usd(d.loss_headroom)} / ${usd(d.daily_loss_limit)}</dd>`] : [])
      // A queued or running review is not a finished one: right after switching on, "Last reviewed just now" claimed a review that hadn't run.
      // Named as on the dashboard's autopilot card ("Last check-in"): the panel said "Last reviewed" beside it.
      // Check-ins are the autopilot's own: with it off (or a flip to off still saving) the figure goes, as the switch
      // says. Right after turning it off the panel kept "Last check-in 37m ago" under "Off: it only suggests ideas".
      .concat(!(flip ? flip.on : on) ? [] : d.review_wait ? [`<dt>Check-in</dt><dd>${d.review_wait.state === 'queued' ? 'Waiting' : 'Silent'} ${waitSpan(d.review_wait.seconds)}</dd>`]
        : d.reviewing ? ['<dt>Last check-in</dt><dd>Reviewing now</dd>'] : d.last_review_at ? [`<dt>Last check-in</dt><dd>${sinceMin(d.last_review_at)}${apEvery(d, 'apf-note')}</dd>`] : []);
    if (stats) {
      stats.dataset.cols = short.length;
      stats.innerHTML = short.map((c, i) => `<div${short.length % 2 && i === short.length - 1 ? ' class="apf-tail"' : ''}>${c}</div>`).join('') + `
      ${budgetShown ? `<div class="apf-wide apf-budget"><dt>Loss budget</dt><dd>Counts live losses booked since 00:00 UTC. Live also stops if your Kalshi account falls ${usd(d.daily_loss_limit)} in a day, open positions included.</dd></div>` : ''}
      ${d.research && !(d.story || []).length ? `<div class="apf-wide"><dt>Research</dt><dd>${d.research.active.length ? 'Researching ' + esc(apMarketNames(d).join(SEP)) : 'Not researching right now'}${SEP}${Number(d.research.tested_7d).toLocaleString('en-US')} ideas tested this week, ${d.research.passed_7d} passed${+d.research.not_cleared_7d ? `, ${Number(d.research.not_cleared_7d).toLocaleString('en-US')} not cleared` : ''}${+d.research.cost_7d >= 0.005 ? ', ' + usd(d.research.cost_7d) + ' spent' : (+d.research.cost_7d > 0 || d.research.cost_7d_under_cent) ? ', under $0.01 spent' : ''}</dd></div>` : ''}
      ${d.paper_progress ? `<div class="apf-wide"><dt>Furthest on paper</dt><dd><a href="/strategies/${d.paper_progress.strategy_id}">${esc(d.paper_progress.title || 'Paper strategy')}</a>${SEP}${paperCount(d.paper_progress)}${SEP}${usd(d.paper_progress.net_pnl, true)} net on them. <small>${gl(PAPER_COUNT_WHY_SAID, 'instantfill')}</small></dd></div>` : ''}`;
    }
    const staleEl = box.querySelector('#apf-stale'); if (staleEl) staleEl.textContent = apStale();
    // The feed's idle pulse reads the status too; repaint it now rather than on the next chat poll.
    // The shown line takes the new minutes; the spoken one changes only with the status.
    const idleEl = box.querySelector('[data-ap-idle]'), idleLine = idleEl && apIdleLine(box);
    if (idleEl && idleEl.textContent !== idleLine) idleEl.textContent = idleLine;
    const pulseEl = idleEl && box.querySelector('#apf-pulse'), idleSay = pulseEl && apIdleLine(box, true), sayEl = pulseEl && pulseEl.querySelector('.vh');
    if (sayEl && pulseEl.apSaid !== idleSay) { pulseEl.apSaid = idleSay; sayEl.textContent = idleSay; }
    const lastEl = box.querySelector('#apf-last'); if (lastEl) lastEl.innerHTML = d.autopilot ? apLastHtml(d.last_action) : '';
    const week = box.querySelector('#apf-week'); if (week) week.innerHTML = d.autopilot ? apWeek(d.week, d) : '';
    const msel = box.querySelector('#apf-model'); if (msel && msel.options.length && d.model && document.activeElement !== msel && !msel.disabled) msel.value = d.model;
    if (Array.isArray(d.focus)) apFocusPaint(box, d.focus);
    const fsel = box.querySelector('#apf-focus');
    if (fsel && Array.isArray(d.focus) && document.activeElement !== fsel && !fsel.disabled && fsel.dataset.cur !== d.focus.join(',')) apFocusOptions(fsel, d.focus);
    const gates = box.querySelector('#apf-gates');
    if (gates) {
      if (d.billing_blocked) {
        // Autopilot is on but can't spend — tell the user WHY it's quiet (so it doesn't look broken).
        gates.innerHTML = d.billing_reason === 'card'
          ? 'Autopilot is paused — <a href="/billing">add a payment method</a> to let it run.' + apStillTrading(d)
          : apReloadFailed(d) ? `Autopilot is paused: ${AP_CARD_FIX}${apStillTrading(d)}`
          : `Autopilot is paused: ${apFloorText()} <a href="/billing">Add credits</a> and it picks up on its own.${apStillTrading(d)}`;
        gates.classList.add('warn');
      } else if (d.credits_low_days != null) {
        gates.innerHTML = `${pausesIn(d.credits_low_days)} <a href="/billing">Add credits or turn on auto-reload</a>.`;
        gates.classList.add('warn');
      } else {
        // The gate's "the Funds page" is a link (apLiveBlockHtml); the armed note stays plain words.
        gates.innerHTML = apLiveBlock(d) ? apLiveBlockHtml(d) : esc(apLiveArmed(d));
        gates.classList.remove('warn');
      }
    }
    const controls = box.querySelector('#apf-controls');
    if (controls) {
      // A paper-only user sees no red Kill and no greyed live button: Kill appears once real money
      // is armed or running, and the live step once autopilot is on (the gate line says why not yet).
      controls.innerHTML = `${d.autopilot_live
        ? `<button class="btn sm" data-ap="livetoggle" data-on="0">Turn off live</button>`
        : d.autopilot && d.live_enabled ? `<button class="btn sm" data-ap="livearm" ${d.kalshi_connected ? '' : 'aria-disabled="true"'}>Enable live autopilot</button>` : ''}
        ${d.autopilot_live || d.live_running ? '<button class="btn sm danger" data-ap="kill">Kill</button>' : ''}
        <a class="btn sm ghost" href="/deploy">See what’s trading</a>`;
      controls.querySelectorAll('[data-ap]').forEach((b) => (b.onclick = (e) => apAction(box, b.dataset.ap, e)));
    }
  }
  // Live armed with nothing live yet reads as "is it trading real money?", so say it outright.
  const apLiveArmed = (d) => d.autopilot_live && !d.live_running ? 'Live autopilot is armed. No strategy is trading real money yet.' : '';
  // A setting in the panel (the switch, model, markets) that didn't save says why in the panel, read out
  // at once; '' clears it before the next try.
  function apNote(box, msg) {
    const f = box.querySelector('#apf-flash');
    if (!f) { if (msg) alert0(msg); return; }
    f.innerHTML = msg ? `<p class="error-text">${esc(msg)}</p>` : '';
    if (msg) announce(msg, true);
  }
  async function apEnableLive(box, confirm) {
    try { await api('/api/autopilot/live', { on: true, confirm }); apFlash(box, 'Live autopilot is on.'); }
    catch (err) { return apFlash(box, err.message, 'bad'); }
    refreshAutopilot(box);
  }

  return {apBuildShell, apStopChat, apUpdate};
});
