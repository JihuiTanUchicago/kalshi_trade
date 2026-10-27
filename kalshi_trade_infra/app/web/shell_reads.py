"""The page's first reads, carried in a signed-in app page's shell.

A signed-in shell already carries /api/me's answer (app.server Handler._shell_boot). The page's own
first read, the one its figures wait on, still went out only once app.js had arrived and run: one
more round trip before the first figure, ~0.6s on a phone on a slow network, on every full load.

For the pages whose first read the shell can name exactly, the shell asks that route itself and
carries the answer, keyed by the URL the page asks for. The page takes it in place of that one
request (api() in both bundles), once, during its first render. Same handler, same arguments, same
JSON as the page's own request, read a moment earlier. A page whose URL carries a query (filters, a
fresh form) carries nothing and asks as before; so does any read that fails.

Billing asks with the browser's UTC offset (?tz=: its statement's days are the viewer's), which only the
browser knows. boot.js keeps it in the tau_tz cookie on every load and the shell names Billing's read
from that. No cookie yet (a first load on this device), no read; an offset that changed since (a clock
change, a trip) names a URL the page doesn't ask, and the page asks as before. It is carried only for an
account Stripe has no cards to list for: the saved-card list waits on Stripe, and a slow Stripe must
never hold the whole shell blank (the page's own read keeps it behind a skeleton instead).

Funds is carried by the same rule, always: its read asks Kalshi for the live and demo cash of an account
with a key (unless the server read it in the last minute), so the shell carries a version that never asks.
Everything from our own database (each book, its positions, P&L and history) is as /api/funds answers it;
a key's cash comes from its memo when kept, else is marked pending, with the last figure read and its age
if the memo holds one. The page draws it as "checking" (never $0) and asks /api/funds/cash?book= for it.
The shell names those asks beside the read ("then"), and boot.js starts them at once, so Kalshi's wait
runs while the bundle downloads instead of after the page has drawn; the page takes each answer once.

The dashboard also carries the autopilot status: its autopilot card sits above the figures, and drawn
a round trip after them it pushed them down the screen. Research carries its loop card's board for the
same reason (it pushed the session list down), but only while the server keeps one for the user: worked
out cold it takes seconds, and the shell never waits on that.
"""
from __future__ import annotations

import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.web.http import ApiError, Ctx
from app.web.routes.billing import asks_stripe, billing_state
from app.web.routes.chat import autopilot_status
from app.web.routes.dashboard import dashboard
from app.web.routes.deployments import list_deployments
from app.web.routes.funds import funds
from app.web.routes.research import get_run, list_runs, research_scoreboard, scoreboard_kept
from app.web.routes.strategies import list_strategies

# The dashboard asks with ?since= from the tau_visit cookie ("<since>.<last seen>", epoch seconds), as
# visitStart() in app.js and app.meridian.js works it out: after a gap this long the last visit ended
# when it was last seen, else the visit goes on from its own start. No cookie, no since.
VISIT_GAP = 1800
_VISIT = re.compile(r"(\d+)\.(\d+)")
_RUN_PAGE = re.compile(r"^/research/(\d+)$")
_TZ = re.compile(r"^-?\d{1,4}$")  # tau_tz: getTimezoneOffset() in minutes, as boot.js writes it
LOOP_DAYS = 14  # Research's loop card asks /api/research/scoreboard?days=14 (rsiLoopRead in both bundles)

MakeCtx = Callable[[Tuple[str, ...], Dict[str, str]], Ctx]
Request = Tuple[str, Callable, Tuple[str, ...], Dict[str, str]]  # URL the page asks, handler, path params, query


class NotKept(Exception):
    """A read the shell carries only when it answers from memory: the page asks for it itself."""


def kept_loop_board(ctx: Ctx) -> Dict[str, Any]:
    """Research's loop card board, as research_scoreboard answers it, while the server keeps one for the
    user; NotKept when it would be worked out now (4.4s p50 on prod, cold)."""
    if not scoreboard_kept(ctx.uid, LOOP_DAYS):
        raise NotKept
    return research_scoreboard(ctx)


