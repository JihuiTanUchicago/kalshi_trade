"""One long name and one short name per market, each from one source.

Walked 2026-10-31: one market read "BTC 15-min up/down" (the Research list, the session page), "Bitcoin 15-minute"
(the activity feed) and "Bitcoin up or down in 15 minutes" (the dashboard, Deploy). The long name is the market's
customer_label (app.trading.markets), which every server-written line says through markets.customer_name and the
pages read as the catalog's label (core.js mktLong); the short name is core.js MKT_SHORT (mktShort). A key either
side can't name reads "an unlisted market", never the raw key.
"""
import re
from pathlib import Path

from app import repository as repo
from app.services import customer_text
from app.services import markets as market_service
from app.trading import markets
from app.web.routes import chat as chat_routes

ROOT = Path(__file__).resolve().parents[1]

# The label each curated market had before #540 (git history of app/trading/markets.py), by key.
FORMER = {
    "Bitcoin 15-minute": "btc15m", "Bitcoin 15-minute, per-second data": "btc15m_tick", "Bitcoin daily close, 5pm EDT": "btc_daily",
    "Bitcoin perpetual (research only)": "btc_perp", "Ethereum 15-minute": "eth15m", "Ethereum daily close, 5pm EDT": "eth_daily",
    "Solana 15-minute": "sol15m", "Solana daily close, 5pm EDT": "sol_daily", "XRP 15-minute": "xrp15m",
    "XRP daily close, 5pm EDT": "xrp_daily", "Dogecoin 15-minute": "doge15m", "NEAR 15-minute": "near15m",
    "Zcash 15-minute": "zec15m", "Hyperliquid (HYPE) 15-minute": "hype15m",
}


def test_customer_name_is_the_long_name_and_never_a_raw_key():
    for key, m in markets.MARKETS.items():
        assert markets.customer_name(key) == m.customer_label
    assert markets.customer_name("kxgone") == "an unlisted market"
    assert markets.customer_name(None) == "an unlisted market"
    assert markets.customer_name("kxgone", "the market it picks") == "the market it picks"


def test_a_retired_label_reads_as_the_market_is_named_today():
    # Each former label maps to its market's customer_label, the one long name: the table can't drift from it.
    assert dict(customer_text.FORMER_LABELS) == {old: markets.MARKETS[k].customer_label for old, k in FORMER.items()}
    words = customer_text.ladder_words
    for old, key in FORMER.items():
        new = markets.MARKETS[key].customer_label
        assert words("Research started — preparing %s…" % old) == "Research started — preparing %s…" % new
        assert words("Loading %s market data…" % old) == "Loading %s market data…" % new
        assert words("Loaded 30 days of %s history: 16,800 decision points." % old) == \
            "Loaded 30 days of %s history: 16,800 decision points." % new
        assert words("Started a fresh research session on %s. Follow it." % old) == \
            "Started a fresh research session on %s. Follow it." % new
    # Prose that only uses the words keeps them; a current name is left as it is.
    for prose in ("Fade late takers on the Bitcoin 15-minute contracts", "Bitcoin 15-minutes", "Bitcoin up or down in 15 minutes."):
        assert words(prose) == prose


def test_every_feed_the_customer_reads_says_the_name_of_today():
    old = "Started a fresh research session on Bitcoin 15-minute. Follow it on the Research page."
    new = "Started a fresh research session on Bitcoin up or down in 15 minutes. Follow it on the Research page."
    assert customer_text.event_rows([{"kind": "step", "message": old, "data": {"note": old}}]) == \
        [{"kind": "step", "message": new, "data": {"note": new}}]
    assert customer_text.chat_rows([{"role": "system", "content": old}])[0]["content"] == new
    assert customer_text.notification_rows([{"kind": "deployed", "body": old}])[0]["body"] == new
    assert customer_text.run_rows([{"error": "Not enough market history collected yet for Bitcoin daily close, 5pm EDT."}])[0]["error"] == \
        "Not enough market history collected yet for Bitcoin above a set price at 5pm ET."
    assert chat_routes._last_move({"text": old, "at": "2026-10-31T00:00:00Z"}, [])["text"] == new


