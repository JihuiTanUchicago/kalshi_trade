import html
import os
import base64
import hashlib
import hmac
import secrets
import ast
import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from data_pipeline.architecture.execution_kernel import DummyExecutionKernel
from data_pipeline.architecture.position_guard import exchange_net_reader, position_guarded_submitter
from data_pipeline.common import get_db_conn, utc_now
from data_pipeline.live_trading_engine import (
    LIVE_MODELS,
    close_live_position,
    current_risk_state as live_current_risk_state,
    clear_model_paused as clear_live_model_paused,
    get_all_live_pause_states,
    latest_bid_for_ticker,
    load_settings as live_load_settings,
    place_limit_order,
    update_settings as live_update_settings,
)
from data_pipeline.sim_config import STARTING_CAPITAL
from data_pipeline.sim_repository import clear_model_paused, get_all_model_pause_states, get_model_recommendation_status

HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
AUTH_USER = os.getenv("DASHBOARD_USER", "todd")
AUTH_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
# The second gate in front of every real-money control. No default: a value
# committed here is a value anyone with the repo knows, and it was the live gate
# in production while the env var went unset. Unset now means locked, not open.
LIVE_TRADING_PASSWORD = os.getenv("LIVE_TRADING_PASSWORD", "")
# A read-only credential for an off-box monitor. It unlocks exactly the three
# status endpoints below, over GET only, and nothing else: no pages, no table
# browsing, no POST, so it can never trade or change a cap. Kept separate from
# DASHBOARD_PASSWORD precisely so a monitor that has to store a secret stores
# the least valuable one available.
MONITOR_TOKEN = os.getenv("MONITOR_TOKEN")
MONITOR_PATHS = frozenset({"/health", "/live_metrics", "/sim_metrics"})
# What each strategy actually is, written from the code that runs it
# (simulated_trading_engine.py, sim_config.py, binary_theory.py,
# modeling_features.py). Every claim here is checkable against those files;
# nothing is inferred. Keep this in sync when the engine changes - a dossier
# that drifts from the engine is worse than no dossier.
# One tick of the engine, in the order the code actually runs it
# (simulated_trading_engine.process_model_tick). Exit is evaluated before
# entry so a stale position never blocks a fresh read.
SHARED_TICK_PSEUDO = """EVERY MINUTE, at second :10

  row  <- newest model_features_1m row for the live 15-minute contract
  if row has no settled target price:   wait for the next minute
  x    <- build_feature_vector(row)                    # 22 columns

  FOR EACH strategy:

      p    <- strategy.probability(x, row)             # this is what differs
      ask  <- row.yes_ask_dollars
      edge <- p - ask
      tte  <- row.time_to_expiry_sec

      # --- exit is decided first
      IF holding a position:
          IF the contract rotated            -> close at that contract's last bid
          ELIF tte <= 60s                    -> force close at $0.99
          ELIF strategy holds to settlement  -> hold, whatever p says
          ELIF p < 0.55 OR edge <= threshold -> close at the current bid

      # --- risk gate, before any new risk is added
      IF drawdown from peak <= -30%:
          halt this strategy and skip entry        # stays halted until cleared by hand

      # --- entry
      IF no position AND not halted AND tte > 60s AND p >= 0.55 AND edge > threshold:
          equity  <- 100 + realised + unrealised
          cap     <- equity x max_position_fraction
          qty     <- clamp( floor((edge / 0.03) x 10), 1, 10 )
          qty     <- min( qty, floor(cap / ask) )      # never more than the book can fund
          IF qty > 0:  buy qty at the ask"""

# Live sizing is not the same arithmetic as paper sizing, which is worth
# knowing before promoting anything: live has no MAX_QTY, only a cost cap.
LIVE_SIZING_PSEUDO = """LIVE, the same strategy sizes differently:

  qty_max <- floor(max_trade_cost / ask)        # $2 / $0.50 = 4 contracts
  qty     <- clamp( floor((edge / 0.03) x qty_max), 1, qty_max )

  # no MAX_QTY ceiling and no cash check on this path - the cost cap is the
  # only bound, so a $0.05 ask buys 40 contracts for the same $2."""


def _eq(*rows):
    return '<math display="block">' + "".join(rows) + "</math>"


FRAC = '<mfrac><mrow>{0}</mrow><mrow>{1}</mrow></mfrac>'
EDGE_MATH = _eq(
    "<mi>edge</mi><mo>=</mo><mi>p</mi><mo>&#8722;</mo><mi>ask</mi>"
)

SHARED_LABEL = (
    "Every fitted model is trained on the same question, and it is a tradeable one rather than a "
    "price-forecasting one: given this minute's order book, could you buy at the current ask and "
    "sell into the bid one minute later for more than you paid? The label is literally "
    "1 if next_minute_yes_bid > this_minute_yes_ask else 0, built in build_supervised(). Rows are "
    "dropped across a ticker rotation, so a label never spans two different contracts."
)
SHARED_LIFECYCLE = [
    ("Fit once, then frozen",
     "Models are fitted a single time on the in-sample window (at least 48 hours, "
     "MIN_INSAMPLE_HOURS) and then never refitted. Everything after the live cutoff is genuinely "
     "out of sample, which is why out-of-sample is the only honest read of a book."),
    ("Entry",
     "A position opens only when the model's probability clears PRED_THRESHOLD (0.55) and its "
     "edge clears that strategy's own edge threshold. Edge is probability minus the current ask, "
     "so it is the model's claim about how mispriced the contract is right now."),
    ("Sizing",
     "Quantity scales with edge, capped at MAX_QTY (10 contracts), by what the book's cash can "
     "afford, and by max_position_fraction of that book's own equity."),
    ("Exit",
     "Default exit is signal decay: the position closes when probability falls back below the "
     "threshold. Every strategy also force-closes inside the last 60 seconds before expiry "
     "(NEAR_EXPIRY_SEC) at FORCE_CLOSE_NEAR_EXPIRY_PRICE, and closes on ticker rotation."),
    ("Self-halt",
     "A book that draws down past max_drawdown_pct (30%) from its own peak pauses itself and "
     "stays paused until you clear it by hand. Drawdown is read from sim_equity_1m so the gate "
     "behaves identically whether the engine is ticking live or replaying history."),
]
STRATEGY_DOSSIER: Dict[str, Dict] = {
    "naive_logistic_baseline": {
        "formula_caption": 'Logistic response on the reduced 13-column subset',
        "formula": '<math display="block"><mi>p</mi><mo>=</mo><mi>&#963;</mi><mo>(</mo><mi>w</mi><mo>&#183;</mo><msub><mi>z</mi><mn>13</mn></msub><mo>+</mo><mi>b</mi><mo>)</mo><mo>=</mo><mfrac><mn>1</mn><mrow><mn>1</mn><mo>+</mo><msup><mi>e</mi><mrow><mo>&#8722;</mo><mo>(</mo><mi>w</mi><mo>&#183;</mo><msub><mi>z</mi><mn>13</mn></msub><mo>+</mo><mi>b</mi><mo>)</mo></mrow></msup></mrow></mfrac></math>',
        "pseudo": """z13 <- StandardScaler( x restricted to the 13 baseline columns )
p   <- sigmoid( w . z13 + b )

# L1 penalty, C = 0.5 (lambda = 2.0), class_weight = balanced,
# max_iter = 1000, random_state = 42. No interaction terms are in z13,
# which is the whole point: this is the control.""",
        "kind": "Fitted - linear",
        "thesis": (
            "A deliberately weak benchmark. It exists so the richer models have something honest "
            "to beat: if a random forest on the full feature set cannot outperform an L1 logistic "
            "regression on a reduced linear subset, the extra machinery is not earning its keep."
        ),
        "reads": (
            "A reduced 13-column subset with no interaction terms (BASELINE_FEATURE_COLS): both "
            "sides of the book and the spread, mid price, order-book imbalance, one- and "
            "three-minute mid returns, trade count and quote-change count over the last 60 "
            "seconds, time to expiry, one- and three-minute Coinbase BTC returns, and moneyness "
            "as a percentage."
        ),
        "decides": (
            "StandardScaler into LogisticRegression with L1 penalty, C=0.5 (lambda=2.0), "
            "class_weight='balanced', max_iter=1000, random_state=42. Opens on probability >= 0.55 "
            "with edge > 0.01."
        ),
        "caveat": (
            "It is the control, not a candidate. Its long negative record is informative rather "
            "than disappointing - it is what an unsophisticated reading of this book earns."
        ),
    },
    "logistic": {
        "formula_caption": 'Same response, all 22 columns including the interaction terms',
        "formula": '<math display="block"><mi>p</mi><mo>=</mo><mi>&#963;</mi><mo>(</mo><mi>w</mi><mo>&#183;</mo><mi>z</mi><mo>+</mo><mi>b</mi><mo>)</mo><mo>,</mo><mspace width="0.6em"/><mi>z</mi><mo>=</mo><mtext>StandardScaler</mtext><mo>(</mo><mi>x</mi><mo>)</mo></math>',
        "pseudo": """z <- StandardScaler( x )          # all 22 columns
p <- sigmoid( w . z + b )

# Identical pipeline and hyper-parameters to the baseline. The only
# difference is the width of the matrix, which isolates one question:
# how much of any edge is the feature engineering rather than capacity?""",
        "kind": "Fitted - linear",
        "thesis": (
            "The same linear machinery as the baseline, but allowed to see the engineered "
            "interaction terms. It isolates one question: how much of any edge comes from the "
            "feature engineering rather than from model capacity?"
        ),
        "reads": (
            "The full feature set (FEATURE_COLS), which adds to the baseline's columns: traded "
            "volume and VWAP over the last 60 seconds, five-minute Coinbase return and realised "
            "volatility, absolute moneyness, volatility-scaled moneyness, and four interaction "
            "terms - moneyness against sqrt(time to expiry), against order-book imbalance, and "
            "against quote-change count."
        ),
        "decides": (
            "Identical pipeline to the baseline (StandardScaler, L1 logistic, C=0.5, balanced "
            "classes, seed 42) on the wider matrix. Opens on probability >= 0.55 with edge > 0.01."
        ),
        "caveat": (
            "Shares the baseline's ceiling: a linear decision boundary on a book whose structure "
            "is unlikely to be linear."
        ),
    },
    "random_forest": {
        "formula_caption": 'Mean vote across the forest',
        "formula": '<math display="block"><mi>p</mi><mo>=</mo><mfrac><mn>1</mn><mi>N</mi></mfrac><munderover><mo>&#8721;</mo><mrow><mi>t</mi><mo>=</mo><mn>1</mn></mrow><mi>N</mi></munderover><msub><mi>tree</mi><mi>t</mi></msub><mo>(</mo><mi>x</mi><mo>)</mo><mo>,</mo><mspace width="0.6em"/><mi>N</mi><mo>=</mo><mn>400</mn></math>',
        "pseudo": """p <- mean over 400 trees of tree_t(x)

# max_depth 8, min_samples_leaf 20, min_samples_split 50,
# max_features sqrt, class_weight balanced_subsample, seed 42.
#
# IF training rows < 1000:
#     fall back to 120 trees, depth 5, leaf 5, split 20
#     and record which regime was used (rf_regime).""",
        "kind": "Fitted - non-linear",
        "thesis": (
            "Allow non-linear structure and interactions the linear models cannot express, on the "
            "same tradeable label. This is the capacity arm of the comparison."
        ),
        "reads": "The full feature set (FEATURE_COLS), the same matrix the logistic model sees.",
        "decides": (
            "RandomForestClassifier with 400 trees, max_depth 8, min_samples_leaf 20, "
            "min_samples_split 50, max_features='sqrt', class_weight='balanced_subsample', "
            "random_state=42. When fewer than 1000 training rows are available it falls back to a "
            "smaller configuration (120 trees, depth 5) and records which regime it used. Opens on "
            "probability >= 0.55 with edge > 0.01."
        ),
        "caveat": (
            "Its overall record is negative, but that record is what motivated the edge-magnitude "
            "research: the losses are not uniform across trades. See random_forest_high_conviction."
        ),
    },
    "random_forest_high_conviction": {
        "formula_caption": 'No probability of its own - only the entry bar moves',
        "formula": '<math display="block"><msub><mi>p</mi><mtext>hc</mtext></msub><mo>=</mo><msub><mi>p</mi><mtext>rf</mtext></msub><mo>,</mo><mspace width="1.2em"/><mtext>open&#160;iff</mtext><mspace width="0.4em"/><mi>edge</mi><mo>&#62;</mo><mn>0.17</mn></math>',
        "pseudo": """p <- random_forest.p              # the same number, not a second model

# The ONLY difference between the two books:
#     random_forest                  opens when edge > 0.01
#     random_forest_high_conviction  opens when edge > 0.17
#
# Everything else - features, trees, exits, sizing - is identical.""",
        "kind": "Filter - not a separate model",
        "thesis": (
            "Not a new model at all. It reuses random_forest's probability output unchanged and "
            "differs only in how sure it insists on being before it trades. It exists to test one "
            "research finding forward, on data that did not produce it."
        ),
        "reads": "Nothing of its own - it is random_forest's probability, aliased.",
        "decides": (
            "Opens only when edge > 0.17 (HIGH_CONVICTION_EDGE_THRESHOLD) instead of 0.01. Same "
            "0.55 probability floor, same exits, same sizing."
        ),
        "caveat": (
            "The finding behind it: among random_forest's trades from March-April 2026, PnL rose "
            "monotonically with edge at entry, and the top quintile (edge above roughly 0.167) was "
            "the only clearly profitable one, at about +$0.062 per trade against -$0.01 to -$0.15 "
            "for the rest. That came from a limited window which visibly decayed inside itself "
            "(March about +$0.125 per trade, April about +$0.006) and had no out-of-sample "
            "evidence. It is explicitly NOT treated as validated. This book is the forward test."
        ),
    },
    "binary_theory_edge": {
        "formula_caption": 'Closed-form digital-option probability. Nothing is fitted.',
        "formula": '<math display="block"><mi>P</mi><mo>(</mo><mtext>YES</mtext><mo>)</mo><mo>=</mo><mi>&#934;</mi><mo>(</mo><mfrac><mrow><mi>ln</mi><mo>(</mo><msub><mi>S</mi><mn>0</mn></msub><mo>/</mo><mi>K</mi><mo>)</mo></mrow><mrow><mi>&#963;</mi><msqrt><mi>T</mi></msqrt></mrow></mfrac><mo>)</mo></math>',
        "pseudo": """S <- spot BTC                      K <- the contract's strike
T <- time_to_expiry as a fraction of a year
sigma <- realised volatility estimate

d <- ln(S / K) / (sigma * sqrt(T))
p <- Phi(d)                        # standard normal CDF

# Drift is deliberately zero. Short-horizon crypto drift is not reliably
# predictable, so a driftless random walk is the honest null.
#
# This is the same d2 term Black-Scholes uses for a cash-or-nothing
# digital, MINUS the risk-neutral drift correction (-0.5*sigma^2*T).
# That makes it the physical-measure probability of the outcome, not a
# risk-neutral price - which is exactly what you want to compare against
# a market quote.
#
# Exit differs from every other book: hold to settlement, never close
# on signal decay.""",
        "kind": "Closed form - nothing fitted",
        "thesis": (
            "Price the contract from options theory instead of learning it from history, then "
            "trade only the largest disagreements with the market. Zero parameters are fitted to "
            "this data, so there is nothing here to overfit."
        ),
        "reads": (
            "Spot BTC, the contract's strike, time remaining, and a volatility estimate. That is "
            "all - no order-book microstructure, no learned weights."
        ),
        "decides": (
            "Treats BTC as a driftless geometric Brownian motion over the contract's remaining "
            "life and takes the closed-form probability P(YES) = Phi( ln(S0/K) / (sigma * sqrt(T)) ). "
            "That is the same d2 term Black-Scholes uses for a cash-or-nothing digital, minus the "
            "risk-neutral drift correction, which makes it a physical-measure probability of the "
            "outcome rather than a risk-neutral price. Drift is deliberately set to zero: "
            "short-horizon crypto drift is not reliably predictable, so a random walk is the "
            "honest null. Opens only when edge > 0.15."
        ),
        "caveat": (
            "Two things to hold onto. First, its exit rule is fundamentally different from every "
            "other book here: it holds to settlement and never closes on signal decay - only "
            "near-expiry force-close or ticker rotation ends a position. Second, it is known to be "
            "systematically overconfident: predicted probabilities run well above realised rates "
            "in the middle deciles, even though standalone AUC was 0.858 with zero fitting. Its "
            "validation window was only about seven to eight weeks."
        ),
    },
}


# Authored rather than borrowed from a glyph set, so it carries one stroke
# weight with the rest of the page and inherits the status line's colour.
STATUS_MARK_SVG = (
    '<svg class="mark mark-calm" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="8.4"/><path d="m8.3 12.2 2.6 2.6 4.8-5.2"/></svg>'
    '<svg class="mark mark-needs" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 4.2 21.3 20H2.7z"/><path d="M12 10.2v4.1"/><path d="M12 17.1v.1"/></svg>'
)

LIVE_COOKIE_NAME = "live_gate"


def live_cookie_token(password: str) -> str:
    """The unlock cookie's value: derived from the password, so it cannot be
    forged without knowing it, and rotating the password logs every browser out.
    The old cookie was the literal "ok", which anyone past basic auth could set."""
    return hmac.new(password.encode("utf-8"), b"live_gate.v1", hashlib.sha256).hexdigest()


def live_password_ok(candidate: str) -> bool:
    """Constant-time check; always False when no password is configured."""
    return bool(LIVE_TRADING_PASSWORD) and bool(candidate) and secrets.compare_digest(
        candidate.encode("utf-8"), LIVE_TRADING_PASSWORD.encode("utf-8")
    )
PAGE_SIZE = 100
TABLES = [
    "markets",
    "market_candles",
    "forward_quotes",
    "coinbase_ticks",
    "trade_quote_features_1m",
    "ws_quote_change_1m",
    "model_features_1m",
    "sim_model_predictions_1m",
    "sim_positions",
    "sim_trades",
    "sim_equity_1m",
    "sim_portfolio_20s",
    "model_research_runs",
    "model_research_feature_importance",
    "live_settings",
    "live_orders",
    "live_positions",
    "live_trades",
    "live_portfolio_20s",
    "live_model_state",
    "collector_state",
]
API_TABLES = [
    "model_features_1m",
    "trade_quote_features_1m",
    "forward_quotes",
    "coinbase_ticks",
    "sim_model_predictions_1m",
    "sim_trades",
    "sim_portfolio_20s",
    "model_research_runs",
    "model_research_feature_importance",
]
API_TIME_COLUMN = {
    "model_features_1m": "snapshot_minute_utc",
    "trade_quote_features_1m": "snapshot_minute_utc",
    "forward_quotes": "snapshot_time_utc",
    "coinbase_ticks": "snapshot_time_utc",
    "sim_model_predictions_1m": "snapshot_minute_utc",
    "sim_trades": "opened_at_utc",
    "sim_portfolio_20s": "snapshot_time_utc",
    "model_research_runs": "created_at_utc",
    "model_research_feature_importance": "created_at_utc",
}
API_MAX_LIMIT = 5000


