import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const {mount, authorizationUrl, callbackMessage} = require('../app/static/broker-connections.js');
const fixtures = () => ({providers: [
  {id: 'ibkr', configured: true, default_environment: 'live', environments: ['live'], connections: [], permission_note: 'Authorize access with Interactive Brokers.'},
  {id: 'robinhood', configured: true, default_environment: 'live', environments: ['live'], connections: [], permission_note: 'Orders are limited to your Robinhood Agentic account.'},
  {id: 'alpaca', configured: true, default_environment: 'paper', environments: ['paper', 'live'], connections: [], permission_note: 'Read account access by default.'},
]});
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };

// A minimal host exercises delegated events and late responses without a browser,
// provider credentials, real accounts or network access.
class Host {
  constructor() { this.isConnected = true; this.writes = 0; this.html = ''; this.members = new Set(); this.attributes = {}; }
  get innerHTML() { return this.html; }
  set innerHTML(value) { this.html = value; this.writes++; this.members.clear(); }
  setAttribute(key, value) { this.attributes[key] = value; }
  contains(element) { return this.members.has(element); }
  button(action, broker, environment) {
    const tag = [...this.html.matchAll(/<button\b([^>]*)>/g)].map(match => match[1]).find(value =>
      value.includes(`data-broker-action="${action}"`) && (!broker || value.includes(`data-broker="${broker}"`)) && (!environment || value.includes(`data-environment="${environment}"`)));
    assert.ok(tag, `rendered ${action} ${broker || ''} ${environment || ''} button`);
    const button = {disabled: /\sdisabled(?:\s|$)/.test(tag), dataset: {}, closest: () => button};
    for (const [, key, value] of tag.matchAll(/data-([\w-]+)="([^"]*)"/g)) button.dataset[key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
    this.members.add(button);
    return button;
  }
  click(button) { return this.onclick({target: button, preventDefault() {}}); }
  change(dataset, value, checked) { return this.onchange({target: {dataset, value, checked}}); }
}

test('both shipped themes load and mount the shared broker account controls', () => {
  const html = readFileSync(new URL('../app/static/index.html', import.meta.url), 'utf8');
  assert.ok(html.indexOf('broker-connections.js?v={{brokers_v}}') < html.indexOf('boot.js?v='));
  assert.match(html, /broker-connections\.css\?v=\{\{brokers_css_v\}\}/);
  for (const name of ['app.js', 'app.meridian.js']) {
    const source = readFileSync(new URL('../app/static/' + name, import.meta.url), 'utf8');
    assert.match(source, /<section id="broker-connections" aria-label="Broker accounts"><\/section>/);
    assert.match(source, /TauBrokerConnections\.mount\(brokerHost, \{api, isCurrent: \(\) => gen === S\.gen\}\)/);
  }
  const context = vm.createContext({URL, URLSearchParams});
  vm.runInContext(readFileSync(new URL('../app/static/broker-connections.js', import.meta.url), 'utf8'), context);
  assert.equal(typeof context.TauBrokerConnections.mount, 'function');
});

test('brokers render in the requested order and Alpaca starts with paper read access', async () => {
  const host = new Host(), calls = [], navigations = [];
  const control = mount(host, {search: '', navigate: value => navigations.push(value), api: async (path, body) => {
    calls.push({path, body});
    return path === '/api/brokers' ? fixtures() : {authorization_url: 'https://app.alpaca.markets/oauth/authorize?state=synthetic'};
  }});
  await control.ready;
  assert.ok(host.innerHTML.indexOf('data-broker-card="alpaca"') < host.innerHTML.indexOf('data-broker-card="robinhood"'));
  assert.ok(host.innerHTML.indexOf('data-broker-card="robinhood"') < host.innerHTML.indexOf('data-broker-card="ibkr"'));
  assert.match(host.innerHTML, /<option value="paper" selected>/);
  assert.doesNotMatch(host.innerHTML, /data-broker-permission="alpaca" checked/);
  await host.click(host.button('connect', 'alpaca'));
  assert.deepEqual(calls[1], {path: '/api/brokers/alpaca/connect', body: {environment: 'paper', permission: 'read'}});
  assert.deepEqual(navigations, ['https://app.alpaca.markets/oauth/authorize?state=synthetic']);
  assert.match(host.innerHTML, /Live trading in Tau stays disabled/);
});

test('Alpaca trading authorization and live environment require explicit selection', async () => {
  const host = new Host(), calls = [];
  const control = mount(host, {search: '', navigate() {}, api: async (path, body) => {
    calls.push({path, body});
    return path === '/api/brokers' ? fixtures() : {authorization_url: 'https://app.alpaca.markets/oauth/authorize?scope=data%20trading'};
  }});
  await control.ready;
  host.change({brokerEnvironment: 'alpaca'}, 'live');
  host.change({brokerPermission: 'alpaca'}, undefined, true);
  await host.click(host.button('connect', 'alpaca'));
  assert.deepEqual(calls[1].body, {environment: 'live', permission: 'trading'});
});

