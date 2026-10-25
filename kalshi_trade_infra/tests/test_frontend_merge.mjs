import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import vm from 'node:vm';
import {perpsFrontendCases} from './kalshi_perps_frontend_cases.mjs';

const require = createRequire(import.meta.url);
const brokerConnections = require('../app/static/broker-connections.js');
const source = readFileSync(new URL('../app/static/app.js', import.meta.url), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

// Parse the rendered controls: absent selectors return null, and replacing a
// section creates new controls. The harness never starts a browser or network.
class Element {
  constructor(tag = 'div', attributes = {}) {
    this.tag = tag; this.attributes = {...attributes}; this.dataset = {};
    this.children = []; this.listeners = new Map(); this.style = {}; this.writes = 0;
    this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 100; this.clientWidth = 760;
    this.hidden = 'hidden' in attributes; this.value = attributes.value || '';
    this.checked = 'checked' in attributes; this.disabled = 'disabled' in attributes;
    this.classes = new Set((attributes.class || '').split(/\s+/).filter(Boolean));
    for (const [key, value] of Object.entries(attributes)) if (key.startsWith('data-')) {
      this.dataset[key.slice(5).replace(/-([a-z])/g, (_, x) => x.toUpperCase())] = value;
    }
    this.classList = {
      add: (...xs) => xs.forEach(x => this.classes.add(x)),
      remove: (...xs) => xs.forEach(x => this.classes.delete(x)),
      contains: x => this.classes.has(x),
      toggle: (x, force = !this.classes.has(x)) => { force ? this.classes.add(x) : this.classes.delete(x); return force; },
    };
  }
  get isConnected() { return !this.removed && (!this.parent || this.parent.isConnected); }
  get className() { return [...this.classes].join(' '); }
  set className(value) { this.classes = new Set(value.split(/\s+/)); }
  get id() { return this.attributes.id; }
  set id(value) { this.attributes.id = value; }
  get innerHTML() { return this.html || ''; }
  set innerHTML(value) {
    this.html = value; this.writes++; this.children.forEach(child => { child.removed = true; }); this.children = [];
    const stack = [{element: this, start: 0}];
    const voids = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
    for (const match of value.matchAll(/<\/?([a-z][\w-]*)\b([^>]*)>/gi)) {
      const tag = match[1].toLowerCase();
      if (match[0].startsWith('</')) {
        if (stack.length > 1 && stack.at(-1).element.tag === tag) {
          const closed = stack.pop(); closed.element.html = value.slice(closed.start, match.index);
        }
      } else {
        const attributes = {};
        for (const [, key, quoted, single, bare] of match[2].matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) attributes[key] = quoted ?? single ?? bare ?? '';
        const child = new Element(tag, attributes); stack.at(-1).element.appendChild(child);
        if (!voids.has(tag) && !match[0].endsWith('/>')) stack.push({element: child, start: match.index + match[0].length});
      }
    }
  }
  get textContent() { return this.text ?? this.innerHTML.replace(/<[^>]*>/g, ''); }
  set textContent(value) { this.text = String(value); }
  matches(selector) {
    const tag = selector.match(/^[\w-]+/);
    if (tag && this.tag !== tag[0]) return false;
    for (const [, id] of selector.matchAll(/#([\w-]+)/g)) if (this.id !== id) return false;
    for (const [, cls] of selector.matchAll(/\.([\w-]+)/g)) if (!this.classes.has(cls)) return false;
    for (const [, key, quoted, bare] of selector.matchAll(/\[([\w-]+)(?:=(?:"([^"]*)"|([^\]]+)))?\]/g)) {
      if (!(key in this.attributes) || (quoted ?? bare) !== undefined && this.attributes[key] !== (quoted ?? bare)) return false;
    }
    return true;
  }
  querySelectorAll(selector) {
    const parts = selector.trim().split(/\s+(?![^\[]*\])/), found = [];
    const visit = element => element.children.forEach(child => {
      if (child.matches(parts.at(-1))) {
        let parent = child.parent, index = parts.length - 2;
        while (parent && index >= 0) { if (parent.matches(parts[index])) index--; parent = parent.parent; }
        if (index < 0) found.push(child);
      }
      visit(child);
    });
    visit(this); return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector) || null; }
  contains(element) { return element === this || this.children.some(child => child.contains(element)); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  dispatchEvent(event) { this.listeners.get(event.type)?.(event); }
  appendChild(child) { this.children.push(child); child.parent = this; }
  insertAdjacentHTML(_position, html) { this.html = (this.html || '') + html; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  focus() {}
  remove() { this.removed = true; }
}

function frontend({fetchImpl, brokerMount} = {}) {
  const root = new Element('div', {id: 'app'}), body = new Element('body'); body.appendChild(root);
  const intervals = new Map(), timeouts = new Map(), requests = [], navigations = [];
  let nextId = 0;
  const location = {pathname: '/strategies/42', search: '', origin: 'http://offline.invalid'};
  const navigate = (_state, _title, path) => { navigations.push(path); const [p, q] = String(path).split('?'); location.pathname = p; location.search = q ? '?' + q : ''; };
  const context = vm.createContext({
    Intl, URL, URLSearchParams, AbortController,
    document: {body, getElementById: id => body.querySelector('#' + id), addEventListener() {}, removeEventListener() {}, createElement: tag => new Element(tag)},
    window: {addEventListener() {}, scrollTo() {}, matchMedia: () => ({matches: false}),
      ...(brokerMount ? {TauBrokerConnections: {mount: brokerMount}} : {})},
    addEventListener() {}, location, history: {pushState: navigate, replaceState: navigate},
    localStorage: {getItem: () => null, setItem() {}},
    setInterval: callback => { intervals.set(++nextId, callback); return nextId; },
    clearInterval: id => intervals.delete(id),
    setTimeout: callback => { timeouts.set(++nextId, callback); return nextId; },
    clearTimeout: id => timeouts.delete(id),
    fetch: async (path, options) => {
      requests.push({path, options});
      if (path === '/api/notifications') return response({unread: 0, items: []});
      if (fetchImpl) return fetchImpl(path, options);
      throw new Error('Unexpected offline request: ' + path);
    },
  });
  const boot = '  setupGlossary();\n  render();';
  assert.equal(source.split(boot).length, 2, 'the harness replaces only automatic boot');
  vm.runInContext(source.replace(boot, 'globalThis.frontend = {S, api, routes, equityChart, runControls, runFeed, clearTimers, runRow, feedMd, viewStrategy, viewStrategies, strategySlip, postSnapshot, viewRun, viewFunds, viewBilling, viewDashboard, viewDeploy, viewResearch, viewExplore, marketPicker, wireMarketPicker, paintDashAp, apUpdate, trCurve, trackRecordPanel, viewMarketDetail, render};'), context);
  const api = context.frontend;
  api.S.me = {user: {id: 7, name: 'Offline fixture'}, markets: [], directions: [], live_trading_available: true, kalshi_connected: true, kalshi_dev_connected: true};
  // Cached global widgets keep these page checks focused. All requests still use
  // the offline transport above, including notifications and financial controls.
  api.S.hot = {markets: []}; api.S.hotAt = Date.now();
  api.S.ap = {mode: 'off'}; api.S.apAt = Date.now();
  return {...api, root, intervals, timeouts, requests, navigations};
}

const strategy = {id: 42, status: 'passed', side: 'yes', stake: 5, deployments: []};
const metrics = pnl => ({pnl, trades: 6, win_rate: .5, fees: 1, profit_factor: 1.2, max_drawdown: 2, sharpe: .5, roi: .1});
const detailStrategy = overrides => ({
  ...strategy, title: '<unsafe> test', thesis: '**Saved** <img src=x onerror=alert(1)>',
  market: 'btc15m', direction: 'momentum', created_at: '2026-10-17T10:00:00Z',
  hypotheses_tried: 5, rules: ['<script>bad()</script>'], spec: {rule: '<script>bad()</script>'},
  in_sample: metrics(20), out_of_sample: metrics(12), equity: [[100, 0], [200, 5], [300, 12]],
  experiment: {mechanism: {who_pays: '<b>Counterparty</b>'}, null_hypothesis: '<script>bad()</script>', classification: 'promising'},
  ...overrides,
});
function strategyFrontend(detail = detailStrategy(), transport) {
  return frontend({fetchImpl: (path, options) => {
    if (path === '/api/strategies/42') return response(detail);
    if (path === '/api/strategies/42/dev-curve') return response({dev_curve: [[200, 1], [300, 2]]});
    return transport(path, options);
  }});
}
const postRequests = f => f.requests.filter(({options}) => options.method === 'POST');
perpsFrontendCases({name: 'Tau', frontend, detailStrategy, strategyFrontend, postRequests});
const funds = () => ({kalshi: {connected: false}, kalshi_dev: {connected: false},
  demo: {capital: 1000, equity: 1001, realized: 1}, paper: {cash: 1000, ledger: [
    {created_at: '2026-10-17T10:00:00Z', memo: '<script>ledger</script>', amount: 10},
  ]}});

test('road to live says plainly when paper is losing money against the backtest', async () => {
  for (const [realization, said] of [[-0.18, /Paper is <b>losing money<\/b> per trade, while the backtest made money on unseen data\./], [0.6, /Paper earns <b>60%<\/b> of the backtest/]]) {
    const readiness = {ready: false, blocking: 'the gatekeeper has not cleared it', deployment_candidate: false, live_autopilot: {ok: false},
      paper: {trades: 12, trades_needed: 30, net_pnl: -0.76, events: 12, events_needed: 20, span_hours: 5, span_needed_hours: 48,
        p_value: null, p_value_needed: 0.1, recent_trades: 6, recent_net_pnl: 2.64, realization,
        checks: {realistic_trades: false, net_pnl: false, events: false, span: false, edge: false, recent: true}}};
    const f = strategyFrontend(detailStrategy(), path => {
      if (path === '/api/strategies/42/live-readiness') return response(readiness);
      return response({});
    });
    await f.viewStrategy(42); await flush(); await flush();
    const body = f.root.querySelector('#road-live-body');
    assert.ok(body, 'road to live panel renders');
    assert.match(body.innerHTML, said);
    assert.doesNotMatch(body.innerHTML, /-18%/);
    // The span gate measures first to last trade, not time since deploying, which the page shows separately.
    assert.match(body.innerHTML, /First to last paper trade/); assert.doesNotMatch(body.innerHTML, /Paper track record/);
    f.clearTimers();
  }
});

test('a signed-out deep link signs in back to the same page', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/me') return response({error: 'Please sign in.'}, 401);
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = null;
  await f.render(); await flush(); await flush();
  assert.deepEqual(f.navigations, ['/signin?next=%2Fstrategies%2F42']);
  const google = f.root.querySelectorAll('a[data-native]').map(a => a.getAttribute('href')).filter(h => h.startsWith('/auth/google'));
  assert.ok(google.length >= 1);
  assert.deepEqual([...new Set(google)], ['/auth/google?next=%2Fstrategies%2F42']);
});

test('the current strategy page renders an escaped research paper and a separate real demo curve', async () => {
  const f = strategyFrontend(); await f.viewStrategy(42); await flush();
  const output = f.root.querySelector('main').innerHTML;
  for (const label of ['Abstract', 'Mechanism &amp; hypothesis', 'Methodology', 'Results', 'Verdict']) assert.ok(output.includes(label));
  assert.match(output, /class="sheet-doc paper"/);
  assert.match(output, /&lt;b&gt;Counterparty&lt;\/b&gt;/);
  assert.match(output, /<b>Saved<\/b> &lt;img/);
  assert.doesNotMatch(output, /<unsafe>|<img|<script>|\[object Object\]/);
  assert.match(output, /id="dep-live"/); assert.match(output, /Type <b>LIVE<\/b>/);
  const chart = f.root.querySelector('#equity-wrap').innerHTML;
  assert.match(chart, /Kalshi dev \(real\)/); assert.doesNotMatch(chart, /NaN|undefined/);
});

test('the sidebar lists each holding with every figure instead of a clipped five-column table', async () => {
  const holdings = [{ticker: 'KXBTC15M-<x>', side: 'no', qty: 4, entry_price: 0.37, cost: 1.5, unrealized: null, mode: 'paper', market_close_time: '2026-10-25T07:30:00Z'},
    {ticker: 'KXBTC15M-B', side: 'yes', qty: 2, entry_price: 0.6, cost: 1.2, unrealized: -0.3, mode: 'live', market_close_time: '2026-10-25T07:45:00Z'}];
  const f = strategyFrontend(detailStrategy({holdings})); await f.viewStrategy(42); await flush();
  const output = f.root.querySelector('main').innerHTML;
  const list = output.slice(output.indexOf('<ul class="holdlist">'), output.indexOf('</ul>', output.indexOf('<ul class="holdlist">')));
  assert.equal((list.match(/<li>/g) || []).length, 2);
  assert.match(list, /NO ×4 @ 37¢/); assert.match(list, /Cost \$1\.50/); assert.match(list, /Unreal\. —/); assert.match(list, /Settles /);
  assert.match(list, /−\$0\.30|-\$0\.30/); assert.match(list, /<span class="mk live">Live<\/span>/);
  assert.doesNotMatch(list, /<x>/); assert.doesNotMatch(output, /<th>Contract<\/th><th>Position<\/th>/);
});

test('the abstract says a strategy cleared the gate only when it passed', async () => {
  for (const status of ['passed', 'rejected', 'failed']) {
    const f = strategyFrontend(detailStrategy({status, hypotheses_tried: 2}));
    await f.viewStrategy(42); await flush();
    const text = f.root.querySelector('.paper-ab-result').innerHTML;
    assert.equal(/cleared the gate/.test(text), status === 'passed', status);
    assert.match(text, /of 2 ideas tested this run/);
  }
});

test('what-if results change the results panel while the saved abstract and failed verdict remain intact', async () => {
  const detail = detailStrategy({status: 'failed', hypotheses_tried: 0, out_of_sample: metrics(-12), experiment: null});
  const result = {in_sample: metrics(50), out_of_sample: metrics(1000), equity: [[100, 0], [300, 1000]], gates: [], passed: true};
  const f = strategyFrontend(detail, (path, options) => {
    assert.equal(path, '/api/strategies/42/whatif');
    assert.deepEqual(JSON.parse(options.body), {fee_multiplier: 0, slippage_cents: 0, stake: 5});
    return response(result);
  });
  await f.viewStrategy(42); await flush();
  const abstract = f.root.querySelector('.paper-ab-result'), verdict = f.root.querySelector('.rp-verdict');
  const savedAbstract = abstract.innerHTML, savedVerdict = verdict.innerHTML;
  const whatif = f.root.querySelector('#whatif');
  assert.match(whatif.innerHTML, /<h3>What if…<\/h3>/);
  whatif.querySelector('#wf').value = '0';
  whatif.querySelector('#ws').value = '0';
  whatif.querySelector('#wk').value = '5';
  whatif.querySelector('#wf').oninput();
  await [...f.timeouts.values()].at(-1)();
  assert.match(f.root.querySelector('#sheet-results').innerHTML, /ends at \+\$1,000/);
  assert.doesNotMatch(f.root.querySelector('#sheet-results').innerHTML, /Kalshi dev \(real\)/);
  assert.match(whatif.querySelector('#wflash').innerHTML, /under these conditions/);
  assert.equal(abstract.innerHTML, savedAbstract); assert.match(savedAbstract, /lost \$12/);
  assert.equal(verdict.innerHTML, savedVerdict); assert.match(savedVerdict, /failed it/);
  assert.equal(detail.out_of_sample.pnl, -12); assert.equal(detail.status, 'failed');
});

test('the shipped equity chart anchors the real demo replay without mutating either curve', () => {
  const f = frontend(), curve = [[100, 50], [200, 60], [300, 70]], demo = [[200, 2], [300, 4]];
  const output = f.equityChart(curve, null, demo);
  assert.match(output, /viewBox="0 0 760 236"/); assert.match(output, /Kalshi dev \(real\)/);
  assert.doesNotMatch(output, /NaN|undefined/);
  const lines = [...output.matchAll(/<polyline points="([^"]+)"/g)].map(match => match[1].split(' '));
  assert.equal(lines[1][0], lines[0][1]);
  assert.ok(Number(lines[1][1].split(',')[1]) < Number(lines[1][0].split(',')[1]));
  assert.deepEqual(demo, [[200, 2], [300, 4]]); assert.deepEqual(curve, [[100, 50], [200, 60], [300, 70]]);
});

test('deployment readiness retains separate demo, live and NO-side gates', async () => {
  const f = strategyFrontend(detailStrategy({status: 'failed'}));
  f.S.me.kalshi_dev_connected = false; f.S.me.live_trading_available = false;
  await f.viewStrategy(42);
  assert.equal(f.root.querySelector('#dep-demo').getAttribute('aria-disabled'), 'true');
  assert.equal(f.root.querySelector('#dep-live').getAttribute('aria-disabled'), 'true');
  assert.match(f.root.querySelector('main').innerHTML, /failed the unseen-data gate/);
  await f.root.querySelector('#dep-demo').onclick();
  f.root.querySelector('#dep-live').onclick();
  assert.equal(f.root.querySelector('#live-confirm').hidden, true); assert.equal(postRequests(f).length, 0);
  const no = strategyFrontend(detailStrategy({side: 'no'})); await no.viewStrategy(42);
  assert.equal(no.root.querySelector('#dep-live').getAttribute('aria-disabled'), 'true');
  assert.equal(no.root.querySelector('#dep-demo').getAttribute('aria-disabled'), null);
});

test('demo deployment sends sandbox mode and navigates only after the successful response', async () => {
  const pending = deferred();
  const f = strategyFrontend(detailStrategy(), (path, options) => {
    assert.equal(path, '/api/deployments');
    return options.method === 'POST' ? pending.promise : response({deployments: [], open_positions: []});
  });
  await f.viewStrategy(42);
  f.root.querySelector('#dep-demo').onclick();
  assert.deepEqual(JSON.parse(postRequests(f)[0].options.body), {strategy_id: 42, mode: 'demo'});
  assert.deepEqual(f.navigations, []);
  pending.resolve(response({id: 9})); await flush();
  assert.deepEqual(f.navigations, ['/deploy']);
});

test('live deployment forwards the exact trimmed typed phrase and leaves rejected confirmation visible', async () => {
  for (const typed of ['  LIVE  ', 'not LIVE', '']) {
    const f = strategyFrontend(detailStrategy(), (path, options) => {
      assert.equal(path, '/api/deployments');
      assert.deepEqual(JSON.parse(options.body), {strategy_id: 42, mode: 'live', confirm: typed.trim()});
      return response({error: 'Synthetic server confirmation refusal'}, 400);
    });
    await f.viewStrategy(42);
    const form = f.root.querySelector('#live-confirm');
    assert.equal(form.hidden, true); f.root.querySelector('#dep-live').onclick(); assert.equal(form.hidden, false);
    form.confirm = {value: typed}; form.onsubmit({preventDefault() {}}); await flush();
    assert.equal(postRequests(f).length, 1); assert.deepEqual(f.navigations, []);
    assert.match(f.root.querySelector('#depflash').innerHTML, /Synthetic server confirmation refusal/);
  }
});

test('the landing page paints without a second /api/me right after the boot 401', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/me') return response({error: 'signed out'}, 401);
    return response({});
  }});
  const signin = f.routes.find(([pattern]) => pattern.test('/signin'))[1];
  f.S.me = null; f.S.signedOutAt = Date.now();
  await signin(); await flush();
  assert.equal(f.requests.filter(({path}) => path === '/api/me').length, 0);
  f.S.signedOutAt = Date.now() - 60000;  // a later visit still checks the session
  await signin(); await flush();
  assert.equal(f.requests.filter(({path}) => path === '/api/me').length, 1);
});

test('the OAuth account return and Funds routes open the current funds page', () => {
  const f = frontend();
  const route = path => f.routes.find(([pattern]) => pattern.test(path))?.[1];
  assert.equal(route('/funds'), f.viewFunds); assert.equal(route('/settings/account'), f.viewFunds);
  assert.notEqual(route('/settings'), f.viewFunds);
});

test('paper account buttons name the amount they will move', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); return response(funds()); }});
  await f.viewFunds();
  const form = f.root.querySelector('#paper'), amount = form.querySelector('input[name=amount]');
  const labels = () => form.querySelectorAll('button').map(b => b.textContent);
  assert.deepEqual(labels(), ['Add', 'Withdraw', 'Reset to amount']);
  amount.value = '500'; amount.dispatchEvent({type: 'input'});
  assert.deepEqual(labels(), ['Add $500.00', 'Withdraw $500.00', 'Reset to $500.00']);
  amount.value = ''; amount.dispatchEvent({type: 'input'});
  assert.deepEqual(labels(), ['Add', 'Withdraw', 'Reset to amount']);
});

