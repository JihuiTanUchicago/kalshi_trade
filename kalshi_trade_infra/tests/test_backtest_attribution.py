"""Conditional-edge attribution: slices a trade list's net edge by fixed price/side/session
regimes so the research agent can see WHERE its (leak-free research-fold) edge concentrates.
Pure over Trade lists - no DB."""
from datetime import datetime, timezone

from app import backtest
from app.markets import NEW_YORK


def _trade(entry_price, side, won, entry_ts, qty=10):
    exit_price = 1.0 if won else 0.0
    return backtest.Trade(ticker="M", side=side, qty=qty, entry_ts=entry_ts, entry_price=entry_price,
                          exit_ts=entry_ts + 900, exit_price=exit_price, fees=0.0, reason="settled", edge=0.1)


def _ts_at_et_hour(hour):
    """A unix ts whose New-York local hour is `hour` (session bucketing is in ET)."""
    base = datetime(2026, 1, 15, hour, 30, tzinfo=NEW_YORK)
    return int(base.astimezone(timezone.utc).timestamp())


def test_empty_trades_give_empty_attribution():
    assert backtest.attribution([]) == {}


def test_mean_net_return_matches_hand_math():
    # One cheap winner: net return = pnl / (qty*entry) = (10*(1-0.1)) / (10*0.1) = 9.0
    attr = backtest.attribution([_trade(0.10, "yes", True, _ts_at_et_hour(2))])
    assert attr["price"]["longshot_lt15c"] == {"mean_net": 9.0, "n": 1}
    assert attr["side"]["yes"] == {"mean_net": 9.0, "n": 1}
    assert attr["session"]["asia_overnight_0_7"] == {"mean_net": 9.0, "n": 1}


def test_price_bands_split_longshot_mid_favorite():
    trades = [_trade(0.05, "yes", False, _ts_at_et_hour(10)),   # longshot loser
              _trade(0.50, "yes", True, _ts_at_et_hour(10)),    # mid winner
              _trade(0.90, "yes", True, _ts_at_et_hour(10))]    # favorite winner
    price = backtest.attribution(trades)["price"]
    assert set(price) == {"longshot_lt15c", "mid_15_85c", "favorite_gt85c"}
    assert price["longshot_lt15c"]["mean_net"] < 0      # the loser
    assert price["mid_15_85c"]["mean_net"] > 0


def test_zero_cost_trades_are_skipped():
    # qty*entry_price == 0 cannot form a net return -> dropped, not a divide-by-zero.
    assert backtest.attribution([_trade(0.0, "no", True, _ts_at_et_hour(5))]) == {}


def test_session_buckets_follow_et_hour():
    attr = backtest.attribution([_trade(0.5, "no", True, _ts_at_et_hour(14))])  # US afternoon
    assert list(attr["session"]) == ["us_afternoon_13_16"]
    assert attr["side"] == {"no": {"mean_net": 1.0, "n": 1}}  # net = (1-0.5)/0.5 = 1.0
