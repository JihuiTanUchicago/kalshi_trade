"""Research RSI, part 1: measure the research loop itself.

A loop can only improve what it measures. Each research run leaves its whole funnel in
app_agent_events: every idea it developed or dropped, every challenger kill, power pre-screen and
gate verdict. This module turns that into a scorecard per run and a scoreboard across runs:

  funnel     explored -> dropped on research data -> challenger/underpowered/not-finalist ->
             gated -> passed (+ holdout passes)
  spend      the run's model tokens priced at its model's list price
  deaths     why each dropped idea died, classified as
               pipeline  the pipeline failed the idea (a feature it thought was missing, no data, a
                         load error, a spec the validator rejected): engineering work, not evidence
                         about the market
               spec      the spec never traded (0 trades): usually a filter cut outside the data
               edge      the market killed it (loses money, fee floor, mechanism falsified)
               fit       the mechanism cannot work on this market's structure (a GBM on a game
                         outcome, a time-series idea on snapshot data): the proposer should have known
               other     anything the rules don't recognise
  efficiency gated ideas and passes per $100, pipeline share of deaths

Read-only. The scoreboard reads labels and counts only; no held-out number is computed here.

    python -m app.rsi --days 7 [--user 2]
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from app.markets import MARKETS

# (tag, kind, pattern) checked in order; the first match wins. Built from the drop reasons of real
# runs (2531, 2563, 2613): the proposer explains a drop in prose, so these are phrase patterns.
_DROP_RULES: Tuple[Tuple[str, str, str], ...] = (
    # the spec validator (or the proposer's reply parser) rejected the idea before it was tested
    ("spec_invalid", "pipeline",
     r"spec invalid|could not be used|unknown field|is not a known feature|spec must be"),
    ("feature_unavailable", "pipeline",
     r"not available|unavailable|unpopulated|not populated|isn't available|is not visible|not visible in"
     r"|(feature|column)s? (is |are )?(missing|null|empty|sparse)|cannot confirm .{0,40}(feature|populated|available)"
     r"|no (such )?feature|isn't a feature|not a (strategy )?feature"),
    ("no_data", "pipeline",
     r"no settled|no data|no history|failed to load|could not load|timed? ?out|load error|no contracts"),
    ("zero_trades", "spec", r"\b0 trades|zero trades|no trades|never (fires|trades|enters)|took no trades"),
    ("fee_floor", "edge", r"fee floor|below the fee|fees? (eat|kill|exceed|swamp)|dead on arrival|can'?t beat the fee"),
    ("loses", "edge",
     r"loses|lost \$|losing|negative (p&?l|pnl|edge|return)|worse than random|-\d+(\.\d+)?c ?/ ?trade"
     r"|falsif|disprov|backward|no edge|calibrated within noise"),
    # From the 80-reason sample of run 2026-10-22..24 "other" deaths (688 of 1620 drops).
    ("missing_context", "pipeline",   # information the market's frames never carry (game state, books)
     r"game[- ]state|does not (expose|populate|report|include|carry)|no (live )?(game|score|team|injury|lineup|sportsbook)"
     r"|(features?|feature set|data) (contains?|has|have|provides?) no|not (exposed|reported)|without (time-series|game|score)"
     r"|no (independent )?fair[- ]value benchmark|requires knowing|feature set|available features"
     r"|not (appear to be |be )?(native or )?(reliably )?populated"),
    ("thin_sample", "spec",           # the regime the idea needs is (almost) absent from the research window
     r"too (few|small|little|sparse)|insufficient|only \d+ (trades|outcomes|contracts|observations)|sample size"
     r"|fires in <|<\s?\d+(\.\d+)?% of|unfalsifiable|p90 (of [a-z_ ]+)?(is|=)|no [a-z0-9 -]{0,30}data (is |in )"
     r"|all snapshots have|\d+(th|st|nd) percentile|research window \("),
    ("no_signal", "edge",             # tested, and the research fold shows nothing
     r"zero (wins|predictive)|\b0(\.\d+)?% win|\b\d+/\d+ wins|catastrophic|found essentially none|near-zero weight"
     r"|no meaningful|contradict|-\$\d|win rate .{0,20}(\d|\.)|essentially zero|null \(all|mid-only"
     r"|however,? (the )?(research|market) (data|fold|window|result)|(research|market) data (reveals|shows)"),
    ("wrong_fit", "fit",              # the mechanism cannot work on this market's structure: a proposer miss
     r"incompatible|does(n't| not) (apply|fit|work)|cannot work|structural(ly)? (mismatch|unsound|invalid)|mismatch"
     r"|misaligned|inverted|backwards|conflat|circular|tautolog|contradictory|internally|overfit|fundamentally"
     r"|not grounded|confuses|ambiguous|nonsensical|not a standard|fatal|does not support|functionally"
     r"|atomic|continuous(ly)? (observable|order|underlying)|facts kill"),
)
_COMPILED = tuple((tag, kind, re.compile(pat, re.I)) for tag, kind, pat in _DROP_RULES)
KINDS = ("pipeline", "spec", "edge", "fit", "other")


def classify_drop(why: Optional[str]) -> Tuple[str, str]:
    """(tag, kind) for one dropped idea's reason; ("other", "other") when no rule matches."""
    text = why or ""
    for tag, kind, rx in _COMPILED:
        if rx.search(text):
            return tag, kind
    return "other", "other"


