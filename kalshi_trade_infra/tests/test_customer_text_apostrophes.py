"""Deploy's row lines, the chat's own lines and the API's refusals a customer reads write an apostrophe curly.

A sibling of test_autopilot_summary_apostrophes.py. Deploy's demo-copy rows said "Its paper deployment wasn't running"
under the bundles' curly "isn’t"; the chat's failed-turn line, its rate-limit refusal and the strategy, community,
account and Explore refusals were straight too, and so was Tau's Share note ("sharing can't be undone").
Untouched, on purpose: the engine's text (app/trading/engine.py), the money path's notification text, the live
switch's refusal, armed() confirms and the deploy handlers (app/web/routes/deployments.py). A strategy's own title
is the user's and reads as they wrote it.
"""
import ast
import pathlib
import re

import pytest

from app.services import customer_text
from app.web import views
from app.web.routes import chat

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "app"
STRAIGHT = re.compile(r"[A-Za-z]'[A-Za-z]")


def _strings(node, doc=None):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != doc]


def _functions(path, names):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: _strings(n, ast.get_docstring(n, clean=False)) for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name in names}


# Deploy's row lines: the demo-copy pause and the status line a row and its strategy page show.
ROW_LINES = ("_demo_copy_pause", "_status_why")


def test_deploy_row_lines_write_no_straight_apostrophe():
    found = _functions(APP / "web" / "views.py", ROW_LINES)
    assert set(found) == set(ROW_LINES), "a row-line function was renamed"
    bad = [(name, s) for name, strings in found.items() for s in strings if STRAIGHT.search(s)]
    assert not bad, bad


def test_deploy_row_lines_read_curly():
    from app.trading import demo_twins

    d = {"mode": "demo", "status": "paused", "status_reason": demo_twins.PAUSE_REASON, "strategy_id": 7}
    why, _ = views._demo_copy_pause(d, None)
    assert why == "Its paper deployment wasn’t running, so this demo copy paused with it"
    if demo_twins.DEMO_TWINS:
        why, _ = views._demo_copy_pause(d, {7: "running"})
        assert why == "Its paper deployment wasn’t running when this paused. It is now, so you can resume it"
    back = views._status_why({"status": "paused", "status_reason": views._DEMO_KEY_PAUSE}, demo_key_back=True)
    assert back == "Your Kalshi demo key wasn’t connected when it paused. It is now, so you can resume it"


# Every ApiError message these routes raise. KEEP: the live switch's refusal stays as it is.
API_ROUTES = ("chat.py", "strategies.py", "community.py", "account.py", "explore.py")
KEEP = {"Live trading isn't enabled on this server yet."}


def _api_errors(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "ApiError":
            out.extend(s for arg in n.args[1:] for s in _strings(arg))
    return out


@pytest.mark.parametrize("name", API_ROUTES)
def test_api_refusals_a_customer_reads_write_no_straight_apostrophe(name):
    msgs = _api_errors(APP / "web" / "routes" / name)
    assert msgs, name
    bad = [m for m in msgs if STRAIGHT.search(m) and m not in KEEP]
    assert not bad, bad


def test_the_chat_says_its_own_lines_curly_and_an_older_stored_line_still_ends_a_turn():
    assert chat.NO_ANSWER == customer_text.NO_ANSWER == "The agent hit an error and didn’t answer."
    assert customer_text.NO_ANSWER_LINE.startswith(customer_text.NO_ANSWER)
    assert not STRAIGHT.search(customer_text.NO_ANSWER_LINE)
    # The research agent writes the one wording; no copy of it, straight or curly, of its own.
    agent_src = (APP / "research" / "agent.py").read_text(encoding="utf-8")
    assert "customer_text.NO_ANSWER_LINE" in agent_src and "didn't answer" not in agent_src and "didn’t answer" not in agent_src
    old = "The agent hit an error and didn't answer. Send your message again, or try in a minute."
    rows = customer_text.chat_rows([{"role": "system", "content": old}, {"role": "user", "content": "it's me"}])
    assert rows[0]["content"] == customer_text.NO_ANSWER_LINE
    assert rows[1]["content"] == "it's me"  # the user's own words, as they wrote them
    for content in (old, customer_text.NO_ANSWER_LINE):
        assert chat._answer_line({"role": "system", "content": content})
    assert not chat._answer_line({"role": "system", "content": "Autopilot deployed Rain on paper."})


def test_the_strategy_pages_share_note_is_curly():
    tau = (APP / "static" / "app-strategies.js").read_text(encoding="utf-8")
    assert "sharing can’t be undone" in tau and "sharing can't be undone" not in tau
    for name in ("app-strategies.js", "app.meridian-strategies.js"):
        src = (APP / "static" / name).read_text(encoding="utf-8")
        assert 'aria-label="Friend’s email"' in src and "Friend's email" not in src
