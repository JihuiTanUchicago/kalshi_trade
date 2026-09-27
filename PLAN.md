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

## Dashboard PnL/equity consistency (fixed 2026-09-26)

Two panels on the Simulated Trading tab reported numbers that contradicted the PnL next to them.
Both were display bugs - no sim/trade data was wrong.

1. **Portfolio Manager cards** printed `equity` from the newest `sim_portfolio_20s` row (whole
   table, no recency bound) next to a `total_pnl` summed live from `sim_trades`. Those are two
   different processes: the 20s updater is a separate daemon and it `continue`s (writes nothing)
   for the whole duration of a `recompute_sim_metrics.py` run, so its last row goes stale while
   `total_pnl` keeps moving - producing e.g. `binary_theory_edge` showing `$108.42` above
   `Total PnL: +$521.66`. Paused models looked fine only because nothing was closing for them.
   `dashboard_server.build_scorecards()` now derives equity as
   `STARTING_CAPITAL + total_pnl + unrealized`, from the same closed-trade rows as the PnL, with
   unrealized/position value taken from the open-position rows the endpoint already builds (no
   extra queries). Side effect: a model with trades but no `sim_portfolio_20s` snapshot yet now
   gets a card instead of silently vanishing from the panel. Covered by
   `tests/test_dashboard_scorecards.py`.
