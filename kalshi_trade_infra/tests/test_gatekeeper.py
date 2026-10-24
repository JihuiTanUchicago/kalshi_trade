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
                      metrics=None, equity_curve=None, folds=None):
        rid = self._next_res
        self._next_res += 1
        row = {"id": rid, "experiment_id": experiment_id, "phase": phase,
               "classification": classification, "n_trades": n_trades,
               "equity_curve": equity_curve, "folds": folds}
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

    def validated_trials_overlapping(self, cur, user_id, market, window_from_ts):
        # Experiments carry an optional `val_to` (their partition's validation_to_ts); without it
        # they are treated as overlapping, like a missing partition row in the real query.
        n = 0
        for eid, e in self.experiments.items():
            if e["user_id"] != user_id or e["market"] != market:
                continue
            if not any(r["phase"] == "validation" for r in self.results.get(eid, [])):
                continue
            if e.get("val_to") is None or e["val_to"] > window_from_ts:
                n += 1
        return n

    def holdout_evaluations_overlapping(self, cur, market, holdout_from_ts):
        return sum(lg["evaluations_used"] for lg in self.ledgers.values()
                   if lg["market"] == market and lg.get("holdout_to", holdout_from_ts + 1) > holdout_from_ts)

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


def _one_day_fluke(n=60):
    """The SAME strong edge as _edge_trades, but every trade opens inside a single calendar day
    (entries 60s apart). Statistically it looks great (small p, CI>0, placebo passes) yet it is a
    one-day artifact — the cross-day gate must demote it from STAT_SUPPORTED."""
    trades = []
    n_win = n - max(4, n // 10)
    cheap = [0.28, 0.30, 0.32]
    base = 1_000_000  # 1_000_000 // 86400 == day 11, and +60*60s stays in the same day
    for i in range(n_win):
        trades.append(_trade(base + i * 60, cheap[i % 3], won=True))
    for i in range(n - n_win):
        trades.append(_trade(base + (n_win + i) * 60, 0.60, won=False))
    return trades


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


# -- cross-day generalization gate ---------------------------------------------


def test_cross_day_gate_rejects_a_one_day_fluke(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _one_day_fluke())
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "fluke"}, economic_rationale="m"))
    out = gk.judge_validation(None, eid, _finalist({"kind": "fluke"}), _ds())
    # Looks statistically strong but the edge is confined to one day -> NOT statistically supported.
    assert out["p_value"] < gk.ALPHA and out["ci"]["lo"] > 0 and out["placebo_p"] < gk.ALPHA
    assert out["cross_day_ok"] is False
    assert out["classification"] == Classification.INCONCLUSIVE.value
    row = repo.results_for_experiment(None, eid, "validation")[-1]
    assert row["folds"]  # per-fold breakdown recorded for the research-paper folds strip


def test_cross_day_gate_passes_an_edge_spread_across_days(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _edge_trades())  # hourly entries span several days
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "edge"}, economic_rationale="m"))
    out = gk.judge_validation(None, eid, _finalist({"kind": "edge"}), _ds())
    assert out["cross_day_ok"] is True
    assert out["classification"] == Classification.STAT_SUPPORTED.value


def test_cross_contract_spends_from_a_shared_fdr_stream(repo, monkeypatch):
    """A cross-contract (btc_daily+eth_daily) strategy advances ONE shared FDR stream, not each
    leg's per-market stream — so a pair can't double-spend budgets, and single-market streams
    stay separate (RESEARCH_PIPELINE_DESIGN.md §E.6)."""
    _patch_sim(monkeypatch, lambda spec: _edge_trades())
    key = "btc_daily+eth_daily"
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market=key,
                                      spec={"kind": "edge"}, economic_rationale="btc-eth basis"))
    out = gk.judge_validation(None, eid, _finalist({"kind": "edge"}, market=key), _ds(market=key))
    assert out["classification"] == Classification.STAT_SUPPORTED.value
    assert (7, key) in repo.fdr                                   # the shared stream advanced
    assert (7, "btc_daily") not in repo.fdr                      # neither leg's own stream touched
    assert (7, "eth_daily") not in repo.fdr


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


def _cross_spec():
    return {"market": "btc_daily",
            "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}],
                      "relationship": "spread"}}


