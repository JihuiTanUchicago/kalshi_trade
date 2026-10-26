"""Legging-safe cross-contract (relative-value pair) LIVE/DEMO entry, and the single-market-cross
live gate relaxation.

A pair must stay balanced (equal YES and NO), but two real kernel orders can't fill atomically, so
`engine._kernel_buy_pair` keeps the legs matched by hand: buy YES, buy NO for the YES fill, and
flatten any naked excess on the exchange immediately — booking the round-trip P&L and, if the
unwind itself under-fills, recording the still-naked remainder as a TRACKED position so the loss /
drawdown guard closes it. These tests drive that logic with a scripted fake kernel and recorded
repo writes (the same no-live-DB pattern as test_cross_contract.py).
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.trading import engine
from app.trading import spec as specmod

CLOSE = datetime.fromtimestamp(1_000_600, tz=timezone.utc)


def _legs():
    # (side, ticker, buy_price, own-side SELL price at the bid, close_time)
    # YES long: buy the 0.40 ask, unwind at the 0.38 bid. NO short: buy 0.55, sell 0.43 (unused —
    # the excess is always on leg 1, the YES leg).
    return [("yes", "L_YES", 0.40, 0.38, CLOSE),
            ("no", "S_NO", 0.55, 0.43, CLOSE)]


class _ScriptedKernel:
    """Returns the scripted (fill_qty, fill_price, fee) for each execute() call, in call order:
    buy YES, buy NO, then (if needed) the unwind sell YES."""

    def __init__(self, fills):
        self.fills = list(fills)
        self.intents = []

    def execute(self, intent):
        self.intents.append(intent)
        fq, fp, fee = self.fills.pop(0)
        return SimpleNamespace(fill_qty_contracts=fq, fill_price_dollars=fp,
                               fee_dollars=fee, external_order_id="ext-%d" % len(self.intents))


def _wire(monkeypatch):
    rec = {"opens": [], "closeds": []}

    def _open(cur, dep_id, uid, mode, ticker, side, qty, price, fee, close, order_ref=None):
        rec["opens"].append({"ticker": ticker, "side": side, "qty": qty, "price": price,
                             "fee": fee, "mode": mode})
        return len(rec["opens"])

    def _closed(cur, dep_id, uid, mode, ticker, side, qty, entry_price, entry_fee, exit_price,
                exit_fee, pnl, reason, close, order_ref=None):
        rec["closeds"].append({"ticker": ticker, "side": side, "qty": qty, "entry_price": entry_price,
                               "entry_fee": entry_fee, "exit_price": exit_price, "exit_fee": exit_fee,
                               "pnl": pnl, "reason": reason})
        return len(rec["closeds"])

    monkeypatch.setattr(engine.repo, "insert_position", _open)
    monkeypatch.setattr(engine.repo, "insert_closed_position", _closed)

    # P0 durability wrapper: the merged _kernel_buy_pair logs an intent before each order and books
    # inside one transaction claimed per leg. Stub those so these tests stay focused on legging logic
    # (the intent/recovery machinery itself is covered in test_order_intent_recovery.py).
    @contextmanager
    def _tx(conn):
        yield None  # cursor unused; insert_position/_closed shims ignore it
    counter = {"n": 0}

    def _log(conn, dep, action, side, ticker, qty, price, mode, **kw):
        counter["n"] += 1
        return "intent-%d" % counter["n"]

    monkeypatch.setattr(engine.repo, "transaction", _tx)
    monkeypatch.setattr(engine.repo, "claim_intent_booking", lambda *a, **k: True)
    monkeypatch.setattr(engine.repo, "mark_order_intent", lambda *a, **k: True)
    monkeypatch.setattr(engine, "_log_order_intent", _log)
    return rec


def _dep():
    return {"id": 7, "user_id": 3, "mode": "demo"}


# -- both legs fully fill: a balanced pair, nothing to unwind -------------------


def test_both_legs_fully_fill_records_balanced_pair(monkeypatch):
    rec = _wire(monkeypatch)
    kernel = _ScriptedKernel([(10, 0.40, 0.70), (10, 0.55, 0.90)])
    ok = engine._kernel_buy_pair(object(), object(), _dep(), kernel, _legs(), 10, "demo")
    assert ok is True
    assert len(kernel.intents) == 2                       # two buys, no unwind sell
    assert all(i.action == "buy" for i in kernel.intents)
    legs = {o["side"]: o for o in rec["opens"]}
    assert set(legs) == {"yes", "no"}
    assert legs["yes"]["qty"] == 10 and legs["no"]["qty"] == 10   # balanced at the requested qty
    assert legs["yes"]["fee"] == 0.70 and legs["no"]["fee"] == 0.90
    assert rec["closeds"] == []                           # nothing flattened


# -- leg 2 under-fills: flatten the excess YES, book the round-trip -------------


def test_leg2_underfills_unwinds_excess_and_records_pair_at_min_qty(monkeypatch):
    rec = _wire(monkeypatch)
    # buy YES 10 @0.40 fee0.70 ; buy NO fills 7 @0.55 fee0.63 ; sell 3 excess YES @0.38 fee0.06.
    kernel = _ScriptedKernel([(10, 0.40, 0.70), (7, 0.55, 0.63), (3, 0.38, 0.06)])
    ok = engine._kernel_buy_pair(object(), object(), _dep(), kernel, _legs(), 10, "demo")
    assert ok is True
    # Three orders: two buys + ONE unwind sell of exactly the excess.
    assert len(kernel.intents) == 3
    sell = kernel.intents[2]
    assert sell.action == "sell" and sell.side == "yes" and sell.ticker == "L_YES"
    assert sell.qty_contracts == 3
    # Hedged pair recorded at the min (7), YES fee pro-rated (0.70 * 7/10 = 0.49), NO fee full.
    legs = {o["side"]: o for o in rec["opens"]}
    assert legs["yes"]["qty"] == 7 and legs["no"]["qty"] == 7
    assert legs["yes"]["fee"] == pytest.approx(0.49)
    assert legs["no"]["fee"] == 0.63
    # Round-trip of the 3 flattened contracts booked exactly: 3*(0.38-0.40) - 0.21 - 0.06 = -0.33.
    assert len(rec["closeds"]) == 1
    rt = rec["closeds"][0]
    assert rt["qty"] == 3 and rt["side"] == "yes" and rt["reason"] == "pair_unwind"
    assert rt["entry_fee"] == pytest.approx(0.70 * 3 / 10)          # 0.21
    assert rt["exit_fee"] == 0.06
    assert rt["pnl"] == pytest.approx(3 * (0.38 - 0.40) - 0.21 - 0.06)   # -0.33
    # Every YES contract is accounted for (7 hedged + 3 flattened = 10 bought); none left naked.
    assert sum(o["qty"] for o in rec["opens"] if o["side"] == "yes") + rt["qty"] == 10


# -- leg 2 fills nothing: unwind ALL of leg 1, deployment flat, return False ----


def test_leg2_fills_zero_unwinds_leg1_fully_and_returns_false(monkeypatch):
    rec = _wire(monkeypatch)
    # buy YES 10 @0.40 fee0.70 ; buy NO fills 0 ; sell all 10 YES @0.38 fee0.20.
    kernel = _ScriptedKernel([(10, 0.40, 0.70), (0, 0.55, 0.0), (10, 0.38, 0.20)])
    ok = engine._kernel_buy_pair(object(), object(), _dep(), kernel, _legs(), 10, "demo")
    assert ok is False                                   # no hedged pair opened
    assert rec["opens"] == []                            # no held positions -> flat
    assert len(rec["closeds"]) == 1                      # the whole round-trip booked
    rt = rec["closeds"][0]
    assert rt["qty"] == 10 and rt["reason"] == "pair_unwind"
    assert rt["entry_fee"] == pytest.approx(0.70)        # full buy fee on the unwound 10
    assert rt["pnl"] == pytest.approx(10 * (0.38 - 0.40) - 0.70 - 0.20)   # -1.10


# -- leg 1 never fills: no second order, no exposure, return False --------------


def test_leg1_fills_zero_returns_false_with_no_second_order(monkeypatch):
    rec = _wire(monkeypatch)
    kernel = _ScriptedKernel([(0, 0.40, 0.0)])           # only the leg-1 buy is attempted
    ok = engine._kernel_buy_pair(object(), object(), _dep(), kernel, _legs(), 10, "demo")
    assert ok is False
    assert len(kernel.intents) == 1                      # leg 2 is never bought if leg 1 is empty
    assert rec["opens"] == [] and rec["closeds"] == []


# -- CRITICAL: the unwind sell itself under-fills -> residual tracked, not dropped


def test_unwind_underfill_records_residual_as_tracked_position(monkeypatch):
    rec = _wire(monkeypatch)
    # buy YES 10 ; buy NO 7 (excess 3) ; unwind sell asks 3 but fills only 1 @0.38 fee0.02.
    kernel = _ScriptedKernel([(10, 0.40, 0.70), (7, 0.55, 0.63), (1, 0.38, 0.02)])
    ok = engine._kernel_buy_pair(object(), object(), _dep(), kernel, _legs(), 10, "demo")
    assert ok is True                                    # a hedged pair of 7 did open
    yes_opens = [o for o in rec["opens"] if o["side"] == "yes"]
    no_opens = [o for o in rec["opens"] if o["side"] == "no"]
    assert len(no_opens) == 1 and no_opens[0]["qty"] == 7
    # Two YES OPEN rows: the hedged 7 and the still-naked residual 2 (NOT silently dropped).
    assert sorted(o["qty"] for o in yes_opens) == [2, 7]
    assert len(rec["closeds"]) == 1 and rec["closeds"][0]["qty"] == 1   # the 1 that did flatten
    # Every bought YES contract is tracked: 7 hedged + 1 flattened + 2 residual = 10.
    tracked = sum(o["qty"] for o in yes_opens) + rec["closeds"][0]["qty"]
    assert tracked == 10
    # Fees split exactly across the three slices, summing back to leg 1's real fill fee (0.70).
    residual = next(o for o in yes_opens if o["qty"] == 2)
    hedged = next(o for o in yes_opens if o["qty"] == 7)
    total_yes_fee = hedged["fee"] + rec["closeds"][0]["entry_fee"] + residual["fee"]
    assert total_yes_fee == pytest.approx(0.70)
    assert residual["fee"] == pytest.approx(0.70 - 0.70 * 7 / 10 - 0.70 * 1 / 10)   # 0.14


# -- the deploy gate: single-market cross is now live-able; multi-market is not --


def test_gate_allows_single_market_and_compatible_multi_market_live():
    single = specmod.validate({"market": "btc_daily",
        "cross": {"pairing": "cross_strike", "legs": []}})
    # btc_daily + eth_daily: both deployable, both daily -> a valid, allowed multi-market pair.
    multi = specmod.validate({"market": "btc_daily",
        "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}})
    plain = specmod.validate({"market": "btc_daily"})

    for mode in ("paper", "demo", "live"):
        assert engine.cross_deploy_block(single, mode) is None      # single-market: all modes
        assert engine.cross_deploy_block(multi, mode) is None       # compatible multi-market: allowed
        assert engine.cross_deploy_block(plain, mode) is None       # non-cross: never touched
