"""Kalshi Contract/Snapshot <-> domain Instrument/Quote (ARCHITECTURE.md step 7)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.adapters.kalshi import instruments as ki
from app.trading.markets import MARKETS, Contract, Snapshot
from trading_core.domain import InstrumentId, InstrumentKind

CLOSE = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)


def test_binary_round_trips_and_has_a_complement():
    c = Contract("KXBTCD-26OCT2517-T100000", 100_000.0, CLOSE, series="KXBTCD")
    yes = ki.binary(c)
    assert str(yes.id) == "kalshi:KXBTCD-26OCT2517-T100000.yes"
    assert yes.kind is InstrumentKind.BINARY and yes.expiry == CLOSE and yes.terms.strike == 100_000.0
    assert ki.contract(yes) == c and ki.contract(yes.complement()) == c
    assert ki.binary(c, "no") == yes.complement()


def test_event_contract_without_a_threshold_maps_strike_to_none_and_back():
    c = Contract("KXNFLGAME-26OCT25KCBUF-KC", 0.0, CLOSE, series="KXNFLGAME")
    inst = ki.binary(c)
    assert inst.terms.strike is None
    assert ki.contract(inst) == c


def test_market_supplies_underlying_and_series():
    m = next(m for m in MARKETS.values() if m.kind == "binary" and m.underlying)
    inst = ki.binary(Contract("X-1", 50.0, CLOSE), market=m)
    assert inst.underlying == m.underlying and inst.series == m.series
    assert ki.market_kind(m) is InstrumentKind.BINARY


def test_every_configured_market_kind_maps():
    for m in MARKETS.values():
        assert isinstance(ki.market_kind(m), InstrumentKind)


def test_quotes_derive_the_no_side_from_the_yes_book():
    snap = Snapshot(Contract("T", 1.0, CLOSE), 1_000, 0.41, 0.44, {"mid": 0.425})
    yes, no = ki.quotes(snap)
    assert (yes.bid, yes.ask, yes.ts) == (0.41, 0.44, 1000.0)
    assert no.instrument == InstrumentId("kalshi", "T", "no")
    assert no.bid == pytest.approx(0.56) and no.ask == pytest.approx(0.59)
    assert yes.features == no.features == {"mid": 0.425}


def test_no_yes_bid_means_no_no_ask():
    yes, no = ki.quotes(Snapshot(Contract("T", 1.0, CLOSE), 1, 0.0, 0.05, {}))
    assert yes.bid is None and no.ask is None and no.bid == pytest.approx(0.95)


def test_perp_and_guards():
    perp = ki.perpetual("KXBTCPERP")
    assert perp.kind is InstrumentKind.PERPETUAL and perp.multiplier == 0.0001 and perp.expiry is None
    with pytest.raises(ValueError):
        ki.contract(perp)
    with pytest.raises(ValueError):
        ki.binary(Contract("T", 1.0, CLOSE), "maybe")


def test_close_time_is_normalised_to_utc():
    est = timezone(timedelta(hours=-5))
    inst = ki.binary(Contract("T", 1.0, CLOSE.astimezone(est)))
    assert inst.expiry.tzinfo == timezone.utc and inst.expiry == CLOSE
