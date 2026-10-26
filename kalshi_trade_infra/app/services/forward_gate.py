"""The paper forward gate: one pre-registered judgment of a probation strategy on its paper fills.

Todd's decision (2026-10-25): a validation near miss trading on paper probation could never become
a pass, because its only validation verdict is frozen (usually underpowered) and the holdout needs
STAT_SUPPORTED. Each autopilot review, this looks at the user's paper-tested strategies and asks
the gatekeeper (gatekeeper.judge_paper_forward, which holds the integrity rules) to judge any whose
realistic paper record has reached its experiment's min_sample. That happens once per experiment.

A FORWARD_VALIDATED verdict goes through the same diversification check as a holdout pass
(gatekeeper.marginal_contribution_ok). If that check promotes it to DEPLOYMENT_CANDIDATE, the
strategy is marked passed. Going live still takes the user's live switch and paper_evidence.

Env: APP_PAPER_FORWARD_GATE=1 turns it on (off by default).
"""
from __future__ import annotations

import os
from typing import Dict, List

from app.research import gatekeeper
from app import repository as repo
from app.research import research_repository as rr

ENABLED = os.getenv("APP_PAPER_FORWARD_GATE", "0") == "1"


def _paper_experiments(cur, user_id: int) -> List[Dict]:
    """Every strategy this user has paper-traded that has a pre-registered experiment, once each,
    oldest deployment first: [{strategy, experiment}]."""
    seen, out = set(), []
    deps = sorted(repo.list_deployments(cur, user_id, include_stopped=True), key=lambda d: d["id"])
    for d in deps:
        sid = d["strategy_id"]
        if d["mode"] != "paper" or sid in seen:
            continue
        seen.add(sid)
        strat = repo.get_strategy(cur, user_id, sid)
        rec = rr.experiments_for_strategy(cur, sid, strat.get("experiment_id")) if strat else None
        if rec:
            out.append({"strategy": strat, "experiment": rec["experiment"]})
    return out


def run(cur, user: Dict) -> List[str]:
    """Judge every paper-tested strategy whose record just reached min_sample. Returns chat lines."""
    if not (ENABLED and user.get("autopilot")):
        return []
    uid = int(user["id"])
    entrants = _paper_experiments(cur, uid)
    # Every paper-tested strategy competes for the same forward evidence, so all of them deflate
    # each verdict's DSR, judged or not.
    n_trials = max(1, len(entrants))
    lines = []
    for e in entrants:
        strat, exp = e["strategy"], e["experiment"]
        trades = gatekeeper.paper_trades(repo.paper_fills_for_gate(cur, uid, strat["id"]))
        v = gatekeeper.judge_paper_forward(cur, int(exp["id"]), trades, n_trials)
        if v is None:
            continue
        stats_txt = "%d paper trades, p=%.3f, %s per trade" % (
            v["n_trades"], v["p_value"], "%+.1f%%" % (100 * (v.get("mean_net_return") or 0)))
        if v["classification"] != gatekeeper.Classification.FORWARD_VALIDATED.value:
            lines.append("Paper forward gate: %s did not pass its one paper judgment (%s, %s)."
                         % (strat["title"], v["classification"], stats_txt))
            continue
        ok, why = gatekeeper.marginal_contribution_ok(
            cur, uid, int(exp["id"]), {"market": exp["market"], "spec": exp["spec"]})
        if not ok:
            lines.append("Paper forward gate: %s passed on paper (%s) but stays off the candidate list: %s."
                         % (strat["title"], stats_txt, why))
            continue
        repo.set_strategy_outcome(cur, strat["id"], "passed", strat.get("result"), int(exp["id"]))
        repo.add_notification(cur, uid, "passed",
                              "“%s” passed the paper forward gate and is a deployment candidate." % strat["title"][:120],
                              "/strategies/%d" % strat["id"])
        lines.append("Paper forward gate: %s PASSED (%s) and is now a deployment candidate. Live still "
                     "needs your live switch." % (strat["title"], stats_txt))
    return lines
