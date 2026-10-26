"""Demo copies of paper strategies: every running paper strategy also trades on Kalshi's demo
(sandbox) exchange, on the same engine code, so the real order path (placing, filling, booking,
reconciling) is exercised from a strategy's first day instead of after its paper record.

Demo's play-money book is thin, so demo P&L is no evidence of an edge; paper keeps that job. A copy
is made only while the user has a demo key and a funded demo account (an empty one refuses every
order), and it is paused (the engine flattens it) once no paper deployment of its strategy is still
running (and resumed with it). On by default (Todd, 2026-10-25); APP_DEMO_TWINS=0 turns it off.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from app import repository as repo
from app import spec as specmod
from app.markets import MARKETS

DEMO_TWINS = os.getenv("APP_DEMO_TWINS", "1") == "1"
# Below this the account can't carry a few paper-sized stakes, and orders come back refused.
DEMO_TWIN_MIN_BALANCE = float(os.getenv("APP_DEMO_TWIN_MIN_BALANCE", "100"))
PAUSE_REASON = "Its paper strategy is no longer running, so the demo copy stopped too."


def _read_balance(cur, user_id: int, timeout: int = 15) -> Optional[float]:
    """The user's demo cash in dollars, or None when there is no key or the read fails."""
    from app import kalshi_account
    from app.kalshi_dev_exec import demo_balance_dollars

    row = repo.get_kalshi_dev_key(cur, user_id)
    if row is None:
        return None
    try:
        return demo_balance_dollars(kalshi_account.credentials_from_row(user_id, row), timeout=timeout)
    except Exception as e:
        print("[demo-twins] balance read failed for user %s: %r" % (user_id, e), flush=True)
        return None


# Where a user adds play money to their demo account (the demo key steps on Funds name it too).
KALSHI_DEMO_SITE = "https://demo.kalshi.co"
# The pages that show demo poll; a short per-user memo keeps the demo cash read off every poll.
# Values only (never the key or creds) are cached; a failed read is cached as None (unknown).
BALANCE_TTL = 60.0
# The cached read runs inside a page request, so a slow demo API costs a few seconds, not sync's 15.
BALANCE_PAGE_TIMEOUT = 3
_BALANCE_CACHE: Dict[int, Tuple[float, Optional[float]]] = {}


def forget_balance(user_id: int) -> None:
    """Drop the memo after the demo key changes, so the next read uses the new key."""
    _BALANCE_CACHE.pop(user_id, None)


def balance_read_at(user_id: int) -> Optional[datetime]:
    """When the memoized demo cash was read (naive UTC), or None. The memo only, never Kalshi."""
    from app import kalshi_account

    return kalshi_account.memo_read_at(_BALANCE_CACHE, user_id)


def balance_cached(cur, user_id: int, ttl: float = BALANCE_TTL) -> Optional[float]:
    """The user's demo cash in dollars, at most `ttl` seconds old, or None when it can't be read.
    Read-only: one GET of the demo account's balance, the same read sync makes."""
    now = time.monotonic()
    hit = _BALANCE_CACHE.get(user_id)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = _read_balance(cur, user_id, timeout=BALANCE_PAGE_TIMEOUT)
    _BALANCE_CACHE[user_id] = (now, value)
    return value


def sync(cur, user: Dict, balance: Callable[[object, int], Optional[float]] = _read_balance,
         enabled: Optional[bool] = None) -> List[str]:
    """Make the user's demo deployments mirror their running paper strategies. Returns chat lines."""
    from app import engine  # local: engine imports agent, which calls this

    if not (DEMO_TWINS if enabled is None else enabled):
        return []
    uid = user["id"]
    deps = repo.list_deployments(cur, uid)
    running_paper = {d["strategy_id"]: d for d in deps if d["mode"] == "paper" and d["status"] == "running"}
    demo = {d["strategy_id"]: d for d in deps if d["mode"] == "demo"}
    out: List[str] = []
    for sid, d in demo.items():
        if sid not in running_paper and d["status"] == "running":
            if repo.set_deployment_status(cur, uid, d["id"], "paused", PAUSE_REASON):
                out.append("[demo] Paused the demo copy of “%s”: its paper strategy stopped." % d["title"])
        elif sid in running_paper and d["status"] == "paused" and d.get("status_reason") == PAUSE_REASON:
            # Paused only because paper was: it follows paper back (any other pause is left alone).
            if repo.set_deployment_status(cur, uid, d["id"], "running", None):
                out.append("[demo] Resumed the demo copy of “%s” with its paper strategy." % d["title"])
    todo = [d for sid, d in running_paper.items() if sid not in demo]
    if not todo:
        return out
    cash = balance(cur, uid)
    if cash is None or cash < DEMO_TWIN_MIN_BALANCE:
        return out
    for d in todo:
        strat = repo.get_strategy(cur, uid, d["strategy_id"])
        if strat is None or specmod.is_code_spec(strat["spec"]):
            continue
        mkt = MARKETS.get(strat["market"])
        if mkt is None or not mkt.deployable or engine.cross_deploy_block(strat["spec"], "demo"):
            continue
        repo.create_deployment(cur, uid, strat["id"], strat["market"], "demo")
        out.append("[demo] “%s” now also trades on the demo exchange (play money), testing the real "
                   "order path alongside its paper record." % strat["title"])
    return out
