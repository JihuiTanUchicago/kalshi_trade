"""Two sandboxes for untrusted, agent-authored code, with two different threat models.

This box holds live Kalshi API keys and a production-DB handle, so running code an LLM
wrote is the single highest-risk thing the pipeline does. Isolation is the whole point.

-----------------------------------------------------------------------------------------
TIER 1 — ExplorationPolicy (pure function, in-process). `safe_policy(code)`.
-----------------------------------------------------------------------------------------
A policy is a *pure* function over plain data (a state dict / candidate list -> allocation
decisions). It does no I/O, so it runs in-process behind three layers:
  1. AST validation — reject `import`, and any `__dunder__` name or attribute access. That
     removes the classic in-process escape (`().__class__.__bases__…__subclasses__()`).
  2. Minimal builtins — arithmetic/sorting/containers only. No `__import__`, `open`, `eval`,
     `exec`, `getattr`, `globals`, `compile`, so there is no in-language route to a module.
  3. Timeout + total fallback — bounded wall-clock; ANY violation/error/timeout degrades to
     DefaultPolicy. A hostile policy can only ever burn bounded CPU on data we handed it.

-----------------------------------------------------------------------------------------
TIER 2 — arbitrary-quant strategy code (subprocess, KERNEL-ISOLATED). `run_strategy_signals()`.
-----------------------------------------------------------------------------------------
A strategy may be ANY code the agent writes over the allowlisted scientific-Python stack
(numpy/pandas/scipy/scikit-learn/statsmodels/xgboost/lightgbm/arch/cvxpy/torch/tensorflow) -
its own math/ML/quant framework - and may read/write a scoped, persisted data dir (open() is
allowed; the confiner scopes writes to scratch + /data and masks secrets). You CANNOT securely
sandbox such code inside a Python interpreter: once it can `import numpy` it has
`numpy.ctypeslib.ctypes` and the C ABI, and any allowlisted stdlib
module transitively binds `os`/`sys`/`importlib` through non-dunder attributes
(`random._os`, `collections._sys`, `sys.modules["importlib"].import_module(...)`), so an AST
ban and an import hook are not a boundary — they are speed bumps. The boundary is the OS.

THE BOUNDARY (`_confined_argv`): the child runs under the platform's kernel sandbox, and if
none is available the call is REFUSED (default-deny — untrusted code never runs unconfined):
  * macOS (dev): `sandbox-exec` with a profile that denies ALL network, denies writes anywhere
    but the scratch dir, and denies reads of credential stores (any `…/credentials/…`, `.env`,
    `.pem`, `.ssh`, `.aws`, `id_rsa`/`id_ed25519`, `…/secrets…`).
  * Linux (prod): `bwrap` (`--unshare-net`, read-only root, scratch the only writable mount)
    or `firejail` (`--net=none --read-only=/`). No network -> no DB, no order placement, and
    nothing read can be exfiltrated; the keyfile and DB DSN are inert.
With the kernel enforcing it, even the numpy/ctypes gadget above is harmless: it can compute,
but it cannot open a socket, write outside scratch, or (macOS) read the keys.

DEFENSE IN DEPTH (not the boundary): the child is still a fresh `python -I -B` with a SCRUBBED
env (no PROD_KEYID / KALSHI_* / DB DSN / AWS vars; `-I` ignores PYTHON*/cwd/user-site), a
restricted-builtins + import-gate namespace, the AST dunder/import ban, and resource rlimits
(RLIMIT_CPU hard-kill + parent wall-clock timeout + RLIMIT_AS + FSIZE + NOFILE + CORE=0).
These remove the easy routes and the high-value targets (no secrets, no `conn` object in the
process) so the blast radius is bounded even before the kernel sandbox is considered.

ponytail: the macOS profile denies credential READS directly; the Linux wrappers rely on
`--unshare-net` to make any read inert rather than hiding every secret path (tmpfs-over-secrets
is the follow-up if a non-exfil local read ever matters). RLIMIT_AS is honored on Linux but
refused by the macOS kernel, so the hard memory cap is Linux-only (CPU + wall-clock bound a
runaway allocation on macOS). `os_sandbox_available()` reports whether a confiner exists.
"""
from __future__ import annotations

import ast
import builtins as _builtins
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict
from typing import Callable, Dict, List, Optional

from app.exploration import Batch, DefaultPolicy, ExplorationPolicy, PolicyState


