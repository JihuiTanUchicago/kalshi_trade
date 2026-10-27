import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import vm from 'node:vm';
import {perpsFrontendCases} from './kalshi_perps_frontend_cases.mjs';
import {deployActionCases} from './deploy_actions_frontend_cases.mjs';
import {stopReasonCases} from './stop_reason_frontend_cases.mjs';
import {trustGlitchCases} from './trust_glitch_frontend_cases.mjs';
import {bellCases} from './bell_frontend_cases.mjs';
import {communityCases} from './community_frontend_cases.mjs';
import {researchPollCases} from './research_poll_frontend_cases.mjs';
import {runPageCases} from './run_page_frontend_cases.mjs';
import {moneyPollCases} from './money_poll_frontend_cases.mjs';
import {strategyPageCases} from './strategy_page_frontend_cases.mjs';
import {strategyListCases} from './strategy_list_frontend_cases.mjs';
import {explorePageCases} from './explore_page_frontend_cases.mjs';
import {phoneSpeedCases} from './phone_speed_frontend_cases.mjs';
import {settingsCases} from './settings_frontend_cases.mjs';
import {firstHourCases} from './first_hour_frontend_cases.mjs';
import {chatPanelCases} from './chat_panel_frontend_cases.mjs';
import {creditsCases, declinedCardCases} from './credits_frontend_cases.mjs';
import {researchFormCases} from './research_form_frontend_cases.mjs';
import {a11yCases} from './a11y_frontend_cases.mjs';

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
  // Records the focus a script hands it, so a check can say where a keyboard user was left.
  focus(options) { this.focusOptions = options; this.focused = true; }
  remove() { this.removed = true; }
  // Puts the markup's one element in this one's place in its parent, as the DOM does; either one reads
  // back the markup it was given.
  get outerHTML() { return this.outer; }
  set outerHTML(value) {
    this.outer = value;
    const holder = new Element('div'); holder.innerHTML = value;
    const fresh = holder.children[0], parent = this.parent;
    if (!fresh || !parent) return;
    fresh.outer = value; fresh.parent = parent; parent.children[parent.children.indexOf(this)] = fresh; this.removed = true;
  }
}

function frontend({fetchImpl, brokerMount, storage, session, stripe, matchMedia = () => ({matches: false}), notifications, win = {}, globals = {}} = {}) {
  const root = new Element('div', {id: 'app'}), body = new Element('body'); body.appendChild(root);
  const intervals = new Map(), timeouts = new Map(), requests = [], navigations = [], reloads = [];
  const delays = new Map();
  // Runs the pending timers set for at most `ms` (an armed confirm's hold, say) and leaves the longer ones.
  const elapse = ms => { for (const [id, run] of [...timeouts]) if ((delays.get(id) || 0) <= ms) { timeouts.delete(id); run(); } };
  let nextId = 0;
  const location = {pathname: '/strategies/42', search: '', origin: 'http://offline.invalid', reload: () => reloads.push(true)};
  const navigate = (_state, _title, path) => { navigations.push(path); const [p, q] = String(path).split('?'); location.pathname = p; location.search = q ? '?' + q : ''; };
  const context = vm.createContext({
    Intl, URL, URLSearchParams, AbortController,
    document: {body, getElementById: id => body.querySelector('#' + id), addEventListener() {}, removeEventListener() {}, createElement: tag => new Element(tag)},
    window: {addEventListener() {}, scrollTo() {}, matchMedia,
      ...(brokerMount ? {TauBrokerConnections: {mount: brokerMount}} : {}), ...(stripe ? {Stripe: stripe} : {}), ...win},
    addEventListener() {}, location, history: {pushState: navigate, replaceState: navigate},
    localStorage: storage || {getItem: () => null, setItem() {}},
    ...(session ? {sessionStorage: session} : {}),
    setInterval: callback => { intervals.set(++nextId, callback); return nextId; },
    clearInterval: id => intervals.delete(id),
    setTimeout: (callback, ms = 0) => { timeouts.set(++nextId, callback); delays.set(nextId, ms); return nextId; },
    clearTimeout: id => timeouts.delete(id),
    fetch: async (path, options) => {
      requests.push({path, options});
      if (path === '/api/notifications') return response(notifications || {unread: 0, items: []});
      if (fetchImpl) return fetchImpl(path, options);
      throw new Error('Unexpected offline request: ' + path);
    },
    ...globals,  // page globals a check stands in for (getComputedStyle, a counting Intl)
  });
  const boot = '  setupGlossary();\n  render();';
  assert.equal(source.split(boot).length, 2, 'the harness replaces only automatic boot');
  vm.runInContext(source.replace(boot, 'globalThis.frontend = {S, api, armed, apMoveText, apPillLabel, apIdleLine, sinceStrip, renderAutopilot, apLoadChat, routes, viewExample, equityChart, runControls, runFeed, clearTimers, runRow, feedMd, viewStrategy, viewStrategies, strategySlip, postSnapshot, viewCommunity, viewRun, viewFunds, viewBilling, viewDashboard, viewDeploy, viewResearch, viewExplore, marketPicker, wireMarketPicker, paintDashAp, apUpdate, apYield, tabEdges, trCurve, trackRecordPanel, mountTrackRecord, viewMarketDetail, viewSystem, viewSettings, render, paymentGate, hotRowHtml, rpUnderwater};'), context);
  const api = context.frontend;
  api.S.me = {user: {id: 7, name: 'Offline fixture'}, markets: [], directions: [], live_trading_available: true, kalshi_connected: true, kalshi_dev_connected: true};
  // Cached global widgets keep these page checks focused. All requests still use
  // the offline transport above, including notifications and financial controls.
  api.S.hot = {markets: []}; api.S.hotAt = Date.now();
  api.S.ap = {mode: 'off'}; api.S.apAt = Date.now();
  // Moves the page's clock (Date.now) forward, for checks on how old a figure is.
  const shiftClock = ms => vm.runInContext(`{ const now = Date.now; Date.now = () => now() + ${Number(ms)}; }`, context);
  return {...api, win: context.window, root, location, document: context.document, window: context.window, intervals, timeouts, elapse, requests, navigations, reloads, shiftClock};
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
deployActionCases({name: 'Tau', frontend, strategyFrontend, detailStrategy, postRequests, source});
stopReasonCases({name: 'Tau', frontend});
trustGlitchCases({name: 'Tau', frontend});
bellCases({name: 'Tau', frontend});
communityCases({name: 'Tau', frontend});
researchPollCases({name: 'Tau', frontend});
runPageCases({name: 'Tau', frontend});
moneyPollCases({name: 'Tau', frontend});
strategyPageCases({name: 'Tau', frontend, detailStrategy, strategyFrontend, postRequests});
strategyListCases({name: 'Tau', frontend, detailStrategy});
explorePageCases({name: 'Tau', frontend});
researchFormCases({name: 'Tau', frontend});
phoneSpeedCases({name: 'Tau', frontend, source, railOpenWide: [['tau_hotrail', '1']],
  storageFor: m => ({getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))})});
settingsCases({name: 'Tau', frontend, current: 'tau', cardWallOpts: () => ({stripe: STRIPE_STUB}),
  storageFor: m => ({getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))})});
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

// Boot fetch budget: the signed-in shell carries /api/me's reply and the page just loaded the current
// build, so the first page's own reads go out at once (before: /api/me and /api/version first).
test('a signed-in shell boots on the account it carries, with no /api/me or /api/version read', async () => {
  const carried = {user: {id: 7, name: 'Carried', ui_theme: 'tau'}, markets: [], directions: []};
  const f = frontend({win: {__TAU_ME__: carried, __BUILD__: 'build-1'}, fetchImpl: path => response(path === '/api/me' ? carried : {})});
  f.S.me = null;
  await f.render(); await flush(); await flush();
  assert.equal(f.S.me, carried);
  const paths = f.requests.map(({path}) => path.split('?')[0]);
  assert.ok(!paths.includes('/api/me') && !paths.includes('/api/version'), paths.join(' '));
  assert.ok(paths.includes('/api/strategies/42'), 'the page read went out');
  // Taken once: a later boot (signed out, then back) asks the server.
  assert.equal(f.window.__TAU_ME__, null);
  f.S.me = null; f.requests.length = 0;
  await f.render(); await flush();
  assert.equal(f.requests[0].path, '/api/me');
});

test('the research page takes its model list from the account instead of waiting on /api/models', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/runs') return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null});
    if (path.startsWith('/api/research/scoreboard') || path === '/api/research/estimate') return response({});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.models = {models: [{key: 'm1', label: 'Model one'}, {key: 'm2', label: 'Model two'}], default: 'm2'};
  f.S.me.user.autopilot = false;
  await f.viewResearch(); await flush(); await flush();
  assert.ok(!f.requests.some(({path}) => path === '/api/models'));
  assert.match(f.root.innerHTML, /<option value="m2" selected>Model two/);
  f.clearTimers();
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
  assert.match(list, /NO ×4 @ 37¢/); assert.match(list, /Cost \+ fee \$1\.50/); assert.match(list, /Unreal\. —/); assert.match(list, /Settles /);
  assert.match(list, /−\$0\.30|-\$0\.30/); assert.match(list, /<span class="mk live">Live<\/span>/);
  assert.doesNotMatch(list, /<x>/); assert.doesNotMatch(output, /<th>Contract<\/th><th>Position<\/th>/);
  // Each holding says why it was bought and how it will exit; one without a reason says nothing.
  assert.deepEqual([...list.matchAll(/<div class="sub-fig pos-why">([^<]*)<\/div>/g)].map((m) => m[1]),
    ['Entered at 60¢: edge ≥ 2¢ after fees · Holds to settlement']);
  // Each contract opens its market page (price, settlement rules, your positions in it).
  assert.match(list, /<a href="\/explore\?m=KXBTC15M-B">KXBTC15M-B<\/a>/); assert.match(list, /href="\/explore\?m=KXBTC15M-%3Cx%3E"/);
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
    let focused = false; form.confirm = {value: '', focus: () => { focused = true; }};
    assert.equal(form.hidden, true); f.root.querySelector('#dep-live').onclick(); assert.equal(form.hidden, false);
    assert.equal(focused, true);  // the typed confirm takes keyboard focus as it opens
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
  const f = frontend({fetchImpl: path => { assert.match(path, /^\/api\/billing(\?|$)/); return response(data); }});
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

const emptyDashboard = () => ({paper: {equity: 1000, cash: 1000, open_at_cost: 0, total_pnl: 12.5, realized_pnl: 12.5},
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
  for (const [autopilot, tried, ask] of [[true, 2, 'add an idea'], [false, 2, 'Seed another idea'], [false, 0, 'Describe an idea']]) {
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
    // The form sits above these figures on a wide screen (it said "below") and after them on a phone.
    assert.doesNotMatch(f.root.querySelector('#rstatus .said').innerHTML, /below|above/);
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
  // The header says what the figure is (Backtest estimate), with a hover title and a glossary marker;
  // a phone's stacked cell keeps the same name and title.
  assert.match(html, /<th class="num" title="What these same closed trades would have made at the backtest’s average per trade on unseen data">Backtest <span class="nobr">estimate<button type="button" class="info" data-glo="pace" aria-label="What does “Backtest estimate” mean\?">/);
  assert.match(html, /<td class="num" data-lab="Backtest estimate" title="What these same closed trades would have made at the backtest’s average per trade on unseen data">\+\$10\.00/);
  assert.doesNotMatch(html, /Test expected/);
  // $12 over 6 unseen trades = $2 a trade, so 5 closed trades -> +$10.00.
  assert.match(html, /\+\$10\.00<div class="sub-fig">same 5 trades<\/div>/);
  // Before the first close the cell names the live paper record that has none, not the backtest.
  assert.match(html, /<span class="sub-fig">no paper trades closed yet<\/span>/);
  assert.doesNotMatch(html, />no closed trades</);
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
  assert.match(table, /data-lab="Contract"><a href="\/explore\?m=T-1">T-1<\/a><div class="sub-fig pos-why">Entered at 41¢: edge ≥ 3¢ after fees/);
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
    if (!on) assert.match(body, /Turn on autopilot above and the strategies that pass every research test/);  // points at the card's switch
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
  // Nothing deployed on this dashboard, so the button skips the empty Deploy board.
  assert.match(panel(), /See passed strategies/); assert.doesNotMatch(panel(), /Go to Deploy/);
  // Switched on elsewhere (another tab, the chat): the next status poll carries it. The record's own
  // poll skips an unchanged payload, so before this the panel kept "Go to Deploy".
  status = {autopilot: true, mode: 'paper', story: [], research: {}, live_running: 0, demo_running: 0, paper_running: 0};
  for (const tick of [...f.intervals.values()]) tick();
  await flush(); await flush();
  assert.equal(f.S.me.user.autopilot, true);
  assert.match(panel(), /Autopilot runs the strategies that pass every research test on paper, with pretend money/); assert.doesNotMatch(panel(), /Go to Deploy/);
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

test('paper P&L on the card and the autopilot card is realized all time, the figure the track record shows', async () => {
  // total_pnl (equity less deposits) took off the open position's entry fee and restarted at a reset:
  // "+$5.19" here beside a "+$5.61" track record, Deploy row and strategy page for one paper book.
  for (const reset_at of [null, '2026-10-20T09:00:00Z']) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') { const d = emptyDashboard(); d.paper = {...d.paper, reset_at, realized_pnl: 9.75, closed_trades: 3}; return response(d); }
      if (path === '/api/autopilot/status') return response(apOn);
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    f.S.ap = apOn; f.paintDashAp();
    assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Paper P&amp;L, realized all time<\/dt><dd><span class="[^"]*">\+\$9\.75/);
    const card = f.root.querySelector('#boardbody').innerHTML;
    assert.match(card, /<span class="amt">\+\$9\.75<\/span> realized all time/);
    assert.doesNotMatch(card + f.root.querySelector('#dash-ap').innerHTML, /12\.50|since reset/);
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
  assert.match(figs, /Kalshi cash/); assert.match(figs, /Your real cash at Kalshi\. Open positions not included/);
  assert.doesNotMatch(figs, /Live money/);
});

test('Funds says when Kalshi cash was read, what each book has open, and matches the dashboard paper figure', async () => {
  const read = new Date(Date.now() - 5 * 60000).toISOString();
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds();
    d.kalshi = {connected: true, key_id: 'abcd-wxyz', balance: 120, balance_at: read, open_positions: 2, open_at_cost: 8.09, funding_url: 'https://kalshi.com'};
    d.demo = {...d.demo, open_positions: 1, open_at_cost: 3.05};
    d.paper = {...d.paper, cash: 991.91, equity: 1000, open_positions: 3, open_at_cost: 8.09}; return response(d); }});
  await f.viewFunds();
  const figs = f.root.querySelector('#ffigs').innerHTML;
  assert.match(figs, /Your real cash at Kalshi, read 5m ago\. 2 open live positions \(\$8\.09 at cost\) not included/);
  assert.match(figs, /\$1,000\.00 capital ·\u00a01 open \(\$3\.05 at cost\) ·\u00a0needs a demo key ·\u00a0real fills/);
  // Paper is the dashboard's figure (cash + open at cost), never cash alone under another name.
  assert.match(figs, /Paper balance[\s\S]*\$1,000\.00[\s\S]*\$991\.91 cash ·\u00a03 open \(\$8\.09 at cost\)/); assert.doesNotMatch(figs, /Paper cash/);
  // Each book stays its own figure: no sum of live, demo and paper anywhere.
  assert.doesNotMatch(figs, /\$1,120|\$2,120|\$1,991/);
  // Nothing open says so; Kalshi not answering says what to do instead of a bare "Unavailable".
  const g = frontend({fetchImpl: () => { const d = funds(); d.kalshi = {connected: true, key_id: 'k', balance: 50, open_positions: 0, open_at_cost: 0}; return response(d); }});
  await g.viewFunds();
  assert.match(g.root.querySelector('#ffigs').innerHTML, /Your real cash at Kalshi\. No open live positions/);
  const h = frontend({fetchImpl: () => { const d = funds(); d.kalshi = {connected: true, key_id: 'k', balance: null, open_positions: 2, open_at_cost: 8}; return response(d); }});
  await h.viewFunds();
  assert.match(h.root.querySelector('#ffigs').innerHTML, /Unavailable[\s\S]*Kalshi didn’t answer just now\. Reload in a minute to try again\./);
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
  assert.match(rows[0], /KXBTC15M-L settled NO<span class="hint"> ·\u00a0lost, paid \$0<\/span>[\s\S]*\$0\.00/);
  assert.match(rows[1], /settled YES<span class="hint"> ·\u00a0won, paid \$1 a contract<\/span>[\s\S]*\+\$25\.00/);
  assert.match(rows[2], /Sold 8\/25 YES KXBTC15M-P at 25¢ \(stop loss, partial\)/);
  assert.match(rows[3], /Paper replay: 10 YES KXBTC15M-R at 40¢ → 55¢ \(take profit\)/);
  assert.match(rows[4], /Bought 25 YES KXBTC15M-W at 40¢<\/td>[\s\S]*−\$10\.42/);
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
  // Each book's realized P&L from its closed trades: the dashboard's, Deploy's and the track record's figure.
  const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); const d = funds();
    d.kalshi = {connected: true, key_id: 'k', balance: 1234.56, open_positions: 1, open_at_cost: 4, realized_pnl: 3.11, closed_trades: 5};
    d.demo = {...d.demo, realized: 9.77, before_reload: 40, closed_trades: 5};
    d.paper = {...d.paper, cash: 995.19, equity: 1005.19, open_positions: 1, open_at_cost: 10, realized_pnl: 5.61, closed_trades: 5}; return response(d); }});
  await f.viewFunds();
  const figs = f.root.querySelector('#ffigs').innerHTML;
  assert.match(figs, /Your real cash at Kalshi\. Tau’s live trades: \+\$3\.11 realized all time\. 1 open live position/);
  assert.match(figs, /1 open \(\$10\.00 at cost\) ·\u00a0\+\$5\.61 realized all time ·\u00a0practice money/);
  assert.match(figs, /\+\$9\.77 realized since reload ·\u00a0needs a demo key/);  // demo's P&L restarts at a reload
  assert.doesNotMatch(figs, /18\.49|15\.38|12\.88|8\.72/);  // no two books added together
  // A book with no closed trade says when its P&L shows, instead of a $0.00 that reads as flat.
  const g = frontend({fetchImpl: () => { const d = funds();
    d.kalshi = {connected: true, key_id: 'k', balance: 50, open_positions: 0, open_at_cost: 0, realized_pnl: 0, closed_trades: 0};
    d.demo = {...d.demo, closed_trades: 0}; d.paper = {...d.paper, realized_pnl: 0, closed_trades: 0}; return response(d); }});
  await g.viewFunds();
  const empty = g.root.querySelector('#ffigs').innerHTML;
  assert.match(empty, /Tau’s live P&amp;L shows once a live trade closes\./);
  assert.match(empty, /P&amp;L shows once a demo trade closes/); assert.match(empty, /P&amp;L shows once a paper trade closes ·\u00a0practice money/);
  assert.doesNotMatch(empty, /realized all time/);
});

test('dashboard: Kalshi cash says when it was read, keeps Tau\'s own trades when Kalshi is down, and an open position says what it is worth', async () => {
  const live = {connected: true, balance: 250, balance_at: new Date().toISOString(), open_positions: 2, running: 1, realized_pnl: 17, today_pnl: -2, open_at_cost: 1.2};
  const pos = {title: 'Drift', ticker: 'KXBTCD-1', side: 'yes', qty: 12, entry_price: .42, entry_fee: .12, mark: .47, value: 5.64, unrealized: .48, mode: 'live', opened_at: '2026-10-25T08:00:00Z'};
  for (const balance of [250, null]) {
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), live: {...live, balance}, open_positions: [pos]});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    const board = f.root.querySelector('#boardbody').innerHTML;
    if (balance) assert.match(board, /Read from Kalshi just now ·\u00a0Tau trades: 2 open \(not in cash\)/);
    else assert.match(board, /Couldn’t read your Kalshi balance just now ·\u00a0Tau trades: 2 open \(not in cash\) ·\u00a0\+\$17\.00 realized all time/);
    assert.match(f.root.querySelector('main').innerHTML, /<span>worth \$5\.64 \(<span class="gain">\+\$0\.48<\/span>\)<\/span>/);
  }
});

