"""All reads/writes for the rigorous-research ledger (RESEARCH_PIPELINE_DESIGN.md
§B.3-B.5). Lives apart from repository.py so Wave-2 agents don't collide, but
follows the same conventions: every statement takes a cursor, rows come back as
dicts (DictCursor), JSON columns round-trip through _json/_loads, timestamps are
naive UTC via repository.now_utc().

Immutability is enforced by table split, not by triggers:
  - app_experiments and app_experiment_results are INSERT-only here (no UPDATE,
    no DELETE), so the ledger of what was tried and what happened is permanent.
    The ONE exception is preregister re-pointing a re-hit experiment's strategy_id
    linkage (not the frozen spec) at the latest strategy row — see preregister.
  - app_fdr_state is the one UPSERTed table (alpha-wealth *state* advances); the
    per-test audit trail lives on the result rows, not here.
  - partitions supersede via active=0 (save_partition), never by mutation.

This module is DB-access only. The partition *math* (boundary snapping, purge/
embargo, fingerprint) is in app/research/partitions.py; the statistical verdicts are in
app/research/gatekeeper.py. Both call into here for persistence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.markets import MARKETS, Market, cross_product
from app.repository import _json, _loads, now_utc

# -- pre-registration (app_experiments) ---------------------------------------


def experiment_row_by_id(cur, experiment_id: int) -> Optional[Dict]:
    cur.execute("SELECT * FROM app_experiments WHERE id=%s", (int(experiment_id),))
    return cur.fetchone()


def partition_by_id(cur, partition_id: int) -> Optional[Dict]:
    cur.execute("SELECT * FROM app_data_partitions WHERE id=%s", (int(partition_id),))
    return cur.fetchone()


def get_experiment(cur, run_id: Optional[int], hypothesis_hash: str) -> Optional[Dict]:
    """The registered experiment for this (run_id, hypothesis_hash), or None.
    NULL run_id is matched with the <=> null-safe operator."""
    cur.execute(
        "SELECT * FROM app_experiments WHERE hypothesis_hash=%s AND run_id<=>%s LIMIT 1",
        (hypothesis_hash, run_id),
    )
    row = cur.fetchone()
    return _experiment_row(row) if row else None


def preregister(cur, pre: Dict[str, Any]) -> int:
    """Insert an IMMUTABLE app_experiments row (the pre-registration). Idempotent
    on (run_id, hypothesis_hash): re-registering the identical frozen spec returns
    the existing id and inserts nothing. NOTHING about this row is ever UPDATEd.

    `pre` carries the frozen fields (gatekeeper builds it from its Prereg):
    user_id, run_id, market, strategy_id, hypothesis_hash, spec, economic_rationale,
    primary_metric, null_hypothesis, alt_hypothesis, planned_test,
    falsification_criteria, min_sample, cost_assumptions, data_provenance,
    research_partition_id, planned_n_tests, correction_method.
    """
    existing = get_experiment(cur, pre.get("run_id"), pre["hypothesis_hash"])
    if existing:
        # A re-proposed/duplicate hypothesis (common under run_forever + dig-deeper) mints a NEW
        # app_strategies row but re-hits this frozen experiment. Re-point the experiment at the
        # latest strategy_id so experiments_for_strategy(new_id) resolves — otherwise the new
        # strategy renders the shallow Abstract-only paper though its full stats live here. Only
        # the strategy_id LINKAGE moves; the frozen spec/hypothesis/test is never touched, so
        # pre-registration integrity holds.
        new_sid = pre.get("strategy_id")
        if new_sid is not None and int(new_sid) != int(existing.get("strategy_id") or 0):
            cur.execute("UPDATE app_experiments SET strategy_id=%s WHERE id=%s",
                        (int(new_sid), int(existing["id"])))
        return int(existing["id"])
    cur.execute(
        """INSERT INTO app_experiments
             (user_id, run_id, strategy_id, market, hypothesis_hash, spec_json,
              economic_rationale, primary_metric, null_hypothesis, alt_hypothesis,
              planned_test, falsification_criteria, min_sample, cost_assumptions_json,
              data_provenance_json, research_partition_id, planned_n_tests,
              correction_method, registered_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            pre["user_id"], pre.get("run_id"), pre.get("strategy_id"), pre["market"],
            pre["hypothesis_hash"], _json(pre["spec"]), pre["economic_rationale"],
            pre["primary_metric"], pre["null_hypothesis"], pre["alt_hypothesis"],
            pre["planned_test"], pre["falsification_criteria"], int(pre["min_sample"]),
            _json(pre["cost_assumptions"]), _json(pre.get("data_provenance") or {}),
            int(pre["research_partition_id"]),
            int(pre["planned_n_tests"]), pre["correction_method"], now_utc(),
        ),
    )
    return int(cur.lastrowid)


