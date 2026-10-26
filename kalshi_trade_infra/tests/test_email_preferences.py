"""Settings' email switch: one field (app_users.email_opt_out) that Settings and the unsubscribe link
both write, and every optional email reads before it goes out. Live-money safety alerts (Bitcoin perps
watch) never read it. No SES call is made: every sender here is stubbed."""
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
import requests

from app import agent, kalshi_perps_watch, notify, server


class Cur:
    def __init__(self, rows=()):
        self.rows, self.sql = list(rows), []
        self.rowcount = 1

    def execute(self, sql, params=()):
        self.sql.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.rows


def ctx(user, body=None, query=None, cur=None):
    conn = SimpleNamespace(cursor=lambda: cur or Cur())
    return server.Ctx(conn, user, (), query or {}, body or {}, None)


# -- the endpoint ----------------------------------------------------------------------


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: {"id": 7} if token else None)
    writes = []
    monkeypatch.setattr(server.repo, "set_email_opt_out", lambda cur, uid, off: writes.append((uid, off)) or True)
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield SimpleNamespace(url="http://127.0.0.1:%s/api/email-preferences" % http.server_port, writes=writes,
                          headers={"Cookie": "rsid=synthetic-session", "X-Recursive": "1"})
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)


def test_route_is_a_signed_in_post():
    rows = [r for r in server.ROUTES if r[1].pattern == "^/api/email-preferences$"]
    assert [(r[0], r[2], r[3]) for r in rows] == [("POST", server.set_email_preferences, True)]


def test_signed_in_owner_turns_optional_email_off_and_on(web):
    for off in (True, False):
        r = requests.post(web.url, json={"email_opt_out": off}, headers=web.headers, timeout=2)
        assert r.status_code == 200 and r.json() == {"ok": True, "email_opt_out": off}
    assert web.writes == [(7, True), (7, False)]


def test_a_body_cannot_name_another_user(web):
    r = requests.post(web.url, json={"email_opt_out": True, "user_id": 99, "id": 99}, headers=web.headers, timeout=2)
    assert r.status_code == 200 and web.writes == [(7, True)]  # the session's user, never the body's


def test_needs_the_csrf_header(web):
    r = requests.post(web.url, json={"email_opt_out": True}, headers={"Cookie": web.headers["Cookie"]}, timeout=2)
    assert r.status_code == 403 and not web.writes


def test_needs_a_session(web):
    r = requests.post(web.url, json={"email_opt_out": True}, headers={"X-Recursive": "1"}, timeout=2)
    assert r.status_code == 401 and not web.writes


@pytest.mark.parametrize("value", [None, "true", 1, 0, "off", [True]])
def test_only_a_boolean_is_stored(web, value):
    r = requests.post(web.url, json={"email_opt_out": value}, headers=web.headers, timeout=2)
    assert r.status_code == 400 and not web.writes


def test_missing_user_row_is_an_error_not_a_silent_ok(monkeypatch):
    monkeypatch.setattr(server.repo, "set_email_opt_out", lambda cur, uid, off: False)
    with pytest.raises(server.ApiError) as e:
        server.set_email_preferences(ctx({"id": 3}, {"email_opt_out": True}))
    assert e.value.status == 404


def test_me_reports_the_switch(monkeypatch):
    class Reads:
        def __init__(self, cur, uid):
            pass

        def balance(self):
            return 0.0
    monkeypatch.setattr(server.billing, "Reads", Reads)
    monkeypatch.setattr(server, "_needs_card", lambda c, r: False)
    monkeypatch.setattr(server, "_auto_reload_terms", lambda c, r: None)
    monkeypatch.setattr(server, "_researchable_markets", lambda cur: [])
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: None)
    monkeypatch.setattr(server.repo, "get_kalshi_dev_key", lambda cur, uid: None)
    base = {"id": 3, "email": "a@example.invalid", "name": "A", "picture_url": None, "autopilot": 0}

    class Handler:
        headers = {}
    for stored, said in ((1, True), (0, False), (None, False)):
        c = ctx(dict(base, email_opt_out=stored))
        c.handler = Handler()
        assert server.me(c)["user"]["email_opt_out"] is said


# -- the repository --------------------------------------------------------------------


def test_setting_an_unchanged_value_still_succeeds():
    from app.adapters.db import email_prefs_repository as prefs
    cur = Cur(rows=[{"id": 3}])
    cur.rowcount = 0  # MySQL counts only changed rows: Off saved twice, or a second unsubscribe click
    assert prefs.set_email_opt_out(cur, 3, True) is True
    cur = Cur()
    cur.rowcount = 0
    assert prefs.set_email_opt_out(cur, 404, True) is False  # no such user


def test_optional_address_is_withheld_after_opt_out():
    from app import repository as repo
    assert repo.optional_email_address(Cur([{"email": "a@x.invalid", "email_opt_out": 0}]), 3) == "a@x.invalid"
    assert repo.optional_email_address(Cur([{"email": "a@x.invalid", "email_opt_out": 1}]), 3) is None
    assert repo.optional_email_address(Cur([{"email": "", "email_opt_out": 0}]), 3) is None
    assert repo.optional_email_address(Cur([]), 3) is None


def test_community_digest_query_skips_opted_out_users():
    from app import repository as repo
    cur = Cur()
    repo.community_email_recipients(cur, 1)
    assert "COALESCE(email_opt_out,0)=0" in cur.sql[0][0]


