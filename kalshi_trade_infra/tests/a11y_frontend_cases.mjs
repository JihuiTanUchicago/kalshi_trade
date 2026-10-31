// Shared cases, run against each bundle's offline harness (Tau and Meridian), from an accessibility pass
// (axe-core plus a live-region watch in Playwright, both themes, 390px and 1280px, 2026-10-27):
// - The autopilot panel's pulse is a polite live region. Each chat poll (3s) rewrote it with the same
//   words, so a screen reader said "Between reviews · 2 on paper" again and again: only a change is written.
// - The research session's foot counted "Researching · 12s" up every second inside a live region, so a
//   screen reader read every tick: the count is not live, and a change of state is said once.
// - A figure's sub-line ("paper money, not real") is a <dd> of its term, not a bare <div> inside the <dl>
//   that a screen reader skipped, so the kind of money is read with the figure.
// - The research and autopilot logs are lists that announce additions (aria-live), not role="log" on
//   the <ol>, which took away the list and its items.
// - Every signed-in page's h1 and money figures sat in #boardbody, outside <main>, so Skip to content and
//   the focus a page change hands over both landed past the heading. <main> holds the board and the page
//   (#main), and both land on the h1.
// - Asides with no name: Tau's Dashboard (positions) and the strategy page (deploy and gates) were two
//   unnamed complementary landmarks beside an unnamed hot-markets rail. Every <aside> is named.
// - Heading levels that skipped: Funds' panels and Tau's research form were h3 under the page's h1, the
//   track record's figure titles h5 under its h2, and Meridian's "Since deploying" h3 under the h1.
// - The pulse's idle line ends "last move 3m ago", and the chat poll rewrote it each minute, so the live
//   region said the whole line again once a minute. The minutes tick in a shown line hidden from the
//   reader; the live words leave them out and change only with the status.
// A second pass (axe-core 4.11 in Playwright, both themes, 390px and 1280px, every signed-in page plus the
// autopilot panel and the bell open, 2026-10-30):
// - Explore's last column (the "Open on Kalshi" links) had an empty <th> named only by aria-label, which a
//   screen reader's table navigation skips (axe empty-table-header): it holds visually hidden text.
// - With the panel open on the Dashboard, the panel's region and the Dashboard's autopilot card were both
//   "Autopilot" (axe landmark-unique): the panel is "Autopilot panel".
// - What if…'s dials were read as bare numbers ("5", "0", "1") where the page shows "$5", "0.0¢" and "1.0×":
//   each dial says its value with its unit (aria-valuetext), and again as it moves.
// - Meridian's "React" button was named "Add a reaction", so a speech user saying "click React" missed it
//   (axe label-content-name-mismatch): the word it shows is its name, its title the description.
//
// From a walk of seeded states (a paying account, a demo deployment, live trading off; both themes, 390px and
// 1280px, 2026-10-30):
// - The phone's full-screen autopilot sheet kept Tab inside it, but a screen reader's swipe walked on into the page
//   hidden under it. The page beside the sheet is inert while it is up, and handed back when it closes. A page
//   change from inside the sheet left focus on the pill, so the new page's heading never took it.
// - Billing's card table had an empty column header (the Remove column), and its Payment method and Add
//   credits panels were h3 under the page's h1. Turning auto-reload off with Space locked the switch while it
//   saved, which dropped focus to the top of the page.
// - A strategy page's Deploy with live money, unavailable while live trading is closed, was a dimmed button
//   with its reason in the line under it and nothing tying the two: a screen reader heard the button, not why.
//   Meridian's undeployed strategy page skipped from the h1 to the research sections' h3s.
//
// From a keyboard-only and screen-reader walk of the main flows (Tab, Shift+Tab, Enter, Space, Escape; ARIA snapshots
// and axe-core 4.14; both themes, 390px and 1280px, a seeded account, 2026-10-30):
// - Focus fell to <body> after a Strategies filter chip (the list is drawn again, the chip with it), after Enter on an
//   Explore row and after Back (a market's page is the same path, /explore?m=, so it wasn't a "page change"), after
//   "Show older sessions" and after the last "Show older entries" (each button went away with nothing to land on).
// - "Show older entries" and a typed Explore search changed the page in silence; Meridian's session page said nothing
//   on Pause or Resume.
// - Every Strategies pick box was "Select for deployment"; Billing's auto-reload amounts were bare spin buttons, and
//   the button that opens them read "Reload $25 at $8" as if it charged the card. A plain checkbox showed no focus.
// - The open autopilot panel's story, a live region, was written again with the same words on each status read.
// - A session's spinner carried aria-label="in process" on a <span>, a name nothing reads (axe aria-prohibited-attr).
//
// From a keyboard and screen-reader pass over known leftovers (axe-core 4.14 in Playwright; both themes, 390px and 1280px,
// 2026-10-31):
// - The Strategies list's Select all sat in the table header a phone's stacked rows clip to nothing: Tab reached it
//   there, a tap couldn't. Up to 760px it is a labelled box of its own over the rows, doing the same thing.
// - After the dashboard autopilot card's Try again, focus went to its first heading, "Last 7 days", halfway down it.
// - Meridian's Explore links were named "event · source condition · market · close" over rows that show
//   "event ≥ $113,000 …" (axe label-content-name-mismatch); its dashboard positions read market, strategy, book over a
//   row that shows market then book, the words run together.
import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));

// Each heading's level against the one before it, in document order: a step down of more than one
// (h1 then h3) is a skip a screen reader's heading list shows as a missing level.
const headingSkips = (host) => {
  const levels = host.querySelectorAll('h1, h2, h3, h4, h5, h6').map((h) => [+h.tag.slice(1), h.textContent.trim()]);
  return levels.filter(([level], i) => level > (i ? levels[i - 1][0] : 0) + 1).map(([level, text]) => `h${level} ${text}`);
};

// Every `@media (max-width: 760px)` block of a stylesheet, joined (the phone's stacked tables).
const phoneRules = (css) => {
  const out = [];
  for (let at = css.indexOf('@media (max-width: 760px) {'); at >= 0; at = css.indexOf('@media (max-width: 760px) {', at + 1)) {
    let depth = 0, i = css.indexOf('{', at);
    for (; i < css.length; i++) { if (css[i] === '{') depth++; else if (css[i] === '}' && !--depth) break; }
    out.push(css.slice(at, i + 1));
  }
  return out.join('\n');
};

