// Explore's market page (/explore?m=TICKER) cases, run against each bundle's offline DOM/transport harness:
// what to do next from a market, its name without a raw series key, and a raw-data table that leaves the
// page's own actions within reach on a phone.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

const MARKETS = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin daily close, 5pm EDT', category: 'Crypto'},
  {key: 'nba_game', series: 'KXNBAGAME', label: 'NBA game winner', category: 'Sports'}];
const page = (over) => ({ticker: 'KXBTCD-26OCT2617-T113499.99', series: 'KXBTCD', title: 'Bitcoin price at 5pm EDT?', sub: '$113,500 or above',
  status: 'active', yes_bid: '0.55', yes_ask: '0.57', last: '0.55', volume_24h: '15234', open_interest: '40211',
  close_time: '2026-10-26T21:00:00Z', as_of: '2026-10-26T11:00:00Z', rules: 'Resolves Yes above 113499.99.', period_min: 1,
  points: Array.from({length: 130}, (_, i) => ({t: 1793012400 + 60 * i, yes: .5, vol: 1})), mine: {open: [], closed: []}, ...over});

export function explorePageCases({name, frontend}) {
  const open = async (payload) => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore/market?') ? response(payload) : response({}))});
    f.S.me.markets = MARKETS;
    f.location.pathname = '/explore'; f.location.search = '?m=' + encodeURIComponent(payload.ticker);
    await f.viewExplore(); await settle();
    return f;
  };

  test(`${name}: a market Tau researches offers to research it, with the market picked, and to open its strategies`, async () => {
    const f = await open(page());
    const next = f.root.querySelector('.mk-next');
    assert.ok(next, 'the market page says what to do next');
    const links = next.querySelectorAll('a');
    assert.deepEqual(links.map((a) => a.getAttribute('href')), ['/research?new=1&amp;market=btc_daily', '/strategies?market=btc_daily']);
    assert.deepEqual(links.map((a) => a.textContent), ['Research BTC 5pm', 'Your BTC 5pm strategies']);
    // The name line reads the market's name, its status in words and the contract; never the raw series alone.
    assert.match(f.root.innerHTML, /Bitcoin daily close, 5pm EDT · Open for trading · KXBTCD-26OCT2617-T113499\.99/);
  });

  test(`${name}: a market Tau doesn't research says so, with no raw series key in its name line`, async () => {
    const f = await open(page({ticker: 'KXFEDDECISION-26DEC-H0', series: 'KXFEDDECISION', title: 'Fed decision in Dec 2026?', sub: 'Hike 0bps'}));
    const next = f.root.querySelector('.mk-next');
    assert.match(next.textContent, /Tau doesn’t research this market, so your strategies can’t trade it\./);
    assert.equal(next.querySelector('a.primary'), null, 'no research button for a market research can’t pick');
    assert.match(f.root.innerHTML, />Open for trading · KXFEDDECISION-26DEC-H0</);
    assert.doesNotMatch(f.root.innerHTML, /KXFEDDECISION ·/);
  });

  test(`${name}: the market page's raw candles come 25 to a page, so its actions stay within reach`, async () => {
    const f = await open(page());
    const raw = f.root.querySelector('#rawsect');
    assert.equal(raw.querySelectorAll('tbody tr').length, 25);
    assert.match(raw.textContent, /Page 1 of 6 · 130 points/);
  });

  test(`${name}: Research opened from a market page has that market picked and the options open`, async () => {
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/runs')) return response({runs: [], counts: {}, policy: null, totals: {tried: 0, passed: 0}, v: 'v1'});
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      return response({});
    }});
    f.S.me.markets = MARKETS; f.S.me.user.autopilot = true;
    f.location.pathname = '/research'; f.location.search = '?new=1&market=btc_daily';
    await f.viewResearch(); await settle();
    const radios = f.root.querySelectorAll('input[name=market]');
    assert.equal(radios.find((r) => r.value === 'btc_daily').checked, true);
    assert.equal(radios.find((r) => r.value === 'nba_game').checked, false);
    assert.equal(f.root.querySelector('#ropts').open, true);
    // A market the picker doesn't list changes nothing.
    const g = frontend({fetchImpl: (path) => (path.startsWith('/api/runs') ? response({runs: [], counts: {}, v: 'v1'}) : response({markets: [], models: []}))});
    g.S.me.markets = MARKETS; g.S.me.user.autopilot = true;
    g.location.pathname = '/research'; g.location.search = '?market=nope';
    await g.viewResearch(); await settle();
    assert.ok(g.root.querySelectorAll('input[name=market]').filter((r) => r.value).every((r) => !r.checked));
  });
}
