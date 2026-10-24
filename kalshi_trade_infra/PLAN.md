# PLAN

## Research RSI: paper outcomes close the loop (2026-10-24)

- The scoreboard only counted what passed the backtest gate. `rsi.paper_outcomes(cur, uid)` adds what
  survived realistic paper fills, keyed by `rsi.family` like the scoreboard: strategies on paper, how
  many have traded, realistic round trips, net P&L after fees, realization (paper net over the
  trip-weighted backtest unseen-data P&L per trade) and how many cleared the paper gate. `by_playbook`
  credits each strategy to the playbook its research run drew (app_strategies.run_id ->
  app_rsi_assignments.run_id), so a playbook whose passes bleed on paper stops looking like a winner.
- Shown under `paper` in `GET /api/research/scoreboard`, and as one line per family in the autopilot
  review context, which flags families whose paper strategies have never traded. One learning loop:
  the research thread's playbook scoring can read `by_playbook` instead of a second loop.
- Next: fold `by_playbook.realization` into playbook scoring once any family has 30+ paper trips.

## Research RSI: free mispricing scan steers where research goes (2026-10-24)

- `app/rsi_scout.py` loads each researchable binary market's RESEARCH window (its active partition, or
  the boundaries a first run would freeze, computed without saving) and runs the calibration and
  fair-value tables as data (`agent.calibration_cells`, `agent.fair_value_rows`). It stores lead counts
  (cells clearing 2 SE after fees) and the strongest lead in `app_rsi_scout`. No model calls.
- The autopilot review now sees the top 8 as "FREE MISPRICING SCAN", and `/api/research/scoreboard`
  returns the top 10 as `scout`.
- Scheduling: `scripts/systemd/tau-scout.{service,timer}` scans the 60 stalest markets every 2 hours
  (MemoryMax 1500M), so each market is rescanned about daily. The units are hand-installed on the
  web box (see scripts/systemd/README.md); until then run `python -m app.rsi_scout`.
- Many markets are scanned, so some leads are luck. It only orders where research looks first; the
  held-out gate still decides.

## Research RSI: a scoreboard, and playbooks the loop rewrites and A/B-tests (2026-10-24)

Todd: "make it really RSI". Until now the loop only evolved finalist selection (dreaming over replayed
trees); nothing measured whether research got better, and nothing learned what to propose. PLAN's own
2026-10-15 note named the missing piece: evolving proposal guidance needs an evaluator that replay
cannot give. Live runs are that evaluator.

- `app/rsi.py` (measure): a scorecard per run from its verdict events (explored, dropped, challenger,
  underpowered, not-finalist, gated, passed, holdout, deploy candidates, model spend) and a scoreboard
  in total / per family / per day: gate-reach rate, gated and passed per $100, and why ideas die. Drop
  reasons are classified by phrase rules built from real runs into pipeline (the pipeline failed the
  idea: "feature not available", no data), spec (0 trades), edge (loses, fee floor, falsified), other.
  `GET /api/research/scoreboard?days=` and `python -m app.rsi --days 7 [--user N] [--cards]`.
- `app/rsi_playbook.py` (learn and keep what helps): one playbook per (user, market family)
  (`rsi.family`: weather-high, weather-low, crypto, sports, ...). The proposer and the develop turn read
  the drawn playbook. After every run with ideas: the run is credited to the playbook it drew, the
  candidate-vs-active trial is settled, and with no candidate pending the model rewrites the active
  playbook from this run's verdicts (labels and research-window facts only: feature coverage and the
  fair-value table) into the next candidate. Runs draw active vs candidate by Thompson sampling on
  Beta(1+reached, 1+ideas-reached), where reached = the idea got to the gate. A candidate is promoted
  at P(better) >= 0.9 with >= 16 ideas, retired at <= 0.1 or after 64 ideas. Version 0 is the empty
  playbook, so the first rewrite must beat no playbook. Tables app_rsi_playbooks, app_rsi_assignments.
- Known risk: the yardstick is gate REACH (research data only), not gate PASS (too rare to learn from
  yet). A playbook could learn to get ideas past the research fold that then fail validation. Watch
  the scoreboard's pass rate among gated ideas per playbook; switch the yardstick once passes exist.

## Fair value vs mid: does the forecast know anything the market doesn't? (2026-10-24)

- Weather run 2613 spent its theses on forecast-vs-market ideas with no evidence the forecast adds
  anything to the mid; execution measured the mid's Brier at .067 against the calibrated forecast's .102
  over a year of NYC. The research prompt now carries `agent._fair_value_block`: for every built-in
  fair-value feature (`*_p_yes`, `*_p_yes_cal`: weather forecast, sportsbook odds) and time-to-close
  band (>24h, 12-24h, 4-12h, <4h), a logistic blend of logit(mid) + logit(fair value) is fit on the
  earlier half of the research window's events and scored on the later half. It reports Brier and the
  net P&L of buying wherever the raw or blended probability beats the quote by 2c after the fee, with SE
  clustered by event. Research window only; descriptive, like the calibration table.
- Remaining: if every band says NO, the run could skip the forecast angle entirely and save the spend.

## Window loads bounded for huge one-minute series (2026-10-24)
- Run 2560 (kxncaafspread, 18,471 one-minute contracts) failed its 180s load step; the catalog now
  has ~1,000 series, so more of these. Every partition window now keeps its most recent whole events
  whose estimated candles (one per candle_minutes over each contract's life) fit
  `partitions.RESEARCH_MAX_CANDLE_ROWS` (1.5M, env TAU_RESEARCH_MAX_CANDLE_ROWS), and the candle /
  micro queries are bounded to the kept contracts' close times (`load_history(until=...)`), so the
  database no longer scans the whole series. Weather, crypto and NHL windows sit below the cap.

## Research spend: stop after a streak of drops; gated windows get station features (2026-10-24)
- Runs 2541 (btc15m) and 2548 (high_ny) each dropped every thesis on the research fold (28 and 18)
  for ~$10 of Opus with nothing gated. `agent.EXPLORE_MAX_DROP_STREAK` (8, env
  TAU_EXPLORE_MAX_DROP_STREAK, 0 disables) ends proposing after 8 drops in a row; kept survivors
  still go to the gate. Roughly halves the cost of a dead market; the 4x-budget attempt cap stays.
- `partitions._load_window` (validation/holdout) passed no station frame_series, so obs_high_f /
  obs_low_f existed in research but not at the gate. Both loaders now use `backtest.station_frame_series`.
- Execution's check on 67 NYC days: raw NBM loses to the Kalshi mid (Brier 0.13 vs 0.09, runs ~1F
  warm). Edge, if any, is in a bias-corrected forecast combined with the market, not raw fcst_edge.

## Weather: built-in station features + pooled cities (2026-10-24)
- First high_ny run (2548): 36 days, 210 contracts = 36 independent events, no forecast/obs data, 13 drops.
  The gate can't confirm anything on 36 events, so evidence must pool across cities.
- `markets.WEATHER_STATIONS` maps KXHIGH* series to their settlement station. Their datasets now carry
  built-in features obs_high_f (running max of the NWS climate day) and obs_temp_f, as-of joined per
  frame (`build_dataset(frame_series=...)`); the live engine adds the same via `engine._event_feats`.
- `spec._poolable`: hourly-candle series (weather) may pool like strike-vs-spot; 1-min sports still can't.
- freedata cache now expires (1h; asos 10 min) so long-lived workers and the engine don't go stale.
- Open: confirm which KXHIGH* city series are collected on the box.

## Research moves off 15m crypto; weather gets a real fundamental (2026-10-24)
- btc15m: 28 theses in run 2541, all dead on the research fold. Treat 15m crypto as efficient after fees.
- Ranking by likely inefficiency (to confirm with coverage data): 1) weather daily highs, 2) in-season
  sports moneylines (NHL/NBA/NCAAF), 3) catalog econ/commodity dailies. Autopilot pointed at high_ny/nhl.
- New free source `asos` (IEM ASOS archive): "NYC" latest temp F, "NYC:dailymax" running max of the NWS
  climate day (LST midnight). Known-at = obs time + 15 min. Unverified from the web box until infra
  confirms outbound access to mesonet.agron.iastate.edu.
- Outcome line now counts `research:dropped`, so an all-DOA run no longer reads as tried=0 doing nothing.

## Calibration table priced at first touch (2026-10-24)
- Run 2541 (btc15m) read the table's "late cheap YES +1.1c" lead and spent ~10 theses on it; every one
  lost (e.g. 3,285 pooled trades, -$1.82/trade). Cause: each contract was priced at its AVERAGE quote in
  a cell, but a rule enters on first touch (a contract sliding to NO through 9c..1c averages ~5c, a rule
  pays 9c). Cells are now priced at the first quote in the cell. Test shows old code printed +1.3c on
  data where first-touch is negative.

## fit() finally gets its training labels (2026-10-24)
- Bug: code strategies' fit(window) never received settlement outcomes, though SPEC_GUIDE's own
  recalibration example reads window["results"]. Every supervised code model trained on all-NO labels
  and died with "only one class present" or fit nothing (seen in prod run 2531).
- Now `freeze_code_model` adds window["results"] for contracts settled inside the research window
  only; signals() windows never carry results.

## Research stops re-proposing dead ideas (2026-10-24)
- Prod run 2531 (kxcopperd) dropped 18 theses in 40 min; 7 were the same favorite-longshot idea. Dropped
  theses never reached app_strategies, so neither later rounds nor later runs knew about them.
- Now: `repo.dropped_theses` reads recent runs' DROPPED events; every proposing round shows them
  (deduped, newest first) and new drops are added live. Fail-open if the read errors.
- Calibration rows are labeled LEAD (best net edge > 2 SE after fees) or noise; with no lead the block
  tells the proposer not to try unconditional favorite-longshot theses on that market.
- Code strategies see yes_bid/yes_ask in `features` too (one thesis died reading None there).

## 90-day history for 15m crypto + old-end backfill + monotonic research cut — October 24, 2026

- **Why.** Sample size, not math, binds the research gate. The 15m ladders settle ~96 contracts a day each, but research used only 30 days (~8 validation days). Collected history goes back only to 2026-09-13 (BTC) and 09-17 (SOL/XRP/DOGE/HYPE), because the collector started with a 30-day floor and only ever syncs forward.
- `markets.CRYPTO_15M_HISTORY_DAYS = 90` for the eight 15m crypto ladders.
- `market_history` backfills the OLD end whenever history_days reaches past what was collected: settled markets between the floor and the oldest close (`/markets` with `max_close_ts`), and spot candles in 7-day slices per pass. Candles for the backfilled markets then flow through the normal `candles_done=0` path, newest first. An OLD market (closed >30 days ago) that Kalshi answers with 400/404 is marked `candles_done=3` and skipped, instead of blocking the series. Recent markets still raise, so real bugs are retried, not hidden.
- **Honesty guard.** `partitions._compute_boundaries(min_research_to=active.research_to_ts)` makes the research cut monotonic. History that grows at the old end widens Research only, and Validation/Holdout keep splitting what lies after the previous cut 25:15. Without this, backfilled history would have moved already-researched contracts into Validation. Validation therefore grows from ~10 to ~22 days as time passes (about 20 days), never by re-labelling researched data.

## Calibration table + 1c cost-stress gate — October 24, 2026

