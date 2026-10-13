import json

import pytest

from app import agent
from app.llm import LLMError
from tests.test_app_backtest import _dataset


class Store:
    """In-memory stand-in for the repository calls the research loop makes."""

    def __init__(self, monkeypatch, status="running"):
        self.events, self.strategies, self.finished, self.status = [], [], None, status
        r = agent.repo
        monkeypatch.setattr(r, "add_event", lambda cur, run_id, kind, msg, data=None: self.events.append((kind, msg, data)))
        monkeypatch.setattr(r, "heartbeat", lambda cur, run_id: self.status)
        monkeypatch.setattr(r, "strategy_memory", lambda cur, uid, market: [])
        monkeypatch.setattr(r, "insert_strategy", self._insert)
        monkeypatch.setattr(r, "finish_run", lambda cur, run_id, status, error=None, tried=0, passed=0, *a: setattr(self, "finished", (status, error, tried, passed)))

    def _insert(self, cur, uid, run_id, parent, market, direction, title, thesis, spec, status, result):
        self.strategies.append({"title": title, "status": status, "result": result, "spec": spec})
        return len(self.strategies)


class Conn:
    def cursor(self):
        return None


RUN = {"id": 1, "user_id": 7, "market": "btc15m", "direction": "volatility", "prompt": None}
WINNER = {"side": "yes", "entry": {"min_edge": 0.1}}
LOSER = {"side": "no", "entry": {"min_edge": 0.1, "min_price": 0.5}}


def scripted(replies):
    prompts = []

    def model(system, messages):
        prompts.append(messages[-1]["content"])
        return replies.pop(0), {"input_tokens": 10, "output_tokens": 5}

    return model, prompts


def hyps(*specs):
    return "```json\n%s\n```" % json.dumps({"hypotheses": [
        {"title": "H%d" % i, "thesis": "Because %d." % i, "spec": s} for i, s in enumerate(specs)]})


def test_research_loop_saves_everything_and_hides_out_of_sample(monkeypatch):
    store = Store(monkeypatch)
    model, prompts = scripted([hyps(WINNER, LOSER), hyps(WINNER)])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m: _dataset(n_contracts=60))
    status, error, tried, passed = store.finished
    assert status == "succeeded" and tried == 3 and passed >= 1
    assert len(store.strategies) == 3
    assert {s["status"] for s in store.strategies} <= {"passed", "failed", "rejected"}
    # The agent iterates on in-sample only: no unseen-data numbers or cutoff in what it reads.
    for p in prompts:
        assert "out_of_sample" not in p
    # Rejected hypotheses never ran out-of-sample.
    for s in store.strategies:
        if s["status"] == "rejected":
            assert "out_of_sample" not in s["result"]


def test_invalid_spec_gets_one_repair(monkeypatch):
    store = Store(monkeypatch)
    bad = hyps({"entry": {"min_edge": 7}})
    model, prompts = scripted([bad, hyps(WINNER), hyps(WINNER)])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    assert "rejected" in prompts[1] and "min_edge=7" in prompts[1]


def test_unrepairable_reply_fails_the_run_visibly(monkeypatch):
    store = Store(monkeypatch)
    model, _ = scripted(["no json here", "still none"])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m: _dataset(n_contracts=60))
    assert store.finished[0] == "failed"
    assert store.events[-1][0] == "error"


def test_too_little_history_fails_before_spending_on_the_model(monkeypatch):
    store = Store(monkeypatch)
    model, prompts = scripted([])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m: _dataset(n_contracts=2))
    assert store.finished[0] == "failed" and prompts == []


def test_cancel_stops_the_run(monkeypatch):
    store = Store(monkeypatch, status="cancelled")
    model, prompts = scripted([hyps(WINNER)])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m: _dataset(n_contracts=60))
    assert store.finished is None and store.strategies == []


def test_autopilot_cannot_raise_risk_or_touch_live(monkeypatch):
    dep = {"id": 3, "title": "T", "status": "running", "mode": "paper", "market": "btc15m", "direction": "volatility",
           "strategy_id": 9, "spec": agent.specmod.validate(WINNER)}
    calls = []
    r = agent.repo
    monkeypatch.setattr(r, "get_deployment", lambda cur, uid, did: dict(dep))
    monkeypatch.setattr(r, "insert_strategy", lambda *a: 99)
    monkeypatch.setattr(r, "create_proposal", lambda cur, uid, kind, reason, did=None, sid=None, status="pending": calls.append(("proposal", kind, status)) or 1)
    monkeypatch.setattr(r, "set_deployment_strategy", lambda *a: calls.append(("applied",)))
    monkeypatch.setattr(r, "set_deployment_status", lambda *a: calls.append(("status",) + a[3:4]))
    ds = lambda m: _dataset(n_contracts=60)
    user = {"id": 1}

    agent.act(None, user, {"type": "adjust", "deployment_id": 3, "changes": {"sizing": {"stake": 50}}}, True, ds)
    assert calls[-1] == ("proposal", "adjust", "pending")  # bigger stake: needs the human
    agent.act(None, user, {"type": "adjust", "deployment_id": 3, "changes": {"entry": {"min_edge": 0.12}}}, True, ds)
    assert calls[-2:] == [("proposal", "adjust", "applied"), ("applied",)]
    dep["mode"], dep["status"] = "live", "paused"
    agent.act(None, user, {"type": "resume", "deployment_id": 3}, True, ds)
    assert calls[-1] == ("proposal", "resume", "pending")  # live: never on its own
    dep["status"] = "running"
    agent.act(None, user, {"type": "pause", "deployment_id": 3}, True, ds)
    assert calls[-1] == ("status", "paused")  # pausing only lowers risk


def test_adjustment_that_fails_the_gates_is_not_proposed(monkeypatch):
    dep = {"id": 3, "title": "T", "status": "running", "mode": "paper", "market": "btc15m", "direction": "volatility",
           "strategy_id": 9, "spec": agent.specmod.validate(WINNER)}
    monkeypatch.setattr(agent.repo, "get_deployment", lambda cur, uid, did: dict(dep))
    monkeypatch.setattr(agent.repo, "create_proposal", lambda *a, **k: pytest.fail("must not propose"))
    text, pid = agent.act(None, {"id": 1}, {"type": "adjust", "deployment_id": 3, "changes": {"side": "no"}}, False,
                          lambda m: _dataset(n_contracts=60))
    assert pid is None and "failed" in text


def test_llm_error_type():
    assert issubclass(LLMError, RuntimeError)