def _experiment_row(r: Optional[Dict]) -> Optional[Dict]:
    if r is None:
        return None
    r["spec"] = _loads(r.pop("spec_json"))
    r["cost_assumptions"] = _loads(r.pop("cost_assumptions_json"))
    r["data_provenance"] = _loads(r.pop("data_provenance_json", None)) or {}
    return r


# -- verdicts (app_experiment_results) -----------------------------------------

# The columns an append_result row may set (besides experiment_id/phase/
# classification/n_trades which are required). Keeps the INSERT honest and the
# caller from having to spell every NULL.
_RESULT_FIELDS = (
    "net_pnl", "mean_net_return", "sharpe", "psr", "dsr", "p_value", "ci_lo",
    "ci_hi", "fdr_alpha_i", "fdr_reject", "bh_reject", "placebo_p",
    "n_trials_audited", "holdout_consumed",
)


# A per-trade return series grows one point per trade and, on long/run_forever windows,
# overruns the server max_allowed_packet (~32 MiB) when stored raw in a JSON column: the
# value truncates and the later json.loads crashes the run ("Unterminated string ...").
# Above this many points we collapse the STORED copy to one point per UTC day (summing
# returns). This is storage/transport only and does NOT weaken any gate: the one consumer
# that reads it back, gatekeeper.marginal_contribution_ok's diversification correlation,
# buckets the series by UTC day (_bucketed/_daily_corr) BEFORE correlating, so a day-summed
# series yields an IDENTICAL correlation to the full per-trade series — the deploy decision
# cannot change. Series under the cap pass through untouched so the research-paper per-trade
# charts keep full resolution. The day-summed form is itself bounded by the number of trading
# days, which cannot approach the packet limit.
_EQUITY_SERIES_CAP = 50_000


