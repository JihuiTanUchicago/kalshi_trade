"""The research market picker's two backend contracts:

1. Each market self-categorises (Crypto / Sports / Bittensor) from its own fields,
   so the SPA can group the picker without any extra per-market metadata.
2. Dormant markets are hidden: a research-only spot market (TAO subnet alpha) must
   not appear until its taostats feed has actually written candles. This is the
   gate that keeps the Bittensor markets out of the picker until they're usable.
"""
import pytest

from app import agent
from app import repository as repo
from app import server
from app.llm import LLMError, Usage
from app.markets import MARKETS


def _insert_spot(cur, symbol, ts=1_800_000_000):
    cur.execute("INSERT INTO spot_candles_1m (symbol, start_ts, open, high, low, close, volume) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)", (symbol, ts, 1.0, 1.0, 1.0, 1.0, 1.0))


def test_category_is_derived_from_market_fields():
    assert MARKETS["btc15m"].category == "Crypto"
    assert MARKETS["eth_daily"].category == "Crypto"
    assert MARKETS["nba_game"].category == "Sports"       # binary, no underlying price
    assert MARKETS["tao_sn64"].category == "Bittensor"    # kind == "spot"


def test_spot_market_hidden_until_it_has_candles(fake_cursor):
    # No spot candles collected yet: every spot (TAO) market is gated out.
    shown = {m["key"] for m in server._researchable_markets(fake_cursor)}
    assert "btc15m" in shown and "nba_game" in shown
    assert not any(k.startswith("tao_") for k in shown)

    # The taostats feed writes SN64's price series: only SN64 becomes researchable.
    _insert_spot(fake_cursor, "TAO-SN64")
    shown = {m["key"] for m in server._researchable_markets(fake_cursor)}
    assert "tao_sn64" in shown
    assert "tao_sn19" not in shown  # still no data for the others


def test_spot_symbols_with_data_empty_input_runs_no_query(fake_cursor):
    # Guard the short-circuit: an empty symbol set must not build a bare `IN ()` query.
    fake_cursor._last = ["sentinel"]
    assert repo.spot_symbols_with_data(fake_cursor, []) == set()
    assert fake_cursor._last == ["sentinel"]  # execute() was never called


# -- the autopilot's OWN market pick is steered to data-ready markets (proactive, not reactive) ----

def test_researchable_keys_returns_only_data_ready(monkeypatch):
    monkeypatch.setattr(server, "_researchable_markets",
                        lambda cur: [{"key": "btc15m", "has_data": True},
                                     {"key": "nba_game", "has_data": False}])
    assert agent._researchable_keys(None) == ["btc15m"]


def test_researchable_keys_fail_open_when_nothing_ready(monkeypatch):
    # A cold/edge DB where nothing reads as ready must NOT block research — offer the whole universe.
    monkeypatch.setattr(server, "_researchable_markets",
                        lambda cur: [{"key": "btc15m", "has_data": False}])
    assert agent._researchable_keys(None) == list(MARKETS)


def test_pick_market_offers_only_the_data_ready_keys():
    seen = {}
    def model(system, messages, on_delta=None):
        seen["msg"] = messages[-1]["content"]
        return '{"market": "eth_daily", "why": "has data"}', {"input_tokens": 1, "output_tokens": 1}
    picked = agent._pick_market({"prompt": "mean reversion"}, model, Usage(),
                                lambda *a, **k: None, ["btc15m", "eth_daily"])
    assert picked == "eth_daily"
    assert "btc15m" in seen["msg"] and "eth_daily" in seen["msg"]
    assert "nba_game" not in seen["msg"]            # a data-less market is never even offered


def test_pick_market_rejects_a_pick_outside_the_offered_keys():
    def model(system, messages, on_delta=None):     # agent keeps naming a market not on offer
        return '{"market": "nba_game", "why": "no data"}', {"input_tokens": 1, "output_tokens": 1}
    with pytest.raises(LLMError):
        agent._pick_market({"prompt": "x"}, model, Usage(), lambda *a, **k: None, ["btc15m"])
