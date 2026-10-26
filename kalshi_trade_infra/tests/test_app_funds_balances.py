"""Per-bucket cash + funding: paper add/reset, app-controlled demo capital, and a
mocked (never-networked) live-balance fetch that degrades without a key.

These exercise the repository + accounting layer against a FakeCursor covering only the
exact query shapes the new code runs - the established pattern (see tests/conftest.py), so
the money math is testable without a live MySQL.
"""
import pytest

from app.adapters.kalshi import kalshi_account
from app import repository as repo


class FakeFundsCursor:
    """In-memory stand-in for the app_ledger / app_positions / app_users query shapes used by
    the paper + demo balance code. Extend the dispatch, don't reach for a real DB."""

    def __init__(self):
        self.ledger = []   # dicts: user_id, kind, amount
        self.positions = []  # dicts: user_id, mode, status, pnl
        self.users = {}    # id -> {"demo_capital": float, "demo_pnl_base": float}
        self.lastrowid = None
        self._last = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        p = params or ()
        self._last = None
        if s.startswith("INSERT INTO app_ledger"):
            uid, kind, amount, _pos, memo, ts = p
            self.ledger.append({"user_id": uid, "kind": kind, "amount": float(amount), "memo": memo, "created_at": ts})
        elif s.startswith("SELECT MAX(created_at) AS at FROM app_ledger WHERE user_id=%s AND kind='deposit' AND memo=%s"):
            uid, memo = p
            ats = [r["created_at"] for r in self.ledger if r["user_id"] == uid and r["kind"] == "deposit" and r["memo"] == memo]
            self._last = [{"at": max(ats) if ats else None}]
        elif s.startswith("SELECT COALESCE(SUM(amount),0) AS b FROM app_ledger WHERE user_id=%s AND kind IN"):
            uid = p[0]
            total = sum(r["amount"] for r in self.ledger if r["user_id"] == uid and r["kind"] in ("deposit", "withdrawal"))
            self._last = [{"b": total}]
        elif s.startswith("SELECT COALESCE(SUM(amount),0) AS b FROM app_ledger WHERE user_id=%s"):
            uid = p[0]
            total = sum(r["amount"] for r in self.ledger if r["user_id"] == uid)
            self._last = [{"b": total}]
        elif s.startswith("DELETE FROM app_ledger WHERE user_id=%s"):
            uid = p[0]
            self.ledger = [r for r in self.ledger if r["user_id"] != uid]
        elif s.startswith("SELECT demo_capital, demo_pnl_base FROM app_users WHERE id=%s"):
            u = self.users.get(p[0])
            self._last = [{"demo_capital": u["demo_capital"], "demo_pnl_base": u["demo_pnl_base"]}] if u else []
        elif s.startswith("UPDATE app_users SET demo_capital=%s, demo_pnl_base=%s WHERE id=%s"):
            cap, base, uid = p
            self.users.setdefault(uid, {})["demo_capital"] = float(cap)
            self.users[uid]["demo_pnl_base"] = float(base)
        elif s.startswith("SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions WHERE user_id=%s AND mode=%s AND status='closed'"):
            uid, mode = p[0], p[1]
            total = sum(r["pnl"] for r in self.positions
                        if r["user_id"] == uid and r["mode"] == mode and r["status"] == "closed")
            self._last = [{"p": total}]
        else:
            raise NotImplementedError(f"unhandled SQL: {s[:90]}")

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return self._last or []


# -- paper: add + reset --------------------------------------------------------


def test_paper_add_then_reset_sets_the_balance():
    cur = FakeFundsCursor()
    repo.add_ledger(cur, 1, "deposit", repo.STARTING_PAPER_BALANCE, "Starting paper balance")
    repo.add_ledger(cur, 1, "deposit", 250.0, "Paper deposit")
    assert repo.paper_balance(cur, 1) == 1250.0
    # Reset wipes the ledger and starts fresh at the target, so the balance IS the target.
    repo.reset_paper_account(cur, 1, 500.0)
    assert repo.paper_balance(cur, 1) == 500.0
    assert repo.paper_deposits(cur, 1) == 500.0  # ROI denominator resets too


def test_paper_reset_at_marks_where_the_equity_pnl_restarts():
    # The dashboard's paper total_pnl (equity - deposits) restarts at a reset, so its label reads
    # "since reset" instead of "all time" once this is set; deposits and withdrawals don't set it.
    cur = FakeFundsCursor()
    repo.add_ledger(cur, 1, "deposit", repo.STARTING_PAPER_BALANCE, "Starting paper balance")
    repo.add_ledger(cur, 1, "deposit", 250.0, "Paper deposit")
    assert repo.paper_reset_at(cur, 1) is None
    repo.reset_paper_account(cur, 1, 500.0)
    at = repo.paper_reset_at(cur, 1)
    assert at is not None and at == cur.ledger[-1]["created_at"]
    assert repo.paper_reset_at(cur, 2) is None  # per user


