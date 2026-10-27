"""Strategy routes: the strategies list and detail page, delete, share, what-if and the dev curve,
plus the per-strategy figures they show (cards, marks, experiment and phase blocks, backtest
checks). Moved verbatim from app.server, which re-imports every name for its route table."""
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from app import repository as repo
from app.adapters.kalshi import kalshi_dev
from app.research import agent, gatekeeper
from app.research import research_repository as research_repo
from app.services import backtest_check, book_memo, forward_gate, gate_explain, trade_why
from app.trading import backtest, track_record
from app.trading import spec as specmod
from app.trading.markets import MARKETS
from app.web.caches import _forget_own_change
from app.web.http import ApiError, Ctx, _int_param, _num
from app.web.views import (
    _deployment_out,
    _demo_key_back,
    _gate_lines,
    _gate_tints,
    _paper_books,
    _past_deployment_out,
    _spec_sizing,
    demo_health_memo,
)
from trading_core.domain.money import cents


def _strategy_card(s: Dict) -> Dict:
    res = s.get("result") or {}
    return {
        "id": s["id"], "run_id": s["run_id"], "parent_id": s["parent_id"], "market": s["market"],
        "direction": s["direction"], "title": s["title"], "thesis": s["thesis"], "status": s["status"],
        "created_at": s["created_at"], "hypotheses_tried": s.get("hypotheses_tried"),
        "in_sample": res.get("in_sample"), "out_of_sample": res.get("out_of_sample"),
        "equity": res.get("equity"), "capital": res.get("capital"),
        "stake": _spec_sizing(s).get("stake"),
        "side": (s["spec"].get("perpetual") or {}).get("side") if specmod.is_perpetual_spec(s["spec"]) else s["spec"].get("side"),
        **({"kind": "perpetual", "research_only": True} if specmod.is_perpetual_spec(s["spec"]) else {}),
        # Agent-authored code runs only in the research sandbox: create_deployment refuses it in every
        # mode, so the pages offer no deploy button for it (they did, and every tap failed).
        **({"kind": "code", "research_only": True} if specmod.is_code_spec(s["spec"]) else {}),
        "deployed": bool(s.get("active_deps")), "deploy_live": bool(s.get("live_deps")),
        "shared_from": s.get("shared_from_name") if s.get("shared_from_user_id") else None,
        "example": s.get("direction") == repo.DEMO_DIRECTION,  # from the seeded example session
        # Found in a session the autopilot started (its run's brief flag, as the research list reads it).
        **({"by_autopilot": True} if s.get("by_autopilot") else {}),
    }


def _mark_fields(p: Dict) -> Dict:
    """Live mark-to-market for one open position from the engine-stamped mark_price (the YES bid
    on a YES position, the YES ask on a NO one). None until the engine's first mark after entry.
    `at_cost` (contracts x entry price) and `cost` (plus the entry fee) are the position's money to the
    cent, rounded as the books' open figures are: the pages multiplied them out themselves, and a
    float product a hair under a half cent (5 x 30.1¢) read $1.50 beside the dashboard's $1.51."""
    qty = int(p["qty"])
    at_cost = Decimal(qty) * Decimal(str(p["entry_price"]))
    cost = at_cost + Decimal(str(p.get("entry_fee") or 0))
    money = {"at_cost": cents(at_cost), "cost": cents(cost)}
    mark = p.get("mark_price")
    if mark is None:
        return {**money, "mark": None, "value": None, "unrealized": None, "mark_ts": None}
    mark = float(mark)
    # A YES contract sells at the YES bid (mark); a NO contract at its own bid, 1 - yes_ask (1 - mark).
    value = cents(qty * (mark if p["side"] == "yes" else 1.0 - mark))
    return {**money, "mark": mark, "value": value, "unrealized": cents(Decimal(str(value)) - cost), "mark_ts": p.get("mark_ts")}


def _with_marks(rows: List[Dict]) -> List[Dict]:
    for p in rows:
        p.update(_mark_fields(p))
    return rows


# An open position whose strategy was deleted (before delete_strategy refused while positions were
# open) comes back with no title, and Deploy and the dashboard showed it with a blank name. The engine
# settles and sells positions through their strategy row (repo.orphaned_open_positions), so nothing
# acts on it now: the row names it and says so.
DELETED_STRATEGY = "Deleted strategy"
DELETED_WHY = "Its strategy was deleted, so Tau no longer sells or settles this position."


def _with_why(rows: List[Dict], deps: List[Dict]) -> List[Dict]:
    """Each position's one-line entry/exit reason (app.services.trade_why), from the strategy specs
    of the deployments the request already read: no extra statement. A position of a stopped
    deployment (not in `deps`) gets its exit reason only; an open one whose strategy is deleted is
    named DELETED_STRATEGY and says nothing acts on it (display only)."""
    specs = {d["id"]: d.get("spec") for d in deps}
    for p in rows:
        if "title" in p and not p["title"] and p.get("status") == "open":
            p["title"], p["why"] = DELETED_STRATEGY, DELETED_WHY
            continue
        p["why"] = trade_why.trade_why(p, specs.get(p.get("deployment_id")))
    return rows


