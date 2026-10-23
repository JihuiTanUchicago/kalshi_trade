"""Synthetic, offline financial and causality checks; no provider/DB access."""
import copy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import kalshi_perps_backtest as perps
from app.markets import Market


MARKET = Market("btc_perp", "BTC_PERP", "Bitcoin perpetual research", 1, 90,
                deployable=False, kind="perpetual")
# January: 08:00 New York funding is 13:00 UTC, two minutes after BASE.
BASE = int(datetime(2026, 1, 2, 12, 58, tzinfo=timezone.utc).timestamp())


def _history(n=7, price="10", estimate="-0.01", step="0.01"):
    end = BASE + (n - 1) * 60
    return {
        "ticker": "BTC-PERP", "environment": "demo", "data_fingerprint": "synthetic-fixture-v1",
        "instrument": {
            "ticker": "BTC-PERP", "environment": "demo", "verified_bitcoin": True,
            "price_unit": "USD", "price_basis": "per_contract", "funding_rate_unit": "decimal",
            "contract_multiplier": "0.0001", "quantity_step": step,
            "funding_schedule": {"timezone": "America/New_York", "hours": [0, 8, 16]},
        },
        "candles": [{"ts": BASE + i * 60, "open": price, "high": price,
                     "low": price, "close": price, "bid": None, "ask": None,
                     "retrieved_at": "2026-01-03T00:00:00Z"} for i in range(n)],
        "observations": [{"kind": "funding_estimate", "ts": BASE, "available_at": BASE,
                          "funding_rate": estimate}],
        "funding": [{"ts": BASE + 120, "rate": "0.01", "mark_price": "10.5"}],
        "coverage": {"funding": {"complete": True, "start_ts": BASE, "end_ts": end,
                                  "expected_count": 1, "missing_timestamps": []}},
    }


def _spec(signal="funding", side="both", lookback=60, threshold=0.001):
    return {"market": "btc_perp", "sizing": {"stake": 100, "max_positions": 1},
            "perpetual": perps.normalize_assumptions({"signal": signal, "side": side,
                                                       "lookback_minutes": lookback,
                                                       "threshold": threshold})}


def _run(history, spec=None, start=None, end=None, what_if=None):
    ds = perps.build_dataset(MARKET, history)
    trades = perps.simulate(spec or _spec(), ds, ds.start_ts if start is None else start,
                            ds.end_ts if end is None else end, what_if)
    return ds, trades


@pytest.mark.parametrize("side,rate,quantity,entry,exit_,gross,funding,fees", [
    ("long", "0.01", "9.98", "10.0050", "10.9945", "9.875210", "-1.047900", "0.2514900120"),
    ("long", "-0.01", "9.98", "10.0050", "10.9945", "9.875210", "1.047900", "0.2514900120"),
    ("short", "0.01", "9.99", "9.9950", "11.0055", "-10.094895", "1.048950", "0.2517539940"),
    ("short", "-0.01", "9.99", "9.9950", "11.0055", "-10.094895", "-1.048950", "0.2517539940"),
])
def test_independent_golden_signed_pnl_funding_and_costs(side, rate, quantity, entry, exit_, gross, funding, fees):
    h = _history(estimate="-0.01" if side == "long" else "0.01")
    # Final open is the preceding bar boundary; its later close is irrelevant.
    h["candles"][-1].update(open="11", high="11", close="11")
    h["funding"][0]["rate"] = rate
    ds, trades = _run(h)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == side
    assert t.exact_quantity == Decimal(quantity)
    assert t.entry_price_decimal == Decimal(entry)
    assert t.exit_price_decimal == Decimal(exit_)
    assert t.gross_pnl_decimal == Decimal(gross)
    assert t.funding_pnl_decimal == Decimal(funding)
    # Notional fees are independent of direction, assessed at both actual scenario prices.
    expected_fees = Decimal(fees)
    assert t.fees_decimal == expected_fees
    assert t.pnl_decimal == Decimal(gross) + Decimal(funding) - expected_fees
    assert t.capital_at_risk == 100
    assert t.net_return == pytest.approx(float(t.pnl_decimal) / 100)
    assert t.underlying_quantity == Decimal(quantity) * Decimal("0.0001")
    assert t.entry_ts == BASE and t.exit_ts == ds.end_ts - 60
    assert t.reason == "window_end"


