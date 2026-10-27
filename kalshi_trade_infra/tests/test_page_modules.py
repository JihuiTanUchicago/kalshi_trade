"""The page files (app/web/page_modules.py): code only some pages use, split out of each theme's bundle.

Each is versioned, cached and compressed like the bundles, named in the shell for the bundle to fetch it
by, and preloaded by a signed-in shell for the page that needs it. Both routers send each path to the
page file this table names, so the shell never preloads one file while the page waits on another."""
import http.client
import re
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from app import server
from app.web import page_modules, webperf

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
USER = {"id": 7, "email": "trader@example.invalid", "name": "Sample", "picture_url": None, "autopilot": 0, "ui_theme": "tau"}
# Every app path both routers know (SPA_ROUTES), with ids where the path takes one.
PATHS = ("/", "/dashboard", "/research", "/research/12", "/example", "/strategies", "/strategies/3", "/deploy",
         "/community", "/explore", "/billing", "/settings/billing", "/admin", "/system", "/settings/system", "/funds",
         "/settings/account", "/devlog", "/track-record", "/settings", "/settings/theme", "/signin", "/terms", "/privacy")


@pytest.fixture
def web(monkeypatch):
    theme = {"ui_theme": "tau"}
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: dict(USER, **theme) if token else None)
    monkeypatch.setattr(server, "me", lambda ctx: {"user": {"id": 7, "ui_theme": theme["ui_theme"]}})
    monkeypatch.setattr(server.shell_reads, "first_reads", lambda *a: ([], []))
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield http.server_port, theme
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)


def _get(port, path, cookie=None, accept_encoding=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {k: v for k, v in (("Cookie", cookie), ("Accept-Encoding", accept_encoding)) if v}
    conn.request("GET", path, headers=headers)
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r, body


def _preloads(html):
    return re.findall(r'<link rel="preload" href="/static/([a-z.-]+\.js)\?v=([0-9a-f]+)" as="script">', html)


def test_every_page_file_is_in_the_repo_versioned_and_warmed_like_the_bundles():
    names = sorted(p.name for p in STATIC.glob("app*-*.js"))
    assert names == sorted(page_modules.FILES)  # no file the table misses, none it names that isn't there
    versions = server._static_versions()
    for f in page_modules.FILES:
        assert f in server._STATIC_NAMES and re.fullmatch(r"[0-9a-f]{10}", versions[f])
    assert page_modules.versions_attr("tau", versions).split(",")[0] == "research:" + versions["app-research.js"]


def test_a_page_file_is_served_like_a_bundle_immutable_at_its_version_and_compressed(web):
    port, _ = web
    v = server._static_versions()["app.meridian-research.js"]
    r, body = _get(port, "/static/app.meridian-research.js?v=" + v, accept_encoding="gzip")
    assert r.status == 200 and r.getheader("Content-Type") == "text/javascript; charset=utf-8"
    assert r.getheader("Cache-Control") == webperf.IMMUTABLE and r.getheader("Content-Encoding") == "gzip"
    # Another build's version (an old page asking after a deploy) gets the current file, revalidated.
    r, _ = _get(port, "/static/app.meridian-research.js?v=0000000000")
    assert r.status == 200 and r.getheader("Cache-Control") == webperf.REVALIDATE


@pytest.mark.parametrize("theme,path,want", [
    ("tau", "/research/12", "app-research.js"), ("tau", "/example", "app-research.js"),
    ("tau", "/strategies", "app-strategies.js"), ("tau", "/billing", "app-billing.js"),
    ("meridian", "/research", "app.meridian-research.js"), ("meridian", "/strategies/3", "app.meridian-strategies.js"),
    ("meridian", "/settings/billing", "app.meridian-billing.js"), ("meridian", "/settings/account", "app.meridian-funds.js"),
    ("tau", "/", None), ("meridian", "/deploy", None), ("tau", "/terms", None),
])
def test_a_signed_in_shell_preloads_the_page_file_its_page_needs(web, theme, path, want):
    port, account = web
    account["ui_theme"] = theme
    r, body = _get(port, path, cookie="rsid=abc")
    html = body.decode()
    versions = server._static_versions()
    assert r.status == 200
    assert _preloads(html) == ([(want, versions[want])] if want else [])
    # Every file's version is named for the bundle to fetch by, in both themes (boot.js may pick either).
    for t, key in (("tau", "data-tau-pages"), ("meridian", "data-mer-pages")):
        assert '%s="%s"' % (key, page_modules.versions_attr(t, versions)) in html
    # The build the page checks /api/version against covers its page files.
    assert 'data-tau-ver="%s"' % page_modules.build_version("tau", versions) in html


def test_a_signed_out_shell_preloads_nothing(web):
    port, _ = web
    for cookie in (None, "tau_ui=meridian"):
        _, body = _get(port, "/research", cookie=cookie)
        assert _preloads(body.decode()) == [] and "{{" not in body.decode()


def test_a_deploy_that_changes_only_a_page_file_changes_the_build_the_page_checks():
    versions = dict(server._static_versions())
    before = page_modules.build_version("tau", versions)
    assert page_modules.build_version("tau", dict(versions, **{"app-billing.js": "f" * 10})) != before
    # The other theme's files are not this build.
    assert page_modules.build_version("tau", dict(versions, **{"app.meridian-billing.js": "e" * 10})) == before


def _router(bundle):
    """Each route of the bundle's router as (compiled path regex, the page file its view is in or None)."""
    src = (STATIC / bundle).read_text()
    table = src[src.index("  const routes = ["):]
    table = table[:table.index("\n  ];")]
    stubs = dict(re.findall(r"function (view\w+)\([^)]*\) \{ return pageView\('([a-z]+)', '\1'", src))
    out = []
    for rx, target in re.findall(r"\[/(\^.*?\$)/, ([^\]]+?)\],", table):
        view = re.match(r"view\w+", target.strip())  # or an inline redirect (/track-record)
        out.append((re.compile(rx.replace("\\/", "/")), view and stubs.get(view.group(0))))
    return out, stubs


@pytest.mark.parametrize("bundle", ["app.js", "app.meridian.js"])
def test_both_routers_send_each_path_to_the_page_file_the_shell_preloads(bundle):
    routes, stubs = _router(bundle)
    assert set(stubs.values()) == set(page_modules.PAGES)  # each page file stands behind some view
    for path in PATHS:
        # viewExample (in the bundle) goes straight on to its session's page, which the preload is for.
        hit = next((page for rx, page in routes if rx.match("/research/1" if path == "/example" else path)), "unrouted")
        if hit == "unrouted":
            continue  # a path this theme's router sends elsewhere (Meridian has no /terms page)
        assert hit == page_modules.page_for(path), (bundle, path)


@pytest.mark.parametrize("theme", ["tau", "meridian"])
def test_each_page_file_returns_the_views_its_bundle_stands_in_for(theme):
    bundle = (STATIC / page_modules.BUNDLE[theme]).read_text()
    for name in page_modules.PAGES:
        src = (STATIC / page_modules.file_name(theme, name)).read_text()
        assert src.count("window.TauPage('%s', (T) => {" % name) == 1
        returned = set(re.search(r"\n  return \{([\w, ]+)\};\n\}\);\n$", src).group(1).split(", "))
        stood_in = set(re.findall(r"function (view\w+)\([^)]*\) \{ return pageView\('%s', " % name, bundle))
        assert returned == stood_in and returned, (theme, name)
        for view in returned:  # the view is the file's own, not left behind in the bundle
            assert re.search(r"\n  async function %s\(" % view, src) and not re.search(r"\n  async function %s\(" % view, bundle)
