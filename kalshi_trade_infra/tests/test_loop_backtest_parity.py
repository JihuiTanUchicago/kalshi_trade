"""Step 8b parity: a DSL spec run through trading_core's TradingLoop books the same trades as
app.backtest.simulate (signal-bar fills) on the same dataset. Any divergence is a bug in one path."""
import random
from datetime import datetime, timezone

import pytest

from app import backtest
from app import spec as specmod
from app.adapters.kalshi.spec_strategy import SpecStrategy, simulate_on_loop
from app.markets import MARKETS

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def _random_dataset(seed, n_events=30, minutes=15, strikes=(98.0, 100.0, 102.0)):
    """Overlapping strikes per 15-minute event, a random-walk spot and noisy books, so entries,
    take-profits, stops, edge-gone exits and settlements all happen."""
    rng = random.Random(seed)
    spot, btc = 100.0, []
    for i in range(n_events * minutes + 200):
        spot *= 1.0 + rng.gauss(0, 0.002)
        btc.append((T0 - 7200 + 60 * i, spot))
    px = dict(btc)
    markets, candles = [], []
    for k in range(n_events):
        open_ts = T0 + k * minutes * 60
        close_ts = open_ts + minutes * 60
        close = datetime.fromtimestamp(close_ts, tz=timezone.utc)
        settle_spot = px.get(close_ts - close_ts % 60, spot)
        for strike in strikes:
            ticker = "M%d_%d" % (k, int(strike))
            markets.append({"ticker": ticker, "strike": strike, "close_time": close,
                            "result": "yes" if settle_spot > strike else "no"})
            mid = rng.uniform(0.15, 0.85)
            for m in range(1, minutes + 1):
                mid = min(0.95, max(0.05, mid + rng.gauss(0, 0.06)))
                spread = rng.choice((0.01, 0.02, 0.03, 0.05))
                bid = round(max(0.0, mid - spread / 2), 2)
                ask = round(min(0.99, bid + spread), 2)
                candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                                "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


SPECS = [
    {"side": "yes", "entry": {"min_edge": 0.05, "max_spread": 0.05}},
    {"side": "no", "entry": {"min_edge": 0.05}, "exit": {"take_profit": 0.1, "stop_loss": 0.1}},
    {"side": "either", "entry": {"min_edge": 0.03}, "exit": {"take_profit": 0.15},
     "sizing": {"stake": 25.0, "max_positions": 3}},
    {"side": "either", "entry": {"min_edge": 0.02}, "exit": {"min_edge_to_hold": 0.0, "stop_loss": 0.2},
     "sizing": {"stake": 10.0, "max_positions": 5}},
]


def _key(t):
    return (t.ticker, t.side, t.entry_ts)


def _row(t):
    return (t.ticker, t.side, t.qty, t.entry_ts, t.entry_price, t.exit_ts, t.exit_price, round(t.fees, 10), t.reason,
            t.edge)


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("raw", SPECS)
def test_loop_books_the_same_trades_as_the_legacy_backtest(monkeypatch, seed, raw):
    monkeypatch.setattr(backtest, "FILL_MODEL", "signal_bar")
    ds = _random_dataset(seed)
    spec = specmod.validate(raw)
    legacy = sorted(backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1), key=_key)
    loop = sorted(simulate_on_loop(spec, ds, ds.start_ts, ds.end_ts + 1), key=_key)
    assert [_row(t) for t in loop] == [_row(t) for t in legacy]


def test_parity_holds_on_a_sub_window(monkeypatch):
    monkeypatch.setattr(backtest, "FILL_MODEL", "signal_bar")
    ds = _random_dataset(7)
    spec = specmod.validate(SPECS[2])
    mid = ds.start_ts + (ds.end_ts - ds.start_ts) // 2
    for lo, hi in ((ds.start_ts, mid), (mid, ds.end_ts + 1)):
        legacy = sorted(backtest.simulate(spec, ds, lo, hi), key=_key)
        assert [_row(t) for t in sorted(simulate_on_loop(spec, ds, lo, hi), key=_key)] == [_row(t) for t in legacy]


def test_reasons_cover_every_exit_path(monkeypatch):
    """Guards the fixture: parity means little if it never exercises an exit kind."""
    monkeypatch.setattr(backtest, "FILL_MODEL", "signal_bar")
    trades = []
    for seed in (1, 2, 3):
        ds = _random_dataset(seed)
        for raw in SPECS:
            trades += simulate_on_loop(specmod.validate(raw), ds, ds.start_ts, ds.end_ts + 1)
    assert len(trades) >= 50 and {t.side for t in trades} == {"yes", "no"}
    assert {"settled", "take_profit", "stop_loss"} <= {t.reason for t in trades}


def test_spec_strategy_refuses_what_it_does_not_model():
    with pytest.raises(ValueError):
        SpecStrategy({"code": "def signals(w): return {}", "sizing": {"stake": 1, "max_positions": 1}}, {})
