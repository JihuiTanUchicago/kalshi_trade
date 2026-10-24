"""Transaction cost analysis (TCA) for real orders: what each fill actually cost, and what it was worth.

Every live/demo order is logged as an intent before it is sent (app_order_intents), and the
kernel's report is saved back onto it: the decision price, the fair value and min_edge of an
entry, and every child attempt with the YES quote it was priced from. This module reads those
rows back and measures, per order:

  * fill rate             filled / requested contracts (a missed entry is free; a missed exit is not)
  * slippage vs decision  fill price vs the price the strategy decided at, in the order's own side,
                          signed so positive = we paid (buy above / sold below the decision price)
  * cost vs arrival mid   fill vs the mid of the first quote the kernel priced from: half-spread
                          plus any walk through the book
  * fee per contract      the taker fee actually charged
  * edge captured         (entries) fair - fill - fee: the edge actually locked in, vs min_edge
  * markouts              own-side mid h seconds after the order vs the fill, signed so positive =
                          the market moved our way. Persistently negative short-horizon markouts on
                          entries are adverse selection: we get filled when we are wrong.

``report`` groups those by mode, series and action. These are the numbers the research loop's
cost model should be calibrated against (backtest fill price + fee vs what live actually paid).

Read-only and outside the order path: it never touches an order, and it runs against the same
repository layer as everything else, so it is testable on fakes.

    python -m app.tca --days 7          # JSON report to stdout
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from app import repository as repo

HORIZONS = (60, 300, 900)


def _load(raw) -> Dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def _f(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def own_side_book(side: str, yes_bid: Optional[float], yes_ask: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    """(bid, ask) in the order's own side. NO mirrors YES: no_bid = 1 - yes_ask, no_ask = 1 - yes_bid."""
    if str(side).lower() == "no":
        return (None if yes_ask is None else 1.0 - yes_ask, None if yes_bid is None else 1.0 - yes_bid)
    return yes_bid, yes_ask


def _mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    return None if bid is None or ask is None else (bid + ask) / 2.0


def _series(ticker: str) -> str:
    return str(ticker or "").split("-")[0]


def _aware(dt) -> Optional[datetime]:
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fill_costs(it: Dict) -> Dict:
    """Per-order cost record from one intent row. Unfilled orders keep their outcome and fill rate
    (0) and leave the price fields None."""
    raw = _load(it.get("raw_json"))
    side, action = str(it.get("side") or "yes").lower(), str(it.get("action") or "").lower()
    buying = action == "buy"
    sign = 1.0 if buying else -1.0
    requested = int(it.get("qty") or 0)
    filled = int(it.get("fill_qty") or 0) if it.get("status") == "booked" else 0
    attempts = [a for a in (raw.get("attempts") or []) if isinstance(a, dict)]
    sent = [a for a in attempts if "limit" in a]
    first = sent[0] if sent else None
    arr_bid, arr_ask = own_side_book(side, _f(first.get("quote_bid")), _f(first.get("quote_ask"))) if first else (None, None)
    arrival_mid = _mid(arr_bid, arr_ask)
    decision = _f(raw.get("decision_price"))
    if decision is None:
        decision = _f(it.get("limit_price"))
    fill = _f(it.get("fill_price")) if filled > 0 else None
    fee = _f(it.get("fee")) if filled > 0 else None
    fee_pc = (fee / filled) if fee is not None and filled > 0 else None
    fair = _f(raw.get("fair"))
    rec = {
        "intent_id": it.get("intent_id"), "mode": it.get("mode"), "action": action, "side": side,
        "ticker": it.get("ticker"), "series": _series(it.get("ticker")), "created_at": it.get("created_at"),
        "requested": requested, "filled": filled,
        "outcome": "filled" if filled >= requested > 0 else ("partial" if filled > 0 else
                                                              str(raw.get("status") or it.get("status") or "unfilled")),
        "children_sent": len(sent), "decision_price": decision, "fair": fair, "min_edge": _f(raw.get("min_edge")),
        "arrival_mid": arrival_mid,
        "arrival_spread": None if arr_bid is None or arr_ask is None else arr_ask - arr_bid,
        "fill_price": fill, "fee_per_contract": fee_pc,
        "slippage_vs_decision": None if fill is None or decision is None else sign * (fill - decision),
        "cost_vs_arrival_mid": None if fill is None or arrival_mid is None else sign * (fill - arrival_mid),
        "edge_captured": (fair - fill - (fee_pc or 0.0)) if buying and fair is not None and fill is not None else None,
    }
    return rec


def add_markouts(cur, rec: Dict, horizons: Iterable[int] = HORIZONS) -> Dict:
    """Own-side mid ``h`` seconds after the order minus the fill, signed so positive = moved our way."""
    t0 = _aware(rec.get("created_at"))
    sign = 1.0 if rec["action"] == "buy" else -1.0
    for h in horizons:
        key = "markout_%ds" % h
        rec[key] = None
        if rec.get("fill_price") is None or t0 is None:
            continue
        q = repo.yes_quote_at(cur, rec["ticker"], t0 + timedelta(seconds=int(h)))
        if q is None:
            continue
        mid = _mid(*own_side_book(rec["side"], q["yes_bid"], q["yes_ask"]))
        if mid is not None:
            rec[key] = sign * (mid - rec["fill_price"])
    return rec


def _wmean(rows: List[Dict], key: str) -> Optional[float]:
    pts = [(r[key], r["filled"]) for r in rows if r.get(key) is not None and r["filled"] > 0]
    w = sum(q for _, q in pts)
    return round(sum(v * q for v, q in pts) / w, 5) if w else None


def summarize(records: List[Dict], horizons: Iterable[int] = HORIZONS) -> List[Dict]:
    """Contract-weighted cost stats per (mode, series, action). Prices are dollars per contract."""
    groups: Dict[Tuple[str, str, str], List[Dict]] = {}
    for r in records:
        groups.setdefault((r["mode"], r["series"], r["action"]), []).append(r)
    out = []
    for (mode, series, action), rows in sorted(groups.items()):
        requested = sum(r["requested"] for r in rows)
        filled = sum(r["filled"] for r in rows)
        outcomes: Dict[str, int] = {}
        for r in rows:
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
        g = {
            "mode": mode, "series": series, "action": action, "orders": len(rows),
            "contracts_requested": requested, "contracts_filled": filled,
            "fill_rate": round(filled / requested, 4) if requested else None, "outcomes": outcomes,
        }
        for key in ("slippage_vs_decision", "cost_vs_arrival_mid", "fee_per_contract", "arrival_spread",
                    "edge_captured"):
            g[key] = _wmean(rows, key)
        for h in horizons:
            g["markout_%ds" % h] = _wmean(rows, "markout_%ds" % h)
        out.append(g)
    return out


def report(cur, days: float = 7.0, now: Optional[datetime] = None, horizons: Iterable[int] = HORIZONS) -> Dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=float(days))
    records = [add_markouts(cur, fill_costs(it), horizons) for it in repo.order_intents_between(cur, since, now)]
    return {"generated_at": now.isoformat(), "window_days": float(days), "orders": len(records),
            "groups": summarize(records, horizons)}


def main() -> None:  # pragma: no cover - thin CLI over report()
    from data_pipeline.common import get_db_conn

    ap = argparse.ArgumentParser(description="Transaction cost analysis of live/demo orders.")
    ap.add_argument("--days", type=float, default=7.0)
    args = ap.parse_args()
    conn = get_db_conn()
    try:
        print(json.dumps(report(conn.cursor(), days=args.days), indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    main()