def test_judge_holdout_cross_runs_on_merged_partition(repo, monkeypatch):
    """A cross-contract finalist is forward-validated on the MERGED holdout of its legs, with the
    holdout ledger + FDR keyed by the shared stream (not either leg's own market)."""
    key = "btc_daily+eth_daily"
    merged = {"id": 9, "holdout_from_ts": 1_500_000, "holdout_to_ts": 2_000_000, "data_fingerprint": "m"}
    frozen_ds = _ds(market=key)
    frozen_legs = [("btc_daily", dict(merged, id=10, data_fingerprint="btc")),
                   ("eth_daily", dict(merged, id=11, data_fingerprint="eth"))]
    loads = []

    def resolve_legs(cur, markets):
        assert cur is None and markets == ["btc_daily", "eth_daily"]
        loads.append("resolve")
        return frozen_legs

    def load_merged(legs, phase):
        assert legs is frozen_legs and phase == "holdout"
        loads.append("load")
        return frozen_ds

    def simulate(spec, ds, start, end, *rest, **kw):
        assert ds is frozen_ds and (start, end) == (frozen_ds.start_ts, frozen_ds.end_ts + 1)
        return _edge_trades()

    monkeypatch.setattr(gk.backtest, "simulate", simulate)
    monkeypatch.setattr(gk.partitions, "ensure_merged_partition", lambda cur, markets: merged)
    monkeypatch.setattr(gk.partitions, "merged_partitions", resolve_legs)
    monkeypatch.setattr(gk.partitions, "merged_dataset_from", load_merged)
    spec = _cross_spec()
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market=key, spec=spec,
                                      economic_rationale="btc-eth basis"))
    repo.append_result(None, eid, "validation", Classification.STAT_SUPPORTED.value, 60)
    out = gk.judge_holdout(None, eid, {"spec": spec, "user_id": 7, "market": "btc_daily"})
    assert out["classification"] == Classification.FORWARD_VALIDATED.value
    assert loads == ["resolve", "load"]
    # the one-time holdout ledger is keyed by the shared stream, and btc_daily's stricter cap (3) wins
    led = next(lg for lg in repo.ledgers.values() if lg["market"] == key)
    assert led["partition_id"] == 9 and led["max_evaluations"] == 3 and led["evaluations_used"] == 1


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


def test_judged_trials_counts_fitted_degrees_of_freedom():
    """A learned model's fitted coefficients each count as an implicit trial, so a richer model
    raises the DSR selection bar; a hand-specified gbm/code spec stays at 1. The weighting only
    ever INCREASES the trial count -> the gate can never get easier by adding parameters."""
    from app import spec as specmod
    gbm = {"spec": specmod.validate({})}
    logistic = {"spec": specmod.validate(
        {"model": {"kind": "logistic", "features": ["z_score", "ob_imbalance", "mid"]}})}
    calibration = {"spec": specmod.validate({"model": {"kind": "calibration"}})}
    assert gk._judged_trials([gbm]) == 1
    assert gk._judged_trials([logistic]) == 4          # intercept + 3 weights
    assert gk._judged_trials([calibration]) == 2       # slope + intercept
    assert gk._judged_trials([gbm, logistic, calibration]) == 7
    assert gk._judged_trials([{}]) == 1                # tolerant of a missing spec (holdout path)


# -- the conjunctive STAT_SUPPORTED gate (pure decision rule) -------------------
# A direct unit test of _classify: it locks that EVERY rigor pillar is a hard veto, so the
# gate can only ever get stricter. If a future edit silently drops or loosens one pillar from
# the conjunction, exactly one of these per-pillar assertions fails. (The judge_* tests above
# only exercise the cross-day and placebo pillars, and only through the integration path.)

# all pillars satisfied -> the ONLY input that may pass
_PASS = dict(lord_reject=True, bh_reject=True, dsr=gk.DSR_MIN, ci_lo=0.01, ci_hi=0.5,
             placebo_passed=True, cross_day_ok=True)


def _clf(**over):
    d = {**_PASS, **over}
    return gk._classify(d["lord_reject"], d["bh_reject"], d["dsr"], d["ci_lo"], d["ci_hi"],
                        d["placebo_passed"], d["cross_day_ok"])


def test_classify_passes_only_when_every_pillar_holds():
    assert _clf() == Classification.STAT_SUPPORTED                 # DSR exactly at the floor is OK (>=)
    assert _clf(bh_reject=None) == Classification.STAT_SUPPORTED   # no chunk -> BH not applicable, not a veto


def test_classify_each_pillar_is_a_hard_veto():
    # Flip ONE pillar at a time to failing; none may still read STAT_SUPPORTED.
    assert _clf(lord_reject=False) != Classification.STAT_SUPPORTED        # FDR budget didn't reject
    assert _clf(bh_reject=False) != Classification.STAT_SUPPORTED          # BH within-chunk didn't reject
    assert _clf(dsr=gk.DSR_MIN - 1e-9) != Classification.STAT_SUPPORTED    # just below the DSR floor
    assert _clf(ci_lo=0.0) != Classification.STAT_SUPPORTED                # CI lower bound must be strictly > 0
    assert _clf(cross_day_ok=False) == Classification.INCONCLUSIVE         # one-window edge -> honest INCONCLUSIVE
    assert _clf(placebo_passed=False) == Classification.REJECTED           # label-shuffle artifact


