// Shared cases, run against each bundle's offline harness (Tau and Meridian): Deploy, the dashboard and the
// strategy page never imply something is trading that isn't, and never show a raw internal identifier.
// - With the server's live switch closed (/api/me's live_trading_available false), the engine places no live
//   orders: it pauses a running live deployment the next time it checks the market, the server refuses Resume
//   on a live one, and nothing a live deployment holds can be sold. So a running live deployment reads
//   "Waiting: live trading isn't open yet", never "Running" or "1 on live money", and Resume is offered
//   disabled, saying why. A Bitcoin perpetual deployment (research-only: no book trades it) says so too.
// - A position names its market in plain words with its own strike ("Bitcoin above $68,499.99 at 5pm ET");
//   its Kalshi ticker, which carries the raw series key, only sits on a small "Kalshi contract" line.
// - A strategy row never shows its zero-padded id.
import assert from './assert_text.mjs';
import {test} from 'node:test';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise((resolve) => setImmediate(resolve));
const settle = async () => { for (let i = 0; i < 6; i++) await flush(); };
const WAITING = 'Waiting', NO_ORDERS = 'Live trading isn’t open yet, so this places no orders';
const TICKER = 'KXBTCD-26OCT2617-T68499.99', NAME = 'Bitcoin above $68,499.99 at 5pm ET';
const TICKER15 = 'KXBTC15M-26OCT262100-00', NAME15 = 'Bitcoin up or down in 15 minutes';
const MARKETS = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above $X at 5pm ET', close_hour_et: 17},
  {key: 'btc15m', series: 'KXBTC15M', label: NAME15}];
const dep = (overrides = {}) => ({id: 1, strategy_id: 1, title: 'Paper one', market: 'btc15m', mode: 'paper', status: 'running',
  status_reason: null, realized_pnl: 1, closed_trades: 5, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z',
  curve: [], stake: 5, max_positions: 1, backtest: {out_of_sample: null}, ...overrides});
const pos = (overrides = {}) => ({id: 11, deployment_id: 2, title: 'Live one', ticker: TICKER, side: 'yes', qty: 2, entry_price: 0.4,
  entry_fee: 0.02, cost: 0.82, at_cost: 0.8, unrealized: null, mode: 'live', opened_at: '2026-10-26T08:00:00Z',
  market_close_time: '2030-01-15T22:00:00Z', closed_at: '2026-10-26T09:00:00Z', pnl: 0.2, ...overrides});
