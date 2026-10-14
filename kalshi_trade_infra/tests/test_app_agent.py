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

    def commit(self):
        pass


RUN = {"id": 1, "user_id": 7, "market": "btc15m", "direction": "volatility", "prompt": None}
WINNER = {"side": "yes", "entry": {"min_edge": 0.1}}
LOSER = {"side": "no", "entry": {"min_edge": 0.1, "min_price": 0.5}}


def scripted(replies):
    prompts = []

    def model(system, messages):
        prompts.append(messages[-1]["content"])
        return replies.pop(0), {"input_tokens": 10, "output_tokens": 5}

    return model, prompts


def plan(days=30):
    return '```json\n%s\n```' % json.dumps({"lookback_days": days, "why": "fits the thesis"})


def pick(m="btc15m"):
    return '```json\n%s\n```' % json.dumps({"market": m, "why": "fits the idea"})


def hyps(*specs):
    return "```json\n%s\n```" % json.dumps({"hypotheses": [
        {"title": "H%d" % i, "thesis": "Because %d." % i, "spec": s} for i, s in enumerate(specs)]})


def test_research_loop_saves_everything_and_hides_out_of_sample(monkeypatch):
    store = Store(monkeypatch)
    model, prompts = scripted([plan(), hyps(WINNER, LOSER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 3}, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
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
    model, prompts = scripted([plan(), bad, hyps(WINNER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 2}, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    assert "rejected" in prompts[2] and "min_edge=7" in prompts[2]


def test_unrepairable_reply_fails_the_run_visibly(monkeypatch):
    store = Store(monkeypatch)
    model, _ = scripted([plan(), "no json here", "still none"])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "failed"
    assert store.events[-1][0] == "error"


def test_too_little_history_fails_before_spending_on_the_model(monkeypatch):
    store = Store(monkeypatch)
    model, prompts = scripted([])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=2))
    assert store.finished[0] == "failed" and prompts == []


def test_cancel_stops_the_run(monkeypatch):
    store = Store(monkeypatch, status="cancelled")
    model, prompts = scripted([plan(), hyps(WINNER)])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
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


def test_budget_is_honored_and_the_agent_iterates(monkeypatch):
    store = Store(monkeypatch)
    # budget 10, BATCH 4 -> refining rounds of 4, 4, 2 (not a fixed two-shot)
    model, prompts = scripted([plan(),
                               hyps(WINNER, LOSER, WINNER, LOSER),
                               hyps(WINNER, LOSER, WINNER, LOSER),
                               hyps(WINNER, LOSER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 10}, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    status, error, tried, passed = store.finished
    assert status == "succeeded" and tried == 10            # the 10-hypothesis budget was honored
    assert len(prompts) == 4                                # 1 window-plan call + 3 refining rounds
    assert "Results so far" in prompts[2]                   # later rounds learn from prior in-sample results


def test_run_forever_runs_many_chunks_until_cancelled(monkeypatch):
    store = Store(monkeypatch)
    beats = {"n": 0}

    def hb(cur, run_id):
        beats["n"] += 1
        return "running" if beats["n"] < 10 else "cancelled"

    monkeypatch.setattr(agent.repo, "heartbeat", hb)
    model, _ = scripted([plan()] + [hyps(WINNER, LOSER)] * 30)
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 2, "run_forever": True},
                       model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished is None                            # cancelled mid-run, not "succeeded"
    assert any(k == "step" and "Cancelled" in m for (k, m, d) in store.events)
    assert len(store.strategies) >= 2                        # it had completed at least one chunk first


def test_plan_lookback_clamps_to_available_history():
    from app import agent
    from app.llm import Usage
    from app.markets import MARKETS
    big = "```json\n%s\n```" % json.dumps({"lookback_days": 9999, "why": "lots"})
    model, _ = scripted([big])
    days = agent._plan_lookback({"market": "btc15m", "prompt": "x"}, "btc15m", model, Usage(), lambda *a, **k: None)
    assert days == MARKETS["btc15m"].history_days      # never asks for more history than exists


def test_agent_picks_market_when_unspecified(monkeypatch):
    store = Store(monkeypatch)
    picked = []
    monkeypatch.setattr(agent.repo, "set_run_market", lambda cur, rid, mk: picked.append(mk))
    model, prompts = scripted([pick("btc15m"), plan(), hyps(WINNER, LOSER), hyps(WINNER)])
    run = {"id": 1, "user_id": 7, "market": None, "direction": None, "prompt": "trade something", "max_hypotheses": 3}
    agent.run_research(Conn(), run, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    assert picked == ["btc15m"]                 # the agent chose the market and it was persisted
