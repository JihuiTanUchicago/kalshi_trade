"""services.gate_explain: one plain line per failed research gate (measured, needed, what to try).

Every known gate has a case; an unknown gate reads as its humanised name with its numbers. Each
line's label says what fell short (it sits under a REJECTED/VOID stamp), never the check's goal,
which `check` keeps. The
lines must agree with the gatekeeper's own decision rule, so a property test drives
gatekeeper._classify over many combinations and checks that a non-passing verdict always names at
least one gate it really failed, and a passing one names none.
"""
import itertools
import re
from types import SimpleNamespace

import pytest

from app import backtest, server
from app.research import gatekeeper
from app.services import gate_explain as ge

KEYS = {"gate", "check", "label", "measured", "needed", "next"}

# A label names the miss. These are the openings a failed check's label may use; a goal-shaped label
# ("Passed the skeptic's review", "Enough trades to judge") would read as praise under a failure.
MISS = ("Too few ", "Too similar ", "Didn't ", "Doesn't ", "Not ", "No real edge", "Lost ", "Loses ", "Unlikely ",
        "The edge could be luck", "The skeptic's review didn't", "Wins no ", "Wins don't ", "Made money on too few",
        "Nearly all the gains", "Profit after fees is too uncertain", "Drawdown on unseen data was too deep")
NB = " "


def _plain(lines):
    """Every line has all its fields, filled, with no raw code (no underscores, no '=') in the words,
    and a label that says what fell short rather than restating the check."""
    for ln in lines:
        assert set(ln) == KEYS
        for k in ("check", "label", "measured", "needed", "next"):
            assert ln[k] and isinstance(ln[k], str), (k, ln)
        assert ln["label"] != ln["check"] and ln["label"].startswith(MISS), ln["label"]
        for k in ("check", "label", "needed", "next"):
            assert "_" not in ln[k] and "=" not in ln[k], (k, ln[k])
        assert ln["next"][0].isupper() and ln["next"].endswith("."), ln["next"]
    return lines


def _one(lines):
    assert len(_plain(lines)) == 1, lines
    return lines[0]


# -- the gatekeeper's statistical gates --------------------------------------------------------------

def test_too_few_trades_says_how_many_more_and_where_to_get_them():
    ln = _one(ge.stat_checks({"n_trades": 18, "p_value": None}, min_sample=30, classification="inconclusive"))
    assert ln["gate"] == "sample_size" and ln["label"] == "Too few trades to judge (18 of 30)"
    assert ln["check"] == "Enough trades to judge"
    assert ln["measured"] == "18%strades on the unseen test window" % NB
    assert ln["needed"] == "at least 30%strades (fixed before the test)" % NB
    assert ln["next"].startswith("Needs about 12 more trades: widen the market set or lengthen the test window")
    # One more trade short reads in the singular; an older record without its minimum still explains itself.
    assert _one(ge.stat_checks({"n_trades": 29}, min_sample=30))["next"].startswith("Needs about 1 more trade:")
    old = _one(ge.stat_checks({"n_trades": 4}))
    assert old["needed"] == "the minimum fixed before the test" and old["label"] == "Too few trades to judge"  # no invented minimum
    assert ge.stat_checks({"n_trades": 40, "p_value": None}, min_sample=30) == []  # nothing failed that it can name


FAILING = {"n_trades": 80, "p_value": 0.18, "fdr_alpha_i": 0.05, "fdr_reject": False, "bh_reject": None,
           "dsr": 0.31, "ci_lo": -0.012, "ci_hi": 0.003, "mean_net_return": -0.004, "placebo_p": 0.42,
           "n_trials_audited": 48}


