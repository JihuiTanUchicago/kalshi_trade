import json
import os
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from data_pipeline.architecture.contracts import RiskContext, TradeIntent
from data_pipeline.architecture.execution_kernel import (
    DummyExecutionKernel,
    MarketableLimitKernel,
    order_wire_params,
)
from data_pipeline.architecture.risk_engine import DummyRiskEngine, LiveSettingsRiskEngine
from data_pipeline.common import api_get, api_get_auth, api_post_auth, get_db_conn, utc_now
from data_pipeline.market_data import MarketFeed
from data_pipeline.modeling_features import FEATURE_COLS, SOURCE_COLS, build_feature_vector, has_target
from data_pipeline.simulated_trading_engine import (
    EDGE_THRESHOLD_OVERRIDES,
    choose_effective_cutoff,
    fit_frozen_models,
    get_live_cutoff_utc,
    score_frozen_models,
    should_close_position,
)

# Candidates deliberately deployable to live, one settings row and one
# pause/enable state each - a strategy going live is a bigger decision than
# going into sim, so this list is narrower than sim's ALL_MODELS (no bare
# baselines here, only things that cleared sim research first).
LIVE_MODELS: Tuple[str, ...] = ("random_forest", "random_forest_high_conviction", "binary_theory_edge")

DEFAULT_SETTINGS = {
    "live_enabled": False,
    "starting_capital": 30.0,
    "signal_threshold": 0.55,
    "edge_threshold": 0.01,
    "max_trade_cost": 2.0,
    "max_open_notional": 6.0,
    "max_concurrent_positions": 1,
    "max_daily_loss": 5.0,
    "max_total_drawdown": 10.0,
    "min_samples_default_rf": 1000,
}
RISK_ENGINE_MODE = os.getenv("RISK_ENGINE_MODE", "live_settings").strip().lower()


def next_minute_plus_delay(delay_seconds: int = 12) -> datetime:
    now = utc_now()
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1, seconds=delay_seconds)


def load_settings(cur, model_name: str = "random_forest") -> Dict:
    """Per-strategy settings row, keyed by model_name (one legacy row still
    exists under the old fixed key 'live_config' - migrate_legacy_settings()
    below folds that into random_forest's row once, on first startup)."""
    cur.execute("SELECT settings_json FROM live_settings WHERE settings_key=%s LIMIT 1", (model_name,))
    row = cur.fetchone()
    if not row:
        defaults = dict(DEFAULT_SETTINGS)
        if model_name in EDGE_THRESHOLD_OVERRIDES:
            # Seed with the sim-validated threshold for this strategy rather
            # than the generic 0.01 - still just a starting point, the user
            # can change it from the Live Trading tab.
            defaults["edge_threshold"] = EDGE_THRESHOLD_OVERRIDES[model_name]
        cur.execute(
            """
            INSERT INTO live_settings (settings_key, settings_json, updated_at_utc)
            VALUES (%s, %s, %s)
            """,
            (model_name, json.dumps(defaults), utc_now().replace(tzinfo=None)),
        )
        return defaults
    cfg = row["settings_json"] if isinstance(row["settings_json"], dict) else json.loads(row["settings_json"])
    out = dict(DEFAULT_SETTINGS)
    out.update(cfg or {})
    return out


def update_settings(cur, model_name: str, patch: Dict) -> Dict:
    allowed = set(DEFAULT_SETTINGS.keys())
    cfg = load_settings(cur, model_name)
    for k, v in patch.items():
        if k in allowed:
            cfg[k] = v
    cur.execute(
        """
        INSERT INTO live_settings (settings_key, settings_json, updated_at_utc)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE settings_json=VALUES(settings_json), updated_at_utc=VALUES(updated_at_utc)
        """,
        (model_name, json.dumps(cfg), utc_now().replace(tzinfo=None)),
    )
    return cfg