# What an idea's TITLE says it trades on, coarse enough that the same idea under a new name lands in
# the same bucket. First match wins, so a "logistic mean-reversion classifier" is mean reversion, and
# the generic learned-recalibration bucket only catches what names no mechanism at all. Measured on
# 2026-10-24's crypto drops: four of these buckets held ~80% of all drops, each across 4-10 markets.
MECHANISMS = (
    ("favorite-longshot / calibration", r"favou?rite.?longshot|longshot|calibrat"),
    ("terminal pinning / convergence near expiry",
     r"pinning|\bpin\b|terminal|convergence|near.?expiry|(final|last) \d+(-\d+)? min"),
    ("volatility mispricing (vol scale / regime / GARCH)",
     r"vol(atility)?[ -](mispric|overpric|underpric|overestimat|underestimat|regime|compression|crush|scale"
     r"|decay|expansion|forecast|clustering)|garch|realized vol|vol_scale|vol scale"),
    ("mean reversion after a move", r"mean.?revers|revert|reversal|anti.?momentum|overshoot|fade"),
    ("momentum / drift continuation", r"momentum|drift|continuation|trend"),
    ("cross-asset lead-lag / pairs", r"lead.?lag|\bpairs?\b|cross.?(market|asset)|relative.?value|spread z"),
    ("order-book / flow microstructure", r"order.?book|imbalance|\bflow\b|quote|volume burst|bid.?ask size"),
    ("session / time-of-day filter", r"session|overnight|time.?of.?day|weekend|\basia"),
    ("generic learned recalibration (logistic / multi-factor)", r"logistic|classifier|multi.?factor|ridge"),
)
_MECH_RX = tuple((name, re.compile(rx, re.I)) for name, rx in MECHANISMS)


def mechanism(title: Optional[str]) -> Optional[str]:
    """The MECHANISMS bucket an idea's title names, or None when it names none of them."""
    for name, rx in _MECH_RX:
        if rx.search(title or ""):
            return name
    return None


def family(market: Optional[str]) -> str:
    """The market family a run belongs to (lessons and allocation are per family, not per city):
    weather splits into daily highs and lows; everything else is its catalog category."""
    m = MARKETS.get(market or "")
    if m is None:
        return "unknown"
    series = (m.series or "").upper()
    if series.startswith("KXHIGH"):
        return "weather-high"
    if series.startswith("KXLOWT"):
        return "weather-low"
    cat = (m.category or "").strip().lower()
    if not cat:
        return "crypto" if m.underlying else "other"
    return re.sub(r"[^a-z0-9]+", "-", cat).strip("-")


