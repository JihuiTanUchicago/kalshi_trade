"""A Bitcoin contract's market page: /api/explore/spot says where stored Bitcoin spot is against the
contract's strike (fresh, stale or missing), which side it is on, and the time left, from the DB only."""
from datetime import datetime, timedelta, timezone

import pytest

from app import server
from app.services import btc_spot
from app.trading.markets import NEW_YORK
from app.web.routes import explore as explore_routes


class FakeConn:
    def cursor(self):
        return None  # every read goes through the patched repository functions


@pytest.fixture(autouse=True)
def fresh_caches():
    explore_routes._SPOT_CACHE.update(at=0.0, row=None)
    explore_routes._STRIKE_CACHE.clear()
    yield
    explore_routes._SPOT_CACHE.update(at=0.0, row=None)
    explore_routes._STRIKE_CACHE.clear()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _event(minutes_ahead=90):
    """An event code (26OCT2717) for an hour that closes about `minutes_ahead` from now, New York time."""
    at = (datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)).astimezone(NEW_YORK)
    return at.strftime("%y%b%d%H").upper(), at.replace(minute=0, second=0, microsecond=0)


def _stub(monkeypatch, spot=None, record=None, reads=None):
    def latest_spot(cur, product, since):
        if reads is not None:
            reads.append(("spot", product, since))
        if isinstance(spot, Exception):
            raise spot
        return spot

    def market_strike(cur, ticker):
        if reads is not None:
            reads.append(("strike", ticker))
        if isinstance(record, Exception):
            raise record
        return record
    monkeypatch.setattr(explore_routes.repo, "latest_spot", latest_spot)
    monkeypatch.setattr(explore_routes.repo, "market_strike", market_strike)


def _get(ticker):
    return server.explore_spot(server.Ctx(FakeConn(), {"id": 1}, (), {"ticker": ticker}, {}, None))


def test_fresh_spot_above_an_above_strike_read_from_the_ticker(monkeypatch):
    ev, close = _event(90)
    _stub(monkeypatch, spot={"at": _now() - timedelta(seconds=4), "price": 113420.0})
    d = _get("KXBTCD-%s-T112999.99" % ev)
    assert 4 <= d["spot"]["age_s"] <= 6 and d["spot"]["stale"] is False and d["spot"]["price"] == 113420.0
    assert d["strike"] == {"kind": "above", "value": 112999.99, "lo": None, "hi": None, "inclusive": False, "from": "ticker"}
    assert d["vs"] == {"side": "above", "diff": 420.01, "pct": 0.372, "yes": True}
    assert d["close_time"] == close.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert 0 < d["secs_left"] <= 90 * 60


def test_stale_spot_is_still_shown_and_marked_stale(monkeypatch):
    ev, _ = _event()
    _stub(monkeypatch, spot={"at": _now() - timedelta(minutes=7), "price": 112500.0})
    d = _get("KXBTCD-%s-T112999.99" % ev)
    assert d["spot"]["stale"] is True and 420 <= d["spot"]["age_s"] <= 422 and d["spot"]["price"] == 112500.0
    assert d["vs"]["side"] == "below" and d["vs"]["diff"] == -499.99 and d["vs"]["yes"] is False


def test_just_inside_two_minutes_is_not_stale(monkeypatch):
    ev, _ = _event()
    _stub(monkeypatch, spot={"at": _now() - timedelta(seconds=btc_spot.STALE_AFTER_S - 5), "price": 1.0})
    assert _get("KXBTCD-%s-T2" % ev)["spot"]["stale"] is False


def test_no_stored_spot_still_gives_the_strike_and_time_left(monkeypatch):
    ev, _ = _event()
    _stub(monkeypatch, spot=None)
    d = _get("KXBTCD-%s-T112999.99" % ev)
    assert d["spot"] is None and d["vs"] is None
    assert d["strike"]["value"] == 112999.99 and d["secs_left"] > 0


def test_the_spot_read_looks_back_one_day_for_btc_usd_and_is_shared_for_a_few_seconds(monkeypatch):
    ev, _ = _event()
    reads = []
    _stub(monkeypatch, spot={"at": _now(), "price": 100.0}, reads=reads)
    for t in ("KXBTCD-%s-T90" % ev, "KXBTCD-%s-T110" % ev, "KXBTCD-%s-T90" % ev):
        _get(t)
    spot_reads = [r for r in reads if r[0] == "spot"]
    assert len(spot_reads) == 1, "one spot read serves every reader inside SPOT_TTL_S"
    assert spot_reads[0][1] == "BTC-USD" and abs((_now() - spot_reads[0][2]) - timedelta(days=1)) < timedelta(seconds=5)
    assert [r for r in reads if r[0] == "strike"] == [("strike", "KXBTCD-%s-T90" % ev), ("strike", "KXBTCD-%s-T110" % ev)]
    explore_routes._SPOT_CACHE["at"] -= explore_routes.SPOT_TTL_S  # the cache ages out: read again
    _get("KXBTCD-%s-T90" % ev)
    assert len([r for r in reads if r[0] == "spot"]) == 2


def test_below_strike_from_the_collectors_record(monkeypatch):
    close = _now() + timedelta(minutes=30)
    _stub(monkeypatch, spot={"at": _now(), "price": 104000.0},
          record={"floor_strike": None, "cap_strike": 105000.0, "strike_type": "less", "close_time": close})
    d = _get("KXBTC-26OCT2717-T105000")
    assert d["strike"]["kind"] == "below" and d["strike"]["from"] == "record"
    assert d["vs"] == {"side": "below", "diff": -1000.0, "pct": -0.952, "yes": True}
    assert d["close_time"] == close.strftime("%Y-%m-%dT%H:%M:%SZ"), "the record's close wins over the ticker's"
    assert 29 * 60 <= d["secs_left"] <= 30 * 60


