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
        self.holdouts = []              # list of (experiment id, finalist, optional load wrapper)
        self.events = []
        self._judgements = judgements   # list of classification values for judge_batch, or None
        monkeypatch.setattr(agent.repo, "insert_strategy", self._insert)
        monkeypatch.setattr(agent.repo, "set_strategy_outcome", self._set_outcome)
        monkeypatch.setattr(agent.gatekeeper, "preregister", self._preregister)
        monkeypatch.setattr(agent.gatekeeper, "judge_batch", self._judge_batch)
        # §E.5 promotion fires for every STAT_SUPPORTED finalist; stub the one-time holdout +
        # diversification gate (exercised for real in test_gatekeeper / test_holdout_promotion).
        monkeypatch.setattr(agent.gatekeeper, "judge_holdout", self._judge_holdout)
        monkeypatch.setattr(agent.gatekeeper, "marginal_contribution_ok",
                            lambda cur, uid, eid, fin: (True, "stub"))
        monkeypatch.setattr(agent.backtest, "partition_dataset", lambda market, part, phase: None)
        # The research-fold power pre-screen runs for real in test_gatekeeper; here every finalist
        # is powered unless a test names it in `underpowered`.
        self.underpowered = set()
        monkeypatch.setattr(agent.gatekeeper, "validation_power", self._power)

    def _power(self, cur, uid, market, spec, ds, partition, min_sample):
        weak = spec.get("_title") in self.underpowered
        return {"ok": not weak, "power": 0.05 if weak else 0.9,
                "reason": "projected validation power 5% < 20%" if weak else ""}

    def _insert(self, cur, uid, run_id, parent, market, direction, title, thesis, spec, status, result):
        self.strategies.append({"title": title, "status": status, "result": result, "spec": spec})
        return len(self.strategies)

    def _set_outcome(self, cur, strategy_id, status, result, experiment_id=None):
        self.strategies[strategy_id - 1].update(status=status, result=result, experiment_id=experiment_id)

    def _preregister(self, cur, pre):
        self.preregistered.append(pre)
        return len(self.preregistered)

    def _judge_batch(self, cur, run_id, exp_ids, finalists, val_ds):
        self.judged.append((list(exp_ids), list(finalists)))
        cls = self._judgements or [gatekeeper.Classification.STAT_SUPPORTED.value] * len(finalists)
        return [{"classification": cls[i], "n_trades": 30} for i in range(len(finalists))]

    def _judge_holdout(self, cur, eid, fin, run_load=None):
        assert run_load is None or callable(run_load)
        self.holdouts.append((eid, fin, run_load))
        return {"classification": gatekeeper.Classification.FORWARD_VALIDATED.value,
                "n_trades": 30, "holdout_consumed": 0}


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
    assert [eid for eid, _, _ in store.holdouts] == exp_ids
    assert all(fin["user_id"] == 7 and wrapper is None for _, fin, wrapper in store.holdouts)
    # STAT_SUPPORTED -> "passed"; the non-finalist is rejected and never judged.
    by_title = {s["title"]: s for s in store.strategies}
    assert by_title["A"]["status"] == "passed" and by_title["B"]["status"] == "passed"
    assert by_title["Loser"]["status"] == "rejected"
    assert passed == 2
    # Each passed strategy is robustly linked to the experiment it was validated under, so its
    # research-paper page resolves even if a later re-hit re-points app_experiments.strategy_id.
    assert by_title["A"]["experiment_id"] in exp_ids and by_title["B"]["experiment_id"] in exp_ids
    assert by_title["Loser"].get("experiment_id") is None  # rejected non-finalist: never linked
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


# -- cross-contract proposals --------------------------------------------------


