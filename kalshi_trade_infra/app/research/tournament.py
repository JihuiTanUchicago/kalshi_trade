"""Paper tournament: every paper entrant trades at once, and a bandit moves a virtual book between them.

The research gate needs roughly 400-800 trades to see a 6-10c edge (gate-power curve, 2026-10-25),
and a single near miss forward-tests at a few trades a day. So paper runs every near miss in
parallel (agent.auto_paper_probation fills the slots) and this module referees:

  standings   per entrant, realistic paper round trips (live kernel over SimulatedVenue) grouped into
              events (five strikes of one 15m event are one bet) and turned into a return per dollar staked, shrunk toward zero (the honest prior for a strategy the
              gatekeeper rejected), and a Thompson draw of who is best. A cash arm (mean exactly 0)
              competes too, so the book sits in cash while nothing beats zero.
  book        a virtual TOURNAMENT_CAPITAL dollars split by those draws. Each round trip adds its
              P&L scaled from the entrant's own paper capital to the weight it held when the trip
              opened. Weights are snapshotted hourly (app_tournament_allocations), so the curve is
              forward-only: a trip never earns a weight chosen after it opened.
  verdicts    an entrant is retired when the data says so: after TOURNAMENT_MIN_TRIPS events
              with P(mean > 0) under ELIMINATE_P, or after DORMANT_DAYS with no trade at all (its
              entry rule never fires on the live book). Retiring frees a slot for the next near miss.
  pooled      all entrants' trips as one sample: does research's near-miss output earn money going
              forward? This is the sample that reaches the gate's 400+ trades in days, not months.

Paper only. Engine sizing is untouched: the bandit allocates virtual dollars, not contracts, because
a bigger paper stake adds no evidence and takes more of a thin book than live would. Nothing here
reads or changes the live gate (agent.paper_evidence, _is_deployment_candidate).

    python -m app.research.tournament --user 1
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

DDL = [
    """
    CREATE TABLE IF NOT EXISTS app_tournament_allocations (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id INT NOT NULL,
      snap_ts DATETIME NOT NULL,
      strategy_id INT NOT NULL,              -- 0 = the cash arm
      deployment_id INT NULL,
      weight DOUBLE NOT NULL,
      p_best DOUBLE NOT NULL,
      p_positive DOUBLE NULL,
      trips INT NOT NULL DEFAULT 0,
      post_mean DOUBLE NULL,                 -- posterior mean return per dollar staked
      post_sd DOUBLE NULL,
      INDEX idx_tourn_user_ts (user_id, snap_ts),
      INDEX idx_tourn_user_strat (user_id, strategy_id, snap_ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

TOURNAMENT_CAPITAL = float(os.getenv("APP_TOURNAMENT_CAPITAL", "10000"))
REBALANCE_EVERY = timedelta(minutes=int(os.getenv("APP_TOURNAMENT_REBALANCE_MINUTES", "60")))
# Shrinkage: the prior counts as PRIOR_TRIPS events at a mean of 0, so a lucky first few trades
# can't grab the book. Per-entrant sd is shrunk toward the pooled sd the same way, floored at SD_FLOOR
# (a binary contract's return per dollar staked has sd near 1; a tiny early sample understates it).
PRIOR_TRIPS = 10.0
SD_FLOOR = 0.5
EXPLORE = 0.2          # share of the book spread evenly over all arms, so no live entrant drops to 0
DRAWS = 4000
TOURNAMENT_MIN_TRIPS = int(os.getenv("APP_TOURNAMENT_MIN_TRIPS", "30"))
ELIMINATE_P = 0.05     # retire when P(mean > 0) falls below this after TOURNAMENT_MIN_TRIPS trips
DORMANT_DAYS = int(os.getenv("APP_TOURNAMENT_DORMANT_DAYS", "7"))
# A paper entrant the engine paused for one position stop is resumed after this long: the backtest
# (#122) exits a stopped position but keeps trading, so a pause would cut the forward sample short.
STOP_RESUME_AFTER = timedelta(hours=1)
POOLED_TARGET = 400    # the low end of what the gate needs to see a ~10c edge


def _now():
    from app import repository as repo
    return repo.now_utc()


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _capital(dep: Dict) -> float:
    """The entrant's own paper capital base, as the engine's loss guard defines it."""
    from app import engine
    try:
        return max(1e-9, float(engine._deployment_capital(dep)))
    except Exception:  # noqa: BLE001 - malformed spec: fall back to the default $5 x 20 book
        return 100.0


def _stake(dep: Dict) -> float:
    try:
        return max(1e-9, float(((dep.get("spec") or {}).get("sizing") or {}).get("stake") or 5.0))
    except (TypeError, ValueError):
        return 5.0


def is_probation(cur, dep: Dict) -> bool:
    from app.research import agent
    return dep.get("mode") == "paper" and not agent._is_deployment_candidate(cur, dep["strategy_id"])


# -- data ----------------------------------------------------------------------------------------

def entrants(cur, user_id: int, deps: Optional[List[Dict]] = None,
             trips_by: Optional[Dict[int, List[Dict]]] = None) -> List[Dict]:
    """Every paper deployment that hasn't been stopped, one per strategy (newest wins), each with its
    realistic round trips (oldest first) and its per-event returns per dollar staked. `deps` and
    `trips_by` are those reads already made (standings); without them each is read here."""
    from app.research import agent
    from app import repository as repo
    out, seen = [], set()
    if deps is None:
        deps = repo.list_deployments(cur, user_id, include_stopped=False)
    for d in deps:
        if d.get("mode") != "paper" or d["strategy_id"] in seen:
            continue
        seen.add(d["strategy_id"])
        trips = (trips_by.get(d["strategy_id"], []) if trips_by is not None
                 else repo.paper_round_trips(cur, user_id, d["strategy_id"]))
        stake = _stake(d)
        # One return per EVENT, not per trip: five strikes of one 15m event are one bet (the live
        # gate clusters the same way, #169), so correlated trips can't fake confidence.
        out.append(dict(d, trips=trips, returns=[p / stake for p in agent._trip_events(trips)]))
    return out


def save_snapshot(cur, user_id: int, ts, rows: List[Dict]) -> None:
    for r in rows:
        cur.execute(
            "INSERT INTO app_tournament_allocations (user_id, snap_ts, strategy_id, deployment_id, weight, p_best, "
            "p_positive, trips, post_mean, post_sd) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (user_id, ts, r["strategy_id"], r.get("deployment_id"), r["weight"], r["p_best"], r.get("p_positive"),
             r.get("trips", 0), r.get("post_mean"), r.get("post_sd")))


def last_snapshot_ts(cur, user_id: int):
    cur.execute("SELECT MAX(snap_ts) AS ts FROM app_tournament_allocations WHERE user_id=%s", (user_id,))
    row = cur.fetchone() or {}
    return row.get("ts")


def weight_history(cur, user_id: int) -> Dict[int, List[Tuple]]:
    """{strategy_id: [(snap_ts, weight), ...] oldest first} for every snapshot of this user."""
    cur.execute("SELECT strategy_id, snap_ts, weight FROM app_tournament_allocations WHERE user_id=%s "
                "ORDER BY snap_ts", (user_id,))
    out: Dict[int, List[Tuple]] = {}
    for r in cur.fetchall():
        out.setdefault(int(r["strategy_id"]), []).append((r["snap_ts"], float(r["weight"])))
    return out


def all_paper_trips(cur, user_id: int, deps: Optional[List[Dict]] = None,
                    trips_by: Optional[Dict[int, List[Dict]]] = None) -> List[Dict]:
    """Every realistic paper round trip of every strategy this user ever ran on paper, with the
    deployment it belongs to, for the book and the pooled sample (retired entrants included: dropping
    them would make the record look better than it was). `deps` (stopped ones included) and
    `trips_by` as in `entrants`."""
    from app import repository as repo
    out, seen = [], set()
    if deps is None:
        deps = repo.list_deployments(cur, user_id, include_stopped=True)
    for d in deps:
        if d.get("mode") != "paper" or d["strategy_id"] in seen:
            continue
        seen.add(d["strategy_id"])
        for t in (trips_by.get(d["strategy_id"], []) if trips_by is not None
                  else repo.paper_round_trips(cur, user_id, d["strategy_id"])):
            out.append(dict(t, strategy_id=d["strategy_id"], ret=t["pnl"] / _stake(d), capital=_capital(d)))
    out.sort(key=lambda t: (t.get("opened_at") is None, t.get("opened_at")))
    return out


# -- the bandit ----------------------------------------------------------------------------------

def _pooled_sd(entries: List[Dict]) -> float:
    xs = [x for e in entries for x in e["returns"]]
    if len(xs) < 2:
        return 1.0
    m = sum(xs) / len(xs)
    return max(SD_FLOOR, math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)))


