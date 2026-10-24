"""Free external data brought into the research fold (Pillar 3): the point-in-time as-of join
(no future value at an earlier ts), graceful degradation, the spec request validating + surviving
into the hash/provenance, and the enrich() join actually reaching the window's frames.
"""
from app import backtest, freedata
from app import spec as specmod
from app.gatekeeper import Prereg

from tests.test_code_strategy import _dataset, _code_spec, BUY_ALL


# -- the as-of join is the leak guard -----------------------------------------


def test_asof_join_never_surfaces_a_future_value():
    obs = [(100, 1.0), (300, 2.0)]  # (known_at_ts, value)
    j = freedata.asof_join([50, 100, 150, 299, 300, 500], obs)
    assert 50 not in j                       # nothing known before the first observation
    assert j[100] == 1.0 and j[150] == 1.0   # latest known value
    assert j[299] == 1.0                      # value released at 300 is INVISIBLE at 299 (no leak)
    assert j[300] == 2.0 and j[500] == 2.0


def test_asof_join_is_order_independent():
    assert freedata.asof_join([500, 50, 150], [(300, 2.0), (100, 1.0)]) == {150: 1.0, 500: 2.0}


def test_lag_days_pushes_the_known_at_time_forward(monkeypatch):
    # observation dated at ts=0; with lag_days=2 it is not known until ts=2*86400.
    monkeypatch.setattr(freedata, "_FETCHERS", {"fred": lambda s: [(0, 7.0)]})
    freedata._CACHE.clear()
    obs, prov = freedata.resolve({"name": "x", "source": "fred", "series": "S", "lag_days": 2})
    assert obs == [(2 * 86400, 7.0)]
    assert prov["observations"] == 1


# -- graceful degradation ------------------------------------------------------


def test_unknown_source_skips_not_crashes():
    obs, prov = freedata.resolve({"name": "x", "source": "nope", "series": "Z"})
    assert obs is None and "skipped" in prov


def test_fetch_failure_skips(monkeypatch):
    def boom(series):
        raise RuntimeError("network down")
    monkeypatch.setattr(freedata, "_FETCHERS", {"fred": boom})
    freedata._CACHE.clear()
    obs, prov = freedata.resolve({"name": "x", "source": "fred", "series": "S"})
    assert obs is None and "skipped" in prov


# -- spec request: validates, hashes, and shows up in provenance ---------------


def test_datasets_request_validates_and_normalises():
    s = _code_spec(code=BUY_ALL)
    s2 = specmod.validate({"market": "btc15m", "code": BUY_ALL,
                           "sizing": {"stake": 10.0, "max_positions": 1},
                           "datasets": [{"name": "dgs10", "source": "fred", "series": "DGS10"}]})
    assert s2["datasets"] == [{"name": "dgs10", "source": "fred", "series": "DGS10", "lag_days": 1}]
    assert "datasets" not in s  # a spec without datasets keeps the key absent (hash stability)


def test_datasets_bad_source_rejected():
    import pytest
    with pytest.raises(specmod.SpecError):
        specmod.validate({"market": "btc15m", "code": BUY_ALL,
                          "sizing": {"stake": 10.0, "max_positions": 1},
                          "datasets": [{"name": "x", "source": "bloomberg", "series": "X"}]})


def test_dataset_request_changes_the_hash_and_is_in_provenance():
    base = _code_spec(code=BUY_ALL)
    withds = specmod.validate({"market": "btc15m", "code": BUY_ALL,
                               "sizing": {"stake": 10.0, "max_positions": 1},
                               "datasets": [{"name": "dgs10", "source": "fred", "series": "DGS10"}]})
    h = lambda sp: Prereg(user_id=1, run_id=1, market="btc15m", spec=sp,
                          economic_rationale="r").hypothesis_hash()
    assert h(base) != h(withds)  # the request is part of the frozen identity -> pins the trial
    assert "fred:DGS10@lag1d" in specmod.data_sources_for(withds)


# -- enrich() joins onto the real window frames --------------------------------


