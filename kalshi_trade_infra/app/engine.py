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
TICK_SECONDS = 15
# A slot decided this late is skipped instead: the backtest decided at the
# slot boundary, and a daily decision taken 50 minutes late is a different rule.
LATE_FRACTION = 0.25
# Hard guard, no model involved: a deployment that has lost this much more
# than its backtest's worst unseen-data drawdown is paused.
LOSS_GUARD_MULTIPLE = 2.0
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"


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


def fetch_quotes(market: Market) -> List[LiveQuote]:
    out, cursor = [], None
    while True:
        params = {"series_ticker": market.series, "status": "open", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        data = api_get("/markets", params)
        for m in data.get("markets") or []:
            ct = parse_iso_to_dt(m.get("close_time"))
            if ct is None or m.get("floor_strike") is None or not market.is_target_event(ct):
                continue
            out.append(LiveQuote(
                Contract(m["ticker"], float(m["floor_strike"]), ct.astimezone(timezone.utc)),
                _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars")),
                _f(m.get("yes_bid_size_fp")), _f(m.get("yes_ask_size_fp")),
            ))
        cursor = data.get("cursor")
        if not cursor:
            return out


def fetch_btc() -> BtcSeries:
    resp = requests.get(COINBASE_CANDLES_URL, params={"granularity": 60}, timeout=10)
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
    btc: Callable[[], BtcSeries] = fetch_btc
    result: Callable[[str], Optional[str]] = fetch_result
    live_kernel: Optional[Callable[[int], object]] = None  # user_id -> kernel; None = live disabled


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


def _live_trade(cur, dep: Dict, kernel, action: str, ticker: str, qty: int, price: float):
    from data_pipeline.architecture.contracts import TradeIntent

    intent = TradeIntent(action=action, side="yes", ticker=ticker, qty_contracts=qty, limit_price_dollars=price,
                         model_name="app-dep-%d" % dep["id"], now_ts=datetime.now(timezone.utc))
    return kernel.execute(intent)


def decide(conn, dep: Dict, snaps: List[Snapshot], sizes: Dict[str, Optional[float]], sources: Sources) -> Dict:
    cur = conn.cursor()
    spec = dep["spec"]
    by_ticker = {s.contract.ticker: s for s in snaps}
    live = dep["mode"] == "live"
    kernel = None
    if live:
        kernel = sources.live_kernel(dep["user_id"]) if (LIVE_TRADING_ENABLED and sources.live_kernel) else None
        if kernel is None:
            repo.set_deployment_status(cur, dep["user_id"], dep["id"], "paused",
                                       "Live trading is not enabled on this server yet.")
            return {"paused": "live disabled"}
    out = {"exits": 0, "entries": 0}

    positions = repo.open_positions(cur, dep["id"])
    for pos in positions:
        snap = by_ticker.get(pos["ticker"])
        sig = specmod.exit_signal(spec, pos["side"], float(pos["entry_price"]), snap) if snap else None
        if sig is None:
            continue
        reason, price = sig
        if live:
            rep = _live_trade(cur, dep, kernel, "sell", pos["ticker"], int(pos["qty"]), price)
            if rep.fill_qty_contracts < int(pos["qty"]):
                continue  # ponytail: partial exits wait for the next slot; per-lot positions if this bites
            pnl = int(pos["qty"]) * (rep.fill_price_dollars - float(pos["entry_price"])) - float(pos["entry_fee"]) - rep.fee_dollars
            repo.close_position(cur, pos["id"], rep.fill_price_dollars, rep.fee_dollars, pnl, reason)
        else:
            _paper_sell(conn, pos, price, reason)
        out["exits"] += 1

    held = {p["ticker"] for p in repo.open_positions(cur, dep["id"])}
    slots = spec["sizing"]["max_positions"] - len(held)
    for entry in specmod.entries(spec, snaps):
        if slots <= 0:
            break
        ticker = entry.snapshot.contract.ticker
        if ticker in held or (live and entry.side != "yes"):
            continue
        qty = specmod.contracts_for(spec["sizing"]["stake"], entry.price)
        shown = sizes.get(ticker)
        if shown is not None:
            qty = min(qty, int(shown))  # paper never fills more than the book showed
        if qty < 1:
            continue
        if live:
            rep = _live_trade(cur, dep, kernel, "buy", ticker, qty, entry.price)
            if rep.fill_qty_contracts < 1:
                continue
            repo.insert_position(cur, dep["id"], dep["user_id"], "live", ticker, "yes", rep.fill_qty_contracts,
                                 rep.fill_price_dollars, rep.fee_dollars, entry.snapshot.contract.close_time,
                                 rep.external_order_id)
        elif _paper_buy(conn, dep, entry, qty) is None:
            break  # out of paper cash
        held.add(ticker)
        slots -= 1
        out["entries"] += 1
    loss_guard(cur, dep)
    return out


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
    feats = None if late else sources.btc().features_at(now_ts)
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
        decide(conn, dep, snaps, sizes, sources)
        stats["decided"] += 1
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
        )

    return make


def run_forever() -> None:
    from data_pipeline.common import get_db_conn

    last_review = 0.0
    while True:
        try:
            conn = get_db_conn()
            sources = Sources(live_kernel=live_kernel_factory(conn) if LIVE_TRADING_ENABLED else None)
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
                    if LIVE_TRADING_ENABLED:
                        try:
                            enforce_autopilot_limits(conn)
                        except Exception as e:
                            print("[engine] autopilot limit check failed: %r" % e, flush=True)
                    time.sleep(TICK_SECONDS)
            finally:
                conn.close()
        except Exception as e:  # reconnect and carry on; a silent dead engine is the worst failure here
            print("[engine] ERROR %s" % e, flush=True)
            time.sleep(5)
