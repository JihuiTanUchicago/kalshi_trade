// Reused frozen86 workspace regressions, targeted at Meridian; current Funds behavior is reconciled.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import vm from 'node:vm';
import {perpsFrontendCases} from './kalshi_perps_frontend_cases.mjs';

const require = createRequire(import.meta.url);
const brokerConnections = require('../app/static/broker-connections.js');
const source = readFileSync(new URL('../app/static/app.meridian.js', import.meta.url), 'utf8');
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
  get className() { return [...this.classes].join(' '); }
  set className(value) { this.classes = new Set(value.split(/\s+/)); }
  get id() { return this.attributes.id; }
  set id(value) { this.attributes.id = value; }
  get parentElement() { return this.parent || null; }
  get open() { return 'open' in this.attributes; }
  set open(value) { if (value) this.attributes.open = ''; else delete this.attributes.open; }
  get innerHTML() { return this.html || ''; }
  set innerHTML(value) {
    if (this.ownerDocument?.activeElement !== this && this.contains(this.ownerDocument?.activeElement)) {
      this.ownerDocument.activeElement = this.ownerDocument.body;
    }
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
    if (selector.endsWith(':focus') && this.ownerDocument?.activeElement !== this) return false;
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
        while (parent && index >= 0) {
          if (parts[index] === '>') {
            index--;
            if (index < 0 || !parent.matches(parts[index])) break;
            index--;
          } else if (parent.matches(parts[index])) index--;
          parent = parent.parent;
        }
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
  appendChild(child) {
    if (child.parent) child.parent.children = child.parent.children.filter(element => element !== child);
    this.children.push(child); child.parent = this; child.removed = false;
    const adopt = element => { element.ownerDocument = this.ownerDocument; element.children.forEach(adopt); };
    adopt(child);
  }
  insertAdjacentHTML(_position, html) { this.html = (this.html || '') + html; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  focus(options) { this.focusOptions = options; if (this.ownerDocument) this.ownerDocument.activeElement = this; }
  remove() { this.removed = true; }
}

function frontend({fetchImpl, brokerMount, stripeLoader, search = '', matchMedia = () => ({matches: false}), storage = new Map(), theme = 'meridian', build} = {}) {
  const root = new Element('div', {id: 'app'}), body = new Element('body');
  const document = {body, activeElement: body, hidden: false,
    getElementById: id => body.querySelector('#' + id), addEventListener() {}, removeEventListener() {},
    createElement: tag => { const element = new Element(tag); element.ownerDocument = document; return element; }};
  body.ownerDocument = document; body.appendChild(root);
  const intervals = new Map(), timeouts = new Map(), windowListeners = new Map(), requests = [], navigations = [], reloads = [];
  let nextId = 0;
  const location = {pathname: '/strategies/42', search, origin: 'http://offline.invalid', reload: () => reloads.push(true)};
  const navigate = (_state, _title, path) => { navigations.push(path); location.pathname = path; };
  const context = vm.createContext({
    Intl, URL, URLSearchParams, AbortController,
    document, testStripeLoader: stripeLoader,
    window: {__TAU_UI__: theme, __BUILD__: build, addEventListener(name, callback) {
      const listeners = windowListeners.get(name) || []; listeners.push(callback); windowListeners.set(name, listeners);
    }, scrollTo() {}, matchMedia,
      ...(brokerMount ? {TauBrokerConnections: {mount: brokerMount}} : {})},
    addEventListener() {}, location, history: {pushState: navigate, replaceState: navigate},
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value))},
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
  vm.runInContext(source.replace(boot, 'if (globalThis.testStripeLoader) loadStripe = globalThis.testStripeLoader; globalThis.frontend = {S, api, render, viewExample, viewSettings, viewBilling, viewSystem, viewAdmin, routes, equityChart, runControls, runFeed, clearTimers, runRow, feedMd, viewStrategy, viewStrategies, strategySlip, tabEdges, viewRun, viewResearch, viewFunds, viewDashboard, viewDeploy, viewCommunity, viewExplore, postSnapshot, replaceDeploymentContent, marketPicker, wireMarketPicker, hotOpen, renderHotRail, trackRecordPanel, paintDashAp, mountTrackRecord};'), context);
  const api = context.frontend;
  api.S.me = {user: {id: 7, name: 'Offline fixture'}, markets: [], directions: [], live_trading_available: true, kalshi_connected: true, kalshi_dev_connected: true};
  // Cached global widgets keep these page checks focused. All requests still use
  // the offline transport above, including notifications and financial controls.
  api.S.hot = {markets: []}; api.S.hotAt = Date.now();
  api.S.ap = {mode: 'off'}; api.S.apAt = Date.now();
  // Moves the page's clock (Date.now) forward, for checks on how old a figure is.
  const shiftClock = ms => vm.runInContext(`{ const now = Date.now; Date.now = () => now() + ${Number(ms)}; }`, context);
  return {...api, root, document, location, intervals, timeouts, windowListeners, requests, navigations, reloads, storage, shiftClock};
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
perpsFrontendCases({name: 'Meridian', frontend, detailStrategy, strategyFrontend, postRequests});
const funds = () => ({kalshi: {connected: false}, kalshi_dev: {connected: false},
  demo: {capital: 1000, equity: 1001, realized: 1}, paper: {cash: 1000, ledger: [
    {created_at: '2026-10-17T10:00:00Z', memo: '<script>ledger</script>', amount: 10},
  ]}});

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
  for (const label of ['aria-label="Strategy hypothesis"', 'Mechanism &amp; hypothesis', 'Methodology', 'Results', 'Verdict']) assert.ok(output.includes(label));
  assert.match(output, /class="sheet-doc paper"/);
  assert.match(output, /&lt;b&gt;Counterparty&lt;\/b&gt;/);
  assert.match(output, /<b>Saved<\/b> &lt;img/);
  assert.doesNotMatch(output, /<unsafe>|<img|<script>|\[object Object\]/);
  assert.match(output, /id="dep-live"/); assert.match(output, /Type <b>LIVE<\/b>/);
  assert.ok(f.root.querySelector('article.paper #figs'));
  const environments = f.root.querySelector('.deployment-environments'), management = f.root.querySelector('.strategy-management');
  assert.equal(environments.tag, 'details'); assert.equal(environments.open, false);
  assert.equal(environments.contains(f.root.querySelector('#dep-paper')), false);
  for (const selector of ['#dep-demo', '#dep-live', '#live-confirm']) assert.equal(environments.contains(f.root.querySelector(selector)), true);
  assert.equal(management.tag, 'details'); assert.equal(management.open, false);
  assert.equal(management.contains(f.root.querySelector('#del-strat')), true); assert.equal(management.contains(f.root.querySelector('#share-form')), true);
  assert.equal(typeof f.root.querySelector('#del-strat').onclick, 'function'); assert.equal(typeof f.root.querySelector('#share-form').onsubmit, 'function');
  const chart = f.root.querySelector('#equity-wrap').innerHTML;
  assert.match(chart, /Kalshi dev \(real\)/); assert.doesNotMatch(chart, /NaN|undefined/);
  assert.equal(f.root.querySelector('#equity-wrap svg.chart').getAttribute('role'), 'img');
  assert.equal(f.root.querySelector('#equity-wrap .chart-sample'), null);
});

test('populated validation and holdout phase curves render without blocking strategy deployment controls', async () => {
  const experiment = {classification: 'forward_validated',
    validation: {equity_curve: [[100, 0], [200, -2], [300, 4]], n_trades: 20, mean_net_return: .02},
    holdout: {equity_curve: [[400, 0], [500, 3]], n_trades: 8, mean_net_return: .01}};
  const before = JSON.stringify(experiment), f = strategyFrontend(detailStrategy({experiment}));
  await f.viewStrategy(42); await flush();
  const phaseChart = f.root.querySelector('.rp-figs .rp-fig svg.chart');
  assert.ok(phaseChart); assert.match(phaseChart.getAttribute('aria-label'), /research phase: Validation, Holdout/);
  assert.equal(phaseChart.querySelectorAll('polyline').length, 2); assert.doesNotMatch(phaseChart.innerHTML, /NaN|undefined/);
  assert.ok(f.root.querySelector('#dep-paper')); assert.ok(f.root.querySelector('#dep-live'));
  assert.ok(f.root.querySelector('#live-confirm input[name="confirm"]'));
  assert.equal(JSON.stringify(experiment), before); assert.equal(postRequests(f).length, 0);
});

test('strategy evidence identifies run-wide trial counts and places missing validation before backtest figures', async () => {
  for (const [count, expected] of [[17, '17'], [0, '0'], [null, '—']]) {
    const detail = detailStrategy({hypotheses_tried: count, experiment: null});
    const before = JSON.stringify(detail), f = strategyFrontend(detail);
    await f.viewStrategy(42); await flush();
    const paper = f.root.querySelector('article.paper'), output = paper.innerHTML;
    const trials = paper.querySelectorAll('#figs .m').find(el => el.querySelector('dt').textContent === 'Ideas tested');
    assert.equal(trials.querySelector('.fig').textContent, expected);
    assert.equal(paper.querySelectorAll('.rp-verdict').length, 1);
    assert.match(paper.querySelector('.legacy-verdict').textContent, /Not validated \(record missing\)/);
    assert.ok(output.indexOf('class="legacy-verdict"') < output.indexOf('id="figs"'));
    assert.match(output, /Backtest results/); assert.doesNotMatch(output, /<h4 class="paper-h">Backtest<\/h4>/);
    const saved = paper.querySelector('.saved-result');
    assert.equal(saved.tag, 'details'); assert.equal(saved.open, false);
    assert.equal(saved.textContent.includes('one passes by luck'), count != null);
    assert.ok(f.root.querySelector('#dep-paper')); assert.ok(f.root.querySelector('#live-confirm input'));
    assert.equal(detail.status, 'passed'); assert.equal(JSON.stringify(detail), before);
    assert.equal(postRequests(f).length, 0);

    const run = researchRun(9, 'succeeded');
    const r = frontend({fetchImpl: path => {
      assert.equal(path, '/api/runs/9?after=0'); return response({run, events: [], strategies: [detail]});
    }});
    await r.viewRun(9);
    assert.equal(r.root.querySelector('td[data-lab="Ideas tested"]').textContent, expected);
    assert.match(r.root.querySelector('thead').textContent, /Ideas tested/);
    assert.doesNotMatch(r.root.querySelector('tbody').textContent, /1 of /);
    assert.equal(postRequests(r).length, 0);
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
  assert.match(whatif.innerHTML, /<h3>Sensitivity<\/h3>/);
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

test('paper chart rounds display bounds with headroom without changing signed observations or backtest scales', () => {
  const f = frontend();
  for (const values of [[3.2, .8, 24.8], [-3.2, -.8, -24.8], [-3.2, 0, 24.8], [0, 0, 0], [.01, .02, .03]]) {
    const curve = Object.freeze(values.map((v, i) => Object.freeze([100 + i * 100, v])));
    const before = JSON.stringify(curve), plain = f.equityChart(curve);
    f.root.innerHTML = f.equityChart(curve, null, null, {paper: true, height: 160});
    const chart = f.root.querySelector('svg.chart');
    const points = chart.querySelector('polyline').getAttribute('points').split(' ').map(p => p.split(',').map(Number));
    const zero = Number(chart.querySelector('line').getAttribute('y1'));
    points.forEach(([, y], index) => {
      assert.ok(Number.isFinite(y) && y > 16 && y < 134, 'observations have space above and below the display bounds');
      if (values[index] === 0) assert.ok(Math.abs(zero - y) < .06, 'zero stays on its reference line after SVG rounding');
      else assert.equal(Math.sign(zero - y), Math.sign(values[index]));
    });
    assert.equal(chart.querySelectorAll('.chart-sample').length, values.length);
    chart.querySelectorAll('.chart-sample').forEach((sample, index) => assert.ok(sample.getAttribute('aria-label').includes(
      values[index] < 0 ? '−$' + Math.abs(values[index]).toFixed(2) : values[index] > 0 ? '+$' + values[index].toFixed(2) : '$0.00')));
    assert.equal(JSON.stringify(curve), before); assert.equal(f.equityChart(curve), plain);
    assert.doesNotMatch(chart.innerHTML, /NaN|undefined/);
  }
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
  f.root.querySelector('.deployment-environments').open = true;
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
    f.root.querySelector('.deployment-environments').open = true;
    assert.equal(form.hidden, true); f.root.querySelector('#dep-live').onclick(); assert.equal(form.hidden, false);
    form.confirm = {value: typed}; form.onsubmit({preventDefault() {}}); await flush();
    assert.equal(postRequests(f).length, 1); assert.deepEqual(f.navigations, []);
    assert.match(f.root.querySelector('#depflash').innerHTML, /Synthetic server confirmation refusal/);
  }
});

const evidenceHtml = ids => ids.map(id => `<details class="dep-evidence" data-deployment="${id}"><summary>Backtest &amp; deployment</summary><div>Evidence ${id}</div></details>`).join('');
const evidenceFor = (host, id) => host.querySelector(`.dep-evidence[data-deployment="${id}"]`);
const positionFor = (host, key) => host.querySelector(`.position-details[data-position="${key}"]`);

test('deployment refresh preserves each disclosure and focused summary by ID after reordering', () => {
  const f = frontend(), host = f.root;
  host.innerHTML = evidenceHtml([11, 22, 33]);
  evidenceFor(host, 22).open = true; evidenceFor(host, 33).open = true;
  const oldSummary = evidenceFor(host, 22).querySelector('summary'); oldSummary.focus();
  f.replaceDeploymentContent(host, evidenceHtml([33, 11, 44, 22]));
  assert.deepEqual(host.querySelectorAll('.dep-evidence').map(detail => [detail.dataset.deployment, detail.open]),
    [['33', true], ['11', false], ['44', false], ['22', true]]);
  const summary = evidenceFor(host, 22).querySelector('summary');
  assert.notEqual(summary, oldSummary); assert.equal(oldSummary.isConnected, false);
  assert.equal(f.document.activeElement, summary); assert.equal(summary.focusOptions.preventScroll, true);
});

test('deployment refresh keeps a focused closed disclosure closed', () => {
  const f = frontend(), host = f.root;
  host.innerHTML = evidenceHtml([11, 22]); evidenceFor(host, 22).open = true;
  evidenceFor(host, 11).querySelector('summary').focus();
  f.replaceDeploymentContent(host, evidenceHtml([22, 11]));
  assert.equal(evidenceFor(host, 11).open, false); assert.equal(evidenceFor(host, 22).open, true);
  assert.equal(f.document.activeElement, evidenceFor(host, 11).querySelector('summary'));
  assert.equal(f.document.activeElement.focusOptions.preventScroll, true);
});

test('removed deployments do not transfer disclosure state or focus to another row', () => {
  const f = frontend(), host = f.root;
  host.innerHTML = evidenceHtml([11, 22, 33]);
  evidenceFor(host, 22).open = true; evidenceFor(host, 33).open = true;
  const removedSummary = evidenceFor(host, 22).querySelector('summary'); removedSummary.focus();
  f.replaceDeploymentContent(host, evidenceHtml([33, 11, 44]));
  assert.equal(evidenceFor(host, 22), null); assert.equal(removedSummary.isConnected, false);
  assert.equal(evidenceFor(host, 33).open, true); assert.equal(evidenceFor(host, 11).open, false);
  assert.equal(evidenceFor(host, 44).open, false); assert.equal(f.document.activeElement, f.document.body);
  evidenceFor(host, 33).querySelector('summary').focus();
  f.replaceDeploymentContent(host, '<p>No deployments</p>');
  assert.equal(host.querySelectorAll('.dep-evidence').length, 0);
  assert.equal(f.document.activeElement, f.document.body);
});

test('deployment refresh leaves focus outside the refreshed host alone', () => {
  const f = frontend();
  f.root.innerHTML = `<section id="deployments">${evidenceHtml([11])}</section><button id="elsewhere">Elsewhere</button>`;
  const host = f.root.querySelector('#deployments'), outside = f.root.querySelector('#elsewhere');
  evidenceFor(host, 11).open = true; outside.focus();
  f.replaceDeploymentContent(host, evidenceHtml([22, 11]));
  assert.equal(evidenceFor(host, 11).open, true); assert.equal(evidenceFor(host, 22).open, false);
  assert.equal(f.document.activeElement, outside);
  assert.ok(host.querySelectorAll('summary').every(summary => summary.focusOptions === undefined));
});

for (const [label, view, endpoint, selector] of [
  ['Overview', 'viewDashboard', '/api/dashboard', 'main'],
  ['Deploy', 'viewDeploy', '/api/deployments', '#deps'],
]) {
  test(`${label} polling preserves deployment disclosure state and focus through reordering and removal`, async () => {
    let ids = [11, 22, 33], reads = 0;
    const deployment = id => ({id, strategy_id: id + 100, title: `Strategy ${id}`, market: 'btc15m', mode: 'paper',
      status: 'running', stake: 5, max_positions: 2, backtest: {out_of_sample: {pnl: 12}},
      created_at: '2026-10-17T10:00:00Z', realized_pnl: 3, unrealized_pnl: null, closed_trades: 1, open_positions: 0, curve: []});
    const f = frontend({fetchImpl: path => {
      assert.equal(path, endpoint); reads++;
      return response({deployments: ids.map(deployment), open_positions: [], recent_closed: [],
        paper: {equity: 1000, cash: 1000, total_pnl: 0, open_at_cost: 0},
        live: {connected: false}, demo: {equity: 1000, capital: 1000, realized_pnl: 0},
        freshness: {btc: 1}, agents: {research_running: 0, research_queued: 0}});
    }});
    await f[view]();
    let host = f.root.querySelector(selector);
    evidenceFor(host, 11).open = true;
    const oldSummary = evidenceFor(host, 11).querySelector('summary'); oldSummary.focus();
    const poll = f.intervals.get(f.S.timers.at(-1)); assert.equal(typeof poll, 'function');
    ids = [44, 22, 11]; poll(); await flush();
    host = f.root.querySelector(selector);
    assert.equal(reads, 2);
    assert.deepEqual(host.querySelectorAll('.dep-evidence').map(detail => [detail.dataset.deployment, detail.open]),
      [['44', false], ['22', false], ['11', true]]);
    const summary = evidenceFor(host, 11).querySelector('summary');
    assert.notEqual(summary, oldSummary); assert.equal(oldSummary.isConnected, false);
    assert.equal(f.document.activeElement, summary); assert.equal(summary.focusOptions.preventScroll, true);
    assert.equal(typeof host.querySelector('[data-dep]').onclick, 'function');
    ids = [22, 44]; poll(); await flush();
    host = f.root.querySelector(selector);
    assert.equal(reads, 3); assert.equal(evidenceFor(host, 11), null);
    assert.ok(host.querySelectorAll('.dep-evidence').every(detail => !detail.open));
    assert.equal(f.document.activeElement, f.document.body); assert.equal(postRequests(f).length, 0);
  });
}

const dashboardData = ({paper = {}, live = {}, demo = {}, ...overrides} = {}) => ({
  paper: {equity: 1111.25, cash: 900, total_pnl: 111.25, today_pnl: -7.5, open_at_cost: 211.25, ...paper},
  live: {connected: false, balance: null, realized_pnl: 17, today_pnl: -2, open_positions: 0, open_at_cost: 50, ...live},
  demo: {equity: 2222.5, capital: 2200, realized_pnl: 22.5, open_positions: 0, running: 0, ...demo},
  deployments: [], open_positions: [], recent_closed: [], freshness: {btc: 1},
  agents: {research_running: 0, research_queued: 0}, ...overrides,
});
const dashboardDeployment = (mode, status = 'running') => ({id: 91, strategy_id: 42, title: 'Offline deployment',
  market: 'btc15m', mode, status, stake: 5, max_positions: 2, realized_pnl: 3,
  unrealized_pnl: null, closed_trades: 1, open_positions: 0, curve: [], created_at: '2026-10-17T10:00:00Z'});
const dashboardPosition = (id, overrides = {}) => ({id, ticker: `KXBTC15M-26OCT181230-${id}`, title: `Strategy ${id}`,
  side: 'yes', qty: 10, entry_price: 0.35, mode: 'paper', unrealized: null, pnl: 4.25,
  market_close_time: '2026-10-18T12:30:00Z', opened_at: '2020-01-01T12:30:00Z', closed_at: '2020-01-02T12:30:00Z', ...overrides});

const apStatus = {autopilot: true, mode: 'paper', story: ['Right now it’s researching BTC 15m.'],
  research: {tested_7d: 12, passed_7d: 0, active: []}, live_running: 0, demo_running: 0, paper_running: 1};
const apDashboard = (data, status) => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(data);
    if (path === '/api/autopilot/status') return response(status);
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = true;
  return f;
};

test('Overview paper P&L says "since reset" after a reset and its day figure says realized', async () => {
  for (const reset_at of [null, '2026-10-20T09:00:00Z']) {
    const f = apDashboard(dashboardData({paper: {reset_at}}), apStatus);
    await f.viewDashboard(); await flush();
    f.S.ap = apStatus; f.paintDashAp();
    const paper = f.root.querySelector('.paper-summary').textContent;
    // total_pnl restarts at a reset; the track record keeps every closed trade, so "all time" would disagree.
    assert.match(paper, reset_at ? /P&amp;L since reset \+\$111\.25/ : /All-time P&amp;L \+\$111\.25/);
    if (reset_at) assert.doesNotMatch(paper, /All-time/);
    // Today is closed trades only (realized_pnl), unlike the equity P&L beside it; the live group says so too.
    assert.match(paper, /Realized today \(UTC\)−\$7\.50/);
    const card = f.root.querySelector('#dash-ap').innerHTML;
    assert.match(card, new RegExp(`<dt>Paper P&amp;L, ${reset_at ? 'since reset' : 'all time'}</dt><dd><span class="[^"]*">\\+\\$111\\.25`));
  }
});

test('Overview says plainly when demo can’t trade, on the page and in the autopilot card, with the action', async () => {
  const health = {code: 'demo_funds', need: 'demo funds: your Kalshi demo account has $0.00',
    line: "Demo isn't trading: your Kalshi demo account has $0.00. Add demo funds on Kalshi's demo site.",
    action: {label: 'Open Kalshi demo', href: 'https://demo.kalshi.co'}};
  const said = /Demo isn&#39;t trading: your Kalshi demo account has \$0\.00\. Add demo funds on Kalshi&#39;s demo site\. <a href="https:\/\/demo\.kalshi\.co" target="_blank" rel="noopener">Open Kalshi demo ↗<\/a>/;
  const status = {...apStatus, demo_running: 1, idle: health};
  const f = apDashboard(dashboardData({demo: {running: 1, health}}), status);
  await f.viewDashboard(); await flush();
  f.S.ap = status; f.paintDashAp();
  const head = f.root.querySelector('#boardbody').innerHTML;
  // Out in the open, not only inside the collapsed Accounts menu's demo figure (which says it too).
  assert.match(head, new RegExp('<div class="notice bad" role="status">[\\s\\S]*?<span class="demo-health">' + said.source));
  assert.match(f.root.querySelector('#other-accounts').innerHTML, new RegExp(said.source + '<\\/span><br>\\$2,200\\.00 capital'));
  assert.match(f.root.querySelector('#dash-ap').innerHTML, said);
  // A healthy demo book reads as before.
  const g = apDashboard(dashboardData({demo: {running: 1}}), apStatus);
  await g.viewDashboard(); await flush();
  assert.doesNotMatch(g.root.querySelector('#boardbody').innerHTML, /demo-health|isn&#39;t trading/);
});

test('Overview empty paper track record follows the autopilot switch when a status read flips it', async () => {
  let status = {autopilot: false, mode: 'off'};
  const empty = (label) => ({trades: 0, label});
  const tr = {generated_at: 1, default_mode: 'paper', method: [], thresholds: {min_sharpe_days: 14, min_trades: 30},
    modes: {live: empty('Live money'), demo: empty('Kalshi demo'), paper: empty('Paper')}};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData());
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
  status = {autopilot: true, mode: 'paper', story: [], research: {}, live_running: 0, demo_running: 0, paper_running: 0};
  for (const tick of [...f.intervals.values()]) tick();
  await flush(); await flush();
  assert.equal(f.S.me.user.autopilot, true);
  assert.match(panel(), /Autopilot runs the strategies that pass every gate on paper/); assert.doesNotMatch(panel(), /Go to Deploy/);
});

test('Overview empty Deployed box never says autopilot is researching while the card says it is quiet or paused', async () => {
  const quiet = {...apStatus, story: ['Right now it’s between research runs. Its last check-in was 3 hours ago, longer than usual.']};
  for (const status of [quiet, {...apStatus, billing_blocked: true, billing_reason: 'card', story: []}]) {
    const f = apDashboard(dashboardData(), status);
    await f.viewDashboard(); await flush();
    f.S.ap = status; f.paintDashAp();
    assert.match(f.root.querySelector('#dash-ap').innerHTML, status.billing_blocked ? /Paused: / : /longer than usual/);
    const deps = f.root.querySelector('#deps-empty').innerHTML;
    assert.match(deps, /Autopilot is on\./); assert.doesNotMatch(deps, /is researching/);
  }
});

test('Overview offers each mode its own trades CSV only when that mode has closed trades', async () => {
  for (const [counts, connected, deployments] of [[{paper: 0, demo: 0, live: 0}, false, []], [{paper: 4, demo: 0, live: 0}, false, []],
    [{paper: 1, demo: 2, live: 3}, true, [dashboardDeployment('live')]], [{paper: 0, demo: 0, live: 3}, false, []]]) {
    const data = dashboardData({paper: {closed_trades: counts.paper}, demo: {closed_trades: counts.demo},
      live: {connected, balance: connected ? 50 : null, closed_trades: counts.live}, deployments});
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response(data);
      if (path.startsWith('/api/deployments/')) return response({});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    // Paper (or live, once real money runs) sits in the account band; the other accounts in the menu.
    const html = f.root.querySelector('#boardbody').innerHTML + f.root.querySelector('main').innerHTML;
    for (const mode of ['paper', 'demo', 'live']) {
      const link = `<a class="csv-link" href="/api/trades.csv?mode=${mode}" download>Download trades (CSV)</a>`;
      assert.equal(html.includes(link), counts[mode] > 0, `${mode} ${JSON.stringify(counts)}`);
    }
  }
});

test('Overview demo account says what demo is and that its P&L restarts at a reload', async () => {
  for (const [demo, re] of [
    [{equity: 1000, capital: 1000, realized_pnl: 0}, /\$1,000\.00 capital ·\u00a0No demo deployments ·\u00a0real fills on Kalshi’s sandbox, not real money/],
    [{equity: 512, capital: 500, realized_pnl: 12, running: 1, before_reload: 40}, /\$500\.00 capital ·\u00a00 open ·\u00a0\+\$12\.00 P&amp;L since reload ·\u00a0real fills/],
    [{equity: 1012, capital: 1000, realized_pnl: 12, running: 1, before_reload: 0}, /\+\$12\.00 P&amp;L all time ·\u00a0real fills/],
  ]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData({demo})); }});
    await f.viewDashboard(); await flush();
    assert.match(f.root.querySelector('#other-accounts').innerHTML, re);
  }
});

