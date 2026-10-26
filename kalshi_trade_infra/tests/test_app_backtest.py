from datetime import datetime, timezone

from app import backtest
from app import spec as specmod
from app.markets import MARKETS

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def test_the_strategy_equity_curve_keeps_a_one_trade_crash_and_its_exact_end():
    # Display only (evaluate's equity, the kalshi-dev second line); the gates and metrics read every
    # trade. Every 2,000/160th point used to step over a crash that recovered on the next trade.
    curve = [(T0 + 60 * i, float(i)) for i in range(2000)]
    curve[1013] = (T0 + 60 * 1013, -500.0)
    assert 1013 not in [int(i * 2000 / 160) for i in range(159)]  # the old rule's picks
    out = backtest._downsample(curve)
    assert len(out) <= backtest.EQUITY_POINTS
    assert (T0 + 60 * 1013, -500.0) in out  # the crash, as the real point
    assert out[0] == curve[0] and out[-1] == curve[-1]
    assert [ts for ts, _ in out] == sorted(ts for ts, _ in out)
    assert backtest._downsample(curve[:100]) == curve[:100]  # short curves are untouched


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


def _dataset_predictive_micro(n_contracts=60, minutes=15):
    """Synthetic book where ob_imbalance PREDICTS the outcome: even contracts settle YES with high
    imbalance, odd settle NO with low imbalance. A logistic fit on ob_imbalance should learn a
    positive weight. Spot sits above every strike so GBM is NOT the source of signal here."""
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n_contracts * minutes + 200)]
    markets, candles, mfeat = [], [], {}
    for k in range(n_contracts):
        open_ts = T0 + k * minutes * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        ticker = "M%d" % k
        yes = (k % 2 == 0)
        markets.append({"ticker": ticker, "strike": 98.0, "close_time": close,
                        "result": "yes" if yes else "no"})
        imb = 0.8 if yes else -0.8
        for m in range(1, minutes + 1):
            ts = open_ts + m * 60
            candles.append({"ticker": ticker, "end_period_ts": ts, "yes_bid_close": 0.38, "yes_ask_close": 0.40})
            mfeat[(ticker, ts)] = {"ob_imbalance": imb}
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc, mfeat)


def test_fit_spec_on_research_freezes_a_logistic_learned_on_the_data():
    ds = _dataset_predictive_micro()
    unfit = specmod.validate({"side": "yes", "model": {"kind": "logistic", "features": ["ob_imbalance"]},
                              "entry": {"min_edge": 0.1}})
    # an unfitted learned model trades nothing (fair_yes is None), so the gate fails it honestly
    assert backtest.simulate(unfit, ds, ds.start_ts, ds.end_ts + 1) == []
    fitted = backtest.fit_spec_on_research(unfit, ds)
    assert specmod.is_fitted(fitted) and fitted["model"]["coef"][0] > 0  # learned the positive sign
    # the frozen model prices high-imbalance (yes-settling) frames high -> it buys and wins there
    trades = backtest.simulate(fitted, ds, ds.start_ts, ds.end_ts + 1)
    assert trades and all(t.side == "yes" for t in trades)
    assert sum(t.pnl for t in trades) > 0


def test_fit_spec_leaves_too_small_a_sample_unfitted():
    ds = _dataset_predictive_micro(n_contracts=4)  # 4*15 = 60 rows < MIN_FIT_SAMPLES
    unfit = specmod.validate({"model": {"kind": "logistic", "features": ["ob_imbalance"]}})
    out = backtest.fit_spec_on_research(unfit, ds)
    assert not specmod.is_fitted(out)  # unchanged: no model fit on a thin sample


def test_fit_diag_reports_why_a_model_was_left_unfitted():
    ds = _dataset_with_micro(None)  # ob_imbalance is null on every row
    unfit = specmod.validate({"model": {"kind": "logistic", "features": ["ob_imbalance"]}})
    diag = {}
    out = backtest.fit_spec_on_research(unfit, ds, diag)
    assert not specmod.is_fitted(out)
    assert diag["coverage"]["ob_imbalance"] == 0.0 and diag["n_usable"] == 0
    assert "ob_imbalance" in diag["reason"] and "null" in diag["reason"] and "need 200" in diag["reason"]