2. **Per-model segment cards** (`Current` / `In-Sample` / `Out-of-Sample`) took their `$` figure
   from the endpoint of the rebased equity series that feeds the charts. Those series only cover
   the last `window_hours` (6) and are rebased so their first point is `$100`, so the card was
   showing "change over the visible window" - `$0.00` for an idle/paused model - labelled as the
   segment's total PnL, next to `closed 8099`. `renderSegmentSummary()` now reads `total_pnl`
   from the `d.in_sample` / `d.out_of_sample` trade aggregates (which sum exactly to the
   Portfolio Manager card's total), and computes equity as `100 + pnl`.

The equity *charts* still come from `sim_portfolio_20s`/`sim_equity_1m` and will still flatline if
the 20s updater is down. The Live Trading tab's equity is deliberately left alone: it comes from
the real Kalshi cash balance (`get_kalshi_cash_balance_dollars`), so it is genuinely not
`$100 + PnL`.

**Root cause of the stale number, confirmed on the box:** `sim_portfolio_20s_updater` had been dead
since **2026-09-13 06:27:40** (13 days; absent from `ps`, last row in `sim_portfolio_20s` at that
timestamp) while `sim_trades` kept closing trades through 2026-09-26. `live_portfolio_20s_updater`
was also down and was left down. Neither runs under systemd - only `dashboard_server` does - so
nothing restarted them. **Worth doing:** put the remaining `nohup`/`setsid` processes under systemd
units too, so a crash doesn't silently freeze a panel for weeks. This is the same failure shape as
the April 27 incident above, just with a process that stays dead instead of a wedged connection.

Deployed 2026-09-26 22:51 UTC: `data_pipeline/dashboard_server.py` copied to `/opt/kalshi` via SSM
(backup at `dashboard_server.py.bak.20260926_225140`), `kalshi-dashboard.service` restarted, and
`sim_portfolio_20s_updater` restarted. Verified against production: every card now satisfies
`equity == 100 + total_pnl + unrealized`, and in-sample + out-of-sample PnL sums to the card total.
CloudFront (`E3W0CV5JMD953I`) has all TTLs at 0, so it caches nothing - no invalidation needed.

## Live Trading tab was blank (fixed 2026-09-26)

`/live_metrics` was returning **HTTP 500** on every request:
`pymysql.err.ProgrammingError: (1146, "Table 'kalshi_trade.live_model_state' doesn't exist")`, raised
by `get_all_live_pause_states()`. The table is defined in `init_schema.py` but the production DB
never got it - `init_schema` only runs at instance launch and the table was added to the file after
that. The front-end did `if(!r.ok) return;`, so the entire tab (strategy toggles, account block,
all three 20s charts, orders/trades tables) rendered as empty with no error anywhere. Fixed by
running `python -m data_pipeline.init_schema` on the box (additive/idempotent; the only DROP is a
PK reshape on `live_positions`, guarded on that table being empty).

`live_portfolio_20s_updater` was also down and is now running. Note it needs **both** env files -
`/opt/kalshi/.env.aws` (MySQL) and `/opt/kalshi/.env` (`PROD_KEYID`/`PROD_KEYFILE`) - or
`get_kalshi_cash_balance_dollars()` returns None and the snapshot silently falls back to
`cash_source=local_fallback` (an estimate, not the real balance). The currently-running
`live_trading_engine` has only the MySQL vars in its environment, so it is in that fallback state
too. Real account cash as of 2026-09-26 23:02 UTC: **$90.26**, `cash_source=kalshi_api`.

Both metrics endpoints now surface failures instead of swallowing them: `setFetchError()` paints a
banner at the top of the tab naming the endpoint and status, and distinguishes the legitimate 403
live-password gate from a real server error. A blank tab reading as "no data yet" is exactly what
hid this 500.

## Dashboard access control (closed 2026-09-26)

The whole dashboard was world-readable: `DASHBOARD_PASSWORD` was unset and `_authorized()` returns
True when it is unset, and the EC2 security group exposed port 8080 to `0.0.0.0/0`, so both the
CloudFront URL and the raw origin `http://54.156.90.14:8080` answered 200 to anyone. Now:

- **Basic auth on every route.** `_authorized()` is the first statement of both `do_GET` and
  `do_POST`, so one password covers pages, `/sim_metrics`, `/live_metrics`, `/health`, `/table`,
  `/api/table` and every POST. A 24-char random password now lives in `/opt/kalshi/.env.dashboard`
  (root:root, `chmod 600`) and the systemd `ExecStart` sources it alongside `.env.aws`. It is
  deliberately NOT in the unit file, which is world-readable in `/etc`, and not in this repo.
  To rotate: edit that file and `systemctl restart kalshi-dashboard`.
- **Origin no longer public.** Port 8080 ingress is now AWS's managed CloudFront prefix list
  (`pl-3b927c52`, `com.amazonaws.global.cloudfront.origin-facing`) plus the owner's `73.186.198.44/32`;
  the `0.0.0.0/0` rule is revoked. Normal traffic is HTTPS via CloudFront, so Basic credentials no
  longer cross plain HTTP in the open. CloudFront already forwards the `Authorization` header.
- Verified: unauthenticated `-> 401`, wrong password `-> 401`, wrong user `-> 401`, correct `-> 200`;
  the separate live-execution gate still returns 403 without `live_password`, so live controls keep
  their second factor.

**Consequence:** `client_api/client.py` defaults to `password="kalshimakesmepoor"` and now gets 401.
Pass the new dashboard password (or better, read it from an env var) when using that client.

## Live strategy settings were not in force (fixed 2026-09-26)

The Live Trading tab's per-strategy settings form was writing to rows nothing read. Three causes,
all in the deployment rather than the code:

1. **The running engine was the pre-multi-strategy build.** PID 2099628 started `Sun Sep 13
   05:11:53`; the new `live_trading_engine.py` landed at `06:16:20` - an hour later. Python had the
   old module in memory, and the outer `while True` retry wrapper re-enters `run_loop()` without
   re-importing, so the file update never took effect. Tell-tale: it logged
   `live trading engine started (RF-only).` where current code logs `(multi-strategy: ...)`.
2. **The old build read a different row.** `load_settings(cur)` there was
   `SELECT ... WHERE settings_key='live_config'` - one global row, last updated 2026-03-07 - while
   the UI writes per-model rows. So the UI showed `edge_threshold 0.15` for `binary_theory_edge`
   while the engine was using `0.01` from `live_config`, plus `max_trade_cost 8.0` vs the UI's 2.0.
3. **The old build hardcoded `model_name="random_forest"`**, so the other two strategies were not
   live-traded at all and their cards controlled nothing.

Restarted the engine (with **both** env files, same lesson as the 20s updater). It now logs
`multi-strategy: random_forest, random_forest_high_conviction, binary_theory_edge`, ticks all three,
and `migrate_legacy_settings()` dropped the stale `live_config` row. All `live_enabled` remain
`false` - nothing trades. Confirmed in force on the first tick: `binary_theory_edge` prob 0.847,
edge 0.097 against its `edge_threshold` 0.15 -> `signal=False`.

Settings wiring in current code, verified end to end - every field on the form is consumed, and
`cfg = load_settings(cur, model_name)` sits inside the per-tick per-model loop, so saves take
effect on the next tick with no restart:

| field | consumed at |
|---|---|
| `signal_threshold` | `live_trading_engine.py:414` (signal) |
| `edge_threshold` | `:414` signal, `:217` sizing gate, `should_close_position` |
| `max_trade_cost` | `:219` `compute_buy_qty` |
| `max_concurrent_positions` | `architecture/risk_engine.py:26` |
| `max_open_notional` | `architecture/risk_engine.py:28` |
| `max_daily_loss` | `:200` -> RED -> auto-pause |
| `max_total_drawdown` | `:202` -> RED -> auto-pause |

`LiveSettingsRiskEngine` (not `DummyRiskEngine`) is the active one: `RISK_ENGINE_MODE` is unset
anywhere in the repo or on the box, and defaults to `live_settings`.

**Standing lesson:** a file copy is not a deploy for anything long-running. After updating
`data_pipeline/*.py` on the box, restart the process that imports it, and confirm by its startup
line rather than by the file's mtime.

Live strategy cards now also show that strategy's **Sim PnL** (`sim_total_pnl`/`sim_closed_trades`/
`sim_win_rate` on each `/live_metrics` `models` entry), read from `sim_trades` with the same query
shape as the Portfolio Manager so the two panels cannot disagree.

