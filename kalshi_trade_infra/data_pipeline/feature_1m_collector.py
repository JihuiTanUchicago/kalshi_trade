import json
import time
from datetime import timedelta
from typing import Dict, List, Optional

from data_pipeline.common import api_get, get_db_conn, micro_series, parse_iso_to_dt, requested_series, utc_now


def next_minute_mark(now=None):
    if now is None:
        now = utc_now()
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1)


def fetch_open_markets(series_ticker: str) -> List[Dict]:
    data = api_get('/markets', {'series_ticker': series_ticker, 'status': 'open', 'limit': 200})
    markets = data.get('markets', [])
    if markets:
        return markets
    data = api_get('/markets', {'series_ticker': series_ticker, 'limit': 200})
    return data.get('markets', [])


def fetch_open_kxbtc15m_markets() -> List[Dict]:  # back-compat alias
    return fetch_open_markets('KXBTC15M')


def choose_active_market(markets: List[Dict]) -> Optional[Dict]:
    now = utc_now()
    in_window = []
    fallback = []
    for m in markets:
        open_t = parse_iso_to_dt(m.get('open_time'))
        close_t = parse_iso_to_dt(m.get('close_time'))
        exp_t = parse_iso_to_dt(m.get('expected_expiration_time'))
        if open_t and close_t and open_t <= now < close_t:
            in_window.append((close_t, m))
        elif close_t and close_t >= now:
            fallback.append((close_t, m))
        elif exp_t and exp_t >= now:
            fallback.append((exp_t, m))
    if in_window:
        in_window.sort(key=lambda x: x[0])
        return in_window[0][1]
    if fallback:
        fallback.sort(key=lambda x: x[0])
        return fallback[0][1]
    return None


def compute_quote_change_events(cur, ticker: str, end_minute) -> int:
    # Prefer websocket-derived minute bucket if available.
    cur.execute(
        """
        SELECT quote_change_events
        FROM ws_quote_change_1m
        WHERE market_ticker=%s AND snapshot_minute_utc=%s
        LIMIT 1
        """,
        (ticker, end_minute.replace(tzinfo=None)),
    )
    ws_row = cur.fetchone()
    if ws_row:
        return int(ws_row.get('quote_change_events') or 0)

    # Fallback: infer from 20-second snapshots if websocket counters are unavailable.
    start = end_minute - timedelta(seconds=60)
    cur.execute(
        """
        SELECT snapshot_time_utc, yes_bid_dollars, yes_ask_dollars
        FROM forward_quotes
        WHERE market_ticker=%s AND snapshot_time_utc > %s AND snapshot_time_utc <= %s
        ORDER BY snapshot_time_utc ASC
        """,
        (ticker, start.replace(tzinfo=None), end_minute.replace(tzinfo=None)),
    )
    rows = cur.fetchall()
    if len(rows) <= 1:
        return 0
    changes = 0
    prev = rows[0]
    for r in rows[1:]:
        if r['yes_bid_dollars'] != prev['yes_bid_dollars'] or r['yes_ask_dollars'] != prev['yes_ask_dollars']:
            changes += 1
        prev = r
    return changes


def compute_trades_60s(ticker: str, end_minute):
    start = end_minute - timedelta(seconds=60)
    trades = []
    cursor = None
    while True:
        params = {'ticker': ticker, 'limit': 200}
        if cursor:
            params['cursor'] = cursor
        data = api_get('/markets/trades', params)
        page = data.get('trades', [])
        if not page:
            break
        trades.extend(page)
        last_trade_time = parse_iso_to_dt(page[-1].get('created_time'))
        if last_trade_time and last_trade_time <= start:
            break
        cursor = data.get('cursor')
        if not cursor:
            break
        time.sleep(0.05)
    filt = []
    for t in trades:
        ct = parse_iso_to_dt(t.get('created_time'))
        if ct and start < ct <= end_minute:
            filt.append(t)
    count = len(filt)
    volume = 0.0
    notional = 0.0
    for t in filt:
        c = float(t.get('count_fp') or 0)
        p = float(t.get('yes_price_dollars') or 0)
        volume += c
        notional += c * p
    vwap = (notional / volume) if volume > 0 else None
    return count, volume, vwap


