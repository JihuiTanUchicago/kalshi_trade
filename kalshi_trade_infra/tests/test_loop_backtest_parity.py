"""Step 8b parity: a DSL spec run through trading_core's TradingLoop books the same trades as
app.trading.backtest.simulate (signal-bar fills) on the same dataset. Any divergence is a bug in one path."""
import random
from datetime import datetime, timezone

import pytest

from app.trading import backtest
from app.trading import spec as specmod
from app.adapters.kalshi.spec_strategy import KalshiNextBarFill, SpecStrategy, simulate_on_loop
from app.trading.markets import MARKETS
from trading_core.domain import InstrumentId, OrderIntent, Quote, Side

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def _random_dataset(seed, n_events=30, minutes=15, strikes=(98.0, 100.0, 102.0), gaps=0.0, sizes=False, voids=0.0):
    """Overlapping strikes per 15-minute event, a random-walk spot and noisy books, so entries,
    take-profits, stops, edge-gone exits and settlements all happen. ``gaps`` drops that fraction of
    quotes (orders rest, go stale, contracts vanish for a bar); ``sizes`` adds top-of-book sizes;
    ``voids`` settles that fraction of markets as Kalshi settles a cancelled one (hist_markets result
    'void' at a fair price in settle_value)."""
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
            row = {"ticker": ticker, "strike": strike, "close_time": close,
                   "result": "yes" if settle_spot > strike else "no"}
            if voids and rng.random() < voids:
                row.update(result="void", settle_value=round(rng.uniform(0.05, 0.95), 2))
            markets.append(row)
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


@pytest.fixture(autouse=True)
def _legacy_reference(monkeypatch):
    """backtest.simulate is the reference here, so it must not itself route to the loop."""
    monkeypatch.setattr(backtest, "ENGINE", "legacy")


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


WHAT_IFS = [backtest.WhatIf(slippage_cents=2.0), backtest.WhatIf(fee_multiplier=1.5),
            backtest.WhatIf(slippage_cents=3.0, fee_multiplier=2.0, stake=7.0, position_stop_pct=25.0)]


@pytest.mark.parametrize("fill", ["next_bar", "signal_bar"])
@pytest.mark.parametrize("what_if", WHAT_IFS)
@pytest.mark.parametrize("raw", SPECS)
def test_cost_stress_what_ifs_book_the_same_trades_on_the_loop(monkeypatch, fill, what_if, raw):
    """The gate's cost stress (slippage, fee multiplier, stake, stop) moves onto the loop unchanged."""
    monkeypatch.setattr(backtest, "FILL_MODEL", fill)
    ds = _random_dataset(17, gaps=0.1, sizes=True)
    spec = specmod.validate(raw)
    legacy = sorted(backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1, what_if), key=_key)
    loop = sorted(simulate_on_loop(spec, ds, ds.start_ts, ds.end_ts + 1, what_if=what_if), key=_key)
    assert legacy and [_row(t) for t in loop] == [_row(t) for t in legacy]


@pytest.mark.parametrize("fill", ["next_bar", "signal_bar"])
def test_engine_flag_routes_dsl_specs_through_the_loop(monkeypatch, fill):
    monkeypatch.setattr(backtest, "FILL_MODEL", fill)
    ds = _random_dataset(18)
    spec = specmod.validate(SPECS[3])
    legacy = backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1, WHAT_IFS[2])
    monkeypatch.setattr(backtest, "ENGINE", "loop")
    calls = []
    import app.adapters.kalshi.spec_strategy as ss
    real = ss.simulate_on_loop
    monkeypatch.setattr(ss, "simulate_on_loop", lambda *a, **k: calls.append(1) or real(*a, **k))
    routed = backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1, WHAT_IFS[2])
    assert calls == [1] and routed and [_row(t) for t in sorted(routed, key=_key)] == \
        [_row(t) for t in sorted(legacy, key=_key)]


def test_next_bar_entry_never_lifts_an_ask_above_the_backtest_cap():
    """A 99c buy can't profit after the fee; backtest.MAX_ENTRY_ASK (#187) skips it and so must the loop."""
    yes = InstrumentId("kalshi", "M", "yes")
    intent = OrderIntent(yes, Side.BUY, 1, fair_value=1.0, meta={"stake": 10.0})
    rejected = []

    class _Venue:
        def submit(self, intent, price, client_order_id):
            raise AssertionError("must not submit at %s" % price)

    for ask in (0.99, 1.0):
        rep = KalshiNextBarFill(0.0, max_ask=backtest.MAX_ENTRY_ASK).execute(
            intent, None, Quote(yes, 0.0, 0.97, ask), _Venue(), "c", 0.0)
        rejected.append(rep.status == "rejected" and "0.98" in rep.message)
    assert rejected == [True, True]


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
    assert out["cases"] == 3 and out["diffs"] == [] and out["legacy_trades"] > 0
    import app.adapters.kalshi.spec_strategy as ss
    monkeypatch.setattr(ss, "simulate_on_loop", lambda *a, **k: [])
    assert loop_parity.main(["--markets", "btc15m"]) == 1


def test_simulate_clocks_its_own_thread_once_per_call(monkeypatch):
    """backtest.sim_seconds is what a research run logs as its backtest share: every simulate call
    adds its wall time once, even when it routes through the loop (which calls nothing back)."""
    monkeypatch.setattr(backtest, "FILL_MODEL", "next_bar")
    ds = _random_dataset(5)
    spec = specmod.validate(SPECS[0])
    before = backtest.sim_seconds()
    backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)
    one = backtest.sim_seconds() - before
    monkeypatch.setattr(backtest, "ENGINE", "loop")
    backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)
    assert 0 < one < backtest.sim_seconds() - before


@pytest.mark.parametrize("fill", ["signal_bar", "next_bar"])
@pytest.mark.parametrize("raw", SPECS)
def test_a_cancelled_market_pays_its_settlement_price_on_both_paths(monkeypatch, fill, raw):
    """A market Kalshi cancelled settles at its fair price, as the live engine is paid: YES gets the
    price and NO one minus it, on the legacy backtest and on the loop alike. Before, it paid 0 to both."""
    monkeypatch.setattr(backtest, "FILL_MODEL", fill)
    ds = _random_dataset(4, voids=0.3)
    values = {t: r for t, r in ds.results.items() if isinstance(r, float)}
    assert values  # the dataset carries the price, not the raw 'void'
    spec = specmod.validate(raw)
    legacy = sorted(backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1), key=_key)
    loop = sorted(simulate_on_loop(spec, ds, ds.start_ts, ds.end_ts + 1), key=_key)
    assert [_row(t) for t in loop] == [_row(t) for t in legacy]
    for t in legacy:
        if t.reason == "settled" and t.ticker in values:
            want = values[t.ticker] if t.side == "yes" else 1.0 - values[t.ticker]
            assert t.exit_price == pytest.approx(want)
