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


def ensure_welcome_bonus(cur, user_id: int) -> bool:
    """Grant the one-time welcome bonus if this user never received it.

    Idempotent and self-healing: the kind='bonus' check skips anyone who already
    has it (including backfilled rows), and the per-user stripe_ref makes concurrent
    logins race-safe via the uq_credit_stripe unique key. Called on EVERY login, so a
    grant that silently failed at signup (or predates the feature) is repaired for free.
    """
    from app import billing
    cur.execute("SELECT 1 FROM app_credit_ledger WHERE user_id=%s AND kind='bonus' LIMIT 1", (user_id,))
    if cur.fetchone():
        return False
    return add_credit(cur, user_id, "bonus", billing.FREE_BONUS, "Welcome credits",
                      stripe_ref="welcome-%d" % user_id)


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
        ensure_welcome_bonus(cur, row["id"])  # self-heal a missed grant on return
        return get_user(cur, row["id"])
    cur.execute(
        """INSERT INTO app_users (google_sub, email, name, picture_url, created_at, last_login_at)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (sub, email, name, picture, now, now),
    )
    user_id = cur.lastrowid
    # Once they're in, they're off the waitlist — the two lists are exclusive.
    if email:
        cur.execute("DELETE FROM app_waitlist WHERE email=%s", (email,))
    add_ledger(cur, user_id, "deposit", STARTING_PAPER_BALANCE, "Starting paper balance")
    ensure_welcome_bonus(cur, user_id)
    seed_demo_session(cur, user_id)
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
    max_hypotheses: Optional[int] = None, run_forever: bool = False,
) -> int:
    cur.execute(
        """INSERT INTO app_agent_runs (user_id, kind, market, direction, prompt, deployment_id, status,
             max_hypotheses, run_forever, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s)""",
        (user_id, kind, market, direction, prompt, deployment_id, max_hypotheses, 1 if run_forever else 0, now_utc()),
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
                  max_hypotheses, run_forever, created_at, started_at, finished_at
           FROM app_agent_runs WHERE id=%s AND user_id=%s""",
        (run_id, user_id),
    )
    return cur.fetchone()


def set_run_counts(cur, run_id: int, tried: int, passed: int) -> None:
    cur.execute("UPDATE app_agent_runs SET hypotheses_tried=%s, strategies_passed=%s WHERE id=%s",
                (tried, passed, run_id))


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
    run_id: Optional[int] = None, limit: int = 500,
) -> List[Dict]:
    sql = """SELECT s.id, s.run_id, s.parent_id, s.market, s.direction, s.title, s.thesis, s.spec_json, s.status,
                    s.result_json, s.created_at, r.hypotheses_tried
             FROM app_strategies s LEFT JOIN app_agent_runs r ON r.id=s.run_id
             WHERE s.user_id=%s"""
    params: List[Any] = [user_id]
    for col, val in (("s.direction", direction), ("s.status", status), ("s.market", market), ("s.run_id", run_id)):
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


def strategy_memory(cur, user_id: int, market: str, limit: int = 40) -> List[Dict]:
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


def load_history(cur, series: str, candle_minutes: int, since: datetime,
                 underlying: str = "BTC-USD") -> Dict[str, List]:
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
    # The underlying price path for THIS market's series (BTC-USD, ETH-USD, …).
    cur.execute(
        "SELECT start_ts, close FROM spot_candles_1m WHERE symbol=%s AND start_ts >= %s ORDER BY start_ts",
        (underlying, start_ts),
    )
    btc = [(int(r["start_ts"]), float(r["close"])) for r in cur.fetchall()]
    return {"markets": markets, "candles": candles, "btc": btc}


def history_freshness(cur) -> Dict[str, Optional[int]]:
    """Unix seconds of the newest BTC spot candle and newest settled market per series."""
    cur.execute("SELECT MAX(start_ts) AS t FROM spot_candles_1m WHERE symbol='BTC-USD'")
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


DEMO_IDEA = "Generate a Todd's random walk strategy that walks +0.01 and -0.01 with 50% equal chances"


