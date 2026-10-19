import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/static/app.js', import.meta.url), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

// Offline DOM fixture: real UI functions and the authenticated API wrapper run,
// while timers, HTTP, cards, brokerage sessions and account records stay synthetic.
class Element {
  constructor(tag = 'div', attributes = {}) {
    this.tag = tag; this.attributes = attributes; this.dataset = {}; this.children = [];
    this.style = {}; this.listeners = new Map(); this.writes = 0; this.value = attributes.value || '';
    this.checked = 'checked' in attributes; this.disabled = 'disabled' in attributes;
    this.scrollTop = 0; this.scrollHeight = 0; this.clientHeight = 100;
    this.classes = new Set((attributes.class || '').split(/\s+/));
    for (const [key, value] of Object.entries(attributes)) if (key.startsWith('data-')) this.dataset[key.slice(5)] = value;
    this.classList = {add: (...xs) => xs.forEach(x => this.classes.add(x)), remove: (...xs) => xs.forEach(x => this.classes.delete(x)),
      toggle: (x, on = !this.classes.has(x)) => on ? this.classes.add(x) : this.classes.delete(x)};
  }
  get isConnected() { return !this.removed && (!this.parent || this.parent.isConnected); }
  get className() { return [...this.classes].join(' '); }
  set className(value) { this.classes = new Set(value.split(/\s+/)); }
  get innerHTML() { return this.html || ''; }
  set innerHTML(value) {
    this.html = value; this.writes++; this.children.forEach(child => { child.removed = true; }); this.children = [];
    const stack = [{element: this, start: 0}], voids = new Set(['input', 'br', 'hr', 'img', 'meta', 'link']);
    for (const match of value.matchAll(/<\/?([a-z][\w-]*)\b([^>]*)>/gi)) {
      const tag = match[1].toLowerCase();
      if (match[0].startsWith('</')) {
        if (stack.length > 1 && stack.at(-1).element.tag === tag) { const closed = stack.pop(); closed.element.html = value.slice(closed.start, match.index); }
      } else {
        const attributes = {};
        for (const [, key, quoted, single, bare] of match[2].matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) attributes[key] = quoted ?? single ?? bare ?? '';
        const child = new Element(tag, attributes); stack.at(-1).element.appendChild(child);
        if (!voids.has(tag) && !match[0].endsWith('/>')) stack.push({element: child, start: match.index + match[0].length});
      }
    }
    if (this.tag === 'select') this.value = (this.options.find(option => 'selected' in option.attributes) || this.options[0])?.attributes.value || '';
  }
  get options() { return this.querySelectorAll('option'); }
  set textContent(value) { this.text = String(value); }
  get textContent() { return this.text ?? this.innerHTML.replace(/<[^>]*>/g, ''); }
  matches(selector) {
    if (selector.startsWith('#')) return this.attributes.id === selector.slice(1);
    if (selector.startsWith('.')) return this.classes.has(selector.slice(1));
    if (selector.startsWith('[')) { const key = selector.slice(1, -1); return key in this.attributes; }
    return this.tag === selector;
  }
  querySelectorAll(selector) {
    const found = [], visit = element => element.children.forEach(child => { if (child.matches(selector)) found.push(child); visit(child); });
    visit(this); return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  appendChild(child) { this.children.push(child); child.parent = this; }
  addEventListener(key, callback) { this.listeners.set(key, callback); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  remove() { this.removed = true; }
}
function frontend(transport = () => { throw new Error('Unexpected synthetic request'); }) {
  const root = new Element('div', {id: 'app'}), body = new Element('body'), box = new Element('div', {id: 'autopilot-float'});
  body.appendChild(root); body.appendChild(box);
  const requests = [], alerts = [], intervals = new Map(); let next = 0;
  const document = {body, activeElement: null, getElementById: id => body.querySelector('#' + id), createElement: tag => new Element(tag), addEventListener() {}};
  const context = vm.createContext({Intl, URL, URLSearchParams, document,
    window: {addEventListener() {}, matchMedia: () => ({matches: false})}, addEventListener() {},
    location: {pathname: '/funds', search: '', origin: 'https://offline.invalid'}, history: {},
    localStorage: {getItem: key => key === 'tau_ap_open' ? '1' : null, setItem() {}},
    setInterval: callback => { intervals.set(++next, callback); return next; }, clearInterval: id => intervals.delete(id), setTimeout() {}, clearTimeout() {},
    fetch: async (path, options) => { requests.push({path, options}); if (path.startsWith('/api/chat?')) return response({messages: [], agent_busy: false}); return transport(path, options); },
    testAlert: value => alerts.push(value), testShell: (_active, board, main) => { root.innerHTML = board + '<main>' + main + '</main>'; },
  });
  const boot = '  setupGlossary();\n  render();';
  assert.equal(source.split(boot).length, 2);
  vm.runInContext(source.replace(boot, 'shell = globalThis.testShell; alert0 = globalThis.testAlert; globalThis.ui = {S, routes, apBuildShell, apUpdate, apFeedLi, apLiveBlock, viewBilling, viewFunds};'), context);
  context.ui.S.me = {user: {id: 7, name: 'Synthetic user'}};
  context.ui.S.ap = {mode: 'paper', model: 'sonnet', autopilot: true};
  return {...context.ui, document, root, box, requests, alerts, intervals};
}
const catalog = {models: [{key: 'opus', label: 'Opus'}, {key: 'sonnet', label: 'Sonnet'}], default: 'opus'};
const posts = f => f.requests.filter(row => row.options.method === 'POST');
const status = changes => ({mode: 'paper', autopilot: true, live_enabled: false, kalshi_connected: false,
  paper_running: 1, live_running: 0, demo_running: 0, today_live_pnl: 0, loss_headroom: 20, daily_loss_limit: 20, model: 'sonnet', ...changes});

test('autopilot model picker loads the saved preference, falls back to the catalog default and escapes labels', async () => {
  for (const preferred of ['sonnet', null]) {
    const f = frontend(path => { assert.equal(path, '/api/models'); return response({...catalog, models: [...catalog.models, {key: '<bad>', label: '<img src=x onerror=alert(1)>'}]}); });
    f.S.ap.model = preferred; f.apBuildShell(f.box); await flush();
    const select = f.box.querySelector('#apf-model');
    assert.equal(select.value, preferred || 'opus');
    assert.equal(select.options.length, 3);
    assert.match(select.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
    assert.doesNotMatch(select.innerHTML, /<img/);
    assert.equal(posts(f).length, 0);
  }
});

test('changing the model posts only the preference and blocks repeated changes while saving', async () => {
  const pending = deferred();
  const f = frontend(path => path === '/api/models' ? response(catalog) : pending.promise);
  f.apBuildShell(f.box); await flush();
  const select = f.box.querySelector('#apf-model'); select.value = 'opus';
  const save = select.onchange(); await select.onchange();
  assert.equal(select.disabled, true);
  assert.equal(posts(f).length, 1);
  assert.equal(posts(f)[0].path, '/api/autopilot/model');
  assert.deepEqual(JSON.parse(posts(f)[0].options.body), {model: 'opus'});
  assert.equal(posts(f)[0].options.credentials, 'same-origin');
  assert.equal(posts(f)[0].options.headers['X-Recursive'], '1');
  assert.equal(f.S.ap.model, 'sonnet');
  pending.resolve(response({model: 'opus'})); await save;
  assert.equal(f.S.ap.model, 'opus'); assert.equal(select.disabled, false);
});

test('a failed model save restores the existing preference without changing trading controls', async () => {
  const f = frontend(path => path === '/api/models' ? response(catalog) : response({error: 'Synthetic model preference rejection'}, 400));
  f.apBuildShell(f.box); await flush();
  const select = f.box.querySelector('#apf-model'); select.value = 'opus'; await select.onchange();
  assert.equal(f.S.ap.model, 'sonnet'); assert.equal(select.value, 'sonnet'); assert.equal(select.disabled, false);
  assert.deepEqual(f.alerts, ['Synthetic model preference rejection']);
  assert.deepEqual(posts(f).map(row => row.path), ['/api/autopilot/model']);
  assert.equal(f.apLiveBlock(status()), 'Live trading is off on this server. ');
});

test('catalog failure and a response after shell replacement cannot populate a stale picker', async () => {
  const failed = frontend(() => response({error: 'Synthetic catalog failure'}, 503));
  failed.apBuildShell(failed.box); await flush();
  assert.equal(failed.box.querySelector('#apf-model').options.length, 0); assert.equal(posts(failed).length, 0);
  const pending = deferred(), f = frontend(() => pending.promise);
  f.apBuildShell(f.box); const old = f.box.querySelector('#apf-model'), writes = old.writes;
  f.box.innerHTML = '<button>Collapsed</button>';
  pending.resolve(response(catalog)); await flush();
  assert.equal(old.writes, writes); assert.equal(old.onchange, undefined);
});

test('a late preference response cannot rewrite a replaced or disconnected shell', async () => {
  for (const detach of [false, true]) {
    const pending = deferred(), f = frontend(path => path === '/api/models' ? response(catalog) : pending.promise);
    f.apBuildShell(f.box); await flush();
    const select = f.box.querySelector('#apf-model'); select.value = 'opus'; const save = select.onchange();
    if (detach) f.box.remove(); else f.box.innerHTML = '<button>Collapsed</button>';
    pending.resolve(response({model: 'opus'})); await save;
    assert.equal(f.S.ap.model, 'sonnet');
  }
});

test('status updates show last review and synchronize the model only when it is not being edited', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  const select = f.box.querySelector('#apf-model');
  f.apUpdate(f.box, status({model: 'opus', last_review_at: new Date(Date.now() - 5 * 60000).toISOString()}));
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /Last reviewed/);
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /5m ago/);
  assert.equal(select.value, 'opus');
  f.document.activeElement = select;
  f.apUpdate(f.box, status({model: 'sonnet'})); assert.equal(select.value, 'opus');
  f.document.activeElement = null; select.disabled = true;
  f.apUpdate(f.box, status({model: 'sonnet'})); assert.equal(select.value, 'opus');
  select.disabled = false; f.apUpdate(f.box, status({model: 'sonnet'})); assert.equal(select.value, 'sonnet');
  assert.doesNotMatch(f.box.querySelector('#apf-stats').innerHTML, /Last reviewed/);
  assert.match(f.box.querySelector('#apf-gates').textContent, /Live trading is off/);
  assert.equal(posts(f).length, 0);
});

