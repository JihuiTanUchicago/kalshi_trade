import assert from './assert_text.mjs';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/static/kalshi-perps-live.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../app/static/kalshi-perps-live.css', import.meta.url), 'utf8');
const BASE = '/api/kalshi/perps/live';
const NOW = Date.parse('2026-10-23T12:00:00Z');
const clone = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; };
const policy = (changes = {}) => ({enabled: true, version: 3, manual_confirmation_required: true, risk_mode: 'kalshi_limits', ...changes});
const order = (changes = {}) => ({id: 12, environment: 'production', source: 'user', status: 'draft', version: 1,
  request_hash: 'ab'.repeat(32), request: {ticker: 'SYNTHBTC', side: 'bid', count: '2', price: '8.125', time_in_force: 'immediate_or_cancel', reduce_only: false},
  filled_count: '0', remaining_count: '2', filled_avg_price: null, total_fees: null,
  created_at: '2026-10-23T12:00:00Z', expires_at: '2026-10-23T12:02:00Z',
  preview: {contract_multiplier: '0.0001', btc_quantity: '0.0002', notional_usd: '16.25', estimated_fee_usd: '0.0195',
    taker_fee_rate: '0.0012', account_equity: '100.5', available_balance: '80.5', account_leverage: '2.5', quoted_at: '2026-10-23T12:00:00Z'}, error_code: null, ...changes});
const overview = (changes = {}) => ({enabled: true, environment: 'production', policy: policy(), connected: true, eligible: true,
  account: {account_equity: '100.5', available_balance: '80.5', initial_margin: '20', maintenance_margin: '10', settled_funds: '100.5'},
  risk: {account_leverage: '2.5', total_position_notional: '251.25'},
  market: {ticker: 'SYNTHBTC', title: '0.0001 BTC', contract_multiplier: '0.0001', tick_size: '0.0001', market_version: 1},
  quote: {bid: '8.1249', ask: '8.125', retrieved_at: '2026-10-23T12:00:00Z'}, fees: {taker_rate: '0.0012'},
  positions: [{ticker: 'SYNTHBTC', position: '-3'}], orders: [], ...changes});

class Host {
  constructor() { this.isConnected = true; this.html = ''; this.writes = 0; this.members = new Set(); this.attributes = {}; }
  get innerHTML() { return this.html; }
  set innerHTML(value) { this.html = value; this.writes++; this.members.clear(); }
  contains(node) { return this.members.has(node); }
  setAttribute(key, value) { this.attributes[key] = value; }
  button(action, id) {
    const tag = [...this.html.matchAll(/<button\b([^>]*)>/g)].map(match => match[1])
      .find(value => value.includes(`data-perps-action="${action}"`) && (id === undefined || value.includes(`data-perps-id="${id}"`)));
    assert.ok(tag, `rendered ${action} ${id || ''} button`);
    const inherited = action === 'preview' && /class="kp-ticket"[^>]*><fieldset disabled/.test(this.html);
    const node = {disabled: /\sdisabled(?:\s|$)/.test(tag) || inherited, dataset: {}, closest: () => node};
    for (const [, key, value] of tag.matchAll(/data-([\w-]+)="([^"]*)"/g)) node.dataset[key.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    this.members.add(node); return node;
  }
  click(action, id) { const target = this.button(action, id); return this.onclick({target, preventDefault() {}}); }
  input(field, value) { return this.oninput({target: {dataset: {perpsField: field}, value: String(value), checked: value === true}}); }
  submit() { return this.onsubmit({preventDefault() {}}); }
}

function harness(initial = overview(), respond = null, options = {}) {
  const calls = [], clock = {now: NOW};
  let nextKey = 0;
  class ClockDate extends Date { constructor(...args) { super(...(args.length ? args : [clock.now])); } static now() { return clock.now; } }
  const context = vm.createContext({Date: ClockDate, crypto: {randomUUID: () => 'synthetic-request-' + (++nextKey)},
    setInterval() { assert.fail('No automatic polling'); }, setTimeout() { assert.fail('No automatic retry'); },
    fetch() { assert.fail('All transport must use the supplied authenticated API'); },
    localStorage: {setItem() { assert.fail('No storage'); }, getItem() { assert.fail('No storage'); }}});
  vm.runInContext(source, context);
  const api = async (path, body) => {
    calls.push({path, body: body === undefined ? undefined : clone(body)});
    if (respond) return respond(path, body, calls);
    if (body === undefined) return clone(initial);
    if (path.endsWith('/policy')) return {policy: policy({enabled: body.enabled, version: 4})};
    if (path.endsWith('/submit')) return {order: order({status: 'filled', version: 3, filled_count: '2', remaining_count: '0', filled_avg_price: '8.125', total_fees: '0.0195'})};
    if (path.endsWith('/refresh')) return {order: order({status: 'unknown', version: 3})};
    if (path.endsWith('/cancel')) return {order: order({status: 'canceled', version: 4, remaining_count: '0'})};
    return {order: order()};
  };
  const host = new Host();
  const component = context.TAU_PERPS_LIVE.mount(host, {api, ...options});
  return {host, component, calls, context, api, clock};
}

