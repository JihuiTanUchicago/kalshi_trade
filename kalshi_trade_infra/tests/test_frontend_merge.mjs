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
  get options() { return this.children.filter(child => child.tag === 'option'); }
  get isConnected() { return !this.removed && (!this.parent || this.parent.isConnected); }
  get parentElement() { return this.parent || null; }
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

function frontend({fetchImpl, brokerMount, storage, stripe, matchMedia = () => ({matches: false})} = {}) {
  const root = new Element('div', {id: 'app'}), body = new Element('body'); body.appendChild(root);
  const intervals = new Map(), timeouts = new Map(), requests = [], navigations = [];
  let nextId = 0;
  const location = {pathname: '/strategies/42', search: '', origin: 'http://offline.invalid'};
  const navigate = (_state, _title, path) => { navigations.push(path); const [p, q] = String(path).split('?'); location.pathname = p; location.search = q ? '?' + q : ''; };
  const context = vm.createContext({
    Intl, URL, URLSearchParams, AbortController,
    document: {body, getElementById: id => body.querySelector('#' + id), addEventListener() {}, removeEventListener() {}, createElement: tag => new Element(tag)},
    window: {addEventListener() {}, scrollTo() {}, matchMedia,
      ...(brokerMount ? {TauBrokerConnections: {mount: brokerMount}} : {}), ...(stripe ? {Stripe: stripe} : {})},
    addEventListener() {}, location, history: {pushState: navigate, replaceState: navigate},
    localStorage: storage || {getItem: () => null, setItem() {}},
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
  vm.runInContext(source.replace(boot, 'globalThis.frontend = {S, api, routes, viewExample, equityChart, runControls, runFeed, clearTimers, runRow, feedMd, viewStrategy, viewStrategies, strategySlip, postSnapshot, viewRun, viewFunds, viewBilling, viewDashboard, viewDeploy, viewResearch, viewExplore, marketPicker, wireMarketPicker, paintDashAp, apUpdate, apYield, tabEdges, trCurve, trackRecordPanel, mountTrackRecord, viewMarketDetail, render};'), context);
  const api = context.frontend;
  api.S.me = {user: {id: 7, name: 'Offline fixture'}, markets: [], directions: [], live_trading_available: true, kalshi_connected: true, kalshi_dev_connected: true};
  // Cached global widgets keep these page checks focused. All requests still use
  // the offline transport above, including notifications and financial controls.
  api.S.hot = {markets: []}; api.S.hotAt = Date.now();
  api.S.ap = {mode: 'off'}; api.S.apAt = Date.now();
  // Moves the page's clock (Date.now) forward, for checks on how old a figure is.
  const shiftClock = ms => vm.runInContext(`{ const now = Date.now; Date.now = () => now() + ${Number(ms)}; }`, context);
  return {...api, root, location, document: context.document, intervals, timeouts, requests, navigations, shiftClock};
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

test('a strategy from the seeded example session carries the Example tag and note on its own page', async () => {
  const note = 'An example Tau ran for you when you signed up. It cost you nothing.';
  for (const example of [true, false]) {
    const f = strategyFrontend(detailStrategy({example, direction: 'random_walk'})); await f.viewStrategy(42); await flush();
    const head = f.root.querySelector('.board-title').outerHTML;
    assert.equal(/<span class="mk quiet example-tag" title="[^"]*">Example<\/span>/.test(head), example);
    assert.equal(head.includes(note), example);
    f.clearTimers();
  }
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
    {ticker: 'KXBTC15M-B', side: 'yes', qty: 2, entry_price: 0.6, cost: 1.2, unrealized: -0.3, mode: 'live', market_close_time: '2026-10-25T07:45:00Z',
      why: 'Entered at 60¢: edge ≥ 2¢ after fees · Holds to settlement'}];
  const f = strategyFrontend(detailStrategy({holdings})); await f.viewStrategy(42); await flush();
  const output = f.root.querySelector('main').innerHTML;
  const list = output.slice(output.indexOf('<ul class="holdlist">'), output.indexOf('</ul>', output.indexOf('<ul class="holdlist">')));
  assert.equal((list.match(/<li>/g) || []).length, 2);
  assert.match(list, /NO ×4 @ 37¢/); assert.match(list, /Cost \$1\.50/); assert.match(list, /Unreal\. —/); assert.match(list, /Settles /);
  assert.match(list, /−\$0\.30|-\$0\.30/); assert.match(list, /<span class="mk live">Live<\/span>/);
  assert.doesNotMatch(list, /<x>/); assert.doesNotMatch(output, /<th>Contract<\/th><th>Position<\/th>/);
  // Each holding says why it was bought and how it will exit; one without a reason says nothing.
  assert.deepEqual([...list.matchAll(/<div class="sub-fig pos-why">([^<]*)<\/div>/g)].map((m) => m[1]),
    ['Entered at 60¢: edge ≥ 2¢ after fees · Holds to settlement']);
});

test('the abstract says a strategy cleared the gate only when it passed', async () => {
  for (const status of ['passed', 'rejected', 'failed']) {
    const f = strategyFrontend(detailStrategy({status, hypotheses_tried: 2}));
    await f.viewStrategy(42); await flush();
    const text = f.root.querySelector('.paper-ab-result').innerHTML;
    assert.equal(/cleared the gate/.test(text), status === 'passed', status);
    assert.match(text, /of 2 ideas tested this run/);
    const figs = f.root.querySelector('#figs').innerHTML;
    assert.equal(/the one that passed/.test(figs), status === 'passed', status);
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

test('the seeded example session is listed as an example, not counted as the user\'s research', async () => {
  const example = {id: 1, status: 'succeeded', market: 'btc15m', direction: 'random_walk', example: true, prompt: 'Random walk',
    hypotheses_tried: 2, strategies_passed: 0, spent_usd: 0, created_at: '2026-10-17T08:00:00Z'};
  const mine = {id: 6, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Mine',
    hypotheses_tried: 3, strategies_passed: 1, spent_usd: 0.42, created_at: '2026-10-25T08:00:00Z'};
  for (const [runs, count] of [[[example], '1 example'], [[mine, example], '1 run ·\u00a01 example']]) {
    const own = runs.filter((r) => !r.example);
    const f = frontend({fetchImpl: path => {
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/runs') return response({runs, counts: {research_running: 0, research_queued: 0}, policy: null,
        totals: {tried: own.reduce((a, r) => a + r.hypotheses_tried, 0), passed: own.reduce((a, r) => a + r.strategies_passed, 0)}});
      if (path.startsWith('/api/research/scoreboard')) return response({});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = false;
    await f.viewResearch(); await flush(); await flush();
    const list = f.root.querySelector('#runs').innerHTML, said = f.root.querySelector('#rstatus .said').innerHTML;
    assert.equal(f.root.querySelector('#rcount').textContent, count);
    assert.match(list, /Example<\/span>/); assert.match(list, /An example Tau ran for you when you signed up\. It cost you nothing\./);
    assert.doesNotMatch(list, /Cost: \$0\.00/);
    if (own.length) { assert.match(said, /tested <em>3<\/em> hypotheses/); assert.match(list, /Cost: \$0\.42/); }
    else assert.doesNotMatch(said, /Your engine has tested/);
  }
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
  assert.match(html, />Test expected<button type="button" class="info" data-glo="pace"/);
  // $12 over 6 unseen trades = $2 a trade, so 5 closed trades -> +$10.00.
  assert.match(html, /\+\$10\.00<div class="sub-fig">same 5 trades<\/div>/);
  assert.match(html, /no closed trades/);
  assert.doesNotMatch(html, /Backtest unseen/);
});

test('Deploy open positions label every cell so phone cards read Contract, Side, Cost + fee', async () => {
  const pos = {title: 'Rain fade', ticker: 'KXRAINNYC-T1', side: 'no', qty: 4, entry_price: .37, entry_fee: .02, unrealized: null, market_close_time: '2026-10-25T17:30:00Z', mode: 'paper'};
  const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [], open_positions: [pos]}) : response({})});
  await f.viewDeploy(); await flush(); await flush();
  const html = f.root.querySelector('#openpos').innerHTML;
  for (const lab of ['Strategy', 'Contract', 'Side', 'Cost \\+ fee', 'Unrealized', 'Settles']) assert.match(html, new RegExp(`data-lab="${lab}"`), lab);
  // This Cost carries the entry fee ($1.48 + $0.02); the dashboard's Cost and "Open at cost" don't, so it says so.
  assert.match(html, /<th class="num">Cost \+ fee<\/th>/); assert.match(html, /data-lab="Cost \+ fee">\$1\.50</);
  assert.match(html, /<td class="name" data-lab="Strategy">Rain fade/);
});

test('every trade on the dashboard and Deploy says why it was entered and why it exited, escaped', async () => {
  const why = 'Entered at 41¢: the 5-minute return < −0.002, edge ≥ 3¢ after fees · Exited at 62¢: take-profit (+21¢ vs +20¢ target)';
  const row = (extra) => ({side: 'yes', qty: 1, entry_price: .41, title: 'Fade <b>', ticker: 'T-1', mode: 'paper', opened_at: '2026-10-25T08:00:00Z',
    closed_at: '2026-10-25T09:00:00Z', pnl: .2, ...extra});
  const open_positions = [row({why: 'Entered at 41¢: edge ≥ 3¢ after fees · Exits: +20¢ take-profit, else settlement'}), row({ticker: 'T-2', why: null})];
  const recent_closed = [row({status: 'closed', why}), row({ticker: 'T-3', status: 'closed', why: 'Held to settlement: <img src=x>'})];
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response({...emptyDashboard(), open_positions, recent_closed});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const html = f.root.querySelector('main').innerHTML;
  const lines = [...html.matchAll(/<small class="stub-why">([^<]*)<\/small>/g)].map((m) => m[1]);
  assert.deepEqual(lines, ['Entered at 41¢: edge ≥ 3¢ after fees · Exits: +20¢ take-profit, else settlement',
    why.replace('<', '&lt;'), 'Held to settlement: &lt;img src=x&gt;']);  // the row with no reason shows none
  assert.doesNotMatch(html, /<img/);
  const d = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [], open_positions}) : response({})});
  await d.viewDeploy(); await flush(); await flush();
  const table = d.root.querySelector('#openpos').innerHTML;
  assert.equal((table.match(/class="sub-fig pos-why"/g) || []).length, 1);
  assert.match(table, /data-lab="Contract">T-1<div class="sub-fig pos-why">Entered at 41¢: edge ≥ 3¢ after fees/);
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
  assert.match(html, /Autopilot ·\u00a0paper/); assert.match(html, /&lt;b&gt;BTC&lt;\/b&gt;/);
  assert.match(html, /\+\$12\.50/); assert.match(html, /1,234 tested ·\u00a00 passed/); assert.match(html, /<a href="\/strategies\/3"[^>]*>4 of 30 paper trades<\/a>/);
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

