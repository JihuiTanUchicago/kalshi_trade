"""Public changelog for the Dev Logs tab — what's shipped and what's planned.

Hand-curated (user-facing highlights, not internal ops notes). Keep newest first
in SHIPPED; move a PLANNED item into SHIPPED with its date when it goes live.
This is the public face of mvp.md's Done / TODO, trimmed to what users care about.
"""
from __future__ import annotations

from typing import Dict, List

# Upcoming / in-progress, most-wanted first.
PLANNED: List[str] = [
    'Activate Alpaca stock/ETF agent data after secure worker configuration and entitlement checks, with a production canary before customer rollout',
    'All-markets collector + cross-contract',
    'Widen the live market universe',
    'Email-all community digest',
    'Premium model access',
    'Kalshi-dev 2nd equity line',
    'Agent internet access / web search (Google/Tavily/Brave)',
    'Polymarket as a 2nd venue: data + API + real & simulation trading',
    'Statistically-rigorous research pipeline (true "quant research"): immutable experiment ledger + pre-registration, Statistical Gatekeeper separate from the generator, BH/online-FDR + Deflated Sharpe, research/validation/locked-holdout split + purged walk-forward/embargo, bandit research allocation, and strategy detail as a research-paper page',
    'Risk-management force-sell layer on drawdown + portfolio caps (lost when a prior background agent exited; needs rebuild)',
    'Dev-Kalshi slippage accounting',
]

# Shipped, newest first: (YYYY-MM-DD, what changed).
SHIPPED: List[tuple] = [
    ('2026-10-16', 'Live autopilot'),
    ('2026-10-16', 'Autopilot consolidated into the floating window; the Deploy page is now board-only (Agent panel removed)'),
    ('2026-10-16', 'Dashboard pause/resume/stop for deployments (same code path as Deploy)'),
    ('2026-10-16', 'Theme switcher'),
    ('2026-10-16', 'Quant toolkit app/quant.py (BS-digital fair value'),
    ('2026-10-16', 'Alpaca stock/ETF market data connected to research/copilot calls'),
    ('2026-10-15', '@-mentions in the community (Slack-style)'),
    ('2026-10-15', 'Dev Logs tab'),
    ('2026-10-15', 'DeepSeek R1 model support'),
    ('2026-10-15', 'Comment search'),
    ('2026-10-15', 'Email-all on new community posts'),
    ('2026-10-15', 'Community composer pinned to the bottom'),
    ('2026-10-15', 'Strategy sharing + notifications'),
    ('2026-10-15', 'Live unrealized (mark-to-market) P&L'),
    ('2026-10-15', 'Strategies list: Deployed/Live badge + search + Deployed-only filter'),
    ('2026-10-15', 'Dashboard Deployed table no longer scrolls sideways'),
    ('2026-10-15', 'Multi-select deploy'),
    ('2026-10-15', 'Stop-then-delete made intuitive'),
    ('2026-10-15', 'Tau-RSI dreaming now improves real research, not the recording'),
    ('2026-10-15', 'Markdown in community posts/comments'),
    ('2026-10-15', 'Meme emoji reactions'),
    ('2026-10-15', 'Live/real trading ENABLED for all users'),
    ('2026-10-15', 'Tau-RSI (P1–P4) shipped + live'),
    ('2026-10-15', 'Open-sourced the repo'),
    ('2026-10-15', 'Strategy detail'),
    ('2026-10-15', 'Invite-only sign-in gate'),
    ('2026-10-15', "Passed strategies always show under their run; clearer 'Hypotheses tested' copy"),
    ('2026-10-15', 'Deploy cap 10→100; research budget cap 50→1000; default $5/$100 sim book'),
    ('2026-10-15', 'Community "My posts" filter; Billing profile dropdown; System DB-node + market-chip fixes; landing-demo no-reflow'),
]


def as_json() -> Dict:
    return {
        "planned": list(PLANNED),
        "shipped": [{"date": d, "title": t} for d, t in SHIPPED],
    }
