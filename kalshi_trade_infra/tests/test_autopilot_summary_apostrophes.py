"""The autopilot panel's summary lines write an apostrophe curly, as the bundles do.

The panel mixed the server's straight apostrophes ("Right now it's researching", "live trading isn't open yet")
with the bundles' own curly ones ("Live trading isn’t open yet.", "Autopilot’s rule"), one line under another.
The server's summary lines (the story, its first line, the idle line and the lines they quote) now say them
curly, and words they quote from another module (the engine's entry scan, a stored pause reason) are curled on
the way out (customer_text.curly). A strategy's own title is the user's and is shown as they wrote it.
Untouched: the engine's text (app/trading/engine.py) and the money path's notification text.
"""
import ast
import pathlib
import re

import pytest

from app.services import customer_text
from app.web import views
from app.web.routes import chat

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
STRAIGHT = re.compile(r"[A-Za-z]'[A-Za-z]")

# Every function that writes a line of the panel's story or idle line (chat.autopilot_status), and the views
# helpers whose words those lines quote.
SUMMARY = {
    APP / "web" / "routes" / "chat.py": ("_research_activity", "_autopilot_story", "_autopilot_now", "_tournament_line",
                                         "_paused_lines", "_waiting_lines", "_stop_line", "_idle_reason", "_money"),
    APP / "web" / "views.py": ("_health_from", "_plain_pause_reason", "_pause_clause"),
}


def _literals(path, names):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            doc = ast.get_docstring(node, clean=False)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value != doc:
                    found.setdefault(node.name, []).append(sub.value)
    return found


@pytest.mark.parametrize("path", sorted(SUMMARY), ids=lambda p: p.name)
def test_no_summary_line_template_writes_a_straight_apostrophe(path):
    found = _literals(path, SUMMARY[path])
    assert set(found) == set(SUMMARY[path]), "a summary function was renamed: %s" % (set(SUMMARY[path]) - set(found))
    bad = [(name, s) for name, strings in found.items() for s in strings if STRAIGHT.search(s)]
    assert not bad, bad


def test_the_tournament_rewrite_writes_its_apostrophe_curly():
    for _rx, words in customer_text._TOURNAMENT_WORDS:
        assert not STRAIGHT.search(words), words


def _d(**kw):
    d = {"autopilot": True, "paper_running": 0, "demo_running": 0, "live_running": 0, "paper_open": 0,
         "paper_waiting": [], "research": {"active": []}, "focus": [], "billing_blocked": False}
    d.update(kw)
    return d


def _lines(d, paper_run=(), paused=(), age=20, passed=()):
    idle = chat._idle_reason(d, list(paper_run), list(paused), age, list(passed))
    return chat._autopilot_story(dict(d, idle=idle)) + ([idle["line"]] if idle else [])


# Payloads that walk the story's and the idle line's branches, every one with words the server wrote itself.
SCENARIOS = [
    _d(research={"active": ["a market it’s still picking"], "tested_7d": 12, "passed_7d": 1, "not_cleared_7d": 1,
                 "cost_7d": 2.5}),
    _d(research={"active": [], "tested_7d": 12, "passed_7d": 0, "not_cleared_7d": 2, "cost_7d": 0.0}),
    _d(research={"active": [], "tested_7d": 3, "passed_7d": 0, "not_cleared_7d": 0}, reviewing=True),
    _d(review_wait={"state": "running", "seconds": 900}),
    _d(review_wait={"state": "queued", "seconds": 900}),
    _d(live_running=2, live_enabled=False),
    _d(today_live_pnl=-60.5, daily_loss_limit=50),
    _d(paper_running=1, paper_progress={"title": "Fade tails", "trades": 4, "trades_needed": 30, "net_pnl": -1.2,
                                        "soonest_days": 6, "soonest_title": "Fade tails"},
       tournament={"entrants": 3, "trips": 12, "target": 400, "capital": 100.0, "cash_weight": 0.6,
                   "leader": {"strategy_id": 1, "title": "Fade tails", "weight": 0.2}}),
]


@pytest.mark.parametrize("d", SCENARIOS)
def test_the_story_says_its_own_words_with_curly_apostrophes(d):
    lines = _lines(d)
    assert lines
    for line in lines:
        assert not STRAIGHT.search(line), line


@pytest.mark.parametrize("age,paper_run,passed,paused", [
    (None, [{"id": 1, "title": "Fade tails", "scan": None}], [], []),  # the engine isn't running
    (20, [{"id": 1, "title": "Fade tails", "scan": None}], [], []),  # it hasn't had its first look
    (None, [], [{"id": 5, "title": "Rain", "market": "kxrainnyc", "in_focus": False, "candidate": False, "retired": False}], []),
    (None, [], [{"id": 5, "title": "Rain", "market": "kxrainnyc", "in_focus": True, "candidate": False, "retired": False}], []),
    (None, [], [], [{"title": "Rain", "status_reason": "Approved agent proposal"}]),
])
def test_the_idle_line_says_its_own_words_with_curly_apostrophes(age, paper_run, passed, paused):
    d = _d(paper_running=len(paper_run), focus=["sports"] if passed and not passed[0]["in_focus"] else [])
    idle = chat._idle_reason(d, paper_run, paused, age, passed)
    assert idle and not STRAIGHT.search(idle["line"]), idle


def test_words_a_line_quotes_from_the_engine_read_curly_and_a_title_reads_as_its_user_wrote_it():
    # spec.entry_scan's "<feature> isn't available right now" (trading code, stored as it is) beside the server's own.
    run = [{"id": 3, "title": "Todd's random walk", "last_scan_at": None,
            "scan": {"why": "yes_ask_depth isn't available right now", "entered": 0, "qualifying": 0}}]
    waiting = chat._paper_waiting(run)
    assert waiting[0]["why"] == "yes_ask_depth isn’t available right now"
    line = chat._waiting_lines(waiting)[0]
    assert line.startswith("Todd's random walk is waiting: Yes_ask_depth isn’t available right now.")
    idle = chat._idle_reason(_d(paper_running=1, paper_waiting=waiting), run, [], 20, [])
    assert "isn’t available" in idle["line"] and "Todd's random walk" in idle["line"]
    # A stored pause reason the panel quotes reads the same way.
    assert views._plain_pause_reason("Paused: the feed wasn't live") == "Paused: the feed wasn’t live"
    assert customer_text.curly("it's") == "it’s" and customer_text.curly("'quoted'") == "'quoted'"
    assert customer_text.curly(None) is None and customer_text.curly("") == ""
