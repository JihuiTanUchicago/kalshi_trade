"""Pre-trade risk decisions and the one invariant every rule shares: an exit is never blocked.

That invariant lives in ``app/execution/guard.py`` and ``position_guard.py`` today, once per
guard; here it is enforced once for every rule, so a new rule cannot forget it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from trading_core.domain.orders import OrderIntent


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    rule: str = ""
    reason: str = ""

    @classmethod
    def allow(cls) -> "RiskDecision":
        return cls(True)

    @classmethod
    def refuse(cls, rule: str, reason: str) -> "RiskDecision":
        return cls(False, rule, reason)


RiskCheck = Callable[[OrderIntent], RiskDecision]


def first_refusal(intent: OrderIntent, checks: Iterable[RiskCheck]) -> Optional[RiskDecision]:
    """Run checks in order; return the first refusal, or None when the intent may proceed.

    A ``reduce_only`` intent skips every check: getting flat must always be possible.
    """
    if intent.reduce_only:
        return None
    for check in checks:
        decision = check(intent)
        if not decision.allowed:
            return decision
    return None
