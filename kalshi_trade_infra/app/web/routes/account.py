"""Account routes: who am I, notifications, the UI theme, email preferences and unsubscribe.
Moved verbatim from app.server, which re-imports every name for its route table."""
from __future__ import annotations

from app import repository as repo
from app.adapters.kalshi_perps import kalshi_perps_trading
from app.adapters.ses import notify
from app.adapters.stripe import billing
from app.research import agent
from app.services import bell, customer_text, markets as market_service
from app.trading import engine
from app.web.http import ApiError, Ctx
from app.web.routes.auth import UI_THEMES, _sync_ui_cookie
from app.web.routes.billing import reload_failed_now
from app.web.routes.research import _researchable_markets, models
from app.web.settings import ADMIN_EMAIL
from app.web.views import _auto_reload_terms, _needs_card, credit_exact


def me(ctx: Ctx):
    _sync_ui_cookie(ctx, ctx.user.get("ui_theme") if ctx.user.get("ui_theme") in UI_THEMES else "tau")
    reads = billing.Reads(ctx.cur, ctx.uid)  # needs_card, auto_reload and credit_balance share one read each
    listed = _researchable_markets(ctx.cur)
    return {
        "user": {
            "id": ctx.user["id"], "email": ctx.user["email"], "name": ctx.user["name"],
            "username": ctx.user.get("username"), "ui_theme": ctx.user.get("ui_theme") or "tau",
            "email_opt_out": bool(ctx.user.get("email_opt_out")),  # Settings' email switch reads this
            "picture": ctx.user["picture_url"], "autopilot": bool(ctx.user["autopilot"]),
            "autopilot_live": bool(ctx.user.get("autopilot_live")),
            "autopilot_daily_loss_limit": float(ctx.user.get("autopilot_daily_loss_limit") or 50),
        },
        "kalshi_connected": repo.get_kalshi_key(ctx.cur, ctx.uid) is not None,
        "kalshi_dev_connected": repo.get_kalshi_dev_key(ctx.cur, ctx.uid) is not None,
        "live_trading_available": engine.LIVE_TRADING_ENABLED,
        # Demo (sandbox) always supports NO/either; live NO is behind the staged-rollout flag.
        "no_side_live_enabled": engine.NO_SIDE_LIVE_ENABLED,
        "is_admin": (ctx.user["email"] or "").lower() == ADMIN_EMAIL.lower(),
        "billing_enabled": billing.configured(),
        "needs_card": _needs_card(ctx, reads),
        "auto_reload": _auto_reload_terms(ctx, reads),
        # The last auto-reload was declined and that is why credits are short (Billing's banner text), so
        # the dashboard and the research form say to update the card rather than "add credits" alone.
        "reload_failed": reload_failed_now(ctx.cur, ctx.uid, reads) if billing.configured() else None,
        "free_bonus": float(billing.FREE_BONUS),
        "credit_balance": credit_exact(reads.balance()),
        "min_run_balance": float(billing.MIN_RUN_BALANCE),  # the headroom a research run needs to start
        "perps_live_available": kalshi_perps_trading.enabled(),  # hide the Funds perps box when live perps are off
        "markets": listed,
        # The long name of each market the list leaves out (core.js mktLong reads both), so one kept on a
        # session, strategy or deployment reads as the server's lines say it.
        "market_names": market_service.unlisted_names(listed),
        "directions": [{"key": k, **v} for k, v in agent.DIRECTIONS.items()],
        # The research form's model list (the same as GET /api/models), so /research doesn't wait on
        # that read before it starts its own.
        "models": models(ctx),
    }


def notifications(ctx: Ctx):
    rows = customer_text.notification_rows(repo.list_notifications(ctx.cur, ctx.uid, limit=bell.READ_ROWS))
    return {"unread": repo.count_unread_notifications(ctx.cur, ctx.uid), "items": bell.grouped(rows),
            # unread_kinds counts the newest READ_ROWS notices only, while `unread` counts them all: the bell's
            # summary says which window its parts cover when the two differ ("131 new; the newest 100: …").
            "unread_kinds": bell.unread_kinds(rows), "unread_kinds_of": bell.READ_ROWS}


def mark_notifications_read(ctx: Ctx):
    repo.mark_notifications_read(ctx.cur, ctx.uid)
    return {"ok": True}


def set_ui_theme(ctx: Ctx):
    theme = str(ctx.body.get("theme") or "").strip()
    if theme not in ("tau", "meridian"):
        raise ApiError(400, "Unknown theme.")
    repo.set_ui_theme(ctx.cur, ctx.uid, theme)
    _sync_ui_cookie(ctx, theme)  # the reload that follows gets the new theme's shell
    return {"ok": True, "theme": theme}


def set_email_preferences(ctx: Ctx):
    """Settings' email switch, for the signed-in user only: optional email (community posts, replies,
    mentions, ready-for-live notices) off or back on. The unsubscribe link writes the same field;
    live-money safety alerts never read it."""
    opt_out = ctx.body.get("email_opt_out")
    if not isinstance(opt_out, bool):
        raise ApiError(400, "Choose whether Tau may send you optional email.")
    if not repo.set_email_opt_out(ctx.cur, ctx.uid, opt_out):
        raise ApiError(404, "Your account wasn’t found. Sign in again.")
    return {"ok": True, "email_opt_out": opt_out}


def unsubscribe(ctx: Ctx):
    """Public one-click unsubscribe from optional email (HMAC-signed link, no login needed). It sets
    the same switch as Settings, so the page says what stopped and where to turn it back on."""
    try:
        uid = int(ctx.query.get("u") or 0)
    except ValueError:
        uid = 0
    ok = bool(uid) and notify.unsubscribe_token_valid(uid, ctx.query.get("t") or "") and repo.set_email_opt_out(ctx.cur, uid, True)
    # While the server's live switch is closed that email says the strategy waits on paper (notify.live_ready_notice):
    # named here as it names itself, never "ready for live trading".
    ready = ("is ready for live trading" if engine.LIVE_TRADING_ENABLED
             else "cleared every paper-to-live check")
    msg = ("You're unsubscribed from Tau's optional email: new community posts, replies, mentions, and "
           "notices that a paper strategy %s. Safety alerts about a Bitcoin perps "
           "account you trade through Tau still come, because they protect real money. You can turn "
           "optional email back on in <a href='/settings' style='color:#1a66c9'>Settings</a>." % ready if ok
           else "This unsubscribe link isn't valid. If you keep getting emails, reply to one and we'll remove you.")
    page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Tau</title><body style='font-family:system-ui,-apple-system,sans-serif;max-width:520px;margin:12vh auto;padding:0 20px;color:#191B16'>"
            "<h1 style='font-size:20px;letter-spacing:.02em'>Tau</h1><p style='font-size:15px;line-height:1.55'>%s</p>"
            "<p style='font-size:13px;margin-top:20px'><a href='/' style='color:#1a66c9'>Back to Tau</a></p></body>") % msg
    return ("html", page)
