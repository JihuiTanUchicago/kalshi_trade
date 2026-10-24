"""Tick recorder -> archiver -> tick_store, end to end on a synthetic hour, no network or DB."""
import asyncio
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("pyarrow")

from data_pipeline import tick_archiver, tick_recorder
from data_pipeline.tick_recorder import Books, HourlyFile, snapshot_levels, delta_fields
from data_pipeline.tick_store import TickStore, _ffill

import numpy as np

H = datetime(2026, 10, 24, 18, tzinfo=timezone.utc)
T0 = int(H.timestamp()) * 1_000_000_000
S = 1_000_000_000
TK = "KXBTC15M-26OCT241500-00"


def _kalshi(rt, typ, msg, sid=1, seq=None):
    m = {"type": typ, "sid": sid, "msg": msg}
    if seq is not None:
        m["seq"] = seq
    return json.dumps({"rt": rt, "m": m})


def test_snapshot_and_delta_encodings():
    assert snapshot_levels({"yes": [[8, 300]]}, "yes") == [(0.08, 300.0)]
    assert snapshot_levels({"yes_dollars": [["0.0800", 300]]}, "yes") == [(0.08, 300.0)]
    assert snapshot_levels({"no_dollars_fp": [["0.5600", "146.00"]]}, "no") == [(0.56, 146.0)]
    assert delta_fields({"side": "yes", "price": 96, "delta": -54}) == ("yes", 0.96, -54.0)
    assert delta_fields({"side": "no", "price_dollars": "0.4100", "delta_fp": "12.50"}) == ("no", 0.41, 12.5)


def test_books_apply_and_checkpoint():
    b = Books()
    b.snapshot({"market_ticker": TK, "yes": [[40, 10]], "no": [[58, 5]]})
    b.delta({"market_ticker": TK, "side": "yes", "price": 40, "delta": -10})
    b.delta({"market_ticker": TK, "side": "yes", "price": 41, "delta": 7})
    assert b.checkpoint() == {TK: {"yes": [[0.41, 7.0]], "no": [[0.58, 5.0]]}}


def test_hourly_file_rolls_and_writes_header(tmp_path):
    headers = []
    f = HourlyFile(str(tmp_path), "kalshi", on_roll=lambda w, rt: (headers.append(rt), w('{"rt":0,"checkpoint":{}}')))
    f.write(T0 + 5 * S, '{"a":1}')
    f.write(T0 + 3600 * S + 1, '{"b":2}')
    f.close()
    assert headers == [T0 + 5 * S - 1, T0 + 3600 * S]
    first = (tmp_path / "kalshi" / "20261024" / "18.ndjson").read_text().splitlines()
    second = (tmp_path / "kalshi" / "20261024" / "19.ndjson").read_text().splitlines()
    assert first == ['{"rt":0,"checkpoint":{}}', '{"a":1}'] and second[0].startswith('{"rt":0,"checkpoint"')


def test_discovery_runs_right_after_each_quarter_hour():
    q = 1_800_000_000 - (1_800_000_000 % 900)
    assert tick_recorder._next_discovery_delay(q + 890) == pytest.approx(11.0)
    assert tick_recorder._next_discovery_delay(q + 100) == 30


