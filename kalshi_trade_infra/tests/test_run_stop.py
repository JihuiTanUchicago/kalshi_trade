"""Why a finished research session stopped (services.run_stop), and a deployment's plain status words.

The research list read "Done" for a run-until-stopped session that ran out of credits: it ends
`succeeded`, like one that ran out of ideas. stop_reason is read from what the run already stores;
nothing about how runs execute or are recorded changes.
"""
import inspect
from types import SimpleNamespace

import pytest

from app import repository as repo
from app import server
from app.services import run_stop

try:  # the research loop moves to app.research (PR #471)
    from app.research import agent
except ImportError:  # pragma: no cover - before the move
    from app import agent


@pytest.mark.parametrize("run,want", [
    ({"status": "queued"}, None),
    ({"status": "running", "run_forever": 1}, None),
    ({"status": "paused", "run_forever": 1}, None),
    ({"status": "succeeded", "run_forever": 1, "out_of_credits": 1}, "credits"),
    ({"status": "succeeded", "run_forever": 1, "out_of_credits": 0}, "complete"),
    ({"status": "succeeded", "run_forever": 0, "out_of_credits": 0}, "limit"),
    ({"status": "succeeded", "run_forever": None}, "limit"),
    ({"status": "cancelled", "run_forever": 1}, "user"),
    ({"status": "failed", "error": "The model provider is busy right now."}, "error"),
    ({"status": "stopped", "error": "Explored 4 hypotheses, then the session was interrupted and stopped."}, "interrupted"),
    ({"status": "stopped", "error": "This market has no settled contracts to research yet."}, "no_data"),
    ({"status": None}, None),
    ({"status": "something-new"}, None),
])
def test_stop_reason_reads_what_the_run_stores(run, want):
    assert run_stop.stop_reason(run) == want


def test_the_agent_still_logs_the_out_of_credits_step_the_list_looks_for():
    """repo.list_runs finds a credits stop by this step's opening words; if the agent's wording drifts,
    every such session would read "Finished" again."""
    src = inspect.getsource(agent.run_research)
    assert 'log("step", "%s' % repo.OUT_OF_CREDITS_STEP in src
    assert len(repo.OUT_OF_CREDITS_STEP) <= 24  # inside idx_events_message's prefix


def test_the_runs_list_carries_stop_reason_not_the_raw_flag(monkeypatch):
    rows = [{"id": 2, "status": "succeeded", "run_forever": 1, "out_of_credits": 1, "direction": "momentum"},
            {"id": 1, "status": "cancelled", "run_forever": 0, "out_of_credits": 0, "direction": "momentum"}]
    monkeypatch.setattr(server.repo, "get_policy", lambda cur, uid: None)
    monkeypatch.setattr(server.repo, "list_runs", lambda cur, uid: rows)
    monkeypatch.setattr(server.repo, "runs_spent", lambda cur, uid, ids: {})
    monkeypatch.setattr(server.repo, "active_run_counts", lambda cur, uid, silent_before=None: {})
    monkeypatch.setattr(server.repo, "list_runs_version", lambda cur, uid: rows)
    monkeypatch.setattr(server, "_research_totals", lambda cur, uid: {"tried": 0, "passed": 0})
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: None), {"id": 7}, (), {}, {}, None)
    out = server.list_runs(ctx)["runs"]
    assert [(r["id"], r["stop_reason"]) for r in out] == [(2, "credits"), (1, "user")]
    assert all("out_of_credits" not in r for r in out)


@pytest.mark.parametrize("status,raw,want", [
    ("running", "By you", None),
    ("paused", None, None),
    ("paused", "By you", "You paused it"),
    ("stopped", "By you", "You removed it"),
    ("paused", "Kill switch", "You pressed Kill"),
    ("paused", "Approved agent proposal", "You approved the agent's proposal to pause it"),
    ("paused", "force-closed: position down 33.0% >= stop 30.0%",
     "Its safety stop sold a position that had lost 33% of its cost"),
    ("paused", "drawdown 23.4% >= limit 20.0%", "It lost 23% of its money, past its 20% limit"),
    # A reason that is already a sentence stays as written.
    ("paused", "Lost $12.00, more than the $10.00 guard (2x its worst backtest drawdown).",
     "Lost $12.00, more than the $10.00 guard (2x its worst backtest drawdown)."),
    ("paused", "Autopilot daily loss limit hit", "Autopilot daily loss limit hit"),
])
def test_a_deployment_says_why_it_is_not_running_in_plain_words(status, raw, want):
    assert server._status_why({"status": status, "status_reason": raw}) == want
