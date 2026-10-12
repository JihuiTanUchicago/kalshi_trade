"""Real SDK object/callback compatibility with all sockets replaced by fixtures."""
from decimal import Decimal
from unittest.mock import patch
import importlib.util
import unittest

from quant_agent.common import GateError
from quant_agent.ibkr import IBKRPaperBroker


@unittest.skipUnless(importlib.util.find_spec("ibapi"),"Official SDK tests need the isolated agent environment")
class SDKTests(unittest.TestCase):
    def setUp(self):
        from ibapi.client import EClient
        def connect(client,*args): client.nextValidId(100);client.managedAccounts("DU999999")
        self.connect_patch=patch.object(EClient,"connect",connect);self.run_patch=patch.object(EClient,"run",lambda s:None)
        self.connect_patch.start();self.run_patch.start()
        self.broker=IBKRPaperBroker({"host":"127.0.0.1","port":4002,"client_id":71,"paper_account":"DU999999","contracts":{"S-A":{"con_id":12345}}})
    def tearDown(self): self.connect_patch.stop();self.run_patch.stop()
    def test_sdk_order_and_contract_are_paper_next_open(self):
        c=self.broker._contract("S-A");o=self.broker._order({"quantity":-10,"intent_id":"a"*64})
        self.assertEqual((c.conId,c.currency,c.secType),(12345,"USD","STK"))
        self.assertEqual((o.account,o.action,o.totalQuantity,o.orderType,o.tif),("DU999999","SELL",10,"MKT","OPG"))
    def test_sdk_what_if_callback_matches_margin_contract(self):
        from ibapi.order_state import OrderState
        req=101;o=self.broker._order({"quantity":10},True);state=OrderState();state.initMarginChange="1234.50"
        self.broker.client.openOrder(req,self.broker._contract("S-A"),o,state)
        self.assertEqual(self.broker.margin[req]["initial_margin_change"],"1234.50")
    def test_sdk_modern_error_callback_is_normalized(self):
        self.broker.client.error(3,123456789,502,"private broker text","")
        self.assertEqual(self.broker.errors,[(3,502)])
    def test_fractional_sdk_execution_is_rejected(self):
        from ibapi.execution import Execution
        e=Execution();e.acctNumber="DU999999";e.orderId=100;e.shares=Decimal("1.5")
        self.broker.client.execDetails(1,self.broker._contract("S-A"),e)
        self.assertIn((100,"fractional_execution"),self.broker.errors)
    def test_commission_and_fees_sdk_callback(self):
        from ibapi.commission_and_fees_report import CommissionAndFeesReport
        report=CommissionAndFeesReport();report.execId="id";report.commissionAndFees=1.25
        self.broker.executions["id"]={"commission":None}
        self.broker.client.commissionAndFeesReport(report)
        self.assertEqual(self.broker.executions["id"]["commission"],1.25)
    def test_live_gateway_port_is_rejected_before_socket(self):
        with self.assertRaises(GateError): IBKRPaperBroker({"host":"127.0.0.1","port":4001,"paper_account":"U999999"})
    def test_real_sdk_order_serializes_without_a_socket(self):
        from ibapi.client import EClient
        from ibapi.server_versions import MAX_CLIENT_VER
        class Connection:
            sent=[]
            def isConnected(self): return True
            def sendMsg(self,data): self.sent.append(data)
        self.broker.client.conn=Connection();self.broker.client.serverVersion_=MAX_CLIENT_VER
        self.broker.client.setConnState(EClient.CONNECTED)
        self.broker.client.placeOrder(101,self.broker._contract("S-A"),self.broker._order({"quantity":1,"intent_id":"a"*64}))
        self.assertTrue(self.broker.client.conn.sent);self.assertFalse(self.broker.errors)


if __name__=="__main__": unittest.main()
