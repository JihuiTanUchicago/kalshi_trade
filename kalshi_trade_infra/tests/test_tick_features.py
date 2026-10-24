"""features_1s on a synthetic hour: causality, book/flow/spot columns, distance to strike."""
import json
import math
import os
import shutil
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq

from data_pipeline import tick_archiver, tick_features
from data_pipeline.tick_store import TickStore

H = datetime(2026, 10, 24, 18, tzinfo=timezone.utc)
H0 = int(H.timestamp())
S = 1_000_000_000
TK = "KXBTC15M-26OCT241415-15"
STRIKE = 80000.0


class FakeS3:
    def __init__(self, root):
        self.root = root

    def upload_file(self, path, bucket, key):
        dst = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(path, dst)

    def head_object(self, Bucket, Key):
        if not os.path.exists(os.path.join(self.root, Key)):
            raise FileNotFoundError(Key)
        return {}


def _k(rt, typ, msg, sid=1):
    return json.dumps({"rt": rt, "m": {"type": typ, "sid": sid, "msg": msg}})


def _spot_price(sec):
    """1 bp up every second from H-600s."""
    return STRIKE * math.exp(1e-4 * (sec - (H0 - 600)))


def _write(root):
    kal = root / "kalshi" / "20261024"
    kal.mkdir(parents=True)
    lines = [
        json.dumps({"rt": H0 * S + 1, "checkpoint": {TK: {"yes": [[0.40, 100.0]], "no": [[0.58, 50.0]], "t": (H0 - 30) * S}}}),
        json.dumps({"rt": H0 * S + 1, "markets": [{"ticker": TK, "series_ticker": "KXBTC15M", "open_time": "2026-10-24T17:45:00Z",
                                                   "close_time": "2026-10-24T18:15:00Z", "floor_strike": STRIKE}]}),
        _k((H0 + 10) * S + 5, "orderbook_delta", {"market_ticker": TK, "side": "yes", "price_dollars": "0.4100", "delta_fp": "30"}),
        _k((H0 + 10) * S + 6, "orderbook_delta", {"market_ticker": TK, "side": "yes", "price_dollars": "0.4100", "delta_fp": "-5"}),
        _k((H0 + 20) * S + 1, "trade", {"market_ticker": TK, "trade_id": "a", "yes_price_dollars": "0.41", "count_fp": "7",
                                        "taker_side": "yes"}, sid=2),
        _k((H0 + 25) * S + 1, "trade", {"market_ticker": TK, "trade_id": "b", "yes_price_dollars": "0.40", "count_fp": "3",
                                        "taker_side": "no"}, sid=2),
    ]
    (kal / "18.ndjson").write_text("\n".join(lines) + "\n")
    cb = root / "coinbase" / "20261024"
    cb.mkdir(parents=True)
    for hour_file, lo, hi in (("17.ndjson", H0 - 600, H0), ("18.ndjson", H0, H0 + 100)):
        out = []
        for sec in range(lo, hi):
            p = _spot_price(sec)
            side = "sell" if sec % 2 else "buy"          # maker side; taker is the other
            out.append(json.dumps({"rt": sec * S + 1000, "m": {"type": "match", "product_id": "BTC-USD", "trade_id": sec,
                                                               "price": str(p), "size": "0.5", "side": side}}))
            out.append(json.dumps({"rt": sec * S + 2000, "m": {"type": "ticker", "product_id": "BTC-USD", "trade_id": sec,
                                                               "price": str(p), "best_bid": str(p - 1), "best_ask": str(p + 1)}}))
        (cb / hour_file).write_text("\n".join(out) + "\n")


@pytest.fixture
def built(tmp_path, monkeypatch):
    root = tmp_path / "ticks"
    _write(root)
    lake = tmp_path / "lake"
    s3 = FakeS3(str(lake))
    monkeypatch.setattr(tick_archiver, "write_manifest_row", lambda m, conn=None: None)
    for path, source, hour in tick_archiver.closed_hour_files(str(root), H + timedelta(hours=2)):
        tick_archiver.archive_file(path, source, hour, s3=s3)
    monkeypatch.setattr(tick_archiver, "FEATURE_STATE", str(tmp_path / "built.json"))
    store = TickStore(local_root=str(lake))
    n = tick_archiver.build_features(s3=s3, store=store, now=H + timedelta(hours=1, minutes=5))
    assert n == 1
    t = pq.read_table(lake / "ticks/v1/features_1s/date=2026-10-24/hour=18/series=KXBTC15M/part.parquet", partitioning=None)
    man = json.loads((lake / "ticks/manifest/features_1s/date=2026-10-24/18.json").read_text())
    assert man["tables"]["series"] == {"KXBTC15M": 900}
    rows = {c: t[c].to_numpy(zero_copy_only=False) for c in t.column_names}
    return rows, store, t


def test_rows_only_while_open_and_types(built):
    rows, _, t = built
    assert rows["sec"][0] == H0 + 1 and rows["sec"][-1] == H0 + 900 and len(rows["sec"]) == 900
    assert t.schema.field("sec").type == pa.int64() and t.schema.field("close_ts").type == pa.int64()
    assert t.schema.field("yes_bid").type == pa.float32() and t.schema.field("spot_stale").type == pa.bool_()
    assert set(rows["series"]) == {"KXBTC15M"} and rows["close_ts"][0] == H0 + 900


