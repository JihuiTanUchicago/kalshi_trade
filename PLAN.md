# PLAN

## Current Codebase Knowledge

- `data_pipeline/` is the real system: ingestion (`forward_collector`, `coinbase_collector`, `feature_1m_collector`), feature building (`model_features_1m_builder`), simulated trading (`simulated_trading_engine`, `sim_portfolio_20s_updater`, `sim_repository`, `sim_config`), live trading (`live_trading_engine`, `live_portfolio_20s_updater`, `architecture/{contracts,risk_engine,execution_kernel}.py`), and the dashboard (`dashboard_server.py`).
- Root-level `clients.py`/`main.py`/`example.py` and the "Model Manager" feature (`sim_model_registry.py`/`sim_custom_model_backfill.py`) were removed - dead/unused legacy.
- Deployed on a single EC2 instance (`i-077d6f7873e7836ba`) behind CloudFront (`https://dehiuraiut9ro.cloudfront.net`), backed by RDS MySQL (`kalshi-trade-mysql`). `dashboard_server` runs under systemd (`kalshi-dashboard.service`, auto-restart); the other processes run via `nohup`/`setsid`.
- Each sim model runs its own independent $100 paper book (`sim_config.STARTING_CAPITAL`) so models can be compared fairly - they are not a shared portfolio.
- Live trading (`live_trading_engine.py`) is currently disabled (`live_enabled=False` in `live_settings`) and has zero open positions. Do not enable it without explicit, separate authorization.

## Known-critical incident (fixed 2026-09-12)

A MySQL connection drop on **2026-04-27** silently broke every long-lived-connection process that swallowed its own exceptions without reconnecting: `dashboard_server` (wedged ~Mar 13), `simulated_trading_engine`, `sim_portfolio_20s_updater`, `model_features_1m_builder`, `live_trading_engine`, `live_portfolio_20s_updater`. Each kept "running" (visible in `ps`) but stopped doing anything for ~4.5-6 months. All six now re-raise on error so the outer `while True` wrapper reacquires a fresh connection; `dashboard_server` additionally runs under systemd. `forward_collector`, `coinbase_collector`, and `feature_1m_collector` were never actually vulnerable - their error handlers make a DB call that fails fast on a dead connection, so they self-heal by accident.

Practical consequence: the 3 baseline sim models (`naive_logistic_baseline`, `logistic`, `random_forest`) have a real 6-month paper track record and it is **badly negative** (-$719, -$678, -$266 respectively as of 2026-09-12). The new risk gate (see below) auto-paused all three the moment it went live. There is currently no viable running strategy - see Action Plan.

## Risk management (added 2026-09-12)

