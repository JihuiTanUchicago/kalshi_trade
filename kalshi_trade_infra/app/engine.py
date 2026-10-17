"""Runs every deployed strategy, for every user, against the live market.

Per market, per decision slot (one minute for 15-minute contracts, one hour
for the daily ladder - the backtest's own cadence):

    settle positions whose contract has a result
    read the live book (Kalshi REST, one call for the whole series) + BTC
    for each running deployment that has not decided this slot:
        exits per spec, then entries per spec, then the loss guard

Paper fills happen at the live ask/bid read this tick, capped at the size
shown, never at a stale bar. Live orders go through MarketableLimitKernel,
which re-reads the book and records only what Kalshi reports filled.

Two engines can run at once safely: `claim_decision` lets exactly one of them
decide a deployment's slot, and closing a position only works on an open one.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import requests

from app import repository as repo
from app import spec as specmod
from app.markets import MARKETS, BtcSeries, Contract, Market, Snapshot, snapshot
from data_pipeline.common import api_get, parse_iso_to_dt
from data_pipeline.kalshi_fees import taker_fee_dollars

# Live orders for app users stay off until the owner explicitly turns them on.
LIVE_TRADING_ENABLED = os.getenv("APP_LIVE_TRADING_ENABLED") == "1"
# Staged rollout for NO-side live: the YES-leg-complement order mechanics are test-verified but
# not yet validated against the real exchange, so non-YES strategies stay on PAPER for the LIVE
# path until this flag is set. Demo/paper NO always work (for sandbox validation; no real money).
# ponytail: temporary; remove once NO-side live is validated on the demo sandbox.
NO_SIDE_LIVE_ENABLED = os.getenv("APP_NO_SIDE_LIVE_ENABLED") == "1"
TICK_SECONDS = 15
# A slot decided this late is skipped instead: the backtest decided at the
# slot boundary, and a daily decision taken 50 minutes late is a different rule.
LATE_FRACTION = 0.25
# Hard guard, no model involved: a deployment that has lost this much more
# than its backtest's worst unseen-data drawdown is paused.
LOSS_GUARD_MULTIPLE = 2.0
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/%s/candles"  # %s = product, e.g. BTC-USD


@dataclass(frozen=True)
class LiveQuote:
    contract: Contract
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    yes_bid_size: Optional[float]
    yes_ask_size: Optional[float]


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _opt_float(v) -> Optional[float]:
    """An optional float env knob: None (feature off) for unset/blank/unparseable."""
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_quotes(market: Market) -> List[LiveQuote]:
    out, cursor = [], None
    while True:
        params = {"series_ticker": market.series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        data = api_get("/markets", params)
        for m in data.get("markets") or []:
            ct = parse_iso_to_dt(m.get("close_time"))
            if ct is None or not market.is_target_event(ct):
                continue
            strike = m.get("floor_strike")
            # An underlying-priced market (BTC/ETH/...) prices strike vs spot, so a contract with
            # no strike is unusable. An outcome-settled market (underlying is None, e.g. sports)
            # has no strike at all - use a 0.0 sentinel, matching the backtest's hist_markets
            # (see market_history.sync_settled_markets); snapshot() never reads it without a spot.
            if strike is None:
                if market.underlying is not None:
                    continue
                strike = 0.0
            out.append(LiveQuote(
                Contract(m["ticker"], float(strike), ct.astimezone(timezone.utc), market.series),
                _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars")),
                _f(m.get("yes_bid_size_fp")), _f(m.get("yes_ask_size_fp")),
            ))
        cursor = data.get("cursor")
        if not cursor:
            return out


def fetch_spot_series(market: Market) -> Optional[BtcSeries]:
    """One-minute spot closes that price `market`'s contracts (strike vs spot), from the
    market's own Coinbase product. None for an outcome-settled market (underlying is None,
    e.g. sports): it has no spot series and trades on the contract's own book features alone."""
    if market.underlying is None:
        return None
    resp = requests.get(COINBASE_CANDLES_URL % market.underlying, params={"granularity": 60}, timeout=10)
    resp.raise_for_status()
    return BtcSeries([(int(r[0]), float(r[4])) for r in resp.json()])


def fetch_result(ticker: str) -> Optional[str]:
    m = (api_get("/markets/%s" % ticker) or {}).get("market") or {}
    result = (m.get("result") or "").lower()
    return result if result in ("yes", "no") else None


