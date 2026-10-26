"""Shared presenters for the web layer: figures more than one page shows (open money, live cash,
gate lines), so app.server and the route modules in app.web.routes compute them one way. Moved
verbatim from app.server, which re-imports every name."""
from __future__ import annotations

from typing import Dict, List

from app import repository as repo
from app.adapters.kalshi import kalshi_account
from app.services import gate_explain


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
