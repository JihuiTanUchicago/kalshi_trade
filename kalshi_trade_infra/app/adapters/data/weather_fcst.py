"""Forecast-implied fair value for daily-high and daily-low temperature contracts (KXHIGH*, KXLOW*).

The NWS publishes a forecast of every station's daily max and min several times a day: the
National Blend of Models (NBM, IEM model "NBS", which also carries its own spread XND) and GFS MOS
("GFS"). data_pipeline/weather_forecast_collector.py stores each issued forecast in
weather_forecasts with known_at = issue time + publication lag, so research and live read the
same point-in-time rows: a frame at ts only sees forecasts whose known_at <= ts.

contract_features() is THE function both sides call (backtest.build_dataset per snapshot, and
engine.tick_market / _cross_market_frame per live quote), so a rule filtering on fcst_edge trades
live exactly as it was tested. It returns, for one contract at one ts:

    fcst_high_f   latest forecast high (F) for the contract's settlement day (KXHIGH*)
    fcst_low_f    latest forecast low (F) for the contract's settlement day (KXLOW*)
    fcst_sd_f     forecast spread used (NBM's XND, or a lead-time default for GFS MOS)
    fcst_age_h    hours since that forecast became known
    fcst_p_yes    forecast-implied probability the contract settles YES, conditioned on the
                  day's observed high (low) so far once the settlement day is underway
    fcst_edge     fcst_p_yes - mid (positive = YES looks cheap against the forecast)

Contract terms come from the ticker, the same way for research and live: KXHIGHNY-26OCT23-B63.5
is the bracket 63-64F, -T64 with strike 64 is "above 64F" (65 or higher), and -T57 with the 0.0
strike sentinel (no floor_strike, so a cap) is "below 57F" (56 or lower). NWS climate highs are
whole degrees, so a probability integrates the normal over [k - 0.5, k + 0.5] per degree.
"""
from __future__ import annotations

import bisect
import math
import re
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

# Preferred model first: NBM is the NWS's own blend and publishes a calibrated spread.
MODEL_PREF = ("NBS", "GFS")
MIN_SD_F = 1.0
# GFS MOS publishes no spread: typical daily-max errors by lead time (hours from known_at to the
# end of the settlement day), roughly the published MOS MAE scaled to a standard deviation.
GFS_SD_BY_LEAD_H = ((24, 2.5), (48, 3.0), (10 ** 9, 3.8))
# A forecast older than this is ignored rather than trusted (a stalled collector must not freeze
# the feature at a days-old value).
MAX_AGE_H = 36.0
# Trailing calibration (fcst_bias_f): the last BIAS_DAYS settled days, each scored on the forecast
# known at BIAS_REF_LOCAL_H local standard time on the day; at least BIAS_MIN_DAYS of them.
BIAS_DAYS = 30
BIAS_MIN_DAYS = 7
BIAS_REF_LOCAL_H = 10
# Hourly ASOS readings miss the true peak between them: the settled (NWS CLI) high minus the hourly
# running high at 17:00-23:00 local was 0F 40%, +1F 49%, +2F 10%, +3F 1% at NYC (Oct 2025-Oct 2026,
# ~325 days). Lows are assumed to mirror it (settled low below the hourly low); unmeasured yet.
OBS_GAP_PMF = ((0, 0.40), (1, 0.49), (2, 0.10), (3, 0.01))
# Afternoon window over which a high's remaining max moves from the forecast to the latest reading.
PEAK_FROM_LOCAL_H = 13.0
PEAK_DONE_LOCAL_H = 16.0
# The first hour of a climate day can still carry yesterday's running max in obs_high_f (see
# freedata._daily_running_max), so the day's observations only condition the probability after it.
OBS_GRACE_S = 3600

_TICKER = re.compile(r"^[A-Z0-9]+-(\d{2})([A-Z]{3})(\d{2})-([BT])(-?\d+(?:\.\d+)?)$")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}