test('the empty paper track record follows the autopilot switch when a status read flips it', async () => {
  let status = {autopilot: false, mode: 'off'};
  const empty = (label) => ({trades: 0, label});
  const tr = {generated_at: 1, default_mode: 'paper', method: [], thresholds: {min_sharpe_days: 14, min_trades: 30},
    modes: {live: empty('Live money'), demo: empty('Kalshi demo'), paper: empty('Paper')}};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/track-record') return response(tr);
    if (path === '/api/autopilot/status') return response(status);
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false;
  await f.viewDashboard(); await flush(); await flush();
  // The dashboard mounts the record after <main>; mount it the same way on a host of its own here.
  const host = new Element('section'); f.root.appendChild(host);
  await f.mountTrackRecord(host, {at: null});
  const panel = () => host.querySelector('.trpanel').innerHTML;
  assert.match(panel(), /Go to Deploy/);
  // Switched on elsewhere (another tab, the chat): the next status poll carries it. The record's own
  // poll skips an unchanged payload, so before this the panel kept "Go to Deploy".
  status = {autopilot: true, mode: 'paper', story: [], research: {}, live_running: 0, demo_running: 0, paper_running: 0};
  for (const tick of [...f.intervals.values()]) tick();
  await flush(); await flush();
  assert.equal(f.S.me.user.autopilot, true);
  assert.match(panel(), /Autopilot runs the strategies that pass every gate on paper/); assert.doesNotMatch(panel(), /Go to Deploy/);
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

test('the dashboard demo bucket and the autopilot card say plainly when demo can’t trade, with the action', async () => {
  const health = {code: 'demo_funds', need: 'demo funds: your Kalshi demo account has $0.00',
    line: "Demo isn't trading: your Kalshi demo account has $0.00. Add demo funds on Kalshi's demo site.",
    action: {label: 'Open Kalshi demo', href: 'https://demo.kalshi.co'}};
  const said = /Demo isn&#39;t trading: your Kalshi demo account has \$0\.00\. Add demo funds on Kalshi&#39;s demo site\. <a href="https:\/\/demo\.kalshi\.co" target="_blank" rel="noopener">Open Kalshi demo ↗<\/a>/;
  const status = {...apOn, demo_running: 1, idle: health};
  const board = async (demo, ap) => {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response({...emptyDashboard(), demo});
      if (path === '/api/autopilot/status') return response(ap);
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    f.S.ap = ap; f.paintDashAp();
    return f;
  };
  const f = await board({equity: 1000, capital: 1000, running: 1, open_positions: 0, realized_pnl: 0, health}, status);
  // The line leads the demo figure, ahead of the capital that made the book look healthy.
  assert.match(f.root.querySelector('#boardbody').innerHTML, new RegExp('<span class="demo-health">' + said.source + '<\\/span><br>\\$1,000\\.00 capital'));
  assert.match(f.root.querySelector('#dash-ap').innerHTML, said);
  // An app-page action still opens in place.
  const k = await board({equity: 1000, capital: 1000, running: 1}, {...apOn, idle: {code: 'demo_key', line: 'Demo isn’t trading: no key.', action: {label: 'Add demo key', href: '/funds'}}});
  assert.match(k.root.querySelector('#dash-ap').innerHTML, /no key\. <a href="\/funds">Add demo key<\/a>/);
  const ok = await board({equity: 1000, capital: 1000, running: 1, open_positions: 0, realized_pnl: 0}, apOn);
  assert.doesNotMatch(ok.root.querySelector('#boardbody').innerHTML, /demo-health/);
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
    [{equity: 1000, capital: 1000}, /\$1,000\.00 capital ·\u00a0no demo strategies yet ·\u00a0real fills on Kalshi’s sandbox, not real money/],
    [{equity: 512, capital: 500, realized_pnl: 12, running: 1, open_positions: 0, before_reload: 40}, /\$500\.00 capital ·\u00a00 open ·\u00a0\+\$12\.00 P&amp;L since reload ·\u00a0real fills/],
    [{equity: 1012, capital: 1000, realized_pnl: 12, running: 1, open_positions: 0, before_reload: 0}, /\+\$12\.00 P&amp;L all time ·\u00a0real fills/],
  ]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response({...emptyDashboard(), demo});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    assert.match(f.root.querySelector('#boardbody').innerHTML, re);
  }
});

test('each dashboard money card offers its own trades CSV only when that mode has closed trades', async () => {
  for (const [counts, connected] of [[{paper: 0, demo: 0, live: 0}, false], [{paper: 4, demo: 0, live: 0}, false],
    [{paper: 0, demo: 2, live: 3}, true], [{paper: 0, demo: 0, live: 3}, false]]) {
    const d = emptyDashboard();
    d.paper.closed_trades = counts.paper;
    d.demo = {...d.demo, closed_trades: counts.demo};
    d.live = {connected, balance: connected ? 50 : null, realized_pnl: 0, today_pnl: 0, open_positions: 0, running: 0, closed_trades: counts.live};
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response(d);
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    const html = f.root.querySelector('#boardbody').innerHTML;
    for (const mode of ['paper', 'demo', 'live']) {
      const link = `<a class="csv-link" href="/api/trades.csv?mode=${mode}" download>Download trades (CSV)</a>`;
      assert.equal(html.includes(link), counts[mode] > 0, `${mode} ${JSON.stringify(counts)}`);
    }
    assert.equal((html.match(/csv-link/g) || []).length, Object.values(counts).filter(Boolean).length);
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

test('the live card says it is Kalshi cash, apart from what Tau trades realized', async () => {
  const liveDep = {id: 9, strategy_id: 9, title: 'Live one', market: 'btc15m', mode: 'live', status: 'running', stake: 5, max_positions: 2,
    realized_pnl: 17, unrealized_pnl: null, closed_trades: 3, open_positions: 2, created_at: '2026-10-25T08:00:00Z', curve: []};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response({...emptyDashboard(), deployments: [liveDep],
      live: {connected: true, balance: 250, open_positions: 2, running: 1, realized_pnl: 17, today_pnl: -2, open_at_cost: 1.2}});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const board = f.root.querySelector('#boardbody').innerHTML;
  // The balance is Kalshi's cash for the whole account; the line under it is Tau's own book.
  assert.match(board, /<span class="mk live">Real<\/span> Kalshi cash/); assert.match(board, /\$250\.00/);
  assert.match(board, /Tau trades: 2 open \(not in cash\) ·\u00a0\+\$17\.00 realized all time ·\u00a0−\$2\.00 realized today \(UTC\)/);  // a day figure says which day: it resets at 00:00 UTC
  assert.match(board, /Live money on: \+\$17\.00 realized all time/);
  // The autopilot card's day figure is the same booked P&L, and says so.
  f.S.me.user.autopilot = true; f.S.ap = {...apOn, live_running: 1, today_live_pnl: -2}; f.paintDashAp();
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Live realized today \(UTC\)<\/dt><dd><span class="[^"]*">−\$2\.00/);
});

test('Funds names the live figure Kalshi cash, open positions not included', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds();
    d.kalshi = {connected: true, key_id: 'abcd-wxyz', balance: 120, funding_url: 'https://kalshi.com'}; return response(d); }});
  await f.viewFunds();
  const figs = f.root.querySelector('#ffigs').innerHTML;
  assert.match(figs, /Kalshi cash/); assert.match(figs, /Your real cash at Kalshi, open positions not included/);
  assert.doesNotMatch(figs, /Live money/);
});

test('Deploy realized says it counts only the strategies listed, never summing live with paper', async () => {
  const dep = (id, mode, pnl) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode, status: 'running', status_reason: null,
    realized_pnl: pnl, closed_trades: 1, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1,
    backtest: {out_of_sample: null}});
  for (const [deployments, re] of [[[dep(1, 'paper', 2)], /\+\$2\.00[\s\S]*paper money, not real ·\u00a0strategies listed below/],
    [[dep(1, 'paper', 2), dep(2, 'live', 5)], /Live realized[\s\S]*\+\$5\.00[\s\S]*real money, strategies listed below ·\u00a0\+\$2\.00 on paper, counted apart/]]) {
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

test('the autopilot card says what switching it on costs before the click', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    throw new Error('Unexpected offline request: ' + path);
  }});
  const cost = () => f.root.querySelector('#dash-ap .apcard-cost');
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 18.4, auto_reload: {amount: 20, charge: 21.1, threshold: 5}};
  await f.viewDashboard(); await flush();
  assert.match(cost().innerHTML, /uses your credits while it's on \(\$18\.40 left\)/);
  assert.match(cost().innerHTML, /When they fall to \$5\.00, auto-reload charges your card \$21\.10 for \$20\.00 more\./);
  assert.match(cost().innerHTML, /<a href="\/billing">Billing<\/a>/);
  f.S.me.auto_reload = null; f.paintDashAp();
  assert.match(cost().innerHTML, /\(\$18\.40 left\) and pauses when they run out\. Turn it off any time\./);
  assert.doesNotMatch(cost().innerHTML, /auto-reload/);
  f.S.me.billing_enabled = false; f.paintDashAp();  // payments off on this server: nothing is spent
  assert.equal(cost(), null);
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /Turn on autopilot/);
});

test('right after switching on, the card says the first review is running, not that it already moved', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = true;
  const at = new Date().toISOString();
  f.S.ap = {...apOn, paper_running: 0, paper_progress: null, reviewing: true, last_review_at: at, last_action: {at, text: 'Autopilot is ON: …'}};
  await f.viewDashboard(); await flush();
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Last move<\/dt><dd>Reviewing now<\/dd>/);
  f.S.ap = {...f.S.ap, reviewing: false}; f.paintDashAp();
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Last move<\/dt><dd>just now<\/dd>/);
});

test('the floating autopilot pill steps aside while it would cover a primary or submit button', () => {
  const f = frontend(), body = f.root.parent;
  f.root.innerHTML = '<main id="main"><form id="dispatch"><button class="btn primary go" type="submit">Start session</button></form><a class="btn" href="/x">Other</a></main>';
  const box = new Element('div', {id: 'autopilot-float', class: 'apf'}); body.appendChild(box);
  box.innerHTML = '<button type="button" class="apf-pill" data-ap="toggle">Autopilot off</button>';
  const rect = (l, t, r, b) => () => ({left: l, top: t, right: r, bottom: b, width: r - l, height: b - t});
  const go = f.root.querySelector('#dispatch .go');
  box.querySelector('.apf-pill').getBoundingClientRect = rect(1249, 848, 1384, 884);
  go.getBoundingClientRect = rect(1170, 803, 1355, 841);  // Research at 1400x900: the row right above the pill
  f.apYield(); assert.equal(box.classes.has('yield'), true);
  go.getBoundingClientRect = rect(1170, 403, 1355, 441);  // scrolled up and away
  f.apYield(); assert.equal(box.classes.has('yield'), false);
  go.getBoundingClientRect = rect(31, 798, 359, 840);     // phone: a full-width button under the pill
  box.querySelector('.apf-pill').getBoundingClientRect = rect(245, 798, 380, 834);
  f.apYield(); assert.equal(box.classes.has('yield'), true);
  go.getBoundingClientRect = rect(0, 0, 0, 0);            // not laid out (hidden): nothing to yield to
  f.apYield(); assert.equal(box.classes.has('yield'), false);
  // A plain link under the pill doesn't count, and the open panel (no pill) never yields.
  f.root.querySelector('a.btn').getBoundingClientRect = rect(1249, 848, 1384, 884);
  f.apYield(); assert.equal(box.classes.has('yield'), false);
  box.classList.add('yield'); box.innerHTML = '<div class="apf-head"></div>';
  f.apYield(); assert.equal(box.classes.has('yield'), false);
});