@dataclass
class Sources:
    """Everything the engine reads from outside, swappable in tests."""

    quotes: Callable[[Market], List[LiveQuote]] = fetch_quotes
    spot: Callable[[Market], Optional[BtcSeries]] = fetch_spot_series
    result: Callable[[str], Optional[str]] = fetch_result
    live_kernel: Optional[Callable[[int], object]] = None  # user_id -> kernel; None = live disabled
    demo_kernel: Optional[Callable[[int], object]] = None  # user_id -> kernel; None = demo disabled


# -- settlement ------------------------------------------------------------------


def settle_due(conn, market: Market, sources: Sources, now: datetime) -> int:
    cur = conn.cursor()
    settled = 0
    results: Dict[str, Optional[str]] = {}
    for dep in repo.deployments_with_open_positions(cur, market.key):
        for pos in repo.open_positions(cur, dep["id"]):
            if pos["market_close_time"] > now.replace(tzinfo=None):
                continue
            if pos["ticker"] not in results:
                results[pos["ticker"]] = sources.result(pos["ticker"])
            result = results[pos["ticker"]]
            if result is None:
                continue  # Kalshi has not settled it yet
            payout = float(pos["qty"]) if result == pos["side"] else 0.0
            pnl = payout - float(pos["qty"]) * float(pos["entry_price"]) - float(pos["entry_fee"])
            with repo.transaction(conn) as tx:
                if not repo.close_position(tx, pos["id"], 1.0 if payout else 0.0, 0.0, pnl, "settled"):
                    continue
                if pos["mode"] == "paper":
                    repo.add_ledger(tx, pos["user_id"], "settlement", payout,
                                    "%s settled %s" % (pos["ticker"], result.upper()), pos["id"])
            settled += 1
    return settled


# -- decisions -------------------------------------------------------------------


def _paper_buy(conn, dep: Dict, entry: specmod.Entry, qty: int) -> Optional[int]:
    price = entry.price
    fee = taker_fee_dollars(qty, price)
    cost = qty * price + fee
    with repo.transaction(conn) as tx:
        repo.lock_user(tx, dep["user_id"])
        if repo.paper_balance(tx, dep["user_id"]) < cost:
            return None
        ticker = entry.snapshot.contract.ticker
        pid = repo.insert_position(tx, dep["id"], dep["user_id"], "paper", ticker, entry.side, qty, price, fee,
                                   entry.snapshot.contract.close_time)
        repo.add_ledger(tx, dep["user_id"], "trade", -cost,
                        "Bought %d %s %s @ %.2f" % (qty, entry.side.upper(), ticker, price), pid)
        return pid


def _paper_sell(conn, pos: Dict, price: float, reason: str) -> None:
    qty = int(pos["qty"])
    fee = taker_fee_dollars(qty, price)
    pnl = qty * (price - float(pos["entry_price"])) - float(pos["entry_fee"]) - fee
    with repo.transaction(conn) as tx:
        if repo.close_position(tx, pos["id"], price, fee, pnl, reason):
            repo.add_ledger(tx, pos["user_id"], "trade", qty * price - fee,
                            "Sold %d %s %s @ %.2f (%s)" % (qty, pos["side"].upper(), pos["ticker"], price, reason), pos["id"])


def _live_trade(cur, dep: Dict, kernel, action: str, side: str, ticker: str, qty: int, price: float):
    from data_pipeline.architecture.contracts import TradeIntent

    # `side` is the real leg (yes|no) and `price` is that side's own price; the
    # kernel reads the correct side of the book and the submitter sends the
    # matching YES-leg wire order. A NO strategy must never place a YES order.
    intent = TradeIntent(action=action, side=side, ticker=ticker, qty_contracts=qty, limit_price_dollars=price,
                         model_name="app-dep-%d" % dep["id"], now_ts=datetime.now(timezone.utc))
    return kernel.execute(intent)


