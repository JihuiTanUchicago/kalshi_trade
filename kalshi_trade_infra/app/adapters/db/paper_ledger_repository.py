"""The paper-money ledger: deposits, fills and the balance they sum to."""
from __future__ import annotations

from typing import Dict, List, Optional

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
