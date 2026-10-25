"""Polymarket's probability for the same event as a Kalshi BTC contract, as features.

    pm_p_yes    Polymarket's probability that the Kalshi contract settles YES: the 15-minute up/down
                window with the same open and close (KXBTC15M), or the daily strike ladder settling
                at the contract's close read at its strike (KXBTCD/KXBTC at noon ET)
    pm_edge     pm_p_yes - the Kalshi mid (positive = Kalshi YES looks cheap against Polymarket)
    pm_spread   Polymarket's YES spread behind pm_p_yes (0 on one-minute history, which has no book)
    pm_age_s    seconds since the Polymarket quote was taken

Two interfaces over one PmSeries:
  PolymarketBook      .features(ticker, strike, ts, yes_bid, yes_ask, frame_feats, close_ts), the
                      forecast-book call backtest.build_dataset and the engine's frames already make
  PolymarketFeatures  trading_core.ports.FeatureProvider for code on the new TradingLoop
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence

from data_pipeline import polymarket as pmk
from trading_core.domain.instruments import Instrument, InstrumentId, InstrumentKind

SERIES = frozenset({"KXBTC15M", "KXBTCD", "KXBTC"})
UPDOWN_WINDOW_S = {"KXBTC15M": 900}    # series whose strike is the price at the open, and their window
MAX_AGE_S = 150                         # live polls every 5s; history is one point a minute
FEATURE_NAMES = ("pm_p_yes", "pm_edge", "pm_spread", "pm_age_s")


def _open_ts(series: str, close_ts: int) -> Optional[int]:
    w = UPDOWN_WINDOW_S.get(series)
    return None if w is None else int(close_ts) - w


class PolymarketBook:
    def __init__(self, quotes: Iterable[pmk.PmQuote], max_age_s: int = MAX_AGE_S) -> None:
        self.series = pmk.PmSeries(quotes)
        self.max_age_s = max_age_s

    def __len__(self) -> int:
        return len(self.series)

    def prob(self, series: str, lo: Optional[float], hi: Optional[float], close_ts: int,
             ts: int) -> Optional[Dict[str, float]]:
        f = self.series.at(lo, hi, int(close_ts), _open_ts(series, close_ts), int(ts), self.max_age_s)
        if f is None:
            return None
        return {"pm_p_yes": f["pm_p_yes"], "pm_spread": f["pm_spread"], "pm_age_s": f["pm_age_s"]}

    def features(self, ticker: str, strike: float, ts: int, yes_bid: Optional[float], yes_ask: Optional[float],
                 frame_feats: Optional[Dict[str, float]] = None, close_ts: Optional[int] = None) -> Dict[str, float]:
        if close_ts is None or not strike:
            return {}
        out = self.prob(ticker.split("-")[0], float(strike), None, close_ts, ts)
        if out is None:
            return {}
        if yes_bid is not None and yes_ask is not None:
            out["pm_edge"] = out["pm_p_yes"] - (float(yes_bid) + float(yes_ask)) / 2.0
        return out


def book_from_snapshot(rows: Optional[Sequence[Dict]]) -> Optional[PolymarketBook]:
    """A book from the recorder's heartbeat snapshot (live), None when empty."""
    if not rows:
        return None
    book = PolymarketBook(pmk.quotes_from_snapshot(rows))
    return book if len(book) else None


def load_book(series: str, since, until=None, store=None) -> Optional[PolymarketBook]:
    """A research book for one Kalshi series: up/down windows for KXBTC15M, ladders otherwise."""
    from app.adapters.polymarket.store import load_quotes
    kinds = ("updown",) if series in UPDOWN_WINDOW_S else ("above", "below")
    book = PolymarketBook(load_quotes(since, until, store, kinds=kinds))
    return book if len(book) else None


def book_for_series(series: str, load: Callable[[], Optional[PolymarketBook]]) -> Optional[PolymarketBook]:
    return load() if series in SERIES else None


class PolymarketFeatures:
    """trading_core.ports.FeatureProvider: pm_p_yes / pm_spread / pm_age_s for binary instruments
    on BTC (any venue) from the book ``source(as_of)`` returns."""

    name = "polymarket"

    def __init__(self, source: Callable[[float], Optional[PolymarketBook]]) -> None:
        self.source = source

    def feature_names(self) -> Sequence[str]:
        return ("pm_p_yes", "pm_spread", "pm_age_s")

    def features(self, instruments: Sequence[Instrument], as_of: float) -> Mapping[InstrumentId, Dict[str, float]]:
        book = self.source(as_of)
        if book is None:
            return {}
        out: Dict[InstrumentId, Dict[str, float]] = {}
        for inst in instruments:
            if inst.kind is not InstrumentKind.BINARY or inst.expiry is None:
                continue
            lo, hi = inst.meta.get("strike_lo"), inst.meta.get("strike_hi")
            if lo is None and hi is None:
                lo = getattr(inst.terms, "strike", None)
            if lo is None and hi is None:
                continue
            f = book.prob(inst.series, lo, hi, int(inst.expiry.timestamp()), int(as_of))
            if f is None:
                continue
            if inst.id.outcome == "no":
                f = dict(f, pm_p_yes=1.0 - f["pm_p_yes"])
            out[inst.id] = f
        return out


FEATURE_DOCS = pmk.FEATURE_DOCS
