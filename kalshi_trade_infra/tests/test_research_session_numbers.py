"""The Research list numbers a user's sessions among their own ("Session 3"), never by the global run id."""
from types import SimpleNamespace

from app import repository as repo
from app.web.routes import research as research_routes


def _ctx():
    return SimpleNamespace(cur=object(), uid=7, query={})


def _stub_list(monkeypatch, runs, own_total=None):
    counted = []
    monkeypatch.setattr(research_routes.repo, "active_run_counts", lambda *a, **k: {})
    monkeypatch.setattr(research_routes.repo, "list_runs_version", lambda *a, **k: [{"id": r["id"]} for r in runs])
    monkeypatch.setattr(research_routes.repo, "list_runs", lambda cur, uid, **k: [dict(r) for r in runs])
    monkeypatch.setattr(research_routes.repo, "runs_spent", lambda *a: {})
    monkeypatch.setattr(research_routes.repo, "get_policy", lambda *a: None)
    monkeypatch.setattr(research_routes, "_research_totals", lambda *a: {})
    monkeypatch.setattr(research_routes.repo, "count_own_research",
                        lambda cur, uid: counted.append(uid) or own_total)
    return counted


def test_a_first_session_is_session_1_whatever_its_run_id(monkeypatch):
    # Run 8 is this user's first session; the seeded example (run 2) gets no number.
    counted = _stub_list(monkeypatch, [{"id": 9, "direction": None}, {"id": 8, "direction": "momentum"},
                                       {"id": 2, "direction": repo.DEMO_DIRECTION}])
    runs = research_routes.list_runs(_ctx())["runs"]
    assert [(r["id"], r.get("seq")) for r in runs] == [(9, 2), (8, 1), (2, None)]
    assert counted == []  # a short list already holds every session: nothing is counted


def test_a_full_page_counts_the_older_sessions_once(monkeypatch):
    # 50 shown of 120 own sessions: the newest is 120, the oldest shown 71.
    runs = [{"id": 1000 - k, "direction": None} for k in range(repo.RUNS_LISTED)]
    counted = _stub_list(monkeypatch, runs, own_total=120)
    out = research_routes.list_runs(_ctx())["runs"]
    assert out[0]["seq"] == 120 and out[-1]["seq"] == 120 - repo.RUNS_LISTED + 1
    assert counted == [7]


def test_count_own_research_leaves_the_example_out():
    seen = []

    class _Cur:
        def execute(self, sql, params):
            seen.append((sql, params))

        def fetchone(self):
            return {"n": 4}

    assert repo.count_own_research(_Cur(), 7) == 4
    sql, params = seen[0]
    assert "kind='research'" in sql and "direction<>%s" in sql and params == (7, repo.DEMO_DIRECTION)
