"""Widened tradeable universe: the crypto 15-minute (strike + Coinbase spot) and the
outcome-settled sports/weather markets added alongside BTC/ETH/NBA.

These prove, with no live DB or network, that each new market (a) is present and deployable
with structurally valid config, (b) builds a backtest dataset from synthetic data of the right
shape, and (c) the live-engine quote/spot path treats it correctly. TAO stays research-only.
Mirrors tests/test_nba_sports_market.py.
"""
from datetime import datetime, timezone

from app import backtest, engine, markets
from app.markets import MARKETS, Contract, snapshot

T0 = 1_800_000_000 - 1_800_000_000 % 3600

# The markets added in this change, by model.
NEW_STRIKE = ["sol15m", "xrp15m", "doge15m", "near15m", "zec15m", "hype15m"]      # underlying + spot
NEW_OUTCOME = ["nfl_game", "nhl_game", "ncaaf_game", "mlb_game", "epl_game", "high_ny"]  # underlying=None


def test_new_strike_markets_present_and_valid():
    for key in NEW_STRIKE:
        m = MARKETS[key]
        assert m.deployable is True
        assert m.kind == "binary"
        assert m.underlying and m.underlying.endswith("-USD")   # has a Coinbase spot product
        assert m.candle_minutes == 1 and m.history_days == markets.CRYPTO_15M_HISTORY_DAYS
        assert m.close_hour_et is None                           # 15M ladder: every window, no daily filter


def test_new_outcome_markets_present_and_valid():
    for key in NEW_OUTCOME:
        m = MARKETS[key]
        assert m.deployable is True
        assert m.kind == "binary"
        assert m.underlying is None                              # outcome-settled: no spot/strike
        assert m.series.startswith("KX")


def test_tao_still_research_only():
    tao = [k for k, m in MARKETS.items() if m.kind == "spot"]
    assert tao and all(MARKETS[k].deployable is False for k in tao)   # execution still blocked


# -- backtest datasets build for each model from synthetic data ------------------

def _strike_dataset(market_key, strike=100.0, spot=100.0, bid=0.40, ask=0.42):
    """A single strike contract with a flat spot path (like the btc regression in the nba test)."""
    m = MARKETS[market_key]
    btc = [(T0 - 7200 + 60 * i, spot) for i in range(300)]
    close = datetime.fromtimestamp(T0 + 900, tz=timezone.utc)
    markets = [{"ticker": "C0", "strike": strike, "close_time": close, "result": "yes"}]
    candles = [{"ticker": "C0", "end_period_ts": T0 + mm * 60, "yes_bid_close": bid, "yes_ask_close": ask}
               for mm in range(1, 15)]
    return backtest.build_dataset(m, markets, candles, btc)


def _outcome_dataset(market_key, minutes=20, result="yes", bid=0.58, ask=0.60):
    """A synthetic outcome-settled event (no spot series), like the nba dataset."""
    m = MARKETS[market_key]
    open_ts = T0
    close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
    markets = [{"ticker": "G0", "strike": 0.0, "close_time": close, "result": result}]
    candles = [{"ticker": "G0", "end_period_ts": open_ts + mm * 60, "yes_bid_close": bid, "yes_ask_close": ask}
               for mm in range(1, minutes)]
    return backtest.build_dataset(m, markets, candles, btc=[])


def test_strike_market_builds_dataset_with_spot_features():
    ds = _strike_dataset("sol15m")
    assert len(ds.frames) > 0
    feats = ds.frames[0][1][0].features
    for f in ("spot", "moneyness", "z_score", "yes_bid", "yes_ask"):
        assert f in feats


def test_outcome_market_builds_dataset_book_only():
    ds = _outcome_dataset("nfl_game")
    assert len(ds.frames) > 0
    feats = ds.frames[0][1][0].features
    for f in ("yes_bid", "yes_ask", "spread", "mid", "tte_min", "hour_et"):
        assert f in feats
    for absent in ("spot", "moneyness", "z_score"):          # no underlying -> no strike-vs-spot math
        assert absent not in feats
    assert set(ds.results.values()) == {"yes"}


# -- live-engine path ------------------------------------------------------------

def test_fetch_spot_series_none_for_outcome_markets():
    for key in NEW_OUTCOME:
        assert engine.fetch_spot_series(MARKETS[key]) is None   # never hits Coinbase, no spot


def test_fetch_quotes_keeps_strikeless_outcome_contract(monkeypatch):
    payload = {"markets": [
        {"ticker": "KXNFLGAME-G1-TEAM", "floor_strike": None, "close_time": "2030-01-01T00:00:00Z",
         "yes_bid_dollars": 0.55, "yes_ask_dollars": 0.57,
         "yes_bid_size_fp": 80.0, "yes_ask_size_fp": 90.0},
    ], "cursor": None}
    monkeypatch.setattr(engine, "api_get", lambda *a, **k: payload)
    q = engine.fetch_quotes(MARKETS["nfl_game"])
    assert len(q) == 1 and q[0].contract.strike == 0.0 and q[0].contract.series == "KXNFLGAME"
    # The same strikeless row on a strike market (sol15m) is unusable -> skipped.
    assert engine.fetch_quotes(MARKETS["sol15m"]) == []


def test_early_closing_outcome_contract_measures_expiry_from_its_expected_resolution(monkeypatch):
    # Shapes from the live KXNFL1HSPREAD book on 2026-10-25: a backstop close_time two days after the
    # game, the half's scheduled end as expected_expiration_time. Research reads settled markets,
    # whose close_time is when they actually closed, so live tte_min must count to the earlier time.
    row = {"floor_strike": None, "yes_bid_dollars": 0.45, "yes_ask_dollars": 0.47,
           "yes_bid_size_fp": 80.0, "yes_ask_size_fp": 90.0}
    payload = {"markets": [
        dict(row, ticker="KXNFLGAME-A", close_time="2030-01-03T17:00:00Z",
             expected_expiration_time="2030-01-01T20:00:00Z", can_close_early=True),
        # Can't close early, or the expected time is after the close: close_time stands.
        dict(row, ticker="KXNFLGAME-B", close_time="2030-01-03T17:00:00Z",
             expected_expiration_time="2030-01-01T20:00:00Z", can_close_early=False),
        dict(row, ticker="KXNFLGAME-C", close_time="2030-01-03T17:00:00Z",
             expected_expiration_time="2030-01-05T20:00:00Z", can_close_early=True),
    ], "cursor": None}
    monkeypatch.setattr(engine, "api_get", lambda *a, **k: payload)
    closes = {q.contract.ticker: q.contract.close_time for q in engine.fetch_quotes(MARKETS["nfl_game"])}
    assert closes == {"KXNFLGAME-A": datetime(2030, 1, 1, 20, tzinfo=timezone.utc),
                      "KXNFLGAME-B": datetime(2030, 1, 3, 17, tzinfo=timezone.utc),
                      "KXNFLGAME-C": datetime(2030, 1, 3, 17, tzinfo=timezone.utc)}
    # A strike market closes on schedule: its close_time is kept even when it can close early.
    strike = dict(payload["markets"][0], floor_strike=100.0)
    assert engine.decision_close_time(MARKETS["sol15m"], strike) == datetime(2030, 1, 3, 17, tzinfo=timezone.utc)


def test_outcome_snapshot_tradeable_without_spot():
    c = Contract("KXHIGHNY-26OCT16-T82", 0.0, datetime.fromtimestamp(T0 + 600, tz=timezone.utc), "KXHIGHNY")
    snap = snapshot({}, c, T0, 0.30, 0.33)
    assert snap is not None and "spot" not in snap.features and "mid" in snap.features
