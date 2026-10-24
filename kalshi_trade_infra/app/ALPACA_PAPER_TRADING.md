# Alpaca paper trading

Source merged in [PR #13](https://github.com/JihuiTanUchicago/kalshi_trade/pull/13)
as `f76b2f1`, including current-main research diagnostics. Production deployment
and real-user account acceptance remain separate. The [isolated staging setup](../staging/README.md)
tests actual MySQL/HTTP with synthetic broker observations. This adds broker-simulated stock/ETF orders, balances, positions and
fill reconciliation to Tau. It uses each user's existing encrypted Alpaca OAuth
grant, separately from the shared `APCA_*` market-data keys and Tau's internal
Kalshi practice ledger.

## User flow

These controls are temporarily removed from Funds in both themes while broker
connections are unavailable. The flow below documents the retained implementation
for a later, verified reactivation; it is not currently offered in the UI.

1. Sign into Tau and open Funds, or Settings → Account in Meridian.
2. Connect Alpaca with **Paper** selected and **Authorize trading at Alpaca** checked.
   Existing read-only connections must reconnect to grant `trading` permission.
3. Enter a stock/ETF symbol, buy/sell, whole shares and limit price. Review the
   saved ticket, then select **Submit paper order**. Account cash is simulated
   cash maintained by Alpaca; Tau's Kalshi practice deposits do not fund it.
4. Account refresh and agent reviews synchronize observed broker fills for recent
   tracked orders. **Check status** looks up a specific client order ID. Partial
   fills, queued orders and cancellation requests remain distinct from fills.
5. **Cancel order** requests cancellation. It stays pending until Alpaca confirms;
   a fill can win the cancellation race. Manage/reset simulated cash at Alpaca.

The co-pilot supports `alpaca_paper_order` actions, for example:

```json
{"type":"alpaca_paper_order","symbol":"AAPL","side":"buy","qty":"1","limit_price":"100.00","reason":"User requested this paper experiment."}
```

This creates a pending `alpaca_paper` proposal and the same durable order ticket.
The user's chat **Approve** button or account **Submit paper order** button uses
the same execution path. Existing Kalshi autopilot never auto-approves these
tickets. An approved proposal records approval/submission, not an exchange fill.
The price above illustrates a request format, not a current market quote.

## Execution boundary

- The host is fixed to `https://paper-api.alpaca.markets/v2`. Environment variables,
  model actions and request fields cannot select a live host. This matters because
  one OAuth token can authorize paper and live accounts. [Alpaca OAuth documentation](https://docs.alpaca.markets/us/docs/using-oauth2-and-trading-api).
- Initial orders are US-equity, whole-share, simple limit, DAY, regular-session
  orders. No options, crypto orders, shorts, margin borrowing, market orders,
  brackets, replacements or extended-hours submission are exposed.
- Checks require an active, unblocked USD paper account and tradable US-equity
  asset. Buys must fit cash after open buy reservations; sells must fit held shares
  after open sell reservations. The configured notional ceiling is checked again
  at submission. Alpaca enforces its own account/order rules too.
- A user lock protects the final claim. A monotonic count of irreversible send
  claims detects competing submissions, including ones that already fully filled
  and vanished from the open-order set while capacity was being read.
- The intent and stable `client_order_id` are committed before the only POST.
  Timeout, malformed acknowledgement and uncertain broker response produce
  `unknown`; retries return the same intent without another POST. A GET returning
  404 after uncertainty does not prove it is safe to resend.
- Fill quantities/prices come from validated broker observations. Acceptance is
  not a fill, a 204 cancellation acknowledgement is not cancellation, stale reads
  cannot reduce booked fill quantities or reopen a terminal order. No synthetic
  fill is written into Tau's Kalshi positions/ledger.
- Drafts are bound to the connection version. Reconnecting/replacing/disconnecting
  a grant invalidates those old tickets. Submitted orders remain at Alpaca; manage
  old-connection orders there if Tau's connection has been replaced. Disconnect
  cannot recall a request already claimed/in flight or revoke the broker grant.
- Capacity checks coordinate Tau's sends. External trading in the same Alpaca
  account can change it between snapshots; use a dedicated paper account for
  validation. This does not add an equity backtest DSL, a continuously scheduled
  equity strategy engine, or live equity execution.

Limit orders placed outside eligible hours can wait until the next session; do
not interpret an unfilled Sunday order as a failed connection. [Alpaca order lifecycle](https://docs.alpaca.markets/us/docs/orders-at-alpaca).

## Operator setup

Keep actual secrets in protected runtime configuration. Never commit `.env` or
put actual API keys into an example file. Shared market-data keys cannot trade
on behalf of individual users. Existing OAuth configuration is still required:

```dotenv
APP_PUBLIC_URL=https://tau-trading.com
ALPACA_OAUTH_CLIENT_ID=<private OAuth app client ID>
ALPACA_OAUTH_CLIENT_SECRET=<private OAuth app secret>
TAU_ALPACA_PAPER_ENABLED=1
TAU_ALPACA_PAPER_MAX_ORDER_USD=500
```

Preserve the existing persistent `APP_SECRET_KEY`; do not generate a replacement.
The paper flag defaults to `0`. The per-order notional limit defaults to USD 500,
accepts plain USD values with at most two decimal places, and must be positive and
at most USD 1,000,000. It is an execution risk control, independent of market-data
spending and Exa quotas. Turning submission off still allows existing order
cancellation/status recovery while the corresponding grant remains valid.

The callback stays
`https://tau-trading.com/auth/brokers/alpaca/callback`.
Register that exact HTTPS callback in the Alpaca OAuth app. If its allowlist still contains only the former CloudFront address, add the canonical-domain callback before connecting. Existing shared market-data keys cannot authorize a user account.

Run the configuration check in the intended injected environment:

```bash
python -m app.alpaca_paper status
```

It uses no network/database and prints booleans, endpoint, callback and notional
limit only. `ready_for_user_connection` is configuration readiness; it does not
prove consent, account access or an order/fill.

Deploy a complete reviewed `app/` package. Use `python -m app.schema`, which adds
`app_alpaca_paper_orders` as well as all existing application/pipeline migrations;
do not substitute broker-only SQL or `data_pipeline.init_schema`. The table is
additive; do not drop/rewrite existing intent history during a rollback. Load the
flag into web and agent workers, wait for active jobs before worker maintenance,
and follow the existing HTTP/asset/CloudFront verification procedure. Source
publication, deployment and real-user consent remain separate acceptance steps.

Actual paper acceptance should confirm the authenticated user's paper connection,
balances/positions and a small explicitly chosen paper ticket, then verify lookup
by client ID, broker status, fill or pending state, and cancellation. Never infer
this acceptance from fixtures, workflow success or a configuration check. No real
paper order or production change was made during this implementation.

## API and persistence

All routes require Tau authentication. POSTs also require `X-Recursive: 1` and
inherit existing session/CSRF checks; responses are `no-store`.

| Method | Route | Behavior |
| --- | --- | --- |
| GET | `/api/brokers/alpaca/paper` | Safe account/positions and tracked order projection; bounded fill synchronization |
| POST | `/api/brokers/alpaca/paper/orders` | Save draft `{request_key,symbol,side,qty,limit_price}`; no order POST |
| POST | `/api/brokers/alpaca/paper/orders/{id}/submit` | Validate, claim once, submit or return existing state |
| POST | `/api/brokers/alpaca/paper/orders/{id}/refresh` | Reconcile by original client ID; no resubmission |
| POST | `/api/brokers/alpaca/paper/orders/{id}/cancel` | Discard draft or request broker cancellation |
| POST | `/api/proposals/{id}/approve` or `/reject` | Same paper intent via existing co-pilot controls |

Reuse the same `request_key` when retrying draft creation. A different ticket
under the same key is rejected. Orders are owner scoped; clients receive neither
tokens, account IDs, credential fingerprints nor raw upstream responses.
Recent history is bounded to 50 tracked tickets; a specific older ticket can be
reconciled by its Tau ID. Unknown requests are deliberately never auto-resubmitted.

Offline evidence and exact test commands: [implementation handoff](../results/alpaca_paper_trading_2026-10-18/HANDOFF.md).
