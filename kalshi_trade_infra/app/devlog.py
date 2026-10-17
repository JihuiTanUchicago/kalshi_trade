"""Public changelog for the Dev Logs tab — what's shipped and what's planned.

Hand-curated (user-facing highlights, not internal ops notes). Keep newest first
in SHIPPED; move a PLANNED item into SHIPPED with its date when it goes live.
This is the public face of mvp.md's Done / TODO, trimmed to what users care about.
"""
from __future__ import annotations

from typing import Dict, List

# Upcoming / in-progress, most-wanted first.
PLANNED: List[str] = [
    'claude code style animation demonstration in a research session',
    'Activate Alpaca stock/ETF agent data after secure worker configuration and entitlement checks, with a production canary before customer rollout',
    'All-markets collector + cross-contract',
    'Widen the live market universe',
    'Email-all community digest',
    'Premium model access',
    'Kalshi-dev 2nd equity line',
    'Agent internet access / web search (Google/Tavily/Brave)',
    'Polymarket as a 2nd venue: data + API + real & simulation trading',
    'Risk-management force-sell layer on drawdown + portfolio caps (lost when a prior background agent exited; needs rebuild)',
    'Authenticated dev/demo-env trading',
    'Research follow-up on a previously passed strategy gets stuck',
    'Dig deeper on a passed strategy',
    'Cross-day generalization in the gates',
    'Order-book depth to research',
    'Contract pairs/groups & hedging',
    'NBA / Kalshi sports markets',
    'Bittensor (TAO) subnet tokens as a new venue',
    'Onboard Opus 5.5 (claude-opus-5-5) + surface model comparison',
]

