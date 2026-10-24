"""Turn tick_recorder's closed hourly NDJSON files into S3 Parquet, and record a manifest row.

Layout (bucket DATALAKE_BUCKET):
  ticks/v1/<table>/date=YYYY-MM-DD/hour=HH/part.parquet   typed, zstd, one file per table-hour
  ticks/raw/<source>/date=YYYY-MM-DD/HH.ndjson.gz          the recorder's lines, lossless
  ticks/manifest/<source>/date=YYYY-MM-DD/HH.json          the manifest row below, as JSON

Tables (rt = receive time, epoch ns, on every row):
  kalshi_book     ticker, kind, side, price, qty, sid, seq, upd_rt, exch_ms
                  kind 0 = exchange snapshot level, 1 = delta (qty is the change),
                  3 = recorder checkpoint level (top of each hour). A row with kind 0/3 and side
                  NULL is a reset marker: clear that ticker's book before applying the levels; its
                  upd_rt is when the book last really changed (a checkpoint is not a change).
  kalshi_markets  ticker, event_ticker, series, open_ts, close_ts, floor_strike, cap_strike,
                  strike_type, status (on subscribe/change, and for every market each hour)
  kalshi_trades   ticker, trade_id, yes_price, no_price, count, taker_side, ts_s, exch_ms
  kalshi_ticker   ticker, price, yes_bid, yes_ask, yes_bid_size, yes_ask_size, volume, open_interest, ts_s,
                  exch_ms (exchange time, ms; kalshi_book deltas carry it too: rt - exch_ms = feed latency)
  coinbase_trades product_id, trade_id, price, size, taker_side, exch_ns
  coinbase_ticker product_id, trade_id, price, best_bid, best_ask, best_bid_size, best_ask_size, exch_ns
  tick_meta       source, event, detail (connects, disconnects, sequence gaps)

The RDS row (tick_archive_hours) is what gap monitoring and research discovery read: per source
and hour, message count, max silence between messages, sequence gaps, reconnects, bytes.

Each run also builds features_1s (data_pipeline/tick_features.py) for archived hours that lack
it, and guards the disk: below TAU_TICK_MIN_FREE_GB free (default 3) the oldest unarchived hour
files are deleted, so failing uploads cost old ticks, never a full disk under the collectors.

Run: python -m data_pipeline.tick_archiver   (timer kalshi-tick-archiver, every 10 minutes)
"""
import glob
import gzip
import json
import os
import shutil
import socket
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.init_schema import TICK_ARCHIVE_DDL as MANIFEST_DDL
from data_pipeline.tick_recorder import TICK_DIR, delta_fields, snapshot_levels, _num

BUCKET = os.getenv("DATALAKE_BUCKET", "kalshi-trade-datalake-568386354218-us-east-1")
PREFIX = os.getenv("TAU_TICK_PREFIX", "ticks")
CLOSE_GRACE_S = 120      # an hour is archived this long after it ends
FLUSH_ROWS = 200_000



def _schemas():
    import pyarrow as pa
    rt = ("rt", pa.int64())
    s, f, i64 = pa.string(), pa.float64(), pa.int64()
    return {
        "kalshi_book": pa.schema([rt, ("ticker", s), ("kind", pa.int8()), ("side", s), ("price", f),
                                  ("qty", f), ("sid", i64), ("seq", i64), ("upd_rt", i64),
                                  ("exch_ms", i64)]),
        "kalshi_markets": pa.schema([rt, ("ticker", s), ("event_ticker", s), ("series", s), ("open_ts", i64),
                                     ("close_ts", i64), ("floor_strike", f), ("cap_strike", f),
                                     ("strike_type", s), ("status", s)]),
        "kalshi_trades": pa.schema([rt, ("ticker", s), ("trade_id", s), ("yes_price", f), ("no_price", f),
                                    ("count", f), ("taker_side", s), ("ts_s", i64), ("exch_ms", i64)]),
        "kalshi_ticker": pa.schema([rt, ("ticker", s), ("price", f), ("yes_bid", f), ("yes_ask", f),
                                    ("yes_bid_size", f), ("yes_ask_size", f), ("volume", f),
                                    ("open_interest", f), ("ts_s", i64), ("exch_ms", i64)]),
        "coinbase_trades": pa.schema([rt, ("product_id", s), ("trade_id", i64), ("price", f), ("size", f),
                                      ("taker_side", s), ("exch_ns", i64)]),
        "coinbase_ticker": pa.schema([rt, ("product_id", s), ("trade_id", i64), ("price", f), ("best_bid", f),
                                      ("best_ask", f), ("best_bid_size", f), ("best_ask_size", f),
                                      ("exch_ns", i64)]),
        "tick_meta": pa.schema([rt, ("source", s), ("event", s), ("detail", s)]),
    }


