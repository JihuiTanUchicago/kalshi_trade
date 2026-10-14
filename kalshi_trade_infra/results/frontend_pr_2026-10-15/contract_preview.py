"""Actual app.server GET handlers with a synthetic repository; POSTs disabled.
Run from infra root. No DB, providers, workers, payments or trading are accessed.
Control /tmp/tau-frontend-pr-profile.json: admin / card_required booleans.
"""
import copy
import io
import json
import time
import re
from pathlib import Path
import sys
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app import server, spec

FIXTURES = json.loads(Path(__file__).with_name('HTTP_FIXTURES.json').read_text())
UI_FIXTURES = json.loads(Path(__file__).with_name('UI_FIXTURES.json').read_text())
PROFILE = Path('/tmp/tau-frontend-pr-profile.json')
REQUESTS = Path('/tmp/tau-frontend-pr-requests.jsonl')

def profile():
    return json.loads(PROFILE.read_text()) if PROFILE.exists() else {}


def user():
    return {'id':1, 'name':'Contract preview', 'email':'operator@preview.invalid' if profile().get('admin') else 'trader@preview.invalid', 'picture_url':None, 'autopilot':False}


class Cursor:
    def execute(self, sql, params=None):
        assert sql.lstrip().upper().startswith('SELECT'), 'Writes forbidden in contract preview'
        self.sql = sql

    def fetchone(self):
        return {'n':42}

    def fetchall(self):
        if 'GROUP BY status' in self.sql:
            return [{'status':'running','c':1},{'status':'succeeded','c':3}]
        if 'FROM app_users' in self.sql:
            return [{**user(),'created_at':'2026-10-14T06:00:00Z','balance':98.4}]
        return []


class Connection:
    def cursor(self): return Cursor()
    def close(self): pass


raw_strategies = []
for row in FIXTURES['/api/strategies']['strategies']:
    full = FIXTURES[f"/api/strategies/{row['id']}"]
    normalized = spec.validate({'market':row['market'], 'side':row.get('side','yes'), 'sizing':{'stake':row.get('stake',10), 'max_positions':2}})
    raw_strategies.append({**row, 'spec':normalized, 'result':{k:full.get(k) for k in ['in_sample','out_of_sample','equity','capital','gates','dataset','recent_trades']}})
raw_deps = [{**d,'spec':{'sizing':{'stake':d['stake'],'max_positions':d['max_positions']}},'result':d['backtest']} for d in FIXTURES['/api/deployments']['deployments']]

def strategies(cur, uid, direction=None, status=None, market=None, limit=500, run_id=None):
    rows = copy.deepcopy(raw_strategies)
    if profile().get('specific_live_reason'):
        rows[0]['side'] = 'no'
        rows[0]['spec']['side'] = 'no'
    if profile().get('many_strategies'):
        for sid in range(20,81):
            row = copy.deepcopy(raw_strategies[0]); row.update(id=sid,title=f'Pagination candidate #{sid}'); rows.append(row)
    if profile().get('extra_artifacts'):
        for sid, parent, title in [(8,1,'Synthetic child revision'),(9,None,'Synthetic standalone artifact'),(10,999,'Synthetic artifact with missing ancestor')]:
            row = copy.deepcopy(raw_strategies[0]); row.update(id=sid,run_id=None,parent_id=parent,title=title); rows.append(row)
    return copy.deepcopy([s for s in rows if uid==1 and (not direction or s['direction']==direction) and (not status or s['status']==status) and (not market or s['market']==market) and (run_id is None or s['run_id']==run_id)][:limit])


