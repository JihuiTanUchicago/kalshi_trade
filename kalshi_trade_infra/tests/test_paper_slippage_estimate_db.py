"""The paper "after typical live slippage" estimate agrees with the positions it is made from, against a
real MySQL, and the gates never see it. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).

One user, one strategy on paper, live and demo at once, plus a paper deployment that was removed. Paper
holds every kind of row: a trade sold before settlement (an entry fill and an exit fill), one held to
settlement (the entry fill alone), a stop that sold part and kept the rest open, a stop that sold part
and let the rest settle, an instant fill and an open position. Each page's estimate is held to the
position rows themselves, read here with a plain SELECT: paper realized P&L of the rows that page counts,
less 0.5c times each closed row's contracts times its fills (two, or one when settled). Live and demo get
none. The gate inputs come out identical whatever the assumption is.
"""
import os
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

RESULT = {"capital": 40.0, "out_of_sample": {"trades": 40, "pnl": 6.0, "win_rate": 0.61},
          "in_sample": {"trades": 90, "pnl": 30.0, "win_rate": 0.7}}


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


def _experiment(cur, uid, strategy_id):
    """A pre-registered experiment (a gatekeeper record) for the user, linked to `strategy_id` when given."""
    from app.research import research_repository as rr
    from app.trading import spec as specmod

    return rr.preregister(cur, dict(
        user_id=uid, run_id=None, strategy_id=strategy_id, market="btc15m", hypothesis_hash=uuid.uuid4().hex,
        spec=specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}}), economic_rationale="m",
        primary_metric="mean_net_return_per_trade", null_hypothesis="edge<=0", alt_hypothesis="edge>0",
        planned_test="stationary_bootstrap", falsification_criteria="ci_lo<=0", min_sample=30, cost_assumptions={},
        research_partition_id=0, planned_n_tests=1, correction_method="BH"))


def _expected(rows, per=Decimal("0.005")):
    """Paper realized P&L of `rows` less `per` a contract fill, rounded once half up: from the rows alone."""
    from trading_core.domain.money import cents

    pnl = sum((Decimal(str(r["pnl"])) for r in rows), Decimal(0))
    fills = sum(int(r["qty"]) * (1 if r["close_reason"] == "settled" else 2) for r in rows)
    return cents(pnl - per * fills), cents(pnl), fills


