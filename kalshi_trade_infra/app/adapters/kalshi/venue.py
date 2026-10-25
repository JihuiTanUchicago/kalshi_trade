"""Kalshi binaries as a ``trading_core.ports.Venue``.

One adapter serves live, demo and paper, because they differ only in the submitter:

    live    KalshiBinaryVenue(timed(guarded(position_guarded(order_submitter(creds), net))), net)
    paper   KalshiBinaryVenue.simulated(feed)   # data_pipeline.architecture.SimulatedVenue

The submitter keeps every guard it has today; this class only translates. Wire translation (the
YES-only book) and fill parsing go through ``execution_kernel.own_side_fill``, the same function
MarketableLimitKernel uses, so the adapter cannot drift from the live kernel on money direction.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, Mapping, Optional, Sequence

from app.adapters.kalshi.convert import VENUE, kalshi_order, to_domain_report, to_trade_intent
from data_pipeline.architecture.contracts import ExecutionReport as KalshiReport
from data_pipeline.architecture.execution_kernel import own_side_fill
from data_pipeline.architecture.simulated_venue import SimulatedVenue
from trading_core.domain import ExecutionReport, InstrumentId, InstrumentKind, OrderIntent
from trading_core.ports import VenueCapabilities

Submitter = Callable[..., dict]


class KalshiBinaryVenue:
    def __init__(self, submitter: Submitter, read_net: Optional[Callable[[str], int]] = None,
                 read_cash: Optional[Callable[[], Optional[float]]] = None, *,
                 sends_real_orders: bool = True, name: str = VENUE) -> None:
        self.name = name
        self.capabilities = VenueCapabilities(kinds=frozenset({InstrumentKind.BINARY}), market_orders=False,
                                              shorting=False, fractional_qty=False,
                                              sends_real_orders=sends_real_orders)
        self._submit = submitter
        self._read_net = read_net
        self._read_cash = read_cash

    @classmethod
    def simulated(cls, feed, max_quote_age_seconds: float = 2.0,
                  positions: Optional[Dict[str, int]] = None) -> "KalshiBinaryVenue":
        sim = SimulatedVenue(feed, max_quote_age_seconds=max_quote_age_seconds, positions=positions)
        return cls(sim, read_net=sim.net_position, sends_real_orders=False, name="kalshi-sim")

    def submit(self, intent: OrderIntent, limit_price: float, client_order_id: str) -> ExecutionReport:
        kalshi_order(intent.instrument)  # refuse a non-Kalshi instrument before anything is sent
        ti = to_trade_intent(intent, limit_price)
        qty = int(ti.qty_contracts)
        res = self._submit(ti.ticker, ti.action, ti.side, qty, float(limit_price), client_order_id=client_order_id)
        report, fill_px, _ = own_side_fill(ti, res, float(limit_price), qty)
        own = KalshiReport(accepted=report.accepted, status=report.status, fill_price_dollars=fill_px,
                           fill_qty_contracts=report.fill_qty_contracts,
                           external_order_id=report.external_order_id, client_order_id=report.client_order_id,
                           fee_dollars=report.fee_dollars, raw_json=report.raw_json)
        return to_domain_report(own, intent, ts=time.time())

    def net_position(self, instrument: InstrumentId) -> float:
        """Kalshi nets one YES leg per ticker (+ YES, - NO); a NO instrument holds its negation."""
        ticker, side = kalshi_order(instrument)
        if self._read_net is None:
            raise RuntimeError("%s venue has no position reader wired" % self.name)
        net = int(self._read_net(ticker))
        return float(net if side == "yes" else -net)

    def cash(self) -> Optional[float]:
        return self._read_cash() if self._read_cash else None

    def lookup(self, client_order_ids: Sequence[str]) -> Mapping[str, ExecutionReport]:
        # Crash recovery stays in app.engine.recover_sent_intents until the engine moves (step 8).
        return {}
