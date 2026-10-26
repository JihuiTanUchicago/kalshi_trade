"""The demo record a strategy needs before live money (Todd, 2026-10-25: "Yes, add the demo check").

Paper proves the edge; demo proves the plumbing. Kalshi's demo exchange runs the real order path
(placing, filling, booking), so before live the strategy must show, on demo:

  * enough settled orders (booked or confirmed unfilled) that the path was really exercised,
  * no order the app lost track of (an intent still unsettled an hour after it was sent),
  * a demo book that matches the demo exchange: a reconciliation sweep in the last day, and no
    ticker that disagreed on two sweeps in a row since the strategy's first demo order.

The sweep is READ-ONLY against the demo exchange; the engine loop runs it every 15 minutes.
A disagreement seen once is not counted: a fill booked a beat after the read, or a settlement the
exchange zeroes before the engine books it, looks like a mismatch exactly once (as in the live
reconciler, app/reconcile.py). Demo P&L is no part of this; the play-money book is too thin.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Callable, Dict, List, Optional

from app import reconcile
from app import repository as repo

DEMO_ORDERS_FOR_LIVE = 20
SWEEP_MAX_AGE = timedelta(hours=24)
# An order intent still unsettled this long after it was sent was lost, not in flight.
UNSETTLED_AFTER = timedelta(hours=1)


def _read_positions(cur, user_id: int) -> Optional[Dict[str, int]]:
    """The user's demo positions (ticker -> signed net), or None with no demo key or a failed read."""
    from app import kalshi_account
    from app.kalshi_dev_exec import demo_positions

    row = repo.get_kalshi_dev_key(cur, user_id)
    if row is None:
        return None
    try:
        return demo_positions(kalshi_account.credentials_from_row(user_id, row))
    except Exception as e:
        print("[demo-record] positions read failed for user %s: %r" % (user_id, e), flush=True)
        return None


def sweep(cur, user_id: int,
          read_positions: Callable[[object, int], Optional[Dict[str, int]]] = _read_positions) -> Optional[List]:
    """Compare the user's open demo book with the demo exchange and record the result. Returns the
    discrepancies, or None when nothing was checked (no demo activity, no key, or the read failed:
    no row is written, so a failing read can only let the check go stale, never pass it)."""
    if not repo.has_demo_activity(cur, user_id):
        return None
    exch = read_positions(cur, user_id)
    if exch is None:
        return None
    book = reconcile.book_net_from_rows(repo.demo_book_by_ticker_side(cur, user_id))
    found = reconcile.classify(book, exch)
    repo.insert_demo_sweep(cur, user_id, len(set(book) | set(exch)), [d._asdict() for d in found])
    return found


def sweep_all(conn) -> Dict[str, int]:
    """Sweep every user with a demo key and demo activity, each in its own transaction. One user's
    failure is logged and skipped, so the engine loop that calls this never stops on it."""
    summary = {"users": 0, "mismatches": 0, "errors": 0}
    for uid in repo.demo_key_users(conn.cursor()):
        try:
            with repo.transaction(conn) as tx:
                found = sweep(tx, uid)
            if found is not None:
                summary["users"] += 1
                summary["mismatches"] += len(found)
        except Exception as e:
            summary["errors"] += 1
            print("[demo-record] sweep failed for user %d: %r (skipping)" % (uid, e), flush=True)
    return summary


def persisted_mismatches(sweeps: List[Dict]) -> List[str]:
    """Tickers that disagreed on two consecutive sweeps (sweeps oldest first)."""
    out = set()
    prev: set = set()
    for s in sweeps:
        cur_set = {m["ticker"] for m in s.get("mismatches") or []}
        out |= prev & cur_set
        prev = cur_set
    return sorted(out)


def refusal_reason(refusal: Optional[Dict]) -> str:
    """One plain phrase for why the demo exchange refused an order (a stored refusal record)."""
    r = refusal or {}
    code, status = str(r.get("code") or ""), r.get("http_status")
    if code == "insufficient_balance":
        return "the Kalshi demo account doesn't have enough balance; add demo funds on Kalshi's demo site"
    if status in (401, 403):
        return "it didn't accept the demo key; check the Kalshi demo key on the Funds page"
    said = r.get("message") or code or ("HTTP %s" % status if status else "")
    return "Kalshi said: %s" % said if said else "no reason given"


def demo_evidence(cur, user_id: int, strategy_id: int, now=None) -> Dict:
    """The demo check of the live gate for one strategy: `ok`, the refusal `why`, and its numbers."""
    now = now or repo.now_utc()
    orders = repo.demo_order_outcomes(cur, user_id, strategy_id, now - UNSETTLED_AFTER)
    sweeps = repo.demo_sweeps_since(cur, user_id, orders["first_at"]) if orders["first_at"] else []
    persisted = persisted_mismatches(sweeps)
    last = sweeps[-1]["checked_at"] if sweeps else None
    refused = int(orders.get("refused") or 0)
    if refused and not orders.get("booked"):
        # Demo never traded: every order the exchange answered was refused. Say so, and why, rather
        # than let the refusals read as settled orders or as orders the app lost.
        why = ("it couldn't trade on the demo exchange yet: Kalshi refused its %d demo order%s (%s)"
               % (refused, "" if refused == 1 else "s", refusal_reason(orders.get("last_refusal"))))
    elif orders["resolved"] < DEMO_ORDERS_FOR_LIVE:
        why = ("it needs %d+ settled orders on the demo exchange first, to prove the real order path "
               "(has %d)" % (DEMO_ORDERS_FOR_LIVE, orders["resolved"]))
        if refused:
            why += "; %d more %s refused by Kalshi (%s)" % (
                refused, "was" if refused == 1 else "were", refusal_reason(orders.get("last_refusal")))
    elif orders["unresolved"]:
        why = ("%d of its demo orders were never accounted for (still unsettled an hour after sending)"
               % orders["unresolved"])
    elif persisted:
        why = ("its demo book and the demo exchange disagreed on %s on two checks in a row"
               % ", ".join(persisted[:3]) + (" and %d more" % (len(persisted) - 3) if len(persisted) > 3 else ""))
    elif last is None or now - last > SWEEP_MAX_AGE:
        why = "its demo book hasn't been checked against the demo exchange in the last 24h"
    else:
        why = ""
    return {
        "ok": not why, "why": why,
        "orders": orders["resolved"], "orders_needed": DEMO_ORDERS_FOR_LIVE,
        "unresolved": orders["unresolved"], "refused": refused, "mismatched_tickers": persisted,
        "last_check_at": last.isoformat() if last else None,
    }
