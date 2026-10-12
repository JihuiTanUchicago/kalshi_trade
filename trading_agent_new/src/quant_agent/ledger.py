"""Integer-share, next-open long/short accounting with explicit cash restrictions.

This is a conservative unlevered research model, not an IBKR margin replica.
Unsupported fractional actions and insolvency stop the experiment.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
import math
import copy

from .common import GateError
from .contracts import Limits, ResearchSpec, StrategyArtifact
from .data import Dataset
from .sandbox import DockerSandbox
from .strategy import plan_orders, reference_weights


def simulate(dataset: Dataset, spec: ResearchSpec, artifact: StrategyArtifact,
             cost_multiplier: float = 1.0, sandbox_image: str | None = None, stop: str | None = None) -> dict:
    dataset.verify_unchanged()
    if artifact.lookback != spec.lookback:
        raise GateError("Candidate/baseline lookback must match the frozen experiment")
    start = next((i for i, d in enumerate(dataset.days) if d >= spec.start), None)
    end = min(spec.end, stop) if stop else spec.end
    if start is None or dataset.days[-1] < end or start < spec.lookback:
        raise GateError("Insufficient warmup or scoring coverage")
    indices = [i for i in range(start, len(dataset.days)) if dataset.days[i] <= end]
    if len(indices) < 2:
        raise GateError("At least two scored sessions are required")
    limits = Limits(**spec.limits)
    cash, previous_nav = limits.capital, limits.capital
    positions, claims, unsettled, last_marks = {}, [], [], {}
    daily, fills, targets = [], [], []
    worker = DockerSandbox(artifact.code, sandbox_image or "") if artifact.kind == "python" else None
    # Capital is introduced at the first scored session; warmup does not earn
    # fictitious interest before this account exists.
    previous_day = dataset.days[start]
    try:
        for index in indices:
            day = dataset.days[index]
            prior = dataset.days[index-1]
            context = dataset.context(index-1, spec.lookback, spec.allow_short,spec.decision_delay_minutes)
            context["positions"] = dict(positions)
            context["nav"] = previous_nav
            context["limits"] = asdict(limits)
            if worker:
                response = worker.step(context)
                weights = response["weights"]
            else:
                weights = reference_weights(artifact, context)
            queued = plan_orders(context, positions, previous_nav, weights, limits, artifact.buffer, spec.allow_short)
            targets.append({"session": day, "asof": context["asof"], "weights": weights, "orders": copy.deepcopy(queued)})
            opening_positions = dict(positions)
            # Explicit settlement dates come from the reviewed session import.
            day_cash_events, created_claims = [], []
            elapsed = (date.fromisoformat(day) - date.fromisoformat(previous_day)).days
            short_value = sum(-q * last_marks[a] for a, q in positions.items() if q < 0)
            available_prior = cash - sum(u["amount"] for u in unsettled) - short_value * limits.short_collateral + sum(min(0, c["amount"]) for c in claims)
            financing = max(0.0, available_prior) * context["financing"]["credit_rate"] * elapsed / 365
            borrow_charge = 0.0
            for asset, qty in positions.items():
                if qty < 0:
                    b = context["borrow"].get(asset)
                    # Recall days still require a fee record (zero availability is
                    # different from a missing historical fee/availability record).
                    if b is None:
                        raise GateError("Held short lacks as-of historical borrow/fee evidence")
                    borrow_charge += -qty * last_marks[asset] * b["fee_rate"] * elapsed / 365 * cost_multiplier
            cash += financing - borrow_charge
            unsettled = [u for u in unsettled if u["date"] > day]
            day_cash_events += [{"kind": "cash_interest", "amount": financing}, {"kind": "borrow_fee", "amount": -borrow_charge}]
            events = dataset.actions.get(day, [])
            for event in sorted(events, key=lambda e: e["kind"] != "split"):
                asset = event["asset_id"]
                qty = positions.get(asset, 0)
                if event["kind"] == "split":
                    new_qty = qty * event["value"]
                    if new_qty != math.trunc(new_qty):
                        raise GateError("Fractional split requires qualified cash-in-lieu support")
                    positions[asset] = int(new_qty)
                    for order in queued:
                        if order["asset_id"] == asset:
                            new_order = order["quantity"] * event["value"]
                            if new_order != math.trunc(new_order):
                                raise GateError("Split-adjusted order would be fractional")
                            order["quantity"] = int(new_order)
                elif event["kind"] == "dividend" and qty:
                    claim = {"asset_id": asset, "amount": qty * event["value"], "date": event["pay_date"]}
                    claims.append(claim)
                    created_claims.append(claim)
                elif event["kind"] == "delist_cash":
                    amount = qty * event["value"]
                    cash += amount
                    day_cash_events.append({"kind": "delist_cash", "asset_id": asset, "quantity": qty, "amount": amount})
                    positions.pop(asset, None)
                    queued = [q for q in queued if q["asset_id"] != asset]
            for claim in claims:
                if claim["date"] <= day:
                    cash += claim["amount"]
                    day_cash_events.append({"kind": "dividend_pay", **claim})
            claims = [c for c in claims if c["date"] > day]
            for asset in positions:
                bar = dataset.bars.get((day, asset))
                if bar is None:
                    raise GateError("Held security needs a mark or a qualified delisting payout")
                last_marks[asset] = bar["open"]
            for order in queued:
                asset, requested = order["asset_id"], order["quantity"]
                bar = dataset.bars.get((day, asset))
                if not bar:
                    raise GateError("Order has no qualified execution-session raw price")
                mid = bar["open"]
                sign = 1 if requested > 0 else -1
                price = mid * (1 + sign * spec.transaction_bps / 10_000 * cost_multiplier)
                old = positions.get(asset, 0)
                # Constrain gaps using actual execution prices, while leaving the
                # requested quantity/signal independent of future information.
                maximum = min(abs(requested), max(0, math.floor(limits.position * previous_nav / price) - old) if requested > 0 and old >= 0 else abs(requested))

                def affordable(size):
                    q = sign * size
                    new = old + q
                    fee = max(spec.minimum_commission, spec.commission_per_share * size) * cost_multiplier if size else 0.0
                    next_cash = cash - q * price - fee
                    marks = {**last_marks, asset: mid}
                    proposed = {**positions, asset: new}
                    short = sum(-n * marks[a] for a, n in proposed.items() if n < 0)
                    long = sum(n * marks[a] for a, n in proposed.items() if n > 0)
                    reserved = sum(u["amount"] for u in unsettled) + max(0, -q * price)
                    available = next_cash - reserved - short * limits.short_collateral + sum(min(0, c["amount"]) for c in claims)
                    reducing = abs(new) <= abs(old) and new * old >= 0
                    min_cash = 0.0 if reducing else previous_nav * limits.cash_buffer
                    return next_cash >= 0 and available >= min_cash - 1e-8 and (long + short <= previous_nav * limits.gross + 1e-8 or reducing) and (abs(new)*mid <= previous_nav * limits.position + 1e-8 or reducing)

                size = maximum
                if not affordable(size):
                    low, high = 0, maximum
                    while low < high:
                        middle = (low + high + 1) // 2
                        if affordable(middle): low = middle
                        else: high = middle - 1
                    size = low
                qty = sign * size
                fee = max(spec.minimum_commission, spec.commission_per_share * size) * cost_multiplier if size else 0.0
                cash -= qty * price + fee
                positions[asset] = old + qty
                last_marks[asset] = mid
                if qty < 0:
                    unsettled.append({"date": dataset.sessions[day]["settlement_date"], "amount": -qty * price})
                fills.append({"session": day, "asset_id": asset, "requested": requested, "quantity": qty,
                              "raw_open": mid, "price": price, "commission": fee,
                              "slippage": abs(qty) * abs(price-mid), "asof": order["asof"], "reason": order["reason"]})
            positions = {a: q for a, q in positions.items() if q}
            for asset in positions:
                last_marks[asset] = dataset.bars[(day, asset)]["close"]
            market_value = sum(q * last_marks[a] for a, q in positions.items())
            receivables = sum(c["amount"] for c in claims)
            nav = cash + market_value + receivables
            if nav <= 0 or cash < -1e-8:
                raise GateError("Account became insolvent under the declared unlevered model")
            short = sum(-q * last_marks[a] for a, q in positions.items() if q < 0)
            unsettled_cash = sum(u["amount"] for u in unsettled)
            daily.append({"session": day, "nav": nav, "previous_nav": previous_nav, "cash": cash,
                          "positions": dict(positions), "opening_positions": opening_positions,
                          "marks": {a: last_marks[a] for a in positions}, "receivables": receivables,
                          "claims": [dict(c) for c in claims], "created_claims": created_claims,
                          "unsettled": unsettled_cash, "short_collateral": short * limits.short_collateral,
                          "available_cash": cash-unsettled_cash-short*limits.short_collateral+sum(min(0,c["amount"]) for c in claims),
                          "cash_events": day_cash_events, "borrow_fee": borrow_charge, "cash_interest": financing,
                          "reference_return": context["financing"]["reference_rate"] * elapsed / 365,
                          "return": nav/previous_nav-1,
                          "gross": sum(abs(q)*last_marks[a] for a,q in positions.items()) / nav})
            previous_nav, previous_day = nav, day
    finally:
        if worker: worker.close()
    return {"dataset_id": dataset.id, "strategy": asdict(artifact), "cost_multiplier": cost_multiplier,
            "daily": daily, "fills": fills, "targets": targets}