def parse_contract(ticker: str, strike: float) -> Optional[Tuple[date, Optional[int], Optional[int]]]:
    """(settlement day, lowest YES degree or None, highest YES degree or None), or None if the
    ticker isn't a daily-high contract. None on a side means unbounded."""
    m = _TICKER.match(ticker or "")
    if not m:
        return None
    yy, mon, dd, kind, num = m.groups()
    if mon not in _MONTHS:
        return None
    try:
        day = date(2000 + int(yy), _MONTHS[mon], int(dd))
    except ValueError:
        return None
    x = float(num)
    if kind == "B":  # B63.5 = 63 or 64
        lo = int(math.floor(x - 0.5 + 1e-9))
        return day, lo, lo + 1
    if strike and abs(float(strike) - x) < 1e-6:  # floor_strike = x: strictly above x
        return day, int(math.floor(x)) + 1, None
    return day, None, int(math.ceil(x)) - 1  # cap: strictly below x


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _p_between(mu: float, sd: float, lo: Optional[int], hi: Optional[int]) -> float:
    """P(rounded high in [lo, hi]) for high ~ N(mu, sd); None = unbounded."""
    a = 0.0 if lo is None else _phi((lo - 0.5 - mu) / sd)
    b = 1.0 if hi is None else _phi((hi + 0.5 - mu) / sd)
    return max(0.0, b - a)


def _cdf_int(mu: float, sd: float, x: Optional[int]) -> float:
    """P(rounded value <= x) for value ~ N(mu, sd); None = +inf."""
    return 1.0 if x is None else _phi((x + 0.5 - mu) / sd)


def p_yes(mu: float, sd: float, lo: Optional[int], hi: Optional[int],
          observed: Optional[float] = None, kind: str = "max") -> float:
    """Probability the day's max (kind "max") or min ("min") lands in [lo, hi]. mu/sd describe
    the extreme of the part of the day still to come (the whole day before it starts); once the
    day is underway the final value is max(observed, rest) for a high, min(observed, rest) for a
    low, so it can't fall below (rise above) what was already observed."""
    sd = max(float(sd), MIN_SD_F)
    if observed is None:
        return _p_between(mu, sd, lo, hi)
    m = int(round(observed))
    if kind == "max":  # F(x) = P(max(m, R) <= x) = 0 below m, else P(R <= x)
        def cdf(x):
            return 1.0 if x is None else (0.0 if x < m else _cdf_int(mu, sd, x))
        below = 0.0 if lo is None else cdf(lo - 1)
        return max(0.0, cdf(hi) - below)
    # P(min(m, R) >= x) = 0 above m, else P(R >= x)
    def sf(x):
        return 1.0 if x is None else (0.0 if x > m else 1.0 - _cdf_int(mu, sd, x - 1))
    above = 0.0 if hi is None else sf(hi + 1)
    return max(0.0, sf(lo) - above)


def p_yes_observed(mu: float, sd: float, lo: Optional[int], hi: Optional[int],
                   observed: Optional[float], kind: str = "max") -> float:
    """p_yes allowing for the hourly readings' miss: the settled extreme is the observed one
    shifted by OBS_GAP_PMF (higher for a max, lower for a min)."""
    if observed is None:
        return p_yes(mu, sd, lo, hi, None, kind)
    sign = 1 if kind == "max" else -1
    return sum(w * p_yes(mu, sd, lo, hi, observed + sign * g, kind) for g, w in OBS_GAP_PMF)


def rest_of_day(mu: float, sd: float, local_s: int, latest_temp: Optional[float], kind: str) -> Tuple[float, float]:
    """(mean, sd) of the extreme still to come. A high usually peaks mid-afternoon: from
    PEAK_FROM_LOCAL_H to PEAK_DONE_LOCAL_H local standard time the remaining max slides from the
    forecast to the latest reading (tight), since after the peak the temperature only falls.
    Lows keep the forecast (a night-time low can still undercut the morning's)."""
    if kind != "max" or latest_temp is None:
        return mu, sd
    h = local_s / 3600.0
    w = min(1.0, max(0.0, (h - PEAK_FROM_LOCAL_H) / (PEAK_DONE_LOCAL_H - PEAK_FROM_LOCAL_H)))
    return (1 - w) * mu + w * float(latest_temp), (1 - w) * sd + w * MIN_SD_F