def test_each_pages_estimate_agrees_with_the_positions_and_the_gates_never_see_it(conn, monkeypatch):
    from app import repository as repo
    from app import server
    from app.research import agent
    from app.services import book_memo
    from app.trading import spec as specmod
    from app.web.routes import dashboard as dashboard_routes
    from trading_core.domain import slippage

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "slip@example.com", "S", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "exit": {"stop_loss": 0.1},
                             "sizing": {"stake": 10.0, "max_positions": 4}})
    sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Slip check", "t", spec, "passed", dict(RESULT))
    dep = {m: repo.create_deployment(cur, uid, sid, "btc15m", m) for m in ("paper", "live", "demo")}
    removed = repo.create_deployment(cur, uid, sid, "btc15m", "paper")
    tag = uuid.uuid4().hex[:6].upper()
    close = repo.now_utc() + timedelta(hours=1)

    def tk(n):
        return "KXSLIP%s-%s" % (tag, n)

    def closed(did, mode, n, qty, price, exit_price, reason, ref):
        fee = 0.07
        pnl = qty * (exit_price - price) - fee - (0.0 if reason == "settled" else fee)
        repo.insert_closed_position(cur, did, uid, mode, tk(n), "yes", qty, price, fee, exit_price,
                                    0.0 if reason == "settled" else fee, pnl, reason, close, order_ref=ref)

    def opened(did, n, qty, price, ref):
        return repo.insert_position(cur, did, uid, "paper", tk(n), "yes", qty, price, 0.08, close, ref)

    def part_sell(pid, qty, price, reason):
        pos = next(p for p in repo.open_positions(cur, dep["paper"]) if p["id"] == pid)
        pnl = qty * (price - float(pos["entry_price"])) - float(pos["entry_fee"]) * qty / int(pos["qty"]) - 0.03
        assert repo.book_partial_exit(cur, pos, qty, price, 0.03, pnl, reason)

    # Paper, listed.
    closed(dep["paper"], "paper", "A", 10, 0.40, 0.55, "take_profit", "sim:a")  # sold before settlement: 20 fills
    closed(dep["paper"], "paper", "B", 6, 0.62, 1.00, "settled", "sim:b")       # held to settlement: 6 fills
    closed(dep["paper"], "paper", "C", 5, 0.70, 0.00, "settled", "sim:c")       # a settled loss: 5 fills
    p = opened(dep["paper"], "D", 8, 0.45, "sim:d")
    part_sell(p, 3, 0.38, "stop")                                                # 3 sold (6 fills), 5 still open
    p = opened(dep["paper"], "E", 4, 0.50, "sim:e")
    part_sell(p, 1, 0.44, "stop")                                                # 1 sold (2 fills) ...
    pos = repo.open_positions(cur, dep["paper"])[-1]
    assert repo.close_position(cur, pos["id"], 1.0, 0.0, 3 * 0.5 - float(pos["entry_fee"]), "settled")  # ... 3 settled (3)
    closed(dep["paper"], "paper", "F", 2, 0.30, 0.35, "take_profit", None)      # an instant fill: 4 fills
    opened(dep["paper"], "G", 5, 0.20, "sim:g")                                  # open: no fill counted yet
    # Paper, removed: still in the book (dashboard, track record), not in "Since deploying".
    closed(removed, "paper", "H", 7, 0.33, 0.41, "take_profit", "sim:h")
    assert repo.set_deployment_status(cur, uid, removed, "stopped")
    # Live and demo: real fills, never estimated.
    closed(dep["live"], "live", "A", 9, 0.40, 0.55, "take_profit", "live:a")
    closed(dep["demo"], "demo", "A", 4, 0.40, 1.00, "settled", "demo:a")

    cur.execute("SELECT id, deployment_id, mode, qty, pnl, status, close_reason, order_ref FROM app_positions WHERE user_id=%s",
                (uid,))
    rows = list(cur.fetchall())
    paper_closed = [r for r in rows if r["mode"] == "paper" and r["status"] == "closed"]

    monkeypatch.setattr(dashboard_routes, "_freshness", lambda c: {})
    user = repo.get_user(cur, uid)

    def ctx(*params):
        return server.Ctx(conn, user, tuple(str(x) for x in params), {}, {}, None)

    def pages():
        book_memo.clear()
        server._TRACK_RECORD.pop(uid, None)
        return server.dashboard(ctx()), server.get_strategy(ctx(sid)), server.get_track_record(ctx())["modes"]

    dash, page, record = pages()

    # The dashboard: every closed paper row, the removed deployment's included (its realized_pnl's rows).
    est, pnl, fills = _expected(paper_closed)
    assert fills == 20 + 6 + 5 + 6 + 2 + 3 + 4 + 14
    assert dash["paper"]["realized_pnl"] == pnl  # unchanged: the estimate rides beside it
    assert dash["paper"]["slippage_estimate"] == {"pnl": est, "per_fill_cents": 0.5}
    assert est < pnl
    for m in ("live", "demo"):
        assert "slippage_estimate" not in dash[m]

    # The strategy page's "Since deploying": the listed paper deployment's closed rows only.
    listed = [r for r in paper_closed if r["deployment_id"] == dep["paper"]]
    est, pnl, _ = _expected(listed)
    books = page["book_totals"]
    assert books["paper"]["pnl"] == pnl and books["paper"]["slippage_estimate"] == {"pnl": est, "per_fill_cents": 0.5}
    assert "slippage_estimate" not in books["live"] and "slippage_estimate" not in books["demo"]

    # The track record's paper tab: whole trades through the simulated venue (slices summed by order_ref),
    # none still part-open, no instant fill; the removed deployment's trade stays in.
    trades = {}
    for r in (r for r in rows if r["mode"] == "paper"):
        trades.setdefault((r["deployment_id"], r["order_ref"] or "row:%d" % r["id"]), []).append(r)
    in_record = [s for (_, ref), slices in trades.items() if str(ref).startswith("sim:")
                 and all(x["status"] == "closed" for x in slices) for s in slices]
    est, pnl, fills = _expected(in_record)
    assert fills == 20 + 6 + 5 + (2 + 3) + 14  # D (part-open) and F (instant) are out of the record
    assert record["paper"]["net_pnl"] == pnl
    assert record["paper"]["slippage_estimate"] == {"pnl": est, "per_fill_cents": 0.5}
    assert record["live"]["slippage_estimate"] is None and record["demo"]["slippage_estimate"] is None

    # The gate inputs and the paper -> live evidence are the same whatever the assumption: none reads it.
    def gates():
        return (repo.paper_round_trips(cur, uid, sid), repo.paper_fills_for_gate(cur, uid, sid),
                repo.list_deployments(cur, uid, include_stopped=True), agent.paper_evidence(cur, uid, sid))

    before = gates()
    monkeypatch.setattr(slippage, "LIVE_SLIPPAGE_PER_CONTRACT_FILL", Decimal("1"))
    after = gates()
    assert after == before
    assert all("contract_fills" not in d and "slippage_estimate" not in d for d in after[2])
    # The pages did take the new assumption (so the check above had teeth), and only the estimate moved.
    dash2, page2, record2 = pages()
    assert dash2["paper"]["slippage_estimate"]["pnl"] == _expected(paper_closed, Decimal("1"))[0]
    assert dash2["paper"]["realized_pnl"] == dash["paper"]["realized_pnl"]
    assert page2["book_totals"]["paper"]["pnl"] == books["paper"]["pnl"]
    assert record2["paper"]["net_pnl"] == record["paper"]["net_pnl"]


