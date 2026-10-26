"""Paper trading for agent-written code strategies, inside the research sandbox.

Todd's decision (2026-10-25, "Paper only, in the sandbox"): a code strategy (spec["code"], the
signals(window) Python research writes for multi-feature models) never runs in the paper or live
engine, so a near miss like the pooled daily last-4h idea (#16128) could never collect the forward
sample the paper forward gate judges. This replays each such paper deployment over fresh data, one
UTC day at a time, after that day's contracts settle: the same sandbox, frozen params, next-bar
fill model, fees and settlement the gatekeeper scored it with, on data that did not exist when it
was pre-registered. Live stays blocked for code strategies (agent.act refuses them).

Integrity:
  * Forward only. Nothing before the deployment was created is traded, and each day is booked once
    (app_deployments.last_decision_ts is the replay cursor, claimed in the booking transaction).
  * The day's window is fixed by the clock, never by results. Trades whose contract has not
    settled hold the day back (up to MAX_WAIT_S); after that they are left out, win or lose.
  * Look-ahead audit. signals() is handed the whole day at once, so a strategy could read frames
    after the one it decides on. Before booking, the picks at AUDIT_CUTS frames are recomputed on a
    window cut at that frame; any difference stops the deployment instead of booking the day.

Booked trips are closed paper rows with order_ref "sim:replay:<dep>:<ticker>:<entry ts>", so the
tournament and the paper forward gate count them as realistic simulated fills.

Runs hourly on the web box (scripts/systemd/tau-code-paper.timer): python -m app.services.code_paper
Env: APP_CODE_PAPER=0 turns it off (on by default; probation only places code strategies when on).
"""
from __future__ import annotations

import os
import random
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.trading import backtest
from app.research import partitions
from app import repository as repo
from app.trading import spec as specmod
from app.trading.markets import MARKETS
from data_pipeline.kalshi_fees import taker_fee_dollars

ENABLED = os.getenv("APP_CODE_PAPER", "1") == "1"
REF_PREFIX = "sim:replay:"
DAY = 86400
WARMUP_S = DAY  # history signals() sees before the day, as a long fold would have had
OPEN_LOOKBACK_S = 2 * DAY  # contracts opened this long before the day can still trade in it
SETTLE_GRACE_S = 2 * 3600  # a day is replayed this long after it ends
MAX_WAIT_S = 2 * DAY  # stop holding a day back for an unsettled contract after this long (< the backfill window)
MAX_BACKFILL_DAYS = 3  # after an outage, older days are skipped rather than replayed in a burst
AUDIT_CUTS = 2