def test_each_failed_statistical_gate_gets_its_own_line_with_its_numbers():
    folds = [{"net_return": 0.1}, {"net_return": -0.1}, {"net_return": -0.1}, {"net_return": -0.2}]
    lines = {ln["gate"]: ln for ln in _plain(ge.stat_checks(FAILING, classification="inconclusive", folds=folds))}
    assert list(lines) == ["significance", "net_edge", "deflated_sharpe", "placebo", "cross_day"]
    assert lines["significance"]["label"] == "The edge could be luck" and lines["significance"]["check"] == "Edge is not luck"
    assert lines["net_edge"]["label"] == "Loses money after fees"
    assert lines["deflated_sharpe"]["label"] == "Doesn't beat the luck of trying many ideas"
    assert lines["placebo"]["label"] == "Wins no more often than its prices imply"
    assert lines["cross_day"]["label"] == "Made money on too few stretches of days (1 of 4)"
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
    assert ln["label"] == "Profit after fees is too uncertain"


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
    assert lines["multiple_testing"]["label"] == "Didn't stand out among the ideas tested with it"
    assert lines["cross_day"]["label"] == "Nearly all the gains came from one day"
    assert lines["cost_stress"]["label"] == "Loses its edge with 1¢ worse fills"
    assert lines["cost_stress"]["measured"] == "−0.20%%%sof the stake per trade with 1¢ worse fills" % NB
    assert lines["cost_stress"]["needed"] == "above 0%"
    too_few = _one(ge.stat_checks(dict(v, bh_reject=True, folds_n=2, folds_positive=2, cost_stress_ok=True),
                                  classification="inconclusive"))
    assert too_few["measured"] == "too few trades for 3 time slices"
    assert too_few["label"] == "Too few trades to check several stretches of days"
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
    assert both["label"] == "Didn't hold up on several stretches of days, or with 1¢ worse fills"
    assert _one(ge.stat_checks(dict(ok, cross_day_ok=True), classification="inconclusive"))["gate"] == "cost_stress"
    assert _one(ge.stat_checks(dict(ok, cost_stress_ok=True), classification="inconclusive"))["gate"] == "cross_day"
    assert ge.stat_checks(ok, classification="statistically_supported") == []
    assert ge.stat_checks(ok) == []  # no verdict recorded: nothing to explain


def test_the_locked_holdout_uses_its_own_level_and_wording():
    v = {"n_trades": 40, "p_value": 0.3, "ci_lo": -0.01, "ci_hi": 0.02, "mean_net_return": 0.004, "dsr": 0.01, "placebo_p": 0.9}
    lines = _plain(ge.stat_checks(v, "holdout", min_sample=30, classification="rejected"))
    assert [ln["gate"] for ln in lines] == ["significance", "net_edge"]  # DSR and the placebo don't gate a holdout
    assert lines[0]["label"] == "The edge could be luck on the locked holdout" and lines[0]["needed"] == "0.10 or lower"
    assert lines[1]["label"] == "Profit after fees is too uncertain on the locked holdout"
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
            ("research_trades", "8%strades on the research data" % NB, "at least 10%strades" % NB,
             "Too few research trades to plan the test (8 of 10)"),
        "research-fold mean net return %.4f is not positive" % -0.0012:
            ("research_edge", "−0.12%" + NB + "of the stake per trade", "above 0%",
             "Doesn't make money after fees and 1¢ worse fills on the research data"),
        "validation window is expected to hold ~%.0f trades, below the pre-registered min_sample %d" % (14.2, 30):
            ("expected_trades", "about 14%strades expected" % NB, "at least 30%strades (fixed before the test)" % NB,
             "Too few trades expected in the unseen test window (about 14 of 30)"),
        ("projected validation power %.0f%% < %.0f%%: a research-fold edge of %.2f%%/trade over ~%.0f validation trades "
         "is unlikely to clear the next alpha %.1e" % (12.0, 100 * gatekeeper.POWER_MIN, 0.4, 35.0, 0.05)):
            ("test_power", "about a 12% chance to pass (an edge of +0.40%~of the stake per trade over about 35~trades)".replace("~", NB),
             "at least a 20% chance", "Unlikely to prove itself on unseen data (about a 12% chance)"),
    }
    for reason, (gate, measured, needed, label) in cases.items():
        ln = _one(ge.prescreen(reason))
        assert (ln["gate"], ln["measured"], ln["needed"], ln["label"]) == (gate, measured, needed, label), reason
    assert _one(ge.prescreen(cases and list(cases)[0]))["next"].startswith("Needs about 2 more trades: loosen the entry rule")
    assert ge.prescreen("no validation window to project onto") == [] and ge.prescreen(None) == []
    other = _one(ge.prescreen("a reason a later version adds"))
    assert other["label"] == "Not yet worth spending a test on" and other["measured"] == "a reason a later version adds"


