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


def _bare_recorder(sent):
    rec = tick_recorder.KalshiRecorder.__new__(tick_recorder.KalshiRecorder)
    tick_recorder.Recorder.__init__(rec)
    rec.books, rec.close_time, rec.meta_by_ticker, rec.resync_times, rec.solo = Books(), {}, {}, [], set()
    rec.reset_session()

    class WS:
        async def send(self, s):
            sent.append(json.loads(s))
    rec.ws = WS()
    rec.meta = lambda *a, **k: None
    rec.file = HourlyFile("/tmp/_tick_test_unused", "kalshi")
    return rec


def test_one_sid_per_channel_seq_gap_resubscribes_all_books():
    sent = []
    rec = _bare_recorder(sent)
    other = "KXBTCD-26OCT2417-T80000"

    async def go():
        await rec.subscribe([TK])
        for ch, sid in (("orderbook_delta", 1), ("trade", 2), ("ticker", 3)):
            await rec.on_message("subscribed", {"id": 1, "type": "subscribed", "msg": {"channel": ch, "sid": sid}})
        await rec.subscribe([other])          # Kalshi folds this into sids 1-3 and answers "ok"
        await rec.on_message("ok", {"id": 2, "type": "ok", "sid": 1, "seq": 1, "msg": {"market_tickers": [TK, other]}})
        await rec.on_message("orderbook_snapshot", {"sid": 1, "seq": 2, "msg": {"market_ticker": TK, "yes": [[40, 1]]}})
        await rec.on_message("orderbook_delta", {"sid": 1, "seq": 3, "msg": {"market_ticker": TK, "side": "yes", "price": 41, "delta": 2}})
        await rec.on_message("trade", {"sid": 2, "seq": 7, "msg": {"market_ticker": TK}})
        await rec.on_message("trade", {"sid": 2, "seq": 9, "msg": {"market_ticker": TK}})   # lost a print: noted only
        assert rec.seq_gaps == 1 and len(sent) == 2
        await rec.on_message("orderbook_delta", {"sid": 1, "seq": 6, "msg": {"market_ticker": TK, "side": "yes", "price": 42, "delta": 2}})
    asyncio.run(go())
    assert rec.seq_gaps == 2
    assert sent[-2] == {"id": 3, "cmd": "unsubscribe", "params": {"sids": [1]}}
    assert sent[-1]["params"] == {"channels": ["orderbook_delta"], "market_tickers": sorted([TK, other])}
    assert 0.42 not in [p for p, _ in rec.books.checkpoint()[TK]["yes"]]  # the post-gap delta was not applied


def test_closed_markets_leave_via_update_subscription_never_unsubscribe():
    sent = []
    rec = _bare_recorder(sent)
    now = datetime.now(timezone.utc)
    old = {"ticker": "OLD-1", "event_ticker": "OLD", "status": "active",
           "close_time": (now + timedelta(minutes=1)).isoformat()}

    async def go():
        await rec.reconcile({"OLD-1": old})
        for ch, sid in (("orderbook_delta", 1), ("trade", 2), ("ticker", 3)):
            await rec.on_message("subscribed", {"id": 1, "type": "subscribed", "msg": {"channel": ch, "sid": sid}})
        rec.close_time["OLD-1"] = now - timedelta(minutes=10)
        await rec.reconcile({})
    asyncio.run(go())
    cmds = [c["cmd"] for c in sent]
    assert "unsubscribe" not in cmds
    upd = [c["params"] for c in sent if c["cmd"] == "update_subscription"]
    assert upd == [{"sids": [s], "market_tickers": ["OLD-1"], "action": "delete_markets"} for s in (1, 2, 3)]
    assert rec.subscribed == set()


