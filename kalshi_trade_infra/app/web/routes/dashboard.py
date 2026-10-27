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
from app.trading import engine
from app.web.caches import _TRACK_RECORD, _shared
from app.web.http import Ctx
from app.web.routes.deployments import _paper_strategy_ids
from app.web.routes.funds import kalshi_cash
from app.web.routes.strategies import _later_verdicts, _with_marks, _with_why
from app.web.views import (
    _demo_health,
    demo_health_memo,
    _demo_key_back,
    _deployment_out,
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


def dashboard(ctx: Ctx, ask_kalshi: bool = False):
    """The home dashboard's read: the shell's first read, an in-app visit and the 15s poll alike. It never
    waits on Kalshi (ask_kalshi False): the live cash comes from its memo or is marked pending (with the last
    figure read and its age), as Funds' is (funds.kalshi_cash), and the page asks /api/funds/cash?book=live
    for it; a demo-funds check that would read the demo cash is marked health_pending, and the page reads
    the dashboard again once that cash is read. The poll's version covers the cash, its read time and its
    pending mark, so a cash read since the page's last answer sends the page a full one."""
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
    # Capital and P&L look fine while Kalshi refuses every order. From the demo cash memo alone: pending when
    # it isn't kept (a line from a figure read under two minutes ago meanwhile, so it doesn't drop for a poll).
    health, health_pending = ((_demo_health(cur, ctx.uid, deps, ask_kalshi=True), False) if ask_kalshi
                              else demo_health_memo(cur, ctx.uid, deps))
    demo.update(capital=de["capital"], equity=de["equity"], realized_pnl=de["realized"],
                total_pnl=de["realized"], roi=de["roi"], before_reload=de["before_reload"], health=health)
    if health_pending:
        demo["health_pending"] = True
    live = _mode_bucket(cur, ctx.uid, "live", open_pos, deps, day, realized["live"], closed)
    live.update(kalshi_cash(cur, ctx.uid, ask_kalshi))
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
        # The server's live switch (/api/me's), polled with the page as the Deploy board's is.
        "live_trading_available": engine.LIVE_TRADING_ENABLED,
    }, ctx.query.get("v"))


# As old as the visit cookie can be (the page's max-age, 90 days). It was 7 days: back after a month,
# the strip said "Since your last visit Oct 20" and showed one week, none of the strategies the
# autopilot had put on paper in the three weeks before.
SINCE_MAX = timedelta(days=90)


SINCE_FIRST = timedelta(hours=24)  # no last visit known (first visit on this device): the last 24h


def _visit_since(raw) -> Tuple[datetime, bool]:
    """The start of "since your last visit" from the dashboard's ?since= (epoch seconds, kept in a
    cookie by the page), clamped to the last 90 days. Missing or unreadable: the last 24 hours, and
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
    is billed; a card charged in the meantime (auto-reload, mostly) rides with them. `milestones` are
    the paper forward-gate passes and live-ready strategies since then, `auto_paused` the strategies
    a loss guard paused (strategy ids).
    `by_deployment` splits each book's figure by the deployment that traded it ({mode: [{deployment_id,
    pnl, trades}]}, best first), the same rows, so a net loss names the strategy that made it. A row
    whose deployment the page doesn't list (`listed`: it was removed) says whose it was itself."""
    act = repo.activity_since(cur, uid, visit)
    return {"at": visit, "first": first,
            "books": {m: {"pnl": cents(pnl), "trades": n} for m, (pnl, n) in recent.items()},
            "passed": _passed_since(cur, uid, visit),
            "autopilot": act["autopilot"], "runs": act["runs"], "own_sessions": bool(act.get("own_sessions")),
            "spent": {**{k: credit_usd(v) for k, v in act["spent"].items()}, "card_charged": bool(act.get("card_charged", True)),
                      **_bought(act.get("bought"))}
            if billing.configured() and act.get("spent") else None,
            "milestones": act.get("milestones") or {"passed": [], "live_ready": []},
            "auto_paused": act.get("auto_paused") or [],
            "by_deployment": _since_by_deployment(by_dep or {}, _removed_names(cur, uid, by_dep or {}, listed))}


PASSED_JUDGE = 500  # the passes since the visit judged for a later check; the strip names 3 of them


def _passed_since(cur, uid: int, visit: datetime) -> Dict:
    """repo.passed_since for the strip: {"n", "items": [{id, title}] the newest 3}, without the passes a
    later check left uncleared (strategies._later_verdicts, one read for all of them, only when something
    passed): one whose one-time holdout then failed, or that the diversification check held back. Those
    go under "not_cleared" ([{id, title, verdict}], newest 3) and "not_cleared_n". The strip said
    "2 strategies passed" for strategies their pages said missed the final test or were held back.
    Up to PASSED_JUDGE passes are judged, all of them in one read: only the newest 50 were, so past 50 "n"
    took off only the uncleared among those 50 and "not_cleared_n" counted those 50 alone. Past
    PASSED_JUDGE (the read is polled every 15s, ~5ms per 100 passes) "more" is set and both counts are
    those of the newest PASSED_JUDGE, at least that many: the strip says "500+", never a wrong exact count."""
    got = repo.passed_since(cur, uid, visit, limit=PASSED_JUDGE)
    items = got.get("items") or []
    later = _later_verdicts(cur, uid, [dict(i, status="passed", spec=i.get("spec") or {}) for i in items]) if items else {}
    name = lambda i: {"id": i["id"], "title": i["title"]}
    more = int(got.get("n") or 0) > len(items)
    out = {"n": (len(items) if more else int(got.get("n") or 0)) - len(later),
           "items": [name(i) for i in items if i["id"] not in later][:3]}
    if more:
        out["more"] = True
    if later:
        out["not_cleared"] = [dict(name(i), verdict=later[i["id"]][0]) for i in items if i["id"] in later][:3]
        out["not_cleared_n"] = len(later)
    return out


def _bought(b: Optional[Dict]) -> Dict:
    """The strip's card charges since the visit, from activity_since's `bought`: the credits they bought
    (`bought`), how many charges (`charges`) and how many of those were auto-reloads (`reloads`). None
    bought: nothing, so the row reads as before."""
    if not b or not b.get("charges"):
        return {}
    return {"bought": credit_usd(b["usd"]), "charges": int(b["charges"]), "reloads": int(b.get("auto") or 0)}


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