## Dashboard redesign: Kursbuch (2026-09-26)

The dashboard was rebuilt as a replacement visual world, not a polish pass. Product truth is now
recorded in `PRODUCT.md`; the durable route strategy lives in
`.impeccable/surfaces/data-pipeline-dashboard-server-py.md` (direction contract, seed key
`abd048b8`). Visitor mode: **Operate**. Confirmed by the owner: the primary job is *watching real
money move*, the audience is *only him*, and ultrawide, laptop and phone are all first-class.

**World.** A Swiss station timetable, not a trading terminal. Grey newsprint stock (`#E9EBE5`), ink
that is never pure black (`#191B16`), hairline rules at one weight, tabular lining figures
everywhere, and **no monospace anywhere** - the terminal look was the category rut and it was also
the incumbent. One reserved signal red (`#C8102E`) that appears nowhere except "this needs you";
money direction rides a desaturated tint field behind the figure, never the reserved red. The live
surface prints on a tinted stock (`#EFE4E7`) with a red head rule, the way a timetable tints a
different service, so real money can never be mistaken for the simulator. Archivo / Archivo Narrow,
two weights. Cards are gone: every panel is a ruled table, because cards at equal weight were why
nothing told you where to look.

**Signature interaction - the as-of rule.** Every section states the age of the writer behind it.
When that writer stops, the rule under its heading breaks to dashed red, the figures strike through
and mute, and a red `STALE 13d` mark states the age. This is the direct structural answer to the
failure that opened this session: two writers dead for 13 days while the UI rendered their last
values as current. It needed new server data - `/sim_metrics` and `/live_metrics` now return a
`writers` map (`last_utc`, `age_sec`, `expect_sec`, measured against the **database** clock so a
skewed server cannot invent freshness) plus `generated_at_utc`. Staleness is declared at
`WRITER_CADENCE_SECONDS` x `STALE_CADENCE_MULTIPLE` (6).

**Other structural changes.**
- `/` now defaults to **live-trading**, not data-pipeline. Live execution is the front page because
  that is the operator's first question.
- A status line above every page states the dominant answer in words before any figure is read
  ("Live trading off / No open positions / All writers current"), red only when it needs him.
- The pipeline tab's expensive queries (`table_counts`, `forward_feed_health`, `latest_model_guard`)
  no longer run on every page load, only on the tab that shows them. The unused `sim_summary()` call
  was dropped from the request path entirely.
- Responsive: tables restack into labelled rows below 640px; plates go 2-up at 1500px and 3-up at
  2200px; the page runs to 2560px instead of 1200px so an ultrawide is not a column in a void.

