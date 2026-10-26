"""Read-only watch over each user's native Bitcoin perps account.

The binary reconciler (app/reconcile.py) and live_alerter.position_mismatches
exist because of 2026-09-27: the book and the exchange disagreed and nothing
asked the exchange. Perps reconcile one order at a time inside
kalshi_perps_trading, then never look again. With leverage the cost of not
looking is a liquidation, so this sweep asks Kalshi on a cadence:

  mismatch      Kalshi's signed position differs from what Tau's own filled
                orders add up to. Reported once it is still there on a second
                sweep, since a fill can land between the two reads. Skipped while
                an order is in flight for the same reason.
  liquidation   mark price within TAU_KALSHI_PERPS_LIQ_ALERT_PCT (default 10%)
                of Kalshi's estimated liquidation price.
  margin        maintenance margin uses TAU_KALSHI_PERPS_MARGIN_ALERT_RATIO
                (default 0.5) or more of account equity, or equity is <= 0.

Thresholds only decide when to tell someone. Nothing here limits, sizes or
places an order: Kalshi's native margin limits stay authoritative. Each
condition is announced once in chat (and by email for the urgent ones), then
once more when it clears.
"""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Dict, List, NamedTuple

from app.adapters.kalshi_perps import kalshi_perps_orders_repository as store
from app.adapters.kalshi_perps import kalshi_perps_trading as service
from app import repository as repo

MISMATCH = "mismatch"
LIQUIDATION = "liquidation"
MARGIN = "margin"


def _threshold(name: str, default: str) -> Decimal:
    try:
        value = Decimal(os.getenv(name, default))
    except InvalidOperation:
        value = Decimal(default)
    return value if value.is_finite() and value > 0 else Decimal(default)


class Alert(NamedTuple):
    key: str
    kind: str
    detail: str


def _num(value) -> Decimal:
    return Decimal(str(value))


