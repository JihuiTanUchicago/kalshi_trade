"""Deribit BTC options: the implied-vol surface that prices Kalshi's BTC contracts (options_surface).

Live: every POLL_S seconds the recorder fetches every BTC option's mark (one public REST call,
public/get_book_summary_by_currency) and
  * appends it verbatim to the tick directory (source "deribit", hourly NDJSON like the other
    recorders); tick_archiver parses each hour into deribit_options (one row per option per poll)
    and deribit_surface (the fitted surface, one row per expiry per poll) and keeps the raw gzip;
  * writes the fitted surface into its heartbeat row (collector_state tick_recorder_deribit), which
    is where the live engine reads it: one fit, one source, for research and live alike.

History: research needs the surface for the months of Kalshi contracts it backtests, older than
the recorder. history.deribit.com serves every BTC option trade with its implied vol, so for each
past UTC day the recorder fits a surface every HIST_STEP_S seconds from the trades of the trailing
HIST_WINDOW_S (fit_trades), and writes the day as one file:

  ticks/v1/deribit_surface_day/date=YYYY-MM-DD/part.parquet   rows of options_surface.SURFACE_FIELDS
                                                               plus rt; method "trades" or "chain"

with the day's archived chain surfaces (method "chain", one per poll) in the same file once the
recorder ran that day, so a research window of N days reads N files. Each pass fills the missing
days of the last HIST_DAYS, newest first, a few at a time, once an hour.

Run:  python -m data_pipeline.deribit_options record      (unit deribit-options-recorder, COLLECTOR box)
      python -m data_pipeline.deribit_options backfill [days]
"""
import json
import math
import os
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

import requests

from data_pipeline import options_surface as osf
from data_pipeline.tick_recorder import TICK_DIR, HourlyFile, write_heartbeat

API = os.getenv("TAU_DERIBIT_API", "https://www.deribit.com/api/v2")
HIST_API = os.getenv("TAU_DERIBIT_HIST_API", "https://history.deribit.com/api/v2")
CURRENCY = "BTC"
POLL_S = float(os.getenv("TAU_DERIBIT_POLL_S", "60"))
HIST_DAYS = int(os.getenv("TAU_DERIBIT_HIST_DAYS", "120"))
HIST_DAYS_PER_PASS = int(os.getenv("TAU_DERIBIT_HIST_DAYS_PER_PASS", "20"))
HIST_PASS_S = 3600
HIST_STEP_S = 900
HIST_WINDOW_S = 3600
HIST_HALF_LIFE_S = 1200
HIST_PAGE = 1000
BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
PREFIX = os.getenv("TAU_TICK_PREFIX", "ticks")
HEARTBEAT_KEY = "tick_recorder_deribit"
DAY_TABLE = "deribit_surface_day"
# Summary fields kept per option (the rest of Deribit's answer is 24h stats nobody prices off).
KEEP = ("instrument_name", "mark_iv", "mark_price", "bid_price", "ask_price", "underlying_price",
        "estimated_delivery_price", "open_interest", "volume", "creation_timestamp")
_MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
                                            "OCT", "NOV", "DEC"))}


def day_key(day: datetime) -> str:
    return f"{PREFIX}/v1/{DAY_TABLE}/date={day:%Y-%m-%d}/part.parquet"


# --- instruments ------------------------------------------------------------------------------