def test_rejected_batch_is_retried_one_market_per_command():
    sent = []
    rec = _bare_recorder(sent)
    mk = {t: {"ticker": t, "status": "initialized"} for t in ("A-1", "A-2")}

    async def go():
        await rec.reconcile(mk)
        await rec.on_message("error", {"id": 1, "type": "error", "msg": {"code": 8, "msg": "Unknown market"}})
        await rec.reconcile(mk)
    asyncio.run(go())
    subs = [c["params"]["market_tickers"] for c in sent if c["cmd"] == "subscribe"]
    assert subs == [["A-1", "A-2"], ["A-1"], ["A-2"]]


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
        json.dumps({"rt": T0 + 1, "checkpoint": {TK: {"yes": [[0.40, 100.0]], "no": [[0.58, 50.0]], "t": T0 - 7 * S}}}),
        json.dumps({"rt": T0 + 1, "markets": [{"ticker": TK, "series_ticker": "KXBTC15M", "event_ticker": "KXBTC15M-26OCT241500",
                                               "open_time": "2026-10-24T17:45:00Z", "close_time": "2026-10-24T18:00:00Z",
                                               "floor_strike": 80242.56, "strike_type": "greater_or_equal"}]}),
        _kalshi(T0 + 2 * S + 10, "orderbook_delta", {"market_ticker": TK, "side": "yes", "price_dollars": "0.4100", "delta_fp": "30", "ts_ms": 1792867202001}, seq=2),
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
    assert kal["messages"] == 8 and kal["bad_lines"] == 1 and kal["seq_gaps"] == 1
    assert kal["tables"]["kalshi_markets"] == 1
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

    mk = ts.read("kalshi_markets", H, H + timedelta(hours=1)).to_pylist()[0]
    assert mk["close_ts"] == int(H.timestamp()) and mk["floor_strike"] == 80242.56 and mk["series"] == "KXBTC15M"
    raw = ts.read("kalshi_book", H, H + timedelta(hours=1), tickers=[TK]).to_pylist()
    assert raw[0]["upd_rt"] == T0 - 7 * S and raw[0]["side"] is None          # checkpoint reset marker
    assert [r["exch_ms"] for r in raw if r["kind"] == 1][0] == 1792867202001

    cov = ts.coverage("kalshi", H, H + timedelta(hours=2))
    assert cov[0]["messages"] == 8 and cov[1] == {"hour_utc": "2026-10-24 19:00:00", "missing": True}


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


def test_requested_series_are_recorded_with_their_spot(monkeypatch):
    from data_pipeline import common

    class Conn:
        def cursor(self):
            class C:
                def __enter__(s):
                    return s

                def __exit__(s, *a):
                    return False
            return C()

        def close(self):
            pass
    monkeypatch.setattr(tick_recorder, "get_db_conn", lambda: Conn())
    monkeypatch.setattr(common, "requested_series", lambda cur, kind, limit: ["KXETH15M", {"series": "KXSOLD"}] if kind == "ticks" else [], raising=False)
    monkeypatch.setattr(tick_recorder, "api_get", lambda *a, **k: {"series": [{"ticker": "KXBTCD"}, {"ticker": "KXETHD"}]})
    assert tick_recorder.requested_tick_series() == ["KXETH15M", "KXSOLD"]
    got = tick_recorder.discover_series()
    assert {"KXETH15M", "KXSOLD", "KXBTCD", "KXBTC15M", "KXCRYPTOLEAD15M"} <= set(got) and "KXETHD" not in got
    rec = tick_recorder.CoinbaseRecorder()
    assert rec.wanted_products() == ["BTC-USD", "ETH-USD", "SOL-USD"]
    assert tick_recorder.spot_product("KXBNB15M") == "BNB-USD" and tick_recorder.spot_product("KXNBAGAME") is None


