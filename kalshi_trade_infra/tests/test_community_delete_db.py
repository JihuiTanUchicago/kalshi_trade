"""Deleting your own community post against a real MySQL: the post goes with its replies, likes,
reactions and photo, so nothing it shared stays readable; someone else's post can't be deleted; a
notice that linked it stays and opens the feed saying the post is gone. Opt in as for
test_app_engine_db.py (APP_TEST_MYSQL=1)."""
import os
import uuid

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
    return repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "del-%s@example.com" % uuid.uuid4().hex[:8], "D", None)["id"]


def _count(cur, sql, arg):
    cur.execute(sql, (arg,))
    return int(cur.fetchone()["n"])


def test_the_author_deletes_a_post_with_everything_hanging_off_it(conn):
    from app import repository as repo

    cur = conn.cursor()
    author, other = _user(cur), _user(cur)
    image = repo.store_image(cur, author, "image/png", b"\x89PNG fake")
    pid = repo.create_post(cur, author, "Sharing my results so far.", "pnl",
                           {"kind": "pnl", "paper_pnl": 7.2, "live_pnl": -0.6}, image)
    keep = repo.create_post(cur, other, "Mine stays", "note", None)
    repo.add_comment(cur, pid, other, "nice")
    repo.toggle_like(cur, pid, other)
    repo.toggle_reaction(cur, pid, other, "🔥")
    repo.add_comment(cur, keep, author, "a reply on someone else's post stays")
    repo.add_notification(cur, author, "comment", "D commented on your post.", "/community#post-%d" % pid)

    assert repo.delete_post(cur, pid, other) is False  # not theirs: nothing goes
    assert repo.post_exists(cur, pid)

    assert repo.delete_post(cur, pid, author) is True
    assert not repo.post_exists(cur, pid)
    for table in ("app_post_comments", "app_post_likes", "app_post_reactions"):
        assert _count(cur, "SELECT COUNT(*) AS n FROM %s WHERE post_id=%%s" % table, pid) == 0, table
    assert repo.get_image(cur, image) is None
    assert pid not in [p["id"] for p in repo.list_posts(cur, other)]
    assert repo.post_exists(cur, keep) and len(repo.list_comments(cur, keep)) == 1
    # The bell line stays; the feed says the post is gone when it is opened.
    assert [n["link"] for n in repo.list_notifications(cur, author)] == ["/community#post-%d" % pid]

    assert repo.delete_post(cur, pid, author) is False  # already gone
