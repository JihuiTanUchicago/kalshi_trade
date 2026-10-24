"""Tau-aware per-user live position reconciliation.

The engine tracks each user's LIVE positions in ``app_positions`` as
``(ticker, side, qty)`` rows, where ``side`` is ``'yes'`` or ``'no'``. The
exchange, however, knows only a single SIGNED net position per ticker. A
reconciler that compares our book to the exchange must map Tau's
``(ticker, side, qty)`` into that signed net, or it mis-reads a legitimately
held NO as a phantom short — which is exactly the false alert the old
``live_alerter.position_mismatches`` produced once NO-side live trading shipped.

Kalshi position sign (the crux)
-------------------------------
Buying NO on Kalshi is placing a SELL on the YES leg
(``execution_kernel.order_wire_params``: buy NO -> ``'ask'`` at ``1 - price``).
So a NO position IS a short-YES position, and ``/portfolio/positions`` reports
it as a NEGATIVE signed ``position`` / ``position_fp``:

    YES qty q  ->  exchange net  +q
    NO  qty q  ->  exchange net  -q

Tau's book net for a ticker = ``sum(+qty for yes) + sum(-qty for no)``. A ticker
reconciles iff that net equals the exchange's signed position. A correctly held
NO (book net -12, exchange -12) therefore MATCHES; it is never a short.

This module is READ-ONLY against the exchange — it never places an order. All DB
access goes through the repository layer so the logic is testable with a fake
cursor. Discrepancies are written to an audit table and surfaced to the user via
the engine's existing chat/notification path. Orphan adoption (recording an
untracked exchange position as a tracked book row — still no orders) is gated
behind ``APP_RECONCILE_ADOPT_ORPHANS`` and OFF by default.
"""
from __future__ import annotations

import os
from datetime import timedelta
from typing import Dict, List, NamedTuple

from app import repository as repo
from app.markets import MARKETS
from data_pipeline.common import KALSHI_KEY_ID, api_get_auth, utc_now

# Discrepancy kinds (stored verbatim in app_position_reconcile.kind).
UNTRACKED = "untracked"          # exchange holds a position our book does not — the serious one
BOOK_ONLY = "book_only"          # our book holds a position the exchange does not — stale/over-counting
SIZE_MISMATCH = "size_mismatch"  # same side, different size
SHORT = "short"                  # signs conflict: a genuine, unexpected opposite exposure

# Kinds urgent enough to flag loudly in the user notification.
_URGENT = (UNTRACKED, SHORT)

# The legacy engine's key. A Tau user whose key matches trades the same Kalshi
# account, so that account's book includes live_positions too.
OPERATOR_KEY_ID = KALSHI_KEY_ID


class ExchPos(NamedTuple):
    net: int                 # signed net contracts: + = YES, - = NO
    exposure_dollars: float  # best-effort current cost basis magnitude (0.0 if unknown)


class Discrepancy(NamedTuple):
    ticker: str
    kind: str
    exchange_qty: int  # signed net on the exchange
    book_qty: int      # signed net in our book


def book_net_from_rows(rows: List[Dict]) -> Dict[str, int]:
    """Fold ``(ticker, side, qty)`` book rows into a signed net per ticker
    (YES positive, NO negative). Tickers that net to zero are dropped."""
    net: Dict[str, int] = {}
    for r in rows:
        qty = int(r["qty"])
        signed = qty if str(r["side"]).lower() == "yes" else -qty
        net[r["ticker"]] = net.get(r["ticker"], 0) + signed
    return {t: v for t, v in net.items() if v != 0}


def exchange_positions(creds) -> Dict[str, ExchPos]:
    """This account's net positions from Kalshi, keyed by ticker. READ-ONLY.
    ``position``/``position_fp`` is already the signed net (see module docstring),
    so no side translation is needed here — a NO position simply arrives negative."""
    raw = api_get_auth("/trade-api/v2/portfolio/positions", credentials=creds).get("market_positions") or []
    out: Dict[str, ExchPos] = {}
    for p in raw:
        net = int(float(p.get("position_fp") or p.get("position") or 0))
        if net == 0:
            continue
        exp = p.get("market_exposure")
        try:
            # market_exposure is reported in cents; it is the magnitude of the
            # current cost basis and is used only as a best-effort adoption price.
            exposure = abs(float(exp)) / 100.0 if exp not in (None, "") else 0.0
        except (TypeError, ValueError):
            exposure = 0.0
        out[p["ticker"]] = ExchPos(net, exposure)
    return out


