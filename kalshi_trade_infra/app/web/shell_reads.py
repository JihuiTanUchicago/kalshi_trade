"""The page's first reads, carried in a signed-in app page's shell.

A signed-in shell already carries /api/me's answer (app.server Handler._shell_boot). The page's own
first read, the one its figures wait on, still went out only once app.js had arrived and run: one
more round trip before the first figure, ~0.6s on a phone on a slow network, on every full load.

For the pages whose first read the shell can name exactly, the shell asks that route itself and
carries the answer, keyed by the URL the page asks for. The page takes it in place of that one
request (api() in both bundles), once, during its first render. Same handler, same arguments, same
JSON as the page's own request, read a moment earlier. A page whose URL carries a query (filters, a
fresh form) carries nothing and asks as before; so does any read that fails.

The dashboard also carries the autopilot status: its autopilot card sits above the figures, and drawn
a round trip after them it pushed them down the screen.
"""
from __future__ import annotations

import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.web.http import ApiError, Ctx
from app.web.routes.chat import autopilot_status
from app.web.routes.dashboard import dashboard
from app.web.routes.deployments import list_deployments
from app.web.routes.research import get_run, list_runs
from app.web.routes.strategies import list_strategies

# The dashboard asks with ?since= from the tau_visit cookie ("<since>.<last seen>", epoch seconds), as
# visitStart() in app.js and app.meridian.js works it out: after a gap this long the last visit ended
# when it was last seen, else the visit goes on from its own start. No cookie, no since.
VISIT_GAP = 1800
_VISIT = re.compile(r"(\d+)\.(\d+)")
_RUN_PAGE = re.compile(r"^/research/(\d+)$")

MakeCtx = Callable[[Tuple[str, ...], Dict[str, str]], Ctx]
Request = Tuple[str, Callable, Tuple[str, ...], Dict[str, str]]  # URL the page asks, handler, path params, query


def dashboard_since(cookie: Optional[str], now: Optional[float] = None) -> Optional[int]:
    """The dashboard's ?since= for this load, from the tau_visit cookie as the page reads it."""
    m = _VISIT.match(cookie or "")
    if not m:
        return None
    since, seen = int(m.group(1)), int(m.group(2))
    at = seen if int(time.time() if now is None else now) - seen > VISIT_GAP else since
    return at or None


def first_requests(path: str, query: str, cookies: Dict[str, str]) -> List[Request]:
    """The reads an app page asks for first, as the page will ask them; [] when the shell can't name them."""
    if query:
        return []
    if path in ("/", "/dashboard"):
        at = dashboard_since(cookies.get("tau_visit"))
        return [(("/api/dashboard?since=%d" % at if at else "/api/dashboard"), dashboard, (), ({"since": str(at)} if at else {})),
                ("/api/autopilot/status", autopilot_status, (), {})]
    if path == "/research":
        return [("/api/runs", list_runs, (), {})]
    if path == "/strategies":
        return [("/api/strategies?page=0", list_strategies, (), {"page": "0"})]
    if path == "/deploy":
        return [("/api/deployments", list_deployments, (), {})]
    m = _RUN_PAGE.match(path)
    if m:
        return [("/api/runs/%s?after=0" % m.group(1), get_run, (m.group(1),), {"after": "0"})]
    return []


def first_reads(path: str, query: str, cookies: Dict[str, str], make_ctx: MakeCtx) -> Tuple[List[Dict[str, Any]], List[str]]:
    """([{url, body}] for each first read that answered, the cookies they set). A read that fails is
    left out: the page asks for it itself and shows what it gets."""
    reads: List[Dict[str, Any]] = []
    set_cookies: List[str] = []
    for url, fn, params, q in first_requests(path, query, cookies):
        try:
            ctx = make_ctx(params, q)
            reads.append({"url": url, "body": fn(ctx)})
            set_cookies += ctx.set_cookies
        except ApiError:
            continue  # a missing session page, say: the page's own read says so
        except Exception as e:  # noqa: BLE001 - the shell must never fail on this
            sys.stdout.write("[app] shell first read failed (%s); the page reads %s itself\n" % (type(e).__name__, url))
            sys.stdout.flush()
    return reads, set_cookies
