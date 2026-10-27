"""Where Bitcoin is against a Kalshi Bitcoin contract's strike, for its market page and Explore's rows.

A Bitcoin contract is one of three ladders: KXBTCD above/below a strike (hourly, and the 5pm ET close),
KXBTC range buckets (with an open-ended contract at each end), and KXBTC15M "up in the next 15
minutes", whose strike is the price the window opened at. The strike comes from Kalshi's own record of
the contract when the collector stored one (floor_strike / cap_strike / strike_type), else from the
ticker: KXBTCD-26OCT2717-T113499.99 is above $113,499.99 and KXBTC-26OCT2717-B113250 is the bucket
centred on $113,250 (one ticker gives no bucket width, though its ladder's tickers do, nor which way a
KXBTC T contract points).
A 15-minute ticker carries no strike at all.

Pure: no I/O, no app imports.
"""
from __future__ import annotations

import math
import re
from typing import Dict, Iterable, Optional

BTC_SERIES = ("KXBTC15M", "KXBTCD", "KXBTC")
SPOT_PRODUCT = "BTC-USD"
# The collector snapshots every 20s, so a spot older than two minutes means the feed stopped.
STALE_AFTER_S = 120

_STRIKE = re.compile(r"^(KXBTC15M|KXBTCD|KXBTC)-[A-Z0-9]+-([TB])(\d+(?:\.\d+)?)$")


def is_btc_contract(ticker: str) -> bool:
    series, dash, rest = (ticker or "").partition("-")
    return series in BTC_SERIES and bool(dash and rest)


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def contract_strike(ticker: str, record: Optional[Dict] = None) -> Optional[Dict]:
    """The contract's strike: {"kind", "value", "lo", "hi", "inclusive", "from"}. kind is "above" or
    "below" (Yes when Bitcoin ends above or below `value`), "range" (Yes inside [lo, hi]; from the ticker
    only the centre `value` is known), or "line" (a KXBTC end contract read from its ticker: the strike,
    not which side pays). None when neither the record nor the ticker gives one."""
    rec = record or {}
    lo, hi, kind = _f(rec.get("floor_strike")), _f(rec.get("cap_strike")), rec.get("strike_type")
    if kind in ("greater", "greater_or_equal") and lo is not None:
        return {"kind": "above", "value": lo, "lo": None, "hi": None, "inclusive": kind == "greater_or_equal", "from": "record"}
    if kind in ("less", "less_or_equal") and hi is not None:
        return {"kind": "below", "value": hi, "lo": None, "hi": None, "inclusive": kind == "less_or_equal", "from": "record"}
    if kind == "between" and lo is not None and hi is not None and lo <= hi:
        return {"kind": "range", "value": round((lo + hi) / 2, 2), "lo": lo, "hi": hi, "inclusive": True, "from": "record"}
    m = _STRIKE.match(ticker or "")
    if not m:
        return None
    series, letter, value = m.group(1), m.group(2), float(m.group(3))
    if letter == "B":
        return {"kind": "range", "value": value, "lo": None, "hi": None, "inclusive": True, "from": "ticker"}
    return {"kind": "above" if series == "KXBTCD" else "line", "value": value, "lo": None, "hi": None,
            "inclusive": False, "from": "ticker"}


def bucket_width(centres: Iterable[float]) -> Optional[float]:
    """A KXBTC ladder's bucket width from the centres its tickers carry (B113250, B113750, ...): the
    largest step every gap between two of them is a whole number of, so a bucket missing between two
    others doesn't double it. None from fewer than two."""
    cents = sorted({round(c * 100) for c in centres})
    gaps = [b - a for a, b in zip(cents, cents[1:])]
    return math.gcd(*gaps) / 100 if gaps else None


def with_bucket_edges(strike: Dict, width: Optional[float]) -> Dict:
    """A bucket read from its ticker, with its edges from the ladder's width: B113250 in a $500 ladder
    is $113,000 to $113,499.99. Any other strike, or no width, comes back as it was."""
    if strike["kind"] != "range" or strike["lo"] is not None or not width:
        return strike
    lo = round(strike["value"] - width / 2, 2)
    return {**strike, "lo": lo, "hi": round(lo + width - 0.01, 2)}


def against_strike(price: float, strike: Dict) -> Dict:
    """Spot against the strike: {"side", "diff", "pct", "yes"}. side is "above", "below" or "at" the
    strike, or "inside" a bucket; diff is spot minus the strike (or the bucket edge it is outside of)
    in dollars, pct that over the strike in percent; yes is whether Yes would pay at this price (None
    when the strike alone can't say). Inside a bucket, to_lo and to_hi are the room to each edge."""
    kind, value = strike["kind"], strike["value"]
    if kind == "range" and strike["lo"] is not None:
        lo, hi = strike["lo"], strike["hi"]
        if lo <= price <= hi:
            return {"side": "inside", "diff": 0.0, "pct": 0.0, "yes": True,
                    "to_lo": round(price - lo, 2), "to_hi": round(hi - price, 2)}
        edge = lo if price < lo else hi
        diff = price - edge
        return {"side": "below" if diff < 0 else "above", "diff": round(diff, 2), "pct": round(diff / edge * 100, 3), "yes": False}
    diff = price - value
    side = "above" if diff > 0 else "below" if diff < 0 else "at"
    yes = None
    if kind == "above":
        yes = diff > 0 or (diff == 0 and strike["inclusive"])
    elif kind == "below":
        yes = diff < 0 or (diff == 0 and strike["inclusive"])
    return {"side": side, "diff": round(diff, 2), "pct": round(diff / value * 100, 3) if value else 0.0, "yes": yes}
