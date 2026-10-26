"""Fee schedules behind trading_core.ports.FeeModel (ARCHITECTURE.md step 3)."""
from datetime import datetime, timezone

import pytest

from app.adapters.kalshi.fees import KalshiBinaryFees, kalshi_perps_fees
from app.adapters.tao.fees import TaoSwapFees
from data_pipeline import kalshi_fees
from trading_core.domain import BinaryTerms, Instrument, InstrumentId, InstrumentKind, PerpetualTerms
from trading_core.ports import FeeModel, FeesByVenue, NotionalRateFees, ZeroFees

EXPIRY = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)
BINARY = Instrument(InstrumentId("kalshi", "KXBTCD-26OCT2517-T100000", "yes"), InstrumentKind.BINARY,
                    terms=BinaryTerms(expiry=EXPIRY))
PERP = Instrument(InstrumentId("kalshi", "KXBTCPERP"), InstrumentKind.PERPETUAL, multiplier=0.0001,
                  terms=PerpetualTerms())
ALPHA = Instrument(InstrumentId("taostats", "SN19-ALPHA"), InstrumentKind.SPOT, quote_currency="TAO")
STOCK = Instrument(InstrumentId("alpaca", "AAPL"), InstrumentKind.SPOT, lot_size=0.0001)


@pytest.mark.parametrize("qty,price", [(1, 0.50), (100, 0.50), (7, 0.03), (250, 0.91), (3, 0.123)])
def test_kalshi_binary_fees_are_the_official_schedule(qty, price):
    fees = KalshiBinaryFees()
    assert fees.fee(BINARY, qty, price) == kalshi_fees.taker_fee_dollars(qty, price)
    assert fees.fee(BINARY, -qty, price) == kalshi_fees.taker_fee_dollars(qty, price)  # a sell pays too
    assert fees.fee(BINARY, qty, price, maker=True) == kalshi_fees.maker_fee_dollars(qty, price)


def test_kalshi_binary_fee_goldens_and_guards():
    fees = KalshiBinaryFees()
    assert fees.fee(BINARY, 100, 0.50) == 1.75          # exact cent, not ceiled to 1.76
    assert fees.fee(BINARY, 1, 0.50) == 0.02            # 0.0175 ceils to 2c per order
    assert fees.fee(BINARY, 100, 0.50, maker=True) == 0.44
    assert fees.fee(BINARY, 0, 0.50) == 0.0
    with pytest.raises(ValueError):
        fees.fee(BINARY, 1.5, 0.50)
    with pytest.raises(ValueError):
        fees.fee(PERP, 1, 0.50)


def test_kalshi_perps_fees_use_the_exchange_tiers_and_refuse_unknown_tickers():
    fees = kalshi_perps_fees({"taker_fee_rates": {"KXBTCPERP": "0.0005"}, "maker_fee_rates": {"KXBTCPERP": "-0.0001"}})
    # 10,000 contracts x 0.0001 BTC = 1 BTC at $100k: notional $100k
    assert fees.fee(PERP, 10_000, 100_000.0) == pytest.approx(50.0)
    assert fees.fee(PERP, 10_000, 100_000.0, maker=True) == pytest.approx(-10.0)  # rebate
    other = Instrument(InstrumentId("kalshi", "KXETHPERP"), InstrumentKind.PERPETUAL, terms=PerpetualTerms())
    with pytest.raises(KeyError):
        fees.fee(other, 1, 1.0)


def test_tao_swap_fee_is_the_chain_cost_on_notional():
    from app.adapters.tao import tao_fees
    assert TaoSwapFees().fee(ALPHA, -40, 0.25) == pytest.approx(tao_fees.swap_fee(10.0))


def test_one_router_prices_every_venue_and_refuses_an_unknown_one():
    fees = FeesByVenue({"kalshi": KalshiBinaryFees(), "taostats": TaoSwapFees(),
                        "alpaca": NotionalRateFees(0.0), "paper": ZeroFees()})
    for model in (fees, KalshiBinaryFees(), TaoSwapFees(), NotionalRateFees(0.001), ZeroFees()):
        assert isinstance(model, FeeModel)
    assert fees.fee(BINARY, 100, 0.50) == 1.75
    assert fees.fee(STOCK, 3, 200.0) == 0.0
    assert NotionalRateFees(0.001, taker_by_symbol={"AAPL": 0.002}).fee(STOCK, 3, 200.0) == pytest.approx(1.2)
    with pytest.raises(KeyError, match="polymarket"):
        fees.fee(Instrument(InstrumentId("polymarket", "0xabc", "yes"), InstrumentKind.BINARY,
                            terms=BinaryTerms(expiry=EXPIRY)), 1, 0.5)
