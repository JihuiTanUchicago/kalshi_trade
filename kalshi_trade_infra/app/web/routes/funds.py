"""Funds routes: the funds page, paper transfers, demo reloads, Kalshi live and demo keys, and the
waitlist signup. Moved verbatim from app.server, which re-imports every name for its route table."""
from __future__ import annotations

from datetime import timedelta

from app import repository as repo
from app.adapters.kalshi import kalshi_account, kalshi_dev_exec
from app.adapters.kalshi_perps import kalshi_perps_trading
from app.adapters.ses import notify
from app.web.http import ApiError, Ctx, _num
from app.web.routes.brokers import _perps_live_call
from app.web.settings import MAX_PAPER_BALANCE, MAX_WAITLIST_PER_MINUTE
from app.web.views import _live_balance, _open_book


def funds(ctx: Ctx):
    cur = ctx.cur
    key = repo.get_kalshi_key(cur, ctx.uid)
    kalshi = _live_balance(cur, ctx.uid)
    if key is not None:
        kalshi["key_id"] = key["key_id"][:4] + "…" + key["key_id"][-4:]
    dev = repo.get_kalshi_dev_key(cur, ctx.uid)
    kalshi_dev_key = {"connected": dev is not None}
    if dev is not None:
        kalshi_dev_key["key_id"] = dev["key_id"][:4] + "…" + dev["key_id"][-4:]
        # The demo account's cash at Kalshi (the same cached read demo health makes), so Funds can
        # say "Connected ✓ (balance $X)". None when it can't be read just now.
        from app.trading import demo_twins

        kalshi_dev_key["balance"] = demo_twins.balance_cached(cur, ctx.uid)
        if kalshi_dev_key["balance"] is not None:
            kalshi_dev_key["balance_at"] = demo_twins.balance_read_at(ctx.uid)  # up to a minute old, like Kalshi cash
        # The demo cash the autopilot's demo copies wait for, so Funds can say why a small balance starts none.
        kalshi_dev_key["copies_from"] = demo_twins.DEMO_TWIN_MIN_BALANCE if demo_twins.DEMO_TWINS else None
    de = repo.demo_equity(cur, ctx.uid)
    # Each book's open positions, so every figure says what it leaves out; paper's balance is cash plus
    # open at cost, the dashboard's paper figure. Books are never added together.
    open_pos = repo.user_positions(cur, ctx.uid, "open")
    paper = _open_book(open_pos, "paper")
    cash = round(repo.paper_balance(cur, ctx.uid), 2)
    kalshi.update(_open_book(open_pos, "live"))
    return {
        "paper": {"cash": cash, "equity": round(cash + paper["open_at_cost"], 2), **paper,
                  "ledger": repo.ledger_rows(cur, ctx.uid)},
        "demo": {"capital": de["capital"], "equity": de["equity"], "realized": de["realized"],
                 "before_reload": de["before_reload"], **_open_book(open_pos, "demo")},
        "kalshi": kalshi,
        "kalshi_dev": kalshi_dev_key,
    }


def paper_transfer(ctx: Ctx):
    kind = ctx.body.get("kind")
    if kind not in ("deposit", "withdraw", "reset"):
        raise ApiError(400, "Choose deposit, withdraw or reset.")
    amount = round(_num(ctx.body, "amount", 1, MAX_PAPER_BALANCE), 2)
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        if kind == "reset":
            # Start fresh at `amount`. Blocked with open paper positions: wiping the ledger would
            # orphan their already-debited cost and the equity math would double-count.
            if any(p["mode"] == "paper" for p in repo.user_positions(tx, ctx.uid, "open")):
                raise ApiError(409, "Close your open paper positions before resetting the account.")
            repo.reset_paper_account(tx, ctx.uid, amount)
            return {"ok": True}
        bal = repo.paper_balance(tx, ctx.uid)
        if kind == "withdraw" and amount > bal:
            raise ApiError(409, "You only have $%.2f of paper cash free." % bal)
        if kind == "deposit" and bal + amount > MAX_PAPER_BALANCE:
            raise ApiError(409, "Paper accounts top out at $%s." % "{:,.0f}".format(MAX_PAPER_BALANCE))
        repo.add_ledger(tx, ctx.uid, "deposit" if kind == "deposit" else "withdrawal",
                        amount if kind == "deposit" else -amount,
                        "Paper %s" % ("deposit" if kind == "deposit" else "withdrawal"))
    return {"ok": True}


def demo_reload(ctx: Ctx):
    """Set the app-controlled demo starting capital. Demo places real sandbox orders but the money
    is ours, so this never touches the real Kalshi demo-account balance — it just resets the
    capital that real fills are applied to, and zeroes the displayed demo P&L from here."""
    amount = round(_num(ctx.body, "amount", 1, MAX_PAPER_BALANCE), 2)
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        repo.reload_demo(tx, ctx.uid, amount)
    return {"ok": True}


