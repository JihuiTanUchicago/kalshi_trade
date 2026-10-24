"""scripts/prune_untraded_markets: which series get deleted, and that deletes stay batched and
resumable. No DB: classification is pure and the delete loop runs on a fake cursor."""
import time

from scripts import prune_untraded_markets as pr


def test_ticker_range_covers_exactly_one_series():
    lo, hi = pr.ticker_range("KXCPI")
    assert lo <= "KXCPI-26OCT-T3.1" < hi
    assert not (lo <= "KXCPIYOY-26OCT-T3" < hi)    # a longer series sharing the prefix
    assert not (lo <= "KXCPI" < hi)


def test_classify_keeps_traded_and_protected_and_unknown():
    ours = {"KXNBAGAME": None, "KXHIGHNY": "Climate and Weather", "KXBTCD": None, "KXCPI": None,
            "KXCOPPER": "Commodities", "KXPRES": None, "KXMVECROSSCATEGORY": None,
            "KXMVESPORTSMULTIGAME": "Sports", "KXOLD": None, "KXGOLDD": None}
    kalshi = {"KXNBAGAME": "Sports", "KXBTCD": "Crypto", "KXCPI": "Economics", "KXPRES": "Politics",
              "KXGOLDD": "Commodities"}
    protected = {"KXGOLDD": "open position"}
    untraded, unknown, saved = pr.classify(ours, kalshi, protected, include_unknown=False)
    assert dict(untraded) == {"KXCPI": "Economics", "KXCOPPER": "Commodities", "KXPRES": "Politics",
                              "KXMVECROSSCATEGORY": "parlay", "KXMVESPORTSMULTIGAME": "Sports"}
    assert unknown == ["KXOLD"] and saved == {"KXGOLDD": "open position"}
    untraded, unknown, _ = pr.classify(ours, kalshi, protected, include_unknown=True)
    assert "KXOLD" in dict(untraded) and unknown == []


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql, self.rowcount = rows, [], 0

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        n = min(self.rows, int(sql.rsplit("LIMIT", 1)[1]))
        self.rows -= n
        self.rowcount = n


def test_delete_series_batches_until_done(monkeypatch):
    monkeypatch.setattr(pr.time, "sleep", lambda s: None)
    cur = _Cur(12)
    n, finished = pr.delete_series(cur, "market_candles", "ticker", "KXCPI", 5, 0, float("inf"))
    assert (n, finished) == (12, True) and len(cur.sql) == 3
    sql, params = cur.sql[0]
    assert "ticker >= %s AND ticker < %s" in sql and params == ("KXCPI-", "KXCPI.")


def test_delete_series_stops_at_the_deadline():
    cur = _Cur(100)
    n, finished = pr.delete_series(cur, "markets", "series_ticker", "KXCPI", 5, 0, time.time() - 1)
    assert (n, finished) == (0, False) and cur.sql == []
