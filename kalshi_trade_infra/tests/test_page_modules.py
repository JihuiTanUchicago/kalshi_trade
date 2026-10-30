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
from app.web import page_modules, static_strip, webperf

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
    names = sorted(p.name for p in [*STATIC.glob("app*-*.js"), *STATIC.glob("page-*.js")])
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
    ("tau", "/terms", "app-legal.js"), ("meridian", "/privacy", "app-legal.js"),  # the legal pages are always Tau's
    ("tau", "/admin", "page-admin.js"), ("meridian", "/settings/system", "page-admin.js"),  # one file for both themes
    ("tau", "/community", "page-community.js"), ("meridian", "/community", "page-community.js"),
    ("tau", "/", None), ("meridian", "/deploy", None), ("tau", "/signin", None),
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


def test_the_legal_pages_preload_their_file_signed_out_too(web):
    # Terms and Privacy draw signed out (every other page goes to sign-in), in Tau on any device.
    port, _ = web
    v = server._static_versions()["app-legal.js"]
    for cookie in (None, "tau_ui=meridian", "rsid=abc"):
        for path in ("/terms", "/privacy"):
            _, body = _get(port, path, cookie=cookie)
            assert _preloads(body.decode()) == [("app-legal.js", v)], (cookie, path)


def _font_preloads(html):
    return re.findall(r'<link rel="preload" href="/static/([a-z0-9.-]+\.woff2)" as="font" type="font/woff2" crossorigin>', html)


# Page-speed pass 2026-10-30: Meridian's DM Sans was asked for only once the bundle had drawn text (~100ms into a
# local load, a round trip later on a phone), so every Meridian page painted in the fallback face and then laid
# the whole page out again when it arrived. Seeded local account, 1280px, cold: Meridian Dashboard layout 82 -> 40ms,
# first figure 304 -> 244ms (median of 3); Deploy 204 -> 167ms, Settings 166 -> 129ms.
@pytest.mark.parametrize("path", ["/", "/deploy", "/research/12", "/funds", "/settings"])
def test_a_signed_in_meridian_shell_preloads_its_text_face_and_tau_preloads_none(web, path):
    port, account = web
    # The preloaded file is the one Meridian's stylesheet names for DM Sans, its body face, and it is in the repo.
    css = (STATIC / "app.meridian.css").read_text()
    face = re.search(r'font-family: "DM Sans";\s*src: url\("/static/([a-z0-9.-]+\.woff2)"\)', css)
    assert face and page_modules.FONTS == {"meridian": face.group(1)} and (STATIC / face.group(1)).is_file()
    assert re.search(r'^\s*font: [^;]*var\(--f-ui\);', css, re.M) and '--f-ui: "DM Sans"' in css
    account["ui_theme"] = "meridian"
    _, body = _get(port, path, cookie="rsid=abc")
    html = body.decode()
    head = html.split("</head>")[0]
    assert _font_preloads(head) == [face.group(1)]
    # Served like the other fonts: immutable, and a font CSP font-src 'self' allows.
    r, _ = _get(port, "/static/" + face.group(1))
    assert r.status == 200 and r.getheader("Content-Type") == "font/woff2" and "font-src 'self'" in server.CSP
    account["ui_theme"] = "tau"  # Tau's app pages use the system face: nothing to preload
    _, body = _get(port, path, cookie="rsid=abc")
    assert _font_preloads(body.decode()) == []


def test_a_signed_out_shell_preloads_no_font():
    """Signed out (sign-in, landing, the legal pages) sets its own type, so no shell preloads Meridian's face."""
    assert page_modules.font_preload("meridian", signed_in=False) == ""
    assert page_modules.font_preload(None) == "" and page_modules.font_preload("tau") == ""


def test_a_signed_out_meridian_device_shell_preloads_no_font(web):
    port, _ = web
    for path in ("/", "/signin", "/terms"):
        _, body = _get(port, path, cookie="tau_ui=meridian")
        assert _font_preloads(body.decode()) == [], path


