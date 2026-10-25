"""Every child order of an intent is recovered, and nothing new is sent on top of an unknown one.

The kernel sends one intent as several IOC children: client_order_id ``<intent>`` first, then
``<intent>-1``, ``<intent>-2`` as it escalates. A timeout or crash on any child leaves the intent
'sent'. Recovery used to look up only ``<intent>``, so a fill on a retry child was never booked:
an entry became an untracked live position, and an exit left the book thinking it still held
contracts that were already sold, so the next tick sold them again.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import engine
from data_pipeline.architecture.execution_kernel import child_client_order_id


def test_child_ids_match_the_kernel_scheme():
    assert [child_client_order_id("I", a) for a in range(3)] == ["I", "I-1", "I-2"]


def test_recovery_sums_every_child_fill():
    orders = [
        {"client_order_id": "I", "fill_count": "4.00", "average_fill_price": "0.4000",
         "average_fee_paid": "0.0170", "order_id": "o0"},
        {"client_order_id": "I-1", "fill_count": "0.00", "order_id": "o1"},
        {"client_order_id": "I-2", "fill_count": "6.00", "average_fill_price": "0.4500",
         "average_fee_paid": "0.0175", "order_id": "o2"},
        {"client_order_id": "OTHER", "fill_count": "99.00", "average_fill_price": "0.10"},
        {"client_order_id": "I-x", "fill_count": "50.00", "average_fill_price": "0.10"},
        {"client_order_id": "I2", "fill_count": "50.00", "average_fill_price": "0.10"},
    ]
    got = engine._match_order_fill(orders, "I", "yes")
    assert got["filled"] == 10
    assert got["avg_price"] == pytest.approx((4 * 0.40 + 6 * 0.45) / 10, abs=1e-4)
    assert got["fee"] == pytest.approx(4 * 0.0170 + 6 * 0.0175)
    assert got["order_id"] == "o2"


def test_a_fill_only_on_a_retry_child_is_not_booked_unfilled():
    # Attempt 0 crossed nothing, attempt 1 filled, then the response was lost. The old lookup read
    # only "I" (0 filled) and marked the intent unfilled: a live position the book never knew about.
    orders = [{"client_order_id": "I", "fill_count": "0.00", "order_id": "o0"},
              {"client_order_id": "I-1", "fill_count": "7.00", "average_fill_price": "0.5200",
               "average_fee_paid": "0.0175", "order_id": "o1"}]
    got = engine._match_order_fill(orders, "I", "yes")
    assert got["filled"] == 7 and got["avg_price"] == pytest.approx(0.52)


def test_first_child_absent_is_indeterminate():
    assert engine._match_order_fill([{"client_order_id": "I-1", "fill_count": "3.00"}], "I", "yes") is None


def test_no_side_fill_is_flipped_to_its_own_cost_basis():
    orders = [{"client_order_id": "I", "fill_count": "5.00", "average_fill_price": "0.6200",
               "average_fee_paid": "0.0170", "order_id": "o"}]
    assert engine._match_order_fill(orders, "I", "no")["avg_price"] == pytest.approx(0.38)


def test_orders_read_follows_the_cursor_and_bounds_by_time():
    pages = [{"orders": [{"client_order_id": "a"}], "cursor": "c1"},
             {"orders": [{"client_order_id": "I"}], "cursor": ""}]
    seen = []

    def fetch(params):
        seen.append(params)
        return pages[len(seen) - 1]

    out = engine._orders_since(fetch, "T", 1_700_000_000)
    assert [o["client_order_id"] for o in out] == ["a", "I"]
    assert seen[0] == {"ticker": "T", "limit": 200, "min_ts": 1_700_000_000}
    assert seen[1]["cursor"] == "c1"


def test_intent_min_ts_is_a_little_before_the_intent():
    created = datetime(2026, 10, 24, 8, 0, 0)  # naive UTC, as stored
    expected = int(created.replace(tzinfo=timezone.utc).timestamp()) - 120
    assert engine._intent_min_ts({"created_at": created}) == expected
    assert engine._intent_min_ts({}) is None


class _RecordingKernel:
    def __init__(self):
        self.calls = 0

    def execute(self, intent):
        self.calls += 1
        raise AssertionError("no order may be sent while an earlier one is unresolved")


def test_exit_is_deferred_while_an_earlier_order_on_the_ticker_is_unresolved(monkeypatch):
    monkeypatch.setattr(engine.repo, "ticker_has_inflight_intent", lambda *a, **k: True)
    k = _RecordingKernel()
    dep = {"id": 1, "user_id": 9, "mode": "live"}
    pos = {"id": 5, "ticker": "T", "side": "yes", "qty": 10, "entry_price": 0.5, "entry_fee": 0.1}
    assert engine._close_position_at(None, None, dep, pos, k, True, 0.40, "exit") is False
    assert k.calls == 0


def test_paper_exit_is_never_blocked_by_the_inflight_check(monkeypatch):
    monkeypatch.setattr(engine.repo, "ticker_has_inflight_intent", lambda *a, **k: True)
    closed = []
    monkeypatch.setattr(engine, "_paper_sell", lambda conn, pos, price, reason: closed.append(pos["id"]))
    pos = {"id": 5, "ticker": "T", "side": "yes", "qty": 10, "entry_price": 0.5, "entry_fee": 0.1}
    assert engine._close_position_at(None, None, {"id": 1, "user_id": 9}, pos, None, False, 0.4, "exit")
    assert closed == [5]


def test_pair_entry_is_skipped_while_a_leg_is_unresolved(monkeypatch):
    monkeypatch.setattr(engine.repo, "ticker_has_inflight_intent",
                        lambda cur, uid, ticker, within, mode: ticker == "NO-LEG" and mode == "live")
    k = _RecordingKernel()
    legs = [("yes", "YES-LEG", 0.4, 0.39, None), ("no", "NO-LEG", 0.5, 0.49, None)]
    assert engine._kernel_buy_pair(None, None, {"id": 1, "user_id": 9}, k, legs, 5, "live") is False
    assert k.calls == 0


def test_inflight_check_fails_open_on_a_read_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db blip")
    monkeypatch.setattr(engine.repo, "ticker_has_inflight_intent", boom)
    assert engine._order_in_flight(None, 1, "T", "live") is False


def test_inflight_query_is_scoped_to_user_ticker_mode_and_window():
    from app import repository as repo

    class Cur:
        def execute(self, sql, params):
            self.sql, self.params = sql, params

        def fetchone(self):
            return {"x": 1}

    c = Cur()
    assert repo.ticker_has_inflight_intent(c, 9, "T", 180, mode="demo") is True
    assert "status='sent'" in c.sql and "user_id=%s" in c.sql and "ticker=%s" in c.sql and "mode=%s" in c.sql
    assert c.params[0] == 9 and c.params[1] == "T" and c.params[2] == "demo"
    assert c.params[3] > repo.now_utc() - timedelta(seconds=200)


def test_intent_past_its_horizon_is_marked_unresolved_without_polling(monkeypatch):
    now = datetime.now(timezone.utc)
    old = {"intent_id": "old", "mode": "demo", "action": "buy", "ticker": "T", "qty": 5,
           "market_close_time": (now - timedelta(days=2)).replace(tzinfo=None),
           "created_at": (now - timedelta(days=7)).replace(tzinfo=None)}
    fresh = {"intent_id": "new", "mode": "live", "action": "buy", "ticker": "T", "qty": 5,
             "market_close_time": (now + timedelta(minutes=10)).replace(tzinfo=None),
             "created_at": (now - timedelta(minutes=1)).replace(tzinfo=None)}
    marked, asked = [], []
    monkeypatch.setattr(engine.repo, "open_sent_intents", lambda cur, s: [old, fresh])
    monkeypatch.setattr(engine.repo, "mark_order_intent", lambda cur, iid, status, *a, **k: marked.append((iid, status)))

    class C:
        def cursor(self):
            return None

    engine.recover_sent_intents(C(), engine.Sources(order_lookup=lambda it: asked.append(it["intent_id"])))
    assert marked == [("old", "unresolved")]
    assert asked == ["new"]  # only the live one is still asked about


def test_horizon_without_a_close_time_uses_the_intent_age():
    now = datetime.now(timezone.utc)
    assert engine._past_resolution_horizon({"created_at": now - timedelta(days=8)}, now)
    assert not engine._past_resolution_horizon({"created_at": now - timedelta(days=1)}, now)
    assert not engine._past_resolution_horizon({}, now)


def test_unrecovered_log_is_throttled(monkeypatch, capsys):
    it = {"intent_id": "x", "mode": "live", "action": "buy", "ticker": "T", "qty": 1,
          "created_at": datetime.now(timezone.utc).replace(tzinfo=None)}
    monkeypatch.setattr(engine.repo, "open_sent_intents", lambda cur, s: [it])
    engine._unrecovered_logged.clear()

    class C:
        def cursor(self):
            return None

    src = engine.Sources(order_lookup=lambda i: None)
    engine.recover_sent_intents(C(), src)
    engine.recover_sent_intents(C(), src)
    assert capsys.readouterr().out.count("UNRECOVERED") == 1
