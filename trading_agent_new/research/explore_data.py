"""Execute the frozen descriptive EDA; never construct strategy returns."""

from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
import hashlib
import json
import os
import argparse

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.mpl-cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import exchange_calendars as xcals
import numpy as np
import pandas as pd

FIELDS = ['open', 'high', 'low', 'close', 'volume', 'adjusted_close']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def matrix_markdown(frame, decimals=2):
    labels = list(frame.columns)
    lines = ['| ETF | ' + ' | '.join(labels) + ' |', '| --- | ' + ' | '.join(['---'] * len(labels)) + ' |']
    for name, row in frame.iterrows():
        lines.append('| ' + str(name) + ' | ' + ' | '.join(f'{float(row[c]):.{decimals}f}' for c in labels) + ' |')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', default='research/eda_protocol_current.json')
    args = parser.parse_args()
    protocol_path = ROOT / args.protocol
    spec_path = ROOT / 'docs/RESEARCH_SPECIFICATION.md'
    protocol = json.loads(protocol_path.read_text())
    data_dir = ROOT / protocol.get('data_directory', 'data')
    manifest = json.loads((data_dir / 'manifest.json').read_text())
    assert digest(protocol_path) == manifest['protocol_sha256'], 'Protocol changed after acquisition.'
    assert digest(spec_path) == manifest['specification_sha256'], 'Specification changed after acquisition.'
    out = ROOT / protocol.get('output_directory', 'results')
    out.mkdir(parents=True, exist_ok=True)
    charts = out / 'charts'
    charts.mkdir(exist_ok=True)
    start, end = protocol['requested_start'], protocol['distribution_scoring_end']
    period_label = f"{protocol['distribution_scoring_start']} to {end}"
    calendar = xcals.get_calendar('XNYS', start=start, end=end)
    schedule = calendar.schedule.loc[start:end].copy()
    sessions = pd.DatetimeIndex(pd.to_datetime(schedule.index)).tz_localize(None).normalize()
    schedule.index = sessions
    closure_candidates = ['2007-01-02', '2012-10-29', '2012-10-30', '2018-12-05', '2022-06-20', '2025-01-09']
    checked_closures = [d for d in closure_candidates if start <= d <= end]
    assert all(pd.Timestamp(d) not in sessions for d in checked_closures), 'Known closure omitted.'
    close_col = 'close' if 'close' in schedule else 'market_close'
    local_closes = pd.to_datetime(schedule[close_col], utc=True).dt.tz_convert('America/New_York')
    early = local_closes.dt.hour < 16
    session_export = pd.DataFrame({'date': sessions.strftime('%Y-%m-%d'),
                                   'close_new_york': local_closes.astype(str).to_numpy(),
                                   'early_close': early.to_numpy()})
    session_export.to_csv(out / 'expected_sessions.csv', index=False)
    dev = sessions[(sessions >= protocol['distribution_scoring_start']) & (sessions <= protocol['distribution_scoring_end'])]
    quality, distributions, timing, event_checks = {}, {}, {}, {}
    latest_snapshots, weekly_bars = [], []
    week_start = pd.Timestamp(end) - pd.Timedelta(days=pd.Timestamp(end).weekday())
    returns = pd.DataFrame(index=dev)
    anomaly_rows, extremes, lag_rows, volume_rows = [], [], [], []
    for record in manifest['files']:
        symbol = record['symbol']
        for path_key, hash_key in [('raw_path', 'raw_sha256'), ('normalized_path', 'normalized_sha256')]:
            assert digest(ROOT / record[path_key]) == record[hash_key], f'{symbol}: snapshot hash mismatch.'
        raw = json.loads((ROOT / record['raw_path']).read_text())['chart']['result'][0]
        frame = pd.read_csv(ROOT / record['normalized_path'])
        dates = pd.to_datetime(frame['date'])
        assert dates.max() < pd.Timestamp(protocol['sealed_from']), 'Observation exceeds authorized cutoff.'
        duplicates = int(dates.duplicated().sum())
        assert not duplicates and dates.is_monotonic_increasing, f'{symbol}: duplicate or unordered dates.'
        frame.index = dates
        prices = frame[['open', 'high', 'low', 'close', 'adjusted_close']]
        finite = pd.DataFrame(np.isfinite(prices), index=prices.index, columns=prices.columns)
        ohlc_bad = (frame['high'] + 1e-6 < frame[['open', 'close', 'low']].max(axis=1)) | (frame['low'] - 1e-6 > frame[['open', 'close', 'high']].min(axis=1))
        missing_dates = sessions.difference(dates)
        extra_dates = dates[~dates.isin(sessions)]
        quality[symbol] = {'rows': len(frame), 'expected_sessions': len(sessions),
                           'first_date': dates.min().date().isoformat(), 'last_date': dates.max().date().isoformat(),
                           'missing_sessions': [d.date().isoformat() for d in missing_dates],
                           'non_session_dates': [d.date().isoformat() for d in extra_dates],
                           'duplicate_dates': duplicates, 'date_order_valid': bool(dates.is_monotonic_increasing),
                           'missing_by_field': frame[FIELDS].isna().sum().to_dict(),
                           'nonfinite_price_cells': int((~finite & prices.notna()).sum().sum()),
                           'nonpositive_price_cells': int((prices <= 0).sum().sum()),
                           'negative_volume_rows': int((frame['volume'] < 0).sum()),
                           'zero_volume_rows': int((frame['volume'] == 0).sum()),
                           'ohlc_violation_rows': int(ohlc_bad.sum())}
        aligned = frame.reindex(sessions)
        valid_price = aligned['adjusted_close'].where(aligned['adjusted_close'] > 0)
        all_returns = valid_price.pct_change(fill_method=None)
        r = all_returns.reindex(dev)
        returns[symbol] = r
        sample = r.dropna()
        median = sample.median()
        mad = (sample - median).abs().median()
        robust_z = 0.67448975 * (r - median) / mad if mad > 0 else pd.Series(np.nan, index=r.index)
        spread = (aligned['high'] / aligned['low'] - 1).reindex(dev)
        previous_median_volume = aligned['volume'].shift(1).rolling(20, min_periods=20).median()
        relative_volume = (aligned['volume'] / previous_median_volume.replace(0, np.nan)).reindex(dev)
        flat = r.abs() < 1e-12
        groups = (flat != flat.shift()).cumsum()
        longest_flat = int(flat.groupby(groups).sum().max())
        std = sample.std(ddof=1)
        distributions[symbol] = {'observations': len(sample), 'mean_daily_pct': sample.mean() * 100,
                                 'median_daily_pct': median * 100, 'daily_std_pct': std * 100,
                                 'annualized_volatility_pct': std * np.sqrt(252) * 100,
                                 'skewness': sample.skew(), 'excess_kurtosis': sample.kurt(),
                                 'p01_pct': sample.quantile(.01) * 100, 'p05_pct': sample.quantile(.05) * 100,
                                 'p95_pct': sample.quantile(.95) * 100, 'p99_pct': sample.quantile(.99) * 100,
                                 'min_pct': sample.min() * 100, 'max_pct': sample.max() * 100,
                                 'min_date': sample.idxmin().date().isoformat(), 'max_date': sample.idxmax().date().isoformat(),
                                 'more_than_3std_pct': ((sample - sample.mean()).abs() > 3 * std).mean() * 100,
                                 'zero_return_days': int(flat.sum()), 'longest_flat_return_run': longest_flat,
                                 'abs_return_above_10pct': int((r.abs() > .10).sum()),
                                 'robust_z_above_8': int((robust_z.abs() > 8).sum()),
                                 'intraday_range_above_15pct': int((spread > .15).sum()),
                                 'volume_above_10x_lagged_median': int((relative_volume > 10).sum())}
        flags = (r.abs() > .10) | (robust_z.abs() > 8) | (spread > .15) | (relative_volume > 10) | ohlc_bad.reindex(dev, fill_value=False)
        for date in r.index[flags]:
            reasons = []
            if abs(r.loc[date]) > .10: reasons.append('absolute return >10%')
            if abs(robust_z.loc[date]) > 8: reasons.append('robust return score >8')
            if spread.loc[date] > .15: reasons.append('intraday range >15%')
            if relative_volume.loc[date] > 10: reasons.append('volume >10x lagged median')
            if ohlc_bad.get(date, False): reasons.append('OHLC inconsistency')
            anomaly_rows.append({'symbol': symbol, 'date': date.date().isoformat(), 'return_pct': r.loc[date] * 100,
                                 'robust_z': robust_z.loc[date], 'intraday_range_pct': spread.loc[date] * 100,
                                 'relative_volume': relative_volume.loc[date], 'reasons': '; '.join(reasons)})
        for date in sample.abs().nlargest(3).index:
            extremes.append({'symbol': symbol, 'date': date.date().isoformat(), 'return_pct': sample.loc[date] * 100})
        stamps = pd.to_datetime(frame['timestamp_utc'], utc=True).dt.tz_convert('America/New_York')
        timing[symbol] = {'new_york_bar_label_times': sorted(stamps.dt.strftime('%H:%M:%S').unique().tolist()),
                          'utc_bar_label_times': sorted(stamps.dt.tz_convert('UTC').dt.strftime('%H:%M:%S').unique().tolist()),
                          'date_label_match': bool((stamps.dt.strftime('%Y-%m-%d').to_numpy() == frame['date'].to_numpy()).all()),
                          'historical_release_time_available': False, 'auction_fill_evidence_available': False}
        events = raw.get('events', {})
        dividend_dates = {}
        for event in events.get('dividends', {}).values():
            date = pd.Timestamp(event['date'], unit='s', tz='UTC').tz_convert('America/New_York').tz_localize(None).normalize()
            if not (pd.Timestamp(start) <= date <= pd.Timestamp(end)): raise ValueError('Out-of-scope dividend event.')
            dividend_dates[date] = event['amount']
        split_events = list(events.get('splits', {}).values())
        factor = aligned['adjusted_close'] / aligned['close']
        factor_change = factor / factor.shift(1) - 1
        raw_return = aligned['close'].pct_change(fill_method=None)
        errors = []
        for date, amount in dividend_dates.items():
            if date not in sessions or pd.isna(factor_change.loc[date]): continue
            prior_close = aligned['close'].shift(1).loc[date]
            expected_change = 1 / (1 - amount / prior_close) - 1
            errors.append(abs(factor_change.loc[date] - expected_change) * 10000)
        significant_changes = set(factor_change.index[factor_change.abs() > .00001])
        unexplained = significant_changes - set(dividend_dates)
        event_checks[symbol] = {'dividend_event_count': len(dividend_dates), 'split_event_count': len(split_events),
                                'dividend_factor_reconciliation_max_error_bps': max(errors) if errors else None,
                                'adjustment_change_without_reported_dividend': [d.date().isoformat() for d in sorted(unexplained)],
                                'close_vs_adjusted_return_difference_max_bps': (raw_return - all_returns).abs().max() * 10000,
                                'dividend_pay_dates_available': False}
        for lag in [1, 5, 21]:
            lag_rows.append({'symbol': symbol, 'lag_sessions': lag, 'correlation': r.corr(r.shift(lag)),
                             'paired_observations': int(pd.concat([r, r.shift(lag)], axis=1).dropna().shape[0])})
        volume_rows.append({'symbol': symbol, 'median_daily_volume_shares': aligned.loc[dev, 'volume'].median(),
                            'median_lagged_20_session_volume_shares': previous_median_volume.reindex(dev).median(),
                            'absolute_return_vs_relative_volume_spearman': r.abs().corr(relative_volume, method='spearman')})
        if protocol.get('historical_holdout_explored'):
            last_date = sample.index[-1]
            last_five = sample.tail(5)
            this_week = r.loc[week_start:end].dropna()
            latest_snapshots.append({'symbol': symbol, 'latest_session': last_date.date().isoformat(),
                                     'reported_close': aligned.loc[last_date, 'close'],
                                     'daily_asset_return_pct': sample.iloc[-1] * 100,
                                     'five_session_asset_return_pct': ((1 + last_five).prod() - 1) * 100,
                                     'week_to_date_asset_return_pct': ((1 + this_week).prod() - 1) * 100,
                                     'completed_week_sessions': len(this_week),
                                     'trailing_63_session_volatility_pct': sample.tail(63).std(ddof=1) * np.sqrt(252) * 100,
                                     'last_volume_shares': aligned.loc[last_date, 'volume'],
                                     'last_relative_volume': relative_volume.loc[last_date]})
            for date in this_week.index:
                weekly_bars.append({'symbol': symbol, 'date': date.date().isoformat(),
                                    **{f: aligned.loc[date, f] for f in FIELDS},
                                    'daily_asset_return_pct': r.loc[date] * 100})
    returns.index.name = 'date'
    returns.to_csv(out / 'daily_asset_returns.csv')
    distribution_frame = pd.DataFrame(distributions).T
    distribution_frame.to_csv(out / 'return_distributions.csv', index_label='symbol')
    pd.DataFrame(anomaly_rows).to_csv(out / 'flagged_observations.csv', index=False)
    pd.DataFrame(extremes).to_csv(out / 'largest_moves.csv', index=False)
    pd.DataFrame(lag_rows).to_csv(out / 'lagged_correlations.csv', index=False)
    pd.DataFrame(volume_rows).to_csv(out / 'volume_relationships.csv', index=False)
    pearson = returns.corr()
    spearman = returns.corr(method='spearman')
    counts = returns.notna().astype(int).T.dot(returns.notna().astype(int))
    pearson.to_csv(out / 'correlation_pearson.csv')
    spearman.to_csv(out / 'correlation_spearman.csv')
    counts.to_csv(out / 'correlation_pair_counts.csv')
    yearly_rows, rolling_rows = [], []
    for a, b in combinations(protocol['symbols'], 2):
        for year, subset in returns.groupby(returns.index.year):
            yearly_rows.append({'asset_a': a, 'asset_b': b, 'year': int(year), 'correlation': subset[a].corr(subset[b]),
                               'paired_observations': int(subset[[a, b]].dropna().shape[0])})
        rolling = returns[a].rolling(63, min_periods=63).corr(returns[b])
        rolling_rows.append({'asset_a': a, 'asset_b': b, 'rolling_63_session_min': rolling.min(),
                             'rolling_63_session_median': rolling.median(), 'rolling_63_session_max': rolling.max()})
    pd.DataFrame(yearly_rows).to_csv(out / 'annual_correlations.csv', index=False)
    pd.DataFrame(rolling_rows).to_csv(out / 'rolling_correlation_summary.csv', index=False)
    window_rows, window_correlations, window_summaries = [], [], {}
    for window in protocol.get('windows', [{'name': 'Analysis_period', 'start': protocol['distribution_scoring_start']}]):
        subset = returns.loc[window['start']:end]
        window_matrix = subset.corr()
        window_matrix.to_csv(out / f"correlation_{window['name']}.csv")
        window_summaries[window['name']] = {'start': window['start'], 'end': end,
                                          'expected_sessions': len(subset), 'pearson': window_matrix.to_dict(),
                                          'observations_per_asset': subset.notna().sum().to_dict()}
        for symbol in protocol['symbols']:
            values = subset[symbol].dropna()
            window_rows.append({'window': window['name'], 'symbol': symbol, 'observations': len(values),
                                'annualized_volatility_pct': values.std(ddof=1) * np.sqrt(252) * 100,
                                'p01_pct': values.quantile(.01) * 100, 'p99_pct': values.quantile(.99) * 100,
                                'skewness': values.skew(), 'excess_kurtosis': values.kurt(),
                                'min_pct': values.min() * 100, 'max_pct': values.max() * 100})
        for a, b in combinations(protocol['symbols'], 2):
            window_correlations.append({'window': window['name'], 'asset_a': a, 'asset_b': b,
                                         'correlation': window_matrix.loc[a, b],
                                         'paired_observations': len(subset[[a, b]].dropna())})
    pd.DataFrame(window_rows).to_csv(out / 'subperiod_distributions.csv', index=False)
    pd.DataFrame(window_correlations).to_csv(out / 'subperiod_correlations.csv', index=False)
    if latest_snapshots:
        pd.DataFrame(latest_snapshots).to_csv(out / 'latest_session_snapshot.csv', index=False)
        pd.DataFrame(weekly_bars).to_csv(out / 'current_week_bars.csv', index=False)
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), constrained_layout=True)
    for ax, symbol in zip(axes.flat, protocol['symbols']):
        sample = returns[symbol].dropna() * 100
        ax.hist(sample, bins=70, color='#227a94', alpha=.9)
        ax.set(title=symbol, xlabel='Daily adjusted-close return (%)', ylabel='Sessions')
        ax.grid(alpha=.15)
    fig.suptitle(f'ETF daily return distributions · {period_label}', fontsize=15)
    fig.savefig(charts / 'return_distributions.png', dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8.5, 7), constrained_layout=True)
    im = ax.imshow(pearson, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(6), pearson.columns)
    ax.set_yticks(range(6), pearson.index)
    for i in range(6):
        for j in range(6):
            value = pearson.iloc[i, j]
            ax.text(j, i, f'{value:.2f}', ha='center', va='center', color='white' if abs(value) > .6 else '#172331', fontsize=13)
    ax.set_title(f'Daily ETF return correlations · {period_label}', pad=16)
    fig.colorbar(im, ax=ax, label='Pearson correlation', shrink=.8)
    fig.savefig(charts / 'return_correlations.png', dpi=160)
    plt.close(fig)
    if 'Year_2026' in window_summaries:
        year_matrix = returns.loc['2026-01-01':end].corr()
        fig, ax = plt.subplots(figsize=(8.5, 7), constrained_layout=True)
        im = ax.imshow(year_matrix, cmap='RdBu_r', vmin=-1, vmax=1)
        ax.set_xticks(range(6), year_matrix.columns)
        ax.set_yticks(range(6), year_matrix.index)
        for i in range(6):
            for j in range(6):
                value = year_matrix.iloc[i, j]
                ax.text(j, i, f'{value:.2f}', ha='center', va='center', color='white' if abs(value) > .6 else '#172331', fontsize=13)
        ax.set_title(f'ETF daily return correlations · 2026 through {end}', pad=16)
        fig.colorbar(im, ax=ax, label='Pearson correlation', shrink=.8)
        fig.savefig(charts / 'return_correlations_2026.png', dpi=160)
        plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), constrained_layout=True)
    for symbol in protocol['symbols']:
        vol = returns[symbol].rolling(63, min_periods=63).std() * np.sqrt(252) * 100
        axes[0].plot(vol.index, vol, label=symbol, linewidth=1)
    axes[0].set(title='Trailing 63-session annualized volatility', ylabel='Volatility (%)')
    axes[0].legend(ncol=6)
    for a, b in [('SPY', 'IWM'), ('SPY', 'TLT'), ('SPY', 'GLD'), ('IEF', 'TLT')]:
        corr = returns[a].rolling(63, min_periods=63).corr(returns[b])
        axes[1].plot(corr.index, corr, label=f'{a}/{b}', linewidth=1)
    axes[1].axhline(0, color='grey', linewidth=.7)
    axes[1].set(title='Trailing 63-session return correlations', ylabel='Correlation', ylim=(-1, 1))
    axes[1].legend(ncol=4)
    for ax in axes:
        ax.grid(alpha=.15)
        ax.set_xlim(returns.index.min(), returns.index.max())
    fig.suptitle(f'Time-varying risk relationships · {period_label}', fontsize=15)
    fig.savefig(charts / 'rolling_risk.png', dpi=160)
    plt.close(fig)
    structural = all(not q['missing_sessions'] and not q['non_session_dates'] and not q['duplicate_dates']
                     and not any(q['missing_by_field'].values()) and not q['nonfinite_price_cells']
                     and not q['nonpositive_price_cells'] and not q['negative_volume_rows'] and not q['ohlc_violation_rows']
                     for q in quality.values())
    summary = {'status': 'exploration completed; formal data qualification remains outstanding',
               'generated_at_utc': datetime.now(timezone.utc).isoformat(),
               'specification_sha256': manifest['specification_sha256'], 'protocol_sha256': manifest['protocol_sha256'],
               'scope': {'protocol_version': protocol['version'], 'analysis_start': protocol['distribution_scoring_start'],
                         'analysis_end': end, 'latest_completed_session_target': protocol.get('latest_completed_session', end),
                         'latest_common_available_session': min(q['last_date'] for q in quality.values()),
                         'historical_holdout_explored': protocol.get('historical_holdout_explored', False)},
               'calendar': {'name': 'XNYS', 'version': xcals.__version__, 'expected_sessions': len(sessions),
                            'analysis_sessions': len(dev), 'early_close_sessions': int(early.sum()),
                            'exceptional_closures_checked': checked_closures},
               'quality': quality, 'structural_checks_pass': structural,
               'distributions': distributions, 'timing': timing, 'corporate_action_checks': event_checks,
               'pearson': pearson.to_dict(), 'spearman': spearman.to_dict(), 'pair_counts': counts.to_dict(),
               'lagged_correlations': lag_rows, 'volume_relationships': volume_rows,
               'rolling_correlation_summary': rolling_rows, 'flagged_observation_count': len(anomaly_rows),
               'window_summaries': window_summaries, 'window_distributions': window_rows,
               'latest_session_snapshots': latest_snapshots, 'current_week_start': week_start.date().isoformat(),
               'strategy_performance_calculated': False,
               'holdout_observations_analyzed': int((returns.loc[protocol.get('former_holdout_start', '2016-01-01'):].notna().sum().sum())) if protocol.get('historical_holdout_explored') else 0,
               'limitations': ['Current public snapshot, not historical point-in-time vintages.',
                               'OHLC not qualified as unadjusted executable prices.',
                               'No dividend payment dates, historical dissemination timestamps, spreads, or auction-fill evidence.',
                               'Current survivor ETF universe; no claim about a point-in-time stock universe.',
                               'Commercial reuse authorization not established; formal source unchanged.']}
    (out / 'eda_summary.json').write_text(json.dumps(clean(summary), indent=2, allow_nan=False) + '\n')
    lines = ['# Current-horizon ETF data exploration' if protocol.get('historical_holdout_explored') else '# Development-period ETF data exploration', '',
             'Completed October 8, 2026 (Asia/Shanghai). The hypothesis and rejection rules were fixed before these checks. No strategy backtest or parameter search was performed.', '',
             f"Source: Yahoo Finance public daily chart snapshot. Requested bars: {start} through {end}. Statistical summaries: {period_label}. Latest common available session: {summary['scope']['latest_common_available_session']}.", '',
             'Historical validation/holdout periods are now exploratory at the user\'s request; they are not untouched confirmatory evidence.' if protocol.get('historical_holdout_explored') else 'Validation and holdout observations from 2016 onward are excluded.', '',
             f"Calendar: {len(sessions):,} expected sessions; {len(dev):,} analysis sessions; {int(early.sum())} half days. Known historical closures are checked explicitly.", '',
             '## Missingness and structural checks', '',
             '| ETF | Rows | Missing sessions | Missing cells | OHLC violations | Zero-volume days |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for symbol, q in quality.items():
        lines.append(f"| {symbol} | {q['rows']} | {len(q['missing_sessions'])} | {sum(q['missing_by_field'].values())} | {q['ohlc_violation_rows']} | {q['zero_volume_rows']} |")
    lines += ['', 'No forward filling, winsorization, or deletion of flagged market extremes was applied.', '',
              '## Return distributions', '',
              '| ETF | Annualized volatility | 1st percentile daily return | 99th percentile daily return | Skewness | Excess kurtosis |',
              '| --- | ---: | ---: | ---: | ---: | ---: |']
    for symbol, d in distributions.items():
        lines.append(f"| {symbol} | {d['annualized_volatility_pct']:.2f}% | {d['p01_pct']:.2f}% | {d['p99_pct']:.2f}% | {d['skewness']:.2f} | {d['excess_kurtosis']:.2f} |")
    lines += ['', '![Return distributions](charts/return_distributions.png)', '',
              'These are distributions of individual ETF adjusted-close returns, not strategy returns. Tail flags are review candidates, not proof of bad data.', '',
              f"SPY excess kurtosis is {distributions['SPY']['excess_kurtosis']:.2f}; EFA is {distributions['EFA']['excess_kurtosis']:.2f}. This sample has substantial tails and is not well described by a fixed Gaussian return model. No extreme-value cleaning is justified by distribution shape alone.", '',
              '## Outliers and volume checks', '',
              f"The prespecified checks flagged {len(anomaly_rows)} asset/session observations. All remain in the evidence. Examples include SPY {distributions['SPY']['max_pct']:+.2f}% on {distributions['SPY']['max_date']}, IWM {distributions['IWM']['min_pct']:+.2f}% on {distributions['IWM']['min_date']}, and GLD {distributions['GLD']['min_pct']:+.2f}% on {distributions['GLD']['min_date']}. These large moves require independent corroboration before formal evidence qualification.", '',
              f"IEF has {distributions['IEF']['volume_above_10x_lagged_median']} observations above ten times its preceding 20-session median volume. These flags could reflect actual trading or data problems; this single-source snapshot cannot decide between them. Median shares traded per session and return/relative-volume relationships are in volume_relationships.csv.", '',
              '## Relationships', '', matrix_markdown(pearson), '',
              '![Return correlations](charts/return_correlations.png)', '',
              f"SPY/IWM correlation is {pearson.loc['SPY', 'IWM']:.2f}, SPY/EFA is {pearson.loc['SPY', 'EFA']:.2f}, and IEF/TLT is {pearson.loc['IEF', 'TLT']:.2f}. Multiple ETF tickers do not imply independent exposures. SPY/TLT is {pearson.loc['SPY', 'TLT']:.2f} and SPY/GLD is {pearson.loc['SPY', 'GLD']:.2f} over this sample, but their rolling correlations vary materially.", '',
              'Same-session relationships are descriptive. Annual and rolling correlations, Spearman correlations, sample counts, within-asset lags, and volume relationships are exported separately. They do not establish predictive ability.', '',
              '![Rolling risk](charts/rolling_risk.png)', '', '## Timing and adjustments', '',
              'Daily timestamps are converted to America/New_York before assigning session dates. A bar labelled 09:30 represents a full daily bar; it was not available at 09:30. Features based on its close require completed-session data and a later eligible execution session.', '',
              'Yahoo adjusted close incorporates splits and dividends. Event/adjustment checks are descriptive reconciliation against the same provider, not an independent validation. The raw response can contain dynamic current quote metadata; that metadata is excluded from all analysis.', '',
              f"Across dividend-paying ETFs, adjustment-factor changes reconcile with the reported distributions to a maximum difference of {max(e['dividend_factor_reconciliation_max_error_bps'] or 0 for e in event_checks.values()):.4f} basis points. No significant factor changes lack a reported dividend. Closing-price and adjusted-close daily returns differ by up to {event_checks['EFA']['close_vs_adjusted_return_difference_max_bps'] / 100:.2f} percentage points for EFA, showing why dividend handling matters. This does not verify dividend payment dates or historical adjustment vintages.", '',
              '## Qualification decision', '',
              f"Structural checks pass: {structural}. The snapshot is suitable for this descriptive exploration only. The original formal-data requirements remain outstanding: point-in-time revisions, qualified raw execution prices, dividend payment dates, historical release timing, independent source checks, and applicable data rights.", '',
              'No hypothesis, window, threshold, universe, cost assumption, or rejection criterion was changed after exploration.', '',
              'Sources: [Yahoo adjusted-close definition](https://in.help.yahoo.com/kb/adjusted-close-sln28256.html); [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars); [NYSE trading calendar](https://www.nyse.com/trade/hours-calendars); [Nasdaq Sandy closure notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2012-44).', '',
              f"Detailed evidence: eda_summary.json, flagged_observations.csv, largest_moves.csv, return_distributions.csv, correlation_*.csv, annual_correlations.csv, rolling_correlation_summary.csv, lagged_correlations.csv, volume_relationships.csv, expected_sessions.csv, and {data_dir.relative_to(ROOT)}/manifest.json.", '']
    if latest_snapshots:
        lines += ['## Current year and recent sessions', '',
                  f"The 2026 summary runs through {end}. Recent windows use the same return, distribution and relationship definitions as the main study. This week has only {latest_snapshots[0]['completed_week_sessions']} completed sessions; its bars are a freshness check, not enough observations for a reliable distribution or Sharpe estimate.", '',
                  '| ETF | 2026 observations | 2026 annualized volatility | 2026 daily 1st percentile | 2026 daily 99th percentile |',
                  '| --- | ---: | ---: | ---: | ---: |']
        for row in window_rows:
            if row['window'] == 'Year_2026':
                lines.append(f"| {row['symbol']} | {row['observations']} | {row['annualized_volatility_pct']:.2f}% | {row['p01_pct']:.2f}% | {row['p99_pct']:.2f}% |")
        lines += ['', '![2026 correlations](charts/return_correlations_2026.png)', '',
                  '| ETF | Latest session | Latest daily asset return | Week-to-date asset return | Trailing 63-session volatility |',
                  '| --- | --- | ---: | ---: | ---: |']
        for row in latest_snapshots:
            lines.append(f"| {row['symbol']} | {row['latest_session']} | {row['daily_asset_return_pct']:+.2f}% | {row['week_to_date_asset_return_pct']:+.2f}% | {row['trailing_63_session_volatility_pct']:.2f}% |")
        lines += ['', 'Week-to-date returns compound the completed daily adjusted-close returns from the preceding week\'s last close. These are asset observations, not simulated trading-strategy profits. Full weekly OHLCV bars are in current_week_bars.csv. Detailed window comparisons are in subperiod_distributions.csv and subperiod_correlations.csv.', '']
    (out / 'EDA_REPORT.md').write_text('\n'.join(lines))
    files = sorted(p for p in out.rglob('*') if p.is_file() and p.name not in {'evidence_checksums.json', 'verification.json'} and p.suffix != '.log')
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in files}
    (out / 'evidence_checksums.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps(clean({'calendar': summary['calendar'], 'structural_checks_pass': structural,
                           'flagged_observations': len(anomaly_rows), 'distributions': distributions,
                           'pearson': pearson.to_dict(), 'corporate_action_checks': event_checks}), indent=2))


if __name__ == '__main__':
    main()
