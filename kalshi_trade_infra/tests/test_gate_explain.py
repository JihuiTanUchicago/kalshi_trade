"""services.gate_explain: one plain line per failed research gate (measured, needed, what to try).

Every known gate has a case; an unknown gate reads as its humanised name with its numbers. The
lines must agree with the gatekeeper's own decision rule, so a property test drives
gatekeeper._classify over many combinations and checks that a non-passing verdict always names at
least one gate it really failed, and a passing one names none.
"""
import itertools
import re
from types import SimpleNamespace

import pytest

from app import backtest, gatekeeper, server
from app.services import gate_explain as ge

KEYS = {"gate", "label", "measured", "needed", "next"}
NB = " "


def _plain(lines):
    """Every line has all five fields, filled, with no raw code (no underscores, no '=') in the words."""
    for ln in lines:
        assert set(ln) == KEYS
        for k in ("label", "measured", "needed", "next"):
            assert ln[k] and isinstance(ln[k], str), (k, ln)
        for k in ("label", "needed", "next"):
            assert "_" not in ln[k] and "=" not in ln[k], (k, ln[k])
        assert ln["next"][0].isupper() and ln["next"].endswith("."), ln["next"]
    return lines


def _one(lines):
    assert len(_plain(lines)) == 1, lines
    return lines[0]


# -- the gatekeeper's statistical gates --------------------------------------------------------------

def test_too_few_trades_says_how_many_more_and_where_to_get_them():
    ln = _one(ge.stat_checks({"n_trades": 18, "p_value": None}, min_sample=30, classification="inconclusive"))
    assert ln["gate"] == "sample_size" and ln["label"] == "Enough trades to judge"
    assert ln["measured"] == "18%strades on the unseen test window" % NB
    assert ln["needed"] == "at least 30%strades (fixed before the test)" % NB
    assert ln["next"].startswith("Needs about 12 more trades: widen the market set or lengthen the test window")
    # One more trade short reads in the singular; an older record without its minimum still explains itself.
    assert _one(ge.stat_checks({"n_trades": 29}, min_sample=30))["next"].startswith("Needs about 1 more trade:")
    assert _one(ge.stat_checks({"n_trades": 4}))["needed"] == "the minimum fixed before the test"
    assert ge.stat_checks({"n_trades": 40, "p_value": None}, min_sample=30) == []  # nothing failed that it can name


FAILING = {"n_trades": 80, "p_value": 0.18, "fdr_alpha_i": 0.05, "fdr_reject": False, "bh_reject": None,
           "dsr": 0.31, "ci_lo": -0.012, "ci_hi": 0.003, "mean_net_return": -0.004, "placebo_p": 0.42,
           "n_trials_audited": 48}


def test_each_failed_statistical_gate_gets_its_own_line_with_its_numbers():
    folds = [{"net_return": 0.1}, {"net_return": -0.1}, {"net_return": -0.1}, {"net_return": -0.2}]
    lines = {ln["gate"]: ln for ln in _plain(ge.stat_checks(FAILING, classification="inconclusive", folds=folds))}
    assert list(lines) == ["significance", "net_edge", "deflated_sharpe", "placebo", "cross_day"]
    assert lines["significance"]["label"] == "Edge is not luck"
    assert lines["significance"]["measured"].startswith("p-value 0.18: a rule with no edge would do this well about 18% of the time")
    assert lines["significance"]["needed"] == "0.05 or lower"
    assert lines["net_edge"]["measured"] == "−0.40%%%sof the stake per trade after fees (90%% range −1.20%% to +0.30%%)" % NB
    assert lines["net_edge"]["needed"] == "the whole 90% range above 0%"
    assert "bigger mispricing" in lines["net_edge"]["next"]  # losing money: a bigger edge, not just more trades
    assert lines["deflated_sharpe"]["measured"] == "deflated Sharpe 0.31 with 48 ideas tried on this data"
    assert lines["deflated_sharpe"]["needed"] == "%.2f or higher" % gatekeeper.DSR_MIN
    assert lines["placebo"]["measured"].startswith("placebo p-value 0.42")
    assert lines["placebo"]["needed"] == "below 0.10"
    assert lines["cross_day"]["measured"] == "1 of 4 time slices profitable"


