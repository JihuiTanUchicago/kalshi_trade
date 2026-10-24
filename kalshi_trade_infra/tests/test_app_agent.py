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
        # Emergency-recovery checkpoint: default to a fresh run (no saved checkpoint) and a no-op
        # persist, so these clean-run tests behave exactly as before. Resume behaviour has its own
        # dedicated tests that drive load_checkpoint/save_checkpoint directly.
        monkeypatch.setattr(r, "load_checkpoint", lambda cur, run_id: None)
        monkeypatch.setattr(r, "save_checkpoint", lambda cur, run_id, ck: None)
        monkeypatch.setattr(r, "credit_balance", lambda *a, **k: 100.0)
        # Tau-RSI: no stored policy (use the default), and no discovery history to
        # dream over, so the self-evolution step is a clean no-op in these tests.
        monkeypatch.setattr(r, "get_policy", lambda *a, **k: None)
        monkeypatch.setattr(r, "strategy_records", lambda *a, **k: [])
        # Research RSI playbooks: none drawn, nothing learned (the wiring has its own tests below).
        monkeypatch.setattr(agent, "_rsi_choose", lambda *a, **k: "")
        monkeypatch.setattr(agent, "_rsi_learn", lambda *a, **k: None)
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
        # §E.5 promotion runs for every STAT_SUPPORTED finalist; stub the one-time holdout +
        # diversification gate so these hand-off tests stay off the ledger DB (the promotion
        # itself is covered in test_gatekeeper + test_holdout_promotion).
        monkeypatch.setattr(agent.gatekeeper, "judge_holdout",
                            lambda cur, eid, fin, run_load=None: {"classification": self._gk.Classification.FORWARD_VALIDATED.value,
                                                   "n_trades": 20, "holdout_consumed": 0})
        monkeypatch.setattr(agent.gatekeeper, "marginal_contribution_ok",
                            lambda cur, uid, eid, fin: (True, "stub"))
        monkeypatch.setattr(agent, "_challenge",
                            lambda finalists, run, model, usage, log: [{"decision": "approve", "reason": "", "fixes": None} for _ in finalists])
        # Pillar 2 per-thesis depth adds a model turn per thesis; pin it OFF here so the scripted
        # replies stay 1:1 with the proposer rounds. The deep loop itself is covered below.
        monkeypatch.setattr(agent, "THESIS_MAX_STEPS", 1)

    def _insert(self, cur, uid, run_id, parent, market, direction, title, thesis, spec, status, result):
        self.strategies.append({"title": title, "status": status, "result": result, "spec": spec, "parent": parent})
        return len(self.strategies)

    def _set_outcome(self, cur, strategy_id, status, result, experiment_id=None):
        self.strategies[strategy_id - 1].update(status=status, result=result, experiment_id=experiment_id)

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


def _fence(obj):
    return "```json\n%s\n```" % json.dumps(obj)


def test_deep_thesis_refines_on_research_fold_then_commits_one_spec(monkeypatch):
    """Pillar 2: with per-thesis depth on, the agent backtests a thesis, refines it, then commits
    ONE spec — the refined one — and it still produces exactly one candidate (one trial)."""
    store = Store(monkeypatch)
    monkeypatch.setattr(agent, "THESIS_MAX_STEPS", 3)  # up to 2 develop turns per thesis
    refined = {"side": "no", "entry": {"min_edge": 0.2}}
    model, prompts = scripted([plan(), hyps(WINNER),
                               _fence({"decision": "refine", "spec": refined, "change": "flip side"}),
                               _fence({"decision": "commit", "why": "mechanism holds"})])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    status, _, tried, _ = store.finished
    assert status == "succeeded" and tried == 1          # one thesis -> one candidate (no trial inflation)
    assert len(store.strategies) == 1
    assert store.strategies[0]["spec"]["side"] == "no"   # committed the REFINED spec, not the first draft
    # The develop turn reads the research fold only: never a held-out number.
    assert any("research fold" in p.lower() for p in prompts)
    for p in prompts:
        assert "out_of_sample" not in p


def test_develop_thesis_module_self_check():
    agent._develop_self_check()


def test_call_with_timeout_self_check():
    agent._timeout_self_check()


def test_dream_cadence_self_check():
    agent._dream_cadence_self_check()


