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


# -- the one intended exception: markets long-term memory marks exhausted (Todd, 2026-10-30) ---------

RETEST = agent.rsi_repair.requeue_prompt({"kind": "micro", "need": "ob_imbalance", "idea_title": "Imbalance fade",
                                          "idea_why": "ob_imbalance not populated"})


def _exhausted(monkeypatch, keys):
    monkeypatch.setattr(agent, "exhausted_markets", lambda cur, uid, ks: [k for k in ks if k in keys])


def test_autopilot_starts_no_taker_research_when_every_market_is_exhausted(monkeypatch):
    runs = _all_cooling(monkeypatch)
    _exhausted(monkeypatch, {"btc15m", "btc_daily", "btc15m_tick"})
    for market in ("btc15m", None, "eth15m"):
        msg, _ = agent.act(None, USER, {"type": "research", "market": market,
                                        "idea": "Order-flow imbalance on short-dated contracts."}, True)
        assert msg.startswith("I didn’t start that: every kind of idea has been tried on")
        assert "market making" in msg and "btc15m" not in msg   # customer labels, never keys
    assert runs == []
    line = agent._cooldown_line(None, 1)
    assert "Do not propose research now" in line and "not a stall" in line and "WITHOUT a market" not in line
    # a re-test on data collected for an idea is the new-data lane, and still starts (btc15m is cooling)
    agent.act(None, USER, {"type": "research", "market": "btc15m", "idea": RETEST}, True)
    assert runs == [("research", None)]
    # research a person starts by hand is not limited
    monkeypatch.setattr(agent.repo, "list_runs", lambda cur, uid, limit=30: [])
    agent.act(None, USER, {"type": "research", "market": "btc15m", "idea": "Order-flow imbalance."}, False)
    assert runs[-1] == ("research", "btc15m")


def test_an_exhausted_market_reroutes_to_one_that_is_not(monkeypatch):
    runs = _all_cooling(monkeypatch)
    _exhausted(monkeypatch, {"btc15m"})
    agent.act(None, USER, {"type": "research", "market": "btc15m",
                           "idea": "Order-flow imbalance on short-dated contracts."}, True)
    assert runs == [("research", None)]
    line = agent._cooldown_line(None, 1)
    assert "do NOT propose research on these: btc15m" in line


def test_the_floor_stands_down_only_when_every_market_is_exhausted(monkeypatch):
    r = worker.repo
    old = [{"created_at": NOW - worker.timedelta(hours=2)}]
    monkeypatch.setattr(r, "list_runs", lambda cur, uid, limit=1: old)
    monkeypatch.setattr(r, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(r, "count_active_research", lambda cur: 0)
    monkeypatch.setattr(worker.billing, "is_ready", lambda cur, uid: True)
    monkeypatch.setattr(agent, "_researchable_keys", lambda cur: ["btc15m", "btc_daily", "btc15m_tick", "eth15m"])
    monkeypatch.setattr(agent, "focus_keys", lambda cur, uid, keys: list(keys))
    _exhausted(monkeypatch, {"btc15m", "btc_daily"})
    assert worker.research_floor_due(None, 1)
    _exhausted(monkeypatch, {"btc15m", "btc_daily", "btc15m_tick"})
    assert not worker.research_floor_due(None, 1)
