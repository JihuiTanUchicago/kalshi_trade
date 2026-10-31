// The Strategies list's market filter offers the Bitcoin perpetual, by its customer label, and says what a link filters
// to. A customer with perpetual strategies couldn't filter to them while the research picker's markets (S.me.markets)
// left the perpetual out (its research closed on the server), and a link with ?market=btc_perp read "All markets"
// while the list it drew was filtered to it. Drawn in each theme's offline harness.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

// Every markup string a script wrote, so the select's options and their selected state can be read whole.
const written = (el) => (el.writes ? [el.html || ''] : []).concat(...el.children.map(written)).join('\n');
const select = (html) => (html.match(/<select class="input strat-mkt" id="strat-market"[\s\S]*?<\/select>/) || [''])[0];
const selected = (sel) => [...sel.matchAll(/<option value="([^"]*)" selected>([^<]*)<\/option>/g)].map((m) => [m[1], m[2]]);

export function strategyMarketFilterCases({name, frontend, detailStrategy}) {
  const PERP = detailStrategy({id: 70, title: 'Perp momentum', status: 'passed', market: 'btc_perp', direction: 'momentum'});
  const draw = async (search, markets) => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/strategies')
      ? response({counts: {total: 1, passed: 1}, matched: 1, pages: 1, strategies: [PERP]}) : response({}))});
    f.S.me.markets = markets;
    f.location.pathname = '/strategies'; f.location.search = search;
    const drawing = f.viewStrategies();
    for (let i = 0; i < 4; i++) { await settle(); f.elapse(2000); }
    await drawing; await settle();
    const out = {f, sel: select(written(f.document.body))};
    return out;
  };
  const CRYPTO = [{key: 'btc15m', category: 'Crypto', label: 'Bitcoin up or down in 15 minutes'}, {key: 'eth15m', category: 'Crypto', label: 'Ethereum up or down in 15 minutes'}];

  test(`${name}: the Strategies market filter offers the Bitcoin perpetual by its customer label, never its key`, async () => {
    const {sel, f} = await draw('?status=', CRYPTO);
    assert.match(sel, /<optgroup label="Crypto perpetuals"><option value="btc_perp">BTC perpetual, no expiry<\/option><\/optgroup>/);
    assert.ok(!/>btc_perp</.test(sel) && !/BTC_PERP/.test(sel), 'no key or series shown');
    assert.deepEqual(selected(sel), [], 'All markets');
    // Picking it filters the list to it, as any other market.
    const m = f.root.querySelector('#strat-market'); m.value = 'btc_perp'; m.onchange(); await settle();
    assert.ok(f.navigations.some((u) => /^\/strategies\?(?:.*&)?market=btc_perp(?:&|$)/.test(u)), JSON.stringify(f.navigations));
    f.clearTimers();
  });

  test(`${name}: a link filtered to the perpetual shows it picked, not "All markets"`, async () => {
    const {sel, f} = await draw('?status=&market=btc_perp', CRYPTO);
    assert.deepEqual(selected(sel), [['btc_perp', 'BTC perpetual, no expiry']]);
    assert.ok(f.requests.some(({path}) => /^\/api\/strategies\?.*market=btc_perp/.test(path)));
    f.clearTimers();
  });

  test(`${name}: with the perpetual already in the research picker's markets it is offered once, in its own group`, async () => {
    const {sel, f} = await draw('?status=&market=btc_perp', [...CRYPTO, {key: 'btc_perp', category: 'Crypto perpetuals', label: 'Bitcoin perpetual future, no expiry (research only)'}]);
    assert.equal((sel.match(/value="btc_perp"/g) || []).length, 1);
    assert.deepEqual(selected(sel), [['btc_perp', 'BTC perpetual, no expiry']]);
    f.clearTimers();
  });

  test(`${name}: a link filtered to a market the picker doesn't list shows that filter by a customer label, never the key`, async () => {
    const {sel, f} = await draw('?status=&market=gone_market', CRYPTO);
    assert.deepEqual(selected(sel), [['gone_market', 'Unlisted market']]);
    assert.ok(!/>gone_market</.test(sel));
    f.clearTimers();
  });
}