def test_seq_gap_triggers_resubscribe():
    rec = tick_recorder.KalshiRecorder.__new__(tick_recorder.KalshiRecorder)
    tick_recorder.Recorder.__init__(rec)
    rec.books, rec.groups, rec.pending, rec.sid_group, rec.last_seq, rec.close_time = Books(), [], {}, {}, {}, {}
    rec._id = 0
    sent = []

    class WS:
        async def send(self, s):
            sent.append(json.loads(s))
    rec.ws = WS()
    rec.file = HourlyFile("/tmp/_tick_test_unused", "kalshi")
    rec.meta = lambda *a, **k: None

    async def go():
        await rec.subscribe([TK])
        await rec.on_message("subscribed", {"id": 1, "type": "subscribed", "msg": {"channel": "orderbook_delta", "sid": 7}})
        await rec.on_message("orderbook_snapshot", {"sid": 7, "seq": 1, "msg": {"market_ticker": TK, "yes": [[40, 1]]}})
        await rec.on_message("orderbook_delta", {"sid": 7, "seq": 2, "msg": {"market_ticker": TK, "side": "yes", "price": 41, "delta": 2}})
        await rec.on_message("orderbook_delta", {"sid": 7, "seq": 5, "msg": {"market_ticker": TK, "side": "yes", "price": 42, "delta": 2}})
    asyncio.run(go())
    assert rec.seq_gaps == 1
    assert sent[-2] == {"id": 2, "cmd": "unsubscribe", "params": {"sids": [7]}}
    assert sent[-1]["cmd"] == "subscribe" and sent[-1]["params"] == {"channels": ["orderbook_delta"], "market_tickers": [TK]}
    assert 42 not in [p for p, _ in rec.books.checkpoint()[TK]["yes"]]  # the post-gap delta was not applied


class FakeS3:
    def __init__(self, root):
        self.root = root

    def upload_file(self, path, bucket, key):
        dst = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(path, dst)


def _write_hour(tmp_path):
    kal = tmp_path / "ticks" / "kalshi" / "20261024"
    kal.mkdir(parents=True)
    lines = [
        json.dumps({"rt": T0 + 1, "checkpoint": {TK: {"yes": [[0.40, 100.0]], "no": [[0.58, 50.0]]}}}),
        _kalshi(T0 + 2 * S + 10, "orderbook_delta", {"market_ticker": TK, "side": "yes", "price_dollars": "0.4100", "delta_fp": "30"}, seq=2),
        _kalshi(T0 + 2 * S + 20, "trade", {"market_ticker": TK, "trade_id": "t1", "yes_price_dollars": "0.4100",
                                           "no_price_dollars": "0.5900", "count_fp": "5", "taker_side": "yes", "ts": int(H.timestamp()) + 2}),
        _kalshi(T0 + 3 * S + 5, "orderbook_delta", {"market_ticker": TK, "side": "no", "price": 58, "delta": -50}, seq=3),
        _kalshi(T0 + 3 * S + 6, "ticker", {"market_ticker": TK, "price_dollars": "0.41", "yes_bid_dollars": "0.41",
                                           "yes_ask_dollars": "0.43", "volume_fp": "100"}),
        json.dumps({"rt": T0 + 4 * S, "meta": "seq_gap", "sid": 1, "expected": 4, "got": 6}),
        _kalshi(T0 + 5 * S, "orderbook_snapshot", {"market_ticker": TK, "yes": [[45, 9]], "no": [[50, 4]]}, seq=1),
        '{"rt": 17',   # torn last line from a crash
    ]
    (kal / "18.ndjson").write_text("\n".join(lines) + "\n")
    cb = tmp_path / "ticks" / "coinbase" / "20261024"
    cb.mkdir(parents=True)
    cbl = [
        json.dumps({"rt": T0 + 1 * S + 1, "m": {"type": "match", "product_id": "BTC-USD", "trade_id": 10, "price": "80000.5",
                                                 "size": "0.1", "side": "sell", "time": "2026-10-24T18:00:01.000001Z"}}),
        json.dumps({"rt": T0 + 1 * S + 2, "m": {"type": "ticker", "product_id": "BTC-USD", "trade_id": 10, "price": "80000.5",
                                                 "best_bid": "80000.0", "best_ask": "80001.0", "time": "2026-10-24T18:00:01Z"}}),
        json.dumps({"rt": T0 + 3 * S + 1, "m": {"type": "match", "product_id": "BTC-USD", "trade_id": 11, "price": "80002",
                                                 "size": "0.3", "side": "buy", "time": "2026-10-24T18:00:03Z"}}),
    ]
    (cb / "18.ndjson").write_text("\n".join(cbl) + "\n")
    return tmp_path / "ticks"


