"""Request timing for Tau's web server: a bounded in-memory window of recent requests, the
per-route p50/p95 and 5xx rate over it, gzip for compressible responses (and brotli for static
files, when the brotli module is installed), and the cache headers and validators for static files.

Stdlib only, apart from the optional brotli. The window lives in the web process, so it resets on a
restart (a deploy); the on-box watchdog reads it from /internal/perf, which only answers loopback callers.
"""
from __future__ import annotations

import gzip
import re
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

WINDOW = 20000  # ~2-3 days at today's traffic; ~1.5MB of tuples
_ROWS: Deque[Tuple[float, str, int, float]] = deque(maxlen=WINDOW)
_LOCK = threading.Lock()
STARTED_AT = time.time()

# Route key for the stats: numeric ids collapse so /api/runs/2624 and /api/runs/2625 are one route.
_ID = re.compile(r"/\d+(?=/|$)")
_KNOWN_PREFIXES = ("/api/", "/auth/", "/static/", "/healthz", "/internal/")


def route_key(method: str, path: str, spa: bool = False) -> str:
    if spa:
        return method + " <page>"
    if not path.startswith(_KNOWN_PREFIXES):
        return method + " <other>"  # scanner noise (/wp-login.php, /.env) is one bucket, not 500 routes
    if path.startswith("/static/"):
        return method + " /static/*"
    return method + " " + _ID.sub("/:id", path)


def record(key: str, status: int, ms: float, now: Optional[float] = None) -> None:
    with _LOCK:
        _ROWS.append((now if now is not None else time.time(), key, status, ms))


def _pct(sorted_ms: List[float], q: float) -> float:
    if not sorted_ms:
        return 0.0
    i = min(len(sorted_ms) - 1, max(0, int(round(q * (len(sorted_ms) - 1)))))
    return round(sorted_ms[i], 1)


def summary(window_s: float = 900, now: Optional[float] = None, top: int = 25) -> Dict:
    """p50/p95/max and 5xx count per route over the last window_s seconds, plus the API total.
    API = /api/* and /auth/* (what the pages wait on); static files and scanner noise are excluded
    from the API total so a burst of 404 probes can't move the SLO numbers."""
    now = now if now is not None else time.time()
    cutoff = now - window_s
    with _LOCK:
        rows = [r for r in _ROWS if r[0] >= cutoff]
    by: Dict[str, List[Tuple[int, float]]] = {}
    for _, key, status, ms in rows:
        by.setdefault(key, []).append((status, ms))
    routes = []
    api_ms: List[float] = []
    api_5xx = 0
    for key, vals in by.items():
        ms_sorted = sorted(v[1] for v in vals)
        n5 = sum(1 for v in vals if v[0] >= 500)
        routes.append({"route": key, "n": len(vals), "p50_ms": _pct(ms_sorted, 0.5), "p95_ms": _pct(ms_sorted, 0.95),
                       "max_ms": round(ms_sorted[-1], 1), "5xx": n5})
        if " /api/" in key or " /auth/" in key:
            api_ms.extend(ms_sorted)
            api_5xx += n5
    api_ms.sort()
    routes.sort(key=lambda r: r["p95_ms"] * r["n"], reverse=True)  # rank by total time users spent waiting
    return {
        "window_s": window_s,
        "uptime_s": int(now - STARTED_AT),
        "requests": len(rows),
        "api": {"n": len(api_ms), "p50_ms": _pct(api_ms, 0.5), "p95_ms": _pct(api_ms, 0.95),
                "5xx": api_5xx, "5xx_rate": round(api_5xx / len(api_ms), 4) if api_ms else 0.0},
        "routes": routes[:top],
    }


_COMPRESSIBLE = ("application/json", "text/", "image/svg+xml")
MIN_GZIP = 1024
# Static files compress once per content version: (coding, name, content hash) -> bytes. Keyed on the
# hash of the bytes being sent, so a compressed copy can never outlive the file it was made from.
_Z_CACHE: Dict[Tuple[str, str, str], bytes] = {}
_Z_LOCK = threading.Lock()
_Z_BUSY: Dict[Tuple[str, str, str], threading.Lock] = {}

# Brotli is optional: pinned in requirements.txt, but with it missing static files go out gzip, as before.
try:
    import brotli as _brotli
except ImportError:  # pragma: no cover - exercised by monkeypatching _brotli to None
    _brotli = None


def compressible(ctype: str, length: int) -> bool:
    """Whether this response can go out compressed, so it varies by Accept-Encoding (even when sent as is)."""
    return length >= MIN_GZIP and ctype.startswith(_COMPRESSIBLE)


