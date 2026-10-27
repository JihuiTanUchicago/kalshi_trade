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
import assert from './assert_text.mjs';
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

  test(`${name}: another hour of the 5pm Bitcoin ladder says its own close, never the 5pm market's name or none`, async () => {
    // KXBTCD runs every hour; btc_daily keeps to its 5pm close. The noon, 9am and midnight contracts had no chip
    // on the hot rail, and one held under a btc_daily strategy took "at 5pm ET" from its strategy's market.
    const row = (t, ti) => ({t, s: 'KXBTCD', ti, su: '$113,000 or above', bid: .5, ask: .52, v24: 10, oi: 1, h: [.5, .51]});
    const f = frontend(); f.S.me.markets = BTC;
    const rail = hotRail(f, [row('KXBTCD-26OCT2812-T112999.99', 'Bitcoin price at 12pm EDT?'), row('KXBTCD-26OCT2809-T112999.99', 'Bitcoin price at 9am EDT?'),
      row('KXBTCD-26OCT2900-T112999.99', 'Bitcoin price at 12am EDT?'), row('KXBTCD-26OCT2817-T112999.99', 'Bitcoin price at 5pm EDT?')]);
    for (const at of ['noon', '9am', 'midnight', '5pm']) assert.match(rail, new RegExp(`>BTC above \\$X at ${at} ET<`));
    assert.equal((rail.match(/>BTC above \$X at 5pm ET</g) || []).length, 1, 'only the 5pm contract takes the 5pm market');
    assert.doesNotMatch(rail, />KXBTCD</);
    // Held under a btc_daily strategy, the noon contract is named by its own close and strike.
    const s = strategyFrontend(detailStrategy({market: 'btc_daily', holdings: [pos({ticker: 'KXBTCD-26OCT2712-T68499.99', mode: 'paper'})]}), () => response({}));
    s.S.me.markets = BTC;
    await s.viewStrategy(42); await flush();
    const held = s.root.querySelector('#main').innerHTML;
    assert.match(held, /<a href="\/explore\?m=KXBTCD-26OCT2712-T68499\.99">Bitcoin above \$68,499\.99 at noon ET<\/a>/);
    assert.doesNotMatch(held, /T68499\.99">[^<]*5pm/);
    // An open position on the Deploy board, under no deployment: its own close, not "Kalshi contract".
    const g = frontend({fetchImpl: (path) => path === '/api/deployments'
      ? response({deployments: [], open_positions: [pos({ticker: 'KXBTCD-26OCT2709-T68499.99'})]}) : response({})});
    g.S.me.markets = BTC;
    await g.viewDeploy(); await flush(); await flush();
    assert.match(g.root.querySelector('#openpos').innerHTML, />Bitcoin above \$68,499\.99 at 9am ET<\/a>/);
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

// Walk 2026-10-27, both themes: a deployment's Unrealized cell on the Overview with no figure said "None open" or
// "Unavailable" in Meridian and a bare "—" in Tau, which said neither. Both now say which: nothing is open, or
// something is open and has no price to mark it at yet.
export function unrealizedCellCases({name, frontend, dashboard}) {
  test(`${name}: an Overview deployment with no unrealized figure says "None open" or "Unavailable", never a bare dash`, async () => {
    const dep = (id, open) => ({id, strategy_id: id, title: 'Book ' + id, market: 'btc15m', mode: 'paper', status: 'running',
      stake: 5, max_positions: 2, realized_pnl: 1, unrealized_pnl: null, closed_trades: 3, open_positions: open, curve: [],
      created_at: '2026-10-25T08:00:00Z'});
    const f = frontend({fetchImpl: (path) => {
      if (path.startsWith('/api/dashboard')) return response({...dashboard(), deployments: [dep(1, 0), dep(2, 2)]});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    await f.viewDashboard(); await flush(); await flush();
    // Tau's table cell, or Meridian's monitor row.
    const html = ['#boardbody', '#main', '#deps'].map((sel) => f.root.querySelector(sel)).filter(Boolean).map((el) => el.innerHTML).join('');
    const cells = [...html.matchAll(/(?:data-lab="Unrealized">|class="monitor-unrealized"><dt>[^<]*<\/dt><dd>)([\s\S]*?)<\/(?:td|dd)>/g)]
      .map((m) => m[1].replace(/<[^>]*>/g, '').trim());
    assert.deepEqual(cells, ['None open', 'Unavailable']);
    if (f.clearTimers) f.clearTimers();
  });
}

// Deploy's open positions and a market page's "Your positions here" read a bare "—" for Unrealized on a position
// the engine hadn't priced yet (a phone walk, 2026-10-27): nothing said why, and a screen reader said "dash".
// Each says Unavailable, as a deployment row and Meridian's dashboard positions do: Tau shows the word (its stacked
// card has room at 390px), Meridian keeps its dash with the word for screen readers.
export function unmarkedPositionCases({name, frontend}) {
  const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
  const spoken = (h) => h.replace(/<span aria-hidden="true">[^<]*<\/span>/g, '').replace(/<[^>]*>/g, '').trim();
  const cells = (html) => [...html.matchAll(/data-lab="Unrealized">([\s\S]*?)<\/td>/g)].map((m) => m[1]);
  const unmarked = pos({id: 7, deployment_id: 1, mode: 'paper', ticker: 'KXBTC15M-26OCT271615-15', market: 'btc15m'});
  const marked = {...unmarked, id: 8, unrealized: .14, mark_ts: '2026-10-27T15:00:00Z'};

  test(`${name}: Deploy's open position with no mark yet says Unavailable, never a bare dash`, async () => {
    const f = frontend({fetchImpl: (path) => path === '/api/deployments' ? response({deployments: [{id: 1, strategy_id: 1, title: 'Drift',
      market: 'btc15m', mode: 'paper', status: 'running', realized_pnl: 0, closed_trades: 0, open_positions: 2, unrealized_pnl: .14,
      created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 2, backtest: {out_of_sample: null}}], open_positions: [unmarked, marked]})
      : response({})});
    f.S.me.markets = BTC; f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    const got = cells(f.root.querySelector('#openpos').innerHTML);
    assert.equal(got.length, 2);
    assert.equal(spoken(got[0]), 'Unavailable');
    assert.match(spoken(got[1]), /^\+\$0\.14/);
    if (f.clearTimers) f.clearTimers();
  });

  test(`${name}: a market page's own open position with no mark yet says Unavailable, never a bare dash`, async () => {
    const page = {ticker: unmarked.ticker, series: 'KXBTC15M', title: 'BTC up or down?', sub: '', status: 'active', yes_bid: '0.55',
      yes_ask: '0.57', last: '0.55', volume_24h: '10', open_interest: '10', close_time: '2026-10-27T16:15:00Z', as_of: '2026-10-27T16:00:00Z',
      rules: 'Resolves Yes if up.', period_min: 1, points: [], mine: {open: [{...unmarked, status: 'open', strategy_id: 1}], closed: []}};
    const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(page) : response({})});
    f.S.me.markets = BTC; f.location.pathname = '/explore'; f.location.search = '?m=' + encodeURIComponent(page.ticker);
    await f.viewExplore(); await settle();
    const got = cells(f.root.innerHTML);
    assert.equal(got.length, 1);
    assert.equal(spoken(got[0]), 'Unavailable');
    assert.match(f.root.innerHTML, /awaiting first mark/);
    if (f.clearTimers) f.clearTimers();
  });
}