def test_book_is_causal_and_aged(built):
    rows, _, _ = built
    at = lambda sec: int(np.nonzero(rows["sec"] == H0 + sec)[0][0])
    assert rows["yes_bid"][at(10)] == pytest.approx(0.40)          # delta at 10.000000005s not yet visible
    assert rows["yes_bid"][at(11)] == pytest.approx(0.41) and rows["yes_bid_size"][at(11)] == 25
    assert rows["updates"][at(11)] == 2 and rows["updates"][at(12)] == 0
    assert rows["yes_ask"][at(11)] == pytest.approx(0.42) and rows["yes_ask_size"][at(11)] == 50
    assert rows["bid_depth"][at(11)] == pytest.approx(125)          # 0.41 and 0.40 are within 5c
    assert rows["book_age_s"][at(5)] == pytest.approx(35)           # checkpoint carried the last real update
    assert rows["book_age_s"][at(15)] == pytest.approx(5, abs=1e-3)
    assert rows["mid"][at(11)] == pytest.approx(0.415)
    assert rows["microprice"][at(11)] == pytest.approx((0.41 * 50 + 0.42 * 25) / 75, rel=1e-5)
    assert rows["imbalance"][at(11)] == pytest.approx((25 - 50) / 75, rel=1e-5)


def test_flow_windows(built):
    rows, _, _ = built
    at = lambda sec: int(np.nonzero(rows["sec"] == H0 + sec)[0][0])
    assert rows["yes_taker_10s"][at(20)] == 0 and rows["yes_taker_10s"][at(21)] == 7
    assert rows["yes_taker_10s"][at(30)] == 7 and rows["yes_taker_10s"][at(31)] == 0
    assert rows["no_taker_60s"][at(40)] == 3 and rows["n_prints_60s"][at(40)] == 2
    assert rows["yes_taker_60s"][at(81)] == 0
    assert rows["last_yes"][at(26)] == pytest.approx(0.40) and np.isnan(rows["last_yes"][at(20)])


def test_spot_returns_vol_and_distance(built):
    rows, _, _ = built
    at = lambda sec: int(np.nonzero(rows["sec"] == H0 + sec)[0][0])
    i = at(50)
    # last print before the end of second H0+49 is at H0+49 -> spot price of second 49
    assert rows["spot"][i] == pytest.approx(_spot_price(H0 + 49), rel=1e-6)
    assert rows["spot_ret_1s"][i] == pytest.approx(1e-4, rel=1e-3)
    assert rows["spot_ret_300s"][i] == pytest.approx(3e-2, rel=1e-3)
    assert rows["rv_300s"][i] == pytest.approx(0.0, abs=1e-6)          # constant drift, no variance
    assert not rows["spot_stale"][i] and rows["spot_stale"][at(110)]   # spot stops at H0+100
    assert rows["secs_to_close"][i] == 850
    assert np.isnan(rows["dist_sigma"][i])                              # zero vol -> undefined
    assert rows["spot_taker_imb_60s"][i] == pytest.approx(0.0, abs=0.05)


def test_dist_sigma_formula():
    secs = np.array([100, 101], dtype=np.int64)
    spot = {"spot": np.array([81000.0, 79000.0]), "rv_300s": np.array([1e-4, 1e-4]), "spot_ret_1s": np.zeros(2),
            "spot_ret_10s": np.zeros(2), "spot_ret_60s": np.zeros(2), "spot_ret_300s": np.zeros(2), "rv_60s": np.zeros(2),
            "spot_taker_imb_60s": np.zeros(2), "spot_stale": np.zeros(2, dtype=bool)}
    up = tick_features.ticker_rows("X", {"close_ts": 500, "floor_strike": 80000.0}, secs, spot, None, None)
    assert up["dist_sigma"][0] == pytest.approx(math.log(81000 / 80000) / (1e-4 * math.sqrt(400)))
    rng = tick_features.ticker_rows("X", {"close_ts": 500, "floor_strike": 78000.0, "cap_strike": 80000.0}, secs, spot, None, None)
    assert rng["dist_sigma"][0] < 0 and rng["dist_sigma"][1] == pytest.approx(
        min(math.log(79000 / 78000), math.log(80000 / 79000)) / (1e-4 * math.sqrt(399)))
    assert np.isnan(up["yes_bid"]).all() and (up["updates"] == 0).all()


def test_reader_filters_by_series(built):
    _, store, _ = built
    f = store.features_1s(H, H + timedelta(minutes=1), series=["KXBTC15M"], columns=["sec", "ticker", "yes_bid"])
    assert len(f["sec"]) == 60 and f["sec"][0] == H0 + 1 and set(f) == {"sec", "ticker", "yes_bid"}
    assert store.features_1s(H, H + timedelta(minutes=1), series=["KXBTCD"]) == {}
    by_ticker = store.features_1s(H, H + timedelta(minutes=2), tickers=[TK], columns=["sec"])
    everything = store.features_1s(H, H + timedelta(minutes=2), columns=["sec"])     # series from the manifest
    assert len(by_ticker["sec"]) == len(everything["sec"]) == 120


def test_disk_guard_drops_oldest_closed_hours(tmp_path):
    d = tmp_path / "kalshi" / "20261024"
    d.mkdir(parents=True)
    for hh in ("15", "16"):
        (d / f"{hh}.ndjson").write_text("x")
    gone = tick_archiver.disk_guard(str(tmp_path), min_free=10**18, now=H)
    assert [os.path.basename(p) for p in gone] == ["15.ndjson", "16.ndjson"]
    assert tick_archiver.disk_guard(str(tmp_path), min_free=0, now=H) == []
