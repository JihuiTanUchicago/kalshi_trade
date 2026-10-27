"""A Bitcoin contract's market page: /api/explore/spot says where stored Bitcoin spot is against the
contract's strike (fresh, stale or missing), which side it is on, and the time left, from the DB only;
Explore's list and hot rail say the same distance per row from one shared spot read."""
import pathlib
import re
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


# Explore's list and the hot rail: how far stored spot is from each Bitcoin contract's strike, from one
# shared spot read and the tickers alone (no per-row read, no exchange or Kalshi call).
def _feed(*tickers, hot=False):
    return {"at": "2026-10-27T10:55:00Z", "total": len(tickers), "shown": len(tickers),
            "markets": [{"t": t, "s": t.split("-")[0], "v24": str(100 - i), **({"h": [0.4, 0.5]} if hot else {})}
                        for i, t in enumerate(tickers)]}


def _list(monkeypatch, feed, **query):
    monkeypatch.setattr(explore_routes, "_explore_feed", lambda: feed)
    return server.explore_list(server.Ctx(FakeConn(), {"id": 1}, (), query, {}, None))


LADDER = ("KXBTCD-26OCT2717-T112999.99", "KXBTCD-26OCT2717-T114000", "KXBTC-26OCT2717-B113250", "KXBTC-26OCT2717-B113750",
          "KXBTC-26OCT2717-B114250", "KXBTC-26OCT2717-T120000", "KXBTC15M-26OCT262345-45", "KXNBAGAME-26OCT26MINDEN-MIN")


def test_the_list_says_how_far_fresh_spot_is_from_each_strike_from_one_read(monkeypatch):
    reads = []
    _stub(monkeypatch, spot={"at": _now() - timedelta(seconds=4), "price": 113420.0}, reads=reads)
    d = _list(monkeypatch, _feed(*LADDER))
    vs = {m["t"]: m.get("vs") for m in d["markets"]}
    assert vs["KXBTCD-26OCT2717-T112999.99"] == {"side": "above", "diff": 420.01, "pct": 0.372}
    assert vs["KXBTCD-26OCT2717-T114000"] == {"side": "below", "diff": -580.0, "pct": -0.509}
    # The ladder's own tickers give its $500 width: B113250 is $113,000 to $113,499.99, spot sits in it.
    assert vs["KXBTC-26OCT2717-B113250"] == {"side": "inside", "diff": 0.0, "pct": 0.0}
    assert vs["KXBTC-26OCT2717-B113750"] == {"side": "below", "diff": -80.0, "pct": -0.07}  # under its $113,500 floor
    assert vs["KXBTC-26OCT2717-B114250"]["diff"] == -580.0
    assert vs["KXBTC-26OCT2717-T120000"]["side"] == "below"   # an end contract: the distance to its line
    assert vs["KXBTC15M-26OCT262345-45"] is None, "a 15-minute window's start price isn't in its ticker"
    assert vs["KXNBAGAME-26OCT26MINDEN-MIN"] is None
    assert d["spot"]["price"] == 113420.0 and d["spot"]["stale"] is False and 4 <= d["spot"]["age_s"] <= 6
    assert [r[0] for r in reads] == ["spot"], "one spot read for the page, never a strike read per row"
    _list(monkeypatch, _feed(*LADDER), page="0")
    assert [r[0] for r in reads] == ["spot"], "a second list inside SPOT_TTL_S shares it"
    assert [m["t"] for m in d["markets"]] == list(LADDER), "the list keeps its order"


@pytest.mark.parametrize("state", ["stale", "missing"])
def test_a_stale_or_missing_spot_gives_no_distances_and_says_its_age(monkeypatch, state):
    _stub(monkeypatch, spot={"at": _now() - timedelta(minutes=7), "price": 112500.0} if state == "stale" else None)
    d = _list(monkeypatch, _feed(*LADDER))
    assert all("vs" not in m for m in d["markets"])
    if state == "stale":
        assert d["spot"]["stale"] is True and 420 <= d["spot"]["age_s"] <= 422
    else:
        assert d["spot"] is None


