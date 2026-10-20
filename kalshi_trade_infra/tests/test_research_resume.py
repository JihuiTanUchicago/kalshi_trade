"""Emergency-recovery / resumable research runs.

A broken run (worker crash, deploy restart, watchdog reap, model stall) is RECLAIMED and resumed
from a durable checkpoint instead of discarding the model credits already spent exploring. These
tests cover: the checkpoint round-trips; a run killed mid-exploration resumes WITHOUT re-exploring
the theses it already developed; the trial count after a resume is identical to an uninterrupted
run (no double-counted gatekeeper trial); an already-gated chunk is never re-gated; and the resume
retry budget caps a run that keeps breaking.
"""
import copy
import json
from datetime import timedelta

from app import agent
from app import repository as repo
from tests.test_app_agent import Conn, LOSER, RUN, Store, WINNER, hyps, plan, scripted
from tests.test_app_backtest import _dataset


# -- 1. the checkpoint round-trips --------------------------------------------


class _CkCur:
    """Minimal cursor that stores the one checkpoint_json column keyed by run_id."""

    def __init__(self):
        self.col = {}
        self._res = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("UPDATE app_agent_runs SET checkpoint_json"):
            self.col[params[1]] = params[0]
        elif s.startswith("SELECT checkpoint_json"):
            self._res = {"checkpoint_json": self.col.get(params[0])}

    def fetchone(self):
        return self._res


def test_checkpoint_round_trips():
    ck = {"chunks_done": 1, "total_passed": 2, "tried": [{"title": "H0", "spec": {"side": "yes"}}],
          "chunk": [], "round_no": 0, "market": "btc15m", "lookback": 30}
    cur = _CkCur()
    repo.save_checkpoint(cur, 5, ck)
    assert repo.load_checkpoint(cur, 5) == ck          # survives JSON serialize/deserialize exactly
    assert repo.load_checkpoint(cur, 999) is None       # a run that never checkpointed


# -- 2 & 3. resume re-uses explored theses + never double-counts a trial -------


def _count_develops(monkeypatch, bucket):
    orig = agent._develop_thesis
    monkeypatch.setattr(agent, "_develop_thesis",
                        lambda *a, **k: (bucket.append(1), orig(*a, **k))[1])


def test_resume_reuses_explored_theses_and_does_not_double_count(monkeypatch):
    ds_fn = lambda m, h=None: _dataset(n_contracts=60)

    # --- a clean, uninterrupted run (budget 2): the baseline for trials + develops ---
    store = Store(monkeypatch)
    snaps = []
    monkeypatch.setattr(agent.repo, "save_checkpoint",
                        lambda cur, run_id, ck: snaps.append(copy.deepcopy(ck)))
    develops = []
    _count_develops(monkeypatch, develops)
    model, _ = scripted([plan(), hyps(WINNER, LOSER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 2}, model=model, dataset_fn=ds_fn)
    clean_trials = store._exp          # Store._preregister counts gatekeeper trials
    assert len(develops) == 2          # both hypotheses were developed from scratch
    assert clean_trials >= 1

    # The mid-exploration crash point: one thesis developed, chunk not yet gated.
    mid = next(s for s in snaps if len(s["chunk"]) == 1 and s["chunks_done"] == 0)
    assert len(mid["tried"]) == 1 and mid["market"] == "btc15m" and mid["lookback"] is not None

    # --- resume from that checkpoint ---
    store2 = Store(monkeypatch)        # resets load/save_checkpoint stubs to defaults...
    monkeypatch.setattr(agent.repo, "load_checkpoint", lambda cur, run_id: copy.deepcopy(mid))
    monkeypatch.setattr(agent.repo, "save_checkpoint", lambda cur, run_id, ck: None)
    develops.clear()
    # NO plan() reply (lookback is resumed from the checkpoint) and only the ONE remaining hypothesis.
    model2, prompts2 = scripted([hyps(LOSER)])
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 2}, model=model2, dataset_fn=ds_fn)

    assert len(develops) == 1          # the saved thesis was re-used, only the remainder explored
    # The crashed attempt gated nothing (crash was mid-exploration, before pre-registration), so the
    # total trials charged == this resume's trials. Identical to the uninterrupted run -> no double.
    assert store2._exp == clean_trials
    assert store2.finished[0] == "succeeded"
    assert store2.finished[2] == 2     # tried count = reused + newly explored, not re-counted


