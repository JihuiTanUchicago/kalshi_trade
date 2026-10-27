"""The bundles, page files and stylesheets go out without their comments (app/web/static_strip.py).

Only a line that is a // comment and nothing else goes, and only where it is one: never a line of a
template literal, a string or a regex that happens to start with //. Every line keeps its number, so
error reports still point at the source. The shipped files are checked against V8 itself: each line the
server leaves out, put back as a token that is a syntax error only in code, must stop the file compiling."""
import gzip
import hashlib
import http.client
import json
import re
import shutil
import subprocess
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from app import server
from app.web import static_strip

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
JS = sorted(n for n in static_strip.NAMES if n.endswith(".js"))
CSS = sorted(n for n in static_strip.NAMES if n.endswith(".css"))


def test_only_whole_line_comments_in_code_go_and_every_line_stays():
    src = "\n".join([
        "(() => {",                                    # 1
        "  // a comment",                              # 2: goes
        "  const u = 'http://x' // trailing stays;",   # 3
        "  const t = `a",                              # 4
        "// in a template: text, not a comment",       # 5
        "  ${f(1, {",                                  # 6
        "    // in the template's code: goes",         # 7
        "    k: 1})}",                                 # 8
        "  //b`;",                                     # 9: still in the template
        "  const re = /\\/\\/[/]x/g, d = a / b / c;",  # 10: a regex, then division
        "  if (re.test(u)) return /x/.source",         # 11
        "  /* a block",                                # 12
        "  // inside it */",                           # 13
        "  const s = 'a\\",                            # 14: a string over a line continuation
        "// still the string';",                       # 15
        "\t// tab-indented: goes",                     # 16
        "})();",
    ])
    assert static_strip.js_comment_lines(src) == [2, 7, 16]
    out = static_strip.strip_js(src)
    assert out.count("\n") == src.count("\n")
    assert out.split("\n")[1] == "" and out.split("\n")[4] == "// in a template: text, not a comment"


@pytest.mark.parametrize("src", ["const a = `open", "const s = 'open\n';", "/* open", "x = /a\n/;"])
def test_a_file_it_cant_follow_goes_out_as_it_is(src):
    with pytest.raises(ValueError):
        static_strip.js_comment_lines(src)
    body = src.encode()
    assert static_strip.served("app.js", body, "d0" + hashlib.sha256(body).hexdigest()[:8]) == body


def test_css_comments_go_but_strings_urls_and_line_numbers_stay():
    src = ('a { content: "/* not */"; }\n/* one\ntwo */\nb { background: url(data:x/*y) }\n'
           "c{x:1}/**/d{y:2} e { font: 'it\\'s /*' }")
    out = static_strip.strip_css(src)
    assert out == ('a { content: "/* not */"; }\n\n\nb { background: url(data:x/*y) }\n'
                   "c{x:1} d{y:2} e { font: 'it\\'s /*' }")
    assert out.count("\n") == src.count("\n")


def test_only_the_named_files_change_and_each_version_is_worked_out_once():
    body = b"// a comment\nvar x;\n"
    assert static_strip.served("boot.js", body, "aaaaaaaaaa") == body
    out = static_strip.served("app.js", body, "bbbbbbbbbb")
    assert out == b"\nvar x;\n" and static_strip.served("app.js", b"changed", "bbbbbbbbbb") is out
    assert set(static_strip.NAMES) >= {"app.js", "app.meridian.js", "app.css", "app.meridian.css", "app-research.js"}


@pytest.mark.parametrize("name", CSS)
def test_each_stylesheet_loses_exactly_its_comments(name):
    # In today's stylesheets no string holds "/*", so every comment is what a plain search finds; a
    # stylesheet where that stops being true fails here until checked by hand.
    src = (STATIC / name).read_text(encoding="utf-8")
    naive = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n") or " ", src, flags=re.S)
    assert static_strip.strip_css(src) == naive


_V8_CHECK = r"""
const vm = require('vm'), fs = require('fs');
const bad = [];
for (const [file, lines] of Object.entries(JSON.parse(fs.readFileSync(0, 'utf8')))) {
  const src = fs.readFileSync(file, 'utf8'), ls = src.split('\n');
  new vm.Script(src, { filename: file });
  for (const n of lines) {
    const c = ls.slice();
    c[n - 1] = '@@@';  // a syntax error in code; in a string or a template, just text
    try { new vm.Script(c.join('\n')); bad.push(file + ':' + n); } catch (e) { if (!(e instanceof SyntaxError)) throw e; }
  }
}
console.log(JSON.stringify(bad));
"""


def test_every_line_left_out_of_the_shipped_js_is_code_by_v8():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    lines = {str(STATIC / n): static_strip.js_comment_lines((STATIC / n).read_text(encoding="utf-8")) for n in JS}
    assert sum(map(len, lines.values())) > 1000  # the check has something to check
    out = subprocess.run([node, "-e", _V8_CHECK], input=json.dumps(lines), capture_output=True, text=True,
                         timeout=300, check=True)
    assert json.loads(out.stdout) == []
    # And the method can tell: the same token on a template's line still compiles.
    probe = subprocess.run([node, "-e", "new (require('vm').Script)('const t = `\\n@@@\\n`;')"], capture_output=True)
    assert probe.returncode == 0


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


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Accept-Encoding": "gzip"})
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    return r, gzip.decompress(raw) if r.getheader("Content-Encoding") == "gzip" else raw


@pytest.mark.parametrize("name", ["app.js", "app.meridian.js", "app-research.js", "app.css", "app.meridian.css"])
def test_served_without_comments_at_the_source_files_version(web, name):
    src = (STATIC / name).read_bytes()
    v = server._static_versions()[name]
    r, body = _get(web, "/static/%s?v=%s" % (name, v))
    assert r.status == 200 and r.getheader("ETag") == 'W/"%s"' % v  # still the source file's hash
    assert body.count(b"\n") == src.count(b"\n") and len(body) < len(src) * 0.95
    if name.endswith(".js"):
        assert body.decode() == static_strip.strip_js(src.decode()) and not static_strip.js_comment_lines(body.decode())
    else:
        assert body.decode() == static_strip.strip_css(src.decode()) and b"/*" not in body


def test_other_static_files_go_out_byte_for_byte(web):
    for name in ("boot.js", "kalshi-perps-live.js", "alpaca-paper.css"):
        r, body = _get(web, "/static/" + name)
        assert r.status == 200 and body == (STATIC / name).read_bytes(), name
