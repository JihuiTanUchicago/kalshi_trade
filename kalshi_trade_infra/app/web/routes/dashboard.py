"""Dashboard routes: the home dashboard (book, curves, agents, since-your-last-visit), the track
record and the data freshness readout. Moved verbatim from app.server, which re-imports every name
for its route table."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app import repository as repo
from app.adapters.stripe import billing
from app.services import book_memo, page_poll
from app.web.caches import _TRACK_RECORD, _shared
from app.web.http import Ctx
from app.web.routes.deployments import _paper_strategy_ids
from app.web.routes.strategies import _with_marks, _with_why
from app.web.views import (
    _demo_health,
    _demo_key_back,
    _deployment_out,
    _live_balance,
    _open_book,
    _paper_books,
    _paper_equity,
    _silent_before,
    _start_of_day_utc,
    credit_usd,
)
from trading_core.domain.money import cents, exact


def _mode_bucket(cur, uid: int, mode: str, open_pos: List[Dict], deps: List[Dict], day,
                 realized: Optional[Tuple[float, float]] = None,
                 closed: Optional[Dict[str, int]] = None) -> Dict:
    """Money in one deployment-mode bucket (paper | demo | live), from that mode's own
    positions and deployments only — so the three buckets never double-count each other.
    `realized` is (all time, since `day`) when the caller read every book's at once.
    `closed` is the closed-trade counts of repo.closed_book_totals (read once for all three)."""
    if realized is None:
        realized = (repo.realized_pnl(cur, uid, mode), repo.realized_pnl(cur, uid, mode, day))
    total, today = realized
    return {
        "closed_trades": int((closed or {}).get(mode, 0)),  # > 0: the dashboard offers /api/trades.csv
        **_open_book(open_pos, mode),
        "running": sum(1 for d in deps if d["mode"] == mode and d["status"] == "running"),
        "realized_pnl": cents(total),
        "today_pnl": cents(today),
    }


def dashboard(ctx: Ctx):
    cur = ctx.cur
    day = _start_of_day_utc()
    open_pos = _with_marks(repo.user_positions(cur, ctx.uid, "open"))
    # Aggregate live mark-to-market unrealized P&L per deployment (from the marks just stamped), so
    # the Deployed table can show each strategy's current open P&L, not only its realized P&L.
    unreal_by_dep: Dict[int, float] = {}
    for p in open_pos:
        u = p.get("unrealized")
        if u is not None and p.get("deployment_id") is not None:
            unreal_by_dep[p["deployment_id"]] = round(unreal_by_dep.get(p["deployment_id"], 0.0) + u, 2)
    # The reads summed from the positions alone are kept until the positions change (services.book_memo).
    memo = book_memo.BookMemo(cur, ctx.uid)
    deps = book_memo.deployments_for_display(memo)
    # Curves only for the deployments the Deployed table shows (a stopped one's history is not drawn).
    curves = book_memo.deployment_curves(memo, [d["id"] for d in deps])
    ledger = book_memo.paper_ledger_summary(cur, ctx.uid)  # balance, deposits and reset: one read, kept until the ledger moves
    balance, deposited = ledger["balance"], ledger["deposited"]
    visit, first = _visit_since(ctx.query.get("since"))
    # Every book's realized P&L and closed-trade count (today and since the last visit), in one read.
    realized, closed, recent, by_dep = book_memo.closed_book_totals(memo, day, visit, split=True)
    _BOOK_SHAPE[ctx.uid] = _book_shape(closed, len(open_pos))  # the track record's cache checks it
    # Three mode buckets, each self-contained (real / sandbox / simulation). Paper + demo both
    # carry an app-controlled cash layer on top of the shared fields; live carries the real
    # Kalshi balance (money we never hold).
    paper = _mode_bucket(cur, ctx.uid, "paper", open_pos, deps, day, realized["paper"], closed)
    equity = _paper_equity(balance, open_pos)
    paper.update(
        cash=cents(balance),
        equity=cents(equity),
        deposited=cents(deposited),
        total_pnl=cents(equity - exact(deposited)),
        roi=round(float(equity - exact(deposited)) / deposited, 4) if deposited > 0 else None,
        daily=book_memo.daily_pnl(memo, "paper"),
        # total_pnl restarts at a reset (the ledger is wiped), so its label says "since reset", not
        # "all time", while the track record still counts every closed trade.
        reset_at=ledger["reset_at"],
    )
    # Demo: real fills applied to the capital WE set. Equity = capital + realized-since-reload,
    # and the displayed realized P&L is net of the reload baseline (so a reload reads as $X flat).
    demo = _mode_bucket(cur, ctx.uid, "demo", open_pos, deps, day, realized["demo"], closed)
    de = repo.demo_equity(cur, ctx.uid, realized=realized["demo"][0])
    demo.update(capital=de["capital"], equity=de["equity"], realized_pnl=de["realized"],
                total_pnl=de["realized"], roi=de["roi"], before_reload=de["before_reload"],
                health=_demo_health(cur, ctx.uid, deps))  # capital and P&L look fine while Kalshi refuses every order
    live = _mode_bucket(cur, ctx.uid, "live", open_pos, deps, day, realized["live"], closed)
    live.update(_live_balance(cur, ctx.uid))
    paper_sids = _paper_strategy_ids(deps)
    key_back = _demo_key_back(cur, ctx.uid, deps)
    # The page polls every 15s with its last answer's version (?v=): an unchanged answer is sent as
    # "same" with only the marks and data ages, which move every tick (services.page_poll).
    return page_poll.answer({
        "paper": paper,
        "demo": demo,
        "live": live,
        "open_positions": _with_why(open_pos, deps),
        "recent_closed": _with_why(repo.user_positions(cur, ctx.uid, "closed", 12), deps),
        # Live book-vs-Kalshi reconciliation: empty list = book matches the exchange; any rows are
        # open discrepancies the reconciler flagged (shown as a trust badge on the Live bucket).
        "reconcile": repo.open_reconcile_rows(cur, ctx.uid),
        "deployments": [_deployment_out(d, curves.get(d["id"], []), unreal_by_dep.get(d["id"]), paper_sids, key_back,
                                        _paper_books(deps)) for d in deps],
        "agents": repo.active_run_counts(cur, ctx.uid, silent_before=_silent_before()),
        "freshness": _freshness(cur),
        "since": _since_visit(cur, ctx.uid, visit, first, recent, by_dep, {d["id"] for d in deps}),
    }, ctx.query.get("v"))


SINCE_MAX = timedelta(days=7)    # an older last visit reads as the last 7 days


SINCE_FIRST = timedelta(hours=24)  # no last visit known (first visit on this device): the last 24h


def _visit_since(raw) -> Tuple[datetime, bool]:
    """The start of "since your last visit" from the dashboard's ?since= (epoch seconds, kept in a
    cookie by the page), clamped to the last 7 days. Missing or unreadable: the last 24 hours, and
    `first` is True so the strip says "Last 24 hours" instead."""
    now = repo.now_utc()
    try:
        at = datetime.fromtimestamp(int(str(raw)), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return now - SINCE_FIRST, True
    return min(max(at, now - SINCE_MAX), now), False


def _since_visit(cur, uid: int, visit: datetime, first: bool, recent: Dict,
                 by_dep: Optional[Dict[Tuple[str, int], Tuple[float, int]]] = None, listed: Optional[set] = None) -> Dict:
    """The dashboard's "since your last visit" strip: each book's realized P&L and closed trades
    since then (from the books' one pass; books are never added together), the strategies that
    passed, the autopilot's own changes and the research sessions started. Two reads. Credits spent
    (real money) ride apart from the books, and only while payments are on: with them off nothing
    is billed. `milestones` are the paper forward-gate passes and live-ready strategies since then.
    `by_deployment` splits each book's figure by the deployment that traded it ({mode: [{deployment_id,
    pnl, trades}]}, best first), the same rows, so a net loss names the strategy that made it. A row
    whose deployment the page doesn't list (`listed`: it was removed) says whose it was itself."""
    act = repo.activity_since(cur, uid, visit)
    return {"at": visit, "first": first,
            "books": {m: {"pnl": cents(pnl), "trades": n} for m, (pnl, n) in recent.items()},
            "passed": repo.passed_since(cur, uid, visit),
            "autopilot": act["autopilot"], "runs": act["runs"], "own_sessions": bool(act.get("own_sessions")),
            "spent": {**{k: credit_usd(v) for k, v in act["spent"].items()}, "card_charged": bool(act.get("card_charged", True))}
            if billing.configured() and act.get("spent") else None,
            "milestones": act.get("milestones") or {"passed": [], "live_ready": []},
            "by_deployment": _since_by_deployment(by_dep or {}, _removed_names(cur, uid, by_dep or {}, listed))}


