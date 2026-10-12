"""Protected paper execution: persistent intents, reconciliation, fixed risk gates."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Protocol
import copy
import json

from .common import GateError, canonical, digest, finite, integer, timestamp, utcnow
from .contracts import Limits, StrategyArtifact
from .contracts import ResearchSpec
from .data import Dataset
from .sandbox import DockerSandbox
from .store import Store
from .strategy import plan_orders, reference_weights, validate_weights


class PaperBroker(Protocol):
    account: str
    def snapshot(self) -> dict: ...
    def borrow(self, asset_id: str) -> dict: ...
    def what_if(self, order: dict) -> dict: ...
    def submit(self, intent: dict) -> int: ...
    def cancel(self, broker_id: int): ...


class PaperController:
    def __init__(self, store: Store, broker: PaperBroker | None, paper_account: str, sandbox_image: str | None = None):
        if not paper_account.startswith("DU") or broker is not None and broker.account != paper_account:
            raise GateError("V1 requires the explicitly allowlisted DU paper account")
        self.store,self.broker,self.account,self.image = store,broker,paper_account,sandbox_image

    def qualify_release(self, run_id: str) -> str:
        run = self.store.run(run_id)
        if run["state"] not in {"decided","learned","finished"}:
            raise GateError("Strategy has not completed its research decision")
        decision = self.store.get(run["decision"],"decision")
        result = self.store.get(decision["result"],"experiment_result")
        challenge = self.store.get(decision["challenge"],"challenge")
        if not decision["paper_eligible"] or not decision["data_qualified"] or not all(decision["gates"].values()) or not challenge["passed"]:
            raise GateError("Strategy failed its fixed paper-qualification gates")
        receipt = self.store.get(result["qualification"]["receipt"],"data_qualification")
        if receipt["dataset_id"] != result["dataset_id"] or result["strategy"] != run["strategy"] or result["spec"] != run["spec"]:
            raise GateError("Paper receipt does not bind the exact data/specification/strategy")
        spec = self.store.get(run["spec"],"research_spec")
        mandate = self.store.control("operator_mandate",asdict(Limits()))
        cost_policy = self.store.control("operator_cost_policy",{"transaction_bps":5.0,"commission_per_share":0.005,"minimum_commission":1.0})
        if canonical(spec["limits"])!=canonical(mandate) or any(spec[k]!=v for k,v in cost_policy.items()):
            raise GateError("Research cannot relax the protected mandate/cost policy for paper execution")
        c = result["comparison"]
        drawdown_change = result["metrics"]["candidate_1"]["max_drawdown"]-result["metrics"]["baseline_1"]["max_drawdown"]
        if c["sharpe_gain"]<0.10 or c["lower_95_one_sided"]<=0 or c["block_length"]<21 or c["bootstrap_samples"]<2000 or drawdown_change>0.02 or result["stress_sharpe_gain"]<=0:
            raise GateError("Strategy failed the protected automatic paper criteria")
        payload = {"run":run_id,"decision":run["decision"],"strategy":run["strategy"],"spec":run["spec"],
                   "data_receipt":result["qualification"]["receipt"],"limits":spec["limits"],
                   "paper_account":self.account,"execution":"next_open","initial_state":{},"live":False}
        key = digest(payload)
        with self.store.db:
            self.store.db.execute("INSERT OR IGNORE INTO releases VALUES(?,?,0)",(key,canonical(payload)))
        return key

    def engineering_control(self,dataset: Dataset,asset_id: str,target_shares: int) -> str:
        """Operator-only one-share proof of paper infrastructure, with no alpha claim."""
        dataset.verify_unchanged()
        qualification = dataset.qualification(self.store)
        if not qualification["qualified"]: raise GateError("Engineering control still needs qualified data")
        snapshot = self._snapshot()
        if any(a!=asset_id or abs(q)>1 for a,q in snapshot["positions"].items()):
            raise GateError("Use a flat/dedicated one-share control account for engineering tests")
        artifact = StrategyArtifact("control",asset_id,20,target_shares=target_shares)
        if asset_id not in dataset.assets or target_shares<0 and dataset.assets[asset_id]["kind"]!="common_stock":
            raise GateError("Engineering shorts are limited to common stocks")
        limits = Limits()
        spec = ResearchSpec("Engineering-only paper order/round-trip test; not an economic strategy",dataset.id,
                            "equal_weight",dataset.days[20],dataset.days[-1],bootstrap_samples=100)
        payload = {"engineering_only":True,"alpha_claim":False,"strategy":self.store.put("strategy",asdict(artifact)),
                   "spec":self.store.put("research_spec",asdict(spec)),"data_receipt":qualification["receipt"],
                   "paper_account":self.account,"limits":asdict(limits),"live":False}
        key = digest(payload)
        with self.store.db: self.store.db.execute("INSERT OR IGNORE INTO releases VALUES(?,?,0)",(key,canonical(payload)))
        return key

    def _snapshot(self) -> dict:
        if self.broker is None: raise GateError("Broker execution worker is not connected")
        s = self.broker.snapshot()
        if s.get("account") != self.account or s.get("paper") is not True or s.get("complete") is not True:
            raise GateError("Broker identity or complete reconciliation snapshot is unavailable")
        age = (datetime.now(timestamp(s["asof"]).tzinfo)-timestamp(s["asof"])).total_seconds()
        if not -1<=age<=60:
            raise GateError("Broker snapshot is stale")
        for key in ("nav","cash","available_funds"): finite(s[key],key)
        if s["nav"] <= 0: raise GateError("Broker reports nonpositive NAV")
        if s.get("unmapped_positions") or s.get("foreign_orders"):
            raise GateError("Dedicated paper account has unmapped positions or foreign orders")
        return s

    def activate(self, release_id: str):
        row = self.store.db.execute("SELECT * FROM releases WHERE id=?",(release_id,)).fetchone()
        if not row: raise GateError("Unknown strategy release")
        payload = json.loads(row["payload"])
        if payload["paper_account"] != self.account: raise GateError("Release belongs to another account")
        current = self.store.db.execute("SELECT id FROM releases WHERE active=1").fetchone()
        if current and current[0] == release_id: return
        snapshot = self._snapshot()
        live_orders = [o for o in snapshot["orders"] if o["status"] not in {"Filled","Cancelled","ApiCancelled","Inactive"}]
        if live_orders or not current and any(snapshot["positions"].values()):
            raise GateError("First activation needs a flat account; transitions need reconciled positions and no pending orders")
        self.reconcile(snapshot)
        if self.unresolved(): raise GateError("Unresolved prior intents prevent activation")
        with self.store.transaction():
            self.store.db.execute("UPDATE releases SET active=0")
            self.store.db.execute("UPDATE releases SET active=1 WHERE id=?",(release_id,))
        if not current:
            self.store.set_control("paper_initial_positions",{})
            self.store.set_control("paper_initial_cash",snapshot["cash"])
            self.store.set_control("paper_activation_date",snapshot["asof"][:10])
        self.store.set_control("paper_pause",False)
        if not current:
            self.store.set_control("paper_peak_nav",snapshot["nav"])
            self.store.set_control("paper_last_nav",snapshot["nav"])
        self.store.event(None,"paper_activation",{"release":release_id,"account":self.account})

    def _guard_risk(self,snapshot: dict,limits: Limits):
        day = timestamp(snapshot["asof"]).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        frame = self.store.control("paper_day_nav",{})
        base = frame.get("base",snapshot["nav"]) if frame.get("day")==day else frame.get("last_nav",self.store.control("paper_last_nav",snapshot["nav"]))
        peak = max(self.store.control("paper_peak_nav",snapshot["nav"]),snapshot["nav"])
        if base-snapshot["nav"] > limits.capital*limits.daily_loss or peak-snapshot["nav"] > limits.capital*limits.drawdown:
            self.pause("Daily loss/drawdown protective limit")
            raise GateError("Paper account hit a protective limit")
        self.store.set_control("paper_day_nav",{"day":day,"base":base,"last_nav":snapshot["nav"]})
        self.store.set_control("paper_peak_nav",peak)
        self.store.set_control("paper_last_nav",snapshot["nav"])

    def poll(self) -> dict:
        snapshot = self._snapshot()
        reconciliation = self.reconcile(snapshot)
        active = self.store.db.execute("SELECT payload FROM releases WHERE active=1").fetchone()
        if active: self._guard_risk(snapshot,Limits(**json.loads(active[0])["limits"]))
        return {"snapshot":snapshot,"reconciliation":reconciliation,"paused":self.store.control("paper_pause",False)}

    def unresolved(self) -> list[str]:
        return [r[0] for r in self.store.db.execute("SELECT id FROM intents WHERE status IN ('sending','unknown')")]

    def reconcile(self, snapshot: dict | None = None) -> dict:
        snapshot = snapshot or self._snapshot()
        matched = 0
        for row in self.store.db.execute("SELECT * FROM intents").fetchall():
            orders = [o for o in snapshot["orders"] if o.get("intent_id") == row["id"]]
            identities = {o.get("broker_id") for o in orders}
            if len(identities) > 1:
                self.pause("Duplicate broker orders for one durable intent")
                raise GateError("Duplicate order identity; operator reconciliation required")
            if orders:
                o = orders[-1]
                filled = integer(o.get("filled",0),"filled quantity")
                expected = abs(json.loads(row["payload"])["quantity"])
                if filled > expected: raise GateError("Broker filled beyond the recorded intent")
                status = {"Filled":"filled","Cancelled":"cancelled","ApiCancelled":"cancelled","Inactive":"rejected"}.get(o["status"],"acknowledged")
                with self.store.db:
                    self.store.db.execute("UPDATE intents SET status=?,broker_id=?,perm_id=?,filled=? WHERE id=?",
                                          (status,o.get("broker_id"),o.get("perm_id"),filled,row["id"]))
                matched += 1
            for execution in snapshot.get("executions",[]):
                if execution.get("intent_id") != row["id"]: continue
                key = execution["execution_id"]
                quantity = integer(abs(execution["quantity"]),"execution quantity")
                intent = json.loads(row["payload"])
                if execution["quantity"]*intent["quantity"] <= 0 or execution.get("asset_id") != intent["asset_id"]:
                    raise GateError("Execution sign/security differs from durable intent")
                if quantity > abs(intent["quantity"]): raise GateError("Oversized execution")
                old = self.store.db.execute("SELECT payload FROM executions WHERE id=?",(key,)).fetchone()
                if old and json.loads(old[0]) != execution:
                    previous = json.loads(old[0])
                    if any(previous.get(k) != execution.get(k) for k in ("quantity","asset_id","price","intent_id")):
                        self.pause("Execution correction requires reconciliation")
                        raise GateError("Execution correction cannot be silently double-counted")
                with self.store.db:
                    self.store.db.execute("INSERT INTO executions VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                                          (key,row["id"],canonical(execution)))
            sum_filled = sum(abs(json.loads(r[0])["quantity"]) for r in self.store.db.execute("SELECT payload FROM executions WHERE intent_id=?",(row["id"],)))
            if sum_filled > abs(json.loads(row["payload"])["quantity"]):
                self.pause("Execution quantity exceeds intent")
                raise GateError("Execution ledger exceeded intent quantity")
            if sum_filled:
                current_status = self.store.db.execute("SELECT status FROM intents WHERE id=?",(row["id"],)).fetchone()[0]
                status = "filled" if sum_filled == abs(json.loads(row["payload"])["quantity"]) else current_status if current_status in {"cancelled","rejected"} else "acknowledged"
                with self.store.db:
                    self.store.db.execute("UPDATE intents SET status=?,filled=? WHERE id=?",(status,sum_filled,row["id"]))
        initial = self.store.control("paper_initial_positions")
        if initial is not None:
            expected = dict(initial)
            movements = []
            for row in self.store.db.execute("SELECT e.payload,i.payload FROM executions e JOIN intents i ON i.id=e.intent_id"):
                execution,intent = json.loads(row[0]),json.loads(row[1])
                movements.append((execution.get("session",intent["session"]),1,"fill",execution))
            for event in self.store.control("paper_actions",[]):
                movements.append((event["session"],0,event["kind"],event))
            for day,priority,kind,event in sorted(movements,key=lambda e:(e[0],e[1])):
                asset = event["asset_id"]
                if kind=="fill": expected[asset] = expected.get(asset,0)+event["quantity"]
                elif kind=="split":
                    qty = expected.get(asset,0)*event["value"]
                    if qty!=int(qty): raise GateError("Paper split needs cash-in-lieu reconciliation")
                    expected[asset] = int(qty)
                elif kind=="delist_cash": expected.pop(asset,None)
            expected = {a:q for a,q in expected.items() if q}
            actual = {a:q for a,q in snapshot["positions"].items() if q}
            if actual != expected:
                self.pause("Broker positions do not reconcile to executions and qualified actions")
                raise GateError("Paper positions failed independent reconciliation")
        self.store.event(None,"paper_reconciliation",{"matched":matched,"unresolved":self.unresolved(),
                               "cash_attribution":"pending independently imported broker statements"})
        return {"matched":matched,"unresolved":self.unresolved()}

    def submit_intent(self, intent: dict) -> str:
        if self.store.control("paper_pause",False): raise GateError("Paper execution is paused")
        row = self.store.db.execute("SELECT payload FROM releases WHERE id=? AND active=1",(intent.get("release"),)).fetchone()
        if not row or intent.get("account")!=self.account:
            raise GateError("Orders require an active qualification receipt for this paper account")
        preflight = self.store.get(intent.get("preflight",""),"paper_preflight")
        fields = {k:v for k,v in intent.items() if k not in {"account","release","session","preflight"}}
        if preflight["release"]!=intent["release"] or preflight["session"]!=intent["session"] or fields not in preflight["orders"]:
            raise GateError("Order differs from its protected preflight")
        integer(abs(intent["quantity"]),"intent quantity",1)
        # Preflight receipts can change after reconciliation; the logical intent
        # identity remains stable across those receipts.
        key = digest({k:v for k,v in intent.items() if k!="preflight"})
        with self.store.transaction():
            existing = self.store.db.execute("SELECT status FROM intents WHERE id=?",(key,)).fetchone()
            if existing and existing[0]!="planned": return key  # Never resubmit an acknowledged or uncertain intent.
            if not existing:
                self.store.db.execute("INSERT INTO intents(id,payload,status) VALUES(?,?,'planned')",(key,canonical(intent)))
            self.store.db.execute("UPDATE intents SET status='sending' WHERE id=? AND status='planned'",(key,))
        try:
            broker_id = self.broker.submit({**intent,"intent_id":key})
        except BaseException:
            with self.store.db: self.store.db.execute("UPDATE intents SET status='unknown' WHERE id=?",(key,))
            self.pause("Order acknowledgement is uncertain")
            raise GateError("Order acknowledgement is uncertain; reconcile before further orders") from None
        with self.store.db:
            self.store.db.execute("UPDATE intents SET status='acknowledged',broker_id=? WHERE id=?",(broker_id,key))
        return key

    def pause(self, reason: str):
        self.store.set_control("paper_pause",True)
        self.store.event(None,"paper_pause",{"reason":reason})
        for row in self.store.db.execute("SELECT broker_id FROM intents WHERE status IN ('acknowledged','sending','unknown') AND broker_id IS NOT NULL"):
            try: self.broker.cancel(row[0])
            except Exception: self.store.event(None,"cancel_uncertain",{"broker_id":row[0]})

    def resume(self):
        self.reconcile()
        if self.unresolved(): raise GateError("Unknown acknowledgements remain unresolved")
        self.store.set_control("paper_pause",False)

    def refresh_actions(self,dataset: Dataset):
        dataset.verify_unchanged()
        if not dataset.qualification(self.store)["qualified"]: raise GateError("Qualified current data is required for paper action adjustments")
        activation_day = self.store.control("paper_activation_date",utcnow()[:10])
        current_day = timestamp(utcnow()).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        actions = [a for day,rows in dataset.actions.items() if activation_day<=day<=current_day for a in rows if a["kind"] in {"split","delist_cash"}]
        self.store.set_control("paper_actions",actions)

    def cycle(self, dataset: Dataset, now: str | None = None) -> dict:
        active = self.store.db.execute("SELECT * FROM releases WHERE active=1").fetchone()
        if not active: raise GateError("No qualified active paper strategy")
        release = json.loads(active["payload"])
        if release["paper_account"] != self.account: raise GateError("Wrong paper account for active release")
        dataset.verify_unchanged()
        if not dataset.qualification(self.store)["qualified"]:
            raise GateError("Fresh paper inputs must pass source qualification")
        self.refresh_actions(dataset)
        snapshot = self._snapshot()
        self.reconcile(snapshot)
        if self.unresolved() or self.store.control("paper_pause",False):
            raise GateError("Paper execution paused or awaiting acknowledgement reconciliation")
        limits = Limits(**release["limits"])
        allocation_nav = min(snapshot["nav"],limits.capital)
        self._guard_risk(snapshot,limits)
        next_session = dataset.manifest.get("next_session")
        if not next_session: raise GateError("A reviewed upcoming exchange session is required")
        current = timestamp(now or utcnow())
        open_time = timestamp(next_session["open_at"])
        if not open_time-timedelta(minutes=60) <= current <= open_time-timedelta(minutes=3):
            raise GateError("Next-open orders require the configured pre-auction submission window")
        if dataset.days[-1] != next_session.get("previous_session"):
            raise GateError("Daily data does not reach the preceding completed exchange session")
        plan_key = f"paper_plan:{active['id']}:{next_session['session']}"
        old_plan = self.store.control(plan_key)
        if old_plan:
            # The entire batch was fixed and persisted before its first send.
            # Resume the original batch; never recalculate it from partially
            # filled positions and turn a recovery into an extra rebalance.
            receipt = self.store.get(old_plan,"paper_preflight")
            if receipt["dataset_id"]!=dataset.id:
                raise GateError("A paper session's frozen inputs cannot be replaced during recovery")
            remaining = []
            for order in receipt["orders"]:
                intent = {**order,"release":active["id"],"account":self.account,"session":next_session["session"],"preflight":old_plan}
                key = digest({k:v for k,v in intent.items() if k!="preflight"})
                row = self.store.db.execute("SELECT status FROM intents WHERE id=?",(key,)).fetchone()
                if row and row[0]=="planned": remaining.append(intent)
            if remaining:
                # Wait for prior sends to become terminal so their unsettled
                # buys cannot be spent a second time during batch recovery.
                if any(o["status"] not in {"Filled","Cancelled","ApiCancelled","Inactive"} for o in snapshot["orders"]):
                    raise GateError("Recover remaining orders after earlier sends become terminal")
                projected = dict(snapshot["positions"])
                margin_needed, buy_notional = 0.0,0.0
                for intent in remaining:
                    projected[intent["asset_id"]] = projected.get(intent["asset_id"],0)+intent["quantity"]
                    check = self.broker.what_if(intent)
                    if check.get("passed") is not True: raise GateError("Recovered order failed fresh broker margin preflight")
                    margin_needed += max(0,finite(check["initial_margin_change"],"recovery margin"))
                    buy_notional += max(0,intent["quantity"])*intent["expected_price"]*1.02+max(1,abs(intent["quantity"])*0.005)
                projected_short = 0.0
                for asset,quantity in projected.items():
                    if quantity>=0: continue
                    b = self.broker.borrow(asset)
                    if b.get("realtime") is not True or not -1<=(current-timestamp(b["asof"])).total_seconds()<=900 or integer(b["shares"],"recovery shortable shares")<-quantity or finite(b["fee_rate"],"recovery borrow fee")<0:
                        raise GateError("Recovered batch lacks current borrow preflight")
                    projected_short += -quantity*dataset.bars[(dataset.days[-1],asset)]["close"]
                cash_room = min(snapshot["cash"],finite(snapshot.get("settled_cash"),"settled paper cash"))-projected_short*limits.short_collateral-allocation_nav*limits.cash_buffer
                if margin_needed>snapshot["available_funds"]-allocation_nav*limits.cash_buffer or buy_notional>min(snapshot["available_funds"]-allocation_nav*limits.cash_buffer,cash_room):
                    raise GateError("Recovered batch exceeds conservative cash/margin limits")
            keys = []
            for order in receipt["orders"]:
                intent = {**order,"release":active["id"],"account":self.account,"session":next_session["session"],"preflight":old_plan}
                key = digest({k:v for k,v in intent.items() if k!="preflight"})
                row = self.store.db.execute("SELECT status FROM intents WHERE id=?",(key,)).fetchone()
                if row and row[0]=="planned":
                    keys.append(self.submit_intent(intent))
                else: keys.append(key)
            return {"session":next_session["session"],"intents":keys,"preflight":old_plan,"resumed_frozen_batch":True}
        artifact = StrategyArtifact(**self.store.get(release["strategy"],"strategy"))
        spec = self.store.get(release["spec"],"research_spec")
        context = dataset.context(len(dataset.days)-1,artifact.lookback,spec["allow_short"],spec.get("decision_delay_minutes",30))
        context.update({"positions":snapshot["positions"],"nav":allocation_nav,"limits":asdict(limits)})
        saved = self.store.control(f"paper_strategy_state:{active['id']}",{})
        if saved.get("asof") and timestamp(saved["asof"])>timestamp(context["asof"]):
            raise GateError("Paper input moved backwards in time")
        next_state = saved.get("state",{})
        if saved.get("asof")==context["asof"]:
            weights = saved["weights"]
        elif artifact.kind == "python":
            with DockerSandbox(artifact.code,self.image or "",initial_state=next_state) as worker:
                response = worker.step(context)
                weights = response["weights"]
                next_state = response["state"]
        else: weights = reference_weights(artifact,context)
        validate_weights(weights,context,limits,spec["allow_short"],snapshot["positions"])
        planning_context = copy.deepcopy(context)
        current_borrow = {}
        for asset in set(a for a,q in snapshot["positions"].items() if q<0) | set(a for a,w in weights.items() if w<0):
            b = self.broker.borrow(asset)
            age = (current-timestamp(b["asof"])).total_seconds()
            if not -1<=age<=900 or b.get("realtime") is not True or finite(b["fee_rate"],"current borrow fee")<0:
                raise GateError("Current broker borrow/fee evidence is stale, delayed or invalid")
            current_borrow[asset] = b
            if asset in planning_context["borrow"]:
                planning_context["borrow"][asset]["shares"] = min(planning_context["borrow"][asset]["shares"],integer(b["shares"],"current shortable shares"))
        orders = plan_orders(planning_context,snapshot["positions"],allocation_nav,weights,limits,artifact.buffer,spec["allow_short"])
        if snapshot["orders"] and any(o["status"] not in {"Filled","Cancelled","ApiCancelled","Inactive"} for o in snapshot["orders"]):
            raise GateError("Outstanding paper orders must reconcile before another cycle")
        margin_needed, buy_notional = 0.0,0.0
        for order in orders:
            asset = order["asset_id"]
            final = snapshot["positions"].get(asset,0)+order["quantity"]
            if final < 0:
                borrow = current_borrow[asset]
                if integer(borrow["shares"],"broker shortable shares") < -final or finite(borrow["fee_rate"],"broker borrow fee") < 0:
                    raise GateError("Broker borrow does not support the requested short")
                if -final*order["expected_price"]*limits.short_collateral > snapshot["cash"]-allocation_nav*limits.cash_buffer:
                    raise GateError("Paper short collateral exceeds conservative cash policy")
            risk = self.broker.what_if({**order,"account":self.account,"session":next_session["session"]})
            if risk.get("passed") is not True: raise GateError("Broker rejected margin/contract preflight")
            margin_needed += max(0,finite(risk["initial_margin_change"],"broker margin change"))
            buy_notional += max(0,order["quantity"])*order["expected_price"]*1.02+max(1,abs(order["quantity"])*0.005)
        projected = dict(snapshot["positions"])
        for order in orders: projected[order["asset_id"]] = projected.get(order["asset_id"],0)+order["quantity"]
        projected_short = sum(-q*context["history"][a][-1]["close"] for a,q in projected.items() if q<0)
        cash_room = min(snapshot["cash"],finite(snapshot.get("settled_cash"),"settled paper cash"))-projected_short*limits.short_collateral-allocation_nav*limits.cash_buffer
        if margin_needed > snapshot["available_funds"]-allocation_nav*limits.cash_buffer or buy_notional > min(snapshot["available_funds"]-allocation_nav*limits.cash_buffer,cash_room):
            raise GateError("Paper order batch exceeds conservative cash/margin limits")
        receipt = self.store.put("paper_preflight",{"release":active["id"],"session":next_session["session"],"asof":context["asof"],
                                "dataset_id":dataset.id,"orders":orders,"current_borrow":current_borrow,"snapshot":{"nav":snapshot["nav"],"available_funds":snapshot["available_funds"]}})
        self.store.set_control(f"paper_strategy_state:{active['id']}",{"asof":context["asof"],"weights":weights,"state":next_state})
        intents = [{**order,"release":active["id"],"account":self.account,"session":next_session["session"],"preflight":receipt} for order in orders]
        with self.store.transaction():
            for intent in intents:
                key = digest({k:v for k,v in intent.items() if k!="preflight"})
                self.store.db.execute("INSERT OR IGNORE INTO intents(id,payload,status) VALUES(?,?,'planned')",(key,canonical(intent)))
            self.store.db.execute("INSERT INTO controls VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(plan_key,canonical(receipt)))
        keys = []
        for intent in intents: keys.append(self.submit_intent(intent))
        return {"session":next_session["session"],"intents":keys,"preflight":receipt}
