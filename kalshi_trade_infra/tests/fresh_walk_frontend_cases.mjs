// Shared cases from a brand-new Bitcoin trader's first hour, run against each bundle's offline harness (Tau
// and Meridian): the autopilot panel says what it is doing once, not twice in a row.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
// The bundles' separator (SEP in app.js and app.meridian.js; test_separator_line_start.mjs): a no-break space, "·", a space.
const SEP = '\u00a0\u00b7 ';

const REVIEWING = "Right now it's reviewing the markets to pick its next move. Each move shows up in its activity feed.";
const FRESH_ON = {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 0, passed_7d: 0}, paper_running: 0, demo_running: 0,
  live_running: 0, today_paper_pnl: 0, today_live_pnl: 0, reviewing: true, focus: ['btc'],
  idle: {code: 'reviewing', line: "Nothing is on paper yet: no strategy has passed its research tests. It's reviewing the markets to pick its next move.", action: null},
  story: [REVIEWING, 'It sticks to the focus you set: Bitcoin.',
    'Nothing trades real money until a strategy makes money on paper over at least 30 trades from 20 separate events and 48 hours, and you turn on live autopilot.']};

export function freshWalkCases({name, frontend, dashboard}) {
  const panel = async (status) => {
    const f = frontend({fetchImpl: () => response({messages: [], models: []})});
    f.S.me.user.autopilot = true;
    const box = new (f.root.constructor)('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl>';
    await f.apUpdate(box, status); await settle();
    f.clearTimers();
    return box;
  };
  const storyText = (box) => box.querySelectorAll('#apf-story p').map((p) => p.textContent.replace(/&#39;/g, "'"));

  // Right after a new user switched it on, the panel's lead line ended "It's reviewing the markets to pick its next
  // move." and the next line began "Right now it's reviewing the markets to pick its next move."
  test(`${name}: the autopilot panel says what it is doing right now once, under the line on why nothing is on paper`, async () => {
    const lines = storyText(await panel(FRESH_ON));
    assert.equal(lines.join(' ').split('pick its next move').length - 1, 1, lines.join('\n'));
    assert.deepEqual(lines.slice(0, 3), [FRESH_ON.idle.line, 'Each move shows up in its activity feed.', 'It sticks to the focus you set: Bitcoin.']);
    // An idle line that doesn't say it keeps the story's first line whole.
    const other = {...FRESH_ON, idle: {code: 'waiting', line: 'No trades right now: Fade is waiting for a contract that fits its entry rules.', action: null}};
    assert.equal(storyText(await panel(other))[1], REVIEWING);
    // With no idle line, the story is as the server sent it.
    assert.deepEqual(storyText(await panel({...FRESH_ON, idle: null})), FRESH_ON.story);
  });

  // A new account's autopilot showed "$0.00" for a paper P&L it had never had: "Paper P&L, realized all time $0.00"
  // on the dashboard card, "Paper realized today (UTC) $0.00" in the panel, and "Autopilot’s paper P&L $0.00 · 0
  // closed trades" in its week once research had spent credits. Each says there is none yet; a used book shows its figure.
  test(`${name}: a new account's autopilot says its paper P&L is none yet, not $0.00`, async () => {
    const book = (paper) => ({...dashboard(), paper: {...dashboard().paper, ...paper}});
    const week = {research_credits: 1.37, checkin_credits: 0, tested: 3, passed: 0, not_cleared: 0, paper_started: 0,
      paper_trades: 0, paper_pnl: 0, card_charged: false};
    const card = async (paper, status) => {
      const f = frontend({fetchImpl: (path) => {
        if (path === '/api/dashboard' || path.startsWith('/api/dashboard?')) return response(book(paper));
        if (path === '/api/autopilot/status') return response(status);
        return response({messages: [], models: []});
      }});
      f.S.me.user.autopilot = true; f.S.ap = status;
      await f.viewDashboard(); await settle();
      f.S.ap = status; f.paintDashAp();
      const html = f.root.querySelector('#dash-ap').innerHTML;
      f.clearTimers();
      return html;
    };
    const fresh = await card({closed_trades: 0, realized_pnl: 0, total_pnl: 0, today_pnl: 0, open_positions: 0}, {...FRESH_ON, week});
    assert.match(fresh, /<dt>Paper P&amp;L, realized all time<\/dt><dd>None yet <small>no paper trade has closed<\/small><\/dd>/);
    assert.match(fresh, /<dt>Autopilot’s paper P&amp;L<\/dt><dd>None yet <small>none of its paper trades has closed<\/small><\/dd>/);
    assert.doesNotMatch(fresh, /\$0\.00/);
    const used = await card({closed_trades: 4, realized_pnl: 1.32, total_pnl: 1.32, today_pnl: 1.32, open_positions: 0},
      {...FRESH_ON, paper_running: 1, week: {...week, paper_started: 1, paper_trades: 4, paper_pnl: 1.32}});
    assert.match(used, /<dt>Paper P&amp;L, realized all time<\/dt><dd><span class="gain">\+\$1\.32<\/span> <small>/);
    assert.match(used, /<dt>Autopilot’s paper P&amp;L<\/dt><dd><span class="pos">\+\$1\.32<\/span> <small>paper, not real money, [^<]*4 closed trades<\/small>/);

    const today = async (status) => /<dt>Paper realized today \(UTC\)<\/dt><dd[^>]*>(.*?)<\/dd>/.exec((await panel(status)).querySelector('#apf-stats').innerHTML)[1];
    assert.equal(await today(FRESH_ON), 'Nothing on paper');
    // A running paper strategy's day is a figure, and it says which money it is and that fees are in, as the dashboard
    // card's paper P&L does: a bare "$0.00" beside "Furthest on paper ... net on them" said neither.
    assert.equal(await today({...FRESH_ON, paper_running: 1}), '$0.00 <small class="apf-note">paper, after Kalshi fees and the spread</small>');
    assert.equal(await today({...FRESH_ON, today_paper_pnl: -0.5}), '−$0.50 <small class="apf-note">paper, after Kalshi fees and the spread</small>');
    const live = /<dt>Live realized today \(UTC\)<\/dt><dd[^>]*>(.*?)<\/dd>/.exec((await panel({...FRESH_ON, autopilot_live: true, today_live_pnl: -2})).querySelector('#apf-stats').innerHTML)[1];
    assert.equal(live, '−$2.00 <small class="apf-note">real money, after Kalshi fees</small>');
  });

  // The System page is in every customer's menu, and its research, backtest and engine boxes read every user's rows:
  // "7 strategies tested" and "1 running · 1 queued · 2 done" beside a customer's one session. The server now counts
  // a customer's own (`mine`), and each such box says so under its name; the operator's still count every user's.
  test(`${name}: a customer's System boxes say they count the customer's own; the operator's count every user's`, async () => {
    const nodes = (mine) => ({agents: {running: 0, queued: 0, done: 1, ...mine}, backtest: {strategies: 3, ...mine},
      sim_engine: {age: 20, paper: 1, ...mine}, live_engine: {age: 20, live: 0, demo: 0, ...mine}, web: {up: true}, db: {rows: 10, size_mb: 5}});
    const BOXES = ['agents', 'backtest', 'sim_engine', 'live_engine'];
    for (const admin of [false, true]) {
      const f = frontend({fetchImpl: (path) => (path === '/api/admin/system' ? response({nodes: nodes(admin ? {} : {mine: true}), events: [], now: '2026-10-27T16:00:00Z'}) : response({}))});
      f.S.me.is_admin = admin;
      await f.viewSystem(); await settle();
      const sub = (id) => f.root.querySelector(`[data-s="${id}"]`).textContent;
      // Tau sets the research box's count on two lines (tspans), read here as the one line they make.
      const metric = (id) => { const el = f.root.querySelector(`[data-m="${id}"]`), ts = el.querySelectorAll('tspan');
        return ts.length ? ts.map((t) => t.textContent).filter(Boolean).join(' · ') : el.textContent; };
      assert.deepEqual(BOXES.map(sub), admin ? ['app.worker · hypotheses', 'honest, out-of-sample', 'simulated fills', 'real Kalshi orders']
        : ['your research sessions', 'your strategies', 'your paper strategies', 'your live and demo']);
      assert.equal(metric('agents'), '0 running · 0 queued · 1 done');
      assert.equal(metric('backtest'), '3 strategies tested');
      assert.equal(sub('db'), 'one source of truth', 'a box of the system itself is the system’s');
      f.root.querySelector('.sys-node[data-id="backtest"]').dispatchEvent({type: 'click'});
      const detail = f.root.querySelector('#sys-detail').innerHTML;
      if (admin) assert.doesNotMatch(detail, /Yours only/);
      else assert.match(detail, /3 strategies tested<\/p><p class="hint">Yours only: other users’ aren’t counted here\.<\/p>/);
      f.clearTimers();
    }
  });

  // Walk 2026-10-27 at 390px and 1280px, both themes: the Database box read "3 MB · 0 rows" (the row count is the
  // database's own estimate, 0 for a new or small table) under "RDS MySQL", and Kalshi, Coinbase, Claude and Stripe
  // each read "connected" with a green dot, though the page reads none of them. The boxes name no cloud product,
  // a count shows as "about N" once it is big enough to mean something, an outside service's box counts what Tau
  // stored from it or says nothing, and its dot follows the collector that reads it (grey when there is none).
  test(`${name}: the System boxes name no cloud product, count rows as "about N" only when it means something, and never claim "connected"`, async () => {
    const open = async (nodes) => {
      const f = frontend({fetchImpl: (path) => (path === '/api/admin/system' ? response({nodes, events: [], now: '2026-10-27T16:00:00Z'}) : response({}))});
      await f.viewSystem(); await settle();
      return f;
    };
    const EXT = {kalshi: {kind: 'ext', series: 0, markets: 0}, coinbase: {kind: 'ext'}, bedrock: {kind: 'ext'}, stripe: {kind: 'ext'}};
    const small = await open({...EXT, db: {rows: 0, size_mb: 3}, web: {up: true}, forward: {age: null, rows: 0, unit: 'quote rows'},
      cb_coll: {age: 400, rows: 120, unit: 'candles'}, features: {age: 20, rows: 0, unit: 'feature rows'}});
    const text = (f, id, k) => f.root.querySelector(`[data-${k}="${id}"]`).textContent;
    const st = (f, id) => f.root.querySelector(`.sys-node[data-id="${id}"]`).getAttribute('data-st');
    const label = (f, id) => f.root.querySelector(`.sys-node[data-id="${id}"] .t`).textContent;
    assert.equal(text(small, 'db', 'm'), '3 MB', 'an estimate of 0 rows is left out');
    assert.equal(text(small, 'forward', 'm'), 'not seen yet');
    assert.equal(text(small, 'cb_coll', 'm'), '7m ago', '120 is no count to show');
    assert.equal(text(small, 'features', 'm'), '20s ago');
    for (const id of ['kalshi', 'coinbase', 'bedrock', 'stripe']) assert.equal(text(small, id, 'm'), '', `${id} says nothing it can't show`);
    // Kalshi's book comes in through the forward collector (no heartbeat: grey), Coinbase's through its collector
    // (stale: grey, not red, as the page can't say whose end stopped); nothing on the page reads Claude or Stripe.
    assert.deepEqual(['kalshi', 'coinbase', 'bedrock', 'stripe'].map((id) => st(small, id)), ['idle', 'idle', 'idle', 'idle']);
    assert.equal(label(small, 'bedrock'), 'Claude');
    small.clearTimers();

    const big = await open({...EXT, kalshi: {kind: 'ext', series: 14, markets: 1234567}, db: {rows: 987654321, size_mb: 130000},
      web: {up: true}, forward: {age: 20, rows: 123456789, unit: 'quote rows'}, cb_coll: {age: 40, rows: 2345678, unit: 'candles'},
      features: {age: 100, rows: 54321, unit: 'feature rows'}});
    assert.equal(text(big, 'db', 'm'), `127 GB${SEP}about 988M rows`);
    assert.equal(text(big, 'forward', 'm'), `about 123M quotes${SEP}20s ago`);
    assert.equal(text(big, 'cb_coll', 'm'), `about 2.3M candles${SEP}40s ago`);
    assert.equal(text(big, 'features', 'm'), `about 54k rows${SEP}2m ago`);
    assert.equal(text(big, 'kalshi', 'm'), `1.2M markets${SEP}14 series`);
    assert.deepEqual(['kalshi', 'coinbase', 'bedrock', 'stripe'].map((id) => st(big, id)), ['live', 'live', 'idle', 'idle']);
    // Every box's lines fit it: about 5 units a character at the map's narrow face, 12 in from the left.
    for (const g of big.root.querySelectorAll('.sys-node')) {
      const w = +g.querySelector('rect').getAttribute('width');
      for (const t of g.querySelectorAll('text')) {
        const line = t.querySelectorAll('tspan').length ? t.querySelectorAll('tspan').map((x) => x.textContent).sort((a, b) => b.length - a.length)[0] : t.textContent;
        assert.ok(12 + line.length * 5 <= w, `"${line}" in the ${w}-wide ${g.dataset.id} box`);
      }
    }
    // Neither the boxes nor any box's details name the cloud product, the database engine or the server's module.
    const said = [];
    for (const g of big.root.querySelectorAll('.sys-node')) {
      said.push(g.querySelector('.t').textContent, g.querySelector('.s').textContent, g.querySelector('.m').textContent);
      g.dispatchEvent({type: 'click'});
      said.push(big.root.querySelector('#sys-detail').innerHTML);
    }
    assert.doesNotMatch(said.join(' | '), /Bedrock|Amazon|AWS|RDS|MySQL|app\.server|SPA\b|connected/);
    big.clearTimers();
  });

  // Walk 2026-10-27 at 390px: the System map was a 640-wide picture scrolled sideways inside its frame, the research
  // box starting at x 537, off the screen. On a phone its boxes stack by stage, two to a row, in a map as wide as
  // the column (340, drawn at about its own size), with a short arrow from each stage into the next instead of
  // edges that would cross the stack. A desktop keeps the 900-wide signal-flow map and its edges.
  test(`${name}: on a phone the System map stacks its boxes by stage in a map the width of the column`, async () => {
    const nodes = {agents: {running: 12, queued: 30, done: 1204}, backtest: {strategies: 3}, db: {rows: 10, size_mb: 5}, web: {users: 2}};
    const open = async (narrow) => {
      const f = frontend({fetchImpl: (path) => (path === '/api/admin/system' ? response({nodes, events: [], now: '2026-10-27T16:00:00Z'}) : response({}))});
      f.window.matchMedia = (q) => ({matches: narrow && /max-width: 760px/.test(q), addEventListener() {}, removeEventListener() {}});
      await f.viewSystem(); await settle();
      return f;
    };
    const f = await open(true), svg = f.root.querySelector('#syssvg');
    const vb = svg.getAttribute('viewBox').split(' ').map(Number);
    assert.deepEqual(vb.slice(0, 3), [0, 0, 340]);
    assert.match(svg.getAttribute('class') || '', /\bsys-stack\b/);
    const boxes = f.root.querySelectorAll('.sys-node').map((g) => {
      const [x, y] = /translate\(([\d.]+),([\d.]+)\)/.exec(g.getAttribute('transform')).slice(1).map(Number), r = g.querySelector('rect');
      return {id: g.dataset.id, x, y, w: +r.getAttribute('width'), h: +r.getAttribute('height')};
    });
    assert.equal(boxes.length, 13);
    for (const b of boxes) {
      assert.ok(b.x >= 8 && b.x + b.w <= 340 - 8, `${b.id} at x ${b.x}, ${b.w} wide, inside the 340-wide map`);
      assert.ok(b.y >= 8 && b.y + b.h <= vb[3], `${b.id} inside the map's height`);
      assert.ok(b.w >= 150, `${b.id} keeps its desktop width, so its words fit as they do there`);
    }
    for (const a of boxes) for (const b of boxes) if (a !== b) {
      assert.ok(a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y, `${a.id} and ${b.id} don't overlap`);
    }
    // Stage by stage, down the screen: outside services, collectors, the database, research and the engines.
    const y = (id) => boxes.find((b) => b.id === id).y;
    assert.ok(y('stripe') < y('forward') && y('web') < y('db') && y('db') < y('agents'));
    assert.equal(f.root.querySelectorAll('.sys-edge').length, 0, 'no edges cross the stack');
    assert.equal(f.root.querySelectorAll('.sys-tier').length, 3, 'an arrow from each stage into the next');
    assert.deepEqual(f.root.querySelectorAll('.sys-tier-cap').map((t) => t.textContent), ['Outside services', 'Collectors and web server', 'Research and engines']);
    // The live counts still fill the boxes, the research box's on its two lines.
    assert.deepEqual(f.root.querySelector('[data-m="agents"]').querySelectorAll('tspan').map((t) => t.textContent.replace(/\u00a0/g, ' ')), ['12 running · 30 queued', '1,204 done']);
    f.clearTimers();
    const d = await open(false);
    assert.equal(d.root.querySelector('#syssvg').getAttribute('viewBox'), '0 0 900 540');
    assert.equal(d.root.querySelectorAll('.sys-edge').length, 16);
    assert.equal(d.root.querySelectorAll('.sys-tier').length, 0);
    d.clearTimers();
  });

  // Walk 2026-10-27: a box whose process has written no heartbeat yet (the server's age is null) read
  // "2 paper running · —" and "0 quote rows · —", a bare dash where the words go. It says "not seen yet", on the box
  // and in its detail panel; a box with a heartbeat still says how long ago it was.
  test(`${name}: a System box with no heartbeat yet says "not seen yet", not a bare dash`, async () => {
    const SEP = ' · ';
    const nodes = {sim_engine: {age: null, paper: 2, mine: true}, live_engine: {age: null, live: 0, demo: 1, mine: true},
      forward: {age: null, rows: 0, unit: 'quote rows'}, cb_coll: {age: 42, rows: 1200, unit: 'candles'}, web: {up: true}, db: {rows: 10, size_mb: 5}};
    const f = frontend({fetchImpl: (path) => (path === '/api/admin/system' ? response({nodes, events: [], now: '2026-10-27T16:00:00Z'}) : response({}))});
    await f.viewSystem(); await settle();
    const metric = (id) => f.root.querySelector(`[data-m="${id}"]`).textContent;
    assert.equal(metric('sim_engine'), `2 paper running${SEP}not seen yet`);
    assert.equal(metric('live_engine'), `0 live${SEP}1 demo${SEP}not seen yet`);
    // Under 1,000 rows the count drops out (#599), so the heartbeat words stand alone.
    assert.equal(metric('forward'), 'not seen yet');
    assert.equal(metric('cb_coll'), `about 1k candles${SEP}42s ago`);
    for (const id of ['sim_engine', 'live_engine', 'forward']) assert.doesNotMatch(metric(id), /—/);
    f.root.querySelector('.sys-node[data-id="sim_engine"]').dispatchEvent({type: 'click'});
    assert.match(f.root.querySelector('#sys-detail').innerHTML, /2 paper running · not seen yet<\/p>/);
    f.clearTimers();
  });

  // Meridian headed the page "Overview" (and its tab read "Overview · Tau") under a nav that says "Dashboard", beside
  // notes that send the reader to "the dashboard". The page says the nav's name, and so does the copy that names it.
  test(`${name}: the dashboard is headed by its nav name, "Dashboard", and the tab and notes say the same`, async () => {
    const f = frontend({fetchImpl: (path) => (path === '/api/dashboard' || path.startsWith('/api/dashboard?')) ? response(dashboard())
      : response({messages: [], models: []})});
    f.location.pathname = '/';
    await f.render(); await settle();
    const here = f.root.querySelector('.services [aria-current="page"]');
    assert.equal(here.textContent.replace(/<[^>]*>/g, '').trim(), 'Dashboard');
    assert.equal(f.root.querySelector('h1').textContent, 'Dashboard');
    assert.equal(f.document.title, `Dashboard${SEP}Tau`);
    assert.doesNotMatch(f.root.innerHTML, />Overview</);
    f.clearTimers();
    // The track record's instant-fill note (track_record_trust_frontend_cases) and Deploy's first-deploy note
    // name it "the Dashboard" too.
  });

  // Walk 2026-10-28, Explore at 390 and 1280, both themes: a multi-game combo's row and its market page were headed
  // "yes Denver,yes Boston,no Over 220.5 points scored", Kalshi's legs run together with no space after each comma.
  test(`${name}: a multi-game combo's title reads its legs apart, on Explore's list and on its market page`, async () => {
    const TICKER = 'KXMVESPORTSMULTIGAMEEXTENDED-S2026ABC123-DEF', RAW = 'yes Denver,yes Boston,no Over 220.5 points scored';
    const NICE = 'Yes Denver, yes Boston, no Over 220.5 points scored';
    const combo = {t: TICKER, s: 'KXMVESPORTSMULTIGAMEEXTENDED', ev: 'KXMVESPORTSMULTIGAMEEXTENDED-S2026ABC123', ti: RAW, su: '',
      bid: '0', ask: '0.0300', last: '0', v24: '40000', oi: '0', st: 'active'};
    const plainRow = {...combo, t: 'KXFEDDECISION-26DEC-H0', s: 'KXFEDDECISION', ev: 'KXFEDDECISION-26DEC', ti: 'Fed decision in Dec 2026?', su: 'Hike 0bps'};
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore?')
      ? response({at: new Date().toISOString(), total: 41233, shown: 2, matched: 2, page: 0, per: 40, sort: 'v24', markets: [combo, plainRow]})
      : response({})});
    f.location.pathname = '/explore'; f.location.search = '';
    await f.viewExplore(); await settle();
    const list = f.root.querySelector('#xrows').innerHTML;
    assert.ok(list.includes(NICE), list.slice(0, 400));
    assert.ok(!list.includes(RAW));
    assert.ok(list.includes(`Fed decision in Dec 2026?${SEP}Hike 0bps`));  // any other title as sent
    f.clearTimers();
    const g = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?')
      ? response({ticker: TICKER, series: combo.s, title: RAW, sub: '', status: 'active', yes_bid: '0', yes_ask: '0.03', last: '0',
        volume_24h: '40000', open_interest: '0', close_time: '2026-10-28T21:00:00Z', as_of: '2026-10-28T00:17:00Z', rules: '', period_min: 1,
        points: [], mine: {open: [], closed: []}})
      : response({})});
    g.location.pathname = '/explore'; g.location.search = '?m=' + encodeURIComponent(TICKER);
    await g.viewExplore(); await settle();
    assert.equal(g.root.querySelector('h1').textContent, NICE);
    assert.ok(!g.root.innerHTML.includes(RAW));
    g.clearTimers();
  });
}