def _close_position_at(conn, cur, dep: Dict, pos: Dict, kernel, via_kernel: bool, price: float, reason: str) -> bool:
    """Close one open position at `price` through this deployment's mode (live/demo kernel sell, or
    paper sell). The single exit path shared by the normal exit signal AND the drawdown force-sell —
    no force-sell-specific order mechanics. Idempotent via `close_position` (only an open row closes),
    so a retried tick never double-closes. Returns True only when the position actually closed; a
    partial live fill books nothing and waits for the next slot."""
    qty = int(pos["qty"])
    if via_kernel:
        rep = _live_trade(cur, dep, kernel, "sell", pos["side"], pos["ticker"], qty, price)
        filled = int(rep.fill_qty_contracts)
        if filled <= 0:
            return False  # nothing filled this slot; retry next slot
        if filled < qty:
            # Partial fill: contracts WERE sold on the exchange, so the fill must be recorded, not
            # dropped. Book the sold slice as realized P&L and shrink the open row to the remainder
            # (which retries next slot); otherwise settlement double-counts and we re-sell what's gone.
            # Contained: a booking failure is logged for reconciliation, never crashes the tick.
            try:
                filled_entry_fee = float(pos["entry_fee"]) * filled / qty
                pnl = filled * (rep.fill_price_dollars - float(pos["entry_price"])) - filled_entry_fee - rep.fee_dollars
                with repo.transaction(conn) as tx:
                    repo.book_partial_exit(tx, pos, filled, rep.fill_price_dollars, rep.fee_dollars, pnl, reason)
            except Exception as e:
                print("[engine] partial-exit booking failed pos %d dep %d filled %d/%d: %r (will reconcile)"
                      % (pos["id"], dep["id"], filled, qty, e), flush=True)
            return False  # position not fully closed — remainder stays open
        pnl = qty * (rep.fill_price_dollars - float(pos["entry_price"])) - float(pos["entry_fee"]) - rep.fee_dollars
        return repo.close_position(cur, pos["id"], rep.fill_price_dollars, rep.fee_dollars, pnl, reason)
    _paper_sell(conn, pos, price, reason)
    return True


def cross_deploy_block(spec: Dict, mode: str) -> Optional[str]:
    """Why a cross-contract (relative-value pair) spec may NOT deploy in `mode`, or None if it may.
    Cross specs deploy on PAPER/DEMO only: multi-leg LIVE execution + its gate is a separate,
    riskier step, so live is refused here. And a pair that spans >1 market needs a synchronized
    multi-market live feed the engine doesn't run (the extra legs' markets aren't deployable), so
    it stays research-only. A single-market pair (cross_strike / calendar) deploys on paper/demo —
    the engine already ticks that market and its frame carries every strike/settlement leg."""
    if not specmod.is_cross_contract(spec):
        return None
    if mode == "live":
        return ("Cross-contract (multi-leg) strategies can't go live yet — multi-leg live "
                "execution is a separate, riskier step. Run it on paper or demo.")
    markets = specmod.involved_markets(spec)
    if len(markets) > 1:
        return ("This is a cross-market pair (%s) — it needs a synchronized multi-market live "
                "feed we don't run yet, so it's research-only for now." % ", ".join(markets))
    return None


