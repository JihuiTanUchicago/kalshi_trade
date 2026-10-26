"""Credits ledger and Stripe customer SQL (usage billing)."""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

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
    """The newest ledger rows. A usage row also carries the kind of run it billed (`run_kind`:
    research, review, chat; NULL with no run) and whether the autopilot started it (`run_brief`),
    so Billing can say what each charge was for. Read through the run's primary key."""
    cur.execute(
        "SELECT l.kind, l.amount_usd, l.memo, l.created_at, l.run_id, l.stripe_ref, r.kind AS run_kind, "
        "r.brief AS run_brief FROM app_credit_ledger l LEFT JOIN app_agent_runs r ON r.id = l.run_id "
        "WHERE l.user_id=%s ORDER BY l.id DESC LIMIT %s",
        (user_id, limit),
    )
    return cur.fetchall()


def last_credit_at(cur, user_id: int, kind: str):
    """When the user's newest ledger row of one kind was written, or None (idx_credit_user_kind_time)."""
    cur.execute("SELECT MAX(created_at) AS t FROM app_credit_ledger WHERE user_id=%s AND kind=%s", (user_id, kind))
    row = cur.fetchone()
    return row["t"] if row else None


def credit_totals(cur, user_id: int, since) -> Dict[str, Dict[str, float]]:
    """Each ledger kind's all-time total and row count, and its total since `since`:
    {kind: {"all": usd, "n": rows, "since": usd, "n_since": rows}}. The kinds' "all" add up to
    credit_balance, so Billing can show how the balance came to be. One grouped read."""
    cur.execute(
        "SELECT kind, COUNT(*) AS n, COALESCE(SUM(amount_usd),0) AS s, "
        "COALESCE(SUM(CASE WHEN created_at >= %s THEN amount_usd ELSE 0 END),0) AS s_since, "
        "COALESCE(SUM(CASE WHEN created_at >= %s THEN 1 ELSE 0 END),0) AS n_since "
        "FROM app_credit_ledger WHERE user_id=%s GROUP BY kind",
        (since, since, user_id),
    )
    return {r["kind"]: {"all": float(r["s"]), "n": int(r["n"]), "since": float(r["s_since"]),
                        "n_since": int(r["n_since"])} for r in cur.fetchall()}


