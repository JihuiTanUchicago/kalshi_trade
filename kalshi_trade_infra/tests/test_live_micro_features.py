"""Live snapshots carry the same order-book (micro) features research joins onto every frame.

Research reads model_features_1m into each contract snapshot; before this the engine built live
snapshots with no micro at all, so any strategy filtering on one (spec._passes needs the feature
present) passed research and then never traded on paper or live.
"""
from datetime import datetime, timezone

from app.trading import engine
from app import repository as repo
from app.trading.markets import MICRO_FEATURES

from tests.test_cross_market import T0, _sources


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql, self.params = rows, None, None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.rows


def _row(ticker, minute_ts, imb):
    return {"market_ticker": ticker, "snapshot_minute_utc": datetime.fromtimestamp(minute_ts, tz=timezone.utc)
            .replace(tzinfo=None), "ob_imbalance": imb, "yes_bid_size": 10, "trades_60s": None}


def test_latest_micro_keeps_the_newest_fresh_row_per_ticker():
    now = 1_800_000_000
    cur = _Cur([_row("A", now - 120, 0.1), _row("A", now - 60, 0.3), _row("B", now - 60, -0.2)])
    out = repo.latest_micro(cur, ["B", "A", "A"], now)
    assert out == {"A": {"ob_imbalance": 0.3, "yes_bid_size": 10}, "B": {"ob_imbalance": -0.2, "yes_bid_size": 10}}
    # As-of and freshness are enforced in SQL: rows at or before now, no older than 120s.
    assert "snapshot_minute_utc <= %s AND snapshot_minute_utc >= %s" in cur.sql
    assert cur.params[:2] == ("A", "B")
    assert (cur.params[2] - cur.params[3]).total_seconds() == 120
    # Every MICRO_FEATURES column is read under its research name.
    for name, (col, _d) in MICRO_FEATURES.items():
        assert "%s AS %s" % (col, name) in cur.sql


def test_latest_micro_with_no_tickers_reads_nothing():
    cur = _Cur([])
    assert repo.latest_micro(cur, [], 1_800_000_000) == {} and cur.sql is None


def test_live_frame_snapshots_carry_micro_features():
    now_ts = T0 + 7200
    src = _sources(now_ts)
    seen = {}

    def micro(tickers, ts):
        seen["args"] = (sorted(tickers), ts)
        return {"BTCD_1": {"ob_imbalance": 0.4, "trades_60s": 12}}

    src.micro = micro
    snaps, _ = engine._cross_market_frame(["btc_daily", "eth_daily"], src, now_ts)
    by = {s.contract.ticker: s for s in snaps}
    assert by["BTCD_1"].features["ob_imbalance"] == 0.4 and by["BTCD_1"].features["trades_60s"] == 12.0
    assert "ob_imbalance" not in by["ETHD_1"].features, "no fresh row -> feature absent, as in research"
    assert seen["args"][1] == now_ts


def test_a_micro_read_failure_never_blocks_the_frame():
    now_ts = T0 + 7200
    src = _sources(now_ts)

    def boom(tickers, ts):
        raise RuntimeError("db down")

    src.micro = boom
    snaps, _ = engine._cross_market_frame(["btc_daily", "eth_daily"], src, now_ts)
    assert len(snaps) == 2 and all("ob_imbalance" not in s.features for s in snaps)


def test_tick_market_passes_micro_into_the_decision_snapshots(monkeypatch):
    market = engine.MARKETS["btc_daily"]
    now_ts = T0 + 7200
    now = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    src = _sources(now_ts)
    src.micro = lambda tickers, ts: {t: {"ob_imbalance": -0.5} for t in tickers}
    dep = {"id": 1, "user_id": 1, "last_decision_ts": 0, "spec": {}}
    monkeypatch.setattr(engine, "settle_due", lambda *a, **k: 0)
    monkeypatch.setattr(repo, "running_deployments", lambda cur, key: [dep])
    monkeypatch.setattr(repo, "market_has_open_positions", lambda cur, key: False)
    monkeypatch.setattr(repo, "update_marks", lambda *a, **k: 0)
    monkeypatch.setattr(repo, "claim_decision", lambda cur, dep_id, slot: True)
    monkeypatch.setattr(engine, "_is_multi_market_cross", lambda spec: False)
    got = {}
    monkeypatch.setattr(engine, "decide", lambda conn, d, snaps, sizes, sources: got.setdefault("snaps", snaps))

    class _Conn:
        def cursor(self):
            return None

    engine.tick_market(_Conn(), market, src, now)
    assert got["snaps"] and all(s.features["ob_imbalance"] == -0.5 for s in got["snaps"])


class _SchemaCur(_Cur):
    """Answers SHOW COLUMNS with a model_features_1m that predates the flow columns."""

    def __init__(self, rows, fields):
        super().__init__(rows)
        self.fields = fields
        self._last = None

    def execute(self, sql, params=None):
        super().execute(sql, params)
        self._last = sql

    def fetchall(self):
        if self._last and self._last.startswith("SHOW COLUMNS"):
            return [{"Field": f} for f in self.fields]
        return self.rows


def test_micro_select_skips_columns_missing_from_the_table(monkeypatch):
    """A MICRO_FEATURES entry whose migration hasn't run must not fail the whole read (which would
    drop every order-book feature from research and live): it is just left out."""
    monkeypatch.setattr(repo, "_micro_cols_cache", {"at": 0.0, "fields": None})
    legacy = [c for n, (c, _d) in MICRO_FEATURES.items() if not c.startswith(("taker_", "flow_"))]
    now = 1_800_000_000
    cur = _SchemaCur([_row("A", now - 60, 0.3)], ["market_ticker", "snapshot_minute_utc"] + legacy)
    out = repo.latest_micro(cur, ["A"], now)
    assert out == {"A": {"ob_imbalance": 0.3, "yes_bid_size": 10}}
    assert "flow_imbalance_60s" not in cur.sql and "orderbook_imbalance AS ob_imbalance" in cur.sql
