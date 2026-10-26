"""Billing routes: credits, cards, top-ups, auto-reload, receipts and the trades CSV export. Moved
verbatim from app.server, which re-imports every name for its route table."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Optional

from app import repository as repo
from app.adapters.llm import models_catalog as catalog
from app.adapters.stripe import billing
from app.web.http import ApiError, Ctx, _num


def _stripe_failed(ctx: Ctx, e: "billing.StripeError", status: int, doing: str, fallback: str) -> ApiError:
    """A failed Stripe call, as the user reads it. Stripe's own text (which can name ids, parameters and
    hosts) goes to the server log; the user gets a declined card in plain words or ``fallback``."""
    print("[billing] %s failed for user %s: %s%s" % (doing, ctx.uid, e, " [%s/%s]" % (e.kind, e.code) if e.kind else ""),
          flush=True)
    return ApiError(status, billing.customer_message(e, fallback))


def _customer_id(ctx: Ctx) -> str:
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    existing = cust["stripe_customer_id"] if cust else None
    cid = billing.get_or_create_customer(ctx.user, existing)
    if cid != existing:  # new or re-created (stale id) -> persist, drop stale default card
        repo.save_stripe_customer(ctx.cur, ctx.uid, cid)
    return cid


def _credit_runway(cur, uid: int, reads: Optional[billing.Reads] = None):
    """(balance, last-7-day usage spend, days the balance lasts at that pace). Research pauses at
    zero, so this is how long autopilot keeps working; None when there is no recent usage."""
    balance = (reads or billing.Reads(cur, uid)).balance()
    spent_7d = repo.credit_spent_total(cur, uid, repo.now_utc() - timedelta(days=7))
    runway = round(balance / (spent_7d / 7), 1) if spent_7d > 0 and balance > 0 else None
    return balance, spent_7d, runway


CREDIT_RUNWAY_WARN_DAYS = 3


def _credits_running_low(cur, uid: int, reads: Optional[billing.Reads] = None):
    """Days of credit left when autopilot will pause within CREDIT_RUNWAY_WARN_DAYS and auto-reload
    won't top it up; None otherwise. A readout for the panel, never a gate."""
    reads = reads or billing.Reads(cur, uid)
    cust = reads.customer()
    if cust and cust.get("auto_reload") and cust.get("default_pm_id"):
        return None
    runway = _credit_runway(cur, uid, reads)[2]
    return runway if runway is not None and runway < CREDIT_RUNWAY_WARN_DAYS else None


def billing_state(ctx: Ctx):
    cur = ctx.cur
    cust = repo.get_stripe_customer(cur, ctx.uid)
    cards, default_pm, auto_reload = [], None, True
    reload_amount, reload_threshold = float(billing.AUTORELOAD_AMOUNT), float(billing.AUTORELOAD_THRESHOLD)
    if cust and billing.configured():
        try:
            cards = billing.list_cards(cust["stripe_customer_id"])
        except billing.StripeError:
            cards = []
        default_pm = cust.get("default_pm_id")
        auto_reload = bool(cust.get("auto_reload"))
        if cust.get("reload_amount") is not None:
            reload_amount = float(cust["reload_amount"])
        if cust.get("reload_threshold") is not None:
            reload_threshold = float(cust["reload_threshold"])
    balance, spent_7d, runway = _credit_runway(cur, ctx.uid)
    return {
        "configured": billing.configured(),
        "publishable_key": billing.STRIPE_PUBLISHABLE_KEY,
        "balance": round(balance, 4),
        "spent": round(repo.credit_spent_total(cur, ctx.uid), 4),
        "spent_7d": round(spent_7d, 4),
        "runway_days": runway,
        "free_bonus": float(billing.FREE_BONUS),
        "topup_fee_pct": float(billing.TOPUP_FEE) * 100,
        "autoreload_threshold": reload_threshold,
        "autoreload_amount": reload_amount,
        # What one auto-reload charges the card (credits plus the top-up fee), so the card wall can
        # say it before the card is saved: auto-reload is on by default.
        "autoreload_charge": billing.topup_charge_cents(Decimal(str(reload_amount))) / 100,
        "min_reload_amount": float(billing.AUTORELOAD_AMOUNT),
        "min_reload_threshold": float(billing.AUTORELOAD_THRESHOLD),
        "min_topup": float(billing.MIN_TOPUP), "max_topup": float(billing.MAX_TOPUP),
        "cards": cards, "default_pm": default_pm, "auto_reload": auto_reload,
        # Read-only spend pace: the last day, and the week split by what spent it (the parts add up
        # to spent_7d). The research floor tells the page when new research can't start.
        "spent_24h": round(repo.credit_spent_total(cur, ctx.uid, repo.now_utc() - timedelta(days=1)), 4),
        "spent_7d_by": {k: round(v, 4) for k, v in
                        repo.usage_by_source(cur, ctx.uid, repo.now_utc() - timedelta(days=7)).items()},
        "min_run_balance": float(billing.MIN_RUN_BALANCE),
        "ledger": [dict({"kind": r["kind"], "amount": float(r["amount_usd"]), "memo": _ledger_memo(r), "created_at": r["created_at"]},
                        **_usage_item(r)) for r in repo.credit_rows(cur, ctx.uid)],
    }


