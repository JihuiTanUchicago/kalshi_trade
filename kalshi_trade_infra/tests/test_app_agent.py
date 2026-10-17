import json

import pytest

from app import agent
from app.llm import LLMError
from tests.test_app_backtest import _dataset


class Store:
    """In-memory stand-in for the repository calls the research loop makes."""

    def __init__(self, monkeypatch, status="running"):
        self.events, self.strategies, self.finished, self.status = [], [], None, status
        self._exp = 0
        r = agent.repo
        monkeypatch.setattr(r, "add_event", lambda cur, run_id, kind, msg, data=None: self.events.append((kind, msg, data)))
        monkeypatch.setattr(r, "heartbeat", lambda cur, run_id: self.status)
        monkeypatch.setattr(r, "strategy_memory", lambda cur, uid, market: [])
        monkeypatch.setattr(r, "insert_strategy", self._insert)
        monkeypatch.setattr(r, "set_strategy_outcome", self._set_outcome)
        monkeypatch.setattr(r, "finish_run", lambda cur, run_id, status, error=None, tried=0, passed=0, *a: setattr(self, "finished", (status, error, tried, passed)))
        monkeypatch.setattr(r, "update_run_progress", lambda *a, **k: None)
        monkeypatch.setattr(r, "set_run_market", lambda *a, **k: None)
        monkeypatch.setattr(r, "credit_balance", lambda *a, **k: 100.0)
        # Tau-RSI: no stored policy (use the default), and no discovery history to
        # dream over, so the self-evolution step is a clean no-op in these tests.
        monkeypatch.setattr(r, "get_policy", lambda *a, **k: None)
        monkeypatch.setattr(r, "strategy_records", lambda *a, **k: [])
        # Wave-2 gatekeeper hand-off: stub the frozen research partition and the Statistical
        # Gatekeeper so the research loop is testable without the ledger DB. judge_batch
        # classifies every approved finalist STAT_SUPPORTED (-> "passed"), and the challenger
        # approves each finalist as-is WITHOUT a model call, so the scripted replies stay 1:1
        # with the proposer rounds (prompt counts unchanged from the pre-gatekeeper loop).
        from app import gatekeeper
        self._gk = gatekeeper
        monkeypatch.setattr(agent.partitions, "ensure_partition",
                            lambda cur, market: {"id": 1, "embargo_seconds": 900, "purge_seconds": 900})
        monkeypatch.setattr(agent.backtest, "partition_dataset", lambda market, part, phase: None)
        monkeypatch.setattr(agent.gatekeeper, "preregister", self._preregister)
        monkeypatch.setattr(agent.gatekeeper, "judge_batch", self._judge_batch)
        monkeypatch.setattr(agent, "_challenge",
                            lambda finalists, run, model, usage, log: [{"decision": "approve", "reason": "", "fixes": None} for _ in finalists])

    def _insert(self, cur, uid, run_id, parent, market, direction, title, thesis, spec, status, result):
        self.strategies.append({"title": title, "status": status, "result": result, "spec": spec, "parent": parent})
        return len(self.strategies)

    def _set_outcome(self, cur, strategy_id, status, result):
        self.strategies[strategy_id - 1].update(status=status, result=result)

    def _preregister(self, cur, pre):
        self._exp += 1
        return self._exp

    def _judge_batch(self, cur, run_id, exp_ids, finalists, val_ds):
        return [{"classification": self._gk.Classification.STAT_SUPPORTED.value, "n_trades": 20}
                for _ in finalists]


class Conn:
    def __init__(self):
        self.pings = 0

    def ping(self, reconnect=True):
        self.pings += 1

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


PASSED_PARENT = {
    "id": 55, "title": "Overnight tail fade", "market": "btc15m", "direction": "volatility",
    "status": "passed", "thesis": "Cheap far-OTM YES is overpriced overnight.",
    "spec": {"side": "yes", "market": "btc15m", "entry": {"min_edge": 0.1}},
    "result": {"in_sample": {"pnl": 42.0, "trades": 30}, "classification": "statistically_supported"},
}