test('Funds demo labels say "since reload" only after a reload, and that demo fills are real', async () => {
  for (const before_reload of [0, 40]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds(); d.demo.before_reload = before_reload; return response(d); }});
    await f.viewFunds(); await flush();
    const main = f.root.querySelector('main').innerHTML;
    assert.match(main, before_reload ? /<dt>Capital at last reload<\/dt>/ : /<dt>Starting capital<\/dt>/);
    assert.match(main, before_reload ? /<dt>P&amp;L since reload<\/dt>/ : /<dt>P&amp;L all time<\/dt>/);
    assert.match(main, /fills and slippage are real; the money is simulated/);
    assert.match(main, /the track record still counts every closed demo trade/);
    assert.match(f.root.querySelector('#ffigs').innerHTML, before_reload ? /capital at last reload ·\u00a0real fills on Kalshi’s sandbox/ : /starting capital ·\u00a0real fills on Kalshi’s sandbox/);
  }
});

test('Overview live summary says it is Kalshi cash, apart from what Tau trades realized', async () => {
  const status = {...apStatus, live_running: 1, today_live_pnl: -2};
  const f = apDashboard(dashboardData({deployments: [dashboardDeployment('live')], live: {connected: true, balance: 3333, open_positions: 2}}), status);
  await f.viewDashboard(); await flush();
  f.S.ap = status; f.paintDashAp();
  const live = f.root.querySelector('.live-summary');
  assert.equal(live.querySelector('dt.lab').textContent, 'Kalshi cash');
  assert.match(live.textContent, /\+\$17\.00 realized all time by Tau trades/);
  assert.match(live.textContent, /Open at cost, not in cash\$50\.00/); assert.match(live.textContent, /Realized today \(UTC\)−\$2\.00/);
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Live realized today \(UTC\)<\/dt><dd><span class="[^"]*">−\$2\.00/);
});

test('Funds names the live figure Kalshi cash, open positions not included', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds();
    d.kalshi = {connected: true, key_id: 'abcd-wxyz', balance: 120, funding_url: 'https://kalshi.com'}; return response(d); }});
  await f.viewFunds(); await flush();
  const figs = f.root.querySelector('#ffigs').innerHTML;
  assert.match(figs, /Kalshi cash/); assert.match(figs, /Real money at Kalshi, open positions not included/);
  assert.doesNotMatch(figs, /Live money/);
});

test('Deploy open positions say their cost includes the entry fee', async () => {
  const pos = {title: 'Rain fade', ticker: 'KXRAINNYC-T1', side: 'no', qty: 4, entry_price: .37, entry_fee: .02, unrealized: null, market_close_time: '2026-10-25T17:30:00Z', mode: 'live'};
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/deployments'); return response({deployments: [], open_positions: [pos]}); }});
  await f.viewDeploy(); await flush();
  const html = f.root.querySelector('#openpos').innerHTML;
  assert.match(html, /<th class="num">Cost \+ fee<\/th>/); assert.match(html, /data-lab="Cost \+ fee">\$1\.50</);
});

test('every trade says why it was entered and why it exited: Overview rows, Deploy and the strategy sidebar', async () => {
  const exitWhy = 'Entered at 35¢: the 5-minute return < −0.002, edge ≥ 3¢ after fees · Exited at 62¢: take-profit (+27¢ vs +20¢ target)';
  const openWhy = 'Entered at 35¢: edge ≥ 3¢ after fees · Exits: +20¢ take-profit, −10¢ stop, else settlement';
  const open = [dashboardPosition(1, {why: openWhy}), dashboardPosition(2, {why: null})];
  const closed = [dashboardPosition(3, {why: exitWhy}), dashboardPosition(4, {why: 'Held to settlement: <img src=x>'})];
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData({open_positions: open, recent_closed: closed})); }});
  await f.viewDashboard();
  const why = key => positionFor(f.root, key).querySelector('.position-why');
  assert.equal(why('open-1').textContent, openWhy);
  assert.equal(why('open-2'), null);  // nothing stored to say: no empty line
  assert.equal(why('closed-3').textContent, exitWhy.replace('<', '&lt;'));
  assert.equal(why('closed-4').textContent, 'Held to settlement: &lt;img src=x&gt;');
  assert.ok(f.root.querySelector('#recent-settlements').contains(why('closed-3')));
  assert.doesNotMatch(f.root.querySelector('main').innerHTML, /<img/);
  const pos = {title: 'Rain fade', ticker: 'KXRAINNYC-T1', side: 'no', qty: 4, entry_price: .37, entry_fee: .02, unrealized: null,
    market_close_time: '2026-10-25T17:30:00Z', mode: 'paper', why: openWhy};
  const d = frontend({fetchImpl: path => { assert.equal(path, '/api/deployments'); return response({deployments: [], open_positions: [pos, {...pos, ticker: 'KXRAINNYC-T2', why: null}]}); }});
  await d.viewDeploy(); await flush();
  const table = d.root.querySelector('#openpos').innerHTML;
  assert.deepEqual([...table.matchAll(/<div class="sub-fig pos-why">([^<]*)<\/div>/g)].map(m => m[1]), [openWhy]);
  const holdings = [{ticker: 'KXBTC15M-A', side: 'yes', qty: 2, entry_price: 0.35, cost: 0.7, unrealized: null, mode: 'paper',
    market_close_time: '2026-10-25T07:45:00Z', why: openWhy}];
  const s = strategyFrontend(detailStrategy({holdings})); await s.viewStrategy(42); await flush();
  const list = s.root.querySelector('main').innerHTML;
  assert.match(list, new RegExp('<ul class="holdlist">[\\s\\S]*<div class="sub-fig pos-why">' + openWhy.replace(/[+.*?()]/g, '\\$&') + '</div></li>'));
  assert.equal(postRequests(f).length + postRequests(d).length, 0);
});

test('Deploy realized says it counts only the strategies listed, never summing live with paper', async () => {
  const dep = (id, mode, pnl) => ({...dashboardDeployment(mode), id, strategy_id: id, realized_pnl: pnl});
  for (const [deployments, re] of [[[dep(1, 'paper', 2)], /\+\$2\.00[\s\S]*paper money, not real ·\u00a0strategies listed below/],
    [[dep(1, 'paper', 2), dep(2, 'live', 5)], /Live realized[\s\S]*\+\$5\.00[\s\S]*real money, strategies listed below ·\u00a0\+\$2\.00 on paper, counted apart/]]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/deployments'); return response({deployments, open_positions: []}); }});
    await f.viewDeploy(); await flush();
    const figs = f.root.querySelector('#dfigs').innerHTML;
    assert.match(figs, re); assert.doesNotMatch(figs, /\$7\.00/);
  }
});

test('Overview "paused, needs you" jumps to the first paused deployment', async () => {
  const deployments = [{...dashboardDeployment('paper'), id: 91, strategy_id: 41},
    {...dashboardDeployment('paper', 'paused'), id: 92, strategy_id: 42, status_reason: 'loss guard'},
    {...dashboardDeployment('demo', 'paused'), id: 93, strategy_id: 43}];
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData({deployments})); }});
  await f.viewDashboard();
  assert.match(f.root.querySelector('.statusline').innerHTML, /<a class="needs-link" href="#dash-paused"><em>2 paused, needs you<\/em><\/a>/);
  const anchored = f.root.querySelectorAll('#dash-deps article#dash-paused');
  assert.equal(anchored.length, 1); assert.equal(anchored[0].querySelector('header h3 a').getAttribute('href'), '/strategies/42');
});

test('Overview autopilot card says what switching it on costs, and a running first review reads as one', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData()); }});
  const card = () => f.root.querySelector('#dash-ap'), cost = () => f.root.querySelector('#dash-ap .apcard-cost');
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 18.4, auto_reload: {amount: 20, charge: 21.1, threshold: 5}};
  await f.viewDashboard(); await flush();
  assert.match(cost().innerHTML, /uses your credits while it's on \(\$18\.40 left\)\. When they fall to \$5\.00, auto-reload charges your card \$21\.10 for \$20\.00 more\./);
  f.S.me.auto_reload = null;
  await f.viewDashboard(); await flush();
  assert.match(cost().innerHTML, /and pauses when they run out\. Turn it off any time\./);
  f.S.me.billing_enabled = false;
  await f.viewDashboard(); await flush();
  assert.equal(cost(), null); assert.match(card().innerHTML, /Turn on autopilot/);
  // Switched on, first review still queued: the card says so instead of "Last move just now".
  const at = new Date().toISOString();
  f.S.me.user.autopilot = true;
  f.S.ap = {autopilot: true, mode: 'paper', story: ['Right now it’s reviewing the markets to pick its next move.'], research: {tested_7d: 0, passed_7d: 0, active: []},
    live_running: 0, demo_running: 0, paper_running: 0, reviewing: true, last_review_at: at, last_action: {at, text: 'Autopilot is ON: …'}};
  f.S.apAt = Date.now();
  await f.viewDashboard(); await flush();
  assert.match(card().innerHTML, /<dt>Last move<\/dt><dd>Reviewing now<\/dd>/);
});

test('Overview deployment monitors preserve every mode, status, risk field and unknown-versus-zero result', async () => {
  const deployments = Object.freeze(['paper', 'demo', 'live'].flatMap((mode, modeIndex) => ['running', 'paused', 'stopped'].map((status, index) =>
    Object.freeze({...dashboardDeployment(mode, status), id: 100 + modeIndex * 3 + index,
      strategy_id: 200 + modeIndex * 3 + index, title: `Strategy <b>${mode} ${status}</b>`,
      stake: 12.5, max_positions: 4, status_reason: 'Risk <cap> reached', realized_pnl: [null, 0, -3.25][index],
      unrealized_pnl: [null, 0, -2.5][index], closed_trades: [0, 2, 5][index], open_positions: [1, 2, 0][index],
      backtest: index === 0 ? null : {out_of_sample: {pnl: index === 1 ? 0 : 7.25}}}))));
  const before = JSON.stringify(deployments), data = dashboardData({deployments});
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(data); }});
  await f.viewDashboard();
  const monitors = f.root.querySelectorAll('#dash-deps article.dep-monitor'); assert.equal(monitors.length, 9);
  monitors.forEach((monitor, index) => {
    const d = deployments[index], state = monitor.querySelector('.monitor-state'), link = monitor.querySelector('header h3 a');
    const field = name => monitor.querySelectorAll('dl > div').find(div => div.querySelector('dt').textContent.startsWith(name)).querySelector('dd');
    assert.equal(link.getAttribute('href'), `/strategies/${d.strategy_id}`);
    assert.equal(link.textContent, `Strategy &lt;b&gt;${d.mode} ${d.status}&lt;/b&gt;`);
    assert.ok(state.textContent.endsWith(d.status === 'running' ? 'Running' : d.status === 'paused' ? 'Paused' : 'Stopped'));
    assert.equal(state.querySelector('.mk').textContent, d.mode === 'live' ? 'LIVE' : d.mode === 'demo' ? 'Demo' : 'Paper');
    assert.equal(monitor.classList.contains('live-row'), d.mode === 'live');
    assert.match(monitor.querySelector('.monitor-setup').textContent, /BTC 15-min ·\u00a0\$12\.5 \/ trade/);
    assert.ok(monitor.querySelector('.monitor-limits').textContent.includes('Max 4 open'));
    assert.ok(monitor.querySelector('.monitor-limits').textContent.startsWith(' ·\u00a0Max 4 open'), 'a space before the separator, so it never reads "trade· Max"');
    assert.equal(monitor.querySelector('.monitor-limits').textContent.includes('Risk &lt;cap&gt; reached'), d.status !== 'running');
    assert.equal(field('Realized').textContent, d.status === 'running' ? '—' : d.status === 'paused' ? '$0.00' : '−$3.25');
    assert.equal(field('Unrealized').textContent.trim(), d.status === 'running' ? 'Unavailable' : d.status === 'paused' ? '$0.00' : '−$2.50');
    assert.equal(monitor.querySelectorAll('.monitor-metrics dt')[1].textContent.includes('(est.)'), d.unrealized_pnl != null && d.open_positions > 0);
    assert.equal(field('Closed').textContent, `${d.closed_trades} / ${d.open_positions}`);
    assert.equal(field('Closed').getAttribute('aria-label'), `${d.closed_trades} closed trades, ${d.open_positions} open positions`);
    const evidence = evidenceFor(monitor, d.id); assert.equal(evidence.tag, 'details'); assert.equal(evidence.open, false);
    assert.ok(evidence.textContent.includes(`Unseen P&amp;L ${d.status === 'running' ? '—' : d.status === 'paused' ? '$0.00' : '+$7.25'}`));
    assert.ok(evidence.textContent.includes('Deployed ' + new Date(d.created_at).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})));
    assert.deepEqual(monitor.querySelectorAll('[data-dep]').map(button => button.dataset.act),
      d.status === 'running' ? ['pause', 'stop'] : d.status === 'paused' ? ['resume', 'stop'] : ['stop']);
    assert.ok(monitor.querySelectorAll('[data-dep]').every(button => button.dataset.dep === String(d.id) && typeof button.onclick === 'function'));
    assert.equal(monitor.querySelector('b'), null); assert.equal(monitor.querySelector('cap'), null);
  });
  assert.equal(JSON.stringify(deployments), before); assert.equal(postRequests(f).length, 0);
});

test('Overview polling shares paper-running context only for a nonempty uniform book and preserves row controls and research destinations', async () => {
  const paper = (id, status = 'running') => Object.freeze({...dashboardDeployment('paper', status), id, strategy_id: 100 + id, status_reason: 'Risk cap reached'});
  const first = paper(11), second = paper(22);
  const frames = [
    {deployments: [first, second], agents: {research_running: 2, research_queued: 1}, context: 'Paper', activity: '3 agents researching'},
    {deployments: [paper(11, 'paused'), second], agents: {research_running: 1, research_queued: 0}, context: null, activity: '1 agent researching'},
    {deployments: [first, Object.freeze({...paper(22, 'paused'), mode: 'demo'}), Object.freeze({...paper(33, 'stopped'), mode: 'live'})], agents: {research_running: 0, research_queued: 0}, context: null, activity: null},
    {deployments: [], agents: {research_running: 0, research_queued: 0}, context: null, activity: null},
    {deployments: [first], agents: {research_running: 0, research_queued: 1}, context: 'Paper', activity: '1 agent researching'},
  ];
  let data, poll, reads = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); reads++; return response(data); }});
  for (const frame of frames) {
    Object.freeze(frame.deployments); Object.freeze(frame.agents);
    data = Object.freeze(dashboardData({deployments: frame.deployments, agents: frame.agents})); const before = JSON.stringify(data);
    if (!poll) { await f.viewDashboard(); poll = f.intervals.get(f.S.timers.at(-1)); assert.equal(typeof poll, 'function'); }
    else { poll(); await flush(); }
    const section = f.root.querySelector('.deployed-monitor'), context = section.querySelector('.monitor-context');
    assert.equal(section.classList.contains('shared-paper-running'), frame.context !== null);
    assert.equal(context?.textContent ?? null, frame.context);
    const monitors = section.querySelectorAll('.dep-monitor'); assert.equal(monitors.length, frame.deployments.length);
    monitors.forEach((monitor, index) => {
      const d = frame.deployments[index], state = monitor.querySelector('.monitor-state');
      assert.equal(state.hidden, false); assert.equal(state.getAttribute('aria-hidden'), null);
      assert.equal(state.querySelector('.mk').textContent, d.mode === 'live' ? 'LIVE' : d.mode === 'demo' ? 'Demo' : 'Paper');
      assert.ok(state.textContent.endsWith(d.status === 'running' ? 'Running' : d.status === 'paused' ? 'Paused' : 'Stopped'));
      assert.equal(monitor.querySelector('header h3 a').getAttribute('href'), `/strategies/${d.strategy_id}`);
      assert.equal(monitor.querySelector('.monitor-limits').textContent.includes('Risk cap reached'), d.status !== 'running');
      const evidence = evidenceFor(monitor, d.id); assert.ok(evidence);
      assert.equal(evidence.contains(monitor.querySelector('[data-act="stop"]')), true);
      assert.deepEqual(monitor.querySelectorAll('[data-dep]').map(button => [button.dataset.dep, button.dataset.act]),
        (d.status === 'running' ? ['pause', 'stop'] : d.status === 'paused' ? ['resume', 'stop'] : ['stop']).map(action => [String(d.id), action]));
      assert.ok(monitor.querySelectorAll('[data-dep]').every(button => typeof button.onclick === 'function'));
    });
    const actions = f.root.querySelector('.page-actions'), activity = actions.querySelector('.research-activity');
    assert.equal(activity?.textContent ?? null, frame.activity);
    if (activity) assert.equal(activity.getAttribute('href'), '/research');
    assert.equal(section.querySelector('.research-activity'), null);
    assert.equal(actions.querySelector('a[href="/research?new=1"]'), null);
    const createLinks = section.querySelectorAll('a[href="/research?new=1"]');
    assert.equal(createLinks.length, 1);
    const create = createLinks[0];
    assert.equal(create.textContent, frame.deployments.length ? 'New research' : 'New session');
    assert.equal(create.getAttribute('href'), '/research?new=1');
    if (!frame.deployments.length) {
      assert.equal(section.querySelector('.empty h3').textContent, 'Nothing deployed yet');
      assert.equal(section.querySelector('.empty a').getAttribute('href'), '/research?new=1');
    }
    assert.equal(JSON.stringify(data), before);
  }
  assert.equal(reads, frames.length); assert.equal(postRequests(f).length, 0); assert.deepEqual(f.navigations, []);
});

test('Overview monitor actions use the correct deployment and retain two-click removal confirmation', async () => {
  let deployments = [{...dashboardDeployment('live'), id: 11}, {...dashboardDeployment('demo', 'paused'), id: 22}], reads = 0;
  const f = frontend({fetchImpl: (path, options) => {
    if (path === '/api/dashboard') { reads++; return response(dashboardData({deployments})); }
    const [, id, action] = path.match(/^\/api\/deployments\/(11|22)\/(pause|resume|stop)$/) || [];
    assert.ok(id); assert.equal(options.method, 'POST'); assert.deepEqual(JSON.parse(options.body), {});
    deployments = deployments.map(d => d.id === Number(id) ? {...d, status: action === 'pause' ? 'paused' : action === 'resume' ? 'running' : 'stopped'} : d);
    return response({ok: true});
  }});
  await f.viewDashboard();
  f.root.querySelector('[data-dep="11"][data-act="pause"]').onclick(); await flush();
  assert.equal(postRequests(f)[0].path, '/api/deployments/11/pause');
  assert.ok(f.root.querySelector('[data-dep="11"][data-act="resume"]'));
  f.root.querySelector('[data-dep="22"][data-act="resume"]').onclick(); await flush();
  assert.equal(postRequests(f)[1].path, '/api/deployments/22/resume');
  const evidence = evidenceFor(f.root, 11); assert.equal(evidence.open, false); evidence.open = true;
  assert.equal(evidence.contains(f.root.querySelector('[data-dep="11"][data-act="stop"]')), true);
  const remove = f.root.querySelector('[data-dep="11"][data-act="stop"]'); remove.onclick(); await flush();
  assert.equal(remove.textContent, 'Confirm stop'); assert.equal(postRequests(f).length, 2);
  remove.onclick(); await flush();
  assert.equal(postRequests(f)[2].path, '/api/deployments/11/stop'); assert.equal(reads, 4);
  assert.deepEqual(f.navigations, []);
});

test('Overview charts cumulative closed paper results separately from all-time P&L and omits short histories', async () => {
  const day = offset => new Date(Date.now() + offset * 86400000).toISOString().slice(0, 10);
  let data, poll, reads = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); reads++; return response(data); }});
  const cases = [
    [[{d: day(-4), pnl: -4}, {d: day(-2), pnl: 0}, {d: day(-1), pnl: 1}], '−$3.00', ['−$4.00', '−$4.00', '−$3.00']],
    [[{d: day(-2), pnl: 0}, {d: day(-1), pnl: 0}], '$0.00', ['$0.00', '$0.00']],
    [[{d: day(-1), pnl: -4}], null],
    [[], null],
  ];
  for (const [daily, ending, amounts] of cases) {
    daily.forEach(Object.freeze); Object.freeze(daily);
    data = dashboardData({paper: {daily}}); Object.freeze(data.paper); Object.freeze(data);
    const before = JSON.stringify(data);
    if (!poll) {
      await f.viewDashboard(); poll = f.intervals.get(f.S.timers.at(-1));
      assert.equal(typeof poll, 'function');
    } else { poll(); await flush(); }
    assert.match(f.root.querySelector('.paper-summary').textContent, /All-time P&amp;L \+\$111\.25/);
    const performance = f.root.querySelector('.overview-performance');
    if (ending === null) assert.equal(performance, null);
    else {
      const chart = performance.querySelector('svg.chart'), label = chart.getAttribute('aria-label');
      assert.match(label, /^Cumulative closed paper profit and loss /);
      assert.ok(label.includes(`from ${daily[0].d} through ${daily.at(-1).d}`), 'sparse trading dates are labelled as their actual period');
      assert.equal(performance.querySelector('.sect-note').getAttribute('title'), `${daily[0].d} – ${daily.at(-1).d}`);
      assert.ok(performance.querySelector('.sect-note').textContent.includes(daily.at(-1).d.slice(0, 4)));
      assert.ok(label.endsWith('; ends at ' + ending)); assert.doesNotMatch(label, /backtest|111\.25/);
      assert.equal(chart.getAttribute('role'), 'group');
      const samples = chart.querySelectorAll('.chart-sample'); assert.equal(samples.length, daily.length);
      samples.forEach((sample, index) => {
        const date = new Date(daily[index].d + 'T12:00:00Z').toLocaleDateString(undefined, {month: 'short', day: 'numeric', timeZone: 'UTC'});
        assert.equal(sample.dataset.time, String(Date.parse(daily[index].d + 'T12:00:00Z') / 1000));
        assert.equal(sample.getAttribute('tabindex'), '0'); assert.equal(sample.getAttribute('role'), 'img');
        assert.equal(sample.getAttribute('aria-label'), `${date} ·\u00a0${amounts[index]}`);
        assert.equal(sample.querySelector('.chart-reading').getAttribute('aria-hidden'), 'true');
        assert.equal(sample.querySelector('.chart-reading text').textContent, `${date} ·\u00a0${amounts[index]}`);
      });
      const points = chart.querySelector('polyline').getAttribute('points').split(' ').map(point => point.split(',').map(Number));
      assert.equal(points.length, daily.length); assert.ok(points.flat().every(Number.isFinite));
      assert.equal(points[0][1], points[1][1], 'a zero-P&L day keeps cumulative P&L flat');
      const zeroY = Number(chart.querySelector('line').getAttribute('y1'));
      if (daily.length === 3) {
        assert.ok(points[0][1] > zeroY && points[2][1] > zeroY, 'the initial loss and negative ending stay below zero');
        assert.ok(points[2][1] < points[1][1], 'a positive day recovers part of the realized loss');
      } else assert.ok(points.every(point => point[1] === zeroY));
      assert.doesNotMatch(chart.innerHTML, /NaN|undefined/);
    }
    assert.equal(JSON.stringify(data), before); assert.equal(data.paper.daily, daily);
  }
  assert.equal(reads, cases.length); assert.equal(postRequests(f).length, 0);
  assert.deepEqual(f.requests.filter(request => request.path !== '/api/notifications').map(request => request.path),
    cases.map(() => '/api/dashboard'));
  assert.deepEqual(f.navigations, []);
});

