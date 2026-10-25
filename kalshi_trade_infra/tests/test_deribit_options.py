"""Deribit options feed: instrument parsing, chain/trade surfaces, the archive -> features_1s path,
the daily history files, and research/live parity of the opt_* features."""
import json
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq

from app import backtest, engine, options_fair, repository
from app.markets import FEATURES, MARKETS, BtcSeries, Contract
from data_pipeline import deribit_options as do
from data_pipeline import options_surface as osf
from data_pipeline import tick_archiver
from data_pipeline.tick_store import TickStore
from tests.test_tick_features import FakeS3, H, H0, S, STRIKE, TK, _spot_price, _write

EXP1 = int(datetime(2026, 10, 25, 8, tzinfo=timezone.utc).timestamp())    # BTC-25OCT26
EXP2 = int(datetime(2026, 11, 1, 8, tzinfo=timezone.utc).timestamp())     # BTC-1NOV26


def _iv(k, atm=0.45, slope=-0.3):
    """True smile of the synthetic chain: vol linear in ln(K/F)."""
    return atm + slope * k


def _chain(fwd1=80_000.0, fwd2=80_400.0, index=80_000.0):
    rows = []
    for code, fwd, atm in (("25OCT26", fwd1, 0.45), ("1NOV26", fwd2, 0.50)):
        for k in range(70_000, 90_001, 1000):
            for cp in ("C", "P"):
                iv = _iv(math.log(k / fwd), atm)
                itm = (cp == "C") != (k >= fwd)
                rows.append({"instrument_name": f"BTC-{code}-{k}-{cp}", "mark_iv": 300.0 if itm else iv * 100,
                             "underlying_price": fwd, "estimated_delivery_price": index, "mark_price": 0.01})
    rows.append({"instrument_name": "BTC-PERPETUAL", "mark_iv": None})
    return rows


def test_parse_instrument():
    assert do.parse_instrument("BTC-25OCT26-110000-C") == (EXP1, 110000.0, "C")
    assert do.parse_instrument("BTC-1NOV26-95000-P") == (EXP2, 95000.0, "P")
    for bad in ("BTC-PERPETUAL", "BTC-25OCT26", "BTC-25XXX26-1-C", None):
        assert do.parse_instrument(bad) is None


def test_chain_surface_uses_forwards_and_out_of_the_money_marks():
    snap = EXP1 - 6 * 3600
    s = do.surface_from_chain(_chain(), snap)
    assert s.index_price == 80_000.0 and [e.expiry_ts for e in s.expiries] == [EXP1, EXP2]
    e1, e2 = s.expiries
    assert e1.basis == pytest.approx(0.0) and e2.basis == pytest.approx(math.log(80_400 / 80_000))
    assert e1.atm_iv == pytest.approx(0.45, abs=1e-3) and e2.atm_iv == pytest.approx(0.50, abs=1e-3)
    assert max(e1.grid) < 1.0                          # the 300% in-the-money marks were ignored
    # an expiry within a minute of the snapshot is not used
    assert [e.expiry_ts for e in do.surface_from_chain(_chain(), EXP1 - 30).expiries] == [EXP2]


def test_trades_surface_fits_each_expiry_from_the_window():
    snap = EXP1 - 10 * 3600
    rng = np.random.default_rng(3)
    trades = []
    for i in range(300):
        k = float(rng.choice(np.arange(76_000, 84_001, 500)))
        ts_ms = (snap - 3000 + i * 10) * 1000
        trades.append({"instrument_name": f"BTC-25OCT26-{int(k)}-C", "timestamp": ts_ms, "amount": 1.0,
                       "iv": 100 * _iv(math.log(k / 80_000)) + float(rng.normal(0, 0.3)), "index_price": 80_000.0,
                       "trade_id": str(i)})
    trades.append({"instrument_name": "BTC-25OCT26-80000-C", "timestamp": (snap + 5) * 1000, "iv": 999,
                   "index_price": 1.0, "amount": 1})     # after the snapshot: not seen
    s = do.surface_from_trades(trades, snap)
    assert s.method == "trades" and s.known_ns == snap * S and s.index_price == 80_000.0
    (e,) = s.expiries
    assert e.atm_iv == pytest.approx(0.45, abs=0.005)
    p, iv = osf.price(s, snap, 81_000, snap + 3 * 3600, 80_000.0)
    assert iv[0] == pytest.approx(_iv(math.log(81_000 / 80_000)), abs=0.01)
    assert do.surface_from_trades(trades, snap - 7200) is None