def billing_without_stripe(ctx: Ctx) -> Dict[str, Any]:
    """Billing's first read, as billing_state answers it, for an account it wouldn't ask Stripe for;
    NotKept for one it would (the saved cards wait on Stripe, up to its timeout)."""
    if asks_stripe(ctx):
        raise NotKept
    return billing_state(ctx)


def funds_without_kalshi(ctx: Ctx) -> Dict[str, Any]:
    """Funds' first read, as funds answers it, except that it never asks Kalshi: a key's cash whose memo
    isn't kept is marked pending (with the last figure read and its age, if any) for the page to ask after."""
    return funds(ctx, ask_kalshi=False)


def then_reads(url: str, body: Dict[str, Any]) -> List[str]:
    """The reads a page asks right after its carried one, which boot.js starts beside the bundle: Funds'
    pending Kalshi cash, one ask per book (the page asks them so too). [] for every other read."""
    if url != "/api/funds" or not isinstance(body, dict):
        return []
    return ["/api/funds/cash?book=%s" % book for book, key in (("live", "kalshi"), ("demo", "kalshi_dev"))
            if isinstance(body.get(key), dict) and body[key].get("pending")]


def dashboard_since(cookie: Optional[str], now: Optional[float] = None) -> Optional[int]:
    """The dashboard's ?since= for this load, from the tau_visit cookie as the page reads it."""
    m = _VISIT.match(cookie or "")
    if not m:
        return None
    since, seen = int(m.group(1)), int(m.group(2))
    at = seen if int(time.time() if now is None else now) - seen > VISIT_GAP else since
    return at or None


def billing_tz(cookie: Optional[str]) -> Optional[int]:
    """Billing's ?tz= for this load, from the tau_tz cookie as boot.js writes it; None without one."""
    return int(cookie) if cookie and _TZ.match(cookie) else None


def first_requests(path: str, query: str, cookies: Dict[str, str]) -> List[Request]:
    """The reads an app page asks for first, as the page will ask them; [] when the shell can't name them."""
    if query:
        return []
    if path in ("/", "/dashboard"):
        at = dashboard_since(cookies.get("tau_visit"))
        return [(("/api/dashboard?since=%d" % at if at else "/api/dashboard"), dashboard, (), ({"since": str(at)} if at else {})),
                ("/api/autopilot/status", autopilot_status, (), {})]
    if path == "/research":
        return [("/api/runs", list_runs, (), {}),
                ("/api/research/scoreboard?days=%d" % LOOP_DAYS, kept_loop_board, (), {"days": str(LOOP_DAYS)})]
    if path == "/strategies":
        return [("/api/strategies?page=0", list_strategies, (), {"page": "0"})]
    if path == "/deploy":
        return [("/api/deployments", list_deployments, (), {})]
    if path in ("/funds", "/settings/account"):
        return [("/api/funds", funds_without_kalshi, (), {})]
    if path in ("/billing", "/settings/billing"):
        tz = billing_tz(cookies.get("tau_tz"))
        return [] if tz is None else [("/api/billing?tz=%d" % tz, billing_without_stripe, (), {"tz": str(tz)})]
    m = _RUN_PAGE.match(path)
    if m:
        return [("/api/runs/%s?after=0" % m.group(1), get_run, (m.group(1),), {"after": "0"})]
    return []


def first_reads(path: str, query: str, cookies: Dict[str, str], make_ctx: MakeCtx) -> Tuple[List[Dict[str, Any]], List[str]]:
    """([{url, body}] for each first read that answered, with "then": the reads its page asks next, when
    there are any; the cookies they set). A read that fails is left out: the page asks for it itself and
    shows what it gets."""
    reads: List[Dict[str, Any]] = []
    set_cookies: List[str] = []
    for url, fn, params, q in first_requests(path, query, cookies):
        try:
            ctx = make_ctx(params, q)
            read = {"url": url, "body": fn(ctx)}
            then = then_reads(url, read["body"])
            if then:
                read["then"] = then
            reads.append(read)
            set_cookies += ctx.set_cookies
        except (ApiError, NotKept):
            continue  # a missing session page, say, or a board not worked out yet: the page asks itself
        except Exception as e:  # noqa: BLE001 - the shell must never fail on this
            sys.stdout.write("[app] shell first read failed (%s); the page reads %s itself\n" % (type(e).__name__, url))
            sys.stdout.flush()
    return reads, set_cookies