def test_zero_trade_reason_names_the_binding_filter():
    ds = _dataset()  # all-yes synthetic book, no micro features attached
    s = specmod.validate({"side": "yes", "entry": {
        "min_edge": 0.1, "filters": [{"feature": "ob_imbalance", "op": ">", "value": 0.02}]}})
    assert backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1) == []
    reason = backtest.zero_trade_reason(s, ds)
    assert reason.startswith("0 trades") and "ob_imbalance>0.02" in reason


def test_feature_coverage_flags_populated_vs_empty_features():
    cov = backtest.feature_coverage(_dataset_with_micro({"ob_imbalance": 0.9}))
    assert cov["ob_imbalance"] == 100 and cov["spot"] == 100  # populated here
    assert cov["trades_60s"] == 0  # a micro feature this market never carried


def test_feature_ranges_show_where_each_populated_feature_sits():
    """The proposer sees p10/p50/p90 per populated feature, so it can't cut below a floor the data
    never reaches (fcst_age_h is never under 0.5h on an hourly weather market)."""
    rng = backtest.feature_ranges(_dataset_with_micro({"ob_imbalance": 0.9}))
    assert rng["ob_imbalance"] == [0.9, 0.9, 0.9]
    assert "trades_60s" not in rng  # an empty feature has no range
    assert all(len(v) == 3 and v[0] <= v[1] <= v[2] for v in rng.values())


def test_develop_turn_lists_the_populated_features():
    """The develop turn (where theses get abandoned) sees which features exist and their range."""
    from app import agent
    ds = _dataset_with_micro({"ob_imbalance": 0.9})
    block = agent._feature_block(ds)
    assert "ob_imbalance 100% [0.9, 0.9, 0.9]" in block and "trades_60s" not in block
    assert agent._feature_block(ds) is block  # cached per dataset
    ins = backtest.metrics([], 10.0, 1.0)
    ins.pop("_curve", None)
    t = {"thesis": "x", "spec": {}, "in_sample": ins}
    assert "ob_imbalance 100%" in agent._develop_prompt({}, t, [], 0, ds)
    assert agent._feature_block(None) == ""


def test_fit_spec_is_a_noop_for_gbm_and_already_fitted():
    ds = _dataset_predictive_micro(n_contracts=4)
    gbm = specmod.validate({"side": "yes"})
    assert backtest.fit_spec_on_research(gbm, ds) is gbm
    frozen = specmod.validate({"model": {"kind": "logistic", "features": ["ob_imbalance"],
                                         "coef": [1.0], "intercept": 0.0}})
    assert backtest.fit_spec_on_research(frozen, ds) is frozen  # never re-fits a frozen model


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


def test_take_profit_exits_at_the_bid_with_a_second_fee(monkeypatch):
    monkeypatch.setattr(backtest, "FILL_MODEL", "signal_bar")  # legacy same-bar fill semantics
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


def _trade(ticker, entry_price, pnl, i):
    qty = int(5 / entry_price)
    exit_price = entry_price + (pnl + 0.0) / qty
    return backtest.Trade(ticker, "yes", qty, T0 + 60 * i, entry_price, T0 + 60 * i + 900, exit_price, 0.0,
                          "settle", 0.05)


def test_event_cluster_pools_the_same_close_across_series():
    assert backtest.event_cluster("KXBTCD-26OCT2517-T80000") == backtest.event_cluster("KXETHD-26OCT2517-T4000")
    assert backtest.event_cluster("KXBTC15M-26OCT241515-15") != backtest.event_cluster("KXBTC15M-26OCT241530-30")
    assert backtest.event_cluster("ODD") == "ODD"


