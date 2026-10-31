"""Research watch: flags failed, stalled, burning and bug-killed research sessions."""
from datetime import datetime, timedelta

from app import research_watch as rw

NOW = datetime(2026, 10, 24, 21, 0, 0)


def _run(i, status, market="btc15m", mins_ago=60, **kw):
    r = {"id": i, "user_id": 1, "market": market, "status": status, "model": "sonnet-4-5", "prompt": "p",
         "error": None, "input_tokens": 0, "output_tokens": 0, "created_at": NOW - timedelta(minutes=mins_ago),
         "started_at": NOW - timedelta(minutes=mins_ago - 1), "heartbeat_at": None, "finished_at": None}
    r.update(kw)
    return r


def _drop(why, at=NOW):
    return {"kind": "verdict", "message": "DROPPED", "data": {"status": "abandoned", "title": "idea", "why": why},
            "created_at": at}


def test_the_report_flags_what_needs_attention(monkeypatch):
    monkeypatch.setattr(rw.rsi, "run_cost_usd", lambda run: 8.0 if run["id"] == 3 else 0.5)
    runs = [
        _run(1, "failed", error="The agent's reply could not be used: unknown field(s) for a code strategy: side",
             finished_at=NOW - timedelta(minutes=50)),
        _run(2, "running", heartbeat_at=NOW - timedelta(minutes=40)),
        _run(3, "succeeded", market="kxnfltd", finished_at=NOW - timedelta(minutes=5)),
        _run(4, "queued", started_at=None, mins_ago=90),
        _run(5, "succeeded", market="kxnba", finished_at=NOW),
    ]
    events = {
        2: [{"kind": "step", "message": "x", "data": {"phase": "developing"}, "created_at": NOW - timedelta(minutes=35)}],
        3: [_drop("The GBM model is fundamentally incompatible with NFL outcome markets")] * 3
           + [_drop("loses money"), {"kind": "verdict", "message": "underpowered", "data": {"power": 0.2},
                                     "created_at": NOW}],
        5: [_drop("spec invalid: unknown field")] + [_drop("taker_yes_vol_60s is not populated")] * 4,
    }
    rep = rw.build_report(runs, events, NOW, 3)
    kinds = {(a["kind"], a["run_id"]) for a in rep["anomalies"]}
    assert ("failed", 1) in kinds and ("stalled", 2) in kinds and ("burn", 3) in kinds
    assert ("wrong_fit", 3) in kinds and ("queued_long", 4) in kinds
    assert ("bug_deaths", 5) in kinds and ("pipeline", 5) in kinds
    assert rep["anomalies"][0]["severity"] == "high"
    failed = next(a for a in rep["anomalies"] if a["kind"] == "failed")
    assert failed["detail"].startswith("our bug:")
    stalled = next(s for s in rep["runs"] if s["run_id"] == 2)
    assert stalled["idle_min"] == 35.0 and stalled["phase"] == "developing"
    r3 = next(s for s in rep["runs"] if s["run_id"] == 3)
    assert [d["tag"] for d in r3["drops"]] == ["wrong_fit"] * 3 + ["loses"]
    assert (r3["developed"], r3["underpowered"], r3["not_finalist"]) == (1, 1, 0)
    assert rep["status_counts"] == {"failed": 1, "running": 1, "succeeded": 2, "queued": 1}
    assert rep["totals"]["explored"] >= 9


def test_a_market_researched_again_and_again_without_a_gate_is_flagged(monkeypatch):
    monkeypatch.setattr(rw.rsi, "run_cost_usd", lambda run: 1.0)
    runs = [_run(i, "succeeded", market="high_ny", finished_at=NOW) for i in range(3)]
    rep = rw.build_report(runs, {}, NOW, 3)
    assert [(a["kind"], a["market"]) for a in rep["anomalies"]] == [("repeat", "high_ny")]


def test_publish_writes_latest_and_a_dated_copy():
    puts = []

    class S3:
        def put_object(self, **kw):
            puts.append(kw["Key"])

    key = rw.publish({"generated_at": "2026-10-24T21:00:00+00:00", "anomalies": []}, s3=S3())
    assert key == "research-watch/date=2026-10-24/2100.json"
    assert puts == [key, "research-watch/latest.json"]


