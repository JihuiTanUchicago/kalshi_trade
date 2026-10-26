"""Tests for app.research_repository against an in-memory fake cursor (no live
DB), extending the FakeCursor idea in tests/conftest.py to the four new ledger
tables. Covers the immutability contract (INSERT-only experiments/results),
fdr-state round-trip, and the holdout one-way latch.
"""
from datetime import datetime

import pytest

from app import research_repository as rr


class LedgerCursor:
    """Minimal in-memory stand-in for a DictCursor over the research-ledger
    tables. Each table is a list of dict rows with an auto-increment id; SELECT *
    returns copies so repository-layer .pop() can't corrupt stored rows."""

    def __init__(self):
        self.t = {k: [] for k in (
            "app_experiments", "app_experiment_results", "app_fdr_state",
            "app_holdout_ledger", "app_data_partitions", "hist_markets")}
        self.lastrowid = None
        self._last = None

    # -- helpers --
    def _ins(self, table, row):
        row = dict(row)
        row["id"] = len(self.t[table]) + 1
        self.t[table].append(row)
        self.lastrowid = row["id"]
        return row

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        p = params
        self._last = None

        # -- app_experiments --
        if s.startswith("SELECT * FROM app_experiments WHERE hypothesis_hash=%s AND run_id<=>%s"):
            h, rid = p
            self._last = [dict(r) for r in self.t["app_experiments"]
                          if r["hypothesis_hash"] == h and r["run_id"] == rid]
        elif s.startswith("SELECT * FROM app_experiments WHERE id=%s"):
            self._last = [dict(r) for r in self.t["app_experiments"] if r["id"] == p[0]][:1]
        elif s.startswith("SELECT * FROM app_experiments WHERE strategy_id=%s"):
            sid = p[0]
            rows = [dict(r) for r in self.t["app_experiments"] if r["strategy_id"] == sid]
            self._last = sorted(rows, key=lambda r: -r["id"])[:1]
        elif s.startswith("INSERT INTO app_experiments"):
            cols = _insert_cols(s)
            self._ins("app_experiments", dict(zip(cols, p)))
        elif s.startswith("UPDATE app_experiments SET strategy_id=%s WHERE id=%s"):
            sid, eid = p
            next(r for r in self.t["app_experiments"] if r["id"] == eid)["strategy_id"] = sid
        # -- app_experiment_results --
        elif s.startswith("INSERT INTO app_experiment_results"):
            cols = _insert_cols(s)
            self._ins("app_experiment_results", dict(zip(cols, p)))
        elif s.startswith("SELECT * FROM app_experiment_results WHERE experiment_id=%s AND phase=%s"):
            eid, phase = p
            self._last = [dict(r) for r in self.t["app_experiment_results"]
                          if r["experiment_id"] == eid and r["phase"] == phase]
        elif s.startswith("SELECT * FROM app_experiment_results WHERE experiment_id=%s"):
            eid = p[0]
            self._last = [dict(r) for r in self.t["app_experiment_results"] if r["experiment_id"] == eid]
        # -- app_fdr_state --
        elif s.startswith("SELECT * FROM app_fdr_state WHERE user_id=%s AND market=%s"):
            uid, mk = p
            self._last = [dict(r) for r in self.t["app_fdr_state"]
                          if r["user_id"] == uid and r["market"] == mk]
        elif s.startswith("INSERT INTO app_fdr_state"):
            uid, mk, method, alpha, w0, wealth, t, rej, upd, epoch_to = p
            existing = next((r for r in self.t["app_fdr_state"]
                             if r["user_id"] == uid and r["market"] == mk), None)
            vals = dict(user_id=uid, market=mk, method=method, alpha=alpha, w0=w0,
                        wealth=wealth, t=t, rejections_json=rej, updated_at=upd, epoch_to_ts=epoch_to)
            if existing:
                existing.update(vals)
            else:
                self._ins("app_fdr_state", vals)
        # -- app_holdout_ledger --
        elif s.startswith("SELECT * FROM app_holdout_ledger WHERE market=%s AND partition_id=%s"):
            mk, pid = p
            self._last = [dict(r) for r in self.t["app_holdout_ledger"]
                          if r["market"] == mk and r["partition_id"] == pid]
        elif s.startswith("SELECT * FROM app_holdout_ledger WHERE id=%s"):
            self._last = [dict(r) for r in self.t["app_holdout_ledger"] if r["id"] == p[0]]
        elif s.startswith("INSERT INTO app_holdout_ledger"):
            mk, pid, fp, maxev = p
            self._ins("app_holdout_ledger", dict(
                market=mk, partition_id=pid, window_fingerprint=fp, evaluations_used=0,
                max_evaluations=maxev, consumed=0, first_used_at=None, last_used_at=None))
        elif s.startswith("UPDATE app_holdout_ledger SET evaluations_used=%s"):
            used, consumed, first, last, lid = p
            row = next(r for r in self.t["app_holdout_ledger"] if r["id"] == lid)
            row.update(evaluations_used=used, consumed=consumed, first_used_at=first, last_used_at=last)
        # -- app_data_partitions --
        elif s.startswith("SELECT * FROM app_data_partitions WHERE market=%s AND active=1"):
            mk = p[0]
            rows = [dict(r) for r in self.t["app_data_partitions"] if r["market"] == mk and r["active"] == 1]
            self._last = sorted(rows, key=lambda r: -r["id"])[:1]
        elif s.startswith("UPDATE app_data_partitions SET active=0"):
            mk = p[0]
            for r in self.t["app_data_partitions"]:
                if r["market"] == mk and r["active"] == 1:
                    r["active"] = 0
        elif s.startswith("INSERT INTO app_data_partitions"):
            cols = _insert_cols(s)
            # the SQL ends with ", active) VALUES (...,1)" so active isn't a param
            row = dict(zip(cols, p))
            row["active"] = 1
            self._ins("app_data_partitions", row)
        elif s.startswith("SELECT * FROM app_data_partitions WHERE id=%s"):
            self._last = [dict(r) for r in self.t["app_data_partitions"] if r["id"] == p[0]]
        elif s.startswith("SELECT COUNT(DISTINCT e.id) AS n FROM app_experiments e"):
            uid, mk, wfrom = p
            parts = {r["id"]: r for r in self.t["app_data_partitions"]}
            judged = {r["experiment_id"] for r in self.t["app_experiment_results"] if r["phase"] == "validation"}
            n = 0
            for e in self.t["app_experiments"]:
                if e["user_id"] != uid or e["market"] != mk or e["id"] not in judged:
                    continue
                part = parts.get(e.get("research_partition_id"))
                if part is None or part["validation_to_ts"] > wfrom:
                    n += 1
            self._last = [{"n": n}]
        elif s.startswith("SELECT COALESCE(SUM(h.evaluations_used), 0) AS n FROM app_holdout_ledger h"):
            mk, hfrom = p
            parts = {r["id"]: r for r in self.t["app_data_partitions"]}
            n = 0
            for h in self.t["app_holdout_ledger"]:
                part = parts.get(h["partition_id"])
                if h["market"] == mk and (part is None or part["holdout_to_ts"] > hfrom):
                    n += h["evaluations_used"]
            self._last = [{"n": n}]
        # -- hist_markets (partition_contracts) --
        elif s.startswith("SELECT ticker, open_time, close_time, result FROM hist_markets"):
            series, since = p[0], p[1]
            rows = [dict(r) for r in self.t["hist_markets"]
                    if r["series_ticker"] == series and r["close_time"] >= since]
            self._last = sorted(rows, key=lambda r: (r["open_time"], r["ticker"]))
        else:
            raise NotImplementedError("unhandled SQL: " + s[:120])

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return self._last or []


