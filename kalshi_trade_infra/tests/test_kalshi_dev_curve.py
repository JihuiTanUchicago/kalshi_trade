"""Read-only Kalshi-demo replay that draws the second (realized) equity line.

No network and no live calls: the dev candlestick GET is monkeypatched. Covers
the happy path (a realized curve from mocked demo candlesticks) and graceful
degradation when demo creds or data are absent.
"""
from datetime import datetime, timezone

from app.trading import backtest
from app.adapters.kalshi import kalshi_dev
from app.trading import spec as specmod
from app.trading.markets import MARKETS

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def _dataset(n_contracts=40, minutes=15, result="yes", ask=0.40, bid=0.38):
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n_contracts * minutes + 200)]
    markets, candles = [], []
    for k in range(n_contracts):
        open_ts = T0 + k * minutes * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        ticker = "M%d" % k
        markets.append({"ticker": ticker, "strike": 98.0, "close_time": close, "result": result})
        for m in range(1, minutes + 1):
            candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                            "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


def _demo_feed(ds, bid, ask):
    """A fake Kalshi-demo candlestick GET built from the dataset's OOS frames."""
    wanted = {}  # ticker -> list of ts in the OOS window
    for ts, snaps in ds.frames:
        if ts < ds.cutoff_ts:
            continue
        for sn in snaps:
            wanted.setdefault(sn.contract.ticker, []).append(ts)

    def fake_get(path, params, timeout=15):
        ticker = path.split("/markets/")[1].split("/")[0]
        cs = [{"end_period_ts": ts,
               "yes_bid": {"close_dollars": bid}, "yes_ask": {"close_dollars": ask}}
              for ts in wanted.get(ticker, [])]
        return {"candlesticks": cs}

    return fake_get


def test_dev_replay_produces_a_realized_curve(monkeypatch):
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}})
    # Demo book priced the same as our history -> the realized curve trades and wins.
    monkeypatch.setattr(kalshi_dev, "_dev_get", _demo_feed(ds, 0.38, 0.40))
    out = kalshi_dev._compute(s, ds)
    assert out is not None
    assert out["env"] == "kalshi-dev"
    assert len(out["dev_curve"]) >= 2
    assert out["dev_metrics"]["trades"] > 0
    assert out["dev_metrics"]["pnl"] > 0  # yes-settled contracts bought cheap


def test_dev_replay_reflects_worse_demo_prices(monkeypatch):
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}})
    # Pay more on the demo book -> realized P&L is lower than our own history's.
    monkeypatch.setattr(kalshi_dev, "_dev_get", _demo_feed(ds, 0.58, 0.60))
    out = kalshi_dev._compute(s, ds)
    assert out is not None
    cutoff = ds.cutoff_ts
    sim_oos = backtest.metrics(
        backtest.simulate(s, ds, cutoff, ds.end_ts + 1),
        s["sizing"]["stake"] * s["sizing"]["max_positions"], 1.0,
    )["pnl"]
    assert out["dev_metrics"]["pnl"] < sim_oos


def _dataset_priced(asks, minutes=40):
    """One contract per entry in `asks`, all sharing the whole window so every
    contract is first-seen in insertion order; `asks[k]` sets contract k's YES ask
    (bid 2c under). A multi-day market's OOS window works the same way: many
    contracts, only some of which the strategy actually trades."""
    open_ts = T0
    close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
    btc = [(open_ts - 7200 + 60 * i, 100.0) for i in range(minutes + 300)]
    markets, candles = [], []
    for k, ask in enumerate(asks):
        ticker = "M%d" % k
        markets.append({"ticker": ticker, "strike": 98.0, "close_time": close, "result": "yes"})
        for m in range(1, minutes + 1):
            candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                            "yes_bid_close": ask - 0.02, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


def test_dev_replay_covers_the_contracts_the_strategy_trades(monkeypatch):
    # Root cause: the first-seen strike ladder is mostly disjoint from the
    # contracts a strategy trades, so capping to the FIRST MAX_CONTRACTS first-seen
    # tickers fetched only untraded contracts -> 0 aligned trades -> null slippage.
    # Here the early first-seen contracts are priced out of the YES band and only
    # the later ones trade; the dev replay must still cover those traded contracts.
    monkeypatch.setattr(kalshi_dev, "MAX_CONTRACTS", 3)
    ds = _dataset_priced([0.97, 0.97, 0.97, 0.40, 0.40, 0.40])
    s = specmod.validate({"side": "yes"})
    monkeypatch.setattr(kalshi_dev, "_dev_get", _demo_feed(ds, 0.43, 0.45))
    out = kalshi_dev._compute(s, ds)
    assert out is not None
    # Old behavior fetched M0..M2 (untraded) -> slippage None; the fix fetches the
    # traded M3..M5 so >= MIN_ALIGNED_TRADES align and the realized curve fills.
    assert out["dev_metrics"]["trades"] >= kalshi_dev.MIN_ALIGNED_TRADES
    assert len(out["dev_curve"]) >= kalshi_dev.MIN_ALIGNED_TRADES
    slip = out["slippage"]
    assert slip is not None and slip["n_trades"] >= kalshi_dev.MIN_ALIGNED_TRADES
    assert slip["entry_cents"] == 5.0  # demo ask 0.45 vs our 0.40 -> +5c worse


def test_quote_end_ts_exact_then_prior_within_interval():
    times = [100, 160, 280]  # a thin book that skipped the 220 slot
    assert kalshi_dev._quote_end_ts(times, 160, 60) == 160   # exact hit
    assert kalshi_dev._quote_end_ts(times, 220, 60) == 160   # gap -> prior within one interval
    assert kalshi_dev._quote_end_ts(times, 281, 60) == 280   # just after a candle
    assert kalshi_dev._quote_end_ts(times, 400, 60) is None  # too stale (> interval)
    assert kalshi_dev._quote_end_ts(times, 50, 60) is None   # before the first candle
    assert kalshi_dev._quote_end_ts([], 100, 60) is None     # no candles


def test_no_curve_when_demo_unconfigured(monkeypatch):
    monkeypatch.setattr(kalshi_dev, "KALSHI_DEV_API_BASE", "")
    assert kalshi_dev.dev_curve_for_strategy(1, {}, "btc15m") is None
    assert "KALSHI_DEV_API_BASE" in kalshi_dev.unavailable_reason()


def test_no_curve_when_demo_host_unreachable(monkeypatch):
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})

    def boom(path, params, timeout=15):
        raise RuntimeError("demo host down")

    monkeypatch.setattr(kalshi_dev, "_dev_get", boom)
    assert kalshi_dev._compute(s, ds) is None
