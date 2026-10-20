// Reused frozen86 workspace regressions, targeted at Meridian; current Funds behavior is reconciled.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import vm from 'node:vm';

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

function frontend({fetchImpl, brokerMount, stripeLoader, search = '', matchMedia = () => ({matches: false}), storage = new Map(), theme = 'meridian', build, versionDocument} = {}) {
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
    Intl, URL, URLSearchParams,
    DOMParser: class { parseFromString() { return versionDocument || {getElementById: () => null}; } },
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
  vm.runInContext(source.replace(boot, 'if (globalThis.testStripeLoader) loadStripe = globalThis.testStripeLoader; globalThis.frontend = {S, api, render, checkVersion, viewSettings, viewBilling, viewSystem, viewAdmin, routes, equityChart, runControls, runFeed, clearTimers, runRow, feedMd, viewStrategy, viewRun, viewResearch, viewFunds, viewDashboard, viewDeploy, viewCommunity, viewExplore, postSnapshot, replaceDeploymentContent, marketPicker, wireMarketPicker, hotOpen, renderHotRail};'), context);
  const api = context.frontend;
  api.S.me = {user: {id: 7, name: 'Offline fixture'}, markets: [], directions: [], live_trading_available: true, kalshi_connected: true, kalshi_dev_connected: true};
  // Cached global widgets keep these page checks focused. All requests still use
  // the offline transport above, including notifications and financial controls.
  api.S.hot = {markets: []}; api.S.hotAt = Date.now();
  api.S.ap = {mode: 'off'}; api.S.apAt = Date.now();
  return {...api, root, document, location, intervals, timeouts, windowListeners, requests, navigations, reloads, storage};
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
const funds = () => ({kalshi: {connected: false}, kalshi_dev: {connected: false},
  demo: {capital: 1000, equity: 1001, realized: 1}, paper: {cash: 1000, ledger: [
    {created_at: '2026-10-17T10:00:00Z', memo: '<script>ledger</script>', amount: 10},
  ]}});

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
    const trials = paper.querySelectorAll('#figs .m').find(el => el.querySelector('dt').textContent === 'Run trials');
    assert.equal(trials.querySelector('.fig').textContent, expected);
    assert.equal(paper.querySelectorAll('.rp-verdict').length, 1);
    assert.match(paper.querySelector('.legacy-verdict').textContent, /Not validated \(record missing\)/);
    assert.ok(output.indexOf('class="legacy-verdict"') < output.indexOf('id="figs"'));
    assert.match(output, /Backtest results/); assert.doesNotMatch(output, /<h4 class="paper-h">Backtest<\/h4>/);
    const saved = paper.querySelector('.saved-result');
    assert.equal(saved.tag, 'details'); assert.equal(saved.open, false);
    assert.equal(saved.textContent.includes('chance of false positives'), count != null);
    assert.ok(f.root.querySelector('#dep-paper')); assert.ok(f.root.querySelector('#live-confirm input'));
    assert.equal(detail.status, 'passed'); assert.equal(JSON.stringify(detail), before);
    assert.equal(postRequests(f).length, 0);

    const run = researchRun(9, 'succeeded');
    const r = frontend({fetchImpl: path => {
      assert.equal(path, '/api/runs/9?after=0'); return response({run, events: [], strategies: [detail]});
    }});
    await r.viewRun(9);
    assert.equal(r.root.querySelector('td[data-lab="Run trials"]').textContent, expected);
    assert.match(r.root.querySelector('thead').textContent, /Run trials/);
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
    assert.match(monitor.querySelector('.monitor-setup').textContent, /BTC 15-min · \$12\.5 \/ trade/);
    assert.ok(monitor.querySelector('.monitor-limits').textContent.includes('Max 4 open'));
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
        assert.equal(sample.getAttribute('aria-label'), `${date} · ${amounts[index]}`);
        assert.equal(sample.querySelector('.chart-reading').getAttribute('aria-hidden'), 'true');
        assert.equal(sample.querySelector('.chart-reading text').textContent, `${date} · ${amounts[index]}`);
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
  assert.ok(sample.getAttribute('aria-label').endsWith(' · −$3.00'));
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
    pending.resolve(response(data)); await loading; await flush();
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
    assert.equal(performanceMode.textContent, 'Paper · cumulative', name + ' source performance scope remains available');
    assert.equal(performanceMode.querySelector('.performance-mode-prefix').textContent, 'Paper · ', name);
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
        .endsWith(source.mode === 'live' ? ' · LIVE' : ' · Paper'));
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
  assert.ok(closedDetail.querySelector('.sub-fig').textContent.includes(settled.ticker + ' · ' + settled.title));
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
    assert.equal(primary.querySelector('.lab').textContent, livePrimary ? 'Live account · Kalshi' : 'Paper portfolio', label);
    assert.equal(primary.querySelector('.fig').textContent, primaryBalance, label);
    assert.equal(accounts.tag, 'details'); assert.equal(accounts.open, false);
    assert.deepEqual(accounts.querySelectorAll('dt.lab').map(lab => lab.textContent),
      [livePrimary ? 'Paper portfolio' : 'Live account', 'Demo balance'], label);
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
  pending.resolve(response(funds())); await loading;
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
  assert.deepEqual(rows.map(row => row.querySelector('.num').getAttribute('data-lab')), ['Unseen P&amp;L', 'Unseen P&amp;L', 'Tested P&amp;L', 'Tested P&amp;L', 'Tested P&amp;L']);
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
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').textContent, 'Dreaming');
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
    assert.equal(path, '/api/runs');
    return response({runs, counts: {research_running: runs.filter(run => run.status === 'running').length,
      research_queued: runs.filter(run => run.status === 'queued').length}, policy: typeof policy === 'function' ? policy() : policy});
  }});
}

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
    create.open = true;
    const prompt = form.querySelector('textarea[name=prompt]'); prompt.value = 'Keep my unsent idea'; prompt.focus();
    f.intervals.get(f.S.timers.at(-1))(); await flush();
    assert.equal(f.root.querySelector('#research-create'), create); assert.equal(create.open, true);
    assert.equal(f.root.querySelector('#dispatch'), form); assert.equal(prompt.value, 'Keep my unsent idea');
    assert.equal(f.document.activeElement, prompt); assert.equal(postRequests(f).length, 0);
    assert.deepEqual([...new Set(f.requests.map(request => request.path))].sort(),
      ['/api/models', '/api/notifications', '/api/research/context', '/api/runs']);
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
    [a.t, ['Bitcoin price', 'Above $100,000', 'Bitcoin price · Above $100,000', ['52¢', '1,200', '4'], '&gt; $100,000']],
    [b.t, ['Bitcoin price', 'Above $100,000', 'Bitcoin price · Above $100,000', ['68¢', '8', '2'], '&gt; $100,000']],
    [unique.t, ['Rain in Seattle?', 'At least 1 inch', 'Rain in Seattle? · At least 1 inch', ['25¢', '0', '0']]],
    [subtitle.t, ['Subtitle only', null, 'Subtitle only', ['—', '0', '8']]],
    [fallback.t, [fallback.t, null, fallback.t, ['12¢', '2', '9']]],
    [hostile.t, ['Price &quot;&lt;img src=x&gt;&quot; &amp; forecast', 'Above &lt;script&gt;unsafe&lt;/script&gt;',
      'Price &quot;&lt;img src=x&gt;&quot; &amp; forecast · Above &lt;script&gt;unsafe&lt;/script&gt;', ['62¢', '12', '5']]],
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
      const [title, sub, label, amounts, display] = m === renamed ? ['Bitcoin price', 'Below $100,000', 'Bitcoin price · Below $100,000', ['68¢', '8', '2'], '&lt; $100,000'] : expected.get(m.t);
      const raw = m === hostile ? 'KX&quot;QUOTE&quot;&lt;ticker&gt;&amp;' : m.t;
      assert.equal(link.getAttribute('href'), '/explore?m=' + encodeURIComponent(m.t));
      assert.equal(link.getAttribute('title'), raw);
      assert.equal(link.getAttribute('aria-label'), label === raw ? label : `${label} · ${raw}`);
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
  assert.equal(rows[1].querySelector('a.market-name').getAttribute('aria-label'), 'Bitcoin 5pm · Above $91,000 · A-2');
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
  assert.equal(contextual[1].textContent, 'Oct 19, 5pm ET · Source context', 'retain every actual context segment without inferring expiry');
  assert.equal(hostile[1].textContent, 'City &lt;script&gt;unsafe&lt;/script&gt; &amp; forecast');
  assert.equal(rows[7].querySelector('.market-event').getAttribute('title'), markets[7].ti);
  assert.equal(rows[7].querySelector('a.market-name').getAttribute('aria-label'), markets[7].ti + ' · ' + markets[7].su + ' · F-1');
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
    assert.equal(link.getAttribute('aria-label'), `Bitcoin · ${conditions[index]} · CONTRACT-${index}`);
    assert.equal(link.getAttribute('title'), `CONTRACT-${index}`);
    assert.equal(link.getAttribute('href'), `/explore?m=CONTRACT-${index}`);
  });
  const requests = f.requests.length;
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  f.S.hot = Object.freeze({at: new Date().toISOString(), markets}); f.renderHotRail();
  const quotes = f.root.querySelectorAll('.hot-row');
  assert.deepEqual(quotes.map(row => row.querySelector('.hot-title > span').textContent), displays);
  quotes.forEach((row, index) => {
    assert.equal(row.querySelector('.hot-title').getAttribute('title'), `Bitcoin · ${conditions[index]}`);
    assert.ok(row.getAttribute('aria-label').startsWith(`Bitcoin · ${conditions[index]} · CONTRACT-${index} · 51¢`));
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
  initial.resolve(response(payload('Late first result'))); await opening;
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
    [new Date(Date.now() - 30000).toISOString(), false, /^Snapshot · just now$/],
    [new Date(Date.now() - 240000).toISOString(), true, /^Stale · 4m ago$/],
    [undefined, true, /^Snapshot time unavailable$/],
    ['not-a-timestamp', true, /^Snapshot time unavailable$/],
    [new Date(Date.now() - 30000).toISOString(), false, /^Snapshot · just now$/],
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
    assert.equal(rail.querySelector('.hot-vol').textContent, '1.2k · 24h');
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
      await loading;
      assert.equal(f.root.innerHTML, html); assert.equal(f.root.writes, writes);
      assert.equal(f.intervals.size, intervals); assert.equal(f.S.timers.length, 0);
      assert.equal(f.S.sysLive, live); assert.equal(postRequests(f).length, 0);
    });
  }
}

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