def test_paper_reset_is_isolated_per_user():
    cur = FakeFundsCursor()
    repo.add_ledger(cur, 1, "deposit", 1000.0, "u1")
    repo.add_ledger(cur, 2, "deposit", 1000.0, "u2")
    repo.reset_paper_account(cur, 1, 50.0)
    assert repo.paper_balance(cur, 1) == 50.0
    assert repo.paper_balance(cur, 2) == 1000.0  # untouched


# -- demo: app-controlled capital, P&L applied against it ----------------------


def test_demo_equity_applies_realized_pnl_to_app_set_capital():
    cur = FakeFundsCursor()
    cur.users[1] = {"demo_capital": 1000.0, "demo_pnl_base": 0.0}
    cur.positions += [
        {"user_id": 1, "mode": "demo", "status": "closed", "pnl": 40.0},
        {"user_id": 1, "mode": "demo", "status": "closed", "pnl": -15.0},
        {"user_id": 1, "mode": "demo", "status": "open", "pnl": None},
    ]
    de = repo.demo_equity(cur, 1)
    assert de["capital"] == 1000.0
    assert de["realized"] == 25.0            # 40 - 15, open ignored
    assert de["equity"] == 1025.0            # capital + realized
    assert de["roi"] == round(25.0 / 1000.0, 4)
    assert de["before_reload"] == 0.0        # never reloaded: the shown P&L is every closed demo trade


def test_demo_reload_sets_capital_and_zeroes_displayed_pnl():
    cur = FakeFundsCursor()
    cur.users[1] = {"demo_capital": 1000.0, "demo_pnl_base": 0.0}
    cur.positions.append({"user_id": 1, "mode": "demo", "status": "closed", "pnl": 40.0})
    # Reload to $500: capital becomes 500 and the realized snapshot becomes the new baseline,
    # so displayed P&L reads flat right after reload (real fills accrue from here).
    repo.reload_demo(cur, 1, 500.0)
    assert cur.users[1]["demo_capital"] == 500.0
    assert cur.users[1]["demo_pnl_base"] == 40.0
    de = repo.demo_equity(cur, 1)
    assert de["capital"] == 500.0
    assert de["realized"] == 0.0
    assert de["equity"] == 500.0
    assert de["before_reload"] == 40.0  # what the "since reload" figure leaves out
    # A new fill after the reload accrues against the fresh capital.
    cur.positions.append({"user_id": 1, "mode": "demo", "status": "closed", "pnl": 12.0})
    assert repo.demo_equity(cur, 1)["equity"] == 512.0


def test_demo_equity_defaults_when_user_row_missing():
    cur = FakeFundsCursor()  # no users seeded
    de = repo.demo_equity(cur, 99)
    assert de["capital"] == round(repo.STARTING_PAPER_BALANCE, 2)
    assert de["equity"] == round(repo.STARTING_PAPER_BALANCE, 2)


# -- live balance: mocked fetch, cached, graceful ------------------------------


def test_balance_cached_memoizes_within_ttl(monkeypatch):
    calls = {"n": 0}

    def fake_balance(creds):
        calls["n"] += 1
        return 321.0

    monkeypatch.setattr(kalshi_account, "balance", fake_balance)
    kalshi_account._BALANCE_CACHE.pop(777, None)
    assert kalshi_account.balance_cached(777, ("kid", object())) == 321.0
    assert kalshi_account.balance_cached(777, ("kid", object())) == 321.0
    assert calls["n"] == 1  # second read served from the memo, no second network call


def test_balance_cached_degrades_to_none_on_failure(monkeypatch):
    def boom(creds):
        raise RuntimeError("kalshi unreachable")

    monkeypatch.setattr(kalshi_account, "balance", boom)
    kalshi_account._BALANCE_CACHE.pop(778, None)
    assert kalshi_account.balance_cached(778, ("kid", object())) is None


def test_live_balance_degrades_without_a_key(monkeypatch):
    from app import server

    monkeypatch.setattr(repo, "get_kalshi_key", lambda cur, uid: None)
    out = server._live_balance(object(), 5)
    assert out["connected"] is False
    assert out["balance"] is None
    assert out["funding_url"] == kalshi_account.KALSHI_FUNDING_URL


def test_live_balance_surfaces_cached_value_when_connected(monkeypatch):
    from app import server

    monkeypatch.setattr(repo, "get_kalshi_key", lambda cur, uid: {"key_id": "abcd1234", "private_key_enc": b""})
    monkeypatch.setattr(kalshi_account, "credentials_from_row", lambda uid, row: ("abcd1234", object()))
    monkeypatch.setattr(kalshi_account, "balance_cached", lambda uid, creds: 150.25)
    out = server._live_balance(object(), 5)
    assert out["connected"] is True
    assert out["balance"] == 150.25


# -- Funds: how old the live figure is, and what each book has open ----------