class PolicyError(Exception):
    """The policy code is malformed, unsafe, or misbehaving."""


# Builtins a numeric/list policy legitimately needs. Deliberately excludes
# __import__, open, eval, exec, compile, getattr/setattr, globals/vars, input, …
_SAFE_NAMES = (
    "abs", "min", "max", "sum", "len", "range", "sorted", "list", "dict", "tuple",
    "set", "float", "int", "bool", "round", "enumerate", "zip", "map", "filter",
    "any", "all", "reversed", "str", "divmod", "pow",
)
_SAFE_BUILTINS = {n: getattr(_builtins, n) for n in _SAFE_NAMES}
_TIMEOUT_S = 2.0


def _validate(code: str) -> None:
    """Static gate: no imports, no dunder names or attributes."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise PolicyError("policy does not parse: %s" % e)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise PolicyError("imports are not allowed in a policy")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise PolicyError("dunder attribute access is not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise PolicyError("dunder names are not allowed")


def _call_timed(fn: Callable, *args):
    """Call fn with a wall-clock timeout (main thread only; best-effort elsewhere)."""
    if threading.current_thread() is not threading.main_thread():
        return fn(*args)  # signals need the main thread; other defenses still apply

    def _raise(signum, frame):
        raise TimeoutError("policy exceeded %ss" % _TIMEOUT_S)

    old = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, _TIMEOUT_S)
    try:
        return fn(*args)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


class _SandboxedPolicy(ExplorationPolicy):
    """Wraps LLM-authored `next_batch`/`select_finalists` so every call is bounded
    and output-checked, and falls back to the default on any problem."""

    def __init__(self, next_batch: Callable, select_finalists: Callable):
        self._nb, self._sf = next_batch, select_finalists
        self._default = DefaultPolicy()

    def next_batch(self, state: PolicyState) -> Batch:
        try:
            width = _call_timed(self._nb, asdict(state))
            width = int(width)
            if width < 0:
                raise PolicyError("negative width")
            return Batch(width)
        except Exception:
            return self._default.next_batch(state)

    def select_finalists(self, candidates: List[Dict], state: PolicyState) -> List[Dict]:
        try:
            picked = _call_timed(self._sf, list(candidates), asdict(state))
            # Output must be a subset of the candidates we handed in (by identity).
            allowed = {id(c) for c in candidates}
            out = [c for c in picked if id(c) in allowed]
            if len(out) != len(list(picked)):
                raise PolicyError("select_finalists returned items that were not candidates")
            return out
        except Exception:
            return self._default.select_finalists(candidates, state)


def load_policy(code: str) -> ExplorationPolicy:
    """Validate + compile a policy into a restricted namespace. Raises PolicyError
    if the code is unsafe or does not define the required functions."""
    _validate(code)
    ns: Dict = {"__builtins__": _SAFE_BUILTINS}
    exec(compile(code, "<policy>", "exec"), ns)  # restricted: no real builtins, pre-validated AST
    nb, sf = ns.get("next_batch"), ns.get("select_finalists")
    if not callable(nb) or not callable(sf):
        raise PolicyError("a policy must define next_batch(state) and select_finalists(candidates, state)")
    return _SandboxedPolicy(nb, sf)


def safe_policy(code: str) -> ExplorationPolicy:
    """The never-break entry point: the sandboxed policy if `code` is valid, else
    the DefaultPolicy. Use this everywhere a per-user policy drives research."""
    try:
        return load_policy(code)
    except PolicyError:
        return DefaultPolicy()


# ===========================================================================
# TIER 2 — arbitrary-quant strategy code (subprocess, OS-isolated)
# ===========================================================================


class SandboxError(Exception):
    """Strategy code was rejected, misbehaved, exceeded a limit, or returned bad output."""


class StrategyCodeError(SandboxError):
    """Static validation (parse / allowed imports / required function) failed."""


STRATEGY_ENTRY = "signals"
# Import roots a strategy may use: the numeric stdlib plus the common scientific-Python
# analytics/ML/stat stack, so agents can write real quant models (not just row-wise loops).
# Still NO os, sys, socket, subprocess, io, pathlib, ctypes, importlib, builtins, threading,
# multiprocessing. These scientific libs CAN reach os/ctypes via non-dunder attributes (see the
# module docstring) - that is expected: the allowlist is defense-in-depth, the OS kernel sandbox
# is the boundary, and under `--unshare-net` + read-only-root a pandas/sklearn compute is inert
# (no network, no fs outside scratch, no secrets in the process). Every root must be installed
# in the worker venv (requirements.txt) or an import of it fails closed at runtime.
STRATEGY_ALLOWED_IMPORTS = (
    "math", "cmath", "statistics", "random", "itertools", "functools", "collections",
    "heapq", "bisect", "operator", "decimal", "fractions", "array", "json", "re", "datetime",
    "numpy", "pandas", "scipy", "sklearn", "statsmodels", "joblib",
    "xgboost", "lightgbm", "arch", "cvxpy", "torch", "tensorflow",
)
STRATEGY_MAX_CODE = 20_000          # chars of source
# Limits sized for the scientific/ML stack (torch/tensorflow/sklearn): they dlopen many shared
# libs, spawn BLAS/OpenMP threads, and reserve large virtual address space. Verified empirically
# under bwrap. Code strategies are RESEARCH-ONLY (never the live/paper engine), so a generous
# budget here never touches the trading loop; the wall-clock + CPU caps still bound any runaway.
STRATEGY_CPU_SECONDS = 60           # RLIMIT_CPU (hard kill)
STRATEGY_MEM_BYTES = 12 * 1024 ** 3  # RLIMIT_AS (virtual; TF/torch reserve a lot). Box has 16G RAM.
STRATEGY_WALL_SECONDS = 120.0       # parent kills the child past this
STRATEGY_NOFILE = 4096              # RLIMIT_NOFILE (ML libs dlopen many .so)
STRATEGY_NPROC = 256                # RLIMIT_NPROC (allow BLAS/OpenMP threads; still bounds forks)
STRATEGY_FSIZE_BYTES = 256 * 1024 * 1024  # RLIMIT_FSIZE (model artifacts to the data dir)

# A persistent, writable data directory mounted into the sandbox so strategies can read datasets
# and save/reload model artifacts ACROSS runs (the scoped file access). Secrets are masked out of
# the sandbox regardless of this (see _confined_argv), so file access never exposes keys/DSN/AWS.
STRATEGY_DATA_DIR = os.getenv(
    "APP_STRATEGY_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "strategy_data"))
STRATEGY_DATA_MOUNT = "/data"       # where STRATEGY_DATA_DIR appears inside a Linux (bwrap) sandbox


def validate_strategy_code(code: str) -> None:
    """Static gate (trust boundary): the code parses, defines `signals`, imports only the
    numeric allowlist, and uses no dunder name/attribute (the only in-language route from a
    plain object to a module). Raises StrategyCodeError. Cheap — no execution — so the agent
    gets feedback at proposal time, and it is also the first of the Tier-2 defense layers."""
    if not isinstance(code, str) or not code.strip():
        raise StrategyCodeError("strategy code must be a non-empty string")
    if len(code) > STRATEGY_MAX_CODE:
        raise StrategyCodeError("strategy code exceeds %d chars" % STRATEGY_MAX_CODE)
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise StrategyCodeError("strategy code does not parse: %s" % e)
    allowed = set(STRATEGY_ALLOWED_IMPORTS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in allowed:
                    raise StrategyCodeError("import of %r is not allowed; permitted: %s"
                                            % (a.name, ", ".join(STRATEGY_ALLOWED_IMPORTS)))
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in allowed:
                raise StrategyCodeError("import from %r is not allowed; permitted: %s"
                                        % (node.module, ", ".join(STRATEGY_ALLOWED_IMPORTS)))
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise StrategyCodeError("dunder attribute access is not allowed")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            raise StrategyCodeError("dunder names are not allowed")
    if not any(isinstance(n, ast.FunctionDef) and n.name == STRATEGY_ENTRY
               for n in tree.body):
        raise StrategyCodeError("strategy must define a top-level %s(window) function"
                                % STRATEGY_ENTRY)


# The child process program. Trusted code we write; the UNTRUSTED strategy is read from the
# input file and exec'd behind the import gate + restricted builtins. argv:
#   in_path out_path cpu_s mem_bytes nofile
_RUNNER = r'''
import sys, json, resource, builtins as _b

def _set(res, soft):
    try:
        cur_soft, hard = resource.getrlimit(res)
        cap = soft if hard == resource.RLIM_INFINITY else min(soft, hard)
        resource.setrlimit(res, (cap, hard))
    except (ValueError, OSError):
        pass  # e.g. macOS refuses RLIMIT_AS; other caps + wall-clock still bound the child

in_path, out_path = sys.argv[1], sys.argv[2]
cpu_s, mem_bytes, nofile = int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
nproc, fsize = int(sys.argv[6]), int(sys.argv[7])
_set(resource.RLIMIT_CPU, cpu_s)
_set(resource.RLIMIT_AS, mem_bytes)
_set(resource.RLIMIT_FSIZE, fsize)
_set(resource.RLIMIT_NOFILE, nofile)
_set(resource.RLIMIT_CORE, 0)
try:
    # Bounded, not zero: the scientific/ML stack spawns BLAS/OpenMP worker threads (threads count
    # against NPROC on Linux). A finite cap still bounds a fork bomb; CPU + wall-clock bound compute.
    _set(resource.RLIMIT_NPROC, nproc)
except Exception:
    pass

with open(in_path) as _f:
    _job = json.load(_f)
allowed = set(_job["allowed"])

# Pre-import the allowlisted modules with the REAL importer so numpy's own internal imports
# (os, ctypes, ...) happen now, before the gate is installed; afterwards they are cached.
for _m in allowed:
    try:
        __import__(_m)
    except Exception:
        pass

_orig_import = _b.__import__
def _gate(name, *a, **k):
    if name.split(".")[0] not in allowed:
        raise ImportError("import of %r is blocked in the strategy sandbox" % name)
    return _orig_import(name, *a, **k)

# Restricted builtins: no eval/exec/compile/getattr/setattr/globals/vars/input/__import__ escape.
# `__import__` is the gate so `import numpy` works for the allowlist only. `open` IS allowed (the
# scoped file access the user asked for): the kernel confiner makes writes land only in scratch +
# the mounted /data dir, reads of the root are secret-masked, and there is no network, so a strategy
# can persist/reload datasets and models but cannot reach keys/DSN/AWS or exfiltrate.
_SAFE = ("abs min max sum len range sorted list dict tuple set frozenset float int bool round "
         "enumerate zip map filter any all reversed str bytes bytearray divmod pow complex slice "
         "isinstance issubclass hash repr format print iter next ord chr open").split()
_bi = {n: getattr(_b, n) for n in _SAFE}
for _exc in ("Exception ValueError TypeError KeyError IndexError ZeroDivisionError "
             "ArithmeticError RuntimeError StopIteration OverflowError FloatingPointError").split():
    _bi[_exc] = getattr(_b, _exc)
_bi["__import__"] = _gate
# `class` statements compile to a __build_class__ call; needed so strategies may define classes.
# Safe: it only builds a class object, and the dunder-attribute AST ban blocks the escape routes.
_bi["__build_class__"] = _b.__build_class__
_bi["True"], _bi["False"], _bi["None"] = True, False, None

ns = {"__builtins__": _bi, "__name__": "strategy"}
try:
    exec(compile(_job["code"], "<strategy>", "exec"), ns)
    fn = ns.get(_job["entry"])
    if not callable(fn):
        raise RuntimeError("strategy does not define a callable %s" % _job["entry"])
    result = fn(_job["window"])
    out = {"signals": result}
except Exception as e:
    out = {"error": "%s: %s" % (type(e).__name__, e)}
with open(out_path, "w") as _f:
    json.dump(out, _f, default=lambda o: None)
'''


_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
# Credential stores a strategy must never read (macOS SBPL regex; Linux relies on --unshare-net).
_SECRET_READ_REGEX = r'(/credentials/|\.env|\.pem|/\.ssh/|/\.aws/|id_rsa|id_ed25519|/secrets)'


def _secret_mask_targets() -> "tuple[List[str], List[str]]":
    """(files, dirs) under the project root the Linux confiner masks (bind /dev/null over files,
    tmpfs over dirs) so strategy code with file access still cannot read keys / DB DSN / AWS creds.
    AWS creds via IMDS are already inert under --unshare-net; this closes the on-disk .env/key path."""
    import glob
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = sorted(p for p in glob.glob(os.path.join(root, ".env*")) if os.path.isfile(p))
    dirs = [d for d in (os.path.join(root, "credentials"),) if os.path.isdir(d)]
    return files, dirs


def _macos_profile(scratch: str, data_dir: Optional[str] = None) -> str:
    """Allow-default, then subtract: no network, no writes outside scratch (+ the data dir), no
    credential reads. (SBPL rules are last-match-wins, so the later allow re-permits writes.)
    `scratch`/`data_dir` are interpolated raw, so they must be safe absolute paths (validated by the
    caller) to avoid SBPL injection; writes are narrowed to scratch (+ its realpath, for the
    /var -> /private/var symlink), the data dir, and a couple of device nodes."""
    real = os.path.realpath(scratch)
    scratch_rules = '(subpath "%s")' % scratch + ('' if real == scratch else ' (subpath "%s")' % real)
    if data_dir:
        dreal = os.path.realpath(data_dir)
        scratch_rules += ' (subpath "%s")' % data_dir + ('' if dreal == data_dir else ' (subpath "%s")' % dreal)
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny network*)\n"
        '(deny file-write* (subpath "/"))\n'
        '(allow file-write* %s (literal "/dev/null") (literal "/dev/urandom") '
        '(literal "/dev/random") (literal "/dev/dtracehelper"))\n'
        '(deny file-read* (regex #"%s"))\n'
        % (scratch_rules, _SECRET_READ_REGEX)
    )


def _safe_scratch(scratch: str) -> str:
    """A scratch path must be absolute and free of SBPL/argv-hostile characters before it is
    interpolated into the sandbox profile. Prod scratch is tempfile.mkdtemp (always safe); this
    guards against any future caller forwarding an untrusted scratch_dir."""
    if not os.path.isabs(scratch) or any(c in scratch for c in '"\n\\()'):
        raise SandboxError("unsafe scratch dir %r" % scratch)
    return scratch


def _confiner() -> Optional[str]:
    """Which OS-level sandbox is available here, or None."""
    if sys.platform == "darwin" and os.path.exists(_SANDBOX_EXEC):
        return "sandbox-exec"
    for tool in ("bwrap", "firejail"):
        if shutil.which(tool):
            return tool
    return None


def os_sandbox_available() -> bool:
    return _confiner() is not None


def _confined_argv(inner: List[str], scratch: str, data_dir: Optional[str] = None) -> List[str]:
    """Wrap the child python argv in the kernel sandbox (the real boundary). Raises SandboxError
    if no confiner exists, so untrusted code is NEVER run unconfined (default-deny). `data_dir`,
    when given, is mounted read-write (at STRATEGY_DATA_MOUNT on Linux) for persisted datasets /
    model artifacts, and the project's secret files/dirs are masked so file access can't read keys."""
    conf = _confiner()
    if conf == "sandbox-exec":
        return [_SANDBOX_EXEC, "-p", _macos_profile(scratch, data_dir)] + inner
    if conf == "bwrap":
        args = [shutil.which("bwrap"), "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                "--tmpfs", "/tmp", "--bind", scratch, scratch]
        if data_dir:
            args += ["--bind", data_dir, STRATEGY_DATA_MOUNT]
        # Mask secrets (applied AFTER --ro-bind / / so they override it): empty file over each .env,
        # tmpfs over the credentials dir. --ro-bind-try/--tmpfs no-op if the path is absent.
        files, dirs = _secret_mask_targets()
        for f in files:
            args += ["--ro-bind-try", "/dev/null", f]
        for d in dirs:
            args += ["--tmpfs", d]
        args += ["--chdir", scratch, "--unshare-net", "--unshare-pid", "--die-with-parent", "--"]
        return args + inner
    if conf == "firejail":
        args = [shutil.which("firejail"), "--quiet", "--net=none", "--private-tmp",
                "--read-only=/", "--read-write=%s" % scratch]
        if data_dir:
            args += ["--read-write=%s" % data_dir]
        files, dirs = _secret_mask_targets()
        for p in files + dirs:
            args += ["--blacklist=%s" % p]
        return args + ["--"] + inner
    raise SandboxError(
        "no OS-level sandbox available (need sandbox-exec on macOS, or bwrap/firejail on Linux); "
        "refusing to run untrusted strategy code on a host that holds live keys / a DB handle")


def _applied_limits() -> Dict[str, bool]:
    """Which rlimits this OS lets us actually set (diagnostics; drives the mem-cap test skip)."""
    out = {}
    for name in ("RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_FSIZE", "RLIMIT_NOFILE"):
        res = getattr(resource, name)
        soft, hard = resource.getrlimit(res)
        try:
            cap = (1024 ** 3) if hard == resource.RLIM_INFINITY else min(1024 ** 3, hard)
            resource.setrlimit(res, (cap, hard))
            resource.setrlimit(res, (soft, hard))  # restore
            out[name] = True
        except (ValueError, OSError):
            out[name] = False
    return out


def run_strategy_signals(code: str, window: Dict, *, cpu_s: int = STRATEGY_CPU_SECONDS,
                         mem_bytes: int = STRATEGY_MEM_BYTES, wall_s: float = STRATEGY_WALL_SECONDS,
                         nofile: int = STRATEGY_NOFILE, nproc: int = STRATEGY_NPROC,
                         fsize: int = STRATEGY_FSIZE_BYTES, scratch_dir: Optional[str] = None,
                         data_dir: Optional[str] = STRATEGY_DATA_DIR) -> List:
    """Run the strategy's `signals(window)` in an isolated child interpreter and return its
    result (a list). Raises SandboxError on rejection, timeout, a blown resource limit, a crash,
    or non-JSON output. See the module docstring for the isolation guarantees. `data_dir`, if set,
    is created and mounted read-write for persisted datasets/models and surfaced as
    window['data_dir']; secrets are masked out of it regardless."""
    validate_strategy_code(code)
    created = scratch_dir is None
    scratch = _safe_scratch(scratch_dir or tempfile.mkdtemp(prefix="strat_"))
    in_path = os.path.join(scratch, "in.json")
    out_path = os.path.join(scratch, "out.json")
    # Scoped file access: a persistent data dir the strategy reads/writes across runs.
    use_data = None
    if data_dir:
        try:
            os.makedirs(data_dir, exist_ok=True)
            use_data = _safe_scratch(data_dir)
        except (OSError, SandboxError):
            use_data = None  # no data dir available -> strategy just runs without it
    conf = _confiner()
    win = window
    if use_data:
        # Inside a Linux namespace the dir appears at STRATEGY_DATA_MOUNT; macOS keeps the real path.
        win = dict(window)
        win["data_dir"] = STRATEGY_DATA_MOUNT if conf in ("bwrap", "firejail") else use_data
    try:
        with open(in_path, "w") as f:
            json.dump({"code": code, "entry": STRATEGY_ENTRY, "window": win,
                       "allowed": list(STRATEGY_ALLOWED_IMPORTS)}, f)
        # Scrubbed env: NONE of the credential / DB / AWS vars. `-I` also makes the child ignore
        # PYTHON* vars, the cwd and user-site; `-B` suppresses __pycache__ writes (denied outside
        # scratch). Thread caps keep BLAS/OpenMP from oversubscribing; cache dirs point at scratch so
        # libs that write a cache don't hit the read-only root. The kernel confiner is the boundary.
        env = {"PATH": "/usr/bin:/bin", "HOME": scratch, "TMPDIR": scratch, "LC_ALL": "C", "LANG": "C",
               "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2",
               "NUMEXPR_NUM_THREADS": "2", "VECLIB_MAXIMUM_THREADS": "2", "TF_CPP_MIN_LOG_LEVEL": "3",
               "XDG_CACHE_HOME": scratch, "MPLCONFIGDIR": scratch}
        inner = [sys.executable, "-I", "-B", "-c", _RUNNER, in_path, out_path,
                 str(cpu_s), str(mem_bytes), str(nofile), str(nproc), str(fsize)]
        argv = _confined_argv(inner, scratch, use_data)
        try:
            proc = subprocess.run(argv, cwd=scratch, env=env, timeout=wall_s,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
        except subprocess.TimeoutExpired:
            raise SandboxError("strategy exceeded the %.0fs wall-clock limit" % wall_s)
        if not os.path.exists(out_path):
            # Deliberately do NOT echo the child's stderr: it is untrusted output and a strategy
            # could gadget-read a secret and write it to fd 2 to smuggle bytes into our logs.
            raise SandboxError("strategy produced no output (exit %s)" % proc.returncode)
        with open(out_path) as f:
            result = json.load(f)
        if "error" in result:
            raise SandboxError("strategy raised: %s" % result["error"])
        sig = result.get("signals")
        if not isinstance(sig, list):
            raise SandboxError("strategy must return a list of per-frame signals")
        return sig
    finally:
        if created:
            shutil.rmtree(scratch, ignore_errors=True)
