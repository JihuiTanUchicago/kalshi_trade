"""Research playbooks: written from each run's verdicts, A/B-tested on live runs, kept only when they
raise the share of ideas that reach the gate."""
import json
import os
import random
import uuid

import pytest

from app import rsi_playbook as pb
from app.llm import Usage


def test_p_better_follows_the_evidence():
    strong = {"ideas": 40, "reached": 12}
    weak = {"ideas": 40, "reached": 2}
    assert pb.p_better(strong, weak) > 0.99
    assert pb.p_better(weak, strong) < 0.01
    assert 0.35 < pb.p_better({"ideas": 0, "reached": 0}, {"ideas": 0, "reached": 0}) < 0.65


def test_the_empty_version_adds_nothing_to_the_prompt():
    assert pb.prompt_block(None, "weather-high") == ""
    assert pb.prompt_block({"version": 0, "text": ""}, "weather-high") == ""
    block = pb.prompt_block({"version": 3, "text": "DEAD ENDS\n- fading the afternoon"}, "weather-high")
    assert block.startswith("RESEARCH PLAYBOOK v3 for weather-high") and "fading the afternoon" in block


def test_idea_lines_carry_labels_never_held_out_numbers():
    events = [
        {"kind": "verdict", "message": "x", "data": {"status": "abandoned", "title": "A", "why": "loses money"}},
        {"kind": "verdict", "message": "PASSED - B", "data": {
            "status": "passed", "classification": "statistically_supported", "title": "B",
            "stats": {"p_value": 0.001, "sharpe": 2.5, "mean_net_return": 0.07}}},
        {"kind": "verdict", "message": "REJECTED (challenger) - C: no mechanism",
         "data": {"status": "rejected", "title": "C", "strategy_id": 1}},
        {"kind": "verdict", "message": "B: holdout", "data": {"phase": "holdout", "classification": "x"}},
        {"kind": "step", "message": "noise", "data": {}},
    ]
    lines = pb.idea_lines(events)
    assert lines == ["- DROPPED on research data [loses]: A. Why: loses money",
                     "- REACHED THE GATE: B -> passed",
                     "- NOT GATED: C. REJECTED (challenger) - C: no mechanism"]
    assert not any(n in "".join(lines) for n in ("0.001", "2.5", "0.07"))


CARD = {"explored": 8, "dropped": 6, "gated": 2, "passed": 0, "death_kinds": {"pipeline": 4, "edge": 2},
        "cost_usd": 9.5}


def test_reflect_returns_the_rewritten_playbook():
    seen = {}

    def model(system, messages):
        seen["system"], seen["user"] = system, messages[0]["content"]
        return json.dumps({"playbook": "DEAD ENDS\n- longshot recalibration loses to the fee\n" * 3,
                           "changes": "added the longshot lesson"}), {"input_tokens": 10, "output_tokens": 5}

    usage = Usage()
    out = pb.reflect(model, usage, "weather-high", "NYC high temp", {"version": 0, "text": ""}, CARD,
                     ["- DROPPED on research data: A. Why: loses"], "fcst_p_yes 100% [0.0,0.1,0.9]")
    assert out["changes"] == "added the longshot lesson" and out["playbook"].startswith("DEAD ENDS")
    assert "8 ideas explored, 6 dropped on research data (edge 2, pipeline 4), 2 reached the gate" in seen["user"]
    assert "(empty: no lessons yet)" in seen["user"] and "PIPELINE FACTS" in seen["system"]
    assert usage.input_tokens == 10


def test_reflect_refuses_an_empty_rewrite():
    replies = iter([json.dumps({"playbook": "too short"})] * 3)

    def model(system, messages):
        return next(replies), {}

    from app.llm import LLMError
    with pytest.raises((LLMError, ValueError)):
        pb.reflect(model, Usage(), "f", "m", {"version": 0, "text": ""}, CARD, [], "")


# -- against a real database ------------------------------------------------------------------

needs_db = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def _fam():
    return "test-" + uuid.uuid4().hex[:8]


