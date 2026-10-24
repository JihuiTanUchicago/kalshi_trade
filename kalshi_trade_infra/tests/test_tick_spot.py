"""BRTI venue ticks: parsers, recorder behaviour, archive tables, composite, features columns."""
import asyncio
import json
import math
import os
import shutil
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq

from data_pipeline import tick_archiver, tick_features, tick_recorder, tick_spot
from data_pipeline.tick_recorder import HourlyFile
from data_pipeline.tick_store import TickStore

H = datetime(2026, 10, 24, 18, tzinfo=timezone.utc)
H0 = int(H.timestamp())
S = 1_000_000_000

# Venue messages in the shapes their public docs give.
KRAKEN_TRADE = {"channel": "trade", "type": "update", "data": [
    {"symbol": "BTC/USD", "side": "sell", "price": 67000.1, "qty": 0.25, "ord_type": "market", "trade_id": 101,
     "timestamp": "2026-10-24T18:00:01.123456Z"},
    {"symbol": "BTC/USD", "side": "buy", "price": 67000.5, "qty": 0.01, "ord_type": "limit", "trade_id": 102,
     "timestamp": "2026-10-24T18:00:01.200000Z"}]}
KRAKEN_TICKER = {"channel": "ticker", "type": "update", "data": [
    {"symbol": "BTC/USD", "bid": 66999.9, "bid_qty": 1.5, "ask": 67000.0, "ask_qty": 0.7, "last": 67000.5,
     "volume": 1234.5, "timestamp": "2026-10-24T18:00:02.000000Z"}]}
BITSTAMP_TRADE = {"data": {"id": 3333, "timestamp": "1792872001", "amount": 0.05, "amount_str": "0.05000000",
                           "price": 67001, "price_str": "67001", "type": 1, "microtimestamp": "1792872001500000",
                           "buy_order_id": 1, "sell_order_id": 2}, "channel": "live_trades_btcusd", "event": "trade"}
BITSTAMP_BOOK = {"data": {"timestamp": "1792872002", "microtimestamp": "1792872002000000",
                          "bids": [["66998", "0.4"], ["66997", "1.0"]], "asks": [["67002", "0.3"], ["67003", "2"]]},
                 "channel": "order_book_btcusd", "event": "data"}
GEMINI_UPDATE = {"type": "update", "eventId": 5, "socket_sequence": 7, "timestamp": 1792872003, "timestampms": 1792872003250,
                 "events": [{"type": "trade", "tid": 88, "price": "67003.00", "amount": "0.002", "makerSide": "bid"},
                            {"type": "change", "side": "ask", "price": "67004.00", "remaining": "0.5", "delta": "-0.1",
                             "reason": "top-of-book"},
                            {"type": "change", "side": "bid", "price": "67002.00", "remaining": "0", "reason": "top-of-book"}]}
BULLISH_TRADES = {"type": "update", "dataType": "V1TAAnonymousTradeUpdate", "data": {"trades": [
    {"tradeId": "1001", "symbol": "BTCUSD", "price": "67005.0", "quantity": "0.1", "side": "BUY", "isTaker": True,
     "createdAtTimestamp": "1792872004000"}]}}
BULLISH_SNAPSHOT = dict(BULLISH_TRADES, type="snapshot")
BULLISH_L1 = {"type": "update", "dataType": "V1TALevel1", "data": {"symbol": "BTCUSDC", "bid": ["67000.0", "0.2"],
                                                                   "ask": ["67010.0", "0.3"], "timestamp": "1792872004500"}}
CRYPTOCOM_TRADE = {"id": -1, "method": "subscribe", "code": 0, "result": {
    "instrument_name": "BTC_USD", "subscription": "trade.BTC_USD", "channel": "trade",
    "data": [{"d": "4611686018439397540", "t": 1792872005000, "p": "67006.0", "q": "0.003", "s": "SELL", "i": "BTC_USD"}]}}
CRYPTOCOM_SNAPSHOT = dict(CRYPTOCOM_TRADE, id=1)
CRYPTOCOM_TICKER = {"id": -1, "method": "subscribe", "code": 0, "result": {
    "instrument_name": "BTC_USD", "subscription": "ticker.BTC_USD", "channel": "ticker",
    "data": [{"i": "BTC_USD", "b": "67005.5", "bs": "0.8", "k": "67006.5", "ks": "0.4", "a": "67006.0", "t": 1792872005100}]}}
