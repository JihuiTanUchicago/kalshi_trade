"""The Strategies list against a real MySQL: "best on unseen data first", the autopilot flag, and what
each card's removed deployments made.

The list is paged server-side (50 a page), so finding the best strategy needs the read itself to order
by the unseen-data (out-of-sample) backtest P&L stored in result_json; a page-local sort would miss a
better strategy on page two. A strategy with no unseen test (rejected, tested only, a result with no
P&L) goes last. The card also says when the autopilot found the strategy (its run's brief flag) and,
per book, what its removed deployments made, which together with its active deployment is its book's
whole record. Written through the repository layer only (no engine, no order). Opt in as for
test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
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
    c.cursor().execute("UPDATE app_deployments SET status='stopped' WHERE user_id IN "
                       "(SELECT id FROM app_users WHERE google_sub LIKE 'test:%%')")
    c.close()


def _result(pnl):
    ins = {"trades": 50, "pnl": 99.0, "win_rate": 0.6}  # in-sample: never the order key
    if pnl == "no-oos":
        return {"in_sample": ins}
    if pnl == "no-pnl":
        return {"in_sample": ins, "out_of_sample": {"trades": 3}}
    return {"in_sample": ins, "out_of_sample": {"trades": 20, "pnl": pnl, "win_rate": 0.5}}


def test_the_list_finds_the_best_strategy_flags_the_autopilot_and_keeps_removed_money(conn, monkeypatch):
    from app import repository as repo
    from app import server
    from app.services import book_memo
    from app.trading import spec as specmod

    book_memo.clear()
    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "lister@example.invalid", "L", None)["id"]
    other = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "other@example.invalid", "O", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    ap_run = repo.create_run(cur, uid, "research", "btc15m", None, "angle", brief=True)
    own_run = repo.create_run(cur, uid, "research", "btc15m", "momentum", "my idea")
    sid = {}
    for title, status, pnl, run in (("mid", "passed", 5.0, own_run), ("worst", "passed", -3.25, ap_run),
                                    ("best", "backtest-only", 12.5, ap_run), ("rejected", "rejected", "no-oos", own_run),
                                    ("no pnl", "passed", "no-pnl", None), ("tiny", "passed", 0.5, None)):
        sid[title] = repo.insert_strategy(cur, uid, run, None, "btc15m", "momentum", title, "t", spec, status, _result(pnl))
    repo.insert_strategy(cur, other, None, None, "btc15m", "momentum", "theirs", "t", spec, "passed", _result(500.0))

    user = repo.get_user(cur, uid)

    def page(**query):
        return server.list_strategies(server.Ctx(conn, user, (), {k: str(v) for k, v in query.items()}, {}, None))

    # The seeded example session's strategies list too (marked "example"); these checks read the user's own.
    titles = lambda out: [c["title"] for c in out["strategies"] if not c.get("example")]  # noqa: E731
    # Best first on unseen data, over every status the view shows; no unseen P&L goes last, newest first.
    assert titles(page(sort="best", status="")) == ["best", "mid", "tiny", "worst", "no pnl"]
    assert titles(page(sort="best", status="rejected")) == ["rejected"]
    # It pages in that order: the second page carries on from the first.
    first = repo.list_strategies(cur, uid, sort="best", limit=2, offset=0, hide_noise=True)
    second = repo.list_strategies(cur, uid, sort="best", limit=2, offset=2, hide_noise=True)
    assert [r["title"] for r in first + second] == ["best", "mid", "tiny", "worst"]
    # The default order is unchanged: newest first, rejected last.
    assert titles(page(status="")) == ["tiny", "no pnl", "best", "worst", "mid"]

    # The autopilot's finds are flagged; the user's own and the chat-made ones are not.
    cards = {c["title"]: c for c in page(status="")["strategies"]}
    assert {t for t, c in cards.items() if c.get("by_autopilot")} == {"best", "worst"}

    # Removed deployments: each book's own total, beside the active record, never added in.
    now = repo.now_utc()

    def closed(did, mode, pnl, i):
        repo.insert_closed_position(cur, did, uid, mode, "KXSL-%s-%d" % (uuid.uuid4().hex[:6], i), "yes", 2, 0.5, 0.02,
                                    1.0, 0.0, pnl, "settled", now, opened_at=now - timedelta(hours=1), closed_at=now)

    gone_paper = repo.create_deployment(cur, uid, sid["mid"], "btc15m", "paper")
    closed(gone_paper, "paper", 1.25, 1)
    closed(gone_paper, "paper", -0.5, 2)
    repo.set_deployment_status(cur, uid, gone_paper, "stopped", "By you")
    gone_demo = repo.create_deployment(cur, uid, sid["mid"], "btc15m", "demo")
    closed(gone_demo, "demo", 3.0, 3)
    repo.set_deployment_status(cur, uid, gone_demo, "stopped", "By you")
    empty = repo.create_deployment(cur, uid, sid["mid"], "btc15m", "paper")  # removed before any trade closed
    repo.set_deployment_status(cur, uid, empty, "stopped", "By you")
    live_now = repo.create_deployment(cur, uid, sid["mid"], "btc15m", "paper")
    closed(live_now, "paper", 2.0, 4)
    repo.insert_position(cur, live_now, uid, "paper", "KXSL-OPEN-%s" % uuid.uuid4().hex[:6], "yes", 2, 0.4, 0.02,
                         now + timedelta(hours=1))  # an open position is no closed trade
    book_memo.clear()
    cards = {c["title"]: c for c in page(status="")["strategies"]}
    mid = cards["mid"]
    assert mid["books"] == ["paper"] and mid["real"]["pnl"] == 2.0 and mid["real"]["trades"] == 1
    # Its removed paper trades have no 'sim:' order_ref: instant fills, which the book counts (display only).
    assert mid["past"] == {"paper": {"pnl": 0.75, "trades": 2, "deployments": 2, "instant_fills": 2},
                           "demo": {"pnl": 3.0, "trades": 1, "deployments": 1}}
    # Active + removed paper is the strategy's whole paper book, which the dashboard counts.
    assert round(mid["real"]["pnl"] + mid["past"]["paper"]["pnl"], 2) == round(repo.realized_pnl(cur, uid, "paper"), 2)
    assert all("past" not in c for t, c in cards.items() if t != "mid")


def test_the_list_flags_a_paper_book_of_instant_fills_as_the_track_record_leaves_it_out(conn):
    """A strategy whose only paper trades were instant fills (no 'sim:' order_ref) read "+$3.80 on paper since
    deploying · 2 trades" on the list, while the track record gave it a row saying all its trades were instant
    fills, left out of the record. The list's flag is the track record's split, read from the same rows."""
    from app import repository as repo
    from app import server
    from app.services import book_memo
    from app.trading import spec as specmod

    book_memo.clear()
    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "instant@example.invalid", "I", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}})
    close = repo.now_utc() - timedelta(hours=2)
    sid, dep_of = {}, {}
    for title, refs in (("instant", [None, None]), ("venue", ["sim:1", "sim:2"]), ("mixed", ["sim:3", None])):
        sid[title] = repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", title, "t", spec, "passed", _result(1.0))
        dep = dep_of[title] = repo.create_deployment(cur, uid, sid[title], "btc15m", "paper")
        for i, ref in enumerate(refs):
            repo.insert_closed_position(cur, dep, uid, "paper", "KXBTC15M-26OCT2517-T98", "yes", 1, 0.40, 0.02, 1.0, 0.0,
                                        1.9, "settled", close, order_ref=ref, opened_at=close - timedelta(minutes=9 - i),
                                        closed_at=close + timedelta(minutes=i))
    conn.commit()
    user = repo.get_user(cur, uid)
    out = server.list_strategies(server.Ctx(conn, user, (), {"status": ""}, {}, None))
    cards = {c["title"]: c for c in out["strategies"] if not c.get("example")}
    assert cards["instant"]["real"]["instant_only"] is True
    assert (cards["instant"]["real"]["trades"], cards["instant"]["real"]["pnl"]) == (2, 3.8)  # the figure is unchanged
    assert "instant_only" not in cards["venue"]["real"] and "instant_only" not in cards["mixed"]["real"]
    # The track record says the same of each: only "instant" is a row of instant fills left out.
    rows = {r["title"]: r for r in book_memo.track_record(cur, uid)["modes"]["paper"]["strategies"]}
    assert {t for t, r in rows.items() if r["instant_only"]} == {t for t, c in cards.items() if c["real"].get("instant_only")}
    # Partly instant fills: the card counts them as the track record's row does (1 of "mixed"'s 2), and the
    # strategy page's paper book says the same; none on "venue". The figures and counts are unchanged.
    assert {t: c["real"].get("instant_fills", 0) for t, c in cards.items()} == {"instant": 2, "venue": 0, "mixed": 1}
    assert {t: r["excluded_instant_fills"] for t, r in rows.items()} == {"instant": 2, "venue": 0, "mixed": 1}
    for title, n in (("instant", 2), ("venue", 0), ("mixed", 1)):
        books = server.get_strategy(server.Ctx(conn, user, (str(sid[title]),), {}, {}, None))["book_totals"]
        assert books["paper"].get("instant_fills", 0) == n and books["paper"]["trades"] == 2
    # Each paper deployment row says the same, on Deploy (beside "0/30 trades" toward live), the dashboard and
    # the strategy page; its closed count is unchanged.
    for read in (lambda: server.list_deployments(server.Ctx(conn, user, (), {}, {}, None))["deployments"],
                 lambda: server.dashboard(server.Ctx(conn, user, (), {}, {}, None))["deployments"]):
        rows = {r["title"]: r for r in read() if r["mode"] == "paper"}
        assert {t: (r["closed_trades"], r.get("instant_fills", 0)) for t, r in rows.items()} == {
            "instant": (2, 2), "venue": (2, 0), "mixed": (2, 1)}
    for title, n in (("instant", 2), ("venue", 0), ("mixed", 1)):
        deps = server.get_strategy(server.Ctx(conn, user, (str(sid[title]),), {}, {}, None))["deployments"]
        assert [d.get("instant_fills", 0) for d in deps] == [n]
    # Kept while the positions are unchanged: a second page read asks again for nothing.
    assert server.list_strategies(server.Ctx(conn, user, (), {"status": ""}, {}, None))["strategies"] == out["strategies"]
    # Removed, each card's "Removed from paper" book says the same of its trades, from the removed totals' own read.
    for title in dep_of:
        repo.set_deployment_status(cur, uid, dep_of[title], "stopped", "By you")
    conn.commit()
    cards = {c["title"]: c for c in server.list_strategies(server.Ctx(conn, user, (), {"status": ""}, {}, None))["strategies"]
             if not c.get("example")}
    assert {t: (c["past"]["paper"]["trades"], c["past"]["paper"].get("instant_fills", 0)) for t, c in cards.items()} == {
        "instant": (2, 2), "venue": (2, 0), "mixed": (2, 1)}


def test_a_null_pnl_sorts_last_and_a_search_matches_its_words_literally(conn):
    """A later-period P&L stored as JSON null ({"pnl": null}) shows "—" on its row, and the "Later-period P&L" sort
    put it among the $0.00 rows: MySQL's JSON_EXTRACT gives a JSON null there, not SQL NULL, and it cast to 0. It goes
    last with the rows that have no figure. And a search for "_" listed every strategy (LIKE's one-character
    wildcard), "50%" every title with a 50 in it: the list and its counts match the words as typed."""
    from app import repository as repo
    from app import server
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "nullsort@example.invalid", "N", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}})
    null_pnl = {"in_sample": {"trades": 5, "pnl": 1.0}, "out_of_sample": {"trades": 0, "pnl": None}}
    for title, res in (("zero", _result(0.0)), ("json null", null_pnl), ("loss", _result(-0.04)), ("gain", _result(0.5)),
                       ("no oos", _result("no-oos")), ("50% off_sale", _result(2.0)), ("plain 50 title", _result(1.0))):
        repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", title, "t", spec, "passed", res)
    conn.commit()
    user = repo.get_user(cur, uid)

    def page(**query):
        return server.list_strategies(server.Ctx(conn, user, (), {k: str(v) for k, v in query.items()}, {}, None))

    titles = lambda out: [c["title"] for c in out["strategies"] if not c.get("example")]  # noqa: E731
    # Highest first, negative below zero; every row without a figure last, newest first.
    assert titles(page(sort="best", status="")) == ["50% off_sale", "plain 50 title", "gain", "zero", "loss", "no oos", "json null"]
    for q, want in (("_", ["50% off_sale"]), ("50%", ["50% off_sale"]), ("50", ["plain 50 title", "50% off_sale"]),
                    ("%", ["50% off_sale"]), ("e_s", [])):
        out = page(status="", q=q)
        assert titles(out) == want, q
        # The counts read the same clause, so the chips count what the search lists.
        assert out["counts"]["total"] == len(want), q


def test_a_shared_copy_names_its_sharer_as_the_community_does_never_by_email(conn):
    """Walk 2026-10-31: a sharer whose Google name is their email address showed that address to the recipient on the
    list and the page ("Shared by dana.private@example.com"), and a sharer with no name had no "Shared by" at all.
    Both reads (the list's and the page's) carry the sharer's @handle for that."""
    from app import repository as repo
    from app.trading import spec as specmod
    from app.web.routes.strategies import _strategy_card

    cur = conn.cursor()
    tag = uuid.uuid4().hex[:8]
    to = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "to-%s@example.invalid" % tag, "To", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 1}})
    want = {}
    for name in ("dana-%s@example.invalid" % tag, None, "Pat Named"):
        sender = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "s%d-%s@example.invalid" % (len(want), tag), name, None)
        src = repo.insert_strategy(cur, sender["id"], None, None, "btc15m", "momentum", "shared %d" % len(want), "t", spec,
                                   "passed", _result(1.0))
        copy = repo.share_strategy(cur, src, sender["id"], to)
        want[copy] = name if name == "Pat Named" else "@" + sender["username"]
    listed = {s["id"]: _strategy_card(s)["shared_from"] for s in repo.list_strategies(cur, to) if s["id"] in want}
    assert listed == want
    for copy, shown in want.items():
        assert _strategy_card(repo.get_strategy(cur, to, copy))["shared_from"] == shown
    assert not any("@example.invalid" in v for v in listed.values())
