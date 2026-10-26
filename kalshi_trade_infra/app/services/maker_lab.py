"""The market-making research loop (paper only): the model proposes quoting policies, the replay
scores them on research hours, the model refines them, and one finalist is judged once on hours it
never saw.

    python -m app.maker_lab_run --series KXBTCD --hours 48 --holdout 16

Split: the newest ``holdout`` archived hours are held out; the ``hours`` before them are research.
The model sees research results only. Round 0 scores a few fixed baselines so it starts from
measured numbers; each later round it proposes ``per_round`` policies with the earlier results in
view. The finalist is the research policy with the highest hour-clustered t (positive mean, enough
fills), or none.

Gate (maker_policy.hour_stats rows, the hour as the unit, scored at pool 0 because no Bitcoin
series carries a rewards pool yet): at least MIN_HOURS active hours and MIN_FILLS fills, the
stationary-bootstrap one-sided p of the hourly markout mean at or below alpha, and a positive mean
after the maker fee Kalshi would charge if the series started charging makers (fee stress). alpha is
GATE_ALPHA divided by the number of finalists already judged on overlapping held-out hours (the
ledger), so rerunning the lab on the same window cannot buy a pass. The break-even pool is reported
either way: once Bitcoin pools post, a policy that loses a little and earns a big share can pay.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence

from app import stats
from app.llm import ModelFn, Usage, ask_json
from trading_core.engine import maker_policy as mr

GATE_ALPHA = 0.05
MIN_HOURS = 12
MIN_FILLS = 200
ROUND0 = ("join_touch", "spot_fair_2c", "spot_fair_2c_pull")

SYSTEM = """You are a quantitative researcher designing PASSIVE market-making policies for Kalshi Bitcoin
binary contracts. Every policy only rests buy orders (a YES bid and a NO bid, which is a YES offer) and
never crosses the spread. It is judged on a queue-aware replay of the real per-second order books:
our orders join the back of their price level and fill only when real prints eat the queue ahead.

How a policy is scored, per UTC hour:
- markout: for every fill, the mid 60 seconds later minus the price paid, times contracts, minus fees.
  This is the cost of adverse selection (informed takers hitting us before the price moves). It is the
  number to make positive. Inventory P&L past 60 s is outcome noise and is not scored.
- reward share: Kalshi pays a liquidity-rewards pool per market for resting size near the touch (both
  sides needed, size deeper than the touch discounted by half per cent). Shown as the pool-dollars the
  policy would earn at $1 per contract-hour. No Bitcoin series has a pool today; Kalshi has filed to
  allow pools of up to $10,000 a day per market from Oct 28. break-even pool = the pool per
  contract-hour at which the policy pays.
- statistics treat each hour as one observation; t = mean / standard error over hours.

Levers (all optional; omitted ones keep their defaults):
  series: KXBTC15M (15-minute up/down, one contract open at a time, very deep touch),
          KXBTCD (hourly above/below strikes, ~130 strikes), KXBTC (hourly ranges)
  quote_size (contracts per side, default 100), max_inventory (|YES - NO| cap, default 500)
  fair_source: "mid" (default), "micro" (book microprice), "spot" (probability implied by the
          cross-exchange BTC price and realized volatility; single-strike contracts only, falls back to mid)
  min_edge (dollars per contract a quote must sit below fair; default 0), back_off (true: a side short
          of min_edge rests at fair - min_edge instead of being dropped)
  offset_ticks (rest N cents behind the touch), improve_min_spread_ticks (step 1c inside a spread of
          at least N cents; 0 = never), skew_ticks (at full inventory, the side adding to it rests N
          cents further back, linear in fill level)
  mid_band [lo, hi] (quote only contracts whose mid is inside), pull_before_close_s (default 60),
          max_secs_to_close (skip contracts further from close)
  pull_move_bp + pull_cooldown_s + move_window_s (1, 10 or 60): pull a contract's quotes for the
          cooldown after BTC moves that many basis points over the window
  max_touch_size (skip a side whose touch queue is deeper), contract_loss_limit (bench a contract
          whose fills cost more than this many dollars; it then only unwinds)

