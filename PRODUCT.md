# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One user: the owner/operator, who also wrote the system. No second audience — not teammates,
not graders, not recruiters. The dashboard is a private instrument, so density, shorthand, and
domain vocabulary (brier, logloss, edge, taker fee, drawdown) need no explanation and no
onboarding. Nothing on it is being sold or demonstrated to anyone.

Confirmed situation: he opens it most often to **watch real money move** — a live position is
open or about to be, and he wants entry, mark, unrealized, and risk state without hunting for
them. Evaluating paper strategies and checking pipeline health are real but secondary jobs.

He opens it on desktop/ultrawide (3440px), laptop, and phone. All three are first-class.

## Product Purpose

Operate and supervise an automated Kalshi BTC 15-minute prediction-market trading system:
watch live execution, judge whether a paper strategy has earned real money, and confirm the
ingestion pipeline is actually alive. Success is that the operator can tell, in seconds and
without doubt, what the system is doing right now and whether to intervene.

## Positioning

Not a product. A single-operator control room for one specific pipeline, whose value is that
every number on it is traceable to this system's own database rather than to a vendor's
summary. Its edge over any off-the-shelf trading dashboard is that it shows the operator's own
models, own paper books, own fee-adjusted verdicts, and own kill switches.

## Operating Context

- Deployed on one EC2 instance behind CloudFront, served by a Python stdlib HTTP server
  (`data_pipeline/dashboard_server.py`), backed by RDS MySQL. Basic auth on every route; live
  execution controls sit behind a second password gate.
- Three surfaces today: Data Pipeline (ingestion health), Simulated Trading (five paper books,
  each starting at $100), Live Trading (real Kalshi account, per-strategy on/off switches,
  risk caps, open positions, orders).
- Background writers run as separate processes on a 20s/1m cadence. They can and do die
  independently of the dashboard; during this session two had been dead for 13 days while the
  UI kept rendering their last values as if current. Staleness is a first-class product fact,
  not an edge case.
- Live trading is currently off (`live_enabled=false` for every strategy). Turning it on is a
  deliberate, guarded act.

## Capabilities and Constraints

- **No build step, no framework, no bundler.** The entire UI is HTML/CSS/JS embedded in Python
  strings in one file and served by `BaseHTTPRequestHandler`. Any design must ship as plain
  CSS and vanilla JS inside that file. This is a hard constraint, not a preference.
- Charts are hand-rolled on `<canvas>` with fixed pixel widths today.
- Data arrives from three JSON endpoints (`/sim_metrics`, `/live_metrics`, `/health`) polled on
  a 10s interval, plus server-rendered pages for table browsing.
- Server-side metrics responses are cached 25s; CloudFront caches nothing (all TTLs 0).
- Real money: `live_trading_engine.py` places real orders when a strategy's `live_enabled` is
  true. Any control that could flip that must be unmistakable and deliberate.
- Terminology in use: in-sample / out-of-sample split at a "live cutoff"; edge = model
  probability minus ask; paper books are independent $100 accounts, not one portfolio.

## Brand Commitments

None. No logo, no name beyond "Kalshi Trade", no external identity to honor. The operator is
free to choose any visual direction.

## Evidence on Hand

All real, all from this system's own database — nothing needs to be invented or mocked:

- Five paper strategies with live records: `binary_theory_edge` (+$515.92, 377 trades, 74% win),
  `random_forest_high_conviction` (+$453.33, 437, 74%), `random_forest` (−$265.85, 7246, 53%),
  `logistic` (−$677.99, 8944, 46%), `naive_logistic_baseline` (−$719.46, 8394, 46%).
- Real Kalshi account cash (~$90.26) and a live record of 2 closed trades, −$1.82.
- Per-model prediction quality (brier, logloss), calibration buckets, execution slippage,
  equity/drawdown time series, open positions, orders, and a model-research run history.
- Fee-adjusted verdicts already computed per strategy (net of Kalshi taker fees).

Three of five paper strategies are deeply negative and auto-paused after a 6-month unattended
run. That failure is part of the honest record and must stay visible, not be styled away.

## Product Principles

1. **Answer "what is happening right now" before anything else.** Live execution is the front
   page; paper results are the archive behind it.
2. **Stale is a state, not a silence.** Any number whose writer has stopped must say so itself.
   A frozen value rendered as if current is the system's worst failure mode and has already
   happened twice.
3. **Real money looks different from paper money.** The live surface must never be mistakable
   for the simulator, at a glance, on any device.
4. **Density is a feature, not a cost.** One expert user, no explaining, no hand-holding — but
   density earned through hierarchy, not achieved by dumping every panel at equal weight.
5. **Every number is traceable.** Two panels showing the same quantity must agree, and where a
   figure is derived, the derivation stays inspectable.

## Accessibility & Inclusion

No externally imposed standard. Self-imposed floor, because the operator reads this on a phone
in bright light and on a 3440px monitor at a distance: text contrast must hold at small sizes,
state must never be carried by color alone (paused/active/stale each need a shape or a word),
and every control must be reachable and legible at 400px width.