class ForecastBook:
    """One station's issued forecasts of one kind ("max" or "min"), indexed for as-of lookups
    by settlement day.

    rows: (known_at_ts, target_day, model, value_f, sd_f or None), any order.
    actuals: (known_at_ts, day, settled value_f) of past settled days, for the trailing bias."""

    def __init__(self, rows: Iterable[Tuple[int, date, str, float, Optional[float]]], lst_offset_h: int,
                 kind: str = "max", actuals: Iterable[Tuple[int, date, float]] = ()):
        self.lst_offset_h = int(lst_offset_h)
        self.kind = kind
        self._actuals = sorted((int(k), d, float(v)) for k, d, v in actuals if v is not None)
        self._actual_keys = [a[0] for a in self._actuals]
        self._bias_cache: Dict[int, Optional[Tuple[float, float, int]]] = {}
        by_key: Dict[Tuple[date, str], List[Tuple[int, float, Optional[float]]]] = {}
        for known_at, day, model, high, sd in rows:
            if high is None or model not in MODEL_PREF:
                continue
            by_key.setdefault((day, model), []).append(
                (int(known_at), float(high), None if sd is None else float(sd)))
        self._series = {k: sorted(v) for k, v in by_key.items()}
        self._keys = {k: [r[0] for r in v] for k, v in self._series.items()}

    def latest(self, day: date, ts: int) -> Optional[Tuple[str, int, float, Optional[float]]]:
        """(model, known_at, high, sd) of the newest forecast for `day` known by ts, preferring
        MODEL_PREF order among those no older than MAX_AGE_H."""
        for model in MODEL_PREF:
            keys = self._keys.get((day, model))
            if not keys:
                continue
            i = bisect.bisect_right(keys, ts) - 1
            if i < 0:
                continue
            known_at, high, sd = self._series[(day, model)][i]
            if (ts - known_at) / 3600.0 <= MAX_AGE_H:
                return model, known_at, high, sd
        return None

    def climate_day(self, ts: int) -> Tuple[date, int]:
        """(NWS climate day containing ts, seconds since that day began), local standard time."""
        local = ts + self.lst_offset_h * 3600
        return datetime.fromtimestamp(local - local % 86400, tz=timezone.utc).date(), local % 86400

    def features(self, ticker: str, strike: float, ts: int, yes_bid: Optional[float], yes_ask: Optional[float],
                 frame_feats: Optional[Dict[str, float]] = None, close_ts: Optional[int] = None) -> Dict[str, float]:
        return snapshot_features(self, ticker, strike, ts, yes_bid, yes_ask, frame_feats)

    def trailing_error(self, ts: int) -> Optional[Tuple[float, float, int]]:
        """(mean forecast-minus-settled, RMS of it, days) over the BIAS_DAYS settled days known by
        ts, scoring each day's forecast as known at BIAS_REF_LOCAL_H local standard time that day.
        None with fewer than BIAS_MIN_DAYS. Only settlements known by ts enter (point-in-time)."""
        n_known = bisect.bisect_right(self._actual_keys, ts)
        if n_known in self._bias_cache:
            return self._bias_cache[n_known]
        errs: List[float] = []
        for _k, day, actual in reversed(self._actuals[:n_known]):
            if len(errs) >= BIAS_DAYS:
                break
            got = self.latest(day, self.day_start_ts(day) + BIAS_REF_LOCAL_H * 3600)
            if got is not None:
                errs.append(got[2] - actual)
        out = None
        if len(errs) >= BIAS_MIN_DAYS:
            out = (sum(errs) / len(errs), math.sqrt(sum(e * e for e in errs) / len(errs)), len(errs))
        self._bias_cache[n_known] = out
        return out

    def day_start_ts(self, day: date) -> int:
        return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()) - self.lst_offset_h * 3600

    def day_end_ts(self, day: date) -> int:
        start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        return start + 86400 - self.lst_offset_h * 3600


