"""The paper forward gate (Todd 2026-10-25): one pre-registered judgment of a probation experiment
on its realistic paper fills, at its own min_sample, on the validation bar."""
from datetime import datetime, timedelta, timezone

import pytest

from app import gatekeeper as gk
from app.gatekeeper import Classification
from app.services import forward_gate
from tests.test_gatekeeper import FakeRepo, _edge_trades, _null_trades


class Repo(FakeRepo):
    def experiment_row_by_id(self, cur, experiment_id):
        return self.experiments.get(experiment_id)


@pytest.fixture
def repo(monkeypatch):
    r = Repo()
    monkeypatch.setattr(gk, "rr", r)
    return r


def _paper(trades):
    # one contract per event ("BTC-T<ts>-1" -> event "BTC-T<ts>")
    return [gk.PaperTrade(t.ticker + "-1", t.qty, t.entry_ts, t.exit_ts, t.entry_price, t.exit_price, t.pnl, t.reason)
            for t in trades]


def _probation_experiment(repo, min_sample=40, validation=Classification.INCONCLUSIVE.value):
    eid = repo.preregister(None, {"user_id": 7, "run_id": 1, "market": "btc15m+eth15m", "hypothesis_hash": "h",
                                  "min_sample": min_sample, "spec": {"kind": "edge"}})
    repo.append_result(None, eid, "validation", validation, 12)
    return eid


def test_an_edge_on_paper_passes_once_on_exactly_its_first_min_sample_trips(repo):
    eid = _probation_experiment(repo)
    trades = _paper(_edge_trades(n=60))
    v = gk.judge_paper_forward(None, eid, trades, n_trials=3)
    assert v["classification"] == Classification.FORWARD_VALIDATED.value and v["n_trades"] == 40
    rows = repo.results_for_experiment(None, eid, gk.PAPER_PHASE)
    assert len(rows) == 1 and rows[0]["n_trades"] == 40 and rows[0]["n_trials_audited"] == 3
    # one look: a longer record is never judged again
    assert gk.judge_paper_forward(None, eid, trades + trades, n_trials=3) is None
    assert len(repo.results_for_experiment(None, eid, gk.PAPER_PHASE)) == 1
    # its LORD stream is its own, so the validation streams are untouched
    assert set(repo.fdr) == {(7, "paper:btc15m+eth15m")}


def test_when_the_check_runs_cannot_change_the_verdict(monkeypatch):
    """Scoring the FIRST min_sample trips makes a 40-trip and a 60-trip record the same test."""
    trades, got = _paper(_edge_trades(n=60)), []
    for record in (trades[:40], trades):
        r = Repo()
        monkeypatch.setattr(gk, "rr", r)
        got.append(gk.judge_paper_forward(None, _probation_experiment(r), record, n_trials=2))
    assert got[0] == got[1]


def test_a_short_record_is_not_a_look(repo):
    eid = _probation_experiment(repo, min_sample=100)
    assert gk.judge_paper_forward(None, eid, _paper(_edge_trades(n=60)), n_trials=1) is None
    assert repo.results_for_experiment(None, eid, gk.PAPER_PHASE) == []
    assert repo.set_fdr_calls == 0


def test_a_burst_on_few_events_is_not_a_look_until_the_event_floor(repo):
    """15 NFL trips on 4 games, all force-closed together by the position stop (2026-10-25), must not
    spend the one look: the judged sample is the shortest prefix with min_sample trips AND
    PAPER_MIN_EVENTS events, counted without looking at P&L."""
    eid = _probation_experiment(repo, min_sample=15)
    burst = [gk.PaperTrade("KXNFLGAME-G%d-%d" % (i % 4, i), 1, 1_000_000 + i, 1_000_100, 0.5, 0.0, -0.5, "stop")
             for i in range(15)]
    assert gk.judge_paper_forward(None, eid, burst, n_trials=1) is None
    assert repo.results_for_experiment(None, eid, gk.PAPER_PHASE) == []
    later = _paper(_edge_trades(n=40))
    want = gk.paper_judged_prefix(burst + later, 15)
    assert len(want) == 15 + gk.PAPER_MIN_EVENTS - 4 and want[-1] == later[gk.PAPER_MIN_EVENTS - 5]
    v = gk.judge_paper_forward(None, eid, burst + later, n_trials=1)
    assert v["n_trades"] == len(want)


def test_a_null_record_fails_and_is_not_judged_again(repo):
    eid = _probation_experiment(repo)
    v = gk.judge_paper_forward(None, eid, _paper(_null_trades(n=60)), n_trials=1)
    assert v["classification"] != Classification.FORWARD_VALIDATED.value
    assert gk.judge_paper_forward(None, eid, _paper(_edge_trades(n=60)), n_trials=1) is None


