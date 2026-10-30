import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import {bundleSource, exposing} from './bundle_source.mjs';

const bundle = process.env.TAU_TEST_THEME === 'meridian' ? 'app.meridian.js' : 'app.js';
// What the checks read from the bundle and its page files (bundle_source.mjs).
const EXPOSE = ['S', 'routes', 'apAction', 'apBuildShell', 'apUpdate', 'apFeedLi', 'apLiveBlock', 'notice', 'viewBilling', 'viewFunds'];
const source = bundleSource(bundle, {expose: EXPOSE, target: 'ui'});
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
  closest(selector) { return this.matches(selector) ? this : this.parent ? this.parent.closest(selector) : null; }
  get parentElement() { return this.parent || null; }
  appendChild(child) { this.children.push(child); child.parent = this; }
  addEventListener(key, callback) { this.listeners.set(key, callback); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  remove() { this.removed = true; }
}
let chatReply = {messages: [], agent_busy: false};  // what the panel's chat poll reads
function frontend(transport = () => { throw new Error('Unexpected synthetic request'); }) {
  const root = new Element('div', {id: 'app'}), body = new Element('body'), box = new Element('div', {id: 'autopilot-float'});
  body.appendChild(root); body.appendChild(box);
  const requests = [], alerts = [], intervals = new Map(); let next = 0;
  const document = {body, activeElement: null, getElementById: id => body.querySelector('#' + id), createElement: tag => new Element(tag), addEventListener() {}};
  const context = vm.createContext({Intl, URL, URLSearchParams, AbortController, document,
    window: {addEventListener() {}, matchMedia: () => ({matches: false})}, addEventListener() {},
    location: {pathname: '/funds', search: '', origin: 'https://offline.invalid'}, history: {},
    localStorage: {getItem: key => key === 'tau_ap_open' ? '1' : null, setItem() {}},
    setInterval: callback => { intervals.set(++next, callback); return next; }, clearInterval: id => intervals.delete(id), setTimeout() {}, clearTimeout() {},
    fetch: async (path, options) => { requests.push({path, options}); if (path.startsWith('/api/chat?')) return response(chatReply); return transport(path, options); },
    testAlert: value => alerts.push(value), testShell: (_active, board, main) => { root.innerHTML = board + '<div id="main">' + main + '</div>'; },
  });
  const boot = '  setupGlossary();\n  render();';
  assert.equal(source.split(boot).length, 2);
  vm.runInContext(source.replace(boot, 'shell = globalThis.testShell; alert0 = globalThis.testAlert; globalThis.ui = ' + exposing(EXPOSE) + ';'), context);
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
  // Said in the panel, beside the control (alert0 put it on the page under the panel).
  assert.deepEqual(f.alerts, []); assert.match(f.box.querySelector('#apf-flash').innerHTML, /error-text">Synthetic model preference rejection/);
  assert.deepEqual(posts(f).map(row => row.path), ['/api/autopilot/model']);
  assert.equal(f.apLiveBlock(status()), 'Live trading isn’t open yet. ');
});

