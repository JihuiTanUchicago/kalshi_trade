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
        elif s.startswith("SELECT * FROM app_experiments WHERE strategy_id=%s"):
            sid = p[0]
            rows = [dict(r) for r in self.t["app_experiments"] if r["strategy_id"] == sid]
            self._last = sorted(rows, key=lambda r: -r["id"])[:1]
        elif s.startswith("INSERT INTO app_experiments"):
            cols = _insert_cols(s)
            self._ins("app_experiments", dict(zip(cols, p)))
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
            uid, mk, method, alpha, w0, wealth, t, rej, upd = p
            existing = next((r for r in self.t["app_fdr_state"]
                             if r["user_id"] == uid and r["market"] == mk), None)
            vals = dict(user_id=uid, market=mk, method=method, alpha=alpha, w0=w0,
                        wealth=wealth, t=t, rejections_json=rej, updated_at=upd)
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
