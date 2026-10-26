"""Cross-contract (relative-value pair) DEPLOYMENT: the paper/demo tick that opens BOTH legs,
and the deploy gate (single-market + cadence-compatible multi-market cross are deployable).

No live DB: the engine's repo reads/writes are monkeypatched + a recording fake kernel, the same
non-MySQL pattern as test_app_force_sell.py. The pair rule itself (which legs to buy) is proven in
test_app_backtest.py; here we prove the engine ACTS on it.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.trading import engine
from app.trading import spec as specmod
from app.trading.markets import Contract, snapshot


# -- deploy gate ---------------------------------------------------------------


def test_cross_deploy_block_single_and_compatible_multi_market_all_modes():
    single_market = specmod.validate({"market": "btc_daily",
        "cross": {"pairing": "cross_strike", "legs": []}})
    # btc_daily + eth_daily: both deployable, both daily cadence -> a valid multi-market pair.
    multi_market = specmod.validate({"market": "btc_daily",
        "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}})
    plain = specmod.validate({"market": "btc_daily"})

    # A single-market pair (cross_strike/calendar) now deploys on paper, demo AND live: the entry
    # path is legging-safe and the engine already ticks that one market.
    for mode in ("paper", "demo", "live"):
        assert engine.cross_deploy_block(single_market, mode) is None
    # A cadence-compatible, both-legs-deployable multi-market pair is allowed in every mode too
    # (it rides the synchronized multi-market feed).
    assert engine.cross_deploy_block(multi_market, "live") is None
    # Incompatible-cadence legs (btc_daily 60m vs btc15m 1m) are rejected at spec validation,
    # before the gate ever sees them.
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "btc_daily",
            "cross": {"pairing": "cross_sectional", "legs": [{"market": "btc15m"}]}})
    # A non-cross strategy is never touched by this gate.
    assert engine.cross_deploy_block(plain, "live") is None


def test_cross_deploy_block_allows_multi_market_when_deployable_and_compatible():
    # btc_daily + eth_daily: both deployable, same daily cadence -> allowed in every mode now that
    # the synchronized multi-market feed (engine.tick_cross_markets) exists.
    cross_market = specmod.validate({"market": "btc_daily",
        "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}})
    for mode in ("paper", "demo", "live"):
        assert engine.cross_deploy_block(cross_market, mode) is None


# -- paper/demo tick opens BOTH legs -------------------------------------------


def _cross_spec():
    return specmod.validate({
        "market": "btc15m",
        "entry": {"min_edge": 0.1, "max_spread": 0.05},
        "sizing": {"stake": 10.0, "max_positions": 1},
        "cross": {"pairing": "cross_strike", "legs": []},
    })


def _pair_snaps():
    """One cross_strike frame: BTC at 100, a 90-strike (cheap YES -> long) and a 110-strike (dear
    YES -> short the YES / buy NO), both quoted 0.49/0.51 and settling 10 minutes out."""
    now = 1_000_000
    close = datetime.fromtimestamp(now + 600, tz=timezone.utc)
    feats = {"spot": 100.0, "ret_1m": 0, "ret_5m": 0, "ret_15m": 0, "ret_60m": 0,
             "vol_15m": 0.002, "vol_60m": 0.002}
    s90 = snapshot(feats, Contract("M_90", 90.0, close, series="KXBTC15M"), now, 0.49, 0.51)
    s110 = snapshot(feats, Contract("M_110", 110.0, close, series="KXBTC15M"), now, 0.49, 0.51)
    assert s90 and s110
    return [s90, s110]


class _Conn:
    def cursor(self):
        return object()  # every repo call is monkeypatched; the cursor is never used


class _Kernel:
    def __init__(self):
        self.intents = []

    def execute(self, intent):
        self.intents.append(intent)
        return SimpleNamespace(fill_qty_contracts=intent.qty_contracts,
                               fill_price_dollars=intent.limit_price_dollars,
                               fee_dollars=0.0, external_order_id="ext-%d" % len(self.intents))


def _wire(monkeypatch, *, balance=1000.0):
    rec = {"inserted": [], "ledger": []}
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [])
    monkeypatch.setattr(engine.repo, "user_risk_config",
                        lambda cur, uid: {"max_open_positions": 20, "max_open_notional": 1000.0,
                                          "drawdown_limit_pct": 25.0})
    monkeypatch.setattr(engine.repo, "user_open_exposure", lambda cur, uid, mode=None: {"n": 0, "notional": 0.0})
    monkeypatch.setattr(engine.repo, "paper_balance", lambda cur, uid: balance)
    monkeypatch.setattr(engine.repo, "lock_user", lambda cur, uid: None)
    monkeypatch.setattr(engine.repo, "add_ledger",
                        lambda cur, uid, kind, amt, memo, pid: rec["ledger"].append((kind, amt, memo)))

    def _insert(cur, dep_id, uid, mode, ticker, side, qty, price, fee, close, order_ref=None):
        rec["inserted"].append({"ticker": ticker, "side": side, "qty": qty, "mode": mode, "price": price})
        return len(rec["inserted"])
    monkeypatch.setattr(engine.repo, "insert_position", _insert)
    monkeypatch.setattr(engine, "loss_guard", lambda cur, dep: False)

    @contextmanager
    def _tx(conn):
        yield object()
    monkeypatch.setattr(engine.repo, "transaction", _tx)
    from tests.conftest import patch_intent_passthrough
    patch_intent_passthrough(monkeypatch)  # P0-1 intent log is transparent for these routing tests
    return rec


def _dep(mode="paper"):
    return {"id": 1, "user_id": 1, "mode": mode, "market": "btc15m", "spec": _cross_spec()}


def test_paper_tick_opens_both_legs_of_a_pair(monkeypatch):
    rec = _wire(monkeypatch)
    out = engine.decide(_Conn(), _dep("paper"), _pair_snaps(), {}, engine.Sources())
    assert out["entries"] == 1                               # one pair opened
    legs = {p["side"]: p for p in rec["inserted"]}
    assert set(legs) == {"yes", "no"}                        # BOTH legs
    assert legs["yes"]["ticker"] == "M_90" and legs["no"]["ticker"] == "M_110"  # long cheap, short dear
    assert all(p["mode"] == "paper" for p in rec["inserted"])
    assert len(rec["ledger"]) == 2                           # each leg booked


def test_demo_tick_routes_both_legs_through_the_kernel(monkeypatch):
    rec = _wire(monkeypatch)
    kernel = _Kernel()
    sources = engine.Sources(demo_kernel=lambda uid: kernel)
    out = engine.decide(_Conn(), _dep("demo"), _pair_snaps(), {}, sources)
    assert out["entries"] == 1
    assert len(kernel.intents) == 2 and {i.side for i in kernel.intents} == {"yes", "no"}
    assert {p["side"] for p in rec["inserted"]} == {"yes", "no"}
    assert all(p["mode"] == "demo" for p in rec["inserted"])


def test_pair_slot_cap_counts_pairs_not_legs(monkeypatch):
    # max_positions=1 and a pair already open (two leg rows) -> no new pair this tick.
    rec = _wire(monkeypatch)
    monkeypatch.setattr(engine.repo, "open_positions",
                        lambda cur, dep_id: [{"ticker": "X_1"}, {"ticker": "X_2"}])
    out = engine.decide(_Conn(), _dep("paper"), _pair_snaps(), {}, engine.Sources())
    assert out["entries"] == 0 and rec["inserted"] == []