# Shipped, newest first: (YYYY-MM-DD, title, detail). `detail` is the full
# markdown explanation (what/components/methodology); may be '' for one-liners.
SHIPPED: List[tuple] = [
    ('2026-10-16', 'Statistically-rigorous research pipeline', '(true "quant research") — splits generation from judgment: immutable experiment ledger + pre-registration, a Statistical Gatekeeper separate from the generator (BH/LORD++ online-FDR, Deflated/Probabilistic Sharpe, stationary-bootstrap p-values), research/validation/locked-holdout split + purged walk-forward/embargo, a 9-phase proposer + challenger, and the strategy detail page rebuilt as a research paper (thesis/mechanism/pre-registered test/results/holdout + 5 charts). Deploy gate gained an additive, fail-closed DEPLOYMENT_CANDIDATE requirement; live gate unchanged except stricter. (Deployed + live `b4d5f2e`.)'),
    ('2026-10-16', 'Real demo-book slippage accounting', 'replays each strategy against the Kalshi demo book (read-only, no orders), measures the per-trade fill gap vs the simulated book as signed entry/exit cents, shows it on the strategy page, and defaults the what-if slippage knob to the measured value. (Deployed + live `a0d05a2`.)'),
    ('2026-10-16', 'Live autopilot', 'full research→paper→live→risk loop, **gated and off by default** behind the typed-LIVE confirm + every existing safety gate (paper-proven, YES-only, per-user Kalshi key, daily-loss kill switch).'),
    ('2026-10-16', 'Autopilot consolidated into the floating window; the Deploy page is now board-only (Agent panel removed)', ''),
    ('2026-10-16', 'Dashboard pause/resume/stop for deployments (same code path as Deploy)', ''),
    ('2026-10-16', 'Theme switcher', 'pick the Tau or Meridian frontend in Settings; Meridian brought to feature parity.'),
    ('2026-10-16', 'Quant toolkit app/quant.py (BS-digital fair value', 'vol, Kalshi fees, edge, Kelly, portfolio metrics) — built + tested, not yet wired into the agent.'),
    ('2026-10-16', 'Alpaca stock/ETF market data connected to research/copilot calls', 'with on-demand symbols, historical training cutoffs, feed provenance and stale-data handling. 258 Python tests passed, 7 opt-in MySQL tests skipped. Real IEX snapshot/history reads were verified locally; production activation remains above. Implementation.'),
    ('2026-10-15', '@-mentions in the community (Slack-style)', 'Every user gets a unique `@handle` (backfilled from their email; assigned on signup), shown as `Name @handle` on posts/comments. Typing `@` in the composer or a reply opens a candidate list (by handle or name, arrow/enter to pick); `@handle` renders highlighted in bodies. The mentioned person gets an in-app notification + an email (emails wait on SES prod, like the rest). New: `app_users.username`, `/api/users/mention`, `MENTION_RE`/`assign_username`. Verified on the real DB (all 10 users backfilled, unique, dedup works).'),
    ('2026-10-15', 'Dev Logs tab', '(public changelog: shipped list with dates + "shipping next"), **Credits & Usage receipt** download (CSV of the full ledger), **reaction-hover reactor names** ("and N others"), **comment lazy-load** (latest 10, "Load N earlier"), **full-width explore chart**, default model → **Claude Opus 4.5**, and **Kalshi-dev 2nd equity line enabled** (demo API is public). Fixed two bugs found in testing: `reactions_for` used a non-existent `r.id` column (broke the whole community feed) and the comment reply form read the search box instead of the reply box.'),
    ('2026-10-15', 'DeepSeek R1 model support', '`llm._bedrock` now falls back to the `reasoningContent` block when a model emits no plain text (reasoning models put the answer there), so `extract_json` still works. Added DeepSeek R1 (`us.deepseek.r1-v1:0`) to the catalog at the verified Bedrock price ($1.35/M in, $5.40/M out). Verified live on the box: a real call returns usable JSON. Accessible via the US inference profile (not access-gated, unlike Claude 5.5/GPT/Grok).'),
    ('2026-10-15', 'Comment search', 'on long threads — once a post has >6 replies, a search box filters them live (client-side over the loaded set, with an "N of M" count). ponytail: server-side search if a thread ever tops the 100-comment fetch cap.'),
    ('2026-10-15', 'Email-all on new community posts', "(code shipped; delivery gated on SES prod — see Blocked) — background-thread dispatch to opted-in users on each new post, per-recipient 4h cooldown so a burst can't flood, one-click HMAC-signed **unsubscribe** link (`/unsubscribe`) + `email_opt_out` column. The in-app notification bell already covers community activity without email."),
    ('2026-10-15', 'Community composer pinned to the bottom', '(chat-style): the feed + filter chips scroll above a sticky composer bar with its own elevation; textarea auto-grows from one line. Fixed a token bug where `var(--surface)` (undefined at `:root`) made the bar transparent — now uses `--stock-raised` (opaque).'),
    ('2026-10-15', 'Strategy sharing + notifications', 'Share any strategy with a friend by the email they sign in with (strategy Share panel → `POST /api/strategies/:id/share`). It\'s **copied** into their inventory (so it\'s theirs to deploy like any other, and can\'t be revoked); idempotent — re-sharing the same one won\'t duplicate. A **notification bell** sits by the profile (top-right) with an unread dot + dropdown; it fires on a share to you and on a comment on your post. Shared strategies carry a **"Shared by X"** flag in the list and on the detail page. New: `app_notifications` table, `shared_from_user_id`/`shared_src_id` on `app_strategies`. Verified end-to-end on the real DB (copy origin, idempotent dedup, unread count).'),
    ('2026-10-15', 'Live unrealized (mark-to-market) P&L', 'The engine stamps each open position\'s current YES bid (`mark_price`/`mark_ts` on `app_positions`) every decision tick — reusing the book it already fetches, so zero extra API calls. The web shows unrealized P&L in the strategy Holdings panel, the Deploy-board Open positions table, and the dashboard open-position cards (value by side; NO estimated as 1−bid, labeled "est."). Updates at decision cadence; "—" until the first mark. Verified end-to-end on the real DB.'),
    ('2026-10-15', 'Strategies list: Deployed/Live badge + search + Deployed-only filter', 'Each row now shows a "Deployed" (or red "Live") pill when it has an active deployment (server-side `active_deps`/`live_deps` via correlated subqueries). Added a search box (`q`, matches title/thesis) and a "Deployed" toggle chip; both narrow the list AND the headline counts server-side (shared `_strategy_filter_sql`). Cross-page sort-by-P&L deferred (P&L lives in result JSON).'),
    ('2026-10-15', 'Dashboard Deployed table no longer scrolls sideways', '`width:100%` on the strategy/deployment tables so long titles wrap instead of widening past the viewport; insanely long names break with `overflow-wrap`. Removed the empty/unhelpful Daily P&L bar chart (and its dead CSS).'),
    ('2026-10-15', 'Multi-select deploy', 'on the Strategies page — checkbox column on deployable (passed) rows + select-all + a sticky "Deploy N on paper" bar (loops the existing single-deploy endpoint; live stays per-strategy behind the typed-LIVE gate). Selection is per page.'),
    ('2026-10-15', 'Stop-then-delete made intuitive', 'the Remove panel on a strategy now has an inline "Stop deployment(s) #N" button (previously you had to leave for the Deploy board, find the row, stop it, come back). Delete stays blocked with a clear hint until the deployment is stopped.'),
    ('2026-10-15', 'Tau-RSI dreaming now improves real research, not the recording', "Root cause of 0 policies evolving: the objective rewarded overfitting the recorded node order (stop-early only wins when that one recording's winner was early; on real trees user 7's winner is at idx 462/500), with no multiple-testing penalty, and the prompt pointed the LLM at the dead lever (batch width) instead of the real one (finalist selection). Fixes: score on `replay_generalization` (mean V over 32 shuffled orderings), `V = quality − 0.1·gen − 0.1·finalists` (drop parallelism bonus, add multiple-testing penalty), prompt rewritten around selection, guard that an adopted policy must actually explore+gate. Real Sonnet-4.5: user 1 goes from gating OOS losers (mean V −71) to catching the real +$282 winner (+232, order-invariant); overfit stop-early now rejected."),
    ('2026-10-15', 'Markdown in community posts/comments', "safe `mdLite` subset (bold/italic/`code`/links/line-breaks), HTML-escaped first and http(s)-only links so there's no XSS surface. Inline-code + link styling added."),
    ('2026-10-15', 'Meme emoji reactions', '(goat/ape/whale/diamond/clown/skull/salute/moon) + spacing between the composer and the feed filter.'),
    ('2026-10-15', 'Live/real trading ENABLED for all users', '(`APP_LIVE_TRADING_ENABLED=1`), with **market-order-like entries** (cross the touch, IOC, 10c slippage tolerance; `KALSHI_*` env-tunable). Safeguards: YES-only, per-user Kalshi key, typed-LIVE confirm, risk caps + loss guard. Reversible via the flag.'),
    ('2026-10-15', 'Tau-RSI (P1–P4) shipped + live', '(Dream-RSI adapted): pure-fn `ExplorationPolicy`+`DefaultPolicy`; replay simulator + objective `V=quality−β₁·gen+β₂·parallelism`; sandbox for LLM-authored policy code; dreaming loop (per-user self-evolving policy, monotonic). `app/{exploration,replay,sandbox,dreaming}.py` + `app_policies`; dreaming attempts now logged. 195+ tests.'),
    ('2026-10-15', 'Open-sourced the repo', '(BSL-1.1 → Apache-2.0 at the change date; NOTICE w/ Dream-RSI attribution; public README + `.env.example`); branch protection on `main`; auto-push on commit. Repositioned as **RSI for Trading** (venue-agnostic).'),
    ('2026-10-15', 'Strategy detail', 'live **Holdings** panel + Kalshi market link; **delete a strategy** (blocked while deployed).'),
    ('2026-10-15', 'Invite-only sign-in gate', '(waitlist approval) + admin Approve/Remove; waitlist excludes account-holders.'),
    ('2026-10-15', "Passed strategies always show under their run; clearer 'Hypotheses tested' copy", ''),
    ('2026-10-15', 'Deploy cap 10→100; research budget cap 50→1000; default $5/$100 sim book', ''),
    ('2026-10-15', 'Community "My posts" filter; Billing profile dropdown; System DB-node + market-chip fixes; landing-demo no-reflow', ''),
]


def as_json() -> Dict:
    return {
        "planned": list(PLANNED),
        "shipped": [{"date": d, "title": t, "detail": dt} for d, t, dt in SHIPPED],
    }
