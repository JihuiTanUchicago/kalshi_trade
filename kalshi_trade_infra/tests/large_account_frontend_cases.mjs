// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): a customer who stayed six
// months. Walked 2026-10-30 on a seeded account (200 research sessions, 3,000 closed trades, a strategy whose backtest
// made $1,584): the Research list said "50 sessions" over the newest 50 of 200 and offered no way to the rest; a
// strategy page's equity chart cut its y-axis labels at the left edge (",584.53"); its return on capital read
// "+1582.3%" beside "$1,582.29".
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 8; i++) await flush(); };
const plain = (html) => html.replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&').replace(/⁠/g, '');
const run = (id, seq) => ({id, seq, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea ' + seq,
  hypotheses_tried: 9, strategies_passed: 1, spent_usd: 0.5, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit'});
const counts = {research_running: 0, research_queued: 0, research_paused: 0};

export function largeAccountCases({name, frontend, detailStrategy, strategyFrontend}) {
  test(`${name}: the Research list says how many of the user's sessions it holds, and shows older ones on request`, async () => {
    const newest = Array.from({length: 50}, (_, k) => run(400 - k, 200 - k));  // ids 400..351, Sessions 200..151
    const asked = [];
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs?before=')) {
        asked.push(path);
        const before = +path.split('=')[1];
        const page = Array.from({length: 50}, (_, k) => run(before - 1 - k, before - 201 - k));
        return response({runs: page, more: before > 301});
      }
      if (path.startsWith('/api/runs')) return response({runs: newest, counts, policy: null, totals: {tried: 1705, passed: 16}, v: 'v1', own_total: 200});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const count = () => plain(f.root.querySelector('#rcount').innerHTML).trim();
    assert.equal(count(), name === 'Tau' ? '50 of 200 sessions' : '50 of 200');
    const host = f.root.querySelector('#runs-older');
    let btn = host.querySelector('button[data-older]');
    assert.ok(btn, 'a "Show older sessions" button under the newest 50');
    assert.match(btn.textContent, /Show older sessions/);
    assert.equal(btn.getAttribute('data-older'), '351', 'it asks for the sessions before the oldest one shown');
    await host.listeners.get('click')({target: btn}); await settle();
    assert.deepEqual(asked, ['/api/runs?before=351']);
    assert.equal(f.root.querySelector('#runs').children.length, 100, 'the older 50 are listed under the newest');
    assert.equal(count(), name === 'Tau' ? '100 of 200 sessions' : '100 of 200');
    // The list's poll keeps them: its answer holds only the newest 50.
    [...f.intervals.values()].at(-1)(); await settle();
    assert.equal(f.root.querySelector('#runs').children.length, 100);
    btn = host.querySelector('button[data-older]');
    assert.equal(btn && btn.getAttribute('data-older'), '301');
    // The server says no more: the button goes.
    await host.listeners.get('click')({target: btn}); await settle();
    assert.equal(f.root.querySelector('#runs').children.length, 150);
    assert.equal(host.querySelector('button[data-older]'), null);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: a list that holds every session offers no older page, and counts as before`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs: [run(9, 2), run(8, 1)], counts, policy: null, totals: {tried: 18, passed: 2}, v: 'v1', own_total: 2});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    assert.equal(plain(f.root.querySelector('#rcount').innerHTML).trim(), name === 'Tau' ? '2 sessions' : '2');
    assert.equal(f.root.querySelector('#runs-older').querySelector('button'), null);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: a strategy page's chart fits its y-axis labels over $1,000, and its return reads "+1,582.3%"`, async () => {
    const oos = {pnl: 1582.29, trades: 1623, win_rate: .58, fees: 81.15, profit_factor: 1.69, max_drawdown: 2.2, sharpe: 1.6, roi: 15.8229, days: 60};
    const f = strategyFrontend(detailStrategy({status: 'backtest-only', experiment: null, out_of_sample: oos,
      in_sample: {...oos, pnl: 2215.21, trades: 4870}, recent_trades: [], capital: 100,
      equity: [[1000, 0], [2000, 792.27], [3000, 1584.53]]}), () => response({}));
    await f.viewStrategy(42); await settle();
    const main = f.root.querySelector('#main').innerHTML, figs = plain(f.root.querySelector('#figs').innerHTML);
    assert.match(figs, /Return on capital\s+\+1,582\.3%/);
    assert.doesNotMatch(figs, /1582\.3%/);
    const tick = main.match(/<text x="([\d.]+)" y="[\d.]+" text-anchor="end">\$1,584\.53<\/text>/);
    assert.ok(tick, 'the top tick is drawn');
    // Right-aligned at x, ~6.5 units a character at 11px: it must start inside the chart.
    assert.ok(+tick[1] >= '$1,584.53'.length * 6.5, `the top tick ends at x=${tick[1]}, too close to the left edge`);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: a chart whose labels fit keeps its 52-unit gutter, and pct groups thousands`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const small = f.equityChart([[1000, 0], [2000, 5], [3000, 12]], null, null, {width: 760, fit: true});
    assert.match(small, /<text x="44" y="[\d.]+" text-anchor="end">\$12\.00<\/text>/);
    const unfit = f.equityChart([[1000, 0], [3000, 1584.53]], null, null, {width: 760});
    assert.match(unfit, /<text x="44" y="[\d.]+" text-anchor="end">\$1,584\.53<\/text>/, 'without fit, the chart is drawn as before');
  });
}