def test_flags_of_a_run_that_ended_over_an_hour_ago_drop_to_low(monkeypatch):
    """A handled failure was re-flagged "high" for the whole 3h window, burying new ones."""
    monkeypatch.setattr(rw.rsi, "run_cost_usd", lambda run: 0.5)
    err = "The agent's reply could not be used: unknown field(s) for a code strategy: side"
    runs = [_run(1, "failed", error=err, finished_at=NOW - timedelta(minutes=90), mins_ago=120),
            _run(2, "failed", error=err, finished_at=NOW - timedelta(minutes=10))]
    rep = rw.build_report(runs, {}, NOW, 3)
    sev = {a["run_id"]: (a["severity"], a.get("stale", False)) for a in rep["anomalies"]}
    assert sev == {1: ("low", True), 2: ("high", False)}
    assert rep["anomalies"][0]["run_id"] == 2


def test_a_spec_invalid_drop_stays_in_the_report_past_the_newest_twelve():
    """bug_deaths is triaged from the drop's text; run 3081's spec_invalid drop was the 3rd of 15
    and fell outside the newest-12 window, so the high flag arrived with nothing to read."""
    drops = [{"tag": "loses", "title": "t%d" % i, "why": ""} for i in range(15)]
    drops[2] = {"tag": "spec_invalid", "title": "bad", "why": "spec invalid: unknown field"}
    kept = rw._kept_drops(drops)
    assert kept[0]["title"] == "bad" and len(kept) == 13 and kept[1:] == drops[-12:]
    assert rw._kept_drops(drops[:5]) == drops[:5]


class _IdleCur:
    """Answers load_idle's queries from a dict of users: {uid: (last_run_or_None, active, note)}."""
    def __init__(self, users):
        self.users, self.rows = users, []

    def execute(self, sql, args=()):
        uid = args[0] if args else None
        if "FROM app_users" in sql:
            self.rows = [{"id": u} for u in self.users]
        elif "ORDER BY id DESC LIMIT 1" in sql and "app_agent_runs" in sql:
            self.rows = [self.users[uid][0]] if self.users[uid][0] else []
        elif "status IN" in sql:
            self.rows = [{"1": 1}] if self.users[uid][1] else []
        elif "app_chat_messages" in sql:
            self.rows = [{"content": self.users[uid][2]}] if self.users[uid][2] else []

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def test_an_autopilot_user_with_credit_and_no_research_for_30_min_is_flagged(monkeypatch):
    """Prod 2026-10-26: no research started 06:03-07:58Z (every review asked for ltc15m) and nobody
    noticed for two hours. Users without credit are skipped: their reviews are off by design."""
    from app.adapters.stripe import billing
    monkeypatch.setattr(billing, "is_ready", lambda cur, uid: uid != 2)
    refusal = "I can't research that market — pick one Tau supports, or let me choose."
    cur = _IdleCur({
        1: ({"id": 3337, "created_at": NOW - timedelta(minutes=95)}, False, refusal),  # idle, with credit
        2: ({"id": 3321, "created_at": NOW - timedelta(minutes=200)}, False, None),     # idle, no credit
        3: ({"id": 3350, "created_at": NOW - timedelta(minutes=10)}, False, None),     # started recently
        4: ({"id": 3300, "created_at": NOW - timedelta(minutes=90)}, True, None),      # one is running
    })
    idle = rw.load_idle(cur, NOW)
    assert [u["user_id"] for u in idle] == [1]
    assert idle[0]["idle_min"] == 95 and idle[0]["reason"] == refusal
    report = rw.build_report([], {}, NOW, 3, idle)
    flag = report["anomalies"][0]
    assert flag["severity"] == "high" and flag["kind"] == "idle" and flag["user_id"] == 1
    assert "95 min (last run 3337)" in flag["detail"] and "can't research that market" in flag["detail"]


