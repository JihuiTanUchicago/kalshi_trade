"""Audit saved evidence independently of the EDA calculations and without network."""

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import argparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', default='research/eda_protocol_current.json')
    args = parser.parse_args()
    protocol_path = ROOT / args.protocol
    protocol = json.loads(protocol_path.read_text())
    data_dir = ROOT / protocol.get('data_directory', 'data')
    out = ROOT / protocol.get('output_directory', 'results')
    manifest = json.loads((data_dir / 'manifest.json').read_text())
    summary = json.loads((out / 'eda_summary.json').read_text())
    assert digest(protocol_path) == manifest['protocol_sha256']
    assert digest(ROOT / 'docs/RESEARCH_SPECIFICATION.md') == manifest['specification_sha256']
    reconstructed = {}
    checked = 0
    expected_dates = pd.read_csv(out / 'expected_sessions.csv')['date'].tolist()
    analysis_dates = expected_dates[1:]
    scored_mask = np.array([protocol['distribution_scoring_start'] <= d <= protocol['distribution_scoring_end'] for d in analysis_dates])
    for record in manifest['files']:
        for path_key, hash_key in [('raw_path', 'raw_sha256'), ('normalized_path', 'normalized_sha256')]:
            assert digest(ROOT / record[path_key]) == record[hash_key]
            checked += 1
        raw = json.loads((ROOT / record['raw_path']).read_text())['chart']['result'][0]
        dates = [datetime.fromtimestamp(t, timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                 for t in raw['timestamp']]
        assert len(dates) == len(set(dates)) == record['rows']
        assert dates == sorted(dates)
        assert all(protocol['requested_start'] <= d < protocol['requested_end_exclusive'] for d in dates)
        assert not set(summary['calendar']['exceptional_closures_checked']).intersection(dates)
        if protocol.get('latest_completed_session'):
            assert dates[-1] == protocol['latest_completed_session'], 'Current-session coverage not met.'
        values = np.array(raw['indicators']['adjclose'][0]['adjclose'], dtype=float)
        assert np.isfinite(values).all() and (values > 0).all()
        lookup = dict(zip(dates, values))
        aligned = np.array([lookup.get(d, np.nan) for d in expected_dates])
        change = aligned[1:] / aligned[:-1] - 1
        sample = change[scored_mask]
        valid_sample = sample[np.isfinite(sample)]
        symbol = record['symbol']
        reported = summary['distributions'][symbol]
        assert len(valid_sample) == reported['observations']
        assert np.isclose(np.std(valid_sample, ddof=1) * np.sqrt(252) * 100, reported['annualized_volatility_pct'], atol=1e-10)
        assert np.isclose(np.quantile(valid_sample, .01) * 100, reported['p01_pct'], atol=1e-10)
        assert np.isclose(np.quantile(valid_sample, .99) * 100, reported['p99_pct'], atol=1e-10)
        reconstructed[symbol] = sample
    direct_correlation = np.empty((len(reconstructed), len(reconstructed)))
    direct_counts = np.empty_like(direct_correlation, dtype=int)
    for i, a in enumerate(protocol['symbols']):
        for j, b in enumerate(protocol['symbols']):
            mask = np.isfinite(reconstructed[a]) & np.isfinite(reconstructed[b])
            direct_correlation[i, j] = np.corrcoef(reconstructed[a][mask], reconstructed[b][mask])[0, 1]
            direct_counts[i, j] = mask.sum()
    reported_correlation = pd.read_csv(out / 'correlation_pearson.csv', index_col=0).loc[protocol['symbols'], protocol['symbols']].to_numpy()
    assert np.allclose(direct_correlation, reported_correlation, atol=1e-12)
    scored_dates = np.array(analysis_dates)[scored_mask]
    for window in protocol.get('windows', []):
        mask = np.array([window['start'] <= d <= protocol['distribution_scoring_end'] for d in scored_dates])
        for symbol in protocol['symbols']:
            values = reconstructed[symbol][mask]
            values = values[np.isfinite(values)]
            row = next(r for r in summary['window_distributions'] if r['window'] == window['name'] and r['symbol'] == symbol)
            assert len(values) == row['observations']
            assert np.isclose(np.std(values, ddof=1) * np.sqrt(252) * 100, row['annualized_volatility_pct'], atol=1e-10)
            assert np.isclose(np.quantile(values, .01) * 100, row['p01_pct'], atol=1e-10)
            assert np.isclose(np.quantile(values, .99) * 100, row['p99_pct'], atol=1e-10)
        matrix = pd.read_csv(out / f"correlation_{window['name']}.csv", index_col=0)
        for a in protocol['symbols']:
            for b in protocol['symbols']:
                valid = mask & np.isfinite(reconstructed[a]) & np.isfinite(reconstructed[b])
                correlation = np.corrcoef(reconstructed[a][valid], reconstructed[b][valid])[0, 1]
                assert np.isclose(correlation, matrix.loc[a, b], atol=1e-12)
    for row in summary.get('latest_session_snapshots', []):
        values = reconstructed[row['symbol']]
        week_mask = np.array([summary['current_week_start'] <= d <= protocol['distribution_scoring_end'] for d in scored_dates])
        week = values[week_mask]
        assert len(week) == row['completed_week_sessions']
        assert np.isclose(values[-1] * 100, row['daily_asset_return_pct'], atol=1e-10)
        assert np.isclose((np.prod(1 + week) - 1) * 100, row['week_to_date_asset_return_pct'], atol=1e-10)
        assert np.isclose((np.prod(1 + values[-5:]) - 1) * 100, row['five_session_asset_return_pct'], atol=1e-10)
        assert np.isclose(np.std(values[-63:], ddof=1) * np.sqrt(252) * 100, row['trailing_63_session_volatility_pct'], atol=1e-10)
    pair_counts = pd.read_csv(out / 'correlation_pair_counts.csv', index_col=0)
    assert (pair_counts.to_numpy() == direct_counts).all()
    flags = pd.read_csv(out / 'flagged_observations.csv')
    assert len(flags) == summary['flagged_observation_count']
    assert not flags[['symbol', 'date']].duplicated().any()
    assert summary['strategy_performance_calculated'] is False
    if not protocol.get('historical_holdout_explored'):
        assert summary['holdout_observations_analyzed'] == 0
    else:
        assert summary['scope']['historical_holdout_explored'] is True
    hashes = json.loads((out / 'evidence_checksums.json').read_text())
    for path, expected in hashes.items():
        assert digest(ROOT / path) == expected, f'Output checksum mismatch: {path}'
    result = {'status': 'passed', 'raw_and_normalized_hashes_checked': checked,
              'analysis_output_hashes_checked': len(hashes),
              'independent_raw_response_recomputation': 'return quantiles, volatility and complete Pearson matrix agree',
              'additional_windows_verified': [w['name'] for w in protocol.get('windows', [])],
              'recent_session_tables_verified': bool(summary.get('latest_session_snapshots')),
              'calendar_closures_checked': summary['calendar']['exceptional_closures_checked'],
              'analysis_observations_per_asset': {s: int(np.isfinite(v).sum()) for s, v in reconstructed.items()},
              'latest_completed_session': protocol.get('latest_completed_session'),
              'historical_holdout_explored': protocol.get('historical_holdout_explored', False),
              'holdout_observations_analyzed': summary['holdout_observations_analyzed'],
              'strategy_performance_calculated': False,
              'limitations': 'Arithmetic and provenance verification; not independent market-data-source validation.'}
    (out / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