test('live autopilot with autopilot off says plainly that autopilot (paper) comes first, and why', () => {
  const f = frontend(() => response({}));
  const why = f.apLiveBlock(status({autopilot: false, live_enabled: true, kalshi_connected: true}));
  assert.match(why, /^Live autopilot can only be turned on after autopilot \(paper\) is on\. /);
  assert.match(why, /proven itself on paper, and autopilot is what runs it there\. $/);
  assert.doesNotMatch(why, /builds on it/);
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

test('a paper-only panel shows paper realized today and no live loss budget; live in play brings both back', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  f.apUpdate(f.box, status({today_paper_pnl: 1.25, today_live_pnl: 0}));
  let html = f.box.querySelector('#apf-stats').innerHTML;
  assert.match(html, /<dt>Paper realized today \(UTC\)<\/dt>/); assert.match(html, /\+\$1\.25/);
  assert.doesNotMatch(html, /Live realized today|Loss budget/);
  // While live trading is closed nothing live trades, so the live loss budget isn't shown; a live position
  // still settling counts in Live realized today.
  f.S.me.live_trading_available = false;
  f.apUpdate(f.box, status({today_paper_pnl: 1.25, today_live_pnl: -3, loss_headroom: 17, daily_loss_limit: 20, live_running: 1}));
  html = f.box.querySelector('#apf-stats').innerHTML;
  assert.match(html, /<dt>Live realized today \(UTC\)<\/dt>/); assert.doesNotMatch(html, /Loss budget|Live also stops/);
  f.S.me.live_trading_available = true;
  for (const live of [{live_running: 1}, {autopilot_live: true}]) {
    f.apUpdate(f.box, status({today_paper_pnl: 1.25, today_live_pnl: -3, loss_headroom: 17, daily_loss_limit: 20, ...live}));
    html = f.box.querySelector('#apf-stats').innerHTML;
    // The day figure is booked P&L (closed trades), and so is the budget; the account-equity stop
    // (open positions included) is a separate check, so the panel says both.
    assert.match(html, /<dt>Live realized today \(UTC\)<\/dt>/); assert.match(html, /Loss budget left/); assert.match(html, /since 00:00 UTC/);
    assert.match(html, /Counts live losses booked since 00:00 UTC\. Live also stops if your Kalshi account falls \$20\.00 in a day, open positions included\./);
    assert.doesNotMatch(html, /Paper realized today|P&amp;L today/);
  }
});

test('one flip of the panel switch turns paper autopilot on', async () => {
  const f = frontend(path => path === '/api/models' ? response(catalog) : path === '/api/settings' ? response({ok: true}) : response(status({autopilot: true})));
  f.apBuildShell(f.box); await flush();
  const sw = f.box.querySelector('#apf-apswitch'); sw.checked = true; await sw.onchange();
  const settings = posts(f).filter(row => row.path === '/api/settings');
  assert.equal(settings.length, 1); assert.deepEqual(JSON.parse(settings[0].options.body), {autopilot: true});
  assert.equal(f.S.me.user.autopilot, true); assert.equal(sw.checked, true);
  assert.doesNotMatch(f.box.querySelector('#apf-ap-copy').innerHTML, /Flip again/);
});

test('the panel warns before credits run out, and says why when autopilot is paused for billing', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  const gates = f.box.querySelector('#apf-gates');
  f.apUpdate(f.box, status({credits_low_days: 1.6}));
  assert.match(gates.innerHTML, /Research pauses in about 2 days at this week’s pace, when credits fall under/); assert.match(gates.innerHTML, /href="\/billing"/);
  assert.equal(gates.classes.has('warn'), true);
  f.apUpdate(f.box, status({credits_low_days: 0.3}));
  assert.match(gates.innerHTML, /within a day/);
  f.apUpdate(f.box, status({billing_blocked: true, billing_reason: 'credits'}));
  assert.match(gates.innerHTML, /paused/); assert.match(gates.innerHTML, /Add credits|add credits/);
  // Paused while the auto-reload card is declined: the card is the step, then credits.
  f.apUpdate(f.box, status({billing_blocked: true, billing_reason: 'credits', reload_failed: 'It couldn’t add $25.00 in credits.'}));
  assert.match(gates.innerHTML, /Autopilot is paused: auto-reload couldn’t charge your card\. <a href="\/billing">Update your card and add credits on Billing<\/a>/);
  assert.equal(gates.classes.has('warn'), true);
  f.apUpdate(f.box, status({}));
  // Back to the live-readiness line (set as text) once billing is fine.
  assert.doesNotMatch(gates.textContent, /Research pauses|paused/); assert.equal(gates.classes.has('warn'), false);
});

test('the Research row only shows when there is no story to say it', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  const research = {active: [], tested_7d: 4, passed_7d: 1, cost_7d: 0};
  f.apUpdate(f.box, status({research, story: ['This week it tested 4 ideas and 1 passed.']}));
  assert.doesNotMatch(f.box.querySelector('#apf-stats').innerHTML, /<dt>Research<\/dt>/);
  f.apUpdate(f.box, status({research, story: []}));
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /<dt>Research<\/dt>/);
});

test('status updates show last review and synchronize the model only when it is not being edited', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  const select = f.box.querySelector('#apf-model');
  f.apUpdate(f.box, status({model: 'opus', last_review_at: new Date(Date.now() - 5 * 60000).toISOString()}));
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /Last check-in/);
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /5m ago/);
  assert.equal(select.value, 'opus');
  f.document.activeElement = select;
  f.apUpdate(f.box, status({model: 'sonnet'})); assert.equal(select.value, 'opus');
  f.document.activeElement = null; select.disabled = true;
  f.apUpdate(f.box, status({model: 'sonnet'})); assert.equal(select.value, 'opus');
  select.disabled = false; f.apUpdate(f.box, status({model: 'sonnet'})); assert.equal(select.value, 'sonnet');
  assert.doesNotMatch(f.box.querySelector('#apf-stats').innerHTML, /Last check-in/);
  assert.match(f.box.querySelector('#apf-gates').textContent, /Live trading isn’t open yet\./);
  assert.equal(posts(f).length, 0);
});