LMAX_BOOK = {"type": "ORDER_BOOK", "instrument_id": "btc-usd", "timestamp": "2026-10-24T18:00:06.000Z", "status": "OPEN",
             "bids": [{"price": "66996.0", "quantity": "1.2"}], "asks": [{"price": "67008.0", "quantity": "0.9"}]}


def rows(source, msg, rt=1):
    hint = getattr(tick_recorder.SPOT_RECORDERS[source], "symbol", None)
    return list(tick_spot.parse(source, rt, msg, hint))


def test_kraken_trades_and_bbo():
    t = rows("kraken", KRAKEN_TRADE)
    assert [r[0] for r in t] == ["kraken_trades"] * 2
    assert t[0][1] == (1, "BTC-USD", "101", 67000.1, 0.25, "sell", tick_spot._iso_ns("2026-10-24T18:00:01.123456Z"))
    q = rows("kraken", KRAKEN_TICKER)
    assert q == [("kraken_quotes", (1, "BTC-USD", 66999.9, 1.5, 67000.0, 0.7, tick_spot._iso_ns("2026-10-24T18:00:02Z")))]
    assert rows("kraken", {"channel": "heartbeat"}) == []
    assert rows("kraken", dict(KRAKEN_TRADE, type="snapshot")) == []


def test_bitstamp_trade_type_is_taker_and_book_touch():
    t = rows("bitstamp", BITSTAMP_TRADE)
    assert t == [("bitstamp_trades", (1, "BTC-USD", "3333", 67001.0, 0.05, "sell", 1792872001500000 * 1000))]
    q = rows("bitstamp", BITSTAMP_BOOK)
    assert q == [("bitstamp_quotes", (1, "BTC-USD", 66998.0, 0.4, 67002.0, 0.3, 1792872002000000 * 1000))]
    assert rows("bitstamp", {"event": "bts:subscription_succeeded", "channel": "live_trades_btcusd", "data": {}}) == []


def test_gemini_maker_side_and_one_sided_quotes():
    out = rows("gemini", GEMINI_UPDATE)
    assert out[0] == ("gemini_trades", (1, "BTC-USD", "88", 67003.0, 0.002, "sell", 1792872003250 * 1_000_000))
    assert out[1] == ("gemini_quotes", (1, "BTC-USD", None, None, 67004.0, 0.5, 1792872003250 * 1_000_000))
    assert len(out) == 2                              # a level with nothing remaining is not a quote
    assert rows("gemini", {"type": "heartbeat", "socket_sequence": 8}) == []


def test_bullish_trades_skip_snapshot_and_l1():
    assert rows("bullish", BULLISH_TRADES) == [
        ("bullish_trades", (1, "BTC-USD", "1001", 67005.0, 0.1, "buy", 1792872004000 * 1_000_000))]
    assert rows("bullish", BULLISH_SNAPSHOT) == []
    assert rows("bullish", BULLISH_L1) == [
        ("bullish_quotes", (1, "BTC-USDC", 67000.0, 0.2, 67010.0, 0.3, 1792872004500 * 1_000_000))]


def test_cryptocom_skips_subscribe_snapshot():
    assert rows("cryptocom", CRYPTOCOM_TRADE) == [
        ("cryptocom_trades", (1, "BTC-USD", "4611686018439397540", 67006.0, 0.003, "sell", 1792872005000 * 1_000_000))]
    assert rows("cryptocom", CRYPTOCOM_SNAPSHOT) == []
    assert rows("cryptocom", CRYPTOCOM_TICKER) == [
        ("cryptocom_quotes", (1, "BTC-USD", 67005.5, 0.8, 67006.5, 0.4, 1792872005100 * 1_000_000))]
    assert rows("cryptocom", {"id": 9, "method": "public/heartbeat"}) == []


def test_lmax_book_and_helpers():
    assert rows("lmax", LMAX_BOOK) == [
        ("lmax_quotes", (1, "BTC-USD", 66996.0, 1.2, 67008.0, 0.9, tick_spot._iso_ns("2026-10-24T18:00:06Z")))]
    assert tick_spot.canon("BTC/USD") == tick_spot.canon("btcusd") == tick_spot.canon("BTC_USD") == "BTC-USD"
    assert tick_spot.canon("BTCUSDC") == "BTC-USDC"
    assert tick_spot.first_level(["1", "2"]) == (1.0, 2.0) and tick_spot.first_level([]) == (None, None)
    assert tick_spot._iso_ns("2026-10-24T18:00:00.123456789Z") == H0 * S + 123456789
    assert tick_spot._iso_ns("not a time") is None
    assert rows("lmax", [1, 2, 3]) == []


