"""Research-load request budget: an external fair-value book read from the tick store may probe at
most a couple of keys per day of the window, never one per hour. A Polymarket loader that paid an S3
404 for every missing archive hour (~4,500 per 90-day load, 275s) timed out btc15m research loads
(runs 2858, 2879, 2874); any new source wired into backtest.forecast_book is held to the same bar."""
from datetime import datetime, timedelta, timezone

import pytest

from app.trading import backtest
from app.adapters.data import options_fair
from app.trading.markets import MARKETS
from data_pipeline import tick_store

DAYS = 90
PER_DAY = 2   # a day file plus one fallback is fine; an hourly fallback is 25+ per day


class CountingStore(tick_store.TickStore):
    fetched: list = []

    def _fetch(self, key):
        CountingStore.fetched.append(key)
        return super()._fetch(key)


def _markets():
    """One market per tick-store-backed series that forecast_book reads."""
    seen, out = set(), []
    for m in MARKETS.values():
        if m.series in options_fair.SERIES and m.series not in seen:
            seen.add(m.series)
            out.append(m)
    return out


@pytest.mark.parametrize("market", _markets(), ids=lambda m: m.key)
def test_an_external_book_load_probes_at_most_a_few_keys_per_day(market, tmp_path, monkeypatch):
    archived_hour = tmp_path / "ticks/v1/polymarket_top/date=2026-10-25/hour=05"
    archived_hour.mkdir(parents=True)   # one archived day, so the archive fallback path runs too
    monkeypatch.setattr(tick_store, "TickStore", lambda *a, **k: CountingStore(local_root=str(tmp_path)))
    CountingStore.fetched = []
    since = datetime(2026, 10, 25, tzinfo=timezone.utc) - timedelta(days=DAYS)
    backtest.forecast_book(market, since.replace(tzinfo=None))
    per_day = len(CountingStore.fetched) / max(1, (datetime.now(timezone.utc) - since).days)
    assert per_day <= PER_DAY, "%.1f store probes per day of window, e.g. %s" % (per_day, CountingStore.fetched[:3])
