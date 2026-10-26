"""The execution cost model replays top-of-book ticks; these pin each statistic on tiny books."""
from datetime import datetime, timezone

import pytest

from app.trading import exec_cost_model as ecm
from app.trading.exec_cost_model import Tick


def T(t, bid, ask, bs=100.0, asz=100.0):
    return Tick(float(t), bid, ask, bs, asz)


def test_clean_drops_crossed_one_sided_and_sorts():
    ticks = ecm.clean([T(3, 0.40, 0.42), T(1, 0.0, 0.42), T(2, 0.43, 0.42), T(0, 0.40, 0.41)])
    assert [k.t for k in ticks] == [0.0, 3.0]


def test_spread_is_time_weighted():
    # 2c spread for 85s, 10c spread for 15s: the median is 2c, p90 lands on the wide one.
    ticks = [T(0, 0.40, 0.42), T(85, 0.35, 0.45), T(100, 0.40, 0.42)]
    s = ecm.taker_stats(ticks, latencies=())
    assert s["spread_p50"] == pytest.approx(0.02)
    assert s["spread_p90"] == pytest.approx(0.10)


def test_touch_decay_counts_ask_moving_up_by_arrival():
    ticks = [T(0, 0.40, 0.42), T(0.5, 0.40, 0.44), T(10, 0.40, 0.44)]
    d = ecm.taker_stats(ticks, latencies=(1.0,))["touch_decay"]["1s"]
    # From t=0 the ask is 44c by t=1 (moved); from t=0.5 it is unchanged at t=1.5.
    assert d["p_ask_up"] == pytest.approx(0.5)
    assert d["mean_ask_up"] == pytest.approx(0.01)


def test_taker_cost_is_half_spread_plus_fee_at_mid():
    ticks = [T(0, 0.49, 0.51), T(100, 0.49, 0.51)]
    s = ecm.taker_stats(ticks, latencies=())
    assert s["taker_cost_per_contract"] == pytest.approx(0.01 + 0.07 * 0.5 * 0.5)


def test_maker_fill_bounds_and_adverse_move():
    # Post at bid 40c at t=0. At t=20 the bid level empties (39c): upper-bound fill only.
    # At t=40 an ask appears at 40c: someone sold at our price - lower-bound fill.
    # 60s after that fill the mid is 37.5c: we bought at 40c, adverse -2.5c.
    ticks = [T(0, 0.40, 0.42), T(20, 0.39, 0.42), T(40, 0.38, 0.40), T(100, 0.37, 0.38), T(400, 0.37, 0.38)]
    m = ecm.maker_stats(ticks, horizons=(60,), markout_s=60, post_every=1000)
    assert m["60s"]["posts"] == 1
    assert m["60s"]["fill_lower"] == 1.0 and m["60s"]["fill_upper"] == 1.0
    assert m["60s"]["adverse_move_mean"] == pytest.approx(0.375 - 0.40)


def test_maker_upper_only_when_level_empties_without_a_seller_at_our_price():
    ticks = [T(0, 0.40, 0.42), T(20, 0.39, 0.42), T(100, 0.39, 0.42)]
    m = ecm.maker_stats(ticks, horizons=(60,), post_every=1000)
    assert m["60s"]["fill_lower"] == 0.0 and m["60s"]["fill_upper"] == 1.0


def test_maker_vs_taker_saving():
    taker = {"mid_p50": 0.50, "spread_p50": 0.02}
    maker = {"60s": {"fill_lower": 0.2, "fill_upper": 0.5, "adverse_move_mean": -0.005}}
    out = ecm.maker_vs_taker(taker, maker)
    taker_cost = 0.01 + 0.0175
    maker_cost = -0.01 + 0.0175 * 0.25 + 0.005
    assert out["taker_cost"] == pytest.approx(taker_cost)
    assert out["60s"]["saving_if_filled"] == pytest.approx(taker_cost - maker_cost, abs=1e-5)
    assert out["60s"]["expected_saving_lower"] == pytest.approx((taker_cost - maker_cost) * 0.2, abs=1e-5)


