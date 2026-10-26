"""The §E.5 promotion WIRING (app.research.agent): a validation pass must flow through the one-time
Locked-Holdout and the marginal-contribution gate to become a DEPLOYMENT_CANDIDATE, or live
deploy is impossible. The gatekeeper verdict logic itself is covered in test_gatekeeper; here we
pin the pipeline hand-off agent._promote_if_forward_validated + _is_deployment_candidate:
earned promotion, a holdout failure that stays short of deployable, the one-time latch across a
second pass, and the anti-leak boundary (held-out numbers never reach the generator block).
"""
import json

from app.research import agent, gatekeeper
from app.research.gatekeeper import Classification

# Reuse the in-memory gatekeeper fakes (DRY): FakeRepo + canned trade lists + dataset/partition stubs.
from tests.test_gatekeeper import (FakeRepo, _ds, _edge_trades, _finalist, _null_trades,
                                   _partition)


class Repo(FakeRepo):
    """FakeRepo + the one method the agent (not the gatekeeper) reaches for."""

    def experiments_for_strategy(self, cur, strategy_id):
        for eid, e in self.experiments.items():
            if e.get("strategy_id") == strategy_id:
                return {"experiment": e, "results": self.results.get(eid, [])}
        return None


def _wire(monkeypatch, repo, trades_for):
    # Both modules hold their own `rr`; point both at the same in-memory repo.
    monkeypatch.setattr(gatekeeper, "rr", repo)
    monkeypatch.setattr(agent, "rr", repo)
    monkeypatch.setattr(gatekeeper.backtest, "simulate",
                        lambda spec, ds, a, b, *rest, **kw: trades_for(spec))
    monkeypatch.setattr(gatekeeper.partitions, "holdout_dataset", lambda m, p: _ds())


def _stat_supported_experiment(repo, strategy_id=1):
    """A finalist that already passed validation (STAT_SUPPORTED), with a validation return series
    the marginal-contribution gate can correlate against deployed peers."""
    eid = repo.preregister(None, {"user_id": 7, "run_id": 1, "market": "btc15m",
                                  "hypothesis_hash": "h%d" % strategy_id, "strategy_id": strategy_id})
    repo.append_result(None, eid, "validation", Classification.STAT_SUPPORTED.value, 60,
                       equity_curve=[[1_000_000 + i * 3600, float(i % 5)] for i in range(60)])
    repo.partitions["btc15m"] = _partition()
    return eid


def _logger():
    events = []
    return events, (lambda kind, msg, data=None: events.append({"kind": kind, "msg": msg, "data": data}))


def test_validation_pass_plus_holdout_plus_marginal_becomes_deployment_candidate(monkeypatch):
    repo = Repo()
    _wire(monkeypatch, repo, lambda spec: _edge_trades())
    eid = _stat_supported_experiment(repo, strategy_id=1)

    events, log = _logger()
    agent._promote_if_forward_validated(None, 7, eid, _finalist({"kind": "edge"}), {"title": "T"}, log)

    # forward-validated on the holdout, then promoted by the (peer-free) diversification gate.
    assert repo.results_for_experiment(None, eid, "holdout")[-1]["classification"] \
        == Classification.FORWARD_VALIDATED.value
    assert repo.results_for_experiment(None, eid, "forward")[-1]["classification"] \
        == Classification.DEPLOYMENT_CANDIDATE.value
    assert repo.ledgers[1]["evaluations_used"] == 1
    # the deploy gate's predicate now clears
    assert agent._is_deployment_candidate(None, 1) is True


def test_holdout_failure_does_not_become_candidate(monkeypatch):
    repo = Repo()
    _wire(monkeypatch, repo, lambda spec: _null_trades())  # no edge on the holdout -> REJECTED
    eid = _stat_supported_experiment(repo, strategy_id=2)

    events, log = _logger()
    agent._promote_if_forward_validated(None, 7, eid, _finalist({"kind": "null"}), {"title": "T"}, log)

    assert repo.results_for_experiment(None, eid, "holdout")[-1]["classification"] \
        == Classification.REJECTED.value
    assert repo.results_for_experiment(None, eid, "forward") == []  # no promotion
    assert agent._is_deployment_candidate(None, 2) is False


def test_holdout_is_judged_at_most_once_per_experiment(monkeypatch):
    repo = Repo()
    _wire(monkeypatch, repo, lambda spec: _edge_trades())
    eid = _stat_supported_experiment(repo, strategy_id=3)

    events, log = _logger()
    agent._promote_if_forward_validated(None, 7, eid, _finalist({"kind": "edge"}), {"title": "T"}, log)
    agent._promote_if_forward_validated(None, 7, eid, _finalist({"kind": "edge"}), {"title": "T"}, log)

    # A second pass must NOT re-judge or burn the holdout again.
    assert len(repo.results_for_experiment(None, eid, "holdout")) == 1
    assert repo.ledgers[1]["evaluations_used"] == 1
    assert any(e["data"].get("skipped") for e in events if e["data"])


def test_holdout_stats_never_reach_the_generator_block(monkeypatch):
    repo = Repo()
    _wire(monkeypatch, repo, lambda spec: _edge_trades())
    eid = _stat_supported_experiment(repo, strategy_id=4)

    events, log = _logger()
    agent._promote_if_forward_validated(None, 7, eid, _finalist({"kind": "edge"}), {"title": "T"}, log)

    # The holdout numbers landed in the FEED (gatekeeper-held), proving they were produced...
    holdout_evt = next(e for e in events if e["data"] and e["data"].get("phase") == "holdout")
    assert holdout_evt["data"]["stats"]["p_value"] is not None
    # ...but the generator-facing block (what strategy_memory feeds back to the proposer) carries
    # only the classification label — no p_value / dsr / ci / holdout pnl. (Leak 2 stays closed.)
    block = agent._result_block({"trades": 1}, {"capital": 1}, Classification.STAT_SUPPORTED.value)
    blob = json.dumps(block)
    for leak in ("p_value", "dsr", "psr", "ci_lo", "holdout", "placebo"):
        assert leak not in blob
