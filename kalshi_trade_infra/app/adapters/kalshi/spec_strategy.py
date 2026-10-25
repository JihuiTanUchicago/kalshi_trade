"""A research spec (the ``app.spec`` DSL) as a ``trading_core.ports.Strategy``, plus the replay that
runs it through ``trading_core.engine.TradingLoop`` (ARCHITECTURE.md step 8b).

``simulate_on_loop`` is the parity harness: on the same dataset it must produce the same trades as
``app.backtest.simulate`` with the legacy same-bar fill model (``FILL_MODEL="signal_bar"``). Once it
does on real data, the backtest can move onto the loop, then paper, then live, and all three run one
code path. Not covered yet: code specs, cross-contract pairs, pooled datasets, the next-bar fill
model and what-if slippage (each gets its own parity test before it moves).
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from app import spec as specmod
from app.adapters.kalshi import instruments as ki
from app.adapters.kalshi.convert import instrument_id
from app.adapters.kalshi.fees import KalshiBinaryFees
from app.markets import Contract, Snapshot
from trading_core.domain import Instrument, InstrumentId, OrderIntent, Portfolio, Quote, Side
from trading_core.engine import CrossTheTouch, QuoteFillVenue, TradingLoop
from trading_core.ports import DecisionContext, FeeModel, FixedClock


class SpecStrategy:
    """Exits first (each held contract checked against ``spec.exit_signal`` at its own bid), then
    entries (``spec.entries``, best edge first) up to ``max_positions``, one position per ticker."""

    def __init__(self, spec: Dict, contracts: Mapping[str, Contract], *, stake: Optional[float] = None,
                 entry_until: float = float("inf"), strategy_id: str = "spec") -> None:
        if specmod.is_code_spec(spec) or spec.get("cross") or specmod.is_perpetual_spec(spec):
            raise ValueError("SpecStrategy runs single-contract DSL specs only")
        self.spec, self.contracts, self.strategy_id = spec, contracts, strategy_id
        self.stake = spec["sizing"]["stake"] if stake is None else stake
        self.max_positions = spec["sizing"]["max_positions"]
        self.entry_until = entry_until

    def _snapshots(self, quotes: Mapping[InstrumentId, Quote]) -> Dict[str, Snapshot]:
        """The legacy YES snapshots, in feed order (entries breaks edge ties by input order)."""
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
                exits.append(OrderIntent(iid, Side.SELL, pos.qty, limit_price=price, reduce_only=True,
                                         strategy_id=self.strategy_id, reason=reason))
                exiting.add(iid)
        if ctx.now >= self.entry_until:
            return exits
        open_n = len(ctx.positions) - len(exiting)
        held = {iid.symbol for iid in ctx.positions if iid not in exiting}
        entries = []
        for cand in specmod.entries(self.spec, list(snaps.values())):
            if open_n >= self.max_positions:
                break
            ticker = cand.snapshot.contract.ticker
            if ticker in held:
                continue
            price = min(0.99, cand.price)
            qty = specmod.contracts_for(self.stake, price)
            if qty < 1:
                continue
            entries.append(OrderIntent(instrument_id(ticker, cand.side), Side.BUY, qty, limit_price=price,
                                       strategy_id=self.strategy_id, reason="entry", fair_value=cand.fair,
                                       meta={"edge": cand.edge}))
            held.add(ticker)
            open_n += 1
        return exits + entries


class _FrameFeed:
    """The current dataset frame as a MarketDataFeed: YES quotes from the snapshots, NO derived."""

    def __init__(self) -> None:
        self.current: Dict[InstrumentId, Quote] = {}

    def load(self, snaps: Sequence[Snapshot]) -> None:
        self.current = {}
        for snap in snaps:
            yes, no = ki.quotes(snap)
            self.current[yes.instrument] = yes
            self.current[no.instrument] = no

    def quote(self, instrument: InstrumentId) -> Optional[Quote]:
        return self.current.get(instrument)

    def quotes(self, instruments: Sequence[InstrumentId]) -> Dict[InstrumentId, Quote]:
        return {i: self.current[i] for i in instruments if i in self.current}


class _ResultSettlement:
    """A binary pays 1 if the dataset's result is its outcome, else 0 (a missing result is a loss,
    exactly as ``backtest.simulate`` books it)."""

    def __init__(self, results: Mapping[str, str]) -> None:
        self.results = results

    def settlement_price(self, instrument: Instrument) -> float:
        return 1.0 if self.results.get(instrument.id.symbol) == instrument.id.outcome else 0.0


def simulate_on_loop(spec: Dict, ds, start_ts: int, end_ts: int, fees: Optional[FeeModel] = None,
                     stake: Optional[float] = None) -> List:
    """``backtest.simulate`` (signal-bar fills) re-expressed as TradingLoop steps; returns the same
    ``backtest.Trade`` records so the two can be compared row for row."""
    from app.backtest import Trade, _first_frame

    contracts = {s.contract.ticker: s.contract for _, snaps in ds.frames for s in snaps}
    instruments: Dict[InstrumentId, Instrument] = {}
    for c in contracts.values():
        yes = ki.binary(c, "yes", ds.market)
        instruments[yes.id] = yes
        instruments[yes.complement().id] = yes.complement()
    clock, feed = FixedClock(0.0), _FrameFeed()
    fees = fees or KalshiBinaryFees()
    strategy = SpecStrategy(spec, contracts, stake=stake, entry_until=end_ts)
    loop = TradingLoop(strategy, instruments, feed, QuoteFillVenue(feed, fees, instruments), clock,
                       execution=CrossTheTouch(max_quote_age_seconds=0.0), book=Portfolio(),
                       settlement=_ResultSettlement(ds.results), universe=lambda now: list(feed.current))
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
