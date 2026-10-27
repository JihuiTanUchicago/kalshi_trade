"""Fund-grade track record: realized performance from the user's own book (app_positions).

Pure math over rows the repository layer hands in (repo.track_record_rows), no I/O, so every
figure is testable without a DB. Built for the reader an investor would be: live, demo and paper
money are never mixed, nothing here is a backtest, and every headline number carries the sample
it rests on, so a lucky week of 12 trades can't read like a proven edge.

Conventions (shown on the page as the methodology note):
- A trade is one entry fill, round trip. Partial-exit slices share the entry's order_ref and are
  summed; a trade with any slice still open is not in the record until it fully closes.
- P&L is net of every Kalshi fee (app_positions.pnl already is).
- Paper trades filled instantly (no simulated venue, order_ref not 'sim:') are left out: they
  assume fills real execution would not get, so they are not evidence.
- Capital is the capital the record REQUIRED: peak capital at risk (max concurrent entry cost,
  open positions included) plus the worst drawdown, i.e. the smallest bankroll that could have
  run every trade without going broke. Returns and drawdown % use it. Peak-at-risk alone would
  flatter a record of many small sequential trades (losses compound past one trade's cost).
- Sharpe/Sortino are on calendar-day P&L from the first close to today, zero days included,
  risk-free rate 0, annualized by sqrt(365) (Kalshi trades every day). Sharpe is scale-free, so
  the capital choice does not move it. PSR is P(true Sharpe > 0), Bailey & Lopez de Prado.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Dict, Iterable, List, Optional

from app.trading.quant import max_drawdown
from app.research.stats import probabilistic_sharpe_ratio
from trading_core.domain.money import cents, exact
from trading_core.domain.slippage import paper_estimate

MODES = ("live", "demo", "paper")
MODE_LABEL = {"live": "Live money", "demo": "Kalshi demo", "paper": "Paper"}
# The tab the record opens on: the first of these with a closed trade. Paper comes before demo: demo
# is the order-path check on Kalshi's thin sandbox book, and its P&L is no evidence of the edge (paper
# keeps that job). A user with 146 paper trades and a 10-trade demo copy opened on demo's figures.
DEFAULT_ORDER = ("live", "paper", "demo")
MIN_TRADES = 30          # below this a win rate or average trade is mostly noise
SOLID_TRADES = 100
MIN_SHARPE_DAYS = 14     # a Sharpe on fewer calendar days is not shown
SOLID_DAYS = 60
MIN_ANNUALIZE_DAYS = 90  # annualizing a shorter record would multiply the luck
CURVE_POINTS = 400       # payload cap (thin_min_max keeps every dip); stats use the full series
Z95 = 1.959964

METHOD = [
    "Every figure comes from closed trades in your own book. Nothing here is a backtest.",
    "A trade is one entry fill, round trip. Partial exits are summed into it, and a trade that is still partly open is left out until it closes.",
    "P&L is net of all Kalshi fees.",
    # What a paper fill assumes: app.services.customer_text.PAPER_FILLS, word for word (a test pins it).
    "Paper trades against Kalshi’s live order book: it buys at the ask and sells at the bid, pays Kalshi’s trading fee on every fill, and fills only the contracts offered at that price. A contract held to the end settles at $1 or $0. It doesn’t model the price moving in the second before a real order lands, so live fills can come in slightly worse.",
    "Strategies removed from paper, demo or live, and strategies deleted after that, keep their trades in every figure: nothing is dropped for doing badly.",
    "Paper trades that filled instantly, without the simulated order book, are left out, because real execution would not get those fills.",
    "Capital is what the record needed: the most money ever at risk at once plus the worst drawdown, so the smallest bankroll that could have taken every trade. Return and drawdown percentages use it.",
    "Sharpe and Sortino use daily P&L from the first closed trade to today, with flat days counted, a 0% risk-free rate and a 365-day year. They are hidden under 14 days.",
    "PSR is the probability the true Sharpe is above zero, corrected for skew and fat tails.",
    "Ranges are 95% confidence intervals: Wilson for the win rate, normal for the average trade.",
]


def _ts(dt: Optional[datetime]) -> Optional[int]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


_EPOCH_DATE = date(1970, 1, 1)


def _day(ts: int) -> date:
    """The UTC date of a unix time: the date datetime.fromtimestamp(ts, utc) has, from the whole days
    since the epoch (a busy record asks for it ~70k times; there are only as many dates as days)."""
    return _day_n(ts // 86400)


@lru_cache(maxsize=8192)
def _day_n(n: int) -> date:
    return _EPOCH_DATE + timedelta(days=int(n))


@lru_cache(maxsize=8192)
def _month_n(n: int) -> str:
    """"YYYY-MM" of the n-th day since the epoch."""
    return _day_n(n).strftime("%Y-%m")


def _ts_date(now: datetime) -> date:
    return (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date()


def _r(v: Optional[float], dp: int = 2) -> Optional[float]:
    return None if v is None or not math.isfinite(v) else round(v, dp)


def wilson(wins: int, n: int, z: float = Z95) -> Optional[List[float]]:
    """Wilson score interval for a win rate; honest at small n, unlike p +/- z*se."""
    if n <= 0:
        return None
    p = wins / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)]


def mean_ci(xs: List[float], z: float = Z95) -> Optional[List[float]]:
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    half = z * sd / math.sqrt(n)
    return [round(m - half, 4), round(m + half, 4)]


def _moments(xs: List[float]):
    """(mean, sample sd, skew, full kurtosis) of a series; sd 0 for a flat one."""
    n = len(xs)
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    if sd == 0:
        return m, 0.0, 0.0, 3.0
    pop = math.sqrt(sum((x - m) ** 2 for x in xs) / n)
    skew = sum(((x - m) / pop) ** 3 for x in xs) / n
    kurt = sum(((x - m) / pop) ** 4 for x in xs) / n
    return m, sd, skew, kurt


def peak_capital(spans: Iterable[tuple]) -> float:
    """Max concurrent entry cost over (open_ts, close_ts | None, cost) spans. A close and an open
    at the same second do not overlap (closes are applied first)."""
    events = []
    for o, c, cost in spans:
        if o is None or cost <= 0:
            continue
        events.append((o, 1, cost))
        if c is not None:
            events.append((c, 0, -cost))
    peak = cur = 0.0
    for _, _, d in sorted(events):
        cur += d
        peak = max(peak, cur)
    return peak


def daily_series(trades: List[Dict], today: date) -> List[float]:
    """Calendar-day net P&L from the first close day through `today`, flat days as 0."""
    if not trades:
        return []
    by_day: Dict[date, float] = {}
    for t in trades:
        d = _day(t["closed_ts"])
        by_day[d] = by_day.get(d, 0.0) + t["pnl"]
    first = min(by_day)
    last = max(today, max(by_day))
    return [by_day.get(first + timedelta(days=i), 0.0) for i in range((last - first).days + 1)]


def _drawdown_stats(curve: List[List], now_ts: int) -> Dict:
    """Worst drawdown, the longest time spent under a prior high (a drawdown still open runs to
    now), and the current one, on the trade curve (cumulative P&L from 0 before the first trade)."""
    if not curve:
        return {"max": 0.0, "current": 0.0, "longest_days": 0.0}
    peak, peak_ts, longest, under = 0.0, curve[0][0], 0, False
    for ts, v in curve:
        if v >= peak:
            if under:
                longest = max(longest, ts - peak_ts)
            peak, peak_ts, under = v, ts, False
        else:
            under = True
    if under:
        longest = max(longest, max(now_ts, curve[-1][0]) - peak_ts)
    return {
        "max": max_drawdown([0.0] + [v for _, v in curve]),
        "current": round(peak - curve[-1][1], 4),
        "longest_days": round(longest / 86400, 1),
    }


def thin_min_max(curve: List[List], cap: int = CURVE_POINTS) -> List[List]:
    """At most `cap` points of a [[ts, value], ...] curve that still shows every dip and peak.

    The first and last points are kept exactly, so the curve ends on the real total. The points
    between them are split into (cap - 2) // 2 runs by count, and each run keeps its lowest and
    highest point, in time order (one point when they are the same). Ties keep the earlier point.
    Every point kept is a real one, never an average. Same rule as repo.deployment_curves applies
    in SQL. Keeping every Nth point instead could step over a one-trade crash and hide a drawdown."""
    if cap < 4:
        raise ValueError("thin_min_max needs room for the ends and one run's low and high (cap >= 4)")
    if len(curve) <= cap:
        return curve
    out = [curve[0]]
    for lo_i, hi_i in _runs(len(curve), (cap - 2) // 2):
        lo = min(range(lo_i, hi_i), key=lambda i: (curve[i][1], i))
        hi = min(range(lo_i, hi_i), key=lambda i: (-curve[i][1], i))
        out.extend(curve[i] for i in sorted({lo, hi}))
    out.append(curve[-1])
    return out


def thin_lows(series: List[List], cap: int = CURVE_POINTS) -> List[List]:
    """At most `cap` points of a [[ts, value], ...] series, keeping the first and last points and
    each run's lowest point (cap - 2 runs by count; ties keep the earlier point). For a drawdown
    series, whose low points are the ones that matter: the deepest point always survives."""
    if cap < 3:
        raise ValueError("thin_lows needs room for the ends and one run's low (cap >= 3)")
    if len(series) <= cap:
        return series
    return ([series[0]] + [series[min(range(lo_i, hi_i), key=lambda i: (series[i][1], i))]
                           for lo_i, hi_i in _runs(len(series), cap - 2)] + [series[-1]])


def _runs(n: int, buckets: int):
    """(start, stop) index ranges splitting the inner points 1..n-2 into `buckets` runs by count."""
    inner = n - 2
    for b in range(buckets):
        lo_i, hi_i = 1 + b * inner // buckets, 1 + (b + 1) * inner // buckets
        if lo_i < hi_i:
            yield lo_i, hi_i


def underwater(curve: List[List]) -> List[List]:
    """The drawdown at each point of a cumulative P&L curve: how far it sits below the highest it
    has been, counting the 0 before the first trade (as _drawdown_stats does), in cents. Its lowest
    value is minus the reported max_drawdown, to the cent. Built from the full curve: a curve thinned
    first could lose the peak a drop started from."""
    out, peak = [], 0.0
    for ts, v in curve:
        peak = max(peak, v)
        # Rounded as max_drawdown then the payload round it (4 places, then cents), so the deepest
        # point equals the figure exactly; 0.0 - x keeps a flat point 0.0, not -0.0.
        out.append([ts, 0.0 - round(round(peak - v, 4), 2)])
    return out


def edge_read(avg_ci: Optional[List[float]]) -> str:
    """'positive' / 'negative' when the 95% range of the average trade excludes zero, else 'unclear'."""
    if avg_ci is None:
        return "unclear"
    return "positive" if avg_ci[0] > 0 else "negative" if avg_ci[1] < 0 else "unclear"


def sample_read(n: int, span_days: float, avg_ci: Optional[List[float]]) -> Dict:
    """Plain-language verdict on how much this record can say. `level` drives the page badge.
    Under MIN_TRADES it makes no claim about the average trade (edge 'thin', as by_strategy reads a
    strategy): a normal range on 5 trades that all won said "above zero at 95% confidence"."""
    if n == 0:
        return {"level": "none", "edge": "none", "text": "No closed trades yet."}
    days = max(1, round(span_days))
    size = "%d trade%s over %d day%s" % (n, "" if n == 1 else "s", days, "" if days == 1 else "s")
    if n < MIN_TRADES or span_days < MIN_SHARPE_DAYS:
        level, lead = "thin", "Too early to judge: %s. A sample this small is mostly luck." % size
    elif n < SOLID_TRADES or span_days < SOLID_DAYS:
        level, lead = "early", "Early read: %s. Treat the numbers as a direction, not proof." % size
    else:
        level, lead = "solid", "Meaningful sample: %s." % size
    edge = edge_read(avg_ci) if n >= MIN_TRADES else "thin"
    tail = {"thin": "", "positive": " The average trade is above zero at 95% confidence.",
            "negative": " The average trade is below zero at 95% confidence.",
            "unclear": " The average trade is not yet distinguishable from zero." if avg_ci else ""}[edge]
    return {"level": level, "edge": edge, "text": lead + tail}


def _peak_at_risk(trades: List[Dict], open_trades: List[Dict]) -> float:
    """peak_capital over a bucket's closed round trips (in close order) and its trades still open."""
    trades = sorted(trades, key=lambda t: (t["closed_ts"], t["opened_ts"] or 0))
    return peak_capital([(t["opened_ts"], t["closed_ts"], t["cost"]) for t in trades]
                        + [(t["opened_ts"], None, t["cost"]) for t in open_trades])


