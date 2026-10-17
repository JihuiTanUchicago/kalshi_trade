"""Tier-2 strategy sandbox: a true isolation boundary for arbitrary agent-authored code.

Each test asserts that a documented escape is BLOCKED (SandboxError), that the resource caps
fire, and that legitimate numeric/numpy code still runs. The whole point is that code which can
read the Kalshi keys, reach the DB, open a socket, escape the scratch dir, or burn unbounded
CPU/mem must be structurally unable to do so.
"""
import os
import time

import pytest

from app import sandbox
from app.sandbox import SandboxError, StrategyCodeError

WIN = {"market": "btc15m", "frames": [{"ts": 1, "contracts": []}]}

# Executing a strategy needs a kernel confiner; without one the sandbox is default-deny (tested
# separately). Tests that must actually RUN the child are skipped where no confiner exists.
needs_confiner = pytest.mark.skipif(not sandbox.os_sandbox_available(),
                                    reason="no OS-level sandbox (sandbox-exec/bwrap/firejail) here")


def _run(body, **kw):
    """body is the inside of signals(window); returns one empty pick-list per frame by default."""
    code = "def signals(window):\n" + "\n".join("    " + ln for ln in body.splitlines())
    kw.setdefault("cpu_s", 3)
    kw.setdefault("wall_s", 8)
    return sandbox.run_strategy_signals(code, WIN, **kw)


# -- happy paths ---------------------------------------------------------------


@needs_confiner
def test_pure_python_strategy_runs():
    out = _run("return [[] for _ in window['frames']]")
    assert out == [[]]


@needs_confiner
def test_numpy_strategy_runs():
    code = ("import numpy as np\n"
            "def signals(window):\n"
            "    return [[{'ticker': 't', 'side': 'yes', 'score': float(np.tanh(1.0))}]"
            "            for _ in window['frames']]")
    out = sandbox.run_strategy_signals(code, WIN, cpu_s=5, wall_s=12)
    assert out[0][0]["side"] == "yes" and out[0][0]["score"] > 0


# -- isolation: no imports outside the numeric allowlist -----------------------


@pytest.mark.parametrize("mod", ["os", "sys", "socket", "subprocess", "pathlib", "ctypes",
                                 "importlib", "shutil", "builtins"])
def test_dangerous_imports_blocked(mod):
    # Rejected statically before anything runs (also enforced at runtime by the import gate).
    with pytest.raises(StrategyCodeError):
        sandbox.validate_strategy_code("import %s\ndef signals(w): return []" % mod)


@pytest.mark.parametrize("mod", ["numpy", "pandas", "scipy", "sklearn", "statsmodels",
                                 "xgboost", "lightgbm", "arch", "cvxpy", "torch", "tensorflow"])
def test_scientific_stack_allowed(mod):
    # The ML/stat stack passes static validation (install-independent): agents can write real models.
    sandbox.validate_strategy_code("import %s\ndef signals(w): return []" % mod)
    assert mod in sandbox.STRATEGY_ALLOWED_IMPORTS


def test_no_network_socket():
    with pytest.raises(SandboxError):
        _run("import socket\n return [socket.socket()]")


def test_cannot_place_order_via_subprocess():
    with pytest.raises(SandboxError):
        _run("import subprocess\n subprocess.run(['/bin/echo', 'order'])\n return []")


# -- isolation: no filesystem / no credentials --------------------------------


@needs_confiner
def test_open_round_trips_in_data_dir(tmp_path):
    # open() IS available now (scoped file access): a strategy can write + read back a file in the
    # mounted data dir, so it can persist/reload datasets and model artifacts across runs.
    body = ("p = window['data_dir'] + '/t.txt'\n"
            "f = open(p, 'w')\nf.write('hi')\nf.close()\n"
            "v = open(p).read()\n"
            "return [[{'v': v}]]")
    out = sandbox.run_strategy_signals("def signals(window):\n" +
                                       "\n".join("    " + ln for ln in body.splitlines()),
                                       WIN, cpu_s=5, wall_s=12, data_dir=str(tmp_path))
    assert out == [[{"v": "hi"}]]


@needs_confiner
def test_data_dir_scoped_per_strategy(tmp_path):
    # A strategy writes a "secret" into its data dir; a DIFFERENT strategy (different code) must
    # NOT be able to read it back — the per-strategy keying isolates hypotheses from each other.
    writer = ("def signals(window):\n"
              "    open(window['data_dir'] + '/leak.txt', 'w').write('from-strategy-A')\n"
              "    return [[{'wrote': 1}]]")
    reader = ("def signals(window):\n"
              "    try:\n"
              "        v = open(window['data_dir'] + '/leak.txt').read()\n"
              "    except Exception:\n"
              "        v = 'isolated'\n"
              "    return [[{'saw': v}]]")
    base = str(tmp_path)
    sandbox.run_strategy_signals(writer, WIN, cpu_s=5, wall_s=12, data_dir=base)
    out = sandbox.run_strategy_signals(reader, WIN, cpu_s=5, wall_s=12, data_dir=base)
    assert out == [[{"saw": "isolated"}]]          # reader can't see writer's file


@needs_confiner
def test_data_dir_persists_for_same_strategy(tmp_path):
    # The SAME strategy code reloads its own artifact across runs (per-strategy persistence works).
    code = ("def signals(window):\n"
            "    p = window['data_dir'] + '/state.txt'\n"
            "    try:\n"
            "        prev = open(p).read()\n"
            "    except Exception:\n"
            "        prev = 'first'\n"
            "    open(p, 'w').write('seen')\n"
            "    return [[{'prev': prev}]]")
    base = str(tmp_path)
    assert sandbox.run_strategy_signals(code, WIN, cpu_s=5, wall_s=12, data_dir=base) == [[{"prev": "first"}]]
    assert sandbox.run_strategy_signals(code, WIN, cpu_s=5, wall_s=12, data_dir=base) == [[{"prev": "seen"}]]


