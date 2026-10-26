"""Demo copies follow the user's running paper strategies (app/trading/demo_twins.py)."""
from app.trading import demo_twins
from app import repository as repo

SPEC = {"side": "yes", "entry": {"min_edge": 0.05}}


class _Store:
    def __init__(self, deps, strategies):
        self.deps, self.strategies, self.created, self.status = deps, strategies, [], []


def _patch(monkeypatch, store):
    monkeypatch.setattr(repo, "list_deployments", lambda cur, uid, include_stopped=False: store.deps)
    monkeypatch.setattr(repo, "get_strategy", lambda cur, uid, sid: store.strategies.get(sid))
    monkeypatch.setattr(repo, "create_deployment",
                        lambda cur, uid, sid, market, mode: store.created.append((sid, market, mode)) or 99)
    monkeypatch.setattr(repo, "set_deployment_status",
                        lambda cur, uid, did, status, reason=None: store.status.append((did, status, reason)) or True)


def _dep(i, sid, mode, status="running", reason=None):
    return {"id": i, "strategy_id": sid, "mode": mode, "status": status, "status_reason": reason, "title": "S%d" % sid}


def _strat(sid, market="btc15m", spec=SPEC):
    return {"id": sid, "market": market, "spec": dict(spec), "title": "S%d" % sid}


def test_running_paper_strategies_get_a_demo_copy_once_funded(monkeypatch):
    store = _Store([_dep(1, 10, "paper"), _dep(2, 11, "paper"), _dep(3, 11, "demo"), _dep(4, 12, "paper", "paused")],
                   {10: _strat(10), 11: _strat(11), 12: _strat(12)})
    _patch(monkeypatch, store)
    lines = demo_twins.sync(None, {"id": 1}, balance=lambda cur, uid: 500.0, enabled=True)
    assert store.created == [(10, "btc15m", "demo")]   # 11 has one, 12's paper is paused
    assert len(lines) == 1


def test_no_copy_without_a_funded_demo_account_or_when_off(monkeypatch):
    for bal, on in ((None, True), (0.0, True), (demo_twins.DEMO_TWIN_MIN_BALANCE - 1, True), (500.0, False)):
        store = _Store([_dep(1, 10, "paper")], {10: _strat(10)})
        _patch(monkeypatch, store)
        assert demo_twins.sync(None, {"id": 1}, balance=lambda cur, uid: bal, enabled=on) == []
        assert store.created == []


def test_code_specs_and_research_only_markets_are_never_copied(monkeypatch):
    store = _Store([_dep(1, 10, "paper"), _dep(2, 11, "paper")],
                   {10: _strat(10, spec={"code": "def decide(): pass"}), 11: _strat(11, market="no-such-market")})
    _patch(monkeypatch, store)
    demo_twins.sync(None, {"id": 1}, balance=lambda cur, uid: 500.0, enabled=True)
    assert store.created == []


def test_demo_copy_pauses_and_resumes_with_its_paper_strategy(monkeypatch):
    store = _Store([_dep(1, 10, "paper", "paused"), _dep(2, 10, "demo")], {10: _strat(10)})
    _patch(monkeypatch, store)
    demo_twins.sync(None, {"id": 1}, balance=lambda cur, uid: 500.0, enabled=True)
    assert store.status == [(2, "paused", demo_twins.PAUSE_REASON)]
    store = _Store([_dep(1, 10, "paper"), _dep(2, 10, "demo", "paused", demo_twins.PAUSE_REASON),
                    _dep(3, 11, "paper"), _dep(4, 11, "demo", "paused", "drawdown stop")], {})
    _patch(monkeypatch, store)
    demo_twins.sync(None, {"id": 1}, balance=lambda cur, uid: 500.0, enabled=True)
    assert store.status == [(2, "running", None)]   # a demo copy paused for its own reason stays paused