# --- recorder --------------------------------------------------------------------------------

class FakeWS:
    def __init__(self, frames):
        self.frames, self.sent, self.closed = list(frames), [], False

    async def send(self, s):
        self.sent.append(json.loads(s))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)

    async def close(self):
        self.closed = True


def _rec(cls, tmp_path):
    rec = cls()
    rec.file = HourlyFile(str(tmp_path), rec.source)
    rec.subscribe_delay_s = 0
    return rec


def test_spot_recorder_records_replies_and_reconnects(tmp_path):
    rec = _rec(tick_recorder.CryptoComRecorder, tmp_path)
    ws = FakeWS([json.dumps({"id": 42, "method": "public/heartbeat", "code": 0}), json.dumps(CRYPTOCOM_TICKER)])
    asyncio.run(rec.pump(ws, "u", rec.streams[0][1]))
    assert ws.sent[0]["method"] == "subscribe" and ws.sent[0]["params"]["channels"] == ["trade.BTC_USD", "ticker.BTC_USD"]
    assert ws.sent[1] == {"id": 42, "method": "public/respond-heartbeat"}
    assert rec.counts == {"public/heartbeat": 1, "ticker": 1}

    bs = _rec(tick_recorder.BitstampRecorder, tmp_path)
    ws = FakeWS([json.dumps({"event": "bts:request_reconnect", "channel": "", "data": ""}), json.dumps(BITSTAMP_TRADE)])
    asyncio.run(bs.pump(ws, "u", []))
    assert bs.counts == {"bts:request_reconnect": 1} and len(ws.frames) == 1     # left at the request


def test_gemini_socket_sequence_gap_and_single_line(tmp_path):
    rec = _rec(tick_recorder.GeminiRecorder, tmp_path)
    metas = []
    rec.meta = lambda event, **kw: metas.append((event, kw))
    frames = [json.dumps({"type": "heartbeat", "socket_sequence": 0}),
              json.dumps(GEMINI_UPDATE, indent=2),                       # seq 7: 1..6 lost; multi-line frame
              json.dumps({"type": "heartbeat", "socket_sequence": 8})]
    asyncio.run(rec.pump(FakeWS(frames), "u", []))
    assert rec.seq_gaps == 1 and metas == [("seq_gap", {"key": "socket", "expected": 1, "got": 7})]
    rec.file.close()
    lines = open(rec.file.path).read().splitlines()
    assert len(lines) == 3 and all(json.loads(l)["m"] for l in lines)


def test_kraken_trade_id_gap(tmp_path):
    rec = _rec(tick_recorder.KrakenRecorder, tmp_path)
    rec.meta = lambda *a, **k: None
    later = {"channel": "trade", "type": "update", "data": [dict(KRAKEN_TRADE["data"][0], trade_id=105)]}
    asyncio.run(rec.pump(FakeWS([json.dumps(KRAKEN_TRADE), json.dumps(later)]), "u", []))
    assert rec.seq_gaps == 1


def test_spot_heartbeat_is_one_row_for_all_venues(tmp_path):
    rec = _rec(tick_recorder.KrakenRecorder, tmp_path)
    asyncio.run(rec.publish("tick_recorder_kraken", {"last_msg_age_s": 1.0}))
    assert tick_recorder.SPOT_STATE["kraken"] == {"last_msg_age_s": 1.0}
    assert set(tick_recorder.SPOT_RECORDERS) == {"kraken", "bitstamp", "gemini", "bullish", "cryptocom", "lmax"}


# --- archive, composite, features ------------------------------------------------------------

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


TK = "KXBTCD-26OCT2415-T67000"


def _line(rt, m):
    return json.dumps({"rt": rt, "m": m})


