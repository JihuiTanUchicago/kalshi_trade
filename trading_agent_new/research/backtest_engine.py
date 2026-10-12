"""Chronological integer-share research simulator; public data is a proxy.

Economic rules live in experiment_protocol.json. Nothing here selects parameters
from performance. Fill prices are simulated, not observations of attainable fills.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import json
import math
import numpy as np
import pandas as pd
import exchange_calendars as xcals
from pandas.tseries.holiday import USFederalHolidayCalendar

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def commission(quantity, enabled=True):
    return max(1.0, .005 * abs(quantity)) if enabled and quantity else 0.0


def affordable_buys(quantities, prices, cash, enabled=True):
    """Scale queued buys proportionally. Opening prices only check affordability."""
    q = np.asarray(quantities, dtype=np.int64).copy()
    def cost(v):
        return float(v @ prices + sum(commission(int(x), enabled) for x in v))
    original_cost = cost(q)
    if original_cost <= cash + 1e-9:
        return q, False
    q = np.floor(q * max(0, cash) / original_cost).astype(np.int64)
    while cost(q) > cash + 1e-9:
        factor = max(0, cash) / cost(q)
        new = np.floor(q * factor).astype(np.int64)
        if np.array_equal(q, new):
            new[np.argmax(q * prices)] -= 1
        q = new
    return q, True


def settlement_lag(day):
    if day < pd.Timestamp('2017-09-05'):
        return 3
    return 2 if day < pd.Timestamp('2024-05-28') else 1


def entitlement(shares, dividend, split):
    """Dividend per post-split share; ledger never uses adjusted execution prices."""
    return shares * split * dividend


def derive_features(closes, dividends, splits, volume):
    rets = np.full_like(closes, np.nan)
    rets[1:] = (closes[1:] + dividends[1:]) * splits[1:] / closes[:-1] - 1
    tr = np.ones_like(closes)
    tr[1:] = np.cumprod(1 + rets[1:], axis=0)
    n, m = closes.shape
    vol, cov = np.full_like(closes, np.nan), np.full((n, m, m), np.nan)
    med = np.full_like(closes, np.nan)
    for k in range(63, n):
        window = rets[k-62:k+1]
        vol[k] = np.std(window, axis=0, ddof=1) * np.sqrt(252)
        cov[k] = np.cov(window.T, ddof=1) * 252
    for k in range(19, n):
        med[k] = np.median(volume[k-19:k+1], axis=0)
    signal = np.zeros_like(closes, dtype=bool)
    signal[252:] = tr[252:] / tr[:-252] > 1
    return tr, rets, vol, cov, signal, med


@dataclass
class Market:
    dates: pd.DatetimeIndex
    symbols: list[str]
    opens: np.ndarray
    closes: np.ndarray
    volume: np.ndarray
    adjusted: np.ndarray
    dividends: np.ndarray
    splits: np.ndarray
    tr: np.ndarray
    returns: np.ndarray
    vol: np.ndarray
    cov: np.ndarray
    signal: np.ndarray
    median_volume: np.ndarray
    lagged_rate: np.ndarray
    risk_free: np.ndarray
    close_times: list[str]
    open_times: list[str]
    settlement_dates: dict
    input_audit: dict
    config: dict


def load_market(protocol_path=ROOT / 'research/experiment_protocol.json'):
    p = json.loads(Path(protocol_path).read_text())
    d = ROOT / p['data_directory']
    manifest = json.loads((d / 'manifest.json').read_text())
    assert manifest['protocol_sha256'] == sha256(protocol_path), 'Protocol changed after snapshot'
    frames = []
    events = []
    for f in manifest['files']:
        assert sha256(ROOT / f['raw_path']) == f['raw_sha256']
        assert sha256(ROOT / f['normalized_path']) == f['normalized_sha256']
        frame = pd.read_csv(ROOT / f['normalized_path'], index_col='date', parse_dates=True)
        frames.append(frame)
        result = json.loads((ROOT / f['raw_path']).read_text())['chart']['result'][0]
        events.append(result.get('events', {}))
    dates = frames[0].index
    assert all(f.index.equals(dates) for f in frames)
    cal = xcals.get_calendar('XNYS', start=dates[0], end='2027-03-01')
    expected = cal.sessions_in_range(dates[0], dates[-1]).tz_localize(None)
    assert dates.equals(expected), 'Missing or extra exchange session'
    def field(name):
        return np.column_stack([f[name].to_numpy(float) for f in frames])
    opens, closes, volume, adjusted = map(field, ['open', 'close', 'volume', 'adjusted_close'])
    assert np.isfinite(opens).all() and np.isfinite(closes).all()
    assert (opens > 0).all() and (closes > 0).all() and (volume >= 0).all()
    div, split = np.zeros_like(closes), np.ones_like(closes)
    event_counts = {}
    for j, e in enumerate(events):
        event_counts[p['symbols'][j]] = {k: len(v) for k, v in e.items()}
        for kind, entries in e.items():
            for item in entries.values():
                day = pd.Timestamp(item['date'], unit='s', tz='UTC').tz_convert('America/New_York').tz_localize(None).normalize()
                assert day in dates, f'Non-session event: {day}'
                k = dates.get_loc(day)
                if kind == 'dividends':
                    div[k, j] += item['amount']
                elif kind == 'splits':
                    split[k, j] *= item['numerator'] / item['denominator']
                else:
                    raise ValueError(f'Unsupported corporate action: {kind}')
    tr, rets, vol, cov, signal, med = derive_features(closes, div, split, volume)
    n = len(dates)
    rate_path = d / 'raw/DFF.csv'
    rm = json.loads((d / 'raw/rate_manifest.json').read_text())
    assert sha256(rate_path) == rm['sha256']
    rates = pd.read_csv(rate_path, index_col=0, parse_dates=True).iloc[:, 0]
    rates = pd.to_numeric(rates, errors='coerce').reindex(dates).ffill().to_numpy(float) / 100
    lagged = np.full(n, np.nan)
    lagged[2:] = rates[:-2]
    days = dates.to_series().diff().dt.days.fillna(1).to_numpy()
    rf = (1 + lagged) ** (days / 365) - 1
    score = dates >= pd.Timestamp(p['distribution_scoring_start'])
    assert np.isfinite(rf[score]).all(), 'Reference rate missing in scored period'
    holidays = USFederalHolidayCalendar().holidays(dates[0], '2027-03-01')
    settle_calendar = cal.sessions.tz_localize(None)
    settle_calendar = settle_calendar[~settle_calendar.isin(holidays)]
    settle_dates = {}
    for day in dates:
        start = settle_calendar.searchsorted(day, side='right')
        settle_dates[day] = settle_calendar[start + settlement_lag(day) - 1]
    sch = cal.schedule.loc[cal.sessions_in_range(dates[0], dates[-1])]
    audit = {'rows_per_asset': n, 'scored_sessions': int(score.sum()),
             'first_date': str(dates[0].date()), 'last_date': str(dates[-1].date()),
             'events': event_counts, 'price_manifest_hashes_verified': True,
             'rate_hash_verified': True, 'calendar_complete': True,
             'formal_point_in_time_qualification': False,
             'protocol_sha256': sha256(protocol_path),
             'maximum_forward_vs_adjusted_daily_return_difference_bps': float(np.nanmax(np.abs(rets[1:] - adjusted[1:] / adjusted[:-1] + 1))*10000),
             'reference_rate_first': float(lagged[score][0]), 'reference_rate_last': float(lagged[score][-1])}
    return Market(dates, p['symbols'], opens, closes, volume, adjusted, div, split,
                  tr, rets, vol, cov, signal, med, lagged, rf,
                  [str(x) for x in sch['close']], [str(x) for x in sch['open']],
                  settle_dates, audit, p)


def target_weights(market, k, strategy):
    p = market.config['features']
    if strategy == 'SPY':
        w = np.zeros(len(market.symbols)); w[0] = p['gross_cap']; return w
    if strategy == 'EqualWeight':
        return np.full(len(market.symbols), p['gross_cap'] / len(market.symbols))
    s = np.ones(len(market.symbols)) if strategy == 'NoTrend' else market.signal[k].astype(float)
    a = s / np.maximum(market.vol[k], p['volatility_floor'])
    if not a.sum():
        return a
    b = a / a.sum()
    forecast = np.sqrt(max(0, b @ market.cov[k] @ b))
    scale = min(p['gross_cap'], p['portfolio_volatility_reference'] / max(forecast, .01))
    return np.minimum(p['asset_cap'], b * scale)


def simulate(market, trial, stop=None):
    """Continuous account, orders selected before fill session information."""
    dates, symbols = market.dates, market.symbols
    m = len(symbols)
    shares = np.zeros(m, dtype=np.int64)
    cash = float(trial['capital']); previous_nav = cash
    receivables, unsettled = [], []
    previous_signal = None
    pending = np.zeros(m, bool)
    daily, orders = [], []
    start = dates.searchsorted(pd.Timestamp(market.config['distribution_scoring_start']))
    end = len(dates) if stop is None else dates.searchsorted(pd.Timestamp(stop), side='right')
    assert start - 1 - trial['extra_signal_lag'] >= 252
    max_reconciliation = 0.0
    s = trial['strategy']
    buffer = market.config['buffers'].get(s, 0)
    for t in range(start, end):
        day = dates[t]
        k = t - 1 - trial['extra_signal_lag']
        mark = market.closes[k]
        claims_before = sum(v for _, v in receivables) + sum(v for _, v in unsettled)
        sizing_nav = cash + claims_before + shares @ mark
        current = shares * mark / sizing_nav
        target = target_weights(market, k, s)
        signal = market.signal[k].copy()
        initial = t == start
        month_refresh = initial or dates[k].month != dates[k+1].month
        eligible = np.zeros(m, bool)
        reason = np.full(m, 'hold', dtype=object)
        if s == 'SPY':
            eligible[:] = initial; reason[:] = 'initial buy and hold' if initial else 'hold'
        elif s in ('Monthly', 'EqualWeight'):
            eligible[:] = month_refresh; reason[:] = 'monthly refresh' if month_refresh else 'hold'
        else:
            eligible = np.abs(current - target) >= buffer
            reason[eligible] = 'buffer threshold'
            changed = np.ones(m, bool) if previous_signal is None else signal != previous_signal
            if s == 'NoTrend':
                changed = np.zeros(m, bool)
            forced = changed | ((target == 0) & (shares > 0)) | pending
            eligible |= forced; reason[forced] = 'trend/zero/pending override'
        provisional = np.where(eligible, target, current)
        risk = np.zeros(m, bool)
        if s != 'SPY':
            capped = np.minimum(provisional, market.config['features']['asset_cap'])
            risk |= provisional > capped + 1e-12
            if capped.sum() > market.config['features']['gross_cap']:
                capped *= market.config['features']['gross_cap'] / capped.sum()
                risk |= provisional > capped + 1e-12
            eligible |= risk; reason[risk] = 'risk cap override'
            provisional = capped
        desired = np.floor(provisional * sizing_nav / mark + 1e-10).astype(np.int64)
        desired = np.where(eligible, desired, shares)
        queued = desired - shares
        previous_signal = signal
        previous_shares = shares.copy()
        # Today's corporate actions do not inform yesterday's order selection.
        splits = market.splits[t]
        if not np.all(splits == 1):
            if not np.allclose(previous_shares * splits, np.round(previous_shares * splits)):
                raise ValueError('Fractional split cash-in-lieu requires additional source evidence')
            shares = np.round(shares * splits).astype(np.int64)
            queued = np.trunc(queued * splits).astype(np.int64)
            desired = shares + queued
        dividend = float(entitlement(previous_shares, market.dividends[t], splits).sum())
        if dividend:
            payable = day + pd.Timedelta(days=trial['dividend_delay_days'])
            receivables.append((payable, dividend))
        # Interest uses cash actually held overnight, never today's sale proceeds.
        gap_days = (day - dates[t-1]).days
        interest = cash * ((1 + max(market.lagged_rate[t] - .005, 0)) ** (gap_days / 365) - 1) if trial['cash_yield'] else 0.0
        cash += interest
        cash += sum(v for dt, v in receivables if dt <= day)
        receivables = [(dt, v) for dt, v in receivables if dt > day]
        cash += sum(v for dt, v in unsettled if dt <= day)
        unsettled = [(dt, v) for dt, v in unsettled if dt > day]
        service = trial['service_annual'] / 12 if initial or day.month != dates[t-1].month else 0.0
        cash -= service
        if cash < -1e-8:
            raise ValueError('Service charge exhausted spendable cash')
        opening = market.opens[t]
        limit = np.floor(market.median_volume[k] * market.config['features']['participation_cap']).astype(np.int64)
        requested = queued.copy()
        fills = np.zeros(m, dtype=np.int64)
        prefill_values = np.full(m, np.nan)
        total_commission = slippage = turnover = 0.0
        cash_reduced = False
        for side in ('sell', 'buy'):
            qty = np.minimum(np.maximum(-queued if side == 'sell' else queued, 0), limit)
            if side == 'sell':
                qty = np.minimum(qty, shares)
            fillprice = opening * (1 - trial['cost_bps'] / 10000 if side == 'sell' else 1 + trial['cost_bps'] / 10000)
            if side == 'buy':
                qty, cash_reduced = affordable_buys(qty, fillprice, cash, trial['commission'])
            for j in np.flatnonzero(qty):
                q = int(qty[j]); charge = commission(q, trial['commission'])
                prefill_nav = cash + shares @ opening + sum(v for _, v in receivables) + sum(v for _, v in unsettled)
                prefill_values[j] = prefill_nav
                turnover += q * fillprice[j] / prefill_nav
                fee = q * abs(fillprice[j] - opening[j])
                total_commission += charge; slippage += fee
                if side == 'sell':
                    shares[j] -= q; fills[j] -= q
                    value = q * fillprice[j] - charge
                    if trial['settled_cash']:
                        unsettled.append((market.settlement_dates[day], value))
                    else:
                        cash += value
                else:
                    shares[j] += q; fills[j] += q
                    cash -= q * fillprice[j] + charge
        assert cash >= -1e-7 and np.all(shares >= 0), 'Negative cash or short position'
        close = market.closes[t]
        div_claim = sum(v for _, v in receivables)
        pending_cash = sum(v for _, v in unsettled)
        nav = float(cash + shares @ close + div_claim + pending_cash)
        # Independent daily accounting identity includes overnight and post-fill moves.
        price_pnl = float(previous_shares @ (splits * opening - market.closes[t-1]) + shares @ (close - opening))
        expected_nav = previous_nav + price_pnl + dividend + interest - service - slippage - total_commission
        residual = nav - expected_nav
        max_reconciliation = max(max_reconciliation, abs(residual))
        assert abs(residual) < max(1e-7, nav * 1e-11), 'Ledger reconciliation failed'
        assert nav > 0
        final_weights = shares * close / nav
        gross = float(final_weights.sum())
        # Retry unfilled forced orders. Rounding below one share is resolved.
        forced_order = np.array(['override' in str(r) for r in reason])
        pending = forced_order & (requested != fills)
        for j in np.flatnonzero(requested):
            q = int(requested[j]); f = int(fills[j])
            orders.append({'date': str(day.date()), 'decision_bar_date': str(dates[k].date()),
                'decision_time_assumed': market.close_times[k] + ' + 1 minute',
                'fill_time': market.open_times[t], 'symbol': symbols[j],
                'signal': bool(signal[j]), 'target_weight': float(target[j]),
                'current_weight': float(current[j]), 'submitted_quantity': q,
                'filled_quantity': f, 'fill_reference': float(opening[j]),
                'fill_price': float(opening[j] * (1 + np.sign(f) * trial['cost_bps']/10000)) if f else None,
                'nav_before_fill': float(prefill_values[j]) if f else None,
                'commission': commission(f, trial['commission']),
                'slippage': abs(f)*opening[j]*trial['cost_bps']/10000,
                'participation_limit': int(limit[j]), 'reason': str(reason[j]),
                'partial_or_rejected': q != f, 'cash_reduced_session': bool(cash_reduced),
                'resulting_shares': int(shares[j]), 'closing_cash': float(cash)})
        row = {'date': str(day.date()), 'nav': nav, 'return': nav/previous_nav-1,
               'risk_free': float(market.risk_free[t]), 'cash': float(cash),
               'dividend_receivable': float(div_claim), 'unsettled_sale_proceeds': float(pending_cash),
               'dividend_entitlement': dividend, 'cash_interest': float(interest),
               'commission': total_commission, 'slippage': float(slippage), 'service': service,
               'turnover': float(turnover), 'gross_exposure': gross,
               'equity_exposure': float(final_weights[:3].sum()),
               'treasury_exposure': float(final_weights[3:5].sum()),
               'gold_exposure': float(final_weights[5]), 'cash_and_claims_weight': 1-gross,
               'tracking_error_l1': float(np.abs(final_weights-target).sum()),
               'asset_cap_breach': bool(s != 'SPY' and max(final_weights) > .25+1e-10),
               'gross_cap_breach': bool(s != 'SPY' and gross > .95+1e-10),
               'risk_override_count': int(risk.sum()), 'cash_reduced': bool(cash_reduced),
               'max_opening_gap': float(np.max(np.abs(opening/market.closes[t-1]-1))),
               'reconciliation_error': float(residual)}
        for j, symbol in enumerate(symbols):
            row[f'shares_{symbol}'] = int(shares[j]); row[f'weight_{symbol}'] = float(final_weights[j])
        daily.append(row)
        previous_nav = nav
    frame = pd.DataFrame(daily).set_index('date'); frame.index = pd.to_datetime(frame.index)
    return frame, pd.DataFrame(orders), {'max_accounting_error_usd': max_reconciliation,
        'nonnegative_cash': bool((frame['cash'] >= -1e-7).all()),
        'no_short_positions': True, 'orders_use_prior_session': all(x['decision_bar_date'] < x['date'] for x in orders),
        'formal_data_qualification': False}


def metrics(frame):
    r = frame['return'].to_numpy(); e = r - frame['risk_free'].to_numpy()
    wealth = np.cumprod(1+r)
    peaks = np.maximum.accumulate(np.r_[1., wealth])[1:]
    days = (frame.index[-1] - frame.index[0]).days + 1
    years = days / 365.25
    return {'sessions': len(frame), 'years': years, 'net_sharpe': float(np.sqrt(252)*e.mean()/e.std(ddof=1)),
        'cagr': float(wealth[-1]**(1/years)-1), 'annual_volatility': float(r.std(ddof=1)*np.sqrt(252)),
        'max_drawdown': float(np.max(1-wealth/peaks)),
        'downside_deviation': float(np.sqrt(np.mean(np.minimum(e,0)**2))*np.sqrt(252)),
        'annual_mean_excess': float(e.mean()*252), 'annual_turnover': float(frame['turnover'].sum()/years),
        'terminal_nav': float(frame['nav'].iloc[-1]),
        'commissions_usd': float(frame['commission'].sum()), 'slippage_usd': float(frame['slippage'].sum()),
        'service_usd': float(frame['service'].sum()),
        'average_gross': float(frame['gross_exposure'].mean()),
        'average_cash_and_claims': float(frame['cash_and_claims_weight'].mean()),
        'average_equity': float(frame['equity_exposure'].mean()),
        'average_treasury': float(frame['treasury_exposure'].mean()),
        'average_gold': float(frame['gold_exposure'].mean()),
        'mean_tracking_error_l1': float(frame['tracking_error_l1'].mean()),
        'asset_cap_breach_days': int(frame['asset_cap_breach'].sum()),
        'gross_cap_breach_days': int(frame['gross_cap_breach'].sum()),
        'cash_reduced_days': int(frame['cash_reduced'].sum()),
        'risk_overrides': int(frame['risk_override_count'].sum())}