test('Funds preserves account controls and history without mounting unavailable broker connections', async () => {
  const mounts = [];
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); return response(funds()); },
    brokerMount: (host, options) => { mounts.push({host, options}); }});
  await f.viewFunds();
  const output = f.root.querySelector('main').innerHTML;
  assert.match(output, /funds-col funds-manage/); assert.match(output, /funds-col funds-history/);
  assert.match(output, /Paper history/); assert.match(output, /&lt;script&gt;ledger&lt;\/script&gt;/);
  assert.match(output, /class="table stack t-ledger"/);  // statement rows on a phone, like the credit ledger
  assert.doesNotMatch(output, /<script>/);
  assert.equal(mounts.length, 0); assert.equal(f.root.querySelector('#broker-connections'), null);
  assert.ok(f.root.querySelector('#kalshi')); assert.ok(f.root.querySelector('#demo')); assert.ok(f.root.querySelector('#paper'));
  assert.equal(f.requests.some(({path}) => path.startsWith('/api/brokers')), false);
});

test('Billing shows how long credits last at last week\'s pace, and the welcome credit before any usage', async () => {
  const billing = (o) => ({balance: 14, spent: 6, spent_7d: 7, runway_days: 14, free_bonus: 20, ledger: [], cards: [], configured: false,
    topup_fee_pct: 5, autoreload_amount: 20, autoreload_threshold: 5, min_reload_amount: 5, min_reload_threshold: 1, min_topup: 5, max_topup: 1000, ...o});
  let data = billing({});
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/billing'); return response(data); }});
  await f.viewBilling();
  let figs = f.root.querySelector('#bfigs').innerHTML;
  assert.match(figs, /Credits last/); assert.match(figs, /About 14 days/); assert.match(figs, /at \$7\.00 a week/);
  assert.doesNotMatch(figs, /Welcome credit/);
  data = billing({runway_days: 0.4});
  await f.viewBilling();
  figs = f.root.querySelector('#bfigs').innerHTML;
  assert.match(figs, /Under a day/); assert.match(figs, /tint neg/);
  data = billing({spent_7d: 0, runway_days: null});
  await f.viewBilling();
  figs = f.root.querySelector('#bfigs').innerHTML;
  assert.match(figs, /Welcome credit/); assert.doesNotMatch(figs, /Credits last/);
  // The ledger is a statement on a phone (item and amount on one line), not a labelled card per line.
  data = billing({ledger: [{kind: 'usage', memo: 'Research run', amount: -0.91, created_at: '2026-10-21T00:00:00Z'}]});
  await f.viewBilling();
  assert.match(f.root.querySelector('#main').innerHTML, /class="table stack t-dep t-ledger"[\s\S]*Research run[\s\S]*−\$0\.91/);
});

