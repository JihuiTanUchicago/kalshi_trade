"""The one trading loop backtest, paper and live share (ARCHITECTURE.md step 8).

    TradingLoop       clock -> quotes + features -> strategy -> risk -> execution -> book
    ExecutionPolicy   turns an approved intent into a priced order on a Venue (CrossTheTouch)
    RiskChain         ordered pre-trade checks; exits always pass (domain.first_refusal)
    QuoteFillVenue    a venue-neutral paper Venue: fills marketable limits at the touch, charges a FeeModel
    QuotingLoop       passive market making: rest quotes at the touch on a QuotingVenue, book their fills

Backtest = TradingLoop(FixedClock, replay feed, QuoteFillVenue or SimulatedVenue). Live = the same
loop with SystemClock, the live feed and the venue adapter. Only the plugged-in adapters differ.
"""
from trading_core.engine.execution import CrossTheTouch, ExecutionPolicy
from trading_core.engine.loop import ExitRule, StepResult, TradingLoop
from trading_core.engine.paper import QuoteFillVenue
from trading_core.engine.quoting import MakerConfig, QuotingLoop
from trading_core.engine.risk import (RiskChain, kill_switch, max_open_positions, max_order_notional, max_position,
                                     one_position_per_symbol)
from trading_core.engine.stops import position_stop

__all__ = [
    "CrossTheTouch", "ExecutionPolicy", "ExitRule", "MakerConfig", "QuoteFillVenue", "QuotingLoop", "RiskChain", "StepResult", "TradingLoop",
    "kill_switch", "max_open_positions", "max_order_notional", "max_position", "one_position_per_symbol",
    "position_stop",
]
