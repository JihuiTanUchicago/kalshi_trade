"""Sportsbook consensus features for NBA/NHL game contracts: point-in-time, and identical in
research datasets and live engine snapshots (app/sports_odds.py, app/sports_odds_collect.py)."""
from datetime import datetime, timezone

import pytest

from app import backtest, engine
from app import sports_odds as so
from app import sports_odds_collect as soc
from app.markets import FEATURES, MARKETS, Contract


def _ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


def test_tickers_split_into_away_home_and_yes_team():
    assert so.parse_contract("KXNBAGAME-26OCT27PORLAL-POR")[2:] == ("POR", "LAL", "POR")
    assert so.parse_contract("KXNHLGAME-26OCT23TBCOL-COL")[2:] == ("TB", "COL", "COL")
    assert so.parse_contract("KXNHLGAME-26OCT30SEACGY-SEA")[1].isoformat() == "2026-10-30"
    assert so.parse_contract("KXNBAGAME-26OCT05LIONYK-NYK") is None   # exhibition vs a non-NBA side
    assert so.parse_contract("KXHIGHNY-26OCT23-B59.5") is None


def test_every_team_name_maps_to_exactly_one_code():
    names = {
        "basketball_nba": ["Portland Trail Blazers", "Los Angeles Lakers", "Los Angeles Clippers", "Sacramento Kings",
                           "Philadelphia 76ers", "Golden State Warriors", "New Orleans Pelicans", "Utah Jazz"],
        "icehockey_nhl": ["Montréal Canadiens", "St Louis Blues", "Columbus Blue Jackets", "Los Angeles Kings",
                          "Utah Mammoth", "Tampa Bay Lightning", "Vegas Golden Knights", "Winnipeg Jets"],
    }
    want = {"basketball_nba": ["POR", "LAL", "LAC", "SAC", "PHI", "GSW", "NOP", "UTA"],
            "icehockey_nhl": ["MTL", "STL", "CBJ", "LA", "UTA", "TB", "VGK", "WPG"]}
    for sport, ns in names.items():
        assert [so.team_code(sport, n) for n in ns] == want[sport]


def test_devig_removes_the_margin():
    ph, pa = so.american_to_prob(-150), so.american_to_prob(130)
    assert ph + pa > 1.0
    assert so.devig(ph, pa) == pytest.approx(0.6 / (0.6 + 100 / 230))


PAYLOAD = [{
    "id": "ev1", "commence_time": "2026-10-28T02:00:00Z", "home_team": "Los Angeles Lakers",
    "away_team": "Portland Trail Blazers",
    "bookmakers": [
        {"key": "draftkings", "last_update": "2026-10-27T20:00:00Z",
         "markets": [{"key": "h2h", "outcomes": [{"name": "Los Angeles Lakers", "price": -200},
                                                 {"name": "Portland Trail Blazers", "price": 170}]}]},
        {"key": "fanduel", "last_update": "2026-10-27T20:01:00Z",
         "markets": [{"key": "h2h", "outcomes": [{"name": "Los Angeles Lakers", "price": -180},
                                                 {"name": "Portland Trail Blazers", "price": 150}]}]},
        {"key": "oddball", "markets": [{"key": "h2h", "outcomes": [{"name": "Los Angeles Lakers", "price": -180}]}]},
    ]}]


def test_parse_events_keeps_two_way_prices_per_book():
    collected = datetime(2026, 10, 27, 21, 5)
    rows = soc.parse_events("basketball_nba", PAYLOAD, collected)
    assert [(r[3], r[4], r[5]) for r in rows] == [("LAL", "POR", "draftkings"), ("LAL", "POR", "fanduel")]
    assert all(r[-1] == collected for r in rows)


def _book_rows(collected):
    rows = soc.parse_events("basketball_nba", PAYLOAD, collected)
    to_ts = lambda d: int(d.replace(tzinfo=timezone.utc).timestamp())  # noqa: E731
    return [(to_ts(r[10]), to_ts(r[2]), r[3], r[4], r[5], r[9]) for r in rows]