def run_cost_usd(run: Dict, screen: Optional[Dict] = None) -> float:
    """The run's model spend at list price (what the user is billed). `screen` is the run's
    `screen` verdict payload: its tokens are part of the run's totals but priced at the screen
    model's rate (services.research_screen)."""
    from app import billing
    from app import models_catalog as catalog
    from app.services.research_screen import screen_cost_split
    try:
        model_id = catalog.resolve(run.get("model")).model_id
    except Exception:  # noqa: BLE001 - an unknown model prices at the default
        model_id = ""
    parts = screen_cost_split(model_id, int(run.get("input_tokens") or 0), int(run.get("output_tokens") or 0),
                              screen)
    return float(sum(billing.usage_cost(m, i, o) for m, i, o in parts))


def run_card(run: Dict, events: Iterable[Dict]) -> Dict:
    """One run's scorecard from its events (each {kind, message, data})."""
    f = Counter()
    deaths: Counter = Counter()
    kinds: Counter = Counter()
    pipeline: List[Dict] = []
    screen: Optional[Dict] = None
    leads_arm: Optional[str] = None
    for ev in events:
        if ev.get("kind") != "verdict":
            continue
        d = ev.get("data") or {}
        msg = ev.get("message") or ""
        phase = d.get("phase")
        if phase == "screen":
            screen = d
        elif phase == "leads":
            leads_arm = d.get("arm")
        elif d.get("status") == "abandoned":
            f["dropped"] += 1
            tag, kind = classify_drop(d.get("why") or msg)
            deaths[tag] += 1
            kinds[kind] += 1
            if kind == "pipeline":
                pipeline.append({"tag": tag, "title": (d.get("title") or "")[:120],
                                 "why": (d.get("why") or msg)[:300]})
        elif phase == "holdout":
            f["holdout_passed" if d.get("classification") == "forward_validated" else "holdout_other"] += 1
        elif phase == "forward":
            f["deploy_candidates"] += d.get("classification") == "deployment_candidate"
        elif d.get("classification"):
            f["gated"] += 1
            f["passed"] += d.get("status") == "passed"
        elif "power" in d:
            f["underpowered"] += 1
        elif msg.startswith("REJECTED (challenger)"):
            f["challenger_rejected"] += 1
        elif "not a finalist" in msg:
            f["not_finalist"] += 1
    # A run that FAILED on an unusable proposer reply never logged its ideas: count it as a bug death.
    if run.get("status") == "failed" and classify_drop(run.get("error"))[0] == "spec_invalid":
        f["spec_failed_runs"] += 1
    developed = f["gated"] + f["underpowered"] + f["challenger_rejected"] + f["not_finalist"]
    explored = max(developed + f["dropped"], int(run.get("hypotheses_tried") or 0))
    cost = run_cost_usd(run, screen) if screen else run_cost_usd(run)
    return {
        "run_id": run.get("id"), "user_id": run.get("user_id"), "market": run.get("market"),
        "family": family(run.get("market")), "status": run.get("status"),
        "created_at": str(run.get("created_at") or ""), "cost_usd": round(cost, 4),
        "explored": explored, "developed": developed, "dropped": f["dropped"],
        "challenger_rejected": f["challenger_rejected"], "underpowered": f["underpowered"],
        "not_finalist": f["not_finalist"], "gated": f["gated"], "passed": f["passed"],
        "holdout_passed": f["holdout_passed"], "deploy_candidates": f["deploy_candidates"],
        "deaths": dict(deaths), "death_kinds": {k: kinds[k] for k in KINDS if kinds[k]},
        "pipeline_deaths": pipeline, "spec_failed_runs": f["spec_failed_runs"],
        # model-tiering A/B arm (None = the run predates it, or ended before logging it)
        "arm": screen.get("arm") if screen else None,
        "leads_arm": leads_arm,  # data-first A/B arm (services.research_leads)
        "screen": {k: screen.get(k) for k in ("screen_model", "screened_out", "handed_over", "audits", "rescued")}
        if screen else None,
    }


