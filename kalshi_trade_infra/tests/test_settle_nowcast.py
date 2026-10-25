"""Final-seconds settlement nowcast (data_pipeline/settle_nowcast.py)."""
import math
from datetime import datetime, timezone

import numpy as np
import pyarrow as pa
import pytest

from data_pipeline import settle_nowcast as sn


def test_window_variance_matches_a_simulated_random_walk():
    rng = np.random.default_rng(1)
    for tau in (90, 60, 30, 10, 1):
        steps = rng.normal(0, 2.0, size=(20000, tau))
        path = 100.0 + np.cumsum(steps, axis=1)       # index at the next tau seconds
        k = min(tau, 60)
        avg = (path[:, -k:].sum(axis=1) + (60 - k) * 100.0) / 60
        mean, sd = sn.window_moments((60 - k) * 100.0, 60 - k, 100.0, 2.0, tau)
        assert mean == pytest.approx(100.0)
        assert sd == pytest.approx(avg.std(), rel=0.03)


def test_inside_the_window_uncertainty_falls_much_faster_than_spot():
    _, sd60 = sn.window_moments(0, 0, 100.0, 2.0, 60)
    _, sd15 = sn.window_moments(45 * 100.0, 45, 100.0, 2.0, 15)
    assert sd15 / sd60 < 0.2                      # spot-style sqrt(tau) would say 0.5
    assert sn.window_moments(60 * 100.0, 60, 99.0, 2.0, 0, proxy_sd=4.0) == (100.0, 4.0)


def test_strike_types():
    assert sn.p_yes(100, 1e-9, "greater", 99, None) == pytest.approx(1.0)
    assert sn.p_yes(100, 10, "between", 90, 110) == pytest.approx(0.6827, abs=1e-3)
    assert sn.p_yes(100, 10, "less", None, 100) == pytest.approx(0.5)
    assert sn.settles_yes(100.0, "greater_or_equal", 100.0, None) and not sn.settles_yes(100.0, "greater", 100.0, None)
    with pytest.raises(ValueError):
        sn.p_yes(1, 1, "weird", 1, 1)


def test_vectorised_rows_match_the_scalar_formula():
    sec = np.arange(1000, 3001)
    x = 50_000 + np.cumsum(np.random.default_rng(3).normal(0, 2.0, len(sec)))
    close = 3000
    taus = np.array([120, 60, 30, 5, 0])
    mean, sd = sn.nowcast_rows(close - taus, np.full(len(taus), close), sec, x, proxy_sd=3.0)
    sig = sn.sigma_per_s(sec, x)
    for t, m, d in zip(taus, mean, sd):
        i = close - t - 1000
        n_obs = 60 - t if t < 60 else 0
        obs = x[(sec > close - 60) & (sec <= close - t)].sum() if n_obs else 0.0
        em, ed = sn.window_moments(obs, n_obs, x[i], sig[i], int(t), proxy_sd=3.0)
        assert m == pytest.approx(em) and d == pytest.approx(ed)
    p = sn.p_yes_rows(mean, sd, np.full(5, x[-1]), np.full(5, np.nan))
    assert p[-1] == pytest.approx(sn.p_yes(mean[-1], sd[-1], "greater", x[-1], None))
    # before the index has enough history to know its volatility: NaN, not a guess
    m2, _ = sn.nowcast_rows(np.array([1010]), np.array([1050]), sec, x)
    assert np.isnan(m2[0])


def test_chain_settlements_use_the_next_contracts_strike():
    meta = {"A": {"ticker": "A", "series": "KXBTC15M", "open_ts": 900, "close_ts": 1800, "floor_strike": 10.0},
            "B": {"ticker": "B", "series": "KXBTC15M", "open_ts": 1800, "close_ts": 2700, "floor_strike": 12.5},
            "D": {"ticker": "D", "series": "KXBTCD", "open_ts": 0, "close_ts": 1800, "floor_strike": 11.99}}
    assert sn.chain_settlements(meta) == {900: 10.0, 1800: 12.5}


class FakeStore:
    """Two back-to-back 15m contracts; the book quotes a spot-style fair value that ignores the
    averaging, so in the last seconds it is wrong whenever spot jumps after most of the window."""

    def __init__(self):
        self.t0 = int(datetime(2026, 10, 24, 22, tzinfo=timezone.utc).timestamp())
        n = 3000
        self.sec = np.arange(self.t0 - 1200, self.t0 - 1200 + n)
        x = np.full(n, 80_000.0) + np.cumsum(np.random.default_rng(5).normal(0, 1.0, n))
        c1 = self.t0 + 900
        x[self.sec > c1 - 10] += 15.0           # a late jump: spot moves $15, the average only ~$2.5
        self.x = x
        self.c1 = c1

    def _avg(self, close):
        w = (self.sec > close - 60) & (self.sec <= close)
        return float(self.x[w].mean())

    def read(self, table, start, end, columns=None, **_):
        rows = [dict(rt=1, ticker="K1", series="KXBTC15M", open_ts=self.t0, close_ts=self.c1,
                     floor_strike=self._avg(self.t0), cap_strike=None, strike_type="greater_or_equal"),
                dict(rt=1, ticker="K2", series="KXBTC15M", open_ts=self.c1, close_ts=self.c1 + 900,
                     floor_strike=self._avg(self.c1), cap_strike=None, strike_type="greater_or_equal")]
        return pa.Table.from_pylist(rows)

    def composite_1s(self, start, end):
        return {"sec": self.sec, "spot_comp": self.x}

    def features_1s(self, start, end, tickers=None, columns=None):
        secs = np.arange(self.c1 - 300, self.c1 + 1)
        k1 = self._avg(self.t0)
        out = {"sec": [], "ticker": [], "yes_bid": [], "yes_ask": [], "yes_bid_size": [], "yes_ask_size": [], "book_age_s": []}
        for s in secs:
            spot = float(self.x[s - self.sec[0]])
            tau = max(self.c1 - s, 1)
            fair = 0.5 * (1 + math.erf((spot - k1) / (1.0 * math.sqrt(tau)) / math.sqrt(2)))
            mid = min(max(round(fair, 2), 0.02), 0.98)
            for k, v in (("sec", s), ("ticker", "K1"), ("yes_bid", mid - 0.01), ("yes_ask", mid + 0.01),
                         ("yes_bid_size", 100.0), ("yes_ask_size", 100.0), ("book_age_s", 1.0)):
                out[k].append(v)
        return {k: np.array(v) for k, v in out.items()}


def test_evaluate_scores_against_the_official_chain_and_trades_net_of_fees():
    st = FakeStore()
    start = datetime.fromtimestamp(st.c1 - 1, timezone.utc)
    end = datetime.fromtimestamp(st.c1 + 1, timezone.utc)
    rep = sn.evaluate(st, start, end, series=["KXBTC15M"], proxy_sd=0.5)
    assert rep["contracts"] == 1
    assert len(rep["proxy_errors"]) == 2 and all(abs(e) < 1e-6 for _, e in rep["proxy_errors"])
    taus = {r["tau"]: r for r in rep["rows"]}
    assert taus[1]["settle"] == pytest.approx(st._avg(st.c1))
    for t in rep["trades"]:
        assert t["fee"] >= 0 and t["pnl"] == pytest.approx((1.0 if (t["side"] == "yes") == bool(taus[1]["yes"]) else 0.0) - t["px"] - t["fee"])
    assert set(rep["calibration"]) >= {"1", "60"}
