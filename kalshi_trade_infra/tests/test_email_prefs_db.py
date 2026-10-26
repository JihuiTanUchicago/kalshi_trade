"""Settings' email switch against a real MySQL: Settings and the unsubscribe link write the same
app_users.email_opt_out, /api/me reads it back, and every optional send's read honours it. MySQL
counts only changed rows, so saving a value that is already stored must still succeed (a second
click on an unsubscribe link used to say the link was invalid). Opt in as for test_app_engine_db.py
(APP_TEST_MYSQL=1). No email is sent: nothing here calls a sender.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def _user(cur, repo, name):
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "%s-%s@example.com" % (name, uuid.uuid4().hex[:6]),
                                  name, None)["id"]
    return uid


def test_settings_and_unsubscribe_share_one_switch(conn):
    from app import server
    from app.adapters.ses import notify
    from app.web import auth
    from app import repository as repo

    cur = conn.cursor()
    uid = _user(cur, repo, "mailer")
    token = uuid.uuid4().hex
    repo.create_session(cur, uid, auth.hash_token(token), server.timedelta(hours=1))
    user = lambda: repo.session_user(cur, auth.hash_token(token))  # noqa: E731 - what each request sees
    ctx = lambda body=None, query=None: server.Ctx(conn, user(), (), query or {}, body or {}, None)  # noqa: E731

    assert not user()["email_opt_out"] and repo.optional_email_address(cur, uid)
    assert server.set_email_preferences(ctx({"email_opt_out": True})) == {"ok": True, "email_opt_out": True}
    assert user()["email_opt_out"] and repo.optional_email_address(cur, uid) is None
    # Off saved twice changes no row; it must still succeed, and so must the link afterwards.
    assert server.set_email_preferences(ctx({"email_opt_out": True}))["email_opt_out"] is True
    for _ in range(2):
        kind, page = server.unsubscribe(ctx(query={"u": str(uid), "t": notify.unsubscribe_token(uid)}))
        assert "You're unsubscribed" in page
    assert server.set_email_preferences(ctx({"email_opt_out": False}))["email_opt_out"] is False
    assert not user()["email_opt_out"] and repo.optional_email_address(cur, uid)
    server.unsubscribe(ctx(query={"u": str(uid), "t": notify.unsubscribe_token(uid)}))
    assert user()["email_opt_out"]  # the link turns Settings' switch off


def test_optional_sends_skip_an_opted_out_user(conn):
    from app import repository as repo

    cur = conn.cursor()
    author = _user(cur, repo, "author")
    off, on = _user(cur, repo, "off"), _user(cur, repo, "on")
    names = {}
    for uid in (off, on):
        names[uid] = "u" + uuid.uuid4().hex[:10]
        cur.execute("UPDATE app_users SET username=%s, last_community_email_at=NULL WHERE id=%s", (names[uid], uid))
    assert repo.set_email_opt_out(cur, off, True)

    recipients = {r["id"] for r in repo.community_email_recipients(cur, author)}
    assert on in recipients and off not in recipients
    flags = {u["id"]: bool(u["email_opt_out"]) for u in repo.users_by_usernames(cur, list(names.values()))}
    assert flags == {off: True, on: False}
    pid = repo.create_post(cur, off, "hello", "note", None, None)
    assert repo.post_author(cur, pid)["email_opt_out"]


def test_unknown_user_is_reported(conn):
    from app import repository as repo

    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(id), 0) + 1000 AS n FROM app_users")
    assert repo.set_email_opt_out(cur, cur.fetchone()["n"], True) is False