async function ticket(h, count = '2', price = '8.125') {
  await h.component.ready;
  h.host.input('count', count); h.host.input('price', price);
  await h.host.submit();
}

test('initial opt-in requires explicit real-money acknowledgement and sends no order', async () => {
  const h = harness(overview({policy: policy({enabled: false})}));
  await h.component.ready;
  assert.equal(h.calls.length, 1);
  assert.equal(h.host.button('enable').disabled, true);
  await h.host.click('enable');
  assert.equal(h.calls.length, 1);
  h.host.input('acknowledged', true);
  await h.host.click('enable');
  assert.deepEqual(h.calls[1], {path: BASE + '/policy', body: {enabled: true, expected_version: 3, acknowledge_real_money: true}});
  assert.equal(h.calls.some(call => call.path.includes('/orders')), false);
  assert.match(h.host.html, /Live perps enabled/);
});

test('preview preserves exact count and USD strings and requires a separate confirmation', async () => {
  const h = harness();
  await ticket(h);
  assert.deepEqual(h.calls[1], {path: BASE + '/orders', body: {request_key: 'synthetic-request-1', side: 'bid', count: '2', price: '8.125', reduce_only: false}});
  assert.equal(h.calls.length, 2);
  for (const value of ['$8.125', '0.0002 BTC', '$16.25', '$0.0195', '$80.5', '2.5×']) assert.ok(h.host.html.includes(value), value);
  assert.match(h.host.html, /Confirm live order/);
  assert.match(h.host.html, /Unfilled quantity canceled/);
  await h.host.click('confirm', '12');
  assert.deepEqual(h.calls[2], {path: BASE + '/orders/12/submit', body: {confirmed: true, expected_version: 1, request_hash: 'ab'.repeat(32)}});
  assert.equal(h.calls.length, 3);
  assert.match(h.host.html, /Filled/);
  assert.match(h.host.html, /Actual fees/);
  assert.doesNotMatch(h.host.html, /data-perps-action="confirm"/);
});

test('whole quantities beyond JS safe integers and high precision prices have no Tau cap or rounding', async () => {
  const count = '9007199254740993', price = '8.123456789012345678';
  const h = harness(overview({account: {account_equity: '0', available_balance: '0'}, risk: {account_leverage: '100'}}),
    async (path, body) => body === undefined ? overview({account: {account_equity: '0', available_balance: '0'}, risk: {account_leverage: '100'}})
      : {order: order({request: {...order().request, count, price}})});
  await ticket(h, count, price);
  assert.equal(h.calls[1].body.count, count);
  assert.equal(h.calls[1].body.price, price);
  assert.match(h.host.html, /9,007,199,254,740,993/);
  assert.match(h.host.html, /\$8\.123456789012345678/);
  assert.equal(h.host.button('confirm', '12').disabled, false);
  assert.doesNotMatch(h.host.html, /leverage.*(?:input|slider)/);
});

test('reduce-only is explicit and part of the immutable preview request', async () => {
  const h = harness();
  await h.component.ready;
  h.host.input('side', 'ask'); h.host.input('count', '2'); h.host.input('price', '8.125'); h.host.input('reduce_only', true);
  await h.host.submit();
  assert.equal(h.calls[1].body.side, 'ask');
  assert.equal(h.calls[1].body.reduce_only, true);
});

