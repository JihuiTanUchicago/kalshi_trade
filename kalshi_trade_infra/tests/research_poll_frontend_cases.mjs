// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the Research
// list's 5s poll sends back the version of its last answer, repaints nothing when the server says the
// list is unchanged, and when one session moved rewrites that session's row alone.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const run = (over) => ({id: 1, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea',
  hypotheses_tried: 9, strategies_passed: 1, spent_usd: 4.2, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit', ...over});
const counts = {research_running: 1, research_queued: 0, research_paused: 0};

export function researchPollCases({name, frontend}) {
  test(`${name}: the research list poll repaints nothing while the list is unchanged, then only the row that moved`, async () => {
    const runs = [run({id: 9, status: 'running', stop_reason: null, spent_usd: 0.5, created_at: '2026-10-26T08:00:00Z'}),
      run({id: 8, spent_usd: 1.25}), run({id: 7, spent_usd: 2})];
    let answer = {runs, counts, policy: null, totals: {tried: 27, passed: 3}, v: 'v1'};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response(answer);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const list = f.root.querySelector('#runs'), figs = f.root.querySelector('#rfigs');
    const row = (id) => list.children.find((el) => el.getAttribute('href') === `/research/${id}`);
    const before = {list: list.writes, figs: figs.writes, r8: row(8), r7: row(7)};
    assert.ok(before.r8 && before.r7, 'each finished session is a row of its own');
    assert.match(before.r8.innerHTML, /\$1\.25/);
    const poll = [...f.intervals.values()].at(-1);
    const asked = () => f.requests.filter(({path}) => path.startsWith('/api/runs')).at(-1).path;

    // Unchanged: the server answers "same"; the page sends back the version and rewrites nothing.
    answer = {v: 'v1', same: true};
    await poll(); await settle();
    assert.equal(asked(), '/api/runs?since=v1');
    assert.equal(list.writes, before.list); assert.equal(figs.writes, before.figs);
    assert.equal(row(8), before.r8); assert.equal(row(7), before.r7);
    assert.match(f.root.querySelector('#rfigs').innerHTML, /27/);  // still the kept answer's figures

    // One session's spend moved: its row alone is rewritten, the others stay the same elements.
    answer = {runs: [runs[0], {...runs[1], spent_usd: 1.5}, runs[2]], counts, policy: null, totals: {tried: 27, passed: 3}, v: 'v2'};
    await poll(); await settle();
    assert.equal(asked(), '/api/runs?since=v1');
    assert.equal(list.writes, before.list, 'the list itself is not rewritten');
    assert.notEqual(row(8), before.r8); assert.match(row(8).innerHTML, /\$1\.50/);
    assert.equal(row(7), before.r7);
    assert.equal(figs.writes, before.figs, 'the figures did not change');

    // A new session changes which rows there are: the list is rewritten, and the next poll sends v3.
    answer = {runs: [run({id: 10, status: 'queued', stop_reason: null, spent_usd: 0, created_at: '2026-10-26T09:00:00Z'}), ...answer.runs],
      counts: {...counts, research_queued: 1}, policy: null, totals: {tried: 27, passed: 3}, v: 'v3'};
    await poll(); await settle();
    assert.equal(asked(), '/api/runs?since=v2');
    assert.equal(list.writes, before.list + 1);
    answer = {v: 'v3', same: true};
    await poll(); await settle();
    assert.equal(asked(), '/api/runs?since=v3');
    assert.equal(list.writes, before.list + 1);
    f.clearTimers();
  });

  // The Research page's Paper tournament (walked 2026-10-27) said "Retiring: ... (posterior mean -4.2% of
  // stake)", "Every near miss", "a bandit", "All entrants together" and "until an entrant beats zero". The
  // server sends each reason in the autopilot feed's words (customer_text.tournament_standings); the page's
  // own words say the rest plainly.
  test(`${name}: the Research page's paper tournament reads in plain words`, async () => {
    const board = {total: {runs: 3, explored: 12, gated: 3, gate_reach_rate: 0.25, passed: 1, holdout_passed: 0, cost_usd: 2, pipeline_death_share: 0.2},
      days: [], trend: null, playbooks: [], scout: [], fix_list: [], data_requests: [], paper: null,
      tournament: {pooled: {trips: 31, target: 400, per_day: 2.5, days_to_target: 147.6, mean_return: -0.012},
        book: {capital: 100, pnl: -1.25, trips: 40},
        entrants: [{strategy_id: 42, market: 'btc15m', title: 'Fade: late YES', weight: 0.2, trips: 31, net_pnl: -2.4, p_positive: 0.07,
          verdict: 'after 31 paper events it is 93% likely to be losing money per event'},
        {strategy_id: 43, market: 'btc15m', title: 'Wick fade NO', weight: 0.3, trips: 0, net_pnl: 0, p_positive: 0.5,
          verdict: 'no trade in 7 days, as its entry rule never fired on the market’s real prices'},
        {strategy_id: 0, title: 'Cash', weight: 0.5}]}};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs: [run({id: 8})], counts, policy: null, totals: {tried: 9, passed: 1}, v: 'v1'});
      if (path.startsWith('/api/research/scoreboard')) return response(board);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const card = f.root.querySelector('#rsimo').innerHTML;
    const at = card.indexOf('Paper tournament'), sect = card.slice(at, card.indexOf('</ul>', at));
    assert.ok(at > 0, 'the section is on the page');
    assert.match(sect, /Every strategy on paper takes part at once, and a \$100 practice book shifts toward the ones that earn\. Together they have 31 of the 400 separate bets it takes to judge them/);
    assert.match(sect, /Falling short: after 31 paper events it is 93% likely to be losing money per event</);
    assert.match(sect, /Falling short: no trade in 7 days, as its entry rule never fired on the market’s real prices</);
    assert.match(sect, /held back until a strategy shows it makes money/);
    assert.match(sect, /Practice book so far: /);
    assert.doesNotMatch(sect, /Retiring|entrant|bandit|near miss|forward sample|posterior|live book|beats zero/i);
    f.clearTimers();
  });

  // Walked 2026-10-27 at 390px and 1280px: the loop card's paper line said "On paper against the live book ... 37 round
  // trips"; the tournament's book read "$10,000.00", its average "-9.0%" with a hyphen beside the "−$18.40" figures,
  // and a book with nothing in it "$0.00 over 0 trades"; Tau's headline said "Hypotheses tested" over "of ideas tested".
  test(`${name}: the Research page's loop card and headline say their figures plainly`, async () => {
    const board = {total: {runs: 3, explored: 12, gated: 3, gate_reach_rate: 0.25, passed: 1, holdout_passed: 0, cost_usd: 2, pipeline_death_share: 0.2},
      days: [], trend: null, playbooks: [], scout: [], fix_list: [], data_requests: [],
      paper: {total: {strategies: 4, trading: 2, round_trips: 37, net_pnl: -16.6, live_ready: 0, realization: -0.5}, by_playbook: {}},
      tournament: {pooled: {trips: 37, target: 400, per_day: 3.7, days_to_target: 98, mean_return: -0.09},
        book: {capital: 10000, pnl: 0, trips: 0},
        entrants: [{strategy_id: 42, market: 'btc15m', title: 'Fade', weight: 0.6, trips: 31, net_pnl: -18.4, p_positive: 0.13, verdict: null},
          {strategy_id: 0, title: 'Cash', weight: 0.4}]}};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs: [run({id: 8})], counts, policy: null, totals: {tried: 21, passed: 3}, v: 'v1'});
      if (path.startsWith('/api/research/scoreboard')) return response(board);
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const card = f.root.querySelector('#rsimo').innerHTML;
    assert.match(card, /On paper at the market’s real prices: 4 passed strategies, 2 trading, 37 closed trades, net −\$16\.60/);
    assert.match(card, /and a \$10,000 practice book shifts/);
    assert.match(card, /averaging −9\.0% of the stake a bet\. The practice book has no trades yet\./);
    assert.doesNotMatch(card, /live book|round trip|\$10,000\.00|-9\.0%|over 0 trades/);
    const top = f.root.querySelector('#rfigs').innerHTML + ((f.root.querySelector('#rstatus .said') || {}).innerHTML || '');
    assert.doesNotMatch(top, /[Hh]ypothes/);
    f.clearTimers();
  });
}
