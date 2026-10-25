"""Arbitrary-quant code strategies: validated, backtested with the SAME fee/sizing/settlement
mechanics as a DSL spec, and judged by the SAME gatekeeper (no bypass). A code strategy that
the sandbox cannot run produces zero trades (fails the gate honestly). Code strategies are
research-only: they never reach the live/paper trading engine.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import agent, backtest, sandbox
from app import gatekeeper as gk
from app import spec as specmod
from app.gatekeeper import Classification, Prereg
from app.markets import MARKETS

from tests.test_gatekeeper import FakeRepo  # reuse the in-memory research_repository stand-in

# Running a code strategy needs a kernel confiner; without one the sandbox is default-deny and a
# code strategy simply produces no trades. Tests that need real trades are skipped if absent.
needs_confiner = pytest.mark.skipif(not sandbox.os_sandbox_available(),
                                    reason="no OS-level sandbox (sandbox-exec/bwrap/firejail) here")

T0 = 1_800_000_000 - 1_800_000_000 % 3600

# A code strategy equivalent to "buy every YES contract and hold to settlement": the simplest
# thing that proves the mechanics match the DSL path.
BUY_ALL = """
def signals(window):
    out = []
    for fr in window["frames"]:
        out.append([{"ticker": c["ticker"], "side": "yes", "score": 1.0} for c in fr["contracts"]])
    return out
