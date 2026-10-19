"""Bounded real-provider/tool-protocol probes; never invoke the model or actions."""
import contextlib
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/opt/kalshi')
WINDOW_START = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 10, 16, 14, 10, tzinfo=timezone.utc)
# Verification must use the actual worker environment, with no injected keys or flags.
PROVIDER_FIELDS = ('APCA_API_KEY_ID', 'APCA_API_SECRET_KEY', 'MASSIVE_API_KEY', 'DATABENTO_API_KEY', 'EXA_API_KEY')
SETTING_NAMES = ('ALPACA_DATA_ENDPOINT','TAU_MARKET_DATA_PRIMARY','TAU_DATABENTO_ENABLED','TAU_DATABENTO_DEFAULT_DATASET',
                 'TAU_DATABENTO_DATASETS','TAU_DATABENTO_MAX_COST_USD','TAU_ALPACA_ENABLED','TAU_ALPACA_FEED',
                 'TAU_ALPACA_SYMBOLS','TAU_MASSIVE_ENABLED','TAU_MASSIVE_FX_FEED','TAU_MASSIVE_FX_SYMBOLS',
                 'TAU_MASSIVE_DATASETS','TAU_EXA_ENABLED','TAU_EXA_HISTORICAL_ENABLED')


def summarize(packet):
    """Keep counts/provenance, never prices, article excerpts or raw API bodies."""
    result = {k: packet[k] for k in (
        'provider', 'kind', 'status', 'code', 'feed', 'dataset', 'timeframe',
        'retrieved_at', 'start', 'end_exclusive', 'requested_start',
        'requested_end_exclusive', 'availability_clipped', 'complete',
        'estimated_cost_usd', 'reserved_cost_usd', 'budget_limit_usd',
        'download_started', 'cache_hit', 'observation_count', 'last_observation_date',
        'snapshot_as_of', 'temporal_basis', 'reported_cost_usd', 'request_id',
        'excluded_after_cutoff', 'historical_ranking', 'qualified_backtest_features',
        'scripted_model_calls', 'real_model_calls', 'knowledge_receipt_count',
        'historical', 'historical_current_data_blocked', 'secret_in_model_context',
    ) if k in packet}
    if isinstance(packet.get('sources'), list):
        sources = packet['sources']
        result.update(source_count=len(sources),
                      source_hosts=sorted({s.get('publisher_host') for s in sources if s.get('publisher_host')}),
                      sources_with_excerpts=sum(bool(s.get('excerpt')) for s in sources),
                      source_hashes=[s.get('content_sha256') for s in sources[:3]])
    if isinstance(packet.get('bars'), dict):
        result['bar_counts'] = {s: len(rows) for s, rows in packet['bars'].items()}
        result['completed_intervals_only'] = all(
            row.get('interval_end', '') <= packet.get('end_exclusive', '')
            for rows in packet['bars'].values() for row in rows)
    if isinstance(packet.get('symbols'), dict):
        result['symbols'] = {s: {k: row[k] for k in ('status', 'count', 'bar_count',
                             'first_timestamp', 'last_timestamp', 'last_interval_end', 'first_bar', 'last_completed_at') if k in row}
                             for s, row in packet['symbols'].items()}
    if isinstance(packet.get('snapshots'), dict):
        result['snapshots'] = {}
        for symbol, snap in packet['snapshots'].items():
            item = {k: snap[k] for k in ('status', 'stale', 'usable', 'reason') if k in snap}
            for name in ('latest_trade', 'latest_quote'):
                if isinstance(snap.get(name), dict):
                    item[name] = {k: snap[name][k] for k in ('timestamp', 'fresh', 'stale', 'age_seconds', 'usable') if k in snap[name]}
            result['snapshots'][symbol] = item
        if packet.get('asset_class') == 'us_option':
            contracts = list(packet['snapshots'].values())
            result.update(option_contract_count=len(contracts),
                          contracts_with_iv=sum(c.get('implied_volatility') is not None for c in contracts),
                          contracts_with_greeks=sum(bool(c.get('greeks')) for c in contracts))
    if isinstance(packet.get('contracts'), list):
        result.update(contract_count=len(packet['contracts']),
                      contracts_with_iv=sum(c.get('implied_volatility') is not None for c in packet['contracts']),
                      contracts_with_greeks=sum(bool(c.get('greeks')) for c in packet['contracts']))
    if isinstance(packet.get('observations'), list):
        rows = packet['observations']
        result.update(observation_count=len(rows), last_observation_date=rows[-1].get('date') if rows else None,
                      observation_fields=sorted({k for row in rows for k in row if k != 'date'}))
    if isinstance(packet.get('latest_values'), dict):
        result['latest_field_dates'] = {k: v.get('observation_date') for k, v in packet['latest_values'].items()}
    return result


def actual_worker_environment():
    pid = int(subprocess.check_output(['systemctl', 'show', 'recursive-agents', '--property=MainPID', '--value'], text=True).strip())
    if pid <= 0:
        raise RuntimeError('NoRunningWorker')
    proc = Path('/proc') / str(pid)
    env = dict(item.decode('utf-8', 'replace').split('=', 1)
               for item in (proc / 'environ').read_bytes().split(b'\0') if b'=' in item)
    if (proc / 'cwd').resolve() != ROOT:
        raise RuntimeError('UnexpectedWorkerDirectory')
    return pid, env