test('Overview paper performance preserves disclosure and focus on polls and redraws locally until cleared', async () => {
  const daily = pnl => [{d: '2026-10-16', pnl: -4}, {d: '2026-10-18', pnl}];
  let data = dashboardData({paper: {daily: daily(1)}}), reads = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); reads++; return response(data); }});
  const resize = () => f.windowListeners.get('resize').forEach(callback => callback());
  await f.viewDashboard();
  let performance = f.root.querySelector('#paper-performance');
  assert.equal(performance.tag, 'details'); assert.equal(performance.open, true);
  const poll = f.intervals.get(f.S.timers.at(-1));
  for (const [open, pnl, ending] of [[true, 2, '−$2.00'], [false, 5, '+$1.00']]) {
    performance.open = open;
    const oldSummary = performance.querySelector('summary'); oldSummary.focus();
    data = dashboardData({paper: {daily: daily(pnl)}}); poll(); await flush();
    const next = f.root.querySelector('#paper-performance'), summary = next.querySelector('summary');
    assert.notEqual(next, performance); assert.equal(oldSummary.isConnected, false); assert.equal(next.open, open);
    assert.equal(f.document.activeElement, summary); assert.equal(summary.focusOptions.preventScroll, true);
    assert.ok(next.querySelector('svg.chart').getAttribute('aria-label').endsWith('; ends at ' + ending));
    const plot = next.querySelector('.paper-plot'), before = plot.writes, requestCount = f.requests.length;
    plot.clientWidth = 320; resize();
    assert.equal(plot.writes, before + 1); assert.equal(plot.querySelector('svg.chart').getAttribute('viewBox'), '0 0 320 180');
    assert.equal(f.document.activeElement, summary); assert.equal(next.open, open);
    assert.equal(f.requests.length, requestCount); performance = next;
  }
  performance.open = true;
  let sample = performance.querySelectorAll('.chart-sample').at(-1); sample.focus();
  const focusedTime = sample.dataset.time, localReads = f.requests.length;
  performance.querySelector('.paper-plot').clientWidth = 280; resize();
  assert.equal(sample.isConnected, false); sample = f.document.activeElement;
  assert.equal(sample.dataset.time, focusedTime); assert.equal(sample.focusOptions.preventScroll, true);
  assert.equal(f.requests.length, localReads);
  data = dashboardData({paper: {daily: [{d: '2026-10-16', pnl: -4}, {d: '2026-10-17', pnl: 1}, {d: '2026-10-18', pnl: 0}]}});
  poll(); await flush(); performance = f.root.querySelector('#paper-performance');
  assert.equal(sample.isConnected, false); sample = f.document.activeElement;
  assert.equal(performance.open, true); assert.equal(performance.querySelectorAll('.chart-sample').length, 3);
  assert.equal(sample.dataset.time, focusedTime); assert.equal(sample.focusOptions.preventScroll, true);
  assert.ok(sample.getAttribute('aria-label').endsWith(' ·\u00a0−$3.00'));
  data = dashboardData({paper: {daily: [{d: '2026-10-16', pnl: -4}, {d: '2026-10-19', pnl: 2}]}});
  poll(); await flush(); performance = f.root.querySelector('#paper-performance');
  assert.equal(performance.open, true); assert.equal(performance.querySelectorAll('.chart-sample').length, 2);
  assert.equal(sample.isConnected, false); assert.equal(f.document.activeElement, f.document.body);
  const outside = f.root.querySelector('.profile-trig'); outside.focus(); performance.open = true;
  poll(); await flush();
  performance = f.root.querySelector('#paper-performance');
  assert.equal(performance.open, true); assert.equal(f.document.activeElement, outside);
  performance.querySelector('summary').focus(); data = dashboardData({paper: {daily: daily(1).slice(0, 1)}});
  poll(); await flush();
  assert.equal(f.root.querySelector('#paper-performance'), null); assert.equal(f.document.activeElement, f.document.body);
  const beforeResize = f.requests.length; resize(); assert.equal(f.requests.length, beforeResize);
  outside.focus(); data = dashboardData({paper: {daily: daily(1)}}); poll(); await flush();
  performance = f.root.querySelector('#paper-performance');
  assert.equal(performance.open, true); assert.equal(f.document.activeElement, outside);
  const plot = performance.querySelector('.paper-plot'), writes = plot.writes;
  f.clearTimers(); plot.clientWidth = 420; resize();
  assert.equal(plot.writes, writes); assert.equal(f.S.timers.length, 0);
  assert.equal(reads, 8); assert.equal(postRequests(f).length, 0);
});

test('a late initial or polled Dashboard read cannot repaint the next page or restore chart work', async () => {
  for (const phase of ['initial', 'poll']) {
    const pending = deferred(), data = dashboardData({paper: {daily: [{d: '2026-10-16', pnl: -4}, {d: '2026-10-18', pnl: 1}]}});
    let reads = 0;
    const f = frontend({fetchImpl: path => {
      assert.equal(path, '/api/dashboard'); reads++;
      return phase === 'poll' && reads === 1 ? response(data) : pending.promise;
    }});
    const loading = f.viewDashboard();
    if (phase === 'poll') { await loading; f.intervals.get(f.S.timers.at(-1))(); }
    f.clearTimers(); f.S.gen++;
    f.root.innerHTML = '<div id="boardbody">Next board</div><main><div class="paper-plot">Next page</div></main>';
    const board = f.root.querySelector('#boardbody'), main = f.root.querySelector('main'), plot = main.querySelector('.paper-plot');
    const writes = [f.root.writes, board.writes, main.writes, plot.writes], intervals = [...f.intervals.keys()], requestCount = f.requests.length;
    pending.resolve(response(data)); await flush(); await flush();
    f.windowListeners.get('resize').forEach(callback => callback());
    assert.deepEqual([f.root.writes, board.writes, main.writes, plot.writes], writes, phase + ' read');
    assert.equal(board.innerHTML, 'Next board'); assert.equal(plot.innerHTML, 'Next page');
    assert.equal(f.S.timers.length, 0); assert.deepEqual([...f.intervals.keys()], intervals);
    assert.equal(f.requests.length, requestCount); assert.equal(postRequests(f).length, 0);
  }
});

test('Overview polling preserves position and deployment disclosures independently across reorder and removal', async () => {
  const rows = (deps, open, closed) => dashboardData({
    deployments: deps.map(id => ({...dashboardDeployment('paper'), id})),
    open_positions: open.map(id => dashboardPosition(id)), recent_closed: closed.map(id => dashboardPosition(id)),
  });
  let data = rows([11, 22], [11, 22], [11, 22]), reads = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); reads++; return response(data); }});
  await f.viewDashboard();
  const poll = f.intervals.get(f.S.timers.at(-1));
  const refresh = async next => { data = next; poll(); await flush(); };
  const opened = (selector, key) => f.root.querySelectorAll(selector).filter(detail => detail.open).map(detail => detail.dataset[key]).sort();
  const check = (deployments, positions) => {
    assert.deepEqual(opened('.dep-evidence', 'deployment'), deployments.slice().sort());
    assert.deepEqual(opened('.position-details', 'position'), positions.slice().sort());
  };
  const focusAfter = async (detail, next, find) => {
    const oldSummary = detail.querySelector('summary'); oldSummary.focus(); await refresh(next);
    const summary = find().querySelector('summary');
    assert.equal(oldSummary.isConnected, false); assert.notEqual(summary, oldSummary);
    assert.equal(f.document.activeElement, summary); assert.equal(summary.focusOptions.preventScroll, true);
  };
  assert.ok(f.root.querySelectorAll('.position-details').every(detail => detail.tag === 'details' && !detail.open));
  f.root.querySelector('#recent-settlements').open = true;
  evidenceFor(f.root, 11).open = true; positionFor(f.root, 'open-11').open = true; positionFor(f.root, 'closed-22').open = true;
  await focusAfter(positionFor(f.root, 'open-11'), rows([22, 11], [22, 11], [11, 22]), () => positionFor(f.root, 'open-11'));
  assert.deepEqual(f.root.querySelectorAll('.open-position .position-details').map(detail => detail.dataset.position), ['open-22', 'open-11']);
  check(['11'], ['open-11', 'closed-22']);
  evidenceFor(f.root, 11).open = false; evidenceFor(f.root, 22).open = true;
  await focusAfter(evidenceFor(f.root, 11), rows([11, 22], [11, 22], [22, 11]), () => evidenceFor(f.root, 11));
  assert.equal(evidenceFor(f.root, 11).open, false); check(['22'], ['open-11', 'closed-22']);
  positionFor(f.root, 'closed-22').open = false;
  await focusAfter(positionFor(f.root, 'closed-22'), rows([22, 11], [22, 33], [11, 22]), () => positionFor(f.root, 'closed-22'));
  assert.equal(positionFor(f.root, 'open-11'), null); assert.equal(positionFor(f.root, 'closed-11').open, false);
  assert.equal(positionFor(f.root, 'open-33').open, false); check(['22'], []);
  positionFor(f.root, 'closed-22').open = true;
  const removedSummary = positionFor(f.root, 'closed-22').querySelector('summary'); removedSummary.focus();
  await refresh(rows([11], [33, 22], [33, 11]));
  assert.equal(positionFor(f.root, 'closed-22'), null); assert.equal(evidenceFor(f.root, 22), null);
  assert.equal(removedSummary.isConnected, false); assert.equal(f.document.activeElement, f.document.body); check([], []);
  const outside = f.root.querySelector('.profile-trig'); outside.focus(); positionFor(f.root, 'open-33').open = true;
  await refresh(rows([22, 11], [11, 33], [22, 11]));
  assert.equal(f.document.activeElement, outside); check([], ['open-33']);
  assert.equal(positionFor(f.root, 'open-11').open, false); assert.equal(positionFor(f.root, 'closed-22').open, false);
  assert.equal(reads, 6); assert.equal(postRequests(f).length, 0);
});

test('Overview identifies all-paper groups and keeps every mode explicit in mixed open and settled books', async () => {
  let data, poll;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(data); }});
  for (const [openModes, closedModes] of [
    [['paper', 'paper'], ['paper', 'paper']],
    [['paper', 'demo', 'live'], ['live', 'paper', 'demo']],
    [['live'], ['paper']],
    [['paper'], ['live']],
  ]) {
    data = dashboardData({open_positions: openModes.map((mode, index) => dashboardPosition(index + 1, {mode})),
      recent_closed: closedModes.map((mode, index) => dashboardPosition(index + 1, {mode})),
      deployments: [dashboardDeployment('live')], live: {connected: true, balance: 3333}});
    if (!poll) { await f.viewDashboard(); poll = f.intervals.get(f.S.timers.at(-1)); }
    else { poll(); await flush(); }
    const ledger = f.root.querySelector('.positions-ledger'), history = ledger.querySelector('#recent-settlements');
    const heading = ledger.querySelector('h2'), allPaper = openModes.every(mode => mode === 'paper');
    assert.equal(heading.querySelector('.position-group-mode')?.textContent || '', allPaper ? 'Paper' : '');
    for (const [host, modes] of [[ledger, openModes], [history, closedModes]]) {
      const table = host.querySelector('table.t-positions'), labels = modes.map(mode => mode === 'live' ? 'LIVE' : mode === 'demo' ? 'Demo' : 'Paper');
      assert.equal(table.getAttribute('data-paper-only'), String(modes.every(mode => mode === 'paper')));
      assert.deepEqual(table.querySelectorAll('.position-mode').map(cell => cell.textContent), labels);
    }
    assert.equal(history.querySelector('summary .position-group-mode')?.textContent || '',
      closedModes.every(mode => mode === 'paper') ? 'Paper' : '');
    assert.equal(postRequests(f).length, 0);
  }
});

test('Overview paper context follows the whole displayed book through mode changes without obscuring source labels', async () => {
  const paperDeployment = Object.freeze(dashboardDeployment('paper'));
  const paperOpen = Object.freeze(dashboardPosition(1));
  const paperClosed = Object.freeze(dashboardPosition(2));
  const cases = [
    {name: 'paper book', shared: true},
    {name: 'connected live account without live records', shared: true, live: {connected: true, balance: 3333}},
    {name: 'paper running, paused and stopped', shared: true, deployments: ['running', 'paused', 'stopped'].map((status, i) => ({...dashboardDeployment('paper', status), id: 91 + i}))},
    {name: 'empty paper workspace', shared: true, deployments: [], open_positions: [], recent_closed: []},
    {name: 'active live deployment', shared: false, deployments: [dashboardDeployment('live')]},
    {name: 'stopped live deployment with paper primary', shared: false, deployments: [dashboardDeployment('live', 'stopped')]},
    ...['open_positions', 'recent_closed', 'deployments'].flatMap(field => ['live', 'demo', 'unknown', undefined].map(mode => ({
      name: `${field} ${mode ?? 'missing'} mode`, shared: false,
      [field]: [{...(field === 'deployments' ? paperDeployment : field === 'open_positions' ? paperOpen : paperClosed), mode}],
    }))),
    {name: 'return to paper book', shared: true},
  ];
  let data, poll, reads = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); reads++; return response(data); }});
  for (const {name, shared, ...overrides} of cases) {
    data = dashboardData({deployments: [paperDeployment], open_positions: [paperOpen], recent_closed: [paperClosed],
      paper: {daily: [{d: '2026-10-16', pnl: 1}, {d: '2026-10-17', pnl: 2}]}, ...overrides});
    for (const field of ['deployments', 'open_positions', 'recent_closed']) {
      data[field].forEach(Object.freeze); Object.freeze(data[field]);
    }
    Object.freeze(data.paper); Object.freeze(data.live); Object.freeze(data);
    const before = JSON.stringify(data);
    if (!poll) { await f.viewDashboard(); poll = f.intervals.get(f.S.timers.at(-1)); assert.equal(typeof poll, 'function'); }
    else { poll(); await flush(); }
    const dashboard = f.root.querySelector('.dash');
    assert.equal(dashboard.classList.contains('paper-workspace'), shared, name);
    const labels = dashboard.querySelectorAll('.position-mode');
    assert.deepEqual(labels.map(label => label.textContent), data.open_positions.concat(data.recent_closed)
      .map(row => row.mode === 'live' ? 'LIVE' : row.mode === 'demo' ? 'Demo' : 'Paper'), name + ' source mode labels remain available');
    const monitors = dashboard.querySelectorAll('.dep-monitor');
    monitors.forEach((monitor, index) => {
      const deployment = data.deployments[index], mode = monitor.querySelector('.monitor-mode');
      assert.equal(mode.textContent, deployment.mode === 'live' ? 'LIVE' : deployment.mode === 'demo' ? 'Demo' : 'Paper', name);
      assert.equal(mode.getAttribute('aria-hidden'), null, name);
      const state = monitor.querySelector('.monitor-state');
      assert.ok(state.textContent.endsWith(deployment.status === 'running' ? 'Running' : deployment.status === 'paused' ? 'Paused' : 'Stopped'), name);
      assert.equal(mode.contains(state.querySelector('.deployment-state')), false, name + ' status stays independent from mode');
    });
    const performanceMode = dashboard.querySelector('.performance-mode');
    assert.equal(performanceMode.textContent, 'Paper ·\u00a0cumulative', name + ' source performance scope remains available');
    assert.equal(performanceMode.querySelector('.performance-mode-prefix').textContent, 'Paper ·\u00a0', name);
    assert.equal(performanceMode.getAttribute('aria-hidden'), null, name);
    assert.equal(JSON.stringify(data), before, name + ' source records are immutable');
    assert.equal(postRequests(f).length, 0, name);
  }
  assert.equal(reads, cases.length);
});

test('Overview contract identities use the catalog and expiry while keeping raw tickers and safe fallbacks', async () => {
  const samples = [
    {ticker: 'KXBTC15M-26OCT181230-B105000', title: 'Strategy <script>unsafe</script>', label: 'Bitcoin', known: true, expiry: true},
    {ticker: 'KXRAIN-26OCT18-T1', label: 'Rainfall index', known: true, expiry: true},
    {ticker: 'KXBTC15M-26OCT181230-B106000', market_close_time: 'not-a-date', label: 'Bitcoin', known: true, expiry: false},
    {ticker: 'KXBTC15MPLUS-26OCT18-T1', label: 'KXBTC15MPLUS-26OCT18-T1', known: false, expiry: true},
    {ticker: 'UNKNOWN<script>unsafe</script>', market_close_time: 'not-a-date', label: 'UNKNOWN&lt;script&gt;unsafe&lt;/script&gt;', known: false, expiry: false},
    {ticker: 'OTHER-SERIES', market_close_time: null, label: 'OTHER-SERIES', known: false, expiry: false},
  ];
  const openedAt = new Date(Date.now() - 120000).toISOString();
  const positions = samples.map(({label, known, expiry, ...fields}, index) => dashboardPosition(index + 1, {opened_at: openedAt, ...fields}));
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData({open_positions: positions})); }});
  f.S.me.markets = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin'},
    {key: 'rainfall_fixture', series: 'KXRAIN', label: 'Rainfall index'}];
  await f.viewDashboard();
  const rows = f.root.querySelectorAll('.open-position'); assert.equal(rows.length, samples.length);
  const headers = f.root.querySelector('.t-positions thead tr').querySelectorAll('th');
  assert.deepEqual(headers.map(th => th.textContent), ['Market / contract', 'Position', 'Expiry', 'Entry', 'Cost', 'Unrealized P&amp;L']);
  assert.ok(headers.every(th => th.getAttribute('scope') === 'col'));
  samples.forEach((sample, index) => {
    const row = rows[index], detail = row.querySelector('.position-details'), summary = detail.querySelector('summary');
    const market = summary.querySelector('.position-market'), secondary = detail.querySelector('.sub-fig');
    assert.equal(detail.tag, 'details'); assert.equal(detail.open, false); assert.equal(detail.dataset.position, `open-${index + 1}`);
    assert.equal(summary.contains(secondary), false); assert.equal(secondary.querySelector('.position-opened').textContent, 'Opened 2m ago');
    if (sample.known) assert.ok(market.textContent.startsWith(sample.label), sample.ticker);
    else assert.equal(market, null);
    if (sample.expiry) {
      const date = new Date(positions[index].market_close_time).toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
      assert.ok(row.querySelector('.position-expiry-cell time').textContent.includes(date), sample.ticker + ' expiry');
      assert.equal(row.querySelector('.position-expiry-cell time').getAttribute('datetime'), new Date(positions[index].market_close_time).toISOString());
      const absolute = new Date(positions[index].market_close_time).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'long', hourCycle: 'h23'});
      assert.equal(secondary.querySelector('.position-absolute').textContent, 'Expires ' + absolute);
    } else { assert.equal(row.querySelector('.position-expiry-cell time'), null); assert.equal(row.querySelector('.position-expiry-cell .vh').textContent, 'Expiry unavailable'); assert.equal(secondary.querySelector('.position-absolute'), null); }
    assert.ok(secondary.textContent.includes(sample.known ? sample.ticker : sample.label), sample.ticker + ' raw identifier');
    const contractCell = row.querySelectorAll('td')[0];
    assert.equal(contractCell.querySelector('.position-contract').textContent, sample.known ? sample.ticker : sample.label);
    assert.equal(summary.contains(contractCell.querySelector('.position-contract')), true, 'full raw contract remains in the native visible identity summary');
    assert.ok(summary.getAttribute('aria-label').includes(sample.known ? sample.ticker : sample.label));
    const sourceStrategy = index === 0 ? 'Strategy &lt;script&gt;unsafe&lt;/script&gt;' : `Strategy ${index + 1}`;
    assert.equal(summary.querySelector('.position-title').textContent, sourceStrategy, 'show the actual strategy independently from the full raw contract');
    assert.ok(summary.getAttribute('aria-label').includes(sourceStrategy));
    const sizeCell = row.querySelectorAll('td')[1];
    assert.equal(sizeCell.querySelector('.position-side').textContent, positions[index].side.toUpperCase(), 'side remains in its native Position cell');
    assert.equal(sizeCell.querySelector('.position-quantity').textContent, 'Quantity ' + positions[index].qty, 'exact size remains labelled in its native Position cell');
    assert.equal(summary.contains(sizeCell), false);
    assert.ok(secondary.textContent.includes(sourceStrategy));
    assert.doesNotMatch(row.innerHTML, /<script>|Invalid Date|NaN/);
  });
  assert.equal(postRequests(f).length, 0);
});

test('Overview rowgroups remove repeated catalog labels without merging nonadjacent families or changing position order', async () => {
  const rows = Object.freeze([
    Object.freeze(dashboardPosition(1, {ticker: 'BTC-A', deployment_id: 11, title: 'Shared strategy'})),
    Object.freeze(dashboardPosition(2, {ticker: 'BTC-B', side: 'no', deployment_id: 11, title: 'Shared strategy'})),
    Object.freeze(dashboardPosition(3, {ticker: 'RAIN-A', deployment_id: 11, title: 'Shared strategy'})),
    Object.freeze(dashboardPosition(4, {ticker: 'BTC-C', mode: 'live', deployment_id: 11, title: 'Shared strategy'})),
    Object.freeze(dashboardPosition(5, {ticker: 'UNKNOWN-A', unrealized: 0})),
  ]);
  const catalog = Object.freeze([Object.freeze({key: 'btc15m', series: 'BTC', label: 'Bitcoin'}),
    Object.freeze({key: 'rain', series: 'RAIN', label: 'Rainfall'})]);
  const before = JSON.stringify({rows, catalog});
  const f = frontend({fetchImpl: () => response(dashboardData({open_positions: rows}))});
  f.S.me.markets = catalog; await f.viewDashboard();
  const table = f.root.querySelector('.t-positions'), bodies = table.querySelectorAll('tbody');
  assert.deepEqual(bodies.map(body => body.querySelector('.position-family-name')?.textContent || ''), ['Bitcoin', 'Rainfall', 'Bitcoin', '']);
  assert.deepEqual(bodies.map(body => body.querySelector('.position-strategy').textContent),
    [rows[0].title, rows[2].title, rows[3].title, rows[4].title]);
  assert.deepEqual(table.querySelectorAll('.position-family th').map(th => th.getAttribute('scope')), ['rowgroup', 'rowgroup', 'rowgroup', 'rowgroup']);
  assert.deepEqual(table.querySelectorAll('.position-family th').map(th => th.getAttribute('colspan')), ['6', '6', '6', '6']);
  assert.deepEqual(table.querySelectorAll('.open-position .position-details').map(detail => detail.dataset.position), ['open-1', 'open-2', 'open-3', 'open-4', 'open-5']);
  assert.deepEqual(bodies.map(body => body.querySelectorAll('.open-position').length), [2, 1, 1, 1]);
  assert.equal(table.querySelectorAll('.open-position').at(-1).querySelector('.position-contract').textContent, 'UNKNOWN-A');
  assert.equal(table.querySelectorAll('.open-position').at(-1).querySelector('.position-market'), null);
  assert.equal(table.querySelectorAll('.position-pnl').at(-1).textContent, '$0.00');
  assert.equal(JSON.stringify({rows, catalog}), before); assert.equal(postRequests(f).length, 0);
});

test('Overview attribution groups require adjacent known deployments and keep title, mode, family and unknown IDs distinct', async () => {
  const alpha = 'Alpha', beta = 'Beta <script>unsafe</script>';
  const rows = Object.freeze([
    [1, 71, alpha, 'BTC-A', 'paper'], [2, 71, alpha, 'BTC-B', 'paper'],
    [3, 72, alpha, 'BTC-C', 'paper'], [4, 72, alpha, 'BTC-D', 'live'],
    [5, 72, beta, 'BTC-E', 'live'], [6, 72, beta, 'RAIN-A', 'live'],
    [7, 71, alpha, 'BTC-F', 'paper'],
    [8, undefined, alpha, 'BTC-G', 'paper'], [9, undefined, alpha, 'BTC-H', 'paper'],
    [10, null, alpha, 'BTC-I', 'paper'], [11, null, alpha, 'BTC-J', 'paper'],
    [12, 71, alpha, 'UNKNOWN-A', 'paper'], [13, 71, alpha, 'UNKNOWN-B', 'paper'],
    [14, '9007199254740993', alpha, 'BTC-K', 'paper'],
    [15, '9007199254740993', alpha, 'BTC-L', 'paper'],
    [16, '9007199254740994', alpha, 'BTC-M', 'paper'],
  ].map(([id, deployment_id, title, ticker, mode]) => Object.freeze(
    dashboardPosition(id, {deployment_id, title, ticker, mode}))));
  const catalog = Object.freeze([
    Object.freeze({key: 'btc15m', series: 'BTC', label: 'Bitcoin'}),
    Object.freeze({key: 'rain', series: 'RAIN', label: 'Rainfall'}),
  ]);
  const before = JSON.stringify({rows, catalog});
  const f = frontend({fetchImpl: () => response(dashboardData({open_positions: rows}))});
  f.S.me.markets = catalog; await f.viewDashboard();
  const table = f.root.querySelector('.t-positions'), groups = table.querySelectorAll('tbody');
  const expected = [[1, 2], [3], [4], [5], [6], [7], [8], [9], [10], [11], [12], [13], [14, 15], [16]];
  assert.deepEqual(groups.map(group => group.querySelectorAll('.open-position .position-details')
    .map(detail => Number(detail.dataset.position.slice('open-'.length)))), expected);
  assert.deepEqual(table.querySelectorAll('.position-contract').map(el => el.textContent), rows.map(row => row.ticker));
  groups.forEach((group, index) => {
    const source = rows.find(row => row.id === expected[index][0]);
    const header = group.querySelector('th[scope="rowgroup"]');
    assert.ok(header, 'every attribution group has a native associated header');
    assert.equal(header.getAttribute('colspan'), '6');
    assert.ok(header.textContent.includes(source.title === beta ? 'Beta &lt;script&gt;unsafe&lt;/script&gt;' : alpha));
    if (source.id === 12 || source.id === 13) assert.equal(header.querySelector('.position-family-name'), null);
    else assert.ok(header.textContent.includes(source.id === 6 ? 'Rainfall' : 'Bitcoin'));
    group.querySelectorAll('.position-details').forEach(detail => {
      assert.ok(detail.querySelector('summary').getAttribute('aria-label').includes(source.title === beta
        ? 'Beta &lt;script&gt;unsafe&lt;/script&gt;' : alpha));
      assert.ok(detail.querySelector('summary').getAttribute('aria-label')
        .endsWith(source.mode === 'live' ? ' ·\u00a0LIVE' : ' ·\u00a0Paper'));
    });
  });
  assert.doesNotMatch(table.innerHTML, /<script>/);
  assert.equal(JSON.stringify({rows, catalog}), before);
  assert.equal(postRequests(f).length, 0);
});

