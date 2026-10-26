"""Self-repair: crypto ideas killed by missing data open a data request; the idea is re-tested once
the data exists, at most once."""
import json
import os
import uuid

import pytest

from app.research import rsi_repair


def test_what_each_pipeline_death_asks_for():
    need = rsi_repair.classify_need
    assert need("btc15m", "no_data", "no settled contracts for btc15m") == ("history", "", "btc15m")
    assert need("btc15m_tick", "no_data", "no usable seconds") == ("ticks", "", "btc15m_tick")
    # a 1-minute order-book feature the series lacks -> the 1-minute collector
    assert need("eth15m", "feature_unavailable", "taker_yes_vol_60s is not populated on eth15m") == \
        ("micro", "taker_yes_vol_60s", "eth15m")
    # a per-second feature -> per-second data, re-tested on the tick twin
    assert need("btc15m", "feature_unavailable", "needs microprice, which is not available here") == \
        ("ticks", "microprice", "btc15m_tick")
    assert need("btc15m", "feature_unavailable", "this needs tick-level book data that is unavailable") == \
        ("ticks", "", "btc15m_tick")
    # a core feature every frame carries: a proposer belief, nothing to collect
    assert need("btc15m", "feature_unavailable", "vol_60m is unavailable") is None
    assert need("btc15m", "loses", "loses money") is None
    assert need("nope", "no_data", "x") is None
    assert rsi_repair.tick_twin("eth15m") is None and rsi_repair.tick_twin("btc15m") == "btc15m_tick"


def test_a_per_second_request_without_a_twin_records_but_never_retests_on_candles():
    assert rsi_repair.classify_need("eth15m", "feature_unavailable", "needs tick-level data, unavailable") == \
        ("ticks", "", "eth15m")
    assert rsi_repair.is_ready(None, {"kind": "ticks", "market": "eth15m", "need": "", "series": "KXETH15M"}) is False


def test_the_requeue_prompt_names_the_idea_and_what_arrived():
    p = rsi_repair.requeue_prompt({"kind": "micro", "need": "flow_imb_60s", "idea_title": "Flow leads mid",
                                   "idea_why": "flow_imb_60s is not populated"})
    assert p.startswith("Re-test Flow leads mid now that the flow_imb_60s feature has been collected")
    assert "flow_imb_60s is not populated" in p


def test_collectors_add_requested_series_after_their_own():
    from data_pipeline import feature_1m_collector as fc

    class Cur:
        def execute(self, sql, args=None):
            assert "app_data_requests" in sql and args[0] == "micro"

        def fetchall(self):
            return [{"series": "KXBTC15M"}, {"series": "KXHYPE15M"}]

    assert fc.with_requested(["KXBTC15M", "KXETH15M"], Cur()) == ["KXBTC15M", "KXETH15M", "KXHYPE15M"]


def test_history_sync_puts_requested_markets_first_after_curated(monkeypatch):
    from app import market_history as mh
    from app.trading.markets import CURATED, Market
    order = []
    monkeypatch.setattr(mh, "_sync_settled", lambda cur, m, now, stats: None)
    monkeypatch.setattr(mh, "sync_market_candles", lambda cur, m, deadline=None: order.append(m.key))
    monkeypatch.setattr(mh, "_candle_rotation", None)
    cur_key = next(iter(CURATED))
    extra = [Market("cat_%d" % i, "KXCAT%d" % i, "c", candle_minutes=60, history_days=5) for i in range(5)]
    mh.sync_all_markets(None, [CURATED[cur_key]] + extra, None, float("inf"), {}, requested=["cat_3"])
    assert order[:2] == [cur_key, "cat_3"]


