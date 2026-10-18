# Independent auth and protocol review

Read-only review by `broker_storage`, completed October 17, 2026.

No actionable security/correctness blocker found in the reviewed OAuth service,
three adapters, server routes, storage/vault or shared frontend. Independent
focused suite: **141 passed**. This is manual code review and offline validation,
not a named `/security-review` invocation or scan-engine result.

Checked: authenticated routes and custom POST header; user/session/provider/
environment binding; state hashing/expiry/single consumption; claimed-at and
reconnect/disconnect fencing; server-side token exchange; fixed endpoints and
redirects; PKCE/issuer checks; encrypted grants and metadata projection; callback
log/error/referrer handling; frontend escaping and stale responses. Primary
Alpaca and IBKR protocol docs match the construction. Root separately captured
public Robinhood discovery metadata (two HTTP200 anonymous GETs).

Unverified external gates: registered Alpaca app and real paper consent/account
read; Robinhood approved hosted public client and complete real PKCE/MCP flow;
approved IBKR consumer, keys/DH and registered callback preserving state, plus
actual request/access/LST exchange. No order tool or IBKR brokerage-session
initializer is reachable through these new routes. Renewal helpers are not
connected to a worker. Database migration/deployment/production acceptance remain
separate.