def _rollup(cards: List[Dict]) -> Dict:
    tot = Counter()
    deaths: Counter = Counter()
    kinds: Counter = Counter()
    for c in cards:
        for k in ("explored", "developed", "dropped", "gated", "passed", "holdout_passed", "deploy_candidates"):
            tot[k] += c[k]
        tot["cost_cents"] += round(100 * c["cost_usd"])
        tot["spec_failed_runs"] += c.get("spec_failed_runs", 0)
        deaths.update(c["deaths"])
        kinds.update(c["death_kinds"])
    cost = tot["cost_cents"] / 100.0
    per100 = (100.0 / cost) if cost > 0 else None
    return {
        "runs": len(cards), "cost_usd": round(cost, 2), "explored": tot["explored"],
        "developed": tot["developed"], "dropped": tot["dropped"], "gated": tot["gated"],
        "passed": tot["passed"], "holdout_passed": tot["holdout_passed"],
        "deploy_candidates": tot["deploy_candidates"],
        "gate_reach_rate": round(tot["gated"] / tot["explored"], 3) if tot["explored"] else None,
        "pass_rate": round(tot["passed"] / tot["explored"], 3) if tot["explored"] else None,
        "gated_per_100usd": round(tot["gated"] * per100, 2) if per100 else None,
        "passed_per_100usd": round(tot["passed"] * per100, 2) if per100 else None,
        "pipeline_death_share": round(kinds["pipeline"] / tot["dropped"], 3) if tot["dropped"] else None,
        # infrastructure bugs: ideas the validator/parser killed, plus whole runs it failed
        "spec_invalid_deaths": deaths["spec_invalid"], "spec_failed_runs": tot["spec_failed_runs"],
        "bug_death_rate": round(deaths["spec_invalid"] / tot["dropped"], 3) if tot["dropped"] else None,
        "death_kinds": {k: kinds[k] for k in KINDS if kinds[k]},
        "top_deaths": deaths.most_common(5),
    }


def fix_list(cards: List[Dict], limit: int = 15) -> List[Dict]:
    """Ideas the PIPELINE killed (not the market), newest first, grouped by tag: the engineering
    backlog the loop hands back, with one example reason per (tag, market) so a fix can be aimed."""
    seen: Dict[Tuple[str, str], Dict] = {}
    for c in reversed(cards):
        for p in c.get("pipeline_deaths") or []:
            key = (p["tag"], c["market"])
            if key in seen:
                seen[key]["count"] += 1
            else:
                seen[key] = {"tag": p["tag"], "market": c["market"], "family": c["family"], "count": 1,
                             "latest_run": c["run_id"], "example": p["why"], "title": p["title"]}
    return sorted(seen.values(), key=lambda r: -r["count"])[:limit]


def scoreboard(cards: List[Dict]) -> Dict:
    """Totals, per family and per day (oldest first) over run cards, so a trend is visible."""
    by_family: Dict[str, List[Dict]] = defaultdict(list)
    by_day: Dict[str, List[Dict]] = defaultdict(list)
    for c in cards:
        by_family[c["family"]].append(c)
        by_day[c["created_at"][:10]].append(c)
    return {
        "total": _rollup(cards),
        "families": {k: _rollup(v) for k, v in sorted(by_family.items())},
        "days": [dict(day=k, **_rollup(v)) for k, v in sorted(by_day.items())],
        "fix_list": fix_list(cards),
        "trend": trend(cards),
    }


