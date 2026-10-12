"""Lazy official-IBKR-SDK adapter. Gateway/account provisioning is external.

Read the setup guide before use. This module never signs into an account, chooses
an account automatically, or treats an orderRef as server-side idempotency.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time

from .common import GateError, finite, integer, timestamp, utcnow


class IBKRPaperBroker:
    def __init__(self, config: dict):
        self.account = config.get("paper_account","")
        if not self.account.startswith("DU") or config.get("port") != 4002 or config.get("host") not in {"127.0.0.1","localhost"}:
            raise GateError("V1 uses local IB Gateway paper port 4002 and an explicit DU account")
        self.config = config
        self.contracts = config.get("contracts",{})
        if not self.contracts: raise GateError("Configure verified stable-ID to IBKR conId mappings")
        conids = [integer(v["con_id"],"IBKR conId",1) for v in self.contracts.values()]
        if len(set(conids)) != len(conids): raise GateError("IBKR contract IDs must be unique")
        self.contracts = {k:{**v,"con_id":integer(v["con_id"],"IBKR conId",1)} for k,v in self.contracts.items()}
        try:
            from ibapi import get_version_string
            from ibapi.client import EClient
            from ibapi.wrapper import EWrapper
            from ibapi.contract import Contract
            from ibapi.order import Order
            from ibapi.execution import ExecutionFilter
        except ImportError:
            raise GateError("Official IBKR SDK is missing; install the version matching your Gateway from IBKR") from None
        if get_version_string()!="10.50.2":
            raise GateError("This adapter is pinned to official SDK 10.50.2; validate another version before changing the pin")
        self.Contract,self.Order,self.ExecutionFilter = Contract,Order,ExecutionFilter
        self.lock = threading.RLock()
        self.events = {k:threading.Event() for k in ("ready","accounts","summary","positions","orders","completed","executions")}
        self.next_id = None
        self.accounts = []
        self.errors = []
        self.orders = {}
        self.executions = {}
        self.summary = {}
        self.positions = {}
        self.margin = {}
        self.margin_events = {}
        self.market = {}
        self.market_events = {}
        self.market_types = {}
        outer = self

        class Client(EWrapper,EClient):
            def __init__(self): EWrapper.__init__(self); EClient.__init__(self,self)
            def nextValidId(self,orderId):
                with outer.lock: outer.next_id = max(orderId,outer.next_id or 0)
                outer.events["ready"].set()
            def managedAccounts(self,accountsList):
                outer.accounts = accountsList.split(",")
                outer.events["accounts"].set()
            def accountSummary(self,reqId,account,tag,value,currency):
                if account == outer.account and currency in {"USD","BASE"}: outer.summary[tag] = value
            def accountSummaryEnd(self,reqId): outer.events["summary"].set()
            def position(self,account,contract,position,avgCost):
                if account == outer.account:
                    q = float(position)
                    if q != int(q): outer.errors.append((0,"fractional_position"))
                    outer.positions[contract.conId] = int(q)
            def positionEnd(self): outer.events["positions"].set()
            def openOrder(self,orderId,contract,order,orderState):
                if order.whatIf:
                    outer.margin[orderId] = {"passed":not bool(getattr(orderState,"warningText","").strip()),
                                            "initial_margin_change":getattr(orderState,"initMarginChange","")}
                    if orderId in outer.margin_events: outer.margin_events[orderId].set()
                elif order.account == outer.account:
                    outer.orders[orderId] = {"broker_id":orderId,"perm_id":order.permId,"intent_id":order.orderRef,
                                            "status":orderState.status,"filled":0}
            def openOrderEnd(self): outer.events["orders"].set()
            def completedOrder(self,contract,order,orderState):
                if order.account == outer.account:
                    outer.orders[order.orderId] = {"broker_id":order.orderId,"perm_id":order.permId,"intent_id":order.orderRef,
                                                 "status":orderState.status,"filled":int(getattr(order,"filledQuantity",0))}
            def completedOrdersEnd(self): outer.events["completed"].set()
            def orderStatus(self,orderId,status,filled,remaining,avgFillPrice,permId,parentId,lastFillPrice,clientId,whyHeld,mktCapPrice):
                if orderId in outer.orders: outer.orders[orderId].update(status=status,filled=int(filled),perm_id=permId)
            def execDetails(self,reqId,contract,execution):
                if execution.acctNumber == outer.account:
                    mapping = {v["con_id"]:k for k,v in outer.contracts.items()}
                    shares = float(execution.shares)
                    if shares!=int(shares):
                        outer.errors.append((execution.orderId,"fractional_execution"));return
                    qty = int(shares)*(1 if execution.side == "BOT" else -1)
                    outer.executions[execution.execId] = {"execution_id":execution.execId,"intent_id":execution.orderRef,
                                                         "asset_id":mapping.get(contract.conId),"quantity":qty,
                                                         "price":float(execution.price),"commission":None}
            def execDetailsEnd(self,reqId): outer.events["executions"].set()
            def commissionReport(self,report):
                if report.execId in outer.executions: outer.executions[report.execId]["commission"] = float(report.commission)
            def commissionAndFeesReport(self,report):
                if report.execId in outer.executions: outer.executions[report.execId]["commission"] = float(report.commissionAndFees)
            def marketDataType(self,reqId,marketDataType): outer.market_types[reqId] = marketDataType
            def tickSize(self,reqId,tickType,size):
                from ibapi.ticktype import TickTypeEnum
                if tickType == TickTypeEnum.SHORTABLE_SHARES:
                    outer.market[reqId] = int(size)
                    if reqId in outer.market_events: outer.market_events[reqId].set()
            def error(self,reqId,*args):
                # SDK error callbacks differ across versions; do not persist the
                # broker's raw text/advanced rejection payload.
                code = args[1] if len(args)>=3 and isinstance(args[1],int) else args[0] if args else 0
                if code not in {2104,2106,2107,2108,2158}: outer.errors.append((reqId,code))

        self.client = Client()
        self.client.connect(config["host"],config["port"],integer(config.get("client_id",71),"client id",1))
        self.thread = threading.Thread(target=self.client.run,daemon=True)
        self.thread.start()
        self._wait("ready")
        self._wait("accounts")
        if self.account not in self.accounts:
            self.close()
            raise GateError("Allowlisted paper account was not reported by Gateway")

    def _wait(self,name,timeout=15):
        if not self.events[name].wait(timeout): raise GateError(f"IBKR snapshot/handshake timed out: {name}")

    def _id(self):
        with self.lock:
            result = self.next_id
            if result is None: raise GateError("IBKR has not allocated an order ID")
            self.next_id += 1
            return result

    def _contract(self,asset):
        if asset not in self.contracts: raise GateError("Security lacks a reviewed IBKR contract mapping")
        c = self.Contract()
        c.conId = self.contracts[asset]["con_id"]
        c.secType,c.currency,c.exchange = "STK","USD","SMART"
        return c

    def _order(self,intent,what_if=False):
        order = self.Order()
        order.account = self.account
        order.action = "BUY" if intent["quantity"] > 0 else "SELL"
        order.totalQuantity = abs(integer(abs(intent["quantity"]),"order quantity",1))
        order.orderType,order.tif = "MKT","OPG"
        order.orderRef = intent.get("intent_id","quant-agent-preflight")
        order.whatIf,order.transmit = what_if,True
        return order

    def snapshot(self) -> dict:
        for event in ("summary","positions","orders","completed","executions"): self.events[event].clear()
        self.positions,self.summary,self.orders = {},{},{}
        self.client.reqAccountSummary(9001,"All","NetLiquidation,TotalCashValue,SettledCash,AvailableFunds")
        self.client.reqPositions()
        self.client.reqAllOpenOrders()
        self.client.reqCompletedOrders(False)
        self.client.reqExecutions(9002,self.ExecutionFilter())
        for name in ("summary","positions","orders","completed","executions"): self._wait(name)
        self.client.cancelAccountSummary(9001)
        self.client.cancelPositions()
        reverse = {v["con_id"]:k for k,v in self.contracts.items()}
        unmapped = [c for c,q in self.positions.items() if q and c not in reverse]
        if self.errors: raise GateError(f"IBKR reported {len(self.errors)} unresolved API error(s); reconcile in Gateway")
        return {"account":self.account,"paper":True,"complete":True,"asof":utcnow(),
                "nav":finite(self.summary.get("NetLiquidation"),"broker NAV"),
                "cash":finite(self.summary.get("TotalCashValue"),"broker cash"),
                "settled_cash":finite(self.summary.get("SettledCash"),"broker settled cash"),
                "available_funds":finite(self.summary.get("AvailableFunds"),"broker available funds"),
                "positions":{reverse[c]:q for c,q in self.positions.items() if q and c in reverse},
                "unmapped_positions":unmapped,"orders":list(self.orders.values()),
                "foreign_orders":[o for o in self.orders.values() if o["status"] not in {"Filled","Cancelled","ApiCancelled","Inactive"} and (not o["intent_id"] or len(o["intent_id"]) != 64)],
                "executions":list(self.executions.values())}

    def borrow(self,asset_id: str) -> dict:
        path = self.config.get("borrow_fee_file")
        if not path: raise GateError("Provide current broker borrow-fee evidence; indicative shortability alone is insufficient")
        with open(path) as stream: fees = json.load(stream)
        record = fees[asset_id]
        if (datetime.now(timezone.utc)-timestamp(record["asof"])).total_seconds() > 900:
            raise GateError("Broker fee evidence is older than 15 minutes")
        req = self._id()
        self.market_events[req] = threading.Event()
        self.client.reqMarketDataType(1)
        self.client.reqMktData(req,self._contract(asset_id),"236",False,False,[])
        try:
            if not self.market_events[req].wait(10): raise GateError("Current broker shortable share count is unavailable")
            if self.market_types.get(req) != 1: raise GateError("Borrow data is not from a realtime market-data session")
            return {"asof":record["asof"],"shares":self.market[req],"fee_rate":finite(record["fee_rate"],"annual borrow fee"),"realtime":True}
        finally: self.client.cancelMktData(req)

    def what_if(self,order: dict) -> dict:
        req = self._id()
        self.margin_events[req] = threading.Event()
        self.client.placeOrder(req,self._contract(order["asset_id"]),self._order(order,True))
        if not self.margin_events[req].wait(15): raise GateError("IBKR what-if margin response timed out")
        result = self.margin[req]
        result["initial_margin_change"] = finite(result["initial_margin_change"],"broker initial margin change")
        return result

    def submit(self,intent: dict) -> int:
        req = self._id()
        self.client.placeOrder(req,self._contract(intent["asset_id"]),self._order(intent))
        # Socket submission does not prove acknowledgement. Require the order
        # identity in the callback; a timeout becomes a durable unknown intent.
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            if req in self.orders: return req
            time.sleep(0.05)
        raise GateError("IBKR order acknowledgement timeout")

    def cancel(self,broker_id: int):
        from ibapi.order_cancel import OrderCancel
        self.client.cancelOrder(broker_id,OrderCancel())

    def close(self):
        self.client.disconnect()
