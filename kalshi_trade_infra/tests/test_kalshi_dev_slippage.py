"""Per-trade slippage measurement for the dev (demo-book) replay.

No network: the demo host is monkeypatched. Covers the slippage math on a known
realized-vs-simulated example, the market-level accessor that feeds the cost
model, and graceful degradation when the demo host is down.
"""
from datetime import datetime, timezone

from app import kalshi_dev
from app import spec as specmod
from app.backtest import Dataset, Trade
from app.markets import MARKETS, snapshot


def _trade(ticker, entry_ts, entry, exit_ts, exit_price, reason, side="yes"):
    return Trade(ticker, side, 1, entry_ts, entry, exit_ts, exit_price, 0.0, reason, 0.0)


def test_slippage_math_on_known_example():
    # Three contracts both books traded at the same decision point. The demo
    # book paid +2c more on entry and received 2c less on exit every time.
    sim = [_trade("A", 100, 0.50, 200, 0.60, "stop"),
           _trade("B", 100, 0.40, 200, 0.50, "stop"),
           _trade("C", 100, 0.30, 200, 0.40, "stop")]
    dev = [_trade("A", 100, 0.52, 200, 0.58, "stop"),
           _trade("B", 100, 0.42, 200, 0.48, "stop"),
           _trade("C", 100, 0.32, 200, 0.38, "stop"),
           # Unaligned (different entry_ts) and side-mismatched trades are ignored.
           _trade("A", 999, 0.90, 999, 0.90, "stop"),
           _trade("B", 100, 0.42, 200, 0.48, "stop", side="no")]
    block = kalshi_dev._slippage(sim, dev, capped=False)
    assert block == {"entry_cents": 2.0, "exit_cents": 2.0, "n_trades": 3, "capped": False}
    # The symmetric per-fill number the cost model consumes is the leg average.
    assert kalshi_dev._per_fill_cents(block) == 2.0


def test_settled_exits_excluded_and_too_few_is_null():
    # Settlement payout (0/1) is identical across books, so exits don't compare.
    sim = [_trade("A", 100, 0.50, 300, 1.0, "settled"),
           _trade("B", 100, 0.40, 300, 1.0, "settled"),
           _trade("C", 100, 0.30, 300, 0.0, "settled")]
    dev = [_trade("A", 100, 0.53, 300, 1.0, "settled"),
           _trade("B", 100, 0.43, 300, 1.0, "settled"),
           _trade("C", 100, 0.33, 300, 0.0, "settled")]
    block = kalshi_dev._slippage(sim, dev, capped=True)
    assert block["exit_cents"] is None and block["n_trades"] == 3
    assert block["entry_cents"] == 3.0 and block["capped"] is True
    # Fewer than MIN_ALIGNED_TRADES aligned -> no trustworthy figure.
    assert kalshi_dev._slippage(sim[:2], dev[:2], capped=False) is None
    assert kalshi_dev._per_fill_cents(None) is None


def _oos_dataset():
    market = MARKETS["btc15m"]
    feats = {"spot": 100000.0, "ret_1m": 0.0, "ret_5m": 0.0, "ret_15m": 0.0,
             "ret_60m": 0.0, "vol_15m": 0.001, "vol_60m": 0.001}
    close = datetime.fromtimestamp(5600, tz=timezone.utc)
    from app.markets import Contract
    sn = snapshot(feats, Contract("A", 100000.0, close), 2000, 0.40, 0.42)
    assert sn is not None
    # start=1000, end=2000 -> cutoff=1700, so the ts=2000 frame is out-of-sample.
    return Dataset(market, [(1000, [sn]), (2000, [sn])], {"A": "yes"}, 1000, 2000, 1)


def test_down_demo_host_yields_null_without_raising(monkeypatch):
    monkeypatch.setattr(kalshi_dev, "_dev_candles", lambda *a, **k: None)  # host down
    ds = _oos_dataset()
    assert kalshi_dev._compute(specmod.validate({"side": "yes"}), ds) is None


def test_measured_slippage_accessor_feeds_cost_model(monkeypatch):
    # dev_curve_for_strategy caches a market-level per-fill number as a side effect
    # so the what-if cost model can read it without a strategy id.
    monkeypatch.setattr(kalshi_dev.backtest, "dataset", lambda *a, **k: object())
    monkeypatch.setattr(kalshi_dev, "_compute", lambda spec, ds: {
        "dev_curve": [[1, 0.0], [2, 1.0]],
        "slippage": {"entry_cents": 2.0, "exit_cents": 1.0, "n_trades": 7, "capped": False},
    })
    assert kalshi_dev.measured_slippage_cents("zzz_testmkt") is None
    kalshi_dev.dev_curve_for_strategy(987654, {}, "zzz_testmkt")
    assert kalshi_dev.measured_slippage_cents("zzz_testmkt") == 1.5
