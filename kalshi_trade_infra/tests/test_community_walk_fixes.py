"""What a community walk as three customers found (2026-10-31), held through the real routes with the repo stubbed:
a reactor whose name is their email address was named by it in every reader's feed; the @-autocomplete matched on
such a name, so a reader could spell out another person's address a letter at a time; the feed had no way past its
newest 30 posts; and the author's card for a strategy they had deleted linked a page that said "Not found".
No DB, no network."""
import json
from types import SimpleNamespace

import pytest

from app import repository as repo
from app import server
from app.web.routes import community

ADDRESS = "dana.private@example.org"


def _ctx(params=(), query=None, body=None):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()), {"id": 7, "email": "me@example.invalid", "name": "Me"},
                      tuple(params), query or {}, body or {}, SimpleNamespace())


def _row(**over):
    row = {"id": 5, "body": "gm", "kind": "note", "snapshot": None, "likes_count": 0, "comments_count": 0,
           "created_at": None, "name": "Ann", "username": "ann", "picture_url": None, "mine": False,
           "reactions": [{"emoji": "🔥", "count": 3, "mine": False, "names": [ADDRESS, "Bob", "  "],
                          "handles": ["danap", "bob", ""]}]}
    row.update(over)
    return row


def test_a_reactor_whose_name_is_their_address_reads_as_their_handle_in_the_feed_and_after_a_reaction(monkeypatch):
    out = community._post_out(_row())
    assert out["reactions"][0]["names"] == ["danap", "Bob", "Trader"]
    assert out["reactions"][0]["handles"] == ["danap", "bob", ""] and out["reactions"][0]["count"] == 3
    assert ADDRESS not in json.dumps(out)
    # The reaction a press returns, which repaints the pills, says it the same way.
    monkeypatch.setattr(repo, "post_exists", lambda cur, pid: True)
    monkeypatch.setattr(repo, "toggle_reaction", lambda cur, pid, uid, emoji: True)
    monkeypatch.setattr(repo, "reactions_for", lambda cur, ids, uid: {5: _row()["reactions"]})
    got = community.react_post(_ctx(("5",), body={"emoji": "🔥"}))
    assert got["reactions"][0]["names"] == ["danap", "Bob", "Trader"] and ADDRESS not in json.dumps(got)


@pytest.mark.parametrize("q", ["dana.private@exa", "example.org", "private", "@example"])
def test_the_mention_search_never_matches_on_a_name_that_is_an_address(monkeypatch, q):
    # The read matches a name anywhere in it (LIKE %q%); a hit on an address must not come back.
    monkeypatch.setattr(repo, "mention_candidates", lambda cur, query: [{"username": "danap", "name": ADDRESS}])
    assert community.mention_candidates(_ctx(query={"q": q}))["users"] == []


def test_the_mention_search_still_finds_a_person_by_handle_or_by_a_real_name(monkeypatch):
    monkeypatch.setattr(repo, "mention_candidates", lambda cur, query: [{"username": "danap", "name": ADDRESS},
                                                                         {"username": "cq", "name": "Dana Quant"}])
    assert community.mention_candidates(_ctx(query={"q": "dan"}))["users"] == [
        {"username": "danap", "name": "danap"}, {"username": "cq", "name": "Dana Quant"}]
    assert community.mention_candidates(_ctx(query={"q": "Quant"}))["users"] == [{"username": "cq", "name": "Dana Quant"}]


@pytest.mark.parametrize("query,limit", [({}, 30), ({"limit": "60"}, 60), ({"limit": "100000"}, 300),
                                         ({"limit": "0"}, 1), ({"limit": "abc"}, 30)])
def test_show_older_posts_reads_more_of_the_feed_in_one_read_up_to_a_cap(monkeypatch, query, limit):
    seen = []

    def list_posts(cur, uid, before, limit=30, mine_only=False):
        seen.append((uid, before, limit, mine_only))
        return []
    monkeypatch.setattr(repo, "list_posts", list_posts)
    assert community.community(_ctx(query=dict(query, before="40", mine="1"))) == {"posts": []}
    assert seen == [(7, 40, limit, True)]


def test_the_authors_card_for_a_strategy_they_deleted_since_has_no_link_and_says_it_is_gone():
    snap = {"kind": "strategy", "id": 4711, "title": "Fade", "market": "btc15m", "status": "passed", "pnl": 5.5}
    gone = community._post_out(_row(kind="strategy", snapshot=dict(snap), mine=True, strategy_gone=True))["snapshot"]
    assert gone.get("gone") is True and "id" not in gone and gone["pnl"] == 5.5
    kept = community._post_out(_row(kind="strategy", snapshot=dict(snap), mine=True))["snapshot"]
    assert kept["id"] == 4711 and "gone" not in kept
    # Anyone else's card is no link either way, and says nothing about the author's strategies.
    other = community._post_out(_row(kind="strategy", snapshot=dict(snap), strategy_gone=True))["snapshot"]
    assert "id" not in other and "gone" not in other