test('billing continues to render the server-provided welcome credit instead of a UI constant', async () => {
  for (const free_bonus of [20, 37]) {
    const f = frontend(path => { assert.equal(path, '/api/billing'); return response({configured: false, cards: [], ledger: [], balance: free_bonus,
      free_bonus, spent: 0, topup_fee_pct: 3, default_pm: null}); });
    await f.viewBilling();
    const figures = f.root.querySelector('#bfigs').innerHTML;
    assert.match(figures, /Welcome credit/); assert.ok(figures.includes('$' + free_bonus.toFixed(2)));
    assert.match(f.root.querySelector('main').innerHTML, /Payments aren’t enabled/);
    assert.equal(posts(f).length, 0);
  }
});

test('current paper proposal approval semantics and broker callback route survive reconciliation', () => {
  const f = frontend();
  assert.equal(f.routes.find(([pattern]) => pattern.test('/settings/account'))[1], f.viewFunds);
  const paper = f.apFeedLi({role: 'system', content: 'Synthetic paper order', created_at: '2026-10-19T00:00:00Z', proposal_id: 7, proposal_status: 'applied', proposal_kind: 'alpaca_paper'});
  assert.match(paper.innerHTML, /Alpaca paper order/); assert.match(paper.innerHTML, />Approved</);
  assert.doesNotMatch(paper.innerHTML, />Applied<|>Filled</);
  assert.match(source, /TauBrokerConnections\.mount\(brokerHost, \{api, isCurrent: \(\) => gen === S\.gen\}\)/);
  assert.match(source, /api\('\/api\/waitlist'/);
});