def test_a_positive_but_noisy_edge_is_told_to_get_more_trades():
    v = dict(FAILING, p_value=0.01, dsr=0.9, placebo_p=0.01, mean_net_return=0.004, ci_lo=-0.001, ci_hi=0.01,
             cross_day_ok=True, cost_stress_ok=True)
    ln = _one(ge.stat_checks(v, classification="inconclusive"))
    assert ln["gate"] == "net_edge" and "positive but too noisy" in ln["next"]


def test_ideas_judged_together_cross_day_concentration_and_cost_stress():
    v = {"n_trades": 80, "p_value": 0.01, "alpha_i": 0.05, "fdr_reject": True, "bh_reject": False, "dsr": 0.9,
         "ci": {"lo": 0.001, "hi": 0.02}, "mean_net_return": 0.01, "placebo_p": 0.01, "cross_day_ok": False,
         "cross_day_max_day_share": 0.96, "folds_n": 4, "folds_positive": 3, "cost_stress_ok": False,
         "cost_stress_mean": -0.002}
    lines = {ln["gate"]: ln for ln in _plain(ge.stat_checks(v, classification="inconclusive", n_tested=4))}
    assert list(lines) == ["multiple_testing", "cross_day", "cost_stress"]
    assert lines["multiple_testing"]["measured"] == "p-value 0.01, one of 4 ideas judged together"
    assert "10% false-discovery rate" in lines["multiple_testing"]["needed"]
    assert lines["cross_day"]["measured"] == "one day carrying 96% of the gains"
    assert "no single day over 90% of the gains" in lines["cross_day"]["needed"]
    assert lines["cost_stress"]["label"] == "Survives 1¢ worse fills"
    assert lines["cost_stress"]["measured"] == "−0.20%%%sof the stake per trade with 1¢ worse fills" % NB
    assert lines["cost_stress"]["needed"] == "above 0%"
    too_few = _one(ge.stat_checks(dict(v, bh_reject=True, folds_n=2, folds_positive=2, cost_stress_ok=True),
                                  classification="inconclusive"))
    assert too_few["measured"] == "too few trades for 3 time slices"
    no_trades_left = _one(ge.stat_checks(dict(v, bh_reject=True, cross_day_ok=True, cost_stress_mean=None),
                                         classification="inconclusive"))
    assert no_trades_left["measured"] == "no trades left with 1¢ worse fills"


def test_a_check_the_ledger_does_not_keep_is_named_without_guessing():
    # The strategy page's ledger row keeps neither the cross-day nor the cost-stress result: when every
    # stored check passed, the line says one of those two failed, and names it when the other is known.
    ok = {"n_trades": 80, "p_value": 0.01, "fdr_alpha_i": 0.05, "dsr": 0.9, "ci_lo": 0.001, "ci_hi": 0.02,
          "mean_net_return": 0.01, "placebo_p": 0.01}
    both = _one(ge.stat_checks(ok, classification="inconclusive"))
    assert both["gate"] == "cross_day_or_cost" and both["measured"] == "not recorded, but every other check passed, so one of these two failed"
    assert _one(ge.stat_checks(dict(ok, cross_day_ok=True), classification="inconclusive"))["gate"] == "cost_stress"
    assert _one(ge.stat_checks(dict(ok, cost_stress_ok=True), classification="inconclusive"))["gate"] == "cross_day"
    assert ge.stat_checks(ok, classification="statistically_supported") == []
    assert ge.stat_checks(ok) == []  # no verdict recorded: nothing to explain


def test_the_locked_holdout_uses_its_own_level_and_wording():
    v = {"n_trades": 40, "p_value": 0.3, "ci_lo": -0.01, "ci_hi": 0.02, "mean_net_return": 0.004, "dsr": 0.01, "placebo_p": 0.9}
    lines = _plain(ge.stat_checks(v, "holdout", min_sample=30, classification="rejected"))
    assert [ln["gate"] for ln in lines] == ["significance", "net_edge"]  # DSR and the placebo don't gate a holdout
    assert lines[0]["label"] == "Edge is not luck on the locked holdout" and lines[0]["needed"] == "0.10 or lower"
    assert "did not repeat on fresh data" in lines[0]["next"]
    # Only a perpetual holdout is judged on its sample (it reads INCONCLUSIVE then).
    short = ge.stat_checks(dict(v, n_trades=12, p_value=0.01, ci_lo=0.001, cost_stress_ok=True), "holdout", 30, "inconclusive")
    assert [ln["gate"] for ln in short] == ["sample_size"] and "the locked holdout" in short[0]["measured"]
    assert ge.stat_checks(dict(v, p_value=0.01, ci_lo=0.001), "holdout", 30, "forward_validated") == []


