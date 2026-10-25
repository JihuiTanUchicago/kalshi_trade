"""The live gate's demo check (app/services/demo_record.py): settled demo orders, nothing lost,
and a demo book that matches the demo exchange."""
from datetime import datetime, timedelta

from app import agent
from app import repository as repo
from app.services import demo_record

NOW = datetime(2026, 10, 25, 22, 0, 0)


def _patch(monkeypatch, resolved=25, unresolved=0, first_at=NOW - timedelta(days=2), sweeps=None):
    monkeypatch.setattr(repo, "demo_order_outcomes", lambda cur, uid, sid, stale_before: {
        "resolved": resolved, "unresolved": unresolved, "first_at": first_at})
    seen = {}

    def since(cur, uid, t):
        seen["since"] = t
        return list(sweeps if sweeps is not None else [{"checked_at": NOW - timedelta(minutes=10), "mismatches": []}])

    monkeypatch.setattr(repo, "demo_sweeps_since", since)
    return seen


def _sw(minutes_ago, *tickers):
    return {"checked_at": NOW - timedelta(minutes=minutes_ago), "mismatches": [{"ticker": t} for t in tickers]}


def test_clean_record_passes_and_reads_sweeps_from_the_first_demo_order(monkeypatch):
    seen = _patch(monkeypatch)
    ev = demo_record.demo_evidence(None, 1, 7, now=NOW)
    assert ev["ok"] and ev["why"] == "" and ev["orders"] == 25
    assert seen["since"] == NOW - timedelta(days=2)


def test_too_few_settled_orders_refuses(monkeypatch):
    _patch(monkeypatch, resolved=19)
    ev = demo_record.demo_evidence(None, 1, 7, now=NOW)
    assert not ev["ok"] and "20+ settled orders" in ev["why"] and "(has 19)" in ev["why"]


def test_no_demo_orders_at_all_refuses_without_reading_sweeps(monkeypatch):
    seen = _patch(monkeypatch, resolved=0, first_at=None)
    ev = demo_record.demo_evidence(None, 1, 7, now=NOW)
    assert not ev["ok"] and "since" not in seen


def test_a_lost_order_refuses(monkeypatch):
    _patch(monkeypatch, unresolved=1)
    ev = demo_record.demo_evidence(None, 1, 7, now=NOW)
    assert not ev["ok"] and "never accounted for" in ev["why"]


def test_a_mismatch_on_two_sweeps_in_a_row_refuses_but_one_sighting_does_not(monkeypatch):
    _patch(monkeypatch, sweeps=[_sw(60, "A"), _sw(45), _sw(30, "B"), _sw(15)])
    assert demo_record.demo_evidence(None, 1, 7, now=NOW)["ok"]
    _patch(monkeypatch, sweeps=[_sw(60, "A"), _sw(45, "A"), _sw(30), _sw(15)])
    ev = demo_record.demo_evidence(None, 1, 7, now=NOW)
    assert not ev["ok"] and "disagreed on A" in ev["why"] and ev["mismatched_tickers"] == ["A"]


def test_a_stale_or_missing_check_refuses(monkeypatch):
    for sweeps in ([], [_sw(25 * 60)]):
        _patch(monkeypatch, sweeps=sweeps)
        ev = demo_record.demo_evidence(None, 1, 7, now=NOW)
        assert not ev["ok"] and "last 24h" in ev["why"]


def test_sweep_records_classified_mismatches_and_skips_unreadable_accounts(monkeypatch):
    rows = []
    monkeypatch.setattr(repo, "has_demo_activity", lambda cur, uid: True)
    monkeypatch.setattr(repo, "demo_book_by_ticker_side", lambda cur, uid: [
        {"ticker": "A", "side": "yes", "qty": 3}, {"ticker": "B", "side": "no", "qty": 2}])
    monkeypatch.setattr(repo, "insert_demo_sweep", lambda cur, uid, n, mm: rows.append((n, mm)))
    # A matches; B is held NO on both sides (-2 == -2); C is on the exchange only.
    found = demo_record.sweep(None, 1, read_positions=lambda cur, uid: {"A": 3, "B": -2, "C": 1})
    assert [(d.ticker, d.kind) for d in found] == [("C", "untracked")]
    assert rows == [(3, [{"ticker": "C", "kind": "untracked", "exchange_qty": 1, "book_qty": 0}])]
    # A failed read writes nothing: it can only let the check go stale, never pass it.
    assert demo_record.sweep(None, 1, read_positions=lambda cur, uid: None) is None
    assert len(rows) == 1


def test_sweep_skips_users_with_no_demo_activity(monkeypatch):
    monkeypatch.setattr(repo, "has_demo_activity", lambda cur, uid: False)
    called = []
    assert demo_record.sweep(None, 1, read_positions=lambda cur, uid: called.append(1) or {}) is None
    assert not called


def test_demo_check_is_the_last_live_gate_check(monkeypatch):
    """Appended last, so no earlier check moves; a failing demo record alone blocks live."""
    monkeypatch.setattr(repo, "list_deployments", lambda cur, uid, include_stopped=False: [])
    monkeypatch.setattr(repo, "paper_round_trips", lambda cur, uid, sid: [])
    monkeypatch.setattr(repo, "get_strategy", lambda cur, uid, sid: None)
    monkeypatch.setattr(demo_record, "demo_evidence", lambda cur, uid, sid: {
        "ok": False, "why": "demo says no", "orders": 3, "orders_needed": 20, "unresolved": 0,
        "mismatched_tickers": [], "last_check_at": None})
    ev = agent.paper_evidence(None, 1, 7)
    assert list(ev["checks"])[-1] == "demo" and ev["checks"]["demo"] is False
    assert list(ev["checks"])[:-1] == ["legacy_trades", "legacy_pnl", "realistic_trades", "events",
                                       "net_pnl", "span", "edge", "recent"]
    assert ev["demo_orders"] == 3 and ev["demo_orders_needed"] == 20
