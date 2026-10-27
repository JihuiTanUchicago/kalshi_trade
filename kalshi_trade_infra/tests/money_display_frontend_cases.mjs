// Shared cases, run against each bundle's offline harness (Tau and Meridian), from a phone and desktop walk as
// a Bitcoin trader (390px and 1280px, both themes, 2026-10-27):
// - Meridian put a connected key's real Kalshi cash in the Accounts menu, closed, whenever paper led the band (no
//   live deployment: everyone while live is closed). Real cash is drawn in the band, its own figure, never added
//   to paper, and says when Kalshi was read; Tau's dashboard always showed it so.
// - KXBTC's hourly price ranges (Explore, the hot rail, a market page, a position held at Kalshi) belong to no
//   market here, so they had no chip, and a held one was named after its deployment's market ("BTC 15-min
//   up/down") or "Kalshi contract". They say range, bucket and close.
// - The strategy page's "Holding right now" tagged Live and Demo rows but not paper ones, so beside a Demo row a
//   paper position read as the real-money book. With more than one book every row says its book.
import assert from 'node:assert/strict';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const BTC = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes'},
  {key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above $X at 5pm ET', close_hour_et: 17}];
const pos = (extra) => ({title: 'Drift', ticker: 'KXBTCD-26OCT2617-T68499.99', side: 'yes', qty: 3, entry_price: .22, entry_fee: .02, cost: .68,
  unrealized: null, mode: 'live', opened_at: '2026-10-27T08:00:00Z', market_close_time: '2030-01-15T21:00:00Z', ...extra});

export function moneyDisplayCases({name, frontend, strategyFrontend, detailStrategy, dashboard, hotRail}) {
  test(`${name}: a connected Kalshi key's real cash is on the dashboard, not behind a closed menu, with when it was read`, async () => {
    const data = {...dashboard(), live: {connected: true, balance: 1234.56, balance_at: new Date().toISOString(), realized_pnl: 0, today_pnl: 0,
      open_positions: 0, open_at_cost: 0}};
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    await f.viewDashboard(); await flush(); await flush();
    const board = ['#boardbody', '#main'].map((sel) => f.root.querySelector(sel)).filter(Boolean);
    const text = board.map((el) => el.innerHTML).join('').replace(/<[^>]*>/g, '');
    assert.match(text, /\$1,234\.56/);
    assert.match(text, /read from Kalshi just now/i);
    for (const el of board) for (const d of el.querySelectorAll('details').filter((x) => !x.open)) assert.doesNotMatch(d.innerHTML, /\$1,234\.56/);
    // Its own figure: never added to paper ($1,234.56 + paper's equity) anywhere on the board.
    const paper = +data.paper.equity, sum = (1234.56 + paper).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    assert.doesNotMatch(text, new RegExp('\\$' + sum.replace(/[.,]/g, '\\$&')));
  });

  test(`${name}: a KXBTC range contract is named as a range with its bucket and close, never another market or the raw series`, async () => {
    const markets = [
      {t: 'KXBTC-26OCT2817-B113250', s: 'KXBTC', ti: 'Bitcoin price range on Oct 28, 2026?', su: '$113,000 to 113,499.99', bid: .21, ask: .24, v24: 10, oi: 1, h: [.2, .22]},
      {t: 'KXBTC-26OCT2809-T114999.99', s: 'KXBTC', ti: 'Bitcoin price range on Oct 28, 2026?', su: '$115,000 or above', bid: .08, ask: .1, v24: 9, oi: 1, h: [.1, .09]}];
    const f = frontend(); f.S.me.markets = BTC;
    const rail = hotRail(f, markets);
    assert.match(rail, />BTC range at 5pm ET</); assert.match(rail, />BTC range at 9am ET</);
    assert.doesNotMatch(rail, />KXBTC</);
    // A range held in a book is named by its own bucket, not "Kalshi contract" or its deployment's market.
    const g = frontend({fetchImpl: (path) => path === '/api/deployments'
      ? response({deployments: [], open_positions: [pos({ticker: 'KXBTC-26OCT2717-B113250'}), pos({ticker: 'KXBTC-26OCT2721-T114999.99', mode: 'paper'})]})
      : response({})});
    g.S.me.markets = BTC;
    await g.viewDeploy(); await flush(); await flush();
    const html = g.root.querySelector('#openpos').innerHTML;
    assert.match(html, /<a href="\/explore\?m=KXBTC-26OCT2717-B113250">Bitcoin in the bucket around \$113,250 at 5pm ET<\/a>/);
    assert.match(html, /<a href="\/explore\?m=KXBTC-26OCT2721-T114999\.99">Bitcoin range end at \$114,999\.99, 9pm ET<\/a>/);
    assert.doesNotMatch(html, />Kalshi contract<\/a>/);
  });

  test(`${name}: with holdings in more than one book, the strategy page tags a paper holding Paper as it tags Demo and Live`, async () => {
    const paper = pos({mode: 'paper'}), demo = pos({mode: 'demo', ticker: 'KXBTCD-26OCT2617-T68999.99'});
    const list = async (holdings) => {
      const f = strategyFrontend(detailStrategy({holdings}), () => response({})); f.S.me.markets = BTC;
      await f.viewStrategy(42); await flush();
      const out = f.root.querySelector('#main').innerHTML, at = out.indexOf('<ul class="holdlist">');
      return out.slice(at, out.indexOf('</ul>', at));
    };
    const mixed = await list([demo, paper]);
    assert.match(mixed, /<span class="mk dep">Demo<\/span>/);
    assert.match(mixed, /T68499\.99">Bitcoin above \$68,499\.99 at 5pm ET<\/a> <span class="mk">Paper<\/span>/);
    // One book alone reads as before: no tag on a page that is all paper.
    assert.doesNotMatch(await list([paper]), /class="mk"/);
  });
}