def _gfs_sd(lead_h: float) -> float:
    for limit, sd in GFS_SD_BY_LEAD_H:
        if lead_h <= limit:
            return sd
    return GFS_SD_BY_LEAD_H[-1][1]


def contract_features(book: Optional[ForecastBook], ticker: str, strike: float, ts: int,
                      yes_bid: Optional[float], yes_ask: Optional[float],
                      observed: Optional[float] = None, latest_temp: Optional[float] = None) -> Dict[str, float]:
    """Forecast features for one daily-high/low contract at ts (only the strike features when
    there is no usable forecast, {} when the ticker doesn't parse). `observed` is the frame's running max (min for a "min" book) for the station's
    current climate day, if known (obs_high_f / obs_low_f); latest_temp its latest reading
    (obs_temp_f), which takes over from the forecast once a high has peaked."""
    if book is None:
        return {}
    terms = parse_contract(ticker, strike)
    if terms is None:
        return {}
    day, lo, hi = terms
    today, into_day = book.climate_day(ts)
    if observed is not None and not (today == day and into_day >= OBS_GRACE_S):
        observed = None
    got = book.latest(day, ts)
    if got is None:
        return strike_features(lo, hi, None, observed)
    model, known_at, high, sd = got
    if sd is None:
        sd = _gfs_sd((book.day_end_ts(day) - known_at) / 3600.0)
    sd = max(float(sd), MIN_SD_F)
    mu_r, sd_r = rest_of_day(high, sd, into_day, latest_temp if observed is not None else None, book.kind)
    p = p_yes_observed(mu_r, sd_r, lo, hi, observed, book.kind)
    name = "fcst_high_f" if book.kind == "max" else "fcst_low_f"
    out = {name: high, "fcst_sd_f": sd, "fcst_age_h": (ts - known_at) / 3600.0, "fcst_p_yes": p}
    out.update(strike_features(lo, hi, high, observed))
    trail = book.trailing_error(ts)
    if trail is not None:
        bias, rms, _n = trail
        out["fcst_bias_f"] = bias
        mu_c, sd_c = rest_of_day(high - bias, max(sd, rms), into_day,
                                 latest_temp if observed is not None else None, book.kind)
        out["fcst_p_yes_cal"] = p_yes_observed(mu_c, sd_c, lo, hi, observed, book.kind)
    if yes_bid is not None and yes_ask is not None:
        mid = (float(yes_bid) + float(yes_ask)) / 2.0
        out["fcst_edge"] = p - mid
        if "fcst_p_yes_cal" in out:
            out["fcst_edge_cal"] = out["fcst_p_yes_cal"] - mid
    return out


def yes_margin(x: float, lo: Optional[int], hi: Optional[int]) -> float:
    """Signed distance (F) from x to the edge of the contract's YES range [lo-0.5, hi+0.5]:
    positive = inside (that far from leaving it), negative = outside (that far from entering)."""
    sides = []
    if lo is not None:
        sides.append(x - (lo - 0.5))
    if hi is not None:
        sides.append((hi + 0.5) - x)
    return min(sides) if sides else 0.0


def strike_features(lo: Optional[int], hi: Optional[int], fcst: Optional[float],
                    observed: Optional[float]) -> Dict[str, float]:
    """The contract's own strike, absolute and relative to the forecast / the day's observed
    extreme, so a spec filter can say "forecast 3F inside the YES range" (filters compare a feature
    with a constant; run 2613's proposer had no strike to condition on)."""
    out = {} if fcst is None else {"fcst_yes_margin_f": yes_margin(fcst, lo, hi)}
    if lo is not None:
        out["strike_lo_f"] = float(lo)
    if hi is not None:
        out["strike_hi_f"] = float(hi)
    if observed is not None:
        out["obs_yes_margin_f"] = yes_margin(float(observed), lo, hi)
    return out


