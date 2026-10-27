"""The user's market focus binds the autopilot. Prod 2026-10-24: Todd told it "Research and trade
only crypto" and it kept launching sports research, because the instruction lived only in chat."""
import json

import pytest

from app import server
from app.research import agent

CRYPTO = {"id": 1, "autopilot": 1, "autopilot_focus": json.dumps(["crypto"])}


def _capture(monkeypatch):
    rec = {"runs": [], "deployments": []}
    r = agent.repo
    monkeypatch.setattr(r, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(r, "create_run", lambda cur, uid, kind, market, direction, idea, **kw: rec["runs"].append(market) or 9)
    monkeypatch.setattr(r, "create_proposal", lambda *a, **k: 1)
    monkeypatch.setattr(r, "create_deployment", lambda cur, uid, sid, market, mode: rec["deployments"].append(market) or 3)
    return rec


def test_focus_tokens_cover_families_coins_and_keys():
    assert agent.normalize_focus(["Crypto", "bitcoin"]) == ["crypto", "btc"]
    assert agent.normalize_focus("crypto, high_ny") == ["crypto", "high_ny"]
    with pytest.raises(ValueError, match="'stocks'"):
        agent.normalize_focus(["stocks"])
    assert agent.in_focus("btc15m", ["crypto"]) and agent.in_focus("eth_daily", ["crypto"])
    assert agent.in_focus("btc_daily", ["btc"]) and not agent.in_focus("eth15m", ["btc"])
    assert not agent.in_focus("nfl_game", ["crypto"]) and agent.in_focus("nfl_game", ["sports"])
    assert agent.in_focus("nfl_game", []) and agent.in_focus(None, ["crypto"])
    assert agent.focus_tokens({"autopilot_focus": "not json"}) == [] and agent.focus_tokens(None) == []


def test_research_outside_the_focus_is_refused_and_inside_goes_ahead(monkeypatch):
    rec = _capture(monkeypatch)
    text, _ = agent.act(None, CRYPTO, {"type": "research", "market": "nfl_game", "idea": "sportsbook vs crowd recalibration"}, True)
    assert rec["runs"] == [] and "focus on crypto" in text
    agent.act(None, CRYPTO, {"type": "research", "market": "btc15m", "idea": "order-flow imbalance on 15m"}, True)
    agent.act(None, CRYPTO, {"type": "research", "idea": "let the picker choose inside the focus"}, True)
    assert rec["runs"] == ["btc15m", None]


def test_deploys_outside_the_focus_are_refused(monkeypatch):
    rec = _capture(monkeypatch)
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "status": "passed", "market": "nba_game", "title": "NBA fade", "spec": {"market": "nba_game"}})
    for kind in ("deploy", "deploy_live"):
        text, pid = agent.act(None, CRYPTO, {"type": kind, "strategy_id": 4}, True)
        assert pid is None and "won't touch" in text
    assert rec["deployments"] == []


def test_only_the_user_can_set_the_focus(monkeypatch):
    stored = []
    monkeypatch.setattr(agent.repo, "set_autopilot_focus", lambda cur, uid, tokens: stored.append(tokens))
    assert "Only you" in agent.set_focus_action(None, {"id": 1}, {"focus": ["sports"]}, "review")
    assert agent.set_focus_action(None, CRYPTO, {"focus": ["Crypto"]}, "review") == ""  # an echo: silent no-op
    assert stored == []
    assert "set to crypto" in agent.set_focus_action(None, {"id": 1}, {"focus": ["crypto"]}, "chat")
    assert "recognise" in agent.set_focus_action(None, {"id": 1}, {"focus": ["stonks"]}, "chat")
    assert "cleared" in agent.set_focus_action(None, {"id": 1}, {"focus": []}, "chat")
    assert stored == [["crypto"], []]