test('a queued or running review reads as in progress, not as a review that already ran', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  const at = new Date().toISOString();
  f.apUpdate(f.box, status({reviewing: true, last_review_at: at}));
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /<dt>Last check-in<\/dt><dd>Reviewing now<\/dd>/);
  assert.doesNotMatch(f.box.querySelector('#apf-stats').innerHTML, /Last check-in<\/dt><dd>just now/);
  f.apUpdate(f.box, status({reviewing: false, last_review_at: at}));
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /<dt>Last check-in<\/dt><dd>just now<\/dd>/);
  assert.doesNotMatch(source, /Working the operation/);
});

// "The next review puts it on paper" said nothing of when. The next check-in has no time to promise (the worker's
// heartbeat skips, queues and spaces out), so the panel gives the status's usual cadence and the last one's age.
test('the panel says how often the autopilot checks in, beside its last check-in and a strategy waiting for one', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  const ago = (m) => new Date(Date.now() - m * 60000).toISOString();
  const line = 'Nothing is on paper yet: Lean in cleared every check, and the next review puts it on paper.';
  const idle = {code: 'to_deploy', line};
  f.apUpdate(f.box, status({checkin_every_min: 10, last_review_at: ago(8), idle}));
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /<dt>Last check-in<\/dt><dd>8m ago <small class="apf-note">usually every 10 min<\/small><\/dd>/);
  assert.match(f.box.querySelector('#apf-story').innerHTML,
    /<p class="apf-idle">Nothing is on paper yet: Lean in cleared every check, and the next review puts it on paper\. <span class="ap-when">Check-ins: usually every 10 min; last one 8 min ago\.<\/span><\/p>/);
  // Late: it says how late, and never "any moment now".
  f.apUpdate(f.box, status({checkin_every_min: 30, last_review_at: ago(185), idle}));
  assert.match(f.box.querySelector('#apf-story').innerHTML, /Check-ins: usually every 30 min; last one 3 hours ago\./);
  // One under way, or one waiting for a worker, says that instead of a cadence.
  f.apUpdate(f.box, status({checkin_every_min: 10, reviewing: true, last_review_at: ago(0), idle}));
  assert.match(f.box.querySelector('#apf-story').innerHTML, /Check-ins: one is under way now\./);
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /<dt>Last check-in<\/dt><dd>Reviewing now<\/dd>/);
  f.apUpdate(f.box, status({checkin_every_min: 10, review_wait: {state: 'queued', seconds: 400, overdue: true}, last_review_at: ago(7), idle}));
  assert.match(f.box.querySelector('#apf-story').innerHTML, /Check-ins: one is waiting for a free worker\./);
  // No cadence (an older server, autopilot off or paused by billing): nothing is said, and the figure is as before.
  f.apUpdate(f.box, status({checkin_every_min: null, last_review_at: ago(8), idle}));
  assert.match(f.box.querySelector('#apf-stats').innerHTML, /<dt>Last check-in<\/dt><dd>8m ago<\/dd>/);
  assert.doesNotMatch(f.box.querySelector('#apf-story').innerHTML, /Check-ins|usually/);
  // Another idle line has no check-in to wait for, so it carries none.
  f.apUpdate(f.box, status({checkin_every_min: 10, last_review_at: ago(8), idle: {code: 'researching', line: 'Nothing is on paper yet.'}}));
  assert.doesNotMatch(f.box.querySelector('#apf-story').innerHTML, /Check-ins/);
});

