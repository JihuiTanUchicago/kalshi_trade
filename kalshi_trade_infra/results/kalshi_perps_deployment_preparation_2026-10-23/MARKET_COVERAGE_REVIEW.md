# Bitcoin perps market coverage review

2026-10-23 / documentation and static-source review / handed off to root. Scope: this new review only; no runtime edits, provider API requests, database writes, deployment, service actions, or feature activation by this reviewer. Official documentation was read online. Other tracker and shared-source updates remain root-owned.

**The 120 missing minutes could be the documented weekly maintenance pause. Actual gap alignment remains unverified.** Kalshi specifies Thursday 03:00–05:00 Eastern, rather than a daily pause. Trading is paused; exceptional maintenance can also disconnect sessions or pause the entire exchange. BTC specifications describe 24/7 trading subject to maintenance. [Maintenance and pauses](https://docs.kalshi.com/getting_started/maintenance_and_pauses), [BTC contract specifications](https://help.kalshi.com/en/articles/15357587-btc-perpetual-futures-contract-specifications).

## What the existing receipt proves

`READINESS_39884723368.json` in the feature worktree reports a successful anonymous production read, 2,761 candles, 120 missing minutes, six funding records with complete funding coverage, and four current observations. Requested bounds were `1792546380..1792719180`, or `2026-10-21T01:33:00Z..2026-10-23T01:33:00Z`. Inclusive minute-end labels give 2,881 expected points; subtracting 120 yields 2,761. That is count consistency, not proof that every omission belongs to maintenance. The summary retained no missing-interval timestamps, raw candle payload, or native schedule snapshot.

Root's later bounded local check failed with `provider_unavailable`; see [CANDLE_GAP_TIMESTAMPS.json](CANDLE_GAP_TIMESTAMPS.json). It supplies no additional gap evidence. This reviewer did not retry. A later staged server acceptance can record bounded counts, timestamp ranges and schema/provenance without retaining licensed price bodies.

## Calendar, timezone, and native metadata

Interpret Kalshi's Eastern local clock with `America/New_York`, not a constant UTC offset. This IANA identifier is the implementation mapping; Kalshi's cited prose says ET. US DST in 2026 runs March 8 through November 1, so the October pause is 07:00–09:00 UTC; a November 5 pause is 08:00–10:00 UTC. Python `zoneinfo` applies the dated IANA transitions. [NIST DST rules](https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst), [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html).

For canonical exclusive-end bars, label `t` represents `[t−60,t)`. A maintenance interval `[C,O)` excludes the 120 wholly closed bars with labels `C+60, C+120, …, O`. For Thursday October 22:

| Meaning | UTC | Unix seconds |
| --- | --- | ---: |
| Closure begins; final pre-closure completed-bar label | 2026-10-22 07:00 | 1792652400 |
| First theoretical closed-bar label | 2026-10-22 07:01 | 1792652460 |
| Closure ends; last theoretical closed-bar label | 2026-10-22 09:00 | 1792659600 |
| First complete bar after reopening | 2026-10-22 09:01 | 1792659660 |

These are locally calculated expected labels, not observed missing timestamps. Excluding end labels in `[C,O)` instead would remove the wrong boundary bars.

The native market response exposes `schedule.is_open`, `next_close_ts`, and `next_open_ts`, plus `status`, `market_version`, `exchange_index`, contract-unit fields, and optional `product_metadata.important_info`. Capture validated values with retrieval time and fingerprint. A current schedule snapshot is not a dated historical calendar. Null or unverified schedule data must not authorize a gap exemption. The perps overview explicitly lists exchange schedule and historical endpoints as unavailable on margin; the predictions exchange-schedule API is not proof of perps historical closures. [Native Get Market](https://docs.kalshi.com/margin-rest/market/get-market), [Perps API overview](https://docs.kalshi.com/margin).

The published rule does not establish its effective start across the entire configured 90-day history. Pin the supported effective range and exceptions; do not backdate today's current metadata or silently exempt every historical Thursday.

## Existing code behavior and implications

Reviewed release HEAD `33bfc957cd8443924f65776e5a744835caa5eaea`:

- `app/adapters/kalshi_perps/kalshi_perps_data.py`, SHA-256 `91cc7ea9a7a5b3b822cc3edf07353029df699c9f6f2097022985fdac4ad58156`: `normalize_instrument` retains native schedule without validating or interpreting it. `candles` requests completed 1-minute data with `include_latest_before_start=false`, skips null OHLC, and preserves `native_end_ts`. It maps second-59 native ends to the next minute; native second-00 ends remain on that boundary. `candle_coverage` expects every wall-clock minute and has no calendar exemption.
- `app/adapters/kalshi_perps/kalshi_perps_backtest.py`, SHA-256 `586c51a4263d618386706a6019d5c866c2114823d50234295c517c6d6316b740`: `_coverage_reason` rejects every adjacent candle difference other than 60 seconds. A maintenance-spanning fold therefore rejects even if all open-market minutes are present. Merely relaxing this comparison would let execution iterate across a closure without a declared position, warm-up, or reopening policy.

The native candle docs specify inclusive query bounds by candle ending time, intervals of 1/60/1440 minutes, and a synthetic leading candle option whose OHLC is null. Never convert its `price.previous` into a traded OHLC bar. Keep the current native-boundary provenance and verify the actual timestamp convention before accepting an exception. The rendered native page does not expose the nested end-timestamp description; the YAML was unsupported by the browsing renderer and a credential-free documentation download timed out. This review does not newly certify second-00 versus second-59 semantics. [Native candlesticks](https://docs.kalshi.com/margin-rest/market/get-market-candlesticks).

## Safe path to usable research history

1. Preserve raw coverage as measured. Add separate scheduled-closed intervals/counts, unexpected missing intervals/counts, native null-price exclusions, request boundaries, retrieval success, effective calendar version and evidence. Only label open-session coverage complete after exact set comparison. Unexpected gaps, conflicting duplicates, invalid boundaries, or missing boundary bars still reject. Do not redefine 120 missing bars as 120 valid bars.
2. For a minimal replay policy, predeclare deterministic trading sessions, remain flat through closures, and reset feature warm-up after reopening. Close at an observed tradable execution opportunity before the pause; with the current next-open model, the last full bar ending at `C` has open `C−60`. Do not fabricate a fill at the closed boundary `C`, interpolate the pause, or compress timestamps. Carrying a position across closure requires a separately reviewed reopening/price-gap, funding, risk and timing model.
3. Apply session boundaries consistently to every strategy and chronological fit/test/holdout slice, preserve wall-clock durations and sequential capital, and disclose the flat-session policy. Do not select favorable contiguous runs, silently omit bad sessions, or reset capital/evaluations per segment. Freeze calendar, session policy, units, and full-value data source version with each run; a coverage-rule change creates a new explicit research version.
4. Funding remains an independent ledger. BTC payments are at 00:00, 08:00 and 16:00 ET. Require each expected actual record and successful retrieval, including explicit zero-rate records; never invent payments or infer zero from absence. Local-clock schedules need DST-aware 7/9-hour transition intervals, not repeated UTC 8-hour additions. Use the provider's finalized rate as supplied; do not prorate it again because the interval contained maintenance. Kalshi says closed portions do not contribute to the funding calculation. [BTC specifications](https://help.kalshi.com/en/articles/15357587-btc-perpetual-futures-contract-specifications), [Funding explanation](https://kalshi.com/perpetuals/learn), [Historical funding](https://docs.kalshi.com/margin-rest/funding/get-historical-funding-rates).
5. The estimate endpoint describes the current unfinished funding period. Collect estimates prospectively with source/computed time and retrieval availability; never turn the six finalized payments into historical signals or project today's four observations backward. Existing `_observation_features` correctly uses only separately observed estimates available by decision time. [Funding estimate](https://docs.kalshi.com/margin-rest/funding/get-funding-rate-estimate).

Acceptance should cover both DST seasons, both DST funding transitions, exact closure/reopening labels, native null bars, an unexpected missing open minute, extended/unscheduled maintenance, unknown calendar metadata, and any position or signal spanning a pause. Then verify actual missing timestamps once on the already successful server route during staged acceptance. Public data collection can truthfully report partial coverage before this work; data access alone does not establish replay readiness or paper/real-order capability. Root owns implementation and activation decisions after the user's scope clarification.