def migrate_legacy_settings(cur) -> None:
    """One-time fold-in of the old single global 'live_config' row into
    random_forest's per-model row, so a pre-multi-strategy deployment's
    settings (and, importantly, live_enabled) aren't silently dropped."""
    cur.execute("SELECT settings_json FROM live_settings WHERE settings_key='live_config' LIMIT 1")
    legacy = cur.fetchone()
    if not legacy:
        return
    cur.execute("SELECT 1 FROM live_settings WHERE settings_key='random_forest' LIMIT 1")
    if cur.fetchone():
        cur.execute("DELETE FROM live_settings WHERE settings_key='live_config'")
        return
    cfg = legacy["settings_json"] if isinstance(legacy["settings_json"], dict) else json.loads(legacy["settings_json"])
    cur.execute(
        """
        INSERT INTO live_settings (settings_key, settings_json, updated_at_utc)
        VALUES ('random_forest', %s, %s)
        """,
        (json.dumps(cfg), utc_now().replace(tzinfo=None)),
    )
    cur.execute("DELETE FROM live_settings WHERE settings_key='live_config'")


def get_model_pause(cur, model_name: str) -> Optional[Dict]:
    cur.execute(
        "SELECT paused_reason, paused_at_utc FROM live_model_state WHERE model_name=%s AND paused=1",
        (model_name,),
    )
    row = cur.fetchone()
    return None if not row else {"paused_reason": row.get("paused_reason"), "paused_at_utc": row.get("paused_at_utc")}


def get_all_live_pause_states(cur) -> Dict[str, Dict]:
    cur.execute("SELECT model_name, paused_reason, paused_at_utc FROM live_model_state WHERE paused=1")
    return {
        r["model_name"]: {"paused_reason": r.get("paused_reason"), "paused_at_utc": str(r.get("paused_at_utc"))}
        for r in cur.fetchall()
    }


def set_model_paused(cur, model_name: str, reason: str, now_ts: datetime) -> None:
    cur.execute(
        """
        INSERT INTO live_model_state (model_name, paused, paused_reason, paused_at_utc, updated_at_utc)
        VALUES (%s, 1, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          paused=1, paused_reason=VALUES(paused_reason), paused_at_utc=VALUES(paused_at_utc),
          updated_at_utc=VALUES(updated_at_utc)
        """,
        (model_name, reason, now_ts.replace(tzinfo=None), now_ts.replace(tzinfo=None)),
    )


def clear_model_paused(cur, model_name: str, now_ts: datetime) -> None:
    cur.execute(
        """
        INSERT INTO live_model_state (model_name, paused, paused_reason, paused_at_utc, updated_at_utc)
        VALUES (%s, 0, NULL, NULL, %s)
        ON DUPLICATE KEY UPDATE
          paused=0, paused_reason=NULL, paused_at_utc=NULL, updated_at_utc=VALUES(updated_at_utc)
        """,
        (model_name, now_ts.replace(tzinfo=None)),
    )


