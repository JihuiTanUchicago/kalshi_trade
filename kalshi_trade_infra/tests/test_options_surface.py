"""Options-implied pricing: Black-76 digital with skew, term structure, settlement averaging, fits."""
import math
import random
from statistics import NormalDist

import numpy as np
import pytest

from data_pipeline import options_surface as osf

N = NormalDist().cdf
T0 = 1_800_000_000
SPOT = 100_000.0


def _surface(atm=0.5, slope=0.0, days=1.0, snap=T0, basis=0.0, known_ns=0):
    grid = tuple(atm + slope * z for z in osf.Z_GRID)
    return osf.Surface(snap, SPOT, (osf.Expiry(snap + int(days * 86400), basis, atm, grid),), "chain", known_ns)


def _black_call(f, k, sig, t):
    sd = sig * math.sqrt(t)
    d1 = (math.log(f / k) + sd * sd / 2) / sd
    return f * N(d1) - k * N(d1 - sd)


def test_flat_smile_is_black_digital_with_the_settlement_average():
    close = T0 + 3600
    p, iv = osf.price(_surface(), T0, 101_000, close, SPOT)
    t = (3600 - 40) / osf.YEAR_S              # the last 60s average counts as a third
    sd = 0.5 * math.sqrt(t)
    assert p[0] == pytest.approx(N((math.log(SPOT / 101_000) - sd * sd / 2) / sd), abs=1e-6)
    assert iv[0] == pytest.approx(0.5)


def test_skewed_digital_is_minus_the_call_price_slope():
    s = _surface(slope=-0.04)                 # put skew: lower strikes, higher vol
    close = T0 + 6 * 3600
    t = osf.effective_secs(6 * 3600) / osf.YEAR_S
    for k in (97_000.0, 100_000.0, 103_000.0):
        h = k * 1e-4
        (p,), _ = osf.price(s, T0, k, close, SPOT)
        _, (v_up,) = osf.price(s, T0, k + h, close, SPOT)
        _, (v_dn,) = osf.price(s, T0, k - h, close, SPOT)
        slope = (_black_call(SPOT, k + h, v_up, t) - _black_call(SPOT, k - h, v_dn, t)) / (2 * h)
        assert p == pytest.approx(-slope, abs=2e-4)
    (p_atm,), _ = osf.price(s, T0, SPOT, close, SPOT)
    assert p_atm > 0.5                        # put skew makes "above spot" worth more than N(d2)


def test_probabilities_fall_with_the_strike_and_ranges_add_up():
    s = _surface(slope=-0.03)
    close = T0 + 3600
    ks = np.linspace(95_000, 105_000, 101)
    p, _ = osf.price(s, np.full(len(ks), T0), ks, close, SPOT)
    assert np.all(np.diff(p) <= 1e-9) and p[0] > 0.99 and p[-1] < 0.01
    (pr,), _ = osf.prob_yes(s, T0, 99_500, 100_500, close, SPOT)
    (a,), _ = osf.price(s, T0, 99_500, close, SPOT)
    (b,), _ = osf.price(s, T0, 100_500, close, SPOT)
    assert pr == pytest.approx(a - b)
    (cap,), _ = osf.prob_yes(s, T0, None, 100_500, close, SPOT)
    assert cap == pytest.approx(1 - b)


def test_total_variance_interpolates_between_expiries_and_vol_is_flat_before_the_first():
    e1 = osf.Expiry(T0 + 86400, 0.0, 0.40, tuple([0.40] * len(osf.Z_GRID)))
    e2 = osf.Expiry(T0 + 3 * 86400, 0.0, 0.60, tuple([0.60] * len(osf.Z_GRID)))
    s = osf.Surface(T0, SPOT, (e1, e2))
    _, (iv_short,) = osf.price(s, T0, SPOT, T0 + 3600, SPOT)
    assert iv_short == pytest.approx(0.40)
    close = T0 + 2 * 86400 + 40              # effective horizon exactly 2 days
    _, (iv_mid,) = osf.price(s, T0, SPOT, close, SPOT)
    w = 0.5 * 0.40 ** 2 * 1 + 0.5 * 0.60 ** 2 * 3
    assert iv_mid == pytest.approx(math.sqrt(w / 2), rel=1e-9)
    _, (iv_far,) = osf.price(s, T0, SPOT, T0 + 30 * 86400, SPOT)
    assert iv_far == pytest.approx(0.60)


