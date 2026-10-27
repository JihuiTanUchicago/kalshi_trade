"""The strategy inventory (app_strategies): insert, record the gate outcome, list/count with filters, get, share, delete,
and the discovery-tree reads."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.db.sql import _json, _loads, now_utc

# The direction of the example session every new account is seeded with (repository.seed_demo_session).
# The user never ran it, so headline counts leave it out; lists still show it, marked as an example.
DEMO_DIRECTION = "random_walk"

# A strategy row `s` with no gatekeeper record: no stored experiment_id and no experiment linked by its strategy_id
# (relabel_backtest_only's own test). The experiment probe (idx_exp_user_market's user_id prefix) runs only for a
# row without experiment_id, a legacy row. Shared by the reads that carry it as a column (NO_RECORD_SQL, the
# Community feed's). Display only.
NO_EXPERIMENT_SQL = ("s.experiment_id IS NULL AND NOT EXISTS (SELECT 1 FROM app_experiments e "
                     "WHERE e.user_id=s.user_id AND e.strategy_id=s.id)")


def strategies_passed_since(cur, user_id: int, since) -> int:
    """Strategies that cleared every gate (status 'passed') from research runs started since
    `since`: the same runs research_week counts ideas over, so "tested N, M passed" never reads
    M > N because of shared copies or chat adjustments (they have no research run). The runs'
    strategies_passed counter is not this: a 2026-10-17 run counted 68 backtest-only rows there."""
    cur.execute("""SELECT COUNT(*) AS n FROM app_strategies s JOIN app_agent_runs r ON r.id=s.run_id
                   WHERE s.user_id=%s AND s.status='passed' AND r.kind='research' AND r.created_at>=%s""",
                (user_id, since))
    return int((cur.fetchone() or {}).get("n") or 0)


def markets_with_strategies(cur, user_id: int, markets: List[str]) -> List[str]:
    """Which of `markets` (market keys) the user has any strategy on, the seeded example's left out as
    count_strategies leaves it out: a market page offers "Your <market> strategies" only then. One read
    through idx_strat_user, a row per market found."""
    if not markets:
        return []
    cur.execute("SELECT DISTINCT market FROM app_strategies WHERE user_id=%%s AND direction<>%%s AND market IN (%s)"
                % ",".join(["%s"] * len(markets)), [user_id, DEMO_DIRECTION, *markets])
    return sorted(r["market"] for r in cur.fetchall())


def passed_since(cur, user_id: int, since, limit: int = 3) -> Dict:
    """Strategies of the user's own that passed since `since`, newest first: {"n": all of them,
    "items": [{"id", "title", "market", "spec", "experiment_id"}] the newest `limit`}. One read through
    idx_strat_user (user_id, status, created_at). Leaves out the seeded example and copies friends shared,
    which aren't new results."""
    cur.execute("""SELECT id, title, market, spec_json, experiment_id, COUNT(*) OVER () AS n FROM app_strategies
                   WHERE user_id=%s AND status='passed' AND created_at>=%s
                   AND (direction IS NULL OR direction<>%s) AND shared_from_user_id IS NULL
                   ORDER BY id DESC LIMIT %s""",
                (user_id, since, DEMO_DIRECTION, int(limit)))
    rows = cur.fetchall()
    return {"n": int(rows[0]["n"]) if rows else 0,
            "items": [{"id": r["id"], "title": r["title"], "market": r.get("market"), "spec": _loads(r.get("spec_json")) or {},
                       "experiment_id": r.get("experiment_id")} for r in rows]}


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


def set_strategy_outcome(cur, strategy_id: int, status: str, result: Optional[Dict],
                         experiment_id: Optional[int] = None) -> None:
    """Record a strategy's final status/result after the gatekeeper's verdict. The research loop
    inserts the row first (so the immutable experiment can carry its strategy_id), then writes
    the classification-derived outcome here once judging returns. `experiment_id` is the robust
    link back to the pre-registration this strategy was validated under — the research-paper page
    resolves by it first (surviving a re-hit re-point). Status/result/experiment_id only — the
    row's identity fields are never touched."""
    cur.execute(
        "UPDATE app_strategies SET status=%s, result_json=%s, experiment_id=%s WHERE id=%s",
        (status, _json(result), experiment_id, strategy_id),
    )


