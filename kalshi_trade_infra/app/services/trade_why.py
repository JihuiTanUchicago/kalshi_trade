"""Why a trade on the book was entered and why it exited, as one plain-English line.

"Is the autopilot doing what the strategy said?" is answered from what is already stored: the
position row (entry and exit price, close_reason, order_ref) and the strategy's spec, which is
frozen once registered, so the rule read now is the rule the engine traded on. The value the
signal had at the moment of entry is NOT stored anywhere (no column, no order-intent field, and
paper logs no intent), so the entry half names the rule that had to hold, never a reading. A
position whose strategy spec the caller does not have gets the exit half only. Display only:
nothing here touches an order, a position or a limit.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.trading import spec as specmod

_OPS = {">": ">", ">=": "≥", "<": "<", "<=": "≤"}
ADOPTED_REF = "reconcile-adopt"  # app.trading.reconcile books an untracked Kalshi position under this order_ref


def _c(x: float) -> str:
    """41¢, 4.5¢: a price or a price move in cents (a dollar figure reads $1)."""
    v = round(100 * float(x), 1)
    sign, v = ("−" if v < 0 else ""), abs(v)
    return sign + (("%d¢" % round(v)) if abs(v - round(v)) < 1e-9 else ("%.1f¢" % v))


def _move(x: float) -> str:
    """+21¢ / −12¢: a signed move in price per contract."""
    return ("+" if x >= 0 else "−") + _c(abs(x))


def _num(v: Any) -> str:
    v = float(v)
    return ("−%g" % abs(v)) if v < 0 else "%g" % v


def _entry(pos: Dict, spec: Optional[Dict]) -> Optional[str]:
    at = "Entered at %s" % _c(pos["entry_price"])
    if (pos.get("order_ref") or "") == ADOPTED_REF:
        return "Adopted from your Kalshi account (Tau did not place it)"
    if not spec or specmod.is_perpetual_spec(spec):
        return None
    if specmod.is_code_spec(spec):
        return at + ": the strategy's code signalled a buy"
    if spec.get("cross"):
        return at + ": one leg of a relative-value pair"
    e = spec.get("entry") or {}
    rule = ["%s %s %s" % (specmod.plain_feature(f["feature"]), _OPS.get(f["op"], f["op"]), _num(f["value"]))
            for f in e.get("filters") or []]
    edge = float(e.get("min_edge") or 0)
    rule.append("edge ≥ %s after fees" % _c(edge) if edge > 0 else "fair value at or above the price after fees")
    return at + ": " + ", ".join(rule)


def _exit(pos: Dict, spec: Optional[Dict]) -> Optional[str]:
    x = (spec or {}).get("exit") or {}
    if pos.get("status") != "closed":
        if not spec or specmod.is_perpetual_spec(spec) or specmod.is_code_spec(spec) or spec.get("cross"):
            return None
        plan = []
        if x.get("take_profit") is not None:
            plan.append("%s take-profit" % _move(x["take_profit"]))
        if x.get("stop_loss") is not None:
            plan.append("%s stop" % _move(-x["stop_loss"]))
        if x.get("min_edge_to_hold") is not None:
            plan.append("sells if edge drops below %s" % _c(x["min_edge_to_hold"]))
        return ("Exits: " + ", ".join(plan) + ", else settlement") if plan else "Holds to settlement"
    if pos.get("exit_price") is None:
        return None
    reason, out = pos.get("close_reason") or "", float(pos["exit_price"])
    gain = out - float(pos["entry_price"])
    at = "Exited at %s" % _c(out)
    if reason == "settled":
        return "Held to settlement: " + ("paid $1" if out >= 1 else "expired worthless" if out <= 0 else "paid %s" % _c(out))
    if reason == "take_profit":
        target = " vs %s target" % _move(x["take_profit"]) if x.get("take_profit") is not None else ""
        return "%s: take-profit (%s%s)" % (at, _move(gain), target)
    if reason == "stop_loss":
        stop = " vs %s stop" % _move(-x["stop_loss"]) if x.get("stop_loss") is not None else ""
        return "%s: stop-loss (%s%s)" % (at, _move(gain), stop)
    if reason == "edge_gone":
        line = " %s" % _c(x["min_edge_to_hold"]) if x.get("min_edge_to_hold") is not None else ""
        return "%s: the model's edge fell below its%s hold line" % (at, line)
    said = {"stop": "your loss stop closed this strategy's positions",
            "drawdown": "your drawdown limit closed this strategy's positions",
            "flatten": "sold when the strategy was paused or stopped",
            "pair_unwind": "the unhedged pair leg was sold straight back"}.get(reason)
    if said:
        return "%s: %s" % (at, said)
    return "%s (%s)" % (at, reason.replace("_", " ")) if reason else at


def trade_why(pos: Dict, spec: Optional[Dict] = None) -> Optional[str]:
    """"Entered at 27¢: the 5-minute return < −0.2, edge ≥ 3¢ after fees · Exited at 48¢:
    take-profit (+21¢ vs +20¢ target)". `spec` is the position's strategy spec, or None when the
    caller doesn't have it (then only the exit is said). None when there is nothing to say.
    A spec it can't read is treated as missing: a display line never fails the page it is on."""
    parts = []
    for half in (_entry, _exit):
        try:
            parts.append(half(pos, spec))
        except (KeyError, TypeError, ValueError, AttributeError):
            parts.append(half(pos, None) if spec is not None else None)
    return " · ".join(p for p in parts if p) or None
