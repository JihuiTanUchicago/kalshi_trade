"""Options-implied fair value for Kalshi BTC contracts: P(BTC > K at T) off a Deribit vol surface.

Deribit's BTC options are the deepest market there is for "where will BTC be at time T", so the
probability its implied-vol surface puts on BTC finishing above a strike is the market's own fair
value for a Kalshi "above K" contract. A Kalshi price far from it is a mispricing the options
market disagrees with, or information Kalshi has first; research decides which.

A Surface is one snapshot (snap_ts) of that surface, stored compactly per Deribit expiry:

  basis    ln(forward / index) for the expiry (0 when only the index is known)
  atm_iv   annualized implied vol at the forward
  grid     implied vol at standardized moneyness z = ln(K/F) / (atm_iv * sqrt(T)), z in Z_GRID,
           flat beyond the grid ends

Two fits make one: fit_smooth for a chain of marks (Deribit's own fitted mark_iv, already
smooth: linear interpolation in log-moneyness), fit_trades for historical trades (noisy: a
recency- and size-weighted quadratic in ln(K/F)/sqrt(T), see data_pipeline/deribit_options.py).

Pricing a contract at ts with horizon T (prob_above):
  * term structure: ATM total variance linear in T between the expiries around T, flat ATM vol
    before the first (Kalshi's 15-minute and hourly contracts all expire before Deribit's next
    08:00 UTC expiry) and after the last; the basis scales the same way.
  * smile: each bracketing expiry's vol-to-ATM ratio at the contract's z, blended with the same
    weights, times the interpolated ATM vol ("sticky standardized moneyness").
  * digital: P(S_T > K) = N(d2) - F phi(d1) sqrt(T) dsigma/dK (Black-76 with the skew term; without
    it the digital is off by several cents on the wings of a skewed smile).
  * Kalshi settles on the average of CF Benchmarks' BRTI over the SETTLE_AVG_S seconds before the
    close, which has less variance than the price at the close: T counts the last window as a
    third (the variance of an average of Brownian motion), and inside the window only the part
    still to come.

Everything is numpy over arrays of (ts, strike, close_ts, spot) for one Surface, so the per-second
feature build prices a whole hour of every BTC contract quickly; single contracts pass length-1
arrays.
"""
import bisect
import math
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

