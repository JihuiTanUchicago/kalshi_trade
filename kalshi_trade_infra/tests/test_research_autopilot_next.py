"""A finished session's passed strategy that the autopilot is about to put on paper itself is marked
`autopilot_next`, so the session page stops asking for a deploy by hand (a second copy doubles the
positions). The marks follow agent.auto_paper_candidates' own tests."""
from app.research import agent
from app.web.routes import research


def _strategy(sid, **o):
    s = {"id": sid, "run_id": 5, "status": "passed", "market": "btc15m", "direction": "momentum",
         "spec": {"side": "yes"}, "active_deps": 0}
    s.update(o)
    return s


def _setup(monkeypatch, deps=(), candidates=(42, 43, 44)):
    monkeypatch.setattr(research.repo, "list_deployments", lambda cur, uid, include_stopped=False: list(deps))
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: sid in candidates)


def test_autopilot_on_marks_the_passed_candidates_it_will_put_on_paper(monkeypatch):
    _setup(monkeypatch, candidates=(42,))
    user = {"id": 7, "autopilot": 1, "autopilot_focus": None}
    rows = [_strategy(42), _strategy(43), _strategy(44, status="rejected")]
    # 43 passed but the gatekeeper never made it a deployment candidate: the autopilot leaves it.
    assert research._autopilot_puts_on_paper(None, user, rows) == {42}


def test_nothing_is_marked_with_autopilot_off_or_for_what_it_would_skip(monkeypatch):
    _setup(monkeypatch, deps=[{"strategy_id": 43, "mode": "paper", "status": "stopped"}])
    rows = [_strategy(42), _strategy(43), _strategy(44, market="kxhighny"), _strategy(45, active_deps=1)]
    assert research._autopilot_puts_on_paper(None, {"id": 7, "autopilot": 0}, rows) == set()
    assert research._autopilot_puts_on_paper(None, None, rows) == set()
    # Focus on weather: the BTC strategy is outside it. 43 ran on paper before (stopped is a decision),
    # 45 is already deployed.
    on = {"id": 7, "autopilot": 1, "autopilot_focus": '["kxhighny"]'}
    assert 42 not in research._autopilot_puts_on_paper(None, on, rows)
    assert research._autopilot_puts_on_paper(None, {**on, "autopilot_focus": None}, rows) & {43, 45} == set()


def test_a_full_book_or_a_code_strategy_is_not_marked(monkeypatch):
    user = {"id": 7, "autopilot": 1, "autopilot_focus": None}
    _setup(monkeypatch, deps=[{"strategy_id": 100 + i, "mode": "paper", "status": "running"}
                              for i in range(agent.AUTO_PAPER_MAX_ACTIVE)])
    assert research._autopilot_puts_on_paper(None, user, [_strategy(42)]) == set()
    _setup(monkeypatch)
    code = _strategy(42, spec={"code": "def decide(x):\n    return None\n"})
    assert research._autopilot_puts_on_paper(None, user, [code]) == set()
    assert research._autopilot_puts_on_paper(None, user, [_strategy(42)]) == {42}
