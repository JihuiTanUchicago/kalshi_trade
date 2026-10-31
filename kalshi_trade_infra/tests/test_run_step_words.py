"""customer_text.step_words: the research agent's housekeeping step lines (its playbook and long-term memory, the
quicker screening model's hand-offs, the lead scan, a reclaim after a restart) as the run page says them. Walk
2026-10-31: a customer watching a live session read "Using research playbook v3 for crypto markets (current).",
"Handing “Ladder idea 8” to the developer model (the screen would commit it)." and "Session interrupted — reclaiming it
to resume from the last checkpoint (attempt 1 of 3)." in its log. The stored message is never changed."""
import re
from pathlib import Path

import pytest

from app.services import customer_text as ct
from app.web.views import _with_gate_lines

ROOT = Path(ct.__file__).parents[1]

# Each line as agent.py (or the run reaper) formats it today, and what the run page says in its place.
STEP_LINES = [
    ("Using research playbook v3 for crypto markets (current).",
     "Drawing on its notes from earlier sessions on how to research these markets."),
    ("Using research playbook v4 for weather-high markets (on trial against the current one).",
     "Trying out revised notes on how to research these markets, against the current ones."),
    ("Research playbook for crypto markets: promoted v4 over v3 (P(better)=0.91).",
     "Its revised research notes for these markets did better than the old ones, so it keeps them."),
    ("Research playbook for crypto markets: retired v4, v3 stays (P(better)=0.22).",
     "Its revised research notes for these markets did no better than the old ones, so it keeps the old ones."),
    ("Wrote research playbook v5 for crypto markets from this run’s verdicts; it now runs on trial against v4. "
     "Tightened the in-sample gate.",
     "Rewrote its notes on how to research these markets from this session’s results; later sessions try them "
     "against the current ones."),
    ("Playbook update skipped this time. The run’s results are saved.",
     "Its research notes weren’t updated this time; this session’s results are saved."),
    ("Using long-term research memory for crypto markets.", "Drawing on what earlier sessions on these markets found."),
    ("Consolidated long-term research memory for crypto markets: 12 mechanisms, 3 marked dead.",
     "Summed up what sessions on these markets have found so far, for later sessions to build on."),
    ("Handing \"Ladder idea 8\" to the developer model (the screen would commit it).",
     "A quicker model looked at “Ladder idea 8” first and passed it on to be worked out in full."),
    ("Screen audit on \"Ladder idea 8\": screen abandoned, developer says abandon.",
     "A second look agreed to drop “Ladder idea 8”."),
    ("Screen audit on \"Ladder idea 8\": screen abandoned, developer says refine.",
     "A quicker model would have dropped “Ladder idea 8”; a second look kept it to work out in full."),
    ("Session interrupted — reclaiming it to resume from the last checkpoint (attempt 1 of 3).",
     "The session was interrupted, so it’s picking up again from where it last saved its progress."),
    ("Session interrupted before its first checkpoint — restarting it (attempt 2 of 3).",
     "The session was interrupted before it saved any progress, so it’s starting again from the top."),
    ("Paused for a server update; resuming from the last checkpoint.",
     "Paused for a server update; it picks up again from where it last saved its progress."),
    ("Paused too long — stopping to free the worker. Start a new session to continue.",
     "Paused too long, so the session stopped. Start a new session to continue."),
    ("Scanning every feature x life x price cell for measured mispricing…",
     "Scanning the research data for mispriced setups first…"),
    ("Lead scan skipped this time.", "Skipped the scan of the data this time and went straight to ideas."),
    ("Dreaming hiccup (kept current policy).", "Couldn’t tune how it searches this time, so it keeps its current approach."),
    ("Policy-evolution step skipped this time.", "Skipped tuning how it searches this time."),
]
JARGON = re.compile(r"playbook|\bv\d|crypto|weather-high|long-term research memory|developer|screen audit|checkpoint|"
                    r"attempt \d|worker|feature x life|lead scan|policy|dreaming|in-sample", re.I)


@pytest.mark.parametrize("message,said", STEP_LINES)
def test_a_housekeeping_step_line_reads_plainly(message, said):
    assert ct.step_words(message) == said
    assert not JARGON.search(said), said


def test_the_words_follow_what_the_agent_and_the_reaper_write():
    # Each line's fixed words still appear where it is written: a reworded line fails here instead of quietly
    # keeping its internal words on the page.
    agent = (ROOT / "research" / "agent.py").read_text(encoding="utf-8")
    reaper = (ROOT / "adapters" / "db" / "agent_run_repository.py").read_text(encoding="utf-8")
    for stem in ("Using research playbook v%s for %s markets (%s).", "on trial against the current one",
                 "Research playbook for %s markets: %s.", "Wrote research playbook v%d for %s markets from this run",
                 "Playbook update skipped this time.", "Using long-term research memory for %s markets.",
                 "Consolidated long-term research memory for %s markets: %s",
                 "Handing \\\"%s\\\" to the developer model (%s).",
                 "Screen audit on \\\"%s\\\": screen abandoned, developer says %s.",
                 "Scanning every feature x life x price cell for measured mispricing…", "Lead scan skipped this time.",
                 "Dreaming hiccup (kept current policy).", "Policy-evolution step skipped this time.",
                 "Paused too long — stopping to free the worker."):
        assert stem in agent, stem
    for stem in ("Session interrupted — reclaiming it to resume from the last checkpoint ",
                 "Session interrupted before its first checkpoint — restarting it ",
                 "Paused for a server update; resuming from the last checkpoint."):
        assert stem in reaper, stem
    play = (ROOT / "research" / "rsi_playbook.py").read_text(encoding="utf-8")
    assert '"promoted v%d over v%d' in play and '"retired v%d, v%d stays' in play


def test_lines_it_does_not_know_keep_their_words():
    for msg in ("Loaded 30 days of Bitcoin up or down in 15 minutes history.", "Cancelled.", "", None,
                "Developing \"Late fade\" (step 2/4)…"):
        assert ct.step_words(msg) is None


def test_the_run_page_gets_the_note_beside_the_untouched_message():
    msg = "Using research playbook v3 for crypto markets (current)."
    evs = _with_gate_lines([{"kind": "step", "message": msg, "data": {"phase": "playbook", "family": "crypto"}},
                            {"kind": "verdict", "message": msg, "data": {}},
                            {"kind": "done", "message": "Session interrupted — reclaiming it to resume from the last "
                                                        "checkpoint (attempt 1 of 3).", "data": None}])
    assert evs[0]["message"] == msg
    assert evs[0]["data"]["note"] == "Drawing on its notes from earlier sessions on how to research these markets."
    assert evs[1]["data"].get("note") is None  # a verdict is gate_explain's
    assert evs[2]["data"] is None  # only step lines
    # The ledger's own lines still read as gate_explain says them.
    plan = _with_gate_lines([{"kind": "step", "message": "Proposing round 1 — generating up to 3 hypotheses…", "data": None}])
    assert plan[0]["data"]["note"] == "Round 1: coming up with up to 3 ideas…"
