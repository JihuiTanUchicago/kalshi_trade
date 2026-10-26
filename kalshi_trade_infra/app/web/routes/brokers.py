"""Brokerage connections and the manual Alpaca paper and Kalshi perps order routes (the approve-then-send
flows). Each handler maps its service's own error type to an ApiError."""
from __future__ import annotations

from app.adapters.alpaca import alpaca_paper
from app.adapters.brokers import broker_oauth
from app.adapters.kalshi_perps import kalshi_perps_trading
from app.web import auth
from app.web.http import ApiError, Ctx, _int_param


def _broker_session_hash(ctx: Ctx) -> str:
    token = ctx.handler.cookies().get(auth.SESSION_COOKIE) if ctx.handler else None
    if not token:
        raise ApiError(401, "Please sign in again before connecting a brokerage.")
    return auth.hash_token(token)


def _broker_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except broker_oauth.Error as exc:
        raise ApiError(exc.status, str(exc)) from None


def broker_connections(ctx: Ctx):
    return _broker_call(broker_oauth.list_brokers, ctx.cur, ctx.uid)


def broker_connect(ctx: Ctx):
    provider = ctx.params[0]
    environment = ctx.body.get("environment", broker_oauth.PROVIDERS[provider]["default_environment"])
    return _broker_call(broker_oauth.connect, ctx.conn, ctx.uid, provider, environment,
                        _broker_session_hash(ctx), permission=ctx.body.get("permission", "read"))


def broker_callback(ctx: Ctx):
    provider = ctx.params[0]
    result = _broker_call(broker_oauth.callback, ctx.conn, ctx.uid, provider, ctx.query,
                          _broker_session_hash(ctx))
    # Only fixed provider/status identifiers enter the return URL. Provider
    # errors, codes, request tokens and state are never reflected into the SPA.
    return ("redirect", "/settings/account?broker=%s&broker_status=%s" % (provider, result))


def broker_disconnect(ctx: Ctx):
    return _broker_call(broker_oauth.disconnect, ctx.conn, ctx.uid, ctx.params[0],
                        ctx.body.get("environment"))


def _paper_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except alpaca_paper.Error as exc:
        raise ApiError(exc.status, str(exc)) from None


def alpaca_paper_account(ctx: Ctx):
    return _paper_call(alpaca_paper.overview, ctx.conn, ctx.uid)


def alpaca_paper_draft(ctx: Ctx):
    return _paper_call(alpaca_paper.create_order, ctx.conn, ctx.uid, ctx.body)


def alpaca_paper_action(ctx: Ctx):
    operation = {"submit": alpaca_paper.submit_order, "refresh": alpaca_paper.refresh_order,
                 "cancel": alpaca_paper.cancel_order}[ctx.params[1]]
    return _paper_call(operation, ctx.conn, ctx.uid, _int_param(ctx))


def _perps_live_call(fn, *args):
    try:
        return fn(*args)
    except kalshi_perps_trading.Error as exc:
        raise ApiError(exc.status, str(exc)) from None


def kalshi_perps_live_account(ctx: Ctx):
    return _perps_live_call(kalshi_perps_trading.overview, ctx.conn, ctx.uid)


def kalshi_perps_live_policy(ctx: Ctx):
    return _perps_live_call(kalshi_perps_trading.save_policy, ctx.conn, ctx.uid, ctx.body)


def kalshi_perps_live_draft(ctx: Ctx):
    return _perps_live_call(kalshi_perps_trading.create_order, ctx.conn, ctx.uid, ctx.body)


def kalshi_perps_live_proposal(ctx: Ctx):
    return _perps_live_call(kalshi_perps_trading.preview_proposal,
                            ctx.conn, ctx.uid, _int_param(ctx), ctx.body)


def kalshi_perps_live_action(ctx: Ctx):
    operation = {"submit": kalshi_perps_trading.submit_order,
                 "refresh": kalshi_perps_trading.refresh_order,
                 "cancel": kalshi_perps_trading.cancel_order}[ctx.params[1]]
    args = (ctx.conn, ctx.uid, _int_param(ctx))
    return _perps_live_call(operation, *args) if ctx.params[1] == "refresh" else _perps_live_call(operation, *args, ctx.body)