def posterior(returns: List[float], pooled_sd: float) -> Tuple[float, float]:
    """(mean, sd) of the posterior on the mean return per dollar staked: a normal prior at 0 worth
    PRIOR_TRIPS trips, with the entrant's variance shrunk toward the pooled one."""
    n = len(returns)
    var0 = max(SD_FLOOR, pooled_sd) ** 2
    if n:
        m = sum(returns) / n
        ss = sum((x - m) ** 2 for x in returns)
    else:
        m, ss = 0.0, 0.0
    var = (ss + PRIOR_TRIPS * var0) / (max(n - 1, 0) + PRIOR_TRIPS)
    k = n + PRIOR_TRIPS
    return n * m / k, math.sqrt(max(var, SD_FLOOR ** 2) / k)


def allocate(entries: List[Dict], seed: str = "") -> List[Dict]:
    """Thompson allocation over the entrants plus a cash arm. Returns one row per arm (cash last)
    with p_best, weight (sums to 1), p_positive, posterior mean/sd and trips. Deterministic per seed."""
    psd = _pooled_sd(entries)
    arms = []
    for e in entries:
        mu, sd = posterior(e["returns"], psd)
        arms.append({"strategy_id": e["strategy_id"], "deployment_id": e.get("id"), "trips": len(e["returns"]),
                     "post_mean": mu, "post_sd": sd, "p_positive": _norm_cdf(mu / sd) if sd > 0 else 0.5})
    rng = random.Random("tournament:%s" % seed)
    wins = [0] * (len(arms) + 1)
    for _ in range(DRAWS):
        best, best_v = len(arms), 0.0  # the cash arm draws exactly 0
        for i, a in enumerate(arms):
            v = rng.gauss(a["post_mean"], a["post_sd"])
            if v > best_v:
                best, best_v = i, v
        wins[best] += 1
    k = len(arms) + 1
    out = []
    for i, a in enumerate(arms):
        p = wins[i] / DRAWS
        out.append(dict(a, p_best=p, weight=(1 - EXPLORE) * p + EXPLORE / k))
    p_cash = wins[-1] / DRAWS
    out.append({"strategy_id": 0, "deployment_id": None, "trips": 0, "post_mean": 0.0, "post_sd": 0.0,
                "p_positive": None, "p_best": p_cash, "weight": (1 - EXPLORE) * p_cash + EXPLORE / k})
    return out


