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


def _random_dataset(seed, n_events=30, minutes=15, strikes=(98.0, 100.0, 102.0), gaps=0.0, sizes=False):
    """Overlapping strikes per 15-minute event, a random-walk spot and noisy books, so entries,
    take-profits, stops, edge-gone exits and settlements all happen. ``gaps`` drops that fraction of
    quotes (orders rest, go stale, contracts vanish for a bar); ``sizes`` adds top-of-book sizes."""
    rng = random.Random(seed)
    spot, btc = 100.0, []
    for i in range(n_events * minutes + 200):
        spot *= 1.0 + rng.gauss(0, 0.002)
        btc.append((T0 - 7200 + 60 * i, spot))
    px = dict(btc)
    markets, candles, micro = [], [], {}
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
                if rng.random() < gaps:
                    continue
                candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                                "yes_bid_close": bid, "yes_ask_close": ask})
                if sizes:
                    micro[(ticker, open_ts + m * 60)] = {"yes_ask_size": float(rng.randint(0, 40)),
                                                         "yes_bid_size": float(rng.randint(0, 40))}
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc, micro or None)


SPECS = [
    {"side": "yes", "entry": {"min_edge": 0.05, "max_spread": 0.05}},
    {"side": "no", "entry": {"min_edge": 0.05}, "exit": {"take_profit": 0.1, "stop_loss": 0.1}},
    {"side": "either", "entry": {"min_edge": 0.03}, "exit": {"take_profit": 0.15},
     "sizing": {"stake": 25.0, "max_positions": 3}},
    {"side": "either", "entry": {"min_edge": 0.02}, "exit": {"min_edge_to_hold": 0.0, "stop_loss": 0.2},
     "sizing": {"stake": 10.0, "max_positions": 5}},
    {"side": "yes", "entry": {"min_edge": 0.1}, "exit": {"min_edge_to_hold": 0.05},
     "sizing": {"stake": 5.0, "max_positions": 2}},
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


@pytest.mark.parametrize("seed,gaps,sizes", [(11, 0.0, False), (12, 0.15, False), (13, 0.0, True), (14, 0.2, True)])
@pytest.mark.parametrize("raw", SPECS)
def test_next_bar_fills_book_the_same_trades_on_the_loop(monkeypatch, seed, gaps, sizes, raw):
    """The default fill model: decide on bar t, fill on bar t+1 within the reservation price and the
    displayed size, the position stop ahead of every exit, unfilled exits resting until stale."""
    monkeypatch.setattr(backtest, "FILL_MODEL", "next_bar")
    ds = _random_dataset(seed, gaps=gaps, sizes=sizes)
    spec = specmod.validate(raw)
    legacy = sorted(backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1), key=_key)
    assert [_row(t) for t in sorted(simulate_on_loop(spec, ds, ds.start_ts, ds.end_ts + 1), key=_key)] == \
        [_row(t) for t in legacy]


def test_next_bar_position_stop_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(backtest, "FILL_MODEL", "next_bar")
    ds = _random_dataset(15)
    spec = specmod.validate(SPECS[0])
    what_if = backtest.WhatIf(position_stop_pct=0)
    legacy = sorted(backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1, what_if), key=_key)
    loop = sorted(simulate_on_loop(spec, ds, ds.start_ts, ds.end_ts + 1, position_stop_pct=0), key=_key)
    assert [_row(t) for t in loop] == [_row(t) for t in legacy] and "stop" not in {t.reason for t in loop}


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
    monkeypatch.setattr(backtest, "FILL_MODEL", "next_bar")
    ds = _random_dataset(5, gaps=0.15, sizes=True)
    nb = [t for raw in SPECS for t in simulate_on_loop(specmod.validate(raw), ds, ds.start_ts, ds.end_ts + 1)]
    assert {"settled", "take_profit", "stop_loss", "stop", "edge_gone"} <= {t.reason for t in nb}


def test_spec_strategy_refuses_what_it_does_not_model():
    with pytest.raises(ValueError):
        SpecStrategy({"code": "def signals(w): return {}", "sizing": {"stake": 1, "max_positions": 1}}, {})


def test_real_data_parity_script_reports_clean_and_dirty_runs(monkeypatch, capsys):
    import json
    from scripts import loop_parity
    ds = _random_dataset(21, n_events=10)
    monkeypatch.setattr(backtest, "dataset", lambda market, days: ds)
    monkeypatch.setattr(loop_parity, "_specs", lambda market, limit: [(1, specmod.validate(SPECS[2]))])
    monkeypatch.setattr(backtest, "FILL_MODEL", backtest.FILL_MODEL)   # the script flips it; restore after
    assert loop_parity.main(["--markets", "btc15m"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cases"] == 2 and out["diffs"] == [] and out["legacy_trades"] > 0
    import app.adapters.kalshi.spec_strategy as ss
    monkeypatch.setattr(ss, "simulate_on_loop", lambda *a, **k: [])
    assert loop_parity.main(["--markets", "btc15m"]) == 1