server.ADMIN_EMAIL = 'operator@preview.invalid'
server.get_db_conn = Connection
server.billing.configured = lambda: False
server.billing.STRIPE_PUBLISHABLE_KEY = ''
server.engine.LIVE_TRADING_ENABLED = False
server.repo.session_user = lambda *a: user()
server.repo.get_kalshi_key = lambda *a: None
server.repo.credit_balance = lambda *a: 98.4
server.repo.credit_spent_total = lambda *a: 1.6
server.repo.credit_rows = lambda *a: [{'kind':'bonus','amount_usd':100,'memo':'Synthetic welcome credit','created_at':'2026-10-14T06:00:00Z'}]
server.repo.get_stripe_customer = lambda *a: None
server.repo.list_runs = lambda *a: copy.deepcopy(FIXTURES['/api/runs']['runs'])
server.repo.active_run_counts = lambda *a: {**copy.deepcopy(FIXTURES['/api/runs']['counts']), 'chat_active':0}
server.repo.get_run = lambda cur,uid,rid: copy.deepcopy(FIXTURES.get(f'/api/runs/{rid}',{}).get('run')) if uid==1 else None
server.repo.run_events = lambda cur,rid,after: copy.deepcopy([e for e in FIXTURES[f'/api/runs/{rid}']['events'] if e['id']>after])
server.repo.list_strategies = strategies
server.repo.get_strategy = lambda cur,uid,sid: next((s for s in strategies(cur,uid) if s['id']==sid),None)
server.repo.list_deployments = lambda *a: [] if profile().get('empty_deployments') else copy.deepcopy(raw_deps)
server.repo.deployment_curves = lambda *a: {d['id']:d['curve'] for d in raw_deps}
# Core account reads do not invoke providers. Unmodified handlers project these rows.
server.repo.paper_balance = lambda *a: 1000
server.repo.paper_deposits = lambda *a: 1000
server.repo.user_positions = lambda *a: []
server.repo.realized_pnl = lambda *a: 24.8
server.repo.daily_pnl = lambda *a: []
server.repo.history_freshness = lambda *a: {}
server.repo.chat_messages = lambda cur,uid,after: copy.deepcopy([m for m in FIXTURES['/api/chat']['messages'] if m['id']>after])
server.repo.list_posts = lambda *a: [{'id':1,'body':'Synthetic Community post','kind':'text','snapshot':None,'likes_count':0,'comments_count':0,'created_at':'2026-10-14T06:00:00Z','name':'Contract preview','picture_url':None,'mine':True,'liked':False,'reactions':[{'emoji':'🔥','count':2,'mine':True}],'image_id':None,'edited_at':None}]
# Inject the readiness flag only for the browser's unavailable-provider gate case.
original_needs_card = server._needs_card
server._needs_card = lambda ctx: bool(profile().get('card_required')) or original_needs_card(ctx)

def forbid_provider(*a, **k):
    raise AssertionError('Provider operations forbidden in contract preview')
server.billing._stripe = forbid_provider
server.agent.ask_json = forbid_provider


# Every market/rail response is synthetic; no Kalshi or S3 reads are made.
from data_pipeline import common
SAMPLE_TICKER = 'KXBTC15M-SAMPLE'
server._explore_feed = lambda: {'at':'2026-10-15T00:00:00Z','total':1,'shown':1,'markets':[
    {'t':SAMPLE_TICKER,'s':'KXBTC15M','ti':'Synthetic Bitcoin market','su':'$92,300 or above',
     'yb':0.47,'ya':0.49,'last':0.48,'v24':1234,'oi':123,'h':[[1792022400,0.47],[1792022460,0.48]]}
]}
def synthetic_kalshi(path, params=None):
    if path == '/markets/' + SAMPLE_TICKER:
        return {'market':{'title':'Synthetic Bitcoin market','yes_sub_title':'$92,300 or above',
                         'yes_bid_dollars':'0.47','yes_ask_dollars':'0.49','last_price_dollars':'0.48',
                         'status':'open','volume_24h_fp':'1234','open_interest_fp':'123',
                         'open_time':'2026-10-14T00:00:00Z','close_time':'2026-10-15T00:00:00Z'}}
    if path == '/series/KXBTC15M/markets/' + SAMPLE_TICKER + '/candlesticks':
        return {'candlesticks':[{'end_period_ts':1791936000+i*60,'price':{'close_dollars':str(0.47+i/10000)},'volume_fp':'5'} for i in range(121)]}
    raise AssertionError('Provider reads forbidden in contract preview')
common.api_get = synthetic_kalshi