def test_clustered_edge_counts_a_lucky_day_once():
    # 40 longshot buys at 5c: 8 strikes on each of 5 days. One day moved and all 8 strikes won;
    # the rest lost. Per trade that is +3.0/$ at t ~ 2.4; per event it is ONE win in 5 (t 0.75).
    lucky = [_trade("KXBTCD-26OCT%02d17-T%d" % (20 + d, 80000 + 100 * k), 0.05, 95.0 if d == 0 else -5.0, 8 * d + k)
             for d in range(5) for k in range(8)]
    e = backtest.clustered_edge(lucky)
    assert e["events"] == 5 and e["top3_event_share"] == 1.0
    assert e["mean_ret"] > 0 and e["t_events"] < 1.0
    # A steady small edge over many independent events keeps a high t.
    steady = [_trade("KXBTC15M-26OCT%04d-15" % i, 0.50, 0.30 if i % 5 else -0.20, i) for i in range(200)]
    s = backtest.clustered_edge(steady)
    assert s["events"] == 200 and s["t_events"] > 5


def test_score_ranks_research_folds_by_clustered_t_not_pnl():
    lucky = {"trades": 40, "pnl": 400.0, "t_events": 0.9, "events": 5}
    steady = {"trades": 200, "pnl": 30.0, "t_events": 4.0, "events": 200}
    one_event = {"trades": 20, "pnl": 900.0, "t_events": None, "events": 1}
    assert backtest.score(steady) > backtest.score(lucky) > backtest.score(one_event) > backtest.score({"trades": 2, "pnl": 1})


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


# -- next-bar fill model (the default; mirrors the live kernel's submit-time re-pricing) ----------


def _replace_quote(ds, offset, bid, ask, **feat):
    """Overwrite every contract's quote at `offset` seconds after its open."""
    for ts, snaps in ds.frames:
        for i, sn in enumerate(snaps):
            if (ts - T0) % 900 == offset:
                snaps[i] = sn.__class__(sn.contract, ts, bid, ask,
                                        dict(sn.features, yes_bid=bid, yes_ask=ask, spread=ask - bid, **feat))


_ONE_AT_A_TIME = {"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05},
                  "sizing": {"stake": 10.0, "max_positions": 1}}


def test_next_bar_entry_fills_at_the_following_quote():
    assert backtest.FILL_MODEL == "next_bar"
    ds = _dataset(ask=0.40, bid=0.38)
    _replace_quote(ds, 120, 0.43, 0.45)   # the bar after the first signal is dearer
    t = backtest.simulate(specmod.validate(_ONE_AT_A_TIME), ds, ds.start_ts, ds.end_ts + 1)[0]
    assert t.entry_ts == T0 + 120 and t.entry_price == 0.45   # signal at +60, filled at +120's ask


def test_next_bar_entry_is_abandoned_past_the_reservation_price():
    """If the ask runs past the price at which the edge still clears min_edge net of fees, live
    abandons the entry, so the backtest must miss it too rather than fill at a price live refuses."""
    ds = _dataset(ask=0.40, bid=0.38)
    _replace_quote(ds, 120, 0.94, 0.96)   # fair ~1: a 96c ask cannot clear a 10c edge after fees
    trades = backtest.simulate(specmod.validate(_ONE_AT_A_TIME), ds, ds.start_ts, ds.end_ts + 1)
    assert trades and all(t.entry_ts % 900 != 120 for t in trades)
    # +120's 96c quote is itself no signal, so the next signal is at +180, filled at +240's 40c ask
    assert trades[0].entry_ts == T0 + 240 and trades[0].entry_price == 0.40


def test_next_bar_fill_is_capped_at_displayed_size():
    ds = _dataset_with_micro({"yes_ask_size": 7.0})
    t = backtest.simulate(specmod.validate(_ONE_AT_A_TIME), ds, ds.start_ts, ds.end_ts + 1)[0]
    assert t.qty == 7        # stake $10 at 40c wants 25 contracts; only 7 were offered


def test_next_bar_exit_sells_at_the_following_bid():
    ds = _dataset(ask=0.40, bid=0.38)
    _replace_quote(ds, 180, 0.70, 0.72)   # spike one bar after the +120 fill
    _replace_quote(ds, 240, 0.60, 0.62)   # the exit executes a bar later, at the lower bid
    spec = specmod.validate(dict(_ONE_AT_A_TIME, exit={"take_profit": 0.2}))
    t = backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)[0]
    assert t.reason == "take_profit" and t.exit_ts == T0 + 240 and t.exit_price == 0.60