def test_challenger_finalist_and_diversification():
    ln = _one(ge.challenger("No one is on the other side; this is a public feed."))
    # Under a REJECTED stamp the line says the review turned it down, not "Passed the skeptic's review".
    assert ln["label"] == "The skeptic's review didn't pass it" and ln["check"] == "Passed the skeptic's review"
    assert ln["measured"] == "an objection before testing: No one is on the other side; this is a public feed"
    assert _one(ge.challenger(None))["measured"] == "an objection before testing: no credible reason the edge exists"
    few = _one(ge.not_finalist({"pnl": 1.5, "trades": 3}))
    assert few["gate"] == "research_trades" and few["needed"] == "at least 5%strades" % NB
    assert few["label"] == "Too few research trades to be a finalist (3 of 5)"
    lost = _one(ge.not_finalist({"pnl": -1.5, "trades": 30}))
    assert lost["gate"] == "research_pnl" and lost["measured"] == "−$1.50 over 30%strades" % NB and lost["needed"] == "above $0"
    assert lost["label"] == "Lost money on the research data"
    ranked = _one(ge.not_finalist({"pnl": 2.5, "trades": 30}))
    assert ranked["gate"] == "finalist" and ranked["measured"] == "$2.50 over 30%strades on the research data" % NB
    assert ranked["label"] == "Not among the round's strongest ideas"
    div = _one(ge.diversification("max |corr| %.2f to deployed experiment %s exceeds %.2f" % (0.91, 12, gatekeeper.CORR_MAX)))
    assert div["measured"] == "a 0.91 correlation of daily results with a strategy you already run" and div["needed"] == "0.80 or less"
    assert div["label"] == "Too similar to a strategy you already run"


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
    assert [ln["label"] for ln in lines] == [
        "Didn't make money on the data it was built on",
        "Didn't make money on unseen data",
        "Too few trades on unseen data (4 of 10)",
        "Wins don't outweigh losses by enough on unseen data",
        "Drawdown on unseen data was too deep",
        "No real edge: it looks like a coin flip",
        "Didn't pass: Min sharpe ratio",  # never the raw code
    ]
    assert lines[2]["next"].startswith("Needs about 6 more trades")
    assert lines[2]["check"] == "Enough unseen trades to judge" and lines[-1]["check"] == "Min sharpe ratio"
    assert _one(ge.backtest_gates([{"name": "Wins outweigh losses on unseen data", "value": None, "threshold": "≥ 1.1", "ok": False}]))["measured"] == "no winning trades"
    assert ge.humanise("max_book__fraction") == "Max book fraction" and ge.humanise(None) == "Unnamed check"
    odd = ge.unknown("some-new_gate", True)
    assert odd["label"] == "Didn't pass: Some new gate" and odd["measured"] == "yes" and odd["needed"] == "the gate's threshold"


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
    assert [ln["gate"] for ln in hold] == ["cost_stress"] and hold[0]["label"] == "Loses its edge with 1¢ worse fills on the locked holdout"
    assert v("Fade: the one-time holdout was not evaluated (consumed).", phase="holdout", skipped=True) == []
    div = v("Fade: diversification gate blocked (stays forward-validated, not deployable) — max |corr| 0.93 to deployed "
            "experiment 4 exceeds 0.80.", phase="forward", marginal_ok=False, classification="forward_validated")
    assert _one(div)["measured"].startswith("a 0.93 correlation")
    assert v("Fade: diversification gate PASSED", phase="forward", marginal_ok=True) == []
    assert ge.for_event(None, None) == []


# -- the research paper's figure tints follow the same checks ---------------------------------------------