def write_feature_row(cur, minute_mark, market_ticker, event_ticker, count, vol, vwap, quote_changes, source_status, payload):
    cur.execute(
        """
        INSERT INTO trade_quote_features_1m
        (snapshot_minute_utc,market_ticker,event_ticker,trades_last_60s_count,trades_last_60s_volume_fp,trades_last_60s_vwap_yes,quote_change_events_60s,source_status,raw_json)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          market_ticker=VALUES(market_ticker), event_ticker=VALUES(event_ticker),
          trades_last_60s_count=VALUES(trades_last_60s_count), trades_last_60s_volume_fp=VALUES(trades_last_60s_volume_fp),
          trades_last_60s_vwap_yes=VALUES(trades_last_60s_vwap_yes), quote_change_events_60s=VALUES(quote_change_events_60s),
          source_status=VALUES(source_status), raw_json=VALUES(raw_json)
        """,
        (
            minute_mark.replace(tzinfo=None),
            market_ticker,
            event_ticker,
            count,
            vol,
            vwap,
            quote_changes,
            source_status,
            json.dumps(payload),
        ),
    )


def collect_series(cur, mark, series: str, is_primary: bool) -> Optional[str]:
    """Snapshot the active market of one series into trade_quote_features_1m for `mark`.
    Returns the ticker written, or None. The primary series keeps the original
    no-market/error sentinel rows (the live-path freshness view expects them); extra
    series stay silent on a miss since their rows are purely additive."""
    try:
        markets = fetch_open_markets(series)
        if not markets:
            if is_primary:
                write_feature_row(cur, mark, None, None, None, None, None, None, 'no_open_market', {'reason': 'no_open_market', 'series': series})
            return None
        m = choose_active_market(markets)
        if not m:
            if is_primary:
                write_feature_row(cur, mark, None, None, None, None, None, None, 'no_active_market', {'reason': 'no_active_market', 'series': series})
            return None
        ticker = m.get('ticker')
        event = m.get('event_ticker')
        count, vol, vwap = compute_trades_60s(ticker, mark)
        qchg = compute_quote_change_events(cur, ticker, mark)
        payload = {
            'ticker': ticker,
            'event_ticker': event,
            'series': series,
            'trades_last_60s_count': count,
            'trades_last_60s_volume_fp': vol,
            'trades_last_60s_vwap_yes': vwap,
            'quote_change_events_60s': qchg,
        }
        write_feature_row(cur, mark, ticker, event, count, vol, vwap, qchg, 'ok', payload)
        print(f'trade_quote_features_1m snapshot {mark.isoformat()} series={series} ticker={ticker} count={count} qchg={qchg}')
        return ticker
    except Exception as e:
        # DB-level failures still bubble (the except re-executes a write on a live cursor);
        # a per-series API hiccup must not drop the other series.
        if is_primary:
            write_feature_row(cur, mark, None, None, None, None, None, None, 'error', {'error': str(e), 'series': series})
        print(f'trade_quote_features_1m error series={series} at {mark.isoformat()}: {e}')
        return None


REQUESTED_MAX_SERIES = 12      # extra series research may ask for (app/rsi_repair.py MAX_MICRO_SERIES)
REQUESTED_REFRESH_SECONDS = 600


def with_requested(base: List[str], cur) -> List[str]:
    """The configured series, then any research asked for (never displacing the primary first)."""
    return base + [s for s in requested_series(cur, "micro", REQUESTED_MAX_SERIES) if s not in base]


def run_loop():
    conn = get_db_conn()
    base = micro_series()
    with conn.cursor() as cur:
        series_list = with_requested(base, cur)
        refreshed = time.time()
        print(f'trade_quote_features_1m collector started. Series={series_list}')
        while True:
            if time.time() - refreshed >= REQUESTED_REFRESH_SECONDS:
                series_list, refreshed = with_requested(base, cur), time.time()
            mark = next_minute_mark()
            time.sleep(max(0.0, (mark - utc_now()).total_seconds()))
            primary_ticker = None
            for idx, series in enumerate(series_list):
                written = collect_series(cur, mark, series, is_primary=(idx == 0))
                if idx == 0:
                    primary_ticker = written
            cur.execute(
                """
                INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                """,
                (
                    'trade_quote_features_1m_last_snapshot',
                    json.dumps({'snapshot_minute_utc': mark.isoformat(), 'ticker': primary_ticker, 'series': series_list}),
                    utc_now().replace(tzinfo=None),
                ),
            )


if __name__ == '__main__':
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f'[ERROR] trade_quote_features_1m collector crashed: {e}')
            time.sleep(5)
