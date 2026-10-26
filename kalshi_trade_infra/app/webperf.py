"""Request timing for Tau's web server: a bounded in-memory window of recent requests, the
per-route p50/p95 and 5xx rate over it, gzip for compressible responses, and the cache headers
and validators for static files.

Stdlib only. The window lives in the web process, so it resets on a restart (a deploy); the
on-box watchdog reads it from /internal/perf, which only answers loopback callers.
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
_GZ_CACHE: Dict[Tuple[str, int, int], bytes] = {}


def wants_gzip(accept_encoding: Optional[str], ctype: str, length: int) -> bool:
    if length < MIN_GZIP or not ctype.startswith(_COMPRESSIBLE):
        return False
    for part in (accept_encoding or "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if name.strip() == "gzip":
            return params.replace(" ", "") != "q=0"
    return False


def gzip_bytes(body: bytes, cache_key: Optional[Tuple[str, int, int]] = None) -> bytes:
    """gzip a body. Static files pass (path, mtime_ns, size) so each version compresses once."""
    if cache_key is not None and cache_key in _GZ_CACHE:
        return _GZ_CACHE[cache_key]
    out = gzip.compress(body, compresslevel=6 if cache_key is not None else 5, mtime=0)
    if cache_key is not None:
        if len(_GZ_CACHE) > 64:
            _GZ_CACHE.clear()
        _GZ_CACHE[cache_key] = out
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
    """Weak: one file goes out gzipped or not, so the validator names the content, not the bytes."""
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
