"""The perps watch: positions vs Tau's filled orders, liquidation and margin
proximity, announced once per condition and never placing an order."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app import kalshi_perps_watch as watch
from app.kalshi_perps_watch import LIQUIDATION, MARGIN, MISMATCH, position_alerts, risk_alerts

T = "KXBTCPERP-USD"
D = Decimal


def _account(equity="1000", maintenance="100"):
    return {"account_equity": equity, "maintenance_margin": maintenance}


def _risk(*rows):
    return {"positions": list(rows)}


def _row(position="5", mark="60000", liq="40000"):
    return {"market_ticker": T, "position": position, "mark_price": mark, "estimated_liquidation_price": liq}


# -- pure rules -----------------------------------------------------------------


def test_matching_book_and_exchange_is_clean():
    assert position_alerts({T: D(5)}, {T: D(5)}) == []
    assert position_alerts({T: D(-3)}, {T: D(-3)}) == []


@pytest.mark.parametrize("book,exch,needle", [
    ({}, {T: D(4)}, "no Tau order filled"),
    ({T: D(4)}, {}, "Kalshi holds none"),
    ({T: D(4)}, {T: D(-4)}, "Kalshi holds -4"),
])
def test_position_mismatches_are_flagged(book, exch, needle):
    (alert,) = position_alerts(book, exch)
    assert alert.kind == MISMATCH and alert.key == "mismatch:" + T and needle in alert.detail


def test_far_from_liquidation_is_quiet():
    assert risk_alerts(_risk(_row(mark="60000", liq="40000")), _account()) == []


def test_near_liquidation_alerts_long_and_short():
    (a,) = risk_alerts(_risk(_row(mark="60000", liq="56000")), _account())
    assert a.kind == LIQUIDATION and "6.7% from liquidation" in a.detail
    (b,) = risk_alerts(_risk(_row(position="-5", mark="60000", liq="63000")), _account())
    assert b.kind == LIQUIDATION


def test_liquidation_threshold_is_configurable(monkeypatch):
    monkeypatch.setenv("TAU_KALSHI_PERPS_LIQ_ALERT_PCT", "40")
    assert [a.kind for a in risk_alerts(_risk(_row(mark="60000", liq="40000")), _account())] == [LIQUIDATION]


def test_flat_or_unpriced_positions_are_ignored():
    assert risk_alerts(_risk(_row(position="0", liq="59999"), _row(liq=None)), _account()) == []


def test_margin_use_alerts_at_half_equity_and_on_wiped_equity():
    assert risk_alerts(_risk(), _account("1000", "499")) == []
    (a,) = risk_alerts(_risk(), _account("1000", "500"))
    assert a.kind == MARGIN and "50%" in a.detail
    (b,) = risk_alerts(_risk(), _account("-5", "100"))
    assert b.kind == MARGIN and "uses all" in b.detail


# -- announce-once discipline over sweeps -----------------------------------------


class Book:
    """In-memory stand-in for the store's watch table and the chat log."""

    def __init__(self, filled=None):
        self.filled = filled or {}
        self.rows = {}
        self.chat = []
        self.emails = []
        self.clock = datetime(2026, 10, 24, 12, 0)

    def tick(self):
        self.clock += timedelta(minutes=1)


@pytest.fixture
def book(monkeypatch):
    b = Book()
    st = watch.store

    def upsert(cur, uid, env, key, kind, detail):
        prev = b.rows.get(key)
        b.rows[key] = {"alert_key": key, "kind": kind, "detail": detail, "updated_at": b.clock,
                       "detected_at": prev["detected_at"] if prev else b.clock}

    monkeypatch.setattr(st, "filled_net_by_ticker", lambda cur, uid, env: dict(b.filled))
    monkeypatch.setattr(st, "open_watch_rows", lambda cur, uid, env: [dict(r) for r in b.rows.values()])
    monkeypatch.setattr(st, "upsert_watch", upsert)
    monkeypatch.setattr(st, "resolve_watch", lambda cur, uid, env, keys: [b.rows.pop(k) for k in keys])
    monkeypatch.setattr(watch.repo, "add_chat", lambda cur, uid, role, text: b.chat.append(text))
    monkeypatch.setattr(watch, "_email", lambda cur, uid, subject, body: b.emails.append(subject))
    return b


def _state(position=None, account=None, risk_rows=()):
    positions = [] if position is None else [{"market_ticker": T, "position": position}]
    return {"positions": positions, "account": account or _account(), "risk": _risk(*risk_rows)}


def _sweep(book, state, in_flight=False):
    out = watch.watch_user(None, 7, "production", state, in_flight)
    book.tick()
    return out