def test_validation_supported_and_holdout_judged_experiments_keep_the_holdout_path(repo):
    sup = _probation_experiment(repo, validation=Classification.STAT_SUPPORTED.value)
    assert gk.judge_paper_forward(None, sup, _paper(_edge_trades(n=60)), n_trials=1) is None
    held = repo.preregister(None, {"user_id": 7, "run_id": 3, "market": "btc15m", "hypothesis_hash": "x",
                                   "min_sample": 40, "spec": {}})
    repo.append_result(None, held, "holdout", Classification.REJECTED.value, 30)
    assert gk.judge_paper_forward(None, held, _paper(_edge_trades(n=60)), n_trials=1) is None


def test_cost_stress_charges_entries_and_early_exits_but_not_settlements():
    t = gk.PaperTrade("X-1", 10, 0, 60, 0.40, 1.0, 5.0, "settled")
    e = gk.PaperTrade("X-2", 10, 0, 60, 0.40, 0.45, 0.4, "exit")
    out = gk._paper_cost_stress([t, e])
    # settled: (5.0 - 0.10) / 4.0 ; early exit: (0.4 - 0.20) / 4.0
    assert out["cost_stress_mean"] == pytest.approx(((4.9 / 4.0) + (0.2 / 4.0)) / 2)
    assert gk._paper_cost_stress([gk.PaperTrade("X-3", 10, 0, 60, 0.40, 0.41, 0.05, "exit")])["cost_stress_ok"] is False


def test_a_paper_pass_reaches_the_diversification_check(repo):
    eid = _probation_experiment(repo)
    gk.judge_paper_forward(None, eid, _paper(_edge_trades(n=60)), n_trials=1)
    ok, why = gk.marginal_contribution_ok(None, 7, eid, {"market": "btc15m+eth15m", "spec": {"kind": "edge"}})
    assert ok, why
    assert repo.results_for_experiment(None, eid, "forward")[-1]["classification"] == \
        Classification.DEPLOYMENT_CANDIDATE.value


def test_paper_fill_rows_become_trades_in_utc():
    t0 = datetime(2026, 10, 25, 12, 0, 0)
    got = gk.paper_trades([{"ticker": "KXBTC15M-26OCT251215-15", "qty": 5, "entry_price": 0.9, "exit_price": 1.0,
                            "fees": 0.05, "pnl": 0.45, "settled": True, "opened_at": t0,
                            "closed_at": t0 + timedelta(minutes=10)}])
    ts = int(t0.replace(tzinfo=timezone.utc).timestamp())
    assert (got[0].entry_ts, got[0].exit_ts, got[0].reason) == (ts, ts + 600, "settled")


def test_the_service_marks_a_paper_pass_and_tells_the_user(monkeypatch):
    calls = []
    monkeypatch.setattr(forward_gate, "ENABLED", True)
    monkeypatch.setattr(forward_gate.repo, "list_deployments", lambda cur, uid, include_stopped=False: [
        {"id": 80, "strategy_id": 16140, "mode": "paper"}, {"id": 81, "strategy_id": 16140, "mode": "paper"},
        {"id": 9, "strategy_id": 5, "mode": "live"}])
    monkeypatch.setattr(forward_gate.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "title": "Deep favorites", "experiment_id": 77, "result": {"in_sample": {}}})
    monkeypatch.setattr(forward_gate.rr, "experiments_for_strategy", lambda cur, sid, eid=None: {
        "experiment": {"id": 77, "market": "btc15m+eth15m", "spec": {}}, "results": []})
    monkeypatch.setattr(forward_gate.repo, "paper_fills_for_gate", lambda cur, uid, sid: [])
    monkeypatch.setattr(forward_gate.gatekeeper, "judge_paper_forward", lambda cur, eid, trades, n: calls.append(n) or {
        "classification": "forward_validated", "n_trades": 150, "p_value": 0.01, "mean_net_return": 0.03})
    monkeypatch.setattr(forward_gate.gatekeeper, "marginal_contribution_ok", lambda cur, uid, eid, fin: (True, "ok"))
    monkeypatch.setattr(forward_gate.repo, "set_strategy_outcome",
                        lambda cur, sid, status, result, eid: calls.append((sid, status, eid)))
    monkeypatch.setattr(forward_gate.repo, "add_notification", lambda *a: calls.append("bell"))
    lines = forward_gate.run(None, {"id": 1, "autopilot": True})
    assert calls == [1, (16140, "passed", 77), "bell"]
    assert "PASSED" in lines[0] and "150 paper trades" in lines[0] and "live switch" in lines[0]
    monkeypatch.setattr(forward_gate, "ENABLED", False)
    assert forward_gate.run(None, {"id": 1, "autopilot": True}) == []