def test_dig_deeper_seeds_a_research_line_from_a_passed_strategy(monkeypatch):
    """Regression for the 'got stuck' follow-up: a run SEEDED from a passed strategy must run to
    completion through the normal gatekeeper, and each branched strategy must link back to the
    parent (discovery-tree lineage). Reproduces the exact seed path and asserts it progresses."""
    store = Store(monkeypatch)
    seeded = {
        "id": 1, "user_id": 7, "market": "btc15m", "direction": "volatility",
        "prompt": agent.dig_deeper_prompt(PASSED_PARENT), "max_hypotheses": 3,
        "seed_strategy_id": 55,   # the passed strategy this line branches off
    }
    model, prompts = scripted([plan(), hyps(WINNER, LOSER), hyps(WINNER)])
    agent.run_research(Conn(), seeded, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    status, error, tried, passed = store.finished
    assert status == "succeeded" and tried == 3 and passed >= 1          # completed, did not hang/crash
    # No bypass: the refined variants still went through pre-registration + judging (passed/failed/rejected).
    assert {s["status"] for s in store.strategies} <= {"passed", "failed", "rejected"}
    # Lineage: every branched strategy points back at the seed strategy.
    assert store.strategies and all(s["parent"] == 55 for s in store.strategies)
    # The seed's thesis + starting spec are carried into the research prompt as the starting point.
    assert "Dig deeper" in prompts[1] and "Overnight tail fade" in prompts[1]


def test_copilot_research_action_branches_a_passed_strategy(monkeypatch):
    created = []
    r = agent.repo
    monkeypatch.setattr(r, "get_strategy", lambda cur, uid, sid: dict(PASSED_PARENT) if sid == 55 else None)
    monkeypatch.setattr(r, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(r, "create_run", lambda cur, uid, kind, market, direction, prompt, **kw: created.append((kind, market, kw.get("seed_strategy_id"))) or 7)
    text, pid = agent.act(None, {"id": 7}, {"type": "research", "strategy_id": 55, "reason": "dig deeper"}, False)
    assert pid is None                                   # research queues a run; it is not a proposal
    assert created == [("research", "btc15m", 55)]       # a research run seeded from the passed strategy
    assert "digging deeper" in text.lower()


def test_copilot_research_action_refuses_a_strategy_that_did_not_pass(monkeypatch):
    r = agent.repo
    monkeypatch.setattr(r, "get_strategy", lambda cur, uid, sid: {**PASSED_PARENT, "status": "failed"})
    monkeypatch.setattr(r, "create_run", lambda *a, **k: pytest.fail("must not start research on an unpassed strategy"))
    text, pid = agent.act(None, {"id": 7}, {"type": "research", "strategy_id": 55, "reason": "x"}, False)
    assert pid is None and "passed" in text


def test_agent_picks_market_when_unspecified(monkeypatch):
    store = Store(monkeypatch)
    picked = []
    monkeypatch.setattr(agent.repo, "set_run_market", lambda cur, rid, mk: picked.append(mk))
    model, prompts = scripted([pick("btc15m"), plan(), hyps(WINNER, LOSER), hyps(WINNER)])
    run = {"id": 1, "user_id": 7, "market": None, "direction": None, "prompt": "trade something", "max_hypotheses": 3}
    agent.run_research(Conn(), run, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    assert picked == ["btc15m"]                 # the agent chose the market and it was persisted


# -- resilience: reconnect + don't bill infra failures (coordinator prod fix) --------


import pymysql  # noqa: E402  (grouped with the resilience tests that use it)


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


def _conn_drop():
    return pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")


def test_checkpoint_reconnects_to_survive_a_dropped_connection(monkeypatch):
    store = Store(monkeypatch)
    conn = Conn()
    model, _ = scripted([plan(), hyps(WINNER)])
    agent.run_research(conn, {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    assert conn.pings > 0  # the run ping-reconnects before the writes that follow each model call


def test_infra_error_fails_run_without_billing(monkeypatch):
    store = Store(monkeypatch)
    billed = []
    monkeypatch.setattr(agent, "_bill", lambda *a, **k: billed.append(a))
    monkeypatch.setattr(agent.repo, "strategy_memory", _raise(_conn_drop()))
    model, _ = scripted([plan()])
    with pytest.raises(pymysql.err.OperationalError):
        agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "failed"
    assert billed == []  # an RDS blip must never charge the user


def test_logic_error_still_bills(monkeypatch):
    store = Store(monkeypatch)
    billed = []
    monkeypatch.setattr(agent, "_bill", lambda *a, **k: billed.append(a))
    monkeypatch.setattr(agent.repo, "strategy_memory", _raise(RuntimeError("boom")))
    model, _ = scripted([plan()])
    with pytest.raises(RuntimeError):
        agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "failed"
    assert billed  # a genuine failure still bills for the tokens already spent


# -- interrupt & continue: pause / resume ------------------------------------------


def test_run_holds_while_paused_then_resumes(monkeypatch):
    store = Store(monkeypatch)
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def hb(cur, run_id):
        calls["n"] += 1
        return "paused" if calls["n"] in (3, 4) else "running"

    monkeypatch.setattr(agent.repo, "heartbeat", hb)
    model, _ = scripted([plan(), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"  # it resumed and finished where it left off
    kinds = [k for k, _, _ in store.events]
    assert "paused" in kinds and "resumed" in kinds


def test_paused_run_announced_only_once(monkeypatch):
    store = Store(monkeypatch)
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def hb(cur, run_id):
        calls["n"] += 1
        return "paused" if 3 <= calls["n"] <= 7 else "running"  # paused across several polls

    monkeypatch.setattr(agent.repo, "heartbeat", hb)
    model, _ = scripted([plan(), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert [k for k, _, _ in store.events].count("paused") == 1  # one notice per pause, not per poll


def test_cancel_while_paused_stops_the_run(monkeypatch):
    store = Store(monkeypatch)
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def hb(cur, run_id):
        calls["n"] += 1
        if calls["n"] == 3:
            return "paused"
        return "cancelled" if calls["n"] >= 4 else "running"

    monkeypatch.setattr(agent.repo, "heartbeat", hb)
    model, _ = scripted([plan(), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished is None  # Cancelled path never calls finish_run (matches existing cancel behavior)
    assert any(k == "step" and m == "Cancelled." for k, m, _ in store.events)


# -- richer log events: full reasoning + the research story ------------------------


def test_log_keeps_full_market_choice_reasoning(monkeypatch):
    store = Store(monkeypatch)
    long_why = ("BTC is the only market with enough liquidity and spreads tight enough that the "
                "edge still clears after Kalshi's taker fee, which is exactly where fees would "
                "otherwise eat the whole move on a thinner contract." + " More detail." * 10)
    assert len(long_why) > 200  # the old cap clipped exactly here, mid-word
    pick_long = "```json\n%s\n```" % json.dumps({"market": "btc15m", "why": long_why})
    model, _ = scripted([pick_long, plan(), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "market": None, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    chose = next(m for k, m, _ in store.events if k == "step" and m.startswith("Chose to research"))
    assert long_why in chose  # full reasoning survives end to end — no mid-word truncation


def test_hypothesis_event_carries_thesis_and_mechanism(monkeypatch):
    store = Store(monkeypatch)
    hyp_json = "```json\n%s\n```" % json.dumps({"hypotheses": [
        {"title": "H0", "thesis": "Edge from flow.", "mechanism": {"why": "late-session imbalance"},
         "spec": WINNER}]})
    model, _ = scripted([plan(), hyp_json])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    hyp = next(d for k, _, d in store.events if k == "hypothesis")
    assert hyp["thesis"] == "Edge from flow." and hyp["mechanism"] == {"why": "late-session imbalance"}


def test_challenger_verdict_is_logged(monkeypatch):
    store = Store(monkeypatch)
    monkeypatch.setattr(agent, "_challenge", lambda finalists, run, model, usage, log:
                        [{"decision": "approve", "reason": "mechanism holds up", "fixes": None} for _ in finalists])
    model, _ = scripted([plan(), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    chal = [m for k, m, _ in store.events if k == "challenger"]
    assert any("Challenger approved" in m and "mechanism holds up" in m for m in chal)


def streaming_scripted(replies):
    """A model that STREAMS its reply in chunks via on_delta, mirroring the Bedrock path. ask_json
    calls it with (system, messages); the proposer wrapper adds on_delta to drive the live feed."""
    def model(system, messages, on_delta=None):
        r = replies.pop(0)
        if on_delta:
            for i in range(0, len(r), 7):
                on_delta(r[i:i + 7])
        return r, {"input_tokens": 10, "output_tokens": 5}
    return model


def test_proposer_streams_thinking_events_sealed_with_an_end(monkeypatch):
    store = Store(monkeypatch)
    model = streaming_scripted([plan(), hyps(WINNER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    thinks = [(m, d) for k, m, d in store.events if k == "thinking"]
    assert thinks, "the proposer's generation should stream `thinking` events"
    assert any(d.get("block") and m for m, d in thinks), "a streamed chunk carries its block + text"
    assert any(d.get("end") for _, d in thinks), "the block is sealed with an end marker"


def test_non_streaming_model_runs_without_thinking_events(monkeypatch):
    # A model that only takes (system, messages) must still work — it just has no live tokens.
    store = Store(monkeypatch)
    model, _ = scripted([plan(), hyps(WINNER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    assert not [e for e in store.events if e[0] == "thinking"]


def test_proposer_prompt_asks_the_agent_to_think_aloud(monkeypatch):
    store = Store(monkeypatch)
    model, prompts = scripted([plan(), hyps(WINNER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert any("Think OUT LOUD" in p for p in prompts)


def test_hypothesis_event_carries_the_full_prereg(monkeypatch):
    store = Store(monkeypatch)
    hyp_json = "```json\n%s\n```" % json.dumps({"hypotheses": [{
        "title": "H0", "thesis": "Edge from flow.", "mechanism": {"who_pays": "retail"},
        "falsification_criteria": "no edge after fees", "negative_control": "shuffle labels",
        "spec": WINNER}]})
    model, _ = scripted([plan(), hyp_json])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    hyp = next(d for k, _, d in store.events if k == "hypothesis")
    assert hyp["spec"]["side"] == "yes"
    assert hyp["falsification"] == "no edge after fees" and hyp["negative_control"] == "shuffle labels"


def test_verdict_event_carries_gatekeeper_stats_for_the_feed(monkeypatch):
    store = Store(monkeypatch)
    model, _ = scripted([plan(), hyps(WINNER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    passed = [d for k, _, d in store.events if k == "verdict" and d and d.get("status") == "passed"]
    assert passed and passed[0]["stats"]["n_trades"] == 20
    # The stats are for the human feed — they must NOT be written into the strategy result that
    # feeds strategy_memory back to the generator (that stays blind to held-out numbers).
    assert all("p_value" not in (s.get("result") or {}) for s in store.strategies)
