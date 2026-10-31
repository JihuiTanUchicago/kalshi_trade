"""The bell against a real MySQL: a repeated pause is one line, a new pause the user hasn't seen
replaces the last, reading the newest notice of one kind uses the (user_id, kind, id) index instead
of walking the table, and the grouped list reads a bounded window. Opt in as for
test_app_engine_db.py (APP_TEST_MYSQL=1)."""
import os
import uuid
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def _user(cur):
    from app import repository as repo
    return repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "bell-%s@example.com" % uuid.uuid4().hex[:8], "B", None)["id"]


def _rows(cur, uid):
    cur.execute("SELECT kind, body, link, read_at FROM app_notifications WHERE user_id=%s ORDER BY id", (uid,))
    return cur.fetchall()


def test_a_repeated_pause_is_one_line_and_an_unseen_one_is_replaced(conn):
    from app import repository as repo

    cur = conn.cursor()
    uid = _user(cur)
    link = "/strategies/77"
    first = repo.add_notification_collapsed(cur, uid, "paused", "“Edge” was paused automatically. Lost $12.", link)
    assert first
    # The same pause seen by a second review (loss guard and force-close both queue one): nothing new.
    assert repo.add_notification_collapsed(cur, uid, "paused", "“Edge” was paused automatically. Lost $12.", link) is None
    # Paused again with a new reason before the user looked: one line, the latest reason.
    assert repo.add_notification_collapsed(cur, uid, "paused", "“Edge” was paused automatically. Lost $15.", link)
    assert [(r["body"], r["read_at"]) for r in _rows(cur, uid)] == [("“Edge” was paused automatically. Lost $15.", None)]
    # Once read, a new pause is news: the read line stays and the new one is added.
    repo.mark_notifications_read(cur, uid)
    assert repo.add_notification_collapsed(cur, uid, "paused", "“Edge” was paused automatically. Lost $20.", link)
    assert [r["read_at"] is None for r in _rows(cur, uid)] == [False, True]
    # The same words long after are a new pause too (the user resumed it in between).
    cur.execute("UPDATE app_notifications SET created_at=created_at - INTERVAL 7 HOUR, read_at=%s WHERE user_id=%s",
                (repo.now_utc(), uid))
    assert repo.add_notification_collapsed(cur, uid, "paused", "“Edge” was paused automatically. Lost $20.", link)
    # Another strategy's pause, and another kind on the same page, are their own lines.
    assert repo.add_notification_collapsed(cur, uid, "paused", "“Edge” was paused automatically. Lost $20.", "/strategies/78")
    repo.add_notification(cur, uid, "passed", "“Edge” passed.", link)
    assert len(_rows(cur, uid)) == 5
    assert repo.count_unread_notifications(cur, uid) == 3


def test_the_newest_notice_of_one_kind_reads_the_users_index_not_the_table(conn):
    from app import repository as repo

    cur = conn.cursor()
    uid = _user(cur)
    for i in range(30):
        repo.add_notification(cur, uid, "comment", "Ana commented on your post.", "/community#post-%d" % (i % 3))
    cur.execute("ANALYZE TABLE app_notifications")
    cur.fetchall()
    cur.execute("EXPLAIN SELECT id, body, created_at, read_at FROM app_notifications WHERE user_id=%s AND kind=%s "
                "ORDER BY id DESC LIMIT 1", (uid, "reload_failed"))
    plan = cur.fetchall()
    assert [p["key"] for p in plan] == ["idx_notif_user_kind"], plan
    assert repo.latest_notification(cur, uid, "reload_failed") is None
    assert repo.latest_notification(cur, uid, "comment")["body"] == "Ana commented on your post."


def test_the_bell_lists_a_bounded_grouped_window_newest_first(conn):
    from app import repository as repo
    from app.services import bell

    cur = conn.cursor()
    uid = _user(cur)
    for i in range(150):  # a heavy user: 150 notices, three posts' replies in runs of 5
        repo.add_notification(cur, uid, "comment", "Reply %d" % i, "/community#post-%d" % (i // 5))
    rows = repo.list_notifications(cur, uid, limit=bell.READ_ROWS)
    assert len(rows) == bell.READ_ROWS and rows[0]["body"] == "Reply 149"
    items = bell.grouped(rows)
    assert len(items) == bell.SHOWN
    assert [(n["body"], n["more"]) for n in items[:2]] == [("Reply 149", 4), ("Reply 144", 4)]
    assert all(not n["read"] for n in items)
    repo.mark_notifications_read(cur, uid)
    assert repo.count_unread_notifications(cur, uid) == 0
    assert all(n["read"] for n in bell.grouped(repo.list_notifications(cur, uid, limit=bell.READ_ROWS)))
    # Times come back as stored (UTC, naive); the API adds the zone when it writes them out.
    assert rows[0]["created_at"] >= repo.now_utc() - timedelta(minutes=5)


def test_a_notice_about_a_strategy_no_longer_the_users_reads_gone_in_the_same_read(conn):
    from app import repository as repo

    cur = conn.cursor()
    uid, other = _user(cur), _user(cur)
    spec = {"side": "yes", "entry": {"min_edge": 0.05}, "exit": {}, "sizing": {"stake": 10.0, "max_positions": 2}}
    kept = repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", "Kept", "t", spec, "passed", {})
    dropped = repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", "Dropped", "t", spec, "passed", {})
    theirs = repo.insert_strategy(cur, other, None, None, "btc15m", "momentum", "Theirs", "t", spec, "passed", {})
    repo.add_notification(cur, uid, "passed", "“Kept” passed.", "/strategies/%d" % kept)
    repo.add_notification(cur, uid, "share", "Sam shared “Dropped” with you.", "/strategies/%d" % dropped)
    repo.add_notification(cur, uid, "share", "Another user's row id.", "/strategies/%d" % theirs)
    repo.add_notification(cur, uid, "comment", "Ana replied to your post.", "/community#post-4")
    repo.add_notification(cur, uid, "reload_failed", "Auto-reload couldn't add $20.00 in credits.", "/billing")
    repo.add_notification(cur, uid, "share", "An old notice.", None)
    repo.delete_strategy(cur, uid, dropped)
    rows = repo.list_notifications(cur, uid, limit=10)
    # Newest first: no link, Billing, a post, another user's strategy, the deleted one, the kept one.
    assert [bool(r["gone"]) for r in rows] == [False, False, False, True, True, False]
    assert rows[-1]["body"] == "“Kept” passed."
