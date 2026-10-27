"""Why a research idea did not pass, in plain words: one line per failed gate.

Each line says what fell short (label: the miss itself, never the check's goal, since it sits
under a REJECTED/VOID stamp), what was measured and what was needed, and one concrete thing to
try next; `check` keeps the check's own neutral name. The pages render it as, e.g.

    Too few trades to judge (18 of 30)
    Measured 18 trades on the unseen test window; needed at least 30 trades (fixed before the test).
    Try next: Needs about 12 more trades: widen the market set or lengthen the test window, ...

Built only from numbers already stored: the strategy's result block, the gatekeeper's recorded
validation/holdout row (the strategy page's experiment block), or a run's verdict event. The
thresholds are read from app.research.gatekeeper and app.trading.backtest, never restated, so the wording follows
the gates. Display only: nothing here judges, gates, sizes or trades, and a gate that cannot be
told apart from the stored numbers says so instead of guessing. A gate this module does not know
gets its humanised name and its numbers, never a raw code.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.trading import backtest
from app.research import gatekeeper

NB = "\u00a0"  # a no-break space: keeps a figure with its unit on a phone

Line = Dict[str, str]


def _line(gate: str, check: str, label: str, measured: str, needed: str, next_step: str) -> Line:
    """One failed gate. `check` names what the gate checks ("Enough trades to judge"); `label`
    says what fell short ("Too few trades to judge (18 of 30)"), which is what a page shows under
    a failure. Figures in a label are ones the line already measures, never new ones."""
    return {"gate": gate, "check": check, "label": label, "measured": measured, "needed": needed,
            "next": next_step}


def _of(have: Any, need: Any) -> str:
    """' (18 of 30)' when both counts are known, else ''."""
    h, n = _f(have), _f(need)
    return " (%s of %s)" % (_int(h), _int(n)) if h is not None and n is not None and n > 0 else ""


def humanise(key: Any) -> str:
    """'min_oos_trades' -> 'Min oos trades'. The fallback name for a gate this module doesn't know."""
    s = re.sub(r"[_\-]+", " ", str(key or "")).strip()
    s = re.sub(r"\s+", " ", s)
    return (s[:1].upper() + s[1:]) if s else "Unnamed check"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def _int(v: Any) -> str:
    return "{:,}".format(int(round(float(v))))


def _trades(n: Any) -> str:
    n = int(round(float(n)))
    return "%s%strade%s" % ("{:,}".format(n), NB, "" if n == 1 else "s")


def _pct(r: float) -> str:
    """A per-trade return (a fraction of the stake) as a signed percent: +0.40%, −1.20%."""
    v = round(100 * float(r), 2)
    return ("−" if v < 0 else "+" if v > 0 else "") + "%.2f%%" % abs(v)


def _per_trade(r: float) -> str:
    return "%s%sof the stake per trade" % (_pct(r), NB)


def _p(v: float) -> str:
    """0.180, 0.050, under 0.001: a p-value or a significance level."""
    v = float(v)
    if 0 < v < 0.001:
        return "under" + NB + "0.001"
    s = ("%.3f" % v).rstrip("0")
    return s + "0" * max(0, 4 - len(s)) if "." in s else s


def _usd(v: float) -> str:
    v = round(float(v), 2)
    return ("−" if v < 0 else "") + "$%s" % format(abs(v), ",.2f")


def _more(have: Any, need: Any) -> str:
    gap = max(1, int(round(float(need))) - int(round(float(have))))
    return "needs about %d more trade%s" % (gap, "" if gap == 1 else "s")


MORE_TRADES = "widen the market set or lengthen the test window, or loosen the entry rule so it fires more often"


# -- the gatekeeper's statistical gates (validation and the one-time holdout) ------------------------

def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _sample(n: Any, min_sample: Any, where: str) -> Line:
    need = int(float(min_sample)) if _f(min_sample) is not None and float(min_sample) > 0 else None
    return _line(
        "sample_size", "Enough trades to judge", "Too few trades to judge" + _of(n or 0, need),
        "%s on %s" % (_trades(n or 0), where),
        ("at least %s (fixed before the test)" % _trades(need)) if need else "the minimum fixed before the test",
        ("%s: %s." % (_cap(_more(n or 0, need)), MORE_TRADES)) if need else "Get more trades: %s." % MORE_TRADES)


_PASSED = (gatekeeper.Classification.STAT_SUPPORTED.value,
           gatekeeper.Classification.FORWARD_VALIDATED.value,
           gatekeeper.Classification.DEPLOYMENT_CANDIDATE.value)


def stat_checks(v: Optional[Dict[str, Any]], phase: str = "validation", min_sample: Any = None,
                classification: Optional[str] = None, folds: Optional[Iterable[Dict]] = None,
                n_tested: Any = None) -> List[Line]:
    """The failed gates of one recorded gatekeeper verdict.

    `v` takes the strategy page's phase block (fdr_alpha_i, ci_lo, ci_hi) or a verdict event's
    stats (alpha_i, ci {lo, hi}); keys it lacks are checks it cannot evaluate, and those are left
    out rather than guessed. A non-passing classification whose failed gate the stored numbers
    cannot name gets one line saying which checks remain."""
    if not v or classification in _PASSED:
        return []
    return _judge(v, phase, min_sample, classification, folds, n_tested)[0]


