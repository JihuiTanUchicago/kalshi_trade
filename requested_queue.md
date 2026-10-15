# Requested Queue

Open requests the user made that aren't shipped yet. Remove each line once fulfilled.
`[blocked: …]` = needs a user action/decision before I can proceed.

## Build (chosen / queued)
- All-markets collector + cross-contract — BUILDING. Phase 1 catalog shipped. **Infra: ingestion SEPARATED onto a dedicated collector box (i-0bd0683cc7e86243d); S3 data-lake bucket created.** Next: S3/Parquet per-minute snapshots (Phase 2), then backtest-over-any-series (3), cross-contract (4). RDS bump deferred (load dropped after split).
- Kalshi dev-env 2nd curve code shipped but needs `KALSHI_DEV_API_BASE` set on the box to actually draw the real-Kalshi-dev line (degrades to one line until then).
- Should track unrealized for deployed strategies (paper/real)
- Real deploy is not working. Cannot deploy to real actually.
- Maybe also a hyperlink to the actual market that each strategy is trading in dashboard
- Also when a strategy is deployed and holds open positions, should have a clear section showing what it's holding
right now in the detail page. /impeccable should be invoked to do this
- Markets still show only a few.

## Blocked on you
- **Model selection: Claude 5.5, OpenAI GPT-6.x, xAI Grok are AWS-access-gated.** Agreements accepted via API + availability shows AUTHORIZED, but invoke returns "not available for this account" even from a full-admin user (so NOT IAM, NOT the instance role — a Bedrock account-level grant AWS hasn't given). Request access in Bedrock console → Model access (us-east-1), or via AWS Sales. Prices already locked: Sonnet5.5 $2/$10, Opus5.5 $4/$20, Haiku5.5 $0.1/$0.5, GPT-6.1 Sol $2.2/$10, GPT-6 Sol $2/$10, GPT-5.6 Sol $8.8/$33. Ship the moment access is granted.
- DeepSeek R1 available+cheap but returns reasoning-only output via Converse (empty text) — needs reasoningContent handling before it's safe to offer.
- (deferred to v0.3) Agent internet access / web search.

## Deferred to v0.3
- Agent internet access / web search (Google/Tavily/Brave).
- Polymarket as a 2nd venue: data + API + real & simulation trading.