FEATURE_DOCS = {
    "fcst_high_f": "weather markets only: latest NWS forecast high (F) for this contract's settlement day "
                   "(NBM blend, else GFS MOS), as issued before the frame",
    "fcst_low_f": "weather markets only: latest NWS forecast low (F) for this contract's settlement day "
                  "(NBM blend, else GFS MOS), as issued before the frame",
    "fcst_sd_f": "weather markets only: forecast spread (F) behind fcst_p_yes (NBM's own, or a GFS lead default)",
    "fcst_age_h": "weather markets only: hours since the forecast behind fcst_high_f/fcst_low_f became public",
    "fcst_p_yes": "weather markets only: forecast-implied probability this contract settles YES, "
                  "conditioned on the observed high (low) so far once the day is underway",
    "fcst_edge": "weather markets only: fcst_p_yes minus the contract's mid (positive = YES cheap vs forecast)",
    "fcst_bias_f": "weather markets only: this station's trailing 30-settled-day mean of morning-of forecast minus "
                   "settled value (F); positive = the forecast has been running warm",
    "fcst_p_yes_cal": "weather markets only: fcst_p_yes after removing fcst_bias_f and widening the spread to the "
                      "trailing forecast error",
    "fcst_edge_cal": "weather markets only: fcst_p_yes_cal minus the contract's mid",
    "strike_lo_f": "weather markets only: lowest temperature (F) that settles this contract YES (absent if unbounded below)",
    "strike_hi_f": "weather markets only: highest temperature (F) that settles this contract YES (absent if unbounded above)",
    "fcst_yes_margin_f": "weather markets only: signed distance (F) from the forecast to the edge of this contract's "
                         "YES range; positive = forecast inside YES by that much, negative = outside",
    "obs_yes_margin_f": "weather markets only, settling day: the same signed distance for the day's observed high "
                        "(low) so far; for a high, a contract whose floor is already beaten has a large positive value",
}


def kind_for_series(series: str) -> str:
    """'min' for the daily-low ladders (KXLOW*), else 'max'."""
    return "min" if (series or "").upper().startswith("KXLOW") else "max"


def book_for_series(series: str, load_rows, load_actuals=None) -> Optional[ForecastBook]:
    """The ForecastBook for a weather series, or None when it isn't one (or its station's local
    standard time is unknown). load_rows(station, kind) returns repository.load_weather_forecasts
    rows: research passes a window-wide loader, the live engine a recent-days one.
    load_actuals(series), if given, returns repository.load_weather_actuals rows for the bias."""
    from app.adapters.data import freedata
    from app.markets import WEATHER_STATIONS
    station = WEATHER_STATIONS.get(series)
    offset = freedata.ASOS_LST_OFFSET_H.get(station) if station else None
    if offset is None:
        return None
    kind = kind_for_series(series)
    return ForecastBook(load_rows(station, kind), offset, kind, load_actuals(series) if load_actuals else ())


def snapshot_features(book: Optional[ForecastBook], ticker: str, strike: float, ts: int,
                      yes_bid: Optional[float], yes_ask: Optional[float],
                      frame_feats: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """contract_features with the day's observed extreme taken from the frame's station features
    (obs_high_f for a max book, obs_low_f for a min book). This is the one call research and live
    make per contract."""
    if book is None:
        return {}
    ff = frame_feats or {}
    obs = ff.get("obs_high_f" if book.kind == "max" else "obs_low_f")
    return contract_features(book, ticker, strike, ts, yes_bid, yes_ask, obs, ff.get("obs_temp_f"))


def with_forecast(micro: Optional[Dict[str, float]], book, contract, ts: int,
                  yes_bid: Optional[float], yes_ask: Optional[float],
                  frame_feats: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
    """A contract's per-snapshot extras for markets.snapshot(): its micro features plus the
    features of an external fair-value book (a weather ForecastBook, a sports_odds.OddsBook or an
    options_fair.OptionsBook, anything with .features). `micro` is returned as is (no copy) when there is no book."""
    if book is None:
        return micro
    fc = book.features(contract.ticker, contract.strike, ts, yes_bid, yes_ask, frame_feats,
                       close_ts=int(contract.close_time.timestamp()))
    return dict(micro, **fc) if micro else fc