def verdict(entry: Dict, arm: Dict, now) -> Optional[str]:
    """Why this entrant should be retired now, or None. Statistical death after enough trips, or
    dormancy (no trade at all after DORMANT_DAYS)."""
    n = arm["trips"]
    if n >= TOURNAMENT_MIN_TRIPS and arm["p_positive"] is not None and arm["p_positive"] < ELIMINATE_P:
        return ("after %d paper events it is %.0f%% likely to be losing money per event "
                "(posterior mean %+.1f%% of stake)" % (n, 100 * (1 - arm["p_positive"]), 100 * arm["post_mean"]))
    created = entry.get("created_at")
    # Dormancy judges an entry rule, so only an entrant that is actually running can be dormant: a
    # paused one (by its user or a guard) isn't trading at all. Its age counts from its last status
    # change, so a resumed entrant gets a fresh week.
    since = max(t for t in (created, entry.get("updated_at")) if t) if (created or entry.get("updated_at")) else None
    if n == 0 and entry.get("status") == "running" and since and now - since >= timedelta(days=DORMANT_DAYS):
        return "no trade in %d days on paper: its entry rule never fires on the live book" % DORMANT_DAYS
    return None


def _events(trips: List[Dict]) -> List[Dict]:
    """Trips grouped into events per strategy (agent._trip_event_key): summed return and P&L, closed
    when the event's last trip closed. Oldest event first."""
    from app.research import agent
    groups: Dict[Tuple, Dict] = {}
    for i, t in enumerate(trips):
        key = (t.get("strategy_id"), agent._trip_event_key(t, i))
        g = groups.setdefault(key, {"ret": 0.0, "pnl": 0.0, "closed_at": None})
        g["ret"] += t["ret"]
        g["pnl"] += t["pnl"]
        if t.get("closed_at") and (g["closed_at"] is None or t["closed_at"] > g["closed_at"]):
            g["closed_at"] = t["closed_at"]
    return list(groups.values())


