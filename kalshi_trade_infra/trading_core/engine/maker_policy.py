"""Market-making policies a research run may propose, and how a replayed policy is scored.

A policy is a JSON object over MakerConfig (trading_core.engine.quoting) plus the replay's inputs
(fair_source, move_window_s) and the series it quotes. validate_policy bounds every lever;
to_config maps it to a MakerConfig. The replay that scores it is app.adapters.sim.maker_eval, the
research loop app.services.maker_lab.

Scoring (hour_stats):
  * every fill is marked out at the mid 60 s later (fees included): what the fill earned before the
    outcome is known. Inventory P&L past that is outcome noise with zero mean when the mid is fair,
    which every fair-value study here found (the mid beat Deribit, Polymarket and the nowcast);
  * rewards are scored as a share of a pool: the replay pays $1 per contract-hour, so an hour's
    ``reward`` is the pool-dollars it would earn and the hour's value = markout + pool * share;
  * the hour is the independent unit (fills inside an hour share one BTC path): mean, standard error
    and t over hours. ``breakeven_pool`` is the pool per contract-hour at which the policy pays.
"""

from __future__ import annotations

import math
from dataclasses import fields
from typing import Dict, List, Sequence, Tuple

from trading_core.engine.quoting import MakerConfig

MAKER_SERIES = ("KXBTC15M", "KXBTCD", "KXBTC")
HORIZON = "m60"
TARGET_SIZE = 1000.0          # rewards target size assumed until a BTC program posts its own

# name -> (kind, lo, hi): the knobs a policy may set. Bounds keep the replay meaningful (a 1-contract
# quote earns nothing; an inventory cap past 5,000 is a directional bet, not market making).
KNOBS: Dict[str, Tuple[str, float, float]] = {
    "quote_size": ("num", 1, 5000),
    "max_inventory": ("num", 0, 5000),
    "min_edge": ("num", -0.05, 0.2),
    "back_off": ("bool", 0, 1),
    "offset_ticks": ("int", 0, 10),
    "improve_min_spread_ticks": ("int", 0, 20),
    "skew_ticks": ("int", 0, 10),
    "pull_before_close_s": ("num", 0, 3600),
    "max_secs_to_close": ("num", 60, 30 * 86400),
    "pull_move_bp": ("num", 0.5, 100),
    "pull_cooldown_s": ("num", 1, 600),
    "max_touch_size": ("num", 1, 1e6),
    "contract_loss_limit": ("num", 0, 1e5),
}
REPLAY_KNOBS = {"fair_source": ("mid", "micro", "spot"), "move_window_s": (1, 10, 60)}
DEFAULTS = {"series": "KXBTCD", "quote_size": 100.0, "max_inventory": 500.0, "fair_source": "mid", "move_window_s": 10,
            "rewarded_only": False}


class PolicyError(ValueError):
    pass


def validate_policy(raw) -> Dict:
    """A clean policy dict, or PolicyError naming every problem."""
    if not isinstance(raw, dict):
        raise PolicyError("policy must be a JSON object")
    errors: List[str] = []
    out = dict(DEFAULTS)
    for k, v in raw.items():
        if k in ("name", "why"):
            out[k] = str(v)[:300]
        elif k == "series":
            if v not in MAKER_SERIES:
                errors.append("series must be one of %s" % (MAKER_SERIES,))
            out[k] = v
        elif k in REPLAY_KNOBS:
            if v not in REPLAY_KNOBS[k]:
                errors.append("%s must be one of %s" % (k, REPLAY_KNOBS[k]))
            out[k] = v
        elif k == "mid_band":
            ok = isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v) \
                and 0 <= v[0] < v[1] <= 1
            if not ok:
                errors.append("mid_band must be [lo, hi] with 0 <= lo < hi <= 1")
            out[k] = [float(x) for x in v] if ok else v
        elif k in KNOBS:
            kind, lo, hi = KNOBS[k]
            if v is None:
                out[k] = None
                continue
            if kind == "bool":
                if not isinstance(v, bool):
                    errors.append("%s must be true or false" % k)
                out[k] = bool(v)
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                errors.append("%s must be a number" % k)
                continue
            if not lo <= v <= hi:
                errors.append("%s must be between %g and %g" % (k, lo, hi))
            out[k] = int(v) if kind == "int" else float(v)
        else:
            errors.append("unknown field %r" % k)
    if errors:
        raise PolicyError("; ".join(errors))
    return out


def to_config(policy: Dict) -> MakerConfig:
    names = {f.name for f in fields(MakerConfig)}
    kw = {k: v for k, v in policy.items() if k in names}
    if "mid_band" in kw:
        kw["mid_band"] = tuple(kw["mid_band"])
    return MakerConfig(**kw)


def hour_stats(rows: Sequence[Dict], pool: float = 0.0, horizon: str = HORIZON) -> Dict:
    """Mean, standard error and t over hours of markout + pool * reward share, plus the break-even pool."""
    active = [r for r in rows if r.get("fills") or r.get("reward")]
    vals = [r[horizon] + pool * r["reward"] for r in active]
    n = len(vals)
    qty = sum(r["qty"] for r in active)
    out = {"hours": n, "fills": sum(r["fills"] for r in active), "qty": round(qty, 1), "pool": pool,
           "mean": None, "se": None, "t": None,
           "markout_per_contract": round(sum(r[horizon] for r in active) / qty, 5) if qty > 0 else None,
           "reward_share_per_hour": round(sum(r["reward"] for r in active) / n, 4) if n else None,
           "breakeven_pool": None}
    if n:
        mean = sum(vals) / n
        out["mean"] = round(mean, 2)
        if n >= 2:
            sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
            se = sd / math.sqrt(n)
            out["se"] = round(se, 2)
            out["t"] = round(mean / se, 2) if se > 0 else None
        share = sum(r["reward"] for r in active) / n
        mk = sum(r[horizon] for r in active) / n
        if share > 0:
            out["breakeven_pool"] = round(max(0.0, -mk / share), 2)
    return out


BASELINES: Dict[str, Dict] = {
    "join_touch": {},
    "spot_fair_1c": {"fair_source": "spot", "min_edge": 0.01, "back_off": True},
    "spot_fair_2c": {"fair_source": "spot", "min_edge": 0.02, "back_off": True},
    "spot_fair_2c_pull": {"fair_source": "spot", "min_edge": 0.02, "back_off": True, "pull_move_bp": 3},
    "micro_fair_1c": {"fair_source": "micro", "min_edge": 0.01, "back_off": True},
    "pull_3bp": {"pull_move_bp": 3},
    "behind_1": {"offset_ticks": 1},
    "mid_band_20_80": {"mid_band": [0.2, 0.8], "pull_before_close_s": 180},
    "skew_3": {"skew_ticks": 3},
}
