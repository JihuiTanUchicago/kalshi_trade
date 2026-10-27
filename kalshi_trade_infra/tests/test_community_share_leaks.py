"""A strategy, deployment or P&L shared to the community is read by everyone signed in to Tau. What
reaches another reader is the card's figures only: no spec or rules, no internal model id, no credits,
no key, no email address, and no row id (the author's card links their page; anyone else's is no link).
Built through the real route with the repo patched where community.py reads it."""
import json
from types import SimpleNamespace

import pytest

from app.web.routes import community

MODEL = "us.anthropic.claude-opus-4-1-v1:0"
SECRET = "sk_live_51NotARealKey"
STRATEGY = {
    "id": 4711, "title": "Fade late spikes", "market": "btc15m", "status": "passed", "direction": "yes",
    "thesis": "who pays: late chasers", "spec": {"rule": "buy when x > 0.7", "model_id": MODEL, "stake": 10},
    "run_id": 9001, "experiment_id": 8123,
    "result": {"out_of_sample": {"pnl": 42.17, "trades": 23, "win_rate": 0.61, "days": 9.4, "roi": .04},
               "in_sample": {"pnl": 80.0}, "model": MODEL, "credits_spent": 3.25},
}
DEPLOYMENT = {"id": 5150, "title": "Fade late spikes", "market": "btc15m", "mode": "live", "realized_pnl": -0.6,
              "closed_trades": 1, "created_at": None, "strategy_id": 4711, "kalshi_key_id": SECRET,
              "max_position": 50, "user_id": 7}
FORBIDDEN = (MODEL, "claude", SECRET, "author@example.net", "buy when", "late chasers", "credit", "spec",
             "rule", "4711", "5150", "9001", "8123", "in_sample", "max_position", "key")


@pytest.fixture
def share(monkeypatch):
    stored = {}
    monkeypatch.setattr(community.repo, "recent_posts_count", lambda cur, uid, since: 0)
    monkeypatch.setattr(community.repo, "get_strategy", lambda cur, uid, sid: dict(STRATEGY))
    monkeypatch.setattr(community.repo, "get_deployment", lambda cur, uid, did: dict(DEPLOYMENT))
    monkeypatch.setattr(community.repo, "realized_pnl", lambda cur, uid, mode: {"paper": 7.2, "live": -0.6}[mode])
    monkeypatch.setattr(community.repo, "closed_trade_counts", lambda cur, uid: {"paper": 4, "live": 1})
    monkeypatch.setattr(community.repo, "get_user", lambda cur, uid: {"id": uid, "name": "author@example.net",
                                                                       "credits": 12.5})
    monkeypatch.setattr(community.repo, "users_by_usernames", lambda cur, names: [])
    monkeypatch.setattr(community, "_email_community_post_async", lambda *a: None)
    later = {}  # what strategies._later_verdicts finds: (verdict, the experiment block it was judged on)
    monkeypatch.setattr(community, "_later_verdicts", lambda cur, uid, rows: {r["id"]: later[r["id"]] for r in rows if r["id"] in later})

    def create_post(cur, uid, body, kind, snapshot, image_id=None):
        stored.update(body=body, kind=kind, snapshot=snapshot)
        return 77
    monkeypatch.setattr(community.repo, "create_post", create_post)

    def post(kind, ref_id=None):
        ctx = SimpleNamespace(cur=None, uid=7, body={"body": "", "kind": kind, "ref_id": ref_id}, query={}, params=())
        assert community.create_community_post(ctx) == {"id": 77}
        return dict(stored)
    post.later = later
    return post


def _as_read(stored, mine):
    row = {"id": 77, "body": stored["body"], "kind": stored["kind"], "snapshot": stored["snapshot"],
           "likes_count": 0, "comments_count": 0, "created_at": None, "name": "author@example.net",
           "username": "ann", "picture_url": None, "mine": mine}
    # Round-trip through JSON, as the snapshot is stored and as the feed is sent.
    row["snapshot"] = json.loads(json.dumps(row["snapshot"]))
    return community._post_out(row)


