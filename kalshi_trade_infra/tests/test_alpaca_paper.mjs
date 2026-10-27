import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const {mount} = require('../app/static/alpaca-paper.js');
const BASE = '/api/brokers/alpaca/paper';
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
const order = (changes = {}) => ({id: 12, client_order_id: 'tau-paper-synthetic', source: 'user', status: 'draft', broker_status: null,
  symbol: 'AAPL', side: 'buy', qty: '2', limit_price: '100.25', time_in_force: 'day', filled_qty: '0', filled_avg_price: null,
  created_at: '2026-10-18T12:00:00Z', error_code: null, ...changes});
const overview = (changes = {}) => ({environment: 'paper', enabled: true, connected: true, trading_authorized: true,
  account: {status: 'ACTIVE', currency: 'USD', cash: '25000', buying_power: '50000', equity: '25200', portfolio_value: '25200'},
  positions: [{symbol: 'SPY', qty: '2', avg_entry_price: '100', market_value: '200', unrealized_pl: '0'}],
  orders: [], limits: {max_order_notional_usd: '500'}, as_of: '2026-10-18T12:00:00Z', ...changes});

// Synthetic DOM host; no credentials, HTTP, account or broker session is used.
class Host {
  constructor() { this.isConnected = true; this.html = ''; this.writes = 0; this.members = new Set(); this.attributes = {}; }
  get innerHTML() { return this.html; }
  set innerHTML(value) { this.html = value; this.writes++; this.members.clear(); }
  setAttribute(key, value) { this.attributes[key] = value; }
  contains(element) { return this.members.has(element); }
  button(action, id) {
    const tag = [...this.html.matchAll(/<button\b([^>]*)>/g)].map(match => match[1]).find(value => value.includes(`data-paper-action="${action}"`) && (id === undefined || value.includes(`data-paper-id="${id}"`)));
    assert.ok(tag, `rendered ${action} ${id || ''} button`);
    const button = {disabled: /\sdisabled(?:\s|$)/.test(tag), dataset: {}, closest: () => button};
    for (const [, key, value] of tag.matchAll(/data-([\w-]+)="([^"]*)"/g)) button.dataset[key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
    this.members.add(button); return button;
  }
  click(button) { return this.onclick({target: button, preventDefault() {}}); }
  input(field, value) { return this.oninput({target: {dataset: {paperField: field}, value}}); }
  ticket(symbol = 'AAPL', qty = '2', price = '100.25', side = 'buy') {
    this.input('symbol', symbol); this.input('qty', qty); this.input('limit_price', price); this.input('side', side);
  }
}
const options = api => ({api, randomUUID: () => 'synthetic-request-0001'});

