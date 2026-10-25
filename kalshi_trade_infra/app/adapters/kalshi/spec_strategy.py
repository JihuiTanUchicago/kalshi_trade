"""A research spec (the ``app.spec`` DSL) as a ``trading_core.ports.Strategy``, plus the replay that
runs it through ``trading_core.engine.TradingLoop`` (ARCHITECTURE.md step 8b).

``simulate_on_loop`` is the parity harness: on the same dataset it must produce the same trades as
``app.backtest.simulate`` under either fill model. ``next_bar`` (the default there) decides on bar t
and fills on bar t+1 within the reservation price, capped at the displayed size, with the position
stop ahead of every exit; ``signal_bar`` fills at the signalling quote. Once parity holds on real
data, the backtest can move onto the loop, then paper, then live, and all three run one code path.
Not covered yet: code specs, cross-contract pairs, pooled datasets and what-if slippage (each gets
its own parity test before it moves).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from app import spec as specmod
from app.adapters.kalshi import instruments as ki
from app.adapters.kalshi.convert import instrument_id
from app.adapters.kalshi.fees import KalshiBinaryFees
from app.markets import Contract, Snapshot
from data_pipeline.architecture.execution_kernel import reservation_price
from trading_core.domain import ExecutionReport, Instrument, InstrumentId, OrderIntent, Portfolio, Quote, Side
from trading_core.engine import (CrossTheTouch, QuoteFillVenue, RiskChain, TradingLoop, max_open_positions,
                                 one_position_per_symbol, position_stop)
from trading_core.ports import DecisionContext, FeeModel, FixedClock, ScaledFees, Venue


class SpecStrategy:
    """Exits first (each held contract checked against ``spec.exit_signal`` at its own bid), then
    entries (``spec.entries``, best edge first) up to ``max_positions``, one position per ticker.

    ``next_bar=True`` emits for a fill on the next bar: exits carry no limit (they take that bar's
    bid), entries carry their stake and fair value for ``KalshiNextBarFill`` to size and cap at fill
    time, and the position count and one-per-ticker rules are enforced at fill time by the risk
    chain instead of here, exactly where the legacy backtest enforces them.

    ``slippage`` (a backtest cost what-if) sizes same-bar entries at the price they will really pay,
    the ask plus that much, as ``backtest.simulate`` does; the venue charges it on the fill."""

    def __init__(self, spec: Dict, contracts: Mapping[str, Contract], *, stake: Optional[float] = None,
                 entry_until: float = float("inf"), strategy_id: str = "spec", next_bar: bool = False,
                 slippage: float = 0.0, frame: Optional[Callable[[], Mapping[str, Snapshot]]] = None) -> None:
        if specmod.is_code_spec(spec) or spec.get("cross") or specmod.is_perpetual_spec(spec):
            raise ValueError("SpecStrategy runs single-contract DSL specs only")
        self.spec, self.contracts, self.strategy_id = spec, contracts, strategy_id
        self.stake = spec["sizing"]["stake"] if stake is None else stake
        self.max_positions = spec["sizing"]["max_positions"]
        self.entry_until = entry_until
        self.next_bar = next_bar
        self.slippage = slippage
        self.frame = frame

    def _snapshots(self, quotes: Mapping[InstrumentId, Quote]) -> Dict[str, Snapshot]:
        """The legacy YES snapshots, in feed order (entries breaks edge ties by input order). A replay
        that already holds them passes ``frame`` (the snapshots its quotes were made from, no feature
        providers in between) and skips rebuilding them from the quotes on every bar."""
        if self.frame is not None:
            return self.frame()
        return {iid.symbol: Snapshot(self.contracts[iid.symbol], int(q.ts), q.bid or 0.0, q.ask, q.features)
                for iid, q in quotes.items() if iid.outcome == "yes" and q.ask is not None}

    def decide(self, ctx: DecisionContext) -> Sequence[OrderIntent]:
        snaps = self._snapshots(ctx.quotes)
        exits, exiting = [], set()
        for iid, pos in ctx.positions.items():
            snap = snaps.get(iid.symbol)
            sig = specmod.exit_signal(self.spec, iid.outcome, pos.avg_price, snap) if snap else None
            if sig is not None:
                reason, price = sig
                exits.append(OrderIntent(iid, Side.SELL, pos.qty, limit_price=None if self.next_bar else price,
                                         reduce_only=True, strategy_id=self.strategy_id, reason=reason))
                exiting.add(iid)
        if ctx.now >= self.entry_until:
            return exits
        open_n = len(ctx.positions) - len(exiting)
        # Same-bar fills free a ticker the moment it exits; next-bar exits still hold it until they fill.
        held = {iid.symbol for iid in ctx.positions if self.next_bar or iid not in exiting}
        entries = []
        for cand in specmod.entries(self.spec, list(snaps.values())):
            if self.next_bar:
                if cand.snapshot.contract.ticker not in held:
                    entries.append(OrderIntent(instrument_id(cand.snapshot.contract.ticker, cand.side), Side.BUY,
                                               max(1, specmod.contracts_for(self.stake, cand.price)),
                                               strategy_id=self.strategy_id, reason="entry", fair_value=cand.fair,
                                               meta={"edge": cand.edge, "stake": self.stake,
                                                     "signal_price": cand.price}))
                continue
            if open_n >= self.max_positions:
                break
            ticker = cand.snapshot.contract.ticker
            if ticker in held:
                continue
            price = min(0.99, cand.price)
            qty = specmod.contracts_for(self.stake, min(0.99, cand.price + self.slippage))
            if qty < 1:
                continue
            entries.append(OrderIntent(instrument_id(ticker, cand.side), Side.BUY, qty, limit_price=price,
                                       strategy_id=self.strategy_id, reason="entry", fair_value=cand.fair,
                                       meta={"edge": cand.edge}))
            held.add(ticker)
            open_n += 1
        return exits + entries


class KalshiNextBarFill:
    """The backtest's next-bar fill model as an ExecutionPolicy (``backtest._simulate_next_bar``).

    An entry fills at this bar's ask, sized from its stake at that price and capped at the displayed
    top-of-book size, and only if the ask is within ``execution_kernel.reservation_price`` for its own
    fair value and the spec's ``min_edge`` (the cap live and paper enforce); otherwise it is missed.
    ``max_ask`` is the highest ask an entry may lift (``backtest.MAX_ENTRY_ASK``: a 99c buy can't
    profit after the fee). ``slippage`` (a cost what-if) is added to the ask before sizing and the
    reservation check, as the backtest does; the venue charges it on the fill. Exits and stops take
    the touch through ``CrossTheTouch``."""

    def __init__(self, min_edge: float, exits: Optional[CrossTheTouch] = None, max_ask: float = 0.99,
                 slippage: float = 0.0) -> None:
        self.min_edge = min_edge
        self.exits = exits or CrossTheTouch(max_quote_age_seconds=0.0)
        self.max_ask = max_ask
        self.slippage = slippage

    def execute(self, intent: OrderIntent, instrument: Instrument, quote: Optional[Quote], venue: Venue,
                client_order_id: str, now: float) -> ExecutionReport:
        if intent.reduce_only or intent.side is Side.SELL:
            return self.exits.execute(intent, instrument, quote, venue, client_order_id, now)
        ask = quote.ask if quote is not None else None
        if ask is None or not 0.0 < ask <= self.max_ask:
            return ExecutionReport(intent, "rejected", message="no ask at or below %.2f" % self.max_ask)
        price = min(0.99, ask + self.slippage)
        qty = specmod.contracts_for(intent.meta["stake"], price)
        size = quote.features.get("yes_ask_size" if intent.instrument.outcome == "yes" else "yes_bid_size")
        if size is not None:
            qty = min(qty, int(float(size)))
        if qty < 1:
            return ExecutionReport(intent, "rejected", message="size below one contract")
        limit = reservation_price(intent.fair_value, self.min_edge, qty)
        if limit is None or price > limit + 1e-9:
            return ExecutionReport(intent, "rejected", message="ask past the reservation price")
        return venue.submit(replace(intent, qty=qty, limit_price=price), price, client_order_id)


class _FrameQuotes(Mapping):
    """One dataset frame as {InstrumentId: Quote}, YES from each snapshot and NO derived. A quote is
    built the first time something reads it: a bar with hundreds of contracts usually needs a few
    (held positions, the orders it sends), and the strategy reads the snapshots themselves."""

    def __init__(self, snaps: Mapping[str, Snapshot]) -> None:
        self._snaps = snaps
        self._built: Dict[InstrumentId, Quote] = {}

    def __getitem__(self, iid: InstrumentId) -> Quote:
        q = self._built.get(iid)
        if q is None:
            snap = self._snaps.get(iid.symbol) if iid.venue == ki.VENUE else None
            if snap is None or iid.outcome not in ("yes", "no"):
                raise KeyError(iid)
            yes, no = ki.quotes(snap)
            self._built[yes.instrument], self._built[no.instrument] = yes, no
            q = yes if iid.outcome == "yes" else no
        return q

    def __iter__(self):
        for ticker in self._snaps:
            yield instrument_id(ticker, "yes")
            yield instrument_id(ticker, "no")

    def __len__(self) -> int:
        return 2 * len(self._snaps)

    def __contains__(self, iid) -> bool:
        return isinstance(iid, InstrumentId) and iid.venue == ki.VENUE and iid.symbol in self._snaps \
            and iid.outcome in ("yes", "no")


class _FrameFeed:
    """The current dataset frame as a MarketDataFeed."""

    def __init__(self) -> None:
        self.snaps: Dict[str, Snapshot] = {}
        self.current: _FrameQuotes = _FrameQuotes({})

    def load(self, snaps: Sequence[Snapshot]) -> None:
        self.snaps = {snap.contract.ticker: snap for snap in snaps}
        self.current = _FrameQuotes(self.snaps)

    def quote(self, instrument: InstrumentId) -> Optional[Quote]:
        return self.current.get(instrument)

    def quotes(self, instruments) -> Mapping[InstrumentId, Quote]:
        if instruments is self.current:
            return self.current   # the whole frame (the replay's universe): stay lazy
        return {i: self.current[i] for i in instruments if i in self.current}


class _ResultSettlement:
    """A binary pays 1 if the dataset's result is its outcome, else 0 (a missing result is a loss,
    exactly as ``backtest.simulate`` books it)."""

    def __init__(self, results: Mapping[str, str]) -> None:
        self.results = results

    def settlement_price(self, instrument: Instrument) -> float:
        return 1.0 if self.results.get(instrument.id.symbol) == instrument.id.outcome else 0.0


def simulate_on_loop(spec: Dict, ds, start_ts: int, end_ts: int, fees: Optional[FeeModel] = None,
                     stake: Optional[float] = None, fill_model: Optional[str] = None,
                     position_stop_pct: Optional[float] = None, what_if=None) -> List:
    """``backtest.simulate`` re-expressed as TradingLoop steps; returns the same ``backtest.Trade``
    records so the two can be compared row for row. ``fill_model`` defaults to the backtest's own
    ``FILL_MODEL``; ``position_stop_pct`` to its ``POSITION_STOP_PCT`` (next-bar only, as there).
    ``what_if`` is a ``backtest.WhatIf``: its stake and stop fill in the arguments left None, its
    slippage goes to the fill model and its fee multiplier scales ``fees``."""
    from app import backtest
    from app.backtest import Trade, _first_frame

    w = what_if or backtest.WhatIf()
    stake = w.stake if stake is None else stake
    position_stop_pct = w.position_stop_pct if position_stop_pct is None else position_stop_pct
    slip = w.slippage_cents / 100.0

    next_bar = (fill_model or backtest.FILL_MODEL) == "next_bar"
    contracts = {s.contract.ticker: s.contract for _, snaps in ds.frames for s in snaps}
    instruments: Dict[InstrumentId, Instrument] = {}
    for c in contracts.values():
        yes = ki.binary(c, "yes", ds.market)
        instruments[yes.id] = yes
        instruments[yes.complement().id] = yes.complement()
    clock, feed, book = FixedClock(0.0), _FrameFeed(), Portfolio()
    fees = fees or KalshiBinaryFees()
    if w.fee_multiplier != 1.0:
        fees = ScaledFees(fees, w.fee_multiplier)
    strategy = SpecStrategy(spec, contracts, stake=stake, entry_until=end_ts, next_bar=next_bar, slippage=slip,
                            frame=lambda: feed.snaps)
    if next_bar:
        stop = backtest.POSITION_STOP_PCT if position_stop_pct is None else float(position_stop_pct)
        bar = max(int(getattr(ds.market, "decision_seconds", 60) or 60), 1)
        extra = dict(execution=KalshiNextBarFill(float(spec["entry"]["min_edge"]), max_ask=backtest.MAX_ENTRY_ASK,
                                                 slippage=slip),
                     next_step_fills=True,
                     pending_ttl=backtest.FILL_MAX_DELAY_BARS * bar, exit_rules=[position_stop(stop)],
                     risk=RiskChain([max_open_positions(spec["sizing"]["max_positions"], book),
                                     one_position_per_symbol(book)]))
    else:
        extra = dict(execution=CrossTheTouch(max_quote_age_seconds=0.0))
    venue = QuoteFillVenue(feed, fees, instruments, slippage=slip)
    loop = TradingLoop(strategy, instruments, feed, venue, clock, book=book,
                       settlement=_ResultSettlement(ds.results), universe=lambda now: feed.current, **extra)
    opened: Dict[InstrumentId, tuple] = {}     # iid -> (entry_ts, entry_price, entry_fee, edge)
    trades: List[Trade] = []

    def close_ts(iid: InstrumentId) -> int:
        return int(contracts[iid.symbol].close_time.timestamp())

    def settled(iid: InstrumentId, qty: float, price: float) -> None:
        entry_ts, entry_px, entry_fee, edge = opened.pop(iid)
        trades.append(Trade(iid.symbol, iid.outcome, int(qty), entry_ts, entry_px, close_ts(iid), price,
                            entry_fee, "settled", edge))

    for ts, snaps in ds.frames[_first_frame(ds, start_ts):]:
        clock.ts = float(ts)
        feed.load(snaps)
        step = loop.step()
        for iid, qty, _avg, price in step.settled:
            settled(iid, qty, price)
        for rep in step.reports:
            for f in rep.fills:
                if f.side is Side.BUY:
                    opened[f.instrument] = (int(f.ts), f.price, f.fee, rep.intent.meta.get("edge", 0.0))
                else:
                    entry_ts, entry_px, entry_fee, edge = opened.pop(f.instrument)
                    trades.append(Trade(f.instrument.symbol, f.instrument.outcome, int(f.qty), entry_ts, entry_px,
                                        int(f.ts), f.price, entry_fee + f.fee, rep.intent.reason, edge))
        if ts >= end_ts and not loop.book.open_positions():
            break
    settlement = _ResultSettlement(ds.results)
    for iid, pos in list(loop.book.open_positions().items()):
        settled(iid, pos.qty, settlement.settlement_price(instruments[iid]))
    return trades