def test_requested_series_absent_helper_or_db_is_empty(monkeypatch):
    from data_pipeline import common
    monkeypatch.delattr(common, "requested_series", raising=False)
    assert tick_recorder.requested_tick_series() == []
    monkeypatch.setattr(common, "requested_series", lambda *a: ["X"], raising=False)
    monkeypatch.setattr(tick_recorder, "get_db_conn", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    assert tick_recorder.requested_tick_series() == []


def test_kalshi_trailing_newline_is_stripped_and_old_split_lines_are_repaired(tmp_path, monkeypatch):
    import gzip
    rec = tick_recorder.Recorder()
    rec.file = HourlyFile(str(tmp_path / "rec"), "kalshi")
    raw = json.dumps({"type": "trade", "sid": 2, "msg": {"market_ticker": TK, "trade_id": "x", "count_fp": "1",
                                                        "yes_price_dollars": "0.5", "taker_side": "yes"}}) + "\n"
    rec.record(T0 + S, raw, "trade")
    rec.file.close()
    assert len(open(rec.file.path).read().splitlines()) == 1

    # An hour written by the first build: every Kalshi message split before its closing brace.
    broken = "".join('{"rt":%d,"m":%s}\n' % (T0 + i * S, raw) for i in range(3))
    assert list(tick_archiver.read_records(broken.splitlines(True)))[0].endswith("}}")

    lake = tmp_path / "lake"
    key_raw = lake / "ticks/raw/kalshi/date=2026-10-24/18.ndjson.gz"
    key_raw.parent.mkdir(parents=True)
    with gzip.open(key_raw, "wt") as fh:
        fh.write(broken)
    man = lake / "ticks/manifest/kalshi/date=2026-10-24/18.json"
    man.parent.mkdir(parents=True)
    man.write_text(json.dumps({"hour_utc": "2026-10-24 18:00:00", "messages": 0, "bad_lines": 6}))

    class S3(FakeS3):
        def list_objects_v2(self, Bucket, Prefix):
            base = os.path.join(self.root, Prefix)
            if not os.path.isdir(base):
                return {}
            return {"Contents": [{"Key": Prefix + f, "ETag": str(os.path.getmtime(os.path.join(base, f)))}
                                 for f in sorted(os.listdir(base))]}

        def download_file(self, bucket, key, path):
            shutil.copy(os.path.join(self.root, key), path)

    rows = []
    monkeypatch.setattr(tick_archiver, "write_manifest_row", lambda m, conn=None: rows.append(m))
    monkeypatch.setattr(tick_archiver, "FEATURE_STATE", str(tmp_path / "tick_features_built.json"))
    tick_archiver._save_built({"2026-10-24 18"})
    s3 = S3(str(lake))
    assert tick_archiver.repair_broken_hours(s3=s3, now=H + timedelta(hours=2)) == 1
    assert rows[0]["messages"] == 3 and rows[0]["bad_lines"] == 0 and rows[0]["tables"]["kalshi_trades"] == 3
    assert "2026-10-24 18" not in tick_archiver._load_built()          # features get rebuilt
    assert tick_archiver.repair_broken_hours(s3=s3, now=H + timedelta(hours=2)) == 0


def test_features_backlog_drains_newest_first_and_a_killed_build_does_not_stall_it(tmp_path, monkeypatch):
    """Prod 10-25 23:00Z: building the oldest missing hour was OOM-killed every run (unit MemoryMax), so
    no later hour was ever built and nothing logged it. Now: newest first, a few per run, an hour counts
    as built only once its features manifest exists, and an hour that keeps killing the build is skipped."""
    from data_pipeline import tick_features
    lake = tmp_path / "lake"

    class S3(FakeS3):
        def head_object(self, Bucket, Key):
            if not os.path.exists(os.path.join(self.root, Key)):
                raise FileNotFoundError(Key)

    now = H + timedelta(hours=10, minutes=5)
    hours = [now.replace(minute=0) - timedelta(hours=k) for k in range(1, 9)]
    for h in hours:
        for src in ("kalshi", "coinbase"):
            p = lake / f"ticks/manifest/{src}/date={h:%Y-%m-%d}/{h:%H}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}")
    monkeypatch.setattr(tick_archiver, "FEATURE_STATE", str(tmp_path / "tick_features_built.json"))
    monkeypatch.setattr(tick_archiver, "write_manifest_row", lambda m, conn=None: None)
    oldest = hours[-1].strftime("%Y-%m-%d %H")
    tick_archiver._save_built({oldest})          # marked built by the old code, but never written
    tick_archiver._save_attempts({hours[0].strftime("%Y-%m-%d %H"): 3})   # the newest killed it 3 times
    built = []

    def build_hour(store, hour, out_dir):
        if hour == hours[1]:
            return None                           # no market metadata: retried, never marked built
        f = os.path.join(out_dir, "KXBTC15M.parquet")
        open(f, "w").close()
        built.append(hour)
        return {"rows": 1, "tickers": 1, "series": {"KXBTC15M": 1}, "files": {"KXBTC15M": f}}

    monkeypatch.setattr(tick_features, "build_hour", build_hour)
    s3 = S3(str(lake))
    assert tick_archiver.build_features(s3=s3, store=object(), now=now) == 2
    assert built == hours[2:4]                    # newest first, 3 tries per run, the killer skipped
    assert hours[1].strftime("%Y-%m-%d %H") not in tick_archiver._load_built()
    while tick_archiver.build_features(s3=s3, store=object(), now=now):
        pass
    assert built[-1] == hours[-1]                 # the stale "built" mark was rebuilt
    assert tick_archiver._load_attempts() == {hours[0].strftime("%Y-%m-%d %H"): 3}