def _tinted(lines):
    """The figures a set of lines names as missed: a figure is red exactly when one of its gates has a line."""
    missed = {ln["gate"] for ln in lines}
    return {k for k, gates in ge.STAT_GATES.items() if missed & set(gates)}


@pytest.mark.parametrize("combo", list(itertools.product(
    [True, False],              # enough trades for the pre-registered minimum
    [True, False],              # p-value clears its recorded level
    [None, True, False],        # Benjamini-Hochberg within the batch
    [True, False],              # DSR clears its floor
    [True, False],              # CI low end above zero
    [True, False],              # placebo
)))
def test_a_figure_is_red_exactly_when_its_gate_line_says_it_missed(combo):
    enough, sig, bh, dsr_ok, ci_ok, placebo_ok = combo
    val = {"n_trades": 120 if enough else 20, "p_value": 0.01 if sig else 0.2, "fdr_alpha_i": 0.05, "fdr_reject": sig,
           "bh_reject": bh, "dsr": 0.9 if dsr_ok else 0.2, "ci_lo": 0.002 if ci_ok else -0.002, "ci_hi": 0.02,
           "mean_net_return": 0.01, "placebo_p": 0.01 if placebo_ok else 0.5}
    cls = gatekeeper._classify(sig, bh, val["dsr"], val["ci_lo"], val["ci_hi"], placebo_ok).value
    if not enough:
        cls = gatekeeper.Classification.INCONCLUSIVE.value
    exp = {"min_sample": 30, "validation": dict(val, classification=cls), "holdout": None, "folds": []}
    status = "passed" if cls == gatekeeper.Classification.STAT_SUPPORTED.value else "failed"
    lines = ge.for_strategy(status, {"classification": cls}, exp)
    tints = ge.strategy_tints(status, exp)["validation"]
    assert {k for k, t in tints.items() if t == "fail"} == _tinted(lines)
    assert set(tints) == set(ge.STAT_GATES)  # every gated figure the record carries is judged, pass or fail


def test_the_figures_use_the_gates_thresholds_not_the_old_page_cutoffs():
    # The page used to redden a DSR under 0.95, a placebo p under 0.10 (backwards) and a p-value over
    # 0.10; the gates need DSR >= DSR_MIN, placebo p < ALPHA and p <= the recorded FDR level.
    val = {"classification": "inconclusive", "n_trades": 80, "p_value": 0.08, "fdr_alpha_i": 0.05, "dsr": 0.7,
           "ci_lo": -0.001, "ci_hi": 0.02, "mean_net_return": 0.004, "placebo_p": 0.05}
    assert gatekeeper.DSR_MIN <= 0.7 < 0.95 and 0.05 < gatekeeper.ALPHA
    t = ge.strategy_tints("failed", {"min_sample": 30, "validation": val})["validation"]
    assert t == {"n_trades": "pass", "p_value": "fail", "mean_net_return": "fail", "dsr": "pass", "placebo_p": "pass"}
    assert {ln["gate"] for ln in ge.stat_checks(val, min_sample=30, classification="inconclusive")} == {"significance", "net_edge"}
    # A figure the record can't judge has no tint (here: no trade count), so the page leaves it neutral.
    assert "n_trades" not in ge.stat_tints(dict(val, n_trades=None), min_sample=30, classification="inconclusive")
    assert ge.stat_tints({"n_trades": 12, "p_value": None}, min_sample=30, classification="inconclusive") == {"n_trades": "fail"}
    assert ge.stat_tints({"n_trades": 40, "p_value": None}, min_sample=30, classification="inconclusive") == {"n_trades": "pass"}
    assert ge.stat_tints(None) == {} and ge.strategy_tints(None, None) == {}


