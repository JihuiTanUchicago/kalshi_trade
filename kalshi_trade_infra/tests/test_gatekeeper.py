"""Gatekeeper tests (RESEARCH_PIPELINE_DESIGN.md §B.2). No live DB: the research_repository
layer is replaced by an in-memory FakeRepo, backtest.simulate by a canned trade list keyed on
the spec, and the holdout dataset by a stub. We drive the real statistical verdict logic
(bootstrap p-value, PSR/DSR, LORD++, label-shuffle placebo, BH) end to end.
"""
from types import SimpleNamespace

import pytest

from app import gatekeeper as gk
from app.backtest import Trade
from app.gatekeeper import Classification, HoldoutConsumed, Prereg


# -- fakes ---------------------------------------------------------------------


class FakeRepo:
    """In-memory stand-in for app.research_repository: just enough of the surface the
    gatekeeper calls, storing experiments / result rows / fdr state / holdout ledger in dicts."""

    def __init__(self):
        self.experiments = {}          # id -> dict
        self.results = {}              # experiment_id -> list[row]
        self.fdr = {}                  # (user_id, market) -> state dict
        self.ledgers = {}              # ledger_id -> dict
        self.partitions = {}           # market -> partition dict
        self.set_fdr_calls = 0
        self._next_exp = 1
        self._next_res = 1
        self._next_ledger = 1

    # pre-registration
    def preregister(self, cur, pre):
        for eid, e in self.experiments.items():
            if e["run_id"] == pre.get("run_id") and e["hypothesis_hash"] == pre["hypothesis_hash"]:
                return eid
        eid = self._next_exp
        self._next_exp += 1
        self.experiments[eid] = dict(pre, id=eid)
        self.results.setdefault(eid, [])
        return eid

    # verdicts
    def append_result(self, cur, experiment_id, phase, classification, n_trades,
                      metrics=None, equity_curve=None):
        rid = self._next_res
        self._next_res += 1
        row = {"id": rid, "experiment_id": experiment_id, "phase": phase,
               "classification": classification, "n_trades": n_trades,
               "equity_curve": equity_curve}
        row.update(metrics or {})
        self.results.setdefault(experiment_id, []).append(row)
        return rid

    def results_for_experiment(self, cur, experiment_id, phase=None):
        rows = self.results.get(experiment_id, [])
        return [r for r in rows if phase is None or r["phase"] == phase]

    # fdr state
    def get_fdr_state(self, cur, user_id, market):
        return self.fdr.get((user_id, market))

    def set_fdr_state(self, cur, user_id, market, state):
        self.set_fdr_calls += 1
        self.fdr[(user_id, market)] = dict(state, user_id=user_id, market=market)

    # replay / audited trial count: experiments with a validation result
    def experiment_records_for_replay(self, cur, user_id, market):
        out = []
        for eid, e in self.experiments.items():
            if e["user_id"] != user_id or e["market"] != market:
                continue
            val = [r for r in self.results.get(eid, []) if r["phase"] == "validation"]
            if val:
                out.append({"experiment_id": eid, "strategy_id": e.get("strategy_id"),
                            "market": market, "classification": val[-1]["classification"]})
        return out

    # partitions / holdout ledger
    def get_active_partition(self, cur, market):
        return self.partitions.get(market)

    def ensure_holdout_ledger(self, cur, market, partition_id, fingerprint, max_evaluations):
        for lg in self.ledgers.values():
            if lg["market"] == market and lg["partition_id"] == partition_id:
                return lg
        lid = self._next_ledger
        self._next_ledger += 1
        lg = {"id": lid, "market": market, "partition_id": partition_id,
              "window_fingerprint": fingerprint, "evaluations_used": 0,
              "max_evaluations": max_evaluations, "consumed": 0}
        self.ledgers[lid] = lg
        return lg

    def record_holdout_use(self, cur, ledger_id):
        lg = self.ledgers.get(ledger_id)
        if not lg:
            return {"ok": False, "reason": "no_such_ledger"}
        if lg["consumed"] == 1 or lg["evaluations_used"] >= lg["max_evaluations"]:
            return {"ok": False, "reason": "holdout_consumed"}
        lg["evaluations_used"] += 1
        lg["consumed"] = 1 if lg["evaluations_used"] >= lg["max_evaluations"] else 0
        return {"ok": True, "evaluations_used": lg["evaluations_used"],
                "max_evaluations": lg["max_evaluations"], "consumed": lg["consumed"]}


def _ds(market="btc15m", start=1_000_000, end=2_000_000):
    return SimpleNamespace(market=SimpleNamespace(key=market), start_ts=start, end_ts=end)


def _trade(entry_ts, entry_price, won, qty=10, fees=0.02):
    exit_price = 1.0 if won else 0.0
    return Trade(ticker="BTC-T%d" % entry_ts, side="yes", qty=qty, entry_ts=entry_ts,
                 entry_price=entry_price, exit_ts=entry_ts + 900, exit_price=exit_price,
                 fees=fees, reason="settled", edge=0.1)