def load_feature_rows(cur, limit=8000) -> List[Dict]:
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, {",".join(SOURCE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc DESC
        LIMIT {limit}
        """
    )
    rows = cur.fetchall()
    rows.reverse()
    return rows


def current_risk_state(cur, cfg: Dict, model_name: str) -> Tuple[str, Dict]:
    """Risk is evaluated per-strategy, on that strategy's own closed trades -
    independent strategies sharing one real account shouldn't be able to
    trip each other's breaker, any more than sim's per-model risk gate lets
    one sim model's drawdown pause another's."""
    cur.execute("SELECT COALESCE(SUM(pnl_dollars),0) p FROM live_trades WHERE status='closed' AND model_name=%s", (model_name,))
    total_realized = float(cur.fetchone()["p"] or 0.0)
    cur.execute(
        "SELECT COALESCE(SUM(pnl_dollars),0) p FROM live_trades WHERE status='closed' AND model_name=%s AND DATE(closed_at_utc)=UTC_DATE()",
        (model_name,),
    )
    daily_realized = float(cur.fetchone()["p"] or 0.0)
    cur.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(entry_price_dollars*qty_contracts),0) n FROM live_positions WHERE model_name=%s",
        (model_name,),
    )
    pos = cur.fetchone()
    open_count = int(pos["c"] or 0)
    open_notional = float(pos["n"] or 0.0)
    total_dd = -min(0.0, total_realized)
    risk = "GREEN"
    reasons = []
    if daily_realized <= -abs(float(cfg["max_daily_loss"])):
        reasons.append("MAX_DAILY_LOSS")
    if total_dd >= abs(float(cfg["max_total_drawdown"])):
        reasons.append("MAX_TOTAL_DD")
    if reasons:
        risk = "RED"
    return risk, {
        "daily_realized": daily_realized,
        "total_realized": total_realized,
        "open_count": open_count,
        "open_notional": open_notional,
        "reasons": reasons,
    }


def compute_buy_qty(prob: float, ask: float, cfg: Dict) -> int:
    edge = prob - ask
    if edge <= float(cfg["edge_threshold"]):
        return 0
    max_by_cost = int(float(cfg["max_trade_cost"]) / max(ask, 1e-6))
    scaled = int((edge / 0.03) * max_by_cost)
    return max(0, min(max_by_cost, max(1, scaled)))


# Kalshi retired the old order endpoint: POST /trade-api/v2/portfolio/orders
# now answers 410 deprecated_v1_order_endpoint, which crashed this engine every
# time a strategy actually wanted to trade. The replacement quotes everything
# from the YES leg and takes fixed-point strings rather than integer cents.
ORDER_PATH = "/trade-api/v2/portfolio/events/orders"
# immediate_or_cancel, not good_till_canceled: an IOC order either crosses now
# or is gone, so there is never a resting order whose state the engine would
# have to track. What it fills is read from the response - see
# DummyExecutionKernel.execute - and nothing is recorded unless it filled.
ORDER_TIME_IN_FORCE = os.getenv("KALSHI_ORDER_TIF", "immediate_or_cancel")

# Execution policy. Kalshi has no market order, so crossing the book means a
# limit priced through the touch; these say how far through.
#   entry: 1 tick. A missed entry costs nothing, so there is no reason to pay
#          more than the insurance against the book ticking mid-flight.
#   exit:  2 ticks, escalating by one per retry. A missed exit is what leaves
#          a position to settle at zero.
ENTRY_CROSS_TICKS = int(os.getenv("KALSHI_ENTRY_CROSS_TICKS", "1"))
EXIT_CROSS_TICKS = int(os.getenv("KALSHI_EXIT_CROSS_TICKS", "2"))
# If the live ask has run this far past the price the signal was computed at,
# the edge is gone: abandon the entry rather than chase it.
MAX_ENTRY_SLIPPAGE = float(os.getenv("KALSHI_MAX_ENTRY_SLIPPAGE", "0.02"))
ORDER_MAX_ATTEMPTS = int(os.getenv("KALSHI_ORDER_MAX_ATTEMPTS", "3"))
MAX_QUOTE_AGE_SECONDS = float(os.getenv("KALSHI_MAX_QUOTE_AGE_SECONDS", "2.0"))


def _opt_float(name: str) -> Optional[float]:
    """Optional float env knob: None (feature off) for unset/blank/unparseable."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# Thin-book execution controls (see MarketableLimitKernel); all off unless set. Each can only
# shrink or abandon an order and none can block an exit, so enabling any is strictly stricter.
MAX_BOOK_FRACTION = _opt_float("KALSHI_MAX_BOOK_FRACTION")
MAX_ENTRY_SPREAD = _opt_float("KALSHI_MAX_ENTRY_SPREAD")
MAX_ORDER_NOTIONAL = _opt_float("KALSHI_MAX_ORDER_NOTIONAL")


def place_limit_order(
    ticker: str, action: str, side: str, qty: int, price_dollars: float, credentials=None,
    client_order_id: Optional[str] = None,
) -> Dict:
    """Submit one limit order. `action` is buy/sell and `side` is the leg
    (yes|no). v2 speaks only the YES leg as bid/ask, so order_wire_params folds
    both legs into it: buy YES = bid, sell YES = ask, and a NO order is its YES
    complement (buy NO = sell YES = ask at 1 - no_price, sell NO = bid at
    1 - no_price). `price_dollars` is the order's OWN-side price."""
    if str(side).lower() not in ("yes", "no"):
        raise ValueError(f"side must be yes or no, got side={side!r}")
    if str(action).lower() not in ("buy", "sell"):
        raise ValueError(f"action must be buy or sell, got {action!r}")
    v2_side, wire_price = order_wire_params(action, side, price_dollars)
    # Same 1c..99c bounds and whole-cent rounding the old endpoint enforced, so
    # this change alters the transport and not the prices being sent.
    cents = max(1, min(99, int(round(float(wire_price) * 100))))
    # A persisted, idempotent client_order_id (EXECUTION_RISK_HARDENING P0-1) is reused on any retry
    # so a timed-out-but-filled order replays as a safe no-op; a fresh uuid otherwise (legacy path).
    client_order_id = client_order_id or str(uuid.uuid4())
    body = {
        "ticker": ticker,
        "side": v2_side,
        "count": f"{int(qty)}.00",
        "price": f"{cents / 100.0:.4f}",
        "time_in_force": ORDER_TIME_IN_FORCE,
        "self_trade_prevention_type": "taker_at_cross",
        "client_order_id": client_order_id,
    }
    resp = api_post_auth(ORDER_PATH, body, credentials=credentials)
    return {"client_order_id": client_order_id, "body": body, "resp": resp}


def open_live_position(
    cur, kernel: DummyExecutionKernel, model_name: str, ticker: str, qty: int, ask: float, prob: float, now_ts: datetime
) -> None:
    intent = TradeIntent(
        action="buy",
        side="yes",
        ticker=ticker,
        qty_contracts=qty,
        limit_price_dollars=ask,
        model_name=model_name,
        now_ts=now_ts,
        metadata={"prob_yes": prob},
    )
    rep = kernel.execute(intent)
    cur.execute(
        """
        INSERT INTO live_orders (created_at_utc,market_ticker,action,side,qty_contracts,limit_price_dollars,status,kalshi_order_id,client_order_id,raw_json)
        VALUES (%s,%s,'buy','yes',%s,%s,%s,%s,%s,%s)
        """,
        (
            now_ts.replace(tzinfo=None),
            ticker,
            qty,
            ask,
            rep.status,
            rep.external_order_id,
            rep.client_order_id,
            json.dumps(rep.raw_json),
        ),
    )
    # Record only what Kalshi actually filled. This used to record the full
    # requested quantity at the requested price for any order that was not
    # explicitly rejected - "conservative assumption for MVP" - so an
    # immediate-or-cancel order that crossed nothing still produced a position
    # in the book. On 2026-09-27 four such phantom positions were opened; the
    # engine then "closed" each one, and a sell against a position that does
    # not exist is not a no-op on Kalshi, it opens a short. Those unintended
    # shorts settled worthless and cost real money, while the dashboard
    # reported the phantom round-trips as wins.
    filled = int(rep.fill_qty_contracts)
    if filled <= 0:
        print(
            "live %s %s no fill (%s), requested %s @ %.2f - nothing recorded"
            % (model_name, ticker, rep.status, qty, ask)
        )
        return
    entry_px = float(rep.fill_price_dollars)
    if filled < qty:
        print("live %s %s partial fill %s of %s @ %.4f" % (model_name, ticker, filled, qty, entry_px))
    meta = json.dumps(
        {
            "prob": prob,
            "order": rep.raw_json,
            "requested_qty": qty,
            "requested_price": ask,
            "fill_qty": filled,
            "fill_price": entry_px,
            "entry_fee": float(rep.fee_dollars),
        }
    )
    cur.execute(
        """
        INSERT INTO live_positions (model_name,market_ticker,opened_at_utc,qty_contracts,entry_price_dollars,raw_json)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          opened_at_utc=VALUES(opened_at_utc),
          qty_contracts=VALUES(qty_contracts),
          entry_price_dollars=VALUES(entry_price_dollars),
          raw_json=VALUES(raw_json)
        """,
        (model_name, ticker, now_ts.replace(tzinfo=None), filled, entry_px, meta),
    )
    cur.execute(
        """
        INSERT INTO live_trades (opened_at_utc,market_ticker,model_name,qty_contracts,entry_price_dollars,status,raw_json)
        VALUES (%s,%s,%s,%s,%s,'open',%s)
        """,
        (now_ts.replace(tzinfo=None), ticker, model_name, filled, entry_px, meta),
    )


def close_live_position(
    cur,
    kernel: DummyExecutionKernel,
    model_name: str,
    ticker: str,
    bid: float,
    now_ts: datetime,
    limit_price: Optional[float] = None,
) -> None:
    cur.execute("SELECT * FROM live_positions WHERE model_name=%s AND market_ticker=%s", (model_name, ticker))
    pos = cur.fetchone()
    if not pos:
        return
    qty = int(pos["qty_contracts"])
    entry = float(pos["entry_price_dollars"])
    px = float(limit_price if limit_price is not None else bid)
    if px <= 0:
        return
    intent = TradeIntent(
        action="sell",
        side="yes",
        ticker=ticker,
        qty_contracts=qty,
        limit_price_dollars=px,
        model_name=model_name,
        now_ts=now_ts,
        metadata={"entry_price": entry},
    )
    rep = kernel.execute(intent)
    cur.execute(
        """
        INSERT INTO live_orders (created_at_utc,market_ticker,action,side,qty_contracts,limit_price_dollars,status,kalshi_order_id,client_order_id,raw_json)
        VALUES (%s,%s,'sell','yes',%s,%s,%s,%s,%s,%s)
        """,
        (
            now_ts.replace(tzinfo=None),
            ticker,
            qty,
            px,
            rep.status,
            rep.external_order_id,
            rep.client_order_id,
            json.dumps(rep.raw_json),
        ),
    )
    # A sell that did not fill leaves the position exactly where it was. The
    # position row must survive so the next tick can try again; deleting it
    # here is what would let the engine forget a holding it still has.
    sold = int(rep.fill_qty_contracts)
    if sold <= 0:
        print(
            "live %s %s exit did not fill (%s), still holding %s - position kept"
            % (model_name, ticker, rep.status, qty)
        )
        return
    exit_px = float(rep.fill_price_dollars)
    entry_fee = 0.0
    pos_raw = pos.get("raw_json")
    if isinstance(pos_raw, str):
        try:
            pos_raw = json.loads(pos_raw)
        except Exception:
            pos_raw = {}
    if isinstance(pos_raw, dict):
        entry_fee = float(pos_raw.get("entry_fee") or 0.0)
    # Fees are real money and were previously left out entirely.
    fee = float(rep.fee_dollars) + entry_fee * (sold / float(qty) if qty else 1.0)
    pnl = (exit_px - entry) * sold - fee
    cur.execute(
        """
        UPDATE live_trades
        SET closed_at_utc=%s, exit_price_dollars=%s, pnl_dollars=%s, qty_contracts=%s, status='closed'
        WHERE market_ticker=%s AND model_name=%s AND status='open'
        ORDER BY opened_at_utc DESC
        LIMIT 1
        """,
        (now_ts.replace(tzinfo=None), exit_px, pnl, sold, ticker, model_name),
    )
    if sold < qty:
        # Partial exit: keep the remainder on the books at the same entry.
        print("live %s %s partial exit %s of %s @ %.4f" % (model_name, ticker, sold, qty, exit_px))
        cur.execute(
            "UPDATE live_positions SET qty_contracts=%s WHERE model_name=%s AND market_ticker=%s",
            (qty - sold, model_name, ticker),
        )
        cur.execute(
            """
            INSERT INTO live_trades (opened_at_utc,market_ticker,model_name,qty_contracts,entry_price_dollars,status,raw_json)
            VALUES (%s,%s,%s,%s,%s,'open',%s)
            """,
            (
                pos["opened_at_utc"],
                ticker,
                model_name,
                qty - sold,
                entry,
                json.dumps({"carried_from_partial_exit": True, "original_qty": qty}),
            ),
        )
        return
    cur.execute("DELETE FROM live_positions WHERE model_name=%s AND market_ticker=%s", (model_name, ticker))


def settled_results() -> Dict[str, Dict]:
    """Markets this account held that Kalshi has already settled, by ticker.

    `market_result` is "yes" or "no"; we are always long the YES leg, so a
    settled market is worth exactly $1.00 or $0.00 per contract.
    """
    try:
        data = api_get_auth("/trade-api/v2/portfolio/settlements?limit=100")
    except Exception as e:
        print(f"live settlement lookup failed: {e}")
        return {}
    out: Dict[str, Dict] = {}
    for row in data.get("settlements") or []:
        ticker = row.get("ticker")
        if ticker and ticker not in out:
            out[ticker] = row
    return out


def reconcile_settled_positions(cur, now_ts: datetime) -> None:
    """Book positions whose market has expired.

    The engine only ever closed a position by selling it. When the exit order
    could not fill - no bid, which is routine in the last minutes of a
    15-minute contract - the market simply expired underneath the position and
    the row stayed 'open' forever, so a total loss was never booked and the
    dashboard kept showing it as a live holding at a stale mark. That happened
    on 2026-09-27 to 27 contracts of KXBTC15M-26SEP271315-15: six consecutive
    sell orders were cancelled, the market settled "no", and $8.64 vanished
    without ever reaching live_trades.

    A settled contract is worth $1.00 or $0.00 - there is nothing left to sell,
    so this books it directly instead of trying to trade out of it.

    Status stays 'closed' rather than a new 'settled': every P&L query in the
    dashboard and, more importantly, the daily-loss and drawdown caps in
    current_risk_state filter on status='closed'. A distinct status would hide
    settlement losses from the risk caps - the same class of bug as the one
    this function exists to fix. The exit price of exactly 1.00 or 0.00 is
    what marks a trade as settled rather than sold.
    """
    cur.execute("SELECT * FROM live_positions")
    positions = cur.fetchall()
    if not positions:
        return
    results = settled_results()
    if not results:
        return
    for pos in positions:
        ticker = pos["market_ticker"]
        row = results.get(ticker)
        if not row:
            continue
        model_name = pos["model_name"]
        qty = int(pos["qty_contracts"])
        entry = float(pos["entry_price_dollars"])
        won = str(row.get("market_result", "")).lower() == "yes"
        exit_px = 1.0 if won else 0.0
        entry_fee = 0.0
        raw = pos.get("raw_json")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if isinstance(raw, dict):
            entry_fee = float(raw.get("entry_fee") or 0.0)
        try:
            settle_fee = float(row.get("fee_cost") or 0.0)
        except (TypeError, ValueError):
            settle_fee = 0.0
        pnl = (exit_px - entry) * qty - entry_fee - settle_fee
        cur.execute(
            """
            UPDATE live_trades
            SET closed_at_utc=%s, exit_price_dollars=%s, pnl_dollars=%s, status='closed'
            WHERE market_ticker=%s AND model_name=%s AND status='open'
            ORDER BY opened_at_utc DESC
            LIMIT 1
            """,
            (now_ts.replace(tzinfo=None), exit_px, pnl, ticker, model_name),
        )
        cur.execute(
            "DELETE FROM live_positions WHERE model_name=%s AND market_ticker=%s", (model_name, ticker)
        )
        print(
            "live %s %s SETTLED %s: %s contracts entered at %.4f -> %.2f, pnl %.2f"
            % (model_name, ticker, row.get("market_result"), qty, entry, exit_px, pnl)
        )


def latest_bid_for_ticker(ticker: str) -> Optional[float]:
    try:
        data = api_get(f"/markets/{ticker}")
    except Exception:
        return None
    m = data.get("market") or {}
    bid = m.get("yes_bid_dollars")
    if bid is None:
        return None
    return float(bid)


def run_loop() -> None:
    conn = get_db_conn()
    with conn.cursor() as cur:
        print(f"live trading engine started (multi-strategy: {', '.join(LIVE_MODELS)}).")
        migrate_legacy_settings(cur)
        # Prices come from the live book at submit time. The bar below is
        # only ever used for model features - never for a price.
        feed = MarketFeed(ws_feed=None, max_quote_age_seconds=MAX_QUOTE_AGE_SECONDS)
        kernel = MarketableLimitKernel(
            place_limit_order,
            feed,
            entry_cross_ticks=ENTRY_CROSS_TICKS,
            exit_cross_ticks=EXIT_CROSS_TICKS,
            max_entry_slippage=MAX_ENTRY_SLIPPAGE,
            max_attempts=ORDER_MAX_ATTEMPTS,
            max_quote_age_seconds=MAX_QUOTE_AGE_SECONDS,
            max_book_fraction=MAX_BOOK_FRACTION,
            max_entry_spread=MAX_ENTRY_SPREAD,
            max_order_notional=MAX_ORDER_NOTIONAL,
        )
        risk_engine = DummyRiskEngine() if RISK_ENGINE_MODE == "dummy" else LiveSettingsRiskEngine()
        frozen_models = None
        frozen_cutoff = None
        while True:
            wake = next_minute_plus_delay(12)
            time.sleep(max(0.0, (wake - utc_now()).total_seconds()))
            now_ts = wake.replace(second=0, microsecond=0)
            try:
                rows = load_feature_rows(cur, limit=200000)
                if len(rows) < 20:
                    continue
                if frozen_models is None:
                    requested_cutoff = get_live_cutoff_utc(cur)
                    frozen_cutoff = choose_effective_cutoff(rows, requested_cutoff)
                    frozen_models = fit_frozen_models(rows, frozen_cutoff)
                    print(
                        "live frozen models ready: "
                        f"cutoff={frozen_cutoff.isoformat() if frozen_cutoff else 'none'} "
                        f"rf_train={frozen_models['random_forest'].train_rows} "
                        f"rf_regime={frozen_models['random_forest'].rf_regime}"
                    )
                latest = rows[-1]
                if not has_target(latest):
                    continue
                ticker = latest["market_ticker"]
                if not ticker:
                    continue
                # The bar's own bid/ask are deliberately NOT used to price or
                # size anything: on 2026-09-27 that bar read 0.58/0.59 against
                # a live book of 0.70/0.71. Features come from the bar, prices
                # come from the book.
                live = feed.quote(ticker)
                if live is None or not live.tradable:
                    print(f"live: no usable quote for {ticker}, skipping tick")
                    continue
                bid = float(live.yes_bid)
                ask = float(live.yes_ask)

                x_latest = np.asarray(build_feature_vector(latest), dtype=float)
                outputs = score_frozen_models(frozen_models, x_latest, latest_row=latest)
                tte = latest.get("time_to_expiry_sec")
                near_expiry = tte is not None and float(tte) <= 60
                # Before any exit is attempted: a market that has already
                # settled cannot be sold, only booked.
                reconcile_settled_positions(cur, now_ts)

                pause_states = get_all_live_pause_states(cur)
                snapshot_by_model = {}

                for model_name in LIVE_MODELS:
                    cfg = load_settings(cur, model_name)
                    out = outputs[model_name]
                    prob = out.prob
                    edge_threshold = float(cfg["edge_threshold"])
                    edge = prob - ask
                    signal = prob >= float(cfg["signal_threshold"]) and edge > edge_threshold
                    already_paused = model_name in pause_states

                    risk_state, risk_meta = current_risk_state(cur, cfg, model_name)
                    if risk_state == "RED" and not already_paused:
                        reason = f"risk breach: {','.join(risk_meta['reasons'])} (daily=${risk_meta['daily_realized']:.2f} total=${risk_meta['total_realized']:.2f})"
                        set_model_paused(cur, model_name, reason, now_ts)
                        already_paused = True
                        print(f"live {model_name}: AUTO-PAUSED - {reason}")

                    # Manage any existing position regardless of pause state -
                    # a paused strategy still needs to be able to exit, only
                    # new entries are blocked.
                    cur.execute(
                        "SELECT market_ticker FROM live_positions WHERE model_name=%s LIMIT 1", (model_name,)
                    )
                    pos = cur.fetchone()
                    should_close_here = should_close_position(model_name, prob, edge, edge_threshold) or near_expiry
                    if pos and pos["market_ticker"] != ticker:
                        old_bid = latest_bid_for_ticker(pos["market_ticker"]) or 0.0
                        close_live_position(cur, kernel, model_name, pos["market_ticker"], old_bid, now_ts)
                    elif pos and should_close_here:
                        # Price to the real current bid, not a flat $0.99 - Kalshi
                        # quotes in $0.001 increments right up to the extremes (our
                        # own forward_quotes history shows real bids from 0.001 to
                        # 0.999), so a hardcoded $0.99 either leaves value on the
                        # table on a winner or, worse, would never fill at all on a
                        # position that's actually losing near expiry.
                        close_live_position(cur, kernel, model_name, pos["market_ticker"], bid, now_ts)

                    live_enabled = bool(cfg["live_enabled"])
                    decision_allowed = False
                    decision_reasons = []
                    if live_enabled and not already_paused:
                        decision = risk_engine.evaluate(
                            RiskContext(
                                cfg=cfg,
                                risk_state=risk_state,
                                risk_meta=risk_meta,
                                ticker=ticker,
                                signal=bool(signal),
                                prob=float(prob),
                                edge=float(edge),
                                near_expiry=bool(near_expiry),
                            )
                        )
                        decision_allowed = decision.allowed
                        decision_reasons = decision.reasons
                        if decision.allowed and signal:
                            qty = compute_buy_qty(prob, ask, cfg)
                            if qty > 0:
                                open_live_position(cur, kernel, model_name, ticker, qty, ask, prob, now_ts)

                    snapshot_by_model[model_name] = {
                        "live_enabled": live_enabled,
                        "paused": already_paused,
                        "risk_state": risk_state,
                        "risk_decision": {"allowed": decision_allowed, "reasons": decision_reasons},
                        "risk": risk_meta,
                        "prob": prob,
                        "signal": signal,
                        "edge": edge,
                    }
                    print(
                        f"live {model_name} t={now_ts.isoformat()} ticker={ticker} p={prob:.4f} edge={edge:.4f} "
                        f"signal={int(signal)} enabled={int(live_enabled)} paused={int(already_paused)} risk={risk_state}"
                    )

                state = {
                    "ticker": ticker,
                    "frozen_cutoff_utc": frozen_cutoff.isoformat() if frozen_cutoff else None,
                    "models": snapshot_by_model,
                }
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES ('live_trading_last_snapshot',%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (json.dumps(state), utc_now().replace(tzinfo=None)),
                )
            except Exception as e:
                print(f"live trading error at {now_ts.isoformat()}: {e}")
                # Re-raise so the outer loop tears down this connection/cursor and
                # acquires a fresh one, instead of retrying forever on a dead connection.
                # No change to signal/trigger/risk logic above - this only affects
                # recovery from a broken DB connection.
                raise


if __name__ == "__main__":
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f"[ERROR] live trading engine crashed: {e}")
            time.sleep(5)