class Preview(server.Handler):
    def cookies(self): return {} if profile().get('signed_out') else {server.auth.SESSION_COOKIE:'synthetic-contract-session'}

    def log_message(self, *a): pass

    def do_GET(self):
        with REQUESTS.open('a') as log:
            log.write(json.dumps({'method':'GET','path':urlsplit(self.path).path})+'\n')
        path = urlsplit(self.path).path
        state = profile()
        if path == '/api/me' and state.get('specific_live_reason'):
            row = copy.deepcopy(FIXTURES['/api/me']); row.update(live_trading_available=True,kalshi_connected=True,needs_card=False,billing_enabled=False,is_admin=False)
            return self._send_json(200,row,[])
        if path == '/api/strategies' and state.get('strategy_failure'):
            return self._send_json(503, {'error':'Synthetic candidate read interruption.'}, [])
        if state.get('delay_strategy_id') and path == '/api/strategies/' + str(state['delay_strategy_id']):
            time.sleep(0.8)
        if state.get('fixture_chat') and re.fullmatch(r'/api/sessions/(?:run|strategy)/\d+/chat',path):
            row = copy.deepcopy(UI_FIXTURES.get(path))
            if row is None: return self._send_json(404, {'error':'No synthetic conversation for this session.'}, [])
            after = int(parse_qs(urlsplit(self.path).query).get('after',['0'])[0])
            row['messages'] = [m for m in row['messages'] if m['id'] > after]
            row['capabilities']['send'] = bool(state.get('fixture_actions'))
            return self._send_json(200,row,[])
        return super().do_GET()

    def do_POST(self):
        with REQUESTS.open('a') as log:
            log.write(json.dumps({'method':'POST','path':urlsplit(self.path).path})+'\n')
        path = urlsplit(self.path).path
        if profile().get('fixture_actions') and re.fullmatch(r'/api/strategies/\d+/whatif',path):
            args = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            sid = int(path.split('/')[3])
            row = copy.deepcopy(UI_FIXTURES['/api/strategies/' + str(sid)])
            time.sleep(0.5)
            delta = float(args.get('fee_multiplier',1)) * 2
            row['out_of_sample']['pnl'] -= delta
            if row.get('gates'): row['gates'][0]['value'] = row['out_of_sample']['pnl']
            row['equity'][-1][1] -= delta
            row['passed'] = True
            return self._send_json(200,row,[])
        if profile().get('fixture_actions') and profile().get('fixture_chat') and re.fullmatch(r'/api/sessions/run/\d+/chat',path):
            args = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            row = UI_FIXTURES[path]
            time.sleep(0.5)
            message = {'id':max(m['id'] for m in row['messages'])+1, 'role':'user', 'content':args['content'], 'strategy_id':args['strategy_id'], 'created_at':'2026-10-14T15:00:00Z', 'proposal_id':None}
            row['messages'].append(message)
            return self._send_json(200, {'session_key':row['session_key'], 'message':message},[])
        if urlsplit(self.path).path == '/api/logout':
            state = profile(); state['signed_out'] = True
            PROFILE.write_text(json.dumps(state))
            return self._send_json(200, {'ok':True}, [])
        return self._send_json(503, {'error':'Contract preview: writes, payments, agents and trading are disabled.'}, [])

    def _send_static(self, path):
        if not server.SPA_ROUTES.match(path):
            return super()._send_static(path)
        renderer = object.__new__(server.Handler)
        renderer.wfile = io.BytesIO()
        renderer._headers = lambda *a: None
        renderer._send_static(path)
        notice = '<aside role="status" style="padding:12px 20px;background:#fff0e8;font:14px system-ui">Actual handlers + optional UI fixtures · sample data · providers and trading disabled</aside>'
        body = renderer.wfile.getvalue().decode().replace('<div id="app"',notice+'<div id="app"',1).encode()
        self._headers(200,'text/html; charset=utf-8',len(body), [('Cache-Control','no-store')])
        self.wfile.write(body)


if __name__ == '__main__':
    http = ThreadingHTTPServer(('127.0.0.1',8096),Preview)
    print('Read-only actual-handler contract preview: http://127.0.0.1:8096',flush=True)
    http.serve_forever()
