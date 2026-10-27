"""services.gate_explain.step_note: the research agent's step lines, written for the ledger ("Froze 2
finalists; the challenger reviewed each before any validation budget was spent."), as the run page says
them. The stored message is never changed (the page finds the out-of-credits line by its words)."""
import re
from pathlib import Path

import pytest

from app.adapters.db.agent_run_repository import OUT_OF_CREDITS_STEP
from app.services import gate_explain as ge
from app.web.views import _with_gate_lines

# The agent's step lines as agent.py formats them today, and what the run page says in their place.
STEP_LINES = [
    ("Plan: explore up to 6 hypotheses, refining each round on the in-sample results, then gate the best on data never seen.",
     "Plan: try up to 6 ideas, sharpen each one on past data, then test the best on data it hasn't seen."),
    ("Plan: explore hypotheses until you stop it, refining each round on the in-sample results, then gate the best on "
     "data never seen. I'll keep going until you stop me.",
     "Plan: try ideas until you stop it, sharpen each one on past data, then test the best on data it hasn't seen."),
    ("Proposing round 2 — generating up to 1 hypothesis…", "Round 2: coming up with up to 1 idea…"),
    ("Proposing round 1 — generating up to 3 hypotheses…", "Round 1: coming up with up to 3 ideas…"),
    ("Resuming round 3 with 2 proposed hypotheses not yet developed.",
     "Round 3, picking up where it left off: 2 ideas still to work out."),
    ("Froze 1 finalist; the challenger reviewed each before any validation budget was spent.",
     "Picked 1 idea to test on data it hasn't seen; a skeptical reviewer read it first."),
    ("Froze 3 finalists; the challenger reviewed each before any validation budget was spent.",
     "Picked the best 3 ideas to test on data it hasn't seen; a skeptical reviewer read each one first."),
    ("Challenger unavailable; approving finalists as-is — the gatekeeper still gates.",
     "The skeptical review couldn't run this time, so the picked ideas go straight to the test on data it hasn't "
     "seen, which still decides."),
    ("Still running - 8 tested so far, 1 passed. Exploring more (stop anytime).",
     "8 tested so far, 1 passed. Looking for more; you can stop it anytime."),
    ("Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching.",
     "Out of credits, so the session stopped here. Add credits (or turn on auto-reload), then start a new session "
     "to keep researching."),
    ("Resuming — re-using 4 explored hypotheses, preparing Bitcoin 15-minute…",
     "Picking up where it left off, keeping the 4 ideas it had explored; preparing Bitcoin 15-minute…"),
    ("Last 5 theses all dropped on the research fold. Stopping proposals; 0 kept go to the gate.",
     "The last 5 ideas all fell apart on past data, so it stopped coming up with more. None go on to the test."),
    ("The proposer keeps returning mechanisms the sibling markets already killed. Stopping proposals; 2 kept go to the gate.",
     "Its new ideas kept repeating ones that already failed on similar markets, so it stopped coming up with more. "
     "2 ideas go on to the test."),
    ("No tradeable surface after 18 attempts — stopping to free the worker.",
     "After 18 attempts, nothing here traded often enough to test, so it stopped."),
]
JARGON = re.compile(r"hypothes|finalist|in-sample|\bgate|validation budget|research fold|challenger", re.I)


@pytest.mark.parametrize("message,said", STEP_LINES)
def test_a_step_line_written_for_the_ledger_reads_plainly(message, said):
    assert ge.step_note("step", message) == said
    assert not JARGON.search(said)


