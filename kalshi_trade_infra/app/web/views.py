"""Shared presenters for the web layer: figures more than one page shows (open money, live cash,
gate lines, the billing gate, a run's wait), so app.server and the route modules in app.web.routes compute them one way. Moved
verbatim from app.server, which re-imports every name."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

from app import repository as repo
from app import worker
from app.adapters.kalshi import kalshi_account
from app.adapters.stripe import billing
from app.services import customer_text, gate_explain
from app.web.http import ApiError, Ctx


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


def _open_book(open_pos: List[Dict], mode: str) -> Dict:
    """One mode's open positions: how many and what they cost (contracts x entry price). The dashboard
    and Funds both read this, so the two pages show the same open money to the cent."""
    pos = [p for p in open_pos if p["mode"] == mode]
    return {"open_at_cost": round(sum(float(p["qty"]) * float(p["entry_price"]) for p in pos), 2),
            "open_positions": len(pos)}


def _live_balance(cur, uid: int) -> Dict:
    """The user's REAL Kalshi cash (cached, best-effort) + where to deposit. We can't mint
    real money, so an unconnected key or a failed fetch degrades to a connect/unavailable
    state. The live key is never logged or echoed — only the resulting balance is surfaced."""
    key = repo.get_kalshi_key(cur, uid)
    out = {"connected": key is not None, "balance": None, "funding_url": kalshi_account.KALSHI_FUNDING_URL}
    if key is not None:
        try:
            out["balance"] = kalshi_account.balance_cached(uid, kalshi_account.credentials_from_row(uid, key))
        except Exception:
            out["balance"] = None
        if out["balance"] is not None:
            out["balance_at"] = kalshi_account.balance_read_at(uid)  # the figure is up to a minute old
    return out


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


def _demo_health(cur, uid: int, deps: List[Dict], stake: Optional[float] = None) -> Optional[Dict]:
    """Why the demo book can't trade, as one plain line and the one thing to do, or None when nothing
    known stops it. A demo deployment looks healthy (running, capital, a P&L) while every order it
    sends is refused, so the pages that show demo say this instead:
      - demo_key: a demo deployment is on (or the engine paused it for the key) and no demo key is saved;
      - demo_funds: the Kalshi demo account holds less than one stake, so Kalshi refuses its orders.
    `deps` are deployment rows (with spec). `stake` asks about a strategy that could go on demo but
    isn't there yet (the strategy page's next rung), so funds are checked even with nothing running.
    The balance read is the cached demo GET (demo_twins.balance_cached); unknown is never a problem."""
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
                "action": {"label": "Add demo key", "href": "/funds"}}
    stakes = [float(_spec_sizing(d)["stake"]) for d in active
              if d["status"] == "running" and _spec_sizing(d).get("stake") is not None]
    if stake is not None:
        stakes.append(float(stake))
    if not stakes:
        return None
    cash = demo_twins.balance_cached(cur, uid)
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


def _deployment_out(d: Dict, curve: List, unrealized: Optional[float] = None, paper_sids: Optional[set] = None) -> Dict:
    res = d.get("result") or {}
    return {
        # A demo deployment of a strategy that is also on paper is its demo copy (app.trading.demo_twins makes
        # them): the row says what it copies and why its fills differ from paper's.
        "demo_copy": d["mode"] == "demo" and d["strategy_id"] in (paper_sids or ()),
        "id": d["id"], "strategy_id": d["strategy_id"], "title": d["title"], "direction": d["direction"],
        "market": d["market"], "mode": d["mode"], "status": d["status"], "status_reason": d["status_reason"],
        "status_why": _status_why(d),
        "realized_pnl": round(float(d["realized_pnl"]), 2), "closed_trades": d["closed_trades"], "wins": d["wins"],
        "unrealized_pnl": unrealized, "open_positions": d["open_positions"], "created_at": d["created_at"], "curve": curve,
        "stake": _spec_sizing(d).get("stake"), "max_positions": _spec_sizing(d).get("max_positions"),
        "backtest": {"out_of_sample": res.get("out_of_sample"), "capital": res.get("capital")},
    }


def _status_why(d: Dict) -> Optional[str]:
    """Why a deployment isn't running, in plain words, for its row and its strategy page. The stored
    reason read "By you", "Kill switch" or an engine line ("force-closed: position down 33.0% >= stop
    30.0%") after the stake, and "By you" didn't say whether you paused it or removed it. A reason
    that is already a sentence is kept as written."""
    raw = (d.get("status_reason") or "").strip()
    if d.get("status") == "running" or not raw:
        return None
    if raw == "By you" and d.get("status") == "stopped":
        return "You removed it"
    if raw not in ("By you", "Approved agent proposal", "Kill switch") and not re.search(r"% >= (?:stop|limit) ", raw):
        return customer_text.clean(raw, "Stopped automatically" if d.get("status") == "stopped" else "Paused automatically")
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
    why = (why or "").strip()
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
