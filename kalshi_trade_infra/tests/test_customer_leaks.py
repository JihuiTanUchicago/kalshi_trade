"""What customers read outside the Dev Logs carries none of the internal detail tests/test_devlog.py keeps off that page:
the server's error and reason strings, and the model names each Billing page derives on its own."""
import ast
import re
from pathlib import Path

import pytest

from app.adapters.kalshi import kalshi_dev
from app.adapters.llm import models_catalog as catalog
from app.research import agent
from app.services import customer_text
from app.web.routes import strategies
from tests.test_devlog import INTERNAL

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


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


# -- one model-label source -------------------------------------------------------------------------------------------
# Billing's ledger names a model from a memo alone in each bundle (MODEL_FAMILY and MODEL_ID in app-billing.js and
# app.meridian-billing.js), as the server's label_for_model_id and customer_text.MODEL_ID do. A family or a provider
# added on one side and not the other would show a raw id, or "AI model", on one Billing page.
BILLING = ["app-billing.js", "app.meridian-billing.js"]


def _js_families(src):
    body = re.search(r"const MODEL_FAMILY = \[(.*?)\];", src, re.S).group(1)
    return tuple(re.findall(r"\['(\w+)', '([^']+)'\]", body))


def _js_model_id(src):
    m = re.search(r"const MODEL_ID = /(.+)/([a-z]*);\n", src)
    return m.group(1), m.group(2)


@pytest.mark.parametrize("name", BILLING)
def test_billing_model_families_match_the_servers(name):
    assert _js_families((STATIC / name).read_text()) == catalog._FAMILY_LABELS


@pytest.mark.parametrize("name", BILLING)
def test_billing_model_id_pattern_matches_the_servers(name):
    source, flags = _js_model_id((STATIC / name).read_text())
    assert source == customer_text.MODEL_ID.pattern
    assert "i" in flags and customer_text.MODEL_ID.flags & re.I


def test_the_drift_check_reads_what_it_compares():
    src = (STATIC / BILLING[0]).read_text()
    assert ("opus", "Claude Opus") in _js_families(src)
    assert re.search(_js_model_id(src)[0], "us.anthropic.claude-opus-4-6-v1", re.I)