def _strategy_row(r: Dict) -> Dict:
    r["spec"] = _loads(r.pop("spec_json"))
    if "last_scan_json" in r:
        r["scan"] = _loads(r.pop("last_scan_json"))
    if "result_json" in r:
        r["result"] = _loads(r.pop("result_json"))
    return r


NOISE_STATUSES = ("rejected", "failed")  # the un-kept outcomes the default list view hides

# A strategy's unseen-data backtest P&L, read from its stored result for the list's "best first" order.
_UNSEEN_PNL_JSON = "JSON_EXTRACT(s.result_json, '$.out_of_sample.pnl')"
_UNSEEN_PNL = "CAST(JSON_UNQUOTE(%s) AS DECIMAL(16,4))" % _UNSEEN_PNL_JSON


def _strategy_filter_sql(direction, status, market, run_id, q, deployed, hide_noise=False) -> tuple:
    """Shared WHERE clause for list/count so the headline figures and the page agree.
    `hide_noise` (default list view only) drops rejected/void rows — they stay in the DB (the
    immutable ledger counts every tested hypothesis for DSR/FDR), just out of the default page.
    Ignored when an explicit `status` is selected (that exact-match already scopes the view)."""
    sql, params = " WHERE s.user_id=%s", []  # caller prepends user_id
    for col, val in (("s.direction", direction), ("s.status", status), ("s.market", market), ("s.run_id", run_id)):
        if val:
            sql += " AND %s=%%s" % col
            params.append(val)
    if hide_noise and not status:
        sql += " AND s.status NOT IN (%s)" % ",".join(["%s"] * len(NOISE_STATUSES))
        params.extend(NOISE_STATUSES)
    if q:
        sql += " AND (s.title LIKE %s OR s.thesis LIKE %s)"
        like = "%" + q + "%"
        params.extend((like, like))
    if deployed:
        sql += " AND EXISTS (SELECT 1 FROM app_deployments d WHERE d.strategy_id=s.id AND d.status<>'stopped')"
    return sql, params


def list_strategies(
    cur, user_id: int, direction: Optional[str] = None, status: Optional[str] = None, market: Optional[str] = None,
    run_id: Optional[int] = None, limit: int = 500, offset: int = 0, q: Optional[str] = None, deployed: bool = False,
    hide_noise: bool = False, sort: Optional[str] = None, only_ids: Optional[List[int]] = None,
    skip_ids: Optional[List[int]] = None, keep_ids: Optional[List[int]] = None,
) -> List[Dict]:
    """The user's strategies, filtered as count_strategies counts them. `sort` "best" orders by the
    unseen-data (out-of-sample) backtest P&L, best first; otherwise newest first, rejected last.
    `only_ids` / `skip_ids` narrow it to, or leave out, those strategies (the list's passes a later check
    left uncleared, from passed_strategies); an empty `only_ids` lists nothing. `keep_ids` lists those
    void or rejected strategies in the `hide_noise` view anyway (a probation strategy held back after
    passing on paper, which the list counts as not cleared, not as void)."""
    if only_ids is not None and not only_ids:
        return []
    keep = hide_noise and not status and keep_ids
    where, fparams = _strategy_filter_sql(direction, status, market, run_id, q, deployed, hide_noise and not keep)
    if keep:
        where += " AND (s.status NOT IN (%s) OR s.id IN (%s))" % (
            ",".join(["%s"] * len(NOISE_STATUSES)), ",".join(["%s"] * len(keep_ids)))
        fparams.extend(NOISE_STATUSES)
        fparams.extend(int(i) for i in keep_ids)
    for ids, op in ((only_ids, "IN"), (skip_ids, "NOT IN")):
        if ids:
            where += " AND s.id %s (%s)" % (op, ",".join(["%s"] * len(ids)))
            fparams.extend(int(i) for i in ids)
    sql = ("""SELECT s.id, s.run_id, s.parent_id, s.market, s.direction, s.title, s.thesis, s.spec_json, s.status,
                    s.result_json, s.experiment_id, s.created_at, r.hypotheses_tried, s.shared_from_user_id, su.name AS shared_from_name,
                    r.brief AS by_autopilot,
                    (SELECT COUNT(*) FROM app_deployments d WHERE d.strategy_id=s.id AND d.status<>'stopped') AS active_deps,
                    (SELECT COUNT(*) FROM app_deployments d WHERE d.strategy_id=s.id AND d.status<>'stopped' AND d.mode='live') AS live_deps,
                    (SELECT COUNT(*) FROM app_deployments d WHERE d.strategy_id=s.id AND d.status='stopped') AS removed_deps
             FROM app_strategies s LEFT JOIN app_agent_runs r ON r.id=s.run_id
                  LEFT JOIN app_users su ON su.id=s.shared_from_user_id""" + where)
    params: List[Any] = [user_id] + fparams
    if sort == "best":
        # The sort "P&L on data it never saw", highest first: the out-of-sample backtest P&L the list's Unseen P&L column shows.
        # One with no unseen test (rejected, tested only) goes last; ties and the rest newest first.
        sql += " ORDER BY (%s IS NULL), %s DESC, s.id DESC LIMIT %%s OFFSET %%s" % (_UNSEEN_PNL_JSON, _UNSEEN_PNL)
    else:
        # Non-rejected (passed/void) first, then newest: in a big run the passed finalists are
        # found early (oldest ids), so a plain id-DESC fetch past the limit would drop them.
        sql += " ORDER BY (s.status='rejected'), s.id DESC LIMIT %s OFFSET %s"
    params.extend((limit, offset))
    cur.execute(sql, params)
    return [_strategy_row(r) for r in cur.fetchall()]


