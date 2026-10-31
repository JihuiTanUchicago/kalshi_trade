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


def test_dataset_result_reads_hist_markets_rows():
    from app.trading.settlement import dataset_result
    assert dataset_result({"result": "yes", "settle_value": None}) == "yes"
    assert dataset_result({"result": "void", "settle_value": "0.5000"}) == pytest.approx(0.5)
    assert dataset_result({"result": "void", "settle_value": None}) is None
    assert dataset_result({"result": "no"}) == "no"   # a row read before the column existed


def test_contract_payout_pays_each_side_its_share():
    from app.trading.settlement import contract_payout, yes_no_or_value
    assert contract_payout("yes", "yes") == 1.0 and contract_payout("yes", "no") == 0.0
    assert contract_payout(0.3, "yes") == pytest.approx(0.3) and contract_payout(0.3, "no") == pytest.approx(0.7)
    assert contract_payout(None, "yes") == 0.0   # missing result: a loss, as the backtest always booked
    assert yes_no_or_value(0.5) and yes_no_or_value("no") and not yes_no_or_value(None) \
        and not yes_no_or_value("void")


def test_history_stores_a_cancelled_market_at_its_price_and_skips_one_without():
    """market_history keeps a cancelled market (result 'void' with its price in settle_value) instead
    of dropping it, so backtests see the ~2% of sports markets Kalshi cancels."""
    from datetime import datetime, timezone
    from app import market_history
    from app.trading.markets import Market

    class Cur:
        rows = None

        def executemany(self, sql, rows):
            assert "settle_value" in sql
            Cur.rows = rows

    mk = next(m for m in market_history.MARKETS.values() if m.underlying is None)
    base = {"open_time": "2026-10-01T00:00:00Z", "close_time": "2026-10-01T03:00:00Z", "event_ticker": "E"}
    page = [dict(base, ticker="A", result="yes", status="finalized"),
            dict(base, ticker="B", result="scalar", status="finalized", settlement_value_dollars="0.5000"),
            dict(base, ticker="C", result="", status="finalized"),           # void, no price: nothing to pay
            dict(base, ticker="D", result="scalar", status="determined")]    # price not set yet
    import unittest.mock as um
    with um.patch.object(Market, "is_target_event", lambda self, ct: True):
        n = market_history._upsert_settled(Cur(), mk, page)
    assert n == 2
    by = {r[0]: r for r in Cur.rows}
    assert by["A"][6] == "yes" and by["A"][8] is None
    assert by["B"][6] == "void" and by["B"][8] == pytest.approx(0.5)


def test_resync_reads_every_collected_series_over_its_window_and_survives_one_failure(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app import market_history

    binaries = [m for m in market_history.MARKETS.values() if m.kind == "binary"][:3]

    class Cur:
        def execute(self, sql, params=()):
            assert sql.startswith("SELECT DISTINCT series_ticker FROM hist_markets")

        def fetchall(self):
            return [{"series_ticker": m.series} for m in binaries[:2]]

    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    calls = []

    def sync(cur, market, min_close, max_close=None):
        calls.append((market.series, min_close))
        if market is binaries[1]:
            raise RuntimeError("Kalshi 503")
        return 7

    monkeypatch.setattr(market_history, "sync_settled_markets", sync)
    stats = market_history.resync_settled(Cur(), now)
    assert stats == {binaries[0].series: 7}
    assert (binaries[0].series, now - timedelta(days=binaries[0].history_days)) in calls
    assert binaries[2].series not in {c[0] for c in calls}   # never collected: not started by a resync
