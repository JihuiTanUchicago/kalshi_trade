"""The two markets Tau trades, and the one feature snapshot both the
backtester and the live engine read.

Backtest and deployment must evaluate the identical rule on identical inputs,
or a passed backtest proves nothing about what gets deployed. So there is
exactly one place features are computed (`BtcSeries.features_at` +
`snapshot`), and both callers feed it the same shape of data: one-minute BTC
closes and a top-of-book quote for each contract.
"""
from __future__ import annotations

import bisect
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from app.adapters.data.options_fair import FEATURE_DOCS as _OPTIONS_DOCS
from data_pipeline.polymarket import FEATURE_DOCS as _POLYMARKET_DOCS
from app.adapters.data.sports_odds import FEATURE_DOCS as _SPORTS_ODDS_DOCS
from app.adapters.data.weather_fcst import FEATURE_DOCS as _WEATHER_FCST_DOCS

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9
    ZoneInfo = None  # type: ignore

NEW_YORK = ZoneInfo("America/New_York") if ZoneInfo else None


# Per-second research twins open once this much tick archive exists (3 days = ~288 15-min contracts).
TICK_MIN_DAYS = float(os.getenv("TAU_TICK_MIN_DAYS", "3"))


@dataclass(frozen=True)
class Market:
    key: str
    series: str
    label: str
    # Kalshi candle period the backtest replays, which is also how often a
    # deployment decides - deciding more often live than in the backtest
    # would trade a rule nobody tested.
    candle_minutes: int
    history_days: int
    close_hour_et: Optional[int] = None  # daily ladder: only the 5pm EDT event
    # Coinbase spot product that prices this market's contracts (strike vs spot).
    # None = no underlying price series (e.g. sports): contracts settle on an event
    # outcome, so there is no strike/spot and the backtest trades on price/order-book
    # features alone (no moneyness/vol/z_score).
    underlying: Optional[str] = "BTC-USD"
    # True only for markets with a live feed + execution path, i.e. tradeable now.
    # Research can BACKTEST any market; the deploy engine ticks only deployable ones,
    # so adding a research-only crypto here never starts paper/live trading on it.
    deployable: bool = False
    # The instrument this market is. "binary" = a Kalshi digital-option contract (strike,
    # expiry, $0/$1 settlement - the whole spec.py/backtest.py binary path). "spot" = a
    # continuous price series (e.g. a TAO subnet alpha token) traded long/flat via
    # backtest.simulate_spot; "perpetual" uses a separate funding-aware research replay.
    # Neither continuous instrument has binary strike/expiry/settlement, so the binary feature and
    # fair-value math never runs on it. simulate() routes on this field exactly once.
    kind: str = "binary"
    # Human-facing group for the research picker (Sports / Weather / Economics / …). The
    # curated crypto markets carry "Crypto"; catalog-generated markets inherit Kalshi's own
    # series category. Purely a display/grouping field - no engine logic reads it.
    category: str = ""
    # "candles" (default): Kalshi candlesticks from the DB. "ticks": the per-second feature table
    # built from the tick archive (app/adapters/data/tick_dataset.py), decided every decision_secs seconds.
    source: str = "candles"
    decision_secs: int = 0           # ticks only: decision cadence in seconds (0 = candle_minutes)
    data_from_ts: int = 0            # ticks only: no contract opening before this has tick data

    @property
    def decision_seconds(self) -> int:
        return self.decision_secs or self.candle_minutes * 60

    def tick_history_short(self, now_ts: Optional[float] = None) -> Optional[str]:
        """Why a per-second (source="ticks") market is not worth a research run yet, or None. A run
        on a few hours of archive splits a handful of contracts into research/validation/holdout,
        so it can only produce noise; the twin opens once TICK_MIN_DAYS of seconds exist."""
        if self.source != "ticks":
            return None
        now_ts = datetime.now(timezone.utc).timestamp() if now_ts is None else now_ts
        days = (now_ts - self.data_from_ts) / 86400.0
        if days >= TICK_MIN_DAYS:
            return None
        return ("%s has %.1f of the %g days of per-second history research needs (archive started %s)"
                % (self.label, max(days, 0.0), TICK_MIN_DAYS,
                   datetime.fromtimestamp(self.data_from_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%MZ")))

    def is_target_event(self, close_time: datetime) -> bool:
        if self.close_hour_et is None:
            return True
        ct = close_time if close_time.tzinfo else close_time.replace(tzinfo=timezone.utc)
        return ct.astimezone(NEW_YORK).hour == self.close_hour_et


# The 19 CURATED markets - hand-tuned config (strike/spot/close-hour) that can't be derived
# from the catalog. These are authoritative and never generated; catalog markets merge on top
# of them (see MARKETS below) and can never shadow one (their series are excluded from generation).
# 15-minute crypto ladders: ~96 settled contracts a day each, so history length is what sets the
# research gate's sample (validation is 25% of it). 90 days ~ 22 validation days, ~2.7x the old 30.
# market_history backfills the older end when this reaches past what was collected.
CRYPTO_15M_HISTORY_DAYS = 90
# Weather settles on a seasonal physical quantity, so a model needs a full year; Kalshi's /historical
# endpoints serve these series back to 2021, and market_history pages them past the live cutoff.
WEATHER_HISTORY_DAYS = int(os.getenv("WEATHER_HISTORY_DAYS", "365"))

# A label is what customers read, so a crypto one says what the contract pays on and when it closes
# ("Bitcoin above $X at 5pm ET", "Solana up or down in 15 minutes"); the app fills a contract's own strike
# in for "$X" from its ticker.
CURATED: Dict[str, Market] = {
    # Logical research series; the native Bitcoin ticker is verified/discovered by the
    # dedicated public-data adapter. Never send BTC_PERP to the event-contract API.
    "btc_perp": Market("btc_perp", "BTC_PERP", "Bitcoin perpetual future, no expiry (research only)",
                       candle_minutes=1, history_days=90, underlying="BTC-USD",
                       deployable=False, kind="perpetual", category="Crypto perpetuals"),
    # Deployable: live feed + execution path exist, so the engine trades these.
    "btc15m": Market("btc15m", "KXBTC15M", "Bitcoin up or down in 15 minutes", candle_minutes=1, history_days=CRYPTO_15M_HISTORY_DAYS,
                     underlying="BTC-USD", deployable=True, category="Crypto"),
    # Research-only: the same KXBTC15M contracts replayed from the per-second tick archive
    # (book, taker flow, Coinbase spot each second), deciding every 5s instead of every minute.
    # Archive starts 2026-10-24 20:00Z; history is short until it accumulates.
    "btc15m_tick": Market("btc15m_tick", "KXBTC15M", "Bitcoin up or down in 15 minutes, per-second data",
                          candle_minutes=1, history_days=7, underlying="BTC-USD", deployable=False, category="Crypto",
                          source="ticks", decision_secs=5, data_from_ts=1792872000),
    "btc_daily": Market("btc_daily", "KXBTCD", "Bitcoin above $X at 5pm ET", candle_minutes=60,
                        history_days=60, close_hour_et=17, underlying="BTC-USD", deployable=True, category="Crypto"),
    # Deployable crypto: same strike-ladder + spot-price model as BTC. The live engine prices
    # each from its own Coinbase product (engine.fetch_spot_series) and places orders on its
    # Kalshi series exactly like BTC - a strategy still only trades once a user deploys it.
    "eth15m": Market("eth15m", "KXETH15M", "Ethereum up or down in 15 minutes", candle_minutes=1, history_days=CRYPTO_15M_HISTORY_DAYS,
                     underlying="ETH-USD", deployable=True, category="Crypto"),
    "eth_daily": Market("eth_daily", "KXETHD", "Ethereum above $X at 5pm ET", candle_minutes=60,
                        history_days=60, close_hour_et=17, underlying="ETH-USD", deployable=True, category="Crypto"),
    "sol_daily": Market("sol_daily", "KXSOLD", "Solana above $X at 5pm ET", candle_minutes=60,
                        history_days=60, close_hour_et=17, underlying="SOL-USD", deployable=True, category="Crypto"),
    "xrp_daily": Market("xrp_daily", "KXXRPD", "XRP above $X at 5pm ET", candle_minutes=60,
                        history_days=60, close_hour_et=17, underlying="XRP-USD", deployable=True, category="Crypto"),
    # Deployable SPORTS market. Kalshi's per-game NBA moneyline (series KXNBAGAME) is a binary
    # YES/NO that settles on the game result - structurally like the crypto binaries, but with NO
    # strike and NO underlying price feed (underlying=None). It trades on the contract's own
    # price/order-book features (the strike-vs-spot GBM model does not apply); the live engine
    # prices it from the Kalshi book alone (no Coinbase spot) and places orders the same way.
    # A strategy only reaches live after passing research AND proving on paper on this same feed.
    "nba_game": Market("nba_game", "KXNBAGAME", "NBA game winner (moneyline)", candle_minutes=1,
                       history_days=30, underlying=None, deployable=True, category="Sports"),
    # More deployable CRYPTO, 15-minute "up/down in the next 15 min" (series KX<COIN>15M). Structurally
    # identical to btc15m/eth15m: one ATM-ish strike per window, priced strike-vs-spot off the coin's own
    # Coinbase product (engine.fetch_spot_series). Chosen because each has a live Coinbase USD spot feed
    # AND a currently-active Kalshi 15M ladder (~96 settled markets/day, floor_strike populated, balanced
    # YES/NO) — so the collector fills hist_markets + candlesticks and the backtest/live paths just work.
    # (KXADA15M / KXBCH15M were EXCLUDED: their 15M ladders are dormant — zero settled markets to collect.)
    "sol15m": Market("sol15m", "KXSOL15M", "Solana up or down in 15 minutes", candle_minutes=1, history_days=CRYPTO_15M_HISTORY_DAYS,
                     underlying="SOL-USD", deployable=True, category="Crypto"),
    "xrp15m": Market("xrp15m", "KXXRP15M", "XRP up or down in 15 minutes", candle_minutes=1, history_days=CRYPTO_15M_HISTORY_DAYS,
                     underlying="XRP-USD", deployable=True, category="Crypto"),
    "doge15m": Market("doge15m", "KXDOGE15M", "Dogecoin up or down in 15 minutes", candle_minutes=1, history_days=CRYPTO_15M_HISTORY_DAYS,
                      underlying="DOGE-USD", deployable=True, category="Crypto"),
    "near15m": Market("near15m", "KXNEAR15M", "NEAR up or down in 15 minutes", candle_minutes=1, history_days=CRYPTO_15M_HISTORY_DAYS,
                      underlying="NEAR-USD", deployable=True, category="Crypto"),
    "zec15m": Market("zec15m", "KXZEC15M", "Zcash up or down in 15 minutes", candle_minutes=1, history_days=CRYPTO_15M_HISTORY_DAYS,
                     underlying="ZEC-USD", deployable=True, category="Crypto"),
    "hype15m": Market("hype15m", "KXHYPE15M", "Hyperliquid (HYPE) up or down in 15 minutes", candle_minutes=1,
                      history_days=CRYPTO_15M_HISTORY_DAYS, underlying="HYPE-USD", deployable=True, category="Crypto"),
    # Deployable SPORTS (outcome-settled, underlying=None): per-game moneyline series, structurally the
    # same binary YES/NO as KXNBAGAME — no strike, no spot, so the live tick and backtest price them on
    # the contract's own price/order-book features alone and settle on the game result (engine.fetch_result).
    # Each is a currently-active league with clean yes/no settlement and real per-game liquidity.
    # (KXNCAABGAME excluded: season not started — 0 settled; KXWNBAGAME excluded: off-season + "scalar"
    # result type the yes/no settlement path can't resolve.)
    "nfl_game": Market("nfl_game", "KXNFLGAME", "NFL game winner (moneyline)", candle_minutes=1,
                       history_days=30, underlying=None, deployable=True, category="Sports"),
    "nhl_game": Market("nhl_game", "KXNHLGAME", "NHL game winner (moneyline)", candle_minutes=1,
                       history_days=30, underlying=None, deployable=True, category="Sports"),
    "ncaaf_game": Market("ncaaf_game", "KXNCAAFGAME", "College football game winner", candle_minutes=1,
                         history_days=30, underlying=None, deployable=True, category="Sports"),
    "mlb_game": Market("mlb_game", "KXMLBGAME", "MLB game winner (moneyline)", candle_minutes=1,
                       history_days=30, underlying=None, deployable=True, category="Sports"),
    "epl_game": Market("epl_game", "KXEPLGAME", "English Premier League game result", candle_minutes=1,
                       history_days=30, underlying=None, deployable=True, category="Sports"),
    # Deployable WEATHER (outcome-settled, underlying=None): daily high-temperature ladder for one city
    # (series KXHIGHNY). A binary YES/NO ("83F or above") settling on the day's observed high — no tradable
    # spot series, so it trades on the book-feature model exactly like sports. Daily cadence gives a usable
    # backtest surface (unlike monthly econ releases, which are too sparse and were excluded). candle_minutes
    # =60: a weather market lives ~1 day, so hourly decisions over the day; no close-hour filter (one event/day).
    "high_ny": Market("high_ny", "KXHIGHNY", "NYC daily high temperature", candle_minutes=60,
                      history_days=WEATHER_HISTORY_DAYS, underlying=None, deployable=True, category="Weather"),
    # Research-only SPOT markets (kind="spot", deployable=False): Bittensor subnet alpha tokens.
    # These are a continuous price series (alpha priced in TAO via the subnet's AMM pool ratio),
    # NOT a Kalshi binary - no strike, no expiry, no settlement. `underlying` is the token's own
    # row-symbol in spot_candles_1m (written by the taostats collector, NOT Coinbase/Kalshi); the
    # backtester routes them to simulate_spot. candle_minutes defaults to 60 (taostats OHLC is
    # hourly/daily, not 1-minute); drop it to 1 per market if a plan ever exposes minute data.
    # Execution is BLOCKED (on-chain AMM only, no order API, no native short) - research only.
    "tao_sn64": Market("tao_sn64", "TAO_SN64", "Bittensor SN64 (Chutes) alpha", candle_minutes=60,
                       history_days=180, underlying="TAO-SN64", deployable=False, kind="spot", category="Bittensor"),
    "tao_sn19": Market("tao_sn19", "TAO_SN19", "Bittensor SN19 (Nineteen) alpha", candle_minutes=60,
                       history_days=180, underlying="TAO-SN19", deployable=False, kind="spot", category="Bittensor"),
    "tao_sn8": Market("tao_sn8", "TAO_SN8", "Bittensor SN8 (PTN / Taoshi) alpha", candle_minutes=60,
                      history_days=180, underlying="TAO-SN8", deployable=False, kind="spot", category="Bittensor"),
    "tao_sn4": Market("tao_sn4", "TAO_SN4", "Bittensor SN4 (Targon) alpha", candle_minutes=60,
                      history_days=180, underlying="TAO-SN4", deployable=False, kind="spot", category="Bittensor"),
    "tao_sn56": Market("tao_sn56", "TAO_SN56", "Bittensor SN56 (Gradients) alpha", candle_minutes=60,
                       history_days=180, underlying="TAO-SN56", deployable=False, kind="spot", category="Bittensor"),
}

# The USD/TAO rate series (taostats Price group) every subnet alpha is denominated against, so
# alpha-in-USD = alpha-in-TAO * TAO-USD can be derived per frame without storing a third series.
TAO_USD_SYMBOL = "TAO-USD"

# A BTC price older than this cannot price a contract: no snapshot, no trade.
MAX_BTC_GAP_SECONDS = 180


def cadence_key(market_key: str) -> Tuple[int, Optional[int]]:
    """A market's decision-cadence identity: (candle_minutes, close_hour_et). Two markets can be
    paired cross-sectionally (relative value across DIFFERENT markets) only if these match - same
    decision frequency AND same close schedule, so one synchronized decision frame aligns both.
    This is what forbids pairing a 1-minute market with a daily one."""
    m = MARKETS[market_key]
    return (m.candle_minutes, m.close_hour_et)


def compatible_cadence(market_keys: Sequence[str]) -> bool:
    """True iff every market shares one decision cadence (see cadence_key) - the precondition for
    a cross-market pair to be backtested on one merged frame and ticked on one live frame."""
    return len({cadence_key(k) for k in market_keys}) <= 1


# -- catalog-driven universe (outcome-settled markets) -------------------------
# The 19 CURATED markets need hand-tuned, non-derivable config (strike/spot/close-hour), so they
# are never generated. But OUTCOME-SETTLED binaries (underlying=None, book-only, settle YES/NO on
# an event - exactly the nba_game model) have UNIFORM, derivable config, so we generate deployable
# Market entries straight from Kalshi's own series catalog (`kalshi_series`, enriched with category
# + frequency by catalog_collector). This is read once at import (best-effort: any failure, or an
# empty/un-enriched catalog, falls back to CURATED only - never crashes). New catalog series appear
# on the next process restart; a running engine/server keeps the universe it loaded.

# Recurrence classes with a real backtest surface. one_off / annual (single election, single award)
# and the sparse monthly/quarterly have too few settled events to research, so they are excluded.
# `custom` stays in because sports game-lines (like the curated nba_game) are frequency="custom";
# the open-markets floor below screens out the custom one-shots that have a single live contract.
RECURRING_FREQ = frozenset({"fifteen_min", "hourly", "daily", "weekly", "custom"})

# Categories that settle YES/NO on a published event and fit the book-only model, cut to what we
# trade (Todd, 2026-10-24: sports, weather and crypto only; data_pipeline.common.TRADED_CATEGORIES).
# "Crypto" is traded but not generated here: it is curated and priced off a spot ladder we already
# model. Economics, Commodities, Financials, Politics, Entertainment and the rest are out, and the
# collectors no longer store them.
ALLOWED_CATEGORIES = frozenset({"Sports", "Climate and Weather"})

# Decision cadence + candle granularity, and backtest lookback, by recurrence. Long-open markets
# (daily/weekly) decide hourly (60) so one market isn't 1,440 one-minute candles/day; fast ones
# (sports games, intraday) decide at 1-minute like nba_game. history_days is bounded so the
# collector's one-time backfill over ~100 new series stays feasible under the ~20 req/s limit.
# Kalshi's candlesticks endpoint accepts only 1, 60 or 1440 minutes, so hourly series decide at 1.
_FREQ_CANDLE = {"fifteen_min": 1, "hourly": 1, "daily": 60, "weekly": 60, "custom": 1}
_FREQ_HISTORY = {"fifteen_min": 14, "hourly": 21, "daily": 45, "weekly": 120, "custom": 45}

# Liquidity / activeness floor and the (generous) safety ceilings on how many markets we generate.
# Prioritized by open_markets (liquidity + a recurrence proxy: an active recurring template always
# has several concurrent contracts). The goal is that EVERY collected, genuinely-tradeable series
# (outcome-settled YES/NO binary in an allowed category — the carve-outs in market_from_series and
# the SQL still exclude Crypto/Financials/MVE/scalar/curated/illiquid) becomes deployable, not a
# tightly-curated subset. The collected catalog (series with open markets) is only a few hundred
# rows, so these ceilings are headroom, not a curation knob — but they stay env-tunable because
# every generated market is backfilled per-pass by market_history.refresh (hist_markets + candles),
# so the box can be throttled down (e.g. CATALOG_MAX_MARKETS=150) under a rate-limit/load crunch
# without a code change. open_markets-DESC ordering means a throttle sheds the thinnest books first.
CATALOG_MIN_OPEN = int(os.getenv("CATALOG_MIN_OPEN", "2"))
CATALOG_MAX_MARKETS = int(os.getenv("CATALOG_MAX_MARKETS", "1000"))
# Per-category ceiling: still a tunable safety valve against one category (Sports has ~3,000
# candidate series) swamping the universe if the collected catalog ever balloons, but set high
# enough that it never starves the full collected set the owner wants tradeable.
CATALOG_MAX_PER_CATEGORY = int(os.getenv("CATALOG_MAX_PER_CATEGORY", "1000"))
# Escape hatch: set to "1" to run on the curated 19 only (e.g. to reproduce a bug offline).
CATALOG_DISABLED = os.getenv("TAU_DISABLE_CATALOG_MARKETS") == "1"

# Curated series are authoritative and never regenerated (the SQL excludes them too).
_CURATED_SERIES = frozenset(m.series for m in CURATED.values())


def _market_key(series_ticker: str) -> str:
    """A stable, spec-safe market key from a series ticker (lower snake, no punctuation)."""
    return "".join(c if c.isalnum() else "_" for c in series_ticker.lower()).strip("_")


def market_from_series(row: Dict) -> Optional[Market]:
    """Build one deployable outcome-settled Market from a `kalshi_series` row, or None if the row
    doesn't qualify. Pure (no DB/network) so it is unit-testable and the SQL filter and this guard
    agree. `row` needs: series_ticker, title, category, frequency, open_markets."""
    series = (row.get("series_ticker") or "").strip()
    freq = (row.get("frequency") or "").strip()
    category = (row.get("category") or "").strip()
    if not series or "MVE" in series.upper():   # multi-leg parlay series don't fit one-contract book model
        return None
    # SCALAR guard. The engine's fetch_result only resolves YES/NO, so a scalar (numeric-settled)
    # series can't settle and must never be generated. In today's Kalshi data every market is
    # market_type="binary" with a yes/no result (verified: 22k open + 10k settled sampled, 100%
    # binary/yes-no), so the catalog supplies no market_type and this never fires - but if Kalshi
    # adds scalar series and the collector starts recording it, a non-binary row is rejected here.
    mtype = (row.get("market_type") or "binary").strip().lower()
    if mtype and mtype != "binary":
        return None
    if freq not in RECURRING_FREQ or category not in ALLOWED_CATEGORIES:
        return None
    try:
        if int(row.get("open_markets") or 0) < CATALOG_MIN_OPEN:
            return None
    except (TypeError, ValueError):
        return None
    key = _market_key(series)
    if not key or key in CURATED or series in _CURATED_SERIES:
        return None
    label = (row.get("title") or series).strip()[:120] or series
    return Market(
        key=key, series=series, label=label,
        candle_minutes=_FREQ_CANDLE.get(freq, 60),
        history_days=WEATHER_HISTORY_DAYS if category == "Climate and Weather" else _FREQ_HISTORY.get(freq, 45),
        underlying=None,        # outcome-settled: no spot, book-only (the nba_game model)
        deployable=True,        # ELIGIBLE to trade; every per-deployment gate still runs
        kind="binary",
        category=category,
    )


def load_catalog_markets() -> Dict[str, Market]:
    """Catalog-generated outcome-settled markets from the enriched `kalshi_series` table, keyed by
    market key. Best-effort: no DB env, an empty/un-enriched catalog, or any error → {} (caller
    falls back to CURATED only). Never raises, never touches the network."""
    if CATALOG_DISABLED:
        return {}
    curated_series = {m.series for m in CURATED.values()}
    try:
        from app.trading import catalog_repository
        from data_pipeline.common import get_db_conn
    except Exception:
        return {}
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor() as cur:
            # Fetch more than the cap (still bounded: kalshi_series is only a few hundred rows) so
            # the per-category ceiling below has room to pick a diverse set, not just the top N.
            rows = catalog_repository.deployable_series(
                cur, curated_series, CATALOG_MIN_OPEN, max(CATALOG_MAX_MARKETS * 5, 500),
                sorted(ALLOWED_CATEGORIES), sorted(RECURRING_FREQ),
            )
    except Exception:
        return {}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    # Rows arrive most-liquid first. Keep liquidity priority but cap per category, and stop at the
    # global cap - a diverse, bounded universe (see CATALOG_MAX_PER_CATEGORY).
    out: Dict[str, Market] = {}
    per_cat: Dict[str, int] = {}
    for row in rows:
        if len(out) >= CATALOG_MAX_MARKETS:
            break
        m = market_from_series(row)
        if m is None or m.key in out:
            continue
        if per_cat.get(m.category, 0) >= CATALOG_MAX_PER_CATEGORY:
            continue
        out[m.key] = m
        per_cat[m.category] = per_cat.get(m.category, 0) + 1
    return out


# The live universe every caller iterates: catalog-generated markets with the 19 CURATED entries
# layered ON TOP (curated is authoritative and can never be shadowed). A plain dict of Market, so
# nothing downstream changes shape. Empty/missing catalog → just the curated 19.
MARKETS: Dict[str, Market] = dict(load_catalog_markets())
MARKETS.update(CURATED)

FEATURES: Dict[str, str] = {
    "spot": "BTC price (USD)",
    "ret_1m": "BTC log return over the last 1 minute",
    "ret_5m": "BTC log return over the last 5 minutes",
    "ret_15m": "BTC log return over the last 15 minutes",
    "ret_60m": "BTC log return over the last 60 minutes",
    "vol_15m": "stdev of 1-minute BTC log returns over the last 15 minutes",
    "vol_60m": "stdev of 1-minute BTC log returns over the last 60 minutes",
    "tte_min": "minutes until the contract settles",
    "moneyness": "ln(spot / strike); positive means BTC is above the strike",
    "z_score": "moneyness / (vol_60m * sqrt(tte_min)); distance to strike in standard deviations",
    "yes_bid": "best YES bid (dollars)",
    "yes_ask": "best YES ask (dollars)",
    "spread": "yes_ask - yes_bid",
    "mid": "(yes_bid + yes_ask) / 2",
    "hour_et": "hour of day in New York (0-23)",
}

# Cross-asset features: a crypto market's frames also carry the leading coin's returns, from the
# same one-minute closes and the same as-of rule (the last candle closed by the decision ts). BTC
# is the cross for every alt; ETH is the cross for BTC. Crypto research kept dropping "BTC leads
# ETH/SOL/XRP" ideas as feature_unavailable because a market only saw its own underlying.
CROSS_FEATURES: Dict[str, str] = {
    **{"btc_ret_%dm" % n: "non-BTC crypto markets only: BTC log return over the last %d minute%s"
       % (n, "" if n == 1 else "s") for n in (1, 5, 15, 60)},
    "btc_vol_60m": "non-BTC crypto markets only: stdev of 1-minute BTC log returns over the last 60 minutes",
    **{"eth_ret_%dm" % n: "BTC markets only: ETH log return over the last %d minutes" % n for n in (5, 15, 60)},
}
FEATURES.update(CROSS_FEATURES)

# Order-book / microstructure features the pipeline already collects into
# model_features_1m, keyed {feature name: (db column, description)}. They are joined
# onto each contract snapshot by (ticker, minute) in the backtester; every one is
# NULLABLE, so a frame without a feature-builder row simply lacks them and a filter
# that references one never matches (spec._passes) - it never crashes a backtest.
MICRO_FEATURES: Dict[str, Tuple[str, str]] = {
    "ob_imbalance": ("orderbook_imbalance",
                     "order-book imbalance (bid_size - ask_size)/(bid_size + ask_size), -1..1"),
    "yes_bid_size": ("yes_bid_size_fp", "resting contracts on the best YES bid"),
    "yes_ask_size": ("yes_ask_size_fp", "resting contracts on the best YES ask"),
    "trades_60s": ("trades_last_60s_count", "number of trades in the last 60 seconds"),
    "trade_vol_60s": ("trades_last_60s_volume_fp", "contracts traded in the last 60 seconds"),
    "trade_vwap_60s": ("trades_last_60s_vwap_yes", "VWAP (YES, dollars) of trades in the last 60 seconds"),
    "quote_changes_60s": ("quote_change_events_60s", "best-quote change events in the last 60 seconds"),
    "ob_mid_ret_1m": ("mid_ret_1m", "log return of the YES mid over the last 1 minute"),
    "ob_mid_ret_3m": ("mid_ret_3m", "log return of the YES mid over the last 3 minutes"),
    # Signed taker flow from market_trades (collected from 2026-10-24 09:21Z): who crossed the spread.
    "taker_yes_vol_60s": ("taker_yes_vol_60s", "contracts bought by YES takers in the last 60 seconds"),
    "taker_no_vol_60s": ("taker_no_vol_60s", "contracts bought by NO takers (YES bid hit) in the last 60 seconds"),
    "flow_imb_60s": ("flow_imbalance_60s",
                     "signed taker flow (yes - no)/(yes + no) over the last 60 seconds, -1..1; absent with no trades"),
    "flow_imb_300s": ("flow_imbalance_300s",
                      "signed taker flow (yes - no)/(yes + no) over the last 5 minutes, -1..1; absent with no trades"),
}
# The micro features live in the same FEATURES namespace specs filter on.
FEATURES.update({name: desc for name, (_col, desc) in MICRO_FEATURES.items()})

# Daily-high temperature series -> the ASOS station Kalshi settles them on. Their datasets carry the
# station's observations as built-in features (app/adapters/data/freedata.station_observations, as-of joined).
# Station = the NWS CLI code each series' market rules name ("Chicago (CLIMDW)"), probed 2026-10-24.
WEATHER_STATIONS: Dict[str, str] = {
    "KXHIGHAUS": "AUS", "KXHIGHCHI": "MDW", "KXHIGHDEN": "DEN", "KXHIGHHOU": "HOU", "KXHIGHLAX": "LAX",
    "KXHIGHMIA": "MIA", "KXHIGHNY": "NYC", "KXHIGHOU": "HOU", "KXHIGHPHIL": "PHL", "KXHIGHTATL": "ATL",
    "KXHIGHTBOS": "BOS", "KXHIGHTDAL": "DFW", "KXHIGHTDC": "DCA", "KXHIGHTEMPDEN": "DEN",
    "KXHIGHTEWR": "EWR", "KXHIGHTHOU": "HOU", "KXHIGHTLV": "LAS", "KXHIGHTMIN": "MSP",
    "KXHIGHTNOLA": "MSY", "KXHIGHTOKC": "OKC", "KXHIGHTPHX": "PHX", "KXHIGHTSAN": "SAN",
    "KXHIGHTSATX": "SAT", "KXHIGHTSDF": "SDF", "KXHIGHTSEA": "SEA", "KXHIGHTSFO": "SFO",
    "KXHIGHTTTN": "TTN", "KXLOWTATL": "ATL", "KXLOWTAUS": "AUS", "KXLOWTBOS": "BOS", "KXLOWTCHI": "MDW",
    "KXLOWTDAL": "DFW", "KXLOWTDC": "DCA", "KXLOWTDEN": "DEN", "KXLOWTEWR": "EWR", "KXLOWTHOU": "HOU",
    "KXLOWTLAX": "LAX", "KXLOWTLV": "LAS", "KXLOWTMIA": "MIA", "KXLOWTMIN": "MSP", "KXLOWTNOLA": "MSY",
    "KXLOWTNYC": "NYC", "KXLOWTOKC": "OKC", "KXLOWTPHIL": "PHL", "KXLOWTPHX": "PHX", "KXLOWTSAN": "SAN",
    "KXLOWTSATX": "SAT", "KXLOWTSDF": "SDF", "KXLOWTSEA": "SEA", "KXLOWTSFO": "SFO", "KXLOWTTTN": "TTN",
}
WEATHER_OBS_FEATURES = ("obs_high_f", "obs_low_f", "obs_temp_f")


def weather_target_day(ticker: str) -> Optional[date]:
    """The local day a daily weather contract settles on, from its event segment:
    KXHIGHNY-26OCT24-T66 -> 2026-10-24. None if the ticker doesn't carry one."""
    parts = ticker.split("-")
    if len(parts) < 2:
        return None
    try:
        return datetime.strptime(parts[1].upper(), "%y%b%d").date()
    except ValueError:
        return None


def climate_day(station: str, ts: int) -> Optional[date]:
    """The NWS climate day (local STANDARD time, never DST-shifted) a station is in at ts."""
    from app.adapters.data.freedata import ASOS_LST_OFFSET_H
    off = ASOS_LST_OFFSET_H.get(station)
    if off is None:
        return None
    return datetime.fromtimestamp(ts + off * 3600, tz=timezone.utc).date()


def weather_obs_applies(series: str, ticker: str, ts: int) -> bool:
    """Today's station readings describe a contract only on the day it settles on: a frame also
    quotes tomorrow's contracts, and today's observed high says nothing about tomorrow's."""
    station = WEATHER_STATIONS.get(series)
    target = weather_target_day(ticker)
    return bool(station) and target is not None and climate_day(station, ts) == target


FEATURES.update({
    "obs_high_f": "weather markets only: highest temperature (F) observed so far today at the settlement "
                  "station (NWS climate day, local standard time); the day's high can only rise from here",
    "obs_low_f": "weather markets only: lowest temperature (F) observed so far today at the settlement "
                 "station (NWS climate day, local standard time); the day's low can only fall from here",
    "obs_temp_f": "weather markets only: latest temperature (F) reading at the settlement station",
})
# Features only the per-second tick datasets carry (app/adapters/data/tick_dataset.py, markets with source="ticks").
TICK_FEATURES: Dict[str, str] = {
    "ret_1s": "per-second data only: BTC log return over the last 1 second",
    "ret_10s": "per-second data only: BTC log return over the last 10 seconds",
    "rv_60s": "per-second data only: stdev of 1-second BTC log returns over the last 60 seconds",
    "rv_300s": "per-second data only: stdev of 1-second BTC log returns over the last 5 minutes",
    "spot_flow_imb_60s": "per-second data only: spot taker buy minus sell over their sum, last 60 seconds, -1..1",
    "microprice": "per-second data only: size-weighted YES mid, (bid*ask_size + ask*bid_size)/(bid_size + ask_size)",
    "bid_depth_5c": "per-second data only: YES contracts bid within 5c of the best bid",
    "ask_depth_5c": "per-second data only: YES contracts offered within 5c of the best ask",
    "book_updates_1s": "per-second data only: order-book changes in the last second",
    "book_age_s": "per-second data only: seconds since this contract's book last changed",
    "taker_yes_vol_10s": "per-second data only: contracts bought by YES takers in the last 10 seconds",
    "taker_no_vol_10s": "per-second data only: contracts bought by NO takers in the last 10 seconds",
    "z_score_5m": "per-second data only: like z_score but with 5-minute per-second volatility "
                  "(ln(spot/strike) / (rv_300s * sqrt(seconds to close)))",
    "flow_imb_10s": "per-second data only: signed taker flow (yes - no)/(yes + no) over the last 10 seconds; "
                    "absent with no trades",
    "p_settle": "per-second data only: nowcast P(YES) from the settlement rule itself. Kalshi BTC settles on the "
                "average of the 60 one-second BRTI values before the close, so inside the last minute part of the "
                "average is already fixed and the uncertainty shrinks like tau^1.5, not sqrt(tau). Uses the 7-venue "
                "BRTI composite (data_pipeline/settle_nowcast.py); compare it to yes_ask / yes_bid",
    "settle_sd": "per-second data only: stdev (dollars) of the nowcast settlement average, incl. ~$4 composite-vs-BRTI error",
    "settle_z": "per-second data only: (nowcast settlement average - strike) / settle_sd",
}
FEATURES.update(TICK_FEATURES)
# Per-contract forecast fair value (app/adapters/data/weather_fcst.snapshot_features, research and live alike).
FEATURES.update(_WEATHER_FCST_DOCS)
# Per-contract sportsbook consensus (app/adapters/data/sports_odds.snapshot_features, research and live alike).
FEATURES.update(_SPORTS_ODDS_DOCS)
# Per-contract Deribit options-implied fair value (app/adapters/data/options_fair.snapshot_features; the per-second
# datasets carry opt_p_yes / opt_iv / opt_edge from features_1s instead).
FEATURES.update(_OPTIONS_DOCS)
# Per-contract Polymarket price for the same event (app/adapters/polymarket/features.py; the
# per-second datasets carry pm_p_yes / pm_spread / pm_age_s from features_1s, pm_edge derived).
FEATURES.update(_POLYMARKET_DOCS)


@dataclass(frozen=True)
class Contract:
    ticker: str
    strike: float
    close_time: datetime  # tz-aware UTC
    # Which market/series this contract belongs to (e.g. "KXBTCD"). Defaulted so single-
    # contract callers (and the live engine) are unaffected; cross-contract pairing uses it
    # to tell a BTC leg from an ETH leg at the same decision frame.
    series: str = ""


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One contract's tradable state at one decision time."""

    contract: Contract
    ts: int  # unix seconds of the decision
    yes_bid: float
    yes_ask: float
    features: Dict[str, float]


class BtcSeries:
    """One-minute BTC closes with O(1) windowed returns and volatility.

    Prefix sums of log returns and their squares make every window a
    subtraction, so replaying 40k decision points is cheap.
    """

    def __init__(self, candles: Sequence[Tuple[int, float]]):
        rows = sorted((int(t), float(c)) for t, c in candles if c and float(c) > 0)
        self.ts: List[int] = [t for t, _ in rows]
        self.close: List[float] = [c for _, c in rows]
        self._s1 = [0.0]
        self._s2 = [0.0]
        for i in range(1, len(self.close)):
            r = math.log(self.close[i] / self.close[i - 1])
            self._s1.append(self._s1[-1] + r)
            self._s2.append(self._s2[-1] + r * r)

    def _index_at(self, ts: int) -> Optional[int]:
        """Index of the last candle that had closed by `ts`, if fresh enough."""
        # A one-minute candle starting at t closes at t+60.
        i = bisect.bisect_right(self.ts, ts - 60) - 1
        if i < 0 or ts - (self.ts[i] + 60) > MAX_BTC_GAP_SECONDS:
            return None
        return i

    def _vol(self, i: int, n: int) -> Optional[float]:
        if i < n:
            return None
        s1 = self._s1[i] - self._s1[i - n]
        s2 = self._s2[i] - self._s2[i - n]
        var = (s2 - s1 * s1 / n) / (n - 1)
        return math.sqrt(max(var, 0.0))

    def features_at(self, ts: int) -> Optional[Dict[str, float]]:
        i = self._index_at(ts)
        if i is None or i < 60:
            return None
        spot = self.close[i]
        out = {"spot": spot}
        for n in (1, 5, 15, 60):
            out["ret_%dm" % n] = math.log(spot / self.close[i - n])
        for n in (15, 60):
            out["vol_%dm" % n] = self._vol(i, n) or 0.0
        return out


def cross_product(market: Market) -> Optional[str]:
    """The Coinbase product whose returns ride along on `market`'s frames (CROSS_FEATURES), or
    None: BTC-USD for an alt-coin binary, ETH-USD for a BTC one. Minute-candle binaries only
    (per-second, spot and perpetual markets build their features elsewhere)."""
    u = market.underlying or ""
    if not u.endswith("-USD") or market.kind != "binary" or market.source == "ticks":
        return None
    return "ETH-USD" if u == "BTC-USD" else "BTC-USD"


def cross_feature_names(market: Optional[Market]) -> frozenset:
    """The CROSS_FEATURES names `market`'s frames can carry (empty when it has no cross product)."""
    prod = cross_product(market) if market is not None else None
    if prod is None:
        return frozenset()
    coin = prod.split("-")[0].lower()
    return frozenset(k for k in CROSS_FEATURES if k.startswith(coin + "_"))


def cross_features(product: Optional[str], series: Optional["BtcSeries"], ts: int) -> Dict[str, float]:
    """The CROSS_FEATURES of `product` as of ts, {} when its series is missing or stale (a filter
    on an absent feature never matches, so a stale cross feed can't trade a different rule)."""
    f = series.features_at(ts) if (product and series is not None) else None
    if f is None:
        return {}
    if product == "BTC-USD":
        out = {"btc_ret_%dm" % n: f["ret_%dm" % n] for n in (1, 5, 15, 60)}
        out["btc_vol_60m"] = f["vol_60m"]
        return out
    coin = product.split("-")[0].lower()
    return {"%s_ret_%dm" % (coin, n): f["ret_%dm" % n] for n in (5, 15, 60)}


# One float object per hour, shared by every snapshot: a research dataset holds ~1M of them.
_HOURS = tuple(float(h) for h in range(24))


def snapshot(
    series_features: Optional[Dict[str, float]],
    contract: Contract,
    ts: int,
    yes_bid: Optional[float],
    yes_ask: Optional[float],
    micro: Optional[Dict[str, float]] = None,
) -> Optional[Snapshot]:
    """Combine BTC features with one contract's quote. None = not tradable.

    `micro` is the contract's collected order-book/microstructure features (keyed by
    the MICRO_FEATURES names); None or missing values are simply skipped so a frame
    without them still trades on the core features."""
    if series_features is None or yes_ask is None or yes_bid is None:
        return None
    if not (0.0 < yes_ask < 1.0) or not (0.0 <= yes_bid < yes_ask):
        return None
    tte_min = (contract.close_time.timestamp() - ts) / 60.0
    if tte_min <= 0:
        return None
    f = dict(series_features)
    if micro:
        for k, v in micro.items():
            if v is not None:
                f[k] = float(v)
    f["tte_min"] = tte_min
    # Strike-vs-spot features only for underlying-priced markets (BTC/ETH/...). A sports
    # market has no spot, so series_features carries no "spot" and these are skipped -
    # the snapshot then trades on price/order-book features alone.
    if "spot" in f:
        vol = f["vol_60m"]
        f["moneyness"] = math.log(f["spot"] / contract.strike)
        f["z_score"] = f["moneyness"] / (vol * math.sqrt(tte_min)) if vol > 0 else 0.0
    f["yes_bid"] = yes_bid
    f["yes_ask"] = yes_ask
    f["spread"] = yes_ask - yes_bid
    f["mid"] = (yes_ask + yes_bid) / 2.0
    f["hour_et"] = _HOURS[datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(NEW_YORK).hour]
    return Snapshot(contract=contract, ts=ts, yes_bid=yes_bid, yes_ask=yes_ask, features=f)