def _insert_cols(s):
    """Column names from 'INSERT INTO t (a,b,c) VALUES ...'."""
    inside = s[s.index("(") + 1:s.index(")")]
    return [c.strip() for c in inside.split(",")]


# -- fixtures / builders -------------------------------------------------------


def _prereg(hash_="h1", run_id=7, strategy_id=11):
    return dict(
        user_id=1, run_id=run_id, strategy_id=strategy_id, market="btc15m",
        hypothesis_hash=hash_, spec={"a": 1}, economic_rationale="retail longshot bias",
        primary_metric="mean_net_return_per_trade", null_hypothesis="edge<=0",
        alt_hypothesis="edge>0", planned_test="stationary_bootstrap",
        falsification_criteria="ci_lo<=0", min_sample=30,
        cost_assumptions={"fee": "kalshi_taker"}, research_partition_id=3,
        planned_n_tests=5, correction_method="BH",
        data_provenance={"features": ["ob_imbalance", "spot"], "sources": ["model_features_1m"]},
    )


@pytest.fixture
def cur():
    return LedgerCursor()


# -- preregister idempotency ---------------------------------------------------


def test_preregister_idempotent_on_run_and_hash(cur):
    first = rr.preregister(cur, _prereg())
    second = rr.preregister(cur, _prereg())  # identical frozen spec
    assert first == second
    assert len(cur.t["app_experiments"]) == 1  # no duplicate row