test('the autopilot panel shows Kill only once real money is armed or running', () => {
  const f = frontend();
  const controls = d => {
    const box = new Element('div'); box.innerHTML = '<div id="apf-controls"></div>';
    f.apUpdate(box, {mode: 'paper', live_enabled: true, kalshi_connected: false, ...d});
    return box.querySelector('#apf-controls').innerHTML;
  };
  const off = controls({autopilot: false});
  assert.doesNotMatch(off, /data-ap="kill"|data-ap="livearm"/); assert.match(off, /See what's trading/);
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
  assert.match(html, />Bitcoin price on Oct 25, 2026\? ·\u00a0\$80,500 or above</);
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
  assert.match(snap('demo'), /·\u00a0demo ·/); assert.match(snap('paper'), /·\u00a0paper ·/); assert.match(snap('live'), /·\u00a0live ·/);
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

test('a queued run counts its wait from the server, and past the reaper limit says plainly it is waiting', async () => {
  const at = (wait, status = 'queued') => {
    const run = {id: 9, prompt: 'Idea', status, market: 'btc15m', created_at: '2026-10-17T10:00:00Z', wait};
    return frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: []}); }});
  };
  // Under the limit: the spinner stays, but the count is the server's (a reload used to restart it at 0s).
  let f = at({state: 'queued', seconds: 200, overdue: false});
  await f.viewRun(9);
  [...f.intervals.values()].forEach(tick => tick());
  assert.match(f.root.querySelector('#runpulse [data-plabel]').textContent, /^Queued ·\u00a020\ds$/);
  assert.equal(f.root.querySelector('#rsiobs [data-wait]').hidden, true);
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').hidden, false);  // not overdue: the phase line stays
  f.clearTimers();
  // Past it: no spinner, how long, and how many sessions a worker takes first.
  f = at({state: 'queued', seconds: 360, overdue: true, ahead: 2});
  await f.viewRun(9);
  const line = 'Still waiting for a free research worker (6 min). 2 sessions are ahead of it; it starts when one frees up.';
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Waiting 6 min/);
  assert.ok(f.root.querySelector('#runpulse').classes.has('late'));
  assert.ok(f.root.querySelector('#runpulse').innerHTML.includes(line));
  assert.doesNotMatch(f.root.querySelector('#runpulse').innerHTML, /class="working"/);
  const wait = f.root.querySelector('#rsiobs [data-wait]');
  assert.equal(wait.hidden, false); assert.equal(wait.textContent, line);
  // The wait line replaces "Waiting for the agent to start." rather than sitting under it.
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').hidden, true);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Waiting 6 min');
  f.clearTimers();
  f = at({state: 'queued', seconds: 300, overdue: true, ahead: 0});
  await f.viewRun(9);
  assert.equal(f.root.querySelector('#rsiobs [data-wait]').textContent, 'Still waiting for a free research worker (5 min). It’s next in line and starts when one frees up.');
  f.clearTimers();
  // A running session whose heartbeat is past the limit reads as silent, not Researching.
  f = at({state: 'silent', seconds: 420, overdue: true}, 'running');
  await f.viewRun(9);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Silent 7 min/);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Silent 7 min');
  assert.ok(f.root.querySelector('#runpulse').innerHTML.includes('No word from the agent for 7 min. A session this quiet is normally interrupted and resumed from its last checkpoint.'));
  f.clearTimers();
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

const memoryStorage = () => { const stored = new Map(); return {getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, String(value))}; };

