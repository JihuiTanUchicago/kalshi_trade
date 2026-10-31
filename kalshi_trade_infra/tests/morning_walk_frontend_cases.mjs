// Shared cases from a returning customer's morning look at Home, run against each bundle's offline harness (Tau and
// Meridian). Walk 2026-10-31 (a morning after 30 paper trades closed overnight, a morning with nothing closed, the
// autopilot on, off and paused for credits): the dashboard's 15s poll dropped keyboard focus to the page's body when a
// trade closed or a mark moved, the autopilot card's "Furthest on paper" link lost focus as its words changed, and the
// autopilot panel read "Today (UTC): paper realized $0.00" with no paper trade closed today, beside a dashboard that
// said none had. Display only: every figure is the server's, unchanged.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

// The interval whose tick asks for `prefix`: the page's own poll.
async function pollOf(f, prefix) {
  for (const tick of [...f.intervals.values()].reverse()) {
    const before = f.requests.length;
    await tick(); await settle();
    if (f.requests.slice(before).some(({path}) => path.startsWith(prefix))) return tick;
  }
  throw new Error('no poll asks for ' + prefix);
}

const ON = {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 0, passed_7d: 0}, paper_running: 1, demo_running: 0,
  live_running: 0, today_paper_pnl: 0, today_live_pnl: 0, focus: [], idle: null, story: [],
  paper_progress: {strategy_id: 12, title: 'Late-rush fade', trades: 31, trades_needed: 30, net_pnl: 4.5, strategies: 1}};

export function morningWalkCases({name, frontend, dashboard}) {
  const dep = (id) => ({id, strategy_id: 10 + id, title: 'Dep ' + id, market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
    stake: 5, max_positions: 4, realized_pnl: 3, unrealized_pnl: null, closed_trades: 8, open_positions: 1, curve: [], created_at: '2026-10-24T08:00:00Z'});
  const pos = (id, unreal) => ({id: 70 + id, deployment_id: id, title: 'Dep ' + id, ticker: `KXBTC15M-26OCT311645-${id}`, side: 'yes', qty: 2,
    entry_price: 0.4, entry_fee: 0.02, mode: 'paper', unrealized: unreal * id, value: 0.8 + unreal * id, mark_ts: '2026-10-31T12:00:00Z',
    opened_at: '2026-10-31T11:50:00Z', market_close_time: '2099-10-31T12:45:00Z'});

  test(`${name}: the dashboard's poll keeps keyboard focus on the same control when a trade closes or a mark moves`, async () => {
    let unreal = 0.1, closed = 8, realized = 3;
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) {
        const base = dashboard();
        return response({...base, deployments: [1, 2].map(dep), open_positions: [1, 2].map((id) => pos(id, unreal)),
          paper: {...base.paper, closed_trades: closed, realized_pnl: realized, today_pnl: realized, open_positions: 2}});
      }
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({messages: [], models: []});
    }});
    await f.viewDashboard(); await settle();
    const poll = await pollOf(f, '/api/dashboard');
    // Each harness records the focus a script hands an element; activeElement is set here as the browser would.
    const hold = (el) => { el.focus(); f.document.activeElement = el; };
    // Tau's open positions link each contract to Explore; Meridian's rows open as disclosures (kept by their own code).
    for (const [label, pick] of [
      ['strategy link', () => f.root.querySelector('#dash-deps a[href="/strategies/12"]')],
      ...(name === 'Tau' ? [['contract link', () => f.root.querySelector('#dash-open a[href="/explore?m=KXBTC15M-26OCT311645-2"]')]] : []),
      ['paper trades CSV link', () => f.root.querySelector('a.csv-link[href="/api/trades.csv?mode=paper"]')],
    ]) {
      const was = pick();
      assert.ok(was, label);
      hold(was);
      unreal += 0.05; closed += 1; realized += 0.5;
      await poll(); await settle();
      const now = pick();
      assert.equal(was.isConnected, false, label + ': the poll repainted it');
      assert.equal(now.focusOptions && now.focusOptions.preventScroll, true, label);
    }
    f.clearTimers();
  });

  test(`${name}: the autopilot card keeps focus on its "Furthest on paper" link when the link's words change`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response({...dashboard(), deployments: [dep(2)]});
      if (path === '/api/autopilot/status') return response(ON);
      return response({messages: [], models: []});
    }});
    f.S.me.user.autopilot = true; f.S.ap = ON;
    await f.viewDashboard(); await settle();
    f.S.ap = ON; f.paintDashAp();
    const link = () => f.root.querySelector('#dash-ap a[href="/strategies/12"]');
    const was = link();
    assert.ok(was, f.root.querySelector('#dash-ap').innerHTML);
    was.focus(); f.document.activeElement = was;
    f.S.ap = {...ON, paper_progress: {...ON.paper_progress, trades: 32}}; f.paintDashAp();
    const now = link();
    assert.notEqual(now, was, 'the card was redrawn');
    assert.equal(now.focusOptions && now.focusOptions.preventScroll, true);
    f.clearTimers();
  });

  test(`${name}: the autopilot panel says no paper trade closed today, not $0.00, and keeps a break-even day's figure`, async () => {
    const today = async (status) => {
      const f = frontend({fetchImpl: () => response({messages: [], models: []})});
      f.S.me.user.autopilot = true;
      const box = new (f.root.constructor)('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl>';
      await f.apUpdate(box, status); await settle();
      f.clearTimers();
      const html = box.querySelector('#apf-stats').innerHTML;
      return /<dt><span class="pnl-win">Today \(UTC\):<\/span> paper <span class="nobr">realized<button[^>]*data-glo="realized"[\s\S]*?<\/button><\/span><\/dt><dd[^>]*>(.*?)<\/dd>/.exec(html)[1];
    };
    // The server sends today_paper_slippage_estimate: null until a paper trade closes today (UTC).
    assert.equal(await today({...ON, today_paper_slippage_estimate: null}), 'No trades closed yet');
    // A trade closed today that broke even keeps its $0.00 (the estimate is there).
    assert.match(await today({...ON, today_paper_slippage_estimate: {pnl: -0.05, per_fill_cents: 0.5}}), /^\$0\.00 <small class="apf-note">paper, after Kalshi fees and the spread<\/small>/);
    assert.match(await today({...ON, today_paper_pnl: 2.4, today_paper_slippage_estimate: {pnl: 2.3, per_fill_cents: 0.5}}), /^\+\$2\.40 /);
    // Nothing on paper at all, and an older server with no estimate field, read as before.
    assert.equal(await today({...ON, paper_running: 0, today_paper_slippage_estimate: null}), 'Nothing on paper');
    assert.match(await today(ON), /^\$0\.00 /);
  });
}
