"""Delete stored Kalshi data for series we don't trade (Todd, 2026-10-24: keep sports, weather
and crypto only; see data_pipeline.common.TRADED_CATEGORIES).

Dry run by default: classifies every series found in kalshi_series / markets / hist_markets,
then prints, per table, the rows and estimated GB that belong to untraded series. Nothing is
written until --apply.

  python -m scripts.prune_untraded_markets                       # dry run (counts only)
  python -m scripts.prune_untraded_markets --apply               # batched DELETEs
  python -m scripts.prune_untraded_markets --apply --rebuild-markets

Safety:
  * A series is untraded only if its category (Kalshi /series, else kalshi_series.category) is
    outside TRADED_CATEGORIES, or it is a multi-leg (MVE) parlay. Series with no known category
    are reported and left alone unless --include-unknown.
  * Never touches a curated series, a series with an open app_positions row or a 'sent'
    app_order_intents row, or the market of a deployment that isn't stopped.
  * DELETEs run in small LIMIT batches with a pause between them, and the run stops at
    --stop-at (UTC, default 23:45) so it can't overlap a maintenance window. Re-running resumes.

InnoDB keeps a table's file size after DELETE (the space is reused, not returned). The `markets`
table is ~99% parlay rows, so --rebuild-markets copies the kept rows into a fresh table and
swaps it in with one atomic RENAME, which returns the space for real once the old table is
dropped (--drop-old, or by hand after checking).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

import pymysql

from data_pipeline.common import TRADED_CATEGORIES, api_get, get_db_conn, is_traded_series

# Child tables first, the catalog row last, so an interrupted run still lists what's left.
# (table, column the series is matched on, rows per DELETE batch). markets rows can carry
# ~20KB of legacy raw_json each, so its batches are smaller.
TABLES: List[Tuple[str, str, int]] = [
    ("market_candles", "ticker", 5000),
    ("market_trades", "ticker", 5000),
    ("hist_markets", "series_ticker", 5000),
    ("markets", "series_ticker", 500),
    ("kalshi_series", "series_ticker", 500),
]


def _series_of_ticker(ticker: str) -> str:
    return (ticker or "").split("-", 1)[0]


def ticker_range(series: str) -> Tuple[str, str]:
    """[lo, hi) bounds of every market ticker in a series ("KXFOO-..."), so a PK/index range scan
    finds them. '.' is the character right after '-', and series tickers never contain '-'."""
    return series + "-", series + "."


def _col(row, key):
    return row[key] if isinstance(row, dict) else row[0]


def known_series(cur) -> Dict[str, Optional[str]]:
    """series_ticker -> category from our own tables (kalshi_series has the category; markets and
    hist_markets just contribute series names). DISTINCT over the series indexes, no full scan."""
    out: Dict[str, Optional[str]] = {}
    cur.execute("SELECT series_ticker, category FROM kalshi_series")
    for r in cur.fetchall():
        out[r["series_ticker"]] = r["category"]
    for table in ("markets", "hist_markets"):
        cur.execute("SELECT DISTINCT series_ticker FROM %s WHERE series_ticker IS NOT NULL" % table)
        for r in cur.fetchall():
            out.setdefault(_col(r, "series_ticker"), None)
    out.pop("", None)
    return out


def kalshi_categories() -> Dict[str, Optional[str]]:
    """series_ticker -> category for every Kalshi series (one bulk call). {} if unreachable."""
    try:
        data = api_get("/series")
    except Exception as e:
        print("[prune] /series fetch failed (%r); using kalshi_series.category only" % e, flush=True)
        return {}
    return {s["ticker"]: s.get("category") for s in data.get("series") or [] if s.get("ticker")}


def protected_series(cur, candidates: Iterable[str]) -> Dict[str, str]:
    """series -> reason, for every series something live still depends on."""
    from app.trading.markets import CURATED, _market_key

    out: Dict[str, str] = {m.series: "curated" for m in CURATED.values()}
    cur.execute("SELECT DISTINCT ticker FROM app_positions WHERE status='open'")
    for r in cur.fetchall():
        out.setdefault(_series_of_ticker(r["ticker"]), "open position")
    cur.execute("SELECT DISTINCT ticker FROM app_order_intents WHERE status='sent'")
    for r in cur.fetchall():
        out.setdefault(_series_of_ticker(r["ticker"]), "sent order intent")
    cur.execute("SELECT DISTINCT market FROM app_deployments WHERE status <> 'stopped'")
    live_keys = {r["market"] for r in cur.fetchall()}
    if live_keys:
        # app_deployments.market is VARCHAR(16), so compare the truncated key too.
        for s in candidates:
            k = _market_key(s)
            if k in live_keys or k[:16] in live_keys:
                out.setdefault(s, "deployment not stopped")
    return out


def classify(ours: Dict[str, Optional[str]], kalshi: Dict[str, Optional[str]], protected: Dict[str, str],
             include_unknown: bool) -> Tuple[List[Tuple[str, str]], List[str], Dict[str, str]]:
    """Split series into (untraded [(series, category)], unknown [series], kept-by-protection)."""
    untraded, unknown, saved = [], [], {}
    for s in sorted(ours):
        category = kalshi.get(s) or ours.get(s)
        is_parlay = "MVE" in s.upper()
        if not is_parlay and not category:
            if not include_unknown:
                unknown.append(s)
                continue
        elif is_traded_series(s, category):
            continue
        if s in protected:
            saved[s] = protected[s]
            continue
        untraded.append((s, category or ("parlay" if is_parlay else "unknown")))
    return untraded, unknown, saved


def _where(col: str, series: str) -> Tuple[str, tuple]:
    if col == "ticker":
        lo, hi = ticker_range(series)
        return "ticker >= %s AND ticker < %s", (lo, hi)
    return "series_ticker = %s", (series,)


def table_stats(cur) -> Dict[str, Dict[str, float]]:
    cur.execute(
        "SELECT table_name AS t, table_rows AS n, data_length + index_length AS b, data_free AS f "
        "FROM information_schema.tables WHERE table_schema = DATABASE()"
    )
    return {r["t"]: {"rows": float(r["n"] or 0), "bytes": float(r["b"] or 0), "free": float(r["f"] or 0)}
            for r in cur.fetchall()}


def count_rows(cur, table: str, col: str, series: str) -> int:
    where, params = _where(col, series)
    cur.execute("SELECT COUNT(*) AS n FROM %s WHERE %s" % (table, where), params)
    return int(cur.fetchone()["n"])


def delete_series(cur, table: str, col: str, series: str, batch: int, pause: float, deadline: float) -> Tuple[int, bool]:
    """Delete one series' rows from one table in LIMIT batches. Returns (rows, finished)."""
    where, params = _where(col, series)
    total = 0
    while True:
        if time.time() >= deadline:
            return total, False
        cur.execute("DELETE FROM %s WHERE %s LIMIT %d" % (table, where, batch), params)
        n = cur.rowcount or 0
        total += n
        if n < batch:
            return total, True
        time.sleep(pause)