def test_the_holdout_figures_follow_the_holdout_gates():
    hold = {"classification": "rejected", "n_trades": 12, "p_value": 0.3, "ci_lo": -0.01, "ci_hi": 0.02,
            "mean_net_return": 0.004, "dsr": 0.01, "placebo_p": 0.9}
    exp = {"min_sample": 30, "validation": {"classification": "statistically_supported", "n_trades": 90, "p_value": 0.2,
                                            "dsr": 0.1, "ci_lo": -0.1, "placebo_p": 0.9}, "holdout": hold}
    t = ge.strategy_tints("passed", exp)
    # A validation the strategy passed has no lines, so none of its figures is red, whatever the numbers.
    assert set(t["validation"].values()) == {"pass"}
    # DSR and the placebo don't gate a holdout, and a rejected holdout is not judged on its sample.
    assert t["holdout"] == {"p_value": "fail", "mean_net_return": "fail"}
    assert {ln["gate"] for ln in ge.for_strategy("passed", {}, exp)} == {"significance", "net_edge"}
    assert ge.strategy_tints("passed", dict(exp, holdout=dict(hold, classification=None))).get("holdout") is None
    fwd = ge.strategy_tints("passed", dict(exp, holdout=dict(hold, classification="forward_validated", n_trades=40)))["holdout"]
    assert fwd == {"n_trades": "pass", "p_value": "pass", "mean_net_return": "pass"}


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
    # Each verdict also carries the plain sentence the page shows over a message written for the ledger.
    assert out[1]["data"]["note"] == "Did not pass on data it never saw (9" + NB + "trades)."
    assert out[2]["data"]["note"] == "Passed every check on data it never saw." and out[3]["data"]["note"] is None


def test_ledger_verdict_lines_read_as_plain_sentences():
    note = ge.event_note
    assert note("Lead scan: control arm, hypotheses first.", {"phase": "leads", "arm": "control"}) == \
        "Went straight to ideas, with no scan of the data first."
    assert note("Lead scan: control arm, hypotheses first.", None) == "Went straight to ideas, with no scan of the data first."
    assert note("Lead scan: 3 of 1200 cells survive the false-discovery control.",
                {"phase": "leads", "arm": "leads", "tests": 1200, "n_leads": 3}) == \
        "Scanned the research data for mispriced setups first: 3 of 1,200 held up after correcting for testing so many at once."
    assert note("Model tiering: control arm, one model for every step.", {"phase": "screen", "arm": "control"}) == \
        "One model did every step of this session."
    assert note("Model tiering: X proposed and screened.", {"phase": "screen", "arm": "screen", "screened_out": 3,
                                                           "handed_over": 6, "rescued": 1}) == \
        "A quicker model screened the ideas first: 3 set aside, 6 passed on to be developed, and a second look brought back 1."
    hold = "T: one-time holdout verdict is gatekeeper-held (classification=%s, 31 trades)"
    assert note(hold % "forward_validated", {"title": "T", "phase": "holdout", "classification": "forward_validated",
                                            "stats": {"n_trades": 31}}) == \
        "Held up on the locked holdout, a final test it gets only once (31" + NB + "trades)."
    assert note(hold % "inconclusive", {"title": "T", "phase": "holdout", "classification": "inconclusive",
                                       "stats": {"n_trades": 31}}).startswith("Did not hold up on the locked holdout")
    assert note("T: the one-time holdout was not evaluated (consumed).", {"title": "T", "phase": "holdout", "skipped": True}) == \
        "The one-time final test on the locked holdout did not run."
    assert note("T: diversification gate PASSED", {"title": "T", "phase": "forward", "marginal_ok": True}) == \
        "Adds something new to what you already run."
    assert note("T: diversification gate blocked", {"title": "T", "phase": "forward", "marginal_ok": False}) is None
    assert note("REJECTED (challenger) - T: no mechanism", {"title": "T", "status": "rejected"}) is None
    for n in (note(hold % "x", {"phase": "holdout", "stats": {"n_trades": "bad"}}), note("PASSED - T", {"status": "passed", "stats": "x"})):
        assert n and "=" not in n and "_" not in n