def pooled(trips: List[Dict]) -> Dict:
    """All paper trips as one sample of EVENTS (`_events`): mean return per dollar staked, a normal-approx one-sided
    p that the mean is <= 0 (cheap enough for a polled panel; the gate itself bootstraps), the pace
    over the last 3 days and when the sample reaches POOLED_TARGET at that pace."""
    trips = _events(trips)
    xs = [t["ret"] for t in trips]
    n = len(xs)
    out = {"trips": n, "target": POOLED_TARGET, "net_pnl": round(sum(t["pnl"] for t in trips), 4),
           "mean_return": None, "p_value": None, "per_day": 0.0, "days_to_target": None}
    if n:
        m = sum(xs) / n
        out["mean_return"] = round(m, 4)
        if n >= 2:
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
            out["p_value"] = round(1 - _norm_cdf(m / (sd / math.sqrt(n))), 4) if sd > 0 else (0.0 if m > 0 else 1.0)
    now = _now()
    recent = [t for t in trips if t.get("closed_at") and now - t["closed_at"] <= timedelta(days=3)]
    out["per_day"] = round(len(recent) / 3.0, 1)
    if n < POOLED_TARGET and out["per_day"] > 0:
        out["days_to_target"] = round((POOLED_TARGET - n) / out["per_day"], 1)
    return out


def book(trips: List[Dict], history: Dict[int, List[Tuple]]) -> Dict:
    """The virtual book's realized curve: each trip's P&L scaled from its entrant's paper capital to
    the dollars the book held in it when the trip opened. Trips that opened before the entrant's
    first snapshot are left out, so every point is a forward result."""
    def weight_at(sid: int, ts) -> Optional[float]:
        w = None
        for snap_ts, weight in history.get(sid, []):
            if snap_ts > ts:
                break
            w = weight
        return w

    points, total, counted, daily = [], 0.0, 0, {}
    for t in sorted((t for t in trips if t.get("closed_at") and t.get("opened_at")), key=lambda t: t["closed_at"]):
        w = weight_at(t["strategy_id"], t["opened_at"])
        if w is None:
            continue
        pnl = t["pnl"] * (w * TOURNAMENT_CAPITAL) / t["capital"]
        total += pnl
        counted += 1
        points.append((t["closed_at"], round(total, 2)))
        day = t["closed_at"].date().isoformat() if hasattr(t["closed_at"], "date") else str(t["closed_at"])[:10]
        daily[day] = daily.get(day, 0.0) + pnl
    peak, dd = 0.0, 0.0
    for _ts, v in points:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return {"capital": TOURNAMENT_CAPITAL, "trips": counted, "pnl": round(total, 2),
            "return_pct": round(100 * total / TOURNAMENT_CAPITAL, 3), "max_drawdown": round(dd, 2),
            "daily": [(d, round(v, 2)) for d, v in sorted(daily.items())],  # realized P&L by UTC close day
            "curve": [(ts.isoformat() if hasattr(ts, "isoformat") else ts, v) for ts, v in points[-500:]]}


