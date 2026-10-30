"""Research sleep (rsi_sleep): a ledger that never ages out, lessons merged without silent forgetting,
and the playbook trial no longer promoting a rewrite on sample size alone."""
import json

import pytest

from app.adapters.llm.llm import Usage
from app.research import rsi_playbook, rsi_sleep as sl
from app.research.rsi import MECHANISMS


def _drop(run_id, market, title, why, day="2026-10-27"):
    return {"run_id": run_id, "market": market, "day": day, "message": "DROPPED \"%s\"" % title,
            "data": {"status": "abandoned", "title": title, "why": why}}


def _gated(run_id, market, title, passed=False, day="2026-10-27"):
    return {"run_id": run_id, "market": market, "day": day, "message": "%s: gate" % title,
            "data": {"status": "passed" if passed else "rejected", "classification": "x", "title": title,
                     "stats": {"p_value": 0.003, "mean_net_return": 0.071}}}


STALE = "Stale quote after a spot jump"
OPTS = "Deribit options IV vs Kalshi mid"


def _history(n_stale=12, n_opts=3):
    evs = [_drop(100 + i, "btc15m", STALE, "loses money after fees: Kalshi reprices in 4 ms") for i in range(n_stale)]
    evs += [_drop(200 + i, "btc15m", OPTS, "no signal on research data", day="2026-10-26") for i in range(n_opts)]
    evs.append(_gated(300, "btc_daily", OPTS))
    evs.append({"run_id": 300, "market": "btc_daily", "day": "2026-10-27", "message": "x: holdout",
                "data": {"phase": "holdout", "classification": "forward_validated", "title": OPTS}})
    return evs


def test_outcome_reads_labels_and_skips_non_ideas():
    assert sl.outcome(_drop(1, "m", "a", "b")) == "dropped"
    assert sl.outcome(_gated(1, "m", "a")) == "gated"
    assert sl.outcome(_gated(1, "m", "a", passed=True)) == "passed"
    assert sl.outcome({"message": "REJECTED (challenger) - a", "data": {"title": "a"}}) == "developed"
    assert sl.outcome({"message": "x", "data": {"phase": "holdout", "classification": "y"}}) is None
    assert sl.outcome({"message": "x", "data": {"phase": "screen"}}) is None


def test_the_ledger_counts_every_idea_and_never_forgets():
    led = sl.fold({}, _history())
    cells = led["markets"]["btc15m"]
    stale = cells["Kalshi lags spot (stale quotes)"]
    assert (stale["tested"], stale["gated"], stale["tags"]) == (12, 0, {"loses": 12})
    assert led["ideas"] == 16 and led["runs"] == 16 and led["since"] == "2026-10-26"
    assert led["markets"]["btc_daily"]["options-implied fair value / IV vs Kalshi"]["gated"] == 1
    # A second fold adds to the counts: nothing ages out, unlike the 80-drop window.
    again = sl.fold(led, [_drop(400, "btc15m", STALE, "loses", day="2026-10-28")])
    assert again["markets"]["btc15m"]["Kalshi lags spot (stale quotes)"]["tested"] == 13
    assert again["markets"]["btc15m"]["Kalshi lags spot (stale quotes)"]["last"] == "2026-10-28"
    assert led["markets"]["btc15m"]["Kalshi lags spot (stale quotes)"]["tested"] == 12   # input untouched
    assert 400 in again["seen"]


def test_exhausted_and_untried_come_from_the_ledger():
    led = sl.fold({}, _history())
    assert sl.exhausted(led, "btc15m") == ["Kalshi lags spot (stale quotes)"]   # 3 options ideas: too few
    names = [m for m, _ in sl.untried(led, "btc15m")]
    assert "Kalshi lags spot (stale quotes)" not in names and "momentum / drift continuation" in names
    assert dict(sl.untried(led, "btc_daily"))["Kalshi lags spot (stale quotes)"] == 12


