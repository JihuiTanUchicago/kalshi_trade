"""Pause notice: when the engine pauses a deployment on its own (loss guard, force-close), the
review it queues rings the user's bell. Read-only toward trading."""
from app.research import agent

USER = {"id": 2}


def _patch(monkeypatch, dep):
    bells = []
    monkeypatch.setattr(agent.repo, "get_deployment", lambda cur, uid, did: dep if dep and did == dep["id"] else None)
    monkeypatch.setattr(agent.repo, "add_notification_collapsed",
                        lambda cur, uid, kind, body, link: bells.append((uid, kind, body, link)) or len(bells))
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


def test_a_second_review_of_the_same_pause_adds_no_second_line(monkeypatch):
    # The loss guard and force-close each queue a review, and a retried review runs the notice again:
    # the repository's collapse says nothing was added, and so does the notice.
    _patch(monkeypatch, {"id": 9, "strategy_id": 7, "status": "paused", "title": "Edge", "status_reason": None})
    monkeypatch.setattr(agent.repo, "add_notification_collapsed", lambda cur, uid, kind, body, link: None)
    assert agent.pause_notice(None, USER, {"kind": "review", "deployment_id": 9}) is False
