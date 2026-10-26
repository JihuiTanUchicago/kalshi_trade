"""Tau-aware per-user live position reconciliation.

The crux is the YES/NO sign: a NO position is a short-YES on the exchange, so
Kalshi reports it as a NEGATIVE signed position. A correctly held NO must
reconcile MATCHED, never as a phantom short. These tests pin that mapping, the
discrepancy classes, the audit+notify surfacing, multi-user isolation, and that
orphan adoption is OFF (places nothing) by default.
"""
from datetime import datetime

import pytest

from app import reconcile
from app.reconcile import (BOOK_ONLY, SHORT, SIZE_MISMATCH, UNTRACKED, Discrepancy,
                           ExchPos, book_net_from_rows, classify)


# -- pure classify (the mapping crux, no DB) -----------------------------------


def test_matched_yes_is_clean():
    assert classify({"T1": 12}, {"T1": 12}) == []


def test_matched_no_is_clean_not_a_short():
    # Book holds 12 NO -> net -12; exchange reports the short-YES as -12. MATCHED.
    assert classify({"T1": -12}, {"T1": -12}) == []


def test_book_net_folds_sides_signed():
    rows = [{"ticker": "T1", "side": "yes", "qty": 5}, {"ticker": "T1", "side": "no", "qty": 2},
            {"ticker": "T2", "side": "no", "qty": 3}]
    assert book_net_from_rows(rows) == {"T1": 3, "T2": -3}


def test_a_fully_offset_ticker_drops_out():
    rows = [{"ticker": "T1", "side": "yes", "qty": 4}, {"ticker": "T1", "side": "no", "qty": 4}]
    assert book_net_from_rows(rows) == {}


def test_untracked_exchange_position_is_flagged():
    out = classify({}, {"T1": 9})
    assert out == [Discrepancy("T1", UNTRACKED, 9, 0)]


def test_untracked_no_exchange_position_is_untracked_not_short():
    out = classify({}, {"T1": -9})
    assert out == [Discrepancy("T1", UNTRACKED, -9, 0)]


def test_book_only_position_is_flagged():
    assert classify({"T1": 7}, {}) == [Discrepancy("T1", BOOK_ONLY, 0, 7)]


def test_size_mismatch_same_side_is_flagged():
    assert classify({"T1": 7}, {"T1": 10}) == [Discrepancy("T1", SIZE_MISMATCH, 10, 7)]


def test_opposite_direction_is_a_short():
    # Book thinks YES 5, exchange holds NO (short-YES) -3: a genuine unexpected short.
    assert classify({"T1": 5}, {"T1": -3}) == [Discrepancy("T1", SHORT, -3, 5)]


# -- reconcile_user: audit + notify (fake cursor, no DB) -----------------------


class FakeCur:
    """Minimal stand-in covering exactly the queries the reconcile repo layer issues."""

    def __init__(self, store):
        self.store = store
        self._last = []
        self.lastrowid = 1
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self._last = []
        if s.startswith("SELECT DISTINCT k.user_id FROM app_kalshi_keys"):
            self._last = [{"user_id": u} for u in self.store["users"]]
        elif s.startswith("SELECT market_ticker AS ticker, 'yes' AS side"):
            self._last = list(self.store.get("legacy", []))
        elif s.startswith("SELECT ticker, side, COALESCE(SUM(qty),0) AS qty FROM app_positions"):
            uid = params[0]
            self._last = list(self.store["book"].get(uid, []))
        elif s.startswith("SELECT ticker, kind, exchange_qty, book_qty, detected_at, updated_at "
                          "FROM app_position_reconcile"):
            uid = params[0]
            self._last = list(self.store["recon"].get(uid, []))
        elif s.startswith("INSERT INTO app_position_reconcile"):
            uid, ticker, kind, exch, book = params[0], params[1], params[2], params[3], params[4]
            self.store.setdefault("upserts", []).append(
                {"user_id": uid, "ticker": ticker, "kind": kind, "exchange_qty": exch, "book_qty": book})
        elif s.startswith("UPDATE app_position_reconcile SET status='resolved'"):
            self.store.setdefault("resolves", []).append(list(params))
        elif s.startswith("INSERT INTO app_chat_messages"):
            self.store.setdefault("chats", []).append({"user_id": params[0], "content": params[2]})
            self.lastrowid = len(self.store["chats"])
        elif s.startswith("SELECT d.id FROM app_deployments d JOIN app_strategies s"):
            self._last = []  # no reconcile deployment yet -> force creation path
        elif s.startswith("INSERT INTO app_strategies"):
            self.lastrowid = 101
        elif s.startswith("INSERT INTO app_deployments"):
            self.lastrowid = 202
        elif s.startswith("INSERT INTO app_positions"):
            self.store.setdefault("positions", []).append(
                {"deployment_id": params[0], "user_id": params[1], "mode": params[2],
                 "ticker": params[3], "side": params[4], "qty": params[5], "entry": params[6]})
            self.lastrowid = len(self.store["positions"])
        else:
            raise AssertionError("unexpected SQL: " + s[:90])

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return self._last