"""


def _dataset(n=40, minutes=15, result="yes", ask=0.40, bid=0.38):
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n * minutes + 200)]
    markets, candles = [], []
    for k in range(n):
        o = T0 + k * minutes * 60
        close = datetime.fromtimestamp(o + minutes * 60, tz=timezone.utc)
        tk = "M%d" % k
        markets.append({"ticker": tk, "strike": 98.0, "close_time": close, "result": result})
        for m in range(1, minutes + 1):
            candles.append({"ticker": tk, "end_period_ts": o + m * 60,
                            "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(MARKETS["btc15m"], markets, candles, btc)


def _code_spec(code=BUY_ALL, stake=10.0, max_positions=1):
    return specmod.validate({"market": "btc15m", "code": code,
                             "sizing": {"stake": stake, "max_positions": max_positions}})


# -- validation ----------------------------------------------------------------


def test_code_spec_validates_to_minimal_shape():
    s = _code_spec()
    assert set(s) == {"market", "sizing", "code"}
    assert s["sizing"] == {"stake": 10.0, "max_positions": 1}


@pytest.mark.parametrize("raw", [
    {"market": "btc15m", "code": "def other(w): return []", "sizing": {"stake": 5, "max_positions": 1}},
    {"market": "btc15m", "code": "import os\ndef signals(w): return []", "sizing": {"stake": 5, "max_positions": 1}},
    {"market": "btc15m", "code": BUY_ALL, "sizing": {"stake": 9999, "max_positions": 1}},
    {"market": "nope", "code": BUY_ALL, "sizing": {"stake": 5, "max_positions": 1}},
    {"market": "btc15m", "code": BUY_ALL, "sizing": {"stake": 5, "max_positions": 1}, "entyr": {}},
])
def test_bad_code_spec_rejected(raw):
    with pytest.raises(specmod.SpecError):
        specmod.validate(raw)


# -- same mechanics as a DSL spec ---------------------------------------------


@needs_confiner
def test_code_strategy_backtests_with_same_fees_and_settlement():
    ds = _dataset()
    trades = backtest.simulate(_code_spec(), ds, ds.start_ts, ds.end_ts + 1)
    assert len(trades) == 40                       # one position per contract, max_positions=1
    t = trades[0]
    assert t.entry_price == 0.40 and t.qty == 25   # buys the ask, $10 / 0.40
    assert t.exit_price == 1.0 and t.reason == "settled"
    assert t.fees == 0.42                           # identical taker-fee rounding to the DSL path


@needs_confiner
def test_code_strategy_can_exit_when_it_stops_listing_a_contract():
    ds = _dataset()
    code = ("def signals(window):\n"
            "    out = []\n"
            "    for i, fr in enumerate(window['frames']):\n"
            "        if i == 0:\n"
            "            out.append([{'ticker': c['ticker'], 'side': 'yes'} for c in fr['contracts']])\n"
            "        else:\n"
            "            out.append([])\n"   # drop everything after the first frame -> sell at bid
            "    return out\n")
    trades = backtest.simulate(_code_spec(code=code), ds, ds.start_ts, ds.end_ts + 1)
    assert any(t.reason == "signal" for t in trades)  # at least one signal-driven exit at the bid


def test_sandbox_failure_yields_no_trades():
    ds = _dataset()
    spec = _code_spec(code="def signals(window):\n    return 1 / 0\n")
    assert backtest.simulate(spec, ds, ds.start_ts, ds.end_ts + 1) == []


# -- judged by the SAME gatekeeper (no bypass) --------------------------------


@pytest.fixture
def repo(monkeypatch):
    r = FakeRepo()
    monkeypatch.setattr(gk, "rr", r)
    return r


@needs_confiner
def test_code_strategy_flows_through_the_gatekeeper(repo):
    ds = _dataset()
    spec = _code_spec()
    # Pre-registration hashes the frozen spec (code included) as the experiment identity.
    eid = gk.preregister(None, Prereg(user_id=7, run_id=1, market="btc15m", spec=spec,
                                      economic_rationale="buy-all baseline"))
    finalist = {"spec": spec, "user_id": 7, "min_sample": 5, "market": "btc15m"}
    # The gatekeeper runs the REAL backtest.simulate (the code runs in the sandbox) on validation.
    out = gk.judge_validation(None, eid, finalist, ds)
    assert out["classification"] in {c.value for c in Classification}
    assert out["n_trades"] > 0
    row = repo.results_for_experiment(None, eid, "validation")[-1]
    assert row["phase"] == "validation" and row["n_trades"] == out["n_trades"]


def test_code_identity_is_the_code(repo):
    a = Prereg(user_id=1, run_id=1, market="btc15m", spec=_code_spec(), economic_rationale="m")
    b = Prereg(user_id=1, run_id=1, market="btc15m",
               spec=_code_spec(code=BUY_ALL + "\n# different"), economic_rationale="m")
    assert a.hypothesis_hash() != b.hypothesis_hash()  # a different body is a different experiment


# -- research-only: never deployed to the trading engine ----------------------


@pytest.mark.parametrize("kind", ["deploy", "deploy_live"])
def test_code_strategy_blocked_from_deployment(monkeypatch, kind):
    strat = {"id": 5, "status": "passed", "title": "Custom quant", "market": "btc15m",
             "spec": _code_spec()}
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: strat)
    msg, pid = agent.act(None, {"id": 7}, {"type": kind, "strategy_id": 5}, autopilot=True)
    assert pid is None and "research-only" in msg


def test_data_provenance_handles_a_code_spec():
    # _prereg records provenance for EVERY finalist, so features_used/data_sources_for must not
    # assume the DSL model/entry fields a code spec ({market, sizing, code}) does not have.
    spec = _code_spec()
    feats = specmod.features_used(spec)
    assert feats == sorted(specmod.FEATURES)  # a code strategy may read any exposed feature
    assert "model_features_1m" in specmod.data_sources_for(spec)


def test_an_empty_book_at_99c_never_fills(monkeypatch):
    """KXNFLRECYDSPROT quotes were mostly yes_bid=0 / yes_ask=0.99: a code strategy "bought" at 99c,
    which can't profit after the fee, and lost ~80c a trade at a ~1% win rate (run 2815). Entries at
    an ask above backtest.MAX_ENTRY_ASK are now unfillable; a real two-sided book still fills."""
    def buy_all(spec, ds, start_ts, end_ts):
        return {ts: {s.contract.ticker: ("yes", 1.0) for s in snaps} for ts, snaps in ds.frames}
    monkeypatch.setattr(backtest, "_code_book", buy_all)
    for fill_model in ("next_bar", "signal_bar"):
        monkeypatch.setattr(backtest, "FILL_MODEL", fill_model)
        empty = _dataset(result="no", ask=0.99, bid=0.0)
        assert backtest.simulate(_code_spec(), empty, empty.start_ts, empty.end_ts + 1) == []
        live = _dataset(result="no", ask=0.40, bid=0.38)
        assert backtest.simulate(_code_spec(), live, live.start_ts, live.end_ts + 1)
