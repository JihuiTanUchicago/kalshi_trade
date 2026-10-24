"""Web server speed and observability: keep-alive, gzip, request timing, and /internal/perf."""
import gzip
import http.client
import json
import time
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from app import server, webperf


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: None)
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield http.server_port
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)


def test_one_connection_serves_many_requests(web):
    conn = http.client.HTTPConnection("127.0.0.1", web, timeout=3)
    for _ in range(3):
        conn.request("GET", "/healthz")
        r = conn.getresponse()
        assert r.status == 200 and json.loads(r.read()) == {"ok": True}
    conn.request("GET", "/api/version")
    r = conn.getresponse()
    assert r.status == 200 and "v" in json.loads(r.read())
    conn.close()


def test_post_rejected_before_reading_its_body_does_not_poison_the_next_request(web):
    conn = http.client.HTTPConnection("127.0.0.1", web, timeout=3)
    body = json.dumps({"x": "GET /healthz HTTP/1.1\r\n\r\n"})
    conn.request("POST", "/api/settings", body=body, headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    assert r.status == 403
    r.read()
    # The server closed that socket rather than parse the leftover body as a request.
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", web, timeout=3)
    conn.request("GET", "/healthz")
    assert conn.getresponse().status == 200


def test_static_bundle_is_gzipped_when_accepted_and_identical_when_unzipped(web):
    conn = http.client.HTTPConnection("127.0.0.1", web, timeout=3)
    conn.request("GET", "/static/app.js", headers={"Accept-Encoding": "gzip, br"})
    r = conn.getresponse()
    raw = r.read()
    assert r.status == 200 and r.getheader("Content-Encoding") == "gzip"
    assert r.getheader("Vary") == "Accept-Encoding"
    original = (server.STATIC_DIR / "app.js").read_bytes()
    assert gzip.decompress(raw) == original and len(raw) < len(original) / 2
    conn.request("GET", "/static/app.js")
    r = conn.getresponse()
    assert r.getheader("Content-Encoding") is None and r.read() == original


def test_small_and_binary_responses_are_not_gzipped():
    assert not webperf.wants_gzip("gzip", "application/json", 200)
    assert not webperf.wants_gzip("gzip", "font/woff2", 50000)
    assert not webperf.wants_gzip("gzip;q=0", "text/javascript", 50000)
    assert not webperf.wants_gzip("br", "text/javascript", 50000)
    assert webperf.wants_gzip("deflate, gzip;q=0.8", "text/css; charset=utf-8", 50000)


def test_access_line_has_status_time_and_no_query(web, capsys):
    conn = http.client.HTTPConnection("127.0.0.1", web, timeout=3)
    conn.request("GET", "/api/me?code=private")
    r = conn.getresponse()
    r.read()
    assert r.status == 401
    out = ""
    for _ in range(100):  # the line prints just after the response is flushed
        out += capsys.readouterr().out
        if "[app] GET /api/me" in out:
            break
        time.sleep(0.01)
    line = [l for l in out.splitlines() if l.startswith("[app] GET /api/me")][-1]
    parts = line.split()
    assert parts[3] == "401" and parts[4].endswith("ms") and parts[5].endswith("Z")
    assert "private" not in out


def test_perf_endpoint_reports_routes_and_is_loopback_only(web):
    conn = http.client.HTTPConnection("127.0.0.1", web, timeout=3)
    for path in ("/api/runs/12", "/api/runs/13", "/wp-login.php"):
        conn.request("GET", path)
        conn.getresponse().read()
    conn.request("GET", "/internal/perf?window=600")
    r = conn.getresponse()
    data = json.loads(r.read())
    assert r.status == 200 and data["window_s"] == 600
    routes = {x["route"]: x for x in data["routes"]}
    assert routes["GET /api/runs/:id"]["n"] >= 2
    assert "GET <other>" in routes and "GET /wp-login.php" not in routes
    assert data["api"]["n"] >= 2


def test_perf_endpoint_hides_from_non_loopback_peers():
    handler = object.__new__(server.Handler)
    handler.client_address = ("130.176.1.1", 5000)
    sent = []
    handler._send_json = lambda status, payload, cookies: sent.append(status)
    handler._perf("window=60")
    assert sent == [404]


def test_summary_percentiles_and_5xx_rate():
    webperf._ROWS.clear()
    now = 1_000_000.0
    for i in range(100):
        webperf.record("GET /api/dashboard", 500 if i < 2 else 200, float(i + 1), now=now)
    webperf.record("GET /static/*", 200, 9999.0, now=now)
    webperf.record("GET /api/old", 200, 9999.0, now=now - 5000)
    s = webperf.summary(900, now=now)
    assert s["api"]["n"] == 100 and s["api"]["5xx"] == 2 and s["api"]["5xx_rate"] == 0.02
    assert s["api"]["p50_ms"] in (50.0, 51.0) and s["api"]["p95_ms"] in (95.0, 96.0)
    assert {r["route"] for r in s["routes"]} == {"GET /api/dashboard", "GET /static/*"}


def test_route_keys_collapse_ids_and_noise():
    assert webperf.route_key("GET", "/api/strategies/42/live-readiness") == "GET /api/strategies/:id/live-readiness"
    assert webperf.route_key("GET", "/.env") == "GET <other>"
    assert webperf.route_key("GET", "/dashboard", spa=True) == "GET <page>"
    assert webperf.route_key("GET", "/static/app.js") == "GET /static/*"


def test_static_versions_rehash_only_when_a_file_changes(monkeypatch):
    first = server._static_versions()
    calls = []
    real = server.hashlib.sha256
    monkeypatch.setattr(server.hashlib, "sha256", lambda b: calls.append(1) or real(b))
    assert server._static_versions() == first
    assert calls == []
