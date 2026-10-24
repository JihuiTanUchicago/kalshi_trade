"""Sportsbook consensus fair value for Kalshi game-winner contracts (KXNBAGAME, KXNHLGAME).

app/sports_odds_collect.py stores every bookmaker's two-way moneyline as it fetched it from The
Odds API into sports_odds, stamped with collected_at_utc. That fetch time is the known-at time:
a frame at ts only sees snapshots collected at or before ts, in research and live alike.

snapshot_features() is THE call both sides make per contract (via OddsBook.features, which
backtest.build_dataset and the engine's decision frames invoke exactly like the weather book):

    book_p_yes    median across books of the de-vigged probability this contract's team wins
    book_n        how many books priced the game in that snapshot
    book_age_min  minutes since that snapshot was collected
    book_edge     book_p_yes - mid (positive = YES looks cheap against the books)

Contract terms come from the ticker: KXNBAGAME-26OCT27PORLAL-POR is Portland (away) at the
Lakers (home) on 2026-10-27 (US date), the YES side being Portland.
"""
from __future__ import annotations

import bisect
import re
import statistics
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

# Kalshi series -> The Odds API sport key.
SPORTS = {"KXNBAGAME": "basketball_nba", "KXNHLGAME": "icehockey_nhl"}

# Kalshi team code -> a distinctive, normalized fragment of the team's full name as books print it.
TEAMS: Dict[str, Dict[str, str]] = {
    "basketball_nba": {
        "ATL": "hawks", "BKN": "nets", "BOS": "celtics", "CHA": "hornets", "CHI": "bulls", "CLE": "cavaliers",
        "DAL": "mavericks", "DEN": "nuggets", "DET": "pistons", "GSW": "warriors", "HOU": "rockets",
        "IND": "pacers", "LAC": "clippers", "LAL": "lakers", "MEM": "grizzlies", "MIA": "heat", "MIL": "bucks",
        "MIN": "timberwolves", "NOP": "pelicans", "NYK": "knicks", "OKC": "thunder", "ORL": "magic",
        "PHI": "76ers", "PHX": "suns", "POR": "trail blazers", "SAC": "kings", "SAS": "spurs",
        "TOR": "raptors", "UTA": "jazz", "WAS": "wizards",
    },
    "icehockey_nhl": {
        "ANA": "ducks", "BOS": "bruins", "BUF": "sabres", "CAR": "hurricanes", "CBJ": "blue jackets",
        "CGY": "flames", "CHI": "blackhawks", "COL": "avalanche", "DAL": "stars", "DET": "red wings",
        "EDM": "oilers", "FLA": "panthers", "LA": "los angeles kings", "MIN": "wild", "MTL": "canadiens",
        "NJ": "devils", "NSH": "predators", "NYI": "islanders", "NYR": "rangers", "OTT": "senators",
        "PHI": "flyers", "PIT": "penguins", "SEA": "kraken", "SJ": "sharks", "STL": "blues",
        "TB": "lightning", "TOR": "maple leafs", "UTA": "utah", "VAN": "canucks", "VGK": "golden knights",
        "WPG": "jets", "WSH": "capitals",
    },
}
# A snapshot older than this is ignored (a stalled collector must not freeze a pregame line).
MAX_AGE_MIN = 6 * 60.0

_TICKER = re.compile(r"^([A-Z0-9]+)-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)-([A-Z]+)$")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", "", s).strip()


def team_code(sport: str, name: str) -> Optional[str]:
    """A book's team name -> the Kalshi code, or None if it isn't one of the league's teams."""
    n = norm_name(name)
    hits = [code for code, frag in TEAMS.get(sport, {}).items() if frag in n]
    return hits[0] if len(hits) == 1 else None


def parse_contract(ticker: str) -> Optional[Tuple[str, date, str, str, str]]:
    """(sport, US game date, away code, home code, YES team code), or None if not a game contract
    of a supported league (or the matchup segment can't be split into two known teams)."""
    m = _TICKER.match(ticker or "")
    if not m:
        return None
    series, yy, mon, dd, pair, yes = m.groups()
    sport = SPORTS.get(series)
    if sport is None or mon not in _MONTHS:
        return None
    try:
        day = date(2000 + int(yy), _MONTHS[mon], int(dd))
    except ValueError:
        return None
    codes = TEAMS[sport]
    splits = [(pair[:i], pair[i:]) for i in range(2, len(pair) - 1) if pair[:i] in codes and pair[i:] in codes]
    if len(splits) != 1 or yes not in splits[0]:
        return None
    away, home = splits[0]
    return sport, day, away, home, yes