def decide(conn, dep: Dict, snaps: List[Snapshot], sizes: Dict[str, Optional[float]], sources: Sources) -> Dict:
    cur = conn.cursor()
    spec = dep["spec"]
    by_ticker = {s.contract.ticker: s for s in snaps}
    mode = dep["mode"]
    # Both live and demo route real orders through a MarketableLimitKernel with identical
    # mechanics; only the key (live vs dev) and host (production vs sandbox) differ, which
    # is baked into the respective kernel factory. Paper (no kernel) is unchanged.
    via_kernel = mode in ("live", "demo")
    kernel = None
    if via_kernel:
        if mode == "live":
            live_on = LIVE_TRADING_ENABLED and sources.live_kernel
            kernel = sources.live_kernel(dep["user_id"]) if live_on else None
            # Accurate reason: if live IS on, a None kernel means the user has no live key
            # (a transient DB/build error raises instead of returning None, so it never lands here).
            why = ("Live trading is not enabled on this server yet." if not live_on
                   else "Add your live Kalshi key on the Funds page to run this on live money.")
        else:  # demo -> sandbox exchange, signed with the user's own dev key; no LIVE switch needed
            kernel = sources.demo_kernel(dep["user_id"]) if sources.demo_kernel else None
            why = "Add your Kalshi demo (sandbox) key on the Funds page to run this on demo."
        if kernel is None:
            repo.set_deployment_status(cur, dep["user_id"], dep["id"], "paused", why)
            return {"paused": "%s disabled" % mode}
    if specmod.is_cross_contract(spec):
        return _decide_pairs(conn, dep, snaps, sizes, kernel, via_kernel, mode)
    out = {"exits": 0, "entries": 0}

    positions = repo.open_positions(cur, dep["id"])
    for pos in positions:
        snap = by_ticker.get(pos["ticker"])
        sig = specmod.exit_signal(spec, pos["side"], float(pos["entry_price"]), snap) if snap else None
        if sig is None:
            continue
        reason, price = sig
        if _close_position_at(conn, cur, dep, pos, kernel, via_kernel, price, reason):
            out["exits"] += 1

    held = {p["ticker"] for p in repo.open_positions(cur, dep["id"])}
    slots = spec["sizing"]["max_positions"] - len(held)
    # Per-user portfolio caps span ALL the user's deployments: block any new entry that would push
    # the user past their open-position count or open entry-notional cap. Read once, tracked locally
    # for the entries this call adds (another deployment's concurrent adds are seen next tick).
    risk = repo.user_risk_config(cur, dep["user_id"])
    exposure = repo.user_open_exposure(cur, dep["user_id"])
    open_count = int(exposure["n"])
    open_notional = float(exposure["notional"])
    cap_positions = int(risk["max_open_positions"])
    cap_notional = float(risk["max_open_notional"])
    for entry in specmod.entries(spec, snaps):
        if slots <= 0 or open_count >= cap_positions:
            break  # deployment slot cap or user-wide position cap reached
        ticker = entry.snapshot.contract.ticker
        if ticker in held:
            continue
        qty = specmod.contracts_for(spec["sizing"]["stake"], entry.price)
        shown = sizes.get(ticker)
        if shown is not None:
            qty = min(qty, int(shown))  # paper never fills more than the book showed
        # Trim to the user-wide open-notional cap; never breach it with a new entry.
        room = cap_notional - open_notional
        if room >= entry.price:
            qty = min(qty, int(room / entry.price))
        else:
            qty = 0
        if qty < 1:
            continue
        if via_kernel:
            rep = _live_trade(cur, dep, kernel, "buy", entry.side, ticker, qty, entry.price)
            if rep.fill_qty_contracts < 1:
                continue
            repo.insert_position(cur, dep["id"], dep["user_id"], mode, ticker, entry.side, rep.fill_qty_contracts,
                                 rep.fill_price_dollars, rep.fee_dollars, entry.snapshot.contract.close_time,
                                 rep.external_order_id)
        elif _paper_buy(conn, dep, entry, qty) is None:
            break  # out of paper cash
        held.add(ticker)
        slots -= 1
        open_count += 1
        open_notional += qty * entry.price  # requested qty; a short live fill only over-counts (safe for a cap)
        out["entries"] += 1
    loss_guard(cur, dep)
    return out


def _decide_pairs(conn, dep: Dict, snaps: List[Snapshot], sizes: Dict[str, Optional[float]],
                  kernel, via_kernel: bool, mode: str) -> Dict:
    """Decide a cross-contract (relative-value pair) deployment: open BOTH legs of each pair the
    rule picks (buy YES on the underpriced leg, NO on the overpriced leg) and HOLD to settlement —
    exactly the simulate_pairs rule the backtest proved, so there is no early-exit logic. Each leg
    is an ordinary position row, so settlement, marks and the loss guard all reuse the single-leg
    machinery unchanged. Only reached for paper/demo (live cross is refused at deploy)."""
    cur = conn.cursor()
    spec = dep["spec"]
    out = {"exits": 0, "entries": 0}
    positions = repo.open_positions(cur, dep["id"])
    held = {p["ticker"] for p in positions}
    # ponytail: every open position of a cross deployment is a pair leg, so pairs = legs // 2;
    # a demo partial fill could orphan a leg and under-count by one — acceptable in the sandbox.
    open_pairs = len(positions) // 2
    max_pairs = spec["sizing"]["max_positions"]
    risk = repo.user_risk_config(cur, dep["user_id"])
    exposure = repo.user_open_exposure(cur, dep["user_id"])
    open_count = int(exposure["n"])
    open_notional = float(exposure["notional"])
    cap_positions = int(risk["max_open_positions"])
    cap_notional = float(risk["max_open_notional"])
    for cand in specmod.pair_entries(spec, snaps):
        if open_pairs >= max_pairs or open_count + 2 > cap_positions:
            break  # pair slot cap, or the user-wide position cap has no room for two more legs
        lt = cand.long_snap.contract.ticker
        st = cand.short_snap.contract.ticker
        if lt in held or st in held:
            continue
        pair_cost = cand.long_price + cand.short_price
        qty = specmod.contracts_for(spec["sizing"]["stake"], pair_cost)
        for tk in (lt, st):  # paper never fills more than either leg's book showed
            shown = sizes.get(tk)
            if shown is not None:
                qty = min(qty, int(shown))
        room = cap_notional - open_notional
        qty = min(qty, int(room / pair_cost)) if room >= pair_cost else 0
        if qty < 1:
            continue
        legs = [("yes", lt, cand.long_price, cand.long_snap.contract.close_time),
                ("no", st, cand.short_price, cand.short_snap.contract.close_time)]
        placed = (_kernel_buy_pair(cur, dep, kernel, legs, qty, mode) if via_kernel
                  else _paper_buy_pair(conn, dep, legs, qty))
        if not placed:
            break  # out of paper cash / nothing filled this slot
        held.update((lt, st))
        open_pairs += 1
        open_count += 2
        open_notional += qty * pair_cost
        out["entries"] += 1
    loss_guard(cur, dep)
    return out