test('a late Funds read cannot replace the next page or mount stale broker controls', async () => {
  const pending = deferred(); let mounts = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); return pending.promise; }, brokerMount: () => mounts++});
  const loading = f.viewFunds();
  f.S.gen++; f.root.innerHTML = '<main>Next page</main>';
  const writes = f.root.writes, main = f.root.querySelector('main');
  // A read for a page the user has left never settles (api drops it), so wait for the event loop, not the view.
  pending.resolve(response(funds())); await flush(); await flush();
  assert.equal(f.root.writes, writes); assert.equal(main.writes, 0);
  assert.equal(main.innerHTML, 'Next page'); assert.equal(mounts, 0);
});

test('a late Dashboard read cannot paint over the page the user moved to or keep polling there', async () => {
  // The reported bug: open the app on Dashboard, tap Deploy before /api/dashboard answers, and
  // the dashboard used to land on the Deploy page and then repaint it every 15 seconds.
  const pending = deferred();
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return pending.promise; }});
  const loading = f.viewDashboard();
  f.S.gen++; f.clearTimers(); f.root.innerHTML = '<div id="boardbody">Deploy board</div><main>Deploy page</main>';
  const writes = f.root.writes, board = f.root.querySelector('#boardbody'), main = f.root.querySelector('main');
  pending.resolve(response({paper: {}, deployments: [], open_positions: [], recent_closed: []}));
  await flush(); await flush();
  assert.equal(f.root.writes, writes); assert.equal(board.writes, 0); assert.equal(main.writes, 0);
  assert.equal(main.innerHTML, 'Deploy page'); assert.equal(f.S.timers.length, 0);
  void loading;
});