# The research paper's figures and the gates whose line names each one. A figure no gate judges
# (PSR, Sharpe, trials audited, the FDR level itself) has no entry and is never tinted.
STAT_GATES = {
    "n_trades": ("sample_size",),
    "p_value": ("significance", "multiple_testing"),
    "mean_net_return": ("net_edge",),
    "dsr": ("deflated_sharpe",),
    "placebo_p": ("placebo",),
}


def stat_tints(v: Optional[Dict[str, Any]], phase: str = "validation", min_sample: Any = None,
               classification: Optional[str] = None) -> Dict[str, str]:
    """{figure: "pass" | "fail"} for each figure of one recorded verdict that a gate judged, by the
    very checks stat_checks words: "fail" exactly when one of its gates has a line, "pass" when
    its gates were judged and none has one, and absent when the stored numbers cannot judge it
    (the page leaves that figure neutral). A passing classification has no lines, so every figure
    it carries reads "pass"."""
    if not v:
        return {}
    judged = _judge(v, phase, min_sample, classification, None, None)[1]
    if classification in _PASSED:
        judged = {g: True for g in judged}
    out: Dict[str, str] = {}
    for stat, gates in STAT_GATES.items():
        seen = [judged[g] for g in gates if g in judged]
        if seen:
            out[stat] = "pass" if all(seen) else "fail"
    return out


def _judge(v: Dict[str, Any], phase: str, min_sample: Any, classification: Optional[str],
           folds: Optional[Iterable[Dict]], n_tested: Any) -> Tuple[List[Line], Dict[str, bool]]:
    """The line of every failed gate, and {gate: passed} for every gate the numbers could judge."""
    judged: Dict[str, bool] = {}
    holdout = phase == "holdout"
    where = "the locked holdout" if holdout else "the unseen test window"
    n = _f(v.get("n_trades"))
    p = _f(v.get("p_value"))
    if p is None:
        # No test ran: below the pre-registered sample (no alpha spent), the only gate it reached.
        need = _f(min_sample)
        if n is None:
            return [], judged
        judged["sample_size"] = need is not None and n >= need
        return ([] if judged["sample_size"] else [_sample(n, min_sample, where)]), judged
    out: List[Line] = []
    need = _f(min_sample)
    if n is not None and need is not None:
        if n >= need:
            judged["sample_size"] = True
        elif not holdout or classification == gatekeeper.Classification.INCONCLUSIVE.value:
            judged["sample_size"] = False
            out.append(_sample(n, min_sample, where))  # a perpetual holdout is judged on its sample too
    ci = v.get("ci") if isinstance(v.get("ci"), dict) else {}

    def pick(key: str, other: Any) -> Any:
        return v.get(key) if v.get(key) is not None else other

    lo, hi = _f(pick("ci_lo", ci.get("lo"))), _f(pick("ci_hi", ci.get("hi")))
    mean = _f(v.get("mean_net_return"))
    # The level the test had to clear: the holdout's fixed ALPHA; on validation (and paper) the one
    # recorded with the verdict, else today's fixed VALIDATION_ALPHA (a row logged before events
    # carried it). Under LORD++ (VALIDATION_ALPHA=0) an unrecorded level stays unknown.
    level = gatekeeper.ALPHA if holdout else _f(pick("fdr_alpha_i", v.get("alpha_i")))
    if level is None and not holdout and gatekeeper.VALIDATION_ALPHA > 0:
        level = gatekeeper.VALIDATION_ALPHA
    sig_ok = (p <= level) if level is not None else v.get("fdr_reject")
    on = " on the locked holdout" if holdout else ""
    if sig_ok is not None:
        judged["significance"] = bool(sig_ok)
    if sig_ok is False:
        out.append(_line(
            "significance", "Edge is not luck" + on, "The edge could be luck" + on,
            "p-value %s: a rule with no edge would do this well about %d%% of the time" % (_p(p), round(100 * p)),
            ("%s or lower" % _p(level)) if level is not None else "a p-value low enough for the test",
            "Its validation edge did not repeat on fresh data, a sign it was luck: try a simpler version of the idea in a new session."
            if holdout else
            "More trades or a bigger edge per trade would sharpen the test: widen the market set, or enter only on the strongest signals."))
    if not holdout and sig_ok and v.get("bh_reject") is not None:
        judged["multiple_testing"] = v.get("bh_reject") is not False
    if not holdout and sig_ok and v.get("bh_reject") is False:
        k = _f(n_tested)
        out.append(_line(
            "multiple_testing", "Stands out among the ideas tested with it",
            "Didn't stand out among the ideas tested with it",
            "p-value %s%s" % (_p(p), (", one of %s ideas judged together" % _int(k)) if k and k > 1 else ""),
            "low enough to survive the correction for testing several ideas at once (%d%% false-discovery rate)"
            % round(100 * gatekeeper.ALPHA),
            "Send fewer, more different ideas per session, so a real edge is not diluted by near-duplicates."))
    if lo is not None:
        judged["net_edge"] = lo > 0
    if lo is not None and lo <= 0:
        rng = " (90%% range %s to %s)" % (_pct(lo), _pct(hi)) if hi is not None else ""
        losing = mean is not None and mean <= 0
        out.append(_line(
            "net_edge", "Profit after fees holds up" + on,
            ("Loses money after fees" if losing else "Profit after fees is too uncertain") + on,
            ("%s after fees%s" % (_per_trade(mean), rng)) if mean is not None else "a 90%% range starting at %s" % _pct(lo),
            "the whole 90% range above 0%",
            "It loses money after fees here: require a bigger mispricing before entering, so each trade clears the fee."
            if losing else
            "The average is positive but too noisy: more trades (widen the market set) or a bigger edge per trade would lift the low end above zero."))
    if not holdout:
        dsr = _f(v.get("dsr"))
        if dsr is not None:
            judged["deflated_sharpe"] = dsr >= gatekeeper.DSR_MIN
        if dsr is not None and dsr < gatekeeper.DSR_MIN:
            trials = _f(v.get("n_trials_audited"))
            out.append(_line(
                "deflated_sharpe", "Beats the luck of trying many ideas",
                "Doesn't beat the luck of trying many ideas",
                "deflated Sharpe %.2f%s" % (dsr, (" with %s ideas tried on this data" % _int(trials)) if trials and trials > 1 else ""),
                "%.2f or higher" % gatekeeper.DSR_MIN,
                "Many ideas have been tried on this data, so the bar is higher: make this idea more distinct, or get more trades so a real edge stands out."))
        placebo = _f(v.get("placebo_p"))
        if placebo is not None:
            judged["placebo"] = placebo < gatekeeper.ALPHA
        if placebo is not None and placebo >= gatekeeper.ALPHA:
            out.append(_line(
                "placebo", "Wins more often than its prices imply",
                "Wins no more often than its prices imply",
                "placebo p-value %s: random replays at the same prices did as well %d%% of the time" % (_p(placebo), round(100 * placebo)),
                "below %s" % _p(gatekeeper.ALPHA),
                "The wins look like what the prices already predicted: base the entry on information the price does not have yet (a faster feed, news, a forecast)."))
    cross = _cross_day(v, folds) if not holdout else None
    if cross:
        out.append(cross)
    stress = _cost_stress(v, on)
    if stress:
        out.append(stress)
    if not out and classification:
        out += _unstored(v, holdout, on)
    return out, judged