def test_classify_rejects_actively_negative_edge():
    # Whole CI at/below zero (placebo still "passes") -> actively no edge, REJECTED not INCONCLUSIVE.
    assert _clf(lord_reject=False, ci_lo=-0.2, ci_hi=0.0) == Classification.REJECTED
    assert _clf(lord_reject=False, ci_lo=-0.2, ci_hi=0.3) == Classification.INCONCLUSIVE  # upside remains


# -- end-to-end calibration: can the gate pass a real edge, and does it hold noise out? ----------
#
# A gate that rejects everything is as useless as one that passes everything, and it fails
# silently: "nothing passed" reads as "no edge exists". These pin both directions on realistic
# shapes: uniform entry prices (no longshot concentration), ~16 days of validation, Kalshi fees.

import random as _random

from app import stats as _stats


def _uniform_trades(n, gross_edge, seed, days=16):
    """n binary YES buys at prices ~U(0.25, 0.75) that win with prob price + gross_edge, Kalshi
    taker fee charged, entries spread evenly over `days`."""
    rng = _random.Random(seed)
    out = []
    for i in range(n):
        p = rng.uniform(0.25, 0.75)
        qty = 10
        win = rng.random() < min(0.99, p + gross_edge)
        ts = 1_700_000_000 + int(i * days * 86400 / n)
        out.append(Trade("T%d" % i, "yes", qty, ts, p, ts + 900, 1.0 if win else 0.0,
                         0.07 * p * (1 - p) * qty, "settled", gross_edge))
    return out


@pytest.fixture
def fast_boot(monkeypatch):
    orig = _stats.stationary_bootstrap_ci
    monkeypatch.setattr(gk.stats, "stationary_bootstrap_ci",
                        lambda x, **kw: orig(x, **dict(kw, n_boot=500)))


def _verdict(trades, seed, n_trials=1):
    v = gk._compute(trades, n_trials, _stats.lord_init(gk.ALPHA), seed=seed)
    return gk._classify(v["lord_reject"], None, v["dsr"], v["ci_lo"], v["ci_hi"],
                        v["placebo_passed"], v["cross_day_ok"]), v


def test_calibration_uniform_real_edge_is_stat_supported(fast_boot):
    """A real 15c/contract edge at mid-range prices over 400 validation trades must pass. Under the
    old winner-subset placebo this was REJECTED in every seed."""
    passes = sum(_verdict(_uniform_trades(400, 0.15, s), s)[0] == Classification.STAT_SUPPORTED
                 for s in range(6))
    assert passes >= 5


def test_calibration_breakeven_noise_is_held_out(fast_boot):
    """Gross edge equal to the mid-price fee (net ~0): the first test in a fresh stream spends
    alpha ~2.7e-3, so essentially no seed may pass."""
    passes = sum(_verdict(_uniform_trades(400, 0.0175, s), 100 + s)[0] == Classification.STAT_SUPPORTED
                 for s in range(20))
    assert passes <= 1


def test_placebo_accepts_an_edge_on_dear_contracts():
    """Winning more often than the price implies on EXPENSIVE contracts is a real edge; the
    market-implied null must see it (the old test scored this p ~ 1)."""
    trades = [_trade(1_000_000 + i * 3600, 0.70, won=(i % 10 != 0)) for i in range(80)]  # 90% wins at 70c
    assert gk._placebo_pvalue(trades, seed=1) < gk.ALPHA


def test_placebo_is_uniform_when_outcomes_match_prices():
    rng = _random.Random(3)
    ps = []
    for seed in range(40):
        trades = []
        for i in range(120):
            p = rng.uniform(0.1, 0.9)
            trades.append(_trade(1_000_000 + i * 3600, p, won=rng.random() < p))
        ps.append(gk._placebo_pvalue(trades, seed=seed))
    assert sum(p < gk.ALPHA for p in ps) <= 10        # ~10% expected, not systematically small
    assert 0.3 < sum(ps) / len(ps) < 0.7              # roughly uniform on average