const emptyDashboard = () => ({paper: {equity: 1000, cash: 1000, open_at_cost: 0, total_pnl: 12.5},
  live: {connected: false}, demo: {equity: 1000, capital: 1000}, deployments: [], open_positions: [], recent_closed: [],
  freshness: {btc: null}, agents: {research_running: 0, research_queued: 0}});
const apOn = {autopilot: true, mode: 'paper', story: ['Right now it\u2019s researching <b>BTC</b> 15m.'],
  research: {tested_7d: 1234, passed_7d: 0, active: []}, live_running: 0, demo_running: 0, paper_running: 2,
  paper_progress: {strategy_id: 3, trades: 4, trades_needed: 30, net_pnl: 1}};

test('the dashboard lists five deployments and positions, paused first, and links to Deploy for the rest', async () => {
  const dep = (id, extra = {}) => ({id, strategy_id: id, title: 'Strategy ' + id, market: 'btc15m', mode: 'paper', status: 'running',
    stake: 5, max_positions: 20, realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 0, created_at: '2026-10-25T08:00:00Z', ...extra});
  const deployments = [1, 2, 3, 4, 5, 6].map((id) => dep(id)).concat([dep(7, {status: 'paused', status_reason: 'loss guard'})]);
  const open_positions = [1, 2, 3, 4, 5, 6].map((i) => ({side: 'yes', qty: 1, entry_price: .4, title: 'Strategy ' + i, ticker: 'T-' + i, mode: 'paper', opened_at: '2026-10-25T08:00:00Z'}));
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response({...emptyDashboard(), deployments, open_positions});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const deps = f.root.querySelector('#dash-deps').innerHTML;
  const shown = [...deps.matchAll(/href="\/strategies\/(\d+)"/g)].map((m) => m[1]);
  assert.deepEqual(shown, ['7', '1', '2', '3', '4']);  // the paused one needs the user, so it leads
  assert.match(deps, /See all 7 deployments on Deploy/);
  assert.match(f.root.querySelector('.statusline').innerHTML, /<a class="needs-link" href="#dash-deps"><em>1 paused, needs you<\/em><\/a>/);
  const html = f.root.querySelector('main').innerHTML;
  assert.equal((html.match(/class="stub"/g) || []).length, 5); assert.match(html, /See all 6 open positions on Deploy/);
});

test('the research status line links its "add an idea" ask to the form', async () => {
  for (const [autopilot, tried, ask] of [[true, 2, 'add an idea below'], [false, 2, 'Seed another idea'], [false, 0, 'Describe an idea below']]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/runs') return response({runs: tried ? [{id: 6, status: 'done', market: 'btc15m', hypothesis: 'Idea', hypotheses_tried: tried, strategies_passed: 0, created_at: '2026-10-25T08:00:00Z'}] : [], counts: {research_running: 0, research_queued: 0}, policy: null});
      if (path.startsWith('/api/research/scoreboard')) return response({});
      if (path === '/api/autopilot/status') return response({autopilot, mode: autopilot ? 'paper' : 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = autopilot;
    await f.viewResearch(); await flush(); await flush();
    assert.ok(f.root.querySelector('form#dispatch'));
    assert.match(f.root.querySelector('#rstatus .said').innerHTML, new RegExp(`<a href="#dispatch">${ask}</a>`));
    // The page paints its shell twice (instant switch, then content); the bell reads once.
    assert.equal(f.requests.filter(({path}) => path === '/api/notifications').length, 1);
  }
});

test('the research headline uses all-time totals, not the 50 newest runs', async () => {
  const run = {id: 6, status: 'done', market: 'btc15m', hypothesis: 'Idea', hypotheses_tried: 3, strategies_passed: 9, created_at: '2026-10-25T08:00:00Z'};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/models') return response({models: [], default: ''});
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/runs') return response({runs: [run], counts: {research_running: 0, research_queued: 0}, policy: null, totals: {tried: 1240, passed: 4}});
    if (path.startsWith('/api/research/scoreboard')) return response({});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false;
  await f.viewResearch(); await flush(); await flush();
  assert.match(f.root.querySelector('#rstatus .said').innerHTML, /tested <em>1240<\/em> hypotheses and kept <em>4<\/em>/);
});

test('the research hint says a run-forever session keeps spending credits', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/models') return response({models: [], default: ''});
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/runs') return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null});
    if (path.startsWith('/api/research/scoreboard')) return response({});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false;
  await f.viewResearch(); await flush(); await flush();
  const rf = f.root.querySelector('#runforever'), hint = () => f.root.querySelector('#rf-hint').textContent;
  assert.equal(rf.checked, true);
  assert.match(hint(), /Runs until you stop it, using credits as it goes/);
  rf.checked = false; rf.dispatchEvent({type: 'change'});
  assert.match(hint(), /A session takes a few minutes/);
  assert.doesNotMatch(hint(), /until you stop it/);
});

test('only the admin view shows backtest-history lag on the dashboard status line', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.is_admin = true;
  await f.viewDashboard(); await flush();
  assert.match(f.root.querySelector('#boardbody').innerHTML, /No backtest history yet/);
});

test('the Deploy board puts realized P&L beside the backtest pace for the same trades', async () => {
  const dep = (id, closed, oos) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
    realized_pnl: 1, closed_trades: closed, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1,
    backtest: {out_of_sample: oos}});
  const f = frontend({fetchImpl: path => {
    if (path === '/api/deployments') return response({deployments: [dep(1, 5, {pnl: 12, trades: 6}), dep(2, 0, {pnl: 12, trades: 6}), dep(3, 4, null)], open_positions: []});
    return response({});
  }});
  await f.viewDeploy(); await flush(); await flush();
  const html = f.root.querySelector('#deps').innerHTML;
  assert.match(html, />Backtest pace</);
  // $12 over 6 unseen trades = $2 a trade, so 5 closed trades -> +$10.00.
  assert.match(html, /\+\$10\.00<div class="sub-fig">same 5 trades<\/div>/);
  assert.match(html, /no closed trades/);
  assert.doesNotMatch(html, /Backtest unseen/);
});