def test_an_old_event_without_its_level_is_judged_against_the_fixed_validation_level(monkeypatch):
    ln = _one(ge.stat_checks({"n_trades": 50, "p_value": 0.2, "ci": {"lo": 0.001, "hi": 0.02}, "dsr": 0.9,
                              "placebo_p": 0.01, "cross_day_ok": True, "cost_stress_ok": True}, classification="inconclusive"))
    assert ln["gate"] == "significance" and ln["needed"] == "%s or lower" % ge._p(gatekeeper.VALIDATION_ALPHA)
    monkeypatch.setattr(gatekeeper, "VALIDATION_ALPHA", 0.0)  # LORD++ as the gate: an unrecorded level stays unknown
    assert ge.stat_checks({"n_trades": 50, "p_value": 0.2, "ci": {"lo": 0.001}, "dsr": 0.9, "placebo_p": 0.01,
                           "cross_day_ok": True, "cost_stress_ok": True}, classification="inconclusive") == []


@pytest.mark.parametrize("combo", list(itertools.product(
    [True, False],              # p-value clears the level
    [None, True, False],        # Benjamini-Hochberg within the batch
    [True, False],              # DSR clears its floor
    [True, False],              # CI low end above zero
    [True, False],              # placebo
    [True, False],              # cross-day
    [True, False],              # cost stress
)))
def test_the_lines_agree_with_the_gatekeepers_decision_rule(combo):
    sig, bh, dsr_ok, ci_ok, placebo_ok, cross_ok, cost_ok = combo
    level = 0.05
    stats = {"n_trades": 120, "p_value": 0.01 if sig else 0.2, "alpha_i": level, "fdr_reject": sig, "bh_reject": bh,
             "dsr": 0.9 if dsr_ok else 0.2, "ci": {"lo": 0.002 if ci_ok else -0.002, "hi": 0.02},
             "mean_net_return": 0.01, "placebo_p": 0.01 if placebo_ok else 0.5, "cross_day_ok": cross_ok,
             "cross_day_max_day_share": 0.5 if cross_ok else 0.95, "folds_n": 4, "folds_positive": 3,
             "cost_stress_ok": cost_ok, "cost_stress_mean": 0.004 if cost_ok else -0.001, "min_sample": 30}
    cls = gatekeeper._classify(sig, bh, stats["dsr"], stats["ci"]["lo"], stats["ci"]["hi"], placebo_ok, cross_ok, cost_ok).value
    lines = _plain(ge.for_event("X - T: validation verdict", {"title": "T", "status": "failed", "classification": cls, "stats": stats}))
    failed = {"significance": not sig, "multiple_testing": sig and bh is False, "deflated_sharpe": not dsr_ok,
              "net_edge": not ci_ok, "placebo": not placebo_ok, "cross_day": not cross_ok, "cost_stress": not cost_ok}
    if cls == gatekeeper.Classification.STAT_SUPPORTED.value:
        assert lines == []
    else:
        assert lines and {ln["gate"] for ln in lines} == {g for g, f in failed.items() if f}


# -- gates before the statistical test ----------------------------------------------------------------