test('the autopilot card and panel say where it may trade, with a Change that opens the focus control', async () => {
  const f = frontend({storage: memoryStorage(), fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/autopilot/status') return response({...apOn, focus: ['crypto']});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = true; f.S.ap = {...apOn, focus: ['crypto']};
  await f.viewDashboard(); await flush();
  const card = f.root.querySelector('#dash-ap');
  assert.match(card.querySelector('.ap-focus').innerHTML, /^Focus: Crypto <button type="button" data-apcard="focus">Change<\/button>$/);
  await card.querySelector('[data-apcard="focus"]').onclick(); await flush();
  const box = f.root.parent.querySelector('#autopilot-float');
  assert.equal(box.querySelector('.apf-prefs').open, true);  // the control sits in "Model and markets"
  f.apUpdate(box, f.S.ap);
  const line = box.querySelector('#apf-focusline');
  assert.equal(line.hidden, false); assert.match(line.innerHTML, /^Focus: Crypto <button type="button" data-ap="focus">Change<\/button>$/);
  box.querySelector('.apf-prefs').open = false;
  line.querySelector('[data-ap="focus"]').onclick();
  assert.equal(box.querySelector('.apf-prefs').open, true);
  // No focus reads as any market; tokens the presets don't name are spelled out.
  for (const [focus, text] of [[[], 'any market'], [['btc'], 'Bitcoin'], [['weather-high', 'sports'], 'Weather high, Sports']]) {
    f.S.ap = {...apOn, focus}; f.paintDashAp();
    assert.match(f.root.querySelector('#dash-ap .ap-focus').innerHTML, new RegExp(`^Focus: ${text} <button`), text);
  }
  // Before a status read has the focus, the card makes no claim about it.
  f.S.ap = {...apOn}; delete f.S.ap.focus; f.paintDashAp();
  assert.equal(f.root.querySelector('#dash-ap .ap-focus'), null);
  f.clearTimers();
});

test('switching autopilot on in the panel opens the market focus control', async () => {
  const f = frontend({storage: memoryStorage(), fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/settings') return response({ok: true});
    if (path === '/api/autopilot/status') return response({...apOn, focus: []});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false; f.S.ap = {...apOn, autopilot: false, mode: 'off', focus: []};
  await f.viewDashboard(); await flush();
  await f.root.querySelector('#dash-ap [data-apcard="focus"]').onclick(); await flush();  // the off card offers it too
  const box = f.root.parent.querySelector('#autopilot-float'), prefs = box.querySelector('.apf-prefs');
  prefs.open = false;
  const sw = box.querySelector('#apf-apswitch'); sw.checked = true; await sw.onchange(); await flush();
  assert.equal(f.S.me.user.autopilot, true); assert.equal(prefs.open, true);
  f.clearTimers();
});

test('the autopilot card and panel show the last 7 days with real credits and paper P&L kept apart', async () => {
  const week = {research_credits: 7.26, tested: 1234, passed: 2, paper_started: 1, paper_pnl: -3.46, paper_trades: 4};
  const stored = new Map();
  const f = frontend({storage: {getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, String(value))}, fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/autopilot/status') return response({...apOn, week});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = true; f.S.ap = {...apOn, week};
  await f.viewDashboard(); await flush();
  const card = f.root.querySelector('#dash-ap .ap-week').innerHTML;
  assert.match(card, /<h3>Last 7 days<\/h3>/);
  assert.match(card, /<dt>Credits spent on research<\/dt><dd>\$7\.26 <small>real money<\/small><\/dd>/);
  assert.match(card, /<dt>Ideas<\/dt><dd>1,234 tested ·\u00a02 passed<\/dd>/);
  assert.match(card, /<dt>Autopilot put on paper<\/dt><dd>1 strategy <small>not counting yours<\/small><\/dd>/);
  assert.match(card, /<dt>Autopilot's paper P&amp;L<\/dt><dd><span class="neg">−\$3\.46<\/span> <small>paper, not real money ·\u00a04 closed trades<\/small><\/dd>/);
  assert.match(card, /The two paper rows count only what the autopilot put on paper itself; strategies you deploy yourself count in the running total and on the Deploy page, not here/);
  assert.doesNotMatch(card, /\$3\.80|\$10\.72/);  // never netted or summed
  assert.doesNotMatch(f.root.querySelector('#dash-ap').innerHTML, /Ideas this week/);  // the scorecard says it
  await f.root.querySelector('#dash-ap [data-apcard="open"]').onclick(); await flush();
  const box = f.root.parent.querySelector('#autopilot-float');
  assert.match(box.querySelector('#apf-week').innerHTML, /Credits spent on research[\s\S]*paper, not real money/);
  f.apUpdate(box, {...apOn, autopilot: false, mode: 'off', week});
  assert.equal(box.querySelector('#apf-week').innerHTML, '');  // off: no scorecard
  f.clearTimers();
});

test('beside Start session the form says what a session usually costs, from ledger data', async () => {
  const research = (estimate) => frontend({fetchImpl: path => {
    if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}, {key: 'haiku', label: 'Haiku'}], default: 'opus'});
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/research/estimate') return estimate ? response(estimate) : response({error: 'down'}, 503);
    if (path === '/api/runs') return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null});
    if (path.startsWith('/api/research/scoreboard')) return response({});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  // The user's own median, phrased per round while run-forever is on (the default), per session when off.
  let f = research({yours: 1.8, sessions: 6, typical: {opus: 9, haiku: 0.4}});
  await f.viewResearch(); await flush(); await flush();
  const cost = () => f.root.querySelector('#rcost'), rf = f.root.querySelector('#runforever');
  assert.equal(cost().hidden, false);
  assert.equal(cost().textContent, 'Each round of ideas usually costs about $1.80 (your recent sessions); it keeps starting new rounds until you stop it.');
  rf.checked = false; rf.dispatchEvent({type: 'change'});
  assert.equal(cost().textContent, 'Usually about $1.80 (your recent sessions).');
  assert.match(f.root.querySelector('#rf-hint').textContent, /A session takes a few minutes/);  // the hint still follows the switch
  // Fewer than 3 of their own: the typical cost for the chosen model, following the model picker.
  f = research({yours: null, sessions: 1, typical: {opus: 2.25}});
  await f.viewResearch(); await flush(); await flush();
  assert.match(cost().textContent, /^Each round of ideas usually costs about \$2\.25 \(recent sessions on this model\)/);
  const model = f.root.querySelector('#rmodel'); model.value = 'haiku'; model.dispatchEvent({type: 'change'});
  assert.equal(cost().hidden, true); assert.equal(cost().textContent, '');  // no data for this model: nothing
  // No data at all, or the read failed: nothing.
  for (const estimate of [{yours: null, sessions: 0, typical: {}}, null]) {
    f = research(estimate);
    await f.viewResearch(); await flush(); await flush();
    assert.equal(cost().hidden, true); assert.equal(cost().textContent, '');
  }
});

test('autopilot says why it is not trading: the card and the panel lead with one line and its action', async () => {
  // One store both harnesses take: Tau's reads getItem/setItem, Meridian's a Map.
  const stored = new Map(); stored.getItem = key => stored.get(key) ?? null; stored.setItem = (key, value) => stored.set(key, String(value));
  const f = frontend({storage: stored,
    fetchImpl: path => {
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      return response({});
    }});
  f.S.me.user.autopilot = true;
  f.root.innerHTML = '<div id="dash-ap"></div>';
  const box = new Element('div', {id: 'autopilot-float'}); f.root.parent.appendChild(box);
  const base = {autopilot: true, mode: 'paper', research: {tested_7d: 0, passed_7d: 0, active: []}, live_running: 0, demo_running: 0,
    paper_running: 0, paper_progress: null, focus: [], story: ['Right now it’s between research runs.', 'Nothing trades real money until...']};
  const card = () => f.root.querySelector('#dash-ap .apcard-now');
  const idleP = () => box.querySelector('#apf-story .apf-idle');
  // Every paper strategy paused by its stop: the line and a link to Deploy, on the card and atop the panel.
  f.S.ap = {...base, idle: {code: 'stopped', line: 'Nothing is trading: Fade <tails> is paused: it hit its loss guard.', action: {label: 'Open Deploy', href: '/deploy'}}};
  f.paintDashAp();
  assert.equal(card().innerHTML, 'Nothing is trading: Fade &lt;tails&gt; is paused: it hit its loss guard. <a href="/deploy">Open Deploy</a>');
  f.root.querySelector('#dash-ap [data-apcard="open"]').onclick(); await flush();
  assert.equal(idleP().innerHTML, 'Nothing is trading: Fade &lt;tails&gt; is paused: it hit its loss guard. <a href="/deploy">Open Deploy</a>');
  const lines = box.querySelectorAll('#apf-story p').map(p => p.innerHTML);
  assert.equal(lines.length, 3); assert.equal(lines[1], 'Right now it’s between research runs.');
  // A stalled engine has no action: the line alone, in place of a healthy-looking "between research runs".
  f.S.ap = {...base, paper_running: 1, idle: {code: 'engine', line: 'Nothing is trading right now: Tau’s trading engine isn’t running.', action: null}};
  f.paintDashAp(); f.root.querySelector('#dash-ap [data-apcard="open"]').onclick(); await flush();
  assert.equal(card().innerHTML, 'Nothing is trading right now: Tau’s trading engine isn’t running.');
  assert.doesNotMatch(card().innerHTML, /between research runs/);
  assert.equal(idleP().innerHTML, 'Nothing is trading right now: Tau’s trading engine isn’t running.');
  // Focus with nothing inside it: Change focus opens the control, from the card and from the panel.
  f.S.ap = {...base, focus: ['sports'], idle: {code: 'focus', line: 'Nothing is on paper: your focus is sports.', action: {label: 'Change focus', do: 'focus'}}};
  f.paintDashAp();
  assert.equal(card().innerHTML, 'Nothing is on paper: your focus is sports. <button type="button" data-apcard="idle-focus">Change focus</button>');
  f.root.querySelector('#dash-ap [data-apcard="idle-focus"]').onclick(); await flush();
  assert.equal(box.querySelector('.apf-prefs').open, true);
  box.querySelector('.apf-prefs').open = false;
  idleP().querySelector('[data-ap="idle-focus"]').onclick();
  assert.equal(box.querySelector('.apf-prefs').open, true);
  // Billing keeps its own lines (card and gates); the panel adds no idle line over them.
  f.S.ap = {...base, billing_blocked: true, billing_reason: 'card', story: [],
    idle: {code: 'billing', line: 'Nothing is on paper, and it can’t research.', action: {label: 'Add a payment method', href: '/billing'}}};
  f.paintDashAp(); f.root.querySelector('#dash-ap [data-apcard="open"]').onclick(); await flush();
  assert.match(card().innerHTML, /^Paused: <a href="\/billing">add a payment method<\/a>/);
  assert.equal(idleP(), null);
  // Trading (no idle): the card goes back to what it's doing.
  f.S.ap = {...base, paper_running: 2, idle: null};
  f.paintDashAp();
  assert.equal(card().innerHTML, 'Right now it’s between research runs.');
});

// Each deployment row draws its cumulative realized P&L: two points or more, a line coloured by its
// last value and labelled with it and the trade count; one trade draws nothing. Each mode keeps its
// own dollar axis, so a paper curve that peaked at $500 doesn't flatten a live one that lost $3.
const sparkDeployment = (id, mode, closed, curve) => ({id, strategy_id: id, title: `Spark ${id}`, market: 'btc15m', mode,
  status: 'running', stake: 5, max_positions: 2, backtest: {out_of_sample: null}, created_at: '2026-10-17T10:00:00Z',
  realized_pnl: curve.length ? curve[curve.length - 1][1] : 0, unrealized_pnl: null, closed_trades: closed, open_positions: 0, curve});
const sparkPayload = () => ({...emptyDashboard(), deployments: [
  sparkDeployment(1, 'paper', 48, [[1760000000, 2], [1760003600, -1], [1760007200, 500], [1760010800, 12.4]]),
  sparkDeployment(2, 'live', 2, [[1760000000, -1], [1760003600, -3]]),
  sparkDeployment(3, 'paper', 1, [[1760000000, 1]]),
]});
for (const [label, view, endpoint, selector] of [['The dashboard', 'viewDashboard', '/api/dashboard', '#dash-deps'], ['Deploy', 'viewDeploy', '/api/deployments', '#deps']]) {
  test(`${label} draws a cumulative P&L sparkline per deployment, by mode, with a labelled sign`, async () => {
    const f = frontend({fetchImpl: path => {
      if (path === endpoint) return response(sparkPayload());
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f[view](); await flush(); await flush();
    const html = f.root.querySelector(selector).innerHTML;
    const svgs = [...html.matchAll(/<svg class="spark (up|down|flat)"[^>]*aria-label="([^"]*)"[^>]*>.*?<\/svg>/g)];
    assert.equal(svgs.length, 2, html);  // the one-trade deployment draws none
    const [up, down] = [svgs.find((m) => m[1] === 'up'), svgs.find((m) => m[1] === 'down')];
    assert.equal(up[2], 'Cumulative P&amp;L, +$12.40 over 48 trades');
    assert.equal(down[2], 'Cumulative P&amp;L, −$3.00 over 2 trades');
    for (const m of svgs) {
      assert.match(m[0], /role="img"/); assert.match(m[0], /viewBox="0 0 80 24"/);
      assert.match(m[0], /<line class="spark-zero"/);
    }
    // The live line uses live's own axis: its -$1 sits well above the bottom, not squashed by paper's $500.
    const livePts = down[0].match(/points="([^"]+)"/)[1].split(' ').map((p) => +p.split(',')[1]);
    assert.ok(livePts[0] < 12 && livePts[1] === 22, livePts.join(' '));
  });
}

const staleDashboard = equity => ({...emptyDashboard(), paper: {...emptyDashboard().paper, equity}});

// A poll that fails (no network, the edge's 5xx page, or a read that hangs until it is aborted) leaves
// the last good figures up. Once they are older than about two polls a quiet note says how old, the
// poll sits out more ticks after each failure instead of hammering the server, and the next good read
// clears the note.
const staleFail = {
  'a network error': [() => Promise.reject(new TypeError('Failed to fetch')), 3],
  'a 5xx page': [() => ({ok: false, status: 503, json: async () => { throw new SyntaxError('Unexpected token <'); }}), 3],
  'a hung read': [options => new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))), 1],
};
// Runs a read to its end: each step fires the newest timer (a retry's pause, or else the read's 15s abort).
const settleRead = async f => {
  for (let i = 0; i < 8; i++) {
    await flush(); await flush();
    const last = [...f.timeouts].at(-1); if (!last) break;
    f.timeouts.delete(last[0]); last[1]();
  }
  await flush(); await flush();
};
const pollStep = async (f, tick, ms) => { f.shiftClock(ms); f.timeouts.clear(); tick(); await settleRead(f); };
for (const [kind, [fail, perTry]] of Object.entries(staleFail)) {
  test(`the dashboard keeps its figures through ${kind}, says how old they are, backs off and clears on recovery`, async () => {
    let down = false, equity = 1000;
    const f = frontend({fetchImpl: (path, options) => {
      if (path === '/api/dashboard') return down ? fail(options) : response(staleDashboard(equity));
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush(); await flush();
    const tick = f.intervals.get(f.S.timers[0]);
    const note = () => f.root.querySelector('#dash-stale').textContent;
    const figures = () => f.root.querySelector('#boardbody').innerHTML;
    const reads = () => f.requests.filter(r => r.path === '/api/dashboard').length;
    assert.equal(note(), '');
    down = true;
    let before = reads();
    await pollStep(f, tick, 15000);  // one failed poll: 15s old is under two polls, so no note yet
    assert.equal(reads() - before, perTry);  // api() retries a network error or an edge 5xx twice; an aborted hang once
    assert.equal(note(), ''); assert.match(figures(), /\$1,000\.00/);
    before = reads();
    await pollStep(f, tick, 20000);  // it sits this tick out, and the 35s-old figures now say so
    assert.equal(reads(), before);
    assert.equal(note(), 'Last updated 35s ago, retrying'); assert.match(figures(), /\$1,000\.00/);
    await pollStep(f, tick, 15000);  // the second try fails too, so it sits out the next three ticks
    assert.equal(reads() - before, perTry); before = reads();
    assert.equal(note(), 'Last updated 50s ago, retrying');
    for (let i = 0; i < 3; i++) await pollStep(f, tick, 20000);
    assert.equal(reads(), before);
    assert.equal(note(), 'Last updated 2m ago, retrying'); assert.match(figures(), /\$1,000\.00/);
    down = false; equity = 1234.5;
    await pollStep(f, tick, 15000);
    assert.equal(reads() - before, 1);
    assert.equal(note(), ''); assert.match(figures(), /\$1,234\.50/);
  });
}

test('a research run keeps its spend when its poll fails, notes the age, and clears on recovery', async () => {
  let down = false, spent = 1.25;
  const f = frontend({fetchImpl: path => {
    assert.equal(path, '/api/runs/9?after=0');
    if (down) return Promise.reject(new TypeError('Failed to fetch'));
    return response({run: {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z',
      started_at: '2026-10-17T10:00:00Z', spent_usd: spent, hypotheses_tried: 2}, events: []});
  }});
  await f.viewRun(9);
  const tick = f.intervals.get(f.S.timers.at(-1));
  const note = () => f.root.querySelector('#run-stale').textContent;
  assert.equal(note(), '');
  down = true;
  await pollStep(f, tick, 2000);  // a 2s poll waits 10s before it calls its figures old
  assert.equal(note(), ''); assert.match(f.root.querySelector('#runfigs').innerHTML, /\$1\.25/);
  const before = f.requests.length;
  await pollStep(f, tick, 9000);
  assert.equal(f.requests.length, before);  // backing off: no read this tick
  assert.equal(note(), 'Last updated 11s ago, retrying'); assert.match(f.root.querySelector('#runfigs').innerHTML, /\$1\.25/);
  down = false; spent = 1.5;
  await pollStep(f, tick, 2000);
  assert.equal(note(), ''); assert.match(f.root.querySelector('#runfigs').innerHTML, /\$1\.50/);
});

test('the autopilot card keeps its figures when the status poll fails, notes the age, and clears on recovery', async () => {
  let down = false;
  const status = {autopilot: true, mode: 'paper', story: ['Researching BTC 15m.'], research: {tested_7d: 3, passed_7d: 0, active: []},
    live_running: 1, demo_running: 0, paper_running: 0, today_live_pnl: 4.5};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(staleDashboard(1000));
    if (path === '/api/autopilot/status') return down ? Promise.reject(new TypeError('Failed to fetch')) : response(status);
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = true; f.S.ap = status; f.S.apAt = Date.now();
  await f.viewDashboard(); await flush(); await flush();
  const tick = [...f.intervals.values()].find(cb => String(cb).includes("getElementById('autopilot-float') && !document.hidden) tick()"));
  const note = () => f.root.querySelector('#dash-ap-stale').textContent;
  const card = () => f.root.querySelector('#dash-ap').innerHTML;
  const reads = () => f.requests.filter(r => r.path === '/api/autopilot/status').length;
  assert.equal(note(), ''); assert.match(card(), /4\.50/);
  down = true;
  await pollStep(f, tick, 20000);
  assert.equal(note(), ''); assert.match(card(), /4\.50/);
  const before = reads();
  await pollStep(f, tick, 25000);
  assert.equal(reads(), before);  // backing off: no read this tick
  assert.equal(note(), 'Last updated 45s ago, retrying');
  f.paintDashAp();  // a repaint for another reason keeps the note
  assert.equal(note(), 'Last updated 45s ago, retrying'); assert.match(card(), /4\.50/);
  down = false;
  await pollStep(f, tick, 20000);
  assert.equal(reads(), before + 1);
  assert.equal(note(), ''); assert.match(card(), /4\.50/);
});


test('a run poll never stacks a second read on one that is still hanging', async () => {
  let hang = false;
  const f = frontend({fetchImpl: (path, options) => hang
    ? new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
    : response({run: {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'}, events: []})});
  await f.viewRun(9);
  const tick = f.intervals.get(f.S.timers.at(-1)), before = f.requests.length;
  hang = true;
  for (let i = 0; i < 7; i++) { f.shiftClock(2000); tick(); await flush(); }  // 14s of 2s ticks while one read hangs
  assert.equal(f.requests.length, before + 1);  // it used to send seven
  assert.equal(f.root.querySelector('#run-stale').textContent, 'Last updated 14s ago, retrying');
});

test('the dead "Dig deeper" win card is gone, and phone tap targets stay 40px or more', () => {
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  assert.ok(!/winCard|data-dig|win-card/.test(source), 'winCard has no callers; its markup and click hook stay deleted');
  assert.ok(!/\.wins?\b|\.win-(card|title|meta|foot|pnl|act)\b/.test(css), 'and so does its CSS');
  const touch = css.slice(css.indexOf('@media (pointer: coarse)'));
  const block = touch.slice(0, touch.indexOf('\n}\n'));
  assert.match(block, /\.bell-trig \{ min-width: 44px;/);
  assert.match(block, /\.apf-pill \{ min-height: 40px; \}/);
  assert.match(block, /\.t-explore \.xlink a \{ min-width: 44px; min-height: 44px;/);
  assert.match(block, /\.info \{ width: 40px; height: 40px;/);
  // Inline text buttons get a 41px tall hit area from padding that a matching negative margin cancels out.
  assert.match(css, /\.research-ap button \{[^}]*padding: 10px 4px; margin: -10px -4px;/);
  assert.match(css, /\.ap-focus button \{[^}]*padding: 10px 4px; margin: -10px -4px -10px 0;/);
  // The RSI disclosure's chevron is pinned right, so a long caption never pushes it onto a row of its own.
  assert.match(css, /\.rsidisc \.pipechev \{ position: absolute; right: 14px;/);
});

test('Tau phone polish: a glossary marker keeps its last word, one rule where boxes meet, touch controls 40px or more', async () => {
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  const f = frontend({fetchImpl: path => (path.startsWith('/api/strategies?')
    ? response({strategies: [], counts: {total: 3, passed: 1, failed: 1, rejected: 1}}) : response({}))});
  await f.viewStrategies(); await flush(); await flush();
  const figs = f.root.querySelector('#sfigs').innerHTML;
  // The marker shares a no-wrap span with the label's last word, so it never wraps onto a line of its own.
  assert.match(figs, /Void on unseen <span class="nobr">data<button type="button" class="info" data-glo="void"/);
  assert.match(figs, /Rejected in <span class="nobr">testing<button type="button" class="info" data-glo="rejected"/);
  assert.match(figs, /<span class="nobr">Passed<button type="button" class="info" data-glo="passed"/);
  assert.doesNotMatch(source, /fig\('[^']*' \+ glo\(/, 'figure labels go through gl(), not label + glo()');
  assert.match(css, /\.nobr \{ white-space: nowrap; \}/);
  // Phone: the RSI tag sits under the title instead of wrapping to the far left under the badge,
  // and the system map scrolls sideways at a readable size.
  const phone = css.slice(css.lastIndexOf('@media (max-width: 760px)'));
  assert.match(phone, /\.rsi-head > \.rsi-tag \{ grid-column: 2;/);
  assert.match(phone, /\.rsidisc-cap > \.rsi-tag, \.rsidisc-cap > \.rsidisc-delta \{ grid-column: 3;/);
  assert.match(phone, /\.sys-wrap \{ overflow-x: auto;/);
  // One rule where two boxes meet.
  assert.match(css, /\.rengine:has\(\.rsidisc\.loop\) \+ \.pipefig \{ border-top: 0; \}/);
  assert.match(css, /\.pipefig:not\(\[open\]\) > \.pipecap \{ border-bottom: 0; \}/);
  // The composer's strategy picker keeps a usable width (it was squeezed to ~20px at 390px).
  assert.match(source, /<label class="field post-strat-f">/);
  assert.match(css, /\.post-tools > \.post-strat-f \{ flex: 1 1 160px; min-width: 0; \}/);
  // Touch: every field, summary, slider and small link that measured under 40px at 360px.
  const touch = css.slice(css.lastIndexOf('@media (pointer: coarse)'));
  const block = touch.slice(0, touch.indexOf('\n}\n'));
  assert.match(block, /\.input, select, input\[type=text\][^{]*\{ min-height: 44px; \}/);
  assert.match(block, /input\[type=range\] \{ height: 40px; \}/);
  assert.match(block, /details > summary \{ padding-block: 11px; min-height: 40px; \}/);
  assert.match(block, /td\.name > a:not\(\.btn\) \{ padding-block: 10px; margin-block: -10px; \}/);
  assert.match(block, /\.legal-nav a, \.legal-foot a, \.lfoot-links a, \.linkish \{ padding: 10px 4px; margin: -10px -4px; \}/);
  // The onboarding controls (Deploy, Start session, the quick deploy) keep their own sizes.
  assert.doesNotMatch(block, /#dep-(paper|demo|live)|\.go\b|strat-quick/);
});

test('Tau: separators wrap with the item after them, the phone tabs show which edge has more, stacked cells are named', () => {
  const f = frontend();
  // Every " · " in the bundle binds to the next item (" · "), so a wrapped line never ends on a dot.
  // Only comments and the line that splits Kalshi's own titles on the plain separator keep it.
  const loose = source.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l) && !l.includes('split(') && / · | \\u00b7 /.test(l.replace(/\s\/\/\s.*$/, '')));
  assert.deepEqual(loose, []);
  // The tab row marks the edges that have more tabs past them, and drops the mark once you reach the end.
  const nav = new Element('nav', {class: 'services'}), tabs = new Element('div', {class: 'services-in'});
  nav.appendChild(tabs);
  Object.assign(tabs, {scrollWidth: 700, clientWidth: 390, scrollLeft: 0});
  f.tabEdges(tabs);
  assert.equal(nav.classes.has('more-r'), true); assert.equal(nav.classes.has('more-l'), false);
  tabs.scrollLeft = 150; tabs.dispatchEvent({type: 'scroll'});
  assert.equal(nav.classes.has('more-r'), true); assert.equal(nav.classes.has('more-l'), true);
  tabs.scrollLeft = 310; tabs.dispatchEvent({type: 'scroll'});
  assert.equal(nav.classes.has('more-r'), false); assert.equal(nav.classes.has('more-l'), true);
  Object.assign(tabs, {scrollWidth: 390, scrollLeft: 0}); tabs.dispatchEvent({type: 'scroll'});  // a wide screen: no hint
  assert.equal(nav.classes.has('more-r'), false); assert.equal(nav.classes.has('more-l'), false);
  // A strategy card's status cell is labelled; the Funds paper ledger names its cells like the credits ledger.
  assert.match(f.strategySlip({id: 1, title: 'T', thesis: '', market: 'btc15m', status: 'passed', out_of_sample: {pnl: 1, trades: 3, win_rate: .5}}, {}),
    /<td class="act st" data-lab="Status">/);
  assert.match(source, /<td class="hint lead-cell" data-lab="When">\$\{when\(r\.created_at\)\}<\/td><td class="name" data-lab="What">[^\n]*data-lab="Amount">/);
});

test('the floating autopilot pill also steps aside from a figure under it', () => {
  const f = frontend(), body = f.root.parent;
  f.root.innerHTML = '<div id="boardbody"><dl class="figures"><div class="m"><dt>Kalshi cash</dt><dd><span class="fig">Not connected</span></dd></div></dl></div><main id="main"><table class="stack"><tbody><tr><td class="num" data-lab="Trades">12</td></tr></tbody></table></main>';
  const box = new Element('div', {id: 'autopilot-float', class: 'apf'}); body.appendChild(box);
  box.innerHTML = '<button type="button" class="apf-pill" data-ap="toggle">Autopilot ·\u00a0paper</button>';
  const rect = (l, t, r, b) => () => ({left: l, top: t, right: r, bottom: b, width: r - l, height: b - t});
  const none = rect(0, 0, 0, 0);
  box.querySelector('.apf-pill').getBoundingClientRect = rect(220, 794, 380, 834);   // 390x844 phone
  const block = f.root.querySelector('.figures .m'), fig = f.root.querySelector('.fig'), cell = f.root.querySelector('td.num');
  [block, fig, cell].forEach((el) => { el.getBoundingClientRect = none; });
  block.getBoundingClientRect = rect(212, 800, 374, 900);   // the figure's label peeks in at the bottom of the screen
  f.apYield(); assert.equal(box.classes.has('yield'), true);
  block.getBoundingClientRect = rect(212, 200, 374, 300);   // scrolled up and away
  f.apYield(); assert.equal(box.classes.has('yield'), false);
  cell.getBoundingClientRect = rect(263, 790, 374, 830);    // a deployment card's number
  f.apYield(); assert.equal(box.classes.has('yield'), true);
});

test('Tau: a finished session says what to do next: your own idea after the example, the passed strategy after yours', async () => {
  const at = async (run, strategies) => {
    const f = frontend({fetchImpl: () => response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: '2026-10-25T10:00:00Z', ...run}, events: [], strategies})});
    await f.viewRun(9); f.clearTimers();
    return f.root.querySelector('#runnext').innerHTML;
  };
  // The example's log ends on "now describe a real idea": the page now gives the button to do it.
  assert.match(await at({status: 'succeeded', example: true}, []), /<a class="btn primary" href="\/research\?new=1">Describe your own idea<\/a>/);
  // A session that passed something links straight to it, above the log (escaped), and not to what it rejected.
  const html = await at({status: 'succeeded'}, [{id: 42, title: '<b>Late</b> momentum', status: 'passed'}, {id: 43, title: 'Fade', status: 'rejected'}]);
  assert.match(html, /Passed: <a href="\/strategies\/42">&lt;b&gt;Late&lt;\/b&gt; momentum<\/a>\. Open it to deploy it on paper\./);
  assert.doesNotMatch(html, /strategies\/43/);
  assert.match(await at({status: 'succeeded'}, [{id: 43, title: 'Fade', status: 'rejected'}]), /Nothing passed this time\. Most ideas don’t\. <a href="\/research\?new=1">Try another idea<\/a>/);
  assert.equal(await at({status: 'running'}, []), '');  // still going: nothing to do yet
});

test('Tau: after a deploy the Deploy page offers autopilot in words, and the panel says what its switch does', async () => {
  const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [{id: 1, strategy_id: 1, title: 'Dep 1', market: 'btc15m', mode: 'paper', status: 'running', status_reason: null, realized_pnl: 0, closed_trades: 0, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-25T08:00:00Z', curve: [], stake: 5, max_positions: 20, backtest: {out_of_sample: null}}], open_positions: []}) : response({})});
  f.S.me.user.autopilot = false;
  await f.viewDeploy(); await flush(); await flush();
  assert.match(f.root.querySelector('#dep-ap').innerHTML, /Want it to find and deploy more like this\? <button type="button" data-research-ap>Turn on autopilot<\/button>/);
  const none = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [], open_positions: []}) : response({})});
  none.S.me.user.autopilot = false;
  await none.viewDeploy(); await flush(); await flush();
  assert.equal(none.root.querySelector('#dep-ap').innerHTML, '');  // the empty board already speaks to autopilot
  assert.ok(!source.includes('the agent only proposes'));
  assert.match(source, /Off: it only suggests ideas and changes, and you approve each one\. Flip the switch to let it research and trade on paper by itself\./);
});

test('a passed strategy not yet on paper puts Deploy on paper up top as well, the same call as the panel', async () => {
  const pending = deferred();
  const f = strategyFrontend(detailStrategy(), (path, options) => {
    assert.equal(path, '/api/deployments');
    return options.method === 'POST' ? pending.promise : response({deployments: [], open_positions: []});
  });
  await f.viewStrategy(42); await flush();
  const quick = f.root.querySelector('#dep-paper-quick'), html = f.root.querySelector('main').innerHTML;
  assert.ok(quick); assert.ok(f.root.querySelector('#dep-paper'));
  assert.equal(quick.textContent, 'Deploy on paper'); assert.ok(quick.classList.contains('primary'));
  assert.ok(html.indexOf('id="dep-paper-quick"') < html.indexOf('id="figs"') || html.indexOf('id="dep-paper-quick"') < html.indexOf('class="paper-abstract"'));
  assert.ok(html.indexOf('id="dep-paper-quick"') < html.indexOf('id="dep-paper"'));
  assert.match(f.root.querySelector('#strat-quick').textContent, /nothing real is at risk/);
  quick.onclick();
  assert.deepEqual(JSON.parse(postRequests(f)[0].options.body), {strategy_id: 42, mode: 'paper'});
  pending.resolve(response({id: 9})); await flush();
  assert.deepEqual(f.navigations, ['/deploy']);
  // A refusal shows beside the button that was pressed.
  const bad = strategyFrontend(detailStrategy(), () => response({error: 'Synthetic paper refusal'}, 400));
  await bad.viewStrategy(42); await flush();
  bad.root.querySelector('#dep-paper-quick').onclick(); await flush(); await flush();
  assert.match(bad.root.querySelector('#depflash-quick').innerHTML, /Synthetic paper refusal/);
  // Already on paper, not validated, or no gatekeeper record behind its "passed": only the panel's own button.
  for (const detail of [detailStrategy({deployments: [{id: 3, mode: 'paper', status: 'running'}]}), detailStrategy({status: 'rejected'}), detailStrategy({experiment: null})]) {
    const g = strategyFrontend(detail, () => response({deployments: [], open_positions: []}));
    await g.viewStrategy(42); await flush();
    assert.equal(g.root.querySelector('#dep-paper-quick'), null); assert.ok(g.root.querySelector('#dep-paper'));
  }
});

test('Research folds model, depth and market behind Options on a phone, open on a wide screen, and says what will run', async () => {
  const markets = [{key: 'btc15m', label: 'Bitcoin 15 min', category: 'Crypto', has_data: true}];
  const research = (matchMedia) => frontend({matchMedia, fetchImpl: path => {
    if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}, {key: 'haiku', label: 'Haiku'}], default: 'opus'});
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/research/estimate') return response({yours: null, sessions: 0, typical: {}});
    if (path === '/api/runs') return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null});
    if (path.startsWith('/api/research/scoreboard')) return response({total: {runs: 0}});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  for (const [phone, open] of [[true, false], [false, true]]) {
    const f = research(() => ({matches: phone}));
    f.S.me.markets = markets;
    await f.viewResearch(); await flush(); await flush();
    const form = f.root.querySelector('#dispatch'), opts = form.querySelector('#ropts');
    assert.equal(opts.tag, 'details'); assert.equal('open' in opts.attributes, open);
    assert.equal(opts.querySelector('.dispatch-opts-t').textContent, 'Options');
    for (const sel of ['#rmodel', '#maxhyp', '#runforever', '.mktpick']) assert.ok(opts.querySelector(sel), sel);
    assert.equal(form.querySelector('#runforever').checked, true);  // run-forever stays the default
    assert.equal(opts.contains(form.querySelector('textarea[name=prompt]')), false);
    assert.equal(opts.contains(form.querySelector('button[type=submit]')), false);
    const sum = () => form.querySelector('#ropts-sum').textContent;
    const model = form.querySelector('#rmodel'); model.value = 'opus'; form.dispatchEvent({type: 'change'});  // the fake select has no default value
    assert.equal(sum(), 'Opus · runs until you stop it · agent’s choice of market');
    model.value = 'haiku';
    form.querySelector('#runforever').checked = false; form.querySelector('#maxhyp').value = '25';
    form.querySelectorAll('input[name=market]').forEach((r) => { r.checked = r.getAttribute('value') === 'btc15m'; });
    form.dispatchEvent({type: 'change'});
    const row = form.querySelector('.mktrow[data-key="btc15m"] .mktrow-name').textContent.trim();
    assert.equal(sum(), 'Haiku · 25 strategies · ' + row); assert.doesNotMatch(row, /choice/);
  }
});

test('a hypothesis in the log says its search-data result and verdict in plain words', async () => {
  const run = {id: 9, status: 'succeeded', prompt: 'Session 9', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', hypotheses_tried: 1, strategies_passed: 1};
  const events = [
    {id: 1, kind: 'hypothesis', message: 'Fade the spike', created_at: '2026-10-17T10:00:00Z', data: {in_sample: {pnl: 4.5, trades: 8}}},
    {id: 2, kind: 'verdict', message: 'PASSED - Fade the spike: cleared every gate', created_at: '2026-10-17T10:01:00Z', data: {status: 'passed', title: 'Fade the spike', strategy_id: 42}},
  ];
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run, events, strategies: []}) : response({})});
  await f.viewRun(9); await flush();
  const log = f.root.querySelectorAll('li').map((li) => li.innerHTML + (li.querySelector('[data-review]') || {innerHTML: ''}).innerHTML).join('');
  assert.doesNotMatch(log, /Gatekeeper/);
  assert.match(log, /class="hx-tag pass">Verdict/);
  assert.match(log, /On the history it searched: \+\$4\.50 · 8 trades<button type="button" class="info" data-glo="insample"/);
});

test('on a phone, sessions come before the form, except when they came to start one (?new=1)', async () => {
  const run = {id: 5, status: 'succeeded', prompt: 'Mine', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', hypotheses_tried: 2, strategies_passed: 1};
  for (const [search, first] of [['', true], ['?new=1', false]]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/models') return response({models: [], default: ''});
      if (path === '/api/research/context') return response({markets: []});
      if (path === '/api/research/estimate') return response({yours: null, sessions: 0, typical: {}});
      if (path === '/api/runs') return response({runs: [run], counts: {research_running: 0, research_queued: 0}, policy: null});
      if (path.startsWith('/api/research/scoreboard')) return response({total: {runs: 1}});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.location.pathname = '/research'; f.location.search = search;
    await f.viewResearch(); await flush(); await flush();
    assert.equal(f.root.querySelector('#main').classList.contains('runs-first'), first, search);
  }
});

test('a returning user reads what happened since the last visit at the top of the dashboard', async () => {
  const since = {at: '2026-10-25T08:00:00+00:00', first: false,
    books: {paper: {pnl: 2.42, trades: 3}, demo: {pnl: -1.1, trades: 1}, live: {pnl: 0, trades: 0}},
    passed: {n: 4, items: [{id: 9, title: '<b>Rain</b>'}, {id: 8, title: 'Fade'}, {id: 7, title: 'Tails'}]},
    autopilot: {deploy: 1, pause: 2, set_risk: 1}, runs: {succeeded: 2, failed: 1}};
  const deployments = [{id: 3, strategy_id: 3, title: 'Paused one', market: 'btc15m', mode: 'paper', status: 'paused',
    status_reason: 'Autopilot: lost $12.00', stake: 5, max_positions: 20, realized_pnl: 0, unrealized_pnl: null,
    closed_trades: 0, open_positions: 0, curve: [], created_at: '2026-10-25T08:00:00Z'}];
  const strip = async (extra) => {
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), deployments, ...extra});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    return f;
  };
  const f = await strip({since});
  const text = f.root.querySelector('#dash-since').innerHTML;
  assert.match(text, /Since your last visit/);
  // Each book on its own, never added together; a book with no trades and nothing deployed stays out.
  // A book's name and its signed amount are one unit that a phone never splits.
  assert.match(text, /<span class="nobr"><b>Demo<\/b> <span class="neg">−\$1\.10<\/span><\/span> on 1 trade<\/span>/);
  assert.match(text, /<span class="nobr"><b>Paper<\/b> <span class="pos">\+\$2\.42<\/span><\/span> on 3 trades<\/span>/);
  assert.doesNotMatch(text, /<b>Live<\/b>|\$1\.32/);
  assert.match(text, /4 strategies passed: <a href="\/strategies\/9">&lt;b&gt;Rain&lt;\/b&gt;<\/a>, <a href="\/strategies\/8">Fade<\/a>, <a href="\/strategies\/7">Tails<\/a>, <a href="\/strategies">1 more<\/a>/);
  assert.match(text, /3 research sessions started/);
  assert.match(text, /It put 1 on paper, paused 2, 1 other change\./);
  assert.match(text, /<a href="#dash-deps">Paused one<\/a> is paused<span class="since-sub">: lost \$12\.00<\/span>/);
  assert.match(text, /<a href="\/research">1 research session failed<\/a>/);
  const host = f.root.querySelector('#boardbody').innerHTML;
  assert.ok(host.indexOf('id="dash-since"') >= 0 && host.indexOf('id="dash-since"') < host.indexOf('id="dash-ap"'));
  // A quiet stretch says so plainly; no last visit known yet reads as the last 24 hours.
  const quiet = await strip({deployments: [], since: {at: '2026-10-25T08:00:00+00:00', first: true, books: {paper: {pnl: 0, trades: 0}},
    passed: {n: 0, items: []}, autopilot: {}, runs: {}}});
  const q = quiet.root.querySelector('#dash-since').innerHTML;
  assert.match(q, /Last 24 hours/); assert.doesNotMatch(q, /Since your last visit/);
  for (const said of ['No trades closed.', 'Nothing new passed.', 'On. It made no changes.', 'Nothing.']) assert.ok(q.includes(said), said);
  // An older server without the block: no strip.
  assert.equal((await strip({})).root.querySelector('#dash-since'), null);
});

test('the last visit lives in a cookie: one visit until 30 minutes pass, then since that visit', async () => {
  const paths = [];
  const f = frontend({fetchImpl: path => {
    paths.push(path);
    if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), deployments: []});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  const now = () => Math.floor(Date.now() / 1000);
  await f.viewDashboard(); await flush();
  assert.equal(paths.filter((p) => p.startsWith('/api/dashboard')).at(-1), '/api/dashboard');  // first visit: the server's last 24h
  assert.match(f.document.cookie, /^tau_visit=0\.\d+; path=\/; max-age=7776000; SameSite=Lax$/);
  await f.viewDashboard(); await flush();
  assert.equal(paths.filter((p) => p.startsWith('/api/dashboard')).at(-1), '/api/dashboard');  // a reload is the same visit
  const left = now() - 7200;
  f.document.cookie = `tau_visit=0.${left}`;
  await f.viewDashboard(); await flush();
  assert.equal(paths.filter((p) => p.startsWith('/api/dashboard')).at(-1), '/api/dashboard?since=' + left);
  assert.match(f.document.cookie, new RegExp('^tau_visit=' + left + '\\.\\d+;'));
  await f.viewDashboard(); await flush();  // reloaded a minute later: still since that visit
  assert.equal(paths.filter((p) => p.startsWith('/api/dashboard')).at(-1), '/api/dashboard?since=' + left);
});

const exRun = {id: 3, status: 'succeeded', prompt: "Todd's random walk", market: 'btc15m', direction: 'random_walk', example: true,
  created_at: '2026-10-17T10:00:00Z', hypotheses_tried: 2, strategies_passed: 1, spent_usd: 0};
const ownRun = {id: 8, status: 'succeeded', prompt: 'Mine', market: 'btc15m', direction: 'momentum', example: false,
  created_at: '2026-10-18T10:00:00Z', hypotheses_tried: 2, strategies_passed: 0, spent_usd: 0.4};
const exResearch = (runs, {estimate = {yours: null, sessions: 0, typical: {}}, matchMedia} = {}) => frontend({matchMedia, fetchImpl: path => {
  if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}], default: 'opus'});
  if (path === '/api/research/context') return response({markets: []});
  if (path === '/api/research/estimate') return response(estimate);
  if (path === '/api/runs') return response({runs, counts: {research_running: 0, research_queued: 0}, policy: null});
  if (path.startsWith('/api/research/scoreboard')) return response({total: {runs: runs.length}});
  if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
  throw new Error('Unexpected offline request: ' + path);
}});

test('a brand-new user sees "See an example session first" on the dashboard and near the top of Research', async () => {
  for (const [own, shown] of [[false, true], [true, false]]) {
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), deployments: [], since: {at: '2026-10-25T08:00:00+00:00', first: true,
        books: {}, passed: {n: 0, items: []}, autopilot: {}, runs: {}, own_sessions: own}});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    const empty = f.root.querySelector('#deps-empty').innerHTML;
    assert.equal(/<a class="btn primary ex-cta" href="\/example" data-example>See an example session first<\/a>/.test(empty), shown, String(own));
    // and up top, in the strip, where a phone sees it without scrolling
    assert.equal(/No sessions of your own yet\. <a href="\/example" data-example>See an example session first<\/a>/.test(f.root.querySelector('#dash-since').innerHTML), shown);
  }
  // Research: only the seeded example so far, so it leads with it (one tap, straight to the session).
  let f = exResearch([exRun]);
  await f.viewResearch(); await flush(); await flush();
  const top = f.root.querySelector('#rexample').innerHTML;
  assert.match(top, /<a class="btn primary ex-cta" href="\/research\/3" data-example>See an example session first<\/a>/);
  assert.match(top, /It cost you nothing/);
  const html = f.root.innerHTML;
  assert.ok(html.indexOf('id="rexample"') < html.indexOf('id="dispatch"'));
  // A session of their own: no nudge.
  f = exResearch([ownRun, exRun]);
  await f.viewResearch(); await flush(); await flush();
  assert.equal(f.root.querySelector('#rexample').innerHTML, '');
});

