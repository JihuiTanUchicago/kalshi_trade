"""Research datasets replayed from the per-second tick archive (app/tick_dataset.py)."""
import math

import numpy as np
import pytest

from app import backtest, spec as specmod, tick_dataset
from app.markets import MARKETS

M = MARKETS["btc15m_tick"]
T0 = M.data_from_ts            # 2026-10-24 20:00Z


def _ticker(k):
    return "KXBTC15M-26OCT24T%02d" % k


def _frame(n=1800, k_contracts=2, stale_at=None, walk=False):
    """Consecutive 15-minute contracts, one row per open second (sec = end of the second)."""
    rng = np.random.default_rng(7)
    spot = 100_100.0 * np.exp(np.cumsum(rng.normal(0, 2e-4, n + 1))) if walk else np.full(n + 1, 100_100.0)
    cols = {c: [] for c in tick_dataset.COLUMNS}
    for k in range(k_contracts):
        open_ts, close_ts = T0 + 900 * k, T0 + 900 * (k + 1)
        for sec in range(open_ts + 1, min(close_ts, T0 + n) + 1):
            row = dict(sec=sec, ticker=_ticker(k), close_ts=close_ts, strike_lo=100_000.0, strike_hi=np.nan,
                       yes_bid=0.40, yes_ask=0.43, secs_to_close=float(close_ts - sec), dist_sigma=0.5,
                       spot_stale=False, spot=spot[sec - T0], spot_comp=spot[sec - T0], spot_ret_1s=0.0, spot_ret_10s=0.0001,
                       spot_ret_60s=0.0002, spot_ret_300s=0.0003, rv_60s=1e-4, rv_300s=1e-4,
                       spot_taker_imb_60s=0.1, yes_bid_size=50.0, yes_ask_size=20.0, imbalance=0.43,
                       microprice=0.421, bid_depth=80.0, ask_depth=40.0, updates=3.0,
                       book_age_s=999.0 if sec == stale_at else 1.0, n_prints_60s=4.0,
                       yes_taker_60s=30.0, no_taker_60s=10.0, yes_taker_10s=0.0, no_taker_10s=0.0,
                       opt_p_yes=0.47 if k == 0 else np.nan, opt_iv=0.45 if k == 0 else np.nan,
                       pm_p_yes=0.48 if k == 0 else np.nan, pm_spread=0.01 if k == 0 else np.nan,
                       pm_age_s=2.0 if k == 0 else np.nan)
            for c in cols:
                cols[c].append(row[c])
    out = {c: np.array(v) for c, v in cols.items()}
    out["sec"] = out["sec"].astype(np.int64)
    return out


def _contracts(k):
    return [{"ticker": _ticker(i), "open_ts": T0 + 900 * i, "close_ts": T0 + 900 * (i + 1),
             "result": "yes" if i % 2 == 0 else "no"} for i in range(k)]


CONTRACTS = _contracts(2)


def test_frames_follow_the_cadence_and_carry_candle_compatible_features():
    ds = tick_dataset.load_window(M, CONTRACTS, T0, T0 + 1800, read=lambda s, e, **k: _frame())
    assert M.decision_seconds == 5
    assert all(ts % 5 == 0 for ts, _ in ds.frames)
    assert ds.contracts == 2 and ds.results == {c["ticker"]: c["result"] for c in CONTRACTS}
    ts, snaps = ds.frames[0]
    s = snaps[0]
    assert ts == T0 + 5 and s.contract.strike == 100_000.0 and s.contract.series == "KXBTC15M"
    f = s.features
    assert f["moneyness"] == pytest.approx(math.log(100_100 / 100_000))
    assert f["z_score_5m"] == 0.5 and f["tte_min"] == pytest.approx((900 - 5) / 60)
    assert f["ret_1m"] == pytest.approx(0.0002) and f["ret_5m"] == pytest.approx(0.0003)
    assert f["opt_p_yes"] == pytest.approx(0.47) and f["opt_iv"] == pytest.approx(0.45)
    assert f["opt_edge"] == pytest.approx(0.47 - 0.415)
    assert f["pm_edge"] == pytest.approx(0.48 - 0.415) and f["pm_age_s"] == 2.0
    assert "pm_edge" not in ds.frames[-1][1][-1].features
    assert "opt_p_yes" not in ds.frames[-1][1][-1].features and "opt_edge" not in ds.frames[-1][1][-1].features
    assert f["ob_imbalance"] == pytest.approx(0.43) and f["flow_imb_60s"] == pytest.approx(0.5)
    assert "flow_imb_10s" not in f                       # no trades in 10s: absent, never 0
    assert "vol_60m" not in f and "z_score" not in f     # minute vols need an hour of data first
    assert set(tick_dataset.TICK_FEATURES) & set(f) >= {"rv_300s", "microprice", "book_age_s"}
    # every feature a spec could filter on is a known feature
    assert set(f) <= set(specmod.FEATURES)