test('Overview separates open cost and unrealized marks from collapsed realized settlements', async () => {
  const open = [dashboardPosition(1, {mode: 'live', unrealized: 2.5}),
    dashboardPosition(2, {side: 'no', qty: 4, entry_price: 0.25, mode: 'demo', pnl: 199}),
    dashboardPosition(3, {qty: 2, entry_price: 0.75, unrealized: 0})];
  const settled = dashboardPosition(4, {mode: 'demo', pnl: -4.25, unrealized: 999});
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData({open_positions: open, recent_closed: [settled]})); }});
  await f.viewDashboard();
  const history = f.root.querySelector('#recent-settlements'), rows = f.root.querySelectorAll('.open-position');
  assert.equal(history.tag, 'details'); assert.equal(history.open, false); assert.equal(rows.length, 3);
  const costs = ['$3.50', '$1.00', '$1.50'], marks = ['+$2.50', '—Unavailable', '$0.00'], modes = ['LIVE', 'Demo', 'Paper'];
  rows.forEach((row, index) => {
    const cells = row.querySelectorAll('td');
    assert.equal(cells.length, 6);
    assert.equal(cells[0].querySelector('.position-title').textContent, open[index].title);
    assert.equal(cells[0].querySelector('.position-contract').textContent, open[index].ticker);
    assert.equal(cells[1].querySelector('.position-side').textContent, open[index].side.toUpperCase());
    assert.equal(cells[1].querySelector('.position-quantity').textContent, `Quantity ${open[index].qty}`);
    assert.equal(history.contains(row), false);
    assert.equal(row.querySelector('.position-mode').textContent, modes[index]);
    assert.equal(row.querySelector('.position-cost').textContent, costs[index]);
    assert.equal(row.querySelector('.position-pnl').textContent, marks[index]);
    assert.ok(row.querySelector('.position-opened').textContent);
  });
  assert.equal(rows[1].querySelector('.position-side').textContent, 'NO');
  assert.equal(rows[1].querySelector('.position-quantity').textContent, 'Quantity 4');
  assert.equal(rows[1].querySelector('.position-entry').textContent, '25¢');
  assert.equal(rows[1].querySelector('.unavailable .vh').textContent, 'Unavailable');
  assert.equal(rows[1].querySelector('.unavailable').getAttribute('title'), 'Unrealized P&amp;L unavailable');
  assert.equal(rows[1].querySelector('.position-mark-note').textContent, 'Unrealized P&amp;L unavailable');
  assert.doesNotMatch(rows[1].innerHTML, /\$199\.00/);
  const closedRow = history.querySelector('.settled-position'), cells = closedRow.querySelectorAll('td');
  assert.equal(cells.length, 5);
  assert.equal(cells[0].querySelector('.position-title').textContent, settled.title);
  assert.equal(cells[0].querySelector('.position-contract').textContent, settled.ticker);
  assert.equal(cells[1].querySelector('.position-side').textContent, settled.side.toUpperCase());
  assert.equal(cells[1].querySelector('.position-quantity').textContent, `Quantity ${settled.qty}`);
  assert.deepEqual(history.querySelectorAll('thead th').map(th => th.textContent), ['Market / contract', 'Position', 'Expiry', 'Entry', 'Realized P&amp;L']);
  assert.equal(closedRow.querySelector('.position-cost'), null);
  const closedDetail = closedRow.querySelector('.position-details');
  assert.equal(closedDetail.tag, 'details'); assert.equal(closedDetail.open, false); assert.equal(closedDetail.dataset.position, 'closed-4');
  assert.ok(closedDetail.querySelector('.sub-fig').textContent.includes(settled.ticker + ' ·\u00a0' + settled.title));
  assert.match(closedDetail.querySelector('.position-opened').textContent, /^Closed /);
  assert.equal(closedDetail.querySelector('.position-absolute').textContent,
    'Expires ' + new Date(settled.market_close_time).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'long', hourCycle: 'h23'}));
  assert.equal(closedRow.querySelector('.position-mode').textContent, 'Demo');
  assert.equal(closedRow.querySelector('.position-pnl').textContent, '−$4.25');
  assert.ok(closedRow.querySelector('.position-opened').textContent); assert.doesNotMatch(closedRow.innerHTML, /\$999\.00/);
  assert.equal(f.root.querySelectorAll('.settled-position').length, 1);
  assert.equal(postRequests(f).length, 0);
});

test('Overview settlements preserve disclosure state and focus during polling and safely disappear with history', async () => {
  const openPosition = dashboardPosition(1), settled = dashboardPosition(2);
  let data = dashboardData({open_positions: [openPosition], recent_closed: [settled]}), reads = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); reads++; return response(data); }});
  await f.viewDashboard();
  let history = f.root.querySelector('#recent-settlements'); assert.equal(history.open, false);
  const poll = f.intervals.get(f.S.timers.at(-1));
  for (const [expanded, pnl] of [[true, 6.5], [false, -2.75]]) {
    history.open = expanded;
    const oldSummary = history.querySelector('summary'); oldSummary.focus();
    data = dashboardData({open_positions: [openPosition], recent_closed: [{...settled, pnl}]});
    poll(); await flush();
    const next = f.root.querySelector('#recent-settlements'), summary = next.querySelector('summary');
    assert.notEqual(next, history); assert.equal(oldSummary.isConnected, false); assert.equal(next.open, expanded);
    assert.equal(f.document.activeElement, summary); assert.equal(summary.focusOptions.preventScroll, true);
    assert.equal(next.querySelector('.settled-position .position-pnl').textContent, pnl > 0 ? '+$6.50' : '−$2.75');
    assert.equal(f.root.querySelectorAll('.open-position').length, 1); history = next;
  }
  const outside = f.root.querySelector('.profile-trig'); outside.focus(); history.open = true;
  poll(); await flush();
  history = f.root.querySelector('#recent-settlements'); assert.equal(history.open, true); assert.equal(f.document.activeElement, outside);
  history.querySelector('summary').focus();
  data = dashboardData({open_positions: [openPosition]}); poll(); await flush();
  assert.equal(f.root.querySelector('#recent-settlements'), null); assert.equal(f.document.activeElement, f.document.body);
  assert.equal(f.root.querySelectorAll('.open-position').length, 1);
  outside.focus(); data = dashboardData({open_positions: [openPosition], recent_closed: [settled]}); poll(); await flush();
  assert.equal(f.root.querySelector('#recent-settlements').open, false); assert.equal(f.document.activeElement, outside);
  assert.equal(reads, 6); assert.equal(postRequests(f).length, 0);
});

test('Overview chooses the correct primary money bucket and preserves disconnected, unavailable and zero balances', async () => {
  for (const [label, overrides, livePrimary, primaryBalance, secondaryLive] of [
    ['disconnected', {}, false, '$1,111.25', 'Not connected'],
    ['connected without live deployment', {live: {connected: true, balance: 3333}}, false, '$1,111.25', '$3,333.00'],
    ['balance read failed without live deployment', {live: {connected: true}}, false, '$1,111.25', 'Unavailable'],
    ['demo deployment', {deployments: [dashboardDeployment('demo')]}, false, '$1,111.25', 'Not connected'],
    ['stopped live deployment', {deployments: [dashboardDeployment('live', 'stopped')]}, false, '$1,111.25', 'Not connected'],
    ['running live deployment', {deployments: [dashboardDeployment('live')], live: {connected: true, balance: 3333}}, true, '$3,333.00'],
    ['paused live deployment', {deployments: [dashboardDeployment('live', 'paused')], live: {connected: true, balance: 3333}}, true, '$3,333.00'],
    ['zero live cash', {deployments: [dashboardDeployment('live')], live: {connected: true, balance: 0}}, true, '$0.00'],
    ['live key disconnected', {deployments: [dashboardDeployment('live')]}, true, 'Not connected'],
    ['live balance read failed', {deployments: [dashboardDeployment('live')], live: {connected: true}}, true, 'Unavailable'],
  ]) {
    const data = dashboardData(overrides), f = frontend({fetchImpl: path => {
      assert.equal(path, '/api/dashboard'); return response(data);
    }});
    await f.viewDashboard();
    const primary = f.root.querySelector('.dashboard-figures'), accounts = f.root.querySelector('#other-accounts');
    assert.equal(primary.classList.contains('live-primary'), livePrimary, label);
    assert.equal(primary.querySelector('.lab').textContent, livePrimary ? 'Kalshi cash' : 'Paper portfolio', label);
    assert.equal(primary.querySelector('.fig').textContent, primaryBalance, label);
    assert.equal(accounts.tag, 'details'); assert.equal(accounts.open, false);
    assert.deepEqual(accounts.querySelectorAll('dt.lab').map(lab => lab.textContent),
      [livePrimary ? 'Paper portfolio' : 'Kalshi cash', 'Demo balance'], label);
    assert.equal(accounts.contains(f.root.querySelector('.paper-summary')), livePrimary, label);
    if (!livePrimary) assert.equal(accounts.querySelector('.fig').textContent, secondaryLive, label);
    const paper = f.root.querySelector('.paper-summary');
    for (const amount of ['$1,111.25', '+$111.25', '−$7.50', '$900.00', '$211.25']) assert.ok(paper.textContent.includes(amount), label + ' paper ' + amount);
    assert.match(accounts.textContent, /\$2,222\.50/); assert.match(accounts.textContent, /\$2,200\.00 capital/);
    const liveHost = livePrimary ? primary : accounts;
    if (!data.live.connected) assert.equal(liveHost.querySelector('a').getAttribute('href'), '/funds', label);
    if (data.live.connected && data.live.balance == null) assert.match(liveHost.textContent, /read your Kalshi balance/, label);
    if (livePrimary) {
      for (const amount of ['−$2.00', '$50.00']) assert.ok(primary.textContent.includes(amount), label + ' live ' + amount);
      if (data.live.connected && data.live.balance != null) assert.ok(primary.textContent.includes('+$17.00'), label + ' realized live P&L');
    }
    assert.equal(postRequests(f).length, 0);
  }
});

test('Overview Accounts preserves open and focused summaries across polling and changing the primary account', async () => {
  let data = dashboardData({live: {connected: true, balance: 3333}}), reads = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); reads++; return response(data); }});
  await f.viewDashboard();
  const poll = f.intervals.get(f.S.timers.at(-1));
  let accounts = f.root.querySelector('#other-accounts');
  assert.equal(accounts.open, false);
  for (const [open, livePrimary] of [[true, true], [false, false]]) {
    accounts.open = open;
    const oldSummary = accounts.querySelector('summary'); oldSummary.focus();
    data = dashboardData({live: {connected: true, balance: 4444},
      deployments: livePrimary ? [dashboardDeployment('live')] : []});
    poll(); await flush();
    const next = f.root.querySelector('#other-accounts'), summary = next.querySelector('summary');
    assert.notEqual(next, accounts); assert.equal(oldSummary.isConnected, false); assert.equal(next.open, open);
    assert.equal(f.document.activeElement, summary); assert.equal(summary.focusOptions.preventScroll, true);
    assert.equal(f.root.querySelector('.dashboard-figures').classList.contains('live-primary'), livePrimary);
    assert.match((livePrimary ? f.root.querySelector('.dashboard-figures') : next).textContent, /\$4,444\.00/);
    accounts = next;
  }
  const outside = f.root.querySelector('.profile-trig'); outside.focus(); accounts.open = true;
  poll(); await flush();
  assert.equal(f.root.querySelector('#other-accounts').open, true); assert.equal(f.document.activeElement, outside);
  assert.equal(reads, 4); assert.equal(postRequests(f).length, 0);
});

test('the OAuth account return and Funds routes open the current funds page', () => {
  const f = frontend();
  const route = path => f.routes.find(([pattern]) => pattern.test(path))?.[1];
  assert.equal(route('/funds'), f.viewFunds); assert.equal(route('/settings/account'), f.viewFunds);
  assert.notEqual(route('/settings'), f.viewFunds);
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
  assert.equal(hypothesis.querySelector('[data-stamp]').textContent, 'Passed');
  assert.equal(hypothesis.querySelectorAll('a[href="/strategies/42"]').length, 1);
  assert.equal(hypothesis.querySelector('.say-title a').getAttribute('href'), '/strategies/42');
  stream.state('paused'); assert.equal(log.children[1], hypothesis);
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
  assert.ok(f.root.querySelector('#resume')); assert.equal(f.root.querySelector('#runpulse'), null);
});

test('a Research run queued or silent past the reaper limit says how long instead of Queued', async () => {
  const at = (wait, status = 'queued') => {
    const run = {id: 9, prompt: 'Idea', status, market: 'btc15m', created_at: '2026-10-17T10:00:00Z', wait};
    return frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: []}); }});
  };
  let f = at({state: 'queued', seconds: 90, overdue: false});
  await f.viewRun(9);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Queued');
  assert.equal(f.root.querySelector('#rsiobs [data-wait]').hidden, true);
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').hidden, false);
  f.clearTimers();
  f = at({state: 'queued', seconds: 540, overdue: true, ahead: 1});
  await f.viewRun(9);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Waiting 9 min/);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Waiting 9 min');
  const wait = f.root.querySelector('#rsiobs [data-wait]');
  assert.equal(wait.hidden, false);
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').hidden, true);  // no "Waiting for the agent to start." above it
  assert.equal(wait.textContent, 'Still waiting for a free research worker (9 min). 1 session is ahead of it; it starts when one frees up.');
  f.clearTimers();
  f = at({state: 'silent', seconds: 300, overdue: true}, 'running');
  await f.viewRun(9);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Silent 5 min/);
  assert.equal(f.root.querySelector('#rsiobs [data-wait]').textContent, 'No word from the agent for 5 min. A session this quiet is normally interrupted and resumed from its last checkpoint.');
  f.clearTimers();
});

test('opening a terminal Research run seals hydrated thoughts and keeps native history inspectable without polling', async () => {
  for (const status of ['succeeded', 'failed', 'cancelled']) {
    const run = researchRun(9, status), events = [{id: 1, kind: 'thinking', message: 'Saved **reasoning** <script>unsafe</script>', data: {block: 1}, created_at: run.created_at}];
    let reads = 0;
    const f = frontend({fetchImpl: path => { reads++; assert.equal(path, '/api/runs/9?after=0'); return response({run, events}); }});
    await f.viewRun(9);
    assert.equal(reads, 1); assert.equal(f.S.timers.length, 0);
    const progress = f.root.querySelector('#rsiobs .rsi-progress'), history = f.root.querySelector('#run-history');
    for (const details of [progress, history]) { assert.equal(details.tag, 'details'); assert.equal(details.open, false); details.open = true; }
    assert.equal(f.root.querySelector('#rsiobs [data-phase]').hidden, true);
    assert.equal(f.root.querySelector('#runfeed').classList.contains('is-complete'), true);
    const thought = history.querySelector('.think'); assert.equal(thought.classList.contains('sealed'), true);
    assert.match(thought.querySelector('[data-body]').innerHTML, /Saved <b>reasoning<\/b> &lt;script&gt;unsafe&lt;\/script&gt;/);
    assert.ok(f.root.querySelector('#rsiobs .rsi-labels')); assert.equal(f.root.querySelector('#cancel'), null);
    if (status === 'succeeded') assert.equal(f.root.querySelector('#runact a').getAttribute('href'), '/strategies');
    assert.equal(progress.open, true); assert.equal(history.open, true);
    assert.equal(postRequests(f).length, 0); assert.deepEqual(f.navigations, []);
  }
});

test('Research results keep every returned status and source value with escaped links and stable focus across polling changes', async () => {
  const strategies = [
    detailStrategy({id: 11, status: 'passed', title: 'Kept <script>unsafe</script>', shared_from: '<img src=x>', out_of_sample: metrics(12)}),
    detailStrategy({id: 12, status: 'failed', title: 'Void & loss', out_of_sample: metrics(-4.25)}),
    detailStrategy({id: 13, status: 'rejected', out_of_sample: null, in_sample: metrics(-7.5)}),
    detailStrategy({id: 14, status: 'backtest-only', out_of_sample: null, in_sample: metrics(0)}),
    detailStrategy({id: 15, status: 'queued', out_of_sample: null, in_sample: {}}),
  ];
  strategies.forEach(s => { Object.freeze(s.in_sample); Object.freeze(s.out_of_sample); Object.freeze(s); }); Object.freeze(strategies);
  const before = JSON.stringify(strategies), run = researchRun(9, 'running'); let payload = {run, events: [], strategies};
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/runs/9?after=0'); return response(payload); }});
  await f.viewRun(9);
  const results = f.root.querySelector('#run-artifacts'), poll = f.intervals.get(f.S.timers.at(-1));
  assert.equal(results.hidden, false); assert.equal(results.querySelector('.section-count').textContent, '5');
  const rows = results.querySelectorAll('tbody tr'); assert.equal(rows.length, 5);
  assert.deepEqual(rows.map(row => row.querySelector('.act .mk').textContent), ['Passed', 'Void', 'Rejected', 'Backtest only', 'Testing']);
  assert.deepEqual(rows.map(row => row.querySelector('.num').textContent), ['+$12.00', '−$4.25', '−$7.50tested only', '$0.00tested only', '—tested only']);
  assert.deepEqual(rows.map(row => row.querySelector('.num').getAttribute('data-lab')), ['Backtest P&amp;L (unseen)', 'Backtest P&amp;L (unseen)', 'Backtest P&amp;L (tested)', 'Backtest P&amp;L (tested)', 'Backtest P&amp;L (tested)']);
  assert.match(results.innerHTML, /Kept &lt;script&gt;unsafe&lt;\/script&gt;/); assert.match(results.innerHTML, /&lt;img src=x&gt;/);
  assert.doesNotMatch(results.innerHTML, /<script>|<img|data-dep|class="pick"/);
  const originalLink = results.querySelector('a[href="/strategies/12"]'); originalLink.focus();
  payload = {...payload, strategies: [...strategies].reverse()}; poll(); await flush();
  const reorderedLink = results.querySelector('a[href="/strategies/12"]');
  assert.notEqual(reorderedLink, originalLink); assert.equal(originalLink.isConnected, false);
  assert.equal(f.document.activeElement, reorderedLink); assert.equal(reorderedLink.focusOptions.preventScroll, true);
  assert.deepEqual(results.querySelectorAll('tbody .name a').map(a => a.getAttribute('href')), [15, 14, 13, 12, 11].map(id => `/strategies/${id}`));
  payload = {...payload, strategies: strategies.filter(s => s.id !== 12)}; poll(); await flush();
  assert.equal(reorderedLink.isConnected, false); assert.equal(f.document.activeElement, f.document.body);
  const outside = f.root.querySelector('.profile-trig'); outside.focus();
  payload = {run, events: []}; poll(); await flush();
  assert.equal(results.hidden, true); assert.equal(results.querySelectorAll('a').length, 0); assert.equal(f.document.activeElement, outside);
  assert.equal(JSON.stringify(strategies), before); assert.equal(postRequests(f).length, 0); assert.deepEqual(f.navigations, []);
  assert.deepEqual([...new Set(f.requests.map(request => request.path))].sort(), ['/api/notifications', '/api/runs/9?after=0']);
});

test('active Research polls and completion retain native disclosure choice, focus, streamed history and a working pending jump', async () => {
  for (const [historyOpen, progressOpen, focusHistory] of [[false, true, true], [true, false, false], [true, true, false]]) {
    const event = (id, kind, message, data = {}) => ({id, kind, message, data, created_at: '2026-10-17T10:00:00Z'});
    let cursor = 0, payload = {run: researchRun(9, 'running'), events: [event(1, 'thinking', 'Initial reasoning', {block: 1})]};
    const f = frontend({fetchImpl: path => { assert.equal(path, `/api/runs/9?after=${cursor}`); return response(payload); }});
    await f.viewRun(9); cursor = 1;
    const history = f.root.querySelector('#run-history'), progress = f.root.querySelector('#rsiobs .rsi-progress');
    const log = history.querySelector('#log'), jump = history.querySelector('#jumplatest');
    assert.equal(history.open, true); assert.equal(progress.open, true);
    history.open = historyOpen; progress.open = progressOpen;
    const summary = (focusHistory ? history : progress).querySelector('summary'); summary.focus();
    const pollId = f.S.timers.at(-1), poll = f.intervals.get(pollId); assert.equal(typeof poll, 'function');
    log.scrollHeight = 1000; log.clientHeight = 200; log.scrollTop = 100;
    payload = {run: researchRun(9, 'running'), events: [event(2, 'step', 'Retained raw step'), event(3, 'thinking', 'Final **draft** <unsafe>', {block: 2})]};
    poll(); await flush(); cursor = 3;
    assert.equal(history.open, historyOpen); assert.equal(progress.open, progressOpen); assert.equal(f.document.activeElement, summary);
    assert.equal(jump.hidden, false); assert.equal(jump.textContent, '2 new ↓'); assert.equal(log.scrollTop, 100);
    const entries = log.children.filter(entry => !entry.removed); assert.equal(entries.length, 3);
    assert.match(entries.at(-1).querySelector('[data-body]').innerHTML, /Final <b>draft<\/b> &lt;unsafe&gt;/);
    const runTimers = [...f.S.timers]; payload = {run: researchRun(9, 'succeeded'), events: []}; poll(); await flush();
    assert.equal(f.root.querySelector('#run-history'), history); assert.equal(f.root.querySelector('#rsiobs .rsi-progress'), progress);
    assert.equal(history.open, historyOpen); assert.equal(progress.open, progressOpen); assert.equal(f.document.activeElement, summary);
    assert.deepEqual(log.children.filter(entry => !entry.removed), entries); assert.equal(entries.at(-1).classList.contains('sealed'), true);
    assert.equal(f.root.querySelector('#runfeed').classList.contains('is-complete'), false);
    assert.equal(log.scrollTop, 100); assert.equal(jump.hidden, false);
    jump.onclick(); assert.equal(log.scrollTop, 1000); assert.equal(jump.hidden, true);
    assert.equal(f.S.timers.length, 0); assert.ok(runTimers.every(id => !f.intervals.has(id))); assert.equal(f.intervals.has(pollId), false);
    assert.equal(postRequests(f).length, 0); assert.deepEqual(f.navigations, []);
  }
});

test('Research run polling keeps one current stage through unknown events, pause, repeat and completion with lineage intact', async () => {
  let payload, cursor = 0, poll, pollId;
  const f = frontend({fetchImpl: path => {
    assert.equal(path, `/api/runs/9?after=${cursor}`); return response(payload);
  }});
  const event = (id, kind, message = kind, data = {}, created_at = new Date().toISOString()) => ({id, kind, message, data, created_at});
  const advance = async (status, events, active, done) => {
    payload = {run: researchRun(9, status), events};
    const before = JSON.stringify(events);
    if (!poll) { await f.viewRun(9); pollId = f.S.timers.at(-1); poll = f.intervals.get(pollId); }
    else { poll(); await flush(); }
    cursor = Math.max(cursor, ...events.map(ev => ev.id));
    const labels = f.root.querySelectorAll('#rsiobs .rsi-lab');
    for (const label of labels) {
      assert.equal(label.classList.contains('is-active'), label.dataset.stage === active, label.dataset.stage);
      assert.equal(label.getAttribute('aria-current'), label.dataset.stage === active ? 'step' : null, label.dataset.stage);
      assert.equal(label.classList.contains('is-done'), done.includes(label.dataset.stage), label.dataset.stage);
    }
    assert.equal(labels.filter(label => label.getAttribute('aria-current') !== null).length, active ? 1 : 0);
    assert.equal(JSON.stringify(events), before);
  };
  await advance('queued', [], null, []);
  const stages = f.root.querySelector('#rsiobs .rsi-labels');
  assert.equal(stages.tag, 'ol'); assert.deepEqual(stages.querySelectorAll('li').map(label => label.textContent), ['Explore', 'Backtest', 'Validate', 'Refine']);
  assert.equal(f.root.querySelector('.run-header > #runact'), f.root.querySelector('#runact'));
  const passed = () => f.root.querySelectorAll('#runfigs .m').find(fig => fig.querySelector('dt').textContent === 'Passed').querySelector('.fig').textContent;
  assert.equal(passed(), '0');
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Queued');
  assert.equal(f.root.querySelector('#rsiobs [data-tree]').hidden, true);
  await advance('running', [event(1, 'run-start', 'Starting', {}, new Date(Date.now() - 90000).toISOString())], 'explore', []);
  assert.equal(f.root.querySelector('#rsiobs').classList.contains('is-quiet'), true);
  assert.match(f.root.querySelector('#rsiobs [data-livetext]').textContent, /^Last event \d+m ago$/);
  await advance('running', [event(2, 'new_backend_phase', 'Future phase')], 'explore', []);
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').textContent, 'New backend phase');
  assert.equal(f.root.querySelector('#rsiobs').classList.contains('is-quiet'), false);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Just updated');
  await advance('running', [event(3, 'hypothesis', 'Parent <script>unsafe</script>', {hyp_id: 'parent'}),
    event(4, 'hypothesis', 'Child', {hyp_id: 'child', parent_id: 'parent'})], 'backtest', ['explore']);
  const tree = f.root.querySelector('#rsiobs [data-tree]'), treeSvg = tree.querySelector('[data-treesvg]');
  assert.equal(tree.hidden, false); assert.equal(treeSvg.querySelectorAll('.rsi-tnode').length, 2);
  assert.equal(treeSvg.querySelectorAll('.rsi-tedge').length, 1);
  assert.match(treeSvg.innerHTML, /Parent &lt;script&gt;unsafe&lt;\/script&gt;/); assert.doesNotMatch(treeSvg.innerHTML, /<script>/);
  await advance('running', [event(5, 'gating')], 'gate', ['explore', 'backtest']);
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').textContent, 'Gating on unseen data');
  await advance('paused', [], null, ['explore', 'backtest', 'gate']);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Paused'); assert.ok(f.root.querySelector('#resume'));
  await advance('running', [], 'gate', ['explore', 'backtest']);
  assert.ok(f.root.querySelector('#pause'));
  await advance('running', [event(6, 'note', 'Dreaming: testing a better policy')], 'dream', ['explore', 'backtest', 'gate']);
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').textContent, 'Tuning how it searches');
  await advance('running', [event(7, 'proposing')], 'explore', ['backtest', 'gate', 'dream']);
  await advance('succeeded', [event(8, 'done')], null, ['explore', 'backtest', 'gate', 'dream']);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Finished');
  assert.equal(passed(), '1');
  assert.equal(f.root.querySelector('#rsiobs [data-tree]'), tree); assert.equal(tree.hidden, false);
  assert.equal(treeSvg.querySelectorAll('.rsi-tnode').length, 2); assert.equal(treeSvg.querySelectorAll('.rsi-tedge').length, 1);
  assert.equal(f.root.querySelector('#runact a').getAttribute('href'), '/strategies');
  assert.equal(f.root.querySelector('#cancel'), null); assert.equal(f.S.timers.length, 0); assert.equal(f.intervals.has(pollId), false);
  assert.equal(postRequests(f).length, 0); assert.deepEqual(f.navigations, []);
});

