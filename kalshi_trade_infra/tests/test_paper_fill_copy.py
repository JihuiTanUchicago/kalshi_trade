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

from app.research import agent
from app.services import backtest_check, customer_text
from app.trading import track_record
from app.web.routes import chat
from data_pipeline.architecture.simulated_venue import SimulatedVenue
from data_pipeline.common import utc_now
from data_pipeline.kalshi_fees import taker_fee_dollars
from data_pipeline.market_data import Quote
from trading_core.domain.slippage import per_fill_cents

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
    assert customer_text.PAPER_NET_SHORT == "net of fees and spread"
    for text in (customer_text.PAPER_NET, customer_text.PAPER_NET_SHORT, customer_text.PAPER_FILLS):
        assert customer_text.leaks(text) == []
        assert "list price" not in text.lower()
    for said in ("buys at the ask", "sells at the bid", "trading fee on every fill", "settles at $1 or $0",
                 "price moving in the second or two before a real order lands"):
        assert said in customer_text.PAPER_FILLS
    # What it leaves out is named once, by the estimate beside paper P&L, with the assumption the server uses
    # (it said "live fills can come in slightly worse" before the estimate existed).
    assert "slightly worse" not in customer_text.PAPER_FILLS
    assert ("an estimate after typical live slippage, it takes %s¢ a contract off each time an order fills"
            % format(per_fill_cents(), "g")) in customer_text.PAPER_FILLS


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
    # Every paper headline: the dashboard's paper figure, Deploy's paper figure (or, on a board led by
    # live money, its paper amount), the track record's paper tab, the autopilot card's all-time and
    # last-7-days paper P&L, and the paper book of "Since your last visit" (live and demo say nothing of
    # the kind). Deploy's rows don't repeat it under the headline that says it: a row's backtest line
    # says the short form beside its own per-trade paper figure (tests/deploy_errors_frontend_cases.mjs).
    assert src.count("${PAPER_NET}") >= 7
    assert "m === 'live' ? ' (real money)' : m === 'paper' ? `, ${PAPER_NET}` : ''" in src


# The server writes these lines whole, so they carry the short form (PAPER_NET_SHORT) inside the sentence.
_BT = {"source": "out_of_sample", "trades": 40, "per_trade": 0.15, "win_rate": 0.61, "stake": 5.0}
_STATS = {"trades": 20, "pnl": 2.4, "pnl_sq": 20 * 0.5 ** 2, "wins": 10, "cost": 100.0}


def test_the_deploy_rows_backtest_comparison_says_it_for_paper_only():
    paper = backtest_check.book_check("paper", _STATS, _BT)["line"]
    assert "+$0.12/trade %s vs backtest" % customer_text.PAPER_NET_SHORT in paper
    for mode in ("live", "demo"):
        assert customer_text.PAPER_NET_SHORT not in backtest_check.book_check(mode, _STATS, _BT)["line"]
    # Too early to compare: the line quotes no figure, so it says nothing about one.
    early = backtest_check.book_check("paper", dict(_STATS, trades=3), _BT)["line"]
    assert customer_text.PAPER_NET_SHORT not in early


def test_the_autopilot_panel_says_it_beside_its_paper_figures():
    d = {"autopilot": True, "paper_running": 1, "live_running": 0,
         "paper_progress": {"trades": 4, "trades_needed": 30, "net_pnl": 1.2},
         "research": {"active": [], "tested_7d": 0, "passed_7d": 0}}
    assert any("is up $1.20 on them %s, across all its paper runs" % customer_text.PAPER_NET_SHORT in line
               for line in chat._autopilot_story(d))
    paused = [{"title": "Fade", "trades": 2, "pnl": -0.8, "why": "its loss guard fired"}]
    assert chat._paused_lines(paused) == ["Fade was paused after 2 paper trades (down $0.80 %s): its loss guard fired."
                                          % customer_text.PAPER_NET_SHORT]


def test_the_autopilots_chat_lines_say_it_beside_paper_net(monkeypatch):
    # The live-ready line in chat (and its email), which the review's own context reads too.
    ev = {"trades": 30, "trades_needed": 30, "net_pnl": 4.2, "span_hours": 48.0, "ready": True}
    line = agent.paper_evidence_line(ev)
    assert "30/30 realistic paper trades; $4.20 %s; 48h of record" % customer_text.PAPER_NET_SHORT in line
    # A review that tried to pause a young tournament entrant.
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: False)
    monkeypatch.setattr(agent.repo, "paper_round_trips", lambda cur, uid, sid: [])
    monkeypatch.setattr(agent, "_trip_events", lambda trips: [0.5, 0.7])
    held = agent._tournament_hold(None, 1, {"strategy_id": 7, "title": "Tails"})
    assert "independent events ($1.20 %s)" % customer_text.PAPER_NET_SHORT in held


@pytest.mark.parametrize("page", ["app-strategies.js", "app.meridian-strategies.js"])
def test_the_strategy_page_says_it_beside_its_paper_record(page):
    src = (STATIC / page).read_text(encoding="utf-8")
    names = re.search(r"const \{(.*?)\} = T;", src, re.S).group(1)
    assert re.search(r"\bPAPER_NET\b", names) and re.search(r"\bglo\b", names)
    # Since deploying: each book's line says what its P&L is net of, paper's in PAPER_NET's words with its bubble.
    assert "paper: PAPER_NET };" in src and ", ${BOOK_NET[mode]}` : 'No closed trades yet'" in src
    # Its bubble follows on paper, glued to the last word and the "·" after it (gloSep) when more of the line follows.
    assert "n && mode === 'paper' ? (tail ? gloSep('paperfills', head) : head + glo('paperfills'))" in src
    assert "name: 'Net, ' + PAPER_NET" in src  # Road to live
