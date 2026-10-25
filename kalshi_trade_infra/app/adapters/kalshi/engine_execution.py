"""The paper/live engine's entry sizing and order placement as a TradingLoop ``ExecutionPolicy``.

``EntryBudget`` is what the engine checks before every entry: the deployment's position slots, the
user's open-position and open-notional caps (read after this decision's exits have booked), the
live size ramp and the depth the book showed. It is a risk check (``budget.check``) and a sizer
(``budget.size``) over the same numbers, updated as entries book.

``KalshiEngineExecution`` sizes an entry with the budget and sends it through ``trade``: the
engine's MarketableLimitKernel call (paper over the simulated venue, demo and live over the real
one), which keeps every guard it has. Without a kernel (legacy paper) an order fills in full at its
limit price with the taker fee, exactly as ``engine._paper_buy`` / ``_paper_sell`` book it.
"""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Callable, Dict, Optional

from app import spec as specmod
from app.adapters.kalshi.convert import kalshi_order, to_domain_report
from data_pipeline.kalshi_fees import taker_fee_dollars
from trading_core.domain import ExecutionReport, Fill, Instrument, OrderIntent, Quote, RiskDecision, Side
from trading_core.ports import Book, Venue

# (action, side, ticker, qty, price, fair) -> the kernel's own-side report (contracts.ExecutionReport)
Trade = Callable[[str, str, str, int, float, Optional[float]], object]


class EntryBudget:
    """``load`` returns (open positions, open entry notional, position cap, notional cap) for the
    user, as ``engine._entry_caps`` does; it runs at the first entry, after the exits booked.
    ``stopped`` is true once an entry could not be paid for: no further entry this decision.
    The book calls ``took`` for every entry it books."""

    def __init__(self, book: Book, max_positions: int, load: Callable[[], tuple],
                 shown: Callable[[str, str], Optional[float]], ramp: Callable[[], float] = lambda: 1.0,
                 stopped: Callable[[], bool] = lambda: False) -> None:
        self.book, self.max_positions = book, int(max_positions)
        self._load, self._shown, self._ramp, self._stopped = load, shown, ramp, stopped
        self._caps: Optional[Dict] = None

    def _state(self) -> Dict:
        if self._caps is None:
            open_count, open_notional, cap_positions, cap_notional = self._load()
            self._caps = dict(open_count=open_count, open_notional=open_notional, cap_positions=cap_positions,
                              cap_notional=cap_notional, ramp=self._ramp())
        return self._caps

    def check(self, intent: OrderIntent) -> RiskDecision:
        if self._stopped():
            return RiskDecision.refuse("out_of_cash", "not enough cash for the last entry")
        held = {iid.symbol for iid in self.book.open_positions()}
        if len(held) >= self.max_positions:
            return RiskDecision.refuse("max_positions", "%d of %d slots used" % (len(held), self.max_positions))
        state = self._state()
        if state["open_count"] >= state["cap_positions"]:
            return RiskDecision.refuse("user_max_open_positions", "%d open >= %d" % (state["open_count"],
                                                                                  state["cap_positions"]))
        return RiskDecision.allow()

    def size(self, intent: OrderIntent) -> int:
        """Contracts for the entry's stake at its limit, ramped, capped at the shown depth and at the
        notional left under the user's cap. Below one contract means skip it."""
        state, price = self._state(), float(intent.limit_price)
        qty = specmod.contracts_for(intent.meta["stake"], price)
        if state["ramp"] < 1.0 and qty >= 1:
            qty = max(1, int(qty * state["ramp"]))  # live size ramp: a fresh live deployment trades small
        shown = self._shown(intent.instrument.symbol, intent.instrument.outcome)
        if shown is not None:
            qty = min(qty, int(shown))  # never size past the depth on the side we take
        room = state["cap_notional"] - state["open_notional"]
        return min(qty, int(room / price)) if room >= price else 0

    def took(self, intent: OrderIntent) -> None:
        """An entry booked: count it against the user caps at its requested size and limit (a short
        fill only over-counts, which is safe for a cap)."""
        state = self._state()
        state["open_count"] += 1
        state["open_notional"] += intent.qty * float(intent.limit_price)


class KalshiEngineExecution:
    def __init__(self, budget: EntryBudget, trade: Optional[Trade] = None) -> None:
        self.budget, self.trade = budget, trade

    def execute(self, intent: OrderIntent, instrument: Instrument, quote: Optional[Quote], venue: Venue,
                client_order_id: str, now: float) -> ExecutionReport:
        ticker, side = kalshi_order(intent.instrument)
        if intent.side is Side.BUY:
            qty = self.budget.size(intent)
            if qty < 1:
                return ExecutionReport(intent, "rejected", message="size below one contract")
            intent = replace(intent, qty=qty)
        qty, price = int(intent.qty), float(intent.limit_price)
        if self.trade is None:
            fill = Fill(intent.instrument, intent.side, qty, price, fee=taker_fee_dollars(qty, price), ts=now)
            return ExecutionReport(intent, "filled", [fill])
        report = self.trade(intent.side.value, side, ticker, qty, price, intent.fair_value)
        return to_domain_report(report, intent, ts=time.time())
