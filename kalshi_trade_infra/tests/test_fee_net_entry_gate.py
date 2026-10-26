"""The trade-entry edge gate must subtract Kalshi's ACTUAL state-dependent taker
fee at the live fill price, so a trade that is edge-positive GROSS but negative
NET (the fee dominates near the 50c mid, where it peaks) is REJECTED - on BOTH
the live decision path and its backtest/sim mirror, which must evaluate the
identical net-of-fee rule.

Guards the fix for the audit finding: a gross edge gate systematically enters
fee-negative trades near 50c. The fee is `ceil_cent(0.07*C*P*(1-P))`.
"""
from datetime import datetime, timezone

from app.trading import spec as specmod
from app.trading.markets import Contract, snapshot
from data_pipeline import live_trading_engine as lte
from data_pipeline import simulated_trading_engine as sim
from data_pipeline.kalshi_fees import taker_fee_per_contract_dollars


def _snap(spot, strike, tte_min, bid, ask, vol=0.001):
    ts = 1_800_000_000
    c = Contract("T", strike, datetime.fromtimestamp(ts + tte_min * 60, tz=timezone.utc))
    feats = {"spot": spot, "ret_1m": 0.0, "ret_5m": 0.0, "ret_15m": 0.0,
             "ret_60m": 0.0, "vol_15m": vol, "vol_60m": vol}
    return snapshot(feats, c, ts, bid, ask)


# --- app/trading/spec.py: the rule the backtester AND app live/paper engine both call ---

def test_spec_entries_rejects_gross_positive_net_negative_near_50c():
    # min_edge 0.5c: small enough that a thin GROSS edge clears the OLD gross gate.
    s = specmod.validate({"model": {"vol_window": 15},
                          "entry": {"min_edge": 0.005, "max_price": 0.95, "min_price": 0.05}})
    stake = s["sizing"]["stake"]
    probe = _snap(spot=100.05, strike=100.0, tte_min=10, bid=0.45, ask=0.47)
    fair = specmod.fair_yes(s, probe.features)
    assert 0.50 < fair < 0.60, fair  # near the 50c mid, where the fee peaks

    gross_thin = 0.012                 # 1.2c gross edge
    ask_thin = fair - gross_thin
    fee = taker_fee_per_contract_dollars(specmod.contracts_for(stake, ask_thin), ask_thin)
    # Precondition: the fee dominates this thin edge -> real net edge is negative.
    assert fee > gross_thin, (fee, gross_thin)
    thin = _snap(spot=100.05, strike=100.0, tte_min=10, bid=ask_thin - 0.02, ask=ask_thin)
    # OLD gross gate would have accepted (gross 1.2c >= min_edge 0.5c); now rejected.
    assert gross_thin >= s["entry"]["min_edge"]
    assert specmod.entries(s, [thin]) == []

    # A genuinely net-positive trade (6c gross, ~1.75c fee -> ~4c net) still passes.
    ask_fat = fair - 0.06
    fat = _snap(spot=100.05, strike=100.0, tte_min=10, bid=ask_fat - 0.02, ask=ask_fat)
    got = specmod.entries(s, [fat])
    assert len(got) == 1 and got[0].side == "yes"


def test_spec_pair_entries_rejects_net_negative_combined_edge():
    # Two cross_strike legs near 50c: combined GROSS edge clears min_edge, but each
    # leg pays a taker fee, so the net combined edge is negative -> no pair.
    s = specmod.validate({
        "cross": {"pairing": "cross_strike"},
        "entry": {"min_edge": 0.01, "max_price": 0.95, "min_price": 0.05},
    })
    # Same settlement (shared close_time) so the two strikes are comparable.
    long_leg = _snap(spot=100.05, strike=100.0, tte_min=10, bid=0.49, ask=0.51)
    short_leg = _snap(spot=99.95, strike=100.2, tte_min=10, bid=0.49, ask=0.51)
    stake = s["sizing"]["stake"]
    pairs = specmod.pair_entries(s, [long_leg, short_leg])
    for p in pairs:
        # If any pair survives, its GROSS edge must exceed the fees on both legs.
        qty = specmod.contracts_for(stake, p.long_price + p.short_price)
        fees = (taker_fee_per_contract_dollars(qty, p.long_price)
                + taker_fee_per_contract_dollars(qty, p.short_price))
        assert p.edge - fees >= s["entry"]["min_edge"] - 1e-12


# --- data_pipeline/live_trading_engine.py: the live decision path ---

def test_live_compute_buy_qty_rejects_fee_negative_trade():
    cfg = dict(lte.DEFAULT_SETTINGS)  # edge_threshold 0.01, max_trade_cost 2.0
    # Thin edge at the 50c mid: gross 1.5c > 1c threshold (old gate: BUY),
    # but fee ~2c -> net -0.5c (new gate: reject).
    assert lte.compute_buy_qty(prob=0.515, ask=0.50, cfg=cfg) == 0
    # Genuinely net-positive (7c gross, 2c fee -> 5c net) still trades.
    assert lte.compute_buy_qty(prob=0.57, ask=0.50, cfg=cfg) > 0


# --- data_pipeline/simulated_trading_engine.py: the live path's sim mirror ---

def test_sim_choose_qty_matches_live_net_of_fee():
    thr = 0.01
    # Same thin edge at the same price -> sim rejects exactly as live does (lockstep).
    assert sim.choose_qty(0.015, notional_cap=100.0, price=0.50, edge_threshold=thr) == 0
    assert sim.choose_qty(0.07, notional_cap=100.0, price=0.50, edge_threshold=thr) > 0
    # No price (legacy callers) -> no fee netting, behaviour unchanged.
    assert sim.choose_qty(0.015, price=None, edge_threshold=thr) > 0


if __name__ == "__main__":
    test_spec_entries_rejects_gross_positive_net_negative_near_50c()
    test_spec_pair_entries_rejects_net_negative_combined_edge()
    test_live_compute_buy_qty_rejects_fee_negative_trade()
    test_sim_choose_qty_matches_live_net_of_fee()
    print("fee-net entry gate tests OK")