def list_strategies(ctx: Ctx):
    q = ctx.query
    direction, status, market = q.get("direction") or None, q.get("status") or None, q.get("market") or None
    search = (q.get("q") or "").strip()[:80] or None  # cap: a search box, not a query language
    deployed = q.get("deployed") in ("1", "true")
    try:
        page = max(0, int(q.get("page") or 0))
    except ValueError:
        page = 0
    per = 50
    counts = repo.count_strategies(ctx.cur, ctx.uid, direction, market, search, deployed)  # true per-status totals, not a capped page
    # Every pass under these filters, and every void or rejected probation strategy that passed on paper,
    # is judged for a later check that left it uncleared (Missed final test, Held back), in one read for
    # all of them, so the chips count every page, not the 50 shown. Those it leaves uncleared count and
    # list under Not cleared: a pass out of Passed, a probation strategy held back on paper out of Void
    # or Rejected (it read "Held back" under the Void chip).
    judged = repo.passed_strategies(ctx.cur, ctx.uid, direction, market, search, deployed,
                                    paper_passed=gatekeeper.Classification.FORWARD_VALIDATED.value)
    got = _later_verdicts(ctx.cur, ctx.uid, judged)
    uncleared = [p for p in judged if p["id"] in got]
    _split_not_cleared(counts, judged, got)
    # Default ("Kept") view hides rejected/void — the big-run noise — but keeps every row in the
    # DB (the ledger counts them for DSR/FDR). An explicit status chip overrides and shows it.
    hide_noise = status is None
    noise = sum(counts.get(s, 0) for s in repo.NOISE_STATUSES)
    # "best": best unseen-data backtest P&L first, across every page (the list is paged server-side).
    sort = "best" if q.get("sort") == "best" else None
    keep = [p["id"] for p in uncleared if p["status"] in repo.NOISE_STATUSES] if hide_noise else []
    rows = repo.list_strategies(ctx.cur, ctx.uid, direction, None if status == NOT_CLEARED else status, market,
                                limit=per, offset=page * per, q=search, deployed=deployed, hide_noise=hide_noise,
                                sort=sort, only_ids=[p["id"] for p in uncleared] if status == NOT_CLEARED else None,
                                skip_ids=[p["id"] for p in uncleared if p["status"] == status] or None,
                                **({"keep_ids": keep} if keep else {}))
    # The seeded example's strategies are out of the counts but still listed (marked "example").
    ex = counts.get("examples") or {}
    shown_ex = ex.get(status, 0) if status else sum(n for s, n in ex.items() if s not in repo.NOISE_STATUSES)
    matched = (counts.get(status, 0) if status else counts["total"] - noise) + shown_ex
    cards = [_strategy_card(s) for s in rows]
    _attach_verdicts(cards, got)
    _attach_real_records(ctx.cur, ctx.uid, cards)
    _attach_past_records(ctx.cur, ctx.uid, cards, [s["id"] for s in rows if s.get("removed_deps")])
    return {"strategies": cards, "counts": counts,
            "matched": matched, "page": page, "per": per, "pages": (matched + per - 1) // per}


def _attach_verdicts(cards: List[Dict], got: Dict[int, Tuple[str, Dict]]) -> None:
    """Stamp each card whose stored status leaves out a later check with `verdict` (MISSED_FINAL or
    HELD_BACK), the stamp its own page shows, from _later_verdicts' reads for the whole list. A list
    stamped "Passed" for a strategy whose page said "Missed final test" or "Held back"."""
    for c in cards:
        if c["id"] in got:
            c["verdict"] = got[c["id"]][0]


# The Strategies list's chip for passes a later check left uncleared (Missed final test, Held back): a
# status filter of its own, never a stored status.
NOT_CLEARED = "not_cleared"


def _split_not_cleared(counts: Dict, judged: List[Dict], got: Dict[int, Tuple[str, Dict]]) -> None:
    """Move the strategies `got` has a verdict for out of their stored status's count and into
    NOT_CLEARED, the seeded example's under "examples" as count_strategies keeps them, so "Passed (3)"
    over rows stamped Missed final test and Held back reads "Passed (1)" and "Not cleared (2)", and a
    probation strategy held back after passing on paper leaves "Void" for "Not cleared" too. The total
    is unchanged."""
    ex = counts.setdefault("examples", {})
    for p in judged:
        if p["id"] not in got:
            continue
        into = ex if p.get("direction") == repo.DEMO_DIRECTION else counts
        into[p["status"]] = into.get(p["status"], 0) - 1
        into[NOT_CLEARED] = into.get(NOT_CLEARED, 0) + 1
    for k in [k for k, n in ex.items() if not n]:
        ex.pop(k)


def _attach_real_records(cur, uid: int, cards: List[Dict]) -> None:
    """Stamp each deployed card with what it has actually done since deploying (realized P&L and
    closed trades across its active deployments), so the list shows reality next to the backtest.
    Money books are never summed: a strategy with a live deployment reports its live deployments
    only (beside its Live badge), otherwise its paper ones, with its demo (sandbox) book beside them
    under "demo" rather than added in. One query, and only when the page has a deployed strategy."""
    if not any(c.get("deployed") for c in cards):
        return
    memo = book_memo.BookMemo(cur, uid)
    deps = book_memo.deployments_for_display(memo)
    real = _book_totals(deps)
    for c in cards:
        books = real.get(c["id"]) if c.get("deployed") else None
        if books:
            mode = next((m for m in ("live", "paper", "demo") if m in books), None)
            if mode is None:  # only a mode this list doesn't show
                continue
            r = books[mode]
            # Every book it runs in now, so the row's badge names them ("On paper + demo"), not "Deployed".
            c["books"] = [m for m in BOOK_ORDER if m in books]
            c["real"] = {**r, "live": mode == "live", "mode": mode}
            if mode == "paper" and "demo" in books:
                dm = books["demo"]
                c["real"]["demo"] = {"pnl": dm["pnl"], "trades": dm["trades"], "open": dm["open"]}
    _flag_instant_only(memo, cards, deps)


def _flag_instant_only(memo, cards: List[Dict], deps: List[Dict]) -> None:
    """Stamp `instant_fills` (how many) on a card whose shown paper book has closed trades that were instant
    fills (not through the simulated venue, order_ref 'sim:'), as the track record tells them apart: it leaves
    those trades out and says how many, while the list's "+$1.30 on paper since deploying · 2 trades" read as
    a record. `instant_only` when every one was. One kept read (book_memo), only for paper rows with trades."""
    _stamp_instant_fills(lambda ids: book_memo.realistic_paper_closed(memo, ids), {c["id"]: c["real"] for c in cards
                                if (c.get("real") or {}).get("mode") == "paper" and c["real"].get("trades")}, deps)


def _stamp_instant_fills(read_sim, paper: Dict[int, Dict], deps: List[Dict]) -> None:
    """For {strategy_id: its listed paper book ({trades, ...}, _book_totals)}: stamp `instant_fills`, its
    closed paper rows less those filled through the simulated venue (`read_sim`: repo.realistic_paper_closed
    over the same deployments, kept or not), when any, and `instant_only` when all were. An instant fill has no order_ref, so
    each is one row and one trade, as track_record.prepare counts the ones it leaves out. Display only:
    nothing here feeds a gate."""
    paper = {sid: r for sid, r in paper.items() if r.get("trades")}
    if not paper:
        return
    dep_ids = {sid: [d["id"] for d in deps if d["strategy_id"] == sid and d["mode"] == "paper" and d.get("id")] for sid in paper}
    sim = read_sim([i for ids in dep_ids.values() for i in ids])
    for sid, r in paper.items():
        n = max(0, int(r["trades"]) - sum(sim.get(i, 0) for i in dep_ids[sid]))
        if n:
            r["instant_fills"] = n
        if n >= int(r["trades"]):
            r["instant_only"] = True


def _stamp_row_instant_fills(read_sim, rows: List[Dict]) -> None:
    """Stamp `instant_fills` on each paper deployment row (as _deployment_out sends it) whose closed trades
    were partly or all instant fills: its closed rows less those filled through the simulated venue
    (`read_sim`: repo.realistic_paper_closed over those deployments, kept or not). The Deploy board and the
    dashboard showed "2 closed" beside "0/30 trades" toward live with no word why. Read only when a paper row
    has a closed trade. Display only: nothing here feeds a gate."""
    paper = [r for r in rows if r.get("mode") == "paper" and int(r.get("closed_trades") or 0) > 0 and r.get("id")]
    if not paper:
        return
    sim = read_sim([r["id"] for r in paper])
    for r in paper:
        n = int(r["closed_trades"]) - int(sim.get(int(r["id"]), 0))
        if n > 0:
            r["instant_fills"] = n


BOOK_ORDER = ("live", "paper", "demo")


def _book_totals(deps: List[Dict]) -> Dict[int, Dict[str, Dict]]:
    """{strategy_id: {mode: {pnl, trades, open, paused}}}: each strategy's listed (not removed)
    deployments summed per book, never across books, the P&L exactly and then rounded once. The
    strategies list's "since deploying" figure and the strategy page's per-book lines both read this:
    the page added its deployments' rounded figures, so two deployments in one book could read a
    cent away from the list."""
    out: Dict[int, Dict[str, Dict]] = {}
    for d in deps:
        r = out.setdefault(d["strategy_id"], {}).setdefault(d["mode"], {"pnl": Decimal(0), "trades": 0, "open": 0, "paused": False})
        r["paused"] = r["paused"] or d.get("status") == "paused"  # often auto-paused; the list flags it
        r["pnl"] += Decimal(str(d["realized_pnl"] or 0))
        r["trades"] += int(d["closed_trades"] or 0)
        r["open"] += int(d["open_positions"] or 0)
    for books in out.values():
        for r in books.values():
            r["pnl"] = cents(r["pnl"])
    return out


def _attach_past_records(cur, uid: int, cards: List[Dict], removed_ids: List[int]) -> None:
    """Stamp each card whose strategy has removed deployments (`removed_ids`, from the list read's
    removed_deps) with what they made, per book: {mode: {"pnl", "trades", "deployments"}} under
    "past". A removed deployment leaves the card's "since deploying" line (active ones only), so a
    strategy that traded for a week and was removed read as if it never traded, while the track
    record's strategy row and the strategy page's "Past deployments" line still counted its trades.
    Books are never added together. One read, and only when the page has such a strategy."""
    if not removed_ids:
        return
    past: Dict[int, Dict[str, Dict]] = {}
    for r in repo.removed_totals_by_strategy(cur, uid, removed_ids):
        past.setdefault(int(r["strategy_id"]), {})[r["mode"]] = {
            "pnl": cents(r["pnl"]), "trades": int(r["trades"] or 0), "deployments": int(r["deployments"] or 0)}
    for c in cards:
        books = past.get(c["id"])
        if books:
            c["past"] = {m: books[m] for m in BOOK_ORDER if m in books}


def _owned_strategy(ctx: Ctx) -> Dict:
    s = repo.get_strategy(ctx.cur, ctx.uid, _int_param(ctx))
    if s is None:
        raise ApiError(404, "No such strategy.")
    return s


DELETE_MODES = ("paper", "demo", "live")


def _delete_block(open_positions: List[Dict]) -> Optional[str]:
    """Why a strategy can't be deleted yet, from its open positions (every deployment, stopped ones
    included, any mode), or None. Stopping a deployment leaves its positions open, and the engine
    settles and flattens positions through their strategy row: deleting the strategy first would
    leave them open for good, with paper cash already paid for them."""
    if not open_positions:
        return None
    n = len(open_positions)
    by_mode = {m: sum(1 for p in open_positions if p["mode"] == m) for m in DELETE_MODES}
    parts = ", ".join("%s: %d" % (m, k) for m, k in by_mode.items() if k)
    return ("This strategy still holds %d open position%s (%s). They'll close at settlement; delete it after that."
            % (n, "" if n == 1 else "s", parts))


def delete_strategy(ctx: Ctx):
    """Remove a strategy from the user's inventory. Blocked while it's deployed (stop the deployment
    first) and while any of its deployments, in any mode, still holds an open position."""
    s = _owned_strategy(ctx)
    if any(d["strategy_id"] == s["id"] for d in repo.list_deployments(ctx.cur, ctx.uid, include_stopped=False)):
        raise ApiError(409, "Stop this strategy's deployment before deleting it.")
    block = _delete_block(repo.positions_for_strategy(ctx.cur, ctx.uid, s["id"], "open"))
    if block:
        raise ApiError(409, block)
    repo.delete_strategy(ctx.cur, ctx.uid, s["id"])
    _forget_own_change(ctx.uid, s["id"])
    return {"ok": True}


def share_strategy(ctx: Ctx):
    """Share a strategy with another Tau user by email. Copies it into their inventory
    (not revocable) and notifies them. The recipient must already have an account."""
    s = _owned_strategy(ctx)
    email = str(ctx.body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise ApiError(400, "Enter the email your friend signs in with.")
    recipient = repo.user_by_email(ctx.cur, email)
    if not recipient:
        raise ApiError(404, "No Tau account uses that email yet — they need to sign in first.")
    if recipient["id"] == ctx.uid:
        raise ApiError(400, "That's your own account.")
    new_id = repo.share_strategy(ctx.cur, s["id"], ctx.uid, recipient["id"])
    if new_id is None:
        return {"ok": True, "already": True}  # idempotent: they already have this one
    sender = (repo.get_user(ctx.cur, ctx.uid) or {}).get("name") or "A friend"
    repo.add_notification(ctx.cur, recipient["id"], "share",
                          "%s shared the strategy “%s” with you." % (sender, s["title"]),
                          "/strategies/%d" % new_id)
    return {"ok": True}


def _exp_num(row: Dict, key: str) -> Optional[float]:
    v = row.get(key)
    return None if v is None else float(v)


def _exp_bool(row: Dict, key: str) -> Optional[bool]:
    v = row.get(key)
    return None if v is None else bool(v)


def _exp_int(row: Dict, key: str) -> Optional[int]:
    v = row.get(key)
    return None if v is None else int(v)


def _phase_block(row: Optional[Dict], holdout: bool = False) -> Optional[Dict]:
    """Shape one app_experiment_results row (validation or holdout) into the §D block."""
    if not row:
        return None
    out = {
        "classification": row.get("classification"),
        "n_trades": _exp_int(row, "n_trades"),
        "mean_net_return": _exp_num(row, "mean_net_return"),
        "ci_lo": _exp_num(row, "ci_lo"),
        "ci_hi": _exp_num(row, "ci_hi"),
        "p_value": _exp_num(row, "p_value"),
        "psr": _exp_num(row, "psr"),
        "dsr": _exp_num(row, "dsr"),
        "sharpe": _exp_num(row, "sharpe"),
        "net_pnl": _exp_num(row, "net_pnl"),
        "fdr_alpha_i": _exp_num(row, "fdr_alpha_i"),
        "fdr_reject": _exp_bool(row, "fdr_reject"),
        "bh_reject": _exp_bool(row, "bh_reject"),
        "placebo_p": _exp_num(row, "placebo_p"),
        "n_trials_audited": _exp_int(row, "n_trials_audited"),
        "equity_curve": row.get("equity_curve"),
    }
    if holdout:
        out["consumed"] = bool(row.get("holdout_consumed"))
    return out


def _rationale(raw) -> Dict:
    """economic_rationale is a TEXT column the gatekeeper stores as structured JSON (§D:
    mechanism / negative_control / competing_explanations / folds). Fall back to treating
    it as a plain mechanism string for anything older or free-form."""
    try:
        d = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else None)
    except (ValueError, TypeError):
        d = None
    if not isinstance(d, dict):
        return {"mechanism": raw or None, "negative_control": None,
                "competing_explanations": None, "folds": []}
    return {
        "mechanism": d.get("mechanism") or raw,
        "negative_control": d.get("negative_control"),
        "competing_explanations": d.get("competing_explanations") or d.get("challenger"),
        "folds": d.get("folds") or [],
    }


def _later_fields(results: List[Dict]) -> Dict:
    """The experiment block's verdicts after validation, from its result rows (oldest first): the one-time
    holdout, a probation strategy's one paper judgment (with when it was judged), and whether it was promoted
    all the way to a deployment candidate (agent._is_deployment_candidate's own test). A strategy page reads
    them from all its rows, a list from research_repo.later_results' rows, so both judge alike."""
    latest = lambda phase: next((r for r in reversed(results) if r.get("phase") == phase), None)
    paper = latest("paper")
    return {
        "holdout": _phase_block(latest("holdout"), holdout=True),
        "paper": dict(_phase_block(paper), verdict_at=paper.get("verdict_at")) if paper else None,
        # A holdout (or paper) pass that isn't was held back by the diversification check after it.
        "promoted": any(r.get("classification") == gatekeeper.Classification.DEPLOYMENT_CANDIDATE.value
                        for r in results),
    }


def _experiment_block(cur, strategy_id: int, experiment_id: Optional[int] = None) -> Optional[Dict]:
    """The §D research-paper `experiment` block for a strategy, or None when the strategy
    predates the rigorous-research pipeline (no ledger row). Resolves by the strategy's stored
    experiment_id first (robust link), falling back to the legacy strategy_id lookup. Additive by
    design: a None here leaves the rest of the detail page intact — never a regression."""
    rec = research_repo.experiments_for_strategy(cur, strategy_id, experiment_id)
    if not rec:
        return None
    exp = rec["experiment"]
    results = rec["results"] or []
    val_row = next((r for r in reversed(results) if r.get("phase") == "validation"), None)
    val = _phase_block(val_row)
    rat = _rationale(exp.get("economic_rationale"))
    overall = results[-1]["classification"] if results else None
    return {
        **_later_fields(results),
        "classification": overall,
        "registered_at": exp.get("registered_at"),
        "mechanism": rat["mechanism"],
        "negative_control": rat["negative_control"],
        "competing_explanations": rat["competing_explanations"],
        "falsification_criteria": exp.get("falsification_criteria"),
        "null_hypothesis": exp.get("null_hypothesis"),
        "alt_hypothesis": exp.get("alt_hypothesis"),
        "primary_metric": exp.get("primary_metric"),
        "planned_test": exp.get("planned_test"),
        "min_sample": _exp_int(exp, "min_sample"),
        "cost_assumptions": exp.get("cost_assumptions"),
        "planned_n_tests": _exp_int(exp, "planned_n_tests"),
        "correction_method": exp.get("correction_method"),
        "n_trials_audited": (val or {}).get("n_trials_audited"),
        "validation": val,
        # Prefer the gatekeeper's recorded cross-day folds (validation phase); fall back to any
        # folds embedded in the older rationale JSON so pre-pipeline experiments still render.
        "folds": (val_row or {}).get("folds") or rat["folds"],
    }


def _autopilot_puts_on_paper(cur, user: Optional[Dict], strategies: List[Dict]) -> set:
    """The passed strategies (a session's, or a strategy page's one) the autopilot puts on paper itself
    at its next check-in, by the tests agent.auto_paper_candidates applies: autopilot on, room under its
    cap, never on paper before, a deployable market inside the focus, not code, and a gatekeeper
    deployment candidate. Display only: the pages said "Open it to deploy it on paper" while the
    autopilot was about to, and a copy deployed by hand as well doubles the positions."""
    if not (user or {}).get("autopilot"):
        return set()
    waiting = [s for s in strategies if s["status"] == "passed" and not s.get("active_deps")
               and s.get("direction") != repo.DEMO_DIRECTION]
    if not waiting:
        return set()
    deps = repo.list_deployments(cur, user["id"], include_stopped=True)
    if sum(1 for d in deps if d["status"] != "stopped") >= agent.AUTO_PAPER_MAX_ACTIVE:
        return set()
    tried = {d["strategy_id"] for d in deps if d["mode"] == "paper" or d["status"] != "stopped"}
    focus = agent.focus_tokens(user)
    out = set()
    for s in waiting:
        mkt = MARKETS.get(s["market"])
        if (s["id"] in tried or mkt is None or not mkt.deployable or not agent.in_focus(s["market"], focus)
                or specmod.is_code_spec(s["spec"])):
            continue
        if agent._is_deployment_candidate(cur, s["id"]):
            out.add(s["id"])
    return out


# What a strategy's stored status leaves out (its card's `verdict`). The status is written once, at
# validation (or, for a probation strategy, at its validation miss), and a later check doesn't change it:
# a validation pass whose one-time locked holdout then failed still reads "passed", and so does one the
# diversification check after the holdout held back; a probation strategy that passed its one paper
# judgment and was then held back by that check keeps its Void or Rejected.
MISSED_FINAL, HELD_BACK = "missed_final", "held_back"


def _later_verdict(s: Dict, exp: Optional[Dict]) -> Optional[str]:
    """MISSED_FINAL, HELD_BACK or None for one strategy, from its experiment block (a page's
    _experiment_block, or _later_verdicts' slim one built from the same rows by _later_fields). Display
    only: it reads the gatekeeper's record and judges nothing again."""
    if not exp:
        return None
    if s.get("status") == "passed" and _gate_lines(gate_explain.for_strategy, "passed", None, exp):
        return MISSED_FINAL  # for_strategy reads a failed holdout first, as the page's why_failed does
    if exp.get("promoted") or specmod.has_perpetual_market(s["spec"], s.get("market")):  # research only: never promoted
        return None
    fv = gatekeeper.Classification.FORWARD_VALIDATED.value
    if s.get("status") == "passed" and (exp.get("holdout") or {}).get("classification") == fv:
        return HELD_BACK
    if s.get("status") in ("failed", "rejected") and (exp.get("paper") or {}).get("classification") == fv:
        return HELD_BACK
    return None


def _later_verdicts(cur, uid: int, strategies: List[Dict]) -> Dict[int, Tuple[str, Dict]]:
    """{strategy id: (its _later_verdict, the slim experiment block it was judged on)} for the strategies a
    list shows, those with one only. At most two reads for the whole list, never one per row: only for a
    passed strategy stored before app_strategies.experiment_id existed, the experiment experiments_for_strategy
    falls back to (by idx_exp_user_market's user_id), then their experiments' holdout, paper and forward rows
    (research_repo.later_results, by primary key and idx_res_exp)."""
    eids = {s["id"]: int(s["experiment_id"]) for s in strategies if s.get("experiment_id")}
    legacy = [s["id"] for s in strategies if s.get("status") == "passed" and s["id"] not in eids]
    if legacy:
        eids.update(research_repo.newest_experiment_ids(cur, uid, legacy))
    later = research_repo.later_results(cur, list(eids.values()))
    out: Dict[int, Tuple[str, Dict]] = {}
    for s in strategies:
        rec = later.get(eids.get(s["id"]))
        if rec is None:
            continue
        try:
            exp = dict(_later_fields(rec["results"]), min_sample=_exp_int(rec, "min_sample"))
        except (TypeError, ValueError):  # a record it can't read never fails the list
            continue
        v = _later_verdict(s, exp)
        if v:
            out[s["id"]] = (v, exp)
    return out


def _research_pass_verdicts(cur, uid: int, since) -> Tuple[List[Dict], Dict[int, Tuple[str, Dict]]]:
    """(the passes from research sessions started since `since`, _later_verdicts for them): what the
    research headlines ("kept N that beat every gate", the autopilot's "N passed this week") count, and
    which of those a later check left uncleared (Missed final test, Held back), so a headline counts only
    what cleared and says how many didn't, as the session rows and the Strategies chips do. One read of
    the passes (repo.passed_strategies, idx_strat_user, each pass's session by primary key), then one of
    their experiments' later rows (later_results), plus the legacy fallback only for a pass stored
    without its experiment id; none when nothing passed. The seeded example is never judged, as on its
    page. Display only."""
    passes = repo.passed_strategies(cur, uid, research_since=since)
    return passes, _later_verdicts(cur, uid, [p for p in passes if p.get("direction") != repo.DEMO_DIRECTION])


def _held_back_lines(cur, uid: int, held: List[Tuple[Dict, Dict]]) -> Dict[int, List[Dict]]:
    """{strategy id: gate_explain.held_back} for strategies _later_verdict holds back, each with its
    experiment block. The reason is the gatekeeper's own, from its one record: a holdout pass's run verdict
    event (repo.forward_verdicts, one read per run), or a paper pass's line in the autopilot chat
    (forward_gate.held_reason, the first such line at or after its paper judgment, one read in all). The
    strategy it repeats is named by its title (one read), never by experiment id. Display only."""
    reasons: Dict[int, Optional[str]] = {}
    events: Dict[int, Dict[str, Dict]] = {}
    chat: Optional[List[Dict]] = None
    for s, exp in held:
        reason = None
        if s.get("status") == "passed":
            if s.get("run_id") and not s.get("shared_from_user_id"):
                if s["run_id"] not in events:
                    events[s["run_id"]] = repo.forward_verdicts(cur, s["run_id"])
                ev = events[s["run_id"]].get(s["title"])
                reason = ev.get("reason") if ev and ev.get("marginal_ok") is False else None
        else:
            if chat is None:
                chat = list(reversed(repo.chat_lines_like(cur, uid, "system", forward_gate.HELD_LIKE)))
            at = (exp.get("paper") or {}).get("verdict_at")
            reason = next((r for r in (forward_gate.held_reason(c["content"], s["title"]) for c in chat
                                       if at is None or c["created_at"] >= at) if r), None)
        reasons[s["id"]] = reason
    peers = research_repo.strategy_titles(cur, uid, [e for e in map(gate_explain.corr_peer, reasons.values()) if e])
    return {s["id"]: gate_explain.held_back(reasons[s["id"]], peers.get(gate_explain.corr_peer(reasons[s["id"]])),
                                            on="holdout" if s.get("status") == "passed" else "paper")
            for s, _ in held}


def get_strategy(ctx: Ctx):
    s = _owned_strategy(ctx)
    out = _strategy_card(s)
    res = s.get("result") or {}
    deps = repo.list_deployments_for_display(ctx.cur, ctx.uid, strategy_id=s["id"])
    held = repo.positions_for_strategy(ctx.cur, ctx.uid, s["id"], "open")
    key_back = _demo_key_back(ctx.cur, ctx.uid, deps)
    exp = _experiment_block(ctx.cur, s["id"], s.get("experiment_id"))
    if exp:
        # Which research-paper figures their gate passed or missed, by the same checks as
        # why_failed, so a figure is red exactly when its line says it missed (display only).
        exp = dict(exp, gate_tints=_gate_tints(s.get("status"), exp))
    verdict = _later_verdict(s, exp)
    held_back = _gate_lines(_held_back_lines, ctx.cur, ctx.uid, [(s, exp)]) if verdict == HELD_BACK else {}
    if verdict:
        out["verdict"] = verdict
    # The ladder's demo rung: why its demo book can't trade, or (not on demo yet) what demo needs. From the
    # demo cash memo alone, never Kalshi: pending when it isn't kept, and the page asks
    # /api/funds/cash?book=demo, then reads the strategy again once (a line from a figure read under two
    # minutes ago stands meanwhile).
    demo_health, demo_pending = (None, False) if specmod.has_perpetual_market(s["spec"], s.get("market")) else \
        demo_health_memo(ctx.cur, ctx.uid, deps, stake=(s["spec"].get("sizing") or {}).get("stake"))
    if demo_pending:
        out["demo_health_pending"] = True
    books = _book_totals(deps).get(s["id"], {})
    # How many of its paper book's closed trades were instant fills, which the track record leaves out (one
    # read over its own paper deployments, only when that book has a closed trade): the page's lines say so.
    # Display only.
    # The same read stamps each paper deployment's own count, so the page's backtest pace line counts realistic
    # fills only, as its backtest check and its count toward live do.
    sim: Optional[Dict[int, int]] = None
    if (books.get("paper") or {}).get("trades"):
        sim = repo.realistic_paper_closed(ctx.cur, [d["id"] for d in deps if d["mode"] == "paper" and d.get("id")])
        _stamp_instant_fills(lambda ids: sim, {s["id"]: books["paper"]}, deps)
    deps_out = [_deployment_out(d, [], demo_key_back=key_back, paper_books=_paper_books(deps)) for d in deps]
    if sim is not None:
        _stamp_row_instant_fills(lambda ids: sim, deps_out)
    out.update(
        spec=s["spec"], rules=specmod.describe(s["spec"]), gates=res.get("gates"), dataset=res.get("dataset"),
        recent_trades=res.get("recent_trades"),
        # The backtest columns' "too few trades to tell skill from luck" caution (display only): the app's
        # one noise level for a trade count, deliberately stricter than the gate's floor, which it names.
        sample_caution={"min_trades": track_record.MIN_TRADES, "gate_min_oos_trades": backtest.GATES["min_oos_trades"]},
        experiment=exp,
        # One plain line per gate it missed: measured, needed, and what to try next (display only). One held
        # back after passing on paper names that check, not the validation miss that put it on probation.
        why_failed=(held_back or {}).get(s["id"]) or _gate_lines(gate_explain.for_strategy, s.get("status"), res, exp),
        deployments=deps_out,
        # Its deployments summed per book ({mode: {pnl, trades, open, paused}}), as the strategies list sums them.
        book_totals=books,
        # Its removed deployments, newest first: book, dates and realized P&L (they left the list above).
        past_deployments=[_past_deployment_out(r) for r in _removed_with_totals(ctx.cur, ctx.uid, s["id"])],
        holdings=[{
            "ticker": p["ticker"], "side": p["side"], "qty": int(p["qty"]), "mode": p["mode"],
            "entry_price": float(p["entry_price"]),
            "cost": cents(Decimal(int(p["qty"])) * Decimal(str(p["entry_price"])) + Decimal(str(p["entry_fee"] or 0))),
            "market_close_time": p["market_close_time"], **_mark_fields(p), "why": trade_why.trade_why(p, s["spec"]),
        } for p in held],
        # The Remove button's reason while any deployment of it still holds a position (delete_strategy's guard).
        delete_block=_delete_block(held),
        demo_health=demo_health,
        # Each book's realized per-trade P&L against the backtest's, one line per book (display only).
        # The page shows them under its current deployments, so with none there is nothing to read.
        backtest_checks=_backtest_checks(ctx.cur, ctx.uid, {s["id"]: s}).get(s["id"], []) if deps else [],
        # The autopilot puts it on paper itself at its next check-in while its switch is on, judged as if on so
        # the page follows a flip: the page says so in place of Deploy on paper, as a copy by hand doubles it.
        # Only a promoted strategy can be one, so no other page reads the user's deployments for it.
        autopilot_paper=bool(exp and exp.get("promoted")) and s["id"] in _autopilot_puts_on_paper(
            ctx.cur, dict(ctx.user, autopilot=1), [dict(s, active_deps=any(d["status"] != "stopped" for d in deps))]),
    )
    return out


def _removed_with_totals(cur, uid: int, strategy_id: int) -> List[Dict]:
    """repo.removed_deployments for one strategy, each with its closed trades and realized P&L (its own
    closed positions, repo.deployment_closed_totals); no position is read when none was removed."""
    rows = repo.removed_deployments(cur, uid, strategy_id)
    totals = repo.deployment_closed_totals(cur, [r["id"] for r in rows]) if rows else {}
    for r in rows:
        r["closed_trades"], r["realized_pnl"] = totals.get(int(r["id"]), (0, 0))
    return rows


BACKTEST_CHECK_TTL = 60.0  # seconds; a book's figures move only when one of its trades closes


_BACKTEST_CHECKS: Dict[Tuple[int, Tuple[int, ...]], Tuple[float, Dict[int, List[Dict]]]] = {}


def _backtest_checks(cur, uid: int, strategies: Dict[int, Dict],
                     memo: Optional[book_memo.BookMemo] = None) -> Dict[int, List[Dict]]:
    """{strategy_id: [one comparison per book]} (services.backtest_check) for {strategy_id: a row with
    the strategy's spec and result}: each book's realized per-trade P&L and win rate against the
    strategy's backtest, never summed across books. A per-user TTL cache, since the Deploy board
    polls; display only."""
    if not strategies:
        return {}
    key = (uid, tuple(sorted(strategies)))
    hit = _BACKTEST_CHECKS.get(key)
    if hit and time.time() - hit[0] < BACKTEST_CHECK_TTL:
        return hit[1]
    # The Deploy board's sums for every strategy it lists are kept (book_memo); one strategy's are cheap.
    stats = (book_memo.book_trade_stats(memo, list(strategies)) if memo is not None
             else repo.book_trade_stats(cur, uid, list(strategies)))
    val = {sid: backtest_check.checks(stats.get(sid, {}), s.get("result"),
                                      ((s.get("spec") or {}).get("sizing") or {}).get("stake"))
           for sid, s in strategies.items()}
    if len(_BACKTEST_CHECKS) > 5000:
        _BACKTEST_CHECKS.clear()
    _BACKTEST_CHECKS[key] = (time.time(), val)
    return val


def what_if(ctx: Ctx):
    s = _owned_strategy(ctx)
    if specmod.has_perpetual_market(s["spec"], s.get("market")):
        raise ApiError(409, "Bitcoin perpetual research uses fixed scenario costs; binary slippage controls do not apply.")
    if s["status"] == "rejected":
        raise ApiError(409, "This hypothesis was rejected in-sample; there is no full backtest to vary.")
    # Default the slippage knob to the real demo-book slippage measured for this
    # market (clamped to the knob's bounds), so omitting it scores against the
    # measured cost rather than 0. The frontend still sends the dial's value.
    measured = kalshi_dev.measured_slippage_cents(s["market"])
    default_slip = 0.0 if measured is None else max(0.0, min(5.0, measured))
    # An older or seeded spec stored without sizing is sized as validation sizes a new one: the
    # $5 x 20 default its strategy page's spec already shows (the page sends no stake for it). It
    # used to answer "stake must be a number", or fail in the backtest and say the data was
    # unavailable. A spec with its sizing set is passed on untouched.
    spec, sizing = s["spec"], _spec_sizing(s)
    if not all(k in sizing for k in specmod.DEFAULT_SPEC["sizing"]):
        spec = {**spec, "sizing": {**specmod.DEFAULT_SPEC["sizing"], **sizing}}
    w = backtest.WhatIf(
        fee_multiplier=_num(ctx.body, "fee_multiplier", 0.0, 3.0, 1.0),
        slippage_cents=_num(ctx.body, "slippage_cents", 0.0, 5.0, default_slip),
        stake=_num(ctx.body, "stake", 1.0, 500.0, spec["sizing"]["stake"]),
    )
    try:
        res = backtest.evaluate(spec, backtest.dataset(s["market"]), w)
    except Exception:
        raise ApiError(503, "Backtest data is not available right now.")
    return {k: res[k] for k in ("in_sample", "out_of_sample", "equity", "gates", "passed", "capital")}


def _no_dev_curve(s: Dict) -> Optional[str]:
    """Why a strategy has no demo replay to draw, or None when it has one."""
    if specmod.has_perpetual_market(s["spec"], s.get("market")):
        return "Bitcoin perpetuals are research-only; event-contract demo replay is unavailable."
    if not (s.get("result") or {}).get("out_of_sample"):
        return "This hypothesis has no out-of-sample backtest to replay."
    return None


# Passed strategies a session page warms at once (kalshi_dev.warm replays them one after another).
WARM_DEV_CURVES = 3


def warm_dev_curves(strategies: List[Dict]) -> None:
    """Start the demo replay of a session's passed strategies in the background as they show up on
    its page, so the one the user opens next draws its second line from memory."""
    kalshi_dev.warm([(s["id"], s["spec"], s["market"]) for s in strategies
                     if s["status"] == "passed" and _no_dev_curve(s) is None][:WARM_DEV_CURVES])


def strategy_dev_curve(ctx: Ctx):
    """Realized out-of-sample curve replayed READ-ONLY against the Kalshi DEMO
    (dev) environment, for the sim-vs-real second line on the equity chart.
    Degrades to {"dev_curve": None} (no second line) when dev replay is
    unconfigured or the demo host/data is unavailable - it never errors the page."""
    s = _owned_strategy(ctx)
    reason = _no_dev_curve(s)
    if reason:
        return {"dev_curve": None, "reason": reason}
    out = kalshi_dev.dev_curve_for_strategy(s["id"], s["spec"], s["market"])
    if out is None:
        return {"dev_curve": None, "reason": kalshi_dev.unavailable_reason()}
    return out
