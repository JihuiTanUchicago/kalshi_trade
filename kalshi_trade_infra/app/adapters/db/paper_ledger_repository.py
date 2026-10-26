"""The paper-money ledger: deposits, fills and the balance they sum to."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.adapters.db.sql import now_utc

STARTING_PAPER_BALANCE = 1000.0
RESET_MEMO = "Paper account reset"


def lock_user(cur, user_id: int) -> None:
    """Serialise every cash-moving write for one user (inside a transaction)."""
    cur.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (user_id,))


def add_ledger(cur, user_id: int, kind: str, amount: float, memo: str, position_id: Optional[int] = None) -> None:
    cur.execute(
        "INSERT INTO app_ledger (user_id, kind, amount, position_id, memo, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (user_id, kind, round(amount, 4), position_id, memo[:255], now_utc()),
    )


def paper_balance(cur, user_id: int) -> float:
    cur.execute("SELECT COALESCE(SUM(amount),0) AS b FROM app_ledger WHERE user_id=%s", (user_id,))
    return float(cur.fetchone()["b"])


def paper_deposits(cur, user_id: int) -> float:
    """Net money the user put in - the denominator of account ROI."""
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) AS b FROM app_ledger WHERE user_id=%s AND kind IN ('deposit','withdrawal')",
        (user_id,),
    )
    return float(cur.fetchone()["b"])


def paper_reset_at(cur, user_id: int):
    """When the user last reset the paper account (None if never). A reset wipes the ledger, so
    the account's equity P&L restarts there while closed trades (track record) keep their history."""
    cur.execute(
        "SELECT MAX(created_at) AS at FROM app_ledger WHERE user_id=%s AND kind='deposit' AND memo=%s",
        (user_id, RESET_MEMO),
    )
    row = cur.fetchone() or {}
    return row.get("at")


def paper_ledger_summary(cur, user_id: int) -> Dict:
    """paper_balance, paper_deposits and paper_reset_at in one pass over the user's ledger, for the
    dashboard (three reads there before, the room the "since your last visit" reads came from).
    {"balance", "deposited", "reset_at"}: the same sums and MAX as the three functions above."""
    cur.execute(
        "SELECT COALESCE(SUM(amount),0) AS b, "
        "COALESCE(SUM(CASE WHEN kind IN ('deposit','withdrawal') THEN amount END),0) AS dep, "
        "MAX(CASE WHEN kind='deposit' AND memo=%s THEN created_at END) AS reset_at "
        "FROM app_ledger WHERE user_id=%s",
        (RESET_MEMO, user_id),
    )
    r = cur.fetchone() or {}
    return {"balance": float(r.get("b") or 0), "deposited": float(r.get("dep") or 0), "reset_at": r.get("reset_at") or None}


def paper_ledger_version(cur, user_id: int) -> Tuple[int, int]:
    """(rows, highest id) of the user's paper ledger, read from idx_ledger_user_time alone (no row is
    fetched): ~9ms at 40k rows against ~20ms for paper_ledger_summary's sums. The ledger is only added
    to (add_ledger) or wiped and restarted with a deposit (reset_paper_account), and no row is ever
    rewritten, so every write moves it: a new row raises the highest id, and a reset changes the count
    or raises the highest id. services.book_memo keeps the summary against it."""
    cur.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(id),0) AS top FROM app_ledger FORCE INDEX (idx_ledger_user_time) WHERE user_id=%s",
        (user_id,),
    )
    r = cur.fetchone() or {}
    return int(r.get("n") or 0), int(r.get("top") or 0)


def ledger_rows(cur, user_id: int, limit: int = 50) -> List[Dict]:
    cur.execute(
        "SELECT id, kind, amount, memo, created_at FROM app_ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return cur.fetchall()


def reset_paper_account(cur, user_id: int, amount: float) -> None:
    """Wipe the paper ledger and start fresh at `amount`. Only safe with no open paper
    positions (the caller guards this) — otherwise their debited cost would be orphaned."""
    cur.execute("DELETE FROM app_ledger WHERE user_id=%s", (user_id,))
    add_ledger(cur, user_id, "deposit", amount, RESET_MEMO)