def count_strategies(
    cur, user_id: int, direction: Optional[str] = None, market: Optional[str] = None,
    q: Optional[str] = None, deployed: bool = False,
) -> Dict[str, int]:
    """Status histogram for the user's strategies via COUNT(*), so the headline figures
    reflect the true total rather than a capped page. Keys are the status values plus
    "total" (their sum), plus "deployed" (how many have an active deployment). Narrowed by
    direction/market/search/deployed, matching list_strategies (status is left open so every
    status bucket is counted). The seeded example session's strategies are left out of every
    count: a new account read "Rejected (2)" for research it never ran. They still list, so
    "examples" holds them per status for the page's matched/pages math."""
    where, fparams = _strategy_filter_sql(direction, None, market, None, q, deployed)
    sql = ("SELECT s.status, COUNT(*) AS n, SUM(EXISTS (SELECT 1 FROM app_deployments d WHERE d.strategy_id=s.id"
           " AND d.status<>'stopped')) AS dep, SUM(CASE WHEN s.direction=%s THEN 1 ELSE 0 END) AS ex"
           " FROM app_strategies s" + where + " GROUP BY s.status")
    params: List[Any] = [DEMO_DIRECTION, user_id] + fparams
    cur.execute(sql, params)
    rows = cur.fetchall()
    examples = {r["status"]: int(r.get("ex") or 0) for r in rows if int(r.get("ex") or 0)}
    counts: Dict[str, Any] = {r["status"]: int(r["n"]) - examples.get(r["status"], 0) for r in rows}
    counts["total"] = sum(counts.values())
    # Strategies with an active deployment, for the Deployed chip (not a status, so not in total).
    counts["deployed"] = sum(int(r.get("dep") or 0) for r in rows)
    counts["examples"] = examples
    return counts


def passed_strategies(
    cur, user_id: int, direction: Optional[str] = None, market: Optional[str] = None,
    q: Optional[str] = None, deployed: bool = False, paper_passed: Optional[str] = None,
    run_ids: Optional[List[int]] = None, research_since=None,
) -> List[Dict]:
    """Every passed strategy count_strategies counts under the same filters, with only what a later
    verdict is judged on (id, status, market, direction, spec, experiment_id) and its run_id: the list's
    chips count the passes a later check left uncleared across every page, not the 50 shown. One read
    through idx_strat_user (user_id, status).
    `paper_passed` (the gatekeeper's FORWARD_VALIDATED value) also reads the void and rejected strategies
    whose experiment has a paper result of that classification (a probation strategy that passed on
    paper, which the diversification check may then have held back): still one read, the paper row
    probed through idx_res_exp. `run_ids` narrows it to those research sessions (the research list's).
    `research_since` narrows it to the passes strategies_passed_since counts: from research sessions
    started since then (each pass's session probed by primary key), so a headline can take off the
    ones a later check left uncleared from that same count."""
    where, fparams = _strategy_filter_sql(direction, None if paper_passed else "passed", market, None, q, deployed)
    if paper_passed:
        noise = ",".join(["%s"] * len(NOISE_STATUSES))
        where += (" AND s.status IN ('passed',%s) AND (s.status='passed' OR EXISTS (SELECT 1 FROM app_experiment_results x"
                  " WHERE x.experiment_id=s.experiment_id AND x.phase='paper' AND x.classification=%%s))" % noise)
        fparams.extend(NOISE_STATUSES)
        fparams.append(paper_passed)
    if run_ids is not None:
        if not run_ids:
            return []
        where += " AND s.run_id IN (%s)" % ",".join(["%s"] * len(run_ids))
        fparams.extend(int(i) for i in run_ids)
    if research_since is not None:
        where += (" AND EXISTS (SELECT 1 FROM app_agent_runs r WHERE r.id=s.run_id AND r.kind='research'"
                  " AND r.created_at>=%s)")
        fparams.append(research_since)
    cur.execute("SELECT s.id, s.status, s.market, s.direction, s.spec_json, s.experiment_id, s.run_id FROM app_strategies s"
                + where, [user_id] + fparams)
    return [_strategy_row(r) for r in cur.fetchall()]