def test_features_falling_behind_the_raw_archive_is_flagged():
    # Prod 10-25 23:00Z: features_1s stopped for ~30h while the raw archives looked fine.
    from app import research_watch as rw

    class S3:
        def __init__(self, keys):
            self.keys = keys

        def list_objects_v2(self, Bucket, Prefix):
            return {"Contents": [{"Key": k} for k in self.keys if k.startswith(Prefix)]}

    now = datetime(2026, 10, 27, 5, 30)
    raw = ["ticks/manifest/kalshi/date=2026-10-27/%02d.json" % h for h in range(5)]
    fresh = rw.data_freshness(S3(raw + ["ticks/manifest/features_1s/date=2026-10-27/03.json"]), now)
    assert fresh == {"kalshi": "2026-10-27T04:00:00", "features_1s": "2026-10-27T03:00:00", "lag_h": 1.0}
    assert rw.freshness_anomalies(fresh) == []
    stale = rw.data_freshness(S3(raw + ["ticks/manifest/features_1s/date=2026-10-25/22.json"]), now)
    assert stale["lag_h"] == 30.0
    [a] = rw.freshness_anomalies(stale)
    assert a["severity"] == "high" and a["kind"] == "features_stale" and "30h behind" in a["detail"]
    assert rw.freshness_anomalies(rw.data_freshness(S3(raw), now))[0]["kind"] == "features_stale"
    assert rw.freshness_anomalies(None) == []


def test_the_report_shows_the_long_term_memory(monkeypatch):
    """rsi_sleep: each run says whether the proposer read the memory, and the report lists every
    family's newest memory with what it calls exhausted."""
    from app.research import rsi_sleep
    now = datetime(2026, 10, 30, 8, 0)
    run = {"id": 7, "user_id": 1, "market": "btc15m", "status": "succeeded", "created_at": now,
           "started_at": now, "finished_at": now}
    events = [{"kind": "step", "message": "Using long-term research memory for crypto markets.",
               "data": {"phase": "memory"}, "created_at": now},
              {"kind": "step", "message": "Loaded data", "data": {"phase": "data_loaded"}, "created_at": now}]
    assert rw.run_summary(run, events, now)["memory"] == ["Using long-term research memory for crypto markets."]
    led = rsi_sleep.fold({}, [{"run_id": i, "market": "btc15m", "day": "2026-10-30", "message": "x",
                               "data": {"status": "abandoned", "title": "Stale quote lag", "why": "loses"}}
                              for i in range(12)])

    class Cur:
        def execute(self, sql, args=None):
            pass

        def fetchall(self):
            return [{"user_id": 1, "family": "crypto"}]

    monkeypatch.setattr(rsi_sleep, "latest", lambda cur, u, f: {
        "user_id": u, "family": f, "version": 3, "created_at": now, "ledger": led, "lessons": [{}, {}],
        "changes": "kept"})
    rows = rw.memory_rows(Cur())
    assert rows == [{"user_id": 1, "family": "crypto", "version": 3, "created_at": str(now), "runs": 12,
                     "ideas": 12, "lessons": 2, "changes": "kept",
                     "exhausted": {"btc15m": ["Kalshi lags spot (stale quotes)"]}}]
    assert rw.build_report([run], {7: events}, now, 3.0, memory=rows)["memory"] == rows


def test_idle_is_low_when_long_term_memory_closed_every_market(monkeypatch):
    """Prod 2026-10-31: after the last probe (01:29Z) the floor stood down by design (Todd 2026-10-30,
    #676/#679) and every report carried a high idle flag. Idle is then expected, so it is low."""
    from app.adapters.stripe import billing
    from app.research import agent
    monkeypatch.setattr(billing, "is_ready", lambda cur, uid: True)
    monkeypatch.setattr(agent, "autopilot_research_exhausted", lambda cur, uid: uid == 1)
    cur = _IdleCur({
        1: ({"id": 4582, "created_at": NOW - timedelta(minutes=158)}, False, None),   # closed by memory
        2: ({"id": 4590, "created_at": NOW - timedelta(minutes=60)}, False, None),    # idle by mistake
    })
    idle = rw.load_idle(cur, NOW)
    assert [(u["user_id"], u["exhausted"]) for u in idle] == [(1, True), (2, False)]
    flags = {a["user_id"]: a for a in rw.build_report([], {}, NOW, 3, idle)["anomalies"]}
    assert flags[1]["severity"] == "low" and "as intended" in flags[1]["detail"]
    assert flags[2]["severity"] == "high"