def test_per_underlying_prices_apply_multiplier_once_and_native_prices_do_not():
    native = _history()
    scaled = copy.deepcopy(native)
    scaled["instrument"]["price_basis"] = "per_underlying"
    for row in scaled["candles"]:
        for key in ("open", "high", "low", "close"):
            row[key] = str(Decimal(row[key]) * 10000)
    scaled["funding"][0]["mark_price"] = "105000"
    _, first = _run(native)
    _, second = _run(scaled)
    assert first[0].exact_quantity == second[0].exact_quantity
    assert first[0].pnl_decimal == second[0].pnl_decimal
    assert first[0].entry_price == 10.005  # per-contract USD, not BTC reference price


@pytest.mark.parametrize("field,value", [
    ("contract_multiplier", None), ("quantity_step", "0"), ("price_unit", "cents"),
    ("price_basis", "unknown"), ("funding_rate_unit", "percent"), ("verified_bitcoin", False),
])
def test_unknown_financial_units_fail_closed(field, value):
    h = _history()
    h["instrument"][field] = value
    with pytest.raises(perps.PerpetualDataError):
        perps.build_dataset(MARKET, h)


@pytest.mark.parametrize("change", ["unknown", "incomplete", "missing_row", "narrow_interval", "missing_schedule"])
def test_no_trade_without_complete_funding_coverage(change):
    h = _history()
    if change == "unknown":
        h["coverage"] = {}
    elif change == "incomplete":
        h["coverage"]["funding"]["complete"] = False
    elif change == "missing_row":
        h["funding"] = []  # even a stale complete=True flag cannot invent this payment
    elif change == "narrow_interval":
        h["coverage"]["funding"]["end_ts"] -= 120
    else:
        h["instrument"].pop("funding_schedule")
    ds, trades = _run(h)
    assert trades == []
    assert "funding" in ds.last_rejection
    assert ds.summary()["rejection_reason"] == ds.last_rejection


def test_funding_free_interval_requires_verified_coverage_but_not_fake_zero_row():
    h = _history()
    # Move the complete interval to after the 08:00 New York settlement.
    for row in h["candles"]:
        row["ts"] += 180
    h["observations"][0].update(ts=BASE + 180, available_at=BASE + 180)
    h["coverage"]["funding"].update(start_ts=BASE + 180, end_ts=BASE + 540, expected_count=0)
    h["funding"] = []
    ds, trades = _run(h)
    assert len(trades) == 1 and trades[0].funding_pnl_decimal == 0
    assert ds.last_rejection == ""


def test_internal_gap_rejects_entire_replay_instead_of_jumping_price():
    h = _history()
    h["candles"].pop(3)
    ds, trades = _run(h)
    assert trades == []
    assert "gap" in ds.last_rejection


def test_momentum_and_mean_reversion_use_only_prior_completed_closes():
    h = _history()
    for i, row in enumerate(h["candles"]):
        p = str(Decimal(10) + i)
        row.update(open=p, high=p, low=p, close=p)
    ds = perps.build_dataset(MARKET, h)
    momentum = perps.normalize_assumptions({"lookback_minutes": 1, "threshold": 0.01})
    reverse = {**momentum, "signal": "mean_reversion"}
    assert perps.target_at(ds, momentum, BASE) is None
    assert perps.target_at(ds, momentum, BASE + 60) == "long"
    assert perps.target_at(ds, reverse, BASE + 60) == "short"
    # Change the executing bar and all later OHLC; the preceding target stays identical.
    h["candles"][2].update(open="1", high="100000", low="1", close="100000")
    changed = perps.build_dataset(MARKET, h)
    assert perps.target_at(changed, momentum, BASE + 60) == "long"
    _, trades = _run(h, _spec("momentum", lookback=1, threshold=0.01))
    assert trades[0].entry_ts == BASE + 60
    assert trades[0].entry_price_decimal == Decimal("1.0005")


def test_momentum_reference_never_reaches_before_requested_replay_start():
    h = _history()
    h["candles"][2].update(open="12", high="12", low="12", close="12")
    ds = perps.build_dataset(MARKET, h)
    rule = perps.normalize_assumptions({"lookback_minutes": 2})
    assert perps.target_at(ds, rule, BASE + 120) == "long"
    assert perps.target_at(ds, rule, BASE + 120, start_ts=BASE + 60) is None


def test_delayed_observation_cannot_be_used_before_publication_or_replaced_by_older_revision():
    h = _history()
    h["observations"][0]["available_at"] = BASE + 120
    h["observations"].extend([
        {"kind": "funding_estimate", "ts": BASE + 60, "available_at": BASE + 60,
         "funding_rate": "0.03"},
        {"kind": "funding_estimate", "ts": BASE + 300, "available_at": BASE + 300,
         "funding_rate": "-0.99"},
    ])
    ds = perps.build_dataset(MARKET, h)
    rule = _spec()["perpetual"]
    assert perps.target_at(ds, rule, BASE) is None
    assert perps.target_at(ds, rule, BASE + 60) == "short"
    assert perps.target_at(ds, rule, BASE + 120) == "short"  # older delayed estimate cannot overwrite
    h["observations"][-1]["funding_rate"] = "0.99"
    future_change = perps.build_dataset(MARKET, h)
    assert perps.target_at(future_change, rule, BASE + 120) == "short"