// Seen in Meridian right after turning autopilot off: "Last check-in 37m ago" stayed under "Off: it only suggests
// ideas". Check-ins are the autopilot's own, so the figure follows the switch: gone while a flip to off saves, gone
// once it lands (before the next status read), and gone in an off status read; back when it is on again.
test('the check-in figure follows the autopilot switch, live', async () => {
  const saving = deferred(), reading = deferred(), at = new Date(Date.now() - 37 * 60000).toISOString();
  const f = frontend(path => path === '/api/models' ? response(catalog) : path === '/api/settings' ? saving.promise : reading.promise);
  f.S.me.user.autopilot = true;
  f.apBuildShell(f.box); await flush();
  const stats = () => f.box.querySelector('#apf-stats').innerHTML;
  f.S.ap = status({last_review_at: at}); f.apUpdate(f.box, f.S.ap);
  assert.match(stats(), /<dt>Last check-in<\/dt><dd>37m ago<\/dd>/);
  const sw = f.box.querySelector('#apf-apswitch'); sw.checked = false;
  const flip = sw.onchange(); await flush();
  // A status read that left before the write lands still says on: the switch, flipped off, wins.
  f.apUpdate(f.box, status({last_review_at: at}));
  assert.doesNotMatch(stats(), /check-in/i);
  saving.resolve(response({ok: true})); await flip; await flush();
  assert.doesNotMatch(stats(), /check-in/i, 'repainted as the switch lands, not on the next status read');
  assert.match(f.box.querySelector('#apf-ap-copy').innerHTML, /Off: it only suggests ideas/);
  for (const off of [{last_review_at: at}, {reviewing: true, last_review_at: at}, {review_wait: {state: 'queued', seconds: 900}}]) {
    f.apUpdate(f.box, status({autopilot: false, mode: 'off', ...off}));
    assert.doesNotMatch(stats(), /check-in/i);
  }
  f.apUpdate(f.box, status({autopilot: true, last_review_at: at}));
  assert.match(stats(), /<dt>Last check-in<\/dt><dd>37m ago<\/dd>/);
  reading.resolve(response(status({autopilot: false, mode: 'off', last_review_at: at})));
});

test('the autopilot pulse and Review figure say how long a run has waited once past the reaper limit', async () => {
  try {
    chatReply = {messages: [], agent_busy: true, agent_wait: null};
    let f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
    assert.match(f.box.querySelector('#apf-pulse').innerHTML, /Working on its next move/);
    chatReply = {messages: [], agent_busy: true, agent_wait: {state: 'queued', seconds: 420, overdue: true}};
    f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
    const pulse = f.box.querySelector('#apf-pulse').innerHTML;
    assert.match(pulse, /Waiting for a free worker for 7 min, longer than usual/);
    assert.doesNotMatch(pulse, /Working on its next move|class="working"/);
    chatReply = {messages: [], agent_busy: true, agent_wait: {state: 'silent', seconds: 5340, overdue: true}};
    f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
    assert.match(f.box.querySelector('#apf-pulse').innerHTML, /No word from it for 89 min, longer than usual/);
    const at = new Date().toISOString();
    f.apUpdate(f.box, status({reviewing: false, review_wait: {state: 'queued', seconds: 300, overdue: true}, last_review_at: at}));
    assert.match(f.box.querySelector('#apf-stats').innerHTML, /<dt>Check-in<\/dt><dd>Waiting 5 min<\/dd>/);
    f.apUpdate(f.box, status({reviewing: false, review_wait: {state: 'silent', seconds: 7200, overdue: true}, last_review_at: at}));
    assert.match(f.box.querySelector('#apf-stats').innerHTML, /<dt>Check-in<\/dt><dd>Silent 2 hr<\/dd>/);
    assert.doesNotMatch(f.box.querySelector('#apf-stats').innerHTML, /In progress/);
  } finally { chatReply = {messages: [], agent_busy: false}; }
});

