"""Credits ledger and Stripe customer SQL (usage billing)."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from app.adapters.db.sql import now_utc


def credit_balance(cur, user_id: int) -> float:
    cur.execute("SELECT COALESCE(SUM(amount_usd),0) AS b FROM app_credit_ledger WHERE user_id=%s", (user_id,))
    return float(cur.fetchone()["b"])


def add_credit(cur, user_id: int, kind: str, amount_usd, memo: str,
               stripe_ref: Optional[str] = None, run_id: Optional[int] = None) -> bool:
    """Append a credit ledger row. Returns False if a row with this stripe_ref
    already exists (idempotent replay), True if inserted."""
    try:
        cur.execute(
            """INSERT INTO app_credit_ledger (user_id, kind, amount_usd, memo, stripe_ref, run_id, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (user_id, kind, str(amount_usd), (memo or "")[:255], stripe_ref, run_id, now_utc()),
        )
        return True
    except Exception as e:  # duplicate stripe_ref -> already credited
        if "uq_credit_stripe" in str(e) or "Duplicate" in str(e):
            return False
        raise


def credit_rows(cur, user_id: int, limit: int = 50) -> List[Dict]:
    cur.execute(
        "SELECT kind, amount_usd, memo, created_at FROM app_credit_ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return cur.fetchall()


def credit_spent_total(cur, user_id: int, since=None) -> float:
    """Usage spend in dollars, all time or since `since` (the billing page's runway)."""
    sql = "SELECT COALESCE(-SUM(amount_usd),0) AS s FROM app_credit_ledger WHERE user_id=%s AND kind='usage'"
    params = (user_id,)
    if since is not None:
        sql += " AND created_at >= %s"
        params = (user_id, since)
    cur.execute(sql, params)
    return float(cur.fetchone()["s"])


def research_spent_since(cur, user_id: int, since) -> float:
    """Dollars actually debited for RESEARCH since `since` (the autopilot panel's week). Every usage
    row carries the run it billed (agent._bill), and the run's kind tells research from chat and
    autopilot reviews. The seeded demo session is left out, as research_week leaves it out."""
    cur.execute(
        """SELECT COALESCE(-SUM(l.amount_usd),0) AS s
           FROM app_credit_ledger l JOIN app_agent_runs r ON r.id = l.run_id
           WHERE l.user_id=%s AND l.kind='usage' AND l.created_at >= %s
             AND r.kind='research' AND (r.direction IS NULL OR r.direction <> 'random_walk')""",
        (user_id, since),
    )
    return float(cur.fetchone()["s"])


def runs_spent(cur, user_id: int, run_ids: Iterable[int]) -> Dict[int, float]:
    """Dollars actually debited for each run so far ({run_id: usd}; a run with no debit is absent),
    for the run page and the research list. One grouped read through idx_credit_run_kind."""
    ids = sorted({int(i) for i in run_ids if i is not None})
    if not ids:
        return {}
    cur.execute(
        "SELECT run_id, COALESCE(-SUM(amount_usd),0) AS s FROM app_credit_ledger "
        "WHERE run_id IN (" + ",".join(["%s"] * len(ids)) + ") AND kind='usage' AND user_id=%s GROUP BY run_id",
        tuple(ids) + (user_id,),
    )
    return {int(r["run_id"]): float(r["s"]) for r in cur.fetchall()}


def get_stripe_customer(cur, user_id: int) -> Optional[Dict]:
    cur.execute(
        "SELECT user_id, stripe_customer_id, default_pm_id, auto_reload, reload_amount, reload_threshold "
        "FROM app_stripe_customers WHERE user_id=%s",
        (user_id,),
    )
    return cur.fetchone()


def save_stripe_customer(cur, user_id: int, customer_id: str) -> None:
    cur.execute(
        """INSERT INTO app_stripe_customers (user_id, stripe_customer_id, created_at) VALUES (%s,%s,%s)
           ON DUPLICATE KEY UPDATE stripe_customer_id=VALUES(stripe_customer_id), default_pm_id=NULL""",
        (user_id, customer_id, now_utc()),
    )


def set_default_pm(cur, user_id: int, pm_id: Optional[str]) -> None:
    cur.execute("UPDATE app_stripe_customers SET default_pm_id=%s WHERE user_id=%s", (pm_id, user_id))


def set_auto_reload(cur, user_id: int, on: bool, amount=None, threshold=None) -> None:
    sets, params = ["auto_reload=%s"], [1 if on else 0]
    if amount is not None:
        sets.append("reload_amount=%s"); params.append(str(amount))
    if threshold is not None:
        sets.append("reload_threshold=%s"); params.append(str(threshold))
    params.append(user_id)
    cur.execute("UPDATE app_stripe_customers SET %s WHERE user_id=%%s" % ", ".join(sets), tuple(params))


def user_by_email(cur, email: str) -> Optional[Dict]:
    cur.execute("SELECT id, email, name FROM app_users WHERE email=%s", (email,))
    return cur.fetchone()
