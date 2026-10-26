"""The community emails (a reply, a mention, a new post), rendered from their templates with made-up
data: each links the post it is about, quotes it in plain words, and says how to stop it. No SES call
is made: the sender is stubbed, and the routes' senders are patched where community.py reads them."""
import re
from types import SimpleNamespace

import pytest

from app.adapters.ses import notify
from app.web import settings as web_settings
from app.web.routes import community

POST = notify.PUBLIC_URL + "/community#post-5"


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "_send", lambda to, subject, body, reply_to=None: sent.append((to, subject, body)) or True)
    return sent


def _rendered(mails):
    notify.comment_notice("a@x.invalid", "Ann", "Bob", "My **first** post", "Nice `KXBTC` [chart](https://example.com/c)",
                          POST, notify.unsubscribe_url(7))
    notify.mention_notice("c@x.invalid", "Cat", "Bob", "hey @cat look at **this**", POST, notify.unsubscribe_url(8))
    notify.community_post_notice("d@x.invalid", "Dee", "Bob", "Sharing a strategy.", notify.unsubscribe_url(9), POST)
    return {kind: body for kind, (_to, _subject, body) in zip(("reply", "mention", "post"), mails)}


def test_each_community_email_links_the_post_it_is_about(mails):
    for kind, body in _rendered(mails).items():
        assert POST in body, kind
        assert "Open the Community tab" not in body, kind  # an instruction with nothing to click
    # The link is one the app opens: the feed route, at that post (the bell's own link, made whole).
    path = POST[len(notify.PUBLIC_URL):]
    assert path == community.post_link(5) and web_settings.SPA_ROUTES.match(path.split("#")[0])


def test_each_community_email_says_how_to_stop_it_with_a_link_that_works(mails):
    bodies = _rendered(mails)
    for kind, uid in (("reply", 7), ("mention", 8), ("post", 9)):
        body = bodies[kind]
        assert "Unsubscribe: " + notify.unsubscribe_url(uid) in body, kind
        assert "Email in Settings: %s/settings" % notify.PUBLIC_URL in body, kind
        token = re.search(r"/unsubscribe\?u=%d&t=(\w+)" % uid, body).group(1)
        assert notify.unsubscribe_token_valid(uid, token)


def test_quoted_posts_read_in_plain_words(mails):
    bodies = _rendered(mails)
    assert "“My first post”" in bodies["reply"]
    assert "“Nice KXBTC chart (https://example.com/c)”" in bodies["reply"]
    assert "“hey @cat look at this”" in bodies["mention"]
    for body in bodies.values():
        assert "**" not in body and "`" not in body
    notify.mention_notice("e@x.invalid", "E", "Bob", "x" * 400, POST)
    quoted = re.search(r"“(.*)”", mails[-1][2]).group(1)
    assert len(quoted) == 280 and quoted.endswith("…")


def test_an_email_with_no_link_given_still_opens_the_feed_and_says_how_to_stop(mails):
    notify.mention_notice("e@x.invalid", "E", "Bob", "hi")
    body = mails[-1][2]
    assert notify.PUBLIC_URL + "/community" in body
    assert "(Turn these off anytime under Email in Settings: %s/settings)" % notify.PUBLIC_URL in body


# -- the routes hand each email its post and its reader's unsubscribe link -----------------------------

def _ctx(uid=1, body=None, params=()):
    return SimpleNamespace(cur=None, uid=uid, body=body or {}, params=params, query={})


def test_a_reply_and_a_mention_email_carry_the_post_and_the_readers_own_unsubscribe(monkeypatch):
    calls = {}
    monkeypatch.setattr(community.repo, "post_author", lambda cur, pid: {
        "user_id": 2, "email": "au@x.invalid", "email_opt_out": 0, "name": "Au", "preview": "p"})
    monkeypatch.setattr(community.repo, "add_comment", lambda *a: 1)
    monkeypatch.setattr(community.repo, "get_user", lambda cur, uid: {"name": "Bob"})
    monkeypatch.setattr(community.repo, "add_notification", lambda *a, **k: 1)
    monkeypatch.setattr(community.repo, "users_by_usernames", lambda cur, hs: [
        {"id": 3, "username": "cat", "name": "Cat", "email": "cat@x.invalid", "email_opt_out": 0}])
    monkeypatch.setattr(community.notify, "comment_notice", lambda *a: calls.setdefault("reply", a) and True)
    monkeypatch.setattr(community.notify, "mention_notice", lambda *a: calls.setdefault("mention", a) and True)
    assert community.create_comment(_ctx(body={"body": "nice @cat"}, params=("5",))) == {"ok": True}
    assert calls["reply"][0] == "au@x.invalid" and calls["reply"][5:] == (POST, notify.unsubscribe_url(2))
    assert calls["mention"][0] == "cat@x.invalid" and calls["mention"][4:] == (POST, notify.unsubscribe_url(3))


def test_a_new_post_email_links_that_post(monkeypatch):
    calls = []
    cur = SimpleNamespace()
    monkeypatch.setattr(community, "get_db_conn", lambda: SimpleNamespace(cursor=lambda: cur))
    monkeypatch.setattr(community.repo, "community_email_recipients", lambda c, uid: [{"id": 4, "email": "r@x.invalid", "name": "R"}])
    monkeypatch.setattr(community.repo, "mark_community_emailed", lambda c, ids: None)
    monkeypatch.setattr(community.notify, "community_post_notice", lambda *a: calls.append(a) or True)

    class Now:  # run the dispatch on this thread
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(community.threading, "Thread", Now)
    community._email_community_post_async(1, "Bob", "Sharing a strategy.", 5)
    assert calls == [("r@x.invalid", "R", "Bob", "Sharing a strategy.", notify.unsubscribe_url(4), POST)]