def test_only_tau_has_the_legal_file():
    assert page_modules.TAU_ONLY == ("legal",) and page_modules.PUBLIC == ("legal",)
    assert "app-legal.js" in page_modules.FILES and "app.meridian-legal.js" not in page_modules.FILES
    versions = server._static_versions()
    assert "legal:" in page_modules.versions_attr("tau", versions)
    assert "legal:" not in page_modules.versions_attr("meridian", versions)
    assert page_modules.preload("meridian", "/terms", versions) == ""


def test_a_deploy_that_changes_only_a_page_file_changes_the_build_the_page_checks():
    versions = dict(server._static_versions())
    before = page_modules.build_version("tau", versions)
    assert page_modules.build_version("tau", dict(versions, **{"app-billing.js": "f" * 10})) != before
    # The other theme's files are not this build.
    assert page_modules.build_version("tau", dict(versions, **{"app.meridian-billing.js": "e" * 10})) == before
    # The shared core and a shared page file are both themes' build.
    for theme in ("tau", "meridian"):
        for shared in ("core.js", "page-autopilot.js", "page-admin.js", "page-community.js"):
            assert page_modules.build_version(theme, dict(versions, **{shared: "d" * 10})) != page_modules.build_version(theme, versions)


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


@pytest.mark.parametrize("theme", ["tau", "meridian"])
def test_both_routers_send_each_path_to_the_page_file_the_shell_preloads(theme):
    bundle = page_modules.BUNDLE[theme]
    routes, stubs = _router(bundle)
    # Each page file of this theme stands behind some view.
    assert set(stubs.values()) == set(page_modules.PAGES) & set(page_modules.names(theme))
    for path in PATHS:
        # viewExample (in the bundle) goes straight on to its session's page, which the preload is for.
        hit = next((page for rx, page in routes if rx.match("/research/1" if path == "/example" else path)), "unrouted")
        if hit == "unrouted":
            continue  # a path this theme's router sends elsewhere (Meridian has no /terms page)
        assert hit == page_modules.page_for(path), (bundle, path)


@pytest.mark.parametrize("theme", ["tau", "meridian"])
def test_each_page_file_returns_the_views_its_bundle_stands_in_for(theme):
    bundle = (STATIC / page_modules.BUNDLE[theme]).read_text()
    for name in set(page_modules.PAGES) & set(page_modules.names(theme)):
        src = (STATIC / page_modules.file_name(theme, name)).read_text()
        assert src.count("window.TauPage('%s', (T) => {" % name) == 1
        returned = set(re.search(r"\n  return \{([\w, ]+)\};\n\}\);\n$", src).group(1).split(", "))
        stood_in = set(re.findall(r"function (view\w+)\([^)]*\) \{ return pageView\('%s', " % name, bundle))
        assert returned == stood_in and returned, (theme, name)
        for view in returned:  # the view is the file's own, not left behind in the bundle
            assert re.search(r"\n  async function %s\(" % view, src) and not re.search(r"\n  async function %s\(" % view, bundle)


# What the autopilot panel's file holds, the open panel: its feed, its chat and its controls. None of it
# is drawn until the panel opens, so a cold load of any page goes without it.
PANEL_CODE = ("async function apLoadChat(", "function apFeedLi(", "const AP_ACT = {", "async function apEnableLive(",
              "function apSheetTab(", "const CHAT_UNSURE = ")


@pytest.mark.parametrize("theme", ["tau", "meridian"])
def test_the_autopilot_panel_is_in_its_own_file_and_the_bundle_only_forwards_to_it(theme):
    bundle = (STATIC / page_modules.BUNDLE[theme]).read_text()
    src = (STATIC / page_modules.file_name(theme, "autopilot")).read_text()
    assert page_modules.PANELS == ("autopilot",) and "autopilot:" in page_modules.versions_attr(theme, server._static_versions())
    assert src.count("window.TauPage('autopilot', (T) => {") == 1
    for code in PANEL_CODE:
        assert code in src and code not in bundle, (theme, code)
    # The bundle keeps one stand-in per function the pill calls, each forwarding once the file has run.
    returned = set(re.search(r"\n  return \{([\w, ]+)\};\n\}\);\n$", src).group(1).split(", "))
    forwarded = set(re.findall(r"PAGES\.autopilot\.(\w+)\(", bundle))
    assert returned == forwarded == {"apBuildShell", "apStopChat", "apUpdate"}
    for name in returned:
        assert re.search(r"\n  function %s\(" % name, src) and re.search(r"\n  function %s\(" % name, bundle)
    assert all(page_modules.page_for(path) != "autopilot" for path in PATHS)  # no page's shell preloads it


