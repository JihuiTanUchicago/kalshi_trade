"""Pause notice: when the engine pauses a deployment on its own (loss guard, force-close), the
review it queues rings the user's bell. Read-only toward trading."""
from app.research import agent

USER = {"id": 2}


def _patch(monkeypatch, dep):
    bells = []
    monkeypatch.setattr(agent.repo, "get_deployment", lambda cur, uid, did: dep if dep and did == dep["id"] else None)
    monkeypatch.setattr(agent.repo, "add_notification", lambda cur, uid, kind, body, link=None: bells.append((uid, kind, body, link)))
    return bells


def test_an_auto_paused_deployment_rings_the_bell(monkeypatch):
    bells = _patch(monkeypatch, {"id": 9, "strategy_id": 7, "status": "paused", "title": "Edge",
                                 "status_reason": "Lost $12.00, more than the $10.00 guard."})
    assert agent.pause_notice(None, USER, {"kind": "review", "deployment_id": 9}) is True
    assert bells == [(2, "paused", "“Edge” was paused automatically. Lost $12.00, more than the $10.00 guard.", "/strategies/7")]


def test_no_notice_without_a_deployment_or_once_it_is_running_again(monkeypatch):
    bells = _patch(monkeypatch, {"id": 9, "strategy_id": 7, "status": "running", "title": "Edge", "status_reason": None})
    assert agent.pause_notice(None, USER, {"kind": "review", "deployment_id": None}) is False
    assert agent.pause_notice(None, USER, {"kind": "review", "deployment_id": 9}) is False
    assert agent.pause_notice(None, USER, {"kind": "review", "deployment_id": 10}) is False
    assert bells == []