def test_preregister_distinct_hash_inserts_new_row(cur):
    a = rr.preregister(cur, _prereg(hash_="h1"))
    b = rr.preregister(cur, _prereg(hash_="h2"))
    assert a != b
    assert len(cur.t["app_experiments"]) == 2


def test_preregister_idempotent_hit_repoints_strategy_id(cur):
    # A re-proposed hypothesis (same run+hash) mints a NEW strategy row; the experiment must be
    # re-pointed at it so experiments_for_strategy(new_id) resolves (else: shallow-paper bug).
    first = rr.preregister(cur, _prereg(strategy_id=11))
    second = rr.preregister(cur, _prereg(strategy_id=22))  # same frozen spec, new strategy row
    assert first == second                                   # still idempotent (no dup experiment)
    assert len(cur.t["app_experiments"]) == 1
    assert cur.t["app_experiments"][0]["strategy_id"] == 22   # linkage moved to the latest
    assert rr.experiments_for_strategy(cur, 22) is not None   # new strategy's paper resolves
    # the frozen spec is untouched — only the strategy_id linkage moved
    assert rr.get_experiment(cur, 7, "h1")["spec"] == {"a": 1}


def test_experiments_for_strategy_resolves_by_stored_experiment_id(cur):
    # After a re-hit re-points app_experiments.strategy_id at the LATEST strategy (22), the earlier
    # strategy (11) no longer resolves by the legacy strategy_id lookup — but its stored
    # experiment_id does, so its research-paper page still renders deep (not the shallow fallback).
    eid = rr.preregister(cur, _prereg(strategy_id=11))
    rr.preregister(cur, _prereg(strategy_id=22))               # same frozen spec re-points to 22
    assert rr.experiments_for_strategy(cur, 11) is None        # legacy lookup: 11 lost the link
    assert rr.experiments_for_strategy(cur, 11, eid) is not None  # stored experiment_id resolves
    assert rr.experiment_by_id(cur, eid)["experiment"]["id"] == eid
    assert rr.experiment_by_id(cur, 999) is None               # unknown id -> None, no error


def test_get_experiment_parses_json(cur):
    rr.preregister(cur, _prereg())
    exp = rr.get_experiment(cur, 7, "h1")
    assert exp["spec"] == {"a": 1}
    assert exp["cost_assumptions"] == {"fee": "kalshi_taker"}


def test_data_provenance_recorded_in_ledger(cur):
    rr.preregister(cur, _prereg())
    exp = rr.get_experiment(cur, 7, "h1")
    # the features/data sources the hypothesis used are persisted and read back
    assert exp["data_provenance"] == {"features": ["ob_imbalance", "spot"],
                                      "sources": ["model_features_1m"]}


def test_data_provenance_defaults_to_empty(cur):
    pre = _prereg(hash_="h9")
    pre.pop("data_provenance")  # a prereg that omits it still registers
    rr.preregister(cur, pre)
    assert rr.get_experiment(cur, 7, "h9")["data_provenance"] == {}


# -- append_result is append-only ----------------------------------------------


def test_append_result_never_updates(cur):
    eid = rr.preregister(cur, _prereg())
    r1 = rr.append_result(cur, eid, "validation", "inconclusive", 12,
                          metrics={"p_value": 0.4, "fdr_reject": False})
    r2 = rr.append_result(cur, eid, "validation", "statistically_supported", 40,
                          metrics={"p_value": 0.01, "fdr_reject": True})
    assert r1 != r2
    rows = rr.results_for_experiment(cur, eid, phase="validation")
    assert len(rows) == 2  # second eval appended, did not overwrite the first
    assert rows[0]["classification"] == "inconclusive"
    assert rows[1]["classification"] == "statistically_supported"
    assert rows[0]["n_trades"] == 12 and rows[0]["p_value"] == 0.4