def test_stale_books_and_contracts_outside_the_window_are_dropped():
    stale = T0 + 50
    ds = tick_dataset.load_window(M, CONTRACTS, T0, T0 + 900, read=lambda s, e, **k: _frame(stale_at=stale))
    assert ds.contracts == 1 and set(ds.results) == {CONTRACTS[0]["ticker"]}
    assert stale not in [ts for ts, _ in ds.frames]
    with pytest.raises(ValueError, match="per-second data"):
        tick_dataset.load_window(M, [dict(CONTRACTS[0], open_ts=T0 - 900)], T0 - 900, T0,
                                 read=lambda s, e, **k: _frame())


def test_minute_vols_are_rebuilt_from_per_second_spot_like_the_candle_path():
    from app.markets import BtcSeries
    n = 4500
    frame = _frame(n=n, k_contracts=5, walk=True)
    ds = tick_dataset.load_window(M, _contracts(5), T0, T0 + n, read=lambda s, e, **k: frame)
    late = [sn for ts, snaps in ds.frames if ts >= T0 + 3720 for sn in snaps]
    assert late and all("vol_60m" in sn.features and "z_score" in sn.features for sn in late)
    sn = late[0]
    sec, spot = frame["sec"], frame["spot"]
    closes = [(t - 60, float(spot[sec == t][0])) for t in range(T0 + 60, sn.ts + 1, 60)]
    want = BtcSeries(closes).features_at(sn.ts)
    assert sn.features["vol_60m"] == pytest.approx(want["vol_60m"])
    assert sn.features["ret_15m"] == pytest.approx(want["ret_15m"])
    assert sn.features["z_score"] == pytest.approx(
        sn.features["moneyness"] / (want["vol_60m"] * math.sqrt(sn.features["tte_min"])))


def test_a_spec_backtests_on_tick_frames_and_fills_on_the_next_decision():
    n = 4500
    ds = tick_dataset.load_window(M, _contracts(5), T0, T0 + n, read=lambda s, e, **k: _frame(n=n, k_contracts=5, walk=True))
    spec = specmod.validate({"side": "either", "entry": {"min_edge": 0.01, "max_spread": 0.05},
                             "sizing": {"stake": 10.0, "max_positions": 1}})
    trades = backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1)
    assert trades
    first_signal = min(ts for ts, snaps in ds.frames if specmod.entries(spec, snaps))
    assert trades[0].entry_ts == first_signal + M.decision_seconds   # filled at the next decision


def test_the_per_second_twin_waits_for_enough_archive():
    from app import agent
    assert "of the 3 days" in M.tick_history_short(now_ts=T0 + 3600)
    assert M.tick_history_short(now_ts=T0 + 3 * 86400) is None
    assert MARKETS["btc15m"].tick_history_short(now_ts=T0) is None      # candle markets never wait
    if M.tick_history_short():                                          # before 2026-10-27 20:00Z
        assert agent.research_unavailable_reason("btc15m_tick") == M.tick_history_short()


def test_rows_in_the_last_minute_carry_the_settlement_nowcast():
    ds = tick_dataset.load_window(M, CONTRACTS, T0, T0 + 1800, read=lambda s, e, **k: _frame(walk=True))
    last = [s for ts, snaps in ds.frames for s in snaps if s.contract.ticker == _ticker(1) and ts > T0 + 1800 - 60]
    assert last
    f = last[-1].features
    assert 0.0 <= f["p_settle"] <= 1.0 and f["settle_sd"] > 0
    assert set(f) <= set(specmod.FEATURES)
    # A flat composite: the average is the spot, the only uncertainty is the proxy's error.
    flat = tick_dataset.load_window(M, CONTRACTS, T0, T0 + 1800, read=lambda s, e, **k: _frame())
    g = [s for ts, snaps in flat.frames for s in snaps if s.contract.ticker == _ticker(1)][-1].features
    assert g["settle_sd"] == pytest.approx(4.0) and g["p_settle"] == pytest.approx(1.0)   # $100 above, sd $4
