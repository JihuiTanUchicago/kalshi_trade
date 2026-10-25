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
from typing import Callable, Dict, List, Optional

from app import repository as repo
from app import spec as specmod
from app.markets import MARKETS

DEMO_TWINS = os.getenv("APP_DEMO_TWINS", "1") == "1"
# Below this the account can't carry a few paper-sized stakes, and orders come back refused.
DEMO_TWIN_MIN_BALANCE = float(os.getenv("APP_DEMO_TWIN_MIN_BALANCE", "100"))
PAUSE_REASON = "Its paper strategy is no longer running, so the demo copy stopped too."


def _read_balance(cur, user_id: int) -> Optional[float]:
    """The user's demo cash in dollars, or None when there is no key or the read fails."""
    from app import kalshi_account
    from app.kalshi_dev_exec import demo_balance_dollars

    row = repo.get_kalshi_dev_key(cur, user_id)
    if row is None:
        return None
    try:
        return demo_balance_dollars(kalshi_account.credentials_from_row(user_id, row))
    except Exception as e:
        print("[demo-twins] balance read failed for user %s: %r" % (user_id, e), flush=True)
        return None


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