@needs_db
def test_lifecycle_baseline_trial_promotion(conn):
    cur = conn.cursor()
    fam, uid = _fam(), 990001
    r0 = random.randrange(10**8, 2 * 10**9)   # run ids are global, so a rerun must not resume old draws
    v0 = pb.choose(cur, uid, fam, run_id=r0)
    assert (v0["version"], v0["status"], v0["text"]) == (0, "active", "")
    assert pb.score_run(cur, r0, dict(CARD, explored=20, gated=1)) == v0["id"]
    assert pb.score_run(cur, r0, CARD) is None          # a run is credited once
    v1 = pb.add_candidate(cur, uid, fam, v0, "DEAD ENDS\n- x", "first lessons", r0)
    assert v1 == 1 and pb.candidate(cur, uid, fam)["text"] == "DEAD ENDS\n- x"
    # Thompson draw: with the candidate far ahead on evidence it is drawn almost always...
    cur.execute("UPDATE app_rsi_playbooks SET ideas=10, reached=6 WHERE user_id=%s AND family=%s AND version=1",
                (uid, fam))
    draws = [pb.choose(cur, uid, fam, run_id=r0 + 100 + i, rng=random.Random(i))["version"] for i in range(20)]
    assert draws.count(1) >= 18
    # ...and a resumed run keeps its first draw.
    assert pb.choose(cur, uid, fam, run_id=r0 + 100)["version"] == draws[0]
    assert pb.decide(cur, uid, fam) is None                    # fewer than MIN_IDEAS on the candidate
    trial = {r["status"]: r for r in pb.summary(cur, uid) if r["family"] == fam}
    assert trial["active"]["p_better"] is None and trial["candidate"]["p_better"] > 0.9
    cur.execute("UPDATE app_rsi_playbooks SET ideas=20, reached=8 WHERE user_id=%s AND family=%s AND version=1",
                (uid, fam))
    assert pb.decide(cur, uid, fam).startswith("promoted v1 over v0")
    assert pb.active(cur, uid, fam)["version"] == 1 and pb.candidate(cur, uid, fam) is None
    rows = pb.summary(cur, uid)
    mine = [r for r in rows if r["family"] == fam]
    assert [(r["version"], r["status"], r["reach_rate"]) for r in mine] == [(1, "active", 0.4)]
    conn.commit()


@needs_db
def test_a_losing_rewrite_is_retired_and_the_incumbent_stays(conn):
    cur = conn.cursor()
    fam, uid = _fam(), 990002
    v0 = pb.active(cur, uid, fam)
    cur.execute("UPDATE app_rsi_playbooks SET ideas=30, reached=9 WHERE id=%s", (v0["id"],))
    pb.add_candidate(cur, uid, fam, v0, "worse lessons", "", None)
    cur.execute("UPDATE app_rsi_playbooks SET ideas=20, reached=0 WHERE user_id=%s AND family=%s AND version=1",
                (uid, fam))
    assert pb.decide(cur, uid, fam).startswith("retired v1, v0 stays")
    assert pb.active(cur, uid, fam)["version"] == 0 and pb.candidate(cur, uid, fam) is None
    # The next rewrite gets the next version number.
    assert pb.add_candidate(cur, uid, fam, v0, "third try", "", None) == 2
    conn.commit()


@needs_db
def test_a_rewrite_whose_passes_lose_on_paper_is_not_promoted(conn):
    cur = conn.cursor()
    fam, uid = _fam(), 990003
    v0 = pb.active(cur, uid, fam)
    cur.execute("UPDATE app_rsi_playbooks SET ideas=30, reached=3 WHERE id=%s", (v0["id"],))
    pb.add_candidate(cur, uid, fam, v0, "gate-friendly lessons", "", None)
    cand = pb.candidate(cur, uid, fam)
    cur.execute("UPDATE app_rsi_playbooks SET ideas=20, reached=10 WHERE id=%s", (cand["id"],))
    bleeding = {str(cand["id"]): {"round_trips": 40, "net_pnl": -12.5}}
    assert pb.decide(cur, uid, fam, paper_of=lambda: bleeding) is None
    assert pb.candidate(cur, uid, fam)["id"] == cand["id"]           # still on trial
    few = {cand["id"]: {"round_trips": 5, "net_pnl": -3.0}}              # too few trips to veto
    assert pb.decide(cur, uid, fam, paper_of=lambda: few).startswith("promoted v1 over v0")
    conn.rollback()
