"""Read-only Kalshi-demo replay that draws the second (realized) equity line.

No network and no live calls: the dev candlestick GET is monkeypatched. Covers
the happy path (a realized curve from mocked demo candlesticks) and graceful
degradation when demo creds or data are absent.
"""
from datetime import datetime, timezone

from app.trading import backtest
from app.adapters.kalshi import kalshi_dev
from app.trading import spec as specmod
from app.trading.markets import MARKETS

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def _dataset(n_contracts=40, minutes=15, result="yes", ask=0.40, bid=0.38):
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n_contracts * minutes + 200)]
    markets, candles = [], []
    for k in range(n_contracts):
        open_ts = T0 + k * minutes * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        ticker = "M%d" % k
        markets.append({"ticker": ticker, "strike": 98.0, "close_time": close, "result": result})
        for m in range(1, minutes + 1):
            candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                            "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


def _demo_feed(ds, bid, ask):
    """A fake Kalshi-demo candlestick GET built from the dataset's OOS frames."""
    wanted = {}  # ticker -> list of ts in the OOS window
    for ts, snaps in ds.frames:
        if ts < ds.cutoff_ts:
            continue
        for sn in snaps:
            wanted.setdefault(sn.contract.ticker, []).append(ts)

    def fake_get(path, params, timeout=15):
        ticker = path.split("/markets/")[1].split("/")[0]
        cs = [{"end_period_ts": ts,
               "yes_bid": {"close_dollars": bid}, "yes_ask": {"close_dollars": ask}}
              for ts in wanted.get(ticker, [])]
        return {"candlesticks": cs}

    return fake_get


def test_dev_replay_produces_a_realized_curve(monkeypatch):
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}})
    # Demo book priced the same as our history -> the realized curve trades and wins.
    monkeypatch.setattr(kalshi_dev, "_dev_get", _demo_feed(ds, 0.38, 0.40))
    out = kalshi_dev._compute(s, ds)
    assert out is not None
    assert out["env"] == "kalshi-dev"
    assert len(out["dev_curve"]) >= 2
    assert out["dev_metrics"]["trades"] > 0
    assert out["dev_metrics"]["pnl"] > 0  # yes-settled contracts bought cheap


def test_dev_replay_reflects_worse_demo_prices(monkeypatch):
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1, "max_spread": 0.05}})
    # Pay more on the demo book -> realized P&L is lower than our own history's.
    monkeypatch.setattr(kalshi_dev, "_dev_get", _demo_feed(ds, 0.58, 0.60))
    out = kalshi_dev._compute(s, ds)
    assert out is not None
    cutoff = ds.cutoff_ts
    sim_oos = backtest.metrics(
        backtest.simulate(s, ds, cutoff, ds.end_ts + 1),
        s["sizing"]["stake"] * s["sizing"]["max_positions"], 1.0,
    )["pnl"]
    assert out["dev_metrics"]["pnl"] < sim_oos


def _dataset_priced(asks, minutes=40):
    """One contract per entry in `asks`, all sharing the whole window so every
    contract is first-seen in insertion order; `asks[k]` sets contract k's YES ask
    (bid 2c under). A multi-day market's OOS window works the same way: many
    contracts, only some of which the strategy actually trades."""
    open_ts = T0
    close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
    btc = [(open_ts - 7200 + 60 * i, 100.0) for i in range(minutes + 300)]
    markets, candles = [], []
    for k, ask in enumerate(asks):
        ticker = "M%d" % k
        markets.append({"ticker": ticker, "strike": 98.0, "close_time": close, "result": "yes"})
        for m in range(1, minutes + 1):
            candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                            "yes_bid_close": ask - 0.02, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