def test_proposer_may_emit_a_cross_spec_that_validates():
    # The 9-phase proposer MAY emit a relative-value pair; the hypotheses check validates it.
    check = agent._hypotheses_check("btc_daily", 3)
    out = check({"hypotheses": [{"title": "BTC-ETH basis", "thesis": "one ladder lags the other",
                 "spec": {"market": "btc_daily",
                          "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}}}]})
    assert specmod.is_cross_contract(out[0]["spec"])


def test_prereg_cross_keys_shared_stream_and_records_both_markets():
    spec = specmod.validate({"market": "btc_daily",
                             "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}})
    run = {"user_id": 7, "id": 1, "market": "btc_daily"}
    pre = agent._prereg({"thesis": "basis", "mechanism": {}, "min_sample": 30},
                        spec, run, {"id": 42}, 1, {"reason": "ok"}, 11)
    assert pre.market == "btc_daily+eth_daily"                         # the shared FDR stream
    assert pre.data_provenance["markets"] == ["btc_daily", "eth_daily"]  # both legs in provenance
    assert pre.research_partition_id == 42
    # a single-contract spec is unchanged: stream == its market, provenance names the one market.
    single = agent._prereg({"min_sample": 30}, specmod.validate({"market": "btc15m"}),
                           {"user_id": 7, "id": 1, "market": "btc15m"}, {"id": 5}, 1, {}, 2)
    assert single.market == "btc15m" and single.data_provenance["markets"] == ["btc15m"]


def test_agent_py_never_touches_validation_or_holdout_datasets():
    import inspect
    src = inspect.getsource(agent)
    # The reviewer's grep: the generator must not import or call the gatekeeper-only loaders.
    assert "validation_dataset" not in src
    assert "holdout_dataset" not in src


def test_underpowered_finalist_spends_no_validation_budget(monkeypatch):
    """A finalist whose research-fold edge projects too little validation power is recorded as
    rejected ('underpowered') and is never pre-registered or judged, so it costs no alpha and
    adds no DSR trial."""
    store = FakeStore(monkeypatch)
    a, b = _cand("A", 50, 20, 9.0), _cand("B", 40, 15, 8.0)
    b["spec"] = dict(b["spec"], _title="B")
    store.underpowered = {"B"}
    _run_gate(monkeypatch, store, [a, b], [{"decision": "approve", "reason": "", "fixes": None}] * 2)
    assert len(store.preregistered) == 1 and store.preregistered[0].spec is a["spec"]
    exp_ids, payloads = store.judged[0]
    assert len(payloads) == 1
    by_title = {s["title"]: s for s in store.strategies}
    assert by_title["B"]["status"] == "rejected"
    assert by_title["B"]["result"]["classification"] == "underpowered"
    assert "power" in by_title["B"]["result"]["gate_reason"]
    assert any("NOT TESTED - B" in msg for kind, msg, _ in store.events if kind == "verdict")


def test_research_prompt_states_the_detectable_edge():
    """The proposer is told how big a per-trade edge the gate can confirm on this window, derived
    from the research window length and the gatekeeper's public constants only."""
    ds = SimpleNamespace(start_ts=0, end_ts=18 * 86400)
    block = agent._detectability_block(ds)
    assert "validation window will span ~8 days" in block
    assert block.count("trades/day") == len(agent._DETECT_TRADES_PER_DAY)
    # more trades -> smaller detectable edge
    import re
    mdes = [float(m) for m in re.findall(r"needs >= ([0-9.]+)%", block)]
    assert mdes == sorted(mdes, reverse=True)
    assert agent._detectability_block(SimpleNamespace(start_ts=5, end_ts=5)) == ""


def test_calibration_block_surfaces_planted_longshot_bias():
    """The research-window calibration table counts each contract once per (band, bin) and shows a
    planted mispricing: 5c YES longshots that never settle YES are a positive buy-NO net edge."""
    import random
    from datetime import datetime, timezone
    from app.markets import Contract, Snapshot
    rng = random.Random(0)
    frames, results = [], {}
    for i in range(400):
        close = datetime.fromtimestamp(1_700_000_000 + i * 900 + 900, tz=timezone.utc)
        longshot = i % 2 == 0
        c = Contract("T%d" % i, 100.0, close)
        results[c.ticker] = "no" if longshot else ("yes" if rng.random() < 0.5 else "no")
        ask = 0.05 if longshot else 0.50
        for k in range(15):                       # 15 one-minute frames, one observation
            ts = 1_700_000_000 + i * 900 + k * 60
            frames.append((ts, [Snapshot(c, ts, ask - 0.01, ask, {"tte_min": 15.0 - k})]))
    ds = SimpleNamespace(frames=frames, results=results, start_ts=0, end_ts=1)
    block = agent._calibration_block(ds)
    early = [ln for ln in block.splitlines() if ln.strip().startswith("early ask  0-10c")]
    assert len(early) == 1 and "n= 200" in early[0] and "YES settled 0.00" in early[0]
    assert float(early[0].split("buy-NO net")[1].split()[0].rstrip("c")) > 0
    assert early[0].endswith("LEAD (buy-NO)") and "cell(s) marked LEAD" in block
    assert all(ln.endswith("noise") for ln in block.splitlines() if "ask 40-60c" in ln)  # fair coin
    assert agent._calibration_block(SimpleNamespace(frames=[], results={})) == ""


def test_calibration_block_tells_the_proposer_when_there_is_no_lead():
    """A market priced right (50c contracts settling YES half the time) has no cell that clears 2 SE
    after fees, so the block says so outright instead of inviting another favorite-longshot thesis."""
    from datetime import datetime, timezone
    from app.markets import Contract, Snapshot
    frames, results = [], {}
    for i in range(60):
        close = datetime.fromtimestamp(1_700_000_000 + i * 900 + 900, tz=timezone.utc)
        c = Contract("T%d" % i, 100.0, close)
        results[c.ticker] = "yes" if i % 2 else "no"
        ts = 1_700_000_000 + i * 900
        frames.append((ts, [Snapshot(c, ts, 0.49, 0.50, {"tte_min": 15.0})]))
    block = agent._calibration_block(SimpleNamespace(frames=frames, results=results, start_ts=0, end_ts=1))
    assert "NO cell clears" in block and "favorite-longshot" in block and "LEAD (" not in block


def test_abandoned_theses_are_remembered_and_shown_to_the_next_round():
    """A thesis dropped on the research fold is fed back into every later proposing round (deduped
    by title), so the proposer stops re-proposing the same dead idea under a new name."""
    events, dropped = [], [{"title": "Old idea", "why": "no underlying feed"}]
    agent._abandon(lambda *a: events.append(a), {"title": "FLB recal"}, "loses in every bin", dropped)
    agent._abandon(lambda *a: events.append(a), {"title": "flb recal "}, "again", dropped)
    assert events[0][2]["why"] == "loses in every bin" and events[0][2]["status"] == "abandoned"
    assert [d["title"] for d in dropped] == ["flb recal ", "FLB recal", "Old idea"]
    block = agent._dropped_block(dropped)
    assert block.count("\n- ") == 2 and "Old idea: no underlying feed" in block  # dup title shown once
    assert agent._dropped_block([]) == ""
    run = {"market": "btc15m", "prompt": "x"}
    ds = SimpleNamespace(start_ts=0, end_ts=0, frames=[], results={}, cutoff_ts=0,
                         summary=lambda: {"out_of_sample_from": 0})
    import app.backtest as bt
    orig = bt.feature_coverage
    bt.feature_coverage = lambda ds: {}
    try:
        assert "Old idea" in agent._round_prompt(run, ds, [], 3, [], dropped)
    finally:
        bt.feature_coverage = orig


def test_dropped_theses_reads_new_and_legacy_drop_events():
    """repo.dropped_theses returns recent runs' abandoned theses as {title, why}, from the event's
    data (new rows) or by parsing the message (rows logged before `why` was stored)."""
    from app import repository as repo

    class Cur:
        def __init__(self):
            self.calls = []
        def execute(self, sql, args):
            self.calls.append((sql, args))
        def fetchall(self):
            if len(self.calls) == 1:
                return [{"id": 9}, {"id": 7}]
            return [{"message": 'DROPPED "New" (no candidate) \u2014 x', "data_json": {"title": "New", "why": "w"}},
                    {"message": 'DROPPED "Legacy FLB" (no candidate) \u2014 loses in all bins',
                     "data_json": '{"title":"Legacy FLB","status":"abandoned"}'}]
    cur = Cur()
    out = repo.dropped_theses(cur, 1, "kxcopperd")
    assert out == [{"title": "New", "why": "w"}, {"title": "Legacy FLB", "why": "loses in all bins"}]
    assert cur.calls[1][1] == (9, 7, 20) and "IN (%s,%s)" in cur.calls[1][0]
    assert "LIKE 'DROPPED %%'" in cur.calls[1][0]

    class Empty(Cur):
        def fetchall(self):
            return []
    assert repo.dropped_theses(Empty(), 1, "m") == []


def test_pooled_finalist_preregisters_on_the_merged_partition(monkeypatch):
    """A pooled rule's evidence spans every pooled market: it pre-registers against the MERGED
    partition, is judged on the merged validation window under its shared stream key, and skips the
    single-market power pre-screen (which would only see the run market's research fold)."""
    store = FakeStore(monkeypatch)
    merged_calls, loads = [], []
    monkeypatch.setattr(agent.partitions, "ensure_merged_partition",
                        lambda cur, mk: merged_calls.append(tuple(mk)) or {"id": 77, "embargo_seconds": 900})
    monkeypatch.setattr(agent.partitions, "merged_partitions", lambda cur, mk: [(m, {}) for m in mk])
    monkeypatch.setattr(agent.partitions, "merged_dataset_from", lambda legs, phase: loads.append(phase) or "VAL")
    store.underpowered = {"P"}  # would be screened out if the single-market pre-screen ran
    cand = _cand("P", 50, 20, 9.0)
    cand["spec"] = dict(specmod.validate({"side": "yes", "entry": {"min_edge": 0.1},
                                          "pool": ["eth15m", "sol15m"]}), _title="P")
    _run_gate(monkeypatch, store, [cand], [{"decision": "approve", "reason": "", "fixes": None}])
    assert merged_calls == [("btc15m", "eth15m", "sol15m")]
    assert store.preregistered[0].research_partition_id == 77
    assert store.preregistered[0].market == "btc15m+eth15m+sol15m"
    assert loads == ["validation"] and len(store.judged) == 1


def test_code_window_exposes_quotes_both_at_top_level_and_in_features():
    """Generated code reads the quote either as c["yes_bid"] (documented) or c["features"]["yes_bid"]
    (how rule specs name it); both must see the real quote, never None."""
    from datetime import datetime, timezone
    from app import backtest
    from app.markets import Contract, Snapshot
    c = Contract("T", 100.0, datetime.fromtimestamp(1_700_000_900, tz=timezone.utc))
    snap = Snapshot(c, 1_700_000_000, 0.41, 0.44, {"tte_min": 15.0})
    got = backtest._binary_window("kxcopperd", [(1_700_000_000, [snap])])["frames"][0]["contracts"][0]
    assert got["yes_bid"] == got["features"]["yes_bid"] == 0.41
    assert got["yes_ask"] == got["features"]["yes_ask"] == 0.44
    assert got["features"]["tte_min"] == 15.0 and "yes_bid" not in snap.features  # snapshot untouched