test('/example opens the finished example session in place, or Research when there is none', async () => {
  // Past 50 sessions the runs list (the newest 50) no longer holds the example, so /example looks it
  // up by itself, not from the list.
  const many = Array.from({length: 50}, (_, i) => ({...ownRun, id: 100 + i}));
  for (const [answer, to] of [[response({id: 3}), '/research/3'], [response({id: null}), '/research'],
                              [response({error: 'Not found'}, 404), '/research']]) {
    const seen = [];
    const f = frontend({fetchImpl: path => {
      seen.push(path);
      if (path === '/api/runs/example') return answer;
      if (path === '/api/runs') return response({runs: many, counts: {research_running: 0, research_queued: 0}, policy: null});
      return response({});
    }});
    await f.viewExample(); await flush();
    assert.equal(f.navigations.at(-1), to);
    assert.equal(seen[0], '/api/runs/example', seen.join(' '));  // the lookup alone, before it goes anywhere
  }
});

test('the demo opens the finished example; running it again says plainly that it uses credits', async () => {
  let f = exResearch([exRun], {estimate: {yours: null, sessions: 0, typical: {opus: 2.25}}});
  f.S.me.billing_enabled = true;
  await f.viewResearch(); await flush(); await flush();
  const form = f.root.querySelector('#dispatch'), open = form.querySelector('[data-ex-open]');
  assert.equal(open.tag, 'a'); assert.equal(open.getAttribute('href'), '/research/3'); assert.equal(open.hidden, false);
  assert.equal(postRequests(f).length, 0);
  const run = form.querySelector('[data-ex]'), ta = form.querySelector('textarea[name=prompt]');
  assert.match(run.textContent, /run it yourself/);
  assert.equal(form.querySelector('#ex-cost').hidden, true);
  run.onclick();
  assert.match(ta.value, /random walk/);
  const note = form.querySelector('#ex-cost');
  assert.equal(note.hidden, false);
  assert.match(note.textContent, /^This starts a new session that uses your credits; the example already shows how this idea ends\. Each round of ideas usually costs about \$2\.25/);
  assert.equal(postRequests(f).length, 0);  // filling the box never starts anything
  // No example on this account: the link hides and "run it yourself" stays.
  f = exResearch([ownRun]);
  await f.viewResearch(); await flush(); await flush();
  assert.equal(f.root.querySelector('[data-ex-open]').hidden, true);
  assert.ok(f.root.querySelector('[data-ex]'));
});

