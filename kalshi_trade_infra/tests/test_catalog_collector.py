"""catalog_collector.refresh_series_meta: enrich kalshi_series with category + frequency from the
bulk /series endpoint (what drives the catalog-market generation in app/markets.py)."""
from data_pipeline import catalog_collector as cc


class _Cur:
    def __init__(self, existing_tickers):
        self._existing = existing_tickers
        self.updates = None

    def execute(self, sql, params=()):
        assert "SELECT series_ticker FROM kalshi_series" in " ".join(sql.split())
        self._rows = [{"series_ticker": t} for t in self._existing]

    def fetchall(self):
        return self._rows

    def executemany(self, sql, rows):
        assert "UPDATE kalshi_series SET category=%s, frequency=%s" in " ".join(sql.split())
        self.updates = list(rows)


def test_refresh_series_meta_updates_only_tracked_series(monkeypatch):
    payload = {"series": [
        {"ticker": "KXHIGHNY", "category": "Climate and Weather", "frequency": "daily"},
        {"ticker": "KXNBAGAME", "category": "Sports", "frequency": "custom"},
        {"ticker": "KXNOTTRACKED", "category": "Economics", "frequency": "weekly"},
    ]}
    monkeypatch.setattr(cc, "api_get", lambda *a, **k: payload)
    cur = _Cur(existing_tickers=["KXHIGHNY", "KXNBAGAME"])   # KXNOTTRACKED absent from our catalog
    n = cc.refresh_series_meta(cur)
    assert n == 2
    # (category, frequency, series_ticker) per row; only the two tracked series updated.
    got = {r[2]: (r[0], r[1]) for r in cur.updates}
    assert got == {"KXHIGHNY": ("Climate and Weather", "daily"), "KXNBAGAME": ("Sports", "custom")}


def test_refresh_series_meta_survives_fetch_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("kalshi down")
    monkeypatch.setattr(cc, "api_get", _boom)
    assert cc.refresh_series_meta(_Cur([])) == 0   # contained: never raises, returns 0
