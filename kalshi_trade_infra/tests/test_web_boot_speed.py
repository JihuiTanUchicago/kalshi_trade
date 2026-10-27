"""A returning customer's load: the signed-in shell carries the account (no /api/me round trip before
the page's own reads), static files are cached for a year only under their current content hash and
revalidate cheaply otherwise, and nothing per-user is ever left to a shared cache."""
import gzip
import hashlib
import http.client
import json
import re
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from app import server
from app.web import static_strip, webperf

USER = {"id": 7, "email": "trader@example.invalid", "name": "Sample", "picture_url": None, "autopilot": 0,
        "ui_theme": "meridian"}


def _as_served(name):
    """A static file as the server sends it: the bundles and stylesheets without their comments (static_strip)."""
    body = (server.STATIC_DIR / name).read_bytes()
    return static_strip.served(name, body, hashlib.sha256(body).hexdigest()[:10])


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: None)
    rows = list(webperf._ROWS)  # these requests stay out of the process-wide perf window other tests read
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield http.server_port
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)
    webperf._ROWS.clear()
    webperf._ROWS.extend(rows)


def _get(port, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path, headers=headers or {})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r, body


def _carried(html):
    found = re.findall(r'<script type="application/json" id="tau-me">(.*?)</script>', html, re.S)
    return [json.loads(x) for x in found]


def _signed_in(monkeypatch, account):
    """A valid session whose /api/me reply is `account` (me() keeps the theme cookie in step, as the real one)."""
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: dict(USER))

    def fake_me(ctx):
        server._sync_ui_cookie(ctx, ctx.user["ui_theme"])
        return account
    monkeypatch.setattr(server, "me", fake_me)


def test_a_signed_in_shell_carries_the_account_so_the_app_starts_without_a_me_read(web, monkeypatch):
    # Before, every full load waited shell -> bundle -> /api/me -> the page's reads: one whole
    # round trip (~0.6s on a slow phone network) spent before the dashboard could ask for anything.
    hostile = "</script><script>alert(1)</script><!--   & 'quotes\""
    account = {"user": {"id": 7, "name": hostile, "ui_theme": "meridian"}, "credit_balance": 12.5,
               "models": {"models": [{"key": "m"}], "default": "m"}}
    _signed_in(monkeypatch, account)
    r, body = _get(web, "/", {"Cookie": "rsid=abc; tau_ui=tau"})
    html = body.decode("utf-8")
    assert r.status == 200 and _carried(html) == [account]
    # Nothing in the account can close the data block or start markup.
    block = html.split('id="tau-me">', 1)[1].split("</script>", 1)[0]
    assert "<" not in block and ">" not in block and " " not in block
    # The account's theme wins over a stale device cookie (the app used to reload into it), and the
    # cookie is put back in step.
    assert re.findall(r'<script src="/static/(app(?:\.meridian)?\.js)\?', html) == ["app.meridian.js"]
    assert re.findall(r'<link rel="stylesheet" href="/static/(app(?:\.meridian)?\.css)\?', html) == ["app.meridian.css"]
    assert 'data-ui="meridian"' in html
    assert any(c.startswith("tau_ui=meridian;") for c in r.msg.get_all("Set-Cookie") or [])
    # Per-user page: never kept by a shared cache (CloudFront), and revalidated by the browser.
    assert r.getheader("Cache-Control") == "private, no-cache" and "Cookie" in r.msg.get_all("Vary")
    assert "{{" not in html


def _account_reads(monkeypatch):
    for name, value in (("get_stripe_customer", None), ("get_kalshi_key", None), ("get_kalshi_dev_key", None),
                        ("credit_balance", 1.0), ("spot_symbols_with_data", set()), ("series_with_candles", set())):
        monkeypatch.setattr(server.repo, name, lambda *a, _v=value: _v)
    monkeypatch.setattr(server.billing, "configured", lambda: False)


def test_the_carried_account_is_the_same_reply_api_me_gives(web, monkeypatch):
    _account_reads(monkeypatch)
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: dict(USER))
    _, body = _get(web, "/research", {"Cookie": "rsid=abc"})
    r, api = _get(web, "/api/me", {"Cookie": "rsid=abc"})
    assert r.status == 200 and r.getheader("Cache-Control") == "no-store"
    assert _carried(body.decode("utf-8")) == [json.loads(api)]


@pytest.mark.parametrize("cookie,path", [
    (None, "/"),                     # signed out
    ("tau_ui=meridian", "/"),        # signed out, theme known
    ("rsid=abc", "/signin"),         # the sign-in and legal pages read the account (or not) themselves
    ("rsid=abc", "/terms"),
    ("rsid=abc", "/privacy"),
])
def test_shells_that_would_not_use_the_account_carry_none(web, monkeypatch, cookie, path):
    _signed_in(monkeypatch, {"user": {"id": 7}})
    r, body = _get(web, path, {"Cookie": cookie} if cookie else {})
    assert r.status == 200 and _carried(body.decode("utf-8")) == [] and r.getheader("Cache-Control") == "no-cache"