test('on a phone the strategy page folds its secondary sections, never money figures or verdicts', async () => {
  for (const [phone, open] of [[true, false], [false, true]]) {
    const f = frontend({matchMedia: () => ({matches: phone}), fetchImpl: path => {
      if (path === '/api/strategies/42') return response(detailStrategy());
      if (path === '/api/strategies/42/dev-curve') return response({dev_curve: [[200, 1], [300, 2]]});
      return response({deployments: [], open_positions: []});
    }});
    await f.viewStrategy(42); await flush();
    const folds = f.root.querySelectorAll('details.fold');
    assert.deepEqual(folds.map((d) => d.querySelector('summary').textContent), ['Methodology', 'Most recent unseen trades', 'Demo &amp; live', 'What if…', 'Share', 'Remove']);
    for (const d of folds) assert.equal('open' in d.attributes, open);
    for (const sel of ['#dep-demo', '#dep-live', '#live-confirm', '#whatif', '#share-form', '#del-strat']) assert.ok(f.root.querySelector(sel).closest('details.fold'), sel);
    for (const sel of ['#figs', '#dep-paper', '#gates', '#depflash']) assert.equal(f.root.querySelector(sel).closest('details.fold'), null, sel);
    for (const label of ['Results', 'Verdict', 'Abstract']) assert.ok(!folds.some((d) => d.querySelector('summary').textContent === label), label);
    assert.match(f.root.querySelector('#figs').innerHTML, /Unseen-data P&L/);
  }
});