YEAR_S = 365.0 * 86400.0
Z_GRID = (-4.0, -3.0, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
_ZG = np.array(Z_GRID)
GRID_COLS = tuple("iv_%s%s" % ("m" if z < 0 else "p", ("%g" % abs(z)).replace(".", "_")) for z in Z_GRID)
# Row layout of a stored surface (tick_archiver's deribit_surface table, the daily files, and the
# live surface in collector_state): one row per (snapshot, expiry).
SURFACE_FIELDS = ("snap_ts", "expiry_ts", "index_price", "basis", "atm_iv") + GRID_COLS + ("n_points", "method")
SETTLE_AVG_S = float(os.getenv("TAU_KALSHI_SETTLE_AVG_S", "60"))
MIN_EXPIRY_S = 60          # an expiry this close (or past) is not used
MAX_AGE_S = float(os.getenv("TAU_OPTIONS_MAX_AGE_S", "1800"))   # older snapshot = no fair value
IV_MIN, IV_MAX = 0.05, 5.0


@dataclass(frozen=True)
class Expiry:
    expiry_ts: int
    basis: float
    atm_iv: float
    grid: Tuple[float, ...]
    n_points: int = 0


@dataclass(frozen=True)
class Surface:
    snap_ts: int
    index_price: float
    expiries: Tuple[Expiry, ...]      # sorted by expiry_ts
    method: str = "chain"
    known_ns: int = 0                 # receive time (ns) of the data, for as-of joins; 0 = snap_ts

    def rows(self) -> List[Dict]:
        out = []
        for e in self.expiries:
            r = {"snap_ts": self.snap_ts, "expiry_ts": e.expiry_ts, "index_price": self.index_price,
                 "basis": e.basis, "atm_iv": e.atm_iv, "n_points": e.n_points, "method": self.method}
            r.update(dict(zip(GRID_COLS, e.grid)))
            out.append(r)
        return out


def surfaces_from_rows(rows: Iterable[Dict]) -> List[Surface]:
    """Group stored rows (dicts with SURFACE_FIELDS, optionally rt) into Surfaces by snapshot."""
    by: Dict[Tuple[int, str], List[Dict]] = {}
    for r in rows:
        by.setdefault((int(r["snap_ts"]), str(r.get("method") or "chain")), []).append(r)
    out = []
    for (snap, method), rs in sorted(by.items()):
        exps = []
        for r in rs:
            grid = tuple(float(r[c]) for c in GRID_COLS)
            atm = float(r["atm_iv"])
            if not (IV_MIN <= atm <= IV_MAX) or not all(IV_MIN <= g <= IV_MAX for g in grid):
                continue
            exps.append(Expiry(int(r["expiry_ts"]), float(r.get("basis") or 0.0), atm, grid, int(r.get("n_points") or 0)))
        if exps:
            rt = max(int(r.get("rt") or 0) for r in rs)
            out.append(Surface(snap, float(rs[0]["index_price"]), tuple(sorted(exps, key=lambda e: e.expiry_ts)),
                               method, rt))
    return out


# --- fits -------------------------------------------------------------------------------------

def _grid_from(fn, atm: float, t_yr: float) -> Tuple[float, ...]:
    """Vol at each Z_GRID point, given vol as a function of ln(K/F)."""
    s = atm * math.sqrt(t_yr)
    return tuple(min(max(fn(z * s), IV_MIN), IV_MAX) for z in Z_GRID)


def fit_smooth(points: Sequence[Tuple[float, float]], t_yr: float) -> Optional[Tuple[float, Tuple[float, ...]]]:
    """(atm_iv, grid) from (ln(K/F), iv) points of an already smooth curve (Deribit mark_iv):
    linear interpolation, flat beyond the outermost strikes. None with no usable point."""
    pts: Dict[float, List[float]] = {}
    for k, iv in points:
        if iv is not None and IV_MIN <= iv <= IV_MAX and math.isfinite(k):
            pts.setdefault(round(k, 9), []).append(iv)
    if not pts or t_yr <= 0:
        return None
    xs = sorted(pts)
    ys = [sum(pts[x]) / len(pts[x]) for x in xs]
    fn = lambda k: float(np.interp(k, xs, ys))  # noqa: E731
    atm = fn(0.0)
    return atm, _grid_from(fn, atm, t_yr)


def _solve(a: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """Gaussian elimination with partial pivoting; None if singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for j in range(c, n + 1):
                    m[r][j] -= f * m[c][j]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_trades(points: Sequence[Tuple[float, float, float]], t_yr: float) -> Optional[Tuple[float, Tuple[float, ...], int]]:
    """(atm_iv, grid, n) from noisy (ln(K/F), iv, weight) trade points. Weighted least squares of iv
    on u = ln(K/F)/sqrt(T): quadratic with 3+ strikes and 5+ trades, linear with 2+ strikes, else
    the weighted mean; u is clamped to the traded range, so the curve is flat past the outermost
    trade. None without a trade within one standard deviation of the forward (no ATM evidence)."""
    pts = [(k, iv, w) for k, iv, w in points
           if iv is not None and IV_MIN <= iv <= IV_MAX and w > 0 and math.isfinite(k)]
    if not pts or t_yr <= 0:
        return None
    rt = math.sqrt(t_yr)
    if not any(abs(k) <= iv * rt for k, iv, _w in pts):
        return None
    us = [k / rt for k, _iv, _w in pts]
    lo_u, hi_u = min(us), max(us)
    strikes = len({round(k, 6) for k, _iv, _w in pts})
    deg = 2 if strikes >= 3 and len(pts) >= 5 else 1 if strikes >= 2 else 0
    coef = None
    while coef is None and deg >= 0:
        n = deg + 1
        ata = [[0.0] * n for _ in range(n)]
        atb = [0.0] * n
        for u, (_k, iv, w) in zip(us, pts):
            basis = [u ** j for j in range(n)]
            for i in range(n):
                atb[i] += w * basis[i] * iv
                for j in range(n):
                    ata[i][j] += w * basis[i] * basis[j]
        coef = _solve(ata, atb)
        if coef is not None:
            vals = [sum(c * u ** j for j, c in enumerate(coef)) for u in np.linspace(lo_u, hi_u, 9)]
            if min(vals) < IV_MIN or max(vals) > IV_MAX:
                coef = None
        if coef is None:
            deg -= 1
    if coef is None:
        return None

    def fn(k: float) -> float:
        u = min(max(k / rt, lo_u), hi_u)
        return sum(c * u ** j for j, c in enumerate(coef))

    atm = min(max(fn(0.0), IV_MIN), IV_MAX)
    return atm, _grid_from(fn, atm, t_yr), len(pts)


# --- pricing ----------------------------------------------------------------------------------

def _ncdf(x):
    """Standard normal CDF, vectorized (Abramowitz-Stegun 7.1.26 erf, |error| < 1.5e-7)."""
    z = np.asarray(x, dtype=float) / math.sqrt(2.0)
    s = np.sign(z)
    z = np.abs(z)
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    return 0.5 * (1.0 + s * (1.0 - poly * np.exp(-z * z)))


def _npdf(x):
    return np.exp(-0.5 * np.asarray(x, dtype=float) ** 2) / math.sqrt(2.0 * math.pi)


def effective_secs(secs_left):
    """Seconds of price variance left in a Kalshi settlement averaged over the last SETTLE_AVG_S:
    tau - 2A/3 before the window, tau^3 / (3 A^2) inside it (continuous at tau = A)."""
    tau = np.maximum(np.asarray(secs_left, dtype=float), 0.0)
    a = SETTLE_AVG_S
    if a <= 0:
        return tau
    return np.where(tau >= a, tau - 2.0 * a / 3.0, tau ** 3 / (3.0 * a * a))


def _grid_interp(grid: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Row-wise linear interpolation of grid[i, :] (vols at Z_GRID) at z[i], flat outside."""
    idx = np.clip(np.searchsorted(_ZG, z), 1, len(_ZG) - 1)
    z0, z1 = _ZG[idx - 1], _ZG[idx]
    w = np.clip((z - z0) / (z1 - z0), 0.0, 1.0)
    r = np.arange(len(z))
    return grid[r, idx - 1] * (1.0 - w) + grid[r, idx] * w


def price(surface: Surface, ts, strike, close_ts, spot) -> Tuple[np.ndarray, np.ndarray]:
    """(P(settle > strike), implied vol at the strike and horizon) for arrays of contracts priced
    off ``surface`` at times ``ts`` with BTC at ``spot``. NaN where undefined (no expiry left,
    contract closed, bad input)."""
    ts = np.atleast_1d(np.asarray(ts, dtype=float))
    n = len(ts)
    k_ = np.broadcast_to(np.asarray(strike, dtype=float), (n,))
    cl = np.broadcast_to(np.asarray(close_ts, dtype=float), (n,))
    sp = np.broadcast_to(np.asarray(spot, dtype=float), (n,))
    nan = np.full(n, np.nan)
    exps = surface.expiries
    if not exps or n == 0:
        return nan, nan.copy()
    e_ts = np.array([e.expiry_ts for e in exps], dtype=float)
    e_b = np.array([e.basis for e in exps])
    e_atm = np.array([e.atm_iv for e in exps])
    e_grid = np.array([e.grid for e in exps]) / e_atm[:, None]       # smile as a ratio to ATM
    m = len(exps)
    t_s = effective_secs(cl - ts)
    t = t_s / YEAR_S
    j0 = np.searchsorted(e_ts, ts + MIN_EXPIRY_S, side="right")       # first usable expiry
    i = np.maximum(np.searchsorted(e_ts, ts + t_s, side="left"), j0)
    ok = (j0 < m) & (t > 0) & (k_ > 0) & (sp > 0) & np.isfinite(sp) & np.isfinite(k_)
    single = (i == j0) | (i >= m)
    lo = np.where(i >= m, m - 1, np.where(single, j0, i - 1))
    hi = np.where(i >= m, m - 1, np.where(single, j0, i))
    lo, hi = np.clip(lo, 0, m - 1), np.clip(hi, 0, m - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        t0 = (e_ts[lo] - ts) / YEAR_S
        t1 = (e_ts[hi] - ts) / YEAR_S
        a = np.where(single, 0.0, (t - t0) / np.where(t1 > t0, t1 - t0, 1.0))
        w_atm = np.where(single, e_atm[lo] ** 2 * t, (1 - a) * e_atm[lo] ** 2 * t0 + a * e_atm[hi] ** 2 * t1)
        basis = np.where(single, e_b[lo] * t / np.where(t0 > 0, t0, 1.0), (1 - a) * e_b[lo] + a * e_b[hi])
        s_atm = np.sqrt(np.maximum(w_atm, 0.0) / t)
        fwd = sp * np.exp(basis)
        rt = np.sqrt(t)

        def vol(k):
            z = np.log(k / fwd) / (s_atm * rt)
            z = np.where(np.isfinite(z), z, 0.0)
            ratio = (1 - a) * _grid_interp(e_grid[lo], z) + a * _grid_interp(e_grid[hi], z)
            return s_atm * ratio

        sig = vol(k_)
        h = 1e-3
        dsig_dk = (vol(k_ * (1 + h)) - vol(k_ * (1 - h))) / (2 * h * k_)
        sd = sig * rt
        d1 = (np.log(fwd / k_) + 0.5 * sd ** 2) / sd
        d2 = d1 - sd
        p = _ncdf(d2) - fwd * _npdf(d1) * rt * dsig_dk
    p = np.where(ok & np.isfinite(p), np.clip(p, 0.0, 1.0), np.nan)
    sig = np.where(ok & np.isfinite(sig), sig, np.nan)
    return p, sig


def prob_yes(surface: Surface, ts, lo, hi, close_ts, spot) -> Tuple[np.ndarray, np.ndarray]:
    """(P(YES), implied vol) for Kalshi strike contracts: floor only ("above lo"), cap only
    ("below hi"), or a range (lo to hi). lo/hi NaN or None = no such edge. The vol is at the floor
    (the cap for cap-only contracts)."""
    ts = np.atleast_1d(np.asarray(ts, dtype=float))
    n = len(ts)
    lo_a = np.broadcast_to(np.asarray(np.nan if lo is None else lo, dtype=float), (n,))
    hi_a = np.broadcast_to(np.asarray(np.nan if hi is None else hi, dtype=float), (n,))
    has_lo, has_hi = np.isfinite(lo_a) & (lo_a > 0), np.isfinite(hi_a) & (hi_a > 0)
    p_lo, v_lo = price(surface, ts, np.where(has_lo, lo_a, 1.0), close_ts, spot)
    p_hi, v_hi = price(surface, ts, np.where(has_hi, hi_a, 1.0), close_ts, spot)
    p = np.where(has_lo & has_hi, np.clip(p_lo - p_hi, 0.0, 1.0),
                 np.where(has_lo, p_lo, np.where(has_hi, 1.0 - p_hi, np.nan)))
    v = np.where(has_lo, v_lo, np.where(has_hi, v_hi, np.nan))
    return p, v


class SurfaceSeries:
    """Snapshots in time order, for as-of lookups: at(ts) is the newest surface known by ts
    (receive time before ts) and younger than MAX_AGE_S."""

    def __init__(self, surfaces: Iterable[Surface]):
        ss = sorted(surfaces, key=lambda s: (s.known_ns or s.snap_ts * 1_000_000_000))
        self.surfaces = ss
        self.known = [s.known_ns or s.snap_ts * 1_000_000_000 for s in ss]

    def __len__(self) -> int:
        return len(self.surfaces)

    def index_at(self, ts: float) -> int:
        """Index of the surface for ts, or -1."""
        i = bisect.bisect_left(self.known, int(ts * 1_000_000_000)) - 1
        if i < 0 or ts - self.surfaces[i].snap_ts > MAX_AGE_S:
            return -1
        return i

    def at(self, ts: float) -> Optional[Surface]:
        i = self.index_at(ts)
        return self.surfaces[i] if i >= 0 else None

    def indexes(self, secs: np.ndarray) -> np.ndarray:
        """index_at for an array of seconds."""
        known = np.asarray(self.known, dtype=np.int64)
        snap = np.array([s.snap_ts for s in self.surfaces], dtype=float)
        if not len(known):
            return np.full(len(secs), -1)
        i = np.searchsorted(known, np.asarray(secs, dtype=np.int64) * 1_000_000_000, side="left") - 1
        stale = (i < 0) | (np.asarray(secs, dtype=float) - snap[np.clip(i, 0, None)] > MAX_AGE_S)
        return np.where(stale, -1, i)
