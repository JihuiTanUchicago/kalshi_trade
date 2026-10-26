"""Why a research idea did not pass, in plain words: one line per failed gate.

Each line says what the gate checks (label), what was measured and what was needed, and one
concrete thing to try next. The pages render it as, e.g.

    Enough trades to judge
    Measured 18 trades on the unseen test window; needed at least 30 trades (fixed before the test).
    Try next: Needs about 12 more trades: widen the market set or lengthen the test window, ...

Built only from numbers already stored: the strategy's result block, the gatekeeper's recorded
validation/holdout row (the strategy page's experiment block), or a run's verdict event. The
thresholds are read from app.gatekeeper and app.backtest, never restated, so the wording follows
the gates. Display only: nothing here judges, gates, sizes or trades, and a gate that cannot be
told apart from the stored numbers says so instead of guessing. A gate this module does not know
gets its humanised name and its numbers, never a raw code.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from app import backtest, gatekeeper

NB = "\u00a0"  # a no-break space: keeps a figure with its unit on a phone

Line = Dict[str, str]


def _line(gate: str, label: str, measured: str, needed: str, next_step: str) -> Line:
    return {"gate": gate, "label": label, "measured": measured, "needed": needed, "next": next_step}


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
        "sample_size", "Enough trades to judge", "%s on %s" % (_trades(n or 0), where),
        ("at least %s (fixed before the test)" % _trades(need)) if need else "the minimum fixed before the test",
        ("%s: %s." % (_cap(_more(n or 0, need)), MORE_TRADES)) if need else "Get more trades: %s." % MORE_TRADES)


def stat_checks(v: Optional[Dict[str, Any]], phase: str = "validation", min_sample: Any = None,
                classification: Optional[str] = None, folds: Optional[Iterable[Dict]] = None,
                n_tested: Any = None) -> List[Line]:
    """The failed gates of one recorded gatekeeper verdict.

    `v` takes the strategy page's phase block (fdr_alpha_i, ci_lo, ci_hi) or a verdict event's
    stats (alpha_i, ci {lo, hi}); keys it lacks are checks it cannot evaluate, and those are left
    out rather than guessed. A non-passing classification whose failed gate the stored numbers
    cannot name gets one line saying which checks remain."""
    if not v:
        return []
    if classification in (gatekeeper.Classification.STAT_SUPPORTED.value,
                          gatekeeper.Classification.FORWARD_VALIDATED.value,
                          gatekeeper.Classification.DEPLOYMENT_CANDIDATE.value):
        return []
    holdout = phase == "holdout"
    where = "the locked holdout" if holdout else "the unseen test window"
    n = _f(v.get("n_trades"))
    p = _f(v.get("p_value"))
    if p is None:
        # No test ran: below the pre-registered sample (no alpha spent), the only gate it reached.
        need = _f(min_sample)
        if n is not None and (need is None or n < need):
            return [_sample(n, min_sample, where)]
        return []
    out: List[Line] = []
    need = _f(min_sample)
    if n is not None and need is not None and n < need and (
            not holdout or classification == gatekeeper.Classification.INCONCLUSIVE.value):
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
    if sig_ok is False:
        out.append(_line(
            "significance", "Edge is not luck" + on,
            "p-value %s: a rule with no edge would do this well about %d%% of the time" % (_p(p), round(100 * p)),
            ("%s or lower" % _p(level)) if level is not None else "a p-value low enough for the test",
            "Its validation edge did not repeat on fresh data, a sign it was luck: try a simpler version of the idea in a new session."
            if holdout else
            "More trades or a bigger edge per trade would sharpen the test: widen the market set, or enter only on the strongest signals."))
    if not holdout and sig_ok and v.get("bh_reject") is False:
        k = _f(n_tested)
        out.append(_line(
            "multiple_testing", "Stands out among the ideas tested with it",
            "p-value %s%s" % (_p(p), (", one of %s ideas judged together" % _int(k)) if k and k > 1 else ""),
            "low enough to survive the correction for testing several ideas at once (%d%% false-discovery rate)"
            % round(100 * gatekeeper.ALPHA),
            "Send fewer, more different ideas per session, so a real edge is not diluted by near-duplicates."))
    if lo is not None and lo <= 0:
        rng = " (90%% range %s to %s)" % (_pct(lo), _pct(hi)) if hi is not None else ""
        losing = mean is not None and mean <= 0
        out.append(_line(
            "net_edge", "Profit after fees holds up" + on,
            ("%s after fees%s" % (_per_trade(mean), rng)) if mean is not None else "a 90%% range starting at %s" % _pct(lo),
            "the whole 90% range above 0%",
            "It loses money after fees here: require a bigger mispricing before entering, so each trade clears the fee."
            if losing else
            "The average is positive but too noisy: more trades (widen the market set) or a bigger edge per trade would lift the low end above zero."))
    if not holdout:
        dsr = _f(v.get("dsr"))
        if dsr is not None and dsr < gatekeeper.DSR_MIN:
            trials = _f(v.get("n_trials_audited"))
            out.append(_line(
                "deflated_sharpe", "Beats the luck of trying many ideas",
                "deflated Sharpe %.2f%s" % (dsr, (" with %s ideas tried on this data" % _int(trials)) if trials and trials > 1 else ""),
                "%.2f or higher" % gatekeeper.DSR_MIN,
                "Many ideas have been tried on this data, so the bar is higher: make this idea more distinct, or get more trades so a real edge stands out."))
        placebo = _f(v.get("placebo_p"))
        if placebo is not None and placebo >= gatekeeper.ALPHA:
            out.append(_line(
                "placebo", "Wins more often than its prices imply",
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
    return out


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
    if n_folds is not None and n_folds < gatekeeper.CROSS_DAY_MIN_FOLDS and (ok is False or ok is None):
        return _line("cross_day", "Works on several stretches of days",
                     "too few trades for %d time slices" % gatekeeper.CROSS_DAY_MIN_FOLDS, need,
                     "Get more trades so the test can split them by time: %s." % MORE_TRADES)
    if n_folds and pos is not None and pos / n_folds < gatekeeper.CROSS_DAY_MIN_POS_FRACTION and ok is not True:
        return _line("cross_day", "Works on several stretches of days",
                     "%s of %s time slices profitable" % (_int(pos), _int(n_folds)), need, nxt)
    if ok is False:
        measured = ("one day carrying %d%% of the gains" % round(100 * share)) if share is not None and share > gatekeeper.CROSS_DAY_MAX_DAY_SHARE \
            else "profit that did not hold across time slices"
        return _line("cross_day", "Works on several stretches of days", measured, need, nxt)
    return None


def _cost_stress(v: Dict[str, Any], on: str = "") -> Optional[Line]:
    if v.get("cost_stress_ok") is not False:
        return None
    c = _cents(gatekeeper.COST_STRESS_CENTS)
    m = _f(v.get("cost_stress_mean"))
    return _line(
        "cost_stress", "Survives %s worse fills%s" % (c, on),
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
                          "%s on the research data" % _trades(g[0]), "at least %s" % _trades(g[1]),
                          "%s: loosen the entry rule or add markets so it trades more on the research data." % _cap(_more(g[0], g[1])))]
        if kind == "edge":
            return [_line("research_edge", "Makes money after fees and %s worse fills on the research data" % _cents(gatekeeper.COST_STRESS_CENTS),
                          _per_trade(float(g[0])), "above 0%",
                          "Require a bigger mispricing before entering, so each trade clears the fee and a worse fill.")]
        if kind == "window":
            return [_line("expected_trades", "Enough trades expected in the unseen test window",
                          "about %s expected" % _trades(g[0]), "at least %s (fixed before the test)" % _trades(g[1]),
                          "%s: %s." % (_cap(_more(g[0], g[1])), MORE_TRADES))]
        return [_line("test_power", "Likely to prove itself on unseen data",
                      "about a %s%% chance to pass (an edge of %s over about %s)"
                      % (g[0], _per_trade(float(g[2]) / 100.0), _trades(g[3])),
                      "at least a %s%% chance" % g[1],
                      "A bigger edge per trade or more trades raise the odds: enter only on the strongest setups, or widen the market set.")]
    return [_line("pre_screen", "Worth spending a test on", r[:200], "a research result strong enough to test",
                  "Make the research result stronger (more trades or a bigger edge per trade), then run it again.")]


def challenger(reason: Optional[str]) -> List[Line]:
    why = str(reason or "").strip() or "no credible reason the edge exists"
    return [_line("challenger", "Passed the skeptic's review", "an objection before testing: " + why[:240].rstrip("."),
                  "a believable reason the edge exists and is not traded away",
                  "Say who is on the other side of the trade and why they keep paying, then run the idea again.")]


def not_finalist(in_sample: Optional[Dict[str, Any]]) -> List[Line]:
    ins = in_sample or {}
    pnl, n = _f(ins.get("pnl")), _f(ins.get("trades"))
    if n is not None and n < 5:
        return [_line("research_trades", "Enough research trades to be a finalist", "%s on the research data" % _trades(n),
                      "at least %s" % _trades(5), "Loosen the entry rule or add markets so it trades more on the research data.")]
    if pnl is not None and pnl <= 0:
        return [_line("research_pnl", "Makes money on the research data",
                      "%s over %s" % (_usd(pnl), _trades(n or 0)), "above $0",
                      "It lost money on the data it was built on: rethink the signal before testing more.")]
    made = ("%s over %s on the research data" % (_usd(pnl), _trades(n or 0))) if pnl is not None else "a lower rank than the finalists"
    return [_line("finalist", "Among the round's strongest ideas", made,
                  "a top spot: only the best few of each round are tested on unseen data",
                  "Run a session focused on this one idea, so it does not compete with stronger ones.")]


_CORR = re.compile(r"max \|corr\| ([\d.]+) to deployed experiment \S+ exceeds ([\d.]+)")


def diversification(reason: Optional[str]) -> List[Line]:
    m = _CORR.search(str(reason or ""))
    measured = ("a %s correlation of daily results with a strategy you already run" % m.group(1)) if m \
        else (str(reason or "").strip()[:200] or "too similar to a strategy you already run")
    return [_line("diversification", "Adds something new to what you already run", measured,
                  "%s or less" % (m.group(2) if m else "%.2f" % gatekeeper.CORR_MAX),
                  "Point it at a different market or time of day, so it does not repeat a strategy you already run.")]


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
            out.append(_line("in_sample_pnl", "Makes money on the data it was built on", _money(val), need,
                             "It lost money even on the data it was tuned on: rethink the signal before testing more."))
        elif name == "Makes money on unseen data":
            out.append(_line("unseen_pnl", name, _money(val), need,
                             "It made money only where it was tuned, a sign of overfitting: simplify the rule (fewer conditions) and test again."))
        elif name == "Enough unseen trades to judge":
            have = _f(val) or 0
            out.append(_line("unseen_trades", name, _trades(have) + " on unseen data",
                             "at least %s" % _trades(backtest.GATES["min_oos_trades"]),
                             "%s: %s." % (_cap(_more(have, backtest.GATES["min_oos_trades"])), MORE_TRADES)))
        elif name == "Wins outweigh losses on unseen data":
            pf = _f(val)
            out.append(_line("profit_factor", name,
                             ("wins %.2f×%sthe losses" % (pf, NB)) if pf is not None else "no winning trades",
                             "at least %.1f×%sthe losses" % (backtest.GATES["min_profit_factor"], NB),
                             "Cut losing trades sooner (add a stop-loss) or skip the weakest entries."))
        elif name == "Worst drawdown on unseen data":
            out.append(_line("drawdown", name, _money(val) + " at the worst point", need,
                             "Lower the stake or hold fewer positions at once, or add a stop-loss."))
        elif name == "Has a real edge, not a coin flip":
            out.append(_line("real_edge", name, str(val), need,
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
    return _line("other", humanise(key), measured,
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