test('with live trading off on the server, the panel says so in one line instead of a dead button', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  const controls = () => f.box.querySelector('#apf-controls').innerHTML, gates = () => f.box.querySelector('#apf-gates').textContent;
  f.apUpdate(f.box, status({live_enabled: false}));
  assert.doesNotMatch(controls(), /livearm|Enable live autopilot/);
  assert.equal(gates(), 'Live trading isn’t open yet. ');
  assert.match(controls(), /See what’s trading/);
  // Live available: the button is exactly as before, greyed until a Kalshi key is connected.
  f.apUpdate(f.box, status({live_enabled: true, kalshi_connected: false}));
  assert.match(controls(), /<button class="btn sm" data-ap="livearm" aria-disabled="true">Enable live autopilot<\/button>/);
  assert.match(gates(), /Connect your Kalshi key on the Funds page first/);
  // "the Funds page" is a link to Funds' Connect Kalshi: it was plain text, with nothing to press.
  assert.match(f.box.querySelector('#apf-gates').innerHTML,
    /^Connect your Kalshi key on <a href="\/funds#connect-kalshi">the Funds page<\/a> first\. $/);
  assert.equal(f.apLiveBlock(status({live_enabled: true, kalshi_connected: false})), 'Connect your Kalshi key on the Funds page first. ');
  f.apUpdate(f.box, status({live_enabled: true, kalshi_connected: true}));
  assert.match(controls(), /<button class="btn sm" data-ap="livearm" >Enable live autopilot<\/button>/);
  // Live already on (or running) keeps its off switch and Kill, whatever the flag says now.
  f.apUpdate(f.box, status({live_enabled: false, autopilot_live: true}));
  assert.match(controls(), /data-ap="livetoggle"/); assert.match(controls(), /data-ap="kill"/);
  assert.equal(posts(f).length, 0);
});

test('a refused live press, and the server refusing it, link "the Funds page" to Connect Kalshi in the words they flash', async () => {
  const refusal = 'Connect your Kalshi key on the Funds page first.';
  const f = frontend(path => path === '/api/models' ? response(catalog) : path === '/api/autopilot/live' ? response({error: refusal}, 400) : response({}));
  f.apBuildShell(f.box); await flush();
  const flashed = () => f.box.querySelector('#apf-flash').innerHTML;
  const linked = '<p class="error-text">Connect your Kalshi key on <a href="/funds#connect-kalshi">the Funds page</a> first.</p>';
  // The gate unmet: the press opens no confirm and says why, the words that were plain text now a link.
  f.S.ap = status({live_enabled: true, kalshi_connected: false}); f.apUpdate(f.box, f.S.ap);
  await f.apAction(f.box, 'livearm');
  assert.equal(flashed(), linked);
  assert.equal(posts(f).length, 0);
  // The page thought the key was there; the server said it isn't (the key went in another tab).
  f.S.ap = status({live_enabled: true, kalshi_connected: true}); f.apUpdate(f.box, f.S.ap);
  const form = f.box.querySelector('#apf-confirm'); form.confirm = {value: 'LIVE AUTOPILOT'};
  form.onsubmit({preventDefault() {}}); await flush(); await flush();
  assert.equal(posts(f).length, 1); assert.equal(posts(f)[0].path, '/api/autopilot/live');
  assert.equal(flashed(), linked);
  // A deploy refused the same way ("Add your Kalshi demo (sandbox) key on the Funds page first.") flashes as a notice.
  assert.match(f.notice('Add your Kalshi demo (sandbox) key on the Funds page first.', 'bad', true),
    /<span>Add your Kalshi demo \(sandbox\) key on <a href="\/funds#connect-kalshi">the Funds page<\/a> first\.<\/span>/);
  // Only those fixed words become markup: whatever else the message says stays escaped.
  const hostile = f.notice('<img src=x onerror=alert(1)> Funds page', 'bad');
  assert.match(hostile, /&lt;img src=x onerror=alert\(1\)&gt; <a href="\/funds#connect-kalshi">Funds page<\/a>/);
  assert.doesNotMatch(hostile, /<img/);
  assert.match(f.notice('Saved.', 'good'), /<span>Saved\.<\/span>/);
});

test('the panel names its log Activity feed, as the dashboard card and the story do', async () => {
  const f = frontend(() => response(catalog)); f.apBuildShell(f.box); await flush();
  assert.match(f.box.querySelector('.apf-session-head').innerHTML, /<span class="say-kind">Activity feed<\/span>/);
  assert.doesNotMatch(source, /Live session/);
  assert.match(source, /Every move shows up in its activity feed\./);
});

test('the autopilot feed labels switch notes as switches, not reviews', () => {
  const f = frontend();
  const kind = content => f.apFeedLi({role: 'system', content, created_at: '2026-10-25T19:22:00Z'}).querySelector('.say-kind').innerHTML;
  assert.equal(kind('Autopilot is ON: the agent may research, deploy and tune paper strategies.'), 'Autopilot on');
  assert.equal(kind('Autopilot is OFF: the agent will only propose; you approve every change'), 'Autopilot off');
  assert.equal(kind('LIVE autopilot is ON — the agent may promote proven strategies.'), 'Live autopilot on');
  assert.equal(kind('LIVE autopilot is OFF.'), 'Live autopilot off');
  assert.equal(kind('Holding: nothing cleared the gates this cycle.'), 'Reviewed');
});