def _removed_names(cur, uid: int, by_dep: Dict[Tuple[str, int], Tuple[float, int]], listed: Optional[set]) -> Dict[int, Dict]:
    """{deployment id: {strategy_id, title}} for the since-visit rows of removed deployments (not in
    `listed`), read only when there is one; the title is None once the strategy itself was deleted.
    The page named every such row "a removed strategy", one that still exists included."""
    if listed is None or all(dep_id in listed for _, dep_id in by_dep):
        return {}
    return {int(r["id"]): {"strategy_id": r["strategy_id"], "title": r["title"]} for r in repo.removed_deployments(cur, uid)}


def _since_by_deployment(by_dep: Dict[Tuple[str, int], Tuple[float, int]],
                         removed: Optional[Dict[int, Dict]] = None) -> Dict[str, List[Dict]]:
    """{mode: [{deployment_id, pnl, trades}]} for each book, best first; a book is never mixed with another.
    A removed deployment's row also carries `removed` and its strategy (`strategy_id`, `title`)."""
    out: Dict[str, List[Dict]] = {}
    for (mode, dep_id), (pnl, n) in by_dep.items():
        row = {"deployment_id": dep_id, "pnl": cents(pnl), "trades": n}
        if dep_id in (removed or {}):
            row.update(removed=True, **removed[dep_id])
        out.setdefault(mode, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (-r["pnl"], r["deployment_id"]))
    return out


