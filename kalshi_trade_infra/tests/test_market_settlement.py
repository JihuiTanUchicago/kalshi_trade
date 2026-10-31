"""How the engine reads Kalshi's settlement of a market, and what a held position is worth at it.

A voided market (no YES/NO result) used to read as "not settled yet" forever, so its position never
closed: paper cash stayed debited, and on the live book the row Kalshi had already zeroed read as a
reconcile mismatch that halts the user's live entries."""
import pytest

from app.trading import engine


@pytest.mark.parametrize("market, expected", [
    ({"result": "yes", "status": "determined"}, "yes"),
    ({"result": "NO", "status": "finalized"}, "no"),
    ({"result": "", "status": "closed"}, None),          # awaiting the source: try again
    ({"result": "", "status": "determined"}, None),
    ({"result": "", "status": "disputed"}, None),
    ({"result": "", "status": "active"}, None),
    ({}, None),                                          # unknown ticker / empty body
    ({"result": "", "status": "finalized"}, engine.VOID),
    ({"result": None, "status": "settled"}, engine.VOID),
    ({"result": "void", "status": "closed"}, engine.VOID),
    ({"result": "", "status": "voided"}, engine.VOID),
    ({"result": "", "status": "finalized", "settlement_value_dollars": "0.4200"}, 0.42),
    ({"result": "scalar", "status": "finalized", "settlement_value": 37}, 0.37),
    # A cancelled game exactly as Kalshi returns it (KXABAGAME-26OCT151200BCKCIB-CIB, 2026-10-13).
    ({"status": "finalized", "result": "scalar", "expiration_value": "", "settlement_value_dollars": "0.5000",
      "settlement_ts": "2026-10-13T03:18:29.598533Z"}, 0.5),
    # Cancelled but the price not yet set: wait, never guess.
    ({"status": "determined", "result": "scalar"}, None),
    # A YES/NO result wins over any price field.
    ({"result": "yes", "status": "finalized", "settlement_value_dollars": "0.5"}, "yes"),
    # A value outside [0, 1] is not a price: the market reads as voided, never as a payout of $3.
    ({"result": "", "status": "finalized", "settlement_value_dollars": "3"}, engine.VOID),
])
def test_market_settlement_reads_kalshis_market_object(market, expected):
    got = engine.market_settlement(market)
    if isinstance(expected, float):
        assert got == pytest.approx(expected)
    else:
        assert got == expected


def test_fetch_result_returns_void_for_a_finalized_market_with_no_result(monkeypatch):
    monkeypatch.setattr(engine, "api_get", lambda path: {"market": {"ticker": "X", "result": "", "status": "finalized"}})
    assert engine.fetch_result("X") == engine.VOID


def test_yes_and_no_pay_a_dollar_to_the_winning_side():
    assert engine.settlement_terms("yes", "yes", 10, 0.40, 0.20) == pytest.approx((10.0, 1.0, 10 - 4 - 0.2))
    assert engine.settlement_terms("yes", "no", 10, 0.60, 0.20) == pytest.approx((0.0, 0.0, -6 - 0.2))


def test_a_void_refunds_the_contract_cost_but_not_the_entry_fee():
    payout, exit_price, pnl = engine.settlement_terms(engine.VOID, "no", 10, 0.60, 0.15)
    assert (payout, exit_price) == pytest.approx((6.0, 0.60))
    assert pnl == pytest.approx(-0.15)


def test_a_price_settlement_pays_its_value_to_yes_and_the_rest_to_no():
    assert engine.settlement_terms(0.42, "yes", 10, 0.40, 0.0) == pytest.approx((4.2, 0.42, 0.2))
    assert engine.settlement_terms(0.42, "no", 10, 0.60, 0.0) == pytest.approx((5.8, 0.58, -0.2))


def test_settlement_labels_for_the_ledger():
    assert engine.settlement_label("yes") == "YES"
    assert engine.settlement_label(engine.VOID) == "VOID (refunded at cost)"
    assert engine.settlement_label(0.42) == "VOID at $0.42 a YES contract"
