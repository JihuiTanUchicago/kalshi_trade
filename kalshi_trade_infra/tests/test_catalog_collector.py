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
        {"ticker": "KXHIGHNY", "category": "Climate and Weather", "frequency": "daily",
         "title": "Highest temperature in NYC"},
        {"ticker": "KXNBAGAME", "category": "Sports", "frequency": "custom"},
        {"ticker": "KXNOTTRACKED", "category": "Economics", "frequency": "weekly"},
    ]}
    monkeypatch.setattr(cc, "api_get", lambda *a, **k: payload)
    cur = _Cur(existing_tickers=["KXHIGHNY", "KXNBAGAME"])   # KXNOTTRACKED absent from our catalog
    n = cc.refresh_series_meta(cur)
    assert n == 2
    # (category, frequency, title, series_ticker) per row; only the two tracked series updated.
    # The series title replaces the market title refresh_series stored; a missing one keeps it.
    got = {r[3]: (r[0], r[1], r[2]) for r in cur.updates}
    assert got == {"KXHIGHNY": ("Climate and Weather", "daily", "Highest temperature in NYC"),
                   "KXNBAGAME": ("Sports", "custom", "")}


def test_refresh_series_meta_survives_fetch_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("kalshi down")
    monkeypatch.setattr(cc, "api_get", _boom)
    assert cc.refresh_series_meta(_Cur([])) == 0   # contained: never raises, returns 0


# -- refresh_once / refresh_series: skip the parlay flood, count open markets from the fetch ------


class _DB:
    """kalshi_series + an indexed COUNT over markets, enough for refresh_series."""

    def __init__(self, series=None, market_counts=None):
        self.series = dict(series or {})          # ticker -> {"open": n, "total": n, "updated_at": dt}
        self.market_counts = dict(market_counts or {})
        self.sql = []
        self._rows = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self.sql.append(s)
        if s.startswith("SELECT series_ticker, COUNT(*) AS n FROM markets WHERE series_ticker IN"):
            assert "GROUP BY series_ticker" in s
            self._rows = [{"series_ticker": t, "n": self.market_counts[t]} for t in params if t in self.market_counts]
        elif s.startswith("UPDATE kalshi_series SET open_markets=0"):
            now = params[0]
            for row in self.series.values():
                if row["updated_at"] < params[1] and row["open"] != 0:
                    row["open"], row["updated_at"] = 0, now
        elif s.startswith("SELECT COUNT(*) AS n FROM kalshi_series"):
            self._rows = [{"n": len(self.series)}]
        else:
            raise AssertionError("unexpected SQL: " + s[:80])

    def executemany(self, sql, rows):
        assert "INSERT INTO kalshi_series" in sql
        for t, title, n_open, total, now in rows:
            self.series[t] = {"open": n_open, "total": total, "updated_at": now, "title": title}

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0]


def _old(open_n):
    from datetime import datetime
    return {"open": open_n, "total": open_n, "updated_at": datetime(2026, 10, 23)}


def test_series_counts_come_from_the_fetch_and_unseen_series_drop_to_zero():
    db = _DB(series={"KXMVECROSSCATEGORY": _old(8354740), "KXNBAGAME": _old(5)}, market_counts={"KXNBAGAME": 40})
    n = cc.refresh_series(db, {"KXNBAGAME": {"open": 3, "title": "NBA game"}}, complete=True)
    assert n == 2
    assert db.series["KXNBAGAME"]["open"] == 3 and db.series["KXNBAGAME"]["total"] == 40
    assert db.series["KXMVECROSSCATEGORY"]["open"] == 0
    assert not any("GROUP BY m.series_ticker" in s for s in db.sql)  # no full-table aggregate


def test_an_incomplete_fetch_never_zeroes_the_catalog():
    db = _DB(series={"KXHIGHNY": _old(4)})
    cc.refresh_series(db, {"KXNBAGAME": {"open": 3, "title": "NBA"}}, complete=False)
    assert db.series["KXHIGHNY"]["open"] == 4


def test_refresh_asks_kalshi_to_exclude_parlays(monkeypatch):
    calls, upserts = [], []
    pages = [
        {"markets": [{"ticker": "KXNBAGAME-26OCT24-A", "event_ticker": "KXNBAGAME-26OCT24", "status": "active", "title": "A"}],
         "cursor": "c1"},
        {"markets": [{"ticker": "KXHIGHNY-26OCT24-B1", "event_ticker": "KXHIGHNY-26OCT24", "status": "active", "title": "B"}],
         "cursor": ""},
    ]

    def api(path, params=None):
        if path == "/series":
            return {"series": []}
        calls.append(dict(params))
        return pages[len(calls) - 1]

    db = _DB(series={"KXMVECROSSCATEGORY": _old(9)})

    class Conn:
        def cursor(self):
            return db

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(cc, "api_get", api)
    monkeypatch.setattr(cc, "get_db_conn", lambda: Conn())
    monkeypatch.setattr(cc, "insert_market_upserts", lambda cur, batch: upserts.extend(batch))
    monkeypatch.setattr(cc, "PAGE_SLEEP", 0)
    monkeypatch.setattr(cc, "refresh_series_meta", lambda cur: 0)
    out = cc.refresh_once()
    assert all(c.get("mve_filter") == "exclude" for c in calls) and len(calls) == 2
    assert out["markets"] == 2 and len(upserts) == 2
    assert db.series["KXNBAGAME"]["open"] == 1 and db.series["KXMVECROSSCATEGORY"]["open"] == 0