def test_every_pre_screen_reason_reads_as_measured_and_needed():
    # The reasons exactly as gatekeeper.validation_power writes them.
    cases = {
        "only %d research-fold trades (need %d) to project validation power" % (8, gatekeeper.POWER_MIN_RESEARCH_TRADES):
            ("research_trades", "8%strades on the research data" % NB, "at least 10%strades" % NB),
        "research-fold mean net return %.4f is not positive" % -0.0012:
            ("research_edge", "−0.12%" + NB + "of the stake per trade", "above 0%"),
        "validation window is expected to hold ~%.0f trades, below the pre-registered min_sample %d" % (14.2, 30):
            ("expected_trades", "about 14%strades expected" % NB, "at least 30%strades (fixed before the test)" % NB),
        ("projected validation power %.0f%% < %.0f%%: a research-fold edge of %.2f%%/trade over ~%.0f validation trades "
         "is unlikely to clear the next alpha %.1e" % (12.0, 100 * gatekeeper.POWER_MIN, 0.4, 35.0, 0.05)):
            ("test_power", "about a 12% chance to pass (an edge of +0.40%~of the stake per trade over about 35~trades)".replace("~", NB),
             "at least a 20% chance"),
    }
    for reason, (gate, measured, needed) in cases.items():
        ln = _one(ge.prescreen(reason))
        assert (ln["gate"], ln["measured"], ln["needed"]) == (gate, measured, needed), reason
    assert _one(ge.prescreen(cases and list(cases)[0]))["next"].startswith("Needs about 2 more trades: loosen the entry rule")
    assert ge.prescreen("no validation window to project onto") == [] and ge.prescreen(None) == []
    other = _one(ge.prescreen("a reason a later version adds"))
    assert other["label"] == "Worth spending a test on" and other["measured"] == "a reason a later version adds"


def test_challenger_finalist_and_diversification():
    ln = _one(ge.challenger("No one is on the other side; this is a public feed."))
    assert ln["measured"] == "an objection before testing: No one is on the other side; this is a public feed"
    assert _one(ge.challenger(None))["measured"] == "an objection before testing: no credible reason the edge exists"
    few = _one(ge.not_finalist({"pnl": 1.5, "trades": 3}))
    assert few["gate"] == "research_trades" and few["needed"] == "at least 5%strades" % NB
    lost = _one(ge.not_finalist({"pnl": -1.5, "trades": 30}))
    assert lost["gate"] == "research_pnl" and lost["measured"] == "−$1.50 over 30%strades" % NB and lost["needed"] == "above $0"
    ranked = _one(ge.not_finalist({"pnl": 2.5, "trades": 30}))
    assert ranked["gate"] == "finalist" and ranked["measured"] == "$2.50 over 30%strades on the research data" % NB
    div = _one(ge.diversification("max |corr| %.2f to deployed experiment %s exceeds %.2f" % (0.91, 12, gatekeeper.CORR_MAX)))
    assert div["measured"] == "a 0.91 correlation of daily results with a strategy you already run" and div["needed"] == "0.80 or less"


# -- the backtest's own gates, and an unknown gate -------------------------------------------------------

def test_every_backtest_gate_and_an_unknown_one():
    ins = {"pnl": -1.2, "trades": 30}
    oos = {"pnl": -3.4, "trades": 4, "profit_factor": 0.82, "max_drawdown": 31.0}
    gates = backtest.gates(ins, oos, 50.0)
    assert not any(g["ok"] for g in gates)
    gates += [{"name": "Has a real edge, not a coin flip", "value": "coin flip", "threshold": "an actual signal", "ok": False},
              {"name": "min_sharpe_ratio", "value": 0.4, "threshold": ">= 0.5", "ok": False},
              {"name": "Makes money on unseen data", "value": 2.0, "threshold": "> $0", "ok": True}]
    lines = _plain(ge.backtest_gates(gates))
    got = [(ln["gate"], ln["measured"], ln["needed"]) for ln in lines]
    assert got == [
        ("in_sample_pnl", "−$1.20", "above $0"),
        ("unseen_pnl", "−$3.40", "above $0"),
        ("unseen_trades", "4%strades on unseen data" % NB, "at least 10%strades" % NB),
        ("profit_factor", "wins 0.82%sthe losses" % ("×" + NB), "at least 1.1%sthe losses" % ("×" + NB)),
        ("drawdown", "$31.00 at the worst point", "$25 or less"),
        ("real_edge", "coin flip", "an actual signal"),
        ("other", "0.4", "at least 0.5"),
    ]
    assert lines[2]["next"].startswith("Needs about 6 more trades")
    assert lines[-1]["label"] == "Min sharpe ratio"  # never the raw code
    assert _one(ge.backtest_gates([{"name": "Wins outweigh losses on unseen data", "value": None, "threshold": "≥ 1.1", "ok": False}]))["measured"] == "no winning trades"
    assert ge.humanise("max_book__fraction") == "Max book fraction" and ge.humanise(None) == "Unnamed check"
    odd = ge.unknown("some-new_gate", True)
    assert odd["label"] == "Some new gate" and odd["measured"] == "yes" and odd["needed"] == "the gate's threshold"