# A shared page file (page-<name>.js): one file both themes load, so one version that each theme's shell names,
# serves, preloads and counts in its build as it does its own page files. Each bundle fetches it by that name
# (pageSrc's PAGE_SHARED), and what a theme draws its own way in it comes from the bundle's shared() list (theme).
def test_both_themes_load_the_one_shared_page_file_and_their_bundles_name_it():
    assert page_modules.SHARED == ("autopilot", "admin", "community")
    versions = server._static_versions()
    for name in page_modules.SHARED:
        f = "page-%s.js" % name
        assert not list(STATIC.glob("app-%s.js" % name)) and not list(STATIC.glob("app.meridian-%s.js" % name))
        assert page_modules.FILES.count(f) == 1 and (STATIC / f).is_file()
        for theme in page_modules.BUNDLE:
            assert page_modules.file_name(theme, name) == f
            assert "%s:%s" % (name, versions[f]) in page_modules.versions_attr(theme, versions).split(",")
        # Comment-stripped and warmed like the other page files.
        assert f in server._STATIC_NAMES and f in static_strip.NAMES
    for theme, bundle_name in page_modules.BUNDLE.items():
        bundle = (STATIC / bundle_name).read_text()
        assert "\n  const PAGE_SHARED = [%s];\n" % ", ".join("'%s'" % n for n in page_modules.SHARED) in bundle
        assert "'/static/' + (PAGE_SHARED.includes(name) ? 'page-' : '%s') + name + '.js'" % page_modules.PREFIX[theme] in bundle
        share = re.search(r"const shared = \(\) => shareMap \|\| \(shareMap = new Proxy\(\{(.*?)\}", bundle, re.S).group(1)
        assert re.findall(r"\btheme: '(\w+)'", share) == [theme]


@pytest.mark.parametrize("theme", ["tau", "meridian"])
def test_the_shared_page_file_is_served_versioned_and_named_in_each_themes_shell(web, theme):
    port, account = web
    account["ui_theme"] = theme
    versions = server._static_versions()
    v = versions["page-autopilot.js"]
    src = (STATIC / "page-autopilot.js").read_text()
    r, body = _get(port, "/static/page-autopilot.js?v=" + v, cookie="rsid=abc", accept_encoding="gzip")
    assert r.status == 200 and r.getheader("Content-Type") == "text/javascript; charset=utf-8"
    assert r.getheader("Cache-Control") == webperf.IMMUTABLE and r.getheader("Content-Encoding") == "gzip"
    r, body = _get(port, "/static/page-autopilot.js?v=" + v)
    assert body.count(b"\n") == src.count("\n") and b"window.TauPage('autopilot', (T) => {" in body
    assert b"// The float is the single home for autopilot" not in body and "// The float is the single home for autopilot" in src
    r, _ = _get(port, "/static/page-autopilot.js?v=0000000000")
    assert r.status == 200 and r.getheader("Cache-Control") == webperf.REVALIDATE
    for path in PATHS:
        _, body = _get(port, path, cookie="rsid=abc")
        html = body.decode()
        # Named by its version for either theme's bundle; preloaded by none (a panel), its version in each build.
        for t, key in (("tau", "data-tau-pages"), ("meridian", "data-mer-pages")):
            assert '%s="%s"' % (key, page_modules.versions_attr(t, versions)) in html and "autopilot:%s" % v in html
        assert "page-autopilot.js" not in [f for f, _ in _preloads(html)], path
    assert page_modules.build_version(theme, versions) != page_modules.build_version(theme, dict(versions, **{"page-autopilot.js": "c" * 10}))


