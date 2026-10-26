"""Page error reports (POST /api/client-errors) and their admin readout: validation, the body cap, the
rate limit, the CSRF header, signed-out reports, the bounded table, and admin-only reading.
No database: the repository is stubbed here; tests/test_client_errors_db.py runs it on MySQL."""
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
import requests

from app import client_errors, server
from app.adapters.db import client_error_repository as ce_repo

GOOD = {"kind": "error", "message": "TypeError: x is undefined", "src": "app.js", "line": 12, "col": 5,
        "path": "/strategies/:id", "theme": "meridian", "ver": "9fea608a94"}


# -- cleaning ---------------------------------------------------------------------------------


def test_a_good_report_keeps_exactly_its_fields():
    assert client_errors.clean(dict(GOOD, user_id=9, email="a@b.co", body={"x": 1})) == GOOD


@pytest.mark.parametrize("body", [{}, {"kind": "error"}, {"kind": "nope", "message": "m"}, {"kind": "error", "message": ""},
                                  {"kind": "error", "message": 42}, {"kind": "error", "message": ["m"]},
                                  {"kind": ["error"], "message": "m"}, {"kind": "error", "message": "   "}])
def test_a_report_that_is_not_one_is_refused(body):
    with pytest.raises(ValueError):
        client_errors.clean(body)


def test_every_field_is_bounded_and_nothing_personal_survives():
    r = client_errors.clean({
        "kind": "rejection",
        "message": "Failed /api/runs?user=a@b.co&key=1 for jane.doe+x@gmail.com sk_live_4eC39HqLyjWDarjtT1zdp7dc "
                   "card 4242424242424242\n\t" + "word " * 200,
        "src": "https://tau.example/static/app.meridian.js?v=abc#frag", "line": 10**9, "col": True,
        "path": "/research/123/x?email=a@b.co#top", "theme": "dark", "ver": "<script>",
    })
    assert r["message"].startswith("Failed /api/runs for <email> <redacted> card <n> word word")
    assert len(r["message"]) == client_errors.MESSAGE_MAX
    assert "a@b.co" not in r["message"] and "gmail" not in r["message"] and "4242" not in r["message"]
    assert r["src"] == "app.meridian.js"
    assert r["line"] is None and r["col"] is None
    assert r["path"] == "/research/:id/x"
    assert r["theme"] == "" and r["ver"] == ""


@pytest.mark.parametrize("path,expect", [("", "?"), ("strategies", "?"), ("/", "/"), ("/a b<c>", "/abc"),
                                         ("/" + "x" * 500, "/" + "x" * (client_errors.PATH_MAX - 1))])
def test_the_page_path_is_a_route_only(path, expect):
    assert client_errors.page_path(path) == expect


def test_a_script_name_that_is_not_a_plain_file_name_is_dropped():
    assert client_errors.clean(dict(GOOD, src="javascript:alert(1) <x>"))["src"] == ""
    assert client_errors.clean(dict(GOOD, src=None))["src"] == ""


# -- the rate limit ----------------------------------------------------------------------------


def test_the_limit_is_per_source_and_global_and_slides():
    lim = client_errors.RateLimiter(per_key=2, global_max=3, window_s=60)
    assert lim.allow(["ip:a"], now=0) and lim.allow(["ip:a"], now=1)
    assert not lim.allow(["ip:a"], now=2)                    # a's own limit
    assert lim.allow(["ip:b"], now=3)
    assert not lim.allow(["ip:c"], now=4)                    # everyone together
    assert lim.allow(["ip:a"], now=61.5)                     # the window slid past a's first two


def test_a_session_and_an_address_are_both_counted():
    lim = client_errors.RateLimiter(per_key=1, global_max=100, window_s=60)
    assert lim.allow(["ip:a", "s:1"], now=0)
    assert not lim.allow(["ip:b", "s:1"], now=1)             # same session from another address
    assert not lim.allow(["ip:a"], now=2)                    # same address signed out


def test_a_spray_of_addresses_cannot_grow_the_limiter_without_bound():
    lim = client_errors.RateLimiter(per_key=5, global_max=10**6, window_s=60, max_keys=50)
    for i in range(500):
        lim.allow(["ip:%d" % i], now=i * 0.001)
    assert len(lim._hits) <= 51


def test_the_address_is_the_peer_unless_the_peer_is_a_proxy():
    def h(peer, fwd=None):
        return SimpleNamespace(client_address=(peer, 1), headers={"X-Forwarded-For": fwd} if fwd else {})
    assert client_errors.client_ip(h("8.8.8.8", "1.2.3.4")) == "8.8.8.8"   # a client can't pick its bucket
    assert client_errors.client_ip(h("127.0.0.1", "6.6.6.6, 198.51.100.7")) == "198.51.100.7"
    assert client_errors.client_ip(h("10.0.0.2")) == "10.0.0.2"


# -- the bounded table (statements only; the real prune runs in test_client_errors_db.py) ------


class Cur:
    def __init__(self, lastrowid=1, rows=()):
        self.sql, self.lastrowid, self.rows = [], lastrowid, list(rows)

    def execute(self, sql, params=()):
        self.sql.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


def test_an_insert_prunes_by_age_and_keeps_only_the_newest_rows():
    cur = Cur(lastrowid=5003)
    assert ce_repo.insert_client_error(cur, GOOD, signed_in=False, keep_rows=5000) == 5003
    ins, by_id, by_age = cur.sql
    assert ins[0].startswith("INSERT INTO app_client_errors") and ins[1][-1] == 0
    assert by_id == ("DELETE FROM app_client_errors WHERE id <= %s", (3,))
    assert by_age[0] == "DELETE FROM app_client_errors WHERE created_at < %s"
    small = Cur(lastrowid=4)
    ce_repo.insert_client_error(small, GOOD, signed_in=True)
    assert [s for s, _ in small.sql if "id <=" in s] == [] and small.sql[0][1][-1] == 1