def trend(cards: List[Dict], min_ideas: int = 8) -> Optional[Dict]:
    """Is research getting better? Gate-reach rate of the newer half of runs vs the older half
    (split by ideas explored, so a few huge runs cannot hide in one side). None until each half
    has min_ideas ideas."""
    total = sum(c["explored"] for c in cards)
    if total < 2 * min_ideas:
        return None
    seen, split = 0, len(cards)
    for i, c in enumerate(cards):
        seen += c["explored"]
        if seen * 2 >= total:
            split = i + 1
            break
    old, new = _rollup(cards[:split]), _rollup(cards[split:])
    if old["explored"] < min_ideas or new["explored"] < min_ideas:
        return None
    return {"before": {k: old[k] for k in ("runs", "explored", "gated", "gate_reach_rate", "cost_usd")},
            "after": {k: new[k] for k in ("runs", "explored", "gated", "gate_reach_rate", "cost_usd")},
            "better": new["gate_reach_rate"] > old["gate_reach_rate"]}


def recent_runs(cur, days: int = 7, user_id: Optional[int] = None) -> List[Dict]:
    sql = ("SELECT id, user_id, market, status, error, model, hypotheses_tried, strategies_passed, input_tokens, "
           "output_tokens, created_at FROM app_agent_runs WHERE kind='research' "
           "AND created_at >= UTC_TIMESTAMP() - INTERVAL %s DAY AND status IN ('succeeded','stopped','failed')")
    args: List = [int(days)]
    if user_id is not None:
        sql += " AND user_id=%s"
        args.append(int(user_id))
    cur.execute(sql + " ORDER BY id", args)
    return list(cur.fetchall())


def verdict_events(cur, run_ids: List[int]) -> Dict[int, List[Dict]]:
    out: Dict[int, List[Dict]] = defaultdict(list)
    for i in range(0, len(run_ids), 200):
        chunk = run_ids[i:i + 200]
        cur.execute("SELECT run_id, kind, message, data_json FROM app_agent_events WHERE kind='verdict' "
                    "AND run_id IN (%s) ORDER BY id" % ",".join(["%s"] * len(chunk)), chunk)
        for r in cur.fetchall():
            data = r.get("data_json")
            if isinstance(data, (bytes, str)):
                try:
                    data = json.loads(data)
                except ValueError:
                    data = None
            out[r["run_id"]].append({"kind": r["kind"], "message": r["message"], "data": data or {}})
    return out


def load_scoreboard(cur, days: int = 7, user_id: Optional[int] = None) -> Dict:
    runs = recent_runs(cur, days, user_id)
    events = verdict_events(cur, [r["id"] for r in runs])
    cards = [run_card(r, events.get(r["id"], [])) for r in runs]
    return dict(scoreboard(cards), days_back=days, cards=cards)


def _playbook_of(cur, strategy_ids: List[int]) -> Dict[int, int]:
    """{strategy_id: playbook_id} for strategies whose research run drew a playbook."""
    if not strategy_ids:
        return {}
    try:
        cur.execute("SELECT s.id AS strategy_id, a.playbook_id FROM app_strategies s "
                    "JOIN app_rsi_assignments a ON a.run_id=s.run_id WHERE s.id IN (%s)"
                    % ",".join(["%s"] * len(strategy_ids)), list(strategy_ids))
        return {int(r["strategy_id"]): int(r["playbook_id"]) for r in cur.fetchall()}
    except Exception:  # noqa: BLE001 - the assignments table may not exist before the first schema run
        return {}


# Paper pace: a running paper strategy that trades far below the rate it traded at in research is
# more often a live/research mismatch than a rare setup (KXNFL1HSPREAD #81 measured time to expiry
# against a close two days late and could never enter, 2026-10-25). Flag it once its research pace
# predicted PACE_MIN_EXPECTED+ trips by now and seeing this few has Poisson p < PACE_MAX_P.
PACE_MIN_EXPECTED = 5.0
PACE_MAX_P = 0.01


