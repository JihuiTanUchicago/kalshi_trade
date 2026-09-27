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

    @staticmethod
    def _num(value, default: float = 0.0) -> float:
        """Kalshi v2 sends counts, prices and fees as fixed-point strings."""
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def execute(self, intent: TradeIntent) -> ExecutionReport:
        res = self._submitter(intent.ticker, intent.action, intent.side, intent.qty_contracts, intent.limit_price_dollars)
        resp = (res or {}).get("resp") or {}
        # The v2 create-order response is flat - there is no nested "order"
        # object, which is what this used to read. It therefore saw {} for
        # every order, defaulted the status to "submitted", and reported the
        # requested quantity at the requested price as though it had filled.
        # An immediate-or-cancel order that crosses nothing comes back with
        # fill_count "0.00" and no average_fill_price at all; believing those
        # were fills is what put phantom positions in the book on 2026-09-27.
        filled = int(self._num(resp.get("fill_count")))
        avg_px = self._num(resp.get("average_fill_price"))
        if filled > 0 and avg_px <= 0:
            # Filled but priced unreadably: the limit is the worst it can be,
            # so it is the honest fallback. Never the other way round.
            avg_px = float(intent.limit_price_dollars)
        order_id = resp.get("order_id")
        client_order_id = (res or {}).get("client_order_id")
        if filled <= 0:
            status = "unfilled"
        elif filled < int(intent.qty_contracts):
            status = "partially_filled"
        else:
            status = "filled"
        return ExecutionReport(
            accepted=filled > 0,
            status=status,
            fill_price_dollars=avg_px if filled > 0 else 0.0,
            fill_qty_contracts=filled,
            external_order_id=str(order_id) if order_id is not None else None,
            client_order_id=str(client_order_id) if client_order_id is not None else None,
            fee_dollars=self._num(resp.get("average_fee_paid")) * filled,
            raw_json=res or {},
        )
