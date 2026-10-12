"""Fetch only observations authorized by the selected exploration protocol."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import csv
import hashlib
import json
import argparse

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'docs/RESEARCH_SPECIFICATION.md'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', default='research/eda_protocol_current.json')
    args = parser.parse_args()
    protocol_path = ROOT / args.protocol
    protocol = json.loads(protocol_path.read_text())
    start = datetime.fromisoformat(protocol['requested_start']).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(protocol['requested_end_exclusive']).replace(tzinfo=timezone.utc)
    data_dir = ROOT / protocol.get('data_directory', 'data')
    raw_dir = data_dir / 'raw'
    csv_dir = data_dir / 'normalized'
    manifest_path = data_dir / 'manifest.json'
    prior = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if prior and prior['protocol_sha256'] != digest(protocol_path):
        raise ValueError('A different protocol requires a fresh data directory.')
    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    def fetch(symbol):
        raw_path = raw_dir / f'{symbol}.json'
        query = urlencode({'period1': int(start.timestamp()), 'period2': int(end.timestamp()),
                           'interval': '1d', 'events': 'div,splits', 'includeAdjustedClose': 'true'})
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}'
        if raw_path.exists():
            body = raw_path.read_bytes()
            fetched = 'cached response; see first manifest'
        else:
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40) as response:
                body = response.read()
            fetched = datetime.now(timezone.utc).isoformat()
        chart = json.loads(body)['chart']
        if chart.get('error') or not chart.get('result'):
            raise ValueError(f'{symbol}: provider error {chart.get("error")}')
        result = chart['result'][0]
        meta = result['meta']
        assert meta['symbol'] == symbol
        assert meta['currency'] == 'USD'
        assert meta['exchangeTimezoneName'] == 'America/New_York'
        timestamps = result['timestamp']
        quote = result['indicators']['quote'][0]
        adjusted = result['indicators']['adjclose'][0]['adjclose']
        rows = []
        for i, timestamp in enumerate(timestamps):
            moment = datetime.fromtimestamp(timestamp, timezone.utc)
            local = moment.astimezone(ZoneInfo('America/New_York'))
            if not (protocol['requested_start'] <= local.date().isoformat() < protocol['requested_end_exclusive']):
                raise ValueError(f'{symbol}: out-of-scope observation {local}')
            rows.append({'date': local.date().isoformat(), 'timestamp_utc': moment.isoformat(),
                         **{field: quote[field][i] for field in ['open', 'high', 'low', 'close', 'volume']},
                         'adjusted_close': adjusted[i]})
        if not raw_path.exists():
            raw_path.write_bytes(body)
        csv_path = csv_dir / f'{symbol}.csv'
        with csv_path.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        # Dynamic current-quote metadata is retained in the raw response for provenance,
        # but never exported into analysis or used for statistics.
        return {'symbol': symbol, 'url': url, 'retrieved_at_utc': fetched,
                'raw_path': str(raw_path.relative_to(ROOT)), 'raw_sha256': digest(raw_path),
                'normalized_path': str(csv_path.relative_to(ROOT)), 'normalized_sha256': digest(csv_path),
                'rows': len(rows), 'first_date': rows[0]['date'], 'last_date': rows[-1]['date'],
                'currency': meta['currency'], 'exchange_timezone': meta['exchangeTimezoneName'],
                'events': {key: len(value) for key, value in result.get('events', {}).items()}}

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(fetch, protocol['symbols']))
    for record in records:
        if record['retrieved_at_utc'].startswith('cached'):
            previous = next((r for r in prior.get('files', []) if r['symbol'] == record['symbol']), {})
            record['retrieved_at_utc'] = previous.get('retrieved_at_utc', record['retrieved_at_utc'])
    manifest = {'provider': 'Yahoo Finance public chart response', 'role': 'exploratory proxy',
                'commercial_reuse_authorization': 'not established',
                'point_in_time_revision_history': 'unavailable',
                'adjustment_note': 'Adjusted close includes dividend and split adjustments; OHLC is not guaranteed raw historical executable price.',
                'raw_metadata_note': 'Raw responses contain current quote metadata; it is excluded from the analysis.',
                'protocol_path': str(protocol_path.relative_to(ROOT)),
                'protocol_sha256': digest(protocol_path), 'specification_sha256': digest(SPEC), 'files': records}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'files': [{k: r[k] for k in ['symbol', 'rows', 'first_date', 'last_date']} for r in records]}, indent=2))


if __name__ == '__main__':
    main()