// The page with every link target and every "Kalshi contract" line taken out: what is left is what reads as a
// name, and no ticker may stand there.
const named = (html) => html.replace(/ (href|aria-label|title|data-[a-z-]+)="[^"]*"/g, '')
  .replace(/<span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">[^<]*<\/span><\/span>/g, '');
// One table row's (or monitor card's) HTML, by the deployment title it carries.
const rowOf = (html, title) => html.split(/<tr\b|<article\b/).find((r) => r.includes(`>${title}</a>`)) || '';

export function liveHonestCases({name, frontend, strategyFrontend, detailStrategy, dashboard}) {
  const board = async ({open, deployments, open_positions = []}) => {
    const sent = [];
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments' || path.startsWith('/api/deployments?')) return response({deployments, open_positions});
      sent.push(path);
      return response({});
    }});
    f.sent = sent;
    f.S.me.live_trading_available = open; f.S.me.markets = MARKETS;
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    return f;
  };
  const LIVE = dep({id: 2, strategy_id: 2, title: 'Live one', mode: 'live', open_positions: 2});

  test(`${name}: with live trading closed, a running live deployment says it is waiting and places no orders, never Running or on live money`, async () => {
    const f = await board({open: false, deployments: [dep(), LIVE]});
    const figs = f.root.querySelector('#dfigs').innerHTML, deps = f.root.querySelector('#deps').innerHTML;
    assert.doesNotMatch(figs, /\d on live money/);
    assert.match(figs, /1 live, placing no orders: live trading isn’t open yet/);
    assert.match(figs, /1 placing no orders/);  // counted apart from the one running on paper
    const live = rowOf(deps, 'Live one');
    assert.ok(live, deps);
    assert.match(live, new RegExp(WAITING)); assert.doesNotMatch(live, /Running/);
    assert.match(live, new RegExp(NO_ORDERS + ', and Tau can’t sell its 2 open positions, which stay open until their markets settle\\. Tau pauses it the next time it checks the market\\.'));
    assert.match(live, /data-act="pause"/);  // the user can still pause it
    // The paper row beside it is untouched.
    assert.doesNotMatch(rowOf(deps, 'Paper one'), /Waiting|places no orders/);
    f.clearTimers();
    // Open, the same board reads as before.
    const g = await board({open: true, deployments: [dep(), LIVE]});
    assert.match(g.root.querySelector('#dfigs').innerHTML, /1 on live money/);
    assert.doesNotMatch(g.root.querySelector('#deps').innerHTML, /Waiting|places no orders/);
    g.clearTimers();
  });

  test(`${name}: with live trading closed, Resume on a paused live deployment is offered disabled, saying why, and sends nothing`, async () => {
    const f = await board({open: false, deployments: [{...LIVE, status: 'paused', status_reason: 'Live trading is not enabled on this server yet.'}]});
    const btn = f.root.querySelector('#deps [data-dep="2"][data-act="resume"]');
    assert.ok(btn); assert.equal(btn.disabled, true);
    assert.equal(btn.getAttribute('title'), 'Live trading isn’t open yet.');
    btn.onclick(); await settle();
    assert.deepEqual(f.sent.filter((p) => p.startsWith('/api/deployments/')), [], 'nothing is sent');
    f.clearTimers();
    const g = await board({open: true, deployments: [{...LIVE, status: 'paused'}]});
    assert.equal(g.root.querySelector('#deps [data-dep="2"][data-act="resume"]').disabled, false);
    g.clearTimers();
  });

  test(`${name}: a running Bitcoin perpetual deployment says it places no orders and isn't counted running`, async () => {
    const f = await board({open: true, deployments: [dep({id: 3, title: 'Perp one', market: 'btc_perp'})]});
    const row = rowOf(f.root.querySelector('#deps').innerHTML, 'Perp one');
    assert.match(row, /Bitcoin perpetuals are research-only, so this places no orders\./); assert.doesNotMatch(row, /Running/);
    assert.match(f.root.querySelector('#dfigs').innerHTML, /1 placing no orders/);
    f.clearTimers();
  });

  test(`${name}: Deploy's open positions name the market with its strike, and the Kalshi ticker only on a small line`, async () => {
    const f = await board({open: true, deployments: [LIVE], open_positions: [pos(), pos({id: 12, ticker: TICKER15, market_close_time: '2030-01-15T21:00:00Z'})]});
    const html = f.root.querySelector('#openpos').innerHTML;
    assert.ok(html.includes(NAME), html); assert.ok(html.includes(NAME15), html);
    for (const t of [TICKER, TICKER15]) {
      assert.ok(html.includes(`<span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">${t}</span></span>`), t);
      assert.ok(!named(html).includes(t), `${t} is never the headline`);
    }
    assert.ok(!/KXBTC15M|KXBTCD/.test(named(html)), 'no raw series key either');
    f.clearTimers();
  });

  test(`${name}: the dashboard says live trading isn't open, names positions by their market, and never shows the ticker`, async () => {
    const data = {...dashboard(), deployments: [LIVE], open_positions: [pos(), pos({id: 12, ticker: TICKER15})],
      recent_closed: [pos({id: 13, ticker: TICKER15, status: 'closed'})]};
    data.live = {...data.live, connected: true, balance: 50, realized_pnl: 17, today_pnl: 0, open_positions: 2, open_at_cost: 1.6};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/dashboard' || path.startsWith('/api/dashboard?')) return response(data);
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      return response({});
    }});
    f.S.me.live_trading_available = false; f.S.me.markets = MARKETS;
    await f.viewDashboard(); await settle();
    const html = f.root.querySelector('#boardbody').innerHTML + f.root.querySelector('#main').innerHTML;
    assert.doesNotMatch(html, /Live money on/);
    assert.match(html, /Live trading isn’t open yet: \+\$17\.00 realized all time on live money/);
    assert.doesNotMatch(rowOf(f.root.querySelector('#dash-deps').innerHTML, 'Live one'), /Running/);
    assert.ok(html.includes(NAME) && html.includes(NAME15), 'each position names its market');
    for (const t of [TICKER, TICKER15]) assert.ok(!named(html).includes(t), `${t} is never the headline`);
    f.clearTimers();
  });

  test(`${name}: the strategy page names its holdings and trades by market, and its live rung waits while live trading is closed`, async () => {
    const live = {id: 2, mode: 'live', status: 'running', realized_pnl: 0, closed_trades: 0, created_at: '2026-10-24T08:00:00Z'};
    const s = strategyFrontend(detailStrategy({market: 'btc_daily', deployments: [live], holdings: [pos()],
      recent_trades: [{opened: '2026-10-24T10:15Z', ticker: TICKER, side: 'yes', qty: 2, entry: 0.4, exit: 1, pnl: 1.2, reason: 'settled'}]}));
    s.S.me.live_trading_available = false; s.S.me.markets = MARKETS;
    await s.viewStrategy(42); await settle();
    const html = s.root.querySelector('#main').innerHTML;
    assert.ok(html.includes(NAME), 'holding and trade name the market');
    assert.ok(html.includes(`<span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">${TICKER}</span></span>`));
    assert.ok(!named(html).includes(TICKER), 'the ticker is never the headline');
    // The deploy panel's list of its deployments says the same, never "Live (running)".
    assert.match(html, /Live[^<]{0,4}(\(|\u00a0· )waiting: live trading isn’t open yet/);
    assert.doesNotMatch(html, /Live[^<]{0,4}(\(|\u00a0· )running/);
    const ladder = s.root.querySelector('#ladder-body').innerHTML;
    assert.match(ladder, /<span class="mk live">Live<\/span> waiting: live trading isn’t open yet, so it places no orders/);
    assert.doesNotMatch(ladder, /Live<\/span> running|it trades live money/);
  });

  test(`${name}: a strategy row shows its title, never a zero-padded id`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = f.strategySlip({id: 7, title: 'Fade the spike', thesis: '', market: 'btc15m', status: 'passed',
      out_of_sample: {pnl: 1, trades: 3, win_rate: 0.5}}, {});
    assert.match(row, />Fade the spike</);
    assert.doesNotMatch(row, /strategy-ref|\b0007\b/);
  });

  // The rest of the surfaces with a "Live" or "running" badge: the Strategies list, a shared deployment's
  // Community card, the autopilot panel and the dashboard's autopilot card say it waits, in the same words.
  const WAIT_MARK = /<span class="mk quiet live-wait" title="Live trading isn’t open yet\.">Waiting<span class="vh">: live trading isn’t open yet<\/span><\/span>/;
  const IDLE_COUNT = '1 live, placing no orders: live trading isn’t open yet';

  test(`${name}: a Strategies row with a live book says it waits while live trading is closed, and why, on a phone too`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const row = (open, real = {pnl: 0, trades: 0, open: 1, mode: 'live', live: true}) => {
      f.S.me.live_trading_available = open;
      return f.strategySlip({id: 7, title: 'Daily drift', thesis: '', market: 'btc15m', status: 'passed', deployed: true, deploy_live: true,
        books: ['live', 'paper'], real, out_of_sample: {pnl: 1, trades: 3, win_rate: 0.5}}, {});
    };
    const closed = row(false);
    assert.match(closed, /<span class="mk live">Live \+ paper<\/span> <span class="mk quiet live-wait"/);
    assert.match(closed, WAIT_MARK);
    assert.match(closed, /<div class="sub-fig live-wait-why">Live trading isn’t open yet, so this places no orders\.<\/div>/);
    // A paused live book reads Paused, not Waiting beside it; the line still says why it places nothing.
    const paused = row(false, {pnl: 0, trades: 0, open: 0, mode: 'live', live: true, paused: true});
    assert.doesNotMatch(paused, /live-wait"/); assert.match(paused, />Paused</); assert.match(paused, /live-wait-why/);
    const open = row(true);
    assert.match(open, /<span class="mk live">Live \+ paper<\/span>/);
    assert.doesNotMatch(open, /Waiting|live-wait|places no orders/);
  });

  test(`${name}: a shared live deployment's Community card says it waits while live trading is closed`, () => {
    const f = frontend({fetchImpl: () => response({})});
    const card = {kind: 'deployment', id: 3, title: 'Daily drift', market: 'btc15m', mode: 'live', realized_pnl: 1.25, closed_trades: 3, since: '2026-10-20T08:00:00Z'};
    f.S.me.live_trading_available = false;
    assert.match(f.postSnapshot(card, ''), WAIT_MARK);
    assert.doesNotMatch(f.postSnapshot({...card, mode: 'paper'}, ''), /Waiting/);
    f.S.me.live_trading_available = true;
    assert.doesNotMatch(f.postSnapshot(card, ''), /Waiting/);
  });

  test(`${name}: the autopilot panel and its dashboard card count a live strategy apart while live trading is closed`, async () => {
    const status = {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 0, passed_7d: 0}, live_running: 1, paper_running: 2,
      demo_running: 0, today_live_pnl: 0, loss_headroom: 50, daily_loss_limit: 50, autopilot_live: false, story: []};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/dashboard' || path.startsWith('/api/dashboard?')) return response(dashboard());
      if (path === '/api/autopilot/status') return response(status);
      return response({messages: [], models: []});
    }});
    f.S.me.live_trading_available = false; f.S.me.user.autopilot = true;
    const box = new (f.root.constructor)('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl>';
    await f.apUpdate(box, status); await settle();
    const stats = box.querySelector('#apf-stats').innerHTML;
    // The panel's half-row figure says it short (its own case below); the dashboard card's line says it in full.
    assert.ok(stats.includes('1 live (waiting)<span class="vh">: live trading isn’t open yet, so it places no orders</span></span> · 2 paper'), stats);
    assert.ok(!stats.includes(IDLE_COUNT), stats);
    assert.doesNotMatch(stats, /class="apf-live">1 live/);
    f.S.ap = status;
    await f.viewDashboard(); await settle();
    f.S.ap = status; f.paintDashAp();
    const card = f.root.querySelector('#dash-ap').innerHTML;
    assert.match(card, new RegExp(`<dt>Strategies running</dt><dd>2 <small>${IDLE_COUNT}</small></dd>`));
    // Open, the counts read as before.
    f.S.me.live_trading_available = true; f.paintDashAp();
    assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Strategies running<\/dt><dd>3<\/dd>/);
    await f.apUpdate(box, status); await settle();
    assert.match(box.querySelector('#apf-stats').innerHTML, /class="apf-live">1 live<\/span>/);
    f.clearTimers();
  });

  // The panel's Running figure shares its row with another figure (two to a row on a phone): "1 live, placing
  // no orders: live trading isn't open yet · 2 paper" wrapped to four lines there. It reads "1 live (waiting)",
  // kept on one line, and the reason rides its hover and screen-reader text.
  test(`${name}: the autopilot panel's Running figure says a live strategy waits in a few words, the reason on hover and read out`, async () => {
    const status = {autopilot: true, mode: 'paper', research: {active: [], tested_7d: 0, passed_7d: 0}, live_running: 1, paper_running: 2,
      demo_running: 0, today_live_pnl: 0, loss_headroom: 50, daily_loss_limit: 50, autopilot_live: false, story: []};
    const f = frontend({fetchImpl: () => response({messages: [], models: []})});
    f.S.me.live_trading_available = false; f.S.me.user.autopilot = true;
    const box = new (f.root.constructor)('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl>';
    const running = async (st) => {
      await f.apUpdate(box, st); await settle();
      const html = box.querySelector('#apf-stats').innerHTML;
      return /<dt>Running<\/dt><dd>(.*?)<\/dd>/.exec(html)[1];
    };
    const one = await running(status);
    assert.equal(one, '<span class="apf-live-wait" title="Live trading isn’t open yet, so it places no orders.">1 live (waiting)'
      + '<span class="vh">: live trading isn’t open yet, so it places no orders</span></span> · 2 paper');
    // What a sighted reader sees: short enough for a phone's half-row cell.
    const seen = one.replace(/<span class="vh">.*?<\/span>/g, '').replace(/<[^>]+>/g, '');
    assert.equal(seen, '1 live (waiting) · 2 paper');
    assert.ok(seen.length <= 28, seen);
    assert.doesNotMatch(one, /placing no orders: live trading/);
    const two = await running({...status, live_running: 2});
    assert.match(two, /title="Live trading isn’t open yet, so they place no orders\.">2 live \(waiting\)/);
    // Open, it is the plain live count.
    f.S.me.live_trading_available = true;
    assert.equal(await running(status), '<span class="apf-live">1 live</span> · 2 paper');
    f.clearTimers();
  });

  test(`${name}: the strategy page's heading is its title, never its zero-padded id`, async () => {
    const s = strategyFrontend(detailStrategy({id: 2, title: 'Fade the spike', market: 'btc15m'}));
    await s.viewStrategy(42); await settle();
    const head = s.root.querySelector('.board-title').outerHTML;
    assert.doesNotMatch(head + s.root.querySelector('#main').innerHTML, /No\.\s*0\d+|\b0000[0-9]\b/);
    assert.match(head, /<h1 class="page">Fade the spike<\/h1>/);
    // Said once: Tau's paper header just below the heading said it again as a second, 34px heading.
    const headings = s.root.querySelectorAll('h1, h2, h3').map((h) => h.textContent.trim());
    assert.deepEqual(headings.filter((t) => t === 'Fade the spike'), ['Fade the spike'], headings.join(' | '));
    assert.equal(s.root.querySelectorAll('.paper-title').length, 0);
    s.clearTimers();
  });

  test(`${name}: a dashboard whose every deployment is paused says how many, never "Nothing deployed"`, async () => {
    const data = {...dashboard(), deployments: [dep({status: 'paused', status_reason: 'Paused by you.'}), dep({id: 2, title: 'Two', status: 'paused'})]};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/dashboard' || path.startsWith('/api/dashboard?')) return response(data);
      return response({autopilot: false, mode: 'off'});
    }});
    await f.viewDashboard(); await settle();
    const html = f.root.querySelector('#boardbody').innerHTML + f.root.querySelector('#main').innerHTML;
    assert.doesNotMatch(html, /Nothing deployed/);
    const said = /<a class="needs-link" href="([^"]+)"><em>2 paused, needs you<\/em><\/a>/.exec(html);
    assert.ok(said, html.slice(0, 600));
    // Tau's status line links to Deploy, where both wait; Meridian's to the first paused card beside it.
    assert.equal(said[1], name === 'Tau' ? '/deploy' : '#dash-paused');
    f.clearTimers();
  });

  test(`${name}: the board's 10s poll carries the live switch, so an open board follows a flip without a reload`, async () => {
    let answer = {deployments: [LIVE], open_positions: [], live_trading_available: true, v: 'a1'};
    const f = frontend({fetchImpl: (path) => {
      if (path === '/api/deployments' || path.startsWith('/api/deployments?')) return response(answer);
      return response({});
    }});
    f.S.me.live_trading_available = true; f.S.me.markets = MARKETS;
    f.location.pathname = '/deploy';
    await f.viewDeploy(); await settle();
    assert.doesNotMatch(f.root.querySelector('#deps').innerHTML, /Waiting/);
    // The server's switch closed (a restart): the next poll's answer has a new version and says so.
    answer = {...answer, live_trading_available: false, v: 'a2'};
    const meReads = () => f.requests.filter(({path}) => path === '/api/me').length, before = meReads();
    const ticks = [...f.intervals.values()];
    for (const tick of ticks) { await tick(); await settle(); }
    assert.equal(f.S.me.live_trading_available, false);
    assert.match(rowOf(f.root.querySelector('#deps').innerHTML, 'Live one'), new RegExp(WAITING));
    assert.match(f.root.querySelector('#dfigs').innerHTML, /1 live, placing no orders/);
    // A "same" answer keeps it; no extra read of /api/me was made for it.
    answer = {v: 'a2', same: true, marks: {}, unrealized: {}};
    for (const tick of ticks) { await tick(); await settle(); }
    assert.equal(f.S.me.live_trading_available, false);
    assert.equal(meReads(), before);
    f.clearTimers();
  });
}