def _fmt(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def position_alerts(book: Dict[str, Decimal], exchange: Dict[str, Decimal]) -> List[Alert]:
    out = []
    for ticker in sorted(set(book) | set(exchange)):
        ours, theirs = book.get(ticker, Decimal(0)), exchange.get(ticker, Decimal(0))
        if ours == theirs:
            continue
        if ours == 0:
            detail = "Kalshi holds %s %s contracts that no Tau order filled" % (_fmt(theirs), ticker)
        elif theirs == 0:
            detail = ("Tau's filled orders add up to %s %s contracts but Kalshi holds none "
                      "(closed outside Tau, or liquidated)" % (_fmt(ours), ticker))
        else:
            detail = "%s: Kalshi holds %s contracts, Tau's filled orders add up to %s" % (
                ticker, _fmt(theirs), _fmt(ours))
        out.append(Alert("mismatch:" + ticker, MISMATCH, detail))
    return out


def risk_alerts(risk: dict, account: dict) -> List[Alert]:
    out = []
    liq_pct = _threshold("TAU_KALSHI_PERPS_LIQ_ALERT_PCT", "10")
    for row in risk.get("positions") or []:
        mark, liq = row.get("mark_price"), row.get("estimated_liquidation_price")
        if mark is None or liq is None or _num(row.get("position") or 0) == 0:
            continue
        mark, liq = _num(mark), _num(liq)
        if mark <= 0 or liq <= 0:
            continue
        distance = abs(mark - liq) / mark * 100
        if distance <= liq_pct:
            out.append(Alert("liquidation:" + row["market_ticker"], LIQUIDATION,
                             "%s is %.1f%% from liquidation: mark %s, Kalshi's estimated liquidation %s, "
                             "position %s" % (row["market_ticker"], distance, _fmt(mark), _fmt(liq),
                                              _fmt(_num(row["position"])))))
    equity, maintenance = _num(account["account_equity"]), _num(account["maintenance_margin"])
    ratio = _threshold("TAU_KALSHI_PERPS_MARGIN_ALERT_RATIO", "0.5")
    if maintenance > 0 and (equity <= 0 or maintenance / equity >= ratio):
        used = "all" if equity <= 0 else "%.0f%%" % (maintenance / equity * 100)
        out.append(Alert("margin", MARGIN, "Maintenance margin $%s uses %s of account equity $%s" % (
            _fmt(maintenance), used, _fmt(equity))))
    return out


def _persisted(row: dict) -> bool:
    d, u = row.get("detected_at"), row.get("updated_at")
    return d is not None and u is not None and u > d


def _email(cur, user_id: int, subject: str, body: str) -> None:
    try:
        from app.adapters.ses import notify
        user = repo.get_user(cur, user_id) or {}
        if user.get("email"):
            notify._send(user["email"], subject, body)
    except Exception as e:  # best effort: the chat line is the record
        print("[perps-watch] email to user %d failed: %r" % (user_id, e), flush=True)


def watch_user(cur, user_id: int, env: str, state: dict, in_flight: bool) -> List[Alert]:
    """Compare one user's fresh exchange state to Tau's book, record what is wrong,
    and tell the user about anything new, changed or cleared."""
    exchange = {row["market_ticker"]: _num(row["position"]) for row in state["positions"]
                if _num(row["position"]) != 0}
    alerts = [] if in_flight else position_alerts(store.filled_net_by_ticker(cur, user_id, env), exchange)
    alerts += risk_alerts(state["risk"], state["account"])

    existing = {row["alert_key"]: row for row in store.open_watch_rows(cur, user_id, env)}
    active = []
    for alert in alerts:
        active.append(alert.key)
        prev = existing.get(alert.key)
        store.upsert_watch(cur, user_id, env, alert.key, alert.kind, alert.detail)
        # A mismatch is only real once it survives a second sweep; risk is urgent now.
        announce = (prev is not None and not _persisted(prev)) if alert.kind == MISMATCH else prev is None
        if announce:
            repo.add_chat(cur, user_id, "system", "Bitcoin perps watch: " + alert.detail)
            _email(cur, user_id, "Tau: Bitcoin perps " + alert.kind + " alert",
                   alert.detail + "\n\nReview your position in Tau Funds or the Kalshi app.")
    cleared = [key for key in existing if key not in active and not (in_flight and key.startswith("mismatch:"))]
    for key in cleared:
        if existing[key]["kind"] != MISMATCH or _persisted(existing[key]):
            repo.add_chat(cur, user_id, "system", "Bitcoin perps watch cleared: " + existing[key]["detail"])
    store.resolve_watch(cur, user_id, env, cleared)
    return alerts


def _read_state(client) -> dict:
    balance, risk, positions = client.balance(), client.risk(), client.positions()
    accounts = [row for row in balance["subaccount_balances"] if row["subaccount"] == 0]
    if len(accounts) != 1:
        raise ValueError("no primary perps subaccount")
    return {"account": accounts[0], "risk": risk, "positions": positions["positions"]}


def watch_all(conn) -> Dict[str, int]:
    """One sweep over every user who may hold perps. Read-only against Kalshi; one
    user's failure is logged and skipped so the engine loop never stops."""
    summary = {"users": 0, "alerts": 0, "errors": 0}
    env = service.environment()
    cur = conn.cursor()
    for uid in store.users_to_watch(cur, env):
        try:
            try:
                _, key = service._key(cur, uid, env)
            except service.Error:
                continue
            in_flight = bool(store.reservation_orders(cur, uid, env))
            with service._client(uid, key, env) as client:
                state = _read_state(client)
            with repo.transaction(conn) as tx:
                summary["alerts"] += len(watch_user(tx, uid, env, state, in_flight))
            summary["users"] += 1
        except Exception as e:
            summary["errors"] += 1
            print("[perps-watch] user %d failed: %r (skipping)" % (uid, e), flush=True)
    return summary