T0 = datetime(2026, 10, 24, 8, 0, 0)
T1 = datetime(2026, 10, 24, 8, 5, 0)


def _store(book=None, recon=None, users=None):
    return {"book": book or {}, "recon": recon or {}, "users": users or []}


def test_matched_yes_user_is_silent():
    store = _store(book={1: [{"ticker": "T1", "side": "yes", "qty": 12}]})
    cur = FakeCur(store)
    out = reconcile.reconcile_user(cur, 1, {"T1": ExchPos(12, 6.0)})
    assert out == []
    assert "chats" not in store  # nothing to tell the user
    assert "upserts" not in store


def test_matched_no_user_is_silent():
    store = _store(book={1: [{"ticker": "T1", "side": "no", "qty": 12}]})
    cur = FakeCur(store)
    out = reconcile.reconcile_user(cur, 1, {"T1": ExchPos(-12, 6.0)})
    assert out == [] and "chats" not in store


def test_untracked_is_audited_and_user_notified():
    store = _store(book={1: []})
    cur = FakeCur(store)
    out = reconcile.reconcile_user(cur, 1, {"T1": ExchPos(9, 4.5)})
    assert [d.kind for d in out] == [UNTRACKED]
    assert store["upserts"] == [{"user_id": 1, "ticker": "T1", "kind": UNTRACKED,
                                 "exchange_qty": 9, "book_qty": 0}]
    assert len(store["chats"]) == 1 and "URGENT" in store["chats"][0]["content"]


def test_book_only_is_flagged():
    store = _store(book={1: [{"ticker": "T1", "side": "yes", "qty": 4}]})
    cur = FakeCur(store)
    out = reconcile.reconcile_user(cur, 1, {})
    assert [d.kind for d in out] == [BOOK_ONLY] and store["upserts"][0]["kind"] == BOOK_ONLY


def test_size_mismatch_is_flagged():
    store = _store(book={1: [{"ticker": "T1", "side": "yes", "qty": 4}]})
    cur = FakeCur(store)
    out = reconcile.reconcile_user(cur, 1, {"T1": ExchPos(7, 3.5)})
    assert [d.kind for d in out] == [SIZE_MISMATCH]


def test_real_short_is_flagged_urgent():
    store = _store(book={1: [{"ticker": "T1", "side": "yes", "qty": 5}]})
    cur = FakeCur(store)
    out = reconcile.reconcile_user(cur, 1, {"T1": ExchPos(-3, 1.5)})
    assert [d.kind for d in out] == [SHORT]
    assert "URGENT" in store["chats"][0]["content"]


def test_unchanged_discrepancy_does_not_renotify():
    # Audit already has the same open, already-halting row -> upsert refreshes it but no new chat.
    store = _store(book={1: []},
                   recon={1: [{"ticker": "T1", "kind": UNTRACKED, "exchange_qty": 9, "book_qty": 0,
                               "detected_at": T0, "updated_at": T1}]})
    cur = FakeCur(store)
    reconcile.reconcile_user(cur, 1, {"T1": ExchPos(9, 4.5)})
    assert "chats" not in store and len(store["upserts"]) == 1


def test_adoption_off_by_default_places_nothing(monkeypatch):
    monkeypatch.delenv("APP_RECONCILE_ADOPT_ORPHANS", raising=False)
    store = _store(book={1: []})
    cur = FakeCur(store)
    reconcile.reconcile_user(cur, 1, {"T1": ExchPos(9, 4.5)}, adopt=False)
    assert "positions" not in store  # no book row written, and never any order


def test_adoption_on_records_a_tracked_row_but_no_order():
    store = _store(book={1: []})
    cur = FakeCur(store)
    reconcile.reconcile_user(cur, 1, {"KXBTCD-X": ExchPos(9, 4.5)}, adopt=True)
    assert len(store["positions"]) == 1
    p = store["positions"][0]
    assert p["user_id"] == 1 and p["side"] == "yes" and p["qty"] == 9 and p["mode"] == "live"
    assert p["entry"] == pytest.approx(0.5)  # 4.5 / 9


# -- reconcile_all: multi-user isolation ---------------------------------------


class FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def begin(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


def test_multi_user_isolation(monkeypatch):
    # User 1 holds 12 YES on T1 and that matches THEIR exchange. User 2's exchange
    # holds something entirely different. Neither user's book is ever compared to
    # the other's account: user 1 reconciles clean, user 2 is flagged on its own.
    store = _store(users=[1, 2], book={1: [{"ticker": "T1", "side": "yes", "qty": 12}], 2: []})
    cur = FakeCur(store)
    conn = FakeConn(cur)

    exch_by_user = {1: {"T1": ExchPos(12, 6.0)}, 2: {"T2": ExchPos(5, 2.5)}}
    monkeypatch.setattr(reconcile.repo, "get_kalshi_key", lambda c, uid: {"user_id": uid})
    import app.adapters.kalshi.kalshi_account as ka
    monkeypatch.setattr(ka, "credentials_from_row", lambda uid, row: uid)
    monkeypatch.setattr(reconcile, "exchange_positions", lambda creds: exch_by_user[creds])

    summary = reconcile.reconcile_all(conn)
    assert summary["users"] == 2 and summary["errors"] == 0
    # User 1 clean (no upsert); user 2's T2 flagged untracked — and user 1 was never
    # compared to user 2's T2.
    upserts = store.get("upserts", [])
    assert [u["user_id"] for u in upserts] == [2]
    assert upserts[0]["ticker"] == "T2" and upserts[0]["kind"] == UNTRACKED


def test_reconcile_all_contains_one_user_failure(monkeypatch):
    store = _store(users=[1, 2], book={1: [], 2: []})
    cur = FakeCur(store)
    conn = FakeConn(cur)
    monkeypatch.setattr(reconcile.repo, "get_kalshi_key", lambda c, uid: {"user_id": uid})
    import app.adapters.kalshi.kalshi_account as ka
    monkeypatch.setattr(ka, "credentials_from_row", lambda uid, row: uid)

    def exch(creds):
        if creds == 1:
            raise RuntimeError("Kalshi unreachable")
        return {"T2": ExchPos(5, 2.5)}

    monkeypatch.setattr(reconcile, "exchange_positions", exch)
    summary = reconcile.reconcile_all(conn)
    assert summary["errors"] == 1 and summary["users"] == 1  # user 2 still reconciled


# -- halting live entries on a persisted mismatch --------------------------------


def test_first_sighting_records_but_does_not_announce_a_halt():
    store = _store(book={1: []})
    reconcile.reconcile_user(FakeCur(store), 1, {"T1": ExchPos(9, 4.5)})
    assert not any("HALTED" in c["content"] for c in store["chats"])


def test_second_sighting_announces_the_halt_once():
    # Seen once before (detected_at == updated_at): this sweep makes it a halt.
    store = _store(book={1: []},
                   recon={1: [{"ticker": "T1", "kind": UNTRACKED, "exchange_qty": 9, "book_qty": 0,
                               "detected_at": T0, "updated_at": T0}]})
    reconcile.reconcile_user(FakeCur(store), 1, {"T1": ExchPos(9, 4.5)})
    halts = [c for c in store["chats"] if "HALTED" in c["content"]]
    assert len(halts) == 1 and "T1" in halts[0]["content"]


def test_clearing_a_halt_announces_the_resume():
    store = _store(book={1: [{"ticker": "T1", "side": "yes", "qty": 9}]},
                   recon={1: [{"ticker": "T1", "kind": UNTRACKED, "exchange_qty": 9, "book_qty": 0,
                               "detected_at": T0, "updated_at": T1}]})
    reconcile.reconcile_user(FakeCur(store), 1, {"T1": ExchPos(9, 4.5)})
    assert any("resumed" in c["content"] for c in store["chats"])
    assert store["resolves"]  # the open row is resolved, which is what lifts the engine's halt


def test_operator_account_counts_the_legacy_engines_positions():
    """The legacy engine's live_positions sit on the operator's Kalshi account. A Tau
    user trading that same account must not see them as untracked (and get halted)."""
    store = _store(book={1: []})
    store["legacy"] = [{"ticker": "T9", "side": "yes", "qty": 3}]
    out = reconcile.reconcile_user(FakeCur(store), 1, {"T9": ExchPos(3, 1.5)}, include_legacy=True)
    assert out == []
    out = reconcile.reconcile_user(FakeCur(store), 1, {"T9": ExchPos(3, 1.5)})
    assert [d.kind for d in out] == [UNTRACKED]


def test_only_the_operator_key_includes_the_legacy_book(monkeypatch):
    store = _store(users=[1, 2], book={1: [], 2: []})
    store["legacy"] = [{"ticker": "T9", "side": "yes", "qty": 3}]
    conn = FakeConn(FakeCur(store))
    monkeypatch.setattr(reconcile, "OPERATOR_KEY_ID", "op-key")
    keys = {1: {"key_id": "op-key"}, 2: {"key_id": "someone-else"}}
    monkeypatch.setattr(reconcile.repo, "get_kalshi_key", lambda c, uid: keys[uid])
    import app.adapters.kalshi.kalshi_account as ka
    monkeypatch.setattr(ka, "credentials_from_row", lambda uid, row: uid)
    monkeypatch.setattr(reconcile, "exchange_positions", lambda creds: {"T9": ExchPos(3, 1.5)})
    reconcile.reconcile_all(conn)
    assert [u["user_id"] for u in store.get("upserts", [])] == [2]


def test_users_to_reconcile_includes_recently_flat_and_open_discrepancy_users():
    """A sell booked against nothing leaves the book flat and the account short, so a
    user with no open position must still be checked."""
    from app import repository as repo

    seen = {}

    class Cur:
        def execute(self, sql, params=()):
            seen["sql"] = " ".join(sql.split())
            seen["params"] = params

        def fetchall(self):
            return [{"user_id": 7}]

    assert repo.users_to_reconcile(Cur()) == [7]
    assert "p.closed_at >= %s" in seen["sql"] and "app_position_reconcile" in seen["sql"]