def test_the_position_stop_paper_and_live_enforce_is_backtested():
    """Filled at +120 for 40c; at +240 the bid is 20c, a loss of over 40% of cost: sold there, as the
    engine's position stop would, instead of riding to a settlement the backtest alone would see."""
    ds = _dataset(ask=0.40, bid=0.38)
    _replace_quote(ds, 240, 0.20, 0.22)
    spec = specmod.validate(_ONE_AT_A_TIME)
    t = backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)[0]
    assert (t.reason, t.exit_ts, t.exit_price) == ("stop", T0 + 240, 0.20)
    held = backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1, backtest.WhatIf(position_stop_pct=0))[0]
    assert held.reason == "settled" and held.exit_price == 1.0
    # a dip short of the stop (30c bid = 25% down) is ridden out
    ds = _dataset(ask=0.40, bid=0.38)
    _replace_quote(ds, 240, 0.30, 0.32)
    assert backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)[0].reason == "settled"


def test_next_bar_is_never_more_optimistic_than_signal_bar(monkeypatch):
    ds = _dataset(ask=0.40, bid=0.38)
    _replace_quote(ds, 120, 0.50, 0.52)
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}})
    nxt = sum(t.pnl for t in backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1))
    monkeypatch.setattr(backtest, "FILL_MODEL", "signal_bar")
    sig = sum(t.pnl for t in backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1))
    assert nxt <= sig


# -- pooled (multi-market) specs ---------------------------------------------------------------


def test_pool_validates_and_lists_involved_markets():
    s = specmod.validate({"market": "btc15m", "pool": ["eth15m", "sol15m", "btc15m"]})
    assert s["pool"] == ["eth15m", "sol15m"]                      # primary removed, sorted, deduped
    assert specmod.involved_markets(s) == ["btc15m", "eth15m", "sol15m"]
    assert specmod.stream_key(s) == "btc15m+eth15m+sol15m"
    assert specmod.is_pooled(s) and specmod.is_multi_market(s) and not specmod.is_cross_contract(s)
    plain = specmod.validate({"market": "btc15m"})
    assert "pool" not in plain and not specmod.is_multi_market(plain)   # absent pool: spec unchanged


def test_pool_rejects_bad_markets_cadence_and_cross():
    import pytest
    for bad in ({"pool": ["nope"]}, {"pool": []}, {"pool": "eth15m"}, {"pool": ["btc_daily"]},
                {"pool": ["btc15m"]}, {"pool": ["eth15m", "sol15m", "xrp15m", "doge15m"]},
                {"pool": ["eth15m"], "cross": {"pairing": "cross_strike", "legs": []}}):
        with pytest.raises(specmod.SpecError):
            specmod.validate(dict({"market": "btc15m"}, **bad))
    # event series (many contracts per frame, ~GB datasets) cannot be pooled, either way round
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "btc15m", "pool": ["nba_game"]})
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "nba_game", "pool": ["nfl_game"]})


def _renamed(ds, prefix):
    """The same synthetic book under a different ticker namespace (a second market)."""
    from dataclasses import replace
    frames = [(ts, [replace(sn, contract=replace(sn.contract, ticker=prefix + sn.contract.ticker))
                    for sn in snaps]) for ts, snaps in ds.frames]
    return backtest.Dataset(ds.market, frames, {prefix + k: v for k, v in ds.results.items()},
                            ds.start_ts, ds.end_ts, ds.contracts)


def test_pooled_rule_trades_every_market_on_the_merged_dataset():
    a = _dataset(n_contracts=10)
    merged = backtest.merge_datasets([a, _renamed(a, "E")], key="btc15m+eth15m")
    spec = specmod.validate({"market": "btc15m", "pool": ["eth15m"], "side": "yes",
                             "entry": {"min_edge": 0.1}, "sizing": {"stake": 10.0, "max_positions": 4}})
    trades = backtest.simulate(spec, merged, merged.start_ts, merged.end_ts + 1)
    single = backtest.simulate(spec, a, a.start_ts, a.end_ts + 1)
    assert {t.ticker[0] for t in trades} == {"M", "E"}           # evidence from both markets
    assert len(trades) == 2 * len(single)                          # ~N x the sample