test('Deploy open positions label every cell so phone cards read Contract, Side, Cost', async () => {
  const pos = {title: 'Rain fade', ticker: 'KXRAINNYC-T1', side: 'no', qty: 4, entry_price: .37, entry_fee: .02, unrealized: null, market_close_time: '2026-10-25T17:30:00Z', mode: 'paper'};
  const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [], open_positions: [pos]}) : response({})});
  await f.viewDeploy(); await flush(); await flush();
  const html = f.root.querySelector('#openpos').innerHTML;
  for (const lab of ['Strategy', 'Contract', 'Side', 'Cost', 'Unrealized', 'Settles']) assert.match(html, new RegExp(`data-lab="${lab}"`), lab);
  assert.match(html, /<td class="name" data-lab="Strategy">Rain fade/);
});

test('while autopilot is off, Turn on autopilot is the only primary button on the dashboard', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const head = () => f.root.querySelector('#boardbody .statusline').innerHTML;
  assert.match(head(), /<a class="btn" href="\/research">New research<\/a>/);
  f.S.me.user.autopilot = true;
  await f.viewDashboard(); await flush();
  assert.match(head(), /<a class="btn primary" href="\/research">New research<\/a>/);
});

test('the dashboard offers one-click autopilot, and once on shows what it is doing and the paper P&L', async () => {
  const f = frontend({fetchImpl: (path, options) => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/settings') { assert.deepEqual(JSON.parse(options.body), {autopilot: true}); return response({ok: true}); }
    if (path === '/api/autopilot/status') return response(apOn);
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const card = () => f.root.querySelector('#dash-ap');
  assert.match(card().innerHTML, /Let the autopilot trade for you/);
  assert.doesNotMatch(f.root.querySelector('#boardbody').innerHTML, /backtest history/i);  // operator-only
  await card().querySelector('[data-apcard="on"]').onclick(); await flush(); await flush();
  assert.equal(f.S.me.user.autopilot, true);
  const html = card().innerHTML;
  assert.match(html, /Autopilot · paper/); assert.match(html, /&lt;b&gt;BTC&lt;\/b&gt;/);
  assert.match(html, /\+\$12\.50/); assert.match(html, /1,234 tested · 0 passed/); assert.match(html, /<a href="\/strategies\/3"[^>]*>4 of 30 paper trades<\/a>/);
  // The most trades on paper, which may be losing: 'Closest to live' overstated it.
  assert.match(html, /Furthest on paper/); assert.doesNotMatch(html, /Closest to live/);
  assert.doesNotMatch(html, /undefined|NaN|<b>BTC/);
});

test('an empty Deployed box asks for research only when autopilot is off; Funds is a link', async () => {
  for (const on of [false, true]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response(emptyDashboard());
      if (path === '/api/autopilot/status') return response(apOn);
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = on;
    await f.viewDashboard(); await flush();
    const body = f.root.querySelector('#boardbody').innerHTML + f.root.querySelector('#dash-deps').innerHTML;
    assert.match(body, /on <a href="\/funds">Funds<\/a> to trade real money/);
    assert.match(body, on ? /Autopilot is on\. Strategies that pass/ : /Research an idea</);
    assert.doesNotMatch(body, on ? /Research an idea</ : /See its research/);
    if (!on) assert.match(body, /Turn on autopilot above and the strategies that pass every gate/);  // points at the card's switch
  }
});

test('the autopilot pill goes by the saved switch until its first status read lands', async () => {
  for (const on of [true, false]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response(emptyDashboard());
      if (path === '/api/autopilot/status') return new Promise(() => {});  // still in flight
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = on; f.S.ap = null; f.S.apAt = 0;  // a fresh page load: nothing read yet
    await f.viewDashboard(); await flush();
    const pill = f.root.parent.querySelector('#autopilot-float .apf-pill-label');
    assert.equal(pill.textContent, on ? 'Autopilot on' : 'Autopilot off');
  }
});

test('the empty Deployed box follows the autopilot switch without a reload', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/autopilot/status') return response({...apOn, autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false;
  await f.viewDashboard(); await flush();
  const deps = () => f.root.querySelector('#deps-empty').innerHTML;
  assert.match(deps(), /Turn on autopilot above/);
  f.S.me.user.autopilot = true; f.S.ap = {...apOn};
  f.paintDashAp();
  assert.match(deps(), /Autopilot is on\. Strategies that pass/); assert.doesNotMatch(deps(), /Turn on autopilot above/);
  f.S.me.user.autopilot = false; f.S.ap = {...apOn, autopilot: false, mode: 'off'};
  f.paintDashAp();
  assert.match(deps(), /Turn on autopilot above/);
});

test('the empty Deployed box never says autopilot is researching while the card says it is quiet or paused', async () => {
  const quiet = {...apOn, story: ['Right now it’s between research runs. Its last check-in was 3 hours ago, longer than usual.']};
  for (const status of [quiet, {...apOn, billing_blocked: true, billing_reason: 'credits', story: []}]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response(emptyDashboard());
      if (path === '/api/autopilot/status') return response(status);
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    f.S.ap = status; f.paintDashAp();
    assert.match(f.root.querySelector('#dash-ap').innerHTML, status.billing_blocked ? /Paused: / : /longer than usual/);
    const deps = f.root.querySelector('#deps-empty').innerHTML;
    assert.match(deps, /Autopilot is on\./); assert.doesNotMatch(deps, /is researching/);
  }
});

test('paper P&L reads "since reset" on the card and dashboard once the paper account was reset', async () => {
  for (const reset_at of [null, '2026-10-20T09:00:00Z']) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') { const d = emptyDashboard(); d.paper.reset_at = reset_at; return response(d); }
      if (path === '/api/autopilot/status') return response(apOn);
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    f.S.ap = apOn; f.paintDashAp();
    const span = reset_at ? 'since reset' : 'all time';
    // Both read total_pnl, which restarts at a reset; the track record keeps every closed trade.
    assert.match(f.root.querySelector('#dash-ap').innerHTML, new RegExp(`<dt>Paper P&amp;L, ${span}</dt><dd><span class="[^"]*">\\+\\$12\\.50`));
    assert.match(f.root.querySelector('#boardbody').innerHTML, new RegExp(`\\+\\$12\\.50 ${span}`));
    if (reset_at) assert.doesNotMatch(f.root.querySelector('#boardbody').innerHTML, /all time/);
  }
});

test('the dashboard demo card says what demo is and that its P&L restarts at a reload', async () => {
  for (const [demo, re] of [
    [{equity: 1000, capital: 1000}, /\$1,000\.00 capital · no demo strategies yet · real fills on Kalshi’s sandbox, not real money/],
    [{equity: 512, capital: 500, realized_pnl: 12, running: 1, open_positions: 0, before_reload: 40}, /\$500\.00 capital · 0 open · \+\$12\.00 P&amp;L since reload · real fills/],
    [{equity: 1012, capital: 1000, realized_pnl: 12, running: 1, open_positions: 0, before_reload: 0}, /\+\$12\.00 P&amp;L all time · real fills/],
  ]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response({...emptyDashboard(), demo});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    assert.match(f.root.querySelector('#boardbody').innerHTML, re);
  }
});