def test_expired_or_past_close_is_undefined():
    s = _surface(days=1)
    p, iv = osf.price(s, T0 + 86400, SPOT, T0 + 90000, SPOT)     # the only expiry has passed
    assert np.isnan(p[0]) and np.isnan(iv[0])
    p, _ = osf.price(s, T0, SPOT, T0 - 1, SPOT)
    assert np.isnan(p[0])


def test_settlement_average_shrinks_variance_continuously():
    eff = osf.effective_secs([0, 30, 59.999, 60, 600])
    assert eff[0] == 0 and eff[1] == pytest.approx(30 ** 3 / (3 * 3600))
    assert eff[2] == pytest.approx(20, abs=1e-3) and eff[3] == pytest.approx(20) and eff[4] == pytest.approx(560)


def test_basis_moves_the_forward():
    (p0,), _ = osf.price(_surface(basis=0.0), T0, SPOT, T0 + 86400 + 40, SPOT)
    (p1,), _ = osf.price(_surface(basis=0.01, days=1), T0, SPOT, T0 + 86400 + 40, SPOT)
    assert p1 > p0 + 0.02


def test_fit_smooth_recovers_the_curve_and_its_atm():
    t = 2 / 365
    pts = [(k, 0.5 - 0.5 * k) for k in np.linspace(-0.1, 0.1, 21)]
    atm, grid = osf.fit_smooth(pts, t)
    assert atm == pytest.approx(0.5)
    s = 0.5 * math.sqrt(t)
    for z, g in zip(osf.Z_GRID, grid):
        k = min(max(z * s, -0.1), 0.1)
        assert g == pytest.approx(0.5 - 0.5 * k, abs=1e-9)
    assert osf.fit_smooth([], t) is None and osf.fit_smooth([(0.0, -1.0)], t) is None


def test_fit_trades_recovers_a_noisy_smile_and_needs_atm_evidence():
    rng = random.Random(7)
    t = 1 / 365
    rt = math.sqrt(t)
    true = lambda u: 0.45 - 0.2 * u + 0.6 * u * u    # noqa: E731
    pts = []
    for _ in range(200):
        u = rng.uniform(-0.12, 0.12)
        pts.append((u * rt, true(u) + rng.gauss(0, 0.01), rng.uniform(0.1, 2.0)))
    atm, grid, n = osf.fit_trades(pts, t)
    assert n == 200 and atm == pytest.approx(0.45, abs=0.005)
    for z, g in zip(osf.Z_GRID, grid):
        u = min(max(z * atm, -0.12), 0.12)
        assert g == pytest.approx(true(u), abs=0.01)
    far = [(2.0 * rt, 0.6, 1.0), (2.5 * rt, 0.62, 1.0)]       # only deep wings traded
    assert osf.fit_trades(far, t) is None
    one = osf.fit_trades([(0.0, 0.5, 1.0)], t)                 # a single strike: flat
    assert one[0] == pytest.approx(0.5) and set(one[1]) == {0.5}


def test_rows_round_trip_and_bad_vols_are_dropped():
    s = _surface(slope=-0.01)
    rows = s.rows()
    assert set(rows[0]) == set(osf.SURFACE_FIELDS)
    back = osf.surfaces_from_rows(rows)
    assert back[0].expiries == s.expiries and back[0].snap_ts == T0
    bad = dict(rows[0], atm_iv=0.0)
    assert osf.surfaces_from_rows([bad]) == []


def test_series_is_as_of_receive_time_and_ages_out():
    a = _surface(snap=T0, known_ns=(T0 + 2) * 10 ** 9)
    b = _surface(snap=T0 + 60, atm=0.6, known_ns=(T0 + 62) * 10 ** 9)
    ser = osf.SurfaceSeries([b, a])
    assert ser.at(T0 + 1) is None                      # snapped at T0 but received at T0+2
    assert ser.at(T0 + 2) is a and ser.at(T0 + 61) is a and ser.at(T0 + 62) is b   # known at ts counts
    assert ser.at(T0 + 60 + osf.MAX_AGE_S + 1) is None
    idx = ser.indexes(np.array([T0 + 1, T0 + 2, T0 + 61, T0 + 62, T0 + 60 + int(osf.MAX_AGE_S) + 1]))
    assert list(idx) == [-1, 0, 0, 1, -1]
