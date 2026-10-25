"""Pre-trade risk as an ordered chain of checks. Every check sees only the intent; state a rule
needs (the book, a halt flag) is bound when the rule is built, so the chain stays a plain list.

The exit invariant is not re-implemented here: ``RiskChain.check`` delegates to
``domain.first_refusal``, which lets every ``reduce_only`` intent through.
"""
from __future__ import annotations

from typing import Callable, Iterable, List, Mapping, Optional

from trading_core.domain import Instrument, InstrumentId, OrderIntent, Portfolio, RiskDecision, first_refusal
from trading_core.domain.risk import RiskCheck


class RiskChain:
    def __init__(self, checks: Iterable[RiskCheck] = ()) -> None:
        self.checks: List[RiskCheck] = list(checks)

    def check(self, intent: OrderIntent) -> Optional[RiskDecision]:
        """The first refusal, or None when the intent may go to execution."""
        return first_refusal(intent, self.checks)


def kill_switch(is_halted: Callable[[], bool], reason: str = "trading halted") -> RiskCheck:
    def check(intent: OrderIntent) -> RiskDecision:
        return RiskDecision.refuse("kill_switch", reason) if is_halted() else RiskDecision.allow()
    return check


def max_order_notional(limit: float, instruments: Mapping[InstrumentId, Instrument]) -> RiskCheck:
    """Refuse an entry whose qty x limit price x multiplier exceeds ``limit``. An entry with no limit
    price cannot be bounded, so it is refused too (fail closed)."""
    def check(intent: OrderIntent) -> RiskDecision:
        if intent.limit_price is None:
            return RiskDecision.refuse("max_order_notional", "entry has no limit price")
        inst = instruments.get(intent.instrument)
        notional = intent.qty * intent.limit_price * (inst.multiplier if inst else 1.0)
        if notional > limit:
            return RiskDecision.refuse("max_order_notional", "notional %.2f > %.2f" % (notional, limit))
        return RiskDecision.allow()
    return check


def max_position(limit: float, book: Portfolio) -> RiskCheck:
    """Refuse an entry that would take |position| in its instrument above ``limit`` units."""
    def check(intent: OrderIntent) -> RiskDecision:
        held = book.positions.get(intent.instrument)
        after = (held.qty if held else 0.0) + intent.side.sign * intent.qty
        if abs(after) > limit:
            return RiskDecision.refuse("max_position", "position %g > %g" % (abs(after), limit))
        return RiskDecision.allow()
    return check


def max_open_positions(limit: int, book: Portfolio) -> RiskCheck:
    """Refuse an entry into a new instrument once ``limit`` instruments are already held."""
    def check(intent: OrderIntent) -> RiskDecision:
        held = book.open_positions()
        if intent.instrument not in held and len(held) >= limit:
            return RiskDecision.refuse("max_open_positions", "%d open >= %d" % (len(held), limit))
        return RiskDecision.allow()
    return check