def _ts(dt) -> int:
    if isinstance(dt, datetime):
        return int((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp())
    return int(dt or 0)


def _naive(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


def next_day(dep: Dict, now_ts: int) -> Optional[Tuple[int, int]]:
    """The [start, end) window this deployment replays next, or None while today's isn't over.
    It starts where the last one ended (or when the deployment was created) and ends at the
    following UTC midnight."""
    oldest = now_ts - now_ts % DAY - MAX_BACKFILL_DAYS * DAY
    start = max(int(dep.get("last_decision_ts") or 0), _ts(dep["created_at"]), oldest)
    end = start - start % DAY + DAY
    return (start, end) if now_ts >= end + SETTLE_GRACE_S else None


def load_day(spec: Dict, start: int, end: int, now_ts: int) -> backtest.Dataset:
    """Every involved market's contracts that could trade in [start, end), with the warm-up frames,
    merged the way the gatekeeper merges a pooled stream."""
    markets = specmod.involved_markets(spec)
    days = max(MARKETS[m].history_days for m in markets)
    days = max(days, (now_ts - (start - OPEN_LOOKBACK_S - WARMUP_S)) // DAY + 2)
    dses = [partitions.window_dataset(m, start - OPEN_LOOKBACK_S - WARMUP_S, end, days) for m in markets]
    return dses[0] if len(dses) == 1 else backtest.merge_datasets(dses, key="+".join(markets))


def peeked_at(spec: Dict, ds: backtest.Dataset, start: int, end: int, seed: int) -> Optional[int]:
    """The first audited frame whose picks change when the window is cut right after it (the code
    read later frames), or None. Audits frames that have picks first, since those trade."""
    warm = start - WARMUP_S
    full = backtest._code_book(spec, ds, start, end, warm)
    frames = [ts for ts, _ in ds.frames if start <= ts < end]
    picked = [ts for ts in frames if full.get(ts)]
    pool = picked or frames
    cuts = sorted(random.Random(seed).sample(pool, min(AUDIT_CUTS, len(pool))))
    for ts in cuts:
        if backtest._code_book(spec, ds, start, ts + 1, warm).get(ts) != full.get(ts):
            return ts
    return None


def _book(tx, dep: Dict, trades: List[backtest.Trade], ds: backtest.Dataset, done: set) -> int:
    n = 0
    for t in trades:
        ref = "%s%d:%s:%d" % (REF_PREFIX, dep["id"], t.ticker, t.entry_ts)
        if ref in done:
            continue
        entry_fee = min(t.fees, taker_fee_dollars(t.qty, t.entry_price))
        pid = repo.insert_closed_position(
            tx, dep["id"], dep["user_id"], "paper", t.ticker, t.side, t.qty, t.entry_price, entry_fee,
            t.exit_price, t.fees - entry_fee, t.pnl, t.reason, _naive(_close_ts(ds, t)), ref,
            opened_at=_naive(t.entry_ts), closed_at=_naive(t.exit_ts))
        repo.add_ledger(tx, dep["user_id"], "trade", t.pnl, "Paper replay: %d %s %s @ %.2f -> %.2f (%s)" % (
            t.qty, t.side.upper(), t.ticker, t.entry_price, t.exit_price, t.reason), pid)
        n += 1
    return n


def _close_ts(ds: backtest.Dataset, t: backtest.Trade) -> int:
    for _, snaps in ds.frames:
        for s in snaps:
            if s.contract.ticker == t.ticker:
                return _ts(s.contract.close_time)
    return t.exit_ts


def replay(conn, dep: Dict, now_ts: int) -> Optional[str]:
    """Replay this deployment's next due day. Returns a log line, or None when nothing was due."""
    win = next_day(dep, now_ts)
    if win is None:
        return None
    start, end = win
    spec = dep["spec"]
    ds = load_day(spec, start, end, now_ts)
    trades = backtest.simulate(spec, ds, start, end, warm_from=start - WARMUP_S)
    if trades:
        peek = peeked_at(spec, ds, start, end, seed=dep["id"] * 100003 + start // DAY)
        if peek is not None:
            why = ("Stopped: its code changes the decision at %s when later data is removed (it reads the "
                   "future), so its paper record would not be real." % _naive(peek).strftime("%Y-%m-%d %H:%M UTC"))
            with repo.transaction(conn) as tx:
                repo.set_deployment_status(tx, dep["user_id"], dep["id"], "stopped", why)
            return "dep %d: %s" % (dep["id"], why)
    unsettled = [t for t in trades if t.reason == "settled" and t.ticker not in ds.results]
    if unsettled and now_ts < end + MAX_WAIT_S:
        return "dep %d: %s held back, %d trade(s) not settled yet" % (dep["id"], _naive(start).date(), len(unsettled))
    trades = [t for t in trades if t not in unsettled]
    with repo.transaction(conn) as tx:
        if not repo.claim_decision(tx, dep["id"], end):
            return None  # another replay booked it, or the deployment stopped
        n = _book(tx, dep, trades, ds, repo.deployment_order_refs(tx, dep["id"], REF_PREFIX))
    return "dep %d: %s booked %d paper trade(s), net $%.2f%s" % (
        dep["id"], _naive(start).date(), n, sum(t.pnl for t in trades),
        ", %d unsettled left out" % len(unsettled) if unsettled else "")


def run(conn, now_ts: Optional[int] = None, max_days: int = MAX_BACKFILL_DAYS + 1) -> List[str]:
    """Replay every due day of every running code paper deployment, oldest day first."""
    if not ENABLED:
        return []
    now_ts = int(now_ts or time.time())
    with conn.cursor() as cur:
        deps = [d for d in repo.running_code_paper_deployments(cur) if specmod.is_code_spec(d["spec"])]
    lines = []
    for dep in deps:
        for _ in range(max_days):
            try:
                line = replay(conn, dep, now_ts)
            except Exception as e:  # one strategy's bad day must not stop the others
                line = "dep %d: replay failed: %r" % (dep["id"], e)
                lines.append(line)
                break
            if line is None:
                break
            lines.append(line)
            if "booked" not in line:
                break
            with conn.cursor() as cur:
                dep = next((d for d in repo.running_code_paper_deployments(cur) if d["id"] == dep["id"]), None)
            if dep is None:
                break
    return lines


def main() -> None:
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    try:
        for line in run(conn):
            print("[code_paper] %s" % line, flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
