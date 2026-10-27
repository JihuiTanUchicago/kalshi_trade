"""What a paper P&L says it includes (customer_text.PAPER_NET / PAPER_FILLS) is what a paper fill does.

A user deciding whether to take a strategy live judges it by its paper P&L, so every page that shows
one says it is after Kalshi fees and the spread, and the info bubble says how a paper fill is priced.
The words are pinned twice: to the fill model (a buy at the ask, a sell at the bid, Kalshi's taker
fee, only the size at the touch, $1 or $0 at settlement), so changing the fill model fails here until
the words change with it; and to both themes' bundles, so every page says the same thing.
"""
import re
from datetime import timedelta
from pathlib import Path

import pytest

from app.services import customer_text
from app.trading import track_record
from data_pipeline.architecture.simulated_venue import SimulatedVenue
from data_pipeline.common import utc_now
from data_pipeline.kalshi_fees import taker_fee_dollars
from data_pipeline.market_data import Quote

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
TICKER = "KXBTC15M-26OCT271315-15"


class _Feed:
    def __init__(self, q):
        self.q = q

    def quote(self, ticker, max_age_seconds=None):
        return self.q


def _venue(bid=0.40, ask=0.42, bid_size=50.0, ask_size=30.0):
    return SimulatedVenue(_Feed(Quote(ticker=TICKER, yes_bid=bid, yes_ask=ask, yes_bid_size=bid_size,
                                      yes_ask_size=ask_size, as_of=utc_now() - timedelta(seconds=0.5),
                                      source="websocket")))


def test_a_paper_buy_pays_the_ask_and_kalshis_taker_fee():
    resp = _venue()(TICKER, "buy", "yes", 20, 0.45)["resp"]  # a limit above the ask still pays the ask
    assert float(resp["average_fill_price"]) == pytest.approx(0.42)
    assert float(resp["average_fee_paid"]) * 20 == pytest.approx(taker_fee_dollars(20, 0.42))


def test_a_paper_sell_gets_the_bid_and_pays_the_fee():
    resp = _venue()(TICKER, "sell", "yes", 20, 0.30)["resp"]
    assert float(resp["average_fill_price"]) == pytest.approx(0.40)
    assert float(resp["average_fee_paid"]) * 20 == pytest.approx(taker_fee_dollars(20, 0.40))


def test_a_paper_fill_takes_only_the_size_at_the_touch():
    resp = _venue(ask_size=12.0)(TICKER, "buy", "yes", 20, 0.45)["resp"]
    assert resp["fill_count"] == "12.00"


def test_the_words_are_plain_and_say_fees_and_the_spread():
    assert customer_text.PAPER_NET == "after Kalshi fees and the spread"
    for text in (customer_text.PAPER_NET, customer_text.PAPER_FILLS):
        assert customer_text.leaks(text) == []
        assert "list price" not in text.lower()
    for said in ("buys at the ask", "sells at the bid", "trading fee on every fill", "settles at $1 or $0",
                 "live fills can come in slightly worse"):
        assert said in customer_text.PAPER_FILLS


def test_the_track_record_method_says_how_paper_fills():
    at = track_record.METHOD.index(customer_text.PAPER_FILLS)
    assert "Kalshi fees" in track_record.METHOD[at - 1]


@pytest.mark.parametrize("bundle", ["app.js", "app.meridian.js"])
def test_both_themes_carry_the_same_words(bundle):
    src = (STATIC / bundle).read_text(encoding="utf-8")
    assert "const PAPER_NET = '%s';" % customer_text.PAPER_NET in src
    assert "paperfills: ['Paper fills', '%s']," % customer_text.PAPER_FILLS in src
    share = re.search(r"const shared = \(\) => shareMap \|\| \(shareMap = new Proxy\(\{(.*?)\}", src, re.S).group(1)
    assert re.search(r"\bPAPER_NET\b", share)
    # Every paper headline: the dashboard's paper figure, Deploy's paper figure and rows, the track
    # record's paper tab, and the autopilot card's all-time and last-7-days paper P&L.
    assert src.count("${PAPER_NET}") >= 6


@pytest.mark.parametrize("page", ["app-strategies.js", "app.meridian-strategies.js"])
def test_the_strategy_page_says_it_beside_its_paper_record(page):
    src = (STATIC / page).read_text(encoding="utf-8")
    names = re.search(r"const \{(.*?)\} = T;", src, re.S).group(1)
    assert re.search(r"\bPAPER_NET\b", names) and re.search(r"\bglo\b", names)
    assert "mode === 'paper' ? `, ${PAPER_NET}${glo('paperfills')}`" in src  # Since deploying
    assert "name: 'Net, ' + PAPER_NET" in src  # Road to live
