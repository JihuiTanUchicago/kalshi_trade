"""Page error reports against a real MySQL: the table app.schema creates, the prune on insert (by row
count and by age), and the admin readout's groups by message and page over the last 24 hours.
Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


def _report(message="TypeError: x is undefined", path="/strategies/:id", theme="tau", ver="aaa111", **kw):
    return dict({"kind": "error", "message": message, "src": "app.js", "line": 12, "col": 5,
                 "path": path, "theme": theme, "ver": ver}, **kw)


@pytest.fixture
def cur():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("DELETE FROM app_client_errors")
    yield c
    c.execute("DELETE FROM app_client_errors")
    conn.close()


def _count(cur):
    cur.execute("SELECT COUNT(*) AS n FROM app_client_errors")
    return cur.fetchone()["n"]


def test_the_table_holds_no_personal_columns(cur):
    cur.execute("SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='app_client_errors'")
    cols = {r["c"] for r in cur.fetchall()}
    assert cols == {"id", "created_at", "kind", "message", "src", "line", "col", "path", "theme", "ver", "signed_in"}


def test_insert_keeps_only_the_newest_rows(cur):
    from app import repository as repo

    ids = [repo.insert_client_error(cur, _report(message="bug %d" % i), signed_in=False, keep_rows=3) for i in range(7)]
    assert _count(cur) == 3
    cur.execute("SELECT id, message FROM app_client_errors ORDER BY id")
    assert [(r["id"], r["message"]) for r in cur.fetchall()] == [(ids[i], "bug %d" % i) for i in (4, 5, 6)]


def test_insert_prunes_rows_older_than_a_week(cur):
    from app import repository as repo

    old = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(days=8)
    cur.execute("INSERT INTO app_client_errors (created_at, kind, message, path) VALUES (%s,'error','old','/')", (old,))
    repo.insert_client_error(cur, _report(), signed_in=True)
    cur.execute("SELECT message, signed_in FROM app_client_errors")
    assert [(r["message"], r["signed_in"]) for r in cur.fetchall()] == [("TypeError: x is undefined", 1)]


def test_groups_by_message_and_page_over_the_last_day(cur, monkeypatch):
    from app import repository as repo
    from app.adapters.db import client_error_repository as mod

    t0 = datetime(2026, 10, 26, 8, 0, 0)
    clock = {"now": t0}
    monkeypatch.setattr(mod, "now_utc", lambda: clock["now"])
    for minutes, rep, signed_in in [
        (0, _report(theme="tau", ver="aaa111"), True),
        (10, _report(theme="meridian", ver="bbb222", line=40), False),
        (20, _report(path="/deploy"), True),                                    # same message, another page
        (30, _report(kind="api", message="GET /api/dashboard failed (500)", src="", line=None, col=None, path="/"), False),
    ]:
        clock["now"] = t0 + timedelta(minutes=minutes)
        repo.insert_client_error(cur, rep, signed_in=signed_in)
    clock["now"] = t0 - timedelta(hours=30)
    repo.insert_client_error(cur, _report(message="yesterday's bug"), signed_in=True)  # kept (< a week), but not in 24h

    clock["now"] = t0 + timedelta(hours=1)
    groups = repo.client_error_groups(cur)
    assert [(g["kind"], g["message"], g["path"], g["n"]) for g in groups] == [
        ("api", "GET /api/dashboard failed (500)", "/", 1),
        ("error", "TypeError: x is undefined", "/deploy", 1),
        ("error", "TypeError: x is undefined", "/strategies/:id", 2),
    ]
    api, _, strat = groups
    assert strat["first_seen"] == t0 and strat["last_seen"] == t0 + timedelta(minutes=10)
    assert strat["themes"] == ["meridian", "tau"] and strat["versions"] == ["bbb222", "aaa111"]  # newest build first
    assert strat["signed_out"] == 1 and strat["at"] == "app.js:40:5"   # the newest one's position
    assert api["at"] == "" and api["signed_out"] == 1
    assert _count(cur) == 5