def test_a_failed_spot_read_gives_no_distances_and_no_raw_error(monkeypatch, capsys):
    _stub(monkeypatch, spot=RuntimeError("(2013, 'Lost connection to MySQL server during query')"))
    d = _list(monkeypatch, _feed(*LADDER))
    assert d["spot"] == {"failed": True} and all("vs" not in m for m in d["markets"])
    assert "MySQL" not in repr(d) and "Lost connection" in capsys.readouterr().out
    assert d["markets"][0]["ct"] == "2026-10-27T21:00:00Z", "the rest of the list is untouched"


def test_a_list_without_bitcoin_strikes_reads_nothing_and_is_untouched(monkeypatch):
    reads = []
    _stub(monkeypatch, spot={"at": _now(), "price": 113420.0}, reads=reads)
    d = _list(monkeypatch, _feed("KXNBAGAME-26OCT26MINDEN-MIN", "KXETHD-26OCT2717-T4000", "KXBTC15M-26OCT262345-45"))
    assert "spot" not in d and all("vs" not in m for m in d["markets"]) and reads == []
    assert set(d["markets"][0]) == {"t", "s", "v24", "ct"}
    # A search that leaves only other markets reads nothing either, though the feed holds Bitcoin.
    _list(monkeypatch, _feed("KXNBAGAME-26OCT26MINDEN-MIN", *LADDER[:2]), q="minden")
    assert reads == []


def test_a_bucket_alone_in_the_feed_gets_no_distance_and_a_gap_in_its_ladder_doesnt_widen_it(monkeypatch):
    _stub(monkeypatch, spot={"at": _now(), "price": 113420.0})
    assert "vs" not in _list(monkeypatch, _feed("KXBTC-26OCT2717-B113250"))["markets"][0], "its edges aren't known"
    # B113750 dropped out of the feed: the gaps are $1,000 and $500, so the ladder is still $500 wide.
    d = _list(monkeypatch, _feed("KXBTC-26OCT2717-B113250", "KXBTC-26OCT2717-B114250", "KXBTC-26OCT2717-B114750"))
    assert d["markets"][1]["vs"] == {"side": "below", "diff": -580.0, "pct": -0.509}
    # A search for one bucket still measures it against its ladder's width from the whole feed.
    d = _list(monkeypatch, _feed("KXBTC-26OCT2717-B113250", "KXBTC-26OCT2717-B113750"), q="B113250")
    assert [m["vs"]["side"] for m in d["markets"]] == ["inside"]


def test_bucket_width_and_edges():
    assert btc_spot.bucket_width([113250, 113750, 114250]) == 500.0
    assert btc_spot.bucket_width([113250, 114250, 114750, 114750]) == 500.0
    assert btc_spot.bucket_width([113250]) is None and btc_spot.bucket_width([]) is None
    k = btc_spot.contract_strike("KXBTC-26OCT2717-B113250")
    assert btc_spot.with_bucket_edges(k, 500.0) == {**k, "lo": 113000.0, "hi": 113499.99}
    assert btc_spot.with_bucket_edges(k, None) is k
    above = btc_spot.contract_strike("KXBTCD-26OCT2717-T98000")
    assert btc_spot.with_bucket_edges(above, 500.0) is above


def test_the_hot_rail_says_when_each_market_closes_and_how_far_spot_is_from_a_strike(monkeypatch):
    reads = []
    _stub(monkeypatch, spot={"at": _now(), "price": 113420.0}, reads=reads)
    feed = _feed("KXBTCD-26OCT2717-T112999.99", "KXNBAGAME-26OCT26MINDEN-MIN", "KXHIGHNY-26OCT27-B60", hot=True)
    feed["markets"].append({"t": "KXBTCD-26OCT2717-T1", "v24": "1"})  # no price trace: not on the rail
    monkeypatch.setattr(explore_routes, "_explore_feed", lambda: feed)
    d = server.explore_hot(server.Ctx(FakeConn(), {"id": 1}, (), {}, {}, None))
    assert [m["t"] for m in d["markets"]] == ["KXBTCD-26OCT2717-T112999.99", "KXNBAGAME-26OCT26MINDEN-MIN", "KXHIGHNY-26OCT27-B60"]
    assert [m["ct"] for m in d["markets"]] == ["2026-10-27T21:00:00Z", None, None]
    assert d["markets"][0]["vs"]["diff"] == 420.01 and "vs" not in d["markets"][1] and d["spot"]["price"] == 113420.0
    assert d["markets"][0]["h"] == [0.4, 0.5] and "ct" not in feed["markets"][0], "the cached feed itself is never written to"
    assert [r[0] for r in reads] == ["spot"]


