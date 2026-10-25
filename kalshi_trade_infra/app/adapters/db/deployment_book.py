"""One deployment's positions in ``app_positions``, behind trading_core's ``Book`` port.

The rows are the truth: they are read when the book is made and again after every booking, the
way the engine re-reads them between its exits and its entries. Booking itself goes through a
``Ledger`` the engine supplies (paper: ``_paper_book_buy`` / ``_paper_book_exit``; demo and live:
``_book_entry`` / ``_book_kernel_exit`` keyed to the order intent), the same functions the legacy
decision path calls, so a fill booked from the TradingLoop and one booked by the legacy path are
the same rows and the same ledger lines by construction.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Mapping, Optional, Protocol

from app.adapters.db.position_repository import open_positions
from app.adapters.kalshi.convert import instrument_id
from trading_core.domain import ExecutionReport, Instrument, InstrumentId, OrderIntent, Position, Side


class DuplicateRows(Exception):
    """Two open rows for one instrument. The Book port has one position per instrument, so the caller
    keeps such a deployment on the legacy path rather than guess which row an exit closes."""


class Ledger(Protocol):
    def cash(self) -> float:
        ...

    def buy(self, report: ExecutionReport) -> bool:
        """Book an entry report's fills; False when there was not enough cash and nothing was booked."""
        ...

    def sell(self, row: Dict, report: ExecutionReport) -> bool:
        """Book an exit report's fills against ``row``; True only when it closed the whole row."""
        ...


class DeploymentBook:
    def __init__(self, cur, deployment_id: int, ledger: Ledger,
                 read_rows: Callable[..., List[Dict]] = open_positions) -> None:
        self._cur, self.deployment_id, self.ledger, self._read_rows = cur, deployment_id, ledger, read_rows
        self.entries = 0          # entries booked through this book
        self.exits = 0            # rows fully closed through this book
        self.out_of_cash = False  # an entry was refused for cash; the engine stops entering this decision
        self.on_entry: Optional[Callable[[OrderIntent], None]] = None   # told each booked entry's intent
        self._rows: Dict[InstrumentId, Dict] = {}
        self.refresh()

    def refresh(self) -> None:
        rows: Dict[InstrumentId, Dict] = {}
        for row in self._read_rows(self._cur, self.deployment_id):
            iid = instrument_id(row["ticker"], row["side"])
            if iid in rows:
                raise DuplicateRows("deployment %s holds two open %s rows" % (self.deployment_id, iid))
            rows[iid] = row
        self._rows = rows

    @property
    def cash(self) -> float:
        return self.ledger.cash()

    @property
    def positions(self) -> Mapping[InstrumentId, Position]:
        return self.open_positions()

    def row(self, instrument: InstrumentId) -> Dict:
        """The open app_positions row behind a position."""
        return self._rows[instrument]

    def open_positions(self) -> Dict[InstrumentId, Position]:
        return {iid: Position(iid, qty=float(row["qty"]), avg_price=float(row["entry_price"]))
                for iid, row in self._rows.items()}

    def record(self, report: ExecutionReport, instruments: Mapping[InstrumentId, Instrument]) -> None:
        if not report.fills:
            return
        if report.intent.side is Side.SELL:
            if self.ledger.sell(self.row(report.intent.instrument), report):
                self.exits += 1
        else:
            if not self.ledger.buy(report):
                self.out_of_cash = True
                return
            self.entries += 1
            if self.on_entry is not None:
                self.on_entry(report.intent)
        self.refresh()

    def settle(self, instrument: InstrumentId, price: float) -> float:
        raise NotImplementedError("deployments settle in engine.settle_due, outside the decision loop")
