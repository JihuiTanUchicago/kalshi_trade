import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

// Exercise the shipped client with a small DOM/timer harness; no accounts, database or network.
const source = readFileSync(new URL('../app/static/app.js', import.meta.url), 'utf8');
class Element {
  constructor() {
    this.dataset = {}; this.nodes = new Map(); this.children = []; this.hidden = false;
    this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 100; this.attributes = {};
    this.clientWidth = 760; this.isConnected = true; this.style = {};
    this.classes = new Set(); this.writes = 0;
    this.classList = {add: (...xs) => xs.forEach(x => this.classes.add(x)), remove: (...xs) => xs.forEach(x => this.classes.delete(x))};
  }
  set innerHTML(value) { this.html = value; this.writes++; }
  get innerHTML() { return this.html || ''; }
  querySelector(selector) { if (!this.nodes.has(selector)) this.nodes.set(selector, new Element()); return this.nodes.get(selector); }
  querySelectorAll() { return []; }
  addEventListener() {}
  appendChild(child) { this.children.push(child); child.parent = this; }
  insertAdjacentHTML(_position, html) { this.html = (this.html || '') + html; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  setAttribute(key, value) { this.attributes[key] = value; }
  replaceWith(element) { this.replacement = element; }
  focus() {}
  remove() { this.removed = true; }
}
function frontend({fetchImpl, globals = {}} = {}) {
  const root = new Element(), intervals = new Map(), timeouts = new Map(), requests = [];
  let nextId = 0;
  const context = vm.createContext({
    Intl, URLSearchParams,
    document: {getElementById: () => root, addEventListener() {}, createElement: () => new Element()},
    window: {addEventListener() {}, matchMedia: () => ({matches: false})}, addEventListener() {},
    setInterval: callback => { intervals.set(++nextId, callback); return nextId; },
    clearInterval: id => intervals.delete(id),
    setTimeout: callback => { timeouts.set(++nextId, callback); return nextId; },
    clearTimeout: id => timeouts.delete(id),
    fetch: async (path, options) => { requests.push({path, options}); return fetchImpl ? fetchImpl(path, options) : {ok: true, status: 200, json: async () => ({ok: true})}; },
    ...globals,
  });
  const boot = '  setupGlossary();\n  render();';
  assert.equal(source.split(boot).length, 2, 'the harness replaces only automatic boot');
  vm.runInContext(source.replace(boot, 'globalThis.frontend = {S, equityChart, strategyDeploymentHtml, bindStrategyDeployment, runControls, runFeed, researchConversationHtml, RESEARCH_STATE, runRow, feedMd, renderStrategyArtifact, viewStrategy, mountSessionChat};'), context);
  const api = context.frontend;
  api.S.me = {user: {id: 7}, markets: [], directions: [], live_trading_available: true, kalshi_connected: true, kalshi_dev_connected: true};
  return {...api, root, intervals, timeouts, requests};
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
function artifactHost() {
  const host = new Element(), query = host.querySelector.bind(host);
  // Strategy artifacts mount inside a section, with no nested main element.
  host.querySelector = selector => selector === 'main' ? null : query(selector);
  return host;
}

test('the integrated paper renders inside its artifact with escaped evidence and the saved demo curve', () => {
  const f = frontend(), host = artifactHost(), detail = detailStrategy();
  const entry = {devReplay: {dev_curve: [[200, 1], [300, 2]]}};
  f.renderStrategyArtifact(detail, host, {selectedId: detail.id, entries: new Map([[detail.id, entry]])}, entry);
  const output = host.innerHTML;
  for (const label of ['Abstract', 'Mechanism &amp; hypothesis', 'Methodology', 'Results', 'Verdict']) assert.ok(output.includes(label));
  assert.match(output, /class="sheet-doc paper"/);
  assert.match(output, /id="figs"/); assert.match(output, /id="session-revision-review"/);
  assert.match(output, /id="result-context">Saved backtest/);
  assert.match(output, /&lt;b&gt;Counterparty&lt;\/b&gt;/);
  assert.match(output, /<b>Saved<\/b> &lt;img/);
  assert.doesNotMatch(output, /<unsafe>|<img|<script>|\[object Object\]/);
  assert.match(output, /data-strategy-deployment/); assert.match(output, /Type <b>LIVE<\/b>/);
  const chart = host.querySelector('#sheet-results').querySelector('#equity-wrap').innerHTML;
  assert.match(chart, /Kalshi dev \(real\)/); assert.doesNotMatch(chart, /NaN|undefined/);
});

test('cached what-if results stay labelled and do not rewrite the saved paper abstract or verdict', () => {
  const f = frontend(), host = artifactHost(), detail = detailStrategy({status: 'failed', out_of_sample: metrics(-12), experiment: null});
  const result = {in_sample: metrics(50), out_of_sample: metrics(1000), equity: [[100, 0], [300, 1000]], gates: [], passed: true};
  const entry = {scenario: {fee: 0, slip: 0, stake: 5, result, error: '', seq: 1}, devReplay: {dev_curve: [[200, 1], [300, 2]]}};
  f.renderStrategyArtifact(detail, host, {selectedId: detail.id, entries: new Map([[detail.id, entry]])}, entry);
  assert.match(host.innerHTML, /id="result-context">What-if scenario/);
  const abstract = host.innerHTML.match(/<p class="paper-ab-result">(.*?)<\/p>/s)[1];
  assert.match(abstract, /lost \$12/); assert.doesNotMatch(abstract, /1,000|cleared the gate/);
  assert.match(host.innerHTML, /It reached the unseen-data gate and failed it/);
  assert.match(host.innerHTML, /What-if scenarios do not change it/);
  const chart = host.querySelector('#sheet-results').querySelector('#equity-wrap').innerHTML;
  assert.match(chart, /ends at \+\$1,000/); assert.doesNotMatch(chart, /Kalshi dev \(real\)/);
  assert.equal(detail.out_of_sample.pnl, -12);
});

test('a missing ancestor response cannot reopen an old workspace after navigation', async () => {
  const f = frontend({fetchImpl: async path => {
    if (path === '/api/strategies/42') return {ok: true, status: 200, json: async () => ({id: 42, run_id: null, parent_id: 11})};
    assert.equal(path, '/api/strategies/11');
    f.S.gen++;
    return {ok: false, status: 404, json: async () => ({error: 'Not found'})};
  }});
  await f.viewStrategy(42);
  assert.equal(f.requests.length, 2); assert.equal(f.root.writes, 0);
});

test('approval cannot navigate away from the current page when its conversation refresh finishes late', async () => {
  const detail = detailStrategy();
  const proposal = {id: 1, kind: 'revise', status: 'pending', base_strategy_id: detail.id, backtest_status: 'passed', diff: []};
  const state = {draft: '', sending: false, error: '', after: 0, following: true, scrollTop: 0,
    messages: new Map(), proposals: new Map([[1, proposal]]), actions: new Set(), reviewId: 1};
  let reads = 0, approvals = 0, navigations = 0;
  // Scope/transport validation is covered by test_session_chat; this fixture controls response timing.
  const client = {
    read: async () => { if (++reads === 2) f.S.gen++; return {capabilities: {approve: true, reject: true}, has_more: false}; },
    action: async (id, action) => { assert.equal(id, 1); assert.equal(action, 'approve'); approvals++; return {session_key: 'run:9', strategy_id: 99}; },
  };
  const f = frontend({globals: {
    newSessionChatState: () => state, sessionChatApi: () => client,
    mergeSessionChat() {}, sessionRevisionPassed: () => true, sessionTargetChanged: () => false,
    history: {pushState: () => { navigations++; throw new Error('Stale navigation'); }},
  }});
  f.mountSessionChat({key: 'run:9', run_id: 9, candidates: [detail], events: []}, detail);
  await new Promise(resolve => setImmediate(resolve));
  const host = f.root.querySelector('#session-chat-host');
  const button = {disabled: false, dataset: {chatAction: 'approve', proposal: '1'}};
  host.onclick({target: {closest: selector => selector === '[data-chat-action]' ? button : null}});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(approvals, 1); assert.equal(reads, 2);
  assert.equal(navigations, 0); assert.equal(state.error, '');
});

test('responsive equity charts keep the real demo replay anchored without mutating input', () => {
  const f = frontend(), curve = [[100, 50], [200, 60], [300, 70]], demo = [[200, 2], [300, 4]];
  const output = f.equityChart(curve, null, 500, 'Saved evidence', {height: 180, showDates: true, devCurve: demo});
  assert.match(output, /viewBox="0 0 500 180"/);
  assert.match(output, /Kalshi dev \(real\)/);
  assert.doesNotMatch(output, /NaN|undefined/);
  const lines = [...output.matchAll(/<polyline points="([^"]+)"/g)].map(match => match[1].split(' '));
  assert.equal(lines[1][0], lines[0][1], 'the replay starts at the simulated P&L at the same time');
  assert.ok(Number(lines[1][1].split(',')[1]) < Number(lines[1][0].split(',')[1]), 'positive demo P&L slopes upward');
  assert.deepEqual(demo, [[200, 2], [300, 4]]);
});

test('deployment renders separate demo and live readiness with the original typed LIVE gate', () => {
  const f = frontend();
  let output = f.strategyDeploymentHtml(strategy);
  assert.match(output, /data-dep-paper/); assert.match(output, /data-dep-demo/); assert.match(output, /data-dep-live/);
  assert.match(output, /Type <b>LIVE<\/b>/);
  f.S.me.kalshi_dev_connected = false; f.S.me.live_trading_available = false;
  output = f.strategyDeploymentHtml({...strategy, status: 'failed'});
  assert.match(output, /data-dep-demo aria-disabled="true"/);
  assert.match(output, /data-dep-live aria-disabled="true"/);
  assert.match(output, /failed the unseen-data gate/);
  assert.match(output, /What-if scenarios do not change it/);
});

test('demo deployment uses the sandbox mode, while disabled demo never reaches transport', async () => {
  const f = frontend(), host = new Element();
  f.bindStrategyDeployment(host, strategy, 0, () => false);
  await host.querySelector('[data-dep-demo]').onclick();
  assert.equal(f.requests.length, 1);
  assert.deepEqual(JSON.parse(f.requests[0].options.body), {strategy_id: 42, mode: 'demo'});
  host.querySelector('[data-dep-demo]').setAttribute('aria-disabled', 'true');
  await host.querySelector('[data-dep-demo]').onclick();
  assert.equal(f.requests.length, 1);
});

test('live deployment passes the typed phrase to the server instead of substituting confirmation', async () => {
  const f = frontend(), host = new Element();
  f.bindStrategyDeployment(host, strategy, 0, () => false);
  const form = host.querySelector('[data-live-confirm]'); form.confirm = {value: '  LIVE  '};
  await form.onsubmit({preventDefault() {}});
  // The submit handler starts busy asynchronously; drain its fetch/json microtasks.
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(JSON.parse(f.requests[0].options.body), {strategy_id: 42, mode: 'live', confirm: 'LIVE'});
});

test('research controls retain pause and resume and preserve armed cancellation across polling', async () => {
  const f = frontend(), host = new Element(); let reloads = 0;
  const reload = async () => reloads++;
  f.runControls(host, 9, 'running', reload);
  await host.querySelector('#pause').onclick({currentTarget: host.querySelector('#pause')});
  assert.equal(f.requests[0].path, '/api/runs/9/pause');
  f.runControls(host, 9, 'paused', reload);
  await host.querySelector('#resume').onclick({currentTarget: host.querySelector('#resume')});
  assert.equal(f.requests[1].path, '/api/runs/9/resume');
  const cancel = host.querySelector('#cancel'); cancel.onclick();
  const writes = host.writes;
  f.runControls(host, 9, 'paused', reload);
  assert.equal(host.writes, writes);
  await cancel.onclick();
  assert.equal(f.requests[2].path, '/api/runs/9/cancel');
  assert.equal(reloads, 3);
});

test('streaming thoughts and challenger/verdict update one hypothesis card and dispose every timer', () => {
  const f = frontend(), section = new Element(), stream = f.runFeed(section), log = section.querySelector('.log');
  const event = (id, kind, message, data = {}) => ({id, kind, message, data, created_at: '2026-10-17T10:00:00Z'});
  stream.push([event(1, 'thinking', 'A **test'), event(2, 'thinking', 'able** edge.')]);
  assert.equal(log.children.length, 1);
  assert.match(log.children[0].querySelector('[data-body]').innerHTML, /<b>testable<\/b>/);
  stream.push([
    event(3, 'hypothesis', 'Momentum', {thesis: 'Late flow', spec: {code: 'return []'}}),
    event(4, 'challenger', 'Challenger accept – Momentum: sound mechanism', {title: 'Momentum', decision: 'accept'}),
    event(5, 'verdict', 'PASSED – Momentum: evidence', {title: 'Momentum', status: 'passed', strategy_id: 42, stats: {n_trades: 80, p_value: .01}}),
  ]);
  assert.equal(log.children.length, 2);
  assert.equal(log.children[0].classes.has('sealed'), true);
  const hypothesis = log.children[1];
  assert.match(hypothesis.innerHTML, /research sandbox only/);
  assert.match(hypothesis.querySelector('[data-review]').innerHTML, /sound mechanism/);
  assert.match(hypothesis.querySelector('[data-stamp]').innerHTML, /\/strategies\/42/);
  stream.state('paused'); assert.match(section.querySelector('.runpulse').innerHTML, /resume/);
  stream.dispose(); assert.equal(f.intervals.size, 0); assert.equal(f.S.timers.length, 0);
});

test('session workspace contains the streaming mount and paused runs remain visible as paused', () => {
  const f = frontend(), run = {id: 9, prompt: '<script>unsafe</script>', status: 'paused', created_at: '2026-10-17T10:00:00Z'};
  const output = f.researchConversationHtml({run, candidates: []});
  assert.match(output, /data-runfeed/); assert.match(output, /role="log"/);
  assert.doesNotMatch(output, /<script>/); assert.match(output, /&lt;script&gt;/);
  assert.equal(f.RESEARCH_STATE.paused, 'Research paused');
  assert.match(f.runRow({...run, market: 'btc15m'}), /Paused/);
  assert.doesNotMatch(f.runRow({...run, market: 'btc15m'}), />Failed</);
});

test('feed markdown escapes model HTML and rejects non-http links', () => {
  const f = frontend(), output = f.feedMd('<img src=x onerror=alert(1)>\n[unsafe](javascript:alert(1))\n**complete** and **pending');
  assert.doesNotMatch(output, /<img|href="javascript:/);
  assert.match(output, /<b>complete<\/b>/); assert.match(output, /\*\*pending/);
});