def static_codings() -> Tuple[str, ...]:
    """The encodings a static file can go out in, besides as is."""
    return ("br", "gzip") if _brotli is not None else ("gzip",)


def _accepts(accept_encoding: Optional[str], coding: str) -> float:
    """The q the client gives a content coding by name (0 if not listed, refused, or malformed).
    "*" is not honored: an encoding we send must be one the client named."""
    for part in (accept_encoding or "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if name.strip() != coding:
            continue
        q = 1.0
        for p in params.split(";"):
            k, _, v = p.replace(" ", "").partition("=")
            if k == "q":
                try:
                    q = float(v)
                except ValueError:
                    return 0.0
        return q if 0 < q <= 1 else 0.0
    return 0.0


def wants_gzip(accept_encoding: Optional[str], ctype: str, length: int) -> bool:
    return compressible(ctype, length) and _accepts(accept_encoding, "gzip") > 0


def pick_encoding(accept_encoding: Optional[str], ctype: str, length: int, allow_br: bool) -> Optional[str]:
    """The content coding to send: br, gzip, or None for as is. br only where allowed (static files,
    compressed once and cached) and only with the brotli module installed; it wins a tie with gzip."""
    if not compressible(ctype, length):
        return None
    gz = _accepts(accept_encoding, "gzip")
    br = _accepts(accept_encoding, "br") if allow_br and _brotli is not None else 0.0
    if br > 0 and br >= gz:
        return "br"
    return "gzip" if gz > 0 else None


def _compress(coding: str, body: bytes, static: bool) -> bytes:
    if coding == "br":
        return _brotli.compress(body, mode=_brotli.MODE_TEXT, quality=11)  # ~1s for app.js, once per version
    return gzip.compress(body, compresslevel=6 if static else 5, mtime=0)


def compress(body: bytes, coding: str, cache_key: Optional[Tuple[str, str]] = None) -> bytes:
    """Encode a body as "gzip" or "br". Static files pass (name, content hash) so each version is
    compressed once; concurrent first requests for it wait on one compression (brotli releases the GIL)."""
    if cache_key is None:
        return _compress(coding, body, False)
    key = (coding,) + tuple(cache_key)
    out = _Z_CACHE.get(key)
    if out is not None:
        return out
    with _Z_LOCK:
        busy = _Z_BUSY.setdefault(key, threading.Lock())
    with busy:
        out = _Z_CACHE.get(key)
        if out is None:
            out = _compress(coding, body, True)
            with _Z_LOCK:
                if len(_Z_CACHE) >= 128:  # old versions pile up only if files change under a running server
                    _Z_CACHE.clear()
                _Z_CACHE[key] = out
                _Z_BUSY.pop(key, None)
    return out



# -- caching for static files and the page shell ---------------------------------------------------
# Bundles are linked as /static/<name>?v=<content hash>, so a URL whose v is the file's current hash
# can be cached for a year, by the browser and by CloudFront's /static/* behavior (keyed on path + v).
# Any other request for a bundle (no v, or another build's v: an old page shell, or a deploy that was
# rolled back) gets the current file with a revalidating cache instead. An immutable answer there would
# pin those bytes under that URL for a year, so a later deploy of that hash would get the wrong file.
# Self-hashed names (the fonts, rubik-latin-691cd1d9b4.woff2) are always immutable.
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
_HASHED_NAME = re.compile(r"-[0-9a-f]{10}\.[a-z0-9]+$")


def static_cache_control(name: str, query: str, current: Optional[str]) -> str:
    if _HASHED_NAME.search(name):
        return IMMUTABLE
    v = next((p[2:] for p in (query or "").split("&") if p.startswith("v=")), None)
    return IMMUTABLE if current and v == current else REVALIDATE


def etag(version: str) -> str:
    """Weak: one file goes out as brotli, gzip or as is, so the validator names the content, not the
    bytes. A 304 to any of them is right: each client's stored copy decodes to the same file."""
    return 'W/"%s"' % version


def etag_matches(if_none_match: Optional[str], tag: str) -> bool:
    """RFC 9110 weak comparison of an If-None-Match header against our ETag ("*" matches any)."""
    want = tag[2:] if tag.startswith("W/") else tag
    for part in (if_none_match or "").split(","):
        part = part.strip()
        if part and (part == "*" or (part[2:] if part.startswith("W/") else part) == want):
            return True
    return False


def embed_json(payload_json: str) -> str:
    """JSON text made safe inside a <script type="application/json"> data block: nothing that could
    close the element or start markup survives, and JSON.parse reads back the same value."""
    return (payload_json.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