for (const [field, value] of [['count', '0'], ['count', '-1'], ['count', '1.5'], ['price', '0'], ['price', '-1'], ['price', '1e3']]) {
  test(`invalid ${field}=${value} sends no preview`, async () => {
    const h = harness(); await h.component.ready;
    h.host.input('count', '2'); h.host.input('price', '8.125'); h.host.input(field, value);
    await h.host.submit();
    assert.equal(h.calls.length, 1);
    assert.match(h.host.html, /positive whole contracts/);
  });
}

test('connected, eligibility and global/per-user gates prevent previews and confirmations', async () => {
  for (const change of [{connected: false}, {eligible: false}, {enabled: false}, {policy: policy({enabled: false})}, {account: null}, {risk: null}]) {
    const h = harness(overview(change));
    await h.component.ready;
    h.host.input('count', '2'); h.host.input('price', '8.125'); await h.host.submit();
    assert.equal(h.calls.length, 1);
    assert.equal(h.host.button('preview').disabled, true);
  }
  const disconnected = harness(overview({connected: false})); await disconnected.component.ready;
  assert.match(disconnected.host.html, /href="\/settings\/account"/);
  const ineligible = harness(overview({eligible: false})); await ineligible.component.ready;
  assert.match(ineligible.host.html, /https:\/\/help\.kalshi\.com\/en\/articles\/15357656-applying-for-perpetuals-access/);
});

test('missing account/risk/quote values are unavailable, never manufactured as zero', async () => {
  const h = harness(overview({account: null, risk: null, quote: null})); await h.component.ready;
  assert.match(h.host.html, /Unavailable/);
  assert.doesNotMatch(h.host.html, /\$0(?:<|\s)/);
  assert.match(h.host.html, /Last retrieved account/);
});

test('nonproduction or nonmanual policy DTO fails closed', async () => {
  for (const data of [overview({environment: 'demo'}), overview({policy: policy({manual_confirmation_required: false})})]) {
    const h = harness(data); await h.component.ready;
    assert.match(h.host.html, /Could not refresh live perps/);
    assert.doesNotMatch(h.host.html, /data-perps-action="confirm"|data-perps-ticket/);
  }
});

test('two confirm clicks while busy send one exact submit', async () => {
  const wait = deferred();
  const h = harness(overview(), (path, body) => body === undefined ? overview() : path.endsWith('/submit') ? wait.promise : {order: order()});
  await ticket(h);
  const target = h.host.button('confirm', '12');
  const first = h.host.onclick({target, preventDefault() {}});
  assert.equal(h.host.attributes['aria-busy'], 'true');
  // A second click already queued on the original button still hits the busy gate.
  h.host.members.add(target);
  await h.host.onclick({target, preventDefault() {}});
  assert.equal(h.calls.filter(call => call.path.endsWith('/submit')).length, 1);
  wait.resolve({order: order({status: 'unknown', version: 3})}); await first;
  assert.match(h.host.html, /Check status/);
});

test('unknown preview economics disable confirmation without manufacturing values', async () => {
  const h = harness(overview(), (path, body) => body === undefined ? overview()
    : {order: order({preview: {...order().preview, available_balance: null, account_leverage: null, estimated_fee_usd: null}})});
  await ticket(h);
  assert.equal(h.host.button('confirm', '12').disabled, true);
  assert.match(h.host.html, /Preview details are unavailable/);
  assert.match(h.host.html, /Estimated fee<\/dt><dd>Unavailable/);
});

test('duplicate preview clicks use one request and existing request key', async () => {
  const wait = deferred();
  const h = harness(overview(), (path, body) => body === undefined ? overview() : wait.promise);
  await h.component.ready;
  h.host.input('count', '2'); h.host.input('price', '8.125');
  const first = h.host.submit(); await h.host.submit();
  assert.equal(h.calls.length, 2);
  wait.resolve({order: order()}); await first;
});

test('uncertain submission offers status refresh and never re-arms after draft refresh or remount', async () => {
  const h = harness(overview(), async (path, body) => {
    if (body === undefined) return overview({orders: [order()]});
    if (path.endsWith('/submit')) throw new Error('PRIVATE RAW PROVIDER ERROR');
    return {order: order()};
  });
  await ticket(h); await h.host.click('confirm', '12');
  assert.match(h.host.html, /Submission is unconfirmed/);
  assert.doesNotMatch(h.host.html, /PRIVATE RAW/);
  assert.doesNotMatch(h.host.html, /data-perps-action="confirm"/);
  await h.host.click('check', '12');
  await h.component.refresh();
  assert.doesNotMatch(h.host.html, /data-perps-action="confirm"/);
  const newer = h.context.TAU_PERPS_LIVE.mount(h.host, {api: h.api}); await newer.ready;
  assert.doesNotMatch(h.host.html, /data-perps-action="confirm"/);
  assert.equal(h.calls.filter(call => call.path.endsWith('/submit')).length, 1);
  assert.equal(h.calls.filter(call => call.path.endsWith('/orders')).length, 1);
});