def _edge_trades(n=60):
    """A clean conditional edge: wins land on the CHEAP (underpriced) contracts, the few losses
    on the dear ones — the favorite-longshot mechanism. Winner prices are tightly clustered so
    the bootstrap mean has a negligible left tail (p -> 0, clearing LORD++'s strict first-test
    budget); the price spread still lets the placebo discriminate."""
    trades = []
    n_win = n - max(4, n // 10)
    cheap = [0.28, 0.30, 0.32]
    for i in range(n_win):
        trades.append(_trade(1_000_000 + i * 3600, cheap[i % 3], won=True))
    for i in range(n - n_win):
        trades.append(_trade(1_000_000 + (n_win + i) * 3600, 0.60, won=False))
    return trades


def _null_trades(n=60):
    """No edge: every bet at mid (0.50), alternating win/loss. Mean ~ -fees, and because every
    entry price is identical there is no conditional signal for the placebo to find."""
    return [_trade(1_000_000 + i * 3600, 0.50, won=(i % 2 == 0)) for i in range(n)]


@pytest.fixture
def repo(monkeypatch):
    r = FakeRepo()
    monkeypatch.setattr(gk, "rr", r)
    return r


def _patch_sim(monkeypatch, trades_for):
    """trades_for: spec -> trade list."""
    monkeypatch.setattr(gk.backtest, "simulate",
                        lambda spec, ds, a, b, *rest, **kw: trades_for(spec))


def _finalist(spec, user_id=7, min_sample=10, market="btc15m"):
    return {"spec": spec, "user_id": user_id, "min_sample": min_sample, "market": market}


# -- Prereg --------------------------------------------------------------------


def test_hypothesis_hash_is_stable_and_spec_sensitive():
    a = Prereg(user_id=1, run_id=5, market="btc15m", spec={"x": 1, "y": 2}, economic_rationale="m")
    b = Prereg(user_id=9, run_id=6, market="btc_daily", spec={"y": 2, "x": 1}, economic_rationale="m")
    c = Prereg(user_id=1, run_id=5, market="btc15m", spec={"x": 1, "y": 3}, economic_rationale="m")
    assert a.hypothesis_hash() == b.hypothesis_hash()   # identity = frozen spec + rationale only
    assert a.hypothesis_hash() != c.hypothesis_hash()   # a different rule is a different experiment
    assert a.to_dict()["hypothesis_hash"] == a.hypothesis_hash()


def test_preregister_is_idempotent(repo):
    pre = Prereg(user_id=1, run_id=5, market="btc15m", spec={"k": 1}, economic_rationale="m")
    first = gk.preregister(None, pre)
    second = gk.preregister(None, pre)
    assert first == second and len(repo.experiments) == 1


# -- judge_validation: happy path ----------------------------------------------


def test_judge_validation_injected_edge_is_stat_supported(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _edge_trades())
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "edge"}, economic_rationale="longshot bias"))
    out = gk.judge_validation(None, eid, _finalist({"kind": "edge"}), _ds())
    assert out["classification"] == Classification.STAT_SUPPORTED.value
    assert out["p_value"] < 0.05 and out["ci"]["lo"] > 0 and out["dsr"] >= gk.DSR_MIN
    assert out["placebo_p"] < gk.ALPHA           # negative control confirms the edge
    assert repo.set_fdr_calls == 1               # alpha was spent exactly once
    row = repo.results_for_experiment(None, eid, "validation")[-1]
    assert row["classification"] == Classification.STAT_SUPPORTED.value and row["fdr_reject"] == 1


# -- judge_validation: error paths ---------------------------------------------


def test_below_min_sample_is_inconclusive_and_spends_no_alpha(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _edge_trades(n=60))
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "edge"}, economic_rationale="m", min_sample=100))
    out = gk.judge_validation(None, eid, _finalist({"kind": "edge"}, min_sample=100), _ds())
    assert out["classification"] == Classification.INCONCLUSIVE.value
    assert out["alpha_spent"] is False
    assert repo.set_fdr_calls == 0                       # LORD++ stream untouched
    assert (7, "btc15m") not in repo.fdr


def test_null_strategy_is_not_stat_supported(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _null_trades())
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "null"}, economic_rationale="m"))
    out = gk.judge_validation(None, eid, _finalist({"kind": "null"}), _ds())
    assert out["classification"] != Classification.STAT_SUPPORTED.value
    assert not (out["p_value"] < gk.ALPHA and out["placebo_p"] < gk.ALPHA)


# -- judge_batch: BH + LORD++ together -----------------------------------------


def test_judge_batch_applies_bh_and_lord(repo, monkeypatch):
    def trades_for(spec):
        return _edge_trades() if spec["kind"] == "edge" else _null_trades()
    _patch_sim(monkeypatch, trades_for)
    e1 = gk.preregister(None, Prereg(user_id=7, run_id=2, market="btc15m",
                                     spec={"kind": "edge"}, economic_rationale="m"))
    e2 = gk.preregister(None, Prereg(user_id=7, run_id=2, market="btc15m",
                                     spec={"kind": "null"}, economic_rationale="m2"))
    outs = gk.judge_batch(None, 2, [e1, e2],
                          [_finalist({"kind": "edge"}), _finalist({"kind": "null"})], _ds())
    by = {o["classification"] for o in outs}
    assert outs[0]["classification"] == Classification.STAT_SUPPORTED.value
    assert outs[0]["bh_reject"] is True
    assert outs[1]["classification"] != Classification.STAT_SUPPORTED.value
    assert Classification.STAT_SUPPORTED.value in by
    assert repo.set_fdr_calls == 1               # one persisted state for the whole chunk