def _dollars(msg: Dict, key: str) -> Optional[float]:
    v = _num(msg.get(key + "_dollars"))
    if v is not None:
        return v
    v = _num(msg.get(key))
    return None if v is None else v / 100.0


def _fp(msg: Dict, key: str) -> Optional[float]:
    v = _num(msg.get(key + "_fp"))
    return v if v is not None else _num(msg.get(key))


def _int(v) -> Optional[int]:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def _iso_ns(v) -> Optional[int]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return int(dt.timestamp()) * 1_000_000_000 + dt.microsecond * 1000
    except ValueError:
        return None


def _book_levels(rt: int, ticker: str, kind: int, book: Dict, sid=None, seq=None) -> List[tuple]:
    # Reset marker; on a checkpoint it carries upd_rt, the rt of the book's last real update.
    rows = [(rt, ticker, kind, None, None, None, sid, seq, _int(book.get("t")) if kind == 3 else rt, None)]
    for side in ("yes", "no"):
        for p, q in book.get(side, []):
            rows.append((rt, ticker, kind, side, float(p), float(q), sid, seq, None, None))
    return rows


def _epoch_s(v) -> Optional[int]:
    ns = _iso_ns(v)
    return None if ns is None else ns // 1_000_000_000


def parse_line(source: str, line: str) -> Iterable[Tuple[str, tuple]]:
    """(table, row) pairs for one recorder line."""
    rec = json.loads(line)
    rt = int(rec["rt"])
    if "meta" in rec:
        detail = {k: v for k, v in rec.items() if k not in ("rt", "meta")}
        yield "tick_meta", (rt, source, rec["meta"], json.dumps(detail) if detail else None)
        return
    if "markets" in rec:
        for m in rec["markets"] or []:
            yield "kalshi_markets", (rt, m.get("ticker"), m.get("event_ticker"), m.get("series_ticker"),
                                     _epoch_s(m.get("open_time")), _epoch_s(m.get("close_time")),
                                     _num(m.get("floor_strike")), _num(m.get("cap_strike")),
                                     m.get("strike_type"), m.get("status"))
        return
    if "checkpoint" in rec:
        for t, book in (rec["checkpoint"] or {}).items():
            for row in _book_levels(rt, t, 3, book):
                yield "kalshi_book", row
        return
    data = rec.get("m") or {}
    typ = data.get("type")
    if source == "kalshi":
        msg = data.get("msg") or {}
        t = msg.get("market_ticker")
        if typ == "orderbook_snapshot" and t:
            book = {s: snapshot_levels(msg, s) for s in ("yes", "no")}
            for row in _book_levels(rt, t, 0, book, data.get("sid"), data.get("seq")):
                yield "kalshi_book", row
        elif typ == "orderbook_delta" and t:
            side, price, d = delta_fields(msg)
            yield "kalshi_book", (rt, t, 1, side, price, d, data.get("sid"), data.get("seq"), None,
                                  _int(msg.get("ts_ms")))
        elif typ == "trade" and t:
            yield "kalshi_trades", (rt, t, str(msg.get("trade_id") or ""), _dollars(msg, "yes_price"),
                                    _dollars(msg, "no_price"), _fp(msg, "count"), msg.get("taker_side"),
                                    _int(msg.get("ts")), _int(msg.get("ts_ms")))
        elif typ == "ticker" and t:
            yield "kalshi_ticker", (rt, t, _dollars(msg, "price"), _dollars(msg, "yes_bid"), _dollars(msg, "yes_ask"),
                                    _fp(msg, "yes_bid_size"), _fp(msg, "yes_ask_size"), _fp(msg, "volume"),
                                    _fp(msg, "open_interest"), _int(msg.get("ts")), _int(msg.get("ts_ms")))
    elif source == "coinbase":
        if typ in ("match", "last_match"):
            # Coinbase "side" is the MAKER's side; the taker is the other one.
            maker = data.get("side")
            taker = {"buy": "sell", "sell": "buy"}.get(maker)
            yield "coinbase_trades", (rt, data.get("product_id"), _int(data.get("trade_id")), _num(data.get("price")),
                                      _num(data.get("size")), taker, _iso_ns(data.get("time")))
        elif typ == "ticker":
            yield "coinbase_ticker", (rt, data.get("product_id"), _int(data.get("trade_id")), _num(data.get("price")),
                                      _num(data.get("best_bid")), _num(data.get("best_ask")),
                                      _num(data.get("best_bid_size")), _num(data.get("best_ask_size")),
                                      _iso_ns(data.get("time")))


