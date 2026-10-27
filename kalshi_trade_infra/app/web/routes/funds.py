"""Funds routes: the funds page, paper transfers, demo reloads, Kalshi live and demo keys, and the
waitlist signup. Moved verbatim from app.server, which re-imports every name for its route table."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from app import repository as repo
from app.adapters.kalshi import kalshi_account, kalshi_dev_exec
from app.adapters.kalshi_perps import kalshi_perps_trading
from app.adapters.ses import notify
from app.services import book_memo
from app.web.http import ApiError, Ctx, _num
from app.web.routes.brokers import _perps_live_call
from app.web.settings import MAX_PAPER_BALANCE, MAX_WAITLIST_PER_MINUTE
from app.web.views import FOLLOW_UP_TTL, _demo_cash, _live_balance, _open_book, _paper_equity
from trading_core.domain.money import cents


def _cash(v):
    """A Kalshi cash figure as the page shows it (cents), or None when there is none to show."""
    return None if v is None else cents(v)


def _memo_cash(memo, kept: bool) -> Dict[str, Any]:
    """One key's cash from its balance memo alone, never Kalshi: the figure when the memo is kept; else
    pending, carrying the last figure read (and when) if there is one, so the page never shows an old
    figure without its age, nor a missing one as $0. `memo` is (value, read_at) or None."""
    if kept and memo is not None:
        return {"balance": _cash(memo[0]), **({"balance_at": memo[1]} if memo[0] is not None else {})}
    out: Dict[str, Any] = {"balance": None, "pending": True}
    if memo is not None and memo[0] is not None:
        out.update(last_balance=_cash(memo[0]), last_balance_at=memo[1])
    return out


_UNREAD = object()


def kalshi_cash(cur, uid: int, ask_kalshi: bool = False, key: Any = _UNREAD) -> Dict[str, Any]:
    """The live key's cash at Kalshi as Funds and the dashboard show it: {"connected", "funding_url",
    "balance" (cents) [, "balance_at"]}. With ask_kalshi False, as every page read takes it, it never waits
    on Kalshi: the cash comes from its memo when kept, else is marked pending (_memo_cash), and the page asks
    /api/funds/cash?book=live for it. `key` is the user's live key row (None: none) when the caller has
    read it; else it is read here, once."""
    if ask_kalshi:
        out = _live_balance(cur, uid)
        out["balance"] = _cash(out["balance"])
        return out
    if key is _UNREAD:
        key = repo.get_kalshi_key(cur, uid)
    if key is None:
        return {"connected": False, "balance": None, "funding_url": kalshi_account.KALSHI_FUNDING_URL}
    return {"connected": True, "funding_url": kalshi_account.KALSHI_FUNDING_URL,
            **_memo_cash(kalshi_account.balance_memo(uid), kalshi_account.balance_kept(uid))}


def funds(ctx: Ctx, ask_kalshi: bool = False):
    """Funds' read: the shell's first read, an in-app visit and the 30s poll alike. It never waits on Kalshi
    (ask_kalshi False): a key's cash comes from its memo or is marked pending (with the last figure read and
    its age), and the page asks /api/funds/cash for it, the one page read that may wait on Kalshi."""
    from app.trading import demo_twins

    cur = ctx.cur
    key = repo.get_kalshi_key(cur, ctx.uid)
    kalshi = kalshi_cash(cur, ctx.uid, ask_kalshi, key)
    if key is not None:
        kalshi["key_id"] = key["key_id"][:4] + "…" + key["key_id"][-4:]
    dev = repo.get_kalshi_dev_key(cur, ctx.uid)
    kalshi_dev_key: Dict[str, Any] = {"connected": dev is not None}
    if dev is not None:
        kalshi_dev_key["key_id"] = dev["key_id"][:4] + "…" + dev["key_id"][-4:]
        # The demo account's cash at Kalshi (the same cached read demo health makes), so Funds can
        # say "Connected ✓ (balance $X)". None when it can't be read just now.
        if ask_kalshi:
            kalshi_dev_key["balance"] = _cash(_demo_cash(cur, ctx.uid))
            if kalshi_dev_key["balance"] is not None:
                kalshi_dev_key["balance_at"] = demo_twins.balance_read_at(ctx.uid)  # up to a minute old, like Kalshi cash
        else:
            kalshi_dev_key.update(_memo_cash(kalshi_account.memo_peek(demo_twins._BALANCE_CACHE, ctx.uid),
                                             demo_twins.balance_kept(ctx.uid)))
        # The demo cash the autopilot's demo copies wait for, so Funds can say why a small balance starts none.
        kalshi_dev_key["copies_from"] = demo_twins.DEMO_TWIN_MIN_BALANCE if demo_twins.DEMO_TWINS else None
    # Each book's realized P&L and closed trades, from the dashboard's read (kept while the positions
    # are unchanged), so Funds says what each book has made with the figure the dashboard, Deploy and
    # the track record show. Demo's is since its last reload, as on the dashboard.
    day = repo.now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    realized, closed, _ = book_memo.closed_book_totals(book_memo.BookMemo(cur, ctx.uid), day)
    de = repo.demo_equity(cur, ctx.uid, realized=realized["demo"][0])
    # Each book's open positions, so every figure says what it leaves out; paper's balance is cash plus
    # open at cost, the dashboard's paper figure. Books are never added together.
    open_pos = repo.user_positions(cur, ctx.uid, "open")
    paper = _open_book(open_pos, "paper")
    balance = repo.paper_balance(cur, ctx.uid)
    kalshi.update(_open_book(open_pos, "live"), realized_pnl=cents(realized["live"][0]),
                  closed_trades=int(closed.get("live", 0)))
    return {
        "paper": {"cash": cents(balance), "equity": cents(_paper_equity(balance, open_pos)), **paper,
                  "realized_pnl": cents(realized["paper"][0]), "closed_trades": int(closed.get("paper", 0)),
                  "ledger": repo.ledger_rows(cur, ctx.uid)},
        "demo": {"capital": de["capital"], "equity": de["equity"], "realized": de["realized"],
                 "before_reload": de["before_reload"], "closed_trades": int(closed.get("demo", 0)),
                 **_open_book(open_pos, "demo")},
        "kalshi": kalshi,
        "kalshi_dev": kalshi_dev_key,
    }


def funds_cash(ctx: Ctx):
    """The follow-up to a page whose read marked a Kalshi cash pending (Funds, the dashboard, the autopilot
    status): one book's cash at Kalshi (?book=live or demo), the figure /api/funds shows. The only page read
    that may wait on Kalshi, up to its timeout: memoized, and asked again once the memo is no longer kept
    (FOLLOW_UP_TTL), one Kalshi read per user and book at a time (asks that come together share it). Only
    that book's cash: never added to another book or to paper."""
    from app.trading import demo_twins

    book = ctx.query.get("book")
    if book == "live":
        live = _live_balance(ctx.cur, ctx.uid, FOLLOW_UP_TTL)
        out: Dict[str, Any] = {"book": "live", "connected": live["connected"], "balance": _cash(live["balance"])}
        if live.get("balance_at") is not None:
            out["balance_at"] = live["balance_at"]
        return out
    if book == "demo":
        if repo.get_kalshi_dev_key(ctx.cur, ctx.uid) is None:
            return {"book": "demo", "connected": False, "balance": None}
        cash = _demo_cash(ctx.cur, ctx.uid, demo_twins.BALANCE_TTL - kalshi_account.KEPT_MARGIN)
        out = {"book": "demo", "connected": True, "balance": _cash(cash)}
        if out["balance"] is not None:
            out["balance_at"] = demo_twins.balance_read_at(ctx.uid)
        return out
    raise ApiError(400, "Choose live or demo.")


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
