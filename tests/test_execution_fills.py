"""The engine must record what Kalshi filled, not what it asked for.

Every payload below is a verbatim Kalshi v2 create-order response captured
from the 2026-09-27 incident, in which four immediate-or-cancel buys crossed
nothing, were recorded as filled positions anyway, and were then "closed" by
sell orders that - having no position to close - opened real short positions.
Those settled worthless. The dashboard reported the phantom round-trips as
wins totalling +$15.36 while the account lost about $17.
"""
import pytest

from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import DummyExecutionKernel

# order 9daa8d10, 06:50 UTC: asked 18 @ 0.82, actually filled 18 @ 0.74
FILLED = {
    "average_fee_paid": "0.0134",
    "average_fill_price": "0.7400",
    "client_order_id": "9daa8d10-d041-4426-8092-11f29ac04e41",
    "fill_count": "18.00",
    "order_id": "01a0e1a0-f040-7928-beef-77a8a56945fa",
    "remaining_count": "0.00",
}
# order 71026b17, 07:01 UTC: asked 24 @ 0.41, crossed nothing.
# Note what is absent: no "average_fill_price", and no "order" object at all.
UNFILLED = {
    "client_order_id": "71026b17-a5ea-4893-94da-e28b7a728749",
    "fill_count": "0.00",
    "order_id": "01a0e1aa-fe78-7352-9ed7-998783254f84",
    "remaining_count": "0.00",
}


def kernel_for(resp):
    def submit(ticker, action, side, qty, price):
        return {"client_order_id": resp.get("client_order_id"), "body": {}, "resp": resp}

    return DummyExecutionKernel(submit)


def intent(qty, price, action="buy"):
    return TradeIntent(
        action=action,
        side="yes",
        ticker="KXBTC15M-26SEP270315-15",
        qty_contracts=qty,
        limit_price_dollars=price,
        model_name="binary_theory_edge",
        now_ts=None,
        metadata={},
    )


def test_unfilled_ioc_is_not_a_fill():
    rep = kernel_for(UNFILLED).execute(intent(24, 0.41))
    assert rep.fill_qty_contracts == 0
    assert rep.accepted is False
    assert rep.status == "unfilled"
    assert rep.fill_price_dollars == 0.0


def test_fill_price_is_kalshis_not_the_limit_we_asked_for():
    rep = kernel_for(FILLED).execute(intent(18, 0.82))
    assert rep.fill_qty_contracts == 18
    assert rep.accepted is True
    assert rep.status == "filled"
    assert rep.fill_price_dollars == pytest.approx(0.74)
    assert rep.fill_price_dollars != 0.82
    assert rep.fee_dollars == pytest.approx(0.0134 * 18)


def test_partial_fill_reports_only_what_filled():
    resp = dict(FILLED, fill_count="7.00", remaining_count="11.00")
    rep = kernel_for(resp).execute(intent(18, 0.82))
    assert rep.fill_qty_contracts == 7
    assert rep.status == "partially_filled"
    assert rep.accepted is True


def test_missing_fill_price_on_a_real_fill_falls_back_to_the_limit():
    """Only ever in the direction that cannot flatter the result."""
    resp = {k: v for k, v in FILLED.items() if k != "average_fill_price"}
    rep = kernel_for(resp).execute(intent(18, 0.82))
    assert rep.fill_qty_contracts == 18
    assert rep.fill_price_dollars == pytest.approx(0.82)


def test_v1_shaped_response_is_not_mistaken_for_a_fill():
    """The old nested shape the kernel used to read. v2 never sends it, and
    reading it is what made every order look accepted."""
    rep = kernel_for({"order": {"status": "resting", "order_id": "x"}}).execute(intent(24, 0.41))
    assert rep.fill_qty_contracts == 0
    assert rep.accepted is False


def test_empty_response_is_not_a_fill():
    for resp in ({}, {"fill_count": None}, {"fill_count": "bogus"}):
        rep = kernel_for(resp).execute(intent(24, 0.41))
        assert rep.fill_qty_contracts == 0, resp
        assert rep.accepted is False, resp