def query_rows(table: str, page: int):
    offset = (page - 1) * PAGE_SIZE
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
        total = cur.fetchone()["c"]
        cur.execute(f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT %s OFFSET %s", (PAGE_SIZE, offset))
        rows = cur.fetchall()
    conn.close()
    return total, rows


def _table_columns(table: str) -> List[str]:
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM {table}")
        cols = [r["Field"] for r in cur.fetchall()]
    conn.close()
    return cols


def query_api_rows(
    table: str,
    offset: int = 0,
    limit: int = 1000,
    start: Optional[str] = None,
    end: Optional[str] = None,
    columns: Optional[List[str]] = None,
):
    if table not in API_TABLES:
        raise ValueError("invalid table")
    safe_limit = max(1, min(API_MAX_LIMIT, int(limit)))
    safe_offset = max(0, int(offset))
    known_cols = _table_columns(table)
    selected_cols = known_cols
    if columns:
        cset = []
        for c in columns:
            c = str(c).strip()
            if c in known_cols:
                cset.append(c)
        if cset:
            selected_cols = cset
    select_sql = ", ".join([f"`{c}`" for c in selected_cols])
    where_parts = []
    params: List[Any] = []
    tcol = API_TIME_COLUMN.get(table)
    if tcol and start:
        where_parts.append(f"`{tcol}` >= %s")
        params.append(start)
    if tcol and end:
        where_parts.append(f"`{tcol}` <= %s")
        params.append(end)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {table} {where_sql}", tuple(params))
        total = int(cur.fetchone()["c"])
        cur.execute(
            f"SELECT {select_sql} FROM {table} {where_sql} ORDER BY 1 ASC LIMIT %s OFFSET %s",
            tuple(params + [safe_limit, safe_offset]),
        )
        rows = cur.fetchall()
    conn.close()
    return {
        "table": table,
        "offset": safe_offset,
        "limit": safe_limit,
        "total": total,
        "returned": len(rows),
        "done": (safe_offset + len(rows)) >= total,
        "next_offset": safe_offset + len(rows),
        "rows": rows,
        "time_column": tcol,
        "columns": selected_cols,
    }


def _parse_window_hours(qs, default: int) -> int:
    try:
        return int(qs.get("window_hours", [str(default)])[0])
    except (ValueError, TypeError):
        return default


_TABLE_COUNTS_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_TABLE_COUNTS_LOCK = threading.Lock()
_TABLE_COUNTS_TTL_SECONDS = 30


def table_counts():
    """Row counts for the dashboard's table cards. Uses information_schema's
    TABLE_ROWS estimate rather than SELECT COUNT(*) per table - an exact count
    on InnoDB requires a full index scan, and doing that for ~20 tables
    (several hundred thousand rows each after 6+ months of collection) on
    every cache miss was slow enough to time out requests under load. This is
    a display metric, not a trading input, so an estimate is the right
    tradeoff - see the 2026-09-13 connection-exhaustion incident in PLAN.md."""
    now = time.time()
    with _TABLE_COUNTS_LOCK:
        cached = _TABLE_COUNTS_CACHE["data"]
        if cached is not None and (now - _TABLE_COUNTS_CACHE["ts"]) < _TABLE_COUNTS_TTL_SECONDS:
            return cached
    conn = get_db_conn()
    out = {t: 0 for t in TABLES}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN %s",
            (tuple(TABLES),),
        )
        for r in cur.fetchall():
            out[r["TABLE_NAME"]] = int(r["TABLE_ROWS"] or 0)
    conn.close()
    with _TABLE_COUNTS_LOCK:
        _TABLE_COUNTS_CACHE["data"] = out
        _TABLE_COUNTS_CACHE["ts"] = now
    return out


def latest_forward_status():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_time_utc, market_ticker, status, event_ticker
            FROM forward_quotes
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    conn.close()
    return row


