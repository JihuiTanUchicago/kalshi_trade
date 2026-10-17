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


def _dataset_with_micro(micro, n_contracts=40, minutes=15):
    """Same synthetic book as _dataset, but attach a micro-feature dict to every
    (ticker, decision_ts). `micro` is the per-frame feature dict to replicate."""
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n_contracts * minutes + 200)]
    markets, candles, mfeat = [], [], {}
    for k in range(n_contracts):
        open_ts = T0 + k * minutes * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        ticker = "M%d" % k
        markets.append({"ticker": ticker, "strike": 98.0, "close_time": close, "result": "yes"})
        for m in range(1, minutes + 1):
            ts = open_ts + m * 60
            candles.append({"ticker": ticker, "end_period_ts": ts, "yes_bid_close": 0.38, "yes_ask_close": 0.40})
            if micro is not None:
                mfeat[(ticker, ts)] = dict(micro)
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc, mfeat or None)


def test_spec_filters_on_orderbook_feature_and_runs():
    ds = _dataset_with_micro({"ob_imbalance": 0.9})
    # the micro feature reaches the snapshot
    assert ds.frames[0][1][0].features["ob_imbalance"] == 0.9
    s = specmod.validate({"side": "yes", "entry": {
        "min_edge": 0.1, "filters": [{"feature": "ob_imbalance", "op": ">=", "value": 0.5}]}})
    passing = backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1)
    # a filter the book clears does not suppress trades
    assert len(passing) == 40
    blocking = specmod.validate({"side": "yes", "entry": {
        "min_edge": 0.1, "filters": [{"feature": "ob_imbalance", "op": "<", "value": 0.0}]}})
    assert backtest.simulate(blocking, ds, ds.start_ts, ds.end_ts + 1) == []


def test_missing_micro_feature_degrades_gracefully():
    ds = _dataset_with_micro(None)  # no feature-builder rows at all
    assert "ob_imbalance" not in ds.frames[0][1][0].features
    s = specmod.validate({"side": "yes", "entry": {
        "min_edge": 0.1, "filters": [{"feature": "ob_imbalance", "op": ">=", "value": 0.5}]}})
    # a filter on an absent feature never matches -> no trades, no crash
    assert backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1) == []


def test_buys_at_the_ask_pays_fees_and_settles_on_result():
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}, "sizing": {"stake": 10.0, "max_positions": 1}})
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
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}, "exit": {"take_profit": 0.2}, "sizing": {"stake": 10.0, "max_positions": 1}})
    t = backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1)[0]
    assert t.reason == "take_profit" and t.exit_price == 0.70
    assert t.fees > 0.42  # entry fee + exit fee


def test_score_ignores_tiny_samples():
    assert backtest.score({"trades": 2, "pnl": 1000}) < backtest.score({"trades": 30, "pnl": 1})


# -- cross-contract (relative-value pairs) ------------------------------------


def _pair_dataset(n_events=12, minutes=15, bid=0.49, ask=0.51):
    """Two strikes per 15-minute event sharing one close_time. BTC sits flat at 100, so the
    90-strike settles YES (underpriced at ~0.50 -> long) and the 110-strike settles NO
    (overpriced -> short the YES / buy NO). A cross_strike pair should buy YES@90 + NO@110."""
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n_events * minutes + 200)]
    markets, candles = [], []
    for k in range(n_events):
        open_ts = T0 + k * minutes * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        for strike, result in ((90.0, "yes"), (110.0, "no")):
            ticker = "M%d_%d" % (k, int(strike))
            markets.append({"ticker": ticker, "strike": strike, "close_time": close, "result": result})
            for m in range(1, minutes + 1):
                candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                                "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


def test_cross_strike_pair_buys_cheap_leg_yes_and_dear_leg_no():
    ds = _pair_dataset()
    s = specmod.validate({
        "market": "btc15m",
        "entry": {"min_edge": 0.1, "max_spread": 0.05},
        "sizing": {"stake": 10.0, "max_positions": 1},
        "cross": {"pairing": "cross_strike", "legs": []},
    })
    trades = backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1)
    assert len(trades) == 12                       # one pair per event, max_positions=1
    t = trades[0]
    assert t.side == "pair" and "|" in t.ticker    # combined leg ticker "long|short"
    assert t.ticker.endswith("_110") and "_90" in t.ticker  # long the 90, short (NO) the 110
    assert round(t.entry_price, 2) == 1.02         # YES@0.51 + NO@(1-0.49)=0.51
    assert t.exit_price == 2.0                      # both legs resolve the model's way
    assert t.pnl > 0 and t.fees > 0                 # fees charged on BOTH legs


def test_cross_contract_merge_unions_frames_across_markets():
    a = _dataset(n_contracts=4)
    b = _dataset(n_contracts=4, spot_above=False, result="no")
    merged = backtest.merge_datasets([a, b], key="btc15m+btc15m", label="pair")
    assert merged.market.key == "btc15m+btc15m"
    assert merged.contracts == a.contracts + b.contracts
    assert len(merged.frames) == len(a.frames)      # same decision timestamps, snaps concatenated
    assert len(merged.frames[0][1]) == len(a.frames[0][1]) + len(b.frames[0][1])
