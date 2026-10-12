"""Bounded read-only auction audit; preserve the frozen bar import."""
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'research'))
from fetch_alpaca import SetupError, load_config
from fetch_alpaca_enrichment import fetch_json
import requests

OUT = Path(__file__).resolve().parent
if (OUT/'receipt.json').exists() or any(OUT.glob('raw_*.json')):
    raise SystemExit('Existing auction evidence is preserved; use a new audit destination for another capture.')
SYMBOLS = ('SPY','QQQ','IWM')
EXCHANGES = {'SPY':'P','QQQ':'T','IWM':'P'}
url = 'https://data.alpaca.markets/v2/stocks/auctions'
params = {'symbols':','.join(SYMBOLS),'start':'2020-03-01','end':'2020-04-01','limit':1000,'feed':'sip'}
receipt = {'quality':'proxy','purpose':'Current-vintage diagnostic of one stress month; no qualification or strategy changes',
           'requests':[],'files':{},'original_import_unchanged':True,'orders_submitted':0}
try:
    config = load_config(ROOT/'.env')
    tokens=set(); auctions={symbol:[] for symbol in SYMBOLS}
    with requests.Session() as session:
        session.headers.update({'APCA-API-KEY-ID':config.key,'APCA-API-SECRET-KEY':config.secret})
        for page in range(5):
            result=fetch_json(session,url,params)
            path=OUT/f'raw_{page:03d}.json'
            with path.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False)
            receipt['files'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            receipt['requests'].append({'url':url,'params':dict(params),'retrieved_at':datetime.now(timezone.utc).isoformat(),'http_status':200})
            for symbol,rows in result['auctions'].items():auctions[symbol].extend(rows)
            token=result.get('next_page_token')
            if not token:break
            if token in tokens:raise SetupError('Repeated auction page token')
            tokens.add(token);params={**params,'page_token':token}
        else:raise SetupError('Five-page auction audit budget exhausted')
    with (ROOT/'data/alpaca_snapshots/20261010T140939.395972Z/daily_raw.csv').open() as stream:
        bars={(r['symbol'],r['session']):float(r['close']) for r in csv.DictReader(stream)}
    reference={}
    for symbol in SYMBOLS:
        doc=json.loads((ROOT/f'data/alpaca_enrichment/20261010_ordered_build/independent_{symbol}.json').read_text())['chart']['result'][0]
        for stamp,price in zip(doc['timestamp'],doc['indicators']['quote'][0]['close']):
            day=datetime.fromtimestamp(stamp,ZoneInfo('America/New_York')).date().isoformat()
            if price is not None:reference[symbol,day]=float(price)
    comparisons=[];missing=[]
    for symbol,days in auctions.items():
        for row in days:
            # Select the listing venue, then the last correction/update on it.
            matches=[a for a in row.get('c',[]) if a['x']==EXCHANGES[symbol]]
            if not matches:missing.append({'symbol':symbol,'session':row['d']});continue
            closing=max(matches,key=lambda a:a['t']);day=row['d'];key=(symbol,day)
            if key not in bars or key not in reference:continue
            auction=float(closing['p']);bar=bars[key];independent=reference[key]
            comparisons.append({'symbol':symbol,'session':day,'listing_venue':EXCHANGES[symbol],
                'auction_close':auction,'alpaca_daily_close':bar,'independent_close':independent,
                'auction_vs_independent_over_5bp':abs(auction-independent)/auction>.0005,
                'bar_vs_independent_over_5bp':abs(bar-independent)/bar>.0005,
                'bar_vs_auction_over_5bp':abs(bar-auction)/bar>.0005})
    receipt.update({'status':'complete','matched_symbol_sessions':len(comparisons),'missing_listing_close':missing,
         'auction_vs_independent_over_5bp':sum(r['auction_vs_independent_over_5bp'] for r in comparisons),
         'bar_vs_independent_over_5bp':sum(r['bar_vs_independent_over_5bp'] for r in comparisons),
         'bar_vs_auction_over_5bp':sum(r['bar_vs_auction_over_5bp'] for r in comparisons),
         'comparisons':comparisons,'listing_exchange_mapping_is_operator_assumption':True,
         'broader_176_disagreements_resolved':False,'historical_original_availability_established':False,
         'commercial_rights_reviewed':False})
except (SetupError,KeyError,ValueError,TypeError,OSError) as error:
    receipt.update({'status':'failed','error':str(error) if isinstance(error,SetupError) else type(error).__name__})
finally:
    receipt['completed_at']=datetime.now(timezone.utc).isoformat()
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k not in ('comparisons','requests','files')},indent=2))