# -- a strategy page and a run's verdict events ------------------------------------------------------------

def test_a_strategy_explains_the_stage_it_stopped_at():
    assert _one(ge.for_strategy("rejected", {"classification": "underpowered",
                                             "gate_reason": "only 3 research-fold trades (need 10) to project validation power"}))["gate"] == "research_trades"
    assert _one(ge.for_strategy("rejected", {"classification": "challenger_rejected", "challenger_reason": "No mechanism."}))["gate"] == "challenger"
    assert _one(ge.for_strategy("rejected", {"classification": "not_finalist", "in_sample": {"pnl": -2, "trades": 9}}))["gate"] == "research_pnl"
    exp = {"min_sample": 30, "planned_n_tests": 3, "validation": {"classification": "inconclusive", "n_trades": 12, "p_value": None},
           "holdout": None, "folds": []}
    assert _one(ge.for_strategy("failed", {"classification": "inconclusive"}, exp))["measured"].startswith("12")
    # A validation pass keeps "passed" when its one-time holdout then fails: that failure is shown.
    held = {"min_sample": 30, "validation": {"classification": "statistically_supported", "p_value": 0.01},
            "holdout": {"classification": "rejected", "n_trades": 40, "p_value": 0.4, "ci_lo": -0.01, "ci_hi": 0.01, "mean_net_return": 0.0}}
    assert [ln["gate"] for ln in ge.for_strategy("passed", {}, held)] == ["significance", "net_edge"]
    assert ge.for_strategy("passed", {}, dict(held, holdout=None)) == []
    # Pre-pipeline rows: the backtest's gates, else the finalist rule from the research numbers.
    legacy = {"gates": [{"name": "Makes money on unseen data", "value": -1, "threshold": "> $0", "ok": False}]}
    assert _one(ge.for_strategy("failed", legacy))["gate"] == "unseen_pnl"
    assert _one(ge.for_strategy("rejected", {"in_sample": {"pnl": 1, "trades": 2}}))["gate"] == "research_trades"
    assert ge.for_strategy("failed", {}) == [] and ge.for_strategy(None, None) == []


def test_each_kind_of_verdict_event_is_explained_from_its_data_or_its_old_message():
    v = lambda msg, **d: ge.for_event(msg, {"title": "Fade", **d})
    assert v("PASSED - Fade: validation verdict is gatekeeper-held", status="passed", stats=FAILING) == []
    under = v("FAILED - Fade: validation verdict is gatekeeper-held (classification=inconclusive, 9 trades)",
              status="failed", classification="inconclusive", stats={"n_trades": 9, "p_value": None, "min_sample": 30})
    assert _one(under)["measured"] == "9%strades on the unseen test window" % NB
    reason = "validation window is expected to hold ~4 trades, below the pre-registered min_sample 30"
    assert _one(v("NOT TESTED - Fade: %s. No validation budget spent." % reason, status="rejected"))["gate"] == "expected_trades"
    assert _one(v("NOT TESTED - Fade: x. No validation budget spent.", status="rejected", reason=reason))["gate"] == "expected_trades"
    assert _one(v("REJECTED (challenger) - Fade: no one pays", status="rejected"))["measured"] == "an objection before testing: no one pays"
    assert _one(v("REJECTED - Fade: not a finalist, so never tested on unseen data (research pnl $-0.5 over 12 trades).",
                  status="rejected"))["gate"] == "research_pnl"
    assert _one(v("REJECTED - Fade: not a finalist, so never tested on unseen data (research pnl $None over None trades).",
                  status="rejected", in_sample={"pnl": 3.0, "trades": 2}))["gate"] == "research_trades"
    hold = v("Fade: one-time holdout verdict is gatekeeper-held (classification=rejected, 40 trades)", phase="holdout",
             classification="rejected", stats={"n_trades": 40, "p_value": 0.05, "ci": {"lo": 0.001, "hi": 0.01},
                                                "mean_net_return": 0.004, "cost_stress_ok": False, "cost_stress_mean": -0.001})
    assert [ln["gate"] for ln in hold] == ["cost_stress"] and hold[0]["label"] == "Survives 1¢ worse fills on the locked holdout"
    assert v("Fade: the one-time holdout was not evaluated (consumed).", phase="holdout", skipped=True) == []
    div = v("Fade: diversification gate blocked (stays forward-validated, not deployable) — max |corr| 0.93 to deployed "
            "experiment 4 exceeds 0.80.", phase="forward", marginal_ok=False, classification="forward_validated")
    assert _one(div)["measured"].startswith("a 0.93 correlation")
    assert v("Fade: diversification gate PASSED", phase="forward", marginal_ok=True) == []
    assert ge.for_event(None, None) == []


