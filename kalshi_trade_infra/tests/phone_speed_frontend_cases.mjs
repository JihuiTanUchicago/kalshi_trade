// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): what a page
// asks the server for while it loads, so a phone on a slow network waits on as few round trips as it can.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const counts = {research_running: 0, research_queued: 0, research_paused: 0};
const runsAnswer = {runs: [], counts, policy: null, totals: {tried: 0, passed: 0}, v: 'v1'};
const researchTransport = (over = {}) => (path) => {
  if (over[path.split('?')[0]]) return over[path.split('?')[0]](path);
  if (path.startsWith('/api/runs')) return response(runsAnswer);
  if (path === '/api/explore/hot') return response({markets: [], at: '2026-10-26T08:00:00Z'});
  if (path === '/api/research/context') return response({markets: []});
  if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
  return response({});
};
const asked = (f, prefix) => f.requests.filter(({path}) => path.startsWith(prefix)).length;

export function phoneSpeedCases({name, frontend, storageFor, railOpenWide, source}) {
  test(`${name}: hot markets are read once while the rail shows, and not at all while it is hidden`, async () => {
    // Shown: the rail is open on a wide screen. Research paints its shell twice; one read, not two.
    let f = frontend({fetchImpl: researchTransport(), storage: storageFor(new Map(railOpenWide)), matchMedia: () => ({matches: false})});
    f.S.hot = null; f.S.hotAt = 0;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/explore/hot'), 1, 'one read for one page');
    assert.equal(f.S.hot.at, '2026-10-26T08:00:00Z');
    f.clearTimers();

    // Hidden: a phone (Tau hides the rail under 761px) with the rail closed (Meridian hides a closed rail).
    f = frontend({fetchImpl: researchTransport(), storage: storageFor(new Map()), matchMedia: () => ({matches: true})});
    f.S.hot = null; f.S.hotAt = 0;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/explore/hot'), 0, 'nothing on the page shows the snapshot');
    // Nor each minute while it stays hidden: the page's own polls still run.
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.equal(asked(f, '/api/explore/hot'), 0);
    assert.ok(asked(f, '/api/runs') >= 2, 'the session list still polls');
    f.clearTimers();
  });

  test(`${name}: Research asks for the loop's scoreboard beside its session list, not after it`, async () => {
    let answerRuns;
    const runsHeld = new Promise((resolve) => { answerRuns = resolve; });
    const board = {total: {runs: 2, explored: 10, gated: 4, passed: 1, cost_usd: 2, gate_reach_rate: 0.4, pipeline_death_share: 0.5}, days: []};
    const f = frontend({fetchImpl: researchTransport({
      '/api/runs': () => runsHeld.then(() => response(runsAnswer)),
      '/api/research/scoreboard': () => response(board),
    })});
    f.location.pathname = '/research';
    const page = f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/runs'), 1);
    assert.equal(asked(f, '/api/research/scoreboard'), 1, 'asked while the session list is still on its way');
    answerRuns(); await page; await settle();
    assert.equal(asked(f, '/api/research/scoreboard'), 1, 'and read once for the page');
    assert.match(f.root.querySelector('#rsimo').innerHTML, /Ideas tried/, 'the loop card draws the board');
    // The 5s poll draws from the kept board inside the minute: no second read.
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.equal(asked(f, '/api/research/scoreboard'), 1);
    f.clearTimers();
  });

  test(`${name}: Billing's statement builds its date and count formats once, whatever its length, and reads as toLocaleString did`, async () => {
    const day = (k) => `2026-09-${String(10 + (k % 15)).padStart(2, '0')}`;
    const statement = (n) => ({configured: false, balance: 12.5, spent: 40, spent_7d: 3, spent_24h: 1, pace_days: 7, free_bonus: 20,
      topup_fee_pct: 5.5, cards: [], default_pm: null, auto_reload: false, min_run_balance: 1, spent_7d_by: {},
      math: {days: 30, start: 20, bought: 0, purchases: 0, other: 0, usage: 7.5, end: 12.5}, ledger_cut: false,
      ledger: Array.from({length: n}, (_, k) => ({kind: 'usage', amount: -0.25, memo: 'Model usage', item: 'Research session', model: 'A model',
        calls: 1234 + k, day: day(Math.floor(k / 3)), first_at: `${day(Math.floor(k / 3))}T08:0${k % 3}:00Z`, created_at: `${day(Math.floor(k / 3))}T09:1${k % 3}:00Z`}))});
    // toLocale*String builds a new formatter on every call: count those calls on the page's own dates.
    const made = async (n) => {
      let calls = 0;
      class CountingDate extends Date {
        toLocaleString(...a) { calls++; return super.toLocaleString(...a); }
        toLocaleDateString(...a) { calls++; return super.toLocaleDateString(...a); }
        toLocaleTimeString(...a) { calls++; return super.toLocaleTimeString(...a); }
      }
      const f = frontend({globals: {Date: CountingDate}, fetchImpl: (path) => path.startsWith('/api/billing') ? response(statement(n)) : response({})});
      f.location.pathname = '/billing';
      await f.viewBilling(); await settle();
      f.clearTimers();
      return {built: calls, html: f.root.querySelector('#main').innerHTML};
    };
    const short = await made(6), long = await made(300);
    assert.equal(long.built, short.built, 'a longer statement formats no more dates through toLocale*String');
    // The words are the ones toLocale*String gave: the line's clock span and zone, the day's heading, the call count.
    const first = new Date('2026-09-10T08:00:00Z'), last = new Date('2026-09-10T09:10:00Z');
    const clock = {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'};
    assert.ok(long.html.includes(`${first.toLocaleTimeString(undefined, clock)}–${last.toLocaleTimeString(undefined, {...clock, timeZoneName: 'short'})}`));
    const [y, m, dd] = '2026-09-10'.split('-').map(Number);
    assert.ok(long.html.includes(new Date(y, m - 1, dd).toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'})));
    assert.ok(long.html.includes(`${(1234).toLocaleString('en-US')} model calls`));
    // Counts go through one NumberFormat too (Number#toLocaleString('en-US') built one per call).
    assert.doesNotMatch(source, /const num = \(n\) => \(n == null \? '—' : Number\(n\)\.toLocaleString/);
  });

  test(`${name}: the first render takes the page's first read from the shell, once, and polls as before`, async () => {
    const f = frontend({fetchImpl: researchTransport()});
    f.location.pathname = '/research';
    f.window.__TAU_FIRST__ = [{url: '/api/runs', body: {...runsAnswer, totals: {tried: 41, passed: 4}, v: 'shell'}}];
    await f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/runs'), 0, 'no round trip for what the shell carried');
    assert.match(f.root.querySelector('#rfigs').innerHTML, /41/);
    assert.equal(f.window.__TAU_FIRST__.length, 0, 'taken once');
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.deepEqual(f.requests.filter(({path}) => path.startsWith('/api/runs')).map(({path}) => path), ['/api/runs?since=shell']);
    f.clearTimers();
  });

  test(`${name}: Research draws its loop card in its first render from the board the shell carries`, async () => {
    // Drawn a round trip after the session list, the card pushed the list down the screen (shell_reads.py
    // carries the board while the server keeps one).
    const board = {total: {runs: 2, explored: 10, gated: 4, passed: 1, cost_usd: 2, gate_reach_rate: 0.4, pipeline_death_share: 0.5}, days: []};
    const f = frontend({fetchImpl: researchTransport()});
    f.location.pathname = '/research';
    f.window.__TAU_FIRST__ = [{url: '/api/runs', body: {...runsAnswer, totals: {tried: 10, passed: 1}}}, {url: '/api/research/scoreboard?days=14', body: board}];
    await f.viewResearch();
    assert.match(f.root.querySelector('#rsimo').innerHTML, /Ideas tried/, 'the card is drawn with the list');
    await settle();
    assert.equal(asked(f, '/api/research/scoreboard'), 0, 'no round trip for what the shell carried');
    assert.equal(asked(f, '/api/runs'), 0);
    assert.equal(f.window.__TAU_FIRST__.length, 0, 'both taken once');
    f.clearTimers();
  });

  test(`${name}: Billing draws its figures from the read the shell carries for its time zone, and asks when the zone moved`, async () => {
    const bill = {configured: false, balance: 12.5, spent: 40, spent_7d: 3, spent_24h: 1, pace_days: 7, free_bonus: 20, topup_fee_pct: 5.5,
      cards: [], default_pm: null, auto_reload: false, min_run_balance: 1, spent_7d_by: {}, ledger: [], ledger_cut: false,
      math: {days: 30, start: 20, bought: 0, purchases: 0, other: 0, usage: 7.5, end: 12.5}};
    const tz = new Date().getTimezoneOffset();
    // The shell names the URL from the tau_tz cookie boot.js keeps (shell_reads.py): the page's own URL.
    let f = frontend({fetchImpl: (path) => path.startsWith('/api/billing') ? response(bill) : response({})});
    f.location.pathname = '/billing';
    f.window.__TAU_FIRST__ = [{url: '/api/billing?tz=' + tz, body: {...bill, balance: 31.25}}];
    await f.viewBilling(); await settle();
    assert.equal(asked(f, '/api/billing'), 0, 'no round trip for what the shell carried');
    assert.match(f.root.querySelector('#bfigs').innerHTML, /\$31\.25/);
    assert.equal(f.window.__TAU_FIRST__.length, 0, 'taken once');
    f.clearTimers();
    // The offset changed since the cookie was written (a clock change): another URL, so the page asks.
    f = frontend({fetchImpl: (path) => path.startsWith('/api/billing') ? response(bill) : response({})});
    f.location.pathname = '/billing';
    f.window.__TAU_FIRST__ = [{url: '/api/billing?tz=' + (tz + 60), body: {...bill, balance: 31.25}}];
    await f.viewBilling(); await settle();
    assert.deepEqual(f.requests.filter(({path}) => path.startsWith('/api/billing')).map(({path}) => path), ['/api/billing?tz=' + tz]);
    assert.match(f.root.querySelector('#bfigs').innerHTML, /\$12\.50/);
    f.clearTimers();
  });

  test(`${name}: Funds draws its figures from the read the shell carries, and polls as before`, async () => {
    // The shell carries it only while every cash figure is already in the server's memo (shell_reads.py).
    const book = (cash) => ({kalshi: {connected: false}, kalshi_dev: {connected: false}, demo: {capital: 1000, equity: 1001, realized: 1},
      paper: {cash, equity: cash, ledger: [{created_at: '2026-10-17T10:00:00Z', memo: 'Paper deposit', amount: 1000}]}});
    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response(book(1000)) : response({})});
    f.location.pathname = '/funds';
    f.window.__TAU_FIRST__ = [{url: '/api/funds', body: book(1234.5)}];
    await f.viewFunds(); await settle();
    assert.equal(asked(f, '/api/funds'), 0, 'no round trip for what the shell carried');
    assert.match(f.root.querySelector('#ffigs').textContent, /\$1,234\.50/);
    assert.equal(f.window.__TAU_FIRST__.length, 0, 'taken once');
    for (const tick of [...f.intervals.values()]) tick();
    await settle();
    assert.equal(asked(f, '/api/funds'), 1, 'the poll reads it fresh');
    assert.match(f.root.querySelector('#ffigs').textContent, /\$1,000\.00/);
    f.clearTimers();
  });

  // An account with Kalshi keys: the shell carries Funds' read without waiting on Kalshi (shell_reads.py), each
  // key's cash pending; the page draws it as checking, never $0, and asks for each book's cash on its own.
  const keyed = (over = {}) => ({
    kalshi: {connected: true, pending: true, balance: null, key_id: 'LIVE…1234', funding_url: 'https://kalshi.com/account/funding',
      closed_trades: 1, realized_pnl: -1.25, open_positions: 0, open_at_cost: 0, ...over.kalshi},
    kalshi_dev: {connected: true, pending: true, balance: null, key_id: 'DEVK…5678', copies_from: 100, ...over.kalshi_dev},
    demo: {capital: 1000, equity: 1003.5, realized: 3.5, closed_trades: 1, open_positions: 0, open_at_cost: 0},
    paper: {cash: 2001.75, equity: 2001.75, realized_pnl: 5.61, closed_trades: 2, open_positions: 0, open_at_cost: 0,
      ledger: [{created_at: '2026-10-17T10:00:00Z', memo: 'Paper deposit', amount: 1000}]},
  });
  const liveFig = (f) => f.root.querySelector('#ffigs').querySelectorAll('div.m')[0].textContent;
  const spot = (f, name) => f.root.querySelector(`[data-cash="${name}"]`).innerHTML;

  test(`${name}: Funds draws a pending Kalshi cash as checking, never $0, then fills each book's in from its own read`, async () => {
    let answerLive;
    const liveHeld = new Promise((resolve) => { answerLive = resolve; });
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/funds/cash?book=live') return liveHeld.then(() => response({book: 'live', connected: true, balance: 1234.56, balance_at: new Date().toISOString()}));
      if (path === '/api/funds/cash?book=demo') return response({book: 'demo', connected: true, balance: 500, balance_at: new Date().toISOString()});
      return response({});
    }});
    f.location.pathname = '/funds';
    f.window.__TAU_FIRST__ = [{url: '/api/funds', body: keyed()}];
    await f.viewFunds(); await settle();
    assert.equal(asked(f, '/api/funds'), 2, 'no /api/funds: the two cash reads only');
    assert.equal(asked(f, '/api/funds/cash?book=live'), 1);
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
    // Live is still on its way: a labelled placeholder, never $0, while the books from our own database are all there.
    assert.match(liveFig(f), /Kalshi cash\s*Checking…/);
    assert.doesNotMatch(liveFig(f), /\$0\.00|Unavailable/);
    assert.match(f.root.querySelector('#ffigs').textContent, /\$2,001\.75/);
    assert.match(f.root.querySelector('#ffigs').textContent, /\$1,003\.50/);
    assert.match(spot(f, 'live-cell'), /^Checking…$/);
    assert.match(spot(f, 'live-ok'), /checking your balance at Kalshi/);
    // Demo answered: its line is filled in place.
    assert.match(spot(f, 'demo-ok'), /Connected ✓<\/b> \(balance \$500\.00, read just now\)/);
    answerLive(); await settle();
    assert.match(liveFig(f), /Kalshi cash\s*\$1,234\.56/);
    assert.doesNotMatch(liveFig(f), /Checking/);
    assert.equal(spot(f, 'live-cell'), '$1,234.56');
    assert.match(spot(f, 'live-ok'), /Connected ✓/);
    assert.equal(asked(f, '/api/funds'), 2, 'the page itself is never read again for it');
    f.clearTimers();
  });

  test(`${name}: Funds shows an older Kalshi cash only with its age while it checks`, async () => {
    const f = frontend({fetchImpl: () => new Promise(() => {})});
    f.location.pathname = '/funds';
    const at = new Date(Date.now() - 5 * 60000).toISOString();
    f.window.__TAU_FIRST__ = [{url: '/api/funds', body: keyed({kalshi: {last_balance: 900, last_balance_at: at}, kalshi_dev: {last_balance: 0, last_balance_at: at}})}];
    await f.viewFunds(); await settle();
    assert.match(liveFig(f), /Kalshi cash\s*\$900\.00\s*Read 5m ago; checking Kalshi for the latest…/);
    assert.equal(spot(f, 'live-cell'), '$900.00, read 5m ago; checking…');
    // An old $0 demo figure is shown as old, and raises no "your demo account is empty" notice from it.
    assert.match(spot(f, 'demo-ok'), /balance \$0\.00, read 5m ago; checking for the latest…/);
    assert.doesNotMatch(spot(f, 'demo-ok'), /refuses demo orders/);
    f.clearTimers();
  });

  test(`${name}: Funds says in plain words when it couldn't check the Kalshi cash`, async () => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/funds/cash')
      ? response({error: 'Traceback (most recent call last): RuntimeError: kalshi read timed out'}, 500) : response({})});
    f.location.pathname = '/funds';
    f.window.__TAU_FIRST__ = [{url: '/api/funds', body: keyed()}];
    await f.viewFunds(); await settle();
    assert.match(liveFig(f), /Kalshi cash\s*Unavailable\s*Tau couldn’t check your Kalshi cash just now\. Reload in a minute to try again\./);
    assert.equal(spot(f, 'live-cell'), 'Couldn’t check it just now');
    assert.match(spot(f, 'demo-ok'), /Tau couldn’t check it just now\. Reload in a minute to try again\./);
    const page = f.root.querySelector('#ffigs').textContent + spot(f, 'live-ok') + spot(f, 'demo-ok');
    assert.doesNotMatch(page, /Traceback|RuntimeError|timed out|\$0\.00|Checking/);
    f.clearTimers();
  });

  test(`${name}: Funds takes the cash reads the shell started early (boot.js), once each`, async () => {
    const f = frontend({fetchImpl: () => response({book: 'live', connected: true, balance: 1})});
    f.location.pathname = '/funds';
    f.window.__TAU_FIRST__ = [{url: '/api/funds', body: keyed(), then: ['/api/funds/cash?book=live', '/api/funds/cash?book=demo']}];
    f.window.__TAU_EARLY__ = {
      '/api/funds/cash?book=live': Promise.resolve(response({book: 'live', connected: true, balance: 1234.56, balance_at: new Date().toISOString()})),
      '/api/funds/cash?book=demo': Promise.resolve(response({error: 'Traceback: RuntimeError'}, 500)),
    };
    await f.viewFunds(); await settle();
    assert.equal(asked(f, '/api/funds'), 0, 'no request: the page read and both cash reads were started by the shell');
    assert.match(liveFig(f), /Kalshi cash\s*\$1,234\.56/);
    assert.match(spot(f, 'demo-ok'), /Tau couldn’t check it just now/, 'an early read that failed reads as any failed one');
    assert.deepEqual(Object.keys(f.window.__TAU_EARLY__), [], 'taken once');
    // A later page never takes an early read: it asks for itself, and the rest are dropped.
    f.window.__TAU_EARLY__ = {'/api/funds/cash?book=live': Promise.resolve(response({book: 'live', connected: true, balance: 99}))};
    f.S.gen = 2;
    assert.equal((await f.api('/api/funds/cash?book=live')).balance, 1);
    assert.equal(f.window.__TAU_EARLY__, null);
    f.clearTimers();
  });

  test(`${name}: a full Funds read never waits on the follow-up, and the follow-up never paints over it`, async () => {
    let answerLive;
    const liveHeld = new Promise((resolve) => { answerLive = resolve; });
    const fresh = keyed({kalshi: {pending: undefined, balance: 2222, balance_at: new Date().toISOString()}, kalshi_dev: {pending: undefined, balance: 600}});
    const f = frontend({fetchImpl: (path) => path === '/api/funds/cash?book=live' ? liveHeld.then(() => response({book: 'live', connected: true, balance: 1111}))
      : path === '/api/funds' ? response(fresh) : new Promise(() => {})});
    f.location.pathname = '/funds';
    f.window.__TAU_FIRST__ = [{url: '/api/funds', body: keyed()}];
    await f.viewFunds(); await settle();
    for (const tick of [...f.intervals.values()]) tick();  // the poll reads it all afresh
    await settle();
    assert.match(liveFig(f), /\$2,222\.00/);
    answerLive(); await settle();
    assert.match(liveFig(f), /\$2,222\.00/, 'the older follow-up is dropped');
    f.clearTimers();
  });

  // The dashboard's shell read never waits on Kalshi either (shell_reads.py): its live cash comes pending, read
  // through the same /api/funds/cash follow-up as Funds', and the same words (cashFig) draw it.
  const keyedDash = (live = {}, demo = {}) => ({
    paper: {equity: 1001.6, cash: 1000, open_at_cost: 1.6, total_pnl: 1.6, closed_trades: 8, open_positions: 0,
      realized_pnl: 3.5, today_pnl: 0, running: 0, daily: []},
    live: {connected: true, pending: true, balance: null, funding_url: 'https://kalshi.com/account/funding', closed_trades: 0,
      open_positions: 0, open_at_cost: 0, realized_pnl: 0, today_pnl: 0, running: 0, ...live},
    demo: {equity: 1000, capital: 1000, realized_pnl: 0, closed_trades: 0, open_positions: 0, health: null, ...demo},
    deployments: [], open_positions: [], recent_closed: [], reconcile: [], freshness: {btc: 30, engine: 4},
    agents: {research_running: 0, research_queued: 0}, v: 'pending1'});
  const dashCash = (f) => {
    const box = [...f.root.querySelectorAll('div.m')].find((el) => /Kalshi cash/.test(el.textContent));
    return box ? box.textContent.replace(/\s+/g, ' ') : '';
  };
  const dashPage = (f) => f.root.querySelector('#boardbody').innerHTML + f.root.querySelector('#main').innerHTML;
  const dashFrontend = (transport) => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/track-record') ? response({modes: {}})
      : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : transport(path)});
    f.S.me.user.autopilot = false;
    f.S.ap = null; f.S.apAt = 0;
    f.location.pathname = '/';
    return f;
  };

  test(`${name}: the dashboard draws a pending Kalshi cash as checking, never $0, then fills it from its own read`, async () => {
    let answerLive;
    const liveHeld = new Promise((resolve) => { answerLive = resolve; });
    const f = dashFrontend((path) => path === '/api/funds/cash?book=live'
      ? liveHeld.then(() => response({book: 'live', connected: true, balance: 1234.56, balance_at: new Date().toISOString()})) : response({}));
    f.window.__TAU_FIRST__ = [{url: '/api/dashboard', body: keyedDash()}];
    await f.viewDashboard(); await settle();
    assert.equal(asked(f, '/api/dashboard'), 0, 'the shell carried the figures');
    assert.equal(asked(f, '/api/funds/cash?book=live'), 1);
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 0, 'no demo check waited on Kalshi');
    assert.match(dashCash(f), /Kalshi cash ?Checking… ?Asking Kalshi for your real cash now\./);
    assert.doesNotMatch(dashCash(f), /\$0\.00|Unavailable/);
    assert.match(dashPage(f), /\$1,001\.60/, 'the paper book is there at once');
    answerLive(); await settle();
    assert.match(dashCash(f), /Kalshi cash ?\$1,234\.56/);
    assert.doesNotMatch(dashCash(f), /Checking/);
    assert.equal(asked(f, '/api/dashboard'), 0, 'the dashboard itself is never read again for it');
    f.clearTimers();
  });

  test(`${name}: the dashboard shows an older Kalshi cash only with its age while it checks`, async () => {
    const f = dashFrontend(() => new Promise(() => {}));
    const at = new Date(Date.now() - 5 * 60000).toISOString();
    f.window.__TAU_FIRST__ = [{url: '/api/dashboard', body: keyedDash({last_balance: 900, last_balance_at: at})}];
    await f.viewDashboard(); await settle();
    assert.match(dashCash(f), /Kalshi cash ?\$900\.00 ?Read 5m ago; checking Kalshi for the latest…/);
    f.clearTimers();
  });

  test(`${name}: the dashboard says in plain words when it couldn't check the Kalshi cash`, async () => {
    const f = dashFrontend((path) => path.startsWith('/api/funds/cash')
      ? response({error: 'Traceback (most recent call last): RuntimeError: kalshi read timed out'}, 500) : response({}));
    f.window.__TAU_FIRST__ = [{url: '/api/dashboard', body: keyedDash()}];
    await f.viewDashboard(); await settle();
    assert.match(dashCash(f), /Kalshi cash ?Unavailable ?Tau couldn’t check your Kalshi cash just now\. Reload in a minute to try again\./);
    assert.doesNotMatch(dashPage(f), /Traceback|RuntimeError|timed out|Checking/);
    assert.doesNotMatch(dashCash(f), /\$0\.00/);
    f.clearTimers();
  });

  test(`${name}: the dashboard takes the cash read the shell started early, and reads again once a demo check can be made`, async () => {
    const health = {code: 'demo_funds', need: 'demo funds', line: 'Demo isn’t trading: your Kalshi demo account has $0.00. Add demo funds on Kalshi’s demo site.',
      action: {label: 'Open Kalshi demo', href: 'https://demo.kalshi.co/'}};
    const full = {...keyedDash({pending: undefined, balance: 1234.56, balance_at: new Date().toISOString()}, {health}), v: 'full1'};
    const f = dashFrontend((path) => path.startsWith('/api/dashboard') ? response(full) : response({}));
    f.window.__TAU_FIRST__ = [{url: '/api/dashboard', body: keyedDash({}, {health_pending: true}),
      then: ['/api/funds/cash?book=live', '/api/funds/cash?book=demo']}];
    f.window.__TAU_EARLY__ = {
      '/api/funds/cash?book=live': Promise.resolve(response({book: 'live', connected: true, balance: 1234.56, balance_at: new Date().toISOString()})),
      '/api/funds/cash?book=demo': Promise.resolve(response({book: 'demo', connected: true, balance: 0})),
    };
    await f.viewDashboard(); await settle();
    assert.equal(asked(f, '/api/funds/cash'), 0, 'both cash reads were started by the shell');
    assert.deepEqual(Object.keys(f.window.__TAU_EARLY__), [], 'taken once');
    assert.match(dashCash(f), /Kalshi cash ?\$1,234\.56/);
    // The demo check waited on the demo cash: once that is read, the dashboard is read once more and says it.
    assert.equal(asked(f, '/api/dashboard'), 1);
    assert.match(dashPage(f), /Demo isn’t trading: your Kalshi demo account has \$0\.00/);
    f.clearTimers();
  });

  test(`${name}: a newer dashboard poll is never painted over by the cash follow-up`, async () => {
    let answerLive;
    const liveHeld = new Promise((resolve) => { answerLive = resolve; });
    const fresh = {...keyedDash({pending: undefined, balance: 2222, balance_at: new Date().toISOString()}), v: 'full2'};
    const f = dashFrontend((path) => path === '/api/funds/cash?book=live' ? liveHeld.then(() => response({book: 'live', connected: true, balance: 1111}))
      : path.startsWith('/api/dashboard') ? response(fresh) : new Promise(() => {}));
    f.window.__TAU_FIRST__ = [{url: '/api/dashboard', body: keyedDash()}];
    await f.viewDashboard(); await settle();
    for (const tick of [...f.intervals.values()]) tick();  // the poll reads it all afresh
    await settle();
    assert.match(dashCash(f), /\$2,222\.00/);
    answerLive(); await settle();
    assert.match(dashCash(f), /\$2,222\.00/, 'the older follow-up is dropped');
    f.clearTimers();
  });

  // /api/dashboard, /api/funds and the autopilot status never wait on Kalshi, whoever asks: an in-app visit and
  // every poll get a cash the server hadn't read in the last minute as pending, and the page fills it in from
  // /api/funds/cash, the one read that may wait on Kalshi.
  test(`${name}: an in-app dashboard visit and each poll fill a pending Kalshi cash from its own read`, async () => {
    const at = new Date(Date.now() - 70000).toISOString();
    let answer = {...keyedDash({last_balance: 900, last_balance_at: at}), v: 'p1'};
    let cash = 1234.56;
    const f = dashFrontend((path) => path.startsWith('/api/dashboard')
      ? response(path.includes('v=' + answer.v) ? {v: answer.v, same: true, marks: {}, unrealized: {}} : answer)
      : path === '/api/funds/cash?book=live' ? response({book: 'live', connected: true, balance: cash, balance_at: new Date().toISOString()})
        : response({}));
    await f.viewDashboard(); await settle();  // no shell read: the page asks /api/dashboard itself
    assert.equal(asked(f, '/api/dashboard'), 1);
    assert.equal(asked(f, '/api/funds/cash?book=live'), 1, 'the visit asked for the pending cash');
    assert.match(dashCash(f), /Kalshi cash ?\$1,234\.56/);
    assert.doesNotMatch(dashCash(f), /[Cc]hecking/);
    const tick = async () => { for (const t of [...f.intervals.values()]) t(); await settle(); };
    await tick();  // unchanged: "same", nothing more to ask
    assert.equal(asked(f, '/api/dashboard'), 2);
    assert.equal(asked(f, '/api/funds/cash?book=live'), 1);
    // A minute on, the memo ran out: the poll's answer is new (its version moved) and pending again.
    answer = {...keyedDash({last_balance: 1234.56, last_balance_at: at}), v: 'p2'};
    cash = 1500;
    await tick();
    assert.equal(asked(f, '/api/funds/cash?book=live'), 2, 'one follow-up for the new pending answer');
    assert.match(dashCash(f), /Kalshi cash ?\$1,500\.00/);
    // A cash read since then: the poll's version moves and the page repaints it, with no follow-up.
    answer = {...keyedDash({pending: undefined, balance: 1600, balance_at: new Date().toISOString()}), v: 'k3'};
    await tick();
    assert.match(dashCash(f), /Kalshi cash ?\$1,600\.00/);
    assert.equal(asked(f, '/api/funds/cash?book=live'), 2);
    f.clearTimers();
  });

  test(`${name}: a demo check pending in a poll reads the demo cash once and the dashboard once more, never in a loop`, async () => {
    const pendingDemo = {...keyedDash({pending: undefined, balance: 10, balance_at: new Date().toISOString()}, {health_pending: true}), v: 'd1'};
    const f = dashFrontend((path) => path.startsWith('/api/dashboard') ? response({...pendingDemo, v: 'd' + asked(f, '/api/dashboard')})
      : path === '/api/funds/cash?book=demo' ? response({book: 'demo', connected: true, balance: 0}) : response({}));
    await f.viewDashboard(); await settle();
    // Still pending after the demo read (the server's memo missed it): read once more, then left to the poll.
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
    assert.equal(asked(f, '/api/dashboard'), 2);
    f.clearTimers();
  });

  test(`${name}: an in-app Funds visit and its poll fill each pending cash from its own read`, async () => {
    let n = 0;
    const f = frontend({fetchImpl: (path) => path === '/api/funds' ? response(keyed({kalshi: {last_balance: 900, last_balance_at: new Date(Date.now() - 70000).toISOString()}}))
      : path === '/api/funds/cash?book=live' ? response({book: 'live', connected: true, balance: 1000 + ++n, balance_at: new Date().toISOString()})
        : path === '/api/funds/cash?book=demo' ? response({book: 'demo', connected: true, balance: 500, balance_at: new Date().toISOString()}) : response({})});
    f.location.pathname = '/funds';
    await f.viewFunds(); await settle();
    assert.equal(asked(f, '/api/funds/cash?book=live'), 1);
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
    assert.match(liveFig(f), /Kalshi cash\s*\$1,001\.00/);
    for (const t of [...f.intervals.values()]) t();
    await settle();
    assert.equal(asked(f, '/api/funds/cash?book=live'), 2, 'the poll came pending too: asked again');
    assert.match(liveFig(f), /Kalshi cash\s*\$1,002\.00/);
    assert.doesNotMatch(liveFig(f), /[Cc]hecking/);
    f.clearTimers();
  });

  test(`${name}: an autopilot status whose idle line waits on the demo cash is read again once that cash is in, once`, async () => {
    const f = frontend({fetchImpl: (path) => path === '/api/autopilot/status' ? response({autopilot: true, mode: 'paper', idle: null, idle_pending: true})
      : path === '/api/funds/cash?book=demo' ? response({book: 'demo', connected: true, balance: 0}) : response({})});
    const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
    await f.refreshAutopilot(box); await settle();
    assert.equal(asked(f, '/api/funds/cash?book=demo'), 1);
    assert.equal(asked(f, '/api/autopilot/status'), 2, 'read again once the demo cash was in, and not again while still pending');
    f.clearTimers();
  });

  test(`${name}: past the passes the server judges, the since strip's counts read as at least that many`, async () => {
    const f = frontend({fetchImpl: () => response({})});
    const since = {at: '2026-10-19T08:00:00+00:00', first: false, books: {}, autopilot: {}, runs: {},
      passed: {n: 375, more: true, items: [{id: 9, title: 'Rain'}, {id: 8, title: 'Fade'}, {id: 7, title: 'Tails'}],
        not_cleared: [{id: 6, title: 'Gust', verdict: 'missed_final'}], not_cleared_n: 125}};
    const text = f.sinceStrip({since, deployments: []}, '#dash-deps');
    assert.match(text, /375\+ strategies passed: .*Tails<\/a>, <a href="\/strategies">372\+ more<\/a>/);
    assert.match(text, /Not cleared to trade: <a href="\/strategies\/6">Gust<\/a> \(missed the final test\), 124\+ more\./);
    // Every pass judged: exact counts, as before.
    const exact = f.sinceStrip({since: {...since, passed: {...since.passed, n: 120, more: undefined, not_cleared_n: 30}}, deployments: []}, '#dash-deps');
    assert.match(exact, /120 strategies passed: .*<a href="\/strategies">117 more<\/a>/);
    assert.match(exact, /29 more\./);
    assert.doesNotMatch(exact, /\+/);
    f.clearTimers();
  });

  test(`${name}: a carried read is used only for its own URL and only by the first page`, async () => {
    let f = frontend({fetchImpl: researchTransport()});
    f.location.pathname = '/research';
    f.window.__TAU_FIRST__ = [{url: '/api/deployments', body: {deployments: []}}];
    await f.viewResearch(); await settle();
    assert.equal(asked(f, '/api/runs'), 1, 'another URL: the page asks for its own');
    // The first page has gone (a later render): the carried read is dropped, never shown late.
    f.S.gen = 2;
    await f.api('/api/notifications');
    assert.equal(f.window.__TAU_FIRST__, null);
    f.clearTimers();

    // The dashboard asks with ?since= from its visit cookie; the shell names the same URL (shell_reads.py).
    const now = Math.floor(Date.now() / 1000), start = now - 4000;
    const dash = {paper: {equity: 1001.6, cash: 1000, open_at_cost: 1.6, total_pnl: 1.6, closed_trades: 8, open_positions: 0,
      realized_pnl: 3.5, today_pnl: 0, running: 0, daily: []}, live: {connected: false, closed_trades: 0, open_positions: 0, realized_pnl: 0},
    demo: {equity: 1000, capital: 1000, realized_pnl: 0, closed_trades: 0, open_positions: 0}, deployments: [], open_positions: [],
    recent_closed: [], reconcile: [], freshness: {btc: 30, engine: 4}, agents: {research_running: 0, research_queued: 0}, v: 'd1'};
    f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(dash);
      if (path.startsWith('/api/track-record')) return response({modes: {}});
      return researchTransport()(path);
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/';
    f.document.cookie = `tau_visit=${start}.${now - 60}`;  // back within half an hour: the visit goes on from its start
    // With the autopilot status its card draws from, above the figures, at the same time as them.
    const status = {autopilot: false, mode: 'off'};
    f.S.ap = null; f.S.apAt = 0;
    f.window.__TAU_FIRST__ = [{url: '/api/dashboard?since=' + start, body: dash}, {url: '/api/autopilot/status', body: status}];
    await f.viewDashboard(); await settle();
    assert.equal(asked(f, '/api/dashboard'), 0, 'the page asked for the URL the shell carried');
    assert.equal(asked(f, '/api/autopilot/status'), 0);
    assert.equal(f.S.ap, status);
    assert.match(f.root.querySelector('#boardbody').innerHTML + f.root.querySelector('#main').innerHTML, /\$1,001\.60/);
    f.clearTimers();
  });
}
