"""The autopilot card's "Last move" (walked 2026-10-26 on a phone and a desktop, in both themes):

- The engine's own pause ("Paused deployment #12 automatically. Lost $12.00, ...") was not a move to
  last_autopilot_action, so the card showed an older deploy while the newest thing that happened was a
  pause. It is a move now, said with the strategy's name and book instead of the row number, and the
  guard that fired in words. The engine's text itself is unchanged (it is mapped on read).
- A strategy name with " — " in it ("Fade the late spike — Bitcoin 15m") was cut at its dash ("I left
  Fade the late spike."). The status read lists, as "titles", the names in the line that hold one, so
  the panel keeps each whole (tests/chat_panel_frontend_cases.mjs pins the panel side).
"""
from datetime import datetime

import pytest

from app.services import customer_text
from app.web.routes import chat as chat_routes

AT = datetime(2026, 10, 26, 21, 0, 0)
SPIKE = "Fade the late spike — Bitcoin 15m"


@pytest.mark.parametrize("why,dep,line", [
    ("Lost $12.00, more than the $10.00 guard (2x its worst backtest drawdown).", {"title": SPIKE, "mode": "paper"},
     "Paused your paper strategy %s automatically: it lost $12.00, more than its $10.00 loss guard." % SPIKE),
    ("force-closed: drawdown 26.0% >= limit 25.0%", {"title": "Rain", "mode": "demo"},
     "Paused your demo strategy Rain automatically: it was down 26.0% of its capital, past your 25.0% limit."),
    ("force-closed: drawdown 26.0% >= limit 25.0%; position down 45.0% >= stop 40.0% of cost", {"title": "Rain", "mode": "live"},
     "Paused your live strategy Rain automatically: it was down 26.0% of its capital, past your 25.0% limit and "
     "a position fell 45.0% below its cost, past your 40.0% stop."),
    ("Live is down $8.40 over its first 12 closed trades ($-0.70 a trade); its paper edge did not survive real execution.",
     {"title": "Rain", "mode": "live"},
     "Paused your live strategy Rain automatically: it is down $8.40 over its first 12 real-money trades."),
    # A reason not listed: the name and book alone, never the engine's own words.
    ("force-closed: something new", {"title": "Rain", "mode": "paper"}, "Paused your paper strategy Rain automatically."),
    # The deployment is gone: no number either.
    ("Lost $12.00, more than the $10.00 guard (2x its worst backtest drawdown).", {"title": None, "mode": None},
     "Paused one of your strategies automatically: it lost $12.00, more than its $10.00 loss guard."),
])
def test_the_engines_pause_reads_by_the_strategys_name_and_never_its_row_number(why, dep, line):
    text = customer_text.auto_pause_line("Paused deployment #12 automatically. " + why, dep)
    assert text == line
    assert "#12" not in text and "deployment" not in text
    assert customer_text.leaks(text) == []


def test_any_other_line_is_left_as_written():
    for text in ("Autopilot paused Rain: it hit its loss guard.", "Paused Rain.", "", None):
        assert customer_text.auto_pause_line(text, {"title": "x", "mode": "paper"}) == text


def _status_last_move(monkeypatch, row, deps):
    """chat._last_action and _last_move as autopilot_status calls them, the repo read stubbed."""
    chat_routes._LAST_ACTION.clear()
    monkeypatch.setattr(chat_routes.repo, "last_autopilot_action", lambda cur, uid: dict(row) if row else None)
    try:
        return chat_routes._last_move(chat_routes._last_action(None, 1, (3, 90)), deps)
    finally:
        chat_routes._LAST_ACTION.clear()


def test_the_last_move_is_the_engines_pause_by_name_with_the_names_the_panel_keeps_whole(monkeypatch):
    row = {"text": "Paused deployment #12 automatically. Lost $12.00, more than the $10.00 guard (2x its worst backtest drawdown).",
           "at": AT, "deployment": {"id": 12, "title": SPIKE, "mode": "paper"}}
    got = _status_last_move(monkeypatch, row, [{"id": 12, "title": SPIKE}, {"id": 13, "title": "Rain — v2"}])
    assert got == {"text": "Paused your paper strategy %s automatically: it lost $12.00, more than its $10.00 loss guard." % SPIKE,
                   "at": AT, "titles": [SPIKE]}  # only names the line holds; the deployment id never leaves


def test_a_line_naming_a_strategy_with_a_dash_carries_that_name_and_other_lines_keep_their_shape(monkeypatch):
    kept = ("I left %s running: it has been on paper for only 3.2 hours, and paper costs nothing while it builds the "
            "record the live gate needs (at least 24 hours before I pause it)." % SPIKE)
    deps = [{"id": 12, "title": SPIKE}, {"id": 14, "title": "Fade the late spike"}, {"id": 15, "title": None}]
    assert _status_last_move(monkeypatch, {"text": kept, "at": AT}, deps) == {"text": kept, "at": AT, "titles": [SPIKE]}
    plain = {"text": "Autopilot paused Rain: it hit its loss guard.", "at": AT}
    assert _status_last_move(monkeypatch, plain, deps) == plain  # no name with a dash: the same {text, at}
    assert _status_last_move(monkeypatch, None, deps) is None
    # The full status route, against MySQL: tests/test_autopilot_status_db.py ("the engine pauses a deployment").
