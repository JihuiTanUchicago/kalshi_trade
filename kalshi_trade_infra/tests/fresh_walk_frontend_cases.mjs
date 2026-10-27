// Shared cases from a brand-new Bitcoin trader's first hour, run against each bundle's offline harness (Tau
// and Meridian): the autopilot panel says what it is doing once, not twice in a row.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

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
        return ts.length ? ts.map((t) => t.textContent).filter(Boolean).join(' · ') : el.textContent; };
      assert.deepEqual(BOXES.map(sub), admin ? ['app.worker · hypotheses', 'honest, out-of-sample', 'simulated fills', 'real Kalshi orders']
        : ['your research sessions', 'your strategies', 'your paper strategies', 'your live and demo']);
      assert.equal(metric('agents'), '0 running · 0 queued · 1 done');
      assert.equal(metric('backtest'), '3 strategies tested');
      assert.equal(sub('db'), 'RDS MySQL', 'a box of the system itself is the system’s');
      f.root.querySelector('.sys-node[data-id="backtest"]').dispatchEvent({type: 'click'});
      const detail = f.root.querySelector('#sys-detail').innerHTML;
      if (admin) assert.doesNotMatch(detail, /Yours only/);
      else assert.match(detail, /3 strategies tested<\/p><p class="hint">Yours only: other users’ aren’t counted here\.<\/p>/);
      f.clearTimers();
    }
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
}
