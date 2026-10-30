"""The autopilot panel's small reads, gathered into one statement for its 20s poll."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

EPOCH = datetime(1970, 1, 1)
RESEARCH_WINDOW = 50  # the newest research sessions list_runs returns, which the panel's "researching now" reads


def _pulse_secs(col: str) -> str:
    """A DATETIME as whole seconds since 1970 (time-zone free, as track_record_rows reads times)."""
    return "TIMESTAMPDIFF(SECOND, '1970-01-01', %s)" % col


def _pulse_at(s) -> Optional[datetime]:
    return None if s is None else EPOCH + timedelta(seconds=int(s))


def _pulse_list(v) -> List:
    if not v:
        return []
    return json.loads(v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v)


def autopilot_pulse(cur, user_id: int, since, review: bool = False, engine: bool = False) -> Dict[str, Any]:
    """One row of what the autopilot panel used to read one statement at a time:

      positions       (rows, closed rows, highest id): repo.positions_version, for services.book_memo
      dep_strategies  {deployment_id: strategy_id}, every deployment: repo.deployment_strategies
      kalshi_key      a Kalshi key is saved (repo.get_kalshi_key is not None)
      chat            (rows, highest id) of the user's chat: the version last_autopilot_action is kept on
      last_review_at  repo.last_review_at
      runs_7d, tested_7d   research_week(since) summed over its models (the seeded example left out)
      researched      any research session ever, the seeded example left out (research_week from 1970 has a run)
      passed_7d       repo.strategies_passed_since(since)
      research_live   the queued and running sessions among the newest RESEARCH_WINDOW (repo.list_runs),
                      newest first, with the fields views._run_wait reads
      review          with `review`: repo.active_agent_run(kind='review'), else None
      engine_age      with `engine`: repo.engine_last_tick_age_seconds, else None

    Each part is the read it replaces, and all of them see the same snapshot. Run times travel as whole
    seconds (the columns are DATETIME) and come back as the same naive datetimes."""
    times = ", ".join(_pulse_secs("r." + c) for c in ("created_at", "started_at", "heartbeat_at"))
    review_sql = ("(SELECT JSON_ARRAY(id, status, %s, %s) FROM app_agent_runs WHERE user_id=%%s AND kind='review' "
                  "AND status IN ('queued','running') ORDER BY id LIMIT 1)" % (_pulse_secs("created_at"), _pulse_secs("heartbeat_at"))
                  if review else "NULL")
    engine_sql = ("(SELECT TIMESTAMPDIFF(SECOND, updated_at_utc, UTC_TIMESTAMP()) FROM collector_state "
                  "WHERE state_key='recursive_engine_last_tick' LIMIT 1)" if engine else "NULL")
    sql = """SELECT pv.n AS pos_n, pv.closed AS pos_closed, pv.top AS pos_top, wk.runs AS runs_7d, wk.tried AS tested_7d,
                    (SELECT COUNT(*) FROM app_strategies s JOIN app_agent_runs r ON r.id=s.run_id
                      WHERE s.user_id=%s AND s.status='passed' AND r.kind='research' AND r.created_at>=%s) AS passed_7d,
                    (SELECT JSON_ARRAYAGG(JSON_ARRAY(r.id, r.market, r.status, """ + times + """))
                       FROM (SELECT id FROM app_agent_runs WHERE user_id=%s AND kind='research' ORDER BY id DESC LIMIT %s) n
                       JOIN app_agent_runs r ON r.id=n.id WHERE r.status IN ('queued','running')) AS research_live,
                    """ + review_sql + """ AS review_live,
                    (SELECT COALESCE(started_at, created_at) FROM app_agent_runs WHERE user_id=%s AND kind='review'
                      ORDER BY id DESC LIMIT 1) AS last_review_at,
                    (SELECT COUNT(*) FROM app_chat_messages WHERE user_id=%s) AS chat_n,
                    (SELECT MAX(id) FROM app_chat_messages WHERE user_id=%s) AS chat_top,
                    EXISTS(SELECT 1 FROM app_kalshi_keys WHERE user_id=%s) AS kalshi_key,
                    EXISTS(SELECT 1 FROM app_agent_runs WHERE user_id=%s AND kind='research'
                           AND (direction IS NULL OR direction <> 'random_walk')) AS researched,
                    (SELECT JSON_ARRAYAGG(JSON_ARRAY(id, strategy_id)) FROM app_deployments WHERE user_id=%s) AS dep_strategies,
                    """ + engine_sql + """ AS engine_age
             FROM (SELECT COUNT(*) AS n, COUNT(CASE WHEN status='closed' THEN 1 END) AS closed, COALESCE(MAX(id),0) AS top
                   FROM app_positions FORCE INDEX (idx_pos_user) WHERE user_id=%s) pv
             CROSS JOIN (SELECT COUNT(*) AS runs, COALESCE(SUM(hypotheses_tried),0) AS tried FROM app_agent_runs
                   WHERE user_id=%s AND kind='research' AND created_at>=%s
                   AND (direction IS NULL OR direction <> 'random_walk')) wk"""
    params = ((user_id, since, user_id, RESEARCH_WINDOW) + ((user_id,) if review else ())
              + (user_id,) * 7 + (user_id, since))
    cur.execute(sql, params)
    r = cur.fetchone() or {}
    live = sorted(_pulse_list(r.get("research_live")), key=lambda x: -int(x[0]))
    rv = _pulse_list(r.get("review_live")) if review else []
    return {
        "positions": (int(r.get("pos_n") or 0), int(r.get("pos_closed") or 0), int(r.get("pos_top") or 0)) if r else None,
        "dep_strategies": {int(d): int(s) for d, s in _pulse_list(r.get("dep_strategies"))} if r else None,
        "kalshi_key": bool(r.get("kalshi_key")),
        "researched": bool(r.get("researched")),
        "chat": (int(r.get("chat_n") or 0), int(r.get("chat_top") or 0)) if r else None,
        "last_review_at": r.get("last_review_at"),
        "runs_7d": int(r.get("runs_7d") or 0), "tested_7d": int(r.get("tested_7d") or 0),
        "passed_7d": int(r.get("passed_7d") or 0),
        "research_live": [{"id": int(x[0]), "market": x[1], "status": x[2], "created_at": _pulse_at(x[3]),
                           "started_at": _pulse_at(x[4]), "heartbeat_at": _pulse_at(x[5])} for x in live],
        "review": ({"id": int(rv[0]), "kind": "review", "status": rv[1], "created_at": _pulse_at(rv[2]),
                    "heartbeat_at": _pulse_at(rv[3])} if rv else None),
        "engine_age": int(r["engine_age"]) if r.get("engine_age") is not None else None,
    }