def _fill_blank_series(cur) -> None:
    """The copy matches on series_ticker, so a row with it blank would be left behind. The live
    KXBTC15M/ETH/SOL/... rows are written that way (4,775 on 10-24), so derive it first."""
    cur.execute("UPDATE markets SET series_ticker = SUBSTRING_INDEX(event_ticker, '-', 1) "
                "WHERE (series_ticker IS NULL OR series_ticker = '') AND event_ticker IS NOT NULL")
    print("[prune] markets: filled blank series_ticker on %d rows" % (cur.rowcount or 0), flush=True)


def drop_old_markets(conn) -> int:
    """DROP markets__untraded_old, but only if every curated series that had rows there also has
    rows in the new markets table. Returns 0 on drop, 1 if a check fails."""
    from app.trading.markets import CURATED

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'markets__untraded_old'")
    if not int(cur.fetchone()["n"]):
        print("[prune] no markets__untraded_old table; nothing to drop", flush=True)
        return 1
    missing = []
    for series in sorted({m.series for m in CURATED.values()}):
        new = count_rows(cur, "markets", "series_ticker", series)
        old = count_rows(cur, "markets__untraded_old", "series_ticker", series)
        print("[prune] curated %-14s markets=%8d  old=%8d" % (series, new, old), flush=True)
        if old and not new:
            missing.append(series)
    cur.execute("SELECT COUNT(*) AS n FROM markets")
    print("[prune] markets rows now: %d" % int(cur.fetchone()["n"]), flush=True)
    if missing:
        print("[prune] NOT dropping: curated series missing from markets: %s" % ", ".join(missing), flush=True)
        return 1
    cur.execute("DROP TABLE markets__untraded_old")
    print("[prune] dropped markets__untraded_old", flush=True)
    return 0


def rebuild_markets(conn, keep_series: Set[str], drop_old: bool) -> None:
    """Copy the kept `markets` rows into markets__keep, catch up on rows written meanwhile, then
    swap with one atomic RENAME. A short lock_wait_timeout makes the RENAME give up rather than
    queue every reader behind a metadata lock if a long query is holding the table."""
    cur = conn.cursor()
    keep = sorted(keep_series)
    _fill_blank_series(cur)
    cur.execute("DROP TABLE IF EXISTS markets__keep")
    cur.execute("CREATE TABLE markets__keep LIKE markets")
    started = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    copied = 0
    for i in range(0, len(keep), 200):
        chunk = keep[i:i + 200]
        cur.execute("INSERT IGNORE INTO markets__keep SELECT * FROM markets WHERE series_ticker IN (%s)"
                    % ",".join(["%s"] * len(chunk)), tuple(chunk))
        copied += cur.rowcount or 0
    print("[prune] markets__keep: copied %d rows" % copied, flush=True)
    _fill_blank_series(cur)   # rows forward_collector wrote (blank) during the copy
    for i in range(0, len(keep), 200):
        chunk = keep[i:i + 200]
        cur.execute("REPLACE INTO markets__keep SELECT * FROM markets WHERE series_ticker IN (%s) AND last_seen_utc >= %%s"
                    % ",".join(["%s"] * len(chunk)), tuple(chunk) + (started,))
    cur.execute("SET SESSION lock_wait_timeout = 5")
    for attempt in range(1, 13):
        try:
            cur.execute("RENAME TABLE markets TO markets__untraded_old, markets__keep TO markets")
            break
        except pymysql.err.OperationalError as e:
            if not e.args or e.args[0] != 1205 or attempt == 12:   # 1205: lock wait timeout
                raise
            print("[prune] RENAME blocked by a metadata lock; retry %d in 10s" % attempt, flush=True)
            time.sleep(10)
    print("[prune] swapped: markets now holds only kept series; old table is markets__untraded_old", flush=True)
    if drop_old:
        cur.execute("DROP TABLE markets__untraded_old")
        print("[prune] dropped markets__untraded_old", flush=True)


