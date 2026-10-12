"""Authentic Docker checks, enabled only with an explicitly pinned local image.

These execute generated probe programs only through DockerSandbox. They do not
use model services, private data or a broker. Fake canaries are test inputs.
"""
from pathlib import Path
from unittest.mock import patch
import json
import os
import subprocess
import tempfile
import time
import unittest

from quant_agent.common import GateError
from quant_agent.sandbox import DockerSandbox


IMAGE = os.environ.get("QUANT_SANDBOX_IMAGE", "")


@unittest.skipUnless(IMAGE, "Set QUANT_SANDBOX_IMAGE to validate an actual Docker image")
class SandboxIntegrationTests(unittest.TestCase):
    def run_code(self, code, context=None, **options):
        with DockerSandbox(code, IMAGE, **options) as sandbox:
            return sandbox.step(context or {})

    def test_real_security_settings_and_only_strategy_mount(self):
        code = '''
import os
def target_weights(context,state):
    values = {}
    for line in open('/proc/self/status'):
        if line.startswith(('CapEff:', 'NoNewPrivs:')):
            key,value = line.split(':',1); values[key] = value.strip()
    return {'weights':{}, 'state':{'uid':os.getuid(), **values}}
'''
        with DockerSandbox(code, IMAGE) as sandbox:
            result = sandbox.step({})
            info = json.loads(subprocess.check_output(["docker", "inspect", sandbox.name], text=True))[0]
            settings = info["HostConfig"]
            self.assertEqual(settings["NetworkMode"], "none")
            self.assertTrue(settings["ReadonlyRootfs"])
            self.assertEqual(settings["Memory"], 512*1024**2)
            self.assertEqual(settings["MemorySwap"], 512*1024**2)
            self.assertEqual(settings["NanoCpus"], 1_000_000_000)
            self.assertEqual(settings["PidsLimit"], 64)
            self.assertEqual(settings["CapDrop"], ["ALL"])
            self.assertIn("no-new-privileges", settings["SecurityOpt"])
            self.assertEqual(len(info["Mounts"]), 1)
            self.assertEqual(info["Mounts"][0]["Destination"], "/strategy.py")
            self.assertFalse(info["Mounts"][0]["RW"])
            self.assertEqual(info["Config"]["Image"], IMAGE)
            self.assertEqual(result["state"], {"uid":65534, "CapEff":"0000000000000000", "NoNewPrivs":"1"})

    def test_external_network_is_unreachable(self):
        code = '''
import socket,os
def target_weights(context,state):
    s=socket.socket(); s.settimeout(1)
    try: s.connect(('203.0.113.1',443)); blocked=False
    except OSError: blocked=True
    finally: s.close()
    return {'weights':{}, 'state':{'blocked':blocked,'interfaces':sorted(os.listdir('/sys/class/net'))}}
'''
        self.assertEqual(self.run_code(code)["state"], {"blocked":True,"interfaces":["lo"]})

    def test_kernel_cgroup_limits_match_the_declared_budget(self):
        code='''
def target_weights(context,state):
    limits={name:open('/sys/fs/cgroup/'+name).read().strip() for name in ('memory.max','pids.max','cpu.max')}
    return {'weights':{},'state':limits}
'''
        state=self.run_code(code)["state"]
        self.assertEqual(state["memory.max"],str(512*1024**2));self.assertEqual(state["pids.max"],"64")
        quota,period=map(int,state["cpu.max"].split());self.assertEqual(quota,period)

    def test_host_canary_and_credentials_are_not_exposed(self):
        with tempfile.TemporaryDirectory(prefix="quant-canary-") as directory:
            path=Path(directory)/"fake-secret.txt";path.write_text("fake canary, not a credential")
            code = '''
import os
def target_weights(context,state):
    try: open(context['host_path']).read(); blocked=False
    except OSError: blocked=True
    return {'weights':{},'state':{'blocked':blocked,'credential_inherited':'QUANT_TEST_FAKE_SECRET' in os.environ,
                                 'docker_socket':os.path.exists('/var/run/docker.sock')}}
'''
            with patch.dict(os.environ,{"QUANT_TEST_FAKE_SECRET":"fake-only"}):
                state=self.run_code(code,{"host_path":str(path)})["state"]
            self.assertEqual(state,{"blocked":True,"credential_inherited":False,"docker_socket":False})

    def test_root_and_strategy_are_read_only(self):
        code='''
def target_weights(context,state):
    blocked=[]
    for path in ('/strategy.py','/runner.py','/root-test'):
        try:
            with open(path,'w') as file: file.write('probe')
        except OSError: blocked.append(path)
    return {'weights':{},'state':{'blocked':blocked}}
'''
        self.assertEqual(len(self.run_code(code)["state"]["blocked"]),3)

    def test_tmp_is_writable_but_not_executable(self):
        code='''
import os,subprocess
def target_weights(context,state):
    path='/tmp/probe.sh'
    with open(path,'w') as file: file.write('#!/bin/sh\\nexit 0\\n')
    os.chmod(path,0o755)
    try: subprocess.run([path],check=True); blocked=False
    except OSError: blocked=True
    return {'weights':{},'state':{'writable':os.path.exists(path),'execution_blocked':blocked}}
'''
        self.assertEqual(self.run_code(code)["state"],{"writable":True,"execution_blocked":True})

    def test_file_size_and_open_file_limits_are_enforced(self):
        code='''
import os,resource
def target_weights(context,state):
    try:
        with open('/tmp/large','wb') as file: file.write(b'x'*(2*1024**2))
        blocked=False
    except OSError: blocked=True
    descriptors=[]
    try:
        for i in range(100): descriptors.append(os.open('/dev/null',os.O_RDONLY))
    except OSError: pass
    for fd in descriptors: os.close(fd)
    return {'weights':{},'state':{'size_blocked':blocked,'size':os.path.getsize('/tmp/large'),
                                 'opened':len(descriptors),'limit':list(resource.getrlimit(resource.RLIMIT_NOFILE))}}
'''
        state=self.run_code(code)["state"]
        self.assertTrue(state["size_blocked"]);self.assertLessEqual(state["size"],1024**2)
        self.assertLess(state["opened"],64);self.assertEqual(state["limit"],[64,64])

    def test_process_limit_is_enforced(self):
        code='''
import os,time
def target_weights(context,state):
    children=[]; blocked=False
    try:
        for i in range(100):
            try: pid=os.fork()
            except OSError: blocked=True; break
            if pid==0: time.sleep(30); os._exit(0)
            children.append(pid)
        return {'weights':{},'state':{'blocked':blocked,'children':len(children)}}
    finally:
        for pid in children:
            try: os.kill(pid,9);os.waitpid(pid,0)
            except OSError: pass
'''
        state=self.run_code(code)["state"]
        self.assertTrue(state["blocked"]);self.assertLess(state["children"],64)

    def test_excess_memory_terminates_container(self):
        code='''
def target_weights(context,state):
    allocation=bytearray(800*1024**2)
    return {'weights':{},'state':{'allocated':len(allocation)}}
'''
        with self.assertRaises(GateError): self.run_code(code,timeout=8)

    def test_hung_code_times_out_and_is_removed(self):
        code='''
def target_weights(context,state):
    while True: pass
'''
        start=time.monotonic(); sandbox=DockerSandbox(code,IMAGE,timeout=2)
        try:
            with self.assertRaises(GateError): sandbox.step({})
        finally: sandbox.close()
        self.assertLess(time.monotonic()-start,18)
        result=subprocess.run(["docker","inspect",sandbox.name],capture_output=True)
        self.assertNotEqual(result.returncode,0)

    def test_malformed_stdout_and_api_fail_closed(self):
        for code in ("print('invalid-json',flush=True)\ndef target_weights(c,s): return {'weights':{},'state':{}}",
                     "def target_weights(c,s): return {'weights':{},'extra':1}"):
            with self.subTest(code=code),self.assertRaises(GateError): self.run_code(code)

    def test_nonfinite_or_oversized_state_fails_closed(self):
        for value in ("float('nan')", "'x'*65000"):
            with self.subTest(value=value),self.assertRaises(GateError):
                self.run_code(f"def target_weights(c,s): return {{'weights':{{}},'state':{{'x':{value}}}}}")

    def test_output_quotas_are_enforced(self):
        line="print('x'*110000,flush=True)\ndef target_weights(c,s): return {'weights':{},'state':{}}"
        with self.assertRaises(GateError): self.run_code(line)
        code="def target_weights(c,s): return {'weights':{},'state':{'x':'x'*600}}"
        with DockerSandbox(code,IMAGE,output_bytes=1000) as sandbox:
            sandbox.step({})
            with self.assertRaises(GateError): sandbox.step({})

    def test_random_seeds_and_checkpoint_replay(self):
        code='''
import random,numpy as np
def target_weights(context,state):
    return {'weights':{'A':0.1},'state':{'draws':[random.random(),float(np.random.random())]}}
'''
        self.assertEqual(self.run_code(code),self.run_code(code))
        stateful='''
def target_weights(context,state):
    total=state.get('total',0)+context['value']
    return {'weights':{'A':0.1},'state':{'total':total}}
'''
        with DockerSandbox(stateful,IMAGE) as sandbox:
            checkpoint=sandbox.step({"value":2})["state"]
            continuation=sandbox.step({"value":3})
        self.assertEqual(continuation,self.run_code(stateful,{"value":3},initial_state=checkpoint))

    def test_incremental_asof_context_has_no_future_file(self):
        code='''
import os
def target_weights(context,state):
    return {'weights':{},'state':{'asof':context['asof'],'rows':len(context['history']),
                                 'full_data_available':os.path.exists('/data/bars.csv'),
                                 'last_seen':state.get('asof')}}
'''
        with DockerSandbox(code,IMAGE) as sandbox:
            first=sandbox.step({"asof":"2026-10-08T20:30:00Z","history":[1,2]})["state"]
            second=sandbox.step({"asof":"2026-10-09T20:30:00Z","history":[1,2,3]})["state"]
        self.assertFalse(first["full_data_available"]);self.assertEqual(first["rows"],2)
        self.assertEqual(second["last_seen"],first["asof"]);self.assertEqual(second["rows"],3)


if __name__=="__main__": unittest.main()