# A 15-minute window's row: its market page reads "Target Price: $113,512.08" from the contract's own name when no
# strike is stored, while Explore's distance stayed empty for the same row. The row now measures from that target
# too, and says it came from the title, so the list and the page show the same figure from the same place.
M15 = "KXBTC15M-26OCT262345-45"


def _m15_feed(**over):
    feed = _feed(M15, "KXBTCD-26OCT2717-T112999.99", "KXNBAGAME-26OCT26MINDEN-MIN")
    feed["markets"][0].update({"ti": "BTC price up in next 15 mins?", "su": "Target Price: $113,512.08", **over})
    return feed


def test_a_fifteen_minute_row_measures_from_the_target_price_in_its_title(monkeypatch):
    reads = []
    _stub(monkeypatch, spot={"at": _now(), "price": 113420.0}, reads=reads)
    d = _list(monkeypatch, _m15_feed())
    vs = {m["t"]: m.get("vs") for m in d["markets"]}
    # Spot minus the target, as the market page's own figure (−$92.08, 0.08% below the strike).
    assert vs[M15] == {"side": "below", "diff": -92.08, "pct": -0.081, "from": "title"}
    assert vs["KXBTCD-26OCT2717-T112999.99"] == {"side": "above", "diff": 420.01, "pct": 0.372}, "a ticker strike names no source"
    assert vs["KXNBAGAME-26OCT26MINDEN-MIN"] is None
    assert [r[0] for r in reads] == ["spot"], "still one spot read, no strike read per row"
    # A page of only that window reads spot for it, where before it read nothing.
    reads.clear()
    explore_routes._SPOT_CACHE.update(at=0.0)
    only = _m15_feed()
    only["markets"] = only["markets"][:1]
    d = _list(monkeypatch, only)
    assert d["markets"][0]["vs"]["from"] == "title" and d["spot"]["price"] == 113420.0 and [r[0] for r in reads] == ["spot"]
    # The hot rail reads the same rows the same way.
    feed = _m15_feed()
    for m in feed["markets"]:
        m["h"] = [0.4, 0.5]
    monkeypatch.setattr(explore_routes, "_explore_feed", lambda: feed)
    hot = server.explore_hot(server.Ctx(FakeConn(), {"id": 1}, (), {}, {}, None))
    assert hot["markets"][0]["vs"] == {"side": "below", "diff": -92.08, "pct": -0.081, "from": "title"}


@pytest.mark.parametrize("over", [{"su": ""}, {"su": "Up or down"}, {"su": "Target Price: $0"}, {"su": "Target Price: TBD"}])
def test_a_fifteen_minute_row_without_a_target_in_its_name_still_has_no_distance(monkeypatch, over):
    _stub(monkeypatch, spot={"at": _now(), "price": 113420.0})
    assert _list(monkeypatch, _m15_feed(**over))["markets"][0].get("vs") is None


def test_title_strike_reads_the_target_as_the_market_page_does():
    assert btc_spot.title_strike("Target Price: $113,512.08", "BTC price up in next 15 mins?") == {
        "kind": "line", "value": 113512.08, "lo": None, "hi": None, "inclusive": False, "from": "title"}
    assert btc_spot.title_strike("", "BTC up? target price $98000")["value"] == 98000.0  # the title, when the subtitle has none
    assert btc_spot.title_strike(None, "") is None and btc_spot.title_strike("Target Price: $0.00") is None
    # The very pattern the market page reads with, in both themes, so a row and its page can't disagree.
    for bundle in ("app.js", "app.meridian.js"):
        src = (pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / bundle).read_text()
        js = re.search(r"const TARGET_IN = /(.+)/i;", src).group(1)
        assert js == btc_spot._TARGET_IN.pattern and btc_spot._TARGET_IN.flags & re.I, bundle