Think about WHERE adverse selection comes from (spot moves the Kalshi book lags, the last minutes before
close, cheap tails) and which lever removes it while keeping fills. A policy that fills rarely cannot be
judged: it needs hundreds of fills over the hours."""


def _policy_hash(p: Dict) -> str:
    core = {k: v for k, v in p.items() if k not in ("name", "why")}
    return hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()[:12]


def research_line(name: str, policy: Dict, st: Dict) -> str:
    knobs = {k: v for k, v in policy.items() if k not in ("name", "why", "rewarded_only") and v != mr.DEFAULTS.get(k)}
    return ("%s %s: hours %s, fills %s, markout/contract %s, mean/hour $%s, t %s, reward share/hour %s, "
            "break-even pool $%s per contract-hour" % (
                name, json.dumps(knobs, sort_keys=True), st["hours"], st["fills"], st["markout_per_contract"],
                st["mean"], st["t"], st["reward_share_per_hour"], st["breakeven_pool"]))


def _check(series: str, n: int) -> Callable[[Dict], List[Dict]]:
    def check(obj: Dict) -> List[Dict]:
        raw = obj.get("policies")
        if not isinstance(raw, list) or not raw:
            raise ValueError('reply must be {"policies": [ ... ]}')
        out = []
        for i, p in enumerate(raw[:n]):
            if not isinstance(p, dict):
                raise ValueError("policy %d is not an object" % i)
            try:
                out.append(mr.validate_policy(dict(p, series=p.get("series", series))))
            except mr.PolicyError as e:
                raise ValueError("policy %d: %s" % (i, e))
        return out
    return check


def propose(model: ModelFn, usage: Usage, series: str, history: List[str], n: int,
            prior: Sequence[str] = ()) -> List[Dict]:
    earlier = ("Earlier lab runs on other hours (what was tried, how it did, and how its finalist fared "
               "on held-out hours):\n%s\n\n" % "\n".join(prior)) if prior else ""
    prompt = (earlier + "Research results so far (research hours only):\n%s\n\nPropose %d new policies for %s that "
              "should beat these. Each one changes something for a stated reason. Reply with JSON only: "
              '{"policies": [{"name": "...", "why": "one sentence", ...levers}]}' % (
                  "\n".join(history) or "(none yet)", n, series))
    return ask_json(model, SYSTEM, [{"role": "user", "content": prompt}], _check(series, n), usage)


def pick_finalist(results: Dict[str, Dict]) -> Optional[str]:
    best, best_t = None, 0.0
    for name, r in results.items():
        st = r["stats"]
        if st["t"] is None or (st["mean"] or 0) <= 0 or st["fills"] < MIN_FILLS:
            continue
        if st["t"] > best_t:
            best, best_t = name, st["t"]
    return best


def judge(rows: Sequence[Dict], alpha: float) -> Dict:
    """The gate on held-out hours (rows in time order), at pool 0."""
    active = [r for r in rows if r.get("fills") or r.get("reward")]
    vals = [r[mr.HORIZON] for r in active]
    fills = sum(r["fills"] for r in active)
    out = {"hours": len(active), "fills": fills, "alpha": alpha, "passed": False,
           "stats": mr.hour_stats(rows, 0.0)}
    if len(active) < MIN_HOURS or fills < MIN_FILLS:
        out["reason"] = "underpowered: %d active hours, %d fills (needs %d and %d)" % (
            len(active), fills, MIN_HOURS, MIN_FILLS)
        return out
    boot = stats.stationary_bootstrap_ci(vals, alpha=2 * alpha)
    stressed = sum(v - r.get("fee_stress", 0.0) for v, r in zip(vals, active)) / len(vals)
    out.update({"p_value": round(boot["p_value"], 4), "lo": round(boot["lo"], 2), "mean": round(boot["point"], 2),
                "fee_stressed_mean": round(stressed, 2)})
    if boot["p_value"] > alpha:
        out["reason"] = "not significant: p %.3f > %.4f" % (boot["p_value"], alpha)
    elif stressed <= 0:
        out["reason"] = "loses once makers pay Kalshi's fee: $%.2f an hour" % stressed
    else:
        out["passed"], out["reason"] = True, "passed"
    return out


class MemoryLedger:
    """Finalists judged per held-out window; the S3 one persists it (S3Ledger)."""

    def __init__(self, entries: Optional[List[Dict]] = None) -> None:
        self.entries = list(entries or [])

    def overlapping(self, series: str, start: int, end: int) -> int:
        return sum(1 for e in self.entries if e["series"] == series and e["start"] < end and start < e["end"])

    def record(self, entry: Dict) -> None:
        self.entries.append(entry)


class S3Ledger(MemoryLedger):
    KEY = "research-watch/maker/ledger.json"

    def __init__(self, s3, bucket: str) -> None:
        self.s3, self.bucket = s3, bucket
        try:
            body = s3.get_object(Bucket=bucket, Key=self.KEY)["Body"].read()
            entries = json.loads(body).get("entries") or []
        except Exception:  # noqa: BLE001 - first run: empty ledger
            entries = []
        super().__init__(entries)

    def record(self, entry: Dict) -> None:
        super().record(entry)
        self.s3.put_object(Bucket=self.bucket, Key=self.KEY, Body=json.dumps({"entries": self.entries}).encode())


def run_lab(series: str, research: Sequence[datetime], holdout: Sequence[datetime], model: ModelFn, usage: Usage,
            ledger: MemoryLedger, evaluate: Callable[..., List[Dict]], rounds: int = 3, per_round: int = 4,
            workers: int = 1, log: Callable[[str], None] = print, prior: Sequence[str] = ()) -> Dict:
    """``evaluate(policy, hours, workers=)`` -> one row per hour (app.adapters.sim.maker_eval.evaluate).
    ``prior``: summary lines of earlier runs (prior_lines), so each run builds on the last."""
    t0 = time.monotonic()
    results: Dict[str, Dict] = {}
    history: List[str] = []

    def score(name: str, policy: Dict) -> None:
        h = _policy_hash(policy)
        if any(r["hash"] == h for r in results.values()):
            log("skip %s: same levers as an earlier policy" % name)
            return
        rows = evaluate(policy, research, workers=workers)
        st = mr.hour_stats(rows, 0.0)
        results[name] = {"policy": policy, "hash": h, "rows": rows, "stats": st}
        history.append(research_line(name, policy, st))
        log(history[-1])

    for name in ROUND0:
        score(name, mr.validate_policy(dict(mr.BASELINES[name], series=series)))
    for rnd in range(1, rounds + 1):
        for i, p in enumerate(propose(model, usage, series, history, per_round, prior)):
            name = "r%d.%d %s" % (rnd, i + 1, (p.get("name") or "policy")[:40])
            score(name, p)
    fin = pick_finalist(results)
    out = {"series": series, "research_hours": [int(h.timestamp()) for h in research],
           "holdout_hours": [int(h.timestamp()) for h in holdout], "results": results, "finalist": fin,
           "verdict": None, "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}}
    if fin is None:
        log("no finalist: no research policy has a positive markout mean with %d+ fills" % MIN_FILLS)
    else:
        start = int(holdout[0].timestamp())
        end = int(holdout[-1].timestamp()) + 3600
        prior = ledger.overlapping(series, start, end)
        alpha = GATE_ALPHA / (prior + 1)
        rows = evaluate(results[fin]["policy"], holdout, workers=workers)
        v = judge(rows, alpha)
        v["rows"] = rows
        out["verdict"] = v
        ledger.record({"series": series, "start": start, "end": end, "hash": results[fin]["hash"],
                       "passed": v["passed"], "at": int(time.time())})
        log("finalist %s on %d held-out hours: %s" % (fin, len(holdout), v["reason"]))
    out["seconds"] = round(time.monotonic() - t0, 1)
    return out


def summary_lines(run: Dict, top: int = 3) -> List[str]:
    """A finished run in a few lines for later runs' prompts: its best research policies and the verdict."""
    res = run.get("results") or {}
    ranked = sorted(res.items(), key=lambda kv: -(kv[1]["stats"].get("t") or -99))[:top]
    when = datetime.fromtimestamp(run["holdout_hours"][0], timezone.utc).strftime("%Y-%m-%d %H:00Z") if run.get("holdout_hours") else "?"
    out = ["- run held out from %s:" % when]
    out += ["  " + research_line(name, r["policy"], r["stats"]) for name, r in ranked]
    v = run.get("verdict")
    out.append("  finalist %s: %s" % (run.get("finalist"), (v or {}).get("reason", "none judged")) +
               ("" if not v else " (held-out mean/hour $%s, markout/contract %s)" % (
                   (v.get("stats") or {}).get("mean"), (v.get("stats") or {}).get("markout_per_contract"))))
    return out


def split(end: datetime, hours: int, holdout: int):
    end = end.replace(minute=0, second=0, microsecond=0)
    allh = [end - timedelta(hours=k) for k in range(hours + holdout, 0, -1)]
    return allh[:hours], allh[hours:]
