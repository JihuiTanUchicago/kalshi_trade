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