class TableWriters:
    def __init__(self, tmpdir: str) -> None:
        self.tmpdir = tmpdir
        self.schemas = _schemas()
        self.buf: Dict[str, List[tuple]] = {}
        self.writers: Dict[str, object] = {}
        self.rows: Dict[str, int] = {}

    def add(self, table: str, row: tuple) -> None:
        b = self.buf.setdefault(table, [])
        b.append(row)
        if len(b) >= FLUSH_ROWS:
            self._flush(table)

    def _flush(self, table: str) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq
        rows = self.buf.get(table) or []
        if not rows:
            return
        schema = self.schemas[table]
        cols = list(zip(*rows))
        arrays = [pa.array(list(c), type=schema.field(i).type) for i, c in enumerate(cols)]
        tbl = pa.Table.from_arrays(arrays, schema=schema)
        if table not in self.writers:
            self.writers[table] = pq.ParquetWriter(os.path.join(self.tmpdir, table + ".parquet"), schema,
                                                   compression="zstd", use_dictionary=True)
        self.writers[table].write_table(tbl)
        self.rows[table] = self.rows.get(table, 0) + len(rows)
        self.buf[table] = []

    def close(self) -> Dict[str, str]:
        for t in list(self.buf):
            self._flush(t)
        for w in self.writers.values():
            w.close()
        return {t: os.path.join(self.tmpdir, t + ".parquet") for t in self.writers}


def archive_file(path: str, source: str, hour: datetime, s3=None, conn=None) -> Dict:
    """Parquet + raw gzip to S3, manifest to RDS + S3. Returns the manifest."""
    tmpdir = tempfile.mkdtemp(prefix="tickarch_")
    try:
        writers = TableWriters(tmpdir)
        n = 0
        first = last = None
        max_gap = 0.0
        gaps = reconnects = bad = 0
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    pairs = list(parse_line(source, line))
                    rt = int(json.loads(line)["rt"]) if not pairs else pairs[0][1][0]
                except Exception:
                    bad += 1   # a torn last line from a crash; the raw archive keeps it
                    continue
                n += 1
                if last is not None:
                    max_gap = max(max_gap, (rt - last) / 1e9)
                first = rt if first is None else first
                last = rt
                for table, row in pairs:
                    if table == "tick_meta":
                        if row[2] in ("seq_gap", "trade_id_gap"):
                            gaps += 1
                        elif row[2] == "disconnected":
                            reconnects += 1
                    writers.add(table, row)
        files = writers.close()

        raw_gz = os.path.join(tmpdir, "raw.ndjson.gz")
        with open(path, "rb") as src, gzip.open(raw_gz, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)

        date, hh = hour.strftime("%Y-%m-%d"), hour.strftime("%H")
        uploads = {f"{PREFIX}/v1/{t}/date={date}/hour={hh}/part.parquet": p for t, p in files.items()}
        uploads[f"{PREFIX}/raw/{source}/date={date}/{hh}.ndjson.gz"] = raw_gz
        parquet_bytes = sum(os.path.getsize(p) for p in files.values())
        manifest = {
            "source": source, "hour_utc": hour.strftime("%Y-%m-%d %H:00:00"), "messages": n,
            "first_rt_utc": _fmt_ns(first), "last_rt_utc": _fmt_ns(last), "max_gap_s": round(max_gap, 3),
            "seq_gaps": gaps, "reconnects": reconnects, "bad_lines": bad,
            "raw_bytes": os.path.getsize(path), "raw_gz_bytes": os.path.getsize(raw_gz),
            "parquet_bytes": parquet_bytes, "tables": writers.rows, "host": socket.gethostname(),
            "s3_prefix": f"s3://{BUCKET}/{PREFIX}/v1/",
        }
        man_path = os.path.join(tmpdir, "manifest.json")
        with open(man_path, "w") as fh:
            json.dump(manifest, fh)
        uploads[f"{PREFIX}/manifest/{source}/date={date}/{hh}.json"] = man_path

        if s3 is None:
            import boto3
            s3 = boto3.client("s3")
        for key, p in uploads.items():
            s3.upload_file(p, BUCKET, key)
        write_manifest_row(manifest, conn)
        return manifest
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _fmt_ns(ns: Optional[int]) -> Optional[str]:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def write_manifest_row(m: Dict, conn=None) -> None:
    own = conn is None
    conn = conn or get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(MANIFEST_DDL)
            cur.execute(
                """INSERT INTO tick_archive_hours
                   (source,hour_utc,messages,first_rt_utc,last_rt_utc,max_gap_s,seq_gaps,reconnects,raw_bytes,
                    parquet_bytes,tables_json,s3_prefix,host,archived_at_utc)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE messages=VALUES(messages), first_rt_utc=VALUES(first_rt_utc),
                     last_rt_utc=VALUES(last_rt_utc), max_gap_s=VALUES(max_gap_s), seq_gaps=VALUES(seq_gaps),
                     reconnects=VALUES(reconnects), raw_bytes=VALUES(raw_bytes), parquet_bytes=VALUES(parquet_bytes),
                     tables_json=VALUES(tables_json), s3_prefix=VALUES(s3_prefix), host=VALUES(host),
                     archived_at_utc=VALUES(archived_at_utc)""",
                (m["source"], m["hour_utc"], m["messages"], m["first_rt_utc"], m["last_rt_utc"], m["max_gap_s"],
                 m["seq_gaps"], m["reconnects"], m["raw_bytes"], m["parquet_bytes"], json.dumps(m["tables"]),
                 m["s3_prefix"], m["host"], utc_now().replace(tzinfo=None)),
            )
    finally:
        if own:
            conn.close()


