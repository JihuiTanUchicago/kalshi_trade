"""Auth routes: Google sign-in, dev login, logout, the session cookie and the UI-theme cookie. Moved
verbatim from app.server, which re-imports every name for its route table."""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote, unquote, urlparse

from app import repository as repo
from app.web import auth
from app.web.http import ApiError, Ctx
from app.web.settings import ADMIN_EMAIL, DEV_LOGIN, OPEN_SIGNUP, SECURE_COOKIES, SPA_ROUTES


def _session_cookie(token: str, max_age: int) -> str:
    return "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (
        auth.SESSION_COOKIE, token, max_age, "; Secure" if SECURE_COOKIES else ""
    )


def _start_session(ctx: Ctx, user_id: int) -> None:
    token = auth.new_session_token()
    repo.create_session(ctx.cur, user_id, auth.hash_token(token), auth.SESSION_TTL)
    ctx.set_cookies.append(_session_cookie(token, int(auth.SESSION_TTL.total_seconds())))


# The account's theme, mirrored on the device so the page shell can link the right stylesheet and
# bundle without a database read. Not a secret, not a session: a stale value is corrected by /api/me.
# Not HttpOnly: the Settings switch writes it too, so a switch whose save failed still applies here.
UI_COOKIE = "tau_ui"
UI_THEMES = ("tau", "meridian")
UI_COOKIE_MAX_AGE = 400 * 86400


def _ui_cookie(theme: str) -> str:
    return "%s=%s; Path=/; SameSite=Lax; Max-Age=%d%s" % (
        UI_COOKIE, theme, UI_COOKIE_MAX_AGE, "; Secure" if SECURE_COOKIES else "")


def _sync_ui_cookie(ctx: "Ctx", theme: str) -> None:
    """Set the device's tau_ui cookie to the account's theme when it differs."""
    read = getattr(ctx.handler, "cookies", None)
    if (read().get(UI_COOKIE) if callable(read) else None) != theme:
        ctx.set_cookies.append(_ui_cookie(theme))


NEXT_COOKIE = "tau_next"


def _safe_next(nxt: Optional[str]) -> Optional[str]:
    """A post-sign-in destination, or None. Only an app page on this site (a SPA route, with an
    optional plain query) passes, so the round-trip through Google can never become an open redirect."""
    if not nxt or len(nxt) > 300 or not nxt.startswith("/") or nxt.startswith("//"):
        return None
    if any(c in nxt for c in "\\\r\n\t ") or any(ord(c) < 32 for c in nxt):
        return None
    u = urlparse(nxt)
    if u.scheme or u.netloc or u.fragment or not SPA_ROUTES.match(u.path):
        return None
    return nxt


def google_start(ctx: Ctx):
    if not auth.google_configured():
        raise ApiError(503, "Google sign-in is not configured on this server.")
    login = auth.new_login()
    repo.save_oauth_state(ctx.cur, login["state"], login["nonce"], login["verifier"])
    # Remember the page a signed-out visitor was sent away from, for 10 minutes, so sign-in lands there.
    nxt = _safe_next(ctx.query.get("next"))
    if nxt:
        ctx.set_cookies.append("%s=%s; Path=/auth; HttpOnly; SameSite=Lax; Max-Age=600%s" % (
            NEXT_COOKIE, quote(nxt, safe=""), "; Secure" if SECURE_COOKIES else ""))
    return ("redirect", auth.authorize_url(login))


def google_callback(ctx: Ctx):
    if ctx.query.get("error"):
        return ("redirect", "/signin?error=cancelled")
    state = repo.pop_oauth_state(ctx.cur, ctx.query.get("state", ""))
    if not state or not ctx.query.get("code"):
        return ("redirect", "/signin?error=expired")
    try:
        ident = auth.exchange_code(ctx.query["code"], state["code_verifier"], state["nonce"])
    except auth.AuthError:
        return ("redirect", "/signin?error=google")
    # Account creation gate: open to anyone when APP_OPEN_SIGNUP=1, else invite-only (operator or an
    # approved waitlist email). Existing users always sign in regardless (upsert finds them).
    email = ident["email"] or ""
    allow_new = OPEN_SIGNUP or email.lower() == ADMIN_EMAIL.lower() or repo.is_waitlist_approved(ctx.cur, email)
    user = repo.upsert_google_user(ctx.cur, ident["sub"], email, ident["name"], ident["picture"], allow_new=allow_new)
    if user is None:
        return ("redirect", "/signin?pending=1")  # request recorded; awaiting approval
    _start_session(ctx, user["id"])
    handler = getattr(ctx, "handler", None)
    nxt = _safe_next(unquote(handler.cookies().get(NEXT_COOKIE, ""))) if handler is not None else None
    if nxt:
        ctx.set_cookies.append("%s=; Path=/auth; HttpOnly; SameSite=Lax; Max-Age=0" % NEXT_COOKIE)
    return ("redirect", nxt or "/")


def dev_login(ctx: Ctx):
    if not DEV_LOGIN:
        raise ApiError(404, "Not found")
    email = ctx.query.get("email") or "jonathan@example.com"
    user = repo.upsert_google_user(ctx.cur, "dev:" + email, email, email.split("@")[0].title(), None)
    _start_session(ctx, user["id"])
    return ("redirect", _safe_next(ctx.query.get("next")) or "/")


def logout(ctx: Ctx):
    token = ctx.handler.cookies().get(auth.SESSION_COOKIE)
    if token:
        repo.delete_session(ctx.cur, auth.hash_token(token))
    ctx.set_cookies.append(_session_cookie("", 0))
    return {"ok": True}