def test_mismatch_waits_for_second_sweep_then_announces_once(book):
    _sweep(book, _state("4"))
    assert book.chat == []
    _sweep(book, _state("4"))
    assert len(book.chat) == 1 and "no Tau order filled" in book.chat[0] and len(book.emails) == 1
    _sweep(book, _state("4"))
    assert len(book.chat) == 1


def test_mismatch_seen_once_clears_silently(book):
    _sweep(book, _state("4"))
    _sweep(book, _state())
    assert book.chat == [] and book.rows == {}


def test_persisted_mismatch_announces_when_cleared(book):
    _sweep(book, _state("4"))
    _sweep(book, _state("4"))
    book.filled = {T: D(4)}
    _sweep(book, _state("4"))
    assert book.chat[-1].startswith("Bitcoin perps watch cleared:") and book.rows == {}


def test_in_flight_order_skips_mismatch_without_clearing_it(book):
    _sweep(book, _state("4"))
    _sweep(book, _state(), in_flight=True)
    assert "mismatch:" + T in book.rows and book.chat == []


def test_liquidation_announces_immediately_and_once(book):
    near = _row(mark="60000", liq="57000")
    _sweep(book, _state(risk_rows=[near]))
    _sweep(book, _state(risk_rows=[_row(mark="59000", liq="57000")]))
    assert len(book.chat) == 1 and "from liquidation" in book.chat[0] and len(book.emails) == 1
    _sweep(book, _state())
    assert book.chat[-1].startswith("Bitcoin perps watch cleared:")


def test_watch_never_touches_order_paths(book, monkeypatch):
    for name in ("create_order", "submit_order", "cancel_order"):
        monkeypatch.setattr(watch.service, name, lambda *a, **k: pytest.fail("watch placed an order"))
    _sweep(book, _state("4", _account("10", "9"), [_row(liq="59000")]))
    _sweep(book, _state("4", _account("10", "9"), [_row(liq="59000")]))


# -- sweep containment ---------------------------------------------------------


def test_one_users_failure_does_not_stop_the_sweep(monkeypatch):
    class Conn:
        def cursor(self):
            return object()

    seen = []
    monkeypatch.setattr(watch.service, "environment", lambda: "production")
    monkeypatch.setattr(watch.store, "users_to_watch", lambda cur, env: [1, 2])
    monkeypatch.setattr(watch.store, "reservation_orders", lambda cur, uid, env: [])

    def key(cur, uid, env):
        if uid == 1:
            raise RuntimeError("vault down")
        return "h", {"key_id": "k"}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def balance(self):
            return {"subaccount_balances": [{"subaccount": 0, **_account()}]}

        def risk(self):
            return _risk()

        def positions(self):
            return {"positions": []}

    class Tx:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(watch.service, "_key", key)
    monkeypatch.setattr(watch.service, "_client", lambda uid, k, env: Client())
    monkeypatch.setattr(watch.repo, "transaction", lambda conn: Tx())
    monkeypatch.setattr(watch, "watch_user", lambda tx, uid, env, state, fl: seen.append(uid) or [])
    assert watch.watch_all(Conn()) == {"users": 1, "alerts": 0, "errors": 1}
    assert seen == [2]


def test_user_without_a_key_is_skipped(monkeypatch):
    class Conn:
        def cursor(self):
            return object()

    monkeypatch.setattr(watch.service, "environment", lambda: "production")
    monkeypatch.setattr(watch.store, "users_to_watch", lambda cur, env: [3])

    def no_key(cur, uid, env):
        raise watch.service.Error("Connect your own Kalshi key", 409, "not_connected")

    monkeypatch.setattr(watch.service, "_key", no_key)
    assert watch.watch_all(Conn()) == {"users": 0, "alerts": 0, "errors": 0}


def test_filled_net_signs_bids_long_and_asks_short():
    class Cur:
        def execute(self, sql, params):
            assert "filled_count > 0" in sql and params == (7, "production")

        def fetchall(self):
            return [{"request_json": {"ticker": T, "side": "bid"}, "filled_count": D("5.00")},
                    {"request_json": '{"ticker": "%s", "side": "ask"}' % T, "filled_count": D("2")},
                    {"request_json": {"ticker": "OTHER", "side": "ask"}, "filled_count": D("1")},
                    {"request_json": {"ticker": "FLAT", "side": "bid"}, "filled_count": D("1")},
                    {"request_json": {"ticker": "FLAT", "side": "ask"}, "filled_count": D("1")}]

    assert watch.store.filled_net_by_ticker(Cur(), 7, "production") == {T: D(3), "OTHER": D(-1)}
