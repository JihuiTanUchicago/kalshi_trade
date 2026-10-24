"""Forecast fair-value features for daily-high/low contracts: point-in-time, and identical in
research datasets and live engine snapshots (app/weather_fcst.py, app/weather_fcst_collect.py)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app import backtest, engine, freedata
from app import weather_fcst as wf
from app import weather_fcst_collect as wfc
from app.markets import FEATURES, MARKETS, Contract


def _ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


# A settled KXHIGHNY ladder from hist_markets (2026-10-23, high was 59): ticker, strike, result.
LADDER = [("KXHIGHNY-26OCT23-T57", 0.0, "no"), ("KXHIGHNY-26OCT23-B57.5", 57.0, "no"),
          ("KXHIGHNY-26OCT23-B59.5", 59.0, "yes"), ("KXHIGHNY-26OCT23-B61.5", 61.0, "no"),
          ("KXHIGHNY-26OCT23-B63.5", 63.0, "no"), ("KXHIGHNY-26OCT23-T64", 64.0, "no")]


def _settles_yes(lo, hi, high):
    return (lo is None or lo <= high) and (hi is None or high <= hi)


def test_contract_terms_parse_from_the_ticker_and_match_real_settlements():
    assert wf.parse_contract("KXHIGHNY-26OCT23-B59.5", 59.0) == (date(2026, 10, 23), 59, 60)
    assert wf.parse_contract("KXHIGHNY-26OCT23-T64", 64.0) == (date(2026, 10, 23), 65, None)
    assert wf.parse_contract("KXHIGHNY-26OCT23-T57", 0.0) == (date(2026, 10, 23), None, 56)
    assert wf.parse_contract("KXBTCD-26OCT2317-T90000", 90000.0) is None
    for ticker, strike, result in LADDER:
        _day, lo, hi = wf.parse_contract(ticker, strike)
        assert _settles_yes(lo, hi, 59) == (result == "yes"), ticker


@pytest.mark.parametrize("observed,kind", [(None, "max"), (58.0, "max"), (61.0, "max"), (60.0, "min"), (57.0, "min")])
def test_ladder_probabilities_sum_to_one(observed, kind):
    terms = [wf.parse_contract(t, k)[1:] for t, k, _r in LADDER]
    total = sum(wf.p_yes(60.3, 2.0, lo, hi, observed, kind) for lo, hi in terms)
    assert total == pytest.approx(1.0, abs=1e-9)


def test_observed_high_rules_out_brackets_below_it():
    assert wf.p_yes(60.0, 2.0, 57, 58, observed=59.0) == 0.0
    assert wf.p_yes(60.0, 2.0, 65, None, observed=66.0) == 1.0
    # The forecast can't rise past what was already observed: the observed high is the high.
    assert wf.p_yes(50.0, 1.0, 63, 64, observed=63.0) == 1.0
    # A daily low only falls: brackets above the observed low are out.
    assert wf.p_yes(45.0, 2.0, 50, 51, observed=48.0, kind="min") == 0.0


NBS_13Z = (_ts("2026-10-23 14:30"), date(2026, 10, 23), "NBS", 60.0, 1.5)
GFS_12Z = (_ts("2026-10-23 16:30"), date(2026, 10, 23), "GFS", 62.0, None)
NBS_18Z = (_ts("2026-10-23 19:30"), date(2026, 10, 23), "NBS", 57.0, 1.0)


def _book(rows=(NBS_13Z, GFS_12Z, NBS_18Z)):
    return wf.ForecastBook(rows, freedata.ASOS_LST_OFFSET_H["NYC"], "max")


def test_book_is_point_in_time_and_prefers_the_blend():
    book = _book()
    day = date(2026, 10, 23)
    assert book.latest(day, _ts("2026-10-23 14:00")) is None          # nothing published yet
    assert book.latest(day, _ts("2026-10-23 18:00"))[:3] == ("NBS", NBS_13Z[0], 60.0)  # NBM over a newer GFS
    assert book.latest(day, _ts("2026-10-23 20:00"))[2] == 57.0       # the 18Z run once it's out
    only_gfs = _book([GFS_12Z])
    assert only_gfs.latest(day, _ts("2026-10-23 18:00"))[0] == "GFS"
    assert only_gfs.latest(day, GFS_12Z[0] + int(wf.MAX_AGE_H * 3600) + 1) is None  # stale: ignored


def test_contract_features_use_the_observed_high_only_on_the_settlement_day():
    book = _book()
    ts = _ts("2026-10-23 18:00")  # 13:00 EST on the settlement day
    f = wf.contract_features(book, "KXHIGHNY-26OCT23-B59.5", 59.0, ts, 0.30, 0.34, observed=61.0)
    assert f["fcst_high_f"] == 60.0 and f["fcst_sd_f"] == 1.5 and f["fcst_age_h"] == pytest.approx(3.5)
    assert f["fcst_p_yes"] == 0.0 and f["fcst_edge"] == pytest.approx(-0.32)  # already 61F: 59-60 is dead
    # The day before (frame on Oct 22), today's observed high says nothing about Oct 23's.
    prev = wf.ForecastBook([(_ts("2026-10-22 14:30"), date(2026, 10, 23), "NBS", 60.0, 1.5)], -5, "max")
    g = wf.contract_features(prev, "KXHIGHNY-26OCT23-B59.5", 59.0, _ts("2026-10-22 18:00"), 0.30, 0.34, observed=61.0)
    assert g["fcst_p_yes"] == pytest.approx(wf.p_yes(60.0, 1.5, 59, 60))
    # GFS has no spread: a lead-time default stands in.
    h = wf.contract_features(_book([GFS_12Z]), "KXHIGHNY-26OCT23-T64", 64.0, ts, 0.1, 0.12)
    assert h["fcst_sd_f"] == 2.5 and "fcst_edge" in h


def test_low_series_get_a_min_book_and_fcst_low_f():
    assert wf.kind_for_series("KXLOWTCHI") == "min" and wf.kind_for_series("KXHIGHNY") == "max"
    book = wf.ForecastBook([(_ts("2026-10-23 02:30"), date(2026, 10, 23), "NBS", 45.0, 2.0)], -5, "min")
    f = wf.snapshot_features(book, "KXLOWTNYC-26OCT23-B44.5", 44.0, _ts("2026-10-23 08:00"), 0.2, 0.25,
                             {"obs_high_f": 99.0, "obs_low_f": 46.0})
    assert f["fcst_low_f"] == 45.0 and "fcst_high_f" not in f
    assert f["fcst_p_yes"] == pytest.approx(wf.p_yes(45.0, 2.0, 44, 45, 46.0, "min"))


def test_every_forecast_feature_is_a_registered_feature():
    for name in ("fcst_high_f", "fcst_low_f", "fcst_sd_f", "fcst_age_h", "fcst_p_yes", "fcst_edge"):
        assert name in FEATURES


def _quote(ticker, strike, bid, ask, close):
    return engine.LiveQuote(Contract(ticker, strike, close, "KXHIGHNY"), bid, ask, 10.0, 10.0)


def test_research_and_live_compute_identical_forecast_features(monkeypatch):
    """The parity contract: the same rows, contract and frame give the same features whether
    research builds the dataset or the live engine builds its decision frame."""
    ts = _ts("2026-10-23 18:00")
    close = datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)
    obs = {"obs_high_f": [(ts - 900, 58.0)]}
    rows = [NBS_13Z, GFS_12Z, NBS_18Z]
    quotes = [_quote(t, k, 0.30, 0.36, close) for t, k, _r in LADDER]

    markets = [{"ticker": q.contract.ticker, "strike": q.contract.strike, "close_time": close, "result": "no"}
               for q in quotes]
    candles = [(q.contract.ticker, ts, q.yes_bid, q.yes_ask) for q in quotes]
    book = wf.book_for_series("KXHIGHNY", lambda station, kind: rows)
    ds = backtest.build_dataset(MARKETS["high_ny"], markets, candles, [], frame_series=obs, forecasts=book)
    research = {s.contract.ticker: s.features for s in ds.frames[0][1]}

    monkeypatch.setattr(freedata, "station_observations", lambda station: obs)
    seen = {}

    def forecasts(station, kind, as_of):
        seen["args"] = (station, kind, as_of)
        return rows

    src = engine.Sources(quotes=lambda m: quotes, spot=lambda m: None, forecasts=forecasts)
    snaps, _ = engine._cross_market_frame(["high_ny"], src, ts)
    live = {s.contract.ticker: s.features for s in snaps}

    assert seen["args"] == ("NYC", "max", ts)
    assert set(research) == set(live) == {t for t, _k, _r in LADDER}
    keys = ("fcst_high_f", "fcst_sd_f", "fcst_age_h", "fcst_p_yes", "fcst_edge")
    for ticker in research:
        assert {k: research[ticker][k] for k in keys} == {k: live[ticker][k] for k in keys}, ticker
    assert research["KXHIGHNY-26OCT23-T57"]["fcst_p_yes"] == 0.0  # 58F already observed: not below 57
    assert sum(f["fcst_p_yes"] for f in research.values()) == pytest.approx(1.0)


def test_a_forecast_read_failure_never_blocks_the_live_frame(monkeypatch):
    monkeypatch.setattr(freedata, "station_observations", lambda station: {})
    close = datetime(2026, 10, 24, 5, 0, tzinfo=timezone.utc)

    def boom(station, kind, as_of):
        raise RuntimeError("db down")

    src = engine.Sources(quotes=lambda m: [_quote("KXHIGHNY-26OCT23-B59.5", 59.0, 0.3, 0.34, close)],
                         spot=lambda m: None, forecasts=boom)
    snaps, _ = engine._cross_market_frame(["high_ny"], src, _ts("2026-10-23 18:00"))
    assert len(snaps) == 1 and "fcst_p_yes" not in snaps[0].features


# -- collector ---------------------------------------------------------------------

NBS_CSV = """runtime,ftime,model,tmp,txn,xnd,station
2026-10-20 00:00:00,2026-10-20 12:00:00,NBS,54,52.0,2.0,KNYC
2026-10-20 00:00:00,2026-10-20 18:00:00,NBS,65,,,KNYC
2026-10-20 00:00:00,2026-10-21 00:00:00,NBS,60,66.0,1.0,KNYC
2026-10-20 00:00:00,2026-10-21 12:00:00,NBS,50,49.0,,KNYC
"""
GFS_CSV = """runtime,ftime,model,n_x,tmp,station
2026-10-20 00:00:00,2026-10-21 00:00:00,GFS,69,62,KNYC
2026-10-20 00:00:00,2026-10-21 12:00:00,GFS,M,52,KNYC
"""


def test_parse_rows_maps_the_00z_max_and_12z_min_to_their_local_days():
    rt = datetime(2026, 10, 20, 0, 0)
    assert wfc.parse_rows(NBS_CSV, "NBS") == [
        (rt, "min", date(2026, 10, 20), 52.0, 2.0),
        (rt, "max", date(2026, 10, 20), 66.0, 1.0),   # 00Z Oct 21 column = Oct 20's daytime high
        (rt, "min", date(2026, 10, 21), 49.0, None),
    ]
    assert wfc.parse_rows(GFS_CSV, "GFS") == [(rt, "max", date(2026, 10, 20), 69.0, None)]


class _Resp:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text


class _Cur:
    def __init__(self):
        self.rows = []
        self.rowcount = 0

    def executemany(self, sql, vals):
        assert sql.startswith("INSERT IGNORE INTO weather_forecasts")
        self.rows.extend(vals)
        self.rowcount = len(vals)


def test_collect_applies_the_publication_lag_and_backs_off_on_429():
    calls = []

    def get(url, params, timeout):
        calls.append(params)
        if params["station"] == "KMDW":
            return _Resp(404)
        if len(calls) == 1:
            return _Resp(429)
        return _Resp(200, NBS_CSV if params["model"] == "NBS" else GFS_CSV)

    waits = []
    cur = _Cur()
    stats = wfc.collect(cur, ["NYC", "MDW"], datetime(2026, 10, 20), datetime(2026, 10, 21), get=get, sleep=waits.append)
    assert calls[0]["station"] == "KNYC" and calls[0]["sts"] == "2026-10-20T00:00Z"
    assert wfc.RETRY_WAITS_S[0] in waits and wfc.REQUEST_GAP_S in waits
    assert stats["requests"] == 2 and stats["inserted"] == 4 and len(stats["errors"]) == 2  # MDW failed alone
    by_model = {r[1]: r for r in cur.rows}
    assert by_model["NBS"][7] - by_model["NBS"][3] == timedelta(seconds=wfc.LAG_S["NBS"])
    assert by_model["GFS"][7] - by_model["GFS"][3] == timedelta(seconds=wfc.LAG_S["GFS"])


def test_trailing_bias_uses_only_settlements_known_by_the_frame():
    # 10 settled days, each with a morning-of NBS forecast 2F warm.
    rows, actuals = [], []
    for i in range(10):
        d = date(2026, 10, 1) + timedelta(days=i)
        start = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) + 5 * 3600  # 00:00 EST
        rows.append((start + 6 * 3600, d, "NBS", 62.0, 1.5))
        actuals.append((start + 30 * 3600, d, 60.0))       # settled value known the next morning
    target = date(2026, 10, 11)
    t_start = int(datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp()) + 5 * 3600
    rows.append((t_start + 6 * 3600, target, "NBS", 62.0, 1.5))
    book = wf.ForecastBook(rows, -5, "max", actuals)
    ts = t_start + 8 * 3600
    f = wf.contract_features(book, "KXHIGHNY-26OCT11-B59.5", 59.0, ts, 0.2, 0.3)
    assert f["fcst_bias_f"] == pytest.approx(2.0)
    assert f["fcst_p_yes_cal"] == pytest.approx(wf.p_yes(60.0, 2.0, 59, 60))  # spread widened to the 2F error
    assert f["fcst_edge_cal"] == pytest.approx(f["fcst_p_yes_cal"] - 0.25)
    # Earlier, only 6 settlements were known: too few, so no calibrated features.
    early = actuals[5][0] + 1
    rows_early = rows[:-1] + [(early - 3600, target, "NBS", 62.0, 1.5)]
    g = wf.contract_features(wf.ForecastBook(rows_early, -5, "max", actuals), "KXHIGHNY-26OCT11-B59.5", 59.0,
                             early, 0.2, 0.3)
    assert "fcst_bias_f" not in g and "fcst_p_yes" in g