_USAGE_MEMO = "Agent usage · "  # billing.charge_usage's memo: this, then the invokable modelId
_RUN_ITEM = {("research", 0): "Research session", ("research", 1): "Autopilot research",
             ("review", 0): "Autopilot check-in", ("review", 1): "Autopilot check-in", ("chat", 0): "Chat"}


def _usage_item(r: Dict) -> Dict[str, str]:
    """What a usage line was for, in customer words: {"item": "Autopilot research", "model":
    "Claude Opus 4.6"}. The memo names the invokable modelId, which is ours, not the customer's, so
    it never reaches the page or the receipt as is. {} for a row that is not usage."""
    if r.get("kind") != "usage":
        return {}
    memo = r.get("memo") or ""
    model = memo[len(_USAGE_MEMO):] if memo.startswith(_USAGE_MEMO) else ""
    item = _RUN_ITEM.get((r.get("run_kind"), int(r.get("run_brief") or 0)), "Agent usage")
    return {"item": item, "model": catalog.label_for_model_id(model) if model else ""}


def _ledger_memo(r: Dict) -> str:
    """A ledger row's memo as the customer reads it (Billing and the receipt): a usage line says what
    it was for and names the model, never its id; any other memo is as written."""
    use = _usage_item(r)
    return "%s · %s" % (use["item"], use["model"]) if use.get("model") else (r.get("memo") or "")


_PLAIN_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)$")


def _csv_safe(value: Any) -> str:
    """One CSV cell that a spreadsheet will show as text, never run as a formula. Strategy titles
    are written by people and models; a cell that starts with = + - @ (or a tab or CR) and isn't a
    plain number gets a leading apostrophe. Negative P&L stays a number."""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in "=+-@\t\r" and not _PLAIN_NUMBER.match(s):
        return "'" + s
    return s


def _csv_rows(buf) -> Callable[[List[Any]], Any]:
    """A csv writer for a user download whose every cell goes through _csv_safe: the one guard both
    downloads (credits receipt, trades) share."""
    import csv
    w = csv.writer(buf)
    return lambda row: w.writerow([_csv_safe(c) for c in row])