def test_the_run_page_never_carries_an_internal_model_id(monkeypatch):
    run = {"id": 9, "kind": "research", "status": "succeeded", "created_at": None, "heartbeat_at": None, "finished_at": None}
    ev = {"id": 1, "kind": "verdict", "message": "Model tiering: Haiku proposed and screened.", "data": {
        "phase": "screen", "arm": "screen", "screen_model": "haiku", "screen_model_id": "us.anthropic.claude-haiku", "screened_out": 1}}
    monkeypatch.setattr(server.repo, "get_run", lambda cur, uid, rid: dict(run))
    monkeypatch.setattr(server.repo, "runs_spent", lambda *a: {})
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "get_policy", lambda *a: None)
    monkeypatch.setattr(server.repo, "latest_dream_event", lambda *a: None)
    monkeypatch.setattr(server.repo, "run_events", lambda *a: [dict(ev, data=dict(ev["data"]))])
    out = server.get_run(_ctx(("9",)))["events"][0]["data"]
    assert "screen_model_id" not in out and "anthropic" not in str(out)
    assert out["note"].startswith("A quicker model screened the ideas first: 1 set aside")


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
    out = server.get_strategy(_ctx(("4",)))
    why = out["why_failed"]
    assert [ln["gate"] for ln in why] == ["sample_size"] and re.match(r"Needs about 19 more trades", why[0]["next"])
    # The research paper's figure tints ride in the experiment block, judged by the same checks.
    assert out["experiment"]["gate_tints"] == {"validation": {"n_trades": "fail"}}
    assert "gate_tints" not in exp  # the block is copied, never changed in place
    # The backtest's luck caution reads its bar from the server: the app's noise level, above the gate's floor.
    assert out["sample_caution"] == {"min_trades": server.track_record.MIN_TRADES, "gate_min_oos_trades": backtest.GATES["min_oos_trades"]}
    assert out["sample_caution"]["min_trades"] > out["sample_caution"]["gate_min_oos_trades"]
    monkeypatch.setattr(server, "_experiment_block", lambda *a: {"validation": "not a row", "min_sample": 30})
    bad = server.get_strategy(_ctx(("4",)))
    assert bad["why_failed"] == [] and bad["experiment"]["gate_tints"] == {}  # every figure neutral
    monkeypatch.setattr(server, "_experiment_block", lambda *a: None)
    assert server.get_strategy(_ctx(("4",)))["experiment"] is None


def test_the_system_feed_reads_a_verdict_as_the_run_pages_note():
    # The system page's activity feed shows the same plain note as the run page, judged on the whole
    # message, and carries nothing else of the event's data (no stats, no model id).
    held = "FAILED - Fade: validation verdict is gatekeeper-held (classification=inconclusive, 9 trades)" + " " * 200
    row = {"kind": "verdict", "message": held, "created_at": None,
           "data_json": '{"title": "Fade", "status": "failed", "classification": "inconclusive", '
                        '"stats": {"n_trades": 9, "p_value": null, "min_sample": 30}}'}
    ev = server._system_event(row)
    assert len(ev["message"]) == 120
    assert ev["data"] == {"note": "Did not pass on data it never saw (9" + NB + "trades).", "title": "Fade"}
    tier = server._system_event({"kind": "verdict", "message": "Model tiering: Haiku proposed and screened.", "created_at": None,
                                 "data_json": {"phase": "screen", "arm": "screen", "screen_model_id": "us.anthropic.claude-haiku",
                                               "screened_out": 1, "handed_over": 2}})
    assert tier["data"] == {"note": "A quicker model screened the ideas first: 1 set aside, 2 passed on to be developed.", "title": None}
    # No note (its own message already reads plainly), no data, unreadable data, or not a verdict: the message as written.
    for r in ({"kind": "verdict", "message": "REJECTED (challenger) - T: no mechanism", "data_json": '{"title": "T", "status": "rejected"}'},
              {"kind": "verdict", "message": "PASSED - Old", "data_json": None},
              {"kind": "verdict", "message": "PASSED - Old", "data_json": "{not json"},
              {"kind": "step", "message": "Froze 2 finalists", "data_json": '{"note": "x"}'}):
        out = server._system_event(dict(r, created_at=None))
        assert "data" not in out and out["message"] == r["message"]
