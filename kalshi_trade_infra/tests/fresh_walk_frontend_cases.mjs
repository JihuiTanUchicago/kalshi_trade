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
  // on the dashboard card, "Paper realized today (UTC) $0.00" in the panel, and "Autopilot's paper P&L $0.00 · 0
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
    assert.match(fresh, /<dt>Autopilot's paper P&amp;L<\/dt><dd>None yet <small>none of its paper trades has closed<\/small><\/dd>/);
    assert.doesNotMatch(fresh, /\$0\.00/);
    const used = await card({closed_trades: 4, realized_pnl: 1.32, total_pnl: 1.32, today_pnl: 1.32, open_positions: 0},
      {...FRESH_ON, paper_running: 1, week: {...week, paper_started: 1, paper_trades: 4, paper_pnl: 1.32}});
    assert.match(used, /<dt>Paper P&amp;L, realized all time<\/dt><dd><span class="gain">\+\$1\.32<\/span> <small>/);
    assert.match(used, /<dt>Autopilot's paper P&amp;L<\/dt><dd><span class="pos">\+\$1\.32<\/span> <small>paper, not real money, [^<]*4 closed trades<\/small>/);

    const today = async (status) => /<dt>Paper realized today \(UTC\)<\/dt><dd[^>]*>(.*?)<\/dd>/.exec((await panel(status)).querySelector('#apf-stats').innerHTML)[1];
    assert.equal(await today(FRESH_ON), 'Nothing on paper');
    assert.equal(await today({...FRESH_ON, paper_running: 1}), '$0.00');  // a running paper strategy's day is a figure
    assert.equal(await today({...FRESH_ON, today_paper_pnl: -0.5}), '−$0.50');
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
      const metric = (id) => f.root.querySelector(`[data-m="${id}"]`).textContent;
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
}
