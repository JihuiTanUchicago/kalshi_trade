"""A session's strategy whose stored status leaves out a later check carries `verdict` and `later_missed`: a
passed one whose one-time locked holdout then failed (the holdout checks its strategy page lists), one the
diversification check after the holdout held back (that check, naming the strategy it repeats), and a probation
one held back after passing on paper. The status stays "passed" (or Void), and the session page said "Passed:
... Open it to deploy it on paper". The whole session is read at once, never one strategy at a time."""
from datetime import datetime

from app.research import gatekeeper
from app.web.routes import research
from app.web.routes import strategies as strategy_routes

FV = gatekeeper.Classification.FORWARD_VALIDATED.value
DC = gatekeeper.Classification.DEPLOYMENT_CANDIDATE.value
REASON = "max |corr| 0.91 to deployed experiment 943 exceeds %.2f" % gatekeeper.CORR_MAX


def _strategy(sid, **o):
    s = {"id": sid, "run_id": 5, "title": "Idea %d" % sid, "status": "passed", "market": "btc15m", "direction": "custom",
         "spec": {"side": "no"}, "result": {"classification": "statistically_supported"}, "experiment_id": 900 + sid}
    s.update(o)
    return s


def _row(phase, cls, **o):
    r = {"phase": phase, "classification": cls, "n_trades": 71, "p_value": 0.03, "mean_net_return": 0.02,
         "ci_lo": 0.002, "ci_hi": 0.04, "verdict_at": datetime(2026, 10, 26, 4)}
    r.update(o)
    return r


MISSED = _row("holdout", "rejected", p_value=0.48, mean_net_return=-0.003, ci_lo=-0.03, ci_hi=0.025)
LATER = {942: [MISSED], 943: [_row("holdout", FV), _row("forward", DC)], 944: [], 945: [MISSED], 947: [_row("holdout", FV)],
         948: [_row("paper", FV)], 949: [_row("paper", "rejected")]}


def _session(monkeypatch, rows, events=None):
    reads = []

    def later_results(cur, eids):
        reads.append(("later", sorted(eids)))
        return {e: {"min_sample": 120, "results": LATER[e]} for e in eids if e in LATER}
    monkeypatch.setattr(strategy_routes.research_repo, "later_results", later_results)
    monkeypatch.setattr(strategy_routes.research_repo, "newest_experiment_ids",
                        lambda cur, uid, sids: reads.append(("legacy", sorted(sids))) or {50: 947})
    monkeypatch.setattr(strategy_routes.research_repo, "strategy_titles",
                        lambda cur, uid, eids: reads.append(("titles", sorted(eids))) or {943: "Idea 43"})
    monkeypatch.setattr(research.repo, "forward_verdicts", lambda cur, run_id: reads.append(("events", run_id)) or dict(events or {}))
    monkeypatch.setattr(research.repo, "chat_lines_like", lambda *a, **k: reads.append(("chat",)) or [])
    return research._later_missed(None, 7, rows), reads


def test_a_failed_holdout_and_a_held_back_pass_are_named_and_a_clean_pass_is_not(monkeypatch):
    rows = [_strategy(42), _strategy(43), _strategy(44), _strategy(45, status="rejected"),
            _strategy(46, direction=research.repo.DEMO_DIRECTION), _strategy(47)]
    ev = {"Idea 47": {"title": "Idea 47", "phase": "forward", "marginal_ok": False, "reason": REASON}}
    out, reads = _session(monkeypatch, rows, ev)
    assert set(out) == {42, 47}
    assert out[42]["verdict"] == "missed_final"
    labels = [line["label"] for line in out[42]["later_missed"]]
    assert "The edge could be luck on the locked holdout" in labels
    assert all("measured" in line and "next" in line for line in out[42]["later_missed"])
    assert out[47]["verdict"] == "held_back"
    assert [(ln["gate"], ln["label"]) for ln in out[47]["later_missed"]] == [("diversification", "Too similar to “Idea 43”")]
    assert "943" not in str(out[47])
    # One read of every listed experiment's later rows (the example is left out), the run's verdict events
    # once, and the repeated strategy's title once; never a read per strategy.
    assert reads == [("later", [942, 943, 944, 945, 947]), ("events", 5), ("titles", [943])]


def test_a_passed_strategy_stored_without_its_experiment_id_is_read_by_the_fallback(monkeypatch):
    rows = [_strategy(50, experiment_id=None), _strategy(51, status="failed", experiment_id=None), _strategy(42)]
    out, reads = _session(monkeypatch, rows)
    assert reads[:2] == [("legacy", [50]), ("later", [942, 947])]
    assert out[50]["verdict"] == "held_back" and out[50]["later_missed"][0]["measured"].startswith("not recorded")
    assert 51 not in out


def test_a_probation_strategy_held_back_after_passing_on_paper_is_named_and_one_that_missed_is_not(monkeypatch):
    rows = [_strategy(48, status="failed"), _strategy(49, status="failed")]
    out, reads = _session(monkeypatch, rows)
    assert set(out) == {48} and out[48]["verdict"] == "held_back"
    assert out[48]["later_missed"][0]["measured"].startswith("not recorded, but it passed its one judgment on paper")
    assert ("chat",) in reads and not any(r[0] == "events" for r in reads)


def test_an_unreadable_record_never_fails_the_page(monkeypatch):
    LATER[960] = [_row("holdout", "rejected", n_trades="x", p_value="y")]
    try:
        out, _ = _session(monkeypatch, [_strategy(60)])
    finally:
        del LATER[960]
    assert out == {}