def _paper_buy_pair(conn, dep: Dict, legs, qty: int) -> bool:
    """Buy both legs of a pair in ONE transaction (so a pair is never half-opened on paper):
    check the combined cost against the paper balance once, then insert both leg positions."""
    items = []
    total = 0.0
    for side, ticker, price, close in legs:
        fee = taker_fee_dollars(qty, price)
        total += qty * price + fee
        items.append((side, ticker, price, fee, close))
    with repo.transaction(conn) as tx:
        repo.lock_user(tx, dep["user_id"])
        if repo.paper_balance(tx, dep["user_id"]) < total:
            return False
        for side, ticker, price, fee, close in items:
            pid = repo.insert_position(tx, dep["id"], dep["user_id"], "paper", ticker, side, qty, price, fee, close)
            repo.add_ledger(tx, dep["user_id"], "trade", -(qty * price + fee),
                            "Bought %d %s %s @ %.2f (pair)" % (qty, side.upper(), ticker, price), pid)
    return True


def _kernel_buy_pair(cur, dep: Dict, kernel, legs, qty: int, mode: str) -> bool:
    """Demo (sandbox) pair entry: send each leg through the same MarketableLimitKernel the single-
    leg path uses and record whatever actually filled. Returns True if any leg filled."""
    any_filled = False
    for side, ticker, price, close in legs:
        rep = _live_trade(cur, dep, kernel, "buy", side, ticker, qty, price)
        if rep.fill_qty_contracts < 1:
            continue
        repo.insert_position(cur, dep["id"], dep["user_id"], mode, ticker, side, rep.fill_qty_contracts,
                             rep.fill_price_dollars, rep.fee_dollars, close, rep.external_order_id)
        any_filled = True
    return any_filled


def loss_guard(cur, dep: Dict) -> bool:
    cur.execute(
        "SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions WHERE deployment_id=%s AND status='closed'", (dep["id"],)
    )
    realized = float(cur.fetchone()["p"])
    result = dep.get("result") or {}
    worst = float((result.get("out_of_sample") or {}).get("max_drawdown") or 0)
    capital = float(result.get("capital") or dep["spec"]["sizing"]["stake"] * dep["spec"]["sizing"]["max_positions"])
    limit = max(LOSS_GUARD_MULTIPLE * worst, 0.5 * capital)
    if realized >= -limit:
        return False
    why = "Lost $%.2f, more than the $%.2f guard (2x its worst backtest drawdown)." % (-realized, limit)
    if repo.set_deployment_status(cur, dep["user_id"], dep["id"], "paused", why):
        repo.add_chat(cur, dep["user_id"], "system", "Paused deployment #%d automatically. %s" % (dep["id"], why))
        repo.create_run(cur, dep["user_id"], "review", dep["market"], None,
                        "Deployment #%d was auto-paused by the loss guard: %s" % (dep["id"], why), dep["id"])
    return True


# -- drawdown force-sell ---------------------------------------------------------
# Conservative fallback if a user's drawdown_limit_pct column is unexpectedly NULL. The real
# per-user default lives in the schema (25%). A limit of 0 disables the force-sell for a user.
DRAWDOWN_LIMIT_PCT_DEFAULT = 25.0


def _deployment_capital(dep: Dict) -> float:
    """The deployment's capital base — same definition the loss guard uses."""
    result = dep.get("result") or {}
    return float(result.get("capital") or dep["spec"]["sizing"]["stake"] * dep["spec"]["sizing"]["max_positions"])


def _liquidation_price(pos: Dict) -> Optional[float]:
    """The price the position's OWN side could be sold at now, from the engine-stamped YES bid
    (`mark_price`). YES liquidates ~yes_bid; NO ~1-yes_bid (matches server._mark_fields). None
    until the first mark after entry — such a position is skipped (priced/retried next tick)."""
    mark = pos.get("mark_price")
    if mark is None:
        return None
    mark = float(mark)
    return mark if pos["side"] == "yes" else 1.0 - mark