def summarize(trades: List[Dict], open_trades: List[Dict], today: date, now_ts: int,
              peak_at_risk: Optional[float] = None) -> Dict:
    """Every headline figure for one money bucket. `trades` are closed round trips oldest-first
    by close time: {pnl, fees, cost, opened_ts, closed_ts}; `open_trades`: {cost, opened_ts, and open_cost:
    what is still held, with its entry fees (cost when absent)}.
    `peak_at_risk` is _peak_at_risk(trades, open_trades) when the caller already has it."""
    trades = sorted(trades, key=lambda t: (t["closed_ts"], t["opened_ts"] or 0))
    n = len(trades)
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    fees = sum(t["fees"] for t in trades)
    cap = peak_at_risk if peak_at_risk is not None else peak_capital(
        [(t["opened_ts"], t["closed_ts"], t["cost"]) for t in trades]
        + [(t["opened_ts"], None, t["cost"]) for t in open_trades])
    curve, cum = [], 0.0
    for t in trades:
        cum += t["pnl"]
        curve.append([t["closed_ts"], round(cum, 4)])
    first_ts = min((t["opened_ts"] or t["closed_ts"] for t in trades), default=None)
    span_days = (now_ts - first_ts) / 86400 if first_ts else 0.0
    dd = _drawdown_stats(curve, now_ts)
    avg_ci = mean_ci(pnls)

    days = daily_series(trades, today)
    sharpe = sortino = psr = None
    if len(days) >= MIN_SHARPE_DAYS:
        m, sd, skew, kurt = _moments(days)
        if sd > 0:
            sr = m / sd
            sharpe = sr * math.sqrt(365)
            psr = probabilistic_sharpe_ratio(sr, len(days), skew, kurt)
        down = math.sqrt(sum(min(0.0, x) ** 2 for x in days) / len(days))
        if down > 0:
            sortino = m / down * math.sqrt(365)
    at_risk = cap
    cap = at_risk + dd["max"]
    ret = net / cap if cap > 0 else None
    ann = ret * 365 / span_days if ret is not None and span_days >= MIN_ANNUALIZE_DAYS else None
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _r(len(wins) / n, 4) if n else None,
        "win_rate_ci": wilson(len(wins), n),
        # Sums of stored money, rounded once as every page rounds them (trading_core.domain.money).
        "net_pnl": cents(net),
        "fees": cents(fees),
        "gross_pnl": cents(net + fees),
        "avg_trade": _r(net / n, 4) if n else None,
        "avg_trade_ci": avg_ci,
        "avg_win": _r(sum(wins) / len(wins), 4) if wins else None,
        "avg_loss": _r(sum(losses) / len(losses), 4) if losses else None,
        "best": cents(max(pnls)) if pnls else None,
        "worst": cents(min(pnls)) if pnls else None,
        "profit_factor": _r(sum(wins) / -sum(losses), 2) if losses else None,
        "capital": round(cap, 2),
        "peak_at_risk": round(at_risk, 2),
        "return": _r(ret, 4),
        "annualized_return": _r(ann, 4),
        "max_drawdown": round(dd["max"], 2),
        "max_drawdown_pct": _r(dd["max"] / cap, 4) if cap > 0 else None,
        "current_drawdown": round(dd["current"], 2),
        "longest_drawdown_days": dd["longest_days"],
        "sharpe": _r(sharpe, 2),
        "sortino": _r(sortino, 2),
        "psr": _r(psr, 3),
        "days": len(days),
        "span_days": round(span_days, 1),
        "first_trade_at": first_ts,
        "last_trade_at": trades[-1]["closed_ts"] if trades else None,
        "open_trades": len(open_trades),
        # What is still held, at cost plus its entry fees (a part-sold trade's sold slice is no longer at
        # risk): the dashboard's and Funds' open_cost for the same book, summed exactly and rounded once.
        "open_cost": cents(sum((exact(t.get("open_cost", t["cost"])) for t in open_trades), Decimal(0))),
        # A part-sold trade joins the record when its remainder closes; until then this is what its
        # sold slices already realized, so the record plus this is every closed row's P&L.
        "open_realized_pnl": cents(sum(t["pnl"] for t in open_trades)),
        "sample": sample_read(n, span_days, avg_ci),
        "curve": thin_min_max(curve),  # display only: every stat above used the full curve
        "underwater": thin_lows(underwater(curve)),  # from the full curve; its low is -max_drawdown
    }