def _usd4(v) -> str:
    """A ledger amount to 4 places, rounded half up from its exact decimal: through a float, -4.666650
    printed -4.6666."""
    return str(Decimal(str(v)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def billing_receipt(ctx: Ctx):
    """Full Credits & Usage history as a downloadable CSV receipt. Memos can carry run and strategy
    names, so every cell is formula-safe."""
    import io
    cur = ctx.cur
    user = repo.get_user(cur, ctx.uid) or {}
    buf = io.StringIO()
    row = _csv_rows(buf)
    row(["Tau - Credits & Usage receipt"])
    row(["Account", user.get("email", "")])
    row(["Generated (UTC)", repo.now_utc().replace(microsecond=0).isoformat()])
    row(["Current balance (USD)", _usd4(repo.credit_balance(cur, ctx.uid))])
    row(["Total spent (USD)", _usd4(repo.credit_spent_total(cur, ctx.uid))])
    row([])
    row(["Date (UTC)", "Type", "Amount (USD)", "Memo"])
    for r in repo.credit_rows(cur, ctx.uid, 100000):  # full history, newest first
        row([r["created_at"], r["kind"], _usd4(r["amount_usd"]), _ledger_memo(r)])
    fname = "tau-credits-%s.csv" % repo.now_utc().strftime("%Y%m%d")
    return ("download", fname, "text/csv; charset=utf-8", buf.getvalue())


TRADE_MODES = ("paper", "demo", "live")
TRADES_CSV_MAX_ROWS = 50000  # about 7MB; a cap, so one request can't read an unbounded book
TRADES_CSV_HEADER = ["closed_at_utc", "opened_at_utc", "mode", "strategy", "strategy_title", "ticker", "side",
                     "contracts", "entry_price", "exit_price", "entry_fee", "exit_fee", "realized_pnl",
                     "close_reason", "position_id"]
def _iso_utc(v: Any) -> str:
    if not isinstance(v, datetime):
        return "" if v is None else str(v)
    v = v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo else v
    return v.replace(microsecond=0).isoformat() + "Z"


def _dec(v: Any, places: int = 4) -> str:
    """An amount to `places`; text is already the file's (closed_trades_for_export reads it so)."""
    if isinstance(v, str):
        return v
    return "" if v is None else "%.*f" % (places, float(v))


def trades_csv(ctx: Ctx):
    """One mode's closed trades as a CSV the user can check the P&L from: realized_pnl summed over the
    file is the mode's realized P&L on the dashboard (demo's is since the last reload, so it can
    differ by what came before). Never mixes modes. Newest TRADES_CSV_MAX_ROWS at most, and says so."""
    import io
    mode = (ctx.query.get("mode") or "").strip().lower()
    if mode not in TRADE_MODES:
        raise ApiError(400, "Pick a mode: paper, demo or live.")
    rows = repo.closed_trades_for_export(ctx.cur, ctx.uid, mode, TRADES_CSV_MAX_ROWS + 1)
    cut = len(rows) > TRADES_CSV_MAX_ROWS
    buf = io.StringIO()
    row = _csv_rows(buf)
    row(TRADES_CSV_HEADER)
    for r in reversed(rows[:TRADES_CSV_MAX_ROWS]):  # oldest first, the order a reader checks a book in
        sid = r.get("strategy_id")
        row([
            _iso_utc(r["closed_at"]), _iso_utc(r["opened_at"]), r["mode"],
            "No. %05d" % sid if sid is not None else "", r.get("title") or "", r["ticker"], r["side"], int(r["qty"]),
            _dec(r["entry_price"]), _dec(r["exit_price"]), _dec(r["entry_fee"]), _dec(r["exit_fee"]),
            _dec(r["pnl"]), r.get("close_reason") or "", r["id"]])
    if cut:
        row(["# Only the newest %d trades are in this file; older ones are not." % TRADES_CSV_MAX_ROWS])
    fname = "tau-trades-%s-%s.csv" % (mode, repo.now_utc().strftime("%Y%m%d"))
    return ("download", fname, "text/csv; charset=utf-8", buf.getvalue())


def billing_setup_intent(ctx: Ctx):
    if not billing.configured():
        raise ApiError(503, "Payments aren't enabled yet.")
    try:
        return billing.create_setup_intent(_customer_id(ctx))
    except billing.StripeError as e:
        raise _stripe_failed(ctx, e, 502, "setup intent", "The card form couldn't start just now. Reload the page "
                                                          "and try again in a minute.")


def billing_card_added(ctx: Ctx):
    pm = str(ctx.body.get("payment_method_id") or "")
    if not pm.startswith("pm_"):
        raise ApiError(400, "No card to save.")
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    try:
        cid = cust["stripe_customer_id"] if cust else _customer_id(ctx)
        billing.set_default_card(cid, pm)
    except billing.StripeError as e:
        raise _stripe_failed(ctx, e, 502, "save card", "Your card couldn't be saved just now. Reload the page "
                                                       "and add it again.")
    repo.set_default_pm(ctx.cur, ctx.uid, pm)
    return {"ok": True}


def billing_topup(ctx: Ctx):
    if not billing.configured():
        raise ApiError(503, "Payments aren't enabled yet.")
    amount = _num(ctx.body, "amount", float(billing.MIN_TOPUP), float(billing.MAX_TOPUP))
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    if not cust or not cust.get("default_pm_id"):
        raise ApiError(409, "Add a card first.")
    from decimal import Decimal as _D
    credits = _D(str(amount))
    idem = "topup-%s-%d" % (ctx.uid, int(repo.now_utc().timestamp()))
    try:
        pi = billing.charge(cust["stripe_customer_id"], cust["default_pm_id"],
                            billing.topup_charge_cents(credits), off_session=False, idem=idem,
                            metadata={"user_id": ctx.uid, "credits": str(credits), "purpose": "topup"})
    except billing.StripeError as e:
        # Not "you weren't charged": a dropped connection can fail here after the charge went through.
        raise _stripe_failed(ctx, e, 402, "top-up", "The top-up didn't complete. Reload this page in a minute "
                                                    "to check your balance before you try again.")
    if pi["status"] != "succeeded":
        print("[billing] top-up for user %s ended %s (%s)" % (ctx.uid, pi["status"], pi.get("id")), flush=True)
        raise ApiError(402, "The card didn't complete the charge. Reload this page in a minute to check your "
                            "balance before you try another card.")
    with repo.transaction(ctx.conn) as tx:
        repo.add_credit(tx, ctx.uid, "topup", credits, "Added $%s credits" % credits, stripe_ref=pi["id"])
    return {"ok": True, "balance": round(repo.credit_balance(ctx.cur, ctx.uid), 4)}


def billing_autoreload(ctx: Ctx):
    on = ctx.body.get("on") is True
    if on and not (repo.get_stripe_customer(ctx.cur, ctx.uid) or {}).get("default_pm_id"):
        raise ApiError(409, "Add a card before turning on auto-reload.")
    from decimal import Decimal as _D
    amount = threshold = None
    if ctx.body.get("amount") is not None:
        amount = _D(str(_num(ctx.body, "amount", float(billing.AUTORELOAD_AMOUNT), float(billing.MAX_TOPUP))))
    if ctx.body.get("threshold") is not None:
        threshold = _D(str(_num(ctx.body, "threshold", float(billing.AUTORELOAD_THRESHOLD), float(billing.MAX_TOPUP))))
    repo.set_auto_reload(ctx.cur, ctx.uid, on, amount=amount, threshold=threshold)
    # What one reload of the saved amount charges the card, so the page's other copy of it (the
    # autopilot card) says the new figure without reading Billing again.
    return {"ok": True, "autoreload_charge": billing.topup_charge_cents(amount) / 100 if amount is not None else None}


def billing_remove_card(ctx: Ctx):
    pm = str(ctx.body.get("payment_method_id") or "")
    cust = repo.get_stripe_customer(ctx.cur, ctx.uid)
    if not cust:
        raise ApiError(404, "No card on file.")
    try:
        cards = billing.list_cards(cust["stripe_customer_id"])
    except billing.StripeError as e:
        raise _stripe_failed(ctx, e, 502, "list cards", "Your cards couldn't be loaded just now, so nothing was "
                                                        "removed. Try again in a minute.")
    if len(cards) <= 1:
        raise ApiError(409, "You can't remove your only card. Add another first.")
    if not any(c["id"] == pm for c in cards):
        raise ApiError(404, "That card isn't on file.")
    try:
        billing.detach_card(pm)
    except billing.StripeError as e:
        raise _stripe_failed(ctx, e, 502, "remove card", "That card couldn't be removed just now. Try again "
                                                         "in a minute.")
    if cust.get("default_pm_id") == pm:
        other = next(c["id"] for c in cards if c["id"] != pm)
        try:
            billing.set_default_card(cust["stripe_customer_id"], other)
        except billing.StripeError as e:
            # The card is gone already; Tau charges the card it has saved as the default, so point
            # that at the remaining card either way rather than leave it on the removed one.
            print("[billing] set default after remove failed for user %s: %s" % (ctx.uid, e), flush=True)
        repo.set_default_pm(ctx.cur, ctx.uid, other)
    return {"ok": True}