def run_checks(credentials=None):
    pid, original_env = actual_worker_environment()
    credentials = {name: original_env.get(name, '') for name in PROVIDER_FIELDS}
    if not all(credentials.values()):
        raise RuntimeError('ActualWorkerProviderCredentialsMissing')
    os.environ.clear()
    os.environ.update(original_env)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    logging.disable(logging.CRITICAL)
    from app.alpaca_data import AlpacaDataClient, Config as AlpacaConfig
    from app.massive_data import MassiveDataClient, Config as MassiveConfig
    from app.databento_data import DatabentoDataClient, Config as DatabentoConfig, CostBudget
    from app.agent_market_data import AgentMarketData, DataScope, _freshness
    from app.agent_knowledge import AgentKnowledge
    from app.llm import Usage
    from app import agent_market_data as market_module

    # Diagnostic pacing only; no product quota or service setting changes.
    last_massive_request = [0.0]
    def pace_massive():
        remaining = 13 - (time.monotonic() - last_massive_request[0])
        if remaining > 0:
            time.sleep(remaining)
        last_massive_request[0] = time.monotonic()
    original_massive_client = MassiveDataClient
    def paced_massive_client(config, **kwargs):
        callback = kwargs.pop('checkpoint', lambda: None)
        def combined():
            callback()
            pace_massive()
        return original_massive_client(config, checkpoint=combined, **kwargs)
    market_module.MassiveDataClient = paced_massive_client

    output = {'mode': 'production_provider_verification', 'source_host': 'production_web_box',
              'worker_pid_for_environment': pid, 'production_worker_modified': False,
              'credentials_source': 'actual_worker_proc_environment', 'model_backend': 'scripted_no_llm',
              'database_or_order_actions': False, 'actual_worker_settings': {name: original_env.get(name) for name in SETTING_NAMES},
              'diagnostic_massive_request_spacing_seconds': 13,
              'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': [], 'events': []}
    from app.market_data_config import check_configuration
    output['actual_worker_preflight'] = check_configuration(original_env)
    if not output['actual_worker_preflight']['ready']:
        raise RuntimeError('ActualWorkerProviderConfigurationInvalid')
    if original_env.get('TAU_EXA_ENABLED') != '1' or original_env.get('TAU_EXA_HISTORICAL_ENABLED') != '1':
        raise RuntimeError('ActualWorkerExaActivationMissing')
    active_bridge = [None]
    def error_result(exc):
        return {'status': 'unavailable', 'code': getattr(exc, 'code', type(exc).__name__),
                'error_class': type(exc).__name__}
    def check(name, operation):
        started = time.monotonic()
        try:
            # Suppress library stdout/stderr; only the summary leaves this process.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                packet = operation()
            receipt = summarize(packet)
            empty = (('bar_counts' in receipt and not any(receipt['bar_counts'].values()))
                     or ('observation_count' in receipt and receipt['observation_count'] == 0)
                     or ('source_count' in receipt and receipt['source_count'] == 0)
                     or ('option_contract_count' in receipt and receipt['option_contract_count'] == 0))
            receipt.setdefault('status', 'missing' if empty else 'available')
        except Exception as exc:
            packet, receipt = None, error_result(exc)
        output['checks'].append({'name': name, 'elapsed_seconds': round(time.monotonic()-started, 3), **receipt})
        return packet
    def event(kind, message, packet=None):
        if isinstance(packet, dict):
            packet = packet.get('market_data', packet)
            if isinstance(packet, dict):
                output['events'].append({'event_kind': kind, 'bridge': active_bridge[0], **summarize(packet)})

    # Small fixed Friday windows avoid conflating closed-market freshness with auth.
    with AlpacaDataClient(AlpacaConfig.from_env()) as client:
        check('alpaca_current_snapshot', lambda: _freshness({'status': 'available', **client.snapshots(['SPY'])}, datetime.now(timezone.utc)))
        check('alpaca_completed_history', lambda: client.bars(['SPY'], WINDOW_START, WINDOW_END, timeframe='1Min'))
    with paced_massive_client(MassiveConfig.from_env()) as client:
        check('massive_fx_history', lambda: client.fx_bars(['EURUSD'], WINDOW_START, WINDOW_END, timeframe='1Min'))
        for dataset in ('treasury_yields', 'funding_conditions'):
            check('massive_' + dataset, lambda dataset=dataset: client.macro(dataset,
                  datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 17, tzinfo=timezone.utc)))
    output['checks'].extend([
        {'name': 'massive_options_chain', 'status': 'disabled_configuration', 'reason': 'prior_live_entitlement_denial'},
        {'name': 'massive_current_fx', 'status': 'disabled_configuration', 'reason': 'prior_live_entitlement_denial'},
    ])
    config = DatabentoConfig.from_env()
    with DatabentoDataClient(config, budget=CostBudget(config.max_cost_usd)) as client:
        for dataset, symbol in (('EQUS.MINI', 'SPY'), ('GLBX.MDP3', 'ESZ6')):
            check('databento_estimate_' + dataset, lambda dataset=dataset, symbol=symbol:
                  client.estimate([symbol], dataset, WINDOW_START, WINDOW_END, timeframe='1Min'))
            check('databento_bars_' + dataset, lambda dataset=dataset, symbol=symbol:
                  client.bars([symbol], dataset, WINDOW_START, WINDOW_END, timeframe='1Min'))

    def bridge(name, historical):
        active_bridge[0] = name
        scope = DataScope.research(int(WINDOW_START.timestamp()), int(WINDOW_END.timestamp())) if historical else DataScope()
        usage, stage = Usage(), {'index': 0, 'calls': 0, 'secret_leak': False}
        knowledge = AgentKnowledge(scope, event)
        market = AgentMarketData(scope, event)
        def model(system, messages):
            stage['calls'] += 1
            text = system + json.dumps(messages)
            stage['secret_leak'] |= any(v and v in text for v in credentials.values())
            index = stage['index']
            stage['index'] += 1
            if index == 0:
                requests = [{'kind': 'publications' if historical else 'search',
                             'query': 'prediction market probability calibration research' if historical else 'Federal Reserve monetary policy October 2026'}]
                if not historical:
                    requests.append({'kind': 'publications', 'query': 'prediction market probability calibration research'})
                obj = {'knowledge_requests': requests}
            elif index == 1:
                sources = [s for p in knowledge.receipts for s in p.get('sources', [])]
                if sources:
                    obj = {'knowledge_requests': [{'kind': 'contents', 'source_id': sources[0]['source_id']}]}
                else:
                    # Provider denial must not prevent testing the market bridge.
                    stage['index'] = 3
                    return model_market_request(2), {'input_tokens': 0, 'output_tokens': 0}
            elif index == 2:
                return model_market_request(index), {'input_tokens': 0, 'output_tokens': 0}
            elif index == 3 and historical:
                return model_market_request(index), {'input_tokens': 0, 'output_tokens': 0}
            else:
                obj = {'reply': 'Provider smoke test complete.', 'actions': []}
            return json.dumps(obj), {'input_tokens': 0, 'output_tokens': 0}
        def model_market_request(index):
            if index == 3:
                requests = [
                    {'provider': 'databento', 'kind': 'bars', 'dataset': 'EQUS.MINI', 'symbols': ['SPY'], 'timeframe': '1Min', 'lookback_days': 1},
                    {'provider': 'databento', 'kind': 'bars', 'dataset': 'GLBX.MDP3', 'symbols': ['ESZ6'], 'timeframe': '1Min', 'lookback_days': 1},
                ]
            elif historical:
                requests = [
                    {'provider': 'alpaca', 'kind': 'bars', 'symbols': ['SPY'], 'timeframe': '1Min', 'lookback_days': 1},
                    {'provider': 'massive', 'kind': 'fx_bars', 'symbols': ['EURUSD'], 'timeframe': '1Min', 'lookback_days': 1},
                ]
            else:
                requests = [
                    {'provider': 'alpaca', 'kind': 'snapshots', 'symbols': ['SPY']},
                    {'provider': 'massive', 'kind': 'fx_bars', 'symbols': ['EURUSD'], 'timeframe': '1Hour', 'lookback_days': 7},
                ]
            return json.dumps({'market_data_requests': requests})
        result = market.ask(knowledge.wrap(model, usage), 'Read-only diagnostic. Return no actions.',
                            [{'role': 'user', 'content': 'Verify provider tool receipts.'}], lambda obj: obj, usage)
        if result.get('actions') != []:
            raise RuntimeError('UnexpectedActionPayload')
        if stage['secret_leak']:
            raise RuntimeError('SecretInModelContext')
        receipt = {'provider': 'agent_tool_bridge', 'status': 'protocol_completed', 'kind': name,
                   'scripted_model_calls': stage['calls'], 'real_model_calls': 0,
                   'knowledge_receipt_count': len(knowledge.receipts),
                   'secret_in_model_context': stage['secret_leak'],
                   'historical': historical, 'snapshot_as_of': scope.cutoff.isoformat() if historical else None}
        if historical:
            guards = [market._read({'provider': 'alpaca', 'kind': 'snapshots', 'symbols': ['SPY']}),
                      market._read({'provider': 'massive', 'kind': 'options_chain', 'symbols': ['SPY']})]
            receipt['historical_current_data_blocked'] = all(p.get('code') == 'time_boundary' for p in guards)
            if not receipt['historical_current_data_blocked']:
                raise RuntimeError('HistoricalBoundaryNotEnforced')
        return receipt
    check('current_agent_tool_bridge', lambda: bridge('current', False))
    check('historical_agent_tool_bridge', lambda: bridge('historical', True))
    # Include only credential-free summaries; never print actual result payloads.
    serialized = json.dumps(output, default=str)
    if any(v and v in serialized for v in credentials.values()):
        raise RuntimeError('SecretInReceipt')
    return output
