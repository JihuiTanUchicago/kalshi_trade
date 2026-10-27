"""Reads made from a user's positions alone, kept until those positions change.

The polled pages (the dashboard every 15s, the autopilot panel every 20s, the Deploy board every 10s)
re-summed a busy trader's whole history on every request: all-time realized P&L, each deployment's
totals and sparkline, the paper record toward the live check, the track record's trades. Each of those
fetches every position row (no index on app_positions covers them, and none is added to the table the
order path writes), 40-80ms apiece at 20k positions, and the answer only moves when a position does.

So each such read is kept per user against repo.positions_version: the user's position count, closed
count and highest id, read from idx_pos_user without fetching a row (~6ms at 23k positions). Every
write the app makes to a position moves it (a new row raises the count and the highest id; a close
moves a row from open to closed), and a closed row's money is never written again, so a kept answer
is served only while the rows it was read from are the rows there now: never stale, after the user's
own write or the engine's. The version is read before the kept read runs, so a write landing between
the two leaves the kept answer under the older version, and the next request reads it again.

Display only: the gates, the engine and the live checks keep reading the database themselves. A user
with no positions reads straight through (nothing to save). Values are shared between requests and
must not be mutated by callers.

The dashboard's paper cash is kept the same way against the paper ledger's own version
(paper_ledger_summary below): the ledger is summed again only after a row is added or it is reset.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Hashable, List, Optional, Tuple

from app import repository as repo
from app.trading import track_record as record

MAX_ENTRIES = 4096  # kept answers across users; cleared whole past this (a few per active user)
_KEPT: Dict[Tuple, Tuple[Tuple[int, int, int], Any]] = {}
_LOCK = threading.Lock()


def clear() -> None:
    with _LOCK:
        _KEPT.clear()
        _LEDGER.clear()


class BookMemo:
    """One request's view of the user's kept reads: the positions' version is read once, on first use."""

    def __init__(self, cur, uid: int, version: Optional[Tuple[int, int, int]] = None,
                 strategies: Optional[Dict[int, int]] = None):
        """`version` and `strategies`, when given, are repo.positions_version and repo.deployment_strategies
        as a read made before any kept read already returned them (the autopilot panel's pulse)."""
        self.cur, self.uid = cur, int(uid)
        self._version: Optional[Tuple[int, int, int]] = version
        self._strategies: Optional[Dict[int, int]] = strategies

    def version(self) -> Tuple[int, int, int]:
        if self._version is None:
            self._version = repo.positions_version(self.cur, self.uid)
        return self._version

    def deployment_strategies(self) -> Dict[int, int]:
        """{deployment_id: strategy_id} for every deployment of the user, read once per request."""
        if self._strategies is None:
            self._strategies = repo.deployment_strategies(self.cur, self.uid)
        return self._strategies

    def peek(self, name: str, key: Hashable = ()) -> Optional[Any]:
        """The answer kept for (name, key) at the current version, or None."""
        v = self.version()
        if not v[0]:
            return None
        hit = _KEPT.get((self.uid, name, key))
        return hit[1] if hit is not None and hit[0] == v else None

    def keep(self, name: str, key: Hashable, val: Any) -> Any:
        v = self.version()
        if v[0]:
            with _LOCK:
                if len(_KEPT) >= MAX_ENTRIES:
                    _KEPT.clear()
                _KEPT[(self.uid, name, key)] = (v, val)
        return val

    def get(self, name: str, key: Hashable, read: Callable[[], Any]) -> Any:
        """The kept answer for (name, key) while the positions are unchanged, else `read()` (kept)."""
        hit = self.peek(name, key)
        if hit is not None:
            return hit
        return self.keep(name, key, read())


_LEDGER: Dict[int, Tuple[Tuple[int, int], Dict]] = {}


def paper_ledger_summary(cur, uid: int) -> Dict:
    """repo.paper_ledger_summary (the paper cash, net deposits and last reset), kept per user against
    repo.paper_ledger_version (the ledger's rows and highest id, from its index alone): every write to
    the ledger moves that version, so a kept summary is served only while its rows are the rows there
    now. The version is read first, so a row added in between is summed on the next request. An empty
    ledger sums to nothing, so it is not read at all. A copy: the caller may change it."""
    v = repo.paper_ledger_version(cur, uid)
    if not v[0]:
        return {"balance": 0.0, "deposited": 0.0, "reset_at": None}
    hit = _LEDGER.get(int(uid))
    if hit is None or hit[0] != v:
        with _LOCK:
            if len(_LEDGER) >= MAX_ENTRIES:
                _LEDGER.clear()
        hit = _LEDGER[int(uid)] = (v, repo.paper_ledger_summary(cur, uid))
    return dict(hit[1])


