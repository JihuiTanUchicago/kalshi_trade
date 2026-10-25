"""Runs every deployed strategy, for every user, against the live market.

Per market, per decision slot (one minute for 15-minute contracts, one hour
for the daily ladder - the backtest's own cadence):

    settle positions whose contract has a result
    read the live book (Kalshi REST, one call for the whole series) + BTC
    for each running deployment that has not decided this slot:
        exits per spec, then entries per spec, then the loss guard

Paper fills happen at the live ask/bid read this tick, capped at the size
shown, never at a stale bar. Live orders go through MarketableLimitKernel,
which re-reads the book and records only what Kalshi reports filled.

Two engines can run at once safely: `claim_decision` lets exactly one of them
decide a deployment's slot, and closing a position only works on an open one.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Tuple

import requests

from app import freedata
from app import repository as repo
from app import spec as specmod
from app import options_fair, sports_odds, weather_fcst
from app.markets import (MARKETS, WEATHER_OBS_FEATURES, WEATHER_STATIONS, BtcSeries, Contract, Market, Snapshot,
                         cross_features, cross_product,
                         compatible_cadence, snapshot, weather_obs_applies)
from data_pipeline.common import api_get, fetch_open_markets, parse_iso_to_dt
from data_pipeline.market_data import ws_quote
from data_pipeline.kalshi_fees import taker_fee_dollars

# Live orders for app users stay off until the owner explicitly turns them on.
LIVE_TRADING_ENABLED = os.getenv("APP_LIVE_TRADING_ENABLED") == "1"
# Staged rollout for NO-side live: the YES-leg-complement order mechanics are test-verified but
# not yet validated against the real exchange, so non-YES strategies stay on PAPER for the LIVE
# path until this flag is set. Demo/paper NO always work (for sandbox validation; no real money).
# ponytail: temporary; remove once NO-side live is validated on the demo sandbox.
NO_SIDE_LIVE_ENABLED = os.getenv("APP_NO_SIDE_LIVE_ENABLED") == "1"
# Paper and demo decisions as one trading_core TradingLoop step instead of the legacy entry/exit loops
# below (ARCHITECTURE.md step 8: backtest, paper and live on one code path; only the venue differs).
# "paper" and "demo" are honoured; live moves separately (it adds the reconcile halts and the size ramp),
# behind its own parity test. Both on by default (Todd, 2026-10-25, after the MySQL parity test
# tests/test_engine_loop_parity_db.py); TAU_ENGINE_LOOP=paper keeps demo on the legacy path,
# TAU_ENGINE_LOOP=off puts both back.
ENGINE_LOOP_MODES = frozenset(m.strip() for m in os.getenv("TAU_ENGINE_LOOP", "paper,demo").split(",")
                              if m.strip()) & {"paper", "demo"}
TICK_SECONDS = 15
# An order whose outcome is unknown (intent still 'sent': a timeout, a crash, a lost response) may
# already have filled. No new order goes out on that user's ticker until recovery reads the truth
# from the exchange, so a retry never stacks a second buy or a second sell on top of a fill we
# cannot see yet (the oversell-into-a-short shape). Bounded: after this window the block lifts
# even if recovery could not resolve it, so an exit is delayed, never trapped.
INFLIGHT_BLOCK_SECONDS = int(os.getenv("APP_INFLIGHT_BLOCK_SECONDS", "180"))
# How often the engine re-reconciles 'sent' intents against the exchange (was a fixed 300s).
RECOVER_EVERY_SECONDS = float(os.getenv("APP_RECOVER_EVERY_SECONDS", "30"))
# An intent the exchange still cannot account for this long after its market closed (or after it
# was logged, if it has no close time) will never resolve by asking again: it is moved to the
# terminal 'unresolved' status (logged loudly, once) so recovery stops polling the exchange for it
# every pass. Its contract has settled by then; the position reconciler owns any exposure.
UNRESOLVED_AFTER_CLOSE_SECONDS = int(os.getenv("APP_UNRESOLVED_AFTER_CLOSE_SECONDS", str(24 * 3600)))
UNRESOLVED_NO_CLOSE_SECONDS = int(os.getenv("APP_UNRESOLVED_NO_CLOSE_SECONDS", str(7 * 24 * 3600)))
UNRECOVERED_LOG_EVERY_SECONDS = 3600
_unrecovered_logged: Dict[str, float] = {}
# This engine process's identity, for the per-position close claim (P0-3): whichever engine stamps
# its id on a position owns that force-close, so two engines never both sell it into a short.
_ENGINE_ID = "engine-%s" % uuid.uuid4()
# A slot decided this late is skipped instead: the backtest decided at the
# slot boundary, and a daily decision taken 50 minutes late is a different rule.
LATE_FRACTION = 0.25
# Hard guard, no model involved: a deployment that has lost this much more
# than its backtest's worst unseen-data drawdown is paused.
LOSS_GUARD_MULTIPLE = 2.0
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/%s/candles"  # %s = product, e.g. BTC-USD
COINBASE_TRADES_URL = "https://api.exchange.coinbase.com/products/%s/trades"
TRADE_PAGES = 3            # x1000 trades: ~20 min of BTC, enough for any candle-batch delay
MAX_TRADE_FILL_S = 900     # an older newest-candle is a dead feed, not a batch delay: leave it stale
# Mark-staleness gate (P1-2): a risk TRIGGER (drawdown / position-stop force-sell) must not fire
# off a mark older than this. Marks refresh every tick (~15s), so the default of 90s (6 ticks) only
# trips when marking has actually stalled; 0 disables the gate. A stale mark is treated like an
# unmarked one — the position is skipped for the trigger decision, never force-sold off stale data.
# The EXIT path (flatten / force-close pricing) never consults this: an exit must always get flat.
try:
    MARK_MAX_AGE_SECONDS = float(os.getenv("APP_MARK_MAX_AGE_SECONDS", "90"))
except (TypeError, ValueError):
    MARK_MAX_AGE_SECONDS = 90.0
# When stamping marks, prefer a websocket top-of-book no older than this over the REST snapshot.
MARK_WS_FRESH_SECONDS = 2.0


@dataclass(frozen=True)
class LiveQuote:
    contract: Contract
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    yes_bid_size: Optional[float]
    yes_ask_size: Optional[float]


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def book_sizes(quotes) -> Dict:
    """Touch depth per ticker for the side an entry would TAKE. A YES buy lifts the YES ask
    (``ticker`` -> yes_ask_size); a NO buy is the YES mirror and hits the YES bid, so its depth is
    yes_bid_size, keyed ``(ticker, "no")``. Sizing a NO entry off the ask showed depth that isn't
    there (an order the book can't fill at the price we decided)."""
    out: Dict = {}
    for q in quotes:
        out[q.contract.ticker] = q.yes_ask_size
        out[(q.contract.ticker, "no")] = q.yes_bid_size
    return out


def shown_size(sizes: Dict, ticker: str, side: str) -> Optional[float]:
    """Contracts the book showed for buying ``side`` of ``ticker``. Callers that only pass a
    per-ticker number (tests, older frames) keep that number for both sides."""
    if str(side).lower() == "no" and (ticker, "no") in sizes:
        return sizes[(ticker, "no")]
    return sizes.get(ticker)


def _opt_float(v) -> Optional[float]:
    """An optional float env knob: None (feature off) for unset/blank/unparseable."""
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def decision_close_time(market: Market, m: Dict) -> Optional[datetime]:
    """The close time an open contract's time-to-expiry is measured against, matching research.

    Research reads settled markets, whose close_time is when the market actually closed. An open
    outcome-settled market that can close early (sports, weather) carries a later backstop
    close_time instead: every open KXNFL1HSPREAD contract on 2026-10-25 said 2026-10-27 17:00Z for a
    first half that ended the same afternoon, so live tte_min ran ~45h above research's and an
    entry window like "0.2-24 hours from expiry" could never open. Kalshi's
    expected_expiration_time is the scheduled resolution, the best pre-close estimate of that
    actual close. Strike markets close on schedule and keep close_time."""
    ct = parse_iso_to_dt(m.get("close_time"))
    if ct is None or market.underlying is not None or not m.get("can_close_early"):
        return ct
    expected = parse_iso_to_dt(m.get("expected_expiration_time"))
    return expected if expected is not None and expected < ct else ct


def fetch_quotes(market: Market) -> List[LiveQuote]:
    out = []
    for m in fetch_open_markets(market.series, get=api_get):
        ct = decision_close_time(market, m)
        if ct is None or not market.is_target_event(ct):
            continue
        strike = m.get("floor_strike")
        # An underlying-priced market (BTC/ETH/...) prices strike vs spot, so a contract with
        # no strike is unusable. An outcome-settled market (underlying is None, e.g. sports)
        # has no strike at all - use a 0.0 sentinel, matching the backtest's hist_markets
        # (see market_history.sync_settled_markets); snapshot() never reads it without a spot.
        if strike is None:
            if market.underlying is not None:
                continue
            strike = 0.0
        out.append(LiveQuote(
            Contract(m["ticker"], float(strike), ct.astimezone(timezone.utc), market.series),
            _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars")),
            _f(m.get("yes_bid_size_fp")), _f(m.get("yes_ask_size_fp")),
        ))
    return out


def fetch_spot_series(market: Market) -> Optional[BtcSeries]:
    """One-minute spot closes that price `market`'s contracts (strike vs spot), from the
    market's own Coinbase product. None for an outcome-settled market (underlying is None,
    e.g. sports): it has no spot series and trades on the contract's own book features alone."""
    if market.underlying is None:
        return None
    return fetch_minute_series(market.underlying)


def _trade_ts(s: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def trade_closes(trades: List[Dict], after_ts: int, now_ts: float) -> Optional[Dict[int, float]]:
    """Minute start -> close (the last trade's price) for every minute after `after_ts` that has
    fully closed by `now_ts`, from Coinbase /trades rows (any order). That is exactly how Coinbase
    builds a candle's close, so the rebuilt minutes match the candles the backtest reads. None when
    the trades don't reach back to `after_ts` (a hole would shift every n-minute window)."""
    last: Dict[int, Tuple[float, int, float]] = {}
    oldest = None
    for t in trades:
        ts, px = _trade_ts(t.get("time")), t.get("price")
        if ts is None or px is None:
            continue
        oldest = ts if oldest is None else min(oldest, ts)
        m = int(ts // 60) * 60
        key = (ts, int(t.get("trade_id") or 0))
        if m not in last or key > last[m][:2]:
            last[m] = (ts, key[1], float(px))
    if oldest is None or int(oldest // 60) * 60 > after_ts + 60:
        return None
    return {m: v[2] for m, v in last.items() if m > after_ts and m + 60 <= now_ts}


def fetch_minute_series(product: str, now: Optional[float] = None) -> BtcSeries:
    """One-minute Coinbase closes of `product`, current to the last closed minute.

    The public candles endpoint publishes in batches: the newest candle is often 3-5 minutes old,
    past MAX_BTC_GAP_SECONDS, so the engine would skip ticks the backtest (complete history) takes.
    When minutes are missing they are rebuilt from the public trades endpoint (the newest 1000
    trades span about 7 minutes of BTC, longer for alts; it pages back up to TRADE_PAGES). Any
    failure there keeps the candles as they are."""
    resp = requests.get(COINBASE_CANDLES_URL % product, params={"granularity": 60}, timeout=10)
    resp.raise_for_status()
    rows = {int(r[0]): float(r[4]) for r in resp.json()}
    now = time.time() if now is None else now
    newest = max(rows) if rows else None
    if newest is not None and newest + 120 <= now <= newest + 60 + MAX_TRADE_FILL_S:
        try:
            rows.update(_fill_from_trades(product, newest, now))
        except Exception as e:  # noqa: BLE001 - the candles alone still price the tick (or skip it)
            print("[engine] trade fill failed for %s: %r" % (product, e), flush=True)
    return BtcSeries(sorted(rows.items()))


def _fill_from_trades(product: str, after_ts: int, now: float) -> Dict[int, float]:
    trades: List[Dict] = []
    params: Dict = {"limit": 1000}
    for _ in range(TRADE_PAGES):
        resp = requests.get(COINBASE_TRADES_URL % product, params=params, timeout=10)
        resp.raise_for_status()
        page = resp.json() or []
        trades.extend(page)
        closes = trade_closes(trades, after_ts, now)
        cursor = (getattr(resp, "headers", None) or {}).get("cb-after")
        if closes is not None or not page or not cursor:
            return closes or {}
        params = {"limit": 1000, "after": cursor}
    return {}


_cross_cache: Dict[str, Tuple[float, BtcSeries]] = {}
CROSS_CACHE_SECONDS = 15.0


def fetch_product_series(product: str) -> Optional[BtcSeries]:
    """One-minute Coinbase closes of a cross product (markets.cross_product), shared by every
    market that reads it for CROSS_CACHE_SECONDS so seven alt markets cost one BTC request."""
    hit = _cross_cache.get(product)
    if hit and time.time() - hit[0] < CROSS_CACHE_SECONDS:
        return hit[1]
    series = fetch_minute_series(product)
    _cross_cache[product] = (time.time(), series)
    return series


def _with_cross(market: Market, sources: "Sources", now_ts: int, feats: Optional[Dict[str, float]]):
    """feats plus the market's CROSS_FEATURES, exactly as backtest.build_dataset merges them. A
    missing or stale cross feed leaves feats as they are (filters on the cross names then can't match)."""
    prod = cross_product(market)
    if feats is None or prod is None or sources.cross_spot is None:
        return feats
    try:
        xf = cross_features(prod, sources.cross_spot(prod), now_ts)
    except Exception as e:  # noqa: BLE001 - a cross-feed hiccup must not stop the market's own tick
        print("[engine] cross spot fetch failed for %s (%s): %r" % (market.key, prod, e), flush=True)
        return feats
    return dict(feats, **xf) if xf else feats


def fetch_result(ticker: str) -> Optional[str]:
    m = (api_get("/markets/%s" % ticker) or {}).get("market") or {}
    result = (m.get("result") or "").lower()
    return result if result in ("yes", "no") else None


@dataclass
class Sources:
    """Everything the engine reads from outside, swappable in tests."""

    quotes: Callable[[Market], List[LiveQuote]] = fetch_quotes
    spot: Callable[[Market], Optional[BtcSeries]] = fetch_spot_series
    # product -> one-minute closes for CROSS_FEATURES; None (tests' default) = no cross features
    cross_spot: Optional[Callable[[str], Optional[BtcSeries]]] = None
    result: Callable[[str], Optional[str]] = fetch_result
    live_kernel: Optional[Callable[[int], object]] = None  # user_id -> kernel; None = live disabled
    demo_kernel: Optional[Callable[[int], object]] = None  # user_id -> kernel; None = demo disabled
    # user_id -> kernel over a SimulatedVenue (never sends an order). None = legacy instant paper fills
    # at the quoted price. Set, paper runs the live execution policy so paper P&L is comparable to live.
    paper_kernel: Optional[Callable[[int], object]] = None
    # intent_row -> {'filled':int,'avg_price':float,'fee':float,'order_id':str} or None (undetermined).
    # Crash-recovery asks this whether a 'sent' intent's order filled; None = can't tell (leave it
    # 'sent', NEVER re-send). None here = no recovery lookup wired (recovery is a safe no-op).
    order_lookup: Optional[Callable[[Dict], Optional[Dict]]] = None
    # Shared live-book websocket (WsTickerFeed) for ≤1s marks (P1-1). None = REST-only marks.
    ws_feed: object = None
    # (tickers, as_of_ts) -> {ticker: {micro feature: value}}: the order-book features research
    # joins onto every snapshot (model_features_1m). None = snapshots carry no micro features.
    micro: Optional[Callable[[List[str], int], Dict[str, Dict[str, float]]]] = None
    # (station, kind, as_of_ts) -> issued forecast rows (repository.load_weather_forecasts) for a
    # weather series' per-contract forecast features. None = snapshots carry no forecast features.
    forecasts: Optional[Callable[[str, str, int], List]] = None
    # (sport, as_of_ts) -> collected sportsbook snapshots (repository.load_sports_odds) for an NBA/NHL
    # game series' consensus features. None = snapshots carry no sportsbook features.
    odds: Optional[Callable[[str, int], List]] = None
    # (series, as_of_ts) -> settled daily values (repository.load_weather_actuals) for the trailing
    # forecast bias (fcst_bias_f / fcst_p_yes_cal). None = those two features are absent.
    weather_actuals: Optional[Callable[[str, int], List]] = None
    # as_of_ts -> the newest Deribit surface rows (repository.latest_options_surface) for the
    # opt_* features of a Bitcoin strike series. None = snapshots carry no options features.
    options: Optional[Callable[[int], Optional[List[Dict]]]] = None
    # as_of_ts -> the Polymarket recorder's newest snapshot rows (app.adapters.polymarket.store
    # .latest_snapshot) for the pm_* features of a Bitcoin strike series. None = no pm_* features.
    polymarket: Optional[Callable[[int], Optional[List[Dict]]]] = None


def _micro_for(sources: Sources, tickers: List[str], now_ts: int) -> Dict[str, Dict[str, float]]:
    """Micro features for this frame, or {} when unwired or unreadable. Without them a strategy
    that filters on one simply doesn't enter (spec._passes), the same as research on a missing row."""
    if sources.micro is None or not tickers:
        return {}
    try:
        return sources.micro(tickers, now_ts) or {}
    except Exception as e:
        print("[engine] micro features unavailable: %r" % e, flush=True)
        return {}


def _btc_fair_books(market: Market, sources: Sources, now_ts: int):
    """Deribit options + Polymarket for a Bitcoin strike series, each optional on its own."""
    from app.adapters.polymarket import features as polymarket
    from app.fair_books import combine
    books = []
    for src, build in ((sources.options, lambda rows: options_fair.book_for_series(
                            market.series, lambda: options_fair.book_from_rows(rows))),
                       (sources.polymarket, lambda rows: polymarket.book_for_series(
                           market.series, lambda: polymarket.book_from_snapshot(rows)))):
        if src is None:
            continue
        try:
            books.append(build(src(now_ts)))
        except Exception as e:  # one source down must not cost the other's features
            print("[engine] fair-value source failed for %s: %r" % (market.key, e), flush=True)
    return combine(*books)


def _forecast_book(market: Market, sources: Sources, now_ts: int):
    """This frame's external fair-value book (research builds the same one from the same table):
    issued forecasts for a weather series, collected sportsbook odds for an NBA/NHL game series,
    the Deribit options surface the collector last fitted for a Bitcoin strike series.
    None when unwired, not such a series, or unreadable: a rule that filters on one of its
    features then doesn't enter, as in research on a frame without them."""
    try:
        if market.series in options_fair.SERIES:
            return _btc_fair_books(market, sources, now_ts)
        if market.series in sports_odds.SPORTS:
            if sources.odds is None:
                return None
            return sports_odds.book_for_series(market.series, lambda sport: sources.odds(sport, now_ts))
        if sources.forecasts is None or market.series not in WEATHER_STATIONS:
            return None
        return weather_fcst.book_for_series(
            market.series, lambda station, kind: sources.forecasts(station, kind, now_ts),
            (lambda series: sources.weather_actuals(series, now_ts)) if sources.weather_actuals else None)
    except Exception as e:
        print("[engine] external fair-value data unavailable for %s: %r" % (market.key, e), flush=True)
        return None


def _event_feats(market: Market, now_ts: int) -> Dict[str, float]:
    """Base features for an outcome-settled market (no spot). Weather daily highs carry their
    station's readings exactly as research joins them (freedata.station_observations, as of now),
    so a rule filtering on obs_high_f trades live the way it was tested. {} when unavailable."""
    station = WEATHER_STATIONS.get(market.series)
    if not station:
        return {}
    try:
        out = {}
        for name, obs in freedata.station_observations(station).items():
            v = freedata.asof_join([now_ts], obs).get(now_ts)
            if v is not None:
                out[name] = v
        return out
    except Exception as e:
        print("[engine] station features unavailable for %s: %r" % (market.key, e), flush=True)
        return {}


def _contract_feats(market: Market, feats: Optional[Dict[str, float]], ticker: str, now_ts: int):
    """A contract's base features: a weather contract keeps the station readings only on the day it
    settles on (research gates them the same way), so tomorrow's contract never sees today's high."""
    if not feats or market.series not in WEATHER_STATIONS or weather_obs_applies(market.series, ticker, now_ts):
        return feats
    return {k: v for k, v in feats.items() if k not in WEATHER_OBS_FEATURES}


def _contract_snapshot(market: Market, feats: Optional[Dict[str, float]], q: LiveQuote, now_ts: int,
                       micro: Dict[str, Dict[str, float]], book):
    """One live contract's Snapshot, built as research builds it: the contract's base features,
    its micro features, and (weather) its forecast features from those same base features."""
    cf = _contract_feats(market, feats, q.contract.ticker, now_ts)
    return snapshot(cf, q.contract, now_ts, q.yes_bid, q.yes_ask, weather_fcst.with_forecast(
        micro.get(q.contract.ticker), book, q.contract, now_ts, q.yes_bid, q.yes_ask, cf))


# -- settlement ------------------------------------------------------------------


def settle_due(conn, market: Market, sources: Sources, now: datetime) -> int:
    cur = conn.cursor()
    settled = 0
    results: Dict[str, Optional[str]] = {}
    for dep in repo.deployments_with_open_positions(cur, market.key):
        for pos in repo.open_positions(cur, dep["id"]):
            if pos["market_close_time"] > now.replace(tzinfo=None):
                continue
            if pos["ticker"] not in results:
                results[pos["ticker"]] = sources.result(pos["ticker"])
            result = results[pos["ticker"]]
            if result is None:
                continue  # Kalshi has not settled it yet
            payout = float(pos["qty"]) if result == pos["side"] else 0.0
            pnl = payout - float(pos["qty"]) * float(pos["entry_price"]) - float(pos["entry_fee"])
            with repo.transaction(conn) as tx:
                if not repo.close_position(tx, pos["id"], 1.0 if payout else 0.0, 0.0, pnl, "settled"):
                    continue
                if pos["mode"] == "paper":
                    repo.add_ledger(tx, pos["user_id"], "settlement", payout,
                                    "%s settled %s" % (pos["ticker"], result.upper()), pos["id"])
            settled += 1
    return settled


EARLY_EXIT_SCORE_SECONDS = 600
_last_exit_score: Dict[str, float] = {}


def score_early_exits(conn, market: Market, sources: Sources, now: datetime) -> int:
    """Score positions that exited before settlement (the stop, a take-profit, a flatten) against
    holding them to the end, once their contract settles: hold_pnl is what the position would have
    made held to expiry. That is how the stop proves (or disproves) itself on the live book. At most
    once per EARLY_EXIT_SCORE_SECONDS per market; read-only toward the exchange; never trades."""
    ts = now.timestamp()
    if ts - _last_exit_score.get(market.key, 0.0) < EARLY_EXIT_SCORE_SECONDS:
        return 0
    _last_exit_score[market.key] = ts
    cur = conn.cursor()
    scored = 0
    results: Dict[str, Optional[str]] = {}
    for pos in repo.unscored_early_exits(cur, market.key, now):
        if pos["ticker"] not in results:
            results[pos["ticker"]] = sources.result(pos["ticker"])
        result = results[pos["ticker"]]
        if result is None:
            continue  # not settled yet (or voided): try again next round
        qty = float(pos["qty"])
        payout = qty if result == pos["side"] else 0.0
        hold = payout - qty * float(pos["entry_price"]) - float(pos["entry_fee"])
        if repo.score_early_exit(cur, pos["id"], result, hold):
            scored += 1
    return scored


# -- decisions -------------------------------------------------------------------


def _paper_book_buy(conn, dep: Dict, ticker: str, side: str, qty: int, price: float, fee: float,
                    close_time, order_ref: Optional[str] = None) -> Optional[int]:
    """Debit the paper ledger and open the position in ONE transaction; None = not enough paper cash.
    `order_ref` is set only for a fill that came through the simulated venue, which is how the live
    gate tells realistic paper fills apart from legacy instant ones."""
    cost = qty * price + fee
    with repo.transaction(conn) as tx:
        repo.lock_user(tx, dep["user_id"])
        if repo.paper_balance(tx, dep["user_id"]) < cost:
            return None
        pid = repo.insert_position(tx, dep["id"], dep["user_id"], "paper", ticker, side, qty, price, fee,
                                   close_time, order_ref)
        repo.add_ledger(tx, dep["user_id"], "trade", -cost,
                        "Bought %d %s %s @ %.2f" % (qty, side.upper(), ticker, price), pid)
        return pid


def _paper_buy(conn, dep: Dict, entry: specmod.Entry, qty: int) -> Optional[int]:
    """Legacy paper entry: fills the whole size instantly at the quoted price."""
    price = entry.price
    return _paper_book_buy(conn, dep, entry.snapshot.contract.ticker, entry.side, qty, price,
                           taker_fee_dollars(qty, price), entry.snapshot.contract.close_time)


def _paper_sell(conn, pos: Dict, price: float, reason: str, fee: Optional[float] = None) -> bool:
    qty = int(pos["qty"])
    fee = taker_fee_dollars(qty, price) if fee is None else float(fee)
    pnl = qty * (price - float(pos["entry_price"])) - float(pos["entry_fee"]) - fee
    with repo.transaction(conn) as tx:
        if repo.close_position(tx, pos["id"], price, fee, pnl, reason):
            repo.add_ledger(tx, pos["user_id"], "trade", qty * price - fee,
                            "Sold %d %s %s @ %.2f (%s)" % (qty, pos["side"].upper(), pos["ticker"], price, reason), pos["id"])
            return True
    return False


def _paper_kernel_close(conn, cur, dep: Dict, pos: Dict, kernel, price: float, reason: str) -> bool:
    """Paper exit through the simulated venue: the same kernel the live exit uses, so a paper exit
    can miss or part-fill exactly as a live one can. A part fill books the sold slice (and credits
    its proceeds) and leaves the remainder open for the next slot, mirroring the live path."""
    qty = int(pos["qty"])
    rep = _live_trade(cur, dep, kernel, "sell", pos["side"], pos["ticker"], qty, price)
    filled = int(rep.fill_qty_contracts)
    if filled <= 0:
        return False  # no fresh quote / no bid: the position stays open, as it would live
    return _paper_book_exit(conn, pos, filled, rep.fill_price_dollars, rep.fee_dollars, reason)


def _paper_book_exit(conn, pos: Dict, filled: int, price: float, fee: float, reason: str) -> bool:
    """Book a paper exit fill of ``filled`` contracts: the whole row closes, or a part fill books the
    sold slice and leaves the remainder open. True only when the row closed."""
    qty = int(pos["qty"])
    if filled >= qty:
        return _paper_sell(conn, pos, price, reason, fee=fee)
    filled_entry_fee = float(pos["entry_fee"]) * filled / qty
    pnl = filled * (price - float(pos["entry_price"])) - filled_entry_fee - fee
    with repo.transaction(conn) as tx:
        if repo.book_partial_exit(tx, pos, filled, price, fee, pnl, reason):
            repo.add_ledger(tx, pos["user_id"], "trade", filled * price - fee,
                            "Sold %d/%d %s %s @ %.2f (%s, partial)" % (filled, qty, pos["side"].upper(), pos["ticker"],
                                                                      price, reason), pos["id"])
    return False


def _live_trade(cur, dep: Dict, kernel, action: str, side: str, ticker: str, qty: int, price: float,
                client_order_id_base: Optional[str] = None, fair: Optional[float] = None,
                min_edge: Optional[float] = None):
    from data_pipeline.architecture.contracts import TradeIntent

    # `side` is the real leg (yes|no) and `price` is that side's own price; the
    # kernel reads the correct side of the book and the submitter sends the
    # matching YES-leg wire order. A NO strategy must never place a YES order.
    # client_order_id_base (the persisted intent id, P0-1) rides on metadata so the kernel can mint
    # a durable, idempotent client_order_id for every child order without a signature change.
    # fair/min_edge (an entry's own-side fair value and the spec's required net edge) let the kernel
    # cap the BUY limit at the reservation price, so the fill can never be worse than the edge allows.
    meta: Dict = {}
    if client_order_id_base:
        meta["client_order_id"] = client_order_id_base
    if fair is not None:
        meta["fair"] = float(fair)
        meta["min_edge"] = float(min_edge or 0.0)
    intent = TradeIntent(action=action, side=side, ticker=ticker, qty_contracts=qty, limit_price_dollars=price,
                         model_name="app-dep-%d" % dep["id"], now_ts=datetime.now(timezone.utc), metadata=meta)
    return kernel.execute(intent)


def _order_in_flight(cur, user_id: int, ticker: str) -> bool:
    """True while this user has an unresolved order on ``ticker`` (see INFLIGHT_BLOCK_SECONDS).
    Fails open on a read error: the block is an extra layer over recovery + reconciliation, and a DB
    blip must not freeze every order."""
    try:
        return repo.ticker_has_inflight_intent(cur, user_id, ticker, INFLIGHT_BLOCK_SECONDS)
    except Exception as e:
        print("[engine] in-flight check failed user %s %s: %r (proceeding)" % (user_id, ticker, e), flush=True)
        return False


def _log_order_intent(conn, dep: Dict, action: str, side: str, ticker: str, qty: int, price: float,
                      mode: str, position_id: Optional[int] = None, reason: Optional[str] = None,
                      market_close_time=None) -> Optional[str]:
    """Durably record an order intent BEFORE the exchange POST (P0-1) and return its id (== the
    client_order_id to reuse). Its own committed transaction, so the record survives a crash the
    instant after the order is placed. Best-effort: returns None if the write fails — an EXIT must
    never be blocked by it (the caller still flattens; the net reconciler catches an unlogged fill)."""
    intent_id = str(uuid.uuid4())
    try:
        with repo.transaction(conn) as tx:
            repo.insert_order_intent(tx, intent_id, dep["id"], dep["user_id"], mode, action, side,
                                     ticker, qty, price, intent_id, position_id, reason, market_close_time)
        return intent_id
    except Exception as e:
        print("[engine] order-intent log failed dep %d %s %s %s: %r (continuing)"
              % (dep["id"], action, side, ticker, e), flush=True)
        return None


def _book_entry(conn, intent_id: Optional[str], deployment_id: int, user_id: int, mode: str, ticker: str,
                side: str, rep, market_close_time) -> bool:
    """Book a filled ENTRY as ONE transaction keyed to its intent (P0-2): claim the intent's single
    'booked' transition and, only if we won it, insert the position row. The claim makes the live
    path and crash-recovery race-safe — a fill is booked exactly once, never twice."""
    with repo.transaction(conn) as tx:
        if intent_id is not None and not repo.claim_intent_booking(
            tx, intent_id, getattr(rep, "external_order_id", None), int(rep.fill_qty_contracts), rep.fill_price_dollars,
            rep.fee_dollars, getattr(rep, "raw_json", None)
        ):
            return False  # already booked (recovery/live race) — no double position
        repo.insert_position(tx, deployment_id, user_id, mode, ticker, side, int(rep.fill_qty_contracts),
                             rep.fill_price_dollars, rep.fee_dollars, market_close_time, getattr(rep, "external_order_id", None))
    return True


def _close_position_at(conn, cur, dep: Dict, pos: Dict, kernel, via_kernel: bool, price: float, reason: str) -> bool:
    """Close one open position at `price` through this deployment's mode (live/demo kernel sell, or
    paper sell). The single exit path shared by the normal exit signal AND the drawdown force-sell —
    no force-sell-specific order mechanics. Idempotent via `close_position` (only an open row closes),
    so a retried tick never double-closes. Returns True only when the position actually closed; a
    partial live fill books nothing and waits for the next slot."""
    qty = int(pos["qty"])
    if not via_kernel:
        if kernel is not None:  # paper over the simulated venue
            return _paper_kernel_close(conn, cur, dep, pos, kernel, price, reason)
        _paper_sell(conn, pos, price, reason)
        return True
    if _order_in_flight(cur, dep["user_id"], pos["ticker"]):
        # An earlier order on this ticker may already have sold some or all of it. Selling the DB
        # quantity again could oversell into a short; wait for recovery to book the truth.
        print("[engine] exit deferred pos %d %s: an earlier order's outcome is still unknown"
              % (pos["id"], pos["ticker"]), flush=True)
        return False
    # Durable order-intent BEFORE the exchange sell (P0-1). Best-effort — an EXIT is NEVER blocked by
    # the intent log: if the write fails (intent_id is None) we STILL flatten and fall back to the
    # net reconciler. The intent carries position_id so crash-recovery knows which position to close.
    intent_id = _log_order_intent(conn, dep, "sell", pos["side"], pos["ticker"], qty, price, dep["mode"],
                                  position_id=pos["id"], reason=reason)
    rep = _live_trade(cur, dep, kernel, "sell", pos["side"], pos["ticker"], qty, price,
                      client_order_id_base=intent_id)
    filled = int(rep.fill_qty_contracts)
    if filled <= 0:
        if intent_id is not None:
            try:
                repo.mark_order_intent(cur, intent_id, "unfilled", raw_json=getattr(rep, "raw_json", None))
            except Exception:
                pass
        return False  # nothing filled this slot; retry next slot
    return _book_kernel_exit(conn, dep, pos, intent_id, rep, reason)


def _book_kernel_exit(conn, dep: Dict, pos: Dict, intent_id: Optional[str], rep, reason: str) -> bool:
    """Book a live/demo exit fill (``rep`` from the kernel, at least one contract) against its intent.
    True only when the whole row closed."""
    qty, filled = int(pos["qty"]), int(rep.fill_qty_contracts)
    if filled < qty:
        # Partial fill: contracts WERE sold on the exchange, so the fill must be recorded, not
        # dropped. Book the sold slice as realized P&L and shrink the open row to the remainder
        # (which retries next slot); otherwise settlement double-counts and we re-sell what's gone.
        # Contained: a booking failure is logged for reconciliation, never crashes the tick. The
        # intent-booking claim + book_partial_exit share ONE transaction (P0-2), keyed to the intent.
        try:
            filled_entry_fee = float(pos["entry_fee"]) * filled / qty
            pnl = filled * (rep.fill_price_dollars - float(pos["entry_price"])) - filled_entry_fee - rep.fee_dollars
            with repo.transaction(conn) as tx:
                if intent_id is not None and not repo.claim_intent_booking(
                    tx, intent_id, getattr(rep, "external_order_id", None), filled, rep.fill_price_dollars, rep.fee_dollars,
                    getattr(rep, "raw_json", None)
                ):
                    return False  # already booked by recovery
                repo.book_partial_exit(tx, pos, filled, rep.fill_price_dollars, rep.fee_dollars, pnl, reason)
        except Exception as e:
            print("[engine] partial-exit booking failed pos %d dep %d filled %d/%d: %r (will reconcile)"
                  % (pos["id"], dep["id"], filled, qty, e), flush=True)
        return False  # position not fully closed — remainder stays open
    pnl = qty * (rep.fill_price_dollars - float(pos["entry_price"])) - float(pos["entry_fee"]) - rep.fee_dollars
    with repo.transaction(conn) as tx:
        if intent_id is not None and not repo.claim_intent_booking(
            tx, intent_id, getattr(rep, "external_order_id", None), filled, rep.fill_price_dollars, rep.fee_dollars,
            getattr(rep, "raw_json", None)
        ):
            return False  # recovery already booked this exit — don't double-close
        return repo.close_position(tx, pos["id"], rep.fill_price_dollars, rep.fee_dollars, pnl, reason)


_PERPETUAL_EXECUTION_DISABLED = (
    "Bitcoin perpetuals are research-only; paper, demo and live execution are disabled."
)


def _perpetual_execution_block(spec: Dict, market_key: Optional[str] = None) -> Optional[str]:
    """Reject perpetual exposure even if a persisted row bypassed the deploy routes."""
    if specmod.has_perpetual_market(spec, market_key):
        return _PERPETUAL_EXECUTION_DISABLED
    return None


def cross_deploy_block(spec: Dict, mode: str) -> Optional[str]:
    """Why a cross-contract (relative-value pair) spec may NOT deploy in `mode`, or None if it may.

    Two disjoint cases, each self-contained so they compose:
      * MULTI-market cross (legs span >1 market): rides the synchronized multi-market feed
        (tick_cross_markets), which fetches every leg's live book+spot on one frame and skips the
        frame if any leg is stale. Deployable in ANY mode (paper/demo/live) ONLY when every leg's
        market is itself deployable (has a live book + execution path) AND the legs share a decision
        cadence (so one synchronized frame aligns them).
      * SINGLE-market cross (cross_strike / calendar): the engine already ticks that one market and
        its frame carries every strike/settlement leg, and the live/demo entry path is legging-safe
        — both legs kept balanced and any naked excess flattened on the exchange immediately (see
        `_kernel_buy_pair`) — so paper, demo AND live are all allowed.
    The OTHER live gates (gatekeeper candidate, LIVE switch, Kalshi key, the NO-side-live rollout
    flag, the typed LIVE confirm, autopilot, drawdown) are unchanged and still run upstream; this
    function also rejects research-only perpetuals (including non-cross specs) and only ever
    ADDS conditions."""
    perpetual_block = _perpetual_execution_block(spec)
    if perpetual_block:
        return perpetual_block
    if not specmod.is_cross_contract(spec):
        return None
    markets = specmod.involved_markets(spec)
    if len(markets) > 1:
        bad = [m for m in markets if m not in MARKETS or not MARKETS[m].deployable]
        if bad:
            return ("This cross-market pair touches market(s) with no live feed/execution path "
                    "(%s), so it stays research-only." % ", ".join(bad))
        if not compatible_cadence(markets):
            return ("This cross-market pair spans incompatible decision cadences (%s) — its legs "
                    "can't be ticked on one synchronized frame, so it stays research-only."
                    % ", ".join(markets))
        return None
    # Single-market cross: legging-safe entry, so paper/demo/live all allowed.
    return None


class _PaperLedger:
    """Paper booking for ``DeploymentBook``: the same functions the legacy decision path books with,
    so both paths write the same position rows and ledger lines. ``sim`` marks fills that came
    through the simulated venue (their order_ref is what the live gate counts)."""

    def __init__(self, conn, dep: Dict, contracts: Dict[str, Contract], sim: bool) -> None:
        self.conn, self.dep, self.contracts, self.sim = conn, dep, contracts, sim

    def cash(self) -> float:
        return repo.paper_balance(self.conn.cursor(), self.dep["user_id"])

    def buy(self, report) -> bool:
        iid = report.intent.instrument
        order_id = next((f.order_id for f in report.fills if f.order_id), None)
        ref = SIM_ORDER_REF_PREFIX + str(order_id or "") if self.sim else None
        return _paper_book_buy(self.conn, self.dep, iid.symbol, iid.outcome, int(report.filled_qty),
                               float(report.avg_price), float(report.fees), self.contracts[iid.symbol].close_time,
                               ref) is not None

    def sell(self, row: Dict, report) -> bool:
        return _paper_book_exit(self.conn, row, int(report.filled_qty), float(report.avg_price), float(report.fees),
                                report.intent.reason)


class _KernelLedger:
    """Demo/live booking for ``DeploymentBook``: the kernel's own report, booked against its order
    intent exactly as the legacy path books it (``_book_entry`` / ``_book_kernel_exit``). The money
    sits at the exchange, so there is no cash to check here."""

    def __init__(self, conn, dep: Dict, contracts: Dict[str, Contract]) -> None:
        self.conn, self.dep, self.contracts = conn, dep, contracts

    def cash(self) -> float:
        return 0.0

    def buy(self, report) -> bool:
        iid, meta = report.intent.instrument, report.intent.meta
        _book_entry(self.conn, meta["order_intent"], self.dep["id"], self.dep["user_id"], self.dep["mode"], iid.symbol,
                    iid.outcome, meta["venue_report"], self.contracts[iid.symbol].close_time)
        return True

    def sell(self, row: Dict, report) -> bool:
        meta = report.intent.meta
        return _book_kernel_exit(self.conn, self.dep, row, meta["order_intent"], meta["venue_report"],
                                 report.intent.reason)


class _IntentLog:
    """The engine's order-intent discipline for ``KalshiEngineExecution`` (demo/live): the in-flight
    block, the durable intent written before the order (a sell carries its row's id and reason, a
    buy its market's close time) and the unfilled mark."""

    def __init__(self, conn, cur, dep: Dict, book, contracts: Dict[str, Contract]) -> None:
        self.conn, self.cur, self.dep, self.book, self.contracts = conn, cur, dep, book, contracts

    def in_flight(self, ticker: str) -> bool:
        return _order_in_flight(self.cur, self.dep["user_id"], ticker)

    def log(self, intent, qty: int, price: float) -> Optional[str]:
        iid = intent.instrument
        if intent.side.value == "sell":
            return _log_order_intent(self.conn, self.dep, "sell", iid.outcome, iid.symbol, qty, price, self.dep["mode"],
                                     position_id=self.book.row(iid)["id"], reason=intent.reason)
        return _log_order_intent(self.conn, self.dep, "buy", iid.outcome, iid.symbol, qty, price, self.dep["mode"],
                                 market_close_time=self.contracts[iid.symbol].close_time)

    def unfilled(self, intent_id: str, report) -> None:
        try:
            repo.mark_order_intent(self.cur, intent_id, "unfilled", raw_json=getattr(report, "raw_json", None))
        except Exception:
            pass


def _decide_on_loop(conn, cur, dep: Dict, snaps: List[Snapshot], sizes: Dict, kernel) -> Optional[Dict]:
    """One decision as a TradingLoop step: ``SpecStrategy`` decides, ``EntryBudget`` holds the slot
    and user caps, ``KalshiEngineExecution`` sizes and sends through the kernel (paper: the
    simulated venue, or a fill at the limit without one; demo: the sandbox exchange, with the
    order-intent log), and ``DeploymentBook`` books into app_positions. Returns the same counts as
    the legacy path, or None when this deployment must stay on it (a spec the strategy adapter does
    not run, or two open rows on one contract)."""
    from app.adapters.db.deployment_book import DeploymentBook, DuplicateRows
    from app.adapters.kalshi import instruments as ki
    from app.adapters.kalshi.engine_execution import EntryBudget, KalshiEngineExecution
    from app.adapters.kalshi.spec_strategy import SpecStrategy, _FrameFeed
    from trading_core.engine import RiskChain, TradingLoop, one_position_per_symbol
    from trading_core.ports import FixedClock

    spec, real = dep["spec"], dep["mode"] in ("live", "demo")
    contracts = {s.contract.ticker: s.contract for s in snaps}
    feed = _FrameFeed()
    feed.load(snaps)
    ledger = _KernelLedger(conn, dep, contracts) if real else _PaperLedger(conn, dep, contracts, sim=kernel is not None)
    try:
        strategy = SpecStrategy(spec, contracts, frame=lambda: feed.snaps, sizing_at_fill=True,
                                strategy_id="app-dep-%d" % dep["id"])
        book = DeploymentBook(cur, dep["id"], ledger, read_rows=repo.open_positions)
    except (ValueError, DuplicateRows):
        return None
    instruments = {}
    for c in contracts.values():
        yes = ki.binary(c, "yes")
        instruments[yes.id], instruments[yes.complement().id] = yes, yes.complement()
    budget = EntryBudget(book, spec["sizing"]["max_positions"],
                         load=lambda: _entry_caps(cur, dep, repo.user_risk_config(cur, dep["user_id"])),
                         shown=lambda ticker, side: shown_size(sizes, ticker, side), stopped=lambda: book.out_of_cash)
    book.on_entry = budget.took
    trade = None
    if kernel is not None:
        min_edge = (spec.get("entry") or {}).get("min_edge")

        def _trade(action, side, ticker, qty, price, fair, client_order_id):
            return _live_trade(cur, dep, kernel, action, side, ticker, qty, price,
                               client_order_id_base=client_order_id, fair=fair, min_edge=min_edge)
        trade = _trade
    orders = _IntentLog(conn, cur, dep, book, contracts) if real else None
    # The kernel owns its venue, so the loop gets none. capital: SpecStrategy sizes from its stake, so
    # the ledger balance is not summed on every decision (cash is checked when an entry books).
    loop = TradingLoop(strategy, instruments, feed, None, FixedClock(time.time()),
                       execution=KalshiEngineExecution(budget, trade, orders),
                       risk=RiskChain([budget.check, one_position_per_symbol(book)]),
                       book=book, capital=lambda: 0.0, universe=lambda now: feed.current)
    loop.step()
    return {"exits": book.exits, "entries": book.entries}


def _record_scan(cur, dep: Dict, snaps: List[Snapshot], out: Dict) -> None:
    """What the entry rule saw this decision, so a quiet strategy can say why it isn't trading (the
    autopilot panel and reviews read it). Best-effort: it never touches an order or a position."""
    try:
        scan = specmod.entry_scan(dep["spec"], snaps)
        scan["entered"] = out["entries"]
        repo.set_deployment_scan(cur, dep["id"], scan)
    except Exception:
        pass


def decide(conn, dep: Dict, snaps: List[Snapshot], sizes: Dict, sources: Sources) -> Dict:
    spec = dep["spec"]
    perpetual_block = _perpetual_execution_block(spec, dep.get("market"))
    if perpetual_block:
        return {"blocked": perpetual_block}
    cur = conn.cursor()
    by_ticker = {s.contract.ticker: s for s in snaps}
    mode = dep["mode"]
    # Both live and demo route real orders through a MarketableLimitKernel with identical
    # mechanics; only the key (live vs dev) and host (production vs sandbox) differ, which
    # is baked into the respective kernel factory. Paper (no kernel) is unchanged.
    via_kernel = mode in ("live", "demo")
    kernel = None
    if via_kernel:
        if mode == "live":
            live_on = LIVE_TRADING_ENABLED and sources.live_kernel
            kernel = sources.live_kernel(dep["user_id"]) if live_on else None
            # Accurate reason: if live IS on, a None kernel means the user has no live key
            # (a transient DB/build error raises instead of returning None, so it never lands here).
            why = ("Live trading is not enabled on this server yet." if not live_on
                   else "Add your live Kalshi key on the Funds page to run this on live money.")
        else:  # demo -> sandbox exchange, signed with the user's own dev key; no LIVE switch needed
            kernel = sources.demo_kernel(dep["user_id"]) if sources.demo_kernel else None
            why = "Add your Kalshi demo (sandbox) key on the Funds page to run this on demo."
        if kernel is None:
            repo.set_deployment_status(cur, dep["user_id"], dep["id"], "paused", why)
            return {"paused": "%s disabled" % mode}
    # A book that still disagrees with the user's real Kalshi account after two reconcile sweeps
    # halts new LIVE entries until it matches again (app/reconcile.py). Exits are never blocked.
    halts = repo.live_entry_halts(cur, dep["user_id"]) if mode == "live" else []
    if mode == "paper":
        # Paper runs the live execution policy against a simulated venue when wired (pairs too, so
        # paper sees legging risk: a leg can fill short and the excess must be unwound).
        kernel = sources.paper_kernel(dep["user_id"]) if sources.paper_kernel else None
    if specmod.is_cross_contract(spec):
        if halts:
            return {"halted": "position mismatch on %s" % ", ".join(h["ticker"] for h in halts)}
        return _decide_pairs(conn, dep, snaps, sizes, kernel, via_kernel, mode)
    if mode in ENGINE_LOOP_MODES:
        out = _decide_on_loop(conn, cur, dep, snaps, sizes, kernel)
        if out is not None:
            _record_scan(cur, dep, snaps, out)
            loss_guard(cur, dep)
            return out
    out = {"exits": 0, "entries": 0}
    if halts:
        out["halted"] = "position mismatch on %s" % ", ".join(h["ticker"] for h in halts)

    positions = repo.open_positions(cur, dep["id"])
    for pos in positions:
        snap = by_ticker.get(pos["ticker"])
        sig = specmod.exit_signal(spec, pos["side"], float(pos["entry_price"]), snap) if snap else None
        if sig is None:
            continue
        reason, price = sig
        if _close_position_at(conn, cur, dep, pos, kernel, via_kernel, price, reason):
            out["exits"] += 1

    held = {p["ticker"] for p in repo.open_positions(cur, dep["id"])}
    slots = spec["sizing"]["max_positions"] - len(held)
    # Per-user portfolio caps span ALL the user's deployments: block any new entry that would push
    # the user past their open-position count or open entry-notional cap. Read once, tracked locally
    # for the entries this call adds (another deployment's concurrent adds are seen next tick).
    risk = repo.user_risk_config(cur, dep["user_id"])
    open_count, open_notional, cap_positions, cap_notional = _entry_caps(cur, dep, risk)
    ramp = _live_ramp_scale(cur, dep) if mode == "live" and not halts else 1.0
    for entry in ([] if halts else specmod.entries(spec, snaps)):
        if slots <= 0 or open_count >= cap_positions:
            break  # deployment slot cap or user-wide position cap reached
        ticker = entry.snapshot.contract.ticker
        if ticker in held:
            continue
        qty = specmod.contracts_for(spec["sizing"]["stake"], entry.price)
        if ramp < 1.0 and qty >= 1:
            qty = max(1, int(qty * ramp))  # live size ramp: a fresh live deployment trades small
        shown = shown_size(sizes, ticker, entry.side)
        if shown is not None:
            qty = min(qty, int(shown))  # never size past the depth on the side we take
        # Trim to the user-wide open-notional cap; never breach it with a new entry.
        room = cap_notional - open_notional
        if room >= entry.price:
            qty = min(qty, int(room / entry.price))
        else:
            qty = 0
        if qty < 1:
            continue
        if via_kernel:
            if _order_in_flight(cur, dep["user_id"], ticker):
                continue  # an earlier order here may have filled; never stack a second buy on it
            close_time = entry.snapshot.contract.close_time
            # Durable order-intent BEFORE the real order (P0-1). An entry is NOT sacrosanct: if the
            # intent write fails we skip it rather than place an untracked order (a missed entry
            # costs nothing; an untracked live fill is exactly the F1 hole we are closing).
            intent_id = _log_order_intent(conn, dep, "buy", entry.side, ticker, qty, entry.price, mode,
                                          market_close_time=close_time)
            if intent_id is None:
                continue
            rep = _live_trade(cur, dep, kernel, "buy", entry.side, ticker, qty, entry.price,
                              client_order_id_base=intent_id, fair=getattr(entry, "fair", None),
                              min_edge=(spec.get("entry") or {}).get("min_edge"))
            if rep.fill_qty_contracts < 1:
                try:
                    repo.mark_order_intent(cur, intent_id, "unfilled", raw_json=getattr(rep, "raw_json", None))
                except Exception:
                    pass
                continue
            # Fill -> position insert is ONE transaction keyed to the intent (P0-2), booked once.
            _book_entry(conn, intent_id, dep["id"], dep["user_id"], mode, ticker, entry.side, rep, close_time)
        elif kernel is not None:
            # Paper over the simulated venue: book only what the touch actually gave, at the fill
            # price and fee the venue charged. A miss (stale quote, edge gone) books nothing.
            # Same reservation-price cap as live, so paper never books a fill live would refuse.
            rep = _live_trade(cur, dep, kernel, "buy", entry.side, ticker, qty, entry.price,
                              fair=getattr(entry, "fair", None), min_edge=(spec.get("entry") or {}).get("min_edge"))
            if rep.fill_qty_contracts < 1:
                continue
            if _paper_book_buy(conn, dep, ticker, entry.side, int(rep.fill_qty_contracts), rep.fill_price_dollars,
                               rep.fee_dollars, entry.snapshot.contract.close_time,
                               SIM_ORDER_REF_PREFIX + str(rep.external_order_id or "")) is None:
                break  # out of paper cash
        elif _paper_buy(conn, dep, entry, qty) is None:
            break  # out of paper cash
        held.add(ticker)
        slots -= 1
        open_count += 1
        open_notional += qty * entry.price  # requested qty; a short live fill only over-counts (safe for a cap)
        out["entries"] += 1
    _record_scan(cur, dep, snaps, out)
    loss_guard(cur, dep)
    return out


def _decide_pairs(conn, dep: Dict, snaps: List[Snapshot], sizes: Dict,
                  kernel, via_kernel: bool, mode: str) -> Dict:
    """Decide a cross-contract (relative-value pair) deployment: open BOTH legs of each pair the
    rule picks (buy YES on the underpriced leg, NO on the overpriced leg) and HOLD to settlement —
    exactly the simulate_pairs rule the backtest proved, so there is no early-exit logic. Each leg
    is an ordinary position row, so settlement, marks and the loss guard all reuse the single-leg
    machinery unchanged. Only reached for paper/demo (live cross is refused at deploy)."""
    cur = conn.cursor()
    spec = dep["spec"]
    out = {"exits": 0, "entries": 0}
    positions = repo.open_positions(cur, dep["id"])
    held = {p["ticker"] for p in positions}
    # ponytail: every open position of a cross deployment is a pair leg, so pairs = legs // 2;
    # a demo partial fill could orphan a leg and under-count by one — acceptable in the sandbox.
    open_pairs = len(positions) // 2
    max_pairs = spec["sizing"]["max_positions"]
    risk = repo.user_risk_config(cur, dep["user_id"])
    open_count, open_notional, cap_positions, cap_notional = _entry_caps(cur, dep, risk)
    for cand in specmod.pair_entries(spec, snaps):
        if open_pairs >= max_pairs or open_count + 2 > cap_positions:
            break  # pair slot cap, or the user-wide position cap has no room for two more legs
        lt = cand.long_snap.contract.ticker
        st = cand.short_snap.contract.ticker
        if lt in held or st in held:
            continue
        pair_cost = cand.long_price + cand.short_price
        qty = specmod.contracts_for(spec["sizing"]["stake"], pair_cost)
        for tk, sd in ((lt, "yes"), (st, "no")):  # never size past either leg's book
            shown = shown_size(sizes, tk, sd)
            if shown is not None:
                qty = min(qty, int(shown))
        room = cap_notional - open_notional
        qty = min(qty, int(room / pair_cost)) if room >= pair_cost else 0
        if qty < 1:
            continue
        # Each leg: (side, ticker, buy_price, own-side SELL price at the bid, close_time). The sell
        # price is what _kernel_buy_pair unwinds a naked leg at (YES sells ~yes_bid; NO ~1-yes_ask).
        legs = [("yes", lt, cand.long_price, cand.long_snap.yes_bid, cand.long_snap.contract.close_time),
                ("no", st, cand.short_price, 1.0 - cand.short_snap.yes_ask, cand.short_snap.contract.close_time)]
        if via_kernel:
            placed = _kernel_buy_pair(conn, cur, dep, kernel, legs, qty, mode)
        elif kernel is not None:
            placed = _paper_kernel_buy_pair(conn, cur, dep, kernel, legs, qty)
        else:
            placed = _paper_buy_pair(conn, dep, legs, qty)
        if not placed:
            break  # out of paper cash / nothing filled this slot
        held.update((lt, st))
        open_pairs += 1
        open_count += 2
        open_notional += qty * pair_cost
        out["entries"] += 1
    loss_guard(cur, dep)
    return out


def _paper_buy_pair(conn, dep: Dict, legs, qty: int) -> bool:
    """Buy both legs of a pair in ONE transaction (so a pair is never half-opened on paper):
    check the combined cost against the paper balance once, then insert both leg positions."""
    items = []
    total = 0.0
    for side, ticker, price, _sell, close in legs:
        fee = taker_fee_dollars(qty, price)
        total += qty * price + fee
        items.append((side, ticker, price, fee, close))
    with repo.transaction(conn) as tx:
        repo.lock_user(tx, dep["user_id"])
        if repo.paper_balance(tx, dep["user_id"]) < total:
            return False
        for side, ticker, price, fee, close in items:
            pid = repo.insert_position(tx, dep["id"], dep["user_id"], "paper", ticker, side, qty, price, fee, close)
            repo.add_ledger(tx, dep["user_id"], "trade", -(qty * price + fee),
                            "Bought %d %s %s @ %.2f (pair)" % (qty, side.upper(), ticker, price), pid)
    return True


def _paper_kernel_buy_pair(conn, cur, dep: Dict, kernel, legs, qty: int) -> bool:
    """Paper pair entry through the simulated venue, with the same legging mechanics as the live
    `_kernel_buy_pair`: buy leg 1, buy leg 2 for what leg 1 got, sell any unhedged leg-1 excess,
    and track whatever that sell could not flatten as an open naked position. Nothing is sent, so
    there are no order intents; the paper ledger is debited/credited for exactly what filled.
    Both legs (and any unwind/residual slice) share one order_ref, so the live gate counts the
    pair as ONE round trip. Returns hedged >= 1."""
    l_side, l_ticker, l_buy, l_sell, l_close = legs[0]
    s_side, s_ticker, s_buy, _s_sell, s_close = legs[1]
    uid, dep_id = dep["user_id"], dep["id"]
    est = qty * (l_buy + s_buy) + taker_fee_dollars(qty, l_buy) + taker_fee_dollars(qty, s_buy)
    if repo.paper_balance(cur, uid) < est:
        return False  # out of paper cash: don't simulate an entry it could not pay for
    rep1 = _live_trade(cur, dep, kernel, "buy", l_side, l_ticker, qty, l_buy)
    f1 = int(rep1.fill_qty_contracts)
    if f1 < 1:
        return False
    rep2 = _live_trade(cur, dep, kernel, "buy", s_side, s_ticker, f1, s_buy)
    f2 = int(rep2.fill_qty_contracts)
    hedged = min(f1, f2)
    excess = f1 - hedged
    unwound = 0
    sell_rep = None
    if excess > 0:
        sell_rep = _live_trade(cur, dep, kernel, "sell", l_side, l_ticker, excess, l_sell)
        unwound = min(int(sell_rep.fill_qty_contracts), excess)
    residual = excess - unwound
    l_fee_hedged = rep1.fee_dollars * hedged / f1
    l_fee_unwound = rep1.fee_dollars * unwound / f1
    l_fee_residual = rep1.fee_dollars - l_fee_hedged - l_fee_unwound
    s_fee = rep2.fee_dollars if hedged >= 1 else 0.0
    ref = SIM_ORDER_REF_PREFIX + "pair-" + str(rep1.external_order_id or uuid.uuid4())
    with repo.transaction(conn) as tx:
        repo.lock_user(tx, uid)
        if hedged >= 1:
            repo.insert_position(tx, dep_id, uid, "paper", l_ticker, l_side, hedged,
                                 rep1.fill_price_dollars, l_fee_hedged, l_close, ref)
            pid = repo.insert_position(tx, dep_id, uid, "paper", s_ticker, s_side, hedged,
                                       rep2.fill_price_dollars, s_fee, s_close, ref)
            repo.add_ledger(tx, uid, "trade",
                            -(hedged * (rep1.fill_price_dollars + rep2.fill_price_dollars) + l_fee_hedged + s_fee),
                            "Bought %d pair %s/%s (pair)" % (hedged, l_ticker, s_ticker), pid)
        if unwound >= 1:
            pnl = (unwound * (sell_rep.fill_price_dollars - rep1.fill_price_dollars)
                   - l_fee_unwound - sell_rep.fee_dollars)
            pid = repo.insert_closed_position(tx, dep_id, uid, "paper", l_ticker, l_side, unwound,
                                              rep1.fill_price_dollars, l_fee_unwound, sell_rep.fill_price_dollars,
                                              sell_rep.fee_dollars, pnl, "pair_unwind", l_close, ref)
            repo.add_ledger(tx, uid, "trade", pnl, "Unwound %d unhedged %s %s (pair)"
                            % (unwound, l_side.upper(), l_ticker), pid)
        if residual >= 1:
            print("[engine] paper pair legging: dep %d left %d naked %s %s after the unwind under-filled"
                  % (dep_id, residual, l_side.upper(), l_ticker), flush=True)
            pid = repo.insert_position(tx, dep_id, uid, "paper", l_ticker, l_side, residual,
                                       rep1.fill_price_dollars, l_fee_residual, l_close, ref)
            repo.add_ledger(tx, uid, "trade", -(residual * rep1.fill_price_dollars + l_fee_residual),
                            "Bought %d %s %s (pair leg left naked)" % (residual, l_side.upper(), l_ticker), pid)
    return hedged >= 1


def _kernel_buy_pair(conn, cur, dep: Dict, kernel, legs, qty: int, mode: str) -> bool:
    """Legging-safe AND durable live/demo pair entry. A relative-value pair must stay balanced (equal
    YES and NO contracts), but two real kernel orders can't fill atomically — so we keep the legs
    matched by hand and flatten any naked excess on the exchange immediately, never leaving untracked
    exposure. Every exchange order carries a durable intent logged BEFORE the POST (P0), so a crash in
    the fill->write window is recoverable by client_order_id, and the whole consistent picture is
    booked in ONE transaction (both-or-neither), each leg claimed exactly once:

      1. Buy leg 1 (YES) for `qty` -> f1 filled. If f1 < 1, mark its intent unfilled, return False.
      2. Buy leg 2 (NO) for f1 -> f2 filled. hedged = min(f1, f2) (the kernel never over-fills, so
         f2 <= f1 and hedged == f2).
      3. If leg 1 over-filled (f1 > hedged), SELL the excess YES at the bid to flatten it, and book
         the round-trip P&L (pro-rated buy fee + sell fee) as a CLOSED row. Never becomes a position.
      4. If that unwind sell ITSELF under-fills, the still-naked remainder is recorded as a tracked
         OPEN position (the drawdown force-sell / loss guard will close it) and logged loudly.
      5. Record hedged legs at `hedged` qty with pro-rated fees, inside the booking transaction.

    Leg 1's real buy fee splits pro-rata across its hedged / unwound / residual slices (the residual
    takes the remainder, so no rounding drift). Each leg's buy intent is claimed once (covering the
    whole order fill); the booking transaction makes the pair all-or-nothing. A crash mid-entry (before
    the transaction) is backstopped by recover_sent_intents + the live reconciler. Returns hedged >= 1."""
    l_side, l_ticker, l_buy, l_sell, l_close = legs[0]  # long YES leg
    s_side, s_ticker, s_buy, _s_sell, s_close = legs[1]  # short NO leg
    uid, dep_id = dep["user_id"], dep["id"]
    if _order_in_flight(cur, uid, l_ticker) or _order_in_flight(cur, uid, s_ticker):
        return False  # an earlier order on a leg is unresolved; never leg in on top of it

    # Leg 1 buy: intent BEFORE the POST (never place an untracked order).
    i1 = _log_order_intent(conn, dep, "buy", l_side, l_ticker, qty, l_buy, mode, market_close_time=l_close)
    if i1 is None:
        return False
    rep1 = _live_trade(cur, dep, kernel, "buy", l_side, l_ticker, qty, l_buy, client_order_id_base=i1)
    f1 = int(rep1.fill_qty_contracts)
    if f1 < 1:
        try:
            repo.mark_order_intent(cur, i1, "unfilled")  # leg 1 never filled -> flat, nothing to unwind
        except Exception:
            pass
        return False

    # Leg 2 buy for the leg-1 fill: intent BEFORE the POST.
    i2 = _log_order_intent(conn, dep, "buy", s_side, s_ticker, f1, s_buy, mode, market_close_time=s_close)
    rep2 = _live_trade(cur, dep, kernel, "buy", s_side, s_ticker, f1, s_buy, client_order_id_base=i2) if i2 else None
    f2 = int(rep2.fill_qty_contracts) if rep2 is not None else 0
    hedged = min(f1, f2)
    excess = f1 - hedged

    # Flatten the unhedged leg-1 excess at the bid: intent BEFORE the POST.
    unwound = residual = 0
    sell_rep = None
    i3 = None
    if excess > 0:
        i3 = _log_order_intent(conn, dep, "sell", l_side, l_ticker, excess, l_sell, mode, market_close_time=l_close)
        if i3 is not None:
            sell_rep = _live_trade(cur, dep, kernel, "sell", l_side, l_ticker, excess, l_sell, client_order_id_base=i3)
            unwound = min(int(sell_rep.fill_qty_contracts), excess)  # a kernel never sells more than asked
        residual = excess - unwound

    # Split leg 1's real buy fee across its three slices so they sum back to it exactly.
    l_fee_hedged = rep1.fee_dollars * hedged / f1
    l_fee_unwound = rep1.fee_dollars * unwound / f1
    l_fee_residual = rep1.fee_dollars - l_fee_hedged - l_fee_unwound

    # Book the final consistent picture in ONE transaction (both-or-neither), each leg claimed once.
    with repo.transaction(conn) as tx:
        # Leg 1: claim once (covers the whole f1 fill), then allocate into hedged / unwound / residual.
        if repo.claim_intent_booking(tx, i1, getattr(rep1, "external_order_id", None), f1,
                                     rep1.fill_price_dollars, rep1.fee_dollars, getattr(rep1, "raw_json", None)):
            if hedged >= 1:
                repo.insert_position(tx, dep_id, uid, mode, l_ticker, l_side, hedged,
                                     rep1.fill_price_dollars, l_fee_hedged, l_close, rep1.external_order_id)
            if unwound >= 1:  # round-trip P&L of the flattened excess — booked, never held
                pnl = (unwound * (sell_rep.fill_price_dollars - rep1.fill_price_dollars)
                       - l_fee_unwound - sell_rep.fee_dollars)
                repo.insert_closed_position(tx, dep_id, uid, mode, l_ticker, l_side, unwound,
                                            rep1.fill_price_dollars, l_fee_unwound, sell_rep.fill_price_dollars,
                                            sell_rep.fee_dollars, pnl, "pair_unwind", l_close, rep1.external_order_id)
            if residual >= 1:  # unwind sell under-filled: still-naked YES — track it + shout
                print("[engine] CROSS-PAIR LEGGING RISK dep %d: %d naked %s %s after unwind under-filled "
                      "(bought %d, hedged %d, flattened %d) — recorded as a tracked position for the guard to close"
                      % (dep_id, residual, l_side.upper(), l_ticker, f1, hedged, unwound), flush=True)
                repo.insert_position(tx, dep_id, uid, mode, l_ticker, l_side, residual,
                                     rep1.fill_price_dollars, l_fee_residual, l_close, rep1.external_order_id)
        # Leg 2: claim once, insert the hedged short leg.
        if hedged >= 1 and i2 is not None and rep2 is not None:
            if repo.claim_intent_booking(tx, i2, getattr(rep2, "external_order_id", None), f2,
                                         rep2.fill_price_dollars, rep2.fee_dollars, getattr(rep2, "raw_json", None)):
                repo.insert_position(tx, dep_id, uid, mode, s_ticker, s_side, hedged,
                                     rep2.fill_price_dollars, rep2.fee_dollars, s_close, rep2.external_order_id)

    # Terminal state for intents not booked into a held position (best-effort; recovery-safe).
    if i2 is not None and hedged < 1:
        try:
            repo.mark_order_intent(cur, i2, "unfilled")
        except Exception:
            pass
    if i3 is not None:
        try:
            repo.mark_order_intent(cur, i3, "booked" if unwound >= 1 else "unfilled")
        except Exception:
            pass
    return hedged >= 1


def loss_guard(cur, dep: Dict) -> bool:
    cur.execute(
        "SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions WHERE deployment_id=%s AND status='closed'", (dep["id"],)
    )
    realized = float(cur.fetchone()["p"])
    result = dep.get("result") or {}
    worst = float((result.get("out_of_sample") or {}).get("max_drawdown") or 0)
    capital = float(result.get("capital") or dep["spec"]["sizing"]["stake"] * dep["spec"]["sizing"]["max_positions"])
    limit = max(LOSS_GUARD_MULTIPLE * worst, 0.5 * capital)
    why = None
    if realized < -limit:
        why = "Lost $%.2f, more than the $%.2f guard (2x its worst backtest drawdown)." % (-realized, limit)
    elif dep.get("mode") == "live":
        why = _live_decay_reason(cur, dep)
    if why is None:
        return False
    if repo.set_deployment_status(cur, dep["user_id"], dep["id"], "paused", why):
        repo.add_chat(cur, dep["user_id"], "system", "Paused deployment #%d automatically. %s" % (dep["id"], why))
        repo.create_run(cur, dep["user_id"], "review", dep["market"], None,
                        "Deployment #%d was auto-paused by the loss guard: %s" % (dep["id"], why), dep["id"])
    return True


# Live decay guard: a strategy reaches live money only after a statistically positive realistic
# paper record (agent.paper_evidence). If, after this many closed LIVE trades, live is losing money
# on average, the edge did not survive real execution: pause it (flatten-on-pause closes it) and let
# the review decide. Pausing only lowers risk; it never opens, resizes or blocks an exit.
LIVE_DECAY_MIN_TRADES = int(os.getenv("APP_LIVE_DECAY_MIN_TRADES", "20"))


# Live size ramp: a deployment's first LIVE_RAMP_TRADES closed live trades run at LIVE_RAMP_FRACTION
# of the spec's stake (at least 1 contract), so a fresh promotion risks a fraction of its size while
# the decay guard above is still gathering its 20 trades. Shrinks entries only; the fraction is
# clamped to (0, 1] so no setting can make a ramp larger than full size.
LIVE_RAMP_TRADES = int(os.getenv("APP_LIVE_RAMP_TRADES", "20"))
def _ramp_fraction(raw: str) -> float:
    return min(1.0, max(0.01, float(raw)))


LIVE_RAMP_FRACTION = _ramp_fraction(os.getenv("APP_LIVE_RAMP_FRACTION", "0.25"))


def _live_ramp_scale(cur, dep: Dict) -> float:
    n, _total = repo.deployment_closed_stats(cur, dep["id"])
    return LIVE_RAMP_FRACTION if n < LIVE_RAMP_TRADES else 1.0


def _live_decay_reason(cur, dep: Dict) -> Optional[str]:
    n, total = repo.deployment_closed_stats(cur, dep["id"])
    if n < LIVE_DECAY_MIN_TRADES or total >= 0:
        return None
    return ("Live is down $%.2f over its first %d closed trades ($%.2f a trade); its paper edge did not "
            "survive real execution." % (-total, n, total / n))


# -- drawdown + position-stop force-sell -----------------------------------------
# Conservative fallback if a user's drawdown_limit_pct column is unexpectedly NULL. The real
# per-user default lives in the schema (25%). A limit of 0 disables the force-sell for a user.
DRAWDOWN_LIMIT_PCT_DEFAULT = 25.0
# Position-level stop-loss: force-sell when any OPEN position is down more than this percent of its
# OWN cost (deployed capital), independent of the whole-capital drawdown guard. A small position
# that craters loses a large fraction of ITS cost but only a tiny fraction of the $capital base, so
# the drawdown guard alone never fires (the exact gap a user hit: 6 @ 79c -> 44c, -44% of cost but
# ~2% of a $100 base). Default 40%: it would have stopped that position, sits mid of the 35-50%
# range, and on a 79c entry triggers near 47c (a clearly broken position, not BTC-market noise).
# A limit of 0 disables it for a user. Fallback if the column is unexpectedly NULL.
POSITION_STOP_PCT_DEFAULT = 40.0


# Separate books (Todd, 2026-10-25, "Separate paper and live books"): a new entry is capped against
# the user's open positions IN ITS OWN MODE only, so paper tournament positions never block a live
# entry and live positions never block paper. Live keeps the user's exact limits. Paper (fake money)
# gets them times PAPER_CAP_MULTIPLE, so the tournament isn't throttled at 20 open positions.
PAPER_CAP_MULTIPLE = max(1.0, float(os.getenv("APP_PAPER_CAP_MULTIPLE", "10")))


def _entry_caps(cur, dep: Dict, risk: Dict) -> Tuple[int, float, int, float]:
    """(open positions, open entry notional, position cap, notional cap) for a new entry by `dep`."""
    mode = dep.get("mode") or "paper"
    cap_positions = int(risk["max_open_positions"])
    cap_notional = float(risk["max_open_notional"])
    if mode == "paper":
        cap_positions = int(cap_positions * PAPER_CAP_MULTIPLE)
        cap_notional = cap_notional * PAPER_CAP_MULTIPLE
    exposure = repo.user_open_exposure(cur, dep["user_id"], mode)
    return int(exposure["n"]), float(exposure["notional"]), cap_positions, cap_notional


def _deployment_capital(dep: Dict) -> float:
    """The deployment's capital base — same definition the loss guard uses."""
    result = dep.get("result") or {}
    return float(result.get("capital") or dep["spec"]["sizing"]["stake"] * dep["spec"]["sizing"]["max_positions"])


def _liquidation_price(pos: Dict) -> Optional[float]:
    """The price the position's OWN side could be sold at now, from the engine-stamped YES bid
    (`mark_price`). YES liquidates ~yes_bid; NO ~1-yes_bid (matches server._mark_fields). None
    until the first mark after entry — such a position is skipped (priced/retried next tick)."""
    mark = pos.get("mark_price")
    if mark is None:
        return None
    mark = float(mark)
    return mark if pos["side"] == "yes" else 1.0 - mark


def _mark_is_fresh(pos: Dict, now: Optional[datetime] = None) -> bool:
    """Is this position's stamped mark recent enough to drive a RISK TRIGGER (P1-2)?

    Refuses a force-sell driven by a mark PROVABLY older than APP_MARK_MAX_AGE_SECONDS — the
    stalled-feed case, where `repo.update_marks` (which always co-writes mark_price + mark_ts)
    stopped updating and the row holds a last mark with an OLD timestamp. The gate is ADDITIVE:
    with no age info (mark_ts absent, as on a legacy / not-yet-marked row) it returns True and the
    trigger is evaluated exactly as before this gate existed — missing age is never read as stale,
    only a present-and-old timestamp is. ONLY the drawdown / position-stop reads consult this; the
    exit path never does, so a stale mark can never block getting flat."""
    if MARK_MAX_AGE_SECONDS <= 0:
        return True  # gate disabled
    ts = pos.get("mark_ts")
    if ts is None:
        return True  # no age info -> behave as before the gate (additive, no suppression)
    now = now or datetime.now(timezone.utc)
    if isinstance(ts, datetime) and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    try:
        return (now - ts).total_seconds() <= MARK_MAX_AGE_SECONDS
    except TypeError:
        return True  # un-ageable mark_ts type -> no positive evidence of staleness, don't suppress


def _subscribe_ws(ws_feed, tickers) -> None:
    """Ensure the shared live-book feed is subscribed to these markets (P1-1). Idempotent (the
    feed keeps a set) and best-effort: no feed, or a disabled one, is a no-op and marks fall back
    to REST. Called from the tick so the markets we price/mark are exactly the ones we subscribe."""
    if ws_feed is None or not tickers:
        return
    try:
        ws_feed.request_subscribe(list(tickers), {})
    except Exception:
        pass


def _ws_mark_bid(ws_feed, ticker: str, now: datetime) -> Optional[float]:
    """Live websocket YES bid for `ticker` if it's fresh enough to mark against (≤MARK_WS_FRESH_
    SECONDS), else None so the caller falls back to the REST quote (P1-1). Uses the shared ws_quote
    parser — one place parses websocket messages. A silent/stale socket reads as None, not stale."""
    if ws_feed is None:
        return None
    try:
        q = ws_quote(ticker, ws_feed.get_latest(ticker))
    except Exception:
        return None
    if q is None or q.yes_bid is None or q.yes_bid <= 0:
        return None
    return q.yes_bid if q.age_seconds(now) <= MARK_WS_FRESH_SECONDS else None


def deployment_drawdown_pct(cur, dep: Dict) -> float:
    """Current drawdown from the high-water mark, as a percent of capital.

    Equity curve = cumulative realized P&L of closed positions (oldest first), with current
    unrealized (open positions marked to `mark_price`) as the final point. Drawdown is peak minus
    current — i.e. how far BELOW its own high the deployment sits RIGHT NOW, not its worst-ever dip
    (a deployment that dipped and recovered is at its high, drawdown ~0, and must not be closed).
    """
    unrealized = 0.0
    for pos in repo.open_positions(cur, dep["id"]):
        price = _liquidation_price(pos)
        if price is None or not _mark_is_fresh(pos):
            continue  # unmarked or stale (P1-2): don't drive a force-sell off it
        qty = int(pos["qty"])
        unrealized += qty * price - (qty * float(pos["entry_price"]) + float(pos["entry_fee"]))
    equity = [0.0]
    cumulative = 0.0
    for pnl in repo.deployment_realized_series(cur, dep["id"]):
        cumulative += pnl
        equity.append(cumulative)
    equity.append(cumulative + unrealized)  # equity right now
    drawdown = max(equity) - equity[-1]     # peak-to-now, >= 0
    capital = _deployment_capital(dep)
    return 100.0 * drawdown / capital if capital > 0 else 0.0


def worst_position_loss_pct(cur, dep: Dict) -> float:
    """The worst open position's CURRENT loss as a percent of its own cost (qty*entry + entry_fee).

    Loss = cost - liquidation value, side-aware via `_liquidation_price` (YES ~yes_bid, NO ~1-yes_bid).
    Returns 0 when no position is marked yet or none is at a loss. A single position that craters
    drives this past the stop even when the deployment's whole-capital drawdown is still small.
    """
    worst = 0.0
    for pos in repo.open_positions(cur, dep["id"]):
        price = _liquidation_price(pos)
        if price is None or not _mark_is_fresh(pos):
            continue  # unmarked or stale (P1-2): priced/retried next tick, never stopped off stale data
        qty = int(pos["qty"])
        cost = qty * float(pos["entry_price"]) + float(pos["entry_fee"])
        if cost <= 0:
            continue
        worst = max(worst, 100.0 * (cost - qty * price) / cost)
    return worst


def _force_close_kernel(dep: Dict, sources: Sources):
    """The same kernel the normal exit path would use for this mode — reusing the live-gate and
    demo-key checks exactly, so force-sell never obtains an execution path the engine couldn't
    already use. None when unavailable (live off / no key): the deployment is still paused and its
    positions settle at expiry."""
    mode = dep["mode"]
    if mode == "live":
        if LIVE_TRADING_ENABLED and sources.live_kernel:
            return sources.live_kernel(dep["user_id"])
        return None
    if mode == "demo":
        return sources.demo_kernel(dep["user_id"]) if sources.demo_kernel else None
    if mode == "paper" and sources.paper_kernel:
        return sources.paper_kernel(dep["user_id"])
    return None


def force_sell_if_drawn_down(conn, dep: Dict, sources: Sources) -> bool:
    """Force-close + pause this deployment if it breaches EITHER risk trigger:
      - whole-capital DRAWDOWN past the user's drawdown_limit_pct (peak-to-now / capital), or
      - any OPEN position down past position_stop_pct of its own cost (the position-level stop).
    Both are checked every tick; whichever fires wins, and both are named if both breach. Returns
    True if it breached (and was paused). Positions close via the mode's own exit path; each
    per-position close is contained: one failing close is logged and retried next tick, never
    aborts the rest or the pause. Each trigger is independently disabled by a 0 limit."""
    cur = conn.cursor()
    risk = repo.user_risk_config(cur, dep["user_id"]) or {}
    dd_limit = DRAWDOWN_LIMIT_PCT_DEFAULT
    if risk.get("drawdown_limit_pct") is not None:
        dd_limit = float(risk["drawdown_limit_pct"])
    stop_limit = POSITION_STOP_PCT_DEFAULT
    if risk.get("position_stop_pct") is not None:
        stop_limit = float(risk["position_stop_pct"])
    reasons: List[str] = []
    if dd_limit > 0:
        dd_pct = deployment_drawdown_pct(cur, dep)
        if dd_pct >= dd_limit:
            reasons.append("drawdown %.1f%% >= limit %.1f%%" % (dd_pct, dd_limit))
    if stop_limit > 0:
        loss_pct = worst_position_loss_pct(cur, dep)
        if loss_pct >= stop_limit:
            reasons.append("position down %.1f%% >= stop %.1f%% of cost" % (loss_pct, stop_limit))
    if not reasons:
        return False
    close_reason = "drawdown" if reasons[0].startswith("drawdown") else "stop"
    mode = dep["mode"]
    via_kernel = mode in ("live", "demo")
    kernel = _force_close_kernel(dep, sources)  # paper: the simulated-venue kernel, or None (instant)
    for pos in repo.open_positions(cur, dep["id"]):
        if via_kernel and kernel is None:
            break  # no execution path; pause below and let the positions settle at expiry
        price = _liquidation_price(pos)
        if price is None:
            continue  # not yet marked — retry on a later tick
        # P0-3 (closes F3): this sweep places a REAL sell every loop with no decision-slot claim, so
        # two engines would each sell the same position into an unintended short. Lease the position
        # first; only the engine that wins the claim sends the order. Paper places no real order, so
        # it needs no claim. The claim can only PREVENT a duplicate — it never blocks a legit close.
        if via_kernel and not repo.claim_position_close(cur, pos["id"], _ENGINE_ID):
            continue  # another engine is already force-closing this position
        try:
            _close_position_at(conn, cur, dep, pos, kernel, via_kernel, price, close_reason)
        except Exception as e:  # one position's close failing must not abort the pause or the others
            print("[engine] force-close failed pos %d dep %d: %r (retry next tick)"
                  % (pos["id"], dep["id"], e), flush=True)
    why = "force-closed: " + "; ".join(reasons)
    if repo.set_deployment_status(cur, dep["user_id"], dep["id"], "paused", why):
        repo.add_chat(cur, dep["user_id"], "system", "Paused deployment #%d automatically. %s" % (dep["id"], why))
        repo.create_run(cur, dep["user_id"], "review", dep["market"], None,
                        "Deployment #%d was force-closed and paused: %s" % (dep["id"], why), dep["id"])
    return True


def enforce_drawdown_limits(conn, sources: Sources) -> int:
    """Each engine loop: force-sell + pause every running deployment past its user's drawdown limit.
    One deployment's failure is contained so the sweep (and the engine loop) never crashes."""
    cur = conn.cursor()
    paused = 0
    for market in MARKETS.values():
        if not market.deployable:
            continue
        for dep in repo.running_deployments(cur, market.key):
            try:
                if force_sell_if_drawn_down(conn, dep, sources):
                    paused += 1
            except Exception as e:
                print("[engine] drawdown check failed dep %d user %d: %r (skipping)"
                      % (dep["id"], dep["user_id"], e), flush=True)
    return paused


# -- auto-flatten on pause/stop --------------------------------------------------


def flatten_deployment(conn, dep: Dict, sources: Sources) -> int:
    """Close ALL open positions of a paused/stopped deployment through its mode's own exit path
    (live/demo kernel sell, paper sell). A non-running deployment must hold NO exposure — nothing
    is actively managing it, so it is flattened. Fail-safe and fully contained like the force-sell:
    exits are NEVER blocked by a risk control; one failing close is logged and retried next sweep;
    a live/demo deployment with no execution path (gate off / no key) is logged LOUDLY and its
    positions settle at expiry (we never leave exposure silently). Returns #positions closed."""
    cur = conn.cursor()
    mode = dep["mode"]
    via_kernel = mode in ("live", "demo")
    kernel = _force_close_kernel(dep, sources)  # paper: the simulated-venue kernel, or None (instant)
    closed = 0
    for pos in repo.open_positions(cur, dep["id"]):
        if via_kernel and kernel is None:
            print("[engine] FLATTEN BLOCKED dep %d pos %d (%s): no execution path — REAL exposure "
                  "left open, settles at expiry" % (dep["id"], pos["id"], mode), flush=True)
            break
        price = _liquidation_price(pos)
        if price is None:
            continue  # not yet marked — retry next sweep
        # P0-3 (closes F3): this sweep places a REAL sell per position with no decision-slot claim, so
        # two engines would each sell the same position. Lease it first; only the winner sends the
        # order. Paper places no real order, so it needs no claim. A claim only PREVENTS a duplicate.
        if via_kernel and not repo.claim_position_close(cur, pos["id"], _ENGINE_ID):
            continue  # another engine is already flattening this position
        try:
            if _close_position_at(conn, cur, dep, pos, kernel, via_kernel, price, "flatten"):
                closed += 1
        except Exception as e:  # one close failing must not abort the rest
            print("[engine] flatten close failed pos %d dep %d: %r (retry next sweep)"
                  % (pos["id"], dep["id"], e), flush=True)
    return closed


def enforce_flatten_on_pause(conn, sources: Sources) -> int:
    """Each engine loop: a paused or stopped deployment must end up FLAT. Sweep every such
    deployment that still holds open positions and close them. Catches BOTH a manual pause/stop
    (via the API) and an auto-pause (loss/drawdown/stop guard), and retries a close that
    partial-filled or wasn't yet marked. Fully contained: one deployment's failure never stops the
    sweep or the other deployments. Returns the #positions flattened this loop."""
    cur = conn.cursor()
    flattened = 0
    for market in MARKETS.values():
        if not market.deployable:
            continue
        for dep in repo.paused_deployments_with_open_positions(cur, market.key):
            try:
                flattened += flatten_deployment(conn, dep, sources)
            except Exception as e:
                print("[engine] flatten sweep failed dep %d user %d: %r (skipping)"
                      % (dep["id"], dep["user_id"], e), flush=True)
    return flattened


# -- crash recovery of in-flight orders (EXECUTION_RISK_HARDENING P0-1, closes F1/F2 + the DR gap) --


def _match_order_fill(orders: List[Dict], client_order_id: str, side: Optional[str] = None) -> Optional[Dict]:
    """Read one intent's TOTAL fill from an exchange orders list, or None if it is indeterminate.

    One intent can send several child orders: ``client_order_id`` for the first, then ``<id>-1``,
    ``<id>-2``, ... for each escalating retry (execution_kernel.child_client_order_id). A crash or a
    timeout on any child leaves the intent 'sent', and every child that filled is real exposure, so
    the fill is the SUM over every child found, with a size-weighted average price and summed fees.

    The first child ABSENT is indeterminate (None), not 'unfilled': an IOC order that filled may not
    appear in the view we read, and wrongly booking it unfilled would drop a real position. Only a
    positively-found first order is acted on; a retry child that is absent was never sent.

    Fill prices on the wire are YES prices (order_wire_params), so a NO intent's average is flipped
    back to its own cost basis (1 - yes), exactly as the kernel parses a live fill."""
    def _num(v, d=0.0):
        try:
            return float(v) if v is not None else d
        except (TypeError, ValueError):
            return d
    base = str(client_order_id)
    found_base = False
    filled_total, weighted, fee_total, order_id = 0, 0.0, 0.0, None
    for o in orders or []:
        coid = str(o.get("client_order_id"))
        if coid == base:
            found_base = True
        elif not (coid.startswith(base + "-") and coid[len(base) + 1:].isdigit()):
            continue
        filled = int(_num(o.get("fill_count")))
        if filled <= 0:
            if order_id is None and coid == base:
                order_id = o.get("order_id")
            continue
        px = _num(o.get("average_fill_price"))
        if str(side or "").lower() == "no" and px > 0:
            px = 1.0 - px
        filled_total += filled
        weighted += px * filled
        fee_total += _num(o.get("average_fee_paid")) * filled
        order_id = o.get("order_id")
    if not found_base:
        return None
    avg = round(weighted / filled_total, 4) if filled_total else 0.0
    return {"filled": filled_total, "avg_price": avg, "fee": round(fee_total, 6), "order_id": order_id}


def _intent_min_ts(it: Dict) -> Optional[int]:
    """Unix seconds a little before the intent was logged, to bound the exchange orders read."""
    created = it.get("created_at")
    if not isinstance(created, datetime):
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return int(created.timestamp()) - 120


def _orders_since(fetch_page: Callable[[Dict], Dict], ticker: str, min_ts: Optional[int],
                  max_pages: int = 10) -> List[Dict]:
    """Every order on ``ticker`` since ``min_ts``, following the cursor (a busy ticker has more than
    one page, and the child we need may not be on the first)."""
    params: Dict = {"ticker": ticker, "limit": 200}
    if min_ts is not None:
        params["min_ts"] = min_ts
    out: List[Dict] = []
    for _ in range(max_pages):
        page = fetch_page(dict(params)) or {}
        out.extend(page.get("orders") or [])
        cursor = page.get("cursor")
        if not cursor:
            break
        params["cursor"] = cursor
    return out


def _make_order_lookup(conn) -> Callable[[Dict], Optional[Dict]]:
    """Build the recovery lookup: intent_row -> fill-dict|None, asking the exchange (the user's own
    key, the matching host) whether the intent's order filled, matched by its persisted
    client_order_id. None on ANY doubt — unknown mode, missing key, network/parse error, or order
    absent — so recovery NEVER re-sends and never mis-books; those intents stay 'sent' and surface.
    NOTE: the Kalshi orders-field mapping (fill_count/average_fill_price) is verified on the demo
    sandbox before it is trusted on live (see EXECUTION_RISK_HARDENING §9); until then absent->None
    keeps it safe (a no-op + alert), never a wrong booking."""
    from app import kalshi_account, kalshi_dev_exec
    from data_pipeline.common import api_get_auth

    def lookup(it: Dict) -> Optional[Dict]:
        mode, coid = it["mode"], it["client_order_id"]
        try:
            if mode == "demo":
                row = repo.get_kalshi_dev_key(conn.cursor(), it["user_id"])
                if row is None:
                    return None
                creds = kalshi_account.credentials_from_row(it["user_id"], row)
                orders = _orders_since(lambda p: kalshi_dev_exec.demo_orders(creds, params=p),
                                       it["ticker"], _intent_min_ts(it))
            elif mode == "live" and LIVE_TRADING_ENABLED:
                row = repo.get_kalshi_key(conn.cursor(), it["user_id"])
                if row is None:
                    return None
                creds = kalshi_account.credentials_from_row(it["user_id"], row)
                orders = _orders_since(lambda p: api_get_auth("/trade-api/v2/portfolio/orders", p,
                                                              credentials=creds),
                                       it["ticker"], _intent_min_ts(it))
            else:
                return None  # live recovery only when the live gate is on; unknown mode -> leave 'sent'
            return _match_order_fill(orders, coid, it.get("side"))
        except Exception as e:
            print("[engine] order lookup failed for intent %s: %r (leaving sent)"
                  % (it.get("intent_id"), e), flush=True)
            return None

    return lookup


def _book_recovered(conn, it: Dict, filled: int, avg_price: float, fee: float, order_id) -> None:
    """Book a recovered fill EXACTLY ONCE, keyed to the intent (same claim_intent_booking guard the
    live path uses, so a recovery/live race books once). An entry re-creates the position row; an
    exit closes (or partial-exits) the intent's own position. Idempotent: a second pass, or a race
    with the live booker, is a clean no-op."""
    rep = SimpleNamespace(fill_qty_contracts=filled, fill_price_dollars=avg_price, fee_dollars=fee,
                          external_order_id=str(order_id) if order_id is not None else None, raw_json=None)
    if it["action"] == "buy":
        _book_entry(conn, it["intent_id"], it["deployment_id"], it["user_id"], it["mode"], it["ticker"],
                    it["side"], rep, it.get("market_close_time"))
        return
    # Exit: close the intent's own position. close_position/book_partial_exit are idempotent against
    # the 'open' guard, and claim_intent_booking ensures the booking happens once.
    cur = conn.cursor()
    pos = repo.get_position(cur, it["position_id"]) if it.get("position_id") is not None else None
    if pos is None or pos["status"] != "open":
        repo.mark_order_intent(cur, it["intent_id"], "booked", getattr(rep, "external_order_id", None), filled, avg_price, fee)
        return  # the position is already closed (settled or booked elsewhere) — nothing to re-close
    qty = int(pos["qty"])
    reason = it.get("reason") or "recovered"
    with repo.transaction(conn) as tx:
        if not repo.claim_intent_booking(tx, it["intent_id"], getattr(rep, "external_order_id", None), filled, avg_price, fee):
            return
        if filled >= qty:
            pnl = qty * (avg_price - float(pos["entry_price"])) - float(pos["entry_fee"]) - fee
            repo.close_position(tx, pos["id"], avg_price, fee, pnl, reason)
        else:
            filled_entry_fee = float(pos["entry_fee"]) * filled / qty
            pnl = filled * (avg_price - float(pos["entry_price"])) - filled_entry_fee - fee
            repo.book_partial_exit(tx, pos, filled, avg_price, fee, pnl, reason)


def _past_resolution_horizon(it: Dict, now: datetime) -> bool:
    """True once asking the exchange about this 'sent' intent again cannot help (see
    UNRESOLVED_AFTER_CLOSE_SECONDS)."""
    def aware(dt):
        if not isinstance(dt, datetime):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    close, created = aware(it.get("market_close_time")), aware(it.get("created_at"))
    if close is not None:
        return (now - close).total_seconds() > UNRESOLVED_AFTER_CLOSE_SECONDS
    return created is not None and (now - created).total_seconds() > UNRESOLVED_NO_CLOSE_SECONDS


def recover_sent_intents(conn, sources: Sources, older_than_seconds: int = 30) -> int:
    """Deterministic crash recovery (P0-1): for each order-intent left 'sent' (POST issued, outcome
    unknown — the F1/F2 crash / lost-response window), ask the exchange whether it filled and book it
    EXACTLY ONCE or mark it unfilled. NEVER re-sends an order; when the outcome can't be determined
    the intent stays 'sent' (safe) and is surfaced. Fully contained: one intent's failure never
    aborts the rest or the engine loop. Returns the number of intents resolved this pass."""
    cur = conn.cursor()
    lookup = sources.order_lookup
    if lookup is None:
        return 0
    resolved = 0
    now = datetime.now(timezone.utc)
    for it in repo.open_sent_intents(cur, older_than_seconds):
        if _past_resolution_horizon(it, now):
            try:
                repo.mark_order_intent(cur, it["intent_id"], "unresolved")
                _unrecovered_logged.pop(str(it.get("intent_id")), None)
                print("[engine] GAVE UP on in-flight order intent %s (%s %s %s x%d): the exchange never "
                      "accounted for it and its market closed long ago; marked 'unresolved'"
                      % (it.get("intent_id"), it.get("mode"), it.get("action"), it.get("ticker"), it.get("qty")),
                      flush=True)
            except Exception as e:
                print("[engine] could not mark intent %s unresolved: %r" % (it.get("intent_id"), e), flush=True)
            continue
        try:
            fill = lookup(it)
        except Exception as e:
            print("[engine] recovery lookup raised for intent %s: %r (leaving sent)"
                  % (it.get("intent_id"), e), flush=True)
            continue
        if fill is None:
            key = str(it.get("intent_id"))
            if time.time() - _unrecovered_logged.get(key, 0.0) >= UNRECOVERED_LOG_EVERY_SECONDS:
                _unrecovered_logged[key] = time.time()  # loud, but once an hour per intent, not every pass
                print("[engine] UNRECOVERED in-flight order intent %s (%s %s %s x%d) — left 'sent', needs attention"
                      % (it.get("intent_id"), it.get("mode"), it.get("action"), it.get("ticker"), it.get("qty")),
                      flush=True)
            continue  # indeterminate — NEVER re-send
        try:
            filled = int(fill.get("filled") or 0)
            if filled <= 0:
                repo.mark_order_intent(cur, it["intent_id"], "unfilled")  # IOC that didn't fill is gone
            else:
                _book_recovered(conn, it, filled, float(fill.get("avg_price") or 0),
                                float(fill.get("fee") or 0), fill.get("order_id"))
            resolved += 1
        except Exception as e:
            print("[engine] recovery booking failed for intent %s: %r (leaving sent)"
                  % (it.get("intent_id"), e), flush=True)
    return resolved


def tick_market(conn, market: Market, sources: Sources, now: Optional[datetime] = None) -> Dict:
    if market.kind == "perpetual":
        return {"blocked": _PERPETUAL_EXECUTION_DISABLED}
    now = now or datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    stats = {"settled": settle_due(conn, market, sources, now)}
    try:
        if score_early_exits(conn, market, sources, now):
            stats["exits_scored"] = True
    except Exception as e:  # a readout; a lookup blip must never stop the tick
        print("[engine] early-exit scoring failed for %s: %r" % (market.key, e), flush=True)
    slot = now_ts - now_ts % market.decision_seconds
    cur = conn.cursor()
    # A multi-market cross deployment is stored under its primary leg's market, so it surfaces here,
    # but it must decide on a SYNCHRONIZED frame of ALL its legs (tick_cross_markets owns it) — never
    # on this single market's snaps alone. Skip it here so it's decided in exactly one place.
    # Agent-written code never runs here: its paper deployments are traded by the sandbox replay
    # (app/services/code_paper.py), which owns their last_decision_ts.
    due = [d for d in repo.running_deployments(cur, market.key)
           if d["last_decision_ts"] < slot and not _is_multi_market_cross(d["spec"])
           and not specmod.is_code_spec(d["spec"])]
    late = now_ts - slot > max(60, market.decision_seconds * LATE_FRACTION)
    # Fetch the live book whenever there's a decision to make OR any open position to mark. Marking
    # runs EVERY tick (not only when a decision is due), so unrealized P&L — and the drawdown
    # force-sell that reads these marks — track the current bid instead of a stale hourly/daily mark.
    need_book = bool(due) or repo.market_has_open_positions(cur, market.key)
    quotes = sources.quotes(market) if need_book else []
    if quotes:
        # Mark off the ≤1s websocket top-of-book when it's fresh, with the REST quote as the
        # freshness backstop (P1-1). Subscribe the markets we're reading so the shared feed has
        # them next tick. No/stale socket => REST yes_bid, exactly as before — never a regression.
        _subscribe_ws(sources.ws_feed, [q.contract.ticker for q in quotes])
        marks: Dict[str, float] = {}
        for q in quotes:
            bid = _ws_mark_bid(sources.ws_feed, q.contract.ticker, now)
            if bid is None:
                bid = q.yes_bid
            if bid is not None:
                marks[q.contract.ticker] = bid
        try:
            stats["marked"] = repo.update_marks(cur, market.key, marks, now)
        except Exception:
            pass
    if not due:
        return stats
    # Series features price strike-vs-spot for underlying markets; an outcome-settled market
    # (sports, underlying=None) has no spot, so its snapshot carries only book features - exactly
    # as the backtester builds it. {} (not None) means "no spot, trade anyway"; None means skip
    # (late slot, or an underlying whose spot feed is stale - don't trade a different rule).
    if late:
        feats = None
    elif market.underlying is None:
        feats = _event_feats(market, now_ts)
    else:
        try:
            series = sources.spot(market)
            feats = _with_cross(market, sources, now_ts, series.features_at(now_ts) if series is not None else None)
        except Exception as e:  # a spot-feed hiccup on one market must not crash the engine loop
            print("[engine] spot fetch failed for %s: %r (skipping tick)" % (market.key, e), flush=True)
            feats = None
    micro = _micro_for(sources, [q.contract.ticker for q in quotes], now_ts) if feats is not None else {}
    book = _forecast_book(market, sources, now_ts) if feats is not None else None
    snaps = [s for s in (_contract_snapshot(market, feats, q, now_ts, micro, book) for q in quotes) if s is not None]
    sizes = book_sizes(quotes)
    # (positions were already marked above, every tick — not only when a decision is due)
    stats["decided"] = 0
    for dep in due:
        if not repo.claim_decision(cur, dep["id"], slot):
            continue  # another engine has it
        if late or feats is None:
            continue  # stale inputs or a late slot: skip it rather than trade a different rule
        try:
            decide(conn, dep, snaps, sizes, sources)
            stats["decided"] += 1
        except Exception as e:  # one user's blip (DB hiccup, bad key) must not stop the whole engine
            print("[engine] decide failed dep %d user %d: %r (skipping)"
                  % (dep["id"], dep["user_id"], e), flush=True)
    return stats


# -- synchronized multi-market tick (cross-MARKET relative value) ----------------
# A cross-MARKET pair (e.g. BTC vs ETH) trades two DIFFERENT markets at once, so it can't ride a
# single market's tick: both legs must be priced on ONE decision frame. tick_cross_markets fetches
# every involved market's live book + spot TOGETHER and, only if every leg is fresh, routes the
# combined Snapshot list to decide()->_decide_pairs (the same rule the merged-dataset backtest
# proved). The staleness rule is the legging-safety contract: if ANY leg's book or spot is stale /
# unavailable / the slot is late, the whole frame is skipped and nothing is claimed — so a pair is
# never half-entered with a naked leg in a second market. _kernel_buy_pair (unchanged, market-
# agnostic) still enters/unwinds each pair's two legs; this path only guarantees it a fresh frame.


def _is_multi_market_cross(spec: Dict) -> bool:
    """A cross spec whose legs span >1 market — the only kind that needs the synchronized feed."""
    return specmod.is_cross_contract(spec) and len(specmod.involved_markets(spec)) > 1


def _cross_market_frame(markets: List[str], sources: Sources, now_ts: int):
    """Fetch EVERY involved market's live book + spot for one synchronized decision frame and build
    the combined (snaps, sizes). Returns None if ANY leg is stale or its book is unavailable — the
    caller then skips the frame, so we never price/leg a pair off a market we can't read right now."""
    if any(MARKETS[key].kind == "perpetual" for key in markets):
        return None  # a persisted cross row must never fetch/price perpetuals as binary legs
    all_snaps: List[Snapshot] = []
    sizes: Dict = {}
    for key in markets:
        market = MARKETS[key]
        try:
            quotes = sources.quotes(market)
        except Exception as e:
            print("[engine] cross quote fetch failed for %s: %r (skipping frame)" % (key, e), flush=True)
            return None
        if not quotes:
            return None  # this leg's book is unavailable this frame — never leg into it
        if market.underlying is None:
            feats: Optional[Dict[str, float]] = _event_feats(market, now_ts)  # outcome-settled leg: no spot
        else:
            try:
                series = sources.spot(market)
            except Exception as e:
                print("[engine] cross spot fetch failed for %s: %r (skipping frame)" % (key, e), flush=True)
                return None
            feats = _with_cross(market, sources, now_ts, series.features_at(now_ts) if series is not None else None)
            if feats is None:
                return None  # stale/missing spot on this leg — skip the whole frame
        micro = _micro_for(sources, [q.contract.ticker for q in quotes], now_ts)
        book = _forecast_book(market, sources, now_ts)
        for q in quotes:
            s = _contract_snapshot(market, feats, q, now_ts, micro, book)
            if s is not None:
                all_snaps.append(s)
        sizes.update(book_sizes(quotes))
    return all_snaps, sizes


def _tick_cross_group(conn, markets: List[str], deps: List[Dict], sources: Sources, now_ts: int) -> int:
    """Decide one group of cross-market deployments that share the same involved-market set. The
    legs share a decision cadence (enforced at spec validation + the deploy gate), so one slot
    serves them all. Claims happen ONLY after a fresh synchronized frame is in hand, so a stale/late
    frame never burns the slot and never enters a pair. Returns how many deployments decided."""
    cur = conn.cursor()
    decision_seconds = MARKETS[markets[0]].decision_seconds
    slot = now_ts - now_ts % decision_seconds
    due = [d for d in deps if d["last_decision_ts"] < slot]
    if not due:
        return 0
    if now_ts - slot > max(60, decision_seconds * LATE_FRACTION):
        return 0  # late slot: the backtest decided at the boundary — skip, don't trade a different rule
    frame = _cross_market_frame(markets, sources, now_ts)
    if frame is None:
        return 0  # a leg is stale/unavailable — skip the frame, never leg into a stale second market
    snaps, sizes = frame
    decided = 0
    for dep in due:
        if not repo.claim_decision(cur, dep["id"], slot):
            continue  # another engine owns this slot
        try:
            decide(conn, dep, snaps, sizes, sources)
            decided += 1
        except Exception as e:  # one deployment's blip must not stop the rest / the engine
            print("[engine] cross decide failed dep %d user %d: %r (skipping)"
                  % (dep["id"], dep["user_id"], e), flush=True)
    return decided


def tick_cross_markets(conn, sources: Sources, now: Optional[datetime] = None) -> Dict:
    """Tick every running MULTI-market cross deployment on a synchronized frame of all its legs.
    Each such deployment is stored under its primary leg's market column, so one pass over the
    deployable markets finds each exactly once (a deployment has a single market column). They are
    grouped by their involved-market set; each group decides together on its shared cadence."""
    now = now or datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    cur = conn.cursor()
    groups: Dict[tuple, List[Dict]] = {}
    for market in MARKETS.values():
        if not market.deployable:
            continue
        for dep in repo.running_deployments(cur, market.key):
            if _is_multi_market_cross(dep["spec"]):
                groups.setdefault(tuple(specmod.involved_markets(dep["spec"])), []).append(dep)
    stats = {"decided": 0}
    for markets, deps in groups.items():
        try:
            stats["decided"] += _tick_cross_group(conn, list(markets), deps, sources, now_ts)
        except Exception as e:  # one group's failure must not stop the others / the engine loop
            print("[engine] cross-market tick failed for %s: %r (skipping)" % ("+".join(markets), e), flush=True)
    return stats


REVIEW_EVERY = timedelta(hours=24)


def schedule_reviews(cur) -> int:
    """The agent's daily look at every user with something running."""
    cur.execute(
        """SELECT DISTINCT d.user_id FROM app_deployments d
           WHERE d.status='running' AND NOT EXISTS (
             SELECT 1 FROM app_agent_runs r WHERE r.user_id=d.user_id AND r.kind='review' AND r.created_at >= %s)""",
        (repo.now_utc() - REVIEW_EVERY,),
    )
    users = [r["user_id"] for r in cur.fetchall()]
    for uid in users:
        repo.create_run(cur, uid, "review", None, None, "Daily check-in on running deployments.")
    return len(users)


def enforce_autopilot_limits(conn) -> int:
    """Kill switch: any user whose live autopilot has lost its daily limit today gets live
    autopilot turned OFF and every running LIVE deployment paused at once. Runs each engine loop."""
    cur = conn.cursor()
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    killed = 0
    for u in repo.autopilot_live_over_limit(cur, day_start):
        repo.set_autopilot_live(cur, u["id"], False)
        loss = -float(u["realized"])
        repo.add_chat(cur, u["id"], "system",
                      "Live autopilot auto-disabled: today's live loss $%.2f hit your $%.2f daily limit. "
                      "Pausing live deployments." % (loss, float(u["lim"])))
        for d in repo.list_deployments(cur, u["id"]):
            if d["mode"] == "live" and d["status"] == "running":
                repo.set_deployment_status(cur, u["id"], d["id"], "paused", "Autopilot daily loss limit hit")
        killed += 1
    return killed


def enforce_account_equity_limits(conn) -> int:
    """Kill switch on the user's REAL Kalshi account, not our book: if account equity (cash plus
    Kalshi's own position value) has fallen by the user's daily loss limit since the first reading
    of the UTC day, turn live autopilot off and pause every running LIVE deployment, exactly like
    enforce_autopilot_limits. That one reads only booked P&L, so a fill we never recorded, a fee we
    under-counted or an open position marked down never trips it. A withdrawal reads as a loss
    (stops early, the safe side); a deposit masks one. Read-only against the exchange."""
    from app import kalshi_account
    from data_pipeline.common import kalshi_account_equity_dollars

    cur = conn.cursor()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    killed = 0
    for u in repo.users_for_equity_guard(cur):
        uid, lim = int(u["id"]), float(u["lim"] or 0)
        if lim <= 0:
            continue
        try:
            creds = kalshi_account.credentials_from_row(uid, repo.get_kalshi_key(cur, uid))
            equity = kalshi_account_equity_dollars(creds)
        except Exception as e:  # contained per user
            print("[engine] equity read failed for user %d: %r" % (uid, e), flush=True)
            continue
        if equity is None:
            continue
        loss = repo.equity_day_start(cur, uid, day, equity) - equity
        if loss < lim:
            continue
        if u.get("autopilot_live"):
            repo.set_autopilot_live(cur, uid, False)
        for d in repo.list_deployments(cur, uid):
            if d["mode"] == "live" and d["status"] == "running":
                repo.set_deployment_status(cur, uid, d["id"], "paused", "Kalshi account daily loss limit hit")
        repo.add_chat(cur, uid, "system",
                      "Live trading stopped: your Kalshi account is down $%.2f today (equity $%.2f), past "
                      "your $%.2f daily limit. Live autopilot is off and live deployments are paused."
                      % (loss, equity, lim))
        killed += 1
    return killed


SIM_ORDER_REF_PREFIX = "sim:"  # order_ref of a paper position filled through the simulated venue


def _execution_kernel(submitter, feed, xc: Dict):
    """The ONE execution policy every mode runs: live, demo and simulated paper differ only in the
    submitter. `xc` is the user's execution overrides (set by the co-pilot's set_exec, clamped to a
    safe envelope); a NULL value falls back to the global KALSHI_MAX_* env default. Each knob can
    only shrink or abandon an order and never blocks an exit, so this never loosens safety."""
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel

    def _exec(col: str, env: str) -> Optional[float]:
        v = xc.get(col)
        return float(v) if v is not None else _opt_float(os.getenv(env))

    # Market-order-like entries: cross through the touch and take the current best
    # ask quickly (IOC), rather than resting a passive limit. The slippage cap keeps
    # it from paying an absurd price if the book is thin; raise KALSHI_MAX_ENTRY_SLIPPAGE
    # toward 0.99 for a true "take whatever's there" market order. All tunable by env.
    return MarketableLimitKernel(
        submitter, feed,
        entry_cross_ticks=int(os.getenv("KALSHI_ENTRY_CROSS_TICKS", "2")),
        exit_cross_ticks=int(os.getenv("KALSHI_EXIT_CROSS_TICKS", "2")),
        max_entry_slippage=float(os.getenv("KALSHI_MAX_ENTRY_SLIPPAGE", "0.10")),
        max_attempts=int(os.getenv("KALSHI_ORDER_MAX_ATTEMPTS", "3")),
        max_quote_age_seconds=float(os.getenv("KALSHI_MAX_QUOTE_AGE_SECONDS", "2.0")),
        # Thin-book controls, all off unless set (see MarketableLimitKernel). Each can only
        # shrink or abandon an order, and none can block an exit, so enabling any is a
        # strictly-stricter change, tunable without a redeploy.
        max_book_fraction=_exec("exec_max_book_fraction", "KALSHI_MAX_BOOK_FRACTION"),
        max_entry_spread=_exec("exec_max_entry_spread", "KALSHI_MAX_ENTRY_SPREAD"),
        max_order_notional=_exec("exec_max_order_notional", "KALSHI_MAX_ORDER_NOTIONAL"),
    )


def live_kernel_factory(conn, ws_feed=None) -> Callable[[int], object]:
    """user_id -> MarketableLimitKernel signing with that user's own key.

    `ws_feed` (the shared WsTickerFeed) makes order pricing read the live websocket book first
    (≤1s, pushed on every top-of-book change) with REST as the freshness backstop (P1-1); None
    => REST-only, exactly as before."""
    from app import kalshi_account
    from app.execution import guarded_submitter, timed_submitter
    from data_pipeline.architecture.position_guard import exchange_net_reader, position_guarded_submitter
    from data_pipeline.market_data import MarketFeed

    feed = MarketFeed(ws_feed=ws_feed)

    def make(user_id: int):
        cur = conn.cursor()
        row = repo.get_kalshi_key(cur, user_id)
        if row is None:
            return None
        creds = kalshi_account.credentials_from_row(user_id, row)
        # P1-3: every real order first passes the process-wide execution guards (kill switch,
        # fat-finger, rate limit, circuit breaker). They only ever block a BUY, never an exit.
        # P2: timed_submitter is the outermost wrapper so it also measures guard-blocked and
        # errored sends; it records off the send path and passes the result through unchanged.
        # Innermost: no SELL may take this user's account past flat, sized to what Kalshi
        # (not our book) says they hold. Like the guards above it can only shrink/refuse a sell.
        submitter = timed_submitter(guarded_submitter(position_guarded_submitter(
            kalshi_account.order_submitter(creds), exchange_net_reader(creds))), mode="live")
        return _execution_kernel(submitter, feed, repo.user_execution_config(cur, user_id))

    return make


def paper_kernel_factory(conn, ws_feed=None) -> Optional[Callable[[int], object]]:
    """user_id -> the live execution kernel over a SimulatedVenue, which never sends an order.

    Paper then misses entries on a stale quote or a moved ask, fills only the size resting at the
    touch, pays the fee on the fill price and can fail to exit, all exactly as live does. That is
    what makes paper results evidence for the live gate. The real-order guards (kill switch, rate
    limit) are deliberately NOT applied: paper must not spend the live order budget. Returns None
    when APP_PAPER_REALISTIC_FILLS=0 (legacy instant fills at the quote)."""
    if os.getenv("APP_PAPER_REALISTIC_FILLS", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    from data_pipeline.architecture.simulated_venue import SimulatedVenue
    from data_pipeline.market_data import MarketFeed

    feed = MarketFeed(ws_feed=ws_feed)
    venue = SimulatedVenue(feed, max_quote_age_seconds=float(os.getenv("KALSHI_MAX_QUOTE_AGE_SECONDS", "2.0")))

    def make(user_id: int):
        return _execution_kernel(venue, feed, repo.user_execution_config(conn.cursor(), user_id))

    make.venue, make.feed = venue, feed  # read by paper_fill_stats for the engine log
    return make


def paper_fill_stats(paper_kernel) -> Optional[str]:
    """One log line on how simulated paper orders are faring: orders sent and filled through the
    SimulatedVenue, and where pricing quotes came from. A low fill rate or many quote misses means
    paper is starved of evidence (stale book), which the live gate would then never see."""
    venue = getattr(paper_kernel, "venue", None)
    if venue is None:
        return None
    sent, filled = int(venue.orders_sent), int(venue.orders_filled)
    rate = (100.0 * filled / sent) if sent else 0.0
    quotes = dict(getattr(getattr(paper_kernel, "feed", None), "stats", None) or {})
    return "[engine] paper sim: %d orders sent, %d filled (%.0f%%); quotes %s" % (sent, filled, rate, quotes)


def run_forever() -> None:
    from app.adapters.polymarket import store as pm_store
    from data_pipeline.common import get_db_conn

    from app.kalshi_dev_exec import demo_kernel_factory

    last_review = 0.0
    last_reconcile = 0.0
    last_equity_check = 0.0
    # How often to read each live user's real Kalshi equity for the account loss kill switch.
    equity_every = float(os.getenv("APP_EQUITY_CHECK_EVERY_SECONDS", "60"))
    # How often to reconcile each user's live book against their real Kalshi account.
    reconcile_every = float(os.getenv("APP_RECONCILE_EVERY_SECONDS", "300"))
    last_perps_watch = 0.0
    perps_watch_every = float(os.getenv("TAU_KALSHI_PERPS_WATCH_EVERY_SECONDS", "60"))
    # One shared live-book websocket for the whole engine (P1-1): marks, PnL and order pricing all
    # read ≤1s top-of-book from it, with REST as the freshness backstop. If WS creds are absent it
    # stays disabled and every read falls back to REST exactly as before — so this never regresses.
    ws_feed = None
    try:
        from data_pipeline.forward_collector import WsTickerFeed
        ws_feed = WsTickerFeed()
        ws_feed.start()
    except Exception as e:
        print("[engine] websocket feed unavailable, pricing/marks fall back to REST: %r" % e, flush=True)
        ws_feed = None
    while True:
        try:
            conn = get_db_conn()
            # Demo (sandbox) execution needs no LIVE switch, but a demo-host misconfig must never
            # take down paper/live: build it defensively and carry on without it if it can't.
            try:
                demo_kernel = demo_kernel_factory(conn, ws_feed=ws_feed)
            except Exception as e:
                print("[engine] demo execution unavailable: %r" % e, flush=True)
                demo_kernel = None
            sources = Sources(
                cross_spot=fetch_product_series,
                live_kernel=live_kernel_factory(conn, ws_feed=ws_feed) if LIVE_TRADING_ENABLED else None,
                demo_kernel=demo_kernel,
                paper_kernel=paper_kernel_factory(conn, ws_feed=ws_feed),
                order_lookup=_make_order_lookup(conn),
                ws_feed=ws_feed,
                micro=lambda tickers, ts: repo.latest_micro(conn.cursor(), tickers, ts),
                forecasts=lambda station, kind, ts: repo.load_weather_forecasts(
                    conn.cursor(), station, kind,
                    (datetime.fromtimestamp(ts, tz=timezone.utc) - timedelta(days=weather_fcst.BIAS_DAYS * 2)).date(), ts),
                weather_actuals=lambda series, ts: [r for r in repo.load_weather_actuals(
                    conn.cursor(), series, datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
                    - timedelta(days=weather_fcst.BIAS_DAYS * 2)) if r[0] <= ts],
                odds=lambda sport, ts: repo.load_sports_odds(
                    conn.cursor(), sport, datetime.fromtimestamp(ts - int(sports_odds.MAX_AGE_MIN * 60), tz=timezone.utc)
                    .replace(tzinfo=None), ts),
                options=lambda ts: repo.latest_options_surface(conn.cursor(), ts),
                polymarket=lambda ts: pm_store.latest_snapshot(conn.cursor(), ts),
            )
            # Deterministic crash recovery (P0-1): before the loop (so it also runs on every
            # reconnect / box reboot), reconcile any order-intent left 'sent' by a prior crash
            # against the exchange and book or discard it exactly once. Contained.
            last_recover = 0.0
            try:
                recover_sent_intents(conn, sources)
            except Exception as e:
                print("[engine] boot recovery failed: %r" % e, flush=True)
            try:
                while True:
                    for market in MARKETS.values():
                        if not market.deployable:
                            continue  # research-only markets never enter the trading loop
                        stats = tick_market(conn, market, sources)
                        if stats.get("decided") or stats.get("settled"):
                            print("[engine] %s %s" % (market.key, stats), flush=True)
                    # Cross-MARKET pairs belong to no single market tick: decide them on a
                    # synchronized frame of all their legs (skipped if any leg is stale).
                    try:
                        xstats = tick_cross_markets(conn, sources)
                        if xstats.get("decided"):
                            print("[engine] cross-market %s" % xstats, flush=True)
                    except Exception as e:  # contained: never stop the single-market loop
                        print("[engine] cross-market tick failed: %r" % e, flush=True)
                    if time.time() - last_review > 600:
                        schedule_reviews(conn.cursor())
                        last_review = time.time()
                        line = paper_fill_stats(sources.paper_kernel)
                        if line:
                            print(line, flush=True)
                    try:
                        repo.engine_heartbeat(conn.cursor(), LIVE_TRADING_ENABLED)
                    except Exception:
                        pass  # a heartbeat write must never stop the trading loop
                    # Risk force-sell: close + pause any deployment past its user's drawdown limit.
                    # Runs for every mode (paper/demo/live); live only closes when the live gate is on
                    # (otherwise pause-only). Fully contained so it can never stop the trading loop.
                    try:
                        enforce_drawdown_limits(conn, sources)
                    except Exception as e:
                        print("[engine] drawdown enforcement failed: %r" % e, flush=True)
                    # Auto-flatten: a paused/stopped deployment (manual OR auto-paused) must hold no
                    # exposure. Runs after the drawdown sweep so anything it just paused is swept too,
                    # and retries any close that partial-filled. Contained — never stops the loop.
                    try:
                        enforce_flatten_on_pause(conn, sources)
                    except Exception as e:
                        print("[engine] flatten-on-pause enforcement failed: %r" % e, flush=True)
                    # Catch in-process orphans too (a swallowed timeout mid-run, not only a crash):
                    # re-reconcile 'sent' intents every RECOVER_EVERY_SECONDS. Cheap when there are
                    # none (one indexed read); while one is open its ticker is blocked
                    # (INFLIGHT_BLOCK_SECONDS), so resolve it fast. Contained; never re-sends.
                    if time.time() - last_recover > RECOVER_EVERY_SECONDS:
                        try:
                            recover_sent_intents(conn, sources)
                        except Exception as e:
                            print("[engine] periodic recovery failed: %r" % e, flush=True)
                        last_recover = time.time()
                    if LIVE_TRADING_ENABLED:
                        try:
                            enforce_autopilot_limits(conn)
                        except Exception as e:
                            print("[engine] autopilot limit check failed: %r" % e, flush=True)
                        if time.time() - last_equity_check > equity_every:
                            try:
                                if enforce_account_equity_limits(conn):
                                    print("[engine] account equity kill switch tripped", flush=True)
                            except Exception as e:
                                print("[engine] account equity check failed: %r" % e, flush=True)
                            last_equity_check = time.time()
                    # Live position reconciliation: compare each user's book to their real
                    # Kalshi account. Read-only against the exchange; it only writes the audit
                    # trail + user notifications. Fully contained so it can never stop the loop.
                    if LIVE_TRADING_ENABLED and time.time() - last_reconcile > reconcile_every:
                        try:
                            from app import reconcile
                            summary = reconcile.reconcile_all(conn)
                            if summary.get("discrepancies") or summary.get("errors"):
                                print("[engine] reconcile %s" % summary, flush=True)
                        except Exception as e:
                            print("[engine] reconcile sweep failed: %r" % e, flush=True)
                        last_reconcile = time.time()
                    # Same idea for native Bitcoin perps: positions vs Tau's filled orders,
                    # plus liquidation and margin proximity. Read-only, contained.
                    if time.time() - last_perps_watch > perps_watch_every:
                        try:
                            from app import kalshi_perps_watch
                            summary = kalshi_perps_watch.watch_all(conn)
                            if summary.get("alerts") or summary.get("errors"):
                                print("[engine] perps watch %s" % summary, flush=True)
                        except Exception as e:
                            print("[engine] perps watch sweep failed: %r" % e, flush=True)
                        last_perps_watch = time.time()
                    time.sleep(TICK_SECONDS)
            finally:
                conn.close()
        except Exception as e:  # reconnect and carry on; a silent dead engine is the worst failure here
            print("[engine] ERROR %s" % e, flush=True)
            time.sleep(5)
