"""Database access layer for the simulated trading engine.

Everything here is I/O: reading feature rows, reading/writing positions and
trades, and persisting settings/pause state. Decision logic (which model to
trust, how much to buy, when to force-close) lives in simulated_trading_engine.py
and calls into this module rather than issuing SQL directly - this is what
makes that logic unit-testable against a mocked cursor.
"""
import ast
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from data_pipeline.kalshi_fees import taker_fee_dollars
from data_pipeline.modeling_features import SOURCE_COLS
from data_pipeline.sim_config import (
    STARTING_CAPITAL,
    SimRiskSettings,
    sim_risk_settings_from_dict,
    sim_risk_settings_to_dict,
)


def load_feature_rows(cur, limit: int = 8000) -> List[Dict]:
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, event_ticker, {",".join(SOURCE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc DESC
        LIMIT {limit}
        """
    )
    rows = cur.fetchall()
    rows.reverse()
    return rows


def latest_feature_row(cur) -> Optional[Dict]:
    cur.execute(
        f"""
        SELECT snapshot_minute_utc, market_ticker, event_ticker, {",".join(SOURCE_COLS)}
        FROM model_features_1m
        WHERE model_eligible=1
        ORDER BY snapshot_minute_utc DESC
        LIMIT 1
        """
    )
    return cur.fetchone()


def parse_iso_utc(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except Exception:
        return None


def get_live_cutoff_utc(cur) -> Optional[datetime]:
    cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_live_cutoff_utc' LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    sv = row.get("state_value")
    if isinstance(sv, dict):
        return parse_iso_utc(sv.get("cutoff_utc"))
    try:
        j = json.loads(sv)
        if isinstance(j, dict):
            return parse_iso_utc(j.get("cutoff_utc"))
    except Exception:
        pass
    return parse_iso_utc(str(sv))


def is_sim_recompute_in_progress(cur) -> bool:
    cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_recompute_in_progress' LIMIT 1")
    row = cur.fetchone()
    if not row:
        return False
    sv = row.get("state_value")
    if isinstance(sv, dict):
        return bool(sv.get("in_progress"))
    try:
        j = json.loads(sv)
        if isinstance(j, dict):
            return bool(j.get("in_progress"))
    except Exception:
        pass
    return False


def _parse_orderbook_levels(raw_json: Optional[dict]) -> List[Tuple[float, float]]:
    if not raw_json:
        return []
    candidates = [
        raw_json.get("yes_bids"),
        raw_json.get("yes_bid_levels"),
        raw_json.get("orderbook_yes_bids"),
    ]
    ob = raw_json.get("orderbook")
    if isinstance(ob, dict):
        candidates.extend([ob.get("yes_bids"), ob.get("yes"), ob.get("bids")])
    levels: List[Tuple[float, float]] = []
    for cand in candidates:
        if not isinstance(cand, list):
            continue
        for lv in cand:
            p = None
            q = None
            if isinstance(lv, dict):
                p = (
                    lv.get("price")
                    or lv.get("yes_bid_dollars")
                    or lv.get("yes_bid")
                    or lv.get("p")
                    or lv.get("price_dollars")
                )
                q = (
                    lv.get("size")
                    or lv.get("size_fp")
                    or lv.get("yes_bid_size_fp")
                    or lv.get("qty")
                    or lv.get("quantity")
                    or lv.get("contracts")
                    or lv.get("count")
                    or lv.get("q")
                )
            elif isinstance(lv, (list, tuple)) and len(lv) >= 2:
                p, q = lv[0], lv[1]
            if p is None or q is None:
                continue
            try:
                pf = float(p)
                qf = float(q)
            except Exception:
                continue
            # Some payloads use cent units (0..100) instead of dollars (0..1).
            if pf > 1.0 and pf <= 100.0:
                pf = pf / 100.0
            if pf <= 0 or qf <= 0:
                continue
            levels.append((pf, qf))
        if levels:
            break
    levels.sort(key=lambda x: x[0], reverse=True)
    return levels


def best_bid_snapshot(cur, ticker: str, as_of_ts: Optional[datetime] = None) -> Dict:
    if as_of_ts is None:
        cur.execute(
            """
            SELECT yes_bid_dollars, yes_bid_size_fp, raw_json
            FROM forward_quotes
            WHERE market_ticker=%s
            ORDER BY snapshot_time_utc DESC
            LIMIT 1
            """,
            (ticker,),
        )
    else:
        cur.execute(
            """
            SELECT yes_bid_dollars, yes_bid_size_fp, raw_json
            FROM forward_quotes
            WHERE market_ticker=%s AND snapshot_time_utc<=%s
            ORDER BY snapshot_time_utc DESC
            LIMIT 1
            """,
            (ticker, as_of_ts.replace(tzinfo=None)),
        )
    r = cur.fetchone()
    if not r and as_of_ts is not None:
        # No quote at/before as_of_ts (e.g. this ticker stopped receiving
        # quotes well before the position finally got closed - happens when
        # a close was delayed, see the reconnect fixes elsewhere in this
        # session). Fall back to the last quote ever recorded for it rather
        # than pricing the exit at $0, which would misprice a contract that
        # actually settled ITM.
        cur.execute(
            """
            SELECT yes_bid_dollars, yes_bid_size_fp, raw_json
            FROM forward_quotes
            WHERE market_ticker=%s
            ORDER BY snapshot_time_utc DESC
            LIMIT 1
            """,
            (ticker,),
        )
        r = cur.fetchone()
    r = r or {}
    raw = r.get("raw_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            try:
                raw = ast.literal_eval(raw)
            except Exception:
                raw = {}
    elif not isinstance(raw, dict):
        raw = {}
    bid = r.get("yes_bid_dollars")
    size = r.get("yes_bid_size_fp")
    levels = _parse_orderbook_levels(raw)
    if bid is not None:
        bid_f = float(bid)
        size_f = float(size) if size is not None else 0.0
        if bid_f > 0:
            if not levels:
                levels = [(bid_f, size_f)]
            elif levels[0][0] != bid_f:
                levels = [(bid_f, size_f)] + levels
    return {
        "bid": (float(bid) if bid is not None else None),
        "bid_size": (float(size) if size is not None else None),
        "levels": levels,
    }


def estimate_sell_proceeds(snapshot: Dict, qty: int) -> Tuple[float, float]:
    if qty <= 0:
        return 0.0, 0.0
    levels = list(snapshot.get("levels") or [])
    if levels:
        best_bid = float(levels[0][0])
        if best_bid > 0:
            proceeds = float(qty) * best_bid
            avg_px = proceeds / float(qty)
            return avg_px, proceeds
    bid = snapshot.get("bid")
    if bid is None or float(bid) <= 0:
        return 0.0, 0.0
    proceeds = float(qty) * float(bid)
    avg_px = proceeds / float(qty)
    return avg_px, proceeds


def get_open_position(cur, model_name: str) -> Optional[Dict]:
    cur.execute("SELECT * FROM sim_positions WHERE model_name=%s", (model_name,))
    return cur.fetchone()


def close_existing_position(
    cur,
    model_name: str,
    now_row: Dict,
    now_ts: datetime,
    should_close_same_ticker: bool = False,
    force_exit_price: Optional[float] = None,
) -> float:
    pos = get_open_position(cur, model_name)
    if not pos:
        return 0.0

    same_ticker = pos["market_ticker"] == now_row["market_ticker"]
    if same_ticker:
        if not should_close_same_ticker:
            return 0.0
        # Source exits from the forward_quotes snapshot path so the bid
        # ladder/size is consistently used for both same-ticker and rollover
        # closes. Kalshi quotes in $0.001 increments near the extremes (seen
        # directly in our own forward_quotes history, e.g. 0.991-0.999), so a
        # real near-expiry quote is usually more accurate than a flat floor -
        # force_exit_price is only a fallback for the rare case where no
        # quote exists at all (see estimate_sell_proceeds returning 0.0),
        # not a substitute for a real one.
        snap = best_bid_snapshot(cur, pos["market_ticker"], as_of_ts=now_ts)
        exit_px, _ = estimate_sell_proceeds(snap, int(pos["qty_contracts"]))
        if exit_px <= 0 and force_exit_price is not None:
            exit_px = force_exit_price
    else:
        # Ticker rotated; close the stale position using its own latest quote.
        stale_snap = best_bid_snapshot(cur, pos["market_ticker"], as_of_ts=now_ts)
        exit_px, _ = estimate_sell_proceeds(stale_snap, int(pos["qty_contracts"]))

    entry_px = float(pos["entry_price_dollars"])
    qty = int(pos["qty_contracts"])
    pnl = (exit_px - entry_px) * qty
    cur.execute(
        """
        UPDATE sim_trades
        SET closed_at_utc=%s, exit_price_dollars=%s, pnl_dollars=%s, status='closed'
        WHERE id=%s
        """,
        (now_ts.replace(tzinfo=None), exit_px, pnl, pos["trade_id"]),
    )
    cur.execute("DELETE FROM sim_positions WHERE model_name=%s", (model_name,))
    return pnl


def open_new_position(
    cur,
    model_name: str,
    now_row: Dict,
    now_ts: datetime,
    prob: float,
    edge: float,
    qty: int,
    entry_price: float,
) -> Optional[Dict]:
    """Persist a new position. Sizing/eligibility decisions are the caller's
    job (see simulated_trading_engine.decide_new_position) - this function
    just writes what it's told, guarding only against a position already
    being open for this model."""
    if qty <= 0 or entry_price <= 0:
        return None
    if get_open_position(cur, model_name):
        return None
    raw = {"prob_yes": prob, "edge": edge, "qty_requested": qty, "fill": {"mode": "quote_ask_conservative", "ticker": now_row["market_ticker"]}}
    cur.execute(
        """
        INSERT INTO sim_trades
        (model_name, market_ticker, opened_at_utc, qty_contracts, entry_price_dollars, status, raw_json)
        VALUES (%s,%s,%s,%s,%s,'open',%s)
        """,
        (
            model_name,
            now_row["market_ticker"],
            now_ts.replace(tzinfo=None),
            qty,
            entry_price,
            json.dumps(raw),
        ),
    )
    trade_id = cur.lastrowid
    cur.execute(
        """
        INSERT INTO sim_positions (model_name, opened_at_utc, market_ticker, qty_contracts, entry_price_dollars, trade_id, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          opened_at_utc=VALUES(opened_at_utc), market_ticker=VALUES(market_ticker),
          qty_contracts=VALUES(qty_contracts), entry_price_dollars=VALUES(entry_price_dollars),
          trade_id=VALUES(trade_id), raw_json=VALUES(raw_json)
        """,
        (
            model_name,
            now_ts.replace(tzinfo=None),
            now_row["market_ticker"],
            qty,
            entry_price,
            trade_id,
            json.dumps(raw),
        ),
    )
    return {"edge": edge, "qty": qty, "entry_price": entry_price}


def upsert_prediction(cur, now_ts: datetime, model_name: str, row: Dict, feature_vec, feature_cols, out, signal: int, edge: float) -> None:
    feature_payload = {k: float(feature_vec[i]) for i, k in enumerate(feature_cols)}
    cur.execute(
        """
        INSERT INTO sim_model_predictions_1m
        (snapshot_minute_utc, model_name, market_ticker, prob_yes, signal_yes, edge_est, train_rows, test_rows, brier, logloss, rf_regime, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          market_ticker=VALUES(market_ticker), prob_yes=VALUES(prob_yes), signal_yes=VALUES(signal_yes),
          edge_est=VALUES(edge_est), train_rows=VALUES(train_rows), test_rows=VALUES(test_rows),
          brier=VALUES(brier), logloss=VALUES(logloss), rf_regime=VALUES(rf_regime), raw_json=VALUES(raw_json)
        """,
        (
            now_ts.replace(tzinfo=None),
            model_name,
            row["market_ticker"],
            out.prob,
            signal,
            edge,
            out.train_rows,
            out.test_rows,
            out.brier,
            out.ll,
            out.rf_regime,
            json.dumps({"features": feature_payload}),
        ),
    )


def get_model_equity(cur, model_name: str) -> float:
    """Current mark-to-market equity for a model: starting capital + realized
    PnL to date + unrealized PnL on any open position."""
    cur.execute(
        "SELECT COALESCE(SUM(pnl_dollars),0) p FROM sim_trades WHERE model_name=%s AND status='closed'",
        (model_name,),
    )
    realized = float(cur.fetchone()["p"] or 0.0)
    unrealized = 0.0
    pos = get_open_position(cur, model_name)
    if pos:
        snap = best_bid_snapshot(cur, pos["market_ticker"])
        mark_px, _ = estimate_sell_proceeds(snap, int(pos["qty_contracts"]))
        unrealized = (float(mark_px) - float(pos["entry_price_dollars"])) * int(pos["qty_contracts"])
    return STARTING_CAPITAL + realized + unrealized


def upsert_equity(cur, now_ts: datetime, model_name: str, realized_pnl: float) -> float:
    cur.execute(
        """
        SELECT cumulative_pnl_dollars, closed_trades_count
        FROM sim_equity_1m
        WHERE model_name=%s
        ORDER BY snapshot_minute_utc DESC
        LIMIT 1
        """,
        (model_name,),
    )
    prev = cur.fetchone()
    prev_cum = float(prev["cumulative_pnl_dollars"]) if prev else 0.0
    cur.execute("SELECT COUNT(*) c, SUM(pnl_dollars > 0) w FROM sim_trades WHERE model_name=%s AND status='closed'", (model_name,))
    agg = cur.fetchone()
    closed_count = int(agg["c"] or 0)
    wins = int(agg["w"] or 0)
    win_rate = (wins / closed_count) if closed_count > 0 else None
    new_cum = prev_cum + realized_pnl
    unrealized = 0.0
    pos = get_open_position(cur, model_name)
    if pos:
        snap = best_bid_snapshot(cur, pos["market_ticker"], as_of_ts=now_ts)
        mark_px, _ = estimate_sell_proceeds(snap, int(pos["qty_contracts"]))
        unrealized = (float(mark_px) - float(pos["entry_price_dollars"])) * int(pos["qty_contracts"])
    equity_dollars = STARTING_CAPITAL + new_cum + unrealized
    cur.execute(
        """
        INSERT INTO sim_equity_1m
        (snapshot_minute_utc, model_name, realized_pnl_dollars, cumulative_pnl_dollars, closed_trades_count, win_rate, raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          realized_pnl_dollars=VALUES(realized_pnl_dollars),
          cumulative_pnl_dollars=VALUES(cumulative_pnl_dollars),
          closed_trades_count=VALUES(closed_trades_count),
          win_rate=VALUES(win_rate),
          raw_json=VALUES(raw_json)
        """,
        (
            now_ts.replace(tzinfo=None),
            model_name,
            realized_pnl,
            new_cum,
            closed_count,
            win_rate,
            json.dumps({"wins": wins, "unrealized_pnl_dollars": unrealized, "equity_dollars": equity_dollars}),
        ),
    )
    return equity_dollars


def get_latest_drawdown_pct(cur, model_name: str) -> Optional[float]:
    """Drawdown from peak realized equity, as a fraction of starting capital
    (negative = below peak). Computed from sim_equity_1m directly (not
    sim_portfolio_20s, which is written by a separate 20s-cadence process on
    a different formula, may be down independently of this engine, and is
    never repopulated during a full historical recompute) so the risk gate
    behaves identically whether ticking live or replaying history. None if
    sim_equity_1m has no rows for this model yet."""
    cur.execute(
        "SELECT cumulative_pnl_dollars FROM sim_equity_1m WHERE model_name=%s ORDER BY snapshot_minute_utc DESC LIMIT 1",
        (model_name,),
    )
    latest = cur.fetchone()
    if not latest or latest.get("cumulative_pnl_dollars") is None:
        return None
    cur.execute("SELECT MAX(cumulative_pnl_dollars) AS peak FROM sim_equity_1m WHERE model_name=%s", (model_name,))
    peak_row = cur.fetchone()
    current_cum = float(latest["cumulative_pnl_dollars"])
    peak_cum = float(peak_row["peak"]) if peak_row and peak_row.get("peak") is not None else current_cum
    return (current_cum - peak_cum) / STARTING_CAPITAL


def get_sim_risk_settings(cur) -> SimRiskSettings:
    cur.execute("SELECT settings_json FROM sim_settings WHERE settings_key='risk_config' LIMIT 1")
    row = cur.fetchone()
    if not row:
        return SimRiskSettings()
    sv = row["settings_json"]
    cfg = sv if isinstance(sv, dict) else json.loads(sv)
    return sim_risk_settings_from_dict(cfg)


def update_sim_risk_settings(cur, patch: Dict) -> SimRiskSettings:
    current = sim_risk_settings_to_dict(get_sim_risk_settings(cur))
    current.update({k: v for k, v in (patch or {}).items() if k in current})
    cur.execute(
        """
        INSERT INTO sim_settings (settings_key, settings_json, updated_at_utc)
        VALUES ('risk_config', %s, UTC_TIMESTAMP())
        ON DUPLICATE KEY UPDATE settings_json=VALUES(settings_json), updated_at_utc=VALUES(updated_at_utc)
        """,
        (json.dumps(current),),
    )
    return sim_risk_settings_from_dict(current)


def get_model_pause_state(cur, model_name: str) -> Optional[Dict]:
    cur.execute(
        "SELECT paused, paused_reason, paused_at_utc FROM sim_model_state WHERE model_name=%s",
        (model_name,),
    )
    row = cur.fetchone()
    if not row or not row.get("paused"):
        return None
    return {"paused_reason": row.get("paused_reason"), "paused_at_utc": row.get("paused_at_utc")}


def get_all_model_pause_states(cur) -> Dict[str, Dict]:
    """All currently-paused models in one query, for dashboard visibility -
    there is otherwise no way to see (or clear) a drawdown-triggered pause
    short of a manual SQL query."""
    cur.execute("SELECT model_name, paused_reason, paused_at_utc FROM sim_model_state WHERE paused=1")
    return {
        r["model_name"]: {"paused_reason": r.get("paused_reason"), "paused_at_utc": str(r.get("paused_at_utc"))}
        for r in cur.fetchall()
    }


MIN_TRADES_FOR_STATUS = 30


def get_model_recommendation_status(cur, model_name: str, paused: bool) -> Dict:
    """Plain-English deploy recommendation for the Portfolio Manager panel -
    net of Kalshi's actual per-contract trading fee (see kalshi_fees.py),
    not just gross PnL, so a model that looks good pre-fees but isn't worth
    trading live gets flagged as such. Both legs are fee'd as taker fills -
    the sim engine crosses the book (buys at ask, sells at bid) rather than
    resting its own limit order, so the taker rate is the correct one here."""
    if paused:
        return {"status": "paused", "label": "PAUSED"}
    cur.execute(
        "SELECT qty_contracts, entry_price_dollars, exit_price_dollars FROM sim_trades "
        "WHERE model_name=%s AND status='closed' AND exit_price_dollars IS NOT NULL",
        (model_name,),
    )
    rows = cur.fetchall()
    n = len(rows)
    if n < MIN_TRADES_FOR_STATUS:
        return {"status": "gathering_data", "label": f"GATHERING DATA ({n}/{MIN_TRADES_FOR_STATUS} trades)"}
    gross = 0.0
    fees = 0.0
    for r in rows:
        qty = int(r["qty_contracts"])
        entry = float(r["entry_price_dollars"])
        exit_px = float(r["exit_price_dollars"])
        gross += (exit_px - entry) * qty
        fees += taker_fee_dollars(qty, entry) + taker_fee_dollars(qty, exit_px)
    net = gross - fees
    if net > 0:
        return {"status": "promising", "label": f"PROMISING - net +${net:.2f} after Kalshi taker fees ({n} trades)"}
    if gross > 0:
        return {"status": "thin_edge", "label": f"THIN EDGE - positive gross (+${gross:.2f}) but net negative after Kalshi taker fees"}
    return {"status": "negative", "label": f"NEGATIVE - net ${net:.2f} ({n} trades)"}


def set_model_paused(cur, model_name: str, reason: str, now_ts: datetime) -> None:
    cur.execute(
        """
        INSERT INTO sim_model_state (model_name, paused, paused_reason, paused_at_utc, updated_at_utc)
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
        INSERT INTO sim_model_state (model_name, paused, paused_reason, paused_at_utc, updated_at_utc)
        VALUES (%s, 0, NULL, NULL, %s)
        ON DUPLICATE KEY UPDATE
          paused=0, paused_reason=NULL, paused_at_utc=NULL, updated_at_utc=VALUES(updated_at_utc)
        """,
        (model_name, now_ts.replace(tzinfo=None)),
    )