def realized_since(memo: BookMemo, modes: Tuple[str, ...], since: datetime, fills: bool = False):
    """repo.realized_pnl_by_mode (each book's realized P&L of the trades closed since `since`), kept: a
    closed row's pnl and closed_at are never written again, so the sum moves only with a position (or a
    new `since`, part of the key). No position, nothing realized: no read. With `fills`, ({mode: realized},
    {mode: contract fills}) from the same read, for the paper after-slippage estimate (display only)."""
    if not memo.version()[0]:
        none = {m: 0.0 for m in modes}
        return (none, {m: 0 for m in modes}) if fills else none
    if fills:
        pnl, taker = memo.get("realized_since_fills", (tuple(modes), since),
                              lambda: repo.realized_pnl_by_mode(memo.cur, memo.uid, tuple(modes), since, fills=True))
        return dict(pnl), dict(taker)
    return dict(memo.get("realized_since", (tuple(modes), since),
                         lambda: repo.realized_pnl_by_mode(memo.cur, memo.uid, tuple(modes), since)))


def open_count(memo: BookMemo, mode: str) -> int:
    """repo.user_open_exposure(mode)["n"] (the user's open positions in one book), kept: a position opens
    as a new row and closes from open to closed, both of which move the version."""
    if not memo.version()[0]:
        return 0
    return memo.get("open_n", mode, lambda: int(repo.user_open_exposure(memo.cur, memo.uid, mode)["n"]))


def closed_totals(memo: BookMemo, deployment_ids: List[int]) -> Dict[int, Tuple[int, Any]]:
    """repo.deployment_closed_totals for the listed deployments (their own closed positions), kept."""
    ids = tuple(sorted({int(i) for i in deployment_ids}))
    if not ids or not memo.version()[0]:
        return {}
    return memo.get("closed_totals", ids, lambda: repo.deployment_closed_totals(memo.cur, list(ids)))


def realistic_paper_closed(memo: BookMemo, deployment_ids: List[int]) -> Dict[int, int]:
    """repo.realistic_paper_closed for the listed deployments (their own closed positions), kept."""
    ids = tuple(sorted({int(i) for i in deployment_ids}))
    if not ids:
        return {}
    return memo.get("realistic_paper_closed", ids, lambda: repo.realistic_paper_closed(memo.cur, list(ids)))


def removed_deployments(memo: BookMemo, strategy_id: Optional[int] = None) -> List[Dict]:
    """repo.removed_deployments (the deployments alone, read every time: one is removed without any
    position changing), each with its closed trades and realized P&L from closed_totals, kept for that
    set of deployments while the positions are unchanged (a closed row's money is never rewritten)."""
    rows = repo.removed_deployments(memo.cur, memo.uid, strategy_id)
    totals = closed_totals(memo, [r["id"] for r in rows])
    for r in rows:
        n, pnl = totals.get(int(r["id"]), (0, 0))
        r["closed_trades"], r["realized_pnl"] = int(n), pnl
    return rows


def closed_book_totals(memo: BookMemo, day: datetime, visit: Optional[datetime] = None, split: bool = False,
                       fills: bool = False):
    """repo.closed_book_totals (every book's realized P&L and closed-trade count, with `split` each
    deployment's since-visit share, and with `fills` each book's contract fills), kept."""
    if fills:
        return memo.get("book_totals_fills", (day, visit, split),
                        lambda: repo.closed_book_totals(memo.cur, memo.uid, day, visit, split=split, fills=True))
    if split:
        return memo.get("book_totals_split", (day, visit),
                        lambda: repo.closed_book_totals(memo.cur, memo.uid, day, visit, split=True))
    return memo.get("book_totals", (day, visit), lambda: repo.closed_book_totals(memo.cur, memo.uid, day, visit))


def deployment_curves(memo: BookMemo, deployment_ids: List[int]) -> Dict[int, List[List]]:
    """repo.deployment_curves for the listed deployments (a curve reads only its deployment's positions), kept."""
    ids = tuple(sorted({int(i) for i in deployment_ids}))
    return memo.get("curves", ids, lambda: repo.deployment_curves(memo.cur, memo.uid, deployment_ids=list(ids)))


def deployments_for_display(memo: BookMemo, strategy_id: Optional[int] = None) -> List[Dict]:
    """repo.list_deployments_for_display: the same rows, totals and order. While the positions are
    unchanged and the same deployments are listed, the deployments are read without their positions
    (repo.deployment_rows_for_display) and given the totals the last full read summed for them; a
    deployment's totals come from its own positions only. Otherwise the full read runs and its totals
    are kept."""
    key = None if strategy_id is None else int(strategy_id)
    kept = memo.peek("dep_totals", key)
    if kept is not None:
        rows = repo.deployment_rows_for_display(memo.cur, memo.uid, strategy_id=key)
        if {r["id"] for r in rows} == set(kept):
            for r in rows:
                r.update(zip(repo.DISPLAY_TOTALS, kept[r["id"]]))
            return [repo._strategy_row(r) for r in rows]
    deps = repo.list_deployments_for_display(memo.cur, memo.uid, strategy_id=key)
    if memo.version()[0]:
        memo.keep("dep_totals", key, {d["id"]: tuple(d[k] for k in repo.DISPLAY_TOTALS) for d in deps})
    return deps


