"""One decision slot, the same in backtest, paper and live.

    settle   every held instrument past expiry whose settlement price is known
    quotes   = feed.quotes(universe), with every FeatureProvider's features merged onto each quote
    exits    every exit rule (a position stop) sells at this step's quotes, ahead of the strategy
    pending  with ``next_step_fills``, last step's intents execute now: exits, then entries
    intents  = strategy.decide(DecisionContext(now, instruments, quotes, positions, capital))
    for each intent: risk.check (exits always pass) -> execution.execute -> book.apply(fills),
             or, with ``next_step_fills``, queue it for the next step's quotes (decide on bar t,
             fill on bar t+1: the latency a live order has). An unfilled exit keeps resting until
             ``pending_ttl`` seconds; an entry gets one chance.

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

# (book, quotes, now) -> exits to send now. Portfolio-level rules the strategy cannot opt out of.
ExitRule = Callable[[Portfolio, Mapping[InstrumentId, Quote], float], Sequence[OrderIntent]]


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
                 universe: Optional[Callable[[float], Iterable[InstrumentId]]] = None,
                 exit_rules: Sequence[ExitRule] = (), next_step_fills: bool = False,
                 pending_ttl: float = float("inf")) -> None:
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
        self.exit_rules = list(exit_rules)
        self.next_step_fills = next_step_fills
        self.pending_ttl = pending_ttl
        self._pending: List[Tuple[float, OrderIntent]] = []   # (decided at, intent)
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

    def _execute(self, intent: OrderIntent, quotes: Mapping[InstrumentId, Quote], now: float,
                 result: StepResult) -> Optional[ExecutionReport]:
        refusal = self.risk.check(intent)
        if refusal is not None:
            result.refused.append((intent, refusal))
            return None
        inst = self.instruments[intent.instrument]
        report = self.execution.execute(intent, inst, quotes.get(intent.instrument), self.venue,
                                        self._client_order_id(now), now)
        for fill in report.fills:
            self.book.apply(fill, multiplier=self.instruments[fill.instrument].multiplier)
        result.reports.append(report)
        if self._on_report is not None:
            self._on_report(report)
        return report

    def _held(self, iid: InstrumentId) -> bool:
        pos = self.book.positions.get(iid)
        return pos is not None and not pos.is_flat

    def _run_pending(self, quotes: Mapping[InstrumentId, Quote], now: float, result: StepResult) -> None:
        due = [p for p in self._pending if p[1].reduce_only] + [p for p in self._pending if not p[1].reduce_only]
        self._pending = []
        for decided, intent in due:
            if now - decided > self.pending_ttl:
                continue                                  # stale: the strategy decides afresh
            if intent.reduce_only and not self._held(intent.instrument):
                continue                                  # settled or stopped while resting
            report = self._execute(intent, quotes, now, result)
            if intent.reduce_only and (report is None or not report.fills):
                self._pending.append((decided, intent))   # an exit rests until it fills or goes stale

    def step(self) -> StepResult:
        now = self.clock.now()
        result = StepResult(now)
        self._settle(now, result)
        quotes = self._quotes(now)
        for rule in self.exit_rules:
            for intent in rule(self.book, quotes, now):
                self._execute(intent, quotes, now, result)
        if self.next_step_fills:
            self._run_pending(quotes, now, result)
        capital = self._capital() if self._capital is not None else self.book.cash
        ctx = DecisionContext(now=now, instruments=self.instruments, quotes=quotes,
                              positions=self.book.open_positions(), capital=capital)
        resting = {i.instrument for _, i in self._pending if i.reduce_only}
        result.intents = [i for i in self.strategy.decide(ctx) if not (i.reduce_only and i.instrument in resting)]
        for intent in result.intents:
            if self.next_step_fills:
                self._pending.append((now, intent))
            else:
                self._execute(intent, quotes, now, result)
        return result
