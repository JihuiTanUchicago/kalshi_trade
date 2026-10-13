from datetime import datetime, timezone

from app import backtest
from app import spec as specmod
from app.markets import MARKETS

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def _dataset(n_contracts=40, minutes=15, result="yes", ask=0.40, bid=0.38, spot_above=True):
    """Synthetic 15-minute contracts back to back. BTC sits 2% above (or below)
    every strike, so the GBM fair value is ~1 (or ~0)."""
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n_contracts * minutes + 200)]
    markets, candles = [], []
    strike = 98.0 if spot_above else 102.0
    for k in range(n_contracts):
        open_ts = T0 + k * minutes * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        ticker = "M%d" % k
        markets.append({"ticker": ticker, "strike": strike, "close_time": close, "result": result})
        for m in range(1, minutes + 1):
            candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60, "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


def test_buys_at_the_ask_pays_fees_and_settles_on_result():
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}})
    trades = backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1)
    assert len(trades) == 40  # one position per contract, max_positions=1
    t = trades[0]
    assert t.entry_price == 0.40 and t.qty == 25 and t.exit_price == 1.0 and t.reason == "settled"
    assert t.fees == 0.42  # ceil_cent(0.07 * 25 * 0.4 * 0.6) = 0.42 exactly
    assert round(t.pnl, 2) == round(25 * 0.6 - 0.42, 2)


def test_losing_side_loses_the_premium():
    ds = _dataset(result="no")
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})
    trades = backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1)
    assert all(t.exit_price == 0.0 and t.pnl < 0 for t in trades)


def test_what_if_fees_and_slippage_only_hurt():
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})
    base = backtest.evaluate(s, ds)["out_of_sample"]["pnl"]
    worse = backtest.evaluate(s, ds, backtest.WhatIf(fee_multiplier=2.0, slippage_cents=2))["out_of_sample"]["pnl"]
    free = backtest.evaluate(s, ds, backtest.WhatIf(fee_multiplier=0.0))["out_of_sample"]["pnl"]
    assert worse < base < free


def test_agent_view_hides_out_of_sample():
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})
    seen = backtest.evaluate(s, ds, include_oos=False)
    assert "out_of_sample" not in seen and "gates" not in seen and "equity" not in seen
    full = backtest.evaluate(s, ds)
    assert full["in_sample"]["trades"] + full["out_of_sample"]["trades"] == 40
    assert full["passed"] is True


def test_gates_fail_a_loser():
    ds = _dataset(result="no")
    full = backtest.evaluate(specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}}), ds)
    assert full["passed"] is False
    assert not next(g for g in full["gates"] if g["name"] == "Makes money on unseen data")["ok"]


def test_take_profit_exits_at_the_bid_with_a_second_fee():
    ds = _dataset(ask=0.40, bid=0.38)
    # Second minute of every contract: bid jumps to 0.70.
    for ts, snaps in ds.frames:
        for i, sn in enumerate(snaps):
            if (ts - T0) % 900 == 120:
                snaps[i] = sn.__class__(sn.contract, ts, 0.70, 0.72, dict(sn.features, yes_bid=0.70, yes_ask=0.72))
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}, "exit": {"take_profit": 0.2}})
    t = backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1)[0]
    assert t.reason == "take_profit" and t.exit_price == 0.70
    assert t.fees > 0.42  # entry fee + exit fee


def test_score_ignores_tiny_samples():
    assert backtest.score({"trades": 2, "pnl": 1000}) < backtest.score({"trades": 30, "pnl": 1})
