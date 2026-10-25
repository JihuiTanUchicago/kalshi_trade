"""Per-user settings: risk limits, execution config, and the autopilot plan, model and market focus."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from app.adapters.db.sql import _json, _loads


def user_risk_config(cur, user_id: int) -> Dict:
    """Per-user risk limits for the force-sell / portfolio-cap layer (conservative DB defaults)."""
    cur.execute(
        "SELECT drawdown_limit_pct, position_stop_pct, max_open_positions, max_open_notional "
        "FROM app_users WHERE id=%s",
        (user_id,),
    )
    return cur.fetchone()


def set_user_risk_config(cur, user_id: int, changes: Dict) -> None:
    """Update a user's risk controls. Only the three enforced columns are writable; callers
    (agent.act) pass already-clamped values, so this layer just persists them (DRY: one UPDATE,
    no business logic). Unknown keys are ignored so a bad agent action can't touch other columns."""
    cols = {k: changes[k] for k in ("drawdown_limit_pct", "max_open_positions", "max_open_notional") if k in changes}
    if not cols:
        return
    sql = "UPDATE app_users SET " + ", ".join("%s=%%s" % k for k in cols) + " WHERE id=%s"
    cur.execute(sql, [*cols.values(), user_id])


PLAN_KEYS = ("goals", "agenda", "deployments", "posture")


_PLAN_FIELD_MAX = 800   # chars per field; keeps the plan a bounded briefing, not a growing journal


def autopilot_plan(cur, user_id: int) -> Dict:
    """The autopilot's durable operating plan (goals/agenda/deployments/posture), or {} if none yet.
    Read by _copilot_context each review so reviews are coherent across time."""
    cur.execute("SELECT autopilot_plan FROM app_users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    plan = _loads((row or {}).get("autopilot_plan")) if row else None
    return plan if isinstance(plan, dict) else {}


def set_autopilot_plan(cur, user_id: int, plan: Dict) -> None:
    """Persist the review's updated operating plan. Only the four known string fields are kept and
    each is truncated, so the stored plan stays a small bounded briefing no matter what the model
    emits (a bad/huge value can't bloat the row or leak other keys)."""
    if not isinstance(plan, dict):
        return
    kept = {k: str(plan[k])[:_PLAN_FIELD_MAX] for k in PLAN_KEYS if plan.get(k)}
    cur.execute("UPDATE app_users SET autopilot_plan=%s WHERE id=%s", (_json(kept) if kept else None, user_id))


def set_autopilot_model(cur, user_id: int, model_key: Optional[str]) -> None:
    """Set the model the autopilot's own runs use (NULL = catalog default). The caller validates
    model_key against models_catalog so only a known key (or None) is ever stored."""
    cur.execute("UPDATE app_users SET autopilot_model=%s WHERE id=%s", (model_key or None, user_id))


def set_autopilot_focus(cur, user_id: int, tokens: Optional[List[str]]) -> None:
    """Store the user's market focus (validated by the caller); empty/None clears it."""
    cur.execute("UPDATE app_users SET autopilot_focus=%s WHERE id=%s",
                (json.dumps(tokens) if tokens else None, user_id))


def user_execution_config(cur, user_id: int) -> Dict:
    """Per-user execution-control overrides (NULL = use the global KALSHI_MAX_* env default).
    The live kernel factory reads this and falls back to env when a column is NULL."""
    cur.execute(
        "SELECT exec_max_book_fraction, exec_max_entry_spread, exec_max_order_notional FROM app_users WHERE id=%s",
        (user_id,),
    )
    return cur.fetchone() or {}


def set_user_execution_config(cur, user_id: int, changes: Dict) -> None:
    """Persist already-clamped per-user execution overrides (agent.act clamps to EXEC_BOUNDS)."""
    cols = {k: changes[k] for k in ("exec_max_book_fraction", "exec_max_entry_spread", "exec_max_order_notional") if k in changes}
    if not cols:
        return
    sql = "UPDATE app_users SET " + ", ".join("%s=%%s" % k for k in cols) + " WHERE id=%s"
    cur.execute(sql, [*cols.values(), user_id])