export function a11yCases({name, frontend, storageFor, billingPage, cardedBilling, source, strategyFrontend, detailStrategy, dashboard, fundsData, apStatus}) {
  test(`${name}: <main> starts at the page's heading and figures, and a page change and Skip to content land there`, async () => {
    const f = frontend({fetchImpl: (path) => path === '/api/deployments' ? response({deployments: [], open_positions: []}) : response({})});
    f.location.pathname = '/deploy';
    await f.render(); await flush(); await flush();
    const mains = f.root.querySelectorAll('main');
    assert.equal(mains.length, 1, 'one main landmark, with none inside it');
    assert.ok(mains[0].querySelector('#boardbody h1'), 'the page heading is in <main>');
    assert.ok(mains[0].querySelector('#boardbody') && mains[0].querySelector('#main'), 'so are the board and the page under it');
    assert.equal(mains[0].querySelector('h1').focusOptions, undefined, 'the first page of a visit leaves focus to the browser');
    f.location.pathname = '/settings';
    await f.render(); await flush(); await flush();
    const heading = f.root.querySelector('main h1'), page = f.root.querySelector('#main');
    assert.equal(heading.textContent, 'Settings');
    assert.equal(heading.getAttribute('tabindex'), '-1');
    assert.equal(heading.focusOptions.preventScroll, true, 'a page change focuses the heading');
    assert.equal(page.focusOptions, undefined, 'not the page under the figures');
    // Skip to content (the shell's first link) goes to the same heading.
    heading.focusOptions = undefined; heading.scrollIntoView = () => { heading.scrolled = true; };
    heading.hasAttribute = (key) => heading.getAttribute(key) != null;
    const skip = f.document.createElement('a'); skip.className = 'skip'; skip.setAttribute('href', '#main'); f.document.body.appendChild(skip);
    let prevented = false;
    for (const [type, listener] of f.documentListeners) if (type === 'click') listener({target: skip, preventDefault: () => { prevented = true; }});
    assert.equal(prevented, true);
    assert.equal(heading.scrolled, true); assert.equal(heading.focusOptions.preventScroll, true);
    assert.equal(page.focusOptions, undefined);
    f.clearTimers();
  });

  // Walk 2026-10-31: the profile button said aria-haspopup="true" (a menu of menuitems, with arrow keys) over a plain
  // list of links, and named nothing it opened; the bell had already become a disclosure. On Meridian, Funds, Billing,
  // Settings, Dev Logs and System have no section tab, so nothing said which of them was showing, and its menu had no
  // way to Terms or Privacy at all.
  test(`${name}: the profile menu is a disclosure that names its list, marks the page showing, and reaches Terms and Privacy`, async () => {
    const f = frontend({fetchImpl: () => response({})});
    f.location.pathname = '/settings';
    await f.viewSettings();
    const trig = f.root.querySelector('.profile-trig'), menu = f.root.querySelector('.profile-menu');
    assert.equal(trig.getAttribute('aria-haspopup'), null);
    assert.equal(trig.getAttribute('aria-controls'), 'profile-menu'); assert.equal(menu.getAttribute('id'), 'profile-menu');
    assert.equal(trig.getAttribute('aria-expanded'), 'false');
    const links = menu.querySelectorAll('a');
    const current = links.filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.getAttribute('href'));
    assert.deepEqual(current, ['/settings']);
    for (const href of ['/terms', '/privacy']) assert.equal(links.filter((a) => a.getAttribute('href') === href).length, 1, href);
    // Meridian has no Terms or Privacy page of its own: boot.js serves them in Tau, so the links load afresh.
    if (name === 'Meridian') for (const a of links.filter((x) => /^\/(?:terms|privacy)$/.test(x.getAttribute('href')))) assert.ok(a.hasAttribute('data-native'), a.getAttribute('href'));
    f.clearTimers();
    // A page the menu doesn't hold marks none of its links (its section tab says where the reader is).
    const d = frontend({fetchImpl: (path) => path === '/api/deployments' ? response({deployments: [], open_positions: []}) : response({})});
    d.location.pathname = '/deploy';
    await d.render(); await flush(); await flush();
    assert.equal(d.root.querySelectorAll('.profile-menu a[aria-current="page"]').length, 0);
    d.clearTimers();
  });

  test(`${name}: every <aside> has a name of its own, on Dashboard and the strategy page as everywhere`, async () => {
    const names = (f) => f.root.querySelectorAll('aside').map((a) => a.getAttribute('aria-label'));
    const d = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response(dashboard()) : response({})});
    await d.viewDashboard(); await flush();
    const s = strategyFrontend(undefined, () => response({}));
    await s.viewStrategy(42); await flush();
    for (const f of [d, s]) {
      for (const label of names(f)) assert.ok(label && label.trim(), 'a named aside');
      assert.equal(new Set(names(f)).size, names(f).length, 'no two with the same name');
    }
    const own = (f) => names(f).filter((n) => n !== 'Hot markets');  // Meridian's shell draws the rail
    assert.deepEqual(own(d), name === 'Tau' ? ['Positions'] : []);
    assert.deepEqual(own(s), ['Deploy and gates']);
    d.clearTimers(); s.clearTimers();
    // Every aside the bundle draws, the hot-markets rail it makes in script included, carries its name.
    assert.deepEqual(source.match(/<aside(?![^>]*aria-label=)[^>]*>/g), null);
    assert.deepEqual(source.match(/createElement\('aside'\)(?![^;]*;[^;]*;[^;]*; a\.setAttribute\('aria-label')/g), null);
  });

  test(`${name}: Explore's empty states and the System page skip no heading level, and System's scrolling feed takes focus by name`, async () => {
    // Explore's empty and failed states were h3 under the page's h1.
    for (const [answer, words] of [[response({markets: [], total: 0, shown: 0, matched: 0, at: new Date().toISOString()}), 'No markets to show yet'],
      [response({error: 'Explore is busy.'}, 500), 'Markets didn’t load']]) {
      const explore = frontend({fetchImpl: (path) => path.startsWith('/api/explore?') ? answer : response({})});
      explore.location.pathname = '/explore'; explore.location.search = '';
      await explore.viewExplore(); for (let i = 0; i < 6; i++) await flush();
      assert.equal(explore.root.querySelector('#xbody h2').textContent, words);
      assert.deepEqual(headingSkips(explore.root), []);
      // A list that failed is said aloud (failure walk 2026-10-31): the heading alone was silent.
      if (answer.status === 500) {
        [...explore.timeouts.values()].forEach((run) => run()); explore.timeouts.clear();
        assert.equal(explore.document.getElementById('sr-alert').textContent, 'Markets didn’t load. Explore is busy.');
      }
      explore.clearTimers();
    }
    // A System map whose read keeps failing says so once, with Try again, and its 4s poll backs off (failure walk
    // 2026-10-31): the same error went into the assertive live region on every tick, and the poll never slowed.
    const down = frontend({fetchImpl: (path) => path === '/api/admin/system' ? response({error: 'System status is busy.'}, 500) : response({})});
    await down.viewSystem(); await flush();
    assert.match(down.root.querySelector('#sys-error').textContent, /System status is busy\./);
    assert.ok(down.root.querySelector('#sys-error [data-retry]'), 'Try again on a map that never loaded');
    const alerts = down.document.getElementById('sr-alert');
    let heard = 0;
    for (let i = 0; i < 8; i++) {
      for (const tick of [...down.intervals.values()]) tick();
      for (let k = 0; k < 4; k++) await flush();
      [...down.timeouts.values()].forEach((run) => run()); down.timeouts.clear();
      if (alerts && alerts.textContent) { heard++; alerts.textContent = ''; }
    }
    assert.equal(heard, 0, 'the same failure is not said again on every poll');
    const asks = down.requests.filter((r) => r.path === '/api/admin/system').length;
    assert.ok(asks <= 5, `the failing poll backs off (asked ${asks} times in 8 ticks)`);
    down.clearTimers();
    // System's detail panel ("Pick a box" / "Select a component", then the box opened) was h3 under the h1.
    const sys = frontend({fetchImpl: (path) => path === '/api/admin/system' ? response({nodes: {}, events: [], now: '2026-10-20T16:00:00Z'}) : response({})});
    await sys.viewSystem(); await flush();
    assert.ok(sys.root.querySelector('#sys-detail h2'));
    assert.deepEqual(headingSkips(sys.root), []);
    assert.match(source, /detail\.innerHTML = `<h2>\$\{esc\(n\.label\)\}<\/h2>/);
    assert.doesNotMatch(source, /detail\.innerHTML = `<h3>/);
    // The live feed scrolls on its own (axe scrollable-region-focusable): Tab reaches it, and it has a name.
    const feed = sys.root.querySelector('#sys-feed');
    assert.equal(feed.getAttribute('tabindex'), '0');
    assert.equal(feed.getAttribute('aria-label'), 'Live activity');
    sys.clearTimers();
  });

  test(`${name}: Funds, the research form, the track record and a deployed strategy's page skip no heading level`, async () => {
    const funds = frontend({fetchImpl: (path) => path === '/api/funds' ? response(fundsData()) : response({})});
    await funds.viewFunds(); await flush();
    assert.ok(funds.root.querySelector('#main h2'), 'Funds has its section headings');
    assert.deepEqual(headingSkips(funds.root), []);
    const research = frontend({fetchImpl: (path) => {
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null, v: 'v1'});
      return response({});
    }});
    research.S.me.user.autopilot = false; research.location.pathname = '/research';
    await research.viewResearch(); for (let i = 0; i < 6; i++) await flush();
    assert.ok(research.root.querySelector('#dispatch'), 'the research form is on the page');
    assert.deepEqual(headingSkips(research.root), []);
    research.clearTimers();
    // The track record mounts under its own h2 (dashTrackRecord); its figure titles come next.
    const record = frontend({fetchImpl: () => response({})}), host = record.document.createElement('section');
    host.innerHTML = '<h1>Dashboard</h1><h2>Track record</h2>' + record.trackRecordPanel({trades: 3, wins: 2, losses: 1, label: 'Paper', net_pnl: 4, fees: 0.2,
      monthly: [], strategies: [], curve: [], sample: {level: 'thin', edge: 'unclear', text: 'Too early to judge.'}}, 'paper', {min_sharpe_days: 14, min_trades: 30});
    assert.ok(host.querySelectorAll('h3').some((h) => h.textContent === 'Equity curve'));
    assert.deepEqual(headingSkips(host), []);
    const deployments = [{id: 1, mode: 'paper', status: 'running', realized_pnl: 2.5, closed_trades: 4, open_positions: 1, created_at: '2026-10-20T08:00:00Z'}];
    const deployed = strategyFrontend(detailStrategy({deployments}), () => response({}));
    await deployed.viewStrategy(42); await flush();
    assert.match(deployed.root.querySelector('#main').innerHTML, /Since deploying/);
    assert.deepEqual(headingSkips(deployed.root), []);
    deployed.clearTimers();
  });

  test(`${name}: the autopilot pulse is written only when its words change, not on every chat poll`, async () => {
    let chat = {messages: [], agent_busy: false};
    const store = new Map([['tau_ap_open', '1']]);
    const f = frontend({storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/chat?')) return response(chat);
      if (path === '/api/models') return response({models: [], default: ''});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7, autopilot: true}};
    f.S.ap = {...f.S.ap, autopilot: true, mode: 'paper', paper_running: 2};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null); await flush(); await flush();
    const pulse = box.querySelector('#apf-pulse');
    assert.equal(pulse.getAttribute('aria-live'), 'polite');
    assert.match(pulse.innerHTML, /Between reviews · 2 on paper/);
    const writes = pulse.writes;
    for (let i = 0; i < 4; i++) { await f.apLoadChat(box, false); await flush(); }
    assert.equal(pulse.writes, writes, 'a poll with the same words left the live region alone');
    // The status read (every 20s) with the same line leaves it alone too.
    f.apUpdate(box, {...f.S.ap});
    assert.equal(pulse.writes, writes);
    // A real change is written, once.
    chat = {messages: [], agent_busy: true};
    await f.apLoadChat(box, false); await f.apLoadChat(box, false); await flush();
    assert.equal(pulse.writes, writes + 1);
    assert.match(pulse.innerHTML, /Working on its next move/);
    chat = {messages: [], agent_busy: false};
    await f.apLoadChat(box, false); await flush();
    assert.equal(pulse.writes, writes + 2);
    assert.match(pulse.innerHTML, /Between reviews/);
  });

  test(`${name}: the pulse's minutes tick on screen without being said again; a status change is said once`, async () => {
    let chat = {messages: [], agent_busy: false};
    const store = new Map([['tau_ap_open', '1']]);
    const f = frontend({storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/chat?')) return response(chat);
      if (path === '/api/models') return response({models: [], default: ''});
      throw new Error('Unexpected offline request: ' + path);
    }});
    const at = new Date(Date.now() - 3 * 60000).toISOString();
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7, autopilot: true}};
    f.S.ap = {...f.S.ap, autopilot: true, mode: 'paper', paper_running: 2, last_action: {at, text: 'Autopilot is ON: …'}};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null); await flush(); await flush();
    const pulse = box.querySelector('#apf-pulse');
    const shown = () => pulse.querySelector('[data-ap-shown]').textContent, said = () => pulse.querySelector('.vh').textContent;
    assert.equal(pulse.getAttribute('aria-live'), 'polite');
    assert.equal(pulse.querySelector('[data-ap-shown]').getAttribute('aria-hidden'), 'true');
    assert.match(shown(), /^Between reviews\u00a0· 2 on paper\u00a0· last move 3m ago/);
    assert.equal(said(), 'Between reviews\u00a0· 2 on paper');
    const writes = pulse.writes;
    // A minute on, from the chat poll and then from the status read: the shown line counts, nothing is said.
    f.shiftClock(60000); await f.apLoadChat(box, false); await flush();
    assert.match(shown(), /last move 4m ago/); assert.equal(said(), 'Between reviews\u00a0· 2 on paper'); assert.equal(pulse.writes, writes);
    f.shiftClock(60000); f.apUpdate(box, {...f.S.ap});
    assert.match(shown(), /last move 5m ago/); assert.equal(said(), 'Between reviews\u00a0· 2 on paper'); assert.equal(pulse.writes, writes);
    // A real change of status is written, once.
    f.S.ap = {...f.S.ap, paper_running: 3}; await f.apLoadChat(box, false); await f.apLoadChat(box, false); await flush();
    assert.equal(pulse.writes, writes + 1); assert.equal(said(), 'Between reviews\u00a0· 3 on paper');
    // A long wait counts its minutes on screen too, said once.
    chat = {messages: [], agent_busy: true, agent_wait: {state: 'running', seconds: 400}};
    await f.apLoadChat(box, false); await flush();
    assert.equal(pulse.writes, writes + 2); assert.equal(said(), 'No word from it for longer than usual');
    const waited = shown();
    chat = {...chat, agent_wait: {state: 'running', seconds: 700}};
    await f.apLoadChat(box, false); await flush();
    assert.notEqual(shown(), waited); assert.match(shown(), /^No word from it for .+, longer than usual$/); assert.equal(pulse.writes, writes + 2);
  });

  test(`${name}: a research session's seconds count is not read out each second; a change of state is said once`, async () => {
    const f = frontend();
    const section = f.document.createElement('section');
    section.innerHTML = '<ol class="log"></ol><button class="jumplatest"></button><div class="runpulse"></div>';
    f.document.body.appendChild(section);
    const stream = f.runFeed(section), pulse = section.querySelector('.runpulse');
    const said = () => { f.elapse(50); const el = f.document.getElementById('sr-status'); return el ? el.textContent : ''; };
    stream.state('queued', {state: 'queued', seconds: 200, overdue: false});
    for (const tick of [...f.intervals.values()]) tick();
    const label = pulse.querySelector('[data-plabel]');
    if (label) assert.match(label.textContent, /^Queued · 20\ds$/);  // Tau counts the wait in the foot
    assert.equal(said(), '', 'the first paint and the ticks say nothing');
    // Meridian has no foot, and nothing above it was a live region: a press of Pause or Resume said nothing (walk
    // 2026-10-30). Both say a change of state once, in the same words.
    stream.state('running');
    assert.equal(said(), 'Researching');
    for (const tick of [...f.intervals.values()]) tick();
    stream.state('running');
    assert.equal(said(), 'Researching', 'the same state again is not said again');
    stream.state('paused');
    assert.equal(said(), 'Paused — resume and it picks up exactly where it left off.');
    stream.state('running');
    assert.equal(said(), 'Researching', 'and Resume');
    f.clearTimers();
    // On the page, the foot that ticks is not itself a live region, and neither is the log: a list, which read every
    // streamed line, each piece of a thought and each second of its clock (walk 2026-10-31).
    const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
    const g = frontend({fetchImpl: (path) => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: []}); }});
    await g.viewRun(9);
    const foot = g.root.querySelector('#runpulse');
    if (foot) assert.equal(foot.getAttribute('aria-live'), null);
    const log = g.root.querySelector('#log');
    assert.equal(log.tag, 'ol'); assert.equal(log.getAttribute('role'), null); assert.equal(log.getAttribute('aria-live'), null);
    g.clearTimers();
  });

  // Walk 2026-10-31: with the log a live region, a screen reader read ~100 lines a minute on a live session. What a
  // listener waits for is said instead: a poll's idea verdicts once (the newest by name), and the end of the session.
  test(`${name}: a live session says each poll's verdicts once and its end once, never its streamed lines`, async () => {
    const AT = '2026-10-17T10:00:00Z';
    const ev = (id, kind, message, data = {}) => ({id, kind, message, data, created_at: AT});
    let status = 'running', next = [];
    const f = frontend({fetchImpl: (path) => {
      if (!path.startsWith('/api/runs/9')) return response({});
      const out = next; next = [];
      return response({run: {id: 9, prompt: 'Idea', status, market: 'btc15m', created_at: AT, started_at: AT, run_forever: 1,
        stop_reason: status === 'cancelled' ? 'user' : null}, events: out, strategies: []});
    }});
    next = [ev(1, 'hypothesis', 'Old idea'), ev(2, 'verdict', 'DROPPED "Old idea" (no candidate) — lost money', {title: 'Old idea', status: 'abandoned'})];
    await f.viewRun(9); await flush();
    const said = () => { f.elapse(50); const el = f.document.getElementById('sr-status'); return el ? el.textContent : ''; };
    assert.equal(said(), '', 'the first paint says nothing');
    const tick = f.intervals.get(f.S.timers.at(-1)), poll = () => tick();  // the 2s poll, before a thought adds its clock
    next = [ev(3, 'thinking', 'Takers chase the move ', {block: 1}), ev(4, 'thinking', 'late in the window.', {block: 1})];
    poll(); await flush(); await flush();
    assert.equal(said(), '', 'a streamed thought is not read out');
    next = [ev(5, 'hypothesis', 'Late fade'), ev(6, 'verdict', 'REJECTED - Late fade: not a finalist', {title: 'Late fade', status: 'rejected'})];
    poll(); await flush(); await flush();
    assert.equal(said(), 'Late fade: rejected.');
    next = [ev(7, 'verdict', 'DROPPED "A" (no candidate) — x', {title: 'A', status: 'abandoned'}),
      ev(8, 'verdict', 'PASSED - B: passed', {title: 'B', status: 'passed', strategy_id: 4}),
      ev(9, 'verdict', 'B: one-time holdout', {title: 'B', phase: 'holdout', classification: 'forward_validated'})];
    poll(); await flush(); await flush();
    assert.equal(said(), '2 ideas checked. Latest: B: passed its first test on unseen data.', 'a later check is not counted');
    status = 'cancelled';
    poll(); await flush(); await flush();
    assert.equal(said(), 'This session has ended: Stopped by you.');
    f.clearTimers();
    // A finished session opened later says nothing of its end.
    status = 'succeeded'; next = [];
    const g = frontend({fetchImpl: (path) => response(path.startsWith('/api/runs/9') ? {run: {id: 9, prompt: 'Idea', status: 'succeeded',
      stop_reason: 'limit', market: 'btc15m', created_at: AT, started_at: AT}, events: [], strategies: []} : {})});
    await g.viewRun(9); await flush();
    g.elapse(50);
    assert.equal((g.document.getElementById('sr-status') || {}).textContent || '', '');
    g.clearTimers();
  });

  test(`${name}: a figure's sub-line belongs to its term, so the kind of money is read with the figure`, async () => {
    const f = billingPage(cardedBilling({balance: 25.71, spent_7d: 100.17, runway_days: 1.7, reload_days: 1.4, pace_days: 7,
      autoreload_threshold: 5, autoreload_charge: 26.38, min_run_balance: 1}));
    await f.viewBilling(); await flush();
    const cells = f.root.querySelectorAll('#bfigs .m');
    assert.ok(cells.length >= 2);
    const subs = f.root.querySelectorAll('#bfigs .sub-fig');
    assert.ok(subs.length >= 1, 'the billing figures carry sub-lines');
    for (const cell of cells) assert.deepEqual(cell.children.map((c) => c.tag).filter((t) => t !== 'dt' && t !== 'dd'), []);
    for (const sub of subs) assert.equal(sub.tag, 'dd');
  });

  test(`${name}: the autopilot activity is a list that announces what is added`, async () => {
    const store = new Map([['tau_ap_open', '1']]);
    const f = frontend({storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/chat?')) return response({messages: [], agent_busy: false});
      if (path === '/api/models') return response({models: [], default: ''});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7}};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null); await flush();
    const msgs = box.querySelector('#apf-messages');
    assert.equal(msgs.tag, 'ol'); assert.equal(msgs.getAttribute('role'), null);
    assert.equal(msgs.getAttribute('aria-live'), 'polite'); assert.equal(msgs.getAttribute('aria-label'), 'Autopilot activity');
    // The feed scrolls on its own and most of its lines hold nothing focusable (axe scrollable-region-focusable on the
    // desktop panel, walk 2026-10-31): Tab reaches it, so the keyboard can scroll back through what it did.
    assert.equal(msgs.getAttribute('tabindex'), '0');
  });

  test(`${name}: every column of Explore's market table has a header a screen reader says, the Kalshi link column too`, async () => {
    const row = (t, mid) => ({t, s: t.split('-')[0], ti: `Game ${t} winner?`, su: 'Home', bid: +(mid - .01).toFixed(2), ask: +(mid + .01).toFixed(2), v24: 900, oi: 50});
    const markets = [row('KXA-1', .4), row('KXB-1', .6)];
    const explore = frontend({fetchImpl: (path) => path.startsWith('/api/explore?')
      ? response({markets, total: 2, shown: 2, matched: 2, page: 0, per: 40, at: new Date().toISOString()}) : response({})});
    explore.location.pathname = '/explore'; explore.location.search = '';
    await explore.viewExplore(); for (let i = 0; i < 6; i++) await flush();
    const heads = explore.root.querySelectorAll('#xbody thead th');
    assert.ok(heads.length >= 5, 'the market table is drawn');
    assert.deepEqual(heads.filter((th) => !th.textContent.trim()).map((th) => th.outerHTML || th.innerHTML), [], 'no header without words');
    const link = heads.filter((th) => th.querySelector('.vh') && th.querySelector('.vh').textContent === 'Link');
    assert.equal(link.length, 1, 'the link column says what it holds, off screen');
    assert.equal(link[0].getAttribute('aria-label'), null);
    assert.equal(link[0].textContent.trim(), 'Link', 'and shows nothing else');
    assert.ok(explore.root.querySelector('#xrows a[aria-label="Open on Kalshi"]'), 'its cells are the Open on Kalshi links');
    explore.clearTimers();
  });

  // Meridian's admin waitlist and both themes' saved-cards table had an empty last header over their buttons (axe
  // empty-table-header), as Explore's link column did: each holds visually hidden "Actions", as Deploy's does.
  test(`${name}: every column of the admin and billing tables has a header a screen reader says, the buttons' column too`, async () => {
    const admin = frontend({fetchImpl: (path) => {
      if (path === '/api/admin') return response({users: [{email: 'synthetic@example.invalid', name: '', created_at: '2026-10-25T10:00:00Z', balance: 5}],
        waitlist: [{email: 'waiting@example.invalid', note: '', created_at: '2026-10-25T10:00:00Z', status: 'requested'}], cards: [], client_errors: [], orphaned_open: null});
      if (path === '/api/admin/kill-switch') return response({on: false, reason: '', by: '', env_on: false});
      return response({});
    }});
    admin.S.me.is_admin = true;
    await admin.viewAdmin(); for (let i = 0; i < 6; i++) await flush();
    const adminHeads = admin.root.querySelectorAll('thead th');
    assert.ok(adminHeads.length >= 4, 'the admin tables are drawn');
    assert.deepEqual(adminHeads.filter((th) => !th.textContent.trim()).map((th) => th.innerHTML), [], 'no admin header without words');
    if (admin.root.querySelector('#waitlist [data-wl]')) {
      const last = admin.root.querySelectorAll('#waitlist thead th').at(-1);
      assert.equal(last.querySelector('.vh').textContent, 'Actions');
    }
    if (admin.clearTimers) admin.clearTimers();

    const billing = billingPage(cardedBilling());
    await billing.viewBilling(); await flush();
    const cardHeads = billing.root.querySelectorAll('thead th');
    assert.ok(billing.root.querySelectorAll('[data-remove]').length, 'the saved cards are drawn');
    assert.deepEqual(cardHeads.filter((th) => !th.textContent.trim()).map((th) => th.innerHTML), [], 'no billing header without words');
  });

  test(`${name}: the open autopilot panel's region is named apart from the Dashboard's autopilot card`, async () => {
    const store = new Map([['tau_ap_open', '1']]);
    const f = frontend({storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(dashboard());
      if (path.startsWith('/api/chat?')) return response({messages: [], agent_busy: false});
      if (path === '/api/models') return response({models: [], default: ''});
      return response({});
    }});
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7}};
    await f.viewDashboard(); await flush();
    const card = f.root.querySelector('#dash-ap');
    assert.equal(card.getAttribute('aria-label'), 'Autopilot');
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null); await flush(); await flush();
    assert.equal(box.getAttribute('role'), 'region');
    assert.equal(box.getAttribute('aria-label'), 'Autopilot panel');
    assert.notEqual(box.getAttribute('aria-label'), card.getAttribute('aria-label'));
    assert.doesNotMatch(source, /box\.setAttribute\('aria-label', 'Autopilot'\)/, 'no copy of the panel keeps the card\'s name');
    f.clearTimers();
  });

  test(`${name}: What if…'s dials say their value with its unit, and again as they move`, async () => {
    const s = strategyFrontend(detailStrategy(), () => response({in_sample: {}, out_of_sample: {}, equity: [], gates: [], passed: true}));
    await s.viewStrategy(42); await flush();
    const wi = s.root.querySelector('#whatif');
    const say = (id) => wi.querySelector(id).getAttribute('aria-valuetext');
    assert.equal(say('#wf'), '1.0 times the fees');
    assert.equal(say('#ws'), '0.0 cents per fill');
    assert.equal(say('#wk'), '$5 per trade');
    wi.querySelector('#wf').value = '1.25'; wi.querySelector('#ws').value = '0.5'; wi.querySelector('#wk').value = '40';
    wi.querySelector('#wk').oninput();
    assert.equal(say('#wf'), '1.25 times the fees');
    assert.equal(say('#ws'), '0.5 cents per fill');
    assert.equal(say('#wk'), '$40 per trade');
    // The shown figures are unchanged.
    assert.equal(wi.querySelector('#wfo').textContent, '1.25×');
    assert.equal(wi.querySelector('#wso').textContent, '0.5¢');
    assert.equal(wi.querySelector('#wko').textContent, '$40');
    s.clearTimers();
  });

  test(`${name}: Community's add-a-reaction button is named by the words it shows`, async () => {
    const post = {id: 12, body: 'Post 12', author: 'Bob', username: 'bob', created_at: '2026-10-17T10:00:00Z', mine: false, comments: 1, reactions: []};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/strategies') return response({strategies: []});
      if (path.startsWith('/api/community')) return response({posts: [post]});
      return response({});
    }});
    f.location.pathname = '/community';
    await f.viewCommunity(); for (let i = 0; i < 4; i++) await flush();
    const add = f.root.querySelector('[data-react-add]');
    assert.ok(add, 'the post has its add-a-reaction button');
    const label = add.getAttribute('aria-label'), shown = add.textContent.replace(/\+/g, '').trim();
    // Meridian shows the word "React"; Tau shows an icon with "+", named by its aria-label.
    // As words: "Add a reaction" holds the letters of "React" but not the word a speech user says.
    const word = new RegExp(`(^|\\W)${shown.replace(/[^\w ]/g, '')}(\\W|$)`, 'i');
    if (shown) assert.ok(label == null || word.test(label), `the name "${label}" holds the shown word "${shown}"`);
    else assert.equal(label, 'Add a reaction');
    if (shown) assert.equal(add.getAttribute('title'), 'Add a reaction', 'what it does is its description');
    f.clearTimers();
  });

  test(`${name}: the phone's autopilot sheet makes the page behind it inert, and closing or widening hands it back`, async () => {
    const store = new Map([['tau_ap_open', '0']]), listeners = [];
    let width = 390;
    const f = frontend({storage: storageFor(store), matchMedia: (q) => ({matches: width <= +/max-width: (\d+)px/.exec(q)[1]}),
      globals: {addEventListener: (type, fn) => listeners.push([type, fn])},
      fetchImpl: (path) => {
        if (path === '/api/deployments') return response({deployments: [], open_positions: []});
        if (path.startsWith('/api/chat')) return response({messages: [], agent_busy: false});
        if (path === '/api/models') return response({models: [], default: ''});
        return response({});
      }});
    f.location.pathname = '/deploy';
    await f.render(); await flush(); await flush();
    // The shell mounts the panel where each bundle keeps it: Tau beside the app in <body>, Meridian in the masthead.
    const box = f.document.getElementById('autopilot-float');
    const add = (tag, attrs) => { const el = f.document.createElement(tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); f.document.body.appendChild(el); return el; };
    const rail = add('aside', {id: 'rail-fixture'}), said = f.document.getElementById('sr-status') || add('div', {id: 'sr-status', 'aria-live': 'polite'});
    const under = (el) => { for (let e = el; e; e = e.parentElement) if (e.hasAttribute && e.hasAttribute('inert')) return true; return false; };
    const anyInert = () => f.document.body.querySelectorAll('[inert]').length;
    const open = async () => { store.set('tau_ap_open', '1'); f.renderAutopilot(box, null); await flush(); };
    await open();
    assert.equal(under(f.root.querySelector('main h1')), true, 'the page under the sheet is out of reach');
    assert.equal(under(rail), true);
    assert.equal(under(box), false, 'never the panel or what holds it');
    assert.equal(under(box.querySelector('.apf-x')), false);
    assert.equal(under(said), false, 'the live region stays heard');
    // Esc closes it: the page comes back before focus goes to what opened it.
    box.onkeydown({key: 'Escape', stopPropagation() {}}); await flush();
    assert.equal(store.get('tau_ap_open'), '0');
    assert.equal(anyInert(), 0);
    // Open again, then the window widens past a sheet: the panel sits beside the page, which is usable again.
    await open();
    assert.equal(under(rail), true);
    width = 1280;
    const resize = listeners.filter(([type, fn]) => type === 'resize' && fn.name === 'apInertPage');
    assert.equal(resize.length, 1, 'the sheet listens for the window changing size');
    resize[0][1]();
    assert.equal(anyInert(), 0, 'a desktop panel leaves the page alone');
    f.renderAutopilot(box, null); await flush();
    assert.equal(anyInert(), 0);
    // A page change on a phone (a link in the sheet) closes it, and the new page's heading takes focus, not the pill.
    width = 390; await open();
    assert.equal(under(rail), true);
    const x = box.querySelector('.apf-x');
    x.blur = () => { f.document.activeElement = f.document.body; };
    f.document.activeElement = x;
    f.location.pathname = '/settings'; await f.render(); await flush(); await flush();
    assert.equal(store.get('tau_ap_open'), '0');
    assert.equal(anyInert(), 0);
    const heading = f.root.querySelector('main h1'), pill = f.document.getElementById('autopilot-float').querySelector('.apf-pill');
    assert.equal(heading.textContent, 'Settings');
    assert.equal(heading.focusOptions && heading.focusOptions.preventScroll, true, 'the new page names itself');
    assert.equal(pill && pill.focusOptions, undefined);
    // Only what the sheet set comes off: an element inert for its own reasons stays so.
    rail.setAttribute('inert', '');
    await open(); store.set('tau_ap_open', '0'); f.renderAutopilot(box, null);
    assert.equal(rail.hasAttribute('inert'), true);
    f.clearTimers();
  });

  test(`${name}: Billing's card table names every column, its panels skip no heading level, and auto-reload keeps focus`, async () => {
    let f;
    const posts = [];
    f = billingPage(cardedBilling(), posts, {'/api/billing/auto-reload': (options) => {
      posts.push(JSON.parse(options.body));
      f.document.activeElement = f.document.body;  // the browser blurs the switch the save locks
      return response({ok: true});
    }});
    await f.viewBilling(); await flush();
    const heads = f.root.querySelectorAll('#cards th');
    assert.deepEqual(heads.map((th) => th.textContent.trim()), ['Card', 'Expires', 'Status', 'Actions']);
    assert.equal(heads[3].querySelector('.vh').textContent, 'Actions', 'named for a screen reader, not shown');
    assert.deepEqual(headingSkips(f.root), []);
    assert.deepEqual(f.root.querySelectorAll('.panel h2').map((h) => h.textContent), ['Payment method', 'Add credits']);
    const box = f.root.querySelector('#autoreload');
    box.focus(); f.document.activeElement = box; box.checked = false;
    await box.onchange(); await flush();
    assert.deepEqual(posts, [{on: false, amount: 25, threshold: 8}]);
    assert.equal(box.disabled, false);
    assert.equal(box.focusOptions.preventScroll, true, 'focus is back on the switch once it unlocks');
  });

  test(`${name}: an unavailable live or demo deploy says why to a screen reader, and the undeployed page skips no heading`, async () => {
    const f = strategyFrontend(detailStrategy(), () => response({}));
    f.S.me = {...f.S.me, live_trading_available: false, kalshi_dev_connected: false};
    await f.viewStrategy(42); await flush();
    const live = f.root.querySelector('#dep-live'), demo = f.root.querySelector('#dep-demo');
    assert.equal(live.getAttribute('aria-disabled'), 'true');
    assert.equal(f.root.querySelector('#' + live.getAttribute('aria-describedby')).textContent, 'Live trading isn’t open yet.');
    assert.equal(demo.getAttribute('aria-disabled'), 'true');
    assert.match(f.root.querySelector('#' + demo.getAttribute('aria-describedby')).textContent, /^Add your Kalshi demo \(sandbox\) key on the Funds page first\.$/);
    assert.deepEqual(headingSkips(f.root), [], 'no deployment: the research sections sit under an h2');
    f.clearTimers();
    // With a demo key the demo button is described by what demo does; live open needs no reason.
    const g = strategyFrontend(detailStrategy(), () => response({}));
    g.S.me = {...g.S.me, live_trading_available: true, kalshi_connected: true, kalshi_dev_connected: true};
    await g.viewStrategy(42); await flush();
    assert.equal(g.root.querySelector('#dep-demo').getAttribute('aria-disabled'), null);
    assert.match(g.root.querySelector('#dep-demo-why').textContent, /^Trades Kalshi’s demo exchange with your own demo key/);
    assert.equal(g.root.querySelector('#dep-live').getAttribute('aria-describedby'), null);
    assert.equal(g.root.querySelector('#dep-live-why'), null);
    g.clearTimers();
  });

  // From a keyboard and screen-reader walk of the main flows (Tab, Enter, Space and Escape only, both themes, 390px and
  // 1280px, seeded account, 2026-10-30): the places focus fell to <body>, a result that said nothing, and controls named
  // only by their place on screen.
  const settle = async () => { for (let i = 0; i < 8; i++) await flush(); };
  // Tau's harness marks the element (focused), Meridian's moves document.activeElement.
  const focusedOn = (f, el) => el.focused === true || f.document.activeElement === el;
  const said = (f) => { f.elapse(50); const el = f.document.getElementById('sr-status'); return el ? el.textContent : ''; };

  test(`${name}: a Strategies filter chip keeps focus once it draws the list again, and a market's page from Explore takes it to its heading`, async () => {
    const oos = {pnl: 3.1, trades: 40, win_rate: 0.6, days: 9};
    const rows = [detailStrategy({id: 61, title: 'Cleared pass', status: 'passed', out_of_sample: oos})];
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/strategies') ? response({counts: {total: 1, passed: 1}, matched: 1, pages: 1, strategies: rows}) : response({}))});
    f.S.me.markets = [{key: 'btc15m', category: 'Crypto'}];
    f.location.pathname = '/strategies'; f.location.search = '';
    await f.render(); await settle();
    // Space on "Passed": the chip is drawn again with the list (the filter rides in the URL), and focus fell to <body>.
    const chip = f.root.querySelector('[data-f="status"][data-v="passed"]');
    f.document.activeElement = chip;
    chip.onclick(); await settle();
    assert.equal(f.location.search, '?status=passed');
    const now = f.root.querySelector('[data-f="status"][data-v="passed"]');
    assert.notEqual(now, chip, 'the list was drawn again');
    assert.equal(now.getAttribute('aria-pressed'), 'true');
    assert.equal(now.focusOptions && now.focusOptions.preventScroll, true, 'focus is on the chip that was pressed');
    assert.equal(f.root.querySelector('main h1').focusOptions, undefined, 'not sent up to the heading');
    // Pressed again, it draws the same URL again: focus stays with it too.
    f.document.activeElement = now;
    now.onclick(); await settle();
    const again = f.root.querySelector('[data-f="status"][data-v="passed"]');
    assert.notEqual(again, now);
    assert.equal(again.focusOptions && again.focusOptions.preventScroll, true);
    assert.equal(f.root.querySelector('main h1').focusOptions, undefined);
    // The market select keeps it too (found by its id).
    f.document.activeElement = f.root.querySelector('#strat-market');
    f.root.querySelector('#strat-market').value = 'btc15m'; f.root.querySelector('#strat-market').onchange(); await settle();
    assert.equal(f.root.querySelector('#strat-market').focusOptions.preventScroll, true);
    f.clearTimers();

    // Explore's list and a market's page are one path (/explore, /explore?m=): Enter on a row left focus on <body>.
    const at = new Date(Date.now() + 5 * 3600e3).toISOString();
    const feed = {at: new Date().toISOString(), total: 2, shown: 1, matched: 1, page: 0, per: 40, sort: 'v24', spot: null,
      markets: [{t: 'KXBTCD-26OCT2617-T112999.99', s: 'KXBTCD', ti: 'Bitcoin price at 5pm EDT?', su: '$113,000 or above', bid: .48, ask: .52, last: .5, v24: 9, oi: 5, ct: at}]};
    const market = {ticker: 'KXBTCD-26OCT2617-T112999.99', series: 'KXBTCD', title: 'Bitcoin price at 5pm EDT?', sub: '$113,000 or above', status: 'active',
      yes_bid: '0.55', yes_ask: '0.57', last: '0.55', volume_24h: '15', open_interest: '40', close_time: at, as_of: new Date().toISOString(), rules: 'Resolves Yes above 112999.99.',
      period_min: 1, points: Array.from({length: 30}, (_, i) => ({t: Math.floor(Date.now() / 1000) - 1800 + 60 * i, yes: .5, vol: 1})), mine: {open: [], closed: []}};
    const g = frontend({fetchImpl: (path) => (path.startsWith('/api/explore/market?') ? response(market) : path.startsWith('/api/explore?') ? response(feed)
      : path.startsWith('/api/explore/spot?') ? response({spot: null}) : response({}))});
    g.S.me.markets = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET', category: 'Crypto', close_hour_et: 17}];
    g.location.pathname = '/explore'; g.location.search = '';
    await g.render(); await settle();
    g.document.activeElement = g.root.querySelector('#xrows a');
    g.location.search = '?m=KXBTCD-26OCT2617-T112999.99'; await g.render(); await settle();  // the row's link (go)
    const heading = g.root.querySelector('main h1');
    assert.match(heading.textContent, /Bitcoin price at 5pm EDT\?/);
    assert.equal(heading.focusOptions && heading.focusOptions.preventScroll, true, "the market's heading takes focus");
    // And Back to the list lands on the list's heading, not <body>.
    g.document.activeElement = g.document.body;
    g.location.search = ''; await g.render(); await settle();
    assert.equal(g.root.querySelector('main h1').textContent.trim(), 'Explore');
    assert.equal(g.root.querySelector('main h1').focusOptions.preventScroll, true);
    g.clearTimers();
  });

  test(`${name}: each Strategies pick box says which strategy it picks`, () => {
    const f = frontend();
    const slip = f.strategySlip(detailStrategy({id: 61, title: 'BTC <snapback> #4', status: 'passed'}), null, {pick: true});
    // Every row's box was "Select for deployment": Tab down the list said the same words on each.
    assert.match(slip, /<input type="checkbox" class="pick" data-id="61" aria-label="Select BTC &lt;snapback&gt; #4 for deployment">/);
    // Its focus ring: test_ui_contrast.mjs (the stylesheets).
  });

  test(`${name}: a phone's Strategies list has a Select all it can tap, labelled, that picks what the header's picks`, async () => {
    const rows = [detailStrategy({id: 61, title: 'First pass', status: 'passed'}), detailStrategy({id: 62, title: 'Second pass', status: 'passed'})];
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/strategies') ? response({counts: {total: 2, passed: 2}, matched: 2, pages: 1, strategies: rows}) : response({}))});
    await f.viewStrategies(); for (let i = 0; i < 6; i++) await flush();
    const picks = f.root.querySelectorAll('.pick'), head = f.root.querySelector('#pick-all');
    assert.equal(picks.length, 2);
    // Its own label, the words the header's box is named by.
    const label = f.root.querySelector('#slips label.pick-all-m'), box = label && label.querySelector('input[type="checkbox"][data-pickall]');
    assert.ok(box, 'a Select all outside the clipped table header');
    assert.equal(label.textContent.trim(), 'Select all deployable');
    assert.equal(head.getAttribute('aria-label'), 'Select all deployable');
    // Either box picks every row and the other box with it; a row taken off clears both; Clear clears both.
    box.checked = true; box.onclick();
    assert.deepEqual(picks.map((c) => c.checked), [true, true]);
    assert.equal(head.checked, true);
    assert.match(f.root.querySelector('#bulkbar').innerHTML, /2 selected/);
    picks[0].checked = false; picks[0].onchange();
    assert.equal(box.checked, false); assert.equal(head.checked, false);
    head.checked = true; head.onclick();
    assert.equal(box.checked, true); assert.deepEqual(picks.map((c) => c.checked), [true, true]);
    f.root.querySelector('#bulk-clear').onclick();
    assert.deepEqual([box.checked, head.checked, ...picks.map((c) => c.checked)], [false, false, false, false]);
    // With nothing to pick, no box.
    const g = frontend({fetchImpl: (path) => (path.startsWith('/api/strategies') ? response({counts: {total: 1, failed: 1}, matched: 1, pages: 1,
      strategies: [detailStrategy({id: 63, title: 'Void one', status: 'failed'})]}) : response({}))});
    await g.viewStrategies(); for (let i = 0; i < 6; i++) await flush();
    assert.equal(g.root.querySelector('[data-pickall]'), null);
    f.clearTimers(); g.clearTimers();
    // The stylesheet shows one of the two: the header's box wide, the phone's own up to 760px (a 44px row), where the
    // header's goes and its column keeps a name a screen reader says (.pick-head).
    const css = readFileSync(new URL(`../app/static/${name === 'Tau' ? 'app.css' : 'app.meridian.css'}`, import.meta.url), 'utf8');
    assert.match(css, /\n\.pick-all-m, \.pick-head \{ display: none; \}/);
    const phone = phoneRules(css);
    assert.match(phone, /\.pick-all-m \{ display: flex;[^}]*min-height: 44px;/);
    assert.match(phone, /\.pick-all-m input \{ width: 24px; height: 24px;/);
    // Each row's own box is 24px on a phone too (WCAG 2.5.8): it was 22px, the stacked row's only control under 24px.
    assert.match(phone, /\.t-strat\.stack tbody td\.pickcol input \{ width: 24px; height: 24px;/);
    assert.match(phone, /\.stack thead #pick-all \{ display: none; \}/);
    assert.match(phone, /\.stack thead \.pick-head \{ display: inline; \}/);
    const th = f.root.querySelector('th.pickcol');
    assert.equal(th.querySelector('#pick-all'), head); assert.equal(th.querySelector('.vh.pick-head').textContent, 'Select');
  });

  test(`${name}: Show older sessions hands focus to the first session it lists, not <body>`, async () => {
    const run = (id) => ({id, seq: id, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea ' + id,
      hypotheses_tried: 9, strategies_passed: 1, spent_usd: 0.5, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit'});
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs?before=')) return response({runs: [run(50), run(49)], more: false});
      if (path.startsWith('/api/runs')) return response({runs: Array.from({length: 50}, (_, k) => run(100 - k)), counts: {research_running: 0, research_queued: 0, research_paused: 0},
        policy: null, totals: {tried: 9, passed: 1}, v: 'v1', own_total: 52});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const host = f.root.querySelector('#runs-older'), btn = host.querySelector('button[data-older]');
    f.document.activeElement = btn;
    await host.listeners.get('click')({target: btn}); await settle();
    assert.equal(host.querySelector('button[data-older]'), null, 'the last page: the button is gone');
    const first = f.root.querySelector('#runs a[href="/research/50"]');
    assert.ok(focusedOn(f, first), 'focus is on the first older session');
    assert.equal(first.focusOptions, undefined, 'and the page scrolls to it');
    f.clearTimers();
  });

  test(`${name}: Show older entries says how many came in, hands focus to the first entry it lists, and past the last page to the line that says so`, async () => {
    const entry = (id) => ({id, kind: 'trade', amount: -1.25, created_at: new Date(Date.UTC(2026, 4, 1) + id * 36e5).toISOString(), memo: `Bought 5 YES KXBTC15M-26OCT241200-00 @ 0.25 (#${id})`});
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/funds/ledger?before=')) {
        const before = +path.split('=')[1], ids = Array.from({length: before - 1}, (_, k) => before - 1 - k);
        return response({ledger: ids.slice(0, 50).map(entry), more: ids.length > 50});
      }
      if (path === '/api/funds') return response({...fundsData(), paper: {cash: 1234.56, equity: 1240.06, realized_pnl: 12.5, closed_trades: 40, open_positions: 0,
        ledger: Array.from({length: 50}, (_, k) => entry(120 - k))}});
      return response({});
    }});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    let btn = f.root.querySelector('#ledger-older-btn');
    f.document.activeElement = btn;
    await f.root.querySelector('#ledger-older').onclick({target: btn}); await settle();
    assert.equal(f.root.querySelectorAll('.t-ledger tbody tr').length, 100);
    assert.equal(said(f), '50 older entries shown.', 'the rows came in with nothing said');
    // More remain: focus stayed on the button, which the 50 new rows pushed below the screen. It goes to the first
    // entry just listed (#70, under the newest 50), as Show older sessions does, and the page scrolls to it.
    let row = f.root.querySelectorAll('.t-ledger tbody tr')[50];
    assert.match(row.innerHTML, /#70\)/);
    assert.equal(row.getAttribute('tabindex'), '-1');
    assert.ok(focusedOn(f, row), 'focus is on the first older entry');
    assert.equal(row.focusOptions, undefined, 'and the page scrolls to it');
    btn = f.root.querySelector('#ledger-older-btn');
    f.document.activeElement = btn;
    await f.root.querySelector('#ledger-older').onclick({target: btn}); await settle();
    assert.equal(f.root.querySelector('#ledger-older-btn'), null);
    // The last page says its own count: the live region still held the previous page's "50 older entries shown."
    assert.equal(f.root.querySelectorAll('.t-ledger tbody tr').length, 120);
    assert.equal(said(f), '20 older entries shown.');
    const end = f.root.querySelector('.ledger-end');
    assert.equal(end.getAttribute('tabindex'), '-1');
    assert.ok(focusedOn(f, end), 'focus fell to <body> with the button');
    assert.equal(end.focusOptions, undefined, 'and the line, under the rows just added, scrolls into view');
    f.clearTimers();
  });

  test(`${name}: Billing's auto-reload amounts have names, and the button that opens them says it changes them`, async () => {
    const f = billingPage(cardedBilling());
    await f.viewBilling(); await flush();
    // The two fields in "Reload [25] dollars when my balance drops to [8] dollars." were read as bare spin buttons.
    assert.equal(f.root.querySelector('#reload-amt').getAttribute('aria-label'), 'Reload amount, in dollars');
    assert.equal(f.root.querySelector('#reload-thr').getAttribute('aria-label'), 'Reload when my balance drops to, in dollars');
    assert.equal(f.root.querySelector('#reload-amt').getAttribute('aria-describedby'), 'autorel-flash');
    // "Reload $25 at $8" alone, out of context, sounded like a button that charges the card.
    const edit = f.root.querySelector('#autorel-edit');
    assert.equal(edit.querySelector('#autorel-sum').textContent, 'Reload $25 at $8', 'the words it shows lead its name');
    assert.equal(edit.querySelector('.vh').textContent, ' (change amounts)');
    f.clearTimers();
  });

  test(`${name}: the autopilot panel's story is written only when its words change, not on every status read`, async () => {
    const store = new Map([['tau_ap_open', '1']]);
    const f = frontend({storage: storageFor(store), fetchImpl: (path) => {
      if (path.startsWith('/api/chat?')) return response({messages: [], agent_busy: false});
      if (path === '/api/models') return response({models: [], default: ''});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), id: 7, autopilot: true}};
    f.S.ap = {...f.S.ap, autopilot: true, mode: 'paper', paper_running: 2};
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    f.renderAutopilot(box, null); await flush(); await flush();
    const story = box.querySelector('#apf-story');
    assert.equal(story.getAttribute('aria-live'), 'polite');
    f.apUpdate(box, {...f.S.ap});
    const writes = story.writes, words = story.innerHTML;
    for (let i = 0; i < 3; i++) f.apUpdate(box, {...f.S.ap});
    assert.equal(story.writes, writes, 'the same story left the live region alone');
    f.apUpdate(box, {...f.S.ap, idle: {code: 'no_ideas', line: 'Nothing to do until the next review.'}});
    assert.equal(story.writes, writes + 1, 'a new story is written, once');
    assert.notEqual(story.innerHTML, words);
    f.clearTimers();
  });

  test(`${name}: a search typed on Explore says how many markets match, and a poll says nothing`, async () => {
    const ct = new Date(Date.now() + 5 * 3600e3).toISOString();
    const row = (t, ti) => ({t, s: t.split('-')[0], ti, su: '', bid: .48, ask: .52, last: .5, v24: 9, oi: 5, ct});
    const f = frontend({fetchImpl: (path) => {
      if (!path.startsWith('/api/explore?')) return response({});
      const q = new URLSearchParams(path.split('?')[1]).get('q') || '';
      const markets = [row('KXBTCD-26OCT2617-T1', 'Bitcoin price at 5pm EDT?'), row('KXBTCD-26OCT2617-T2', 'Bitcoin price at 5pm EDT, higher?')].filter((m) => !q || m.ti.toLowerCase().includes(q));
      return response({at: new Date().toISOString(), total: 2, shown: markets.length, matched: markets.length, page: 0, per: 40, sort: 'v24', spot: null, markets});
    }});
    f.S.me.markets = [];
    f.location.pathname = '/explore';
    await f.viewExplore(); await settle();
    assert.equal(said(f), '', 'the first list says nothing');
    const type = async (words) => { const q = f.root.querySelector('#xq'); q.value = words; q.listeners.get('input')({target: q}); f.elapse(220); await settle(); };
    await type('bitcoin');
    assert.equal(said(f), '2 markets match “bitcoin”.');
    await type('higher');
    assert.equal(said(f), '1 market matches “higher”.');
    await type('zzz');
    assert.equal(said(f), 'No markets match “zzz”.');
    f.document.getElementById('sr-status').textContent = '';
    for (const tick of [...f.intervals.values()]) { await tick(); await settle(); }
    assert.equal(said(f), '', 'the list kept current says nothing');
    f.clearTimers();
  });

  // Walks of 2026-10-31: a Try again that brought back what failed drew over its notice, the button with it, and
  // keyboard focus fell to <body> (Billing's saved cards, System's map, Explore's list, the dashboard's autopilot card).
  // Back, focus goes to the heading of what came in (or the card, which has none); failed again, to the new Try again.
  test(`${name}: a Try again that brings back what failed puts focus on what came in, and one that fails again on Try again`, async () => {
    const settle = async () => { for (let i = 0; i < 8; i++) await flush(); };
    const focused = (el) => !!(el && el.focusOptions && el.focusOptions.preventScroll === true);
    // Billing: the saved cards come back under Payment method; still unread, focus goes to the new Try again.
    let cards = cardedBilling({cards: [], cards_unread: true});
    const b = billingPage(null, [], {[`/api/billing?tz=${new Date().getTimezoneOffset()}`]: () => response(cards)});
    await b.viewBilling(); await settle();
    let again = b.root.querySelector('#cards [data-retry]');
    b.document.activeElement = again;
    await again.onclick(); await settle();
    const still = b.root.querySelector('#cards [data-retry]');
    assert.ok(still && still !== again, 'still unread: a new Try again');
    assert.ok(focused(still), 'focus is on the new Try again');
    b.document.activeElement = still; cards = cardedBilling();
    await still.onclick(); await settle();
    const pay = b.root.querySelector('#main .panel h2');
    assert.equal(pay.textContent, 'Payment method');
    assert.ok(focused(pay), 'the cards back: their panel heading takes focus');
    assert.equal(pay.getAttribute('tabindex'), '-1');
    b.clearTimers();

    // System: the map back, the page's heading takes focus (the map has none); failed again, the new Try again.
    let sysUp = false, sysAsk = 0;
    const s = frontend({fetchImpl: (path) => path === '/api/admin/system'
      ? (++sysAsk, sysUp ? response({nodes: {}, events: [], now: '2026-10-20T16:00:00Z'}) : response({error: 'System status is busy.'}, 500)) : response({})});
    await s.viewSystem(); await settle();
    again = s.root.querySelector('#sys-error [data-retry]');
    s.document.activeElement = again;
    await again.onclick(); await settle();
    const sysAgain = s.root.querySelector('#sys-error [data-retry]');
    assert.ok(sysAgain && sysAgain !== again && focused(sysAgain), 'failed again: focus on the new Try again');
    assert.equal(focused(s.root.querySelector('main h1')), false);
    s.document.activeElement = sysAgain; sysUp = true;
    await sysAgain.onclick(); await settle();
    assert.equal(s.root.querySelector('#sys-error [data-retry]'), null);
    const sysHead = s.root.querySelector('main h1');
    assert.equal(sysHead.textContent.trim(), 'System');
    assert.ok(focused(sysHead), 'the map back: the page heading takes focus');
    assert.equal(sysHead.getAttribute('tabindex'), '-1');
    s.clearTimers();

    // Explore: the list back, the page's heading takes focus (the list has none); failed again, Try again keeps it.
    const at = new Date(Date.now() + 5 * 3600e3).toISOString();
    const feed = {at: new Date().toISOString(), total: 1, shown: 1, matched: 1, page: 0, per: 40, sort: 'v24', spot: null,
      markets: [{t: 'KXBTCD-26OCT2617-T112999.99', s: 'KXBTCD', ti: 'Bitcoin price at 5pm EDT?', su: '$113,000 or above', bid: .48, ask: .52, last: .5, v24: 9, oi: 5, ct: at}]};
    let xUp = false;
    const x = frontend({fetchImpl: (path) => path.startsWith('/api/explore?') ? (xUp ? response(feed) : response({error: 'Explore is busy.'}, 500))
      : path.startsWith('/api/explore/spot?') ? response({spot: null}) : response({})});
    x.location.pathname = '/explore'; x.location.search = '';
    await x.viewExplore(); await settle();
    again = x.root.querySelector('#xbody [data-xretry]');
    x.document.activeElement = again;
    await again.onclick(); await settle();
    assert.equal(x.root.querySelector('#xbody [data-xretry]'), again, 'failed again with the same words: the same button, still focused');
    assert.equal(focused(x.root.querySelector('main h1')), false);
    xUp = true;
    await again.onclick(); await settle();
    assert.ok(x.root.querySelector('#xrows a'), 'the list is back');
    const xHead = x.root.querySelector('main h1');
    assert.equal(xHead.textContent.trim(), 'Explore');
    assert.ok(focused(xHead), 'the list back: the page heading takes focus');
    x.clearTimers();

    // The dashboard's autopilot card: back, the card (named Autopilot) takes focus. Not its first heading: a week with
    // something in it draws "Last 7 days" halfway down the card, and focus landed there (keyboard walk 2026-10-31).
    let apUp = false;
    const week = {tested: 4, passed: 1, not_cleared: 0, paper_started: 1, research_credits: 0.84, checkin_credits: 0, trades: 0, pnl: 0};
    const d = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(dashboard());
      if (path === '/api/autopilot/status') return apUp ? response({...apStatus, week}) : response({error: 'Something went wrong on our side.'}, 500);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      return response({});
    }});
    d.S.me = {...d.S.me, billing_enabled: true, credit_balance: 25.71, min_run_balance: 1};
    d.S.me.user.autopilot = true; d.S.ap = null; d.S.apAt = 0;
    await d.viewDashboard(); await settle();
    again = d.root.querySelector('#dash-ap [data-apcard="again"]');
    d.document.activeElement = again;
    await again.onclick(); await settle();
    assert.equal(d.root.querySelector('#dash-ap [data-apcard="again"]'), again, 'failed again: the same button keeps focus');
    assert.equal(focused(d.root.querySelector('#dash-ap')), false);
    apUp = true;
    await again.onclick(); await settle();
    const card = d.root.querySelector('#dash-ap');
    assert.equal(card.querySelector('[data-apcard="again"]'), null, 'the card draws the status');
    assert.equal(card.querySelector('.ap-week h3').textContent, 'Last 7 days');
    assert.ok(focused(card), 'the card takes focus');
    assert.equal(focused(card.querySelector('.ap-week h3')), false, 'not the week heading halfway down it');
    assert.equal(card.getAttribute('tabindex'), '-1');
    assert.equal(card.getAttribute('aria-label'), 'Autopilot');
    d.clearTimers();
  });

  // Walk 2026-10-31 (the server down, then back): the Strategies list's Try again drew the list over its button and
  // focus fell to <body>; Research's "Your research results" Try again did the same. Back, focus goes into what came in.
  test(`${name}: the Strategies list's and Research results' Try again put focus into what came in`, async () => {
    const settle = async () => { for (let i = 0; i < 8; i++) await flush(); };
    const focused = (el) => !!(el && el.focusOptions && el.focusOptions.preventScroll === true);
    const rows = [detailStrategy({id: 61, title: 'Cleared pass', status: 'passed', out_of_sample: {pnl: 3.1, trades: 40, win_rate: 0.6, days: 9}})];
    let up = false;
    const st = frontend({fetchImpl: (path) => (path.startsWith('/api/strategies')
      ? (up ? response({counts: {total: 1, passed: 1}, matched: 1, pages: 1, strategies: rows}) : response({error: 'Something went wrong on our side.'}, 500))
      : response({}))});
    st.S.me.markets = [{key: 'btc15m', category: 'Crypto'}];
    st.location.pathname = '/strategies'; st.location.search = '';
    await st.viewStrategies(); await settle();
    const slips = st.root.querySelector('#slips');
    let again = slips.querySelector('[data-retry]');
    st.document.activeElement = again;
    await again.onclick(); await settle();
    const still = slips.querySelector('[data-retry]');
    assert.ok(still && still !== again && focused(still), 'failed again: focus on the new Try again');
    st.document.activeElement = still; up = true;
    await still.onclick(); await settle();
    assert.equal(slips.querySelector('[data-retry]'), null);
    assert.match(slips.textContent, /Cleared pass/);
    assert.ok(focused(slips), 'the list back: focus goes into it');
    assert.equal(slips.getAttribute('tabindex'), '-1');
    st.clearTimers();

    const BOARD = {total: {runs: 2, explored: 10, gated: 3, passed: 1, cost_usd: 2, gate_reach_rate: 0.3, pipeline_death_share: 0.2}};
    let boardUp = false;
    const r = frontend({fetchImpl: (path) => {
      if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}], default: 'opus'});
      if (path.startsWith('/api/research/scoreboard')) return boardUp ? response(BOARD) : response({error: 'Something went wrong on our side.'}, 500);
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {research_running: 0, research_queued: 0}, totals: {tried: 4, passed: 1}});
      return response({});
    }});
    r.S.me.user.autopilot = false;
    r.location.pathname = '/research';
    await r.viewResearch(); await settle();
    const host = r.root.querySelector('#rsimo');
    again = host.querySelector('[data-retry]');
    r.document.activeElement = again; boardUp = true;
    await again.onclick(); await settle();
    assert.match(host.textContent, /Is research getting better\?/);
    assert.ok(focused(host), 'the results back: focus goes into them');
    r.clearTimers();
  });

  test(`${name}: a session's working spinner is hidden from a screen reader, not named "in process"`, async () => {
    // A <span aria-label> with no role is a name nothing reads (axe aria-prohibited-attr): the word beside it says it.
    const f = frontend();
    const row = f.runRow({id: 9, seq: 3, status: 'running', market: 'btc15m', direction: 'momentum', prompt: 'Idea', hypotheses_tried: 2, strategies_passed: 0, created_at: '2026-10-25T08:00:00Z'});
    assert.doesNotMatch(row, /aria-label="in process"/);
    for (const m of row.matchAll(/<span class="working"[^>]*>/g)) assert.match(m[0], /aria-hidden="true"/);
    const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
    const g = frontend({fetchImpl: () => response({run, events: []})});
    await g.viewRun(9); await settle();
    const figs = g.root.querySelector('#runfigs');
    assert.doesNotMatch(figs ? figs.innerHTML : '', /aria-label="in process"/);
    g.clearTimers();
  });
}