def deployment_drawdown_pct(cur, dep: Dict) -> float:
    """Current drawdown from the high-water mark, as a percent of capital.

    Equity curve = cumulative realized P&L of closed positions (oldest first), with current
    unrealized (open positions marked to `mark_price`) as the final point. Drawdown is peak minus
    current — i.e. how far BELOW its own high the deployment sits RIGHT NOW, not its worst-ever dip
    (a deployment that dipped and recovered is at its high, drawdown ~0, and must not be closed).
    """
    unrealized = 0.0
    for pos in repo.open_positions(cur, dep["id"]):
        price = _liquidation_price(pos)
        if price is None:
            continue
        qty = int(pos["qty"])
        unrealized += qty * price - (qty * float(pos["entry_price"]) + float(pos["entry_fee"]))
    equity = [0.0]
    cumulative = 0.0
    for pnl in repo.deployment_realized_series(cur, dep["id"]):
        cumulative += pnl
        equity.append(cumulative)
    equity.append(cumulative + unrealized)  # equity right now
    drawdown = max(equity) - equity[-1]     # peak-to-now, >= 0
    capital = _deployment_capital(dep)
    return 100.0 * drawdown / capital if capital > 0 else 0.0


def _force_close_kernel(dep: Dict, sources: Sources):
    """The same kernel the normal exit path would use for this mode — reusing the live-gate and
    demo-key checks exactly, so force-sell never obtains an execution path the engine couldn't
    already use. None when unavailable (live off / no key): the deployment is still paused and its
    positions settle at expiry."""
    mode = dep["mode"]
    if mode == "live":
        if LIVE_TRADING_ENABLED and sources.live_kernel:
            return sources.live_kernel(dep["user_id"])
        return None
    if mode == "demo":
        return sources.demo_kernel(dep["user_id"]) if sources.demo_kernel else None
    return None


def force_sell_if_drawn_down(conn, dep: Dict, sources: Sources) -> bool:
    """If this deployment's drawdown breaches the user's limit, force-close its open positions via
    the mode's own exit path and pause it. Returns True if it breached (and was paused). Each
    per-position close is contained: one failing close is logged and retried next tick, never
    aborts the rest or the pause."""
    cur = conn.cursor()
    risk = repo.user_risk_config(cur, dep["user_id"])
    limit_pct = DRAWDOWN_LIMIT_PCT_DEFAULT
    if risk and risk.get("drawdown_limit_pct") is not None:
        limit_pct = float(risk["drawdown_limit_pct"])
    if limit_pct <= 0:
        return False  # force-sell disabled for this user
    dd_pct = deployment_drawdown_pct(cur, dep)
    if dd_pct < limit_pct:
        return False
    mode = dep["mode"]
    via_kernel = mode in ("live", "demo")
    kernel = _force_close_kernel(dep, sources) if via_kernel else None
    for pos in repo.open_positions(cur, dep["id"]):
        if via_kernel and kernel is None:
            break  # no execution path; pause below and let the positions settle at expiry
        price = _liquidation_price(pos)
        if price is None:
            continue  # not yet marked — retry on a later tick
        try:
            _close_position_at(conn, cur, dep, pos, kernel, via_kernel, price, "drawdown")
        except Exception as e:  # one position's close failing must not abort the pause or the others
            print("[engine] force-close failed pos %d dep %d: %r (retry next tick)"
                  % (pos["id"], dep["id"], e), flush=True)
    why = "force-closed: drawdown %.1f%% >= limit %.1f%%" % (dd_pct, limit_pct)
    if repo.set_deployment_status(cur, dep["user_id"], dep["id"], "paused", why):
        repo.add_chat(cur, dep["user_id"], "system", "Paused deployment #%d automatically. %s" % (dep["id"], why))
        repo.create_run(cur, dep["user_id"], "review", dep["market"], None,
                        "Deployment #%d was force-closed and paused: %s" % (dep["id"], why), dep["id"])
    return True


def enforce_drawdown_limits(conn, sources: Sources) -> int:
    """Each engine loop: force-sell + pause every running deployment past its user's drawdown limit.
    One deployment's failure is contained so the sweep (and the engine loop) never crashes."""
    cur = conn.cursor()
    paused = 0
    for market in MARKETS.values():
        if not market.deployable:
            continue
        for dep in repo.running_deployments(cur, market.key):
            try:
                if force_sell_if_drawn_down(conn, dep, sources):
                    paused += 1
            except Exception as e:
                print("[engine] drawdown check failed dep %d user %d: %r (skipping)"
                      % (dep["id"], dep["user_id"], e), flush=True)
    return paused