test('billing continues to render the server-provided welcome credit instead of a UI constant', async () => {
  for (const free_bonus of [20, 37]) {
    const f = frontend(path => { assert.match(path, /^\/api\/billing(\?|$)/); return response({configured: false, cards: [], ledger: [], balance: free_bonus,
      free_bonus, spent: 0, topup_fee_pct: 3, default_pm: null}); });
    await f.viewBilling();
    const figures = f.root.querySelector('#bfigs').innerHTML;
    assert.match(figures, /Welcome credit/); assert.ok(figures.includes('$' + free_bonus.toFixed(2)));
    // Payments off says so in a customer's words: it read "Payments aren’t enabled on this server yet".
    assert.match(f.root.querySelector('#main').innerHTML, /Card payments aren’t available yet\. You can still use your free credits\./);
    assert.doesNotMatch(f.root.querySelector('#main').innerHTML, /server/i);
    assert.equal(posts(f).length, 0);
  }
});

test('billing shows a failed auto-reload by the switch, with its reason and Update card', async () => {
  const failed = {at: '2026-10-26T13:05:00Z', text: 'It couldn\'t add $20.00 in credits. That card has expired. Add a current card and try again.'};
  const f = frontend(path => { assert.match(path, /^\/api\/billing(\?|$)/); return response({configured: true, publishable_key: 'synthetic-only',
    cards: [{id: 'pm_1', brand: 'visa', last4: '4242', exp_month: 1, exp_year: 2026}], default_pm: 'pm_1', auto_reload: true, ledger: [],
    balance: 3, free_bonus: 20, spent: 17, spent_7d: 4, topup_fee_pct: 5.5, autoreload_amount: 20, autoreload_threshold: 5,
    min_reload_amount: 20, min_reload_threshold: 5, min_topup: 5, max_topup: 1000, min_run_balance: 1, reload_failed: failed}); });
  await f.viewBilling(); await flush();
  const note = f.root.querySelector('#autorel-fail');
  assert.ok(note);
  assert.match(note.innerHTML, /<b>Auto-reload failed<\/b>/);
  assert.match(note.innerHTML, /That card has expired\. Add a current card and try again\./);
  assert.equal(f.root.querySelector('#autorel-fix').textContent, 'Update card');
  assert.doesNotMatch(f.root.querySelector('#main').innerHTML, /list price|pi_|cus_|Stripe error/);
  assert.equal(posts(f).length, 0);
});

