"""Every SQL statement the customer app runs. Business logic (server, agent,
engine) takes a cursor and calls these, so it can be tested with a fake.

Datetimes are stored as naive UTC, like the rest of this database.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional

STARTING_PAPER_BALANCE = 1000.0


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


@contextmanager
def transaction(conn) -> Iterator[Any]:
    """BEGIN..COMMIT on an autocommit connection; ROLLBACK on any error."""
    conn.begin()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _json(value) -> Optional[str]:
    return None if value is None else json.dumps(value, separators=(",", ":"))


def _loads(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


# -- users & sessions ----------------------------------------------------------


def upsert_google_user(cur, sub: str, email: str, name: Optional[str], picture: Optional[str]) -> Dict:
    """Create on first sign-in (with the starting paper balance), refresh profile after."""
    now = now_utc()
    cur.execute("SELECT id FROM app_users WHERE google_sub=%s", (sub,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE app_users SET email=%s, name=%s, picture_url=%s, last_login_at=%s WHERE id=%s",
            (email, name, picture, now, row["id"]),
        )
        return get_user(cur, row["id"])
    cur.execute(
        """INSERT INTO app_users (google_sub, email, name, picture_url, created_at, last_login_at)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (sub, email, name, picture, now, now),
    )
    user_id = cur.lastrowid
    add_ledger(cur, user_id, "deposit", STARTING_PAPER_BALANCE, "Starting paper balance")
    return get_user(cur, user_id)


def get_user(cur, user_id: int) -> Optional[Dict]:
    cur.execute(
        "SELECT id, email, name, picture_url, autopilot, created_at FROM app_users WHERE id=%s", (user_id,)
    )
    return cur.fetchone()


def lock_user(cur, user_id: int) -> None:
    """Serialise every cash-moving write for one user (inside a transaction)."""
    cur.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (user_id,))


def set_autopilot(cur, user_id: int, on: bool) -> None:
    cur.execute("UPDATE app_users SET autopilot=%s WHERE id=%s", (1 if on else 0, user_id))


def create_session(cur, user_id: int, token_hash: str, ttl: timedelta) -> None:
    now = now_utc()
    cur.execute(
        "INSERT INTO app_sessions (token_hash, user_id, created_at, expires_at) VALUES (%s,%s,%s,%s)",
        (token_hash, user_id, now, now + ttl),
    )


def session_user(cur, token_hash: str) -> Optional[Dict]:
    cur.execute(
        """SELECT u.id, u.email, u.name, u.picture_url, u.autopilot, u.created_at
           FROM app_sessions s JOIN app_users u ON u.id=s.user_id
           WHERE s.token_hash=%s AND s.expires_at > %s""",
        (token_hash, now_utc()),
    )
    return cur.fetchone()


def delete_session(cur, token_hash: str) -> None:
    cur.execute("DELETE FROM app_sessions WHERE token_hash=%s", (token_hash,))


def save_oauth_state(cur, state: str, nonce: str, verifier: str) -> None:
    now = now_utc()
    cur.execute("DELETE FROM app_oauth_states WHERE created_at < %s", (now - timedelta(minutes=10),))
    cur.execute(
        "INSERT INTO app_oauth_states (state, nonce, code_verifier, created_at) VALUES (%s,%s,%s,%s)",
        (state, nonce, verifier, now),
    )


def pop_oauth_state(cur, state: str) -> Optional[Dict]:
    """Single use: whoever deletes the row owns it, so a replayed callback fails."""
    cur.execute(
        "SELECT nonce, code_verifier, created_at FROM app_oauth_states WHERE state=%s", (state,)
    )
    row = cur.fetchone()
    if not row:
        return None
    cur.execute("DELETE FROM app_oauth_states WHERE state=%s", (state,))
    if cur.rowcount != 1 or row["created_at"] < now_utc() - timedelta(minutes=10):
        return None
    return row


# -- Kalshi keys ---------------------------------------------------------------


def save_kalshi_key(cur, user_id: int, key_id: str, private_key_enc: bytes) -> None:
    cur.execute(
        """INSERT INTO app_kalshi_keys (user_id, key_id, private_key_enc, created_at) VALUES (%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE key_id=VALUES(key_id), private_key_enc=VALUES(private_key_enc),
             created_at=VALUES(created_at)""",
        (user_id, key_id, private_key_enc, now_utc()),
    )