# -- the referee ---------------------------------------------------------------------------------

def standings(cur, user_id: int) -> Dict:
    """Read-only: current entrants with their allocation, plus the pooled sample and the book. Two
    reads feed both halves: the deployments (stopped ones included; the entrants are the others) and
    every paper strategy's round trips at once (repo.paper_round_trips_by_strategy). Each half read
    them again, and the trips one strategy at a time: 2 + 2x strategies statements per scoreboard."""
    from app import repository as repo
    now = _now()
    deps = repo.list_deployments(cur, user_id, include_stopped=True)
    trips_by = repo.paper_round_trips_by_strategy(
        cur, user_id, sorted({d["strategy_id"] for d in deps if d.get("mode") == "paper"}))
    ents = entrants(cur, user_id, [d for d in deps if d.get("status") != "stopped"], trips_by)
    arms = allocate(ents, seed="%s:%s" % (user_id, now.strftime("%Y%m%d%H")))
    by_sid = {e["strategy_id"]: e for e in ents}
    rows = []
    for a in arms:
        e = by_sid.get(a["strategy_id"])
        rows.append(dict(a, title=(e or {}).get("title") or ("Cash" if not a["strategy_id"] else ""),
                         market=(e or {}).get("market"), status=(e or {}).get("status"),
                         net_pnl=round(sum(t["pnl"] for t in (e or {}).get("trips", [])), 4),
                         verdict=verdict(e, a, now) if e else None))
    trips = all_paper_trips(cur, user_id, deps, trips_by)
    return {"entrants": rows, "pooled": pooled(trips), "book": book(trips, weight_history(cur, user_id)),
            "as_of": now.isoformat()}


def rebalance(cur, user: Dict, force: bool = False) -> List[str]:
    """Hourly: snapshot the allocation, retire entrants with a verdict and resume probation entrants
    the engine paused for a single position stop. Autopilot-on users only. Returns chat lines for
    what changed (nothing on a quiet hour)."""
    from app import repository as repo
    if not user.get("autopilot"):
        return []
    now = _now()
    last = last_snapshot_ts(cur, user["id"])
    if not force and last is not None and now - last < REBALANCE_EVERY:
        return []
    lines: List[str] = []
    for d in repo.list_deployments(cur, user["id"], include_stopped=False):
        reason = d.get("status_reason") or ""
        if (d.get("mode") == "paper" and d.get("status") == "paused" and reason.startswith("force-closed: position down")
                and "drawdown" not in reason and d.get("updated_at") and now - d["updated_at"] >= STOP_RESUME_AFTER
                and is_probation(cur, d)):
            if repo.set_deployment_status(cur, user["id"], d["id"], "running",
                                          "Tournament: resumed after a position stop (the stop closed the trade; "
                                          "the forward test keeps counting)"):
                lines.append("[tournament] Resumed paper entrant “%s” after a position stop. The stop closed that "
                             "trade and its loss counts; pausing would cut the forward sample short." % d.get("title"))
    ents = entrants(cur, user["id"])
    arms = allocate(ents, seed="%s:%s" % (user["id"], now.strftime("%Y%m%d%H")))
    by_sid = {e["strategy_id"]: e for e in ents}
    for a in arms:
        e = by_sid.get(a["strategy_id"])
        why = verdict(e, a, now) if e else None
        if why and e.get("status") == "running" and is_probation(cur, e) and repo.set_deployment_status(cur, user["id"], e["id"], "stopped",
                                                                        "Tournament: retired, " + why[:200]):
            # A pooled entrant runs one deployment per leg; retire the whole entrant, not one leg.
            for d in repo.list_deployments(cur, user["id"], include_stopped=False):
                if d["strategy_id"] == e["strategy_id"] and d["mode"] == "paper" and d["id"] != e["id"] \
                        and d.get("status") != "stopped":
                    repo.set_deployment_status(cur, user["id"], d["id"], "stopped", "Tournament: retired, " + why[:200])
            lines.append("[tournament] Retired paper entrant “%s”: %s. Its slot goes to the next near miss."
                         % (e.get("title"), why))
            a["weight_retired"] = a["weight"]
    live = [a for a in arms if "weight_retired" not in a]
    total = sum(a["weight"] for a in live) or 1.0
    for a in live:
        a["weight"] = a["weight"] / total
    save_snapshot(cur, user["id"], now, live)
    return lines