const PEM = '-----BEGIN RSA PRIVATE KEY-----\nMIIEsecretsecretsecret\n-----END RSA PRIVATE KEY-----';
const KID = 'a952bcbe-ec3b-4b5b-b8f9-11dae589608c';
const keyFunds = (state) => frontend({fetchImpl: (path, options = {}) => {
  if (path === '/api/funds') { state.reads++; return response({...funds(), kalshi: state.live, kalshi_dev: state.dev}); }
  if (path === '/api/kalshi-key') { state.live = {connected: true, balance: state.liveBalance, key_id: 'a952…608c', funding_url: 'https://kalshi.com/account/funding'}; return response({ok: true, balance: state.liveBalance}); }
  if (path === '/api/kalshi-dev-key') { state.dev = {connected: true, key_id: 'a952…608c', balance: state.devBalance}; return response({ok: true}); }
  throw new Error('Unexpected offline request: ' + path);
}});
const submitKey = async (f, id, kid, pem) => {
  const form = f.root.querySelector('#' + id); form.key_id = {value: kid}; form.private_key = {value: pem};
  await form.onsubmit({preventDefault() {}}); await flush();
};

test('Funds says where each Kalshi key comes from, what to paste, and which key goes where', async () => {
  const f = keyFunds({reads: 0, live: {connected: false}, dev: {connected: false}});
  await f.viewFunds();
  const live = f.root.querySelector('#kalshi').closest('section').innerHTML, main = f.root.querySelector('main').innerHTML;
  assert.match(live, /<a href="https:\/\/kalshi\.com\/account\/profile" target="_blank" rel="noopener">your profile<\/a>, find API Keys and click Create New API Key/);
  assert.match(live, /<b>Key ID<\/b> \(like <span class="nobr">a952bcbe-ec3b-…<\/span>\) and downloads a <b>private key<\/b> file \(\.key\), once/);
  assert.match(live, /A key made on demo\.kalshi\.co won’t work here: add it under Demo key\./);
  assert.match(main, /<a href="https:\/\/demo\.kalshi\.co\/" target="_blank" rel="noopener">Sign up or sign in at demo\.kalshi\.co<\/a> \(free\)/);
  assert.match(main, /<a href="https:\/\/demo\.kalshi\.co\/account\/profile" target="_blank" rel="noopener">your demo profile<\/a>/);
  assert.match(main, /A real-money key from kalshi\.com won’t work here\./);
  assert.equal((main.match(/href="https:\/\/docs\.kalshi\.com\/getting_started\/api_keys"/g) || []).length, 2);
  assert.equal((main.match(/name="key_id"[^>]*placeholder="like a952bcbe-ec3b-4b5b-…"/g) || []).length, 2);
  assert.doesNotMatch(main, /<details class="connection-help">/);  // the steps are never folded shut for a new user
});

test('a mixed-up Kalshi key gets a plain reason before anything is sent, and never echoes the key', async () => {
  const f = keyFunds({reads: 0, live: {connected: false}, dev: {connected: false}});
  await f.viewFunds();
  const cases = [
    [PEM, KID, /That’s the key file’s text; it goes in the Private key box/],
    [KID, KID, /That looks like the Key ID; it goes in the Key ID box/],
    [KID, '-----BEGIN PUBLIC KEY-----\nMIIBsecret\n-----END PUBLIC KEY-----', /That’s a public key\. Tau needs the private key/],
    [KID, 'hello secret', /That isn’t a private key\. Paste the whole \.key file/],
    [KID, PEM.slice(0, 50), /That private key is cut off/],
    ['', PEM, /Paste the Key ID: the short code shown next to the key on the API keys page on demo\.kalshi\.co\./],
  ];
  for (const [kid, pem, said] of cases) {
    await submitKey(f, 'kalshi-dev', kid, pem);
    const out = f.root.querySelector('#kdflash').innerHTML;
    assert.match(out, said); assert.doesNotMatch(out, /secret|MIIE/);
  }
  await submitKey(f, 'kalshi', '', PEM);
  assert.match(f.root.querySelector('#kflash').innerHTML, /on the API keys page on kalshi\.com\./);
  assert.equal(postRequests(f).length, 0);
});

test('connecting a Kalshi key confirms it with the balance: "Connected ✓ (balance $X)"', async () => {
  const state = {reads: 0, live: {connected: false}, dev: {connected: false}, liveBalance: 1234.5, devBalance: 25000};
  const f = keyFunds(state);
  await f.viewFunds();
  await submitKey(f, 'kalshi', KID, PEM);
  assert.match(f.root.querySelector('#kflash').innerHTML, /Connected ✓ \(balance \$1,234\.50\)\. Kalshi confirmed the key\./);
  assert.match(f.root.querySelector('main').innerHTML, /<p class="key-ok"><b>Connected ✓<\/b> \(balance \$1,234\.50\)<\/p>/);
  await submitKey(f, 'kalshi-dev', KID, PEM);
  assert.match(f.root.querySelector('#kdflash').innerHTML, /Connected ✓ \(balance \$25,000\.00\)\. Kalshi’s demo exchange confirmed the key\./);
  assert.match(f.root.querySelector('main').innerHTML, /<b>Connected ✓<\/b> \(balance \$25,000\.00\) <span class="hint">in your Kalshi demo account<\/span>/);
  const sent = postRequests(f).map(({path}) => path);
  assert.deepEqual(sent, ['/api/kalshi-key', '/api/kalshi-dev-key']);
  assert.doesNotMatch(f.root.querySelector('main').innerHTML, /MIIE|BEGIN RSA PRIVATE KEY-----\n/);  // the key is never shown back
  // A balance Kalshi couldn't read just now still says it connected, without inventing a figure.
  const g = keyFunds({reads: 0, live: {connected: true, balance: null, key_id: 'a952…608c'}, dev: {connected: true, key_id: 'a952…608c', balance: null}});
  await g.viewFunds();
  assert.equal((g.root.querySelector('main').innerHTML.match(/<b>Connected ✓<\/b> \(couldn’t read the balance just now\)/g) || []).length, 2);
});

const cardedBilling = (o = {}) => ({configured: true, publishable_key: 'synthetic-only', balance: 7.4213, spent: 47.5787, spent_7d: 9.8, runway_days: 5.3,
  free_bonus: 20, topup_fee_pct: 5.5, autoreload_threshold: 8, autoreload_amount: 25, min_reload_amount: 20, min_reload_threshold: 5,
  min_topup: 5, max_topup: 1000, default_pm: 'pm_1', auto_reload: true,
  cards: [{id: 'pm_2', brand: 'mastercard', last4: '4444', exp_month: 11, exp_year: 2027}, {id: 'pm_1', brand: 'visa', last4: '4242', exp_month: 4, exp_year: 2029}],
  ledger: [
    {kind: 'usage', amount: -0.2104, memo: 'Agent usage · claude-opus-4-6', created_at: '2026-10-25T17:00:00Z'},
    {kind: 'autoreload', amount: 25, memo: 'Auto-reload $25', created_at: '2026-10-25T16:00:00Z'},
    {kind: 'usage', amount: -0.91, memo: 'Research run (seed)', created_at: '2026-10-25T15:00:00Z'},
    {kind: 'topup', amount: 10, memo: 'Added $10 credits', created_at: '2026-10-25T14:00:00Z'},
    {kind: 'bonus', amount: 20, memo: 'Welcome credits', created_at: '2026-10-24T14:00:00Z'},
  ], ...o});
const STRIPE_STUB = () => ({confirmSetup: async () => ({error: {message: 'stub'}}), elements: () => ({create: () => ({mount() {}})})});
const billingPage = (data, posts = []) => frontend({stripe: STRIPE_STUB, fetchImpl: (path, options = {}) => {
  if (path === '/api/billing') return response(data);
  if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
  if (path === '/api/billing/auto-reload') { posts.push(JSON.parse(options.body)); return response({ok: true}); }
  throw new Error('Unexpected offline request: ' + path);
}});

test('Billing says what auto-reload does and when it fires, in the server\'s own figures', async () => {
  const posts = [], f = billingPage(cardedBilling(), posts);
  await f.viewBilling(); await flush();
  const when = f.root.querySelector('#autorel-when');
  assert.equal(when.innerHTML, '<b>On.</b> When a research or chat charge takes your balance to $8.00 or less, we charge your VISA •••• 4242 for $25.00 of credits plus the 5.5% purchase fee.');
  const box = f.root.querySelector('#autoreload'); box.checked = false;
  await box.onchange(); await flush();
  assert.match(when.innerHTML, /^<b>Off\.<\/b> When your credits run low, new research sessions won’t start until you add more\.$/);
  assert.deepEqual(posts, [{on: false, amount: 25, threshold: 8}]);  // what is saved is unchanged
  assert.equal(f.root.querySelector('#autorel-sum').textContent, 'Reload $25 at $8');
});

