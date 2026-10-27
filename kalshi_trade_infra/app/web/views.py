"""Shared presenters for the web layer: figures more than one page shows (open money, live cash,
gate lines, the billing gate, a run's wait), so app.server and the route modules in app.web.routes compute them one way. Moved
verbatim from app.server, which re-imports every name."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

from app import repository as repo
from app import worker
from app.adapters.kalshi import kalshi_account
from app.adapters.stripe import billing
from app.services import customer_text, gate_explain
from app.trading.markets import MARKETS
from app.web.http import ApiError, Ctx
from trading_core.domain.money import cents, exact


_LEDGER_PLACE = Decimal("0.000001")  # app_credit_ledger.amount_usd is DECIMAL(14,6)


def credit_cents(v) -> Decimal:
    """A credits figure to the cent, rounded half up from its exact decimal: the one rounding every
    page that shows credits uses (Billing, the autopilot panel, the dashboard, a session's cost), so
    one $0.105 charge reads $0.11 everywhere. Python's round() works on the binary float and said
    $0.10. A float summed in Python carries noise past the ledger's six places (0.10499999999999998),
    so it is first put back on those places. Never applied to a stored amount."""
    return Decimal(str(v or 0)).quantize(_LEDGER_PLACE, rounding=ROUND_HALF_UP).quantize(billing.CENT, rounding=ROUND_HALF_UP)


def credit_usd(v) -> float:
    """credit_cents as the float a JSON answer carries (never -0.0)."""
    return float(credit_cents(v)) + 0.0


def credit_exact(v) -> float:
    """A balance as the ledger holds it (six places, no float noise), for a figure the page compares
    as well as shows: the page rounds it half up to the cent, as credit_cents does. Rounding it to
    four places first could round twice (0.10496 -> 0.105 -> $0.11 beside Billing's $0.10)."""
    return float(Decimal(str(v or 0)).quantize(_LEDGER_PLACE, rounding=ROUND_HALF_UP)) + 0.0


def _open_cost(open_pos: List[Dict], mode: str) -> Decimal:
    """What one mode's open positions cost (contracts x entry price), exactly."""
    return sum((Decimal(str(p["qty"])) * Decimal(str(p["entry_price"])) for p in open_pos if p["mode"] == mode), Decimal(0))


def _open_cost_with_fees(open_pos: List[Dict], mode: str) -> Decimal:
    """What one mode's open positions cost with their entry fees (contracts x entry price + entry fee),
    exactly: each position's "Cost + fee" on Deploy and the strategy page, summed before rounding."""
    return sum((Decimal(str(p["qty"])) * Decimal(str(p["entry_price"])) + Decimal(str(p.get("entry_fee") or 0))
                for p in open_pos if p["mode"] == mode), Decimal(0))


def _open_book(open_pos: List[Dict], mode: str) -> Dict:
    """One mode's open positions: how many and what they cost. `open_cost` is with the entry fees, the
    basis every page names a position's cost on (Deploy's and the strategy page's "Cost + fee");
    `open_at_cost` is before them, the part paper's balance counts (the fee is already spent). The
    dashboard and Funds both read this, so the two pages show the same open money to the cent. Display
    only: nothing stored or summed into P&L changes."""
    return {"open_at_cost": cents(_open_cost(open_pos, mode)),
            "open_cost": cents(_open_cost_with_fees(open_pos, mode)),
            "open_positions": sum(1 for p in open_pos if p["mode"] == mode)}


def _paper_equity(balance: float, open_pos: List[Dict]) -> Decimal:
    """Paper equity, exactly: the ledger's cash plus the open paper positions at cost. The dashboard
    and Funds round this once (cents); cash and cost rounded first and then added could miss by a cent."""
    return exact(balance) + _open_cost(open_pos, "paper")


# A page's follow-up cash read (/api/funds/cash) asks Kalshi once a memo is no longer kept (memo_kept), so
# the read a poll marked pending fetches a fresh figure, not the memo's last few seconds.
FOLLOW_UP_TTL = kalshi_account._BALANCE_TTL - kalshi_account.KEPT_MARGIN


def _live_balance(cur, uid: int, ttl: float = FOLLOW_UP_TTL) -> Dict:
    """The user's REAL Kalshi cash (cached, best-effort) + where to deposit. We can't mint
    real money, so an unconnected key or a failed fetch degrades to a connect/unavailable
    state. The live key is never logged or echoed — only the resulting balance is surfaced.
    May wait on Kalshi (one read per user at a time, kalshi_account.single_flight): only the page's
    follow-up asks it; the dashboard's and Funds' own reads take the memo (funds.kalshi_cash). Display only."""
    key = repo.get_kalshi_key(cur, uid)
    out = {"connected": key is not None, "balance": None, "funding_url": kalshi_account.KALSHI_FUNDING_URL}
    if key is not None:
        try:
            out["balance"] = kalshi_account.balance_cached(uid, kalshi_account.credentials_from_row(uid, key), ttl)
        except Exception:
            out["balance"] = None
        if out["balance"] is not None:
            out["balance_at"] = kalshi_account.balance_read_at(uid)  # the figure is up to a minute old
    return out


def _demo_cash(cur, uid: int, ttl: Optional[float] = None) -> Optional[float]:
    """The demo account's cash, the cached demo GET (demo_twins.balance_cached, at most `ttl` old, its own
    minute by default), with one demo read per user at a time (kalshi_account.single_flight): pages that
    miss the memo together share it. Display only: the demo-copy sync reads the demo cash its own way."""
    from app.trading import demo_twins

    ttl = demo_twins.BALANCE_TTL if ttl is None else ttl
    hit = demo_twins._BALANCE_CACHE.get(uid)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    return kalshi_account.single_flight(("demo", uid), lambda: demo_twins.balance_cached(cur, uid, ttl))


def _gate_lines(fn, *args) -> List[Dict]:
    """services.gate_explain's per-gate lines, or none: a record it can't read never fails the page."""
    try:
        return fn(*args)
    except (TypeError, ValueError, KeyError, AttributeError):
        return []


def _with_gate_lines(events: List[Dict]) -> List[Dict]:
    """Each verdict event gains `why_failed`: one plain line per gate it missed (measured, needed,
    what to try next), from the numbers the event already carries, and `note`: a plain sentence
    the page shows in place of a message written for the ledger ("gatekeeper-held
    (classification=...)", "Lead scan: control arm"). The model tiering line's internal model id
    is dropped: the page never shows one. A step or done line the agent wrote in the ledger's terms
    gains `note` too (gate_explain.step_note). Display only; no extra read."""
    for ev in events:
        if ev.get("kind") == "verdict":
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            data.pop("screen_model_id", None)
            data["why_failed"] = _gate_lines(gate_explain.for_event, ev.get("message"), data)
            try:
                data["note"] = gate_explain.event_note(ev.get("message"), data)
            except (TypeError, ValueError, KeyError, AttributeError):
                data["note"] = None
            ev["data"] = data
        elif ev.get("kind") in ("step", "done"):
            # The agent's step lines in plain words ("Froze 2 finalists; ... validation budget" read as jargon).
            note = gate_explain.step_note(ev.get("kind"), ev.get("message"))
            if note:
                data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                data["note"] = note
                ev["data"] = data
    return events


# The engine pauses a demo deployment with this in its reason when the user has no demo key.
_DEMO_KEY_PAUSE = "demo (sandbox) key"


# _demo_health's answer when it would have to ask Kalshi for the demo cash and was told not to: unknown yet.
DEMO_HEALTH_PENDING = "pending"


# A demo cash memo past its window but read less than this long ago (seconds) still answers a page's demo check,
# marked pending so the page asks /api/funds/cash?book=demo for a fresh figure meanwhile: the poll that finds the
# memo only just run out keeps the line it showed a moment ago, instead of dropping it until the follow-up is in.
# The pages draw a pending Kalshi cash the same way while its last figure is under this age (cashFig, both bundles).
RECENT_ENOUGH = 120.0


class _NoCash(Exception):
    """The demo cash a check needs isn't in the memo (or is too old to stand in), and Kalshi isn't asked."""


def _demo_health(cur, uid: int, deps: List[Dict], stake: Optional[float] = None):
    """Why the demo book can't trade, as one plain line and the one thing to do, or None when nothing
    known stops it. A demo deployment looks healthy (running, capital, a P&L) while every order it
    sends is refused, so the pages that show demo say this instead:
      - demo_key: a demo deployment is on (or the engine paused it for the key) and no demo key is saved;
      - demo_funds: the Kalshi demo account holds less than one stake, so Kalshi refuses its orders.
    `deps` are deployment rows (with spec). `stake` asks about a strategy that could go on demo but
    isn't there yet (the strategy page's next rung), so funds are checked even with nothing running.
    Unknown cash is never a problem. It never waits on Kalshi: when the demo cash memo isn't kept it answers
    DEMO_HEALTH_PENDING. The pages read demo_health_memo, which also keeps a line from a figure read under
    RECENT_ENOUGH ago. Display only: nothing that gates or sizes an order reads this."""
    health, pending = demo_health_memo(cur, uid, deps, stake, recent=0.0)
    return DEMO_HEALTH_PENDING if pending else health


def demo_health_memo(cur, uid: int, deps: List[Dict], stake: Optional[float] = None,
                     recent: float = RECENT_ENOUGH) -> Tuple[Optional[Dict], bool]:
    """_demo_health from the demo cash memo alone, never Kalshi, as every page read takes it (the dashboard,
    the autopilot status, the Deploy board and the strategy page, whoever asks: the shell, a visit, a poll):
    (health, pending). `pending`: the check needs the demo cash and the memo isn't kept, so the page asks
    /api/funds/cash?book=demo and reads again, once. Meanwhile a figure read under `recent` seconds ago
    answers the check, so a line shown a moment ago stays up; with none, or an older one, health is None
    (never a "Demo isn't trading" from an unknown figure) until the follow-up is in. Display only."""
    from app.trading import demo_twins

    pending = False

    def cash() -> Optional[float]:
        nonlocal pending
        if demo_twins.balance_kept(uid):
            hit = kalshi_account.memo_peek(demo_twins._BALANCE_CACHE, uid)
            if hit is not None:
                return hit[0]
        pending = True
        last = demo_twins._BALANCE_CACHE.get(uid)
        if last and time.monotonic() - last[0] < recent:
            return last[1]
        raise _NoCash

    try:
        health = _health_from(cur, uid, deps, stake, cash)
    except _NoCash:
        return None, True
    return health, pending


def _health_from(cur, uid: int, deps: List[Dict], stake: Optional[float], cash_read) -> Optional[Dict]:
    """_demo_health's line, with the demo cash from cash_read(), asked only when a stake needs it."""
    from app.trading import demo_twins

    demo = [d for d in deps if d["mode"] == "demo"]
    active = [d for d in demo if d["status"] == "running"
              or (d["status"] == "paused" and _DEMO_KEY_PAUSE in (d.get("status_reason") or ""))]
    if not active and stake is None:
        return None
    if repo.get_kalshi_dev_key(cur, uid) is None:
        if not active:
            return None  # nothing on demo; the deploy button already says to add the key
        return {"code": "demo_key", "need": "your Kalshi demo key",
                "line": "Demo isn't trading: your Kalshi demo key isn't connected. Add it on the Funds page.",
                "action": {"label": "Add demo key", "href": "/funds#connect-kalshi"}}
    stakes = [float(_spec_sizing(d)["stake"]) for d in active
              if d["status"] == "running" and _spec_sizing(d).get("stake") is not None]
    if stake is not None:
        stakes.append(float(stake))
    if not stakes:
        return None
    cash = cash_read()
    least = min(stakes)
    if cash is None or cash >= least:
        return None
    has = "has $0.00" if cash < 0.005 else "has %s, less than one %s stake" % (_usd(cash), _usd(least))
    return {"code": "demo_funds", "need": "demo funds: your Kalshi demo account %s" % has,
            "line": "Demo isn't trading: your Kalshi demo account %s. Add demo funds on Kalshi's demo site." % has,
            "action": {"label": "Open Kalshi demo", "href": demo_twins.KALSHI_DEMO_SITE}}


def _spec_sizing(row: Dict) -> Dict:
    """A strategy or deployment row's spec sizing, {} when an older or seeded spec has none (display only)."""
    spec = row.get("spec")
    sizing = spec.get("sizing") if isinstance(spec, dict) else None
    return sizing if isinstance(sizing, dict) else {}


def _usd(v: float) -> str:
    return "$%s" % format(round(float(v), 2), ",.2f")


def _demo_key_back(cur, uid: int, deps: List[Dict]) -> bool:
    """True when a demo deployment is paused for a missing demo key and the key is connected now. The
    engine leaves it paused once the key is added, and its row still said to add the key, beside a
    Funds page saying it is connected. Reads the key only when such a deployment is listed."""
    if not any(d["mode"] == "demo" and d["status"] == "paused" and _DEMO_KEY_PAUSE in (d.get("status_reason") or "")
               for d in deps):
        return False
    return repo.get_kalshi_dev_key(cur, uid) is not None


def _paper_books(deps: List[Dict]) -> Dict[int, str]:
    """{strategy_id: "running" | "paused"} for each strategy with a paper deployment that isn't stopped
    (running when any of them runs): what a demo copy the demo-copy sync paused is waiting on."""
    out: Dict[int, str] = {}
    for d in deps:
        if d["mode"] == "paper" and d["status"] in ("running", "paused"):
            out[d["strategy_id"]] = "running" if d["status"] == "running" or out.get(d["strategy_id"]) == "running" else "paused"
    return out


def _demo_copy_pause(d: Dict, paper_books: Optional[Dict[int, str]]) -> Optional[Tuple[str, Optional[str]]]:
    """(why, resume_block) for a demo deployment the demo-copy sync paused (app.trading.demo_twins), or
    None for any other row. The sync stores PAUSE_REASON ("... so the demo copy stopped too") and matches
    those exact words to resume the copy once its paper deployment runs again, so the stored text stays
    and its row says it here: paused, not stopped, and what it waits on. While the sync is on and the
    paper deployment isn't running, Resume would only be paused again at the sync's next pass, so
    `resume_block` says what to do first and the page offers Resume disabled. `paper_books` is
    _paper_books of the deployments the page read (None: unknown, so nothing is claimed about paper).
    Display only: the sync, the resume route and the stored reason are unchanged."""
    from app.trading import demo_twins

    if d["mode"] != "demo" or d["status"] != "paused" or (d.get("status_reason") or "").strip() != demo_twins.PAUSE_REASON:
        return None
    paper = None if paper_books is None else paper_books.get(d["strategy_id"], "none")
    if paper is None or not demo_twins.DEMO_TWINS:
        return "Its paper deployment wasn't running, so this demo copy paused with it", None
    if paper == "running":
        return "Its paper deployment wasn't running when this paused. It is now, so you can resume it", None
    if paper == "paused":
        return ("Waiting on its paper deployment, which is paused. Resume that one and this copy resumes with it",
                "Resume its paper deployment first: this demo copy resumes with it.")
    return ("Waiting to run on paper again: a demo copy runs only while its paper deployment does",
            "Deploy it on paper first: this demo copy resumes with its paper deployment.")


def _deployment_out(d: Dict, curve: List, unrealized: Optional[float] = None, paper_sids: Optional[set] = None,
                    demo_key_back: bool = False, paper_books: Optional[Dict[int, str]] = None) -> Dict:
    res = d.get("result") or {}
    copy_pause = _demo_copy_pause(d, paper_books)
    return {
        # A demo deployment of a strategy that is also on paper is its demo copy (app.trading.demo_twins makes
        # them): the row says what it copies and why its fills differ from paper's.
        "demo_copy": d["mode"] == "demo" and d["strategy_id"] in (paper_sids or ()),
        "id": d["id"], "strategy_id": d["strategy_id"], "title": d["title"], "direction": d["direction"],
        "market": d["market"], "mode": d["mode"], "status": d["status"], "status_reason": d["status_reason"],
        "status_why": copy_pause[0] if copy_pause else _status_why(d, demo_key_back),
        # Why Resume is offered disabled (a demo copy waiting on its paper deployment), or None.
        "resume_block": copy_pause[1] if copy_pause else None,
        "realized_pnl": cents(d["realized_pnl"]), "closed_trades": d["closed_trades"], "wins": d["wins"],
        "unrealized_pnl": unrealized, "open_positions": d["open_positions"], "created_at": d["created_at"], "curve": curve,
        "stake": _spec_sizing(d).get("stake"), "max_positions": _spec_sizing(d).get("max_positions"),
        "backtest": {"out_of_sample": res.get("out_of_sample"), "capital": res.get("capital")},
    }


def _realized_by_book(listed: List[Dict], removed: List[Dict]) -> Dict[str, Dict]:
    """{book: its realized P&L as the Deploy board names it}, for each book with a deployment listed or
    removed: `listed` (the deployments the board lists), `removed` and `removed_deployments` (the ones it
    no longer lists; book_memo.removed_deployments), and for paper and live `all`, the two together.
    Every closed position belongs to one deployment, so `all` is the dashboard's all-time figure for that
    book, to the cent (summed exactly, then rounded once, as the dashboard's one SUM is). Demo's
    dashboard figure counts from its last reload, so demo has no `all`. Books are never summed together.
    The board's "Realized" summed only the listed rows and didn't say so, beside a larger dashboard figure."""
    def total(rows: List[Dict]) -> Decimal:
        return sum((Decimal(str(r.get("realized_pnl") or 0)) for r in rows), Decimal(0))

    out: Dict[str, Dict] = {}
    for mode in ("paper", "demo", "live"):
        ls, rs = [d for d in listed if d["mode"] == mode], [r for r in removed if r["mode"] == mode]
        if not ls and not rs:
            continue
        a, b = total(ls), total(rs)
        book = {"listed": cents(a), "removed": cents(b), "removed_deployments": len(rs)}
        if mode != "demo":
            book["all"] = cents(a + b)
        out[mode] = book
    return out


def _past_deployment_out(r: Dict) -> Dict:
    """A removed deployment as its strategy page lists it: book, dates and realized P&L (display only)."""
    return {"id": r["id"], "mode": r["mode"], "created_at": r["created_at"], "removed_at": r["removed_at"],
            "realized_pnl": cents(r.get("realized_pnl")),
            "closed_trades": int(r.get("closed_trades") or 0)}


# The engine's loss guard pause (engine.loss_guard): "Lost $12.40, more than the $10.00 guard (...)".
_LOSS_GUARD = re.compile(r"^Lost \$[\d,]+\.\d\d, more than the \$([\d,]+\.\d\d) guard")


def _status_why(d: Dict, demo_key_back: bool = False) -> Optional[str]:
    """Why a deployment isn't running, in plain words, for its row and its strategy page. The stored
    reason read "By you", "Kill switch" or an engine line ("force-closed: position down 33.0% >= stop
    30.0%") after the stake, and "By you" didn't say whether you paused it or removed it. A reason
    that is already a sentence is kept as written, with what Resume does where the reason alone
    misleads: a demo key that is connected now (`demo_key_back`, from _demo_key_back), or a loss guard
    its lifetime realized P&L is still past (the guard sums every closed trade after each decision, so
    a resumed deployment pauses again at its next check). Display only."""
    raw = (d.get("status_reason") or "").strip()
    if d.get("status") == "running" or not raw:
        return None
    if raw == "By you" and d.get("status") == "stopped":
        return "You removed it"
    if d.get("status") == "paused" and demo_key_back and _DEMO_KEY_PAUSE in raw:
        return "Your Kalshi demo key wasn't connected when it paused. It is now, so you can resume it"
    if raw not in ("By you", "Approved agent proposal", "Kill switch") and not re.search(r"% >= (?:stop|limit) ", raw):
        why = customer_text.clean(raw, "Stopped automatically" if d.get("status") == "stopped" else "Paused automatically")
        guard = _LOSS_GUARD.match(raw)
        if (guard and d.get("status") == "paused" and d.get("realized_pnl") is not None
                and float(d["realized_pnl"]) < -float(guard.group(1).replace(",", ""))):
            why = why.rstrip(".") + ". Its loss is still past that guard, so Resume would pause it again at its next check"
        return why
    clause = _pause_clause(raw)
    return clause[:1].upper() + clause[1:]


def _gate_tints(status: Optional[str], exp: Dict) -> Dict:
    """services.gate_explain's per-figure pass/fail, or none (every figure neutral) for a record it can't read."""
    try:
        return gate_explain.strategy_tints(status, exp)
    except (TypeError, ValueError, KeyError, AttributeError):
        return {}


def _plain_pause_reason(why: str) -> str:
    """The engine's pause reason in plain words, for the phone panel."""
    from app.trading import demo_twins

    why = (why or "").strip()
    if why == demo_twins.PAUSE_REASON:  # stored as "... the demo copy stopped too", but it is paused (_demo_copy_pause)
        return "its paper deployment wasn't running, so its demo copy paused with it"
    m = re.search(r"position down ([\d.]+)% >= stop ([\d.]+)%", why)
    if m:
        return "its safety stop sold a position that had lost %.0f%% of its cost" % float(m.group(1))
    m = re.search(r"drawdown ([\d.]+)% >= limit ([\d.]+)%", why)
    if m:
        return "it lost %.0f%% of its money, past its %.0f%% limit" % (float(m.group(1)), float(m.group(2)))
    if why.lower().startswith("lost $"):
        return "it hit its loss guard"
    return (customer_text.clean(why, "") or "").rstrip(".")[:120] or "it was paused"


def _pause_clause(raw: Optional[str]) -> str:
    """Why a deployment is paused, as the end of a sentence."""
    raw = (raw or "").strip()
    return {"By you": "you paused it", "Approved agent proposal": "you approved the agent's proposal to pause it",
            "Kill switch": "you pressed Kill"}.get(raw) or _plain_pause_reason(raw)


def _start_of_day_utc() -> datetime:
    return repo.now_utc().replace(hour=0, minute=0, second=0)


def _needs_card(ctx: Ctx, reads: Optional[billing.Reads] = None) -> bool:
    """True when payments are live but the user has no card on file. Agent usage
    is metered per token, so we require a card before any run — the free credits
    unlock the moment one is saved."""
    if not billing.configured():
        return False
    cust = (reads or billing.Reads(ctx.cur, ctx.uid)).customer()
    return not (cust and cust.get("default_pm_id"))


def _auto_reload_terms(ctx: Ctx, reads: Optional[billing.Reads] = None) -> Optional[Dict]:
    """What auto-reload will charge the saved card, for the autopilot card's cost line: the credits
    added, the card charge (credits plus the top-up fee) and the balance that triggers it. The same
    floors billing.auto_reload applies. None when payments are off, no card is saved, or it is off."""
    if not billing.configured():
        return None
    cust = (reads or billing.Reads(ctx.cur, ctx.uid)).customer()
    if not (cust and cust.get("default_pm_id") and cust.get("auto_reload")):
        return None
    amount = max(billing.AUTORELOAD_AMOUNT, Decimal(str(cust.get("reload_amount") or billing.AUTORELOAD_AMOUNT)))
    threshold = max(billing.AUTORELOAD_THRESHOLD, Decimal(str(cust.get("reload_threshold") or billing.AUTORELOAD_THRESHOLD)))
    return {"amount": float(amount), "charge": billing.topup_charge_cents(amount) / 100, "threshold": float(threshold)}


def _require_billing_ready(ctx: Ctx, gerund: str) -> None:
    if _needs_card(ctx):
        raise ApiError(402, "Add a payment method on the Billing tab before %s. Your $%d in free credits "
                            "unlock the moment a card is on file — you won't be charged until they run out."
                            % (gerund, int(billing.FREE_BONUS)))
    if billing.configured() and repo.credit_balance(ctx.cur, ctx.uid) <= 0:
        raise ApiError(402, "You're out of credits. Add credits on the Billing tab to keep %s." % gerund)


# A queued or silent run reads as overdue once it passes the reaper's limit (worker.ABANDONED_AFTER,
# TAU_RUN_ABANDONED_SECONDS): a running run that hasn't beaten for that long is one the reaper stops,
# and a queued run is never reaped, so without this a backed-up or dead worker showed a spinner forever.
RUN_OVERDUE_SECONDS = int(worker.ABANDONED_AFTER.total_seconds())


def _silent_before() -> datetime:
    """A running run whose last beat is older than this has gone quiet past the reaper's limit."""
    return repo.now_utc() - timedelta(seconds=RUN_OVERDUE_SECONDS)


def _run_wait(run: Optional[Dict]) -> Optional[Dict]:
    """How long a run has been waiting for a worker, or silent while running: {"state": "queued" |
    "silent", "seconds": n, "overdue": bool}. A queued run always reports its wait, measured from its
    last re-queue (heartbeat_at) or its creation; a running one only once its heartbeat is overdue.
    None for anything else."""
    if not run:
        return None
    if run.get("status") == "queued":
        since, state = run.get("heartbeat_at") or run.get("created_at"), "queued"
    elif run.get("status") == "running":
        since, state = run.get("heartbeat_at") or run.get("started_at"), "silent"
    else:
        return None
    if not isinstance(since, datetime):
        return None
    age = (repo.now_utc() - since).total_seconds()
    secs = max(0, int(age))
    overdue = age > RUN_OVERDUE_SECONDS  # the same line _silent_before draws for the counts, to the second
    if state == "silent" and not overdue:
        return None
    return {"state": state, "seconds": secs, "overdue": overdue}


def session_title(prompt: Optional[str], market: Optional[str]) -> Optional[str]:
    """What a research session's list row, page and billing line name it when its prompt is not words
    for the customer: the autopilot's research floor (worker.RESEARCH_FLOOR_IDEA) starts its sessions
    with an instruction to the agent, so a phone's first screen read "Research floor: no research
    started for a while, so pick the most promising angle ..." over every such session. None for any
    other prompt (the page shows the idea as typed). The prompt itself is unchanged: the agent reads it."""
    if (prompt or "").strip() != worker.RESEARCH_FLOOR_IDEA:
        return None
    m = MARKETS.get(market or "")
    return "New idea picked by the autopilot for %s" % (m.label if m else "the market it picks")
