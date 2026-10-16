import json
import time
from datetime import timedelta
from typing import Dict, List, Optional

from data_pipeline.common import api_get, get_db_conn, parse_iso_to_dt, utc_now


def next_minute_mark(now=None):
    if now is None:
        now = utc_now()
    return now.replace(second=0, microsecond=0) + timedelta(minutes=1)


def fetch_open_kxbtc15m_markets() -> List[Dict]:
    data = api_get('/markets', {'series_ticker': 'KXBTC15M', 'status': 'open', 'limit': 200})
    markets = data.get('markets', [])
    if markets:
        return markets
    data = api_get('/markets', {'series_ticker': 'KXBTC15M', 'limit': 200})
    return data.get('markets', [])


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


def run_loop():
    conn = get_db_conn()
    with conn.cursor() as cur:
        print('trade_quote_features_1m collector started. Writing minute-sharp rows.')
        while True:
            mark = next_minute_mark()
            time.sleep(max(0.0, (mark - utc_now()).total_seconds()))
            try:
                markets = fetch_open_kxbtc15m_markets()
                if not markets:
                    write_feature_row(cur, mark, None, None, None, None, None, None, 'no_open_market', {'reason': 'no_open_market'})
                    continue
                m = choose_active_market(markets)
                if not m:
                    write_feature_row(cur, mark, None, None, None, None, None, None, 'no_active_market', {'reason': 'no_active_market'})
                    continue
                ticker = m.get('ticker')
                event = m.get('event_ticker')
                count, vol, vwap = compute_trades_60s(ticker, mark)
                qchg = compute_quote_change_events(cur, ticker, mark)
                payload = {
                    'ticker': ticker,
                    'event_ticker': event,
                    'trades_last_60s_count': count,
                    'trades_last_60s_volume_fp': vol,
                    'trades_last_60s_vwap_yes': vwap,
                    'quote_change_events_60s': qchg,
                }
                write_feature_row(cur, mark, ticker, event, count, vol, vwap, qchg, 'ok', payload)
                cur.execute(
                    """
                    INSERT INTO collector_state (state_key,state_value,updated_at_utc)
                    VALUES (%s,%s,%s)
                    ON DUPLICATE KEY UPDATE state_value=VALUES(state_value), updated_at_utc=VALUES(updated_at_utc)
                    """,
                    (
                        'trade_quote_features_1m_last_snapshot',
                        json.dumps({'snapshot_minute_utc': mark.isoformat(), 'ticker': ticker}),
                        utc_now().replace(tzinfo=None),
                    ),
                )
                print(f'trade_quote_features_1m snapshot {mark.isoformat()} ticker={ticker} count={count} qchg={qchg}')
            except Exception as e:
                write_feature_row(cur, mark, None, None, None, None, None, None, 'error', {'error': str(e)})
                print(f'trade_quote_features_1m error at {mark.isoformat()}: {e}')


if __name__ == '__main__':
    while True:
        try:
            run_loop()
        except Exception as e:
            print(f'[ERROR] trade_quote_features_1m collector crashed: {e}')
            time.sleep(5)
