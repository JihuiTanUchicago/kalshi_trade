"""Public changelog for the Dev Logs tab — what's shipped and what's planned.

Hand-curated (user-facing highlights, not internal ops notes). Keep newest first
in SHIPPED; move a PLANNED item into SHIPPED with its date when it goes live.
This is the public face of mvp.md's Done / TODO, trimmed to what users care about.
"""
from __future__ import annotations

from typing import Dict, List

# Upcoming / in-progress, most-wanted first.
PLANNED: List[str] = [
    "@-mentions in the community (type @ to tag someone; they get notified)",
    "Download a full Credits & Usage receipt",
    "Widen the live market universe beyond BTC",
    "All-markets data lake + backtest over any Kalshi series",
    "Email digests of new community activity (pending email provider approval)",
    "More premium models (Claude 5.x, GPT, Grok) — pending cloud access",
]

# Shipped, newest first: (YYYY-MM-DD, what changed).
SHIPPED: List[tuple] = [
    ("2026-10-15", "Default research model upgraded to Claude Opus 4.5"),
    ("2026-10-15", "DeepSeek R1 added to the model picker"),
    ("2026-10-15", "Reaction hover shows who reacted; comments load 10 at a time with search"),
    ("2026-10-15", "Community composer pinned to the bottom (chat-style)"),
    ("2026-10-15", "Share a strategy with a friend + a notification bell"),
    ("2026-10-15", "Live unrealized (mark-to-market) P&L on open positions"),
    ("2026-10-15", "Strategies list: Deployed/Live badge, search, and a deployed-only filter"),
    ("2026-10-15", "Multi-select deploy; stop-a-deployment inline before deleting"),
    ("2026-10-15", "Markdown + meme reactions in community posts"),
    ("2026-10-15", "Self-improving research loop (Tau-RSI) now generalizes instead of overfitting"),
    ("2026-10-14", "Live/real trading enabled with market-order-like entries and risk caps"),
    ("2026-10-14", "Open-sourced the codebase; repositioned as RSI for Trading"),
    ("2026-10-13", "Per-model billing with exact prices; pick the model your research runs on"),
    ("2026-10-13", "Community tab: posts, likes, comments, photos, P&L sharing"),
    ("2026-10-12", "Credits + per-token billing (OpenRouter-style) over Stripe"),
]


def as_json() -> Dict:
    return {
        "planned": list(PLANNED),
        "shipped": [{"date": d, "title": t} for d, t in SHIPPED],
    }