def _bounded_series(series: Optional[List]) -> Optional[List]:
    if not series or len(series) <= _EQUITY_SERIES_CAP:
        return series
    daily: Dict[int, float] = {}
    for ts, r in series:
        daily[int(ts) // 86400] = daily.get(int(ts) // 86400, 0.0) + float(r)
    return [[day * 86400, round(v, 8)] for day, v in sorted(daily.items())]


def append_result(cur, experiment_id: int, phase: str, classification: str,
                  n_trades: int, metrics: Optional[Dict[str, Any]] = None,
                  equity_curve: Optional[List] = None, folds: Optional[List] = None) -> int:
    """APPEND one immutable verdict row for a phase evaluation. Never updates an
    existing row — a re-evaluation is a new row, so the full history is preserved.
    `metrics` supplies any of _RESULT_FIELDS; missing ones store NULL. `folds` is the
    per-day/per-fold cross-day breakdown the research-paper page renders."""
    m = metrics or {}
    cols = ["experiment_id", "phase", "classification", "n_trades"]
    vals: List[Any] = [experiment_id, phase, classification, int(n_trades)]
    for f in _RESULT_FIELDS:
        cols.append(f)
        v = m.get(f)
        if f in ("fdr_reject", "bh_reject", "holdout_consumed") and v is not None:
            v = 1 if v else 0
        vals.append(v if f != "holdout_consumed" else (v or 0))
    cols.append("equity_curve_json")
    vals.append(_json(_bounded_series(equity_curve)))
    cols.append("folds_json")
    vals.append(_json(folds))
    cols.append("verdict_at")
    vals.append(now_utc())
    placeholders = ",".join(["%s"] * len(vals))
    cur.execute(
        "INSERT INTO app_experiment_results (%s) VALUES (%s)" % (",".join(cols), placeholders),
        tuple(vals),
    )
    return int(cur.lastrowid)


def results_for_experiment(cur, experiment_id: int, phase: Optional[str] = None) -> List[Dict]:
    """Every verdict row for an experiment, oldest first. Filtered by phase if given."""
    if phase:
        cur.execute(
            "SELECT * FROM app_experiment_results WHERE experiment_id=%s AND phase=%s ORDER BY id",
            (experiment_id, phase),
        )
    else:
        cur.execute(
            "SELECT * FROM app_experiment_results WHERE experiment_id=%s ORDER BY id",
            (experiment_id,),
        )
    return [_result_row(r) for r in cur.fetchall()]


def _result_row(r: Dict) -> Dict:
    if "equity_curve_json" in r:
        r["equity_curve"] = _loads(r.pop("equity_curve_json"))
    if "folds_json" in r:
        r["folds"] = _loads(r.pop("folds_json"))
    return r


# -- online-FDR state (app_fdr_state) — the one UPSERTed table -----------------


def get_fdr_state(cur, user_id: int, market: str) -> Optional[Dict]:
    """The LORD++ alpha-wealth state for this (user, market) stream, or None if
    the stream hasn't started. rejections_json is parsed to a list."""
    cur.execute(
        "SELECT * FROM app_fdr_state WHERE user_id=%s AND market=%s",
        (user_id, market),
    )
    row = cur.fetchone()
    if not row:
        return None
    row["rejections"] = _loads(row.pop("rejections_json")) or []
    return row


def set_fdr_state(cur, user_id: int, market: str, state: Dict[str, Any]) -> None:
    """Upsert the alpha-wealth state (advance wealth/t/rejections). `state` is the
    plain dict the stats layer persists: alpha, w0, wealth, t, rejections, method, plus the
    gatekeeper's `epoch_to_ts` (end of the validation window the stream is spending on)."""
    cur.execute(
        """INSERT INTO app_fdr_state
             (user_id, market, method, alpha, w0, wealth, t, rejections_json, updated_at, epoch_to_ts)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE method=VALUES(method), alpha=VALUES(alpha),
             w0=VALUES(w0), wealth=VALUES(wealth), t=VALUES(t),
             rejections_json=VALUES(rejections_json), updated_at=VALUES(updated_at),
             epoch_to_ts=VALUES(epoch_to_ts)""",
        (
            user_id, market, state.get("method", "LORD++"), float(state["alpha"]),
            float(state["w0"]), float(state["wealth"]), int(state["t"]),
            _json(list(state.get("rejections", []))), now_utc(),
            int(state["epoch_to_ts"]) if state.get("epoch_to_ts") is not None else None,
        ),
    )


# -- locked-holdout ledger (app_holdout_ledger) --------------------------------


def get_holdout_ledger(cur, market: str, partition_id: int) -> Optional[Dict]:
    cur.execute(
        "SELECT * FROM app_holdout_ledger WHERE market=%s AND partition_id=%s LIMIT 1",
        (market, partition_id),
    )
    return cur.fetchone()


def ensure_holdout_ledger(cur, market: str, partition_id: int, window_fingerprint: str,
                          max_evaluations: int) -> Dict:
    """Return the holdout ledger row for this partition, creating it (consumed=0,
    evaluations_used=0) if absent. Idempotent on window_fingerprint."""
    row = get_holdout_ledger(cur, market, partition_id)
    if row:
        return row
    cur.execute(
        """INSERT INTO app_holdout_ledger
             (market, partition_id, window_fingerprint, evaluations_used, max_evaluations, consumed)
           VALUES (%s,%s,%s,0,%s,0)
           ON DUPLICATE KEY UPDATE market=VALUES(market)""",
        (market, partition_id, window_fingerprint, int(max_evaluations)),
    )
    return get_holdout_ledger(cur, market, partition_id)


def record_holdout_use(cur, ledger_id: int) -> Dict:
    """Spend ONE holdout evaluation. REFUSES (returns {"ok": False, ...}) when the
    holdout is already consumed or evaluations_used has reached max_evaluations —
    the one-way latch the design calls sacred. On success increments
    evaluations_used, flips consumed=1 when it reaches max_evaluations, stamps the
    first/last-used timestamps, and returns {"ok": True, ...}."""
    cur.execute("SELECT * FROM app_holdout_ledger WHERE id=%s", (ledger_id,))
    row = cur.fetchone()
    if not row:
        return {"ok": False, "reason": "no_such_ledger"}
    used = int(row["evaluations_used"])
    cap = int(row["max_evaluations"])
    if int(row["consumed"]) == 1 or used >= cap:
        return {"ok": False, "reason": "holdout_consumed", "evaluations_used": used,
                "max_evaluations": cap, "consumed": 1}
    used += 1
    consumed = 1 if used >= cap else 0
    now = now_utc()
    first = row["first_used_at"] or now
    cur.execute(
        """UPDATE app_holdout_ledger
             SET evaluations_used=%s, consumed=%s, first_used_at=%s, last_used_at=%s
           WHERE id=%s""",
        (used, consumed, first, now, ledger_id),
    )
    return {"ok": True, "evaluations_used": used, "max_evaluations": cap, "consumed": consumed}


# -- data partitions (app_data_partitions) -------------------------------------


def get_active_partition(cur, market: str) -> Optional[Dict]:
    cur.execute(
        "SELECT * FROM app_data_partitions WHERE market=%s AND active=1 ORDER BY id DESC LIMIT 1",
        (market,),
    )
    return cur.fetchone()


def save_partition(cur, market: str, b: Dict[str, Any]) -> Dict:
    """Freeze a new active partition, superseding any current active one for the
    market (active=0, kept for audit). `b` is the boundary dict from partitions.py.
    Returns the inserted row (with its id)."""
    cur.execute("UPDATE app_data_partitions SET active=0 WHERE market=%s AND active=1", (market,))
    cur.execute(
        """INSERT INTO app_data_partitions
             (market, research_from_ts, research_to_ts, validation_from_ts, validation_to_ts,
              holdout_from_ts, holdout_to_ts, embargo_seconds, purge_seconds,
              data_fingerprint, frozen_at, active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
        (
            market, b["research_from_ts"], b["research_to_ts"], b["validation_from_ts"],
            b["validation_to_ts"], b["holdout_from_ts"], b["holdout_to_ts"],
            b["embargo_seconds"], b["purge_seconds"], b["data_fingerprint"], now_utc(),
        ),
    )
    pid = int(cur.lastrowid)
    cur.execute("SELECT * FROM app_data_partitions WHERE id=%s", (pid,))
    return cur.fetchone()


# -- raw history for the partition math + dataset loaders ----------------------


def partition_contracts(cur, market: Market, since: datetime) -> List[Dict]:
    """Settled contracts for the market since `since`, as {ticker, open_ts,
    close_ts, result}. Drives boundary snapping and the data fingerprint. Only
    candles_done=1 rows (same filter the backtester's load_history uses)."""
    cur.execute(
        """SELECT ticker, open_time, close_time, result FROM hist_markets
           WHERE series_ticker=%s AND close_time >= %s AND candles_done=1
           ORDER BY open_time, ticker""",
        (market.series, since),
    )
    out = []
    for r in cur.fetchall():
        out.append({
            "ticker": r["ticker"],
            "open_ts": _ts(r["open_time"]),
            "close_ts": _ts(r["close_time"]),
            "result": r["result"],
        })
    if market.data_from_ts:   # a tick-sourced market: contracts before its archive have no data
        out = [c for c in out if c["open_ts"] >= market.data_from_ts]
    return out


def partition_source_rows(cur, market: Market, since: datetime,
                          open_from_ts: Optional[int] = None, open_to_ts: Optional[int] = None,
                          max_candle_rows: Optional[int] = None) -> Dict[str, List]:
    """Everything backtest.build_dataset needs, plus open_ts on each market row so
    partitions.py can assign whole contracts to a window. Reuses repository.
    load_history for candles/btc (no SQL duplicated) and adds the open times.
    With a window, only contracts opening in [open_from_ts, open_to_ts) are loaded, and the
    candle query is bounded to their close times. `max_candle_rows` keeps the window's most
    recent whole events whose estimated candle count fits (see cap_recent_events)."""
    from app import repository as repo
    contracts = partition_contracts(cur, market, since)
    opens = {c["ticker"]: c["open_ts"] for c in contracts}
    tickers, until = None, None
    if open_from_ts is not None and open_to_ts is not None:
        window = [c for c in contracts if c["open_ts"] is not None and open_from_ts <= c["open_ts"] < open_to_ts]
        if max_candle_rows:
            window = cap_recent_events(window, market.candle_minutes, max_candle_rows)
        tickers = {c["ticker"] for c in window}
        if window:
            # Same rows, far less scanned: nothing outside the kept contracts' close times is read.
            first_open = min(c["open_ts"] for c in window)
            since = max(since, _dt(first_open, since))
            until = _dt(max(c["close_ts"] for c in window), since)
    h = repo.load_history(cur, market.series, market.candle_minutes, since, market.underlying, tickers, until,
                          cross=cross_product(market))
    for m in h["markets"]:
        m["open_ts"] = opens.get(m["ticker"])
    return h


def _event(ticker: str) -> str:
    return ticker.rsplit("-", 1)[0]


def cap_recent_events(contracts: List[Dict], candle_minutes: int, max_rows: int) -> List[Dict]:
    """The most recent whole events (by latest open) whose contracts' estimated candle rows, one per
    candle_minutes over each contract's open->close life, fit max_rows. An upper bound: a 1-minute
    series with 18k listed contracts (KXNCAAFSPREAD) can't be loaded inside the step limit or the
    worker's memory, so research sees its latest slice instead of failing. Always keeps one event."""
    events: Dict[str, List[Dict]] = {}
    for c in contracts:
        events.setdefault(_event(c["ticker"]), []).append(c)
    order = sorted(events.values(), key=lambda cs: max(c["open_ts"] for c in cs), reverse=True)
    step = max(60, int(candle_minutes) * 60)
    kept: List[Dict] = []
    rows = 0
    for cs in order:
        n = sum(max(1, (c["close_ts"] - c["open_ts"]) // step) for c in cs)
        if kept and rows + n > max_rows:
            break
        kept.extend(cs)
        rows += n
    return sorted(kept, key=lambda c: (c["open_ts"], c["ticker"]))


def _dt(ts: int, like: datetime) -> datetime:
    """ts as a datetime with the same tz-awareness as `like` (hist_markets holds naive UTC)."""
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return d if like.tzinfo is not None else d.replace(tzinfo=None)


def _ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp()) if dt.tzinfo is None else int(dt.timestamp())


# -- replay / research-paper reads ---------------------------------------------


def validated_trials_overlapping(cur, user_id: int, market: str, window_from_ts: int) -> int:
    """How many of this user's experiments on `market` were validation-judged on a window that
    still overlaps a validation window starting at `window_from_ts` (their frozen partition's
    validation_to_ts is after it). These are the trials that competed for the current evidence:
    the gatekeeper's DSR deflates for exactly this count. An experiment whose partition row is
    missing is counted (conservative: unknown evidence is assumed to overlap)."""
    cur.execute(
        """SELECT COUNT(DISTINCT e.id) AS n
             FROM app_experiments e
             JOIN app_experiment_results r ON r.experiment_id=e.id AND r.phase='validation'
             LEFT JOIN app_data_partitions p ON p.id=e.research_partition_id
            WHERE e.user_id=%s AND e.market=%s
              AND (p.id IS NULL OR p.validation_to_ts > %s)""",
        (user_id, market, int(window_from_ts)),
    )
    row = cur.fetchone()
    return int((row or {}).get("n") or 0)


def holdout_evaluations_overlapping(cur, market: str, holdout_from_ts: int) -> int:
    """Total one-time holdout looks already spent on `market` across every frozen partition whose
    holdout window still overlaps a holdout starting at `holdout_from_ts`. Partitions re-freeze as
    contracts settle, so the per-ledger cap must be enforced over overlapping windows too. A
    ledger whose partition row is missing is counted (conservative)."""
    cur.execute(
        """SELECT COALESCE(SUM(h.evaluations_used), 0) AS n
             FROM app_holdout_ledger h
             LEFT JOIN app_data_partitions p ON p.id=h.partition_id
            WHERE h.market=%s AND (p.id IS NULL OR p.holdout_to_ts > %s)""",
        (market, int(holdout_from_ts)),
    )
    row = cur.fetchone()
    return int((row or {}).get("n") or 0)


def experiment_records_for_replay(cur, user_id: int, market: str) -> List[Dict]:
    """Experiments with their latest VALIDATION verdict, for replay.build_tree —
    so the discovery tree is scored on gatekeeper-recorded validation outcomes,
    NOT the old reused OOS (closes Leak 2/5). One row per experiment that has a
    validation result: {experiment_id, strategy_id, parent_id, hypothesis_hash,
    market, classification, n_trades, net_pnl, mean_net_return}. An underpowered verdict (no
    p-value) reads as net_pnl NULL here even though the row records its P&L for paper probation:
    an unmeasured sample is not a validation outcome the optimizer should learn from.

    `strategy_id`/`parent_id` carry the DISCOVERY-TREE lineage (a refinement's strategy
    points back at the strategy it dug deeper on, via app_strategies.parent_id), so
    replay.build_tree can traverse real parent->child branches instead of a flat list.
    LEFT JOIN: an experiment whose strategy row is gone just has parent_id NULL (a root)."""
    cur.execute(
        """SELECT e.id AS experiment_id, e.strategy_id, s.parent_id, e.hypothesis_hash, e.market,
                  r.classification, r.n_trades,
                  CASE WHEN r.p_value IS NULL THEN NULL ELSE r.net_pnl END AS net_pnl, r.mean_net_return
             FROM app_experiments e
             JOIN app_experiment_results r ON r.experiment_id=e.id
             JOIN (SELECT experiment_id, MAX(id) AS mx FROM app_experiment_results
                     WHERE phase='validation' GROUP BY experiment_id) last
               ON last.experiment_id=e.id AND last.mx=r.id
             LEFT JOIN app_strategies s ON s.id=e.strategy_id
            WHERE e.user_id=%s AND e.market=%s
            ORDER BY e.id""",
        (user_id, market),
    )
    return cur.fetchall()


def experiment_by_id(cur, experiment_id: int) -> Optional[Dict]:
    """The experiment with this id plus all its verdict rows. The robust lookup for the
    research-paper page: a strategy stores the id of the experiment it was validated under, so
    this resolves ITS own experiment even after a re-hit re-pointed app_experiments.strategy_id
    at a later strategy row. {"experiment": {...}, "results": [...]} or None."""
    cur.execute("SELECT * FROM app_experiments WHERE id=%s LIMIT 1", (experiment_id,))
    exp = _experiment_row(cur.fetchone())
    if not exp:
        return None
    return {"experiment": exp, "results": results_for_experiment(cur, int(exp["id"]))}


def probation_candidates(cur, user_id: int, max_p: float, min_trades: int, limit: int = 20) -> List[Dict]:
    """Strategies whose LATEST validation verdict was a near miss: positive net P&L on unseen data
    and a p-value at or below `max_p`, over at least `min_trades` trades, best p first. Read-only."""
    cur.execute(
        """SELECT e.strategy_id, e.market, r.p_value, r.net_pnl, r.n_trades
           FROM app_experiment_results r
           JOIN app_experiments e ON e.id = r.experiment_id
           WHERE e.user_id=%s AND e.strategy_id IS NOT NULL AND r.phase='validation'
             AND r.id = (SELECT MAX(r2.id) FROM app_experiment_results r2
                         WHERE r2.experiment_id = r.experiment_id AND r2.phase='validation')
             AND r.net_pnl > 0 AND r.p_value IS NOT NULL AND r.p_value <= %s AND r.n_trades >= %s
           ORDER BY r.p_value ASC, r.id DESC LIMIT %s""",
        (user_id, float(max_p), int(min_trades), int(limit)),
    )
    return [{"strategy_id": int(r["strategy_id"]), "market": r["market"], "p_value": float(r["p_value"]),
             "net_pnl": float(r["net_pnl"]), "n_trades": int(r["n_trades"])} for r in cur.fetchall()]


def underpowered_candidates(cur, user_id: int, min_trades: int, limit: int = 20) -> List[Dict]:
    """Strategies whose LATEST validation verdict was inconclusive for lack of sample: no p-value
    (below the gate's min sample) over at least `min_trades` trades. Not rejected, just unmeasured,
    so a forward paper test is the cheapest way to measure them. `net_pnl` is the validation P&L
    the gatekeeper recorded (None on rows written before it did). Newest first. Read-only."""
    cur.execute(
        """SELECT e.strategy_id, e.market, r.n_trades, r.net_pnl
           FROM app_experiment_results r
           JOIN app_experiments e ON e.id = r.experiment_id
           WHERE e.user_id=%s AND e.strategy_id IS NOT NULL AND r.phase='validation'
             AND r.id = (SELECT MAX(r2.id) FROM app_experiment_results r2
                         WHERE r2.experiment_id = r.experiment_id AND r2.phase='validation')
             AND r.classification='inconclusive' AND r.p_value IS NULL AND r.n_trades >= %s
           ORDER BY r.id DESC LIMIT %s""",
        (user_id, int(min_trades), int(limit)),
    )
    return [{"strategy_id": int(r["strategy_id"]), "market": r["market"], "p_value": None,
             "net_pnl": None if r["net_pnl"] is None else float(r["net_pnl"]),
             "n_trades": int(r["n_trades"] or 0)} for r in cur.fetchall()]


def experiments_for_strategy(cur, strategy_id: int, experiment_id: Optional[int] = None) -> Optional[Dict]:
    """The experiment behind a strategy plus all its verdict rows, for the research-paper page
    (§D). {"experiment": {...}, "results": [...]} or None. Resolves by the strategy's stored
    `experiment_id` first (robust 1:1 link), falling back to the legacy strategy_id lookup so
    strategies written before the link existed still resolve."""
    if experiment_id:
        rec = experiment_by_id(cur, int(experiment_id))
        if rec:
            return rec
    cur.execute("SELECT * FROM app_experiments WHERE strategy_id=%s ORDER BY id DESC LIMIT 1", (strategy_id,))
    exp = _experiment_row(cur.fetchone())
    if not exp:
        return None
    return {"experiment": exp, "results": results_for_experiment(cur, int(exp["id"]))}