def test_dev_replay_covers_the_contracts_the_strategy_trades(monkeypatch):
    # Root cause: the first-seen strike ladder is mostly disjoint from the
    # contracts a strategy trades, so capping to the FIRST MAX_CONTRACTS first-seen
    # tickers fetched only untraded contracts -> 0 aligned trades -> null slippage.
    # Here the early first-seen contracts are priced out of the YES band and only
    # the later ones trade; the dev replay must still cover those traded contracts.
    monkeypatch.setattr(kalshi_dev, "MAX_CONTRACTS", 3)
    ds = _dataset_priced([0.97, 0.97, 0.97, 0.40, 0.40, 0.40])
    s = specmod.validate({"side": "yes"})
    monkeypatch.setattr(kalshi_dev, "_dev_get", _demo_feed(ds, 0.43, 0.45))
    out = kalshi_dev._compute(s, ds)
    assert out is not None
    # Old behavior fetched M0..M2 (untraded) -> slippage None; the fix fetches the
    # traded M3..M5 so >= MIN_ALIGNED_TRADES align and the realized curve fills.
    assert out["dev_metrics"]["trades"] >= kalshi_dev.MIN_ALIGNED_TRADES
    assert len(out["dev_curve"]) >= kalshi_dev.MIN_ALIGNED_TRADES
    slip = out["slippage"]
    assert slip is not None and slip["n_trades"] >= kalshi_dev.MIN_ALIGNED_TRADES
    assert slip["entry_cents"] == 5.0  # demo ask 0.45 vs our 0.40 -> +5c worse


def test_quote_end_ts_exact_then_prior_within_interval():
    times = [100, 160, 280]  # a thin book that skipped the 220 slot
    assert kalshi_dev._quote_end_ts(times, 160, 60) == 160   # exact hit
    assert kalshi_dev._quote_end_ts(times, 220, 60) == 160   # gap -> prior within one interval
    assert kalshi_dev._quote_end_ts(times, 281, 60) == 280   # just after a candle
    assert kalshi_dev._quote_end_ts(times, 400, 60) is None  # too stale (> interval)
    assert kalshi_dev._quote_end_ts(times, 50, 60) is None   # before the first candle
    assert kalshi_dev._quote_end_ts([], 100, 60) is None     # no candles


def test_no_curve_when_demo_unconfigured(monkeypatch):
    monkeypatch.setattr(kalshi_dev, "KALSHI_DEV_API_BASE", "")
    assert kalshi_dev.dev_curve_for_strategy(1, {}, "btc15m") is None
    assert "KALSHI_DEV_API_BASE" in kalshi_dev.unavailable_reason()


def test_no_curve_when_demo_host_unreachable(monkeypatch):
    ds = _dataset()
    s = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})

    def boom(path, params, timeout=15):
        raise RuntimeError("demo host down")

    monkeypatch.setattr(kalshi_dev, "_dev_get", boom)
    assert kalshi_dev._compute(s, ds) is None


# -- pinned payload --------------------------------------------------------------------------------
# A realistic replay: a random-walk spot, two strikes per 15-minute window (more unseen contracts than
# MAX_CONTRACTS, so the cap applies), candles with gaps, and a thin demo book that skips periods, quotes
# a cent or two worse and errors on one contract. The page's bytes for it are pinned: a speed-up of the
# replay (fetching, caching) must answer exactly what it answered before.

def _pinned_dataset(windows=120):
    import random
    rng = random.Random(11)
    start = T0 - 7200
    spot, px = 100000.0, {}
    for i in range(windows * 15 + 121):
        spot = round(spot * (1 + rng.gauss(0, 0.0008)), 2)
        px[start + 60 * i] = spot
    btc = sorted(px.items())
    markets, candles = [], []
    for w in range(windows):
        open_ts = T0 + w * 900
        close = datetime.fromtimestamp(open_ts + 900, tz=timezone.utc)
        for j, off in enumerate((-40.0, 40.0)):
            strike = round(px[open_ts] + off, 2)
            ticker = "P%d-%d" % (w, j)
            markets.append({"ticker": ticker, "strike": strike, "close_time": close,
                            "result": "yes" if px[open_ts + 900] >= strike else "no"})
            for m in range(1, 15):
                if rng.random() < 0.1:
                    continue  # a missing candle
                ts = open_ts + 60 * m
                lean = (px[ts - 60] - strike) / 120.0
                mid = min(0.95, max(0.05, round(0.5 + lean + rng.gauss(0, 0.06), 2)))
                candles.append((ticker, ts, round(mid - 0.01, 2), round(mid + 0.01, 2)))
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


