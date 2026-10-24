"""Research RSI, part 4: when a crypto idea dies because data is MISSING (not because the market said
no), ask the data pipeline for that data, and re-test the idea once it exists.

    research run ──► an idea dropped as feature_unavailable / no_data (rsi.classify_drop), or the
    │                whole run failed loading data
    ├─► detect(): one app_data_requests row per (user, market, kind, need)
    │     kind history  settled contracts + candles   -> market_history syncs the market first
    │     kind micro    a 1-minute order-book feature -> feature_1m_collector adds the series
    │     kind ticks    per-second data               -> tick_recorder adds the series
    ├─► check(): is the data there now? (contracts in the research window / feature coverage)
    └─► requeue(): one new research session on the idea, for an autopilot user, under the same
                   caps any autopilot research obeys. At most once per request, so a data gap
                   can never loop on spend.

Only the crypto family for now (Todd, 2026-10-24: "if agent research fails because of missing data in
crypto, we should automatically launch data pipeline to store data"). A feature the proposer merely
BELIEVED missing (it is a core feature every frame carries) is not collectable: the playbook's
PIPELINE FACTS is where that lesson goes, so no request is made.

    python -m app.rsi_repair [--days 3]
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from app.markets import FEATURES, MARKETS, MICRO_FEATURES, TICK_FEATURES

DDL = [
    """
    CREATE TABLE IF NOT EXISTS app_data_requests (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      market VARCHAR(64) NOT NULL,
      series VARCHAR(64) NOT NULL,
      kind VARCHAR(16) NOT NULL,              -- history | micro | ticks
      need VARCHAR(64) NOT NULL DEFAULT '',   -- the feature, for micro/ticks; '' for history
      status VARCHAR(16) NOT NULL,            -- open | ready | requeued | expired
      baseline INT NOT NULL DEFAULT 0,        -- research-window contracts when asked
      source_run_id BIGINT NULL,
      idea_title VARCHAR(255) NULL,
      idea_why TEXT NULL,
      created_at DATETIME NOT NULL,
      ready_at DATETIME NULL,
      requeued_run_id BIGINT NULL,
      note VARCHAR(255) NULL,
      UNIQUE KEY uq_data_request (user_id, market, kind, need),
      INDEX idx_data_request_status (status, kind)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

FAMILIES = ("crypto",)
READY_MIN_CONTRACTS = 120      # research-window contracts before a history/ticks re-test is worth it
READY_GROWTH = 24              # ... and at least this many more than when the data was asked for
MICRO_READY_DAYS = 3           # days of a collected micro feature before re-testing on it
EXPIRE_DAYS = 21               # an open request that never fills is dropped
MAX_REQUEUES_PER_PASS = 2      # per user, on top of the autopilot caps
MAX_MICRO_SERIES = 12          # extra series the 1-minute collector may take on
MAX_TICK_SERIES = 6            # extra series the tick recorder may take on
_FEATURE_RX = re.compile(r"\b[a-z][a-z0-9_]{2,40}\b")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def tick_twin(market: str) -> Optional[str]:
    """The research market that replays `market`'s series from per-second data, if one exists."""
    m = MARKETS.get(market)
    if m is None:
        return None
    if m.source == "ticks":
        return market
    for k, t in MARKETS.items():
        if t.source == "ticks" and t.series == m.series:
            return k
    return None


def classify_need(market: str, tag: str, why: str) -> Optional[Tuple[str, str, str]]:
    """(kind, need, market to re-test on) for one pipeline death, or None when nothing can be
    collected for it (a core feature every frame already has, or an unknown market)."""
    m = MARKETS.get(market)
    if m is None:
        return None
    if tag == "no_data":
        return ("ticks" if m.source == "ticks" else "history"), "", market
    if tag != "feature_unavailable":
        return None
    named = [w for w in _FEATURE_RX.findall((why or "").lower()) if w in FEATURES]
    for name in named:
        if name in TICK_FEATURES:
            twin = tick_twin(market)
            return "ticks", name, twin or market
        if name in MICRO_FEATURES:
            return "micro", name, market
    if re.search(r"per[- ]second|tick[- ]level|sub[- ]minute|order[- ]book depth|level ?2", why or "", re.I):
        return "ticks", "", tick_twin(market) or market
    return None


def _pipeline_deaths(cur, days: int) -> List[Dict]:
    """Dropped ideas and failed runs whose reason is missing data, for crypto markets."""
    from app import rsi
    since = _now() - timedelta(days=days)
    cur.execute("SELECT id, user_id, market, status, error FROM app_agent_runs WHERE kind='research' "
                "AND created_at >= %s AND market IS NOT NULL ORDER BY id", (since,))
    runs = [r for r in cur.fetchall() if rsi.family(r["market"]) in FAMILIES]
    out: List[Dict] = []
    for r in runs:
        if r["status"] == "failed" and r.get("error"):
            tag, kind = rsi.classify_drop(r["error"])
            if kind == "pipeline":
                out.append({"user_id": r["user_id"], "market": r["market"], "run_id": r["id"], "tag": tag,
                            "title": "", "why": str(r["error"])[:1000]})
    events = rsi.verdict_events(cur, [r["id"] for r in runs]) if runs else {}
    for r in runs:
        for e in events.get(r["id"], []):
            d = e.get("data") or {}
            if d.get("status") != "abandoned":
                continue
            tag, kind = rsi.classify_drop(d.get("why") or e.get("message"))
            if kind == "pipeline":
                out.append({"user_id": r["user_id"], "market": r["market"], "run_id": r["id"], "tag": tag,
                            "title": (d.get("title") or "")[:255], "why": (d.get("why") or e.get("message") or "")[:1000]})
    return out


def window_contracts(cur, market: str) -> int:
    """Settled contracts the market's research loader would see right now."""
    from app import research_repository as rr
    m = MARKETS[market]
    return len(rr.partition_contracts(cur, m, _now() - timedelta(days=m.history_days)))


def micro_days(cur, series: str, feature: str) -> float:
    """Days (distinct hours / 24) in the last two weeks with the feature collected for the series."""
    col = MICRO_FEATURES[feature][0]
    try:
        cur.execute("SELECT COUNT(DISTINCT DATE_FORMAT(f.snapshot_minute_utc, '%%Y-%%m-%%d %%H')) AS h "
                    "FROM model_features_1m f WHERE f.market_ticker LIKE %s AND f." + col + " IS NOT NULL "
                    "AND f.snapshot_minute_utc >= %s", (series + "-%", _now() - timedelta(days=14)))
        return float((cur.fetchone() or {}).get("h") or 0) / 24.0
    except Exception:  # noqa: BLE001 - no table / no column yet means no coverage
        return 0.0


def is_ready(cur, req: Dict) -> bool:
    if req["kind"] == "micro":
        return micro_days(cur, req["series"], req["need"]) >= MICRO_READY_DAYS
    n = window_contracts(cur, req["market"])
    return n >= READY_MIN_CONTRACTS and n >= int(req.get("baseline") or 0) + READY_GROWTH


def record(cur, death: Dict) -> Optional[int]:
    """Open (or leave alone) the request for one pipeline death. None when nothing is collectable."""
    need = classify_need(death["market"], death["tag"], death["why"])
    if need is None:
        return None
    kind, feature, market = need
    cur.execute("SELECT id FROM app_data_requests WHERE user_id=%s AND market=%s AND kind=%s AND need=%s",
                (death["user_id"], market, kind, feature))
    if cur.fetchone():
        return None          # asked already (whatever its state): a request is made, and re-tested, once
    m = MARKETS[market]
    baseline = 0 if kind == "micro" else window_contracts(cur, market)
    cur.execute(
        "INSERT IGNORE INTO app_data_requests (user_id, market, series, kind, need, status, baseline, source_run_id, "
        "idea_title, idea_why, created_at) VALUES (%s,%s,%s,%s,%s,'open',%s,%s,%s,%s,%s)",
        (death["user_id"], market, m.series, kind, feature, baseline, death["run_id"], death["title"][:255] or None,
         death["why"], _now()))
    return cur.lastrowid or None


def wanted(cur, kind: str) -> List[Dict]:
    """Open requests of one kind, oldest first: what a collector should add to its work."""
    try:
        cur.execute("SELECT market, series, need, MIN(created_at) AS since FROM app_data_requests "
                    "WHERE status='open' AND kind=%s GROUP BY market, series, need ORDER BY since", (kind,))
        return list(cur.fetchall())
    except Exception:  # noqa: BLE001 - before the first schema run the table does not exist
        return []


def wanted_series(cur, kind: str, limit: int) -> List[str]:
    """Distinct series with an open request of this kind, oldest request first, at most `limit`."""
    out: List[str] = []
    for r in wanted(cur, kind):
        if r["series"] not in out:
            out.append(r["series"])
    return out[:limit]


def requeue_block(cur, user_id: int, market: str) -> Optional[str]:
    """Why a re-test may not start now ('' / None = it may). The same caps autopilot research obeys."""
    from app import agent
    from app import repository as repo
    user = repo.get_user(cur, user_id) or {}
    if not user.get("autopilot"):
        return "autopilot is off"
    why = agent.research_unavailable_reason(market)
    if why:
        return why
    if repo.count_runs(cur, user_id, "research", active_only=True) >= agent.MAX_ACTIVE_RESEARCH:
        return "research slots are full"
    if agent.MAX_RESEARCH_PER_DAY and repo.count_runs(
            cur, user_id, "research", since=repo.now_utc() - timedelta(days=1)) >= agent.MAX_RESEARCH_PER_DAY:
        return "daily research limit reached"
    if agent.MAX_GLOBAL_ACTIVE_RESEARCH and repo.count_active_research(cur) >= agent.MAX_GLOBAL_ACTIVE_RESEARCH:
        return "the research queue is full"
    return None


def requeue_prompt(req: Dict) -> str:
    what = {"history": "more settled history for this market",
            "micro": "the %s feature" % req["need"],
            "ticks": "per-second data" + (" (%s)" % req["need"] if req["need"] else "")}[req["kind"]]
    idea = req.get("idea_title") or "the idea"
    return ("Re-test %s now that %s has been collected. It was dropped earlier because: %s. Build it on the "
            "data that now exists; if it still fails, say what is missing." % (idea, what, (req.get("idea_why") or "")[:500]))[:1000]


def requeue(cur, req: Dict) -> Optional[int]:
    from app import repository as repo
    user = repo.get_user(cur, req["user_id"]) or {}
    run_id = repo.create_run(cur, req["user_id"], "research", req["market"], None, requeue_prompt(req), brief=True,
                             model=user.get("autopilot_model"))
    cur.execute("UPDATE app_data_requests SET status='requeued', requeued_run_id=%s WHERE id=%s", (run_id, req["id"]))
    return run_id


def run(conn, days: int = 3) -> Dict[str, int]:
    """One pass: record new requests, mark filled ones ready, re-test ready ones, expire stale ones."""
    cur = conn.cursor()
    stats = {"deaths": 0, "opened": 0, "ready": 0, "requeued": 0, "expired": 0}
    for d in _pipeline_deaths(cur, days):
        stats["deaths"] += 1
        if record(cur, d):
            stats["opened"] += 1
    conn.commit()
    cur.execute("SELECT * FROM app_data_requests WHERE status IN ('open','ready') ORDER BY id")
    per_user: Dict[int, int] = {}
    for req in cur.fetchall():
        if req["status"] == "open":
            if req["created_at"] < _now() - timedelta(days=EXPIRE_DAYS):
                cur.execute("UPDATE app_data_requests SET status='expired' WHERE id=%s", (req["id"],))
                stats["expired"] += 1
                continue
            if req["market"] not in MARKETS or not is_ready(cur, req):
                continue
            cur.execute("UPDATE app_data_requests SET status='ready', ready_at=%s WHERE id=%s", (_now(), req["id"]))
            stats["ready"] += 1
        if per_user.get(req["user_id"], 0) >= MAX_REQUEUES_PER_PASS:
            continue
        block = requeue_block(cur, req["user_id"], req["market"])
        if block:
            cur.execute("UPDATE app_data_requests SET note=%s WHERE id=%s", (("waiting: " + block)[:255], req["id"]))
            continue
        requeue(cur, req)
        per_user[req["user_id"]] = per_user.get(req["user_id"], 0) + 1
        stats["requeued"] += 1
    conn.commit()
    return stats


def summary(cur, user_id: int, limit: int = 20) -> List[Dict]:
    """The user's data requests, newest first, for the research panel."""
    try:
        cur.execute("SELECT id, market, kind, need, status, idea_title, created_at, ready_at, requeued_run_id, note "
                    "FROM app_data_requests WHERE user_id=%s ORDER BY id DESC LIMIT %s", (user_id, int(limit)))
        return list(cur.fetchall())
    except Exception:  # noqa: BLE001 - table not created yet
        return []


def main(argv: Optional[Iterable[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=3)
    a = ap.parse_args(argv)
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    try:
        print("[rsi_repair] %s" % run(conn, a.days), flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