def _unstored(v: Dict[str, Any], holdout: bool, on: str) -> List[Line]:
    """Every check the numbers carry passed, yet the verdict did not: the failed gate is one the
    record does not keep (the ledger row stores neither the cross-day nor the cost-stress result).
    Name it when only one is unknown; say both when both are."""
    c = _cents(gatekeeper.COST_STRESS_CENTS)
    cd_unknown = not holdout and v.get("cross_day_ok") is None
    cs_unknown = v.get("cost_stress_ok") is None
    passed = "not recorded, but every other check passed, so this one failed"
    if cd_unknown and cs_unknown:
        return [_line("cross_day_or_cost", "Works on several stretches of days, and survives %s worse fills" % c,
                      "Didn't hold up on several stretches of days, or with %s worse fills" % c,
                      "not recorded, but every other check passed, so one of these two failed",
                      "profit on most stretches of days, and above 0%% with %s worse fills" % c,
                      "Test it on a longer history and require a bigger edge to enter, then run it again.")]
    if cs_unknown:
        line = _cost_stress({"cost_stress_ok": False}, on)
        line["measured"] = passed
        return [line]
    if cd_unknown:
        line = _cross_day({"cross_day_ok": False}, None)
        line["measured"] = passed
        return [line]
    return []


def _cents(c: float) -> str:
    return ("%g" % float(c)) + "¢"


def _cross_day(v: Dict[str, Any], folds: Optional[Iterable[Dict]]) -> Optional[Line]:
    ok = v.get("cross_day_ok")
    fl = [f for f in (folds or []) if isinstance(f, dict)]
    n_folds = _f(v.get("folds_n"))
    pos = _f(v.get("folds_positive"))
    if n_folds is None and fl:
        n_folds = float(len(fl))
        pos = float(sum(1 for f in fl if (_f(f.get("net_return", f.get("mean_net_return"))) or 0) > 0))
    share = _f(v.get("cross_day_max_day_share"))
    need = "most time slices profitable and no single day over %d%% of the gains" % round(100 * gatekeeper.CROSS_DAY_MAX_DAY_SHARE)
    nxt = "The profit came from a short stretch: test it on a longer history, and add a condition that says when it should work."
    check = "Works on several stretches of days"
    if n_folds is not None and n_folds < gatekeeper.CROSS_DAY_MIN_FOLDS and (ok is False or ok is None):
        return _line("cross_day", check, "Too few trades to check several stretches of days",
                     "too few trades for %d time slices" % gatekeeper.CROSS_DAY_MIN_FOLDS, need,
                     "Get more trades so the test can split them by time: %s." % MORE_TRADES)
    if n_folds and pos is not None and pos / n_folds < gatekeeper.CROSS_DAY_MIN_POS_FRACTION and ok is not True:
        return _line("cross_day", check, "Made money on too few stretches of days" + _of(pos, n_folds),
                     "%s of %s time slices profitable" % (_int(pos), _int(n_folds)), need, nxt)
    if ok is False:
        one_day = share is not None and share > gatekeeper.CROSS_DAY_MAX_DAY_SHARE
        measured = ("one day carrying %d%% of the gains" % round(100 * share)) if one_day \
            else "profit that did not hold across time slices"
        label = "Nearly all the gains came from one day" if one_day else "Didn't hold up across stretches of days"
        return _line("cross_day", check, label, measured, need, nxt)
    return None