**Verification.** Built code-led (no image generation in this harness). Inspected in one batched
round at ultrawide, laptop and 390px phone, plus a deliberately-aged fixture to audit the stale
path. The mechanical detector went 166 -> 4 findings; the four that remain are the detector summing
sibling micro-labels on the `.measure` and `.plates` rows, where each label is 8-27 characters, and
were a deliberate keep. Contrast was computed, not eyeballed: muted ink clears 4.5:1 on all three
grounds.

**Two traps worth remembering.**
1. The production box runs **Python 3.9**: an f-string expression cannot contain a backslash there.
   Local Python 3.14 accepts it silently. The deploy's `py_compile` step caught it before install.
2. A local harness (`scratchpad/harness.py`) serves the real handler against captured production
   JSON with auth disabled. That is how this was inspected without pointing a browser at the live
   box or triggering a basic-auth modal. Fixtures come from SSM, which truncates output at ~24KB, so
   they are subsampled and fetched in two chunks.

## Strategy dossiers + finish-review fixes (2026-09-26)

**Strategy dossiers.** Each book on the Simulation tab now links to `/?tab=strategy&name=<model>`,
a Read-mode page inside the Operate app (`.reading`, 1060px measure) that states what the strategy
actually is. Content lives in `STRATEGY_DOSSIER` / `SHARED_LABEL` / `SHARED_LIFECYCLE` in
`dashboard_server.py`, written from the engine source rather than from memory: the tradeable label
(`1 if next_minute_yes_bid > this_minute_yes_ask else 0`, from `build_supervised()`), the exact
feature subsets, the real estimator hyper-parameters, the per-strategy edge thresholds, and the
research finding behind each candidate. **If the engine changes, this dossier must change with it —
a dossier that has drifted from the engine is worse than none.**

Worth knowing, because the dossiers now say it out loud: `random_forest_high_conviction` is not a
separate model at all (it re-uses `random_forest`'s probability and only raises the entry bar to
edge > 0.17), and `binary_theory_edge` fits nothing (closed-form driftless-GBM
`P(YES) = Phi(ln(S0/K) / (sigma*sqrt(T)))`, and it holds to settlement rather than exiting on
signal decay).

**Finish review.** The shipped `impeccable-finish-reviewer` refused the first pass outright because
it was given source instead of rendered pixels — correctly. Captures now live in
`.impeccable/review/`. Of its eight material findings, seven were real and are fixed:

1. The stale strike shipped invisible — 1px in `--rule-2` over a muted glyph. Now 2px in `--ink-2`.
   Half the signature interaction was not reaching the eye.
2. **The Data Pipeline tab had no as-of rule at all**, and hardcoded captions ("last 120 minutes")
   sat in the exact slot every other tab uses for writer age — so the one surface whose job is
   "confirm the pipeline is alive" was the only one that could not go stale. `/health` now returns
   `writers` via `pipeline_writer_freshness()`, and the feed and guard sections are wired to it.
   The masthead clock on that tab is fixed too (it read `READING...` forever).
3. Drawdown axes printed raw unitless floats (`-2848.6229`). Both now pass `unit:'$'`.
4. `--neg` was invisible on the rose live stock: money read in one direction only, on the one
   surface where a loss is the fact that matters. `body.live-service` now overrides both tints.
5. The status line was capped at 104ch, so the "full-width" promise broke; the rule now spans and
   only the sentence is capped. `.measure` tracks are capped so figures spread rather than stranding.
6. **No more `window.confirm` / `window.alert` anywhere.** A browser dialog states no recovery and
   belongs to no design system. Destructive live actions now arm in place (click once to arm, again
   within 6s to fire) and every outcome reports through an in-page `.notice`.
7. On phone the strategy rows exploded into eight label/value lines with the switch at the bottom.
   The switch is now lifted directly under the name, prob/edge/signal are hidden behind the
   existing disclosure, and rows carry **leader dots** — the timetable device that ties a label to
   its figure across a gap, and one of the FORM block's own named donations.