def _pinned_feed(ds, calls=None):
    by_ticker = {}
    for ts, snaps in ds.frames:
        for sn in snaps:
            by_ticker.setdefault(sn.contract.ticker, []).append((ts, sn.yes_bid, sn.yes_ask))

    def fake_get(path, params, timeout=15):
        ticker = path.split("/markets/")[1].split("/")[0]
        if calls is not None:
            calls.append(ticker)
        if ticker == "P100-1":
            raise RuntimeError("demo host hiccup")
        worse = 0.01 * (1 + int(ticker.split("-")[1]))
        return {"candlesticks": [
            {"end_period_ts": ts, "yes_bid": {"close_dollars": max(0.0, round(bid - worse, 2))},
             "yes_ask": {"close_dollars": min(0.99, round(ask + worse, 2))}}
            for k, (ts, bid, ask) in enumerate(by_ticker.get(ticker, []))
            if params["start_ts"] <= ts <= params["end_ts"] and k % 4 != 3]}

    return fake_get


PINNED_SPECS = (
    {"side": "either", "entry": {"min_edge": 0.03, "max_spread": 0.05}},
    {"side": "yes", "entry": {"min_edge": 0.02, "max_spread": 0.05},
     "exit": {"take_profit": 0.7, "stop_loss": 0.2}},
)
PINNED_SHA256 = (
    "30eca4c59f1055d40fc13807a7eefb7262aaa4ce0715bbbc7069b9600f53c21e",
    "2007398d9195dd2631af8a97ec8b9999b4e102a22307d7213340201624cb8937",
)


def _page_bytes(out):
    import json
    from app.web.http import _json_default
    return json.dumps(out, default=_json_default, separators=(",", ":")).encode("utf-8")


def _pinned_env(monkeypatch, ds, calls=None):
    monkeypatch.setattr(kalshi_dev, "MAX_CONTRACTS", 60)
    monkeypatch.setattr(kalshi_dev, "KALSHI_DEV_API_BASE", "http://demo.invalid")
    monkeypatch.setattr(kalshi_dev, "_dev_get", _pinned_feed(ds, calls))
    monkeypatch.setattr(kalshi_dev.backtest, "dataset", lambda market_key, history_days=None: ds)


def test_dev_curve_bytes_are_pinned(monkeypatch):
    import hashlib
    ds = _pinned_dataset()
    _pinned_env(monkeypatch, ds)
    for k, (raw, want) in enumerate(zip(PINNED_SPECS, PINNED_SHA256)):
        s = specmod.validate(dict(raw))
        out = kalshi_dev.dev_curve_for_strategy(-1000 - k, s, "btc15m")
        assert out is not None and out["capped"] is True and out["slippage"] is not None
        body = _page_bytes(out)
        assert hashlib.sha256(body).hexdigest() == want
        # The cached answer is the same bytes.
        assert _page_bytes(kalshi_dev.dev_curve_for_strategy(-1000 - k, s, "btc15m")) == body


def test_fetched_candles_serve_every_strategy_on_the_market(monkeypatch):
    ds = _pinned_dataset()
    calls = []
    _pinned_env(monkeypatch, ds, calls)
    a, b = (specmod.validate(dict(raw)) for raw in PINNED_SPECS)
    kalshi_dev.dev_curve_for_strategy(1, a, "btc15m")
    first = len(calls)
    assert first == 60  # one GET per contract, capped
    kalshi_dev.dev_curve_for_strategy(2, b, "btc15m")
    # The second strategy asks only for contracts the first didn't, plus the one that errored.
    again = calls[first:]
    assert "P100-1" in again and len(again) < first