def _cost_stress(v: Dict[str, Any], on: str = "") -> Optional[Line]:
    if v.get("cost_stress_ok") is not False:
        return None
    c = _cents(gatekeeper.COST_STRESS_CENTS)
    m = _f(v.get("cost_stress_mean"))
    return _line(
        "cost_stress", "Survives %s worse fills%s" % (c, on), "Loses its edge with %s worse fills%s" % (c, on),
        ("%s with %s worse fills" % (_per_trade(m), c)) if m is not None else "no trades left with %s worse fills" % c,
        "above 0%",
        "The edge is thinner than real trading friction: raise the minimum edge to enter by at least 2¢, so it still pays after a worse fill.")


# -- gates before the statistical test -------------------------------------------------------------

_PRE = [
    (re.compile(r"only (\d+) research-fold trades \(need (\d+)\)"), "trades"),
    (re.compile(r"research-fold mean net return (-?[\d.]+(?:e-?\d+)?) is not positive"), "edge"),
    (re.compile(r"expected to hold ~(\d+) trades, below the pre-registered min_sample (\d+)"), "window"),
    (re.compile(r"projected validation power (\d+)% < (\d+)%: a research-fold edge of (-?[\d.]+)%/trade over ~(\d+) validation trades"), "power"),
]


def prescreen(reason: Optional[str]) -> List[Line]:
    """The validation-budget pre-screen (gatekeeper.validation_power) from its stored reason."""
    r = str(reason or "").strip()
    if not r or r == "no validation window to project onto":
        return []
    for rx, kind in _PRE:
        m = rx.search(r)
        if not m:
            continue
        g = m.groups()
        if kind == "trades":
            return [_line("research_trades", "Enough research trades to plan the test",
                          "Too few research trades to plan the test" + _of(g[0], g[1]),
                          "%s on the research data" % _trades(g[0]), "at least %s" % _trades(g[1]),
                          "%s: loosen the entry rule or add markets so it trades more on the research data." % _cap(_more(g[0], g[1])))]
        if kind == "edge":
            c = _cents(gatekeeper.COST_STRESS_CENTS)
            return [_line("research_edge", "Makes money after fees and %s worse fills on the research data" % c,
                          "Doesn't make money after fees and %s worse fills on the research data" % c,
                          _per_trade(float(g[0])), "above 0%",
                          "Require a bigger mispricing before entering, so each trade clears the fee and a worse fill.")]
        if kind == "window":
            return [_line("expected_trades", "Enough trades expected in the unseen test window",
                          "Too few trades expected in the unseen test window" + _of(g[0], g[1]).replace("(", "(about ", 1),
                          "about %s expected" % _trades(g[0]), "at least %s (fixed before the test)" % _trades(g[1]),
                          "%s: %s." % (_cap(_more(g[0], g[1])), MORE_TRADES))]
        return [_line("test_power", "Likely to prove itself on unseen data",
                      "Unlikely to prove itself on unseen data (about a %s%% chance)" % g[0],
                      "about a %s%% chance to pass (an edge of %s over about %s)"
                      % (g[0], _per_trade(float(g[2]) / 100.0), _trades(g[3])),
                      "at least a %s%% chance" % g[1],
                      "A bigger edge per trade or more trades raise the odds: enter only on the strongest setups, or widen the market set.")]
    return [_line("pre_screen", "Worth spending a test on", "Not yet worth spending a test on", r[:200], "a research result strong enough to test",
                  "Make the research result stronger (more trades or a bigger edge per trade), then run it again.")]


def challenger(reason: Optional[str]) -> List[Line]:
    why = str(reason or "").strip() or "no credible reason the edge exists"
    return [_line("challenger", "Passed the skeptic's review", "The skeptic's review didn't pass it",
                  "an objection before testing: " + why[:240].rstrip("."),
                  "a believable reason the edge exists and is not traded away",
                  "Say who is on the other side of the trade and why they keep paying, then run the idea again.")]