def classify(book_net: Dict[str, int], exch_net: Dict[str, int]) -> List[Discrepancy]:
    """Compare signed nets per ticker and classify each disagreement. A ticker
    whose book net equals its exchange net is reconciled and produces nothing."""
    out: List[Discrepancy] = []
    for ticker in sorted(set(book_net) | set(exch_net)):
        b = int(book_net.get(ticker, 0))
        e = int(exch_net.get(ticker, 0))
        if b == e:
            continue
        if b == 0:
            kind = UNTRACKED          # exchange holds something our book doesn't know about
        elif e == 0:
            kind = BOOK_ONLY          # our book holds something the exchange doesn't
        elif (b > 0) != (e > 0):
            kind = SHORT              # opposite directions: a genuine unexpected short/flip
        else:
            kind = SIZE_MISMATCH      # same side, different magnitude
        out.append(Discrepancy(ticker, kind, e, b))
    return out


def _side_qty(net: int) -> str:
    if net == 0:
        return "flat"
    return "%d %s" % (abs(net), "YES" if net > 0 else "NO")


def describe(d: Discrepancy) -> str:
    """A plain-English line for the user's chat/notification feed."""
    if d.kind == UNTRACKED:
        return ("URGENT — your Kalshi account holds %s on %s that this app did not record "
                "(likely a fill placed but not written to the book). It is NOT being managed "
                "by the app's risk controls; review it on Kalshi." % (_side_qty(d.exchange_qty), d.ticker))
    if d.kind == BOOK_ONLY:
        return ("The app's book shows %s on %s but your Kalshi account holds none — the book is "
                "stale/over-counting and will not be acted on." % (_side_qty(d.book_qty), d.ticker))
    if d.kind == SHORT:
        return ("URGENT — direction mismatch on %s: the app's book expects %s but Kalshi holds %s, "
                "an unexpected opposite/short exposure. Review immediately." %
                (d.ticker, _side_qty(d.book_qty), _side_qty(d.exchange_qty)))
    return ("Size mismatch on %s: Kalshi holds %s, the app's book shows %s." %
            (d.ticker, _side_qty(d.exchange_qty), _side_qty(d.book_qty)))


def _market_key_for_ticker(ticker: str) -> str:
    """The deployable market whose series prefixes this ticker, for the adoption
    container. Falls back to 'reconcile' when nothing matches (still a valid row)."""
    for m in MARKETS.values():
        if m.deployable and ticker.startswith(m.series):
            return m.key
    return "reconcile"


def _adopt_orphan(cur, user_id: int, d: Discrepancy, exch: Dict[str, ExchPos]) -> None:
    """Record an UNTRACKED exchange position as a tracked LIVE book row under the
    user's paused reconciliation deployment. Places NO order — only a row. The
    entry price is best-effort (from the exchange's cost basis, else neutral 0.50);
    the operator is alerted to verify it. Next sweep the book then matches the
    exchange and the audit row self-resolves.
    ponytail: entry price/close time are best-effort; adoption is a manual-review aid, not
    a source of truth for P&L. Gate stays OFF by default.
    """
    market = _market_key_for_ticker(d.ticker)
    dep_id = repo.reconcile_deployment_id(cur, user_id, market)
    side = "yes" if d.exchange_qty > 0 else "no"
    qty = abs(d.exchange_qty)
    ep = exch.get(d.ticker)
    entry = 0.5
    if ep is not None and ep.exposure_dollars > 0 and qty > 0:
        entry = min(0.99, max(0.01, round(ep.exposure_dollars / qty, 2)))
    repo.insert_position(cur, dep_id, user_id, "live", d.ticker, side, qty, entry, 0.0,
                         utc_now() + timedelta(days=1), order_ref="reconcile-adopt")