def test_invalid_spec_gets_one_repair(monkeypatch):
    store = Store(monkeypatch)
    bad = hyps({"entry": {"min_edge": 7}})
    model, prompts = scripted([plan(), bad, hyps(WINNER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 2}, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    assert "rejected" in prompts[2] and "min_edge=7" in prompts[2]


def test_unrepairable_reply_fails_the_run_visibly(monkeypatch):
    store = Store(monkeypatch)
    model, _ = scripted([plan(), "no json here", "still none", "and still none"])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "failed"
    assert store.events[-1][0] == "error"


def test_too_little_history_stops_before_spending_on_the_model(monkeypatch):
    store = Store(monkeypatch)
    model, prompts = scripted([])
    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=2))
    # Not-enough-data is a NoData case: the run ends `stopped` (neutral), not a red `failed`.
    assert store.finished[0] == "stopped" and prompts == []


def test_unknown_pinned_market_fails_cleanly_not_as_keyerror(monkeypatch):
    """A pinned market no longer in MARKETS (a retired/renamed series) must fail with a clean,
    user-facing message BEFORE any model spend — not surface as the bare KeyError('<key>') that
    the old setup raised and that logged the useless "Unexpected error: '<key>'"."""
    store = Store(monkeypatch)
    model, prompts = scripted([])
    agent.run_research(Conn(), {**RUN, "market": "retired_series_xyz"}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    status, error, _, _ = store.finished
    assert status == "failed" and prompts == []            # died before a single model call
    assert "retired_series_xyz" in error and "no longer available" in error
    assert not error.startswith("Unexpected error")        # a clean message, not a raw KeyError dump


def test_autopilot_run_on_a_vanished_market_repicks_instead_of_failing(monkeypatch):
    """An agent-launched (brief) run whose catalog market dropped out before it started keeps the
    angle and lets the picker choose, rather than burning a slot on a 'no longer available' fail."""
    store = Store(monkeypatch)
    picked, pinned = [], []
    monkeypatch.setattr(agent, "_pick_market", lambda run, model, usage, log, keys, hist: picked.append(keys) or "btc15m")
    monkeypatch.setattr(agent.repo, "set_run_market", lambda cur, rid, m: pinned.append(m))
    model, _ = scripted([])
    agent.run_research(Conn(), {**RUN, "market": "retired_series_xyz", "brief": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=2))
    assert picked and pinned == ["btc15m"]
    assert store.finished[0] == "stopped"  # reached the data load on the new market, not 'failed'


def test_sports_market_passes_the_universe_guard_and_runs(monkeypatch):
    """The guard must NOT reject a real curated sports market (underlying=None): nba_game is in
    MARKETS, so the run gets past the chokepoint and researches exactly like a crypto market."""
    from app.markets import MARKETS
    assert "nba_game" in MARKETS and MARKETS["nba_game"].underlying is None
    store = Store(monkeypatch)
    model, prompts = scripted([plan(), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "market": "nba_game", "max_hypotheses": 1},
                       model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"                 # cleared the guard and ran the loop
    assert prompts and all(s["spec"]["market"] == "nba_game" for s in store.strategies)


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
    assert pid is None and "didn't pass these checks" in text and '"' in text


def test_repeat_note_query_matches_exact_text_since_a_time():
    class Cur:
        def execute(self, sql, params):
            self.sql, self.params = " ".join(sql.split()), params
        def fetchone(self):
            return {"1": 1}
    cur, since = Cur(), agent.repo.now_utc()
    assert agent.repo.recent_chat_same(cur, 2, "system", "same line", since) is True
    assert "created_at>=%s AND content=%s" in cur.sql and cur.params == (2, "system", since, "same line")


def test_adjustment_is_backtest_only_not_passed_and_cannot_be_deployed(monkeypatch):
    # An adjustment is only a re-backtest — it never goes through pre-registration or the
    # gatekeeper, so it must NOT be minted "passed" (the status the deploy gates key on). It gets
    # the non-deployable "backtest-only" status; the adjustment still applies to its deployment.
    dep = {"id": 3, "title": "T", "status": "running", "mode": "paper", "market": "btc15m",
           "direction": "volatility", "strategy_id": 9, "spec": agent.specmod.validate(WINNER)}
    inserted = {}
    r = agent.repo
    monkeypatch.setattr(r, "get_deployment", lambda cur, uid, did: dict(dep))
    monkeypatch.setattr(r, "insert_strategy",
                        lambda cur, uid, run_id, parent, market, direction, title, thesis, spec, status, result:
                        inserted.update(status=status) or 99)
    monkeypatch.setattr(r, "create_proposal", lambda *a, **k: 1)
    monkeypatch.setattr(r, "set_deployment_strategy", lambda *a: None)
    ds = lambda m: _dataset(n_contracts=60)
    agent.act(None, {"id": 1}, {"type": "adjust", "deployment_id": 3, "changes": {"entry": {"min_edge": 0.12}}}, True, ds)
    assert inserted["status"] == "backtest-only"  # strictly stricter: not "passed"

    # The deploy gate rejects it precisely because status != "passed" (never weakened/reordered).
    monkeypatch.setattr(r, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "status": "backtest-only", "title": "T",
        "spec": agent.specmod.validate(WINNER), "market": "btc15m"})
    msg, pid = agent.act(None, {"id": 1}, {"type": "deploy", "strategy_id": 99}, False, ds)
    assert pid is None and "passed" in msg


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


def test_a_reaped_run_stops_its_zombie_copy_quietly(monkeypatch):
    """The watchdog re-queued the run while this thread was in a long silent phase: the old thread
    must stop at its next checkpoint, writing no events and no finish over the new owner's record."""
    store = Store(monkeypatch)
    beats = {"n": 0}

    def hb(cur, run_id):
        beats["n"] += 1
        return "running" if beats["n"] < 3 else "queued"

    monkeypatch.setattr(agent.repo, "heartbeat", hb)
    monkeypatch.setattr(agent.repo, "run_worker", lambda cur, run_id: "w1")
    model, _ = scripted([plan()] + [hyps(WINNER, LOSER)] * 30)
    agent.run_research(Conn(), {**RUN, "worker_id": "w1", "max_hypotheses": 2, "run_forever": True},
                       model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished is None
    assert not any("Cancelled" in m for (k, m, d) in store.events)
    n_events = len(store.events)
    assert beats["n"] == 3 and n_events > 0


def test_a_run_reclaimed_by_another_worker_stops_this_copy(monkeypatch):
    store = Store(monkeypatch)
    owners = iter(["w1", "w1", "w2"])
    monkeypatch.setattr(agent.repo, "run_worker", lambda cur, run_id: next(owners, "w2"))
    model, _ = scripted([plan()] + [hyps(WINNER, LOSER)] * 30)
    agent.run_research(Conn(), {**RUN, "worker_id": "w1", "max_hypotheses": 2, "run_forever": True},
                       model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished is None


def test_run_worker_reads_the_owner():
    from app import repository as repo

    class Rec:
        def execute(self, sql, params=()):
            self.sql, self.params = sql, params

        def fetchone(self):
            return {"worker_id": "host:1:0"}

    cur = Rec()
    assert repo.run_worker(cur, 5) == "host:1:0" and cur.params == (5,)


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


def test_act_normalizes_a_messy_action_type(monkeypatch):
    # The model sometimes emits "Research"/"research "/"research\n" (or under "kind"); a whitespace/
    # casing variant must still route to the research handler, not the "not allowed" fallback.
    created = []
    r = agent.repo
    monkeypatch.setattr(r, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(r, "create_run", lambda cur, uid, kind, market, direction, prompt, **kw:
                        created.append((kind, market)) or 9)
    for messy in ({"type": " Research\n", "market": "btc15m", "idea": "favorite-longshot bias"},
                  {"kind": "research", "market": "btc15m", "idea": "favorite-longshot bias"}):
        created.clear()
        text, pid = agent.act(None, {"id": 1}, messy, True)
        assert "not allowed" not in text, "messy type %r fell through to the fallback" % messy
        assert created == [("research", "btc15m")]


def test_agent_picks_market_when_unspecified(monkeypatch):
    store = Store(monkeypatch)
    picked = []
    monkeypatch.setattr(agent.repo, "set_run_market", lambda cur, rid, mk: picked.append(mk))
    model, prompts = scripted([pick("btc15m"), plan(), hyps(WINNER, LOSER), hyps(WINNER)])
    run = {"id": 1, "user_id": 7, "market": None, "direction": None, "prompt": "trade something", "max_hypotheses": 3}
    agent.run_research(Conn(), run, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    assert picked == ["btc15m"]                 # the agent chose the market and it was persisted


# -- resilience: reconnect; bill for work done on ANY failure (incl. infra blips) --------


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


def test_infra_error_still_bills(monkeypatch):
    # Policy: the work done is charged regardless of the failure cause — an infra/DB blip bills
    # too (no "no charge, start again" message), same as a logic error.
    store = Store(monkeypatch)
    billed = []
    monkeypatch.setattr(agent, "_bill", lambda *a, **k: billed.append(a))
    monkeypatch.setattr(agent.repo, "strategy_memory", _raise(_conn_drop()))
    model, _ = scripted([plan()])
    with pytest.raises(pymysql.err.OperationalError):
        agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "failed"
    assert len(billed) == 1  # billed for the work done even on an RDS blip


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


def test_proposer_explores_diverse_families(monkeypatch):
    # The system prompt must render the seed palette + the fitted-model routes AND frame the palette
    # as OPEN (invent beyond it; economic / academic / classical-statistical lenses all welcome, not
    # just ML), and the per-call prompt must demand a diverse, mechanism-spanning, fitted-model-
    # including set — this is what stops the proposer defaulting to a batch of if-else threshold variants.
    names = [n for n, _ in agent.STRATEGY_FAMILIES]
    assert len(names) == len(set(names)) >= 8  # a real spread, no dupes
    for name, _how in agent.STRATEGY_FAMILIES:
        assert name in agent.RESEARCH_SYSTEM
    for kind in ('model.kind="logistic"', 'model.kind="calibration"', "fit(window)"):
        assert kind in agent.RESEARCH_SYSTEM  # fitted routes, not just thresholds
    # Freedom, not a fixed menu: off-list angles are welcomed and every intellectual lens is allowed.
    assert "NOT A CLOSED MENU" in agent.RESEARCH_SYSTEM and "worth MORE, not less" in agent.RESEARCH_SYSTEM
    for lens in ("ECONOMIC", "ACADEMIC", "econometric", "NOT only machine learning"):
        assert lens in agent.RESEARCH_SYSTEM
    proposer = agent._research_prompt(RUN, _dataset(n_contracts=60), [], count=5)
    assert "DIFFERENT mechanisms and model structures" in proposer and "FITTED model" in proposer
    assert "counts for MORE" in proposer  # an off-palette, well-motivated angle is rewarded
    assert "span at least 5" in proposer  # min(count=5, len(STRATEGY_FAMILIES))


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


def test_classify_load_error_self_check():
    agent._classify_self_check()


def test_load_passes_through_a_normal_result():
    # The timeout+classify wrapping must NOT alter a normal successful load.
    assert agent._load("ok", lambda: "DATASET") == "DATASET"
    sentinel = object()
    assert agent._load("ok", lambda a, b: (a, b), sentinel, 2) == (sentinel, 2)


def test_load_classifies_no_settled_contracts():
    # A sports/un-settled market's "no settled contracts" ValueError surfaces as a specific,
    # market-naming LLMError (not the generic "unexpected error").
    def boom():
        raise ValueError("no settled contracts for market 'kxnflgame' since 2024-01-01")
    with pytest.raises(agent.NoData) as ei:   # a NoData subclass -> the run finishes `stopped`, not failed
        agent._load("Loading data", boom)
    assert "kxnflgame" in str(ei.value) and "no settled contracts" in str(ei.value)


def test_load_classifies_transient_db_error(monkeypatch):
    # A transient RDS drop (2013) that persists through every retry surfaces as the clean,
    # retryable LLMError. Backoff zeroed so the test doesn't actually sleep.
    monkeypatch.setattr(agent, "LOAD_RETRY_BACKOFF", 0.0)
    def boom():
        raise _conn_drop()  # pymysql.err.OperationalError(2013, "Lost connection …")
    with pytest.raises(LLMError) as ei:
        agent._load("Loading data", boom)
    assert str(ei.value) == "The data store was busy; please start the session again."


def test_load_retries_a_transient_drop_then_succeeds(monkeypatch):
    # A transient RDS blip is absorbed in place: the load retries and returns the real dataset,
    # so the user never sees "data store was busy" for a one-off drop.
    monkeypatch.setattr(agent, "LOAD_RETRY_BACKOFF", 0.0)
    monkeypatch.setattr(agent, "LOAD_RETRIES", 2)
    calls = [0]
    def flaky():
        calls[0] += 1
        if calls[0] < 3:
            raise _conn_drop()
        return "DATASET"
    assert agent._load("Loading data", flaky) == "DATASET"
    assert calls[0] == 3  # two drops absorbed, third attempt succeeded


def test_load_does_not_retry_a_non_transient_error(monkeypatch):
    # A genuine bug (not a transient DB drop) is NOT retried — it propagates on the first attempt.
    monkeypatch.setattr(agent, "LOAD_RETRY_BACKOFF", 0.0)
    calls = [0]
    def boom():
        calls[0] += 1
        raise KeyError("missing_key")
    with pytest.raises(KeyError):
        agent._load("Loading data", boom)
    assert calls[0] == 1  # not retried


def test_load_does_not_swallow_a_genuine_bug():
    def boom():
        raise KeyError("missing_key")
    with pytest.raises(KeyError):
        agent._load("Loading data", boom)


def test_no_settled_contracts_surfaces_a_clean_message_end_to_end(monkeypatch):
    # Through run_research: a startup load that raises the no-settled-contracts ValueError is
    # recorded as the specific LLMError (not re-raised, not the generic "unexpected error").
    store = Store(monkeypatch)
    model, _ = scripted([plan()])
    def no_data(m, h=None):
        raise ValueError("no settled contracts for market 'btc15m' since 2024-01-01")
    agent.run_research(Conn(), RUN, model=model, dataset_fn=no_data)  # NoData -> does not re-raise
    status, error, _, _ = store.finished
    assert status == "stopped"   # a dataless market is NOT a failure — nothing to research there yet
    assert "btc15m" in error and "no settled contracts" in error


def test_transient_db_drop_in_a_load_surfaces_a_clean_message_end_to_end(monkeypatch):
    # A transient RDS drop DURING the startup load is relabelled retryable and does not re-raise —
    # unlike a drop on a non-load call (test_infra_error_still_bills), which still propagates.
    store = Store(monkeypatch)
    model, _ = scripted([plan()])
    def dropped(m, h=None):
        raise _conn_drop()
    agent.run_research(Conn(), RUN, model=model, dataset_fn=dropped)
    status, error, _, _ = store.finished
    assert status == "failed"
    assert error == "The data store was busy; please start the session again."


def test_adjust_missing_deployment_lists_current_ones_not_a_dead_end(monkeypatch):
    # The agent often references a deployment it named earlier that has since been removed. act()
    # must not dead-end with a vague "couldn't find"; it names what's gone AND lists the current
    # deployments so the next review acts on a real one.
    r = agent.repo
    monkeypatch.setattr(r, "get_deployment", lambda cur, uid, did: None)  # the referenced one is gone
    monkeypatch.setattr(r, "list_deployments", lambda cur, uid: [
        {"id": 42, "title": "Live BTC edge", "market": "btc15m", "status": "running"}])
    msg, pid = agent.act(None, {"id": 1}, {"type": "adjust", "deployment_id": 999, "changes": {"x": 1}}, True)
    assert pid is None
    assert "999" in msg and "#42" in msg and "Live BTC edge" in msg  # self-correcting, not a dead end


def test_finished_research_run_prints_one_outcome_line(monkeypatch, capsys):
    store = Store(monkeypatch)
    model, _prompts = scripted([plan(), hyps(WINNER, LOSER), hyps(WINNER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 3}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("[research] run=")]
    assert len(lines) == 1
    assert "status=succeeded tried=3" in lines[0] and "verdicts=" in lines[0]
    assert "validation:" in lines[0], "each gatekeeper verdict is tallied by phase"


def test_research_outcome_line_format():
    line = agent.research_outcome_line(7, 2, "btc15m", "failed", 4, 0, 100, 20, "m",
                                       {"validation:rejected": 3}, "RuntimeError")
    assert line == ("[research] run=7 user=2 market=btc15m status=failed tried=4 passed=0 tokens_in=100 "
                    "tokens_out=20 model=m verdicts=validation:rejected=3 error=RuntimeError")


def test_outcome_line_counts_theses_dropped_on_the_research_fold(monkeypatch, capsys):
    """A run whose every thesis dies on the research fold counts those theses as tried (the sessions
    list showed "0 of 0 passed" for runs that explored 8 ideas), and the outcome line still says how
    many were dropped."""
    store = Store(monkeypatch)
    model, _prompts = scripted([plan()] + [hyps(WINNER, LOSER)] * 20)
    monkeypatch.setattr(agent, "_develop_thesis",
                        lambda h, run, ds, partition, memory, proposer, md, usage, log, *a, **k:
                        agent._abandon(log, h, "dead on arrival", k.get("dropped")))
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 3}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("[research] run=")][0]
    assert "tried=8" in line and "research:dropped=8" in line
    assert store.finished[0] == "succeeded" and store.finished[2] == 8   # what the sessions list shows


def test_the_drawn_playbook_reaches_the_proposer_and_the_develop_turn(monkeypatch):
    store = Store(monkeypatch)
    monkeypatch.setattr(agent, "THESIS_MAX_STEPS", 2)
    monkeypatch.setattr(agent, "_rsi_choose", lambda cur, uid, market, run_id, log:
                        "RESEARCH PLAYBOOK v2 for crypto markets:\nDEAD ENDS\n- ZEBRA-LESSON")
    model, prompts = scripted([plan(), hyps(WINNER), _fence({"decision": "commit", "why": "holds"})])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 1}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store.finished[0] == "succeeded"
    with_lesson = [p for p in prompts if "ZEBRA-LESSON" in p]
    assert len(with_lesson) == 2 and "Develop THIS one thesis" in with_lesson[1]


def test_after_a_run_the_playbook_is_scored_settled_and_rewritten(monkeypatch):
    """_rsi_learn credits the run to its playbook, settles the trial, and with no candidate pending
    asks the model for the next version from this run's verdicts (labels only)."""
    from app import rsi_playbook
    calls, logged = {}, []
    events = [{"kind": "verdict", "message": "DROPPED", "data": {"status": "abandoned", "title": "A",
                                                                  "why": "obs_high_f is not available"}}]
    monkeypatch.setattr(agent.repo, "run_events", lambda cur, run_id: events)
    monkeypatch.setattr(rsi_playbook, "score_run", lambda cur, run_id, card: calls.setdefault("card", card))
    monkeypatch.setattr(rsi_playbook, "decide", lambda cur, uid, fam, paper_of=None: "promoted v1 over v0 (P(better)=0.93)")
    pending = {"cand": None}
    monkeypatch.setattr(rsi_playbook, "candidate", lambda cur, uid, fam: pending["cand"])
    monkeypatch.setattr(rsi_playbook, "active", lambda cur, uid, fam: {"id": 5, "version": 1, "text": "old"})
    monkeypatch.setattr(rsi_playbook, "add_candidate",
                        lambda cur, uid, fam, parent, text, changes, run_id: calls.setdefault("new", (text, run_id)) and 2)
    reply = _fence({"playbook": "PIPELINE FACTS\n- obs_high_f IS populated on settling days", "changes": "fixed a myth"})
    model, prompts = scripted([reply])
    usage = agent.Usage()
    log = lambda kind, msg, data=None: logged.append(msg)  # noqa: E731
    ds = _dataset(n_contracts=60)
    agent._rsi_learn(Conn(), None, dict(RUN, market="btc15m"), ds, 3, 1000, 100, model, usage, log)
    assert calls["card"]["explored"] == 3 and calls["card"]["death_kinds"] == {"pipeline": 1}
    assert calls["new"] == ("PIPELINE FACTS\n- obs_high_f IS populated on settling days", 1)
    assert any("promoted v1 over v0" in m for m in logged)
    assert any(m.startswith("Wrote research playbook v2") and "fixed a myth" in m for m in logged)
    assert "obs_high_f is not available" in prompts[0] and usage.input_tokens == 10
    # A candidate already on trial: score and settle only, no rewrite (one trial at a time).
    pending["cand"] = {"id": 6, "version": 2}
    model2, prompts2 = scripted([])
    agent._rsi_learn(Conn(), None, dict(RUN, market="btc15m"), ds, 3, 1000, 100, model2, agent.Usage(), log)
    assert prompts2 == []


def test_scan_outcomes_and_tally_query():
    from datetime import date
    from app import repository as repo
    assert repo.scan_outcome({"qualifying": 2, "contracts": 3}) == "qualified"
    assert repo.scan_outcome({"qualifying": 0, "contracts": 0}) == "no contracts"
    assert repo.scan_outcome({"qualifying": 0, "contracts": 4, "blocked_at": "a spread of 5c or less"}) == "a spread of 5c or less"

    class Cur:
        def __init__(self):
            self.calls = []

        def execute(self, sql, args=None):
            self.calls.append((sql, args))

        def fetchall(self):
            return [{"deployment_id": 7, "outcome": "qualified", "n": 3}, {"deployment_id": 7, "outcome": "x", "n": 5}]
    cur = Cur()
    assert repo.scan_tally(cur, [7, 8]) == {7: {"qualified": 3, "x": 5}}
    assert cur.calls[0][1][:2] == (7, 8) and isinstance(cur.calls[0][1][2], date)
    assert repo.scan_tally(cur, []) == {} and len(cur.calls) == 1
    cur = Cur()
    repo.set_deployment_scan(cur, 7, {"qualifying": 0, "contracts": 2, "blocked_at": "b"})
    assert "app_deployment_scan_days" in cur.calls[1][0] and cur.calls[1][1][0] == 7 and cur.calls[1][1][2] == "b"
