"""Agent D — the generator's hand-off to the Statistical Gatekeeper (RESEARCH_PIPELINE_DESIGN
§B.5). These test the WIRING in agent._gate_and_save (not the gatekeeper's own math, which
tests/test_gatekeeper.py covers): the challenger gate before pre-registration, pre-register +
judge_batch for approved finalists, the classification->status mapping, and the structural
guarantees that keep validation/holdout evidence away from the generator.
"""
from types import SimpleNamespace

from app import agent
from app import exploration
from app import gatekeeper
from app import spec as specmod


# -- fakes ---------------------------------------------------------------------


class FakeStore:
    """Captures the repository + gatekeeper calls agent._gate_and_save makes."""

    def __init__(self, monkeypatch, judgements=None):
        self.strategies = []            # id -> {title, status, result, spec}
        self.preregistered = []         # list of Prereg objects
        self.judged = []                # list of (exp_ids, finalist payloads)
        self.events = []
        self._judgements = judgements   # list of classification values for judge_batch, or None
        monkeypatch.setattr(agent.repo, "insert_strategy", self._insert)
        monkeypatch.setattr(agent.repo, "set_strategy_outcome", self._set_outcome)
        monkeypatch.setattr(agent.gatekeeper, "preregister", self._preregister)
        monkeypatch.setattr(agent.gatekeeper, "judge_batch", self._judge_batch)
        monkeypatch.setattr(agent.backtest, "partition_dataset", lambda market, part, phase: None)

    def _insert(self, cur, uid, run_id, parent, market, direction, title, thesis, spec, status, result):
        self.strategies.append({"title": title, "status": status, "result": result, "spec": spec})
        return len(self.strategies)

    def _set_outcome(self, cur, strategy_id, status, result):
        self.strategies[strategy_id - 1].update(status=status, result=result)

    def _preregister(self, cur, pre):
        self.preregistered.append(pre)
        return len(self.preregistered)

    def _judge_batch(self, cur, run_id, exp_ids, finalists, val_ds):
        self.judged.append((list(exp_ids), list(finalists)))
        cls = self._judgements or [gatekeeper.Classification.STAT_SUPPORTED.value] * len(finalists)
        return [{"classification": cls[i], "n_trades": 30} for i in range(len(finalists))]


def _cand(title, pnl, trades, score):
    return {"title": title, "thesis": "because %s" % title,
            "spec": specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}}),
            "in_sample": {"pnl": pnl, "trades": trades}, "capital": 100.0, "score": score,
            "mechanism": {"who_pays": "retail"}, "min_sample": 10}


RUN = {"id": 1, "user_id": 7, "market": "btc15m", "direction": "volatility"}
PARTITION = {"id": 5, "embargo_seconds": 900, "purge_seconds": 900}


def _run_gate(monkeypatch, store, chunk, decisions):
    monkeypatch.setattr(agent, "_challenge",
                        lambda finalists, run, model, usage, log: decisions[:len(finalists)])
    log = lambda kind, msg, data=None: store.events.append((kind, msg, data))
    ds = SimpleNamespace(summary=lambda: {"market": "btc15m"})
    return agent._gate_and_save(None, RUN, ds, PARTITION, chunk, log,
                                exploration.DefaultPolicy(), model=None, usage=None)


# -- the hand-off --------------------------------------------------------------


def test_approved_finalist_is_preregistered_judged_and_mapped(monkeypatch):
    store = FakeStore(monkeypatch)
    # Two profitable finalists + one losing non-finalist.
    chunk = [_cand("A", 50, 20, 9.0), _cand("B", 40, 15, 8.0), _cand("Loser", -5, 10, -1.0)]
    passed = _run_gate(monkeypatch, store, chunk, [{"decision": "approve", "reason": "", "fixes": None}] * 2)

    assert len(store.preregistered) == 2          # only the two finalists were pre-registered
    assert len(store.judged) == 1                  # one batch judge call
    exp_ids, payloads = store.judged[0]
    assert len(exp_ids) == 2 and all("spec" in p and p["user_id"] == 7 for p in payloads)
    # STAT_SUPPORTED -> "passed"; the non-finalist is rejected and never judged.
    by_title = {s["title"]: s for s in store.strategies}
    assert by_title["A"]["status"] == "passed" and by_title["B"]["status"] == "passed"
    assert by_title["Loser"]["status"] == "rejected"
    assert passed == 2
    # The generator's stored result carries the classification LABEL and research metrics only —
    # never a held-out number.
    for s in store.strategies:
        assert "out_of_sample" not in s["result"]
        assert "classification" in s["result"]


def test_classification_maps_onto_status(monkeypatch):
    store = FakeStore(monkeypatch, judgements=[
        gatekeeper.Classification.STAT_SUPPORTED.value,
        gatekeeper.Classification.INCONCLUSIVE.value,
        gatekeeper.Classification.REJECTED.value,
    ])
    chunk = [_cand("Sup", 50, 20, 9.0), _cand("Inc", 40, 15, 8.0), _cand("Rej", 30, 12, 7.0)]
    _run_gate(monkeypatch, store, chunk, [{"decision": "approve", "reason": "", "fixes": None}] * 3)
    status = {s["title"]: s["status"] for s in store.strategies}
    assert status == {"Sup": "passed", "Inc": "failed", "Rej": "rejected"}


def test_challenger_reject_records_rejected_row_and_never_tests(monkeypatch):
    store = FakeStore(monkeypatch)
    chunk = [_cand("Good", 50, 20, 9.0), _cand("Bad", 40, 15, 8.0)]
    # Approve the top finalist, REJECT the second before any budget is spent.
    decisions = [{"decision": "approve", "reason": "ok", "fixes": None},
                 {"decision": "reject", "reason": "no mechanism, placebo would pass", "fixes": None}]
    _run_gate(monkeypatch, store, chunk, decisions)

    assert len(store.preregistered) == 1           # the REJECTed one was NEVER pre-registered
    assert len(store.judged[0][0]) == 1            # ...nor validation-tested
    bad = next(s for s in store.strategies if s["title"] == "Bad")
    assert bad["status"] == "rejected"             # but it IS recorded, with the reason
    assert "placebo" in (bad["result"].get("challenger_reason") or "")
    assert "out_of_sample" not in bad["result"]


def test_revise_merges_the_spec_fix_before_preregistering(monkeypatch):
    store = FakeStore(monkeypatch)
    chunk = [_cand("Tweak", 50, 20, 9.0)]
    decisions = [{"decision": "revise", "reason": "raise the edge floor",
                  "fixes": {"entry": {"min_edge": 0.2}}}]
    _run_gate(monkeypatch, store, chunk, decisions)
    assert len(store.preregistered) == 1
    assert store.preregistered[0].spec["entry"]["min_edge"] == 0.2  # the patch was applied + frozen


# -- the two structural (leak-closing) guarantees ------------------------------


def test_memory_block_carries_no_held_out_number():
    # Even a legacy result dict that still holds an out_of_sample must not surface its number.
    memory = [{"status": "passed", "title": "Old",
               "result": {"in_sample": {"pnl": 12, "trades": 8},
                          "out_of_sample": {"pnl": 999}}}]
    block = agent._memory_block(memory)
    assert "unseen" not in block and "999" not in block
    assert "12" in block and "Old" in block            # research metrics + title still shown


def test_agent_py_never_touches_validation_or_holdout_datasets():
    import inspect
    src = inspect.getsource(agent)
    # The reviewer's grep: the generator must not import or call the gatekeeper-only loaders.
    assert "validation_dataset" not in src
    assert "holdout_dataset" not in src