def test_future_realized_funding_never_becomes_a_signal_or_fit_feature():
    h = _history()
    ds = perps.build_dataset(MARKET, h)
    original = perps.strategy_window(ds, BASE, BASE + 120)
    h["funding"][0]["rate"] = "-0.9999"
    h["funding"][0]["mark_price"] = "99999999"
    changed = perps.build_dataset(MARKET, h)
    assert perps.strategy_window(changed, BASE, BASE + 120) == original
    assert [row["ts"] for row in original["frames"]] == [BASE, BASE + 60]
    assert "funding" not in original
    assert perps.target_at(changed, _spec()["perpetual"], BASE) == "long"


def test_payment_ledger_alone_is_not_an_observed_funding_signal():
    h = _history()
    h["observations"] = []
    _, trades = _run(h)
    assert trades == []


def test_explicit_delayed_bar_availability_blocks_price_signal():
    h = _history()
    h["candles"][1].update(open="12", high="12", low="12", close="12", available_at=BASE + 120)
    ds = perps.build_dataset(MARKET, h)
    rule = _spec("momentum", lookback=1)["perpetual"]
    assert perps.target_at(ds, rule, BASE + 60) is None
    window = perps.strategy_window(ds, BASE, ds.end_ts)
    assert BASE + 60 not in [row["ts"] for row in window["frames"]]


def test_exact_funding_boundaries_charge_exit_and_exclude_entry():
    h = _history(n=5)
    # Start the replay and position exactly at the scheduled payment.
    h["observations"][0].update(ts=BASE + 120, available_at=BASE + 120)
    ds, trades = _run(h, start=BASE + 120)
    assert len(trades) == 1
    assert trades[0].entry_ts == BASE + 120
    assert trades[0].funding_pnl_decimal == 0
    # Force exit exactly at funding. An existing holder pays before its exit fill.
    h = _history(n=4)
    _, trades = _run(h)
    assert trades[0].exit_ts == BASE + 120
    assert trades[0].funding_pnl_decimal == Decimal("-1.047900")


def test_scope_and_boundary_close_do_not_read_newer_bars_or_funding():
    h = _history()
    end = BASE + 180
    _, first = _run(h, end=end)
    h["candles"][-1].update(open="999", high="999", low="999", close="999")
    h["funding"].append({"ts": BASE + 300, "rate": "0.99", "mark_price": "999"})
    _, second = _run(h, end=end)
    assert [(t.entry_ts, t.exit_ts, t.pnl_decimal) for t in first] == [
        (t.entry_ts, t.exit_ts, t.pnl_decimal) for t in second]
    assert first[0].exit_ts == end - 60


def test_common_exclusive_last_bar_plus_one_bound_needs_no_future_coverage():
    from app import backtest

    ds = perps.build_dataset(MARKET, _history())
    canonical = perps.simulate(_spec(), ds, ds.start_ts, ds.end_ts)
    common = backtest.simulate(_spec(), ds, ds.start_ts, ds.end_ts + 1)
    assert len(common) == 1
    assert common[0].pnl_decimal == canonical[0].pnl_decimal
    assert common[0].exit_ts == canonical[0].exit_ts == ds.end_ts - 60


def test_quantity_uses_contract_step_and_reserves_entry_fee_within_capital():
    h = _history(price="0.4", step="0.01")
    h["funding"][0]["mark_price"] = "0.4"
    _, trades = _run(h)
    trade = trades[0]
    assert trade.exact_quantity % Decimal("0.01") == 0
    entry_notional = trade.exact_quantity * trade.entry_price_decimal
    assert entry_notional * Decimal("1.0012") <= Decimal(100)
    assert (trade.exact_quantity + Decimal("0.01")) * trade.entry_price_decimal * Decimal("1.0012") > Decimal(100)
    assert trade.exact_quantity > 1  # no binary 0/1 cap or binary-contract fee formula


