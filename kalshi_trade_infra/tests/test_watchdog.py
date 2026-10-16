"""The watchdog restarts a stale service, stays quiet on a fresh one, and never
restart-loops (cooldown)."""
import json

from data_pipeline import watchdog


class _Cur:
    def __init__(self, ages):
        self._ages = ages

    def execute(self, sql, params):
        self._keys = list(params)

    def fetchall(self):
        return [{"k": k, "age": self._ages.get(k)} for k in self._keys]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, ages):
        self._ages = ages

    def cursor(self):
        return _Cur(self._ages)

    def close(self):
        pass


def _patch(monkeypatch, tmp_path, ages):
    monkeypatch.setattr(watchdog, "get_db_conn", lambda: _Conn(ages))
    monkeypatch.setattr(watchdog, "STATE_FILE", str(tmp_path / "state.json"))
    calls = []
    monkeypatch.setattr(watchdog.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    return calls


T = [["forward_collector_last_snapshot", "kalshi-forward-collector", 240]]


def test_fresh_heartbeat_does_nothing(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, tmp_path, {"forward_collector_last_snapshot": 30})
    assert watchdog.run_once(T, now=1000) == []
    assert calls == []


def test_stale_heartbeat_restarts(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, tmp_path, {"forward_collector_last_snapshot": 600})
    assert watchdog.run_once(T, now=1000) == ["kalshi-forward-collector"]
    assert calls == [["systemctl", "restart", "kalshi-forward-collector"]]


def test_missing_heartbeat_counts_as_stale(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, tmp_path, {})  # key absent -> age None
    assert watchdog.run_once(T, now=1000) == ["kalshi-forward-collector"]


def test_cooldown_blocks_a_second_restart(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, {"forward_collector_last_snapshot": 600})
    watchdog.run_once(T, now=1000)                       # restarts, records t=1000
    calls2 = _patch(monkeypatch, tmp_path, {"forward_collector_last_snapshot": 600})
    # re-patch keeps the same STATE_FILE path (tmp_path), so the cooldown persists
    assert watchdog.run_once(T, now=1000 + 300) == []    # 300s < COOLDOWN_S -> skipped
    assert watchdog.run_once(T, now=1000 + watchdog.COOLDOWN_S + 1) == ["kalshi-forward-collector"]