def seed_demo_session(cur, user_id: int) -> None:
    """A complete, pre-populated demo on every account so the end-to-end flow is
    visible without doing anything: the idea the user would type, the session it
    becomes, the agent log, and the strategies it discovers. The star is a
    coin-flip 'random walk' with no edge. Idempotent per user."""
    import random

    cur.execute("SELECT 1 FROM app_agent_runs WHERE user_id=%s AND kind='research' AND prompt=%s", (user_id, DEMO_IDEA))
    if cur.fetchone():
        return
    now = now_utc()
    started = now - timedelta(minutes=3)
    cur.execute(
        """INSERT INTO app_agent_runs (user_id, kind, market, direction, prompt, status, hypotheses_tried,
             strategies_passed, created_at, started_at, heartbeat_at, finished_at)
           VALUES (%s,'research','btc15m','random_walk',%s,'succeeded',2,0,%s,%s,%s,%s)""",
        (user_id, DEMO_IDEA, started, started, now, now),
    )
    run_id = cur.lastrowid

    def event(kind, message, data=None, at=None):
        cur.execute(
            "INSERT INTO app_agent_events (run_id, kind, message, data_json, created_at) VALUES (%s,%s,%s,%s,%s)",
            (run_id, kind, message, _json(data), at or now),
        )

    rng = random.Random(user_id * 2654435761 & 0xFFFFFFFF)

    def walk(p_up):
        steps, cum, curve, wins = 120, 0.0, [], 0
        base = int((now - timedelta(minutes=steps * 15)).timestamp())
        for i in range(steps):
            step = 0.01 if rng.random() < p_up else -0.01
            cum += step
            wins += step > 0
            curve.append([base + i * 900, round(cum, 4)])
        pnl = round(cum, 2)
        m = {"trades": steps, "win_rate": round(wins / steps, 3), "pnl": pnl, "fees": round(steps * 0.01, 2),
             "roi": round(pnl / 10.0, 4), "profit_factor": 1.0, "max_drawdown": round(abs(min(c[1] for c in curve)), 2),
             "sharpe": None, "avg_edge": 0.0, "days": round(steps * 900 / 86400, 1), "trades_per_day": None}
        return m, curve

    event("step", "Loaded 30 days of Bitcoin 15-minute history: 16,800 decision points.", at=started)
    event("step", "Read the idea: a coin flip with no information. Testing it honestly anyway.", at=started)
    cands = [("Todd's random walk", 0.50,
              "Each step is +1¢ or −1¢ with equal odds — a pure coin flip with no information. "
              "Tested faithfully to show what no edge looks like."),
             ("Todd's random walk, biased coin", 0.52,
              "The same walk, but nudged to land heads 52% of the time to see how thin an edge the fee wall still eats.")]
    for i, (title, p_up, thesis) in enumerate(cands):
        m, curve = walk(p_up)
        event("hypothesis", title, {"thesis": thesis, "in_sample": m, "round": 1}, at=started)
        result = {"capital": 10.0, "demo": True,
                  "dataset": {"start": "2026-09-13T00:00Z", "end": now.strftime("%Y-%m-%dT%H:%MZ"),
                              "out_of_sample_from": datetime.fromtimestamp(curve[60][0], tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")},
                  "in_sample": dict(m), "out_of_sample": dict(m), "equity": curve,
                  "gates": [{"name": "Makes money on unseen data", "value": m["pnl"], "threshold": "> $0", "ok": m["pnl"] > 0},
                            {"name": "Has a real edge, not a coin flip", "value": "coin flip", "threshold": "an actual signal", "ok": False}],
                  "passed": False, "recent_trades": []}
        insert_strategy(cur, user_id, run_id, None, "btc15m", "random_walk", title, thesis,
                        json.loads(json.dumps(_demo_spec())), "rejected", result)
        event("verdict", "VOID — %s: no edge, so nothing to deploy." % title,
              {"title": title, "status": "rejected"}, at=now)
    event("done", "0 of 2 hypotheses passed. Random really does wander nowhere — now describe a real idea.",
          {"passed": 0, "tried": 2}, at=now)


def _demo_spec():
    from app import spec as _spec
    return _spec.DEFAULT_SPEC


# -- community -------------------------------------------------------------------


def store_image(cur, user_id: int, content_type: str, data: bytes) -> int:
    cur.execute(
        "INSERT INTO app_images (user_id, content_type, data, created_at) VALUES (%s,%s,%s,%s)",
        (user_id, content_type, data, now_utc()),
    )
    return cur.lastrowid


def get_image(cur, image_id: int) -> Optional[Dict]:
    cur.execute("SELECT content_type, data FROM app_images WHERE id=%s", (image_id,))
    return cur.fetchone()


def create_post(cur, user_id: int, body: str, kind: str, snapshot: Optional[Dict], image_id: Optional[int] = None) -> int:
    cur.execute(
        "INSERT INTO app_posts (user_id, body, kind, snapshot_json, image_id, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (user_id, body[:2000], kind, _json(snapshot), image_id, now_utc()),
    )
    return cur.lastrowid


def edit_post(cur, post_id: int, user_id: int, body: str) -> bool:
    """Edit own post body, stamping edited_at. Returns False if not the owner."""
    cur.execute(
        "UPDATE app_posts SET body=%s, edited_at=%s WHERE id=%s AND user_id=%s",
        (body[:2000], now_utc(), post_id, user_id),
    )
    return cur.rowcount == 1


def list_posts(cur, viewer_id: int, before_id: int = 0, limit: int = 30) -> List[Dict]:
    cur.execute(
        """SELECT p.id, p.body, p.kind, p.snapshot_json, p.image_id, p.edited_at, p.likes_count, p.comments_count, p.created_at,
                  u.name, u.picture_url, (p.user_id = %s) AS mine,
                  EXISTS(SELECT 1 FROM app_post_likes l WHERE l.post_id=p.id AND l.user_id=%s) AS liked
           FROM app_posts p JOIN app_users u ON u.id=p.user_id
           WHERE (%s = 0 OR p.id < %s) ORDER BY p.id DESC LIMIT %s""",
        (viewer_id, viewer_id, before_id, before_id, limit),
    )
    rows = cur.fetchall()
    for r in rows:
        r["snapshot"] = _loads(r.pop("snapshot_json"))
        r["mine"] = bool(r["mine"]); r["liked"] = bool(r["liked"])
    by_post = reactions_for(cur, [r["id"] for r in rows], viewer_id)
    for r in rows:
        r["reactions"] = by_post.get(r["id"], [])
    return rows


def reactions_for(cur, post_ids: List[int], viewer_id: int) -> Dict[int, List[Dict]]:
    """Per-post emoji counts (+ whether the viewer added each), most-used first."""
    if not post_ids:
        return {}
    marks = ",".join(["%s"] * len(post_ids))
    cur.execute(
        "SELECT post_id, emoji, COUNT(*) AS n, MAX(user_id=%s) AS mine "
        "FROM app_post_reactions WHERE post_id IN (%s) GROUP BY post_id, emoji "
        "ORDER BY n DESC, emoji" % ("%s", marks),
        tuple([viewer_id] + list(post_ids)),
    )
    out: Dict[int, List[Dict]] = {}
    for r in cur.fetchall():
        out.setdefault(r["post_id"], []).append({"emoji": r["emoji"], "count": int(r["n"]), "mine": bool(r["mine"])})
    return out


def toggle_reaction(cur, post_id: int, user_id: int, emoji: str) -> bool:
    """Add/remove one emoji reaction. Returns True if now reacted."""
    cur.execute("DELETE FROM app_post_reactions WHERE post_id=%s AND user_id=%s AND emoji=%s", (post_id, user_id, emoji))
    if cur.rowcount:
        return False
    cur.execute("INSERT INTO app_post_reactions (post_id, user_id, emoji, created_at) VALUES (%s,%s,%s,%s)",
                (post_id, user_id, emoji, now_utc()))
    return True


def toggle_like(cur, post_id: int, user_id: int) -> bool:
    """Returns True if now liked, False if unliked. Keeps likes_count in sync."""
    cur.execute("DELETE FROM app_post_likes WHERE post_id=%s AND user_id=%s", (post_id, user_id))
    if cur.rowcount:
        cur.execute("UPDATE app_posts SET likes_count=GREATEST(likes_count-1,0) WHERE id=%s", (post_id,))
        return False
    cur.execute("INSERT INTO app_post_likes (post_id, user_id, created_at) VALUES (%s,%s,%s)", (post_id, user_id, now_utc()))
    cur.execute("UPDATE app_posts SET likes_count=likes_count+1 WHERE id=%s", (post_id,))
    return True


def post_exists(cur, post_id: int) -> bool:
    cur.execute("SELECT 1 FROM app_posts WHERE id=%s", (post_id,))
    return cur.fetchone() is not None


def post_author(cur, post_id: int) -> Optional[Dict]:
    """The post's author (user_id, email, name) plus a short body preview, for
    reply notifications."""
    cur.execute(
        """SELECT p.user_id, u.email, u.name, LEFT(p.body, 140) AS preview
           FROM app_posts p JOIN app_users u ON u.id=p.user_id WHERE p.id=%s""",
        (post_id,),
    )
    return cur.fetchone()


def add_comment(cur, post_id: int, user_id: int, body: str) -> int:
    cur.execute(
        "INSERT INTO app_post_comments (post_id, user_id, body, created_at) VALUES (%s,%s,%s,%s)",
        (post_id, user_id, body[:1000], now_utc()),
    )
    cur.execute("UPDATE app_posts SET comments_count=comments_count+1 WHERE id=%s", (post_id,))
    return cur.lastrowid


def list_comments(cur, post_id: int, limit: int = 100) -> List[Dict]:
    cur.execute(
        """SELECT c.id, c.body, c.created_at, u.name, u.picture_url
           FROM app_post_comments c JOIN app_users u ON u.id=c.user_id
           WHERE c.post_id=%s ORDER BY c.id LIMIT %s""",
        (post_id, limit),
    )
    return cur.fetchall()


def recent_posts_count(cur, user_id: int, since: datetime) -> int:
    cur.execute("SELECT COUNT(*) AS n FROM app_posts WHERE user_id=%s AND created_at >= %s", (user_id, since))
    return int(cur.fetchone()["n"])


# -- credits & billing -----------------------------------------------------------


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


def credit_spent_total(cur, user_id: int) -> float:
    cur.execute(
        "SELECT COALESCE(-SUM(amount_usd),0) AS s FROM app_credit_ledger WHERE user_id=%s AND kind='usage'",
        (user_id,),
    )
    return float(cur.fetchone()["s"])


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