- **Calibration table in the research prompt** (`agent._calibration_block`). On the research window only, per time band (early vs the last third of a contract's life) and price bin, the proposer sees the settled YES rate vs the quote and the buy-YES / buy-NO net edge after the taker fee, with a standard error. Each contract counts once per cell. It aims generation at measured mispricing (favorite-longshot, terminal pinning) without touching held-out data.
- **Cost-stress gate** (`gatekeeper.COST_STRESS_CENTS = 1.0`, proposed by the execution thread). Validation and holdout trades are re-simulated with 1c of extra slippage per fill, and the stressed mean net return must stay > 0 for STAT_SUPPORTED / FORWARD_VALIDATED. The basis is measured: the ask moves 0.2c against us at 1s and 0.55c at 2s, p90 spread is up to 2.4c, and there are no live fills to calibrate against yet. The validation-power pre-screen projects at the same stressed cost, so zero-friction edges are screened out before they spend alpha. Binary markets only; perps/spot model their own costs. Verdicts carry `cost_stress_ok` / `cost_stress_mean`.
- Next: trade-flow features from `market_trades` (execution thread, live since 2026-10-24 09:21Z, 6 micro series) once a few days accrue; longer research history once the agents-worker OOM fix lands (infra thread owns it).

## Pooled multi-market research specs — October 24, 2026

A spec may carry `"pool": [<market>...]` (up to 3 extra markets sharing `spec.market`'s cadence, binary only, not combinable with `cross`; capped at 4 markets total because each 1-minute market-month is ~50MB of snapshots and the agents worker has MemoryMax=400M). The same single-contract rule is judged on the POOLED trades of all its markets: merged partition, merged research/validation/holdout datasets and one shared FDR stream (`stream_key`). That gives about N× the validation sample and a √N× smaller detectable edge, which is the main lever now that data (not math) binds the gate. `spec.is_multi_market` replaces `is_cross_contract` where evidence spans markets, which also fixes same-market cross_strike/calendar specs, previously sent to `ensure_merged_partition` with one market (a ValueError). Execution is untouched: a passed pooled rule is an ordinary single-market spec on `spec.market`.

## Backtest fills on the next bar at the live reservation price — October 24, 2026

`app/backtest.py` now defaults to `FILL_MODEL="next_bar"` for single-contract binaries: a signal computed on bar t fills against bar t+1's quote, an entry is abandoned when that ask exceeds `execution_kernel.reservation_price(fair, min_edge, qty)` (the same cap live and paper enforce since the execution thread's change), fills are capped at displayed top-of-book size (`yes_ask_size` / `yes_bid_size` when the feed has them), and exits sell at the next bar's bid. Code strategies may not pay above their signal price. `TAU_BACKTEST_FILL_MODEL=signal_bar` restores the old optimistic same-quote fill for comparison. Research folds, validation and holdout all use it, so a gatekeeper pass now reflects fills live could actually get.

## Research gatekeeper can pass a real edge again — October 24, 2026

Root cause of "no strategy has ever passed research": the gatekeeper could not pass a real edge. A power simulation through the actual gate code rejected a planted 15c/contract edge over 400 validation trades 6/6 times. Fixed on `claude/project-thread-dehmjp`:
- **Placebo:** the binary negative control was a winner-subset 1/price shuffle that only accepted edges concentrated in cheap contracts; a uniform real edge scored p≈1 and was classified REJECTED. Replaced with a market-implied null (each settled contract redrawn as Bernoulli(entry price)).
- **Primary p-value:** now 1−Φ(mean/bootstrap SE). The empirical bootstrap mass moves in 1/n_boot steps (5e-4) while LORD++ alpha is below that by the 3rd test, so it could not reject.
- **Evidence epochs:** the LORD++ stream carries `epoch_to_ts` (new `app_fdr_state` column); a fresh stream starts only once validation has fully rolled past the old one. DSR trial count = experiments whose validation window overlaps the current one (ledger-derived). Legacy streams continue until their data rolls out.
- **Validation-budget pre-screen:** finalists whose research-fold edge projects <20% power at the next alpha are recorded `underpowered` and never pre-registered (no alpha, no DSR trial).
- **Holdout churn latch:** partitions re-freeze on every settlement; the holdout cap now counts looks across all overlapping re-frozen windows.
After: the planted 15c edge passes 6/6, an 8c edge over 400 trades passes ~50% on a fresh stream, a 4c edge needs ~2,000 validation trades (data, not math, is now the constraint), breakeven noise passes 0/20. Open decision for Todd: DSR≥0.95 stacked on LORD++ double-corrects for multiplicity. Next: next-bar fills with reservation price and depth caps; cross-market pooled hypotheses for sample size; MDE feedback to the generator.

## Realistic paper fills and a stronger live gate — October 24, 2026, UTC

Merged to main (branch `claude/project-thread-76ft6y`) and deployed 08:42Z; pairs (#35) deployed 09:03Z. App paper deployments now run the live `MarketableLimitKernel` over `SimulatedVenue` (`engine.paper_kernel_factory`, `Sources.paper_kernel`, shared `_execution_kernel` helper so paper and live cannot drift). Paper now misses on a stale quote or a moved ask, fills only the touch size, pays the fee per child order and can part-fill an exit; simulated fills carry `order_ref='sim:<id>'`. `APP_PAPER_REALISTIC_FILLS=0` restores legacy instant fills. Cross-contract pairs keep the atomic paper fill (legging risk not simulated yet). Fixed `SimulatedVenue` pricing NO orders off the YES touch; it now uses the `order_wire_params` mirror.

Live gate (`agent._proven_on_paper`), additive only: the old 8-trade/not-negative check stays, then 30+ closed realistic round trips (`repo.paper_round_trips`, legacy fills excluded), net P&L > 0 after fees, 48h+ span, and stationary-bootstrap one-sided p ≤ 0.10 on mean P&L per trade. Existing strategies have zero realistic trades, so none can go live until they re-earn it on paper. Tests: `tests/test_paper_realistic_fills.py`, `tests/test_app_autopilot_live.py`. Deploy is pending a bundle that excludes the unreleased perps release.

Follow-up (PR #27): `paper_evidence` reports paper vs backtest unseen-data P&L per trade (`realization`, informational) and the autopilot review context shows each paper deployment's evidence line. Live decay guard in `engine.loss_guard`: a live deployment net negative after `APP_LIVE_DECAY_MIN_TRADES` (20) closed trades is paused and flattened. Pause-only, never opens or blocks an exit.

Funnel (PR follow-up): `agent.auto_paper_candidates` runs at the start of every autopilot review and puts each gatekeeper DEPLOYMENT_CANDIDATE that never ran on paper onto paper via `act()` (max 3 per review, 20 active), so realistic evidence accrues without waiting for the LLM. Never live; a stopped paper run is not redeployed.

Paper pairs now run through the simulated venue too (`_paper_kernel_buy_pair`, same legging mechanics as live `_kernel_buy_pair`: short second leg -> unwind the excess, failed unwind -> tracked naked leg). Both legs share one `sim:pair-` order_ref so the gate counts a pair as one round trip.

Live-ready notice (`agent.live_ready_notices`, run at the start of every autopilot review): the first time a running paper strategy clears every `paper_evidence` check, the user gets one chat line (marker `[live-ready #<strategy_id>]`, deduped via `repo.chat_contains`) and one SES email (`notify.live_ready_notice`) linking the strategy. Read-only toward trading: going live is still the user's promote or live autopilot, which re-run every gate. For a Sports, Elections, Politics or Entertainment market, the notice and the email also tell the user to re-verify their Kalshi location in the mobile app first (`agent.location_attestation_note`), because Kalshi rejects orders in those categories once the attestation lapses. Crypto and weather get no note.

Live size ramp (`engine._live_ramp_scale`): a live deployment's first `APP_LIVE_RAMP_TRADES` (20) closed trades enter at `APP_LIVE_RAMP_FRACTION` (0.25, clamped to (0, 1]) of the spec stake, at least 1 contract, so a fresh promotion risks a quarter of its size while the decay guard collects its 20 trades. Entries only; exits untouched.

Research loop un-jammed (2026-10-24): for an hour every autopilot review re-proposed the same three markets on the 6h research cooldown (many runs had been stopped by deploy restarts), so no research started. Now reviews see a `Research cooldown, do NOT propose...` line (`agent._cooldown_line`). On autopilot, a cooldown-refused market starts the same angle with market=None, and `run_research` picks from markets off cooldown (`_research_blocked_markets`, one `list_runs` read). An already-running market and manual requests still refuse. The active-research cap still bounds it.

Opus quota goes to research: scheduled reviews run on `APP_REVIEW_MODEL` (default `sonnet-4-5`, `agent.REVIEW_MODEL_KEY`), billed at that model; chats and research keep the user's model. CloudWatch for 2026-10-23: Opus 10.25M in / 1.01M out over 806 calls (~$76), Sonnet 5.64M in / 0.93M out (~$31). Reviews (~26k input each) were about half the Opus input and pushed research onto Sonnet. Bedrock's Opus 4.5 tokens-per-day quota is not adjustable (us profile L-F397ECBF 6.75M, global L-E2985A8E 13.5M). Expected net cost change is about +$8/day: about $12 saved on reviews, about $20 more for research back on Opus.

Deploys no longer burn research runs: `repo.fail_abandoned_runs` gives a reaped research run only `TAU_RUN_MAX_RESUMES` (3) resumes, and every deploy's restart counted as one, so a run restarted 4 times in a busy deploy hour was stopped for good. The agents worker now traps SIGTERM (`worker._yield_on_sigterm`): it stops claiming, re-queues the research runs it holds via `repo.yield_run` (no resume spent, a 'Paused for a server update' event), and exits. Reviews and chats are left to the reaper so their actions aren't repeated; a SIGKILL/OOM still counts as a crash. Deploy rule (coordinator, 2026-10-24): at most one batched web-box deploy per hour at :50, with safety fixes exempt.

Interactive lane (`worker.INTERACTIVE_LANES`, env `APP_AGENT_INTERACTIVE_LANES`, default 1): the box runs `APP_AGENT_CONCURRENCY=2` and allows 2 active research runs per user, so both threads sat on hour-long research and the autopilot review (and any chat Todd typed) waited in the queue. Seen on 2026-10-24: review 2550 was queued for 12+ minutes behind runs 2548 and 2549. Extra `:chat<N>` threads now claim only non-research runs (`repo.claim_run(skip_research=True)`). Research capacity is unchanged.

Idle reviews spaced out (`worker._idle_review_skip`, env `APP_IDLE_REVIEW_SECONDS`, default 1800): when every research slot is busy and no deployment is running, the 10-minute heartbeat review could only re-propose research that the cap refuses. Todd's chat showed the same three cooldown refusals at 11:31, 11:39 and 11:41. Those reviews now run at most every 30 minutes. Research completion still enqueues a review right away, and a running deployment keeps the 10-minute cadence. Saves about two thirds of review spend while research is saturated (about 26k Sonnet input tokens per review).

Vanished catalog markets repick (`run_research`): the autopilot kept queuing catalog markets that had dropped out of `MARKETS` by the time a worker started the run, usually after a restart reloaded the catalog. Examples are kxebasketballgam (run 2551 at the 12:50Z deploy) and kxeuroleague* (6 runs over 2 days). Each one failed as "no longer available" and wasted a slot and a review. An agent-launched (`brief`) run now keeps its angle and lets the picker choose a live market. A user-pinned market still fails cleanly.

Research funnel telemetry: every finished research run prints one `[research] run=… status=… tried=… passed=… tokens_in=… tokens_out=… model=… verdicts=phase:class=n,…` line to the agents log (`agent.research_outcome_line`), so pass rates and token cost per pass can be measured from the box log without DB reads. Copilot (review/chat) runs print a matching `[copilot] run=… kind=… actions=… tokens_in=… tokens_out=…` line, since reviews outnumber research runs ~3:2. Bedrock Claude spend measured at ~$90–175/day (Oct 18–23, credits-covered), with Opus 4.5's non-adjustable daily token cap hit most days (fallback Sonnet → Haiku); spend held flat until the fixed gatekeeper shows passes.

Research robustness: prod logs showed a code strategy's truncated `out.json` raising a raw `JSONDecodeError` out of `sandbox._run_entry`, past `freeze_code_model`'s `SandboxError` handler, killing the whole research run (its tokens already spent). Unreadable or non-object output is now a `SandboxError`, so only that hypothesis fails.

Forward paper probation (`agent.auto_paper_probation`, off unless `APP_PAPER_PROBATION=1`): 2,857 strategies rejected and none cleared, so paper has never traded and the realistic-fill engine has no production record. Each autopilot review puts validation near misses (latest validation row net > 0, p ≤ `APP_PROBATION_MAX_P` 0.25, ≥ 20 trades; `rr.probation_candidates`) that never ran on paper onto paper, at most `APP_PROBATION_MAX_ACTIVE` (4) at once. Live is unchanged: deploy_live and the manual live path still require a gatekeeper DEPLOYMENT_CANDIDATE. A probation strategy that clears every paper check gets a `[paper-standout #id]` line, not a promote invite. For Todd on 2026-10-24 that is #16001 (sol15m, p=0.155), #11280 and #11281 (sol_daily, p≈0.22).

Probation turned on (Todd, 2026-10-24 13:10Z): `APP_PAPER_PROBATION=1` is in the box `.env.app` from the 13:50Z batch.

Fresh paper is left alone (`agent.PAPER_MIN_AGE`, env `APP_PAPER_MIN_AGE_HOURS`, default 24). Within minutes of probation going live, review 2558 paused deployment #74 (#16001, sol15m) for "zero fills after hours on paper", though it was 10 minutes old. Autopilot pauses of a paper deployment younger than 24h are now refused with the deployment's age. Live pauses are never held back, and the engine's own guards (drawdown, loss) are untouched. The review now also sees each deployment's age ("deployed 0.5 hours ago (too new to judge...)"), because the refusal alone left the model guessing: later reviews paused #75 and #76 (sol_daily) for "zero fills for days" 20 minutes after they started.

Reaped research threads stop instead of running on as zombies (`agent.Superseded`, `repo.run_worker`). When the watchdog reaps a research run (no progress for `TAU_RUN_STALL_SECONDS`, 150s), the worker thread kept going. At 14:05Z both research threads were at 36-51% CPU on runs the DB showed as queued (2549, resume_count 2) or stopped (2555), while 2549 and 2560 waited unclaimed. Those threads also kept spending Opus tokens and writing events and checkpoints over the new owner's record. Every checkpoint now confirms the run is still running or paused and still owned by this worker. If not, the thread bills what it spent, logs `[research] run=… superseded`, and exits without writing an event or a finish.

Research in the autopilot float (`server._research_activity`, `research` in `/api/autopilot/status`): the markets being researched now, plus the last 7 days' ideas tested and passed, from one `list_runs(limit=50)` read. A quiet panel reads as working rather than stuck.

Visibility: the strategy page's Road to live panel (both themes) shows each gate's progress, and the autopilot float's stats show the running paper strategy closest to live (`paper_progress` in `/api/autopilot/status`: realistic trades / 30 and net P&L, one grouped query, no bootstrap on the 20s poll).

The manual live path now needs the paper record too. `server.create_deployment` with mode live checked the gatekeeper candidate but not `agent._proven_on_paper`, so a candidate could go live by hand with no realistic paper trades while the autopilot path and the Road-to-live view both required them. It now refuses with the first failing paper check (30+ realistic round trips, net up, 48h+, bootstrap p ≤ 0.10). Paper and demo are unchanged.

Catalog market labels come from the series now. kalshi_series.title held one market's title ("Portland wins", "Middle Tennessee wins by over 7.5 points", "Will the maximum temperature be >77° on Oct 25, 2026?"), so the research picker, run logs and the app named catalog markets after a single contract. `catalog_collector.refresh_series_meta` now also writes the /series title ("NBA Game", "College Football Spread", "Highest temperature in Chicago"), and `refresh_series` no longer overwrites a stored title.

The autopilot panel opens with a plain-language summary (`server._autopilot_story`, rendered into `#apf-story` in both themes). It says what it is researching now, how many ideas it tested this week and that most fail, whether the paper strategies have traded yet and why not, and what live needs: 30 realistic paper trades over 48h+, net up, and live autopilot turned on. It is built only from the status payload, so it can't disagree with the figures under it. The Research row now reads "Researching X" or "Not researching right now", not "choosing a market · Idle". Checked at 390px.

The autopilot feed got three fixes. (1) Reviews saw finished research runs as "[succeeded]" and told Todd that two empty runs were "proven strategies ready for paper", then tried to deploy strategies that had failed. The context now says "[finished, NOTHING passed, no new strategy]" or "[finished, N passed]". (2) A refused action with no proposal ("you already have research running") is posted once per 2 hours on a scheduled review (`agent.REPEAT_NOTE_WINDOW`, `repo.recent_chat_same`). Chats always post. (3) A failed adjustment says "didn't pass these checks: \"makes money on unseen data\"", instead of a gate list that read as praise.

Next: feed realization to the research thread's backtest fill-model calibration.

## Kalshi perps deployment preparation — October 23, 2026, Asia/Shanghai

In progress (`tau-kalshi-perps-deployment-preparation-20261023`): build a native real-money Bitcoin perps path, using Kalshi's own margin/leverage limits and mandatory owner confirmation for every agent-proposed order. No extra Tau financial caps and no autonomous broker execution. Existing binary live gates and research-only strategy promotion blocks stay unchanged. Encrypted selected-source recovery passed (run39888106069); legitimate installed fixes and header CSS are being reconciled into main. Native client/store/service, both-theme Funds preview/confirmation and hosted synthetic acceptance harness are implemented; 2,265 Python/10 skipped and226+8 frontend checks pass. Frozen58 security review completed with no findings; hosted staging found a proposal-column width mismatch, now repaired. Hosted rerun and migration-delta review remain pending. Production code, services, settings and jobs remain unchanged. Full candidate verification and guarded rollout remain required. [Preparation handoff](results/kalshi_perps_deployment_preparation_2026-10-23/HANDOFF.md).

## Bitcoin perpetual data and research — October23,2026,Asia/Shanghai

Source merged through [PR #21](https://github.com/JihuiTanUchicago/kalshi_trade/pull/21) as main 33bfc957 (`tau-kalshi-bitcoin-perps-research-20261023`). Native Bitcoin candles, funding and observations feed causal research with committed-source manifests, frozen holdout and existing statistical gates. Both themes label it Research only; all perpetual execution is blocked. **1,899 Python / 10 skipped and 196+8 frontend checks pass; CI and hosted full-schema MySQL/HTTP staging pass on the identical source tree.** Explicit proxy and native metadata fixes resolve local retrieval; real production/demo reads returned 2,761/2,822 candles, six funding records and four observations each. Candle gaps still prevent continuous-replay acceptance. Read-only production check39884723368 passed: five native HTTP200 requests, all active perps flags off, one running research and no queued/paused jobs at inspection. Installed-source reconciliation is required: 21 files differ from base; 11 match known Git blobs and 10 have unresolved exact source copies. Preserve accepted styles and existing research; no deployment/migration/restart occurred. Actual perps SQL/replay and genuine queued research remain activation gates. [Setup](app/KALSHI_PERPS_RESEARCH.md), [canonical evidence and handoff](results/kalshi_bitcoin_perps_2026-10-23/HANDOFF.md).

## Tau header divider alignment — October22,2026,Asia/Shanghai

Implemented/offline verified (`tau-header-alignment-20261022`): default Tau masthead and Hot Markets heading share50pxrow height; native1280/1100/320pxpreview borders align exactly. 1676Python/10skipped and177frontend+8Meridian checks pass. Production release pending. Cosmetic CSS only; preserve Meridian and actual installed unpublished boot/legal styles. [Handoff](results/header_alignment_2026-10-22/HANDOFF.md).

## Remove persistent Meridian update notice — October21,2026,Asia/Shanghai

Implemented/offline verified (`tau-meridian-update-notice-20261021`): Meridian's build probe, update banner and unused styles are deleted; Tau/default/shared/backend behavior stays intact. 177frontend+8Meridian checks and1676Python/10skipped pass. Immutable publication and fresh installed-state release remain pending. Root owns the isolated fix and existing safe whole-package release; no provider/order/service actions. [Handoff](results/meridian_update_notice_2026-10-21/HANDOFF.md).

## Meridian compact workspace deployment — October21,2026,Asia/Shanghai

Deployed and accepted (`tau-meridian-workspace-20261021`). Settings → Theme → Meridian selects the retained compact redesign. Only Meridian JS/CSS changed; the actual Tau default, backend, configuration and running service PIDs were preserved. Whole-package exchange and the full unchanged installed schema succeeded. CloudFront refresh was issued, then origin/public 200/hash/version checks passed in run39463270100 and independently from local.

Verification: **1,676 Python passed / 10 skipped; 178 frontend + 8 Meridian current-behavior checks; 65 operation checks**, independent control review and synthetic desktop/320px/theme switching. No service restart, job mutation or provider/order call. Source is tracked in PR18; the separate operations branch must never merge. Ownership released at acceptance; the prior design loop remains stopped. [Canonical handoff](results/meridian_workspace_2026-10-21/HANDOFF.md).

## Isolated paper testing and GitHub source — October 19, 2026, Asia/Shanghai

Paper source merged as `f76b2f1` through PR #13, reconciled with main `8e3ec87`; latest research diagnostics are preserved. **1,608 Python / 10 skipped and 71 Node tests passed**, independent integration review and PR/main CI passed. Source merge does not deploy production; its workflow is manual and the old exact-ref activation follow-up remains paused.

Implemented repeatable offline staging (`tau-paper-main-staging-20261019`): complete app/data image, separate MySQL8.4 DB/user, private generated secrets, internal network and web-only loopback preview. Full schema precedes web; synthetic authenticated acceptance runs in an unpublished verification container. **1,645 Python passed / 10 skipped**, including 37 isolation/fixture/stack guards. [Real MySQL/HTTP run39144052370](https://github.com/JihuiTanUchicago/kalshi_trade/actions/runs/39144052370) passed14 lifecycle checks with zero provider/order calls or production changes. The dedicated staging workflow boots and verifies the actual Compose stack on each relevant revision and retains sanitized acceptance artifacts. This is not a persistent public site or actual user OAuth/fill acceptance. [Setup and boundaries](staging/README.md).

## Alpaca paper production deployment — October 18, 2026, Asia/Shanghai

Production rollout held for staging first (`tau-alpaca-paper-deploy-20261018`). Paper source is now merged in PR #13; no production migration/restart has been accepted. The old exact-ref operation is paused and must be replaced/reviewed against merged source before use. Staged provider overlays, active research and live/autopilot gates remain unchanged. [Deployment evidence](results/alpaca_paper_trading_2026-10-18/deployment/HANDOFF.md).

## Alpaca paper trading — October 18, 2026, Asia/Shanghai

Implemented / offline verified / independent review complete (`tau-alpaca-paper-trading-20261018`); advisory ownership handed off. Source is isolated at `../tau-alpaca-paper-20261018` from GitHub main `3c70435`. Adds per-user OAuth paper equity LIMIT DAY intents with explicit confirmation, account/positions, broker fills/cancellation reconciliation and agent proposals; shared main source is unchanged. Durable single-send claims, monotonic send generation and bounded cash/long-share checks cover timeouts/replays/concurrent fills. **1,602 Python passed / 10 skipped; 71 frontend passed; four synthetic browser scenarios/eight screenshots in both themes and desktop/mobile**. Independent control-path review has no remaining blocker. Thirty-five engine/vault/connection/data-pipeline files are byte-identical. The earlier implementation milestone was local-only; source is now merged via PR #13 with latest-main diagnostics preserved. Production full app.schema/private runtime opt-in and genuine OAuth/paper-order acceptance remain pending; no production provider/order, migration or service change is claimed. Existing production feed activation and live/autopilot gates are preserved. [Handoff and reproducible evidence](results/alpaca_paper_trading_2026-10-18/HANDOFF.md).

## Open PR integration with latest main — October 18, 2026, Asia/Shanghai

- **Status:** both PRs merged on GitHub; local main synchronized (`tau-open-pr-main-merge-20261018`); advisory reservation released. User authorized local latest-main integration, both PR updates/commits and GitHub merges. Imported all 68 newer main commits and exact object hashes, then fast-forwarded local main to `0700437`; preserve that source's research-rigor, execution/risk, reconciliation and frontend changes.
- PR #10 conflicts are resolved by retaining the new Funds layout, adding broker mount generation guards and the `/settings/account` alias, loading broker assets before bootstrap, and retaining both progress histories. The current full `app.schema` migration supersedes the older broker-only rollout instructions. No database migration/deployment is being performed here.
- Independent backend/frontend integration reviews found no remaining compatibility issue. Reconciled upstream-stale test fixtures and removed-helper references with actual current UI contracts. Combined regression: **1,187 Python passed / 9 skipped; 58 frontend passed**, syntax/whitespace and private preservation checks pass. Full offline verification precedes every commit. Private environments, runtime services, orders/gates and sibling source are no-touch. [Scope and merge evidence](results/open_pr_merge_2026-10-18/HANDOFF.md).

- **GitHub result:** [PR #10](https://github.com/JihuiTanUchicago/kalshi_trade/pull/10) merged as `ec3d0e6` and [PR #11](https://github.com/JihuiTanUchicago/kalshi_trade/pull/11) as `3445f76`; signed merge trees exactly match the tested candidates. Normal head-matched merges, no forced update/rules bypass; no open PR remains. Source publication is complete, with a documentation/evidence-only follow-up recording the result. [Merge receipt](results/open_pr_merge_2026-10-18/MERGE_RECEIPT.json). Production acceptance remains teammate-owned.

## Databento primary data and production setup — October 18, 2026, Asia/Shanghai

- **Status:** implemented / offline verified / ready for deployment-owner review (`tau-databento-primary-20261018`); advisory reservation released. Databento is selectable as the historical-bar primary with an explicit default dataset, stable explicit-provider overrides and no silent fallback. Databento-primary research avoids automatic duplicate Alpaca history; other feeds retain current snapshots, spot FX, macro and options analytics that this adapter does not replace.
- Focused configuration helper materializes effective defaults → recognized process values → private file, validates without network, and optionally atomically writes a separate mode-0600 overlay. Base environment files, unknown keys, shell evaluation and unsafe paths are rejected. The updated agent unit loads and preflights the overlay last; a missing overlay preserves legacy startup. [Production setup and coverage decision](app/MARKET_DATA_DEPLOYMENT.md).
- **Verification:** **939 Python passed / 9 skipped**; independent control-path review **287 focused passed with sockets blocked**, no remaining actionable findings. Review-driven fixes prevent old base settings resurrecting omitted providers and prevent overwriting `.env`/`.env.app`/`.env.aws`. Syntax and whitespace checks pass. Named slash-command skills are unavailable; manual independent review and planned-only Dev Log synchronization were used without claiming those commands ran.
- Branch `codex/databento-primary-20261018` starts from GitHub main `a5d5528`; OAuth PR #10 stays separate. Private credentials, execution/gates, schema, sibling product and other archives are untouched. No paid/provider/model call, service restart, migration or production action. Deployment-owner credential/entitlement configuration, durable data-cost accounting and a real queued worker/model canary remain acceptance gates. [Canonical handoff](results/databento_primary_2026-10-18/HANDOFF.md).

## Broker OAuth teammate handoff — October 17, 2026, Asia/Shanghai

- **Status:** published for review / teammate handoff complete (`tau-broker-oauth-teammate-handoff-20261017`). User selected teammate execution; no further desktop AWS/SSH request is pending. Canonical operator guide covers whole-app source, original/private versus GitHub workflow credential access, preserved encryption key, exact two-table migration, web-only restart, Tau invalidation, acceptance and rollback.
- [PR #10](https://github.com/JihuiTanUchicago/kalshi_trade/pull/10) publishes the locally tested source and selected safe evidence on `codex/broker-oauth-20261017`, targeting main. Initial source commit `473d624`/tree `9c5ee5b` exactly matches the GitHub object; main unchanged. Full pre-publication checks: **1,020 Python passed / 9 skipped; 55 frontend passed**. Handoff review and shell/Python/archive checks pass. No automatic merge, deployment or teammate message. Seven encrypted GitHub secrets already exist. Production/schema/configuration/real consent remain teammate acceptance work. [Operator guide](app/BROKER_OAUTH_DEPLOYMENT.md) · [Publication handoff](results/broker_oauth_2026-10-17/teammate_handoff_2026-10-17/HANDOFF.md).

## Broker OAuth rollout preparation and encrypted sync — October 17, 2026, Asia/Shanghai

- **Status:** GitHub sync complete / local deployment candidate verified / waiting for production access (`tau-broker-oauth-production-20261017`); advisory reservation handed off. User explicitly authorized deployment/runtime injection/schema and subsequent consent readiness. Both OAuth names were encrypted and stdin-uploaded; seven repository secrets now listed, five earlier entries and private env unchanged. No source/secret value was committed or printed.
- Full pre-release regression: **1,020 Python passed / 9 skipped; 55 frontend passed**. Independent deployment review found no source blocker; whole-app archive, exact two-table SQL, per-file/hash manifest and rollback/acceptance runbook are prepared. Actual remote source/dependency/schema compatibility and persistent APP_SECRET_KEY have not been inspected. Do not run broad app.schema/secret loader or restart agents/engines.
- No AWS credential/profile or Tau SSH target is available locally; access question is pending. Deployment is already authorized: resume with configured access without re-requesting approval. No server injection, migration, restart, CloudFront invalidation or real consent/account/order test occurred. Callback 404 remains the earlier live observation. [Rollout handoff](results/broker_oauth_2026-10-17/production_2026-10-17/HANDOFF.md) · [Deployment runbook](results/broker_oauth_2026-10-17/production_2026-10-17/DEPLOYMENT_RUNBOOK.md) · [GitHub receipt](results/broker_oauth_2026-10-17/production_2026-10-17/GITHUB_SECRET_SYNC.json).

## Alpaca OAuth credentials and callback readiness — October 17, 2026, Asia/Shanghai

- **Status:** supplied locally / configuration checked; advisory reservation handed off (`tau-alpaca-oauth-credential-check-20261017`). The exact client ID/secret names are present in Tau’s ignored mode-0600 `.env`. Actual local configuration builds the correct paper/data authorization URL without including the secret. Provider authentication/approval is not established without real consent; no token/account/order request occurred.
- **Evidence:** 112 focused offline tests pass. Anonymous production `/healthz` returns200, while broker callback and new asset return 404. Local `APP_SECRET_KEY` is absent; the production runtime must retain its existing key. New OAuth names are absent from GitHub secret metadata. Deployment/migration/runtime injection and a genuine paper consent/account check remain pending; existing broader regression is valid for unchanged source. Private env and runtime/source hashes are unchanged; no upload, commit, migration, restart, deployment or live activation. [Current handoff](results/broker_oauth_2026-10-17/credentials_2026-10-17/HANDOFF.md) · [Receipts](results/broker_oauth_2026-10-17/credentials_2026-10-17/VERIFICATION.json).

## Broker account OAuth connections — October 17, 2026, Asia/Shanghai

- **Status:** implemented locally / offline verified; advisory reservation handed off (`tau-broker-oauth-20261017`). Settings → Account in both themes now offers Alpaca Connect, Robinhood Trading MCP and approved IBKR OAuth1a in that order. Ten-minute hashed state binds the originating user/session/provider/environment; encrypted grants, single-use claims and latest-attempt fencing prevent callback replay or resurrection after disconnect. Readiness and masked metadata only are public.
- Alpaca defaults to paper/read+data; explicit order authorization is optional and `/v2/account` verifies the selected host. Robinhood uses discovered official public PKCE/issuer metadata and verifies MCP initialize only. IBKR signs RSA/DH requests and verifies its LST proof without starting a brokerage session. All Tau trading gates/data activation flags and protected sibling/execution source are unchanged.
- **Verification:** infrastructure **1,020 passed / 9 skipped**; frontend **55 passed**; independent auth/protocol review **141 focused passed**, no actionable blocker; four synthetic desktop/mobile theme captures and controls pass. Two anonymous Robinhood discovery GETs returned 200; no real broker consent/token/account/order call. Python/JS syntax, whitespace, private-value scan and protected-source checks pass. Named slash review/devlog commands are not installed; no claim that they ran.
- User confirmed `https://d1gfpzcosqrjya.cloudfront.net`; only `APP_PUBLIC_URL` was added to ignored local `.env`, preserving existing keys/flags. Alpaca app credentials were not yet supplied at this implementation milestone; their subsequent local configuration check is recorded above. Provider approval, IBKR material/callback behavior, persistent runtime encryption-key injection, authorized schema migration/deployment and real account acceptance remain open. No commit/push/deployment/migration/live activation. [Setup and exact callbacks](app/BROKER_OAUTH.md) · [Handoff](results/broker_oauth_2026-10-17/HANDOFF.md) · [Verification](results/broker_oauth_2026-10-17/VERIFICATION.json) · [Review](results/broker_oauth_2026-10-17/REVIEW.md).

## Broadened co-pilot autonomy — risk/execution/param control within safe bounds — October 17, 2026 (worktree, not deployed)

The autopilot/co-pilot now manages the whole operation, not just pause/stop, while every money/risk
value it sets stays inside a hard-clamped envelope.

New `agent.act()` action kinds (each a logged, reversible proposal via `create_proposal`; applied
immediately only under autopilot, else pending the user's approval — the existing pattern):
- `set_risk` → `repo.set_user_risk_config` writes `drawdown_limit_pct` / `max_open_positions` /
  `max_open_notional`. Clamped to `agent.RISK_BOUNDS`: drawdown_limit_pct ∈ [1, 50] (never 0, so a
  stop can't be disabled; ≤50 so it always bites), max_open_positions ∈ [1, 50], max_open_notional
  ∈ [1, 5000]. These feed the existing engine force-sell + portfolio caps unchanged.
- `set_exec` → `repo.set_user_execution_config`. NEW per-user override layer: three nullable
  `app_users.exec_*` columns the live `live_kernel_factory.make()` reads FIRST, falling back to the
  `KALSHI_MAX_*` env defaults when NULL. Clamped to `agent.EXEC_BOUNDS`: book_fraction ∈ [0.01,0.50],
  entry_spread ∈ [0.01,0.25], order_notional ∈ [1,500]. Each kernel knob can only shrink/abandon an
  order and never blocks an exit, so a set value never weakens safety.
- `research` extended: besides dig-deeper off a passed strategy, it can now start a FRESH line
  (`market` + `idea`) through `repo.create_run(kind="research")` — the identical RSI pipeline
  (proposer → gatekeeper → one-time holdout) a manual Research-page run uses, no narrowing.
- `adjust` already tunes strategy/model spec params (re-validated + re-backtested); surfaced as a
  first-class capability in the prompt.

Clamping is enforced in `agent._clamp_into` at BOTH the action site and in `apply_proposal`
(defensive re-clamp on approval). `create_proposal`/`get_proposal` gained a JSON `payload` column
(the clamped change set to apply on approval). Proposal `kind` uses `set_exec` (not "set_execution")
to fit the existing `VARCHAR(12)`.

Immutable backstop, untouched and in order: `APP_LIVE_TRADING_ENABLED` / `APP_NO_SIDE_LIVE_ENABLED`
flags, every deploy_live gate (`_is_deployment_candidate`, LIVE switch, Kalshi key, typed confirm,
`_proven_on_paper`, `live_autopilot_ok`), the loss budget + daily-loss kill switch, and the
drawdown/portfolio force-sell. Also killed the stale "YES-side only" copy (server.py autopilot_live
message, app.js panel, schema comment): any side is promotable once `NO_SIDE_LIVE_ENABLED` is on,
with the "being validated" fallback only when it's off.

`position_stop_pct` (named in the task) was deliberately NOT added: it has no enforcement path in
the engine, and a knob the agent could "set" that does nothing would be a safety illusion. The real
per-deployment stop is `drawdown_limit_pct`.

Tests: `tests/test_app_agent_autonomy.py` (clamps, proposal-vs-applied, fresh research, defensive
re-clamp). Full suite green (529 passed / 9 skipped).
## Alpaca and Databento GitHub secret sync — October 17, 2026, Asia/Shanghai

- **Status:** synced and metadata verified; advisory reservation released (`tau-alpaca-databento-secret-sync-20261017`). The user restored Databento in Tau’s private `.env` and requested GitHub sync. `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` and `DATABENTO_API_KEY` were client-encrypted and uploaded through stdin; all five named secrets covering Alpaca/Massive/Databento/Exa are listed. Existing Massive/Exa metadata is unchanged; no secret value was logged, placed in Git or passed as an argument. Private `.env` bytes/mode are unchanged.
- [Deployment guide](app/DEPLOYMENT_SECRETS.md) and README now reflect all four providers, explicit runtime injection and the current SSM loader’s lack of Alpaca fields. Databento’s local missing-key gate is resolved; worker activation, data-cost accounting, entitlements and real production acceptance remain under their existing gates. No workflow, AWS/server/service, provider/paid call or trading operation. [Upload receipt](results/api_secret_handoff_2026-10-17/PROVIDER_UPLOAD_RECEIPT.json) · [Handoff](results/api_secret_handoff_2026-10-17/HANDOFF.md).

## Local provider environment consolidation — October 17, 2026, Asia/Shanghai

- **Status:** available Alpaca credentials copied / offline configuration verified; advisory reservation released (`tau-local-provider-env-20261017`). Tau’s ignored mode-0600 `.env` now contains `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` copied from Polygon’s private root `.env`. The source and all existing target bytes/assignments are preserved. `Config.from_env` accepts the exact copied pair without any provider call; activation flags are unchanged.
- `DATABENTO_API_KEY=` is present as an empty placeholder because no local value remains available. Restoring that value is still required; earlier successful provider checks are historical evidence. No runtime code, GitHub/AWS secret, service, deployment or trading setting changed. The existing Massive/Exa GitHub sync remains a separate milestone. [Configuration evidence](results/api_secret_handoff_2026-10-17/LOCAL_ENV_CONSOLIDATION.json) · [Handoff](results/api_secret_handoff_2026-10-17/HANDOFF.md).

## API credential deployment handoff — October 17, 2026, Asia/Shanghai

- **Status:** encrypted GitHub sync verified / deployment handoff ready; advisory reservation released (`tau-api-secret-handoff-20261017`). The configured `MASSIVE_API_KEY` and `EXA_API_KEY` were stored as encrypted repository Actions Secrets; command success and subsequent name/timestamp reads confirm creation. Real `.env` stays ignored, untracked and mode 0600; its bytes are unchanged. No key value was logged, committed or passed in command arguments.
- The user is not sure whether the teammate deploys through Actions or manual SSH/AWS. [Deployment-owner guide](app/DEPLOYMENT_SECRETS.md) explains both paths, non-downloadable GitHub secret values, point-in-time sync and the existing AWS SSM loader's broader effects (including callback overwrite and web/agent restarts). No deployment workflow or AWS parameter was created, provider flag changed, service restarted or paid provider/model call made. Alpaca/Databento keys were absent from the current product `.env`; no unrelated locations were searched.
- **Verification:** infrastructure **878 passed / 9 skipped**; independent guide review corrected the explicit OAuth callback argument, otherwise no blocker. Guide links and selected-file private-value/PEM scan pass. Public provider Dev Logs stay planned; server injection and real production worker/provider acceptance remain under their existing rollout gates. [Handoff and receipt](results/api_secret_handoff_2026-10-17/HANDOFF.md).

## GitHub main publication — October 17, 2026, Asia/Shanghai

- **Status:** merged on GitHub and synchronized locally; advisory reservation released (`tau-github-main-merge-20261017`). [PR #9](https://github.com/JihuiTanUchicago/kalshi_trade/pull/9) merged at `2026-10-17T13:41:58Z` as `1df5d4ff834374d15d4ca5d334798194367ce6d2`. GitHub main and the tested source tree were independently confirmed; no rules bypass.
- Reconciled main `5da1922` and its 12 newer sandbox/execution/strategy-page commits before publication. Independent backend/frontend review found no actionable blocker. Final checks: **878 infrastructure Python passed / 9 skipped; 137 sibling Python passed / 22 skipped; 43 frontend passed; 11 synthetic browser routes/themes and focused controls passed**. GitHub had no required checks/reviews or Actions workflows configured; local evidence provided the verification.
- Original sources are preserved in backup directory `tau-pre-github-merge-20261017_213901` and stash `c84435800b9cc8ab9f7cd289e301c00ee189a966`; shared local main fast-forwarded to the GitHub merge. Private file bytes/modes are unchanged. Original evidence and unrelated worktrees remain. Only selected source/small records were published; bulk generated/provider/account data and private keys were excluded.
- Source publication is complete. Production deployment, migrations, provider/worker/model acceptance and trading activation remain separately gated; World Monitor remains default-off WIP. Public provider Dev Logs remain planned because this milestone does not establish production availability. [Final handoff](results/github_main_merge_2026-10-17/HANDOFF.md) · [GitHub receipt](results/github_main_merge_2026-10-17/MERGE_RECEIPT.json).

## Latest-main integration — October 17, 2026, Asia/Shanghai

- **Status:** complete locally / combined tree verified; reservation released (`tau-main-integration-20261017`). Shared local main is fast-forwarded to `0bd3bcf6ab80fd68d28594b63f11aad091326a19`; 58 reconciled local source files remain unstaged/uncommitted on top. No conflict entries or conflict markers remain.
- Target main: `0bd3bcf6ab80fd68d28594b63f11aad091326a19`, **67 upstream commits** after the local baseline `f8ff5e22fb65ca24e9407d8fcc75a9734262a487`. Today's local provider/knowledge work, older frontend work and sibling feed changes are recorded separately in the [daily release notes](results/main_integration_2026-10-17/RELEASE_NOTES.md).
- Six conflicted files were reconciled in an isolated checkout: PLAN, MVP, research agent, server, Tau JS and CSS. Streaming proposer and gatekeeper partitions now compose with Exa/gated news without losing token accounting, cancellation or infrastructure billing protection. The local research/artifact workspace retains upstream streaming cards, pause/resume, demo/live controls and the three funding buckets. Public Dev Logs keep provider rollout under planned work.
- **Verification on shared main:** infrastructure **849 passed / 9 skipped**, sibling **137 passed / 22 skipped**, frontend **39 passed**, 11 synthetic browser route/theme checks and focused streaming/control/artifact interactions pass with no page errors. Python/JS/shell syntax and full diff whitespace pass. Earlier fixture failures (new demo key/heartbeat fields and preview buckets/replay endpoint) are documented and superseded. No provider/model/account/DB call was used in this integration.
- Source/evidence backup: `/Users/jonathanzhang/Desktop/Polygon/.runtime/github-export/tau-main-backup-20261017_170009`; preservation stash `2efc7a7bec9cb125651fc25eee09ea5cf1cafd09` is retained, not popped. Private environment bytes/modes are unchanged. The staged-free original tree was updated only after comparison with the snapshot and tested integration files; previous PR worktrees and historical evidence remain.
- Upstream research/gatekeeper, sandbox, TAO, sports and live-safety history is retained below. Inherited deployed/live statements describe upstream's recorded state; this integration does not newly verify a production rollout. World Monitor remains active work in progress. No commit, push or deployment is authorized by this preparation.
- [Integration/recovery/evidence](results/main_integration_2026-10-17/HANDOFF.md) · [Daily release notes](results/main_integration_2026-10-17/RELEASE_NOTES.md). No push, new branch commit, PR mutation, deployment, migration, private-setting write or live-trading activation occurred. Real provider entitlements and production worker/model acceptance remain the next release gates.

## Exa Snapshot after pay-as-you-go activation — October 17, 2026, Asia/Shanghai

- **Status:** live-provider and historical adapter acceptance passed locally; advisory reservation released (`tau-exa-paygo-acceptance-20261017`). The user's pay-as-you-go switch resolved the prior Snapshot entitlement block.
- Three real Snapshot requests returned **HTTP 200**: historical Search **10 sources**, selected-page Contents **1**, historical publication-intent Search **10**. All retained the host cutoff **2026-10-10T08:53:56Z**; dates/cutoffs, prompt evidence, host citations, no live fallback and a network-free cache repeat passed. Provider cost telemetry was absent, so cost remains unknown.
- Existing local flags remain enabled and application_quotas=none. No runtime/private configuration edit, real LLM/DB/queued worker, production rollout/restart, purchase, commit, push or trading action occurred. The identical acceptance helper and fresh results preserve prior 403 evidence. Unchanged Exa code retains the prior offline verification; no redundant full-suite run was made for an account-state change.
- Current evidence (local archive: `results/exa_integration_2026-10-17/paygo_acceptance_2026-10-17/HANDOFF.md`). Synthesis was scripted. Remaining gate: production worker environment/deployment and real queued model/worker acceptance.

## World Monitor news monitoring — October 17, 2026, Asia/Shanghai

- **Status:** in progress; advisory reservation active (`tau-worldmonitor-news-20261017`).
- Add an independent news HTTP client, first-observed/versioned local journal, polling CLI and actual research/copilot news tool. Current headlines cannot leak into historical research. Existing Exa and market-data behavior remains separate.
- No AGPL server implementation is embedded, private credential/configuration write or paid/deployment/trading operation. Hosted API vs self-hosted preference is pending; the protocol adapter supports either configured origin.
- Scope and evidence (local archive: `results/worldmonitor_integration_2026-10-17/HANDOFF.md`).


## Initial Exa Snapshot activation — October 17, 2026 (earlier 403 attempt; superseded above)

- **Status at this earlier milestone:** local configuration enabled / provider acceptance blocked; verification complete and advisory reservation released (`tau-exa-snapshot-activation-20261017`). The subsequent pay-as-you-go acceptance above resolves its entitlement block.
- Both `TAU_EXA_ENABLED=1` and `TAU_EXA_HISTORICAL_ENABLED=1` are set in the ignored mode-0600 local `.env`, preserving the key and all unrelated private bytes. Network-free status confirms both enabled with application_quotas=none. No local agent/server process is running, so there is no local process to restart. Deployed worker environment/acceptance remains separate.
- Actual historical knowledge-adapter Search returned **HTTP 403 / entitlement** at a seven-day host cutoff; no live fallback. A separate diagnostic confirmed **SNAPSHOT_NOT_ON_PLAN**. Historical Contents/publication/cache acceptance could not proceed then. The user subsequently clarified only a card had been added, then switched to pay-as-you-go; all historical stages now pass in the follow-up above. Earlier evidence remains preserved.
- **Verification:** all **80 Exa tests pass**; runtime source unchanged, so the previous full regression **558 passed / 7 opt-in MySQL skipped** remains the relevant broader evidence. Two real historical HTTP attempts were denied. No quota was added, model/DB/queued-worker run, production action, purchase, commit or push occurred.
- Ownership and baseline (local archive: `results/exa_integration_2026-10-17/snapshot_activation_2026-10-17/HANDOFF.md`). Runtime code, frontend, other provider/trading settings, sibling sources and prior evidence are outside this configuration-only workstream.

## Exa quota removal and credential validation — October 17, 2026, Asia/Shanghai

- **Status:** implemented / offline and live-provider verified locally; advisory reservation released (`tau-exa-unlimited-20261017`). User supplied the key and requested removal of Exa budget/quota limits.
- Removed Exa run/month dollar ceilings, request/round/batch caps, forced five-result sampling and the unpublished budget-only DAO/schema dependency. Old quota environment variables are ignored. Provider-reported cost receipts, historical boundaries, cancellation, source validation and transport/context safeguards remain. Other data providers/model-credit/trading policies retain their existing behavior.
- Real Exa Search returned **10 sources**, selected-page Contents **1**, publication Search **10** through the actual knowledge adapter with a scripted model; host citations and a network-free cache repeat passed. Four HTTP attempts including Snapshot probe; successful responses reported **$0.015** total, not an independently reconciled invoice.
- At this earlier milestone Snapshot returned **HTTP 403 / entitlement**, so historical activation was left disabled. A subsequent workstream enabled the flag; the latest pay-as-you-go acceptance above resolves the provider block. Current-time web tools were verified. Workers must explicitly load the environment; the key and unrelated private bytes are preserved.
- **Verification:** 80 Exa tests; full regression **558 passed, 7 opt-in MySQL skipped**. Python/shell syntax and network-free status pass; all **323 non-owned baseline files** are unchanged. Obsolete quota DAO/tests were removed with the quota policy; the previous 569-test run is retained below as history.
- Implementation handoff (local archive: `results/exa_integration_2026-10-17/unlimited_2026-10-17/HANDOFF.md`) records ownership, provider receipts, failed system-Python status attempt and successful venv retry. Its Snapshot entitlement gate is resolved by the passing follow-up above. Production worker/model acceptance remains pending; no migration, deployment, restart, commit or push occurred in these Exa workstreams.

## Initial Exa integration — October 17, 2026 (historical; quota policy superseded above)

- Initial workstream `tau-exa-integration-20261017` connected native web/publication tools, provenance/citations, temporal scope and model usage metering to actual research/copilot interfaces. It was disabled and offline verified before the user supplied a key.
- That milestone passed 91 synthetic checks; full regression **569 passed, 7 opt-in MySQL skipped**, with 220 non-owned files preserved. Its budget DAO/schema and quota policy were subsequently removed at the user's request. No original migration or paid call ran.
- Original evidence, preserved as history (local archive: `results/exa_integration_2026-10-17/HANDOFF.md`) · [Current setup](app/README.md#exa-web-and-publication-research--october-17-2026). Scheduled news collection/event features remain separate work.

## Databento credentialed API checks — October 17, 2026, Asia/Shanghai

- **Status:** local authenticated stock/futures downloads and actual agent-data context verified; reservation released. Databento remains disabled persistently; production worker/model acceptance is pending.
- The real provider returned **10 SPY minute bars** (EQUS.MINI) and **10 ESZ6 minute bars** (GLBX.MDP3) for October 16, 14:00–14:10 UTC. Both reached `AgentMarketData.ask` through the real HTTP adapter and a scripted local model. Native prices, volumes, instrument/publisher provenance, complete intervals and cutoff boundaries passed.
- The user explicitly removed the spending ceiling for this test. Fresh provider quotes were allocated only in the test's in-memory budget; estimated/reserved total **$0.000006258488** (SPY), futures $0. This is not a reconciled vendor billing amount or a permanent budget/activation change.
- The authorized smoke used six successful HTTP attempts (four metadata, two downloads), then a cache repeat used **zero additional HTTP attempts or reservation**. Across both live stages: 14 attempts, three downloads (the futures window was read once directly and once through the agent loop). No real LLM call, runtime fix, credential/configuration edit, deployment or trading action.
- The first authorized continuation stopped locally because `.env` had changed outside the workstream and lost the key. The user restored it; the same prepared smoke then passed. Earlier missing-key/metadata-retry evidence is retained. Prior implementation regression **478 passed, 7 MySQL skipped** remains valid for unchanged runtime source; it was not rerun for this provider check.
- Remaining gates: durable paid-data accounting, explicit persistent dataset/worker configuration and a real queued model/worker canary. Current test funding does not activate future autonomous spending.
- Live acceptance/evidence (local archive: `results/databento_integration_2026-10-17/live_2026-10-17/HANDOFF.md`).


## Databento historical data integration — October 17, 2026, Asia/Shanghai

- **Status:** implemented locally and offline verified; reservation released. Disabled by default.
- Stocks/ETFs and explicit futures contracts now use the actual research/copilot data loop alongside Alpaca and Massive. Native 1-minute/hour/day OHLCV; per-schema availability, completed intervals, raw prices, instrument/publisher provenance and visible missing/partial coverage.
- Every download checks an estimated decimal cost; the default zero cap rejects positive-cost requests. Reservations persist across requests/asks on one data context; billable attempts are not retried. This is not a durable account/run-wide cap or a vendor billing guarantee. Provider charges are not passed through Tau model credits.
- **Verification:** 95 new offline tests; full regression **478 passed, 7 opt-in MySQL skipped**. Python and secret-loader shell syntax pass. The scoped patch has no trailing whitespace; whole-tree `git diff --check` retains five pre-existing `mvp.md` whitespace findings. All 321 non-owned baseline source files remain unchanged.
- A blank Databento key slot and disabled/zero-budget settings were appended to this product's ignored mode-0600 `.env`, preserving existing contents. Tracked examples contain no key; optional AWS secret-loader wiring is ready but was not run.
- Remaining gates: licensed datasets/key, explicit spending configuration, a bounded credentialed provider check and real worker/model canary. Live streaming, durable data-cost accounting, equity/futures backtests and deployment remain separate work. No provider/model purchase, trading or deployment took place.
- [Setup](app/README.md#databento-historical-data-for-agents--october-17-2026) · Verification and handoff (local archive: `results/databento_integration_2026-10-17/HANDOFF.md`).

## Massive credentialed provider checks — October 17, 2026, Asia/Shanghai

Locally verified with the real user-supplied key / reservation released. Two bounded
read-only passes used 10 HTTP attempts total. EUR/USD history returned 120 completed
hourly bars; Treasury yields returned 20 observations; funding conditions returned
31 observations. Tested SPY option-chain and current EUR/USD quote endpoints both
returned HTTP 403 (entitlement). Those capabilities remain blocked for this key;
no subscription change or fallback was attempted.

Live funding data exposed staggered observation dates: policy IORB had October 17,
while SOFR/effective fed funds had October 15. Agent macro context now retains each
series' latest non-null value, observation date/age and stale flag, independently
of the recent-row sample. Missing later values never become zero or refresh an
older series. Full regression: **383 Python passed, 7 opt-in MySQL skipped**.
Real read-only data reached a scripted model through the implemented agent context;
this is not a production worker/real-LLM acceptance claim.

The key stays in the ignored mode-0600 `.env`; tracked examples contain no key.
No credential/configuration file, worker flag, AWS/service state, frontend, schema,
order path or sibling source was changed. Persistent activation remains disabled.
Next gates: enable the missing provider permissions if required; deploy/configure
the worker securely and accept a real queued canary. No commit/push/deployment.
Live evidence and handoff (local archive: `results/massive_integration_2026-10-17/live_2026-10-17/HANDOFF.md`).


## Strategy label — October 17, 2026, Asia/Shanghai

Complete locally / browser verified. Rename the full Tau navigation tab and page heading from
Strategy Library to Strategy; retain position, routes, filters and artifact links.
Scope: two app.js labels and current navigation/usage records. No backend, CSS,
Meridian, provider, trading or sibling changes. JavaScript syntax passes; browser
confirms the Strategy heading, active Strategy tab and absence of the old label.
Current navigation/usage records and MVP updated; reservation released.


## Massive FX/rates/options agent data — October 17, 2026, Asia/Shanghai

Implemented locally / offline verified; disabled by default. Massive supplies
completed FX bars and entitled current FX quotes, daily Treasury/funding series,
and current option chains with Greeks, IV and prior-day open interest. Actual
research/copilot calls use the existing bounded data-request loop and model
metering. Alpaca remains independently supported. Historical research sees only
completed FX bars in its training window; current snapshots and latest-vintage
macro data are denied. Option results are bounded samples with explicit truncation.

Verification: **381 Python passed, 7 opt-in MySQL skipped**. Synthetic contracts
cover HTTP decoding into model context, real research/copilot entry points,
provider coexistence, cutoff boundaries, freshness, caching, credentials, errors,
pagination, cancellation and request budgets. Bash/Python syntax and protected
source checks pass. An interim cleanup regression removed Alpaca's timezone import;
its DST tests caught it, the import was restored, and the final full suite passes.

The initial offline phase prepared a mode-0600 ignored `.env` with an empty key
slot; the user later supplied it (see the credentialed checks above). The tracked
`.env.example` keeps blank credentials. AWS secret-loader wiring is ready but has not been executed.
That initial phase performed no credentialed provider/model acceptance, deployment,
service restart, publication or trading change. No integration write targeted frontend/server,
DB/schema or sibling source. The initial preservation snapshot matched all 314
protected files; later concurrent frontend source/documentation edits are retained
and recorded separately in OUTSIDE_SCOPE_CHANGES.json. Key/entitlement checks and a controlled
production worker canary remain gates. Reservation released.
Canonical handoff and verification (local archive: `results/massive_integration_2026-10-17/HANDOFF.md`).


## Strategy Library navigation — October 17, 2026, Asia/Shanghai

Complete locally / browser verified. Full Tau now has Strategy Library between
Research and Explore. The existing library has the same page title and its own
active-tab identity; filters and strategy links reuse the existing implementation.
Six synthetic browser checks and JavaScript syntax pass. Meridian, backend/API,
CSS, bootstrap, preview transport, credentials/trading and sibling work are unchanged.
Current navigation/usage/design and MVP records are aligned; no commit or deployment.
Reservation released. Evidence and handoff (local archive: `results/strategy_library_nav_2026-10-17/HANDOFF.md`).


## Latest main frontend inspection — October 17, 2026, Asia/Shanghai

Complete locally / offline verified. Main fast-forwarded from `0cc084d` to
`f8ff5e22fb65ca24e9407d8fcc75a9734262a487`. Alpaca PR #8 is now merged upstream;
its existing local modules/tests matched main exactly and are tracked cleanly.
The external theme bootstrap loads one frontend bundle after the local helper
scripts. Tau retains the Research/artifact workspace and combined Settings, with
Theme added as a section. Meridian's JS/CSS and boot.js match main unchanged.

Verification: 299 Python passed, 7 opt-in MySQL skipped; 31 Node passed; 8 synthetic
browser checks passed with no captured console errors. Both themes render, switch
back correctly and preserve Tau Research artifact behavior. The shared sample-data
preview runs on 8090 under the existing CSP. Meridian Dashboard is marked as the
browser deliverable; opening it in the app's right panel was queued by the host.
759 protected source files and 2059 old evidence files are unchanged; repository.py
and schema.py were intentionally updated to the fetched upstream versions.

No push, migration, deployment, provider/model call, live-flag or credential change.
Local changes remain unstaged/uncommitted and backed up. Actual account preference
persistence needs the upstream ui_theme schema migration and configured backend;
the preview saves only a local theme cookie and blocks other business writes.
Scope completed; reservation released. Canonical handoff (local archive: `results/main_frontend_sync_2026-10-17/HANDOFF.md`).

## Inherited upstream implementation history — fetched October 17, 2026

The following three sections preserve upstream's original implementation-stage notes and
verification counts. They are historical evidence, not new local test/deployment results;
newer upstream shipped statuses are retained in `../mvp.md`.

## Cross-contract research + cross-day gatekeeper — October 16, 2026 (worktree, research/eval only)

Builds §E.6: cross-contract relative value, sequenced AFTER the gatekeeper, with per-market
FDR streams and a cross-day generalization gate. Research + EVALUATION only — no cross-contract
LIVE execution, `engine.py`/the live gate untouched.

- **Spec extension** (`app/spec.py`): an optional `cross` block turns a spec into a
  relative-value PAIR — `{"pairing": "cross_sectional"|"cross_strike"|"calendar",
  "legs": [{"market": …}], "relationship": "spread"}`. `cross_sectional` = two different
  markets (BTC vs ETH), `cross_strike` = two strikes of one event, `calendar` = one strike
  across two settlements. `pair_entries()` groups snapshots by the pairing key and buys YES on
  the leg the GBM model says is underpriced + NO on the overpriced leg (combined edge ≥
  `entry.min_edge`). `cross=None` → ordinary single-contract spec, unchanged. Helpers:
  `is_cross_contract`, `involved_markets`, `stream_key`.
- **Backtest** (`app/backtest.py`): `simulate()` dispatches a `cross` spec to `simulate_pairs()`
  — one combined `Trade` per pair (entry_price = both legs' cost, exit_price = per-unit payoff),
  held to settlement, reusing the real Kalshi taker fee + `contracts_for` sizing.
  `merge_datasets()` unions single-market datasets into one whose frames carry every market's
  snapshots per decision ts (what a cross-sectional pair needs) and whose synthetic `Market.key`
  is the combined stream key. Contract gained a `series` field so a BTC leg is distinguishable
  from an ETH leg at the same frame. ETH/SOL/XRP ladders were already backtest-able (Phase 3).
- **FDR streams** (`app/gatekeeper.py` + schema): a cross spec's validation keys its LORD++
  stream on the merged dataset's combined `market` (`btc_daily+eth_daily`) — ONE shared stream,
  never double-spending each leg's per-market budget; single markets keep separate streams.
  `market` columns widened VARCHAR(16)→(48) to hold the combined key (idempotent MODIFY).
- **Cross-day gate** (`app/gatekeeper.py` `_cross_day`): splits validation trades into purged
  walk-forward folds (`stats.purged_walkforward_splits`) and buckets per-trade returns by day.
  STAT_SUPPORTED now also requires a majority of folds net-positive AND no single day carrying
  >90% of the positive edge — a one-day fluke drops to INCONCLUSIVE. The per-fold breakdown is
  stored on the result row (`app_experiment_results.folds_json`) and rendered by the existing
  research-paper folds strip (`server._experiment_block` prefers it over the rationale's).
- **Deferred** (`[v0.3]`): wiring agent.py to PROPOSE cross specs + merged validation/holdout
  partitions, and cross-contract LIVE execution.

## Arbitrary-quant code strategies in a hardened sandbox — October 16, 2026 (review worktree)

Goal: let the research agent author ARBITRARY quant code (any Python/numpy math/ML/framework)
as a strategy, run in a GENUINELY ISOLATED sandbox, still gated by the SAME statistical
pipeline. Freedom in METHOD, same bar on PROOF — the code computes the signal, but every
strategy still goes through pre-registration + the gatekeeper (purged walk-forward, FDR, DSR,
holdout). Freedom must not reintroduce overfitting, and must not touch live trading.

- `app/sandbox.py` — now two tiers.
  - Tier 1 (unchanged): `safe_policy()` runs a PURE-function ExplorationPolicy in-process
    (AST ban + minimal builtins + timeout + fall back to DefaultPolicy).
  - Tier 2 (new): `run_strategy_signals(code, window)` runs untrusted strategy code in a FRESH
    `python -I -B` child whose isolation boundary is the OS KERNEL, not the interpreter. (You
    cannot securely sandbox code that can `import numpy` inside a Python process — numpy exposes
    `ctypes`, and any allowlisted stdlib module reaches the real os/sys through NON-dunder attrs
    like `random._os`; a prior security review demonstrated a working file-read + socket escape
    of a Python-only gate. So the Python layer is now DEFENSE IN DEPTH, and the boundary is
    `_confined_argv`.) The child runs under the platform kernel sandbox, and if none exists the
    call is REFUSED (default-deny — untrusted code never runs unconfined):
      * macOS (dev): `sandbox-exec` profile — deny ALL network, deny writes outside the scratch
        dir, deny reads of credential stores (`…/credentials/…`, `.env`, `.pem`, `.ssh`, `.aws`,
        `id_rsa`/`id_ed25519`, `…/secrets…`).
      * Linux (prod): `bwrap` (`--unshare-net`, read-only root, scratch the only rw mount) or
        `firejail` (`--net=none --read-only=/`). No network ⇒ no DB, no order placement, nothing
        read can be exfiltrated; the keyfile/DSN are inert.
    Verified end-to-end: the demonstrated `random._os` credential read and the
    `importlib`-bypass socket now both fail with kernel PermissionError. Defense in depth (still
    there, not the boundary): scrubbed env (no PROD_KEYID/KALSHI_*/DSN/AWS; `-I` ignores
    PYTHON*/cwd/user-site), restricted builtins + import gate + AST dunder/import ban, and
    rlimits (RLIMIT_CPU hard-kill + parent wall-clock + AS[Linux] + FSIZE + NOFILE + CORE=0).
    ponytail: RLIMIT_AS is Linux-only (macOS refuses it); tmpfs-over-every-secret-path on Linux
    is the follow-up if a non-exfil local read ever matters (unshare-net already makes it inert).
- `app/spec.py` — `validate()` branches to `_validate_code_spec` when the spec has a `code`
  field: a minimal `{market, sizing, code}` spec (sizing range-checked like the DSL; code
  statically validated by the sandbox; unknown top-level fields rejected). `CODE_STRATEGY_GUIDE`
  (appended to `SPEC_GUIDE`, so every proposer prompt surfaces it) defines the interface;
  `describe()` renders a code spec in plain language; `is_code_spec()` is the one predicate
  callers use.
- `app/backtest.py` — `simulate()` detects a code spec and precomputes a per-frame target book
  once via the sandbox (`_code_book`), then the EXISTING entry/exit/sizing/fee/settlement loop
  consumes it through `_code_entries`/`_code_exit` exactly as it consumes DSL `entries`/
  `exit_signal`. `_parse_book` validates the untrusted sandbox output (shape, tickers, side,
  finite score); ANY sandbox failure or malformed output → empty book → zero trades, so a
  broken/hostile strategy fails the gate honestly instead of crashing research. The gatekeeper
  re-simulates the frozen code spec on validation/holdout with no change (same `simulate`).
- `app/agent.py` — `act()` deploy / deploy_live now reject `is_code_spec` strategies up front:
  arbitrary code runs ONLY in the research sandbox and never in the live/paper engine (which
  evaluates the DSL rule via `specmod.entries`). Live-trading gate and `engine.py` untouched.
- Tests: `tests/test_sandbox_isolation.py` (socket/env/file/os-import/dunder/subprocess blocked;
  CPU + wall-clock caps fire; mem cap asserted where RLIMIT_AS is settable, else skipped; numpy
  + pure-python strategies run) and `tests/test_code_strategy.py` (code spec validates; bad code
  rejected; same fees/settlement as the DSL path; signal-driven exits; sandbox failure → no
  trades; flows through the real gatekeeper and gets classified; code is the experiment identity;
  blocked from deploy). Suite: 377 passed, 8 skipped.

## Rigorous quant-research pipeline + dev-env trading foundation — October 16, 2026

Full design + signatures: `RESEARCH_PIPELINE_DESIGN.md` (source of truth). The research
loop was turned from "generate → fixed-70/30-OOS gate" into a statistically-disciplined
engine that separates GENERATION from JUDGMENT:

- `app/stats.py` — pure validity math: Benjamini-Hochberg / Benjamini-Yekutieli FDR,
  LORD++ online-FDR (persistable alpha-wealth state), Probabilistic + Deflated Sharpe,
  stationary-bootstrap CI (the primary validation p-value), timestamp-based purged
  walk-forward + embargo splitter. Reuses `app/quant.py`.
- Immutable experiment ledger (`app/schema.py`: `app_experiments` [pre-registration,
  INSERT-only], `app_experiment_results` [append-only verdicts], `app_fdr_state`,
  `app_holdout_ledger`, `app_data_partitions`) via `app/research_repository.py`.
- `app/partitions.py` — frozen chronological Research/Validation/Locked-Holdout split
  (60/25/15), purge/embargo tied to each market's settlement cadence; validation/holdout
  loaders are gatekeeper-only (the generator can't reach them).
- `app/gatekeeper.py` — the Statistical Gatekeeper, the only module that reads
  validation/holdout. Pre-registers hypotheses, spends the FDR budget, classifies
  Rejected→Inconclusive→Promising→Stat-supported→Forward-validated→Deployment-candidate.
  STAT_SUPPORTED ⟺ LORD reject AND BH reject AND DSR≥0.95 AND CI_lo>0 AND placebo passes.
- `app/agent.py` — 9-phase proposer + a Challenger LLM pass (3-role: propose→challenge→
  execute); `_memory_block` no longer leaks held-out pnl into the next prompt; deploy /
  deploy_live gained an ADDITIVE, fail-closed `DEPLOYMENT_CANDIDATE` requirement on top of
  every existing live gate (nothing weakened). Strategy detail page is now a research paper
  (thesis/mechanism/pre-registered test/results/holdout + 5 charts) via `server.py`'s
  additive `experiment` block (old strategies → `experiment: null`).
- Dev-env trading FOUNDATION (dormant until integrated): `app_kalshi_dev_keys` table,
  per-user dev-key accessors in `repository.py`, and `app/kalshi_dev_exec.py` — an
  authenticated Kalshi DEMO (sandbox) execution client, host-isolated so it can never
  reach the production exchange.
- Dev-env trading INTEGRATION (BUILT, uncommitted — awaiting user review): `engine.decide`
  gained a `demo` mode alongside `paper`/`live` via a shared `via_kernel` path —
  `Sources.demo_kernel` = `kalshi_dev_exec.demo_kernel_factory(conn)`, wired defensively in
  `run_forever` (a demo-host misconfig can't take down paper/live). DESIGN DECISION: demo
  reuses the PRODUCTION book (`MarketFeed`/`fetch_quotes`) for the SIGNAL but routes every
  ORDER to the demo kernel against the sandbox host — clearly separated, no LIVE switch,
  structurally incapable of reaching the real exchange (foundation host guard stays).
  `server.save_kalshi_dev_key`/`delete_kalshi_dev_key` mirror the live-key endpoints
  (verify against the sandbox via `demo_fills`, encrypt with `kalshi_account.encrypt_private_key`,
  store in `app_kalshi_dev_keys`; raw key never logged/echoed). `create_deployment` accepts
  `mode='demo'` (requires a dev key on file, YES-only). SECURITY GAP CLOSED: `create_deployment`
  `mode='live'` now also requires `agent._is_deployment_candidate` (the manual path matches the
  autopilot path; additive, fail-closed — no existing live gate weakened). `dashboard()`
  aggregates money into three mode buckets (live/demo/paper) via `_mode_bucket`, no double-count.
  Frontend (both themes, byte-identical for shared snippets): Funds demo-key form, "Deploy on
  demo (sandbox)" affordance, three-bucket dashboard, LIVE/DEMO/PAPER row labels.

Verification: 336 passed / 7 skipped; live-gate tests green; `/security-review` clean
(no new HIGH/MEDIUM). Live-trading gate unchanged except made stricter.

## Alpaca market data for agents — October 16, 2026, Asia/Shanghai

Implemented for PR review; disabled by default. Agents previously received only
Kalshi-specific data summaries. `app/alpaca_data.py` now reads stock/ETF snapshots
and raw OHLCV history, and `app/agent_market_data.py` supplies watchlist context and
bounded on-demand reads to the actual research/copilot call sites. Research reads
stay within its training window; current snapshots are restricted to copilot.
Feed/time provenance, stale/invalid data, pagination, cache separation, retry and
request limits are explicit. Data-request model rounds retain usage metering and
research cancellation checks. Credentials remain server-side; no order/account
endpoint, equity strategy/backtest, streaming collector, schema or dependency is added.

Verification on the exact PR branch: 258 Python tests passed, 7 opt-in MySQL tests skipped. Provider and agent
contract tests cover synthetic HTTP/model responses. A separate local read-only
IEX smoke check supplied a scripted agent with a real SPY trade/quote snapshot and
44 historical hourly bars, with sampled history before its cutoff. SIP and a real
production model/worker have not been live accepted. [Setup and limits](app/README.md#alpaca-stocketf-data-for-agents--october-16-2026).

Next gates: secure worker configuration and explicit activation, appropriate data
entitlements, then production canary acceptance. The checked-in secret loader and
per-user canary controls require follow-up before a controlled customer rollout.
No deployment or live trading is enabled by this PR.

## Alpaca integration PR — October 16, 2026, Asia/Shanghai

October 17 update: PR #8 merged upstream as `058dde5`; publication evidence below
describes its earlier review state. Production activation remains separate.

Published for review: [PR #8](https://github.com/JihuiTanUchicago/kalshi_trade/pull/8),
open, non-draft and attached. Branch `codex/alpaca-market-data-20261016`, commit
`b102c5aaa63dc88dadd09626032c8e2f6561ef4b`, based on verified main `0cc084d`.
Only 10 Alpaca code/test/env/documentation files are included; unrelated frontend
and sibling work is excluded. Exact clean PR tree: 258 Python passed/7 opt-in
MySQL skipped; staged whitespace, syntax and private-value checks pass. The
earlier 291-test result belongs to the shared tree with local frontend tests.
GitHub reports clean/mergeable, with no reported CI checks. All 318 protected
shared sources and the shared main HEAD/index are preserved. No merge,
deployment, worker restart, credential update or model/financial operation.
Reservation released; review and production activation remain separate gates.
Publication handoff (local archive: `results/alpaca_pr_2026-10-16/HANDOFF.md`).

## Alpaca market data for agents — October 16, 2026, Asia/Shanghai

Implemented locally; focused/full tests and read-only live IEX checks pass. New
`app/alpaca_data.py` supplies snapshots and paginated raw OHLCV bars;
`app/agent_market_data.py` supplies watchlist context and bounded on-demand symbol
reads to actual research/copilot calls. Provider/feed/time provenance, stale-data
handling, fixed data-only endpoints, retries/cache/request bounds and historical
training cutoffs are enforced. Usage includes tool-request model rounds; research
cancellation remains effective. This does not add equity strategy features,
backtests, brokerage accounts, orders, news or a streaming collector.

Verification: 59 focused tests pass; full Python suite 291 passed/7 opt-in MySQL
skipped. Existing private local credentials were read only for an ephemeral live
smoke process: a scripted agent received a real SPY trade/quote snapshot and 44
hourly bars, with sampled history before its cutoff. No credential file modified
or written. IEX verified; SIP is configurable/offline tested, not live accepted.

Owned: new provider/context modules/tests, narrow agent integration, env template,
app README/product notes, tracker, required MVP queue and isolated evidence.
Frontend/server, database/schema, Kalshi execution/live flags, existing previews,
credentials, standalone Polygon and sibling feed work remain outside scope.
No commit, push, deployment, paid subscription or model call. Next gate: load
credentials and `TAU_ALPACA_ENABLED=1` into the real agent worker environment;
confirm commercial data entitlement before customer rollout. All 310 protected
sources match the baseline. New additions pass whitespace checks; five existing
MVP whitespace warnings are preserved. Advisory reservation released; handoff
contains reproducible commands and the activation boundary.
Workstream handoff (local archive: `results/alpaca_market_data_2026-10-16/HANDOFF.md`).

## Latest GitHub main + local merge — October 16, 2026, Asia/Shanghai

Complete locally / offline verified. Shared main fast-forwarded from `e40d060` to
`0cc084d084e1296bc524509919647e307f2ec45f`, matching GitHub main on final API check.
Five overlaps were reconciled in an isolated checkout before applying the validated
overlay. All local user work remains uncommitted. Research/artifact, Dashboard,
Settings and Hot Markets preserve main's model picker, RSI, paginated strategy
search/bulk deployment, holdings, demo replay, sharing, notifications, Community,
Dev Logs, receipts and version banner. The version marker uses an HTML data attribute
so the existing script CSP remains intact. Session grouping follows all API pages;
saved demo replay and what-if curves remain distinct.

Scope: local source reconciliation and focused compatibility tests/docs. No push,
remote merge, deployment, migration, credentials/provider/account operations or live
flags. Standalone Polygon, sibling feed work and historical evidence are preserved.
Final verification: 244 Python passed, 7 opt-in MySQL skipped; 31 Node passed;
23 synthetic browser checks passed, including the shared preview under production
CSP. 641 protected source files and 2016 historical evidence files match backups.
The preview at 8090 serves current API shapes with all business writes disabled.
No authenticated/production/mobile acceptance claimed; scoped chat backend remains
pending. Reservation released. Recovery and exact commands are in the
canonical handoff (local archive: `results/local_github_merge_2026-10-16/HANDOFF.md`).


## Landing demo animations — no-reflow (2026-10-15) — SHIPPED
Three animated demo containers used to **expand** as rows/cards arrived (reported as annoying).
All now hold a constant size so the page never reflows mid-animation:
- **Hero research panel** (`#demo-body`, `startDemo()`): every variable-height region reserves
  its full size *structurally* — no fragile measurement (an earlier measure-and-lock approach
  broke because it ran before the Rubik web-font loaded, so the real 2-line bubble overflowed it).
  Cards are pre-built hidden; the typing bubble and the status line each carry a `visibility:hidden`
  **ghost** holding their final/longest text, grid-stacked under a `.live` span that receives the
  typed/swapped text. The ghost reflows with the real font, so the box holds full height from frame
  one and the live text can never grow it. Verified by injection: bubble height constant (65.5px
  @420px) from empty → partial → full text. Demo idea copy also shortened to one desktop line:
  "Sell overpriced tails in last hour before 5pm close".
- **Deploy fills** (`#sc-pos`) and **autopilot log** (`#sc-loop`): fixed-height windows
  (`align-content:end` + `overflow:hidden` + a top fade `mask-image`); new rows append at the
  bottom and older ones scroll up under the fade — reads as a live feed, no growth. `scroll-behavior`
  drops to `auto` under `prefers-reduced-motion`.

## System map zoom-in (2026-10-15) — SHIPPED
Drill from a System-map box into the real code behind it, three levels deep:
**component → module → function** (source + call graph).
- **`app/code_map.py` (new):** read-only static analysis with stdlib `ast`, no new deps, no DB.
  `COMPONENTS` maps each non-external system-map node id → its source files (`app/*`,
  `data_pipeline/*`). `resolve_module()` is the security boundary — it `Path.resolve()`s the
  request-supplied path and rejects anything not a `.py` file inside `app/` or `data_pipeline/`
  (traversal, absolute paths, symlink escapes all collapse and fail before any read).
  `component_modules()` / `module_symbols()` / `function_detail()` serve the three levels.
  The call graph is **name-based** (a `foo()` call links to every def named `foo` across the
  mapped files) and cached once per process — plenty for "who touches this" navigation.
- **`GET /api/system/code` (new route, `system_code` handler in `app/server.py`):** auth-required,
  open to any signed-in user like `admin_system` (it's the "show the homework" proof). Query:
  `?component=<id>` → modules; `?module=<path>` → functions+classes; `?module=<path>&func=<qual>`
  → source + callers/callees. `CodeMapError` → `ApiError(404)`.
- **SPA (`viewSystem` in `app/static/app.js`):** the detail panel gains an "Open the code ›" button
  on non-external nodes; drill-down renders modules → functions → function source with clickable
  callers/callees (jump across modules). A `codeState` flag stops the 4s telemetry poll from
  clobbering the open drill-down. CSS under `.sys-crumb/.sys-list/.sys-src` in `app/static/app.css`.
- **Tests:** `tests/test_code_map.py` — AST extraction at all 3 levels + path-whitelist rejection
  (traversal / out-of-repo / non-`.py`). 15 cases, suite green (166 passed, 7 skipped).

## UI tweaks (2026-10-15) — SHIPPED
- **Billing moved into a profile dropdown.** Removed `Billing` from the top nav; clicking the
  user's name in the masthead now opens a small Kursbuch menu (`.profile-menu`) with Billing +
  Sign out. (`app/static/app.js` `shell()`, `app/static/app.css` `.profile*`.)
- **System page fixed for non-admins.** `viewSystem()` had a leftover `if (!adminViewOn()) go('/')`
  guard that bounced every normal user home — the System tab was visible but dead for them. Removed;
  the `/api/admin/system` route was already public (admin-only fields gated inside it).
- **Payment showcase dots are now clickable.** The reel under the "Add a payment method" art
  auto-advanced only; dots are real `<button>`s that jump to a picture and reset the timer
  (`paymentGate()` `show(i)`/`restart()`). Dropped `aria-hidden` on the reel so the controls aren't
  focusable-inside-hidden.

## Frontend cosmetics PR — October 16, 2026, Asia/Shanghai

Current GitHub status: closed, unmerged; historical publication evidence below is retained.

Published for review: [PR #7](https://github.com/JihuiTanUchicago/kalshi_trade/pull/7),
open, attached and clean/mergeable. The requested short cosmetic-only comment is
posted. Final branch `codex/frontend-cosmetics-20261016`, commitf241469 on current
clean-history maina46e1b8. Reapplied only presentation work; existing main Research/
Strategies, model selection, Kalshi demo, profile, code browser and Community
features remain. Earlier unmerged conversation/artifact features are excluded.
Only the Settings SPA route allowlist changes server.py; business handlers stay.

Main was rewritten twice during preparation/publication; exact Git objects were
verified/imported and the branch rebased with a lease on its owned prior head.
GitHub confirms the exact13 files/commit/tree.177 Python passed, 7 opt-in MySQL
skipped;15 synthetic desktop browser and6 static-handler checks pass, plus syntax/
whitespace. Phone/authenticated services/CI acceptance are not claimed.772 shared
sources and2 external sources, original HEAD/index and8090 preview are preserved.
Owned QA servers/successful tab closed; error tab29 cannot be closed through Browser
because of its generated data URL. Isolated publication checkout retained, clean.
No merge, deployment, provider/model or financial operation. Ownership released.
Canonical handoff (local archive: `results/frontend_cosmetics_pr_2026-10-16/HANDOFF.md`).

## Overview heading cleanup — October 16, 2026, Asia/Shanghai

Implemented and browser verified. Overview uses the shared page-title style without
its subtitle or bottom divider. New research and the portfolio-first body remain.
Live realized P&L/history freshness are retained with account details; paused/live
states remain in Deployed. Compact Hot Markets is unchanged.

Owned seven frontend/current product/design/readme/surface/plan paths plus isolated
evidence; existing dirty work, backend/API/feeds/guards, fixtures, MVP, sibling work,
PRs and earlier evidence were outside scope. No commit/push/deploy/provider/account/
trading operation. Verification:25 passing browser checks at1280px and the native
1015px preview, including live/stale/missing-history/paused/empty fixtures. No errors
on the main preview; JS syntax, served asset hashes,766 repository +2 external
protected sources pass. All56 API literals and JS outside Dashboard are unchanged;
CSS changes one Dashboard-only rule. QA assertion diagnostics are corrected and
retained with passing replacements. No new unit/full suites for this reversible
presentation change. Screenshots inspected; native Dashboard refreshed. Owned QA
tab and synthetic8096 server closed; original8090 preview retained. Ownership
released. Canonical handoff (local archive: `results/overview_heading_cleanup_2026-10-16/HANDOFF.md`).

## Compact Hot Markets heading — October 16, 2026, Asia/Shanghai

Implemented and verified. Follow the supplied Position-page screenshot: use its existing compact
Hot Markets heading on Dashboard too. Remove the Overview-height stretching and
its extra measurements. Both visibility controls remain removed; all existing
panel widths, top navigation, quotes, page content and phone flow stay as restored.
This supersedes the previous request to align the two Dashboard heading dividers.

Owned seven frontend/product/design/readme/surface/plan paths and isolated evidence.
Existing dirty source, backend/API/feeds/guards/fixtures, MVP/marketing, sibling work
and PRs are outside scope. No commit/push/deploy/provider/account/trading operation.
Verification:23 browser assertions across Position/Dashboard/Research/Settings at
1280px pass; every heading measures43.195px, versus the former82.375px Dashboard
header. The native Position preview at1015px is refreshed and also measures43.195px.
No browser errors. JS syntax, served hashes,3 JS/1 CSS exact edits and766 repository
+2 external protected sources pass; all56 literal API calls remain unchanged.
No new unit/full suites for this reversible refinement. Ownership released; owned
QA tab closed and native user page retained. Handoff (local archive: `results/hot_markets_compact_heading_2026-10-16/HANDOFF.md`).

## Hot Markets controls and divider — October 16, 2026, Asia/Shanghai

Implemented and verified. Removed both Hot Markets visibility controls and saved collapsed state;
keep the panel open in its existing location. Align the panel heading divider with
the bottom of Overview while the two columns are side by side. Measure the actual
Overview header so wrapping, polling and resizing preserve alignment; phones keep
the existing stacked flow. No other visual or page changes.

Owned seven existing frontend/product/design/readme/surface/plan records and
isolated evidence. Existing dirty work, backend/API/feeds/guards, data/fixtures,
MVP/marketing, sibling products and PRs remain outside scope. No commit, push,
deployment or provider/account/trading operation. Verification:17 browser assertions
pass at the actual1015px viewport, including exact0px divider offset after load,
reload and navigation; no browser errors. JS syntax,2 served asset hashes,10 JS/11
CSS exact edit replays and preservation of766 repository +2 external sources pass.
All56 literal API calls are unchanged. No new tests/full suites for this small
layout change. Temporary QA tab closed; original preview and user navigation
preserved. Ownership released.
Handoff (local archive: `results/hot_markets_alignment_2026-10-16/HANDOFF.md`).

## Restore previous frontend — October 16, 2026, Asia/Shanghai

Restored the saved version before the rejected Hot Markets toggle/line-cleanup
workstream, at the user's request. Top navigation, prior dashboard layout,
Hot Markets chevron toggle and original separators are back. Both runtime assets
match the saved pre-cleanup bytes. Earlier Research/Settings/backend-compatible
work and unrelated dirty files remain. Source/evidence for the rejected design
are archived; its visual gate was never satisfied and is superseded by this revert.

Verified: JavaScript syntax, both served/runtime assets exactly match the saved
pre-cleanup bytes,10 browser assertions pass and no browser errors. Top navigation,
original dividers,176px chart, quote toggle/resizing, Research and Settings are
restored.766 repository +2 external protected sources remain unchanged. No new
tests or full suites were needed for this exact-byte restoration.
Ownership released after verification: seven prior frontend/product/design/readme/surface/plan paths and isolated
revert evidence. No backend/API/feed/guard/fixture/MVP/sibling/PR changes or commits,
pushes, deployments or account/trading operations.
Canonical revert handoff (local archive: `results/frontend_line_cleanup_revert_2026-10-16/HANDOFF.md`).

## Hot Markets below header — October 15, 2026, Asia/Shanghai

Implemented locally, verified and approved by **GPT-6.1 Sol: 9.2/10**, no blockers. One full-width black header now sits above a shared row of Hot Markets and page content. Their top edges meet the header bottom; neutral rules join the panel divider. Above 600px the rail reserves page width; phones stack the panel between header and page. The chevron-only toggle, removed RIGHT NOW copy, quotes/refresh, persistence, navigation, keyboard/focus and existing page features remain. Charts explicitly resize on toggle; the sticky rail fits the remaining viewport while scrolling.

Verification: **282 browser assertions**, **29 Node tests**, **17 focused Python tests** and JavaScript syntax pass; no browser runtime errors. Nine toggle widths, eleven routes at four widths, sticky scrolling/resizing, chart width changes, focus and the existing System read-error state are covered. **766 protected sources unchanged**; declared shell/layout changes replay exactly, with all other page/data/API/guard/chart-renderer logic identical. API paths and controls are unchanged; the existing rail ID moves into literal shell markup and gains its landmark name. Full Python regression was not rerun for this layout-only integration. Source hashes stayed fixed during independent review. The scroll-fit optimization and sparse mobile quote spacing are nonblocking follow-ups.

Canonical handoff (local archive: `results/hot_markets_header_2026-10-15/HANDOFF.md`), review (local archive: `results/hot_markets_header_2026-10-15/REVIEW.md`), verification (local archive: `results/hot_markets_header_2026-10-15/VERIFICATION.json`), browser receipt (local archive: `results/hot_markets_header_2026-10-15/BROWSER_CHECKS.json`) and preservation (local archive: `results/hot_markets_header_2026-10-15/PRESERVATION.json`). Native http://127.0.0.1:8090/ refreshed with Hot Markets open at restored 1015×954: full-width header, 248px rail and 767px page meet at the same boundary, without overflow. QA tab is closed; the existing read-only sample preview remains, with writes disabled. Owned seven shell/layout and current product/design/readme/surface/plan paths plus isolated evidence; advisory ownership released. Backend/API/feeds/guards, prior copy/page features, preview transport/fixtures, public marketing, MVP, PRs, Polygon/sibling work and prior records remain untouched. No commit, publication, deployment, migration or provider/financial operation. Next: user review; broader visual and live-backend gates remain separate.

## Hot Markets icon toggle — October 15, 2026, Asia/Shanghai

Implemented locally, verified and approved by **GPT-6.1 Sol: 9.3/10**, no blockers. Removed RIGHT NOW/dot and the black-header Hot markets label. The compact left control now uses double chevrons, right to open and left to close, with accessible state labels and matching native tooltip. Quote-panel title, desktop/coarse targets, keyboard/focus, dock dimensions/phone flow, navigation and all data/actions remain.

Verification: **57 browser assertions** at 1280/1024/600/320px in both states, JavaScript syntax passed, no runtime errors. No unit/full suites added/rerun for the reversible markup/CSS refinement. **766 protected sources unchanged**; only two JS markup lines and a tooltip assignment differ, with all other copy/API/data/chart/dock/guard logic identical and unchanged paths, IDs, controls and ARIA labels/counts. Source hashes were fixed for the independent review; its minor stroke-size nit is nonblocking.

Canonical handoff (local archive: `results/hot_markets_toggle_2026-10-15/HANDOFF.md`), review (local archive: `results/hot_markets_toggle_2026-10-15/REVIEW.md`), verification (local archive: `results/hot_markets_toggle_2026-10-15/VERIFICATION.json`), browser receipt (local archive: `results/hot_markets_toggle_2026-10-15/BROWSER_CHECKS.json`), preservation (local archive: `results/hot_markets_toggle_2026-10-15/PRESERVATION.json`). Native http://127.0.0.1:8090/ refreshed with observed collapsed state and restored 1015×954 viewport; QA tab closed, preview server unchanged, sample data/writes disabled. Owned shared toggle/panel markup/CSS, current PRODUCT/DESIGN/surface/README/PLAN notes and isolated evidence; advisory ownership released. Backend/API/quotes/guards, prior cleanup/dock, transport/fixtures, public pages, MVP, PRs, Polygon/sibling work and prior records remain untouched. No commit, provider/financial operation, publication, deployment or migration. Next: user review. Scoped approval leaves broader visual/live-backend gates separate.

## Hot Markets dock — October 15, 2026, Asia/Shanghai

Implemented locally, verified and independently approved by **GPT-6.1 Sol: 9.2/10**, no blockers or lost features. Toggle is first on the left of the shared header. Above 600px the entire app reserves a 248–306px rail; smaller phones stack the bounded-height panel above the app in document flow. The old <=1080 overlay rule and width animation are removed, so panel visibility and reserved space change together. Quote data/API/refresh, persistence, navigation, closing focus, chart sizing, prior copy cleanup and Dashboard layout remain.

Verification: **246 browser assertions**, **29 Node tests**, **17 focused Python tests** and JavaScript syntax pass; no browser runtime errors. Nine toggle widths and eleven routes at five widths cover fit/no-overlap, chart expansion/contraction, keyboard/focus, one rail, persistence, SPA/Settings navigation and read-error behavior. **766 protected sources unchanged**; all JavaScript outside toggle movement/rail DOM placement is identical, with unchanged API paths, HTML IDs, controls and ARIA labels. Full Python regression was not rerun. The authenticated sign-in redirect expectation was corrected in QA and recorded. Review is scoped to this integration; earlier overall visual design and live-backend gates remain separate.

Canonical handoff (local archive: `results/hot_markets_dock_2026-10-15/HANDOFF.md`), review (local archive: `results/hot_markets_dock_2026-10-15/REVIEW.md`), verification (local archive: `results/hot_markets_dock_2026-10-15/VERIFICATION.json`), browser receipt (local archive: `results/hot_markets_dock_2026-10-15/BROWSER_CHECKS.json`) and preservation (local archive: `results/hot_markets_dock_2026-10-15/PRESERVATION.json`). Native latest page at http://127.0.0.1:8090/ is refreshed with Hot Markets open: 248px rail + 767px app at restored 1015×954. Main read-only sample preview PID85246/session13271 remains; QA tab is closed and no extra server started. Owned shared header/rail JS/CSS, current PRODUCT/DESIGN/surface/README/PLAN notes and isolated evidence; advisory ownership released. Backend/transport/fixtures, feeds/execution/guards, public marketing redesign, MVP, PRs, Polygon/sibling work and prior records remain untouched. No commit, publication, deployment, migration or provider/financial operation. Next: user review.

## Frontend copy cleanup — October 15, 2026, Asia/Shanghai

Implemented locally, verified and approved for copy cleanliness. Removed repeated descriptions, workflow/keyboard tutorials, payment pitches and explanatory empty-state paragraphs across all customer tabs, Research/session/artifact/library, market detail, Settings and dialogs. System descriptions are shorter; session terminology and related actions are consistent. Actual data/research/chat content, labels/accessibility, useful errors/states, evidence/provenance, fees/limits, paper/live consent and saved/scenario meaning remain. Hot Markets only loses an unsupported empty-state timing promise; its behavior/layout and the portfolio-first Dashboard remain.

The user-required **GPT-6.1 Sol** subagents reviewed the baseline (**6.3/10**) and each revision (**9.1/10**, final **9.2/10**, approval YES, no harmful deletion). A capacity error interrupted the first final-review attempt; the same reviewer/model resumed and completed. Final source hash `f2d8da4f7a5ad3245e2a1e3086dca9d34e4ac75fbcfca539f01fcaf8854f428e` was fixed throughout final review. The **≥9/10 copy gate is satisfied**; this does not close the earlier overall visual design gate or live backend acceptance.

Verification: **123 browser assertions**, **29 existing Node tests**, **17 focused Python tests** and JavaScript syntax pass. Eleven routes were checked at desktop/phone widths; isolated fixtures cover empty/error states, configured Billing/System, chat drafts/newlines/switching, payment prerequisite, risk/LIVE/scenario meaning and autopilot confirmation. No browser runtime errors. **766 protected sources unchanged**; all 59 declared replacement records replay exactly, API paths/HTML IDs/control names/ARIA labels/control-tag counts are identical, and CSS changes only Send alignment. Full Python regression was not rerun for this copy edit. QA diagnostics and the unchanged payment-modal Escape observation are retained; research stays blocked without a card.

Canonical handoff (local archive: `results/frontend_copy_cleanup_2026-10-15/HANDOFF.md`), final review (local archive: `results/frontend_copy_cleanup_2026-10-15/REVIEW_FINAL.md`), verification (local archive: `results/frontend_copy_cleanup_2026-10-15/VERIFICATION.json`), browser receipt (local archive: `results/frontend_copy_cleanup_2026-10-15/BROWSER_CHECKS.json`) and preservation (local archive: `results/frontend_copy_cleanup_2026-10-15/PRESERVATION.json`). Existing native preview at http://127.0.0.1:8090/ is refreshed on the latest page, with its viewport restored and Hot Markets collapsed; PID85246/session13271 remains the read-only sample preview. Temporary QA tabs/server are closed. Owned only `app.js` copy, Send alignment, current PRODUCT/DESIGN/surface/README/PLAN notes and isolated evidence; advisory ownership released. Existing backend/API/guards/transport/fixtures, standalone operator console, public marketing redesign, PRs, MVP, Polygon/sibling work and prior records remain untouched. No commit, publication, deployment, migration or real provider/financial operation. Next: user review; authenticated-account acceptance remains separate.

## Dashboard layout only — October 15, 2026, Asia/Shanghai

Implemented locally and verified. The user approved the Dashboard portion of the preview and explicitly retained existing Hot Markets. Paper portfolio/open positions now lead, followed by performance and recent research; the complete deployed table and settled trades remain below. Account panels stack at 760px and below. Existing API reads, formatting, polling, chart sizing, error isolation and actions remain unchanged.

Verification: **79 browser assertions**, **29 existing Node tests** and **17 focused Python tests** pass; JavaScript syntax and scoped whitespace/links pass. Browser checks cover 320/760/1024/1440px, source values and daily losses, keyboard disclosure, unchanged Hot Markets drawer/focus/chart resizing, and isolated synthetic research-read failure/recovery at desktop/phone widths. No browser runtime errors. **766 protected sources unchanged**; JavaScript outside the Dashboard template and all Hot Markets CSS lines are identical to the dirty baseline. No new production tests or backend behavior were added for this layout change; the full Python suite was not rerun.

Canonical handoff (local archive: `results/dashboard_layout_2026-10-15/HANDOFF.md`), browser checks (local archive: `results/dashboard_layout_2026-10-15/BROWSER_CHECKS.json`), verification (local archive: `results/dashboard_layout_2026-10-15/VERIFICATION.json`) and preservation (local archive: `results/dashboard_layout_2026-10-15/PRESERVATION.json`). Native right-side Dashboard refreshed at http://127.0.0.1:8090/; PID85246/session13271 remains the read-only sample preview. Temporary failure-fixture server/tab stopped, viewport restored and original tab retained. Owned only Dashboard template/portfolio CSS, current PRODUCT/DESIGN/surface/README/PLAN notes and isolated evidence; advisory ownership released. Header/Hot Markets, Settings/Research and other views, existing backend/server/fixtures, PRs, MVP, Polygon/sibling work and prior records remain untouched. Next: user review; real-account acceptance and deployment remain separate. No rolling banner, commit, publication, deployment, migration, new feed, provider or financial operation.

## Dashboard order and quote-banner preview — October 15, 2026, Asia/Shanghai

Rendered and browser verified; design preview only, before frontend implementation. Portfolio/open positions come first, followed by performance and recent research, with deployed/settled information retained below. **Top banner** and **Under navigation** compare horizontal Hot Markets quote placement. Labelled sample bid/ask cents, pause/resume, hover/focus pause, a stationary quote list, reduced-motion default and adjustable speed are included. Verification: **35 browser assertions passed**, zero runtime errors at 320/760/1024px; plot sizing/labels, syntax/fragment readback and **772 protected source hashes** pass. Canonical handoff (local archive: `results/dashboard_quotes_design_2026-10-15/HANDOFF.md`), verification (local archive: `results/dashboard_quotes_design_2026-10-15/VERIFICATION.json`), preservation (local archive: `results/dashboard_quotes_design_2026-10-15/PRESERVATION.json`). Owned only the thread's `dashboard-quotes-preview.html`, isolated evidence and this entry; advisory ownership released. Active frontend/backend/preview runtime, Settings/Research, other records/PRs, MVP, Polygon/sibling work and credentials remain untouched. Temporary inspection server/tab/files cleaned up; original Dashboard tab and viewport preserved. Next: user reviews placement/layout before application integration. No commit, publication, deployment, migration, provider or financial operation.

## Settings consolidation — October 15, 2026, Asia/Shanghai

Implemented in the local working tree and offline/browser verified; uncommitted and not deployed. One **Settings** main-navigation entry contains horizontal Account/Billing/System sections. Existing forms/API actions, full map, financial/auth guards and legacy URLs remain; operator users/waitlist/grants expand within System under the existing role/mode. Repeated headings, introductions, balance captions, instructional filler and a duplicate expansion indicator are removed. Kalshi setup collapses; auto-reload has two labelled fields. Read failures retain navigation and recover independently; stale responses and obsolete System polling cannot update another section.

Verification: **170 Python passed / 7 opt-in MySQL skipped; 29 Node passed; 84 browser and 19 HTTP checks passed** at 320/760/1280px. No browser runtime errors; syntax, scoped whitespace, links and served hashes pass. **764 protected sources unchanged**; backend AST is identical except the SPA route whitelist, and frontend API literal paths/counts are identical. Synthetic payment/account/operator writes are isolated fixtures; no providers or trading were contacted. Canonical handoff (local archive: `results/settings_integration_2026-10-15/HANDOFF.md`), browser checks (local archive: `results/settings_integration_2026-10-15/BROWSER_CHECKS.json`), HTTP checks (local archive: `results/settings_integration_2026-10-15/HTTP_CHECKS.json`), preservation (local archive: `results/settings_integration_2026-10-15/PRESERVATION.json`). Native preview is open on http://127.0.0.1:8090/settings/account, Python 3.12 PID85246/session13271, sample data with writes disabled. Temporary 8098 test server/tab cleaned up; viewport restored. Owned frontend, SPA route pattern/tests, current PRODUCT/DESIGN/surface/README/PLAN notes and isolated evidence; advisory ownership released. Other backend/provider/worker/trading sources, PRs, MVP, Polygon/sibling work and prior records remain untouched. Next: user review and configured non-production account/payment/MySQL acceptance. No commit, publication, deployment, migration or real financial/provider operation.

## Combined Admin design preview — October 15, 2026, Asia/Shanghai

Rendered and browser verified; design preview only, awaiting user review before application changes. One Admin navigation entry groups Account, Billing and System; recommended section rail and alternative section tabs preserve personal-account access, with operator tools restricted within System. The interactive draft uses sample data and local actions only. Verification: **72 browser assertions passed; 18 layout measurements** across 320/768/1024px and dark Account; JavaScript syntax/fragment format pass, final wrapped interactions have no new runtime errors, and **772 protected sources remain unchanged**. Earlier standalone/inspection diagnostics are retained with corrections. The user's Account tab remains unchanged; temporary inspection tab/server/wrappers are cleaned up. Canonical handoff (local archive: `results/admin_hub_design_2026-10-15/HANDOFF.md`), verification (local archive: `results/admin_hub_design_2026-10-15/VERIFICATION.json`), preservation (local archive: `results/admin_hub_design_2026-10-15/PRESERVATION.json`). Advisory ownership released. Owned only the thread's `admin-hub-preview.html`, isolated evidence and this narrow entry. Application/runtime/backend/API/auth/payment/trading contracts, Meridian/PR records, MVP, Polygon and sibling work remain untouched. Next: user selects the layout; implementation and authenticated acceptance remain pending. No commit, publication, deployment, migration, provider or financial operation.

## Meridian frontend PR publication — October 15, 2026, Asia/Shanghai

Published and attached: [GitHub PR #6](https://github.com/JihuiTanUchicago/kalshi_trade/pull/6), open/ready for review and clean/mergeable; not merged or deployed. Branch `codex/meridian-frontend-redesign`, commit `5a99fd0f9638863b664402935bc7e0a889c59832`, base `e40d060`. The exact 33-path tree combines the existing Research conversation/artifact workspace with compact Meridian/Catalyst presentation, local fonts, current contracts, focused tests and compact synthetic evidence. MVP/queue, Polygon/sibling work, prototype archives, credentials and unrelated records are excluded. Prior PR #5 remains closed/unmerged and unchanged.

Verification in the isolated publication checkout: **163 Python passed / 7 opt-in MySQL skips; 29 Node passed; 183 synthetic browser checks passed** at 360/760/1024/1280/1440px; syntax, whitespace, links and source/tree hashes pass. Application/font/test bytes match the shared frontend; only the copied license normalizes line endings/trailing spaces. GitHub lists no CI checks/statuses, so no CI success is inferred. Git HTTPS push failed in its HTTP2 framing layer; authenticated Git REST reproduced the exact local commit/tree before ref/PR creation.

All 85 protected shared sources remain unchanged. Shared main stays dirty at `e40d060` and its 8090 preview returns 200 without browser navigation or refresh. The isolated publication checkout is clean; only temporary preview 8097 was stopped. The old 8095 prototype probe returned 502 and its source/process/tabs were untouched. The PR explicitly discloses scoped chat backend implementation, authenticated non-production MySQL/account/provider acceptance and the earlier visual target (**latest 7/10; requested 9/10 unmet**) as remaining gates.

Canonical handoff (local archive: `results/meridian_frontend_pr_2026-10-15/HANDOFF.md`), publication (local archive: `results/meridian_frontend_pr_2026-10-15/PUBLICATION.json`), remote verification (local archive: `results/meridian_frontend_pr_2026-10-15/GITHUB_VERIFICATION.json`), preservation (local archive: `results/meridian_frontend_pr_2026-10-15/PRESERVATION.json`). Advisory publication ownership released. Next: human PR review; no merge, deployment, migration, paid/application provider or financial operation. Product/design/surface/API contracts are committed with the candidate; publication adds no contract/provider decision or unrelated roadmap update.

## Meridian design on local main — October 15, 2026, Asia/Shanghai

Integrated into the local main working tree and offline/browser verified; uncommitted and not deployed. The user's requested compact Meridian/Catalyst presentation now runs in the actual customer app. Overview uses actual recent sessions and existing paper account/trade data, with period-based cumulative closed P&L, daily values, isolated read errors and stale-response protection. Compact header/rows/panels/transcripts, local fonts, a header Hot Markets trigger, measured charts and unboxed evidence replace the prototype-only presentation. Existing Research artifacts/data/actions, Explore/Hot Markets, account features and financial/auth guards remain. Form height 481px→348px and workspace heading 55px→27px at 1440px; message line-height 20.15px→18.2px; 44px touch targets retained.

Verification: **163 Python passed / 7 opt-in MySQL skips; 29 Node passed; 183 browser checks passed** across 360/760/1024/1280/1440px. Six served asset hashes match. Seventy-four protected sources and three prototype runtime sources match; only static font serving/CSP changes affect the Python server. Original dirty work and source-before copies are retained. The final browser receipt covers all routes, drafts/tabs, controls/evidence, drawer fit/resizing/focus and Overview success/empty/error/race behavior. Initial nav/hidden-pane/plot-size/preservation-enumeration diagnostics remain with their corrections. No commit/push/PR mutation/deployment/migration/application provider or financial operation occurred; the user-requested design critics were invoked.

The earlier visual-quality gate remains open: main critics 24–29 scored 6.2, 6.5, 6.8, 7.0, 7.2 and 7.0/10. No ≥9 or full design acceptance is claimed. Every independent screenshot-only review uses the same prompt in a fresh GPT-6.1 Sol context. The latest user priority of compact local-main integration is implemented; further studio-quality refinement remains. Canonical handoff (local archive: `results/meridian_main_integration_2026-10-15/HANDOFF.md`), verification (local archive: `results/meridian_main_integration_2026-10-15/VERIFICATION.json`), critic history (local archive: `results/meridian_main_integration_2026-10-15/ITERATIONS.json`), preservation (local archive: `results/meridian_main_integration_2026-10-15/PRESERVATION.json`). Read-only sample preview PID70137/session28157 is refreshed on Overview at http://127.0.0.1:8090/; start via /preview. Existing user prototype tabs/8095 remain. Advisory integration ownership released. Next: continue visual refinement with the compact main source intact; scoped chat backend and authenticated non-production MySQL/provider acceptance remain independent pending gates.

## Local main pull and frontend compatibility — October 15, 2026, Asia/Shanghai

Historical pre-Meridian sync receipt; current presentation and preview ownership are above.

Completed and offline/browser verified; not deployed. Local main fast-forwarded 18 commits from 99a5399 to current upstream e40d060. Applied the already-compatible runtime/helpers/tests from frontend PR #5 while preserving the Research conversation/artifact layout and upstream Explore/Hot Markets, public System, research depth/run-forever/automatic market choice, pagination, credits and deployment warnings/guards. No additional application-code fix was needed; twelve runtime/test files match the PR. The local read-only preview now supports new deep links and Explore query/data shapes, with six research choices and honest sample conversations. User MVP, Polygon work, standalone original and independent prototype/records remain preserved; recovery backups and path-scoped stash aacb057c90f01ed049ce2e666b4e8b1adcd5256c are retained.

Verification on the updated main checkout: **157 Python passed / 7 opt-in MySQL skips; 29 Node passed; 16 browser and 19 HTTP checks passed**. Syntax, owned whitespace, exact served/PR asset hashes and documentation links pass. Browser checks cover new routes/data, controls, tabs/drafts, Position, delayed-load pane selection and 360/760px layouts. A mobile probe was occluded by the open Hot Markets drawer; DOM hit testing identified the cause and checks pass with it collapsed, without a runtime pane change. Main preview PID65067/session96989 is refreshed at http://127.0.0.1:8090/research/1?strategy=1 with both original artifacts open and #1 selected; current draft was retained. Temporary 8096 server/tab stopped; viewport restored. The native market drawer is collapsed so conversation remains visible. No unrelated source changes or original local work lost. Canonical handoff (local archive: `results/local_main_frontend_sync_2026-10-15/HANDOFF.md`), verification (local archive: `results/local_main_frontend_sync_2026-10-15/VERIFICATION.json`), preservation (local archive: `results/local_main_frontend_sync_2026-10-15/PRESERVATION.json`). Advisory ownership released. Next: user review; actual scoped chat backend and authenticated non-production MySQL/account/provider acceptance remain pending. PR #5 remains open and unchanged; no remote merge, new commit/push, deployment, migration, provider/model/payment or trading operation.

## Frontend GitHub PR publication — October 15, 2026, Asia/Shanghai

Historical publication receipt: the local checkout subsequently advanced in the main-sync workstream above.

Published and attached to this Codex task: [GitHub PR #5](https://github.com/JihuiTanUchicago/kalshi_trade/pull/5), open/ready for review and mergeable, not merged or deployed. Branch `codex/research-artifact-workspace`, commit `6eec9d5efd26f4f98b3285da3f8904b2e73e5b98`, based on current upstream `e40d060` (18 updates since the editing preview). Its 33 paths contain the final Research conversation/artifact workspace, Position deployment entrypoints, scoped chat contract, approved copy/control cleanup and final documentation/compact synthetic evidence. Explore/Hot Markets, iterative research/depth/automatic market choice, pagination, credits and upstream deployment policy/warnings are preserved. The obsolete frontend System admin redirect is corrected while authenticated routing/backend activity ownership stay intact. Description explains all final frontend changes and remaining backend boundaries.

Verification: **157 Python passed / 7 opt-in MySQL skips; 29 Node passed; 24 browser and 14 HTTP checks passed**, plus syntax/whitespace/documentation links and exact served/published tree hashes. GitHub reports CLEAN/MERGEABLE with no CI checks listed; no CI success is inferred. Synthetic providers/financial writes disabled; temporary 8096 server/tab stopped and viewport reset. Direct Git transfer failed; authenticated GitHub REST recovered exact upstream objects and published the verified tree, with connectivity/hash checks. Shared main remains at `99a5399`; 290 non-evidence sources, 8090 preview, user MVP/its existing PR, Polygon integration, standalone original and independent prototype/records are preserved. Rebased code lives in sibling `kalshi_trade-frontend-pr/kalshi_trade_infra`; do not reproduce its acceptance against old shared main. Advisory publication reservation released. Canonical handoff (local archive: `results/frontend_pr_2026-10-15/HANDOFF.md`), publication (local archive: `results/frontend_pr_2026-10-15/PUBLICATION.json`), verification (local archive: `results/frontend_pr_2026-10-15/VERIFICATION.json`). Next: PR review; scoped backend implementation and authenticated non-production MySQL/account/provider acceptance remain pending. No merge, deployment, migration, paid/model/provider or financial operation.

## Approved Research UI copy/control cuts — October 15, 2026, Asia/Shanghai

Implemented and offline/browser verified; not deployed. Applied user-approved C1–C11/B1–B2: single session status/count, compact message-group targets, accessible composer, preserved direction/IDs without repeated headings, concise Research intro, compact Position cards and one platform live notice. Removed duplicate navigation and demo invitations. Sample conversation is explicitly labelled; one current revision retains chronological proposal/backtest history. Distinct proposals/actions, complete strategy evidence, drafts/tabs, saved-rule/live guards and both deployment entrypoints remain.

Verification: **148 Python passed / 7 opt-in MySQL skips; 29 Node passed; 25 browser and 4 HTTP checks passed**. New grouped-target test preserves source IDs; browser covers every cut, revision decisions, all-status review, error/disconnection/draft behavior, Position controls, empty-state/specific live restrictions and 360/760px fit. Screenshots inspected; viewport restored; current served bytes and owned whitespace pass. **771 non-owned source files preserved; 22 non-chat fixture endpoints unchanged**. Real backend/business/records are untouched. Contract/PRODUCT unchanged because capabilities/endpoints did not change.

Main preview http://127.0.0.1:8090/research/1?strategy=1 (PID70248/session98434), existing native tab with two artifacts; sample data and writes disabled. Temporary 8094 server/tab stopped. Owned presentation/helpers/test, sample JSON and related design/readme/progress evidence; advisory ownership released. Concurrent Meridian work, mvp.md, standalone/merged Polygon, credentials and other evidence remain preserved. No commit, deployment, migration, paid/provider/model or financial operation. Next: user review; session-scoped backend and authenticated non-production MySQL/account acceptance remain pending. Canonical handoff (local archive: `results/research_ui_cleanup_2026-10-15/HANDOFF.md`), verification (local archive: `results/research_ui_cleanup_2026-10-15/VERIFICATION.json`), cleaned preview (local archive: `results/research_ui_cleanup_2026-10-15/EDITING_PREVIEW.png`).

## Meridian Catalyst palette and independent critic iterations — October 14, 2026, Asia/Shanghai

Historical prototype milestone, continued in the user-authorized local-main integration above. Catalyst's palette, local fonts, quote strip, research queue and supporting portfolio composition were explored in the isolated Meridian concept. Prototype source is retained at iteration 23, whose independent score was 7.6/10. All 24 unfiltered prototype scores (6.5–8.0), screenshots, source snapshots and the fixed screenshot-only critic prompt remain in `results/frontend_reimagination_2026-10-14/evidence/catalyst-refinement/`. The 9/10 criterion was never included in critic prompts or claimed satisfied. Latest completed prototype browser run was iteration 22, 269/269; iteration 23 was captured/reviewed but not fully browser-regressed. Earlier real 768px overflow and test-selector diagnostics remain preserved. T1–T7/C1–C4 cuts were applied in the concept under the improvement brief; other concept sources were unchanged. The old prototype-only ownership/read-only-main boundary is superseded by the latest explicit integration request; prototype presentation ownership is released. Current implementation/evidence now belongs to the main workstream.

## Research conversation and strategy artifacts — October 14–15, 2026, Asia/Shanghai

Implemented and offline/browser verified; not deployed. Completed the requested restoration first, then transformed each Research session into conversation/activity/all-status strategy links on the left and opened artifact tabs/full sheets on the right. Independent Strategies navigation is removed; legacy links/library filters, ancestor/standalone artifacts and every saved evidence/scenario/gate remain. Position exposes eligible strategies with the same paper/live deployment component; existing board, positions, chat/autopilot and other screens remain.

Verification: **148 Python passed / 7 opt-in MySQL skips; 28 Node passed (6 new artifact-state cases); 39 browser and 8 HTTP checks passed**. Actual GET handlers use synthetic repository data; optional fake sends/scenarios test target/result races. Coverage includes full sheets/statuses, tabs/keyboard/close/mobile, isolated drafts, history, revision review, scenario errors, poll recovery, cancellation, Position and payment gates. Corrected polling-deadline probes remain diagnostics. Screenshots inspected at desktop/mobile; 360/760/1024px fit; syntax/owned whitespace pass. **766 non-owned source files preserved**, with business server unchanged after reversing only asset hashing lines. Backend scoped chat routes remain unimplemented; real handlers preserve drafts and disable writes.

Main preview http://127.0.0.1:8090/research/1?strategy=1 (PID64648/session82593) retains two artifact tabs, synthetic data and disabled writes. Existing right split request reported queued. Temporary 8094 server/tab stopped; viewport reset. Owned frontend/state/tests, static versioning and relevant UI/progress records; advisory ownership handed off. Concurrent Meridian evidence/entries, mvp.md, workers/schema/credentials and Polygon feed work remain untouched. Next: connect scoped backend contract and configured non-production account/MySQL acceptance. No commit, push, migration, deployment, paid/model or financial operation. Canonical handoff (local archive: `results/research_artifact_workspace_2026-10-14/HANDOFF.md`), verification (local archive: `results/research_artifact_workspace_2026-10-14/VERIFICATION.json`), editing preview (local archive: `results/research_artifact_workspace_2026-10-14/EDITING_PREVIEW.png`).

## Meridian dark trading hub and cut review — October 14, 2026, Asia/Shanghai

Implemented and browser verified; cut list proposed, not applied. User preferred Meridian and requested a dark Bloomberg-inspired trading hub. The isolated concept now uses graphite/black panels, amber headings, cyan traces and monospaced figures, with BTC context/sample Kalshi bid/ask quotes, a responsive paper-portfolio plot and activity above the retained phase board. Website, six workspace screens and dialogs are dark. Existing copy/actions remain for review. Seven text groups (T1–T7) and four replicated control patterns (C1–C4) are identified from current DOM/handlers; card Open is explicitly a repeated span affordance, not a second button. Candidate/risk/mode/review controls remain meaningful.

Verification: **260/260 Chromium checks pass**, all original views fit 360/768/1024/1440px plus Meridian 440/620px; no script errors, failed resources or external interaction requests. Twelve Fieldwork/Aperture screenshots are pixel-identical. JS syntax and tracker whitespace pass; screenshots inspected. Initial table-selector diagnostic is retained; the portfolio plot now fills its measured panel width. Canonical handoff (local archive: `results/frontend_reimagination_2026-10-14/HANDOFF.md`), verification (local archive: `results/frontend_reimagination_2026-10-14/evidence/meridian-terminal/VERIFICATION.json`), cut list (local archive: `results/frontend_reimagination_2026-10-14/CUT_REVIEW.md`), review receipt (local archive: `results/frontend_reimagination_2026-10-14/evidence/meridian-terminal/REVIEW_EVIDENCE.json`). Preview: http://127.0.0.1:8095/?concept=meridian&view=workspace, existing PID58550/session73043; right-panel handoff queued.

Owned only the isolated prototype/layout/scoped stylesheet, review/evidence and narrow documentation entries. Actual customer-app Research conversation/artifacts, backend, financial/provider state, user MVP, Polygon/feed work and other workstreams are read-only. Sources-before captured; other tracker entries preserved. Advisory ownership handed off. Next: user reviews chosen cut IDs; production integration/physical-device/backend acceptance remain separate. All quotes/results are illustrative. No commit, push, deployment, migration, paid/model/provider or financial action.


## Separate Research and Strategies restoration — October 14, 2026, Asia/Shanghai

Implemented and offline/browser verified; not deployed. User requested the previous separate sections while reconsidering the design. Restored upstream `99a5399` Research form/run history/activity and Strategies filters/list/direct detail, retaining current billing/admin/System/Community, Account/Position labels, unrelated cleanup, route/scenario guards and financial gates. The merged session/conversation frontend is inactive and preserved in the source backup; its helper modules and unimplemented backend contract remain design references.

Verification: **148 Python passed / 7 opt-in MySQL skips, 22 Node passed (preserved inactive helpers), 23 browser and 8 actual-handler HTTP checks passed**. Browser/HTTP data is synthetic, providers and writes disabled; 360/760px layouts and screenshots inspected. No inactive session requests or financial/research/chat submissions. Corrected selector/shared-tab probe diagnostics are retained. **767 non-owned source files match baseline**, including backend, mvp.md and Polygon feed work. Main preview: http://127.0.0.1:8090/strategies/1, existing tab; temporary 8094 server/tab stopped and viewport reset. Native right split request reported queued.

Owned affected frontend/navigation/styles/entrypoint, focused asset test and relevant UI/progress records; advisory ownership handed off. Previous cleanup/reimagination evidence and unrelated changes are preserved. Next: user's revised design; configured authenticated MySQL/account/provider acceptance remains pending. No commit, push, deployment, migration, paid/model call or financial action. Canonical handoff (local archive: `results/separate_research_strategies_2026-10-14/HANDOFF.md`), verification (local archive: `results/separate_research_strategies_2026-10-14/VERIFICATION.json`), source backup (local archive: `results/separate_research_strategies_2026-10-14/source_before/`).

## Frontend reimagination concepts — October 14, 2026, Asia/Shanghai

Historical original exploration receipt; Meridian was subsequently selected and revised in the dark-hub workstream above. Three isolated concepts were implemented and offline/browser verified. User requested complete Tau frontend redesigns inspired by a shell-generated random alphanumeric string. The 768-character seed was analyzed and deleted; only abstracted patterns remain. **Fieldwork** (warm editorial research ledger; initial recommendation), **Aperture** (dark instruments/lime/horizontal navigation), and **Meridian** (cobalt architecture/workflow board) each include a website plus Dashboard, Strategy, Position, Community, Account and Billing. Candidate evidence/comparison, scripted sample conversation, local research, explicit simulated paper review/deployment, filters/search, portfolio periods, pause/resume and community interactions are functional in the browser. All figures and replies are illustrative; there are no real backend/provider/financial calls.

Verification: **255/255 Chromium checks pass**, all 21 screens fit 360/768/1024/1440px; desktop/mobile website/workspace/candidate screenshots inspected; no JavaScript errors, failed resources or external browser requests. JS/shell syntax and tracker whitespace pass. Duplicate mobile wordmark, report caption and control reflow are corrected; candidate identity/close controls remain visible during mobile scrolling; initial diagnostic receipts are retained. Bundled fonts/licenses and vector assets make the 306KB buildless source self-contained. Canonical handoff (local archive: `results/frontend_reimagination_2026-10-14/HANDOFF.md`), verification (local archive: `results/frontend_reimagination_2026-10-14/evidence/VERIFICATION.json`), browser checks (local archive: `results/frontend_reimagination_2026-10-14/evidence/BROWSER_CHECKS.json`), overview (local archive: `results/frontend_reimagination_2026-10-14/evidence/OVERVIEW.png`). Preview: **http://127.0.0.1:8095/?concept=fieldwork&view=workspace**, PID58550/session73043, right-panel browser handoff queued.

Owned only results/frontend_reimagination_2026-10-14/ and this additive entry. App/backend/session/MVP/Polygon and existing previews were read-only in this workstream. Reference comparison records the separate cleanup's concurrent app.js/DESIGN/app README changes without restoring or claiming them; other shared records are preserved. Advisory ownership handed off at the design boundary. Direction selection arrived: Meridian; current refinement/cut review is recorded above. Actual app integration, configured account/backend and physical-device acceptance remain separate work. No commit, push, migration, deployment, paid/model call or financial operation.


## Frontend copy and control cleanup — October 14, 2026, Asia/Shanghai

Implemented and offline/browser verified at 2026-10-14T21:59:15.067917+08:00; not deployed. User approved the review's cuts. Session cards are single native links; repeated status/count/instruction copy, unchanged revision rows and the hardcoded custody metric are removed. Landing and empty-dashboard actions are consolidated. A desktop comparison owns the matching proposal's decision controls; close/resize restore them, with visible focus restoration and mobile pane actions retained. Existing integration and financial gates remain unchanged.

Verification: **148 Python passed, 7 opt-in MySQL skips; 22 Node passed; 28 read-only synthetic browser checks passed**, including 360/760px layout and normal desktop. Normal viewport restored; current served app.js/app.css match disk. The early viewport-event sampling failure and rejected harness typo remain diagnostic evidence. Baseline snapshots preserve the previous local changes. 820 original non-owned files match; the existing compatibility workstream changed only its unowned synthetic contract-preview fixture concurrently and it was left intact. All protected app/backend/tests, user MVP and trading_agent_new source remain preserved.

Owned app.js/app.css, app README, customer-app DESIGN/surface guidance, this entry and results/frontend_cleanup_2026-10-14; other workstreams are preserved. Canonical handoff (local archive: `results/frontend_cleanup_2026-10-14/HANDOFF.md`), verification (local archive: `results/frontend_cleanup_2026-10-14/VERIFICATION.json`), browser checks (local archive: `results/frontend_cleanup_2026-10-14/BROWSER_CHECKS.json`). Preview: http://127.0.0.1:8090/strategies. Advisory reservation released; next user review. No commit, push, migration, paid/provider call, deployment or financial action.

## GitHub sync and frontend compatibility — October 14, 2026, Asia/Shanghai

Pulled, merged and offline frontend verified: main fast-forwarded from 20995e0 to **99a5399** (40 commits); a final fetch confirms HEAD matches origin/main. The first HTTP/2 fetch failed, HTTP/1.1 retry succeeded. All 74 prior local files were backed up before stashing; recoverable stash dd2b0c01f7dc09beecda1e9301f49b50d92e2191 remains. Five shared conflicts resolved while retaining approved Strategy/session chat, upstream billing/admin/System/Community features and user mvp annotations. Protected Polygon feed work, grouping/chat helpers and earlier evidence remain byte-identical. No feature commit; local edits remain unstaged.

Compatibility keeps Billing navigation, global payment dialog and needs_card checks in the unified session form, existing generation guards and both sign-out cache clears. **148 Python passed/7 MySQL skips, 22 Node passed, 13 actual-handler HTTP assertions and 19 browser checks passed** with synthetic repository data and disabled providers. Coverage includes new credit/card/role metadata, operator card gates, original/new screens, candidate/draft behavior, missing chat routes, card dialog and mobile layout. Syntax/compilation/pinned dependencies/pip check pass; PyArrow17.0.0 installed without starting collectors. The temporary 8094 server/tab is stopped; viewport reset. Original preview page is restored at http://127.0.0.1:8090/research/4 (PID52033, session44851), with current assets and refreshed synthetic metadata, writes disabled.

Latest backend still lacks session-scoped chat routes; actual-handler UI correctly remains Not connected, with drafts retained. Next: scoped backend implementation and configured non-production MySQL/model/Stripe acceptance. Existing incoming billing/agent/schema business files match HEAD; no database/migration, provider/model, payment, deployment or trading action. Separate approved copy/control-cleanup and reimagination workstreams were active during final verification; their presentation changes/records are preserved and are not claimed by this sync. Advisory sync ownership handed off. Canonical handoff (local archive: `results/github_frontend_sync_2026-10-14/HANDOFF.md`), verification (local archive: `results/github_frontend_sync_2026-10-14/VERIFICATION.json`), preservation (local archive: `results/github_frontend_sync_2026-10-14/PRESERVATION.json`).

## Session conversation UI and backend contract — October 14, 2026, Asia/Shanghai

Implemented and offline/browser verified; backend integration and deployment pending: user approved Side conversation and chose **UI + backend connection contract**. Sessions now contain a candidate-aware composer, independent history/drafts, polling/recovery and proposal backtest/comparison/review controls. The shared picker sits above evidence and chat; <=800px uses pane buttons. Missing routes show Not connected and retain drafts. Current backend session routes, persistence, scoped worker context and revision execution remain unimplemented; account-wide Position chat is separate.

Verification: **130 Python passed, 7 opt-in MySQL skips; 22 Node passed; 34 browser checks and 6 HTTP assertions passed** with synthetic loopback fixtures. Coverage includes captured/immutable targets, retries/new typing, independent read/write errors, invalid scope/data, pagination, revision gates/original retention, active research/cancellation/queue boundaries, reading position, existing scenarios/Position controls and 360/760/1024px fit. Screenshots inspected; viewport restored; temporary 8094 server/tab stopped. Canonical handoff (local archive: `results/session_chat_ui_2026-10-14/HANDOFF.md`), verification (local archive: `results/session_chat_ui_2026-10-14/VERIFICATION.json`), [backend contract](app/SESSION_CHAT_API.md).

Owned frontend/static asset versioning, focused tests and related product/design/readme/progress/evidence records; advisory ownership handed off. Repository/agent/schema, grouping helper and user mvp.md match baseline. Reversing only the two new asset-version changes reproduces the baseline server hash, confirming backend business code is preserved. Standalone Polygon, prior feed work, workers, credentials and financial state are untouched. Main preview is http://127.0.0.1:8090/research/1, PID32180/session45617; its actual assets are retained in the existing app tab and right-pane placement was requested (native tool reported queued). All preview writes remain disabled. Next: implement the scoped contract and verify authenticated non-production acceptance plus opt-in MySQL checks. No commit, migration, paid/provider call, deployment or real trading operation.


## Session conversation design — October 14, 2026, Asia/Shanghai

Historical design receipt: **Side conversation approved and implemented above**. The user explicitly scoped the next stage to UI plus backend contract; the previous design-feedback gate is satisfied.

Draft ready for user review, design only: the user requested a rough rendering of chat inside each Strategy agent session before implementation. Recommended Side conversation keeps the selected candidate's thesis/backtest beside a session-specific transcript; Tabbed conversation is the alternative and also the mobile pattern. Candidate/version labels remain attached to messages and proposals when the picker changes. Suggested revisions show parameter diffs and follow backtest → compare → review; saving a new candidate preserves the original. Researching queues a next trial at a safe boundary; deployed paper suggestions require the shown manual review before applying an update. Existing live-money/autopilot gates remain authoritative.

Current backend /api/chat and queued copilot work are user-wide, and adjustments target deployments. Session history/context, per-session queue/busy/proposal routing, undeployed candidate revision and research intervention still need implementation after design approval. The draft uses local synthetic conversations/results only; no app, schema, API, worker, provider or financial behavior was changed. App/backend and user mvp.md hashes match the workstream baseline; prior Strategy implementation and Polygon feed work are preserved.

Verification: 17 browser checks pass for context, local replies, revision test/compare/save/original retention, layout switching, dismissal, independent state, 1024px fit and 360px mobile conversation/evidence/chart reflow. JavaScript syntax and fragment checks pass; the viewport override was restored. Optional Researching/Deployed design-control variations are proposed but not browser exercised. The isolated draft is on http://127.0.0.1:8093, PID 28058, exec session 21449; the existing app remains on 8090. Scope: isolated visualization, this entry and results/session_chat_design_2026-10-14 records; advisory ownership is handed off at the design boundary. Canonical design handoff (local archive: `results/session_chat_design_2026-10-14/HANDOFF.md`), verification (local archive: `results/session_chat_design_2026-10-14/VERIFICATION.json`), browser checks (local archive: `results/session_chat_design_2026-10-14/BROWSER_CHECKS.json`). Next: user feedback on side versus tabbed conversation and revision review, then implement only the approved session behavior. No new implementation approval is implied; no commit, migration, paid model call or deployment.

## Strategy UI implementation — October 14, 2026, Asia/Shanghai

Implemented and offline/browser verified; not deployed: the user approved the Session cards draft on October 14. Strategy now merges research and candidates into phase cards, with partial-deployment counts and inspectable completed history. Each session contains candidate selection, thesis, saved backtest and evaluator-backed what-if controls. Research and candidate deployment reuse existing API validation/gates; Position and Account keep the existing Deploy/Funds routes. Completed-session candidate reads now filter by owner and run_id, and the new session-data.js uses existing content-hash versioning.

Verification: 12 session-grouping tests passed; Python regression 130 passed, 7 opt-in MySQL money-path skips (baseline here 124 passed, 7 skipped); 33 browser checks passed with synthetic HTTP fixtures, including filters/history, polling/drafts/cancellation, candidate gates, legacy links, scenarios/races/reset/navigation, $500 stake payload and retained other screens. Cards/review at 360px and collection at 760px fit without horizontal overflow; desktop screenshots were inspected. The viewport override was restored. Actual changed app assets are open in the right-hand preview at http://127.0.0.1:8090/strategies, PID 23410, exec session 6522. Sample actions remain disabled. The approved 8091 design draft remains available.

Owned scope: app/static, app/server.py and app/repository.py, focused tests, app README/product/design/surface contracts, this tracker and evidence. User-edited mvp.md matches its baseline hash; Polygon feed work, standalone package, workers, credentials, schema and financial state are preserved. Advisory ownership is handed off. Canonical implementation handoff (local archive: `results/strategy_ui_2026-10-14/HANDOFF.md`), verification (local archive: `results/strategy_ui_2026-10-14/VERIFICATION.json`) and browser checks (local archive: `results/strategy_ui_2026-10-14/BROWSER_CHECKS.json`). Remaining gate: authenticated end-to-end research, evaluator and paper deployment on a configured non-production backend, plus opt-in MySQL tests. The collection still uses the existing 50-run/200-strategy window. Next: backend acceptance when configured; full Position/Account redesign, pagination and rolling market feeds remain later work. No commit, push, migration, model/provider call or deployment.

## Strategy UI redesign proposal — October 13, 2026, Asia/Shanghai

Historical draft receipt below. **Approved October 14 and implemented above**; the previous feedback gate is satisfied. The isolated draft and its ten-check evidence remain available for comparison.

Draft ready for review, no app implementation or acceptance: the user added the UI section in mvp.md and requested a review plus a demo before changes. The proposal merges Research and Strategies into Strategy, organized around agent-session cards. A session already owns multiple candidates via run_id; backtests, thesis and scenario controls belong inside the session, with candidate-level deployment decisions. Position retains ongoing deployment/position operations. The proposed three headline states need remaining-review counts for partial deployment and inspectable history for no eligible strategy, failures and cancellations. Current backtest status does not record a separate user-review decision.

Two isolated interactive variants are available: Session cards (recommended) and Workflow board. The separate draft preview on http://127.0.0.1:8091 is PID 86338, exec session 94428; the existing 8090 app preview and user-selected Deploy tab remain intact. Ten browser checks pass, including candidate review, failing sample scenarios, local sample lifecycle changes, no-eligible history, new-session entry and the alternative layout. JavaScript syntax and fragment checks pass; desktop cards and detail view were visually checked with no horizontal overflow. All figures and scenario calculations are illustrative, and mobile has responsive CSS but was not device tested. User-edited mvp.md, actual app/static, Polygon feed work and backend/account/trading state are preserved; original app asset hashes still match. No backend API calls, migrations, paid calls, commits or deployment. Canonical draft source, state rules and remaining gates: [design handoff](../../frontend_preview/STRATEGY_UI_DESIGN_HANDOFF.md). Evidence: [verification](../../frontend_preview/STRATEGY_UI_DESIGN_VERIFICATION.json), [session screenshot](../../frontend_preview/STRATEGY_SESSIONS_DRAFT.png) and [review screenshot](../../frontend_preview/STRATEGY_REVIEW_DRAFT.png). Next at the draft milestone was feedback before implementation; approval arrived October 14. Current status is in the implementation entry above.

## Local frontend preview — October 13, 2026, Asia/Shanghai

Historical preview receipt below. The approved implementation now changes app assets; the current preview process and status are in the implementation handoff above.

App UI editing preview complete and browser verified: the user-requested screens after login are available at http://127.0.0.1:8090/preview, with Dashboard left open in the right-hand browser panel. The loopback-only preview process is now PID 82602, exec session 63751. Existing app.js/app.css assets are served unchanged, ready for requested edits and browser reloads. Dashboard, Research and session detail, Strategies and strategy detail, Deploy, Community and Funds all render with 15 local read-only synthetic API fixtures and a persistent sample-data notice. Specific layout/style changes await the user's direction.

Verification: 54 HTTP assertions pass, including filters, incremental reads, invalid cursors, unknown routes, disabled writes, exact asset bytes and returning to the landing page. All eight browser views pass; the dashboard screenshot was visually checked. `/preview` and `/preview/landing` switch local display mode using a preview cookie; Sign out clears only that cookie. This is not Google login or an app account/session. Other POST actions remain unavailable. MySQL/Google configuration and backend dependencies are still absent locally. The previous raw Google-route error recovery is retained in historical evidence.

App source, user-edited mvp.md, Polygon feed work, databases and provider/account state are preserved in this preview workstream. No workers, provider operations, account writes, schema migrations or deployment were started. Canonical handoff and reproducible commands: [HANDOFF.md](../../frontend_preview/HANDOFF.md); current evidence: [APP_PREVIEW_VERIFICATION.json](../../frontend_preview/APP_PREVIEW_VERIFICATION.json) and [dashboard screenshot](../../frontend_preview/DASHBOARD_PREVIEW.png). These files, serve.py and app_fixtures.json are adjacent ignored runtime artifacts. The original preview process has ended; current process ownership is in the implementation handoff. UI implementation followed user approval on October 14; functional backend/account flows remain a separate configuration gate.

## Local checkout sync — October 13, 2026, Asia/Shanghai

At 19:38 Asia/Shanghai, the user-requested fast-forward pull updated local main from 4151c5e to 20995e0 (eight upstream commits), including the latest Kursbuch app/landing/waitlist changes and mvp.md additions. All 18 pre-existing Polygon local edits/untracked files were backed up and retained without conflicts. Sync only: no app service, schema migration, model call, live-trading operation or deployment was run. The existing deployed-state notes below describe earlier upstream work, not actions taken during this pull. Recovery/progress receipt: Polygon sync record (local archive: `../trading_agent_new/results/github_sync_2026-10-13/PULL_RECEIPT.json`). Next: review the incoming app before further integration; runtime acceptance was not tested here.

## ARCHITECTURE PLAN — all-markets collector + cross-contract trading (proposed 2026-10-13)

**Goal:** collect *every* open Kalshi market at per-minute resolution, handle renewing
contracts correctly, let users find markets by a stable **name** (not a ticker), and let a
strategy trade **several order books at once**.

### STATUS (2026-10-14) — Phase 2 snapshot collector SHIPPED (`data_pipeline/snapshot_collector.py`)
Running on the collector box as `tau-snapshot.service` (per-minute, aligned to :00).
Key empirical findings that shaped the design:
- **The parlay flood:** raw `/markets?status=open` is ~99.9% ONE combinatorial series
  (`KXMVECROSSCATEGORY`, 386k+ markets, mostly zero-liquidity). A blind market scan caps out
  (400k+) and NEVER reaches the real markets. So enumeration must use `/series` (15,020 series)
  and `/events?with_nested_markets` (14,023 open events / 132,270 real markets / 4,574 series,
  zero parlay) — NOT a market scan. (This is also why the Phase-1 catalog only found ~11 series;
  `catalog_collector.py` still uses the flood scan and needs the same `/events` fix — TODO.)
- **Fixed membership for research integrity:** a dynamic "hot" filter makes a market appear only
  while hot → ragged, selection-biased panels. So we snapshot a FROZEN set of SERIES
  (`data_pipeline/snapshot_series.txt`, committed/auditable), built by
  `scripts/build_snapshot_series.py` = all *active* Crypto series + top-20 real series by open
  markets. Currently **98 series ≈ 41,467 markets/snapshot**. Expand `TOP_REAL` toward all markets.
- **Quotes vs enumeration:** `/events` nested markets carry NO quotes; quotes come from
  `/markets?series_ticker=X`. So: enumerate via `/events`, snapshot via per-series `/markets`.
- **Throughput:** unauthenticated `/markets` rate-limits ~5 rps (429s above). The collector box
  has NO Kalshi key, so auth (higher limit) isn't available there. Solution: prune empty series
  (0 data lost) + a global token-bucket (`SNAPSHOT_RPS=5`) across `SNAPSHOT_WORKERS=6` threads +
  per-series error isolation. Full 41k-market snapshot in **~34s (<60s)**, no 429.
- **Alignment:** one `snapshot_minute_utc` set once per scan, stamped on every row → all contracts
  share an aligned timestamp (cross-contract joins work); parallel fetch keeps the real window ~30s.
- **Storage:** S3 + Parquet (Snappy), `s3://kalshi-trade-datalake-.../snapshots_1m/dt=.../minute=.../part.parquet`.
### STATUS (2026-10-17) — Catalog-DRIVEN outcome-settled universe BUILT (not yet deployed)
The 19 curated markets need hand-tuned, non-derivable config (strike/spot/close-hour), so they
stay authored by hand. But OUTCOME-SETTLED binaries (underlying=None, book-only, settle YES/NO on
an event — the `nba_game` model) have uniform, derivable config, so they're now GENERATED from the
catalog:
- `app/markets.py`: `MARKETS` = catalog-generated set + the 19 `CURATED` layered on top (authoritative,
  never shadowed). `load_catalog_markets()` reads the enriched `kalshi_series` at import, best-effort
  (no DB / empty / un-enriched catalog → just the curated 19; never raises, never hits the network).
  `market_from_series()` is the pure, testable config-derivation. SQL lives in `app/catalog_repository.py`.
- Generation filter (all derivable from the catalog): recurring frequency (fifteen_min/hourly/daily/
  weekly/custom — excludes one_off/annual/sparse monthly+quarterly), allowed category (Sports, Weather,
  Economics, Commodities, Sci/Tech, Companies, Health, World, Transportation — EXCLUDES Crypto [curated,
  spot-ladder] and Financials [index strike-ladders needing a spot feed]), open_markets ≥ 2, non-MVE,
  non-curated, non-scalar. Bounded: ≤150 total, ≤40/category, liquidity-ordered (all env-tunable).
- `catalog_collector.refresh_series_meta()` enriches `kalshi_series` with Kalshi's own category+frequency
  via ONE bulk `/series` call; `kalshi_series` gained a `frequency` column (init_schema DDL + migration).
- Eager collection: `market_history.refresh` already loops `MARKETS`; each series is now contained in
  try/except so one failing series never stalls the backfill for the rest. The ~100-series one-time
  backfill is heavy but rate-limited (KALSHI_PAUSE); research fails closed until a market's data lands.
- Live path unchanged: generated markets ride the exact `nba_game` engine path; `deployable=True` only
  makes them ELIGIBLE — every per-deployment gate (gatekeeper, LIVE switch, key, typed confirm, NO-side,
  drawdown, autopilot) still runs, in order. TAO stays research-only. No gate weakened.
- Deploy sequence: deploy → `init_schema` → `catalog_collector` enriches → restart engine/market_history.

### STATUS (2026-10-14) — Phase 3 crypto backtest SHIPPED (research-only)
The backtester now runs on any strike-ladder crypto series, not just BTC:
- `Market` gained `underlying` (Coinbase product) + `deployable`. `MARKETS` now has BTC
  (deployable) + ETH/SOL/XRP 15m/daily (deployable=False). Research + backtest use all;
  the deploy engine (`engine.py`) ticks only `deployable`, and `create_deployment` blocks
  non-deployable — so research-only coins can be backtested but never trade.
- Price source generalized: `btc_candles_1m` -> `spot_candles_1m(symbol, start_ts, …)`;
  `market_history.sync_spot_candles(symbol)` collects per underlying (BTC/ETH/SOL/XRP spot
  backfilled ~87k 1m candles each); `load_history(..., underlying)` reads the right symbol.
  BTC history migrated into the new table by `app.schema`.
- Remaining before ETH/SOL/XRP backtests are rich: settled-contract history (`hist_markets`)
  + quote candles (`market_candles`) accrue via the `recursive-history` loop per series.
Next: Phase 4 (cross-contract) + the Hot-Markets sidebar + user-facing Explore tab.

### STATUS (2026-10-17) — tradeable universe WIDENED to 19 deployable markets (committed on branch, not yet deployed)
Curated static expansion of `app/markets.py` — 12 new `deployable=True` markets across 3 categories,
each verified against the live public Kalshi + Coinbase APIs (not inferred):
- **Crypto 15-min (strike + Coinbase spot):** sol15m, xrp15m, doge15m, near15m, zec15m, hype15m —
  series `KX<COIN>15M`, candle_minutes=1, history_days=30. Each has a live Coinbase USD product
  (fetch_spot_series) AND a currently-active 15M ladder (~96 settled markets/day, `floor_strike`
  populated, balanced YES/NO) so the collector + backtest + live paths all work unchanged.
- **Sports moneyline (outcome-settled, underlying=None, book-only — the NBA pattern):** nfl_game,
  nhl_game, ncaaf_game, mlb_game, epl_game.
- **Weather (outcome-settled, underlying=None, book-only):** high_ny (NYC daily high temp, candle_minutes=60).
Architecture choice = STATIC curation, NOT catalog-driven generation: `markets.py` has no DB access
(DB stays in the repository layer) and the catalog can't supply the fields that matter — the right
Coinbase `underlying`, candle granularity, close-hour, and strike-vs-outcome — so a generator would
produce FAKE config (e.g. KXDOGED *looks* like a directional crypto but its markets are strikeless and
the collector would silently drop every one). The catalog's role is discovery (used here to survey +
liquidity/structure-probe every candidate), not config. Excluded as bad-fit: all daily `*D` crypto
(KXDOGED strikeless; AVAX/LINK/LTC/DOT/XLM/BCH/NEAR daily ladders dormant), ADA/BCH 15M (dormant),
WNBA (scalar result the yes/no settle path can't resolve), monthly econ (too sparse to backtest).
No live gate touched; TAO stays research-only. **Before research works, `market_history` must backfill
each new series** (hist_markets + candlesticks; crypto also needs the coin's spot in `spot_candles_1m`).

### The core idea: Series (logical contract) vs Market (renewing instance)
Kalshi tickers renew: `KXBTC15M-26OCT1401...` is one 15-minute window; a new ticker opens every
15 minutes. The stable thing is the **series** (`KXBTC15M` = "BTC 15-min"). So:
- **series** = the logical "contract" a user searches/selects and a strategy targets.
- **market instance** = a concrete, settling ticker under a series (comes and goes).
- A strategy says "trade series X (and Y)"; the engine always trades the *currently-open*
  instance(s) of those series — rolling is automatic.

```
 Kalshi /series /events /markets
         │  discover + roll
         ▼
 ┌──────────────┐   per-minute, synchronized (one snapshot_minute_utc for all)
 │  series       │   ┌───────────────────────────┐
 │  catalog      │──▶│ snapshot every OPEN market │──▶ market_snapshots_1m
 │ (searchable)  │   │ (yes/no bid+ask, last, vol,│    (partition by day+series)
 └──────────────┘   │  open_interest)            │
         │           └───────────────────────────┘
         ▼
  Research: search by series name → pick 1..N series (cross-contract)
         ▼
  Backtest.Dataset(series=[...]) → multi-book spec → sim/live engines trade all books
```

### Data model (new)
- `kalshi_series(series_ticker PK, title, category, status, updated_at)` — the searchable catalog.
- `kalshi_markets(ticker PK, series_ticker, open_time, close_time, strike, status)` — instances.
- `market_snapshots_1m(snapshot_minute_utc, ticker, series_ticker, yes_bid, yes_ask, last,
  volume, open_interest, …)` — the per-minute time-series; **synchronized** (every open market
  shares the same `snapshot_minute_utc` each tick, so cross-sectional/cross-contract analysis works).

### Storage decision (needs your call)
Per the earlier math, per-minute × all markets is cheap on columnar/compressed storage and dear
on RDS rows (~1.7 KB/row): **$1000/mo ≈ 9.5k markets·yr on RDS vs ~40 TB on S3/Parquet.**
- **Option A (RDS-only, v1):** simplest, reuses the stack; fine for thousands of markets; migrate later.
- **Option B (S3 + Parquet, partitioned by day/series):** scales to the whole exchange for years;
  RDS keeps only the catalog + hot recent data. More plumbing up front.

### Build phases
1. **Catalog + roll:** ingest all series/markets metadata; detect settle→reopen. Search UX on Research.
2. **Snapshot collector:** per-minute synchronized snapshot of every open market → snapshots table/lake.
3. **Backtest over any series:** `Dataset` takes a series (not the hard-coded 2); Research runs it.
4. **Cross-contract:** spec gains a `series: [...]` list; backtester + sim/live engines trade N books.

### What changes in the app
- Research page: the 2-market radio → a **search box over series** (autocomplete, multi-select).
- `backtest.Dataset` / `spec`: single-market → list-of-series.
- Engines (`app/worker.py`, live engine): iterate the selected series' open instances.
- Strategy "market" field becomes a set; UI shows which books a strategy spans.


## Mandatory card gate + payment modal, wallets, notifications, UI polish (2026-10-13, deployed)

Stripe is now **LIVE in test mode** on the box (keys in Parameter Store, loaded via
`load_app_secrets.sh`). Everything below is deployed to `d1gfpzcosqrjya.cloudfront.net`.

### Card-on-file is now mandatory (the headline change)
A signed-in user with **no default card** cannot use the agent, regardless of their free credits.
- Server gate: `server._needs_card(ctx)` = `billing.configured() and no default_pm_id`.
  `server._require_billing_ready(ctx, gerund)` raises 402 from **both** `create_run` and `post_chat`
  (one shared helper — DRY). `me()` now returns `needs_card` + `free_bonus`.
- Client gate: `app.js paymentGate()` runs at the end of **every** `render()`. If `S.me.needs_card`,
  it opens a **global blocking `<dialog>`** (Esc/backdrop can't dismiss; only "Sign out instead"
  escapes). On a successful card save it refreshes `/api/me` and re-renders — the app unlocks.

### Payment modal — two-panel, Stripe Payment Element (card + Apple/Google Pay)
Reuses the `.wl-modal` dialog (same Catalyst-style look as the waitlist modal), widened to 940px:
```
 ┌─────────────────────────────┬───────────────────────────┐
 │  .pay-show (ink, animated)   │  .pay-right (Stripe form)  │
 │  ┌───────────────────────┐   │  Add a payment method     │
 │  │ faux app window        │   │  <subtitle: $100 free…>   │
 │  │  [auto-rotating SCENE] │   │  ┌─────────────────────┐  │
 │  │  strat→deploy→agent    │   │  │ Payment Element     │  │
 │  └───────────────────────┘   │  │ card·ApplePay·GPay  │  │
 │  caption + carousel dots     │  └─────────────────────┘  │
 │                              │  [ Save payment method ]  │
 │                              │  Sign out instead         │
 └─────────────────────────────┴───────────────────────────┘
```
- Left panel cycles the landing `SCENE.strat/deploy/agent` builders every 5.4s (`PAY_SHOW`,
  `closePay()` clears `payCarousel` + `sceneTimers`). Honors `prefers-reduced-motion`.
- Right panel: `create_setup_intent` now uses `automatic_payment_methods{enabled, allow_redirects:never}`
  so the **Payment Element** offers Apple Pay / Google Pay beside card with no return_url.
  `confirmSetup({elements, redirect:'if_required'})` → `/api/billing/card-added` sets it default.
- **Apple Pay caveat**: Payment Element shows card + Google Pay out of the box; **Apple Pay needs the
  CloudFront domain registered with Stripe + the `/.well-known/apple-developer-merchantid-domain-association`
  file hosted** — NOT yet done (follow-up).
- CSP widened: `script-src +pay.google.com`, `connect-src +https://*.stripe.com`,
  `frame-src +https://*.stripe.com +pay.google.com`.

### Charge bug fixed
`billing.charge()` PaymentIntent now sends `automatic_payment_methods{enabled,allow_redirects:never}` —
off-session top-ups/auto-reloads succeed without a return_url (was erroring in test).

### Per-user auto-reload amounts
`app_stripe_customers` gained `reload_amount` (min/default $20) + `reload_threshold` (min/default $5),
editable on Billing ("Reload $X when balance drops to $Y"). `billing.auto_reload` reads them and
clamps to the floors; `repo.set_auto_reload(on, amount, threshold)`.

### Reply email notifications
Commenting on a community post emails the author (`notify.comment_notice`, `repo.post_author`), with a
self-reply guard. Best-effort; SES sandbox only delivers to verified addresses until prod access lands.

### Accounts hygiene
- Waitlist and users are **mutually exclusive**: first sign-in deletes the matching `app_waitlist` row
  (`repo.upsert_google_user`), and `admin_overview` hides waitlist emails that already have accounts.
  Backfilled on the box; 2 stale rows removed.
- Identity is keyed on `google_sub`, so real Google logins can't duplicate. Two `stripetest@example.com`
  rows were my self-test pollution (random subs, shared fake email) — deleted on the box.

### UI polish
- "Your sessions" is now a **responsive card grid** (`.runs`→`.run-card`, color left-border by outcome)
  instead of 1-per-row; fixed the old one-word-per-line wrap (title was in a 90px grid column).
- Live **spinner** next to "Researching"/"Waiting" (`.working`) in the run view + sessions.
- Agent log **highlights verdicts** (PASSED green / VOID red badges); run feed **sorts unseen-P&L
  profitable-first** (rejected sink to the bottom).
- Strategies filter toolbar got breathing room under its rule (`.section-head.filters`).
- Deploy page: the Board/Agent-chat **segmented toggle** now shows ≤1080px so the chat composer is
  reachable without scrolling past the board.
- Research: funny placeholder ("Bro idk just give me a trading strategy frfr…"); replaced the four
  cryptic truncated example chips with one readable "Try the demo — Todd's random walk" chip.
- **Glossary info bubbles** (`GLOSSARY`, `glo(key)`, `setupGlossary`): a drawn "i" marker next to
  jargon (Passed / Void / Rejected / Unseen data / Gates) opens one shared top-layer definition
  popover (no clipping in tables), on hover, keyboard focus, and tap (Esc/outside-click dismiss).

### Access model decision (chosen, NOT yet built)
Google has **no public API** to add OAuth test users. Decision: **publish the OAuth consent screen**
(email/profile/openid need no Google verification → unlimited users), then gate access **in-app** via an
admin allowlist (Admin "Approve" moves an email off the waitlist and permits login). TODO: build the
allowlist + login check; until then access stays via Google test-users.

Tests: `tests/test_app_auth_and_api.py` gained a reply-notification test (email author, not self).
All app tests green.

## Billing / credits (Stripe), admin, community photos+edit (2026-10-14)

**Bedrock agent confirmed working**: a real research session ran on `us.anthropic.claude-sonnet-4-5`
via the instance role (AWS credits), producing Claude-written strategies and metering tokens.

**Credits/billing (`app/billing.py`, OpenRouter-style, LIVE Stripe)**. Credits are real USD, separate
from the paper balance; new users get `TAU_FREE_CREDITS` ($100). Agent usage (research+chat) is
metered per token at Anthropic list price (`billing.PRICES`) and deducted from credits after each run
(`agent._bill` -> `billing.charge_usage`). Top-up charges the card for credits + 5.5% fee
(`TAU_TOPUP_FEE`); auto-reload $20 at $5 off-session. Dependency-free Stripe client over HTTPS (no SDK
on py3.9); idempotent via PaymentIntent keys + unique `stripe_ref`; signed webhook at
`/api/stripe/webhook`. Research/chat are gated on balance>0 only once `billing.configured()`.
Role has `TauBedrockInvoke`, `TauSesSend` already; billing needs no AWS perms.

**Pending user action to ACTIVATE billing** (it's dormant until keys are set; deploy is safe):
put three values in Parameter Store (SecureString) then run `/opt/kalshi/load_app_secrets.sh`:
`/recursive/STRIPE_SECRET_KEY` (sk_live_), `/recursive/STRIPE_PUBLISHABLE_KEY` (pk_live_),
`/recursive/STRIPE_WEBHOOK_SECRET` (whsec_, from a webhook on
`https://d1gfpzcosqrjya.cloudfront.net/api/stripe/webhook` subscribed to `payment_intent.succeeded`).
CSP already allows js.stripe.com / api.stripe.com / frame-src js.stripe.com.

**Admin tab** (operator = `TAU_ADMIN_EMAIL`, default tjhprivate0416@gmail.com): grant credits to any
email, list users+balances and the waitlist. `/api/admin`, `/api/admin/grant`.

**Community**: attach a photo (stored in `app_images` MEDIUMBLOB, served `/api/community/image/<id>`,
<=3MB, png/jpeg/webp/gif), and edit your own posts (`edited_at` -> shows "edited"). Strategy filter
chips show counts (e.g. "Void (3)"). New tables: app_credit_ledger, app_stripe_customers, app_images;
app_posts gained image_id + edited_at. `MAX_BODY` raised to 8MB for base64 image posts.

**Email status**: SES verified for tjhprivate0416; operator waitlist emails send (check spam -- gmail
From deliverability is weak). SES production DENIED, so signup confirmations to arbitrary addresses
need a provider (Resend) -- still pending the user's call. notify defaults to tjhprivate0416@gmail.com.

Tests: 136 pass (added tests/test_app_billing.py for usage pricing, top-up fee, webhook signature).
## Email (SES) + Bedrock LLM (2026-10-13)

**Waitlist email** moved from SNS to **SES** (`app/notify.py`). SNS only reached a *confirmed*
operator subscription (it was stuck PendingConfirmation = zero emails) and can never email the
signup. SES now emails BOTH: a confirmation to the signer and a notification to the operator
(reply-to the applicant). From/To default to `tjhprivate016@gmail.com` (env `TAU_FROM_EMAIL` /
`TAU_OPERATOR_EMAIL`). Role has `TauSesSend` (ses:SendEmail). **Pending user action:** click the
SES verification email sent to tjhprivate016@gmail.com (operator mail works after that). SES is in
**sandbox** (Max24HourSend 200); production access was requested via `sesv2 put-account-details`
so signup confirmations to arbitrary addresses deliver once AWS approves (~24h). Until then only the
verified operator address receives mail.

**Agent LLM via Bedrock.** `app/llm.py` gained a Bedrock backend: `APP_LLM_PROVIDER=bedrock` (set in
`.env.app`) routes Claude calls through Amazon Bedrock via the instance role (AWS credits, no
Anthropic key). `APP_BEDROCK_MODEL` default `anthropic.claude-sonnet-5-5`. Role has `TauBedrockInvoke`
(bedrock:InvokeModel). End-to-end verified except **model access**: an on-box invoke returns
`AccessDeniedException` until Claude model access is enabled in the Bedrock console (us-east-1 >
Model access > Anthropic). After that, agents run on Bedrock; the `ANTHROPIC_API_KEY` path is no
longer needed. If the id needs the inference-profile form, switch `APP_BEDROCK_MODEL` to
`us.anthropic.claude-sonnet-5-5`.

## Tau rebrand + unified UI + Community + idea-first (2026-10-13, deployed)

The product is now **Tau** (user-facing rename; internal infra names — systemd services
`recursive-*`, SNS `recursive-waitlist`, env vars, the `X-Recursive` CSRF header — kept to avoid
re-provisioning). Deployed to the box and live at https://d1gfpzcosqrjya.cloudfront.net.

- **One clean design system** (white ground, Rubik, soft rounded cards, pill buttons, one warm
  accent `#F05A28`, green/red for money) for BOTH the landing and the authed app. Kursbuch is gone
  from the product app; the operator console keeps Kursbuch and was untouched.
- **Idea-first research.** No pre-set directions. The dispatch form is a free-text idea; a run is a
  "session" that spawns several strategies. `create_run` now requires an idea (>= 8 chars), direction
  optional; `agent._research_prompt` centers the idea. Strategies page dropped the direction chips.
- **Expanded landing**: hero with a replayable agent-discovers-strategies animation (`startDemo`),
  how-it-works, feature grid, FAQ, footer.
- **Community tab** (new): Twitter/Kalshi-style feed. Tables `app_posts` / `app_post_likes` /
  `app_post_comments`; endpoints `GET/POST /api/community`, `POST /api/community/{id}/like`,
  `GET/POST /api/community/{id}/comments`. Snapshots (strategy / deployment / pnl) are built
  server-side from the poster's OWN data in `_post_snapshot`. Rate-limited.
- **Demo on every account**: `repo.seed_demo_session` pre-populates a research session with the idea
  "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances" plus two
  coin-flip strategies and an agent log, so the end-to-end flow is visible on first login. Seeded for
  all existing users on deploy; runs for new users at account creation.
- **Owner Kalshi key connected.** The production key (`/opt/kalshi/.env` PROD_KEYID + prod_key.txt)
  was encrypted into app user 1 (tjhprivate0416@gmail.com) server-side via `app.kalshi_account`
  (never through chat). Verified against Kalshi (cash ~$56.58). **Live trading stays OFF**
  (`APP_LIVE_TRADING_ENABLED` unset); enabling real orders needs separate authorization AND the
  Kalshi geolocation attestation. Note: the house `kalshi-live-engine` shares that same key/account.
- Tests: 131 passing (create_run tests updated for idea-first).
- **DESIGN.md is stale again.** The documenter pass earlier described the Catalyst-landing +
  Kursbuch-app split; the design has since unified to Tau. Re-run the documenter once the look
  settles. The reverse-skill install request remains declined (offensive-security toolkit).

## UI revamp + waitlist (2026-10-13)

Owner rejected the "Tote Slip" look. Current UI:
- **Pre-login landing** copies catalyst.app's clean style: Rubik, white ground, pill
  buttons, a product-preview browser mock. Has **Join waitlist** -> `POST /api/waitlist`
  (unauthenticated, rate-limited), which records the email in `app_waitlist` and notifies
  the owner via SNS topic `recursive-waitlist` (ARN in `.env.app` as
  `RECURSIVE_WAITLIST_TOPIC_ARN`; subscription for tjhprivate016@gmail.com is **pending
  confirmation** until that address clicks the AWS confirm link). `app/notify.py` publishes
  via the instance role (policy `RecursiveWaitlistPublish`).
- **Authed app** reverted to the Kursbuch timetable world shared with the operator console
  (ink on stock, hairline rules, measured rows, tables not cards, one reserved signal red;
  money direction rides a pos/neg tint behind the figure). All five tabs reworked in
  `app/static/app.js` + `app.css`.
- **Known stale:** DESIGN.md / `.impeccable/design.json` still describe the Tote Slip world
  and don't cover the landing. Run the impeccable documenter when the look is settled.
- Deployed 2026-10-13 to the box (web/agents/engine restarted; schema migrated for
  `app_waitlist`). Reverse-engineering "reverse-skill" from GitHub was **declined** (offensive
  security toolkit, unrelated to this project).

## Recursive v0.1 - customer product (built 2026-10-12, not yet deployed)

`mvp.md` v0.1 is implemented as a new package `app/` (details and diagrams: `app/README.md`;
product truth: `PRODUCT.md`; design contract: `.impeccable/surfaces/app-static-index-html.md`).

Owner decisions this session: paper money by default, live only through the user's **own**
Kalshi API key (we never hold funds - CFTC); **both** markets (KXBTC15M and the KXBTCD 5pm
ladder); agents emit a **thesis + parameterized spec**, never code; new consumer visual world
"The Tote Slip"; product name **Recursive**; Google-only sign-in.

What exists:
- `app/markets.py` + `app/spec.py`: one feature snapshot and one rule, shared by backtest and
  engine. `app/backtest.py`: real Kalshi candles + results, taker fees, 70/30 time split, 5
  gates, what-if (fees/slippage/stake). `app/market_history.py`: resumable backfill of Kalshi
  settled markets/candles + Coinbase 1m candles (new tables `hist_markets`, `btc_candles_1m`;
  reuses `market_candles`).
- `app/agent.py`: 2-round research loop on in-sample only, OOS revealed only for frozen
  finalists, per-user memory; co-pilot chat/review with actions re-backtested; autopilot
  guardrails. `app/llm.py`: Claude over HTTPS with one JSON repair round.
- `app/engine.py`: per-slot decisions for every user, paper fills at the live book capped by
  size, live via `MarketableLimitKernel` with the user's key (gated by
  `APP_LIVE_TRADING_ENABLED`, off), settlement on Kalshi results, loss guard, daily reviews.
- `app/server.py` + `app/static/`: Google OIDC/PKCE, hashed sessions, CSRF header, rate
  limits, JSON API, SPA (Dashboard, Research hub + live run "printer", Strategies, Strategy
  homework + what-if, Deploy board + agent chat + autopilot, Funds: paper ledger + Kalshi key).
- `data_pipeline/common.py` / `live_trading_engine.place_limit_order` gained an optional
  `credentials` argument (default = house key, so existing callers are unchanged).
- Tests: 53 new (`tests/test_app_*.py`); the money path runs against real MySQL with
  `APP_TEST_MYSQL=1`. Full suite: 130 passed. Found and fixed on the way: `10 // 0.4 == 24.0`
  under-sized every order by one contract.

**Business finding - read before launch.** On ~13 days (15m) and ~24 days (daily) of real
history, a grid of ~400 specs per market found **zero** that pass the fee-inclusive
out-of-sample gates; the GBM fair value is slightly *worse* calibrated than the Kalshi mid
(log loss 0.403 vs 0.384 at 3-8 min). The gate is doing its job, but a product where agents
rarely find a passing slip will not feel lovable. Highest-leverage next steps:
1. Maker (resting) orders: Kalshi's maker fee is 1/4 of taker; most rejected specs die on fees.
2. Richer building blocks: order-book imbalance and trade flow (already in `model_features_1m`
   for 15m), BRTI-vs-Coinbase basis, cross-strike ladder shape for the daily market.
3. Longer history via Kalshi's `/historical` endpoints (live API covers settled markets back
   to 2026-08-12 only).

**Deployed 2026-10-13 05:05 UTC** (box `i-077d6f7873e7836ba`; no house service restarted).
- URL: **https://d1gfpzcosqrjya.cloudfront.net** - its own CloudFront distribution `EEQ00Y93RTB1K`
  (CachingDisabled + AllViewer: cookies, POST, query strings forwarded; HTTP->HTTPS). The operator
  dashboard distribution `E3W0CV5JMD953I` was not touched.
- Origin port 8090 is reachable only from CloudFront, via a separate security group
  `sg-0eb5783d005711504` (`recursive-web-sg`). A second prefix-list rule cannot go into the old
  group: each CloudFront prefix-list rule counts ~55 against the 60-rule limit.
- `recursive-{web,agents,engine,history}` run under systemd with `MemoryMax` (400/400/250/250M) and
  `Nice=5`. The box has 1.8GB and the house live engine alone uses ~690MB, so a 1GB `/swapfile` was
  added and agents run 2 threads. If memory gets tight, it is the app that gets killed, not the house.
- `/opt/kalshi/.env.app` (root, 600): `APP_SECRET_KEY` generated on the box (never left it),
  `APP_HOST=0.0.0.0`, `APP_PORT=8090`, `APP_AGENT_CONCURRENCY=2`, `APP_GOOGLE_REDIRECT_URI`.
- Secrets hand-off: the owner puts SecureString parameters `/recursive/GOOGLE_CLIENT_ID`,
  `/recursive/GOOGLE_CLIENT_SECRET` and `/recursive/ANTHROPIC_API_KEY` in Parameter Store; then
  `/opt/kalshi/load_app_secrets.sh` (repo: `scripts/load_app_secrets.sh`) writes them into
  `.env.app` and restarts web + agents. The role `kalshi-collector-ec2-role` has inline policy
  `RecursiveReadAppSecrets` (`ssm:GetParameter` on `parameter/recursive/*` only).
- Backups of the two overwritten pipeline files are in `/opt/kalshi/bak.20261013_050545/`. Both
  matched the repo byte for byte before the change.
- Still open: * Google OAuth client and Anthropic key (above). `APP_LIVE_TRADING_ENABLED` stays unset
  until separately authorised. HEAD requests return 501 (no sign-in flow uses HEAD).

Deferred (v0.2 or later): charging, mark-to-market of open paper positions (shown at cost
today), partial-fill handling on live exits, email notifications.

NO-side live/demo orders: implemented (pending owner review; live still off by default). Because
the `events/orders` endpoint only speaks the YES leg (`bid`=buy YES, `ask`=sell YES), a NO order is
sent as its YES complement via `execution_kernel.order_wire_params`: buy NO = sell-YES `ask` at
`1 - no_price`, sell NO = buy-YES `bid` at `1 - no_price`. The kernel prices from the NO side of the
book (no_ask = 1−yes_bid, no_bid = 1−yes_ask) and flips the reported YES fill back to the NO cost
basis (`1 - yes_fill`). `engine._live_trade` threads the real `entry.side`/`pos["side"]`, positions
insert the real side, and settlement/mark-to-market were already side-generic. The YES-only guards in
`agent.deploy_live` and `server.create_deployment` are relaxed; every other live gate is unchanged.

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

## Push alerts for live trading (added 2026-09-26)

`data_pipeline/live_alerter.py` runs on the box under a **systemd timer**
(`kalshi-alerter.timer`, every 5 minutes) and publishes to SNS topic
`arn:aws:sns:us-east-1:568386354218:kalshi-live-alerts`. Alerts on: a strategy halting itself, a
position opening (loudly if it cost more than $20), each closed trade, a switch flipping, the day's
realised loss passing a floor, cash under $70, the balance falling back to an estimate, and any
writer going stale. Two rules keep it usable: it fires **only on change** (state in
`/opt/kalshi/.alerter_state.json`), and it sends **one heartbeat a day** so silence can be
distinguished from a dead alerter - the exact failure mode this system has already suffered twice.

Permissions are deliberately narrow: a `KalshiLiveAlertsPublish` policy granting `sns:Publish` on
that one topic, attached to `kalshi-collector-ec2-role`. The alerter never writes to a trading
table and never places an order.

Two traps found deploying it. **`crontab` does not exist on this AMI** - use a systemd timer, which
is the better fit anyway. And **`/opt/kalshi/.env.aws` sets `AWS_PROFILE`**, which is right for a
laptop and fatal on the box: boto3 then looks for a credentials file that is not there instead of
falling through to the instance role. `run_alerter.sh` unsets it after sourcing.

## Read-only monitor token (added 2026-09-26)

`MONITOR_TOKEN` in `/opt/kalshi/.env.dashboard` unlocks `GET /health`, `/live_metrics` and
`/sim_metrics` and nothing else - verified refused for pages, `/table`, and every POST including the
live switch. It exists so anything off-box that must store a credential stores the least valuable
one available, rather than `DASHBOARD_PASSWORD`.

**Cloud routines cannot monitor this system.** A scheduled Claude cloud session was built, run, and
disabled: its sandbox egress proxy refuses connections to the CloudFront host
(`connect_rejected ... organization policy`), and `user_declared_urls` is dropped by the server.
The routine is kept disabled at `trig_01RdZe7mQyrWJaXnx9JFUmZV` in case that policy ever changes.

## Kalshi retired the order endpoint (fixed 2026-09-27)

Live trading could not place a single order, and every attempt crashed the engine.
`POST /trade-api/v2/portfolio/orders` now returns **410 `deprecated_v1_order_endpoint`**. The
exception propagated out of the per-strategy loop, so the whole tick aborted and the engine
restarted - which is why `binary_theory_edge`'s own log lines for 05:24 and 05:25 are missing while
its neighbours' are present.

New endpoint is `POST /trade-api/v2/portfolio/events/orders`, and the schema is genuinely
different: no `action` or `type` field, `side` is `bid`/`ask` on the YES leg (bid = buy YES, ask =
sell a YES position), and `count`/`price` are fixed-point **strings in dollars**, not integer cents.
Verified without creating an order by probing with a deliberately invalid body: the new path
answers `400 missing_parameters: CreateOrderV2Request.SelfTradePreventionType` (so it exists and
parses), the old path answers 410. Both `api.elections.kalshi.com` and `external-api.kalshi.com`
behave identically, so no host change was needed. Same 1c-99c bounds and whole-cent rounding as
before: this changed the transport, not the prices sent.

`time_in_force` is **immediate_or_cancel**, deliberately. The engine records a position straight
after the call and never reconciles fills, so a resting order would leave it believing it holds
something it does not - which already happened once, and `live_orders` still carries a March order
stuck at `resting`. IOC either crosses now, matching what the simulator assumes, or nothing happens.
**Open gap:** a partial fill is still recorded as a full fill. Reconciliation against Kalshi's
positions endpoint is not implemented.

**Second blocker, owner action only:** a well-formed order then returns
`403 "Your location attestation for API trading is missing or expired."` Kalshi requires a
geolocation attestation for API trading. No code can fix it - verify location in the Kalshi app.

## UI: actions that silently did nothing (fixed 2026-09-27)

`arm()` compared `ARMED.btn === btn`, a **DOM node identity** check, while the strategies table
re-renders every 10s and replaces that node. The confirming click therefore landed on a fresh
button and silently re-armed. Arming is now keyed by a stable `data-arm-key` string.

A second fix here - holding the render entirely while the operator was armed, had a config panel
open, or had focus inside the table - **was wrong and has since been reverted.** See the next
section: it is what made a strategy that had just been switched on keep reading "Off".

Save confirmations now render in `#strat_notice` inside the Strategies section. They previously
appeared at the top of `live-root`, which on a tall page meant a successful save looked exactly
like nothing happening.

The alerter now tails the engine log for error lines, reporting each once. It would not have caught
this failure otherwise: a crash-loop restarts too fast to look stale and writes no trade.

## "I turned it on, then it was off again" (fixed 2026-09-27)

Reported as: click **Turn on**, the banner says the strategy is live, refresh, and it reads `OFF`
again. The same shape for **Save caps**. Nothing was actually wrong with the write - the database
had `binary_theory_edge` at `live_enabled: true`, stamped `06:36:55 UTC`, the second the button was
clicked, with the operator's caps intact. **The strategy was live the whole time; only the screen
was lying.** Two independent staleness bugs, both on the read side, stacked:

**1. The read cache outlived the write.** `/live_metrics` and `/sim_metrics` go through `_cached`
with a 25-second TTL and nothing ever invalidated it. A POST committed, returned the fresh settings
(which is why the banner was correct), and then `refreshLiveMetrics()` - fired by the button itself
a millisecond later - was served the pre-write payload. Every read for the next 25 seconds, page
reloads included, showed the old state. Fixed by clearing the whole cache after **every** POST,
from a `finally:` on `do_POST` rather than per route, so no future route can forget it:

    def do_POST(self):
        try:
            self._handle_post()
        finally:
            invalidate_metrics_cache()

Clearing all keys rather than tracking which ones a write dirtied is deliberate: the cost is one
recomputed query on the next read, and the bookkeeping version is what rots.

**2. The render guard added the same day (above) refused to redraw the table.** It held the render
whenever a config panel was open - and the reporting screenshot shows exactly that: the
`binary_theory_edge` caps drawer open, the "NOW LIVE" banner up, and the row still reading `OFF`.
Even with fresh data arriving, the row could not repaint. Saving caps left the drawer open too, so
a successful save also never showed.

The guard was solving something real (a re-render under the cursor swallowing the click), but
"never repaint" is too blunt. The table now always renders and afterwards restores the three things
a redraw would otherwise destroy: open drawers, the focused field, and a half-confirmed armed
button. `CFG_EDITED` already carried in-progress values across a repaint.

Covered by `tests/test_dashboard_cache.py`, including a wiring test that fails if `do_POST` ever
stops routing through the `finally:`.

**Still open, noted here rather than changed silently:** `LIVE_TRADING_PASSWORD` falls back to a
hardcoded default in `dashboard_server.py` when the environment variable is unset - and it is unset
on the box, so the committed default is the live gate in production.

## Position reconciliation (added 2026-09-27)

`position_mismatches()` in the alerter, which already runs every 5 minutes with a DB cursor,
Kalshi auth, SNS and a state file - so no new service. It compares `live_positions` against
`GET /portfolio/positions` and reports:

- a **short** position (loud): we only ever buy YES, so a negative position cannot be intended.
  This is the exact signature of the 2026-09-27 phantom-order damage, which ran for hours because
  nothing ever asked Kalshi what we held.
- a holding Kalshi has and our book does not, or vice versa
- a size mismatch

Settlement clears Kalshi's position a beat before the engine books it, so a mismatch is only
reported if it is **still there on the next run** five minutes later.

Deliberately compares holdings, not money: a balance check needs deposits and withdrawals tracked,
which they are not, and would be wrong the first time either happened.

## The engine believed its own orders (fixed 2026-09-27) - INCIDENT

Reported as "the P&L doesn't add up": dashboard said **+$2.20 realised, 66.7% win** while cash had
gone **$90.26 -> $74.25**. The dashboard was summing the engine's *intentions*.

**Root cause.** `DummyExecutionKernel.execute` read `resp["order"]["status"]`. The Kalshi **v2**
create-order response has no nested `order` object - it is flat:

    filled   {"fill_count": "18.00", "average_fill_price": "0.7400", "average_fee_paid": "0.0134", ...}
    unfilled {"fill_count": "0.00",  "order_id": "...", "remaining_count": "0.00"}     <- no price at all

So since the v2 migration the kernel saw `{}` for every order, defaulted `status` to `"submitted"`,
set `accepted=True`, and reported `fill_price_dollars=intent.limit_price_dollars` and
`fill_qty_contracts=intent.qty_contracts` - the request echoed back as though it were a fill.
`open_live_position` then recorded the position under the comment *"Conservative assumption for
MVP: treat accepted order as filled at limit price"*, and never checked `rep.accepted` anyway.

**Why it cost money rather than just misreporting.** Orders are immediate-or-cancel. Four of six
buys on 2026-09-27 crossed nothing and were canceled. The engine recorded them as positions. A
minute later it "closed" each one - and **a sell against a position you do not hold is not a no-op
on Kalshi, it opens a short.** Three phantom closes bought 64 NO contracts on
`KXBTC15M-26SEP270315-15` for $17.76 + $1.44 fees. That market settled YES. All 64 expired worthless.

| market | dashboard said | actually |
|---|---|---|
| `...0300-00` | -$11.34 | **+$2.23** (18 YES @0.74 settled YES) |
| `...0315-15` | +$15.36 | **-$19.41** (64 worthless NO) |

Wrong in both directions: the one genuine trade *made* $2.23 and was booked as an $11.34 loss,
because the exit price was taken from the quote rather than the fill too.

**Fix.** Three layers, each independently sufficient for the four phantom trades:
- `DummyExecutionKernel` parses `fill_count` / `average_fill_price` / `average_fee_paid` from the
  flat v2 response. `accepted = fill_count > 0`. Status is `unfilled` / `partially_filled` / `filled`.
  A fill with an unreadable price falls back to the **limit**, never to something flattering.
- `open_live_position` records nothing when `fill_qty_contracts == 0`, records the partial when
  partial, and stores the real entry price and fee. The order is still written to `live_orders`
  for the audit trail.
- `close_live_position` returns without deleting the position when the exit does not fill, carries
  the remainder forward on a partial exit, and subtracts entry+exit fees from P&L. It already
  returned early when no position row existed, so fill-based recording alone closes the naked-sell
  hole: a position that was never recorded can never be sold.

Covered by `tests/test_execution_fills.py` (verbatim captured Kalshi payloads, including the v1
shape that must **not** read as a fill) and `tests/test_live_fill_recording.py`.

**Timeline.** Fix deployed and engine restarted 07:35:11 UTC. One last naked sell fired at
07:34:15, ~55s earlier, leaving a real **-21 contract short** on `KXBTC15M-26SEP270345-45`
($4.20 exposure) that settled on its own. `live_positions` and the phantom `open` rows were
voided against Kalshi's own position list (status `void`, not deleted - the attempts stay auditable).

**Still open.** `live_trades` ids 5-9 remain historically wrong (recorded from intentions), so the
dashboard reads **+$8.50 over 7 closed trades** against a real balance of ~$69.82 from ~$90. A
one-time back-correction against Kalshi fills/settlements was scoped out and is the obvious next
step. Nothing reconciles `live_trades` against Kalshi periodically, so a fill that happens outside
the engine's own call path is still invisible to it.

## Positions that expire were never booked (fixed 2026-09-27)

The engine only ever closed a position by **selling** it. When the exit order could not fill -
no bid, which is routine in the last minutes of a 15-minute contract - the market expired
underneath the position, the row stayed `open` forever, and the loss was never booked. The
dashboard went on showing it as a live holding at a stale mark.

It happened to 27 contracts of `KXBTC15M-26SEP271315-15`: six consecutive sell orders cancelled
(17:09-17:14), market settled `no`, $8.64 gone and invisible. `reconcile_settled_positions()` now
runs at the top of every tick, before any exit is attempted, and books settled markets directly
from `/portfolio/settlements` at $1.00 or $0.00. First tick after deploy:

    live random_forest_high_conviction KXBTC15M-26SEP271315-15 SETTLED no:
      27 contracts entered at 0.3200 -> 0.00, pnl -9.46

Status stays `'closed'`, deliberately: every P&L query **and the daily-loss / drawdown caps in
`current_risk_state`** filter on `status='closed'`. A separate `'settled'` status would have hidden
settlement losses from the risk caps - the same class of bug as the one being fixed. An exit price
of exactly 1.00 or 0.00 is what marks a trade as settled rather than sold.

## Why paper and live disagreed (2026-09-27)

The simulator is not modelling execution, it is modelling **quotes**. Measured, not assumed:

| finding | evidence |
|---|---|
| Paper P&L was **gross of fees** | `pnl = (exit - entry) * qty`, no fee term. rf_high_conviction: +$469.03 gross, **$154.36 of fees**, net **+$314.67** - a third of the headline |
| `FORCE_CLOSE_NEAR_EXPIRY_PRICE = 0.99` | An empty bid ladder near expiry was marked as a **near-certain win**, in exactly the illiquid case where live gets nothing |
| Exits assume the quoted bid is always hittable, in full | Live, 6/6 exit orders on `...271315-15` were cancelled |
| The sim never holds to settlement | Live does, whenever the sell does not fill |
| Sim sizes ~10 contracts, live sized 25-33 | Live ran ~3x the position the sim validated |

Head-to-head on the same markets that day: sim averaged **+8.7c per contract** per round trip over
its last 200 `rf_high_conviction` trades; live paid **-8c**. On `...271315-15` the sim booked +$0.30
and live lost $9.46.

Two hypotheses were **disproved** by measuring, and are recorded so they are not re-litigated:
the 0.99 force-close is *not* a major P&L driver for `rf_high_conviction` (0 trades of 462 hit it;
10 of 396 for `binary_theory_edge`, worth $35.10), and fees alone do not flip either strategy
negative in the sim.

**Applied:** fees on both legs now subtracted in `close_existing_position`; `FORCE_CLOSE_NEAR_EXPIRY_PRICE`
is `0.0` (no bid means no exit - a forward-running sim cannot know the settlement outcome, so the
mark must not assume a win); all 25,442 closed sim trades rebased from gross to net.

**Not done, and it is the real gap:** the simulator still has no fill model. It assumes every order
fills at the quoted price, in full, instantly, on both legs. Until it models partial fills, unfilled
IOC orders and holding to settlement, paper P&L remains an upper bound rather than a forecast.

## Live P&L rebuilt against Kalshi (2026-09-27)

`live_trades` ids 6-9 were voided (Kalshi: canceled, zero fill - they are not trades). Id 5 was
corrected to its real fill, 18 @ **0.74** (recorded 0.82), settled YES at 1.00, pnl **+$4.08**.

Dashboard now reads **-$11.37 over 10 real trades**: random_forest -$1.82, binary_theory_edge
+$3.06, random_forest_high_conviction -$12.61.

Cash went $90.26 -> ~$56.58. The difference between that ~-$33.68 and the -$11.37 of real strategy
P&L is one-off damage from the phantom-order bug - unintended short positions that belong to no
strategy - and is not recoverable into any `live_trades` row. **Nothing reconciles `live_trades`
against Kalshi on a schedule**, so this gap can reopen silently.

All three strategies set `live_enabled=false` on 2026-09-27 pending a fill model in the simulator.

## Execution rebuilt to price from the live book (2026-09-27)

**The defect.** Every order was built from `model_features_1m` `rows[-1]` - a completed one-minute
bar, up to ~75s stale by the time the order landed at :15s. Measured live: the bar read
**0.58 / 0.59** while Kalshi's book was **0.70 / 0.71**. It failed in both directions, which is why
the symptoms looked contradictory:

- **buying** at the stale ask, under the real ask -> never crosses -> cancelled (the unfilled entries)
- **selling** at the stale bid, under the real bid -> crosses instantly and gives away the difference

Top-of-book depth is **2,000-3,000 contracts** against orders of 25-33, so liquidity was never the
constraint. Stale pricing was the whole problem.

**Kalshi has no market order.** `type: "market"` on `/portfolio/events/orders` is rejected with
`invalid price: can't convert '' to decimal` - a price is always mandatory. Crossing the book
therefore means a *marketable limit*, which makes the quote the order is built from the single most
important input.

**What was built.**

`data_pipeline/market_data.py` - `MarketFeed` / `Quote`. Top of book with an explicit age.
Websocket-first with REST as both fallback and freshness backstop, because a socket that silently
stops updating looks exactly like a calm market. Returning `None` is a valid answer: no quote means
no order. In production `ws_feed=None`, so every quote is a REST read - at a one-minute decision
cadence that is 1-4 calls/min and *always* correct, where a second in-process socket would add a
stale-socket failure mode for latency that does not yet matter. The `ws_feed` hook exists for when
tick-level triggering makes it matter.

`MarketableLimitKernel` in `architecture/execution_kernel.py`, replacing the passthrough on the
live path. Three things the old kernel did not do:
1. re-prices from the live book at submit time;
2. **re-checks the edge at the price actually available** - if the live ask has run more than
   `MAX_ENTRY_SLIPPAGE` (default 2c) past the price the signal was computed at, the entry is
   abandoned, not paid up for. Following the book must not become chasing it;
3. **escalates one tick per retry on an exit.** Deliberately asymmetric: a missed entry costs
   nothing, a missed exit is how 27 contracts were carried into settlement for -$9.46. Bounded by
   `ORDER_MAX_ATTEMPTS` so it cannot walk the book down indefinitely.

Knobs (env): `KALSHI_ENTRY_CROSS_TICKS=1`, `KALSHI_EXIT_CROSS_TICKS=2`,
`KALSHI_MAX_ENTRY_SLIPPAGE=0.02`, `KALSHI_ORDER_MAX_ATTEMPTS=3`, `KALSHI_MAX_QUOTE_AGE_SECONDS=2.0`.

The engine's split is now explicit: **features from the bar** (what the model was trained on),
**prices, edge and sizing from the book** (what you can actually trade at). The bar's bid/ask no
longer reach any decision.

**Tick-level capture.** `forward_collector` subscribed to the `ticker` channel and sampled it on
20-second marks, discarding everything between - 180 distinct timestamps an hour, and 0 of 880,745
rows ever carried depth. New table `forward_quote_ticks` now records every top-of-book change:
**20 rows in 2 minutes where the sampler gave 6**, catching real intra-minute moves
(0.61 -> 0.60 -> 0.59 -> 0.58 inside 20 seconds). This is the prerequisite for a simulator fill
model and the history cannot be reconstructed after the fact, which is why it went first.

**Still open.**
- The simulator still has no fill model: it assumes every order fills at the quoted price, in full,
  instantly, on both legs. Until it replays `forward_quote_ticks` against the real cross policy,
  paper P&L is an upper bound, not a forecast.
- Triggering on book events rather than a minute timer. Constrained by the model itself: its label
  is `bid(t+1) > ask(t)` at **one-minute spacing**, so the prediction horizon is one minute however
  often it is evaluated. Changing the trigger changes the feature distribution it was fit on and
  needs retraining plus revalidation - which needs the fill model first to measure whether it helps.
- No `orderbook_delta` subscription, so still no depth beyond touch. Not currently a constraint
  (touch depth is ~100x our order size) but required for any strategy that sizes up.

All three strategies remain `live_enabled=false`.

## One execution policy, two venues (2026-09-27)

The simulator and the live engine now run the **same** `MarketableLimitKernel`, against the same
`MarketFeed`, with the same cross ticks, the same edge tolerance and the same retry behaviour.
Only the submitter differs:

    live:  MarketableLimitKernel(place_limit_order,    feed)
    sim:   MarketableLimitKernel(SimulatedVenue(feed), feed)

The policy knobs are read from the **same environment variables** in both engines
(`KALSHI_ENTRY_CROSS_TICKS`, `KALSHI_EXIT_CROSS_TICKS`, `KALSHI_MAX_ENTRY_SLIPPAGE`,
`KALSHI_ORDER_MAX_ATTEMPTS`), so a paper book cannot silently be run under a policy the live
account is not. That was the structural reason the two disagreed.

**`architecture/simulated_venue.py`** returns Kalshi's flat v2 response shape, so one fill parser
reads both venues and they cannot drift. It models crossing the touch, partial fills against the
size resting at the touch, Kalshi's taker fee, and orders that simply do not fill. It does not
model queue position (every order here is a taker) or depth past the touch (the ticker channel
does not carry it, and touch depth is ~100x our order size).

**What the simulator can now do that it could not before**, each of which happened live on
2026-09-27 and was invisible in paper:
- **miss an entry** - an order that does not fill is not a position
- **fail an exit** - an unfilled sell leaves the position exactly where it was
- **be carried into settlement** - `reconcile_settled_sim_positions()` books expired contracts at
  $1.00/$0.00 from the *public* market result, since the simulator has no account to query
- **abandon a trade whose edge has gone** - if the live ask has run past the signal price

The sim also now scores its edge against the **live book** rather than the bar's ask, matching the
live engine's features-from-the-bar / prices-from-the-book split.

Startup line, for confirming the two match: `sim execution: marketable limit, entry_cross=1
exit_cross=2 max_slippage=0.02 attempts=3`.

**Remaining gap.** This is forward paper trading with a realistic fill model, not a backtest.
`forward_quote_ticks` only began recording on 2026-09-27, so there is no tick history to replay
older signals against; a historical backtest would still have to use 20-second `forward_quotes`
samples and would inherit their optimism. Judge the strategies on paper results recorded from
tonight onward, not on the pre-existing 25,442 trades - those were produced by the old
fill-everything model and are an upper bound.

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

## Sim-vs-real equity curve (Kalshi dev replay)

- `app/kalshi_dev.py`: READ-ONLY replay of a strategy's out-of-sample window against the
  Kalshi DEMO environment (`KALSHI_DEV_API_BASE`, e.g. `https://demo-api.kalshi.co/trade-api/v2`).
  Pulls public per-contract candlesticks (unauthenticated GET), rebuilds the OOS snapshots off the
  real demo order-book bid/ask while reusing the real BTC spot features, then re-scores with the
  backtester's own `simulate`/`metrics`/fee model so the realized curve is directly comparable to
  the simulated one. Never authenticates, never POSTs, never places an order.
- Endpoint `GET /api/strategies/{id}/dev-curve` (`strategy_dev_curve`) returns `{dev_curve, dev_metrics,
  contracts, capped}`; degrades to `{dev_curve: null, reason}` when demo isn't configured/reachable.
  Cached per strategy id (10 min). Capped to the first `KALSHI_DEV_MAX_CONTRACTS` (default 60) OOS
  contracts to bound API calls (ceiling noted in-file; raise/parallelise/persist for the full window).
- `app/static/app.js`: `equityChart` takes an optional `devCurve` (dashed accent line + legend); the
  strategy detail view fetches the dev-curve after load and redraws the chart with both lines.

## Tau-RSI: self-evolving research (Dream-RSI adapted) — DESIGN (2026-10-15)
Paper: Dream-RSI (arXiv 2609.14858, Google/UMD) — github.com/zhengkid/Dream-RSI.
Owner chose: per-user private memory; FULL Dream-RSI (replay simulator + dreaming);
paper-faithful **evolvable executable policy code**; retrieval + self-edited policy.

**Core safety invariant:** the exploration policy is a PURE decision function
`next_batch(tree, round) -> Batch | STOP` and `should_stop(tree, round)`. It reads the
discovery tree and returns allocation decisions only; it NEVER touches LLM/backtest/DB/
network — the harness performs all I/O. So per-user LLM-written policy CODE is sandboxable:
side-effect-free, run with no network/filesystem, import whitelist (math/statistics), AST
validation (no dunder/imports), CPU+mem+time limits, and a default-policy fallback on any
error/timeout.

**Mapping to our pipeline:** discovery agent = hypothesis proposer (LLM) + backtester
(evaluator); node = one tested hypothesis + its in-sample/OOS/gate outcome (already stored in
app_strategies); exploration policy = today's hardcoded BATCH=4/FINALISTS 3-8/stopping (to be
made evolvable); replay simulator = re-traverse the stored per-user tree with objective
`V = best_score - b1*generations + b2*parallelism` (no new LLM/backtest); dreaming = a
policy-development LLM revises the policy code, each validated over historical trees via replay,
best (>= current) deployed. NOTE our backtests are cheap, so the replay trick's payoff is
smaller than the paper's expensive-kernel setting; the dominant cost here is proposal tokens.

**Phases:** P1 foundation (ExplorationPolicy pure-fn interface + DefaultPolicy extracted from
current logic; discovery-tree schema: parent_id + per-user linkage; no behavior change) ->
P2 replay simulator + objective (read-only, tested) -> P3 sandbox (restricted subprocess +
AST validation + resource limits + loader/fallback) -> P4 dreaming loop (policy-dev agent +
per-user policy storage + deploy-best; billed as research).

## Tau-RSI: fixing "0 policies evolved" — GENERALIZATION OBJECTIVE (2026-10-15)
**Symptom:** 0 policies evolved across 6 users / 3 runs despite apparent headroom.

**Root-cause diagnosis (evidence from real trees users 7/1/2, market btc15m, pulled via SSM):**
1. **The old objective rewarded OVERFITTING the recorded node order, not better research.**
   A single fixed-order replay with a `-b1*generations` term made "stop early" look great
   *only when that recording's winner happened to appear early* — which does not recur next run.
   Proof: a stop-just-after-the-winner policy beats the default on the fixed order for every
   user (user 2: V 194.2->224.6) but **collapses** when V is averaged over shuffled orders
   (user 2: mean 194.2 -> -40.8; user 7 winner is actually at idx **462/500**, so stopping early
   there throws the winner away). The paper's premise ("winner appears early") is empirically
   false on our trees.
2. **The policy's only real lever is finalist SELECTION, not batch width / stopping.** With OOS
   P&L in the hundreds–thousands and b1=0.1, reaching the winner dwarfs any compute saving, so
   the generalization-optimal `next_batch` is just "reveal the budget" — stopping is a dead lever.
   The live winner for user 1 was a *selection* fix: the default ranks by in-sample score and
   tests the top ~8, which **MISSES** user 1's real OOS winner (+$282, idx 15) and instead gates
   money-losers (default mean V = **-71**). Testing every profitable/sturdy candidate catches it
   (mean V **+232**), order-invariant.
3. **The old objective had no multiple-testing penalty and an ungrounded parallelism bonus.**
   "Select everything" maximized best_quality for free (manufacturing false edges — the exact
   thing research_brief.md warns against); the `+b2*parallelism` term rewarded wide batches whose
   effect the replay cannot even measure (recorded outcomes don't depend on batch size) = a free
   gaming vector.
4. **Why the LLM found nothing:** the prompt exposed only {proposed,budget,round} and told the LLM
   stopping/batching was the lever, so it kept proposing early-stops that backfire on real trees,
   while the one reliable win (looser selection) was explicitly discouraged ("keep it small").
   Real Sonnet-4.5 run (old prompt): user 7 = 0/3 beat base, user 1 = 1/3 (and that one games the
   missing penalty). Non-deterministic + N_CANDIDATES=3 = ~0 adoptions.

**Fix (minimal, preserves pure-function + sandbox invariants):**
- `replay.replay_generalization(policy, tree, budget)` = **mean V over 32 orderings** (recorded +
  seeded shuffles). This is what `dreaming` scores base and candidates on. Order-overfitting is
  now self-defeating; the default (reveals all -> order-invariant) is the robust baseline.
- New objective `V = best_quality - 0.1*generations - 0.1*finalists`: dropped the parallelism
  bonus (ungrounded/gameable), added a **multiple-testing penalty** per gated finalist (grounds
  the brief's "best of fifty is weak evidence"), so selection is a real precision/recall tradeoff
  and "select all" can't game it.
- `next_batch` now sees only {proposed,budget,round} in replay too (was fed `history` the live
  harness never provides) — removed train/serve skew; dropped the vestigial `PolicyState.history`.
- `DREAM_SYSTEM`/prompt rewritten: tells the LLM it's scored on the AVERAGE over reshuffled orders
  (stopping early can't help), names **selection** as the lever (catch the OOS winner with as FEW
  finalists as possible), and surfaces the selection-gap signal (did the current policy catch the
  best strategy the history holds?). N_CANDIDATES 3->5.
- Guard: a candidate must actually explore+gate (`generations>0 and finalists>0`), so the new
  penalties can't make a do-nothing policy (V=0) "beat" a default that selects OOS losers (V<0).

**Signal flow (dreaming loop, after fix):**
```
recorded discovery tree (app_strategies, per user+market)
        │  build_tree()
        ▼
  ┌───────────────────────────── evolve_policy ─────────────────────────────┐
  │ current policy ──► replay_generalization (mean V over 32 shuffled orders)│  = base_v
  │                                                                          │
  │ policy-dev LLM (DREAM_SYSTEM + tree summary + selection-gap signal)      │
  │        │ N_CANDIDATES=5 pure-Python policies                            │
  │        ▼                                                                 │
  │   sandbox.load_policy (AST gate + restricted builtins + timeout)         │
  │        │ for each safe candidate                                         │
  │        ▼                                                                 │
  │   explore+gate guard ──► replay_generalization  ─► v                     │
  │                                                                          │
  │   keep best v (> base_v + eps)   ── monotonic: current always competes   │
  └──────────────────────────────────────────────────────────────────────────┘
        │  set_policy() only if a candidate genuinely generalizes
        ▼
  next run uses the evolved policy (agent.run_research -> current_policy)
```

**Before/after (real trees; default -> best adopted, generalization mean V):**
| user | default V | overfit stop-early (old would chase) | evolved (selection) | outcome |
|------|-----------|--------------------------------------|---------------------|---------|
| 7 (winner idx 462) | 4092.79 | fixed 4096.4 but **gen 4035.7 (rejected)** | 4093.3 (finalists 8->3, same winner) | tiny real win; overfit refused |
| 1 (winner idx 15)  | **-71.24** (gates OOS losers) | — | **+231.92** (catches the +$282 winner) | big real win, order-invariant |
| 2 (winner idx 13)  | 193.00 | fixed 224.6 but **gen -40.8 (rejected)** | none > default | default kept (already optimal); overfit refused |

Real Sonnet-4.5 with the new prompt: user 1 = **3/5 candidates reach +231.9** (all via selection,
no early-stop attempts); user 7 = 2/5 find the small tighter-selection win; overfit rejected. The
loop now improves real research where headroom exists and honestly adopts nothing where it doesn't.

**Deliberately NOT done (ponytail):**
- *Evolving proposal/directional guidance* (the biggest lever on research quality): the replay
  simulator replays FIXED recorded proposals — it cannot score what *different* guidance would
  propose, so making guidance evolvable would be optimizing a knob the simulator can't evaluate.
  Needs a different evaluator (e.g. held-out live runs), out of scope for a replay-validated loop.
- *Throttle*: dreaming is ~1k in / ~1.3k out tokens (~$0.02) per eligible run and is monotonic
  (never harmful), so a throttle is low-value. If wanted: persist the tree size at last dream and
  skip when it hasn't grown by N new gated nodes (needs a schema column; deferred).
