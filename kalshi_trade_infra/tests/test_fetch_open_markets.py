"""fetch_open_markets: /markets?status=open first, /events nested markets when that is empty.

On 2026-10-24 Kalshi's status=open market filter answered [] for KXBTC15M while its contract
traded, which froze the forward collector and blinded the btc15m live feed for hours."""
from datetime import datetime, timedelta, timezone

from data_pipeline import forward_collector
from data_pipeline.common import fetch_open_markets


def _getter(markets_pages, events_pages):
    calls = []

    def get(path, params):
        calls.append((path, dict(params)))
        pages = markets_pages if path == "/markets" else events_pages
        idx = sum(1 for p, _ in calls if p == path) - 1
        return pages[idx] if idx < len(pages) else {}
    get.calls = calls
    return get


def test_uses_markets_filter_when_it_answers():
    get = _getter([{"markets": [{"ticker": "A"}], "cursor": "c1"}, {"markets": [{"ticker": "B"}], "cursor": None}], [])
    assert [m["ticker"] for m in fetch_open_markets("KXBTCD", get=get)] == ["A", "B"]
    assert all(p == "/markets" for p, _ in get.calls)
    assert get.calls[1][1]["cursor"] == "c1"


def test_falls_back_to_events_when_filter_is_empty():
    events = {"events": [{"event_ticker": "KXBTC15M-26OCT241500", "series_ticker": "KXBTC15M", "markets": [
        {"ticker": "KXBTC15M-26OCT241500-00", "status": "active"},
        {"ticker": "KXBTC15M-26OCT241500-XX", "status": "initialized"},
    ]}], "cursor": None}
    get = _getter([{"markets": [], "cursor": None}], [events])
    got = fetch_open_markets("KXBTC15M", get=get)
    assert [m["ticker"] for m in got] == ["KXBTC15M-26OCT241500-00"]
    assert got[0]["event_ticker"] == "KXBTC15M-26OCT241500"
    assert get.calls[-1][1]["with_nested_markets"] == "true"


def test_collector_drops_tracked_event_once_closed(monkeypatch):
    now = datetime.now(timezone.utc)
    closed = {"ticker": "OLD-00", "event_ticker": "OLD", "close_time": (now - timedelta(minutes=1)).isoformat()}
    assert forward_collector._closed(closed)
    assert not forward_collector._closed({"close_time": (now + timedelta(minutes=5)).isoformat()})
