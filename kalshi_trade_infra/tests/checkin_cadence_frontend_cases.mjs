// Shared cases, run against each bundle's offline harness (Tau and Meridian): "the autopilot puts it on paper at
// its next check-in" said nothing of when. The next check-in has no time anyone can promise (the worker's heartbeat
// runs on its own timer, skips a user it just reviewed, waits for a free worker and spaces idle users out), so
// wherever that copy appears it carries the status's usual cadence (checkin_every_min) and how long ago the last
// one ran, follows each status read, and says nothing while no check-in is coming or the status isn't read.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const AT = '2026-10-28T04:30:00Z';
const ago = (m) => new Date(Date.now() - m * 60000).toISOString();
const ap = (o) => ({autopilot: true, mode: 'paper', research: {tested_7d: 2, passed_7d: 1, active: []}, live_running: 0, demo_running: 0,
  paper_running: 0, story: [], checkin_every_min: 10, last_review_at: ago(8), ...o});
const EIGHT = ' (usually every 10 min; last one 8 min ago)';
const spans = (f) => f.root.querySelectorAll('[data-ap-when]');
const texts = (f) => spans(f).map((n) => n.textContent);

export function checkinCadenceCases({name, frontend, detailStrategy, strategyFrontend, dashboard}) {
  const meridian = name === 'Meridian';

  test(`${name}: the strategy page says how often the autopilot checks in beside "at its next check-in", and follows the status`, async () => {
    const detail = {status: 'passed', why_failed: [], autopilot_paper: true, experiment: {classification: 'deployment_candidate', promoted: true,
      holdout: {classification: 'forward_validated', n_trades: 64, mean_net_return: 0.024, consumed: true}}};
    const f = strategyFrontend(detailStrategy(detail), () => response({}));
    f.S.me.user.autopilot = true; f.S.ap = ap();
    await f.viewStrategy(42); await flush();
    assert.match(f.root.querySelector('#strat-quick').innerHTML,
      /The autopilot is putting this on paper at its next check-in<span data-ap-when> \(usually every 10 min; last one 8 min ago\)<\/span>, so there is nothing for you to deploy\./);
    assert.ok(spans(f).length >= 2, 'the quick line and the next rung');
    // The next status read: a review under way says so, in every place at once.
    f.S.ap = ap({reviewing: true, last_review_at: ago(0)}); f.paintDashAp();
    assert.deepEqual([...new Set(texts(f))], [' (one is under way now)']);
    // Late, it says how late; it never promises "any minute now".
    f.S.ap = ap({last_review_at: ago(47)}); f.paintDashAp();
    assert.deepEqual([...new Set(texts(f))], [' (usually every 10 min; last one 47 min ago)']);
    // Paused by billing, or a server that doesn't send a cadence: no check-in is coming, so nothing is said.
    for (const o of [{billing_blocked: true}, {checkin_every_min: null}, {checkin_every_min: undefined}]) {
      f.S.ap = ap(o); f.paintDashAp();
      assert.deepEqual([...new Set(texts(f))], ['']);
    }
    // Switched off: the line hides and its cadence goes with it.
    f.S.ap = ap({autopilot: false, mode: 'off', checkin_every_min: null}); f.paintDashAp();
    for (const n of f.root.querySelectorAll('[data-ap-next]')) assert.equal(n.hidden, true);
    assert.deepEqual([...new Set(texts(f))], ['']);
    // Opened before the status is read: the place is there, empty, and fills on the first read.
    const g = strategyFrontend(detailStrategy(detail), () => response({}));
    g.S.me.user.autopilot = true; g.S.ap = null;
    await g.viewStrategy(42); await flush();
    assert.match(g.root.querySelector('#strat-quick').innerHTML, /next check-in<span data-ap-when><\/span>, so there/);
    g.S.ap = ap(); g.paintDashAp();
    assert.deepEqual([...new Set(texts(g))], [EIGHT]);
  });

  test(`${name}: a finished session's passed strategy and its ideas list say how often the autopilot checks in`, async () => {
    let status = ap();
    const strat = {id: 42, title: 'Momentum', status: 'passed', market: 'btc15m', direction: 'momentum', deployed: false, autopilot_next: true,
      in_sample: {pnl: 14.2, trades: 60}, out_of_sample: {pnl: 8.52, trades: 30, days: 12}};
    const view = async (runStatus) => {
      const f = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9')
        ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', brief: 1, status: runStatus, run_forever: runStatus === 'running' ? 1 : 0,
          hypotheses_tried: 2, strategies_passed: 1, created_at: AT, started_at: AT}, events: [],
          strategies: [strat, {id: 43, title: 'Fade', status: 'rejected', market: 'btc15m', direction: 'momentum'}]})
        : path === '/api/autopilot/status' ? response(status) : response({})});
      f.S.me.user.autopilot = true; f.S.ap = status;
      await f.viewRun(9); await settle(); f.clearTimers();
      return f;
    };
    const f = await view('succeeded');
    assert.match(f.root.querySelector('#runnext').innerHTML,
      /The autopilot puts it on paper itself at its next check-in<span data-ap-when> \(usually every 10 min; last one 8 min ago\)<\/span>, so there is nothing for you to deploy\./);
    if (!meridian) {
      // Tau's Ideas tested list.
      assert.match(f.root.querySelector('#runideas').innerHTML,
        /<span class="ri-why">The autopilot puts it on paper at its next check-in<span data-ap-when> \(usually every 10 min; last one 8 min ago\)<\/span><\/span>/);
    }
    status = ap({last_review_at: ago(3 * 60)}); f.S.ap = status; f.paintDashAp();
    assert.deepEqual([...new Set(texts(f))], [' (usually every 10 min; last one 3 hours ago)']);
    if (meridian) {
      // Meridian's session list, under the strategy's title, while the session runs.
      status = ap();
      const g = await view('running');
      assert.deepEqual(g.root.querySelector('#run-artifacts').querySelectorAll('.slip-next').map((el) => el.innerHTML),
        [`The autopilot puts it on paper at its next check-in<span data-ap-when>${EIGHT}</span>`]);
    }
  });

  test(`${name}: the dashboard card says how often the autopilot checks in, beside a strategy waiting for one and its last check-in`, async () => {
    const line = 'Nothing is on paper yet: Momentum cleared every check, and the next review puts it on paper.';
    const status = ap({idle: {code: 'to_deploy', line}});
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(dashboard());
      if (path === '/api/autopilot/status') return response(status);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      return response({});
    }});
    f.S.me.user.autopilot = true; f.S.ap = status;
    await f.viewDashboard(); await flush();
    f.S.ap = status; f.paintDashAp();
    const card = () => f.root.querySelector('#dash-ap').innerHTML;
    assert.match(card(), /the next review puts it on paper\. <span class="ap-when">Check-ins: usually every 10 min; last one 8 min ago\.<\/span>/);
    assert.match(card(), /<dt>Last check-in<\/dt><dd>8m ago <small>usually every 10 min<\/small><\/dd>/);
    // Without a cadence the card reads as it did.
    f.S.ap = ap({idle: {code: 'to_deploy', line}, checkin_every_min: null}); f.paintDashAp();
    assert.doesNotMatch(card(), /Check-ins|usually every/);
    assert.match(card(), /<dt>Last check-in<\/dt><dd>8m ago<\/dd>/);
    f.clearTimers();
  });
}