def test_book_is_point_in_time_and_takes_the_median():
    collected = datetime(2026, 10, 27, 21, 5)
    book = so.OddsBook(_book_rows(collected))
    t_c = int(collected.replace(tzinfo=timezone.utc).timestamp())
    assert so.snapshot_features(book, "KXNBAGAME-26OCT27PORLAL-LAL", t_c - 60, 0.6, 0.62) == {}
    f = so.snapshot_features(book, "KXNBAGAME-26OCT27PORLAL-POR", t_c + 600, 0.30, 0.34)
    p_dk = 1 - so.devig(so.american_to_prob(-200), so.american_to_prob(170))
    p_fd = 1 - so.devig(so.american_to_prob(-180), so.american_to_prob(150))
    assert f["book_p_yes"] == pytest.approx((p_dk + p_fd) / 2) and f["book_n"] == 2.0
    assert f["book_age_min"] == pytest.approx(10.0) and f["book_edge"] == pytest.approx(f["book_p_yes"] - 0.32)
    stale = t_c + int(so.MAX_AGE_MIN * 60) + 60
    assert so.snapshot_features(book, "KXNBAGAME-26OCT27PORLAL-POR", stale, 0.3, 0.34) == {}


def test_registered_features():
    for name in ("book_p_yes", "book_n", "book_age_min", "book_edge"):
        assert name in FEATURES


def test_research_and_live_compute_identical_book_features():
    collected = datetime(2026, 10, 27, 21, 5)
    rows = _book_rows(collected)
    ts = _ts("2026-10-27 22:00")
    close = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)
    quotes = [engine.LiveQuote(Contract(t, 0.0, close, "KXNBAGAME"), b, a, 5.0, 5.0)
              for t, b, a in (("KXNBAGAME-26OCT27PORLAL-POR", 0.30, 0.34), ("KXNBAGAME-26OCT27PORLAL-LAL", 0.66, 0.70))]
    markets = [{"ticker": q.contract.ticker, "strike": 0.0, "close_time": close, "result": "no"} for q in quotes]
    candles = [(q.contract.ticker, ts, q.yes_bid, q.yes_ask) for q in quotes]
    book = so.book_for_series("KXNBAGAME", lambda sport: rows)
    ds = backtest.build_dataset(MARKETS["nba_game"], markets, candles, [], forecasts=book)
    research = {s.contract.ticker: s.features for s in ds.frames[0][1]}
    seen = {}

    def odds(sport, as_of):
        seen["args"] = (sport, as_of)
        return rows

    src = engine.Sources(quotes=lambda m: quotes, spot=lambda m: None, odds=odds)
    snaps, _ = engine._cross_market_frame(["nba_game"], src, ts)
    live = {s.contract.ticker: s.features for s in snaps}
    assert seen["args"] == ("basketball_nba", ts)
    keys = ("book_p_yes", "book_n", "book_age_min", "book_edge")
    for t in research:
        assert {k: research[t][k] for k in keys} == {k: live[t][k] for k in keys}
    assert research["KXNBAGAME-26OCT27PORLAL-POR"]["book_p_yes"] + research["KXNBAGAME-26OCT27PORLAL-LAL"][
        "book_p_yes"] == pytest.approx(1.0)


class _Resp:
    def __init__(self, code, body, remaining):
        self.status_code, self._body, self.headers = code, body, {"x-requests-remaining": str(remaining)}

    def json(self):
        return self._body


class _Cur:
    def __init__(self):
        self.rows, self.rowcount = [], 0

    def executemany(self, sql, vals):
        assert sql.startswith("INSERT IGNORE INTO sports_odds")
        self.rows.extend(vals)
        self.rowcount = len(vals)


def test_collect_stops_at_the_credit_reserve_and_isolates_failures():
    calls = []

    def get(url, params, timeout):
        calls.append(url)
        return _Resp(200, PAYLOAD, soc.RESERVE_CREDITS - 1)

    cur = _Cur()
    stats = soc.collect(cur, "k", sports=["basketball_nba", "icehockey_nhl"], get=get,
                        now=datetime(2026, 10, 27, 21, 5, tzinfo=timezone.utc))
    assert len(calls) == 1 and stats["inserted"] == 2 and "credits left" in stats["errors"][0]


def test_no_key_is_a_quiet_no_op(monkeypatch, capsys):
    monkeypatch.setattr(soc, "api_key", lambda: None)
    soc.main()
    assert "no Odds API key" in capsys.readouterr().out