def save_kalshi_key(ctx: Ctx):
    key_id = str(ctx.body.get("key_id") or "")
    pem = str(ctx.body.get("private_key") or "")
    try:
        cash = kalshi_account.verify(key_id, pem)
        blob = kalshi_account.encrypt_private_key(ctx.uid, pem.strip())
    except kalshi_account.KalshiKeyError as e:
        raise ApiError(400, str(e))
    except RuntimeError:
        raise ApiError(503, "This server can't store keys yet (encryption key not configured).")
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        # Replacing the key while live deployments run would point their open positions' exits at
        # another Kalshi account; the same rule as disconnecting.
        if any(d["mode"] == "live" and d["status"] == "running" for d in repo.list_deployments(tx, ctx.uid)) \
                and repo.get_kalshi_key(tx, ctx.uid) is not None:
            raise ApiError(409, "Pause or stop your live deployments before replacing your Kalshi key.")
        _perps_live_call(kalshi_perps_trading.guard_key_change, tx, ctx.uid, "production")
        repo.save_kalshi_key(tx, ctx.uid, key_id.strip(), blob)
    kalshi_account.remember_balance(ctx.uid, cash)
    return {"ok": True, "balance": cash}


def delete_kalshi_key(ctx: Ctx):
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        if any(d["mode"] == "live" and d["status"] == "running" for d in repo.list_deployments(tx, ctx.uid)):
            raise ApiError(409, "Pause or stop your live deployments before disconnecting Kalshi.")
        _perps_live_call(kalshi_perps_trading.guard_key_change, tx, ctx.uid, "production")
        repo.delete_kalshi_key(tx, ctx.uid)
    return {"ok": True}


def save_kalshi_dev_key(ctx: Ctx):
    """Store the user's own Kalshi DEMO (sandbox) key, encrypted at rest. Mirrors
    save_kalshi_key, but proves the key against the SANDBOX exchange (never production) and
    stores it in the separate app_kalshi_dev_keys table, so demo orders can never pick up a
    live key. The raw private key is used only to verify + encrypt here; it is never logged or echoed."""
    key_id = str(ctx.body.get("key_id") or "").strip()
    pem = str(ctx.body.get("private_key") or "")
    if not key_id or len(key_id) > 128:
        raise ApiError(400, "Paste the Key ID from the API keys page on demo.kalshi.co: the short code shown next "
                            "to the key, like a952bcbe-ec3b-4b5b-….")
    try:
        creds = (key_id, kalshi_account.parse_private_key(pem))
    except kalshi_account.KalshiKeyError as e:
        raise ApiError(400, str(e))
    try:
        kalshi_dev_exec.demo_fills(creds)  # authenticate against the sandbox only — proves the key works
    except kalshi_dev_exec.DemoHostError:
        raise ApiError(503, "The demo (sandbox) exchange isn't configured on this server yet.")
    except Exception:
        raise ApiError(400, "Kalshi's demo exchange didn't accept this key, or couldn't be reached just now. Check "
                            "that the Key ID and the private key come from the same key, and that you made it on "
                            "demo.kalshi.co: a key from kalshi.com is a live key and goes in the Kalshi account box.")
    try:
        blob = kalshi_account.encrypt_private_key(ctx.uid, pem.strip())
    except RuntimeError:
        raise ApiError(503, "This server can't store keys yet (encryption key not configured).")
    with repo.transaction(ctx.conn) as tx:
        _perps_live_call(kalshi_perps_trading.guard_key_change, tx, ctx.uid, "demo")
        repo.set_kalshi_dev_key(tx, ctx.uid, key_id, blob)
    from app.trading import demo_twins

    demo_twins.forget_balance(ctx.uid)  # Funds reads the new key's demo cash, not the old memo
    return {"ok": True}


def delete_kalshi_dev_key(ctx: Ctx):
    with repo.transaction(ctx.conn) as tx:
        repo.lock_user(tx, ctx.uid)
        if any(d["mode"] == "demo" and d["status"] == "running" for d in repo.list_deployments(tx, ctx.uid)):
            raise ApiError(409, "Pause or stop your demo deployments before removing your demo key.")
        _perps_live_call(kalshi_perps_trading.guard_key_change, tx, ctx.uid, "demo")
        repo.delete_kalshi_dev_key(tx, ctx.uid)
    return {"ok": True}


def waitlist(ctx: Ctx):
    email = str(ctx.body.get("email") or "").strip().lower()
    note = str(ctx.body.get("note") or "").strip()[:500]
    if not repo.EMAIL_RE.match(email) or len(email) > 320:
        raise ApiError(400, "Enter a valid email address.")
    cur = ctx.cur
    if repo.recent_waitlist_from(cur, "", repo.now_utc() - timedelta(minutes=1)) >= MAX_WAITLIST_PER_MINUTE:
        raise ApiError(429, "We're getting a lot of requests right now. Try again in a minute.")
    is_new = repo.add_waitlist(cur, email, note or None)
    if is_new:
        notify.waitlist_request(email, note or None, repo.count_waitlist(cur))
    return {"ok": True}
