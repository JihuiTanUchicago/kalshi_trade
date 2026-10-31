// Shared cases, run against each bundle's offline harness (Tau and Meridian): every market reads by one long name
// and one short name, both from the shared core (core.js mktLong, mktShort). Walked 2026-10-31 with research
// sessions, feed lines, deployments, positions and bell notices on six markets: one market read "BTC 15-min
// up/down", "Bitcoin 15-minute" and "Bitcoin up or down in 15 minutes"; a perpetual strategy's page said "BTC
// perpetual, no expiry" over a Market line "Unlisted market"; the last move said "on BTC 15-min up/down" in a
// sentence the server's own lines say with the long name.
// - The long name is the catalog's label (me.markets) or, for a market the list leaves out, me.market_names.
// - The short name is core.js MKT_SHORT.
import assert from './assert_text.mjs';
import {test} from 'node:test';
import fs from 'node:fs';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const core = fs.readFileSync(new URL('../app/static/core.js', import.meta.url), 'utf8');
const block = core.slice(core.indexOf('const MKT_SHORT = {'));
const SHORT = Object.fromEntries([...block.slice(0, block.indexOf('};')).matchAll(/(\w+): '([^']*)'/g)].map((m) => [m[1], m[2]]));
// The long names as the server sends them (customer_label).
const LONG = {
  btc15m: 'Bitcoin up or down in 15 minutes', btc_daily: 'Bitcoin above a set price at 5pm ET',
  high_ny: 'NYC daily high temperature', nba_game: 'NBA game winner (moneyline)',
  btc_perp: 'Bitcoin perpetual future, no expiry (research only)',
};
const ME = {
  markets: [
    {key: 'btc15m', label: LONG.btc15m, series: 'KXBTC15M', category: 'Crypto', has_data: true},
    {key: 'btc_daily', label: LONG.btc_daily, series: 'KXBTCD', category: 'Crypto', has_data: true, close_hour_et: 17},
    {key: 'high_ny', label: LONG.high_ny, series: 'KXHIGHNY', category: 'Weather', has_data: true},
    {key: 'nba_game', label: LONG.nba_game, series: 'KXNBAGAME', category: 'Sports', has_data: true},
  ],
  // The perpetual while perps are closed: not in the list, still named.
  market_names: {btc_perp: LONG.btc_perp},
};

export function marketNameCases({name, frontend, detailStrategy, strategyFrontend}) {
  const withMe = (f) => { f.S.me = {...f.S.me, ...ME}; return f; };

  test(`${name}: a strategy's page says its market's short name in its heading and its long name on its Market line, a perpetual's too`, async () => {
    for (const key of Object.keys(LONG)) {
      const perp = key === 'btc_perp';
      const f = withMe(strategyFrontend(detailStrategy({market: key, status: 'passed', dataset: {start: '2026-09-01', end: '2026-10-17', out_of_sample_from: '2026-10-10'},
        ...(perp ? {kind: 'perpetual', research_only: true} : {})}), () => response({})));
      await f.viewStrategy(42); await flush();
      const html = f.root.querySelector('#main').innerHTML;
      assert.ok(html.includes('<dt>Market</dt>'), key + ': the Market line');
      const dd = html.slice(html.indexOf('<dt>Market</dt>')).match(/<dd>([\s\S]*?)<\/dd>/)[1].replace(/<[^>]*>/g, '').replace(' ↗', '').trim();
      assert.equal(dd, LONG[key], key);
      const head = f.root.querySelector('.strategy-pagehead') || f.root.querySelector('.board-title');
      assert.ok(head && (head.outer || head.innerHTML).includes(SHORT[key]), key + ': the short name in the heading');
      assert.doesNotMatch(html, /Unlisted market/, key);
      f.clearTimers();
    }
  });

  test(`${name}: the autopilot's last move and research line name a market by its long name, a key the list leaves out too`, () => {
    const f = withMe(frontend());
    for (const key of Object.keys(LONG)) {
      assert.equal(f.apMoveText({text: `Started a fresh research session on ${key} — same gates as any run.`, at: new Date().toISOString()}),
        `Started a fresh research session on ${LONG[key]}`, key);
    }
    f.S.ap = {autopilot: true, mode: 'paper', research: {active: ['btc_perp', LONG.btc15m, 'KXHIGHNY', 'kxgone']}};
    assert.equal(f.apIdleLine().replace(/\s/g, ' '), `Researching ${[LONG.btc_perp, LONG.btc15m, LONG.high_ny, 'an unlisted market'].join(' · ')}`);
  });

  test(`${name}: the research list names each session's market by its short name, never the key`, async () => {
    const runs = Object.keys(LONG).map((market, i) => ({id: i + 1, kind: 'research', market, status: 'succeeded', prompt: '',
      created_at: '2026-10-31T10:00:00Z', started_at: '2026-10-31T10:00:00Z', finished_at: '2026-10-31T10:20:00Z',
      hypotheses_tried: 2, strategies_passed: 0}));
    const f = withMe(frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs, total: runs.length, counts: {}});
      if (path.startsWith('/api/research/context')) return response({at: null, markets: []});
      if (path.startsWith('/api/research/scoreboard')) return response({});
      if (path === '/api/models') return response({models: [], default: ''});
      return response({});
    }}));
    f.location.pathname = '/research';
    await f.viewResearch(); await flush(); await flush();
    const text = f.root.querySelector('#runs').innerHTML.replace(/<[^>]*>/g, ' ');
    for (const key of Object.keys(LONG)) {
      assert.ok(text.includes(SHORT[key]), key);
      assert.doesNotMatch(text, new RegExp(`\\b${key}\\b`), key);
    }
    f.clearTimers();
  });
}
