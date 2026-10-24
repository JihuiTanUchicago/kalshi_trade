"""TCA reads the kernel's own report back off the order intent and prices every fill.

Rows are built by running the REAL kernel against a fake venue, so a change to what the kernel
records breaks these tests instead of silently blanking the cost numbers.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import tca
from data_pipeline.architecture.contracts import TradeIntent
from data_pipeline.architecture.execution_kernel import MarketableLimitKernel
from data_pipeline.common import utc_now
from data_pipeline.market_data import Quote

T0 = datetime(2026, 10, 24, 9, 0, 0)  # naive UTC, as stored


def _quote(bid, ask):
    return Quote(ticker="KXBTC15M-X-1", yes_bid=bid, yes_ask=ask, yes_bid_size=500.0, yes_ask_size=500.0,
                 as_of=utc_now(), source="websocket")


class _Feed:
    def __init__(self, q):
        self.q = q

    def quote(self, ticker, max_age_seconds=None):
        return self.q


def _venue(yes_fill):
    def submit(ticker, action, side, qty, price, client_order_id=None):
        return {"client_order_id": client_order_id, "resp": {
            "fill_count": "%d.00" % qty, "average_fill_price": "%.4f" % yes_fill,
            "average_fee_paid": "0.0170", "order_id": "o"}}
    return submit


def _intent_row(action, side, qty, decision, quote, yes_fill, fair=None, min_edge=None, booked=True):
    meta = {"client_order_id": "I"}
    if fair is not None:
        meta.update(fair=fair, min_edge=min_edge or 0.0)
    k = MarketableLimitKernel(_venue(yes_fill), _Feed(quote), entry_cross_ticks=1, max_entry_slippage=0.10)
    rep = k.execute(TradeIntent(action=action, side=side, ticker="KXBTC15M-X-1", qty_contracts=qty,
                                limit_price_dollars=decision, model_name="m", now_ts=None, metadata=meta))
    return {"intent_id": "I", "mode": "live", "action": action, "side": side, "ticker": "KXBTC15M-X-1",
            "qty": qty, "limit_price": decision, "created_at": T0,
            "status": "booked" if booked and rep.fill_qty_contracts else "unfilled",
            "fill_qty": rep.fill_qty_contracts, "fill_price": rep.fill_price_dollars, "fee": rep.fee_dollars,
            "raw_json": rep.raw_json}


def test_yes_buy_costs():
    row = _intent_row("buy", "yes", 10, decision=0.50, quote=_quote(0.50, 0.52), yes_fill=0.52,
                      fair=0.58, min_edge=0.01)
    r = tca.fill_costs(row)
    assert r["outcome"] == "filled" and r["filled"] == 10 and r["children_sent"] == 1
    assert r["slippage_vs_decision"] == pytest.approx(0.02)   # paid 52c vs a 50c decision
    assert r["cost_vs_arrival_mid"] == pytest.approx(0.01)    # half the 2c spread
    assert r["arrival_spread"] == pytest.approx(0.02)
    assert r["fee_per_contract"] == pytest.approx(0.017)
    assert r["edge_captured"] == pytest.approx(0.58 - 0.52 - 0.017)


def test_no_sell_is_priced_in_its_own_side_and_signed_as_a_sell():
    # Sell NO = buy YES on the wire. YES 0.60/0.62 => NO bid 0.38 / ask 0.40, mid 0.39.
    row = _intent_row("sell", "no", 5, decision=0.39, quote=_quote(0.60, 0.62), yes_fill=0.62)
    r = tca.fill_costs(row)
    assert r["fill_price"] == pytest.approx(0.38)              # 1 - 0.62
    assert r["slippage_vs_decision"] == pytest.approx(0.01)    # sold 1c below the decision
    assert r["cost_vs_arrival_mid"] == pytest.approx(0.01)
    assert r["edge_captured"] is None                          # only entries have one


def test_rejected_entry_keeps_its_reason_and_zero_fill():
    row = _intent_row("buy", "yes", 10, decision=0.50, quote=_quote(0.57, 0.58), yes_fill=0.58,
                      fair=0.60, min_edge=0.02, booked=False)
    r = tca.fill_costs(row)
    assert r["filled"] == 0 and r["outcome"] == "edge_gone_net"
    assert r["fill_price"] is None and r["slippage_vs_decision"] is None


def test_markouts_are_signed_so_positive_means_the_market_moved_our_way(monkeypatch):
    row = _intent_row("buy", "yes", 10, decision=0.50, quote=_quote(0.50, 0.52), yes_fill=0.52)
    later = {60: (0.55, 0.57), 300: (0.47, 0.49)}

    def quote_at(cur, ticker, ts, max_lag_seconds=30):
        h = int((ts - T0.replace(tzinfo=timezone.utc)).total_seconds())
        if h not in later:
            return None
        return {"yes_bid": later[h][0], "yes_ask": later[h][1], "at": ts}

    monkeypatch.setattr(tca.repo, "yes_quote_at", quote_at)
    r = tca.add_markouts(None, tca.fill_costs(row), horizons=(60, 300, 900))
    assert r["markout_60s"] == pytest.approx(0.56 - 0.52)
    assert r["markout_300s"] == pytest.approx(0.48 - 0.52)     # adverse: bought, then it fell
    assert r["markout_900s"] is None                           # no quote recorded


def test_summary_is_contract_weighted_and_counts_outcomes():
    a = tca.fill_costs(_intent_row("buy", "yes", 10, 0.50, _quote(0.50, 0.52), 0.52))
    b = tca.fill_costs(_intent_row("buy", "yes", 30, 0.50, _quote(0.50, 0.51), 0.51))
    c = tca.fill_costs(_intent_row("buy", "yes", 10, 0.50, _quote(0.57, 0.58), 0.58, fair=0.60,
                                   min_edge=0.02, booked=False))
    (g,) = tca.summarize([a, b, c], horizons=())
    assert g["orders"] == 3 and g["contracts_requested"] == 50 and g["contracts_filled"] == 40
    assert g["fill_rate"] == pytest.approx(0.8)
    assert g["slippage_vs_decision"] == pytest.approx((10 * 0.02 + 30 * 0.01) / 40, abs=1e-5)
    assert g["outcomes"] == {"filled": 2, "edge_gone_net": 1}


def test_report_reads_the_window_and_groups(monkeypatch):
    rows = [_intent_row("buy", "yes", 10, 0.50, _quote(0.50, 0.52), 0.52)]
    seen = {}

    def between(cur, since, until=None, modes=("live", "demo")):
        seen["since"], seen["until"] = since, until
        return rows

    monkeypatch.setattr(tca.repo, "order_intents_between", between)
    monkeypatch.setattr(tca.repo, "yes_quote_at", lambda *a, **k: None)
    now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    out = tca.report(None, days=2, now=now)
    assert seen["since"] == now - timedelta(days=2) and seen["until"] == now
    assert out["orders"] == 1 and out["groups"][0]["series"] == "KXBTC15M"
