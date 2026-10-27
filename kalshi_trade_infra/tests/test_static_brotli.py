"""Brotli for static files: sent only to clients that ask for it, with gzip and as-is fallbacks, one
weak ETag per content version whatever the encoding, and never a compressed copy of an older file.

These run with or without the brotli package: without it, a stand-in codec takes its place (so the
choice of encoding is still tested), and the round trip through real brotli skips."""
import gzip
import hashlib
import http.client
import os
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from app import server
from app.web import static_strip, webperf

MODERN = "gzip, deflate, br, zstd"  # what Chrome, Firefox and Safari send over HTTPS


class _StandIn:
    """A reversible codec in brotli's shape, for runs without the package."""
    MODE_TEXT = 1

    def __init__(self):
        self.calls = 0

    def compress(self, body, mode=None, quality=None):
        self.calls += 1
        return b"BR:" + body[::-1]

    @staticmethod
    def decompress(raw):
        assert raw.startswith(b"BR:")
        return raw[3:][::-1]


@pytest.fixture
def standin(monkeypatch):
    """The stand-in codec, with empty compression caches (restored after the test)."""
    monkeypatch.setattr(webperf, "_Z_CACHE", {})
    monkeypatch.setattr(webperf, "_Z_BUSY", {})
    monkeypatch.setattr(webperf, "_brotli", _StandIn())
    return webperf._brotli


@pytest.fixture
def codec(request):
    """The brotli module the server uses: the real one when installed (its cache shared across
    tests, keyed by content, so each bundle pays brotli's best setting once), else the stand-in."""
    return webperf._brotli or request.getfixturevalue("standin")


@pytest.fixture
def static_dir(tmp_path, monkeypatch):
    """A copy of the static files the server reads, so a test can change one under it."""
    d = tmp_path / "static"
    shutil.copytree(server.STATIC_DIR, d)
    monkeypatch.setattr(server, "STATIC_DIR", d)
    monkeypatch.setattr(server, "_VERSIONS_CACHE", {"sig": None, "out": None})
    return d


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