def test_append_result_coerces_bools_and_defaults_nulls(cur):
    eid = rr.preregister(cur, _prereg())
    rr.append_result(cur, eid, "holdout", "rejected", 5)
    row = rr.results_for_experiment(cur, eid)[0]
    assert row["net_pnl"] is None and row["psr"] is None  # unset -> NULL
    assert row["holdout_consumed"] == 0                    # NOT NULL default


# -- bounded equity series (Bug 1: 32 MiB JSON truncation) ---------------------


def test_small_equity_series_stored_verbatim():
    # Under the cap: per-trade resolution preserved exactly (so the paper charts don't degrade).
    series = [[1_700_000_000 + i * 3600, round(0.01 * i, 8)] for i in range(100)]
    assert rr._bounded_series(series) is series
    assert rr._bounded_series(None) is None
    assert rr._bounded_series([]) == []


def test_huge_equity_series_is_bounded_and_round_trips(cur):
    # A run_forever series of 60k trades over 200 days would overrun max_allowed_packet stored raw.
    days, per_day = 200, 300
    series = [[d * 86400 + t * 60, round(((d * 7 + t) % 11) * 0.001 - 0.005, 8)]
              for d in range(days) for t in range(per_day)]
    assert len(series) > rr._EQUITY_SERIES_CAP
    bounded = rr._bounded_series(series)
    assert len(bounded) == days                      # collapsed to one point per day
    eid = rr.preregister(cur, _prereg())
    rr.append_result(cur, eid, "validation", "inconclusive", len(series), equity_curve=series)
    stored = rr.results_for_experiment(cur, eid, "validation")[-1]["equity_curve"]
    assert stored == bounded                         # read-back parses (no truncation) and matches


def test_bounded_series_does_not_change_gate_correlation(cur):
    # RIGOR: marginal_contribution_ok correlates the STORED series via gatekeeper._daily_corr,
    # which buckets by UTC day first. Day-summing the stored copy must leave that correlation
    # IDENTICAL to the full per-trade series, so no deploy decision can flip from the cap.
    from app.research import gatekeeper as gk
    days, per_day = 150, 400                         # > cap, forces the day-bucket path
    # Per-trade returns vary with the DAY (plus per-trade jitter) so daily sums have real
    # day-to-day variance and genuine comovement — otherwise the correlation is a trivial 0.
    a = [[d * 86400 + t * 30, round(((d % 7) - 3) * 0.0001 + ((t % 3) - 1) * 0.00002, 8)]
         for d in range(days) for t in range(per_day)]
    b = [[d * 86400 + t * 30, round(((d % 7) - 3) * 0.00008 + ((t % 5) - 2) * 0.00001, 8)]
         for d in range(days) for t in range(per_day)]
    full_corr = gk._daily_corr(a, b)
    bounded_corr = gk._daily_corr(rr._bounded_series(a), rr._bounded_series(b))
    # Identical up to 8-decimal rounding of the day sums (far below any gate's sensitivity).
    assert abs(full_corr - bounded_corr) < 1e-6      # gate input unchanged
    assert abs(full_corr) > 0.01                      # non-degenerate: the test actually exercises corr


# -- fdr state round-trip ------------------------------------------------------


def test_fdr_state_round_trips(cur):
    assert rr.get_fdr_state(cur, 1, "btc15m") is None
    state = {"method": "LORD++", "alpha": 0.1, "w0": 0.05, "wealth": 0.03, "t": 4,
             "rejections": [1, 3]}
    rr.set_fdr_state(cur, 1, "btc15m", state)
    got = rr.get_fdr_state(cur, 1, "btc15m")
    assert got["alpha"] == 0.1 and got["w0"] == 0.05 and got["wealth"] == 0.03
    assert got["t"] == 4 and got["rejections"] == [1, 3]