const researchRun = (id, status) => ({id, status, prompt: `Session ${id}`, market: 'btc15m',
  created_at: '2026-10-17T10:00:00Z', hypotheses_tried: id, strategies_passed: status === 'succeeded' ? 1 : 0});
function researchFrontend(runs = [], {policy = null, ...options} = {}) {
  return frontend({...options, fetchImpl: path => {
    if (path === '/api/models') return response({models: [{key: 'offline', label: 'Offline model'}], default: 'offline'});
    if (path === '/api/research/context') return response({markets: []});
    if (path.startsWith('/api/research/scoreboard')) return response({total: {runs: 0}});
    if (path === '/api/research/estimate') return response(options.estimate || {yours: null, sessions: 0, typical: {}});
    assert.equal(path, '/api/runs');
    return response({runs, counts: {research_running: runs.filter(run => run.status === 'running').length,
      research_queued: runs.filter(run => run.status === 'queued').length}, policy: typeof policy === 'function' ? policy() : policy});
  }});
}

test('Research lists the seeded example as an example and does not count it as a session', async () => {
  const example = {...researchRun(1, 'succeeded'), direction: 'random_walk', example: true, spent_usd: 0};
  const mine = {...researchRun(6, 'succeeded'), example: false, spent_usd: 0.42};
  for (const [runs, count] of [[[example], ''], [[mine, example], '1']]) {
    const f = researchFrontend(runs);
    await f.viewResearch(); await flush();
    const list = f.root.querySelector('#runs').innerHTML;
    assert.equal(f.root.querySelector('#rcount').textContent, count);
    assert.match(list, /Example<\/span>/); assert.match(list, /An example Tau ran for you when you signed up\. It cost you nothing\./);
    assert.doesNotMatch(list, /Cost: \$0\.00/);
    if (count) assert.match(list, /Cost: \$0\.42/);
  }
});

test('Research index shows the research loop scoreboard, escaped, and keeps it open while polling', async () => {
  const board = {total: {runs: 3, explored: 24, gated: 5, passed: 1, holdout_passed: 0, cost_usd: 30,
      gate_reach_rate: 0.208, pipeline_death_share: 0.25},
    trend: {before: {runs: 2, explored: 12, gated: 1, gate_reach_rate: 0.083}, after: {runs: 1, explored: 12, gated: 4, gate_reach_rate: 0.333}, better: true},
    days: [{day: '2026-10-23', explored: 12, gated: 1}, {day: '2026-10-24', explored: 12, gated: 4}],
    playbooks: [{id: 7, family: 'weather-high', status: 'active', version: 1, ideas: 20, reached: 3, text: 'DEAD ENDS <script>x</script>'},
      {family: 'weather-high', status: 'candidate', version: 2, ideas: 6, reached: 2, p_better: 0.81, changes: 'new <script>x</script>', text: 'v2 text'}],
    scout: [{market: 'btc15m', best_what: 'calibration <4h 5-10c buy-NO', best_net_c: 3.2, best_z: 2.6}],
    fix_list: [{tag: 'feature_unavailable', market: 'btc15m', count: 4, example: 'needs obs_high_f'}],
    paper: {total: {strategies: 2, trading: 1, round_trips: 12, net_pnl: -1.5, realization: -0.4, live_ready: 0},
      by_playbook: {'7': {round_trips: 12, net_pnl: -1.5}}},
    data_requests: [{market: 'btc15m', kind: 'micro', need: 'flow_imb_60s', status: 'requeued', requeued_run_id: 44,
      idea_title: 'Flow <b>leads</b>', note: null}]};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/models') return response({models: [], default: ''});
    if (path === '/api/research/context') return response({markets: []});
    if (path.startsWith('/api/research/scoreboard')) return response(board);
    assert.equal(path, '/api/runs');
    return response({runs: [researchRun(3, 'succeeded')], counts: {research_running: 0, research_queued: 0}, policy: null});
  }});
  await f.viewResearch(); await flush();
  const details = f.root.querySelector('#rsimo details.loop');
  assert.ok(details); assert.equal(details.open, false);
  const html = details.innerHTML;
  assert.match(html, /Is research getting better\?/); assert.match(html, /Improving/);
  assert.match(html, /8% <span class="rsi-arrow">→<\/span> 33%/);
  assert.match(html, /v2<\/b> on trial ·\u00a02 of 6 ideas reached the gate ·\u00a081% likely better/);
  assert.match(html, /feature missing/); assert.match(html, /calibration &lt;4h/);
  assert.match(html, /On paper against the live book: 2 passed strategies, 1 trading, 12 round trips, net −\$1\.50, losing money where the backtest expected a profit/);
  assert.match(html, /3 of 20 ideas reached the gate ·\u00a0on paper 12 trips, −\$1\.50/);
  assert.match(html, /order-book feature ·\u00a0flow_imb_60s<\/b> ·\u00a0idea re-tested ·\u00a0<a href="\/research\/44">session<\/a>/);
  assert.match(html, /For: Flow &lt;b&gt;leads&lt;\/b&gt;/);
  assert.ok(html.includes('&lt;script&gt;')); assert.doesNotMatch(html, /<script>/);
  details.open = true;
  f.intervals.get(f.S.timers.at(-1))(); await flush();
  assert.equal(f.root.querySelector('#rsimo details.loop').open, true);
  assert.equal(f.requests.filter(r => r.path.startsWith('/api/research/scoreboard')).length, 1);  // cached for a minute
});

for (const [label, view, selector, endpoint] of [
  ['index', 'viewResearch', '#rsimo', '/api/runs'],
  ['run', 'viewRun', '#rsibox', '/api/runs/9?after=0'],
]) {
  test(`Research ${label} policy disclosure retains open or closed state and focus while polling updates its evidence`, async () => {
    let policy = {evolved: false, last_dream: 'No policy improved the score.', last_dream_at: '2026-10-17T10:00:00Z'};
    const run = researchRun(9, 'paused');
    const f = label === 'index' ? researchFrontend([run], {policy: () => policy}) : frontend({fetchImpl: path => {
      assert.equal(path, endpoint); return response({run, events: [], rsi: policy});
    }});
    await f[view](9); await flush();
    let details = f.root.querySelector(selector + ' details');
    assert.equal(details.tag, 'details'); assert.equal(details.open, false);
    const poll = f.intervals.get(f.S.timers.at(-1)); assert.equal(typeof poll, 'function');
    for (const [open, score] of [[true, 0.5], [false, 0.75]]) {
      details.open = open;
      const oldSummary = details.querySelector('summary'); oldSummary.focus();
      policy = {evolved: true, base_score: 0.25, score, summary: `Updated ${score} <script>unsafe</script>`,
        evolved_at: '2026-10-17T10:00:00Z'};
      poll(); await flush();
      const next = f.root.querySelector(selector + ' details'), summary = next.querySelector('summary');
      assert.notEqual(next, details); assert.equal(oldSummary.isConnected, false); assert.equal(next.open, open);
      assert.equal(f.document.activeElement, summary); assert.equal(summary.focusOptions.preventScroll, true);
      assert.match(next.querySelector('.rsi-score').textContent, new RegExp(String(score)));
      assert.ok(next.querySelector('.rsidisc-body').innerHTML.includes(`Updated ${score} &lt;script&gt;unsafe&lt;/script&gt;`));
      assert.doesNotMatch(next.innerHTML, /<script>/); details = next;
    }
    details.open = true;
    const outside = f.root.querySelector('.profile-trig'); outside.focus();
    policy = {...policy, score: 0.9}; poll(); await flush();
    assert.equal(f.root.querySelector(selector + ' details').open, true);
    assert.equal(f.document.activeElement, outside);
    assert.match(f.root.querySelector(selector + ' .rsi-score').textContent, /0\.9/);
    assert.equal(f.requests.filter(request => request.path === endpoint).length, 4);
    assert.equal(postRequests(f).length, 0);
  });
}

test('Research setup is a native closed disclosure unless requested and retains a draft during polling', async () => {
  for (const [search, initiallyOpen] of [['', false], ['?new=1', true]]) {
    const f = researchFrontend([], {search}); await f.viewResearch(); await flush();
    const create = f.root.querySelector('#research-create'), form = f.root.querySelector('#dispatch');
    assert.equal(create.tag, 'details'); assert.equal(create.open, initiallyOpen);
    assert.equal(create.querySelector('summary').textContent, 'New session'); assert.equal(create.contains(form), true);
    assert.ok(form.querySelector('#rmodel')); assert.ok(form.querySelector('#maxhyp')); assert.ok(form.querySelector('#runforever'));
    assert.match(form.querySelector('#rf-hint').textContent, /Runs until you stop it, using credits as it goes/);
    create.open = true;
    const prompt = form.querySelector('textarea[name=prompt]'); prompt.value = 'Keep my unsent idea'; prompt.focus();
    f.intervals.get(f.S.timers.at(-1))(); await flush();
    assert.equal(f.root.querySelector('#research-create'), create); assert.equal(create.open, true);
    assert.equal(f.root.querySelector('#dispatch'), form); assert.equal(prompt.value, 'Keep my unsent idea');
    assert.equal(f.document.activeElement, prompt); assert.equal(postRequests(f).length, 0);
    assert.deepEqual([...new Set(f.requests.map(request => request.path))].sort(),
      ['/api/models', '/api/notifications', '/api/research/context', '/api/research/estimate', '/api/research/scoreboard?days=14', '/api/runs']);
  }
});

for (const [label, statuses, featured] of [
  ['running before queued and paused', ['paused', 'succeeded', 'queued', 'running', 'running', 'failed', 'cancelled'], 4],
  ['queued before paused when none is running', ['paused', 'failed', 'queued', 'queued'], 3],
  ['paused when none is running or queued', ['failed', 'paused', 'cancelled', 'paused'], 2],
]) {
  test(`Research features ${label} and retains every other session in history`, async () => {
    const runs = statuses.map((status, index) => researchRun(index + 1, status));
    runs[featured - 1].prompt = '<script>Unsafe session title</script>';
    runs[featured - 1].started_at = new Date(Date.now() - 120000).toISOString();
    const f = researchFrontend(runs); await f.viewResearch(); await flush();
    const active = f.root.querySelector('#active-research'), history = f.root.querySelector('#runs');
    assert.equal(active.querySelector('a.active-open').getAttribute('href'), `/research/${featured}`);
    assert.equal(active.querySelector('.active-session b').textContent, `Session ${featured}`);
    assert.equal(active.querySelector('.active-prompt').tag, 'h2');
    assert.match(active.querySelector('.active-prompt').innerHTML, /&lt;script&gt;Unsafe session title&lt;\/script&gt;/);
    assert.equal(active.querySelector('.active-prompt').getAttribute('title'), '&lt;script&gt;Unsafe session title&lt;/script&gt;');
    assert.doesNotMatch(active.innerHTML, /<script>/);
    assert.match(active.querySelector('.active-state').textContent,
      new RegExp(runs[featured - 1].status === 'running' ? 'Researching' : runs[featured - 1].status === 'queued' ? 'Queued' : 'Paused'));
    assert.ok(active.querySelector('.active-meta').textContent.includes('BTC 15-min'));
    assert.ok(active.querySelector('.active-meta').textContent.includes('Started 2m ago'));
    assert.deepEqual(active.querySelectorAll('.active-foot dt').map(dt => dt.textContent), ['Tested', 'Passed']);
    assert.deepEqual(active.querySelectorAll('.active-foot dd').map(dd => dd.textContent), [String(featured), '0']);
    assert.deepEqual(history.querySelectorAll('a.run-card').map(card => card.getAttribute('href')),
      runs.filter(run => run.id !== featured).map(run => `/research/${run.id}`));
    for (const run of runs.filter(run => run.id !== featured)) {
      const card = history.querySelector(`a[href="/research/${run.id}"]`);
      assert.equal(card.querySelector('.run-id').textContent, `Session ${run.id}`);
      assert.ok(card.querySelector('.run-title').textContent.includes(run.prompt));
    }
    for (const run of runs.filter(run => run.status === 'paused' && run.id !== featured)) {
      assert.equal(history.querySelector(`a[href="/research/${run.id}"] .run-state`).textContent, 'Outcome Paused');
    }
    assert.equal(f.root.querySelector('#rcount').textContent, String(runs.length - 1));
    assert.equal(postRequests(f).length, 0);
  });
}

test('completed and empty Research accounts keep their history and do not show an active card', async () => {
  for (const runs of [[researchRun(1, 'succeeded'), researchRun(2, 'failed'), researchRun(3, 'cancelled')], []]) {
    const f = researchFrontend(runs); await f.viewResearch(); await flush();
    assert.equal(f.root.querySelector('#active-research').innerHTML, '');
    assert.deepEqual(f.root.querySelector('#runs').querySelectorAll('a.run-card').map(card => card.getAttribute('href')),
      runs.map(run => `/research/${run.id}`));
    assert.equal(f.root.querySelector('#rcount').textContent, runs.length ? String(runs.length) : '');
    if (!runs.length) assert.equal(f.root.querySelector('#runs .empty h3').textContent, 'No sessions yet');
    assert.equal(postRequests(f).length, 0);
  }
});

test('one active Research session does not claim the account has no sessions', async () => {
  for (const status of ['running', 'queued', 'paused']) {
    const f = researchFrontend([researchRun(7, status)]); await f.viewResearch(); await flush();
    assert.equal(f.root.querySelector('#active-research a.active-open').getAttribute('href'), '/research/7');
    assert.equal(f.root.querySelector('#runs').querySelectorAll('a.run-card').length, 0);
    assert.doesNotMatch(f.root.querySelector('#runs').textContent, /No sessions yet/);
  }
});

test('Community snapshots retain source financial values, missing versus zero, escaped identity and accurate deployment modes', () => {
  const f = frontend(), host = new Element();
  const render = snapshot => {
    Object.freeze(snapshot); const before = JSON.stringify(snapshot);
    host.innerHTML = f.postSnapshot(snapshot);
    assert.equal(JSON.stringify(snapshot), before); assert.doesNotMatch(host.innerHTML, /<script>|<img|<unsafe>/);
    if (host.innerHTML) assert.equal(host.querySelectorAll('dl').length, 1, 'snapshot evidence has one native definition list');
    return host.querySelectorAll('dd').map(dd => dd.textContent);
  };
  for (const snapshot of [undefined, null, {kind: 'unknown'}]) assert.deepEqual(render(snapshot), []);
  assert.deepEqual(render({kind: 'pnl', paper_pnl: null, live_pnl: 0}), ['—', '$0.00']);
  assert.deepEqual(render({kind: 'pnl', paper_pnl: -9.25, live_pnl: 12.5}), ['−$9.25', '+$12.50']);
  assert.deepEqual(host.querySelectorAll('dt').map(dt => dt.textContent), ['Paper', 'Live']);
  assert.equal(host.querySelector('.snap-pnl .snap-head b').textContent, 'Realized P&amp;L');
  assert.equal(host.querySelector('dd.loss').textContent, '−$9.25'); assert.equal(host.querySelector('dd.gain').textContent, '+$12.50');
  for (const [pnl, trades, win_rate, values] of [
    [null, null, null, ['—']], [0, 0, 0, ['$0.00', '0', '0.0%']], [-4.5, 3, .25, ['−$4.50', '3', '25.0%']],
  ]) {
    assert.deepEqual(render({kind: 'strategy', id: 42, title: 'Title "quoted" <script>unsafe</script>', market: '<unsafe>', status: 'failed', pnl, trades, win_rate}), values);
    assert.equal(host.querySelector('a.snap').getAttribute('href'), '/strategies/42');
    assert.equal(host.querySelector('.snap-head .mk').textContent, 'Void');
    assert.match(host.innerHTML, /Title &quot;quoted&quot; &lt;script&gt;unsafe&lt;\/script&gt;/);
    assert.equal(host.querySelector('.snap-meta').textContent, '&lt;unsafe&gt;');
    assert.deepEqual(host.querySelectorAll('dt').map(dt => dt.textContent),
      ['Out-of-sample P&amp;L', ...(trades == null ? [] : ['Trades']), ...(win_rate == null ? [] : ['Win rate'])]);
    assert.deepEqual(host.querySelectorAll('.snap-secondary dt').map(dt => dt.textContent),
      [...(trades == null ? [] : ['Trades']), ...(win_rate == null ? [] : ['Win rate'])]);
  }
  for (const [mode, badge, realized_pnl, closed_trades, values] of [
    ['paper', 'Paper', 0, 0, ['$0.00', '0']], ['demo', 'Demo', -7.5, 4, ['−$7.50', '4']], ['live', 'LIVE', 12.5, 8, ['+$12.50', '8']],
  ]) {
    assert.deepEqual(render({kind: 'deployment', id: 7, title: '<script>unsafe</script>', market: '<unsafe>', mode, realized_pnl, closed_trades}), values);
    assert.equal(host.querySelector('.snap-head .mk').textContent, badge);
    assert.equal(host.querySelector('.snap-head .mk').classList.contains('live'), mode === 'live');
    assert.equal(host.querySelector('.snap-meta').textContent, '&lt;unsafe&gt;');
    assert.deepEqual(host.querySelectorAll('dt').map(dt => dt.textContent), ['Realized P&amp;L', 'Closed trades']);
    assert.deepEqual(host.querySelectorAll('.snap-secondary dt').map(dt => dt.textContent), ['Closed trades']);
    assert.equal(host.querySelector('a'), null);
  }
  assert.deepEqual(f.requests, []); assert.deepEqual(f.navigations, []); assert.equal(f.intervals.size, 0);
});

test('Community feed refreshes preserve the native composer choice, unsent draft, strategy selection and focus', async () => {
  const post = (id, body) => ({id, body, author: 'Offline trader', username: 'fixture', created_at: '2026-10-17T10:00:00Z',
    mine: true, comments: 2, reactions: [{emoji: '👍', count: 1, mine: true, names: ['Offline trader']}]});
  let posts = [post(11, 'Initial post')], reads = 0;
  const f = frontend({fetchImpl: path => {
    if (path === '/api/strategies') return response({strategies: [{id: 42, title: 'Saved strategy', status: 'passed'}]});
    assert.equal(path, '/api/community'); reads++; return response({posts});
  }});
  await f.viewCommunity(); await flush();
  const compose = f.root.querySelector('.community-compose'), form = compose.querySelector('#composer-post'), feed = f.root.querySelector('#feed');
  const draft = form.querySelector('#post-body'), select = form.querySelector('#post-strat');
  assert.equal(compose.tag, 'details'); assert.equal(compose.open, false); assert.equal(feed.contains(form), false);
  assert.ok(compose.parentElement.children.indexOf(compose) < compose.parentElement.children.indexOf(feed), 'New post precedes post controls in keyboard traversal as well as the visual layout');
  assert.equal(draft.getAttribute('aria-label'), 'Write a post'); assert.equal(draft._mention, true);
  assert.equal(select.querySelectorAll('option').at(-1).value, 42);
  assert.equal(typeof form.onsubmit, 'function');
  for (const selector of ['#photo-btn', '#photo-remove', '[data-share="pnl"]']) assert.equal(typeof form.querySelector(selector).onclick, 'function');
  assert.equal(typeof form.querySelector('#photo-input').onchange, 'function');
  assert.equal(feed.querySelector('.rx[data-emoji]').getAttribute('aria-pressed'), 'true');
  assert.ok(feed.querySelector('[data-act="comments"]')); assert.ok(feed.querySelector('[data-act="edit"]')); assert.ok(feed.querySelector('[data-react-add]'));
  compose.open = true; draft.value = 'Keep my unsent @idea'; select.value = '42'; draft.focus();
  const poll = f.intervals.get(f.S.timers.at(-1)); assert.equal(typeof poll, 'function');
  posts = [post(12, 'Fresh <script>unsafe</script>')]; poll(); await flush();
  assert.equal(feed.querySelector('[data-id="11"]'), null); assert.ok(feed.querySelector('[data-id="12"]'));
  assert.match(feed.innerHTML, /Fresh &lt;script&gt;unsafe&lt;\/script&gt;/); assert.doesNotMatch(feed.innerHTML, /<script>/);
  assert.equal(f.root.querySelector('#composer-post'), form); assert.equal(compose.open, true);
  assert.equal(draft.value, 'Keep my unsent @idea'); assert.equal(select.value, '42'); assert.equal(f.document.activeElement, draft);
  compose.open = false; const summary = compose.querySelector('summary'); summary.focus();
  posts = []; poll(); await flush();
  assert.equal(feed.querySelector('.empty h3').textContent, 'No posts yet');
  assert.equal(f.root.querySelector('.community-compose'), compose); assert.equal(compose.open, false);
  assert.equal(draft.value, 'Keep my unsent @idea'); assert.equal(select.value, '42'); assert.equal(f.document.activeElement, summary);
  assert.equal(reads, 3); assert.equal(postRequests(f).length, 0); assert.deepEqual(f.navigations, []);
  assert.deepEqual([...new Set(f.requests.map(request => request.path))].sort(), ['/api/community', '/api/notifications', '/api/strategies']);
});

test('Explore preserves distinct source counts and search zeroes while omitting duplicates and reporting source snapshot age', async () => {
  const recent = new Date(Date.now() - 30000).toISOString(), old = new Date(Date.now() - 240000).toISOString();
  const market = Object.freeze({t: 'BTC-26OCT19', ti: 'Bitcoin <unsafe>', s: 'BTC', bid: .51, ask: .53, v24: 1200, oi: 4});
  for (const [search, total, shown, matched, at, expected] of [
    ['', 3, 2, 1, recent, [['Available markets', '2'], ['Tracked', '3'], ['Matching', '1'], ['Snapshot', 'just now']]],
    ['', 1, 1, 1, old, [['Available markets', '1'], ['Stale snapshot', '4m ago']]],
    ['?q=%3Cunsafe%3E', 3, 2, 0, undefined, [['Available markets', '2'], ['Tracked', '3'], ['Matching', '0'], ['Snapshot', 'Time unavailable']]],
    ['?q=btc', 1, 1, 1, 'not-a-timestamp', [['Available markets', '1'], ['Matching', '1'], ['Snapshot', 'Time unavailable']]],
    ['', 0, 0, 0, undefined, [['Available markets', '0'], ['Snapshot', 'Time unavailable']]],
  ]) {
    const payload = Object.freeze({total, shown, matched, at, per: 40, page: 0, markets: Object.freeze(matched ? [market] : [])});
    const before = JSON.stringify(payload), query = new URLSearchParams(search), q = query.get('q') || '';
    const endpoint = '/api/explore?' + new URLSearchParams({q, sort: 'v24', page: '0'});
    const f = frontend({search, fetchImpl: path => { assert.equal(path, endpoint); return response(payload); }});
    await f.viewExplore();
    assert.deepEqual(f.root.querySelectorAll('#xfigs .m').map(fig => [fig.querySelector('dt').textContent,
      (fig.querySelector('.snapshot-age') || fig.querySelector('.fig')).textContent]), expected);
    const snapshot = f.root.querySelector('.snapshot-time'), time = snapshot.querySelector('time');
    if (Number.isFinite(Date.parse(at))) {
      assert.equal(time.getAttribute('datetime'), at); assert.match(time.textContent, / UTC$/);
      assert.equal(Date.parse(time.textContent), Date.parse(at));
      assert.equal(snapshot.classList.contains('snapshot-old'), at === old);
      assert.equal(snapshot.classList.contains('snapshot-unknown'), false);
    } else {
      assert.equal(time, null); assert.equal(snapshot.classList.contains('snapshot-unknown'), true);
      assert.equal(snapshot.classList.contains('snapshot-old'), false);
    }
    assert.equal(typeof f.root.querySelector('#xq').listeners.get('input'), 'function');
    assert.doesNotMatch(f.root.querySelector('#xbody').innerHTML, /<unsafe>|NaN|undefined/);
    if (matched) {
      const sort = f.root.querySelector('[data-sort="v24"]'); assert.match(sort.textContent, /^24h volume/);
      assert.equal(sort.closest('th').getAttribute('aria-sort'), 'descending'); assert.equal(typeof sort.onclick, 'function');
      assert.equal(f.root.querySelector('#xbody tbody a').getAttribute('href'), '/explore?m=BTC-26OCT19');
      assert.equal(f.root.querySelector('#xbody tbody .num').textContent, '52¢');
    } else assert.ok(f.root.querySelector('#xbody .empty'));
    assert.equal(JSON.stringify(payload), before); assert.equal(postRequests(f).length, 0); assert.deepEqual(f.navigations, []);
    assert.deepEqual(f.requests.filter(request => request.path !== '/api/notifications').map(request => request.path), [endpoint]);
    assert.equal(f.S.timers.length, 0);
  }
});