def delete_strategy(cur, user_id: int, strategy_id: int) -> bool:
    """Remove a strategy from the user's inventory. Caller ensures it isn't deployed."""
    cur.execute("DELETE FROM app_strategies WHERE id=%s AND user_id=%s", (strategy_id, user_id))
    return cur.rowcount > 0


def share_strategy(cur, src_id: int, from_uid: int, to_uid: int) -> Optional[int]:
    """Copy strategy `src_id` (owned by `from_uid`) into `to_uid`'s inventory so it is theirs
    to deploy and cannot be revoked. Returns the new strategy id, or None if the source doesn't
    exist / isn't the sender's, or the recipient already has this exact share."""
    cur.execute(
        "SELECT market, direction, title, thesis, spec_json, status, result_json FROM app_strategies WHERE id=%s AND user_id=%s",
        (src_id, from_uid),
    )
    src = cur.fetchone()
    if not src:
        return None
    cur.execute("SELECT id FROM app_strategies WHERE user_id=%s AND shared_src_id=%s", (to_uid, src_id))
    if cur.fetchone():
        return None  # already shared to this user — idempotent, no duplicate copy
    cur.execute(
        """INSERT INTO app_strategies
             (user_id, run_id, parent_id, market, direction, title, thesis, spec_json, status, result_json,
              created_at, shared_from_user_id, shared_src_id)
           VALUES (%s,NULL,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (to_uid, src["market"], src["direction"], src["title"], src["thesis"], src["spec_json"],
         src["status"], src["result_json"], now_utc(), from_uid, src_id),
    )
    return cur.lastrowid


def get_strategy(cur, user_id: int, strategy_id: int) -> Optional[Dict]:
    cur.execute(
        """SELECT s.id, s.run_id, s.parent_id, s.market, s.direction, s.title, s.thesis, s.spec_json, s.status,
                  s.result_json, s.experiment_id, s.created_at, r.hypotheses_tried, s.shared_from_user_id, su.name AS shared_from_name
           FROM app_strategies s LEFT JOIN app_agent_runs r ON r.id=s.run_id
                LEFT JOIN app_users su ON su.id=s.shared_from_user_id
           WHERE s.id=%s AND s.user_id=%s""",
        (strategy_id, user_id),
    )
    row = cur.fetchone()
    return _strategy_row(row) if row else None


def strategy_records(cur, user_id: int, market: str, limit: int = 500) -> List[Dict]:
    """Raw discovery-tree records for one user+market, OLDEST first: each tested
    hypothesis with its in-sample metrics, (if it was gated) its out-of-sample
    outcome, and its id/parent_id lineage (a dig-deeper strategy points back at the
    strategy it refined). Feeds the Tau-RSI replay simulator (app/trading/replay.py)."""
    cur.execute(
        """SELECT id, parent_id, status, result_json FROM app_strategies
           WHERE user_id=%s AND market=%s ORDER BY id ASC LIMIT %s""",
        (user_id, market, limit),
    )
    out: List[Dict] = []
    for r in cur.fetchall():
        res = _loads(r["result_json"]) or {}
        ins = res.get("in_sample") or {}
        oos = res.get("out_of_sample")
        out.append({
            "id": r.get("id"), "parent_id": r.get("parent_id"),
            "in_sample": {"pnl": ins.get("pnl") or 0, "trades": ins.get("trades") or 0},
            "tested": oos is not None,
            "oos_pnl": (oos or {}).get("pnl") or 0.0,
            "passed": r["status"] == "passed",
        })
    return out