test('Billing ledger says why each line was charged and where the receipt is; amounts stay the server\'s', async () => {
  const f = billingPage(cardedBilling());
  await f.viewBilling(); await flush();
  const main = f.root.querySelector('main').innerHTML;
  assert.match(main, /<a class="btn sm" href="\/api\/billing\/receipt" download>Download receipt \(CSV\)<\/a>/);
  assert.match(main, /<p class="hint ledger-key">Newest first\. Research and chat bill one line per model call, named by its model\. The receipt has every line, with exact amounts\.<\/p>/);
  const rows = f.root.querySelectorAll('.t-ledger tbody tr').map((r) => r.innerHTML);
  assert.equal(rows.length, 5);
  assert.match(rows[0], /Agent usage<div class="sub-fig">claude-opus-4-6<\/div>[\s\S]*−\$0\.21/);
  assert.doesNotMatch(rows[0], /Agent usage · /);  // the memo's prefix isn't said twice
  assert.match(rows[1], /Auto-reload<div class="sub-fig">Card charged for these credits plus the 5\.5% purchase fee<\/div>[\s\S]*\+\$25\.00/);
  assert.match(rows[2], /Agent usage<div class="sub-fig">Research run \(seed\)<\/div>[\s\S]*−\$0\.91/);
  assert.match(rows[3], /Added credits<div class="sub-fig">Card charged for these credits plus the 5\.5% purchase fee<\/div>[\s\S]*\+\$10\.00/);
  assert.match(rows[4], /Welcome credits<\/td>[\s\S]*\+\$20\.00/);  // free credits: no card line
  assert.doesNotMatch(main, /list price/);
  // The figures up top are unchanged: what the server sent, formatted as before.
  assert.match(f.root.querySelector('#bfigs').innerHTML, /\$7\.42/);
  assert.match(f.root.querySelector('#bfigs').innerHTML, /\$47\.58/);
});

test('Billing puts Add credits right under the balance in one column, and says where a session\'s cost is shown', async () => {
  const f = billingPage(cardedBilling());
  await f.viewBilling(); await flush();
  const detail = f.root.querySelector('.bill-detail');
  assert.ok(detail && detail.querySelector('aside #topup-btn'));
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  assert.match(css, /@media \(max-width: 1080px\) \{ \.bill-detail > aside \{ order: -1; \} \}/);
  assert.match(f.root.innerHTML, /The <a href="\/research">research form<\/a> shows what a session usually costs before you start\./);
});

test('the Remove button stays disabled, with the server\'s reason, while a stopped deployment still holds positions', async () => {
  const reason = "This strategy still holds 2 open positions (paper: 1, live: 1). They'll close at settlement; delete it after that.";
  for (const block of [reason, null]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/strategies/42') return response(detailStrategy({delete_block: block, deployments: [{id: 9, mode: 'paper', status: 'stopped', market: 'btc15m'}]}));
      if (path === '/api/strategies/42/dev-curve') return response({dev_curve: []});
      return response({deployments: [], open_positions: []});
    }});
    await f.viewStrategy(42); await flush();
    const del = f.root.querySelector('#del-strat'), why = f.root.querySelector('#del-why');
    if (block) {
      assert.equal(del.attributes['aria-disabled'], 'true'); assert.equal(del.attributes['aria-describedby'], 'del-why');
      assert.match(why.innerHTML, /still holds 2 open positions \(paper: 1, live: 1\)\. They.+ll close at settlement; delete it after that\./);
      await del.onclick(); await flush();
      assert.match(f.root.querySelector('#delflash').innerHTML, /still holds 2 open positions \(paper: 1, live: 1\)/);
    } else {
      assert.equal('aria-disabled' in del.attributes, false);
      assert.match(why.innerHTML, /This can.t be undone\./);
    }
    assert.equal(postRequests(f).length, 0);  // a click arms a confirm or explains; it never deletes
  }
});

test('the admin page counts open positions whose strategy was deleted', async () => {
  for (const [orphaned, text] of [
    [undefined, 'None: every open position belongs to a strategy that still exists.'],
    [{total: 0, users: 0, by_mode: {}}, 'None: every open position belongs to a strategy that still exists.'],
    [{total: 3, users: 2, by_mode: {paper: {positions: 1, users: 1, cost: 4, oldest_close: null}, demo: {positions: 2, users: 1, cost: 3.5, oldest_close: null}}},
      /^3 open positions \(paper: 1, demo: 2\) across 2 users belong to deleted strategies\. The engine no longer settles or flattens them\. Paper: \$4\.00 at cost, .+ Demo: \$3\.50 at cost, /],
  ]) {
    const f = frontend({fetchImpl: path => {
      assert.equal(path, '/api/admin');
      return response({users: [], waitlist: [], ...(orphaned ? {orphaned_open: orphaned} : {})});
    }});
    f.S.me.is_admin = true; f.location.pathname = '/admin';
    await f.render(); await flush(); await flush();
    const line = f.root.querySelector('#o-state').textContent;
    if (typeof text === 'string') assert.equal(line, text); else assert.match(line, text);
  }
});

test('the since strip says what demo needs in a sentence, and a book with nothing closed keeps its name', async () => {
  const since = {at: '2026-10-25T08:00:00+00:00', first: false, books: {demo: {pnl: 0, trades: 0}},
    passed: {n: 0, items: []}, autopilot: {}, runs: {}};
  const deployments = [{id: 4, strategy_id: 4, title: 'On demo', market: 'btc15m', mode: 'demo', status: 'running',
    stake: 5, max_positions: 2, realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 0, curve: [], created_at: '2026-10-25T08:00:00Z'}];
  const strip = async (health) => {
    const base = emptyDashboard();
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...base, deployments, since, demo: {...base.demo, health}});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    return f.root.querySelector('#dash-since').innerHTML;
  };
  const key = await strip({code: 'demo_key', need: 'your Kalshi demo key', line: "Demo isn't trading: your Kalshi demo key isn't connected.",
    action: {label: 'Add demo key', href: '/funds'}});
  assert.match(key, /Demo can’t trade: it needs your Kalshi demo key\. <a href="\/funds">Add demo key<\/a>/);
  assert.doesNotMatch(key, /Demo can’t trade: your/);
  assert.match(key, /<span class="since-book" data-book="demo"><b>Demo<\/b> no trades closed<\/span>/);
  // No `need` from an older server: its whole line, not an empty "Demo can't trade: ."
  const old = await strip({line: "Demo isn't trading: your Kalshi demo key isn't connected."});
  assert.match(old, /Demo isn.+t trading: your Kalshi demo key isn.+t connected\./); assert.doesNotMatch(old, /trade: \./);
});

test('past its paper-trade target the autopilot card says how many and how many were needed, never "67 of 30"', async () => {
  for (const [trades, said] of [[4, '4 of 30 paper trades'], [67, '67 paper trades (30 needed)'], [30, '30 paper trades (30 needed)']]) {
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response(emptyDashboard());
      if (path === '/api/autopilot/status') return response({autopilot: true, mode: 'paper', story: ['Researching.'],
        research: {tested_7d: 3, passed_7d: 0, active: []}, live_running: 0, demo_running: 0, paper_running: 1,
        paper_progress: {strategy_id: 3, trades, trades_needed: 30, net_pnl: 1}});
      if (path === '/api/settings') return response({ok: true});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    await f.root.querySelector('#dash-ap').querySelector('[data-apcard="on"]').onclick(); await flush(); await flush();
    const html = f.root.querySelector('#dash-ap').innerHTML;
    assert.ok(html.includes(said), said); assert.doesNotMatch(html, /\b67 of 30\b/);
  }
});

test('a backtest trade\'s exit reads in words, and a sub-cent charge shows its amount', async () => {
  const opened = '2026-10-17T10:00Z';
  const recent = ['take_profit', 'stop_loss', 'edge_gone', 'settled', 'brand_new_reason'].map((reason, i) =>
    ({ticker: 'KXBTC15M-T' + i, side: 'yes', qty: 2, entry: 0.4, exit: 0.6, pnl: 0.4, reason, opened}));
  const f = strategyFrontend(detailStrategy({recent_trades: recent}), () => response({deployments: [], open_positions: []}));
  await f.viewStrategy(42); await flush();
  const html = f.root.querySelector('main').innerHTML;
  for (const word of ['take-profit', 'stop-loss', 'edge gone', 'settled', 'brand new reason']) assert.ok(html.includes(`<small class="hint">${word}</small>`), word);
  assert.doesNotMatch(html, /take_profit|stop_loss|edge_gone|brand_new_reason/);
  const b = billingPage(cardedBilling({ledger: [{kind: 'usage', amount: -0.0042, memo: 'Agent usage · sonnet', created_at: '2026-10-25T17:00:00Z'},
    {kind: 'usage', amount: -0.21, memo: 'Agent usage · sonnet', created_at: '2026-10-25T16:00:00Z'}]}));
  await b.viewBilling(); await flush();
  const rows = b.root.querySelector('.t-ledger').innerHTML;
  assert.match(rows, />−\$0\.004</); assert.match(rows, />−\$0\.21</); assert.doesNotMatch(rows, /−\$0\.00</);
});

test('the example Kalshi Key ID never breaks across lines', async () => {
  assert.equal((source.match(/\(like <span class="nobr">a952bcbe-ec3b-…<\/span>\)/g) || []).length, 1);
  assert.doesNotMatch(source, /Key ID<\/b> \(like a952bcbe/);
});

test('the equity chart\'s unseen-data label fits its window instead of running off the chart', () => {
  const curve = [[0, 0], [50, 1], [100, 2]];
  const iso = (t) => new Date(t * 1000).toISOString();
  const wide = frontend().equityChart(curve, iso(30), null, {width: 760});
  assert.match(wide, /<text x="[\d.]+" y="[\d.]+" style="fill:var\(--ink-2\)">UNSEEN BY THE AGENT →<\/text>/);
  // A cut near the right edge (a phone): the short label, pinned to the chart's right edge.
  const narrow = frontend().equityChart(curve, iso(97), null, {width: 340});
  assert.doesNotMatch(narrow, /UNSEEN BY THE AGENT/);
  assert.match(narrow, /text-anchor="end" style="fill:var\(--ink-2\)">UNSEEN →<\/text>/);
});

test('the open-positions why line and a long strategy name wrap, so Deploy never scrolls sideways', () => {
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  assert.match(css, /\.pos-why \{[^}]*white-space: normal;/);
  assert.match(css, /#openpos td\.name \{ white-space: normal;/);
  assert.match(css, /\.fold > summary\.fold-h \{[^}]*gap: 6px;/);
  assert.match(css, /\.dispatch-go \.ex-run \{ min-height: 40px; \}/);
});

test('Deploy prices a deployment\'s open positions in its row, as the dashboard does, one deployment at a time', async () => {
  const dep = (id, mode) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode, status: 'running', status_reason: null,
    realized_pnl: 1, closed_trades: 3, open_positions: 2, unrealized_pnl: null, created_at: '2026-10-25T08:00:00Z', curve: [],
    stake: 5, max_positions: 4, backtest: {out_of_sample: null}});
  const pos = (id, deployment_id, mode, unrealized) => ({id, deployment_id, mode, title: 'Dep ' + deployment_id, ticker: 'KXBTC15M-T' + id,
    side: 'yes', qty: 2, entry_price: 0.4, entry_fee: 0.01, market_close_time: '2026-10-26T12:00:00Z', unrealized});
  const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [dep(1, 'paper'), dep(2, 'live'), dep(3, 'paper')],
    open_positions: [pos(10, 1, 'paper', 1.25), pos(11, 1, 'paper', -0.5), pos(12, 2, 'live', 2), pos(13, 3, 'paper', null)]}) : response({})});
  await f.viewDeploy(); await flush(); await flush();
  const html = f.root.querySelector('#deps').innerHTML;
  assert.ok(html.includes('+$0.75'), 'paper deployment 1: its two marks');
  assert.ok(html.includes('+$2.00'), 'live deployment 2: its own mark only');
  assert.doesNotMatch(html, /\+\$2\.75/);  // never added across deployments or books
});