def not_finalist(in_sample: Optional[Dict[str, Any]]) -> List[Line]:
    ins = in_sample or {}
    pnl, n = _f(ins.get("pnl")), _f(ins.get("trades"))
    if n is not None and n < 5:
        return [_line("research_trades", "Enough research trades to be a finalist",
                      "Too few research trades to be a finalist" + _of(n, 5), "%s on the research data" % _trades(n),
                      "at least %s" % _trades(5), "Loosen the entry rule or add markets so it trades more on the research data.")]
    if pnl is not None and pnl <= 0:
        return [_line("research_pnl", "Makes money on the research data", "Lost money on the research data",
                      "%s over %s" % (_usd(pnl), _trades(n or 0)), "above $0",
                      "It lost money on the data it was built on: rethink the signal before testing more.")]
    made = ("%s over %s on the research data" % (_usd(pnl), _trades(n or 0))) if pnl is not None else "a lower rank than the finalists"
    return [_line("finalist", "Among the round's strongest ideas", "Not among the round's strongest ideas", made,
                  "a top spot: only the best few of each round are tested on unseen data",
                  "Run a session focused on this one idea, so it does not compete with stronger ones.")]


_CORR = re.compile(r"max \|corr\| ([\d.]+) to deployed experiment \S+ exceeds ([\d.]+)")
_CORR_PEER = re.compile(r"to deployed experiment (\d+) exceeds")


def diversification(reason: Optional[str]) -> List[Line]:
    m = _CORR.search(str(reason or ""))
    measured = ("a %s correlation of daily results with a strategy you already run" % m.group(1)) if m \
        else (str(reason or "").strip()[:200] or "too similar to a strategy you already run")
    return [_line("diversification", "Adds something new to what you already run",
                  "Too similar to a strategy you already run", measured,
                  "%s or less" % (m.group(2) if m else "%.2f" % gatekeeper.CORR_MAX),
                  "Point it at a different market or time of day, so it does not repeat a strategy you already run.")]


def corr_peer(reason: Optional[str]) -> Optional[int]:
    """The experiment id of the deployed strategy a diversification miss names, or None. For the page
    to look up that strategy's title; the id itself is never shown."""
    m = _CORR_PEER.search(str(reason or ""))
    return int(m.group(1)) if m else None


_HELD_ON = {"holdout": "it held up on the locked holdout", "paper": "it passed its one judgment on paper"}


def held_back(reason: Optional[str], peer: Optional[str] = None, on: str = "holdout") -> List[Line]:
    """The check after the one-time holdout (or, `on` "paper", after a probation strategy's one paper
    judgment), for a strategy that passed there and was not promoted to a deployment candidate: the
    diversification line, named for the strategy it repeats (`peer`, that strategy's title) when known.
    `reason` is the gatekeeper's recorded reason; without a figure there, the line says the check was
    not recorded rather than guessing one."""
    m = _CORR.search(str(reason or ""))
    line = diversification(reason if m else None)[0]
    if not m:
        line["measured"] = "not recorded, but %s and was not cleared to trade, so this check failed" % _HELD_ON.get(on, _HELD_ON["holdout"])
    if peer:
        name = "“%s”" % str(peer).strip()[:80]
        line["label"] = "Too similar to " + name
        if m:
            line["measured"] = "a %s correlation of daily results with %s" % (m.group(1), name)
    return [line]


# -- the backtest's own gates (strategy result.gates) ----------------------------------------------

def _needed(threshold: Any) -> str:
    t = str(threshold if threshold is not None else "").strip()
    for sym, word in ((">=", "at least "), ("≥", "at least "), (">", "above ")):
        if t.startswith(sym):
            return word + t[len(sym):].strip()
    for sym in ("≤", "<="):
        if t.startswith(sym):
            return t[len(sym):].strip() + " or less"
    if t.startswith("<"):
        return "below " + t[1:].strip()
    return t or "the gate's threshold"


def _money(v: Any) -> str:
    x = _f(v)
    return _usd(x) if x is not None else str(v)


def backtest_gates(gates: Optional[Iterable[Dict[str, Any]]]) -> List[Line]:
    """The failed rows of a backtest's gate list (backtest.gates), each with its next step."""
    out: List[Line] = []
    for g in gates or []:
        if not isinstance(g, dict) or g.get("ok"):
            continue
        name, val, thr = str(g.get("name") or ""), g.get("value"), g.get("threshold")
        need = _needed(thr)
        if name == "Makes money in-sample":
            out.append(_line("in_sample_pnl", "Makes money on the data it was built on",
                             "Didn't make money on the data it was built on", _money(val), need,
                             "It lost money even on the data it was tuned on: rethink the signal before testing more."))
        elif name == "Makes money on unseen data":
            out.append(_line("unseen_pnl", name, "Didn't make money on unseen data", _money(val), need,
                             "It made money only where it was tuned, a sign of overfitting: simplify the rule (fewer conditions) and test again."))
        elif name == "Enough unseen trades to judge":
            have = _f(val) or 0
            out.append(_line("unseen_trades", name,
                             "Too few trades on unseen data" + _of(have, backtest.GATES["min_oos_trades"]),
                             _trades(have) + " on unseen data",
                             "at least %s" % _trades(backtest.GATES["min_oos_trades"]),
                             "%s: %s." % (_cap(_more(have, backtest.GATES["min_oos_trades"])), MORE_TRADES)))
        elif name == "Wins outweigh losses on unseen data":
            pf = _f(val)
            out.append(_line("profit_factor", name, "Wins don't outweigh losses by enough on unseen data",
                             ("wins %.2f×%sthe losses" % (pf, NB)) if pf is not None else "no winning trades",
                             "at least %.1f×%sthe losses" % (backtest.GATES["min_profit_factor"], NB),
                             "Cut losing trades sooner (add a stop-loss) or skip the weakest entries."))
        elif name == "Worst drawdown on unseen data":
            out.append(_line("drawdown", name, "Drawdown on unseen data was too deep", _money(val) + " at the worst point", need,
                             "Lower the stake or hold fewer positions at once, or add a stop-loss."))
        elif name == "Has a real edge, not a coin flip":
            out.append(_line("real_edge", name, "No real edge: it looks like a coin flip", str(val), need,
                             "Describe an idea with a reason it should beat the price, and run a session on it."))
        else:
            out.append(unknown(name, val, thr))
    return out