def test_the_prompt_block_names_exhausted_and_never_held_out_numbers():
    know = {"version": 2, "ledger": sl.fold({}, _history()),
            "lessons": [{"text": "Kalshi BTC books reprice in ms: lag theses die", "kind": "dead_end", "evidence": 12}]}
    block = sl.render(know, "btc15m", "crypto")
    assert block.startswith("LONG-TERM RESEARCH MEMORY for crypto markets (memory v2")
    assert "EXHAUSTED on btc15m" in block and "Kalshi lags spot (stale quotes)" in block
    assert "NEVER TESTED on btc15m" in block and "lag theses die" in block
    assert not any(n in block for n in ("0.003", "0.071", "forward_validated"))
    assert len(block) <= sl.BLOCK_CHARS
    assert sl.render(None, "btc15m", "crypto") == "" and sl.render({"ledger": {}}, "btc15m", "crypto") == ""


def test_standing_lessons_are_frozen_kept_merged_or_retired():
    old = [{"text": "a", "kind": "dead_end", "evidence": 5, "since": 1},
           {"text": "b", "kind": "data_fact", "evidence": 2, "since": 2},
           {"text": "c", "kind": "dead_end", "evidence": 4, "since": 3}]
    check = sl.check_merge(old)
    with pytest.raises(ValueError, match="L2, L3"):                 # dropped silently
        check({"keep": ["L1"], "new": [{"text": "d"}]})
    with pytest.raises(ValueError, match="reworded alone"):         # a one-lesson "merge" is a rewrite
        check({"keep": ["L2", "L3"], "merged": [{"from": ["L1"], "text": "a, softened"}]})
    with pytest.raises(ValueError, match="more than once"):
        check({"keep": ["L1", "L2", "L3"], "merged": [{"from": ["L1", "L2"], "text": "ab"}]})
    with pytest.raises(ValueError, match="L3"):                     # a retirement needs a reason
        check({"keep": ["L1", "L2"], "retired": [{"id": "L3", "why": ""}]})
    with pytest.raises(ValueError, match="at most"):
        check({"keep": ["L1", "L2", "L3"], "new": [{"text": "x%d" % i} for i in range(sl.MAX_LESSONS)]})
    out = check({"keep": [{"id": "L2", "evidence": 9}, {"id": "L3", "evidence": 1}],
                 "merged": [], "new": [{"text": "d  new", "kind": "weird", "evidence": 7}],
                 "retired": [{"id": "L1", "why": "the feature exists since 10-25"}], "changes": "one new"})
    # Kept lessons come back word for word; evidence only grows.
    assert out["lessons"] == [{"text": "b", "kind": "data_fact", "evidence": 9, "since": 2},
                              {"text": "c", "kind": "dead_end", "evidence": 4, "since": 3},
                              {"text": "d new", "kind": "dead_end", "evidence": 7}]
    assert out["retired"] == [{"id": "L1", "why": "the feature exists since 10-25"}] and out["new"] == 1
    out = check({"keep": ["L2"], "merged": [{"from": ["L1", "L3"], "text": "a and c", "evidence": 9}]})
    assert out["lessons"][1] == {"text": "a and c", "kind": "dead_end", "evidence": 9, "since": 1}


def test_evidence_lines_cap_one_bucket():
    lines = sl.evidence_lines(_history(n_stale=30))
    assert sum("stale" in l.lower() for l in lines) == 4
    assert any("REACHED THE GATE" in l for l in lines)


class _Store:
    """latest/_save/repo.research_verdicts_after stand-ins for sleep()."""

    def __init__(self, events):
        self.events, self.rows = events, []

    def latest(self, cur, user_id, family):
        return json.loads(json.dumps(self.rows[-1])) if self.rows else None

    def save(self, cur, user_id, family, version, through, ledger, lessons, changes):
        self.rows.append({"version": version, "through_run_id": through, "ledger": ledger, "lessons": lessons,
                          "changes": changes})

    def verdicts(self, cur, user_id, markets, after, include_run_id=0, max_runs=200):
        return [e for e in self.events if e["run_id"] > after]


@pytest.fixture
def store(monkeypatch):
    from app import repository as repo
    st = _Store(_history())
    monkeypatch.setattr(sl, "latest", st.latest)
    monkeypatch.setattr(sl, "_save", st.save)
    monkeypatch.setattr(repo, "research_verdicts_after", st.verdicts)
    return st


def _model(reply):
    def model(system, messages):
        model.seen = messages[0]["content"]
        return json.dumps(reply), {"input_tokens": 100, "output_tokens": 20}
    return model