def _get(port, path, accept_encoding=None, if_none_match=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {}
    if accept_encoding is not None:
        headers["Accept-Encoding"] = accept_encoding
    if if_none_match is not None:
        headers["If-None-Match"] = if_none_match
    conn.request("GET", path, headers=headers)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    return r, raw


def _as_served(name):
    """A static file as the server sends it: the bundles and stylesheets without their comments (static_strip)."""
    body = (server.STATIC_DIR / name).read_bytes()
    return static_strip.served(name, body, hashlib.sha256(body).hexdigest()[:10])


def _decode(r, raw, codec):
    coding = r.getheader("Content-Encoding")
    if coding == "br":
        return codec.decompress(raw)
    if coding == "gzip":
        return gzip.decompress(raw)
    assert coding is None, coding
    return raw


def test_brotli_goes_only_to_clients_that_ask_for_it(web, codec):
    original = _as_served("app.js")
    cases = {
        MODERN: "br",
        "br": "br",
        "gzip": "gzip",
        "br;q=0, gzip": "gzip",          # refused outright
        "gzip;q=1, br;q=0.5": "gzip",    # the client prefers gzip
        "br;q=0.8, gzip;q=0.8": "br",    # a tie goes to the smaller one
        "br;q=bogus, gzip": "gzip",      # a malformed q is not a yes
        "*": None,                       # only an encoding the client named
        "identity": None,
        "": None,
        None: None,
    }
    for accept, want in cases.items():
        r, raw = _get(web, "/static/app.js", accept)
        assert r.status == 200, accept
        assert r.getheader("Content-Encoding") == want, accept
        assert r.msg.get_all("Vary") == ["Accept-Encoding"], accept  # every variant, the plain one too
        assert int(r.getheader("Content-Length")) == len(raw), accept
        assert _decode(r, raw, codec) == original, accept
        # The security headers ride on every variant.
        assert r.getheader("Content-Security-Policy") == server.CSP and r.getheader("X-Content-Type-Options") == "nosniff"


def test_without_the_brotli_package_static_files_fall_back_to_gzip_then_as_is(web, monkeypatch):
    monkeypatch.setattr(webperf, "_brotli", None)
    original = _as_served("app.css")
    r, raw = _get(web, "/static/app.css", MODERN)
    assert r.getheader("Content-Encoding") == "gzip" and gzip.decompress(raw) == original
    assert r.getheader("Vary") == "Accept-Encoding"
    r, raw = _get(web, "/static/app.css", "br")
    assert r.getheader("Content-Encoding") is None and raw == original
    assert r.getheader("Vary") == "Accept-Encoding"
    assert webperf.static_codings() == ("gzip",)


def test_api_responses_never_go_out_as_brotli(codec):
    # Only static files, compressed once and cached, are worth brotli's best setting.
    assert webperf.pick_encoding(MODERN, "application/json", 50000, allow_br=False) == "gzip"
    assert webperf.pick_encoding("br", "application/json", 50000, allow_br=False) is None
    assert webperf.pick_encoding(MODERN, "text/javascript", 50000, allow_br=True) == "br"
    assert webperf.pick_encoding(MODERN, "font/woff2", 50000, allow_br=True) is None  # already compressed
    assert webperf.pick_encoding(MODERN, "text/css", 200, allow_br=True) is None  # too small to bother


def test_one_weak_etag_per_version_and_304_under_every_encoding(web, codec):
    tags = set()
    for accept in (MODERN, "gzip", None):
        r, _ = _get(web, "/static/app.meridian.js", accept)
        tags.add(r.getheader("ETag"))
    assert len(tags) == 1
    tag = tags.pop()
    version = server._static_versions()["app.meridian.js"]
    assert tag == 'W/"%s"' % version
    for accept in (MODERN, "gzip", None):
        r, raw = _get(web, "/static/app.meridian.js?v=" + version, accept, if_none_match=tag)
        assert r.status == 304 and raw == b"", accept
        assert r.getheader("ETag") == tag and r.getheader("Vary") == "Accept-Encoding", accept
        assert r.getheader("Content-Encoding") is None, accept
        assert r.getheader("Cache-Control") == webperf.IMMUTABLE, accept
    r, raw = _get(web, "/static/app.meridian.js", MODERN, if_none_match='W/"0000000000"')
    assert r.status == 200 and r.getheader("Content-Encoding") == "br" and raw


def test_a_changed_file_never_gets_the_old_compressed_copy(web, codec, static_dir):
    f = static_dir / "boot.js"
    old = f.read_bytes()
    r, raw = _get(web, "/static/boot.js", MODERN)
    assert r.getheader("Content-Encoding") == "br" and codec.decompress(raw) == old
    old_tag = r.getheader("ETag")

    # A new build of the same size, written with the old timestamp: the stat-keyed version cache
    # can't see it, the bytes can.
    st = f.stat()
    new = old.replace(b"function", b"FUNCTION", 1)
    assert new != old and len(new) == len(old)
    f.write_bytes(new)
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    new_tag = 'W/"%s"' % hashlib.sha256(new).hexdigest()[:10]
    for accept in (MODERN, "gzip", None):
        r, raw = _get(web, "/static/boot.js", accept)
        assert _decode(r, raw, codec) == new, accept
        assert r.getheader("ETag") == new_tag != old_tag, accept
    # The old version's URL can't pin the new bytes for a year.
    r, raw = _get(web, "/static/boot.js?v=" + old_tag[3:-1], MODERN)
    assert codec.decompress(raw) == new and r.getheader("Cache-Control") == webperf.REVALIDATE

    # An ordinary deploy (new size and time) moves the version and the compressed copy with it.
    newer = new + b"\n// next build\n"
    f.write_bytes(newer)
    r, raw = _get(web, "/static/boot.js", MODERN)
    assert codec.decompress(raw) == newer
    assert r.getheader("ETag") == 'W/"%s"' % server._static_versions()["boot.js"]


def test_each_version_compresses_once_even_when_requests_race(standin):
    codec = standin
    body = b"x" * 5000
    out = []
    threads = [threading.Thread(target=lambda: out.append(webperf.compress(body, "br", ("a.js", "v1")))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codec.calls == 1 and len(set(out)) == 1
    webperf.compress(body + b"y", "br", ("a.js", "v2"))
    assert codec.calls == 2


def test_startup_warms_both_encodings_of_every_bundle(standin):
    server.warm_static()
    for name in ("app.js", "app.meridian.js", "app.css", "app.meridian.css"):
        digest = hashlib.sha256((server.STATIC_DIR / name).read_bytes()).hexdigest()[:10]
        assert ("br", name, digest) in webperf._Z_CACHE and ("gzip", name, digest) in webperf._Z_CACHE


def test_real_brotli_round_trips_and_beats_gzip(web, monkeypatch):
    brotli = pytest.importorskip("brotli")
    monkeypatch.setattr(webperf, "_brotli", brotli)
    for name in ("app.js", "app.meridian.js", "app.css", "app.meridian.css"):
        original = _as_served(name)
        r, br_raw = _get(web, "/static/" + name, MODERN)
        assert r.getheader("Content-Encoding") == "br" and brotli.decompress(br_raw) == original
        _, gz_raw = _get(web, "/static/" + name, "gzip")
        assert len(br_raw) < len(gz_raw) * 0.92, (name, len(br_raw), len(gz_raw))


def test_the_pinned_brotli_is_the_one_the_deploy_installs():
    root = Path(__file__).resolve().parents[1]
    pins = [l.strip() for l in (root / "requirements.txt").read_text().splitlines() if l.lower().startswith("brotli")]
    assert len(pins) == 1 and "==" in pins[0]
    script = (root / "scripts" / "deploy_web.sh").read_text()
    req = next(l for l in script.splitlines() if l.startswith("BROTLI_REQ="))
    assert ('"%s --hash=sha256:' % pins[0]) in req
    # Hash-locked and binary only; a failed install leaves gzip serving and never rolls the deploy back.
    i = script.index("pip install")
    step = script[script.rindex("\n", 0, i):script.index("\nfi\n", i)]
    assert "--require-hashes" in step and "--only-binary=:all:" in step and "--no-deps" in step
    assert "rollback" not in step and "exit" not in step and "WARN brotli not installed" in step
    assert script.index("pip install") < script.index("systemctl restart ${SERVICES}\nsleep 5")