def _write(root):
    """One hour: a KXBTCD contract; Coinbase quoting 67000 +/- 1; Kraken 67010 +/- 1; Bitstamp
    67020 +/- 1 but silent after H0+90; Gemini 67030 +/- 1, one-sided until H0+50."""
    kal = root / "kalshi" / "20261024"
    kal.mkdir(parents=True)
    kal.joinpath("18.ndjson").write_text("\n".join([
        json.dumps({"rt": H0 * S + 1, "checkpoint": {TK: {"yes": [[0.5, 10.0]], "no": [[0.48, 10.0]], "t": H0 * S}}}),
        json.dumps({"rt": H0 * S + 1, "markets": [{"ticker": TK, "series_ticker": "KXBTCD", "open_time": "2026-10-24T17:00:00Z",
                                                   "close_time": "2026-10-24T19:00:00Z", "floor_strike": 67000.0}]}),
    ]) + "\n")
    for src, hh, lines in (
        ("coinbase", "17", [_line((H0 - 200) * S, {"type": "ticker", "product_id": "BTC-USD", "trade_id": 1, "price": "67000",
                                                   "best_bid": "66999", "best_ask": "67001"})]),
        ("coinbase", "18", [_line((H0 + k) * S + 5, {"type": "ticker", "product_id": "BTC-USD", "trade_id": 2 + k,
                                                     "price": "67000", "best_bid": "66999", "best_ask": "67001"})
                            for k in range(0, 3600, 30)]),
        ("kraken", "18", [json.dumps({"rt": H0 * S, "meta": "connected"})] +
         [_line((H0 + k) * S + 7, {"channel": "ticker", "type": "update", "data": [
             {"symbol": "BTC/USD", "bid": 67009, "bid_qty": 1, "ask": 67011, "ask_qty": 1}]}) for k in range(0, 3600, 20)] +
         [_line((H0 + 5) * S, KRAKEN_TRADE)]),
        ("bitstamp", "18", [_line((H0 + k) * S + 9, dict(BITSTAMP_BOOK, data=dict(BITSTAMP_BOOK["data"], bids=[["67019", "1"]],
                                                                                    asks=[["67021", "1"]])))
                            for k in range(0, 100, 10)]),
        ("gemini", "18", [_line((H0 + 1) * S, dict(GEMINI_UPDATE, events=[{"type": "change", "side": "bid", "price": "67029",
                                                                           "remaining": "1", "reason": "initial"}])),
] + [_line((H0 + k) * S, dict(GEMINI_UPDATE, events=[{"type": "change", "side": "ask", "price": "67031",
                                                                "remaining": "1", "reason": "top-of-book"}]))
                            for k in range(50, 3600, 30)]),
    ):
        d = root / src / "20261024"
        d.mkdir(parents=True, exist_ok=True)
        d.joinpath(hh + ".ndjson").write_text("\n".join(lines) + "\n")


@pytest.fixture
def lake(tmp_path, monkeypatch):
    root = tmp_path / "ticks"
    _write(root)
    lake = tmp_path / "lake"
    s3 = FakeS3(str(lake))
    monkeypatch.setattr(tick_archiver, "write_manifest_row", lambda m, conn=None: None)
    for path, source, hour in tick_archiver.closed_hour_files(str(root), H + timedelta(hours=2)):
        tick_archiver.archive_file(path, source, hour, s3=s3)
    monkeypatch.setattr(tick_archiver, "FEATURE_STATE", str(tmp_path / "built.json"))
    return lake, s3


def test_archive_writes_per_venue_tables_and_parser_version(lake):
    lake, _ = lake
    v1 = lake / "ticks/v1"
    t = pq.read_table(v1 / "kraken_trades/date=2026-10-24/hour=18/part.parquet", partitioning=None)
    assert t.num_rows == 2 and t.column("trade_id").to_pylist() == ["101", "102"]
    assert pq.read_table(v1 / "kraken_quotes/date=2026-10-24/hour=18/part.parquet").num_rows == 180
    assert (v1 / "kraken_meta/date=2026-10-24/hour=18/part.parquet").exists()          # not tick_meta
    assert not (v1 / "tick_meta/date=2026-10-24/hour=18/part.parquet").exists()
    man = json.loads((lake / "ticks/manifest/kraken/date=2026-10-24/18.json").read_text())
    assert man["parser"] == tick_spot.PARSER_VERSION and man["bad_lines"] == 0
    assert man["tables"]["kraken_quotes"] == 180
    assert "parser" not in json.loads((lake / "ticks/manifest/kalshi/date=2026-10-24/18.json").read_text())
    assert tick_archiver.needs_rearchive("kraken", dict(man, parser=0))
    assert not tick_archiver.needs_rearchive("kraken", man) and not tick_archiver.needs_rearchive("kalshi", {"messages": 5})