def test_hourly_weather_series_can_pool_with_each_other_but_not_with_1min_sports(monkeypatch):
    """Daily weather highs use hourly candles (a few thousand points per load), so several cities
    can pool their evidence; a 1-minute sports series still can't join (~1.4GB per load)."""
    import dataclasses
    import pytest
    from app import markets
    chi = dataclasses.replace(markets.MARKETS["high_ny"], key="kxhighchi", series="KXHIGHCHI")
    monkeypatch.setitem(markets.MARKETS, "kxhighchi", chi)
    monkeypatch.setitem(specmod.MARKETS, "kxhighchi", chi)
    s = specmod.validate({"market": "high_ny", "side": "yes", "pool": ["kxhighchi"],
                          "sizing": {"stake": 5, "max_positions": 1}})
    assert s["pool"] == ["kxhighchi"]
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "high_ny", "pool": ["nba_game"]})
    # hourly series are light (+120MB per 365-day city), so a weather pool may hold 6 extra cities
    cities = ["kxcity%d" % i for i in range(7)]
    for key in cities:
        city = dataclasses.replace(chi, key=key, series=key.upper())
        monkeypatch.setitem(markets.MARKETS, key, city)
        monkeypatch.setitem(specmod.MARKETS, key, city)
    assert len(specmod.validate({"market": "high_ny", "pool": cities[:6]})["pool"]) == 6
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "high_ny", "pool": cities})
    assert specmod.max_pool(markets.MARKETS["btc15m"]) == specmod.MAX_POOL_MARKETS == 3


def test_pool_cap_counts_extra_markets_after_dropping_the_primary_and_duplicates():
    """Run 3271 (doge15m) lost a pooled idea to "pool must be a list of 1..3": listing the spec's
    own market (or a duplicate) in the pool counted against the cap of 3 EXTRA markets."""
    import pytest
    s = specmod.validate({"market": "xrp15m", "pool": ["btc15m", "eth15m", "sol15m", "xrp15m", "eth15m"]})
    assert s["pool"] == ["btc15m", "eth15m", "sol15m"]
    with pytest.raises(specmod.SpecError, match="at most 3 extra markets besides xrp15m; got 4"):
        specmod.validate({"market": "xrp15m", "pool": ["btc15m", "eth15m", "sol15m", "doge15m"]})


def test_frame_series_reach_each_frame_only_once_known():
    """Weather-station readings are joined per frame point-in-time: a frame before a reading is
    known lacks the feature, and every later frame carries the newest known value."""
    from datetime import datetime, timezone
    from app.markets import MARKETS
    close = datetime.fromtimestamp(10_000, tz=timezone.utc)
    mk = [{"ticker": "W", "strike": 60.0, "close_time": close, "result": "yes"}]
    candles = [("W", ts, 0.40, 0.45) for ts in (1000, 2000, 3000)]
    ds = backtest.build_dataset(MARKETS["high_ny"], mk, candles, [],
                                frame_series={"obs_high_f": [(1500, 58.0), (2500, 61.0)]})
    got = [sn[0].features.get("obs_high_f") for _, sn in ds.frames]
    assert got == [None, 58.0, 61.0]


def test_feature_block_states_the_window_carries_strikes_and_events():
    """Runs 2761/2772/2775 dropped sports ladder theses as missing_context ("no strike values, no
    event context") because the feature list said "anything missing is not" and strike/event are
    window fields, not features. The block now measures and names them."""
    from app import agent
    block = agent._feature_block(_dataset_with_micro({"ob_imbalance": 0.9}))
    assert "Per-contract fields in a code window" in block
    assert "strike (nonzero on 100% of contracts, p10/p50/p90 98/98/98)" in block
    assert "event (40 events" in block