def test_enrich_writes_external_values_point_in_time(monkeypatch):
    freedata._CACHE.clear()
    ds = _dataset()
    window = backtest._binary_window("btc15m", ds.frames)
    tss = sorted(f["ts"] for f in window["frames"])
    mid = tss[len(tss) // 2]
    # one observation known exactly at the middle frame (lag_days=0): earlier frames see nothing,
    # that frame and later see 9.0.
    monkeypatch.setattr(freedata, "_FETCHERS", {"fred": lambda s: [(mid, 9.0)]})
    spec = dict(_code_spec(code=BUY_ALL),
                datasets=[{"name": "r", "source": "fred", "series": "S", "lag_days": 0}])
    prov = freedata.enrich(spec, window)
    assert prov and prov[0]["observations"] == 1
    for f in window["frames"]:
        ext = f.get("external", {})
        if f["ts"] < mid:
            assert "r" not in ext           # future value absent on earlier frames
        else:
            assert ext["r"] == 9.0


def test_enrich_noop_without_datasets():
    ds = _dataset()
    window = backtest._binary_window("btc15m", ds.frames)
    assert freedata.enrich(_code_spec(code=BUY_ALL), window) == []
    assert all("external" not in f for f in window["frames"])


# -- asos: hourly weather-station observations ----------------------------------

_ASOS_CSV = """station,valid,tmpf
NYC,2026-10-23 03:51,50.0
NYC,2026-10-23 05:51,49.0
NYC,2026-10-23 18:51,61.0
NYC,2026-10-23 20:51,M
NYC,2026-10-24 04:51,48.0
NYC,2026-10-24 05:51,47.0
NYC,2026-10-24 12:51,55.0
"""


def test_asos_dailymax_resets_on_the_lst_day_and_is_delayed_to_publication(monkeypatch):
    """NYC:dailymax is the running max of the NWS climate day (midnight EST = 05:00 UTC, even under
    DST), known 15 min after each observation; missing readings are skipped."""
    from datetime import datetime, timezone

    class Resp:
        text = _ASOS_CSV
        def raise_for_status(self):
            pass
    seen = {}
    import requests
    monkeypatch.setattr(requests, "get", lambda url, params, timeout: seen.update(p=params) or Resp())
    obs = freedata._fetch_asos("nyc:dailymax", now=datetime(2026, 10, 24, tzinfo=timezone.utc))
    ts = lambda s: int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())
    assert [v for _, v in obs] == [50.0, 49.0, 61.0, 61.0, 47.0, 55.0]
    # 03:51Z is still the 10-22 climate day; 05:51Z starts 10-23; 10-24 04:51Z is still 10-23.
    assert obs[0][0] == ts("2026-10-23 03:51") + freedata.ASOS_LAG_S
    assert ("station", "NYC") in seen["p"] and ("data", "tmpf") in seen["p"]
    raw = freedata._fetch_asos("NYC", now=datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert [v for _, v in raw] == [50.0, 49.0, 61.0, 48.0, 47.0, 55.0]


def test_asos_series_grammar():
    assert freedata._parse_asos_series("NYC") == ("NYC", None)
    assert freedata._parse_asos_series("mdw:dailymax") == ("MDW", -6)
    assert freedata._parse_asos_series("KXYZ:dailymax:-7") == ("KXYZ", -7)
    import pytest
    for bad in ("N", "NY C", "NYC:dailymin", "ZZZ:dailymax", "NYC:dailymax:-5:x"):
        with pytest.raises(ValueError):
            freedata._parse_asos_series(bad)


def test_asos_is_an_accepted_dataset_source():
    s = specmod.validate({"market": "btc15m", "code": BUY_ALL, "sizing": {"stake": 5, "max_positions": 1},
                          "datasets": [{"name": "nyc_hi", "source": "asos", "series": "NYC:dailymax",
                                        "lag_days": 0}]})
    assert s["datasets"] == [{"name": "nyc_hi", "source": "asos", "series": "NYC:dailymax", "lag_days": 0}]


def test_cache_refetches_after_its_ttl(monkeypatch):
    """Worker processes live for days: a cached series must refresh, or newer frames would carry a
    stale last value forever."""
    calls = []
    monkeypatch.setattr(freedata, "_FETCHERS", {"fred": lambda s: calls.append(s) or [(0, 1.0)]})
    freedata._CACHE.clear()
    clock = [1000.0]
    monkeypatch.setattr(freedata.time, "time", lambda: clock[0])
    req = {"name": "x", "source": "fred", "series": "S", "lag_days": 0}
    freedata.resolve(req)
    freedata.resolve(req)
    assert len(calls) == 1
    clock[0] += freedata.CACHE_TTL_S + 1
    freedata.resolve(req)
    assert len(calls) == 2


def test_station_observations_name_the_builtin_weather_features(monkeypatch):
    monkeypatch.setattr(freedata, "_FETCHERS", {"asos": lambda s: [(0, 70.0 if "DAILYMAX" in s.upper() else 65.0)]})
    freedata._CACHE.clear()
    out = freedata.station_observations("NYC")
    assert out == {"obs_high_f": [(0, 70.0)], "obs_temp_f": [(0, 65.0)]}
    monkeypatch.setattr(freedata, "_FETCHERS", {"asos": lambda s: (_ for _ in ()).throw(OSError("down"))})
    freedata._CACHE.clear()
    assert freedata.station_observations("NYC") == {}   # fail-open: features simply absent


def test_live_engine_sees_the_same_station_features_as_research(monkeypatch):
    """Parity: the engine's base features for a weather market are the station readings known as of
    now, the same as research joins per frame; non-weather event markets get {}."""
    from app import engine
    from app.markets import MARKETS
    monkeypatch.setattr(freedata, "_FETCHERS",
                        {"asos": lambda s: [(100, 70.0 if "DAILYMAX" in s.upper() else 65.0), (900, 72.0)]})
    freedata._CACHE.clear()
    assert engine._event_feats(MARKETS["high_ny"], 500) == {"obs_high_f": 70.0, "obs_temp_f": 65.0}
    assert engine._event_feats(MARKETS["high_ny"], 50) == {}          # nothing known yet
    assert engine._event_feats(MARKETS["nba_game"], 500) == {}