def test_balance_read_at_dates_the_memo_and_never_reads_kalshi(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(kalshi_account, "balance", lambda creds: (_ for _ in ()).throw(AssertionError("no read")))
    kalshi_account._BALANCE_CACHE.pop(779, None)
    assert kalshi_account.balance_read_at(779) is None  # nothing memoized: no time to show
    kalshi_account._BALANCE_CACHE[779] = (kalshi_account.time.monotonic() - 40, 12.0)
    at = kalshi_account.balance_read_at(779)
    age = (datetime.now(timezone.utc).replace(tzinfo=None) - at).total_seconds()
    assert at.tzinfo is None and 38 <= age <= 45, age  # naive UTC, as the API's other times
    kalshi_account._BALANCE_CACHE.pop(779, None)


def test_live_balance_says_when_it_was_read_only_when_it_was(monkeypatch):
    from app import server

    monkeypatch.setattr(repo, "get_kalshi_key", lambda cur, uid: {"key_id": "abcd1234", "private_key_enc": b""})
    monkeypatch.setattr(kalshi_account, "credentials_from_row", lambda uid, row: ("abcd1234", object()))
    monkeypatch.setattr(kalshi_account, "balance_read_at", lambda uid: "T")
    monkeypatch.setattr(kalshi_account, "balance_cached", lambda uid, creds: 150.25)
    assert server._live_balance(object(), 5)["balance_at"] == "T"
    monkeypatch.setattr(kalshi_account, "balance_cached", lambda uid, creds: None)  # Kalshi didn't answer
    assert "balance_at" not in server._live_balance(object(), 5)


def test_funds_dates_the_demo_balance_from_its_memo_and_never_reads_kalshi_for_it(monkeypatch):
    """The demo key line says when its balance was read, from the demo memo's own fill time; a balance
    that couldn't be read carries no time, and dating it never makes another demo read."""
    from datetime import datetime, timezone

    from app import server
    from app.trading import demo_twins

    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: None)
    monkeypatch.setattr(server.repo, "get_kalshi_dev_key", lambda cur, uid: {"key_id": "DEVKEY-1234"})
    monkeypatch.setattr(server.repo, "demo_equity", lambda cur, uid: {"capital": 1000, "equity": 1000, "realized": 0,
                                                                       "before_reload": 0})
    monkeypatch.setattr(server.repo, "paper_balance", lambda cur, uid: 1000)
    monkeypatch.setattr(server.repo, "ledger_rows", lambda cur, uid: [])
    monkeypatch.setattr(server.repo, "user_positions", lambda cur, uid, status: [])
    monkeypatch.setattr(demo_twins, "_read_balance", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no read")))

    class Ctx:
        cur, uid = object(), 781

    demo_twins._BALANCE_CACHE[781] = (demo_twins.time.monotonic() - 40, 25.0)  # read 40s ago
    dev = server.funds(Ctx())["kalshi_dev"]
    age = (datetime.now(timezone.utc).replace(tzinfo=None) - dev["balance_at"]).total_seconds()
    assert dev["balance"] == 25.0 and 38 <= age <= 45, age
    demo_twins._BALANCE_CACHE[781] = (demo_twins.time.monotonic(), None)  # the demo API didn't answer
    assert "balance_at" not in server.funds(Ctx())["kalshi_dev"]
    demo_twins._BALANCE_CACHE.pop(781, None)
    assert demo_twins.balance_read_at(781) is None  # nothing memoized: no time to show


def test_funds_names_each_books_open_positions_and_paper_matches_the_dashboard(monkeypatch):
    """Funds' paper figure is the dashboard's (cash + open at cost), and every book reports only its own
    open positions: a live, a demo and two paper positions never land in another book's count."""
    from app import server

    pos = [{"mode": "live", "qty": 10, "entry_price": 0.40}, {"mode": "demo", "qty": 5, "entry_price": 0.61},
           {"mode": "paper", "qty": 12, "entry_price": 0.42}, {"mode": "paper", "qty": 5, "entry_price": 0.61}]
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: None)
    monkeypatch.setattr(server.repo, "get_kalshi_dev_key", lambda cur, uid: None)
    monkeypatch.setattr(server.repo, "demo_equity", lambda cur, uid: {"capital": 750.0, "equity": 753.77, "realized": 3.77,
                                                                       "before_reload": 0})
    monkeypatch.setattr(server.repo, "paper_balance", lambda cur, uid: 2001.74)
    monkeypatch.setattr(server.repo, "ledger_rows", lambda cur, uid: [])
    monkeypatch.setattr(server.repo, "user_positions", lambda cur, uid, status: pos)

    class Ctx:
        cur, uid = object(), 1

    out = server.funds(Ctx())
    assert (out["kalshi"]["open_positions"], out["kalshi"]["open_at_cost"]) == (1, 4.0)
    assert (out["demo"]["open_positions"], out["demo"]["open_at_cost"]) == (1, 3.05)
    assert (out["paper"]["open_positions"], out["paper"]["open_at_cost"]) == (2, 8.09)
    assert out["paper"]["cash"] == 2001.74 and out["paper"]["equity"] == 2009.83
    assert out["demo"]["equity"] == 753.77  # demo's own figure, untouched by paper or live
    # The dashboard's buckets read the same helper, so the two pages agree to the cent.
    assert server._open_book(pos, "paper") == {"open_at_cost": 8.09, "open_positions": 2}
