"""Cross-MARKET (relative value across DIFFERENT markets, e.g. BTC vs ETH) support — both the
research path and the synchronized LIVE feed.

Covers: the proposer can emit a valid 2-market cross spec and is told which markets it may pair;
a cross-market spec backtests end-to-end on a MERGED dataset; the synchronized tick builds one
combined frame from two markets and SKIPS the frame (no entry) when a leg is stale; cadence-
incompatible markets are rejected; cross_deploy_block allows a 2-market cross only when both legs
are deployable + cadence-compatible, and still refuses incompatible / non-deployable; single-
market and non-cross specs are unaffected.

No live DB — fakes + monkeypatch, the same pattern as test_cross_contract.py.
"""
from datetime import datetime, timezone

import pytest

from app import agent
from app import backtest
from app import engine
from app import spec as specmod
from app.markets import MARKETS, BtcSeries, Contract

T0 = 1_800_000_000 - 1_800_000_000 % 3600


# -- 1. proposer explores cross-MARKET pairs -----------------------------------


def test_proposer_is_offered_cadence_compatible_cross_market_legs():
    opt = agent._cross_market_options("btc_daily")
    # The daily-crypto peers (same 60-min cadence + 5pm close) are surfaced; btc15m (1-min) is not.
    assert "eth_daily" in opt and "sol_daily" in opt and "xrp_daily" in opt
    assert "btc15m" not in opt and "cross_sectional" in opt
    # A market with no cadence peer is simply not offered a cross leg (no crash, empty string).
    assert agent._cross_market_options("btc15m")  # eth15m/nba_game share (1-min, no-close) cadence