test('expired preview cannot submit and explicit fresh preview uses a new key without sending', async () => {
  let previews = 0;
  const h = harness(overview(), (path, body) => body === undefined ? overview() : {
    order: order({id: ++previews === 1 ? 12 : 13, expires_at: previews === 1 ? '2026-10-23T12:02:00Z' : '2026-10-23T12:05:00Z'})});
  await ticket(h);
  h.clock.now += 121000;
  await h.host.click('confirm', '12');
  assert.equal(h.calls.length, 2);
  assert.match(h.host.html, /preview expired/);
  await h.host.click('new-preview', '12');
  assert.notEqual(h.calls[1].body.request_key, h.calls[2].body.request_key);
  assert.equal(h.calls.filter(call => call.path.endsWith('/submit')).length, 0);
});

test('editing a ticket removes the previous confirmation before another preview', async () => {
  const h = harness(); await ticket(h);
  h.host.input('count', '3');
  assert.doesNotMatch(h.host.html, /data-perps-action="confirm"/);
  assert.equal(h.calls.length, 2);
});

test('an immutable agent proposal is previewed once, and confirmation is a separate click', async () => {
  const proposed = order({source: 'agent', request: {...order().request, side: 'ask', count: '3', reduce_only: true}});
  const h = harness(overview(), (path, body) => body === undefined ? overview() : {order: proposed}, {proposalId: 73});
  await h.component.ready;
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].path, BASE + '/proposals/73/preview');
  assert.deepEqual(Object.keys(h.calls[1].body), ['request_key']);
  assert.match(h.host.html, /Sell SYNTHBTC · Agent proposal/);
  assert.match(h.host.html, /Reduce only/);
  assert.equal(h.calls.filter(call => call.path.endsWith('/submit')).length, 0);
  await h.host.click('confirm', '12');
  assert.deepEqual(h.calls[2].body, {confirmed: true, expected_version: 1, request_hash: 'ab'.repeat(32)});
});

test('failed proposal preview never automatically retries when the account is refreshed', async () => {
  const h = harness(overview(), (path, body) => body === undefined ? overview() : Promise.reject(new Error('preview failed')), {proposalId: 73});
  await h.component.ready;
  await h.component.refresh();
  assert.equal(h.calls.filter(call => call.path.includes('/proposals/')).length, 1);
  assert.match(h.host.html, /Review agent order/);
});

test('failed preview requires explicit refresh and keeps its idempotency key', async () => {
  let failed = false;
  const h = harness(overview(), (path, body) => {
    if (body === undefined) return overview();
    if (!failed) { failed = true; throw new Error('PRIVATE SECRET'); }
    return {order: order()};
  });
  await ticket(h); assert.match(h.host.html, /Preview was not confirmed/);
  await h.host.submit(); assert.equal(h.calls.length, 2);
  await h.component.refresh(); await h.host.submit();
  assert.equal(h.calls[1].body.request_key, h.calls[3].body.request_key);
  assert.doesNotMatch(h.host.html, /PRIVATE SECRET/);
});

test('manual cancellation targets one owned remainder and uncertain cancel never retries', async () => {
  const accepted = order({status: 'accepted', version: 4});
  const h = harness(overview({orders: [accepted]}), (path, body) => {
    if (body === undefined) return overview({orders: [accepted]});
    if (path.endsWith('/cancel')) throw new Error('cancel uncertain');
    return {order: accepted};
  });
  await h.component.ready;
  assert.equal(h.calls.length, 1);
  await h.host.click('cancel', '12');
  assert.deepEqual(h.calls[1], {path: BASE + '/orders/12/cancel', body: {confirmed: true, expected_version: 4, request_hash: 'ab'.repeat(32)}});
  assert.doesNotMatch(h.host.html, /data-perps-action="cancel"/);
  await h.host.click('check', '12');
  assert.doesNotMatch(h.host.html, /data-perps-action="cancel"/);
  assert.equal(h.calls.filter(call => call.path.endsWith('/cancel')).length, 1);
});