def test_deploy_the_strategies_list_and_the_autopilot_carry_it_from_the_reads_they_already_make(conn, monkeypatch):
    """The Deploy board's paper Realized, the Strategies list's paper card, the autopilot's paper day and its
    week each carry the estimate, held to the position rows that figure counts; live and demo never do. A
    backtest-only strategy's Deploy row says so (backtest_only) from the row's own read. The gate's
    list_deployments carries none of it."""
    from app import repository as repo
    from app import server
    from app.services import book_memo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "slip2@example.com", "S", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "exit": {"stop_loss": 0.1},
                             "sizing": {"stake": 10.0, "max_positions": 4}})
    a = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Paper and demo", "t", spec, "passed", dict(RESULT))
    c = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Live and paper", "t", spec, "passed", dict(RESULT))
    b = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Old loose gate", "t", spec, "backtest-only", dict(RESULT))
    # A and C passed with a gatekeeper record (A's linked by its strategy id, as before experiment_id existed; C's
    # stored), so their rows claim nothing; a pass with none says later-period (test_..._no_gatekeeper_record...).
    _experiment(cur, uid, a)
    repo.set_strategy_outcome(cur, c, "passed", dict(RESULT), experiment_id=_experiment(cur, uid, None))
    repo.create_proposal(cur, uid, "deploy", "Autopilot", None, a, "applied")  # the autopilot put A on paper
    dep = {"a_paper": repo.create_deployment(cur, uid, a, "btc15m", "paper"),
           "a_demo": repo.create_deployment(cur, uid, a, "btc15m", "demo"),
           "c_live": repo.create_deployment(cur, uid, c, "btc15m", "live"),
           "c_paper": repo.create_deployment(cur, uid, c, "btc15m", "paper"),
           "b_paper": repo.create_deployment(cur, uid, b, "btc15m", "paper")}
    removed = repo.create_deployment(cur, uid, a, "btc15m", "paper")
    tag = uuid.uuid4().hex[:6].upper()
    close = repo.now_utc() + timedelta(hours=1)
    n = iter(range(100))

    def closed(did, mode, qty, price, exit_price, reason, ref):
        fee = 0.07
        pnl = qty * (exit_price - price) - fee - (0.0 if reason == "settled" else fee)
        repo.insert_closed_position(cur, did, uid, mode, "KXSLIQ%s-%d" % (tag, next(n)), "yes", qty, price, fee, exit_price,
                                    0.0 if reason == "settled" else fee, pnl, reason, close, order_ref=ref)

    closed(dep["a_paper"], "paper", 10, 0.40, 0.55, "take_profit", "sim:a1")  # 20 fills
    closed(dep["a_paper"], "paper", 6, 0.62, 1.00, "settled", "sim:a2")      # 6 fills
    closed(dep["a_demo"], "demo", 4, 0.40, 1.00, "settled", "demo:a")
    closed(dep["c_live"], "live", 9, 0.40, 0.55, "take_profit", "live:c")
    closed(dep["c_paper"], "paper", 3, 0.50, 0.00, "settled", "sim:c")       # 3 fills
    closed(dep["b_paper"], "paper", 2, 0.30, 0.36, "take_profit", "sim:b")   # 4 fills
    closed(removed, "paper", 7, 0.33, 0.41, "take_profit", "sim:r")          # 14 fills, no longer listed
    assert repo.set_deployment_status(cur, uid, removed, "stopped")

    cur.execute("SELECT deployment_id, mode, qty, pnl, status, close_reason FROM app_positions WHERE user_id=%s", (uid,))
    rows = list(cur.fetchall())
    paper = [r for r in rows if r["mode"] == "paper" and r["status"] == "closed"]

    def est(rs):
        return {"pnl": _expected(rs)[0], "per_fill_cents": 0.5}

    def of(*ids):
        return [r for r in paper if r["deployment_id"] in ids]

    ctx = server.Ctx(conn, repo.get_user(cur, uid), (), {}, {}, None)
    book_memo.clear()

    # Deploy: the listed paper deployments' Realized, never the removed one's (its "all" counts it, unestimated).
    board = server.list_deployments(ctx)
    books = board["realized_by_book"]
    listed = of(dep["a_paper"], dep["c_paper"], dep["b_paper"])
    assert books["paper"]["listed"] == _expected(listed)[1]
    assert books["paper"]["slippage_estimate"] == est(listed)
    assert books["paper"]["all"] == _expected(paper)[1] and books["paper"]["removed_deployments"] == 1
    assert "slippage_estimate" not in books["live"] and "slippage_estimate" not in books["demo"]
    # A backtest-only strategy's row says so, from the row's own read; the rest don't.
    by = {r["id"]: r for r in board["deployments"]}
    assert by[dep["b_paper"]]["backtest_only"] is True
    assert not any(by[dep[k]]["backtest_only"] for k in ("a_paper", "a_demo", "c_live", "c_paper"))

    # The Strategies list: a paper card carries its listed paper book's estimate; a live card shows live, unestimated.
    cards = {s["id"]: s for s in server.list_strategies(ctx)["strategies"]}
    assert cards[a]["real"]["mode"] == "paper" and cards[a]["real"]["slippage_estimate"] == est(of(dep["a_paper"]))
    assert "slippage_estimate" not in cards[a]["real"]["demo"]
    assert cards[c]["real"]["mode"] == "live" and "slippage_estimate" not in cards[c]["real"]
    assert cards[b]["real"]["slippage_estimate"] == est(of(dep["b_paper"])) and cards[b]["status"] == "backtest-only"

    # The autopilot: the paper day (every paper trade closed today, the removed deployment's included), and its
    # week (the paper trades of the strategies it put on paper: A's, listed or removed).
    status = server.autopilot_status(ctx)
    assert status["today_paper_pnl"] == _expected(paper)[1]
    assert status["today_paper_slippage_estimate"] == est(paper)
    week = server._autopilot_week(cur, uid, {})
    mine = of(dep["a_paper"], removed)
    assert week["paper_pnl"] == _expected(mine)[1] and week["paper_trades"] == len(mine)
    assert week["paper_slippage_estimate"] == est(mine)

    # The gate's read carries none of the display columns.
    assert all("strategy_status" not in d and "contract_fills" not in d
               for d in repo.list_deployments(cur, uid, include_stopped=True))