def tick_market(conn, market: Market, sources: Sources, now: Optional[datetime] = None) -> Dict:
    now = now or datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    stats = {"settled": settle_due(conn, market, sources, now)}
    slot = now_ts - now_ts % market.decision_seconds
    cur = conn.cursor()
    due = [d for d in repo.running_deployments(cur, market.key) if d["last_decision_ts"] < slot]
    if not due:
        return stats
    late = now_ts - slot > max(60, market.decision_seconds * LATE_FRACTION)
    quotes = [] if late else sources.quotes(market)
    # Series features price strike-vs-spot for underlying markets; an outcome-settled market
    # (sports, underlying=None) has no spot, so its snapshot carries only book features - exactly
    # as the backtester builds it. {} (not None) means "no spot, trade anyway"; None means skip
    # (late slot, or an underlying whose spot feed is stale - don't trade a different rule).
    if late:
        feats = None
    elif market.underlying is None:
        feats = {}
    else:
        try:
            series = sources.spot(market)
            feats = series.features_at(now_ts) if series is not None else None
        except Exception as e:  # a spot-feed hiccup on one market must not crash the engine loop
            print("[engine] spot fetch failed for %s: %r (skipping tick)" % (market.key, e), flush=True)
            feats = None
    snaps = [s for s in (snapshot(feats, q.contract, now_ts, q.yes_bid, q.yes_ask) for q in quotes) if s is not None]
    sizes = {q.contract.ticker: q.yes_ask_size for q in quotes}
    # Mark open positions to the current YES bid (the price they could be liquidated at)
    # using the book we just fetched — so the web shows live unrealized P&L. Best-effort:
    # a mark failure must never block the trading decision.
    try:
        stats["marked"] = repo.update_marks(
            cur, market.key, {q.contract.ticker: q.yes_bid for q in quotes if q.yes_bid is not None}, now)
    except Exception:
        pass
    stats["decided"] = 0
    for dep in due:
        if not repo.claim_decision(cur, dep["id"], slot):
            continue  # another engine has it
        if late or feats is None:
            continue  # stale inputs or a late slot: skip it rather than trade a different rule
        try:
            decide(conn, dep, snaps, sizes, sources)
            stats["decided"] += 1
        except Exception as e:  # one user's blip (DB hiccup, bad key) must not stop the whole engine
            print("[engine] decide failed dep %d user %d: %r (skipping)"
                  % (dep["id"], dep["user_id"], e), flush=True)
    return stats


REVIEW_EVERY = timedelta(hours=24)


def schedule_reviews(cur) -> int:
    """The agent's daily look at every user with something running."""
    cur.execute(
        """SELECT DISTINCT d.user_id FROM app_deployments d
           WHERE d.status='running' AND NOT EXISTS (
             SELECT 1 FROM app_agent_runs r WHERE r.user_id=d.user_id AND r.kind='review' AND r.created_at >= %s)""",
        (repo.now_utc() - REVIEW_EVERY,),
    )
    users = [r["user_id"] for r in cur.fetchall()]
    for uid in users:
        repo.create_run(cur, uid, "review", None, None, "Daily check-in on running deployments.")
    return len(users)


def enforce_autopilot_limits(conn) -> int:
    """Kill switch: any user whose live autopilot has lost its daily limit today gets live
    autopilot turned OFF and every running LIVE deployment paused at once. Runs each engine loop."""
    cur = conn.cursor()
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    killed = 0
    for u in repo.autopilot_live_over_limit(cur, day_start):
        repo.set_autopilot_live(cur, u["id"], False)
        loss = -float(u["realized"])
        repo.add_chat(cur, u["id"], "system",
                      "Live autopilot auto-disabled: today's live loss $%.2f hit your $%.2f daily limit. "
                      "Pausing live deployments." % (loss, float(u["lim"])))
        for d in repo.list_deployments(cur, u["id"]):
            if d["mode"] == "live" and d["status"] == "running":
                repo.set_deployment_status(cur, u["id"], d["id"], "paused", "Autopilot daily loss limit hit")
        killed += 1
    return killed