def get_kalshi_key(cur, user_id: int) -> Optional[Dict]:
    cur.execute("SELECT key_id, private_key_enc, created_at FROM app_kalshi_keys WHERE user_id=%s", (user_id,))
    return cur.fetchone()


def delete_kalshi_key(cur, user_id: int) -> None:
    cur.execute("DELETE FROM app_kalshi_keys WHERE user_id=%s", (user_id,))


# -- paper ledger --------------------------------------------------------------


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


def ledger_rows(cur, user_id: int, limit: int = 50) -> List[Dict]:
    cur.execute(
        "SELECT id, kind, amount, memo, created_at FROM app_ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return cur.fetchall()


# -- agent runs ----------------------------------------------------------------

RUN_ACTIVE = ("queued", "running")


def create_run(
    cur, user_id: int, kind: str, market: Optional[str] = None, direction: Optional[str] = None,
    prompt: Optional[str] = None, deployment_id: Optional[int] = None,
) -> int:
    cur.execute(
        """INSERT INTO app_agent_runs (user_id, kind, market, direction, prompt, deployment_id, status, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,'queued',%s)""",
        (user_id, kind, market, direction, prompt, deployment_id, now_utc()),
    )
    return cur.lastrowid


def count_runs(cur, user_id: int, kind: str, since: Optional[datetime] = None, active_only: bool = False) -> int:
    sql = "SELECT COUNT(*) AS n FROM app_agent_runs WHERE user_id=%s AND kind=%s"
    params: List[Any] = [user_id, kind]
    if active_only:
        sql += " AND status IN ('queued','running')"
    if since is not None:
        sql += " AND created_at >= %s"
        params.append(since)
    cur.execute(sql, params)
    return int(cur.fetchone()["n"])


def claim_run(conn, worker_id: str) -> Optional[Dict]:
    """Take the oldest queued run. SKIP LOCKED lets any number of workers
    share the queue without two of them taking the same run."""
    with transaction(conn) as cur:
        cur.execute(
            "SELECT * FROM app_agent_runs WHERE status='queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
        run = cur.fetchone()
        if not run:
            return None
        now = now_utc()
        cur.execute(
            "UPDATE app_agent_runs SET status='running', worker_id=%s, started_at=%s, heartbeat_at=%s WHERE id=%s",
            (worker_id, now, now, run["id"]),
        )
        run.update(status="running", worker_id=worker_id, started_at=now)
        return run


def fail_abandoned_runs(cur, stale_after: timedelta) -> int:
    """A run whose worker stopped heart-beating is failed, not retried: a
    retry would silently spend the user's model budget twice."""
    cur.execute(
        """UPDATE app_agent_runs SET status='failed', error='The agent stopped responding.', finished_at=%s
           WHERE status='running' AND heartbeat_at < %s""",
        (now_utc(), now_utc() - stale_after),
    )
    return cur.rowcount


def heartbeat(cur, run_id: int) -> Optional[str]:
    """Touch the run and return its status (so a cancel is noticed)."""
    cur.execute("UPDATE app_agent_runs SET heartbeat_at=%s WHERE id=%s", (now_utc(), run_id))
    cur.execute("SELECT status FROM app_agent_runs WHERE id=%s", (run_id,))
    row = cur.fetchone()
    return row["status"] if row else None


def finish_run(
    cur, run_id: int, status: str, error: Optional[str] = None, tried: int = 0, passed: int = 0,
    input_tokens: int = 0, output_tokens: int = 0,
) -> None:
    cur.execute(
        """UPDATE app_agent_runs SET status=%s, error=%s, hypotheses_tried=%s, strategies_passed=%s,
             input_tokens=%s, output_tokens=%s, finished_at=%s
           WHERE id=%s AND status='running'""",
        (status, error, tried, passed, input_tokens, output_tokens, now_utc(), run_id),
    )


def cancel_run(cur, user_id: int, run_id: int) -> bool:
    cur.execute(
        """UPDATE app_agent_runs SET status='cancelled', finished_at=%s
           WHERE id=%s AND user_id=%s AND status IN ('queued','running')""",
        (now_utc(), run_id, user_id),
    )
    return cur.rowcount == 1


def add_event(cur, run_id: int, kind: str, message: str, data: Optional[Dict] = None) -> None:
    cur.execute(
        "INSERT INTO app_agent_events (run_id, kind, message, data_json, created_at) VALUES (%s,%s,%s,%s,%s)",
        (run_id, kind, message, _json(data), now_utc()),
    )


def list_runs(cur, user_id: int, limit: int = 50) -> List[Dict]:
    cur.execute(
        """SELECT id, market, direction, prompt, status, hypotheses_tried, strategies_passed, error,
                  created_at, started_at, finished_at
           FROM app_agent_runs WHERE user_id=%s AND kind='research' ORDER BY id DESC LIMIT %s""",
        (user_id, limit),
    )
    return cur.fetchall()


def get_run(cur, user_id: int, run_id: int) -> Optional[Dict]:
    cur.execute(
        """SELECT id, kind, market, direction, prompt, status, hypotheses_tried, strategies_passed, error,
                  created_at, started_at, finished_at
           FROM app_agent_runs WHERE id=%s AND user_id=%s""",
        (run_id, user_id),
    )
    return cur.fetchone()


def run_events(cur, run_id: int, after_id: int = 0) -> List[Dict]:
    cur.execute(
        "SELECT id, kind, message, data_json, created_at FROM app_agent_events WHERE run_id=%s AND id>%s ORDER BY id",
        (run_id, after_id),
    )
    rows = cur.fetchall()
    for r in rows:
        r["data"] = _loads(r.pop("data_json"))
    return rows


# -- strategies ----------------------------------------------------------------


def insert_strategy(
    cur, user_id: int, run_id: Optional[int], parent_id: Optional[int], market: str, direction: str,
    title: str, thesis: str, spec: Dict, status: str, result: Optional[Dict],
) -> int:
    cur.execute(
        """INSERT INTO app_strategies
             (user_id, run_id, parent_id, market, direction, title, thesis, spec_json, status, result_json, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (user_id, run_id, parent_id, market, direction, title[:200], thesis, _json(spec), status, _json(result), now_utc()),
    )
    return cur.lastrowid


def _strategy_row(r: Dict) -> Dict:
    r["spec"] = _loads(r.pop("spec_json"))
    if "result_json" in r:
        r["result"] = _loads(r.pop("result_json"))
    return r


def list_strategies(
    cur, user_id: int, direction: Optional[str] = None, status: Optional[str] = None, market: Optional[str] = None,
    limit: int = 200,
) -> List[Dict]:
    sql = """SELECT s.id, s.run_id, s.parent_id, s.market, s.direction, s.title, s.thesis, s.spec_json, s.status,
                    s.result_json, s.created_at, r.hypotheses_tried
             FROM app_strategies s LEFT JOIN app_agent_runs r ON r.id=s.run_id
             WHERE s.user_id=%s"""
    params: List[Any] = [user_id]
    for col, val in (("s.direction", direction), ("s.status", status), ("s.market", market)):
        if val:
            sql += " AND %s=%%s" % col
            params.append(val)
    sql += " ORDER BY s.id DESC LIMIT %s"
    params.append(limit)
    cur.execute(sql, params)
    return [_strategy_row(r) for r in cur.fetchall()]


def get_strategy(cur, user_id: int, strategy_id: int) -> Optional[Dict]:
    cur.execute(
        """SELECT s.id, s.run_id, s.parent_id, s.market, s.direction, s.title, s.thesis, s.spec_json, s.status,
                  s.result_json, s.created_at, r.hypotheses_tried
           FROM app_strategies s LEFT JOIN app_agent_runs r ON r.id=s.run_id
           WHERE s.id=%s AND s.user_id=%s""",
        (strategy_id, user_id),
    )
    row = cur.fetchone()
    return _strategy_row(row) if row else None


def strategy_memory(cur, user_id: int, market: str, limit: int = 15) -> List[Dict]:
    """What this user's agents already tried on this market, newest first."""
    cur.execute(
        """SELECT title, direction, spec_json, status, result_json FROM app_strategies
           WHERE user_id=%s AND market=%s ORDER BY id DESC LIMIT %s""",
        (user_id, market, limit),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


# -- deployments & positions ---------------------------------------------------


def create_deployment(cur, user_id: int, strategy_id: int, market: str, mode: str) -> int:
    now = now_utc()
    cur.execute(
        """INSERT INTO app_deployments (user_id, strategy_id, market, mode, status, created_at, updated_at)
           VALUES (%s,%s,%s,%s,'running',%s,%s)""",
        (user_id, strategy_id, market, mode, now, now),
    )
    return cur.lastrowid


_DEPLOYMENT_SELECT = """
    SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.status, d.status_reason, d.last_decision_ts,
           d.created_at, d.updated_at, s.title, s.direction, s.spec_json, s.result_json,
           COALESCE(SUM(CASE WHEN p.status='closed' THEN p.pnl END),0) AS realized_pnl,
           COUNT(CASE WHEN p.status='closed' THEN 1 END) AS closed_trades,
           COUNT(CASE WHEN p.status='closed' AND p.pnl > 0 THEN 1 END) AS wins,
           COUNT(CASE WHEN p.status='open' THEN 1 END) AS open_positions
    FROM app_deployments d
    JOIN app_strategies s ON s.id=d.strategy_id
    LEFT JOIN app_positions p ON p.deployment_id=d.id
"""


def list_deployments(cur, user_id: int, include_stopped: bool = False) -> List[Dict]:
    sql = _DEPLOYMENT_SELECT + " WHERE d.user_id=%s"
    if not include_stopped:
        sql += " AND d.status <> 'stopped'"
    sql += " GROUP BY d.id ORDER BY d.id DESC"
    cur.execute(sql, (user_id,))
    return [_strategy_row(r) for r in cur.fetchall()]


def get_deployment(cur, user_id: int, deployment_id: int) -> Optional[Dict]:
    cur.execute(_DEPLOYMENT_SELECT + " WHERE d.id=%s AND d.user_id=%s GROUP BY d.id", (deployment_id, user_id))
    row = cur.fetchone()
    return _strategy_row(row) if row else None


def running_deployments(cur, market: str) -> List[Dict]:
    cur.execute(
        """SELECT d.id, d.user_id, d.strategy_id, d.market, d.mode, d.last_decision_ts, s.spec_json, s.result_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           WHERE d.status='running' AND d.market=%s ORDER BY d.id""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def deployments_with_open_positions(cur, market: str) -> List[Dict]:
    """Paused deployments still need their open positions settled."""
    cur.execute(
        """SELECT DISTINCT d.id, d.user_id, d.mode, s.spec_json
           FROM app_deployments d JOIN app_strategies s ON s.id=d.strategy_id
           JOIN app_positions p ON p.deployment_id=d.id AND p.status='open'
           WHERE d.market=%s""",
        (market,),
    )
    return [_strategy_row(r) for r in cur.fetchall()]


def set_deployment_status(cur, user_id: int, deployment_id: int, status: str, reason: Optional[str] = None) -> bool:
    cur.execute(
        "UPDATE app_deployments SET status=%s, status_reason=%s, updated_at=%s WHERE id=%s AND user_id=%s AND status<>'stopped'",
        (status, reason, now_utc(), deployment_id, user_id),
    )
    return cur.rowcount == 1


def set_deployment_strategy(cur, user_id: int, deployment_id: int, strategy_id: int) -> bool:
    cur.execute(
        "UPDATE app_deployments SET strategy_id=%s, updated_at=%s WHERE id=%s AND user_id=%s",
        (strategy_id, now_utc(), deployment_id, user_id),
    )
    return cur.rowcount == 1


def claim_decision(cur, deployment_id: int, decision_ts: int) -> bool:
    """At most one decision per deployment per slot, however many engines
    run: whoever moves last_decision_ts forward owns the slot."""
    cur.execute(
        "UPDATE app_deployments SET last_decision_ts=%s WHERE id=%s AND status='running' AND last_decision_ts < %s",
        (decision_ts, deployment_id, decision_ts),
    )
    return cur.rowcount == 1


def open_positions(cur, deployment_id: int) -> List[Dict]:
    cur.execute("SELECT * FROM app_positions WHERE deployment_id=%s AND status='open' ORDER BY id", (deployment_id,))
    return cur.fetchall()


def user_positions(cur, user_id: int, status: str = "open", limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT p.*, s.title FROM app_positions p
           JOIN app_deployments d ON d.id=p.deployment_id JOIN app_strategies s ON s.id=d.strategy_id
           WHERE p.user_id=%s AND p.status=%s ORDER BY p.id DESC LIMIT %s""",
        (user_id, status, limit),
    )
    return cur.fetchall()


def insert_position(
    cur, deployment_id: int, user_id: int, mode: str, ticker: str, side: str, qty: int, entry_price: float,
    entry_fee: float, market_close_time: datetime, order_ref: Optional[str] = None,
) -> int:
    cur.execute(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
             market_close_time, opened_at, status, order_ref)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s)""",
        (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
         market_close_time.astimezone(timezone.utc).replace(tzinfo=None) if market_close_time.tzinfo else market_close_time,
         now_utc(), order_ref),
    )
    return cur.lastrowid


def close_position(cur, position_id: int, exit_price: float, exit_fee: float, pnl: float, reason: str) -> bool:
    """Idempotent: only an open position closes, so a retried tick cannot
    book the same exit twice."""
    cur.execute(
        """UPDATE app_positions SET status='closed', exit_price=%s, exit_fee=%s, pnl=%s, close_reason=%s, closed_at=%s
           WHERE id=%s AND status='open'""",
        (exit_price, exit_fee, round(pnl, 4), reason, now_utc(), position_id),
    )
    return cur.rowcount == 1


def realized_pnl(cur, user_id: int, mode: str, since: Optional[datetime] = None) -> float:
    sql = "SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions WHERE user_id=%s AND mode=%s AND status='closed'"
    params: List[Any] = [user_id, mode]
    if since is not None:
        sql += " AND closed_at >= %s"
        params.append(since)
    cur.execute(sql, params)
    return float(cur.fetchone()["p"])


def daily_pnl(cur, user_id: int, mode: str, days: int = 60) -> List[Dict]:
    cur.execute(
        """SELECT DATE(closed_at) AS d, SUM(pnl) AS pnl FROM app_positions
           WHERE user_id=%s AND mode=%s AND status='closed' AND closed_at >= %s
           GROUP BY DATE(closed_at) ORDER BY d""",
        (user_id, mode, now_utc() - timedelta(days=days)),
    )
    return cur.fetchall()


# -- chat & proposals ----------------------------------------------------------


def add_chat(cur, user_id: int, role: str, content: str, proposal_id: Optional[int] = None) -> int:
    cur.execute(
        "INSERT INTO app_chat_messages (user_id, role, content, proposal_id, created_at) VALUES (%s,%s,%s,%s,%s)",
        (user_id, role, content, proposal_id, now_utc()),
    )
    return cur.lastrowid


def chat_messages(cur, user_id: int, after_id: int = 0, limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT m.id, m.role, m.content, m.created_at, m.proposal_id,
                  p.kind AS proposal_kind, p.status AS proposal_status, p.deployment_id, p.strategy_id
           FROM app_chat_messages m LEFT JOIN app_proposals p ON p.id=m.proposal_id
           WHERE m.user_id=%s AND m.id>%s ORDER BY m.id DESC LIMIT %s""",
        (user_id, after_id, limit),
    )
    return list(reversed(cur.fetchall()))


def create_proposal(
    cur, user_id: int, kind: str, reason: str, deployment_id: Optional[int] = None,
    strategy_id: Optional[int] = None, status: str = "pending",
) -> int:
    cur.execute(
        """INSERT INTO app_proposals (user_id, kind, deployment_id, strategy_id, reason, status, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (user_id, kind, deployment_id, strategy_id, reason, status, now_utc()),
    )
    return cur.lastrowid


def get_proposal(cur, user_id: int, proposal_id: int) -> Optional[Dict]:
    cur.execute("SELECT * FROM app_proposals WHERE id=%s AND user_id=%s", (proposal_id, user_id))
    return cur.fetchone()


def decide_proposal(cur, proposal_id: int, status: str) -> bool:
    cur.execute(
        "UPDATE app_proposals SET status=%s, decided_at=%s WHERE id=%s AND status='pending'",
        (status, now_utc(), proposal_id),
    )
    return cur.rowcount == 1


# -- dataset ---------------------------------------------------------------------


def load_history(cur, series: str, candle_minutes: int, since: datetime) -> Dict[str, List]:
    cur.execute(
        """SELECT ticker, strike, close_time, result FROM hist_markets
           WHERE series_ticker=%s AND close_time >= %s AND candles_done=1""",
        (series, since),
    )
    markets = cur.fetchall()
    cur.execute(
        """SELECT c.ticker, c.end_period_ts, c.yes_bid_close, c.yes_ask_close
           FROM market_candles c JOIN hist_markets h ON h.ticker=c.ticker
           WHERE h.series_ticker=%s AND h.close_time >= %s AND h.candles_done=1
             AND c.period_interval_minutes=%s""",
        (series, since, candle_minutes),
    )
    candles = cur.fetchall()
    start_ts = int(since.replace(tzinfo=timezone.utc).timestamp()) - 2 * 86400
    cur.execute("SELECT start_ts, close FROM btc_candles_1m WHERE start_ts >= %s ORDER BY start_ts", (start_ts,))
    btc = [(int(r["start_ts"]), float(r["close"])) for r in cur.fetchall()]
    return {"markets": markets, "candles": candles, "btc": btc}


def history_freshness(cur) -> Dict[str, Optional[int]]:
    """Unix seconds of the newest BTC candle and newest settled market per series."""
    cur.execute("SELECT MAX(start_ts) AS t FROM btc_candles_1m")
    out = {"btc": (cur.fetchone() or {}).get("t")}
    cur.execute("SELECT series_ticker, MAX(close_time) AS t FROM hist_markets WHERE candles_done=1 GROUP BY series_ticker")
    for r in cur.fetchall():
        out[r["series_ticker"]] = int(r["t"].replace(tzinfo=timezone.utc).timestamp()) if r["t"] else None
    return out


def deployment_curves(cur, user_id: int) -> Dict[int, List[List]]:
    """Cumulative realized P&L per deployment, oldest first, for sparklines."""
    cur.execute(
        """SELECT deployment_id, closed_at, pnl FROM app_positions
           WHERE user_id=%s AND status='closed' ORDER BY closed_at, id""",
        (user_id,),
    )
    out: Dict[int, List[List]] = {}
    totals: Dict[int, float] = {}
    for r in cur.fetchall():
        dep = r["deployment_id"]
        totals[dep] = totals.get(dep, 0.0) + float(r["pnl"])
        out.setdefault(dep, []).append([int(r["closed_at"].replace(tzinfo=timezone.utc).timestamp()), round(totals[dep], 4)])
    return out


def active_run_counts(cur, user_id: int) -> Dict[str, int]:
    cur.execute(
        """SELECT kind, status, COUNT(*) AS n FROM app_agent_runs
           WHERE user_id=%s AND status IN ('queued','running') GROUP BY kind, status""",
        (user_id,),
    )
    out = {"research_running": 0, "research_queued": 0, "chat_active": 0}
    for r in cur.fetchall():
        if r["kind"] == "research":
            out["research_" + r["status"]] += int(r["n"])
        else:
            out["chat_active"] += int(r["n"])
    return out


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def add_waitlist(cur, email: str, note: Optional[str]) -> bool:
    """Record a waitlist request. Returns True if this is a new email."""
    cur.execute(
        """INSERT INTO app_waitlist (email, note, status, created_at) VALUES (%s,%s,'requested',%s)
           ON DUPLICATE KEY UPDATE note=COALESCE(VALUES(note), note)""",
        (email[:320], (note or None) and note[:500], now_utc()),
    )
    return cur.rowcount == 1  # 1 = inserted, 2 = updated an existing row


def count_waitlist(cur) -> int:
    cur.execute("SELECT COUNT(*) AS n FROM app_waitlist")
    return int(cur.fetchone()["n"])


def recent_waitlist_from(cur, ip_bucket: str, since: datetime) -> int:
    # No per-IP column; rate-limit waitlist globally by recent inserts instead.
    cur.execute("SELECT COUNT(*) AS n FROM app_waitlist WHERE created_at >= %s", (since,))
    return int(cur.fetchone()["n"])
