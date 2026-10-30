"""The research session page's log, paged, against a real MySQL. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).

A run-until-stopped session logs thousands of lines and its page read every one (repo.run_events with no
bound) to paint its newest. Its first read now sends the newest RUN_EVENTS_PAGE lines and, from the older
ones, what the page counts (`earlier`): every figure must read as it did from all the lines. "Show earlier
steps" pages backward (`before`) to the first line, and the 2s poll (`after`) still reads every new line.
Also the dashboard's Kalshi key presence reads: the same answers as reading the key rows, without their bytes.
"""
import json
import os
import uuid
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

OUT = "Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching."


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


class Logged:
    """The connection, with each statement its cursors send kept in `sql`."""

    def __init__(self, conn):
        self.conn, self.sql = conn, []

    def cursor(self):
        real, sql = self.conn.cursor(), self.sql

        class Cur:
            def execute(self, q, args=None):
                sql.append(" ".join(str(q).split()))
                return real.execute(q, args)

            def __getattr__(self, k):
                return getattr(real, k)
        return Cur()

    def __getattr__(self, k):
        return getattr(self.conn, k)


def _session(cur, uid, other_run):
    """A long session's log, written the way the agent writes it, with another session's lines between its own:
    thinking in blocks, ideas, the skeptic's reviews, verdicts (failed ones with what they missed, dropped ones),
    the round lines, a pause and resume, a dreaming line, and the out-of-credits step."""
    from app import repository as repo

    rid = repo.create_run(cur, uid, "research", "btc15m", "momentum", run_forever=True)
    stats = {"n_trades": 61, "p_value": 0.21, "dsr": 0.4, "sharpe": 0.3, "ci": {"lo": -0.01, "hi": 0.03},
             "mean_net_return": 0.004, "placebo_p": 0.3, "min_sample": 30, "alpha_i": 0.05, "fdr_reject": False,
             "cross_day_ok": True, "cost_stress_ok": True}
    for i in range(40):
        for j in range(12):
            repo.add_event(cur, rid, "thinking", "thought %d.%d " % (i, j) * 20, {"block": i + 1})
            repo.add_event(cur, other_run, "thinking", "another session", {"block": 1})
        repo.add_event(cur, rid, "thinking", "", {"block": i + 1, "end": True})
        title = "Idea %d" % i
        repo.add_event(cur, rid, "hypothesis", title, {"thesis": "t", "spec": {"side": "no"}, "in_sample": {"trades": 9}})
        repo.add_event(cur, rid, "challenger", "Challenger approve: fine", {"title": title, "decision": "approve"})
        if i % 5 == 4:
            repo.add_event(cur, rid, "verdict", "DROPPED \"%s\" (no candidate) — it lost money after fees" % title,
                           {"title": title, "status": "abandoned", "why": "it lost money after fees"})
        else:
            sid = repo.insert_strategy(cur, uid, rid, None, "btc15m", "momentum", title, "t", {"side": "no"}, "failed", {})
            repo.add_event(cur, rid, "verdict", "FAILED - %s: validation verdict is gatekeeper-held (classification=no_edge, "
                           "61 trades); the numbers never return to the generator." % title,
                           {"title": title, "status": "failed", "classification": "no_edge", "strategy_id": sid,
                            "n_tested": 4, "stats": stats})
        repo.add_event(cur, rid, "step", "Round %d: %d tested so far, 0 passed." % (i, i + 1))
        if i == 3:
            repo.add_event(cur, rid, "paused", "Paused by you.")
            repo.add_event(cur, rid, "resumed", "Resumed.")
        if i == 6:
            repo.add_event(cur, rid, "step", "Dreaming: tested 8 candidate policies over 7 hypotheses.")
        if i == 8:
            repo.add_event(cur, rid, "step", OUT)
    return rid


def _figures(events, pre=None):
    """What the session page works out from its lines (both bundles' viewRun and its loop panel), from `pre`
    (the server's tally of the lines it didn't send) and then each line it was sent."""
    pre = pre or {}
    fig = {"tried": pre.get("hypotheses", 0), "dropped": pre.get("dropped", 0),
           "why": {sid: w for sid, w in pre.get("why_failed", [])},
           "pauses": [(p["kind"], str(p["created_at"])) for p in pre.get("pauses", [])],
           "out_of_credits": pre.get("out_of_credits", False), "dreamed": pre.get("dreamed", False),
           "kinds": set(pre.get("kinds", []))}
    for ev in events:
        d = ev.get("data") or {}
        fig["tried"] += ev["kind"] == "hypothesis"
        if ev["kind"] in ("paused", "resumed"):
            fig["pauses"].append((ev["kind"], str(ev["created_at"])))
        fig["out_of_credits"] |= ev["kind"] == "step" and ev["message"].startswith("Paused — out of credits")
        fig["dreamed"] |= ev["kind"] == "step" and ev["message"].startswith("Dreaming:")
        if ev["kind"] == "verdict" and d.get("status") == "abandoned":
            fig["dropped"] += 1
        if ev["kind"] == "verdict" and d.get("strategy_id") is not None and d.get("why_failed"):
            fig["why"][d["strategy_id"]] = d["why_failed"]
        if ev["kind"] in ("hypothesis", "challenger", "verdict", "paused", "resumed"):
            fig["kinds"].add("step" if ev["kind"] == "verdict" and not d.get("title") else ev["kind"])
    # A strategy's missed checks as the pages show them: the first whole, and how many. The loop panel's stages
    # from the kinds of line it saw (a step lights what every session's first lines already light).
    fig["why"] = {sid: (w[0], len(w)) for sid, w in fig["why"].items()}
    fig["kinds"].discard("step")
    return fig


