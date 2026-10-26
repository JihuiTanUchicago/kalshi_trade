// Offline page renderer for the view fuzz test (tests/test_view_fuzz.mjs): boots a bundle in a fake DOM,
// answers every API read from a fixture table, and records each crash the page reports (the same
// reportBroken('view') hook that sends a broken page to /admin), plus any promise that rejects unhandled.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const flush = () => new Promise(resolve => setImmediate(resolve));
const realSetTimeout = setTimeout;

// One compound selector (tag, #id, .class, [attr], [attr=value]; pseudo-classes ignored) as a predicate,
// parsed once: the pages query the same few selectors thousands of times a run.
const selectors = new Map();
function compileSelector(selector) {
  let test = selectors.get(selector);
  if (test) return test;
  const plain = selector.replace(/:not\([^)]*\)|:[\w-]+(\([^)]*\))?/g, '');
  if (plain.includes(',')) {
    const any = plain.split(',').map(s => compileSelector(s.trim()));
    test = el => any.some(t => t(el));
  } else {
    const tag = (plain.match(/^[\w-]+/) || [])[0], ids = [...plain.matchAll(/#([\w-]+)/g)].map(m => m[1]);
    const classes = [...plain.matchAll(/\.([\w-]+)/g)].map(m => m[1]);
    const attrs = [...plain.matchAll(/\[([\w-]+)(?:([~^$*|]?)=(?:"([^"]*)"|'([^']*)'|([^\]]+)))?\]/g)]
      .map(([, key, how, a, b, c]) => [key, how ? undefined : a ?? b ?? c]);
    test = el => (!tag || el.tag === tag) && ids.every(id => el.id === id) && classes.every(c => el.classes.has(c))
      && attrs.every(([key, want]) => key in el.attributes && (want === undefined || el.attributes[key] === want));
  }
  selectors.set(selector, test);
  return test;
}

class Element {
  constructor(tag = 'div', attributes = {}) {
    this.tag = tag; this.attributes = {...attributes}; this.dataset = {};
    this.children = []; this.listeners = new Map(); this.style = {setProperty() {}}; this.writes = 0;
    this.scrollTop = 0; this.scrollLeft = 0; this.scrollHeight = 0; this.scrollWidth = 0; this.clientHeight = 100; this.clientWidth = 760;
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
  get options() { return this.querySelectorAll('option'); }
  get isConnected() { return !this.removed && (!this.parent || this.parent.isConnected); }
  get parentElement() { return this.parent || null; }
  get parentNode() { return this.parent || null; }
  get firstChild() { return this.children[0] || null; }
  get firstElementChild() { return this.children[0] || null; }
  get lastElementChild() { return this.children.at(-1) || null; }
  get nextElementSibling() { const s = this.parent?.children || []; return s[s.indexOf(this) + 1] || null; }
  get previousElementSibling() { const s = this.parent?.children || []; return s[s.indexOf(this) - 1] || null; }
  get className() { return [...this.classes].join(' '); }
  set className(value) { this.classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get id() { return this.attributes.id; }
  set id(value) { this.attributes.id = value; }
  get open() { return 'open' in this.attributes; }
  set open(value) { if (value) this.attributes.open = ''; else delete this.attributes.open; }
  get offsetWidth() { return 760; }
  get offsetHeight() { return 100; }
  get innerHTML() { return this.html || ''; }
  set innerHTML(value) {
    value = String(value);
    this.html = value; this.text = undefined; this.writes++; this.children.forEach(child => { child.removed = true; }); this.children = [];
    const stack = [{element: this, start: 0}];
    const voids = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
    for (const match of value.matchAll(/<\/?([a-z][\w-]*)\b([^>]*)>/gi)) {
      const tag = match[1].toLowerCase();
      if (match[0].startsWith('</')) {
        // Close up to the matching tag, so one unclosed element doesn't swallow the rest of the page.
        const at = stack.findLastIndex((entry, i) => i > 0 && entry.element.tag === tag);
        if (at > 0) while (stack.length > at) { const closed = stack.pop(); closed.element.html = value.slice(closed.start, match.index); }
      } else {
        const attributes = {};
        for (const [, key, quoted, single, bare] of match[2].matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) attributes[key] = quoted ?? single ?? bare ?? '';
        const child = new Element(tag, attributes); stack.at(-1).element.appendChild(child);
        if (!voids.has(tag) && !match[0].endsWith('/>')) stack.push({element: child, start: match.index + match[0].length});
      }
    }
  }
  get outerHTML() { return `<${this.tag}>${this.innerHTML}</${this.tag}>`; }
  set outerHTML(value) { this.innerHTML = value; }
  get textContent() { return this.text ?? this.innerHTML.replace(/<[^>]*>/g, ''); }
  set textContent(value) { this.text = String(value); this.html = ''; this.children = []; }
  get innerText() { return this.textContent; }
  set innerText(value) { this.textContent = value; }
  matches(selector) { return compileSelector(selector)(this); }
  querySelectorAll(selector) {
    if (selector.includes(',') && !/\([^)]*,/.test(selector)) {
      const all = new Set(selector.split(',').flatMap(s => this.querySelectorAll(s.trim())));
      return [...all];
    }
    const parts = selector.trim().split(/\s+(?![^[]*\])/).filter(p => p !== '>'), found = [];
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
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest?.(selector) || null; }
  contains(element) { return element === this || this.children.some(child => child.contains(element)); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  removeEventListener(name) { this.listeners.delete(name); }
  dispatchEvent(event) { this.listeners.get(event.type)?.(event); }
  appendChild(child) {
    if (child.parent) child.parent.children = child.parent.children.filter(element => element !== child);
    this.children.push(child); child.parent = this; child.removed = false; return child;
  }
  append(...xs) { xs.forEach(x => typeof x === 'object' && this.appendChild(x)); }
  prepend(child) { this.appendChild(child); this.children.unshift(this.children.pop()); }
  insertBefore(child) { return this.appendChild(child); }
  replaceWith(child) { if (this.parent) { const i = this.parent.children.indexOf(this); this.parent.children[i] = child; child.parent = this.parent; } this.removed = true; }
  replaceChildren(...xs) { this.children = []; this.append(...xs); }
  removeChild(child) { this.children = this.children.filter(c => c !== child); child.removed = true; }
  insertAdjacentHTML(_position, html) { const holder = new Element('div'); holder.innerHTML = html; holder.children.forEach(c => this.appendChild(c)); this.html = (this.html || '') + html; }
  insertAdjacentElement(_position, el) { this.appendChild(el); return el; }
  getAttribute(key) { return this.attributes[key] ?? null; }
  hasAttribute(key) { return key in this.attributes; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  toggleAttribute(key, on) { if (on ?? !(key in this.attributes)) this.attributes[key] = ''; else delete this.attributes[key]; }
  getBoundingClientRect() { return {top: 0, left: 0, right: 760, bottom: 100, width: 760, height: 100, x: 0, y: 0}; }
  scrollIntoView() {} scrollTo() {} scrollBy() {} focus() {} blur() {} click() { this.listeners.get('click')?.({target: this, preventDefault() {}}); }
  showModal() { this.attributes.open = ''; } close() { delete this.attributes.open; }
  getContext() { return null; }
  animate() { return {finished: Promise.resolve(), cancel() {}}; }
  remove() { this.removed = true; }
}

// Records reads of keys a reply lacks (`trace` is a Set of "endpoint path.to.key"), to find what a
// fixture should carry.
const IGNORE = new Set(['then', 'toJSON', 'constructor', 'length', 'nodeType', 'asymmetricMatch']);
function traced(value, where, trace) {
  if (!value || typeof value !== 'object') return value;
  return new Proxy(value, {get(target, key) {
    if (typeof key !== 'string') return target[key];
    if (!(key in target) && !IGNORE.has(key)) trace.add(where + ' ' + key);
    const v = target[key];
    return v && typeof v === 'object' ? traced(v, where + (Array.isArray(target) ? '[]' : '.' + key), trace) : v;
  }});
}

// Boots one bundle on a path. `reply(path)` answers each GET (data or {status, data}); POSTs answer {ok: true}.
// Returns what the page reported broken, what it asked for, and the page itself.
export async function renderPage(bundleSource, path, reply, {me, trace} = {}) {
  const root = new Element('div', {id: 'app'}), body = new Element('body'); body.appendChild(root);
  const crashes = [], requests = [];
  const [pathname, query] = path.split('?');
  const location = {pathname, search: query ? '?' + query : '', hash: '', origin: 'http://offline.invalid', href: 'http://offline.invalid' + path, reload() {}, assign() {}, replace() {}};
  const navigate = (_s, _t, to) => { const [p, q] = String(to).split('?'); location.pathname = p.split('#')[0]; location.search = q ? '?' + q : ''; };
  const store = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k)}; };
  const document = {body, head: new Element('head'), activeElement: body, hidden: false, title: '', cookie: '',
    documentElement: new Element('html'),
    getElementById: id => body.querySelector('#' + id), querySelector: s => body.querySelector(s), querySelectorAll: s => body.querySelectorAll(s),
    addEventListener() {}, removeEventListener() {}, createElement: tag => new Element(tag), elementsFromPoint: () => []};
  const timers = [];
  const context = vm.createContext({
    Intl, URL, URLSearchParams, AbortController, console: {log() {}, warn() {}, error() {}, info() {}},
    document, navigator: {userAgent: 'offline', clipboard: {writeText: async () => {}}, onLine: true},
    window: {addEventListener() {}, removeEventListener() {}, scrollTo() {}, scrollBy() {}, matchMedia: () => ({matches: false, addEventListener() {}}),
      __tauReport: (kind, err) => { if (kind === 'view') crashes.push(err); }, __TAU_ME__: null, __TAU_UI__: undefined, innerWidth: 1200, innerHeight: 800,
      Stripe: () => ({elements: () => ({create: () => ({mount() {}, on() {}, unmount() {}})}), confirmSetup: async () => ({})})},
    addEventListener() {}, removeEventListener() {}, location, history: {pushState: navigate, replaceState: navigate, back() {}},
    localStorage: store(), sessionStorage: store(), innerWidth: 1200, innerHeight: 800,
    requestAnimationFrame: cb => { timers.push(cb); return timers.length; }, cancelAnimationFrame() {},
    setInterval: () => 0, clearInterval() {},
    setTimeout: (cb, ms) => { if (!ms || ms <= 50) timers.push(cb); return 0; }, clearTimeout() {},
    fetch: async (url, options = {}) => {
      const p = String(url);
      requests.push(p);
      if (options.method === 'POST') return response({ok: true});
      let r = reply(p);
      if (r && r.__status) return response(r.data, r.__status);
      if (r === undefined) r = {};
      return response(trace ? traced(r, p.split('?')[0], trace) : r);
    },
  });
  context.window.document = document; context.window.location = location;
  compiled(bundleSource).runInContext(context);
  const t = context.__t;
  t.S.me = me;
  t.S.hot = {markets: []}; t.S.hotAt = Date.now();
  const rejected = [];
  const onRejection = e => rejected.push(e);
  process.on('unhandledRejection', onRejection);
  try {
    // A page that never settles (a read it is still waiting on) is reported as hung, not left to hang the test.
    let tid;
    const hung = await Promise.race([t.render().then(() => false), new Promise(done => { tid = realSetTimeout(() => done(true), 1500); })]);
    clearTimeout(tid);
    if (hung) crashes.push(new Error('hung: ' + requests.join(' ')));
    for (let i = 0; i < 6; i++) {
      await flush();
      for (const cb of timers.splice(0)) { try { cb(); } catch (e) { crashes.push(e); } }
    }
  } catch (e) { crashes.push(e); }
  finally { await flush(); process.off('unhandledRejection', onRejection); }
  return {crashes: [...crashes, ...rejected], requests, root, location};
}

// Each bundle is compiled once and run in a fresh context per render (hundreds of renders a test).
const scripts = new Map();
function compiled(source) {
  if (!scripts.has(source)) {
    const boot = '  setupGlossary();\n  render();';
    if (source.split(boot).length !== 2) throw new Error('bundle boot line changed');
    scripts.set(source, new vm.Script(source.replace(boot, 'globalThis.__t = {S, render};')));
  }
  return scripts.get(source);
}

export const loadBundle = name => readFileSync(new URL('../app/static/' + name, import.meta.url), 'utf8');

// A field's path as the contract lists name it: list positions as '*' ("deployments.*.side").
export const pattern = path => path.map(k => typeof k === 'number' ? '*' : k).join('.');

// The page's words: a part painted later doesn't re-serialize its parent here, so this reads every
// element the page wrote into (innerHTML or textContent), which together cover what is on screen.
export function pageText(root) {
  const out = [], visit = el => { if (el.writes || el.text !== undefined) out.push(el.textContent); el.children.forEach(visit); };
  visit(root);
  return out.join(' ');
}
// Chart points ([t, v] pairs, number lists) are data, not fields: the fuzz leaves them whole.
const isPoints = v => Array.isArray(v) && v.length > 0 && v.every(x => typeof x === 'number' || (Array.isArray(x) && x.every(y => typeof y === 'number')));

// The changes the fuzz makes to one reply, each a list of [path, op] applied together in one render
// (op 'missing' deletes the field, 'null' sets it null). Lists are walked into their first `items`
// entries. single: every field alone, missing then null. Otherwise grouped, for a fast run: each
// object's plain fields all missing at once (an older row without them), and each object or list field
// alone set null (a state the server sends null in); a group that breaks is split to name the culprit. `kept(pattern)` names fields
// the server always sends, which the fuzz leaves alone.
export function mutationSets(value, {items = 8, single = false, kept = () => false} = {}, path = []) {
  const out = [];
  if (Array.isArray(value)) {
    if (!isPoints(value)) value.slice(0, items).forEach((v, i) => out.push(...mutationSets(v, {items, single, kept}, [...path, i])));
    return out;
  }
  if (!value || typeof value !== 'object') return out;
  const keys = Object.keys(value).filter(k => !kept(pattern([...path, k])));
  const nested = k => value[k] && typeof value[k] === 'object';
  const plain = single ? keys : keys.filter(k => !nested(k));
  if (single) for (const k of plain) out.push([[[...path, k], 'missing']], [[[...path, k], 'null']]);
  else if (plain.length) out.push(plain.map(k => [[...path, k], 'missing']));
  for (const k of Object.keys(value).filter(nested)) {
    if (!single && !kept(pattern([...path, k]))) out.push([[[...path, k], 'null']]);
    out.push(...mutationSets(value[k], {items, single, kept}, [...path, k]));
  }
  return out;
}

// A copy of `value` with each [path, op] of `changes` applied.
export function mutate(value, changes) {
  const copy = structuredClone(value);
  for (const [path, op] of changes) {
    let at = copy;
    for (const k of path.slice(0, -1)) at = at[k];
    if (op === 'null') at[path.at(-1)] = null; else delete at[path.at(-1)];
  }
  return copy;
}

// Renders `page` with its replies, then once per change of mutationSets for each reply it read, and
// returns what broke: [{endpoint, path, op, error}] (a baseline failure comes back as endpoint
// '(baseline)'). `kept` is {endpoint: [patterns the server always sends]}; `skip` lists endpoints left whole.
export async function fuzzPage(source, page, replies, me, {kept = {}, skip = [], items, single = false} = {}) {
  const answer = r => url => r[url.split('?')[0]];
  const run = async r => (await renderPage(source, page, answer(r), {me})).crashes[0];
  const base = await renderPage(source, page, answer(replies), {me});
  if (base.crashes.length) return [{endpoint: '(baseline)', path: '', op: '', error: base.crashes[0]}];
  const broke = [];
  for (const endpoint of [...new Set(base.requests.map(u => u.split('?')[0]))].filter(e => e in replies && !skip.includes(e))) {
    const keep = new Set(kept[endpoint] || []);
    for (const changes of mutationSets(replies[endpoint], {items, single, kept: p => keep.has(p)})) {
      const error = await run({...replies, [endpoint]: mutate(replies[endpoint], changes)});
      if (!error) continue;
      const found = [];
      if (changes.length > 1) {
        for (const change of changes) {
          const one = await run({...replies, [endpoint]: mutate(replies[endpoint], [change])});
          if (one) found.push({endpoint, path: change[0].join('.'), op: change[1], error: one});
        }
      }
      broke.push(...(found.length ? found : [{endpoint, path: changes.map(c => c[0].join('.')).join(' + '), op: changes[0][1], error}]));
    }
  }
  return broke;
}