test('browser export uses only authenticated Tau endpoints and no credential storage or live selector', async () => {
  const source = readFileSync(new URL('../app/static/alpaca-paper.js', import.meta.url), 'utf8');
  const context = vm.createContext({Intl, Date, URL});
  vm.runInContext(source, context);
  assert.equal(typeof context.TauAlpacaPaper.mount, 'function');
  assert.doesNotMatch(source, /localStorage|sessionStorage|https:\/\/|fetch\(/);
  const host = new Host(), paths = [];
  const control = mount(host, options(async path => { paths.push(path); return overview(); }));
  await control.ready;
  assert.deepEqual(paths, [BASE]);
  assert.match(host.innerHTML, /Broker-simulated US equities\. Separate from Tau’s Kalshi practice balance/);
  assert.match(host.innerHTML, /Cash|Buying power|Equity|Average entry|Unrealized P&amp;L/);
  assert.match(host.innerHTML, /\$25,000\.00/);
  assert.doesNotMatch(host.innerHTML, /value="live"|Live account|Deposit/);
  assert.equal(host.button('review').disabled, false);
});

test('missing consent, disconnected accounts, disabled server and inactive accounts fail closed', async () => {
  for (const [patch, message] of [
    [{connected: false, account: null}, /Connect an Alpaca paper account/],
    [{trading_authorized: false}, /Reconnect with Paper selected/],
    [{enabled: false, account: null}, /not enabled on this server/],
    [{account: {status: 'ACCOUNT_UPDATED', currency: 'USD'}}, /not ready for orders/],
    [{limits: {}}, /order limit is unavailable/],
  ]) {
    const host = new Host(), calls = [];
    const control = mount(host, options(async (path, body) => { calls.push({path, body}); return overview(patch); }));
    await control.ready;
    assert.match(host.innerHTML, message);
    const button = host.button('review');
    assert.equal(button.disabled, true);
    button.disabled = false; host.ticket(); await host.click(button);
    assert.equal(calls.length, 1);
  }
});

test('whole-share, price tick and maximum-notional validation leaves the ticket intact', async () => {
  const host = new Host(), calls = [];
  const control = mount(host, options(async path => { calls.push(path); return overview(); }));
  await control.ready;
  for (const [symbol, qty, price, message] of [
    ['<SPY>', '1', '100', /valid US stock symbol/],
    ['SPY', '1.5', '100', /positive whole-share quantity/],
    ['SPY', '1', '1e2', /positive limit price/],
    ['SPY', '1', '100.125', /two decimal places/],
    ['SPY', '6', '100', /per-order notional limit/],
  ]) {
    host.ticket(symbol, qty, price);
    await host.click(host.button('review'));
    assert.match(host.innerHTML, message);
    assert.ok(host.innerHTML.includes(`value="${qty}"`));
  }
  assert.equal(calls.length, 1);
});

test('review saves a draft with exact order details; explicit submit is required and does not infer a fill', async () => {
  const host = new Host(), calls = [];
  const control = mount(host, options(async (path, body) => {
    calls.push({path, body});
    if (path === BASE) return overview();
    if (path.endsWith('/submit')) return {order: order({status: 'submitted', broker_status: 'new'})};
    return {order: order()};
  }));
  await control.ready; host.ticket('aapl');
  await host.click(host.button('review'));
  assert.deepEqual(calls[1], {path: BASE + '/orders', body: {request_key: 'synthetic-request-0001', symbol: 'AAPL', side: 'buy', qty: '2', limit_price: '100.25'}});
  assert.equal(calls.length, 2);
  assert.match(host.innerHTML, /Awaiting approval/);
  assert.match(host.innerHTML, /Buy 2 AAPL/);
  assert.match(host.innerHTML, /Limit \$100\.25 · DAY · <span>Maximum notional \$200\.50/);
  assert.match(host.innerHTML, /Submit paper order/);
  await host.click(host.button('submit', 12));
  assert.deepEqual(calls[2], {path: BASE + '/orders/12/submit', body: {}});
  assert.match(host.innerHTML, /alpaca-paper-state">Open/);
  assert.match(host.innerHTML, /0 filled/);
  assert.doesNotMatch(host.innerHTML, /alpaca-paper-state">Filled/);
});

test('double review clicks create one request and an ambiguous failure reuses the request key through refresh', async () => {
  const host = new Host(), pending = deferred(), calls = [];
  let keys = 0, creates = 0;
  const control = mount(host, {randomUUID: () => 'synthetic-request-' + (++keys), api: async (path, body) => {
    calls.push({path, body});
    if (path === BASE) return overview();
    if (++creates === 1) return pending.promise;
    return {order: order()};
  }});
  await control.ready; host.ticket();
  const first = host.click(host.button('review'));
  const duplicate = host.button('review'); duplicate.disabled = false;
  await host.click(duplicate);
  assert.equal(calls.length, 2);
  pending.reject(new Error('private token response'));
  await first;
  assert.match(host.innerHTML, /ticket is preserved/);
  assert.doesNotMatch(host.innerHTML, /private token response/);
  await control.refresh();
  assert.match(host.innerHTML, /data-paper-field="symbol" value="AAPL"/);
  await host.click(host.button('review'));
  assert.equal(keys, 1);
  assert.equal(calls[1].body.request_key, calls[3].body.request_key);
  host.input('limit_price', '99.25');
  await host.click(host.button('review'));
  assert.equal(keys, 2);
  assert.notEqual(calls[3].body.request_key, calls[4].body.request_key);
});

test('submit ambiguity offers status reconciliation without another submission button', async () => {
  const host = new Host(), calls = [];
  const control = mount(host, options(async (path, body) => {
    calls.push({path, body});
    if (path === BASE) return overview({orders: [order()]});
    if (path.endsWith('/submit')) throw new Error('raw broker body');
    return {order: order({status: 'submitted', broker_status: 'partially_filled', filled_qty: '1', filled_avg_price: '100'})};
  }));
  await control.ready;
  await host.click(host.button('submit', 12));
  assert.match(host.innerHTML, /Submission unconfirmed/);
  assert.doesNotMatch(host.innerHTML, /data-paper-action="submit"|raw broker body/);
  await host.click(host.button('check', 12));
  assert.equal(calls.filter(call => call.path.endsWith('/submit')).length, 1);
  assert.deepEqual(calls[2], {path: BASE + '/orders/12/refresh', body: {}});
  assert.match(host.innerHTML, /Partially filled/);
  assert.match(host.innerHTML, /1 \/ 2 filled at \$100\.00/);
});

test('agent drafts use the same approval path and only broker status establishes filled', async () => {
  const host = new Host();
  const control = mount(host, options(async path => path === BASE ? overview({orders: [order({source: 'agent', proposal_id: 44})]})
    : {order: order({source: 'agent', status: 'submitted', broker_status: 'filled', filled_qty: '2', filled_avg_price: '100.10'})}));
  await control.ready;
  assert.match(host.innerHTML, /Agent draft/);
  assert.match(host.innerHTML, /Awaiting approval/);
  await host.click(host.button('submit', 12));
  assert.match(host.innerHTML, /alpaca-paper-state">Filled/);
  assert.match(host.innerHTML, /2 \/ 2 filled at \$100\.10/);
});

test('cancel and status recovery remain available when new submissions are disabled; 204 is not canceled', async () => {
  const host = new Host(), calls = [];
  const control = mount(host, options(async (path, body) => {
    calls.push({path, body});
    if (path === BASE) return overview({enabled: false, account: null, orders: [order({status: 'submitted', broker_status: 'new'})]});
    return {order: order({status: path.endsWith('/cancel') ? 'cancel_pending' : 'canceled', broker_status: path.endsWith('/cancel') ? 'new' : 'canceled'})};
  }));
  await control.ready;
  assert.equal(host.button('review').disabled, true);
  assert.equal(host.button('cancel', 12).disabled, false);
  await host.click(host.button('cancel', 12));
  assert.match(host.innerHTML, /Cancellation requested/);
  assert.doesNotMatch(host.innerHTML, /alpaca-paper-state">Canceled/);
  assert.match(host.innerHTML, /further fills are possible/);
  await host.click(host.button('check', 12));
  assert.match(host.innerHTML, /alpaca-paper-state">Canceled/);
  assert.equal(calls.length, 3);
});

test('broker fields are escaped and arbitrary provider errors never reach the page', async () => {
  const host = new Host();
  let first = true;
  const control = mount(host, options(async () => {
    if (!first) throw new Error('<script>secret token and account response</script>');
    first = false;
    return overview({orders: [order({symbol: '<img src=x onerror=alert(1)>', source: 'agent'})],
      positions: [{symbol: '<script>bad()</script>', qty: '1', avg_entry_price: '10', market_value: '10', unrealized_pl: '0'}]});
  }));
  await control.ready; host.ticket('SPY');
  await control.refresh();
  assert.match(host.innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(host.innerHTML, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(host.innerHTML, /<img|<script>|secret token and account response/);
  assert.match(host.innerHTML, /last loaded account and orders/);
  assert.match(host.innerHTML, /data-paper-field="symbol" value="SPY"/);
});

test('a live payload or malformed order fails closed with a retryable load error', async () => {
  for (const payload of [overview({environment: 'live'}), overview({orders: [order({id: '../../live'})]}), {orders: []}]) {
    const host = new Host(), control = mount(host, options(async () => payload));
    await control.ready;
    assert.match(host.innerHTML, /Could not load Alpaca paper trading/);
    assert.doesNotMatch(host.innerHTML, /data-paper-action="review"|data-paper-action="submit"/);
  }
});

test('late overview responses and late action results cannot rewrite a disposed or navigated page', async () => {
  for (const mode of ['destroy', 'route', 'detached']) {
    const host = new Host(), pending = deferred(); let current = true;
    const control = mount(host, {...options(() => pending.promise), isCurrent: () => current});
    const writes = host.writes;
    if (mode === 'destroy') control.destroy();
    if (mode === 'route') current = false;
    if (mode === 'detached') host.isConnected = false;
    pending.resolve(overview()); await control.ready;
    assert.equal(host.writes, writes);
  }
  const host = new Host(), pending = deferred();
  const control = mount(host, options(path => path === BASE ? Promise.resolve(overview({orders: [order()]})) : pending.promise));
  await control.ready;
  const submit = host.click(host.button('submit', 12)), writes = host.writes;
  control.destroy(); pending.resolve({order: order({status: 'submitted'})}); await submit;
  assert.equal(host.writes, writes);
  for (const event of ['onclick', 'oninput', 'onchange', 'onsubmit']) assert.equal(host[event], null);
});

test('repeated submission clicks issue one request while in flight', async () => {
  const host = new Host(), pending = deferred(), calls = [];
  const control = mount(host, options(async path => { calls.push(path); return path === BASE ? overview({orders: [order()]}) : pending.promise; }));
  await control.ready;
  const first = host.click(host.button('submit', 12));
  const duplicate = host.button('submit', 12); duplicate.disabled = false;
  await host.click(duplicate);
  assert.equal(calls.length, 2);
  pending.resolve({order: order({status: 'submitted', broker_status: 'new'})}); await first;
});