def closed_hour_files(root: str, now: Optional[datetime] = None) -> List[Tuple[str, str, datetime]]:
    """(path, source, hour) for every hour file whose hour ended more than CLOSE_GRACE_S ago."""
    now = now or utc_now()
    out = []
    for path in sorted(glob.glob(os.path.join(root, "*", "*", "*.ndjson"))):
        parts = path.split(os.sep)
        source, day, hh = parts[-3], parts[-2], parts[-1].split(".")[0]
        try:
            hour = datetime.strptime(day + hh, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if (now - (hour + timedelta(hours=1))).total_seconds() > CLOSE_GRACE_S:
            out.append((path, source, hour))
    return out


MIN_FREE_BYTES = int(float(os.getenv("TAU_TICK_MIN_FREE_GB", "3")) * 1e9)
CACHE_DIR = os.getenv("TAU_TICK_CACHE", os.path.join(os.path.dirname(TICK_DIR.rstrip("/")) or "/", "tick_cache"))
CACHE_MAX_AGE_S = 6 * 3600
FEATURE_LOOKBACK_H = 48
FEATURE_STATE = os.path.join(os.path.dirname(TICK_DIR.rstrip("/")) or "/", "tick_features_built.json")


def disk_guard(root: str = TICK_DIR, min_free: int = MIN_FREE_BYTES, now: Optional[datetime] = None) -> List[str]:
    """If free space is under ``min_free`` (uploads failing for hours, say), delete the oldest
    closed hour files until it is not. Losing old ticks beats filling the disk under every
    collector on the box. Returns what was deleted."""
    dropped = []
    for path, _source, _hour in closed_hour_files(root, now):
        if shutil.disk_usage(root).free >= min_free:
            break
        os.remove(path)
        dropped.append(path)
        print(f"[ERROR] disk guard: free < {min_free / 1e9:.1f} GB, deleted unarchived {path}", flush=True)
    return dropped


def clean_cache(cache_dir: str = CACHE_DIR, max_age_s: int = CACHE_MAX_AGE_S) -> None:
    cutoff = utc_now().timestamp() - max_age_s
    for dirpath, _dirs, files in os.walk(cache_dir):
        for f in files:
            p = os.path.join(dirpath, f)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass


def _load_built() -> set:
    try:
        with open(FEATURE_STATE) as fh:
            return set(json.load(fh))
    except Exception:
        return set()


def _save_built(built: set) -> None:
    keep = sorted(built)[-FEATURE_LOOKBACK_H * 2:]
    with open(FEATURE_STATE + ".tmp", "w") as fh:
        json.dump(keep, fh)
    os.replace(FEATURE_STATE + ".tmp", FEATURE_STATE)


def _exists(s3, key: str) -> bool:
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


def build_features(s3=None, store=None, now: Optional[datetime] = None, conn=None) -> int:
    """features_1s for every archived Kalshi hour in the last FEATURE_LOOKBACK_H that lacks it,
    once its Coinbase hour is archived too (or 2 hours have passed without it)."""
    from data_pipeline import tick_features
    from data_pipeline.tick_store import TickStore
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    store = store or TickStore(bucket=BUCKET, prefix=PREFIX, cache_dir=CACHE_DIR, s3=s3)
    now = now or utc_now()
    built = _load_built()
    top = now.replace(minute=0, second=0, microsecond=0)
    n = 0
    for k in range(FEATURE_LOOKBACK_H, 0, -1):
        hour = top - timedelta(hours=k)
        tag = hour.strftime("%Y-%m-%d %H")
        if tag in built:
            continue
        date, hh = hour.strftime("%Y-%m-%d"), hour.strftime("%H")
        if not _exists(s3, f"{PREFIX}/manifest/kalshi/date={date}/{hh}.json"):
            continue
        if not _exists(s3, f"{PREFIX}/manifest/coinbase/date={date}/{hh}.json") and k < 2:
            continue
        tmpdir = tempfile.mkdtemp(prefix="tickfeat_")
        try:
            out = os.path.join(tmpdir, "part.parquet")
            t0 = utc_now()
            res = tick_features.build_hour(store, hour, out)
            if res is not None:
                s3.upload_file(out, BUCKET, f"{PREFIX}/v1/features_1s/date={date}/hour={hh}/part.parquet")
                manifest = {"source": "features_1s", "hour_utc": hour.strftime("%Y-%m-%d %H:00:00"),
                            "messages": res["rows"], "first_rt_utc": None, "last_rt_utc": None, "max_gap_s": None,
                            "seq_gaps": 0, "reconnects": 0, "raw_bytes": 0, "parquet_bytes": os.path.getsize(out),
                            "tables": {"features_1s": res["rows"], "tickers": res["tickers"]},
                            "host": socket.gethostname(), "s3_prefix": f"s3://{BUCKET}/{PREFIX}/v1/",
                            "build_s": round((utc_now() - t0).total_seconds(), 1)}
                man = os.path.join(tmpdir, "manifest.json")
                with open(man, "w") as fh:
                    json.dump(manifest, fh)
                s3.upload_file(man, BUCKET, f"{PREFIX}/manifest/features_1s/date={date}/{hh}.json")
                write_manifest_row(manifest, conn)
                print(f"features_1s {tag}:00 rows={res['rows']} tickers={res['tickers']} "
                      f"{manifest['parquet_bytes'] / 1e6:.1f}MB in {manifest['build_s']}s", flush=True)
                n += 1
            built.add(tag)
            _save_built(built)
        except Exception as e:
            print(f"[ERROR] features_1s {tag}: {type(e).__name__}: {e}", flush=True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return n


def run_once() -> int:
    done = 0
    for path, source, hour in closed_hour_files(TICK_DIR):
        try:
            m = archive_file(path, source, hour)
        except Exception as e:
            print(f"[ERROR] archive {path}: {e}", flush=True)
            continue
        os.remove(path)
        done += 1
        print(f"archived {source} {hour:%Y-%m-%d %H}:00 msgs={m['messages']} raw={m['raw_bytes']/1e6:.1f}MB "
              f"parquet={m['parquet_bytes']/1e6:.1f}MB max_gap={m['max_gap_s']}s seq_gaps={m['seq_gaps']} "
              f"tables={m['tables']}", flush=True)
    for d in glob.glob(os.path.join(TICK_DIR, "*", "*")):
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    disk_guard()
    try:
        build_features()
    except Exception as e:
        print(f"[ERROR] features_1s: {type(e).__name__}: {e}", flush=True)
    clean_cache()
    return done


if __name__ == "__main__":
    n = run_once()
    print(f"tick archiver: {n} hour file(s) archived", flush=True)
    sys.exit(0)
