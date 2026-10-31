// Reused frozen86 workspace regressions, targeted at Meridian; current Funds behavior is reconciled.
import assert, {visible} from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import vm from 'node:vm';
import {bundleSource, exposing} from './bundle_source.mjs';
import {pageFileCases} from './page_files_frontend_cases.mjs';
import {adminFigureCases} from './admin_figures_frontend_cases.mjs';
import {perpsFrontendCases} from './kalshi_perps_frontend_cases.mjs';
import {deployActionCases} from './deploy_actions_frontend_cases.mjs';
import {stopReasonCases} from './stop_reason_frontend_cases.mjs';
import {trustGlitchCases} from './trust_glitch_frontend_cases.mjs';
import {moneyDisplayCases, pastCloseCases, unmarkedPositionCases, unrealizedCellCases} from './money_display_frontend_cases.mjs';
import {moneyAgreementCases} from './money_agreement_frontend_cases.mjs';
import {bellCases} from './bell_frontend_cases.mjs';
import {communityCases} from './community_frontend_cases.mjs';
import {researchPollCases} from './research_poll_frontend_cases.mjs';
import {runPageCases} from './run_page_frontend_cases.mjs';
import {olderStepsCases} from './run_feed_older_cases.mjs';
import {moneyPollCases} from './money_poll_frontend_cases.mjs';
import {strategyPageCases} from './strategy_page_frontend_cases.mjs';
import {strategyListCases} from './strategy_list_frontend_cases.mjs';
import {strategyListParityCases} from './strategy_list_parity_frontend_cases.mjs';
import {exploreParityCases} from './explore_parity_frontend_cases.mjs';
import {countFormatCases} from './count_format_frontend_cases.mjs';
import {largeAccountCases} from './large_account_frontend_cases.mjs';
import {explorePageCases} from './explore_page_frontend_cases.mjs';
import {exploreSpotListCases} from './explore_spot_list_frontend_cases.mjs';
import {explorePollCases} from './explore_poll_frontend_cases.mjs';
import {loadPollCases} from './load_poll_frontend_cases.mjs';
import {phoneSpeedCases} from './phone_speed_frontend_cases.mjs';
import {kalshiWaitCases} from './kalshi_wait_frontend_cases.mjs';
import {settingsCases} from './settings_frontend_cases.mjs';
import {firstHourCases} from './first_hour_frontend_cases.mjs';
import {firstTenMinutesCases} from './first_ten_minutes_frontend_cases.mjs';
import {fundsTrustCases} from './funds_trust_frontend_cases.mjs';
import {fundsWalkCases} from './funds_walk_frontend_cases.mjs';
import {fundsHistoryCases} from './funds_history_frontend_cases.mjs';
import {moneyPagesWalkCases} from './money_pages_walk_frontend_cases.mjs';
import {staleMarkCases} from './stale_mark_frontend_cases.mjs';
import {chatPanelCases} from './chat_panel_frontend_cases.mjs';
import {creditsCases, declinedCardCases} from './credits_frontend_cases.mjs';
import {writeWaitCases} from './write_wait_frontend_cases.mjs';
import {flakyNetworkCases} from './flaky_network_frontend_cases.mjs';
import {deployErrorCases} from './deploy_errors_frontend_cases.mjs';
import {liveHonestCases} from './live_honest_frontend_cases.mjs';
import {freshWalkCases} from './fresh_walk_frontend_cases.mjs';
import {newcomerMoneyCases} from './newcomer_money_frontend_cases.mjs';
import {researchFormCases} from './research_form_frontend_cases.mjs';
import {spendTrustCases} from './spend_trust_frontend_cases.mjs';
import {a11yCases} from './a11y_frontend_cases.mjs';
import {trackRecordTrustCases} from './track_record_trust_frontend_cases.mjs';
import {slippageEstimateCases} from './slippage_estimate_frontend_cases.mjs';
import {newUserCases} from './new_user_frontend_cases.mjs';
import {firstSessionCases} from './first_session_frontend_cases.mjs';
import {checkinCadenceCases} from './checkin_cadence_frontend_cases.mjs';

const require = createRequire(import.meta.url);
const brokerConnections = require('../app/static/broker-connections.js');
// What the checks read from the bundle and its page files (bundle_source.mjs).
const EXPOSE = ['S', 'api', 'PAGES', 'deploymentMonitor', 'armed', 'apMoveText', 'apPillLabel', 'apIdleLine', 'sinceStrip', 'renderAutopilot', 'refreshAutopilot', 'apLoadChat', 'render', 'viewExample', 'viewSettings', 'viewBilling', 'viewSystem', 'viewAdmin', 'routes', 'equityChart', 'runControls', 'runFeed', 'clearTimers', 'runRow', 'feedMd', 'viewStrategy', 'viewStrategies', 'strategySlip', 'tabEdges', 'viewRun', 'viewResearch', 'viewFunds', 'viewDashboard', 'viewDeploy', 'viewCommunity', 'viewExplore', 'postSnapshot', 'replaceDeploymentContent', 'marketPicker', 'wireMarketPicker', 'hotOpen', 'renderHotRail', 'trackRecordPanel', 'paintDashAp', 'mountTrackRecord', 'apUpdate', 'paymentGate', 'viewMarketDetail', 'rpUnderwater'];
const source = bundleSource('app.meridian.js', {expose: EXPOSE});
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
  get tagName() { return this.tag.toUpperCase(); }
  get open() { return 'open' in this.attributes; }
  set open(value) { if (value) this.attributes.open = ''; else delete this.attributes.open; }
  get innerHTML() { return this.html || ''; }
  set innerHTML(value) {
    if (this.ownerDocument?.activeElement !== this && this.contains(this.ownerDocument?.activeElement)) {
      this.ownerDocument.activeElement = this.ownerDocument.body;
    }
    this.html = value; this.text = undefined; this.writes++; this.children.forEach(child => { child.removed = true; }); this.children = [];
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
    // A comma list ("button, input, ...", the way a focus walk asks for every control) answers in
    // document order, as the DOM does.
    if (selector.includes(',')) {
      const order = [], walk = element => element.children.forEach(child => { order.push(child); walk(child); });
      walk(this);
      const hits = new Set(selector.split(',').map(part => part.trim()).filter(Boolean).flatMap(part => this.querySelectorAll(part)));
      return order.filter(element => hits.has(element));
    }
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
  insertBefore(child, ref) { this.appendChild(child); const at = this.children.indexOf(ref); if (at >= 0) this.children.splice(at, 0, this.children.pop()); }
  insertAdjacentHTML(_position, html) { this.html = (this.html || '') + html; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  hasAttribute(key) { return key in this.attributes; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  focus(options) { this.focusOptions = options; if (this.ownerDocument) this.ownerDocument.activeElement = this; }
  remove() { this.removed = true; }
  // Puts the markup's one element in this one's place in its parent, as the DOM does; either one reads
  // back the markup it was given.
  get outerHTML() { return this.outer; }
  set outerHTML(value) {
    this.outer = value;
    const holder = new Element('div'); holder.innerHTML = value;
    const fresh = holder.children[0], parent = this.parent;
    if (!fresh || !parent) return;
    // Focus inside the replaced element falls back to the body, and the new one belongs to the document.
    if (this.ownerDocument && this.contains(this.ownerDocument.activeElement)) this.ownerDocument.activeElement = this.ownerDocument.body;
    const adopt = element => { element.ownerDocument = this.ownerDocument; element.children.forEach(adopt); };
    adopt(fresh);
    fresh.outer = value; fresh.parent = parent; parent.children[parent.children.indexOf(this)] = fresh; this.removed = true;
  }
}

function frontend({fetchImpl, brokerMount, stripeLoader, search = '', matchMedia = () => ({matches: false}), storage = new Map(), session, theme = 'meridian', build, notifications, win = {}, globals = {}} = {}) {
  const root = new Element('div', {id: 'app'}), body = new Element('body'), documentListeners = [];
  const document = {body, activeElement: body, hidden: false,
    getElementById: id => body.querySelector('#' + id), addEventListener: (name, callback) => documentListeners.push([name, callback]), removeEventListener() {},
    createElement: tag => { const element = new Element(tag); element.ownerDocument = document; return element; }};
  body.ownerDocument = document; body.appendChild(root);
  const intervals = new Map(), timeouts = new Map(), windowListeners = new Map(), requests = [], navigations = [], reloads = [];
  const delays = new Map();
  // Runs the pending timers set for at most `ms` (an armed confirm's hold, say) and leaves the longer ones.
  const elapse = ms => { for (const [id, run] of [...timeouts]) if ((delays.get(id) || 0) <= ms) { timeouts.delete(id); run(); } };
  let nextId = 0;
  const location = {pathname: '/strategies/42', search, origin: 'http://offline.invalid', reload: () => reloads.push(true)};
  // A path's query goes to location.search, as in a browser (a sign-in redirect carries ?next=).
  const navigate = (_state, _title, path) => { navigations.push(path); const [p, q] = String(path).split('?'); location.pathname = p; location.search = q ? '?' + q : ''; };
  const context = vm.createContext({
    Intl, URL, URLSearchParams, AbortController,
    document, testStripeLoader: stripeLoader,
    window: {__TAU_UI__: theme, __BUILD__: build, addEventListener(name, callback) {
      const listeners = windowListeners.get(name) || []; listeners.push(callback); windowListeners.set(name, listeners);
    }, scrollTo() {}, matchMedia,
      ...(brokerMount ? {TauBrokerConnections: {mount: brokerMount}} : {}), ...win},
    addEventListener() {}, location, history: {pushState: navigate, replaceState: navigate},
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key), key: i => [...storage.keys()][i] ?? null, get length() { return storage.size; }},
    ...(session ? {sessionStorage: session} : {}),
    setInterval: callback => { intervals.set(++nextId, callback); return nextId; },
    clearInterval: id => intervals.delete(id),
    setTimeout: (callback, ms = 0) => { timeouts.set(++nextId, callback); delays.set(nextId, ms); return nextId; },
    clearTimeout: id => timeouts.delete(id),
    fetch: async (path, options) => {
      requests.push({path, options});
      if (path === '/api/notifications') return typeof notifications === 'function' ? notifications() : response(notifications || {unread: 0, items: []});
      if (fetchImpl) return fetchImpl(path, options);
      throw new Error('Unexpected offline request: ' + path);
    },
    ...globals,  // page globals a check stands in for (a counting Intl)
  });
  const boot = '  setupGlossary();\n  render();';
  assert.equal(source.split(boot).length, 2, 'the harness replaces only automatic boot');
  vm.runInContext(source.replace(boot, 'if (globalThis.testStripeLoader) loadStripe = globalThis.testStripeLoader; globalThis.frontend = ' + exposing(EXPOSE) + ';'), context);
  const api = context.frontend;
  api.S.me = {user: {id: 7, name: 'Offline fixture'}, markets: [], directions: [], live_trading_available: true, kalshi_connected: true, kalshi_dev_connected: true};
  // Cached global widgets keep these page checks focused. All requests still use
  // the offline transport above, including notifications and financial controls.
  api.S.hot = {markets: []}; api.S.hotAt = Date.now();
  api.S.ap = {mode: 'off'}; api.S.apAt = Date.now();
  // Moves the page's clock (Date.now) forward, for checks on how old a figure is.
  const shiftClock = ms => vm.runInContext(`{ const now = Date.now; Date.now = () => now() + ${Number(ms)}; }`, context);
  return {...api, win: context.window, root, document, window: context.window, location, intervals, timeouts, elapse, windowListeners, documentListeners, requests, navigations, reloads, storage, shiftClock};
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
deployActionCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, postRequests, source});
stopReasonCases({name: 'Meridian', frontend});
trustGlitchCases({name: 'Meridian', frontend});
bellCases({name: 'Meridian', frontend});
adminFigureCases({name: 'Meridian', frontend});
communityCases({name: 'Meridian', frontend});
pageFileCases({name: 'Meridian', frontend, prefix: 'app.meridian-', pagesKey: 'merPages', storageFor: m => m});
settingsCases({name: 'Meridian', frontend, current: 'meridian', storageFor: m => m, cardWallOpts: () => ({stripeLoader: async () => STRIPE_STUB})});
researchPollCases({name: 'Meridian', frontend});
runPageCases({name: 'Meridian', frontend});
moneyPollCases({name: 'Meridian', frontend, stripe: () => ({stripeLoader: async () => STRIPE_STUB})});
strategyPageCases({name: 'Meridian', frontend, detailStrategy, strategyFrontend, postRequests});
strategyListCases({name: 'Meridian', frontend, detailStrategy});
strategyListParityCases({name: 'Meridian', frontend, detailStrategy});
exploreParityCases({name: 'Meridian', frontend});
countFormatCases({name: 'Meridian', frontend, detailStrategy, strategyFrontend, fundsData: () => funds(), dashboard: () => dashboardData()});
largeAccountCases({name: 'Meridian', frontend, detailStrategy, strategyFrontend});
explorePageCases({name: 'Meridian', frontend});
trackRecordTrustCases({name: 'Meridian', frontend, Element, dashboard: () => dashboardData()});
researchFormCases({name: 'Meridian', frontend});
spendTrustCases({name: 'Meridian', frontend});
kalshiWaitCases({name: 'Meridian', frontend, detailStrategy});
phoneSpeedCases({name: 'Meridian', frontend, source, railOpenWide: [['tau_hotrail', '1']], storageFor: m => m});
exploreSpotListCases({name: 'Meridian', frontend, railOpenWide: [['tau_hotrail', '1']], storageFor: m => m});
explorePollCases({name: 'Meridian', frontend, railOpenWide: [['tau_hotrail', '1']], storageFor: m => m});
loadPollCases({name: 'Meridian', frontend, railOpenWide: [['tau_hotrail', '1']],
  storageFor: m => m});
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
  const output = f.root.querySelector('#main').innerHTML;
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

// Walk 2026-10-27: a Void strategy's page stamped "Void" in its head and "Void" again as the verdict right under it.
test('a strategy page stamps its status once: the verdict under the head drops a label that repeats it', async () => {
  const stamps = (f, said) => [...f.root.querySelector('.strategy-pagehead').querySelectorAll('.mk'), ...f.root.querySelector('article.paper').querySelectorAll('.mk')]
    .filter(el => el.textContent.trim() === said).length;
  for (const [status, said, words] of [['failed', 'Void', /It reached the unseen-data gate and failed it/], ['rejected', 'Rejected', /Rejected — /],
    ['backtest-only', 'Backtest only', /It never went through the held-out tests: no test on data it hadn’t seen, no one-time final test and no correction for how many ideas were tried\./]]) {
    const f = strategyFrontend(detailStrategy({status, experiment: null}));
    await f.viewStrategy(42); await flush();
    assert.equal(stamps(f, said), 1, `${status}: one "${said}" stamp`);
    const verdict = f.root.querySelector('.legacy-verdict');
    assert.equal(verdict.querySelector('.mk'), null); assert.match(verdict.textContent, words);
  }
  // A pass with no gatekeeper record keeps its verdict's own label: it says what the head's Passed doesn't.
  const f = strategyFrontend(detailStrategy({status: 'passed', experiment: null}));
  await f.viewStrategy(42); await flush();
  assert.equal(stamps(f, 'Passed'), 1);
  assert.equal(f.root.querySelector('.legacy-verdict .mk').textContent, 'Not validated');
  assert.match(readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8'), /\.legacy-verdict \.rp-verdict p:first-child \{ margin-top: 0; \}/);
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
    assert.match(paper.querySelector('.legacy-verdict').textContent, /^Not validated\s*It’s marked Passed, but there’s no record of its held-out tests/);
    assert.ok(output.indexOf('class="legacy-verdict"') < output.indexOf('id="figs"'));
    assert.match(output, /Backtest results/); assert.doesNotMatch(output, /<h4 class="paper-h">Backtest<\/h4>/);
    const saved = paper.querySelector('.saved-result');
    assert.equal(saved.tag, 'details'); assert.equal(saved.open, false);
    // The luck note sits under the Ideas tested figure, in Tau's words, and the folded result doesn't repeat it.
    assert.equal(trials.textContent.includes('More ideas tried, more chance one passes by luck (multiple testing).'), count != null);
    assert.equal(saved.textContent.includes('passes by luck'), false);
    assert.ok(f.root.querySelector('#dep-paper')); assert.ok(f.root.querySelector('#live-confirm input'));
    assert.equal(detail.status, 'passed'); assert.equal(JSON.stringify(detail), before);
    assert.equal(postRequests(f).length, 0);

    const run = researchRun(9, 'succeeded');
    const r = frontend({fetchImpl: path => {
      assert.equal(path, '/api/runs/9?after=0'); return response({run, events: [], strategies: [detail]});
    }});
    await r.viewRun(9);
    // On its own session's page every row's count was the session's again (a running one's counter, behind
    // the Tested figure above it): the column is left out there, and kept on the Strategies list.
    assert.equal(r.root.querySelector('td[data-lab="Ideas tested"]'), null);
    assert.doesNotMatch(r.root.querySelector('thead').textContent, /Ideas tested/);
    assert.match(r.root.querySelector('#runfigs').innerHTML, /Tested/);
    assert.match(r.strategySlip(detail), new RegExp('data-lab="Ideas tested">' + expected + '<'));
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

// Tau's later-period shading was the sheet's own colour and never showed (walked 2026-10-28). Meridian's strategy
// sheet has no fill of its own, so the band (--stock-raised) sits on the page's cream (--stock) and shows, quietly.
test('the strategy chart’s later-period shading shows against the Meridian page', () => {
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  const chart = frontend().equityChart([[0, 0], [50, 1], [100, 2]], new Date(30000).toISOString(), null, {width: 760});
  const fill = chart.match(/<rect x="[\d.]+" y="[\d.]+" width="[\d.]+" height="[\d.]+" fill="var\(--([a-z-]+)\)"\/>/)[1];
  assert.match(css, /\n\.sheet-doc\.paper \{ border: 0; background: none; padding: 0; \}/);
  const tok = (name) => css.match(new RegExp(`--${name}: (#[0-9A-Fa-f]{6});`))[1].toUpperCase();
  assert.equal(fill, 'stock-raised');
  assert.notEqual(tok(fill), tok('stock'));
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
  assert.match(f.root.querySelector('#main').innerHTML, /failed the unseen-data gate/);
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
  ['Overview', 'viewDashboard', '/api/dashboard', '#main'],
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
  paper: {equity: 1111.25, cash: 900, total_pnl: 111.25, realized_pnl: 98.4, today_pnl: -7.5, open_at_cost: 211.25, ...paper},
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

test('Overview paper P&L is realized all time, the Closed P&L chart and track record figure, and its day figure says realized', async () => {
  for (const reset_at of [null, '2026-10-20T09:00:00Z']) {
    const f = apDashboard(dashboardData({paper: {reset_at}}), apStatus);
    await f.viewDashboard(); await flush();
    f.S.ap = apStatus; f.paintDashAp();
    const paper = f.root.querySelector('.paper-summary').textContent;
    // total_pnl (equity less deposits) took off open entry fees and restarted at a reset, so it sat
    // beside a different Closed P&L for one book; realized is what every other page counts.
    assert.match(paper, /Since you started: realized P&amp;L \+\$98\.40/);
    assert.doesNotMatch(paper, /All-time|since reset/);
    // Today is closed trades only (realized_pnl); the live group says so too.
    assert.match(paper, /Today \(UTC\): paper realized−\$7\.50/);
    const card = f.root.querySelector('#dash-ap').innerHTML;
    assert.match(card, /<dt><span class="pnl-win">Since you started:<\/span> paper P&amp;L, <span class="nobr">realized<button[^>]*data-glo="realized"[\s\S]*?<\/button><\/span><\/dt><dd><span class="[^"]*">\+\$98\.40/);
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
  // The dashboard mounts the record after #main; mount it the same way on a host of its own here.
  const host = new Element('section'); f.root.appendChild(host);
  await f.mountTrackRecord(host, {at: null});
  const panel = () => host.querySelector('.trpanel').innerHTML;
  // Nothing deployed on this dashboard, so the button skips the empty Deploy board.
  assert.match(panel(), /See passed strategies/); assert.doesNotMatch(panel(), /Go to Deploy/);
  status = {autopilot: true, mode: 'paper', story: [], research: {}, live_running: 0, demo_running: 0, paper_running: 0};
  f.shiftClock(20000);  // the next status poll, 20s on (a tick under 10s after a read asks nothing new)
  for (const tick of [...f.intervals.values()]) tick();
  await flush(); await flush();
  assert.equal(f.S.me.user.autopilot, true);
  assert.match(panel(), /Autopilot runs the strategies that pass every research test on paper, with pretend money/); assert.doesNotMatch(panel(), /Go to Deploy/);
});

test('Overview: a trade the dashboard poll sees open or close re-reads the track record now, not on its own minute', async () => {
  const empty = (label) => ({trades: 0, label});
  let tr = {generated_at: 1, default_mode: 'paper', method: [], thresholds: {min_sharpe_days: 14, min_trades: 30},
    modes: {live: empty('Live money'), demo: empty('Kalshi demo'), paper: empty('Paper')}};
  let dash = dashboardData({paper: {closed_trades: 0, open_positions: 0}});
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dash);
    if (path === '/api/track-record') return response(tr);
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  Object.defineProperty(Element.prototype, 'parentNode', {get() { return this.parent; }, configurable: true});
  try {
    await f.viewDashboard(); await flush(); await flush();
    const reads = () => f.requests.filter(r => r.path === '/api/track-record').length;
    const dashPoll = f.intervals.get(f.S.timers[0]);
    const poll = async () => { dashPoll(); await flush(); await flush(); await flush(); };
    assert.ok(f.root.querySelector('#track-record'), 'the record mounts below the board');
    assert.equal(reads(), 1);
    await poll();
    assert.equal(reads(), 1);
    dash = dashboardData({paper: {closed_trades: 1, open_positions: 0}});
    tr = {...tr, generated_at: 2, modes: {...tr.modes, paper: {...empty('Paper'), trades: 1}}};
    await poll();
    assert.equal(reads(), 2);
    await poll();
    assert.equal(reads(), 2);
  } finally {
    delete Element.prototype.parentNode;
  }
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

test('Meridian: the empty Deployed box names its next step "research an idea yourself", as Tau does, with or without a session yet', async () => {
  for (const own_sessions of [false, true]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response(dashboardData({since: {own_sessions}}));
      if (path === '/api/autopilot/status') return response({...apStatus, autopilot: false, mode: 'off'});
      if (path.startsWith('/api/')) return response({});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = false;
    await f.viewDashboard(); await flush(); f.clearTimers();
    const deps = f.root.querySelector('#deps-empty').innerHTML;
    // The words name the Research page (the nav item, and the autopilot card's "or research by hand"), not a "session".
    assert.match(deps, own_sessions ? /on paper first\. Or research an idea yourself\.<\/p>/ : /<p>Turn on autopilot above, or research an idea yourself\.<\/p>/);
    assert.doesNotMatch(deps, /start a session/);
  }
});

test('Meridian: the empty Deployed box\'s button says what its sentence says, "Research an idea", as Tau\'s does', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData({since: {own_sessions: true}}));
    if (path === '/api/autopilot/status') return response({...apStatus, autopilot: false, mode: 'off'});
    if (path.startsWith('/api/')) return response({});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false;
  await f.viewDashboard(); await flush(); f.clearTimers();
  const box = f.root.querySelector('#deps-empty');
  // "Or research an idea yourself." sat over a "New session" button: the sentence and the button named two things.
  assert.match(box.innerHTML, /Or research an idea yourself\.<\/p><a class="btn" href="\/research\?new=1">Research an idea<\/a>/);
  assert.doesNotMatch(box.innerHTML, /New session/);
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
    const html = f.root.querySelector('#boardbody').innerHTML + f.root.querySelector('#main').innerHTML;
    for (const mode of ['paper', 'demo', 'live']) {
      const link = `<a class="csv-link" href="/api/trades.csv?mode=${mode}" download>Download trades (CSV)</a>`;
      assert.equal(html.includes(link), counts[mode] > 0, `${mode} ${JSON.stringify(counts)}`);
    }
  }
});

test('Overview demo account says what demo is and that its P&L restarts at a reload', async () => {
  for (const [demo, re] of [
    [{equity: 1000, capital: 1000, realized_pnl: 0}, /\$1,000\.00 capital\u00a0· No demo deployments\u00a0· real fills on Kalshi’s sandbox, not real money/],
    [{equity: 512, capital: 500, realized_pnl: 12, running: 1, before_reload: 40}, /\$500\.00 capital\u00a0· 0 open\u00a0· \+\$12\.00 realized since reload, after Kalshi fees\u00a0· real fills/],
    [{equity: 1012, capital: 1000, realized_pnl: 12, running: 1, before_reload: 0}, /\+\$12\.00 realized all time, after Kalshi fees\u00a0· real fills/],
  ]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData({demo})); }});
    await f.viewDashboard(); await flush();
    assert.match(f.root.querySelector('#other-accounts').innerHTML, re);
  }
});

test('Funds demo labels say "since reload" only after a reload, and that demo proves the order path, not the edge', async () => {
  for (const before_reload of [0, 40]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds(); d.demo.before_reload = before_reload; return response(d); }});
    await f.viewFunds(); await flush();
    const main = f.root.querySelector('#main').innerHTML;
    assert.match(main, before_reload ? /<dt>Capital at last reload<\/dt>/ : /<dt>Starting capital<\/dt>/);
    assert.match(main, before_reload ? /<dt>Realized since reload<\/dt>/ : /<dt>Realized all time<\/dt>/);
    assert.match(main, /to prove the order path before live money\. The sandbox book is thin, so its fills and P&amp;L are no evidence of the edge; paper keeps that job\. The money is simulated\./);
    assert.doesNotMatch(main, /slippage are real/);
    assert.match(main, /Demo is the step between paper and live: it proves orders place, fill and book/);
    assert.match(main, /the track record still counts every closed demo trade/);
    assert.match(f.root.querySelector('#ffigs').innerHTML, before_reload ? /capital at last reload\u00a0· needs a demo key\u00a0· real fills on Kalshi’s sandbox/ : /starting capital\u00a0· needs a demo key\u00a0· real fills on Kalshi’s sandbox/);
  }
});

test('Overview demo monitors say they are the sandbox, what they copy, and why their fills differ from paper', async () => {
  const deployments = [{...dashboardDeployment('demo'), demo_copy: true}, {...dashboardDeployment('demo'), id: 92, demo_copy: false},
    {...dashboardDeployment('paper'), id: 93}];
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData({deployments})); }});
  await f.viewDashboard();
  const monitors = f.root.querySelectorAll('#dash-deps article.dep-monitor'); assert.equal(monitors.length, 3);
  const line = (m) => { const el = m.querySelector('.monitor-config .demo-row'); return el ? el.innerHTML : null; };
  assert.equal(line(monitors[0]), 'Demo copy of its paper run: the same rules on Kalshi’s sandbox, with play money. It proves orders place, fill and book before live money; the demo book is thin, so fills differ from paper’s.');
  assert.match(line(monitors[1]), /^On Kalshi’s sandbox, with play money\. It proves orders place, fill and book/);
  assert.equal(line(monitors[2]), null);  // paper says nothing of the sort
});

test('Overview: only the admin view shows Bitcoin price collector lag, red, naming the feed it means', async () => {
  // Walk 2026-10-30: "No backtest history yet", red beside a passed strategy, read as that strategy having no backtest.
  // It is the Bitcoin price collector's lag (operator's to fix, so admin only), and stays red: new backtests lack prices.
  for (const [btc, admin, said] of [[null, true, 'No Bitcoin price history collected yet'], [3 * 3600, true, 'Bitcoin price history 3h behind'],
    [null, false, null], [60, true, null]]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData({freshness: {btc}})); }});
    f.S.me.is_admin = admin;
    await f.viewDashboard(); await flush();
    const line = f.root.querySelector('.dashboard-status');
    if (said) { assert.ok(line && /\bneeds\b/.test(line.className), 'red, as a problem the operator must fix'); assert.match(line.innerHTML, new RegExp(`<em>${said}</em>`)); }
    else assert.doesNotMatch(f.root.querySelector('#boardbody').innerHTML, /Bitcoin price history/, JSON.stringify([btc, admin]));
    assert.doesNotMatch(f.root.querySelector('#boardbody').innerHTML, /backtest history/i);
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
  assert.match(live.textContent, /Live open at cost before fees, not in cash\$50\.00/); assert.match(live.textContent, /Live realized today \(UTC\)−\$2\.00/);
  // Walk 2026-10-30: "Open positions 1" sat beside a positions table headed "2 paper · 1 live" without saying which
  // book it counted. Each live figure in the band names its book, as "Live realized today" does.
  assert.match(live.textContent, /Live open positions2/);
  const labs = [...live.querySelectorAll('.portfolio-detail .lab')].map((el) => el.textContent);
  assert.ok(labs.length >= 3, labs.join(' | ')); assert.deepEqual(labs.filter((t) => /^Open/.test(t)), [], labs.join(' | '));
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Live realized today \(UTC\)<\/dt><dd><span class="[^"]*">−\$2\.00<\/span> <small>real money, after Kalshi fees<\/small>/);
});

test('Funds names the live figure Kalshi cash, open positions not included', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds();
    d.kalshi = {connected: true, key_id: 'abcd-wxyz', balance: 120, funding_url: 'https://kalshi.com'}; return response(d); }});
  await f.viewFunds(); await flush();
  const figs = f.root.querySelector('#ffigs').innerHTML;
  assert.match(figs, /Kalshi cash/); assert.match(figs, /Real money at Kalshi\. Open positions not included/);
  assert.doesNotMatch(figs, /Live money/);
});

test('Funds says when Kalshi cash was read, what each book has open, and matches the Overview paper figure', async () => {
  const read = new Date(Date.now() - 5 * 60000).toISOString();
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds();
    d.kalshi = {connected: true, key_id: 'abcd-wxyz', balance: 120, balance_at: read, open_positions: 1, open_at_cost: 3.05, open_cost: 3.11, funding_url: 'https://kalshi.com'};
    d.demo = {...d.demo, open_positions: 2, open_at_cost: 8.09, open_cost: 8.25};
    d.paper = {...d.paper, cash: 991.91, equity: 1000, open_positions: 3, open_at_cost: 8.09, open_cost: 8.25}; return response(d); }});
  await f.viewFunds(); await flush();
  const figs = f.root.querySelector('#ffigs').innerHTML;
  assert.match(figs, /Real money at Kalshi, read 5m ago\. 1 open live position \(\$3\.11 at cost \+ fees\) not included/);
  assert.match(figs, /starting capital\u00a0· 2 open \(\$8\.25 at cost \+ fees, all of it in Tau’s demo book\)\u00a0· needs a demo key\u00a0· real fills/);
  assert.match(figs, /Paper balance[\s\S]*\$1,000\.00[\s\S]*\$991\.91 cash\u00a0· 3 open \(\$8\.25 at cost \+ fees, \$8\.09 of it in the balance\)\u00a0· practice money</); assert.doesNotMatch(figs, /Paper cash/);
  assert.doesNotMatch(figs, /\$1,120|\$2,120|\$1,991/);  // books are never summed
  const h = frontend({fetchImpl: () => { const d = funds(); d.kalshi = {connected: true, key_id: 'k', balance: null, open_positions: 0, open_at_cost: 0}; return response(d); }});
  await h.viewFunds(); await flush();
  assert.match(h.root.querySelector('#ffigs').innerHTML, /Kalshi didn’t answer just now\. Reload in a minute to try again\./);
});

test('Funds paper history says prices in cents, a lost settlement as lost, and explains fees and settlement once', async () => {
  const ledger = [
    {created_at: '2026-10-26T10:05:00Z', kind: 'settlement', memo: 'KXBTC15M-L settled NO', amount: 0},
    {created_at: '2026-10-26T10:04:00Z', kind: 'settlement', memo: 'KXBTC15M-W settled YES', amount: 25},
    {created_at: '2026-10-26T10:03:00Z', kind: 'trade', memo: 'Sold 8/25 YES KXBTC15M-P @ 0.25 (stop_loss, partial)', amount: 1.86},
    {created_at: '2026-10-26T10:02:00Z', kind: 'trade', memo: 'Paper replay: 10 YES KXBTC15M-R @ 0.40 -> 0.55 (take_profit)', amount: 1.3},
    {created_at: '2026-10-26T10:01:00Z', kind: 'trade', memo: 'Bought 25 YES KXBTC15M-W @ 0.40', amount: -10.42},
    {created_at: '2026-10-26T10:00:00Z', kind: 'deposit', memo: '<b>Starting</b> paper balance', amount: 1000},
  ];
  const f = frontend({fetchImpl: () => { const d = funds(); d.paper.ledger = ledger; return response(d); }});
  await f.viewFunds(); await flush();
  const rows = [...f.root.querySelectorAll('.t-ledger tbody tr')].map((tr) => tr.innerHTML);
  assert.match(rows[0], /KXBTC15M-L settled NO<span class="hint">\u00a0· lost, paid \$0<\/span>[\s\S]*\$0\.00/);
  assert.match(rows[1], /settled YES<span class="hint">\u00a0· won, paid \$1 a contract<\/span>[\s\S]*\+\$25\.00/);
  assert.match(rows[2], /Sold 8\/25 YES KXBTC15M-P at 25¢ \(stop loss, partial\)/);
  assert.match(rows[3], /Paper replay: 10 YES KXBTC15M-R at 40¢ → 55¢ \(take profit\)/);
  assert.match(rows[4], /Bought 25 YES KXBTC15M-W at 40¢<\/span><\/td>[\s\S]*−\$10\.42/);
  // The words and the settled note are one inline run (.ledger-said): the stacked cell is a flex row, and at 390px
  // the note was its own item, so "· won, paid $1 a contract" began a line (walk 2026-10-27).
  assert.match(rows[1], /<span class="ledger-said">[^<]*settled YES<span class="hint">\u00a0· won, paid \$1 a contract<\/span><\/span>/);
  assert.match(rows[5], /&lt;b&gt;Starting&lt;\/b&gt; paper balance/);  // still escaped
  for (const r of rows) assert.doesNotMatch(r, /@ 0\.|stop_loss|take_profit/);
  const how = f.root.querySelector('.ledger-how').textContent;
  assert.match(how, /A buy takes the contracts’ price plus Kalshi’s fee/);
  assert.match(how, /each winning contract pays \$1 and each losing one pays \$0/);
  assert.doesNotMatch(how, /latest 50/);
  const g = frontend({fetchImpl: () => { const d = funds(); d.paper.ledger = Array.from({length: 50}, () => ledger[4]); return response(d); }});
  await g.viewFunds(); await flush();
  assert.match(g.root.querySelector('.ledger-how').textContent, /The latest 50 entries\./);
});

test('Funds says what each book has made, realized, never summed, and when a new book’s P&L will show', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds();
    d.kalshi = {connected: true, key_id: 'k', balance: 1234.56, open_positions: 1, open_at_cost: 4, open_cost: 4, realized_pnl: 3.11, closed_trades: 5};
    d.demo = {...d.demo, realized: 9.77, before_reload: 40, closed_trades: 5};
    d.paper = {...d.paper, cash: 995.19, equity: 1005.19, open_positions: 1, open_at_cost: 10, open_cost: 10, realized_pnl: 5.61, closed_trades: 5}; return response(d); }});
  await f.viewFunds(); await flush();
  const figs = f.root.querySelector('#ffigs').innerHTML;
  assert.match(figs, /Real money at Kalshi\. Tau’s live trades: \+\$3\.11 realized all time, after Kalshi fees\. 1 open live position/);
  assert.match(figs, /\$995\.19 cash\u00a0· 1 open \(\$10\.00 at cost \+ fees\)\u00a0· \+\$5\.61 realized all time, after Kalshi fees and the spread\u00a0· practice money</);  // as Tau's Funds says it
  assert.match(figs, /\+\$9\.77 realized since reload, after Kalshi fees\u00a0· needs a demo key/);
  assert.doesNotMatch(figs, /18\.49|15\.38|12\.88|8\.72/);  // no two books added together
  const g = frontend({fetchImpl: () => { const d = funds();
    d.kalshi = {connected: false, realized_pnl: 0, closed_trades: 0};
    d.demo = {...d.demo, closed_trades: 0}; d.paper = {...d.paper, realized_pnl: 0, closed_trades: 0}; return response(d); }});
  await g.viewFunds(); await flush();
  const empty = g.root.querySelector('#ffigs').innerHTML;
  assert.match(empty, /P&amp;L shows once a demo trade closes/); assert.match(empty, /cash\u00a0· P&amp;L shows once a paper trade closes\u00a0· practice money</);
  assert.doesNotMatch(empty, /realized all time|Tau’s live/);
});

test('Overview Kalshi cash says when it was read, and keeps Tau\'s realized line when Kalshi is down', async () => {
  for (const balance of [3333, null]) {
    const f = apDashboard(dashboardData({deployments: [dashboardDeployment('live')], live: {connected: true, balance, balance_at: new Date().toISOString(), open_positions: 2}}), {...apStatus});
    await f.viewDashboard(); await flush();
    const text = f.root.querySelector('.live-summary').textContent;
    if (balance) assert.match(text, /Read from Kalshi just now\u00a0· \+\$17\.00 realized all time by Tau trades/);  // Tau's words (cashAt)
    else assert.match(text, /Couldn’t read your Kalshi balance just now\u00a0· \+\$17\.00 realized all time by Tau trades/);
    assert.doesNotMatch(text, /cash read from Kalshi/);
  }
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
  // The server joins entry and exit with a plain " · "; drawn, each is SEP, so a wrapped line ends on "·".
  const drawn = s => s.replace(/ · /g, '\u00a0· ');
  assert.equal(why('open-1').textContent, drawn(openWhy));
  assert.equal(why('open-2'), null);  // nothing stored to say: no empty line
  assert.equal(why('closed-3').textContent, drawn(exitWhy.replace('<', '&lt;')));
  assert.equal(why('closed-4').textContent, 'Held to settlement: &lt;img src=x&gt;');
  assert.ok(f.root.querySelector('#recent-settlements').contains(why('closed-3')));
  assert.doesNotMatch(f.root.querySelector('#main').innerHTML, /<img/);
  const pos = {title: 'Rain fade', ticker: 'KXRAINNYC-T1', side: 'no', qty: 4, entry_price: .37, entry_fee: .02, unrealized: null,
    market_close_time: '2026-10-25T17:30:00Z', mode: 'paper', why: openWhy};
  const d = frontend({fetchImpl: path => { assert.equal(path, '/api/deployments'); return response({deployments: [], open_positions: [pos, {...pos, ticker: 'KXRAINNYC-T2', why: null}]}); }});
  await d.viewDeploy(); await flush();
  const table = d.root.querySelector('#openpos').innerHTML;
  assert.deepEqual([...table.matchAll(/<div class="sub-fig pos-why">([^<]*)<\/div>/g)].map(m => m[1]), [drawn(openWhy)]);
  const holdings = [{ticker: 'KXBTC15M-A', side: 'yes', qty: 2, entry_price: 0.35, cost: 0.7, unrealized: null, mode: 'paper',
    market_close_time: '2026-10-25T07:45:00Z', why: openWhy}];
  const s = strategyFrontend(detailStrategy({holdings})); await s.viewStrategy(42); await flush();
  const list = s.root.querySelector('#main').innerHTML;
  assert.match(list, new RegExp('<ul class="holdlist">[\\s\\S]*<div class="sub-fig pos-why">' + drawn(openWhy).replace(/[+.*?()]/g, '\\$&') + '</div></li>'));
  assert.equal(postRequests(f).length + postRequests(d).length, 0);
});

test('Deploy realized says it counts only the strategies listed, never summing live with paper', async () => {
  const dep = (id, mode, pnl) => ({...dashboardDeployment(mode), id, strategy_id: id, realized_pnl: pnl});
  for (const [deployments, re] of [[[dep(1, 'paper', 2)], /Realized, listed below[\s\S]*\+\$2\.00[\s\S]*paper money, not real · after Kalshi fees and the <span class="nobr">spread<button[^>]*data-glo="paperfills"[\s\S]*?<\/button><\/span>/],
    [[dep(1, 'paper', 2), dep(2, 'live', 5)], /Live realized, listed below[\s\S]*\+\$5\.00[\s\S]*real money\u00a0· after Kalshi fees\u00a0· \+\$2\.00 on paper from the deployments listed, counted apart, after Kalshi fees and the <span class="nobr">spread<button[^>]*data-glo="paperfills"[\s\S]*?<\/button><\/span>/]]) {
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
  assert.match(cost().innerHTML, /uses your credits while it’s on \(\$18\.40 left\)\. When they fall to \$5\.00, auto-reload charges your card \$21\.10 for \$20\.00 more\./);
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
  assert.match(card().innerHTML, /<dt>Last check-in<\/dt><dd>Reviewing now<\/dd>/);
  assert.match(card().innerHTML, /Last move <time [^>]+>just now<\/time>: Autopilot switched on\./);
});

test('Meridian: while its paper strategy holds nothing, the autopilot card also says what the autopilot is doing', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(dashboardData()); }});
  f.S.me.user.autopilot = true;
  const flat = {code: 'waiting', line: 'No trades right now: ETH drift is waiting for a contract that fits its entry rules. Its last check: no edge.', action: null};
  f.S.ap = {autopilot: true, mode: 'paper', story: [], research: {tested_7d: 3, passed_7d: 0, active: ['btc15m']},
    live_running: 0, demo_running: 0, paper_running: 1, reviewing: false, idle: flat, last_action: null};
  f.S.apAt = Date.now();
  await f.viewDashboard(); await flush();
  const now = () => f.root.querySelector('#dash-ap .apcard-now').innerHTML;
  assert.match(now(), /Its last check: no edge\. Meanwhile it’s researching BTC 15-min up\/down\.$/);
  f.S.ap = {...f.S.ap, research: {tested_7d: 3, passed_7d: 0, active: []}};
  await f.viewDashboard(); await flush();
  assert.doesNotMatch(now(), /Meanwhile/);
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
    assert.match(monitor.querySelector('.monitor-setup').textContent, /BTC 15-min up\/down\u00a0· \$12\.50 \/ trade/);
    assert.ok(monitor.querySelector('.monitor-limits').textContent.includes('Max 4 open'));
    assert.ok(monitor.querySelector('.monitor-limits').textContent.startsWith('\u00a0· Max 4 open'), 'a space before the separator, so it never reads "trade· Max"');
    assert.equal(monitor.querySelector('.monitor-limits').textContent.includes('Risk &lt;cap&gt; reached'), d.status !== 'running');
    assert.equal(field('Realized').textContent, d.status === 'running' ? '—' : d.status === 'paused' ? '$0.00' : '−$3.25');
    assert.equal(field('Unrealized').textContent.trim(), d.status === 'running' ? 'Not marked yet' : d.status === 'paused' ? '$0.00' : '−$2.50');
    assert.equal(monitor.querySelectorAll('.monitor-metrics dt')[1].textContent.includes('(est.)'), d.unrealized_pnl != null && d.open_positions > 0);
    assert.equal(field('Closed').textContent, `${d.closed_trades} / ${d.open_positions}`);
    assert.equal(field('Closed').getAttribute('aria-label'), `${d.closed_trades} closed trades, ${d.open_positions} open positions`);
    const evidence = evidenceFor(monitor, d.id); assert.equal(evidence.tag, 'details'); assert.equal(evidence.open, false);
    // No backtest figure (a research session's strategy keeps its unseen result with the gatekeeper): no "Later-period P&L —".
    if (d.status === 'running') assert.ok(!evidence.textContent.includes('P&amp;L'), evidence.textContent);
    else assert.ok(visible(evidence.textContent).includes(`Later-period P&amp;L ${d.status === 'paused' ? '$0.00' : '+$7.25'}\u00a0· unseen\u00a0data`));
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
    assert.equal(create.textContent, frame.deployments.length ? 'New research' : 'Research an idea');
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
  remove.onclick(); await flush(); assert.equal(postRequests(f).length, 2);  // a double-click's second click does not confirm
  f.elapse(500); remove.onclick(); await flush();
  assert.equal(postRequests(f)[2].path, '/api/deployments/11/stop'); assert.equal(reads, 4);
  assert.deepEqual(f.navigations, []);
});

test('Meridian: a confirm press right after arming does nothing, so a fast double-click cannot skip "Confirm"', () => {
  const f = frontend(), btn = new Element('button'); btn.innerHTML = 'Remove';
  let fired = 0; const fire = () => { fired++; };
  f.armed(btn, 'Confirm stop', fire); f.armed(btn, 'Confirm stop', fire);
  assert.equal(fired, 0); assert.equal(btn.textContent, 'Confirm stop'); assert.equal(btn.dataset.armed, 'wait');
  f.elapse(500); f.armed(btn, 'Confirm stop', fire);
  assert.equal(fired, 1); assert.equal(btn.dataset.armed, '');
});

test('Meridian: a confirmed action that fails gives its button back as it was, and one that relabels it keeps its label', async () => {
  const f = frontend(), btn = new Element('button'); btn.innerHTML = 'Remove';
  let fired = 0;
  const fail = async () => { fired++; throw new Error('502'); };
  f.armed(btn, 'Confirm remove', fail); f.elapse(500);
  await f.armed(btn, 'Confirm remove', fail).catch(() => {});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(fired, 1); assert.equal(btn.textContent, 'Remove'); assert.equal(btn.dataset.armed, '');
  // Trying again is the same two presses: the first only arms.
  f.armed(btn, 'Confirm remove', fail);
  assert.equal(fired, 1); assert.equal(btn.textContent, 'Confirm remove');
  f.elapse(500); await f.armed(btn, 'Confirm remove', fail).catch(() => {});
  assert.equal(fired, 2);
  const on = new Element('button'); on.innerHTML = 'Resume';
  f.armed(on, 'Confirm resume', async () => { on.textContent = 'Pause'; }); f.elapse(500);
  await f.armed(on, 'Confirm resume', async () => { on.textContent = 'Pause'; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(on.textContent, 'Pause');
});

test('Meridian: the autopilot Kill and Reset to amount take a deliberate second press', async () => {
  const posts = [];
  const f = frontend({fetchImpl: (path, options = {}) => {
    if (path === '/api/funds') return response(funds());
    if (path === '/api/autopilot/status') return response({mode: 'paper', autopilot: true});
    if (path === '/api/autopilot/kill' || path === '/api/funds/paper') { posts.push(path); return response({ok: true, paused: 1}); }
    throw new Error('Unexpected offline request: ' + path);
  }});
  const box = new Element('div'); box.innerHTML = '<div id="apf-controls"></div><div id="apf-flash"></div>';
  f.apUpdate(box, {mode: 'paper', live_enabled: true, kalshi_connected: true, autopilot: true, autopilot_live: true});
  const kill = box.querySelector('[data-ap="kill"]');
  kill.onclick({currentTarget: kill, target: kill}); kill.onclick({currentTarget: kill, target: kill}); await flush();
  assert.deepEqual(posts, []); assert.equal(kill.textContent, 'Confirm kill');
  f.elapse(500); await kill.onclick({currentTarget: kill, target: kill}); await flush();
  assert.deepEqual(posts, ['/api/autopilot/kill']);
  await f.viewFunds();
  const submit = async () => {
    const form = f.root.querySelector('#paper'); form.amount = {value: '250'};
    form.querySelector('[data-kind="reset"]').onclick();
    await form.onsubmit({preventDefault() {}}); await flush(); await flush();
  };
  await submit(); await submit();
  assert.deepEqual(posts, ['/api/autopilot/kill']);
  f.elapse(500); await submit();
  assert.deepEqual(posts, ['/api/autopilot/kill', '/api/funds/paper']);
  assert.deepEqual(JSON.parse(postRequests(f).at(-1).options.body), {kind: 'reset', amount: 250});
});

test('Meridian admin: Halt new buys goes at once, Resume buys and waitlist Remove ask first', async () => {
  let kill = {on: false, reason: '', by: '', env_on: false};
  const f = frontend({fetchImpl: (path, options = {}) => {
    if (path === '/api/admin') return response({users: [], waitlist: [{email: 'synthetic@example.invalid', note: '', created_at: '2026-10-25T10:00:00Z', status: 'requested'}]});
    if (path === '/api/admin/kill-switch' && options.method === 'POST') { kill = {...kill, on: JSON.parse(options.body).on}; return response(kill); }
    if (path === '/api/admin/kill-switch') return response(kill);
    if (path === '/api/admin/waitlist') return response({ok: true});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.is_admin = true;
  await f.viewAdmin(); await flush();
  const form = f.root.querySelector('#kill'), btn = f.root.querySelector('#k-btn');
  const sent = (path) => postRequests(f).filter(row => row.path === path).map(row => JSON.parse(row.options.body));
  await form.onsubmit({preventDefault() {}}); await flush();
  assert.deepEqual(sent('/api/admin/kill-switch').map(b => b.on), [true]);  // halting is one press
  assert.equal(btn.textContent, 'Resume buys');
  form.onsubmit({preventDefault() {}}); form.onsubmit({preventDefault() {}}); await flush();
  assert.equal(sent('/api/admin/kill-switch').length, 1); assert.equal(btn.textContent, 'Confirm resume');
  f.elapse(500); await form.onsubmit({preventDefault() {}}); await flush();
  assert.deepEqual(sent('/api/admin/kill-switch').map(b => b.on), [true, false]);
  const remove = f.root.querySelector('#waitlist [data-wl="remove"]');
  remove.onclick(); remove.onclick(); await flush();
  assert.deepEqual(sent('/api/admin/waitlist'), []); assert.equal(remove.textContent, 'Confirm remove');
  f.elapse(500); await remove.onclick(); await flush();
  assert.deepEqual(sent('/api/admin/waitlist'), [{email: 'synthetic@example.invalid', action: 'remove'}]);
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
    assert.match(f.root.querySelector('.paper-summary').textContent, /Since you started: realized P&amp;L \+\$98\.40/);
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
        assert.equal(sample.getAttribute('aria-label'), `${date}\u00a0· ${amounts[index]}`);
        assert.equal(sample.querySelector('.chart-reading').getAttribute('aria-hidden'), 'true');
        assert.equal(sample.querySelector('.chart-reading text').textContent, `${date}\u00a0· ${amounts[index]}`);
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
  assert.ok(sample.getAttribute('aria-label').endsWith('\u00a0· −$3.00'));
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

// Money-pages walk 2026-10-30: with two days of closed P&L the Overview chart's date axis read "Oct 29, Oct 30, Oct 30"
// (its middle tick fell on the second day's midnight). Each day is named once; three or more days keep the middle tick.
// Its dates are the chart's own days: one between two points ("Oct 18", the midpoint of the 16th and the 19th) named
// a day with no closed P&L.
test('Overview Closed P&L chart names each day once on its date axis', async () => {
  const label = (d) => new Date(d + 'T12:00:00Z').toLocaleDateString(undefined, {month: 'short', day: 'numeric', timeZone: 'UTC'});
  let data;
  const f = frontend({fetchImpl: () => response(data)});
  const axis = () => f.root.querySelector('#paper-performance svg.chart').querySelectorAll('text')
    .filter((t) => t.getAttribute('y') === '174').map((t) => t.textContent);
  for (const [daily, expected] of [
    [[{d: '2026-10-29', pnl: 1}, {d: '2026-10-30', pnl: 2}], ['2026-10-29', '2026-10-30']],
    [[{d: '2026-10-28', pnl: 1}, {d: '2026-10-29', pnl: -1}, {d: '2026-10-30', pnl: 2}], ['2026-10-28', '2026-10-29', '2026-10-30']],
    // Days apart: no date between them, where the chart has no point.
    [[{d: '2026-10-16', pnl: -4}, {d: '2026-10-19', pnl: 2}], ['2026-10-16', '2026-10-19']],
  ]) {
    data = dashboardData({paper: {daily}});
    await f.viewDashboard(); f.clearTimers();
    assert.deepEqual(axis(), expected.map(label));
  }
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
    f.root.innerHTML = '<div id="boardbody">Next board</div><div id="main"><div class="paper-plot">Next page</div></div>';
    const board = f.root.querySelector('#boardbody'), main = f.root.querySelector('#main'), plot = main.querySelector('.paper-plot');
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
    // One book is named; a mix says "All books" (never a bare count that reads as the band's paper book).
    const bookOf = (modes) => new Set(modes).size > 1 ? 'All books' : {paper: 'Paper', demo: 'Demo', live: 'Live'}[modes[0]];
    const heading = ledger.querySelector('h2');
    assert.equal(heading.querySelector('.position-group-mode')?.textContent || '', bookOf(openModes));
    for (const [host, modes] of [[ledger, openModes], [history, closedModes]]) {
      const table = host.querySelector('table.t-positions'), labels = modes.map(mode => mode === 'live' ? 'LIVE' : mode === 'demo' ? 'Demo' : 'Paper');
      assert.equal(table.getAttribute('data-paper-only'), String(modes.every(mode => mode === 'paper')));
      assert.deepEqual(table.querySelectorAll('.position-mode').map(cell => cell.textContent), labels);
    }
    assert.equal(history.querySelector('summary .position-group-mode')?.textContent || '', bookOf(closedModes));
    assert.equal(postRequests(f).length, 0);
  }
});

test('Overview open positions under the Paper portfolio band count each book apart and say they cover all books', async () => {
  // "Open positions 3" sat under the Paper portfolio band, beside its paper-only "Open at cost + fees $12.90", with a
  // Demo row among the three: the count read as three paper positions.
  const data = dashboardData({paper: {open_positions: 2, open_cost: 12.9},
    open_positions: [dashboardPosition(1), dashboardPosition(2), dashboardPosition(3, {mode: 'demo'})],
    recent_closed: [dashboardPosition(4), dashboardPosition(5, {mode: 'demo'}), dashboardPosition(6, {mode: 'demo'})],
    deployments: [dashboardDeployment('paper'), {...dashboardDeployment('demo'), id: 92}]});
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(data); }});
  await f.viewDashboard();
  const band = f.root.querySelector('.account-band').textContent;
  assert.match(band, /Paper portfolio/);
  const heading = f.root.querySelector('#dash-open h2');
  assert.equal(heading.querySelector('.section-count').textContent, '2\u00a0paper\u00a0\u00b7 1\u00a0demo');
  assert.equal(heading.querySelector('.position-group-mode').textContent, 'All books');
  assert.doesNotMatch(heading.textContent, /\b3\b/, 'never one count across books');
  const summary = f.root.querySelector('#recent-settlements summary');
  assert.match(summary.textContent, /Recent settlements 1\u00a0paper\u00a0\u00b7 2\u00a0demo All books/);
  // No money is added up across books in the heading.
  assert.doesNotMatch(heading.innerHTML + summary.innerHTML, /\$/);
  // A single book is named, with its count.
  const one = dashboardData({open_positions: [dashboardPosition(1, {mode: 'demo'}), dashboardPosition(2, {mode: 'demo'})]});
  const g = frontend({fetchImpl: () => response(one)});
  await g.viewDashboard();
  const h = g.root.querySelector('#dash-open h2');
  assert.equal(h.querySelector('.section-count').textContent, '2');
  assert.equal(h.querySelector('.position-group-mode').textContent, 'Demo');
  assert.equal(postRequests(f).length + postRequests(g).length, 0);
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
    assert.equal(performanceMode.textContent, 'Paper\u00a0· cumulative, after Kalshi fees and the spread', name + ' source performance scope remains available');
    assert.equal(performanceMode.querySelector('.performance-mode-prefix').textContent, 'Paper\u00a0· ', name);
    assert.equal(performanceMode.getAttribute('aria-hidden'), null, name);
    assert.equal(JSON.stringify(data), before, name + ' source records are immutable');
    assert.equal(postRequests(f).length, 0, name);
  }
  assert.equal(reads, cases.length);
});

test('Overview: an open position whose market has closed says so under its expiry; one still to close and a settled row do not', async () => {
  // Walk 2026-10-30: a live position still held a day after its close read only "Oct 29, 07:48 UTC" under Expiry, a date
  // that read as still to come. Tau's dashboard said "closed, result pending" for the same row.
  const past = new Date(Date.now() - 3 * 3600e3).toISOString(), future = new Date(Date.now() + 40 * 60e3).toISOString();
  const f = frontend({fetchImpl: () => response(dashboardData({
    open_positions: [dashboardPosition(1, {market_close_time: past, mode: 'live'}), dashboardPosition(2, {market_close_time: future}),
      dashboardPosition(3, {market_close_time: 'not-a-date'})],
    recent_closed: [dashboardPosition(4, {market_close_time: past})]}))});
  await f.viewDashboard();
  const rows = f.root.querySelectorAll('.open-position'); assert.equal(rows.length, 3);
  const cell = (row) => row.querySelector('.position-expiry-cell');
  assert.equal(cell(rows[0]).querySelector('.position-expired').textContent, 'Closed, result pending');
  assert.equal(cell(rows[0]).querySelector('time').getAttribute('datetime'), past, 'the date stays beside it');
  assert.equal(cell(rows[1]).querySelector('.position-expired'), null, 'a market still open says nothing more');
  assert.equal(cell(rows[2]).querySelector('.position-expired'), null); assert.equal(cell(rows[2]).querySelector('.vh').textContent, 'Expiry unavailable');
  const settled = f.root.querySelector('.settled-position'); assert.ok(settled);
  assert.equal(cell(settled).querySelector('.position-expired'), null, 'a settled row needs no pending note');
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.position-expired \{ display: block;/);
});

test('Overview contract identities use the catalog and expiry, keep the raw ticker in the details only, and fall back safely', async () => {
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
  assert.deepEqual(headers.map(th => th.textContent), ['Market / contract', 'Position', 'Expiry', 'Entry', 'Cost + fee', 'Unrealized P&amp;L']);
  assert.ok(headers.every(th => th.getAttribute('scope') === 'col'));
  samples.forEach((sample, index) => {
    const row = rows[index], detail = row.querySelector('.position-details'), summary = detail.querySelector('summary');
    const market = summary.querySelector('.position-market'), secondary = detail.querySelector('.sub-fig');
    assert.equal(detail.tag, 'details'); assert.equal(detail.open, false); assert.equal(detail.dataset.position, `open-${index + 1}`);
    assert.equal(summary.contains(secondary), false); assert.equal(secondary.querySelector('.position-opened').textContent, 'Opened 2m ago');
    // The market's plain name leads; a contract no listed market covers reads "Kalshi contract", never its ticker.
    if (sample.known) assert.ok(market.textContent.startsWith(sample.label), sample.ticker);
    else assert.equal(market.textContent, 'Kalshi contract', sample.ticker);
    if (sample.expiry) {
      const date = new Date(positions[index].market_close_time).toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
      assert.ok(row.querySelector('.position-expiry-cell time').textContent.includes(date), sample.ticker + ' expiry');
      assert.equal(row.querySelector('.position-expiry-cell time').getAttribute('datetime'), new Date(positions[index].market_close_time).toISOString());
      const absolute = new Date(positions[index].market_close_time).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'long', hourCycle: 'h23'});
      assert.equal(secondary.querySelector('.position-absolute').textContent, 'Expires ' + absolute);
    } else { assert.equal(row.querySelector('.position-expiry-cell time'), null); assert.equal(row.querySelector('.position-expiry-cell .vh').textContent, 'Expiry unavailable'); assert.equal(secondary.querySelector('.position-absolute'), null); }
    // The ticker (it carries the raw series key) sits only in the details, as the Kalshi contract to find it by.
    const raw = sample.known ? sample.ticker : sample.label;
    assert.equal(secondary.querySelector('.kalshi-ref .tick').textContent, raw, sample.ticker + ' raw identifier');
    assert.equal(row.querySelector('.position-contract'), null);
    assert.ok(!summary.textContent.includes(raw), 'the ticker is never the headline');
    assert.ok(!summary.getAttribute('aria-label').includes(raw));
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
  assert.equal(table.querySelectorAll('.open-position').at(-1).querySelector('.kalshi-ref .tick').textContent, 'UNKNOWN-A');
  assert.equal(table.querySelectorAll('.open-position').at(-1).querySelector('.position-market').textContent, 'Kalshi contract');
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
  assert.deepEqual(table.querySelectorAll('.kalshi-ref .tick').map(el => el.textContent), rows.map(row => row.ticker));
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
        .endsWith(source.mode === 'live' ? '\u00a0· LIVE' : '\u00a0· Paper'));
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
  const costs = ['$3.50', '$1.00', '$1.50'], marks = ['+$2.50', '—Not marked yet', '$0.00'], modes = ['LIVE', 'Demo', 'Paper'];
  rows.forEach((row, index) => {
    const cells = row.querySelectorAll('td');
    assert.equal(cells.length, 6);
    assert.equal(cells[0].querySelector('.position-title').textContent, open[index].title);
    assert.equal(cells[0].querySelector('.position-market').textContent, 'Kalshi contract');  // no market listed here: never the ticker
    assert.equal(cells[0].querySelector('.kalshi-ref .tick').textContent, open[index].ticker);
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
  // Walk 2026-10-30: one phrase for a position with no mark yet on every page; the dash keeps the cell compact, its
  // spoken word and hover say "Not marked yet".
  assert.equal(rows[1].querySelector('.unavailable .vh').textContent, 'Not marked yet');
  assert.equal(rows[1].querySelector('.unavailable').getAttribute('title'), 'Not marked yet');
  assert.equal(rows[1].querySelector('.position-mark-note').textContent, 'Unrealized: not marked yet');
  assert.doesNotMatch(rows[1].innerHTML, /\$199\.00/);
  const closedRow = history.querySelector('.settled-position'), cells = closedRow.querySelectorAll('td');
  assert.equal(cells.length, 5);
  assert.equal(cells[0].querySelector('.position-title').textContent, settled.title);
  assert.equal(cells[0].querySelector('.kalshi-ref .tick').textContent, settled.ticker);
  assert.equal(cells[1].querySelector('.position-side').textContent, settled.side.toUpperCase());
  assert.equal(cells[1].querySelector('.position-quantity').textContent, `Quantity ${settled.qty}`);
  assert.deepEqual(history.querySelectorAll('thead th').map(th => th.textContent), ['Market / contract', 'Position', 'Expiry', 'Entry', 'Realized P&amp;L']);
  assert.equal(closedRow.querySelector('.position-cost'), null);
  const closedDetail = closedRow.querySelector('.position-details');
  assert.equal(closedDetail.tag, 'details'); assert.equal(closedDetail.open, false); assert.equal(closedDetail.dataset.position, 'closed-4');
  assert.ok(closedDetail.querySelector('.sub-fig').textContent.includes('Kalshi contract ' + settled.ticker + '\u00a0· ' + settled.title));
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
    // A connected key's cash is never behind the closed menu: under paper in the band, its own figure.
    const cashInBand = !livePrimary && !!data.live.connected;
    assert.deepEqual(accounts.querySelectorAll('dt.lab').map(lab => lab.textContent),
      livePrimary ? ['Paper portfolio', 'Tau’s demo book'] : cashInBand ? ['Tau’s demo book'] : ['Kalshi cash', 'Tau’s demo book'], label);
    assert.equal(accounts.contains(f.root.querySelector('.paper-summary')), livePrimary, label);
    assert.equal(!!primary.querySelector('.kalshi-cash'), cashInBand, label);
    if (!livePrimary) assert.equal((cashInBand ? primary.querySelector('.kalshi-cash') : accounts).querySelector('.fig').textContent, secondaryLive, label);
    const paper = f.root.querySelector('.paper-summary');
    for (const amount of ['$1,111.25', '+$98.40', '−$7.50', '$900.00', '$211.25']) assert.ok(visible(paper.textContent).includes(amount), label + ' paper ' + amount);
    assert.match(accounts.textContent, /\$2,222\.50/); assert.match(accounts.textContent, /\$2,200\.00 capital/);
    const liveHost = livePrimary || cashInBand ? primary : accounts;
    if (!data.live.connected) assert.equal(liveHost.querySelector('a').getAttribute('href'), '/funds#connect-kalshi', label);
    if (data.live.connected && data.live.balance == null) assert.match(liveHost.textContent, /read your Kalshi balance/, label);
    if (livePrimary) {
      for (const amount of ['−$2.00', '$50.00']) assert.ok(visible(primary.textContent).includes(amount), label + ' live ' + amount);
      if (data.live.connected && data.live.balance != null) assert.ok(visible(primary.textContent).includes('+$17.00'), label + ' realized live P&L');
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
    assert.match(f.root.querySelector('.dashboard-figures').textContent, /\$4,444\.00/);
    assert.doesNotMatch(next.textContent, /\$4,444\.00/);
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
  const output = f.root.querySelector('#main').innerHTML;
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
  f.S.gen++; f.root.innerHTML = '<div id="main">Next page</div>';
  const writes = f.root.writes, main = f.root.querySelector('#main');
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
  host.querySelector('#cancel').onclick(); assert.equal(postRequests(f).length, 2);  // the first press only arms
  // The run page's 2s poll calls again with the same status: the armed confirm survives it, so the
  // second press cancels instead of arming a fresh button.
  f.runControls(host, 9, 'paused', reload);
  const cancel = host.querySelector('#cancel'); assert.equal(cancel.textContent, 'Confirm cancel');
  cancel.onclick(); assert.equal(postRequests(f).length, 2);  // a press right after arming (a double-click) does nothing
  f.elapse(500); await cancel.onclick(); assert.equal(postRequests(f)[2].path, '/api/runs/9/cancel'); assert.equal(reloads, 3);
  assert.match(cancel.getAttribute('title'), /^Ends the session for good\. What it has spent stays charged/);
});

test('a poll with the same run status leaves a pause in flight disabled, so it cannot be sent twice', async () => {
  const pending = deferred(), f = frontend({fetchImpl: () => pending.promise}), host = new Element();
  f.runControls(host, 9, 'running', async () => {});
  const pause = host.querySelector('#pause'), pressing = pause.onclick({currentTarget: pause});
  assert.equal(pause.disabled, true);
  f.runControls(host, 9, 'running', async () => {});  // the poll lands while the POST is out
  assert.equal(host.querySelector('#pause'), pause); assert.equal(pause.disabled, true);
  assert.equal(postRequests(f).length, 1);
  pending.resolve(response({ok: true})); await pressing;
  f.runControls(host, 9, 'paused', async () => {});  // a new status repaints
  assert.ok(host.querySelector('#resume')); assert.equal(host.querySelector('#pause'), null);
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
  assert.match(hypothesis.querySelector('[data-review]').innerHTML, /Sound mechanism/);
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
  // A list that announces what is added (a role="log" on the <ol> took away its list semantics).
  assert.equal(f.root.querySelector('#log').getAttribute('aria-live'), 'polite'); assert.equal(f.root.querySelector('#log').getAttribute('role'), null);
  assert.match(f.root.querySelector('#runboard').innerHTML, /&lt;script&gt;/);
  assert.doesNotMatch(f.root.querySelector('#runboard').innerHTML, /<script>/);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Paused/);
  assert.ok(f.root.querySelector('#resume')); assert.equal(f.root.querySelector('#runpulse'), null);
});

test('Meridian: a run names its model and says it runs until stopped, or how many strategies it tests', async () => {
  const page = async (extra) => {
    const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', ...extra};
    const f = frontend({fetchImpl: () => response({run, events: []})});
    await f.viewRun(9);
    const deck = f.root.querySelector('#runboard').innerHTML;
    f.clearTimers();
    return deck;
  };
  // The default model's key is null: the server sends its customer name, never the internal id.
  assert.match(await page({model: null, model_label: 'Claude Opus 4.6', run_forever: 1, max_hypotheses: 10}), /Claude Opus 4\.6 · Runs until you stop it/);
  assert.match(await page({model: 'sonnet-4-6', model_label: 'Claude Sonnet 4.6', run_forever: 0, max_hypotheses: 25}), /Claude Sonnet 4\.6 · Up to 25 strategies/);
  assert.match(await page({status: 'cancelled', model_label: 'Claude Opus 4.6', run_forever: 1}), /Ran until stopped/);
  assert.doesNotMatch(await page({model: 'sonnet-4-6', model_label: '<b>x</b>', run_forever: 1}), /sonnet-4-6|<b>x/);
});

test('Meridian: a Pause that keeps failing replaces its error notice instead of stacking one per press', async () => {
  const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
  const f = frontend({fetchImpl: (path, opts) => (opts && opts.method === 'POST')
    ? response({error: 'Only a running session can be paused.'}, 409) : response({run, events: []})});
  await f.viewRun(9);
  for (let i = 0; i < 3; i++) {
    const pause = f.root.querySelector('#pause');
    await pause.onclick({currentTarget: pause});
  }
  assert.equal(postRequests(f).length, 3);
  const flashHtml = f.root.querySelector('#flash').innerHTML;
  assert.equal((flashHtml.match(/class="notice bad"/g) || []).length, 1);
  assert.match(flashHtml, /Only a running session can be paused\./);
  f.clearTimers();
});

test('a Research run queued or silent past the reaper limit says how long, a queued one in the word Queued', async () => {
  const at = (wait, status = 'queued') => {
    const run = {id: 9, prompt: 'Idea', status, market: 'btc15m', created_at: '2026-10-17T10:00:00Z', wait};
    return frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: []}); }});
  };
  let f = at({state: 'queued', seconds: 90, overdue: false});
  await f.viewRun(9);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Queued');
  // Status says the badge's word: it said "Waiting" beside the badge's "Queued" (walk 2026-10-30).
  assert.match(f.root.querySelector('#runfigs').textContent, /Status\s*Queued/);
  assert.doesNotMatch(f.root.querySelector('#runfigs').textContent, /Waiting/);
  assert.equal(f.root.querySelector('#rsiobs [data-wait]').hidden, true);
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').hidden, false);
  f.clearTimers();
  f = at({state: 'queued', seconds: 540, overdue: true, ahead: 1});
  await f.viewRun(9);
  // One word for the state, overdue or not: Status said "Waiting 9 min" where the badge said "Queued" a minute before.
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Queued 9 min/);
  assert.doesNotMatch(f.root.querySelector('#runfigs').innerHTML, /Waiting/);
  assert.equal(f.root.querySelector('#rsiobs [data-livetext]').textContent, 'Queued 9 min');
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
  // Each figure's line as a desktop reads it (bt-long), then a phone's short form of it (bt-short, its hover the full line).
  const shortOf = row => { const s = row.querySelector('.num .bt-short'); return s ? s.textContent : null; };
  assert.deepEqual(rows.map(row => { const c = row.querySelector('.num'), s = shortOf(row); return s == null ? c.textContent : c.textContent.slice(0, -s.length); }),
    ['+$12.00later-period P&amp;L after the split date\u00a0· unseen\u00a0data', '−$4.25later-period P&amp;L after the split date\u00a0· unseen\u00a0data\u00a0· did not pass', '−$7.50on the history it searched\u00a0· did not pass', '$0.00on the history it searched', '—']);
  assert.deepEqual(rows.map(shortOf), ['later\u00a0period\u00a0· unseen\u00a0data', 'later\u00a0period\u00a0· unseen\u00a0data\u00a0· did\u00a0not\u00a0pass', 'history it searched\u00a0· did\u00a0not\u00a0pass', 'history it searched', null]);
  assert.deepEqual(rows.map(row => row.querySelector('.num').getAttribute('data-lab')), ['Backtest P&amp;L', 'Backtest P&amp;L', 'Backtest P&amp;L', 'Backtest P&amp;L', 'Backtest P&amp;L']);
  assert.match(results.innerHTML, /Kept &lt;script&gt;unsafe&lt;\/script&gt;/); assert.match(results.innerHTML, /&lt;img src=x&gt;/);
  assert.doesNotMatch(results.innerHTML, /<script>|<img|data-dep|class="pick"/);
  const originalLink = results.querySelector('a[href="/strategies/12"]'); originalLink.focus();
  payload = {...payload, strategies: [...strategies].reverse()}; poll(); await flush();
  const reorderedLink = results.querySelector('a[href="/strategies/12"]');
  assert.notEqual(reorderedLink, originalLink); assert.equal(originalLink.isConnected, false);
  assert.equal(f.document.activeElement, reorderedLink); assert.equal(reorderedLink.focusOptions.preventScroll, true);
  assert.deepEqual(results.querySelectorAll('tbody .name a').map(a => a.getAttribute('href')), [11, 15, 14, 13, 12].map(id => `/strategies/${id}`));  // passed first, the rest as returned
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
  assert.equal(stages.tag, 'ol'); assert.deepEqual(stages.querySelectorAll('li').map(label => label.textContent), ['Explore', 'Backtest', 'Check', 'Improve']);
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

// `seq` is the session's number among the user's own (the server's per-user count), never its run id.
const researchRun = (id, status) => ({id, seq: 10 + id, status, prompt: `Idea ${id}`, market: 'btc15m',
  created_at: '2026-10-17T10:00:00Z', hypotheses_tried: id, strategies_passed: status === 'succeeded' ? 1 : 0});
function researchFrontend(runs = [], {policy = null, ...options} = {}) {
  return frontend({...options, fetchImpl: path => {
    if (path === '/api/models') return response({models: [{key: 'offline', label: 'Offline model'}], default: 'offline'});
    if (path === '/api/research/context') return response({markets: []});
    if (path.startsWith('/api/research/scoreboard')) return response({total: {runs: 0}});
    if (path === '/api/research/estimate') return response(options.estimate || {yours: null, sessions: 0, typical: {}});
    assert.equal(path, '/api/runs');
    return response({runs, counts: {research_running: runs.filter(run => run.status === 'running').length,
      research_paused: runs.filter(run => run.status === 'paused').length,
      research_queued: runs.filter(run => run.status === 'queued').length}, policy: typeof policy === 'function' ? policy() : policy});
  }});
}

// The pipeline figure's diversification step (gatekeeper.marginal_contribution_ok) said "Marginal-contribution check".
// It says what the check tests: daily returns against a strategy already passed on the same market, |ρ| ≤ 0.80.
test('Meridian: Research’s pipeline figure names the diversification check in plain words', async () => {
  const f = researchFrontend([]);
  await f.viewResearch(); await flush();
  const fig = f.root.querySelector('.pipefig').innerHTML;
  assert.match(fig, /Adds something new[\s\S]*Its daily returns can’t move too closely with a strategy that already passed here on the same market \(correlation \|ρ\| ≤ 0\.80\)\. A near-copy adds nothing\./);
  assert.doesNotMatch(fig, /Marginal|contribution/i);
  f.clearTimers();
});

test('Meridian: Research counts a paused session as paused, not as running', async () => {
  // One running and one paused said "Running 2" (the server folded paused into running).
  let f = researchFrontend([researchRun(4, 'running'), researchRun(5, 'paused')]);
  await f.viewResearch(); await flush();
  let status = f.root.querySelector('#research-status').innerHTML;
  assert.match(status, /Running<\/dt><dd><span class="fig ">1<\/span>/);
  assert.match(status, /Paused<\/dt><dd><span class="fig ">1<\/span>/);
  f.clearTimers();
  // No paused session: no Paused figure.
  f = researchFrontend([researchRun(4, 'running')]);
  await f.viewResearch(); await flush();
  status = f.root.querySelector('#research-status').innerHTML;
  assert.doesNotMatch(status, /Paused/);
  f.clearTimers();
});

test('a session row’s cost keeps its own line in the Market column, and the example’s note sits under its title', async () => {
  // Walk 2026-10-27 at 1280px: the 120px Market column read "BTC above $X at / 5pm ET · Cost: / $0.06", and the
  // example's "An example Tau ran f…" was cut there.
  const example = {...researchRun(1, 'succeeded'), direction: 'random_walk', example: true, spent_usd: 0};
  const mine = {...researchRun(6, 'succeeded'), example: false, spent_usd: 0.06};
  const f = researchFrontend([mine, example]);
  await f.viewResearch(); await flush();
  const [own, ex] = f.root.querySelectorAll('#runs a.run-card').map((a) => a.innerHTML);
  // It names the credits it came from (walked 2026-10-28), on a line of its own when the column is narrow.
  assert.match(own, /<span class="run-cost"><span class="run-sep"> · <\/span>Cost: \$0\.06<span class="run-cred"> in\u00a0credits<\/span><\/span>/);
  assert.match(ex, /<span class="run-note">An example Tau ran for you when you signed up\. It cost you nothing\.<\/span>/);
  assert.doesNotMatch(ex.match(/<span class="run-meta">.*?<\/span><span class="run-when">/s)[0], /example Tau ran|Cost/);
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  const rule = (sel) => [...css.matchAll(new RegExp('\\n' + sel.replace(/[.()]/g, '\\$&') + ' \\{([^}]*)\\}', 'g'))].map((m) => m[1]).join(';');
  // It wraps in that column, never leaving one word on its last line (test_ui_layout.mjs: kept to one line it was cut).
  assert.match(rule('.research-history .run-cost'), /display: block; white-space: normal; text-wrap: pretty;/);
  assert.match(rule('.research-history .run-cost .run-sep'), /display: none;/);
  assert.match(rule('.research-history .run-meta'), /-webkit-line-clamp: none;/);
  assert.match(rule('.research-history .run-note'), /grid-column: 1; grid-row: 2;/);
  f.clearTimers();
});

test('Research lists the seeded example as an example and does not count it as a session', async () => {
  const example = {...researchRun(1, 'succeeded'), direction: 'random_walk', example: true, spent_usd: 0};
  const mine = {...researchRun(6, 'succeeded'), example: false, spent_usd: 0.42};
  // The heading counts what it lists: "Recent sessions 1" sat over two rows, one of them the example.
  for (const [runs, count] of [[[example], '1 example'], [[mine, example], '1 · 1 example'], [[mine], '1']]) {
    const f = researchFrontend(runs);
    await f.viewResearch(); await flush();
    const list = f.root.querySelector('#runs').innerHTML;
    assert.equal(f.root.querySelector('#rcount').textContent, count);
    assert.equal(f.root.querySelectorAll('#runs a.run-card').length, runs.length, 'one row per thing the heading counts');
    if (!runs.includes(example)) { f.clearTimers(); continue; }
    assert.match(list, /Example<\/span>/); assert.match(list, /An example Tau ran for you when you signed up\. It cost you nothing\./);
    assert.doesNotMatch(list, /Cost: \$0\.00/);
    if (runs.includes(mine)) assert.match(list, /Cost: \$0\.42/);
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
  assert.match(html, /v2<\/b> on trial\u00a0· 2 of 6 ideas reached the gate\u00a0· 81% likely better/);
  assert.match(html, /feature missing/); assert.match(html, /calibration &lt;4h/);
  assert.match(html, /On paper at the market’s real prices: 2 passed strategies, 1 trading, 12 closed trades, net −\$1\.50, losing money where the backtest expected a profit/);
  assert.match(html, /3 of 20 ideas reached the gate\u00a0· on paper 12 closed trades, −\$1\.50/);
  assert.match(html, /order-book feature\u00a0· flow_imb_60s<\/b>\u00a0· idea re-tested\u00a0· <a href="\/research\/44">session<\/a>/);
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
    assert.equal(active.querySelector('.active-session b').textContent, `Session ${10 + featured}`);
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
      assert.equal(card.querySelector('.run-id').textContent, `Session ${run.seq}`);
      assert.ok(card.querySelector('.run-title').textContent.includes(run.prompt));
    }
    for (const run of runs.filter(run => run.status === 'paused' && run.id !== featured)) {
      assert.equal(history.querySelector(`a[href="/research/${run.id}"] .run-state`).textContent, 'Outcome Paused');
    }
    assert.equal(f.root.querySelector('#rcount').textContent, String(runs.length - 1));
    assert.equal(postRequests(f).length, 0);
  });
}

test('Research numbers a user\'s sessions among their own, never by the global run id', async () => {
  // A user's first session is run 8 in the whole app, and the seeded example (no number) is older.
  const runs = [{...researchRun(9, 'running'), seq: 2}, {...researchRun(8, 'succeeded'), seq: 1},
    {...researchRun(2, 'succeeded'), seq: undefined, example: true}];
  const f = researchFrontend(runs); await f.viewResearch(); await flush();
  const active = f.root.querySelector('#active-research'), history = f.root.querySelector('#runs');
  assert.equal(active.querySelector('.active-session b').textContent, 'Session 2');
  assert.equal(history.querySelector('a[href="/research/8"] .run-id').textContent, 'Session 1');
  assert.equal(history.querySelector('a[href="/research/2"] .run-id'), null);
  for (const html of [active.innerHTML, history.innerHTML]) assert.doesNotMatch(html, /Session (8|9)\b/);
  // An answer without numbers (an older server) shows none rather than the run id.
  const g = researchFrontend([{...researchRun(9, 'running'), seq: undefined}, {...researchRun(8, 'succeeded'), seq: undefined}]);
  await g.viewResearch(); await flush();
  assert.equal(g.root.querySelector('#active-research .active-session b'), null);
  assert.equal(g.root.querySelector('#runs a[href="/research/8"] .run-id'), null);
});

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
  assert.deepEqual(host.querySelectorAll('dt').map(dt => dt.textContent), ['Paper', 'Live (real money)']);
  assert.equal(host.querySelector('.snap-pnl .snap-head b').textContent, 'Realized P&amp;L');
  assert.equal(host.querySelector('dd.loss').textContent, '−$9.25'); assert.equal(host.querySelector('dd.gain').textContent, '+$12.50');
  for (const [pnl, trades, win_rate, values] of [
    [null, null, null, ['—']], [0, 0, 0, ['$0.00', '0', '0.0%']], [-4.5, 3, .25, ['−$4.50', '3', '25.0%']],
  ]) {
    assert.deepEqual(render({kind: 'strategy', id: 42, title: 'Title "quoted" <script>unsafe</script>', market: '<unsafe>', status: 'failed', pnl, trades, win_rate}), values);
    assert.equal(host.querySelector('a.snap').getAttribute('href'), '/strategies/42');
    assert.equal(host.querySelector('.snap-head .mk').textContent, 'Void');
    assert.match(host.innerHTML, /Title &quot;quoted&quot; &lt;script&gt;unsafe&lt;\/script&gt;/);
    assert.equal(host.querySelector('.snap-meta').textContent, 'Unlisted market');  // a key the catalog doesn’t list, never the key
    assert.deepEqual(host.querySelectorAll('dt').map(dt => dt.textContent),
      ['Later-period P&amp;L', ...(trades == null ? [] : ['Trades']), ...(win_rate == null ? [] : ['Win rate'])]);
    assert.deepEqual(host.querySelectorAll('.snap-secondary dt').map(dt => dt.textContent),
      [...(trades == null ? [] : ['Trades']), ...(win_rate == null ? [] : ['Win rate'])]);
  }
  for (const [mode, badge, realized_pnl, closed_trades, values] of [
    ['paper', 'Paper', 0, 0, ['$0.00', '0']], ['demo', 'Demo', -7.5, 4, ['−$7.50', '4']], ['live', 'LIVE', 12.5, 8, ['+$12.50', '8']],
  ]) {
    assert.deepEqual(render({kind: 'deployment', id: 7, title: '<script>unsafe</script>', market: '<unsafe>', mode, realized_pnl, closed_trades}), values);
    assert.equal(host.querySelector('.snap-head .mk').textContent, badge);
    assert.equal(host.querySelector('.snap-head .mk').classList.contains('live'), mode === 'live');
    assert.equal(host.querySelector('.snap-meta').textContent, 'Unlisted market');
    assert.deepEqual(host.querySelectorAll('dt').map(dt => dt.textContent), ['Realized P&amp;L', 'Closed trades']);
    assert.deepEqual(host.querySelectorAll('.snap-secondary dt').map(dt => dt.textContent), ['Closed trades']);
    assert.equal(host.querySelector('a'), null);
  }
  assert.deepEqual(f.requests, []); assert.deepEqual(f.navigations, []); assert.equal(f.intervals.size, 0);
});

test('Community: another trader’s strategy card says whose it is instead of a dead link; figures name the book, span and trade count', () => {
  const f = frontend(), host = new Element();
  const strat = {kind: 'strategy', id: 42, title: 'Fade', market: 'btc15m', status: 'passed', pnl: 42.17, trades: 23, win_rate: .61, days: 9.4};
  host.innerHTML = f.postSnapshot(strat, '@bob');
  assert.equal(host.querySelector('a'), null, 'their strategy page is theirs alone');
  assert.match(host.querySelector('.snap-note').textContent, /^Backtest over 9 days after the split date \(later\u00a0period\u00a0· unseen\u00a0data\), not paper or live trading\. Only @bob can open this strategy; ask them to share a copy from its page\.$/);
  host.innerHTML = f.postSnapshot(strat, '');
  assert.equal(host.querySelector('a.snap').getAttribute('href'), '/strategies/42');
  assert.doesNotMatch(host.querySelector('.snap-note').textContent, /Only/);
  host.innerHTML = f.postSnapshot({...strat, days: undefined}, '<b>x</b>');
  assert.match(host.querySelector('.snap-note').textContent, /^Backtest after the split date \(later\u00a0period\u00a0· unseen\u00a0data\), not paper/); assert.doesNotMatch(host.innerHTML, /<b>x/);
  // Each book on its own line with its trades; a book with none says so rather than $0.00. Never one sum.
  host.innerHTML = f.postSnapshot({kind: 'pnl', paper_pnl: 120.5, live_pnl: 0, paper_trades: 12, live_trades: 0});
  assert.deepEqual(host.querySelectorAll('dd').map(dd => dd.textContent), ['+$120.50on 12 trades', 'No trades yet']);
  assert.match(host.querySelector('.snap-kind').textContent, /All time/);
  host.innerHTML = f.postSnapshot({kind: 'pnl', paper_pnl: -2, live_pnl: 5, paper_trades: 1, live_trades: 3});
  assert.deepEqual(host.querySelectorAll('dd').map(dd => dd.textContent), ['−$2.00on 1 trade', '+$5.00on 3 trades']);
  host.innerHTML = f.postSnapshot({kind: 'deployment', id: 7, title: 'Fade', market: 'btc15m', mode: 'demo', realized_pnl: 7.2, closed_trades: 4, since: '2026-10-03T12:00:00Z'});
  assert.equal(host.querySelector('.snap-head .mk').textContent, 'Demo'); assert.match(host.querySelector('.snap-since').textContent, /^since Oct 3, 2026$/);
});

test('Community: replies that fail to load say so with Try again, never an empty thread', async () => {
  let failing = true;
  const post = {id: 11, body: 'Hi', author: 'Bob', username: 'bob', created_at: '2026-10-17T10:00:00Z', mine: false, comments: 2, reactions: []};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/strategies') return response({strategies: []});
    if (path === '/api/community') return response({posts: [post]});
    if (path === '/api/community/11/comments') return failing ? response({error: 'Server error.'}, 500) : response({comments: [{body: 'First', author: 'Ana', created_at: '2026-10-17T10:00:00Z'}]});
    throw new Error('unexpected ' + path);
  }});
  await f.viewCommunity(); await flush();
  const feed = f.root.querySelector('#feed'), click = target => feed.listeners.get('click')({target});
  const thread = feed.querySelector('[data-act="comments"]');
  thread.click = () => click(thread);
  await click(thread); await flush();
  const box = feed.querySelector('.comments');
  assert.equal(box.hidden, false); assert.match(box.querySelector('.notice').textContent, /Replies didn’t load/);
  assert.equal(box.querySelector('.cmt-list'), null); assert.equal(box.querySelector('.cmt-form'), null);
  failing = false;
  await click(box.querySelector('[data-replies-retry]')); await flush();
  assert.equal(box.hidden, false); assert.match(box.querySelector('.cmt-list').textContent, /First/);
  assert.equal(postRequests(f).length, 0);
});

test('Community: editing a post starts from the text as written and keeps its formatting after Save', async () => {
  const source = '**Bold** and [docs](https://example.com/a)';
  const post = {id: 11, body: source, author: 'Me', username: 'me', created_at: '2026-10-17T10:00:00Z', mine: true, comments: 0, reactions: []};
  const f = frontend({fetchImpl: (path, options) => {
    if (path === '/api/strategies') return response({strategies: []});
    if (path === '/api/community') return response({posts: [post]});
    if (path === '/api/community/11/edit') return response({ok: true});
    throw new Error('unexpected ' + path);
  }});
  await f.viewCommunity(); await flush();
  const feed = f.root.querySelector('#feed'), bodyEl = feed.querySelector('.post-body');
  let form = null;
  bodyEl.insertAdjacentElement = (_where, el) => { form = el; };
  const proto = Object.getPrototypeOf(bodyEl), had = 'setSelectionRange' in proto;
  if (!had) proto.setSelectionRange = () => {};
  try {
    await feed.listeners.get('click')({target: feed.querySelector('[data-act="edit"]')}); await flush();
    const ta = form.querySelector('textarea');
    assert.equal(ta.textContent, source, 'the edit box holds the markdown, not the rendered text');
    ta.value = '**Bolder** now';
    await form.onsubmit({preventDefault() {}}); await flush();
    assert.match(bodyEl.innerHTML, /<b>Bolder<\/b> now/);
    assert.equal(JSON.parse(postRequests(f).at(-1).options.body).body, '**Bolder** now');
  } finally { if (!had) delete proto.setSelectionRange; }
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

test('Explore: an empty feed says the list has not arrived (not that a blank search missed) and a failed read offers Try again', async () => {
  let reply = () => response({total: 0, shown: 0, matched: 0, per: 40, page: 0, markets: []});
  const f = frontend({fetchImpl: () => reply()});
  await f.viewExplore();
  const body = f.root.querySelector('#xbody');
  assert.equal(body.querySelector('.empty h2').textContent, 'No markets to show yet');
  assert.doesNotMatch(body.innerHTML, /No markets match/);
  reply = () => response({error: 'Tau is taking too long to respond.'}, 503);
  await body.querySelector('[data-xretry]').onclick(); await flush();
  assert.equal(body.querySelector('.empty h2').textContent, 'Markets didn’t load');
  assert.match(body.querySelector('.empty p').textContent, /taking too long/);
  const searched = frontend({search: '?q=zzz', fetchImpl: () => response({total: 3, shown: 3, matched: 0, per: 40, page: 0, markets: []})});
  await searched.viewExplore();
  assert.equal(searched.root.querySelector('#xbody .empty h2').textContent, 'No markets match “zzz”');
  assert.equal(searched.root.querySelector('#xbody [data-xretry]'), null);
});

test('Explore preserves distinct source counts and search zeroes while omitting duplicates and reporting source snapshot age', async () => {
  const recent = new Date(Date.now() - 30000).toISOString(), old = new Date(Date.now() - 240000).toISOString();
  const market = Object.freeze({t: 'BTC-26OCT19', ti: 'Bitcoin <unsafe>', s: 'BTC', bid: .51, ask: .53, v24: 1200, oi: 4});
  for (const [search, total, shown, matched, at, expected] of [
    ['', 3, 2, 1, recent, [['In this list', '2'], ['Tracked', '3'], ['Matching', '1'], ['Prices updated', 'just now']]],
    ['', 1, 1, 1, old, [['In this list', '1'], ['Prices updated', '4m ago']]],
    ['?q=%3Cunsafe%3E', 3, 2, 0, undefined, [['In this list', '2'], ['Tracked', '3'], ['Matching', '0'], ['Prices updated', 'Time unavailable']]],
    ['?q=btc', 1, 1, 1, 'not-a-timestamp', [['In this list', '1'], ['Matching', '1'], ['Prices updated', 'Time unavailable']]],
    // No feed yet (no time, nothing tracked): one figure says so, never "Available markets 0" and "Time unavailable".
    ['', 0, 0, 0, undefined, [['Market feed', 'Not in yet']]],
  ]) {
    const payload = Object.freeze({total, shown, matched, at, per: 40, page: 0, markets: Object.freeze(matched ? [market] : [])});
    const before = JSON.stringify(payload), query = new URLSearchParams(search), q = query.get('q') || '';
    const endpoint = '/api/explore?' + new URLSearchParams({q, sort: 'v24', page: '0'});
    const f = frontend({search, fetchImpl: path => { assert.equal(path, endpoint); return response(payload); }});
    await f.viewExplore();
    assert.deepEqual(f.root.querySelectorAll('#xfigs .m').map(fig => [fig.querySelector('dt').textContent,
      (fig.querySelector('.snapshot-age') || fig.querySelector('.fig')).textContent]), expected);
    const snapshot = f.root.querySelector('.snapshot-time'), time = snapshot && snapshot.querySelector('time');
    if (!total) assert.equal(snapshot, null);
    else if (Number.isFinite(Date.parse(at))) {
      // The age is the visible figure; the snapshot's own time is its hover, never a second raw stamp beside it
      // ("Prices updated 6m ago 2026-10-28 00:12:19 UTC").
      assert.equal(time.getAttribute('datetime'), at); assert.equal(time, snapshot.querySelector('.snapshot-age'));
      assert.equal(snapshot.querySelectorAll('time').length, 1); assert.doesNotMatch(snapshot.textContent, /UTC|\d{4}-\d\d-\d\d/);
      assert.match(time.getAttribute('title'), / UTC$/); assert.equal(Date.parse(time.getAttribute('title')), Date.parse(at));
      assert.equal(snapshot.classList.contains('snapshot-old'), at === old);
      assert.equal(!!snapshot.querySelector('.snapshot-behind'), at === old);
      if (at === old) assert.equal(snapshot.querySelector('.snapshot-behind').textContent, 'Behind: prices normally refresh each minute');
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
    assert.equal(f.S.timers.length, 1);
  }
});

test('Explore keeps duplicate contracts distinct through row rotation while unique and missing names retain exact accessible identity and quotes', async () => {
  const contract = (t, ti, su, overrides = {}) => Object.freeze({t, ti, su, s: 'KXBTC15M', bid: .51, ask: .53, last: .5, v24: 1200, oi: 4, ...overrides});
  // Two contracts with one title and one condition differ by when they close (`ct`), which the row and its
  // accessible name both say; never by the raw ticker.
  const a = contract('BTC-26OCT191200', ' Bitcoin price ', ' Above $100,000 ', {ct: '2026-10-19T16:00:00Z'});
  const b = contract('BTC-26OCT191230', 'Bitcoin price', 'Above $100,000', {bid: .67, ask: .69, v24: 8, oi: 2, ct: '2026-10-19T16:30:00Z'});
  const unique = contract('RAIN-26OCT19', 'Rain in Seattle?', 'At least 1 inch', {s: 'KXRAIN', bid: null, ask: null, last: .25, v24: 0, oi: 0});
  const subtitle = contract('SUB-26OCT19', '  ', ' Subtitle only ', {bid: null, ask: null, last: null, v24: 0, oi: 8});
  const fallback = contract('RAW-26OCT19', '', '', {bid: .11, ask: .13, v24: 2, oi: 9});
  const hostile = contract('KX"QUOTE"<ticker>&', ' Price "<img src=x>" & forecast ', ' Above <script>unsafe</script> ', {s: 'KX"QUOTE"<series>&', bid: .61, ask: .63, v24: 12, oi: 5});
  const renamed = Object.freeze({...b, su: 'Below $100,000'});
  const expected = new Map([
    [a.t, ['Bitcoin price', 'Above $100,000', 'Bitcoin price\u00a0· Above $100,000', ['52¢', '1,200', '4'], '&gt; $100,000']],
    [b.t, ['Bitcoin price', 'Above $100,000', 'Bitcoin price\u00a0· Above $100,000', ['68¢', '8', '2'], '&gt; $100,000']],
    [unique.t, ['Rain in Seattle?', 'At least 1 inch', 'Rain in Seattle?\u00a0· At least 1 inch', ['25¢', '0', '0']]],
    [subtitle.t, ['Subtitle only', null, 'Subtitle only', ['—', '0', '8']]],
    [fallback.t, ['Kalshi contract', null, 'Kalshi contract', ['12¢', '2', '9']]],
    [hostile.t, ['Price &quot;&lt;img src=x&gt;&quot; &amp; forecast', 'Above &lt;script&gt;unsafe&lt;/script&gt;',
      'Price &quot;&lt;img src=x&gt;&quot; &amp; forecast\u00a0· Above &lt;script&gt;unsafe&lt;/script&gt;', ['62¢', '12', '5']]],
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
      const [title, sub, label, amounts, display] = m === renamed ? ['Bitcoin price', 'Below $100,000', 'Bitcoin price\u00a0· Below $100,000', ['68¢', '8', '2'], '&lt; $100,000'] : expected.get(m.t);
      const raw = m === hostile ? 'KX&quot;QUOTE&quot;&lt;ticker&gt;&amp;' : m.t;
      assert.equal(link.getAttribute('href'), '/explore?m=' + encodeURIComponent(m.t));
      assert.equal(link.getAttribute('title'), null, 'no raw ticker tooltip');
      const closes = link.querySelector('.market-close');
      assert.equal(link.getAttribute('aria-label'), closes ? `${label}\u00a0· ${closes.textContent}` : label);
      assert.equal(link.querySelector('strong').textContent, display || sub || title);
      if (sub) assert.equal(row.querySelector('.market-contract a'), link);
      else assert.equal(row.querySelector('.market-contract'), null);
      assert.equal(row.querySelector('.market-ref'), null, 'the raw ticker is no line of the row');
      assert.ok(!row.querySelector('td').textContent.includes(raw), 'nor anywhere in its name cell');
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
  assert.equal(postRequests(f).length, 0); assert.equal(f.S.timers.length, 1);
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
  assert.equal(rows[1].querySelector('a.market-name').getAttribute('aria-label'), 'Bitcoin 5pm\u00a0· Above $91,000', 'the source wording, never the raw ticker');
  assert.equal(rows[3].querySelector('.market-event').classList.contains('vh'), false);
  assert.equal(rows[4].querySelector('.market-event').classList.contains('vh'), false);
  assert.equal(rows[5].querySelector('a.market-name strong').textContent, 'Bitcoin 5pm');
  assert.equal(rows[6].querySelector('a.market-name strong').textContent, 'Subtitle only');
  const identityHeaders = f.root.querySelector('.t-explore thead tr').querySelectorAll('th').slice(0, 2);
  assert.deepEqual(identityHeaders.map(th => th.textContent), ['Market / contract', 'Context']);
  assert.ok(identityHeaders.every(th => th.getAttribute('scope') === 'col' && th.getAttribute('rowspan') === '2'));
  const yesGroup = f.root.querySelector('.t-explore th.price-group');
  assert.equal(yesGroup.textContent, 'YES'); assert.equal(yesGroup.getAttribute('scope'), 'colgroup');
  assert.equal(yesGroup.getAttribute('colspan'), '3');
  const unsplit = rows[0].querySelectorAll('td');
  assert.equal(unsplit.length, 8);
  // A phone's stacked row labels its prices as Tau's Explore does ("Yes price"): "YES Price / YES Bid" mixed capitals.
  assert.deepEqual(unsplit.slice(2).map(td => td.getAttribute('data-lab')), ['Yes price', 'Yes bid', 'Yes ask', '24h volume', 'Open interest', null]);
  assert.equal(unsplit[0].querySelector('.market-event').textContent, 'Bitcoin 5pm', 'retain the entire unsplit source title');
  assert.equal(unsplit[0].querySelector('a.market-name').getAttribute('href'), '/explore?m=A-1');
  assert.equal(f.root.querySelectorAll('#xbody .market-ref').length, 0, 'no row prints its raw ticker');
  assert.ok(rows.every((row, i) => !row.querySelector('td').textContent.includes(markets[i].t)));
  assert.doesNotMatch(unsplit[1].textContent, /5pm|expiry/i, 'do not infer a separate context or expiry from unstructured title text');
  assert.equal(rows[5].querySelector('td').getAttribute('colspan'), '2', 'a single identity fallback spans both identity tracks');
  assert.equal(rows[6].querySelector('td').getAttribute('colspan'), '2');
  const contextual = rows[7].querySelectorAll('td'), hostile = rows[8].querySelectorAll('td');
  assert.equal(contextual.length, 8); assert.equal(hostile.length, 8);
  assert.equal(contextual[1].textContent, 'Oct 19, 5pm ET\u00a0· Source context', 'retain every actual context segment without inferring expiry');
  assert.equal(hostile[1].textContent, 'City &lt;script&gt;unsafe&lt;/script&gt; &amp; forecast');
  assert.equal(rows[7].querySelector('.market-event').getAttribute('title'), markets[7].ti);
  assert.equal(rows[7].querySelector('a.market-name').getAttribute('aria-label'), markets[7].ti + '\u00a0· ' + markets[7].su);
  assert.deepEqual(rows.slice(7).map(row => ['.yes-price', '.quote-bid', '.quote-ask', '.market-volume', '.market-interest'].map(selector => row.querySelector(selector).textContent)),
    [['41¢', '40¢', '42¢', '8', '2'], ['41¢', '40¢', '42¢', '8', '2']]);
  assert.doesNotMatch(f.root.querySelector('#xbody').innerHTML, /<script>|<unsafe>/);
  assert.equal(JSON.stringify(markets), before); assert.equal(postRequests(f).length, 0);
});

// Walk 2026-10-30 at 1280px and 390px: a closed 15-minute window's row read "Yes bid 0¢ · Yes ask 0¢", a Yes on offer
// for nothing, beside a market page that says "no bid / ask 5¢" for the same book. A side Kalshi sends as 0 (nobody quotes
// it) reads "—" and says which side is empty; and a search that matches nothing says what to do next, as Tau's does.
test('Explore shows a side nobody quotes as empty, not 0¢, and a search that misses says how to widen it', async () => {
  const markets = Object.freeze([
    Object.freeze({t: 'KXBTC15M-26OCT300345-45', s: 'KXBTC15M', ti: 'BTC price up in next 15 mins?', su: 'Target Price: $109,101.00', bid: 0, ask: 0, last: .99, v24: 90321, oi: 0}),
    Object.freeze({t: 'KXETH15M-26OCT300430-30', s: 'KXETH15M', ti: 'ETH price up in next 15 mins?', su: 'Target Price: $3,812.10', bid: '0.0000', ask: '0.0500', last: 0, v24: 0, oi: 0}),
    Object.freeze({t: 'A-1', s: 'X', ti: 'Weather', su: 'At least 1 inch', bid: .4, ask: .42, last: .4, v24: 8, oi: 2}),
  ]);
  const f = frontend({fetchImpl: () => response({at: new Date().toISOString(), markets, total: 3, shown: 3, matched: 3, per: 40})});
  await f.viewExplore();
  const rows = f.root.querySelectorAll('#xbody tbody tr');
  assert.deepEqual(rows.map(row => row.querySelectorAll('.quote-side').map(n => n.textContent)),
    [['—No bid', '—No ask'], ['—No bid', '5¢'], ['40¢', '42¢']]);
  assert.deepEqual(rows.map(row => row.querySelector('.yes-price').textContent), ['99¢', '—', '41¢'], 'the price is the midpoint only when both sides are quoted, else the last trade');
  assert.equal(rows[0].querySelector('.quote-bid > span').getAttribute('title'), 'No bid');
  assert.equal(rows[0].querySelector('.quote-ask > span').getAttribute('title'), 'No ask');
  assert.doesNotMatch(f.root.querySelector('#xbody').textContent, /(^|[^\d.])0¢/, 'no side reads as a 0¢ quote');
  const searched = frontend({search: '?q=zzz', fetchImpl: () => response({total: 3, shown: 3, matched: 0, per: 40, page: 0, markets: []})});
  await searched.viewExplore();
  assert.equal(searched.root.querySelector('#xbody .empty h2').textContent, 'No markets match “zzz”');
  assert.equal(searched.root.querySelector('#xbody .empty p').textContent, 'Try a broader search, or clear it to see the hottest markets.');
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
    assert.equal(link.getAttribute('aria-label'), `Bitcoin\u00a0· ${conditions[index]}`);
    assert.equal(link.getAttribute('title'), null);
    assert.equal(link.getAttribute('href'), `/explore?m=CONTRACT-${index}`);
  });
  const requests = f.requests.length;
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  f.S.hot = Object.freeze({at: new Date().toISOString(), markets}); f.renderHotRail();
  const quotes = f.root.querySelectorAll('.hot-row');
  assert.deepEqual(quotes.map(row => row.querySelector('.hot-title > span').textContent), displays);
  quotes.forEach((row, index) => {
    assert.equal(row.querySelector('.hot-title').getAttribute('title'), `Bitcoin\u00a0· ${conditions[index]}`);
    assert.ok(row.getAttribute('aria-label').startsWith(`Bitcoin\u00a0· ${conditions[index]}\u00a0· 51¢`));
  });
  assert.equal(f.requests.length, requests, 'formatting source conditions performs no lookup');
  assert.equal(JSON.stringify(markets), before); assert.equal(postRequests(f).length, 0);
});

test('Explore says when a timed contract closes, and nothing for an event with no hour', async () => {
  const markets = [{t: 'KXBTC15M-26OCT262345-45', s: 'KXBTC15M', ti: 'BTC price up in next 15 mins?', su: 'Target Price: $113,204.11', bid: .48, ask: .51, v24: 9, oi: 1, ct: new Date(Date.now() + 5 * 3600e3).toISOString()},
    {t: 'KXNBAGAME-26OCT26MINDEN-MIN', s: 'KXNBAGAME', ti: 'Minnesota at Denver Winner?', su: 'Minnesota', bid: .41, ask: .42, v24: 8, oi: 1, ct: null}];
  const f = frontend({fetchImpl: () => response({at: new Date().toISOString(), markets, total: 2, shown: 2, matched: 2, per: 40})});
  await f.viewExplore();
  const links = f.root.querySelectorAll('a.market-name');
  assert.match(links[0].querySelector('.market-close').textContent, /^Closes .*\d/);
  assert.equal(links[1].querySelector('.market-close'), null);
});

test('Hot Markets names a 5pm Bitcoin contract by its market, an hourly one by the same words at its own hour', () => {
  const f = frontend();
  f.S.me.markets = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET', close_hour_et: 17}];
  const row = (t, ti) => ({t, s: 'KXBTCD', ti, su: '$113,000 or above', bid: .5, ask: .52, v24: 10, oi: 0});
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  f.S.hot = {at: new Date().toISOString(), markets: [row('KXBTCD-26OCT2717-T112999.99', 'Bitcoin price at 5pm EDT?'), row('KXBTCD-26OCT2700-T112999.99', 'Bitcoin price at 12am EDT?')]};
  f.renderHotRail();
  assert.deepEqual(f.root.querySelectorAll('.hot-row').map(r => r.querySelector('.hot-title strong').textContent), ['BTC above set price at 5pm ET', 'BTC above set price at midnight ET']);
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
    [['51¢', '53¢'], ['—No bid', '2¢'], ['—', '54¢'], ['—', '—'], ['—', '—'], ['—', '—'], ['—No bid', '2¢']],
    'a side at zero is a side nobody quotes (Kalshi has no 0¢ price), told apart from a missing one');
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
  assert.equal(f.root.querySelector('[data-sort="last"]').getAttribute('aria-label'), 'Sort by price');
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
  assert.equal(postRequests(f).length, 0); assert.equal(f.S.timers.length, 1);
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
  f.S.gen++; f.root.innerHTML = '<div id="main">Another route</div>';
  departed.resolve(response(payload('Old route result', 30))); await flush();
  assert.equal(f.root.querySelector('#main').textContent, 'Another route'); assert.deepEqual([body.writes, figures.writes], writes);
  assert.equal(reads, 4); assert.equal(postRequests(f).length, 0);

  const initial = deferred(), g = frontend({fetchImpl: path => { assert.equal(path, '/api/explore?q=&sort=v24&page=0'); return initial.promise; }});
  const opening = g.viewExplore(), initialBody = g.root.querySelector('#xbody'), initialFigures = g.root.querySelector('#xfigs');
  const initialWrites = [initialBody.writes, initialFigures.writes];
  g.S.gen++; g.root.innerHTML = '<div id="main">New route before first result</div>';
  // A read for a page the user has left never settles (api drops it), so wait for the event loop, not the view.
  initial.resolve(response(payload('Late first result'))); await flush(); await flush();
  assert.equal(g.root.querySelector('#main').textContent, 'New route before first result');
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
    [new Date(Date.now() - 30000).toISOString(), false, /^Updated just now$/],
    [new Date(Date.now() - 240000).toISOString(), true, /^Behind\u00a0· updated 4m ago$/],
    [undefined, true, /^Update time unavailable$/],
    ['not-a-timestamp', true, /^Update time unavailable$/],
    [new Date(Date.now() - 30000).toISOString(), false, /^Updated just now$/],
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
    assert.equal(rail.querySelector('.hot-vol').textContent, '1.2k\u00a0· 24h');
    assert.equal(rail.querySelector('.hot-vol').getAttribute('title'), '24-hour volume');
    // The row opens Tau's own market page, as Explore's rows do, not Kalshi in a new tab.
    assert.equal(rail.querySelector('.hot-row').getAttribute('href'), '/explore?m=KXBTC15M-26OCT181230-00');
    assert.equal(f.S.hot, snapshot); assert.equal(JSON.stringify(snapshot), before);
  }
  assert.equal(f.S.hotAt, cachedAt); assert.equal(f.S.ap, autopilot);
  assert.deepEqual([...storage], [['tau_hotrail', '1']]);
  assert.deepEqual(f.requests, []); assert.deepEqual(f.navigations, []);
  assert.equal(f.intervals.size, 0); assert.equal(f.timeouts.size, 0);
});

test('Hot Markets keeps a 15-minute window’s "Target Price:" with its amount, on a row of its own', () => {
  // Walk 2026-10-27 at 1280px: the condition sat in the ~80px name column beside the volume, cut to "Target Price:…".
  const f = frontend({storage: new Map([['tau_hotrail', '1']])});
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  f.S.me.markets = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin'}];
  f.S.hot = {at: new Date().toISOString(), markets: [
    {t: 'KXBTC15M-26OCT271830-30', s: 'KXBTC15M', ti: 'Bitcoin price up or down in next 15 mins?', su: 'Target Price: $113,512.08', bid: .54, ask: .56, v24: 10, h: [.4, .5]},
    {t: 'KXBTCD-26OCT2717-T112999.99', s: 'KXBTCD', ti: 'Bitcoin price at 5pm EDT?', su: '$113,000 or above', bid: .5, ask: .52, v24: 10, h: [.4, .5]}]};
  f.renderHotRail();
  const rows = f.root.querySelectorAll('.hot-row');
  assert.match(rows[0].innerHTML, /<span class="hot-cond-wide"><span class="nobr">Target Price: \$113,512\.08<\/span><\/span>/);
  assert.match(rows[1].innerHTML, /<span>≥ \$113,000<\/span>/);  // a strike keeps its place beside the volume
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  const wide = (css.match(/\n\.hot-title > span\.hot-cond-wide \{([^}]*)\}/) || [])[1] || '';
  for (const want of [/grid-column: 1 \/ -1;/, /white-space: normal;/, /overflow: visible;/]) assert.match(wide, want);
  assert.match(css, /\n\.hot-row:has\(\.hot-cond-wide\) \.hot-when \{ grid-row: 4; \}/);
  f.clearTimers();
});

test('Hot Markets keeps a range bucket’s top with its floor, on a row of its own', () => {
  // Walk 2026-10-30 at 1280px: a KXBTC bucket's "$113,000 to 113,499.99" sat in the ~80px name column, cut to
  // "$113,000 to 1…", so the rail's buckets of one ladder ("BTC range at 5pm ET") lost the edge that sets them apart.
  const f = frontend({storage: new Map([['tau_hotrail', '1']])});
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  f.S.hot = {at: new Date().toISOString(), markets: [
    {t: 'KXBTC-26OCT3017-B113250', s: 'KXBTC', ti: 'Bitcoin price range on Oct 30, 2026?', su: '$113,000 to 113,499.99', bid: .21, ask: .24, v24: 10, h: [.2, .22]},
    {t: 'KXBTC-26OCT3017-B112750', s: 'KXBTC', ti: 'Bitcoin price range on Oct 30, 2026?', su: '$112,500 to $112,999.99', bid: .18, ask: .2, v24: 10, h: [.2, .19]},
    {t: 'KXBTCD-26OCT3017-T112999.99', s: 'KXBTCD', ti: 'Bitcoin price at 5pm EDT?', su: '$113,000 or above', bid: .5, ask: .52, v24: 10, h: [.4, .5]},
    {t: 'KXHIGHNY-26OCT31-B58.5', s: 'KXHIGHNY', ti: 'Highest temperature in NYC tomorrow?', su: '58° to 59°', bid: .2, ask: .25, v24: 10, h: [.2, .25]}]};
  f.renderHotRail();
  const rows = f.root.querySelectorAll('.hot-row');
  assert.match(rows[0].innerHTML, /<span class="hot-cond-wide">\$113,000 to 113,499\.99<\/span>/);
  assert.match(rows[1].innerHTML, /<span class="hot-cond-wide">\$112,500 to \$112,999\.99<\/span>/);
  assert.match(rows[2].innerHTML, /<span>≥ \$113,000<\/span>/);  // a strike keeps its place beside the volume
  assert.match(rows[3].innerHTML, /<span>58° to 59°<\/span>/);  // a short non-price range does too
  f.clearTimers();
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
    assert.equal(rows[index].querySelector('.hot-title strong').textContent, 'BTC 15-min up/down');
    assert.ok(rows[index].innerHTML.includes('>BTC 15-min up/down<') && !rows[index].innerHTML.includes('>KXBTC15M<'), 'no raw series chip, not even for screen readers');
    assert.ok(labels[index].includes(markets[index].ti)); assert.ok(!labels[index].includes(markets[index].t), 'the raw ticker is not read out as its name');
    assert.ok(labels[index].includes('BTC 15-min up/down'));
    assert.match(labels[index], /At least \$105,000.*52¢.*\+4¢ across available history.*1\.2k volume over 24 hours/);
    // It opens Tau's market page in place, so it no longer says it opens Kalshi in a new tab.
    assert.doesNotMatch(labels[index] + rows[index].textContent, /Opens Kalshi/);
    assert.equal(rows[index].getAttribute('target'), null); assert.equal(rows[index].getAttribute('href'), '/explore?m=' + encodeURIComponent(markets[index].t));
  }
  assert.match(labels[2], /Price &quot;preview&quot; &lt;img/);
  assert.doesNotMatch(labels[2], /KXBTC15M-/);
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

// A tag the markdown built holds no markup of its own and balanced quotes: a link inside another link's address,
// or a mention's quoted class inside one, closed that href early and the rest of a post became attributes.
const builtTagsSound = (html) => (html.match(/<[^>]*>/g) || []).every((tag) => !tag.slice(1).includes('<') && (tag.split('"').length - 1) % 2 === 0);

test('a post or reply can’t turn its words into attributes through a link: the markdown never links inside a tag', async () => {
  const hostile = '[x](https://a(https://b/onmouseover=onerror=alert;throw-1+) see https://x.com/@bob/p and @ana';
  const post = {id: 11, body: hostile, author: '"><svg onload=alert(1)>', username: 'eve', created_at: '2026-10-17T10:00:00Z', mine: false, comments: 1, reactions: []};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/strategies') return response({strategies: []});
    if (path === '/api/community') return response({posts: [post]});
    if (path === '/api/community/11/comments') return response({comments: [{body: hostile, author: 'Ana', username: 'ana', created_at: '2026-10-17T10:00:00Z'}]});
    throw new Error('unexpected ' + path);
  }});
  await f.viewCommunity(); await flush();
  const feed = f.root.querySelector('#feed'), body = feed.querySelector('.post-body').innerHTML;
  assert.equal(body, '<a href="https://a(https://b/onmouseover=onerror=alert;throw-1+" target="_blank" rel="noopener nofollow">x</a>'
    + ' see <a href="https://x.com/@bob/p" target="_blank" rel="noopener nofollow">https://x.com/@bob/p</a> and <span class="mention">@ana</span>');
  assert.ok(builtTagsSound(feed.innerHTML)); assert.doesNotMatch(feed.innerHTML, /<svg onload/); assert.match(feed.innerHTML, /&quot;&gt;&lt;svg onload=alert\(1\)&gt;/);
  const thread = feed.querySelector('[data-act="comments"]');
  await feed.listeners.get('click')({target: thread}); await flush();
  const reply = feed.querySelector('.cmt-list').innerHTML;
  assert.ok(builtTagsSound(reply)); assert.match(reply, /<a href="https:\/\/a\(https:\/\/b\/onmouseover=onerror=alert;throw-1\+" target/);
  // The research feed and the chat draw the same marks (feedMd), and keep what they always linked.
  const fed = f.feedMd(hostile + '\n**bold**@carl `@code` (https://e.com/p) [ https://c](https://d)');
  assert.ok(builtTagsSound(fed));
  assert.match(fed, /<b>bold<\/b><span class="mention">@carl<\/span> <code><span class="mention">@code<\/span><\/code> \(<a href="https:\/\/e.com\/p"/);
  assert.match(fed, /<a href="https:\/\/d" target="_blank" rel="noopener nofollow"> https:\/\/c<\/a>/);
});


const billingData = (overrides = {}) => ({balance: 10, spent: 2, free_bonus: 3, ledger: [], cards: [], configured: false,
  topup_fee_pct: 5, autoreload_amount: 20, autoreload_threshold: 5, min_reload_amount: 5, min_reload_threshold: 1,
  min_topup: 5, max_topup: 1000, publishable_key: 'synthetic-only', ...overrides});
const systemData = () => ({nodes: {}, events: [], now: '2026-10-20T16:00:00Z'});
function leaveView(f, html = '<div id="main">Next page</div>') {
  f.S.gen++; f.clearTimers(); f.root.innerHTML = html;
  return {rootWrites: f.root.writes, main: f.root.querySelector('#main')};
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
      const f = frontend({fetchImpl: request => { assert.equal(request.split('?')[0], expected); return pending.promise; }});
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
  const f = frontend({fetchImpl: path => { assert.match(path, /^\/api\/billing(\?|$)/); return response(data); }});
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

// What only one theme's Admin draws stays its own in the shared file (page-admin.js): Meridian's waitlist, and none of
// Tau's lines under the titles or its DB box's largest tables (test_frontend_merge.mjs).
test('Meridian: Admin has the waitlist and no title line, and the System map no table breakdown', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/admin') return response({users: [], waitlist: [{email: 'waiting@example.invalid', note: '', created_at: '2026-10-25T10:00:00Z', status: 'requested'}]});
    if (path === '/api/admin/kill-switch') return response({on: false, reason: '', by: '', env_on: false});
    if (path === '/api/admin/system') return response({...systemData(), nodes: {db: {size_mb: 2048, rows: 5000, top_tables: [{table: 'markets', mb: 12}]}}});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.is_admin = true;
  await f.viewAdmin(); await flush();
  assert.match(f.root.querySelector('#waitlist').innerHTML, /waiting@example\.invalid/);
  assert.doesNotMatch(f.root.innerHTML, /class="deck"|Operator tools/);
  await f.viewSystem(); await flush();
  assert.doesNotMatch(f.root.innerHTML, /class="deck"|A live map/);
  assert.equal(f.root.querySelector('#sys-detail').innerHTML, '<h2>Select a component</h2>');
  f.root.querySelector('.sys-node[data-id="db"]').dispatchEvent({type: 'click'});
  assert.doesNotMatch(f.root.querySelector('#sys-detail').innerHTML, /sys-tables|Largest tables|markets/);
  f.clearTimers();
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

// The live activity feed shows a verdict as the run page's plain note (server gate_explain.event_note)
// after its title, else its own message minus the status word; everything escaped.
const SYS_EVENTS = [
  {kind: 'verdict', message: 'FAILED - Fade <b>: validation verdict is gatekeeper-held (classification=inconclusive, 9 trades)',
    created_at: '2026-10-20T15:59:00Z', data: {note: 'Did not pass on data it never saw (9 trades).', title: 'Fade <b>'}},
  {kind: 'verdict', message: 'Model tiering: X proposed and screened.', created_at: '2026-10-20T15:58:00Z',
    data: {note: 'A quicker model screened the ideas first: 1 set aside, 2 passed on to be developed.', title: null}},
  {kind: 'verdict', message: 'PASSED - Lean in: cleared every gate', created_at: '2026-10-20T15:57:00Z'},
  {kind: 'step', message: 'Froze 2 finalists', created_at: '2026-10-20T15:56:00Z'},
];
const sysFeedText = html => [...String(html).matchAll(/<\/time><span>([^<]*)<\/span>/g)].map(m => m[1]);

test('System: the live activity feed reads a verdict as its plain note, else its message', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/admin/system'); return response({...systemData(), events: SYS_EVENTS}); }});
  await f.viewSystem(); await flush();
  const html = f.root.querySelector('#sys-feed').innerHTML;
  assert.deepEqual(sysFeedText(html), [
    'Fade &lt;b&gt;: Did not pass on data it never saw (9 trades).',
    'A quicker model screened the ideas first: 1 set aside, 2 passed on to be developed.',
    'Lean in: cleared every gate',
    'Froze 2 finalists',
  ]);
  assert.doesNotMatch(html, /gatekeeper-held|classification=|Model tiering|<b>/);
  f.clearTimers();
});

// Walk 2026-10-27: the System page's research box read "12 running · 30 queued · 1,204 done" on one line, which ran
// out of its 158-wide box (171 wide at 390px and 1280px; the map scales as one, so the box and its text keep their
// proportion at every width). As on Tau, the count is two lines in a box tall enough for them, every figure grouped.
test('System: the research box sets its count on two lines that fit the box, with big numbers grouped', async () => {
  const nodes = {agents: {running: 12, queued: 30, done: 1204}, backtest: {strategies: 3}, db: {rows: 10, size_mb: 5}, web: {users: 2}};
  const f = frontend({fetchImpl: path => (path === '/api/admin/system' ? response({nodes, events: [], now: '2026-10-27T16:00:00Z'}) : response({}))});
  await f.viewSystem(); await flush();
  const g = f.root.querySelector('.sys-node[data-id="agents"]'), m = g.querySelector('[data-m="agents"]');
  const spans = m.querySelectorAll('tspan');
  assert.deepEqual(spans.map(t => t.textContent), ['12 running · 30 queued', '1,204 done']);
  const w = +g.querySelector('rect').getAttribute('width'), h = +g.querySelector('rect').getAttribute('height');
  // About 5 units a character at the map's 10.5px narrow face: each line keeps clear of the box's right edge.
  for (const t of spans) assert.ok(12 + t.textContent.length * 5 <= w - 8, `"${t.textContent}" in a ${w}-wide box`);
  // Both lines sit under the name and its sub-line (y 41) and above the box's foot.
  const ys = spans.map(t => +t.getAttribute('y'));
  assert.ok(ys[0] >= 41 + 13 && ys[1] >= ys[0] + 12 && ys[1] <= h - 10, `lines at ${ys} in a ${h}-tall box`);
  // The box below it still clears the taller box, and the edges leave from its middle.
  assert.ok(40 + h < 160 - 20);
  const edge = f.root.querySelectorAll('.sys-edge').find(p => p.dataset.e === 'agents');
  assert.match(edge.getAttribute('d'), new RegExp(`^M878,${40 + h / 2} `));
  // The detail panel reads the count as one line.
  g.dispatchEvent({type: 'click'});
  assert.match(f.root.querySelector('#sys-detail').innerHTML, /12 running · 30 queued · 1,204 done/);
  f.clearTimers();
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
  const text = id => visible(evidenceFor(f.root.querySelector('#dash-deps'), id).textContent);
  // $12 over 6 unseen trades = $2 a trade, so 5 closed trades -> +$10.00.
  assert.ok(text(1).includes('Backtest estimate +$10.00 for the same 5 trades\u00a0· Later-period P&amp;L +$12.00'), text(1));
  assert.ok(!text(2).includes('Backtest estimate')); assert.ok(!text(3).includes('Backtest estimate'));
});

test('Buying credits says how long the amount lasts at the user\'s own pace', async () => {
  const stripe = stripeFixture();
  let data = billingData({configured: true, spent_7d: 7, runway_days: 10});
  const f = frontend({stripeLoader: async () => stripe.Stripe, fetchImpl: path => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response(data);
    return response({client_secret: 'synthetic-secret'});
  }});
  await f.viewBilling(); await flush();
  const note = () => f.root.querySelector('#topup-note').textContent;
  // $20 at $7 a week ($1 a day) -> about 20 days.
  assert.match(note(), /You’ll pay \$21\.00 \(\$20\.00 credits \+ 5% fee\)\. At your pace \(\$7\.00 a week\) that’s about 20 days of research\./);
  const amt = f.root.querySelector('#topup-amt'); amt.value = '200'; amt.oninput();
  assert.match(note(), /over 3 months of research/);
  data = billingData({configured: true, spent_7d: 0});
  await f.viewBilling(); await flush();
  assert.match(note(), /5% fee\)\.$/); assert.doesNotMatch(note(), /At your pace/);
});

test('Billing does not create a setup intent when Stripe loading completes after departure', async () => {
  const pending = deferred(), stripe = stripeFixture();
  const f = frontend({stripeLoader: () => pending.promise, fetchImpl: path => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response(billingData({configured: true}));
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
    if (/^\/api\/billing(\?|$)/.test(path)) return response(billingData({configured: true}));
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
      if (/^\/api\/billing(\?|$)/.test(path)) { reads++; return response(billingData({configured: true})); }
      if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic-secret'});
      assert.equal(path, '/api/billing/card-added'); return stage === 'card-added' ? pending.promise : response({ok: true});
    }});
    await f.viewBilling();
    const save = f.root.querySelector('#save-card'), saving = save.onclick({currentTarget: save});
    await flush();
    const next = leaveView(f, '<div id="main"><div id="card-flash">Fresh card panel</div></div>');
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
      if (path.split('?')[0] === initialPath) { reads++; return response(label === 'Billing topup'
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
    const next = leaveView(f, `<div id="main"><div id="${host}">Fresh action panel</div></div>`);
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

test('theme preference save failure stays on this theme without a reload or financial writes', async () => {
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/ui-theme'); return response({error: 'Synthetic unavailable preference service'}, 503); }});
  await f.viewSettings(); f.root.querySelector('[data-theme="tau"]').onclick(); await flush();
  assert.equal(f.storage.get('tau_ui'), undefined); assert.deepEqual(f.reloads, []);
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
    const dataset = {coreJs: '/static/core.js?v=core-js', tauJs: '/static/app.js?v=tau-js', tauVer: 'tau-js', merJs: '/static/app.meridian.js?v=mer-js', merVer: 'mer-js', merCss: '/static/app.meridian.css?v=mer-css'};
    const context = {window: {}, localStorage: {getItem: () => { if (blocked) throw new Error('Synthetic blocked storage'); return stored; }},
      document: {getElementById: id => id === 'tau-boot' ? {dataset} : id === 'tau-css' ? css : null,
        createElement: tag => { assert.equal(tag, 'script'); return {}; }, body: {appendChild: script => scripts.push(script)}}};
    vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
    // The shared core, then the theme's bundle, in that order (async off: added scripts run in the order added).
    assert.equal(context.window.__TAU_UI__, expected); assert.equal(scripts.length, 2);
    assert.deepEqual(scripts.map((x) => x.src), [dataset.coreJs, expected === 'meridian' ? dataset.merJs : dataset.tauJs]);
    assert.ok(scripts.every((x) => x.async === false));
    assert.equal(context.window.__BUILD__, expected === 'meridian' ? dataset.merVer : dataset.tauVer);
    assert.equal(css.href, expected === 'meridian' ? dataset.merCss : '/static/app.css?v=tau-css');
  });
}

// Boot fetch budget: the signed-in shell carries /api/me's reply, so the first page's reads go out at once.
test('Meridian boots on the account the signed-in shell carries, with no /api/me read', async () => {
  const carried = {user: {id: 7, name: 'Carried', ui_theme: 'meridian'}, markets: [], directions: []};
  const storage = new Map([['tau_ui', 'meridian']]);
  const f = frontend({storage, win: {__TAU_ME__: carried}, fetchImpl: path => response(path === '/api/me' ? carried : {})});
  f.S.me = null;
  await f.render(); await flush(); await flush();
  assert.equal(f.S.me, carried); assert.deepEqual(f.reloads, []);
  const paths = f.requests.map(({path}) => path.split('?')[0]);
  assert.ok(!paths.includes('/api/me') && !paths.includes('/api/version'), paths.join(' '));
  assert.ok(paths.includes('/api/strategies/42'), 'the page read went out');
  // Taken once: a later boot (signed out, then back) asks the server.
  assert.equal(f.window.__TAU_ME__, null);
  f.S.me = null; f.requests.length = 0;
  await f.render(); await flush();
  assert.equal(f.requests[0].path, '/api/me');
});

test('Meridian Research takes its model list from the account instead of waiting on /api/models', async () => {
  const f = researchFrontend([]);
  f.S.me.models = {models: [{key: 'm1', label: 'Model one'}, {key: 'm2', label: 'Model two'}], default: 'm2'};
  await f.viewResearch(); await flush();
  assert.ok(!f.requests.some(({path}) => path === '/api/models'));
  assert.match(f.root.innerHTML, /<option value="m2" selected>Model two/);
  f.clearTimers();
});

test('boot.js hands the app the account a signed-in shell carries, once, and survives a broken block', () => {
  for (const [text, expected] of [['{"user":{"id":7},"n":"\\u003c/script\\u003e"}', {user: {id: 7}, n: '</script>'}], ['{not json', undefined]]) {
    const node = {textContent: text, removed: false, remove() { this.removed = true; }};
    const dataset = {ui: 'meridian', tauJs: '/static/app.js?v=t', tauVer: 't', merJs: '/static/app.meridian.js?v=m', merVer: 'm', merCss: '/static/app.meridian.css?v=m'};
    const context = {window: {}, location: {pathname: '/'}, localStorage: {getItem: () => null, setItem() {}},
      document: {getElementById: id => id === 'tau-me' ? node : id === 'tau-boot' ? {dataset} : null,
        createElement: () => ({}), body: {appendChild() {}}}};
    vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
    assert.deepEqual(context.window.__TAU_ME__ === undefined ? undefined : JSON.parse(JSON.stringify(context.window.__TAU_ME__)), expected);
    assert.equal(node.removed, expected !== undefined);
    assert.equal(context.window.__TAU_UI__, 'meridian');  // the theme choice runs either way
  }
});

test("boot.js hands the app the page's first read the shell carries, once, apart from the account", () => {
  for (const [text, expected] of [['[{"url":"/api/deployments","body":{"v":"x","t":"\\u003c/script\\u003e"}}]', [{url: '/api/deployments', body: {v: 'x', t: '</script>'}}]], ['{not json', undefined]]) {
    const me = {textContent: '{"user":{"id":7}}', remove() { this.removed = true; }};
    const node = {textContent: text, removed: false, remove() { this.removed = true; }};
    const dataset = {ui: 'tau', tauJs: '/static/app.js?v=t', tauVer: 't', merJs: '/static/app.meridian.js?v=m', merVer: 'm', merCss: '/static/app.meridian.css?v=m'};
    const context = {window: {}, location: {pathname: '/deploy'}, localStorage: {getItem: () => null, setItem() {}},
      document: {getElementById: id => id === 'tau-first' ? node : id === 'tau-me' ? me : id === 'tau-boot' ? {dataset} : null,
        createElement: () => ({}), body: {appendChild() {}}}};
    vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
    assert.deepEqual(context.window.__TAU_FIRST__ === undefined ? undefined : JSON.parse(JSON.stringify(context.window.__TAU_FIRST__)), expected);
    assert.equal(node.removed, expected !== undefined);
    assert.deepEqual(JSON.parse(JSON.stringify(context.window.__TAU_ME__)), {user: {id: 7}}, 'a broken first read leaves the account');
  }
});

test("boot.js starts the reads a carried read names next, once each, and only the app's own", () => {
  const text = JSON.stringify([{url: '/api/funds', body: {}, then: ['/api/funds/cash?book=live', '/api/funds/cash?book=demo', 'https://elsewhere.example/x', 7]},
    {url: '/api/autopilot/status', body: {}}]);
  const node = {textContent: text, remove() {}};
  const dataset = {ui: 'tau', tauJs: '/static/app.js?v=t', tauVer: 't', merJs: '/static/app.meridian.js?v=m', merVer: 'm', merCss: '/static/app.meridian.css?v=m'};
  const asked = [];
  const context = {window: {}, location: {pathname: '/funds'}, localStorage: {getItem: () => null, setItem() {}},
    fetch: (url, opts) => { asked.push([url, opts.credentials]); return Promise.resolve({url}); },
    document: {getElementById: id => id === 'tau-first' ? node : id === 'tau-boot' ? {dataset} : null, createElement: () => ({}), body: {appendChild() {}}}};
  vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
  assert.deepEqual(asked, [['/api/funds/cash?book=live', 'same-origin'], ['/api/funds/cash?book=demo', 'same-origin']]);
  assert.deepEqual(Object.keys(context.window.__TAU_EARLY__), ['/api/funds/cash?book=live', '/api/funds/cash?book=demo']);
  // No fetch (an old browser) or no "then": nothing starts, and boot goes on.
  delete context.fetch; context.window = {};
  vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
  assert.equal(context.window.__TAU_EARLY__, undefined);
  assert.equal(context.window.__TAU_UI__, 'tau');
});

test("boot.js keeps the browser's UTC offset in the tau_tz cookie, the one Billing's read names, and survives blocked cookies", () => {
  for (const [protocol, blocked] of [['https:', false], ['http:', false], ['https:', true]]) {
    const written = [], dataset = {ui: 'tau', tauJs: '/static/app.js?v=t', tauVer: 't', merJs: '/static/app.meridian.js?v=m', merVer: 'm', merCss: '/static/app.meridian.css?v=m'};
    const document = {getElementById: id => id === 'tau-boot' ? {dataset} : null, createElement: () => ({}), body: {appendChild() {}}};
    Object.defineProperty(document, 'cookie', {set: (v) => { if (blocked) throw new Error('Synthetic blocked cookies'); written.push(v); }});
    const context = {window: {}, location: {pathname: '/', protocol}, localStorage: {getItem: () => null, setItem() {}}, document};
    vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
    const tz = vm.runInNewContext('new Date().getTimezoneOffset()');
    // The same digits as the page's '/api/billing?tz=' + new Date().getTimezoneOffset() (shell_reads.billing_tz reads them).
    assert.deepEqual(written, blocked ? [] : [`tau_tz=${tz}; Path=/; Max-Age=34560000; SameSite=Lax${protocol === 'https:' ? '; Secure' : ''}`]);
    assert.equal(context.window.__TAU_UI__, 'tau', 'the theme choice runs either way');
  }
});

test('a research session that does not exist links to the list instead of offering Try again', async () => {
  const f = frontend({fetchImpl: path => (path.startsWith('/api/runs/9') ? {ok: false, status: 404, json: async () => ({error: 'No such research session.'})} : {ok: true, status: 200, json: async () => ({})})});
  f.location.pathname = '/research/9';
  await f.render(); await flush();
  const html = f.root.innerHTML;
  assert.match(html, /No such research session\./); assert.match(html, /href="\/research">All research sessions</);
  assert.doesNotMatch(html, /data-retry/);
});

test('the legal pages load in Tau even for a Meridian user, since only Tau has them', () => {
  for (const [pathname, expected] of [['/terms', 'tau'], ['/privacy', 'tau'], ['/settings', 'meridian']]) {
    const scripts = [], css = {href: '/static/app.css?v=tau-css'};
    const dataset = {coreJs: '/static/core.js?v=core-js', tauJs: '/static/app.js?v=tau-js', tauVer: 'tau-js', merJs: '/static/app.meridian.js?v=mer-js', merVer: 'mer-js', merCss: '/static/app.meridian.css?v=mer-css'};
    const context = {window: {}, location: {pathname}, localStorage: {getItem: () => 'meridian'},
      document: {getElementById: id => id === 'tau-boot' ? {dataset} : id === 'tau-css' ? css : null,
        createElement: () => ({}), body: {appendChild: script => scripts.push(script)}}};
    vm.runInNewContext(readFileSync(new URL('../app/static/boot.js', import.meta.url), 'utf8'), context);
    assert.equal(context.window.__TAU_UI__, expected, pathname);
    assert.deepEqual(scripts.map((x) => x.src), [dataset.coreJs, expected === 'meridian' ? dataset.merJs : dataset.tauJs]);
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
  assert.match(paper, /Autopilot runs the strategies that pass every research test on paper, with pretend money/);
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
  assert.match(card, /<dt>Credits spent on research<\/dt><dd>\$0\.50<\/dd>/);
  assert.match(card, /<dt>Autopilot put on paper<\/dt><dd>3 strategies <small>not counting yours<\/small><\/dd>/);
  assert.match(card, /<dt><span class="pnl-win">Last 7 days:<\/span> autopilot’s paper P&amp;L<\/dt><dd><span class="pos">\+\$1\.25<\/span> <small>paper, not real money, after Kalshi fees and the spread\u00a0· 1 closed trade<\/small><\/dd>/);
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
  assert.equal(cost().textContent, 'A session like this usually takes about $0.42 from your credits (your recent sessions).');
  f = researchFrontend([], {estimate: {yours: null, sessions: 2, typical: {offline: 3.1}}}); await f.viewResearch(); await flush();
  assert.match(cost().textContent, /about \$3\.10 \(recent sessions on this model\)/);
  f = researchFrontend([]); await f.viewResearch(); await flush();
  assert.equal(cost().hidden, true); assert.equal(cost().textContent, '');
  // With payments on, a model with no estimate still says how it is billed and that it can be stopped.
  f = researchFrontend([]); f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 12, min_run_balance: 1};
  await f.viewResearch(); await flush();
  assert.equal(cost().hidden, false);
  assert.equal(cost().textContent, 'No cost estimate for this model yet. It runs until you stop it from its session page, using your credits as it goes, and keeps running if you leave this page.');
  // Said once (walk 2026-10-30): the switch's hint under it, "Runs until you stop it, using credits as it goes",
  // steps aside while this line says both; a session with a limit keeps the old line and the hint.
  const hint = () => f.root.querySelector('#rf-hint');
  assert.equal(hint().hidden, true);
  assert.equal((cost().textContent.match(/credits as it/g) || []).length, 1);
  const forever = f.root.querySelector('#runforever'); forever.checked = false; forever.dispatchEvent({type: 'change'});
  assert.equal(cost().textContent, 'No cost estimate for this model yet. It’s charged to your credits as it runs, and you can stop it any time from its session page.');
  assert.equal(hint().hidden, false); assert.match(hint().textContent, /^A session takes a few minutes/);
  forever.checked = true; forever.dispatchEvent({type: 'change'});
  assert.equal(hint().hidden, true);
  assert.doesNotMatch(cost().textContent, /list price/i);
});

test('Research says a low balance before Start, shows a running session’s spend, and lists stopped and paused sessions as such', async () => {
  const running = {...researchRun(5, 'running'), spent_usd: 2.37}, stopped = {...researchRun(4, 'stopped'), strategies_passed: 1, spent_usd: 6.1};
  let f = researchFrontend([running, stopped, researchRun(3, 'paused')]);
  f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, credit_balance: 0.5, min_run_balance: 1};
  await f.viewResearch(); await flush();
  assert.match(f.root.querySelector('#dispatch .notice').textContent, /You have \$0\.50 in credits — a research session needs at least \$1\.00 to start\./);
  const foot = f.root.querySelector('#active-research .active-foot');
  assert.deepEqual(foot.querySelectorAll('dt').map(dt => dt.textContent), ['Tested', 'Passed', 'Spent so far']);
  // It names its credits, as the session rows and page do, and the amount can't split across lines.
  assert.equal(foot.querySelectorAll('dd')[2].textContent, '$2.37 in\u00a0credits');
  assert.equal(foot.querySelectorAll('dd')[2].querySelector('.nobr').textContent, '$2.37');
  // A session that ran until stopped reads like a finished one, not a red "Failed".
  const card = f.root.querySelector('#runs a[href="/research/4"]');
  assert.doesNotMatch(card.innerHTML, /Failed|loss/);
  assert.match(card.querySelector('.run-state').textContent, /1\/4 passed/);
  assert.match(card.getAttribute('class'), /\bvoid\b/);
  assert.equal(f.root.querySelector('#runs a[href="/research/3"] .run-state').textContent, 'Outcome Paused');
  // Enough credits: no notice.
  f = researchFrontend([]); f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, credit_balance: 5, min_run_balance: 1};
  await f.viewResearch(); await flush();
  assert.equal(f.root.querySelector('#dispatch .notice'), null);
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
  // A brand-new user who has never run research (research.researched false) isn't told it's "between research
  // runs": the server's first story line and idle line say no research has run yet, and the card shows them as sent.
  const first = 'Right now no research has run yet. Its first research session starts at its next check-in; it checks in about every 10 minutes.';
  const fresh = {...base, research: {...base.research, researched: false}, story: [first, 'Nothing trades real money until...']};
  f.S.ap = {...fresh, idle: null};
  f.paintDashAp();
  assert.equal(card().innerHTML, first);
  f.S.ap = {...fresh, idle: {code: 'no_strategies', line: 'Nothing is on paper yet: no research has run yet. Its first research session starts at its next check-in.', action: null}};
  f.paintDashAp(); f.root.querySelector('#dash-ap [data-apcard="open"]').onclick(); await flush();
  assert.equal(card().innerHTML, 'Nothing is on paper yet: no research has run yet. Its first research session starts at its next check-in.');
  assert.equal(box.querySelectorAll('#apf-story p').map(p => p.innerHTML)[1], first);
  assert.doesNotMatch(box.querySelector('#apf-story').innerHTML, /between research runs/);
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
for (const [label, view, endpoint, selector] of [['Overview', 'viewDashboard', '/api/dashboard', '#main'], ['Deploy', 'viewDeploy', '/api/deployments', '#deps']]) {
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
    const figures = () => f.root.querySelector('#main').innerHTML;
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
  const tick = [...f.intervals.values()].find(cb => String(cb).includes("getElementById('autopilot-float') && !document.hidden && !apFresh()) tick()"));
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
  assert.match(block, /\.info \{ width: 44px; height: 44px; margin: -15px -15px -15px -10px; \}/);
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
  // Phone: the RSI tag sits under the title; the system map stacks to the column's width (fresh_walk_frontend_cases).
  const phone = css.slice(css.lastIndexOf('@media (max-width: 760px)'));
  assert.match(phone, /\.rsidisc-cap > \.rsi-tag, \.rsidisc-cap > \.rsidisc-delta \{ grid-column: 2;/);
  assert.doesNotMatch(phone, /\.sys-wrap \{ overflow-x: auto;|width: 640px/);
  // Touch: every field, summary, slider and small link that measured under 40px at 360px.
  const touch = css.slice(css.lastIndexOf('@media (pointer: coarse)'));
  const block = touch.slice(0, touch.indexOf('\n}\n'));
  assert.match(block, /\.input, select, input\[type=text\][^{]*\.post-tools select, \.explore-filters \.input \{ min-height: 44px; \}/);
  assert.match(block, /input\[type=range\], \.dial input\[type=range\] \{ height: 44px; \}/);
  assert.match(block, /details > summary \{ padding-block: 13px; min-height: 44px; \}/);
  assert.match(block, /\.wordmark a \{ padding: 3px 5px; margin: -3px -5px; \}/);
  assert.match(block, /\.legal-nav a, \.legal-foot a, \.lfoot-links a, \.linkish \{ padding: 10px 4px; margin: -10px -4px; \}/);
  assert.doesNotMatch(block, /#dep-(paper|demo|live)|\.go\b|strat-quick/);
  // Funds: the perps ticket's buttons, fields and checkboxes were 34px and 16px.
  assert.match(perps, /@media \(pointer: coarse\) \{\n  \.kalshi-perps-live \.btn, \.kp-field input, \.kp-field select, \.kp-reduce, \.kp-check \{ min-height: 44px; \}/);
});

test('Meridian: separators wrap with the item after them, the phone tabs show which edge has more, stacked cells are named', () => {
  const f = frontend();
  // Every " · " in the bundle binds to the next item (" · "), so a wrapped line never ends on a dot.
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
  assert.match(source, /<td class="hint lead-cell" data-lab="When">\$\{ledgerAt\(r\.created_at\)\}<\/td><td class="name" data-lab="What">[^\n]*data-lab="Amount">/);
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

test('Meridian: a finished session ends with the way on: another idea or autopilot after the last failed card, your own idea under the example\'s log', async () => {
  const at = async (run, strategies, autopilot = false) => {
    const f = frontend({fetchImpl: () => response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: '2026-10-25T10:00:00Z', ...run}, events: [], strategies})});
    f.S.me.user.autopilot = autopilot;
    await f.viewRun(9); f.clearTimers();
    return f;
  };
  let f = await at({status: 'succeeded'}, [{id: 43, title: 'Fade', status: 'failed'}, {id: 44, title: 'Lean', status: 'rejected'}]);
  const main = f.root.querySelector('#main').innerHTML;
  assert.ok(main.indexOf('id="run-artifacts"') < main.indexOf('id="runend"') && main.indexOf('id="runend"') < main.indexOf('id="rsibox"'));
  const end = f.root.querySelector('#runend').innerHTML;
  assert.match(end, /<a class="btn" href="\/research\?new=1">Try another idea<\/a><p class="research-ap">Rather not write ideas yourself\? <button type="button" data-research-ap>Turn on autopilot<\/button>/);
  assert.doesNotMatch(end, /btn primary/);
  assert.equal(f.root.querySelector('#runend-log').innerHTML, '');
  assert.doesNotMatch((await at({status: 'succeeded'}, [], true)).root.querySelector('#runend').innerHTML, /Turn on autopilot/);  // already on
  // The example: under its log's last line, inside the Agent log; a plain button beside the primary above.
  f = await at({status: 'succeeded', example: true}, []);
  const hist = f.root.querySelector('#run-history').innerHTML;
  assert.ok(hist.indexOf('id="runfeed"') < hist.indexOf('id="runend-log"'));
  assert.equal(f.root.querySelector('#runend-log').innerHTML, '<p class="run-end"><a class="btn" href="/research?new=1">Describe your own idea</a></p>');
  assert.equal(f.root.querySelector('#runend').innerHTML, '');
  // Something passed, or still going: nothing at the foot.
  assert.equal((await at({status: 'succeeded'}, [{id: 42, title: 'Late', status: 'passed'}])).root.querySelector('#runend').innerHTML, '');
  assert.equal((await at({status: 'running'}, [])).root.querySelector('#runend').innerHTML, '');
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
  const quick = f.root.querySelector('#dep-paper-quick'), html = f.root.querySelector('#main').innerHTML;
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
  // Not validated, or no gatekeeper record behind its "passed": only the panel's own button.
  for (const detail of [detailStrategy({status: 'rejected'}), detailStrategy({experiment: null})]) {
    const g = strategyFrontend(detail, () => response({deployments: [], open_positions: []}));
    await g.viewStrategy(42); await flush();
    assert.equal(g.root.querySelector('#dep-paper-quick'), null); assert.ok(g.root.querySelector('#dep-paper'));
  }
  // Already on paper: only the panel's own button, with its second-copy warning, under the panel's View deployments.
  // Walk 2026-10-30: "It already runs on paper. Deploying it again…" was followed by "It runs on paper. See it on Deploy."
  const on = strategyFrontend(detailStrategy({deployments: [{id: 3, mode: 'paper', status: 'running'}]}), () => response({deployments: [], open_positions: []}));
  await on.viewStrategy(42); await flush();
  assert.equal(on.root.querySelector('#dep-paper-quick'), null); assert.ok(on.root.querySelector('#dep-paper'));
  const onHtml = on.root.querySelector('#main').innerHTML;
  assert.match(onHtml, /class="hint paper-again">It already runs on paper\. Deploying it again starts a second copy/);
  assert.doesNotMatch(onHtml, /on-paper|It runs on paper/);
  assert.equal(onHtml.match(/runs on paper/g).length, 1);
  assert.match(onHtml, /<a class="btn primary" href="\/deploy">View deployments<\/a>/);
});

test('strategy page: out-of-sample figures say their span, deployments go by book not row id, and a second paper copy is flagged', async () => {
  const detail = detailStrategy({out_of_sample: {...metrics(12), days: 15.2}, capital: 100,
    deployments: [{id: 812, mode: 'demo', status: 'running'}, {id: 811, mode: 'paper', status: 'paused'}]});
  const f = strategyFrontend(detail, () => response({deployments: [], open_positions: []}));
  await f.viewStrategy(42); await flush();
  const figs = f.root.querySelector('#figs').innerHTML, html = f.root.querySelector('#main').innerHTML;
  assert.match(figs, /6 trades over 15 days/);
  assert.match(figs, /Later period over 15 days\u00a0· unseen\u00a0data\u00a0· \$100 at risk at most/);
  assert.match(html, /Demo · running<br>Paper · paused/);
  assert.match(html, /Stop deployments \(demo, paper\)/);
  assert.doesNotMatch(html, /#81[12]/);
  assert.match(html, /class="hint paper-again">It already runs on paper\. Deploying it again starts a second copy/);
  // Its paused paper deployment is also found on Deploy, beside the button.
  assert.match(html, /<p class="hint on-paper">Its paper deployment is paused\. <a href="\/deploy">Resume it on Deploy<\/a>\.<\/p>/);
  assert.ok(f.root.querySelector('#dep-paper'));
  // An older result with no window length keeps its figure as it was; not on paper, no warning.
  const g = strategyFrontend(detailStrategy({capital: 100}), () => response({deployments: [], open_positions: []}));
  await g.viewStrategy(42); await flush();
  assert.match(g.root.querySelector('#figs').innerHTML, /<dd class="sub-fig">6 trades the agent never saw<\/dd>/);
  // With no span it still names the slice its return is on.
  assert.match(g.root.querySelector('#figs').innerHTML, /<dd class="sub-fig">Later period\u00a0· unseen\u00a0data\u00a0· \$100 at risk at most<\/dd>/);
  assert.doesNotMatch(g.root.querySelector('#main').innerHTML, /paper-again|on-paper/);
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
    assert.equal(sum(), 'Opus · runs until you stop it · agent’s choice of market');
    model.value = 'haiku';
    form.querySelector('#runforever').checked = false; form.querySelector('#maxhyp').value = '25';
    form.querySelectorAll('input[name=market]').forEach((r) => { r.checked = r.getAttribute('value') === 'btc15m'; });
    form.dispatchEvent({type: 'change'});
    const row = form.querySelector('.mktrow[data-key="btc15m"] .mktrow-name').textContent.trim();
    assert.equal(sum(), 'Haiku · 25 strategies · ' + row); assert.doesNotMatch(row, /choice/);
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
  assert.match(log, /On the history it searched: \+\$4\.50 · 8 trades<button type="button" class="info" data-glo="insample"/);
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
  // Paper says what its figure is net of, as every paper P&L does; demo and live don't.
  assert.match(text, /<span class="nobr"><b>Paper<\/b> <span class="pos">\+\$2\.42<\/span><\/span> on 3 trades, after Kalshi fees and the spread<\/span>/);
  assert.doesNotMatch(text, /<b>Live<\/b>|\$1\.32/);
  assert.match(text, /4 strategies passed: <span class="since-links"><a href="\/strategies\/9">&lt;b&gt;Rain&lt;\/b&gt;<\/a>, <a href="\/strategies\/8">Fade<\/a>, <a href="\/strategies\/7">Tails<\/a>, <a href="\/strategies">1 more<\/a><\/span>/);
  assert.match(text, /3 research sessions started/);
  assert.match(text, /It put 1 on paper, paused 2, made 1 other change\./);
  assert.match(text, /<a href="#dash-paused">Paused one<\/a> is paused<span class="since-sub">: lost \$12\.00<\/span>/);
  assert.match(text, /<a href="\/research">1 research session failed<\/a>/);
  const host = f.root.querySelector('#main').innerHTML;
  assert.ok(host.indexOf('id="dash-since"') >= 0 && host.indexOf('id="dash-since"') < host.indexOf('id="dash-ap"'));
  // A quiet stretch says so plainly; no last visit known yet reads as the last 24 hours.
  const quiet = await strip({deployments: [], since: {at: '2026-10-25T08:00:00+00:00', first: true, books: {paper: {pnl: 0, trades: 0}},
    passed: {n: 0, items: []}, autopilot: {}, runs: {}}});
  const q = quiet.root.querySelector('#dash-since').innerHTML;
  assert.match(q, /Last 24 hours/); assert.doesNotMatch(q, /Since your last visit/);
  for (const said of ['No trades closed.', 'Nothing new passed.', 'On. It made no changes.', 'Nothing.']) assert.ok(q.includes(said), said);
  // A pass a later check left uncleared is named apart, as its page and the lists stamp it, never as passed.
  const fell = await strip({deployments: [], since: {...since, passed: {n: 1, items: [{id: 9, title: 'Rain'}],
    not_cleared: [{id: 8, title: '<b>Fade</b>', verdict: 'missed_final'}, {id: 7, title: 'Tails', verdict: 'held_back'}], not_cleared_n: 3}}});
  const ft = fell.root.querySelector('#dash-since').innerHTML;
  assert.match(ft, /1 strategy passed: <a href="\/strategies\/9">Rain<\/a>/);
  assert.match(ft, /Not cleared to trade: <a href="\/strategies\/8">&lt;b&gt;Fade&lt;\/b&gt;<\/a> \(missed the final test\), <a href="\/strategies\/7">Tails<\/a> \(held back\), 1 more\./);
  assert.doesNotMatch(ft, /passed: [^.]*Fade/);
  // An older server without the block: no strip.
  assert.equal((await strip({})).root.querySelector('#dash-since'), null);
});

test('Meridian: the strip splits a book\'s figure by the strategy that traded it, inside that book only', async () => {
  const dep = (id, title, mode, status) => ({id, strategy_id: 100 + id, title, market: 'btc15m', mode, status, status_reason: null,
    stake: 5, max_positions: 3, realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 0, curve: [], created_at: '2026-10-20T08:00:00Z'});
  const deployments = [dep(3, 'ETH drift', 'paper', 'running'), dep(4, 'SOL <i>fade</i>', 'paper', 'paused'), dep(5, 'Demo copy', 'demo', 'running')];
  const since = {at: '2026-10-19T08:00:00+00:00', first: false,
    books: {paper: {pnl: -24.19, trades: 19}, demo: {pnl: 1.5, trades: 2}, live: {pnl: 0, trades: 0}},
    passed: {n: 0, items: []}, autopilot: {}, runs: {},
    by_deployment: {paper: [{deployment_id: 3, pnl: 28.89, trades: 12}, {deployment_id: 4, pnl: -53.08, trades: 7}],
      demo: [{deployment_id: 5, pnl: 1.5, trades: 2}]}};
  const strip = async (extra) => {
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...dashboardData(), deployments, ...extra});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    return f.root.querySelector('#dash-since').innerHTML;
  };
  const text = await strip({since});
  // Paper: the winner and the loser named, each with its own signed amount; demo (one strategy) has no split.
  assert.match(text, /<div class="since-split" data-book="paper"><span class="since-sub">Paper:<\/span> <a href="\/strategies\/103">ETH drift<\/a> <span class="nobr"><span class="pos">\+\$28\.89<\/span> on 12<\/span><span class="sep">·<\/span><a href="\/strategies\/104">SOL &lt;i&gt;fade&lt;\/i&gt;<\/a> <span class="nobr"><span class="neg">−\$53\.08<\/span> on 7<\/span><\/div>/);
  assert.doesNotMatch(text, /data-book="demo"><span class="since-sub">|since-split" data-book="demo"/);
  assert.doesNotMatch(text, /\$27\.39|−\$22\.69/);  // nothing adds paper and demo together
  // Only the paper book shown: no book label in front of its split; a deployment no longer listed is named plainly.
  const solo = await strip({since: {...since, books: {paper: since.books.paper},
    by_deployment: {paper: [...since.by_deployment.paper, {deployment_id: 99, pnl: -1, trades: 1}, {deployment_id: 98, pnl: -2, trades: 1}]}},
  deployments: deployments.slice(0, 2)});
  assert.match(solo, /<div class="since-split" data-book="paper"><a href="\/strategies\/103">ETH drift<\/a>/);
  assert.match(solo, /a removed strategy <span class="nobr"><span class="neg">−\$1\.00<\/span> on 1<\/span><span class="sep">·<\/span><span class="since-sub">1 more<\/span><\/div>/);
  // A removed deployment the server names says whose it was: its strategy, or a deleted strategy once that is gone too.
  const named = await strip({since: {...since, books: {paper: since.books.paper}, by_deployment: {paper: [
    {deployment_id: 97, pnl: 2, trades: 1, removed: true, strategy_id: 7, title: 'Old fade'},
    {deployment_id: 96, pnl: -1, trades: 2, removed: true, strategy_id: 6, title: null}]}}, deployments: deployments.slice(0, 2)});
  assert.match(named, /<a href="\/strategies\/7">Old fade<\/a> <span class="since-sub">\(removed deployment\)<\/span> <span class="nobr"><span class="pos">\+\$2\.00<\/span> on 1<\/span>/);
  assert.match(named, /a deleted strategy <span class="nobr"><span class="neg">−\$1\.00<\/span> on 2<\/span>/);
  assert.doesNotMatch(named, /a removed strategy/);
  // An older server without the split: the book's line alone.
  assert.doesNotMatch(await strip({since: {...since, by_deployment: undefined}}), /since-split/);
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
    // Up top, in the strip, where a phone sees it without scrolling: the page's one way to the example.
    assert.equal(/No sessions of your own yet\. <a href="\/example" data-example>See an example session first<\/a>/.test(f.root.querySelector('#dash-since').innerHTML), shown);
    // The empty Deployed box no longer repeats it as a second primary button beside the autopilot card's.
    assert.doesNotMatch(f.root.querySelector('#deps-empty').innerHTML, shown ? /class="btn/ : /href="\/example"/, String(own));
    const page = ['#boardbody', '#main', '#dash-ap'].map((sel) => f.root.querySelector(sel).innerHTML).join('');
    assert.equal((page.match(/href="\/example"/g) || []).length, shown ? 1 : 0, String(own));
    assert.deepEqual(page.match(/class="btn primary[^>]*>[^<]*/g), ['class="btn primary" data-apcard="on">Turn on autopilot'], String(own));
  }
  // Research: only the seeded example so far, so it leads with it (one tap, straight to the session).
  let f = exResearch([exRun]);
  await f.viewResearch(); await flush(); await flush();
  const top = f.root.querySelector('#rexample').innerHTML;
  // A plain button: Start session is the page's one primary action.
  assert.match(top, /<a class="btn ex-cta" href="\/research\/3" data-example>See an example session first<\/a>/);
  assert.match(top, /It cost you nothing/);
  const html = f.root.innerHTML;
  assert.ok(html.indexOf('id="rexample"') < html.indexOf('id="dispatch"'));
  assert.equal((f.root.querySelector('#dispatch').innerHTML.match(/class="btn primary/g) || []).length, 1);
  assert.doesNotMatch(top, /btn primary/);
  // The form's own demo link would open the same session twice over: it waits until the line goes.
  assert.equal(f.root.querySelector('[data-ex-open]').hidden, true);
  // A session of their own: no nudge.
  f = exResearch([ownRun, exRun]);
  await f.viewResearch(); await flush(); await flush();
  assert.equal(f.root.querySelector('#rexample').innerHTML, '');
  // Came to start one (?new=1, "Describe your own idea" on the example itself): they have just seen it.
  f = exResearch([exRun]);
  f.location.pathname = '/research'; f.location.search = '?new=1';
  await f.viewResearch(); await flush(); await flush();
  assert.equal(f.root.querySelector('#rexample').innerHTML, '');
  const back = f.root.querySelector('[data-ex-open]');
  assert.equal(back.hidden, false); assert.equal(back.getAttribute('href'), '/research/3');  // still one quiet way back
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
  f.location.pathname = '/research'; f.location.search = '?new=1';  // from the example: the form's own link leads back
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
    assert.deepEqual(folds.map((d) => d.querySelector('summary').textContent), ['Most recent later-period trades (unseen\u00a0data)', 'Methodology', 'Sensitivity']);
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
  if (path === '/api/kalshi-key/delete') { state.live = {connected: false}; return response({ok: true}); }
  if (path === '/api/kalshi-dev-key/delete') { state.dev = {connected: false}; return response({ok: true}); }
  throw new Error('Unexpected offline request: ' + path);
}});
const submitKey = async (f, id, kid, pem) => {
  const form = f.root.querySelector('#' + id); form.key_id = {value: kid}; form.private_key = {value: pem};
  await form.onsubmit({preventDefault() {}}); await flush();
};

test('Funds says where each Kalshi key comes from, what to paste, and which key goes where', async () => {
  const f = keyFunds({reads: 0, live: {connected: false}, dev: {connected: false}});
  await f.viewFunds();
  const live = f.root.querySelector('#kalshi').closest('section').innerHTML, main = f.root.querySelector('#main').innerHTML;
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
  assert.match(f.root.querySelector('#main').innerHTML, /<p class="key-ok"><b>Connected ✓<\/b> \(balance \$1,234\.50\)<\/p>/);
  await submitKey(f, 'kalshi-dev', KID, PEM);
  assert.match(f.root.querySelector('#kdflash').innerHTML, /Connected ✓ \(Kalshi demo account cash \$25,000\.00\)\. Kalshi’s demo exchange confirmed the key\./);
  assert.match(f.root.querySelector('#main').innerHTML, /<b>Connected ✓<\/b> \(Kalshi demo account cash \$25,000\.00\)<\/p>/);
  const sent = postRequests(f).map(({path}) => path);
  assert.deepEqual(sent, ['/api/kalshi-key', '/api/kalshi-dev-key']);
  assert.doesNotMatch(f.root.querySelector('#main').innerHTML, /MIIE|BEGIN RSA PRIVATE KEY-----\n/);  // the key is never shown back
  // No balance from Kalshi (down, or the key deleted there) is "saved", never a green check, and says what to do.
  const g = keyFunds({reads: 0, live: {connected: true, balance: null, key_id: 'a952…608c'}, dev: {connected: true, key_id: 'a952…608c', balance: null}});
  await g.viewFunds();
  const gm = g.root.querySelector('#main').innerHTML;
  assert.doesNotMatch(gm, /Connected ✓/);
  assert.equal((gm.match(/<p class="key-ok key-unread"><b>Key saved<\/b> \(Kalshi didn’t send a balance for it just now\)<\/p>/g) || []).length, 2);
  assert.match(gm, /the key may have been deleted on kalshi\.com: disconnect it and connect a new one\./);
  assert.match(gm, /the key may have been deleted on demo\.kalshi\.co: remove it and connect a new one\./);
  assert.doesNotMatch(gm, /has \$0\.00/);  // unknown is not empty
});

test('a $0 Kalshi demo account is explained, and keys are changed or removed with plain feedback', async () => {
  const state = {reads: 0, live: {connected: true, balance: 1234.5, key_id: 'a952…608c', funding_url: 'https://kalshi.com/account/funding'}, dev: {connected: true, key_id: 'a952…608c', balance: 0}};
  const f = keyFunds(state);
  await f.viewFunds();
  const main = f.root.querySelector('#main').innerHTML;
  assert.match(main, /Your Kalshi demo account has \$0\.00, so Kalshi refuses demo orders\. Add demo funds in your account on <a href="https:\/\/demo\.kalshi\.co\/" target="_blank" rel="noopener">demo\.kalshi\.co<\/a>/);
  assert.match(main, /To change keys, disconnect and connect the new one\./);
  assert.match(main, /To change keys, remove this one and connect the new one\./);
  // The live perps box shows only where /api/me says live perps are on (the fixture says nothing).
  assert.equal(f.root.querySelector('#kalshi-perps-live'), null);
  // Removing takes a second tap, then says the key still works at Kalshi until deleted there.
  const dc = f.root.querySelector('#disconnect');
  dc.onclick(); assert.equal(postRequests(f).length, 0);
  f.elapse(500); await dc.onclick(); await flush();
  assert.deepEqual(postRequests(f).map(({path}) => path), ['/api/kalshi-key/delete']);
  assert.match(f.root.querySelector('#kflash').innerHTML, /Disconnected\. Tau deleted its copy of the key; the key itself stays valid until you delete it on kalshi\.com\./);
  const dvc = f.root.querySelector('#dev-disconnect');
  dvc.onclick(); f.elapse(500); await dvc.onclick(); await flush();
  assert.match(f.root.querySelector('#kdflash').innerHTML, /Demo key removed\. Tau deleted its copy; delete the key on demo\.kalshi\.co too/);
  // Both key forms are back, with no autofill and no phone auto-capitalising of the Key ID or the key.
  const fresh = f.root.querySelector('#main').innerHTML;
  assert.equal((fresh.match(/name="key_id" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"/g) || []).length, 2);
  assert.equal((fresh.match(/name="private_key" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"/g) || []).length, 2);
  const on = keyFunds(state); on.S.me.perps_live_available = true;
  await on.viewFunds();
  assert.ok(on.root.querySelector('#kalshi-perps-live'));
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
const billingPage = (data, posts = [], routes = {}) => frontend({stripeLoader: async () => STRIPE_STUB, fetchImpl: (path, options = {}) => {
  if (routes[path]) return routes[path](options);
  if (/^\/api\/billing(\?|$)/.test(path)) return response(data);
  if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
  if (path === '/api/billing/auto-reload') { posts.push(JSON.parse(options.body)); return response({ok: true}); }
  throw new Error('Unexpected offline request: ' + path);
}});

test('Billing copies its balance and card onto the page state, and a moved balance re-reads the autopilot status', async () => {
  const f = frontend({stripeLoader: async () => STRIPE_STUB, fetchImpl: (path) => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response(cardedBilling({balance: 20.4}));
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    if (path === '/api/autopilot/status') return response({...apStatus, billing_blocked: false});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, needs_card: true, credit_balance: 0.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = true;
  const box = new Element('div', {id: 'autopilot-float'}); f.document.body.appendChild(box);
  await f.viewBilling(); await flush(); await flush();
  assert.equal(f.S.me.credit_balance, 20.4); assert.equal(f.S.me.needs_card, false);
  assert.deepEqual({...f.S.me.auto_reload}, {amount: 25, charge: cardedBilling().autoreload_charge, threshold: 8});
  assert.equal(f.requests.filter(({path}) => path === '/api/autopilot/status').length, 1);
  assert.equal(f.S.ap.billing_blocked, false);
  const since = {deployments: [], since: {at: '2026-10-25T08:00:00+00:00', first: false, books: {}, passed: {n: 0, items: []}, autopilot: {}, runs: {}}};
  assert.doesNotMatch(f.sinceStrip(since, '#dash-paused'), /Credits are at/);
  await f.viewBilling(); await flush(); await flush();
  assert.equal(f.requests.filter(({path}) => path === '/api/autopilot/status').length, 1);  // nothing moved: no extra read
});

test('Meridian: saving auto-reload updates the page state the autopilot card reads, with no extra read', async () => {
  const posts = [];
  const f = frontend({stripeLoader: async () => STRIPE_STUB, storage: new Map([['tau_ap_open', '1']]), fetchImpl: (path, options = {}) => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response(cardedBilling({balance: 23.4}));
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    if (path === '/api/billing/auto-reload') { posts.push(JSON.parse(options.body)); return response({ok: true, autoreload_charge: 52.75}); }
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, credit_balance: 23.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = true;
  f.S.ap = {...apStatus, week: {research_credits: 7.26, tested: 10, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0, credits_left: 23.4, runway_days: 6.1}};
  const box = new Element('div', {id: 'autopilot-float'}); f.document.body.appendChild(box);
  await f.viewBilling(); await flush(); await flush();
  const reads = () => f.requests.filter(({path}) => /^\/api\/billing(\?|$)/.test(path) || path === '/api/autopilot/status').length, before = reads();
  const amt = f.root.querySelector('#reload-amt'); amt.value = '50'; await amt.onchange(); await flush();
  assert.deepEqual(posts, [{on: true, amount: 50, threshold: 8}]);
  assert.deepEqual({...f.S.me.auto_reload}, {amount: 50, charge: 52.75, threshold: 8});
  assert.match(box.querySelector('#apf-week').innerHTML, /each time your balance falls to \$8\.00, auto-reload charges your card \$52\.75 for \$50\.00 more/);
  assert.equal(reads(), before);
});

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
  const main = f.root.querySelector('#main').innerHTML;
  assert.match(main, /<a class="btn sm" href="\/api\/billing\/receipt" download>Download receipt \(CSV\)<\/a>/);
  assert.match(main, /<p class="hint ledger-key">Newest first\. The receipt has every line, with exact amounts\.<\/p>/);
  const rows = f.root.querySelectorAll('.t-ledger tbody tr').map((r) => r.innerHTML);
  assert.equal(rows.length, 5);
  assert.match(rows[0], /Agent usage<div class="sub-fig">Claude Opus 4\.6<\/div>[\s\S]*−\$0\.21/);  // the model's name, never its id
  assert.doesNotMatch(rows[0], /Agent usage · |claude-opus/);  // the memo's prefix isn't said twice
  assert.match(rows[1], /Auto-reload<div class="sub-fig">Card charged: \$25\.00 credits plus the 5\.5% purchase fee<\/div>[\s\S]*\+\$25\.00/);
  assert.match(rows[2], /Agent usage<div class="sub-fig">Research run \(seed\)<\/div>[\s\S]*−\$0\.91/);
  assert.match(rows[3], /Added credits<div class="sub-fig">Card charged: \$10\.00 credits plus the 5\.5% purchase fee<\/div>[\s\S]*\+\$10\.00/);
  assert.match(rows[4], /Welcome credits<\/td>[\s\S]*\+\$20\.00/);  // free credits: no card line
  assert.doesNotMatch(main, /list price/);
  // The figures up top are unchanged: what the server sent, formatted as before.
  assert.match(f.root.querySelector('#bfigs').innerHTML, /\$7\.42/);
  assert.match(f.root.querySelector('#bfigs').innerHTML, /\$47\.58/);
});

test('Billing statement: a heading per day, one line per session a day that links it, each card charge with its Stripe ref, and a sum that closes', async () => {
  const f = billingPage(cardedBilling({
    math: {days: 30, start: 12.5, bought: 35, purchases: 2, other: 0, usage: 40.08, end: 7.42},
    ledger: [
      {kind: 'usage', amount: -12.9494, memo: 'Research session · Claude Opus 4.6', item: 'Research session', model: 'Claude Opus 4.6', calls: 57,
        created_at: '2026-01-15T08:50:00Z', first_at: '2026-01-15T08:01:00Z', day: '2026-01-15',
        session: {id: 108, prompt: '<b>Fade</b> the open', market: 'btc15m', direction: 'momentum'}},
      {kind: 'autoreload', amount: 25, memo: 'Auto-reload $25', created_at: '2026-01-15T08:01:00Z', first_at: '2026-01-15T08:01:00Z',
        day: '2026-01-15', card_charge: 26.38, stripe_ref: 'pi_3Synthetic<x>'},
      {kind: 'usage', amount: -0.0126, memo: 'Autopilot check-in · Claude Haiku 4.5', item: 'Autopilot check-in', model: 'Claude Haiku 4.5', calls: 3,
        created_at: '2026-01-14T20:01:00Z', first_at: '2026-01-14T20:00:00Z', day: '2026-01-14'},
      {kind: 'topup', amount: 10, memo: 'Added $10 credits', created_at: '2026-01-14T14:00:00Z', first_at: '2026-01-14T14:00:00Z',
        day: '2026-01-14', card_charge: 10.55, stripe_ref: 'pi_3SyntheticTopup'},
    ], ledger_cut: true}));
  await f.viewBilling(); await flush();
  // The days are the viewer's: the read says the browser's offset from UTC.
  assert.ok(f.requests.some(({path}) => /^\/api\/billing\?tz=-?\d+$/.test(path)));
  const main = f.root.querySelector('#main').innerHTML;
  // The balance 30 days ago, plus credits bought, minus agent usage, is the balance now: the server's cents.
  assert.match(main, /<dl class="bill-math">[\s\S]*Balance 30 days ago<\/dt><dd>\$12\.50<\/dd>[\s\S]*Credits bought \(2 card charges\)<\/dt><dd>\+\$35\.00<\/dd>[\s\S]*Agent usage<\/dt><dd>−\$40\.08<\/dd>[\s\S]*class="total"><dt>Balance now<\/dt><dd>\$7\.42<\/dd>/);
  assert.doesNotMatch(main, /Welcome and other credits/);  // nothing else came in this month
  assert.match(main, /<p class="hint ledger-key">Last 30 days, newest first\./);
  const rows = f.root.querySelectorAll('.t-ledger tbody tr').map((r) => r.innerHTML);
  assert.equal(rows.length, 6);  // two day headings and four lines
  assert.match(rows[0], /<td colspan="3" data-lab="Day"><b>[A-Z][a-z]{2}, Jan 15<\/b><span class="day-sum">\$12\.95 used\u00a0· \+\$25\.00 credits<\/span><\/td>/);
  assert.match(rows[1], /<time datetime="2026-01-15T08:50:00Z">\d\d:\d\d–\d\d:\d\d/);  // the span of the session's calls
  assert.match(rows[1], /Research session<div class="sub-fig"><a href="\/research\/108">&lt;b&gt;Fade&lt;\/b&gt; the open<\/a>\u00a0· Claude Opus 4\.6\u00a0· 57 model calls<\/div>[\s\S]*−\$12\.95/);
  assert.match(rows[2], /Auto-reload<div class="sub-fig">Card charged \$26\.38: \$25\.00 credits plus the 5\.5% purchase fee\u00a0· Stripe ref <span class="ref">pi_3Synthetic&lt;x&gt;<\/span><\/div>[\s\S]*\+\$25\.00/);
  assert.match(rows[3], /<b>[A-Z][a-z]{2}, Jan 14<\/b><span class="day-sum">\$0\.01 used\u00a0· \+\$10\.00 credits<\/span>/);
  assert.match(rows[4], /Autopilot check-in<div class="sub-fig">Claude Haiku 4\.5\u00a0· 3 model calls<\/div>/);
  assert.doesNotMatch(rows[4], /href=/);  // a check-in has no session page
  assert.match(rows[5], /Added credits<div class="sub-fig">Card charged \$10\.55: \$10\.00 credits plus the 5\.5% purchase fee\u00a0· Stripe ref <span class="ref">pi_3SyntheticTopup<\/span>/);
  assert.match(main, /Older days are in the receipt\./);  // the line cap left days out, and says where they are
  assert.doesNotMatch(main, /list price|markup|us\.anthropic/i);
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
  assert.match(key, /<span class="since-book" data-book="demo"><b>Demo<\/b>: no trades closed yet<\/span>/);
  // No `need` from an older server: its whole line, not an empty "Demo can't trade: ."
  const old = await strip({line: "Demo isn't trading: your Kalshi demo key isn't connected."});
  assert.match(old, /Demo isn.+t trading: your Kalshi demo key isn.+t connected\./); assert.doesNotMatch(old, /trade: \./);
});

test('the since strip says a demo book paused for its demo key once, beside the link to add it', async () => {
  const since = {at: '2026-10-25T08:00:00+00:00', first: false, books: {demo: {pnl: 0, trades: 0}},
    passed: {n: 0, items: []}, autopilot: {}, runs: {}};
  const dep = (id, title, mode, why) => ({id, strategy_id: id, title, market: 'btc15m', mode, status: 'paused', status_reason: why,
    stake: 5, max_positions: 2, realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 0, curve: [], created_at: '2026-10-25T08:00:00Z'});
  const KEY = 'Add your Kalshi demo (sandbox) key on the Funds page to run this on demo.';
  const LIVE = 'Add your live Kalshi key on the Funds page to run this on live money.';
  const strip = async (deployments, health) => {
    const base = dashboardData();
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...base, deployments, since, demo: {...base.demo, health}});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    return f.root.querySelector('#dash-since').innerHTML;
  };
  const health = {code: 'demo_key', need: 'your Kalshi demo key', line: "Demo isn't trading: your Kalshi demo key isn't connected.",
    action: {label: 'Add it on the Funds page', href: '/funds#connect-kalshi'}};
  const html = await strip([dep(4, 'Fade <tails>', 'demo', KEY), dep(5, 'Live one', 'live', LIVE)], health);
  // The demo key is said once, on the demo line with its link; the paused row only names the strategy.
  assert.match(html, />Fade &lt;tails&gt;<\/a> is paused<br>/);
  assert.equal((html.match(/demo \(sandbox\) key|your Kalshi demo key/g) || []).length, 1, html);
  assert.match(html, /Demo can’t trade: it needs your Kalshi demo key\. <a href="\/funds#connect-kalshi">Add it on the Funds page<\/a>/);
  // Another reason that sends someone to Funds links "the Funds page", as its Deploy row does.
  assert.match(html, />Live one<\/a> is paused<span class="since-sub">: Add your live Kalshi key on <a href="\/funds#connect-kalshi">the Funds page<\/a> to run this on live money<\/span>/);
  // With no demo-key line to say it (an older server), the row keeps its reason, linked.
  const alone = await strip([dep(4, 'Fade', 'demo', KEY)], null);
  assert.match(alone, />Fade<\/a> is paused<span class="since-sub">: Add your Kalshi demo \(sandbox\) key on <a href="\/funds#connect-kalshi">the Funds page<\/a> to run this on demo<\/span>/);
});

test('past its paper-trade target the autopilot card says how many and how many were needed, never "67 of 30"', async () => {
  for (const [trades, said] of [[4, '4 of 30 realistic paper trades'], [67, '67 realistic paper trades (30 needed)'], [30, '30 realistic paper trades (30 needed)']]) {
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
  const html = f.root.querySelector('#main').innerHTML;
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

test('a deployed book with nothing open says so instead of "Not marked yet"', async () => {
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
  assert.match(cells[1], /<span class="unavailable">Not marked yet<\/span>/);
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
  const html = visible(f.root.querySelector('#deps').innerHTML);
  assert.ok(html.includes('+$0.75'), 'paper deployment 1: its two marks');
  assert.ok(html.includes('+$2.00'), 'live deployment 2: its own mark only');
  assert.doesNotMatch(html, /\+\$2\.75/);  // never added across deployments or books
});

// Why an idea did not pass (server services.gate_explain): every place that shows the verdict lists
// each missed gate with what was measured, what was needed and one thing to try next, escaped. A
// label says what fell short ("Too few trades…"), never the check's goal, so it reads right under VOID.
const MISSED = [
  {gate: 'sample_size', check: 'Enough trades to judge', label: 'Too few trades to judge (18 of 30)', measured: '18 trades on the unseen test window',
    needed: 'at least 30 trades (fixed before the test)', next: 'Needs about 12 more trades: widen the market set or lengthen the test window, or loosen the entry rule so it fires more often.'},
  {gate: 'other', check: 'Min <b>sharpe</b> ratio', label: 'Didn\'t pass: Min <b>sharpe</b> ratio', measured: '0.4', needed: 'at least 0.5', next: 'Change one thing about the rule and test again, so you can see what moves this check.'},
];
const MISSED_ROWS = [
  ['Too few trades to judge (18 of 30)', 'Measured 18 trades on the unseen test window; needed at least 30 trades (fixed before the test).', MISSED[0].next],
  ['Didn&#39;t pass: Min &lt;b&gt;sharpe&lt;/b&gt; ratio', 'Measured 0.4; needed at least 0.5.', MISSED[1].next],
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
  // A pass lists nothing it missed; its one-time holdout lands on the same card after the verdict,
  // with the lines it missed there, not on a loose row stamped VOID.
  const [passPart, holdout] = reviews[1].split('Locked holdout');
  assert.deepEqual(missedRows(passPart), []);
  assert.match(passPart, /Cleared every gate/);
  assert.deepEqual(missedRows(holdout), [MISSED_ROWS[0]]);
  assert.match(holdout, /missed/);
  assert.doesNotMatch(reviews[1], /classification=/);
  assert.equal(items.filter((li) => !li.removed).length, 2);
  // The agent log folds shut once a session ends, so the Strategies list carries each miss too:
  // the first gate under the strategy's name, and a link to the rest on its page; a pass shows none.
  // Passed strategies lead the list.
  const rows = f.root.querySelector('#run-artifacts').innerHTML.split('<tr').slice(2);
  assert.deepEqual(missedRows(rows[1]), [MISSED_ROWS[0]]);
  assert.match(rows[1], /<a class="sub-fig" href="\/strategies\/41">1 more check on its page<\/a>/);
  assert.doesNotMatch(rows[0], /slip-missed/);
  f.clearTimers();
  // Nothing passed: the next-step line says where the reasons are.
  const none = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run: {...run, strategies_passed: 0}, events: [], strategies: [{id: 41, title: 'Fade', status: 'failed'}]}) : response({})});
  await none.viewRun(9); none.clearTimers();
  assert.match(none.root.querySelector('#runnext').innerHTML, /Each strategy below says which check it missed and what to try next\./);
});

test('Meridian: a run says its ledger lines in plain words, with the zone of its times', async () => {
  const run = {id: 9, status: 'succeeded', prompt: 'Session 9', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', hypotheses_tried: 2, strategies_passed: 1};
  const at = '2026-10-17T10:01:00Z';
  const events = [
    {id: 1, kind: 'verdict', message: 'Lead scan: control arm, hypotheses first.', created_at: at,
      data: {phase: 'leads', arm: 'control', why_failed: [], note: 'Went straight to ideas, with no scan of the data first.'}},
    {id: 2, kind: 'hypothesis', message: 'Lean in', created_at: at, data: {in_sample: {pnl: 3, trades: 9}}},
    {id: 3, kind: 'verdict', message: 'PASSED - Lean in: validation verdict is gatekeeper-held (classification=statistically_supported, 88 trades); the numbers never return to the generator.',
      created_at: at, data: {status: 'passed', title: 'Lean in', strategy_id: 42, why_failed: [], note: 'Passed every check on data it never saw (88 trades).'}},
    {id: 4, kind: 'verdict', message: 'Other: one-time holdout verdict is gatekeeper-held (classification=forward_validated, 31 trades); the numbers never return to the generator.',
      created_at: at, data: {title: 'Other', phase: 'holdout', classification: 'forward_validated', why_failed: [], note: 'Held up on the locked holdout, a final test it gets only once (31 trades).'}},
    {id: 5, kind: 'verdict', message: 'DROPPED "Thin" (no candidate) — every variant took 0 trades', created_at: at,
      data: {title: 'Thin', status: 'abandoned', why: 'every variant took 0 trades', why_failed: []}},
  ];
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run, events, strategies: []}) : response({})});
  await f.viewRun(9); await flush();
  const log = f.root.querySelector('#log').children.filter((li) => !li.removed).map((li) => li.innerHTML + (li.querySelector('[data-review]') || {innerHTML: ''}).innerHTML).join('\n');
  assert.doesNotMatch(log, /classification=|gatekeeper-held|control arm|VOID/);
  assert.match(log, /Went straight to ideas, with no scan of the data first\./);
  assert.match(log, /Passed every check on data it never saw \(88 trades\)\./);
  assert.match(log, /Locked holdout · held<\/span><span class="hx-vtext">Held up on the locked holdout/);
  assert.match(log, /DROPPED<\/b> <b>Thin<\/b> — every variant took 0 trades/);
  assert.match(log, /<time datetime="2026-10-17T10:01:00Z" title="[^"]+">/);
  f.clearTimers();
});

const M_RUN_AT = async (run, events = [], strategies = []) => {
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: '2026-10-25T10:00:00Z', ...run}, events, strategies}) : response({})});
  await f.viewRun(9); await flush(); f.clearTimers();
  return f;
};
const M_FIG = (html, label) => (html.split(label)[1] || '').replace(/<[^>]*>/g, ' ').trim().split(/\s+/)[0];

test('Meridian: a session that ran out of credits says so and offers Add credits, not "Done" and another idea', async () => {
  const step = {id: 7, kind: 'step', message: 'Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching.', created_at: '2026-10-25T11:00:00Z'};
  let f = await M_RUN_AT({status: 'succeeded', run_forever: 1, hypotheses_tried: 4, strategies_passed: 0}, [step], [{id: 43, title: 'Fade', status: 'failed', market: 'btc15m', direction: 'momentum'}]);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Out of credits/);
  const next = f.root.querySelector('#runnext').innerHTML;
  assert.match(next, /It stopped when your credits ran out\. <a href="\/billing">Add credits<\/a>, then start a new session to keep researching\. Nothing passed before then/);
  assert.doesNotMatch(next, /Try another idea/);
  assert.equal(f.root.querySelector('#runend').innerHTML, '<div class="run-end"><a class="btn" href="/billing">Add credits</a></div>');
  f = await M_RUN_AT({status: 'succeeded'}, [], []);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Finished/);
  assert.doesNotMatch(f.root.querySelector('#runnext').innerHTML, /billing/);
});

test('Meridian: a running session counts its ideas and passes live; a stopped one leaves no idea "Testing" and says a provider failure once', async () => {
  const hyp = (id) => ({id, kind: 'hypothesis', message: 'Idea ' + id, data: {}, created_at: '2026-10-25T10:00:00Z'});
  let f = await M_RUN_AT({status: 'running', run_forever: 1, hypotheses_tried: 3, strategies_passed: 0}, [1, 2, 3, 4, 5].map(hyp), [{id: 42, title: 'Late', status: 'passed', market: 'btc15m', direction: 'momentum'}]);
  let figs = f.root.querySelector('#runfigs').innerHTML;
  assert.equal(M_FIG(figs, 'Tested'), '5'); assert.equal(M_FIG(figs, 'Passed'), '1');
  f = await M_RUN_AT({status: 'running', max_hypotheses: 10, hypotheses_tried: 2}, [hyp(1)], []);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /of up to 10/);
  f = await M_RUN_AT({status: 'succeeded', started_at: '2026-10-25T10:00:00Z', finished_at: '2026-10-25T14:59:00Z'});
  assert.equal(M_FIG(f.root.querySelector('#runfigs').innerHTML, 'Time'), '5');
  const error = 'The research models are at capacity right now, so the session stopped. Start it again in a little while.';
  f = await M_RUN_AT({status: 'failed', error}, [{id: 1, kind: 'hypothesis', message: 'Vol', data: {}, created_at: '2026-10-25T10:00:00Z'}]);
  const stamp = f.root.querySelector('#log').querySelector('[data-stamp]');
  assert.equal(stamp.textContent, 'Not finished'); assert.equal(stamp.classList.contains('pending'), false);
  assert.doesNotMatch(f.root.querySelector('#runnext').innerHTML, /stopped on an error/);
  assert.match(f.root.querySelector('#runnext').innerHTML, /so the session stopped\. Start it again in a little while\. <a href="\/research\?new=1">Start a new session<\/a>/);
});

test('Meridian: a long session shows its first strategies and folds the rest behind Show all', async () => {
  const strategies = Array.from({length: 12}, (_, i) => ({id: 100 + i, title: 'Idea ' + i, status: i === 9 ? 'passed' : 'failed', market: 'btc15m', direction: 'momentum'}));
  const run = {id: 9, status: 'stopped', prompt: 'Session 9', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', hypotheses_tried: 12, strategies_passed: 1};
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run, events: [], strategies}) : response({})});
  await f.viewRun(9); await flush();
  const results = f.root.querySelector('#run-artifacts');
  assert.equal(results.querySelectorAll('tbody tr').length, 8);
  assert.equal(results.querySelector('tbody .name a').getAttribute('href'), '/strategies/109');  // the pass leads
  assert.match(results.innerHTML, /data-allstrats[^>]*>Show all 12<\/button>/);
  // A phone shows four: eight cards were ~2,000px between the figures and the log.
  const ph = frontend({matchMedia: () => ({matches: true}), fetchImpl: path => path.startsWith('/api/runs/9') ? response({run, events: [], strategies}) : response({})});
  await ph.viewRun(9); await flush(); ph.clearTimers();
  assert.equal(ph.root.querySelector('#run-artifacts').querySelectorAll('tbody tr').length, 4);
  assert.match(ph.root.querySelector('#run-artifacts').innerHTML, /data-allstrats[^>]*>Show all 12<\/button>/);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Stopped/);
  f.clearTimers();
  // A failed session says why and how to start again, above the folded log.
  const bad = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run: {...run, status: 'failed', error: 'The model <i>timed out</i>.'}, events: [], strategies: []}) : response({})});
  await bad.viewRun(9); bad.clearTimers();
  assert.match(bad.root.querySelector('#runnext').innerHTML, /This session stopped on an error\. The model &lt;i&gt;timed out&lt;\/i&gt;\. <a href="\/research\?new=1">Start a new session<\/a>/);
});

test('Meridian: the strategy page lists what it missed under Verdict and names the first in the Deploy notice', async () => {
  const f = strategyFrontend(detailStrategy({status: 'failed', why_failed: MISSED})); await f.viewStrategy(42); await flush();
  const html = f.root.querySelector('#main').innerHTML;
  const at = html.indexOf('What it missed, and what to try next');
  assert.ok(at > html.indexOf('Verdict'), 'listed in the Verdict section');
  assert.deepEqual(missedRows(html.slice(at)).slice(0, 2), MISSED_ROWS);
  assert.match(html, /Void: too few trades to judge \(18 of 30\), and 1 more check missed \(see Verdict\)\. It wasn’t validated/);
  assert.doesNotMatch(html, /failed the unseen-data gate|<b>sharpe/);
  const r = strategyFrontend(detailStrategy({status: 'rejected', why_failed: [MISSED[0]]})); await r.viewStrategy(42); await flush();
  assert.match(r.root.querySelector('#main').innerHTML, /Rejected: too few trades to judge \(18 of 30\) \(see Verdict\)\./);
  // Passed, or an older server without the field: nothing extra, and the old notice stands.
  for (const extra of [{why_failed: []}, {}]) {
    const p = strategyFrontend(detailStrategy(extra)); await p.viewStrategy(42); await flush();
    assert.doesNotMatch(p.root.querySelector('#main').innerHTML, /What it missed|class="why-failed"/);
  }
  const old = strategyFrontend(detailStrategy({status: 'failed'})); await old.viewStrategy(42); await flush();
  assert.match(old.root.querySelector('#main').innerHTML, /Void: it failed the unseen-data gate\./);
});

// The research paper's figures are red exactly when the gate that judges them missed. The server
// judges each figure with the gatekeeper's own thresholds (services.gate_explain.strategy_tints, the
// same checks that write why_failed); the page restates no cutoff. These fixtures are what the server
// sends for these numbers (tests/test_gate_explain.py pins the server side).
const FIGURE_GATES = {'Trades': ['sample_size'], 'Bootstrap p-value': ['significance', 'multiple_testing'],
  'Net return per trade': ['net_edge'], 'DSR': ['deflated_sharpe'], 'Placebo p-value': ['placebo']};
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
  const red = tintedFigures(paperSections(f.root.querySelector('#main').innerHTML).validation);
  assert.deepEqual(red.sort(), missedFigures(VAL_LINES).sort());
  assert.deepEqual(red.sort(), ['Bootstrap p-value', 'Net return per trade', 'Trades']);
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
  const hs = paperSections(h.root.querySelector('#main').innerHTML);
  assert.deepEqual(tintedFigures(hs.validation), []);
  assert.deepEqual(tintedFigures(hs.holdout).sort(), missedFigures(HOLD_LINES).sort());
  assert.match(hs.holdout, /<div class="k">Holdout<\/div><div class="val">Consumed<\/div>/);
  // An older server without gate_tints judges nothing, so nothing is red, whatever the numbers.
  const old = strategyFrontend(detailStrategy({status: 'failed', experiment: {...failing, holdout: held.holdout, gate_tints: undefined}}));
  await old.viewStrategy(42); await flush();
  assert.doesNotMatch(old.root.querySelector('#main').innerHTML, /class="val sig"/);
});

test('Meridian: the dashboard says where the sessions it counts are, and points finished ones at what each idea missed', async () => {
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
    /Nothing new passed<span class="since-sub">\u00a0· 2 research sessions started, all finished, <a href="\/research">see what each idea missed<\/a><\/span>\./);
  // A session still queued or running hasn't judged any idea yet: the line says where it is instead.
  const queued = await at({...base, passed: {n: 0, items: []}, runs: {queued: 1}});
  assert.match(queued, /<span class="since-sub">\u00a0· 1 research session started, still queued, <a href="\/research">follow it on Research<\/a><\/span>\./);
  assert.doesNotMatch(queued, /see what each idea missed/);
  assert.match(await at({...base, passed: {n: 0, items: []}, runs: {running: 2}}), /2 research sessions started, all running, <a href="\/research">follow them on Research<\/a>/);
  assert.match(await at({...base, passed: {n: 0, items: []}, runs: {running: 1, succeeded: 2, cancelled: 1}}),
    /4 research sessions started, 1 running, 2 finished, 1 stopped, <a href="\/research">see what each idea missed<\/a>/);
  assert.match(await at({...base, passed: {n: 1, items: [{id: 9, title: 'Rain'}]}, runs: {queued: 1}}), /1 research session started, still queued<\/span>\./);
  assert.doesNotMatch(await at({...base, passed: {n: 1, items: [{id: 9, title: 'Rain'}]}, runs: {succeeded: 2}}), /see what each idea missed/);
  assert.doesNotMatch(await at({...base, passed: {n: 0, items: []}, runs: {}}), /see what each idea missed/);
});

test('the backtest luck line reads its trade bar from the server and names it as stricter than the gate', async () => {
  const flags = async overrides => {
    const f = strategyFrontend(detailStrategy(overrides)); await f.viewStrategy(42); await flush();
    return f.root.querySelectorAll('.luck-flag').map(p => p.textContent);
  };
  const lines = await flags({sample_caution: {min_trades: 30, gate_min_oos_trades: 10}});
  assert.equal(lines.length, 2);  // in-sample and out-of-sample, 6 trades each
  for (const line of lines) assert.match(line, /Only 6 trades — under 30, too few to tell skill from luck \(a caution, stricter than the gate’s floor of 10\)/);
  assert.deepEqual(await flags({sample_caution: {min_trades: 5, gate_min_oos_trades: 10}}), []);
  assert.deepEqual(await flags({}), []);  // no bar from the server, no line: never a guessed constant
});

test('Meridian first-run funnel: an empty paper track record never sends a user with nothing deployed to an empty Deploy board', () => {
  const f = frontend(), th = {min_sharpe_days: 30};
  f.S.me = {user: {autopilot: false}};
  const paper = () => f.trackRecordPanel({trades: 0, label: 'Paper'}, 'paper', th);
  f.S.dashDeps = 0; f.S.dashNoSessions = true;
  assert.match(paper(), /<a class="btn" href="\/research\?new=1">New session<\/a>/); assert.doesNotMatch(paper(), /Go to Deploy/);
  // The dashboard's autopilot card above already offers the switch: the record doesn't repeat it.
  assert.doesNotMatch(paper(), /Turn on autopilot/);
  f.S.dashNoSessions = false;
  assert.match(paper(), /<a class="btn" href="\/strategies\?status=passed">See passed strategies<\/a>/);
  f.S.dashDeps = 2; assert.match(paper(), /Go to Deploy/); assert.match(paper(), /Turn on autopilot/);
  f.S.dashDeps = undefined; assert.match(paper(), /Go to Deploy/);
  f.S.dashDeps = 0; assert.match(f.trackRecordPanel({trades: 0, label: 'Demo'}, 'demo', th), /Go to Deploy/);
  // A strategy just deployed on paper: the record says it's running instead of asking for a deploy.
  f.S.dashDeps = 1; f.S.dashOnPaper = 1;
  assert.match(paper(), /Your strategy is running on paper\. It trades only when its rule fires, so the first trade can take a while\./);
  assert.doesNotMatch(paper(), /Deploy a passed strategy on paper/); assert.match(paper(), /href="\/deploy">See it on Deploy</);
});

test('Meridian first-run funnel: an empty Deploy board with nothing passed starts a session instead of opening an empty list', async () => {
  for (const [passed, cta, href] of [[0, 'New session', '/research?new=1'], [2, 'See passed strategies', '/strategies?status=passed'], [null, 'See passed strategies', '/strategies?status=passed']]) {
    const seen = [];
    const f = frontend({fetchImpl: path => {
      seen.push(path);
      if (path === '/api/deployments') return response({deployments: [], open_positions: []});
      if (path === '/api/strategies?status=passed') return passed == null ? response({error: 'down'}, 500) : response({strategies: [], counts: passed ? {passed} : {rejected: 3}});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDeploy(); await flush(); await flush(); await flush();
    const deps = f.root.querySelector('#deps').innerHTML;
    assert.match(deps, new RegExp(`<a class="btn" href="${href.replace(/[?]/g, '\\?')}">${cta}</a>`), String(passed));
    assert.equal(/Nothing has passed yet/.test(deps), passed === 0);
    assert.equal(seen.filter((p) => p.startsWith('/api/strategies')).length, 1);
  }
});

test('Meridian first-run funnel: deploying from a strategy page lands on Deploy with a note that it worked and what happens next', async () => {
  const f = strategyFrontend(detailStrategy({title: 'Momentum <b>fade</b>'}), (path, options) => {
    if (options && options.method === 'POST') return response({id: 9});
    if (path === '/api/deployments') return response({deployments: [], open_positions: []});
    return response({strategies: [], counts: {passed: 1}});
  });
  await f.viewStrategy(42); await flush();
  f.root.querySelector('#dep-paper').onclick(); await flush(); await flush();
  assert.deepEqual(f.navigations, ['/deploy']);
  if (f.S.deployed) await f.viewDeploy();
  await flush(); await flush();
  const note = f.root.querySelector('#flash').innerHTML;
  assert.match(note, /class="notice good"/);
  assert.match(note, /Deployed on paper: Momentum &lt;b&gt;fade&lt;\/b&gt;\. It trades only when its rule fires, against live prices with paper money, so the first trade can take a while\./);
  assert.equal(f.S.deployed, null);
  await f.viewDeploy(); await flush();
  assert.equal(f.root.querySelector('#flash').innerHTML, '');
});

test('Meridian money pages: open positions name their market, settle with date and zone, and a live row says LIVE', async () => {
  const pos = (extra) => ({title: 'Drift', ticker: 'KXBTCD-26OCT2617-T68499.99', side: 'no', qty: 25, entry_price: .36, entry_fee: .41, cost: 9.41,
    unrealized: null, mode: 'paper', opened_at: '2026-10-25T08:00:00Z', market_close_time: '2030-01-15T17:30:00Z', ...extra});
  const markets = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET'}];
  const f = frontend({fetchImpl: path => path === '/api/deployments'
    ? response({deployments: [], open_positions: [pos(), pos({ticker: 'KXOTHER-1', market_close_time: new Date(Math.min(Date.now() + 60e3, new Date().setHours(23, 59, 59, 0))).toISOString()})]}) : response({})});
  f.S.me.markets = markets;
  await f.viewDeploy(); await flush(); await flush();
  const html = f.root.querySelector('#openpos').innerHTML;
  // The market's plain name leads, its own strike filled in; the ticker sits on a small line, to find it on Kalshi.
  assert.match(html, /<a href="\/explore\?m=KXBTCD-26OCT2617-T68499\.99">Bitcoin \$68,500 or above at 5pm ET<\/a><div class="sub-fig"><span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">KXBTCD-26OCT2617-T68499\.99<\/span>/);
  assert.match(html, /<a href="\/explore\?m=KXOTHER-1">Kalshi contract<\/a>/);
  assert.doesNotMatch(html, />KX[A-Z]+-[^<]*<\/a>/);
  assert.match(html, /data-lab="Settles">Jan 1[56], \d\d:\d\d [^<\s]+<\/td>/);
  assert.match(html, /data-lab="Settles">\d\d:\d\d [^<\s]+<\/td>/);
  const s = strategyFrontend(detailStrategy({holdings: [pos()]})); s.S.me.markets = markets; await s.viewStrategy(42); await flush();
  const side = s.root.querySelector('#main').innerHTML;
  assert.match(side, /<span>Cost \+ fee \$9\.41<\/span>/); assert.match(side, /<span data-close="[^"]+" data-form="settles" data-cap="1">Settles Jan 1[56], \d\d:\d\d [^<\s]+<\/span>/);
  assert.match(side, /1 open position at cost \+ fees \$9\.41/);
  // The dashboard's expiry column names the zone too.
  const g = frontend({fetchImpl: () => response(dashboardData({open_positions: [dashboardPosition(1, {market_close_time: '2030-01-15T17:30:00Z'})]}))});
  await g.viewDashboard();
  assert.match(g.root.querySelector('.position-expiry-cell time').textContent, /^Jan 1[56], \d\d:\d\d [^\s]+$/);
  // The row's mode pill drops its fill, so its light text must change too or LIVE reads as blank.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.position-mode \.mk\.live \{ color: var\(--signal\); \}/);
  // Track record: the calendar-day count is named, not "Days of history" beside "over 1 day".
  const m = {trades: 2, wins: 1, losses: 1, label: 'Kalshi demo', net_pnl: -0.03, fees: 0.12, monthly: [], strategies: [], curve: [], days: 2,
    sample: {level: 'thin', edge: 'unclear', text: 'Too early.'}};
  assert.match(g.trackRecordPanel(m, 'demo', {min_sharpe_days: 14, min_trades: 30}), /<dt>Calendar days \(UTC\)<\/dt><dd>2<\/dd>/);
  // An empty paper record whose closed trades were all instant fills doesn't claim none closed.
  const left = g.trackRecordPanel({trades: 0, label: 'Paper', excluded_instant_fills: 8}, 'paper', {min_sharpe_days: 14, min_trades: 30});
  assert.match(left, /<h3>No paper trades in the record yet<\/h3>/); assert.match(left, /8 instant-fill paper trades left out/);
});
test('Meridian: an open ETH, SOL or XRP position names its contract as Bitcoin\'s does, with its own strike to the last decimal', async () => {
  // "ETH 5pm" named the coin and an hour. A daily ladder contract fills its own strike in for "a set price", as its rules
  // read it (an XRP strike runs to four decimals); a 15-minute one says up or down.
  const pos = (ticker) => ({title: 'Drift', ticker, side: 'yes', qty: 2, entry_price: .4, entry_fee: .02, cost: .82, unrealized: null,
    mode: 'paper', opened_at: '2026-10-25T08:00:00Z', market_close_time: '2030-01-15T17:30:00Z'});
  const f = frontend({fetchImpl: path => path === '/api/deployments'
    ? response({deployments: [], open_positions: ['KXETHD-26OCT2717-T3999.99', 'KXSOLD-26OCT2717-T189.99', 'KXXRPD-26OCT2717-T2.4599',
      'KXETH15M-26OCT271715-15', 'KXSOL15M-26OCT271715-15', 'KXXRPD-26OCT2717'].map(pos)}) : response({})});
  f.S.me.markets = [{key: 'eth_daily', series: 'KXETHD', label: 'Ethereum above a set price at 5pm ET', close_hour_et: 17},
    {key: 'sol_daily', series: 'KXSOLD', label: 'Solana above a set price at 5pm ET', close_hour_et: 17},
    {key: 'xrp_daily', series: 'KXXRPD', label: 'XRP above set price at 5pm ET', close_hour_et: 17},
    {key: 'eth15m', series: 'KXETH15M', label: 'Ethereum up or down in 15 minutes'}, {key: 'sol15m', series: 'KXSOL15M', label: 'Solana up or down in 15 minutes'}];
  await f.viewDeploy(); await flush(); await flush();
  const names = [...f.root.querySelector('#openpos').innerHTML.matchAll(/<td class="pos-name" data-lab="Market"><a [^>]*>([^<]*)<\/a>/g)].map(m => m[1]);
  assert.deepEqual(names, ['Ethereum above $3,999.99 at 5pm ET', 'Solana above $189.99 at 5pm ET', 'XRP above $2.4599 at 5pm ET',
    'Ethereum up or down in 15 minutes', 'Solana up or down in 15 minutes', 'XRP above set price at 5pm ET']);
});


test('autopilot walk (Meridian): the last move says what and when, the pill says what it is doing, the pulse never reads Idle over research', () => {
  const f = frontend();
  const t = (text) => f.apMoveText({text, at: new Date().toISOString()});
  assert.equal(t('Autopilot deployed **Lean into it** on paper.'), 'Deployed Lean into it on paper');
  assert.equal(t('Autopilot is ON: the agent may research, deploy and tune paper strategies'), 'Autopilot switched on');
  const paper = {label: 'Autopilot · paper'}, live = {label: 'Autopilot · LIVE'};
  const ap = {autopilot: true, mode: 'paper', research: {active: []}, paper_running: 0};
  assert.equal(f.apPillLabel({...ap, research: {active: ['Bitcoin 15-minute']}}, paper), 'Autopilot · researching');
  assert.equal(f.apPillLabel({...ap, paper_running: 1}, paper), 'Autopilot · 1 on paper');
  assert.equal(f.apPillLabel({...ap, mode: 'live', paper_running: 1}, live), 'Autopilot · LIVE');
  f.S.ap = {...ap, research: {active: ['Bitcoin 15-minute']}};
  assert.equal(f.apIdleLine(), 'Researching Bitcoin 15-minute');
  f.S.ap = {...ap, autopilot: false, mode: 'off'};
  assert.match(f.apIdleLine(), /^Off: it acts only when you message it/);
  f.S.ap = ap;
  assert.equal(f.apIdleLine(), 'Idle');
});

test('autopilot (Meridian): the market it researches reads by its label, never a raw key or series', () => {
  const f = frontend();
  f.S.me.markets = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin up or down in 15 minutes'}, {key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET'},
    {key: 'kxhighchi', series: 'KXHIGHCHI', label: 'Chicago high temp'}];
  const ap = {autopilot: true, mode: 'paper', research: {active: []}, paper_running: 0};
  // A listed market reads by its full label, as Billing's research lines and every position name it, by key,
  // series or label alike; a key only the app knows (eth15m, not in this catalog) by its short one.
  f.S.ap = {...ap, research: {active: ['btc15m', 'KXBTCD', 'kxhighchi', 'eth15m']}};
  assert.equal(f.apIdleLine(), 'Researching Bitcoin up or down in 15 minutes · Bitcoin above a set price at 5pm ET · Chicago high temp · ETH 15-min up/down');
  f.S.ap = {...ap, research: {active: ['Bitcoin 15-minute', 'kxgone', "a market it’s still picking"]}};
  assert.equal(f.apIdleLine(), 'Researching Bitcoin 15-minute · an unlisted market');
  // The server sends a listed market's catalog label; it reads as it is.
  f.S.ap = {...ap, research: {active: ['Bitcoin above a set price at 5pm ET']}};
  assert.equal(f.apIdleLine(), 'Researching Bitcoin above a set price at 5pm ET');
  // The story quotes the same list; the panel says it the same way, and so does the research figure.
  const d = {...ap, research: {active: ['btc15m', 'KXBTCD'], tested_7d: 3, passed_7d: 0}, story: ["Right now it's researching btc15m and KXBTCD."]};
  const box = new Element('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl>';
  f.apUpdate(box, d);
  assert.match(box.querySelector('#apf-story').innerHTML, /<p>Right now it\S{1,6}s researching Bitcoin up or down in 15 minutes and Bitcoin above a set price at 5pm ET\.<\/p>/);
  f.apUpdate(box, {...d, story: []});
  assert.match(box.querySelector('#apf-stats').innerHTML, /Researching Bitcoin up or down in 15 minutes · Bitcoin above a set price at 5pm ET/);
  assert.doesNotMatch(box.querySelector('#apf-stats').innerHTML + box.querySelector('#apf-story').innerHTML, /BTC 15-min|BTC above/);
  assert.doesNotMatch(source, /esc\(\(d\.story && d\.story\[0\]\)|\(d\.story \|\| \[\]\)\.map|\[\.\.\.new Set\(d\.research\.active\)\]/);
});

test('autopilot (Meridian): the collapsed pill sits in the masthead, never floating over the page', () => {
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  // Only the open panel is fixed; the pill is a masthead control in the page's flow.
  assert.match(css, /\n\.apf \{ position: relative; flex: none;/);
  assert.deepEqual([...css.matchAll(/^\.apf[^{]*\{[^}]*position: fixed/gm)].map((m) => m[0].split('{')[0].trim()), ['.apf.open']);
});

test('autopilot walk (Meridian): the since strip counts the research sessions the autopilot started', () => {
  const f = frontend();
  f.S.me.user.autopilot = true;
  const d = {deployments: [], since: {at: '2026-10-25T08:00:00+00:00', first: false, books: {}, passed: {n: 0, items: []},
    autopilot: {research: 2, set_risk: 1}, runs: {}}};
  assert.match(f.sinceStrip(d, '#dash-paused'), /It started 2 research sessions, made 1 other change\./);
});

test('a Deploy poll that reads the same board repaints nothing, and repaints what changed', async () => {
  const dep = {id: 1, strategy_id: 101, title: 'Strategy 1', market: 'btc15m', mode: 'paper', status: 'running', stake: 5,
    max_positions: 2, backtest: {out_of_sample: {pnl: 12}}, created_at: '2026-10-17T10:00:00Z', realized_pnl: 3,
    unrealized_pnl: null, closed_trades: 1, open_positions: 1, curve: []};
  const pos = {title: 'Strategy 1', ticker: 'KXBTC15M-T1', side: 'yes', qty: 2, entry_price: .4, entry_fee: .02, unrealized: null,
    market_close_time: '2026-10-25T17:30:00Z', mode: 'paper'};
  let board = {deployments: [dep], open_positions: [pos]}, reads = 0;
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/deployments'); reads++; return response(board); }});
  await f.viewDeploy(); await flush(); await flush();
  const regions = ['#dfigs', '#deps', '#openpos'].map(sel => f.root.querySelector(sel));
  const first = regions.map(el => el.writes);
  const tick = f.intervals.get(f.S.timers.at(-1));
  tick(); await flush(); await flush();
  assert.equal(reads, 2); assert.deepEqual(regions.map(el => el.writes), first);
  board = {deployments: [{...dep, realized_pnl: 4.5, closed_trades: 2}], open_positions: []};  // a trade closed
  tick(); await flush(); await flush();
  assert.equal(reads, 3); assert.deepEqual(regions.map((el, i) => el.writes - first[i]), [1, 1, 1]);
  assert.match(f.root.querySelector('#openpos').innerHTML, /No open positions/);
});

// The autopilot feed under a slow or failing server: a read that lands after a newer one never paints
// a move twice, and a first load that fails says so instead of leaving the feed blank.
test('the autopilot feed never repeats a move and says when it could not load', async () => {
  let reply = () => response({messages: [{id: 1, role: 'user', content: 'one', created_at: '2026-10-17T10:00:00Z'}, {id: 2, role: 'user', content: 'two', created_at: '2026-10-17T10:01:00Z'}]});
  const f = frontend({fetchImpl: path => { assert.match(path, /^\/api\/chat\?after=\d+$/); return reply(path); }});
  const box = f.document.createElement('div'); box.innerHTML = '<ol id="apf-messages"></ol>';
  const moves = () => box.querySelector('#apf-messages').children.filter(li => li.classes.has('apf-you')).length;
  assert.equal(await f.apLoadChat(box, true), true);
  assert.equal(moves(), 2);
  // An older read that only lands now still carries move 2.
  reply = () => response({messages: [{id: 2, role: 'user', content: 'two', created_at: '2026-10-17T10:01:00Z'}, {id: 3, role: 'user', content: 'three', created_at: '2026-10-17T10:02:00Z'}]});
  await f.apLoadChat(box);
  assert.equal(moves(), 3);
  const empty = f.document.createElement('div'); empty.innerHTML = '<ol id="apf-messages"></ol>';
  reply = () => response({error: "Something went wrong on our side. It’s been logged."}, 500);
  assert.equal(await f.apLoadChat(empty, true), false);
  assert.match(empty.querySelector('#apf-messages').innerHTML, /Couldn’t load the autopilot’s activity\. Retrying\./);
});

test('back online, a dashboard poll sitting out its back-off reads at once and clears its note', async () => {
  let down = false, equity = 1000;
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return down ? response({error: "Something went wrong on our side. It’s been logged."}, 500) : response(staleDashboard(equity));
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush(); await flush();
  const tick = f.intervals.get(f.S.timers[0]);
  const reads = () => f.requests.filter(r => r.path === '/api/dashboard').length;
  const note = () => f.root.querySelector('#dash-stale').textContent;
  down = true;
  await pollStep(f, tick, 15000); await pollStep(f, tick, 20000); await pollStep(f, tick, 15000);  // two failures in a row
  const before = reads();
  await pollStep(f, tick, 20000);
  assert.equal(reads(), before);  // sitting out its back-off
  assert.match(note(), /Last updated .* ago, retrying/);
  down = false; equity = 1234.5;
  (f.windowListeners.get('online') || []).forEach(fn => fn());
  await settleRead(f);
  assert.equal(reads() - before, 1);
  assert.equal(note(), ''); assert.match(f.root.querySelector('#main').innerHTML, /\$1,234\.50/);
});

test('a boot whose account read fails offers Try again instead of sending a signed-in user to sign in', async () => {
  for (const me of [response({error: "Something went wrong on our side. It’s been logged."}, 500), {ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected end of JSON input'); }}]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/me'); return me; }});
    f.S.me = null;
    await f.render(); await flush(); await flush();
    assert.deepEqual(f.navigations, []);
    assert.ok(f.root.querySelector('#bootretry'));
    assert.match(f.root.innerHTML, /Tau is taking longer than usual to load/);
  }
});

test('Meridian: a page change names the tab and puts keyboard focus on the new page\'s heading, the first page and a repaint do not', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/deployments') return response({deployments: [], open_positions: []});
    return response({});
  }});
  f.location.pathname = '/deploy';
  await f.render(); await flush(); await flush();
  assert.equal(f.document.title, 'Deploy · Tau');
  assert.equal(f.document.activeElement, f.document.body);  // the first page of a visit: the browser's own start
  await f.render(); await flush(); await flush();
  assert.equal(f.document.activeElement, f.document.body);  // the same page again
  f.location.pathname = '/billing';
  await f.render(); await flush(); await flush();
  const heading = f.root.querySelector('main h1');
  assert.ok(f.document.activeElement === heading); assert.equal(heading.focusOptions.preventScroll, true);
});

test('Meridian: a dashboard poll that redraws the board leaves focus on the page heading it had', async () => {
  let data = dashboardData();
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/dashboard'); return response(data); }});
  await f.viewDashboard(); await flush();
  const board = f.root.querySelector('#boardbody'), writes = board.writes, heading = f.root.querySelector('main h1');
  heading.focus();
  data = dashboardData({demo: {equity: 2300}, live: {connected: true, balance: 41.5}});
  f.intervals.get(f.S.timers.at(-1))(); await flush();
  assert.equal(board.writes, writes + 1, 'the board was redrawn');
  const next = f.root.querySelector('main h1');
  assert.notEqual(next, heading); assert.equal(heading.isConnected, false);
  assert.ok(f.document.activeElement === next, 'focus is on the new heading, not dropped to the page');
  assert.equal(next.getAttribute('tabindex'), '-1'); assert.equal(next.focusOptions.preventScroll, true);
  f.clearTimers();
});

test('Meridian: the autopilot pill keeps keyboard focus through a status repaint, and an unchanged read repaints nothing', () => {
  const f = frontend();
  const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
  f.renderAutopilot(box, {mode: 'off'});
  box.querySelector('.apf-pill').focus();
  const writes = box.writes;
  f.renderAutopilot(box, {mode: 'off'});
  assert.equal(box.writes, writes);
  f.renderAutopilot(box, {mode: 'paper', autopilot: true});
  assert.equal(box.writes, writes + 1);
  assert.equal(f.document.activeElement, box.querySelector('.apf-pill'));
  assert.match(box.querySelector('.apf-pill').innerHTML, /paper/);
});

// -- Spend: what each charge was for, how fast credits go, and what happens when they run out ------

test('Billing shows the spend pace, what spent it, and what each line was for, never a model id', async () => {
  const f = billingPage(cardedBilling({spent_24h: 1.4, spent_7d_by: {research: 4.2, autopilot_research: 5.1, autopilot_review: 0.5, chat: 0, other: 0}, min_run_balance: 1,
    ledger: [{kind: 'usage', amount: -0.2104, memo: 'Autopilot research · Claude Opus 4.6', item: 'Autopilot research', model: 'Claude Opus 4.6', created_at: '2026-10-25T17:00:00Z'}]}));
  await f.viewBilling(); await flush();
  const figs = f.root.querySelector('#bfigs').innerHTML;
  assert.match(figs, /Spent, last 7 days[\s\S]*\$9\.80[\s\S]*\$1\.40 in the last 24 hours\u00a0· \$47\.58 all time/);
  assert.equal(f.root.querySelector('#bsplit').innerHTML, 'Last 7 days: autopilot research $5.10\u00a0· your research sessions $4.20\u00a0· autopilot check-ins $0.50.');
  const row = f.root.querySelector('.t-ledger tbody tr').innerHTML;
  assert.match(row, /Autopilot research<div class="sub-fig">Claude Opus 4\.6<\/div>/);
  assert.match(row, /<time datetime="2026-10-25T17:00:00Z">[^<]*\d\d:\d\d [A-Z+\-0-9:]+<\/time>/);  // a time, with its zone
  assert.doesNotMatch(f.root.querySelector('#main').innerHTML, /anthropic|list price/i);
  assert.doesNotMatch(f.root.querySelector('#main').innerHTML, /role="status"/);  // enough credits: no out-of-credits notice
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.bill-detail \.t-dep \{ min-width: 0; \}/);  // Amount stays in view beside Add credits
});

test('Billing under the research floor says research stopped and the next step', async () => {
  const f = billingPage(cardedBilling({balance: 0.4, min_run_balance: 1, auto_reload: false}));
  f.S.me.user.autopilot = true;
  await f.viewBilling(); await flush();
  const main = f.root.querySelector('#main').innerHTML;
  assert.match(main, /You have \$0\.40 in credits\. New research needs at least \$1\.00 to start, so none is starting and autopilot is paused\. Add credits here, or turn on auto-reload so it doesn’t stop again\. Autopilot picks up again on its own\./);
  assert.match(f.root.querySelector('#bfigs').innerHTML, /neg/);  // the balance reads as a problem
  assert.match(f.root.querySelector('#autorel-when').innerHTML, /^<b>Off\.<\/b> Below \$1\.00 no new research starts and autopilot pauses; a session already running stops at \$0\./);
  const on = billingPage(cardedBilling({balance: -0.3, min_run_balance: 1}));
  await on.viewBilling(); await flush();
  assert.match(on.root.querySelector('#main').innerHTML, /You’re out of credits\.[\s\S]*Auto-reload is on but hasn’t topped you up: add credits here, or check your card\./);
});

test('run-until-stopped says what an hour costs at recent rates, how long the balance covers, and when it stops', async () => {
  let f = researchFrontend([], {estimate: {yours: 0.42, sessions: 4, typical: {}, per_hour: {yours: 1.25, typical: {}}}});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 23.4, auto_reload: null};
  await f.viewResearch(); await flush();
  const cost = () => f.root.querySelector('#rcost');
  assert.equal(cost().textContent, 'Each round of ideas usually costs about $0.42 (your recent sessions); it keeps starting new rounds until you stop it. '
    + 'At recent rates it costs about $1.25 an hour (your recent sessions). Your $23.40 covers about 19 hours. It stops by itself if your credits run out.');
  f = researchFrontend([], {estimate: {yours: null, sessions: 0, typical: {}, per_hour: {yours: null, typical: {offline: 3}}}});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 100, auto_reload: {amount: 20, charge: 21.1, threshold: 5}};
  await f.viewResearch(); await flush();
  assert.equal(cost().textContent, 'At recent rates it costs about $3.00 an hour (recent sessions on this model). Your $100.00 covers about 33 hours. Auto-reload adds $20.00 when your balance falls to $5.00, charging your card $21.10.');
});

test('the autopilot card puts credits left and the only limit beside its spend, and a credits pause says how much it needs', async () => {
  const week = {research_credits: 0.5, tested: 12, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0, checkin_credits: 0.42, credits_left: 23.4, runway_days: 6.1};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData());
    if (path === '/api/autopilot/status') return response({...apStatus, week});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 23.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = true;
  await f.viewDashboard(); await flush();
  f.S.ap = {...apStatus, week}; f.paintDashAp();
  const card = f.root.querySelector('#dash-ap').innerHTML;
  assert.match(card, /<dt>Credits spent on research<\/dt><dd>\$0\.50 <small>plus \$0\.42 on its check-ins<\/small><\/dd>/);
  assert.match(card, /Credits left: <b>\$23\.40<\/b>, about 6 days at this week’s pace\. It has no daily spending cap: it uses credits until your balance is under \$1\.00, then pauses\./);
  f.S.ap = {...apStatus, week, billing_blocked: true, billing_reason: 'credits'}; f.paintDashAp();
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /Paused: starting research needs \$1\.00 in credits\. <a href="\/billing">Add credits<\/a> and it picks up on its own\./);
  f.clearTimers();
});

test('a credits pause puts the week line in the paused state, and the next status read after a top-up puts it back', async () => {
  const week = {research_credits: 0.5, tested: 12, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0, checkin_credits: 0, credits_left: 0.4, runway_days: 0.4};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData());
    if (path === '/api/autopilot/status') return response({...apStatus, week});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 0.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = true;
  await f.viewDashboard(); await flush();
  f.S.ap = {...apStatus, week, billing_blocked: true, billing_reason: 'credits'}; f.paintDashAp();
  const line = () => f.root.querySelector('#dash-ap .ap-week-left').innerHTML;
  assert.equal(line(), 'Credits left: <b>$0.40</b>. Research is paused until you add credits: a session needs $1.00 to start. <a href="/billing">Billing</a> lists every charge.');
  assert.doesNotMatch(line(), /then pauses|this week’s pace|no daily spending cap/);
  f.S.ap = {...apStatus, week, billing_blocked: true, billing_reason: 'card'}; f.paintDashAp();
  assert.match(line(), /Research is paused until you add a payment method\./);
  f.S.ap = {...apStatus, week: {...week, credits_left: 20.4, runway_days: 17}}; f.paintDashAp();
  assert.match(line(), /^Credits left: <b>\$20\.40<\/b>, about 17 days at this week’s pace\. It has no daily spending cap: it uses credits until your balance is under \$1\.00, then pauses\./);
  f.clearTimers();
});

test('the autopilot switch card says it would wait for credits when the balance is already under what research needs', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData());
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, credit_balance: 0.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = false; f.S.ap = null;
  await f.viewDashboard(); await flush();
  assert.equal(f.root.querySelector('#dash-ap .apcard-cost').innerHTML, 'It uses your credits while it’s on. You have $0.40, under the $1.00 a research session needs to start, so it waits until you <a href="/billing">add credits</a>. Turn it off any time.');
  f.clearTimers();
});

// The bell, the reconciliation warning and the demo key line: what a once-a-day reader needs to trust.
const bellNotes = () => ({unread: 1, items: [
  {id: 3, kind: 'paused', body: '“A” was paused automatically.', link: '/strategies/3', created_at: new Date(Date.now() - 2 * 3600e3).toISOString(), read: false},
  {id: 2, kind: 'comment', body: 'Ana commented on your post.', link: '/community', created_at: new Date(Date.now() - 3 * 86400e3).toISOString(), read: true},
]});
const bellFrontend = (notifications) => frontend({notifications, fetchImpl: path => {
  if (path === '/api/dashboard') return response(dashboardData());
  if (path === '/api/notifications/read') return response({ok: true});
  if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
  throw new Error('Unexpected offline request: ' + path);
}});

test('a bell that filled up while the user was away opens with what it holds, by kind, until it is closed', async () => {
  // A week away: five strategies put on paper, one paused, one forward-test pass, one unknown kind.
  const at = (h) => new Date(Date.now() - h * 3600e3).toISOString();
  const items = [['passed', 3], ['paused', 20], ['deployed', 30], ['deployed', 50], ['deployed', 70], ['deployed', 90], ['deployed', 110]]
    .map(([kind, h], i) => ({id: 20 - i, kind, body: `${kind} ${i}`, link: `/strategies/${i}`, created_at: at(h), read: false}));
  const f = bellFrontend({unread: 8, items, unread_kinds: {deployed: 5, paused: 1, passed: 1, digest: 1}});
  await f.viewDashboard(); await flush(); await flush();
  const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig');
  const list = wrap.querySelector('#bell-list');
  assert.match(list.innerHTML, /^<p class="bell-sum">8 new: 5 strategies put on paper\u00a0· 1 paused\u00a0· 1 passed its paper test\u00a0· 1 other<\/p>/);
  assert.equal(wrap.querySelectorAll('.notif').length, 7);  // every line still listed under it
  await trig.onclick({stopPropagation() {}});
  assert.ok(list.querySelector('.bell-sum'), 'the summary stays while the list is open');
  await trig.onclick({stopPropagation() {}});  // close: read now, so the summary goes with the marks
  assert.ok(wrap.querySelectorAll('.bell-sum').every((e) => e.removed));
  // A few new ones need no summary, nor does a list with nothing new.
  for (const d of [{unread: 3, items: items.slice(0, 3), unread_kinds: {passed: 1, paused: 1, deployed: 1}},
    {unread: 0, items: items.map((n) => ({...n, read: true})), unread_kinds: {}}]) {
    const g = bellFrontend(d);
    await g.viewDashboard(); await flush(); await flush();
    assert.equal(g.root.querySelector('.bell-sum'), null);
  }
});

test('the bell keeps new items marked while it is open, says how many, and clears them on close', async () => {
  const f = bellFrontend(bellNotes());
  await f.viewDashboard(); await flush(); await flush();
  const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig');
  assert.equal(wrap.querySelector('.bell-head .bell-new').textContent, '1 new');
  assert.equal(wrap.querySelectorAll('.notif.unread').length, 1);
  await trig.onclick({stopPropagation() {}});
  // Opening reads them on the server and drops the dot, but the reader still sees which ones are new.
  assert.equal(postRequests(f).filter(({path}) => path === '/api/notifications/read').length, 1);
  assert.equal(wrap.querySelector('.bell-dot').hidden, true);
  assert.equal(wrap.querySelectorAll('.notif.unread').length, 1);
  assert.match(wrap.querySelector('.notif.unread').innerHTML, /^<span class="vh notif-new">New: <\/span>“A” was paused/);  // not colour alone
  await trig.onclick({stopPropagation() {}});  // close
  assert.equal(wrap.querySelectorAll('.notif.unread').length, 0);
  assert.ok(wrap.querySelectorAll('.bell-new').every((e) => e.removed));
  assert.ok(wrap.querySelectorAll('.notif-new').every((e) => e.removed));
});

test('a bell item older than a day shows its day, clock and zone, and every item its full time on hover', async () => {
  const f = bellFrontend(bellNotes());
  await f.viewDashboard(); await flush(); await flush();
  const [recent, older] = f.root.querySelectorAll('#bell-list time');
  assert.equal(recent.textContent, '2h ago');
  // "Oct 23, 14:05 EDT": not a bare "Oct 23", nor a clock that doesn't say whose (walk 2026-10-31).
  assert.match(older.textContent, /^[A-Z][a-z]{2} \d{1,2}, \d\d:\d\d (?:[A-Z]{2,5}|GMT[+-]\d{1,2}(?::\d\d)?)$/);
  for (const t of [recent, older]) { assert.ok(t.getAttribute('datetime')); assert.match(t.getAttribute('title'), /\d\d:\d\d/); }
  // Nothing new: no count, no marks.
  const g = bellFrontend({unread: 0, items: bellNotes().items.map((n) => ({...n, read: true}))});
  await g.viewDashboard(); await flush(); await flush();
  assert.equal(g.root.querySelector('.bell-new'), null); assert.equal(g.root.querySelectorAll('.notif.unread').length, 0);
});

test('Overview\'s reconciliation warning names the contracts and where to compare them; Tau has no Portfolio page', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData({live: {connected: true, balance: 50, open_positions: 2},
      reconcile: [{ticker: 'KXBTCD-26OCT2617-T100000', kind: 'untracked'}, {ticker: 'KXETHD-26OCT2617-T2600', kind: 'size_mismatch'}]}));
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const board = f.root.querySelector('#boardbody').innerHTML;
  assert.match(board, /2 live positions disagree with Kalshi \(KXBTCD-26OCT2617-T100000, KXETHD-26OCT2617-T2600\)\. Compare <a href="#dash-open">Tau’s open positions<\/a> with the positions in your Kalshi account\./);
  assert.doesNotMatch(board, /Portfolio/);
  assert.ok(f.root.querySelector('#dash-open'), 'the link lands on the open positions list');
});

test('Funds says when the demo key\'s balance was read, as it does for Kalshi cash', async () => {
  const read = new Date(Date.now() - 5 * 60000).toISOString();
  for (const [at, said] of [[read, /\(Kalshi demo account cash \$25\.00, read 5m ago\)<\/p>/], [undefined, /\(Kalshi demo account cash \$25\.00\)<\/p>/]]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds');
      return response({...funds(), kalshi_dev: {connected: true, key_id: 'DEVK…1234', balance: 25, balance_at: at}}); }});
    await f.viewFunds();
    assert.match(f.root.querySelector('#main').innerHTML, said);
  }
});

// Settings' email switch: it shows the stored state from /api/me, names what it stops and what always
// comes (perps safety alerts), and saves through /api/email-preferences only.
test('Settings email switch shows the stored state and says what it stops and what still comes', async () => {
  for (const [stored, checked, said] of [[undefined, true, /^On\. Tau emails you about replies to your posts, mentions of your @name, new community posts \(at most one email every 4 hours\), and a paper strategy that’s ready for live trading\.$/],
    [false, true, /^On\./], [true, false, /^Off\. Tau doesn’t email you about replies to your posts, mentions of your @name, new community posts, or a paper strategy that’s ready for live trading\. The bell in Tau still shows/]]) {
    const f = frontend({fetchImpl: path => { throw new Error('Settings reads nothing on open: ' + path); }});
    f.S.me.user = {...f.S.me.user, email: 'owner@example.invalid', email_opt_out: stored};
    await f.viewSettings();
    const sw = f.root.querySelector('#email-optional');
    assert.equal(sw.checked, checked); assert.equal(sw.getAttribute('role'), 'switch');
    assert.match(f.root.querySelector('#email-state').textContent, said);
    const section = f.root.querySelector('.email-settings').innerHTML;
    assert.match(section, /Sent to owner@example\.invalid/);
    assert.match(section, /<b>Always sent:<\/b> safety alerts about a Bitcoin perps account you trade through Tau: a position that doesn’t match Tau’s orders, a position near liquidation, or heavy margin use\. They protect real money, so this switch doesn’t stop them\./);
    assert.match(section, /this switch doesn’t stop them\. Also an email when an auto-reload of your credits fails, since research pauses when they run out\.<\/p>/);
    assert.equal(postRequests(f).length, 0);
  }
});

test('Settings email switch saves off and on, and a failed save puts the switch back', async () => {
  let fail = false;
  const f = frontend({fetchImpl: (path, options) => {
    assert.equal(path, '/api/email-preferences');
    if (fail) return response({error: 'Synthetic preference outage'}, 503);
    return response({ok: true, email_opt_out: JSON.parse(options.body).email_opt_out});
  }});
  await f.viewSettings();
  let sw = f.root.querySelector('#email-optional');
  assert.equal(sw.checked, true);
  sw.checked = false; await sw.onchange(); await flush();
  assert.deepEqual(postRequests(f).map(r => [r.path, JSON.parse(r.options.body), r.options.headers['X-Recursive']]),
    [['/api/email-preferences', {email_opt_out: true}, '1']]);
  assert.equal(f.S.me.user.email_opt_out, true); assert.equal(sw.checked, false); assert.equal(sw.disabled, false);
  assert.match(f.root.querySelector('#email-state').textContent, /^Off\./);
  assert.match(f.root.querySelector('#email-flash').innerHTML, /Optional email is off\. Safety alerts still come\./);
  sw.checked = true; await sw.onchange(); await flush();
  assert.deepEqual(JSON.parse(postRequests(f)[1].options.body), {email_opt_out: false});
  assert.equal(f.S.me.user.email_opt_out, false); assert.match(f.root.querySelector('#email-state').textContent, /^On\./);
  fail = true;
  sw.checked = false; await sw.onchange(); await flush();
  assert.equal(f.S.me.user.email_opt_out, false); assert.equal(sw.checked, true);  // nothing changed on the server
  assert.match(f.root.querySelector('#email-state').textContent, /^On\./);
  assert.match(f.root.querySelector('#email-flash').innerHTML, /Synthetic preference outage/);
});

// The agent's answers often carry a table: it renders as one (cells escaped, in a box that scrolls
// sideways on a phone), and a half-streamed one with no |---| rule yet stays literal text.
test('feed markdown renders a table and leaves an unfinished one literal', () => {
  const f = frontend();
  const table = f.feedMd('Here.\n\n| Strategy | Book |\n|---|:---:|\n| <b>BTC</b> fade | **paper** |\n| ETH | demo |\nAfter');
  assert.match(table, /<div class="md-table"><table><thead><tr><th>Strategy<\/th><th>Book<\/th><\/tr><\/thead><tbody><tr><td>&lt;b&gt;BTC&lt;\/b&gt; fade<\/td><td><b>paper<\/b><\/td><\/tr><tr><td>ETH<\/td><td>demo<\/td><\/tr><\/tbody><\/table><\/div><p>After<\/p>/);
  assert.doesNotMatch(f.feedMd('| Strategy | Book |'), /<table/);
});

// The panel's chat, opened, with a scripted server. `chat` answers each feed read.
function agentPanel(fetchImpl, chat) {
  const f = frontend({storage: new Map([['tau_ap_open', '1']]), fetchImpl: (path, options) => {
    if (path.startsWith('/api/chat?')) return response({messages: chat(), agent_busy: false});
    if (path === '/api/models') return response({models: [], default: ''});
    return fetchImpl(path, options);
  }});
  f.S.me = {...f.S.me, user: {...(f.S.me && f.S.me.user), autopilot: false}};
  const box = f.document.createElement('div'); box.id = 'autopilot-float'; f.document.body.appendChild(box);
  f.renderAutopilot(box, null);
  return {f, box};
}

test('the agent chat sends a message once while it is in flight, and says a failed send above the composer', async () => {
  const pending = deferred(); let posts = 0, refuse = false;
  const {box} = agentPanel((path, options) => {
    assert.equal(path, '/api/chat'); assert.equal(options.method, 'POST'); posts++;
    return refuse ? response({error: "That's a lot of messages this hour. Give the agent a minute."}, 429) : pending.promise;
  }, () => []);
  await flush();
  const form = box.querySelector('#apf-composer'), ta = box.querySelector('#apf-msg'), err = box.querySelector('#apf-err');
  ta.value = 'What is going on?';
  form.onsubmit({preventDefault() {}}); form.onsubmit({preventDefault() {}}); form.onsubmit({preventDefault() {}});
  await flush();
  assert.equal(posts, 1);  // Enter pressed again during a slow send no longer sends it again
  pending.resolve(response({id: 7})); await flush(); await flush();
  assert.equal(ta.value, ''); assert.equal(err.hidden, true);
  refuse = true; ta.value = 'Again';
  await form.onsubmit({preventDefault() {}}); await flush();
  assert.equal(posts, 2);
  assert.equal(err.hidden, false);  // in the panel, by the composer, not at the top of the page under it
  assert.equal(err.textContent, "That's a lot of messages this hour. Give the agent a minute.");
  assert.equal(ta.value, 'Again');  // kept, to send again
});

test('a proposal says what Approve does and in which book, and one decision locks both buttons', async () => {
  const at = '2026-10-17T10:00:00Z';
  let lines = [
    {id: 1, role: 'system', content: 'Proposed to pause BTC daily close range.', created_at: at, proposal_id: 4, proposal_kind: 'pause', proposal_status: 'pending', deployment_mode: 'live'},
    {id: 2, role: 'system', content: 'Proposed deploying ETH drift on paper.', created_at: at, proposal_id: 5, proposal_kind: 'deploy', proposal_status: 'pending'},
    {id: 3, role: 'system', content: 'Autopilot paused BTC 15m fade.', created_at: at, proposal_id: 6, proposal_kind: 'pause', proposal_status: 'applied', deployment_mode: 'paper'},
    {id: 4, role: 'system', content: "The agent hit an error and didn't answer. Send your message again, or try in a minute.", created_at: at},
  ];
  const pending = deferred(), decided = [];
  const {f, box} = agentPanel((path) => { decided.push(path); return path === '/api/proposals/9/approve' ? response({review_required: true, review_url: '/funds?perps_proposal=9'}) : pending.promise; }, () => lines);
  await flush(); await flush();
  const msgs = box.querySelector('#apf-messages'), [live, paper, done, failed] = msgs.children.filter(li => li.classes.has('apf-act'));
  assert.match(live.innerHTML, /Asks to pause/);
  assert.match(live.querySelector('.apf-ask').textContent, /pauses this strategy, which runs LIVE, with real money in your Kalshi account/);
  assert.ok(live.querySelector('.apf-ask').classes.has('live'));
  assert.match(paper.innerHTML, /Asks to put on paper/); assert.match(paper.innerHTML, /Nothing trades real money/);
  assert.match(done.innerHTML, /Paused/); assert.equal(done.querySelector('.apf-ask'), null); assert.equal(done.querySelector('[data-decide]'), null);
  assert.match(failed.innerHTML, /No answer/); assert.doesNotMatch(failed.innerHTML, /Reviewed/);
  const click = msgs.listeners.get('click');
  const [approve, decline] = live.querySelectorAll('button');
  const sent = click({target: approve}); await flush();
  assert.equal(approve.disabled, true); assert.equal(decline.disabled, true);  // the other one can't be sent too
  await click({target: decline});
  assert.deepEqual(decided, ['/api/proposals/4/approve']);
  lines = lines.map(m => m.id === 1 ? {...m, proposal_status: 'applied'} : m);
  pending.resolve(response({ok: true})); await sent; await flush();
  assert.equal(msgs.children.filter(li => li.classes.has('apf-act'))[0].querySelector('[data-decide]'), null);
  // A Bitcoin perps live order still goes to its exact-ticket review on Approve.
  lines = [{id: 9, role: 'system', content: 'Proposed a perps order.', created_at: at, proposal_id: 9, proposal_kind: 'kalshi_perps_live', proposal_status: 'pending'}];
  await f.apLoadChat(box, true);
  const review = msgs.querySelector('[data-decide]');
  assert.equal(review.textContent, 'Review live order');
  await click({target: review}); await flush();
  assert.ok(f.navigations.includes('/funds?perps_proposal=9'), f.navigations.join());
});

test('track record (Meridian): stopped and removed strategies stay in the table and say so; profit factor and Sharpe read after fees, with a true minus', () => {
  const f = frontend();
  const th = {min_sharpe_days: 14, min_trades: 30};
  const row = (o) => ({strategy_id: 4, title: 'Fade', market: 'btc15m', trades: 12, open_trades: 0, net_pnl: -3, win_rate: 0.4,
    avg_trade: -0.25, max_drawdown: 4, last_trade_at: 1790000000, edge: 'thin', status: 'running', removed: false, ...o});
  const m = {trades: 40, wins: 16, losses: 24, label: 'Paper', net_pnl: -9, fees: 3, monthly: [], curve: [], days: 20,
    sharpe: -1.25, sortino: -2.5, psr: 0.2, profit_factor: 0.6,
    sample: {level: 'early', edge: 'unclear', text: 'Early read.'},
    strategies: [row({}), row({strategy_id: 5, title: 'Reversal', status: 'stopped'}), row({strategy_id: 6, status: 'paused'}),
      row({strategy_id: 7, title: 'Deleted strategy', market: 'high_ny', status: 'stopped', removed: true})]};
  const html = f.trackRecordPanel(m, 'paper', th);
  assert.match(html, /<h2>By strategy<\/h2><p>Removed ones included/);
  assert.match(html, /<a href="\/strategies\/5">Reversal<\/a><div class="sub-fig">Removed from paper<\/div>/);
  assert.match(html, /<a href="\/strategies\/6">Fade<\/a><div class="sub-fig">Paused<\/div>/);
  assert.match(html, /<a href="\/strategies\/4">Fade<\/a><\/td>/);  // a running one needs no label
  // A removed strategy has no page left: no dead link, and its market says which one it was.
  assert.doesNotMatch(html, /\/strategies\/7/);
  assert.match(html, /Deleted strategy<div class="sub-fig">NYC high temp · removed from paper, then deleted<\/div>/);
  // Every trade's P&L is net of fees, so the ratio isn't "gross" beside the gross-before-fees line.
  assert.match(html, /winning trades ÷ losing trades, after fees/); assert.doesNotMatch(html, /gross wins/);
  assert.match(html, /−1\.25/); assert.match(html, /Sortino −2\.50/); assert.doesNotMatch(html, />-1\.25</);
});

// A newcomer's first hour: what the card wall charges, what the dashboard says right after the switch, and
// that the paper portfolio's $1,000 is practice money.
test('Meridian card wall says saving the card charges nothing and what auto-reload will charge it, before it is saved', async () => {
  for (const [auto_reload, said] of [[true, 'Saving the card charges nothing. Auto-reload is on: when your credits fall to $5.00, we charge the card $21.10: $20.00 of credits plus the 5.5% purchase fee. You can turn it off on Billing.'],
    [false, 'Saving the card charges nothing.']]) {
    const stripe = stripeFixture();
    const f = frontend({stripeLoader: async () => stripe.Stripe, fetchImpl: path => {
      if (/^\/api\/billing(\?|$)/.test(path)) return response(billingData({configured: true, auto_reload, autoreload_threshold: 5, autoreload_amount: 20, autoreload_charge: 21.1, topup_fee_pct: 5.5}));
      assert.equal(path, '/api/billing/setup-intent'); return response({client_secret: 'synthetic-secret'});
    }});
    f.location.pathname = '/'; Object.assign(f.S.me, {needs_card: true, free_bonus: 20});
    await f.paymentGate(); await flush();
    const dlg = f.document.body.querySelector('.pay-modal');
    assert.match(dlg.querySelector('.wl-sub').innerHTML, /Save a card and we'll add \$20 in free credits\./);
    assert.doesNotMatch(dlg.innerHTML, /by the token|list price/i);
    const terms = dlg.querySelector('#pay-terms');
    assert.equal(terms.hidden, false); assert.equal(terms.textContent, said);
  }
});

test('Meridian: turning autopilot on updates the last-24-hours row at once, not only after a reload', async () => {
  const f = frontend({fetchImpl: path => {
    if (path.startsWith('/api/dashboard')) return response(dashboardData({since: {at: '2026-10-25T08:00:00+00:00', first: true,
      books: {}, passed: {n: 0, items: []}, autopilot: {}, runs: {}, own_sessions: false}}));
    if (path === '/api/settings') return response({ok: true});
    if (path === '/api/autopilot/status') return response(apStatus);
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const row = () => f.root.querySelector('#dash-since [data-since-ap]').textContent;
  assert.equal(row(), 'Off.');
  await f.root.querySelector('#dash-ap [data-apcard="on"]').onclick(); await flush(); await flush();
  assert.equal(row(), 'On. It made no changes.');
});

test('Meridian Overview says the paper portfolio is practice money', async () => {
  const f = apDashboard(dashboardData(), apStatus);
  await f.viewDashboard(); await flush();
  // Walk 2026-10-27 at 390px: "· Realized P&L, all time", "· after Kalshi fees" and "· Download trades (CSV)" each began
  // a line. Each "·" has a no-break space before it and a plain one after, so it ends its line.
  const sub = f.root.querySelector('.paper-summary .portfolio-return').innerHTML;
  assert.ok(!/ ·/.test(sub) && sub.includes('</span> · <span class="pnl-win">Since you started:</span> <span class="nobr">realized'), sub);
  assert.match(f.root.querySelector('.paper-summary').textContent, /Practice money, not real · Since you started: realized P&amp;L \+\$98\.40/);
});

// A new account's paper book read "Realized P&L, all time $0.00" and "Realized today (UTC) $0.00": results it never had.
test('Meridian Overview says a never-used paper book has no strategies yet, not $0.00 realized', async () => {
  const fresh = {total_pnl: 0, realized_pnl: 0, today_pnl: 0, open_at_cost: 0, open_cost: 0, cash: 1000, equity: 1000, closed_trades: 0, open_positions: 0};
  const f = apDashboard(dashboardData({paper: fresh}), apStatus);
  await f.viewDashboard(); await flush();
  const paper = f.root.querySelector('.paper-summary').textContent;
  assert.match(paper, /Practice money, not real\s·\s?no paper strategies yet/);
  assert.match(paper, /Today \(UTC\): paper realizedNone yet/);
  assert.doesNotMatch(paper, /Since you started|realized P&amp;L/);
  // "Open at cost + fees $0.00" read as a figure too, for a book nothing has ever been open in.
  assert.match(paper, /Open at cost \+ fees(?:<[^>]*>)*None yet/);
  assert.doesNotMatch(paper, /\$0\.00/);
  // A paper deployment with no trade closed yet has no realized figure either: "Realized P&L, all time $0.00",
  // "Realized today $0.00" and "Open at cost + fees $0.00" read as results beside Deploy's "Realized: None yet".
  const used = apDashboard(dashboardData({paper: fresh, deployments: [dashboardDeployment('paper')]}), apStatus);
  await used.viewDashboard(); await flush();
  const usedText = used.root.querySelector('.paper-summary').textContent;
  assert.match(usedText, /P&amp;L shows once a paper trade closes[\s\S]*Today \(UTC\): paper realizedNone yet[\s\S]*Open at cost \+ feesNone open/);
  assert.doesNotMatch(usedText, /Since you started|realized P&amp;L|\$0\.00/);
  // Once a trade has closed its figures are figures, a $0.00 day included.
  const traded = apDashboard(dashboardData({paper: {...fresh, closed_trades: 1, realized_pnl: 5.73, cash: 1005.73, equity: 1005.73},
    deployments: [dashboardDeployment('paper')]}), apStatus);
  await traded.viewDashboard(); await flush();
  assert.match(traded.root.querySelector('.paper-summary').textContent, /Since you started: realized P&amp;L \+\$5\.73[\s\S]*Today \(UTC\): paper realized\$0\.00[\s\S]*Open at cost \+ feesNone open/);
});

// Meridian opens a market page from Explore's ?m= link.
const OPEN_MARKET = (payload, markets) => {
  const f = frontend({search: '?m=' + encodeURIComponent(payload.ticker), fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(payload) : response({})});
  if (markets) f.S.me.markets = markets;
  f.ready = f.viewExplore().then(flush);
  return f;
};
// One contract's market page as a customer reads it: what the price means and when it was read, how
// and when it settles (in a named zone), and the reader's own positions, each money book apart.
const MARKET_PAGE = {ticker: 'KXBTCD-26OCT2617-T113499.99', series: 'KXBTCD', title: 'Bitcoin price at 5pm EDT?', sub: '$113,500 or above',
  status: 'active', yes_bid: '0.55', yes_ask: '0.57', last: '0.55', volume_24h: '15234', open_interest: '40211',
  close_time: '2026-10-26T21:00:00Z', settles_at: '2026-10-26T21:05:00Z', as_of: '2026-10-26T11:00:00Z',
  rules: 'If the BRTI average before 5 PM EDT is above 113499.99, then the market resolves to Yes.', rules_more: '',
  period_min: 1, points: [{t: 1793012400, yes: .5, vol: 3}, {t: 1793012460, yes: .52, vol: 2}],
  mine: {open: [
    {mode: 'live', strategy_id: 4, title: 'Daily close drift', side: 'yes', qty: 2, entry_price: 0.52, cost: 1.06, unrealized: 0.04, mark_ts: '2026-10-26T10:59:00Z', status: 'open', market_close_time: '2026-10-26T21:00:00Z'},
    {mode: 'paper', strategy_id: 4, title: 'Daily close drift', side: 'no', qty: 10, entry_price: 0.44, cost: 4.5, unrealized: 0.8, mark_ts: '2026-10-26T10:59:00Z', status: 'open', market_close_time: '2026-10-26T21:00:00Z'}],
  closed: [{mode: 'paper', strategy_id: null, title: null, side: 'no', qty: 8, entry_price: 0.7, cost: 5.68, status: 'closed', pnl: 0.24, exit_price: 0.75, close_reason: 'take_profit', market_close_time: '2026-10-26T21:00:00Z'}]}};
// Escaped for the patterns below: a zone with no short name reads "GMT+9" (Asia/Tokyo), and its "+" is a quantifier.
const readerZone = new Intl.DateTimeFormat(undefined, {timeZoneName: 'short'}).formatToParts(new Date()).find((p) => p.type === 'timeZoneName').value
  .replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

test('a market page says what its price is, how it settles and when, and the reader’s positions by money book', async () => {
  const f = OPEN_MARKET(MARKET_PAGE, [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET'}]);
  await f.ready;
  const html = f.root.innerHTML;
  // The market's readable name and status in words, not "KXBTCD · active".
  assert.match(html, /Bitcoin \$113,500 or above at 5pm ET · <span data-close="[^"]+" data-form="status" data-skew="\d+">Open for trading<\/span> · <span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">KXBTCD-26OCT2617-T113499\.99/); assert.doesNotMatch(html, /· active ·/);
  // The price: a chance, the book it comes from, and when it was read.
  // Each piece holds together ("bid 58¢" ended a 390px line and "/ ask 61¢" began the next), breaking only at "·".
  assert.match(html, new RegExp('≈\u00a056% chance of Yes\u00a0· bid\u00a055¢\u00a0/ ask\u00a057¢\u00a0· as\u00a0of\u00a0[^<]*\u00a0' + readerZone));
  // Every clock names its zone: Closes, the expected result, the raw table, the chart's axis.
  // The zone stays on the time's line ("Closes Oct 28, 02:45" left "UTC" alone on the next at 390px).
  assert.match(html, new RegExp('Closes(?:</span>)?</dt><dd><span class="fig ">[^<]*\u00a0' + readerZone + '<'));
  assert.match(html, new RegExp('Result expected [^<]*' + readerZone)); assert.match(f.root.querySelector('#rawsect').innerHTML, new RegExp('Time \\(' + readerZone + '\\)'));
  assert.match(html, new RegExp('class="pc-xlab" text-anchor="end">[^<]*' + readerZone));
  assert.match(html, /If the BRTI average before 5\u00a0PM\u00a0EDT is above 113499\.99/);
  // Live and paper each get their own block and totals; nothing adds them together.
  const live = html.slice(html.indexOf('<span class="mk live">Live</span> real money'), html.indexOf('<span class="mk">Paper</span>'));
  const paper = html.slice(html.indexOf('<span class="mk">Paper</span> paper money, not real'));
  assert.ok(live.length > 0 && paper.length > 0);
  assert.match(live, /1 open at cost \+ fees \$1\.06/); assert.match(live, /\+\$0\.04/); assert.doesNotMatch(live, /\$4\.50/);
  assert.match(paper, /1 open at cost \+ fees \$4\.50/); assert.match(paper, /1 closed · realized <span class="gain">\+\$0\.24/);
  assert.match(paper, /Closed \(take-profit\) @ 75¢/); assert.match(paper, /Deleted strategy/);
  assert.doesNotMatch(html, /\$5\.56|\$0\.84/);  // live + paper cost, live + paper unrealized
  assert.match(live, /<a href="\/strategies\/4">Daily close drift<\/a>/);
  assert.doesNotMatch(html, /NaN|undefined/);
});

test('a market page says when the reader has no positions there, or when they did not load', async () => {
  for (const [mine, said] of [[{open: [], closed: []}, /None of your strategies holds or has traded this contract/], [null, /Your positions in this market didn’t load/]]) {
    const f = OPEN_MARKET({...MARKET_PAGE, mine});
    await f.ready;
    assert.match(f.root.innerHTML, said); assert.doesNotMatch(f.root.innerHTML, /mk-book/);
  }
  // Kalshi unreachable: the Explore snapshot says how old it is, and the rules point to Kalshi.
  const f = OPEN_MARKET({...MARKET_PAGE, rules: undefined, settles_at: undefined, close_time: null, snapshot: true,
    as_of: new Date(Date.now() - 6 * 60000).toISOString(), history_unavailable: true, points: []});
  await f.ready;
  assert.match(f.root.innerHTML, /Explore snapshot, 6m ago/); assert.match(f.root.innerHTML, /settlement rules didn’t come with this snapshot/);
  assert.match(f.root.innerHTML, /Closes<\/dt><dd><span class="fig ">—/);
});

test('a settled market shows its result in place of a live price', async () => {
  const f = OPEN_MARKET({...MARKET_PAGE, status: 'finalized', result: 'no'});
  await f.ready;
  assert.match(f.root.innerHTML, /Result<\/dt><dd><span class="fig ">No<\/span><\/dd><dd class="sub-fig">each No contract paid \$1/);
  assert.match(f.root.innerHTML, /Settled\u00a0· <span class="kalshi-ref">Kalshi contract <span class="tick" translate="no">KXBTCD-26OCT2617-T113499\.99/); assert.doesNotMatch(f.root.innerHTML, /chance of Yes/);
});

// Broken pages on /admin: browser error reports grouped by message and page (server client_error_groups).
// Anyone can send a report, signed out too, so every field is escaped.
test('the admin page lists the last day of page errors, grouped, with every field escaped', async () => {
  const groups = [{kind: 'error', message: '<img src=x onerror=alert(1)> is not a function', path: '/strategies/:id', n: 3, signed_out: 1,
    first_seen: '2026-10-26T08:00:00Z', last_seen: '2026-10-26T09:00:00Z', themes: ['meridian', 'tau'], versions: ['<b>v</b>', 'abc123'], at: 'app.js:12:5'}];
  for (const [rows, expect] of [[undefined, /No page errors reported in the last 24 hours\./], [[], /No page errors reported/], [groups, null]]) {
    const f = frontend({fetchImpl: path => {
      assert.equal(path, '/api/admin');
      return response({users: [], waitlist: [], ...(rows ? {client_errors: rows} : {})});
    }});
    f.S.me.is_admin = true; f.location.pathname = '/admin';
    await f.render(); await flush(); await flush();
    const html = f.root.querySelector('#client-errors').innerHTML;
    if (expect) { assert.match(html, expect); f.clearTimers(); continue; }
    assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt; is not a function/);
    assert.doesNotMatch(html, /<img|<b>v/);
    assert.match(html, /Uncaught error\u00a0\u00b7 app\.js:12:5/);
    assert.match(html, /data-lab="Page, theme, build">\/strategies\/:id<div class="sub-fig">meridian, tau\u00a0\u00b7 build &lt;b&gt;v&lt;\/b&gt; \+1\u00a0older<\/div>/);
    assert.match(html, /data-lab="Count">3<div class="sub-fig">1 signed out<\/div>/);
    assert.match(html, /data-lab="Last seen">.+<div class="sub-fig">first .+<\/div><\/td><\/tr>/);
    assert.equal(f.root.querySelector('#ce-count').textContent, 'last 24h\u00a0\u00b7 3 reports');
    f.clearTimers();
  }
});

test('a page that breaks on a reply it did not expect reports the bug, and the user sees plain words', async () => {
  const reports = [];
  const f = frontend({fetchImpl: () => response({})});  // no users list: the admin page throws a TypeError
  f.win.__tauReport = (kind, err) => reports.push([kind, err]);
  f.S.me.is_admin = true; f.location.pathname = '/admin';
  await f.render(); await flush(); await flush();
  assert.match(f.root.innerHTML, /Something went wrong on this page\. Try again\./);
  assert.equal(reports.length, 1);
  assert.equal(reports[0][0], 'view'); assert.equal(reports[0][1].name, 'TypeError');
  f.clearTimers();
});

test('a returning user reads what the time away cost, the paper forward-test passes and a live-ready strategy in the strip', async () => {
  // A week away: the autopilot spent credits (real money), a paper strategy passed its forward test and
  // became ready for live days after it was created, and auto-reload is off with two days of credit left.
  const since = {at: '2026-10-19T08:00:00+00:00', first: false, books: {paper: {pnl: 12.65, trades: 36}},
    passed: {n: 0, items: []}, autopilot: {}, runs: {succeeded: 6},
    spent: {since: 27.45, week: 27.45}, milestones: {passed: [232], live_ready: [232]}};
  const deployments = [{id: 7, strategy_id: 232, title: 'ETH <i>drift</i>', market: 'eth15m', mode: 'paper', status: 'running',
    status_reason: null, stake: 10, max_positions: 3, realized_pnl: 97.07, unrealized_pnl: null,
    closed_trades: 32, open_positions: 0, curve: [], created_at: '2026-10-19T08:00:00Z'}];
  const strip = async (extra, me) => {
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...dashboardData(), deployments, since, ...extra});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, credit_balance: 7.15, min_run_balance: 1, auto_reload: null, ...me};
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    return f.root.querySelector('#dash-since').innerHTML;
  };
  const text = await strip({});
  // What it cost: its own row, never added to the paper book above it. With no word on whether a card was ever
  // charged (card_charged unknown), it never says "real money", nor who paid.
  assert.match(text, /<dt>Cost<\/dt><dd><b>\$27\.45<\/b> of credits spent<span class="since-sub"> · \$7\.15 left · <a href="\/billing">Billing<\/a><\/span><\/dd>/);
  // No card ever charged: the credits spent were free ones, and the row says the card is untouched.
  const free = await strip({since: {...since, spent: {...since.spent, card_charged: false}}});
  assert.match(free, /of credits spent<span class="since-sub">\u00a0· free credits so far: your card hasn’t been charged\u00a0· \$7\.15 left\u00a0· /);
  assert.doesNotMatch(free, /real money/);
  assert.match(await strip({since: {...since, spent: {...since.spent, card_charged: true}}}), /of credits spent<span class="since-sub">\u00a0· real money\u00a0· /);
  // A card charged while they were away says so, with the credits it bought (never netted with the spend).
  const reload = (extra) => strip({since: {...since, spent: {...since.spent, card_charged: true, ...extra}}});
  assert.match(await reload({bought: 20, charges: 1, reloads: 1}), /<b>\$27\.45<\/b> of credits spent; auto-reload charged your card once for <b>\$20\.00<\/b> of credits<span class="since-sub">\u00a0· real money/);
  assert.match(await reload({bought: 60, charges: 3, reloads: 3}), /auto-reload charged your card 3 times for <b>\$60\.00<\/b> of credits/);
  assert.match(await reload({bought: 40, charges: 2, reloads: 2}), /auto-reload charged your card twice for <b>\$40\.00<\/b> of credits/);  // "twice", not "2 times"
  assert.match(await reload({bought: 45, charges: 2, reloads: 1}), /spent; 2 card charges \(1 by auto-reload\) bought <b>\$45\.00<\/b> of credits/);
  assert.match(await reload({bought: 25, charges: 1, reloads: 0}), /spent; you bought <b>\$25\.00<\/b> of credits/);
  assert.doesNotMatch(text, /auto-reload charged|you bought/);
  assert.doesNotMatch(await reload({bought: 20, charges: 1, reloads: 1}), /\$7\.45|\$47\.45/);  // never netted or added
  // A loss guard's pauses are told in the Autopilot row (the engine's, not its moves), resumed ones too.
  const guarded = await strip({since: {...since, autopilot: {deploy: 3}, auto_paused: [232, 9]}});
  assert.match(guarded, /<dt>Autopilot<\/dt><dd>It put 3 on paper\. 2 strategies were paused automatically to stop a loss\.<\/dd>/);
  assert.match(await strip({since: {...since, auto_paused: [9]}}), /<span data-since-ap>On\. It made no changes\.<\/span> 1 strategy was paused automatically to stop a loss\./);
  assert.doesNotMatch(text, /paused automatically/);
  assert.match(text, /<b>Paper<\/b> <span class="pos">\+\$12\.65<\/span>/);
  assert.doesNotMatch(text, /\$40\.10|−\$14\.80|\$14\.80/);  // paper and credits never summed or netted
  // The forward-test pass leads New results when nothing else passed, named from the page's deployments.
  assert.match(text, /<dt>New results<\/dt><dd><a href="\/strategies\/232">ETH &lt;i&gt;drift&lt;\/i&gt;<\/a> passed its paper forward test: a candidate for live<span class="since-sub">\u00a0· /);
  assert.doesNotMatch(text, /Nothing new passed/);
  // Live-ready is the week's next step, first under Needs you; the runway warns before the pause.
  assert.match(text, /<dt>Needs you<\/dt><dd><a href="\/strategies\/232">ETH &lt;i&gt;drift&lt;\/i&gt;<\/a> is ready for live trading\. Going live is your call\./);
  // Live trading closed on the server: it waits on paper, as the bell says, never "Going live is your call".
  const shut = await strip({}, {live_trading_available: false});
  assert.match(shut, /<dt>Needs you<\/dt><dd><a href="\/strategies\/232">ETH &lt;i&gt;drift&lt;\/i&gt;<\/a> cleared every paper-to-live check\. Live trading isn\u2019t open yet, so it stays on paper and nothing trades real money\./);
  assert.doesNotMatch(shut, /ready for live trading|Going live is your call/);
  // Counted to the pause, not to $0: $6.15 above the $1.00 floor at $27.45 a week.
  assert.match(text, /Research pauses in about 2 days at this week’s pace, when credits fall under \$1\.00\. <a href="\/billing">Add credits or turn on auto-reload<\/a>/);
  // Auto-reload on: no runway warning. A plenty balance: none either.
  assert.doesNotMatch(await strip({}, {auto_reload: {amount: 20, charge: 21.1, threshold: 5}}), /Research pauses/);
  assert.doesNotMatch(await strip({}, {credit_balance: 80}), /Research pauses/);
  // Under the research floor the floor line says it, not both.
  const floor = await strip({}, {credit_balance: 0.42});
  assert.match(floor, /Credits are at \$0\.42/); assert.doesNotMatch(floor, /Research pauses/);
  // Payments off (the server sends no spend): no Cost row. Nothing spent: says so.
  assert.doesNotMatch(await strip({since: {...since, spent: null}}), /<dt>Cost<\/dt>/);
  assert.match(await strip({since: {...since, spent: {since: 0, week: 0}}}), /<dt>Cost<\/dt><dd>No credits spent/);
  // Something else passed too: the list first, the forward test after it.
  const both = await strip({since: {...since, passed: {n: 1, items: [{id: 9, title: 'Fade'}]}}});
  assert.match(both, /1 strategy passed: <a href="\/strategies\/9">Fade<\/a>.*\. <a href="\/strategies\/232">ETH &lt;i&gt;drift&lt;\/i&gt;<\/a> passed its paper forward test: a candidate for live\./);
  // A milestone is named by its own title, from its strategy row (the server's names), before its deployment's; one
  // with no deployment listed read "Strategy 10", an internal id. One whose title is gone (deleted) is "a strategy".
  assert.match(await strip({since: {...since, names: {232: 'ETH drift'}}}), /<dt>New results<\/dt><dd><a href="\/strategies\/232">ETH drift<\/a> passed/);
  const gone = {...since, milestones: {passed: [232, 10], live_ready: [10]}};
  const own = await strip({deployments: [], since: {...gone, names: {232: 'ETH <i>drift</i>', 10: 'BTC fade'}}});
  assert.match(own, /<dt>New results<\/dt><dd><span class="since-links"><a href="\/strategies\/232">ETH &lt;i&gt;drift&lt;\/i&gt;<\/a>, <a href="\/strategies\/10">BTC fade<\/a><\/span> passed their paper forward test: candidates for live/);
  assert.match(own, /<dt>Needs you<\/dt><dd><a href="\/strategies\/10">BTC fade<\/a> is ready for live trading\./);
  const bare = await strip({deployments: [], since: {...gone, names: {232: 'ETH drift'}}});
  assert.match(bare, /<a href="\/strategies\/232">ETH drift<\/a>, a strategy<\/span> passed their paper forward test/);
  assert.match(bare, /<dt>Needs you<\/dt><dd>A strategy is ready for live trading\./);
  const none = await strip({deployments: [], since: {...since, milestones: {passed: [10], live_ready: []}}});
  assert.match(none, /<dt>New results<\/dt><dd>A strategy passed its paper forward test: a candidate for live/);
  for (const html of [own, bare, none]) assert.doesNotMatch(html, /Strategy \d/);
});

test('the last move says the forward test verdict and drops the live-ready marker, and a credits pause says what keeps trading', async () => {
  const f = frontend();
  const t = (text) => f.apMoveText({text, at: new Date().toISOString()});
  assert.equal(t('Paper forward gate: ETH late-window drift PASSED (32 paper trades, p=0.021, +6.1% per trade) and is now a deployment candidate. Live still needs your live switch.'),
    'ETH late-window drift passed its paper forward test');
  assert.equal(t('Paper forward gate: BTC fade did not pass its one paper judgment (INCONCLUSIVE, 30 paper trades, p=0.210, -0.5% per trade).'),
    'BTC fade did not pass its paper forward test');
  assert.equal(t('Paper forward gate: BTC fade passed on paper (30 paper trades, p=0.010, +2.0% per trade) but stays off the candidate list: too close to one you run.'),
    'BTC fade passed on paper, not added to the candidates');
  assert.equal(t('[live-ready #232] “ETH drift” cleared every paper-to-live check: 32 realistic paper trades, +$97.07 net. Going live is your call.'),
    '“ETH drift” cleared every paper-to-live check: 32 realistic paper trades, +$97.07 net');
  const g = frontend({fetchImpl: path => {
    if (path.startsWith('/api/dashboard')) return response(dashboardData());
    if (path === '/api/autopilot/status') return response({autopilot: true, mode: 'paper'});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  g.S.me = {...g.S.me, billing_enabled: true, credit_balance: 0.42, min_run_balance: 1, auto_reload: null};
  g.S.me.user.autopilot = true;
  await g.viewDashboard(); await flush();
  const paused = {autopilot: true, mode: 'paper', research: {active: []}, billing_blocked: true, billing_reason: 'credits'};
  g.S.ap = {...paused, paper_running: 1}; g.paintDashAp();
  assert.match(g.root.querySelector('#dash-ap').innerHTML, /and it picks up on its own\. The strategy already running keeps trading\./);
  g.S.ap = {...paused, paper_running: 2, demo_running: 1}; g.paintDashAp();
  assert.match(g.root.querySelector('#dash-ap').innerHTML, /The 3 strategies already running keep trading\./);
  g.S.ap = {...paused, paper_running: 0}; g.paintDashAp();
  assert.doesNotMatch(g.root.querySelector('#dash-ap').innerHTML, /keeps? trading/);
  g.clearTimers();
});

// ---- Failures a user can act on (Meridian): a write that failed says why next to it and puts the screen back;
// a write that landed says so even when the page can't refresh after it; one send per press.

test('Meridian: the autopilot switch in the panel locks while it saves, and a failed save goes back and says why in the panel', async () => {
  const save = deferred(); let posts = 0;
  const off = {...apStatus, autopilot: false, mode: 'off', focus: []};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData());
    if (path === '/api/settings') { posts++; return save.promise; }
    if (path === '/api/autopilot/status') return response(off);
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false; f.S.ap = off;
  await f.viewDashboard(); await flush();
  await f.root.querySelector('#dash-ap [data-apcard="focus"]').onclick(); await flush();
  const box = f.root.parent.querySelector('#autopilot-float'), sw = box.querySelector('#apf-apswitch');
  sw.checked = true; const saving = sw.onchange(); await flush();
  assert.equal(sw.disabled, true);
  save.resolve(response({error: 'Autopilot could not be saved. Try again.'}, 500)); await saving; await flush();
  assert.equal(posts, 1);
  assert.equal(sw.checked, false); assert.equal(sw.disabled, false); assert.notEqual(f.S.me.user.autopilot, true);
  assert.match(box.querySelector('#apf-flash').innerHTML, /error-text">Autopilot could not be saved\. Try again\./);
  f.clearTimers();
});

test('Meridian: an auto-reload change that does not save puts the switch, amounts and summary back', async () => {
  let pending = null; const sent = [];
  const f = frontend({stripeLoader: async () => STRIPE_STUB, fetchImpl: (path, options = {}) => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response(cardedBilling());
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    if (path === '/api/billing/auto-reload') { sent.push(JSON.parse(options.body)); pending = deferred(); return pending.promise; }
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewBilling(); await flush();
  const box = f.root.querySelector('#autoreload'), amt = f.root.querySelector('#reload-amt'), when = () => f.root.querySelector('#autorel-when').innerHTML;
  amt.value = '40'; let saving = amt.onchange(); await flush();
  assert.deepEqual([box.disabled, amt.disabled], [true, true]);
  assert.deepEqual(sent.at(-1), {on: true, amount: 40, threshold: 8});
  pending.resolve(response({error: 'Your card was declined.'}, 402)); await saving; await flush();
  assert.equal(box.checked, true); assert.equal(String(amt.value), '25'); assert.equal(box.disabled, false);
  assert.equal(f.root.querySelector('#autorel-sum').textContent, 'Reload $25 at $8');
  assert.match(when(), /^<b>On\.<\/b>[\s\S]*\$25\.00 of credits/);
  box.checked = false; saving = box.onchange(); await flush();
  pending.resolve(response({}, 503)); await saving; await flush();
  assert.equal(box.checked, true); assert.match(when(), /^<b>On\.<\/b>/);
});

test('Meridian: a top-up that went through says so even when the page cannot refresh after it', async () => {
  let reads = 0;
  const f = frontend({stripeLoader: async () => STRIPE_STUB, fetchImpl: path => {
    if (/^\/api\/billing(\?|$)/.test(path)) return ++reads === 1 ? response(cardedBilling()) : response({error: 'Tau is busy.'}, 500);
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    if (path === '/api/billing/topup') return response({ok: true, balance: 27.42});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewBilling(); await flush();
  const btn = f.root.querySelector('#topup-btn');
  await btn.onclick({currentTarget: btn}); await flush();
  const said = f.root.querySelector('#topup-flash').innerHTML;
  assert.match(said, /notice good/); assert.doesNotMatch(said, /Tau is busy/);
  assert.match(said, /New balance is \$27\.42\. The page didn’t refresh, so reload to see it\./);
});

test('Meridian Community: Post and Share my P&L send once while either is out, and a failed reply says why under its own box', async () => {
  const post = {id: 11, body: 'Hi', author: 'Bob', username: 'bob', created_at: '2026-10-17T10:00:00Z', mine: false, comments: 1, reactions: [{emoji: '👍', count: 1, mine: false}]};
  const sending = deferred(), reacting = deferred(); let posts = 0, reacts = 0, feedOk = true;
  const f = frontend({fetchImpl: (path, options = {}) => {
    if (path === '/api/strategies') return response({strategies: []});
    if (path === '/api/community' && options.method === 'POST') { posts++; return sending.promise; }
    if (path === '/api/community') return feedOk ? response({posts: [post]}) : response({error: 'Tau is busy.'}, 500);
    if (path === '/api/community/11/react') { reacts++; return reacting.promise; }
    if (path === '/api/community/11/comments' && options.method === 'POST') return response({error: 'Replies are closed on this post.'}, 400);
    if (path === '/api/community/11/comments') return response({comments: [{body: 'First', author: 'Ana', created_at: '2026-10-17T10:00:00Z'}]});
    return response({});
  }});
  await f.viewCommunity(); await flush();
  const form = f.root.querySelector('#composer-post'), share = form.querySelector('[data-share="pnl"]'), postBtn = form.querySelector('[type=submit]');
  share.onclick(); f.elapse(500);  // Share my P&L asks first (community_frontend_cases.mjs); the second press sends
  const first = share.onclick(); await flush();
  assert.deepEqual([share.disabled, postBtn.disabled], [true, true]);
  await share.onclick(); form.onsubmit({preventDefault() {}}); await flush();
  assert.equal(posts, 1);
  feedOk = false;
  sending.resolve(response({ok: true, id: 12})); await first; await flush();
  assert.deepEqual([share.disabled, postBtn.disabled], [false, false]);
  assert.match(f.root.querySelector('#post-flash').innerHTML, /notice good[\s\S]*Posted\. The page didn’t refresh/);
  feedOk = true;
  const feed = f.root.querySelector('#feed'), click = (target) => feed.listeners.get('click')({target});
  const chip = feed.querySelector('.rx[data-emoji]');
  click(chip); click(chip); await flush();
  assert.equal(reacts, 1);
  reacting.resolve(response({reactions: [{emoji: '👍', count: 2, mine: true}]})); await flush(); await flush();
  await click(feed.querySelector('[data-act="comments"]')); await flush();
  const box = feed.querySelector('.comments'), cf = box.querySelector('.cmt-form');
  cf.querySelector('input').value = 'Nice';
  await cf.onsubmit({preventDefault() {}, currentTarget: cf}); await flush();
  assert.match(box.querySelector('.form-flash').innerHTML, /notice bad[\s\S]*Replies are closed on this post\./);
});

test('Meridian: a card wall whose card form did not load says what to do, and Save becomes Try again', async () => {
  let up = false;
  const f = frontend({stripeLoader: async () => STRIPE_STUB, fetchImpl: path => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response({configured: true, publishable_key: 'synthetic-only'});
    if (path === '/api/billing/setup-intent') { if (!up) throw new TypeError('Failed to fetch'); return response({client_secret: 'synthetic'}); }
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.location.pathname = '/'; Object.assign(f.S.me, {needs_card: true, free_bonus: 20});
  await f.paymentGate(); await flush();
  const wall = () => f.document.body.querySelectorAll('.pay-modal').filter(d => d.isConnected).at(-1);
  let dlg = wall();
  assert.match(dlg.querySelector('#pay-hint').innerHTML, /The card form didn’t load\. Check your connection, or allow js\.stripe\.com if a blocker is on, then try again\./);
  assert.equal(dlg.querySelector('#pay-submit').textContent, 'Try again');
  up = true;
  dlg.querySelector('#payform').onsubmit({preventDefault() {}}); await flush(); await flush();
  dlg = wall();
  assert.equal(dlg.querySelector('#pay-hint').innerHTML, '');
  assert.equal(dlg.querySelector('#pay-submit').textContent, 'Save payment method');
});

test('Meridian: a session that ends mid-use says so on the sign-in page, once', async () => {
  const f = frontend({fetchImpl: () => response({error: 'Please sign in.'}, 401)});
  const signin = f.routes.find(([pattern]) => pattern.test('/signin'))[1];
  f.location.pathname = '/signin';  // already there: the harness's history keeps the query in the path
  await assert.rejects(f.api('/api/community', {body: 'draft'}), /Please sign in/);
  await signin(); await flush();
  assert.match(f.root.querySelector('.lnotice').textContent, /You were signed out, so that last change wasn’t saved\./);
  await signin(); await flush();
  assert.equal(f.root.querySelector('.lnotice'), null);
});

test('Meridian: a brand-new account\'s empty Strategies, Deploy and Research say what each is and the one next step', async () => {
  // Strategies: none yet, autopilot off.
  let f = frontend({fetchImpl: path => (path.startsWith('/api/strategies?')
    ? response({strategies: [], counts: {total: 0, passed: 0, failed: 0, rejected: 0}}) : response({}))});
  f.S.me.user.autopilot = false;
  await f.viewStrategies(); await flush(); await flush();
  let empty = f.root.querySelector('#slips .empty');
  assert.equal(empty.querySelector('h3').textContent, 'No strategies yet');
  assert.match(empty.innerHTML, /<p>Every strategy a research session writes lands here, with its test on data it never saw\. Start a session to find your first\.<\/p>/);
  assert.deepEqual(empty.querySelectorAll('a.btn').map(a => a.getAttribute('href')), ['/research?new=1']);
  // A filter that matches nothing says to try another, not a bare heading.
  f = frontend({fetchImpl: path => (path.startsWith('/api/strategies?')
    ? response({strategies: [], counts: {total: 3, passed: 1, failed: 1, rejected: 1}}) : response({}))});
  await f.viewStrategies(); await flush(); await flush();
  assert.match(f.root.querySelector('#slips .empty').innerHTML, /<h3>No matching strategies<\/h3><p>Try another filter\.<\/p>/);

  // Deploy: nothing deployed. With passed strategies (or before that count is in) the board says what
  // goes on it; with none passed, that nothing has passed yet. The Realized figure points at no list.
  for (const [passed, said, href] of [[2, /Open a passed strategy and deploy it here\. Paper first: it trades the live market with paper money\./, '/strategies?status=passed'],
    [0, /Nothing has passed yet\. A strategy goes on the board once it passes every test in a research session, paper first\./, '/research?new=1']]) {
    f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [], open_positions: []})
      : path === '/api/strategies?status=passed' ? response({counts: {passed}}) : response({})});
    f.location.pathname = '/deploy';
    await f.viewDeploy(); for (let i = 0; i < 6; i++) await flush();
    empty = f.root.querySelector('#deps .empty');
    assert.match(empty.innerHTML, said);
    assert.deepEqual(empty.querySelectorAll('a.btn').map(a => a.getAttribute('href')), [href]);
    assert.match(f.root.querySelector('#dfigs').innerHTML, /paper money, not real/);
    assert.doesNotMatch(f.root.querySelector('#dfigs').innerHTML, /strategies listed below/);
    f.clearTimers();
  }

  // Research: what a session does, under the page name.
  f = frontend({fetchImpl: path => path === '/api/runs' ? response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null}) : response({models: [], default: '', markets: []})});
  f.location.pathname = '/research';
  await f.viewResearch(); await flush(); await flush(); f.clearTimers();
  assert.match(f.root.querySelector('.research-page').innerHTML, /<h1 class="page">Research<\/h1><p class="lede research-lede">Describe an idea and a session turns it into strategies, then tests each on data it never saw\. The ones that pass can trade on paper\.<\/p>/);
});

test('Meridian: Strategies says under its name what the page is for, in Tau\'s words, and Research results stays beside the name', async () => {
  const text = 'Every strategy your agents researched. Passed strategies on deployable markets can be deployed; void ones stay here so you can see what didn’t work.';
  // The list is one file for both themes (page-strategies.js): Tau's head and Meridian's say the one line.
  const tauSource = readFileSync(new URL('../app/static/page-strategies.js', import.meta.url), 'utf8');
  assert.ok(tauSource.includes(`boardTitle('Strategies', '${text}')`));
  assert.ok(tauSource.includes("${pageLede('" + text + "')}"));
  const f = frontend({fetchImpl: path => (path.startsWith('/api/strategies?')
    ? response({strategies: [], counts: {total: 0, passed: 0, failed: 0, rejected: 0}}) : response({}))});
  await f.viewStrategies(); await flush(); await flush();
  const head = f.root.querySelector('.strategy-heading').innerHTML;
  // The name, then the summary beside it, then the line on a row of its own.
  assert.match(head, /^<h1 class="page">Strategies<\/h1><details class="strategy-summary">[^]*?<\/details><p class="lede page-lede">([^<]*)<\/p>$/);
  assert.equal(f.root.querySelector('.strategy-heading .page-lede').textContent, text);
  f.clearTimers();
  // At 390px the name keeps its width and a long "N% pass rate, of the 1,201 strategies here" wraps beside it;
  // the line spans both columns underneath.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.strategy-heading \{ display: grid; grid-template-columns: max-content minmax\(0, 1fr\);/);
  assert.match(css, /\.strategy-heading > \.strategy-summary \{ justify-self: end; \}/);
  assert.match(css, /\.strategy-heading > \.page-lede \{ grid-column: 1 \/ -1; margin: 0; \}/);
});

test('Meridian: Deploy, Explore, Settings and Community each say under their name what the page is for, in Tau\'s words', async () => {
  // Explore is one file for both themes (page-explore.js): Tau's heading is in it, beside Meridian's.
  const tauSource = ['app.js', 'page-explore.js'].map((f) => readFileSync(new URL('../app/static/' + f, import.meta.url), 'utf8')).join('\n');
  // Community's page file is both themes' (page-community.js): one lede, Tau's heading's and Meridian's alike.
  const community = readFileSync(new URL('../app/static/page-community.js', import.meta.url), 'utf8');
  const said = (page, text) => tauSource.includes(`boardTitle('${page}', '${text}')`)
    || page === 'Community' && community.includes(`const lede = '${text}';`) && community.includes(`boardTitle('Community', lede)`) && community.includes('${pageLede(lede)}');
  const LEDES = {
    Deploy: 'Your strategies trading now.',
    Explore: 'Every market Tau is tracking right now, across crypto, politics, sports, weather and more, hottest first. Prices refresh each minute.',
    Settings: 'How Tau looks and works for you.',
    Community: 'Share a strategy, an idea, or how your money is doing. Like and reply to other traders.',
  };
  // Tau's heading says the same words: the two themes never describe one page two ways.
  for (const [page, text] of Object.entries(LEDES)) assert.ok(said(page, text), page);
  const lede = (f, selector) => {
    const head = f.root.querySelector(selector).innerHTML;
    const [, line] = head.match(/<h1 class="page">[^<]+<\/h1>(?:\s|<div class="chips feed-filter"[^]*?<\/div>\s*)*<p class="lede page-lede">([^<]*)<\/p>/) || [];
    return line;
  };

  let f = frontend({fetchImpl: path => path === '/api/deployments' ? response({deployments: [], open_positions: []}) : response({counts: {passed: 0}})});
  f.location.pathname = '/deploy';
  await f.viewDeploy(); await flush(); f.clearTimers();
  assert.equal(lede(f, '.board-title'), LEDES.Deploy);

  f = frontend({fetchImpl: () => response({total: 0, shown: 0, matched: 0, per: 40, page: 0, markets: []})});
  await f.viewExplore(); await flush(); f.clearTimers();
  assert.equal(lede(f, '.explore-heading'), LEDES.Explore);

  f = frontend({fetchImpl: () => response({})});
  await f.viewSettings(); await flush();
  assert.equal(lede(f, '.board-title'), LEDES.Settings);

  f = frontend({fetchImpl: path => path === '/api/community' ? response({posts: []}) : response({strategies: []})});
  await f.viewCommunity(); await flush(); f.clearTimers();
  assert.equal(lede(f, '.community-heading'), LEDES.Community);

  // Research's lede type; on Explore it takes its own full row under the name, and the price age and (on a
  // narrow column) the search move down a row instead of sharing it.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.page-lede \{ margin: 4px 0 0; font-size: 14px; line-height: 1\.5;/);
  assert.match(css, /\.explore-heading > \.page-lede \{ grid-column: 1 \/ -1; grid-row: 2; margin: 0; \}/);
  assert.match(css, /\.explore-freshness \{ display: flex; grid-column: 1 \/ -1; grid-row: 3;/);
  assert.match(css, /\.explore-filters \.xsearch \{ grid-column: 1 \/ -1; grid-row: 3; \}\n  \.explore-freshness \{ grid-column: 1 \/ -1; grid-row: 4; \}/);
  // Community's takes its own row under the name and filters (its 70ch measure fit beside them at 1280px).
  assert.match(css, /\.community-heading > \.page-lede \{ flex-basis: 100%; max-width: none; margin: 0; \}/);
  assert.match(css, /\.feed-filter \{ grid-column: 1 \/ -1; grid-row: 2; \}\n  \.community-heading > \.page-lede \{ grid-column: 1 \/ -1; grid-row: 3; \}/);
});

// Keyboard and screen-reader paths through the autopilot switch and the notification list. A reader
// hears a change only through a live region, and a keyboard user is lost the moment focus falls to
// the top of the page; both used to happen on the one-click way into autopilot.
const said = f => { [...f.timeouts.values()].forEach(callback => callback()); return f.document.getElementById('sr-status')?.textContent || ''; };

test('turning autopilot on from the Overview card says so out loud and leaves focus on a control', async () => {
  let status = {...apStatus, autopilot: false, mode: 'off', focus: []};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(dashboardData());
    if (path === '/api/autopilot/status') return response(status);
    if (path === '/api/settings') { status = {...status, autopilot: true, mode: 'paper'}; return response({ok: true}); }
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }, storage: new Map([['tau_ap_open', '0']])});
  f.S.me.user.autopilot = false; f.S.ap = status;
  await f.viewDashboard(); await flush(); await flush();
  const on = f.root.querySelector('#dash-ap [data-apcard="on"]');
  on.focus();
  await on.onclick(); for (let i = 0; i < 4; i++) await flush();
  assert.match(said(f), /^Autopilot is on\. It researches and trades on paper by itself/);
  // The card repaints without the pressed button, so focus follows to what replaced it.
  assert.notEqual(f.document.activeElement, f.document.body);
  assert.ok(f.document.activeElement.matches('.apf-x') || f.document.activeElement.matches('[data-apcard="open"]'),
    'focus landed on ' + f.document.activeElement.className);
  f.clearTimers();
});

test('the panel switch says its new state, and locking it does not drop keyboard focus', async () => {
  let status = {...apStatus, autopilot: true, mode: 'paper', focus: []};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/autopilot/status') return response(status);
    if (path === '/api/settings') { status = {...status, autopilot: false, mode: 'off'}; return response({ok: true}); }
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }, storage: new Map([['tau_ap_open', '1']])});
  f.S.me.user.autopilot = true; f.S.ap = status;
  const box = new Element('div', {id: 'autopilot-float'}); f.document.body.appendChild(box);
  f.renderAutopilot(box, status); await flush();
  const sw = box.querySelector('#apf-apswitch');
  sw.focus(); sw.checked = false;
  await sw.onchange(); for (let i = 0; i < 3; i++) await flush();
  assert.equal(f.S.me.user.autopilot, false);
  assert.match(said(f), /^Autopilot is off\. It only suggests ideas for you to approve\.$/);
  assert.equal(f.document.activeElement, sw);
  f.clearTimers();
});

test('the notification list closes when focus leaves it, so Tab out never leaves it open behind the page', async () => {
  const f = frontend({fetchImpl: path => (path === '/api/dashboard' ? response(dashboardData()) : response({})),
    notifications: {unread: 1, items: [{body: 'Autopilot put a strategy on paper.', link: '/deploy', created_at: '2026-10-17T10:00:00Z', read: false}]}});
  await f.viewDashboard(); await flush(); await flush();
  const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
  await trig.onclick({stopPropagation() {}}); await flush();
  assert.equal(menu.hidden, false); assert.equal(trig.getAttribute('aria-expanded'), 'true');
  await trig.onclick({stopPropagation() {}});
  assert.equal(menu.hidden, true);
  await trig.onclick({stopPropagation() {}});
  assert.equal(menu.hidden, false);
  // Tab out of the list (focus moves to the profile button): it closes instead of staying open where
  // Esc, bound to the bell, can no longer reach it.
  wrap.dispatchEvent({type: 'focusout', relatedTarget: f.root.querySelector('.profile-trig')});
  assert.equal(menu.hidden, true); assert.equal(trig.getAttribute('aria-expanded'), 'false');
  f.clearTimers();
});

test('the full-screen autopilot sheet keeps Tab inside it; beside the page it lets Tab walk on', async () => {
  for (const sheet of [true, false]) {
    const f = frontend({storage: new Map([['tau_ap_open', '1']]),
      matchMedia: () => ({matches: sheet}),   // under 601px the open panel covers the whole page
      fetchImpl: path => {
        if (path === '/api/models') return response({models: [], default: ''});
        if (path.startsWith('/api/chat')) return response({messages: []});
        throw new Error('Unexpected offline request: ' + path);
      }});
    const box = new Element('div', {id: 'autopilot-float'}); f.document.body.appendChild(box);
    f.renderAutopilot(box, {...apStatus, focus: []}); await flush();
    const first = box.querySelector('.apf-x'), last = box.querySelector('#apf-msg');
    [first, last].forEach((el) => { el.offsetWidth = 40; });   // the rest is folded away or hidden
    let prevented = 0;
    const press = (shiftKey) => box.onkeydown({key: 'Tab', shiftKey, preventDefault: () => prevented++});
    last.focus(); press(false);
    assert.equal(f.document.activeElement, sheet ? first : last);
    first.focus(); press(true);
    assert.equal(f.document.activeElement, sheet ? last : first);
    assert.equal(prevented, sheet ? 2 : 0);
    f.clearTimers();
  }
});

// A log list whose rows really leave and come back (the shared fake only flags a removed node), for the
// long-log fold: rows held off the page, then put back above the ones on screen.
class LiveList extends Element {
  get children() { return (this.kids || []).filter(k => k.parent === this && !k.removed); }
  set children(value) { this.kids = value; }
  appendChild(child) { this.insertBefore(child, null); }
  get firstChild() { return this.children[0] || null; }
  insertBefore(child, ref) {
    const add = child.tag === '#fragment' ? child.kids.slice() : [child];
    this.kids = this.kids.filter(k => !add.includes(k));  // a node lives in one place
    const at = ref ? this.kids.indexOf(ref) : -1;
    add.forEach(c => { c.parent = this; c.removed = false; });
    this.kids.splice(at < 0 ? this.kids.length : at, 0, ...add);
  }
}
if (!Object.getOwnPropertyDescriptor(Element.prototype, 'nextSibling')) {
  Object.defineProperty(Element.prototype, 'nextSibling', {get() { const s = this.parent ? this.parent.children : []; return s[s.indexOf(this) + 1] || null; }});
}
const longFeed = (f) => {
  const section = new Element(), log = new LiveList('ol', {class: 'log stream'});
  const jump = new Element('button', {class: 'jumplatest', hidden: ''});
  section.querySelector = sel => ({'.log': log, '.jumplatest': jump})[sel] || null;
  f.document.createDocumentFragment = () => new LiveList('#fragment');
  return {stream: f.runFeed(section), log, jump};
};
const runEvent = (id, kind, message, data = {}) => ({id, kind, message, data, created_at: '2026-10-17T10:00:00Z'});
olderStepsCases({name: 'Meridian', frontend, longFeed, runEvent});

test('Meridian: a long research log paints its latest rows first and shows the earlier ones on request, in place', () => {
  const f = frontend(), {stream, log, jump} = longFeed(f);
  const events = [runEvent(1, 'hypothesis', 'Early idea', {thesis: 'Old'})];
  for (let i = 2; i <= 120; i++) events.push(runEvent(i, 'step', `Step ${i}`));
  stream.push(events);
  assert.equal(log.children.length, 61);
  const fold = log.children[0];
  assert.equal(fold.className, 'log-earlier');
  assert.match(fold.innerHTML, /<button type="button" class="btn small">Show 60 earlier entries<\/button>/);
  assert.match(log.children[1].innerHTML, /Step 61/); assert.match(log.children[60].innerHTML, /Step 120/);
  log.scrollHeight = 100; log.scrollTop = 0; log.clientHeight = 100;  // at the foot: it sticks
  stream.push([runEvent(121, 'verdict', 'FAILED - Early idea: no edge', {title: 'Early idea', status: 'failed'})]);
  assert.equal(log.children.length, 61);  // the verdict landed on its held card
  log.scrollHeight = 5000; log.scrollTop = 0;  // scrolled up: the "N new" chip, as before
  stream.push([runEvent(122, 'step', 'Step 122')]);
  assert.equal(jump.hidden, false); assert.equal(jump.textContent, '1 new ↓');
  fold.querySelector('button').onclick();
  assert.equal(log.children.length, 121); assert.equal(log.querySelector('.log-earlier'), null);
  assert.match(log.children[0].querySelector('[data-review]').innerHTML, /Verdict|failed|Void/i);
  assert.match(log.children[59].innerHTML, /Step 60/); assert.match(log.children[60].innerHTML, /Step 61/);
  assert.equal(f.document.activeElement, log.children[59]); assert.equal(log.children[59].focusOptions.preventScroll, true);
  assert.equal(log.style.scrollBehavior, '');
  // A short log is never folded.
  const g = frontend(), short = longFeed(g);
  short.stream.push(Array.from({length: 80}, (_, i) => runEvent(i + 1, 'step', `Step ${i + 1}`)));
  assert.equal(short.log.children.length, 80);
});

test('Meridian: run log times build each date format once, and read as toLocaleString did', () => {
  let made = 0;
  const CountingIntl = Object.assign(Object.create(Intl), {DateTimeFormat: function (...a) { made++; return new Intl.DateTimeFormat(...a); }});
  const f = frontend({globals: {Intl: CountingIntl}}), {stream, log} = longFeed(f);
  stream.push(Array.from({length: 10}, (_, i) => runEvent(i + 1, 'step', `Step ${i + 1}`)));
  const after10 = made;
  stream.push(Array.from({length: 50}, (_, i) => runEvent(i + 11, 'step', `Step ${i + 11}`)));
  assert.equal(made, after10);
  const d = new Date('2026-10-17T10:00:00Z');
  const time = log.children[0].querySelector('time');
  assert.equal(time.getAttribute('title'), d.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'}));
  assert.equal(time.textContent, d.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}));
});

test('Meridian: the run page poll leaves its unchanged figures, strategies and policy box alone', async () => {
  const run = {id: 9, prompt: 'Lag', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', spent_usd: 1.5, hypotheses_tried: 3};
  const strategies = [{id: 41, title: 'Lag idea', status: 'failed', market: 'btc15m', out_of_sample: {pnl: -1, trades: 30, win_rate: .4}}];
  let spent = 1.5;
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9')
    ? response({run: {...run, spent_usd: spent}, events: [], strategies, rsi: {evolved: false, min_history: 12}}) : response({})});
  await f.viewRun(9); await flush();
  const els = ['#runfigs', '#runboard', '#runnext', '#run-artifacts', '#rsibox'].map((s) => f.root.querySelector(s));
  assert.match(els[3].innerHTML, /Lag idea/); assert.match(els[4].innerHTML, /Self-tuning/);
  const writes = els.map((el) => el.writes);
  for (const tick of f.intervals.values()) tick();
  await flush(); await flush();
  assert.deepEqual(els.map((el) => el.writes), writes);
  spent = 2;  // a figure that moved repaints, and only it
  for (const tick of f.intervals.values()) tick();
  await flush(); await flush();
  assert.deepEqual(els.map((el) => el.writes), [writes[0] + 1, ...writes.slice(1)]);
});

test('Meridian: the Show earlier row has its own style, and the live pill pulses on the compositor', () => {
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.log > li\.log-earlier \{ display: block; text-align: center;/);
  assert.match(css, /@keyframes apf-pulse \{ 0%,100% \{ opacity: 1; transform: scale\(1\); \} 50% \{ opacity: 0; transform: scale\(2\.25\); \} \}/);
  assert.match(css, /prefers-reduced-motion: no-preference\) \{ \.apf\.live \.apf-dot::after \{ animation: apf-pulse/);
});

// A spec stored without sizing reaches the client as stake: null and max_positions: null (the server
// reads old rows only as far as they go). Nothing reads "$ a trade", "null" or NaN.
const nullStakeDep = (over) => ({id: 1, strategy_id: 42, title: 'Old spec', market: 'btc15m', mode: 'paper', status: 'running',
  realized_pnl: 1, closed_trades: 4, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [],
  stake: null, max_positions: null, backtest: {out_of_sample: null}, ...over});
const deployBoard = async (deps) => {
  const f = frontend({fetchImpl: (path) => path === '/api/deployments' ? response({deployments: deps, open_positions: []}) : response({})});
  f.location.pathname = '/deploy';
  await f.viewDeploy(); for (let i = 0; i < 6; i++) await flush();
  const html = f.root.querySelector('#deps').innerHTML;
  f.clearTimers();
  return html;
};

test('a strategy page with no stake drops the stake dial and the pace line, and sends no stake', async () => {
  const deps = [nullStakeDep({stake: 5})];
  const detail = detailStrategy({stake: null, max_positions: null, deployments: deps});
  const bodies = [];
  const f = strategyFrontend(detail, (path, options) => {
    if (path === '/api/strategies/42/whatif') { bodies.push(JSON.parse(options.body)); return response({in_sample: metrics(1), out_of_sample: metrics(2), equity: [[100, 0]], gates: [], passed: true}); }
    return response({});
  });
  await f.viewStrategy(42); await flush();
  const main = f.root.querySelector('#main').innerHTML;
  assert.match(main, /Since deploying/);
  assert.doesNotMatch(main, /NaN|null|undefined|\$ a trade|unseen-data pace/);
  const whatif = f.root.querySelector('#whatif');
  assert.equal(whatif.querySelector('#wk'), null);
  whatif.querySelector('#wf').value = '2';
  whatif.querySelector('#wf').oninput();
  await [...f.timeouts.values()].at(-1)();
  assert.deepEqual(bodies, [{fee_multiplier: 2, slippage_cents: 0}]);
  assert.match(whatif.querySelector('#wflash').innerHTML, /under these conditions/);
  f.clearTimers();
  // With a stake, a deployment that has none is scaled at the strategy's own: 4 trades at +$2 each.
  const g = strategyFrontend(detailStrategy({deployments: deps.map((d) => ({...d, stake: null}))}), () => response({}));
  await g.viewStrategy(42); await flush();
  const real = g.root.querySelector('#main').innerHTML;
  assert.match(real, /later-period pace \(unseen data\), 4 trades would have made \+\$8\.00/);
  assert.doesNotMatch(real, /NaN/);
  assert.ok(g.root.querySelector('#whatif #wk'), 'a strategy with a stake keeps its dial');
  g.clearTimers();
});

test('a Deploy row and a dashboard monitor with no stake say so instead of "$ / trade"', async () => {
  const html = await deployBoard([nullStakeDep({id: 1, title: 'Neither'}), nullStakeDep({id: 2, title: 'Cap only', max_positions: 3}),
    nullStakeDep({id: 3, title: 'Both', stake: 5, max_positions: 3})]);
  // Walk 2026-10-27 at 390px: "Max 2" ended a line and "open" began the next. Stake and cap each stay whole.
  assert.match(html, /Neither<\/a>\s*<div class="dep-meta"><span class="sub-fig">BTC[^<]*\u00a0· <span class="nobr">Stake not <span class="nobr">set<button[^>]*data-glo="stake"[\s\S]*?<\/button><\/span><\/span><\/span>/);
  assert.match(html, /Cap only<\/a>\s*<div class="dep-meta"><span class="sub-fig">[^<]*\u00a0· <span class="nobr">Stake not <span class="nobr">set<button[^>]*data-glo="stake"[\s\S]*?<\/button><\/span><\/span>\u00a0· <span class="nobr">Max 3 open<\/span><\/span>/);
  assert.match(html, /Both<\/a>\s*<div class="dep-meta"><span class="sub-fig">[^<]*\u00a0· <span class="nobr">\$5 \/ trade<\/span>\u00a0· <span class="nobr">Max 3 open<\/span><\/span>/);
  assert.doesNotMatch(html, /\$ \/ trade|Max\s+open|null|NaN/);
  const f = frontend();
  const none = f.deploymentMonitor(nullStakeDep({status: 'paused', status_why: 'You paused it'}));
  // The card's setup and limits lines (inline) keep the stake and the cap whole, each "·" ending its line.
  assert.match(none, /<p class="monitor-setup">[^<]*\u00a0· <span class="nobr">Stake not <span class="nobr">set<button[^>]*data-glo="stake"[\s\S]*?<\/button><\/span><\/span><\/p><div class="monitor-limits"><span>\u00a0· You paused it<\/span>/);
  assert.doesNotMatch(none, /\$ \/ trade|Max\s+open|null|NaN/);
  assert.match(f.deploymentMonitor(nullStakeDep({stake: 5, max_positions: 3})), /\$5 \/ trade<\/span><\/p><div class="monitor-limits"><span>\u00a0· <span class="nobr">Max 3 open<\/span><\/span>/);
});

test('a Deploy row and a dashboard monitor write a stake to the cent unless it is whole dollars', async () => {
  // Walk 2026-10-31: a $7.50 stake read "$7.5 / trade" on Deploy and the dashboard's monitor card.
  const html = await deployBoard([nullStakeDep({id: 1, title: 'Half', stake: 7.5, max_positions: 4}),
    nullStakeDep({id: 2, title: 'Whole', stake: 25, max_positions: 4}), nullStakeDep({id: 3, title: 'Odd', stake: 12.125, max_positions: 4})]);
  assert.match(html, /Half<\/a>\s*<div class="dep-meta"><span class="sub-fig">[^<]*\u00a0· <span class="nobr">\$7\.50 \/ trade<\/span>/);
  assert.match(html, /Whole<\/a>\s*<div class="dep-meta"><span class="sub-fig">[^<]*\u00a0· <span class="nobr">\$25 \/ trade<\/span>/);
  assert.match(html, /Odd<\/a>\s*<div class="dep-meta"><span class="sub-fig">[^<]*\u00a0· <span class="nobr">\$12\.13 \/ trade<\/span>/);
  assert.doesNotMatch(html, /\$7\.5 |\$12\.125|NaN/);
  const f = frontend();
  assert.match(f.deploymentMonitor(nullStakeDep({stake: 7.5, max_positions: 3})), /\$7\.50 \/ trade<\/span><\/p>/);
});

test('Meridian: a paper card on the dashboard says "after Kalshi fees and the spread" as the small explainer it is elsewhere', () => {
  const f = frontend();
  const html = f.deploymentMonitor(nullStakeDep({mode: 'paper', status: 'running', stake: 5}));
  // The phrase (customer_text.PAPER_NET) with its PAPER_FILLS bubble, under the P&L, not a 20px figure of its own.
  assert.match(html, /<dd class="sub-fig paper-net">after Kalshi fees and the <span class="nobr">spread<button type="button" class="info" data-glo="paperfills"[\s\S]*?<\/button><\/span><\/dd>/);
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\n\.monitor-metrics dd\.paper-net, \.monitor-metrics dd\.book-net \{[^}]*font: 400 12px\/16px var\(--f-ui\);[^}]*color: var\(--ink-3\);/);
  assert.doesNotMatch(f.deploymentMonitor(nullStakeDep({mode: 'live', status: 'running', stake: 5})), /paper-net/);
});

test('Meridian: an untitled session row leaves its market to the Market column, not the title too', async () => {
  // Walk 2026-10-30: "Momentum · BTC 15-min up/down" in the title beside a Market column saying "BTC 15-min up/down".
  const untitled = {...researchRun(7, 'succeeded'), prompt: '', title: null, direction: 'momentum'};
  const titled = {...researchRun(8, 'succeeded')};
  const f = researchFrontend([untitled, titled]); await f.viewResearch(); await flush();
  const row = (id) => f.root.querySelector('#runs').children.find((el) => el.getAttribute('href') === `/research/${id}`);
  const title = row(7).querySelector('.run-title b');
  assert.equal(title.textContent, 'Momentum');
  assert.doesNotMatch(row(7).querySelector('.run-title').innerHTML, /BTC 15-min/);
  assert.match(row(7).querySelector('.run-meta').textContent, /BTC 15-min up\/down/);
  // A typed idea is its own title, the market still in its column.
  assert.equal(row(8).querySelector('.run-title b').textContent, 'Idea 8');
  assert.match(row(8).querySelector('.run-meta').textContent, /BTC 15-min up\/down/);
  // No idea and no angle: its number is the title, said once, not a bare "Session" over "Session 21".
  const bare = {...researchRun(11, 'succeeded'), prompt: '', title: null, direction: null};
  const g = researchFrontend([bare]); await g.viewResearch(); await flush();
  const only = g.root.querySelector('#runs').children.find((el) => el.getAttribute('href') === '/research/11');
  assert.equal(only.querySelector('.run-title b').textContent, 'Session 21');
  assert.equal(only.querySelector('.run-id'), null);
  assert.match(only.querySelector('.run-meta').textContent, /BTC 15-min up\/down/);
  g.clearTimers();
  f.clearTimers();
});

test('Meridian: a research session the autopilot started says so on the active card, the list and its page', async () => {
  const ap = {...researchRun(15, 'running'), by_autopilot: 1};
  const apDone = {...researchRun(14, 'succeeded'), by_autopilot: 1};
  const mine = {...researchRun(9, 'succeeded'), by_autopilot: 0, direction: 'momentum'};
  const example = {...researchRun(1, 'succeeded'), by_autopilot: 0, example: true, direction: 'random_walk'};
  const f = researchFrontend([ap, apDone, mine, example]); await f.viewResearch(); await flush();
  const active = f.root.querySelector('#active-research'), history = f.root.querySelector('#runs');
  assert.equal(active.querySelector('.active-session b').textContent, 'Session 25');  // its per-user number (seq), not run 15
  assert.match(active.querySelector('.active-session').innerHTML, /title="The autopilot started this session\.">Autopilot<\/span>/);
  assert.match(history.querySelector('a[href="/research/14"] .run-title').innerHTML, /Autopilot<\/span>/);
  for (const id of [9, 1]) assert.doesNotMatch(history.querySelector(`a[href="/research/${id}"] .run-title`).innerHTML, /Autopilot<\/span>/);
  assert.match(history.querySelector('a[href="/research/1"] .run-title').innerHTML, /Example<\/span>/);
  f.clearTimers();
  for (const [run, said, not] of [[ap, /BTC 15-min up\/down · Started by autopilot/, /· Session/],
    [{...ap, direction: 'momentum'}, /· Momentum · Started by autopilot/, /· Session/],
    [mine, /· Momentum/, /Started by autopilot/], [{...ap, by_autopilot: 0}, /BTC 15-min up\/down/, /Started by autopilot|· Session/]]) {
    const g = frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/' + run.id)); return response({run, events: []}); }});
    g.S.me.directions = [{key: 'momentum', label: 'Momentum', brief: ''}];
    await g.viewRun(run.id);
    const head = g.root.querySelector('#runboard').innerHTML.replace(/ /g, ' ');
    assert.match(head, said); assert.doesNotMatch(head, not);
    g.clearTimers();
  }
});

test('Meridian: a research start that moved off a cooldown market is the autopilot\'s last move, in customer words', () => {
  const f = frontend();
  const line = 'Started a fresh research session on a market the research specialist picks. Bitcoin 15-minute was researched in the last few hours, so this angle goes to one that isn\'t on cooldown. Follow it on the Research page.';
  assert.equal(f.apMoveText({text: line, at: new Date().toISOString()}), 'Started a fresh research session on a market the research specialist picks');
});

test('Meridian: a strategy that did not pass shows its backtest P&L muted, at the size of the others, never in the gain green', () => {
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\n\.t-strat \.pnl-nopass \{ color: var\(--ink-3\);/);
  assert.match(css, /\.t-strat td\.num \.loss, \.t-strat td\.num \.pnl-nopass \{ font-size: 16px; font-weight: 500; \}/);
});

// After every helper it reads (billingPage, the dashboard and autopilot fixtures) is defined.
firstHourCases({name: 'Meridian', frontend, billingPage, cardedBilling, dashboard: dashboardData, apStatus, fundsData: funds});
firstTenMinutesCases({name: 'Meridian', frontend, dashboard: dashboardData, apStatus, billingPage, cardedBilling});
fundsTrustCases({name: 'Meridian', frontend, fundsData: funds, dashboard: dashboardData, detailStrategy, strategyFrontend});
fundsWalkCases({name: 'Meridian', frontend, fundsData: funds, dashboard: dashboardData, detailStrategy, strategyFrontend});
fundsHistoryCases({name: 'Meridian', frontend, fundsData: funds});
chatPanelCases({name: 'Meridian', frontend, storageFor: m => m});
a11yCases({name: 'Meridian', frontend, storageFor: m => m, billingPage, cardedBilling, source, strategyFrontend, detailStrategy,
  dashboard: dashboardData, fundsData: funds, apStatus});
creditsCases({name: 'Meridian', frontend, billingPage, cardedBilling, dashboard: dashboardData, apStatus});
writeWaitCases({name: 'Meridian', frontend, billingPage, cardedBilling, postRequests, storageFor: m => m});
declinedCardCases({name: 'Meridian', frontend, dashboard: dashboardData});
flakyNetworkCases({name: 'Meridian', frontend});
deployErrorCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, postRequests});
liveHonestCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, dashboard: dashboardData});
freshWalkCases({name: 'Meridian', frontend, dashboard: dashboardData});
newcomerMoneyCases({name: 'Meridian', frontend, dashboard: dashboardData});
unrealizedCellCases({name: 'Meridian', frontend, dashboard: dashboardData});
unmarkedPositionCases({name: 'Meridian', frontend});
moneyAgreementCases({name: 'Meridian', frontend});
pastCloseCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, dashboard: dashboardData});
moneyPagesWalkCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, dashboard: dashboardData});
staleMarkCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, dashboard: dashboardData});
moneyDisplayCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, dashboard: dashboardData, hotRail: (f, markets) => {
  f.root.innerHTML = '<aside id="hotrail"></aside>'; f.S.hot = {at: new Date().toISOString(), markets}; f.renderHotRail();
  return f.root.querySelector('#hotrail').innerHTML;
}});
slippageEstimateCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, dashboard: dashboardData});

test('the strategies sort shows "Later-period P&L" whole, and the filter row still fits one line at 1366', () => {
  // Measured in DM Sans 14px: the label is ~110px of text, whole in the 175px select the market filter has. The
  // 25px #571 took from the market filter and the search for "P&L on data it never saw" went back to them.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  const px = (re) => { const m = css.match(re); return m ? +m[1] : null; };
  const both = px(/\n\.stratfilters \.strat-mkt \{ flex-basis: (\d+)px; max-width: \1px; \}/);
  const search = px(/\n\.stratfilters \.searchwrap \{ flex: 0 1 (\d+)px; margin-left: auto; \}/);
  assert.ok(both >= 150, String(both));  // ~110px of label, the select's padding and its arrow
  assert.doesNotMatch(css, /\n\.stratfilters (?:\.strat-sort|#strat-market) \{/);  // one width for both selects
  assert.ok(both * 2 + search <= 175 + 175 + 220, `${both} x 2 + ${search}`);
  assert.ok(search >= 205, 'its placeholder, "Search name or thesis…", stays whole');
});

test('a research row’s Outcome column holds "+12 passed, not cleared" on one line', () => {
  // At 112px the uncleared line took two at 1280px. Measured in DM Sans 12px: "+12 passed, not cleared" is ~130px.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  const grid = css.match(/\n\.research-history \.run-card, \.run-columns \{[^}]*grid-template-columns: minmax\(0, 1fr\) 120px 88px (\d+)px;/);
  assert.ok(grid && +grid[1] >= 136, grid && grid[1]);
  const f = frontend();
  const row = f.runRow({id: 1, status: 'succeeded', market: 'btc15m', direction: 'momentum', example: false, prompt: 'Idea',
    hypotheses_tried: 40, strategies_passed: 13, not_cleared: 12, spent_usd: 1, error: null, created_at: '2026-10-25T08:00:00Z', stop_reason: 'limit'});
  assert.match(row, /<span class="run-denominator run-fell">\+12 passed, not cleared<\/span>/);
});

test('the hot rail wraps a market’s name instead of cutting its close hour, and a Deploy row’s link reads as a link', () => {
  // The rail's name column is ~80px: "BTC above $X at 5pm ET" read "BTC above…", the hour lost.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  const rules = [...css.matchAll(/\n\.hot-title strong \{([^}]*)\}/g)].map((m) => m[1]);
  const last = (prop) => rules.map((r) => (r.match(new RegExp('(?:^|;)\\s*' + prop + ':\\s*([^;]+)')) || [])[1]).filter(Boolean).at(-1);
  assert.equal(last('white-space'), 'normal');
  assert.equal(last('-webkit-line-clamp'), '3');
  const f = frontend();
  f.S.me.markets = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin above a set price at 5pm ET', close_hour_et: 17}];
  f.root.innerHTML = '<aside id="hotrail"></aside>';
  f.S.hot = {at: new Date().toISOString(), markets: [{t: 'KXBTCD-26OCT2717-T112999.99', s: 'KXBTCD', ti: 'Bitcoin price at 5pm EDT?', su: '$113,000 or above', bid: .5, ask: .52, v24: 10, oi: 0}]};
  f.renderHotRail();
  assert.equal(f.root.querySelector('.hot-title strong').textContent, 'BTC above set price at 5pm ET', 'the whole name, its hour included');
  // A pause reason's "the Funds page" in a Deploy row is underlined; the row's strategy name still isn't.
  assert.match(css, /\n\.t-dep td\.name \.sub-fig a, \.monitor-limits a \{ text-decoration: underline;/);
});

test('an Overview demo or live monitor names its book and fees under Realized P&L, as a paper one does', async () => {
  // Walk 2026-10-27 (paper + a demo key): a demo monitor read "Realized P&L +$2.17" with nothing under it, while each
  // paper one said "after Kalshi fees and the spread". It says its book and fees, as the strategy page's book lines do.
  const deployments = [{...dashboardDeployment('demo'), id: 71, closed_trades: 1, realized_pnl: 2.17},
    {...dashboardDeployment('live'), id: 72, closed_trades: 2, realized_pnl: -1.5},
    {...dashboardDeployment('demo'), id: 73, closed_trades: 0, realized_pnl: 0}];
  const f = frontend({fetchImpl: () => response(dashboardData({deployments}))});
  await f.viewDashboard();
  const notes = [...f.root.querySelectorAll('#dash-deps article.dep-monitor .monitor-realized')].map((m) => {
    const n = m.querySelector('.book-net'); return n ? n.textContent : null;
  });
  assert.deepEqual(notes, ['after Kalshi fees, in Tau’s demo book: not real money', 'real money, after Kalshi fees', null]);
});

test('Overview’s day figures name their book, and a trades CSV link never breaks inside', async () => {
  // Walk 2026-10-27 (a live key, live trading closed): the paper band's "Realized today (UTC) −$0.57" sat above the
  // Kalshi cash band and didn't say it was paper's; at 1280 "Download" ended a line and "trades (CSV)" began the next.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\na\.csv-link \{ white-space: nowrap; \}/);
  const tau = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  assert.match(tau, /\na\.csv-link \{ white-space: nowrap; \}/);
  const f = frontend({fetchImpl: () => response(dashboardData({paper: {equity: 999.36, cash: 994.66, realized_pnl: -0.57, today_pnl: -0.57,
    closed_trades: 4, open_positions: 0, total_pnl: -0.57}}))});
  await f.viewDashboard();
  const html = f.root.querySelector('#main').innerHTML;
  assert.match(html, /<span class="lab"><span class="pnl-win">Today \(UTC\):<\/span> paper realized<\/span>/);
  assert.doesNotMatch(html, /<span class="lab">Realized today/);
});

test('an Overview paper monitor says how many of its closed trades were instant fills', async () => {
  // Walk 2026-10-27: a paper monitor read "Closed / open 2 / 0" with no word that the track record and the count of
  // realistic paper trades toward live leave its instant fills out. The server's `instant_fills` says how many.
  const deployments = [{...dashboardDeployment('paper'), id: 93, closed_trades: 2, instant_fills: 1},
    {...dashboardDeployment('paper'), id: 94, closed_trades: 2, instant_fills: 2},
    {...dashboardDeployment('paper'), id: 95, closed_trades: 1, instant_fills: 1},
    {...dashboardDeployment('paper'), id: 96, closed_trades: 2},
    {...dashboardDeployment('demo'), id: 97, closed_trades: 2, instant_fills: 2}];
  const f = frontend({fetchImpl: () => response(dashboardData({deployments}))});
  await f.viewDashboard();
  const monitors = f.root.querySelectorAll('#dash-deps article.dep-monitor'); assert.equal(monitors.length, 5);
  const html = (m) => { const el = m.querySelector('.monitor-config .dep-instant'); return el ? el.innerHTML : null; };
  // The note's words, less the instant-fill bubble glued to its last word ("live."), which each note carries.
  const line = (m) => { const h = html(m); return h == null ? null : h.replace(/<button[\s\S]*?<\/button>/g, '').replace(/<[^>]*>/g, ''); };
  const tail = ', left out of the track record and of the count of realistic paper trades toward live.';
  assert.deepEqual(monitors.map(line), ['1 of its 2 closed trades was an instant fill' + tail, 'All 2 of its closed trades were instant fills' + tail,
    'Its 1 closed trade was an instant fill' + tail, null, null]);
  for (const m of monitors.slice(0, 3)) assert.match(html(m), /toward <span class="nobr">live\.<button type="button" class="info" data-glo="instantfill"/);
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\n\.monitor-config \.dep-instant \{ margin: 4px 0 10px; white-space: normal; \}/);
});

test('a backtest-only strategy’s Deploy row says "Later-period P&L · not held out", never unseen', async () => {
  // Its out_of_sample is the old loose gate's later slice, which picked it (#590's strategy-page words); the server says
  // so per row (backtest_only, from the strategy's status in the row's own read).
  const row = (o) => ({id: 11, strategy_id: 111, title: 'S', market: 'btc15m', mode: 'paper', status: 'running', stake: 5, max_positions: 2,
    backtest: {out_of_sample: {pnl: 12, trades: 20}}, created_at: '2026-10-17T10:00:00Z', realized_pnl: 3, unrealized_pnl: null,
    closed_trades: 2, open_positions: 0, curve: [], ...o});
  const f = frontend({fetchImpl: () => response({deployments: [row({backtest_only: true}), row({id: 12, strategy_id: 112, backtest_only: false})], open_positions: []})});
  await f.viewDeploy();
  const html = f.root.querySelector('#deps').innerHTML;
  assert.match(html, /<span class="dep-fact" title="After its split date, which picked it \(later period\u00a0· not held out\)">Later-period P&amp;L \+\$12\.00<\/span>\u00a0· <span class="nobr">not\u00a0held\u00a0out<button[^>]*data-glo="laterperiod"[\s\S]*?<\/button><\/span>\u00a0· /);
  // The held-out one's hover says the family's other half, as Tau's Backtest estimate hover does: it had none.
  assert.match(html, /<span class="dep-fact" title="After its split date \(later period\u00a0· unseen data\)">Later-period P&amp;L \+\$12\.00<\/span>\u00a0· <span class="nobr">unseen\u00a0data<button[^>]*data-glo="unseen"[\s\S]*?<\/button><\/span>\u00a0· /);
  assert.doesNotMatch(html, /picked it: not held out|on unseen data/);
  assert.equal((html.match(/unseen\u00a0data/g) || []).length, 1, 'only the strategy with a gatekeeper record says unseen');
  assert.equal((visible(html).match(/Later-period P&amp;L \+\$12\.00<\/span>/g) || []).length, 2, 'both name the figure as the Strategies list does');
  assert.doesNotMatch(html, /Unseen P&amp;L/);
});

test('a Void strategy with no gatekeeper record’s Deploy row says "not held out", without "which picked it"', async () => {
  // The first version's simple backtest stored it as Void with no record: its details said "· unseen data". The server
  // sends backtest_only and void_no_record; nothing picked a void one, as its Strategies row and page say.
  const row = (o) => ({id: 11, strategy_id: 111, title: 'S', market: 'btc15m', mode: 'paper', status: 'running', stake: 5, max_positions: 2,
    backtest: {out_of_sample: {pnl: 12, trades: 20}}, created_at: '2026-10-17T10:00:00Z', realized_pnl: 3, unrealized_pnl: null,
    closed_trades: 2, open_positions: 0, curve: [], ...o});
  const f = frontend({fetchImpl: () => response({deployments: [row({backtest_only: true, void_no_record: true})], open_positions: []})});
  await f.viewDeploy();
  const html = f.root.querySelector('#deps').innerHTML;
  assert.match(html, /<span class="dep-fact" title="After its split date \(later period\u00a0· not held out\)">Later-period P&amp;L \+\$12\.00<\/span>\u00a0· <span class="nobr">not\u00a0held\u00a0out<button[^>]*data-glo="latervoid"[\s\S]*?<\/button><\/span>\u00a0· /);
  assert.doesNotMatch(html, /unseen|picked it/i);
});

test('an Overview monitor’s details say "Later-period P&L · not held out" for a strategy whose page does, never unseen', async () => {
  // Walk 2026-10-27: a passed strategy with no gatekeeper record, whose page reads "Later-period P&L … after the split
  // date, which picked it: not held out", had "Unseen P&L +$0.90" in its Overview details. The server's backtest_only
  // now covers it (and backtest-only ones); a strategy with a record says "unseen data" after the same label, as the
  // Strategies list does ("later period · unseen data"): it read "Unseen P&L" here alone.
  const bt = {backtest: {out_of_sample: {pnl: 0.9, trades: 60}}};
  const deployments = [{...dashboardDeployment('paper'), id: 81, ...bt, backtest_only: true},
    {...dashboardDeployment('paper'), id: 82, ...bt, backtest_only: false}];
  const f = frontend({fetchImpl: () => response(dashboardData({deployments}))});
  await f.viewDashboard();
  const facts = [...f.root.querySelectorAll('#dash-deps article.dep-monitor .dep-evidence')].map((d) => d.textContent);
  assert.equal(facts.length, 2);
  assert.match(facts[0], /Later-period P&(amp;)?L \+\$0\.90\u00a0· not\u00a0held\u00a0out/); assert.doesNotMatch(facts[0], /unseen/i);
  assert.match(facts[1], /Later-period P&(amp;)?L \+\$0\.90\u00a0· unseen\u00a0data/); assert.doesNotMatch(facts[1], /Unseen P&/);
});

test('a Deploy row’s details keep "Deployed" with its date and "Later-period P&L" with its figure', async () => {
  // Walk 2026-10-27: "· Deployed" ended one line of a row's details and "Oct 18" began the next, at 390px and in
  // the 1280px table's name column. Each fact is one .dep-fact span, which never wraps inside.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\n\.dep-evidence \.dep-fact \{ white-space: nowrap; \}/);
  const f = frontend({fetchImpl: () => response({deployments: [{id: 11, strategy_id: 111, title: 'S', market: 'btc15m', mode: 'paper',
    status: 'running', stake: 5, max_positions: 2, backtest: {out_of_sample: {pnl: 12, trades: 20}}, created_at: '2026-10-17T10:00:00Z',
    realized_pnl: 3, unrealized_pnl: null, closed_trades: 2, open_positions: 0, curve: []}], open_positions: []})});
  await f.viewDeploy();
  const html = f.root.querySelector('#deps').innerHTML;
  assert.match(html, /Backtest estimate \+\$1\.20 for the same 2 trades · <span class="dep-fact" title="After its split date \(later period\u00a0· unseen data\)">Later-period P&amp;L \+\$12\.00<\/span> · <span class="nobr">unseen data<button[^>]*data-glo="unseen"[\s\S]*?<\/button><\/span> · <span class="dep-fact">Deployed [^<]+<\/span>/);
});
newUserCases({name: 'Meridian', frontend, strategyFrontend, detailStrategy, dashboard: dashboardData, billingPage, cardedBilling, apStatus});
firstSessionCases({name: 'Meridian', frontend, dashboard: dashboardData, apStatus, storageFor: m => m});
checkinCadenceCases({name: 'Meridian', frontend, detailStrategy, strategyFrontend, dashboard: dashboardData});

test('a Share my P&L card lines its Paper and Live labels up at the top', () => {
  // Walk 2026-10-27: Paper's figure carries "on 17 trades" under it, so with the row aligned to the bottom
  // "Live (real money)" sat 16px below "Paper".
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\n\.feedwrap \.snap-pnl \.snap-metrics \{ align-items: start; \}/);
  const f = frontend();
  assert.match(f.postSnapshot({kind: 'pnl', paper_pnl: 12.34, live_pnl: 0, paper_trades: 17, live_trades: 0}), /^<div class="snap snap-pnl">[\s\S]*<dl class="snap-metrics">/);
});

test('Meridian Billing: the default card’s mark in its table is a plain word, not a padless filled box', () => {
  // Walk 2026-10-28: ".t-dep .mk" drops a mark's padding and border, and ".mk.on" kept its dark fill, so "Default"
  // sat in a black box tight to its letters.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.t-dep \.mk:not\(\.live\):not\(\.armed\) \{ padding: 0; border: 0;/);
  assert.match(css, /\.t-dep \.mk\.on \{ background: none; color: var\(--ink\); \}/);
});

test('Meridian Research: the outlined New session button stays readable when hovered or tapped', () => {
  // Walk 2026-10-28: the button is a .btn.primary drawn outlined (transparent, ink text). .btn.primary:hover turned
  // it black and kept the dark ink text, so on hover, and after a tap on a phone, "New session" all but vanished.
  const css = readFileSync(new URL('../app/static/app.meridian.css', import.meta.url), 'utf8');
  assert.match(css, /\.research-page \.research-create > summary \{[^}]*background: transparent;[^}]*color: var\(--ink\); \}/);
  assert.match(css, /\n\.research-page \.research-create > summary:hover \{ background: var\(--ink\); color: #F1F3ED; \}/);
});

test('Meridian: the Passed filter with nothing passed says so and offers a new session, not "Try another filter"', async () => {
  // A first session where every idea failed: the dashboard's "See passed strategies" opens /strategies?status=passed.
  const f = frontend({search: '?status=passed', fetchImpl: path => (path.startsWith('/api/strategies?')
    ? response({strategies: [], counts: {total: 2, passed: 0, failed: 0, rejected: 2}}) : response({}))});
  f.S.me.user.autopilot = false;
  await f.viewStrategies(); await flush(); await flush();
  const empty = f.root.querySelector('#slips .empty');
  assert.equal(empty.querySelector('h3').textContent, 'No strategy has passed yet');
  assert.doesNotMatch(empty.innerHTML, /Try another filter/);
  assert.deepEqual(empty.querySelectorAll('a.btn').map(a => a.getAttribute('href')), ['/research?new=1']);
  // Another filter that matches nothing still says to try another.
  const g = frontend({search: '?status=passed&market=nba', fetchImpl: path => (path.startsWith('/api/strategies?')
    ? response({strategies: [], counts: {total: 3, passed: 1, failed: 1, rejected: 1}}) : response({}))});
  await g.viewStrategies(); await flush(); await flush();
  assert.match(g.root.querySelector('#slips .empty').innerHTML, /<h3>No matching strategies<\/h3><p>Try another filter\.<\/p>/);
});
