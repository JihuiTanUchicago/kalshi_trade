"""DB access for the catalog-driven market universe (app/trading/markets.py reads this).

Kept in the repository layer (per AGENTS.md) so markets.py holds no inline SQL and the
generation filter is testable against FakeCursor. Returns plain rows; markets.py builds the
Market objects (so this module never imports markets.py — no import cycle)."""
from __future__ import annotations

from typing import Dict, Iterable, List


def deployable_series(cur, curated_series: Iterable[str], min_open: int, cap: int,
                      allowed_categories: List[str], recurring_freqs: List[str]) -> List[Dict]:
    """Rows of `kalshi_series` eligible to become deployable outcome-settled markets, most liquid
    first. Filters (all derivable from the enriched catalog):
      - open_markets >= min_open         (liquid + currently active)
      - frequency IN recurring_freqs     (recurs with a real backtest surface)
      - category  IN allowed_categories  (settles YES/NO on an event; excludes Crypto/Financials)
      - series_ticker not a curated series and not a multi-leg (MVE) parlay series
    category/frequency are NULL until catalog_collector enriches them, so a fresh DB simply returns
    no rows (markets.py then runs on the curated 19). `cap` bounds the collector + box load."""
    allowed = [c for c in allowed_categories if c]
    freqs = [f for f in recurring_freqs if f]
    if not allowed or not freqs:
        return []
    curated = [s for s in curated_series if s]
    params: List = [int(min_open)]
    sql = [
        "SELECT series_ticker, title, category, frequency, open_markets",
        "FROM kalshi_series",
        "WHERE open_markets >= %s",
        "AND category IN (%s)" % ",".join(["%s"] * len(allowed)),
        "AND frequency IN (%s)" % ",".join(["%s"] * len(freqs)),
        "AND UPPER(series_ticker) NOT LIKE '%%MVE%%'",
    ]
    params.extend(allowed)
    params.extend(freqs)
    if curated:
        sql.append("AND series_ticker NOT IN (%s)" % ",".join(["%s"] * len(curated)))
        params.extend(curated)
    sql.append("ORDER BY open_markets DESC, series_ticker ASC")
    sql.append("LIMIT %s")
    params.append(int(cap))
    cur.execute("\n".join(sql), tuple(params))
    return list(cur.fetchall())