def latest_snapshot(cur, user_id: int) -> List[Dict]:
    cur.execute("SELECT strategy_id, weight, trips FROM app_tournament_allocations WHERE user_id=%s AND snap_ts="
                "(SELECT MAX(snap_ts) FROM app_tournament_allocations WHERE user_id=%s)", (user_id, user_id))
    return [{"strategy_id": int(r["strategy_id"]), "weight": float(r["weight"]), "trips": int(r["trips"] or 0)}
            for r in cur.fetchall()]


def panel_summary(cur, user_id: int, titles: Dict[int, str]) -> Optional[Dict]:
    """The autopilot panel's one-line view, from the last hourly snapshot (one query, no draws: the
    panel polls). None before the first snapshot or when no entrant is left."""
    rows = latest_snapshot(cur, user_id)
    ents = [r for r in rows if r["strategy_id"]]
    if not ents:
        return None
    lead = max(ents, key=lambda r: r["weight"])
    cash = next((r["weight"] for r in rows if not r["strategy_id"]), 0.0)
    return {"entrants": len(ents), "trips": sum(r["trips"] for r in ents), "target": POOLED_TARGET,
            "capital": TOURNAMENT_CAPITAL, "cash_weight": round(cash, 3),
            "leader": {"strategy_id": lead["strategy_id"], "title": titles.get(lead["strategy_id"]) or "",
                       "weight": round(lead["weight"], 3)}}


def context_lines(st: Dict, limit: int = 8) -> List[str]:
    """The tournament for the autopilot review: who holds the book, the pooled sample and the curve."""
    p, b = st["pooled"], st["book"]
    ents = [r for r in st["entrants"] if r["strategy_id"]]
    if not ents and not p["trips"]:
        return []
    cash = next((r for r in st["entrants"] if not r["strategy_id"]), None)
    out = ["Paper tournament (every paper entrant trades; a bandit splits a virtual $%.0f book by realized "
           "paper results; it retires losers itself, so do not pause entrants on a few bad trades):" % b["capital"]]
    for r in sorted(ents, key=lambda r: -r["weight"])[:limit]:
        out.append("- #%d %s (%s): %.0f%% of the book, %d events, net $%.2f, P(edge>0)=%.0f%%%s" % (
            r["strategy_id"], r["title"], r["market"], 100 * r["weight"], r["trips"], r["net_pnl"],
            100 * (r["p_positive"] or 0), ("; retiring: " + r["verdict"]) if r.get("verdict") else ""))
    if cash:
        out.append("- cash: %.0f%% of the book" % (100 * cash["weight"]))
    line = "Pooled forward sample: %d of %d independent events" % (p["trips"], p["target"])
    if p["mean_return"] is not None:
        line += ", mean %+.1f%% of stake per event" % (100 * p["mean_return"])
    if p["p_value"] is not None:
        line += ", p=%.2f" % p["p_value"]
    if p["days_to_target"] is not None:
        line += ", %.1f events/day, ~%.0f days to target" % (p["per_day"], p["days_to_target"])
    out.append(line + ". Book: $%.2f (%+.2f%%), max drawdown $%.2f over %d trips." % (
        b["pnl"], b["return_pct"], b["max_drawdown"], b["trips"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", type=int, required=True)
    a = ap.parse_args()
    from data_pipeline.common import get_db_conn
    conn = get_db_conn()
    try:
        st = standings(conn.cursor(), a.user)
    finally:
        conn.close()
    st["book"]["curve"] = st["book"]["curve"][-20:]
    print(json.dumps(st, indent=1, default=str))


if __name__ == "__main__":
    main()