def test_groups_read_bytes_and_drop_an_empty_position():
    cur = Cur(rows=[{"kind": "api", "message": "GET /api/x failed (500)", "path": "/", "n": 2, "signed_out": 1,
                     "first_seen": None, "last_seen": None, "themes": b"meridian,tau", "versions": None, "at": ":0:0"}])
    (g,) = ce_repo.client_error_groups(cur)
    assert g["themes"] == ["meridian", "tau"] and g["versions"] == [] and g["at"] == "" and g["n"] == 2


# -- the endpoint --------------------------------------------------------------------------------


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    monkeypatch.setattr(server.repo, "session_user",
                        lambda cur, token: {"id": 7, "email": "someone@example.com"} if token else None)
    stored = []
    monkeypatch.setattr(server.repo, "insert_client_error",
                        lambda cur, report, signed_in: stored.append((report, signed_in)) or 1)
    monkeypatch.setattr(client_errors, "LIMITER", client_errors.RateLimiter(per_key=3, global_max=100, window_s=600))
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield SimpleNamespace(base="http://127.0.0.1:%s" % http.server_port,
                          url="http://127.0.0.1:%s/api/client-errors" % http.server_port, stored=stored)
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)


def test_route_is_a_post_open_to_signed_out_visitors():
    rows = [r for r in server.ROUTES if r[1].pattern == "^/api/client-errors$"]
    assert [(r[0], r[2], r[3]) for r in rows] == [("POST", server.report_client_error, False)]


def test_a_signed_out_page_can_report(web):
    r = requests.post(web.url, json=GOOD, headers={"X-Recursive": "1"}, timeout=2)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert web.stored == [(GOOD, False)]


def test_a_signed_in_report_stores_only_that_it_was_signed_in(web):
    r = requests.post(web.url, json=dict(GOOD, user_id=99), timeout=2,
                      headers={"X-Recursive": "1", "Cookie": "rsid=synthetic-session"})
    assert r.status_code == 200
    (report, signed_in), = web.stored
    assert signed_in is True and report == GOOD  # no user id, email or address


def test_needs_the_csrf_header(web):
    r = requests.post(web.url, json=GOOD, timeout=2)
    assert r.status_code == 403 and not web.stored
    r = requests.post(web.url, data="kind=error&message=x", timeout=2,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})  # what a cross-site form sends
    assert r.status_code == 403 and not web.stored


def test_a_body_over_the_cap_is_refused_before_it_is_read(web):
    big = dict(GOOD, message="x " * client_errors.MAX_BODY)
    r = requests.post(web.url, json=big, headers={"X-Recursive": "1"}, timeout=2)
    assert r.status_code == 413 and not web.stored
    # The same body is fine on a route with the normal cap: the small cap is this route's alone.
    assert server.BODY_LIMITS == {"/api/client-errors": client_errors.MAX_BODY} and server.MAX_BODY > client_errors.MAX_BODY


@pytest.mark.parametrize("body,status", [(b"{not json", 400), (b"[1,2]", 400), (b'{"kind":"bad","message":"m"}', 400),
                                         (b'{"kind":"error"}', 400)])
def test_a_malformed_report_is_refused(web, body, status):
    r = requests.post(web.url, data=body, headers={"X-Recursive": "1", "Content-Type": "application/json"}, timeout=2)
    assert r.status_code == status and not web.stored


def test_the_rate_limit_answers_429_and_stores_nothing_more(web):
    codes = [requests.post(web.url, json=dict(GOOD, message="m%d" % i), headers={"X-Recursive": "1"}, timeout=2).status_code
             for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert len(web.stored) == 3


# -- the admin readout -----------------------------------------------------------------------------


def _admin_ctx(email, cur):
    conn = SimpleNamespace(cursor=lambda: cur)
    return server.Ctx(conn, {"id": 1, "email": email}, (), {}, {}, None)


def test_the_readout_is_admin_only(monkeypatch):
    called = []
    monkeypatch.setattr(server.repo, "client_error_groups", lambda cur: called.append(1) or [])
    with pytest.raises(server.ApiError) as e:
        server.admin_overview(_admin_ctx("someone@example.com", Cur()))
    assert e.value.status == 403 and not called


def test_the_admin_sees_the_groups(monkeypatch):
    groups = [{"kind": "error", "message": "m", "path": "/", "n": 2}]
    monkeypatch.setattr(server.repo, "client_error_groups", lambda cur: groups)
    monkeypatch.setattr(server.repo, "orphaned_open_positions", lambda cur: {"total": 0, "users": 0, "by_mode": {}})
    out = server.admin_overview(_admin_ctx(server.ADMIN_EMAIL.upper(), Cur()))
    assert out["client_errors"] == groups


def test_admin_over_http_needs_a_session_and_the_admin(web, monkeypatch):
    monkeypatch.setattr(server.repo, "client_error_groups", lambda cur: [{"message": "secret"}])
    assert requests.get(web.base + "/api/admin", timeout=2).status_code == 401
    r = requests.get(web.base + "/api/admin", headers={"Cookie": "rsid=synthetic-session"}, timeout=2)
    assert r.status_code == 403 and "secret" not in r.text
