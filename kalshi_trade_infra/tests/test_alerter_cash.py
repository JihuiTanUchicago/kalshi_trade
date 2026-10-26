"""The daily check-in's cash figure comes from Kalshi, not a frozen snapshot.

On 2026-10-26 the heartbeat still said $56.58 (kalshi_api): that was the last live_portfolio_20s row,
written by the legacy live engine before it was stopped on 2026-10-24.
"""
from datetime import datetime

import data_pipeline.live_alerter as la


class _Cur:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, args=None):
        pass

    def fetchone(self):
        return self.row


SNAP = {"snapshot_time_utc": datetime(2026, 10, 14, 3, 12), "equity_dollars": 56.58,
        "raw_json": '{"cash_source": "kalshi_api"}'}


def _now(**kw):
    base = {"enabled": {}, "positions": [], "daily": {}, "paused": {}, "cash_as_of": None}
    base.update(kw)
    return base


def test_reads_the_balance_from_kalshi_now(monkeypatch):
    monkeypatch.setattr(la, "get_kalshi_cash_balance_dollars", lambda: 123.45)
    assert la._cash(_Cur(SNAP)) == (123.45, "kalshi_api", None)


def test_unreadable_balance_falls_back_to_the_snapshot_and_says_when(monkeypatch):
    monkeypatch.setattr(la, "get_kalshi_cash_balance_dollars", lambda: None)
    cash, source, as_of = la._cash(_Cur(SNAP))
    assert (cash, source, as_of) == (56.58, "snapshot, kalshi_api", "2026-10-14 03:12Z")
    body = la.heartbeat_body(_now(cash=cash, cash_source=source, cash_as_of=as_of))
    assert "Cash: $56.58 (snapshot, kalshi_api, as of 2026-10-14 03:12Z)" in body


def test_live_balance_line(monkeypatch):
    assert "Cash: $123.45 (kalshi_api)\n" in la.heartbeat_body(_now(cash=123.45, cash_source="kalshi_api"))