@needs_confiner
def test_open_cannot_write_outside_scratch(tmp_path):
    # open() is scoped by the confiner: the read-only root (anywhere but scratch + the data dir) is
    # not writable, so an attempt to write there fails -> SandboxError.
    target = str(tmp_path.parent / "escape_write.txt")
    with pytest.raises(SandboxError):
        _run("open(%r, 'w').write('x')\nreturn [[]]" % target)


def test_cannot_read_env_credentials(monkeypatch):
    # Even with a secret in the PARENT env, the scrubbed child env + blocked os import means the
    # strategy has no route to it (and `import os` is rejected before the child even runs).
    monkeypatch.setenv("PROD_KEYID", "SUPER-SECRET-KEY")
    with pytest.raises(SandboxError):
        _run("import os\n return [os.environ.get('PROD_KEYID')]")


# -- isolation: the KERNEL boundary (what actually stops a numpy/stdlib gadget) ------
# These exploits bypass the Python layer on purpose (non-dunder module attrs reach the real
# os/sys; importlib bypasses the __import__ gate). The OS confiner must still contain them.


@needs_confiner
def test_os_confiner_blocks_credential_read(tmp_path):
    cred_dir = tmp_path / "credentials"
    cred_dir.mkdir()
    (cred_dir / "kalshi.pem").write_text("PRIVATE-KEY-MATERIAL")
    # random._os is the real os module; its path matches the secret-read deny rule.
    code = ("import random\n _os = random._os\n"
            " return [_os.read(_os.open(%r, 0), 64).decode('utf-8', 'replace')]"
            % str(cred_dir / "kalshi.pem"))
    with pytest.raises(SandboxError):  # kernel denies the read -> PermissionError -> SandboxError
        _run(code)


@needs_confiner
def test_os_confiner_blocks_socket_via_importlib_bypass():
    # collections._sys -> sys -> sys.modules['importlib'].import_module('socket') defeats the
    # import allowlist entirely; the kernel's network deny is what actually stops the connection.
    code = ("import collections\n _sys = collections._sys\n"
            " il = _sys.modules['importlib']\n socket = il.import_module('socket')\n"
            " c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            " c.connect(('127.0.0.1', 1))\n return [1]")
    with pytest.raises(SandboxError):
        _run(code)


def test_default_deny_when_no_confiner(monkeypatch):
    # With no OS sandbox available, untrusted code is REFUSED rather than run unconfined.
    monkeypatch.setattr(sandbox, "_confiner", lambda: None)
    with pytest.raises(SandboxError):
        _run("return [[] for _ in window['frames']]")


@needs_confiner
def test_cannot_escape_scratch_dir_write(tmp_path):
    scratch = str(tmp_path)
    # Writing outside the scratch dir is denied by the confiner (open is also removed, so reach
    # the real os via a stdlib attr to even attempt it).
    target = str(tmp_path.parent / "outside_write.txt")
    code = ("import random\n _os = random._os\n"
            " return [_os.write(_os.open(%r, _os.O_WRONLY | _os.O_CREAT), b'x')]" % target)
    with pytest.raises(SandboxError):
        _run(code, scratch_dir=scratch)
    assert not os.path.exists(target)


def test_dunder_escape_blocked():
    # The classic ().__class__.__bases__[0].__subclasses__() gadget is refused statically.
    with pytest.raises(StrategyCodeError):
        sandbox.validate_strategy_code("def signals(w): return [().__class__.__bases__]")


# -- isolation: resource caps --------------------------------------------------


@needs_confiner
def test_cpu_cap_kills_runaway_loop():
    start = time.time()
    with pytest.raises(SandboxError):
        _run("x = 0\n while True:\n  x += 1", cpu_s=1, wall_s=15)
    assert time.time() - start < 14  # the CPU cap fired well before the wall-clock backstop


@needs_confiner
def test_wall_clock_cap_fires():
    with pytest.raises(SandboxError):
        # busy-spin so RLIMIT_CPU would eventually fire too, but the short wall-clock wins first
        _run("import math\n x = 0.0\n while True:\n  x += math.sqrt(2.0)", cpu_s=30, wall_s=1)


@needs_confiner
def test_memory_cap_blocks_hog():
    if not sandbox._applied_limits().get("RLIMIT_AS"):
        pytest.skip("RLIMIT_AS not settable on this OS (macOS dev); enforced on Linux/CI")
    with pytest.raises(SandboxError):
        # request ~2GB under a 256MB cap
        _run("b = bytearray(2 * 1024 * 1024 * 1024)\n return [len(b)]",
             mem_bytes=256 * 1024 * 1024, cpu_s=10, wall_s=15)


# -- malformed code / output --------------------------------------------------


def test_missing_signals_function_rejected():
    with pytest.raises(StrategyCodeError):
        sandbox.validate_strategy_code("def other(w): return []")


@needs_confiner
def test_strategy_exception_becomes_sandbox_error():
    with pytest.raises(SandboxError):
        _run("return 1 / 0")


def test_oversized_code_rejected():
    with pytest.raises(StrategyCodeError):
        sandbox.validate_strategy_code("def signals(w):\n return []\n# " + "x" * 20_001)
