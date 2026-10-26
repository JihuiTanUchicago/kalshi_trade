"""POST /api/strategies/:id/whatif for a spec stored without sizing (older or seeded rows). It used to
fail inside the backtest on spec["sizing"] and answer "Backtest data is not available right now."; it
now sizes the spec as validation sizes a new one (the $5 x 20 default the strategy page already shows),
and a spec with sizing gets exactly the result it got before. No DB: the strategy row, the measured
slippage and the dataset are stubbed (a synthetic btc15m dataset)."""
import copy
from types import SimpleNamespace

import pytest

from app import repository as repo
from app import server  # what_if: server re-imports it once it moves to app.web.routes
from app.web.http import ApiError, Ctx
from app.adapters.kalshi import kalshi_dev
from app.trading import backtest
from app.trading import spec as specmod
from tests.test_loop_backtest_parity import _random_dataset

SID, UID = 41, 7
RAW = {"side": "either", "entry": {"min_edge": 0.03}, "exit": {"take_profit": 0.15}}
KEYS = ("in_sample", "out_of_sample", "equity", "gates", "passed", "capital")


@pytest.fixture
def world(monkeypatch):
    ds = _random_dataset(3)
    row = {"id": SID, "market": "btc15m", "status": "passed", "spec": None}
    monkeypatch.setattr(repo, "get_strategy", lambda cur, uid, sid: row if (uid, sid) == (UID, SID) else None)
    monkeypatch.setattr(kalshi_dev, "measured_slippage_cents", lambda market: None)
    monkeypatch.setattr(backtest, "dataset", lambda market: ds)
    return SimpleNamespace(row=row, ds=ds)


def _what_if(body):
    conn = SimpleNamespace(cursor=lambda: object())
    return server.what_if(Ctx(conn, {"id": UID}, (str(SID),), {}, body, None))


def _expected(spec, ds, stake):
    res = backtest.evaluate(spec, ds, backtest.WhatIf(fee_multiplier=1.0, slippage_cents=0.0, stake=stake))
    return {k: res[k] for k in KEYS}


def test_a_spec_without_sizing_is_sized_at_the_default_not_refused_as_missing_data(world):
    full = specmod.validate(copy.deepcopy(RAW))
    assert full["sizing"] == specmod.DEFAULT_SPEC["sizing"] == {"stake": 5.0, "max_positions": 20}
    stored = {k: v for k, v in full.items() if k != "sizing"}
    world.row["spec"] = stored
    with pytest.raises(KeyError):  # what the backtest did with it before
        backtest.evaluate(stored, world.ds, backtest.WhatIf(stake=10.0))
    # A stake sent (an API client; older pages sent their dial's) over the default 20 positions...
    out = _what_if({"fee_multiplier": 1.0, "slippage_cents": 0.0, "stake": 10})
    assert out == _expected(full, world.ds, 10.0) and out["capital"] == 200.0
    # ...and no stake sent, as the strategy page does for a strategy without one: the default $5.
    out = _what_if({})
    assert out == _expected(full, world.ds, 5.0) and out["capital"] == 100.0
    assert "sizing" not in world.row["spec"]  # the stored row is not changed
    # Part of a sizing: the rest comes from the default.
    world.row["spec"] = {**stored, "sizing": {"stake": 8.0}}
    assert _what_if({})["capital"] == 160.0


def test_a_spec_with_sizing_gets_the_same_result_as_before(world, monkeypatch):
    sized = specmod.validate({**copy.deepcopy(RAW), "sizing": {"stake": 25.0, "max_positions": 3}})
    world.row["spec"] = sized
    seen = []
    real = backtest.evaluate
    monkeypatch.setattr(backtest, "evaluate", lambda spec, ds, w: seen.append((spec, w)) or real(spec, ds, w))
    assert _what_if({}) == _expected(sized, world.ds, 25.0)
    assert seen[0][0] is sized and seen[0][1].stake == 25.0  # the stored spec itself, its own stake
    assert _what_if({"stake": 40, "fee_multiplier": 2.0})["capital"] == 120.0


def test_a_real_data_failure_still_says_the_data_is_unavailable(world, monkeypatch):
    world.row["spec"] = specmod.validate(copy.deepcopy(RAW))
    monkeypatch.setattr(backtest, "dataset", lambda market: (_ for _ in ()).throw(RuntimeError("db gone")))
    with pytest.raises(ApiError) as e:
        _what_if({})
    assert e.value.status == 503 and str(e.value) == "Backtest data is not available right now."