@pytest.mark.parametrize("theme", ["tau", "meridian"])
def test_a_shared_page_files_page_is_preloaded_by_its_one_name_in_each_theme(theme):
    # A page (not a panel) whose file both themes load: each theme's signed-in shell preloads page-<name>.js.
    versions = dict(server._static_versions(), **{"page-admin.js": "a1b2c3d4e5"})
    assert page_modules.file_name(theme, "admin") == "page-admin.js"
    for path in ("/admin", "/system", "/settings/system"):
        assert page_modules.preload(theme, path, versions) == '\n<link rel="preload" href="/static/page-admin.js?v=a1b2c3d4e5" as="script">'
        assert page_modules.preload(theme, path, versions, signed_in=False) == ""
    assert "admin:a1b2c3d4e5" in page_modules.versions_attr(theme, versions).split(",")
    assert page_modules.build_version(theme, versions) != page_modules.build_version(theme, server._static_versions())


@pytest.mark.parametrize("theme", ["tau", "meridian"])
@pytest.mark.parametrize("name,paths,comment", [
    ("admin", ("/admin", "/system"), "// ---------- system map ----------"),
    ("community", ("/community",), "// ---------- community ----------"),
])
def test_a_shared_page_file_is_served_once_for_both_themes(web, theme, name, paths, comment):
    # The operator pages (Admin, the System map) are one file, and so is Community: either theme's shell preloads it by
    # its one version.
    port, account = web
    account["ui_theme"] = theme
    f = "page-%s.js" % name
    v = server._static_versions()[f]
    src = (STATIC / f).read_text()
    r, body = _get(port, "/static/%s?v=%s" % (f, v), cookie="rsid=abc", accept_encoding="gzip")
    assert r.status == 200 and r.getheader("Cache-Control") == webperf.IMMUTABLE and r.getheader("Content-Encoding") == "gzip"
    r, body = _get(port, "/static/%s?v=%s" % (f, v))
    assert body.count(b"\n") == src.count("\n") and ("window.TauPage('%s', (T) => {" % name).encode() in body
    assert comment.encode() not in body and comment in src
    for path in paths:
        _, body = _get(port, path, cookie="rsid=abc")
        assert _preloads(body.decode()) == [(f, v)], path


# Funds' own files: the perps, broker and Alpaca paper scripts and stylesheets. They were linked by every
# page's shell, the stylesheets render-blocking in <head>, though only Funds uses them (#536); then by
# Funds' shell alone, where on a phone's slow network they still held its first figure back (the bundle,
# deferred behind their three scripts, waited for them). No shell links them now: the Funds page file
# asks the bundle for them once its figures have painted (pageAssets).
FUNDS_FILES = ("broker-connections.css", "alpaca-paper.css", "kalshi-perps-live.css",
               "alpaca-paper.js", "kalshi-perps-live.js", "broker-connections.js")