# -- judge_holdout -------------------------------------------------------------


def _partition():
    return {"id": 1, "holdout_from_ts": 1_500_000, "holdout_to_ts": 2_000_000,
            "data_fingerprint": "abc"}


def test_judge_holdout_refuses_non_stat_supported(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _edge_trades())
    monkeypatch.setattr(gk.partitions, "holdout_dataset", lambda m, p: _ds())
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "x"}, economic_rationale="m"))
    repo.append_result(None, eid, "validation", Classification.INCONCLUSIVE.value, 20)
    repo.partitions["btc15m"] = _partition()
    with pytest.raises(HoldoutConsumed):
        gk.judge_holdout(None, eid, _finalist({"kind": "x"}))


def test_judge_holdout_refuses_when_consumed(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _edge_trades())
    monkeypatch.setattr(gk.partitions, "holdout_dataset", lambda m, p: _ds())
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "x"}, economic_rationale="m"))
    repo.append_result(None, eid, "validation", Classification.STAT_SUPPORTED.value, 60)
    repo.partitions["btc15m"] = _partition()
    # Ledger already at its cap -> must refuse before spending.
    repo.ledgers[1] = {"id": 1, "market": "btc15m", "partition_id": 1,
                       "window_fingerprint": gk._holdout_fingerprint(_partition()),
                       "evaluations_used": 10, "max_evaluations": 10, "consumed": 1}
    with pytest.raises(HoldoutConsumed):
        gk.judge_holdout(None, eid, _finalist({"kind": "x"}))


def test_judge_holdout_forward_validates_on_success(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _edge_trades())
    monkeypatch.setattr(gk.partitions, "holdout_dataset", lambda m, p: _ds())
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "edge"}, economic_rationale="m"))
    repo.append_result(None, eid, "validation", Classification.STAT_SUPPORTED.value, 60)
    repo.partitions["btc15m"] = _partition()
    out = gk.judge_holdout(None, eid, _finalist({"kind": "edge"}))
    assert out["classification"] == Classification.FORWARD_VALIDATED.value
    assert repo.ledgers[1]["evaluations_used"] == 1
    # A second look on the same experiment is one-time -> refused.
    with pytest.raises(HoldoutConsumed):
        gk.judge_holdout(None, eid, _finalist({"kind": "edge"}))


# -- marginal_contribution_ok --------------------------------------------------


def test_marginal_contribution_fails_on_near_duplicate(repo):
    series = [[1_000_000 + i * 3600, 0.5 + 0.01 * (i % 5)] for i in range(40)]
    # Deployed peer: forward-validated, promoted to DEPLOYMENT_CANDIDATE, same return series.
    peer = repo.preregister(None, {"user_id": 7, "run_id": 1, "market": "btc15m",
                                   "hypothesis_hash": "peer", "strategy_id": 1})
    repo.append_result(None, peer, "validation", Classification.STAT_SUPPORTED.value, 40,
                       equity_curve=series)
    repo.append_result(None, peer, "forward", Classification.DEPLOYMENT_CANDIDATE.value, 40)
    # Candidate: forward-validated, with a near-identical series.
    cand = repo.preregister(None, {"user_id": 7, "run_id": 2, "market": "btc15m",
                                   "hypothesis_hash": "cand", "strategy_id": 2})
    repo.append_result(None, cand, "validation", Classification.STAT_SUPPORTED.value, 40,
                       equity_curve=[[ts, r + 0.0001] for ts, r in series])
    repo.append_result(None, cand, "holdout", Classification.FORWARD_VALIDATED.value, 40)
    ok, reason = gk.marginal_contribution_ok(None, 7, cand, _finalist({"kind": "c"}))
    assert ok is False and "corr" in reason


def test_marginal_contribution_promotes_when_uncorrelated(repo):
    cand = repo.preregister(None, {"user_id": 7, "run_id": 2, "market": "btc15m",
                                   "hypothesis_hash": "cand", "strategy_id": 2})
    repo.append_result(None, cand, "validation", Classification.STAT_SUPPORTED.value, 10,
                       equity_curve=[[1_000_000 + i * 3600, float(i)] for i in range(10)])
    repo.append_result(None, cand, "holdout", Classification.FORWARD_VALIDATED.value, 10)
    ok, reason = gk.marginal_contribution_ok(None, 7, cand, _finalist({"kind": "c"}))
    assert ok is True
    assert repo.results_for_experiment(None, cand, "forward")[-1]["classification"] == \
        Classification.DEPLOYMENT_CANDIDATE.value
