"""The session page's tally of a long session's older lines names each strategy they judged (`judged`).

Walk 2026-10-31: a finished session whose pass the user then deleted read "Passed 1" over "Nothing passed this
time", and counted the deleted one "dropped before testing". The page tells a deleted strategy from a dropped idea
by the strategies its log judged that are no longer among the session's own; for a long session the lines it isn't
sent come in the tally. No read: the tally works from the lines it already has.
"""
from app.web.routes import research


def _verdict(eid, title, status, sid=None):
    data = {"title": title, "status": status}
    if sid is not None:
        data["strategy_id"] = sid
    return {"id": eid, "kind": "verdict", "message": "%s - %s: done" % (status.upper(), title), "data": data, "created_at": None}


def test_the_tally_names_each_strategy_its_older_lines_judged_once_and_never_a_dropped_idea():
    rows = [
        {"id": 1, "kind": "hypothesis", "message": "Gone pass", "data": {}, "created_at": None},
        _verdict(2, "Gone pass", "passed", 7),
        {"id": 3, "kind": "hypothesis", "message": "Dropped", "data": {}, "created_at": None},
        _verdict(4, "Dropped", "abandoned"),
        {"id": 5, "kind": "hypothesis", "message": "Void one", "data": {}, "created_at": None},
        _verdict(6, "Void one", "failed", 8),
        _verdict(7, "Gone pass", "passed", 7),  # a later line on the same strategy names it once
        _verdict(9, "Newer", "rejected", 9),    # on the page already: not tallied
    ]
    out = research._run_tally(rows, 8)
    assert out["judged"] == [[7, "passed", "Gone pass"], [8, "failed", "Void one"]]
    assert out["dropped"] == 1 and out["hypotheses"] == 3


def test_a_tally_with_no_judged_strategy_sends_an_empty_list():
    out = research._run_tally([{"id": 1, "kind": "step", "message": "Loading", "data": {}, "created_at": None}], 5)
    assert out["judged"] == []