def test_a_stale_session_or_a_failed_account_read_still_serves_a_plain_shell(web, monkeypatch):
    # Stale session cookie: no account, the device's theme stays, the app's own /api/me says signed out.
    r, body = _get(web, "/", {"Cookie": "rsid=gone; tau_ui=meridian"})
    html = body.decode("utf-8")
    assert r.status == 200 and _carried(html) == [] and 'data-ui="meridian"' in html
    # The account read fails (database down): still a shell, in the account's theme when it was read.
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: dict(USER))

    def boom(ctx):
        raise RuntimeError("db down")
    monkeypatch.setattr(server, "me", boom)
    r, body = _get(web, "/", {"Cookie": "rsid=abc"})
    html = body.decode("utf-8")
    assert r.status == 200 and _carried(html) == [] and 'data-ui="meridian"' in html
    assert r.getheader("Cache-Control") == "no-cache"


def test_me_carries_the_research_model_list(monkeypatch):
    # /research used to wait on /api/models before starting its own reads (two serial round trips).
    _account_reads(monkeypatch)
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: object()), dict(USER), (), {}, {}, SimpleNamespace())
    assert server.me(ctx)["models"] == server.models(ctx)
    assert server.me(ctx)["models"]["models"] and server.me(ctx)["models"]["default"]


def test_a_bundle_under_its_current_hash_is_immutable_with_a_validator(web):
    v = server._static_versions()["app.js"]
    r, body = _get(web, "/static/app.js?v=" + v, {"Accept-Encoding": "gzip"})
    assert r.status == 200 and r.getheader("Cache-Control") == "public, max-age=31536000, immutable"
    assert r.getheader("ETag") == 'W/"%s"' % v and r.getheader("Content-Encoding") == "gzip"
    assert gzip.decompress(body) == _as_served("app.js")


@pytest.mark.parametrize("query", ["", "?v=0123456789", "?v="])
def test_a_bundle_under_another_hash_revalidates_and_answers_304(web, query):
    # An old shell (or a deploy rolled back) asking for a build this server doesn't have gets the
    # current file, but never pinned for a year under that URL: the next deploy of that hash must win.
    v = server._static_versions()["app.css"]
    r, body = _get(web, "/static/app.css" + query)
    assert r.status == 200 and r.getheader("Cache-Control") == "no-cache"
    assert r.getheader("ETag") == 'W/"%s"' % v and body == _as_served("app.css")
    r, body = _get(web, "/static/app.css" + query, {"If-None-Match": 'W/"%s"' % v})
    assert r.status == 304 and body == b"" and r.getheader("ETag") == 'W/"%s"' % v
    r, body = _get(web, "/static/app.css" + query, {"If-None-Match": '"stale", W/"0000000000"'})
    assert r.status == 200 and len(body) > 1000


def test_every_versioned_link_in_the_shell_is_immutable_and_hashed_fonts_always_are(web):
    # Funds' shell also links that page's own files (page_modules.ASSETS).
    links = set()
    for path in ("/", "/funds"):
        _, body = _get(web, path)
        links.update(re.findall(r'"(/static/[a-z0-9_.-]+\?v=[0-9a-f]+)"', body.decode("utf-8")))
    assert len(links) >= 10
    for link in links:
        r, _ = _get(web, link)
        assert r.status == 200 and r.getheader("Cache-Control") == webperf.IMMUTABLE, link
    for css in ("app.css", "app.meridian.css"):
        for font in re.findall(r'url\("(/static/[^"]+\.woff2)"\)', (server.STATIC_DIR / css).read_text()):
            r, _ = _get(web, font)
            assert r.status == 200 and r.getheader("Cache-Control") == webperf.IMMUTABLE, font


def test_cache_busting_follows_the_content(tmp_path, monkeypatch):
    # A deploy that changes a bundle changes its ?v=, so the shell links a URL no cache has seen.
    for name in server._STATIC_NAMES:
        (tmp_path / name).write_bytes(b"x" + name.encode())
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path)
    server._VERSIONS_CACHE.update(sig=None, out=None)
    before = server._static_versions()["app.js"]
    (tmp_path / "app.js").write_bytes(b"a new build")
    after = server._static_versions()["app.js"]
    assert before != after
    assert webperf.static_cache_control("app.js", "v=" + after, after) == webperf.IMMUTABLE
    assert webperf.static_cache_control("app.js", "v=" + before, after) == webperf.REVALIDATE
    server._VERSIONS_CACHE.update(sig=None, out=None)


def test_etag_comparison_is_weak_and_handles_lists():
    tag = webperf.etag("abc")
    assert webperf.etag_matches('W/"abc"', tag) and webperf.etag_matches('"abc"', tag)
    assert webperf.etag_matches('"x", W/"abc"', tag) and webperf.etag_matches("*", tag)
    assert not webperf.etag_matches(None, tag) and not webperf.etag_matches("", tag)
    assert not webperf.etag_matches('W/"abcd"', tag)


def test_api_replies_are_never_left_to_a_shared_cache(web, monkeypatch):
    r, _ = _get(web, "/api/me")  # 401, signed out
    assert r.status == 401 and r.getheader("Cache-Control") == "no-store"
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: dict(USER))
    monkeypatch.setattr(server.repo, "get_image", lambda cur, i: {"content_type": "image/png", "data": b"\x89PNG"})
    r, _ = _get(web, "/api/community/image/3", {"Cookie": "rsid=abc"})
    assert r.status == 200 and r.getheader("Cache-Control").startswith("private,")


def test_embedded_json_reads_back_the_same_value():
    value = {"a": "</script><!--<b>&  ", "n": [1, 2.5, None, True]}
    text = webperf.embed_json(json.dumps(value))
    assert json.loads(text) == value
    assert not set("<>&  ") & set(text)