TRACK_RECORD_TTL = 60.0  # seconds; the record moves only when a trade closes


# A book with fewer trades than this is read fresh on every request: its grouped read is a few rows
# through idx_pos_user, and a new user's first trade showed up only after the cached empty record
# expired (up to a minute after the board above it showed the trade).
TRACK_RECORD_CACHE_MIN_TRADES = 200


# {user id: the book's shape at the dashboard's last read} (_book_shape): one closed-trade count per
# mode and the open count. A busy book's cached record is rebuilt once the dashboard has seen a trade
# open or close that the record predates, so the two never disagree for the rest of the minute.
_BOOK_SHAPE: Dict[int, Tuple] = {}


def _book_shape(closed: Dict[str, int], open_count: int) -> Tuple:
    return tuple(sorted(closed.items())), int(open_count)


def get_track_record(ctx: Ctx):
    """The fund-grade track record: realized results per money bucket (live / demo / paper), from
    the user's own closed trades. A busy book is cached per user for TRACK_RECORD_TTL (never served
    stale past it, nor past a trade the dashboard has seen open or close, nor past the user's own
    deploy or stop), so a page left open costs one grouped scan a minute at most; a small one is
    read every time."""
    hit, shape = _TRACK_RECORD.get(ctx.uid), _BOOK_SHAPE.get(ctx.uid)
    if (hit and hit[2] >= TRACK_RECORD_CACHE_MIN_TRADES and time.time() - hit[0] < TRACK_RECORD_TTL
            and hit[3] == shape):
        return hit[1]
    val = book_memo.track_record(ctx.cur, ctx.uid)  # the trades and their buckets kept until the book changes
    n = sum(int(m.get("trades") or 0) for m in (val.get("modes") or {}).values())
    _TRACK_RECORD[ctx.uid] = (time.time(), val, n, shape)
    return val


def _freshness(cur) -> Dict:
    raw = _shared("history_freshness", 60, lambda c: repo.history_freshness(c), cur)
    now = int(datetime.now(timezone.utc).timestamp())
    out = {k: (now - int(v) if v else None) for k, v in raw.items()}
    # Engine liveness: seconds since the deployment engine's last tick (None = never/dead). A stalled
    # engine holding real positions is the worst silent failure, so it rides the same payload.
    try:
        out["engine"] = repo.engine_last_tick_age_seconds(cur)
    except Exception:
        out["engine"] = None
    return out