def test_reads_used_by_optional_sends_carry_the_switch():
    from app import repository as repo
    cur = Cur()
    repo.users_by_usernames(cur, ["bob"])
    repo.post_author(cur, 5)
    repo.session_user(cur, "hash")
    assert all("email_opt_out" in sql for sql, _ in cur.sql)


# -- each optional email honours it ----------------------------------------------------


def test_opted_out_mention_gets_the_bell_but_no_email(monkeypatch):
    bells, mails = [], []
    monkeypatch.setattr(server.repo, "users_by_usernames", lambda cur, hs: [
        {"id": 2, "username": "bob", "name": "Bob", "email": "b@x.invalid", "email_opt_out": 1},
        {"id": 3, "username": "cat", "name": "Cat", "email": "c@x.invalid", "email_opt_out": 0}])
    monkeypatch.setattr(server.repo, "add_notification", lambda cur, uid, kind, body, link: bells.append(uid))
    monkeypatch.setattr(server.notify, "mention_notice", lambda to, *a: mails.append(to) or True)
    server._notify_mentions(None, 1, "Me", "hey @bob and @cat", "/community")
    assert sorted(bells) == [2, 3] and mails == ["c@x.invalid"]


@pytest.mark.parametrize("opt_out,emailed", [(1, False), (0, True)])
def test_reply_email_follows_the_post_authors_switch(monkeypatch, opt_out, emailed):
    mails, bells = [], []
    monkeypatch.setattr(server.repo, "post_author", lambda cur, pid: {
        "user_id": 2, "email": "author@x.invalid", "name": "Au", "preview": "p", "email_opt_out": opt_out})
    monkeypatch.setattr(server.repo, "add_comment", lambda *a: 1)
    monkeypatch.setattr(server.repo, "get_user", lambda cur, uid: {"name": "Commenter"})
    monkeypatch.setattr(server.repo, "users_by_usernames", lambda cur, hs: [])
    monkeypatch.setattr(server.repo, "add_notification", lambda cur, uid, kind, body, link: bells.append(uid))
    monkeypatch.setattr(server.notify, "comment_notice", lambda to, *a: mails.append(to) or True)
    c = ctx({"id": 1}, {"body": "nice"})
    c.params = ("5",)
    assert server.create_comment(c) == {"ok": True}
    assert bells == [2] and mails == (["author@x.invalid"] if emailed else [])


@pytest.mark.parametrize("address,emailed", [(None, False), ("t@x.invalid", True)])
def test_ready_for_live_email_reads_the_switch_at_send_time(monkeypatch, address, emailed):
    mails, bells = [], []
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: True)
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid: [
        {"strategy_id": 7, "mode": "paper", "status": "running", "title": "Edge"}])
    monkeypatch.setattr(agent.repo, "chat_contains", lambda *a: False)
    monkeypatch.setattr(agent.repo, "add_chat", lambda *a, **k: None)
    monkeypatch.setattr(agent.repo, "add_notification", lambda cur, uid, kind, body, link=None: bells.append(kind))
    monkeypatch.setattr(agent.repo, "optional_email_address", lambda cur, uid: address)
    monkeypatch.setattr(agent, "paper_evidence", lambda cur, uid, sid: {
        "ready": True, "why": "", "trades": 31, "trades_needed": 30, "net_pnl": 4.2, "span_hours": 50.0,
        "p_value": 0.05, "realization": None})
    monkeypatch.setattr(notify, "live_ready_notice", lambda to, *a: mails.append(to) or True)
    # The user dict the review holds still has an address; the stored switch decides.
    assert len(agent.live_ready_notices(None, {"id": 2, "email": "t@x.invalid", "name": "T"})) == 1
    assert bells == ["live_ready"] and mails == (["t@x.invalid"] if emailed else [])


def test_perps_safety_alerts_ignore_the_switch(monkeypatch):
    """Live-money safety alerts (position mismatch, near liquidation, heavy margin) are not optional:
    an opted-out user still gets them, as the Settings copy says."""
    sent = []
    monkeypatch.setattr(kalshi_perps_watch.repo, "get_user", lambda cur, uid: {
        "id": uid, "email": "p@x.invalid", "email_opt_out": 1})
    monkeypatch.setattr(notify, "_send", lambda to, subject, body, reply_to=None: sent.append((to, subject)) or True)
    kalshi_perps_watch._email(None, 4, "Tau: Bitcoin perps margin alert", "detail")
    assert sent == [("p@x.invalid", "Tau: Bitcoin perps margin alert")]


# -- the unsubscribe link agrees with Settings ------------------------------------------


def test_unsubscribe_page_says_what_stopped_and_points_to_settings(monkeypatch):
    writes = []
    monkeypatch.setattr(server.repo, "set_email_opt_out", lambda cur, uid, off: writes.append((uid, off)) or True)
    kind, page = server.unsubscribe(ctx(None, query={"u": "7", "t": notify.unsubscribe_token(7)}))
    assert kind == "html" and writes == [(7, True)]  # the same field Settings' switch writes
    for said in ("new community posts", "replies", "mentions", "ready for live trading",
                 "Safety alerts about a Bitcoin perps account", "href='/settings'"):
        assert said in page


def test_community_email_carries_a_link_that_flips_the_same_switch(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "_send", lambda to, subject, body, reply_to=None: sent.append(body) or True)
    notify.community_post_notice("a@x.invalid", "A", "B", "hello", notify.unsubscribe_url(7))
    assert notify.unsubscribe_url(7) in sent[0] and "/unsubscribe?u=7&t=" in sent[0]
