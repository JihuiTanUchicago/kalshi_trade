// Shared cases, run against each bundle's offline harness (Tau and Meridian): the words that say a research session's
// state, walked through a session's whole life (queued, running, silent, paused, finished with passes and with none,
// failed, stopped) on Home and Research at 390px and 1366px (audit 2026-10-31).
//   - A session that ended with no line logged read "Waiting for the first event — the agent is spinning up".
//   - Home said "1 agent researching" (running plus queued) over a Research page reading "Running 0 · Queued 1".
//   - The autopilot pill said "researching" with only a session queued, and the since-your-visit strip "1 running"
//     for a session Research listed as "Silent 5 min".
//   - A strategy whose session count is 0 read "—" on Tau and "0" on Meridian.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const plain = (html) => html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();

export function sessionStateCases({name, frontend, dashboard, detailStrategy, strategyFrontend}) {
  const run = (o) => ({id: 9, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Fade a late rush',
    hypotheses_tried: 3, strategies_passed: 0, spent_usd: 0.4, error: null, created_at: '2026-10-25T08:00:00Z',
    started_at: '2026-10-25T08:00:00Z', finished_at: '2026-10-25T09:00:00Z', stop_reason: 'limit', run_forever: 0, ...o});
  const emptyLog = async (r) => {
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/runs/9') ? response({run: r, events: [], strategies: []}) : response({})});
    await f.viewRun(9); await flush(); f.clearTimers();
    const ph = f.root.querySelector('#log .log-empty');
    return ph ? ph.textContent : null;
  };

  test(`${name}: an empty session log says the session's state; only one starting says the agent is spinning up`, async () => {
    const ended = 'No events were recorded for this session.';
    // Finished (with passes or none), failed on an error, stopped by you, interrupted: nothing logged, said plainly.
    for (const r of [run({strategies_passed: 1}), run(), run({status: 'failed', stop_reason: 'error', error: 'The session hit an unexpected error and stopped.'}),
      run({status: 'cancelled', stop_reason: 'user'}), run({status: 'stopped', stop_reason: 'interrupted', error: 'The session was interrupted before it tested an idea — start a new one.'})]) {
      const said = await emptyLog(r);
      assert.equal(said, ended, r.status);
      assert.doesNotMatch(said, /spinning up|Waiting/, r.status);
    }
    const live = {finished_at: null, stop_reason: null, spent_usd: 0, hypotheses_tried: 0};
    // Each theme's own words for a session starting, as before.
    assert.match(await emptyLog(run({...live, status: 'running'})), name === 'Tau' ? /^Waiting for the first event — the agent is spinning up\./ : /^Waiting for the first event\.$/);
    // Queued: waiting for an agent, not one spinning up.
    const queued = await emptyLog(run({...live, status: 'queued', started_at: null, wait: {state: 'queued', seconds: 20, overdue: false}}));
    assert.equal(queued, 'Waiting for the first event. The session starts once an agent is free.');
    // Silent past the reaper's limit (the server's wait), and paused: neither is spinning up.
    assert.equal(await emptyLog(run({...live, status: 'running', wait: {state: 'silent', seconds: 300, overdue: true}})), 'No events recorded yet.');
    assert.equal(await emptyLog(run({...live, status: 'paused'})), 'No events yet. Resume the session and its first event shows here.');
  });

  const home = async (agents) => {
    const base = dashboard();
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/dashboard') ? response({...base, agents})
      : path.startsWith('/api/track-record') ? response({modes: {}})
        : path === '/api/autopilot/status' ? response({autopilot: false, mode: 'off'}) : response({})});
    f.location.pathname = '/';
    await f.viewDashboard(); await settle();
    f.clearTimers();
    return [...f.root.querySelectorAll('a')].filter((a) => a.getAttribute('href') === '/research' && /researching|queued/.test(a.textContent)).map((a) => a.textContent.trim());
  };

  test(`${name}: Home counts research as the Research page does: a queued session is said apart, never "researching"`, async () => {
    // research_running is the server's count less any session silent past the reaper's limit (active_run_counts), as
    // the Research page's "Running" figure is: a silent session alone leaves Home saying nothing of research.
    assert.deepEqual(await home({research_running: 0, research_queued: 1, research_paused: 0, chat_active: 0}), ['1 session queued']);
    assert.deepEqual(await home({research_running: 2, research_queued: 1, research_paused: 0, chat_active: 0}), ['2 agents researching\u00a0· 1 session queued']);
    assert.deepEqual(await home({research_running: 1, research_queued: 0, research_paused: 0, chat_active: 0}), ['1 agent researching']);
    assert.deepEqual(await home({research_running: 0, research_queued: 0, research_paused: 0, chat_active: 0}), []);
  });

  test(`${name}: the autopilot pill and the since-your-visit strip don't call a queued or silent session running`, () => {
    const {apPillLabel, sinceRunsState, SEP} = frontend({fetchImpl: () => response({})}).window.TauCore;
    const m = {label: 'Autopilot' + SEP + 'paper'};
    const ap = (research) => ({autopilot: true, mode: 'paper', paper_running: 0, research});
    assert.equal(apPillLabel(ap({active: ['Bitcoin'], queued: ['Bitcoin']}), m), 'Autopilot' + SEP + 'session queued');
    assert.equal(apPillLabel(ap({active: ['Bitcoin', 'Ether'], queued: ['Ether']}), m), 'Autopilot' + SEP + 'researching');
    assert.equal(apPillLabel(ap({active: ['Bitcoin']}), m), 'Autopilot' + SEP + 'researching');  // an older status, no `queued`
    // The server counts a running session past the reaper's limit as `silent` (activity_since).
    assert.equal(plain(sinceRunsState({queued: 1, silent: 1}, 2, true)), '1 queued, 1 silent, follow them on Research');
    assert.equal(plain(sinceRunsState({silent: 1}, 1, true)), 'now silent, follow it on Research');
    assert.equal(plain(sinceRunsState({running: 1}, 1, true)), 'still running, follow it on Research');
  });

  test(`${name}: a strategy's Ideas tested reads its session's count, and "—" when that is unknown (null, or 0 not saved yet)`, async () => {
    const f = frontend({fetchImpl: () => response({})});
    const cell = (o) => f.strategySlip(detailStrategy({id: 46, title: 'Fade', ...o}), null, {}).match(/data-lab="Ideas tested"[^>]*>([^<]*)</)[1];
    assert.equal(cell({hypotheses_tried: 3}), '3');
    assert.equal(cell({hypotheses_tried: 1}), '1');
    assert.equal(cell({hypotheses_tried: 0}), '—');
    assert.equal(cell({hypotheses_tried: null}), '—');
    assert.equal(cell({hypotheses_tried: null, parent_id: 45}), 'Adjustment');
    // The strategy page's figure follows the same rule.
    for (const [n, want] of [[0, /Ideas tested\s*—\s*Count unavailable\./], [null, /Ideas tested\s*—\s*Count unavailable\./], [4, /Ideas tested\s*4\s*in the session that found it/]]) {
      const g = strategyFrontend(detailStrategy({status: 'passed', hypotheses_tried: n}), () => response({}));
      await g.viewStrategy(42); await flush();
      assert.match(g.root.querySelector('#figs').textContent, want, String(n));
      if (g.clearTimers) g.clearTimers();
    }
  });
}