def test_fdr_state_upsert_advances(cur):
    rr.set_fdr_state(cur, 1, "btc15m", {"alpha": 0.1, "w0": 0.05, "wealth": 0.05, "t": 1, "rejections": []})
    rr.set_fdr_state(cur, 1, "btc15m", {"alpha": 0.1, "w0": 0.05, "wealth": 0.02, "t": 2, "rejections": [2]})
    got = rr.get_fdr_state(cur, 1, "btc15m")
    assert got["t"] == 2 and got["rejections"] == [2]
    assert len(cur.t["app_fdr_state"]) == 1  # one stream row, upserted


# -- holdout one-way latch -----------------------------------------------------


def test_holdout_refuses_past_max_evaluations(cur):
    led = rr.ensure_holdout_ledger(cur, "btc_daily", 3, "fp-daily", max_evaluations=2)
    lid = led["id"]
    assert rr.record_holdout_use(cur, lid)["ok"] is True   # 1/2
    r2 = rr.record_holdout_use(cur, lid)                   # 2/2 -> consumes
    assert r2["ok"] is True and r2["consumed"] == 1
    r3 = rr.record_holdout_use(cur, lid)                   # over the cap
    assert r3["ok"] is False and r3["reason"] == "holdout_consumed"


def test_holdout_refuses_when_already_consumed(cur):
    led = rr.ensure_holdout_ledger(cur, "btc15m", 1, "fp-15m", max_evaluations=1)
    assert rr.record_holdout_use(cur, led["id"])["ok"] is True
    assert rr.record_holdout_use(cur, led["id"])["ok"] is False  # consumed latch


def test_ensure_holdout_ledger_idempotent(cur):
    a = rr.ensure_holdout_ledger(cur, "btc15m", 1, "fp-15m", 10)
    b = rr.ensure_holdout_ledger(cur, "btc15m", 1, "fp-15m", 10)
    assert a["id"] == b["id"]
    assert len(cur.t["app_holdout_ledger"]) == 1


def test_record_holdout_use_no_such_ledger(cur):
    assert rr.record_holdout_use(cur, 999)["ok"] is False


# -- evidence-epoch queries ----------------------------------------------------


def test_fdr_state_round_trips_epoch(cur):
    rr.set_fdr_state(cur, 1, "btc15m", {"alpha": 0.1, "w0": 0.05, "wealth": 0.05, "t": 1,
                                        "rejections": [], "epoch_to_ts": 1_700_000_000})
    assert rr.get_fdr_state(cur, 1, "btc15m")["epoch_to_ts"] == 1_700_000_000
    rr.set_fdr_state(cur, 1, "btc15m", {"alpha": 0.1, "w0": 0.05, "wealth": 0.05, "t": 1, "rejections": []})
    assert rr.get_fdr_state(cur, 1, "btc15m")["epoch_to_ts"] is None   # legacy callers store NULL


def _partition_row(cur, val_to, hold_to):
    return cur._ins("app_data_partitions", {"market": "btc15m", "validation_to_ts": val_to,
                                             "holdout_to_ts": hold_to, "active": 0})


def test_validated_trials_overlapping_counts_only_live_evidence(cur):
    old, live = _partition_row(cur, 1_000, 1_500), _partition_row(cur, 3_000, 3_500)
    for i, part_id in enumerate((old["id"], live["id"], 999)):     # 999: partition row missing
        pre = dict(_prereg(hash_="h%d" % i), research_partition_id=part_id)
        eid = rr.preregister(cur, pre)
        rr.append_result(cur, eid, "validation", "inconclusive", 30)
    unjudged = rr.preregister(cur, dict(_prereg(hash_="never"), research_partition_id=live["id"]))
    assert unjudged
    assert rr.validated_trials_overlapping(cur, 1, "btc15m", 2_000) == 2   # live + missing row
    assert rr.validated_trials_overlapping(cur, 1, "btc15m", 500) == 3


def test_holdout_evaluations_overlapping_sums_refrozen_windows(cur):
    old, live = _partition_row(cur, 1_000, 1_500), _partition_row(cur, 3_000, 3_500)
    for part in (old, live):
        lid = rr.ensure_holdout_ledger(cur, "btc15m", part["id"], "fp%d" % part["id"], 10)["id"]
        rr.record_holdout_use(cur, lid)
        rr.record_holdout_use(cur, lid)
    assert rr.holdout_evaluations_overlapping(cur, "btc15m", 2_000) == 2   # only the live window
    assert rr.holdout_evaluations_overlapping(cur, "btc15m", 1_000) == 4