@pytest.mark.parametrize("price,exhausted", [("12", False), ("40", True)])
def test_losses_reduce_next_allocation_and_exhausted_capital_prevents_reentry(price, exhausted):
    h = _history(n=10, estimate="0.01")
    # Synthetic short marked against a >100% upward move, then another entry opportunity.
    for row in h["candles"][3:]:
        row.update(open=price, high=price, low=price, close=price)
    h["observations"].extend([
        {"kind": "funding_estimate", "ts": BASE + 120, "available_at": BASE + 120, "funding_rate": "0"},
        {"kind": "funding_estimate", "ts": BASE + 180, "available_at": BASE + 180, "funding_rate": "0.01"},
    ])
    _, trades = _run(h)
    if exhausted:
        assert len(trades) == 1
        assert trades[0].pnl < -100  # loss remains visible; no artificial zero floor
    else:
        assert len(trades) == 2
        assert trades[1].capital_at_risk == pytest.approx(100 + trades[0].pnl)
        assert trades[1].capital_at_risk < 100
        assert trades[1].exact_quantity * trades[1].entry_price_decimal <= trades[1].capital_decimal


def test_max_holding_24_hours_and_one_position_only():
    h = _history(n=1500)
    h["observations"] = [{"kind": "funding_estimate", "ts": BASE + i * 60,
                           "available_at": BASE + i * 60, "funding_rate": "-0.01"}
                          for i in range(1500)]
    schedule = h["instrument"]["funding_schedule"]
    h["funding"] = [{"ts": ts, "rate": "0", "mark_price": "10"}
                    for ts in perps._expected_funding(schedule, BASE, h["coverage"]["funding"]["end_ts"])]
    _, trades = _run(h)
    assert trades[0].reason == "max_holding"
    assert trades[0].exit_ts - trades[0].entry_ts == 86400
    assert all(t.exit_ts - t.entry_ts <= 86400 for t in trades)
    assert all(a.exit_ts < b.entry_ts for a, b in zip(trades, trades[1:]))
    assert trades[1].capital_at_risk < trades[0].capital_at_risk  # costs reduce next capital


@pytest.mark.parametrize("raw", [
    {"leverage": 2}, {"max_holding_minutes": 60}, {"taker_fee_bps": 0},
    {"slippage_bps": 0}, {"maker_fee_bps": 1}, {"lookback_minutes": True},
    {"lookback_minutes": 1441}, {"threshold": float("nan")}, {"signal": "future_price"},
])
def test_unsupported_or_optimistically_changed_assumptions_rejected(raw):
    with pytest.raises(ValueError):
        perps.normalize_assumptions(raw)


def test_arbitrary_code_cross_positions_and_improved_cost_scenarios_rejected():
    ds = perps.build_dataset(MARKET, _history())
    for spec in ({**_spec(), "code": "def signals(window): return []"},
                 {**_spec(), "cross": {"legs": []}},
                 {**_spec(), "sizing": {"stake": 100, "max_positions": 2}}):
        with pytest.raises(ValueError):
            perps.simulate(spec, ds, ds.start_ts, ds.end_ts)
    for scenario in (SimpleNamespace(fee_multiplier=0.99, slippage_cents=0),
                     SimpleNamespace(fee_multiplier=1, slippage_cents=-0.01)):
        with pytest.raises(ValueError):
            perps.simulate(_spec(), ds, ds.start_ts, ds.end_ts, scenario)


def test_cost_stress_worsens_same_direction_trade_and_labels_research_limitations():
    h = _history()
    ds, normal = _run(h)
    _, stressed = _run(h, what_if=SimpleNamespace(fee_multiplier=2, slippage_cents=0.01, stake=None))
    assert stressed[0].pnl < normal[0].pnl
    summary = ds.summary()
    assert summary["kind"] == "perpetual" and summary["data_fingerprint"] == "synthetic-fixture-v1"
    assert any("Uncalibrated" in item for item in summary["limitations"])
    assert summary["assumptions"]["taker_fee_bps"] == 12


def test_funding_schedule_accounts_for_new_york_dst():
    schedule = {"timezone": "America/New_York", "hours": [0, 8, 16]}
    start = int(datetime(2026, 3, 8, tzinfo=timezone.utc).timestamp())
    events = perps._expected_funding(schedule, start, start + 86400)
    hours_utc = [datetime.fromtimestamp(ts, timezone.utc).hour for ts in events]
    assert hours_utc == [5, 12, 20]  # 00:00 EST, then 08:00/16:00 EDT


def test_conflicting_duplicate_bars_and_funding_rejected():
    for kind in ("candles", "funding"):
        h = _history()
        row = copy.deepcopy(h[kind][0])
        row["close" if kind == "candles" else "rate"] = "9" if kind == "candles" else "-0.03"
        if kind == "candles":
            row["low"] = "9"
        h[kind].append(row)
        with pytest.raises(perps.PerpetualDataError, match="conflicting duplicate"):
            perps.build_dataset(MARKET, h)