def daily_pnl(memo: BookMemo, mode: str, days: int = 60) -> List[Dict]:
    """repo.daily_pnl(mode, days): closed P&L per UTC day from `days` ago, oldest first. The first
    day counts only what closed after the window's start, which moves every request, so it is read
    fresh (a day's rows through idx_pos_user); the whole days after it are kept."""
    start = repo.now_utc() - timedelta(days=days)
    if not memo.version()[0]:
        return repo.daily_pnl(memo.cur, memo.uid, mode, since=start)
    midnight = datetime(start.year, start.month, start.day) + timedelta(days=1)
    rest = memo.peek("daily", (mode, midnight))
    if rest is None:
        # One read of the whole window; its days from midnight on are the whole days kept.
        rows = repo.daily_pnl(memo.cur, memo.uid, mode, since=start)
        memo.keep("daily", (mode, midnight), [r for r in rows if r["d"] >= midnight.date()])
        return rows
    first = repo.realized_pnl_between(memo.cur, memo.uid, mode, start, midnight)
    return ([first] if first else []) + list(rest)


def _strategy_key(memo: BookMemo, strategy_ids: List[int]) -> Tuple:
    """The strategies and every deployment counted toward them. These reads group positions by their
    deployment's strategy, and an adjustment re-points a deployment at a new strategy row without
    touching a position, so the deployments are part of the key (one small read of the user's
    deployments, stopped ones included)."""
    ids = tuple(sorted({int(s) for s in strategy_ids}))
    if not memo.version()[0]:
        return ids, ()
    deps = memo.deployment_strategies()
    return ids, tuple(sorted((d, s) for d, s in deps.items() if s in ids))


def paper_progress(memo: BookMemo, strategy_ids: List[int], key: Optional[Tuple] = None) -> Dict[int, Tuple[int, float]]:
    """repo.paper_progress (closed realistic paper round trips and their P&L per strategy), kept.
    `key` is _strategy_key's answer when the caller already has it."""
    key = key or _strategy_key(memo, strategy_ids)
    return memo.get("paper_progress", key, lambda: repo.paper_progress(memo.cur, memo.uid, list(key[0])))


def paper_event_counts(memo: BookMemo, strategy_ids: List[int], key: Optional[Tuple] = None) -> Dict[int, int]:
    """repo.paper_event_counts (separate events among each strategy's closed paper trades), kept."""
    key = key or _strategy_key(memo, strategy_ids)
    return memo.get("paper_events", key, lambda: repo.paper_event_counts(memo.cur, memo.uid, list(key[0])))


def paper_round_trips_by_strategy(memo: BookMemo, strategy_ids: List[int]) -> Dict[int, List[Dict]]:
    """repo.paper_round_trips_by_strategy (each strategy's closed realistic paper round trips, for the
    Deploy board's road to live), kept as paper_progress is."""
    key = _strategy_key(memo, strategy_ids)
    return memo.get("paper_trips", key, lambda: repo.paper_round_trips_by_strategy(memo.cur, memo.uid, list(key[0])))


def book_trade_stats(memo: BookMemo, strategy_ids: List[int]) -> Dict[int, Dict[str, Dict]]:
    """repo.book_trade_stats (each strategy's per-book trade sums, for the backtest comparison), kept as
    paper_progress is: it too groups the positions by their deployment's strategy."""
    key = _strategy_key(memo, strategy_ids)
    return memo.get("book_stats", key, lambda: repo.book_trade_stats(memo.cur, memo.uid, list(key[0])))


def paper_readouts(memo: BookMemo, strategy_ids: List[int]) -> Tuple[Dict[int, Tuple[int, float]], Dict[int, int]]:
    """(paper_progress, paper_event_counts) for the autopilot panel, sharing one read of the deployments."""
    key = _strategy_key(memo, strategy_ids)
    return paper_progress(memo, strategy_ids, key), paper_event_counts(memo, strategy_ids, key)


def track_record(cur, uid: int, now: Optional[datetime] = None) -> Dict:
    """The track record payload (app.trading.track_record.build over repo.track_record_rows), with its slow
    parts kept: the trades grouped from the positions (kept while the positions are unchanged) and the
    buckets made from them (track_record.prepare, kept while those trades and their deployments'
    strategy, status and title are unchanged). The deployments are read fresh every time, so a stop, a
    pause or a removed strategy shows at once; the figures that move with the clock are always
    computed now (track_record.finish)."""
    memo = BookMemo(cur, uid)
    trades = memo.get("track_record_trades", (), lambda: repo.track_record_trades(cur, uid))
    deps = repo.track_record_deployments(cur, trades) if trades else {}
    shape = tuple(sorted((i, d["strategy_id"], d["status"], d["title"], d["market"]) for i, d in deps.items()))
    prepared = memo.get("track_record_buckets", shape,
                        lambda: record.prepare(repo.track_record_join(trades, deps, seconds=True) if trades else []))
    return record.finish(prepared, now)