test('Funds demo labels say "since reload" only after a reload, and that demo fills are real', async () => {
  for (const before_reload of [0, 40]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds(); d.demo.before_reload = before_reload; return response(d); }});
    await f.viewFunds();
    const main = f.root.querySelector('main').innerHTML;
    assert.match(main, before_reload ? /<dt>Capital at last reload<\/dt>/ : /<dt>Starting capital<\/dt>/);
    assert.match(main, before_reload ? /<dt>P&amp;L since reload<\/dt>/ : /<dt>P&amp;L all time<\/dt>/);
    assert.match(main, /the track record still counts every closed demo trade/);
    assert.match(f.root.querySelector('#ffigs').innerHTML, /real fills on Kalshi’s sandbox, not real money/);
  }
});

test('Deploy realized says it counts only the strategies listed, never summing live with paper', async () => {
  const dep = (id, mode, pnl) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode, status: 'running', status_reason: null,
    realized_pnl: pnl, closed_trades: 1, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1,
    backtest: {out_of_sample: null}});
  for (const [deployments, re] of [[[dep(1, 'paper', 2)], /\+\$2\.00[\s\S]*paper money, not real · strategies listed below/],
    [[dep(1, 'paper', 2), dep(2, 'live', 5)], /Live realized[\s\S]*\+\$5\.00[\s\S]*real money, strategies listed below · \+\$2\.00 on paper, counted apart/]]) {
    const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments, open_positions: []}) : response({})});
    await f.viewDeploy(); await flush(); await flush();
    const figs = f.root.querySelector('#dfigs').innerHTML;
    assert.match(figs, re); assert.doesNotMatch(figs, /\$7\.00/);
  }
});

test('a failed autopilot switch-on leaves the dashboard card off and says why', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/settings') return response({error: 'Add a payment method first.'}, 400);
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  await f.root.querySelector('#dash-ap [data-apcard="on"]').onclick(); await flush();
  assert.notEqual(f.S.me.user.autopilot, true);
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /Turn on autopilot/);
  assert.match(f.root.querySelector('#dash-ap .apcard-err').innerHTML, /Add a payment method first\./);
});

test('the autopilot panel shows Kill only once real money is armed or running', () => {
  const f = frontend();
  const controls = d => {
    const box = new Element('div'); box.innerHTML = '<div id="apf-controls"></div>';
    f.apUpdate(box, {mode: 'paper', live_enabled: true, kalshi_connected: false, ...d});
    return box.querySelector('#apf-controls').innerHTML;
  };
  const off = controls({autopilot: false});
  assert.doesNotMatch(off, /data-ap="kill"|data-ap="livearm"/); assert.match(off, /Open board/);
  const paper = controls({autopilot: true});
  assert.doesNotMatch(paper, /data-ap="kill"/); assert.match(paper, /data-ap="livearm" aria-disabled="true"/);
  assert.match(controls({autopilot: true, autopilot_live: true}), /data-ap="kill"/);
  assert.match(controls({autopilot: false, live_running: 1}), /data-ap="kill"/);
});

test('Explore tells same-titled markets from different events apart', async () => {
  const row = (t, ev) => ({t, s: 'KXBTCD', ev, ti: 'Bitcoin price on Oct 25, 2026?', su: '$80,500 or above', last: '0.5', bid: '0.49', ask: '0.51', v24: '10', oi: '5', st: 'active'});
  const f = frontend({fetchImpl: path => {
    if (path.startsWith('/api/explore?')) return response({at: '2026-10-25T15:00:00Z', total: 2, shown: 2, matched: 2, page: 0, per: 50, sort: 'v24',
      markets: [row('KXBTCD-26OCT2512-T80499.99', 'KXBTCD-26OCT2512'), row('KXBTCD-26OCT2517-T80499.99', 'KXBTCD-26OCT2517')]});
    return response({});
  }});
  await f.viewExplore(); await flush();
  const html = f.root.querySelector('#xbody').innerHTML;
  assert.match(html, /KXBTCD-26OCT2512</); assert.match(html, /KXBTCD-26OCT2517</);
});

test('Explore drops a yes subtitle that only repeats the title', async () => {
  const row = (t, ti, su) => ({t, s: 'KXNBAGAME', ev: t, ti, su, last: '0.5', bid: '0.49', ask: '0.51', v24: '10', oi: '5', st: 'active'});
  const f = frontend({fetchImpl: path => path.startsWith('/api/explore?')
    ? response({at: '2026-10-25T16:15:00Z', total: 3, shown: 3, matched: 3, page: 0, per: 50, sort: 'v24', markets: [
      row('A', 'Minnesota wins', 'Minnesota'), row('B', 'Will Bitcoin be above $200000 by Jan 1, 2027?', 'Above $200000'),
      row('C', 'Bitcoin price on Oct 25, 2026?', '$80,500 or above')]})
    : response({})});
  await f.viewExplore(); await flush();
  const html = f.root.querySelector('#xbody').innerHTML;
  assert.match(html, />Minnesota wins</); assert.match(html, />Will Bitcoin be above \$200000 by Jan 1, 2027\?</);
  assert.match(html, />Bitcoin price on Oct 25, 2026\? · \$80,500 or above</);
});

test('Explore shows tenth-of-a-cent prices instead of rounding them to 0¢', async () => {
  const row = (t, last) => ({t, s: 'KXBTC15M', ev: t, ti: 'BTC price up in next 15 mins?', su: 'Target', last, bid: '0', ask: last, v24: '10', oi: '5', st: 'active'});
  const f = frontend({fetchImpl: path => path.startsWith('/api/explore?')
    ? response({at: '2026-10-25T16:15:00Z', total: 2, shown: 2, matched: 2, page: 0, per: 50, sort: 'v24', markets: [row('KXBTC15M-A', '0.0010'), row('KXBTC15M-B', '0.3700')]})
    : response({})});
  await f.viewExplore(); await flush();
  const html = f.root.querySelector('#xbody').innerHTML;
  assert.match(html, />0\.1¢</); assert.match(html, />37¢</); assert.doesNotMatch(html, />0¢</);
});

test('a market Kalshi did not answer for offers Try again and loads on retry', async () => {
  let calls = 0;
  const f = frontend({fetchImpl: path => {
    if (!path.startsWith('/api/explore/market?')) return response({});
    return ++calls === 1 ? response({error: "Kalshi didn't send this market's history just now. Try again in a minute."}, 502)
      : response({ticker: 'KXNBAGAME-X', title: 'Minnesota wins', points: [], yes_bid: .5, yes_ask: .51, last: .5});
  }});
  await f.viewMarketDetail('KXNBAGAME-X'); await flush();
  assert.match(f.root.querySelector('main').innerHTML, /Try again in a minute/);
  f.root.querySelector('#mk-retry').onclick(); await flush(); await flush();
  assert.equal(calls, 2);
  assert.doesNotMatch(f.root.querySelector('main').innerHTML, /mk-retry/);
});

test('a market whose history did not load still shows its figures, with Try again on the chart', async () => {
  let calls = 0;
  const f = frontend({fetchImpl: path => {
    if (!path.startsWith('/api/explore/market?')) return response({});
    return ++calls === 1
      ? response({ticker: 'KXNBAGAME-X', series: 'KXNBAGAME', title: 'Minnesota wins', points: [], yes_bid: '0.50', yes_ask: '0.51', last: '0.50', open_interest: '201649', history_unavailable: true})
      : response({ticker: 'KXNBAGAME-X', series: 'KXNBAGAME', title: 'Minnesota wins', points: [{t: 1792900000, yes: .5, vol: 3}, {t: 1792900060, yes: .51, vol: 2}], period_min: 1, yes_bid: '0.50', yes_ask: '0.51'});
  }});
  await f.viewMarketDetail('KXNBAGAME-X'); await flush();
  const main = f.root.querySelector('main').innerHTML;
  assert.match(main, /Price history didn’t load/); assert.match(f.root.querySelector('#rawsect').innerHTML, /Waiting on Kalshi for the candles/);
  assert.match(f.root.innerHTML, /201,649/);  // the snapshot's open interest still shows
  f.root.querySelector('#mk-retry').onclick(); await flush(); await flush();
  assert.equal(calls, 2); assert.doesNotMatch(f.root.querySelector('main').innerHTML, /didn’t load/);
});