@pytest.mark.parametrize("price,side,diff,yes", [
    (113100.0, "inside", 0.0, True),
    (112900.0, "below", -100.0, False),     # $100 under the bucket's floor
    (113600.01, "above", 100.02, False),   # just past its cap
])
def test_range_bucket_from_the_record_says_where_spot_sits(monkeypatch, price, side, diff, yes):
    _stub(monkeypatch, spot={"at": _now(), "price": price},
          record={"floor_strike": 113000.0, "cap_strike": 113499.99, "strike_type": "between", "close_time": None})
    d = _get("KXBTC-26OCT2717-B113250")
    assert d["strike"] == {"kind": "range", "value": 113249.99, "lo": 113000.0, "hi": 113499.99, "inclusive": True, "from": "record"}
    assert (d["vs"]["side"], d["vs"]["diff"], d["vs"]["yes"]) == (side, diff, yes)
    if side == "inside":
        assert d["vs"]["to_lo"] == 100.0 and d["vs"]["to_hi"] == 399.99


def test_range_bucket_from_the_ticker_alone_measures_from_its_centre(monkeypatch):
    _stub(monkeypatch, spot={"at": _now(), "price": 113000.0}, record=None)
    d = _get("KXBTC-26OCT2717-B113250")
    assert d["strike"] == {"kind": "range", "value": 113250.0, "lo": None, "hi": None, "inclusive": True, "from": "ticker"}
    assert d["vs"] == {"side": "below", "diff": -250.0, "pct": -0.221, "yes": None}


def test_fifteen_minute_strike_comes_only_from_the_record(monkeypatch):
    t = "KXBTC15M-26OCT262345-45"
    _stub(monkeypatch, spot={"at": _now(), "price": 113000.0}, record=None)
    d = _get(t)
    assert d["strike"] is None and d["vs"] is None and d["spot"]["price"] == 113000.0
    explore_routes._STRIKE_CACHE.clear()
    _stub(monkeypatch, spot={"at": _now(), "price": 113000.0},
          record={"floor_strike": 113000.0, "cap_strike": None, "strike_type": "greater_or_equal", "close_time": None})
    explore_routes._SPOT_CACHE.update(at=0.0)
    d = _get(t)
    assert d["strike"]["kind"] == "above" and d["strike"]["inclusive"] is True
    assert d["vs"] == {"side": "at", "diff": 0.0, "pct": 0.0, "yes": True}, "at the target, greater-or-equal pays Yes"


@pytest.mark.parametrize("ticker,record,want", [
    ("KXBTCD-26OCT2717-T113499.99", None, ("above", 113499.99, "ticker")),
    ("KXBTCD-26OCT2700-T98000", None, ("above", 98000.0, "ticker")),
    ("KXBTC-26OCT2717-B113250", None, ("range", 113250.0, "ticker")),
    ("KXBTC-26OCT2717-T120000", None, ("line", 120000.0, "ticker")),   # an end contract: which way it pays isn't in the ticker
    ("KXBTC15M-26OCT262345-45", None, None),                            # the 15-minute target isn't in the ticker
    ("KXBTCD-26OCT2717", None, None),
    ("KXBTCD-26OCT2717-T", None, None),
    ("KXBTCD-26OCT2717-T1e5", None, None),
    ("KXBTCD-26OCT2717-T98000", {"strike_type": "greater", "floor_strike": None}, ("above", 98000.0, "ticker")),  # unusable record
    ("KXBTC-26OCT2717-T120000", {"strike_type": "greater", "floor_strike": "119999.99"}, ("above", 119999.99, "record")),
    ("KXBTC-26OCT2717-B113250", {"strike_type": "between", "floor_strike": 113500, "cap_strike": 113000}, ("range", 113250.0, "ticker")),
])
def test_strike_parsing(ticker, record, want):
    got = btc_spot.contract_strike(ticker, record)
    assert ((got["kind"], got["value"], got["from"]) if got else None) == want


@pytest.mark.parametrize("ticker", ["KXETHD-26OCT2717-T4000", "KXBTCX-26OCT2717-T1", "KXBTCD", "", "KXBTCD-"])
def test_a_non_bitcoin_contract_is_refused(monkeypatch, ticker):
    _stub(monkeypatch, spot={"at": _now(), "price": 1.0})
    with pytest.raises(server.ApiError) as err:
        _get(ticker)
    assert err.value.status == 400


def test_a_failed_spot_read_says_so_without_the_raw_error(monkeypatch, capsys):
    _stub(monkeypatch, spot=RuntimeError("(2013, 'Lost connection to MySQL server during query')"))
    with pytest.raises(server.ApiError) as err:
        _get("KXBTCD-26OCT2717-T98000")
    assert err.value.status == 503 and "Try again" in str(err.value) and "MySQL" not in str(err.value)
    assert "Lost connection" in capsys.readouterr().out


def test_a_failed_strike_read_falls_back_to_the_ticker(monkeypatch, capsys):
    _stub(monkeypatch, spot={"at": _now(), "price": 99000.0}, record=RuntimeError("lock wait timeout"))
    d = _get("KXBTCD-26OCT2717-T98000")
    assert d["strike"]["from"] == "ticker" and d["vs"]["side"] == "above"
    assert "lock wait timeout" in capsys.readouterr().out


def test_a_closed_contract_has_no_time_left(monkeypatch):
    _stub(monkeypatch, spot={"at": _now(), "price": 99000.0},
          record={"floor_strike": 98000.0, "strike_type": "greater", "close_time": _now() - timedelta(minutes=5)})
    assert _get("KXBTCD-26OCT2717-T98000")["secs_left"] == 0