def test_primary_p_is_continuous_below_bootstrap_resolution():
    """The bootstrap mass at/below zero is pinned at 0 for a strong edge, but LORD++ needs to
    compare against alphas far below 1/n_boot; the SE-based p must stay finite and tiny."""
    boot = {"point": 0.05, "se": 0.01, "p_value": 0.0}
    p = gk._primary_p(boot)
    assert 0.0 < p < 1e-5
    assert gk._primary_p({"point": 0.05, "se": 0.0, "p_value": 0.0}) == 0.0   # degenerate SE -> empirical


# -- evidence epochs: FDR stream + DSR trial count follow the validation data ---------------------


def test_lord_stream_continues_while_validation_windows_overlap(repo):
    repo.fdr[(7, "btc15m")] = {"method": "LORD++", "alpha": 0.1, "w0": 0.05, "wealth": 0.01,
                               "t": 40, "rejections": [], "epoch_to_ts": 2_000_000}
    st = gk._lord_state(None, 7, "btc15m", 1_500_000, 2_100_000)
    assert st["t"] == 40 and st["epoch_to_ts"] == 2_000_000


def test_lord_stream_restarts_on_fresh_validation_data(repo):
    repo.fdr[(7, "btc15m")] = {"method": "LORD++", "alpha": 0.1, "w0": 0.05, "wealth": 0.01,
                               "t": 40, "rejections": [], "epoch_to_ts": 2_000_000}
    st = gk._lord_state(None, 7, "btc15m", 2_000_000, 2_600_000)
    assert st["t"] == 0 and st["wealth"] == st["w0"] and st["epoch_to_ts"] == 2_600_000


def test_legacy_stream_is_continued_and_stamped(repo):
    repo.fdr[(7, "btc15m")] = {"method": "LORD++", "alpha": 0.1, "w0": 0.05, "wealth": 0.01,
                               "t": 300, "rejections": []}
    st = gk._lord_state(None, 7, "btc15m", 1_500_000, 2_100_000)
    assert st["t"] == 300 and st["epoch_to_ts"] == 2_100_000   # no free refill on the same data


def test_epoch_is_persisted_after_judging(repo, monkeypatch):
    _patch_sim(monkeypatch, lambda spec: _edge_trades())
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "edge"}, economic_rationale="m"))
    gk.judge_validation(None, eid, _finalist({"kind": "edge"}), _ds(start=1_000_000, end=2_000_000))
    assert repo.fdr[(7, "btc15m")]["epoch_to_ts"] == 2_000_000


def test_dsr_trials_count_only_overlapping_validation_windows(repo):
    for i, val_to in enumerate((900_000, 1_200_000, None)):
        eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                          spec={"i": i}, economic_rationale="m"))
        repo.experiments[eid]["val_to"] = val_to
        repo.append_result(None, eid, "validation", "inconclusive", 30)
    # window starts at 1_000_000: the 900_000 window has fully rolled out; 1_200_000 and the
    # partition-less one (conservatively) still overlap.
    assert gk._n_trials(None, 7, "btc15m", including=1, window_from_ts=1_000_000) == 3
    assert gk._n_trials(None, 7, "btc15m", including=1) == 4    # holdout path: all-time


# -- validation-budget pre-screen ------------------------------------------------------------------


_POWER_PART = {"embargo_seconds": 900, "validation_from_ts": 3_000_000,
               "validation_to_ts": 3_000_000 + 16 * 86400}


def test_validation_power_passes_a_strong_research_edge(repo, monkeypatch):
    monkeypatch.setattr(gk.backtest, "research_fold_trades",
                        lambda spec, ds, emb, what_if=None: _uniform_trades(300, 0.15, 1, days=12))
    pw = gk.validation_power(None, 7, "btc15m", {}, None, _POWER_PART, min_sample=30)
    assert pw["ok"] and pw["power"] > 0.5 and pw["n_val_expected"] == pytest.approx(400, rel=0.01)


def test_validation_power_screens_out_a_thin_edge(repo, monkeypatch):
    monkeypatch.setattr(gk.backtest, "research_fold_trades",
                        lambda spec, ds, emb, what_if=None: _uniform_trades(150, 0.03, 2, days=12))
    pw = gk.validation_power(None, 7, "btc15m", {}, None, _POWER_PART, min_sample=30)
    assert not pw["ok"] and pw["reason"]


def test_validation_power_needs_research_trades(repo, monkeypatch):
    monkeypatch.setattr(gk.backtest, "research_fold_trades", lambda spec, ds, emb, what_if=None: [])
    pw = gk.validation_power(None, 7, "btc15m", {}, None, _POWER_PART)
    assert not pw["ok"] and "research-fold trades" in pw["reason"]


# -- holdout re-freeze churn -----------------------------------------------------------------------


