"""Independent checks: this module does not import the simulator or planner."""
from __future__ import annotations

from datetime import date, timedelta
import math

from .common import GateError, canonical, timestamp
from .contracts import ResearchSpec
from .data import Dataset


def near(a: float, b: float, name: str, nav: float = 100_000, absolute: float = 0.01, relative: float = 1e-8):
    if not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > max(absolute, abs(nav)*relative):
        raise GateError(f"Independent ledger verification failed: {name}")


def verify_ledger(dataset: Dataset, spec: ResearchSpec, result: dict) -> dict:
    dataset.verify_unchanged()
    if result["dataset_id"] != dataset.id:
        raise GateError("Wrong dataset in ledger")
    cash, previous_nav = spec.limits["capital"], spec.limits["capital"]
    positions, claims, pending, marks = {}, [], [], {}
    multiplier = result["cost_multiplier"]
    fills_by_day = {}
    for fill in result["fills"]:
        fills_by_day.setdefault(fill["session"], []).append(fill)
    target_by_day = {t["session"]: t for t in result["targets"]}
    if len(target_by_day) != len(result["daily"]) or len(result["daily"]) < 2:
        raise GateError("Incomplete targets/daily ledger")
    previous_day = result["daily"][0]["session"]
    max_error = 0.0
    for row in result["daily"]:
        day = row["session"]
        prior = dataset.days[dataset.days.index(day)-1]
        if row["opening_positions"] != positions:
            raise GateError("Opening positions do not carry forward")
        if timestamp(target_by_day[day]["asof"]) != timestamp(dataset.sessions[prior]["close_at"])+timedelta(minutes=spec.decision_delay_minutes):
            raise GateError("Decision does not use the preceding completed session")
        f = dataset.financing[prior]
        if timestamp(f["available_at"]) > timestamp(target_by_day[day]["asof"]):
            raise GateError("Financing leakage")
        elapsed = (date.fromisoformat(day)-date.fromisoformat(previous_day)).days
        prior_short = sum(-q*marks[a] for a,q in positions.items() if q < 0)
        available = cash-sum(p["amount"] for p in pending)-prior_short*spec.limits["short_collateral"]+sum(min(0,c["amount"]) for c in claims)
        interest = max(0,available)*f["credit_rate"]*elapsed/365
        borrow = 0.0
        for a,q in positions.items():
            if q < 0:
                b = dataset.borrow.get((prior,a))
                if b is None or timestamp(b["available_at"]) > timestamp(target_by_day[day]["asof"]):
                    raise GateError("Missing as-of borrow evidence")
                borrow += -q*marks[a]*b["fee_rate"]*elapsed/365*multiplier
        near(row["cash_interest"], interest, "cash interest")
        near(row["borrow_fee"], borrow, "borrow fees")
        cash += interest-borrow
        pending = [p for p in pending if p["date"] > day]
        splits = {}
        for event in sorted(dataset.actions.get(day, []), key=lambda e:e["kind"] != "split"):
            a, value = event["asset_id"], event["value"]
            if event["kind"] == "split":
                quantity = positions.get(a,0)*value
                if quantity != int(quantity): raise GateError("Unsupported fractional split")
                positions[a] = int(quantity)
                splits[a] = splits.get(a,1.0)*value
            elif event["kind"] == "dividend" and positions.get(a,0):
                claims.append({"asset_id":a, "amount":positions[a]*value,"date":event["pay_date"]})
            elif event["kind"] == "delist_cash":
                cash += positions.get(a,0)*value
                positions.pop(a,None)
        for claim in claims:
            if claim["date"] <= day: cash += claim["amount"]
        claims = [c for c in claims if c["date"] > day]
        expected_orders = {o["asset_id"]: o for o in target_by_day[day]["orders"]}
        for fill in fills_by_day.get(day,[]):
            a, q = fill["asset_id"], fill["quantity"]
            if a not in expected_orders or q != int(q): raise GateError("Unexpected/fractional fill")
            requested = expected_orders[a]["quantity"] * splits.get(a,1.0)
            if fill["requested"] != requested or abs(q) > abs(requested) or q*requested < 0:
                raise GateError("Fill differs from its frozen order intent")
            if timestamp(fill["asof"]) >= timestamp(dataset.sessions[day]["open_at"]):
                raise GateError("Order uses execution-session information")
            raw = dataset.bars[(day,a)]["open"]
            sign = 1 if requested > 0 else -1
            price = raw*(1+sign*spec.transaction_bps/10_000*multiplier)
            fee = max(spec.minimum_commission, spec.commission_per_share*abs(q))*multiplier if q else 0.0
            near(fill["price"], price, "fill price")
            near(fill["raw_open"],raw,"raw execution price")
            near(fill["commission"],fee,"commission")
            near(fill["slippage"],abs(q)*abs(price-raw),"slippage")
            cash -= q*price+fee
            positions[a] = positions.get(a,0)+q
            if q < 0:
                pending.append({"date":dataset.sessions[day]["settlement_date"],"amount":-q*price})
        positions = {a:q for a,q in positions.items() if q}
        marks = {a:dataset.bars[(day,a)]["close"] for a in positions}
        if row["positions"] != positions or row["marks"] != marks or canonical(row["claims"]) != canonical(claims):
            raise GateError("Positions, raw marks or payable claims failed independent reconstruction")
        receivable = sum(c["amount"] for c in claims)
        nav = cash+sum(q*marks[a] for a,q in positions.items())+receivable
        max_error = max(max_error,abs(row["nav"]-nav),abs(row["cash"]-cash))
        near(row["nav"],nav,"NAV",nav)
        near(row["cash"],cash,"cash",nav)
        near(row["previous_nav"],previous_nav,"prior NAV",nav)
        near(row["receivables"],receivable,"receivables",nav)
        near(row["unsettled"],sum(p["amount"] for p in pending),"settlement",nav)
        near(row["short_collateral"],sum(-q*marks[a] for a,q in positions.items() if q<0)*spec.limits["short_collateral"],"short collateral",nav)
        near(row["return"],nav/previous_nav-1,"daily return",1,1e-12,1e-10)
        near(row["reference_return"],f["reference_rate"]*elapsed/365,"reference return",1,1e-12,1e-10)
        gross = sum(abs(q)*marks[a] for a,q in positions.items())/nav
        near(row["gross"],gross,"gross exposure",1,1e-12,1e-10)
        available_cash = cash-sum(p["amount"] for p in pending)-sum(-q*marks[a] for a,q in positions.items() if q<0)*spec.limits["short_collateral"]+sum(min(0,c["amount"]) for c in claims)
        near(row["available_cash"],available_cash,"available cash",nav)
        previous_nav,previous_day = nav,day
    return {"passed":True,"sessions":len(result["daily"]),"fills":len(result["fills"]),
            "max_cash_nav_error":max_error,"method":"independent raw-price/account reconstruction"}
