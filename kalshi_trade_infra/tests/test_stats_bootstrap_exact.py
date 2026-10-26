"""The stationary bootstrap's fast path must draw exactly what the loop it replaced drew.

stats.stationary_bootstrap_ci is the gatekeeper's primary validation p-value and the paper -> live
edge test (agent.paper_evidence). It read ~3 numpy calls per resampled point (~1.3s for an 800-event
paper record, on the Deploy board's request path); it now reads the same PCG64 words in bulk. These
tests hold it, bit for bit, to the original loop (kept below as the reference) and to numpy's own
Generator draws, including Lemire's rejection branch, which natural draws at small n almost never hit.
"""
import time

import numpy as np
import pytest

from app import agent, stats

M32 = 0xFFFFFFFF


def reference_ci(x, stat="mean", n_boot=2000, avg_block=0.0, alpha=0.10, seed=0):
    """stationary_bootstrap_ci as it was before the fast path (2026-10-26), verbatim."""
    arr = np.asarray(x, dtype=float)
    n = len(arr)
    ab = avg_block if avg_block and avg_block >= 2.0 else stats._politis_white_avg_block(arr) if n >= 2 else 2.0
    degenerate = stats._degenerate_result(arr, stat, n_boot, ab)
    if degenerate is not None:
        return degenerate
    p = 1.0 / ab
    rng = np.random.default_rng(seed)
    boot = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = np.empty(n, dtype=np.int64)
        i = int(rng.integers(0, n))
        idx[0] = i
        for t in range(1, n):
            if rng.random() < p:
                i = int(rng.integers(0, n))
            else:
                i = (i + 1) % n
            idx[t] = i
        boot[b] = stats._stat_value(arr[idx], stat)
    return stats._ci_result(boot, stats._stat_value(arr, stat), alpha, n_boot, ab)


def _same(a, b):
    assert a.keys() == b.keys()
    for k in a:
        assert a[k] == b[k] or (a[k] != a[k] and b[k] != b[k]), (k, a[k], b[k])  # NaN == NaN here


@pytest.mark.parametrize("n", [2, 3, 5, 21, 64, 301])
@pytest.mark.parametrize("stat", ["mean", "sharpe"])
def test_the_fast_bootstrap_matches_the_loop_bit_for_bit(n, stat):
    g = np.random.default_rng(n)
    for seed in (0, 1, 12345):
        x = list(g.normal(0.01, 1.0, n))
        for avg_block in (0.0, 2.0, 7.5):
            _same(stats.stationary_bootstrap_ci(x, stat, 200, avg_block, 0.10, seed),
                  reference_ci(x, stat, 200, avg_block, 0.10, seed))


def test_the_degenerate_cases_are_unchanged():
    for x in ([], [1.5], [3.0, 3.0, 3.0]):
        _same(stats.stationary_bootstrap_ci(x), reference_ci(x))


class _Words:
    """numpy's Generator(PCG64).random() / .integers(0, n), written out over raw 64-bit words: the
    plain statement of what the fast path inlines (checked against numpy below)."""

    def __init__(self, bg):
        self.bg, self.w, self.has, self.half = bg, [], False, 0

    def word(self):
        if not self.w:
            self.w = list(self.bg.random_raw(64).tolist())[::-1]
        return self.w.pop()

    def random(self):
        return (self.word() >> 11) * (1.0 / 9007199254740992.0)

    def u32(self):
        if self.has:
            self.has = False
            return self.half
        x = self.word()
        self.has, self.half = True, x >> 32
        return x & M32

    def integers(self, n):
        m = self.u32() * n
        thr = ((M32 + 1) - n) % n
        while (m & M32) < thr:
            m = self.u32() * n
        return m >> 32


def test_the_written_out_draws_are_numpys_own_including_rejections():
    # n = 2**31 + 1 and 3 * 2**30 reject about half and a quarter of their draws.
    pick = np.random.default_rng(5)
    for seed in range(6):
        rng, words = np.random.default_rng(seed), _Words(np.random.PCG64(seed))
        for _ in range(4000):
            if pick.random() < 0.5:
                assert rng.random() == words.random()
            else:
                n = int(pick.choice([2, 3, 7, 440, 2 ** 31 + 1, 3 * 2 ** 30, 2 ** 32 - 5]))
                assert int(rng.integers(0, n)) == words.integers(n)


class _Crafted:
    """A bit generator that hands out set words: zeros (a 0.0 double starts a block, and a zero half
    is rejected by Lemire at n=3 and n=5) mixed into ordinary ones, so the rejection branch runs."""

    def __init__(self, seed):
        g = np.random.default_rng(seed)
        self.w = g.integers(0, 2 ** 64, size=200_000, dtype=np.uint64)
        self.w[g.random(self.w.size) < 0.3] = 0
        self.at = 0

    def random_raw(self, size):  # the same stream however it is fetched
        self.at += size
        return self.w[self.at - size:self.at]


@pytest.mark.parametrize("n", [3, 5])
@pytest.mark.parametrize("chunk", [1 << 16, 1])  # 1: refetch every few words, mid-rejection too
def test_the_fast_rows_take_the_rejection_branch_exactly(n, chunk, monkeypatch):
    monkeypatch.setattr(stats, "_RAW_CHUNK", chunk)
    rows = list(stats._pcg64_stationary_rows(_Crafted(n), n, 0.5, 400))
    words = _Words(_Crafted(n))
    want = []
    for _ in range(400):
        i = words.integers(n)
        row = [i]
        for _t in range(1, n):
            i = words.integers(n) if words.random() < 0.5 else (i + 1) % n
            row.append(i)
        want.append(row)
    assert rows == want


def test_the_fast_bootstrap_is_several_times_faster_than_the_loop():
    x = list(np.random.default_rng(3).normal(0.02, 1.0, 300))
    t = time.perf_counter()
    reference_ci(x, n_boot=600)
    slow = time.perf_counter() - t
    fast = min(_timed(lambda: stats.stationary_bootstrap_ci(x, n_boot=600)) for _ in range(3))
    assert fast * 2 < slow, "fast path %.3fs vs loop %.3fs" % (fast, slow)


def _timed(fn):
    t = time.perf_counter()
    fn()
    return time.perf_counter() - t


def test_the_paper_edge_p_value_is_computed_once_per_record(monkeypatch):
    """agent.paper_evidence's bootstrap is memoized on the exact per-event P&L: the Deploy board, the
    scoreboard and the strategy page ask for the same record every 10-60s, and it only changes when a
    trade closes. Same answer as the direct call; a changed record is recomputed."""
    agent._EDGE_P.clear()
    calls = []
    real = stats.stationary_bootstrap_ci
    monkeypatch.setattr(stats, "stationary_bootstrap_ci", lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    events = [0.5, -0.25, 1.0, 0.75, -0.5] * 6
    p = agent._paper_edge_p_value(events)
    assert p == real(events, stat="mean", alpha=0.10)["p_value"]
    assert agent._paper_edge_p_value(list(events)) == p and len(calls) == 1
    agent._paper_edge_p_value(events[:-1] + [-0.5000001])
    assert len(calls) == 2