@pytest.mark.parametrize("theme", ["tau", "meridian"])
@pytest.mark.parametrize("cookie", [None, "rsid=abc"])
def test_no_shell_links_funds_own_files_ahead_of_the_first_figure_and_every_shell_names_them(web, theme, cookie):
    port, account = web
    account["ui_theme"] = theme
    versions = server._static_versions()
    assert page_modules.ASSETS == {"funds": FUNDS_FILES}
    for path in PATHS:
        _, body = _get(port, path, cookie=cookie)
        html = body.decode()
        head = html.split("</head>")[0]
        # The first figure waits on the theme's stylesheet, boot.js, the shared core, the bundle and the page's
        # own file (preloaded beside them) and nothing else: one render-blocking stylesheet, and the deferred
        # scripts, boot.js, the core then the bundle, with nothing deferred ahead of them. Funds' paths too.
        linked = re.findall(r'<link rel="stylesheet" href="/static/([a-z.-]+\.css)\?v=([0-9a-f]+)"', head)
        scripts = re.findall(r'<script src="/static/([a-z.-]+\.js)\?v=([0-9a-f]+)"[^>]*>', html)
        assert [f for f, _ in linked] in (["app.css"], ["app.meridian.css"]), path
        assert [f for f, _ in scripts] in (["boot.js", "core.js", "app.js"], ["boot.js", "core.js", "app.meridian.js"], ["boot.js"]), path  # boot.js alone picks the theme
        if cookie and page_modules.page_for(path) == "funds":  # signed in: the core and the theme's own bundle, right after boot.js
            own = ["app.meridian.css", "boot.js", "core.js", "app.meridian.js"] if theme == "meridian" else ["app.css", "boot.js", "core.js", "app.js"]
            assert [f for f, _ in linked + scripts] == own, path
        assert all(v == versions[f] for f, v in linked + scripts)
        assert not re.search(r'<(?:link|script)[^>]+/static/(?:%s)' % "|".join(re.escape(f) for f in FUNDS_FILES), html), path
        # Named for the bundle, by URL, in ASSETS' order: the paper staging smoke (scripts/paper_staging_smoke.py)
        # still finds the Alpaca paper files in the Funds shell, its script ahead of the broker one.
        assert 'data-page-assets="%s"' % " ".join("funds:/static/%s?v=%s" % (f, versions[f]) for f in FUNDS_FILES) in html
        assert "/static/alpaca-paper.css?v=" in html and html.index("/static/alpaca-paper.js?v=") < html.index("/static/broker-connections.js?v=")


# The shared core (core.js): the pure helpers both themes' bundles take from window.TauCore as they start, so it
# runs right before the bundle in every shell that links one, in both themes, signed in or out. A shell that
# leaves the theme to boot.js names the core for it (data-core-js), and boot.js adds it ahead of the bundle.
@pytest.mark.parametrize("theme", ["tau", "meridian"])
@pytest.mark.parametrize("cookie", [None, "rsid=abc", "tau_ui=%s"])
def test_every_shell_runs_the_shared_core_right_before_its_bundle(web, theme, cookie):
    port, account = web
    account["ui_theme"] = theme
    versions = server._static_versions()
    assert page_modules.CORE == "core.js" and "core.js" in server._STATIC_NAMES
    for path in PATHS:
        _, body = _get(port, path, cookie=cookie and cookie.replace("%s", theme))
        html = body.decode()
        scripts = re.findall(r'<script src="/static/([a-z.-]+\.js)\?v=([0-9a-f]+)" defer></script>', html)
        assert all(v == versions[f] for f, v in scripts), path
        assert 'data-core-js="/static/core.js?v=%s"' % versions["core.js"] in html, path
        # Only Tau has the legal pages, so their shell knows the theme on any device.
        known = "tau" if path in ("/terms", "/privacy") else theme if cookie else None
        if known is None:  # boot.js picks the theme, and adds the core and the bundle itself
            assert [f for f, _ in scripts] == ["boot.js"], path
            continue
        assert [f for f, _ in scripts] == ["boot.js", "core.js", page_modules.BUNDLE[known]], path


def test_the_core_is_served_like_a_bundle_immutable_at_its_version_compressed_and_without_its_comments(web):
    port, _ = web
    v = server._static_versions()["core.js"]
    r, body = _get(port, "/static/core.js?v=" + v)
    assert r.status == 200 and r.getheader("Content-Type") == "text/javascript; charset=utf-8"
    assert r.getheader("Cache-Control") == webperf.IMMUTABLE
    src = (STATIC / "core.js").read_text()
    assert body.count(b"\n") == src.count("\n") and b"window.TauCore = Object.freeze" in body
    assert b"// The separator between pieces of one line" not in body and "// The separator between pieces of one line" in src
    r, _ = _get(port, "/static/core.js?v=" + v, accept_encoding="gzip")
    assert r.getheader("Content-Encoding") == "gzip"
