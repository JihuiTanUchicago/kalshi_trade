"""What customers read outside the Dev Logs carries none of the internal detail tests/test_devlog.py keeps off that page:
the server's error and reason strings."""
import ast
import re
from pathlib import Path

import pytest

from app.adapters.kalshi import kalshi_dev
from app.research import agent
from app.services import customer_text
from app.web.routes import strategies
from tests.test_devlog import INTERNAL

ROOT = Path(__file__).resolve().parents[1]


def _internal(text):
    """The Dev Logs guard's kinds that ``text`` carries."""
    return [k for k, (pat, _) in INTERNAL.items() if re.search(pat, text, re.I if k.startswith("what Tau pays") else 0)]


# -- the server's error strings ---------------------------------------------------------------------------------------
# Every ApiError a route raises is the "error" a page shows in its toast or notice. The words written in the route
# itself say nothing internal. Allowed: admin.py (operator-only pages, behind is_admin), and the demo key form's
# example Key ID ("like a952bcbe-ec3b-4b5b-…"), which is the shape of what Kalshi shows the customer, not a commit.
ALLOWED_ROUTE_FILES = {"admin.py"}
ALLOWED_WORDS = re.compile(r"like a952bcbe-ec3b-4b5b-…")


def _route_errors():
    for path in sorted((ROOT / "app" / "web" / "routes").glob("*.py")):
        if path.name in ALLOWED_ROUTE_FILES:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ApiError" and len(node.args) > 1:
                words = " ".join(c.value for c in ast.walk(node.args[1]) if isinstance(c, ast.Constant) and isinstance(c.value, str))
                if words:
                    yield "%s:%d" % (path.name, node.lineno), ALLOWED_WORDS.sub("", words)


def test_route_error_strings_are_found():
    found = dict(_route_errors())
    assert len(found) > 50 and any("Pick a model from the list" in w for w in found.values())


def test_route_error_strings_carry_no_internal_detail():
    assert [(where, _internal(words)) for where, words in _route_errors() if _internal(words)] == []


# -- reasons a route passes on from below -----------------------------------------------------------------------------
# Walk 2026-10-27: starting research on Bitcoin perpetuals with its data closed answered "Kalshi perpetual research
# data is disabled; set TAU_KALSHI_PERPS_ENABLED=true." on the research form and in the autopilot's chat, and the
# Strategy page's demo replay read sent "Kalshi demo replay isn't configured on this server (set KALSHI_DEV_API_BASE)."

def test_closed_perps_research_says_so_without_the_setting(monkeypatch):
    monkeypatch.setenv("TAU_KALSHI_PERPS_ENABLED", "false")
    why = agent.research_unavailable_reason("btc_perp")
    assert why == "Bitcoin perpetuals research isn’t open on this server yet."
    assert _internal(why) == [] and customer_text.leaks(why) == []


def test_demo_replay_reason_never_names_the_setting(monkeypatch):
    owned = {"id": 42, "spec": {}, "market": "btc15m", "result": {"out_of_sample": {"trades": 31}}}
    monkeypatch.setattr(strategies, "_owned_strategy", lambda ctx: owned)
    monkeypatch.setattr(kalshi_dev, "dev_curve_for_strategy", lambda *a: None)
    monkeypatch.setattr(kalshi_dev, "KALSHI_DEV_API_BASE", "")
    assert "KALSHI_DEV_API_BASE" in kalshi_dev.unavailable_reason()  # the operator's log line keeps it
    unset = strategies.strategy_dev_curve(None)
    assert unset == {"dev_curve": None, "reason": "Kalshi demo replay isn’t available on this server."}
    monkeypatch.setattr(kalshi_dev, "KALSHI_DEV_API_BASE", "https://demo-api.kalshi.co/trade-api/v2")
    no_prices = strategies.strategy_dev_curve(None)["reason"]
    assert no_prices == "No Kalshi demo prices are available for this strategy’s unseen window yet."
    assert _internal(unset["reason"] + " " + no_prices) == []