def forward_feed_health(window_minutes: int = 120):
    conn = get_db_conn()
    out = {
        "window_minutes": window_minutes,
        "rows_total": 0,
        "rows_na": 0,
        "na_rate_pct": 0.0,
        "rows_real": 0,
        "gaps_missing_slots": 0,
        "misaligned_rows": 0,
        "last_snapshot_time": None,
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM forward_quotes
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
            """,
            (window_minutes,),
        )
        out["rows_total"] = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM forward_quotes
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
              AND market_ticker='N/A'
            """,
            (window_minutes,),
        )
        out["rows_na"] = cur.fetchone()["c"]
        out["rows_real"] = max(0, out["rows_total"] - out["rows_na"])
        if out["rows_total"] > 0:
            out["na_rate_pct"] = round((out["rows_na"] / out["rows_total"]) * 100, 2)

        # 20-second alignment check: allowed seconds are 0,20,40.
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM forward_quotes
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
              AND MOD(SECOND(snapshot_time_utc), 20) <> 0
            """,
            (window_minutes,),
        )
        out["misaligned_rows"] = cur.fetchone()["c"]

        cur.execute(
            """
            SELECT snapshot_time_utc
            FROM forward_quotes
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s MINUTE)
            ORDER BY snapshot_time_utc ASC
            """,
            (window_minutes,),
        )
        rows = cur.fetchall()
        times = [r["snapshot_time_utc"] for r in rows]
        if times:
            out["last_snapshot_time"] = str(times[-1])
            # Expect one row per 20-second slot now. To avoid false gap inflation from
            # legacy minute-only data, start gap analysis at first observed :20/:40 mark.
            start_time = times[0]
            for t in times:
                if t.second in (20, 40):
                    start_time = t
                    break
            slot_times = [t for t in times if t >= start_time]
            unique_slots = set(slot_times)
            span_seconds = int((slot_times[-1] - slot_times[0]).total_seconds())
            expected_slots = (span_seconds // 20) + 1
            out["gaps_missing_slots"] = max(0, expected_slots - len(unique_slots))

    conn.close()
    return out


def latest_model_guard():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_minute_utc, market_ticker, model_eligible, guard_status, guard_reasons_json
            FROM model_features_1m
            WHERE market_ticker LIKE 'KXBTC15M-%' OR market_ticker IS NULL
            ORDER BY snapshot_minute_utc DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    conn.close()
    return row


def sim_health_summary():
    conn = get_db_conn()
    out = {"open_positions": 0, "models": []}
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM sim_positions")
        out["open_positions"] = int(cur.fetchone()["c"])
        pause_states = get_all_model_pause_states(cur)
        cur.execute(
            """
            SELECT model_name, COUNT(*) closed_trades, COALESCE(SUM(pnl_dollars),0) total_pnl
            FROM sim_trades
            WHERE status='closed'
            GROUP BY model_name
            ORDER BY model_name
            """
        )
        for r in cur.fetchall():
            pause = pause_states.get(r["model_name"])
            out["models"].append(
                {
                    "model_name": r["model_name"],
                    "closed_trades": int(r["closed_trades"] or 0),
                    "total_pnl": float(r["total_pnl"] or 0),
                    "paused": pause is not None,
                    "paused_reason": pause.get("paused_reason") if pause else None,
                }
            )
    conn.close()
    return out


def _bucket_key(p: float) -> str:
    lo = max(0.0, min(0.9, (int(p * 10) / 10.0)))
    hi = lo + 0.1
    return f"{lo:.1f}-{hi:.1f}"


_METRICS_CACHE: Dict[Any, Any] = {}
_METRICS_CACHE_LOCK = threading.Lock()
_METRICS_CACHE_TTL_SECONDS = 25


def invalidate_metrics_cache() -> None:
    """Every mutating POST clears this. Without it a toggle or a caps save
    lands in the database and then the very next read - including the one the
    button itself triggers - serves the pre-write payload for up to
    _METRICS_CACHE_TTL_SECONDS, so the row keeps reading "Off" and the save
    looks like it did nothing."""
    with _METRICS_CACHE_LOCK:
        _METRICS_CACHE.clear()


def _cached(cache_key, ttl_seconds, compute_fn):
    now = time.time()
    with _METRICS_CACHE_LOCK:
        entry = _METRICS_CACHE.get(cache_key)
        if entry is not None and (now - entry[1]) < ttl_seconds:
            return entry[0]
    data = compute_fn()
    with _METRICS_CACHE_LOCK:
        _METRICS_CACHE[cache_key] = (data, now)
    return data


# How often each background writer is expected to write. A figure whose writer
# has stopped must say so itself rather than render as current: that failure has
# already happened twice here, once for 13 days.
WRITER_CADENCE_SECONDS: Dict[str, int] = {
    "sim_portfolio_20s": 20,
    "sim_equity_1m": 60,
    "sim_trades": 900,
    "live_portfolio_20s": 20,
    "live_engine": 60,
    "forward_quotes": 20,
    "model_features_1m": 60,
}
STALE_CADENCE_MULTIPLE = 6


def _writer_freshness(cur, specs: Dict[str, str]) -> Dict[str, Dict]:
    """Age of each named writer's newest row, measured against the database
    clock so a skewed server cannot invent freshness."""
    out: Dict[str, Dict] = {}
    for name, sql in specs.items():
        expect = WRITER_CADENCE_SECONDS.get(name, 60)
        try:
            cur.execute(sql)
            row = cur.fetchone() or {}
            age = row.get("age_sec")
            last = row.get("last_utc")
            out[name] = {
                "last_utc": str(last) if last is not None else None,
                "age_sec": float(age) if age is not None else None,
                "expect_sec": expect,
            }
        except Exception:
            out[name] = {"last_utc": None, "age_sec": None, "expect_sec": expect}
    return out


def pipeline_writer_freshness() -> Dict[str, Dict]:
    """Ages of the ingestion writers, so the Data Pipeline tab can state its own
    staleness instead of being the one surface that cannot. Its whole job is
    confirming the pipeline is alive."""
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            return _writer_freshness(
                cur,
                {
                    "forward_quotes": _freshness_sql("forward_quotes", "snapshot_time_utc"),
                    "model_features_1m": _freshness_sql("model_features_1m", "snapshot_minute_utc"),
                },
            )
    finally:
        conn.close()


def _freshness_sql(table: str, column: str, where: str = "") -> str:
    clause = f" WHERE {where}" if where else ""
    return (
        f"SELECT MAX({column}) last_utc, "
        f"TIMESTAMPDIFF(SECOND, MAX({column}), UTC_TIMESTAMP()) age_sec FROM {table}{clause}"
    )


def sim_metrics(window_hours: int = 6):
    return _cached(("sim_metrics", window_hours), _METRICS_CACHE_TTL_SECONDS, lambda: _sim_metrics_uncached(window_hours))


def build_scorecards(
    score_map: Dict[str, Dict],
    open_positions: List[Dict],
    pause_states: Dict[str, Dict],
    recommendation_fn,
) -> List[Dict]:
    """Portfolio Manager cards: one row per model, equity reconciled with PnL.

    Equity is derived from the same closed-trade aggregates that produce
    total_pnl (plus unrealized on any open position) rather than read off the
    latest sim_portfolio_20s snapshot. That snapshot is written by a separate
    20s process which is skipped entirely while a full sim recompute runs and
    can be down independently of this server, so its last row goes stale while
    total_pnl keeps moving - which showed up as a card reporting an equity that
    contradicted the PnL printed directly underneath it. Deriving it here also
    means a model that has traded but has no portfolio snapshot yet still gets
    a card instead of silently disappearing from the panel.
    """
    unrealized_by_model: Dict[str, float] = {}
    position_value_by_model: Dict[str, float] = {}
    for pos in open_positions:
        m = pos["model_name"]
        qty = int(pos["qty_contracts"])
        unrealized_by_model[m] = unrealized_by_model.get(m, 0.0) + float(pos["unrealized_pnl"])
        position_value_by_model[m] = position_value_by_model.get(m, 0.0) + float(pos["mark_bid"]) * qty

    scorecards: List[Dict] = []
    for m in sorted(set(score_map) | set(unrealized_by_model)):
        pause = pause_states.get(m)
        sc = dict(
            score_map.get(
                m,
                {
                    "model_name": m, "closed_trades": 0, "total_pnl": 0.0, "avg_trade_pnl": 0.0,
                    "win_rate": None,
                    "paused": pause is not None,
                    "paused_reason": pause.get("paused_reason") if pause else None,
                },
            )
        )
        unrealized = unrealized_by_model.get(m, 0.0)
        sc["unrealized_pnl"] = unrealized
        sc["equity"] = STARTING_CAPITAL + float(sc["total_pnl"]) + unrealized
        sc["return_pct"] = ((sc["equity"] / STARTING_CAPITAL) - 1.0) * 100.0
        sc["position_value"] = position_value_by_model.get(m, 0.0)
        sc["recommendation"] = recommendation_fn(m, pause is not None)
        scorecards.append(sc)
    return scorecards


def _sim_metrics_uncached(window_hours: int = 6):
    conn = get_db_conn()
    out = {
        "starting_capital": STARTING_CAPITAL,
        "live_cutoff_utc": None,
        "recompute_in_progress": False,
        "equity_series_20s": {},
        "equity_series_1m": {},
        "stack_series_20s": {},
        "drawdown_series_20s": {},
        "scorecards": [],
        "open_positions": [],
        "recent_trades": [],
        "calibration": [],
        "execution_quality": [],
        "in_sample": [],
        "out_of_sample": [],
    }
    with conn.cursor() as cur:
        cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_live_cutoff_utc' LIMIT 1")
        cutoff_row = cur.fetchone()
        if cutoff_row:
            sv = cutoff_row["state_value"]
            try:
                j = sv if isinstance(sv, dict) else json.loads(sv)
                out["live_cutoff_utc"] = j.get("cutoff_utc")
            except Exception:
                out["live_cutoff_utc"] = str(sv)

        cur.execute("SELECT state_value FROM collector_state WHERE state_key='sim_recompute_in_progress' LIMIT 1")
        prog_row = cur.fetchone()
        if prog_row:
            sv = prog_row["state_value"]
            try:
                j = sv if isinstance(sv, dict) else json.loads(sv)
                out["recompute_in_progress"] = bool(j.get("in_progress"))
            except Exception:
                out["recompute_in_progress"] = False

        cur.execute(
            """
            SELECT snapshot_time_utc, model_name, cash_dollars, position_value_dollars, equity_dollars, drawdown_dollars
            FROM sim_portfolio_20s
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s HOUR)
            ORDER BY snapshot_time_utc ASC
            """,
            (window_hours,),
        )
        for r in cur.fetchall():
            m = r["model_name"]
            ts = str(r["snapshot_time_utc"])
            out["equity_series_20s"].setdefault(m, []).append({"t": ts, "equity": float(r["equity_dollars"])})
            out["stack_series_20s"].setdefault(m, []).append(
                {"t": ts, "cash": float(r["cash_dollars"]), "position": float(r["position_value_dollars"])}
            )
            out["drawdown_series_20s"].setdefault(m, []).append({"t": ts, "drawdown": float(r["drawdown_dollars"])})

        cur.execute(
            """
            SELECT snapshot_minute_utc, model_name, cumulative_pnl_dollars, raw_json
            FROM sim_equity_1m
            WHERE snapshot_minute_utc >= (UTC_TIMESTAMP() - INTERVAL %s HOUR)
            ORDER BY snapshot_minute_utc ASC
            """,
            (window_hours,),
        )
        for r in cur.fetchall():
            m = r["model_name"]
            ts = str(r["snapshot_minute_utc"])
            eq = 100.0 + float(r["cumulative_pnl_dollars"] or 0.0)
            try:
                raw_blob = r["raw_json"]
                if isinstance(raw_blob, dict):
                    raw = raw_blob
                elif isinstance(raw_blob, str):
                    try:
                        raw = json.loads(raw_blob or "{}")
                    except Exception:
                        raw = ast.literal_eval(raw_blob) if raw_blob else {}
                else:
                    raw = {}
                if isinstance(raw, dict):
                    # Prefer explicit equity when present; otherwise reconstruct
                    # from cumulative + unrealized to avoid flat-line fallback.
                    if raw.get("equity_dollars") is not None:
                        eq = float(raw["equity_dollars"])
                    elif raw.get("unrealized_pnl_dollars") is not None:
                        eq = 100.0 + float(r["cumulative_pnl_dollars"] or 0.0) + float(raw["unrealized_pnl_dollars"])
            except Exception:
                pass
            out["equity_series_1m"].setdefault(m, []).append({"t": ts, "equity": eq})

        pause_states = get_all_model_pause_states(cur)

        cur.execute(
            """
            SELECT model_name, COUNT(*) closed_trades,
                   COALESCE(SUM(pnl_dollars),0) total_pnl,
                   COALESCE(AVG(pnl_dollars),0) avg_pnl,
                   COALESCE(SUM(pnl_dollars > 0),0) wins
            FROM sim_trades
            WHERE status='closed'
            GROUP BY model_name
            """
        )
        score_map = {}
        for r in cur.fetchall():
            closed = int(r["closed_trades"] or 0)
            wins = int(r["wins"] or 0)
            pause = pause_states.get(r["model_name"])
            score_map[r["model_name"]] = {
                "model_name": r["model_name"],
                "closed_trades": closed,
                "total_pnl": float(r["total_pnl"] or 0),
                "avg_trade_pnl": float(r["avg_pnl"] or 0),
                "win_rate": (wins / closed) if closed > 0 else None,
                "paused": pause is not None,
                "paused_reason": pause.get("paused_reason") if pause else None,
            }

        cur.execute("SELECT DISTINCT market_ticker FROM sim_positions")
        open_tickers = [r["market_ticker"] for r in cur.fetchall()]
        if open_tickers:
            placeholders = ",".join(["%s"] * len(open_tickers))
            cur.execute(
                f"""
                SELECT p.model_name, p.market_ticker, p.qty_contracts, p.entry_price_dollars, p.opened_at_utc,
                       fq.yes_bid_dollars, fq.yes_ask_dollars
                FROM sim_positions p
                LEFT JOIN (
                  SELECT f1.*
                  FROM forward_quotes f1
                  JOIN (
                    SELECT market_ticker, MAX(snapshot_time_utc) mx
                    FROM forward_quotes
                    WHERE market_ticker IN ({placeholders})
                    GROUP BY market_ticker
                  ) f2 ON f2.market_ticker=f1.market_ticker AND f2.mx=f1.snapshot_time_utc
                ) fq ON fq.market_ticker=p.market_ticker
                ORDER BY p.opened_at_utc DESC
                """,
                tuple(open_tickers),
            )
        else:
            cur.execute("SELECT NULL LIMIT 0")
        for r in cur.fetchall():
            entry = float(r["entry_price_dollars"])
            qty = int(r["qty_contracts"])
            mark = float(r["yes_bid_dollars"]) if r["yes_bid_dollars"] is not None else entry
            out["open_positions"].append(
                {
                    "model_name": r["model_name"],
                    "market_ticker": r["market_ticker"],
                    "qty_contracts": qty,
                    "entry_price": entry,
                    "mark_bid": mark,
                    "unrealized_pnl": (mark - entry) * qty,
                    "opened_at_utc": str(r["opened_at_utc"]),
                }
            )

        out["scorecards"] = build_scorecards(
            score_map,
            out["open_positions"],
            pause_states,
            lambda m, paused: get_model_recommendation_status(cur, m, paused),
        )

        out["writers"] = _writer_freshness(
            cur,
            {
                "sim_portfolio_20s": _freshness_sql("sim_portfolio_20s", "snapshot_time_utc"),
                "sim_equity_1m": _freshness_sql("sim_equity_1m", "snapshot_minute_utc"),
                "sim_trades": _freshness_sql("sim_trades", "closed_at_utc", "status='closed'"),
            },
        )
        cur.execute("SELECT UTC_TIMESTAMP() now_utc")
        out["generated_at_utc"] = str((cur.fetchone() or {}).get("now_utc") or "")

        cur.execute(
            """
            SELECT id, model_name, market_ticker, opened_at_utc, closed_at_utc, qty_contracts,
                   entry_price_dollars, exit_price_dollars, pnl_dollars, status, raw_json
            FROM sim_trades
            ORDER BY id DESC
            LIMIT 60
            """
        )
        trades = cur.fetchall()
        for r in trades:
            raw = r.get("raw_json") or {}
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            exp_entry = None
            if raw.get("prob_yes") is not None and raw.get("edge") is not None:
                exp_entry = float(raw["prob_yes"]) - float(raw["edge"])
            realized_entry = float(r["entry_price_dollars"])
            slippage = None if exp_entry is None else (realized_entry - exp_entry)
            out["recent_trades"].append(
                {
                    "id": int(r["id"]),
                    "model_name": r["model_name"],
                    "market_ticker": r["market_ticker"],
                    "opened_at_utc": str(r["opened_at_utc"]),
                    "closed_at_utc": str(r["closed_at_utc"]) if r["closed_at_utc"] else None,
                    "qty_contracts": int(r["qty_contracts"]),
                    "entry_price": realized_entry,
                    "exit_price": float(r["exit_price_dollars"]) if r["exit_price_dollars"] is not None else None,
                    "pnl": float(r["pnl_dollars"]) if r["pnl_dollars"] is not None else None,
                    "status": r["status"],
                    "fill_mode": (raw.get("fill") or {}).get("mode"),
                    "expected_entry": exp_entry,
                    "slippage": slippage,
                }
            )

        cur.execute(
            """
            SELECT p.model_name, p.prob_yes, m1.market_ticker,
                   m1.mid_dollars AS mid_now, m2.mid_dollars AS mid_next
            FROM sim_model_predictions_1m p
            JOIN model_features_1m m1 ON m1.snapshot_minute_utc=p.snapshot_minute_utc AND m1.market_ticker=p.market_ticker
            JOIN model_features_1m m2 ON m2.market_ticker=m1.market_ticker AND m2.snapshot_minute_utc=(m1.snapshot_minute_utc + INTERVAL 1 MINUTE)
            WHERE p.snapshot_minute_utc >= (UTC_TIMESTAMP() - INTERVAL %s HOUR)
            ORDER BY p.snapshot_minute_utc DESC
            LIMIT 2000
            """,
            (window_hours,),
        )
        cal: Dict[str, Dict[str, Dict[str, float]]] = {}
        for r in cur.fetchall():
            model = r["model_name"]
            p = float(r["prob_yes"])
            y = 1 if float(r["mid_next"]) > float(r["mid_now"]) else 0
            b = _bucket_key(p)
            cal.setdefault(model, {}).setdefault(b, {"n": 0, "sum_p": 0.0, "sum_y": 0.0})
            cal[model][b]["n"] += 1
            cal[model][b]["sum_p"] += p
            cal[model][b]["sum_y"] += y
        for model, buckets in cal.items():
            for b, v in sorted(buckets.items()):
                if v["n"] <= 0:
                    continue
                out["calibration"].append(
                    {
                        "model_name": model,
                        "bucket": b,
                        "n": int(v["n"]),
                        "avg_pred": v["sum_p"] / v["n"],
                        "avg_realized": v["sum_y"] / v["n"],
                    }
                )

        exec_stats: Dict[str, Dict[str, float]] = {}
        for t in out["recent_trades"]:
            m = t["model_name"]
            exec_stats.setdefault(m, {"n": 0, "sum_slippage": 0.0, "sum_abs_slippage": 0.0})
            if t["slippage"] is not None:
                exec_stats[m]["n"] += 1
                exec_stats[m]["sum_slippage"] += float(t["slippage"])
                exec_stats[m]["sum_abs_slippage"] += abs(float(t["slippage"]))
        for m, v in exec_stats.items():
            n = int(v["n"])
            out["execution_quality"].append(
                {
                    "model_name": m,
                    "n": n,
                    "avg_slippage": (v["sum_slippage"] / n) if n > 0 else None,
                    "avg_abs_slippage": (v["sum_abs_slippage"] / n) if n > 0 else None,
                }
            )

        def _segment_stats(trade_where_sql: str, pred_where_sql: str, params: tuple):
            cur.execute(
                f"""
                SELECT model_name, COUNT(*) closed_trades,
                       COALESCE(SUM(pnl_dollars),0) total_pnl,
                       COALESCE(AVG(pnl_dollars),0) avg_pnl,
                       COALESCE(SUM(pnl_dollars > 0),0) wins
                FROM sim_trades
                WHERE status='closed' AND {trade_where_sql}
                GROUP BY model_name
                ORDER BY model_name
                """,
                params,
            )
            trade_rows = cur.fetchall()
            cur.execute(
                f"""
                SELECT model_name, COUNT(*) n_preds,
                       COALESCE(AVG(brier),0) avg_brier,
                       COALESCE(AVG(logloss),0) avg_logloss
                FROM sim_model_predictions_1m
                WHERE {pred_where_sql}
                GROUP BY model_name
                ORDER BY model_name
                """,
                params,
            )
            pred_map = {r["model_name"]: r for r in cur.fetchall()}
            out_rows = []
            for r in trade_rows:
                m = r["model_name"]
                closed = int(r["closed_trades"] or 0)
                wins = int(r["wins"] or 0)
                p = pred_map.get(m, {})
                out_rows.append(
                    {
                        "model_name": m,
                        "closed_trades": closed,
                        "total_pnl": float(r["total_pnl"] or 0.0),
                        "avg_pnl": float(r["avg_pnl"] or 0.0),
                        "win_rate": (wins / closed) if closed > 0 else None,
                        "n_preds": int(p.get("n_preds") or 0),
                        "avg_brier": float(p.get("avg_brier") or 0.0),
                        "avg_logloss": float(p.get("avg_logloss") or 0.0),
                    }
                )
            return out_rows

        cutoff = out.get("live_cutoff_utc")
        if cutoff:
            out["in_sample"] = _segment_stats("closed_at_utc < %s", "snapshot_minute_utc < %s", (cutoff,))
            out["out_of_sample"] = _segment_stats("closed_at_utc >= %s", "snapshot_minute_utc >= %s", (cutoff,))
        else:
            out["in_sample"] = _segment_stats("closed_at_utc IS NOT NULL", "1=1", tuple())
            out["out_of_sample"] = _segment_stats("1=0", "1=0", tuple())

    conn.close()
    return out


def live_settings_update(model_name: str, patch: Dict):
    conn = get_db_conn()
    with conn.cursor() as cur:
        out = live_update_settings(cur, model_name, patch)
    conn.commit()
    conn.close()
    return out


def live_metrics(window_hours: int = 12):
    return _cached(("live_metrics", window_hours), _METRICS_CACHE_TTL_SECONDS, lambda: _live_metrics_uncached(window_hours))


def _live_metrics_uncached(window_hours: int = 12):
    conn = get_db_conn()
    out = {
        "settings": {},
        "models": {},
        "equity_series_20s": [],
        "stack_series_20s": [],
        "drawdown_series_20s": [],
        "open_positions": [],
        "recent_orders": [],
        "recent_trades": [],
        "risk_state": "GREEN",
        "cash_source": "unknown",
        "scorecard": {},
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT snapshot_time_utc, cash_dollars, position_value_dollars, equity_dollars, drawdown_dollars, risk_state, raw_json
            FROM live_portfolio_20s
            WHERE snapshot_time_utc >= (UTC_TIMESTAMP() - INTERVAL %s HOUR)
            ORDER BY snapshot_time_utc ASC
            """,
            (window_hours,),
        )
        latest_equity = None
        for r in cur.fetchall():
            ts = str(r["snapshot_time_utc"])
            out["equity_series_20s"].append({"t": ts, "equity": float(r["equity_dollars"])})
            out["stack_series_20s"].append({"t": ts, "cash": float(r["cash_dollars"]), "position": float(r["position_value_dollars"])})
            out["drawdown_series_20s"].append({"t": ts, "drawdown": float(r["drawdown_dollars"])})
            out["risk_state"] = r["risk_state"]
            latest_equity = float(r["equity_dollars"])
            try:
                raw = r["raw_json"] if isinstance(r["raw_json"], dict) else json.loads(r["raw_json"] or "{}")
                out["cash_source"] = raw.get("cash_source", out["cash_source"])
            except Exception:
                pass

        cur.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(pnl_dollars),0) p, COALESCE(AVG(pnl_dollars),0) a, COALESCE(SUM(pnl_dollars>0),0) w "
            "FROM live_trades WHERE status='closed'"
        )
        s = cur.fetchone()
        closed = int(s["c"] or 0)
        wins = int(s["w"] or 0)
        out["scorecard"] = {
            "closed_trades": closed,
            "total_pnl": float(s["p"] or 0),
            "avg_pnl": float(s["a"] or 0),
            "win_rate": (wins / closed) if closed > 0 else None,
            "equity": latest_equity,
        }

        cur.execute("SELECT model_name, qty_contracts, entry_price_dollars, opened_at_utc, market_ticker FROM live_positions ORDER BY opened_at_utc DESC")
        pos_rows = cur.fetchall()
        latest_bids: Dict[str, Optional[float]] = {}
        tickers = list({p["market_ticker"] for p in pos_rows})
        if tickers:
            placeholders = ",".join(["%s"] * len(tickers))
            cur.execute(
                f"""
                SELECT f1.market_ticker, f1.yes_bid_dollars
                FROM forward_quotes f1
                JOIN (
                  SELECT market_ticker, MAX(snapshot_time_utc) mx
                  FROM forward_quotes
                  WHERE market_ticker IN ({placeholders})
                  GROUP BY market_ticker
                ) f2 ON f2.market_ticker=f1.market_ticker AND f2.mx=f1.snapshot_time_utc
                """,
                tuple(tickers),
            )
            latest_bids = {
                r["market_ticker"]: float(r["yes_bid_dollars"]) if r["yes_bid_dollars"] is not None else None
                for r in cur.fetchall()
            }
        for p in pos_rows:
            bid = latest_bids.get(p["market_ticker"])
            if bid is None:
                bid = float(p["entry_price_dollars"])
            out["open_positions"].append(
                {
                    "model_name": p["model_name"],
                    "market_ticker": p["market_ticker"],
                    "qty_contracts": int(p["qty_contracts"]),
                    "entry_price": float(p["entry_price_dollars"]),
                    "mark_bid": bid,
                    "unrealized_pnl": (bid - float(p["entry_price_dollars"])) * int(p["qty_contracts"]),
                    "opened_at_utc": str(p["opened_at_utc"]),
                }
            )

        cur.execute(
            """
            SELECT created_at_utc, market_ticker, action, side, qty_contracts, limit_price_dollars, status, kalshi_order_id, client_order_id
            FROM live_orders
            ORDER BY id DESC
            LIMIT 40
            """
        )
        out["recent_orders"] = [
            {
                "created_at_utc": str(r["created_at_utc"]),
                "market_ticker": r["market_ticker"],
                "action": r["action"],
                "side": r["side"],
                "qty_contracts": int(r["qty_contracts"]),
                "limit_price_dollars": float(r["limit_price_dollars"]) if r["limit_price_dollars"] is not None else None,
                "status": r["status"],
                "kalshi_order_id": r["kalshi_order_id"],
                "client_order_id": r["client_order_id"],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT model_name, opened_at_utc, closed_at_utc, market_ticker, qty_contracts, entry_price_dollars, exit_price_dollars, pnl_dollars, status
            FROM live_trades
            ORDER BY id DESC
            LIMIT 40
            """
        )
        out["recent_trades"] = [
            {
                "model_name": r["model_name"],
                "opened_at_utc": str(r["opened_at_utc"]),
                "closed_at_utc": str(r["closed_at_utc"]) if r["closed_at_utc"] else None,
                "market_ticker": r["market_ticker"],
                "qty_contracts": int(r["qty_contracts"]),
                "entry_price": float(r["entry_price_dollars"]),
                "exit_price": float(r["exit_price_dollars"]) if r["exit_price_dollars"] is not None else None,
                "pnl": float(r["pnl_dollars"]) if r["pnl_dollars"] is not None else None,
                "status": r["status"],
            }
            for r in cur.fetchall()
        ]

        # Per-strategy settings, pause state, closed-trade record, and the
        # most recent tick's live signal (prob/edge/risk) from the engine's
        # own snapshot - this is what makes each strategy card independently
        # meaningful instead of one global block for everything.
        pause_states = get_all_live_pause_states(cur)
        cur.execute(
            "SELECT model_name, COUNT(*) closed_trades, COALESCE(SUM(pnl_dollars),0) total_pnl, COALESCE(SUM(pnl_dollars>0),0) wins "
            "FROM live_trades WHERE status='closed' GROUP BY model_name"
        )
        trade_stats = {r["model_name"]: r for r in cur.fetchall()}

        cur.execute("SELECT state_value FROM collector_state WHERE state_key='live_trading_last_snapshot' LIMIT 1")
        snap_row = cur.fetchone()
        snap = {}
        if snap_row:
            sv = snap_row.get("state_value")
            try:
                snap = sv if isinstance(sv, dict) else json.loads(sv or "{}")
            except Exception:
                snap = {}
        snap_models = snap.get("models", {}) if isinstance(snap, dict) else {}

        # The same strategy's paper-trading record, so a live card can be read
        # against the sim track record it was promoted on without switching
        # tabs. Same source and shape as the Portfolio Manager's total_pnl, so
        # the two panels always agree.
        placeholders = ",".join(["%s"] * len(LIVE_MODELS))
        cur.execute(
            f"""
            SELECT model_name, COUNT(*) closed_trades,
                   COALESCE(SUM(pnl_dollars),0) total_pnl,
                   COALESCE(SUM(pnl_dollars > 0),0) wins
            FROM sim_trades
            WHERE status='closed' AND model_name IN ({placeholders})
            GROUP BY model_name
            """,
            tuple(LIVE_MODELS),
        )
        sim_stats = {r["model_name"]: r for r in cur.fetchall()}

        for model_name in LIVE_MODELS:
            cfg = live_load_settings(cur, model_name)
            out["settings"][model_name] = cfg
            ts_stat = trade_stats.get(model_name)
            closed_m = int(ts_stat["closed_trades"]) if ts_stat else 0
            wins_m = int(ts_stat["wins"]) if ts_stat else 0
            pause = pause_states.get(model_name)
            live_snap = snap_models.get(model_name, {})
            out["models"][model_name] = {
                "live_enabled": bool(cfg.get("live_enabled")),
                "paused": pause is not None,
                "paused_reason": pause.get("paused_reason") if pause else None,
                "closed_trades": closed_m,
                "total_pnl": float(ts_stat["total_pnl"]) if ts_stat else 0.0,
                "win_rate": (wins_m / closed_m) if closed_m > 0 else None,
                "risk_state": live_snap.get("risk_state", "GREEN"),
                "prob": live_snap.get("prob"),
                "edge": live_snap.get("edge"),
                "signal": live_snap.get("signal"),
            }
            sim_stat = sim_stats.get(model_name)
            sim_closed = int(sim_stat["closed_trades"]) if sim_stat else 0
            sim_wins = int(sim_stat["wins"]) if sim_stat else 0
            out["models"][model_name].update(
                {
                    "sim_total_pnl": float(sim_stat["total_pnl"]) if sim_stat else 0.0,
                    "sim_closed_trades": sim_closed,
                    "sim_win_rate": (sim_wins / sim_closed) if sim_closed > 0 else None,
                }
            )

        out["writers"] = _writer_freshness(
            cur,
            {
                "live_portfolio_20s": _freshness_sql("live_portfolio_20s", "snapshot_time_utc"),
                "live_engine": (
                    "SELECT updated_at_utc last_utc, "
                    "TIMESTAMPDIFF(SECOND, updated_at_utc, UTC_TIMESTAMP()) age_sec "
                    "FROM collector_state WHERE state_key='live_trading_last_snapshot' LIMIT 1"
                ),
                "forward_quotes": _freshness_sql("forward_quotes", "snapshot_time_utc"),
            },
        )
        cur.execute("SELECT UTC_TIMESTAMP() now_utc")
        out["generated_at_utc"] = str((cur.fetchone() or {}).get("now_utc") or "")
    conn.close()
    return out


def model_research_summary():
    conn = get_db_conn()
    out = {"best_models": [], "recent_runs": [], "last_run_state": None}
    with conn.cursor() as cur:
        cur.execute("SELECT state_value FROM collector_state WHERE state_key='model_research_last_run' LIMIT 1")
        state = cur.fetchone()
        if state:
            sv = state.get("state_value")
            if isinstance(sv, dict):
                out["last_run_state"] = sv
            else:
                try:
                    out["last_run_state"] = json.loads(sv)
                except Exception:
                    out["last_run_state"] = {"raw": str(sv)}

        cur.execute(
            """
            SELECT r.*
            FROM model_research_runs r
            JOIN (
              SELECT model_name, MAX(objective_pnl_dollars) best_pnl
              FROM model_research_runs
              WHERE stage='selected' AND status='success'
              GROUP BY model_name
            ) b ON b.model_name=r.model_name AND b.best_pnl=r.objective_pnl_dollars
            JOIN (
              SELECT model_name, objective_pnl_dollars, MAX(id) mx
              FROM model_research_runs
              WHERE stage='selected' AND status='success'
              GROUP BY model_name, objective_pnl_dollars
            ) x ON x.model_name=r.model_name AND x.objective_pnl_dollars=r.objective_pnl_dollars AND x.mx=r.id
            ORDER BY r.model_name
            """
        )
        best_runs = cur.fetchall()
        for b in best_runs:
            run_id = int(b["id"])
            cur.execute(
                """
                SELECT feature_name, importance_abs_mean, importance_signed_mean, rank_order, method
                FROM model_research_feature_importance
                WHERE run_id=%s
                ORDER BY rank_order ASC
                LIMIT 20
                """,
                (run_id,),
            )
            imp = [
                {
                    "feature_name": r["feature_name"],
                    "importance_abs_mean": float(r["importance_abs_mean"]),
                    "importance_signed_mean": float(r["importance_signed_mean"]),
                    "rank_order": int(r["rank_order"]),
                    "method": r["method"],
                }
                for r in cur.fetchall()
            ]
            params = b["params_json"] if isinstance(b["params_json"], dict) else json.loads(b["params_json"] or "{}")
            metrics = b["metrics_json"] if isinstance(b["metrics_json"], dict) else json.loads(b["metrics_json"] or "{}")
            feats = (
                b["selected_features_json"]
                if isinstance(b["selected_features_json"], list)
                else json.loads(b["selected_features_json"] or "[]")
            )
            out["best_models"].append(
                {
                    "run_id": run_id,
                    "model_name": b["model_name"],
                    "created_at_utc": str(b["created_at_utc"]),
                    "stage": b["stage"],
                    "objective_pnl_dollars": float(b["objective_pnl_dollars"]),
                    "n_train": int(b["n_train"]),
                    "n_eval": int(b["n_eval"]),
                    "params": params,
                    "metrics": metrics,
                    "selected_features": feats,
                    "feature_importance": imp,
                }
            )

        cur.execute(
            """
            SELECT id, created_at_utc, model_name, stage, objective_pnl_dollars, n_train, n_eval, status, notes
            FROM model_research_runs
            ORDER BY id DESC
            LIMIT 60
            """
        )
        out["recent_runs"] = [
            {
                "id": int(r["id"]),
                "created_at_utc": str(r["created_at_utc"]),
                "model_name": r["model_name"],
                "stage": r["stage"],
                "objective_pnl_dollars": float(r["objective_pnl_dollars"]),
                "n_train": int(r["n_train"]),
                "n_eval": int(r["n_eval"]),
                "status": r["status"],
                "notes": r["notes"],
            }
            for r in cur.fetchall()
        ]
    conn.close()
    return out


def _comment(code: str) -> str:
    """Escape pseudocode and mute its comment lines, so the algorithm reads
    before the commentary does."""
    out = []
    for line in code.split("\n"):
        esc = html.escape(line)
        idx = line.find("#")
        if idx >= 0:
            out.append(html.escape(line[:idx]) + '<span class="cm">' + html.escape(line[idx:]) + "</span>")
        else:
            out.append(esc)
    return "\n".join(out)


def render_page(title: str, body_html: str, service: str = "pipeline") -> str:
    css = """
    @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;600&family=Archivo+Narrow:wght@400;600&display=swap');
    /* Kursbuch: a station timetable, not a terminal. Ink on stock, hairline
       rules, tabular figures. One reserved signal colour, used nowhere but
       "this needs you". No cards, no shadows, no glass, no monospace. */
    :root{
      --stock:#E9EBE5;
      --stock-live:#EFE4E7;
      --stock-sunk:#DFE2DA;
      --stock-raised:#F1F3ED;
      --ink:#191B16;
      --ink-2:#444841;
      --ink-3:#5F645D;
      --rule:#C9CDC2;
      --rule-2:#B1B6AA;
      --signal:#C8102E;
      --signal-wash:#F8E4E6;
      --pos:#D9E7D6;
      --neg:#F0DEDC;
      --radius:3px;
      --gut:clamp(14px,2.2vw,28px);
    }
    *{box-sizing:border-box}
    html{-webkit-text-size-adjust:100%}
    body{
      margin:0;
      background:var(--stock);
      color:var(--ink);
      font-family:"Archivo",ui-sans-serif,system-ui,sans-serif;
      font-size:14px;
      line-height:1.45;
      font-variant-numeric:tabular-nums lining-nums;
      -webkit-font-smoothing:antialiased;
    }
    body.live-service{background:var(--stock-live)}
    /* --neg is a rose, and so is the live stock; on that surface the loss
       field needs its own value or money reads in one direction only. */
    body.live-service{--neg:#E7CFC9;--pos:#D2E4CE}
    ::selection{background:var(--ink);color:#F1F3ED}
    a{color:var(--ink);text-decoration-thickness:1px;text-underline-offset:2px;
      text-decoration-color:var(--rule-2)}
    a:hover{text-decoration-color:var(--ink)}
    input,textarea{caret-color:var(--signal)}
    :focus-visible{outline:2px solid var(--ink);outline-offset:2px}
    * ::-webkit-scrollbar{width:11px;height:11px}
    * ::-webkit-scrollbar-track{background:var(--stock-sunk)}
    * ::-webkit-scrollbar-thumb{background:var(--rule-2);border:3px solid var(--stock-sunk)}
    * ::-webkit-scrollbar-thumb:hover{background:var(--ink-3)}
    *{scrollbar-color:var(--rule-2) var(--stock-sunk);scrollbar-width:thin}

    /* ---- service head ------------------------------------------------- */
    .masthead{border-bottom:2px solid var(--ink);background:var(--stock)}
    body.live-service .masthead{background:var(--stock-live);border-bottom-color:var(--signal)}
    .masthead-in{max-width:2560px;margin:0 auto;padding:14px var(--gut) 10px;
      display:flex;align-items:baseline;justify-content:space-between;gap:16px;flex-wrap:wrap}
    .wordmark{font-family:"Archivo Narrow",Archivo,sans-serif;font-weight:600;font-size:13px;
      letter-spacing:.16em;text-transform:uppercase;margin:0}
    .wordmark .sep{color:var(--rule-2);margin:0 .5em}
    .wordmark .svc{color:var(--ink-3)}
    body.live-service .wordmark .svc{color:var(--signal)}
    .asof{font-family:"Archivo Narrow",Archivo,sans-serif;font-size:12px;letter-spacing:.08em;
      text-transform:uppercase;color:var(--ink-3);white-space:nowrap}
    .asof b{color:var(--ink);font-weight:600}

    /* ---- service links (tabs) ----------------------------------------- */
    .services{border-bottom:1px solid var(--rule)}
    .services-in{max-width:2560px;margin:0 auto;padding:0 var(--gut);display:flex;gap:0;flex-wrap:wrap}
    .svc-link{display:inline-block;padding:9px 16px 8px;text-decoration:none;color:var(--ink-2);
      font-family:"Archivo Narrow",Archivo,sans-serif;font-size:12.5px;letter-spacing:.1em;
      text-transform:uppercase;border-bottom:2px solid transparent;margin-bottom:-1px}
    .svc-link:hover{color:var(--ink);background:var(--stock-raised)}
    .svc-link[aria-current="page"]{color:var(--ink);border-bottom-color:var(--ink);font-weight:600}
    body.live-service .svc-link[aria-current="page"]{border-bottom-color:var(--signal)}

    .wrap{max-width:2560px;margin:0 auto;padding:0 var(--gut) 64px}

    /* ---- status line: the one dominant answer -------------------------- */
    .statusline{display:flex;align-items:flex-start;gap:12px;padding:16px 0 15px;
      border-bottom:1px solid var(--rule)}
    .statusline .mark{flex:none;width:17px;height:17px;margin-top:1px;color:var(--ink-3)}
    .statusline .mark-needs,.statusline.needs .mark-calm{display:none}
    .statusline.needs .mark-needs{display:block;color:var(--signal)}
    .statusline .said{font-family:"Archivo Narrow",Archivo,sans-serif;font-size:clamp(16px,2.1vw,20px);
      letter-spacing:.01em;font-weight:600;line-height:1.35;max-width:92ch}
    .statusline .said em{font-style:normal;color:var(--ink-3)}
    .statusline.needs .said em{color:var(--signal)}
    .statusline .sep{color:var(--rule-2);margin:0 .45em}

    /* ---- measured row: figures on one rule, never a card --------------- */
    /* Tracks are capped so four figures spread across the sheet instead of
       each sitting at the left edge of a 640px cell on an ultrawide. */
    .measure{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,300px));
      justify-content:space-between;border-bottom:1px solid var(--rule)}
    .measure > div{padding:14px 18px 13px;border-left:1px solid var(--rule)}
    .measure > div:first-child{border-left:0;padding-left:0}
    .lab{font-family:"Archivo Narrow",Archivo,sans-serif;font-size:11px;letter-spacing:.11em;
      text-transform:uppercase;color:var(--ink-3);display:block;margin-bottom:5px}
    .fig{font-size:clamp(21px,2.6vw,27px);font-weight:600;letter-spacing:-.015em;line-height:1.1;
      display:inline-block}
    .fig.sm{font-size:17px}
    .fig.tint{padding:1px 7px;margin-left:-7px;border-radius:var(--radius)}
    .fig.pos{background:var(--pos)}
    .fig.neg{background:var(--neg)}
    .sub-fig{font-size:12px;color:var(--ink-3);margin-top:4px}

    /* ---- section: ruled head + as-of rule (signature interaction) ------ */
    .sect{margin-top:32px}
    .sect-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
      flex-wrap:wrap;padding-bottom:7px;border-bottom:2px solid var(--ink)}
    .sect.stale .sect-head{border-bottom:2px dashed var(--signal)}
    .sect-head h2{margin:0;font-family:"Archivo Narrow",Archivo,sans-serif;font-size:13px;
      font-weight:600;letter-spacing:.13em;text-transform:uppercase}
    .sect-note{font-family:"Archivo Narrow",Archivo,sans-serif;font-size:12px;letter-spacing:.02em;
      color:var(--ink-3)}
    .sect.stale .sect-note{color:var(--signal);font-weight:600}
    /* The strike is half the stale signal; at 27px a 1px hairline in rule
       grey disappears, so it is drawn in ink and at 2px. */
    .sect.stale .measure .fig,.sect.stale tbody td{color:var(--ink-3);text-decoration:line-through;
      text-decoration-thickness:2px;text-decoration-color:var(--ink-2)}
    .stale-mark{color:var(--signal);font-weight:600;text-transform:uppercase;letter-spacing:.09em;
      text-decoration:none!important}

    /* ---- timetable ------------------------------------------------------ */
    .sheet{overflow-x:auto;overflow-y:visible}
    /* Fixed columns so a long strategy name cannot swallow the slack and
       strand the figures at the far right of a 2500px sheet. */
    .t-books,.t-strat,.t-period,.t-pos8,.t-pos7{table-layout:fixed;min-width:860px}
    .t-books col.c1{width:30%} .t-books col.c2,.t-books col.c3{width:13%}
    .t-books col.c4{width:10%} .t-books col.c5{width:8%}
    .t-books col.c6{width:12%} .t-books col.c7{width:14%}
    .t-strat col.c1{width:22%} .t-strat col.c2{width:9%}
    .t-strat col.c3{width:14%} .t-strat col.c4{width:17%}
    .t-strat col.c5{width:10%} .t-strat col.c6{width:8%}
    .t-strat col.c7{width:8%} .t-strat col.c8{width:12%}
    .t-period col.c1{width:18%} .t-period col.c2{width:13%}
    .t-period col.c3{width:12%} .t-period col.c4{width:10%}
    .t-period col.c5{width:9%} .t-period col.c6{width:12%}
    .t-period col.c7,.t-period col.c8{width:13%}
    .t-pos8 col.c1{width:20%} .t-pos8 col.c2{width:24%} .t-pos8 col.c3{width:7%}
    .t-pos8 col.c4{width:9%} .t-pos8 col.c5{width:10%} .t-pos8 col.c6{width:12%}
    .t-pos8 col.c7{width:12%} .t-pos8 col.c8{width:6%}
    .t-pos7 col.c1{width:22%} .t-pos7 col.c2{width:26%} .t-pos7 col.c3{width:8%}
    .t-pos7 col.c4{width:10%} .t-pos7 col.c5{width:11%} .t-pos7 col.c6{width:12%}
    .t-pos7 col.c7{width:11%}
    .t-books td,.t-strat td,.t-period td,.t-pos8 td,.t-pos7 td{overflow:hidden;text-overflow:ellipsis}
    .t-books td .sub-fig,.t-strat td .sub-fig{white-space:normal}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th,td{padding:9px 12px 8px;text-align:left;vertical-align:baseline;
      border-bottom:1px solid var(--rule);white-space:nowrap}
    th{font-family:"Archivo Narrow",Archivo,sans-serif;font-size:12px;letter-spacing:.02em;
      color:var(--ink-3);font-weight:600;
      border-bottom:1px solid var(--rule-2);position:sticky;top:0;background:var(--stock);z-index:1}
    body.live-service th{background:var(--stock-live)}
    td:first-child,th:first-child{padding-left:0}
    td:last-child,th:last-child{padding-right:0}
    tbody tr:hover td{background:var(--stock-raised)}
    td.num,th.num{text-align:right;font-variant-numeric:tabular-nums lining-nums}
    td.name{font-weight:600}
    /* Formulas and pseudocode sit on a recessed plate, the way a worked
       example sits in a printed manual. */
    .plate-eq{border:1px solid var(--rule);background:var(--stock-raised);
      padding:6px 16px 10px;margin:12px 0 0;overflow-x:auto}
    .plate-eq math{font-size:19px;color:var(--ink)}
    /* Monospace is barred as decoration, not where alignment carries meaning.
       Pseudocode is code: the indentation is the structure. */
    pre.code{margin:12px 0 0;padding:14px 16px;border:1px solid var(--rule);
      background:var(--stock-raised);overflow-x:auto;
      font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
      font-size:12.5px;line-height:1.75;color:var(--ink);
      font-variant-ligatures:none;white-space:pre;tab-size:2}
    pre.code .cm{color:var(--ink-3)}
    .cellwrap{max-width:46ch;white-space:normal;word-break:break-word;line-height:1.5;color:var(--ink-2)}
    .tick{font-family:"Archivo Narrow",Archivo,sans-serif;letter-spacing:.02em;color:var(--ink-2)}
    .empty-row td{color:var(--ink-3);padding:16px 0;border-bottom:1px solid var(--rule);
      display:block;max-width:66ch;white-space:normal}

    /* ---- marks: state never by colour alone ---------------------------- */
    .mk{font-family:"Archivo Narrow",Archivo,sans-serif;font-size:11px;letter-spacing:.09em;
      text-transform:uppercase;font-weight:600;padding:2px 7px 1px;border:1px solid var(--rule-2);
      border-radius:var(--radius);color:var(--ink-2);white-space:nowrap;display:inline-block}
    .mk.on{border-color:var(--ink);color:#F1F3ED;background:var(--ink)}
    .mk.armed{border-color:var(--signal);color:var(--signal);background:var(--signal-wash)}
    .mk.halt{border-color:var(--signal);color:#FDF2F3;background:var(--signal)}
    .mk.quiet{color:var(--ink-3)}
    .fnote{font-size:11px;color:var(--ink-3);vertical-align:super;line-height:0;margin-left:3px}
    .legend{font-size:12.5px;color:var(--ink-3);padding:10px 0 0;line-height:1.7;max-width:66ch}
    .legend b{color:var(--ink);font-weight:600}
    .legend .fnote{vertical-align:baseline;margin:0 4px 0 0}

    /* ---- controls ------------------------------------------------------- */
    .btn{font-family:"Archivo Narrow",Archivo,sans-serif;font-size:11.5px;letter-spacing:.1em;
      text-transform:uppercase;font-weight:600;padding:6px 13px 5px;border:1px solid var(--ink);
      border-radius:var(--radius);background:transparent;color:var(--ink);cursor:pointer;
      text-decoration:none;display:inline-block;transition:background .16s cubic-bezier(.16,1,.3,1),
      color .16s cubic-bezier(.16,1,.3,1)}
    .btn:hover{background:var(--ink);color:#F1F3ED}
    .btn:active{transform:translateY(1px)}
    .btn[disabled]{border-color:var(--rule-2);color:var(--ink-3);cursor:not-allowed;background:transparent}
    .btn.danger{border-color:var(--signal);color:var(--signal)}
    .btn.armed{background:var(--signal);color:#FDF2F3;border-color:var(--signal)}
    .btn.danger:hover{background:var(--signal);color:#FDF2F3}
    .btn.sm{font-size:11px;padding:4px 10px 3px}
    input,select,button{font-family:inherit;font-size:13px;color:var(--ink)}
    input[type=number],input[type=password],input[type=text],select{
      background:var(--stock-raised);border:1px solid var(--rule-2);border-radius:var(--radius);
      padding:6px 9px;width:100%;font-variant-numeric:tabular-nums}
    input:hover,select:hover{border-color:var(--ink-3)}
    input:focus,select:focus{border-color:var(--ink);outline:none;background:var(--stock)}
    .field{display:flex;flex-direction:column;gap:3px;min-width:104px}
    .field .lab{margin:0}
    details > summary{cursor:pointer;font-family:"Archivo Narrow",Archivo,sans-serif;font-size:12px;
      letter-spacing:.01em;color:var(--ink-3);list-style:none;padding:3px 0}
    details > summary::-webkit-details-marker{display:none}
    details > summary::before{content:"+ ";color:var(--rule-2)}
    details[open] > summary::before{content:"\\2212 "}
    details > summary:hover{color:var(--ink)}

    /* ---- plate: the ruled chart field ---------------------------------- */
    .plate{border:1px solid var(--rule);background:var(--stock-raised);padding:10px 12px 6px;
      margin-top:12px}
    body.live-service .plate{background:var(--stock)}
    canvas{display:block;width:100%;height:auto}
    @media (min-width:1500px){
      .plates{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}
      .plates > .plate:first-child{grid-column:1 / -1}
    }
    @media (min-width:2200px){
      .plates{grid-template-columns:repeat(3,1fr)}
      .plates > .plate:first-child{grid-column:auto}
    }
    /* Model names are snake_case identifiers; upper-casing a 29-character
       identifier costs legibility and buys nothing. */
    .keys{display:flex;flex-wrap:wrap;gap:14px;padding:9px 0 2px;font-size:12px;color:var(--ink-2);
      font-family:"Archivo Narrow",Archivo,sans-serif;letter-spacing:.01em}
    .keys span{display:inline-flex;align-items:center;gap:6px}
    .keys i{width:14px;height:0;border-top:2px solid currentColor;display:inline-block}

    /* ---- the one authored moment: a figure washes when it changes ------ */
    @keyframes wash{from{background-color:var(--rule-2)}to{background-color:transparent}}
    .washed{animation:wash .18s cubic-bezier(.16,1,.3,1) 1}
    @media (prefers-reduced-motion:reduce){
      *,*::before,*::after{animation-duration:.001ms!important;transition-duration:.001ms!important}
    }

    /* ---- notices -------------------------------------------------------- */
    .notice{border:1px solid var(--signal);background:var(--signal-wash);
      padding:12px 14px;margin:16px 0;font-size:13px;color:var(--ink);max-width:66ch}
    .notice h3{margin:0 0 4px;font-family:"Archivo Narrow",Archivo,sans-serif;font-size:11.5px;
      letter-spacing:.1em;text-transform:uppercase;color:var(--signal)}
    .prose{max-width:74ch;color:var(--ink-2);font-size:14.5px;line-height:1.6}
    /* A dossier is Read mode inside an Operate app: the page takes its own
       measure so the rules do not span 2500px over a 370px text column. */
    .reading{max-width:1060px}
    /* In the narrower reading column the capped tracks wrap and orphan a cell
       behind a border-left, so the record row shares the width evenly there. */
    .reading .measure{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));justify-content:stretch}
    h1.page{font-size:clamp(23px,3vw,30px);font-weight:600;letter-spacing:-.02em;margin:22px 0 3px}
    .deck{color:var(--ink-3);font-size:14px;max-width:68ch;margin-bottom:2px}
    .pager{display:flex;gap:10px;align-items:center;padding:12px 0}

    /* ---- responsive: one dominant answer owns the phone ----------------- */
    @media (max-width:860px){
      .measure{grid-template-columns:repeat(2,minmax(0,1fr))}
      .measure > div{border-left:0;padding:12px 0 11px}
      .measure > div:nth-child(even){padding-left:16px;border-left:1px solid var(--rule)}
      .sheet{margin:0 calc(var(--gut) * -1);padding:0 var(--gut)}
      th{position:static}
    }
    @media (max-width:640px){
      .stack thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
      .stack tbody tr{display:block;border-bottom:1px solid var(--rule-2);padding:9px 0 7px}
      .stack tbody tr{display:flex;flex-direction:column}
      .stack tbody td{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px;
        border:0;padding:2px 0;white-space:normal;text-align:left}
      .stack tbody td .sub-fig{flex:1 0 100%;text-align:right;margin-top:0}
      .stack tbody td.name{font-size:14px;order:-2}
      .stack tbody td.act{order:-1;padding:4px 0 6px}
      /* Leader dots: the device that lets a dense timetable be read standing
         up, and the reason a label and its figure stay tied across a gap. */
      .stack tbody td::before{order:-2}
      .stack tbody td::after{content:"";order:-1;flex:1 1 auto;min-width:14px;align-self:flex-end;
        margin:0 2px 5px;border-bottom:1px dotted var(--rule-2)}
      .stack tbody td.name::after,.stack tbody td.act::after{content:none}
      .stack tbody td.phone-hide{display:none}
      .stack tbody td::before{content:attr(data-lab);font-family:"Archivo Narrow",Archivo,sans-serif;
        font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);flex:none}
      .stack tbody td.num{text-align:right}
      .stack tbody tr:hover td{background:transparent}
      .statusline .said{font-size:15px}
    }
    @media print{
      body{background:#fff}
      .services,.btn{display:none}
    }
    """
    js = """
    function toUtcMs(v){
      if(v==null) return null;
      if(typeof v === 'number' && Number.isFinite(v)) return v;
      let s=String(v).trim();
      if(/^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$/.test(s)) s=s.replace(' ','T')+'Z';
      else if(/^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}$/.test(s)) s=s+'Z';
      const ms=Date.parse(s);
      return Number.isFinite(ms) ? ms : null;
    }
    function fmtNy(v){
      const ms = toUtcMs(v);
      if(ms==null) return String(v??'');
      const d = new Date(ms);
      const txt = new Intl.DateTimeFormat('en-US', {
        timeZone:'America/New_York',
        year:'numeric', month:'2-digit', day:'2-digit',
        hour:'2-digit', minute:'2-digit', second:'2-digit',
        hour12:false
      }).format(d).replace(',', '');
      return `${txt} ET`;
    }
    // Ink on stock. Traces separate by value AND dash pattern, so a reading is
    // never carried by colour alone.
    var TRACE=['#191B16','#7A5C2E','#31566F','#55693F','#6B4257'];
    var DASH=[[],[6,3],[2,3],[9,3,2,3],[4,2]];
    function fitCanvas(c, cssHeight){
      var dpr = window.devicePixelRatio || 1;
      var cssW = Math.max(240, c.clientWidth || c.parentElement.clientWidth || 640);
      c.width = Math.round(cssW * dpr);
      c.height = Math.round(cssHeight * dpr);
      c.style.height = cssHeight + 'px';
      var ctx = c.getContext('2d');
      ctx.setTransform(dpr,0,0,dpr,0,0);
      return {ctx:ctx, w:cssW, h:cssHeight};
    }
    function gridText(ctx){
      ctx.font='11px "Archivo Narrow", Archivo, sans-serif';
      ctx.fillStyle='#5F645D';
    }
    function drawLineChart(canvasId, seriesMap, key, colors, opts){
      const c = document.getElementById(canvasId);
      if(!c) return;
      const models = Object.keys(seriesMap||{}).filter(m => (seriesMap[m]||[]).length>0);
      const fit = fitCanvas(c, Number(c.dataset.h||200));
      const ctx=fit.ctx, w=fit.w, h=fit.h;
      ctx.clearRect(0,0,w,h);
      opts = opts || {};
      const padL=58, padR=14, padT=12, padB=24;
      if(models.length===0){
        gridText(ctx);
        ctx.fillText('no readings in this window', padL, h/2);
        return;
      }
      let all=[];
      for(const m of models){ for(const p of (seriesMap[m]||[])){ all.push(Number(p[key]||0)); } }
      let min=Math.min.apply(null,all), max=Math.max.apply(null,all);
      if(min===max){ min-=1; max+=1; }
      const span=max-min; min-=span*0.06; max+=span*0.06;
      const toX=(i,n)=> padL + (i*(w-padL-padR))/Math.max(1,n-1);
      const toY=(v)=> h-padB - ((v-min)*(h-padT-padB))/Math.max(1e-9,(max-min));
      gridText(ctx);
      ctx.textBaseline='middle';
      for(let k=0;k<=4;k++){
        const v=min+(max-min)*(k/4), y=Math.round(toY(v))+0.5;
        ctx.strokeStyle = (k===0||k===4) ? '#B1B6AA' : '#D7DBD0';
        ctx.lineWidth=1;
        ctx.beginPath(); ctx.moveTo(padL,y); ctx.lineTo(w-padR,y); ctx.stroke();
        const label = opts.unit==='$' ? ('$'+v.toFixed(2)) : v.toFixed(4);
        ctx.textAlign='right';
        ctx.fillText(label, padL-8, y);
      }
      // zero line reads heavier than the graticule
      if(min<0 && max>0){
        const y=Math.round(toY(0))+0.5;
        ctx.strokeStyle='#191B16'; ctx.lineWidth=1;
        ctx.beginPath(); ctx.moveTo(padL,y); ctx.lineTo(w-padR,y); ctx.stroke();
      }
      let idx=0;
      for(const m of models){
        const ser=seriesMap[m]||[];
        ctx.beginPath();
        for(let i=0;i<ser.length;i++){
          const x=toX(i,ser.length), y=toY(Number(ser[i][key]||0));
          if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        }
        ctx.setLineDash(DASH[idx%DASH.length]);
        ctx.strokeStyle=(colors&&colors[m])||TRACE[idx%TRACE.length];
        ctx.lineWidth=1.75; ctx.lineJoin='round';
        ctx.stroke();
        ctx.setLineDash([]);
        idx++;
      }
      if(opts.cutoff && (seriesMap[models[0]]||[]).length>1){
        const base=seriesMap[models[0]];
        const ci=base.findIndex(p => String(p.t) >= String(opts.cutoff));
        if(ci>=0){
          const x=Math.round(toX(ci, base.length))+0.5;
          ctx.strokeStyle='#C8102E'; ctx.lineWidth=1; ctx.setLineDash([5,3]);
          ctx.beginPath(); ctx.moveTo(x,padT); ctx.lineTo(x,h-padB); ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle='#C8102E'; ctx.textAlign='left'; ctx.textBaseline='top';
          ctx.fillText('LIVE', Math.min(w-40, x+5), padT);
        }
      }
      ctx.textAlign='left'; ctx.textBaseline='alphabetic';
    }
    function drawStackChart(canvasId, series, keyA, keyB, opts){
      const c=document.getElementById(canvasId);
      if(!c) return;
      const fit=fitCanvas(c, Number(c.dataset.h||180));
      const ctx=fit.ctx, w=fit.w, h=fit.h;
      ctx.clearRect(0,0,w,h);
      opts=opts||{};
      const padL=58,padR=14,padT=12,padB=24;
      gridText(ctx); ctx.textBaseline='middle';
      if(!series || series.length===0){ ctx.fillText('no readings in this window', padL, h/2); return; }
      const va=series.map(p=>Number(p[keyA]||0));
      const vb=series.map(p=>Number(p[keyB]||0));
      const all=va.concat(vb);
      let min=Math.min(Math.min.apply(null,all),0), max=Math.max(Math.max.apply(null,all),1);
      if(min===max){ min-=1; max+=1; }
      const toX=(i,n)=> padL + (i*(w-padL-padR))/Math.max(1,n-1);
      const toY=(v)=> h-padB - ((v-min)*(h-padT-padB))/Math.max(1e-9,(max-min));
      for(let k=0;k<=4;k++){
        const v=min+(max-min)*(k/4), y=Math.round(toY(v))+0.5;
        ctx.strokeStyle=(k===0||k===4)?'#B1B6AA':'#D7DBD0'; ctx.lineWidth=1;
        ctx.beginPath(); ctx.moveTo(padL,y); ctx.lineTo(w-padR,y); ctx.stroke();
        ctx.textAlign='right'; ctx.fillText('$'+v.toFixed(2), padL-8, y);
      }
      const band=(vals,fill,stroke,dash)=>{
        ctx.beginPath();
        for(let i=0;i<vals.length;i++){ const x=toX(i,vals.length), y=toY(vals[i]); if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y); }
        ctx.lineTo(toX(vals.length-1,vals.length),toY(min));
        ctx.lineTo(toX(0,vals.length),toY(min));
        ctx.closePath(); ctx.fillStyle=fill; ctx.fill();
        ctx.beginPath();
        for(let i=0;i<vals.length;i++){ const x=toX(i,vals.length), y=toY(vals[i]); if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y); }
        ctx.setLineDash(dash); ctx.strokeStyle=stroke; ctx.lineWidth=1.75; ctx.stroke(); ctx.setLineDash([]);
      };
      band(va,'rgba(25,27,22,0.07)','#191B16',[]);
      band(vb,'rgba(122,92,46,0.10)','#7A5C2E',[6,3]);
      if(opts.cutoff && series.length>1){
        const ci=series.findIndex(p=>String(p.t)>=String(opts.cutoff));
        if(ci>=0){
          const x=Math.round(toX(ci,series.length))+0.5;
          ctx.strokeStyle='#C8102E'; ctx.lineWidth=1; ctx.setLineDash([5,3]);
          ctx.beginPath(); ctx.moveTo(x,padT); ctx.lineTo(x,h-padB); ctx.stroke(); ctx.setLineDash([]);
          ctx.fillStyle='#C8102E'; ctx.textAlign='left'; ctx.textBaseline='top';
          ctx.fillText('LIVE', Math.min(w-40,x+5), padT);
        }
      }
      ctx.textAlign='left'; ctx.textBaseline='alphabetic';
    }
    function computeDrawdownSeriesFromEquity(series){
      if(!series || series.length===0) return [];
      let peak = Number(series[0].equity||0);
      const out=[];
      for(const p of series){
        const eq = Number(p.equity||0);
        if(eq > peak) peak = eq;
        out.push({t:p.t, drawdown:eq - peak});
      }
      return out;
    }
    function sliceAndRebaseSeries(byModelRaw, models, startTs, endTs){
      const startMs=toUtcMs(startTs);
      const endMs=toUtcMs(endTs);
      const out={};
      for(const m of models){
        const src=(byModelRaw[m]||[]);
        const seg=src.filter(p => {
          const pms=toUtcMs(p.t);
          if(pms==null) return false;
          if(startMs!=null && pms < startMs) return false;
          if(endMs!=null && pms >= endMs) return false;
          return true;
        });
        if(seg.length===0) continue;
        const baseEq=Number(seg[0].equity||0);
        out[m]=seg.map(p => ({t:p.t, equity: 100 + (Number(p.equity||0) - baseEq)}));
      }
      return out;
    }
    function rebaseWholeSeries(byModelRaw, models){
      const out={};
      for(const m of models){
        const src=(byModelRaw[m]||[]);
        if(src.length===0) continue;
        const baseEq=Number(src[0].equity||0);
        out[m]=src.map(p => ({t:p.t, equity: 100 + (Number(p.equity||0) - baseEq)}));
      }
      return out;
    }
    function isWalkForwardModel(m){
      return String(m||'').startsWith('walk_forward_');
    }
    function segmentRangeText(seriesMap){
      let minT=null, maxT=null;
      for(const k of Object.keys(seriesMap||{})){
        const arr=seriesMap[k]||[];
        if(arr.length===0) continue;
        const s=arr[0].t, e=arr[arr.length-1].t;
        const sms=toUtcMs(s), ems=toUtcMs(e);
        if(sms==null || ems==null) continue;
        if(minT===null || sms < minT) minT=sms;
        if(maxT===null || ems > maxT) maxT=ems;
      }
      if(minT===null || maxT===null) return '(no data)';
      return `(${fmtNy(minT)} → ${fmtNy(maxT)})`;
    }
    function segmentTotals(rows){
      const out={closed:0,pnl:0,wins:0,preds:0,brierSum:0,brierN:0,loglossSum:0,loglossN:0};
      for(const r of (rows||[])){
        const c=Number(r.closed_trades||0);
        const wr=(r.win_rate==null?null:Number(r.win_rate));
        out.closed += c;
        out.pnl += Number(r.total_pnl||0);
        out.wins += (wr==null?0:(wr*c));
        out.preds += Number(r.n_preds||0);
        if(r.avg_brier!=null){ out.brierSum += Number(r.avg_brier)*Math.max(1,Number(r.n_preds||0)); out.brierN += Math.max(1,Number(r.n_preds||0)); }
        if(r.avg_logloss!=null){ out.loglossSum += Number(r.avg_logloss)*Math.max(1,Number(r.n_preds||0)); out.loglossN += Math.max(1,Number(r.n_preds||0)); }
      }
      out.win_rate = out.closed>0 ? (out.wins/out.closed) : null;
      out.avg_brier = out.brierN>0 ? (out.brierSum/out.brierN) : null;
      out.avg_logloss = out.loglossN>0 ? (out.loglossSum/out.loglossN) : null;
      return out;
    }
    // PnL here comes from the closed-trade aggregates in d.in_sample /
    // d.out_of_sample, never from the equity series feeding the charts: those
    // series only cover the last window_hours and are rebased so their first
    // point is $100, so reading their endpoint reported the change over the
    // visible window (often $0.00) as if it were the segment's total PnL.
    function renderSegmentSummary(d, models, currentBasisLabel){
      const body=document.getElementById('sim_segments_body');
      if(!body) return;
      const pick=(arr)=>(arr||[]).filter(r=>models.includes(r.model_name));
      const inRows=pick(d.in_sample), oosRows=pick(d.out_of_sample);
      const hasCutoff=!!d.live_cutoff_utc;
      const out=[];
      for(const m of models){
        const inRow=inRows.find(x=>x.model_name===m);
        const oosRow=oosRows.find(x=>x.model_name===m);
        if(!inRow && !oosRow) continue;
        const isWF=isWalkForwardModel(m);
        const segs = isWF
          ? [['Walk-forward', [inRow,oosRow].filter(Boolean)]]
          : [['In-sample', inRow?[inRow]:[]], ['Out-of-sample', oosRow?[oosRow]:[]]];
        segs.forEach(([label,rows],i)=>{
          const t=segmentTotals(rows);
          const pnl=money(t.pnl);
          out.push(`<tr>
            <td class="name" data-lab="Strategy">${i===0?esc(m):''}</td>
            <td data-lab="Period">${esc(label)}</td>
            <td class="num" data-lab="P&amp;L"><span class="fig sm tint ${pnl.cls}">${pnl.txt}</span></td>
            <td class="num" data-lab="Closed">${Number(t.closed||0).toLocaleString()}</td>
            <td class="num" data-lab="Win">${t.win_rate==null?'n/a':pct(t.win_rate,1)}</td>
            <td class="num" data-lab="Predictions">${Number(t.preds||0).toLocaleString()}</td>
            <td class="num" data-lab="Brier">${t.avg_brier==null?'n/a':t.avg_brier.toFixed(4)}</td>
            <td class="num" data-lab="Log loss">${t.avg_logloss==null?'n/a':t.avg_logloss.toFixed(4)}</td>
          </tr>`);
        });
      }
      body.innerHTML = out.length ? out.join('')
        : '<tr class="empty-row"><td colspan="8">No closed paper trades on either side of the cutoff yet.</td></tr>';
      const basis=document.getElementById('sim_basis');
      if(basis) basis.textContent = hasCutoff ? 'split at the live cutoff' : 'no cutoff set';
    }
    function esc(v){
      return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    var MINUS='\u2212';
    function money(v, decimals){
      const n=Number(v||0), d=(decimals==null?2:decimals);
      const txt=(n>0?'+$':(n<0?MINUS+'$':'$'))+Math.abs(n).toFixed(d);
      return {txt:txt, cls:(n>0?'pos':(n<0?'neg':''))};
    }
    function pct(v, d){ return v==null ? 'n/a' : (Number(v)*100).toFixed(d==null?0:d)+'%'; }
    function labelOf(col){ return String(col).replace(/_/g,' '); }
    function isNumericCol(col){
      return /(pnl|qty|price|bid|entry|exit|n$|_n$|rate|count|trades|brier|logloss|preds|avg|slippage|limit|equity|value|unrealized)/i.test(col);
    }
    function renderRows(tbodyId, rows, cols, emptyMsg){
      const el=document.getElementById(tbodyId); if(!el) return;
      if(!rows || rows.length===0){
        el.innerHTML = `<tr class="empty-row"><td colspan="${cols.length}">${esc(emptyMsg||'Nothing recorded yet.')}</td></tr>`;
        return;
      }
      el.innerHTML = rows.map(r => '<tr>' + cols.map(c => {
        let v = r[c];
        if(/(_utc|^opened|^closed|^created|^time$)/.test(c) && v) v = fmtNy(v);
        if(typeof v === 'number' && !Number.isInteger(v)) v = v.toFixed(4).replace(/0+$/,'').replace(/\\.$/,'');
        const cls = isNumericCol(c) ? ' class="num"' : '';
        return `<td${cls} data-lab="${esc(labelOf(c))}">${esc(v)}</td>`;
      }).join('') + '</tr>').join('');
    }
    // ---- the as-of rule -------------------------------------------------
    // A panel states the age of the writer behind it. When that writer stops,
    // the rule under its heading breaks to dashed and the figures strike out.
    // Nothing here pops a toast; the page tells the truth typographically.
    function ageWords(sec){
      if(sec==null) return 'unknown';
      const s=Math.max(0,Math.round(sec));
      if(s<90) return s+'s';
      const m=Math.round(s/60); if(m<90) return m+'m';
      const h=Math.round(m/60); if(h<48) return h+'h';
      return Math.round(h/24)+'d';
    }
    function fresh(writers, name){
      const w=(writers||{})[name];
      if(!w || w.age_sec==null) return {known:false, stale:false, age:null};
      const expect=Number(w.expect_sec||60);
      return {known:true, stale:Number(w.age_sec) > expect*6, age:Number(w.age_sec), last:w.last_utc};
    }
    function markSection(sectId, f, whatWrites){
      const sect=document.getElementById(sectId); if(!sect) return;
      const note=sect.querySelector('.sect-note');
      if(!f.known){
        sect.classList.remove('stale');
        if(note) note.textContent='never written';
        return;
      }
      sect.classList.toggle('stale', f.stale);
      if(!note) return;
      note.innerHTML = f.stale
        ? `<span class="stale-mark">stale ${esc(ageWords(f.age))}</span> &#183; ${esc(whatWrites)} stopped writing`
        : `as of ${esc(ageWords(f.age))} ago`;
    }
    // ---- the one authored moment ----------------------------------------
    var LAST_FIG={};
    function washIfChanged(key, value, el){
      if(!el) return;
      const prev=LAST_FIG[key];
      LAST_FIG[key]=value;
      if(prev===undefined || prev===value) return;
      el.classList.remove('washed');
      void el.offsetWidth;
      el.classList.add('washed');
    }
    function setStatusLine(elId, parts, needsYou){
      const el=document.getElementById(elId); if(!el) return;
      el.classList.toggle('needs', !!needsYou);
      const said=el.querySelector('.said');
      if(said){
        said.innerHTML = parts.map(pt =>
          pt.alarm ? `<em>${esc(pt.text)}</em>` : esc(pt.text)
        ).join('<span class="sep">&#183;</span>');
      }
    }
    function headClock(generatedAt){
      const el=document.getElementById('head_asof'); if(!el) return;
      const now=new Date();
      const t=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',
        minute:'2-digit',second:'2-digit',hour12:false}).format(now);
      el.innerHTML = `read <b>${esc(t)}</b> ET`;
    }
    function livePass(){
      const sp = new URLSearchParams(window.location.search || '');
      const q = sp.get('live_password') || '';
      if(q){ try{ localStorage.setItem('live_password', q); }catch(e){} return q; }
      try{ return localStorage.getItem('live_password') || ''; }catch(e){ return ''; }
    }
    const SIM_MODELS=['naive_logistic_baseline','logistic','random_forest','random_forest_high_conviction','binary_theory_edge'];
    const LIVE_MODELS=['random_forest','random_forest_high_conviction','binary_theory_edge'];
    function simColor(id, idx){ return TRACE[idx % TRACE.length]; }
    function simDash(idx){
      const d=DASH[idx % DASH.length];
      return d.length===0 ? 'solid' : (d.length===2 && d[0]<=2 ? 'dotted' : 'dashed');
    }
    async function resumeModel(modelName){
      const r=await fetch('/sim_risk/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:modelName})});
      let j={};
      try{ j=await r.json(); }catch(e){}
      if(!r.ok || !j.ok){ setNotice('sim-root', `Could not resume ${modelName}: ${(j&&j.error)||('HTTP '+r.status)}. The book stays halted.`, 'Resume failed'); }
      else { setNotice('sim-root', `${modelName} may open paper positions again.`, 'Resumed'); }
      await refreshSimMetrics();
    }
    var VERDICT_MARK={promising:'\u2020', thin_edge:'\u2021', negative:'\u00a7', paused:'\u00b6', gathering_data:'\u2022'};
    function renderStrategyRecord(d, name){
      const el=document.getElementById('strat_record');
      if(!el) return;
      const c=(d.scorecards||[]).find(x=>x.model_name===name);
      if(!c){
        el.innerHTML='<div><span class="lab">Record</span><span class="fig sm">no closed trades yet</span></div>';
        return;
      }
      const eq=money(c.equity==null?0:c.equity), pnl=money(c.total_pnl);
      const state=c.paused?'Halted':'Trading';
      el.innerHTML=
        `<div><span class="lab">Equity</span><span class="fig">${eq.txt}</span>`+
          `<div class="sub-fig">started at $100.00</div></div>`+
        `<div><span class="lab">Total P&amp;L</span><span class="fig tint ${pnl.cls}">${pnl.txt}</span>`+
          `<div class="sub-fig">${Number(c.closed_trades||0).toLocaleString()} closed trades</div></div>`+
        `<div><span class="lab">Win rate</span><span class="fig">${c.win_rate==null?'n/a':pct(c.win_rate,1)}</span>`+
          `<div class="sub-fig">of closed trades</div></div>`+
        `<div><span class="lab">State</span><span class="fig sm">${esc(state)}</span>`+
          `<div class="sub-fig">${c.paused?esc(c.paused_reason||'auto-halted'):'trading on its own book'}</div></div>`;
      const v=document.getElementById('strat_verdict');
      if(v){
        const rec=c.recommendation||{};
        v.innerHTML = rec.label
          ? `<b>Fee-adjusted verdict</b> &#8212; ${esc(rec.label)}`
          : '';
      }
      markSection('sect_strat_record', fresh(d.writers,'sim_trades'), 'the simulated engine');
    }
    function renderPortfolioManager(scorecards){
      const body=document.getElementById('pm_body');
      const legend=document.getElementById('pm_legend');
      if(!body) return;
      const cards=(scorecards||[]).filter(c=>SIM_MODELS.includes(c.model_name))
        .sort((a,b)=>Number(b.total_pnl||0)-Number(a.total_pnl||0));
      if(cards.length===0){
        body.innerHTML='<tr class="empty-row"><td colspan="7">No paper books have traded yet. They appear here once the simulated engine closes its first position.</td></tr>';
        return;
      }
      const marks=[];
      body.innerHTML = cards.map(c => {
        const eq=money(c.equity==null?0:c.equity);
        const pnl=money(c.total_pnl);
        const rec=c.recommendation||{};
        const mark=VERDICT_MARK[rec.status]||'';
        if(mark) marks.push({mark:mark, model:c.model_name, label:rec.label||rec.status});
        const unreal=Number(c.unrealized_pnl||0);
        const state=c.paused
          ? '<span class="mk halt">Halted</span>'
          : '<span class="mk on">Trading</span>';
        const act=c.paused
          ? `<button class="btn sm" onclick="resumeModel('${esc(c.model_name)}')">Resume</button>`
          : (rec.status==='promising' ? '<a class="btn sm" href="/?tab=live-trading">Review</a>' : '');
        const why=c.paused && c.paused_reason ? `<div class="sub-fig">${esc(c.paused_reason)}</div>` : '';
        const open=Math.abs(unreal)>=0.005 ? `<div class="sub-fig">open position ${money(unreal).txt} unrealised</div>` : '';
        return `<tr>
          <td class="name" data-lab="Strategy"><a href="/?tab=strategy&amp;name=${encodeURIComponent(c.model_name)}">${esc(c.model_name)}</a>${mark?`<span class="fnote">${mark}</span>`:''}${why}${open}</td>
          <td class="num" data-lab="Equity"><span class="fig sm">${eq.txt}</span></td>
          <td class="num" data-lab="Total P&amp;L"><span class="fig sm tint ${pnl.cls}">${pnl.txt}</span></td>
          <td class="num" data-lab="Trades">${Number(c.closed_trades||0).toLocaleString()}</td>
          <td class="num" data-lab="Win">${c.win_rate==null?'n/a':pct(c.win_rate)}</td>
          <td data-lab="State">${state}</td>
          <td class="act" data-lab="">${act}</td>
        </tr>`;
      }).join('');
      if(legend){
        // Keyed by strategy, not by status: two books can both be promising
        // with different fee-adjusted figures, and one shared line would show
        // whichever rendered last as if it spoke for both.
        legend.innerHTML = marks.map(mk =>
          `<div><span class="fnote">${mk.mark}</span><b>${esc(mk.model)}</b> &#8212; ${esc(mk.label)}</div>`
        ).join('');
      }
    }
    // A dialog drawn by the browser states no recovery and belongs to no
    // design system. Notices render in the page's own voice; destructive
    // actions arm in place and need a second, deliberate click.
    function setNotice(rootId, msg, kind){
      // Strategy actions report next to the strategy table; a confirmation
      // rendered at the top of a tall page is a confirmation nobody sees.
      const anchor = document.getElementById('strat_notice');
      const root = (anchor && rootId === 'live-root') ? anchor : document.getElementById(rootId);
      if(!root) return;
      const id=rootId+'_notice';
      let el=document.getElementById(id);
      if(!msg){ if(el) el.remove(); return; }
      if(!el){
        el=document.createElement('div');
        el.id=id; el.className='notice'; el.setAttribute('role','status');
        el.innerHTML='<h3></h3><p style="margin:0"></p>';
        root.insertBefore(el, root.firstChild);
      }
      el.querySelector('h3').textContent = kind || 'Notice';
      el.querySelector('p').textContent = msg;
      const box=el.getBoundingClientRect();
      if(box.top < 0 || box.bottom > innerHeight) el.scrollIntoView({block:'nearest'});
      clearTimeout(el._t);
      el._t=setTimeout(()=>{ el.remove(); }, 12000);
    }
    // Keyed by a stable string, never by the DOM node: the strategies table
    // re-renders every 10s, so an armed button object is destroyed under the
    // operator's hand and the confirming click used to land on a fresh node and
    // silently re-arm. That is the "I had to click it several times" bug.
    var ARMED=null;   // {key, label, run, t}
    function disarm(){
      if(!ARMED) return;
      clearTimeout(ARMED.t);
      const el=document.querySelector('[data-arm-key="'+ARMED.key+'"]');
      if(el && el.dataset.idle){ el.textContent=el.dataset.idle; el.classList.remove('armed'); }
      ARMED=null;
    }
    function arm(btn, confirmLabel, run){
      const key=btn.dataset.armKey;
      if(ARMED && ARMED.key===key){
        const go=ARMED.run;
        disarm();
        go();
        return;
      }
      disarm();
      btn.dataset.idle = btn.dataset.idle || btn.textContent;
      btn.textContent = confirmLabel;
      btn.classList.add('armed');
      ARMED={key:key, label:confirmLabel, run:run,
             t:setTimeout(()=>{ disarm(); }, 8000)};
    }
    function setFetchError(rootId, msg){
      const root=document.getElementById(rootId);
      if(!root) return;
      const id=rootId+'_fetch_error';
      let el=document.getElementById(id);
      if(!msg){ if(el) el.remove(); return; }
      if(!el){
        el=document.createElement('div');
        el.id=id; el.className='notice'; el.setAttribute('role','status');
        el.innerHTML='<h3>Reading failed</h3><p style="margin:0"></p>';
        root.insertBefore(el, root.firstChild);
      }
      el.querySelector('p').textContent=msg;
    }
    async function refreshSimMetrics(){
      const simRoot=document.getElementById('sim-root');
      if(!simRoot) return;
      try{
        // A dossier page is the same data narrowed to one book.
        const only = simRoot.dataset.strategy || '';
        const selectedModels = only ? [only] : SIM_MODELS;
        const r=await fetch('/sim_metrics',{cache:'no-store'});
        if(!r.ok){
          setFetchError('sim-root', `Simulated-trading data unavailable: /sim_metrics returned HTTP ${r.status}. The panels below are stale or empty until this is fixed - check the dashboard log on the server.`);
          return;
        }
        setFetchError('sim-root', null);
        const d=await r.json();
        renderPortfolioManager(d.scorecards);
        if(only) renderStrategyRecord(d, only);
        (function(){
          const cards=(d.scorecards||[]).filter(c=>SIM_MODELS.includes(c.model_name));
          const halted=cards.filter(c=>c.paused).length;
          const best=cards.slice().sort((a,b)=>Number(b.total_pnl||0)-Number(a.total_pnl||0))[0];
          const wTrades=fresh(d.writers,'sim_trades');
          const wPort=fresh(d.writers,'sim_portfolio_20s');
          const stale=[];
          if(wTrades.stale) stale.push('trade engine');
          if(wPort.stale) stale.push('equity writer');
          const parts=[];
          parts.push({text:(cards.length-halted)+' of '+cards.length+' books trading'});
          if(halted) parts.push({text:halted+' auto-halted', alarm:true});
          if(best) parts.push({text:'Best '+best.model_name+' '+money(best.total_pnl).txt});
          if(d.recompute_in_progress) parts.push({text:'Recompute running', alarm:true});
          parts.push(stale.length ? {text:stale.join(' + ')+' stale', alarm:true}
                                  : {text:'All writers current'});
          if(!only) setStatusLine('sim_status', parts, stale.length>0 || d.recompute_in_progress);
          markSection('sect_sim_books', wTrades, 'the simulated engine');
          markSection('sect_sim_plates', wPort, 'the equity writer');
          markSection('sect_sim_segments', wTrades, 'the simulated engine');
          headClock(d.generated_at_utc);
        })();
        const byModelRaw=(d.equity_series_1m && Object.keys(d.equity_series_1m).length>0) ? d.equity_series_1m : (d.equity_series_20s||{});
        const colors={};
        let idx=0;
        for(const m of selectedModels){
          if(byModelRaw[m]){ colors[m]=simColor(`sim:${m}`, idx++); }
        }
        const frozenModels=selectedModels.filter(m => !isWalkForwardModel(m));
        const wfModels=selectedModels.filter(m => isWalkForwardModel(m));
        const inSampleSeries = {
          ...sliceAndRebaseSeries(byModelRaw, frozenModels, null, d.live_cutoff_utc || null),
        };
        const outSampleSeries = {
          ...sliceAndRebaseSeries(byModelRaw, frozenModels, d.live_cutoff_utc || null, null),
          ...rebaseWholeSeries(byModelRaw, wfModels),
        };
        const hasCutoff = !!d.live_cutoff_utc;
        const currentBasisLabel = hasCutoff ? 'since out-of-sample start' : 'since in-sample start';
        if(Object.keys(inSampleSeries).length===0 && !d.live_cutoff_utc){
          // Fallback for environments with no cutoff configured yet.
          for(const m of selectedModels){
            if(byModelRaw[m] && byModelRaw[m].length>0){
              const baseEq = Number(byModelRaw[m][0].equity||0);
              inSampleSeries[m]=byModelRaw[m].map(p => ({t:p.t, equity:100 + (Number(p.equity||0)-baseEq)}));
            }
          }
        }
        drawLineChart('equity_chart_in_sample', inSampleSeries, 'equity', colors, {unit:'$'});
        drawLineChart('equity_chart_out_sample', outSampleSeries, 'equity', colors, {unit:'$'});
        const rin=document.getElementById('range_in_sample'); if(rin) rin.textContent=segmentRangeText(inSampleSeries);
        const roo=document.getElementById('range_out_sample'); if(roo) roo.textContent=segmentRangeText(outSampleSeries);
        const basePicked=selectedModels;
        let focusModel=null;
        const opens=(d.open_positions||[]);
        for(const m of selectedModels){
          if(opens.some(r => r.model_name===m)){ focusModel=m; break; }
        }
        if(!focusModel){
          for(const m of selectedModels){
            if((d.stack_series_20s||{})[m] && (d.stack_series_20s[m]||[]).length>0){ focusModel=m; break; }
          }
        }
        if(!focusModel){
          const ks=Object.keys(d.stack_series_20s||{});
          focusModel=ks.length?ks[0]:null;
        }
        if(focusModel && d.stack_series_20s && d.stack_series_20s[focusModel]){
          drawStackChart('stack_chart', d.stack_series_20s[focusModel], 'cash', 'position', {cutoff:d.live_cutoff_utc});
        }else{
          drawStackChart('stack_chart', [], 'cash', 'position', {cutoff:d.live_cutoff_utc});
        }
        const ddSel={};
        if(focusModel && d.equity_series_20s && d.equity_series_20s[focusModel]){
          const dd = computeDrawdownSeriesFromEquity(d.equity_series_20s[focusModel]);
          if(dd.length>0) ddSel[focusModel]=dd;
        }
        if(Object.keys(ddSel).length===0 && focusModel && d.drawdown_series_20s && d.drawdown_series_20s[focusModel]){
          ddSel[focusModel]=d.drawdown_series_20s[focusModel];
        }
        const ddColors = focusModel ? {[focusModel]: (colors[focusModel] || TRACE[0])} : {};
        drawLineChart('drawdown_chart', ddSel, 'drawdown', ddColors, {cutoff:d.live_cutoff_utc, unit:'$'});
        const stNote=document.getElementById('sim_stack_model');
        if(stNote) stNote.textContent = focusModel ? `model: ${focusModel}` : 'model: N/A';
        const ddNote=document.getElementById('sim_drawdown_model');
        if(ddNote) ddNote.textContent = focusModel ? `model: ${focusModel}` : 'model: N/A';
        renderSegmentSummary(d, basePicked, currentBasisLabel);

        renderRows('open_positions_body', (d.open_positions||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','market_ticker','qty_contracts','entry_price','mark_bid','unrealized_pnl','opened_at_utc'], 'No paper position is open right now.');
        renderRows('trades_body', (d.recent_trades||[]).filter(r => basePicked.includes(r.model_name)).slice(0,30), ['id','model_name','market_ticker','opened_at_utc','closed_at_utc','qty_contracts','entry_price','exit_price','pnl','status','expected_entry','slippage','fill_mode']);
        renderRows('calib_body', (d.calibration||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','bucket','n','avg_pred','avg_realized'], 'No predictions inside the window to bucket yet.');
        renderRows('exec_body', (d.execution_quality||[]).filter(r => basePicked.includes(r.model_name)), ['model_name','n','avg_slippage','avg_abs_slippage'], 'No recent fills to measure slippage against.');
        const cut=document.getElementById('sim_cutoff');
        if(cut){
          const runNote = d.recompute_in_progress ? ' | recompute in progress (charts temporarily partial)' : '';
          if(d.live_cutoff_utc){
            cut.textContent = `train/live cutoff: ${fmtNy(d.live_cutoff_utc)}${runNote}`;
          }else{
            cut.textContent = `cutoff not set${runNote}`;
          }
        }
        const lg=document.getElementById('sim_legend');
        if(lg){
          const known=selectedModels.filter(m => byModelRaw[m] && byModelRaw[m].length>0);
          lg.innerHTML = known.map((k,i)=>`<span style='color:${colors[k]}'><i style='border-top-style:${simDash(i)}'></i>${esc(k)}</span>`).join('');
        }
        try{
          const rr = await fetch('/model_research',{cache:'no-store'});
          if(rr.ok){
            const mr = await rr.json();
            const hdr=document.getElementById('mr_last_run');
            if(hdr){
              const s=mr.last_run_state||{};
              hdr.textContent = s.ran_at_utc ? `last run: ${fmtNy(s.ran_at_utc)} | cutoff: ${fmtNy(s.cutoff_utc)} | train ${s.train_rows||0} | eval ${s.eval_rows||0}` : 'no research run yet';
            }
            const bestBody=document.getElementById('mr_best_models_body');
            if(bestBody){
              bestBody.innerHTML = (mr.best_models||[]).map(x=>{
                const m=x.metrics||{};
                const p=JSON.stringify(x.params||{});
                const feats=(x.selected_features||[]).join(', ');
                return `<tr><td>${x.model_name}</td><td>${x.run_id}</td><td>${fmtNy(x.created_at_utc)}</td><td>${Number(x.objective_pnl_dollars||0).toFixed(2)}</td><td>${m.brier==null?'':Number(m.brier).toFixed(4)}</td><td>${m.logloss==null?'':Number(m.logloss).toFixed(4)}</td><td>${x.n_train}</td><td>${x.n_eval}</td><td><div class="cellwrap">${p}</div></td><td><div class="cellwrap">${feats}</div></td></tr>`;
              }).join('');
            }
            const fiBody=document.getElementById('mr_feature_importance_body');
            if(fiBody){
              const rows=[];
              for(const bm of (mr.best_models||[])){
                for(const f of (bm.feature_importance||[]).slice(0,10)){
                  rows.push(`<tr><td>${bm.model_name}</td><td>${bm.run_id}</td><td>${f.rank_order}</td><td>${f.feature_name}</td><td>${Number(f.importance_abs_mean||0).toFixed(6)}</td><td>${Number(f.importance_signed_mean||0).toFixed(6)}</td><td>${f.method||''}</td></tr>`);
                }
              }
              fiBody.innerHTML = rows.join('');
            }
            const recentBody=document.getElementById('mr_recent_runs_body');
            if(recentBody){
              recentBody.innerHTML = (mr.recent_runs||[]).map(r=>`<tr><td>${r.id}</td><td>${fmtNy(r.created_at_utc)}</td><td>${r.model_name}</td><td>${r.stage}</td><td>${Number(r.objective_pnl_dollars||0).toFixed(2)}</td><td>${r.n_train}</td><td>${r.n_eval}</td><td>${r.status}</td><td>${r.notes||''}</td></tr>`).join('');
            }
          }
        }catch(e){}
      }catch(e){
        setFetchError('sim-root', `Simulated-trading data unavailable: /sim_metrics request failed (${e}).`);
      }
    }
    const LIVE_SETTINGS_FIELDS = ['signal_threshold','edge_threshold','max_trade_cost','max_open_notional','max_concurrent_positions','max_daily_loss','max_total_drawdown'];
    const LIVE_FIELD_STEP = {signal_threshold:'0.01', edge_threshold:'0.001', max_trade_cost:'0.1', max_open_notional:'0.1', max_concurrent_positions:'1', max_daily_loss:'0.1', max_total_drawdown:'0.1'};
    async function refreshLiveMetrics(){
      const root=document.getElementById('live-root');
      if(!root) return;
      try{
        const lp = livePass();
        const r=await fetch('/live_metrics' + (lp?('?live_password='+encodeURIComponent(lp)):'') ,{cache:'no-store'});
        if(!r.ok){
          setFetchError('live-root', r.status===403
            ? 'Live panel locked. Append &live_password=... to the URL (or use the unlock link) to view live execution controls.'
            : `Live-trading data unavailable: /live_metrics returned HTTP ${r.status}. Strategy toggles, account status and charts stay empty until this is fixed - check the dashboard log on the server.`);
          return;
        }
        setFetchError('live-root', null);
        const d=await r.json();
        drawLineChart('live_equity_chart', {'live': d.equity_series_20s||[]}, 'equity', {'live':TRACE[0]}, {unit:'$'});
        drawLineChart('live_drawdown_chart', {'live': d.drawdown_series_20s||[]}, 'drawdown', {'live':TRACE[1]}, {unit:'$'});
        drawStackChart('live_stack_chart', d.stack_series_20s||[], 'cash', 'position');
        renderLiveOpenPositions(d.open_positions||[]);
        renderRows('live_orders_body', d.recent_orders||[], ['created_at_utc','market_ticker','action','side','qty_contracts','limit_price_dollars','status','kalshi_order_id','client_order_id'], 'No real order has been placed.');
        renderRows('live_trades_body', d.recent_trades||[], ['model_name','opened_at_utc','closed_at_utc','market_ticker','qty_contracts','entry_price','exit_price','pnl','status'], 'No live trade has closed yet.');
        const sc=document.getElementById('live_score');
        if(sc){
          const st=d.scorecard||{};
          const eq=(st.equity==null)?null:Number(st.equity);
          const pnl=money(st.total_pnl);
          const est=d.cash_source!=='kalshi_api';
          sc.innerHTML=
            `<div><span class="lab">Account cash</span>`+
              `<span class="fig" id="fig_cash">${eq==null?'n/a':'$'+eq.toFixed(2)}</span>`+
              `<div class="sub-fig">${est?'estimated &#8212; real balance unavailable':'from Kalshi'}</div></div>`+
            `<div><span class="lab">Realised, all time</span>`+
              `<span class="fig tint ${pnl.cls}">${pnl.txt}</span>`+
              `<div class="sub-fig">${Number(st.closed_trades||0)} closed &#183; ${st.win_rate==null?'n/a':pct(st.win_rate,1)} win</div></div>`+
            `<div><span class="lab">Exposure</span>`+
              `<span class="fig">${(d.open_positions||[]).length}</span>`+
              `<div class="sub-fig">open position${(d.open_positions||[]).length===1?'':'s'}</div></div>`+
            `<div><span class="lab">Risk state</span>`+
              `<span class="fig sm">${esc(d.risk_state||'n/a')}</span>`+
              `<div class="sub-fig">${esc(d.cash_source||'unknown')} feed</div></div>`;
          washIfChanged('live_cash', eq, document.getElementById('fig_cash'));
        }
        // ---- the dominant answer, in words, before any figure is read
        (function(){
          const models=d.models||{};
          const names=Object.keys(models);
          const on=names.filter(m=>models[m].live_enabled);
          const halted=names.filter(m=>models[m].paused);
          const opens=(d.open_positions||[]).length;
          const wPort=fresh(d.writers,'live_portfolio_20s');
          const wEng=fresh(d.writers,'live_engine');
          const wFwd=fresh(d.writers,'forward_quotes');
          const staleNames=[];
          if(wPort.stale) staleNames.push('balance');
          if(wEng.stale) staleNames.push('engine');
          if(wFwd.stale) staleNames.push('market feed');
          const red=String(d.risk_state||'').toUpperCase()==='RED';
          const parts=[];
          parts.push(on.length
            ? {text:on.length+' strateg'+(on.length===1?'y':'ies')+' live', alarm:true}
            : {text:'Live trading off'});
          parts.push({text: opens ? opens+' position'+(opens===1?'':'s')+' open' : 'No open positions',
                      alarm: opens>0});
          if(halted.length) parts.push({text:halted.length+' auto-halted', alarm:true});
          if(red) parts.push({text:'Risk red', alarm:true});
          parts.push(staleNames.length
            ? {text:staleNames.join(' + ')+' stale', alarm:true}
            : {text:'All writers current'});
          setStatusLine('live_status', parts, on.length>0 || staleNames.length>0 || red || halted.length>0);
          markSection('sect_live_account', wPort, 'the balance writer');
          markSection('sect_live_strat', wEng, 'the trading engine');
          markSection('sect_live_plates', wPort, 'the balance writer');
          headClock(d.generated_at_utc);
        })();
        const balanceNote = document.getElementById('live_balance_note');
        if(balanceNote){
          balanceNote.style.display = (d.cash_source==='kalshi_api') ? 'none' : 'block';
        }
        renderLiveStrategyCards(d.models||{}, d.settings||{});
      }catch(e){
        setFetchError('live-root', `Live-trading data unavailable: /live_metrics request failed (${e}).`);
      }
    }
    function renderLiveOpenPositions(rows){
      const el=document.getElementById('live_open_positions_body'); if(!el) return;
      if(!rows || rows.length===0){
        el.innerHTML='<tr class="empty-row"><td colspan="8">No live position is open. A strategy that is on will open one when its edge clears its threshold.</td></tr>';
        return;
      }
      el.innerHTML = rows.map(r => {
        const un=money(r.unrealized_pnl);
        return `<tr>
          <td class="name" data-lab="Strategy">${esc(r.model_name)}</td>
          <td class="tick" data-lab="Market">${esc(r.market_ticker)}</td>
          <td class="num" data-lab="Qty">${esc(r.qty_contracts)}</td>
          <td class="num" data-lab="Entry">$${Number(r.entry_price).toFixed(2)}</td>
          <td class="num" data-lab="Mark bid">$${Number(r.mark_bid).toFixed(2)}</td>
          <td class="num" data-lab="Unrealised"><span class="fig sm tint ${un.cls}">${un.txt}</span></td>
          <td data-lab="Opened">${esc(fmtNy(r.opened_at_utc))}</td>
          <td class="act" data-lab=""><button class="btn sm danger" data-arm-key="close:${esc(r.model_name)}:${esc(r.market_ticker)}" data-idle="Close" onclick="arm(this, 'Confirm close', ()=>closeLivePosition('${esc(r.model_name)}','${esc(r.market_ticker)}'))">Close</button></td>
        </tr>`;
      }).join('');
    }
    async function closeLivePosition(modelName, ticker){
      try{
        const lp = livePass();
        const r=await fetch('/live_position/close' + (lp?('?live_password='+encodeURIComponent(lp)):''),
          {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:modelName, market_ticker:ticker})});
        let j={};
        try{ j=await r.json(); }catch(e){}
        if(!r.ok || !j.ok){ setNotice('live-root', `Could not close ${ticker}: ${(j&&j.error)||('HTTP '+r.status)}. The position is still open.`, 'Close failed'); }
        else{ setNotice('live-root', `Close order submitted for ${ticker} at bid $${Number(j.close_bid||0).toFixed(2)}.`, 'Order sent'); }
      }catch(e){ setNotice('live-root', `Could not close ${ticker}: ${e}. The position is still open.`, 'Close failed'); }
      await refreshLiveMetrics();
    }
    // The strategies table re-renders every 10s so prob/edge stay live. That
    // used to blow away an open settings panel and anything half-typed in it,
    // which is the page moving under the operator's hands. Open state, edited
    // values and the caret are captured and restored around the re-render.
    // Only edits survive a re-render: an open panel or a focused field already
    // blocks the render, but a value typed and then clicked away from does not.
    var CFG_EDITED = {};
    document.addEventListener('input', function(e){
      const el = e.target;
      if(el && el.id && el.id.indexOf('ls_') === 0) CFG_EDITED[el.id] = el.value;
    });
    function renderLiveStrategyCards(models, settings){
      const body=document.getElementById('live_strat_body');
      if(!body) return;
      // Re-rendering under the operator's cursor used to swallow the click, so
      // this held the render whenever a caps drawer was open or a button armed.
      // That is why a strategy could be switched on and keep reading "Off":
      // the drawer below it was open, so the row never redrew. Render always,
      // and put back the three things a redraw would otherwise destroy - the
      // open drawers, the focused field, and a half-confirmed button.
      const openModels = Array.from(body.querySelectorAll('details[data-model][open]'))
        .map(d => d.dataset.model);
      const act = document.activeElement;
      const focusId = (act && act.id && body.contains(act)) ? act.id : null;
      body.innerHTML = LIVE_MODELS.map(m => {
        const st=models[m]||{}, cfg=settings[m]||{};
        const on=!!st.live_enabled, halted=!!st.paused;
        const state = halted ? '<span class="mk halt">Halted</span>'
                    : (on ? '<span class="mk armed">Live</span>' : '<span class="mk quiet">Off</span>');
        const livePnl=money(st.total_pnl);
        const simPnl=money(st.sim_total_pnl);
        const sig = st.signal==null ? 'n/a' : (st.signal ? 'yes' : 'no');
        const toggle = `<button class="btn sm${on?' danger':''}" data-arm-key="toggle:${esc(m)}" data-idle="${on?'Turn off':'Turn on'}" onclick="arm(this, ${on?"'Confirm off'":"'Confirm live'"}, ()=>toggleLiveModel('${esc(m)}', ${!on}))">${on?'Turn off':'Turn on'}</button>`;
        const resume = halted ? `<button class="btn sm" onclick="resumeLiveModel('${esc(m)}')">Clear halt</button>` : '';
        const why = halted && st.paused_reason ? `<div class="sub-fig">${esc(st.paused_reason)}</div>` : '';
        const fields = LIVE_SETTINGS_FIELDS.map(f =>
          `<label class="field"><span class="lab">${esc(labelOf(f))}</span>`+
          `<input id="ls_${esc(m)}_${esc(f)}" type="number" step="${LIVE_FIELD_STEP[f]}" min="0" value="${cfg[f]==null?'':esc(cfg[f])}"></label>`
        ).join('');
        return `<tr>
            <td class="name" data-lab="Strategy"><a href="/?tab=strategy&amp;name=${encodeURIComponent(m)}">${esc(m)}</a>${why}</td>
            <td data-lab="State">${state}</td>
            <td class="num" data-lab="Live P&amp;L"><span class="fig sm tint ${livePnl.cls}">${livePnl.txt}</span>
              <div class="sub-fig">${Number(st.closed_trades||0)} trades</div></td>
            <td class="num" data-lab="Paper P&amp;L"><span class="fig sm tint ${simPnl.cls}">${simPnl.txt}</span>
              <div class="sub-fig">${Number(st.sim_closed_trades||0).toLocaleString()} trades &#183; ${st.sim_win_rate==null?'n/a':pct(st.sim_win_rate)} win</div></td>
            <td class="num phone-hide" data-lab="Probability">${st.prob==null?'n/a':Number(st.prob).toFixed(3)}</td>
            <td class="num phone-hide" data-lab="Edge">${st.edge==null?'n/a':Number(st.edge).toFixed(3)}</td>
            <td class="phone-hide" data-lab="Signal">${sig}</td>
            <td class="act" data-lab="">${toggle} ${resume}</td>
          </tr>
          <tr class="cfg">
            <td colspan="8" style="padding-top:0">
              <details data-model="${esc(m)}">
                <summary>Risk caps and thresholds for ${esc(m)}</summary>
                <div style="display:flex;flex-wrap:wrap;gap:12px;padding:10px 0 12px">${fields}
                  <label class="field"><span class="lab">&nbsp;</span>
                    <button class="btn sm" onclick="saveLiveModelSettings('${esc(m)}')">Save caps</button></label>
                </div>
              </details>
            </td>
          </tr>`;
      }).join('');
      for(const id in CFG_EDITED){
        const el = document.getElementById(id);
        if(el) el.value = CFG_EDITED[id];
      }
      for(const m of openModels){
        const d = body.querySelector(`details[data-model="${m}"]`);
        if(d) d.open = true;
      }
      if(focusId){
        const el = document.getElementById(focusId);
        if(el && el !== document.activeElement) el.focus();
      }
      if(ARMED){
        const b = body.querySelector(`[data-arm-key="${ARMED.key}"]`);
        if(b){ b.textContent = ARMED.label; b.classList.add('armed'); }
        else { disarm(); }
      }
    }
    async function toggleLiveModel(modelName, turnOn){
      try{
        const lp = livePass();
        const r = await fetch('/live_model/toggle' + (lp?('?live_password='+encodeURIComponent(lp)):''), {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({model_name: modelName, live_enabled: turnOn})
        });
        let j={}; try{ j=await r.json(); }catch(e){}
        if(!r.ok || !j.ok){ setNotice('live-root', `Could not switch ${modelName}: ${(j&&j.error)||('HTTP '+r.status)}. Its state is unchanged.`, 'Switch failed'); }
        else{ setNotice('live-root', turnOn
          ? `${modelName} is live. It can place real orders on its next tick.`
          : `${modelName} is off. It will not open new positions.`, turnOn ? 'Now live' : 'Switched off'); }
      }catch(e){ setNotice('live-root', `Could not switch ${modelName}: ${e}. Its state is unchanged.`, 'Switch failed'); }
      await refreshLiveMetrics();
    }
    async function resumeLiveModel(modelName){
      try{
        const lp = livePass();
        const r = await fetch('/live_model/resume' + (lp?('?live_password='+encodeURIComponent(lp)):''), {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({model_name: modelName})
        });
        let j={}; try{ j=await r.json(); }catch(e){}
        if(!r.ok || !j.ok){ setNotice('live-root', `Could not clear the halt on ${modelName}: ${(j&&j.error)||('HTTP '+r.status)}.`, 'Clear failed'); }
        else{ setNotice('live-root', `Halt cleared on ${modelName}. Its switch still governs whether it trades.`, 'Halt cleared'); }
      }catch(e){ setNotice('live-root', `Could not clear the halt on ${modelName}: ${e}.`, 'Clear failed'); }
      await refreshLiveMetrics();
    }
    async function saveLiveModelSettings(modelName){
      const patch = {};
      for(const f of LIVE_SETTINGS_FIELDS){
        const el = document.getElementById(`ls_${modelName}_${f}`);
        if(el && el.value !== '') patch[f] = Number(el.value);
      }
      try{
        const lp = livePass();
        const r = await fetch('/live_settings' + (lp?('?live_password='+encodeURIComponent(lp)):''), {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({model_name: modelName, ...patch})
        });
        let j={}; try{ j=await r.json(); }catch(e){}
        if(!r.ok || !j.ok){ setNotice('live-root', `Could not save caps for ${modelName}: ${(j&&j.error)||('HTTP '+r.status)}.`, 'Save failed'); }
        else{
          for(const f of LIVE_SETTINGS_FIELDS) delete CFG_EDITED['ls_' + modelName + '_' + f];
          setNotice('live-root', `Caps saved for ${modelName}. They apply on its next tick.`, 'Saved');
        }
      }catch(e){ setNotice('live-root', `Could not save caps for ${modelName}: ${e}.`, 'Save failed'); }
      await refreshLiveMetrics();
    }
    async function refreshHealth(){
      try{
        const r = await fetch('/health', {cache:'no-store'});
        if(!r.ok) return;
        const d = await r.json();
        if(d.counts){
          for(const [k,v] of Object.entries(d.counts)){
            const el = document.querySelector(`[data-count-key="${k}"]`);
            if(el) el.textContent = Number(v).toLocaleString();
          }
        }
        headClock();
        if(d.writers){
          const wf=fresh(d.writers,'forward_quotes');
          const wm=fresh(d.writers,'model_features_1m');
          markSection('sect_pipe_feed', wf, 'the forward collector');
          markSection('sect_pipe_guard', wm, 'the feature builder');
        }
        const latest = document.getElementById('latest-forward');
        if(latest && d.latest_forward){
          latest.textContent = `last forward: ${fmtNy(d.latest_forward.snapshot_time_utc)} | ${d.latest_forward.market_ticker} | ${d.latest_forward.status}`;
        }
        if(d.forward_health){
          const fh = d.forward_health;
          const bind = (id,val) => { const el=document.getElementById(id); if(el) el.textContent=val; };
          bind('fh_rows_total', Number(fh.rows_total).toLocaleString());
          bind('fh_rows_real', Number(fh.rows_real).toLocaleString());
          bind('fh_na_rate', `${fh.na_rate_pct}%`);
          bind('fh_gaps', Number(fh.gaps_missing_slots).toLocaleString());
          bind('fh_misaligned', Number(fh.misaligned_rows).toLocaleString());
          bind('fh_last', fh.last_snapshot_time ? fmtNy(fh.last_snapshot_time) : 'N/A');
        }
      }catch(e){}
    }
    var RESIZE_T=null;
    window.addEventListener('resize', ()=>{
      clearTimeout(RESIZE_T);
      RESIZE_T=setTimeout(()=>{ refreshSimMetrics(); refreshLiveMetrics(); }, 180);
    });
    setInterval(refreshHealth, 10000);
    setInterval(refreshSimMetrics, 10000);
    setInterval(refreshLiveMetrics, 10000);
    window.addEventListener('load', ()=>{ refreshHealth(); refreshSimMetrics(); refreshLiveMetrics(); });
    """
    services = (
        ("live", "/?tab=live-trading", "Live"),
        ("sim", "/?tab=simulated-trading", "Simulated"),
        ("pipeline", "/?tab=data-pipeline", "Pipeline"),
    )
    nav = "".join(
        f'<a class="svc-link" href="{href}"'
        + (' aria-current="page"' if key == service else "")
        + f">{label}</a>"
        for key, href, label in services
    )
    svc_label = {
        "live": "Live execution",
        "sim": "Simulation",
        "pipeline": "Data pipeline",
        "table": "Records",
    }.get(service, "Records")
    body_class = "live-service" if service == "live" else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{html.escape(title)}</title><style>{css}</style></head>
<body class="{body_class}">
<header class="masthead"><div class="masthead-in">
  <p class="wordmark">Kalshi&nbsp;BTC&nbsp;15M<span class="sep">/</span><span class="svc">{svc_label}</span></p>
  <p class="asof" id="head_asof">reading&#8230;</p>
</div></header>
<nav class="services" aria-label="Services"><div class="services-in">{nav}</div></nav>
<main class="wrap">{body_html}</main>
<script>{js}</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _authorized(self) -> bool:
        if not AUTH_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            user, pw = raw.split(":", 1)
            return secrets.compare_digest(user, AUTH_USER) and secrets.compare_digest(pw, AUTH_PASSWORD)
        except Exception:
            return False

    def _send_unauthorized(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Kalshi Dashboard"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Unauthorized")

    def _send(self, body: str, code: int = 200, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def _cookie_map(self):
        raw = self.headers.get("Cookie", "")
        out = {}
        for part in raw.split(";"):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        return out

    def _monitor_authorized(self, parsed) -> bool:
        """True only for a GET of a status endpoint carrying the monitor token."""
        if not MONITOR_TOKEN or self.command != "GET":
            return False
        if parsed.path not in MONITOR_PATHS:
            return False
        token = parse_qs(parsed.query).get("monitor_token", [""])[0]
        return bool(token) and secrets.compare_digest(token, MONITOR_TOKEN)

    def _live_authorized(self, parsed=None) -> bool:
        if parsed is not None and self._monitor_authorized(parsed):
            return True
        if not LIVE_TRADING_PASSWORD:
            return False  # fail closed: no configured password means no live controls
        cookie = self._cookie_map().get(LIVE_COOKIE_NAME, "")
        if cookie and secrets.compare_digest(
            cookie.encode("utf-8"), live_cookie_token(LIVE_TRADING_PASSWORD).encode("utf-8")
        ):
            return True
        if parsed is not None:
            qs = parse_qs(parsed.query)
            if live_password_ok(qs.get("live_password", [""])[0]):
                return True
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        if not self._authorized() and not self._monitor_authorized(parsed):
            self._send_unauthorized()
            return

        if parsed.path == "/model_research":
            payload = model_research_summary()
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/live_unlock":
            qs = parse_qs(parsed.query)
            pw = qs.get("password", [""])[0]
            if not LIVE_TRADING_PASSWORD:
                self._send("Live trading is locked: LIVE_TRADING_PASSWORD is not set on this server.", 403)
                return
            if live_password_ok(pw):
                token = live_cookie_token(LIVE_TRADING_PASSWORD)
                self.send_response(302)
                self.send_header(
                    "Set-Cookie", f"{LIVE_COOKIE_NAME}={token}; Path=/; Max-Age=86400; HttpOnly; SameSite=Lax"
                )
                self.send_header("Location", "/?tab=live-trading")
                self.end_headers()
                return
            self._send("Live trading password invalid.", 403)
            return

        if parsed.path == "/":
            qs = parse_qs(parsed.query)
            # Live execution is the front page: the operator's first question is
            # "what is it doing with real money right now", not "how is ingestion".
            tab = qs.get("tab", ["live-trading"])[0]

            if tab == "strategy":
                name = qs.get("name", [""])[0]
                dossier = STRATEGY_DOSSIER.get(name)
                if not dossier:
                    body = (
                        "<h1 class='page'>Unknown strategy</h1>"
                        "<p class='deck'>No dossier exists for that name. "
                        "<a href='/?tab=simulated-trading'>Back to the books</a>.</p>"
                    )
                    self._send(render_page("Unknown strategy", body, "sim"))
                    return
                lifecycle = "".join(
                    f"<tr><td class='name' data-lab='Stage'>{html.escape(t)}</td>"
                    f"<td data-lab='Rule'><div class='cellwrap'>{html.escape(d)}</div></td></tr>"
                    for t, d in SHARED_LIFECYCLE
                )
                body = f"""
                <p class="deck" style="margin-top:22px">
                  <a href="/?tab=simulated-trading" style="color:inherit">Books</a> &#8594;
                  {html.escape(dossier['kind'])}</p>
                <h1 class="page" style="margin-top:2px">{html.escape(name)}</h1>
                <div id="sim-root" class="reading" data-strategy="{html.escape(name)}">

                <section class="sect" id="sect_strat_record" style="margin-top:20px">
                  <div class="sect-head"><h2>Its record</h2><p class="sect-note">reading&#8230;</p></div>
                  <div class="measure" id="strat_record"></div>
                  <p class="legend" id="strat_verdict"></p>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Thesis</h2></div>
                  <p class="prose" style="margin:12px 0 0">{html.escape(dossier['thesis'])}</p>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>What it reads</h2></div>
                  <p class="prose" style="margin:12px 0 0">{html.escape(dossier['reads'])}</p>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>How it decides</h2></div>
                  <p class="prose" style="margin:12px 0 0">{html.escape(dossier['decides'])}</p>
                  <p class="lab" style="margin:18px 0 0">{html.escape(dossier['formula_caption'])}</p>
                  <div class="plate-eq">{dossier['formula']}</div>
                  <p class="lab" style="margin:18px 0 0">The probability step, in pseudocode</p>
                  <pre class="code">{_comment(dossier['pseudo'])}</pre>
                  <p class="lab" style="margin:18px 0 0">Edge, the number every entry is gated on</p>
                  <div class="plate-eq">{EDGE_MATH}</div>
                  <p class="legend">Edge is the strategy's claim about how mispriced the contract is
                  right now: its own probability minus what the market is asking.</p>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>One tick, end to end</h2>
                    <p class="sect-note">every minute at :10</p></div>
                  <pre class="code">{_comment(SHARED_TICK_PSEUDO)}</pre>
                  <p class="lab" style="margin:18px 0 0">Sizing on the live path is not this arithmetic</p>
                  <pre class="code">{_comment(LIVE_SIZING_PSEUDO)}</pre>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>What you should hold against it</h2></div>
                  <p class="prose" style="margin:12px 0 0">{html.escape(dossier['caveat'])}</p>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>The question every fitted book is asked</h2></div>
                  <p class="prose" style="margin:12px 0 0">{html.escape(SHARED_LABEL)}</p>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Lifecycle, shared by every book</h2></div>
                  <div class="sheet"><table class="stack"><colgroup><col style="width:22%"><col></colgroup>
                    <thead><tr><th>Stage</th><th>Rule</th></tr></thead>
                    <tbody>{lifecycle}</tbody></table></div>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Record by period</h2><p class="sect-note" id="sim_basis"></p></div>
                  <div class="sheet"><table class="stack t-period">
                    <colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"><col class="c6"><col class="c7"><col class="c8"></colgroup>
                    <thead><tr><th>Strategy</th><th>Period</th><th class="num">P&amp;L</th><th class="num">Closed</th>
                    <th class="num">Win</th><th class="num">Predictions</th><th class="num">Brier</th>
                    <th class="num">Log loss</th></tr></thead>
                    <tbody id="sim_segments_body"></tbody>
                  </table></div>
                  <p class="legend">Lower Brier and log loss are better; both judge the probability,
                  not the trade. <span id="sim_cutoff"></span></p>
                </section>
                </div>
                """
                self._send(render_page(name, body, "sim"))
                return

            if tab == "simulated-trading":
                body = f"""
                <h1 class="page">Simulation</h1>
                <p class="deck">Five paper books, each funded with its own $100. Models are frozen at the
                live cutoff, so out-of-sample is the only honest read.</p>
                <div id="sim-root">
                <div class="statusline" id="sim_status">{STATUS_MARK_SVG}<div class="said">reading&#8230;</div></div>

                <section class="sect" id="sect_sim_books">
                  <div class="sect-head"><h2>Books</h2><p class="sect-note">reading&#8230;</p></div>
                  <div class="sheet"><table class="stack t-books">
                    <colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"><col class="c6"><col class="c7"></colgroup>
                    <thead><tr><th>Strategy</th><th class="num">Equity</th><th class="num">Total P&amp;L</th>
                    <th class="num">Trades</th><th class="num">Win</th><th>State</th><th></th></tr></thead>
                    <tbody id="pm_body"></tbody>
                  </table></div>
                  <div class="legend" id="pm_legend"></div>
                </section>

                <section class="sect" id="sect_sim_segments">
                  <div class="sect-head"><h2>Record by period</h2><p class="sect-note" id="sim_basis"></p></div>
                  <div class="sheet"><table class="stack t-period">
                    <colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"><col class="c6"><col class="c7"><col class="c8"></colgroup>
                    <thead><tr><th>Strategy</th><th>Period</th><th class="num">P&amp;L</th><th class="num">Closed</th>
                    <th class="num">Win</th><th class="num">Predictions</th><th class="num">Brier</th>
                    <th class="num">Log loss</th></tr></thead>
                    <tbody id="sim_segments_body"></tbody>
                  </table></div>
                  <p class="legend">Lower Brier and log loss are better; both judge the probability, not the
                  trade. <span id="sim_cutoff"></span></p>
                </section>

                <section class="sect" id="sect_sim_plates">
                  <div class="sect-head"><h2>Equity, each book rebased to $100</h2><p class="sect-note">reading&#8230;</p></div>
                  <div class="keys" id="sim_legend"></div>
                  <div class="plates">
                  <div class="plate">
                    <p class="lab">In-sample <span id="range_in_sample"></span></p>
                    <canvas id="equity_chart_in_sample" data-h="200"></canvas>
                  </div>
                  <div class="plate">
                    <p class="lab">Out-of-sample <span id="range_out_sample"></span></p>
                    <canvas id="equity_chart_out_sample" data-h="200"></canvas>
                  </div>
                  <div class="plate">
                    <p class="lab">Cash against position value <span class="sect-note" id="sim_stack_model"></span></p>
                    <canvas id="stack_chart" data-h="170"></canvas>
                  </div>
                  <div class="plate">
                    <p class="lab">Drawdown from peak <span class="sect-note" id="sim_drawdown_model"></span></p>
                    <canvas id="drawdown_chart" data-h="150"></canvas>
                  </div>
                  </div>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Open paper positions</h2></div>
                  <div class="sheet"><table class="stack t-pos7"><colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"><col class="c6"><col class="c7"></colgroup><thead><tr><th>Strategy</th><th>Market</th>
                  <th class="num">Qty</th><th class="num">Entry</th><th class="num">Mark bid</th>
                  <th class="num">Unrealised</th><th>Opened</th></tr></thead>
                  <tbody id="open_positions_body"></tbody></table></div>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Recent paper trades</h2></div>
                  <div class="sheet"><table><thead><tr><th class="num">#</th><th>Strategy</th><th>Market</th>
                  <th>Opened</th><th>Closed</th><th class="num">Qty</th><th class="num">Entry</th>
                  <th class="num">Exit</th><th class="num">P&amp;L</th><th>Status</th><th class="num">Expected</th>
                  <th class="num">Slippage</th><th>Fill</th></tr></thead>
                  <tbody id="trades_body"></tbody></table></div>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Calibration</h2><p class="sect-note">predicted against realised</p></div>
                  <div class="sheet"><table class="stack"><thead><tr><th>Strategy</th><th>Bucket</th>
                  <th class="num">n</th><th class="num">Predicted</th><th class="num">Realised</th></tr></thead>
                  <tbody id="calib_body"></tbody></table></div>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Execution quality</h2><p class="sect-note">fill against expected entry</p></div>
                  <div class="sheet"><table class="stack"><thead><tr><th>Strategy</th><th class="num">n</th>
                  <th class="num">Avg slippage</th><th class="num">Avg absolute</th></tr></thead>
                  <tbody id="exec_body"></tbody></table></div>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Research runs</h2><p class="sect-note" id="mr_last_run">reading&#8230;</p></div>
                  <div class="sheet"><table><thead><tr><th>Strategy</th><th class="num">Run</th><th>Created</th>
                  <th class="num">Objective P&amp;L</th><th class="num">Brier</th><th class="num">Log loss</th>
                  <th class="num">Train</th><th class="num">Eval</th><th>Parameters</th><th>Features</th></tr></thead>
                  <tbody id="mr_best_models_body"></tbody></table></div>
                  <details style="margin-top:10px"><summary>Feature importance and full run history</summary>
                    <div class="sheet" style="margin-top:8px"><table><thead><tr><th>Strategy</th><th class="num">Run</th>
                    <th class="num">Rank</th><th>Feature</th><th class="num">Importance</th>
                    <th class="num">Signed</th><th>Method</th></tr></thead>
                    <tbody id="mr_feature_importance_body"></tbody></table></div>
                    <div class="sheet" style="margin-top:14px"><table><thead><tr><th class="num">#</th><th>Created</th>
                    <th>Strategy</th><th>Stage</th><th class="num">Objective</th><th class="num">Train</th>
                    <th class="num">Eval</th><th>Status</th><th>Notes</th></tr></thead>
                    <tbody id="mr_recent_runs_body"></tbody></table></div>
                  </details>
                </section>
                </div>
                """
                self._send(render_page("Simulation", body, "sim"))
                return

            if tab == "live-trading":
                if not self._live_authorized(parsed):
                    body = f"""
                    <h1 class="page">Live execution is locked</h1>
                    <p class="deck">This surface can place real orders. It takes a second password.</p>
                    <form method="GET" action="/" style="display:flex;gap:10px;align-items:flex-end;
                      flex-wrap:wrap;max-width:460px;margin-top:22px">
                      <input type="hidden" name="tab" value="live-trading">
                      <label class="field" style="flex:1"><span class="lab">Live trading password</span>
                        <input type="password" name="live_password" autocomplete="current-password" autofocus></label>
                      <button class="btn" type="submit">Unlock</button>
                    </form>
                    <p class="legend" style="max-width:460px">Simulation and pipeline stay readable without it.</p>
                    """
                    self._send(render_page("Live execution locked", body, "live"))
                    return
                body = f"""
                <h1 class="page">Live execution</h1>
                <p class="deck">Real money. Every strategy carries its own switch, its own caps, and halts
                itself on breach.</p>
                <div id="live-root">
                <div class="statusline" id="live_status">{STATUS_MARK_SVG}<div class="said">reading&#8230;</div></div>

                <section class="sect" id="sect_live_account">
                  <div class="sect-head"><h2>Account</h2><p class="sect-note">reading&#8230;</p></div>
                  <div class="measure" id="live_score"></div>
                </section>

                <div id="live_balance_note" class="notice" style="display:none">
                  <h3>Balance is an estimate</h3>
                  <p style="margin:0">Kalshi API credentials are not configured on this server, so the cash
                  above is starting capital plus tracked P&amp;L, not your real balance. Real order placement
                  will also fail until they are configured. Monitoring and switches are unaffected.</p>
                </div>

                <section class="sect" id="sect_live_strat">
                  <div class="sect-head"><h2>Strategies</h2><p class="sect-note">reading&#8230;</p></div>
                  <div id="strat_notice"></div>
                  <div class="sheet"><table class="stack t-strat">
                    <colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"><col class="c6"><col class="c7"><col class="c8"></colgroup>
                    <thead><tr><th>Strategy</th><th>State</th><th class="num">Live P&amp;L</th>
                    <th class="num">Paper P&amp;L</th><th class="num">Probability</th><th class="num">Edge</th>
                    <th>Signal</th><th></th></tr></thead>
                    <tbody id="live_strat_body"></tbody>
                  </table></div>
                  <p class="legend">A strategy opens a position when its probability clears the signal
                  threshold and its edge clears the edge threshold. Paper P&amp;L is the same strategy's
                  simulated record, for comparison.</p>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Open positions</h2></div>
                  <div class="sheet"><table class="stack t-pos8"><colgroup><col class="c1"><col class="c2"><col class="c3"><col class="c4"><col class="c5"><col class="c6"><col class="c7"><col class="c8"></colgroup><thead><tr><th>Strategy</th><th>Market</th>
                  <th class="num">Qty</th><th class="num">Entry</th><th class="num">Mark bid</th>
                  <th class="num">Unrealised</th><th>Opened</th><th></th></tr></thead>
                  <tbody id="live_open_positions_body"></tbody></table></div>
                </section>

                <section class="sect" id="sect_live_plates">
                  <div class="sect-head"><h2>Account over time</h2><p class="sect-note">reading&#8230;</p></div>
                  <div class="plates">
                  <div class="plate">
                    <p class="lab">Equity, 20-second marks</p>
                    <canvas id="live_equity_chart" data-h="210"></canvas>
                  </div>
                  <div class="plate">
                    <p class="lab">Cash against position value</p>
                    <canvas id="live_stack_chart" data-h="170"></canvas>
                    <div class="keys"><span><i></i>Cash</span>
                      <span style="color:#7A5C2E"><i style="border-top-style:dashed"></i>Position value</span></div>
                  </div>
                  <div class="plate">
                    <p class="lab">Drawdown from peak</p>
                    <canvas id="live_drawdown_chart" data-h="150"></canvas>
                  </div>
                  </div>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Orders</h2></div>
                  <div class="sheet"><table><thead><tr><th>Time</th><th>Market</th><th>Action</th><th>Side</th>
                  <th class="num">Qty</th><th class="num">Limit</th><th>Status</th><th>Order id</th>
                  <th>Client id</th></tr></thead><tbody id="live_orders_body"></tbody></table></div>
                </section>

                <section class="sect">
                  <div class="sect-head"><h2>Closed trades</h2></div>
                  <div class="sheet"><table><thead><tr><th>Strategy</th><th>Opened</th><th>Closed</th>
                  <th>Market</th><th class="num">Qty</th><th class="num">Entry</th><th class="num">Exit</th>
                  <th class="num">P&amp;L</th><th>Status</th></tr></thead>
                  <tbody id="live_trades_body"></tbody></table></div>
                </section>
                </div>
                """
                self._send(render_page("Live execution", body, "live"))
                return

            counts = table_counts()
            latest = latest_forward_status()
            fh = forward_feed_health()
            mg = latest_model_guard()
            rows = "".join(
                [
                    f'<tr><td class="name"><a href="/table?name={t}" style="color:inherit">{html.escape(t)}</a></td>'
                    f'<td class="num" data-count-key="{html.escape(t)}">{counts.get(t,0):,}</td></tr>'
                    for t in TABLES
                ]
            )
            latest_text = (
                f"{latest['market_ticker']} &#183; {latest['status']}"
                if latest
                else "no forward snapshots yet"
            )
            guard = mg or {}
            body = f"""
            <h1 class="page">Data pipeline</h1>
            <p class="deck">Everything downstream is only as honest as this. Ingestion for markets,
            candles, forward snapshots and one-minute features.</p>

            <section class="sect" id="sect_pipe_feed">
              <div class="sect-head"><h2>Forward feed</h2>
                <p class="sect-note">reading&#8230;</p></div>
              <div class="measure">
                <div><span class="lab">Rows total</span><span class="fig" id="fh_rows_total">{fh['rows_total']:,}</span></div>
                <div><span class="lab">Rows real</span><span class="fig" id="fh_rows_real">{fh['rows_real']:,}</span></div>
                <div><span class="lab">N/A rate</span><span class="fig" id="fh_na_rate">{fh['na_rate_pct']}%</span></div>
                <div><span class="lab">Missing 20s slots</span><span class="fig" id="fh_gaps">{fh['gaps_missing_slots']:,}</span></div>
                <div><span class="lab">Misaligned</span><span class="fig" id="fh_misaligned">{fh['misaligned_rows']:,}</span></div>
              </div>
              <p class="legend">Counted over the last {fh['window_minutes']} minutes.
                Newest snapshot <b id="fh_last">{fh['last_snapshot_time'] or 'none'}</b>
                &#183; <span id="latest-forward">{latest_text}</span></p>
            </section>

            <section class="sect" id="sect_pipe_guard">
              <div class="sect-head"><h2>Model data guard</h2>
                <p class="sect-note">reading&#8230;</p></div>
              <div class="measure">
                <div><span class="lab">Guard</span><span class="fig sm">{html.escape(str(guard.get('guard_status','n/a')))}</span></div>
                <div><span class="lab">Model eligible</span><span class="fig sm">{html.escape(str(guard.get('model_eligible','n/a')))}</span></div>
                <div><span class="lab">Minute</span><span class="fig sm">{html.escape(str(guard.get('snapshot_minute_utc','n/a')))}</span></div>
                <div><span class="lab">Market</span><span class="fig sm">{html.escape(str(guard.get('market_ticker','n/a')))}</span></div>
              </div>
              <p class="legend">Eligibility of the most recent minute for model input.</p>
            </section>

            <section class="sect">
              <div class="sect-head"><h2>Records</h2><p class="sect-note">row counts</p></div>
              <div class="sheet"><table class="stack"><thead><tr><th>Table</th>
                <th class="num">Rows</th></tr></thead><tbody>{rows}</tbody></table></div>
            </section>
            """
            self._send(render_page("Data pipeline", body, "pipeline"))
            return

        if parsed.path == "/health":
            counts = table_counts()
            latest = latest_forward_status()
            fh = forward_feed_health()
            mg = latest_model_guard()
            ss = sim_health_summary()
            writers = pipeline_writer_freshness()
            if latest and latest.get("snapshot_time_utc"):
                latest["snapshot_time_utc"] = str(latest["snapshot_time_utc"])
            if mg and mg.get("snapshot_minute_utc"):
                mg["snapshot_minute_utc"] = str(mg["snapshot_minute_utc"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "ok": True,
                        "counts": counts,
                        "latest_forward": latest,
                        "forward_health": fh,
                        "model_guard": mg,
                        "sim_summary": ss,
                        "writers": writers,
                    }
                ).encode("utf-8")
            )
            return

        if parsed.path == "/api/tables":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "tables": API_TABLES,
                        "time_columns": API_TIME_COLUMN,
                        "max_limit": API_MAX_LIMIT,
                    }
                ).encode("utf-8")
            )
            return

        if parsed.path == "/api/table":
            qs = parse_qs(parsed.query)
            name = qs.get("name", [""])[0]
            offset = int(qs.get("offset", ["0"])[0])
            limit = int(qs.get("limit", ["1000"])[0])
            start = qs.get("start", [None])[0]
            end = qs.get("end", [None])[0]
            cols_raw = qs.get("columns", [""])[0]
            columns = [c.strip() for c in cols_raw.split(",") if c.strip()] if cols_raw else None
            try:
                payload = query_api_rows(
                    table=name,
                    offset=offset,
                    limit=limit,
                    start=start,
                    end=end,
                    columns=columns,
                )
                self.send_response(200)
            except Exception as e:
                payload = {"ok": False, "error": str(e)}
                self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, default=str).encode("utf-8"))
            return

        if parsed.path == "/sim_metrics":
            qs = parse_qs(parsed.query)
            window_hours = _parse_window_hours(qs, 6)
            data = sim_metrics(window_hours=window_hours)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if parsed.path == "/live_metrics":
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            qs = parse_qs(parsed.query)
            window_hours = _parse_window_hours(qs, 12)
            data = live_metrics(window_hours=window_hours)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if parsed.path == "/table":
            qs = parse_qs(parsed.query)
            name = qs.get("name", [""])[0]
            page = int(qs.get("page", ["1"])[0])
            if name not in TABLES:
                self._send("invalid table", 400)
                return
            total, rows = query_rows(name, page)
            cols = list(rows[0].keys()) if rows else []
            header = "".join([f"<th>{html.escape(str(c))}</th>" for c in cols])
            body_rows = []
            for r in rows:
                num_attr = " class='num'"
                tds = "".join(
                    [
                        "<td"
                        + (num_attr if isinstance(r[c], (int, float)) else "")
                        + ">"
                        + html.escape(str(r[c]))
                        + "</td>"
                        for c in cols
                    ]
                )
                body_rows.append(f"<tr>{tds}</tr>")
            prev_dis = " aria-disabled='true' tabindex='-1'" if page <= 1 else ""
            prev_link = (
                f"<a class='btn sm'{prev_dis} href='/table?name={name}&page={max(1,page-1)}'>Previous</a>"
            )
            next_link = f"<a class='btn sm' href='/table?name={name}&page={page+1}'>Next</a>"
            empty = (
                "<tr class='empty-row'><td>This page is past the end of the table.</td></tr>"
                if not rows
                else ""
            )
            body = (
                f"<h1 class='page'>{html.escape(name)}</h1>"
                f"<p class='deck'>{total:,} rows, {PAGE_SIZE} to a page. "
                f"<a href='/?tab=data-pipeline' style='color:inherit'>Back to the pipeline</a>.</p>"
                f"<section class='sect'>"
                f"<div class='sect-head'><h2>Page {page}</h2>"
                f"<p class='sect-note'>rows {min(total, (page-1)*PAGE_SIZE + 1):,}"
                f"&#8211;{min(total, page*PAGE_SIZE):,}</p></div>"
                f"<div class='sheet' style='max-height:72vh'><table><thead><tr>{header}</tr></thead>"
                f"<tbody>{''.join(body_rows) or empty}</tbody></table></div>"
                f"<div class='pager'>{prev_link} {next_link}</div>"
                f"</section>"
            )
            self._send(render_page(f"Table {name}", body, "table"))
            return

        self._send("not found", 404)

    def do_POST(self):
        # One place, so no future POST route can forget it.
        try:
            self._handle_post()
        finally:
            invalidate_metrics_cache()

    def _handle_post(self):
        if not self._authorized():
            self._send_unauthorized()
            return
        parsed = urlparse(self.path)
        if parsed.path == "/live_settings":
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model_name = str(payload.pop("model_name", "") or "").strip()
                if model_name not in LIVE_MODELS:
                    raise ValueError(f"model_name must be one of {LIVE_MODELS}")
                cfg = live_settings_update(model_name, payload)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "settings": cfg}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        if parsed.path == "/live_model/toggle":
            # The ON/OFF switch a human clicks per strategy. Never called by
            # any automated code path in this codebase - only from the
            # dashboard button, gated by the live password.
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model_name = str(payload.get("model_name") or "").strip()
                if model_name not in LIVE_MODELS:
                    raise ValueError(f"model_name must be one of {LIVE_MODELS}")
                live_enabled = bool(payload.get("live_enabled"))
                cfg = live_settings_update(model_name, {"live_enabled": live_enabled})
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "settings": cfg}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        if parsed.path == "/live_model/resume":
            # Clears an auto-triggered risk-breach pause. Does not turn the
            # strategy ON by itself - live_enabled is unaffected.
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model_name = str(payload.get("model_name") or "").strip()
                if model_name not in LIVE_MODELS:
                    raise ValueError(f"model_name must be one of {LIVE_MODELS}")
                conn = get_db_conn()
                with conn.cursor() as cur:
                    clear_live_model_paused(cur, model_name, utc_now())
                conn.commit()
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        if parsed.path == "/live_position/close":
            # Manually close one existing live position. This is a real,
            # human-clicked action - the account owner reviews and clicks,
            # this handler never fires on its own. Gated by the same live
            # password as /live_settings.
            if not self._live_authorized(parsed):
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": "live_locked"}).encode("utf-8"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                ticker = str(payload.get("market_ticker") or "").strip()
                model_name = str(payload.get("model_name") or "").strip()
                if not ticker:
                    raise ValueError("market_ticker is required")
                if not model_name:
                    raise ValueError("model_name is required")
                bid = latest_bid_for_ticker(ticker)
                if bid is None or bid <= 0:
                    raise ValueError(f"no valid current bid available for {ticker} - refusing to close blind")
                conn = get_db_conn()
                with conn.cursor() as cur:
                    # Sized to what Kalshi holds, not the row: a manual close of a
                    # phantom/stale position must not open a short.
                    kernel = DummyExecutionKernel(
                        position_guarded_submitter(place_limit_order, exchange_net_reader())
                    )
                    close_live_position(cur, kernel, model_name, ticker, bid, utc_now())
                conn.commit()
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "market_ticker": ticker, "close_bid": bid}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        if parsed.path == "/sim_risk/resume":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                model_name = str(payload.get("model_name") or "").strip()
                if not model_name:
                    raise ValueError("model_name is required")
                conn = get_db_conn()
                with conn.cursor() as cur:
                    clear_model_paused(cur, model_name, utc_now())
                conn.commit()
                conn.close()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "model_name": model_name}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return
        self._send("not found", 404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"Dashboard listening on {HOST}:{PORT}")
    if not LIVE_TRADING_PASSWORD:
        print("WARNING: LIVE_TRADING_PASSWORD is unset - every live control is locked until it is set.")
    server.serve_forever()


if __name__ == "__main__":
    main()
