"""Retain only reviewed fixed JSON markers; never print or save raw Actions logs."""
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = 'JihuiTanUchicago/kalshi_trade'
MARKER = re.compile(r'TAU_HEADER_ALIGNMENT_(PREFLIGHT|INVENTORY|RESULTS|PUBLIC|INVALIDATION|ERROR|PHASE)=(\{.*\})\s*$')


def command(*args):
    response = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if response.returncode:
        raise RuntimeError('ReceiptRequestFailed') from None
    return response.stdout


def records(raw):
    result = []
    for line in raw.splitlines():
        match = MARKER.search(line)
        if match:
            try:
                receipt = json.loads(match[2])
            except ValueError:
                raise RuntimeError('InvalidFixedReceipt') from None
            if not isinstance(receipt, dict):
                raise RuntimeError('InvalidFixedReceipt') from None
            result.append({'type': match[1], 'receipt': receipt})
    return result


def collect(run, expected, destination):
    if not re.fullmatch(r'[1-9][0-9]{0,19}', run) or not re.fullmatch(r'[0-9a-f]{40}', expected):
        raise RuntimeError('ExactOperationPinRequired')
    meta = json.loads(command('gh', 'run', 'view', run, '--repo', REPO, '--json',
                              'databaseId,status,conclusion,headSha,url'))
    if meta.get('headSha') != expected:
        raise RuntimeError('OperationHeadMismatch')
    if meta.get('status') != 'completed':
        return {'workflow': meta, 'records': []}
    raw = command('gh', 'run', 'view', run, '--repo', REPO, '--log')
    result = {'workflow': meta, 'records': records(raw)}
    raw = None
    if not result['records']:
        raise RuntimeError('FixedReceiptUnavailable')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / ('DEPLOYMENT_' + run + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('Usage: collect.py RUN_ID EXACT_OPERATIONS_SHA OUTPUT_DIRECTORY')
    try:
        print(json.dumps(collect(sys.argv[1], sys.argv[2], Path(sys.argv[3])), indent=2))
    except Exception:
        print(json.dumps({'status': 'receipt_collection_requires_inspection'}))
        raise SystemExit(1)