test('Deploy realized says it counts only the strategies listed, never summing live with paper', async () => {
  const dep = (id, mode, pnl) => ({id, strategy_id: id, title: 'Dep ' + id, market: 'btc15m', mode, status: 'running', status_reason: null,
    realized_pnl: pnl, closed_trades: 1, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5, max_positions: 1,
    backtest: {out_of_sample: null}});
  for (const [deployments, re] of [[[dep(1, 'paper', 2)], /Realized, deployments listed below[\s\S]*\+\$2\.00[\s\S]*paper money, not real</],
    [[dep(1, 'paper', 2), dep(2, 'live', 5)], /Live realized, deployments listed below[\s\S]*\+\$5\.00[\s\S]*real money ·\u00a0\+\$2\.00 on paper from the deployments listed, counted apart/]]) {
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

test('saving auto-reload on Billing updates the autopilot card\'s auto-reload line at once, with no extra read', async () => {
  const posts = [], storage = {getItem: key => (key === 'tau_ap_open' ? '1' : null), setItem() {}};  // the panel is open
  const f = frontend({stripe: STRIPE_STUB, storage, fetchImpl: (path, options = {}) => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response(cardedBilling({balance: 23.4}));
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    if (path === '/api/billing/auto-reload') { posts.push(JSON.parse(options.body)); return response({ok: true, autoreload_charge: 52.75}); }
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, credit_balance: 23.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = true;
  f.S.ap = {...apOn, week: {research_credits: 7.26, tested: 10, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0, credits_left: 23.4, runway_days: 6.1}};
  const box = new Element('div', {id: 'autopilot-float'}); f.document.body.appendChild(box);
  await f.viewBilling(); await flush(); await flush();
  assert.deepEqual({...f.S.me.auto_reload}, {amount: 25, charge: cardedBilling().autoreload_charge, threshold: 8});
  const reads = () => f.requests.filter(({path}) => /^\/api\/billing(\?|$)/.test(path) || path === '/api/autopilot/status').length, before = reads();
  const amt = f.root.querySelector('#reload-amt'); amt.value = '50'; await amt.onchange(); await flush();
  assert.deepEqual(posts, [{on: true, amount: 50, threshold: 8}]);
  assert.deepEqual({...f.S.me.auto_reload}, {amount: 50, charge: 52.75, threshold: 8});
  assert.match(box.querySelector('#apf-week').innerHTML, /auto-reload adds \$50\.00 at \$8\.00/);
  assert.equal(reads(), before);
  const sw = f.root.querySelector('#autoreload'); sw.checked = false; await sw.onchange(); await flush();
  assert.equal(f.S.me.auto_reload, null);
  assert.doesNotMatch(box.querySelector('#apf-week').innerHTML, /auto-reload adds/);
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
  // The cell says when it last checked in; the switch is the move, said as the switch, not as a review.
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Last check-in<\/dt><dd>Reviewing now<\/dd>/);
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /<p class="ap-last">Last move <time datetime="[^"]+" title="[^"]+">just now<\/time>: Autopilot switched on\.<\/p>/);
  f.S.ap = {...f.S.ap, reviewing: false}; f.paintDashAp();
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /<dt>Last check-in<\/dt><dd>just now<\/dd>/);
});

test('while its paper strategy holds nothing, the autopilot card also says what the autopilot is doing', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = true;
  const flat = {code: 'flat', line: 'Nothing open right now: ETH drift has closed 18 trades on paper and holds no position. It checks again at its market\'s next decision time.', action: null};
  f.S.ap = {...apOn, idle: flat, research: {...apOn.research, active: ['btc15m', 'eth15m']}};
  await f.viewDashboard(); await flush();
  const now = () => f.root.querySelector('#dash-ap .apcard-now').innerHTML;
  assert.match(now(), /holds no position\. It checks again at its market(?:'|&#39;)s next decision time\. Meanwhile it's researching BTC 15-min and ETH 15-min\.$/);
  f.S.ap = {...f.S.ap, research: {...apOn.research, active: ["a market it's still picking"]}}; f.paintDashAp();
  assert.match(now(), /Meanwhile it's picking a market to research\.$/);
  f.S.ap = {...f.S.ap, research: {...apOn.research, active: []}, reviewing: true}; f.paintDashAp();
  assert.match(now(), /Meanwhile it's reviewing the markets to pick its next move\.$/);
  f.S.ap = {...f.S.ap, reviewing: false}; f.paintDashAp();
  assert.match(now(), /next decision time\.$/);  // between runs: nothing to add
  // An idle line that already says what it is doing (nothing on paper) gets nothing added.
  f.S.ap = {...f.S.ap, paper_running: 0, research: {...apOn.research, active: ['btc15m']},
    idle: {code: 'researching', line: 'Nothing is on paper yet: no strategy has passed its research tests. It\'s researching BTC 15-min.', action: null}};
  f.paintDashAp();
  assert.doesNotMatch(now(), /Meanwhile/);
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
  // Any link counts too (walks found the pill on Billing's Add credits link), and the open panel
  // (no pill) never yields.
  f.root.querySelector('a.btn').getBoundingClientRect = rect(250, 800, 370, 830);
  f.apYield(); assert.equal(box.classes.has('yield'), true);
  box.classList.add('yield'); box.innerHTML = '<div class="apf-head"></div>';
  f.apYield(); assert.equal(box.classes.has('yield'), false);
});

test('the floating autopilot pill hit-tests the page a frame after it renders, never inside a page render', () => {
  // elementsFromPoint lays out and pre-paints the page on the spot: run from the pill's render, inside
  // Research's first render, it fixed the form where it stood before the session list moved above it on
  // a phone, and Chrome counted that move as a layout shift of 0.68.
  const frames = [];
  const f = frontend({globals: {requestAnimationFrame: (cb) => frames.push(cb)}}), body = f.root.parent;
  f.root.innerHTML = '<main id="main"><form id="dispatch"><button class="btn primary go" type="submit">Start session</button></form></main>';
  const box = new Element('div', {id: 'autopilot-float', class: 'apf'}); body.appendChild(box);
  const go = f.root.querySelector('#dispatch .go');
  let hits = 0;
  f.document.elementsFromPoint = () => { hits++; return [go]; };
  f.renderAutopilot(box, {mode: 'off'});
  assert.equal(hits, 0, 'no hit test inside the render');
  assert.equal(frames.length, 1);
  const rect = (l, t, r, b) => () => ({left: l, top: t, right: r, bottom: b, width: r - l, height: b - t});
  box.querySelector('.apf-pill').getBoundingClientRect = rect(245, 798, 380, 834);   // 390x844 phone
  go.getBoundingClientRect = rect(31, 798, 359, 840);
  f.renderAutopilot(box, {mode: 'off'});  // the same pill again (the 20s poll): still one check queued
  assert.equal(frames.length, 1);
  frames.shift()();
  assert.ok(hits > 0);
  assert.equal(box.classes.has('yield'), true, 'the pill still steps aside, a frame later');
});

test('the floating autopilot pill steps aside from the Agent log header buttons on the run page', () => {
  const f = frontend(), body = f.root.parent;
  f.root.innerHTML = '<main id="main"><section><div class="section-head"><h2>Agent log</h2><span id="runact"><span class="runact"><button class="btn small" id="pause">Pause</button><button class="btn danger small" id="cancel">Cancel</button></span></span></div></section></main>';
  const box = new Element('div', {id: 'autopilot-float', class: 'apf'}); body.appendChild(box);
  box.innerHTML = '<button type="button" class="apf-pill" data-ap="toggle">Autopilot off</button>';
  const rect = (l, t, r, b) => () => ({left: l, top: t, right: r, bottom: b, width: r - l, height: b - t});
  const none = rect(0, 0, 0, 0), cancel = f.root.querySelector('#cancel');
  f.root.querySelector('#pause').getBoundingClientRect = none;
  box.querySelector('.apf-pill').getBoundingClientRect = rect(245, 798, 380, 834);   // 390x844 phone
  cancel.getBoundingClientRect = rect(300, 800, 374, 836);  // the header scrolled to the foot of the screen
  f.apYield(); assert.equal(box.classes.has('yield'), true);
  cancel.getBoundingClientRect = rect(300, 200, 374, 236);  // scrolled up and away
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
  assert.equal(calls, 2); assert.doesNotMatch(f.root.querySelector('main').innerHTML, /Price history didn’t load/);
});

const OPEN_MARKET = (payload, markets) => {
  const f = frontend({fetchImpl: (path) => path.startsWith('/api/explore/market?') ? response(payload) : response({})});
  if (markets) f.S.me.markets = markets;
  f.ready = f.viewMarketDetail(payload.ticker).then(flush);
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
const readerZone = new Intl.DateTimeFormat(undefined, {timeZoneName: 'short'}).formatToParts(new Date()).find((p) => p.type === 'timeZoneName').value;

test('a market page says what its price is, how it settles and when, and the reader’s positions by money book', async () => {
  const f = OPEN_MARKET(MARKET_PAGE, [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin daily close, 5pm EDT'}]);
  await f.ready;
  const html = f.root.innerHTML;
  // The market's readable name and status in words, not "KXBTCD · active".
  assert.match(html, /Bitcoin daily close, 5pm EDT · Open for trading · KXBTCD-26OCT2617-T113499\.99/); assert.doesNotMatch(html, /· active ·/);
  // The price: a chance, the book it comes from, and when it was read.
  assert.match(html, new RegExp('≈ 56% chance of Yes · bid 55¢ / ask 57¢ · as of [^<]*' + readerZone));
  // Every clock names its zone: Closes, the expected result, the raw table, the chart's axis.
  assert.match(html, new RegExp('Closes</dt><dd><span class="fig ">[^<]*' + readerZone));
  assert.match(html, new RegExp('Result expected [^<]*' + readerZone)); assert.match(f.root.querySelector('#rawsect').innerHTML, new RegExp('Time \\(' + readerZone + '\\)'));
  assert.match(html, new RegExp('class="pc-xlab" text-anchor="end">[^<]*' + readerZone));
  assert.match(html, /If the BRTI average before 5 PM EDT is above 113499\.99/);
  // Live and paper each get their own block and totals; nothing adds them together.
  const live = html.slice(html.indexOf('<span class="mk live">Live</span> real money'), html.indexOf('<span class="mk">Paper</span>'));
  const paper = html.slice(html.indexOf('<span class="mk">Paper</span> paper money, not real'));
  assert.ok(live.length > 0 && paper.length > 0);
  assert.match(live, /1 open at cost \+ fees \$1\.06/); assert.match(live, /\+\$0\.04/); assert.doesNotMatch(live, /\$4\.50/);
  assert.match(paper, /1 open at cost \+ fees \$4\.50/); assert.match(paper, /1 closed · realized <span class="gain">\+\$0\.24/);
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
  assert.match(f.root.innerHTML, /Settled ·\u00a0KXBTCD-26OCT2617-T113499\.99/); assert.doesNotMatch(f.root.innerHTML, /chance of Yes/);
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

test('a shared deployment wears its own book’s badge and says since when', () => {
  const f = frontend(), host = new Element();
  for (const [mode, badge, cls] of [['demo', 'Demo', 'dep'], ['paper', 'Paper', null], ['live', 'Live', 'live']]) {
    host.innerHTML = f.postSnapshot({kind: 'deployment', id: 1, title: 'Fade', market: 'btc15m', mode, realized_pnl: 1.5, closed_trades: 1, since: '2026-10-03T12:00:00Z'});
    const mk = host.querySelector('.snap-head .mk');
    assert.equal(mk.textContent, badge); assert.equal(mk.classList.contains('dep'), cls === 'dep'); assert.equal(mk.classList.contains('live'), cls === 'live');
    assert.match(host.querySelector('.snap-meta').textContent, /1 trade since Oct 3, 2026$/);
  }
});

test('another trader’s shared strategy says whose it is instead of linking to a page the viewer cannot open', () => {
  const f = frontend(), host = new Element();
  const strat = {kind: 'strategy', id: 42, title: 'Fade', market: 'btc15m', status: 'passed', pnl: 42.17, trades: 23, win_rate: .61, days: 9.4};
  host.innerHTML = f.postSnapshot(strat, '@bob');
  assert.equal(host.querySelector('a'), null);
  assert.equal(host.querySelector('.snap-note').textContent, 'Only @bob can open this strategy. Ask them to share a copy from its page.');
  assert.match(host.querySelector('.snap-meta').textContent, /backtest on unseen data over 9 days: \+\$42\.17 .*23 trades .*61\.0% win$/);
  host.innerHTML = f.postSnapshot(strat, '');
  assert.equal(host.querySelector('a.snap').getAttribute('href'), '/strategies/42'); assert.equal(host.querySelector('.snap-note'), null);
  host.innerHTML = f.postSnapshot(strat, '<img src=x>');
  assert.doesNotMatch(host.innerHTML, /<img/);
});

test('a shared P&L names each book’s trades, says all time, and never shows $0.00 for a book with no trades', () => {
  const f = frontend(), host = new Element();
  host.innerHTML = f.postSnapshot({kind: 'pnl', paper_pnl: 120.5, live_pnl: 0, paper_trades: 12, live_trades: 0});
  const rows = host.querySelectorAll('.snap-row').map((r) => r.textContent.replace(/\s+/g, ' ').trim());
  assert.deepEqual(rows, ['Paper+$120.50 on 12 trades', 'Live (real money)no trades yet']);
  assert.match(host.querySelector('.snap-meta').textContent, /all time/);
  host.innerHTML = f.postSnapshot({kind: 'pnl', paper_pnl: 3, live_pnl: -1});  // a post from before counts were kept
  assert.deepEqual(host.querySelectorAll('.snap-row b').map((b) => b.textContent), ['+$3.00', '−$1.00']);
});

test('Community replies that fail to load say so with Try again, never an empty thread', async () => {
  let failing = true;
  const post = {id: 11, body: 'Hi', author: 'Bob', username: 'bob', created_at: '2026-10-17T10:00:00Z', mine: false, comments: 2, reactions: []};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/strategies') return response({strategies: []});
    if (path === '/api/community') return response({posts: [post]});
    if (path === '/api/community/11/comments') return failing ? response({error: 'Server error.'}, 500) : response({comments: [{body: 'First', author: 'Ana', created_at: '2026-10-17T10:00:00Z'}]});
    return response({});
  }});
  await f.viewCommunity(); await flush();
  const feed = f.root.querySelector('#feed'), click = (target) => feed.listeners.get('click')({target});
  const thread = feed.querySelector('[data-act="comments"]');
  thread.click = () => click(thread);
  await click(thread); await flush();
  const box = feed.querySelector('.comments');
  assert.equal(box.hidden, false); assert.match(box.querySelector('.notice').textContent, /Replies didn’t load/);
  assert.equal(box.querySelector('.cmt-list'), null);
  failing = false;
  await click(box.querySelector('[data-replies-retry]')); await flush();
  assert.match(box.querySelector('.cmt-list').textContent, /First/);
});

test('Explore figures say what the list holds, show Matching only for a search, and flag prices that are behind', async () => {
  let at = new Date().toISOString();
  const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore?')
    ? response({at, total: 41233, shown: 3000, matched: path.includes('q=btc') ? 12 : 3000, per: 40, page: 0, markets: []}) : response({}))});
  await f.viewExplore(); await flush();
  const figs = () => f.root.querySelector('#xfigs').innerHTML;
  assert.match(figs(), /Markets tracked.*41,233/); assert.match(figs(), /In this list.*3,000.*the most traded/);
  assert.doesNotMatch(figs(), /Live now|Matching|Behind/); assert.match(figs(), /Prices updated.*just now/);
  // A search adds how many matched; a list ten minutes old says it is behind.
  at = new Date(Date.now() - 600000).toISOString();
  f.root.querySelector('#xq').listeners.get('input')({target: {value: 'btc'}});
  f.elapse(300); await flush(); await flush();
  assert.match(figs(), /Matching.*12/); assert.match(figs(), /fig-behind/); assert.match(figs(), /Behind: prices normally refresh each minute/);
});

test('Explore with no search and no markets says the list has not arrived, and a failed read offers Try again', async () => {
  let reply = () => response({total: 0, shown: 0, matched: 0, per: 40, page: 0, markets: []});
  const f = frontend({fetchImpl: (path) => (path.startsWith('/api/explore?') ? reply() : response({}))});
  await f.viewExplore(); await flush();
  const body = f.root.querySelector('#xbody');
  assert.equal(body.querySelector('.empty h3').textContent, 'No markets to show yet'); assert.doesNotMatch(body.innerHTML, /No markets match/);
  reply = () => response({error: 'Server error.'}, 500);
  await body.querySelector('[data-xretry]').onclick(); await flush();
  assert.equal(body.querySelector('.empty h3').textContent, 'Markets didn’t load');
  assert.ok(body.querySelector('[data-xretry]'));
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
  assert.match(paper, /Autopilot runs the strategies that pass every research test on paper, with pretend money/);
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
  assert.match(hypothesis.querySelector('[data-review]').innerHTML, /sound mechanism/);
  assert.match(hypothesis.querySelector('[data-stamp]').innerHTML, /\/strategies\/42/);
  stream.state('paused'); assert.match(section.querySelector('.runpulse').innerHTML, /resume/);
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
  assert.ok(f.root.querySelector('#resume')); assert.match(f.root.querySelector('#runpulse').innerHTML, /resume/);
});

test('Tau: research counts a paused session as paused, not as researching', async () => {
  const at = (counts) => frontend({fetchImpl: path => {
    if (path === '/api/models') return response({models: [], default: ''});
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/runs') return response({runs: [], counts, policy: null, totals: {tried: 8, passed: 0}});
    if (path.startsWith('/api/research/scoreboard')) return response({});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  // One running and one paused said "Researching now 2" (the server folded paused into running).
  let f = at({research_running: 1, research_paused: 1, research_queued: 0});
  f.S.me.user.autopilot = false;
  await f.viewResearch(); await flush(); await flush();
  const said = f.root.querySelector('#rstatus .said').innerHTML, figs = f.root.querySelector('#rfigs').innerHTML;
  assert.match(said, /<em>1<\/em> agent researching now · <em>1<\/em> paused — /);
  assert.match(figs, /Researching now<\/dt><dd><span class="fig ">1<\/span><\/dd><dd class="sub-fig">1 paused<\/dd>/);
  f.clearTimers();
  // Only a paused one: nothing is researching, and the line still says one is paused.
  f = at({research_running: 0, research_paused: 1, research_queued: 0});
  f.S.me.user.autopilot = false;
  await f.viewResearch(); await flush(); await flush();
  assert.match(f.root.querySelector('#rstatus .said').innerHTML, /^<em>1<\/em> paused — /);
  assert.doesNotMatch(f.root.querySelector('#rstatus .said').innerHTML, /researching now/);
  f.clearTimers();
});

test('Tau: a run names its model and says it runs until stopped, or how many strategies it tests', async () => {
  const page = async (extra) => {
    const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', ...extra};
    const f = frontend({fetchImpl: () => response({run, events: []})});
    await f.viewRun(9);
    const deck = f.root.querySelector('#runboard').innerHTML;
    f.clearTimers();
    return deck;
  };
  // The default model's key is null: the server sends its customer name, never the internal id.
  assert.match(await page({model: null, model_label: 'Claude Opus 4.6', run_forever: 1, max_hypotheses: 10}), /Claude Opus 4\.6 · Runs until you stop it/);
  assert.match(await page({model: 'sonnet-4-6', model_label: 'Claude Sonnet 4.6', run_forever: 0, max_hypotheses: 25}), /Claude Sonnet 4\.6 · Up to 25 strategies/);
  assert.match(await page({model_label: 'Claude Sonnet 4.6', run_forever: 0, max_hypotheses: 1}), /Up to 1 strategy</);
  assert.match(await page({status: 'stopped', model_label: 'Claude Opus 4.6', run_forever: true}), /Claude Opus 4\.6 · Ran until stopped/);
  const deck = await page({model: 'sonnet-4-6', model_label: '<b>x</b>', run_forever: 1});
  assert.doesNotMatch(deck, /sonnet-4-6|<b>x/);
  // The seeded example says it is an example, not a model.
  assert.doesNotMatch(await page({status: 'succeeded', direction: 'random_walk', example: true, model_label: 'Claude Opus 4.6', run_forever: 0, max_hypotheses: 2}), /Claude Opus|Up to/);
});

test('Tau: Pause and Cancel sit beside the run title, above the spend figure, not at the Agent log', async () => {
  const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', spent_usd: 1.2};
  const f = frontend({fetchImpl: () => response({run, events: []})});
  await f.viewRun(9);
  const html = f.root.innerHTML;
  assert.match(html, /<div class="run-header"><div id="runboard">[\s\S]*<\/div><span id="runact"><\/span><\/div><div id="flash"><\/div><dl class="figures measure run-figs" id="runfigs"/);
  assert.match(html, /<h2>Agent log<\/h2><\/div>/);
  assert.ok(f.root.querySelector('#pause') && f.root.querySelector('#cancel'));
  f.clearTimers();
});

test('Tau: a Pause that keeps failing replaces its error notice instead of stacking one per press', async () => {
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
  // The sentence is said once, in the loop panel; the log's foot says the state in the badge's words.
  assert.match(f.root.querySelector('#runpulse').innerHTML, /<span>Waiting 6 min<\/span>/);
  assert.ok(!f.root.querySelector('#runpulse').innerHTML.includes(line));
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
  // Said once, in the loop panel (as on Meridian), where it takes the place of the last phase.
  assert.equal(f.root.querySelector('#rsiobs [data-wait]').textContent, 'No word from the agent for 7 min. A session this quiet is normally interrupted and resumed from its last checkpoint.');
  assert.equal(f.root.querySelector('#rsiobs [data-phase]').hidden, true);
  assert.match(f.root.querySelector('#runpulse').innerHTML, /<span>Silent 7 min<\/span>/);
  assert.doesNotMatch(f.root.querySelector('#runpulse').innerHTML, /No word from the agent/);
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
  assert.equal(cost().textContent, 'A session like this usually takes about $1.80 from your credits (your recent sessions).');
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
  // With payments on, a model with no estimate still says how it is billed and that it can be stopped,
  // and a model with one goes back to its figure.
  f = research({yours: null, sessions: 1, typical: {opus: 2.25}});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 12, min_run_balance: 1};
  await f.viewResearch(); await flush(); await flush();
  const picker = f.root.querySelector('#rmodel'); picker.value = 'haiku'; picker.dispatchEvent({type: 'change'});
  assert.equal(cost().hidden, false);
  assert.equal(cost().textContent, 'No cost estimate for this model yet. It’s charged to your credits as it runs, and you can stop it any time from its session page.');
  picker.value = 'opus'; picker.dispatchEvent({type: 'change'});
  assert.match(cost().textContent, /^Each round of ideas usually costs about \$2\.25/);
  assert.doesNotMatch(cost().textContent, /No cost estimate|list price/i);
});

test('the research list says Paused for a paused session, not a red Failed', () => {
  const f = frontend();
  const row = f.runRow({id: 4, status: 'paused', prompt: 'Fade the favourite', market: 'btc15m', created_at: '2026-10-17T10:00:00Z',
    hypotheses_tried: 3, strategies_passed: 0, spent_usd: 1.2});
  assert.match(row, /<span class="run-state">Paused<\/span>/);
  assert.doesNotMatch(row, /Failed|class="loss"/);
  assert.match(row, /Spent so far: \$1\.20/);
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

test('the floating autopilot pill steps aside from any control or value under it, only where it shows through, and never while focused', () => {
  const f = frontend(), body = f.root.parent;
  f.root.innerHTML = '<main id="main"><form><input class="input" name="amt"><textarea class="input"></textarea></form><details><summary>More</summary></details><dl><div><dt>Balance</dt><dd>$1,000.00</dd></div></dl><p>Plain text</p></main>';
  const box = new Element('div', {id: 'autopilot-float', class: 'apf'}); body.appendChild(box);
  box.innerHTML = '<button type="button" class="apf-pill" data-ap="toggle">Autopilot off</button>';
  const rect = (l, t, r, b) => () => ({left: l, top: t, right: r, bottom: b, width: r - l, height: b - t});
  const pill = box.querySelector('.apf-pill'), main = f.root.querySelector('main');
  pill.getBoundingClientRect = rect(245, 794, 380, 834);   // 390x844 phone
  const els = ['input', 'textarea', 'summary', 'dd'].map((s) => f.root.querySelector(s));
  els.forEach((el) => { el.getBoundingClientRect = rect(0, 0, 0, 0); });
  let shows = main;  // what elementsFromPoint finds under the pill (the pill itself on top)
  f.document.elementsFromPoint = () => [pill, box, shows];
  for (const el of els) {  // Funds' fields, a disclosure, a dl's figure: each one sends the pill aside
    el.getBoundingClientRect = rect(30, 790, 360, 830); shows = el;
    f.apYield(); assert.equal(box.classes.has('yield'), true, el.tag);
    el.getBoundingClientRect = rect(30, 300, 360, 340);
    f.apYield(); assert.equal(box.classes.has('yield'), false, el.tag);
  }
  // A value its panel clips out of view (laid out under the pill, but the panel is what shows) doesn't count.
  els[3].getBoundingClientRect = rect(288, 802, 317, 820); shows = main;
  f.apYield(); assert.equal(box.classes.has('yield'), false);
  shows = els[3];
  f.apYield(); assert.equal(box.classes.has('yield'), true);
  // Tabbing onto the stepped-aside pill brings it back, so a keyboard user can always open it.
  f.document.activeElement = pill;
  f.apYield(); assert.equal(box.classes.has('yield'), false);
  // Plain text under the pill isn't a control or a figure; and the page's foot always clears it.
  f.document.activeElement = null; els[3].getBoundingClientRect = rect(0, 0, 0, 0);
  f.apYield(); assert.equal(box.classes.has('yield'), false);
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  assert.match(css, /body:not\(\.landing-body\) \{ padding-bottom: 72px; \}/);
  assert.match(css, /@media \(max-width: 600px\) \{ \.apf \{ right: 10px; bottom: 10px; \}/);  // 10 + 40 + 8 < 72
});

test('the autopilot says the market it researches by its label, never a raw key or series', () => {
  const f = frontend();
  f.S.me.markets = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin daily close, 5pm EDT'}, {key: 'kxhighchi', series: 'KXHIGHCHI', label: 'Chicago high temp'}];
  const ap = {autopilot: true, mode: 'paper', research: {active: []}, paper_running: 0};
  f.S.ap = {...ap, research: {active: ['btc15m', 'KXBTCD', 'kxhighchi']}};
  assert.equal(f.apIdleLine(), 'Researching BTC 15-min · BTC 5pm · Chicago high temp');
  f.S.ap = {...ap, research: {active: ['Bitcoin 15-minute', 'kxgone', "a market it's still picking"]}};
  assert.equal(f.apIdleLine(), 'Researching Bitcoin 15-minute · an unlisted market');
  // The story quotes the same list; the panel, the card and the pill's tooltip say it the same way.
  const d = {...ap, research: {active: ['btc15m', 'KXBTCD'], tested_7d: 3, passed_7d: 0}, story: ["Right now it's researching btc15m and KXBTCD."]};
  const box = new Element('div'); box.innerHTML = '<div id="apf-story"></div><dl id="apf-stats"></dl>';
  f.apUpdate(box, d);
  assert.match(box.querySelector('#apf-story').innerHTML, /<p>Right now it\S{1,6}s researching BTC 15-min and BTC 5pm\.<\/p>/);
  assert.doesNotMatch(box.querySelector('#apf-story').innerHTML, /btc15m|KXBTCD/);
  f.apUpdate(box, {...d, story: []});
  assert.match(box.querySelector('#apf-stats').innerHTML, /Researching BTC 15-min · BTC 5pm/);
  assert.doesNotMatch(source, /esc\(\(d\.story && d\.story\[0\]\)|\(d\.story \|\| \[\]\)\.map|\[\.\.\.new Set\(d\.research\.active\)\]/);
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
  assert.match(await at({status: 'succeeded'}, [{id: 43, title: 'Fade', status: 'rejected'}]), /Nothing passed this time\. Most ideas don’t\. Each idea below says which check it missed; tap one for what to try next\. <a href="\/research\?new=1">Try another idea<\/a>/);
  assert.equal(await at({status: 'running'}, []), '');  // still going: nothing to do yet
  // A failed session says why (escaped) and how to start again; a cancelled one says so too.
  assert.match(await at({status: 'failed', error: 'The model <i>timed out</i>.'}, []),
    /This session stopped on an error\. The model &lt;i&gt;timed out&lt;\/i&gt;\. <a href="\/research\?new=1">Start a new session<\/a>/);
  assert.match(await at({status: 'cancelled'}, [{id: 43, title: 'Fade', status: 'rejected'}]),
    /This session was cancelled before it finished\. The ideas it tested are listed below\. <a href="\/research\?new=1">Try another idea<\/a>/);
});

const OUT_OF_CREDITS_STEP = {id: 7, kind: 'step', message: 'Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching.', created_at: '2026-10-25T11:00:00Z'};
const RUN_AT = async (run, events = [], strategies = []) => {
  const f = frontend({fetchImpl: () => response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: '2026-10-25T10:00:00Z', ...run}, events, strategies})});
  await f.viewRun(9); f.clearTimers();
  return f;
};

test('Tau: a session that ran out of credits says so and offers Add credits, not "Done" and another idea', async () => {
  let f = await RUN_AT({status: 'succeeded', run_forever: 1, hypotheses_tried: 4, strategies_passed: 0, spent_usd: 19.95}, [OUT_OF_CREDITS_STEP], [{id: 43, title: 'Fade', status: 'failed'}]);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Out of credits/);
  assert.doesNotMatch(f.root.querySelector('#runfigs').innerHTML, />Done</);
  const next = f.root.querySelector('#runnext').innerHTML;
  assert.match(next, /It stopped when your credits ran out\. <a href="\/billing">Add credits<\/a>, then start a new session to keep researching\. Nothing passed before then/);
  assert.doesNotMatch(next, /Try another idea/);
  assert.equal(f.root.querySelector('#runend').innerHTML, '<div class="run-end"><a class="btn" href="/billing">Add credits</a></div>');
  // Something passed before the credits ran out: both, the credits first.
  f = await RUN_AT({status: 'succeeded', run_forever: 1}, [OUT_OF_CREDITS_STEP], [{id: 42, title: 'Late', status: 'passed'}]);
  assert.match(f.root.querySelector('#runnext').innerHTML, /credits ran out\. <a href="\/billing">Add credits<\/a>.*Passed: <a href="\/strategies\/42">Late<\/a>\. Open it to deploy it on paper\./);
  // Without the step it is an ordinary finish.
  f = await RUN_AT({status: 'succeeded'}, [], [{id: 43, title: 'Fade', status: 'failed'}]);
  assert.match(f.root.querySelector('#runfigs').innerHTML, /Finished/);
  assert.doesNotMatch(f.root.querySelector('#runnext').innerHTML, /billing/);
});

test('Tau: a running session counts its ideas and passes live, and a set-size one says how many it will test', async () => {
  const hyp = (id) => ({id, kind: 'hypothesis', message: 'Idea ' + id, data: {}, created_at: '2026-10-25T10:00:00Z'});
  // The run's counters lag a round behind its log; "Passed …" sat beside a passed idea.
  let f = await RUN_AT({status: 'running', run_forever: 1, hypotheses_tried: 3, strategies_passed: 0}, [1, 2, 3, 4, 5].map(hyp), [{id: 42, title: 'Late', status: 'passed'}, {id: 43, title: 'Fade', status: 'failed'}]);
  let figs = f.root.querySelector('#runfigs').innerHTML;
  assert.match(figs, /Tested<\/dt><dd><span class="fig ">5</); assert.match(figs, /Passed<\/dt><dd><span class="fig ">1</);
  assert.doesNotMatch(figs, /…|of up to/);
  f = await RUN_AT({status: 'running', max_hypotheses: 10, hypotheses_tried: 2}, [hyp(1)], []);
  figs = f.root.querySelector('#runfigs').innerHTML;
  assert.match(figs, /Tested<\/dt><dd><span class="fig ">2<.*of up to 10/s); assert.match(figs, /Passed<\/dt><dd><span class="fig ">0</);
  // A long session's time reads in hours, not "299 min".
  f = await RUN_AT({status: 'succeeded', hypotheses_tried: 4, strategies_passed: 0, started_at: '2026-10-25T10:00:00Z', finished_at: '2026-10-25T14:59:00Z'});
  assert.match(f.root.querySelector('#runfigs').innerHTML, />5 hr</);
});

test('Tau: a running session quiet for hours reads its age in minutes and hours, not raw seconds', async () => {
  const ago = (s) => new Date(Date.now() - s * 1000).toISOString();
  for (const [secs, said] of [[3 * 3600 + 40, 'Last step 3 hr ago ·\u00a0still working'], [5 * 60 + 2, 'Last step 5 min ago ·\u00a0still working'], [20, 'active 20s ago']]) {
    const f = await RUN_AT({status: 'running', started_at: ago(secs + 60)}, [{id: 1, kind: 'step', message: 'Loading data…', created_at: ago(secs)}]);
    const said0 = f.root.querySelector('#rsiobs [data-livetext]').textContent;
    assert.equal(said0, said);
    assert.doesNotMatch(said0, /\d{3,}s|likely a long model call/);
  }
});

test('Tau: a stopped session leaves no idea spinning on "Testing", and a provider failure is said once', async () => {
  const error = 'The research models are at capacity right now, so the session stopped. Start it again in a little while.';
  const f = await RUN_AT({status: 'failed', error}, [{id: 1, kind: 'hypothesis', message: 'Vol', data: {}, created_at: '2026-10-25T10:00:00Z'}]);
  const stamp = f.root.querySelector('#log').querySelector('[data-stamp]');
  assert.equal(stamp.textContent, 'Not finished'); assert.equal(stamp.classList.contains('pending'), false);
  assert.match(f.root.querySelector('#runnext').innerHTML, /^<p class="run-next">The research models are at capacity right now, so the session stopped\. Start it again in a little while\. <a href="\/research\?new=1">Start a new session<\/a><\/p>$/);
  // Still running: the idea is still being tested.
  const live = await RUN_AT({status: 'running'}, [{id: 1, kind: 'hypothesis', message: 'Vol', data: {}, created_at: '2026-10-25T10:00:00Z'}]);
  assert.equal(live.root.querySelector('#log').querySelector('[data-stamp]').classList.contains('pending'), true);
});

test('Tau: a past thought is still: no pulse once sealed, and no "0s" clock on one replayed from the log', () => {
  const f = frontend(), section = new Element();
  section.innerHTML = '<ol class="log"></ol><button class="jumplatest"></button><div class="runpulse"></div>';
  const stream = f.runFeed(section), log = section.querySelector('.log');
  stream.push([{id: 1, kind: 'thinking', message: 'Looking at the book.', data: {block: 1}, created_at: '2026-10-25T10:00:00Z'},
    {id: 2, kind: 'thinking', message: '', data: {block: 1, end: true}, created_at: '2026-10-25T10:00:00Z'}]);
  assert.equal(log.children[0].classes.has('sealed'), true);
  assert.equal(log.children[0].querySelector('[data-el]').hidden, true);
  f.clearTimers();
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  assert.match(css, /\.log\.stream \.think\.sealed \.node::after \{ animation: none; \}/);
});

test('Tau: a finished session ends under its last log line with the way on: your own idea after the example, another idea or autopilot after nothing passed', async () => {
  const at = async (run, strategies, autopilot = false) => {
    const f = frontend({fetchImpl: () => response({run: {id: 9, prompt: 'Idea', market: 'btc15m', created_at: '2026-10-25T10:00:00Z', ...run}, events: [], strategies})});
    f.S.me.user.autopilot = autopilot;
    await f.viewRun(9); f.clearTimers();
    return f;
  };
  let f = await at({status: 'succeeded', example: true}, []);
  // Under the log, inside the Agent log section: a plain button, so the line above keeps the one primary.
  const main = f.root.querySelector('main').innerHTML;
  assert.ok(main.indexOf('id="runfeed"') < main.indexOf('id="runend"'));
  assert.equal(f.root.querySelector('#runend').innerHTML, '<p class="run-end"><a class="btn" href="/research?new=1">Describe your own idea</a></p>');
  // Nothing passed: another idea, or let autopilot pick them (the same one-click switch as elsewhere).
  f = await at({status: 'succeeded'}, [{id: 43, title: 'Fade', status: 'failed'}]);
  const end = f.root.querySelector('#runend').innerHTML;
  assert.match(end, /<a class="btn" href="\/research\?new=1">Try another idea<\/a><p class="research-ap">Rather not write ideas yourself\? <button type="button" data-research-ap>Turn on autopilot<\/button>/);
  assert.doesNotMatch(end, /btn primary/);
  assert.doesNotMatch((await at({status: 'stopped'}, [], true)).root.querySelector('#runend').innerHTML, /Turn on autopilot/);  // already on
  assert.match((await at({status: 'stopped'}, [], true)).root.querySelector('#runend').innerHTML, /Try another idea/);
  // Something passed (the line above links it), or still going: nothing at the foot.
  assert.equal((await at({status: 'succeeded'}, [{id: 42, title: 'Late', status: 'passed'}])).root.querySelector('#runend').innerHTML, '');
  assert.equal((await at({status: 'running'}, [])).root.querySelector('#runend').innerHTML, '');
});

test('Tau: the run page folds its RSI explainer into one "How research works" line on every screen, and keeps the reader\'s choice across repaints', async () => {
  const run = {id: 9, prompt: 'Idea', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z'};
  const rsi = {evolved: false, last_dream: null, min_history: 12};
  for (const phone of [true, false]) {
    const f = frontend({matchMedia: () => ({matches: phone}), fetchImpl: path => { assert.ok(path.startsWith('/api/runs/9')); return response({run, events: [], rsi}); }});
    await f.viewRun(9);
    const box = f.root.querySelector('#rsibox'), disc = () => box.querySelector('details.rsidisc');
    assert.equal('open' in disc().attributes, false, String(phone));
    assert.match(disc().querySelector('summary').innerHTML, /How research works<\/span><span class="rsi-tag quiet">Self-tuning/);
    assert.match(box.innerHTML, /The agent is <b>self-tuning<\/b>/);
    // The reader opens it; the next poll's repaint keeps their choice.
    disc().open = true;
    await [...f.intervals.values()].at(-1)(); await flush();
    assert.equal('open' in disc().attributes, true, String(phone));
    f.clearTimers();
  }
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

test('strategy page: unseen figures say their span, deployments go by book not row id, and a second paper copy is flagged', async () => {
  const detail = detailStrategy({out_of_sample: {...metrics(12), days: 15.2}, capital: 100,
    recent_trades: [{opened: '2026-10-24T10:15Z', ticker: 'KXBTC15M-26OCT25-T67000', side: 'yes', qty: 5, entry: .42, exit: 1, pnl: 2.8, reason: 'settled'}],
    deployments: [{id: 812, mode: 'demo', status: 'running'}, {id: 811, mode: 'paper', status: 'paused'}]});
  const f = strategyFrontend(detail, () => response({deployments: [], open_positions: []}));
  await f.viewStrategy(42); await flush();
  const figs = f.root.querySelector('#figs').innerHTML, html = f.root.querySelector('main').innerHTML;
  assert.match(figs, /6 trades over 15 days the agent never saw/);
  assert.match(figs, /Unseen data over 15 days · \$100 at risk at most/);
  assert.match(html, /Already deployed: Demo \(running\), Paper \(paused\)\./);
  assert.match(html, /Stop deployments \(demo, paper\)/);
  assert.doesNotMatch(html, /#81[12]/);
  assert.match(html, /class="hint paper-again">It already runs on paper\. Deploying it again starts a second copy/);
  // The unseen trades scroll inside the paper's column and wrap, never running under the sidebar.
  assert.match(html, /<div class="sheet"><table class="table stack t-unseen">/);
  // An older result with no window length keeps its figure as it was; not on paper, no warning.
  const g = strategyFrontend(detailStrategy({capital: 100}), () => response({deployments: [], open_positions: []}));
  await g.viewStrategy(42); await flush();
  assert.match(g.root.querySelector('#figs').innerHTML, /6 trades the agent never saw/);
  assert.match(g.root.querySelector('#figs').innerHTML, /<dd class="sub-fig">\$100 at risk at most<\/dd>/);
  assert.doesNotMatch(g.root.querySelector('main').innerHTML, /paper-again/);
});

test('a strategy row renders its thesis markdown as the strategy page does, escaped', () => {
  const f = frontend({fetchImpl: () => response({})});
  const row = f.strategySlip(detailStrategy({id: 46}), null, {});
  assert.match(row, /<div class="sub-fig cellwrap"><b>Saved<\/b> &lt;img/);
  assert.doesNotMatch(row, /\*\*Saved\*\*|<img/);
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
  assert.match(text, /It put 1 on paper, paused 2, made 1 other change\./);
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

test('the strip splits a book\'s figure by the strategy that traded it, inside that book only', async () => {
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
      if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), deployments, ...extra});
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
  // An older server without the split: the book's line alone.
  assert.doesNotMatch(await strip({since: {...since, by_deployment: undefined}}), /since-split/);
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
    // Up top, in the strip, where a phone sees it without scrolling: the page's one way to the example.
    assert.equal(/No sessions of your own yet\. <a href="\/example" data-example>See an example session first<\/a>/.test(f.root.querySelector('#dash-since').innerHTML), shown);
    // The empty Deployed box no longer repeats it as a second primary button beside the autopilot card's.
    assert.doesNotMatch(f.root.querySelector('#deps-empty').innerHTML, shown ? /class="btn/ : /href="\/example"/, String(own));
    const page = ['#boardbody', 'main', '#dash-ap'].map((sel) => f.root.querySelector(sel).innerHTML).join('');
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
  assert.equal((f.root.querySelector('main').innerHTML.match(/class="btn primary/g) || []).length, 1);
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
  // No balance from Kalshi (down, or the key deleted there) is "saved", never a green check, and says what to do.
  const g = keyFunds({reads: 0, live: {connected: true, balance: null, key_id: 'a952…608c'}, dev: {connected: true, key_id: 'a952…608c', balance: null}});
  await g.viewFunds();
  const gm = g.root.querySelector('main').innerHTML;
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
  const main = f.root.querySelector('main').innerHTML;
  assert.match(main, /Your Kalshi demo account has \$0\.00, so Kalshi refuses demo orders\. Add demo funds in your account on <a href="https:\/\/demo\.kalshi\.co\/" target="_blank" rel="noopener">demo\.kalshi\.co<\/a>/);
  assert.match(main, /To use a different key, disconnect this one and connect the new one\./);
  assert.match(main, /To use a different demo key, remove this one and connect the new one\./);
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
  const fresh = f.root.querySelector('main').innerHTML;
  assert.equal((fresh.match(/name="key_id" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"/g) || []).length, 2);
  assert.equal((fresh.match(/name="private_key" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false"/g) || []).length, 2);
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
const billingPage = (data, posts = [], routes = {}) => frontend({stripe: STRIPE_STUB, fetchImpl: (path, options = {}) => {
  if (routes[path]) return routes[path](options);
  if (/^\/api\/billing(\?|$)/.test(path)) return response(data);
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
  assert.match(main, /<p class="hint ledger-key">Newest first\. The receipt has every line, with exact amounts\.<\/p>/);
  const rows = f.root.querySelectorAll('.t-ledger tbody tr').map((r) => r.innerHTML);
  assert.equal(rows.length, 5);
  assert.match(rows[0], /Agent usage<div class="sub-fig">claude-opus-4-6<\/div>[\s\S]*−\$0\.21/);
  assert.doesNotMatch(rows[0], /Agent usage · /);  // the memo's prefix isn't said twice
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
  const main = f.root.querySelector('main').innerHTML;
  // The balance 30 days ago, plus credits bought, minus agent usage, is the balance now: the server's cents.
  assert.match(main, /<dl class="bill-math">[\s\S]*Balance 30 days ago<\/dt><dd>\$12\.50<\/dd>[\s\S]*Credits bought \(2 card charges\)<\/dt><dd>\+\$35\.00<\/dd>[\s\S]*Agent usage<\/dt><dd>−\$40\.08<\/dd>[\s\S]*class="total"><dt>Balance now<\/dt><dd>\$7\.42<\/dd>/);
  assert.doesNotMatch(main, /Welcome and other credits/);  // nothing else came in this month
  assert.match(main, /<p class="hint ledger-key">Last 30 days, newest first\./);
  const rows = f.root.querySelectorAll('.t-ledger tbody tr').map((r) => r.innerHTML);
  assert.equal(rows.length, 6);  // two day headings and four lines
  assert.match(rows[0], /<td colspan="3" data-lab="Day"><b>[A-Z][a-z]{2}, Jan 15<\/b><span class="day-sum">\$12\.95 used ·\u00a0\+\$25\.00 credits<\/span><\/td>/);
  assert.match(rows[1], /<time datetime="2026-01-15T08:50:00Z">\d\d:\d\d–\d\d:\d\d/);  // the span of the session's calls
  assert.match(rows[1], /Research session<div class="sub-fig"><a href="\/research\/108">&lt;b&gt;Fade&lt;\/b&gt; the open<\/a> ·\u00a0Claude Opus 4\.6 ·\u00a057 model calls<\/div>[\s\S]*−\$12\.95/);
  assert.match(rows[2], /Auto-reload<div class="sub-fig">Card charged \$26\.38: \$25\.00 credits plus the 5\.5% purchase fee ·\u00a0Stripe ref <span class="ref">pi_3Synthetic&lt;x&gt;<\/span><\/div>[\s\S]*\+\$25\.00/);
  assert.match(rows[3], /<b>[A-Z][a-z]{2}, Jan 14<\/b><span class="day-sum">\$0\.01 used ·\u00a0\+\$10\.00 credits<\/span>/);
  assert.match(rows[4], /Autopilot check-in<div class="sub-fig">Claude Haiku 4\.5 ·\u00a03 model calls<\/div>/);
  assert.doesNotMatch(rows[4], /href=/);  // a check-in has no session page
  assert.match(rows[5], /Added credits<div class="sub-fig">Card charged \$10\.55: \$10\.00 credits plus the 5\.5% purchase fee ·\u00a0Stripe ref <span class="ref">pi_3SyntheticTopup<\/span>/);
  assert.match(main, /Older days are in the receipt\./);  // the line cap left days out, and says where they are
  assert.doesNotMatch(main, /list price|markup|us\.anthropic/i);
});

test('a failed auto-reload says why by the auto-reload switch, with Update card going to the card form', async () => {
  const failed = {at: '2026-10-26T13:05:00Z', text: 'It couldn\'t add $25.00 in credits. Your card was declined for <insufficient> funds.'};
  const posts = [], f = billingPage(cardedBilling({reload_failed: failed}), posts);
  await f.viewBilling(); await flush();
  const note = f.root.querySelector('#autorel-fail');
  assert.ok(note, 'the banner is on the page');
  assert.ok(f.root.querySelector('section.panel #autorel-fail'), 'it sits in the payment-method panel, by the switch');
  assert.match(note.innerHTML, /<b>Auto-reload failed<\/b> <time datetime="2026-10-26T13:05:00Z">/);
  assert.match(note.innerHTML, /It couldn&#39;t add \$25\.00 in credits\. Your card was declined for &lt;insufficient&gt; funds\./);
  assert.equal('hidden' in note.attributes, false);
  const fix = f.root.querySelector('#autorel-fix');
  assert.equal(fix.textContent, 'Update card');
  const sent = f.requests.length;
  fix.onclick();  // goes to the card form: no request, no charge
  assert.equal(f.requests.length, sent);
  // Switched off, the banner goes with it (it is about auto-reload); back on, it is back.
  const sw = f.root.querySelector('#autoreload'); sw.checked = false; await sw.onchange(); await flush();
  assert.equal(note.hidden, true);
  sw.checked = true; await sw.onchange(); await flush();
  assert.equal(note.hidden, false);
  assert.deepEqual(posts.map((p) => p.on), [false, true]);
  // Nothing failed: no banner. Off at load: there, but hidden.
  const ok = billingPage(cardedBilling({reload_failed: null}));
  await ok.viewBilling(); await flush();
  assert.equal(ok.root.querySelector('#autorel-fail'), null);
  const off = billingPage(cardedBilling({auto_reload: false, reload_failed: failed}));
  await off.viewBilling(); await flush();
  assert.equal('hidden' in off.root.querySelector('#autorel-fail').attributes, true);
});

test('the failed auto-reload banner is one helper, byte-identical in both bundles, styled in both stylesheets', () => {
  const meridian = readFileSync(new URL('../app/static/app.meridian.js', import.meta.url), 'utf8');
  const helper = (src) => (src.match(/ {2}function reloadFailNote\(d\) \{[\s\S]*?\n {2}\}\n/) || [])[0];
  assert.ok(helper(source));
  assert.equal(helper(meridian), helper(source));
  for (const sheet of ['app.css', 'app.meridian.css']) {
    const css = readFileSync(new URL('../app/static/' + sheet, import.meta.url), 'utf8');
    assert.match(css, /\.autorel-fail\[hidden\] \{ display: none; \}/);
    assert.match(css, /\.autorel-fail \.btn \{/);
  }
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
  assert.match(key, /<span class="since-book" data-book="demo"><b>Demo<\/b>: no trades closed yet<\/span>/);
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

test('Tau: a run says per missed gate what was measured, what was needed and what to try next', async () => {
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
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run, events, strategies: []}) : response({})});
  await f.viewRun(9); await flush();
  const items = f.root.querySelector('#log').children.filter((li) => li.tag === 'li');
  const reviews = items.map((li) => (li.querySelector('[data-review]') || {innerHTML: ''}).innerHTML).filter(Boolean);  // the two hypothesis cards
  assert.deepEqual(missedRows(reviews[0]), MISSED_ROWS);
  assert.doesNotMatch(reviews[0], /classification=|gatekeeper-held|<b>sharpe/);  // the plain lines replace the raw note
  // A pass lists nothing it missed; its one-time holdout lands on the same card after the verdict,
  // with the lines it missed there, not on a loose row stamped VOID.
  const [passPart, holdout] = reviews[1].split('Locked holdout');
  assert.deepEqual(missedRows(passPart), []);
  assert.match(passPart, /cleared every gate/);
  assert.deepEqual(missedRows(holdout), [MISSED_ROWS[0]]);
  assert.match(holdout, /missed/);
  assert.doesNotMatch(reviews[1], /classification=/);
  assert.equal(items.filter((li) => !li.removed).length, 2);
  f.clearTimers();
  // Nothing passed: the next-step line says where the reasons are.
  const none = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run: {...run, strategies_passed: 0}, events: [], strategies: [{id: 41, title: 'Fade', status: 'failed'}]}) : response({})});
  await none.viewRun(9); none.clearTimers();
  assert.match(none.root.querySelector('#runnext').innerHTML, /Each idea below says which check it missed; tap one for what to try next\./);
});

test('Tau: a run says its ledger lines in plain words, with the zone of its times', async () => {
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
  assert.match(log, /Locked holdout · held<\/span><span class="hx-vtext">Held up on the locked holdout/);
  assert.match(log, /DROPPED<\/b> <b>Thin<\/b> — every variant took 0 trades/);
  assert.match(log, /<time datetime="2026-10-17T10:01:00Z" title="[^"]+">/);
  f.clearTimers();
});

// The System page's live activity feed shows a verdict as the run page's plain note (server
// gate_explain.event_note) after its title, else its own message minus the status word; escaped.
test('Tau: the System feed reads a verdict as its plain note, else its message', async () => {
  const events = [
    {kind: 'verdict', message: 'FAILED - Fade <b>: validation verdict is gatekeeper-held (classification=inconclusive, 9 trades)',
      created_at: '2026-10-20T15:59:00Z', data: {note: 'Did not pass on data it never saw (9 trades).', title: 'Fade <b>'}},
    {kind: 'verdict', message: 'Model tiering: X proposed and screened.', created_at: '2026-10-20T15:58:00Z',
      data: {note: 'A quicker model screened the ideas first: 1 set aside, 2 passed on to be developed.', title: null}},
    {kind: 'verdict', message: 'PASSED - Lean in: cleared every gate', created_at: '2026-10-20T15:57:00Z'},
    {kind: 'step', message: 'Froze 2 finalists', created_at: '2026-10-20T15:56:00Z'},
  ];
  const f = frontend({fetchImpl: path => path === '/api/admin/system' ? response({nodes: {}, events, now: '2026-10-20T16:00:00Z'}) : response({})});
  await f.viewSystem(); await flush();
  const html = f.root.querySelector('#sys-feed').innerHTML;
  assert.deepEqual([...html.matchAll(/<\/time><span>([^<]*)<\/span>/g)].map(m => m[1]), [
    'Fade &lt;b&gt;: Did not pass on data it never saw (9 trades).',
    'A quicker model screened the ideas first: 1 set aside, 2 passed on to be developed.',
    'Lean in: cleared every gate',
    'Froze 2 finalists',
  ]);
  assert.doesNotMatch(html, /gatekeeper-held|classification=|Model tiering|<b>/);
  f.clearTimers();
});

test('Tau: a run lists each idea it tested with its outcome and first missed check, passed first, each jumping to its card', async () => {
  const run = {id: 9, status: 'succeeded', prompt: 'Session 9', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', hypotheses_tried: 2, strategies_passed: 1};
  const at = '2026-10-17T10:01:00Z';
  const events = [
    {id: 1, kind: 'hypothesis', message: 'Fade <b>', created_at: at, data: {in_sample: {pnl: 4.5, trades: 8}}},
    {id: 2, kind: 'verdict', message: 'FAILED - Fade <b>: ...', created_at: at, data: {status: 'failed', title: 'Fade <b>', strategy_id: 41, why_failed: MISSED}},
    {id: 3, kind: 'hypothesis', message: 'Lean in', created_at: at, data: {in_sample: {pnl: 3, trades: 9}}},
    {id: 4, kind: 'verdict', message: 'PASSED - Lean in: ...', created_at: at, data: {status: 'passed', title: 'Lean in', strategy_id: 42, why_failed: []}},
  ];
  const strategies = [{id: 41, title: 'Fade <b>', status: 'failed'}, {id: 42, title: 'Lean in', status: 'passed'}];
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run, events, strategies}) : response({})});
  await f.viewRun(9); await flush();
  const ideas = f.root.querySelector('#runideas').innerHTML;
  assert.match(ideas, /<h2>Ideas tested<\/h2>/);
  assert.ok(ideas.indexOf('Lean in') < ideas.indexOf('Fade'), 'passed first');
  assert.match(ideas, /<span class="hx-stamp pass">Passed<\/span><button type="button" class="ri-title" data-goto="42">Lean in<\/button><span class="ri-why"><a href="\/strategies\/42">/);
  assert.match(ideas, new RegExp(`<span class="hx-stamp void">Void</span><button type="button" class="ri-title" data-goto="41">Fade &lt;b&gt;</button><span class="ri-why">Too few trades to judge \\(18 of 30\\) · 1 more check</span>`));
  assert.ok(f.root.querySelector('#log').children.some((li) => li.dataset && String(li.dataset.sid) === '41'), 'the card is the jump target');
  f.clearTimers();
});

test('Tau: the strategy page lists what it missed under Verdict and names the first in the Deploy notice', async () => {
  const f = strategyFrontend(detailStrategy({status: 'failed', why_failed: MISSED})); await f.viewStrategy(42); await flush();
  const html = f.root.querySelector('main').innerHTML;
  const at = html.indexOf('What it missed, and what to try next');
  assert.ok(at > html.indexOf('Verdict'), 'listed in the Verdict section');
  assert.deepEqual(missedRows(html.slice(at)).slice(0, 2), MISSED_ROWS);
  assert.match(html, /Void: too few trades to judge \(18 of 30\), and 1 more check missed \(see Verdict\)\. It wasn’t validated/);
  assert.doesNotMatch(html, /failed the unseen-data gate|<b>sharpe/);
  const r = strategyFrontend(detailStrategy({status: 'rejected', why_failed: [MISSED[0]]})); await r.viewStrategy(42); await flush();
  assert.match(r.root.querySelector('main').innerHTML, /Rejected: too few trades to judge \(18 of 30\) \(see Verdict\)\./);
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
  'Net return per trade': ['net_edge'], 'DSR': ['deflated_sharpe'], 'Placebo p-value': ['placebo']};
const tintedFigures = html => [...String(html).matchAll(/<div class="rp-stat"><div class="k">([^<]*)<\/div><div class="val( sig)?">/g)]
  .filter(m => m[2]).map(m => m[1].replace(/&amp;/g, '&'));
const missedFigures = lines => Object.keys(FIGURE_GATES).filter(k => lines.some(l => FIGURE_GATES[k].includes(l.gate)));
const paperSections = html => {
  const at = html.indexOf('The one-time locked holdout');
  return {validation: html.slice(html.indexOf('Validation-window evidence'), at), holdout: html.slice(at)};
};

test('Tau: a research-paper figure is red exactly when its gate line says it missed', async () => {
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
  const hs = paperSections(h.root.querySelector('main').innerHTML);
  assert.deepEqual(tintedFigures(hs.validation), []);
  assert.deepEqual(tintedFigures(hs.holdout).sort(), missedFigures(HOLD_LINES).sort());
  assert.match(hs.holdout, /<div class="k">Holdout<\/div><div class="val">Consumed<\/div>/);
  // An older server without gate_tints judges nothing, so nothing is red, whatever the numbers.
  const old = strategyFrontend(detailStrategy({status: 'failed', experiment: {...failing, holdout: held.holdout, gate_tints: undefined}}));
  await old.viewStrategy(42); await flush();
  assert.doesNotMatch(old.root.querySelector('main').innerHTML, /class="val sig"/);
});

test('Tau: a hot-markets row names its market the app’s way, never by the raw series', () => {
  const f = frontend();
  f.S.me.markets = [{key: 'btc15m', series: 'KXBTC15M', label: 'Bitcoin 15-minute'}, {key: 'eth_daily', series: 'KXETHD', label: 'Ethereum daily close, 5pm EDT'}];
  const row = (s) => f.hotRowHtml({t: s + '-26OCT261530-30', s, ti: 'Some title', su: '', bid: .48, ask: .52, v24: 1200, h: [.4, .5]});
  assert.match(row('KXBTC15M'), /<span class="hot-foot"><span class="mk quiet">BTC 15-min<\/span>/);
  assert.match(row('KXETHD'), /<span class="mk quiet">ETH 5pm<\/span>/);
  // A series no market here covers loses the chip rather than showing the ticker.
  assert.doesNotMatch(row('KXWEIRD'), /mk quiet|>KXWEIRD</);
  for (const s of ['KXBTC15M', 'KXETHD']) assert.doesNotMatch(row(s), new RegExp('>' + s + '<'));
});

test('Tau: the dashboard says where the sessions it counts are, and points finished ones at what each idea missed', async () => {
  const at = async (since) => {
    const f = frontend({fetchImpl: path => {
      if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), deployments: [], since});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    return f.root.querySelector('#dash-since').innerHTML;
  };
  const base = {at: '2026-10-25T08:00:00+00:00', first: false, books: {paper: {pnl: 0, trades: 0}}, autopilot: {}};
  assert.match(await at({...base, passed: {n: 0, items: []}, runs: {succeeded: 2}}),
    /Nothing new passed <span class="since-sub">· 2 research sessions started, all finished, <a href="\/research">see what each idea missed<\/a><\/span>\./);
  // A session still queued or running hasn't judged any idea yet: the line says where it is instead.
  const queued = await at({...base, passed: {n: 0, items: []}, runs: {queued: 1}});
  assert.match(queued, /· 1 research session started, still queued, <a href="\/research">follow it on Research<\/a><\/span>\./);
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
  for (const line of lines) assert.match(line, /n=6 — under 30 trades, too few to tell skill from luck \(a caution, stricter than the gate’s floor of 10\)/);
  assert.deepEqual(await flags({sample_caution: {min_trades: 5, gate_min_oos_trades: 10}}), []);
  assert.deepEqual(await flags({}), []);  // no bar from the server, no line: never a guessed constant
});

test('first-run funnel: an empty paper track record never sends a user with nothing deployed to an empty Deploy board', () => {
  const f = frontend(), th = {min_sharpe_days: 30};
  f.S.me = {user: {autopilot: false}};
  const paper = () => f.trackRecordPanel({trades: 0, label: 'Paper'}, 'paper', th);
  // No session of their own yet: straight to a new session (it was Deploy → Strategies → Research).
  f.S.dashDeps = 0; f.S.dashNoSessions = true;
  assert.match(paper(), /<a class="btn" href="\/research\?new=1">Start a research session<\/a>/); assert.doesNotMatch(paper(), /Go to Deploy/);
  // The dashboard's autopilot card above already offers the switch: the record doesn't repeat it.
  assert.doesNotMatch(paper(), /Turn on autopilot/);
  // Sessions but nothing deployed: the strategies that passed.
  f.S.dashNoSessions = false;
  assert.match(paper(), /<a class="btn" href="\/strategies">See passed strategies<\/a>/);
  // Something deployed, or no dashboard read yet: Deploy as before. Live and demo keep their own button.
  f.S.dashDeps = 2; assert.match(paper(), /Go to Deploy/); assert.match(paper(), /Turn on autopilot/);
  f.S.dashDeps = undefined; assert.match(paper(), /Go to Deploy/);
  f.S.dashDeps = 0; assert.match(f.trackRecordPanel({trades: 0, label: 'Live'}, 'live', th), /Go to Deploy/);
});

test('first-run funnel: an empty Deploy board with nothing passed starts a session instead of opening an empty list', async () => {
  for (const [passed, cta, href] of [[0, 'Start a research session', '/research?new=1'], [2, 'See passed strategies', '/strategies'], [null, 'See passed strategies', '/strategies']]) {
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
    assert.equal(seen.filter((p) => p.startsWith('/api/strategies')).length, 1);  // asked once, not every poll
  }
  // A board with deployments never asks.
  const seen = [];
  const g = frontend({fetchImpl: path => { seen.push(path); return response({deployments: [{id: 1, strategy_id: 4, title: 'A', mode: 'paper', status: 'running', realized_pnl: 0, curve: []}], open_positions: []}); }});
  await g.viewDeploy(); await flush(); await flush();
  assert.equal(seen.some((p) => p.startsWith('/api/strategies')), false);
});

test('first-run funnel: deploying from a strategy page lands on Deploy with a note that it worked and what happens next', async () => {
  const f = strategyFrontend(detailStrategy({title: 'Momentum <b>fade</b>'}), (path, options) => {
    if (options && options.method === 'POST') return response({id: 9});
    if (path === '/api/deployments') return response({deployments: [], open_positions: []});
    return response({strategies: [], counts: {passed: 1}});
  });
  await f.viewStrategy(42); await flush();
  f.root.querySelector('#dep-paper').onclick(); await flush(); await flush();
  assert.deepEqual(f.navigations, ['/deploy']);
  if (f.S.deployed) await f.viewDeploy();  // the harness may not route; the view reads the note either way
  await flush(); await flush();
  const note = f.root.querySelector('#flash').innerHTML;
  assert.match(note, /class="notice good"/);
  assert.match(note, /Deployed on paper: Momentum &lt;b&gt;fade&lt;\/b&gt;\. It trades only when its rule fires, against live prices with paper money, so the first trade can take a while\. Its trades show up here and on your dashboard\./);
  assert.equal(f.S.deployed, null);
  // Once: the next visit to Deploy has no note.
  await f.viewDeploy(); await flush();
  assert.equal(f.root.querySelector('#flash').innerHTML, '');
  // Demo says demo.
  f.S.deployed = {mode: 'demo', title: 'X'}; await f.viewDeploy(); await flush();
  assert.match(f.root.querySelector('#flash').innerHTML, /Deployed on demo: X\. It trades only when its rule fires, on Kalshi’s demo exchange with no real money/);
});

test('money pages: an open position names its market and settles with a date and zone; an unmarked dashboard row says its figure is cost', async () => {
  const pos = (extra) => ({title: 'Drift', ticker: 'KXBTCD-26OCT2617-T68499.99', side: 'no', qty: 25, entry_price: .36, entry_fee: .41, cost: 9.41,
    unrealized: null, mode: 'paper', opened_at: '2026-10-25T08:00:00Z', market_close_time: '2030-01-15T17:30:00Z', ...extra});
  const markets = [{key: 'btc_daily', series: 'KXBTCD', label: 'Bitcoin daily close, 5pm EDT'}];
  const f = frontend({fetchImpl: path => path === '/api/deployments'
    ? response({deployments: [], open_positions: [pos(), pos({ticker: 'KXOTHER-1', market_close_time: new Date().toISOString()})]}) : response({})});
  f.S.me.markets = markets;
  await f.viewDeploy(); await flush(); await flush();
  const html = f.root.querySelector('#openpos').innerHTML;
  // The raw ticker keeps its readable market under it; an unknown series gets no guessed label.
  assert.match(html, /KXBTCD-26OCT2617-T68499\.99<\/a><div class="sub-fig pos-mkt">Bitcoin daily close, 5pm EDT<\/div>/);
  assert.match(html, /KXOTHER-1<\/a><\/td>/);
  // Another day carries its date; today only the time; both name the zone (a bare "21:17" read as today, zone unknown).
  assert.match(html, /data-lab="Settles">Jan 1[56], \d\d:\d\d [^<\s]+<\/td>/);
  assert.match(html, /data-lab="Settles">\d\d:\d\d [^<\s]+<\/td>/);
  // The strategy page's holding says its cost includes the fee, and settles the same way.
  const s = strategyFrontend(detailStrategy({holdings: [pos()]})); s.S.me.markets = markets; await s.viewStrategy(42); await flush();
  const side = s.root.querySelector('main').innerHTML;
  assert.match(side, /<span>Cost \+ fee \$9\.41<\/span>/); assert.match(side, /<span>Settles Jan 1[56], \d\d:\d\d [^<\s]+<\/span>/);
  assert.match(side, /1 open position at cost \+ fees \$9\.41/); assert.match(side, /<div class="sub-fig pos-mkt">Bitcoin daily close, 5pm EDT<\/div>/);
  // Dashboard: an unmarked position's figure is its cost, never a bare dollar amount beside the marked rows' P&L.
  const g = frontend({fetchImpl: path => {
    if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), open_positions: [pos(), pos({qty: 10, entry_price: .47, unrealized: 0.32})]});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await g.viewDashboard(); await flush();
  const main = g.root.querySelector('main').innerHTML;
  assert.match(main, /<span>\$9\.00 at cost<\/span>/); assert.match(main, /<span><span class="gain">\+\$0\.32<\/span><\/span>/);
});

test('track record: the calendar-day count is named as such, so it never contradicts the sample line\'s elapsed days', () => {
  const f = frontend({fetchImpl: () => response({})});
  const m = {trades: 2, wins: 1, losses: 1, label: 'Kalshi demo', net_pnl: -0.03, fees: 0.12, monthly: [], strategies: [], curve: [], days: 2,
    sample: {level: 'thin', edge: 'unclear', text: 'Too early to judge: 2 trades over 1 day.'}};
  const html = f.trackRecordPanel(m, 'demo', {min_sharpe_days: 14, min_trades: 30});
  assert.match(html, /<dt>Calendar days \(UTC\)<\/dt><dd>2<\/dd>/); assert.doesNotMatch(html, /Days of history/);
  // An empty paper record whose closed trades were all instant fills doesn't claim none closed.
  const th = {min_sharpe_days: 14, min_trades: 30};
  const left = f.trackRecordPanel({trades: 0, label: 'Paper', excluded_instant_fills: 8}, 'paper', th);
  assert.match(left, /<h3>No paper trades in the record yet<\/h3>/); assert.match(left, /8 instant-fill paper trades left out/);
  assert.match(f.trackRecordPanel({trades: 0, label: 'Paper'}, 'paper', th), /<h3>No closed paper trades yet<\/h3>/);
});

test('autopilot walk: the last move says what and when, the pill says what it is doing, the pulse never reads Idle over research', () => {
  const f = frontend();
  f.S.me.markets = [{key: 'sol15m', label: 'Solana 15-minute'}];
  const t = (text) => f.apMoveText({text, at: new Date().toISOString()});
  // The first sentence, without the "Autopilot" lead-in or Markdown; the switch reads as the switch.
  assert.equal(t('Autopilot deployed **Lean into it** on paper.'), 'Deployed Lean into it on paper');
  assert.equal(t('Autopilot paused Fade the spike. It lost 22% of its money.'), 'Paused Fade the spike');
  assert.equal(t('Autopilot is ON: the agent may research, deploy and tune paper strategies'), 'Autopilot switched on');
  assert.equal(t('LIVE autopilot is OFF.'), 'Live autopilot switched off');
  // A research start (agent.act names the market by its key) reads the way the app names markets.
  assert.match(t('Started a fresh research session on sol15m — same gates as any run (pre-registration, holdout, diversification).'), /^Started a fresh research session on (?!sol15m)\S/);
  assert.equal(f.apMoveText(null), '');
  // The pill: in paper mode the word for what it is doing; LIVE keeps its label.
  const paper = {label: 'Autopilot · paper'}, live = {label: 'Autopilot · LIVE'};
  const ap = {autopilot: true, mode: 'paper', research: {active: []}, paper_running: 0};
  assert.equal(f.apPillLabel({...ap, research: {active: ['Bitcoin 15-minute']}}, paper), 'Autopilot · researching');
  assert.equal(f.apPillLabel({...ap, reviewing: true}, paper), 'Autopilot · reviewing');
  assert.equal(f.apPillLabel({...ap, paper_running: 2}, paper), 'Autopilot · 2 on paper');
  assert.equal(f.apPillLabel({...ap, billing_blocked: true, research: {active: ['Bitcoin 15-minute']}}, paper), 'Autopilot · paused');
  assert.equal(f.apPillLabel(ap, paper), 'Autopilot · paper');
  assert.equal(f.apPillLabel({...ap, mode: 'live', research: {active: ['Bitcoin 15-minute']}}, live), 'Autopilot · LIVE');
  assert.equal(f.apPillLabel(null, paper), 'Autopilot · paper');
  // The feed's pulse follows the status read: researching, off, or idle on its schedule.
  f.S.ap = {...ap, research: {active: ['Bitcoin 15-minute']}};
  assert.equal(f.apIdleLine(), 'Researching Bitcoin 15-minute');
  f.S.ap = {...ap, research: {active: ["a market it's still picking"]}};
  assert.equal(f.apIdleLine(), 'Picking a market to research');
  f.S.ap = {...ap, autopilot: false, mode: 'off'};
  assert.match(f.apIdleLine(), /^Off: it acts only when you message it/);
  f.S.ap = ap;
  assert.equal(f.apIdleLine(), 'Idle — reviews run on a schedule');
});

test('autopilot walk: the since strip counts the research sessions the autopilot started and reads as a sentence', () => {
  const f = frontend();
  f.S.me.user.autopilot = true;
  const d = {deployments: [], since: {at: '2026-10-25T08:00:00+00:00', first: false, books: {}, passed: {n: 0, items: []},
    autopilot: {research: 2, deploy: 1, set_risk: 1}, runs: {succeeded: 2}}};
  assert.match(f.sinceStrip(d, '#dash-deps'), /<dt>Autopilot<\/dt><dd>It put 1 on paper, started 2 research sessions, made 1 other change\.<\/dd>/);
  d.since.autopilot = {research: 1};
  assert.match(f.sinceStrip(d, '#dash-deps'), /It started 1 research session\./);
});

test('a Deploy poll that reads the same board repaints nothing, and repaints what changed', async () => {
  const dep = {id: 1, strategy_id: 1, title: 'Dep 1', market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
    realized_pnl: 1, closed_trades: 5, open_positions: 1, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5,
    max_positions: 1, backtest: {out_of_sample: null}};
  const pos = {title: 'Dep 1', ticker: 'KXBTC15M-T1', side: 'yes', qty: 2, entry_price: .4, entry_fee: .02, unrealized: null,
    market_close_time: '2026-10-25T17:30:00Z', mode: 'paper'};
  let board = {deployments: [dep], open_positions: [pos]}, reads = 0;
  const f = frontend({fetchImpl: path => {
    if (path === '/api/deployments') { reads++; return response(board); }
    return response({});
  }});
  await f.viewDeploy(); await flush(); await flush();
  const regions = ['#dfigs', '#deps', '#openpos', '#dep-ap'].map(sel => f.root.querySelector(sel));
  const writes = () => regions.map(el => el.writes);
  const first = writes(), stop = f.root.querySelector('#deps [data-act="stop"]');
  stop.onclick();  // armed: a poll used to rewrite the row and drop the confirmation
  assert.equal(stop.textContent, 'Remove and sell 1 open?');  // it holds a position, which Remove sells
  const tick = f.intervals.get(f.S.timers.at(-1));
  tick(); await flush(); await flush();
  assert.equal(reads, 2); assert.deepEqual(writes(), first);
  assert.equal(f.root.querySelector('#deps [data-act="stop"]'), stop); assert.equal(stop.textContent, 'Remove and sell 1 open?');
  board = {deployments: [{...dep, realized_pnl: 2.5, closed_trades: 6}], open_positions: []};  // a trade closed
  tick(); await flush(); await flush();
  assert.equal(reads, 3);
  assert.deepEqual(writes().map((n, i) => n - first[i]), [1, 1, 1, 0]);  // the nudge above the rows did not change
  assert.match(f.root.querySelector('#openpos').innerHTML, /No open positions/);
  assert.match(f.root.querySelector('#deps').innerHTML, /\+\$2\.50/);
});

test('the dashboard asks for the track record beside the board, once, and draws it below', async () => {
  const empty = (label) => ({trades: 0, label});
  const tr = {generated_at: 1, default_mode: 'paper', method: [], thresholds: {min_sharpe_days: 14, min_trades: 30},
    modes: {live: empty('Live money'), demo: empty('Kalshi demo'), paper: empty('Paper')}};
  const dash = deferred();
  let failTrack = true;
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return dash.promise;
    if (path === '/api/track-record') return failTrack ? response({error: 'Tau is restarting.'}, 500) : response(tr);
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  // The real page has <main> inside a wrapper the record is appended to; the harness's elements
  // only know their parent, so give them the DOM's name for it while this test runs.
  Object.defineProperty(Element.prototype, 'parentNode', {get() { return this.parent; }, configurable: true});
  try {
    const view = f.viewDashboard(); await flush();
    const paths = () => f.requests.map(r => r.path).filter(p => p !== '/api/notifications' && p !== '/api/autopilot/status');
    assert.deepEqual(paths(), ['/api/track-record', '/api/dashboard']);  // both asked before the board has answered
    dash.resolve(response(emptyDashboard()));
    await view; await flush(); await flush();
    const host = f.root.querySelector('#track-record');
    assert.match(host.innerHTML, /Tau is restarting\./);  // the early read failed: the record says so, with a retry
    failTrack = false;
    host.querySelector('[data-retry]').onclick(); await flush(); await flush();
    assert.match(host.innerHTML, /Track record/);
    assert.deepEqual(paths(), ['/api/track-record', '/api/dashboard', '/api/track-record']);  // the retry asks again
  } finally {
    delete Element.prototype.parentNode;
  }
});

test('a trade the dashboard poll sees open or close re-reads the track record now, not on its own minute', async () => {
  const empty = (label) => ({trades: 0, label});
  let tr = {generated_at: 1, default_mode: 'paper', method: [], thresholds: {min_sharpe_days: 14, min_trades: 30},
    modes: {live: empty('Live money'), demo: empty('Kalshi demo'), paper: empty('Paper')}};
  let dash = emptyDashboard();
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
    assert.equal(reads(), 1);
    await poll();
    assert.equal(reads(), 1);  // nothing moved: the record keeps its own minute
    const paperChip = () => f.root.querySelector('#track-record [data-trtab="paper"]').textContent;
    assert.equal(paperChip(), 'Paper ·\u00a00');
    // The first trade closes: the board's poll sees it, and the record below follows it at once.
    dash = {...emptyDashboard(), paper: {...emptyDashboard().paper, closed_trades: 1}};
    tr = {...tr, generated_at: 2, modes: {...tr.modes, paper: {...empty('Paper'), trades: 1}}};
    await poll();
    assert.equal(reads(), 2); assert.equal(paperChip(), 'Paper ·\u00a01');
    await poll();
    assert.equal(reads(), 2);  // once per move
  } finally {
    delete Element.prototype.parentNode;
  }
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
  reply = () => response({error: "Something went wrong on our side. It's been logged."}, 500);
  assert.equal(await f.apLoadChat(empty, true), false);
  assert.match(empty.querySelector('#apf-messages').innerHTML, /Couldn’t load the autopilot’s activity\. Retrying\./);
});

test('a page that throws on a reply it did not expect shows plain words, not the TypeError', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/deployments') return response({deployments: 'not a list', open_positions: []});
    return response({});
  }});
  f.location.pathname = '/deploy';
  await f.render(); await flush(); await flush();
  const html = f.root.querySelector('main').innerHTML;
  assert.match(html, /Something went wrong on this page\. Try again\./);
  assert.doesNotMatch(html, /TypeError|is not a function|undefined/);
});

test('Tau: a page change names the tab, and a deployment control names its strategy and says what it did', async () => {
  const dep = {id: 1, strategy_id: 1, title: 'Dep <1>', market: 'btc15m', mode: 'paper', status: 'running', status_reason: null,
    realized_pnl: 1, closed_trades: 5, open_positions: 0, unrealized_pnl: null, created_at: '2026-10-24T08:00:00Z', curve: [], stake: 5,
    max_positions: 1, backtest: {out_of_sample: null}};
  let stopped = false;
  const f = frontend({fetchImpl: path => {
    if (path === '/api/deployments') return response({deployments: stopped ? [] : [dep], open_positions: []});
    if (path === '/api/deployments/1/stop') { stopped = true; return response({ok: true}); }
    return response({});
  }});
  f.location.pathname = '/deploy';
  await f.render(); await flush(); await flush();
  assert.equal(f.document.title, 'Deploy · Tau');
  // Every row's Pause and Remove read the same; the hidden strategy name tells them apart.
  assert.match(f.root.querySelector('#deps [data-act="pause"]').innerHTML, /^Pause<span class="vh"> Dep &lt;1&gt;<\/span>$/);
  // The live regions are in the page before anything is said, and each message goes out through them.
  const said = (id) => { [...f.timeouts.values()].forEach((run) => run()); f.timeouts.clear(); return f.document.getElementById(id).textContent; };
  const stop = f.root.querySelector('#deps [data-act="stop"]');
  stop.onclick();
  assert.equal(stop.textContent, 'Confirm stop');
  assert.equal(f.document.getElementById('sr-status').getAttribute('aria-live'), 'polite');
  assert.equal(f.document.getElementById('sr-alert').getAttribute('aria-live'), 'assertive');
  assert.equal(said('sr-status'), 'Confirm stop: press again within 5 seconds.');
  stop.dataset.armed = '1';  // running the timers above also ran the 5s disarm
  stop.onclick(); await flush(); await flush(); await flush();
  assert.equal(stopped, true);
  assert.equal(said('sr-status'), 'Deployment stopped.');
});

// -- Two-step confirms: a double-click arms and fires nothing ------------------------------------

test('a confirm press right after arming does nothing: a fast double-click cannot skip "Confirm"', () => {
  const f = frontend(), btn = new Element('button'); btn.innerHTML = 'Remove<span class="vh"> Dep</span>';
  let fired = 0; const fire = () => { fired++; };
  f.armed(btn, 'Confirm stop', fire);
  assert.equal(btn.textContent, 'Confirm stop'); assert.equal(btn.classes.has('armed'), true); assert.equal(btn.dataset.armed, 'wait');
  f.armed(btn, 'Confirm stop', fire); f.armed(btn, 'Confirm stop', fire);  // a double (or triple) click's later clicks
  assert.equal(fired, 0); assert.equal(btn.textContent, 'Confirm stop');
  f.elapse(500);  // the hold passes: the next press is a deliberate one
  assert.equal(btn.dataset.armed, '1');
  f.armed(btn, 'Confirm stop', fire);
  assert.equal(fired, 1); assert.equal(btn.dataset.armed, ''); assert.equal(btn.classes.has('armed'), false);
});

test('an armed confirm resets after 5 seconds, and an earlier arming\'s reset never disarms a later one', () => {
  const f = frontend(), btn = new Element('button'); btn.innerHTML = 'Cancel';
  let fired = 0; const fire = () => { fired++; };
  f.armed(btn, 'Confirm cancel', fire); f.elapse(5000);
  assert.equal(btn.dataset.armed, ''); assert.equal(btn.innerHTML, 'Cancel'); assert.equal(btn.classes.has('armed'), false);
  f.armed(btn, 'Confirm cancel', fire); f.elapse(500); f.armed(btn, 'Confirm cancel', fire);
  assert.equal(fired, 1);
  const stale = [...f.timeouts.values()]; f.timeouts.clear();  // the first arming's 5s reset, still pending
  f.armed(btn, 'Confirm cancel', fire);
  stale.forEach(run => run());
  assert.equal(btn.dataset.armed, 'wait'); assert.equal(btn.textContent, 'Confirm cancel');
  f.elapse(500); f.armed(btn, 'Confirm cancel', fire); assert.equal(fired, 2);
});

test('a held Enter key repeats nothing while a confirm is armed, in both bundles', () => {
  const meridian = readFileSync(new URL('../app/static/app.meridian.js', import.meta.url), 'utf8');
  for (const src of [source, meridian]) {
    const body = src.match(/ {2}function guardArmedRepeat\(\) \{[\s\S]*?\n {2}\}\n/);
    assert.ok(body, 'guardArmedRepeat is defined');
    assert.match(src, /\n {2}setupAnnouncer\(\);\n {2}guardArmedRepeat\(\);\n/);  // installed at boot
    const listeners = [], document = {armed: null, addEventListener: (name, fn, capture) => listeners.push({name, fn, capture}), querySelector: () => document.armed};
    vm.runInNewContext(body[0] + 'guardArmedRepeat();', {document});
    assert.equal(listeners.length, 1); assert.equal(listeners[0].name, 'keydown'); assert.equal(listeners[0].capture, true);
    const press = (o) => { let blocked = false; listeners[0].fn({key: 'Enter', repeat: true, target: {tagName: 'BUTTON'}, preventDefault: () => { blocked = true; }, ...o}); return blocked; };
    assert.equal(press(), false);  // nothing armed: Enter repeats as usual
    document.armed = {};
    assert.equal(press(), true);  // the held Enter that armed can't go on to confirm
    assert.equal(press({repeat: false}), false);  // a fresh press still confirms
    assert.equal(press({key: ' '}), false);
    assert.equal(press({target: {tagName: 'TEXTAREA'}}), false);
  }
});

test('the autopilot Kill goes through the shared confirm: a double-click does not kill', async () => {
  let kills = 0;
  const f = frontend({fetchImpl: path => {
    if (path === '/api/autopilot/kill') { kills++; return response({paused: 2}); }
    if (path === '/api/autopilot/status') return response({mode: 'paper', autopilot: true, autopilot_live: false});
    return response({});
  }});
  const box = new Element('div'); box.innerHTML = '<div id="apf-controls"></div><div id="apf-flash"></div>';
  f.apUpdate(box, {mode: 'paper', live_enabled: true, kalshi_connected: true, autopilot: true, autopilot_live: true});
  const kill = box.querySelector('[data-ap="kill"]');
  kill.onclick({currentTarget: kill, target: kill}); kill.onclick({currentTarget: kill, target: kill}); await flush();
  assert.equal(kills, 0); assert.equal(kill.textContent, 'Confirm kill');
  f.elapse(500);
  await kill.onclick({currentTarget: kill, target: kill}); await flush();
  assert.equal(kills, 1);
  f.elapse(5000); kill.onclick({currentTarget: kill, target: kill}); await flush();
  assert.equal(kills, 1);  // a later press arms afresh
});

test('Reset to amount asks first, since it wipes the paper history; Add and Withdraw go at once', async () => {
  const posts = [];
  const f = frontend({fetchImpl: (path, options = {}) => {
    if (path === '/api/funds') return response(funds());
    if (path === '/api/funds/paper') { posts.push(JSON.parse(options.body)); return response({ok: true}); }
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewFunds();
  const submit = async (kind) => {
    const form = f.root.querySelector('#paper'); form.amount = {value: '500'};
    form.querySelector(`[data-kind="${kind}"]`).onclick();
    await form.onsubmit({preventDefault() {}}); await flush(); await flush();
  };
  await submit('deposit');
  assert.deepEqual(posts, [{kind: 'deposit', amount: 500}]);
  await submit('reset'); await submit('reset');  // a double-click on Reset
  assert.equal(posts.length, 1);
  assert.equal(f.root.querySelector('#paper [data-kind="reset"]').textContent, 'Confirm reset');
  f.elapse(500); await submit('reset');
  assert.deepEqual(posts.at(-1), {kind: 'reset', amount: 500});
  await submit('withdraw');
  assert.deepEqual(posts.at(-1), {kind: 'withdraw', amount: 500});
});

// -- Spend: what each charge was for, how fast credits go, and what happens when they run out ------

test('Billing shows the spend pace, what spent it, and what each line was for, never a model id', async () => {
  const f = billingPage(cardedBilling({spent_24h: 1.4, spent_7d_by: {research: 4.2, autopilot_research: 5.1, autopilot_review: 0.5, chat: 0, other: 0}, min_run_balance: 1,
    ledger: [{kind: 'usage', amount: -0.2104, memo: 'Autopilot research · Claude Opus 4.6', item: 'Autopilot research', model: 'Claude Opus 4.6', created_at: '2026-10-25T17:00:00Z'}]}));
  await f.viewBilling(); await flush();
  const figs = f.root.querySelector('#bfigs').innerHTML;
  assert.match(figs, /Spent, last 7 days[\s\S]*\$9\.80[\s\S]*\$1\.40 in the last 24 hours ·\u00a0\$47\.58 all time/);
  assert.equal(f.root.querySelector('#bsplit').innerHTML, 'Last 7 days: autopilot research $5.10 ·\u00a0your research sessions $4.20 ·\u00a0autopilot check-ins $0.50.');
  const row = f.root.querySelector('.t-ledger tbody tr').innerHTML;
  assert.match(row, /Autopilot research<div class="sub-fig">Claude Opus 4\.6<\/div>/);
  assert.match(row, /<time datetime="2026-10-25T17:00:00Z">[^<]*\d\d:\d\d [A-Z+\-0-9:]+<\/time>/);  // a time, with its zone
  assert.doesNotMatch(f.root.querySelector('main').innerHTML, /anthropic|list price/i);
  assert.doesNotMatch(f.root.querySelector('main').innerHTML, /role="status"/);  // enough credits: no out-of-credits notice
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  assert.match(css, /\.bill-detail \.t-dep \{ min-width: 0; \}/);  // Amount stays in view beside Add credits
});

test('Billing under the research floor says research stopped and the next step', async () => {
  const f = billingPage(cardedBilling({balance: 0.4, min_run_balance: 1, auto_reload: false}));
  f.S.me.user.autopilot = true;
  await f.viewBilling(); await flush();
  const main = f.root.querySelector('main').innerHTML;
  assert.match(main, /You have \$0\.40 in credits\. New research needs at least \$1\.00 to start, so none is starting and autopilot is paused\. Add credits here, or turn on auto-reload so it doesn’t stop again\. Autopilot picks up again on its own\./);
  assert.match(f.root.querySelector('#bfigs').innerHTML, /neg/);  // the balance reads as a problem, not a gain
  assert.match(f.root.querySelector('#autorel-when').innerHTML, /^<b>Off\.<\/b> Below \$1\.00 no new research starts and autopilot pauses; a session already running stops at \$0\./);
  const on = billingPage(cardedBilling({balance: -0.3, min_run_balance: 1}));
  await on.viewBilling(); await flush();
  assert.match(on.root.querySelector('main').innerHTML, /You’re out of credits\.[\s\S]*Auto-reload is on but hasn’t topped you up: add credits here, or check your card\./);
});

test('run-until-stopped says what an hour costs at recent rates, how long the balance covers, and when it stops', async () => {
  const research = (estimate) => frontend({fetchImpl: path => {
    if (path === '/api/models') return response({models: [{key: 'opus', label: 'Opus'}, {key: 'haiku', label: 'Haiku'}], default: 'opus'});
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/research/estimate') return response(estimate);
    if (path === '/api/runs') return response({runs: [], counts: {research_running: 0, research_queued: 0}, policy: null});
    if (path.startsWith('/api/research/scoreboard')) return response({});
    if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  let f = research({yours: 0.4, sessions: 6, typical: {}, per_hour: {yours: 1.25, typical: {}}});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 23.4, auto_reload: null};
  await f.viewResearch(); await flush(); await flush();
  const cost = () => f.root.querySelector('#rcost');
  assert.equal(cost().textContent, 'Each round of ideas usually costs about $0.40 (your recent sessions); it keeps starting new rounds until you stop it. '
    + 'At recent rates it costs about $1.25 an hour (your recent sessions). Your $23.40 covers about 19 hours. It stops by itself if your credits run out.');
  const rf = f.root.querySelector('#runforever'); rf.checked = false; rf.dispatchEvent({type: 'change'});
  assert.equal(cost().textContent, 'A session like this usually takes about $0.40 from your credits (your recent sessions).');  // a set-size session: no hourly line
  // No own rate: the model's typical one; with auto-reload on it says that instead of stopping.
  f = research({yours: null, sessions: 0, typical: {}, per_hour: {yours: null, typical: {opus: 3}}});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 100, auto_reload: {amount: 20, charge: 21.1, threshold: 5}};
  await f.viewResearch(); await flush(); await flush();
  assert.equal(cost().textContent, 'At recent rates it costs about $3.00 an hour (recent sessions on this model). Your $100.00 covers about 33 hours. Auto-reload adds $20.00 when your balance falls to $5.00, charging your card $21.10.');
  const model = f.root.querySelector('#rmodel'); model.value = 'haiku'; model.dispatchEvent({type: 'change'});
  // Nothing known for this model: with payments on it says how it is billed instead of going blank.
  assert.match(cost().textContent, /^No cost estimate for this model yet\. It’s charged to your credits as it runs/);
});

test('the autopilot card puts credits left and the only limit beside its spend, and a credits pause says how much it needs', async () => {
  const week = {research_credits: 7.26, tested: 10, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0, checkin_credits: 0.42, credits_left: 23.4, runway_days: 6.1};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/autopilot/status') return response({...apOn, week});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 23.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = true; f.S.ap = {...apOn, week};
  await f.viewDashboard(); await flush();
  const card = f.root.querySelector('#dash-ap').innerHTML;
  assert.match(card, /<dt>Credits spent on research<\/dt><dd>\$7\.26 <small>real money ·\u00a0plus \$0\.42 on its check-ins<\/small><\/dd>/);
  assert.match(card, /Credits left: <b>\$23\.40<\/b>, about 6 days at this week’s pace\. It has no daily spending cap: it uses credits until your balance is under \$1\.00, then pauses\./);
  f.S.ap = {...apOn, week, billing_blocked: true, billing_reason: 'credits'}; f.paintDashAp();
  assert.match(f.root.querySelector('#dash-ap').innerHTML, /Paused: starting research needs \$1\.00 in credits\. <a href="\/billing">Add credits<\/a> and it picks up on its own\./);
  f.clearTimers();
});

test('a credits pause puts the week line in the paused state, and the next status read after a top-up puts it back', async () => {
  const week = {research_credits: 7.26, tested: 10, passed: 0, paper_started: 0, paper_pnl: 0, paper_trades: 0, checkin_credits: 0, credits_left: 0.4, runway_days: 0.4};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/autopilot/status') return response({...apOn, week});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, credit_balance: 0.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = true; f.S.ap = {...apOn, week, billing_blocked: true, billing_reason: 'credits'};
  await f.viewDashboard(); await flush();
  const line = () => f.root.querySelector('#dash-ap .ap-week-left').innerHTML;
  // Already paused: it said "it uses credits until your balance is under $1.00, then pauses" and how long $0.40 lasts.
  assert.equal(line(), 'Credits left: <b>$0.40</b>. Research is paused until you add credits: a session needs $1.00 to start. <a href="/billing">Billing</a> lists every charge.');
  assert.doesNotMatch(line(), /then pauses|this week’s pace|no daily spending cap/);
  f.S.ap = {...apOn, week, billing_blocked: true, billing_reason: 'card'}; f.paintDashAp();
  assert.match(line(), /Research is paused until you add a payment method\./);
  // Credits added: the status read clears the pause and the running copy comes back.
  f.S.ap = {...apOn, week: {...week, credits_left: 20.4, runway_days: 17}}; f.paintDashAp();
  assert.match(line(), /^Credits left: <b>\$20\.40<\/b>, about 17 days at this week’s pace\. It has no daily spending cap: it uses credits until your balance is under \$1\.00, then pauses\./);
  f.clearTimers();
});

test('the autopilot switch card says it would wait for credits when the balance is already under what research needs', async () => {
  const f = frontend({fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, credit_balance: 0.4, min_run_balance: 1, auto_reload: null};
  f.S.me.user.autopilot = false; f.S.ap = null;
  await f.viewDashboard(); await flush();
  const cost = f.root.querySelector('#dash-ap .apcard-cost').innerHTML;
  assert.equal(cost, 'It uses your credits while it\'s on. You have $0.40, under the $1.00 a research session needs to start, so it waits until you <a href="/billing">add credits</a>. Turn it off any time.');
  f.clearTimers();
});

test('Billing copies its balance and card onto the page state, and a moved balance re-reads the autopilot status', async () => {
  const f = frontend({stripe: STRIPE_STUB, fetchImpl: (path) => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response(cardedBilling({balance: 20.4}));
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    if (path === '/api/autopilot/status') return response({...apOn, billing_blocked: false});
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
  // The dashboard's "Needs you" no longer says credits are at $0.40 (it did until a reload).
  const since = {deployments: [], since: {at: '2026-10-25T08:00:00+00:00', first: false, books: {}, passed: {n: 0, items: []}, autopilot: {}, runs: {}}};
  assert.doesNotMatch(f.sinceStrip(since, '#dash-deps'), /Credits are at/);
  f.S.me.credit_balance = 0.4;
  assert.match(f.sinceStrip(since, '#dash-deps'), /Credits are at \$0\.40/);  // the same strip, under the floor
  f.S.me.credit_balance = 20.4;
  // Read again with nothing moved: no extra status read.
  await f.viewBilling(); await flush(); await flush();
  assert.equal(f.requests.filter(({path}) => path === '/api/autopilot/status').length, 1);
});

// The bell, the reconciliation warning and the demo key line: what a once-a-day reader needs to trust.
const bellNotes = () => ({unread: 1, items: [
  {id: 3, kind: 'paused', body: '“A” was paused automatically.', link: '/strategies/3', created_at: new Date(Date.now() - 2 * 3600e3).toISOString(), read: false},
  {id: 2, kind: 'comment', body: 'Ana commented on your post.', link: '/community', created_at: new Date(Date.now() - 3 * 86400e3).toISOString(), read: true},
]});
const bellFrontend = (notifications) => frontend({notifications, fetchImpl: path => {
  if (path === '/api/dashboard') return response(emptyDashboard());
  if (path === '/api/notifications/read') return response({ok: true});
  throw new Error('Unexpected offline request: ' + path);
}});

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

test('a bell item older than a day shows its day and clock, and every item its full time on hover', async () => {
  const f = bellFrontend(bellNotes());
  await f.viewDashboard(); await flush(); await flush();
  const [recent, older] = f.root.querySelectorAll('#bell-list time');
  assert.equal(recent.textContent, '2h ago');
  assert.match(older.textContent, /^[A-Z][a-z]{2} \d{1,2}, \d\d:\d\d$/);  // "Oct 23, 14:05", not a bare "Oct 23"
  for (const t of [recent, older]) { assert.ok(t.getAttribute('datetime')); assert.match(t.getAttribute('title'), /\d\d:\d\d/); }
  // Nothing new: no count, no marks.
  const g = bellFrontend({unread: 0, items: bellNotes().items.map((n) => ({...n, read: true}))});
  await g.viewDashboard(); await flush(); await flush();
  assert.equal(g.root.querySelector('.bell-new'), null); assert.equal(g.root.querySelectorAll('.notif.unread').length, 0);
});

test('the reconciliation warning names the contracts and where to compare them; Tau has no Portfolio page', async () => {
  for (const [rows, said] of [
    [[{ticker: 'KXBTCD-26OCT2617-T100000', kind: 'untracked'}], /1 live position disagrees with Kalshi \(KXBTCD-26OCT2617-T100000\)\./],
    [['A', 'B', 'C', 'D'].map((x) => ({ticker: 'KX-' + x, kind: 'size_mismatch'})), /4 live positions disagree with Kalshi \(KX-A, KX-B, KX-C and 1 more\)\./],
  ]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response({...emptyDashboard(), reconcile: rows,
        live: {connected: true, balance: 50, open_positions: 2, running: 1, realized_pnl: 0, today_pnl: 0}});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    const board = f.root.querySelector('#boardbody').innerHTML;
    assert.match(board, said);
    assert.match(board, /Compare <a href="#dash-open">Tau’s open positions<\/a> with the positions in your Kalshi account\./);
    assert.doesNotMatch(board, /Portfolio/);
    assert.ok(f.root.querySelector('#dash-open'), 'the link lands on the open positions list');
  }
});

test('a new account\'s paper card says nothing is on paper yet instead of "$0.00 at cost"', async () => {
  const fresh = {...emptyDashboard(), paper: {equity: 1000, cash: 1000, open_at_cost: 0, total_pnl: 0, realized_pnl: 0, open_positions: 0, closed_trades: 0}};
  const dep = {id: 1, strategy_id: 1, title: 'S', market: 'btc15m', mode: 'paper', status: 'running', stake: 5, max_positions: 2,
    realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 0, created_at: '2026-10-25T08:00:00Z'};
  for (const [d, empty] of [[fresh, true], [{...fresh, deployments: [dep]}, false]]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response(d);
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    const board = f.root.querySelector('#boardbody').innerHTML;
    if (empty) { assert.match(board, /\$1,000\.00 of practice money ·\u00a0no paper strategies yet/); assert.doesNotMatch(board, /at cost/); }
    else assert.match(board, /\$1,000\.00 cash ·\u00a0\$0\.00 at cost ·\u00a0<span class="amt">\$0\.00<\/span> realized all time/);  // a strategy on paper: its book, zeros and all
  }
});

test('a paused deployment row names its book beside "Paused"', async () => {
  for (const [mode, tag] of [['paper', '<span class="mk">PAPER</span>'], ['live', '<span class="mk live">LIVE</span>'], ['demo', '<span class="mk dep">DEMO</span>']]) {
    const dep = {id: 1, strategy_id: 1, title: 'S', market: 'btc15m', mode, status: 'paused', status_reason: 'loss guard', stake: 5, max_positions: 2,
      realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 0, created_at: '2026-10-25T08:00:00Z'};
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response({...emptyDashboard(), deployments: [dep]});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    assert.equal(f.root.querySelector('#dash-deps td[data-lab="Status"]').innerHTML, `<span class="mk armed">Paused</span> ${tag}`);
  }
});

test('the dashboard status line never calls demo paper money', async () => {
  const dep = (mode, status = 'running') => ({id: 1, strategy_id: 1, title: 'S', market: 'btc15m', mode, status, status_reason: null, stake: 5, max_positions: 2,
    realized_pnl: 0, unrealized_pnl: null, closed_trades: 0, open_positions: 0, created_at: '2026-10-25T08:00:00Z'});
  for (const [deps, said] of [[[dep('paper')], 'Paper money only'], [[dep('paper'), dep('demo')], 'No real money: paper and demo'],
    [[dep('paper'), dep('demo', 'stopped')], 'Paper money only'], [[dep('demo', 'paused')], 'No real money: paper and demo']]) {
    const f = frontend({fetchImpl: path => {
      if (path === '/api/dashboard') return response({...emptyDashboard(), deployments: deps});
      throw new Error('Unexpected offline request: ' + path);
    }});
    await f.viewDashboard(); await flush();
    assert.equal(f.root.querySelector('.statusline .said').innerHTML.split('<span class="sep">')[0], said);
  }
});

test('Funds says what demo proves, where it sits on the ladder, and why a small demo balance starts no copies', async () => {
  const view = async (dev) => {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds'); return response({...funds(), kalshi_dev: dev}); }});
    await f.viewFunds();
    return {main: f.root.querySelector('main').innerHTML, figs: f.root.querySelector('#ffigs').innerHTML};
  };
  const none = await view({connected: false});
  // Demo is the order path's test, not realistic slippage: its book is thin, so it is no evidence of the edge.
  assert.match(none.main, /to prove the order path before live money\. The sandbox book is thin, so its fills and P&amp;L are no evidence of the edge; paper keeps that job\./);
  assert.doesNotMatch(none.main, /slippage is realistic/);
  assert.match(none.main, /Demo is the step between paper and live: it proves orders place, fill and book/);
  assert.match(none.figs, /needs a demo key ·\u00a0real fills on Kalshi’s sandbox/);
  const dev = {connected: true, key_id: 'DEVK…1234', copies_from: 100};
  const low = await view({...dev, balance: 40});
  assert.doesNotMatch(low.figs, /needs a demo key/);
  assert.match(low.main, /Your Kalshi demo account has \$40\.00\. Demo copies of your paper strategies start once it holds \$100\.00: add play money in your account on <a href="https:\/\/demo\.kalshi\.co[^"]*"/);
  assert.match((await view({...dev, balance: 0})).main, /Your Kalshi demo account has \$0\.00, so Kalshi refuses demo orders\./);
  for (const ok of [{...dev, balance: 100}, {...dev, balance: 40, copies_from: null}, {...dev, balance: null}]) {
    assert.doesNotMatch((await view(ok)).main, /Your Kalshi demo account has/);
  }
});

test('Funds says when the demo key\'s balance was read, as it does for Kalshi cash', async () => {
  const read = new Date(Date.now() - 5 * 60000).toISOString();
  for (const [at, said] of [[read, /\(balance \$25\.00, read 5m ago\) <span class="hint">in your Kalshi demo account/], [undefined, /\(balance \$25\.00\) <span class="hint">in your Kalshi demo account/]]) {
    const f = frontend({fetchImpl: path => { assert.equal(path, '/api/funds');
      return response({...funds(), kalshi_dev: {connected: true, key_id: 'DEVK…1234', balance: 25, balance_at: at}}); }});
    await f.viewFunds();
    assert.match(f.root.querySelector('main').innerHTML, said);
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
  const f = frontend({storage: {getItem: key => key === 'tau_ap_open' ? '1' : null, setItem() {}}, fetchImpl: (path, options) => {
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

test('track record: stopped and removed strategies stay in the table and say so; profit factor and Sharpe read after fees, with a true minus', () => {
  const f = frontend();
  const th = {min_sharpe_days: 14, min_trades: 30};
  const row = (o) => ({strategy_id: 4, title: 'Fade', market: 'btc15m', trades: 12, open_trades: 0, net_pnl: -3, win_rate: 0.4,
    avg_trade: -0.25, max_drawdown: 4, last_trade_at: 1790000000, edge: 'thin', status: 'running', removed: false, ...o});
  const m = {trades: 40, wins: 16, losses: 24, label: 'Paper', net_pnl: -9, fees: 3, monthly: [], curve: [], days: 20,
    sharpe: -1.25, sortino: -2.5, psr: 0.2, profit_factor: 0.6,
    sample: {level: 'early', edge: 'unclear', text: 'Early read.'},
    strategies: [row({}), row({strategy_id: 5, title: 'Reversal', status: 'stopped'}), row({strategy_id: 6, status: 'paused'}),
      row({strategy_id: 7, title: 'Removed strategy', market: 'high_ny', status: 'stopped', removed: true})]};
  const html = f.trackRecordPanel(m, 'paper', th);
  assert.match(html, /<h2>By strategy<\/h2><p>Stopped ones included/);
  assert.match(html, /<a href="\/strategies\/5">Reversal<\/a><div class="sub-fig">Stopped<\/div>/);
  assert.match(html, /<a href="\/strategies\/6">Fade<\/a><div class="sub-fig">Paused<\/div>/);
  assert.match(html, /<a href="\/strategies\/4">Fade<\/a><\/td>/);  // a running one needs no label
  // A removed strategy has no page left: no dead link, and its market says which one it was.
  assert.doesNotMatch(html, /\/strategies\/7/);
  assert.match(html, /Removed strategy<div class="sub-fig">NYC high temp · stopped, then removed<\/div>/);
  // Every trade's P&L is net of fees, so the ratio isn't "gross" beside the gross-before-fees line.
  assert.match(html, /winning trades ÷ losing trades, after fees/); assert.doesNotMatch(html, /gross wins/);
  assert.match(html, /−1\.25/); assert.match(html, /Sortino −2\.50/); assert.doesNotMatch(html, />-1\.25</);
});

// A newcomer's first hour: what the card wall charges, what the dashboard says right after the switch, and
// what the empty autopilot feed promises.
const cardWall = async (billing) => {
  const f = frontend({stripe: STRIPE_STUB, fetchImpl: path => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response({configured: true, publishable_key: 'synthetic-only', ...billing});
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.location.pathname = '/'; Object.assign(f.S.me, {needs_card: true, free_bonus: 20});
  await f.paymentGate(); await flush();
  return f.document.body.querySelector('.pay-modal');
};

test('the card wall says saving the card charges nothing and what auto-reload will charge it, before it is saved', async () => {
  const dlg = await cardWall({auto_reload: true, autoreload_threshold: 5, autoreload_amount: 20, autoreload_charge: 21.1});
  assert.match(dlg.querySelector('.wl-sub').innerHTML, /Save a card and we'll add \$20 in free credits\./);
  assert.doesNotMatch(dlg.innerHTML, /by the token|list price/i);
  const terms = dlg.querySelector('#pay-terms');
  assert.equal(terms.hidden, false);
  assert.equal(terms.textContent, 'Saving the card charges nothing. Auto-reload is on: when your credits fall to $5.00, we charge the card $21.10 for $20.00 more. You can turn it off on Billing.');
  // Auto-reload already off on this account: no reload promise.
  const off = await cardWall({auto_reload: false, autoreload_threshold: 5, autoreload_amount: 20, autoreload_charge: 21.1});
  assert.equal(off.querySelector('#pay-terms').textContent, 'Saving the card charges nothing.');
});

test('turning autopilot on updates the last-24-hours row at once, not only after a reload', async () => {
  const f = frontend({fetchImpl: (path) => {
    if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), since: {at: '2026-10-25T08:00:00+00:00', first: true,
      books: {}, passed: {n: 0, items: []}, autopilot: {}, runs: {}, own_sessions: false}});
    if (path === '/api/settings') return response({ok: true});
    if (path === '/api/autopilot/status') return response(apOn);
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewDashboard(); await flush();
  const row = () => f.root.querySelector('#dash-since [data-since-ap]').textContent;
  assert.equal(row(), 'Off.');
  await f.root.querySelector('#dash-ap [data-apcard="on"]').onclick(); await flush(); await flush();
  assert.equal(row(), 'On. It made no changes.');
});

test('the empty autopilot feed says it trades real money only after live autopilot is turned on', async () => {
  const f = frontend({fetchImpl: () => response({messages: []})});
  const box = f.document.createElement('div'); box.innerHTML = '<ol id="apf-messages"></ol>';
  await f.apLoadChat(box, true);
  const empty = box.querySelector('#apf-messages').innerHTML;
  assert.match(empty, /on paper \(pretend money\)\. It trades real money only if you also turn on live autopilot\./);
  assert.doesNotMatch(empty, /promoting to paper or live|gates/);
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
    assert.match(html, /Uncaught error \u00b7\u00a0app\.js:12:5/);
    assert.match(html, /data-lab="Page, theme, build">\/strategies\/:id<div class="sub-fig">meridian, tau \u00b7\u00a0build &lt;b&gt;v&lt;\/b&gt; \+1\u00a0older<\/div>/);
    assert.match(html, /data-lab="Count">3<div class="sub-fig">1 signed out<\/div>/);
    assert.match(html, /data-lab="Last seen">.+<div class="sub-fig">first .+<\/div><\/td><\/tr>/);
    assert.equal(f.root.querySelector('#ce-count').textContent, 'last 24h \u00b7\u00a03 reports');
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
      if (path.startsWith('/api/dashboard')) return response({...emptyDashboard(), deployments, since, ...extra});
      if (path === '/api/autopilot/status') return response({autopilot: false, mode: 'off'});
      throw new Error('Unexpected offline request: ' + path);
    }});
    f.S.me = {...f.S.me, billing_enabled: true, needs_card: false, credit_balance: 7.15, min_run_balance: 1, auto_reload: null, ...me};
    f.S.me.user.autopilot = true;
    await f.viewDashboard(); await flush();
    return f.root.querySelector('#dash-since').innerHTML;
  };
  const text = await strip({});
  // What it cost: its own row, real money, never added to the paper book above it.
  assert.match(text, /<dt>Cost<\/dt><dd><b>\$27\.45<\/b> of credits spent<span class="since-sub"> · real money · \$7\.15 left · <a href="\/billing">Billing<\/a><\/span><\/dd>/);
  assert.match(text, /<b>Paper<\/b> <span class="pos">\+\$12\.65<\/span>/);
  assert.doesNotMatch(text, /\$40\.10|−\$14\.80|\$14\.80/);  // paper and credits never summed or netted
  // The forward-test pass leads New results when nothing else passed, named from the page's deployments.
  assert.match(text, /<dt>New results<\/dt><dd><a href="\/strategies\/232">ETH &lt;i&gt;drift&lt;\/i&gt;<\/a> passed its paper forward test: a candidate for live <span class="since-sub">/);
  assert.doesNotMatch(text, /Nothing new passed/);
  // Live-ready is the week's next step, first under Needs you; the runway warns before the pause.
  assert.match(text, /<dt>Needs you<\/dt><dd><a href="\/strategies\/232">ETH &lt;i&gt;drift&lt;\/i&gt;<\/a> is ready for live trading\. Going live is your call\./);
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
    if (path.startsWith('/api/dashboard')) return response(emptyDashboard());
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

// ---- Failures a user can act on: a write that failed says why next to it and puts the screen back; a write
// that landed says so even when the page can't refresh after it; one send per press.

test('the autopilot switch in the panel locks while it saves, and a failed save goes back to the saved state and says why in the panel', async () => {
  const save = deferred(); let posts = 0;
  const f = frontend({storage: memoryStorage(), fetchImpl: path => {
    if (path === '/api/dashboard') return response(emptyDashboard());
    if (path === '/api/settings') { posts++; return save.promise; }
    if (path === '/api/autopilot/status') return response({...apOn, autopilot: false, mode: 'off', focus: []});
    if (path === '/api/models') return response({models: [], default: ''});
    if (path.startsWith('/api/chat')) return response({messages: []});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.S.me.user.autopilot = false; f.S.ap = {...apOn, autopilot: false, mode: 'off', focus: []};
  await f.viewDashboard(); await flush();
  await f.root.querySelector('#dash-ap [data-apcard="focus"]').onclick(); await flush();
  const box = f.root.parent.querySelector('#autopilot-float'), sw = box.querySelector('#apf-apswitch');
  sw.checked = true; const saving = sw.onchange(); await flush();
  assert.equal(sw.disabled, true);  // a second flip can't race the first
  save.resolve(response({error: 'Autopilot could not be saved. Try again.'}, 500)); await saving; await flush();
  assert.equal(posts, 1);
  assert.equal(sw.checked, false); assert.equal(sw.disabled, false); assert.notEqual(f.S.me.user.autopilot, true);
  assert.match(box.querySelector('#apf-flash').innerHTML, /error-text">Autopilot could not be saved\. Try again\./);
  f.clearTimers();
});

test('an auto-reload change that does not save puts the switch, amounts and summary back, and locks while it saves', async () => {
  let pending = null; const sent = [];
  const f = frontend({stripe: STRIPE_STUB, fetchImpl: (path, options = {}) => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response(cardedBilling());
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    if (path === '/api/billing/auto-reload') { sent.push(JSON.parse(options.body)); pending = deferred(); return pending.promise; }
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewBilling(); await flush();
  const box = f.root.querySelector('#autoreload'), amt = f.root.querySelector('#reload-amt'), when = () => f.root.querySelector('#autorel-when').innerHTML;
  assert.equal(box.checked, true); assert.match(when(), /^<b>On\.<\/b>[\s\S]*\$25\.00 of credits/);
  // A new amount that fails: auto-reload stays on, at the saved amount (it used to flip the switch off).
  amt.value = '40'; let saving = amt.onchange(); await flush();
  assert.deepEqual([box.disabled, amt.disabled], [true, true]);
  assert.deepEqual(sent.at(-1), {on: true, amount: 40, threshold: 8});
  pending.resolve(response({error: 'Your card was declined.'}, 402)); await saving; await flush();
  assert.equal(box.checked, true); assert.equal(String(amt.value), '25'); assert.equal(box.disabled, false);
  assert.equal(f.root.querySelector('#autorel-sum').textContent, 'Reload $25 at $8');
  assert.match(when(), /^<b>On\.<\/b>[\s\S]*\$25\.00 of credits/);
  assert.match(f.root.querySelector('#autorel-flash').innerHTML, /notice bad[\s\S]*Your card was declined\./);
  // Switching off that fails: the summary doesn't keep saying Off.
  box.checked = false; saving = box.onchange(); await flush();
  pending.resolve(response({}, 503)); await saving; await flush();
  assert.equal(box.checked, true); assert.match(when(), /^<b>On\.<\/b>/);
  assert.match(f.root.querySelector('#autorel-flash').innerHTML, /may or may not have gone through/);
  // A save that lands becomes the state the next failure goes back to.
  box.checked = false; saving = box.onchange(); await flush();
  pending.resolve(response({ok: true})); await saving; await flush();
  assert.match(when(), /^<b>Off\.<\/b>/);
  box.checked = true; saving = box.onchange(); await flush();
  pending.resolve(response({error: 'Try again.'}, 400)); await saving; await flush();
  assert.equal(box.checked, false); assert.match(when(), /^<b>Off\.<\/b>/);
});

test('a top-up that went through says so even when the page cannot refresh after it, so nobody buys twice', async () => {
  let reads = 0;
  const f = frontend({stripe: STRIPE_STUB, fetchImpl: path => {
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
  assert.match(said, /Added \$20\.00 in credits\.[\s\S]*New balance is \$27\.42\. The page didn’t refresh, so reload to see it\./);
});

test('Community: Post and Share my P&L send once while either is out, and a failed reply says why under its own box', async () => {
  const post = {id: 11, body: 'Hi', author: 'Bob', username: 'bob', created_at: '2026-10-17T10:00:00Z', mine: false, comments: 1, reactions: [{emoji: '👍', count: 1, mine: false}]};
  const sending = deferred(), reacting = deferred(); let posts = 0, reacts = 0, feedOk = true;
  const f = frontend({fetchImpl: (path, options = {}) => {
    if (path === '/api/strategies') return response({strategies: []});
    if (path === '/api/community' && options.method === 'POST') { posts++; return sending.promise; }
    if (path === '/api/community') return feedOk ? response({posts: [post]}) : response({error: 'Tau is busy.'}, 500);
    if (path === '/api/community/11/react') { reacts++; return reacting.promise; }
    if (path === '/api/community/11/comments' && options.method === 'POST') return response({error: 'Replies are closed on this post.'}, 400);
    if (path === '/api/community/11/comments') return response({comments: [{body: 'First', author: 'Ana', created_at: '2026-10-17T10:00:00Z'}]});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewCommunity(); await flush();
  const form = f.root.querySelector('#composer-post'), share = form.querySelector('[data-share="pnl"]'), postBtn = form.querySelector('[type=submit]');
  share.onclick(); f.elapse(500);  // Share my P&L asks first (community_frontend_cases.mjs); the second press sends
  const first = share.onclick(); await flush();
  assert.deepEqual([share.disabled, postBtn.disabled], [true, true]);
  await share.onclick(); form.onsubmit({preventDefault() {}}); await flush();
  assert.equal(posts, 1);
  feedOk = false;  // the post lands, the feed refresh after it doesn't
  sending.resolve(response({ok: true, id: 12})); await first; await flush();
  assert.deepEqual([share.disabled, postBtn.disabled], [false, false]);
  assert.match(f.root.querySelector('#post-flash').innerHTML, /notice good[\s\S]*Posted\. The page didn’t refresh/);
  feedOk = true;
  // A reaction is one send per tap: a second tap while the first is out doesn't toggle it back off.
  const feed = f.root.querySelector('#feed'), click = (target) => feed.listeners.get('click')({target});
  const chip = feed.querySelector('.rx[data-emoji]');
  click(chip); click(chip); await flush();
  assert.equal(reacts, 1);
  reacting.resolve(response({reactions: [{emoji: '👍', count: 2, mine: true}]})); await flush(); await flush();
  click(feed.querySelector('.rx[data-emoji]')); await flush();
  assert.equal(reacts, 2);
  // A reply that fails says so under the reply box, not at the top of the feed.
  await click(feed.querySelector('[data-act="comments"]')); await flush();
  const box = feed.querySelector('.comments'), cf = box.querySelector('.cmt-form');
  cf.querySelector('input').value = 'Nice';
  await cf.onsubmit({preventDefault() {}, currentTarget: cf}); await flush();
  assert.match(box.querySelector('.form-flash').innerHTML, /notice bad[\s\S]*Replies are closed on this post\./);
  assert.equal(f.root.querySelector('main [data-alert0]'), null);
});

test('a card wall whose card form did not load says what to do, and Save becomes Try again', async () => {
  let up = false;
  const f = frontend({stripe: STRIPE_STUB, fetchImpl: path => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response({configured: true, publishable_key: 'synthetic-only'});
    if (path === '/api/billing/setup-intent') { if (!up) throw new TypeError('Failed to fetch'); return response({client_secret: 'synthetic'}); }
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.location.pathname = '/'; Object.assign(f.S.me, {needs_card: true, free_bonus: 20});
  await f.paymentGate(); await flush();
  const wall = () => f.document.body.querySelectorAll('.pay-modal').filter(d => d.isConnected).at(-1);
  let dlg = wall();
  assert.match(dlg.querySelector('#pay-hint').innerHTML, /The card form didn’t load\. Check your connection, or allow js\.stripe\.com if a blocker is on, then try again\./);
  assert.doesNotMatch(dlg.querySelector('#pay-hint').innerHTML, /Failed to fetch|may or may not/);
  assert.equal(dlg.querySelector('#pay-submit').textContent, 'Try again');
  up = true;
  dlg.querySelector('#payform').onsubmit({preventDefault() {}}); await flush(); await flush();
  dlg = wall();
  assert.equal(dlg.querySelector('#pay-hint').innerHTML, '');
  assert.equal(dlg.querySelector('#pay-submit').textContent, 'Save payment method');
});

test('the card wall shows Stripe\'s words only about the card itself, never its other errors', async () => {
  let reply = {error: {type: 'invalid_request_error', message: "No such setupintent: 'seti_synthetic'"}};
  const stripe = () => ({confirmSetup: async () => reply, elements: () => ({create: () => ({mount() {}})})});
  const f = frontend({stripe, fetchImpl: path => {
    if (/^\/api\/billing(\?|$)/.test(path)) return response({configured: true, publishable_key: 'synthetic-only'});
    if (path === '/api/billing/setup-intent') return response({client_secret: 'synthetic'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  f.location.pathname = '/'; Object.assign(f.S.me, {needs_card: true, free_bonus: 20});
  await f.paymentGate(); await flush();
  const dlg = f.document.body.querySelectorAll('.pay-modal').filter(d => d.isConnected).at(-1);
  const submit = async () => { dlg.querySelector('#payform').onsubmit({preventDefault() {}}); await flush(); await flush(); };
  await submit();
  assert.match(dlg.querySelector('#pay-hint').innerHTML, /Your card couldn’t be saved just now\. Reload the page and add it again\./);
  assert.doesNotMatch(dlg.querySelector('#pay-hint').innerHTML, /seti_|No such/);
  reply = {error: {type: 'card_error', message: 'Your card was declined.'}};  // written for the cardholder
  await submit();
  assert.match(dlg.querySelector('#pay-hint').innerHTML, /Your card was declined\./);
});

test('a session that ends mid-use says so on the sign-in page, and that a change was not saved', async () => {
  const f = frontend({fetchImpl: () => response({error: 'Please sign in.'}, 401)});
  f.location.pathname = '/community';
  await assert.rejects(f.api('/api/community', {body: 'draft'}), /Please sign in/); await flush(); await flush();
  assert.deepEqual(f.navigations, ['/signin?next=%2Fcommunity']);
  assert.match(f.root.querySelector('.lnotice').textContent, /You were signed out, so that last change wasn’t saved\. Sign in to go back to the page and try it again\./);
  // Said once: a later visit to sign-in is the plain page.
  const signin = f.routes.find(([pattern]) => pattern.test('/signin'))[1];
  await signin(); await flush();
  assert.equal(f.root.querySelector('.lnotice'), null);
  // A read that hits an ended session says only that it ended.
  f.S.me = {user: {id: 7}}; f.location.pathname = '/deploy';
  await assert.rejects(f.api('/api/deployments'), /Please sign in/); await flush(); await flush();
  assert.match(f.root.querySelector('.lnotice').textContent, /^You were signed out\. Sign in to go back to the page you were on\.$/);
  // An edge page in front of Tau that answers a 4xx with no words says what to do.
  const g = frontend({fetchImpl: () => ({ok: false, status: 403, json: async () => { throw new SyntaxError('html'); }})});
  await assert.rejects(g.api('/api/funds/paper', {kind: 'deposit', amount: 5}), /Tau couldn't do that \(403\)\. Reload the page and try again\./);
});


// Keyboard-only and screen-reader paths into autopilot: a change nobody says out loud, and focus
// dropped at the top of the page, both used to happen on the one-click way in.
const srSaid = f => { [...f.timeouts.values()].forEach(callback => callback()); return f.document.getElementById('sr-status')?.textContent || ''; };

test('turning autopilot on says so out loud and hands focus to the control that replaced the button', async () => {
  let status = {autopilot: false, mode: 'off'};
  const f = frontend({storage: {getItem: key => (key === 'tau_ap_open' ? '1' : null), setItem() {}},
    fetchImpl: path => {
      if (path === '/api/dashboard') return response(emptyDashboard());
      if (path === '/api/autopilot/status') return response(status);
      if (path === '/api/settings') { status = {...apOn}; return response({ok: true}); }
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
  f.S.ap = status;
  await f.viewDashboard(); await flush(); await flush();
  const on = f.root.querySelector('#dash-ap [data-apcard="on"]');
  f.document.activeElement = on;
  await on.onclick(); for (let i = 0; i < 4; i++) await flush();
  assert.match(srSaid(f), /^Autopilot is on\. It researches and trades on paper by itself/);
  const box = f.document.getElementById('autopilot-float');
  assert.equal(box.querySelector('.apf-x').focused, true);  // the open panel, not the masthead
  f.clearTimers();
});

test('the panel switch says its new state and keeps keyboard focus while it saves', async () => {
  let status = {...apOn};
  const f = frontend({storage: {getItem: key => (key === 'tau_ap_open' ? '1' : null), setItem() {}},
    fetchImpl: path => {
      if (path === '/api/autopilot/status') return response(status);
      if (path === '/api/settings') { status = {autopilot: false, mode: 'off'}; return response({ok: true}); }
      if (path === '/api/models') return response({models: [], default: ''});
      if (path.startsWith('/api/chat')) return response({messages: []});
      throw new Error('Unexpected offline request: ' + path);
    }});
  f.S.me.user.autopilot = true; f.S.ap = status;
  const box = new Element('div', {id: 'autopilot-float'}); f.document.body.appendChild(box);
  f.renderAutopilot(box, status); await flush();
  const sw = box.querySelector('#apf-apswitch');
  // The browser blurs a control that goes disabled, which is the state the save leaves behind.
  f.document.activeElement = f.document.body; sw.checked = false;
  await sw.onchange(); for (let i = 0; i < 3; i++) await flush();
  assert.equal(f.S.me.user.autopilot, false);
  assert.match(srSaid(f), /^Autopilot is off\. It only suggests ideas for you to approve\.$/);
  assert.equal(sw.focused, true);  // focus comes back to the switch, not the top of the page
  f.clearTimers();
});

test('the full-screen autopilot sheet keeps Tab inside it; beside the page it lets Tab walk on', async () => {
  for (const sheet of [true, false]) {
    const f = frontend({storage: {getItem: key => (key === 'tau_ap_open' ? '1' : null), setItem() {}},
      matchMedia: () => ({matches: sheet}),   // under 601px the open panel covers the whole page
      fetchImpl: path => {
        if (path === '/api/models') return response({models: [], default: ''});
        if (path.startsWith('/api/chat')) return response({messages: []});
        throw new Error('Unexpected offline request: ' + path);
      }});
    const box = new Element('div', {id: 'autopilot-float'}); f.document.body.appendChild(box);
    f.renderAutopilot(box, {...apOn}); await flush();
    const first = box.querySelector('.apf-x'), last = box.querySelector('#apf-msg');
    [first, last].forEach((el) => { el.offsetWidth = 40; });   // the rest is folded away or hidden
    let prevented = 0;
    const press = (shiftKey) => box.onkeydown({key: 'Tab', shiftKey, preventDefault: () => prevented++});
    f.document.activeElement = last; press(false);
    assert.equal(first.focused, sheet ? true : undefined);
    f.document.activeElement = first; press(true);
    assert.equal(last.focused, sheet ? true : undefined);
    assert.equal(prevented, sheet ? 2 : 0);
    f.clearTimers();
  }
});

test('the notification list closes when focus leaves it, so Tab out never leaves it open behind the page', async () => {
  const f = bellFrontend(bellNotes());
  await f.viewDashboard(); await flush(); await flush();
  const wrap = f.root.querySelector('.bell-wrap'), trig = wrap.querySelector('.bell-trig'), menu = wrap.querySelector('.bell-menu');
  await trig.onclick({stopPropagation() {}});
  assert.equal(menu.hidden, false); assert.equal(trig.getAttribute('aria-expanded'), 'true');
  // Tab out of the list: it closes, instead of staying open where Esc (bound to the bell) can't reach it.
  wrap.dispatchEvent({type: 'focusout', relatedTarget: f.root.querySelector('.profile-trig')});
  assert.equal(menu.hidden, true); assert.equal(trig.getAttribute('aria-expanded'), 'false');
  // Focus moving within the bell (trigger to an item) leaves it open.
  await trig.onclick({stopPropagation() {}});
  wrap.dispatchEvent({type: 'focusout', relatedTarget: wrap.querySelector('.notif')});
  assert.equal(menu.hidden, false);
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
  const jump = new Element('button', {class: 'jumplatest', hidden: ''}), pulse = new Element('div', {class: 'runpulse'});
  section.querySelector = sel => ({'.log': log, '.jumplatest': jump, '.runpulse': pulse})[sel] || null;
  f.document.createDocumentFragment = () => new LiveList('#fragment');
  return {stream: f.runFeed(section), log, jump};
};
const runEvent = (id, kind, message, data = {}) => ({id, kind, message, data, created_at: '2026-10-17T10:00:00Z'});

test('Tau: a long research log paints its latest rows first and shows the earlier ones on request, in place', () => {
  const f = frontend(), {stream, log, jump} = longFeed(f);
  const events = [runEvent(1, 'hypothesis', 'Early idea', {thesis: 'Old'})];
  for (let i = 2; i <= 120; i++) events.push(runEvent(i, 'step', `Step ${i}`));
  stream.push(events);
  // 120 rows: the newest 60 are on the page, the other 60 wait behind one button at the top.
  assert.equal(log.children.length, 61);
  const fold = log.children[0];
  assert.equal(fold.className, 'log-earlier');
  assert.match(fold.innerHTML, /<button type="button" class="btn small">Show 60 earlier entries<\/button>/);
  assert.match(log.children[1].innerHTML, /Step 61/); assert.match(log.children[60].innerHTML, /Step 120/);
  // A late verdict still lands on its held card, and adds no row of its own.
  log.scrollHeight = 100; log.scrollTop = 0; log.clientHeight = 100;  // at the foot: it sticks
  stream.push([runEvent(121, 'verdict', 'FAILED - Early idea: no edge', {title: 'Early idea', status: 'failed'})]);
  assert.equal(log.children.length, 61);
  // Scrolled up, a new entry raises the "N new" chip as before.
  log.scrollHeight = 5000; log.scrollTop = 0;
  stream.push([runEvent(122, 'step', 'Step 122')]);
  assert.equal(jump.hidden, false); assert.equal(jump.textContent, '1 new ↓');
  // Show earlier puts every held row back above the rest, drops the button and leaves focus on the
  // newest revealed row (the pressed button is gone).
  fold.querySelector('button').onclick();
  assert.equal(log.children.length, 121);
  assert.equal(log.querySelector('.log-earlier'), null);
  assert.match(log.children[0].querySelector('[data-review]').innerHTML, /Verdict/);
  assert.match(log.children[59].innerHTML, /Step 60/); assert.match(log.children[60].innerHTML, /Step 61/);
  assert.equal(log.children[59].focused, true); assert.equal(log.children[59].getAttribute('tabindex'), '-1');
  assert.equal(log.style.scrollBehavior, '');  // the instant jump put the log's smooth scrolling back
  stream.reveal(); assert.equal(log.children.length, 121);  // nothing left to show
});

test('Tau: a short research log is never folded, and a jump to an older idea shows its held card', () => {
  const f = frontend(), {stream, log} = longFeed(f);
  stream.push(Array.from({length: 80}, (_, i) => runEvent(i + 1, 'step', `Step ${i + 1}`)));
  assert.equal(log.children.length, 80); assert.equal(log.querySelector('.log-earlier'), null);
  assert.match(source, /if \(!card\) \{ stream\.reveal\(\); card = find\(\); \}/);
});

test('Tau: run log times build each date format once, and read as toLocaleString did', () => {
  let made = 0;
  const CountingIntl = Object.assign(Object.create(Intl), {DateTimeFormat: function (...a) { made++; return new Intl.DateTimeFormat(...a); }});
  const f = frontend({globals: {Intl: CountingIntl}}), {stream, log} = longFeed(f);
  stream.push(Array.from({length: 10}, (_, i) => runEvent(i + 1, 'step', `Step ${i + 1}`)));
  const after10 = made;
  stream.push(Array.from({length: 50}, (_, i) => runEvent(i + 11, 'step', `Step ${i + 11}`)));
  assert.equal(made, after10);
  const d = new Date('2026-10-17T10:00:00Z');
  const title = d.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short'});
  const time = log.children[0].querySelector('time');
  assert.equal(time.getAttribute('title'), title);
  assert.equal(time.textContent, d.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}));
  assert.match(source, /if \(!Number\.isFinite\(d\.getTime\(\)\)\) return 'Invalid Date';/);
});

test('Tau: the run page poll leaves its unchanged title, figures and next line alone', async () => {
  const run = {id: 9, prompt: 'Lag', status: 'running', market: 'btc15m', created_at: '2026-10-17T10:00:00Z', spent_usd: 1.5, hypotheses_tried: 3};
  let spent = 1.5;
  const f = frontend({fetchImpl: path => path.startsWith('/api/runs/9') ? response({run: {...run, spent_usd: spent}, events: [], strategies: []}) : response({})});
  await f.viewRun(9); await flush();
  const figs = f.root.querySelector('#runfigs'), board = f.root.querySelector('#runboard'), next = f.root.querySelector('#runnext');
  const writes = [figs.writes, board.writes, next.writes];
  for (const tick of f.intervals.values()) tick();
  await flush(); await flush();
  assert.deepEqual([figs.writes, board.writes, next.writes], writes);
  spent = 2;  // a figure that moved repaints
  for (const tick of f.intervals.values()) tick();
  await flush(); await flush();
  assert.equal(figs.writes, writes[0] + 1); assert.match(figs.innerHTML, /\$2\.00/);
});

test('Tau: the pill does not hit-test log rows its scrolling log has clipped out of view', () => {
  const styles = new Map(), plain = {overflowX: 'visible', overflowY: 'visible', position: 'static'};
  const f = frontend({globals: {getComputedStyle: el => styles.get(el) || plain}}), body = f.root.parent;
  f.root.innerHTML = '<main id="main"><ol class="log stream"><li><dl><dd>0.21</dd></dl></li></ol></main>';
  const box = new Element('div', {id: 'autopilot-float', class: 'apf'}); body.appendChild(box);
  box.innerHTML = '<button type="button" class="apf-pill" data-ap="toggle">Autopilot off</button>';
  const rect = (l, t, r, b) => () => ({left: l, top: t, right: r, bottom: b, width: r - l, height: b - t});
  const log = f.root.querySelector('.log'), dd = f.root.querySelector('dd');
  box.querySelector('.apf-pill').getBoundingClientRect = rect(245, 798, 380, 834);   // 390x844 phone
  styles.set(log, {overflowX: 'visible', overflowY: 'auto', position: 'static'});
  log.getBoundingClientRect = rect(16, 200, 374, 700);   // the log's box ends well above the pill
  dd.getBoundingClientRect = rect(260, 800, 330, 820);   // a row scrolled below it, under the pill
  let hits = 0;
  f.document.elementsFromPoint = () => { hits++; return [dd]; };
  f.apYield(); assert.equal(box.classes.has('yield'), false); assert.equal(hits, 0);
  log.getBoundingClientRect = rect(16, 200, 374, 810);   // the log reaches the pill: the row shows there
  f.apYield(); assert.equal(box.classes.has('yield'), true); assert.ok(hits > 0);
  // One pass over the page for every kind of thing it steps aside from.
  assert.match(source, /for \(const el of document\.body\.querySelectorAll\(AP_UNDER_SEL\)\)/);
});

test('Tau: a long run log stays cheap to animate on a phone', () => {
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  // Only the open thought pulses (120 sealed ones repainted the log every frame), under reduced motion too.
  assert.match(css, /\.log\.stream \.lane-think \.node::after \{ background: var\(--stock-raised\); border-color: var\(--ink-2\); \}/);
  assert.match(css, /\.log\.stream \.lane-think:not\(\.sealed\) \.node::after \{ animation: thinkpulse/);
  assert.match(css, / {2}\.log\.stream \.lane-think:not\(\.sealed\) \.node::after \{ animation: none; \}/);
  assert.match(css, /\.log\.stream \{ contain: paint; \}/);
  // The live dot beats with transform and opacity (the compositor's), never a box-shadow.
  assert.match(css, /@keyframes rsibeat \{ 0%, 100% \{ opacity: 1; transform: scale\(1\); \} 50% \{ opacity: 0; transform: scale\(2\.4\); \} \}/);
  assert.match(css, /\.rsiobs-pdot, \.rsiobs-pdot::after \{ animation: none !important; \}/);
  assert.match(css, /\.log > li\.log-earlier \{/);
  // So does the live autopilot pill's dot, on every page (a box-shadow pulse held a phone at ~33%).
  assert.match(css, /@keyframes apf-pulse \{ 0%,100% \{ opacity: 1; transform: scale\(1\); \} 50% \{ opacity: 0; transform: scale\(2\.25\); \} \}/);
  assert.match(css, /prefers-reduced-motion: no-preference\) \{ \.apf\.live \.apf-dot::after \{ animation: apf-pulse/);
  assert.doesNotMatch(css, /@keyframes (rsibeat|apf-pulse) \{[^\n]*box-shadow/);
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
  const main = f.root.querySelector('main').innerHTML;
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
  const real = g.root.querySelector('main').innerHTML;
  assert.match(real, /unseen-data pace, 4 trades would have made \+\$8\.00/);
  assert.doesNotMatch(real, /NaN/);
  assert.ok(g.root.querySelector('#whatif #wk'), 'a strategy with a stake keeps its dial');
  g.clearTimers();
});

test('a Deploy row with no stake says so instead of "$ a trade, up to  open"', async () => {
  const html = await deployBoard([nullStakeDep({id: 1, title: 'Neither'}), nullStakeDep({id: 2, title: 'Cap only', max_positions: 3}),
    nullStakeDep({id: 3, title: 'Stake only', stake: 5}), nullStakeDep({id: 4, title: 'Both', stake: 5, max_positions: 3})]);
  assert.match(html, /Neither<\/a>\s*<div class="sub-fig">Stake not set<\/div>/);
  assert.match(html, /Cap only<\/a>\s*<div class="sub-fig">Stake not set, up to 3 open<\/div>/);
  assert.match(html, /Stake only<\/a>\s*<div class="sub-fig">\$5 a trade<\/div>/);
  assert.match(html, /Both<\/a>\s*<div class="sub-fig">\$5 a trade, up to 3 open<\/div>/);
  assert.doesNotMatch(html, /\$ a trade|up to\s+open|null|NaN/);
});

test('Tau: a research session the autopilot started says so on the list and on its page', async () => {
  const ap = {id: 15, status: 'running', market: 'btc15m', direction: null, by_autopilot: 1, example: false, prompt: 'Order-flow imbalance',
    hypotheses_tried: 1, strategies_passed: 0, spent_usd: 1.41, created_at: '2026-10-26T17:36:00Z'};
  const mine = {id: 9, status: 'succeeded', market: 'btc15m', direction: 'momentum', by_autopilot: 0, example: false, prompt: 'Mine',
    hypotheses_tried: 3, strategies_passed: 1, spent_usd: 0.42, created_at: '2026-10-25T08:00:00Z'};
  const example = {id: 1, status: 'succeeded', market: 'btc15m', direction: 'random_walk', by_autopilot: 0, example: true, prompt: 'Random walk',
    hypotheses_tried: 2, strategies_passed: 0, spent_usd: 0, created_at: '2026-10-17T08:00:00Z'};
  const f = frontend({fetchImpl: path => {
    if (path === '/api/models') return response({models: [], default: ''});
    if (path === '/api/research/context') return response({markets: []});
    if (path === '/api/runs') return response({runs: [ap, mine, example], counts: {research_running: 1, research_queued: 0}, policy: null, totals: {tried: 4, passed: 1}});
    if (path.startsWith('/api/research/scoreboard')) return response({});
    if (path === '/api/autopilot/status') return response({autopilot: true, mode: 'paper'});
    throw new Error('Unexpected offline request: ' + path);
  }});
  await f.viewResearch(); await flush(); await flush();
  const cards = f.root.querySelector('#runs').innerHTML.split('<a class="run-card').slice(1);
  assert.equal(cards.length, 3);
  assert.match(cards[0], /title="The autopilot started this session\.">Autopilot<\/span>/);
  assert.doesNotMatch(cards[1], /Autopilot<\/span>/);
  assert.doesNotMatch(cards[2], /Autopilot<\/span>/); assert.match(cards[2], /Example<\/span>/);
  f.clearTimers();
  for (const [run, said, not] of [[ap, /BTC 15-min · Started by autopilot/, /· Session/],
    [{...ap, direction: 'momentum'}, /· Momentum · Started by autopilot/, /· Session/],
    [mine, /· Momentum/, /Started by autopilot/], [{...ap, by_autopilot: 0}, /· Session/, /Started by autopilot/]]) {
    const g = frontend({fetchImpl: path => { assert.ok(path.startsWith('/api/runs/' + run.id)); return response({run, events: []}); }});
    g.S.me.directions = [{key: 'momentum', label: 'Momentum', brief: ''}];
    await g.viewRun(run.id);
    const head = g.root.querySelector('#runboard').innerHTML.replace(/ /g, ' ');
    assert.match(head, said); assert.doesNotMatch(head, not);
    g.clearTimers();
  }
});

test('Tau: a research start that moved off a cooldown market is the autopilot\'s last move, in customer words', () => {
  const f = frontend();
  const line = 'Started a fresh research session on a market the research specialist picks. Bitcoin 15-minute was researched in the last few hours, so this angle goes to one that isn\'t on cooldown. Follow it on the Research page.';
  assert.equal(f.apMoveText({text: line, at: new Date().toISOString()}), 'Started a fresh research session on a market the research specialist picks');
});

test('Tau: the run page\'s "Ideas tested" heading keeps a gap from the figures, and a strategy that did not pass shows its P&L muted', () => {
  const css = readFileSync(new URL('../app/static/app.css', import.meta.url), 'utf8');
  // On a running session nothing sits between them: the heading sat flush on the figures' bottom rule.
  assert.match(css, /\n\.run-ideas \{ margin: 24px 0; \}/);
  assert.match(css, /\n\.t-strat \.pnl-nopass \{ color: var\(--ink-3\);/);
});

// After every helper it reads (billingPage, the dashboard and autopilot fixtures) is defined.
firstHourCases({name: 'Tau', frontend, billingPage, cardedBilling, dashboard: emptyDashboard, apStatus: apOn});
chatPanelCases({name: 'Tau', frontend, storageFor: m => ({getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))})});
a11yCases({name: 'Tau', frontend, storageFor: m => ({getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}), billingPage, cardedBilling});
creditsCases({name: 'Tau', frontend, billingPage, cardedBilling, dashboard: emptyDashboard, apStatus: apOn});
declinedCardCases({name: 'Tau', frontend, dashboard: emptyDashboard});