# -- the server attaches them, with no extra read --------------------------------------------------------

def _ctx(params=()):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()), {"id": 7, "autopilot": 0}, params, {}, {}, SimpleNamespace())


def test_the_run_page_gives_each_verdict_event_its_lines(monkeypatch):
    run = {"id": 9, "kind": "research", "status": "succeeded", "created_at": None, "heartbeat_at": None, "finished_at": None}
    events = [{"id": 1, "kind": "step", "message": "Froze 2 finalists", "data": None},
              {"id": 2, "kind": "verdict", "message": "FAILED - Fade: validation verdict is gatekeeper-held", "data": {
                  "title": "Fade", "status": "failed", "classification": "inconclusive", "stats": {"n_trades": 9, "p_value": None, "min_sample": 30}}},
              {"id": 3, "kind": "verdict", "message": "PASSED - Lean: validation verdict", "data": {"title": "Lean", "status": "passed", "stats": {}}},
              {"id": 4, "kind": "verdict", "message": "REJECTED - Old: an old line", "data": None}]
    monkeypatch.setattr(server.repo, "get_run", lambda cur, uid, rid: dict(run))
    monkeypatch.setattr(server.repo, "runs_spent", lambda *a: {})
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "get_policy", lambda *a: None)
    monkeypatch.setattr(server.repo, "latest_dream_event", lambda *a: None)
    monkeypatch.setattr(server.repo, "run_events", lambda *a: [dict(e) for e in events])
    out = server.get_run(_ctx(("9",)))["events"]
    assert "why_failed" not in (out[0]["data"] or {})
    assert [ln["gate"] for ln in out[1]["data"]["why_failed"]] == ["sample_size"]
    assert out[2]["data"]["why_failed"] == [] and out[3]["data"]["why_failed"] == []


def test_the_strategy_page_lists_what_it_missed_and_a_bad_record_never_fails_it(monkeypatch):
    row = {"id": 4, "run_id": 1, "parent_id": None, "market": "btc15m", "title": "Fade", "thesis": "t", "status": "failed",
           "created_at": None, "result": {"classification": "inconclusive"}, "spec": {"sizing": {"stake": 5}, "side": "yes"},
           "experiment_id": 3, "direction": "momentum"}
    exp = {"min_sample": 30, "validation": {"classification": "inconclusive", "n_trades": 11, "p_value": None}, "holdout": None, "folds": []}
    monkeypatch.setattr(server.specmod, "describe", lambda spec: [])
    monkeypatch.setattr(server, "_experiment_block", lambda *a: exp)
    monkeypatch.setattr(server.repo, "list_deployments_for_display", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "positions_for_strategy", lambda *a: [])
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: dict(row))
    monkeypatch.setattr(server, "_demo_health", lambda *a, **k: None)
    why =server.get_strategy(_ctx(("4",)))["why_failed"]
    assert [ln["gate"] for ln in why] == ["sample_size"] and re.match(r"Needs about 19 more trades", why[0]["next"])
    monkeypatch.setattr(server, "_experiment_block", lambda *a: {"validation": "not a row", "min_sample": 30})
    assert server.get_strategy(_ctx(("4",)))["why_failed"] == []
