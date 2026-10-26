"""Research data loads must fit the agents worker.

On 2026-10-24 every research run on a 1-minute sports series was OOM-killed:
1.6M candle rows fetched as dicts of Decimals (~1GB), plus the built dataset,
plus a second copy for the narrowed reload. These pin the slimmer path:
candles stream as compact tuples, only the partition window's contracts are
kept, and a Snapshot carries no per-instance __dict__.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.trading import backtest
from app import repository as repo
from app.trading.markets import Contract, Snapshot, snapshot

SINCE = datetime(2026, 10, 1)
CLOSE = datetime(2026, 10, 30, 12, 0)
T0 = int(datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc).timestamp())

MARKETS_ROWS = [
    {"ticker": "A", "strike": 9.5, "close_time": CLOSE, "result": "yes"},
    {"ticker": "B", "strike": 9.5, "close_time": CLOSE, "result": "no"},
]
CANDLE_ROWS = [
    ("A", T0, Decimal("0.2000"), Decimal("0.3000")),
    ("B", T0, Decimal("0.4000"), Decimal("0.5000")),
    ("A", T0 + 60, Decimal("0.2100"), None),
]


class BufferedCur:
    """A test-style cursor: no pymysql connection, rows come back as dicts."""

    def __init__(self):
        self._last = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT ticker, strike, close_time, result FROM hist_markets"):
            self._last = [dict(r) for r in MARKETS_ROWS]
        elif s.startswith("SELECT c.ticker, c.end_period_ts"):
            self._last = [{"ticker": t, "end_period_ts": ts, "yes_bid_close": b, "yes_ask_close": a}
                          for t, ts, b, a in CANDLE_ROWS]
        else:
            self._last = []

    def fetchall(self):
        return self._last


class StreamingCur(BufferedCur):
    """Has a connection, so candles come through an unbuffered cursor as tuples."""

    def __init__(self):
        super().__init__()
        outer = self

        class SS:
            def execute(self, sql, params=()):
                outer.streamed_sql = sql

            def __iter__(self):
                return iter(CANDLE_ROWS)

            def close(self):
                outer.ss_closed = True

        class Conn:
            def cursor(self, cls=None):
                outer.cursor_class = cls
                return SS()

        self.connection = Conn()
        self.ss_closed = False


def test_candles_come_back_as_compact_float_tuples():
    h = repo.load_history(BufferedCur(), "KXMLBTOTAL", 1, SINCE, None)
    assert h["candles"][0] == ("A", T0, 0.2, 0.3)
    assert all(type(x) is tuple and len(x) == 4 for x in h["candles"])
    assert h["candles"][2][3] is None  # a missing ask stays None, not 0


def test_a_real_connection_streams_through_an_unbuffered_cursor():
    import pymysql

    cur = StreamingCur()
    h = repo.load_history(cur, "KXMLBTOTAL", 1, SINCE, None)
    assert cur.cursor_class is pymysql.cursors.SSCursor and cur.ss_closed
    assert h["candles"] == [("A", T0, 0.2, 0.3), ("B", T0, 0.4, 0.5), ("A", T0 + 60, 0.21, None)]


def test_a_ticker_window_drops_other_contracts_while_streaming():
    h = repo.load_history(StreamingCur(), "KXMLBTOTAL", 1, SINCE, None, tickers={"B"})
    assert [m["ticker"] for m in h["markets"]] == ["B"]
    assert h["candles"] == [("B", T0, 0.4, 0.5)]


def test_build_dataset_reads_tuples_and_dicts_the_same():
    from app.trading.markets import Market

    market = Market(key="t", series="KXMLBTOTAL", label="t", candle_minutes=1, history_days=30, underlying=None)
    tuples = repo.load_history(BufferedCur(), "KXMLBTOTAL", 1, SINCE, None)
    dicts = [{"ticker": t, "end_period_ts": ts, "yes_bid_close": b, "yes_ask_close": a}
             for t, ts, b, a in tuples["candles"]]
    a = backtest.build_dataset(market, tuples["markets"], tuples["candles"], [])
    b = backtest.build_dataset(market, tuples["markets"], dicts, [])

    def shape(ds):
        return [(ts, [(s.contract.ticker, s.yes_bid, s.yes_ask) for s in snaps]) for ts, snaps in ds.frames]

    assert shape(a) == shape(b) and a.frames


def test_snapshots_carry_no_per_instance_dict():
    ct = Contract("A", 9.5, datetime.now(timezone.utc) + timedelta(days=1), series="KXMLBTOTAL")
    s = snapshot({}, ct, T0, 0.2, 0.3)
    assert isinstance(s, Snapshot) and not hasattr(s, "__dict__")
    other = snapshot({}, ct, T0 + 60, 0.2, 0.3)
    assert s.features["hour_et"] is other.features["hour_et"]  # one shared float per hour


def test_deploy_applies_the_memory_caps_before_restarting():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "scripts" / "deploy_web.sh").read_text()
    assert "recursive-agents=8G" in script
    assert script.index("set-property") < script.index("systemctl restart ${SERVICES}\nsleep 5")


def test_a_huge_window_keeps_its_most_recent_whole_events():
    """An 18k-contract one-minute series can't load inside the step limit: the window keeps its
    latest whole events (every strike of a game together) up to the estimated candle budget."""
    from app.research import research_repository as rr

    def c(event, strike, open_ts, life_min):
        return {"ticker": "KXS-%s-%s" % (event, strike), "open_ts": open_ts, "close_ts": open_ts + life_min * 60}

    old = [c("G1", s, 0, 100) for s in (3, 7)]
    mid = [c("G2", s, 1000, 100) for s in (3, 7)]
    new = [c("G3", s, 2000, 100) for s in (3, 7)]
    kept = rr.cap_recent_events(old + mid + new, 1, 450)
    assert {k["ticker"].split("-")[1] for k in kept} == {"G2", "G3"}  # 400 rows fit, the 3rd game doesn't
    assert rr.cap_recent_events(new, 1, 10) == new  # never empty: the newest event always stays
    assert rr.cap_recent_events(old + new, 60, 450) == old + new  # hourly candles: everything fits


def test_a_window_load_is_bounded_to_its_contracts_close_times():
    """The candle query no longer scans the whole series: since/until wrap the kept contracts."""
    from app.research import research_repository as rr
    from app.trading.markets import Market

    seen = {}

    class Cur:
        def execute(self, sql, params=()):
            seen.setdefault("q", []).append((" ".join(sql.split()), params))
        def fetchall(self):
            q = seen["q"][-1][0]
            if q.startswith("SELECT ticker, open_time"):
                return [{"ticker": "X-E1-1", "open_time": datetime(2026, 10, 5), "close_time": datetime(2026, 10, 6), "result": "yes"},
                        {"ticker": "X-E2-1", "open_time": datetime(2026, 10, 20), "close_time": datetime(2026, 10, 21), "result": "no"}]
            return []

    m = Market(key="x", series="X", label="x", candle_minutes=60, history_days=30, underlying=None)
    lo = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
    hi = int(datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp())
    rr.partition_source_rows(Cur(), m, SINCE, lo, hi, 10_000)
    sql, params = next((q, p) for q, p in seen["q"] if q.startswith("SELECT ticker, strike"))
    assert "close_time <= %s" in sql and params == ("X", datetime(2026, 10, 5), datetime(2026, 10, 6))
