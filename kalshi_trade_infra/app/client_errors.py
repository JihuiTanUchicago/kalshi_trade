"""Page error reports from the browser (POST /api/client-errors): validation and an in-memory rate limit.

boot.js sends one report when a page hits an uncaught error or unhandled rejection, and the app bundle
sends one when an API call or a page bug ends in an error the page shows. Each report locates the bug
and nothing else: kind, message, script file name, line/col, page path, theme, build. This module
cleans what arrives (a signed-out visitor can send it too), so a report can never carry a query string,
an email, a token or a long free-form body into the table, whatever the client sent.

Stdlib only. The limiter lives in the web process, like webperf's window: a restart resets it.
"""
from __future__ import annotations

import ipaddress
import re
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Iterable, Optional

MAX_BODY = 4096          # bytes; a report is ~300 of them
MESSAGE_MAX = 300
SRC_MAX = 80
PATH_MAX = 120
KINDS = ("error", "rejection", "api", "view")
THEMES = ("tau", "meridian")
WINDOW_S = 600.0
PER_SOURCE = 30          # reports per IP (or per session) per window
GLOBAL_MAX = 300         # every source together per window: the hard bound on writes

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_QUERY = re.compile(r"\?[^\s'\"<>()]*=[^\s'\"<>()]*")    # ?a=b... wherever it appears
_TOKEN = re.compile(r"[A-Za-z0-9_\-+=]{24,}")             # keys, session ids, JWT parts, hashes
_LONG_NUM = re.compile(r"\d{9,}")                         # card or phone numbers
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
_ID = re.compile(r"/\d+(?=/|$)")
_PATH_BAD = re.compile(r"[^A-Za-z0-9/_:.\-]")
_SRC_OK = re.compile(r"^[A-Za-z0-9._-]+$")
_VER_OK = re.compile(r"^[0-9a-f]{1,16}$")


def scrub(text: Any, limit: int = MESSAGE_MAX) -> str:
    """A message with what could identify someone taken out: emails, URL query strings, long
    token-like runs and long digit runs. Whitespace collapsed, cut to `limit` characters."""
    s = _CTRL.sub(" ", str(text if text is not None else ""))
    s = _QUERY.sub("", s)
    s = _EMAIL.sub("<email>", s)
    s = _TOKEN.sub("<redacted>", s)
    s = _LONG_NUM.sub("<n>", s)
    return " ".join(s.split())[:limit]


def page_path(value: Any) -> str:
    """The route only: no query or fragment, numeric ids as :id (so /research/12 and /research/13 group)."""
    p = str(value or "").split("?", 1)[0].split("#", 1)[0]
    if not p.startswith("/"):
        return "?"
    return _PATH_BAD.sub("", _ID.sub("/:id", p))[:PATH_MAX] or "/"


def _basename(value: Any) -> str:
    f = str(value or "").split("?", 1)[0].split("#", 1)[0]
    f = f.rsplit("/", 1)[-1][:SRC_MAX]
    return f if _SRC_OK.match(f) else ""


def _pos(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    n = int(value)
    return n if 0 <= n <= 10_000_000 else None


def clean(body: Dict[str, Any]) -> Dict[str, Any]:
    """The row to store, from a report body. Raises ValueError on a report that isn't one.
    Unknown fields are dropped; every kept field is bounded."""
    kind = body.get("kind")
    if kind not in KINDS:
        raise ValueError("kind must be one of: %s" % ", ".join(KINDS))
    message = scrub(body.get("message")) if isinstance(body.get("message"), str) else ""
    if not message:
        raise ValueError("message is required")
    theme = body.get("theme") if body.get("theme") in THEMES else ""
    ver = body.get("ver") if isinstance(body.get("ver"), str) and _VER_OK.match(body["ver"]) else ""
    return {"kind": kind, "message": message, "src": _basename(body.get("src")),
            "line": _pos(body.get("line")), "col": _pos(body.get("col")),
            "path": page_path(body.get("path")), "theme": theme, "ver": ver}


def client_ip(handler: Any) -> str:
    """The address to rate-limit by: the peer, or, when the peer is a proxy on this box or network,
    the address that proxy saw (the last X-Forwarded-For entry; earlier entries are the client's own
    words). Behind CloudFront that can be an edge address shared by many visitors, which is why the
    per-source limit is generous and GLOBAL_MAX is the hard bound. Never stored."""
    peer = (getattr(handler, "client_address", None) or ("",))[0] or ""
    try:
        private = ipaddress.ip_address(peer).is_private
    except ValueError:
        private = False
    headers = getattr(handler, "headers", None)
    fwd = (headers.get("X-Forwarded-For") if headers else None) or ""
    if private and fwd.strip():
        return fwd.split(",")[-1].strip()[:64]
    return peer


class RateLimiter:
    """Sliding-window counts per key plus one global count. allow() records the hit only when every
    key (and the global count) is under its limit."""

    def __init__(self, per_key: int = PER_SOURCE, global_max: int = GLOBAL_MAX, window_s: float = WINDOW_S,
                 max_keys: int = 5000):
        self.per_key, self.global_max, self.window_s, self.max_keys = per_key, global_max, window_s, max_keys
        self._hits: Dict[str, Deque[float]] = {}
        self._all: Deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self, keys: Iterable[str], now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        cutoff = now - self.window_s
        with self._lock:
            if len(self._hits) > self.max_keys:  # a spray of addresses can't grow this without bound
                self._hits = {k: q for k, q in self._hits.items() if q and q[-1] >= cutoff}
                if len(self._hits) > self.max_keys:
                    self._hits.clear()
            while self._all and self._all[0] < cutoff:
                self._all.popleft()
            buckets = [self._hits.setdefault(k, deque()) for k in keys]
            for q in buckets:
                while q and q[0] < cutoff:
                    q.popleft()
            if len(self._all) >= self.global_max or any(len(q) >= self.per_key for q in buckets):
                return False
            self._all.append(now)
            for q in buckets:
                q.append(now)
            return True


LIMITER = RateLimiter()