def parse_instrument(name: str) -> Optional[Tuple[int, float, str]]:
    """BTC-25OCT26-110000-C -> (expiry epoch s at 08:00 UTC, strike, "C"|"P"), or None."""
    parts = (name or "").split("-")
    if len(parts) != 4 or parts[3] not in ("C", "P"):
        return None
    code = parts[1].upper()
    try:
        day, mon, yy = int(code[:-5]), _MONTHS[code[-5:-2]], int(code[-2:])
        strike = float(parts[2].replace("d", "."))
        exp = datetime(2000 + yy, mon, day, 8, tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return None
    return int(exp.timestamp()), strike, parts[3]


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def surface_from_chain(summary: Iterable[Dict], snap_ts: int, index_price: Optional[float] = None,
                       known_ns: int = 0) -> Optional[osf.Surface]:
    """The surface of one book-summary poll: per expiry, the median underlying_price is the forward
    and each out-of-the-money option's mark_iv is a point on the smile (Deribit fits one curve, so
    the in-the-money side only repeats it)."""
    by: Dict[int, List[Tuple[float, str, float, Optional[float]]]] = {}
    idx = []
    for r in summary:
        inst = parse_instrument(r.get("instrument_name"))
        iv = _f(r.get("mark_iv"))
        if inst is None or iv is None or iv <= 0:
            continue
        exp, k, cp = inst
        by.setdefault(exp, []).append((k, cp, iv / 100.0, _f(r.get("underlying_price"))))
        d = _f(r.get("estimated_delivery_price"))
        if d:
            idx.append(d)
    if index_price is None and idx:
        index_price = sorted(idx)[len(idx) // 2]
    if not index_price or index_price <= 0:
        return None
    exps = []
    for exp, rows in sorted(by.items()):
        t = (exp - snap_ts) / osf.YEAR_S
        if exp - snap_ts < osf.MIN_EXPIRY_S:
            continue
        fwds = sorted(u for _k, _cp, _iv, u in rows if u)
        fwd = fwds[len(fwds) // 2] if fwds else index_price
        pts = [(math.log(k / fwd), iv) for k, cp, iv, _u in rows if (cp == "C") == (k >= fwd)]
        fit = osf.fit_smooth(pts, t)
        if fit is None:
            continue
        exps.append(osf.Expiry(exp, math.log(fwd / index_price), fit[0], fit[1], len(pts)))
    if not exps:
        return None
    return osf.Surface(int(snap_ts), float(index_price), tuple(exps), "chain", known_ns)


def surface_from_trades(trades: Iterable[Dict], snap_ts: int, window_s: int = HIST_WINDOW_S,
                        half_life_s: float = HIST_HALF_LIFE_S) -> Optional[osf.Surface]:
    """A surface at snap_ts from the option trades of the window before it (history.deribit.com
    rows: instrument_name, timestamp ms, iv in percent, index_price, amount). Each trade's
    moneyness is against its own index price, weighted by size and halved every half_life_s."""
    by: Dict[int, List[Tuple[float, float, float]]] = {}
    last_idx, last_t = None, -1
    lo_ms, hi_ms = (snap_ts - window_s) * 1000, snap_ts * 1000
    for tr in trades:
        ts = tr.get("timestamp")
        if ts is None or not (lo_ms <= ts < hi_ms):
            continue
        inst = parse_instrument(tr.get("instrument_name"))
        iv, ix = _f(tr.get("iv")), _f(tr.get("underlying_price")) or _f(tr.get("index_price"))
        if inst is None or not iv or not ix:
            continue
        exp, k, _cp = inst
        if exp - snap_ts < osf.MIN_EXPIRY_S:
            continue
        age = snap_ts - ts / 1000.0
        w = (_f(tr.get("amount")) or 0.1) * 0.5 ** (age / half_life_s)
        by.setdefault(exp, []).append((math.log(k / ix), iv / 100.0, w))
        if ts > last_t and _f(tr.get("index_price")):
            last_t, last_idx = ts, float(tr["index_price"])
    if last_idx is None:
        return None
    exps = []
    for exp, pts in sorted(by.items()):
        fit = osf.fit_trades(pts, (exp - snap_ts) / osf.YEAR_S)
        if fit is not None:
            exps.append(osf.Expiry(exp, 0.0, fit[0], fit[1], fit[2]))
    if not exps:
        return None
    return osf.Surface(int(snap_ts), last_idx, tuple(exps), "trades", int(snap_ts) * 1_000_000_000)


# --- archiver ---------------------------------------------------------------------------------

def parse_record(rt: int, data: Dict) -> Iterable[Tuple[str, tuple]]:
    """(table, row) pairs of one recorded poll, for tick_archiver: deribit_options rows (rt,
    instrument, expiry_ts, strike, cp, mark_iv, mark_price, bid_price, ask_price, underlying_price,
    index_price, open_interest) and the fitted deribit_surface rows (rt + SURFACE_FIELDS)."""
    if not isinstance(data, dict) or data.get("type") != "book_summary":
        return
    summary = data.get("summary") or []
    index = _f(data.get("index"))
    for r in summary:
        inst = parse_instrument(r.get("instrument_name"))
        if inst is None:
            continue
        yield "deribit_options", (rt, r.get("instrument_name"), inst[0], inst[1], inst[2], _f(r.get("mark_iv")),
                                  _f(r.get("mark_price")), _f(r.get("bid_price")), _f(r.get("ask_price")),
                                  _f(r.get("underlying_price")), index, _f(r.get("open_interest")))
    s = surface_from_chain(summary, rt // 1_000_000_000, index, rt)
    if s is not None:
        for row in s.rows():
            yield "deribit_surface", (rt,) + tuple(row[f] for f in osf.SURFACE_FIELDS)


# --- HTTP -------------------------------------------------------------------------------------

def _get(base: str, method: str, params: Dict, session=None, timeout: int = 20) -> Dict:
    get = (session or requests).get
    for attempt in range(6):
        resp = get(f"{base}/public/{method}", params=params, timeout=timeout)
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(min(2 ** attempt, 30))
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"deribit {method} {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"deribit {method} error: {body['error']}")
        return body.get("result")
    raise RuntimeError(f"deribit {method}: gave up after retries")


def fetch_chain(session=None) -> Tuple[Optional[float], List[Dict]]:
    summary = _get(API, "get_book_summary_by_currency", {"currency": CURRENCY, "kind": "option"}, session) or []
    try:
        index = _f((_get(API, "get_index_price", {"index_name": "btc_usd"}, session) or {}).get("index_price"))
    except Exception:  # noqa: BLE001 - the summary carries the index too (estimated_delivery_price)
        index = None
    return index, [{k: r.get(k) for k in KEEP if k in r} for r in summary]


def fetch_trades(start_ms: int, end_ms: int, session=None, pause_s: float = 0.1) -> List[Dict]:
    """Every BTC option trade with start_ms <= timestamp < end_ms, oldest first."""
    out: List[Dict] = []
    seen = set()
    cur = start_ms
    while cur < end_ms:
        res = _get(HIST_API, "get_last_trades_by_currency_and_time",
                   {"currency": CURRENCY, "kind": "option", "start_timestamp": cur, "end_timestamp": end_ms - 1,
                    "count": HIST_PAGE, "sorting": "asc"}, session) or {}
        trades = res.get("trades") or []
        new = [t for t in trades if t.get("trade_id") not in seen]
        for t in new:
            seen.add(t.get("trade_id"))
        out.extend(new)
        if not res.get("has_more") or not trades:
            break
        last = max(int(t["timestamp"]) for t in trades)
        cur = last if new else last + 1      # a full page inside one millisecond still advances
        time.sleep(pause_s)
    return out


# --- history ----------------------------------------------------------------------------------

def day_rows(day: datetime, trades: List[Dict], chain_rows: Optional[List[Dict]] = None) -> List[Dict]:
    """A day file's rows: a trades surface every HIST_STEP_S (from the day's first step, known at
    its snap time) plus the chain rows archived that day."""
    out = []
    t0 = int(day.timestamp())
    for snap in range(t0 + HIST_STEP_S, t0 + 86400 + 1, HIST_STEP_S):
        s = surface_from_trades(trades, snap)
        if s is not None:
            for r in s.rows():
                r["rt"] = s.known_ns
                out.append(r)
    out.extend(chain_rows or [])
    return out


def write_day(rows: List[Dict], path: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    fields = [("rt", pa.int64()), ("snap_ts", pa.int64()), ("expiry_ts", pa.int64())]
    fields += [(c, pa.float64()) for c in ("index_price", "basis", "atm_iv") + osf.GRID_COLS]
    fields += [("n_points", pa.int64()), ("method", pa.string())]
    sch = pa.schema(fields)
    cols = {f.name: [r.get(f.name) for r in rows] for f in sch}
    pq.write_table(pa.table(cols, schema=sch), path, compression="zstd")


def chain_rows_for_day(day: datetime, store) -> List[Dict]:
    t = store.read("deribit_surface", day, day + timedelta(days=1))
    return t.to_pylist() if t is not None and t.num_rows else []


def backfill(days: int = HIST_DAYS, max_days: int = HIST_DAYS_PER_PASS, s3=None, now: Optional[datetime] = None,
             fetch=fetch_trades, store=None) -> int:
    """Write the missing day files of the last ``days`` complete UTC days, newest first, at most
    ``max_days`` per call. A day is complete 30 minutes after it ends (its last chain hour archived)."""
    from data_pipeline.tick_store import TickStore
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    store = store or TickStore(bucket=BUCKET, prefix=PREFIX, s3=s3, cache_dir=tempfile.mkdtemp(prefix="deribit_day_"))
    now = now or datetime.now(timezone.utc)
    last = (now - timedelta(minutes=30)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    done = 0
    for k in range(days):
        if done >= max_days:
            break
        day = last - timedelta(days=k)
        key = day_key(day)
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
            continue
        except Exception:  # noqa: BLE001 - absent: build it
            pass
        t_start = time.time()
        trades = fetch(int((day.timestamp() - HIST_WINDOW_S) * 1000), int((day.timestamp() + 86400) * 1000))
        rows = day_rows(day, trades, chain_rows_for_day(day, store))
        if not rows:
            print(f"deribit history {day:%Y-%m-%d}: no surface from {len(trades)} trades", flush=True)
            continue
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "part.parquet")
            write_day(rows, p)
            s3.upload_file(p, BUCKET, key)
        done += 1
        print(f"deribit history {day:%Y-%m-%d}: {len(trades)} trades -> {len(rows)} surface rows "
              f"in {time.time() - t_start:.0f}s", flush=True)
    return done


# --- recorder ---------------------------------------------------------------------------------

class DeribitRecorder:
    source = "deribit"

    def __init__(self) -> None:
        self.file = HourlyFile(TICK_DIR, self.source)
        self.session = requests.Session()
        self.polls = 0
        self.fails = 0
        self.last_ok = 0.0
        self.errors: List[str] = []
        self.hist = {"days_written": 0, "last_pass": None, "error": None}

    def poll(self) -> Optional[osf.Surface]:
        rt = time.time_ns()
        index, summary = fetch_chain(self.session)
        line = json.dumps({"rt": rt, "m": {"type": "book_summary", "index": index, "summary": summary}},
                          separators=(",", ":"))
        self.file.write(rt, line)
        self.file.flush()
        self.polls += 1
        self.last_ok = time.time()
        return surface_from_chain(summary, rt // 1_000_000_000, index, rt)

    def heartbeat(self, surface: Optional[osf.Surface]) -> None:
        state = {"host": socket.gethostname(), "polls": self.polls, "fails": self.fails,
                 "last_msg_age_s": round(time.time() - self.last_ok, 1) if self.last_ok else None,
                 "errors": self.errors[-5:], "history": self.hist}
        if surface is not None:
            state["surface"] = surface.rows()
            state["snap_ts"] = surface.snap_ts
        write_heartbeat(HEARTBEAT_KEY, state)

    def history_loop(self) -> None:
        while True:
            try:
                self.hist["days_written"] += backfill()
                self.hist["error"] = None
            except Exception as e:  # noqa: BLE001 - retried next pass
                self.hist["error"] = f"{type(e).__name__}: {e}"[:300]
                print(f"[WARN] deribit history: {self.hist['error']}", flush=True)
            self.hist["last_pass"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            time.sleep(HIST_PASS_S)

    def run(self) -> None:
        threading.Thread(target=self.history_loop, daemon=True).start()
        print(f"deribit options recorder -> {TICK_DIR}/{self.source} every {POLL_S:g}s", flush=True)
        while True:
            t0 = time.time()
            surface = None
            try:
                surface = self.poll()
            except Exception as e:  # noqa: BLE001 - one bad poll must not stop the recorder
                self.fails += 1
                self.errors.append(f"{datetime.now(timezone.utc):%H:%M:%S} {type(e).__name__}: {e}"[:300])
                self.errors = self.errors[-20:]
                print(f"[WARN] deribit poll: {e}", flush=True)
            self.heartbeat(surface)
            time.sleep(max(1.0, POLL_S - (time.time() - t0)))


def main(argv: List[str]) -> None:
    which = argv[1] if len(argv) > 1 else "record"
    if which == "backfill":
        n = backfill(int(argv[2]) if len(argv) > 2 else HIST_DAYS, max_days=10_000)
        print(f"deribit history: wrote {n} day files", flush=True)
        return
    DeribitRecorder().run()


if __name__ == "__main__":
    main(sys.argv)
