"""No-network integrity check of complete packaged current-main source."""
import hashlib
import json
from pathlib import Path
import subprocess
HERE=Path(__file__).resolve().parent
manifest=json.loads((HERE/'manifest.json').read_text())
source=subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD','--','kalshi_trade_infra/app','kalshi_trade_infra/data_pipeline'],text=True).splitlines()
actual={}
for name in source:
    raw=subprocess.check_output(['git','show','HEAD:'+name])
    actual[name.removeprefix('kalshi_trade_infra/')]=hashlib.sha256(raw).hexdigest()
if actual!=manifest['release']:raise SystemExit('Current-main runtime manifest mismatch')
print(json.dumps({'runtime_manifest_matches':True,'release_sha':manifest['release_sha'],'files':len(actual)}))
