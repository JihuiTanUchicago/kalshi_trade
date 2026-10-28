// Explore's market page (/explore?m=TICKER) cases, run against each bundle's offline DOM/transport harness:
// what to do next from a market, its name without a raw series key, and a raw-data table that leaves the
// page's own actions within reach on a phone.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };

const MARKETS = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above $X at 5pm ET', category: 'Crypto', close_hour_et: 17},
  {key: 'nba_game', series: 'KXNBAGAME', label: 'NBA game winner', category: 'Sports'}];
const page = (over) => ({ticker: 'KXBTCD-26OCT2617-T113499.99', series: 'KXBTCD', title: 'Bitcoin price at 5pm EDT?', sub: '$113,500 or above',
  status: 'active', yes_bid: '0.55', yes_ask: '0.57', last: '0.55', volume_24h: '15234', open_interest: '40211',
  close_time: '2026-10-26T21:00:00Z', as_of: '2026-10-26T11:00:00Z', rules: 'Resolves Yes above 113499.99.', period_min: 1,
  points: Array.from({length: 130}, (_, i) => ({t: 1793012400 + 60 * i, yes: .5, vol: 1})), mine: {open: [], closed: []}, ...over});

export function explorePageCases({name, frontend}) {
  const open = async (payload, narrow = false) => {
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore/market?') ? response(payload) : response({}))});
    if (narrow) f.window.matchMedia = (q) => ({matches: /max-width/.test(q), addEventListener() {}, removeEventListener() {}});
    f.S.me.markets = MARKETS;
    f.location.pathname = '/explore'; f.location.search = '?m=' + encodeURIComponent(payload.ticker);
    await f.viewExplore(); await settle();
    return f;
  };

  test(`${name}: a market Tau researches offers to research it, with the market picked, and to open its strategies`, async () => {
    const f = await open(page({my_markets: ['btc_daily']}));
    const next = f.root.querySelector('.mk-next');
    assert.ok(next, 'the market page says what to do next');
    const links = next.querySelectorAll('a');
    assert.deepEqual(links.map((a) => a.getAttribute('href')), ['/research?new=1&amp;market=btc_daily', '/strategies?market=btc_daily']);
    assert.deepEqual(links.map((a) => a.textContent), ['Research BTC above $X at 5pm ET', 'Your BTC above $X at 5pm ET strategies']);
    // "Your … strategies" showed to a reader with none on this market (and opened an empty list): it shows only when the
    // server says they have one there; with none, or that read failed (null), only Research is offered.
    for (const mine of [[], ['nba_game'], null]) {
      const g = await open(page({my_markets: mine}));
      assert.deepEqual(g.root.querySelector('.mk-next').querySelectorAll('a').map((a) => a.getAttribute('href')), ['/research?new=1&amp;market=btc_daily'], String(mine));
      assert.doesNotMatch(g.root.querySelector('.mk-next').textContent, /strategies/);
    }
    // The name line reads the market's name with this contract's strike, its status in words and the contract;
    // never the raw series alone.
    assert.match(f.root.innerHTML, /Bitcoin above \$113,499\.99 at 5pm ET · Open for trading · <span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">KXBTCD-26OCT2617-T113499\.99/);
  });

  test(`${name}: a market Tau doesn't research says so, with no raw series key in its name line`, async () => {
    const f = await open(page({ticker: 'KXFEDDECISION-26DEC-H0', series: 'KXFEDDECISION', title: 'Fed decision in Dec 2026?', sub: 'Hike 0bps'}));
    const next = f.root.querySelector('.mk-next');
    assert.match(next.textContent, /Tau doesn’t research this market, so your strategies can’t trade it\./);
    assert.equal(next.querySelector('a.primary'), null, 'no research button for a market research can’t pick');
    assert.match(f.root.innerHTML, />Open for trading · <span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">KXFEDDECISION-26DEC-H0</);
    assert.doesNotMatch(f.root.innerHTML, /KXFEDDECISION ·/);
  });

  test(`${name}: an untitled contract's page is headed by a plain name, its ticker only on the line under it`, async () => {
    const f = await open(page({ticker: 'KXFEDDECISION-26DEC-H0', series: 'KXFEDDECISION', title: '', sub: ''}));
    assert.equal(f.root.querySelector('h1').textContent, 'Kalshi contract', 'never the raw ticker as the heading');
    // The ticker is labelled the way a position's is (kalshiRef): it read "Open for trading · KXFEDDECISION-26DEC-H0".
    assert.match(f.root.querySelector('.board-title .deck').textContent, /Open for trading\u00a0· Kalshi contract KXFEDDECISION-26DEC-H0$/);
    assert.doesNotMatch(f.root.querySelector('.board-title .deck').textContent, /·\sKX/);
  });

  test(`${name}: an hourly contract of the 5pm Bitcoin ladder isn't named the 5pm market, and points at the close Tau researches`, async () => {
    const f = await open(page({ticker: 'KXBTCD-26OCT2700-T112999.99', title: 'Bitcoin price on Oct 27, 2026 at 12am EDT?', sub: '$113,000 or above'}));
    assert.doesNotMatch(f.root.innerHTML, /Bitcoin above \S+ at 5pm ET ·/, 'the midnight contract is not the 5pm market');
    assert.match(f.root.innerHTML, /Bitcoin above \$112,999\.99 at midnight ET\u00a0· Open for trading\u00a0· <span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">KXBTCD-26OCT2700-T112999\.99/, 'named by its own close');
    const next = f.root.querySelector('.mk-next');
    assert.match(next.textContent, /Tau researches only the 5pm ET close of this ladder, so your strategies don’t trade this contract\./);
    assert.deepEqual(next.querySelectorAll('a').map((a) => a.getAttribute('href')), ['/research?new=1&amp;market=btc_daily']);
    assert.equal(next.querySelector('a.primary'), null, 'no research button that reads as researching this contract');
  });

  test(`${name}: on a phone the price chart is drawn near the width it shows at, so its labels stay legible`, async () => {
    const wide = await open(page());
    assert.match(wide.root.querySelector('.pchart').getAttribute('viewBox'), /^0 0 760 /);
    const f = await open(page(), true);
    assert.match(f.root.querySelector('.pchart').getAttribute('viewBox'), /^0 0 340 220$/);
  });

  test(`${name}: the market page's raw candles come 25 to a page, so its actions stay within reach`, async () => {
    const f = await open(page());
    const raw = f.root.querySelector('#rawsect');
    assert.equal(raw.querySelectorAll('tbody tr').length, 25);
    // Walked 2026-10-28: the chart said "Kalshi per-minute candles", a trader's word; it says how often it has a price.
    for (const [period_min, words] of [[1, 'A price each minute'], [60, 'A price each hour'], [1440, 'A price each day']]) {
      const g = await open(page({period_min}));
      const head = g.root.querySelectorAll('.sect-head').find((h) => /Price history/.test(h.textContent));
      assert.match(head.textContent, new RegExp(`Yes price\\s?· ${words}, from Kalshi`));
      assert.doesNotMatch(g.root.querySelector('#main').textContent, /candle/i);
    }
    const empty = await open(page({points: []}));
    assert.match(empty.root.querySelector('#rawsect').textContent, /Kalshi has no price history for this market yet\./);
    assert.match(raw.textContent, /Page 1 of 6 · 130 points/);
  });

  // A Bitcoin contract's page: where stored spot is against the strike (/api/explore/spot), in its own section.
  const SPOT = {ticker: 'KXBTCD-26OCT2617-T112999.99', spot: {price: 113420, at: '2026-10-26T11:00:00Z', age_s: 4, stale: false},
    strike: {kind: 'above', value: 112999.99, lo: null, hi: null, inclusive: false, from: 'ticker'},
    vs: {side: 'above', diff: 420.01, pct: 0.372, yes: true}, close_time: '2026-10-26T21:00:00Z', secs_left: 4320, as_of: '2026-10-26T11:00:04Z'};
  const openSpot = async (spotReply, over = {}) => {
    const asked = [];
    const f = frontend({fetchImpl: (path) => {
      asked.push(path);
      if (path.startsWith('/api/explore/market?')) return response(page({ticker: SPOT.ticker, ...over}));
      if (path.startsWith('/api/explore/spot?')) return spotReply(path);
      return response({});
    }});
    f.S.me.markets = MARKETS;
    f.location.pathname = '/explore'; f.location.search = '?m=' + encodeURIComponent(over.ticker || SPOT.ticker);
    await f.viewExplore(); await settle();
    return {f, asked, body: () => f.root.querySelector('#mk-spot-body')};
  };

  test(`${name}: a Bitcoin contract's page says where Bitcoin is against the strike, how fresh that is, and the time left`, async () => {
    const {asked, body} = await openSpot(() => response(SPOT));
    assert.equal(body().closest('section').querySelector('h2').textContent, 'Bitcoin vs the strike');
    assert.deepEqual(asked.filter((p) => p.startsWith('/api/explore/spot?')), ['/api/explore/spot?ticker=KXBTCD-26OCT2617-T112999.99']);
    const html = body().innerHTML;
    assert.match(html, /Bitcoin now<\/dt><dd><span class="fig ">\$113,420\.00<\/span><\/dd><dd class="sub-fig">Coinbase · 4s ago</);
    assert.match(html, />Strike<\/dt>.*>\$112,999\.99<.*Yes if Bitcoin settles above\u00a0it/);
    assert.match(html, />Spot vs strike<\/dt><dd><span class="fig ">\+\$420\.01<\/span><\/dd><dd class="sub-fig">0\.37% above the strike · on the Yes side</);
    assert.match(html, />Time left<\/dt>.*>1 hr 12 min<.*closes /);
    assert.doesNotMatch(html, /fig-behind|KXBTCD ·|BTC-USD/);
    // A 15-minute window's start price pays Yes at or above it (greater_or_equal), and the page says so.
    const {body: m15} = await openSpot(() => response({...SPOT, strike: {...SPOT.strike, value: 113384.12, inclusive: true, from: 'record'}}),
      {ticker: 'KXBTC15M-26OCT262345-45', series: 'KXBTC15M'});
    assert.match(m15().innerHTML, />Target price<\/dt><dd><span class="fig ">\$113,384\.12<\/span><\/dd><dd class="sub-fig">Yes if Bitcoin settles at or above\u00a0it</);
  });

  // A 15-minute window's page said "This window's start price isn't stored yet" under a heading reading "Target Price:
  // $113,512.08" (Kalshi's subtitle): with no stored strike the page takes it from the contract's own name and says so.
  test(`${name}: a 15-minute window with no stored strike reads its target price from the contract's title, and says so`, async () => {
    const M15 = {ticker: 'KXBTC15M-26OCT262345-45', series: 'KXBTC15M', title: 'BTC price up in next 15 mins?', sub: 'Target Price: $113,512.08'};
    const none = {...SPOT, ticker: M15.ticker, strike: null, vs: null};
    let {f, body} = await openSpot(() => response(none), M15);
    assert.match(f.root.querySelector('h1').textContent, /Target Price: \$113,512\.08/);
    let html = body().innerHTML;
    // The section, the figure and the distance all name it as the title does: "Bitcoin vs the strike" over a "Strike"
    // beside "Spot vs target price" named one line twice.
    assert.equal(body().closest('section').querySelector('h2').textContent, 'Bitcoin vs the target price');
    assert.match(html, />Target price<\/dt><dd><span class="fig ">\$113,512\.08<\/span><\/dd><dd class="sub-fig">Read from the contract’s title</);
    // Spot is measured against it as the server measures a strike line: by how much, never which side pays. It is
    // named as the title names it (and as Explore's list does), "target price", not "strike".
    assert.match(html, />Spot vs target price<\/dt><dd><span class="fig ">−\$92\.08<\/span><\/dd><dd class="sub-fig">0\.08% below the target price</);
    assert.doesNotMatch(html, /isn’t stored yet|on the (Yes|No) side|Spot vs strike|the strike|>Strike</);
    // Spot exactly on it says so in the same words.
    ({body} = await openSpot(() => response({...none, spot: {...SPOT.spot, price: 113512.08}}), M15));
    html = body().innerHTML;
    assert.match(html, />Spot vs target price<\/dt><dd><span class="fig ">At the target price</);
    // A stored start price still wins over the title, with the server's distance; on a 15-minute window it is still
    // its target price, as Kalshi names it.
    ({body} = await openSpot(() => response({...SPOT, ticker: M15.ticker, strike: {...SPOT.strike, value: 113384.12, inclusive: true, from: 'record'}}), M15));
    html = body().innerHTML;
    assert.match(html, />Target price<\/dt><dd><span class="fig ">\$113,384\.12<\/span><\/dd><dd class="sub-fig">Yes if Bitcoin settles at or above\u00a0it</);
    assert.match(html, />Spot vs target price<\/dt><dd><span class="fig ">\+\$420\.01<\/span><\/dd><dd class="sub-fig">0\.37% above the target price\u00a0· on the Yes side</);
    assert.doesNotMatch(html, /contract’s title|>Strike<|the strike/);
    // A stored strike on any other market keeps "strike" (the first case above).
    // Neither stored nor in the title: the honest line stays.
    ({body} = await openSpot(() => response(none), {...M15, sub: ''}));
    html = body().innerHTML;
    assert.match(html, />Target price<\/dt><dd><span class="fig ">—<\/span><\/dd><dd class="sub-fig">This window’s start price isn’t stored yet</);
    assert.equal(body().closest('section').querySelector('h2').textContent, 'Bitcoin vs the target price');
    assert.doesNotMatch(html, /Spot vs|>Strike</);
  });

  test(`${name}: a stored spot over two minutes old stays up and says plainly how old the feed is`, async () => {
    const {body} = await openSpot(() => response({...SPOT, spot: {...SPOT.spot, age_s: 420, stale: true}, vs: {side: 'below', diff: -499.99, pct: -0.442, yes: false}}));
    const html = body().innerHTML;
    assert.match(html, /class="m fig-behind"><dt class="lab">Bitcoin now<\/dt><dd><span class="fig ">\$113,420\.00<\/span><\/dd><dd class="sub-fig">Spot feed is 7 min old</);
    // The distance was measured from that old price, and its label says so too.
    assert.match(html, />Spot vs strike, 7 min ago<\/dt><dd><span class="fig ">−\$499\.99<\/span><\/dd><dd class="sub-fig">0\.44% below the strike · on the No side</);
  });

  test(`${name}: with no stored spot the section says so and still gives the strike and the time left`, async () => {
    const {body} = await openSpot(() => response({...SPOT, spot: null, vs: null}));
    const html = body().innerHTML;
    assert.match(html, />Bitcoin now<\/dt><dd><span class="fig ">—<\/span><\/dd><dd class="sub-fig">No stored price in the last day</);
    assert.match(html, />\$112,999\.99</); assert.match(html, />1 hr 12 min</);
    assert.doesNotMatch(html, /Spot vs/);
  });

  test(`${name}: a range bucket says whether spot is inside it, and how far outside it when not`, async () => {
    const bucket = {kind: 'range', value: 113249.99, lo: 113000, hi: 113499.99, inclusive: true, from: 'record'};
    let {body} = await openSpot(() => response({...SPOT, ticker: 'KXBTC-26OCT2617-B113250', strike: bucket, vs: {side: 'inside', diff: 0, pct: 0, yes: true, to_lo: 420, to_hi: 79.99}}),
      {ticker: 'KXBTC-26OCT2617-B113250', series: 'KXBTC'});
    let html = body().innerHTML;
    assert.match(html, />Bucket<\/dt><dd><span class="fig ">\$113,000\.00 to \$113,499\.99<\/span>/);  // to the cent, as Kalshi's own bounds
    assert.match(html, />Spot vs bucket<\/dt><dd><span class="fig ">Inside<\/span><\/dd><dd class="sub-fig">\$420\.00 above its floor · \$79\.99 below its top · on the Yes side</);
    ({body} = await openSpot(() => response({...SPOT, strike: bucket, vs: {side: 'above', diff: 100.02, pct: 0.088, yes: false}}), {ticker: 'KXBTC-26OCT2617-B113250', series: 'KXBTC'}));
    html = body().innerHTML;
    assert.match(html, />\+\$100\.02<\/span><\/dd><dd class="sub-fig">0\.09% above its top · on the No side</);
    // From the ticker alone only the bucket's centre is known, and the page says so.
    ({body} = await openSpot(() => response({...SPOT, strike: {...bucket, lo: null, hi: null, value: 113250, from: 'ticker'}, vs: {side: 'below', diff: -250, pct: -0.221, yes: null}}),
      {ticker: 'KXBTC-26OCT2617-B113250', series: 'KXBTC'}));
    html = body().innerHTML;
    assert.match(html, />Bucket centre<\/dt>.*its edges aren’t stored/);
    assert.match(html, />Spot vs centre<\/dt><dd><span class="fig ">−\$250\.00<\/span><\/dd><dd class="sub-fig">0\.22% below its centre</);
    assert.doesNotMatch(html, /on the (Yes|No) side/);
  });

  test(`${name}: the rest of a Bitcoin market's page draws while its spot read is still out`, async () => {
    const {f, body} = await openSpot(() => new Promise(() => {}));
    assert.match(f.root.innerHTML, /How it settles/); assert.ok(f.root.querySelector('#rawsect'));
    assert.match(body().innerHTML, /Reading Bitcoin’s latest stored price…/);
  });

  test(`${name}: a failed spot read says so with Try again, and the retry fills the section`, async () => {
    let calls = 0;
    const {body} = await openSpot(() => (++calls === 1 ? response({error: 'Bitcoin’s latest price didn’t load. Try again in a moment.'}, 503) : response(SPOT)));
    assert.match(body().innerHTML, /Bitcoin’s latest price didn’t load\. Try again in a moment\./);
    await body().querySelector('[data-spot-retry]').onclick(); await settle();
    assert.match(body().innerHTML, /\+\$420\.01/);
    // Walk 2026-10-28: Tau's generic words (a 500) or no reply said only "Something went wrong on our side." in the
    // section. It names what didn't load and that the rest of the page is there.
    for (const [answer, why] of [[() => response({error: 'Something went wrong on our side. It’s been logged.'}, 500), 'Something went wrong on our side. It’s been logged.'],
      [() => ({ok: false, status: 500, json: async () => { throw new SyntaxError('Unexpected token <'); }}), 'Tau is having trouble right now. Try again in a moment.']]) {
      const g = await openSpot(answer);
      assert.equal(g.body().querySelector('p.hint').textContent.trim(), `Bitcoin’s latest stored price didn’t load. ${why} Everything else on this page did. Try again`);
      assert.match(g.f.root.innerHTML, /How it settles/);
      g.f.clearTimers && g.f.clearTimers();
    }
  });

  // The figures carry the age Tau read them at ("Coinbase · 4s ago"), which stood still while the 15s poll
  // failed (a train, a lift): once it has failed for about two polls, a line says how old they really are.
  test(`${name}: spot figures a failing poll left up say how old they are, and the next good read clears it`, async () => {
    let fail = false;
    const {f, body} = await openSpot(() => (fail ? response({error: 'Something went wrong on our side.'}, 500) : response(SPOT)));
    const note = () => f.root.querySelector('#mk-spot-stale').textContent;
    const tick = async () => { for (const run of [...f.intervals.values()]) await run(); await settle(); };
    assert.equal(note(), '');
    fail = true;
    f.shiftClock(31000); await tick();
    assert.match(note(), /^Last updated 3\ds ago, retrying$/);
    assert.match(body().innerHTML, /Coinbase\u00a0· 4s ago/, 'the last figures stay up');
    fail = false;
    f.shiftClock(31000); await tick(); await tick();
    assert.equal(note(), '');
    f.clearTimers();
  });

  test(`${name}: a market that isn't a Bitcoin contract, or a settled one, has no spot section and asks for none`, async () => {
    const {f, asked} = await openSpot(() => response(SPOT), {ticker: 'KXETHD-26OCT2617-T4000', series: 'KXETHD'});
    assert.equal(f.root.querySelector('#mk-spot'), null);
    assert.deepEqual(asked.filter((p) => p.startsWith('/api/explore/spot?')), []);
    // A settled one's read started with the page's (it isn't known to be settled until then); it is never drawn.
    const {f: g} = await openSpot(() => response(SPOT), {result: 'yes', status: 'finalized'});
    assert.equal(g.root.querySelector('#mk-spot'), null);
  });

  // With Kalshi unreachable the page draws the Explore snapshot: its close (from the ticker) is a time, and the raw
  // data section said "Waiting on Kalshi for the candles." under a chart that already said they didn't load.
  test(`${name}: a market drawn from the snapshot says when it closes and that its candles didn't come, not that it waits`, async () => {
    const f = await open(page({points: [], period_min: null, history_unavailable: true, snapshot: true, rules: undefined}));
    assert.match(f.root.innerHTML, /Price history didn’t load/);
    const raw = f.root.querySelector('#rawsect').innerHTML;
    assert.match(raw, /None to show: Kalshi didn’t send this market’s price history just now\. Try again under Price history\./);
    assert.doesNotMatch(raw, /Waiting/);
    const closes = /<dt class="lab">Closes<\/dt><dd><span class="fig[^"]*">(.*?)<\/span>/.exec(f.root.innerHTML);
    assert.ok(closes && /21:00/.test(closes[1]) && !/—/.test(closes[1]), closes && closes[1]);
  });

  // Walked 2026-10-28: a link to a market Kalshi doesn't have read "Kalshi has no market KXNOPE-26OCT28-X." over a
  // Try again that could only fail the same way.
  test(`${name}: a market Kalshi has no record of says so in words, with only the way back to Explore`, async () => {
    let calls = 0;
    const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore/market?')
      ? (calls++, response({error: 'Kalshi has no market KXNOPE-26OCT28-X.'}, 404)) : response({}))});
    f.location.pathname = '/explore'; f.location.search = '?m=KXNOPE-26OCT28-X';
    await f.viewExplore(); await settle();
    const main = f.root.querySelector('#main');
    assert.match(main.textContent, /Kalshi has no market at this link\. It may have been taken down, or the link is incomplete\./);
    assert.doesNotMatch(main.innerHTML, /KXNOPE/, 'no raw code from the link');
    assert.equal(main.querySelector('#mk-retry'), null, 'no Try again that can only fail again');
    assert.equal(main.querySelector('a.btn').getAttribute('href'), '/explore');
    assert.equal(calls, 1);
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

  // Walk 2026-10-27, a Bitcoin market page at 390px: Kalshi's rules read "CF Benchmarks' Bitcoin" with a straight
  // apostrophe and broke "before 5" from "PM EDT"; "bid 58¢" ended a line and "/ ask 61¢" began the next; "Closes Oct
  // 28, 02:45" left "UTC" alone; "Yes if Bitcoin settles above" left "it" alone.
  test(`${name}: a Bitcoin market page keeps its times, quote and Kalshi's rules on readable lines`, async () => {
    const rules = 'If the simple average of the sixty seconds of CF Benchmarks\' Bitcoin Real-Time Index (BRTI) before 5 PM EDT is above 112999.99 at 5 PM EDT on Oct 27, 2026, then the market resolves to Yes.';
    const f = await open(page({rules, rules_more: 'Kalshi\'s rules don\'t change after a market opens.'}));
    const [main, more] = f.root.querySelectorAll('p.mk-rules').map((p) => p.textContent);
    assert.equal(main, 'If the simple average of the sixty seconds of CF Benchmarks’ Bitcoin Real-Time Index (BRTI) before 5 PM EDT is above 112999.99 at 5 PM EDT on Oct 27, 2026, then the market resolves to Yes.');
    assert.equal(more, 'Kalshi’s rules don’t change after a market opens.');
    assert.doesNotMatch(f.root.innerHTML, /[A-Za-z]'/, 'no straight apostrophe after a letter anywhere on the page');
    const html = f.root.innerHTML;
    assert.match(html, /bid 55¢ \/ ask 57¢/);
    assert.match(html, /as of [^<·]* [A-Z]{2,5}<\/dd>/, 'the read time keeps its zone');
    assert.match(html, /Closes<\/dt><dd><span class="fig ">[^<]*\d [A-Z]{2,5}<\/span>/, 'the close keeps its zone');
  });
}