def _write_deribit(root):
    d = root / "deribit" / "20261024"
    d.mkdir(parents=True)
    for hh, lo, hi in (("17", H0 - 180, H0), ("18", H0, H0 + 3600)):
        lines = [json.dumps({"rt": t * S + 500, "m": {"type": "book_summary", "index": 80_000.0, "summary": _chain()}})
                 for t in range(lo, hi, 60)]
        (d / f"{hh}.ndjson").write_text("\n".join(lines) + "\n")


@pytest.fixture
def lake(tmp_path, monkeypatch):
    root = tmp_path / "ticks"
    _write(root)
    _write_deribit(root)
    lake = tmp_path / "lake"
    s3 = FakeS3(str(lake))
    monkeypatch.setattr(tick_archiver, "write_manifest_row", lambda m, conn=None: None)
    monkeypatch.setattr(tick_archiver, "FEATURE_STATE", str(tmp_path / "built.json"))
    for path, source, hour in tick_archiver.closed_hour_files(str(root), H + timedelta(hours=2)):
        tick_archiver.archive_file(path, source, hour, s3=s3)
    store = TickStore(local_root=str(lake))
    assert tick_archiver.build_features(s3=s3, store=store, now=H + timedelta(hours=1, minutes=5)) == 1
    return lake, s3, store


def test_archive_writes_options_and_surface_tables(lake):
    lake, _, store = lake
    opts = store.read("deribit_options", H, H + timedelta(hours=1))
    assert opts.num_rows == 60 * 2 * 21 * 2         # 60 polls x 2 expiries x 21 strikes x C/P
    assert set(opts.column("cp").to_pylist()) == {"C", "P"}
    surf = store.read("deribit_surface", H, H + timedelta(hours=1))
    assert surf.num_rows == 60 * 2 and set(surf.column("method").to_pylist()) == {"chain"}
    man = json.loads((lake / "ticks/manifest/deribit/date=2026-10-24/18.json").read_text())
    assert man["messages"] == 60 and man["bad_lines"] == 0


def test_features_1s_price_each_second_off_the_surface_known_before_it(lake):
    lake, _, store = lake
    t = pq.read_table(lake / "ticks/v1/features_1s/date=2026-10-24/hour=18/series=KXBTC15M/part.parquet",
                      partitioning=None)
    rows = {c: t[c].to_numpy(zero_copy_only=False) for c in t.column_names}
    i = int(np.nonzero(rows["sec"] == H0 + 50)[0][0])
    # newest poll received before H0+50 is the one at H0 (rt H0 + 500ns)
    s = do.surface_from_chain(_chain(), H0, 80_000.0, H0 * S + 500)
    spot = float(rows["spot_comp"][i]) if np.isfinite(rows["spot_comp"][i]) else float(rows["spot"][i])
    p, iv = osf.prob_yes(s, H0 + 50, STRIKE, None, H0 + 900, spot)
    assert rows["opt_p_yes"][i] == pytest.approx(p[0], abs=1e-5) and rows["opt_iv"][i] == pytest.approx(iv[0], rel=1e-5)
    # the 17:57-17:59 polls cover the hour's first seconds; at the close second nothing is left to price
    assert np.isfinite(rows["opt_p_yes"][:-1]).all() and np.isnan(rows["opt_p_yes"][-1])