def test_archive_then_read_per_second(tmp_path, monkeypatch):
    root = _write_hour(tmp_path)
    lake = tmp_path / "lake"
    rows = []
    monkeypatch.setattr(tick_archiver, "write_manifest_row", lambda m, conn=None: rows.append(m))
    now = H + timedelta(hours=1, minutes=5)
    files = tick_archiver.closed_hour_files(str(root), now)
    assert len(files) == 2 and tick_archiver.closed_hour_files(str(root), H + timedelta(hours=1)) == []
    for path, source, hour in files:
        tick_archiver.archive_file(path, source, hour, s3=FakeS3(str(lake)))
    kal = [m for m in rows if m["source"] == "kalshi"][0]
    assert kal["messages"] == 7 and kal["bad_lines"] == 1 and kal["seq_gaps"] == 1
    assert kal["tables"]["kalshi_trades"] == 1 and kal["max_gap_s"] == pytest.approx(2.0, abs=0.01)
    assert (lake / "ticks/raw/kalshi/date=2026-10-24/18.ndjson.gz").exists()
    assert (lake / "ticks/manifest/coinbase/date=2026-10-24/18.json").exists()

    ts = TickStore(local_root=str(lake))
    book = ts.book_1s([TK], H, H + timedelta(seconds=6))
    by_sec = {int(s) - int(H.timestamp()): i for i, s in enumerate(book["sec"])}
    assert book["yes_bid"][by_sec[1]] == 0.40 and book["yes_ask"][by_sec[1]] == pytest.approx(0.42)
    assert book["yes_bid"][by_sec[3]] == 0.41 and book["yes_bid_size"][by_sec[3]] == 30
    assert np.isnan(book["yes_ask"][by_sec[4]])            # the only NO bid was pulled at 3.000000005s
    assert book["yes_bid"][by_sec[6]] == 0.45 and book["yes_ask"][by_sec[6]] == 0.50  # fresh snapshot replaces
    assert book["updates"][by_sec[3]] == 1

    tr = ts.trades_1s([TK], H, H + timedelta(seconds=6))
    assert list(tr["sec"] - int(H.timestamp())) == [3] and tr["yes_taker"][0] == 5 and tr["vwap_yes"][0] == 0.41

    spot = ts.spot_1s(H, H + timedelta(seconds=5))
    assert len(spot["sec"]) == 5
    assert np.isnan(spot["price"][0]) and spot["price"][1] == 80000.5 and spot["price"][2] == 80000.5
    assert spot["price"][3] == 80002 and spot["taker_buy"][1] == 0.1 and spot["taker_buy"][3] == 0
    assert spot["taker_sell"][3] == 0.3 and spot["bid"][4] == 80000.0

    cov = ts.coverage("kalshi", H, H + timedelta(hours=2))
    assert cov[0]["messages"] == 7 and cov[1] == {"hour_utc": "2026-10-24 19:00:00", "missing": True}


def test_ffill_leaves_leading_nans():
    out = _ffill(np.array([np.nan, 1.0, np.nan, 3.0, np.nan]))
    assert np.isnan(out[0]) and list(out[1:]) == [1.0, 1.0, 3.0, 3.0]


def test_alerter_ages_a_silent_recorder_by_its_last_message():
    from data_pipeline import live_alerter as la

    class Cur:
        def execute(self, sql, params=()):
            self.sql = " ".join(sql.split())

        def fetchone(self):
            if "tick_archive_hours" in self.sql:
                return {"a": 1500}
            return {"a": 5}

        def fetchall(self):
            return [{"state_key": "tick_recorder_kalshi", "a": 4,
                     "state_value": json.dumps({"last_msg_age_s": 500.0})},
                    {"state_key": "tick_recorder_coinbase", "a": 3, "state_value": json.dumps({"last_msg_age_s": 0.2})}]
    ages = la._writer_ages(Cur())
    assert ages["tick_recorder_kalshi"] == 500.0 and ages["tick_recorder_coinbase"] == 3.0
    assert ages["tick_archive"] == 1500.0
    assert ages["tick_recorder_kalshi"] > la.WRITER_CADENCE["tick_recorder_kalshi"] * la.STALE_MULTIPLE
    assert set(la.OPTIONAL_WRITERS) <= set(la.WRITER_CADENCE)