def _poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) for X ~ Poisson(lam)."""
    term = total = math.exp(-lam)
    for i in range(1, k + 1):
        term *= lam / i
        total += term
    return min(1.0, total)


def paper_pace(dep: Dict, trips: int, now=None) -> Optional[Dict]:
    """Expected paper trips by now at the strategy's research pace (in_sample trades_per_day over
    the hours since this deployment was created) and the chance of seeing `trips` or fewer.
    `behind` only for a running deployment past both thresholds. None without a research pace."""
    from datetime import datetime, timezone
    per_day = ((dep.get("result") or {}).get("in_sample") or {}).get("trades_per_day")
    created = dep.get("created_at")
    if not per_day or not isinstance(created, datetime):
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    hours = max(0.0, (now - created.replace(tzinfo=None)).total_seconds() / 3600.0)
    expected = float(per_day) * hours / 24.0
    p = _poisson_cdf(int(trips), expected)
    behind = dep.get("status") == "running" and expected >= PACE_MIN_EXPECTED and p < PACE_MAX_P
    return {"expected": round(expected, 1), "hours": round(hours, 1), "p": round(p, 4), "behind": behind}


def paper_eta_days(dep: Dict, trips: int, now=None) -> Optional[float]:
    """Days until this paper strategy could have the record the live gate counts (enough realistic
    trips and enough hours of record) at the pace it trades: its own paper pace once it has 3+
    trips, else its research pace. Says nothing about whether it will be up by then. None without
    a pace."""
    from datetime import datetime, timezone
    from app import agent
    created = dep.get("created_at")
    if not isinstance(created, datetime):
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    hours = max(0.0, (now - created.replace(tzinfo=None)).total_seconds() / 3600.0)
    if trips >= 3 and hours > 0:
        per_day = trips / hours * 24.0
    else:
        per_day = float(((dep.get("result") or {}).get("in_sample") or {}).get("trades_per_day") or 0)
    if per_day <= 0:
        return None
    days = max(0, agent.MIN_REALISTIC_PAPER_TRADES - int(trips)) / per_day
    return round(max(days, max(0.0, agent.MIN_PAPER_SPAN_HOURS - hours) / 24.0), 1)


def _paper_rollup(rows: List[Dict]) -> Dict:
    trips = sum(r["round_trips"] for r in rows)
    net = sum(r["net_pnl"] for r in rows)
    # Trip-weighted backtest expectation: what these trips "should" have earned per the backtest's
    # unseen-data P&L per trade. Realization = paper net / that; None until something traded.
    expected = sum(r["round_trips"] * r["backtest_per_trade"] for r in rows if r["backtest_per_trade"])
    return {
        "strategies": len(rows), "trading": sum(1 for r in rows if r["round_trips"]),
        "round_trips": trips, "net_pnl": round(net, 4),
        "realization": round(net / expected, 3) if expected > 0 else None,
        "live_ready": sum(1 for r in rows if r["live_ready"]),
        # For strategies that never traded: the entry check the engine last saw no contract clear
        # (spec.entry_scan). Tells research which part of its specs the live book never reaches.
        "stuck_on": dict(Counter(r["stuck_on"] for r in rows if not r["round_trips"] and r.get("stuck_on"))),
        # Running strategies trading far below their research pace (paper_pace): (id, trips, expected).
        "behind_pace": [(r["strategy_id"], r["round_trips"], r["pace"]["expected"])
                        for r in rows if (r.get("pace") or {}).get("behind")],
    }


def paper_outcomes(cur, user_id: int) -> Dict:
    """RSI part 3: what research's passes earned once they met the live book on paper. The other
    half of the loop's scorecard: the scoreboard counts what passed the backtest gate, this counts
    what survived realistic fills (the live kernel over SimulatedVenue). Per family (same keys as
    the scoreboard) and per playbook (via the run that produced each strategy), so a playbook that
    yields gate passes which then bleed on paper stops looking like a winner.

    Read-only. Strategies with too few trips to clear the paper gate skip the (bootstrap) live-ready
    check, so this stays cheap enough for the panel."""
    from app import agent
    from app import repository as repo
    deps = [d for d in repo.list_deployments(cur, user_id, include_stopped=True) if d.get("mode") == "paper"]
    by_strategy: Dict[int, Dict] = {}
    for d in deps:
        by_strategy.setdefault(int(d["strategy_id"]), d)
    ids = sorted(by_strategy)
    progress = repo.paper_progress(cur, user_id, ids)
    playbooks = _playbook_of(cur, ids)
    rows = []
    for sid in ids:
        d = by_strategy[sid]
        trips, net = progress.get(sid, (0, 0.0))
        oos = (d.get("result") or {}).get("out_of_sample") or {}
        n_bt = int(oos.get("trades") or 0)
        ready = False
        if trips >= agent.MIN_REALISTIC_PAPER_TRADES:
            try:
                ready = bool(agent.paper_evidence(cur, user_id, sid)["ready"])
            except Exception:  # noqa: BLE001 - informational; never fail the scoreboard
                ready = False
        rows.append({"strategy_id": sid, "family": family(d.get("market")), "playbook_id": playbooks.get(sid),
                     "round_trips": int(trips), "net_pnl": float(net),
                     "backtest_per_trade": float(oos.get("pnl") or 0) / n_bt if n_bt else None,
                     "live_ready": ready, "stuck_on": (d.get("scan") or {}).get("blocked_at"),
                     "pace": paper_pace(d, trips)})
    fams: Dict[str, List[Dict]] = defaultdict(list)
    pbs: Dict[int, List[Dict]] = defaultdict(list)
    for r in rows:
        fams[r["family"]].append(r)
        if r["playbook_id"] is not None:
            pbs[r["playbook_id"]].append(r)
    return {
        "total": _paper_rollup(rows),
        "families": {k: _paper_rollup(v) for k, v in sorted(fams.items())},
        "by_playbook": {k: _paper_rollup(v) for k, v in sorted(pbs.items())},
    }


def paper_outcomes_lines(outcomes: Dict) -> List[str]:
    """One line per family for the autopilot review: did research's passes hold up on paper?"""
    out = []
    for fam, r in (outcomes.get("families") or {}).items():
        line = "- %s: %d on paper, %d trading, %d realistic round trips, net $%.2f" % (
            fam, r["strategies"], r["trading"], r["round_trips"], r["net_pnl"])
        if r["realization"] is not None:
            line += ", paper earns %.0f%% of backtest per trade" % (100 * r["realization"])
        if r["live_ready"]:
            line += ", %d live-ready" % r["live_ready"]
        if r["strategies"] and not r["trading"]:
            line += " (none has traded yet: their entry rules may never fire on the live book)"
        if r.get("stuck_on"):
            line += "; untraded ones last stopped at: %s" % ", ".join(
                "%s (%d)" % (k, n) for k, n in sorted(r["stuck_on"].items(), key=lambda kv: -kv[1]))
        if r.get("behind_pace"):
            line += "; FAR BELOW RESEARCH PACE (check the live book shows what research saw): %s" % ", ".join(
                "#%d %d trips vs ~%.0f expected" % (sid, n, exp) for sid, n, exp in r["behind_pace"])
        out.append(line)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--user", type=int, default=None)
    ap.add_argument("--cards", action="store_true", help="include one scorecard per run")
    a = ap.parse_args()
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    try:
        board = load_scoreboard(conn.cursor(), a.days, a.user)
    finally:
        conn.close()
    if not a.cards:
        board.pop("cards")
    print(json.dumps(board, indent=1, default=str))


if __name__ == "__main__":
    main()