def _deadline(stop_at: str) -> float:
    hh, mm = (int(x) for x in stop_at.split(":"))
    now = datetime.now(timezone.utc)
    end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if end <= now:
        raise SystemExit("--stop-at %s UTC has already passed today; pick a later time" % stop_at)
    return end.timestamp()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--include-unknown", action="store_true", help="also prune series with no known category")
    ap.add_argument("--rebuild-markets", action="store_true",
                    help="swap `markets` for a copy holding only kept series instead of DELETEing from it")
    ap.add_argument("--drop-old", action="store_true", help="with --rebuild-markets, drop the old table after the swap")
    ap.add_argument("--drop-old-only", action="store_true",
                    help="only drop markets__untraded_old, after checking curated series survived the swap")
    ap.add_argument("--pause", type=float, default=0.2, help="seconds between DELETE batches")
    ap.add_argument("--stop-at", default="23:45", help="UTC HH:MM to stop deleting (resume by re-running)")
    ap.add_argument("--tables", default=",".join(t for t, _, _ in TABLES), help="comma list of tables to prune")
    args = ap.parse_args(argv)
    tables = [t for t in TABLES if t[0] in set(args.tables.split(","))]
    deadline = _deadline(args.stop_at) if args.apply else float("inf")

    conn = get_db_conn()
    if args.drop_old_only:
        return drop_old_markets(conn)
    cur = conn.cursor()
    ours = known_series(cur)
    kalshi = kalshi_categories()
    protected = protected_series(cur, ours)
    untraded, unknown, saved = classify(ours, kalshi, protected, args.include_unknown)
    print("[prune] traded categories: %s" % ", ".join(sorted(TRADED_CATEGORIES)))
    print("[prune] series seen=%d untraded=%d unknown-category=%d protected=%d"
          % (len(ours), len(untraded), len(unknown), len(saved)))
    for s, why in sorted(saved.items()):
        if s in ours and not is_traded_series(s, kalshi.get(s) or ours.get(s)):
            print("[prune]   keeping untraded %s (%s)" % (s, why))
    if unknown:
        print("[prune]   unknown category (left alone): %s" % ", ".join(unknown[:50]))
    by_cat: Dict[str, int] = {}
    for _, c in untraded:
        by_cat[c] = by_cat.get(c, 0) + 1
    print("[prune] untraded series by category: %s" % ", ".join("%s=%d" % kv for kv in sorted(by_cat.items())))

    stats = table_stats(cur)
    untraded_names = [s for s, _ in untraded]
    rebuild = args.rebuild_markets and any(t == "markets" for t, _, _ in tables)
    for table, col, _batch in tables:
        st = stats.get(table, {"rows": 0, "bytes": 0, "free": 0})
        n = sum(count_rows(cur, table, col, s) for s in untraded_names)
        per_row = st["bytes"] / st["rows"] if st["rows"] else 0
        print("[prune] %-15s untraded rows=%12d  ~%.1f GB of %.1f GB (table ~%d rows, %.1f GB free inside)"
              % (table, n, n * per_row / 1e9, st["bytes"] / 1e9, st["rows"], st["free"] / 1e9), flush=True)

    if not args.apply:
        print("[prune] dry run; nothing deleted. Re-run with --apply.")
        return 0

    for table, col, batch in tables:
        if table == "markets" and rebuild:
            keep = set(ours) - set(untraded_names)
            rebuild_markets(conn, keep, args.drop_old)
            continue
        done = 0
        for s in untraded_names:
            n, finished = delete_series(cur, table, col, s, batch, args.pause, deadline)
            done += n
            if not finished:
                print("[prune] %s: stopped at --stop-at after %d rows; re-run to resume" % (table, done), flush=True)
                return 2
        print("[prune] %s: deleted %d rows" % (table, done), flush=True)
    after = table_stats(cur)
    for table, _, _ in tables:
        a = after.get(table) or after.get("markets__untraded_old")
        if a:
            print("[prune] after: %-15s %.1f GB, %.1f GB reusable inside the file (not returned to RDS)"
                  % (table, a["bytes"] / 1e9, a["free"] / 1e9))
    return 0


if __name__ == "__main__":
    sys.exit(main())