def test_sleep_bootstraps_then_waits_for_enough_new_ideas(store):
    usage = Usage()
    m = _model({"new": [{"text": "lag theses die: Kalshi reprices in ms", "kind": "dead_end", "evidence": 12}],
                "changes": "first lessons"})
    did = sl.sleep(None, m, usage, 1, "crypto", ["btc15m", "btc_daily"], run_id=300)
    assert did.startswith("memory v1: 16 new ideas from 16 runs") and usage.input_tokens == 100
    assert "loses money after fees" in m.seen and "0.071" not in m.seen
    assert store.rows[-1]["through_run_id"] == 300
    # Two more ideas: not time yet, nothing written.
    store.events += [_drop(301, "btc15m", STALE, "loses"), _drop(302, "btc15m", STALE, "loses")]
    assert sl.sleep(None, m, usage, 1, "crypto", ["btc15m"], run_id=302) is None and len(store.rows) == 1
    # Enough new ideas, and a late-finishing run below the cursor is still picked up once.
    store.events += [_drop(303 + i, "btc15m", OPTS, "no signal") for i in range(sl.SLEEP_MIN_NEW)]
    store.events.append(_drop(299, "btc15m", STALE, "loses"))
    m2 = _model({"keep": [{"id": "L1", "evidence": 15}], "changes": "kept"})
    did = sl.sleep(None, m2, Usage(), 1, "crypto", ["btc15m"], run_id=342)
    led = store.rows[-1]["ledger"]
    assert did.startswith("memory v2") and led["ideas"] == 16 + 2 + sl.SLEEP_MIN_NEW + 1
    assert "L1 [dead_end, ~12 ideas] lag theses die: Kalshi reprices in ms" in m2.seen
    assert store.rows[-1]["lessons"] == [{"text": "lag theses die: Kalshi reprices in ms", "kind": "dead_end",
                                          "evidence": 15, "since": 1}]


def test_a_failed_merge_still_saves_the_ledger_and_keeps_the_lessons(store):
    sl.sleep(None, _model({"new": [{"text": "keep me"}]}), Usage(), 1, "crypto", ["btc15m"], 300)
    store.events += [_drop(400 + i, "btc15m", STALE, "loses") for i in range(sl.SLEEP_MIN_NEW)]
    did = sl.sleep(None, _model({"new": [{"text": "forgot L1"}]}), Usage(), 1, "crypto",
                   ["btc15m"], 439)
    assert "ledger only" in did
    assert store.rows[-1]["lessons"] == store.rows[0]["lessons"] and store.rows[-1]["ledger"]["ideas"] == 56


def test_the_kill_switch_hides_the_block(monkeypatch):
    monkeypatch.setenv("TAU_RSI_SLEEP", "0")
    assert not sl.enabled() and sl.prompt_block(None, 1, "crypto", "btc15m") == ""
    monkeypatch.delenv("TAU_RSI_SLEEP")
    assert sl.enabled()


def test_a_zero_reach_rewrite_is_not_promoted_on_sample_size(monkeypatch):
    """16 ideas, 0 reached vs 300 ideas, 0 reached: p_better is ~0.95 from sample size alone."""
    act = {"id": 1, "version": 4, "ideas": 300, "reached": 0}
    cand = {"id": 2, "version": 5, "ideas": 16, "reached": 0}
    assert rsi_playbook.p_better(cand, act) >= rsi_playbook.PROMOTE_P
    monkeypatch.setattr(rsi_playbook, "candidate", lambda cur, u, f: cand)
    monkeypatch.setattr(rsi_playbook, "active", lambda cur, u, f: act)
    writes = []

    class Cur:
        def execute(self, sql, args=None):
            writes.append(sql)

    assert rsi_playbook.decide(Cur(), 1, "crypto") is None and writes == []
    cand.update(ideas=rsi_playbook.MAX_IDEAS)
    assert rsi_playbook.decide(Cur(), 1, "crypto").startswith("retired v5, v4 stays")
    cand.update(ideas=20, reached=rsi_playbook.MIN_REACHED)
    assert rsi_playbook.decide(Cur(), 1, "crypto").startswith("promoted v5 over v4")


# -- against a real database ------------------------------------------------------------------

needs_db = pytest.mark.skipif(__import__("os").getenv("APP_TEST_MYSQL") != "1",
                              reason="needs APP_TEST_MYSQL=1 and a MySQL")