test('current paper proposal approval semantics and broker callback route survive reconciliation', () => {
  const f = frontend();
  assert.equal(f.routes.find(([pattern]) => pattern.test('/settings/account'))[1], f.viewFunds);
  const paper = f.apFeedLi({role: 'system', content: 'Synthetic paper order', created_at: '2026-10-19T00:00:00Z', proposal_id: 7, proposal_status: 'applied', proposal_kind: 'alpaca_paper'});
  assert.match(paper.innerHTML, /Alpaca paper order/); assert.match(paper.innerHTML, />Approved</);
  assert.doesNotMatch(paper.innerHTML, />Applied<|>Filled</);
  assert.doesNotMatch(source, /TauBrokerConnections\.mount/);
  if (process.env.TAU_TEST_THEME === 'meridian') assert.match(source, /api\('\/api\/waitlist'/);
  else {
    assert.doesNotMatch(source, /api\('\/api\/waitlist'/);
    assert.match(source, /href="\/terms"/);
    assert.match(source, /href="\/privacy"/);
  }
});

test('market focus picker shows the saved focus, posts a change and follows status updates', async () => {
  const f = frontend(path => path === '/api/models' ? response(catalog) : path === '/api/autopilot/focus' ? response({ok: true, focus: ['crypto']}) : response({messages: []}));
  f.S.ap.focus = ['btc']; f.apBuildShell(f.box); await flush();
  const select = f.box.querySelector('#apf-focus');
  assert.equal(select.value, 'btc');
  assert.deepEqual(select.options.map(o => o.attributes.value), ['', 'crypto', 'btc', 'sports']);
  select.value = 'crypto'; await select.onchange();
  const post = posts(f).find(row => row.path === '/api/autopilot/focus');
  assert.deepEqual(JSON.parse(post.options.body), {focus: ['crypto']});
  assert.deepEqual([...f.S.ap.focus], ['crypto']); assert.equal(select.value, 'crypto'); assert.equal(select.disabled, false);
  f.apUpdate(f.box, status({focus: ['high_ny']}));
  const synced = f.box.querySelector('#apf-focus');
  assert.equal(synced.value, 'high_ny'); assert.match(synced.innerHTML, /Only High ny/);  // a key the harness's catalog doesn't list; a listed one reads by its name
  f.apUpdate(f.box, status({focus: []})); assert.equal(f.box.querySelector('#apf-focus').value, '');
});

test('a rejected focus change restores the previous choice', async () => {
  const f = frontend(path => path === '/api/models' ? response(catalog) : response({error: 'Synthetic focus rejection'}, 400));
  f.S.ap.focus = ['crypto']; f.apBuildShell(f.box); await flush();
  const select = f.box.querySelector('#apf-focus'); select.value = 'sports'; await select.onchange();
  assert.equal(select.value, 'crypto'); assert.deepEqual([...f.S.ap.focus], ['crypto']);
  assert.deepEqual(f.alerts, []); assert.match(f.box.querySelector('#apf-flash').innerHTML, /error-text">Synthetic focus rejection/);
});

// Both bundles carry the same keyboard and screen-reader contracts. The behaviour is checked per
// bundle (tests/test_frontend_merge.mjs, tests/test_meridian_workspace.mjs); these are the pieces
// that are easy to drop on one side only.
test('this bundle keeps the keyboard and screen-reader contracts of the main flows', () => {
  // A control that goes disabled is blurred by the browser: busy() hands focus back to it.
  assert.match(source, /async function busy\(btn, fn, waited = waitNote\(btn\)\) \{\n\s*const had = document\.activeElement === btn;/);
  // A write that hangs says so beside its control after 20s, and the word goes when the write answers.
  assert.match(source, /const WAIT_NOTE_MS = 20000;\n\s*const WAIT_NOTE = 'Still waiting for Tau to confirm…';/);
  assert.match(source, /try \{ return await fn\(\); \} finally \{\n\s*waited\(\);/);
  assert.match(source, /if \(had && btn\.isConnected && \(!a \|\| a === document\.body\) && btn\.focus\) btn\.focus\(\{ preventScroll: true \}\);/);
  // Turning autopilot on or off is said out loud (the switch, its copy and the card change silently).
  assert.match(source, /announce\('Autopilot is on\. It researches and trades on paper by itself; every move shows up in the autopilot panel\.'\);/);
  assert.match(source, /announce\(on \? 'Autopilot is on\. It researches and trades on paper by itself\.' : 'Autopilot is off\. It only suggests ideas for you to approve\.'\);/);
  // The live switch, the kill switch and a refused arm answer in the panel AND out loud.
  assert.match(source, /function apFlash\(box, msg, kind\) \{[\s\S]*?if \(msg\) announce\(msg, kind === 'bad'\);/);
  // The full-screen sheet keeps Tab inside it; the bell and the profile menu close when focus leaves.
  assert.match(source, /if \(e\.key === 'Tab' && apSheet\(\) && apExpanded\(\)\) apSheetTab\(box, e\);/);
  assert.match(source, /const apSheet = \(\) => !!\(window\.matchMedia && window\.matchMedia\('\(max-width: 600px\)'\)\.matches\);/);
  assert.match(source, /wrap\.addEventListener\('focusout', \(e\) => \{ if \(!menu\.hidden && !wrap\.contains\(e\.relatedTarget\)\) close\(\); \}\);/);
  assert.match(source, /prof\.addEventListener\('focusout', \(e\) => \{ if \(!menu\.hidden && !prof\.contains\(e\.relatedTarget\)\) close\(\); \}\);/);
  // Every field a reader meets has a name of its own, and the hidden photo picker (driven by the
  // Photo button) is not an unnamed, invisible tab stop.
  assert.match(source, /<textarea class="input" id="post-body"[^>]*aria-label="Write a post"/);
  assert.match(source, /<input class="input" maxlength="1000" aria-label="Write a reply"/);
  assert.match(source, /<input type="file" id="photo-input"[^>]*tabindex="-1" aria-label="Choose a photo to attach">/);
});