def live_kernel_factory(conn) -> Callable[[int], object]:
    """user_id -> MarketableLimitKernel signing with that user's own key."""
    from app import kalshi_account
    from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
    from data_pipeline.market_data import MarketFeed

    feed = MarketFeed()

    def make(user_id: int):
        row = repo.get_kalshi_key(conn.cursor(), user_id)
        if row is None:
            return None
        creds = kalshi_account.credentials_from_row(user_id, row)
        # Market-order-like entries: cross through the touch and take the current best
        # ask quickly (IOC), rather than resting a passive limit. The slippage cap keeps
        # it from paying an absurd price if the book is thin; raise KALSHI_MAX_ENTRY_SLIPPAGE
        # toward 0.99 for a true "take whatever's there" market order. All tunable by env.
        return MarketableLimitKernel(
            kalshi_account.order_submitter(creds), feed,
            entry_cross_ticks=int(os.getenv("KALSHI_ENTRY_CROSS_TICKS", "2")),
            exit_cross_ticks=int(os.getenv("KALSHI_EXIT_CROSS_TICKS", "2")),
            max_entry_slippage=float(os.getenv("KALSHI_MAX_ENTRY_SLIPPAGE", "0.10")),
            max_attempts=int(os.getenv("KALSHI_ORDER_MAX_ATTEMPTS", "3")),
            max_quote_age_seconds=float(os.getenv("KALSHI_MAX_QUOTE_AGE_SECONDS", "2.0")),
            # Thin-book controls, all off unless set (see MarketableLimitKernel). Each can only
            # shrink or abandon an order, and none can block an exit, so enabling any is a
            # strictly-stricter change, tunable without a redeploy.
            max_book_fraction=_opt_float(os.getenv("KALSHI_MAX_BOOK_FRACTION")),
            max_entry_spread=_opt_float(os.getenv("KALSHI_MAX_ENTRY_SPREAD")),
            max_order_notional=_opt_float(os.getenv("KALSHI_MAX_ORDER_NOTIONAL")),
        )

    return make


def run_forever() -> None:
    from data_pipeline.common import get_db_conn

    from app.kalshi_dev_exec import demo_kernel_factory

    last_review = 0.0
    last_reconcile = 0.0
    # How often to reconcile each user's live book against their real Kalshi account.
    reconcile_every = float(os.getenv("APP_RECONCILE_EVERY_SECONDS", "300"))
    while True:
        try:
            conn = get_db_conn()
            # Demo (sandbox) execution needs no LIVE switch, but a demo-host misconfig must never
            # take down paper/live: build it defensively and carry on without it if it can't.
            try:
                demo_kernel = demo_kernel_factory(conn)
            except Exception as e:
                print("[engine] demo execution unavailable: %r" % e, flush=True)
                demo_kernel = None
            sources = Sources(
                live_kernel=live_kernel_factory(conn) if LIVE_TRADING_ENABLED else None,
                demo_kernel=demo_kernel,
            )
            try:
                while True:
                    for market in MARKETS.values():
                        if not market.deployable:
                            continue  # research-only markets never enter the trading loop
                        stats = tick_market(conn, market, sources)
                        if stats.get("decided") or stats.get("settled"):
                            print("[engine] %s %s" % (market.key, stats), flush=True)
                    if time.time() - last_review > 600:
                        schedule_reviews(conn.cursor())
                        last_review = time.time()
                    try:
                        repo.engine_heartbeat(conn.cursor(), LIVE_TRADING_ENABLED)
                    except Exception:
                        pass  # a heartbeat write must never stop the trading loop
                    # Risk force-sell: close + pause any deployment past its user's drawdown limit.
                    # Runs for every mode (paper/demo/live); live only closes when the live gate is on
                    # (otherwise pause-only). Fully contained so it can never stop the trading loop.
                    try:
                        enforce_drawdown_limits(conn, sources)
                    except Exception as e:
                        print("[engine] drawdown enforcement failed: %r" % e, flush=True)
                    if LIVE_TRADING_ENABLED:
                        try:
                            enforce_autopilot_limits(conn)
                        except Exception as e:
                            print("[engine] autopilot limit check failed: %r" % e, flush=True)
                    # Live position reconciliation: compare each user's book to their real
                    # Kalshi account. Read-only against the exchange; it only writes the audit
                    # trail + user notifications. Fully contained so it can never stop the loop.
                    if LIVE_TRADING_ENABLED and time.time() - last_reconcile > reconcile_every:
                        try:
                            from app import reconcile
                            summary = reconcile.reconcile_all(conn)
                            if summary.get("discrepancies") or summary.get("errors"):
                                print("[engine] reconcile %s" % summary, flush=True)
                        except Exception as e:
                            print("[engine] reconcile sweep failed: %r" % e, flush=True)
                        last_reconcile = time.time()
                    time.sleep(TICK_SECONDS)
            finally:
                conn.close()
        except Exception as e:  # reconnect and carry on; a silent dead engine is the worst failure here
            print("[engine] ERROR %s" % e, flush=True)
            time.sleep(5)
