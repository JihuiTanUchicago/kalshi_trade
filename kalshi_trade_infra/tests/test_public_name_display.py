"""How one customer is named to another outside the feed (walk 2026-10-31): a strategy shared with you says who
shared it as the community names them, never their email address, and /api/me tells Settings the name other people
see. No database: the reads are stubbed."""
from types import SimpleNamespace

from app import server
from app.adapters.db import strategy_repository
from app.web.routes import account as account_routes
from app.web.routes import strategies as strategy_routes


def _shared(**row):
    return strategy_routes._shared_from({"shared_from_user_id": 7, **row})


def test_shared_from_is_the_sharers_name_as_the_community_shows_it():
    assert _shared(shared_from_name="Pat Prolific", shared_from_username="prolific") == "Pat Prolific"
    assert _shared(shared_from_name="مريم العلي 🚀", shared_from_username="maryam") == "مريم العلي 🚀"
    # A Google profile named by its address: the recipient read that address.
    assert _shared(shared_from_name="dana.private@example.com", shared_from_username="danaprivate") == "@danaprivate"
    assert _shared(shared_from_name="Dana <dana.private@example.com>", shared_from_username="danaprivate") == "@danaprivate"
    # No name at all: the "Shared by" line was left out.
    assert _shared(shared_from_name=None, shared_from_username="freshperson") == "@freshperson"
    assert _shared(shared_from_name="  ", shared_from_username="freshperson") == "@freshperson"
    # The sharer's account is gone (the join found no row).
    assert _shared(shared_from_name=None, shared_from_username=None) == "another trader"
    # Not a shared copy.
    assert strategy_routes._shared_from({"shared_from_user_id": None, "shared_from_name": "X"}) is None


def test_strategy_card_carries_it():
    s = {"id": 1, "run_id": None, "parent_id": None, "market": "btc_daily", "direction": "custom", "title": "T",
         "thesis": "", "status": "passed", "created_at": None, "spec": {"side": "yes"}, "result": {},
         "shared_from_user_id": 7, "shared_from_name": "dana.private@example.com", "shared_from_username": "danaprivate"}
    assert strategy_routes._strategy_card(s)["shared_from"] == "@danaprivate"


class Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append(" ".join(sql.split()))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_both_strategy_reads_select_the_sharers_handle():
    cur = Cur()
    strategy_repository.get_strategy(cur, 1, 2)
    assert "su.username AS shared_from_username" in cur.sql[-1]
    cur = Cur()
    try:
        strategy_repository.list_strategies(cur, 1)
    except Exception:
        pass  # only the SQL it sent matters here
    assert any("su.username AS shared_from_username" in q for q in cur.sql)


def test_me_says_the_name_other_people_see(monkeypatch):
    class Reads:
        def __init__(self, cur, uid):
            pass

        def balance(self):
            return 0.0
    monkeypatch.setattr(server.billing, "Reads", Reads)
    monkeypatch.setattr(account_routes, "_needs_card", lambda c, r: False)
    monkeypatch.setattr(account_routes, "_auto_reload_terms", lambda c, r: None)
    monkeypatch.setattr(account_routes, "_researchable_markets", lambda cur: [])
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: None)
    monkeypatch.setattr(server.repo, "get_kalshi_dev_key", lambda cur, uid: None)
    base = {"id": 3, "email": "a@example.invalid", "picture_url": None, "autopilot": 0, "username": "a"}
    for name, shown in (("Ada", "Ada"), (None, "Trader"), ("a@example.invalid", "Trader"), ("  ", "Trader")):
        c = server.Ctx(SimpleNamespace(cursor=lambda: Cur()), dict(base, name=name), (), {}, {}, None)
        c.handler = SimpleNamespace(headers={})
        assert server.me(c)["user"]["public_name"] == shown