The eighth finding — a duplicated disclosure row — was **not** a bug. It was an artifact of my own
stitched full-page capture: I screenshotted at `scrollY=840` with an 840px viewport, so the boundary
row appeared at the bottom of segment 1 and the top of segment 2. Verified in the DOM: 6 rows, 3
disclosures, stable across re-renders. Recorded here so nobody "fixes" it later.

Still open from the ceiling check, honestly: bar-length-as-duration is unbuilt, and the tint-field
wash (the one authored motion moment) is coded but never captured, so it stands unverified.

DESIGN.md is now written from the shipped build by the shipped documenter, with `.impeccable/design.json`
alongside it.

## Two live-path bugs found by the over-engineering review (fixed 2026-09-26)

Found while counting duplication, not while looking for bugs:

- **The Close button on a live position always 403'd for a URL-password session.**
  `/live_position/close` was the only live route calling `self._live_authorized()` with no `parsed`,
  and `closeLivePosition()` was the only live POST that did not append `?live_password=`. The two
  defects hid each other: closing worked only if the `live_gate` cookie happened to be set. This is
  the control that manually exits a real-money position, so it is the last one that should be
  unreliable. Both halves fixed; no bare `_live_authorized()` call remains.
- `_authorized()` compared the dashboard password with `==`. Now `secrets.compare_digest`.

## CloudFront was rejecting every POST (fixed 2026-09-26)

**No control on the dashboard had ever worked through the public URL.** The distribution
(`E3W0CV5JMD953I`) was configured `AllowedMethods: [HEAD, GET]`, so CloudFront rejected every POST
with its own 403 - "This distribution is not configured to allow the HTTP request method that was
used for this request" - before the origin ever saw it. That silently disabled: save caps, the live
on/off switch, clear-halt, resume a paused sim book, close a live position, and manual orders.

Fixed by setting `AllowedMethods` to the full seven-method set while leaving `CachedMethods` at
`[GET, HEAD]` and all TTLs at 0. The pre-change config is preserved for revert. Verified: a POST
probe with a deliberately invalid `model_name` went 403 -> 400, meaning auth now passes and the
handler is the thing rejecting it; a real no-op save of `binary_theory_edge`'s existing caps
returned `ok: true` with `live_enabled` untouched.

Related and still true: the distribution also sets `Cookies: Forward: none`, so the `live_gate`
cookie is stripped and can never authorize anything in production. Only `?live_password=` in the
query string works - which is what the front-end sends. Do not "simplify" the live gate down to the
cookie path; through CloudFront it does not exist.

**Config panel no longer disappears mid-edit.** `renderLiveStrategyCards` re-renders every 10s so
prob/edge stay live, which was wiping an open settings panel and anything half-typed in it. Open
state, edited values and the caret are now captured and restored around the re-render, and a
successful save clears the pending-edit record. Reading `selectionStart` is guarded: number inputs
do not support selection and throw.

**Strategy dossiers now carry the math and the algorithm.** Formulas are native MathML - no KaTeX,
no CDN, nothing to load, so they render on a page whose job is telling you when things are broken.
Each dossier carries its decision formula, the probability step in pseudocode, and a shared
"one tick, end to end" block in the order `process_model_tick` actually runs it. A separate block
records that **live sizing is not paper sizing**: live has no `MAX_QTY` and no cash check, so the
cost cap is the only bound and a $0.05 ask buys 40 contracts for the same $2.

Monospace is used in those pseudocode blocks, which DESIGN.md's No-Monospace rule otherwise bars.
The rule is about monospace as technical costume; pseudocode is code, where indentation carries the
structure. Scoped exception, recorded rather than silently broken.

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

## Open Items / Follow-ups

- `live_trading_engine.py` and `live_portfolio_20s_updater.py` got the same reconnect fix as their sim counterparts (explicitly approved) - this only affects DB reconnection behavior, no change to trading/risk logic.
- The leaked `client_api` password (`kalshimakesmepoor`, hardcoded in `client_api/client.py` and `client_api/README.md`) was intentionally left as-is per explicit instruction - not rotated.
- `venv/` was untracked from git (was previously committed - 7500+ files); `.gitignore` updated. Files remain on disk, only git tracking changed.