def _sent(out):
    from app import server

    return json.loads(json.dumps(out, default=server._json_default))


def test_a_long_sessions_page_sends_its_newest_lines_counts_the_rest_and_pages_back(conn):
    from app import repository as repo
    from app import server
    from app.services import customer_text
    from app.web.routes import research
    from app.web.views import _with_gate_lines

    cur = conn.cursor()
    user = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "t@example.com", "T", None)
    other = repo.create_run(cur, user["id"], "research", "btc15m", "momentum", run_forever=True)
    rid = _session(cur, user["id"], other)
    conn.commit()
    page = research.RUN_EVENTS_PAGE

    def get(query):
        logged = Logged(conn)
        return _sent(server.get_run(server.Ctx(logged, user, (str(rid),), query, {}, SimpleNamespace()))), logged.sql

    every = _sent(customer_text.event_rows(_with_gate_lines(repo.run_events(cur, rid))))
    assert len(every) > 3 * page
    first, sql = get({"after": "0"})
    # The newest page, word for word as the whole log sent it; the rest counted, not sent.
    assert first["events"] == every[-page:]
    assert first["earlier"]["before"] == first["events"][0]["id"]
    assert _figures(first["events"], first["earlier"]) == _figures(every)
    assert _figures(every)["out_of_credits"] and _figures(every)["dreamed"] and _figures(every)["pauses"]
    # One statement reads the event table (besides the cached dream line), bounded.
    reads = [s for s in sql if "app_agent_events" in s and "LIKE 'Dreaming:" not in s]
    assert len(reads) == 1 and "LIMIT" in reads[0], reads

    # "Show earlier steps": a page at a time back to the first line; together they are the whole log.
    got, before, more = list(first["events"]), first["earlier"]["before"], True
    while more:
        older, _ = get({"before": str(before)})
        assert 0 < len(older["events"]) <= page and set(older) == {"events", "more"}
        assert [e["id"] for e in older["events"]] == sorted(e["id"] for e in older["events"])
        assert older["events"][-1]["id"] < before
        got = older["events"] + got
        before, more = older["events"][0]["id"], older["more"]
    assert got == every

    # The poll after its last line reads every new line, unbounded, as it always has.
    last = first["events"][-1]["id"]
    for i in range(page + 5):
        repo.add_event(cur, rid, "step", "Live step %d" % i)
    conn.commit()
    poll, _ = get({"after": str(last)})
    assert [e["message"] for e in poll["events"]] == ["Live step %d" % i for i in range(page + 5)]
    assert "earlier" not in poll

    # A short session sends all its lines and nothing to page back to.
    short = repo.create_run(cur, user["id"], "research", "btc15m", "momentum")
    repo.add_event(cur, short, "step", "Only line")
    conn.commit()
    out = _sent(server.get_run(server.Ctx(conn, user, (str(short),), {"after": "0"}, {}, SimpleNamespace())))
    assert [e["message"] for e in out["events"]] == ["Only line"] and out["earlier"] is None
    # Another user's session pages nothing.
    stranger = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "s@example.com", "S", None)
    with pytest.raises(server.ApiError):
        server.get_run(server.Ctx(conn, stranger, (str(rid),), {"before": str(before + 1000)}, {}, SimpleNamespace()))


def test_the_key_presence_reads_answer_as_the_key_rows_do(conn):
    from app import repository as repo

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "k@example.com", "K", None)["id"]
    for has, get, save, drop in ((repo.has_kalshi_key, repo.get_kalshi_key, repo.save_kalshi_key, repo.delete_kalshi_key),
                                 (repo.has_kalshi_dev_key, repo.get_kalshi_dev_key, repo.set_kalshi_dev_key,
                                  repo.delete_kalshi_dev_key)):
        assert has(cur, uid) is False and get(cur, uid) is None
        save(cur, uid, "placeholder-id", b"\x00" * 32)  # placeholder bytes, never a key
        assert has(cur, uid) is True and get(cur, uid) is not None
        drop(cur, uid)
        assert has(cur, uid) is False
    conn.commit()