def test_resume_of_already_gated_bounded_run_does_not_regate(monkeypatch):
    """A bounded run reaped AFTER its one chunk gated (cursor advanced, chunk cleared) resumes
    straight to 'succeeded' — it never re-pre-registers or re-judges anything."""
    store = Store(monkeypatch)
    ck = {"chunks_done": 1, "total_passed": 1, "tried": [{"title": "H0"}], "chunk": [],
          "round_no": 0, "market": "btc15m", "lookback": 30}
    monkeypatch.setattr(agent.repo, "load_checkpoint", lambda cur, run_id: copy.deepcopy(ck))
    model, prompts = scripted([])      # a completed resume must make ZERO model calls
    agent.run_research(Conn(), {**RUN, "max_hypotheses": 2}, model=model,
                       dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    assert store._exp == 0             # nothing re-gated -> no trial charged again
    assert store.finished == ("succeeded", None, 1, 1)
    assert prompts == []


# -- 4 & 5. reclaim-vs-fail state machine + bounded retries --------------------


class _AbCur:
    """Captures what fail_abandoned_runs does to each stale run."""

    rowcount = 1

    def __init__(self, rows):
        self._rows = rows
        self.status_updates = []       # (sql, params) for the status-flipping UPDATEs
        self.events = []               # add_event INSERT params

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT id, kind, resume_count"):
            self._fetch = self._rows
        elif s.startswith("INSERT INTO app_agent_events"):
            self.events.append(params)
        elif "SET status=" in s:
            self.status_updates.append((s, params))
        # the add_event heartbeat bump (SET heartbeat_at ... status='running') is a no-op here

    def fetchall(self):
        return self._fetch


def test_resumable_vs_failed_and_retry_cap():
    progressed = json.dumps({"chunks_done": 0, "tried": [{"t": 1}], "chunk": [{"t": 1}]})
    rows = [
        {"id": 10, "kind": "research", "resume_count": 0, "checkpoint_json": progressed},   # -> resume
        {"id": 11, "kind": "research", "resume_count": 3, "checkpoint_json": progressed},   # -> STOPPED (cap)
        {"id": 12, "kind": "research", "resume_count": 0, "checkpoint_json": None},          # -> STOPPED (no progress)
        {"id": 13, "kind": "review", "resume_count": 0, "checkpoint_json": progressed},      # -> STOPPED (not research)
    ]
    cur = _AbCur(rows)
    reaped = repo.fail_abandoned_runs(cur, timedelta(seconds=240), max_resumes=3)
    assert reaped == 4

    requeued = [p[1] for s, p in cur.status_updates if "status='queued'" in s]
    # An interrupted/abandoned run is STOPPED, never failed — the UPDATE carries (msg, tried, passed, …);
    # id is the 5th param. No status='failed' is ever written here any more.
    assert not any("status='failed'" in s for s, _ in cur.status_updates)
    stopped = {p[4]: p[0] for s, p in cur.status_updates if "status='stopped'" in s}

    assert requeued == [10]                                  # only the one with progress + budget resumes
    assert set(stopped) == {11, 12, 13}                       # every non-resumable run is STOPPED, not failed
    assert "Explored 1 hypothesis" in stopped[11]             # had progress -> reports how far it got
    assert "interrupted before" in stopped[12]                # no progress -> explored nothing
    assert "Explored 1 hypothesis" in stopped[13]             # non-research reaped the same way
    assert 10 in [p[0] for p in cur.events]                   # the reclaim is announced on the resumed run


def test_resume_count_at_cap_is_not_reclaimed():
    """One extra guard on the boundary: resume_count == max_resumes fails, resume_count < max resumes."""
    at_cap = [{"id": 1, "kind": "research", "resume_count": 2,
               "checkpoint_json": json.dumps({"tried": [{"t": 1}]})}]
    cur = _AbCur(at_cap)
    repo.fail_abandoned_runs(cur, timedelta(seconds=90), max_resumes=2)
    assert all("status='queued'" not in s for s, _ in cur.status_updates)   # at the cap -> not reclaimed
    assert any("status='stopped'" in s for s, _ in cur.status_updates)       # terminal = STOPPED, not failed
