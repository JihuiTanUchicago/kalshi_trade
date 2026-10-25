"""One decision slot, the same in backtest, paper and live.

    settle   every held instrument past expiry whose settlement price is known
    quotes   = feed.quotes(universe), with every FeatureProvider's features merged onto each quote
    intents  = strategy.decide(DecisionContext(now, instruments, quotes, positions, capital))
    for each intent: risk.check (exits always pass) -> execution.execute -> book.apply(fills)

The loop owns no I/O: the clock, feed, venue, providers and the ``on_report`` sink are adapters.
The book here is the strategy's own view (its fills); the venue's book is the exchange truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from trading_core.domain import ExecutionReport, Instrument, InstrumentId, OrderIntent, Portfolio, Quote, RiskDecision
from trading_core.engine.execution import CrossTheTouch, ExecutionPolicy
from trading_core.engine.risk import RiskChain
from trading_core.ports.clock import Clock
from trading_core.ports.features import FeatureProvider
from trading_core.ports.market_data import MarketDataFeed
from trading_core.ports.settlement import SettlementSource
from trading_core.ports.strategy import DecisionContext, Strategy
from trading_core.ports.venue import Venue


@dataclass
class StepResult:
    now: float
    intents: List[OrderIntent] = field(default_factory=list)
    reports: List[ExecutionReport] = field(default_factory=list)
    refused: List[Tuple[OrderIntent, RiskDecision]] = field(default_factory=list)
    settled: List[Tuple[InstrumentId, float, float, float]] = field(default_factory=list)  # id, qty, avg, price


class TradingLoop:
    def __init__(self, strategy: Strategy, instruments: Mapping[InstrumentId, Instrument], feed: MarketDataFeed,
                 venue: Venue, clock: Clock, *, execution: Optional[ExecutionPolicy] = None,
                 risk: Optional[RiskChain] = None, features: Sequence[FeatureProvider] = (),
                 book: Optional[Portfolio] = None, capital: Optional[Callable[[], float]] = None,
                 on_report: Optional[Callable[[ExecutionReport], None]] = None,
                 settlement: Optional[SettlementSource] = None,
                 universe: Optional[Callable[[float], Iterable[InstrumentId]]] = None) -> None:
        self.strategy, self.instruments = strategy, dict(instruments)
        self.feed, self.venue, self.clock = feed, venue, clock
        self.execution = execution or CrossTheTouch()
        self.risk = risk or RiskChain()
        self.features = list(features)
        self.book = book if book is not None else Portfolio()
        self._capital = capital
        self._on_report = on_report
        self.settlement = settlement
        self._universe = universe         # the instruments live at ``now`` (contracts roll); None = all
        self._seq = 0

    def _settle(self, now: float, result: StepResult) -> None:
        if self.settlement is None:
            return
        for iid, pos in list(self.book.open_positions().items()):
            inst = self.instruments[iid]
            if inst.expiry is None or inst.expiry.timestamp() > now:
                continue
            price = self.settlement.settlement_price(inst)
            if price is not None:
                result.settled.append((iid, pos.qty, pos.avg_price, price))
                self.book.settle(iid, price)

    def _quotes(self, now: float) -> Dict[InstrumentId, Quote]:
        live = list(self._universe(now)) if self._universe is not None else list(self.instruments)
        quotes = dict(self.feed.quotes(live))
        for provider in self.features:
            extra = provider.features([self.instruments[i] for i in live], now)
            for iid, values in extra.items():
                if iid in quotes and values:
                    quotes[iid] = replace(quotes[iid], features={**quotes[iid].features, **values})
        return quotes

    def _client_order_id(self, now: float) -> str:
        self._seq += 1
        return "%s-%d-%d" % (self.strategy.strategy_id, int(now), self._seq)

    def step(self) -> StepResult:
        now = self.clock.now()
        result = StepResult(now)
        self._settle(now, result)
        quotes = self._quotes(now)
        capital = self._capital() if self._capital is not None else self.book.cash
        ctx = DecisionContext(now=now, instruments=self.instruments, quotes=quotes,
                              positions=self.book.open_positions(), capital=capital)
        result.intents = list(self.strategy.decide(ctx))
        for intent in result.intents:
            refusal = self.risk.check(intent)
            if refusal is not None:
                result.refused.append((intent, refusal))
                continue
            inst = self.instruments[intent.instrument]
            report = self.execution.execute(intent, inst, quotes.get(intent.instrument), self.venue,
                                            self._client_order_id(now), now)
            for fill in report.fills:
                self.book.apply(fill, multiplier=inst.multiplier)
            result.reports.append(report)
            if self._on_report is not None:
                self._on_report(report)
        return result