def american_to_prob(price: float) -> Optional[float]:
    p = float(price)
    if p >= 100:
        return 100.0 / (p + 100.0)
    if p <= -100:
        return -p / (-p + 100.0)
    return None


def devig(p_home: float, p_away: float) -> Optional[float]:
    """Home win probability with the book's margin removed proportionally."""
    s = p_home + p_away
    return p_home / s if s > 0 else None


class OddsBook:
    """One league's collected snapshots, indexed by (game date, away, home) for as-of lookups.

    rows: (collected_at_ts, commence_ts, home_code, away_code, book, p_home_devigged), any order."""

    def __init__(self, rows: Iterable[Tuple[int, int, str, str, str, float]]):
        snaps: Dict[Tuple[str, str], Dict[int, List[Tuple[int, float]]]] = {}
        for collected, commence, home, away, _book, p_home in rows:
            snaps.setdefault((away, home), {}).setdefault(int(collected), []).append((int(commence), float(p_home)))
        self._snaps = {k: sorted(v.items()) for k, v in snaps.items()}
        self._keys = {k: [t for t, _ in v] for k, v in self._snaps.items()}

    def latest(self, day: date, away: str, home: str, ts: int) -> Optional[Tuple[int, float, int]]:
        """(collected_at, median de-vigged home probability, books) from the newest snapshot known
        by ts for the game on `day` (US date: commence within 30h after that date's 00:00 UTC
        covers every North American start time), younger than MAX_AGE_MIN."""
        keys = self._keys.get((away, home))
        if not keys:
            return None
        lo = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        hi = lo + 30 * 3600
        i = bisect.bisect_right(keys, ts) - 1
        while i >= 0:
            collected, quotes = self._snaps[(away, home)][i]
            if (ts - collected) / 60.0 > MAX_AGE_MIN:
                return None
            ps = [p for commence, p in quotes if lo <= commence < hi]
            if ps:
                return collected, statistics.median(ps), len(ps)
            i -= 1
        return None

    def features(self, ticker: str, strike: float, ts: int, yes_bid: Optional[float], yes_ask: Optional[float],
                 frame_feats: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        return snapshot_features(self, ticker, ts, yes_bid, yes_ask)


def snapshot_features(book: Optional[OddsBook], ticker: str, ts: int,
                      yes_bid: Optional[float], yes_ask: Optional[float]) -> Dict[str, float]:
    """Sportsbook consensus features for one game contract at ts ({} when nothing usable)."""
    if book is None:
        return {}
    terms = parse_contract(ticker)
    if terms is None:
        return {}
    _sport, day, away, home, yes = terms
    got = book.latest(day, away, home, ts)
    if got is None:
        return {}
    collected, p_home, n = got
    p = p_home if yes == home else 1.0 - p_home
    out = {"book_p_yes": p, "book_n": float(n), "book_age_min": (ts - collected) / 60.0}
    if yes_bid is not None and yes_ask is not None:
        out["book_edge"] = p - (float(yes_bid) + float(yes_ask)) / 2.0
    return out


def book_for_series(series: str, load_rows) -> Optional[OddsBook]:
    """The OddsBook for a supported game series, else None. load_rows(sport) returns
    repository.load_sports_odds rows."""
    sport = SPORTS.get(series)
    return OddsBook(load_rows(sport)) if sport else None


FEATURE_DOCS = {
    "book_p_yes": "NBA/NHL game markets only: median across US sportsbooks of the de-vigged moneyline "
                  "probability that this contract's team wins, from the latest odds snapshot before the frame",
    "book_n": "NBA/NHL game markets only: number of sportsbooks behind book_p_yes",
    "book_age_min": "NBA/NHL game markets only: minutes since the odds snapshot behind book_p_yes was taken",
    "book_edge": "NBA/NHL game markets only: book_p_yes minus the contract's mid (positive = YES cheap vs books)",
}
