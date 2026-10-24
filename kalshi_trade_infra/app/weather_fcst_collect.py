"""Collect issued NWS station forecasts of the daily max/min into weather_forecasts.

Two free, keyless forecasts from the Iowa Environmental Mesonet's MOS archive, every station in
markets.WEATHER_STATIONS:
  NBS  National Blend of Models text guidance: TXN max/min plus its own spread XND
  GFS  GFS MOS (MAV): N/X max/min, no spread

Each run's max (the 00Z column, the daytime high of the previous local day) and min (the 12Z
column, that morning's low) becomes one row per settlement day. known_at = runtime + LAG_S, a
conservative publication delay, so research never sees a forecast before the NWS released it;
the live engine reads the same rows with the same known_at <= now rule (app/weather_fcst).

Usage (web box, hourly timer: scripts/systemd/kalshi-weather-fcst.timer):
  python -m app.weather_fcst_collect                     # incremental: runs from the last 2 days
  python -m app.weather_fcst_collect --since 2025-10-01  # backfill
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple

IEM_MOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py"
MODELS = ("NBS", "GFS")
# Publication delay after the nominal run time. NBM text bulletins post about an hour after the
# run and MAV about 3.5h after; both are padded so a forecast is never "known" early.
LAG_S = {"NBS": 90 * 60, "GFS": 270 * 60}
VALUE_COL = {"NBS": "txn", "GFS": "n_x"}
SD_COL = {"NBS": "xnd"}
# IEM asks for gentle use and answers 429 to bursts: one request at a time, spaced out.
REQUEST_GAP_S = 3.0
RETRY_WAITS_S = (30, 60, 120)
CHUNK_DAYS = 31
INCREMENTAL_DAYS = 2
_TIMEOUT_S = 60

Row = Tuple[datetime, str, date, float, Optional[float]]  # (runtime, kind, target_day, value_f, sd_f)


def icao(station: str) -> str:
    """NWS climate station (as in WEATHER_STATIONS) -> the ICAO id IEM files MOS under."""
    s = station.strip().upper()
    return "K" + s if len(s) == 3 else s


def _num(v: Optional[str]) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def parse_rows(text: str, model: str) -> List[Row]:
    """IEM mos.py CSV -> one row per (run, kind, settlement day). The max sits in the 00Z column
    (the previous local day's daytime high), the min in the 12Z column (that day's morning low)."""
    col, sd_col = VALUE_COL[model], SD_COL.get(model)
    out: List[Row] = []
    for r in csv.DictReader(io.StringIO(text)):
        v = _num(r.get(col))
        if v is None or not -80.0 < v < 140.0:
            continue
        try:
            runtime = datetime.strptime(r["runtime"][:19], "%Y-%m-%d %H:%M:%S")
            ftime = datetime.strptime(r["ftime"][:19], "%Y-%m-%d %H:%M:%S")
        except (KeyError, TypeError, ValueError):
            continue
        if ftime.hour == 0 and ftime.minute == 0:
            kind, day = "max", (ftime - timedelta(days=1)).date()
        elif ftime.hour == 12 and ftime.minute == 0:
            kind, day = "min", ftime.date()
        else:
            continue
        sd = _num(r.get(sd_col)) if sd_col else None
        out.append((runtime, kind, day, v, sd if sd is None or sd >= 0 else None))
    return out


def fetch(station: str, model: str, sts: datetime, ets: datetime, get=None,
          sleep: Callable[[float], None] = time.sleep) -> str:
    """One IEM request, retried with backoff on 429/5xx. Raises after the last retry."""
    if get is None:
        import requests
        get = requests.get
    params = {"station": icao(station), "model": model, "format": "csv",
              "sts": sts.strftime("%Y-%m-%dT%H:%MZ"), "ets": ets.strftime("%Y-%m-%dT%H:%MZ")}
    for wait in RETRY_WAITS_S + (None,):
        resp = get(IEM_MOS_URL, params=params, timeout=_TIMEOUT_S)
        if resp.status_code == 200:
            return resp.text
        if wait is None or resp.status_code not in (429, 500, 502, 503, 504):
            raise RuntimeError("IEM mos %s %s: HTTP %s" % (station, model, resp.status_code))
        sleep(wait)
    raise AssertionError("unreachable")


def upsert(cur, station: str, model: str, rows: Iterable[Row], now: datetime) -> int:
    """INSERT IGNORE: an issued forecast never changes, and keeping the first collected_at shows
    when it was actually first seen."""
    vals = [(station, model, kind, runtime, day, value, sd, runtime + timedelta(seconds=LAG_S[model]), now)
            for runtime, kind, day, value, sd in rows]
    if not vals:
        return 0
    cur.executemany(
        "INSERT IGNORE INTO weather_forecasts (station, model, kind, runtime_utc, target_day, value_f, sd_f,"
        " known_at_utc, collected_at_utc) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", vals)
    return int(cur.rowcount or 0)


def collect(cur, stations: Iterable[str], since: datetime, until: datetime, models=MODELS, get=None,
            sleep: Callable[[float], None] = time.sleep) -> Dict:
    """Fetch [since, until) for every station x model in CHUNK_DAYS windows. One station's failure
    is recorded and skipped so the rest still land."""
    stats: Dict = {"requests": 0, "parsed": 0, "inserted": 0, "errors": []}
    first = True
    for station in stations:
        for model in models:
            start = since
            while start < until:
                end = min(until, start + timedelta(days=CHUNK_DAYS))
                if not first:
                    sleep(REQUEST_GAP_S)
                first = False
                try:
                    rows = parse_rows(fetch(station, model, start, end, get=get, sleep=sleep), model)
                    stats["requests"] += 1
                    stats["parsed"] += len(rows)
                    stats["inserted"] += upsert(cur, station, model, rows,
                                               datetime.now(timezone.utc).replace(tzinfo=None))
                except Exception as e:  # noqa: BLE001 - keep collecting the other stations
                    stats["errors"].append("%s/%s %s: %r" % (station, model, start.date(), e))
                start = end
    return stats


def stations() -> List[str]:
    from app.markets import WEATHER_STATIONS
    return sorted(set(WEATHER_STATIONS.values()))


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", help="backfill from this UTC date (YYYY-MM-DD); default: last %d days" % INCREMENTAL_DAYS)
    ap.add_argument("--station", action="append", help="only these stations (repeatable)")
    args = ap.parse_args(argv)
    from data_pipeline.common import get_db_conn

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = (datetime.strptime(args.since, "%Y-%m-%d") if args.since
             else (now - timedelta(days=INCREMENTAL_DAYS)).replace(minute=0, second=0, microsecond=0))
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            stats = collect(cur, args.station or stations(), since, now + timedelta(hours=1))
    finally:
        conn.close()
    print(json.dumps(dict(stats, errors=stats["errors"][:20], n_errors=len(stats["errors"]))), flush=True)
    if stats["requests"] == 0 and stats["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
