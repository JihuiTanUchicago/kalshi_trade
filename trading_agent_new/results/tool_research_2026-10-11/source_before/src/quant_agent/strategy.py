"""One strategy/context/order-planning API shared by research and paper trading."""
from __future__ import annotations

import math
import statistics

from .common import GateError, finite
from .contracts import Limits, StrategyArtifact


def reference_weights(artifact: StrategyArtifact, context: dict) -> dict[str, float]:
    assets = [a["asset_id"] for a in context["universe"]]
    if artifact.kind=="control":
        if artifact.name not in assets: raise GateError("Engineering security is not currently eligible/mature")
        price = context["history"][artifact.name][-1]["close"]
        return {artifact.name:artifact.target_shares*1.001*price/context["nav"]}
    if not assets:
        return {}
    weight = min(0.25, 0.95 / len(assets))
    result = {}
    for asset in assets:
        rows = context["history"][asset]
        total_return = 1.0
        for previous, current in zip(rows, rows[1:]):
            total_return *= (current["close"] + current["dividend"]) * current["split"] / previous["close"]
        if artifact.name == "equal_weight":
            result[asset] = weight
        elif total_return > 1:
            result[asset] = weight
        elif artifact.name == "long_short_trend" and asset in context["borrow"] and context["borrow"][asset]["shares"] > 0:
            result[asset] = -weight
        else:
            result[asset] = 0.0
    return result


def validate_weights(weights: dict, context: dict, limits: Limits, allow_short: bool, positions: dict | None = None) -> dict[str, float]:
    if not isinstance(weights, dict):
        raise GateError("Strategy output must map stable security IDs to target weights")
    universe = {a["asset_id"]: a for a in context["universe"]}
    if set(weights) - set(universe):
        raise GateError("Strategy referenced an ineligible/future/unknown security")
    result = {}
    for asset, value in weights.items():
        value = finite(value, "target weight")
        if abs(value) > limits.position + 1e-12:
            raise GateError("Strategy breached its fixed position cap")
        if value < 0:
            b = context["borrow"].get(asset)
            if not allow_short or universe[asset]["kind"] != "common_stock":
                raise GateError("Short target lacks allowed security type/current as-of borrow evidence")
            if b is None or b["shares"] <= 0:
                if (positions or {}).get(asset,0) < 0:
                    value = 0.0  # Protected risk override closes a recalled short.
                else:
                    raise GateError("Short target lacks allowed security type/current as-of borrow evidence")
        result[asset] = value
    if sum(abs(w) for w in result.values()) > limits.gross + 1e-12:
        raise GateError("Strategy breached its fixed gross cap")
    return result


def plan_orders(context: dict, positions: dict[str, int], nav: float, weights: dict,
                limits: Limits, buffer: float = 0.0, allow_short: bool = True) -> list[dict]:
    """Freeze integer quantities using prior-close information only."""
    weights = validate_weights(weights, context, limits, allow_short,positions)
    nav = finite(nav, "sizing NAV")
    if nav <= 0:
        raise GateError("Nonpositive account NAV")
    orders = []
    for asset in sorted(set(weights) | set(positions)):
        held = positions.get(asset, 0)
        history = context["history"].get(asset)
        if not history:
            if held:
                raise GateError("Cannot plan a held security without fresh as-of prices")
            continue
        price = history[-1]["close"]
        target = weights.get(asset, 0.0)
        desired = math.trunc(nav * target / price)
        b = context["borrow"].get(asset)
        if desired < 0:
            desired = max(desired, -b["shares"])
        forced_cover = held < 0 and (not b or -held > b["shares"])
        if forced_cover:
            desired = max(desired, -b["shares"] if b else 0)
        if not forced_cover and abs(held * price / nav - target) < buffer:
            continue
        qty = desired - held
        volume = statistics.median(row["volume"] for row in history)
        cap = math.floor(volume * limits.participation)
        # Borrow recalls are recorded as forced covers and not delayed by an
        # assumed participation cap; actual execution remains a broker concern.
        if not forced_cover:
            qty = max(-cap, min(cap, qty))
        if qty:
            orders.append({"asset_id": asset, "quantity": qty, "expected_price": price,
                           "asof": context["asof"], "reason": "borrow_recall" if forced_cover else "rebalance"})
    # Reductions precede increases; selling never grants immediate settled cash.
    return sorted(orders, key=lambda o: (abs(positions.get(o["asset_id"], 0) + o["quantity"]) > abs(positions.get(o["asset_id"], 0)), o["quantity"] > 0, o["asset_id"]))