def _months(first: date, last: date) -> List[str]:
    """Every calendar month from `first`'s through `last`'s, oldest first, as "YYYY-MM"."""
    y, m, out = first.year, first.month, []
    while (y, m) <= (last.year, last.month):
        out.append("%04d-%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly(trades: List[Dict], today: Optional[date] = None) -> List[Dict]:
    """Net P&L per calendar month (UTC), newest first: the grid an allocator scans first. Every
    month from the first close through `today` (or the last close) has a row, so a month with no
    trades reads as one (trades 0, win_rate None) instead of silently dropping out of the grid."""
    out: Dict[str, Dict] = {}
    for t in trades:
        k = _month_n(t["closed_ts"] // 86400)
        m = out.setdefault(k, {"month": k, "pnl": 0.0, "trades": 0, "wins": 0})
        m["pnl"] += t["pnl"]
        m["trades"] += 1
        m["wins"] += t["pnl"] > 0
    if trades:
        # _day never decreases as the time grows, so the first and last days are the earliest and
        # latest closes' days.
        first, last = _day(min(t["closed_ts"] for t in trades)), _day(max(t["closed_ts"] for t in trades))
        for k in _months(first, max([last] + ([today] if today else []))):
            out.setdefault(k, {"month": k, "pnl": 0.0, "trades": 0, "wins": 0})
    rows = sorted(out.values(), key=lambda m: m["month"], reverse=True)
    for m in rows:
        m["pnl"] = cents(m["pnl"])
        m["win_rate"] = round(m["wins"] / m["trades"], 4) if m["trades"] else None
    return rows


# A strategy deployed more than once in a bucket reads as its most active deployment.
_STATUS_RANK = {"running": 3, "paused": 2, "stopped": 1}


def by_strategy(trades: List[Dict], open_trades: List[Dict], left_out: Iterable[Dict] = ()) -> List[Dict]:
    """One row per strategy in this bucket, best net P&L first. `status` is its deployment's status
    now (running, paused or stopped; None when unknown) and `removed` marks a strategy the user
    deleted after stopping it: both stay in, so the table shows nothing was dropped.
    `left_out` are its instant paper fills (prepare leaves them out of the record): a row counts them and
    their P&L apart (excluded_instant_fills, excluded_instant_pnl), so its figures reconcile with the
    strategy's realized P&L on its list row and the Deploy board, which count every closed row. A strategy
    whose only trades were instant fills still gets a row (trades 0, `instant_only`), after the others, so it is
    named beside its excluded P&L instead of only in the book's caveat; the record's totals never count it."""
    groups: Dict[int, Dict] = {}

    def group(t):
        g = groups.setdefault(t["strategy_id"], {"title": t["title"], "market": t["market"], "removed": t["removed"],
                                                 "trades": [], "open": 0, "status": None})
        if _STATUS_RANK.get(t["dep_status"], 0) > _STATUS_RANK.get(g["status"], 0):
            g["status"] = t["dep_status"]
        return g

    for t in trades:
        group(t)["trades"].append(t)
    for t in open_trades:
        group(t)["open"] += 1
    left: Dict[int, List[float]] = {}
    for t in left_out:
        group(t)
        left.setdefault(t["strategy_id"], []).append(t["pnl"])
    rows = []
    for sid, g in groups.items():
        ts = sorted(g["trades"], key=lambda t: t["closed_ts"])
        pnls = [t["pnl"] for t in ts]
        n = len(pnls)
        cum, curve = 0.0, [0.0]
        for p in pnls:
            cum += p
            curve.append(cum)
        ci = mean_ci(pnls)
        rows.append({
            "strategy_id": sid, "title": g["title"], "market": g["market"], "trades": n,
            "status": g["status"], "removed": g["removed"],
            "open_trades": g["open"], "net_pnl": cents(sum(pnls)),
            "win_rate": _r(sum(1 for p in pnls if p > 0) / n, 4) if n else None,
            "avg_trade": _r(sum(pnls) / n, 4) if n else None, "avg_trade_ci": ci,
            "max_drawdown": round(max_drawdown(curve), 2),
            "last_trade_at": ts[-1]["closed_ts"] if ts else None,
            "edge": edge_read(ci) if n >= MIN_TRADES else "thin",
            "excluded_instant_fills": len(left.get(sid, ())), "excluded_instant_pnl": cents(sum(left.get(sid, ()))),
            "instant_only": not n and not g["open"] and bool(left.get(sid)),
        })
    rows.sort(key=lambda r: (r["instant_only"], -r["net_pnl"], -r["trades"]))
    return rows


def build(rows: List[Dict], now: Optional[datetime] = None) -> Dict:
    """The whole page payload from repo.track_record_rows output."""
    return finish(prepare(rows), now)


def prepare(rows: List[Dict]) -> Dict:
    """The part of `build` that depends on the rows alone: each bucket's closed round trips, its trades
    still part-open and how many instant paper fills were left out. services.book_memo keeps it while
    the book is unchanged; `finish` (which also reads the clock) never modifies it."""
    closed: Dict[str, List[Dict]] = {m: [] for m in MODES}
    opened: Dict[str, List[Dict]] = {m: [] for m in MODES}
    excluded: Dict[str, List[Dict]] = {m: [] for m in MODES}
    for r in rows:
        mode = r.get("mode")
        if mode not in closed:
            continue
        t = {
            # The strategy row is gone when the user removed it after stopping it; its trades stay.
            "strategy_id": int(r.get("strategy_id") or 0), "title": r.get("title") or "Deleted strategy",
            "removed": r.get("title") is None, "dep_status": r.get("dep_status"),
            "market": r.get("market") or "", "pnl": float(r.get("pnl") or 0), "fees": float(r.get("fees") or 0),
            "cost": float(r.get("cost") or 0),
            # repo.track_record_join(seconds=True) hands the unix seconds over as they were read.
            "opened_ts": r["opened_ts"] if "opened_ts" in r else _ts(r.get("opened_at")),
            "closed_ts": r["closed_ts"] if "closed_ts" in r else _ts(r.get("closed_at")),
            "open_cost": float(r.get("open_cost") if r.get("open_cost") is not None else r.get("cost") or 0),
            # Contracts times taker fills of its closed slices: the paper after-slippage estimate's input only.
            "contract_fills": int(r.get("contract_fills") or 0),
        }
        if int(r.get("open_slices") or 0) > 0:
            opened[mode].append(t)
            continue
        if mode == "paper" and not str(r.get("order_ref") or "").startswith("sim:"):
            excluded[mode].append(t)
            continue
        if t["closed_ts"] is None:
            continue
        closed[mode].append(t)
    # The by-strategy table and the peak capital at risk read the trades alone, never the clock.
    return {"closed": closed, "opened": opened, "excluded": {m: len(excluded[m]) for m in MODES},
            "excluded_pnl": {m: cents(sum(t["pnl"] for t in excluded[m])) for m in MODES},
            "strategies": {m: by_strategy(closed[m], opened[m], excluded[m]) for m in MODES},
            "peak_at_risk": {m: _peak_at_risk(closed[m], opened[m]) for m in MODES}}


def finish(prepared: Dict, now: Optional[datetime] = None) -> Dict:
    """The page payload from `prepare`'s buckets, as of `now`."""
    now = now or datetime.now(timezone.utc)
    now_ts, today = _ts(now), _ts_date(now)
    closed, opened, excluded = prepared["closed"], prepared["opened"], prepared["excluded"]
    modes = {}
    for m in MODES:
        s = summarize(closed[m], opened[m], today, now_ts, prepared["peak_at_risk"][m])
        # A fresh list of the rows: finish never hands out what prepare keeps.
        # What the instant fills left out made: the record plus this (and open_realized_pnl) is the realized
        # P&L the dashboard, Funds and Deploy show for this book, so the page can say why the two differ.
        s.update(label=MODE_LABEL[m], excluded_instant_fills=excluded[m], excluded_instant_pnl=prepared["excluded_pnl"][m],
                 monthly=monthly(closed[m], today), strategies=[dict(r) for r in prepared["strategies"][m]])
        # Beside net_pnl, never in place of it: the same closed trades after the slippage a live order typically
        # pays (trading_core.domain.slippage). Paper only (None for live and demo, and for a book with no trade).
        s["slippage_estimate"] = paper_estimate(m, sum(t["pnl"] for t in closed[m]),
                                                sum(t.get("contract_fills", 0) for t in closed[m]))
        modes[m] = s
    default = next((m for m in DEFAULT_ORDER if modes[m]["trades"]), "paper")
    return {"generated_at": now_ts, "default_mode": default, "modes": modes, "method": METHOD,
            "thresholds": {"min_trades": MIN_TRADES, "min_sharpe_days": MIN_SHARPE_DAYS,
                           "min_annualize_days": MIN_ANNUALIZE_DAYS}}

