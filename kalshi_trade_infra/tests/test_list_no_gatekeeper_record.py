"""A passed strategy with no gatekeeper record (the old loose backtest gate) says so on the Strategies list.

Its page decides "no record" from experiments_for_strategy (its stored experiment_id, else the newest
experiment linked by strategy_id): with none, it reads "Not validated (record missing)" and calls its
out_of_sample the later-period figure (#590). The list judges every pass for a later verdict with the
same two reads (newest_experiment_ids for a pass stored without its experiment id, then later_results,
keyed by every experiment that exists), so it learns which passes have a record from them, with no
extra statement. Display only: no status, gate or record changes.
"""
from app import server
from app.research import research_repository as research_repo
from app.web.routes import strategies as strategy_routes

from tests.test_app_auth_and_api import ctx


def _judged():
    # 1: linked by experiment_id; 2: legacy, linked by strategy_id; 3: legacy, no experiment at all;
    # 4: experiment_id set, but no such experiment; 5: a void probation strategy (never "passed").
    return [{"id": 1, "status": "passed", "experiment_id": 11, "spec": {}},
            {"id": 2, "status": "passed", "experiment_id": None, "spec": {}},
            {"id": 3, "status": "passed", "experiment_id": None, "spec": {}},
            {"id": 4, "status": "passed", "experiment_id": 44, "spec": {}},
            {"id": 5, "status": "failed", "experiment_id": 55, "spec": {}}]


def _fake_reads(monkeypatch, calls):
    monkeypatch.setattr(research_repo, "newest_experiment_ids",
                        lambda cur, uid, ids: calls.append(("newest", sorted(ids))) or {2: 22})
    # Keyed by every experiment that exists, with or without a later row (later_results' contract).
    monkeypatch.setattr(research_repo, "later_results",
                        lambda cur, ids: calls.append(("later", sorted(ids))) or {
                            i: {"min_sample": 30, "results": []} for i in ids if i in (11, 22, 55)})


def test_later_verdicts_says_which_strategies_its_reads_found_a_record_for(monkeypatch):
    calls = []
    _fake_reads(monkeypatch, calls)
    recorded = set()
    assert strategy_routes._later_verdicts(None, 1, _judged(), recorded=recorded) == {}
    assert recorded == {1, 2, 5}
    # The same two reads as without it: one for the legacy passes, one for every experiment.
    assert calls == [("newest", [2, 3]), ("later", [11, 22, 44, 55])]
    calls.clear()
    assert strategy_routes._later_verdicts(None, 1, _judged()) == {} and len(calls) == 2


def test_the_strategies_list_flags_only_a_pass_with_no_record(monkeypatch):
    calls = []
    _fake_reads(monkeypatch, calls)
    monkeypatch.setattr(server.repo, "count_strategies", lambda *a, **k: {"passed": 4, "failed": 1, "total": 5})
    monkeypatch.setattr(server.repo, "passed_strategies", lambda *a, **k: _judged())
    rows = [dict(s, status=s["status"]) for s in _judged()] + [{"id": 6, "status": "backtest-only"}]
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [dict(r) for r in rows])
    monkeypatch.setattr(strategy_routes, "_strategy_card", lambda s: {"id": s["id"], "status": s["status"]})
    out = server.list_strategies(ctx(query={"status": "passed"}))
    flagged = {c["id"]: c.get("no_gatekeeper_record", False) for c in out["strategies"]}
    # 3 has no experiment either way; 4's stored experiment doesn't exist. 1 and 2 have theirs. The void one and
    # the backtest-only one aren't passes (the page and the list already word a backtest-only row from its status).
    assert flagged == {1: False, 2: False, 3: True, 4: True, 5: False, 6: False}
    assert len(calls) == 2  # no read of its own


def test_a_card_the_list_did_not_judge_claims_nothing():
    cards = [{"id": 7, "status": "passed"}, {"id": 8, "status": "passed"}]
    strategy_routes._attach_no_record(cards, [{"id": 8, "status": "passed"}], set())
    assert "no_gatekeeper_record" not in cards[0] and cards[1]["no_gatekeeper_record"] is True
