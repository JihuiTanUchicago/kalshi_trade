"""An entry can never fill worse than its edge allows.

The decision gate (spec.entries) checks the edge net of the taker fee at the DECISION price. The
kernel then crosses the live ask by a few ticks, tolerates the ask running up to
KALSHI_MAX_ENTRY_SLIPPAGE (default 10c) past the signal, and escalates one tick per retry. Without
a cap, a 2c-edge signal could fill 10c+ worse: a guaranteed loser the backtest never saw. With the
entry's own-side fair value on intent.metadata, the kernel caps every BUY limit at the reservation
price (highest price whose net-of-fee edge still clears min_edge) and abandons an entry whose live
ask is already past it. Sells are never touched.
"""
from datetime import timedelta

import pytest

from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import MarketableLimitKernel, reservation_price
from data_pipeline.common import utc_now
from data_pipeline.kalshi_fees import taker_fee_per_contract_dollars
from data_pipeline.market_data import Quote

TICKER = "KXBTC15M-26OCT241315-15"


def quote(bid, ask, bid_size=5000.0, ask_size=5000.0):
    return Quote(ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=bid_size, yes_ask_size=ask_size,
                 as_of=utc_now() - timedelta(seconds=0.1), source="websocket")


class Feed:
    def __init__(self, q):
        self.q = q

    def quote(self, ticker, max_age_seconds=None):
        return self.q


class NeverFills:
    def __init__(self):
        self.sent = []

    def __call__(self, ticker, action, side, qty, price, client_order_id=None):
        self.sent.append({"action": action, "side": side, "qty": qty, "price": price})
        return {"client_order_id": client_order_id, "resp": {"fill_count": "0.00", "order_id": "o"}}


class FillsAtLimit(NeverFills):
    def __call__(self, ticker, action, side, qty, price, client_order_id=None):
        super().__call__(ticker, action, side, qty, price, client_order_id)
        wire = price if side == "yes" else 1.0 - price
        return {"client_order_id": client_order_id,
                "resp": {"fill_count": "%d.00" % qty, "average_fill_price": "%.4f" % wire,
                         "average_fee_paid": "0.0170", "order_id": "o"}}


def buy(qty, signal, fair=None, min_edge=None, side="yes", action="buy"):
    meta = {}
    if fair is not None:
        meta["fair"] = fair
    if min_edge is not None:
        meta["min_edge"] = min_edge
    return TradeIntent(action=action, side=side, ticker=TICKER, qty_contracts=qty, limit_price_dollars=signal,
                       model_name="m", now_ts=None, metadata=meta)


def kernel(sub, q, **kw):
    kw.setdefault("entry_cross_ticks", 2)
    kw.setdefault("max_entry_slippage", 0.10)
    kw.setdefault("max_attempts", 3)
    return MarketableLimitKernel(sub, Feed(q), **kw)


def test_reservation_price_is_the_highest_cent_that_clears_min_edge_net_of_fee():
    p = reservation_price(0.60, 0.02, 100)
    assert p == pytest.approx(0.56)
    assert 0.60 - p - taker_fee_per_contract_dollars(100, p) >= 0.02
    nxt = p + 0.01
    assert 0.60 - nxt - taker_fee_per_contract_dollars(100, nxt) < 0.02


def test_reservation_price_none_when_no_price_clears():
    assert reservation_price(0.02, 0.05, 10) is None


def test_reservation_uses_the_per_order_fee_ceiling_for_small_orders():
    # One contract at 50c pays a full 2c fee (ceil of 1.75c), so its cap is lower than at size.
    assert reservation_price(0.55, 0.0, 1) < reservation_price(0.55, 0.0, 1000) + 1e-9


def test_buy_limit_is_capped_at_the_reservation_price():
    sub = NeverFills()
    k = kernel(sub, quote(0.54, 0.55), max_attempts=1)
    k.execute(buy(100, 0.55, fair=0.60, min_edge=0.02))
    # Uncapped it would send ask + 2 ticks = 0.57; the edge only allows 0.56.
    assert sub.sent[0]["price"] == pytest.approx(0.56)


def test_entry_abandoned_when_live_ask_is_past_the_reservation_price():
    sub = NeverFills()
    # Ask ran 3c from the 55c signal: within the 10c slippage tolerance, but past the 56c reservation.
    rep = kernel(sub, quote(0.57, 0.58)).execute(buy(100, 0.55, fair=0.60, min_edge=0.02))
    assert sub.sent == []
    assert rep.accepted is False and rep.status == "edge_gone_net"
    assert rep.raw_json["reservation"] == pytest.approx(0.56)


def test_retry_escalation_never_crosses_the_cap():
    sub = NeverFills()
    kernel(sub, quote(0.50, 0.51)).execute(buy(100, 0.51, fair=0.60, min_edge=0.02))
    cap = reservation_price(0.60, 0.02, 100)
    assert len(sub.sent) == 3
    assert all(s["price"] <= cap + 1e-9 for s in sub.sent)


def test_filled_entry_reports_a_price_no_worse_than_the_cap():
    sub = FillsAtLimit()
    rep = kernel(sub, quote(0.54, 0.55)).execute(buy(100, 0.55, fair=0.60, min_edge=0.02))
    assert rep.fill_qty_contracts == 100
    assert rep.fill_price_dollars <= reservation_price(0.60, 0.02, 100) + 1e-9


def test_no_side_buy_is_capped_in_its_own_price_space():
    sub = NeverFills()
    # YES bid 0.62 => NO ask 0.38. NO fair 0.45, min_edge 0.02 => cap 0.41 (vs uncapped 0.40 + ... ).
    k = kernel(sub, quote(0.62, 0.63), entry_cross_ticks=5, max_attempts=1)
    k.execute(buy(100, 0.38, fair=0.45, min_edge=0.02, side="no"))
    cap = reservation_price(0.45, 0.02, 100)
    assert sub.sent[0]["side"] == "no"
    assert sub.sent[0]["price"] == pytest.approx(cap)  # 0.38 + 5 ticks = 0.43 capped down


def test_a_sell_is_never_capped_or_blocked_by_fair():
    sub = NeverFills()
    # fair is irrelevant to an exit: it must still cross down from the bid and escalate.
    kernel(sub, quote(0.20, 0.21), exit_cross_ticks=2).execute(
        buy(10, 0.20, fair=0.90, min_edge=0.40, action="sell"))
    assert [s["price"] for s in sub.sent] == pytest.approx([0.18, 0.17, 0.16])


def test_without_fair_behaviour_is_unchanged():
    sub = NeverFills()
    kernel(sub, quote(0.54, 0.55), max_attempts=1).execute(buy(100, 0.55))
    assert sub.sent[0]["price"] == pytest.approx(0.57)


def test_engine_entry_passes_fair_and_min_edge_to_the_kernel():
    from app.trading import engine

    seen = {}

    class K:
        def execute(self, intent):
            seen.update(intent.metadata)
            return None

    engine._live_trade(None, {"id": 1}, K(), "buy", "yes", TICKER, 5, 0.55, client_order_id_base="I1",
                       fair=0.61, min_edge=0.03)
    assert seen == {"client_order_id": "I1", "fair": 0.61, "min_edge": 0.03}
    seen.clear()
    engine._live_trade(None, {"id": 1}, K(), "sell", "yes", TICKER, 5, 0.55, client_order_id_base="I2")
    assert seen == {"client_order_id": "I2"}