def test_series_model_skips_thin_contracts_and_aggregates():
    busy = [T(i * 10, 0.40, 0.42) for i in range(200)]
    thin = [T(0, 0.40, 0.42)]
    out = ecm.series_model({"S-A": busy, "S-B": thin})
    assert out["contracts"] == 1 and out["taker"]["spread_p50"] == pytest.approx(0.02)
    assert out["maker"]["60s"]["posts"] > 0


def test_fetch_ticks_groups_by_contract():
    class Cur:
        def execute(self, sql, params):
            self.params = params

        def fetchall(self):
            at = datetime(2026, 10, 24, 9)
            return [{"market_ticker": "S-A", "observed_at_utc": at, "yes_bid_dollars": 0.4,
                     "yes_ask_dollars": 0.42, "yes_bid_size_fp": 10, "yes_ask_size_fp": None},
                    {"market_ticker": "S-A", "observed_at_utc": at, "yes_bid_dollars": None,
                     "yes_ask_dollars": 0.42, "yes_bid_size_fp": None, "yes_ask_size_fp": None}]

    c = Cur()
    out = ecm.fetch_ticks(c, "S", datetime(2026, 10, 24, tzinfo=timezone.utc), datetime(2026, 10, 25, tzinfo=timezone.utc))
    assert list(out) == ["S-A"] and len(out["S-A"]) == 1 and out["S-A"][0].ask_size is None
    assert c.params[2] == "S-%"


# -- queue-aware maker fills from trade prints -----------------------------------

from app.trading.exec_cost_model import Print


def P(t, price, count, side="no"):
    return Print(float(t), price, float(count), side)


def test_queue_fill_needs_bid_hits_past_the_queue_ahead():
    # Post at 40c behind 10 contracts. 6 + 4 hit the bid: still 1 short of 10 ahead + our 1.
    ticks = [T(0, 0.40, 0.42, bs=10), T(200, 0.40, 0.42, bs=10), T(400, 0.40, 0.42, bs=10)]
    short = [P(0, 0.41, 1, side="yes"), P(10, 0.40, 6), P(20, 0.40, 4), P(30, 0.41, 50, side="yes"), P(399, 0.42, 1, side="yes")]
    q = ecm.maker_queue_stats(ticks, short, horizons=(60,), post_every=1000)
    assert q["60s"]["posts"] == 1 and q["60s"]["fill_queue"] == 0.0
    enough = short[:3] + [P(25, 0.40, 1)] + short[3:]
    q = ecm.maker_queue_stats(ticks, enough, horizons=(60,), post_every=1000)
    assert q["60s"]["fill_queue"] == 1.0


def test_queue_fill_when_a_print_trades_through_our_price():
    ticks = [T(0, 0.40, 0.42, bs=500), T(100, 0.37, 0.39, bs=5), T(400, 0.37, 0.39, bs=5)]
    prints = [P(0, 0.41, 1, side="yes"), P(50, 0.39, 2), P(399, 0.39, 1)]
    q = ecm.maker_queue_stats(ticks, prints, horizons=(60,), markout_s=60, post_every=1000)
    assert q["60s"]["fill_queue"] == 1.0
    # Filled at 40c at t=50; the mid at t=110 is 38c: a 2c adverse move.
    assert q["60s"]["adverse_move_mean"] == pytest.approx(-0.02)


def test_queue_stats_only_count_posts_covered_by_prints():
    ticks = [T(0, 0.40, 0.42), T(500, 0.40, 0.42), T(1000, 0.40, 0.42)]
    prints = [P(490, 0.41, 1, side="yes"), P(900, 0.41, 1, side="yes")]
    q = ecm.maker_queue_stats(ticks, prints, horizons=(60,), post_every=1)
    assert q["60s"]["posts"] == 1  # only the t=500 post; t=0 predates the first print
    assert ecm.maker_queue_stats(ticks, [], horizons=(60,)) == {}


def test_series_model_reports_queue_view_when_prints_exist():
    ticks = [T(i * 10, 0.40, 0.42, bs=1) for i in range(40)]
    prints = [P(i * 10 + 5, 0.40, 5) for i in range(40)]
    out = ecm.series_model({"S-A": ticks}, {"S-A": prints})
    assert out["maker_queue"]["60s"]["fill_queue"] == 1.0
    assert "60s" in out["maker_queue_vs_taker"]
    assert "maker_queue" not in ecm.series_model({"S-A": ticks})
