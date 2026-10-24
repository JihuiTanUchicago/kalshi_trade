"""Bring FREE external data into the research fold (Pillar 3).

A `code` spec may request external datasets under spec["datasets"]:

    "datasets": [
        {"name": "dgs10", "source": "fred", "series": "DGS10", "lag_days": 1},
        ...
    ]

resolve() fetches each series on the HOST (never inside the sandbox) from a FREE, keyless
source. enrich() then as-of-joins every resolved series onto the window's frames, so
fit(window) / signals(window) can read the joined value at each frame as:

    frame["external"][name]     # float, or absent if no value was known at that frame's ts

WHY THIS IS LEAK-FREE (the fold boundary + point-in-time rule):
  * The join (asof_join) gives a frame at time `ts` ONLY the most recent observation whose
    KNOWN-AT time is <= ts. A value published after ts can never reach an earlier frame, so no
    future information bleeds backward. known-at = observation date + the series' publication
    lag (lag_days), recorded in provenance.
  * FITTING is fold-restricted by the caller: freeze_code_model/fit_spec_on_research run only on
    the research Dataset, so a frozen model is fit on research-fold external data alone. signals()
    on validation/holdout joins the SAME series the SAME point-in-time way — exactly what a live
    book would see at those later timestamps — so there is no re-fit and no leak.
  * REPRODUCIBILITY + the prereg hash: the dataset REQUEST lives in spec["datasets"], which is
    part of the canonical-JSON hash (gatekeeper.Prereg.hypothesis_hash), so the pre-registration
    still pins exactly one trial. data_sources_for() surfaces the request into the ledger's
    data_provenance so an auditor sees what external data the hypothesis touched.

ONLY free, keyless sources are supported. A source that needs a key/entitlement that is not
configured, an unknown source, or any fetch/parse error DEGRADES GRACEFULLY: the dataset is
skipped with a recorded reason, the frame key is simply absent, and a strategy that needed it
produces no signal and fails the gate honestly — it never crashes the research run.

ponytail: FRED serves revised (latest-vintage) values, not the ALFRED point-in-time vintage as
of each known-at date; lag_days approximates the publication delay but not later revisions.
Upgrade path: an alfred: source using the keyless alfredgraph.csv?vintage_date= endpoint if a
hypothesis proves sensitive to revisions.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

log = logging.getLogger(__name__)

_FETCH_TIMEOUT_S = 20
# Cache resolved series: the same series is requested across folds (research/validation/holdout)
# and across many specs in one run. Key = (source, series) -> (fetched_at, observations). Entries
# expire after CACHE_TTL_S, since worker processes live for days and a never-refreshed series would
# carry a stale last value onto every newer frame.
CACHE_TTL_S = 3600
# Hourly station readings feed the live engine too: refresh them sooner so a new METAR shows up.
SOURCE_TTL_S = {"asos": 600}
_CACHE: Dict[Tuple[str, str], Tuple[float, Optional[List[Tuple[int, float]]]]] = {}

# Sources that resolve for FREE with no key/entitlement on the host. Each maps source -> fetcher
# returning observations as (observation_unix_ts_utc_midnight, value), ascending, or raising.
SOURCES = ("fred", "asos")


def asof_join(frame_tss: List[int], observations: List[Tuple[int, float]]) -> Dict[int, float]:
    """Point-in-time join: for each frame ts, the value of the most recent observation whose
    known-at time is <= ts. Returns {ts: value}; a ts with no observation known by then is
    ABSENT from the result (never None-filled), so the caller can tell "no data yet" apart from
    a real 0.0.

    This is the leak guard: a value whose known-at time is AFTER a frame's ts is never visible
    at that frame, so no future value can appear at an earlier timestamp.
    `observations` must be (known_ts, value) ascending by known_ts.
    """
    obs = sorted(observations)  # defensive: ascending by known_ts
    out: Dict[int, float] = {}
    i = 0
    cur: Optional[float] = None
    for ts in sorted(set(frame_tss)):
        while i < len(obs) and obs[i][0] <= ts:
            cur = obs[i][1]
            i += 1
        if cur is not None:
            out[ts] = cur
    return out


def _fetch_fred(series: str) -> List[Tuple[int, float]]:
    """Free, keyless FRED CSV: fredgraph.csv?id=<series>. Rows are (observation_date, value);
    missing values are '.'. Returns (unix ts at UTC midnight of the observation date, value)."""
    import requests  # already a dependency; imported lazily so sandbox/import paths stay clean

    # URL-encode the model-chosen series id (host/path are hardcoded; this just stops a stray
    # char in `series` altering the query string — defense-in-depth, the input is LLM-generated).
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s" % quote(series, safe="")
    resp = requests.get(url, timeout=_FETCH_TIMEOUT_S)
    resp.raise_for_status()
    rows = list(csv.reader(io.StringIO(resp.text)))
    if not rows or len(rows[0]) < 2:
        raise ValueError("unexpected FRED CSV shape for %s" % series)
    out: List[Tuple[int, float]] = []
    for r in rows[1:]:
        if len(r) < 2 or r[1] in ("", "."):
            continue
        try:
            d = datetime.strptime(r[0].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            out.append((int(d.timestamp()), float(r[1])))
        except (ValueError, OverflowError):
            continue
    if not out:
        raise ValueError("no usable observations for FRED series %s" % series)
    out.sort()
    return out


# Hourly airport-station observations (ASOS/METAR) from the Iowa Environmental Mesonet archive:
# free, keyless, and the source Kalshi weather traders use. A METAR is public within minutes of its
# valid time; ASOS_LAG_S is baked into the known-at time on top of the spec's own lag_days.
ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
ASOS_LAG_S = 15 * 60
ASOS_HISTORY_DAYS = 400  # weather research history reaches 365 days
ASOS_TIMEOUT_S = 60
# NWS climate days (what Kalshi's daily-high markets settle on) run midnight to midnight LOCAL
# STANDARD time all year, so a station's day boundary is a fixed UTC offset, never DST-shifted.
ASOS_LST_OFFSET_H = {
    "NYC": -5, "LGA": -5, "JFK": -5, "EWR": -5, "PHL": -5, "BOS": -5, "DCA": -5, "IAD": -5,
    "BWI": -5, "MIA": -5, "ATL": -5, "CLT": -5, "DTW": -5, "TTN": -5, "SDF": -5, "OKC": -6, "MDW": -6, "ORD": -6, "AUS": -6,
    "DFW": -6, "DAL": -6, "HOU": -6, "IAH": -6, "SAT": -6, "MSP": -6, "MSY": -6, "STL": -6,
    "DEN": -7, "PHX": -7, "SLC": -7, "LAX": -8, "SFO": -8, "SEA": -8, "LAS": -8, "SAN": -8,
}


def _parse_asos_series(series: str) -> Tuple[str, Optional[str], Optional[int]]:
    """'NYC' -> latest temperature (F); 'NYC:dailymax' / 'NYC:dailymin' -> running max / min of the
    NWS climate day so far (F), LST offset from ASOS_LST_OFFSET_H; 'XYZ:dailymax:-6' gives the offset
    explicitly. Returns (station, "max"|"min"|None, lst_offset_hours or None); raises on a bad series."""
    parts = series.strip().upper().split(":")
    station = parts[0]
    if not (3 <= len(station) <= 4 and station.isalnum()):
        raise ValueError("bad ASOS station %r" % station)
    if len(parts) == 1:
        return station, None, None
    if parts[1] not in ("DAILYMAX", "DAILYMIN") or len(parts) > 3:
        raise ValueError("ASOS series must be STATION or STATION:dailymax|dailymin[:<utc offset h>]")
    agg = parts[1][5:].lower()
    if len(parts) == 3:
        return station, agg, int(parts[2])
    if station not in ASOS_LST_OFFSET_H:
        raise ValueError("no LST offset known for %s; use %s:%s:<offset>" % (station, station, parts[1].lower()))
    return station, agg, ASOS_LST_OFFSET_H[station]


def _asos_rows(text: str) -> List[Tuple[int, float]]:
    """(valid unix ts UTC, tmpf) from IEM's onlycomma CSV (header station,valid,tmpf), ascending."""
    out: List[Tuple[int, float]] = []
    for r in csv.reader(io.StringIO(text)):
        if len(r) < 3 or r[0].startswith("#") or r[1] == "valid":
            continue
        try:
            t = datetime.strptime(r[1].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            out.append((int(t.timestamp()), float(r[2])))
        except (ValueError, OverflowError):
            continue  # 'M' (missing) and malformed rows
    out.sort()
    return out


def _daily_running(rows: List[Tuple[int, float]], lst_offset_h: int, agg: str = "max") -> List[Tuple[int, float]]:
    """Running max (or min) of each climate day so far, emitted at every observation. A frame in a
    new day sees the prior day's value until that day's first observation (at most about an hour)."""
    pick = max if agg == "max" else min
    out: List[Tuple[int, float]] = []
    day, cur = None, None
    for t, v in rows:
        d = (t + lst_offset_h * 3600) // 86400
        if d != day:
            day, cur = d, v
        else:
            cur = pick(cur, v)
        out.append((t, cur))
    return out


_STATION_ROWS: Dict[str, Tuple[float, List[Tuple[int, float]]]] = {}


def _station_rows(station: str, now: Optional[datetime] = None) -> List[Tuple[int, float]]:
    """One IEM download per station per SOURCE_TTL_S, shared by its raw/max/min series."""
    import requests
    from datetime import timedelta

    hit = _STATION_ROWS.get(station)
    if hit is not None and now is None and time.time() - hit[0] <= SOURCE_TTL_S["asos"]:
        return hit[1]
    end = (now or datetime.now(timezone.utc)) + timedelta(days=1)
    start = end - timedelta(days=ASOS_HISTORY_DAYS)
    params = [("station", station), ("data", "tmpf"), ("tz", "Etc/UTC"), ("format", "onlycomma"),
              ("latlon", "no"), ("missing", "M"), ("direct", "no"),
              ("report_type", "3"), ("report_type", "4"),
              ("year1", start.year), ("month1", start.month), ("day1", start.day),
              ("year2", end.year), ("month2", end.month), ("day2", end.day)]
    resp = requests.get(ASOS_URL, params=params, timeout=ASOS_TIMEOUT_S)
    resp.raise_for_status()
    rows = _asos_rows(resp.text)
    if not rows:
        raise ValueError("no usable ASOS observations for %s" % station)
    if now is None:
        _STATION_ROWS[station] = (time.time(), rows)
    return rows


def _fetch_asos(series: str, now: Optional[datetime] = None) -> List[Tuple[int, float]]:
    """Free, keyless IEM ASOS archive. Returns (known-at ts, value): observation time + ASOS_LAG_S."""
    station, agg, offset = _parse_asos_series(series)
    rows = _station_rows(station, now)
    if agg is not None:
        rows = _daily_running(rows, offset, agg)
    return [(t + ASOS_LAG_S, v) for t, v in rows]


_FETCHERS = {"fred": _fetch_fred, "asos": _fetch_asos}


def resolve(req: Dict) -> Tuple[Optional[List[Tuple[int, float]]], Dict]:
    """Resolve ONE dataset request into (observations, provenance). observations is a list of
    (known_at_unix_ts, value) ascending, with the publication lag already applied; None when the
    dataset could not be resolved (the provenance then carries a 'skipped' reason). NEVER raises:
    any failure degrades to (None, provenance) so the research run continues."""
    name = req.get("name")
    source = req.get("source")
    series = req.get("series")
    lag_days = int(req.get("lag_days", 1))
    prov: Dict = {"name": name, "source": source, "series": series, "lag_days": lag_days}
    fetcher = _FETCHERS.get(source)
    if fetcher is None:
        prov["skipped"] = "unknown or unconfigured source %r" % source
        return None, prov
    key = (source, series)
    hit = _CACHE.get(key)
    if hit is None or time.time() - hit[0] > SOURCE_TTL_S.get(source, CACHE_TTL_S):
        try:
            got = fetcher(series)
        except Exception as e:  # network/parse/entitlement - all degrade gracefully
            log.warning("freedata: could not resolve %s:%s (%s)", source, series, e)
            got = None
        _CACHE[key] = hit = (time.time(), got)
    raw = hit[1]
    if raw is None:
        prov["skipped"] = "fetch failed or unavailable (see log)"
        return None, prov
    lag_s = lag_days * 86400
    obs = [(t + lag_s, v) for t, v in raw]  # shift observation date -> known-at time
    prov["observations"] = len(obs)
    prov["known_from"] = _iso(obs[0][0])
    prov["known_to"] = _iso(obs[-1][0])
    return obs, prov


def station_observations(station: str) -> Dict[str, List[Tuple[int, float]]]:
    """Built-in weather features for a daily-high market's settlement station, as (known_at, value)
    series: obs_high_f / obs_low_f (running max / min of the NWS climate day so far) and obs_temp_f
    (latest reading).
    A series that can't be fetched is left out, so the features are simply absent (fail-open)."""
    out: Dict[str, List[Tuple[int, float]]] = {}
    for name, series in (("obs_high_f", station + ":dailymax"), ("obs_low_f", station + ":dailymin"),
                         ("obs_temp_f", station)):
        obs, _prov = resolve({"name": name, "source": "asos", "series": series, "lag_days": 0})
        if obs:
            out[name] = obs
    return out


def enrich(spec: Dict, window: Dict) -> List[Dict]:
    """Join every dataset spec["datasets"] requests onto `window` IN PLACE under each frame's
    "external" dict, point-in-time (asof_join). Returns the provenance list (one record per
    request, with resolved/known-at ranges or a skip reason). A no-datasets spec is a no-op and
    returns []. Values are only written where a value was actually known by the frame's ts."""
    reqs = spec.get("datasets") or []
    frames = window.get("frames") or []
    if not reqs or not frames:
        return []
    frame_tss = [int(f["ts"]) for f in frames]
    provenance: List[Dict] = []
    for req in reqs:
        obs, prov = resolve(req)
        provenance.append(prov)
        if obs is None:
            continue
        joined = asof_join(frame_tss, obs)
        name = req["name"]
        for f in frames:
            v = joined.get(int(f["ts"]))
            if v is not None:
                f.setdefault("external", {})[name] = v
    return provenance


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def demo() -> None:
    """Self-check: the as-of join never surfaces a future value at an earlier ts."""
    # obs known at t=100 (v=1.0) and t=300 (v=2.0). lag already baked into these known-at ts.
    obs = [(100, 1.0), (300, 2.0)]
    j = asof_join([50, 100, 150, 300, 500], obs)
    assert 50 not in j, "no value should exist before the first observation is known"
    assert j[100] == 1.0 and j[150] == 1.0, "frame sees the most recent known value"
    assert j[300] == 2.0 and j[500] == 2.0, "frame at/after a release sees the newer value"
    # THE leak test: a value released at t=300 must NOT be visible at t=299.
    assert asof_join([299], obs).get(299) == 1.0, "future value leaked into an earlier frame!"
    # Unsorted observations and frames still join correctly.
    assert asof_join([500, 50, 150], [(300, 2.0), (100, 1.0)]) == {150: 1.0, 500: 2.0}
    # resolve() of an unknown source degrades gracefully, never raises.
    o, p = resolve({"name": "x", "source": "nope", "series": "Z"})
    assert o is None and "skipped" in p, "unknown source must skip, not crash"
    print("freedata demo OK")


if __name__ == "__main__":
    demo()
