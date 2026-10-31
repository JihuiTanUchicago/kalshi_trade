// Shared cases, run against each bundle's offline DOM/transport harness (Tau and Meridian): the Research
// list's 5s poll sends back the version of its last answer, repaints nothing when the server says the
// list is unchanged, and when one session moved rewrites that session's row alone.
import assert from './assert_text.mjs';
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
    // Strategies that clear every paper-to-live check: open, "ready for live"; with the server's live switch closed they
    // wait on paper, as their bell notice says, so the line names them that way, never "ready for live".
    const ready = async (open) => {
      const g = frontend({fetchImpl: (path) => {
        if (path.startsWith('/api/runs')) return response({runs: [run({id: 8})], counts, policy: null, totals: {tried: 21, passed: 3}, v: 'v1'});
        if (path.startsWith('/api/research/scoreboard')) return response({...board, paper: {...board.paper, total: {...board.paper.total, live_ready: 2}}});
        if (path === '/api/models') return response({models: [], default: ''});
        if (path === '/api/research/context') return response({markets: []});
        if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
        return response({});
      }});
      g.S.me.user.autopilot = false; g.S.me.live_trading_available = open;
      g.location.pathname = '/research';
      await g.viewResearch(); await settle();
      const html = g.root.querySelector('#rsimo').innerHTML;
      g.clearTimers();
      return html;
    };
    const shut = await ready(false);
    assert.match(shut, /net −\$16\.60, losing money where the backtest expected a profit\u00a0· 2 cleared every paper-to-live check\./);
    assert.doesNotMatch(shut, /ready for live/);
    assert.match(await ready(true), /\u00a0· 2 ready for live\./);
  });
  test(`${name}: each session row's Created date carries its day, clock and zone`, async () => {
    // Walked 2026-10-31: the rows read "Oct 28" in no zone, beside session pages whose clocks name theirs.
    const runs = [run({id: 8, created_at: '2026-10-25T08:00:00Z'}), run({id: 7, created_at: 'not a date'})];
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs, counts, policy: null, totals: {tried: 9, passed: 1}, v: 'v1'});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      return response({});
    }});
    f.S.me.user.autopilot = false;
    f.location.pathname = '/research';
    await f.viewResearch(); await settle();
    const html = f.root.querySelector('#runs').innerHTML;
    const stamp = new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'})
      .format(new Date('2026-10-25T08:00:00Z'));
    assert.match(stamp, /\d\d:\d\d \S+$/);  // the zone, last
    const day = new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric'}).format(new Date('2026-10-25T08:00:00Z'));
    assert.ok(html.includes(`<time datetime="2026-10-25T08:00:00Z" title="${stamp}">${day}</time>`), html);
    // A row with no readable date says none, not "Invalid Date".
    assert.doesNotMatch(html, /Invalid Date|NaN/);
    f.clearTimers();
  });

  // Walk 2026-10-31: a session row whose "Queued 30 min" or "40m ago" moved on a minute was rewritten by the poll, and
  // keyboard focus on it fell to the page's body once a minute. It goes back to the same row's new markup.
  test(`${name}: a poll that rewrites the focused session row puts focus back on that row`, async () => {
    const runs = [run({id: 9, status: 'queued', stop_reason: null, spent_usd: 0, created_at: '2026-10-26T08:00:00Z'}),
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
    const list = f.root.querySelector('#runs');
    const row = (id) => list.querySelector(`a[href="/research/${id}"]`);
    const poll = [...f.intervals.values()].at(-1);
    // Tau's harness marks the element a script focused; Meridian's moves document.activeElement to it.
    const isFocused = (el) => el.focused === true || f.document.activeElement === el;
    // The row itself holds focus, and its markup moves: the new row takes the focus, without a scroll.
    let had = row(8);
    f.document.activeElement = had;
    answer = {runs: [runs[0], {...runs[1], spent_usd: 1.5}, runs[2]], counts, policy: null, totals: {tried: 27, passed: 3}, v: 'v2'};
    await poll(); await settle();
    assert.notEqual(row(8), had, 'the row was rewritten');
    assert.ok(isFocused(row(8)), 'focus went back to the same session');
    assert.equal(row(8).focusOptions.preventScroll, true);
    assert.ok(!isFocused(row(7)) && !(row(9) && isFocused(row(9))));
    // A new session rewrites the whole list: focus still goes back to the same session's row, now one place down.
    had = row(8);
    f.document.activeElement = had;
    answer = {runs: [run({id: 10, status: 'queued', stop_reason: null, spent_usd: 0, created_at: '2026-10-26T09:00:00Z'}), ...answer.runs.map((r) => (r.id === 8 ? {...r, spent_usd: 1.75} : r))],
      counts, policy: null, totals: {tried: 27, passed: 3}, v: 'v3'};
    await poll(); await settle();
    assert.notEqual(row(8), had);
    assert.ok(isFocused(row(8)));
    assert.ok(!(row(10) && isFocused(row(10))));
    f.clearTimers();
  });

  // Walk 2026-10-31: "Passed every gate 0 · 0.0% of ideas tested" under three tested ideas read as if none had been
  // tested. The share names what it is a share of, says "none of" for nothing passed and "under 0.1%" for a sliver.
  test(`${name}: the headline's pass share names how many ideas it is a share of, and never reads 0.0%`, async () => {
    const words = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    for (const [totals, tau, mer] of [
      [{tried: 3, passed: 0}, /all time · none of 3 ideas/, 'None of 3 ideas passed, all time'],
      [{tried: 5000, passed: 1}, /all time · under 0\.1% of 5,000 ideas/, 'Under 0.1% of 5,000 ideas passed, all time'],
      [{tried: 1, passed: 1}, /all time · 100\.0% of 1 idea\b/, '100.0% of 1 idea passed, all time'],
      [{tried: 551, passed: 13}, /all time · 2\.4% of 551 ideas/, '2.4% of 551 ideas passed, all time'],
    ]) {
      const f = frontend({fetchImpl: (path) => {
        if (path.startsWith('/api/runs')) return response({runs: [run({hypotheses_tried: totals.tried, strategies_passed: totals.passed})], counts: {...counts, research_running: 0}, policy: null, totals});
        if (path === '/api/models') return response({models: [], default: ''});
        if (path === '/api/research/context') return response({markets: []});
        if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
        return response({});
      }});
      f.S.me.user.autopilot = false;
      f.location.pathname = '/research';
      await f.viewResearch(); await settle();
      const figs = f.root.querySelector('#rfigs');
      const said = words(figs.innerHTML) + ' ' + (figs.getAttribute('title') || '');
      assert.doesNotMatch(said, /(^|[^\d])0\.0%|of ideas tested/, JSON.stringify(totals));
      if (f.root.querySelector('#rstatus .said')) assert.match(words(figs.innerHTML), tau, JSON.stringify(totals));
      else assert.equal(figs.getAttribute('title'), mer, JSON.stringify(totals));
      f.clearTimers();
    }
  });

  // Walk 2026-10-31: a finished session that tested no idea read "Finished · 0 of 0 passed" (Tau) and "0/0 passed" (Meridian).
  test(`${name}: a finished session that tested no idea says so, not "0 of 0 passed"`, () => {
    const f = frontend();
    const empty = f.runRow(run({hypotheses_tried: 0, strategies_passed: 0}));
    const words = empty.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    assert.match(words, /Finished/);
    assert.match(words, /no ideas tested/i);
    assert.doesNotMatch(words, /0 of 0|0 \/ 0|0\/0|passed/);
    // One that ran out of credits before its first idea names that, and one with an idea keeps its count.
    const credits = f.runRow(run({hypotheses_tried: 0, strategies_passed: 0, stop_reason: 'credits', run_forever: 1})).replace(/<[^>]+>/g, ' ');
    assert.match(credits, /Out of credits/); assert.match(credits, /no ideas tested/i);
    assert.match(f.runRow(run({hypotheses_tried: 3, strategies_passed: 0})).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' '), /0 of 3 passed|0 \/ 3 passed/);
  });
}