def unknown(key: Any, value: Any = None, threshold: Any = None) -> Line:
    """A gate this module has no words for: its humanised name and its numbers, never a raw code."""
    if value is None:
        measured = "not recorded"
    elif isinstance(value, bool):
        measured = "yes" if value else "no"
    elif isinstance(value, (int, float)):
        measured = _money(value) if "$" in str(threshold or "") else "%g" % value
    else:
        measured = str(value)[:200]
    return _line("other", humanise(key), "Didn't pass: " + humanise(key), measured,
                 _needed(threshold) if threshold is not None else "the gate's threshold",
                 "Change one thing about the rule and test again, so you can see what moves this check.")


# -- entry points: a strategy page, a run's verdict event -------------------------------------------

_PASSING = {"passed"}


def for_strategy(status: Optional[str], result: Optional[Dict[str, Any]],
                 experiment: Optional[Dict[str, Any]] = None) -> List[Line]:
    """Every failed gate of one strategy, from what its page already reads: the gatekeeper's
    recorded verdict (the experiment block) when there is one, else the result block's own stage
    (pre-screen, challenger, finalist selection) or its backtest gates. A validation pass keeps the
    status "passed" even when the one-time holdout then fails, so that failure is read first. []
    for a strategy that passed everything it was judged on."""
    exp = experiment or {}
    hold = exp.get("holdout")
    if hold and hold.get("classification") not in (None, gatekeeper.Classification.FORWARD_VALIDATED.value):
        lines = stat_checks(hold, "holdout", exp.get("min_sample"), hold.get("classification"))
        if lines:
            return lines
    if status in _PASSING:
        return []
    res = result or {}
    cls = res.get("classification")
    if cls == "underpowered":
        return prescreen(res.get("gate_reason"))
    if cls == "challenger_rejected":
        return challenger(res.get("challenger_reason"))
    if cls == "not_finalist":
        return not_finalist(res.get("in_sample"))
    val = exp.get("validation")
    if val:
        lines = stat_checks(val, "validation", exp.get("min_sample"), val.get("classification"),
                            folds=exp.get("folds"), n_tested=exp.get("planned_n_tests"))
        if lines:
            return lines
    lines = backtest_gates(res.get("gates"))
    if lines:
        return lines
    if status == "rejected" and res.get("in_sample"):
        return not_finalist(res.get("in_sample"))
    return []


