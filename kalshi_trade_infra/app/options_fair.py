"""Deribit options-implied fair value for Kalshi's BTC strike contracts (KXBTC15M, KXBTCD, KXBTC).

The surface (data_pipeline/options_surface.py) comes from Deribit's BTC options, recorded on the
collector box by data_pipeline/deribit_options.py. Research and live read the same fits:

  research  the day files (ticks/v1/deribit_surface_day/, trade-fitted history back to before the
            recorder plus the recorded chain) and today's hourly deribit_surface archive, via
            load_book(since)
  live      the newest surface the recorder put in its collector_state heartbeat
            (repository.latest_options_surface), via book_from_rows

snapshot_features() is THE call both sides make per contract (OptionsBook.features, which
backtest.build_dataset and the engine's decision frames invoke exactly like the weather and
sportsbook books), priced at the frame's BTC spot:

    opt_p_yes    options-implied probability the contract settles YES
    opt_edge     opt_p_yes - mid (positive = YES looks cheap against the options market)
    opt_iv       implied vol at the contract's strike and horizon (annualized)
    opt_age_min  minutes since the surface snapshot was taken
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from data_pipeline import options_surface as osf

SERIES = frozenset({"KXBTC15M", "KXBTCD", "KXBTC"})
DAY_TABLE = "deribit_surface_day"
# Research reads one chain snapshot per 5 minutes and the expiries within 8 days (every candle
# market prices contracts of a day or less); live reads the newest snapshot.
RESEARCH_STEP_S = 300
RESEARCH_MAX_EXPIRY_DAYS = 8.0


class OptionsBook:
    """Surface snapshots in time order; features() prices one contract as of ts."""

    def __init__(self, surfaces: Iterable[osf.Surface]):
        self.series = osf.SurfaceSeries(surfaces)

    def __len__(self) -> int:
        return len(self.series)

    def features(self, ticker: str, strike: float, ts: int, yes_bid: Optional[float], yes_ask: Optional[float],
                 frame_feats: Optional[Dict[str, float]] = None, close_ts: Optional[int] = None) -> Dict[str, float]:
        return snapshot_features(self, strike, ts, close_ts, yes_bid, yes_ask, frame_feats)


def snapshot_features(book: Optional[OptionsBook], strike: float, ts: int, close_ts: Optional[int],
                      yes_bid: Optional[float], yes_ask: Optional[float],
                      frame_feats: Optional[Dict[str, float]]) -> Dict[str, float]:
    """Options-implied features of one "above strike" contract at ts ({} when nothing usable:
    no surface young enough, no spot in the frame, no close time)."""
    if book is None or close_ts is None or not strike or strike <= 0:
        return {}
    spot = (frame_feats or {}).get("spot")
    if not spot or spot <= 0:
        return {}
    surface = book.series.at(ts)
    if surface is None:
        return {}
    p, iv = osf.price(surface, ts, strike, close_ts, spot)
    if not (p[0] == p[0]):
        return {}
    out = {"opt_p_yes": float(p[0]), "opt_iv": float(iv[0]), "opt_age_min": (ts - surface.snap_ts) / 60.0}
    if yes_bid is not None and yes_ask is not None:
        out["opt_edge"] = out["opt_p_yes"] - (float(yes_bid) + float(yes_ask)) / 2.0
    return out


def book_from_rows(rows: Optional[List[Dict]]) -> Optional[OptionsBook]:
    """An OptionsBook from stored surface rows (the live heartbeat's), None when empty."""
    if not rows:
        return None
    book = OptionsBook(osf.surfaces_from_rows(rows))
    return book if len(book) else None


def _day_rows(store, day: datetime) -> List[Dict]:
    import pyarrow.parquet as pq
    p = store._fetch(f"{store.prefix}/v1/{DAY_TABLE}/date={day:%Y-%m-%d}/part.parquet")
    return pq.read_table(p).to_pylist() if p else []


def _thin(rows: List[Dict], step_s: int, max_expiry_s: int) -> List[Dict]:
    """One chain snapshot per step_s (the first of each step), expiries up to max_expiry_s out
    plus the next one (the bracket for a horizon just past the cut)."""
    keep_snap: Dict[int, int] = {}
    for r in rows:
        if r.get("method") == "chain":
            b = int(r["snap_ts"]) // step_s
            keep_snap[b] = min(keep_snap.get(b, int(r["snap_ts"])), int(r["snap_ts"]))
    first_beyond: Dict[int, int] = {}
    for r in rows:
        snap, exp = int(r["snap_ts"]), int(r["expiry_ts"])
        if exp - snap > max_expiry_s:
            first_beyond[snap] = min(first_beyond.get(snap, exp), exp)
    out = []
    for r in rows:
        snap, exp = int(r["snap_ts"]), int(r["expiry_ts"])
        if r.get("method") == "chain" and keep_snap.get(snap // step_s) != snap:
            continue
        if exp - snap > max_expiry_s and exp != first_beyond.get(snap):
            continue
        out.append(r)
    return out


def load_surfaces(since: datetime, until: Optional[datetime] = None, store=None, step_s: int = RESEARCH_STEP_S,
                  max_expiry_days: float = RESEARCH_MAX_EXPIRY_DAYS) -> List[osf.Surface]:
    """Stored surfaces from ``since`` to ``until`` (default now): the day file of each past day,
    and the hourly chain archive for days without one yet (today, and yesterday until its file is
    written). Within an hour that has chain snapshots the trade fits are dropped, so the series
    never alternates between the two fits; chain snapshots are thinned to one per step_s, which a
    surface that moves this slowly loses nothing to, and a 90-day window stays small."""
    from data_pipeline.tick_store import TickStore
    store = store or TickStore()
    since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    until = until or datetime.now(timezone.utc)
    day = (since - timedelta(seconds=osf.MAX_AGE_S)).replace(hour=0, minute=0, second=0, microsecond=0)
    out: List[osf.Surface] = []
    while day < until:
        rows = _day_rows(store, day)
        if not rows:
            t = store.read("deribit_surface", day, min(day + timedelta(days=1), until))
            rows = t.to_pylist() if t is not None and t.num_rows else []
        chain_hours = {int(r["snap_ts"]) // 3600 for r in rows if r.get("method") == "chain"}
        rows = [r for r in rows if r.get("method") == "chain" or int(r["snap_ts"]) // 3600 not in chain_hours]
        out.extend(osf.surfaces_from_rows(_thin(rows, step_s, int(max_expiry_days * 86400))))
        day += timedelta(days=1)
    return out


def load_book(since: datetime, until: Optional[datetime] = None, store=None) -> Optional[OptionsBook]:
    book = OptionsBook(load_surfaces(since, until, store))
    return book if len(book) else None


def book_for_series(series: str, load) -> Optional[OptionsBook]:
    """The OptionsBook for a Deribit-priced BTC series, else None. load() returns the book."""
    return load() if series in SERIES else None


FEATURE_DOCS = {
    "opt_p_yes": "Bitcoin strike markets only: Deribit options-implied probability that this contract settles "
                 "YES (BTC above the strike at the close, from the implied-vol smile and term structure, with "
                 "Kalshi's 60-second settlement average), priced at the frame's BTC spot",
    "opt_edge": "Bitcoin strike markets only: opt_p_yes minus the contract's mid (positive = YES cheap vs options)",
    "opt_iv": "Bitcoin strike markets only: Deribit implied volatility (annualized, 0.5 = 50%) at the "
              "contract's strike and time to close",
    "opt_age_min": "Bitcoin strike markets only: minutes since the Deribit surface behind opt_p_yes was taken",
}
