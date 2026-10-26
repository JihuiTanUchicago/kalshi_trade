"""Invariant: autopilot research keeps starting when every market it may research is cooling down.

Research stalled twice on 2026-10-26: 06:03-07:58Z (reviews kept naming an unsupported market) and
15:27-16:45Z (Bitcoin-only left two markets, both on cooldown, and the reviews started nothing).
Any change to the picker, cooldown, focus or scope must keep these green: each path a review can
take still creates a research run, and the worker's floor starts one when the reviews don't."""
from app import worker
from app.research import agent

NOW = agent.repo.now_utc()
# Every Bitcoin market just finished, so each is on the 6h cooldown.
COOLING = [{"id": 3, "market": "btc15m", "status": "succeeded", "finished_at": NOW, "created_at": NOW},
           {"id": 2, "market": "btc_daily", "status": "succeeded", "finished_at": NOW, "created_at": NOW},
           {"id": 1, "market": "btc15m_tick", "status": "succeeded", "finished_at": NOW, "created_at": NOW}]
USER = {"id": 1, "autopilot_focus": '["crypto"]'}


def _all_cooling(monkeypatch):
    r = agent.repo
    runs = []
    monkeypatch.setattr(r, "list_runs", lambda cur, uid, limit=30: COOLING)
    monkeypatch.setattr(r, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(r, "count_active_research", lambda cur: 0)
    monkeypatch.setattr(r, "create_run", lambda cur, uid, kind, market=None, direction=None, idea=None, **kw:
                        runs.append((kind, market)) or 9)
    monkeypatch.setattr(agent, "_researchable_keys", lambda cur: ["btc15m", "btc_daily", "btc15m_tick", "eth15m"])
    monkeypatch.setattr(agent, "focus_keys", lambda cur, uid, keys: list(keys))
    return runs


def test_every_review_path_still_starts_research(monkeypatch):
    runs = _all_cooling(monkeypatch)
    for market in ("btc15m", None, "eth15m", "ltc15m"):  # cooling, open choice, out of scope, unsupported
        agent.act(None, USER, {"type": "research", "market": market,
                               "idea": "Order-flow imbalance on short-dated contracts."}, True)
    assert runs == [("research", None)] * 4


def test_the_review_is_not_told_to_stop_and_the_pick_still_has_a_market(monkeypatch):
    _all_cooling(monkeypatch)
    line = agent._cooldown_line(None, 1)
    assert "WITHOUT a market" in line and "do NOT propose these markets" not in line
    assert agent._least_recent_markets(None, 1, ["btc15m", "btc_daily", "btc15m_tick"])


def test_the_worker_floor_starts_research_when_reviews_do_not(monkeypatch):
    r = worker.repo
    started = []
    last = [{"created_at": NOW - worker.timedelta(minutes=worker.RESEARCH_FLOOR_MINUTES + 1)}]
    monkeypatch.setattr(r, "autopilot_user_ids", lambda cur: [1])
    monkeypatch.setattr(r, "get_user", lambda cur, uid: {"id": uid, "autopilot_model": "opus-4-6"})
    monkeypatch.setattr(r, "list_runs", lambda cur, uid, limit=1: last)
    monkeypatch.setattr(r, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(r, "count_active_research", lambda cur: 0)
    monkeypatch.setattr(r, "create_run", lambda cur, uid, kind, market=None, direction=None, idea=None, **kw:
                        started.append((uid, kind, market, kw.get("brief"), kw.get("model"))))
    monkeypatch.setattr(worker.billing, "is_ready", lambda cur, uid: True)
    assert worker.start_research_floor(None) == [1]
    assert started == [(1, "research", None, True, "opus-4-6")]
    # not when research ran recently, is already going, or the user has no credit
    last[0]["created_at"] = NOW
    assert worker.start_research_floor(None) == []
    last[0]["created_at"] = NOW - worker.timedelta(hours=2)
    monkeypatch.setattr(r, "count_runs", lambda cur, uid, kind, active_only=False, **k: 1 if active_only else 0)
    assert worker.start_research_floor(None) == []
    monkeypatch.setattr(r, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(worker.billing, "is_ready", lambda cur, uid: False)
    assert worker.start_research_floor(None) == []
