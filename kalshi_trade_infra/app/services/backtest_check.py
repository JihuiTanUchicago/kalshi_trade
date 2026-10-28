"""Is each book doing what the backtest said it would? One plain line per book (paper, demo, live).

Display only: nothing here gates, sizes or trades. Each book is compared on its own and never added
to another book. A book's trades are its completed round trips (repo.book_trade_stats): partial-exit
slices are summed into their trade, a trade still partly open waits, and paper counts only fills
through the simulated venue (instant fills are not evidence, as on the track record page).

The comparison is the book's realized P&L per trade against the backtest's: the unseen-data
(out-of-sample) figures the gate used when there are any, else the tested data's. The honest band
is the noise an n-trade average carries: the backtest's per-trade figure plus or minus two standard
errors, with the standard error the book's own per-trade spread over the square root of n (the
backtest stores no per-trade spread). Inside the band reads "within the usual range"; outside it
reads behind or ahead. Under MIN_TRADES completed trades it says it is too early to tell.

Trade size: a backtest trade risks about one stake. When a book's trades are much smaller or
larger (a live size ramp, a different stake), the backtest's per-trade figure is scaled to the
book's average trade cost and the line says so.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from app.services.customer_text import PAPER_NET_SHORT

MIN_TRADES = 10
Z = 2.0  # about 95% of n-trade averages land within two standard errors
# Within this ratio of book cost to stake, a book trades the backtest's size (contract rounding
# alone keeps a trade's cost a little under the stake).
SAME_SIZE = (0.75, 1.25)
BOOKS = ("live", "demo", "paper")
LABEL = {"live": "live", "demo": "demo", "paper": "paper"}
# What a book's count covers, said in its line: every run of the strategy in that book, removed ones
# included, so a deployment row's own "N closed trades" beside it never reads as the same figure.
RUNS = {"live": "across all its live runs", "demo": "across all its demo runs",
        "paper": "across all its paper runs, realistic fills only"}
# Demo fills come from Kalshi's sandbox book, which is thin: a demo book ahead of or behind its
# backtest says how its orders filled there, not whether the edge is real (paper keeps that job).
DEMO_NOTE = " Demo’s book is thin, so this is no evidence of the edge either way."


def _usd(v: float) -> str:
    v = round(float(v), 2)
    return ("−" if v < 0 else "+") + "$%.2f" % abs(v)


def _pct(v: float) -> str:
    return "%d%%" % round(100 * float(v))


def backtest_figures(result: Optional[Dict], stake: Optional[float]) -> Optional[Dict]:
    """The backtest's per-trade P&L and win rate: unseen-data figures when there are any, else the
    tested data's. None when the backtest has no trades to compare with."""
    result = result or {}
    for source in ("out_of_sample", "in_sample"):
        m = result.get(source) or {}
        n = int(m.get("trades") or 0)
        if n > 0 and m.get("pnl") is not None:
            return {"source": source, "trades": n, "per_trade": float(m["pnl"]) / n,
                    "win_rate": None if m.get("win_rate") is None else float(m["win_rate"]),
                    "stake": float(stake) if stake else None}
    return None


def book_check(mode: str, stats: Optional[Dict], bt: Optional[Dict]) -> Optional[Dict]:
    """The comparison for one book, or None when there is nothing to compare (no completed trade,
    or no backtest trades). A demo book's line ends with DEMO_NOTE."""
    out = _book_check(mode, stats, bt)
    if out is not None and mode == "demo":
        out["line"] += DEMO_NOTE
    return out


def _book_check(mode: str, stats: Optional[Dict], bt: Optional[Dict]) -> Optional[Dict]:
    n = int((stats or {}).get("trades") or 0)
    if n < 1 or bt is None:
        return None
    pnl, sq = float(stats.get("pnl") or 0), float(stats.get("pnl_sq") or 0)
    per = pnl / n
    win = int(stats.get("wins") or 0) / n
    avg_cost = float(stats.get("cost") or 0) / n
    scale = 1.0
    if bt.get("stake") and avg_cost > 0:
        ratio = avg_cost / bt["stake"]
        if not SAME_SIZE[0] <= ratio <= SAME_SIZE[1]:
            scale = ratio
    expect = bt["per_trade"] * scale
    out = {"mode": mode, "trades": n, "per_trade": round(per, 4), "win_rate": round(win, 3),
           "backtest_per_trade": round(expect, 4), "backtest_win_rate": bt.get("win_rate"),
           "backtest_source": bt["source"], "scaled": scale != 1.0, "low": None, "high": None}
    book = "On %s" % LABEL[mode]
    if n < MIN_TRADES:
        out["verdict"] = "early"
        out["line"] = ("%s: %d completed trade%s so far %s; too early to tell against the backtest (it takes about %d)."
                       % (book, n, "" if n == 1 else "s", RUNS[mode], MIN_TRADES))
        return out
    var = max(0.0, (sq - pnl * pnl / n) / (n - 1))
    se = math.sqrt(var / n)
    low, high = expect - Z * se, expect + Z * se
    out.update(low=round(low, 4), high=round(high, 4))
    vs = "backtest" if bt["source"] == "out_of_sample" else "in-sample backtest"
    size = " at this book’s trade size" if scale != 1.0 else ""
    # A paper per-trade figure says what it is net of, as every paper P&L does (customer_text.PAPER_NET).
    net = " " + PAPER_NET_SHORT if mode == "paper" else ""
    figures = "%d trades %s: %s/trade%s vs %s %s/trade%s" % (n, RUNS[mode], _usd(per), net, vs, _usd(expect), size)
    if bt.get("win_rate") is not None:
        figures += "; won %s vs %s" % (_pct(win), _pct(bt["win_rate"]))
    band = "(%s to %s)" % (_usd(low), _usd(high))
    if per < low:
        out["verdict"] = "behind"
        out["line"] = "Behind its backtest on %s: %s. Below the usual range for %d trades %s." % (LABEL[mode], figures, n, band)
    elif per > high:
        out["verdict"] = "ahead"
        out["line"] = "Ahead of its backtest on %s: %s. Above the usual range for %d trades %s." % (LABEL[mode], figures, n, band)
    else:
        out["verdict"] = "within"
        out["line"] = "%s: %s. Within the backtest’s usual range." % (book, figures)
    return out


def checks(stats_by_mode: Dict[str, Dict], result: Optional[Dict], stake: Optional[float]) -> List[Dict]:
    """One comparison per book with a completed trade, live first."""
    bt = backtest_figures(result, stake)
    out = []
    for mode in BOOKS:
        c = book_check(mode, stats_by_mode.get(mode), bt)
        if c is not None:
            out.append(c)
    return out