for (const [label, version, changed] of [['current Meridian', 'meridian-current', false], ['new Meridian', 'meridian-new', true], ['missing build', null, false]]) {
  test(`Meridian update check uses its own HTML build: ${label}`, async () => {
    let reads = 0;
    const versionDocument = {getElementById: id => id === 'tau-boot' && version ? {dataset: {merVer: version, tauVer: 'different-tau-build'}} : null};
    const f = frontend({build: 'meridian-current', versionDocument, fetchImpl: (path, options) => {
      assert.equal(path, '/'); assert.equal(options.cache, 'no-store'); assert.equal(options.credentials, 'same-origin'); reads++;
      return {ok: true, text: async () => '<html>synthetic build document</html>'};
    }});
    await f.checkVersion();
    const bar = f.document.getElementById('verbar');
    assert.equal(Boolean(bar), changed); assert.equal(reads, 1); assert.equal(postRequests(f).length, 0);
    await f.checkVersion(); assert.equal(reads, 1, 'throttle prevents duplicate reads and notices');
    if (changed) { bar.querySelector('#verreload').onclick(); assert.deepEqual(f.reloads, [true]); }
    else assert.deepEqual(f.reloads, []);
  });
}

test('Meridian update metadata failure leaves the workspace usable', async () => {
  for (const fetchImpl of [() => ({ok: false}), () => { throw new Error('Synthetic offline'); }]) {
    const f = frontend({build: 'meridian-current', fetchImpl});
    await f.checkVersion(); assert.equal(f.document.getElementById('verbar'), null);
    assert.equal(postRequests(f).length, 0); assert.deepEqual(f.reloads, []);
  }
});

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
