"""Strategy routes: the strategies list and detail page, delete, share, what-if and the dev curve,
plus the per-strategy figures they show (cards, marks, experiment and phase blocks, backtest
checks). Moved verbatim from app.server, which re-imports every name for its route table."""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional, Tuple

from app import repository as repo
from app.adapters.kalshi import kalshi_dev
from app.research import research_repository as research_repo
from app.services import backtest_check, book_memo, gate_explain, trade_why
from app.trading import backtest, track_record
from app.trading import spec as specmod
from app.web.caches import _forget_own_change
from app.web.http import ApiError, Ctx, _int_param, _num
from app.web.views import (
    _deployment_out,
    _demo_health,
    _demo_key_back,
    _gate_lines,
    _gate_tints,
    _paper_books,
    _past_deployment_out,
    _spec_sizing,
)


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
    on a YES position, the YES ask on a NO one). None until the engine's first mark after entry."""
    qty = int(p["qty"])
    cost = qty * float(p["entry_price"]) + float(p.get("entry_fee") or 0)
    mark = p.get("mark_price")
    if mark is None:
        return {"mark": None, "value": None, "unrealized": None, "mark_ts": None}
    mark = float(mark)
    # A YES contract sells at the YES bid (mark); a NO contract at its own bid, 1 - yes_ask (1 - mark).
    value = round(qty * (mark if p["side"] == "yes" else 1.0 - mark), 2)
    return {"mark": mark, "value": value, "unrealized": round(value - cost, 2), "mark_ts": p.get("mark_ts")}


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
    # Default ("Kept") view hides rejected/void — the big-run noise — but keeps every row in the
    # DB (the ledger counts them for DSR/FDR). An explicit status chip overrides and shows it.
    hide_noise = status is None
    noise = sum(counts.get(s, 0) for s in repo.NOISE_STATUSES)
    # The seeded example's strategies are out of the counts but still listed (marked "example").
    ex = counts.get("examples") or {}
    shown_ex = ex.get(status, 0) if status else sum(n for s, n in ex.items() if s not in repo.NOISE_STATUSES)
    matched = (counts.get(status, 0) if status else counts["total"] - noise) + shown_ex
    rows = repo.list_strategies(ctx.cur, ctx.uid, direction, status, market, limit=per, offset=page * per,
                                q=search, deployed=deployed, hide_noise=hide_noise)
    cards = [_strategy_card(s) for s in rows]
    _attach_real_records(ctx.cur, ctx.uid, cards)
    _attach_past_records(ctx.cur, ctx.uid, cards, [s["id"] for s in rows if s.get("removed_deps")])
    return {"strategies": cards, "counts": counts,
            "matched": matched, "page": page, "per": per, "pages": (matched + per - 1) // per}


def _attach_real_records(cur, uid: int, cards: List[Dict]) -> None:
    """Stamp each deployed card with what it has actually done since deploying (realized P&L and
    closed trades across its active deployments), so the list shows reality next to the backtest.
    Money books are never summed: a strategy with a live deployment reports its live deployments
    only (beside its Live badge), otherwise its paper ones, with its demo (sandbox) book beside them
    under "demo" rather than added in. One query, and only when the page has a deployed strategy."""
    if not any(c.get("deployed") for c in cards):
        return
    real: Dict[int, Dict[str, Dict]] = {}
    for d in book_memo.deployments_for_display(book_memo.BookMemo(cur, uid)):
        r = real.setdefault(d["strategy_id"], {}).setdefault(d["mode"], {"pnl": 0.0, "trades": 0, "open": 0, "paused": False})
        r["paused"] = r["paused"] or d.get("status") == "paused"  # often auto-paused; the list flags it
        r["pnl"] += float(d["realized_pnl"] or 0)
        r["trades"] += int(d["closed_trades"] or 0)
        r["open"] += int(d["open_positions"] or 0)
    for c in cards:
        books = real.get(c["id"]) if c.get("deployed") else None
        if books:
            mode = next((m for m in ("live", "paper", "demo") if m in books), None)
            if mode is None:  # only a mode this list doesn't show
                continue
            r = books[mode]
            # Every book it runs in now, so the row's badge names them ("On paper + demo"), not "Deployed".
            c["books"] = [m for m in BOOK_ORDER if m in books]
            c["real"] = {**r, "pnl": round(r["pnl"], 2), "live": mode == "live", "mode": mode}
            if mode == "paper" and "demo" in books:
                dm = books["demo"]
                c["real"]["demo"] = {"pnl": round(dm["pnl"], 2), "trades": dm["trades"], "open": dm["open"]}


BOOK_ORDER = ("live", "paper", "demo")


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
            "pnl": round(float(r["pnl"] or 0), 2), "trades": int(r["trades"] or 0), "deployments": int(r["deployments"] or 0)}
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
    latest = lambda phase: next((r for r in reversed(results) if r.get("phase") == phase), None)
    val_row = latest("validation")
    val = _phase_block(val_row)
    hold = _phase_block(latest("holdout"), holdout=True)
    rat = _rationale(exp.get("economic_rationale"))
    overall = results[-1]["classification"] if results else None
    return {
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
        "holdout": hold,
        # Prefer the gatekeeper's recorded cross-day folds (validation phase); fall back to any
        # folds embedded in the older rationale JSON so pre-pipeline experiments still render.
        "folds": (val_row or {}).get("folds") or rat["folds"],
    }


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
    out.update(
        spec=s["spec"], rules=specmod.describe(s["spec"]), gates=res.get("gates"), dataset=res.get("dataset"),
        recent_trades=res.get("recent_trades"),
        # The backtest columns' "too few trades to tell skill from luck" caution (display only): the app's
        # one noise level for a trade count, deliberately stricter than the gate's floor, which it names.
        sample_caution={"min_trades": track_record.MIN_TRADES, "gate_min_oos_trades": backtest.GATES["min_oos_trades"]},
        experiment=exp,
        # One plain line per gate it missed: measured, needed, and what to try next (display only).
        why_failed=_gate_lines(gate_explain.for_strategy, s.get("status"), res, exp),
        deployments=[_deployment_out(d, [], demo_key_back=key_back, paper_books=_paper_books(deps)) for d in deps],
        # Its removed deployments, newest first: book, dates and realized P&L (they left the list above).
        past_deployments=[_past_deployment_out(r) for r in _removed_with_totals(ctx.cur, ctx.uid, s["id"])],
        holdings=[{
            "ticker": p["ticker"], "side": p["side"], "qty": int(p["qty"]), "mode": p["mode"],
            "entry_price": float(p["entry_price"]),
            "cost": round(int(p["qty"]) * float(p["entry_price"]) + float(p["entry_fee"] or 0), 2),
            "market_close_time": p["market_close_time"], **_mark_fields(p), "why": trade_why.trade_why(p, s["spec"]),
        } for p in held],
        # The Remove button's reason while any deployment of it still holds a position (delete_strategy's guard).
        delete_block=_delete_block(held),
        # The ladder's demo rung: why its demo book can't trade, or (not on demo yet) what demo needs.
        demo_health=None if specmod.has_perpetual_market(s["spec"], s.get("market")) else
        _demo_health(ctx.cur, ctx.uid, deps, stake=(s["spec"].get("sizing") or {}).get("stake")),
        # Each book's realized per-trade P&L against the backtest's, one line per book (display only).
        # The page shows them under its current deployments, so with none there is nothing to read.
        backtest_checks=_backtest_checks(ctx.cur, ctx.uid, {s["id"]: s}).get(s["id"], []) if deps else [],
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


def strategy_dev_curve(ctx: Ctx):
    """Realized out-of-sample curve replayed READ-ONLY against the Kalshi DEMO
    (dev) environment, for the sim-vs-real second line on the equity chart.
    Degrades to {"dev_curve": None} (no second line) when dev replay is
    unconfigured or the demo host/data is unavailable - it never errors the page."""
    s = _owned_strategy(ctx)
    if specmod.has_perpetual_market(s["spec"], s.get("market")):
        return {"dev_curve": None, "reason": "Bitcoin perpetuals are research-only; event-contract demo replay is unavailable."}
    if not (s.get("result") or {}).get("out_of_sample"):
        return {"dev_curve": None, "reason": "This hypothesis has no out-of-sample backtest to replay."}
    out = kalshi_dev.dev_curve_for_strategy(s["id"], s["spec"], s["market"])
    if out is None:
        return {"dev_curve": None, "reason": kalshi_dev.unavailable_reason()}
    return out