// Every page the server serves the app shell for (app/server.py SPA_ROUTES). A path with no route
// fell back to the dashboard, so Meridian's /settings/billing opened Tau's dashboard after a theme switch.
const SPA_PATHS = ['/', '/dashboard', '/research', '/research/1', '/strategies', '/strategies/1', '/deploy', '/community',
  '/billing', '/admin', '/system', '/funds', '/explore', '/devlog', '/track-record', '/settings', '/settings/account',
  '/settings/billing', '/settings/system', '/settings/theme', '/signin', '/terms', '/privacy'];

test('Tau has a page for every app path the server serves', () => {
  const f = frontend();
  for (const path of SPA_PATHS) assert.ok(f.routes.some(([re]) => re.test(path)), path);
  const page = (path) => f.routes.find(([re]) => re.test(path))[1].name;
  assert.equal(page('/settings/billing'), 'viewBilling'); assert.equal(page('/settings/system'), 'viewSystem');
  assert.equal(page('/settings/theme'), 'viewSettings');
});

test('the legal pages offer a signed-in reader the dashboard, not Sign in', async () => {
  for (const [me, href, label] of [[response({user: {id: 7}}), '/', 'Dashboard'], [response({error: 'Please sign in.'}, 401), '/signin', 'Sign in']]) {
    const f = frontend({fetchImpl: path => (path === '/api/me' ? me : response({}))});
    f.S.me = null;
    await f.routes.find(([re]) => re.test('/terms'))[1](); await flush(); await flush();
    const a = f.root.querySelector('.legal-away');
    assert.equal(a.getAttribute('href'), href); assert.equal(a.textContent, label);
    assert.deepEqual(f.navigations, []);
  }
});

test('a strategy that does not exist links to the list instead of offering Try again', async () => {
  const f = frontend({fetchImpl: path => (path.startsWith('/api/strategies/42') ? response({error: 'No such strategy.'}, 404) : response({}))});
  await f.render(); await flush();
  const html = f.root.innerHTML;
  assert.match(html, /No such strategy\./); assert.match(html, /href="\/strategies">All strategies</);
  assert.doesNotMatch(html, /data-retry/);
});

test('a shared demo deployment says demo, not paper', () => {
  const f = frontend();
  const snap = (mode) => f.postSnapshot({kind: 'deployment', id: 1, title: 'Fade', market: 'btc15m', mode, realized_pnl: 1.5, closed_trades: 3});
  assert.match(snap('demo'), /· demo ·/); assert.match(snap('paper'), /· paper ·/); assert.match(snap('live'), /· live ·/);
});

test('a track record whose trades all closed in one minute spaces them one per trade', () => {
  const f = frontend();
  assert.equal(JSON.stringify(f.trCurve([[1000, 1], [1000, -2], [1030, 3]])), '[[1000,1],[1001,-2],[1002,3]]');
  const spread = [[1000, 1], [5000, 2]];
  assert.equal(f.trCurve(spread), spread);
  assert.equal(f.trCurve(null), null);
});

test('an empty paper track record points at autopilot when it is on, live and demo stay manual', () => {
  const f = frontend(), th = {min_sharpe_days: 30};
  f.S.me = {user: {autopilot: true}};
  const paper = f.trackRecordPanel({trades: 0, label: 'Paper'}, 'paper', th);
  assert.match(paper, /Autopilot runs the strategies that pass every gate on paper/);
  assert.match(paper, /href="\/research">See its research/); assert.doesNotMatch(paper, /Turn on autopilot|Go to Deploy/);
  assert.match(f.trackRecordPanel({trades: 0, label: 'Live'}, 'live', th), /Go to Deploy/);
  f.S.me = {user: {autopilot: false}};
  const off = f.trackRecordPanel({trades: 0, label: 'Paper'}, 'paper', th);
  assert.match(off, /Deploy a passed strategy on paper/); assert.match(off, /Turn on autopilot/); assert.match(off, /Go to Deploy/);
});

test('the retained broker module still rejects a late redirect after its owning view changes', async () => {
  const pending = deferred(), redirects = [];
  const f = frontend({fetchImpl: path => {
    if (path === '/api/funds') return response(funds());
    if (path === '/api/brokers') return response({providers: [{id: 'alpaca', configured: true,
      default_environment: 'paper', environments: ['paper', 'live'], connections: []}]});
    assert.equal(path, '/api/brokers/alpaca/connect'); return pending.promise;
  }});
  await f.viewFunds();
  // Explicit isolated module fixture; customer Funds does not mount this host.
  const host = new Element('section', {id: 'offline-broker-control'}); f.root.appendChild(host);
  const generation = f.S.gen;
  const control = brokerConnections.mount(host, {api: f.api, search: '',
    isCurrent: () => generation === f.S.gen, navigate: url => redirects.push(url)});
  await control.ready;
  const connect = host.querySelector('[data-broker-action="connect"][data-broker="alpaca"]');
  assert.ok(connect); const connecting = host.onclick({target: connect, preventDefault() {}});
  assert.deepEqual(JSON.parse(postRequests(f)[0].options.body), {environment: 'paper', permission: 'read'});
  // A route may await data before replacing the old DOM. Exercise the generation
  // guard while the broker host is still connected, independent of detachment.
  f.S.gen++; const writes = host.writes;
  assert.equal(host.isConnected, true);
  pending.resolve(response({authorization_url: 'https://app.alpaca.markets/oauth/authorize?state=synthetic'}));
  await connecting;
  assert.deepEqual(redirects, []); assert.equal(host.writes, writes);
});

test('current research controls pause and resume and cancellation needs two current clicks', async () => {
  const f = frontend({fetchImpl: () => response({ok: true})}), host = new Element(); let reloads = 0;
  const reload = async () => reloads++;
  f.runControls(host, 9, 'running', reload);
  const pause = host.querySelector('#pause'); await pause.onclick({currentTarget: pause});
  assert.equal(postRequests(f)[0].path, '/api/runs/9/pause');
  f.runControls(host, 9, 'paused', reload);
  const resume = host.querySelector('#resume'); await resume.onclick({currentTarget: resume});
  assert.equal(postRequests(f)[1].path, '/api/runs/9/resume');
  host.querySelector('#cancel').onclick(); assert.equal(postRequests(f).length, 2);
  f.runControls(host, 9, 'paused', reload);
  const cancel = host.querySelector('#cancel'); cancel.onclick(); assert.equal(postRequests(f).length, 2);
  await cancel.onclick(); assert.equal(postRequests(f)[2].path, '/api/runs/9/cancel'); assert.equal(reloads, 3);
});