def test_holdout_cap_counts_looks_across_refrozen_windows(repo, monkeypatch):
    """Ten looks on yesterday's frozen window + a re-freeze (new partition id) on almost the same
    data must NOT open ten more looks."""
    repo.ledgers[99] = {"id": 99, "market": "btc15m", "partition_id": 0, "window_fingerprint": "old",
                        "evaluations_used": 10, "max_evaluations": 10, "consumed": 1,
                        "holdout_to": 2_000_000}
    repo.partitions["btc15m"] = _partition()   # new id=1 window, holdout_from 1_500_000 overlaps
    _patch_sim(monkeypatch, lambda spec: _edge_trades())
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m",
                                      spec={"kind": "edge"}, economic_rationale="m"))
    repo.append_result(None, eid, "validation", Classification.STAT_SUPPORTED.value, 60)
    monkeypatch.setattr(gk.partitions, "holdout_dataset", lambda market, part: _ds())
    with pytest.raises(HoldoutConsumed):
        gk.judge_holdout(None, eid, _finalist({"kind": "edge"}))


def test_dsr_floor_is_a_selection_check_not_a_second_significance_test():
    """DSR >= 0.5 (observed Sharpe beats the expected best lucky null); significance comes from
    LORD++. The offline research_eval scorecard, which has no LORD++ stream, keeps 0.95."""
    from app import research_eval
    assert gk.DSR_MIN == 0.5
    assert research_eval.DSR_MIN == 0.95
    assert _clf(dsr=0.6) == Classification.STAT_SUPPORTED
    assert _clf(dsr=0.6, lord_reject=False) != Classification.STAT_SUPPORTED   # LORD++ still required


# -- cost stress -----------------------------------------------------------------------------


def test_classify_cost_stress_failure_is_inconclusive():
    """Every other pillar holds but the edge dies under 1c of extra slippage: not supported."""
    d = dict(_PASS)
    args = (d["lord_reject"], d["bh_reject"], d["dsr"], d["ci_lo"], d["ci_hi"], d["placebo_passed"],
            d["cross_day_ok"])
    assert gk._classify(*args, cost_stress_ok=True) == Classification.STAT_SUPPORTED
    assert gk._classify(*args, cost_stress_ok=False) == Classification.INCONCLUSIVE


def _cs_trade(i, entry, exit_price):
    return Trade("T%d" % i, "yes", 10, 1_700_000_000 + i * 900, entry, 1_700_000_000 + i * 900 + 900,
                 exit_price, 0.0, "settled", 0.0)


def test_cost_stress_resimulates_with_extra_slippage(monkeypatch):
    """_cost_stress re-runs the same spec with WhatIf(slippage_cents=COST_STRESS_CENTS); a thin edge
    that is positive at zero friction and negative once the stress is paid fails."""
    seen = []

    def fake_simulate(spec, ds, start, end, what_if=None):
        seen.append(what_if)
        bump = what_if.slippage_cents / 100.0 if what_if else 0.0
        # 0.5c per contract of edge at zero friction: 50.5% wins at 50c entry
        return [_cs_trade(i, 0.50 + bump, 1.0 if i % 200 < 101 else 0.0) for i in range(400)]

    monkeypatch.setattr(gk.backtest, "simulate", fake_simulate)
    ds = SimpleNamespace(market=SimpleNamespace(kind="binary"), start_ts=0, end_ts=1)
    base = fake_simulate({}, ds, 0, 2)
    seen.clear()
    out = gk._cost_stress({}, ds, base)
    assert seen and seen[0].slippage_cents == gk.COST_STRESS_CENTS
    assert out["cost_stress_trades"] == 400 and out["cost_stress_mean"] < 0 and not out["cost_stress_ok"]
    # no trades, or a non-binary instrument, is not re-simulated
    assert gk._cost_stress({}, ds, [])["cost_stress_ok"]
    assert gk._cost_stress({}, SimpleNamespace(market=SimpleNamespace(kind="spot")), base)["cost_stress_ok"]


def test_validation_power_projects_at_the_stressed_cost(repo, monkeypatch):
    """The pre-screen asks for research-fold trades at the gate's COST_STRESS_CENTS on a binary market."""
    seen = []

    def fold(spec, ds, emb, what_if=None):
        seen.append(what_if)
        return _uniform_trades(300, 0.15, 1, days=12)

    monkeypatch.setattr(gk.backtest, "research_fold_trades", fold)
    ds = SimpleNamespace(market=SimpleNamespace(kind="binary"))
    gk.validation_power(None, 7, "btc15m", {}, ds, _POWER_PART, min_sample=30)
    assert seen[-1].slippage_cents == gk.COST_STRESS_CENTS
