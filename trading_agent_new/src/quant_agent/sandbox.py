"""Docker-only generated-code execution with incremental, as-of JSON messages.

There is intentionally no host-Python fallback. Generated programs see only a
read-only strategy file and the current context, not a mounted dataset/store.
"""
from __future__ import annotations

from pathlib import Path
from queue import Queue, Empty
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid

from .common import GateError, canonical


class DockerSandbox:
    def __init__(self, code: str, image: str, timeout: float = 20, output_bytes: int = 64_000_000, initial_state: dict | None = None):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise GateError("Sandbox image must be a locally built, pinned SHA256 image ID")
        if not shutil.which("docker"):
            raise GateError("Docker is unavailable; generated Python will not execute on the host")
        self.timeout, self.output_bytes = timeout, output_bytes
        self.directory = tempfile.TemporaryDirectory(prefix="quant-strategy-")
        self.name = "quant-agent-" + uuid.uuid4().hex
        self.closed = False
        self.initial_state = initial_state or {}
        self.first = True
        code_path = Path(self.directory.name) / "strategy.py"
        code_path.write_text(code)
        code_path.chmod(0o444)
        self.command = self.build_command(image, str(code_path), self.name)
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, start_new_session=True)
        self.lines = Queue(maxsize=2)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    @staticmethod
    def build_command(image: str, code_path: str, name: str) -> list[str]:
        return ["docker", "run", "--rm", "-i", "--pull=never", "--name", name,
                "--network=none", "--read-only", "--user=65534:65534", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--memory=512m", "--memory-swap=512m",
                "--cpus=1", "--pids-limit=64", "--ulimit=nofile=64:64", "--ulimit=fsize=1024:1024",
                "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m", "--env=PYTHONHASHSEED=0",
                "--mount", f"type=bind,src={code_path},dst=/strategy.py,readonly", image,
                "python", "-I", "/runner.py"]

    def _read(self):
        total = 0
        while not self.closed:
            line = self.process.stdout.readline(self.output_bytes + 1)
            total += len(line)
            if total > self.output_bytes or len(line) > 100_000:
                self.lines.put(GateError("Generated code exceeded its output quota"))
                return
            if not line:
                self.lines.put(GateError("Generated code exited without a valid response"))
                return
            try:
                self.lines.put(json.loads(line))
            except (ValueError, UnicodeError):
                self.lines.put(GateError("Generated code emitted invalid JSON"))
                return

    def step(self, context: dict) -> dict:
        message = {"context":context}
        if self.first: message["initial_state"] = self.initial_state
        self.first = False
        raw = canonical(message).encode() + b"\n"
        if len(raw) > 2_000_000:
            raise GateError("Strategy context exceeds its input quota")
        written = threading.Event()
        failures = []
        def write():
            try:
                self.process.stdin.write(raw)
                self.process.stdin.flush()
            except (BrokenPipeError,OSError) as exc:
                failures.append(exc)
            finally: written.set()
        threading.Thread(target=write,daemon=True).start()
        try:
            if not written.wait(self.timeout) or failures:
                raise GateError("Generated code did not accept its input before timeout")
            result = self.lines.get(timeout=self.timeout)
        except (BrokenPipeError, Empty):
            raise GateError("Generated code timed out/exited; experiment failed") from None
        if isinstance(result, Exception):
            raise result
        if not isinstance(result, dict) or set(result) != {"weights", "state"}:
            raise GateError("Generated code violated the Strategy API")
        if not isinstance(result["state"], dict):
            raise GateError("Strategy state must serialize as a JSON object")
        try:
            if len(canonical(result["state"]).encode())>64_000: raise GateError("Strategy state exceeds 64 KB")
        except (TypeError,ValueError): raise GateError("Strategy state contains non-JSON or nonfinite values") from None
        return result

    def close(self):
        if self.closed:
            return
        self.closed = True
        subprocess.run(["docker", "rm", "-f", self.name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, check=False)
        try:
            self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=5)
        self.directory.cleanup()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