@needs_db
def test_sleep_round_trip_on_mysql():
    import random

    from app import repository as repo, schema
    from data_pipeline.common import get_db_conn

    schema.main()
    conn = get_db_conn()
    cur = conn.cursor()
    uid, fam = random.randrange(10**8, 2 * 10**9), "test-sleep-%d" % random.randrange(10**6)
    done = repo.create_run(cur, uid, "research", market="btc15m")
    for i in range(3):
        repo.add_event(cur, done, "verdict", 'DROPPED "%s %d" (no candidate) x loses' % (STALE, i),
                       {"status": "abandoned", "title": "%s %d" % (STALE, i), "why": "loses after fees"})
    repo.add_event(cur, done, "step", "noise", {})
    cur.execute("UPDATE app_agent_runs SET status='succeeded' WHERE id=%s", (done,))
    live = repo.create_run(cur, uid, "research", market="btc15m")     # still queued: read only when named
    repo.add_event(cur, live, "verdict", "x", {"status": "abandoned", "title": OPTS, "why": "no signal"})
    other = repo.create_run(cur, uid, "research", market="high_ny")   # another family's market
    repo.add_event(cur, other, "verdict", "x", {"status": "abandoned", "title": STALE, "why": "loses"})
    cur.execute("UPDATE app_agent_runs SET status='succeeded' WHERE id=%s", (other,))

    rows = repo.research_verdicts_after(cur, uid, ["btc15m", "btc_daily"], 0)
    assert [r["run_id"] for r in rows] == [done] * 3 and rows[0]["data"]["why"] == "loses after fees"
    assert len(repo.research_verdicts_after(cur, uid, ["btc15m"], 0, include_run_id=live)) == 4
    assert repo.research_verdicts_after(cur, uid, ["btc15m"], live) == []

    model = _model({"new": [{"text": "lag theses die", "kind": "dead_end", "evidence": 3}]})
    did = sl.sleep(cur, model, Usage(), uid, fam, ["btc15m"], run_id=live)
    assert did.startswith("memory v1: 4 new ideas from 2 runs")
    know = sl.latest(cur, uid, fam)
    assert know["version"] == 1 and know["through_run_id"] == live and know["ideas"] == 4
    assert know["lessons"][0]["text"] == "lag theses die"
    assert "lag theses die" in sl.prompt_block(cur, uid, fam, "btc15m")
    conn.rollback()
    conn.close()


def test_a_market_is_exhausted_only_when_every_mechanism_is(monkeypatch):
    names = list(dict.fromkeys(n for n, _ in MECHANISMS))
    cell = lambda tested, gated=0: {"tested": tested, "gated": gated, "passed": 0, "tags": {}}
    led = {"markets": {"btc15m": {n: cell(12) for n in names}, "btc_daily": {n: cell(12) for n in names[1:]}}}
    led["markets"]["btc_daily"][names[0]] = cell(9)          # one bucket short of the bar
    led["markets"]["btc15m_tick"] = {n: cell(12) for n in names}
    led["markets"]["btc15m_tick"][names[2]] = cell(30, gated=1)   # something reached the gate
    assert sl.market_exhausted(led, "btc15m")
    assert not sl.market_exhausted(led, "btc_daily")
    assert not sl.market_exhausted(led, "btc15m_tick")
    assert not sl.market_exhausted(led, "eth15m")    # never researched

    from app.research import agent
    reads = []
    monkeypatch.setattr(sl, "latest", lambda cur, uid, fam: reads.append(fam) or {"ledger": led})
    assert agent.exhausted_markets(None, 1, ["btc15m", "btc_daily", "btc15m_tick"]) == ["btc15m"]
    assert reads == ["crypto"]                                # one memory read per family
    monkeypatch.setattr(agent, "AUTOPILOT_SKIP_EXHAUSTED", False)
    assert agent.exhausted_markets(None, 1, ["btc15m"]) == []
    monkeypatch.setattr(agent, "AUTOPILOT_SKIP_EXHAUSTED", True)
    monkeypatch.setenv("TAU_RSI_SLEEP", "0")
    assert agent.exhausted_markets(None, 1, ["btc15m"]) == []
    monkeypatch.delenv("TAU_RSI_SLEEP")
    monkeypatch.setattr(sl, "latest", lambda *a: (_ for _ in ()).throw(RuntimeError("no table")))
    assert agent.exhausted_markets(None, 1, ["btc15m"]) == []  # no memory: nothing is exhausted