def test_the_seeded_example_names_its_market_by_its_long_name():
    class Rec:
        lastrowid, rows = 1, []

        def execute(self, sql, params=()):
            self.rows.append((sql, params))
            self.lastrowid += 1

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    cur = Rec()
    repo.seed_demo_session(cur, 7)
    lines = [p[2] for s, p in cur.rows if "app_agent_events" in s]
    assert lines[0] == "Loaded 30 days of %s history: 16,800 decision points." % markets.customer_name("btc15m")
    assert not any("15-minute" in line for line in lines)


def test_the_autopilot_names_a_market_it_cant_find_in_words(monkeypatch):
    pulse = {"research_live": [{"id": 1, "status": "queued", "market": "kxgone"}, {"id": 2, "status": "queued", "market": "high_ny"},
                               {"id": 3, "status": "queued", "market": None}],
             "tested_7d": 0, "passed_7d": 0, "runs_7d": 0, "researched": True}
    monkeypatch.setattr(chat_routes, "_week_not_cleared", lambda *a: 0)
    out = chat_routes._research_activity(None, 7, pulse=pulse, spent=0.0, exact=0.0)
    assert out["active"] == ["an unlisted market", markets.customer_name("high_ny"), "a market it’s still picking"]


def test_the_page_gets_a_long_name_for_every_market_its_list_leaves_out():
    listed = [{"key": k} for k in markets.MARKETS if k != "btc_perp"]
    assert market_service.unlisted_names(listed) == {"btc_perp": markets.MARKETS["btc_perp"].customer_label}
    assert market_service.unlisted_names([{"key": k} for k in markets.MARKETS]) == {}


def test_me_sends_the_long_names_of_markets_its_list_leaves_out(monkeypatch):
    from tests.test_app_frontend_contract import context
    from app import server
    monkeypatch.setattr(server.billing, "configured", lambda: False)
    for name in ("get_stripe_customer", "get_kalshi_key", "get_kalshi_dev_key"):
        monkeypatch.setattr(server.repo, name, lambda *a: None)
    monkeypatch.setattr(server.repo, "credit_balance", lambda *a: 10.0)
    monkeypatch.setattr(server.repo, "spot_symbols_with_data", lambda *a: set())
    monkeypatch.setattr(server.repo, "series_with_candles", lambda *a: set())
    data = server.me(context())
    listed = {m["key"] for m in data["markets"]}
    assert set(data["market_names"]) == set(markets.MARKETS) - listed
    for key, name in data["market_names"].items():
        assert name == markets.MARKETS[key].customer_label


def test_no_customer_line_falls_back_to_a_raw_market_key():
    # "customer_label if k in MARKETS else k" put the raw key in the line for a market the catalog dropped.
    rx = re.compile(r"customer_label if [^\n]+ in MARKETS else (?![\"'])")
    hits = [f"{p.relative_to(ROOT)}: {line.strip()}" for p in (ROOT / "app").rglob("*.py")
            for line in p.read_text().splitlines() if rx.search(line) and "FOCUS_WORDS" not in line]
    assert hits == []


def test_the_front_end_names_markets_only_through_the_core():
    # Both themes' marketShort and marketFull are the core's mktShort and mktLong; no bundle or page file reads
    # MKT_SHORT or the catalog's label for a market itself.
    for name in ("app.js", "app.meridian.js"):
        src = (ROOT / "app" / "static" / name).read_text()
        assert "  const marketShort = (k) => mktShort(k, S.me);\n" in src
        assert "  const marketFull = (k) => mktLong(k, S.me);\n" in src
        assert "MKT_SHORT" not in src and "marketLabel" not in src, name
        assert not re.search(r"\.find\(\(x\) => x\.key === k\)[^;]*\.label", src), name
    for p in (ROOT / "app" / "static").glob("*.js"):
        if p.name != "core.js":
            assert "MKT_SHORT" not in p.read_text() and "marketLabel" not in p.read_text(), p.name
    core = (ROOT / "app" / "static" / "core.js").read_text()
    assert "const mktLong = (k, me) => (!k ? NO_MARKET : mktCatalog(k, me) || MKT_SHORT[k] || UNLISTED_MARKET);" in core
    assert "const mktShort = (k, me) => (!k ? NO_MARKET : MKT_SHORT[k] || mktCatalog(k, me) || UNLISTED_MARKET);" in core
