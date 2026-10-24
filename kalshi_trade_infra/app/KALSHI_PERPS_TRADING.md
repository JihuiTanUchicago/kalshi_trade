# Native Bitcoin perpetual orders

This is a separate, manually confirmed Kalshi margin API path. It does not enable
the binary live engine or promote research-only perpetual strategies into an
automatic strategy executor. The research backtest's 1× scenario is unrelated to
this native order path.

The user selected Kalshi's account/product margin and leverage limits without
additional Tau financial caps. There is no `leverage` field on a native order:
actual leverage follows the account's positions, equity and Kalshi's rules. Tau
does not turn available balance into an invented maximum order size.

## User flow

1. Obtain perpetuals approval and fund the separate margin account at Kalshi.
2. Connect your own Kalshi production API key in Tau's account settings.
3. In Funds, explicitly enable manual Bitcoin perpetual orders and acknowledge
   real money. Account eligibility, margin, current leverage and market state
   must be available before ordering.
4. Enter whole native contracts, bid/ask, a USD **per-contract** limit and optional
   reduce-only. Preview shows the corresponding BTC units, notional, fee estimate
   and account state. One native contract represents 0.0001 BTC; native prices
   are already per contract. Never multiply notional by that BTC multiplier again.
5. Separately confirm the exact live ticket. Every order is limit IOC: any unfilled
   quantity is canceled by the venue. Review actual fills and fees afterward.

Agents may propose tickets when the user's manual policy is enabled. Approving
that chat proposal only opens Funds review. It never submits an order. Autopilot
cannot bypass the ticket confirmation.

An uncertain submission stays locked for status reconciliation. Tau does not
retry its order POST, invent a fill, or release the claim because an order is
temporarily absent from history. Key rotation/disconnection is blocked while a
submission needs reconciliation. Disabling new orders leaves owned status checks
and cancellation available; it does not close positions or cancel other orders.

## Production configuration

- `TAU_KALSHI_PERPS_LIVE_ENABLED=1`: expose the manual native capability. Default 0.
- `TAU_KALSHI_PERPS_LIVE_ENVIRONMENT=production`: fixed operator choice. Demo is a
  separate private account context; the initial Funds component accepts production.
- `TAU_KALSHI_PERPS_LIVE_TICKER`: optional exact native BTC ticker. With no value,
  discover and verify the native Bitcoin instrument.
- `TAU_KALSHI_PERPS_PROXY_URL`: optional credential-free proxy, only when the host
  needs one. Native production/demo origins remain fixed and TLS verified.

Keep these settings in protected server configuration. Never put credentials in
Git. Native requests use each user's encrypted key, never global `PROD_*` keys.
Keep `APP_LIVE_TRADING_ENABLED`, binary live settings and existing risk gates at
their independently approved values. `TAU_KALSHI_PERPS_ENABLED` is the separate
research-data flag; enabling live tickets does not establish research acceptance.

Run the complete `python -m app.schema` during a whole-package deployment. New
settings and order tables are additive. Preserve existing private configuration,
the encryption secret, installed production fixes and diagnostic files. A
standard workflow that restarts active research workers requires an idle/drain
check or explicit permission to interrupt those runs.

## Verification boundary

Offline tests cover the signed native transport, exact decimals, contract units,
immutable previews, ownership, single-send claims committed before network I/O,
uncertain recovery, partial fills, actual fees, key changes and proposal review.
Hosted isolated staging exercises the authenticated HTTP/database lifecycle with
an explicitly synthetic broker, without production credentials or real orders.
Those checks do not establish a real customer's approval, available margin or
successful live fill. The owner must connect an eligible account and confirm a
specific order to establish account-specific live execution.

Official contracts and current verification receipts are linked from
[the release handoff](../results/kalshi_perps_deployment_preparation_2026-10-23/HANDOFF.md).
