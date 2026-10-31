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
    assert set(out[0]) == {"id", "kind", "body", "link", "created_at", "read", "more", "alike", "from", "from_more", "gone"}
    assert not any(n["gone"] for n in out)


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
    # The window and one row past it, in the same read: whether any notice is older than the list.
    assert asked["limit"] == bell.READ_ROWS + 1
    assert out["unread"] == 1 and [(n["id"], n["more"], n["read"]) for n in out["items"]] == [(3, 1, False), (1, 0, True)]
    assert out["older"] is False


def test_the_unread_notices_are_counted_by_kind_for_the_lists_summary():
    rows = [_row(9, "deployed", "/strategies/9", read=False), _row(8, "deployed", "/strategies/8", read=False),
            _row(7, "paused", "/strategies/3", read=False), _row(6, "paused", "/strategies/3", read=False),
            _row(5, "passed", "/strategies/1"), _row(4, "deployed", "/strategies/4")]
    # Stored rows, not grouped lines: two pauses of one strategy in a row are one line and two notices.
    assert bell.unread_kinds(rows) == {"deployed": 2, "paused": 2}
    assert bell.unread_kinds([_row(1, "share", None)]) == {}


def test_a_notice_about_a_strategy_no_longer_the_users_says_gone():
    # list_notifications joins each strategy link to its row: a deleted strategy (a shared copy removed, one
    # the user deleted) comes back gone=1, so the bell says so instead of linking to "Not found".
    rows = [dict(_row(3, "share", "/strategies/14"), gone=1), dict(_row(2, "passed", "/strategies/6"), gone=0),
            _row(1, "comment", "/community#post-1")]
    out = bell.grouped(rows)
    assert [(n["id"], n["gone"]) for n in out] == [(3, True), (2, False), (1, False)]


def test_a_group_says_whether_its_notices_say_the_same_and_whom_replies_are_from():
    # Walk 2026-10-31: "Bob replied to your post." over replies from Dana, Carol and Bob read "and 3 more like
    # this", as if Bob had written all four; a live pause over an earlier paper pause (another reason) read as more
    # of the same. A group says whether they all say the same words, and replies and mentions name their people.
    post, strat = "/community#post-1", "/strategies/13"
    rows = [_row(20, "comment", post, read=False, body="Bob replied to your post."),
            _row(19, "comment", post, body="Dana replied to your post."),
            _row(18, "comment", post, body="Carol replied to your post."),
            _row(17, "comment", post, body="Bob replied to your post."),
            _row(16, "mention", post, body="Carol mentioned you in a reply."),
            _row(15, "mention", post, body="Bob mentioned you in a post."),
            _row(14, "comment", "/community#post-2", body="Carol replied to your post."),
            _row(13, "comment", "/community#post-2", body="Carol replied to your post."),
            _row(12, "paused", strat, body="“Fade” was paused automatically. Live is down $4.20."),
            _row(11, "paused", strat, body="“Fade” was paused automatically. Lost $12.34.")]
    out = bell.grouped(rows)
    assert [(n["id"], n["more"], n["alike"], n["from"], n["from_more"]) for n in out] == [
        (20, 3, False, ["Dana", "Carol", "Bob"], 0),  # Bob's own second reply names him too
        (16, 1, False, ["Bob"], 0),
        (14, 1, True, ["Carol"], 0),
        (12, 1, False, [], 0)]                      # a pause names no person
    # The words shown are each notice's own, unchanged.
    assert [n["body"] for n in out] == [rows[0]["body"], rows[4]["body"], rows[6]["body"], rows[8]["body"]]


def test_a_group_names_three_people_and_counts_the_rest_and_a_name_reads_whole():
    post = "/community#post-9"
    names = ["Ann", "Bo", "Cy", "Di", "Ed", "Bo"]
    rows = [_row(30, "comment", post, body="Zed replied to your post.")]
    rows += [_row(29 - i, "comment", post, body="%s replied to your post." % n) for i, n in enumerate(names)]
    out = bell.grouped(rows)
    assert (out[0]["more"], out[0]["from"], out[0]["from_more"]) == (6, ["Ann", "Bo", "Cy"], 2)
    # A name with the notice's own words in it reads whole; a body in other words names no one.
    odd = bell.grouped([_row(2, "comment", post, body="Al replied to your post."),
                        _row(1, "comment", post, body="Me replied to your post. replied to your post.")])
    assert odd[0]["from"] == ["Me replied to your post."]
    other = bell.grouped([_row(2, "comment", post, body="Al replied to your post."),
                          _row(1, "comment", post, body="There’s an update on your account.")])
    assert (other[0]["alike"], other[0]["from"]) == (False, [])


def test_a_pause_opens_at_since_deploying_and_a_failed_reload_at_billings_notice_the_stored_link_groups():
    rows = [_row(5, "paused", "/strategies/13", read=False), _row(4, "paused", "/strategies/13"),
            _row(3, "reload_failed", "/billing"), _row(2, "passed", "/strategies/13"), _row(1, "comment", "/community#post-4")]
    out = bell.grouped(rows)
    assert [(n["link"], n["more"]) for n in out] == [("/strategies/13#since-deploying", 1), ("/billing#autorel-fail", 0),
                                                     ("/strategies/13", 0), ("/community#post-4", 0)]
    # Only the plain page link takes the part: anything else is left as stored.
    assert bell.shown_link("paused", "/strategies/13#x") == "/strategies/13#x"
    assert bell.shown_link("paused", None) is None
    assert bell.shown_link("reload_failed", "/billing?x=1") == "/billing?x=1"


def test_the_bell_says_when_older_notices_are_past_its_lines(monkeypatch):
    many = [_row(500 - i, "share", "/strategies/%d" % i) for i in range(bell.READ_ROWS + 1)]
    monkeypatch.setattr(server.repo, "count_unread_notifications", lambda cur, uid: 0)
    ctx = type("C", (), {"cur": None, "uid": 1})()
    for rows, older in ((many, True), (many[:bell.SHOWN], False), (many[:bell.SHOWN + 1], True), ([], False)):
        monkeypatch.setattr(server.repo, "list_notifications", lambda cur, uid, limit=20, rows=rows: rows[:limit])
        out = server.notifications(ctx)
        assert out["older"] is older, len(rows)
        assert len(out["items"]) == min(len(rows), bell.SHOWN)
    # The 101st row only says there is more: the summary still counts the window of 100.
    unread = [dict(r, read_at=None) for r in many]
    monkeypatch.setattr(server.repo, "list_notifications", lambda cur, uid, limit=20: unread[:limit])
    assert server.notifications(ctx)["unread_kinds"] == {"share": bell.READ_ROWS}
    # One group that swallows the whole window still has older rows behind it.
    run = [_row(300 - i, "comment", "/community#post-1") for i in range(bell.READ_ROWS + 1)]
    monkeypatch.setattr(server.repo, "list_notifications", lambda cur, uid, limit=20: run[:limit])
    out = server.notifications(ctx)
    assert (len(out["items"]), out["items"][0]["more"], out["older"]) == (1, bell.READ_ROWS - 1, True)