- `sim_config.SimRiskSettings` (stored in the `sim_settings` table, key `risk_config`): `max_position_fraction` (cap new-position notional as a fraction of a model's own current equity, default 0.20), `max_drawdown_pct` (pause a model once its drawdown from peak exceeds this, default 0.30), `min_equity_floor` (hard floor, default $10).
- Drawdown is computed from `sim_equity_1m`'s own realized-PnL history (peak vs current), not the separate `sim_portfolio_20s` table - that keeps the gate working identically whether ticking live or replaying via `recompute_sim_metrics.py`.
- A paused model stays paused until explicitly cleared via `POST /sim_risk/resume {"model_name": ...}` - no silent auto-resume. Pause state is visible in `/health`'s `sim_summary.models[].paused`/`paused_reason`.
- Near-expiry (`time_to_expiry_sec <= 60`): blocks new entries and force-closes any open position at $0.99 (matches the README's long-standing claim, which the code never actually implemented until now).

## Strategy research findings (2026-09-12)

Built `research/` (successor to the deleted `work/` dir): `expiry_resolution.py` is the reusable
backtesting harness (chronological 60/20/20 split snapped to ticker boundaries so no contract
straddles a split - the original methodology's plain row-index split didn't guarantee this),
`expiry_resolution_sensitivity.py` and `fee_sensitivity.py` are diagnostic follow-ups.

Investigated: revisiting the expiry-resolution label (terminal YES/NO instead of next-minute
direction) that looked promising in the deleted `work/` research - but that result was on only
5 days of data (9 test trades). With the current ~6 months (62,755 eligible rows):

- Reproducing the original take-profit-scalp exit rule on the larger sample: all 3 models
  (logistic/RF/HGB) are **negative** on held-out test (663 and 404 trades respectively for
  logistic/RF, both net losers despite ~77-82% win rates) - the original 9-trade result was noise.
- Diagnosis: high AUC (~0.87) but negative PnL despite high win rate means the *signal* has real
  information but the *exit rule* (fixed $0.05 take-profit, uncapped downside otherwise) fights it.
- Switching to hold-to-settlement exits (monetizing the resolution prediction directly): the
  logistic model showed a broad, robust-looking positive-PnL plateau across both validation and
  test threshold grids (not a lucky single point) - genuinely the most interesting finding.
- **But it does not survive transaction costs.** Gross test PnL was +$0.87 over 442 trades
  (+$0.002/trade). Even a 1% fee rate (well below Kalshi's actual schedule, which scales with
  `price*(1-price)` - highest exactly where these trades enter) flips it to **-$0.30 net**; at
  ~7% it's -$7.32. RF/HGB didn't replicate the effect under the same exit style either, which is
  a further reason not to trust it even before the fee check.

**Verdict: no candidate from this thread clears the bar.** This was a real, rigorous negative
result, not a lack of effort - see `research/` for the full methodology if revisiting this later.

### Follow-up checks on the existing production models (2026-09-12)

Two cheap retrospective checks on the ~24k real historical closed trades already in `sim_trades`,
before building anything new:

- `research/volatility_regime_check.py`: bucketed each model's trade PnL by `cb_vol_5m` quintile
  at entry. **Ruled out** - losses are roughly uniform across all 5 volatility regimes for all 3
  models; this isn't a "the models only fail in choppy/calm markets" problem.
- `research/pnl_distribution_check.py`: `random_forest` has win_rate > 50% in every volatility
  quintile yet still loses money in every one - looked like a fat-tail/stop-loss-fixable problem.
  **Ruled out on inspection**: loss/win ratio is only 1.16x (avg loss $1.78 vs avg win $1.53), and
  the worst 1% of trades account for only 6.2% of total losses (worst 10% account for 43.2% - a
  smooth distribution, not outlier-driven). `random_forest` is running almost exactly at its
  breakeven win rate (~53.7% needed given the 1.16x loss/win ratio; achieving ~52-53%) - a small,
  structurally persistent negative edge after spread costs, not a few bad trades a stop-loss would
  catch. This model needs a genuinely more accurate signal to cross breakeven, not better risk
  management.

### Fourth check: edge magnitude (2026-09-12) - the one live candidate

`research/edge_magnitude_check.py`: bucketed each model's historical trades by edge magnitude
(`prob_yes - ask`) at entry. For `random_forest` specifically, PnL rose monotonically with edge -
the top quintile (edge > ~0.167) was the only clearly profitable bucket (+$89.40/1449 trades,
+$0.062/trade avg), with a positive edge-PnL correlation. `logistic`/`naive_logistic_baseline`
showed no such pattern (if anything the opposite).

**Caveat found via `research/edge_magnitude_time_split_check.py`**: all 1449 of those trades fall
between 2026-03-07 and 2026-04-27 - the entire window before the connection-drop incident froze
the engine for ~5 months. There is zero out-of-sample evidence since, and the effect visibly
decayed within that window (March avg +$0.125/trade -> April avg +$0.006/trade). Not enough to
call this validated from backtesting alone.

**Decision**: rather than mine the same limited historical window further, added
`random_forest_high_conviction` as a new sim-only model (`simulated_trading_engine.py`,
`ALL_MODELS`) - reuses `random_forest`'s exact probability output unchanged, just requires
`edge > HIGH_CONVICTION_EDGE_THRESHOLD` (0.17, in `sim_config.py`) instead of the base 0.01. Runs
its own independent $100 book, subject to the same risk gate as every other model. This tests the
hypothesis forward on genuinely new data instead of re-analyzing the same 7-8 weeks. Deployed and
verified live 2026-09-12 (fresh $100 equity, not paused, correctly reusing random_forest's prob).
**Check back on this model's real forward performance before drawing any conclusion from it.**

### Fifth/sixth checks: open_interest and two-sided quotes (2026-09-12)

`research/two_sided_quote_check.py`: `open_interest_fp` was already flowing through
`model_features_1m_builder.py` (queried, never used) - tested it as an added feature via
time-series-CV logistic regression. **Negligible**: AUC delta +0.0010, not worth pipeline changes
on its own.

Also tested the NO-side quotes (`no_bid_dollars`/`no_ask_dollars`) as a potential
mispricing/liquidity signal (`(yes_ask+no_ask)-1.0` gap, etc.) - found these were only present in
0.67% of historical rows (403/60,000), too sparse to test. Root cause: `forward_collector.py`
stored the partial WebSocket ticker message as `raw_json` whenever available, which doesn't carry
the NO side, discarding the fuller REST market object that does. **Fixed** (not just diagnosed):
added `no_bid_dollars`/`no_ask_dollars` as explicit `forward_quotes` columns, populated via the
same `_pick_value(ws_msg, m, ...)` fallback already used for `open_interest_fp` - the REST market
object is fetched every 20s regardless of WS availability, so this gives near-100% coverage going
forward. Deployed and verified: fresh rows now show consistent two-sided quotes
(e.g. yes_bid=0.33/yes_ask=0.34, no_bid=0.66/no_ask=0.67 - correctly complementary, no gap in this
sample). **Needs days/weeks to accumulate enough volume for a real test** - this is infrastructure
for future research, not a finding yet.

### Seventh check: fine-grained realized volatility (2026-09-12)

`cb_vol_5m` (the only volatility feature) is computed from just 5 once-per-minute Coinbase price
samples, despite `coinbase_ticks` already being collected every 20 seconds (~74 samples available
in the same window) - a concrete "smart use of existing data" candidate needing zero new
collection. Tested two proper realized-volatility estimators from the quant-finance literature
(not ML - this was a deliberate move away from defaulting to logistic/RF for everything):
realized volatility (`RV = sqrt(sum(r_i^2))`, the standard high-frequency estimator) and an
EWMA-weighted variant. **Clean negative**: both correlate 0.86 with the existing coarse estimate
(same underlying signal, just smoothed differently) and AUC deltas were all ~0.0001-0.0002 -
noise. 20-second-level data isn't the bottleneck for this particular feature; the coarse version
was already adequate. See `research/fine_grained_volatility_check.py`.

### Eighth check: binary-option theory - a non-ML approach (2026-09-12)

Per explicit feedback that logistic/RF was too narrow a toolkit: derived a closed-form fair
probability from options theory instead of fitting anything. Model: BTC follows a driftless GBM
over the contract's remaining life; for a binary paying $1 if `S_T >= K`,
`P(YES) = Phi(ln(S_0/K) / (sigma*sqrt(T)))` - the Black-Scholes d2 term without the risk-neutral
drift correction, since this is a physical-measure probability question, not derivative pricing.
sigma comes from the existing `cb_vol_5m` scaled to the contract's own time-to-expiry. Zero
fitting, zero training data needed - see `data_pipeline/binary_theory.py` (production) and
`research/binary_option_theory_check.py` (validation, same formula, kept in sync intentionally).

**Result: matched ML-level standalone predictive power (AUC 0.858) with no fitting at all.**
Calibration showed a clear, systematic overconfidence bias (predicts 0.87 where only 0.775 of
that decile actually resolves YES, etc.) - consistent with a constant-volatility GBM
underestimating BTC's true tail risk. Filtered to only its largest mispricings (edge > 0.15,
`research/binary_theory_robustness_check.py`): 451 trades spanning the *entire* available window
(not just pre-incident, though that window is still only ~7-8 weeks + a few hours of fresh data -
same `model_features_1m_builder` outage gap noted above affects this dataset too), improving
rather than decaying (Mar avg +$0.0034/trade -> Apr avg +$0.0150/trade), and survived up to ~3%
simulated fees (vs. 1% for the earlier `random_forest` candidate) before turning negative.

**Decision**: this is the strongest candidate found this session by a meaningful margin - matches
an independent ML-based finding (large mispricings being where the edge lives) via a completely
different, non-fitted methodology, which raises confidence it's a real market feature rather than
one model's artifact. Deployed `binary_theory_edge` as a new sim-only model (own $100 book, same
risk gate, `HOLD_TO_SETTLEMENT_MODELS` exit style - never closes early on signal decay, only via
near-expiry force-close-at-$0.99 or ticker rotation, since the backtest's "hold to true settlement
price" isn't available live without lookahead). Deployed and verified live 2026-09-12: computing
a distinct probability every tick (confirmed different from the ML models'), fresh $100 equity,
not paused. **Still needs real forward time before treating this as validated** - same discipline
as `random_forest_high_conviction`.

### Ninth check: Kalshi's real tick size, fee formula, and a production incident (2026-09-12/13)

**Tick size correction.** Assumed (and the README documented) a flat $0.01 tick with a
force-close-at-$0.99 near-expiry floor. User feedback + our own `forward_quotes` history
disproved this: real quotes on `KXBTC15M-*` go down to $0.001 increments, observed across the
*entire* price range (not just near 0/1 - e.g. `0.042/0.049`, `0.977/0.979` bid/ask pairs from
2026-09-13, and non-whole-cent rows going back to 2026-03-17, ~648k of them). The near-expiry
force-close logic in both `simulated_trading_engine.py`/`sim_repository.py` and
`live_trading_engine.py` was hardcoding the exit at exactly $0.99 *even when a real bid was
available*, discarding real quotes as good as $0.999 on a winner and, more seriously, forcing a
flat $0.99 floor on a position that might legitimately be losing near expiry (this matters most
for `binary_theory_edge`, the one hold-to-settlement model that can actually reach near-expiry
while losing). Fixed: both now try the real current bid first via `best_bid_snapshot` and only
fall back to the $0.99 floor when no quote exists at all (empty ladder - the original, narrower
intent of that fallback). See `data_pipeline/sim_repository.py::close_existing_position` and
`data_pipeline/live_trading_engine.py`'s near-expiry branch.

**Fee formula correction.** The new Portfolio Manager "recommendation status" label
(`get_model_recommendation_status` in `sim_repository.py`) initially used a flat assumed 3% fee
rate. Corrected to Kalshi's actual published formula (taker: `ceil_cent(0.07*C*P*(1-P))`, maker:
`ceil_cent(0.0175*C*P*(1-P))`, source: kalshi-fee-schedule.pdf) in the new
`data_pipeline/kalshi_fees.py`, using `Decimal` (not float) for the cent-rounding so it doesn't
misround Kalshi's own documented $1.75-per-100-contracts peak example. The sim engine crosses the
book on both entry and exit (buys at ask, sells at bid), so both legs are fee'd at the taker rate.

**Also found while wiring the recommendation feature into the dashboard**: `get_model_recommendation_status`
was imported by `dashboard_server.py` but had gone missing from `sim_repository.py` (lost in an
earlier fork-merge conflict resolution this session) - the dashboard was crash-looping on every
deploy attempt with an `ImportError` until this was caught and re-added. Lesson: `py_compile`
does not catch a missing import target; added a quick AST-based cross-file import check as a
pre-deploy sanity step (not a saved script, just something to re-run before future deploys).

**Production incident: RDS `max_connections` exhaustion (2026-09-13, ~05:00-05:25 UTC).**
While redeploying the above, the dashboard and both trading engines were restarted, which surfaced
a real, unrelated bug: `sim_portfolio_20s_updater.py`/`live_portfolio_20s_updater.py` run
`SELECT MAX(peak_equity_dollars) FROM sim_portfolio_20s WHERE model_name=...` every ~20 seconds,
forever, against an append-only table that's now ~6 months deep - no index on
`peak_equity_dollars`, so this became a slow full scan per model per tick. Once one tick got
slow, the next tick's query queued up behind it (and the one after that), each opening its own
connection, on a small RDS instance with `max_connections=60` - a classic thundering-herd pileup
that eventually exhausted every connection slot and broke `/health` and other reads with `(1040,
'Too many connections')`. Fixed at the root: added covering indexes
(`idx_sim_portfolio_model_peak (model_name, peak_equity_dollars)` on `sim_portfolio_20s`,
`idx_live_portfolio_peak (peak_equity_dollars)` on `live_portfolio_20s`) so the `MAX()` is answered
via a loose index scan instead of a full scan - see the migration block in `init_schema.py`.
Immediate mitigation while the index built: killed the stuck queries via `KILL <id>` and briefly
stopped both `*_portfolio_20s_updater` processes so they'd stop adding to the pileup, then
restarted them once the index was in place. No trading logic or sim/live positions were affected -
this only touched the 20-second equity-snapshot cache tables, not `sim_trades`/`sim_positions`.
**Follow-up worth doing eventually**: this class of "unbounded re-scan of an ever-growing
append-only table" is a pattern, not a one-off - worth auditing `dashboard_server.py`'s other
aggregation queries (`table_counts()`, `sim_metrics()`) for the same shape before the next
multi-month milestone.

## Action Plan

1. **Monitor the two live, unvalidated strategy candidates** - give both real time to accumulate
   trades before judging either; a handful of trades proves nothing:
   - `random_forest_high_conviction` (edge > 0.17 filter on the existing random_forest signal)
   - `binary_theory_edge` (closed-form GBM probability, edge > 0.15, hold-to-settlement exit)
   Check `/health`'s `sim_summary`, the dashboard's Portfolio Manager panel, or query
   `sim_trades WHERE model_name IN (...)`.
2. **Let the no-side-quote data accumulate**, then test the two-sided-quote-gap hypothesis properly
   once there's a real sample (see `research/two_sided_quote_check.py` - already handles the
   `require_no_side` case, just needs enough post-2026-09-12 rows).
3. **Further strategy research**: eight hypotheses tested this session - six cleanly ruled out
   (expiry-resolution label, volatility-regime conditioning, stop-loss/tail-risk, open_interest,
   fine-grained realized volatility) and two deployed forward (above). Untested if continuing:
   calibration-weighted ensembling of the 3 base ML models (lower confidence - they share similar
   structural issues), GARCH-style conditional volatility (likely redundant given RV/EWMA already
   correlate 0.86 with the coarse estimate), or a genuinely different feature/label/asset-class
   angle. Not ML-only - traditional stats and closed-form finance are proving at least as useful
   here (see the binary-option-theory result above).
4. **Live trading remains off** (`live_enabled=False`) until a strategy demonstrates a real,
   validated, fee-adjusted edge over a statistically meaningful forward sample - not before.
5. **Ongoing monitoring**: report back on sim portfolio health regularly (equity, drawdown, any
   pause events, new-candidate progress) rather than letting it run silently unwatched - that
   silence is exactly what let the April 27 incident go unnoticed for months.
6. **UI**: Portfolio Manager panel shipped (equity/PnL/pause-status per model + a resume button,
   `/sim_risk/resume`) and verified visually in-browser. Still open: manual trigger buttons for
   recompute/model-guard-refresh/re-run-research, further visual cleanup of the older panels.

### Hourly check 2026-09-16 13:39 UTC - dashboard unreachable, now a 3+ day outage of this routine

`curl https://dehiuraiut9ro.cloudfront.net/health` fails at TLS CONNECT with `403` from the
session's egress proxy; `$HTTPS_PROXY/__agentproxy/status` confirms it's a policy denial
(`connect_rejected`, "gateway answered 403 to CONNECT"), not a transient/dashboard-side outage.

This is not a new finding - every hourly run since **2026-09-13 07:38 UTC** (the first check after
the production-infra merge landed at 06:46 UTC) has hit this identical 403 and recorded it on its
own throwaway branch (`research/*-blocked`, `research/hourly-check-*-blocked`,
`scheduled-check/*-blocked`, etc. - ~25+ separate branches as of this run). None of those branches
were ever merged to `main`, so `main`'s `PLAN.md` still only reflects the 2026-09-12/13 research
session and carries no record of this outage at all unless you look at branches directly. **As of
this run, the routine has been unable to reach the dashboard for over 3 days straight (~79+ hours,
dozens of runs) - zero monitoring of `sim_metrics`/model pause status and zero new research this
entire window.** Neither Part 1 (candidate monitoring) nor Part 2 (new research angle) could be
attempted, same as every run since the 13th. This needs a human to update the session's network
egress allowlist to permit `dehiuraiut9ro.cloudfront.net:443` - no action available from inside
this sandbox (no AWS/SSH access, and the proxy denial is enforced outside this session).

**Process note for whoever reviews this**: since these check branches never reach `main`, future
runs re-discover this same blocker from scratch every hour with no way to see prior attempts'
detail beyond branch names. Once the network access is fixed, it would be worth merging (or at
least squash-summarizing) the useful `research/*` branches' `PLAN.md` entries back into `main` so
the dated-entry history the task instructions rely on ("read PLAN.md's dated entries first") is
actually visible from `main` going forward.

## Open Items / Follow-ups

- `live_trading_engine.py` and `live_portfolio_20s_updater.py` got the same reconnect fix as their sim counterparts (explicitly approved) - this only affects DB reconnection behavior, no change to trading/risk logic.
- The leaked `client_api` password (`kalshimakesmepoor`, hardcoded in `client_api/client.py` and `client_api/README.md`) was intentionally left as-is per explicit instruction - not rotated.
- `venv/` was untracked from git (was previously committed - 7500+ files); `.gitignore` updated. Files remain on disk, only git tracking changed.
