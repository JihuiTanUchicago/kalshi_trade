"""End-to-end power check of the research gate: a planted edge run through the REAL backtest
(next-bar fills, fees, reservation price) and the REAL gatekeeper statistics must pass, and a
fairly-priced market must not. The placebo bug that silently rejected every edge for weeks lived
between these layers, where unit tests of each piece could not see it."""
import random
from datetime import datetime, timezone

from app import backtest
from app import gatekeeper as gk
from app import spec as specmod
from app import stats
from app.markets import MARKETS

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def _market(p_yes, n_contracts=400, minutes=15, ask=0.40, bid=0.38, seed=0):
    """Back-to-back 15-minute contracts quoted at a flat 38/40 book that settle YES with
    probability p_yes. Spot sits above every strike, so the GBM fair value says buy YES each time."""
    rng = random.Random(seed)
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n_contracts * minutes + 200)]
    markets, candles = [], []
    for k in range(n_contracts):
        open_ts = T0 + k * minutes * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        ticker = "M%d" % k
        markets.append({"ticker": ticker, "strike": 98.0, "close_time": close,
                        "result": "yes" if rng.random() < p_yes else "no"})
        for m in range(1, minutes + 1):
            candles.append({"ticker": ticker, "end_period_ts": open_ts + m * 60,
                            "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


_SPEC = specmod.validate({"market": "btc15m", "side": "yes", "entry": {"min_edge": 0.1},
                          "sizing": {"stake": 10.0, "max_positions": 1}})


def _verdict(ds, seed):
    trades = backtest.simulate(_SPEC, ds, ds.start_ts, ds.end_ts + 1)
    v = gk._compute(trades, 1, stats.lord_init(gk.ALPHA), seed=seed)
    v.update(gk._cost_stress(_SPEC, ds, trades))
    cls = gk._classify(v["lord_reject"], None, v["dsr"], v["ci_lo"], v["ci_hi"], v["placebo_passed"],
                       v["cross_day_ok"], v["cost_stress_ok"])
    return cls, v


def test_planted_edge_passes_the_full_gate():
    """YES priced at 40c that settles 55% of the time: a 15c edge before the ~1.7c fee."""
    passed = 0
    for s in range(3):
        cls, v = _verdict(_market(0.55, seed=s), seed=s)
        assert v["n_trades"] > 300 and v["cost_stress_ok"]
        passed += cls == gk.Classification.STAT_SUPPORTED
    assert passed == 3


def test_fairly_priced_market_does_not_pass():
    """YES priced at 40c that settles 40% of the time: no edge, and the fee makes it negative."""
    for s in range(3):
        cls, _v = _verdict(_market(0.40, seed=100 + s), seed=s)
        assert cls != gk.Classification.STAT_SUPPORTED
