"""Local UI preview: existing assets, no database or provider operations."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import hashlib
import json
import os
import re
import sys

static = Path(sys.argv[1]).resolve()
fixtures = json.loads((Path(__file__).parent / "app_fixtures.json").read_text())
preview_cookie = "tau_ui_preview"

class Preview(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, content_type, body, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def app_preview_enabled(self) -> bool:
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        value = cookies.get(preview_cookie)
        return value is not None and value.value == "1"

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        app_preview = self.app_preview_enabled()
        if path == "/healthz":
            return self.send(200, "application/json", b'{"ok":true,"mode":"frontend_preview"}')
        if path in ("/preview", "/preview/landing"):
            opening = path == "/preview"
            cookie = f"{preview_cookie}={'1' if opening else ''}; Path=/; HttpOnly; SameSite=Strict"
            if not opening:
                cookie += "; Max-Age=0"
            return self.send(303, "text/plain", b"", {
                "Location": "/dashboard" if opening else "/signin", "Set-Cookie": cookie,
            })
        if path in ("/auth/google", "/auth/google/callback"):
            return self.send(303, "text/plain", b"", {
                "Location": "/dashboard" if app_preview else "/signin",
            })
        if path.startswith("/api/") and app_preview:
            data = fixtures.get(path)
            if data is None:
                return self.send(404, "application/json", b'{"error":"No UI fixture for this route."}')
            query = parse_qs(url.query, keep_blank_values=True)
            if path == "/api/explore":
                rows = data["markets"]
                search = query.get("q", [""])[0].strip().lower()
                if search:
                    rows = [row for row in rows if search in " ".join(str(row.get(field) or "") for field in ("ti", "t", "s")).lower()]
                sort = query.get("sort", ["v24"])[0]
                if sort not in ("v24", "oi", "last"):
                    sort = "v24"
                try:
                    page = max(0, int(query.get("page", ["0"])[0]))
                except ValueError:
                    page = 0
                rows = sorted(rows, key=lambda row: float(row.get(sort) or 0), reverse=True)
                data = {**data, "matched": len(rows), "page": page, "per": 40, "sort": sort, "markets": rows[page * 40:(page + 1) * 40]}
            if path == "/api/explore/market" and query.get("ticker", [""])[0] != data.get("ticker"):
                return self.send(404, "application/json", b'{"error":"No UI fixture for this market."}')
            if path == "/api/strategies":
                rows = data["strategies"]
                for field in ("status", "market", "direction"):
                    value = query.get(field, [""])[0]
                    if value:
                        rows = [row for row in rows if row.get(field) == value]
                data = {"strategies": rows}
            if path == "/api/chat" or re.fullmatch(r"/api/sessions/(?:run|strategy)/\d+/chat", path) or re.fullmatch(r"/api/runs/\d+", path):
                try:
                    after = int(query.get("after", ["0"])[0])
                except ValueError:
                    return self.send(400, "application/json", b'{"error":"Invalid after value."}')
                field = "events" if path.startswith("/api/runs/") else "messages"
                data = {**data, field: [row for row in data[field] if row["id"] > after]}
            return self.send(200, "application/json", json.dumps(data).encode())
        if path.startswith(("/api/", "/auth/")):
            message = {"error": "Local frontend preview: account and data services are not configured."}
            return self.send(401 if path == "/api/me" else 503, "application/json", json.dumps(message).encode())
        if re.fullmatch(r"/(?:|dashboard|research(?:/\d+)?|strategies(?:/\d+)?|deploy|community|billing|admin|system|funds|explore|signin)", path):
            html = (static / "index.html").read_text()
            for token, name in (("css_v", "app.css"), ("js_v", "app.js"), ("session_v", "session-data.js"), ("chat_v", "session-chat.js"), ("artifacts_v", "research-artifacts.js"), ("icon_v", "icon.svg")):
                html = html.replace("{{" + token + "}}", hashlib.sha256((static / name).read_bytes()).hexdigest()[:12])
            preview_message = (
                '<strong>UI editing preview.</strong> Sample data only. Actions are disabled. '
                '<a href="/preview/landing" data-native style="color:inherit">View landing page</a>'
                if app_preview else
                '<strong>Local frontend preview.</strong> Google sign-in and account data need a configured backend. '
                '<a href="/preview" data-native style="color:inherit">Open the app UI with sample data</a>'
            )
            notice = (
                '<aside role="status" aria-label="Local preview notice" '
                'style="padding:6px 20px;background:#F0F0F0;color:#4F4F4F;'
                'border-bottom:1px solid #DBDBDB;font:12px/1.5 system-ui,sans-serif">'
                + preview_message + '</aside>'
            )
            html = html.replace('<div id="app"', notice + '\n<div id="app"', 1)
            return self.send(200, "text/html; charset=utf-8", html.encode())
        match = re.fullmatch(r"/static/([a-z0-9_.-]+\.(css|js|svg|png|ico|woff2))", path)
        target = static / match[1] if match else None
        if target is None or not target.is_file():
            return self.send(404, "text/plain", b"Not found")
        content_type = {"css": "text/css", "js": "text/javascript", "svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon", "woff2": "font/woff2"}[match[2]]
        return self.send(200, content_type, target.read_bytes())

    def do_POST(self):
        if urlsplit(self.path).path == "/api/logout":
            return self.send(200, "application/json", b'{"ok":true}', {
                "Set-Cookie": f"{preview_cookie}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
            })
        return self.send(503, "application/json", b'{"error":"UI preview: actions are disabled. Sample data is read-only."}')

if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8097
    server = ThreadingHTTPServer(("127.0.0.1", port), Preview)
    server.daemon_threads = True
    print(json.dumps({"url": f"http://127.0.0.1:{port}", "pid": os.getpid(), "mode": "frontend_preview"}), flush=True)
    server.serve_forever()