def strategy_tints(status: Optional[str], experiment: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """The research paper's tint per figure, {"validation": {...}, "holdout": {...}} (stat_tints),
    judged on the same records for_strategy words: a validation the strategy passed ("passed")
    reads as passed, and a holdout without a recorded verdict is not judged."""
    exp = experiment or {}
    out: Dict[str, Dict[str, str]] = {}
    val, hold = exp.get("validation"), exp.get("holdout")
    if val:
        cls = gatekeeper.Classification.STAT_SUPPORTED.value if status in _PASSING else val.get("classification")
        out["validation"] = stat_tints(val, "validation", exp.get("min_sample"), cls)
    if hold and hold.get("classification") is not None:
        out["holdout"] = stat_tints(hold, "holdout", exp.get("min_sample"), hold.get("classification"))
    return out


_NOT_FINALIST = re.compile(r"research pnl \$(-?[\d.]+|None) over (\d+|None) trades")


def for_event(message: Optional[str], data: Optional[Dict[str, Any]]) -> List[Line]:
    """Every failed gate a run's verdict event can name, from its data (and, for events logged
    before the data carried the numbers, the reason in its message). [] for a pass."""
    d = data or {}
    msg = str(message or "")
    title = str(d.get("title") or "")
    tail = msg.split(title + ":", 1)[1].strip() if title and (title + ":") in msg else ""
    if d.get("phase") == "forward" and d.get("marginal_ok") is False:
        return diversification(d.get("reason") or tail)
    if d.get("phase") == "holdout":
        if d.get("skipped"):
            return []
        return stat_checks(d.get("stats"), "holdout", d.get("min_sample"), d.get("classification"))
    if d.get("status") == "passed":
        return []
    if msg.startswith("NOT TESTED"):
        return prescreen(d.get("reason") or tail)
    if msg.startswith("REJECTED (challenger)"):
        return challenger(d.get("reason") or tail)
    if "not a finalist" in msg:
        ins = d.get("in_sample")
        if not ins:
            m = _NOT_FINALIST.search(msg)
            ins = {"pnl": _f(m.group(1)), "trades": _f(m.group(2))} if m else {}
        return not_finalist(ins)
    stats = d.get("stats")
    if stats:
        st = dict(stats)
        if d.get("n_tested") is not None:
            st.setdefault("n_tested", d.get("n_tested"))
        return stat_checks(st, "validation", st.get("min_sample"), d.get("classification"),
                           n_tested=st.get("n_tested"))
    return []


# -- the run feed's other verdict lines, in plain words ---------------------------------------------

def _count(v: Any) -> Optional[int]:
    f = _f(v)
    return int(round(f)) if f is not None else None


def event_note(message: Optional[str], data: Optional[Dict[str, Any]]) -> Optional[str]:
    """One plain sentence for a run verdict event whose own message is written for the ledger
    ("validation verdict is gatekeeper-held (classification=...)", "Lead scan: control arm",
    "Model tiering: ..."), or None when the message already reads plainly or its for_event lines
    say it. The run page shows it in place of that message. Built from the numbers the event
    carries; display only, and nothing here reaches the generator."""
    d = data or {}
    msg = str(message or "")
    phase = d.get("phase") or ("leads" if msg.startswith("Lead scan:") else "screen" if msg.startswith("Model tiering:") else None)
    if phase == "leads":
        if d.get("arm") != "leads":
            return "Went straight to ideas, with no scan of the data first."
        n, tests = _count(d.get("n_leads")), _count(d.get("tests"))
        if n is None or not tests:
            return "Scanned the research data for mispriced setups first."
        return ("Scanned the research data for mispriced setups first: %s of %s held up after correcting "
                "for testing so many at once." % (_int(n), _int(tests)))
    if phase == "screen":
        if d.get("arm") != "screen":
            return "One model did every step of this session."
        out, handed, rescued = (_count(d.get(k)) or 0 for k in ("screened_out", "handed_over", "rescued"))
        return ("A quicker model screened the ideas first: %d set aside, %d passed on to be developed%s."
                % (out, handed, (", and a second look brought back %d" % rescued) if rescued else ""))
    stats = d.get("stats") if isinstance(d.get("stats"), dict) else {}
    n = _count(stats.get("n_trades"))
    trades = (" (%s)" % _trades(n)) if n is not None else ""
    if phase == "holdout":
        if d.get("skipped"):
            return "The one-time final test on the locked holdout did not run."
        if d.get("classification") in _PASSED:
            return "Held up on the locked holdout, a final test it gets only once%s." % trades
        return "Did not hold up on the locked holdout, a final test it gets only once%s." % trades
    if phase == "forward":
        return "Adds something new to what you already run." if d.get("marginal_ok") else None
    if d.get("status") == "passed":
        # Its first test only: the one-time locked holdout and the diversification check come after it,
        # and a pass that misses either is stamped Missed final test or Held back. "Passed every check"
        # here sat right above that holdout's "Missed" on the run page.
        return "Passed its first test on data it never saw%s." % trades
    if "gatekeeper-held" in msg:
        return "Did not pass on data it never saw%s." % trades
    return None


# -- the run feed's step lines, in plain words ------------------------------------------------------

def _ideas(n: int) -> str:
    return "%d idea%s" % (n, "" if n == 1 else "s")


def _Ideas(n: int) -> str:
    return "%d idea%s" % (n, "" if n == 1 else "s") if n else "None"


# A running session's progress line (agent.py, after each chunk); step_note counts its uncleared passes apart.
_STILL = re.compile(r"^Still running - (\d+) tested so far, (\d+) passed\. Exploring more \(stop anytime\)\.")


# The agent's own step lines, written for whoever reads the run's ledger ("Froze 2 finalists; the
# challenger reviewed each before any validation budget was spent."), as a customer reads them. Each
# pattern matches the line agent.py writes today (tests/test_gate_explain.py renders each one); a line
# no pattern knows keeps its words.
_STEP_NOTES: List[Tuple["re.Pattern[str]", Any]] = [
    (re.compile(r"^Plan: explore (?:up to (\d+) hypotheses|hypotheses until you stop it), refining each round on "
                r"the in-sample results, then gate the best on data never seen\."),
     lambda m: "Plan: try %s, sharpen each one on past data, then test the best on data it hasn't seen."
     % ("up to " + _ideas(int(m.group(1))) if m.group(1) else "ideas until you stop it")),
    (re.compile(r"^Proposing round (\d+) — generating up to (\d+) hypothes[ie]s…"),
     lambda m: "Round %s: coming up with up to %s…" % (m.group(1), _ideas(int(m.group(2))))),
    (re.compile(r"^Resuming round (\d+) with (\d+) proposed hypothes[ie]s not yet developed\."),
     lambda m: "Round %s, picking up where it left off: %s still to work out." % (m.group(1), _ideas(int(m.group(2))))),
    (re.compile(r"^Froze (\d+) finalists?; the challenger reviewed each before any validation budget was spent\."),
     lambda m: ("Picked 1 idea to test on data it hasn't seen; a skeptical reviewer read it first."
                if m.group(1) == "1" else "Picked the best %s to test on data it hasn't seen; a skeptical reviewer "
                "read each one first." % _ideas(int(m.group(1))))),
    (re.compile(r"^Challenger unavailable; approving finalists as-is — the gatekeeper still gates\."),
     lambda m: "The skeptical review couldn't run this time, so the picked ideas go straight to the test on "
               "data it hasn't seen, which still decides."),
    (_STILL,
     lambda m:"%s tested so far, %s passed. Looking for more; you can stop it anytime." % (m.group(1), m.group(2))),
    (re.compile(r"^Paused — out of credits\."),
     lambda m: "Out of credits, so the session stopped here. Add credits (or turn on auto-reload), then start "
               "a new session to keep researching."),
    (re.compile(r"^Resuming — re-using (\d+) explored hypotheses, preparing (.+)…$"),
     lambda m: "Picking up where it left off, keeping the %s it had explored; preparing %s…"
     % (_ideas(int(m.group(1))), m.group(2))),
    (re.compile(r"^Last (\d+) theses all dropped on the research fold\. Stopping proposals; (\d+) kept go to the gate\."),
     lambda m: "The last %s all fell apart on past data, so it stopped coming up with more. %s go on to the test."
     % (_ideas(int(m.group(1))), _Ideas(int(m.group(2))))),
    (re.compile(r"^The proposer keeps returning mechanisms the sibling markets already killed\. Stopping proposals; "
                r"(\d+) kept go to the gate\."),
     lambda m: "Its new ideas kept repeating ones that already failed on similar markets, so it stopped coming up "
               "with more. %s go on to the test." % _Ideas(int(m.group(1)))),
    (re.compile(r"^No tradeable surface after (\d+) attempts — stopping to free the worker\."),
     lambda m: "After %s attempts, nothing here traded often enough to test, so it stopped." % m.group(1)),
]
# The session's last line; the seeded example's says "0 of 2 hypotheses passed. Random really does ...".
_DONE = re.compile(r"^(\d+) of (\d+) hypotheses passed( every gate)?(?: \((\d+) dropped on research data\))?\.(.*)$", re.S)


def step_note(kind: Optional[str], message: Optional[str], not_cleared: int = 0) -> Optional[str]:
    """One plain sentence for a run's step or done line written for the ledger ("in-sample",
    "finalist", "gate", "validation budget"), or None when the line already reads plainly. The run page
    shows it in place of the message, which stays as written (the page finds the out-of-credits line by
    its words). `not_cleared`: how many of the done line's passes a later check left uncleared (the
    session's Missed final test and Held back stamps, which the run page's handler reads). The agent's
    count holds them, so "1 of 2 ideas passed every check" sat under the page's "Passed 0, 1 not
    cleared"; the line counts them apart, as the page's figures do. A running session's "N tested so far,
    M passed" line does the same with `not_cleared` as how many of its M were left uncleared. Display only."""
    msg = str(message or "")
    if kind == "done":
        m = _DONE.match(msg)
        if not m:
            return None
        dropped = int(m.group(4) or 0)
        fell = min(max(0, int(not_cleared or 0)), int(m.group(1)))
        if fell and m.group(3):
            return "%d of %s cleared every check%s; %d more passed %s first test, then %s cleared to trade.%s" % (
                int(m.group(1)) - fell, _ideas(int(m.group(2))), " (%d dropped before testing)" % dropped if dropped else "",
                fell, "its" if fell == 1 else "their", "wasn't" if fell == 1 else "weren't", m.group(5))
        return "%s of %s passed%s%s.%s" % (m.group(1), _ideas(int(m.group(2))), " every check" if m.group(3) else "",
                                           " (%d dropped before testing)" % dropped if dropped else "", m.group(5))
    if kind != "step":
        return None
    m = _STILL.match(msg)
    if m:
        # A running session's "N tested so far, M passed": M is the agent's count, which holds the passes a
        # later check left uncleared, so it read "3 passed" over a page saying "Passed 1, 2 not cleared". Here
        # `not_cleared` is how many of the passes this line counts were left uncleared (views._with_gate_lines).
        passed = int(m.group(2))
        fell = min(max(0, int(not_cleared or 0)), passed)
        if fell:
            return ("%s tested so far, %d cleared every check; %d more passed %s first test, then %s cleared to trade. "
                    "Looking for more; you can stop it anytime." % (m.group(1), passed - fell, fell, "its" if fell == 1 else "their",
                                                                   "wasn't" if fell == 1 else "weren't"))
    for rx, say in _STEP_NOTES:
        m = rx.match(msg)
        if m:
            return say(m)
    return None