def test_a_lapsed_replay_is_reused_while_the_history_is_the_same(monkeypatch):
    ds = _pinned_dataset()
    calls = []
    _pinned_env(monkeypatch, ds, calls)
    s = specmod.validate(dict(PINNED_SPECS[0]))
    computed = []
    real = kalshi_dev._compute
    monkeypatch.setattr(kalshi_dev, "_compute", lambda *a: computed.append(1) or real(*a))
    body = _page_bytes(kalshi_dev.dev_curve_for_strategy(7, s, "btc15m"))
    key = next(iter(kalshi_dev._cache))
    lapse = lambda: kalshi_dev._cache.__setitem__(key, (0.0,) + kalshi_dev._cache[key][1:])  # noqa: E731
    # One contract errored on the demo host, so the lapsed replay is worked out again...
    lapse()
    assert _page_bytes(kalshi_dev.dev_curve_for_strategy(7, s, "btc15m")) == body
    assert len(computed) == 2
    # ...and once every contract fetched, a lapsed replay on the same history answers from memory.
    kalshi_dev._cache[key] = kalshi_dev._cache[key][:3] + (True,)
    lapse()
    assert _page_bytes(kalshi_dev.dev_curve_for_strategy(7, s, "btc15m")) == body
    assert len(computed) == 2
    # Newer history is a new version: replayed.
    ds.end_ts += 60
    lapse()
    kalshi_dev.dev_curve_for_strategy(7, s, "btc15m")
    assert len(computed) == 3


