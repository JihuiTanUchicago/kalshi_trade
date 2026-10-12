"""Statement-based cash/fee attribution and evidence-backed operational learning.

Inputs are operator-normalized broker exports, with raw source hashes preserved.
This verifies arithmetic/consistency, not authenticity of an operator's document.
"""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo
import json

from .common import GateError,canonical,digest,file_hash,finite,integer,timestamp,utcnow
from .data import Dataset
from .memory import Memory
from .paper import PaperController
from .store import Store


def record_close(controller: PaperController,dataset: Dataset) -> str:
    controller.refresh_actions(dataset)
    evidence = controller.poll()
    snapshot = evidence["snapshot"]
    day = timestamp(snapshot["asof"]).astimezone(ZoneInfo("America/New_York")).date().isoformat()
    session = dataset.sessions.get(day)
    if not session or timestamp(snapshot["asof"])<timestamp(session["close_at"]):
        raise GateError("A close receipt needs the current session's completed close and qualified data")
    key = controller.store.put("broker_close",snapshot)
    controller.store.set_control(f"paper_close:{controller.account}:{day}",key)
    return key


def _positions_before(store: Store,day: str,dataset: Dataset) -> dict:
    result = dict(store.control("paper_initial_positions",{}))
    events = []
    for row in store.db.execute("SELECT e.payload,i.payload FROM executions e JOIN intents i ON i.id=e.intent_id"):
        e,i = json.loads(row[0]),json.loads(row[1])
        session = e.get("session",i["session"])
        if session<day: events.append((session,1,"trade",e))
    for a in store.control("paper_actions",[]):
        if a["session"]<day: events.append((a["session"],0,a["kind"],a))
    for session,priority,kind,e in sorted(events,key=lambda x:(x[0],x[1])):
        a = e["asset_id"]
        if kind=="trade": result[a] = result.get(a,0)+e["quantity"]
        elif kind=="split": result[a] = result.get(a,0)*e["value"]
        elif kind=="delist_cash": result.pop(a,None)
    if any(q!=int(q) for q in result.values()): raise GateError("Fractional historical action needs explicit reconciliation")
    return {a:int(q) for a,q in result.items() if q}