def credit_statement(cur, user_id: int, since, tz_minutes: int = 0, limit: int = 300) -> List[Dict]:
    """The ledger since `since` as statement lines, newest first: a usage row is one model call, so
    a session's calls on one day (the viewer's day, `tz_minutes` behind UTC as a browser's
    getTimezoneOffset says) with one model are one line, with their count, total, first and last
    time and the run they billed; every other row (credits bought, auto-reloads, grants) is its own
    line with its Stripe reference. Amounts are the ledger's own sums. One statement."""
    tz = int(tz_minutes)
    cur.execute(
        "SELECT g.kind, g.run_id, g.day, g.n, g.amount, g.first_at, g.last_at, g.memo, g.stripe_ref, "
        "r.kind AS run_kind, r.brief AS run_brief, r.prompt AS run_prompt, r.market AS run_market, "
        "r.direction AS run_direction FROM ("
        "(SELECT 'usage' AS kind, l.run_id, DATE(l.created_at - INTERVAL %s MINUTE) AS day, COUNT(*) AS n, "
        "SUM(l.amount_usd) AS amount, MIN(l.created_at) AS first_at, MAX(l.created_at) AS last_at, l.memo, "
        "NULL AS stripe_ref, MAX(l.id) AS last_id FROM app_credit_ledger l "
        "WHERE l.user_id=%s AND l.kind='usage' AND l.created_at >= %s "
        "GROUP BY l.run_id, DATE(l.created_at - INTERVAL %s MINUTE), l.memo) "
        "UNION ALL "
        "(SELECT l.kind, l.run_id, DATE(l.created_at - INTERVAL %s MINUTE), 1, l.amount_usd, l.created_at, "
        "l.created_at, l.memo, l.stripe_ref, l.id FROM app_credit_ledger l "
        "WHERE l.user_id=%s AND l.kind<>'usage' AND l.created_at >= %s) "
        "ORDER BY last_at DESC, last_id DESC LIMIT %s) g LEFT JOIN app_agent_runs r ON r.id = g.run_id "
        "ORDER BY g.last_at DESC, g.last_id DESC",
        (tz, user_id, since, tz, tz, user_id, since, int(limit)),
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


def usage_by_source(cur, user_id: int, since) -> Dict[str, float]:
    """Usage dollars since `since`, split by what spent them: research the user started
    ("research"), research the autopilot started ("autopilot_research", a brief run), autopilot
    check-ins ("autopilot_review"), chat ("chat") and anything else ("other"). The parts add up to
    credit_spent_total over the same window. One grouped read through idx_credit_user_kind_time."""
    cur.execute(
        "SELECT r.kind AS run_kind, COALESCE(r.brief, 0) AS brief, COALESCE(-SUM(l.amount_usd),0) AS s "
        "FROM app_credit_ledger l LEFT JOIN app_agent_runs r ON r.id = l.run_id "
        "WHERE l.user_id=%s AND l.kind='usage' AND l.created_at >= %s GROUP BY r.kind, COALESCE(r.brief, 0)",
        (user_id, since),
    )
    out = {"research": 0.0, "autopilot_research": 0.0, "autopilot_review": 0.0, "chat": 0.0, "other": 0.0}
    for r in cur.fetchall():
        out[_usage_key(r["run_kind"], r["brief"])] += float(r["s"])
    return out


def _usage_key(run_kind: Optional[str], brief) -> str:
    """usage_by_source's name for what a run of `run_kind` (None: no run) spent."""
    return (("autopilot_research" if int(brief or 0) else "research") if run_kind == "research"
            else "autopilot_review" if run_kind == "review" else "chat" if run_kind == "chat" else "other")


def credit_week(cur, user_id: int, since, balance: bool = False) -> Dict:
    """The autopilot panel's credit figures in one read of the ledger: {"research": research_spent_since,
    "by_source": usage_by_source, "spent": credit_spent_total, each over usage since `since`, and with
    `balance` "balance": credit_balance (None without)}. The usage rows are grouped once, by their run's
    kind, brief flag and whether it is the seeded example (research_spent_since leaves that out), and the
    balance rides the same statement. Sums stay Decimal until each figure is made, so every figure is
    the float its own read returned. Every part reads the ledger as it stands at this one statement."""
    sql = ("SELECT 'usage' AS part, r.kind AS run_kind, COALESCE(r.brief, 0) AS brief, "
           "COALESCE(r.direction = 'random_walk', 0) AS example, -SUM(l.amount_usd) AS s "
           "FROM app_credit_ledger l LEFT JOIN app_agent_runs r ON r.id = l.run_id "
           "WHERE l.user_id=%s AND l.kind='usage' AND l.created_at >= %s "
           "GROUP BY r.kind, COALESCE(r.brief, 0), COALESCE(r.direction = 'random_walk', 0)")
    params: Tuple = (user_id, since)
    if balance:
        sql += (" UNION ALL SELECT 'balance', NULL, NULL, NULL, COALESCE(SUM(amount_usd),0) "
                "FROM app_credit_ledger WHERE user_id=%s")
        params += (user_id,)
    cur.execute(sql, params)
    groups: Dict[Tuple, Decimal] = {}
    research, spent, bal = Decimal(0), Decimal(0), None
    for r in cur.fetchall():
        s = Decimal(str(r["s"] if r["s"] is not None else 0))
        if r["part"] == "balance":
            bal = float(s)
            continue
        key = (r["run_kind"], int(r["brief"] or 0))
        groups[key] = groups.get(key, Decimal(0)) + s
        spent += s
        if r["run_kind"] == "research" and not int(r["example"] or 0):
            research += s
    by_source = {"research": 0.0, "autopilot_research": 0.0, "autopilot_review": 0.0, "chat": 0.0, "other": 0.0}
    for (kind, brief), s in groups.items():
        by_source[_usage_key(kind, brief)] += float(s)
    return {"research": float(research), "by_source": by_source, "spent": float(spent), "balance": bal}


def forever_session_rates(cur, since, user_id: Optional[int] = None, limit: int = 500) -> List[Tuple[Optional[str], float, float]]:
    """(model, dollars, hours) for each run-until-stopped research session created since `since`
    (one user's, or every user's), where hours is the span from its first debit to its last. Only
    sessions that billed for at least half an hour, so a rate is never read off one call. Newest
    first; callers keep only rates and medians."""
    sql = ("SELECT r.id, r.model, -SUM(l.amount_usd) AS s, "
           "TIMESTAMPDIFF(SECOND, MIN(l.created_at), MAX(l.created_at)) AS secs "
           "FROM app_agent_runs r JOIN app_credit_ledger l ON l.run_id = r.id AND l.kind='usage' "
           "WHERE r.kind='research' AND r.run_forever=1 AND r.created_at >= %s")
    params: Tuple = (since,)
    if user_id is not None:
        sql += " AND r.user_id=%s"
        params += (user_id,)
    sql += " GROUP BY r.id, r.model HAVING secs >= 1800 ORDER BY r.id DESC LIMIT %s"
    cur.execute(sql, params + (int(limit),))
    return [(r["model"], float(r["s"]), int(r["secs"]) / 3600.0) for r in cur.fetchall()
            if r["s"] is not None and float(r["s"]) > 0]


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


# A finished research session for the cost hint before Start: one that ran to its end on a set
# number of ideas. A run-until-stopped session has no natural size, so it is never a sample.
_FINISHED_SESSION = ("r.kind='research' AND r.status='succeeded' AND r.run_forever=0 "
                     "AND (r.direction IS NULL OR r.direction <> 'random_walk')")
_RUN_DEBITS = "(SELECT -SUM(l.amount_usd) FROM app_credit_ledger l WHERE l.run_id = r.id AND l.kind='usage')"


def finished_session_costs(cur, user_id: int, limit: int = 10) -> List[float]:
    """What the user's newest finished research sessions each took from credits (the usage rows
    billed to the run), newest first. Sessions that debited nothing are left out."""
    # The newest runs first (idx_runs_user), then each one's debits (idx_credit_run_kind): a busy
    # autopilot account has thousands of runs, so never total them all before the LIMIT.
    cur.execute(
        "SELECT r.id, " + _RUN_DEBITS + " AS s FROM app_agent_runs r "
        "WHERE r.user_id=%s AND " + _FINISHED_SESSION + " ORDER BY r.created_at DESC, r.id DESC LIMIT %s",
        (user_id, int(limit)),
    )
    return [float(r["s"]) for r in cur.fetchall() if r["s"] is not None and float(r["s"]) > 0]


def finished_session_costs_by_model(cur, user_id: int, limit: int = 50) -> List[Tuple[Optional[str], float]]:
    """(model, cost) for the user's newest finished research sessions, newest first, as
    finished_session_costs reads them, so the cost hint can follow the model picked (the run's model
    key; NULL ran on the default)."""
    cur.execute(
        "SELECT r.id, r.model, " + _RUN_DEBITS + " AS s FROM app_agent_runs r "
        "WHERE r.user_id=%s AND " + _FINISHED_SESSION + " ORDER BY r.created_at DESC, r.id DESC LIMIT %s",
        (user_id, int(limit)),
    )
    return [(r["model"], float(r["s"])) for r in cur.fetchall() if r["s"] is not None and float(r["s"]) > 0]


def recent_session_costs(cur, since, limit: int = 2000) -> List[Tuple[Optional[str], float]]:
    """(model, cost) for every user's finished research sessions created since `since`, newest
    first, for the server-wide typical cost per model. Callers keep only the aggregate."""
    cur.execute(
        "SELECT r.id, r.model, " + _RUN_DEBITS + " AS s FROM app_agent_runs r "
        "WHERE r.created_at >= %s AND " + _FINISHED_SESSION + " ORDER BY r.created_at DESC LIMIT %s",
        (since, int(limit)),
    )
    return [(r["model"], float(r["s"])) for r in cur.fetchall() if r["s"] is not None and float(r["s"]) > 0]


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