def test_a_passed_strategy_with_no_gatekeeper_record_says_later_period_on_every_deployment_row(conn):
    """The strategy page calls a backtest's later slice "Later-period P&L" for a backtest-only strategy and for a
    "passed" one with no gatekeeper record (no experiment, stored or linked by its strategy id); the Overview's
    deployment details said "Unseen P&L" for the second. Every deployment row says so (backtest_only), from the
    deployment read itself: the full read and the kept one (book_memo's) agree, on the dashboard, Deploy and the
    strategy page, while a pass with a record, stored or legacy, claims nothing."""
    from app import repository as repo
    from app import server
    from app.services import book_memo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "norecord@example.com", "N", None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 2}})

    def strat(title, status):
        return repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", title, "t", spec, status, dict(RESULT))

    sids = {"none": strat("Passed, no record", "passed"), "stored": strat("Passed, stored record", "passed"),
            "legacy": strat("Passed, legacy record", "passed"), "old": strat("Old loose gate", "backtest-only"),
            "void": strat("Void", "failed"), "void_kept": strat("Void, stored record", "failed")}
    repo.set_strategy_outcome(cur, sids["stored"], "passed", dict(RESULT), experiment_id=_experiment(cur, uid, None))
    repo.set_strategy_outcome(cur, sids["void_kept"], "failed", dict(RESULT), experiment_id=_experiment(cur, uid, None))
    _experiment(cur, uid, sids["legacy"])
    _experiment(cur, uid, None)  # another experiment of the same user, linked to nothing, changes nothing
    deps = {k: repo.create_deployment(cur, uid, sid, "btc15m", "paper") for k, sid in sids.items()}
    # The void has no record either: the first version's simple backtest stored it as failed, never judged on held-out
    # data, so its rows say "not held out" too (void_no_record, VOID_NO_RECORD_SQL), as its Strategies row and page do.
    # This case said False for it, which left its rows saying "unseen data".
    want = {deps["none"]: True, deps["stored"]: False, deps["legacy"]: False, deps["old"]: True, deps["void"]: True,
            deps["void_kept"]: False}

    ctx = server.Ctx(conn, repo.get_user(cur, uid), (), {}, {}, None)
    book_memo.clear()
    for read in range(2):  # the full read, then the kept one (the positions haven't changed)
        dash = {r["id"]: r["backtest_only"] for r in server.dashboard(ctx)["deployments"]}
        board = {r["id"]: r["backtest_only"] for r in server.list_deployments(ctx)["deployments"]}
        assert dash == want and board == want, read
        # Only the void with no record says so (its hover leaves out "which picked it"), on both.
        for rows in (server.dashboard(ctx)["deployments"], server.list_deployments(ctx)["deployments"]):
            assert {r["id"] for r in rows if r.get("void_no_record")} == {deps["void"]}, read
    page = server.get_strategy(server.Ctx(conn, repo.get_user(cur, uid), (str(sids["none"]),), {}, {}, None))
    assert [d["backtest_only"] for d in page["deployments"]] == [True]
    # The read the engine and the gates use carries none of it.
    assert all("no_gatekeeper_record" not in d and "void_no_record" not in d for d in repo.list_deployments(cur, uid))