def test_picker_keys_and_review_context_stay_inside_the_focus(monkeypatch):
    monkeypatch.setattr(agent.repo, "get_user", lambda cur, uid: CRYPTO)
    assert agent.focus_keys(None, 1, ["btc15m", "nfl_game", "eth_daily"]) == ["btc15m", "eth_daily"]
    monkeypatch.setattr(agent.repo, "get_user", lambda cur, uid: {"id": 1})
    assert agent.focus_keys(None, 1, ["btc15m", "nfl_game"]) == ["btc15m", "nfl_game"]

    r = agent.repo
    monkeypatch.setattr(r, "list_deployments", lambda cur, uid, **k: [])
    monkeypatch.setattr(r, "list_strategies", lambda cur, uid, **k: [])
    monkeypatch.setattr(r, "user_risk_config", lambda cur, uid: {})
    monkeypatch.setattr(r, "user_execution_config", lambda cur, uid: {})
    ctx = agent._copilot_context(None, CRYPTO)
    assert "USER'S MARKET FOCUS (binding, set by the user): crypto." in ctx
    markets = next(line for line in ctx.splitlines() if line.startswith("Markets you can research AND deploy"))
    assert "btc15m" in markets and "nfl_game" not in markets and "high_ny" not in markets
    assert "emit a set_focus action" in agent._copilot_context(None, {"id": 1})


def test_panel_says_it_sticks_to_the_focus():
    story = server._autopilot_story({"autopilot": True, "focus": ["crypto"]})
    assert "It sticks to the focus you set: crypto." in story
    assert not any("focus" in line for line in server._autopilot_story({"autopilot": True, "focus": []}))


def test_the_panel_names_the_focus_in_words_never_its_token():
    # Walk 2026-10-27: a Bitcoin-only account's story read "It sticks to the focus you set: btc." right above the
    # panel's own "Focus: Bitcoin".
    story = server._autopilot_story({"autopilot": True, "focus": ["btc"]})
    assert "It sticks to the focus you set: Bitcoin." in story
    assert not any(" btc" in line for line in story)
    assert agent.focus_words(["btc", "eth"]) == "Bitcoin, Ethereum"
    assert agent.focus_words(["btc15m"]) == agent.MARKETS["btc15m"].label
    assert agent.focus_words(["weather-high", "sports"]) == "daily high temperatures, sports"
    assert agent.focus_words([]) == ""
    idle = server._idle_reason({"autopilot": True, "focus": ["btc"]}, [], [], None, [
        {"id": 5, "title": "Rain idea", "market": "high_ny", "in_focus": False, "candidate": False, "retired": False}])
    assert idle["code"] == "focus" and "your focus is Bitcoin," in idle["line"] and "btc" not in idle["line"]


def test_focus_endpoint_validates_and_stores(monkeypatch):
    from types import SimpleNamespace
    stored, chat = [], []
    monkeypatch.setattr(server.repo, "set_autopilot_focus", lambda cur, uid, tokens: stored.append(tokens))
    monkeypatch.setattr(server.repo, "add_chat", lambda cur, uid, role, text, *a: chat.append(text))
    assert server.autopilot_focus(SimpleNamespace(cur=None, uid=1, body={"focus": ["Bitcoin"]})) == {"ok": True, "focus": ["btc"]}
    with pytest.raises(server.ApiError):
        server.autopilot_focus(SimpleNamespace(cur=None, uid=1, body={"focus": ["stonks"]}))
    assert stored == [["btc"]] and chat == ["Market focus set to Bitcoin."]
    assert any(r[0] == "POST" and r[1].pattern == "^/api/autopilot/focus$" for r in server.ROUTES)


def _board():
    # Todd's shape on 2026-10-24: told "only crypto", most runs went to sports.
    cards = ([{"market": "btc15m"}] * 8 + [{"market": "nfl_game"}] * 13 + [{"market": "high_ny"}] + [{"market": None}])
    return {"cards": cards, "total": {"runs": 23, "cost_usd": 61.5, "gated": 3, "passed": 0},
            "families": {"crypto": {"runs": 8, "cost_usd": 20.0, "gated": 2, "passed": 0},
                         "sports": {"runs": 13, "cost_usd": 38.0, "gated": 1, "passed": 0},
                         "weather-high": {"runs": 1, "cost_usd": 3.5, "gated": 0, "passed": 0}}}