test('streaming thoughts and challenger/verdict update one hypothesis and navigation clears feed timers', () => {
  const f = frontend(), section = new Element();
  section.innerHTML = '<ol class="log"></ol><button class="jumplatest"></button><div class="runpulse"></div>';
  const stream = f.runFeed(section), log = section.querySelector('.log');
  const event = (id, kind, message, data = {}) => ({id, kind, message, data, created_at: '2026-10-17T10:00:00Z'});
  stream.push([event(1, 'thinking', 'A **test'), event(2, 'thinking', 'able** edge.')]);
  assert.equal(log.children.length, 1);
  assert.match(log.children[0].querySelector('[data-body]').innerHTML, /<b>testable<\/b>/);
  stream.push([
    event(3, 'hypothesis', 'Momentum', {thesis: 'Late flow', spec: {code: 'return []'}}),
    event(4, 'challenger', 'Challenger accept – Momentum: sound mechanism', {title: 'Momentum', decision: 'accept'}),
    event(5, 'verdict', 'PASSED – Momentum: evidence', {title: 'Momentum', status: 'passed', strategy_id: 42, stats: {n_trades: 80, p_value: .01}}),
  ]);
  assert.equal(log.children.length, 2); assert.equal(log.children[0].classes.has('sealed'), true);
  const hypothesis = log.children[1];
  assert.match(hypothesis.innerHTML, /research sandbox only/);
  assert.match(hypothesis.querySelector('[data-review]').innerHTML, /sound mechanism/);
  assert.match(hypothesis.querySelector('[data-stamp]').innerHTML, /\/strategies\/42/);
  stream.state('paused'); assert.match(section.querySelector('.runpulse').innerHTML, /resume/);
  f.clearTimers(); assert.equal(f.intervals.size, 0); assert.equal(f.S.timers.length, 0);
});

test('the current research run renders a safe streaming log and its paused status with Resume', async () => {
  const run = {id: 9, prompt: '<script>unsafe</script>', status: 'paused', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/runs/9?after=0'); return response({run, events: []}); }});
  await f.viewRun(9);
  assert.match(f.root.innerHTML, /role="log"/);
  assert.match(f.root.querySelector('#runboard').innerHTML, /&lt;script&gt;/);
  assert.doesNotMatch(f.root.querySelector('#runboard').innerHTML, /<script>/);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Paused/);
  assert.ok(f.root.querySelector('#resume')); assert.match(f.root.querySelector('#runpulse').innerHTML, /resume/);
});

test('phone labels on strategy rows say the P&L is a backtest', () => {
  const f = frontend({fetchImpl: path => { throw new Error('Unexpected offline request: ' + path); }});
  const m = (pnl) => ({pnl, trades: 40, win_rate: 0.54});
  const lab = (s) => f.strategySlip(s, {}).match(/<td class="num" data-lab="([^"]*)"/)[1];
  assert.equal(lab({id: 1, status: 'passed', title: 'Kept', market: 'btc15m', out_of_sample: m(12), in_sample: m(3)}), 'Backtest P&amp;L (unseen)');
  assert.equal(lab({id: 2, status: 'rejected', title: 'Dropped', market: 'btc15m', out_of_sample: null, in_sample: m(-7.5)}), 'Backtest P&amp;L (tested)');
});

test('before its first policy check the run page says what the check needs', async () => {
  const run = {id: 9, prompt: 'Idea', status: 'succeeded', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
  const rsi = {evolved: false, last_dream: null, min_history: 12};
  const f = frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: [], rsi}); }});
  await f.viewRun(9);
  const box = f.root.querySelector('#rsibox').innerHTML;
  assert.match(box, /No check yet\. The first one runs at the end of a session, once at least 12 ideas have been tested\./);
  assert.doesNotMatch(box, /first result appears/);
  f.clearTimers();
});

test('a finished run hides its last loop phase instead of reading as still working', async () => {
  for (const [status, hidden] of [['succeeded', true], ['running', false]]) {
    const run = {id: 9, prompt: 'Idea', status, market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
    const events = [{id: 1, kind: 'verdict', message: 'REJECTED – Idea', data: {title: 'Idea', status: 'rejected'}, created_at: '2026-10-17T10:03:00Z'}];
    const f = frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events}); }});
    await f.viewRun(9);
    const phase = f.root.querySelector('#rsiobs').querySelector('[data-phase]');
    assert.equal(phase.hidden, hidden, status);
    f.clearTimers();
  }
});

test('the grouped market picker keeps Agent choice visible while filters hide unmatched categories', () => {
  const f = frontend();
  f.S.me.markets = Array.from({length: 9}, (_, i) => ({key: i === 0 ? 'eth15m' : 'custom' + i,
    label: i === 8 ? '<script>market</script>' : 'Market ' + i, category: i < 3 ? 'Crypto' : i < 6 ? 'Sports' : 'Bittensor'}));
  const host = new Element(); host.innerHTML = f.marketPicker(f.S.me.markets); f.wireMarketPicker(host);
  const lead = host.querySelector('.mkt-lead'), search = host.querySelector('#mktfind');
  assert.equal(lead.querySelector('input').value, ''); assert.equal(lead.querySelector('input').checked, true);
  assert.match(host.innerHTML, /&lt;script&gt;market&lt;\/script&gt;/); assert.doesNotMatch(host.innerHTML, /<script>/);
  search.value = 'ETH'; search.dispatchEvent({type: 'input'});
  assert.equal(host.querySelectorAll('.mkt-group').filter(group => !group.hidden).length, 1);
  assert.equal(lead.hidden, false); assert.equal(host.querySelector('.mkt-none').hidden, true);
  search.value = 'no match'; search.dispatchEvent({type: 'input'});
  assert.ok(host.querySelectorAll('.mkt-group').every(group => group.hidden));
  assert.equal(lead.hidden, false); assert.equal(host.querySelector('.mkt-none').hidden, false);
  search.value = ''; search.dispatchEvent({type: 'input'});
  assert.ok(host.querySelectorAll('.mkt-group').every(group => !group.hidden));
});

test('feed markdown escapes model HTML and rejects non-http links', () => {
  const f = frontend(), output = f.feedMd('<img src=x onerror=alert(1)>\n[unsafe](javascript:alert(1))\n**complete** and **pending');
  assert.doesNotMatch(output, /<img|href="javascript:/);
  assert.match(output, /<b>complete<\/b>/); assert.match(output, /\*\*pending/);
});

test('a research run shows what it has cost so far from its ledger debits, and its cost once finished', async () => {
  for (const [status, label] of [['running', 'Spent so far'], ['paused', 'Spent so far'], ['succeeded', 'Cost'], ['cancelled', 'Cost']]) {
    const run = {id: 9, prompt: 'Idea', status, market: 'btc15m', created_at: '2026-10-17T10:00:00Z', spent_usd: 1.8372};
    const f = frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: []}); }});
    await f.viewRun(9);
    assert.match(f.root.querySelector('#runfigs').innerHTML, new RegExp(`${label}</dt><dd><span class="fig ">\\$1\\.84</span>`), status);
    f.clearTimers();
  }
  // An older server that sends no figure shows none, rather than a made-up $0.00.
  const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
  const f = frontend({fetchImpl: () => response({run, events: []})});
  await f.viewRun(9);
  assert.doesNotMatch(f.root.querySelector('#runfigs').innerHTML, /Spent so far|Cost/);
  f.clearTimers();
});

test('research list rows state each session\'s cost from the ledger', async () => {
  const runs = [{id: 6, status: 'succeeded', market: 'btc15m', prompt: 'Done idea', hypotheses_tried: 3, strategies_passed: 0, created_at: '2026-10-25T08:00:00Z', spent_usd: 2.5},
    {id: 7, status: 'running', market: 'btc15m', prompt: 'Live idea', hypotheses_tried: 1, strategies_passed: 0, created_at: '2026-10-25T09:00:00Z', spent_usd: 0.42}];
  const f = frontend({fetchImpl: path => {
    if (path === '/api/models') return response({models: [], default: ''});
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/runs') return response({runs, counts: {research_running: 1, research_queued: 0}, policy: null});
    if (path.startsWith('/api/research/scoreboard')) return response({});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false;
  await f.viewResearch(); await flush(); await flush();
  const html = f.root.querySelector('#runs').innerHTML;
  assert.match(html, /href="\/research\/6"[\s\S]*?Cost: \$2\.50/);
  assert.match(html, /href="\/research\/7"[\s\S]*?Spent so far: \$0\.42/);
  f.clearTimers();
});
