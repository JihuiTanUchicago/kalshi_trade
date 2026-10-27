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
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));

// Each heading's level against the one before it, in document order: a step down of more than one
// (h1 then h3) is a skip a screen reader's heading list shows as a missing level.
const headingSkips = (host) => {
  const levels = host.querySelectorAll('h1, h2, h3, h4, h5, h6').map((h) => [+h.tag.slice(1), h.textContent.trim()]);
  return levels.filter(([level], i) => level > (i ? levels[i - 1][0] : 0) + 1).map(([level, text]) => `h${level} ${text}`);
};

export function a11yCases({name, frontend, storageFor, billingPage, cardedBilling, source, strategyFrontend, detailStrategy, dashboard, fundsData}) {
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
      explore.clearTimers();
    }
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
    stream.state('running');
    if (label) {
      assert.equal(said(), 'Researching');
      for (const tick of [...f.intervals.values()]) tick();
      stream.state('running');
      assert.equal(said(), 'Researching', 'the same state again is not said again');
      stream.state('paused');
      assert.equal(said(), 'Paused — resume and it picks up exactly where it left off.');
    } else {
      assert.equal(said(), '');  // Meridian has no foot: its run status is said by the page above
    }
    f.clearTimers();
    // On the page, the foot that ticks is not itself a live region, and the log is a list that announces.
    const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
    const g = frontend({fetchImpl: (path) => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: []}); }});
    await g.viewRun(9);
    const foot = g.root.querySelector('#runpulse');
    if (foot) assert.equal(foot.getAttribute('aria-live'), null);
    const log = g.root.querySelector('#log');
    assert.equal(log.tag, 'ol'); assert.equal(log.getAttribute('role'), null); assert.equal(log.getAttribute('aria-live'), 'polite');
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
  });
}