@pytest.mark.parametrize("kind,ref", [("strategy", 4711), ("deployment", 5150), ("pnl", None)])
def test_another_reader_gets_the_card_figures_and_nothing_private(share, kind, ref):
    out = _as_read(share(kind, ref), mine=False)
    snap = out["snapshot"]
    assert set(snap) <= set(community.SNAPSHOT_FIELDS[kind]) and "id" not in snap
    text = json.dumps(out).lower()
    for word in FORBIDDEN:
        assert word.lower() not in text, (kind, word)
    assert out["author"] == "Trader"  # a name that is an address never shows


def test_the_card_keeps_what_it_says(share):
    snap = _as_read(share("strategy", 4711), mine=False)["snapshot"]
    assert snap == {"kind": "strategy", "title": "Fade late spikes", "market": "btc15m", "status": "passed",
                    "pnl": 42.17, "trades": 23, "win_rate": 0.61, "days": 9.4}
    dep = _as_read(share("deployment", 5150), mine=False)["snapshot"]
    assert dep["mode"] == "live" and dep["realized_pnl"] == -0.6 and dep["closed_trades"] == 1
    # Each book on its own figure: paper and live are never added together.
    pnl = _as_read(share("pnl"), mine=False)["snapshot"]
    assert pnl == {"kind": "pnl", "paper_pnl": 7.2, "live_pnl": -0.6, "paper_trades": 4, "live_trades": 1}


def test_a_shared_pass_a_later_check_left_uncleared_says_so_and_nothing_more(share):
    # Its status stays "passed" after its one-time holdout failed: the card stamped Passed where its page and
    # list say Missed final test. The verdict's word rides on the card; the record it was judged on doesn't.
    share.later[4711] = ("missed_final", {"holdout": {"classification": "inconclusive", "p_value": 0.48}, "experiment_id": 8123})
    snap = _as_read(share("strategy", 4711), mine=False)["snapshot"]
    assert snap["status"] == "passed" and snap["verdict"] == "missed_final"
    assert set(snap) == {"kind", "title", "market", "status", "verdict", "pnl", "trades", "win_rate", "days"}
    assert "8123" not in json.dumps(snap) and "holdout" not in json.dumps(snap)


def test_the_author_alone_gets_the_id_their_card_links(share):
    assert _as_read(share("strategy", 4711), mine=True)["snapshot"]["id"] == 4711


def test_an_older_stored_snapshot_with_more_in_it_is_cut_to_the_card(share):
    stored = {"body": "x", "kind": "strategy", "snapshot": {
        "kind": "strategy", "id": 4711, "title": "Edge via " + MODEL, "market": "btc15m", "status": "passed",
        "spec": STRATEGY["spec"], "user_id": 7, "api_key": SECRET, "credits": 12.5, "pnl": 1.0}}
    snap = _as_read(stored, mine=False)["snapshot"]
    assert snap == {"kind": "strategy", "title": "Edge via the AI model", "market": "btc15m", "status": "passed", "pnl": 1.0}
    assert _as_read({"body": "x", "kind": "note", "snapshot": {"kind": "secret", "api_key": SECRET}}, mine=True)["snapshot"] is None


# -- a share can be taken down by its author, and only by them -----------------------------------------

def test_the_author_can_take_a_post_down_and_no_one_else_can(monkeypatch):
    from app import server
    from app.web.http import ApiError

    calls = []
    monkeypatch.setattr(community.repo, "delete_post", lambda cur, pid, uid: calls.append((pid, uid)) or uid == 7)

    def ctx(uid):
        return SimpleNamespace(cur=None, uid=uid, body={}, query={}, params=("77",))
    assert community.delete_community_post(ctx(7)) == {"ok": True}
    with pytest.raises(ApiError) as refused:
        community.delete_community_post(ctx(8))
    assert refused.value.status == 403 and "your own posts" in str(refused.value)
    assert calls == [(77, 7), (77, 8)]
    rows = [r for r in server.ROUTES if r[1].pattern == r"^/api/community/(\d+)/delete$"]
    assert [(r[0], r[2], r[3]) for r in rows] == [("POST", server.delete_community_post, True)]  # signed in, a POST