def test_the_notes_follow_the_words_agent_py_writes():
    # Each line's fixed words still appear in the agent's source: a reworded line fails here instead of
    # quietly keeping its ledger words on the page.
    src = (Path(ge.__file__).parents[1] / "research" / "agent.py").read_text(encoding="utf-8")
    for stem in ("Plan: explore %s, refining each round on the in-sample results, then gate the best on data never seen.",
                 "Proposing round %d — generating up to %d hypothes%s…",
                 "Resuming round %d with %d proposed hypothes%s not yet developed.",
                 "Froze %d finalist%s; the challenger reviewed each before any validation budget was spent.",
                 "Challenger unavailable; approving finalists as-is — the gatekeeper still gates.",
                 "Still running - %d tested so far, %d passed. Exploring more (stop anytime).",
                 "Resuming — re-using %d explored hypotheses, preparing",
                 "Last %d theses all dropped on the research fold. Stopping proposals; %d kept go ",
                 "The proposer keeps returning mechanisms the sibling markets already killed. ",
                 "No tradeable surface after %d attempts — stopping to free the worker.",
                 "%d of %d hypotheses passed every gate%s.",
                 "Paused — out of credits. Add more (or turn on auto-reload) and start a new "):
        assert stem in src, stem
    assert ge.step_note("step", OUT_OF_CREDITS_STEP + ". Add more.").startswith("Out of credits")


def test_the_done_line_and_lines_it_leaves_alone():
    assert ge.step_note("done", "1 of 5 hypotheses passed every gate.") == "1 of 5 ideas passed every check."
    assert ge.step_note("done", "0 of 5 hypotheses passed every gate (1 dropped on research data).") == \
        "0 of 5 ideas passed every check (1 dropped before testing)."
    assert ge.step_note("done", "1 of 1 hypotheses passed every gate.") == "1 of 1 idea passed every check."
    # Passes a later check left uncleared (Missed final test, Held back) are counted apart, never more than passed.
    assert ge.step_note("done", "1 of 2 hypotheses passed every gate.", 1) == \
        "0 of 2 ideas cleared every check; 1 more passed its first test, then wasn't cleared to trade."
    assert ge.step_note("done", "3 of 9 hypotheses passed every gate (2 dropped on research data).", 2) == \
        "1 of 9 ideas cleared every check (2 dropped before testing); 2 more passed their first test, then weren't cleared to trade."
    assert ge.step_note("done", "1 of 2 hypotheses passed every gate.", 4).startswith("0 of 2 ideas cleared every check; 1 more")
    assert ge.step_note("done", "0 of 2 hypotheses passed. Random really does wander nowhere.", 1) == \
        "0 of 2 ideas passed. Random really does wander nowhere."
    # The seeded example's last line keeps its own sentence after the count.
    assert ge.step_note("done", "0 of 2 hypotheses passed. Random really does wander nowhere — now describe a real idea.") == \
        "0 of 2 ideas passed. Random really does wander nowhere — now describe a real idea."
    for kind, msg in (("step", "Loaded 30 days of Bitcoin 15-minute history."), ("step", None), ("step", ""),
                      ("done", "Done."), ("done", None),
                      ("verdict", "Froze 1 finalist; the challenger reviewed each before any validation budget was spent."),
                      ("thinking", "Plan: explore up to 6 hypotheses"), (None, "Proposing round 1 — generating up to 3 hypotheses…")):
        assert ge.step_note(kind, msg) is None


def test_the_run_page_gets_the_note_beside_the_untouched_message():
    msg = "Paused — out of credits. Add more (or turn on auto-reload) and start a new session to keep researching."
    evs = _with_gate_lines([{"kind": "step", "message": msg, "data": None},
                            {"kind": "step", "message": "Loading data…", "data": {"phase": "loading"}},
                            {"kind": "step", "message": "Froze 2 finalists; the challenger reviewed each before any "
                                                        "validation budget was spent.", "data": "not a dict"},
                            {"kind": "done", "message": "1 of 2 hypotheses passed every gate.", "data": {"passed": 1}}])
    assert evs[0]["message"] == msg and evs[0]["data"]["note"].startswith("Out of credits")
    assert evs[1]["data"] == {"phase": "loading"}  # nothing to say: untouched
    assert evs[2]["data"] == {"note": "Picked the best 2 ideas to test on data it hasn't seen; a skeptical reviewer read each one first."}
    assert evs[3]["data"] == {"passed": 1, "note": "1 of 2 ideas passed every check."}
    done = _with_gate_lines([{"kind": "done", "message": "1 of 2 hypotheses passed every gate.", "data": {"passed": 1}}], 1)
    assert done[0]["data"]["note"] == "0 of 2 ideas cleared every check; 1 more passed its first test, then wasn't cleared to trade."
