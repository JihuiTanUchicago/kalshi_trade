"""Tests for app.partitions: the chronological 60/25/15 split math (boundary
snapping, settlement-cadence purge/embargo, fingerprint) and ensure_partition's
freeze/supersede against the in-memory LedgerCursor. No live DB; the dataset
LOADERS (research/validation/holdout_dataset) are integration-only and not
exercised here — these tests own the boundary logic.
"""
from datetime import timedelta

import pytest

from app import partitions
from app.markets import MARKETS
from app.repository import now_utc
from tests.test_research_repository import LedgerCursor


def _contracts(duration, window, n, start_ts=1_000_000):
    """n contracts settling every `duration` seconds, each listed for `window`
    seconds (window > duration mimics btc_daily's 25h listing / 24h cadence)."""
    out = []
    for i in range(n):
        close = start_ts + (i + 1) * duration
        out.append({"ticker": "T%04d" % i, "open_ts": close - window,
                    "close_ts": close, "result": "yes" if i % 2 else "no"})
    return out


# -- pure boundary math --------------------------------------------------------


def test_boundaries_chronological_and_contiguous():
    ct = _contracts(900, 900, 100)
    b = partitions._compute_boundaries(MARKETS["btc15m"], ct)
    assert b["research_from_ts"] < b["research_to_ts"] < b["validation_to_ts"] < b["holdout_to_ts"]
    # contiguous, non-overlapping: each window's end is the next window's start
    assert b["research_to_ts"] == b["validation_from_ts"]
    assert b["validation_to_ts"] == b["holdout_from_ts"]


def test_boundaries_snapped_to_contract_opens():
    ct = _contracts(900, 900, 100)
    opens = {c["open_ts"] for c in ct}
    b = partitions._compute_boundaries(MARKETS["btc15m"], ct)
    # the two internal cuts land exactly on real contract open times (no straddle)
    assert b["research_to_ts"] in opens
    assert b["validation_to_ts"] in opens


def test_split_ratios_are_roughly_60_25_15():
    ct = _contracts(900, 900, 100)
    b = partitions._compute_boundaries(MARKETS["btc15m"], ct)
    span = ct[-1]["open_ts"] - ct[0]["open_ts"]
    research = (b["research_to_ts"] - b["research_from_ts"]) / span
    validation = (b["validation_to_ts"] - b["validation_from_ts"]) / span
    assert 0.55 <= research <= 0.63
    assert 0.22 <= validation <= 0.28


def test_embargo_purge_btc15m():
    b = partitions._compute_boundaries(MARKETS["btc15m"], _contracts(900, 900, 100))
    assert b["purge_seconds"] == 900          # one settlement cadence
    assert b["embargo_seconds"] == 960        # + one decision bar (60s)


def test_embargo_purge_btc_daily_uses_cadence_not_listing_window():
    # daily contracts list for 25h (90000s) but settle every 24h (86400s);
    # purge must be the 24h cadence, embargo 24h + one 60-min decision bar.
    b = partitions._compute_boundaries(MARKETS["btc_daily"], _contracts(86400, 90000, 40))
    assert b["purge_seconds"] == 86400
    assert b["embargo_seconds"] == 90000


def test_fingerprint_deterministic_and_data_sensitive():
    ct = _contracts(900, 900, 50)
    a = partitions._compute_boundaries(MARKETS["btc15m"], ct)["data_fingerprint"]
    b = partitions._compute_boundaries(MARKETS["btc15m"], list(ct))["data_fingerprint"]
    assert a == b and len(a) == 64
    ct2 = ct + _contracts(900, 900, 1, start_ts=ct[-1]["close_ts"])
    assert partitions._compute_boundaries(MARKETS["btc15m"], ct2)["data_fingerprint"] != a


def test_holdout_max_evaluations_defaults():
    assert partitions.holdout_max_evaluations("btc15m") == 10
    assert partitions.holdout_max_evaluations("eth_daily") == 10
    assert partitions.holdout_max_evaluations("btc_daily") == 3


# -- ensure_partition freeze / reuse / supersede -------------------------------


def _seed_hist(cur, market_key, duration, window, n):
    m = MARKETS[market_key]
    # anchor the newest contract near now so the history_days cutoff keeps them all
    end = now_utc().replace(microsecond=0)
    base = int((end - timedelta(seconds=(n + 1) * duration)).timestamp())
    for c in _contracts(duration, window, n, start_ts=base):
        from datetime import datetime, timezone
        cur.t["hist_markets"].append({
            "series_ticker": m.series, "ticker": c["ticker"],
            "open_time": datetime.fromtimestamp(c["open_ts"], tz=timezone.utc).replace(tzinfo=None),
            "close_time": datetime.fromtimestamp(c["close_ts"], tz=timezone.utc).replace(tzinfo=None),
            "result": c["result"], "candles_done": 1,
        })


@pytest.fixture
def cur():
    return LedgerCursor()


def test_ensure_partition_freezes_and_persists(cur):
    _seed_hist(cur, "btc15m", 900, 900, 120)
    part = partitions.ensure_partition(cur, "btc15m")
    assert part["active"] == 1
    assert part["purge_seconds"] == 900 and part["embargo_seconds"] == 960
    assert part["research_from_ts"] < part["holdout_to_ts"]
    assert len(cur.t["app_data_partitions"]) == 1


def test_ensure_partition_reuses_unchanged_data(cur):
    _seed_hist(cur, "btc15m", 900, 900, 120)
    a = partitions.ensure_partition(cur, "btc15m")
    b = partitions.ensure_partition(cur, "btc15m")  # same data -> same frozen row
    assert a["id"] == b["id"]
    assert len(cur.t["app_data_partitions"]) == 1


def test_ensure_partition_supersedes_on_data_change(cur):
    _seed_hist(cur, "btc15m", 900, 900, 120)
    a = partitions.ensure_partition(cur, "btc15m")
    _seed_hist(cur, "btc15m", 900, 900, 1)  # one more contract -> new fingerprint
    # shift the extra one past the others so it is genuinely new
    cur.t["hist_markets"][-1]["ticker"] = "ZZZZ"
    b = partitions.ensure_partition(cur, "btc15m")
    assert b["id"] != a["id"]
    actives = [r for r in cur.t["app_data_partitions"] if r["active"] == 1]
    assert len(actives) == 1 and actives[0]["id"] == b["id"]


def test_ensure_partition_no_data_raises(cur):
    with pytest.raises(ValueError):
        partitions.ensure_partition(cur, "btc15m")
