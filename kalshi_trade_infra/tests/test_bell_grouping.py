"""The bell lists notices about the same thing in a row as one line with a count, keeps every other
line in order, and reads a bounded number of rows however many notices a user has."""
from app import server
from app.services import bell


def _row(i, kind, link, read=True, body=None):
    return {"id": i, "kind": kind, "body": body or "%s %d" % (kind, i), "link": link,
            "created_at": "2026-10-26T10:%02d:00" % (i % 60), "read_at": "x" if read else None}


def test_adjacent_notices_about_one_page_collapse_into_the_newest():
    rows = [_row(9, "comment", "/community#post-4", read=False, body="Ana commented on your post."),
            _row(8, "comment", "/community#post-4", body="Bo commented on your post."),
            _row(7, "comment", "/community#post-4"),
            _row(6, "paused", "/strategies/3"),
            _row(5, "comment", "/community#post-4"),  # not adjacent to the first run: its own line
            _row(4, "share", "/strategies/11"),
            _row(3, "share", "/strategies/12")]       # same kind, another page: not alike
    out = bell.grouped(rows)
    assert [(n["id"], n["more"]) for n in out] == [(9, 2), (6, 0), (5, 0), (4, 0), (3, 0)]
    assert out[0]["body"] == "Ana commented on your post." and out[0]["read"] is False
    assert set(out[0]) == {"id", "kind", "body", "link", "created_at", "read", "more"}


def test_a_group_is_unread_when_any_notice_in_it_is():
    out = bell.grouped([_row(2, "paused", "/strategies/3"), _row(1, "paused", "/strategies/3", read=False)])
    assert out == [dict(out[0], more=1, read=False)]


def test_notices_without_a_link_never_group():
    out = bell.grouped([_row(2, "share", None), _row(1, "share", None)])
    assert [n["more"] for n in out] == [0, 0]


def test_the_list_stops_at_its_size_and_a_trailing_run_still_counts():
    rows = [_row(100 - i, "share", "/strategies/%d" % i) for i in range(bell.SHOWN)]
    rows += [_row(50, "share", "/strategies/%d" % (bell.SHOWN - 1)), _row(49, "comment", "/community")]
    out = bell.grouped(rows)
    assert len(out) == bell.SHOWN and out[-1]["more"] == 1


def test_the_endpoint_reads_a_bounded_window_and_groups_it(monkeypatch):
    asked = {}

    def rows(cur, uid, limit=20):
        asked["limit"] = limit
        return [_row(3, "comment", "/community", read=False), _row(2, "comment", "/community"), _row(1, "share", "/strategies/9")]

    monkeypatch.setattr(server.repo, "list_notifications", rows)
    monkeypatch.setattr(server.repo, "count_unread_notifications", lambda cur, uid: 1)
    out = server.notifications(type("C", (), {"cur": None, "uid": 1})())
    assert asked["limit"] == bell.READ_ROWS
    assert out["unread"] == 1 and [(n["id"], n["more"], n["read"]) for n in out["items"]] == [(3, 1, False), (1, 0, True)]


def test_the_unread_notices_are_counted_by_kind_for_the_lists_summary():
    rows = [_row(9, "deployed", "/strategies/9", read=False), _row(8, "deployed", "/strategies/8", read=False),
            _row(7, "paused", "/strategies/3", read=False), _row(6, "paused", "/strategies/3", read=False),
            _row(5, "passed", "/strategies/1"), _row(4, "deployed", "/strategies/4")]
    # Stored rows, not grouped lines: two pauses of one strategy in a row are one line and two notices.
    assert bell.unread_kinds(rows) == {"deployed": 2, "paused": 2}
    assert bell.unread_kinds([_row(1, "share", None)]) == {}
