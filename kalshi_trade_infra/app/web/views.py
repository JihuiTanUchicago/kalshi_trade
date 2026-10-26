"""Shared presenters for the web layer: figures more than one page shows (open money, live cash,
gate lines), so app.server and the route modules in app.web.routes compute them one way. Moved
verbatim from app.server, which re-imports every name."""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from app import repository as repo
from app.adapters.kalshi import kalshi_account
from app.services import customer_text, gate_explain


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
    is dropped: the page never shows one. Display only; no extra read."""
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