needs_db = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn
    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def _user(cur, autopilot):
    tag = uuid.uuid4().hex[:8]
    cur.execute("INSERT INTO app_users (google_sub, email, name, autopilot, created_at, last_login_at) "
                "VALUES (%s,%s,'t',%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                ("repair-" + tag, "repair-%s@example.com" % tag, 1 if autopilot else 0))
    return cur.lastrowid


def _dead_run(cur, uid, market, why, status="succeeded", error=None):
    cur.execute("INSERT INTO app_agent_runs (user_id, kind, market, prompt, status, error, created_at) "
                "VALUES (%s,'research',%s,'',%s,%s,UTC_TIMESTAMP())", (uid, market, status, error))
    rid = cur.lastrowid
    if why:
        cur.execute("INSERT INTO app_agent_events (run_id, kind, message, data_json, created_at) VALUES "
                    "(%s,'verdict','DROPPED',%s,UTC_TIMESTAMP())",
                    (rid, json.dumps({"status": "abandoned", "title": "Flow leads mid", "why": why})))
    return rid


@needs_db
def test_a_missing_feature_opens_one_request_then_requeues_once_ready(conn, monkeypatch):
    cur = conn.cursor()
    uid = _user(cur, autopilot=True)
    _dead_run(cur, uid, "eth15m", "taker_yes_vol_60s is not populated on this market")
    _dead_run(cur, uid, "eth15m", "taker_yes_vol_60s is unavailable again")          # same need: one row
    _dead_run(cur, uid, "high_ny", "obs_high_f is unavailable")                       # weather: not crypto
    conn.commit()
    monkeypatch.setattr(rsi_repair, "is_ready", lambda cur, req: False)
    rsi_repair.run(conn)
    mine = [r for r in rsi_repair.summary(cur, uid)]
    assert [(r["market"], r["kind"], r["need"], r["status"]) for r in mine] == \
        [("eth15m", "micro", "taker_yes_vol_60s", "open")]
    assert "KXETH15M" in rsi_repair.wanted_series(cur, "micro", 50)
    # data arrives: one re-test, then never again
    from app.research import agent
    monkeypatch.setattr(agent, "research_unavailable_reason", lambda m: None)
    monkeypatch.setattr(rsi_repair, "is_ready", lambda cur, req: True)
    rsi_repair.run(conn)
    rsi_repair.run(conn)
    req = rsi_repair.summary(cur, uid)[0]
    assert req["status"] == "requeued" and req["requeued_run_id"]
    cur.execute("SELECT market, prompt, status, brief FROM app_agent_runs WHERE id=%s", (req["requeued_run_id"],))
    run = cur.fetchone()
    assert run["market"] == "eth15m" and run["status"] == "queued" and run["brief"] == 1
    assert run["prompt"].startswith("Re-test Flow leads mid now that the taker_yes_vol_60s feature")
    cur.execute("SELECT COUNT(*) AS n FROM app_agent_runs WHERE user_id=%s AND prompt LIKE 'Re-test%%'", (uid,))
    assert cur.fetchone()["n"] == 1
    conn.commit()


@needs_db
def test_without_autopilot_the_request_waits_with_a_reason(conn, monkeypatch):
    cur = conn.cursor()
    uid = _user(cur, autopilot=False)
    _dead_run(cur, uid, "sol15m", None, status="failed", error="no settled contracts for market 'sol15m'")
    conn.commit()
    monkeypatch.setattr(rsi_repair, "is_ready", lambda cur, req: True)
    monkeypatch.setattr(rsi_repair, "window_contracts", lambda cur, m: 10)
    rsi_repair.run(conn)
    req = rsi_repair.summary(cur, uid)[0]
    assert (req["kind"], req["status"], req["note"]) == ("history", "ready", "waiting: autopilot is off")
    conn.commit()


def test_a_micro_feature_is_ready_only_once_it_covers_the_research_window(monkeypatch):
    """Prod 2026-10-24 run 2726: requeued "now that ob_imbalance has been collected", it died on
    "ob_imbalance not populated": the collected hours were all newer than the research window."""
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 24, 23, 0)
    monkeypatch.setattr(rsi_repair, "_now", lambda: now)
    seen = []

    class Cur:
        def execute(self, sql, args):
            seen.append(args)
        def fetchone(self):
            return {"h": 24 * 5}

    import app.research_repository as rr
    monkeypatch.setattr(rr, "get_active_partition", lambda cur, m: None)
    lo, hi = rsi_repair.research_window(Cur(), "eth15m")
    days = rsi_repair.MARKETS["eth15m"].history_days
    assert lo == now - timedelta(days=days) and abs((hi - lo).days - days * 0.6) <= 1
    assert hi < now - timedelta(days=days * 0.39)
    req = {"kind": "micro", "series": "KXETH15M", "need": "taker_yes_vol_60s", "market": "eth15m"}
    assert rsi_repair.is_ready(Cur(), req)
    assert seen[-1][1:] == (lo, hi)                       # coverage counted inside the window only
    monkeypatch.setattr(rr, "get_active_partition",
                        lambda cur, m: {"research_from_ts": 1_700_000_000, "research_to_ts": 1_710_000_000})
    lo2, hi2 = rsi_repair.research_window(Cur(), "eth15m")
    assert (hi2 - lo2).total_seconds() == 10_000_000