test('Explore keeps duplicate contracts distinct through row rotation while unique and missing names retain exact accessible identity and quotes', async () => {
  const contract = (t, ti, su, overrides = {}) => Object.freeze({t, ti, su, s: 'KXBTC15M', bid: .51, ask: .53, last: .5, v24: 1200, oi: 4, ...overrides});
  const a = contract('BTC-26OCT191200', ' Bitcoin price ', ' Above $100,000 ');
  const b = contract('BTC-26OCT191230', 'Bitcoin price', 'Above $100,000', {bid: .67, ask: .69, v24: 8, oi: 2});
  const unique = contract('RAIN-26OCT19', 'Rain in Seattle?', 'At least 1 inch', {s: 'KXRAIN', bid: null, ask: null, last: .25, v24: 0, oi: 0});
  const subtitle = contract('SUB-26OCT19', '  ', ' Subtitle only ', {bid: null, ask: null, last: null, v24: 0, oi: 8});
  const fallback = contract('RAW-26OCT19', '', '', {bid: .11, ask: .13, v24: 2, oi: 9});
  const hostile = contract('KX"QUOTE"<ticker>&', ' Price "<img src=x>" & forecast ', ' Above <script>unsafe</script> ', {s: 'KX"QUOTE"<series>&', bid: .61, ask: .63, v24: 12, oi: 5});
  const renamed = Object.freeze({...b, su: 'Below $100,000'});
  const expected = new Map([
    [a.t, ['Bitcoin price', 'Above $100,000', 'Bitcoin price ·\u00a0Above $100,000', ['52¢', '1,200', '4'], '&gt; $100,000']],
    [b.t, ['Bitcoin price', 'Above $100,000', 'Bitcoin price ·\u00a0Above $100,000', ['68¢', '8', '2'], '&gt; $100,000']],
    [unique.t, ['Rain in Seattle?', 'At least 1 inch', 'Rain in Seattle? ·\u00a0At least 1 inch', ['25¢', '0', '0']]],
    [subtitle.t, ['Subtitle only', null, 'Subtitle only', ['—', '0', '8']]],
    [fallback.t, [fallback.t, null, fallback.t, ['12¢', '2', '9']]],
    [hostile.t, ['Price &quot;&lt;img src=x&gt;&quot; &amp; forecast', 'Above &lt;script&gt;unsafe&lt;/script&gt;',
      'Price &quot;&lt;img src=x&gt;&quot; &amp; forecast ·\u00a0Above &lt;script&gt;unsafe&lt;/script&gt;', ['62¢', '12', '5']]],
  ]);
  let markets = Object.freeze([a, b, unique, subtitle, fallback, hostile]);
  const f = frontend({fetchImpl: path => {
    assert.ok(['/api/explore?q=&sort=v24&page=0', '/api/explore?q=&sort=oi&page=0'].includes(path));
    return response({total: markets.length, shown: markets.length, matched: markets.length, per: 40, page: 0, at: new Date().toISOString(), markets});
  }});
  const check = (duplicates, bRenamed = false) => {
    const rows = f.root.querySelectorAll('#xbody tbody tr'); assert.equal(rows.length, markets.length);
    rows.forEach((row, index) => {
      const m = markets[index], link = row.querySelector('a.market-name');
      const [title, sub, label, amounts, display] = m === renamed ? ['Bitcoin price', 'Below $100,000', 'Bitcoin price ·\u00a0Below $100,000', ['68¢', '8', '2'], '&lt; $100,000'] : expected.get(m.t);
      const raw = m === hostile ? 'KX&quot;QUOTE&quot;&lt;ticker&gt;&amp;' : m.t;
      assert.equal(link.getAttribute('href'), '/explore?m=' + encodeURIComponent(m.t));
      assert.equal(link.getAttribute('title'), raw);
      assert.equal(link.getAttribute('aria-label'), label === raw ? label : `${label} ·\u00a0${raw}`);
      assert.equal(link.querySelector('strong').textContent, display || sub || title);
      if (sub) assert.equal(row.querySelector('.market-contract a'), link);
      else assert.equal(row.querySelector('.market-contract'), null);
      const ref = row.querySelector('.market-ref');
      assert.ok(ref, 'every source contract retains its full visible raw identifier');
      assert.equal(ref.textContent, raw);
      assert.deepEqual(['.yes-price', '.market-volume', '.market-interest'].map(selector => row.querySelector(selector).textContent), amounts);
      const pair = row.querySelectorAll('.quote-side').map(n => n.textContent);
      assert.deepEqual(pair, m.bid == null ? ['—', '—'] : [Math.round(m.bid * 100) + '¢', Math.round(m.ask * 100) + '¢']);
      const external = row.querySelector('.xlink a');
      assert.equal(external.getAttribute('href'), 'https://kalshi.com/markets/' + encodeURIComponent(m.s.toLowerCase()));
      assert.equal(external.getAttribute('target'), '_blank'); assert.equal(external.getAttribute('rel'), 'noopener');
    });
    assert.doesNotMatch(f.root.querySelector('#xbody').innerHTML, /<img|<script>|<ticker>|<series>/);
    const names = rows.slice(0, 2).map(row => row.querySelector('a.market-name').getAttribute('aria-label'));
    if (!bRenamed && duplicates.length) assert.notEqual(names[0], names[1]);
  };
  const original = JSON.stringify(markets); await f.viewExplore(); check([a.t, b.t]); assert.equal(JSON.stringify(markets), original);
  markets = Object.freeze([hostile, fallback, subtitle, unique, renamed, a]);
  const rotated = JSON.stringify(markets); f.root.querySelector('[data-sort="oi"]').onclick(); await flush();
  check([], true); assert.equal(JSON.stringify(markets), rotated);
  markets = Object.freeze([b, a]); f.root.querySelector('[data-sort="v24"]').onclick(); await flush(); check([a.t, b.t]);
  assert.deepEqual(f.requests.filter(request => request.path !== '/api/notifications').map(request => request.path),
    ['/api/explore?q=&sort=v24&page=0', '/api/explore?q=&sort=oi&page=0', '/api/explore?q=&sort=v24&page=0']);
  assert.equal(postRequests(f).length, 0); assert.equal(f.S.timers.length, 0);
});

test('Explore keeps every source event and contract independently legible when the sort interleaves event families', async () => {
  const m = (t, s, ti, su) => Object.freeze({t, s, ti, su, bid: .4, ask: .42, last: .4, v24: 8, oi: 2});
  const markets = Object.freeze([
    m('A-1', 'BTC', 'Bitcoin 5pm', 'Above $90,000'),
    m('A-2', 'BTC', 'Bitcoin 5pm', 'Above $91,000'),
    m('B-1', 'ETH', 'Ethereum 5pm', 'Above $3,000'),
    m('A-3', 'BTC', 'Bitcoin 5pm', 'Above $92,000'),
    m('C-1', 'OTHER', 'Bitcoin 5pm', 'Above $93,000'),
    m('D-1', 'OTHER', 'Bitcoin 5pm', 'Bitcoin 5pm'),
    m('E-1', 'OTHER', '', 'Subtitle only'),
    m('F-1', 'BTC', 'Bitcoin · Oct 19, 5pm ET · Source context', 'Above $94,000'),
    m('G-1', 'OTHER', 'Weather · City <script>unsafe</script> & forecast', 'At least 1 inch'),
  ]);
  const before = JSON.stringify(markets);
  const f = frontend({fetchImpl: () => response({at: new Date().toISOString(), markets, total: markets.length, shown: markets.length, matched: markets.length, per: 40})});
  await f.viewExplore();
  const rows = f.root.querySelectorAll('#xbody tbody tr');
  assert.deepEqual(rows.map(row => row.querySelector('a.market-name').getAttribute('href')), markets.map(m => '/explore?m=' + encodeURIComponent(m.t)));
  assert.ok(rows.slice(0,5).every(row => !row.querySelector('.market-event').classList.contains('vh')));
  assert.equal(rows[1].querySelector('.market-event').textContent, 'Bitcoin 5pm');
  assert.equal(rows[1].querySelector('a.market-name').getAttribute('aria-label'), 'Bitcoin 5pm ·\u00a0Above $91,000 ·\u00a0A-2');
  assert.equal(rows[3].querySelector('.market-event').classList.contains('vh'), false);
  assert.equal(rows[4].querySelector('.market-event').classList.contains('vh'), false);
  assert.equal(rows[5].querySelector('a.market-name strong').textContent, 'Bitcoin 5pm');
  assert.equal(rows[5].querySelector('.market-ref').textContent, 'D-1');
  assert.equal(rows[6].querySelector('a.market-name strong').textContent, 'Subtitle only');
  assert.equal(rows[6].querySelector('.market-ref').textContent, 'E-1');
  const identityHeaders = f.root.querySelector('.t-explore thead tr').querySelectorAll('th').slice(0, 2);
  assert.deepEqual(identityHeaders.map(th => th.textContent), ['Market / contract', 'Context']);
  assert.ok(identityHeaders.every(th => th.getAttribute('scope') === 'col' && th.getAttribute('rowspan') === '2'));
  const yesGroup = f.root.querySelector('.t-explore th.price-group');
  assert.equal(yesGroup.textContent, 'YES'); assert.equal(yesGroup.getAttribute('scope'), 'colgroup');
  assert.equal(yesGroup.getAttribute('colspan'), '3');
  const unsplit = rows[0].querySelectorAll('td');
  assert.equal(unsplit.length, 8);
  assert.equal(unsplit[0].querySelector('.market-event').textContent, 'Bitcoin 5pm', 'retain the entire unsplit source title');
  assert.equal(unsplit[0].querySelector('a.market-name').getAttribute('href'), '/explore?m=A-1');
  assert.equal(unsplit[0].querySelector('.market-ref').textContent, 'A-1');
  assert.doesNotMatch(unsplit[1].textContent, /5pm|expiry/i, 'do not infer a separate context or expiry from unstructured title text');
  assert.equal(rows[5].querySelector('td').getAttribute('colspan'), '2', 'a single identity fallback spans both identity tracks');
  assert.equal(rows[6].querySelector('td').getAttribute('colspan'), '2');
  const contextual = rows[7].querySelectorAll('td'), hostile = rows[8].querySelectorAll('td');
  assert.equal(contextual.length, 8); assert.equal(hostile.length, 8);
  assert.equal(contextual[1].textContent, 'Oct 19, 5pm ET ·\u00a0Source context', 'retain every actual context segment without inferring expiry');
  assert.equal(hostile[1].textContent, 'City &lt;script&gt;unsafe&lt;/script&gt; &amp; forecast');
  assert.equal(rows[7].querySelector('.market-event').getAttribute('title'), markets[7].ti);
  assert.equal(rows[7].querySelector('a.market-name').getAttribute('aria-label'), markets[7].ti + ' ·\u00a0' + markets[7].su + ' ·\u00a0F-1');
  assert.deepEqual(rows.slice(7).map(row => ['.yes-price', '.quote-bid', '.quote-ask', '.market-volume', '.market-interest'].map(selector => row.querySelector(selector).textContent)),
    [['41¢', '40¢', '42¢', '8', '2'], ['41¢', '40¢', '42¢', '8', '2']]);
  assert.doesNotMatch(f.root.querySelector('#xbody').innerHTML, /<script>|<unsafe>/);
  assert.equal(JSON.stringify(markets), before); assert.equal(postRequests(f).length, 0);
});

test('Explore and Hot Markets compact conditions preserve strict versus inclusive source bounds, exact digits and accessible source wording', async () => {
  const conditions = ['$0.00 or above', '$1,234.500 or below', 'Above $2.75', 'Below $000.0', 'At least 1 inch', '60% or above', 'Above $20 if approved'];
  const displays = ['≥ $0.00', '≤ $1,234.500', '&gt; $2.75', '&lt; $000.0', 'At least 1 inch', '60% or above', 'Above $20 if approved'];
  const markets = Object.freeze(conditions.map((su, index) => Object.freeze({t: `CONTRACT-${index}`, s: 'BTC', ti: 'Bitcoin', su, bid: .5, ask: .52, v24: index, oi: 0})));
  const before = JSON.stringify(markets);
  const f = frontend({fetchImpl: () => response({at: new Date().toISOString(), markets, total: 7, shown: 7, matched: 7, per: 40})});
  await f.viewExplore();
  const links = f.root.querySelectorAll('a.market-name');
  assert.deepEqual(links.map(link => link.querySelector('strong').textContent), displays);
  links.forEach((link, index) => {
    assert.equal(link.getAttribute('aria-label'), `Bitcoin ·\u00a0${conditions[index]} ·\u00a0CONTRACT-${index}`);
    assert.equal(link.getAttribute('title'), `CONTRACT-${index}`);
    assert.equal(link.getAttribute('href'), `/explore?m=CONTRACT-${index}`);
  });
  const requests = f.requests.length;
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  f.S.hot = Object.freeze({at: new Date().toISOString(), markets}); f.renderHotRail();
  const quotes = f.root.querySelectorAll('.hot-row');
  assert.deepEqual(quotes.map(row => row.querySelector('.hot-title > span').textContent), displays);
  quotes.forEach((row, index) => {
    assert.equal(row.querySelector('.hot-title').getAttribute('title'), `Bitcoin ·\u00a0${conditions[index]}`);
    assert.ok(row.getAttribute('aria-label').startsWith(`Bitcoin ·\u00a0${conditions[index]} ·\u00a0CONTRACT-${index} ·\u00a051¢`));
  });
  assert.equal(f.requests.length, requests, 'formatting source conditions performs no lookup');
  assert.equal(JSON.stringify(markets), before); assert.equal(postRequests(f).length, 0);
});

test('Explore bid and ask preserve decimal strings, zero and independently missing or malformed quote sides', async () => {
  const markets = Object.freeze([
    Object.freeze({t: 'DECIMAL', ti: 'Decimal contract', bid: '.51', ask: '.53', last: '.5'}),
    Object.freeze({t: 'ZERO', ti: 'Zero bid contract', bid: 0, ask: .02, last: .01}),
    Object.freeze({t: 'MISSING', ti: 'Missing bid contract', bid: null, ask: .54, last: .5}),
    Object.freeze({t: 'MALFORMED', ti: 'Malformed quote contract', bid: 'not-a-price', ask: null, last: null}),
    Object.freeze({t: 'BLANK', ti: 'Blank quote contract', bid: '', ask: '  ', last: null}),
    Object.freeze({t: 'TYPES', ti: 'Wrong type contract', bid: false, ask: [], last: null}),
    Object.freeze({t: 'STRINGZERO', ti: 'String zero contract', bid: '0', ask: '0.02', last: .01}),
  ]);
  const before = JSON.stringify(markets);
  const f = frontend({fetchImpl: path => {
    assert.equal(path, '/api/explore?q=&sort=v24&page=0');
    return response({total: 7, shown: 7, matched: 7, per: 40, page: 0, at: null, markets});
  }});
  await f.viewExplore();
  const rows = f.root.querySelectorAll('#xbody tbody tr');
  assert.deepEqual(rows.map(row => row.querySelectorAll('.quote-side').map(side => side.textContent)),
    [['51¢', '53¢'], ['0¢', '2¢'], ['—', '54¢'], ['—', '—'], ['—', '—'], ['—', '—'], ['0¢', '2¢']]);
  assert.deepEqual(rows.map(row => row.querySelector('td.num').textContent), ['52¢', '1¢', '50¢', '—', '—', '—', '1¢']);
  const priceGroup = f.root.querySelector('.t-explore th[scope="colgroup"]');
  assert.equal(priceGroup.textContent, 'YES'); assert.equal(priceGroup.getAttribute('colspan'), '3');
  const quoteHeaders = f.root.querySelectorAll('.t-explore thead tr')[1].querySelectorAll('th');
  assert.deepEqual(quoteHeaders.map(th => th.textContent), ['Price', 'Bid', 'Ask']);
  assert.ok(quoteHeaders.every(th => th.getAttribute('scope') === 'col'));
  assert.doesNotMatch(f.root.querySelector('#xbody').innerHTML, /NaN|not-a-price|undefined/);
  assert.equal(JSON.stringify(markets), before); assert.equal(postRequests(f).length, 0);
  assert.equal(f.requests.filter(r => r.path.startsWith('/api/explore')).length, 1);
});

test('Explore header sorting keeps the original criteria and search, resets pagination and preserves focused controls after every replacement', async () => {
  const a = Object.freeze({t: 'BTC-A', ti: 'First contract', s: 'BTC', bid: .51, ask: .53, v24: 1200, oi: 4, last: .5});
  const b = Object.freeze({t: 'BTC-B', ti: 'Second contract', s: 'BTC', bid: .31, ask: .33, v24: 100, oi: 8, last: .6});
  const orders = {v24: [a, b], oi: [b, a], last: [b, a]}, queries = [];
  const f = frontend({search: '?q=btc&page=2&sort=oi', fetchImpl: path => {
    const url = new URL(path, 'http://offline.invalid'); assert.equal(url.pathname, '/api/explore');
    const params = Object.fromEntries(url.searchParams); queries.push(params);
    return response({total: 100, shown: 90, matched: 81, per: 40, page: Number(params.page), at: new Date().toISOString(), markets: orders[params.sort]});
  }});
  await f.viewExplore();
  assert.equal(f.root.querySelector('[data-sort="last"]').getAttribute('aria-label'), 'Sort by last trade price');
  for (const criterion of ['last', 'v24', 'oi']) {
    const button = f.root.querySelector(`[data-sort="${criterion}"]`); button.focus(); button.onclick(); await flush();
    const replacement = f.root.querySelector(`[data-sort="${criterion}"]`);
    assert.notEqual(replacement, button); assert.equal(button.isConnected, false);
    assert.equal(f.document.activeElement, replacement); assert.equal(replacement.focusOptions.preventScroll, true);
    for (const control of f.root.querySelectorAll('[data-sort]')) {
      assert.equal(typeof control.onclick, 'function');
      assert.equal(control.closest('th').getAttribute('aria-sort'), control.dataset.sort === criterion ? 'descending' : 'none');
    }
    assert.deepEqual(f.root.querySelectorAll('#xbody tbody .name a').map(link => link.getAttribute('href')),
      orders[criterion].map(market => '/explore?m=' + market.t));
  }
  assert.deepEqual(queries, [{q: 'btc', sort: 'oi', page: '2'}, ...['last', 'v24', 'oi'].map(sort => ({q: 'btc', sort, page: '0'}))]);
  assert.deepEqual(f.navigations, ['last', 'v24', 'oi'].map(sort => '/explore?' + new URLSearchParams({q: 'btc', sort, page: '0'})));
  assert.equal(postRequests(f).length, 0); assert.equal(f.S.timers.length, 0);
});

test('Explore ignores superseded requests and responses from a departed route, including its initial read', async () => {
  const payload = (title, shown = 1) => ({total: shown, shown, matched: 1, per: 40, page: 0, at: new Date().toISOString(),
    markets: [{t: 'BTC-OFFLINE', ti: title, s: 'BTC', bid: .51, ask: .53, v24: 1200, oi: 4, last: .5}]});
  const older = deferred(), latest = deferred(), departed = deferred();
  let reads = 0;
  const f = frontend({fetchImpl: path => {
    const expected = ['v24', 'oi', 'last', 'v24'][reads++];
    assert.equal(path, '/api/explore?' + new URLSearchParams({q: '', sort: expected, page: '0'}));
    return reads === 1 ? response(payload('Initial')) : reads === 2 ? older.promise : reads === 3 ? latest.promise : departed.promise;
  }});
  await f.viewExplore();
  const body = f.root.querySelector('#xbody'), figures = f.root.querySelector('#xfigs');
  f.root.querySelector('[data-sort="oi"]').onclick();
  f.root.querySelector('[data-sort="last"]').focus(); f.root.querySelector('[data-sort="last"]').onclick();
  latest.resolve(response(payload('Newest result', 20))); await flush();
  assert.equal(body.querySelector('tbody .name a strong').textContent, 'Newest result');
  assert.equal(figures.querySelector('.fig').textContent, '20');
  const focused = f.document.activeElement, writes = [body.writes, figures.writes];
  older.resolve(response(payload('Superseded result', 10))); await flush();
  assert.deepEqual([body.writes, figures.writes], writes); assert.equal(f.document.activeElement, focused);
  f.root.querySelector('[data-sort="v24"]').onclick();
  f.S.gen++; f.root.innerHTML = '<main>Another route</main>';
  departed.resolve(response(payload('Old route result', 30))); await flush();
  assert.equal(f.root.querySelector('main').textContent, 'Another route'); assert.deepEqual([body.writes, figures.writes], writes);
  assert.equal(reads, 4); assert.equal(postRequests(f).length, 0);

  const initial = deferred(), g = frontend({fetchImpl: path => { assert.equal(path, '/api/explore?q=&sort=v24&page=0'); return initial.promise; }});
  const opening = g.viewExplore(), initialBody = g.root.querySelector('#xbody'), initialFigures = g.root.querySelector('#xfigs');
  const initialWrites = [initialBody.writes, initialFigures.writes];
  g.S.gen++; g.root.innerHTML = '<main>New route before first result</main>';
  // A read for a page the user has left never settles (api drops it), so wait for the event loop, not the view.
  initial.resolve(response(payload('Late first result'))); await flush(); await flush();
  assert.equal(g.root.querySelector('main').textContent, 'New route before first result');
  assert.deepEqual([initialBody.writes, initialFigures.writes], initialWrites);
  assert.equal(g.S.timers.length, 0); assert.equal(postRequests(g).length, 0); assert.deepEqual(g.navigations, []);
});

test('Hot Markets defaults closed at every width and respects either saved preference', () => {
  for (const [width, saved, expected] of [[760, null, false], [761, null, false],
    [760, '1', true], [761, '0', false], [760, '0', false], [761, '1', true]]) {
    const queries = [], storage = new Map(saved == null ? [] : [['tau_hotrail', saved]]);
    const f = frontend({storage, matchMedia: query => { queries.push(query); return {matches: width <= 760}; }});
    assert.equal(f.hotOpen(), expected, `${width}px with saved preference ${saved}`);
    assert.deepEqual(queries, []);
  }
});

test('the header owns one persistent market drawer control that retains focus through quote refresh and toggles only its saved view preference', () => {
  const storage = new Map(), f = frontend({storage});
  f.root.innerHTML = '<header><span class="market-control"></span></header><aside id="hotrail"></aside>';
  f.S.hot = Object.freeze({at: new Date().toISOString(), markets: Object.freeze([])});
  f.renderHotRail();
  const button = f.root.querySelector('header button');
  assert.equal(f.root.querySelectorAll('[data-hot="toggle"]').length, 1);
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  assert.equal(button.getAttribute('aria-controls'), 'hotrail');
  assert.equal(button.getAttribute('aria-label'), 'Expand hot markets');
  button.focus(); f.renderHotRail();
  assert.equal(f.root.querySelector('header button'), button);
  assert.equal(f.document.activeElement, button);
  button.onclick();
  assert.equal(f.hotOpen(), true);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  assert.equal(button.getAttribute('aria-label'), 'Collapse hot markets');
  assert.equal(f.document.body.classList.contains('hot-open'), true);
  button.onclick();
  assert.equal(f.hotOpen(), false);
  assert.equal(f.document.body.classList.contains('hot-open'), false);
  assert.deepEqual([...storage], [['tau_hotrail', '0']]);
  assert.deepEqual(f.requests, []); assert.deepEqual(f.navigations, []);
});

test('market drawer changes redraw the current paper chart at its new width without polling or losing focus', async () => {
  const data = dashboardData({paper: {daily: [{d: '2026-10-16', pnl: -4}, {d: '2026-10-18', pnl: 5}]}});
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(data); }});
  await f.viewDashboard();
  const button = f.root.querySelector('[data-hot="toggle"]'), plot = f.root.querySelector('.paper-plot');
  button.focus();
  const requests = f.requests.length, samples = plot.querySelectorAll('.chart-sample').map(e => e.getAttribute('aria-label'));
  for (const width of [771, 316]) {
    plot.clientWidth = width;
    const writes = plot.writes;
    button.onclick();
    assert.equal(plot.writes, writes + 1);
    assert.equal(plot.querySelector('svg.chart').getAttribute('viewBox'), `0 0 ${width} 180`);
    assert.deepEqual(plot.querySelectorAll('.chart-sample').map(e => e.getAttribute('aria-label')), samples);
    assert.equal(f.document.activeElement, button);
    assert.equal(f.requests.length, requests);
  }
  const writes = plot.writes;
  f.clearTimers(); button.onclick();
  assert.equal(plot.writes, writes, 'leaving Dashboard clears its local redraw callback');
  assert.equal(f.requests.length, requests);
  assert.deepEqual(postRequests(f), []); assert.deepEqual(f.navigations, []);
});

test('Hot Markets reports source snapshot age without changing quotes or performing actions', () => {
  const storage = new Map([['tau_hotrail', '1']]), f = frontend({storage});
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  const market = Object.freeze({t: 'KXBTC15M-26OCT181230-00', ti: 'Bitcoin price', su: 'Above $105,000',
    s: 'KXBTC15M', bid: .51, ask: .53, last: .5, v24: 1200, h: Object.freeze([.48, .52])});
  const markets = Object.freeze([market]), cachedAt = f.S.hotAt, autopilot = f.S.ap;
  const cases = [
    [new Date(Date.now() - 30000).toISOString(), false, /^Snapshot ·\u00a0just now$/],
    [new Date(Date.now() - 240000).toISOString(), true, /^Stale ·\u00a04m ago$/],
    [undefined, true, /^Snapshot time unavailable$/],
    ['not-a-timestamp', true, /^Snapshot time unavailable$/],
    [new Date(Date.now() - 30000).toISOString(), false, /^Snapshot ·\u00a0just now$/],
  ];
  for (const [at, old, label] of cases) {
    const snapshot = Object.freeze({markets, ...(at === undefined ? {} : {at})});
    const before = JSON.stringify(snapshot);
    f.S.hot = snapshot; f.renderHotRail();
    const rail = f.root.querySelector('#hotrail'), freshness = rail.querySelector('.hot-freshness');
    assert.equal(rail.classList.contains('is-stale'), old, `source timestamp ${at}, independent of recent receipt time`);
    assert.equal(freshness.classList.contains('is-old'), old, `snapshot timestamp ${at}`);
    assert.match(freshness.textContent, label);
    assert.equal(freshness.getAttribute('title').includes('More than 3 minutes old'), Boolean(at && at !== 'not-a-timestamp' && old));
    assert.equal(rail.querySelector('.hot-price b').textContent, '52¢');
    assert.equal(rail.querySelector('.hot-delta').textContent, '+4¢');
    assert.equal(rail.querySelector('.hot-vol').textContent, '1.2k ·\u00a024h');
    assert.equal(rail.querySelector('.hot-vol').getAttribute('title'), '24-hour volume');
    assert.equal(rail.querySelector('.hot-row').getAttribute('href'), 'https://kalshi.com/markets/kxbtc15m');
    assert.equal(f.S.hot, snapshot); assert.equal(JSON.stringify(snapshot), before);
  }
  assert.equal(f.S.hotAt, cachedAt); assert.equal(f.S.ap, autopilot);
  assert.deepEqual([...storage], [['tau_hotrail', '1']]);
  assert.deepEqual(f.requests, []); assert.deepEqual(f.navigations, []);
  assert.equal(f.intervals.size, 0); assert.equal(f.timeouts.size, 0);
});

