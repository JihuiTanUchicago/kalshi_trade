/* Per-user Alpaca paper account. All transport stays on Tau's authenticated API. */
(function (root, factory) {
  'use strict';
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TauAlpacaPaper = api;
})(typeof globalThis === 'object' ? globalThis : this, function (root) {
  'use strict';
  const BASE = '/api/brokers/alpaca/paper';
  const TERMINAL = new Set(['filled', 'canceled', 'expired', 'rejected']);
  const LOCAL_STATES = new Set(['draft', 'submitting', 'submitted', 'unknown', 'rejected', 'cancel_pending', 'canceled']);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
  const numeric = value => (typeof value === 'string' || typeof value === 'number') && String(value).trim() !== '' && Number.isFinite(Number(value));
  const money = value => numeric(value) ? Number(value).toLocaleString('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4}) : '—';
  const number = value => numeric(value) ? Number(value).toLocaleString('en-US', {maximumFractionDigits: 6}) : '—';
  const text = value => typeof value === 'string' ? value.slice(0, 120) : '';
  let mounts = 0;

  function normalizeOrder(value) {
    if (!value || !/^[1-9][0-9]{0,19}$/.test(String(value.id)) || !LOCAL_STATES.has(value.status)
        || !['buy', 'sell'].includes(value.side) || value.time_in_force !== 'day'
        || !numeric(value.qty) || Number(value.qty) <= 0 || !numeric(value.limit_price) || Number(value.limit_price) <= 0) throw new Error('Invalid paper order');
    return {id: String(value.id), source: value.source === 'agent' ? 'agent' : 'user', status: value.status,
      broker_status: text(value.broker_status), symbol: text(value.symbol), side: value.side,
      qty: String(value.qty), limit_price: String(value.limit_price), time_in_force: 'day',
      filled_qty: numeric(value.filled_qty) ? String(value.filled_qty) : '0',
      filled_avg_price: numeric(value.filled_avg_price) ? String(value.filled_avg_price) : null,
      created_at: text(value.created_at), error_code: text(value.error_code)};
  }

  function normalizeOverview(value) {
    if (!value || value.environment !== 'paper' || !Array.isArray(value.orders) || !Array.isArray(value.positions)) throw new Error('Invalid paper account');
    const limit = value.limits && value.limits.max_order_notional_usd;
    return {enabled: value.enabled === true, connected: value.connected === true,
      trading_authorized: value.trading_authorized === true,
      account: value.account && typeof value.account === 'object' ? value.account : null,
      positions: value.positions.filter(row => row && typeof row === 'object'), orders: value.orders.map(normalizeOrder),
      limit: numeric(limit) && Number(limit) > 0 ? Number(limit) : null, as_of: text(value.as_of)};
  }

  function orderState(order) {
    if (['draft', 'submitting', 'unknown', 'cancel_pending', 'rejected', 'canceled'].includes(order.status)) return order.status;
    return order.broker_status || order.status;
  }

  function mount(host, options) {
    if (!host || !options || typeof options.api !== 'function') throw new Error('Paper account host and API are required');
    const prefix = 'alpaca-paper-' + (++mounts);
    const request = options.api;
    const current = () => !disposed && host.isConnected !== false && (!options.isCurrent || options.isCurrent());
    const uuid = options.randomUUID || (() => root.crypto.randomUUID());
    const fields = {symbol: '', side: 'buy', qty: '1', limit_price: ''};
    let data = null, disposed = false, loading = false, pending = '', error = '', notice = '', requestKey = '', sequence = 0;

    function canTrade() {
      return !!(data && data.enabled && data.connected && data.trading_authorized && data.account
        && data.account.status === 'ACTIVE' && data.account.currency === 'USD' && data.limit);
    }

    function gateMessage() {
      if (!data) return '';
      if (!data.enabled) return 'Paper order submission is not enabled on this server.';
      if (!data.connected) return 'Connect an Alpaca paper account above to begin.';
      if (!data.trading_authorized) return 'Reconnect with Paper selected and “Authorize trading at Alpaca” checked to place paper orders.';
      if (!data.account || data.account.status !== 'ACTIVE' || data.account.currency !== 'USD') return 'The Alpaca paper account is not ready for orders. Refresh or check the account at Alpaca.';
      if (!data.limit) return 'The paper order limit is unavailable. Refresh before placing an order.';
      return '';
    }

    function ticketHtml() {
      const disabled = !canTrade() || !!pending;
      return `<form class="alpaca-paper-ticket" data-paper-ticket aria-label="Paper equity order">
        <fieldset${disabled ? ' disabled' : ''}><legend class="vh">New paper equity order</legend>
          <label class="field"><span>Symbol</span><input type="text" data-paper-field="symbol" value="${esc(fields.symbol)}" maxlength="10" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="AAPL" aria-label="Stock symbol" required></label>
          <label class="field"><span>Side</span><select data-paper-field="side"><option value="buy"${fields.side === 'buy' ? ' selected' : ''}>Buy</option><option value="sell"${fields.side === 'sell' ? ' selected' : ''}>Sell</option></select></label>
          <label class="field"><span>Shares</span><input type="text" data-paper-field="qty" value="${esc(fields.qty)}" inputmode="numeric" pattern="[1-9][0-9]*" autocomplete="off" aria-label="Whole shares" required></label>
          <label class="field"><span>Limit · USD</span><input type="text" data-paper-field="limit_price" value="${esc(fields.limit_price)}" inputmode="decimal" autocomplete="off" placeholder="0.00" aria-label="Limit price in US dollars" required></label>
          <button class="btn primary" type="submit" data-paper-action="review"${disabled ? ' disabled' : ''}>${pending === 'review' ? 'Saving draft…' : 'Review paper order'}</button>
        </fieldset>
        <p class="hint">Whole-share limit orders · DAY · regular session${data && data.limit ? ` · ${money(data.limit)} maximum per order` : ''}.</p>
      </form>`;
    }

    function orderHtml(order) {
      const state = orderState(order), terminal = TERMINAL.has(state);
      const review = order.status === 'draft';
      const disabled = pending ? ' disabled' : '';
      const status = {draft: 'Awaiting approval', submitting: 'Submission in progress', submitted: 'Submitted', unknown: 'Submission unconfirmed', cancel_pending: 'Cancellation requested', partially_filled: 'Partially filled', new: 'Open', accepted: 'Accepted', filled: 'Filled', canceled: 'Canceled', expired: 'Expired', rejected: 'Rejected'}[state] || state.replace(/_/g, ' ');
      const filled = Number(order.filled_qty) > 0 ? `${number(order.filled_qty)} / ${number(order.qty)} filled${order.filled_avg_price ? ` at ${money(order.filled_avg_price)}` : ''}` : '0 filled';
      return `<article class="alpaca-paper-order${review ? ' alpaca-paper-review' : ''}" data-paper-order="${esc(order.id)}" aria-label="${esc(order.symbol)} paper order">
        <div class="alpaca-paper-order-main"><div><strong>${order.side === 'buy' ? 'Buy' : 'Sell'} ${number(order.qty)} ${esc(order.symbol)}</strong>${order.source === 'agent' ? `<span class="alpaca-paper-origin">${review ? 'Agent draft' : 'Agent order'}</span>` : ''}<span class="alpaca-paper-state">${esc(status)}</span></div>
          <p>Limit ${money(order.limit_price)} · DAY · <span>${review ? 'Maximum notional' : 'Order notional'} ${money(Number(order.qty) * Number(order.limit_price))}</span>${review ? '' : ` · ${esc(filled)}`}</p>
          ${order.status === 'unknown' ? '<p class="alpaca-paper-warning">Check status before placing another order. The submission may have reached Alpaca.</p>' : order.status === 'cancel_pending' ? '<p class="hint">Cancellation is pending broker confirmation; further fills are possible.</p>' : ''}
          ${order.status === 'rejected' ? '<p class="alpaca-paper-warning">Alpaca rejected this paper order.</p>' : ''}
        </div><div class="alpaca-paper-order-actions">
          ${review ? `<button class="btn primary sm" type="button" data-paper-action="submit" data-paper-id="${esc(order.id)}"${!canTrade() || pending ? ' disabled' : ''}>Submit paper order<span class="vh">: ${order.side} ${number(order.qty)} ${esc(order.symbol)} at ${money(order.limit_price)}, DAY</span></button>` : `<button class="btn ghost sm" type="button" data-paper-action="check" data-paper-id="${esc(order.id)}"${disabled}>Check status<span class="vh"> for ${esc(order.symbol)}</span></button>`}
          ${!terminal && order.status !== 'cancel_pending' ? `<button class="btn ghost sm" type="button" data-paper-action="cancel" data-paper-id="${esc(order.id)}"${disabled}>${review ? 'Discard draft' : 'Cancel order'}<span class="vh"> for ${esc(order.symbol)}</span></button>` : ''}
        </div></article>`;
    }

    function accountHtml() {
      if (!data || !data.account) return '';
      const account = data.account;
      return `<dl class="alpaca-paper-balances" aria-label="Alpaca simulated balances">${[['Cash', account.cash], ['Buying power', account.buying_power], ['Equity', account.equity]].map(([label, value]) => `<div><dt>${label}</dt><dd>${money(value)}</dd></div>`).join('')}</dl>`;
    }

    function positionsHtml() {
      if (!data || !data.account) return '';
      const rows = data.positions.map(row => `<tr><th scope="row">${esc(text(row.symbol))}</th><td>${number(row.qty)}</td><td>${money(row.avg_entry_price)}</td><td>${money(row.market_value)}</td><td>${money(row.unrealized_pl)}</td></tr>`).join('');
      return `<div class="alpaca-paper-positions"><h5>Positions</h5>${rows ? `<div class="alpaca-paper-table" tabindex="0" role="region" aria-label="Paper positions, scroll horizontally"><table><thead><tr><th scope="col">Symbol</th><th scope="col">Shares</th><th scope="col">Average entry</th><th scope="col">Market value</th><th scope="col">Unrealized P&amp;L</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="hint">No Alpaca paper positions.</p>'}</div>`;
    }

    function render() {
      if (!current()) return;
      const gate = gateMessage();
      const asOf = data && data.as_of ? new Date(data.as_of) : null;
      const time = asOf && Number.isFinite(asOf.getTime()) ? asOf.toLocaleTimeString('en-US', {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : '';
      host.innerHTML = `<div class="alpaca-paper-head"><div><h4 id="${prefix}-title">Alpaca paper trading</h4><p class="hint">Broker-simulated US equities. Separate from Tau’s Kalshi practice balance.</p></div><button class="btn ghost sm" type="button" data-paper-action="refresh"${loading || pending ? ' disabled' : ''}>${loading ? 'Refreshing…' : 'Refresh'}</button></div>
        ${error ? `<p class="alpaca-paper-error" role="alert">${esc(error)}</p>` : notice ? `<p class="alpaca-paper-feedback" role="status">${esc(notice)}</p>` : ''}
        ${loading && !data ? '<p class="hint" role="status">Loading Alpaca paper account…</p>' : ''}
        ${gate ? `<p class="alpaca-paper-gate">${esc(gate)}</p>` : ''}
        ${accountHtml()}
        ${data ? ticketHtml() : ''}
        ${data && data.orders.length ? `<div class="alpaca-paper-orders" aria-label="Paper orders"><h5>Orders</h5>${data.orders.map(orderHtml).join('')}</div>` : data && canTrade() ? '<p class="hint alpaca-paper-empty">No paper orders yet.</p>' : ''}
        ${positionsHtml()}
        ${time ? `<p class="hint alpaca-paper-asof">Account snapshot <time datetime="${esc(data.as_of)}" title="${esc(asOf.toLocaleString())}">${esc(time)}</time>. Refresh for current balances and order status.</p>` : ''}`;
      host.setAttribute('aria-busy', loading || pending ? 'true' : 'false');
      host.setAttribute('aria-labelledby', prefix + '-title');
    }

    async function refresh() {
      if (!current() || loading || pending) return;
      const turn = ++sequence;
      loading = true; error = ''; notice = ''; render();
      try {
        const response = await request(BASE);
        if (!current() || turn !== sequence) return;
        data = normalizeOverview(response);
      } catch (_) {
        if (current() && turn === sequence) error = data ? 'Could not refresh Alpaca paper trading. The last loaded account and orders are shown.' : 'Could not load Alpaca paper trading. Try Refresh.';
      } finally {
        if (current() && turn === sequence) { loading = false; render(); }
      }
    }

    function validateTicket() {
      const symbol = fields.symbol.trim().toUpperCase(), qty = fields.qty.trim(), price = fields.limit_price.trim();
      if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(symbol)) return 'Enter a valid US stock symbol.';
      if (!/^[1-9]\d*$/.test(qty) || !Number.isSafeInteger(Number(qty))) return 'Enter a positive whole-share quantity.';
      if (!/^(?:0|[1-9]\d*)(?:\.\d{1,4})?$/.test(price) || Number(price) <= 0) return 'Enter a positive limit price with up to four decimal places.';
      if (Number(price) >= 1 && (price.split('.')[1] || '').length > 2) return 'Use up to two decimal places for prices of $1 or more.';
      if (!Number.isFinite(Number(qty) * Number(price)) || Number(qty) * Number(price) > data.limit) return 'This paper order exceeds the per-order notional limit.';
      return {symbol, side: fields.side, qty, limit_price: price};
    }

    function upsertOrder(row) {
      const order = normalizeOrder(row);
      const index = data.orders.findIndex(value => value.id === order.id);
      if (index >= 0) data.orders[index] = order;
      else data.orders.unshift(order);
      return order;
    }

    async function review() {
      if (!current() || loading || pending || !canTrade()) return;
      const ticket = validateTicket();
      if (typeof ticket === 'string') { error = ticket; notice = ''; render(); return; }
      try {
        if (!requestKey) requestKey = uuid();
        if (!/^[A-Za-z0-9_-]{8,80}$/.test(requestKey)) throw new Error('No request key');
      } catch (_) { error = 'This browser cannot create a secure paper-order request. Update your browser and try again.'; render(); return; }
      pending = 'review'; error = ''; notice = ''; render();
      try {
        const response = await request(BASE + '/orders', {request_key: requestKey, ...ticket});
        if (!current()) return;
        const order = upsertOrder(response && response.order);
        notice = order.status === 'draft' ? 'Draft saved. Review the exact order below before submitting.' : 'This ticket was already recorded. Check its order status below.';
      } catch (_) {
        if (current()) error = 'Could not save the paper draft. Your ticket is preserved; review it again to retry safely.';
      } finally {
        pending = '';
        if (current()) render();
      }
    }

    async function act(button) {
      if (!current() || button.disabled || pending || loading) return;
      const action = button.dataset.paperAction;
      if (action === 'refresh') return refresh();
      if (action === 'review') return review();
      if (!['submit', 'check', 'cancel'].includes(action) || !data) return;
      const order = data.orders.find(value => value.id === button.dataset.paperId);
      if (!order || (action === 'submit' && (!canTrade() || order.status !== 'draft'))) return;
      if (action === 'cancel' && (TERMINAL.has(orderState(order)) || order.status === 'cancel_pending')) return;
      pending = action + '-' + order.id; error = ''; notice = ''; render();
      try {
        const response = await request(BASE + '/orders/' + encodeURIComponent(order.id) + '/' + (action === 'check' ? 'refresh' : action), {});
        if (!current()) return;
        const result = upsertOrder(response && response.order);
        notice = action === 'submit' ? (result.status === 'unknown' ? 'Submission is unconfirmed. Use Check status to reconcile it.' : 'Paper order recorded. Broker status and filled shares are shown below.') : action === 'cancel' ? (result.status === 'canceled' ? 'Paper draft or order canceled.' : 'Cancellation requested. Check status for broker confirmation.') : 'Order status checked.';
      } catch (_) {
        if (current()) {
          if (action === 'submit') order.status = 'unknown';
          if (action === 'cancel' && order.status !== 'draft') order.status = 'cancel_pending';
          error = action === 'submit' ? 'Could not confirm submission. Check this order’s status before trying another order.' : action === 'cancel' ? 'Could not confirm cancellation. Check this order’s status.' : 'Could not check this paper order. Try again.';
        }
      } finally {
        pending = '';
        if (current()) render();
      }
    }

    host.onclick = event => {
      const button = event.target.closest && event.target.closest('[data-paper-action]');
      if (button && host.contains(button)) { event.preventDefault(); return act(button); }
    };
    host.oninput = host.onchange = event => {
      if (!current() || pending) return;
      const field = event.target.dataset && event.target.dataset.paperField;
      if (!Object.hasOwn(fields, field) || (field === 'side' && !['buy', 'sell'].includes(event.target.value))) return;
      if (fields[field] !== event.target.value) { fields[field] = event.target.value; requestKey = ''; }
    };
    host.onsubmit = event => { event.preventDefault(); return review(); };
    const ready = refresh();
    return {ready, refresh, destroy() { disposed = true; sequence++; host.onclick = null; host.oninput = null; host.onchange = null; host.onsubmit = null; }};
  }
  return {mount};
});
