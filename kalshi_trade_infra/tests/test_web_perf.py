"""Web server speed and observability: keep-alive, gzip, request timing, and /internal/perf."""
import gzip
import http.client
import json
import socket
import struct
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


def test_reused_connection_is_not_stalled_by_nagle(web):
    # Headers and body are separate writes; without TCP_NODELAY each response after the first on a
    # kept-alive connection (CloudFront's origin pool) waited ~40ms for the client's delayed ACK.
    assert server.Handler.disable_nagle_algorithm is True
    conn = http.client.HTTPConnection("127.0.0.1", web, timeout=3)
    took = []
    for _ in range(9):
        t = time.perf_counter()
        conn.request("GET", "/healthz")
        conn.getresponse().read()
        took.append(time.perf_counter() - t)
    conn.close()
    assert sorted(took[1:])[4] < 0.02, took  # median of the reused-connection requests


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


def test_session_reuse_after_a_rejected_post_reconnects_cleanly(web):
    # The staging smoke does exactly this with requests.Session: a CSRF-less POST (403), then GETs.
    import requests
    s = requests.Session()
    r = s.post("http://127.0.0.1:%d/api/brokers/alpaca/paper/orders" % web, json={}, timeout=3)
    assert r.status_code == 403 and r.headers["Connection"] == "close"
    for _ in range(3):
        assert s.get("http://127.0.0.1:%d/healthz" % web, timeout=3).status_code == 200


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


def test_a_client_that_hung_up_is_logged_499_not_a_server_error(web, monkeypatch, capsys):
    def gone():
        raise BrokenPipeError(32, "Broken pipe")
    monkeypatch.setattr(server, "_static_versions", gone)
    conn = http.client.HTTPConnection("127.0.0.1", web, timeout=3)
    conn.request("GET", "/api/version")
    with pytest.raises(http.client.RemoteDisconnected):
        conn.getresponse()
    captured = ""
    for _ in range(100):
        out = capsys.readouterr()
        captured += out.out + out.err
        if "[app] GET /api/version" in captured:
            break
        time.sleep(0.01)
    line = [l for l in captured.splitlines() if l.startswith("[app] GET /api/version")][-1]
    assert line.split()[3] == "499" and "Traceback" not in captured
    route = [r for r in webperf.summary()["routes"] if r["route"] == "GET /api/version"][0]
    assert route["5xx"] == 0


def test_a_client_that_resets_an_idle_keep_alive_socket_prints_no_traceback(web, capsys):
    sock = socket.create_connection(("127.0.0.1", web), timeout=3)
    sock.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
    assert b"200" in sock.recv(4096)
    # SO_LINGER 0: close() sends RST, so the server's read of the next request line raises
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    sock.close()
    time.sleep(0.2)
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err


def test_an_access_line_is_one_write_so_threads_cannot_glue_lines(monkeypatch):
    writes = []
    monkeypatch.setattr(server.sys, "stdout", SimpleNamespace(write=writes.append, flush=lambda: None))
    server._log_line("[app] GET /api/me 200 3ms 2026-10-25T17:40:00Z")
    assert writes == ["[app] GET /api/me 200 3ms 2026-10-25T17:40:00Z\n"]


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


def test_explore_feed_serves_stale_while_one_thread_refreshes(monkeypatch):
    fetched = []
    monkeypatch.setattr(server, "_EXPLORE_CACHE", {"at": 0.0, "data": None})
    monkeypatch.setattr(server, "_fetch_explore_feed", lambda: fetched.append(1) or {"at": len(fetched), "markets": []})
    assert server._explore_feed()["at"] == 1  # cold: the first caller waits for S3 once
    assert server._explore_feed()["at"] == 1 and len(fetched) == 1  # warm: cached
    server._EXPLORE_CACHE["at"] -= 60  # stale
    started = []
    monkeypatch.setattr(server.threading, "Thread", lambda target, daemon: SimpleNamespace(start=lambda: started.append(target)))
    assert server._explore_feed()["at"] == 1 and server._explore_feed()["at"] == 1  # served stale, no wait
    assert len(started) == 1  # one refresh, not one per request
    started[0]()
    assert server._explore_feed()["at"] == 2


def test_explore_feed_keeps_last_good_copy_when_s3_fails(monkeypatch):
    monkeypatch.setattr(server, "_EXPLORE_CACHE", {"at": 0.0, "data": {"at": "good", "markets": [1]}})
    monkeypatch.setattr(server, "_fetch_explore_feed", lambda: None)
    server._EXPLORE_CACHE["refreshing"] = True
    server._refresh_explore_feed()
    assert server._EXPLORE_CACHE["data"]["at"] == "good" and server._EXPLORE_CACHE["refreshing"] is False


def test_shared_reads_compute_once_then_refresh_in_one_background_thread(monkeypatch):
    calls = []
    fn = lambda cur: calls.append(cur) or len(calls)
    assert server._shared("k", 60, fn, "cur") == 1
    assert server._shared("k", 60, fn, "cur") == 1 and calls == ["cur"]
    server._SHARED["k"]["at"] -= 61
    started = []
    monkeypatch.setattr(server.threading, "Thread", lambda target, args, daemon: SimpleNamespace(start=lambda: started.append(args)))
    assert server._shared("k", 60, fn, "cur") == 1 and server._shared("k", 60, fn, "cur") == 1
    assert len(started) == 1  # one refresh while stale, not one per request
    conn = SimpleNamespace(cursor=lambda: "bg", close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: conn)
    server._refresh_shared(*started[0])
    assert server._shared("k", 60, fn, "cur") == 2 and calls[-1] == "bg"


def test_shared_refresh_failure_keeps_the_last_value(monkeypatch):
    server._shared("k", 60, lambda cur: "good", None)
    monkeypatch.setattr(server, "get_db_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    ent = server._SHARED["k"]
    ent["busy"] = True
    server._refresh_shared(ent, lambda cur: "never")
    assert ent["val"] == "good" and ent["busy"] is False


def test_dashboard_freshness_uses_the_shared_read(monkeypatch):
    calls = []
    monkeypatch.setattr(server.repo, "history_freshness", lambda cur: calls.append(1) or {"btc": None})
    monkeypatch.setattr(server.repo, "engine_last_tick_age_seconds", lambda cur: 5)
    for _ in range(3):
        assert server._freshness(None) == {"btc": None, "engine": 5}
    assert calls == [1]


def test_the_rsi_block_names_the_history_the_first_policy_check_needs():
    from app import dreaming, server
    block = server._rsi_block(None, None)
    assert block["evolved"] is False and block["last_dream"] is None
    assert block["min_history"] == dreaming.MIN_TREE