def test_scorecard_grades_focus_adherence_and_spend_per_gated_idea():
    card = agent.autopilot_scorecard(_board(), ["crypto"])
    assert (card["in_focus"], card["placed"], card["adherence"]) == (8, 22, 0.364)
    assert card["families"][0] == {"family": "sports", "runs": 13, "cost_usd": 38.0, "gated": 1, "passed": 0,
                                   "usd_per_gated": 38.0}
    assert card["burning"] == []  # weather spent $3.50, under the burn bar
    lines = agent.autopilot_scorecard_lines(card)
    assert "8 of 22 runs were inside their focus (crypto) = 36%. Every run outside it ignored the user" in lines[2]
    assert "crypto 8 runs $20.00, gate reached 2, $10.00 per gated idea" in lines[3]
    assert lines[-1].startswith("Act on it")
    free = agent.autopilot_scorecard(_board(), [])
    assert free["adherence"] is None and not any("focus (" in line for line in agent.autopilot_scorecard_lines(free))
    b = _board()
    b["families"]["sports"]["gated"] = 0
    assert agent.autopilot_scorecard(b, [])["burning"] == ["sports"]
    assert agent.autopilot_scorecard_lines(agent.autopilot_scorecard({"cards": [], "total": {}}, [])) == []


def test_story_says_when_the_last_check_in_is_late(monkeypatch):
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 25, 16, 0)
    monkeypatch.setattr(server.repo, "now_utc", lambda: now)
    on_time = server._autopilot_story({"autopilot": True, "last_review_at": now - timedelta(minutes=20)})
    assert "checks in about every" in on_time[0]
    late = server._autopilot_story({"autopilot": True, "last_review_at": now - timedelta(minutes=57)})
    assert "last check-in was 57 minutes ago" in late[0]
    hours = server._autopilot_story({"autopilot": True, "last_review_at": now - timedelta(hours=5, minutes=10)})
    assert "last check-in was 5 hours ago" in hours[0]
    # 99 minutes reads "2h ago" in the Last check-in figure beside it, so the line says 2 hours too.
    assert "last check-in was 2 hours ago" in server._autopilot_story({"autopilot": True, "last_review_at": now - timedelta(minutes=99)})[0]
    assert "last check-in was 3 days ago" in server._autopilot_story({"autopilot": True, "last_review_at": now - timedelta(days=3)})[0]
    # Researching right now is its own answer, and no review yet means it's just starting.
    busy = server._autopilot_story({"autopilot": True, "last_review_at": now - timedelta(hours=5),
                                    "research": {"active": ["Bitcoin"]}})
    assert busy[0] == "Right now it's researching Bitcoin."
    assert "checks in about every" in server._autopilot_story({"autopilot": True, "last_review_at": None})[0]


def test_story_says_a_queued_or_running_review_is_happening_now(monkeypatch):
    # Switching on queues the first review at once; the panel said "between research runs, checks in
    # about every 10 minutes" under a Working pulse while the user waited to see it move.
    from datetime import datetime
    now = datetime(2026, 10, 25, 16, 0)
    monkeypatch.setattr(server.repo, "now_utc", lambda: now)
    first = server._autopilot_story({"autopilot": True, "reviewing": True, "last_review_at": now})
    assert first[0] == "Right now it's reviewing the markets to pick its next move. Each move shows up in its activity feed."
    queued = server._autopilot_story({"autopilot": True, "last_review_at": now,
                                      "review_wait": {"state": "queued", "seconds": 400, "overdue": True}})
    assert queued[0] == ("Its next review has waited 6 minutes for a free worker, longer than usual. "
                         "It starts when one frees up.")
    # Research already running is the more specific answer.
    assert server._autopilot_story({"autopilot": True, "reviewing": True,
                                    "research": {"active": ["Bitcoin"]}})[0] == "Right now it's researching Bitcoin."
