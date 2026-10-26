"""The free mispricing scan: research-window leads per market, ranked, without freezing anything."""
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import rsi_scout
from tests.test_agent_gatekeeper import _fv_dataset


def test_a_planted_forecast_edge_is_a_ranked_lead():
    got = rsi_scout.scan_dataset(_fv_dataset(informative=True))
    assert got["fv_leads"] == 4 and got["cal_leads"] == 0
    assert got["best_z"] > 2 and got["best_net_c"] > 5
    assert got["best_what"].startswith("fcst_p_yes") and got["best_what"].endswith("vs mid")
    assert got["contracts"] == 300


def test_a_fair_market_has_no_lead():
    got = rsi_scout.scan_dataset(_fv_dataset(informative=False))
    assert (got["cal_leads"], got["fv_leads"], got["best_z"], got["best_what"]) == (0, 0, None, None)


class _Cur:
    def __init__(self, scanned=None, ranking=None):
        self.sql, self.scanned, self.rank = [], scanned or {}, ranking or []
        self._rows = []

    def execute(self, sql, args=None):
        self.sql.append((sql, args))
        if sql.startswith("SELECT market, scanned_at"):
            self._rows = [{"market": k, "scanned_at": v} for k, v in self.scanned.items()]
        elif "ORDER BY best_z" in sql:
            self._rows = list(self.rank)
        else:
            self._rows = []

    def fetchall(self):
        return self._rows


def test_candidates_scan_the_stalest_first_and_skip_fresh_ones(monkeypatch):
    from app import repository as repo
    from app.trading.markets import MARKETS
    monkeypatch.setattr(repo, "series_with_candles", lambda cur: {MARKETS[k].series for k in ("btc15m", "high_ny", "eth15m")})
    now = rsi_scout._now()
    cur = _Cur(scanned={"btc15m": now - timedelta(hours=30), "high_ny": now - timedelta(hours=1)})
    assert rsi_scout.candidates(cur, stale_hours=24) == ["eth15m", "btc15m"]


def test_run_saves_every_market_and_survives_a_bad_one(monkeypatch):
    saved = []
    monkeypatch.setattr(rsi_scout, "scan_market", lambda cur, m: (_ for _ in ()).throw(ValueError("no settled contracts"))
                        if m == "bad" else {"cal_leads": 1, "best_z": 3.0, "best_what": "x"})
    monkeypatch.setattr(rsi_scout, "save", lambda cur, m, row: saved.append((m, row)))
    conn = SimpleNamespace(cursor=lambda: None, commit=lambda: None)
    assert rsi_scout.run(conn, ["bad", "high_ny"], max_markets=5) == 2
    assert saved[0] == ("bad", {"error": "ValueError: no settled contracts"}) and saved[1][1]["best_z"] == 3.0


def test_prompt_lines_name_the_market_and_its_lead():
    rows = [{"market": "high_ny", "family": "weather-high", "best_what": "fcst_p_yes >24h blend vs mid",
             "best_net_c": 4.2, "best_z": 2.7, "cal_leads": 0, "fv_leads": 2},
            {"market": "gone_market", "best_z": 9.0}]
    text = rsi_scout.prompt_lines(_Cur(ranking=rows))
    assert text.startswith("- high_ny (NYC") and "+4.2c net per contract, z=2.7" in text
    assert "gone_market" not in text
    assert rsi_scout.prompt_lines(_Cur()) == ""


needs_db = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@needs_db
def test_save_then_rank_against_a_real_database():
    from app import schema
    from data_pipeline.common import get_db_conn
    schema.main()
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        rsi_scout.save(cur, "high_ny", {"contracts": 900, "research_days": 200.0, "cal_leads": 1, "fv_leads": 2,
                                        "best_z": 2.9, "best_net_c": 3.1, "best_what": "fcst_p_yes >24h blend vs mid"})
        rsi_scout.save(cur, "btc15m", {"error": "ValueError: no settled contracts"})
        conn.commit()
        top = rsi_scout.ranking(cur, 5)
        assert top[0]["market"] == "high_ny" and top[0]["family"] == "weather-high"
        assert "btc15m" not in [r["market"] for r in top]
    finally:
        conn.close()


def test_the_research_window_is_computed_without_freezing_a_partition(monkeypatch):
    from app.research import research_repository as rr
    monkeypatch.setattr(rr, "get_active_partition", lambda cur, m: None)
    monkeypatch.setattr(rr, "save_partition", lambda *a, **k: pytest.fail("the scout must not freeze partitions"))
    t0 = 1_760_000_000
    contracts = [{"ticker": "KXHIGHNY-D%d-B60" % i, "open_ts": t0 + i * 86400, "close_ts": t0 + i * 86400 + 80000,
                  "result": "yes" if i % 3 else "no"} for i in range(200)]
    monkeypatch.setattr(rr, "partition_contracts", lambda cur, m, since: contracts)
    w = rsi_scout.research_window(None, "high_ny")
    assert t0 <= w["research_from_ts"] < w["research_to_ts"] <= w["validation_from_ts"]
    monkeypatch.setattr(rr, "get_active_partition", lambda cur, m: {"id": 7, "research_from_ts": 1})
    assert rsi_scout.research_window(None, "high_ny")["id"] == 7
