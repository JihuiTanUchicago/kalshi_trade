# Requested Queue

Open requests the user made that aren't shipped yet. Remove each line once fulfilled.
`[blocked: …]` = needs a user action/decision before I can proceed.

## Build (chosen / queued)
- All-markets collector + cross-contract — BUILDING. Phase 1 catalog shipped. **Infra: ingestion SEPARATED onto a dedicated collector box (i-0bd0683cc7e86243d); S3 data-lake bucket created.** Next: S3/Parquet per-minute snapshots (Phase 2), then backtest-over-any-series (3), cross-contract (4). RDS bump deferred (load dropped after split).
- System map zoom-in: drill a component → module → function (AST-derived), with source + callers/callees.
- Kalshi dev-environment execution: strategy curve shows 2 lines (our sim + real Kalshi-dev out-of-sample).
- Custom Slack-style **image** emoji (upload/manage), beyond the standard unicode set.

## Blocked on you
- (deferred to v0.3) Agent internet access / web search.

## Deferred to v0.3
- Agent internet access / web search (Google/Tavily/Brave).
- Polymarket as a 2nd venue: data + API + real & simulation trading.
