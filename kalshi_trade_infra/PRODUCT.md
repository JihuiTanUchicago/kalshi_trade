# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Existing codebase answers it: Python 3.9-compatible stdlib HTTP server, MySQL (RDS), vanilla
HTML/CSS/JS with no build step. The customer app (`app/`) serves real static files
(`app/static/`) rather than HTML embedded in Python strings; the operator console keeps its
single-file form.

## Users

Primary: **retail traders who want an edge on Bitcoin prediction markets without writing
code** - people like Jonathan in `mvp.md`. They know what a BTC price is and what a yes/no
contract pays; they do not know what a brier score is. They sign in with Google, tell an agent
what they want to trade, and judge the result by money, not by model diagnostics. They check
in on a phone between other things and sit down at a laptop to review and deploy.

Secondary: the owner/operator, who keeps the private Kursbuch control room
(`data_pipeline/dashboard_server.py`) for supervising the house pipeline. That surface keeps
its own audience and rules (see "Operator console" below).

## Product Purpose

**Tau** is a self-improving alpha-discovery loop for Kalshi's Bitcoin markets: an
agent proposes trading hypotheses, validates them in a backtest it cannot cheat (it never sees
the out-of-sample period while iterating), and only strategies that pass are deployable. The
user decides what to deploy, watches it trade, and talks to the agent to adjust it - or lets
the agent adjust it on autopilot, with every thought written to the chat.

Success: a user goes from "I want to trade bitcoin" to a deployed, backtest-passed strategy
in one sitting, understands why it should work, and can tell at a glance whether it is.

## Positioning

Not a signals newsletter and not a no-code bot builder. The agent does the research, and the
product shows its homework: the thesis in plain language, the in-sample result it iterated on,
the out-of-sample result it never saw, and how many hypotheses were tried to find it. A
strategy that fails its gate is shown as failed, not hidden.

## Operating Context

- Markets in v0.1: Kalshi **BTC 15-minute** (`KXBTC15M`) and **BTC daily close at 5pm EDT**
  (`KXBTCD`, the 5pm event's strike ladder).
- Money: every user starts with a **paper account** (simulated deposits/withdrawals). Live
  trading happens only in the user's **own Kalshi account** via an API key they connect; we
  never hold customer funds (that would need CFTC registration). The Account page shows the real
  Kalshi balance and sends the user to Kalshi to move money.
- Sign-in is Google only.
- Agents run in a background worker; research takes minutes, so progress must be visible
  and survive the user closing the tab.

## Capabilities and Constraints

- The October 15 local Meridian presentation brings recent research sessions to
  Overview beside existing paper account, deployments and trade data. Optional
  session reads fail independently; existing endpoints and financial behavior do
  not change. Compact spacing and Catalyst-inspired colors are local frontend
  changes, not a production deployment.

- Navigation: Dashboard, Research, Explore, Position, Community, Account, Billing and System
  (with Admin available to the operator).
  The requested separate-page restoration was completed before this transformation.
  Research sessions now hold conversation on the left and generated strategy
  artifacts in tabs on the right. Every candidate status remains inspectable;
  existing library/filter access and old strategy URLs remain available in Research.
- Strategy artifacts preserve all saved evidence, exact rules/spec, equity curve,
  sample/unseen metrics, trades, gates and evaluator-backed what-if scenarios.
  Scenarios do not change the deployable saved rule. Paper/live controls are shared
  with Position's eligible-strategy list; existing financial gates remain.
- Session conversation uses the [scoped backend contract](app/SESSION_CHAT_API.md),
  whose routes/persistence/worker behavior remain unimplemented. Unavailable routes
  retain drafts and disable writes; Position keeps its account-wide chat/autopilot.
  Artifact tabs and drafts are temporary per-user/session frontend state, cleared
  on sign-out or browser reload. [Workspace evidence](results/meridian_frontend_pr_2026-10-15/HANDOFF.md).
- Agents produce a **thesis + parameterized strategy spec**, never code. Our backtester and
  our engines run the spec, so backtest and deployment evaluate the identical rule.
- Position highlights passed candidates. Artifact deployment follows the current
  upstream policy: users may explicitly deploy saved passed/void/rejected candidates,
  with risk warnings for unvalidated results and the existing market/live guards.
  Session-chat revision approval still requires a passed backtest.
- Autopilot ("dangerously skip permission") lets the agent apply adjustments and deploy to
  paper on its own, inside guardrails: it can never move a strategy to live money and never
  raise a risk cap.
- Live trading for app users is gated by a server-wide switch that is **off** until the owner
  explicitly authorizes it; live strategies are YES-side only in v0.1.
- Upstream credits/Billing and the card-on-file gate are included in the current
  code. The Research form respects `needs_card` and the global payment
  dialog; metered agent work still uses the backend's credit/card checks. Local
  preview has payments disabled. Actual account/payment acceptance remains a
  configured-backend gate, separate from this frontend compatibility check.

## Brand Commitments

- Name: **Tau** (chosen by the owner, 2026-10-12). Never use "Kalshi" as or inside the
  product's name or mark; Kalshi is named only as the venue.

## Evidence on Hand

- Real Kalshi settled markets, candlesticks and results for both series, and Coinbase BTC
  candles, pulled by `app/market_history.py` - all backtests run on these, nothing invented.
- The house pipeline's paper record (see Operator console) proves most naive strategies lose
  after fees: three of five went deeply negative. That is why the gate exists.
- No customers, testimonials, or performance claims exist yet. Do not fabricate any.

## Product Principles

1. **Show the homework.** Every strategy carries its thesis, its in-sample and out-of-sample
   result, and the number of hypotheses tried. Failed strategies stay visible.
2. **Paper is the default, live is a deliberate act.** Real money must look different and
   require an explicit, informed step - never a toggle that is easy to hit by accident.
3. **Stale is a state, not a silence.** A number whose source has stopped says so.
4. **Plain language first, numbers second.** Say what is happening in a sentence a
   non-quant understands, then show the figure that proves it.
5. **The agent explains itself.** Nothing the agent does - research, adjustment, deployment -
   happens without a readable reason in the chat or the run log.

## Accessibility & Inclusion

WCAG 2.2 AA as the floor: phone in daylight and laptop are both first-class, state is never
carried by color alone (gain/loss, paper/live, passed/failed each carry a word or shape), every
control is reachable by keyboard and at 360px width, and motion respects
`prefers-reduced-motion`.

## Operator console (secondary surface)

`data_pipeline/dashboard_server.py` stays the owner's private Kursbuch control room for the house
15-minute pipeline: one expert user, density over explanation, basic auth plus a live-password
gate, live execution as its front page. Its design record is DESIGN.md's Kursbuch world and
`.impeccable/surfaces/data-pipeline-dashboard-server-py.md`; it is not the customer product.