test('Hot Markets preserves dated contract identity and escapes full accessible quote names', () => {
  const f = frontend({storage: new Map([['tau_hotrail', '1']])});
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  f.S.me.markets = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin'}];
  const quote = {s: 'KXBTC15M', su: 'At least $105,000', bid: .51, ask: .53, last: .5, v24: 1200, h: Object.freeze([.48, .52])};
  const markets = Object.freeze([
    Object.freeze({...quote, t: 'KXBTC15M-26OCT181230-00', ti: 'Bitcoin price on Oct 18, 2026'}),
    Object.freeze({...quote, t: 'KXBTC15M-26OCT191230-00', ti: 'Bitcoin price on Oct 19, 2026'}),
    Object.freeze({...quote, t: 'KXBTC15M-"quoted"<contract>&', ti: 'Price "preview" <img src=x onerror="alert(1)"> & more',
      su: 'Above <script>unsafe</script>', bid: null, ask: null, last: null, v24: 0, h: Object.freeze([])}),
  ]);
  f.S.hot = Object.freeze({at: new Date().toISOString(), markets});
  const before = JSON.stringify(f.S.hot); f.renderHotRail();
  const rows = f.root.querySelectorAll('.hot-row'), labels = rows.map(row => row.getAttribute('aria-label'));
  assert.equal(rows.length, 3); assert.notEqual(labels[0], labels[1]);
  for (let index = 0; index < 2; index++) {
    assert.equal(rows[index].querySelector('.hot-title strong').textContent, 'BTC 15-min');
    assert.ok(labels[index].includes(markets[index].ti)); assert.ok(labels[index].includes(markets[index].t));
    assert.match(labels[index], /At least \$105,000.*52¢.*\+4¢ across available history.*1\.2k volume over 24 hours.*Opens Kalshi in a new tab/);
    assert.equal(rows[index].getAttribute('target'), '_blank'); assert.equal(rows[index].getAttribute('rel'), 'noopener');
  }
  assert.match(labels[2], /Price &quot;preview&quot; &lt;img/);
  assert.match(labels[2], /KXBTC15M-&quot;quoted&quot;&lt;contract&gt;&amp;/);
  assert.match(labels[2], /Above &lt;script&gt;unsafe&lt;\/script&gt;.*Quote unavailable.*0 volume over 24 hours/);
  assert.equal(rows[2].getAttribute('onerror'), null); assert.equal(rows[2].querySelector('img'), null); assert.equal(rows[2].querySelector('script'), null);
  assert.equal(JSON.stringify(f.S.hot), before); assert.deepEqual(f.requests, []); assert.deepEqual(f.navigations, []);
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


const billingData = (overrides = {}) => ({balance: 10, spent: 2, free_bonus: 3, ledger: [], cards: [], configured: false,
  topup_fee_pct: 5, autoreload_amount: 20, autoreload_threshold: 5, min_reload_amount: 5, min_reload_threshold: 1,
  min_topup: 5, max_topup: 1000, publishable_key: 'synthetic-only', ...overrides});
const systemData = () => ({nodes: {}, events: [], now: '2026-10-20T16:00:00Z'});
function leaveView(f, html = '<main>Next page</main>') {
  f.S.gen++; f.clearTimers(); f.root.innerHTML = html;
  return {rootWrites: f.root.writes, main: f.root.querySelector('main')};
}
function stripeFixture(confirmSetup = async () => ({setupIntent: {payment_method: 'synthetic-pm'}})) {
  const calls = {constructed: 0, mounted: 0};
  return {calls, Stripe: () => {
    calls.constructed++;
    return {confirmSetup, elements: () => ({create: () => ({mount: () => calls.mounted++})})};
  }};
}

for (const [label, path, data] of [['System', '/system', systemData], ['Billing', '/billing', billingData],
  ['Funds', '/funds', funds], ['Admin', '/admin', () => ({users: [], waitlist: []})]]) {
  for (const failure of [false, true]) {
    test(`${label} departed initial ${failure ? 'error' : 'success'} cannot replace the current page or register a poll`, async () => {
      const pending = deferred();
      const expected = {System: '/api/admin/system', Billing: '/api/billing', Funds: '/api/funds', Admin: '/api/admin'}[label];
      const f = frontend({fetchImpl: request => { assert.equal(request, expected); return pending.promise; }});
      f.S.me.is_admin = true; f.location.pathname = path;
      const loading = f.render();
      f.location.pathname = '/settings'; await f.render();
      const html = f.root.innerHTML, writes = f.root.writes, intervals = f.intervals.size;
      const live = f.S.sysLive;
      pending.resolve(failure ? response({error: 'Synthetic departed failure'}, 503) : response(data()));
      await flush(); await flush();  // the departed read never settles, so its view never resumes
      assert.equal(f.root.innerHTML, html); assert.equal(f.root.writes, writes);
      assert.equal(f.intervals.size, intervals); assert.equal(f.S.timers.length, 0);
      assert.equal(f.S.sysLive, live); assert.equal(postRequests(f).length, 0);
    });
  }
}

test('Billing swaps the welcome credit for a credit runway once there is usage this week', async () => {
  let data = billingData({spent_7d: 3.5, runway_days: 20});
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/billing'); return response(data); }});
  await f.viewBilling();
  let figs = f.root.querySelector('#bfigs').innerHTML;
  assert.match(figs, /Credits last/); assert.match(figs, /About 20 days/); assert.match(figs, /at \$3\.50 a week/);
  assert.doesNotMatch(figs, /Welcome credit/);
  data = billingData({runway_days: 200, spent_7d: 0.35});
  await f.viewBilling();
  assert.match(f.root.querySelector('#bfigs').innerHTML, /Over 3 months/);
  data = billingData({});
  await f.viewBilling();
  figs = f.root.querySelector('#bfigs').innerHTML;
  assert.match(figs, /Welcome credit/); assert.doesNotMatch(figs, /Credits last/);
});

test('System reports a current read failure and clears the notice after a successful poll', async () => {
  let reads = 0;
  const f = frontend({fetchImpl: path => {
    assert.equal(path, '/api/admin/system');
    return ++reads === 1 ? response({error: '<unsafe> unavailable'}, 503) : response(systemData());
  }});
  await f.viewSystem();
  const notice = f.root.querySelector('#sys-error');
  assert.ok(notice); assert.match(notice.innerHTML, /&lt;unsafe&gt; unavailable/);
  assert.doesNotMatch(notice.innerHTML, /<unsafe>/);
  assert.equal(f.S.timers.length, 1);
  f.intervals.get(f.S.timers[0])(); await flush();
  assert.equal(notice.innerHTML, ''); assert.match(f.root.querySelector('#sys-stamp').textContent, /updated/);
  assert.match(f.root.querySelector('#sys-feed').innerHTML, /Quiet right now/);
});

test('System ignores an in-flight poll after navigation without replacing live state', async () => {
  const pending = deferred(), initial = systemData(); let reads = 0;
  const f = frontend({fetchImpl: path => {
    assert.equal(path, '/api/admin/system'); return ++reads === 1 ? response(initial) : pending.promise;
  }});
  await f.viewSystem(); f.intervals.get(f.S.timers[0])(); await flush();
  const next = leaveView(f), intervalCount = f.intervals.size;
  pending.resolve(response({...systemData(), nodes: {web: {users: 999}}})); await flush();
  assert.equal(f.S.sysLive, initial.nodes); assert.equal(next.main.innerHTML, 'Next page');
  assert.equal(next.main.writes, 0); assert.equal(f.root.writes, next.rootWrites);
  assert.equal(f.intervals.size, intervalCount); assert.equal(reads, 2);
});

test('deployment details hold realized P&L against the backtest pace for the same trades', async () => {
  const dep = (id, closed, oos) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
    realized_pnl: 1, closed_trades: closed, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1,
    backtest: {out_of_sample: oos}});
  const data = dashboardData({deployments: [dep(1, 5, {pnl: 12, trades: 6}), dep(2, 0, {pnl: 12, trades: 6}), dep(3, 1, {pnl: 3})]});
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(data); }});
  await f.viewDashboard();
  const text = id => evidenceFor(f.root.querySelector('#dash-deps'), id).textContent;
  // $12 over 6 unseen trades = $2 a trade, so 5 closed trades -> +$10.00.
  assert.ok(text(1).includes('Test expected +$10.00 for the same 5 trades ·\u00a0Unseen P&amp;L +$12.00'), text(1));
  assert.ok(!text(2).includes('Test expected')); assert.ok(!text(3).includes('Test expected'));
});

test('Buying credits says how long the amount lasts at the user\'s own pace', async () => {
  const stripe = stripeFixture();
  let data = billingData({configured: true, spent_7d: 7, runway_days: 10});
  const f = frontend({stripeLoader: async () => stripe.Stripe, fetchImpl: path => {
    if (path === '/api/billing') return response(data);
    return response({client_secret: 'synthetic-secret'});
  }});
  await f.viewBilling(); await flush();
  const note = () => f.root.querySelector('#topup-note').textContent;
  // $20 at $7 a week ($1 a day) -> about 20 days.
  assert.match(note(), /You'll pay \$21\.00 \(\$20\.00 credits \+ 5% fee\)\. At your pace \(\$7\.00 a week\) that's about 20 days of research\./);
  const amt = f.root.querySelector('#topup-amt'); amt.value = '200'; amt.oninput();
  assert.match(note(), /over 3 months of research/);
  data = billingData({configured: true, spent_7d: 0});
  await f.viewBilling(); await flush();
  assert.match(note(), /5% fee\)\.$/); assert.doesNotMatch(note(), /At your pace/);
});

test('Billing does not create a setup intent when Stripe loading completes after departure', async () => {
  const pending = deferred(), stripe = stripeFixture();
  const f = frontend({stripeLoader: () => pending.promise, fetchImpl: path => {
    if (path === '/api/billing') return response(billingData({configured: true}));
    assert.equal(path, '/api/billing/setup-intent'); return response({client_secret: 'synthetic-secret'});
  }});
  const loading = f.viewBilling(); await flush(); const next = leaveView(f);
  pending.resolve(stripe.Stripe); await loading;
  assert.equal(stripe.calls.constructed, 0); assert.equal(stripe.calls.mounted, 0);
  assert.equal(postRequests(f).length, 0); assert.equal(f.root.writes, next.rootWrites);
});

test('Billing does not mount Stripe when the setup intent completes after departure', async () => {
  const pending = deferred(), stripe = stripeFixture();
  const f = frontend({stripeLoader: async () => stripe.Stripe, fetchImpl: path => {
    if (path === '/api/billing') return response(billingData({configured: true}));
    assert.equal(path, '/api/billing/setup-intent'); return pending.promise;
  }});
  const loading = f.viewBilling(); await flush(); const next = leaveView(f);
  pending.resolve(response({client_secret: 'synthetic-secret'})); await loading;
  assert.equal(stripe.calls.mounted, 0); assert.equal(f.root.writes, next.rootWrites);
  assert.deepEqual(postRequests(f).map(row => row.path), ['/api/billing/setup-intent']);
});

for (const stage of ['confirmation', 'card-added']) for (const failure of [false, true]) {
  test(`Billing ignores departed ${stage} ${failure ? 'failure' : 'success'} without another action or UI write`, async () => {
    const pending = deferred(); let reads = 0;
    const stripe = stripeFixture(stage === 'confirmation' ? () => pending.promise : undefined);
    const f = frontend({stripeLoader: async () => stripe.Stripe, fetchImpl: path => {
      if (path === '/api/billing') { reads++; return response(billingData({configured: true})); }
      if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic-secret'});
      assert.equal(path, '/api/billing/card-added'); return stage === 'card-added' ? pending.promise : response({ok: true});
    }});
    await f.viewBilling();
    const save = f.root.querySelector('#save-card'), saving = save.onclick({currentTarget: save});
    await flush();
    const next = leaveView(f, '<main><div id="card-flash">Fresh card panel</div></main>');
    if (stage === 'confirmation') pending.resolve(failure ? {error: {message: 'Synthetic confirmation failure'}} : {setupIntent: {payment_method: 'synthetic-pm'}});
    else pending.resolve(failure ? response({error: 'Synthetic card record failure'}, 503) : response({ok: true}));
    await saving;
    assert.equal(f.root.querySelector('#card-flash').innerHTML, 'Fresh card panel');
    assert.equal(f.root.writes, next.rootWrites); assert.equal(next.main.writes, 0); assert.equal(reads, 1);
    assert.deepEqual(postRequests(f).map(row => row.path), stage === 'confirmation'
      ? ['/api/billing/setup-intent'] : ['/api/billing/setup-intent', '/api/billing/card-added']);
  });
}

for (const label of ['Billing topup', 'Funds demo reload', 'Admin credit grant']) for (const failure of [false, true]) {
  test(`${label} ignores a departed ${failure ? 'failure' : 'success'} without follow-up reads or UI writes`, async () => {
    const pending = deferred(), stripe = stripeFixture(); let reads = 0;
    const initialPath = {'Billing topup': '/api/billing', 'Funds demo reload': '/api/funds', 'Admin credit grant': '/api/admin'}[label];
    const actionPath = {'Billing topup': '/api/billing/topup', 'Funds demo reload': '/api/funds/demo', 'Admin credit grant': '/api/admin/grant'}[label];
    const f = frontend({stripeLoader: async () => stripe.Stripe, fetchImpl: path => {
      if (path === initialPath) { reads++; return response(label === 'Billing topup'
        ? billingData({configured: true, cards: [{id: 'synthetic-card'}]}) : label === 'Funds demo reload' ? funds() : {users: [], waitlist: []}); }
      if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic-secret'});
      assert.equal(path, actionPath); return pending.promise;
    }});
    f.S.me.is_admin = true;
    if (label === 'Billing topup') {
      await f.viewBilling(); const button = f.root.querySelector('#topup-btn'); button.onclick({currentTarget: button});
    } else if (label === 'Funds demo reload') {
      await f.viewFunds(); const form = f.root.querySelector('#demo'); form.amount = {value: '1250'};
      form.onsubmit({preventDefault() {}});
    } else {
      await f.viewAdmin(); f.root.querySelector('#g-email').value = 'synthetic@example.invalid'; f.root.querySelector('#g-amt').value = '10';
      const form = f.root.querySelector('#grant'); form.onsubmit({preventDefault() {}, target: form});
    }
    await flush();
    const host = {'Billing topup': 'topup-flash', 'Funds demo reload': 'dmflash', 'Admin credit grant': 'g-flash'}[label];
    const next = leaveView(f, `<main><div id="${host}">Fresh action panel</div></main>`);
    pending.resolve(failure ? response({error: 'Synthetic departed action failure'}, 503) : response({balance: 20, email: 'synthetic@example.invalid'}));
    await flush();
    assert.equal(reads, 1); assert.equal(f.root.querySelector('#' + host).innerHTML, 'Fresh action panel');
    assert.equal(f.root.writes, next.rootWrites); assert.equal(next.main.writes, 0);
    const action = postRequests(f).find(row => row.path === actionPath); assert.ok(action);
    assert.deepEqual(JSON.parse(action.options.body), label === 'Billing topup' ? {amount: 20}
      : label === 'Funds demo reload' ? {amount: 1250} : {email: 'synthetic@example.invalid', amount: 10});
  });
}

test('Meridian retains Settings theme, account, billing and system deep links', () => {
  const f = frontend(), route = path => f.routes.find(([pattern]) => pattern.test(path))?.[1];
  for (const path of ['/settings', '/settings/theme']) assert.equal(route(path), f.viewSettings);
  for (const path of ['/funds', '/settings/account']) assert.equal(route(path), f.viewFunds);
  for (const path of ['/billing', '/settings/billing']) assert.equal(route(path), f.viewBilling);
  for (const path of ['/system', '/settings/system']) assert.equal(route(path), f.viewSystem);
});

test('Meridian theme selection stays local to the theme preference and can switch back to Tau', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/ui-theme'); return response({ok: true, theme: 'tau'}); }});
  await f.viewSettings();
  const selected = f.root.querySelector('[data-theme="meridian"]');
  assert.equal(selected.getAttribute('aria-checked'), 'true');
  selected.onclick(); await flush();
  assert.equal(postRequests(f).length, 0); assert.deepEqual(f.reloads, []);
  f.root.querySelector('[data-theme="tau"]').onclick(); await flush();
  assert.equal(f.storage.get('tau_ui'), 'tau'); assert.deepEqual(f.reloads, [true]);
  assert.equal(postRequests(f).length, 1);
  assert.equal(postRequests(f)[0].path, '/api/ui-theme');
  assert.deepEqual(JSON.parse(postRequests(f)[0].options.body), {theme: 'tau'});
});

test('theme preference save failure retains the existing local fallback without financial writes', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/ui-theme'); return response({error: 'Synthetic unavailable preference service'}, 503); }});
  await f.viewSettings(); f.root.querySelector('[data-theme="tau"]').onclick(); await flush();
  assert.equal(f.storage.get('tau_ui'), 'tau'); assert.deepEqual(f.reloads, [true]);
  assert.deepEqual(postRequests(f).map(row => row.path), ['/api/ui-theme']);
});

for (const build of [undefined, 'meridian-current', 'meridian-old']) {
  test(`Meridian navigation stays free of version requests and update banners: ${build || 'missing build'}`, async () => {
    const f = frontend({build, fetchImpl: path => {
      if (path === '/' || path === '/api/version') return {
        ok: true, text: async () => '<div id="tau-boot" data-mer-ver="meridian-new"></div>',
        json: async () => ({v: 'different-tau-build'}),
      };
      throw new Error('Unexpected fixture request: ' + path);
    }});
    f.location.pathname = '/settings';
    for (let navigation = 0; navigation < 3; navigation++) {
      await f.render();
      assert.equal(f.document.getElementById('verbar'), null);
      assert.equal(f.root.getAttribute('aria-busy'), 'false');
      assert.ok(f.root.querySelector('[data-theme="meridian"]'), 'settings still renders');
    }
    assert.deepEqual(f.requests.filter(row => row.path === '/' || row.path === '/api/version'), []);
    assert.equal(postRequests(f).length, 0); assert.deepEqual(f.reloads, []);
  });
}

for (const [label, stored, blocked, expected] of [['default', null, false, 'tau'], ['saved Meridian', 'meridian', false, 'meridian'], ['saved Tau', 'tau', false, 'tau'], ['blocked storage', null, true, 'tau']]) {
  test(`unchanged bootstrap selects the correct isolated bundle: ${label}`, () => {
    const scripts = [], css = {href: '/static/app.css?v=tau-css'};
    const dataset = {tauJs: '/static/app.js?v=tau-js', tauVer: 'tau-js', merJs: '/static/app.meridian.js?v=mer-js', merVer: 'mer-js', merCss: '/static/app.meridian.css?v=mer-css'};
    const context = {window: {}, localStorage: {getItem: () => { if (blocked) throw new Error('Synthetic blocked storage'); return stored; }},
      document: {getElementById: id => id === 'tau-boot' ? {dataset} : id === 'tau-css' ? css : null,
        createElement: tag => { assert.equal(tag, 'script'); return {}; }, body: {appendChild: script => scripts.push(script)}}};
    vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
    assert.equal(context.window.__TAU_UI__, expected); assert.equal(scripts.length, 1);
    assert.equal(scripts[0].src, expected === 'meridian' ? dataset.merJs : dataset.tauJs);
    assert.equal(context.window.__BUILD__, expected === 'meridian' ? dataset.merVer : dataset.tauVer);
    assert.equal(css.href, expected === 'meridian' ? dataset.merCss : '/static/app.css?v=tau-css');
  });
}

test('a research session that does not exist links to the list instead of offering Try again', async () => {
  const f = frontend({fetchImpl: path => (path.startsWith('/api/runs/9') ? {ok: false, status: 404, json: async () => ({error: 'No such research run.'})} : {ok: true, status: 200, json: async () => ({})})});
  f.location.pathname = '/research/9';
  await f.render(); await flush();
  const html = f.root.innerHTML;
  assert.match(html, /No such research run\./); assert.match(html, /href="\/research">All research sessions</);
  assert.doesNotMatch(html, /data-retry/);
});

test('the legal pages load in Tau even for a Meridian user, since only Tau has them', () => {
  for (const [pathname, expected] of [['/terms', 'tau'], ['/privacy', 'tau'], ['/settings', 'meridian']]) {
    const scripts = [], css = {href: '/static/app.css?v=tau-css'};
    const dataset = {tauJs: '/static/app.js?v=tau-js', tauVer: 'tau-js', merJs: '/static/app.meridian.js?v=mer-js', merVer: 'mer-js', merCss: '/static/app.meridian.css?v=mer-css'};
    const context = {window: {}, location: {pathname}, localStorage: {getItem: () => 'meridian'},
      document: {getElementById: id => id === 'tau-boot' ? {dataset} : id === 'tau-css' ? css : null,
        createElement: () => ({}), body: {appendChild: script => scripts.push(script)}}};
    vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
    assert.equal(context.window.__TAU_UI__, expected, pathname);
    assert.equal(scripts[0].src, expected === 'meridian' ? dataset.merJs : dataset.tauJs);
  }
});

test('a shell that already links its theme makes boot.js only record it, with no swap or second bundle', () => {
  for (const [ui, stored, pathname, expected, saved] of [['meridian', null, '/', 'meridian', 'meridian'],
    ['tau', 'meridian', '/', 'tau', 'tau'], ['tau', 'meridian', '/terms', 'tau', undefined]]) {
    const scripts = [], css = {href: 'shell-linked'}, writes = {};
    const dataset = {ui, tauJs: '/static/app.js?v=tau-js', tauVer: 'tau-js', merJs: '/static/app.meridian.js?v=mer-js', merVer: 'mer-js', merCss: '/static/app.meridian.css?v=mer-css'};
    const context = {window: {}, location: {pathname},
      localStorage: {getItem: () => stored, setItem: (k, v) => { writes[k] = v; }},
      document: {getElementById: id => id === 'tau-boot' ? {dataset} : id === 'tau-css' ? css : null,
        createElement: () => ({}), body: {appendChild: script => scripts.push(script)}}};
    vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
    assert.equal(context.window.__TAU_UI__, expected, ui + pathname);
    assert.equal(context.window.__BUILD__, expected === 'meridian' ? dataset.merVer : dataset.tauVer);
    assert.equal(scripts.length, 0); assert.equal(css.href, 'shell-linked');
    assert.equal(writes.tau_ui, saved);  // a forced Tau legal page never overwrites a saved Meridian
  }
});

test('Meridian has a page for every app path the server serves, bar the legal pages boot.js sends to Tau', () => {
  const f = frontend();
  for (const path of ['/', '/dashboard', '/research', '/research/1', '/strategies', '/strategies/1', '/deploy', '/community',
    '/billing', '/admin', '/system', '/funds', '/explore', '/devlog', '/track-record', '/settings', '/settings/account',
    '/settings/billing', '/settings/system', '/settings/theme', '/signin']) assert.ok(f.routes.some(([re]) => re.test(path)), path);
});

test('Meridian empty paper track record points at autopilot when it is on', () => {
  const f = frontend(), th = {min_sharpe_days: 30};
  f.S.me = {user: {autopilot: true}};
  const paper = f.trackRecordPanel({trades: 0, label: 'Paper'}, 'paper', th);
  assert.match(paper, /Autopilot runs the strategies that pass every gate on paper/);
  assert.match(paper, /See its research/); assert.doesNotMatch(paper, /Go to Deploy/);
  assert.match(f.trackRecordPanel({trades: 0, label: 'Demo'}, 'demo', th), /Go to Deploy/);
});

test('a research run shows what it has cost so far from its ledger debits, and its cost once finished', async () => {
  for (const [status, label] of [['running', 'Spent so far'], ['succeeded', 'Cost'], ['failed', 'Cost']]) {
    const run = {...researchRun(9, status), spent_usd: 1.8372};
    const f = frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: []}); }});
    await f.viewRun(9);
    assert.match(f.root.querySelector('#runfigs').innerHTML, new RegExp(`${label}</dt><dd><span class="fig ">\\$1\\.84</span>`), status);
    f.clearTimers();
  }
  const f = frontend({fetchImpl: () => response({run: researchRun(9, 'running'), events: []})});
  await f.viewRun(9);
  assert.doesNotMatch(f.root.querySelector('#runfigs').innerHTML, /Spent so far|Cost/);
  f.clearTimers();
});

test('Research history rows state each session\'s cost from the ledger', async () => {
  const f = researchFrontend([{...researchRun(3, 'succeeded'), spent_usd: 2.5}, researchRun(4, 'failed')]);
  await f.viewResearch(); await flush();
  const html = f.root.querySelector('#runs').innerHTML;
  assert.match(html, /href="\/research\/3"[\s\S]*?Cost: \$2\.50/);
  assert.doesNotMatch(html.split('href="/research/4"')[1], /Cost:/);  // no figure from the server, no claim
  f.clearTimers();
});

test('the Overview autopilot card and panel say where it may trade, with a Change that opens the focus control', async () => {
  let status = {...apStatus, focus: ['crypto']};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData());
    if (path === '/api/autopilot/status') return response(status);
    if (path === '/api/settings') { status = {...status, autopilot: true, mode: 'paper'}; return response({ok: true}); }  // the server now reports it on
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = true;
  await f.viewDashboard(); await flush();
  f.S.ap = status; f.paintDashAp();
  const card = f.root.querySelector('#dash-ap');
  assert.match(card.querySelector('.ap-focus').innerHTML, /^Focus: Crypto <button type="button" data-apcard="focus">Change<\/button>$/);
  await card.querySelector('[data-apcard="focus"]').onclick(); await flush();
  const box = f.root.parent.querySelector('#autopilot-float'), prefs = box.querySelector('.apf-prefs');
  assert.equal(prefs.open, true);  // the control sits in "Model and markets"
  const line = box.querySelector('#apf-focusline');
  assert.equal(line.hidden, false); assert.match(line.innerHTML, /^Focus: Crypto <button type="button" data-ap="focus">Change<\/button>$/);
  prefs.open = false; line.querySelector('[data-ap="focus"]').onclick();
  assert.equal(prefs.open, true);
  for (const [focus, text] of [[[], 'any market'], [['sports'], 'Sports'], [['weather-low'], 'Weather low']]) {
    f.S.ap = {...apStatus, focus}; f.paintDashAp();
    assert.match(f.root.querySelector('#dash-ap .ap-focus').innerHTML, new RegExp(`^Focus: ${text} <button`), text);
  }
  // Switching on from the panel opens the focus control right away.
  status = {...apStatus, autopilot: false, mode: 'off', focus: []};
  f.S.me.user.autopilot = false; f.S.ap = status; prefs.open = false;
  const sw = box.querySelector('#apf-apswitch'); sw.checked = true; await sw.onchange(); await flush();
  assert.equal(f.S.me.user.autopilot, true); assert.equal(prefs.open, true);
  f.clearTimers();
});

