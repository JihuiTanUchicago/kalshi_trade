"""What the research pages say about a session: running and paused counted apart (while both still
hold one of the user's session slots), and the run page naming its model by its customer name."""
from types import SimpleNamespace

import pytest

from app import models_catalog, repository as repo, server
from app.adapters.db import agent_run_repository


class _Cur:
    def __init__(self, rows=None, one=None):
        self.rows, self.one, self.sql, self.params = rows or [], one, None, None

    def execute(self, sql, params=None):
        self.sql, self.params = " ".join(sql.split()), params

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one


def test_active_run_counts_says_paused_research_apart_from_running():
    # One running and one paused read "Researching now 2" / "Running 2": paused was folded in.
    cur = _Cur([{"kind": "research", "status": "running", "n": 1},
                {"kind": "research", "status": "paused", "n": 1},
                {"kind": "research", "status": "queued", "n": 2},
                {"kind": "chat", "status": "running", "n": 1}])
    assert repo.active_run_counts(cur, 7) == {
        "research_running": 1, "research_paused": 1, "research_queued": 2, "chat_active": 1}
    assert repo.active_run_counts(_Cur(), 7) == {
        "research_running": 0, "research_paused": 0, "research_queued": 0, "chat_active": 0}


def test_a_paused_session_still_counts_toward_the_session_limit():
    # The split is display only: the 2-session limit (count_runs active_only) still counts paused ones.
    cur = _Cur(one={"n": 2})
    assert agent_run_repository.count_runs(cur, 7, "research", active_only=True) == 2
    assert "status IN ('queued','running','paused')" in cur.sql


def test_a_run_model_key_reads_as_its_customer_name():
    assert models_catalog.label_for_key(None) == models_catalog.default().label  # NULL ran on the default
    assert models_catalog.label_for_key("sonnet-4-6") == "Claude Sonnet 4.6"
    assert models_catalog.label_for_key("opus-5-5") == "Claude Opus 5.5"  # access pending
    assert models_catalog.label_for_key("opus-4-1") == "Claude Opus"  # a retired key names its family
    assert models_catalog.label_for_key("mystery") == "AI model"
    for m in list(models_catalog.MODELS.values()) + models_catalog.PENDING:
        label = models_catalog.label_for_key(m.key)
        assert label != m.key and "anthropic." not in label and "us." not in label and ":" not in label


@pytest.mark.parametrize("model,label", [(None, "Claude Opus 4.6"), ("sonnet-4-6", "Claude Sonnet 4.6")])
def test_the_run_page_gets_the_model_name_never_its_id(monkeypatch, model, label):
    run = {"id": 9, "kind": "research", "status": "running", "model": model, "run_forever": 1, "max_hypotheses": 10}
    monkeypatch.setattr(server.repo, "get_run", lambda cur, uid, rid: dict(run))
    monkeypatch.setattr(server.repo, "runs_spent", lambda *a: {})
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "get_policy", lambda *a: None)
    monkeypatch.setattr(server.repo, "latest_dream_event", lambda *a: None)
    monkeypatch.setattr(server.repo, "run_events", lambda *a: [])
    server._LAST_DREAM.clear()
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: object()),
                     {"id": 7, "email": "trader@example.invalid", "name": "Sample", "picture_url": None, "autopilot": 0},
                     ("9",), {}, {}, SimpleNamespace())
    out = server.get_run(ctx)["run"]
    assert out["model_label"] == label
    assert "anthropic" not in out["model_label"] and out["run_forever"] == 1