def audit_statement(store: Store,statement: dict,source_file: Path,dataset: Dataset,paper_account: str) -> str:
    if not dataset.qualification(store)["qualified"]: raise GateError("Operational audit needs qualified historical action/raw-price evidence")
    if not paper_account.startswith("DU") or statement.get("account")!=paper_account or statement.get("currency")!="USD" or statement.get("complete_session") is not True:
        raise GateError("Statement must describe the full allowlisted USD paper session")
    if not source_file.is_file() or source_file.stat().st_size==0: raise GateError("Keep the original broker export as evidence")
    day = statement["session"]
    close_hash = store.control(f"paper_close:{paper_account}:{day}")
    if not close_hash: raise GateError("An independently recorded broker close is required")
    close = store.get(close_hash,"broker_close")
    positions = _positions_before(store,day,dataset)
    opening_positions = {a:integer(abs(q),"statement shares")*(1 if q>=0 else -1) for a,q in statement["opening_positions"].items() if q}
    if opening_positions!=positions: raise GateError("Statement opening positions disagree with the execution journal")
    cash = finite(statement["opening_cash"],"opening cash")
    prior = store.control(f"last_statement:{paper_account}")
    if prior:
        previous = store.get(prior,"operational_check")
        if previous["session"]>=day: raise GateError("Statements must be audited once in chronological order")
        if abs(cash-previous["closing_cash"])>0.01: raise GateError("Statement opening cash does not carry forward")
    elif store.control("paper_initial_cash") is not None and abs(cash-store.control("paper_initial_cash"))>0.01:
        raise GateError("First statement opening cash differs from the activation snapshot")
    executions = {}
    for row in store.db.execute("SELECT e.payload,i.payload FROM executions e JOIN intents i ON i.id=e.intent_id"):
        e,i = json.loads(row[0]),json.loads(row[1])
        if e.get("session",i["session"])==day: executions[e["execution_id"]]=e
    seen,trades,commissions = set(),set(),set()
    costs = {"commission":0.0,"borrow_fee":0.0,"interest":0.0,"dividend":0.0,"tax":0.0}
    weighted_slippage,notional = 0.0,0.0
    for event in statement["events"]:
        eid,kind = event["event_id"],event["kind"]
        if eid in seen: raise GateError("Duplicate statement cash activity")
        seen.add(eid)
        if event.get("currency","USD")!="USD": raise GateError("Foreign-currency cash needs a separate accounting model")
        amount = finite(event["amount"],"cash activity")
        asset = event.get("asset_id")
        if kind=="trade":
            execution_id = event["execution_id"]
            if execution_id in trades or execution_id not in executions: raise GateError("Unmatched/duplicate statement execution")
            execution = executions[execution_id]
            quantity = finite(event["quantity"],"trade quantity");price=finite(event["price"],"trade price")
            if quantity!=execution["quantity"] or asset!=execution["asset_id"] or abs(price-execution["price"])>1e-8 or abs(amount+quantity*price)>0.01:
                raise GateError("Statement trade differs from independent broker execution")
            trades.add(execution_id);positions[asset]=positions.get(asset,0)+int(quantity)
            raw=dataset.bars[(day,asset)]["open"]
            weighted_slippage += quantity*(price-raw);notional += abs(quantity)*raw
        elif kind=="commission":
            execution_id = event["execution_id"]
            execution = executions.get(execution_id)
            if execution_id in commissions or not execution or execution["commission"] is None or abs(amount+execution["commission"])>0.01:
                raise GateError("Commission is missing, duplicate or inconsistent with broker fee callback")
            commissions.add(execution_id);costs[kind]+=amount
        elif kind=="split":
            action = next((a for a in dataset.actions.get(day,[]) if a["asset_id"]==asset and a["kind"]=="split"),None)
            if not action or event["ratio"]!=action["value"] or amount!=0: raise GateError("Unqualified split adjustment")
            quantity=positions.get(asset,0)*event["ratio"]
            if quantity!=int(quantity): raise GateError("Fractional statement action needs cash-in-lieu support")
            positions[asset]=int(quantity)
        elif kind=="delist_cash":
            action=next((a for a in dataset.actions.get(day,[]) if a["asset_id"]==asset and a["kind"]=="delist_cash"),None)
            if not action or abs(amount-positions.get(asset,0)*action["value"])>0.01: raise GateError("Delisting cash is unsupported by qualified evidence")
            positions.pop(asset,None)
        elif kind=="dividend":
            ex_date=event["ex_date"]
            action=next((a for a in dataset.actions.get(ex_date,[]) if a["asset_id"]==asset and a["kind"]=="dividend"),None)
            held=_positions_before(store,ex_date,dataset).get(asset,0)
            for a in dataset.actions.get(ex_date,[]):
                if a["asset_id"]==asset and a["kind"]=="split": held*=a["value"]
            if not action or action["pay_date"]!=day or abs(amount-held*action["value"])>0.01: raise GateError("Dividend payment is inconsistent with entitlement/pay-date evidence")
            costs[kind]+=amount
        elif kind in {"borrow_fee","interest","tax"}:
            if kind in {"borrow_fee","tax"} and amount>0: raise GateError("Expense sign is inconsistent")
            costs[kind]+=amount
        else:
            raise GateError("Unattributed cash activity/transfer blocks operational acceptance")
        cash += amount
    if trades!=set(executions) or commissions!=set(executions): raise GateError("Statement omits broker executions or fees")
    positions={a:q for a,q in positions.items() if q}
    if positions!=statement["closing_positions"] or positions!=close["positions"]: raise GateError("Closing statement/API positions disagree")
    if abs(cash-finite(statement["closing_cash"],"closing cash"))>0.01 or abs(cash-close["cash"])>0.01:
        raise GateError("Statement cash does not reconcile to movements and broker close")
    receipt=store.put("operational_check",{"passed":True,"quality":"operational","account":paper_account,"session":day,
                      "closing_cash":cash,"closing_positions":positions,"source_sha256":file_hash(source_file),
                      "normalized_statement_hash":digest(statement),"broker_close":close_hash,"dataset_id":dataset.id,
                      "cash_attributed":True,"fees_matched":True,"cost_components":costs,
                      "observed_open_slippage_bps":weighted_slippage/notional*10_000 if notional else None,
                      "strategy_alpha":False,"cash_activity_complete":True})
    store.set_control(f"last_statement:{paper_account}",receipt)
    Memory(store).add(receipt,[{"pointer":"/cash_attributed","equals":True}],"operational_attribution",
                      {"market":"US","frequency":"daily","quality":"operational"})
    return receipt
