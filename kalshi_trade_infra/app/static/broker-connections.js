/* Account authorization only. This module has no order-placement transport. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TauBrokerConnections = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const BROKERS = {
    alpaca: {name: 'Alpaca', environments: ['paper', 'live'], host: 'app.alpaca.markets', path: '/oauth/authorize'},
    robinhood: {name: 'Robinhood', environments: ['live'], host: 'robinhood.com', path: '/oauth'},
    ibkr: {name: 'Interactive Brokers', environments: ['live'], hosts: ['interactivebrokers.com', 'www.interactivebrokers.com'], path: '/authorize'},
  };
  const SETUP_HOSTS = new Set(['alpaca.markets', 'docs.alpaca.markets', 'robinhood.com', 'www.robinhood.com', 'interactivebrokers.com', 'www.interactivebrokers.com']);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
  const environmentName = environment => environment === 'paper' ? 'Paper' : 'Live';

  function authorizationUrl(id, value) {
    const broker = Object.hasOwn(BROKERS, id) ? BROKERS[id] : null;
    if (!broker || typeof value !== 'string') throw new Error('Invalid broker redirect');
    const url = new URL(value);
    const hosts = broker.hosts || [broker.host];
    if (url.protocol !== 'https:' || url.username || url.password || url.port || url.hash || !hosts.includes(url.hostname) || url.pathname !== broker.path) {
      throw new Error('Invalid broker redirect');
    }
    return url.href;
  }

  function setupUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && !url.username && !url.password && !url.port && SETUP_HOSTS.has(url.hostname) ? url.href : '';
    } catch (_) { return ''; }
  }

  function callbackMessage(search) {
    const params = new URLSearchParams(search || '');
    const id = params.get('broker');
    const broker = Object.hasOwn(BROKERS, id) ? BROKERS[id] : null;
    if (!broker) return null;
    const messages = {
      connected: ['connected. Trading in Tau remains disabled.', false],
      cancelled: ['connection cancelled.', false],
      expired: ['authorization expired. Try connecting again.', true],
      failed: ['could not be connected. Try again.', true],
      superseded: ['connection was replaced by a newer request. Try again.', true],
    };
    const status = params.get('broker_status');
    const result = Object.hasOwn(messages, status) ? messages[status] : null;
    return result ? {text: broker.name + ' ' + result[0], error: result[1]} : null;
  }

  function normalizeProviders(data) {
    if (!data || !Array.isArray(data.providers)) throw new Error('Invalid broker response');
    const providers = new Map();
    for (const value of data.providers) {
      if (!value || !Object.hasOwn(BROKERS, value.id) || providers.has(value.id)) continue;
      const broker = BROKERS[value.id];
      const environments = broker.environments.filter(environment => Array.isArray(value.environments) && value.environments.includes(environment));
      if (!environments.length) throw new Error('Invalid broker environment');
      const connections = (Array.isArray(value.connections) ? value.connections : []).filter(connection =>
        connection && connection.connected === true && environments.includes(connection.environment));
      providers.set(value.id, {
        id: value.id, name: broker.name, configured: value.configured === true,
        reason: typeof value.reason === 'string' ? value.reason.slice(0, 500) : '',
        permission_note: typeof value.permission_note === 'string' ? value.permission_note.slice(0, 1000) : '',
        setup_url: setupUrl(value.setup_url), environments, connections,
        default_environment: environments.includes(value.default_environment) ? value.default_environment : environments[0],
      });
    }
    if (!providers.size) throw new Error('No broker providers');
    return Object.keys(BROKERS).filter(id => providers.has(id)).map(id => providers.get(id));
  }

  function mount(host, options) {
    if (!host || !options || typeof options.api !== 'function') throw new Error('Broker account host and API are required');
    const request = options.api;
    const current = () => !disposed && host.isConnected !== false && (!options.isCurrent || options.isCurrent());
    const navigate = options.navigate || (url => window.location.assign(url));
    const callback = callbackMessage(options.search === undefined ? (typeof window === 'object' ? window.location.search : '') : options.search);
    const states = new Map();
    let providers = [], loading = false, loadFailed = false, disposed = false, sequence = 0;

    function stateFor(provider) {
      if (!states.has(provider.id)) states.set(provider.id, {environment: provider.default_environment, permission: 'read', pending: false, error: '', notice: ''});
      const state = states.get(provider.id);
      if (!provider.environments.includes(state.environment)) state.environment = provider.default_environment;
      return state;
    }

    function providerHtml(provider) {
      const state = stateFor(provider);
      const selected = provider.connections.find(connection => connection.environment === state.environment);
      const disabled = !provider.configured || state.pending;
      const connections = provider.connections.map(connection => {
        const scopes = Array.isArray(connection.scopes) ? connection.scopes : [];
        const access = provider.id === 'alpaca' ? (scopes.includes('trading') ? 'Trading authorized' : 'Read access') : 'Broker authorized';
        return `<li class="broker-connection"><div><span class="broker-status${connection.expired ? ' broker-expired' : ''}">${connection.expired ? 'Expired' : 'Connected'}</span> · ${environmentName(connection.environment)} · ${access}${connection.account_label ? `<span class="broker-account-label">${esc(connection.account_label)}</span>` : ''}</div><button class="btn ghost sm" type="button" data-broker-action="disconnect" data-broker="${provider.id}" data-environment="${connection.environment}"${state.pending ? ' disabled' : ''}>Disconnect<span class="vh"> ${provider.name} ${environmentName(connection.environment)}</span></button></li>`;
      }).join('');
      return `<article class="broker-card" data-broker-card="${provider.id}" aria-labelledby="broker-title-${provider.id}"${state.pending ? ' aria-busy="true"' : ''}>
        <div class="broker-heading"><h4 id="broker-title-${provider.id}">${provider.name}</h4>${!provider.configured ? '<span class="hint">Setup required</span>' : ''}</div>
        ${provider.permission_note ? `<p class="hint broker-note">${esc(provider.permission_note)}</p>` : ''}
        ${connections ? `<ul class="broker-connected">${connections}</ul>` : ''}
        <div class="broker-controls">${provider.environments.length > 1 ? `<label class="broker-environment"><span class="vh">${provider.name} environment</span><select data-broker-environment="${provider.id}"${state.pending ? ' disabled' : ''}>${provider.environments.map(environment => `<option value="${environment}"${state.environment === environment ? ' selected' : ''}>${environmentName(environment)}</option>`).join('')}</select></label>` : ''}
          <button type="button" class="btn${provider.configured ? ' primary' : ''}" data-broker-action="connect" data-broker="${provider.id}"${disabled ? ' disabled' : ''}>${state.pending ? 'Please wait…' : selected ? 'Reconnect' : 'Connect'}<span class="vh"> ${provider.name}</span></button>
          ${!provider.configured && provider.setup_url ? `<a class="broker-setup" href="${esc(provider.setup_url)}" target="_blank" rel="noopener noreferrer">Connection details<span class="vh"> for ${provider.name}</span></a>` : ''}
        </div>
        ${provider.id === 'alpaca' && provider.configured ? `<label class="broker-permission"><input type="checkbox" data-broker-permission="alpaca"${state.permission === 'trading' ? ' checked' : ''}${state.pending ? ' disabled' : ''}> <span>Authorize trading at Alpaca</span></label>` : ''}
        ${!provider.configured ? `<p class="hint broker-note">${esc(provider.reason || 'Your Tau administrator needs to enable this connection.')}</p>` : ''}
        ${state.error ? `<p class="broker-feedback broker-error" role="alert">${esc(state.error)}</p>` : state.notice ? `<p class="broker-feedback" role="status">${esc(state.notice)}</p>` : ''}
      </article>`;
    }

    function render() {
      if (!current()) return;
      host.innerHTML = `<div class="broker-section-head"><h3>Broker accounts</h3><p class="hint">Authorize access at your broker. Trading in Tau stays disabled.</p></div>
        ${callback ? `<p class="broker-callback${callback.error ? ' broker-error' : ''}" role="${callback.error ? 'alert' : 'status'}">${esc(callback.text)}</p>` : ''}
        ${loadFailed ? '<div class="broker-load-error" role="alert"><span>Broker accounts could not be loaded.</span><button type="button" class="btn sm" data-broker-action="retry">Retry</button></div>' : loading && !providers.length ? '<p class="hint" role="status">Loading broker accounts…</p>' : `<div class="broker-grid">${providers.map(providerHtml).join('')}</div>`}`;
      host.setAttribute('aria-busy', loading ? 'true' : 'false');
    }

    async function refresh() {
      if (!current() || loading) return;
      const turn = ++sequence;
      loading = true; loadFailed = false; render();
      try {
        const result = await request('/api/brokers');
        if (!current() || turn !== sequence) return;
        providers = normalizeProviders(result);
      } catch (_) {
        if (current() && turn === sequence) loadFailed = true;
      } finally {
        if (current() && turn === sequence) { loading = false; render(); }
      }
    }

    async function act(button) {
      if (!current() || button.disabled) return;
      const action = button.dataset.brokerAction;
      if (action === 'retry') return refresh();
      if (!['connect', 'disconnect'].includes(action)) return;
      const provider = providers.find(value => value.id === button.dataset.broker);
      if (!provider) return;
      const state = stateFor(provider);
      if (state.pending || (action === 'connect' && !provider.configured)) return;
      const environment = action === 'disconnect' ? button.dataset.environment : state.environment;
      if (!provider.environments.includes(environment) || (action === 'disconnect' && !provider.connections.some(connection => connection.environment === environment))) return;
      state.pending = true; state.error = ''; state.notice = ''; render();
      try {
        const result = await request('/api/brokers/' + provider.id + '/' + action,
          action === 'connect' ? {environment, permission: provider.id === 'alpaca' ? state.permission : 'read'} : {environment});
        if (!current()) return;
        if (action === 'connect') navigate(authorizationUrl(provider.id, result && result.authorization_url));
        else {
          if (!result || result.disconnected !== true) throw new Error('Disconnect not confirmed');
          provider.connections = provider.connections.filter(connection => connection.environment !== environment);
          state.notice = 'Tau access removed. You can also revoke the grant at your broker.';
        }
      } catch (_) {
        if (current()) state.error = action === 'connect' ? 'Could not start the connection. Try again.' : 'Could not disconnect this account. Try again.';
      } finally {
        state.pending = false;
        if (current()) render();
      }
    }

    host.onclick = event => {
      const button = event.target.closest && event.target.closest('[data-broker-action]');
      if (button && host.contains(button)) { event.preventDefault(); return act(button); }
    };
    host.onchange = event => {
      if (!current()) return;
      const target = event.target;
      const id = target.dataset && (target.dataset.brokerEnvironment || target.dataset.brokerPermission);
      const provider = providers.find(value => value.id === id);
      if (!provider) return;
      const state = stateFor(provider);
      if (state.pending) return;
      if (target.dataset.brokerEnvironment && provider.environments.includes(target.value)) { state.environment = target.value; state.error = ''; state.notice = ''; render(); }
      if (target.dataset.brokerPermission && provider.id === 'alpaca') state.permission = target.checked ? 'trading' : 'read';
    };
    const ready = refresh();
    return {ready, refresh, destroy() { disposed = true; sequence++; host.onclick = null; host.onchange = null; }};
  }

  return {mount, authorizationUrl, callbackMessage};
});
