/* Native perps: explicit previews and owner confirmation, authenticated Tau API only. */
(function (root, factory) {
  'use strict';
  const plugin = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = plugin;
  else root.TAU_PERPS_LIVE = plugin;
})(typeof globalThis === 'object' ? globalThis : this, function (root) {
  'use strict';
  const BASE = '/api/kalshi/perps/live';
  const ACCESS = 'https://help.kalshi.com/en/articles/15357656-applying-for-perpetuals-access';
  const owners = new WeakMap();
  // Survive a component remount during an uncertain POST. No browser storage.
  const attempted = new Set(), uncertain = new Set(), cancelAttempted = new Set();
  const terminal = new Set(['filled', 'partial', 'canceled', 'rejected', 'expired']);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
  const text = value => typeof value === 'string' ? value.slice(0, 240) : '';
  const decimal = value => typeof value === 'string' && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value);
  const positive = value => decimal(value) && !value.startsWith('-') && /[1-9]/.test(value);
  const whole = value => typeof value === 'string' && /^[1-9]\d*$/.test(value);
  const version = value => Number.isSafeInteger(value) && value >= 0;
  const id = value => typeof value === 'number' ? (Number.isSafeInteger(value) && value > 0 ? String(value) : '') : (typeof value === 'string' && /^[1-9]\d{0,19}$/.test(value) ? value : '');
  const exact = value => {
    if (!decimal(value)) return 'Unavailable';
    const [integer, fraction = ''] = value.split('.');
    const tail = fraction.replace(/0+$/, '');
    return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (tail ? '.' + tail : '');
  };
  const money = value => decimal(value) ? (value.startsWith('-') ? '-$' + exact(value.slice(1)) : '$' + exact(value)) : 'Unavailable';
  const leverage = value => decimal(value) ? exact(value) + '×' : 'Unavailable';
  const time = value => {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleTimeString('en-US', {hour: '2-digit', minute: '2-digit', second: '2-digit'}) : 'Unavailable';
  };
  let mounts = 0;

  function policy(value) {
    if (!value || typeof value.enabled !== 'boolean' || !version(value.version)
        || value.manual_confirmation_required !== true || value.risk_mode !== 'kalshi_limits') throw new Error('Invalid policy');
    return {enabled: value.enabled, version: value.version, manual_confirmation_required: true, risk_mode: 'kalshi_limits'};
  }

  function order(value) {
    const request = value && value.request;
    if (!value || !id(value.id) || value.environment !== 'production' || !version(value.version)
        || !/^[0-9a-f]{64}$/.test(value.request_hash) || !['user', 'agent'].includes(value.source)
        || !text(value.status) || !request || !['bid', 'ask'].includes(request.side)
        || !text(request.ticker) || !whole(request.count) || !positive(request.price)
        || request.time_in_force !== 'immediate_or_cancel' || typeof request.reduce_only !== 'boolean') throw new Error('Invalid live order');
    return {id: id(value.id), environment: 'production', source: value.source, status: text(value.status),
      version: value.version, request_hash: value.request_hash,
      request: {ticker: text(request.ticker), side: request.side, count: request.count, price: request.price,
        time_in_force: 'immediate_or_cancel', reduce_only: request.reduce_only},
      preview: value.preview && typeof value.preview === 'object' ? {...value.preview} : {},
      filled_count: decimal(value.filled_count) ? value.filled_count : null,
      remaining_count: decimal(value.remaining_count) ? value.remaining_count : null,
      filled_avg_price: decimal(value.filled_avg_price) ? value.filled_avg_price : null,
      total_fees: decimal(value.total_fees) ? value.total_fees : null,
      expires_at: text(value.expires_at), error_code: text(value.error_code)};
  }

  function overview(value) {
    if (!value || value.environment !== 'production' || typeof value.enabled !== 'boolean'
        || typeof value.connected !== 'boolean' || typeof value.eligible !== 'boolean'
        || !Array.isArray(value.orders) || !Array.isArray(value.positions)) throw new Error('Invalid live account');
    return {enabled: value.enabled, policy: policy(value.policy), connected: value.connected, eligible: value.eligible,
      account: value.account && typeof value.account === 'object' ? value.account : null,
      risk: value.risk && typeof value.risk === 'object' ? value.risk : null,
      market: value.market && typeof value.market === 'object' ? value.market : null,
      quote: value.quote && typeof value.quote === 'object' ? value.quote : null,
      positions: value.positions.filter(row => row && typeof row === 'object'), orders: value.orders.map(order)};
  }

  function mount(host, options) {
    if (!host || !options || typeof options.api !== 'function') throw new Error('Live perps host and API are required');
    const previous = owners.get(host);
    if (previous) previous.destroy();
    const identity = {}, prefix = 'kalshi-perps-' + (++mounts), request = options.api;
    const proposalId = id(options.proposalId);
    const fields = {side: 'bid', count: '1', price: '', reduce_only: false};
    let data = null, disposed = false, loading = false, pending = '', fresh = false, acknowledged = false;
    let error = '', notice = '', reviewId = '', ticketKey = '', proposalKey = '', retrievedAt = '', sequence = 0;
    const current = () => !disposed && owners.get(host) === identity && host.isConnected !== false && (!options.isCurrent || options.isCurrent());
    const canPreview = () => !!(fresh && data && data.enabled && data.policy.enabled && data.connected && data.eligible
      && data.account && data.risk && data.market && text(data.market.ticker) && positive(data.market.contract_multiplier));
    const expired = row => !Number.isFinite(Date.parse(row.expires_at)) || Date.parse(row.expires_at) <= Date.now();
    const previewComplete = row => ['contract_multiplier', 'btc_quantity', 'notional_usd'].every(key => positive(row.preview[key]))
      && ['estimated_fee_usd', 'taker_fee_rate', 'account_equity', 'available_balance', 'account_leverage'].every(key => decimal(row.preview[key]));
    const canConfirm = row => canPreview() && row.status === 'draft' && reviewId === row.id
      && !attempted.has(row.id) && !uncertain.has(row.id) && !expired(row) && previewComplete(row);
    const displayStatus = row => uncertain.has(row.id) || (attempted.has(row.id) && row.status === 'draft') ? 'Submission unconfirmed'
      : ({draft: expired(row) ? 'Preview expired' : 'Preview', approved: 'Awaiting submission', claimed: 'Submission pending',
        accepted: 'Awaiting final fill', unknown: 'Submission unconfirmed', cancel_pending: 'Cancellation unconfirmed',
        rejected: 'Rejected', filled: 'Filled', partial: 'Partially filled · remainder canceled',
        canceled: row.filled_count === '0' && row.error_code !== 'user_canceled' ? 'Unfilled · canceled' : 'Canceled', expired: 'Expired'})[row.status] || row.status;

    function render() {
      if (!current()) return;
      const active = host.ownerDocument && host.ownerDocument.activeElement;
      const focusField = active && host.contains(active) && active.dataset && active.dataset.perpsField;
      const selection = focusField && typeof active.selectionStart === 'number' ? [active.selectionStart, active.selectionEnd] : null;
      const busy = loading || !!pending;
      const account = data && data.account, risk = data && data.risk;
      const selected = data && data.orders.find(row => row.id === reviewId);
      const stats = [['Equity', money(account && account.account_equity)], ['Available balance', money(account && account.available_balance)],
        ['Initial margin', money(account && account.initial_margin)], ['Maintenance margin', money(account && account.maintenance_margin)],
        ['Leverage', leverage(risk && risk.account_leverage)]];
      const gate = !data ? '' : !data.enabled ? 'Live perps are unavailable on this server.'
        : !data.connected ? '<a href="/settings/account">Connect your Kalshi account in Settings</a>.'
          : !data.eligible ? `<a href="${ACCESS}" target="_blank" rel="noopener noreferrer">Apply for Kalshi perps access</a>.`
            : !data.policy.enabled ? '' : !canPreview() ? 'Account snapshot unavailable. Refresh before ordering.' : '';
      host.innerHTML = `<section class="kalshi-perps-live" aria-labelledby="${prefix}-title">
        <div class="kp-head"><div><h4 id="${prefix}-title">Bitcoin perps <span class="kp-live">Real money</span></h4><p class="kp-hint">Kalshi sets margin and leverage limits. Every order needs your confirmation.</p></div>
          <button type="button" class="btn ghost sm" data-perps-action="refresh"${busy ? ' disabled' : ''}>${loading ? 'Refreshing…' : 'Refresh'}</button></div>
        ${error ? `<p class="kp-error" role="alert">${esc(error)}</p>` : notice ? `<p class="kp-feedback" role="status">${esc(notice)}</p>` : ''}
        ${!data && loading ? '<p class="kp-hint" role="status">Loading live account…</p>' : ''}
        ${gate ? `<p class="kp-gate">${gate}</p>` : ''}
        ${data ? `<div class="kp-policy">${data.policy.enabled ? `<span>Live perps enabled</span><button type="button" class="btn ghost sm" data-perps-action="disable"${busy || !fresh ? ' disabled' : ''}>Disable</button>`
          : `<label class="kp-check"><input type="checkbox" data-perps-field="acknowledged"${acknowledged ? ' checked' : ''}${busy || !fresh || !data.enabled || !data.connected || !data.eligible ? ' disabled' : ''}>I authorize real-money perps trading.</label><button type="button" class="btn sm" data-perps-action="enable"${busy || !fresh || !data.enabled || !data.connected || !data.eligible || !acknowledged ? ' disabled' : ''}>Enable live perps</button>`}</div>` : ''}
        ${data && data.connected && data.eligible ? `<dl class="kp-balances" aria-label="Last retrieved account margin">${stats.map(([label, value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl><p class="kp-hint kp-asof">Last retrieved account${retrievedAt ? ' · ' + esc(time(retrievedAt)) : ''}</p>` : ''}
        ${data ? ticketHtml(busy) : ''}
        ${proposalId && !selected ? `<button type="button" class="btn ghost sm kp-proposal" data-perps-action="proposal"${busy || !canPreview() ? ' disabled' : ''}>Review agent order</button>` : ''}
        ${selected ? detailHtml(selected, busy) : ''}
        ${data && data.orders.some(row => row.id !== reviewId) ? `<div class="kp-orders" aria-label="Perps orders"><h5>Orders</h5>${data.orders.filter(row => row.id !== reviewId).map(row => rowHtml(row, busy)).join('')}</div>` : ''}
        ${positionsHtml()}
      </section>`;
      host.setAttribute('aria-busy', busy ? 'true' : 'false');
      if (focusField && typeof host.querySelector === 'function') {
        const next = host.querySelector('[data-perps-field="' + focusField + '"]');
        if (next && !next.disabled && typeof next.focus === 'function') {
          next.focus();
          if (selection && typeof next.setSelectionRange === 'function') next.setSelectionRange(...selection);
        }
      }
    }

    function ticketHtml(busy) {
      const quote = data.quote;
      return `<form class="kp-ticket" data-perps-ticket aria-label="Bitcoin perpetual limit order"><fieldset${busy || !canPreview() ? ' disabled' : ''}><legend class="kp-sr">New live order</legend>
        <label class="kp-field"><span>Side</span><select data-perps-field="side"><option value="bid"${fields.side === 'bid' ? ' selected' : ''}>Buy</option><option value="ask"${fields.side === 'ask' ? ' selected' : ''}>Sell</option></select></label>
        <label class="kp-field"><span>Whole contracts</span><input type="text" data-perps-field="count" inputmode="numeric" pattern="[1-9][0-9]*" autocomplete="off" value="${esc(fields.count)}" required></label>
        <label class="kp-field kp-price"><span>Limit USD / contract</span><input type="text" data-perps-field="price" inputmode="decimal" autocomplete="off" value="${esc(fields.price)}" required></label>
        <label class="kp-check kp-reduce"><input type="checkbox" data-perps-field="reduce_only"${fields.reduce_only ? ' checked' : ''}>Reduce only</label>
        <button type="submit" class="btn sm" data-perps-action="preview">Preview order</button>
        </fieldset><p class="kp-hint">${data.market && positive(data.market.contract_multiplier) ? '1 contract = ' + esc(exact(data.market.contract_multiplier)) + ' BTC. ' : ''}${quote ? 'Bid ' + esc(money(quote.bid)) + ' · Ask ' + esc(money(quote.ask)) + '. ' : ''}IOC: unfilled quantity is canceled.</p></form>`;
    }

    function actionsHtml(row, busy, detailed) {
      const blocked = busy ? ' disabled' : '';
      const label = esc((row.request.side === 'bid' ? 'Buy ' : 'Sell ') + exact(row.request.count) + ' ' + row.request.ticker + ' contracts at ' + money(row.request.price) + ' per contract');
      const neverSent = row.status === 'draft' && !attempted.has(row.id) && !uncertain.has(row.id);
      if (neverSent && !detailed) return `<button type="button" class="btn ghost sm" data-perps-action="review" data-perps-id="${row.id}" aria-label="Review ${label}"${blocked}>Review</button>`;
      const check = `<button type="button" class="btn ghost sm" data-perps-action="check" data-perps-id="${row.id}" aria-label="Check status: ${label}"${blocked}>Check status</button>`;
      if (neverSent && expired(row) && (row.source === 'user' || proposalId)) return `<button type="button" class="btn sm" data-perps-action="new-preview" data-perps-id="${row.id}"${busy || !canPreview() ? ' disabled' : ''}>Refresh preview</button>`;
      if (neverSent) return `<button type="button" class="btn primary sm" data-perps-action="confirm" data-perps-id="${row.id}" aria-label="Confirm live order: ${label}"${busy || !canConfirm(row) ? ' disabled' : ''}>Confirm live order</button>`;
      if (terminal.has(row.status) && !detailed) return `<button type="button" class="btn ghost sm" data-perps-action="review" data-perps-id="${row.id}"${blocked}>Details</button>`;
      return (!terminal.has(row.status) ? check : '') + (['approved', 'accepted'].includes(row.status) && !cancelAttempted.has(row.id)
        ? `<button type="button" class="btn ghost sm" data-perps-action="cancel" data-perps-id="${row.id}"${blocked}>Cancel remainder</button>` : '');
    }

    function rowHtml(row, busy) {
      return `<article class="kp-order"><div><strong>${row.request.side === 'bid' ? 'Buy' : 'Sell'} ${esc(exact(row.request.count))} · ${esc(row.request.ticker)}</strong><p>${esc(money(row.request.price))} / contract · ${esc(displayStatus(row))}${row.source === 'agent' ? ' · Agent proposal' : ''}</p></div><div class="kp-actions">${actionsHtml(row, busy, false)}</div></article>`;
    }

    function detailHtml(row, busy) {
      const p = row.preview;
      const values = [['Contracts', exact(row.request.count)], ['BTC quantity', decimal(p.btc_quantity) ? exact(p.btc_quantity) + ' BTC' : 'Unavailable'],
        ['Limit / contract', money(row.request.price)], ['Notional', money(p.notional_usd)], ['Estimated fee', money(p.estimated_fee_usd)],
        ['Available balance', money(p.available_balance)], ['Current leverage', leverage(p.account_leverage)]];
      const unsent = row.status === 'draft' && !attempted.has(row.id) && !uncertain.has(row.id);
      return `<article class="kp-review" data-perps-review aria-label="Exact live order review"><div class="kp-review-head"><h5>${row.request.side === 'bid' ? 'Buy' : 'Sell'} ${esc(row.request.ticker)}${row.source === 'agent' ? ' · Agent proposal' : ''}</h5><span>${esc(displayStatus(row))}</span></div>
        <dl class="kp-preview">${values.map(([label, value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>
        <p class="kp-hint">${row.request.reduce_only ? 'Reduce only · ' : ''}IOC · Unfilled quantity canceled${unsent ? ' · Preview ' + esc(time(p.quoted_at)) : ''}</p>
        ${unsent && expired(row) ? '<p class="kp-error">This preview expired. Create a fresh preview before confirming.</p>' : unsent && !previewComplete(row) ? '<p class="kp-error">Preview details are unavailable. Refresh before ordering.</p>' : ''}
        ${!unsent ? `<dl class="kp-fills"><div><dt>Confirmed filled contracts</dt><dd>${esc(exact(row.filled_count))}</dd></div><div><dt>Average fill / contract</dt><dd>${esc(money(row.filled_avg_price))}</dd></div><div><dt>Actual fees</dt><dd>${esc(money(row.total_fees))}</dd></div></dl>` : ''}
        ${uncertain.has(row.id) || ['unknown', 'claimed', 'approved', 'accepted', 'cancel_pending'].includes(row.status) || attempted.has(row.id) && row.status === 'draft' ? '<p class="kp-hint">Check status before placing another order. This order will not be resubmitted.</p>' : ''}
        <div class="kp-actions">${actionsHtml(row, busy, true)}<button type="button" class="btn ghost sm" data-perps-action="dismiss"${busy ? ' disabled' : ''}>Close review</button></div></article>`;
    }

    function positionsHtml() {
      if (!data || !data.positions.length) return '';
      return `<div class="kp-positions"><h5>Positions</h5><div class="kp-table" tabindex="0" role="region" aria-label="Perps positions"><table><thead><tr><th scope="col">Market</th><th scope="col">Contracts</th></tr></thead><tbody>${data.positions.map(row => `<tr><th scope="row">${esc(text(row.ticker))}</th><td>${esc(exact(row.position))}</td></tr>`).join('')}</tbody></table></div></div>`;
    }

    function upsert(value) {
      const row = order(value);
      if (row.status !== 'draft') uncertain.delete(row.id);
      const index = data.orders.findIndex(item => item.id === row.id);
      if (index < 0) data.orders.unshift(row); else data.orders[index] = row;
      return row;
    }

    async function refresh() {
      if (!current() || loading || pending) return;
      const turn = ++sequence;
      loading = true; error = ''; notice = ''; render();
      try {
        const response = await request(BASE);
        if (!current() || turn !== sequence) return;
        data = overview(response); fresh = true; retrievedAt = new Date().toISOString();
        for (const row of data.orders) if (row.status !== 'draft') uncertain.delete(row.id);
      } catch (_) {
        if (current() && turn === sequence) { fresh = false; error = 'Could not refresh live perps. Refresh before ordering.'; }
      } finally {
        if (current() && turn === sequence) { loading = false; render(); }
      }
    }

    function key(value) {
      const result = value || root.crypto.randomUUID();
      if (!/^[A-Za-z0-9_-]{8,80}$/.test(result)) throw new Error('Secure request key unavailable');
      return result;
    }

    async function preview(fromProposal) {
      if (!current() || pending || loading || !canPreview()) return;
      if (!fromProposal && (!whole(fields.count.trim()) || !positive(fields.price.trim()) || !['bid', 'ask'].includes(fields.side))) {
        error = 'Enter positive whole contracts and a positive USD limit per contract.'; notice = ''; render(); return;
      }
      let body;
      try {
        if (fromProposal) { proposalKey = key(proposalKey); body = {request_key: proposalKey}; }
        else { ticketKey = key(ticketKey); body = {request_key: ticketKey, side: fields.side, count: fields.count.trim(), price: fields.price.trim(), reduce_only: fields.reduce_only}; }
      } catch (_) { error = 'A secure order request could not be created. Refresh your browser.'; render(); return; }
      if (fromProposal && !proposalId) return;
      pending = 'preview'; error = ''; notice = ''; render();
      try {
        const response = await request(fromProposal ? BASE + '/proposals/' + proposalId + '/preview' : BASE + '/orders', body);
        if (!current()) return;
        const row = upsert(response && response.order);
        reviewId = row.id;
        notice = '';
      } catch (_) {
        if (current()) { fresh = false; error = 'Preview was not confirmed. Refresh to find any saved preview before ordering.'; }
      } finally {
        pending = '';
        if (current()) render();
      }
    }

    async function setPolicy(enabled) {
      if (!current() || loading || pending || !fresh || !data || (enabled && (!acknowledged || !data.enabled || !data.connected || !data.eligible))) return;
      pending = 'policy'; error = ''; notice = ''; render();
      try {
        const body = {enabled, expected_version: data.policy.version};
        if (enabled) body.acknowledge_real_money = true;
        const response = await request(BASE + '/policy', body);
        if (!current()) return;
        data.policy = policy(response && response.policy); reviewId = ''; acknowledged = false;
        notice = enabled ? 'Live perps enabled. Preview an order to continue.' : 'Live perps disabled. Existing orders and positions are unchanged.';
      } catch (_) {
        if (current()) { fresh = false; error = 'The preference change was not confirmed. Refresh before ordering.'; }
      } finally { pending = ''; if (current()) render(); }
    }

    async function act(button) {
      if (!current() || button.disabled || loading || pending) return;
      const action = button.dataset.perpsAction;
      if (action === 'refresh') return refresh();
      if (action === 'preview') return preview(false);
      if (action === 'proposal') return preview(true);
      if (action === 'enable' || action === 'disable') return setPolicy(action === 'enable');
      if (action === 'dismiss') { reviewId = ''; render(); return; }
      const row = data && data.orders.find(item => item.id === button.dataset.perpsId);
      if (!row) return;
      if (action === 'review') { reviewId = row.id; error = ''; notice = ''; render(); return; }
      if (action === 'new-preview' && row.status === 'draft' && !attempted.has(row.id) && !uncertain.has(row.id) && expired(row)) {
        if (row.source === 'agent') { proposalKey = ''; return preview(true); }
        fields.side = row.request.side; fields.count = row.request.count; fields.price = row.request.price;
        fields.reduce_only = row.request.reduce_only; ticketKey = ''; return preview(false);
      }
      if (!['confirm', 'check', 'cancel'].includes(action)) return;
      if (action === 'confirm' && !canConfirm(row)) {
        error = 'This order needs a fresh preview before confirmation.'; render(); return;
      }
      if (action === 'cancel' && (!['approved', 'accepted'].includes(row.status) || cancelAttempted.has(row.id))) return;
      pending = action; error = ''; notice = ''; reviewId = row.id;
      if (action === 'confirm') attempted.add(row.id);
      if (action === 'cancel') cancelAttempted.add(row.id);
      render();
      const endpoint = action === 'confirm' ? 'submit' : action === 'check' ? 'refresh' : 'cancel';
      const body = action === 'check' ? {} : {confirmed: true, expected_version: row.version, request_hash: row.request_hash};
      try {
        const response = await request(BASE + '/orders/' + encodeURIComponent(row.id) + '/' + endpoint, body);
        if (!current()) return;
        const result = upsert(response && response.order);
        if (action === 'confirm' && result.status === 'draft') uncertain.add(row.id);
        notice = action === 'check' ? 'Order status checked.' : '';
      } catch (_) {
        if (current()) {
          if (action === 'confirm') uncertain.add(row.id);
          if (action === 'cancel') row.status = 'cancel_pending';
          error = action === 'confirm' ? 'Submission is unconfirmed. Check status; do not place this order again.'
            : action === 'cancel' ? 'Cancellation is unconfirmed. Check status.' : 'Could not check order status. Try Check status again.';
        }
      } finally { pending = ''; if (current()) render(); }
    }

    function destroy() {
      disposed = true; sequence++;
      if (owners.get(host) === identity) {
        owners.delete(host); host.onclick = null; host.oninput = null; host.onchange = null; host.onsubmit = null;
      }
    }
    identity.destroy = destroy;
    owners.set(host, identity);
    host.onclick = event => {
      const button = event.target.closest && event.target.closest('[data-perps-action]');
      if (button && host.contains(button)) { event.preventDefault(); return act(button); }
    };
    host.oninput = host.onchange = event => {
      if (!current() || pending || loading) return;
      const field = event.target.dataset && event.target.dataset.perpsField;
      if (field === 'acknowledged') { acknowledged = event.target.checked === true; render(); return; }
      if (!Object.hasOwn(fields, field) || field === 'side' && !['bid', 'ask'].includes(event.target.value)) return;
      const value = field === 'reduce_only' ? event.target.checked === true : event.target.value;
      if (fields[field] !== value) { fields[field] = value; ticketKey = ''; reviewId = ''; error = ''; notice = ''; render(); }
    };
    host.onsubmit = event => { event.preventDefault(); return preview(false); };
    const ready = (async () => { await refresh(); if (current() && proposalId && canPreview()) await preview(true); })();
    return {ready, refresh, destroy};
  }
  return {mount};
});