test('the Overview autopilot card and panel show the last 7 days with real credits and paper P&L kept apart', async () => {
  const week = {research_credits: 0.5, tested: 12, passed: 0, paper_started: 3, paper_pnl: 1.25, paper_trades: 1};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData());
    if (path === '/api/autopilot/status') return response({...apStatus, week});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = true;
  await f.viewDashboard(); await flush();
  f.S.ap = {...apStatus, week}; f.paintDashAp();
  const card = f.root.querySelector('#dash-ap .ap-week').innerHTML;
  assert.match(card, /<dt>Credits spent on research<\/dt><dd>\$0\.50 <small>real money<\/small><\/dd>/);
  assert.match(card, /<dt>Autopilot put on paper<\/dt><dd>3 strategies <small>not counting yours<\/small><\/dd>/);
  assert.match(card, /<dt>Autopilot's paper P&amp;L<\/dt><dd><span class="pos">\+\$1\.25<\/span> <small>paper, not real money ·\u00a01 closed trade<\/small><\/dd>/);
  assert.doesNotMatch(card, /\$1\.75|\$0\.75/);  // never netted or summed
  await f.root.querySelector('#dash-ap [data-apcard="open"]').onclick(); await flush();
  const box = f.root.parent.querySelector('#autopilot-float');
  assert.match(box.querySelector('#apf-week').innerHTML, /Last 7 days[\s\S]*paper, not real money/);
  // Before a week has been read the card shows its old ideas figure and no scorecard.
  f.S.ap = {...apStatus}; f.paintDashAp();
  assert.equal(f.root.querySelector('#dash-ap .ap-week'), null);
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /Ideas this week/);
  f.clearTimers();
});

test('Research says what a session usually costs beside Start session, and nothing without data', async () => {
  let f = researchFrontend([], {estimate: {yours: 0.42, sessions: 4, typical: {}}}); await f.viewResearch(); await flush();
  const cost = () => f.root.querySelector('#rcost');
  assert.equal(cost().hidden, false);
  assert.equal(cost().textContent, 'Each round of ideas usually costs about $0.42 (your recent sessions); it keeps starting new rounds until you stop it.');
  const rf = f.root.querySelector('#runforever'); rf.checked = false; rf.dispatchEvent({type: 'change'});
  assert.equal(cost().textContent, 'Usually about $0.42 (your recent sessions).');
  f = researchFrontend([], {estimate: {yours: null, sessions: 2, typical: {offline: 3.1}}}); await f.viewResearch(); await flush();
  assert.match(cost().textContent, /about \$3\.10 \(recent sessions on this model\)/);
  f = researchFrontend([]); await f.viewResearch(); await flush();
  assert.equal(cost().hidden, true); assert.equal(cost().textContent, '');
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
const sparkPayload = () => ({...dashboardData(), deployments: [
  sparkDeployment(1, 'paper', 48, [[1760000000, 2], [1760003600, -1], [1760007200, 500], [1760010800, 12.4]]),
  sparkDeployment(2, 'live', 2, [[1760000000, -1], [1760003600, -3]]),
  sparkDeployment(3, 'paper', 1, [[1760000000, 1]]),
]});
for (const [label, view, endpoint, selector] of [['Overview', 'viewDashboard', '/api/dashboard', 'main'], ['Deploy', 'viewDeploy', '/api/deployments', '#deps']]) {
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

const staleDashboard = equity => dashboardData({paper: {equity}});

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
    const figures = () => f.root.querySelector('main').innerHTML;
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
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.ok(!/winCard|data-dig|win-card/.test(source), 'winCard has no callers; its markup and click hook stay deleted');
  assert.ok(!/\.wins?\b|\.win-(card|title|meta|foot|pnl|act)\b/.test(css), 'and so does its CSS');
  const touch = css.slice(css.indexOf('@media (pointer: coarse)'));
  const block = touch.slice(0, touch.indexOf('\n}\n'));
  assert.match(block, /\.masthead \.bell-trig \{ min-width: 44px;/);
  assert.match(block, /\.market-control \.hot-tab \{ width: 44px; \}/);
  assert.match(block, /\.info \{ width: 40px; height: 40px;/);
  assert.match(css, /\.research-ap button \{[^}]*padding: 10px 4px; margin: -10px -4px;/);
  assert.match(css, /\.ap-focus button \{[^}]*padding: 10px 4px; margin: -10px -4px -10px 0;/);
  assert.match(css, /\.rsidisc \.pipechev \{ position: absolute; right: 14px;/);
});

test('Meridian phone polish: a glossary marker keeps its last word, one rule where boxes meet, touch controls 40px or more', async () => {
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  const perps = readFileSync(new URL('../app/static/kalshi-perps-live.css', import.meta.url), 'utf8');
  const f = frontend({fetchImpl: path => (path.startsWith('/api/strategies?')
    ? response({strategies: [], counts: {total: 3, passed: 1, failed: 1, rejected: 1}}) : response({}))});
  await f.viewStrategies(); await flush(); await flush();
  const figs = f.root.querySelector('#sfigs').innerHTML;
  // The marker shares a no-wrap span with the label's last word, so it never wraps onto a line of its own.
  assert.match(figs, /Void on unseen <span class="nobr">data<button type="button" class="info" data-glo="void"/);
  assert.match(figs, /Rejected in <span class="nobr">testing<button type="button" class="info" data-glo="rejected"/);
  assert.doesNotMatch(source, /fig\('[^']*' \+ glo\(/, 'figure labels go through gl(), not label + glo()');
  assert.match(css, /\.nobr \{ white-space: nowrap; \}/);
  // The double dividers: the research-policy box on the progress section's top rule (run page), and
  // a stacked position card's rule 4-9px above the next family's heading or Recent settlements (dashboard).
  assert.match(css, /#rsibox:not\(:empty\) \+ \.rsiobs \{ border-top: 0; \}/);
  assert.match(css, /@container dashboard \(max-width: 779px\) \{\n  \.t-positions tbody > tr:last-child \{ border-bottom: 0; \}\n\}/);
  assert.match(css, /\.pipefig:not\(\[open\]\) > \.pipecap \{ border-bottom: 0; \}/);
  // Phone: the RSI tag sits under the title, the system map scrolls sideways at a readable size.
  const phone = css.slice(css.lastIndexOf('@media (max-width: 760px)'));
  assert.match(phone, /\.rsidisc-cap > \.rsi-tag, \.rsidisc-cap > \.rsidisc-delta \{ grid-column: 2;/);
  assert.match(phone, /\.sys-wrap \{ overflow-x: auto;/);
  // Touch: every field, summary, slider and small link that measured under 40px at 360px.
  const touch = css.slice(css.lastIndexOf('@media (pointer: coarse)'));
  const block = touch.slice(0, touch.indexOf('\n}\n'));
  assert.match(block, /\.input, select, input\[type=text\][^{]*\.post-tools select, \.explore-filters \.input \{ min-height: 44px; \}/);
  assert.match(block, /input\[type=range\], \.dial input\[type=range\] \{ height: 40px; \}/);
  assert.match(block, /details > summary \{ padding-block: 11px; min-height: 40px; \}/);
  assert.match(block, /\.wordmark a \{ padding: 3px 5px; margin: -3px -5px; \}/);
  assert.match(block, /\.legal-nav a, \.legal-foot a, \.lfoot-links a, \.linkish \{ padding: 10px 4px; margin: -10px -4px; \}/);
  assert.doesNotMatch(block, /#dep-(paper|demo|live)|\.go\b|strat-quick/);
  // Funds: the perps ticket's buttons, fields and checkboxes were 34px and 16px.
  assert.match(perps, /@media \(pointer: coarse\) \{\n  \.kalshi-perps-live \.btn, \.kp-field input, \.kp-field select, \.kp-reduce, \.kp-check \{ min-height: 44px; \}/);
});

test('Meridian: separators wrap with the item after them, the phone tabs show which edge has more, stacked cells are named', () => {
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

test('Meridian: a finished session says what to do next: your own idea after the example, the passed strategy after yours', async () => {
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
  assert.match(await at({status: 'succeeded'}, [{id: 43, title: 'Fade', status: 'rejected'}]), /Nothing passed this time\. Most ideas don’t\. Each strategy below says which check it missed and what to try next\. <a href="\/research\?new=1">Try another idea<\/a>/);
  assert.equal(await at({status: 'running'}, []), '');  // still going: nothing to do yet
});

test('Meridian: after a deploy the Deploy page offers autopilot in words, and the panel says what its switch does', async () => {
  const f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [dashboardDeployment('paper')], open_positions: []}) : response({})});
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
      if (path.startsWith('/api/dashboard')) return response({...dashboardData(), deployments, ...extra});
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
  assert.match(text, /<a href="#dash-paused">Paused one<\/a> is paused<span class="since-sub">: lost \$12\.00<\/span>/);
  assert.match(text, /<a href="\/research">1 research session failed<\/a>/);
  const host = f.root.querySelector('main').innerHTML;
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
    if (path.startsWith('/api/dashboard')) return response({...dashboardData(), deployments: []});
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
      if (path.startsWith('/api/dashboard')) return response({...dashboardData(), deployments: [], since: {at: '2026-10-25T08:00:00+00:00', first: true,
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
    assert.deepEqual(folds.map((d) => d.querySelector('summary').textContent), ['Most recent unseen trades', 'Methodology', 'Sensitivity']);
    for (const d of folds) assert.equal('open' in d.attributes, open);
    assert.ok(f.root.querySelector('#whatif').closest('details.fold'));
    for (const sel of ['#figs', '#dep-paper', '#gates']) assert.equal(f.root.querySelector(sel).closest('details.fold'), null, sel);
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
const billingPage = (data, posts = []) => frontend({stripeLoader: async () => STRIPE_STUB, fetchImpl: (path, options = {}) => {
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
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /@media \(max-width: 1080px\) \{ \.bill-detail > aside \{ order: -1; \} \}/);
  assert.match(f.root.innerHTML, /The <a href="\/research">research form<\/a> shows what a session usually costs before you start\./);
});

test('the Remove button stays disabled, with the server\'s reason, while a stopped deployment still holds positions', async () => {
  const reason = "This strategy still holds 2 open positions (paper: 1, live: 1). They'll close at settlement; delete it after that.";
  for (const block of [reason, null]) {
    const f = strategyFrontend(detailStrategy({delete_block: block, deployments: [{id: 9, mode: 'paper', status: 'stopped', market: 'btc15m'}]}),
      () => response({deployments: [], open_positions: []}));
    await f.viewStrategy(42); await flush();
    const del = f.root.querySelector('#del-strat'), why = f.root.querySelector('#del-why');
    if (block) {
      assert.equal(del.attributes['aria-disabled'], 'true'); assert.equal(del.attributes['aria-describedby'], 'del-why');
      assert.match(why.innerHTML, /still holds 2 open positions \(paper: 1, live: 1\)\. They.+ll close at settlement; delete it after that\./);
      await del.onclick(); await flush();
      assert.match(f.root.querySelector('#delflash').innerHTML, /still holds 2 open positions \(paper: 1, live: 1\)/);
    } else {
      assert.equal('aria-disabled' in del.attributes, false);
      assert.match(why.innerHTML, /Permanently deletes this strategy\./);
    }
    assert.equal(postRequests(f).length, 0);  // a click arms a confirm or explains; it never deletes
    f.clearTimers();
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
    f.clearTimers();
  }
});

test('the since strip says what demo needs in a sentence, and a book with nothing closed keeps its name', async () => {
  const since = {at: '2026-10-25T08:00:00+00:00', first: false, books: {demo: {pnl: 0, trades: 0}},
    passed: {n: 0, items: []}, autopilot: {}, runs: {}};
  const deployments = [{id: 4, strategy_id: 4, title: 'On demo', market: 'btc15m', mode: 'demo', status: 'running',
    stake: 5, max_positions: 2, realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 0, curve: [], created_at: '2026-10-25T08:00:00Z'}];
  const strip = async (health) => {
    const base = dashboardData();
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
      if (path.startsWith('/api/dashboard')) return response(dashboardData());
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

test('a deployed book with nothing open says so instead of "Unavailable"', async () => {
  const dep = (id, open) => ({id, strategy_id: id, title: 'Book ' + id, market: 'btc15m', mode: 'paper', status: 'running',
    stake: 5, max_positions: 2, realized_pnl: 1, unrealized_pnl: null, closed_trades: 3, open_positions: open, curve: [], created_at: '2026-10-25T08:00:00Z'});
  const f = frontend({fetchImpl: path => {
    if (path.startsWith('/api/dashboard')) return response(dashboardData({deployments: [dep(1, 0), dep(2, 2)]}));
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const cells = f.root.querySelectorAll('.monitor-unrealized').map((c) => c.innerHTML);
  assert.equal(cells.length, 2);
  assert.match(cells[0], /<span class="unavailable">None open<\/span>/);
  assert.match(cells[1], /<span class="unavailable">Unavailable<\/span>/);
});

test('Meridian CSS: open-positions why line wraps, "Not connected" keeps its small size on phones, ledger notes wrap', () => {
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.pos-why \{[^}]*white-space: normal;/);
  assert.match(css, /#openpos td\.name \{ white-space: normal;/);
  const phone = css.indexOf('.account-band .portfolio-numbers .fig { font-size: 28px');
  const state = css.indexOf('.account-band .portfolio-numbers .fig.balance-state { font-size: 20px');
  assert.ok(phone > 0 && state > phone, 'the state size comes after the phone figure size');
  assert.match(css, /\.t-ledger\.stack tbody td\.name \{[^}]*flex-wrap: wrap; \}\n  \.t-ledger\.stack tbody td\.name \.sub-fig \{ min-width: 0; flex: 0 1 auto; \}/);
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

// Why an idea did not pass (server services.gate_explain): every place that shows the verdict lists
// each missed gate with what was measured, what was needed and one thing to try next, escaped.
const MISSED = [
  {gate: 'sample_size', label: 'Enough trades to judge', measured: '18 trades on the unseen test window',
    needed: 'at least 30 trades (fixed before the test)', next: 'Needs about 12 more trades: widen the market set or lengthen the test window, or loosen the entry rule so it fires more often.'},
  {gate: 'other', label: 'Min <b>sharpe</b> ratio', measured: '0.4', needed: 'at least 0.5', next: 'Change one thing about the rule and test again, so you can see what moves this check.'},
];
const MISSED_ROWS = [
  ['Enough trades to judge', 'Measured 18 trades on the unseen test window; needed at least 30 trades (fixed before the test).', MISSED[0].next],
  ['Min &lt;b&gt;sharpe&lt;/b&gt; ratio', 'Measured 0.4; needed at least 0.5.', MISSED[1].next],
];
const missedRows = html => [...String(html).matchAll(/<li><b class="wf-label">([^<]*)<\/b><span class="wf-fig">([^<]*)<\/span><span class="wf-next"><b>Try next:<\/b> ([^<]*)<\/span><\/li>/g)].map(m => m.slice(1));

test('Meridian: a run says per missed gate what was measured, what was needed and what to try next', async () => {
  const run = {id: 9, status: 'succeeded', prompt: 'Session 9', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', hypotheses_tried: 3, strategies_passed: 1};
  const at = '2026-10-17T10:01:00Z';
  const events = [
    {id: 1, kind: 'hypothesis', message: 'Fade the spike', created_at: at, data: {in_sample: {pnl: 4.5, trades: 8}}},
    {id: 2, kind: 'verdict', message: 'FAILED - Fade the spike: validation verdict is gatekeeper-held (classification=inconclusive, 18 trades); the numbers never return to the generator.',
      created_at: at, data: {status: 'failed', title: 'Fade the spike', strategy_id: 41, classification: 'inconclusive', stats: {n_trades: 18}, why_failed: MISSED}},
    {id: 3, kind: 'hypothesis', message: 'Lean in', created_at: at, data: {in_sample: {pnl: 3, trades: 9}}},
    {id: 4, kind: 'verdict', message: 'PASSED - Lean in: cleared every gate', created_at: at, data: {status: 'passed', title: 'Lean in', strategy_id: 42, why_failed: []}},
    {id: 5, kind: 'verdict', message: 'Lean in: one-time holdout verdict is gatekeeper-held (classification=rejected, 40 trades); the numbers never return to the generator.',
      created_at: at, data: {title: 'Lean in', phase: 'holdout', classification: 'rejected', why_failed: [MISSED[0]]}},
  ];
  const strategies = [{id: 41, title: 'Fade the spike', status: 'failed', market: 'btc15m', direction: 'momentum'},
    {id: 42, title: 'Lean in', status: 'passed', market: 'btc15m', direction: 'momentum'}];
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run, events, strategies}) : response({})});
  await f.viewRun(9); await flush();
  const items = f.root.querySelector('#log').children.filter((li) => li.tag === 'li');
  const reviews = items.map((li) => (li.querySelector('[data-review]') || {innerHTML: ''}).innerHTML).filter(Boolean);  // the two hypothesis cards
  assert.deepEqual(missedRows(reviews[0]), MISSED_ROWS);
  assert.doesNotMatch(reviews[0], /classification=|gatekeeper-held|<b>sharpe/);  // the plain lines replace the raw note
  assert.deepEqual(missedRows(reviews[1]), []);  // a pass lists nothing it missed
  assert.match(reviews[1], /cleared every gate/);
  // A verdict with no card of its own (the one-time holdout) lists its lines on its own row.
  const holdout = items[items.length - 1].innerHTML;
  assert.deepEqual(missedRows(holdout), [MISSED_ROWS[0]]);
  assert.doesNotMatch(holdout, /classification=/);
  // The agent log folds shut once a session ends, so the Strategies list carries each miss too:
  // the first gate under the strategy's name, and a link to the rest on its page; a pass shows none.
  const rows = f.root.querySelector('#run-artifacts').innerHTML.split('<tr').slice(2);
  assert.deepEqual(missedRows(rows[0]), [MISSED_ROWS[0]]);
  assert.match(rows[0], /<a class="sub-fig" href="\/strategies\/41">1 more check on its page<\/a>/);
  assert.doesNotMatch(rows[1], /slip-missed/);
  f.clearTimers();
  // Nothing passed: the next-step line says where the reasons are.
  const none = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run: {...run, strategies_passed: 0}, events: [], strategies: [{id: 41, title: 'Fade', status: 'failed'}]}) : response({})});
  await none.viewRun(9); none.clearTimers();
  assert.match(none.root.querySelector('#runnext').innerHTML, /Each strategy below says which check it missed and what to try next\./);
});

test('Meridian: the strategy page lists what it missed under Verdict and names the first in the Deploy notice', async () => {
  const f = strategyFrontend(detailStrategy({status: 'failed', why_failed: MISSED})); await f.viewStrategy(42); await flush();
  const html = f.root.querySelector('main').innerHTML;
  const at = html.indexOf('What it missed, and what to try next');
  assert.ok(at > html.indexOf('Verdict'), 'listed in the Verdict section');
  assert.deepEqual(missedRows(html.slice(at)).slice(0, 2), MISSED_ROWS);
  assert.match(html, /Void: it missed “Enough trades to judge” and 1 more check \(see Verdict\)\. It wasn’t validated/);
  assert.doesNotMatch(html, /failed the unseen-data gate|<b>sharpe/);
  const r = strategyFrontend(detailStrategy({status: 'rejected', why_failed: [MISSED[0]]})); await r.viewStrategy(42); await flush();
  assert.match(r.root.querySelector('main').innerHTML, /Rejected: it missed “Enough trades to judge” \(see Verdict\)\./);
  // Passed, or an older server without the field: nothing extra, and the old notice stands.
  for (const extra of [{why_failed: []}, {}]) {
    const p = strategyFrontend(detailStrategy(extra)); await p.viewStrategy(42); await flush();
    assert.doesNotMatch(p.root.querySelector('main').innerHTML, /What it missed|class="why-failed"/);
  }
  const old = strategyFrontend(detailStrategy({status: 'failed'})); await old.viewStrategy(42); await flush();
  assert.match(old.root.querySelector('main').innerHTML, /Void: it failed the unseen-data gate\./);
});

// The research paper's figures are red exactly when the gate that judges them missed. The server
// judges each figure with the gatekeeper's own thresholds (services.gate_explain.strategy_tints, the
// same checks that write why_failed); the page restates no cutoff. These fixtures are what the server
// sends for these numbers (tests/test_gate_explain.py pins the server side).
const FIGURE_GATES = {'Trades': ['sample_size'], 'Bootstrap p-value': ['significance', 'multiple_testing'],
  'Mean net return / trade': ['net_edge'], 'DSR': ['deflated_sharpe'], 'Placebo p-value': ['placebo']};
const tintedFigures = html => [...String(html).matchAll(/<div class="rp-stat"><div class="k">([^<]*)<\/div><div class="val( sig)?">/g)]
  .filter(m => m[2]).map(m => m[1].replace(/&amp;/g, '&'));
const missedFigures = lines => Object.keys(FIGURE_GATES).filter(k => lines.some(l => FIGURE_GATES[k].includes(l.gate)));
const paperSections = html => {
  const at = html.indexOf('The one-time locked holdout');
  return {validation: html.slice(html.indexOf('Validation-window evidence'), at), holdout: html.slice(at)};
};

test('Meridian: a research-paper figure is red exactly when its gate line says it missed', async () => {
  // Failing: 20 trades under a minimum of 30, p 0.08 over its 0.05 level, the CI low end below zero.
  // The DSR (0.70) and the placebo p (0.05) pass their gates (DSR_MIN 0.5, ALPHA 0.10), so they stay
  // ink, though the old page cutoffs (DSR 0.95, placebo p under 0.10) painted both red.
  const VAL_LINES = [{gate: 'sample_size'}, {gate: 'significance'}, {gate: 'net_edge'}].map(l => ({...l, label: l.gate, measured: 'x', needed: 'y', next: 'Z.'}));
  const failing = {classification: 'inconclusive', min_sample: 30,
    validation: {n_trades: 20, p_value: 0.08, fdr_alpha_i: 0.05, dsr: 0.7, psr: 0.2, placebo_p: 0.05, ci_lo: -0.001, ci_hi: 0.02, mean_net_return: 0.004},
    holdout: null,
    gate_tints: {validation: {n_trades: 'fail', p_value: 'fail', mean_net_return: 'fail', dsr: 'pass', placebo_p: 'pass'}}};
  const f = strategyFrontend(detailStrategy({status: 'failed', experiment: failing, why_failed: VAL_LINES})); await f.viewStrategy(42); await flush();
  const red = tintedFigures(paperSections(f.root.querySelector('main').innerHTML).validation);
  assert.deepEqual(red.sort(), missedFigures(VAL_LINES).sort());
  assert.deepEqual(red.sort(), ['Bootstrap p-value', 'Mean net return / trade', 'Trades']);
  // Passed validation, failed holdout: the validation figures all pass (DSR 0.60 and placebo 0.02
  // would have been red under the old cutoffs); the holdout's p-value and mean are red as its lines
  // say, its sample is not judged, and a consumed holdout is a state, not a miss.
  const HOLD_LINES = [{gate: 'significance'}, {gate: 'net_edge'}].map(l => ({...l, label: l.gate, measured: 'x', needed: 'y', next: 'Z.'}));
  const held = {classification: 'rejected', min_sample: 30,
    validation: {n_trades: 90, p_value: 0.01, fdr_alpha_i: 0.05, dsr: 0.6, placebo_p: 0.02, ci_lo: 0.001, ci_hi: 0.02, mean_net_return: 0.01},
    holdout: {classification: 'rejected', n_trades: 12, p_value: 0.3, ci_lo: -0.01, ci_hi: 0.02, mean_net_return: 0.004, consumed: true},
    gate_tints: {validation: {n_trades: 'pass', p_value: 'pass', mean_net_return: 'pass', dsr: 'pass', placebo_p: 'pass'},
      holdout: {p_value: 'fail', mean_net_return: 'fail'}}};
  const h = strategyFrontend(detailStrategy({status: 'passed', experiment: held, why_failed: HOLD_LINES})); await h.viewStrategy(42); await flush();
  const hs = paperSections(h.root.querySelector('main').innerHTML);
  assert.deepEqual(tintedFigures(hs.validation), []);
  assert.deepEqual(tintedFigures(hs.holdout).sort(), missedFigures(HOLD_LINES).sort());
  assert.match(hs.holdout, /<div class="k">Holdout<\/div><div class="val">Consumed<\/div>/);
  // An older server without gate_tints judges nothing, so nothing is red, whatever the numbers.
  const old = strategyFrontend(detailStrategy({status: 'failed', experiment: {...failing, holdout: held.holdout, gate_tints: undefined}}));
  await old.viewStrategy(42); await flush();
  assert.doesNotMatch(old.root.querySelector('main').innerHTML, /class="val sig"/);
});

test('Meridian: the dashboard points a quiet stretch with sessions at what each idea missed', async () => {
  const at = async (since) => {
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...dashboardData(), deployments: [], since});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    return f.root.querySelector('#dash-since').innerHTML;
  };
  const base = {at: '2026-10-25T08:00:00+00:00', first: false, books: {paper: {pnl: 0, trades: 0}}, autopilot: {}};
  assert.match(await at({...base, passed: {n: 0, items: []}, runs: {succeeded: 2}}),
    /Nothing new passed <span class="since-sub">· 2 research sessions started, <a href="\/research">see what each idea missed<\/a><\/span>\./);
  assert.doesNotMatch(await at({...base, passed: {n: 1, items: [{id: 9, title: 'Rain'}]}, runs: {succeeded: 2}}), /see what each idea missed/);
  assert.doesNotMatch(await at({...base, passed: {n: 0, items: []}, runs: {}}), /see what each idea missed/);
});
