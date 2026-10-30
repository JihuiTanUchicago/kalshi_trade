"""No customer ever reads a market label's strike placeholder ("$X").

Walked 2026-10-30: a market page's main button read "Research BTC above $X at 5pm ET" and Explore's chips
"BTC ABOVE $X AT 5PM ET": the 5pm ladders' family label ("Bitcoin above $X at 5pm ET") reached the page as
written. The label keeps "$X" for the research model (its market list and the reply it matches); every
customer surface reads ``customer_label`` ("Bitcoin above a set price at 5pm ET"), both themes' chips say the
same words (the shared core's MKT_SHORT, core.js), and a contract's page fills its own strike in for them.
"""
import re
from pathlib import Path

import pytest

from app import server
from app.services import customer_text
from app.trading import markets
from app.trading.markets import MARKETS

PLACEHOLDER = re.compile(r"\$[A-Z]\b")
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _short_labels():
    src = (STATIC / "core.js").read_text()
    block = src[src.index("const MKT_SHORT = {"):]
    return src, dict(re.findall(r"(\w+): '([^']*)'", block[:block.index("};")]))


def test_no_market_reads_a_placeholder_to_a_customer():
    shown = {k: m.customer_label for k, m in MARKETS.items()}
    assert not {k: v for k, v in shown.items() if PLACEHOLDER.search(v)}, \
        "a customer-visible market label carries a strike placeholder like $X"
    # The ladders keep their meaning: the coin, "above" a strike, and the close.
    assert shown["btc_daily"] == "Bitcoin above a set price at 5pm ET"
    assert {MARKETS[k].customer_label for k in ("eth_daily", "sol_daily", "xrp_daily")} == {
        "Ethereum above a set price at 5pm ET", "Solana above a set price at 5pm ET", "XRP above a set price at 5pm ET"}


def test_the_research_model_still_reads_the_label_it_matches():
    # The model's market list and the pick it replies with (agent._pick_market's by_label) use the label as
    # before; only what a customer reads changed.
    assert MARKETS["btc_daily"].label == "Bitcoin above $X at 5pm ET"


def test_a_catalog_title_with_a_placeholder_reads_in_words():
    m = markets.market_from_series({"series_ticker": "KXNEWTHING", "title": "Nasdaq above $Y at close",
                                    "category": next(iter(markets.ALLOWED_CATEGORIES)),
                                    "frequency": next(iter(markets.RECURRING_FREQ)), "open_markets": 999})
    assert m is not None and m.label == "Nasdaq above $Y at close"
    assert m.customer_label == "Nasdaq above a set price at close", "a catalog placeholder never reaches a customer"


def test_the_market_list_the_pages_read_has_no_placeholder(fake_cursor):
    # /api/me's markets (S.me.markets): every page's market name, the research form's picker and chat's names.
    rows = server._researchable_markets(fake_cursor)
    assert rows and not [r["label"] for r in rows if PLACEHOLDER.search(r["label"])], \
        "the market list the pages read carries a strike placeholder like $X"
    assert {r["key"]: r["label"] for r in rows}["btc_daily"] == "Bitcoin above a set price at 5pm ET"


def test_no_chip_reads_a_placeholder_in_either_theme():
    src, short = _short_labels()
    assert short and not {k: v for k, v in short.items() if PLACEHOLDER.search(v)}, \
        "a market chip carries a strike placeholder like $X"
    # A contract fills its own strike in for the family's words (strikeIn): the core's pattern takes both the
    # server's words and the chip's, so a market page never falls back to the family words.
    words = re.search(r"const LADDER_WORDS = /([^/]+)/;", src).group(1)
    for text in (MARKETS["btc_daily"].customer_label, short["btc_daily"], short["xrp_daily"]):
        assert re.search(words, text), text


def test_an_older_research_log_line_reads_in_words():
    # A run's log lines written before 2026-10-30 named the ladder by its placeholder; the stored row is unchanged.
    events = customer_text.event_rows([
        {"kind": "step", "message": "Chose to research Bitcoin above $X at 5pm ET. It fits.",
         "data": {"label": "XRP above $X at 5pm ET"}},
        {"kind": "error", "message": "Not enough market history collected yet for Solana above $X at 5pm ET."}])
    assert [e["message"] for e in events] == [
        "Chose to research Bitcoin above a set price at 5pm ET. It fits.",
        "Not enough market history collected yet for Solana above a set price at 5pm ET."]
    assert events[0]["data"]["label"] == "XRP above a set price at 5pm ET"
    assert customer_text.run_rows([{"error": "No data for Bitcoin above $X at 5pm ET."}])[0]["error"] == \
        "No data for Bitcoin above a set price at 5pm ET."