def test_concurrent_requests_share_one_replay(monkeypatch):
    import threading
    ds = _pinned_dataset()
    _pinned_env(monkeypatch, ds)
    gate, computed = threading.Event(), []
    monkeypatch.setattr(kalshi_dev, "_compute",
                        lambda *a: computed.append(1) or gate.wait(5) and {"dev_curve": [[1, 0.0], [2, 1.0]]})
    s = specmod.validate(dict(PINNED_SPECS[0]))
    got = []
    threads = [threading.Thread(target=lambda: got.append(kalshi_dev.dev_curve_for_strategy(9, s, "btc15m")))
               for _ in range(3)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(5)
    assert len(computed) == 1 and len(got) == 3 and all(g == got[0] for g in got)


def test_warm_replays_passed_strategies_once_in_the_background(monkeypatch):
    from app.web.routes import strategies as routes
    ds = _pinned_dataset()
    _pinned_env(monkeypatch, ds)
    monkeypatch.setattr(kalshi_dev, "WARM", True)
    s = specmod.validate(dict(PINNED_SPECS[0]))
    oos = {"out_of_sample": {"trades": 12}}
    rows = [{"id": 31, "status": "passed", "market": "btc15m", "spec": s, "result": oos},
            {"id": 32, "status": "rejected", "market": "btc15m", "spec": s, "result": {}},
            {"id": 33, "status": "passed", "market": "btc15m", "spec": s, "result": {}}]  # nothing unseen
    started = []
    monkeypatch.setattr(kalshi_dev, "_warm_all", lambda todo: started.append([t[0] for t in todo]))
    routes.warm_dev_curves(rows)
    routes.warm_dev_curves(rows)  # the session page polls; each strategy is warmed once
    import time
    for _ in range(50):
        if started:
            break
        time.sleep(0.01)
    assert started == [[31]]
    monkeypatch.setattr(kalshi_dev, "WARM", False)
    kalshi_dev._warmed.clear()
    routes.warm_dev_curves(rows)
    time.sleep(0.05)
    assert started == [[31]]


# -- the page read never works the replay out on the request -----------------------------------------
# Measured 2026-10-28 on a seeded account (40 runs, 60 strategies, 6 paper deployments, 2,400 closed
# trades): the first GET /api/strategies/<id>/dev-curve took ~2.9s, all of it backtest.dataset on the
# request (the market's history from the DB, then the Deribit and Polymarket books listed and read from
# S3), before any demo candlestick GET. With the web server's kalshi_dev.start(), the read answers at
# once and one background worker replays.

PENDING = {"dev_curve": None, "pending": True,
           "reason": "Replaying the unseen window against Kalshi’s demo book; it shows here in a moment."}


def _route_bytes(monkeypatch, sid, spec):
    from app.web.routes import strategies as routes
    owned = {"id": sid, "spec": spec, "market": "btc15m", "result": {"out_of_sample": {"trades": 31}}}
    monkeypatch.setattr(routes, "_owned_strategy", lambda ctx: owned)
    return _page_bytes(routes.strategy_dev_curve(None))


def _join_worker():
    worker = kalshi_dev._BACKGROUND["worker"]
    if worker is not None:
        worker.join(10)
    assert kalshi_dev._BACKGROUND["worker"] is None and not kalshi_dev._queue


def test_the_page_read_answers_at_once_and_then_the_same_bytes_as_before(monkeypatch):
    import threading
    import time
    ds = _pinned_dataset()
    _pinned_env(monkeypatch, ds)
    specs = [specmod.validate(dict(raw)) for raw in PINNED_SPECS]
    # Before: worked out in the request (background off, as in tests and scripts).
    before = [_route_bytes(monkeypatch, -2000 - k, s) for k, s in enumerate(specs)]
    assert all(b'"dev_curve":[[' in b for b in before)
    with kalshi_dev._lock:
        kalshi_dev._cache.clear()
        kalshi_dev._candles.clear()
    # After: the market's history is slow to load; the read neither waits for it nor loads it itself.
    monkeypatch.setitem(kalshi_dev._BACKGROUND, "on", True)
    gate, loaded_on = threading.Event(), []

    def slow_dataset(market_key, history_days=None):
        loaded_on.append(threading.current_thread().name)
        gate.wait(10)
        return ds
    monkeypatch.setattr(kalshi_dev.backtest, "dataset", slow_dataset)
    for k, s in enumerate(specs):
        t = time.perf_counter()
        assert _route_bytes(monkeypatch, -2000 - k, s) == _page_bytes(PENDING)
        assert time.perf_counter() - t < 0.5
    assert _route_bytes(monkeypatch, -2000, specs[0]) == _page_bytes(PENDING)  # asked again: still one replay
    assert len(kalshi_dev._queued) == 2
    gate.set()
    _join_worker()
    assert loaded_on and set(loaded_on) == {"dev-curve-replay"}
    # Once worked out: the bytes the read always gave, for the same data.
    assert [_route_bytes(monkeypatch, -2000 - k, s) for k, s in enumerate(specs)] == before


def test_a_lapsed_replay_is_served_while_the_worker_replays_it(monkeypatch):
    ds = _pinned_dataset()
    _pinned_env(monkeypatch, ds)
    s = specmod.validate(dict(PINNED_SPECS[0]))
    before = _route_bytes(monkeypatch, 41, s)
    monkeypatch.setitem(kalshi_dev._BACKGROUND, "on", True)
    key = next(iter(kalshi_dev._cache))
    kalshi_dev._cache[key] = (0.0,) + kalshi_dev._cache[key][1:]
    computed = []
    real = kalshi_dev._compute
    monkeypatch.setattr(kalshi_dev, "_compute", lambda *a: computed.append(1) or real(*a))
    assert _route_bytes(monkeypatch, 41, s) == before  # served as kept, not replayed in the request
    _join_worker()
    assert len(computed) == 1  # one contract errored on the demo host, so the worker replayed it
    assert kalshi_dev._cache[key][0] > 0 and _route_bytes(monkeypatch, 41, s) == before


def test_without_demo_replay_set_up_the_read_says_so_at_once(monkeypatch):
    monkeypatch.setitem(kalshi_dev._BACKGROUND, "on", True)
    monkeypatch.setattr(kalshi_dev, "KALSHI_DEV_API_BASE", "")
    assert _route_bytes(monkeypatch, 43, specmod.validate(dict(PINNED_SPECS[0]))) == _page_bytes(
        {"dev_curve": None, "reason": "Kalshi demo replay isn’t available on this server."})
    assert kalshi_dev._BACKGROUND["worker"] is None and not kalshi_dev._queue
