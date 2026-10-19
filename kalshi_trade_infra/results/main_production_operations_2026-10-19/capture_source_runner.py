"""Retrieve ciphertext only for private source review; no deployment entry point."""
import hashlib
import json
from pathlib import Path
import subprocess
import uuid
import base64
import re
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from readiness_runner import remote, BUCKET, REGION

HERE = Path(__file__).resolve().parent
STATE = Path('/tmp/tau-source-capture-state.json')


def cleanup(cipher_path):
    if not re.fullmatch(r'/run/tau-encrypted-source-[A-Za-z0-9_-]{4,64}/source.enc.json', cipher_path):
        raise RuntimeError('InvalidCipherPath')
    code = ('from pathlib import Path\nimport json\np=Path(' + repr(cipher_path) + ')\n'
            'p.unlink(missing_ok=True)\n'
            'if p.parent.exists():p.parent.rmdir()\nprint(json.dumps({"ciphertext_removed":True}))\n')
    cleaned = remote(code, 'Tau encrypted source capture cleanup', 60)
    STATE.unlink(missing_ok=True)
    print('TAU_SOURCE_CLEANUP=' + json.dumps(cleaned), flush=True)

if __name__ == '__main__':
    try:
        if '--cleanup' in sys.argv:
            if STATE.exists():
                cleanup(json.loads(STATE.read_text())['cipher_path'])
            else:
                print('TAU_SOURCE_CLEANUP=' + json.dumps({'status': 'no_capture_pending'}), flush=True)
            raise SystemExit(0)
        request = json.loads((HERE / 'capture-request.json').read_text())
        program = (HERE / 'capture_source_remote.py').read_text()
        object_key = 'bundle/tau-source-review-' + uuid.uuid4().hex + '.json'
        program += '\nimport json\ntry:\n r=capture(' + repr(request['public_key']) + ',' + repr(request['hashes']) + ',' + repr(object_key) + ')\n'
        program += 'except Exception as exc:\n r={"status":"capture_failed","error_class":type(exc).__name__}\nprint(json.dumps(r))\n'
        result = remote(program, 'Tau encrypted source-only recovery review', 180)
        print('TAU_SOURCE_CAPTURE=' + json.dumps(result), flush=True)
        if result.get('status') != 'captured_encrypted':
            raise RuntimeError('CaptureRequiresInspection')
        cipher_path = result['cipher_path']
        if not re.fullmatch(r'/run/tau-encrypted-source-[A-Za-z0-9_-]{4,64}/source.enc.json', cipher_path):
            raise RuntimeError('InvalidCipherPath')
        STATE.write_text(json.dumps({'cipher_path': cipher_path}))
        os.chmod(STATE, 0o600)
        target = Path('/tmp/tau-encrypted-source-review')
        target.mkdir(mode=0o700, exist_ok=True)
        output = target / 'source.enc.json'
        try:
            def fetch_chunk(offset):
                code = ('import os,stat,json,base64\n'
                            'fd=os.open(' + repr(cipher_path) + ',os.O_RDONLY|os.O_NOFOLLOW)\n'
                            'try:\n s=os.fstat(fd)\n assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o600\n'
                            ' raw=os.pread(fd,12000,' + str(offset) + ')\n print(json.dumps({"chunk":base64.b64encode(raw).decode()}))\nfinally:\n os.close(fd)\n')
                chunk = remote(code, 'Tau encrypted source chunk ' + str(offset // 12000), 90)
                return base64.b64decode(chunk['chunk'], validate=True)
            with ThreadPoolExecutor(max_workers=4) as executor:
                parts = list(executor.map(fetch_chunk, range(0, result['cipher_bytes'], 12000)))
            with output.open('wb') as stream:
                for raw in parts:
                    stream.write(raw)
            if hashlib.sha256(output.read_bytes()).hexdigest() != result['cipher_sha256']:
                raise RuntimeError('CiphertextDownloadIntegrityFailed')
        finally:
            cleanup(cipher_path)
        (target / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    except Exception as exc:
        print('TAU_SOURCE_ERROR=' + json.dumps({'error_class': type(exc).__name__}), flush=True)
        raise SystemExit(1)