def test_research_reads_day_files_and_drops_trade_fits_where_chain_exists(lake, monkeypatch):
    lake, s3, store = lake
    day = H.replace(hour=0)
    trades = [{"instrument_name": "BTC-25OCT26-80000-C", "timestamp": (H0 - 1800 + i) * 1000, "iv": 45.0,
               "index_price": 80_000.0, "amount": 1.0, "trade_id": str(i)} for i in range(0, 1800, 30)]
    trades += [{"instrument_name": "BTC-25OCT26-80000-C", "timestamp": (H0 + 3600 + 600) * 1000, "iv": 45.0,
                "index_price": 80_000.0, "amount": 1.0, "trade_id": "x"}]
    windows = []

    def fetch(a, b):
        windows.append((a, b))
        return trades
    n = do.backfill(days=3, max_days=5, s3=s3, now=day + timedelta(days=1, hours=1), fetch=fetch, store=store)
    assert n == 1 and windows[0] == ((int(day.timestamp()) - 3600) * 1000, (int(day.timestamp()) + 86400) * 1000)
    assert len(windows) == 3                          # newest first; days without a surface stay missing
    rows = pq.read_table(lake / do.day_key(day)).to_pylist()
    methods = {(r["method"], r["snap_ts"] // 3600) for r in rows}
    assert ("chain", H0 // 3600) in methods and ("trades", H0 // 3600 + 1) in methods
    assert do.backfill(days=3, max_days=5, s3=s3, now=day + timedelta(days=1, hours=1), fetch=fetch, store=store) == 0
    got = options_fair.load_surfaces(H - timedelta(minutes=10), H + timedelta(hours=3), store=store)
    by_hour = {}
    for s in got:
        by_hour.setdefault(s.snap_ts // 3600, set()).add(s.method)
    assert by_hour[H0 // 3600] == {"chain"}          # trade fits dropped inside chain hours
    assert by_hour[H0 // 3600 + 1] == {"trades"}
    chain = [s.snap_ts for s in got if s.method == "chain"]
    step = options_fair.RESEARCH_STEP_S
    assert len({t // step for t in chain}) == len(chain) and len(chain) >= 3600 // step   # one per 5 minutes


def test_research_and_live_compute_identical_options_features():
    snap = EXP1 - 20 * 3600
    surface = do.surface_from_chain(_chain(), snap, 80_000.0, snap * S)
    rows = surface.rows()
    ts = snap + 300
    btc = [(ts - 60 * (k + 1), 80_000.0 + k + 15.0 * (-1) ** k) for k in range(90)]
    close = datetime.fromtimestamp(ts + 600, tz=timezone.utc)
    quotes = [engine.LiveQuote(Contract("KXBTC15M-X-00", 79_900.0, close, "KXBTC15M"), 0.55, 0.57, 5.0, 5.0)]
    markets = [{"ticker": "KXBTC15M-X-00", "strike": 79_900.0, "close_time": close, "result": "yes"}]
    candles = [("KXBTC15M-X-00", ts, 0.55, 0.57)]
    book = options_fair.book_for_series("KXBTC15M", lambda: options_fair.book_from_rows(rows))
    ds = backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc, forecasts=book)
    research = ds.frames[0][1][0].features
    seen = {}

    def options(as_of):
        seen["as_of"] = as_of
        return rows
    src = engine.Sources(quotes=lambda m: quotes, spot=lambda m: BtcSeries(btc), options=options)
    snaps, _ = engine._cross_market_frame(["btc15m"], src, ts)
    live = snaps[0].features
    keys = ("opt_p_yes", "opt_edge", "opt_iv", "opt_age_min", "opt_iv_rv", "opt_rv_p_yes", "opt_rv_edge")
    assert seen["as_of"] == ts and {k: research[k] for k in keys} == {k: live[k] for k in keys}
    assert research["opt_edge"] == pytest.approx(research["opt_p_yes"] - 0.56)
    assert research["opt_age_min"] == pytest.approx(5.0) and 0.5 < research["opt_p_yes"] < 1.0
    # no options feed wired: the features are simply absent
    snaps, _ = engine._cross_market_frame(["btc15m"], engine.Sources(quotes=lambda m: quotes,
                                                                     spot=lambda m: BtcSeries(btc)), ts)
    assert "opt_p_yes" not in snaps[0].features


def test_only_bitcoin_strike_series_get_a_book_and_features_are_registered():
    assert options_fair.book_for_series("KXETH15M", lambda: 1 / 0) is None
    for name in ("opt_p_yes", "opt_edge", "opt_iv", "opt_age_min", "opt_iv_rv", "opt_rv_p_yes", "opt_rv_edge"):
        assert name in FEATURES


def test_realized_vol_recalibration_reprices_the_smile_at_the_hours_realized_vol():
    snap = EXP1 - 20 * 3600
    surface = do.surface_from_chain(_chain(), snap, 80_000.0, snap * S)
    book = options_fair.book_from_rows(surface.rows())
    ts, close, spot = snap + 300, snap + 300 + 900, 80_000.0
    _, (iv_atm,) = osf.price(surface, ts, spot, close, spot)

    def feats(rv_ann, strike=80_150.0):
        rv = rv_ann / options_fair.MINUTES_PER_YEAR ** 0.5
        return options_fair.snapshot_features(book, strike, ts, close, 0.10, 0.12, {"spot": spot, "vol_60m": rv})
    same = feats(iv_atm)                                  # realized = implied: nothing changes
    assert same["opt_iv_rv"] == pytest.approx(1.0) and same["opt_rv_p_yes"] == pytest.approx(same["opt_p_yes"], abs=1e-9)
    calm = feats(iv_atm / 2)                              # a quiet hour: the out-of-the-money YES gets cheaper
    assert calm["opt_iv_rv"] == pytest.approx(2.0) and calm["opt_rv_p_yes"] < calm["opt_p_yes"] - 0.02
    assert calm["opt_rv_edge"] == pytest.approx(calm["opt_rv_p_yes"] - 0.11)
    assert feats(iv_atm / 50)["opt_rv_p_yes"] == pytest.approx(feats(iv_atm / 5)["opt_rv_p_yes"])   # scale floor 0.2
    flat = options_fair.snapshot_features(book, 80_150.0, ts, close, 0.10, 0.12, {"spot": spot, "vol_60m": 0.0})
    assert "opt_p_yes" in flat and not {"opt_iv_rv", "opt_rv_p_yes", "opt_rv_edge"} & set(flat)


class _Cur:
    def __init__(self, value):
        self.value = value

    def execute(self, sql, params=()):
        assert "tick_recorder_deribit" in sql

    def fetchone(self):
        return {"state_value": self.value} if self.value is not None else None


def test_latest_options_surface_reads_the_recorder_heartbeat():
    rows = do.surface_from_chain(_chain(), EXP1 - 3600).rows()
    cur = _Cur(json.dumps({"polls": 3, "surface": rows}))
    assert repository.latest_options_surface(cur, EXP1 - 3600) == rows
    assert repository.latest_options_surface(cur, EXP1 - 3601) is None       # not known yet
    assert repository.latest_options_surface(_Cur(None), EXP1) is None
    assert repository.latest_options_surface(_Cur("not json"), EXP1) is None


def test_parse_record_ignores_other_lines():
    assert list(do.parse_record(1, {"type": "other"})) == []
    assert list(do.parse_record(1, None)) == []


class _Resp:
    def __init__(self, body, code=200):
        self.status_code, self._body, self.text = code, body, json.dumps(body)

    def json(self):
        return self._body


class _Session:
    """history.deribit.com stand-in: pages of 2 trades, the second page repeating a millisecond."""

    def __init__(self):
        self.trades = [{"trade_id": str(i), "timestamp": ts} for i, ts in enumerate((1000, 1001, 1001, 1002, 1005))]
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params["start_timestamp"])
        if len(self.calls) == 1:
            return _Resp({"error": "busy"}, 429)
        rows = [t for t in self.trades if params["start_timestamp"] <= t["timestamp"] <= params["end_timestamp"]][:2]
        more = len([t for t in self.trades if params["start_timestamp"] <= t["timestamp"] <= params["end_timestamp"]]) > 2
        return _Resp({"result": {"trades": rows, "has_more": more}})


def test_fetch_trades_pages_dedupes_and_retries(monkeypatch):
    monkeypatch.setattr(do.time, "sleep", lambda s: None)
    sess = _Session()
    got = do.fetch_trades(1000, 1006, session=sess)
    assert [t["trade_id"] for t in got] == ["0", "1", "2", "3", "4"]
    assert sess.calls[:2] == [1000, 1000]           # the 429 was retried


def test_batched_options_features_equal_per_snapshot_features():
    """build_dataset prefetches every snapshot's options features in a few vectorized calls; the
    result must be exactly what snapshot_features gives one contract at a time."""
    snap = EXP1 - 20 * 3600
    s1 = do.surface_from_chain(_chain(), snap, 80_000.0, snap * S)
    s2 = do.surface_from_chain(_chain(fwd1=80_500.0, fwd2=80_900.0), snap + 900, 80_500.0, (snap + 900) * S)
    book = options_fair.book_from_rows(s1.rows() + s2.rows())
    rng = np.random.default_rng(7)
    reqs = []
    for _ in range(400):
        ts = int(snap - 600 + rng.integers(0, 3 * 3600))          # some before any surface, some stale
        ff = {"spot": 0.0 if rng.random() < 0.1 else 79_000 + rng.random() * 2_000,
              "vol_60m": 0.0 if rng.random() < 0.2 else rng.random() * 0.002}
        bid = None if rng.random() < 0.1 else round(float(rng.random() * 0.9), 2)
        reqs.append((0.0 if rng.random() < 0.1 else 78_000 + rng.random() * 4_000, ts,
                     None if rng.random() < 0.05 else ts + int(rng.integers(-60, 3600)), bid,
                     None if bid is None else bid + 0.02, ff))
    one = [options_fair.snapshot_features(book, *r) for r in reqs]
    assert options_fair.snapshot_features_batch(book, reqs) == one
    assert sum(1 for f in one if "opt_rv_edge" in f) > 30 and sum(1 for f in one if not f) > 40
    book.prefetch(reqs)
    assert [book.features("T", r[0], r[1], r[3], r[4], r[5], close_ts=r[2]) for r in reqs] == one


def test_build_dataset_prefetches_options_features_once(monkeypatch):
    snap = EXP1 - 20 * 3600
    rows = do.surface_from_chain(_chain(), snap, 80_000.0, snap * S).rows()
    ts = snap + 300
    btc = [(ts - 60 * (k + 1), 80_000.0 + k + 15.0 * (-1) ** k) for k in range(90)]
    close = datetime.fromtimestamp(ts + 600, tz=timezone.utc)
    markets = [{"ticker": f"KXBTC15M-X-{k:02d}", "strike": 79_800.0 + 50 * k, "close_time": close, "result": "yes"}
               for k in range(5)]
    candles = [(m["ticker"], t, 0.55, 0.57) for m in markets for t in (ts, ts + 60, ts + 120)]
    book = options_fair.book_for_series("KXBTC15M", lambda: options_fair.book_from_rows(rows))
    calls = []
    real = osf.price
    monkeypatch.setattr(osf, "price", lambda *a, **k: calls.append(1) or real(*a, **k))
    ds = backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc, forecasts=book)
    batched = [s.features for _, snaps in ds.frames for s in snaps]
    assert len(batched) == 15 and all("opt_p_yes" in f for f in batched) and len(calls) <= 3
    monkeypatch.setattr(type(book), "prefetch", lambda self, reqs: None)
    book._prefetched = {}
    ref = backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc, forecasts=book)
    assert [s.features for _, snaps in ref.frames for s in snaps] == batched
