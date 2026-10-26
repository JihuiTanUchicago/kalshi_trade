"""GET /api/runs/example: the id of the user's seeded example session, which /example opens. The runs
list holds only the newest 50 sessions, so /example used to land on /research for a user with more.
The real SQL is covered in test_app_engine_db.py (APP_TEST_MYSQL=1)."""
from types import SimpleNamespace

from app import server


class OneRowCursor:
    def __init__(self, row):
        self.row, self.log = row, []

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.row


def _ctx(cur, uid=7):
    return server.Ctx(SimpleNamespace(cursor=lambda: cur), {"id": uid}, (), {}, {}, None)


def _route(method, path):
    return next((fn for meth, pat, fn, needs in server.ROUTES if meth == method and pat.match(path)), None)


def test_the_example_route_is_its_own_and_needs_a_session():
    assert _route("GET", "/api/runs/example") is server.example_run
    assert _route("GET", "/api/runs/41") is server.get_run  # a run by id still reads as before
    assert _route("GET", "/api/runs") is server.list_runs
    assert next(needs for meth, pat, fn, needs in server.ROUTES if fn is server.example_run) is True


def test_it_answers_the_example_id_in_one_read_scoped_to_the_user():
    cur = OneRowCursor({"id": 3})
    assert server.example_run(_ctx(cur)) == {"id": 3}
    assert len(cur.log) == 1
    sql, params = cur.log[0]
    assert "FROM app_agent_runs WHERE user_id=%s AND kind='research' AND direction=%s" in sql
    assert "ORDER BY id DESC LIMIT 1" in sql and params == (7, server.repo.DEMO_DIRECTION)


def test_no_example_session_answers_none():
    # A user who has none (or deleted it): /example falls back to /research.
    assert server.example_run(_ctx(OneRowCursor(None))) == {"id": None}
