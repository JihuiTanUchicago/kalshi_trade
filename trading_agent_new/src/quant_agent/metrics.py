"""Recomputable investment statistics and preregistered paired uncertainty."""
from __future__ import annotations

import math
import random
import statistics

from .common import GateError


def sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    deviation = statistics.stdev(returns)
    return math.sqrt(252) * statistics.mean(returns) / deviation if deviation > 1e-12 else 0.0


def metrics(ledger: dict, capital: float) -> dict:
    rows = ledger["daily"]
    excess = [r["return"] - r["reference_return"] for r in rows]
    peak, maximum = capital, 0.0
    for row in rows:
        peak = max(peak, row["nav"])
        maximum = max(maximum, 1-row["nav"]/peak)
    notionals = sum(abs(f["quantity"])*f["raw_open"] for f in ledger["fills"])
    average_nav = statistics.mean(r["nav"] for r in rows)
    return {"sessions": len(rows), "excess_sharpe": sharpe(excess), "max_drawdown": maximum,
            "net_return": rows[-1]["nav"]/capital-1,
            "annualized_turnover": notionals/average_nav*252/len(rows),
            "orders_filled": sum(bool(f["quantity"]) for f in ledger["fills"]),
            "transaction_cost": sum(f["commission"]+f["slippage"] for f in ledger["fills"]),
            "borrow_cost": sum(r["borrow_fee"] for r in rows),
            "mean_gross": statistics.mean(r["gross"] for r in rows)}


def compare(candidate: dict, baseline: dict, samples: int, block: int, seed: int) -> dict:
    a, b = candidate["daily"], baseline["daily"]
    if [r["session"] for r in a] != [r["session"] for r in b]:
        raise GateError("Paired experiments must have identical scoring sessions")
    n = len(a)
    ar = [r["return"]-r["reference_return"] for r in a]
    br = [r["return"]-r["reference_return"] for r in b]
    gain = sharpe(ar)-sharpe(br)
    rng = random.Random(seed)
    gains = []
    for _ in range(samples):
        indices = []
        while len(indices) < n:
            start = rng.randrange(n)
            indices.extend((start+j) % n for j in range(min(block, n-len(indices))))
        gains.append(sharpe([ar[i] for i in indices])-sharpe([br[i] for i in indices]))
    gains.sort()
    groups = {}
    for i, row in enumerate(a):
        groups.setdefault(row["session"][:4], []).append(i)
    years = {year: sharpe([ar[i] for i in ids])-sharpe([br[i] for i in ids]) for year, ids in groups.items() if len(ids) >= 20}
    mean_a, mean_b = statistics.mean(ar), statistics.mean(br)
    variance = sum((x-mean_b)**2 for x in br)
    beta = sum((x-mean_b)*(y-mean_a) for x,y in zip(br,ar))/variance if variance > 1e-20 else None
    lower = gains[int(0.05*(len(gains)-1))]
    return {"sharpe_gain": gain, "lower_95_one_sided": lower,
            "upper_95_one_sided": gains[int(0.95*(len(gains)-1))],
            "bootstrap_samples": samples, "block_length": block, "seed": seed,
            "annual_sharpe_gains": years, "benchmark_beta": beta,
            "sufficient_blocks": n >= 2*block,
            "retrospective_selection": True, "confirmatory_alpha": False}