def _persisted(row: Dict) -> bool:
    """An open audit row seen on at least two sweeps (see repo.live_entry_halts)."""
    d, u = row.get("detected_at"), row.get("updated_at")
    return d is not None and u is not None and u > d


def reconcile_user(cur, user_id: int, exch: Dict[str, ExchPos], adopt: bool = False,
                   include_legacy: bool = False) -> List[Discrepancy]:
    """Reconcile one user's live book against their exchange positions. Upserts each
    genuine discrepancy to the audit trail, notifies the user when a discrepancy is
    new or changed (never every sweep — the standing-condition discipline), resolves
    audit rows that have cleared, and optionally adopts untracked orphans.

    A discrepancy still open on the next sweep halts the user's new LIVE entries
    (engine.decide reads repo.live_entry_halts); exits keep running. The user is
    told once when the halt starts and once when it lifts.

    include_legacy: this user's key trades the operator account, which also holds
    the legacy engine's live_positions; count them as ours."""
    rows = list(repo.live_book_by_ticker_side(cur, user_id))
    if include_legacy:
        rows += list(repo.legacy_live_book_rows(cur))
    book_net = book_net_from_rows(rows)
    exch_net = {t: ep.net for t, ep in exch.items()}
    discreps = classify(book_net, exch_net)

    existing = {r["ticker"]: r for r in repo.open_reconcile_rows(cur, user_id)}
    was_halted = any(_persisted(r) for r in existing.values())
    halted_now = [d for d in discreps if d.ticker in existing]
    active: List[str] = []
    for d in discreps:
        active.append(d.ticker)
        prev = existing.get(d.ticker)
        changed = (prev is None or prev["kind"] != d.kind
                   or int(prev["exchange_qty"]) != d.exchange_qty
                   or int(prev["book_qty"]) != d.book_qty)
        repo.upsert_reconcile(cur, user_id, d.ticker, d.kind, d.exchange_qty, d.book_qty)
        if changed:
            repo.add_chat(cur, user_id, "system", "Live position reconciliation: " + describe(d))
        if adopt and d.kind == UNTRACKED:
            _adopt_orphan(cur, user_id, d, exch)
    repo.resolve_reconcile_except(cur, user_id, active)
    if halted_now and not was_halted:
        repo.add_chat(cur, user_id, "system",
                      "Live entries HALTED: your book and your Kalshi account still disagree on %s after "
                      "two checks. No new live position will open until they match again; exits keep "
                      "running." % ", ".join(sorted(d.ticker for d in halted_now)))
    elif was_halted and not halted_now:
        repo.add_chat(cur, user_id, "system",
                      "Live entries resumed: your book matches your Kalshi account again.")
    return discreps


def reconcile_all(conn) -> Dict[str, int]:
    """Sweep every user who has a live key and open live positions. Fully guarded:
    one user's failure (bad key, unreachable exchange) is logged and skipped so the
    sweep — and the engine loop that calls it — never crashes. READ-ONLY against the
    exchange; writes only the audit trail + user notifications (+ adopted rows when
    the default-OFF flag is set). Never places an order."""
    from app import kalshi_account

    adopt = os.getenv("APP_RECONCILE_ADOPT_ORPHANS") == "1"
    summary = {"users": 0, "discrepancies": 0, "errors": 0}
    cur = conn.cursor()
    for uid in repo.users_to_reconcile(cur):
        try:
            key = repo.get_kalshi_key(cur, uid)
            if key is None:
                continue
            creds = kalshi_account.credentials_from_row(uid, key)
            exch = exchange_positions(creds)  # read-only exchange call, this user's own key
            operator = bool(OPERATOR_KEY_ID) and key.get("key_id") == OPERATOR_KEY_ID
            with repo.transaction(conn) as tx:
                discreps = reconcile_user(tx, uid, exch, adopt=adopt, include_legacy=operator)
            summary["users"] += 1
            summary["discrepancies"] += len(discreps)
        except Exception as e:  # contained per user: a reconcile error is never fatal
            summary["errors"] += 1
            print("[reconcile] user %d failed: %r (skipping)" % (uid, e), flush=True)
    return summary