test('positive fills with unknown economics stay unavailable; partial and unfilled are distinct', async () => {
  const partial = order({status: 'partial', filled_count: '1', remaining_count: '0', filled_avg_price: null, total_fees: null});
  const h = harness(overview({orders: [partial, order({id: 13, status: 'canceled', filled_count: '0', remaining_count: '0'})]}));
  await h.component.ready;
  assert.match(h.host.html, /Partially filled · remainder canceled/);
  assert.match(h.host.html, /Unfilled · canceled/);
  await h.host.click('review', '12');
  assert.match(h.host.html, /Average fill \/ contract<\/dt><dd>Unavailable/);
  assert.match(h.host.html, /Actual fees<\/dt><dd>Unavailable/);
  assert.doesNotMatch(h.host.html, /data-perps-action="confirm"/);
});

test('unknown fixed status and ticker are escaped and cannot acquire a confirm action', async () => {
  const unsafe = order({status: '<img src=x onerror=bad()>', request: {...order().request, ticker: '<script>bad()</script>'}});
  const h = harness(overview({orders: [unsafe]})); await h.component.ready;
  assert.match(h.host.html, /&lt;img/);
  assert.match(h.host.html, /&lt;script&gt;/);
  assert.doesNotMatch(h.host.html, /<img|<script|data-perps-action="confirm"/);
});

test('destroyed or disconnected mount ignores late account and proposal responses', async () => {
  for (const detach of [false, true]) {
    const wait = deferred();
    const h = harness(overview(), () => wait.promise, {proposalId: 73});
    const writes = h.host.writes;
    if (detach) h.host.isConnected = false; else h.component.destroy();
    wait.resolve(overview()); await h.component.ready;
    assert.equal(h.host.writes, writes);
    assert.equal(h.calls.length, 1);
  }
});

test('remount invalidates older response and old destroy cannot remove new handlers', async () => {
  const wait = deferred();
  const h = harness(overview(), () => wait.promise);
  const newer = h.context.TAU_PERPS_LIVE.mount(h.host, {api: async () => overview({policy: policy({enabled: false})})});
  await newer.ready;
  const html = h.host.html;
  h.component.destroy();
  assert.equal(typeof h.host.onclick, 'function');
  wait.resolve(overview()); await h.component.ready;
  assert.equal(h.host.html, html);
});

test('late submit result does not render over a newer Funds component', async () => {
  const wait = deferred();
  const h = harness(overview(), (path, body) => body === undefined ? overview() : path.endsWith('/submit') ? wait.promise : {order: order()});
  await ticket(h); const action = h.host.click('confirm', '12');
  const newer = h.context.TAU_PERPS_LIVE.mount(h.host, {api: async () => overview({policy: policy({enabled: false})})}); await newer.ready;
  const html = h.host.html;
  wait.resolve({order: order({status: 'filled', filled_count: '2', remaining_count: '0'})}); await action;
  assert.equal(h.host.html, html);
});

test('disabling opt-in never cancels orders or adopts positions', async () => {
  const h = harness(overview({orders: [order({status: 'accepted'})]})); await h.component.ready;
  await h.host.click('disable');
  assert.deepEqual(h.calls[1], {path: BASE + '/policy', body: {enabled: false, expected_version: 3}});
  assert.equal(h.calls.length, 2);
  assert.match(h.host.html, /Existing orders and positions are unchanged/);
});

test('failed account refresh disables ordering; no timers, direct fetch or credential storage are present', async () => {
  let loads = 0;
  const h = harness(overview(), () => ++loads === 1 ? overview() : Promise.reject(new Error('PRIVATE SECRET')));
  await h.component.ready; await h.component.refresh();
  assert.equal(h.host.button('preview').disabled, true);
  assert.doesNotMatch(h.host.html, /PRIVATE SECRET/);
  assert.doesNotMatch(source, /setInterval\s*\(|setTimeout\s*\(|\bfetch\s*\(|localStorage|sessionStorage/);
  assert.doesNotMatch(h.host.html, /name="(?:private_key|api_key|password)"/);
  assert.match(css, /var\(--rule\)/);
  assert.match(css, /var\(--stock-raised\)/);
  assert.match(css, /@media/);
  assert.match(h.host.html, /aria-label="Bitcoin perpetual limit order"/);
});
