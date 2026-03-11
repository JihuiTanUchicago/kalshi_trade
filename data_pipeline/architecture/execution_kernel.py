from typing import Callable

from data_pipeline.architecture.contracts import ExecutionReport, TradeIntent


class DummyExecutionKernel:
    """
    Bypass execution kernel for MVP.
    It does not optimize routing/slicing/queue position; it forwards the
    limit order intent to the provided submitter and returns a normalized report.
    """

    def __init__(self, submitter: Callable[[str, str, str, int, float], dict]):
        self._submitter = submitter

    def execute(self, intent: TradeIntent) -> ExecutionReport:
        res = self._submitter(intent.ticker, intent.action, intent.side, intent.qty_contracts, intent.limit_price_dollars)
        order = (res or {}).get("resp", {}).get("order", {})
        status = str(order.get("status", "submitted"))
        order_id = order.get("order_id")
        client_order_id = (res or {}).get("client_order_id")
        accepted = status not in {"rejected", "cancelled", "canceled", "error"}
        return ExecutionReport(
            accepted=accepted,
            status=status,
            fill_price_dollars=float(intent.limit_price_dollars),
            fill_qty_contracts=int(intent.qty_contracts),
            external_order_id=str(order_id) if order_id is not None else None,
            client_order_id=str(client_order_id) if client_order_id is not None else None,
            raw_json=res or {},
        )