def test_composite_is_median_of_fresh_venues(lake):
    lake, _ = lake
    store = TickStore(local_root=str(lake))
    c = store.composite_1s(H, H + timedelta(hours=1))
    at = lambda k: k - 1                              # sec H0+k is index k-1
    # H0+60: coinbase 67000, kraken 67010, bitstamp 67020, gemini 67030 (both sides by H0+51)
    assert c["n_venues"][at(60)] == 4 and c["spot_comp"][at(60)] == pytest.approx(67015.0)
    # Bitstamp silent after H0+90 -> dropped after 60s; median of 67000, 67010, 67030
    assert c["n_venues"][at(200)] == 3 and c["spot_comp"][at(200)] == pytest.approx(67010.0)
    # Gemini one-sided until H0+50: no mid; coinbase (carried from the previous hour) + kraken + bitstamp
    assert np.isnan(c["mid_gemini"][at(30)]) and c["spot_comp"][at(30)] == pytest.approx(67010.0)
    assert c["age_coinbase"][at(29)] == pytest.approx(28) and c["mid_coinbase"][at(1)] == pytest.approx(67000.0)
    assert np.isnan(c["mid_lmax"]).all()             # never recorded


def test_features_carry_composite_columns_and_old_hours_still_read(lake, tmp_path):
    lake, s3 = lake
    store = TickStore(local_root=str(lake))
    assert tick_archiver.build_features(s3=s3, store=store, now=H + timedelta(hours=1, minutes=5)) == 1
    f = store.features_1s(H, H + timedelta(hours=1), series=["KXBTCD"])
    i = int(np.nonzero(f["sec"] == H0 + 200)[0][0])
    assert f["spot_comp"][i] == pytest.approx(67010.0) and f["spot_comp_n"][i] == 3
    assert f["spot_cb_comp_bp"][i] == pytest.approx((67000 / 67010 - 1) * 1e4, rel=1e-4)
    assert np.isnan(f["dist_sigma_comp"][i])          # flat Coinbase price: zero vol, as dist_sigma
    # an hour built before the composite existed: same reader, missing columns come back null
    old = lake / "ticks/v1/features_1s/date=2026-10-24/hour=17/series=KXBTCD/part.parquet"
    old.parent.mkdir(parents=True)
    t = pq.read_table(lake / "ticks/v1/features_1s/date=2026-10-24/hour=18/series=KXBTCD/part.parquet", partitioning=None)
    t = t.drop_columns(["spot_comp", "spot_comp_n", "spot_cb_comp_bp", "dist_sigma_comp"]).slice(0, 10)
    t = t.set_column(0, "sec", pa.array(np.arange(H0 - 3599, H0 - 3589, dtype=np.int64)))
    pq.write_table(t, old)
    both = store.features_1s(H - timedelta(hours=1), H + timedelta(hours=1), series=["KXBTCD"],
                             columns=["sec", "spot", "spot_comp"])
    assert len(both["sec"]) == 10 + 3600 and np.isnan(both["spot_comp"][:10].astype(float)).all()


def test_session_opens_every_stream_and_closes_all_when_one_ends(tmp_path, monkeypatch):
    import websockets
    opened, pings = [], []

    async def connect(url, **kw):
        pings.append(kw.get("ping_interval"))
        ws = FakeWS([json.dumps(BULLISH_TRADES)] if url.endswith("/trades") else [])
        opened.append((url, ws))
        return ws
    monkeypatch.setattr(websockets, "connect", connect)
    rec = _rec(tick_recorder.BullishRecorder, tmp_path)
    rec.keepalive_s = 0
    rec.meta = lambda *a, **k: None
    asyncio.run(rec.session())
    assert [u.rsplit("/", 1)[1] for u, _ in opened] == ["trades", "orderbook"]
    assert all(ws.closed for _, ws in opened) and rec.ws is None
    trades_ws = opened[0][1]
    assert [m["params"]["symbol"] for m in trades_ws.sent] == ["BTCUSD", "BTCUSDC"]
    assert {m["params"]["topic"] for m in opened[1][1].sent} == {"l1Orderbook"}
    assert pings == [20, 20]
    lm = _rec(tick_recorder.LmaxRecorder, tmp_path)
    lm.meta = lambda *a, **k: None
    asyncio.run(lm.session())
    assert pings[-1] is None
