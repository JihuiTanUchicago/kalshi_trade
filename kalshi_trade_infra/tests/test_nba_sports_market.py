"""Kalshi SPORTS markets (NBA game moneyline, series KXNBAGAME): research/backtest only.

A sports contract is a binary YES/NO that settles on the game result - structurally like
the crypto binaries, but with NO strike and NO underlying price feed. These tests prove the
backtester builds a dataset over such contracts from their own price history (no spot path),
settles on the outcome, and that the crypto-only GBM DSL degrades to no-trades (never crashes)
on a sports market. The existing BTC markets are unaffected.
"""
from datetime import datetime, timezone

import pytest

from app import backtest
from app.research import sandbox
from app import spec as specmod
from app.markets import MARKETS

# Code strategies (the research vehicle for sports) need an OS sandbox; skip the real-trade
# test where none exists (mirrors tests/test_code_strategy.py).
needs_confiner = pytest.mark.skipif(not sandbox.os_sandbox_available(),
                                    reason="no OS-level sandbox (sandbox-exec/bwrap/firejail) here")

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def _sports_dataset(n_games=12, minutes=20, result="yes", bid=0.58, ask=0.60):
    """Synthetic NBA-style games: each is one binary market with `minutes` of 1-minute
    price candles leading into its close. No underlying price series (btc=[]) and a 0.0
    strike sentinel, exactly like the KXNBAGAME rows the collector stores."""
    markets, candles = [], []
    for k in range(n_games):
        open_ts = T0 + k * (minutes + 5) * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        ticker = "KXNBAGAME-G%d-TEAM" % k
        markets.append({"ticker": ticker, "strike": 0.0, "close_time": close, "result": result})
        for m in range(1, minutes):  # last minute == close_time (tte 0) is skipped by snapshot
            candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                            "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["nba_game"], markets, candles, btc=[])


def test_nba_market_is_tradeable_sports_market():
    m = MARKETS["nba_game"]
    assert m.series == "KXNBAGAME" and m.candle_minutes == 1
    assert m.underlying is None          # no spot path - trades on book features alone
    assert m.deployable is True          # live engine ticks it (prices off the Kalshi book)
    assert m.is_target_event(datetime.now(timezone.utc)) is True  # no close-hour filter


def test_build_dataset_over_sports_contracts():
    ds = _sports_dataset()
    assert ds.contracts == 12
    assert len(ds.frames) > 0
    snap = ds.frames[0][1][0]
    # Price / order-book features are present...
    for feat in ("yes_bid", "yes_ask", "spread", "mid", "tte_min", "hour_et"):
        assert feat in snap.features
    # ...but the strike-vs-spot features never exist for a market with no underlying.
    for absent in ("spot", "moneyness", "z_score", "vol_60m"):
        assert absent not in snap.features
    # Settlement is outcome-based: every contract carries its game result.
    assert set(ds.results.values()) == {"yes"}


@needs_confiner
def test_code_strategy_settles_on_game_outcome():
    ds = _sports_dataset(result="yes", bid=0.58, ask=0.60)
    code = ("def signals(window):\n"
            "    return [[{'ticker': c['ticker'], 'side': 'yes'} for c in fr['contracts']]\n"
            "            for fr in window['frames']]\n")
    spec = specmod.validate({"market": "nba_game", "code": code,
                             "sizing": {"stake": 10.0, "max_positions": 1}})
    trades = backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)
    assert len(trades) == 12                       # one position per game, max_positions=1
    t = trades[0]
    assert t.entry_price == 0.60                   # bought the ask
    assert t.exit_price == 1.0 and t.reason == "settled"  # YES game resolved YES
    assert t.pnl > 0 and t.fees > 0


def test_dsl_spec_on_sports_degrades_to_no_trades_not_crash():
    ds = _sports_dataset()
    # The crypto GBM DSL has no fair value without a strike/spot, so it must produce zero
    # trades (fair_yes -> None), not raise a KeyError on the missing moneyness/vol features.
    s = specmod.validate({"market": "nba_game", "side": "yes", "entry": {"min_edge": 0.01}})
    assert backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1) == []


def test_btc_snapshot_still_carries_strike_features():
    """Regression: guarding the spot features behind `"spot" in f` must not strip them from
    an underlying market."""
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(300)]
    close = datetime.fromtimestamp(T0 + 900, tz=timezone.utc)
    markets = [{"ticker": "B0", "strike": 98.0, "close_time": close, "result": "yes"}]
    candles = [{"ticker": "B0", "end_period_ts": T0 + m * 60, "yes_bid_close": 0.4, "yes_ask_close": 0.42}
               for m in range(1, 15)]
    ds = backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)
    feats = ds.frames[0][1][0].features
    assert "spot" in feats and "moneyness" in feats and "z_score" in feats


# --- Live-engine path: the sports market is now tradeable, so the live feed must handle a
# strikeless, spot-less market exactly as the backtester does. ---

def test_fetch_spot_series_none_for_sports():
    """A sports market has no underlying price product, so the live engine fetches NO spot
    series for it (and never hits Coinbase) - the snapshot trades on the book alone."""
    from app import engine
    assert engine.fetch_spot_series(MARKETS["nba_game"]) is None


def test_fetch_quotes_keeps_strikeless_sports_contracts(monkeypatch):
    """fetch_quotes must keep a sports contract that has no floor_strike (0.0 sentinel), but
    still skip a strikeless contract on an UNDERLYING market (there a strike is required)."""
    from app import engine
    payload = {"markets": [
        {"ticker": "KXNBAGAME-G1-TEAM", "floor_strike": None, "close_time": "2030-01-01T00:00:00Z",
         "yes_bid_dollars": 0.58, "yes_ask_dollars": 0.60,
         "yes_bid_size_fp": 100.0, "yes_ask_size_fp": 120.0},
    ], "cursor": None}
    monkeypatch.setattr(engine, "api_get", lambda *a, **k: payload)

    sports = engine.fetch_quotes(MARKETS["nba_game"])
    assert len(sports) == 1
    assert sports[0].contract.strike == 0.0                 # sentinel, never read without a spot
    assert sports[0].contract.series == "KXNBAGAME"
    assert sports[0].yes_ask == 0.60

    # Same strikeless row on an underlying market (BTC) is unusable -> skipped.
    assert engine.fetch_quotes(MARKETS["btc15m"]) == []


def test_sports_snapshot_tradeable_without_spot():
    """The live tick builds a sports snapshot from feats={} (no spot). It must be tradeable and
    carry only book features - the same shape the backtest produces."""
    from app.markets import Contract, snapshot
    c = Contract("KXNBAGAME-G1-TEAM", 0.0, datetime.fromtimestamp(T0 + 600, tz=timezone.utc), "KXNBAGAME")
    snap = snapshot({}, c, T0, 0.58, 0.60)          # feats={} is what tick_market passes for sports
    assert snap is not None
    for feat in ("yes_bid", "yes_ask", "spread", "mid", "tte_min", "hour_et"):
        assert feat in snap.features
    for absent in ("spot", "moneyness", "z_score"):
        assert absent not in snap.features


def test_crypto_markets_are_deployable():
    """The crypto research markets were flipped tradeable; each must have a Coinbase product
    the generalized live spot fetch can use."""
    for key in ("eth15m", "eth_daily", "sol_daily", "xrp_daily"):
        m = MARKETS[key]
        assert m.deployable is True and m.underlying and m.underlying.endswith("-USD")