def test_proposer_can_emit_a_valid_two_market_cross_spec():
    check = agent._hypotheses_check("btc_daily", 4)
    out = check({"hypotheses": [{
        "title": "BTC/ETH basis dislocation",
        "thesis": "When ETH's daily ladder lags a BTC move, the relative mispricing reverts.",
        "spec": {"market": "btc_daily",
                 "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}},
    }]})
    spec = out[0]["spec"]
    assert specmod.is_cross_contract(spec)
    assert specmod.involved_markets(spec) == ["btc_daily", "eth_daily"]
    assert specmod.stream_key(spec) == "btc_daily+eth_daily"


# -- 2. a cross-market spec backtests through a MERGED dataset ------------------


def _leg_dataset(market_key, strike, result, n_events=12, minutes=60, bid=0.49, ask=0.51):
    """One market's dataset: spot flat at 100 so the model saturates — a 90-strike settles YES
    (long candidate) and a 110-strike settles NO (short/NO candidate). Series comes from the
    market, so two different markets give two distinct series (what cross_sectional needs)."""
    m = MARKETS[market_key]
    btc = [(T0 - 7200 + 60 * i, 100.0) for i in range(n_events * minutes + 200)]
    markets, candles = [], []
    for k in range(n_events):
        open_ts = T0 + k * minutes * 60
        close = datetime.fromtimestamp(open_ts + minutes * 60, tz=timezone.utc)
        ticker = "%s_%d_%d" % (market_key, k, int(strike))
        markets.append({"ticker": ticker, "strike": strike, "close_time": close, "result": result})
        for mm in range(1, minutes + 1):
            candles.append({"ticker": ticker, "end_period_ts": open_ts + mm * 60,
                            "yes_bid_close": bid, "yes_ask_close": ask})
    return backtest.build_dataset(m, markets, candles, btc)


def test_cross_market_spec_backtests_on_a_merged_dataset():
    btc = _leg_dataset("btc_daily", 90.0, "yes")    # underpriced YES -> long
    eth = _leg_dataset("eth_daily", 110.0, "no")    # overpriced YES -> short (buy NO)
    merged = backtest.merge_datasets([btc, eth], key="btc_daily+eth_daily")
    spec = specmod.validate({
        "market": "btc_daily",
        "entry": {"min_edge": 0.1, "max_spread": 0.05},
        "sizing": {"stake": 10.0, "max_positions": 1},
        "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]},
    })
    trades = backtest.simulate(spec, merged, merged.start_ts, merged.end_ts + 1)
    assert trades, "a cross-market pair should open on the merged frame"
    t = trades[0]
    assert t.side == "pair"
    assert "btc_daily" in t.ticker and "eth_daily" in t.ticker  # one leg from EACH market
    assert t.exit_price == 2.0 and t.pnl > 0                    # both legs resolve the model's way


# -- 3. synchronized live feed: one combined frame, skip when a leg is stale ---


def _quote(ticker, series, strike, close_ts, bid=0.49, ask=0.51):
    c = Contract(ticker, strike, datetime.fromtimestamp(close_ts, tz=timezone.utc), series=series)
    return engine.LiveQuote(c, bid, ask, 50.0, 50.0)


def _fresh_spot(now_ts):
    return BtcSeries([(now_ts - 60 * (150 - i), 100.0) for i in range(150)])


def _sources(now_ts, *, eth_stale=False):
    quotes = {
        "btc_daily": [_quote("BTCD_1", "KXBTCD", 90.0, now_ts + 3600)],
        "eth_daily": [_quote("ETHD_1", "KXETHD", 110.0, now_ts + 3600)],
    }

    def q(market):
        return quotes[market.key]

    def spot(market):
        if market.key == "eth_daily" and eth_stale:
            return None          # stale/missing spot on the second leg
        return _fresh_spot(now_ts)

    return engine.Sources(quotes=q, spot=spot)


def test_cross_frame_combines_both_markets_when_fresh():
    now_ts = T0 + 7200
    snaps, sizes = engine._cross_market_frame(["btc_daily", "eth_daily"], _sources(now_ts), now_ts)
    series = {s.contract.series for s in snaps}
    assert series == {"KXBTCD", "KXETHD"}            # BOTH markets present on the one frame
    assert sizes["BTCD_1"] == 50.0 and sizes["ETHD_1"] == 50.0


def test_cross_frame_is_skipped_when_one_leg_is_stale():
    now_ts = T0 + 7200
    assert engine._cross_market_frame(["btc_daily", "eth_daily"],
                                      _sources(now_ts, eth_stale=True), now_ts) is None


def test_synchronized_tick_skips_and_never_claims_when_a_leg_is_stale(monkeypatch):
    now_ts = T0 + 7200
    slot = now_ts - now_ts % MARKETS["btc_daily"].decision_seconds
    dep = {"id": 7, "user_id": 1, "mode": "paper", "market": "btc_daily",
           "last_decision_ts": slot - 1, "spec": None}
    claims, decides = [], []
    monkeypatch.setattr(engine.repo, "claim_decision", lambda cur, did, s: claims.append(did) or True)
    monkeypatch.setattr(engine, "decide", lambda *a, **k: decides.append(a))

    class _Conn:
        def cursor(self):
            return object()

    # Stale leg -> no frame -> nothing claimed, nothing decided (never leg into a stale market).
    n = engine._tick_cross_group(_Conn(), ["btc_daily", "eth_daily"], [dep],
                                 _sources(now_ts, eth_stale=True), now_ts)
    assert n == 0 and claims == [] and decides == []
    # Fresh legs -> the deployment claims its slot and decides on the combined frame.
    n = engine._tick_cross_group(_Conn(), ["btc_daily", "eth_daily"], [dep],
                                 _sources(now_ts), now_ts)
    assert n == 1 and claims == [7] and len(decides) == 1


# -- 4. cadence compatibility --------------------------------------------------


def test_cadence_incompatible_cross_market_pair_is_rejected_at_validation():
    with pytest.raises(specmod.SpecError, match="cadence"):
        specmod.validate({"market": "btc15m",
                          "cross": {"pairing": "cross_sectional", "legs": [{"market": "btc_daily"}]}})
    # A compatible daily/daily pair validates fine.
    assert specmod.validate({"market": "btc_daily",
                             "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}})


# -- 5. deploy gate: multi-market allowance is strictly conditioned -------------


def test_cross_deploy_block_allows_multi_market_only_when_deployable_and_compatible():
    ok = specmod.validate({"market": "btc_daily",
                           "cross": {"pairing": "cross_sectional", "legs": [{"market": "eth_daily"}]}})
    for mode in ("paper", "demo", "live"):
        assert engine.cross_deploy_block(ok, mode) is None


def test_cross_deploy_block_refuses_non_deployable_legs():
    # Two TAO markets share a cadence (60-min, no fixed close) but are research-only (not deployable).
    tao = specmod.validate({"market": "tao_sn64",
                            "cross": {"pairing": "cross_sectional", "legs": [{"market": "tao_sn19"}]}})
    for mode in ("paper", "demo", "live"):
        assert "research-only" in (engine.cross_deploy_block(tao, mode) or "")


def test_cross_deploy_block_refuses_incompatible_cadence_defensively():
    # A hand-built spec that bypassed validation: two deployable but cadence-incompatible markets.
    # The gate is the last line of defence and still refuses it.
    bad = {"market": "btc15m", "side": "either",
           "cross": {"pairing": "cross_sectional", "legs": [{"market": "btc_daily"}],
                     "relationship": "spread"}}
    assert "cadence" in (engine.cross_deploy_block(bad, "live") or "")


def test_single_market_and_plain_specs_unaffected():
    single = specmod.validate({"market": "btc_daily", "cross": {"pairing": "cross_strike", "legs": []}})
    plain = specmod.validate({"market": "btc_daily"})
    assert engine.cross_deploy_block(single, "paper") is None       # single-market cross: paper OK
    assert engine.cross_deploy_block(single, "live") is None         # single-market cross: live OK (legging-safe)
    assert engine.cross_deploy_block(plain, "live") is None         # non-cross: untouched