test('unconfigured and expired connections remain disconnectable without leaking account labels into HTML', async () => {
  const data = fixtures(), alpaca = data.providers.find(provider => provider.id === 'alpaca');
  Object.assign(alpaca, {configured: false, reason: '<b>Operator setup pending</b>', setup_url: 'https://docs.alpaca.markets/us/docs/about-connect-api', connections: [
    {connected: true, expired: true, environment: 'paper', account_label: '<img src=x onerror=alert(1)>', scopes: ['data']},
  ]});
  const host = new Host(), calls = [];
  const control = mount(host, {search: '', api: async (path, body) => {
    calls.push({path, body}); return path === '/api/brokers' ? data : {disconnected: true};
  }});
  await control.ready;
  assert.equal(host.button('connect', 'alpaca').disabled, true);
  assert.equal(host.button('disconnect', 'alpaca', 'paper').disabled, false);
  assert.match(host.innerHTML, /Expired/);
  assert.match(host.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(host.innerHTML, /<img|<b>Operator/);
  await host.click(host.button('connect', 'alpaca'));
  assert.equal(calls.length, 1);
  await host.click(host.button('disconnect', 'alpaca', 'paper'));
  assert.deepEqual(calls[1], {path: '/api/brokers/alpaca/disconnect', body: {environment: 'paper'}});
  assert.match(host.innerHTML, /Tau access removed\. You can also revoke the grant at your broker/);
  assert.doesNotMatch(host.innerHTML, /broker-account-label|>Expired</);
});

test('provider fields, setup URLs and callback errors cannot inject HTML or raw response text', async () => {
  const data = fixtures(), alpaca = data.providers.find(provider => provider.id === 'alpaca');
  Object.assign(alpaca, {configured: false, setup_url: 'javascript:alert(1)', reason: '<script>unsafe()</script>', permission_note: '" onerror="alert(1)'});
  data.providers.push({id: 'evil', configured: true, name: '<img>'});
  const host = new Host();
  const control = mount(host, {search: '?broker=alpaca&broker_status=failed&error=<script>private_token</script>', api: async () => data});
  await control.ready;
  assert.match(host.innerHTML, /Alpaca could not be connected\. Try again/);
  assert.match(host.innerHTML, /&lt;script&gt;unsafe\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(host.innerHTML, /javascript:|<script>|private_token|data-broker-card="evil"/);
  for (const search of ['?broker=__proto__&broker_status=connected', '?broker=alpaca&broker_status=__proto__', '?broker=unknown&broker_status=connected']) assert.equal(callbackMessage(search), null);
});

test('redirects are restricted to each broker’s official authorization endpoint', () => {
  assert.equal(authorizationUrl('robinhood', 'https://robinhood.com/oauth?state=test'), 'https://robinhood.com/oauth?state=test');
  assert.equal(authorizationUrl('ibkr', 'https://interactivebrokers.com/authorize?oauth_token=test'), 'https://interactivebrokers.com/authorize?oauth_token=test');
  for (const value of ['javascript:alert(1)', 'http://app.alpaca.markets/oauth/authorize', 'https://app.alpaca.markets.evil.test/oauth/authorize', 'https://app.alpaca.markets@evil.test/oauth/authorize', 'https://user@app.alpaca.markets/oauth/authorize', 'https://app.alpaca.markets:444/oauth/authorize', 'https://app.alpaca.markets/oauth/authorize#unsafe', 'https://app.alpaca.markets/untrusted', '//app.alpaca.markets/oauth/authorize']) assert.throws(() => authorizationUrl('alpaca', value));
  assert.throws(() => authorizationUrl('robinhood', 'https://app.alpaca.markets/oauth/authorize'));
  assert.throws(() => authorizationUrl('__proto__', 'https://app.alpaca.markets/oauth/authorize'));
});

test('a malformed authorization response stays on the page with a fixed, retryable error', async () => {
  const host = new Host(), navigations = [];
  const control = mount(host, {search: '', navigate: value => navigations.push(value), api: async path =>
    path === '/api/brokers' ? fixtures() : {authorization_url: 'https://evil.test/steal?token=private'}});
  await control.ready;
  await host.click(host.button('connect', 'alpaca'));
  assert.deepEqual(navigations, []);
  assert.match(host.innerHTML, /Could not start the connection\. Try again/);
  assert.doesNotMatch(host.innerHTML, /evil\.test|token=private/);
  assert.equal(host.button('connect', 'alpaca').disabled, false);
});

test('double clicks while authorization is pending make one request', async () => {
  const host = new Host(), pending = deferred(), calls = [];
  const control = mount(host, {search: '', navigate() {}, api: async (path, body) => {
    calls.push({path, body}); return path === '/api/brokers' ? fixtures() : pending.promise;
  }});
  await control.ready;
  const first = host.click(host.button('connect', 'alpaca'));
  const secondButton = host.button('connect', 'alpaca');
  assert.equal(secondButton.disabled, true);
  secondButton.disabled = false; // The in-memory guard also rejects a queued duplicate event.
  await host.click(secondButton);
  assert.equal(calls.length, 2);
  pending.reject(new Error('provider secret must not be displayed'));
  await first;
  assert.match(host.innerHTML, /Could not start the connection/);
  assert.doesNotMatch(host.innerHTML, /provider secret/);
});

test('late loading responses do not rewrite a page after navigation', async () => {
  const host = new Host(), pending = deferred();
  let current = true;
  const control = mount(host, {search: '', isCurrent: () => current, api: () => pending.promise});
  const writes = host.writes;
  current = false; pending.resolve(fixtures()); await control.ready;
  assert.equal(host.writes, writes);
  assert.doesNotMatch(host.innerHTML, /data-broker-card/);
});

test('late authorization does not redirect or rewrite an old page', async () => {
  const host = new Host(), pending = deferred(), navigations = [];
  const control = mount(host, {search: '', navigate: value => navigations.push(value), api: path =>
    path === '/api/brokers' ? Promise.resolve(fixtures()) : pending.promise});
  await control.ready;
  const connection = host.click(host.button('connect', 'alpaca'));
  const writes = host.writes;
  host.isConnected = false;
  pending.resolve({authorization_url: 'https://app.alpaca.markets/oauth/authorize?state=old'});
  await connection;
  assert.deepEqual(navigations, []);
  assert.equal(host.writes, writes);
});

test('load failures and invalid API payloads offer one retry without showing raw errors', async () => {
  const host = new Host();
  let calls = 0;
  const control = mount(host, {search: '', api: async () => {
    if (++calls === 1) throw new Error('private_provider_error');
    if (calls === 2) return {providers: 'invalid'};
    return fixtures();
  }});
  await control.ready;
  assert.match(host.innerHTML, /Broker accounts could not be loaded/);
  assert.doesNotMatch(host.innerHTML, /private_provider_error/);
  await host.click(host.button('retry'));
  assert.match(host.innerHTML, /Broker accounts could not be loaded/);
  await host.click(host.button('retry'));
  assert.equal(calls, 3);
  assert.match(host.innerHTML, /data-broker-card="alpaca"/);
  assert.doesNotMatch(host.innerHTML, /data-broker-action="retry"/);
  control.destroy();
  assert.equal(host.onclick, null);
  assert.equal(host.onchange, null);
});

test('disconnect errors preserve the connection and allow another attempt', async () => {
  const data = fixtures();
  data.providers.find(provider => provider.id === 'robinhood').connections = [{connected: true, environment: 'live', scopes: []}];
  const host = new Host();
  const control = mount(host, {search: '', api: async path => {
    if (path === '/api/brokers') return data;
    throw new Error('private broker token');
  }});
  await control.ready;
  await host.click(host.button('disconnect', 'robinhood', 'live'));
  assert.match(host.innerHTML, /Could not disconnect this account/);
  assert.doesNotMatch(host.innerHTML, /private broker token/);
  assert.equal(host.button('disconnect', 'robinhood', 'live').disabled, false);
});

test('nested Alpaca paper host survives broker refresh and environment changes and is disposed with its parent', async () => {
  class NestedHost extends Host {
    get innerHTML() { return this.accounts ? this.accounts.innerHTML + this.paper.innerHTML : this.html; }
    set innerHTML(value) {
      this.html = value; this.writes++; this.members.clear();
      this.accounts = new Host(); this.paper = new Host();
      this.members.add(this.accounts); this.members.add(this.paper);
    }
    querySelector(selector) { return selector === '[data-broker-accounts]' ? this.accounts : selector === '[data-alpaca-paper]' ? this.paper : null; }
    contains(value) { return this.members.has(value) || !!(this.accounts && this.accounts.contains(value)); }
    button(...args) { return this.accounts.button(...args); }
  }
  const host = new NestedHost(), data = fixtures();
  data.providers.find(provider => provider.id === 'alpaca').connections = [{connected: true, environment: 'paper', scopes: ['data', 'trading']}];
  const mounted = [], lifecycle = {refreshes: 0, destroys: 0};
  const control = mount(host, {search: '', api: async path => path === '/api/brokers' ? data : {disconnected: true},
    paperModule: {mount(paperHost, options) {
      mounted.push(paperHost); assert.equal(typeof options.api, 'function'); assert.equal(options.isCurrent(), true);
      paperHost.innerHTML = '<input value="synthetic unsent draft">';
      return {refresh: async () => { lifecycle.refreshes++; }, destroy: () => { lifecycle.destroys++; }};
    }}});
  await control.ready;
  const firstHost = host.paper;
  host.change({brokerEnvironment: 'alpaca'}, 'live');
  await control.refresh();
  assert.equal(mounted.length, 1);
  assert.equal(host.paper, firstHost);
  assert.match(host.paper.innerHTML, /synthetic unsent draft/);
  await host.click(host.button('disconnect', 'alpaca', 'paper'));
  assert.equal(lifecycle.refreshes, 1);
  assert.equal(host.paper, firstHost);
  control.destroy();
  assert.equal(lifecycle.destroys, 1);
});
