"""One account, every page that shows its money, held to one number per figure, against a real MySQL.

The money-trust audit (2026-10-27). One user holds paper, demo and live books at once, with
deployments running, paused and removed, a strategy deleted after its deployment was removed, an
instant paper fill, a part-sold trade still held, a demo reload and an open position in every book.
Its trades are written through the repository layer (no engine, no order) with P&L chosen on the
half cents where the pages used to part: Python's round() rounded the binary float, so one amount
read a cent apart depending on how it was summed (live's removed deployment, -$0.1315 and -$0.6135,
read -$0.74 on one page and -$0.75 on another), and the strategy page added its deployments'
rounded figures (two paper deployments of $0.0050 each read $0.02 beside the list's $0.01).

Every page is then read the way the app reads it: the dashboard (with "since your last visit"), the
strategies list, each strategy page (with its past deployments), Deploy, the track record, Funds, the
autopilot panel and the chat feed, and the agent's own context (what its chat replies quote). Each
figure of one thing must be the same number to the cent on every page that shows it. Live money is
never in a figure with paper or demo money. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import re
import uuid
from datetime import timedelta, timezone
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


@pytest.fixture
def quiet(monkeypatch):
    from app.adapters.stripe import billing
    from app.services import book_memo
    from app.trading import engine
    from app.web.routes import dashboard as dashboard_routes

    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(dashboard_routes, "_freshness", lambda c: {})
    book_memo.clear()
    yield
    book_memo.clear()


def _seed(cur):
    """The account: {uid, sid, dep, visit}. Deployment names: A* Alpha, B1 Beta, C* Gamma, D0 Delta."""
    from app import repository as repo
    from app.trading import spec as specmod

    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "audit@example.invalid", "Audit", None)["id"]
    now = repo.now_utc()
    day = now.replace(hour=0, minute=0, second=0)
    old, visit, lately = now - timedelta(days=3), now - timedelta(hours=48), now - timedelta(hours=30)
    today = max(day + timedelta(minutes=1), now - timedelta(minutes=30))
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "exit": {"stop_loss": 0.1},
                             "sizing": {"stake": 10.0, "max_positions": 4}})
    sid = {k: repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "Audit " + k, "t", spec, "passed",
                                   dict(RESULT)) for k in ("alpha", "beta", "gamma", "delta")}
    dep, n = {}, [0]
    tag = uuid.uuid4().hex[:6].upper()

    def deploy(name, strat, mode):
        dep[name] = repo.create_deployment(cur, uid, sid[strat], "btc15m", mode)

    def closed(name, mode, pnl, ref, at):
        n[0] += 1
        repo.insert_closed_position(cur, dep[name], uid, mode, "KXBTCAU%s-26OCT27-T%d" % (tag, n[0]), "yes", 10, 0.40,
                                    0.07, 0.45, 0.07, pnl, "settled", at, order_ref=ref,
                                    opened_at=at - timedelta(hours=1), closed_at=at)

    def held(name, mode, ref, qty, price):
        repo.insert_position(cur, dep[name], uid, mode, "KXBTCAU%s-26OCT28-H%s" % (tag, name), "yes", qty, price, 0.03,
                             now + timedelta(hours=6), order_ref=ref)

    # Paper: Alpha removed once (A0), then running (A1) and a second, paused copy (A2); Beta paused by its
    # loss guard (B1); Delta removed and then deleted (D0).
    deploy("A0", "alpha", "paper")
    closed("A0", "paper", 0.6175, "sim:a0-1", old)
    closed("A0", "paper", 0.6175, "sim:a0-2", old)
    repo.set_deployment_status(cur, uid, dep["A0"], "stopped", "By you")
    deploy("D0", "delta", "paper")
    closed("D0", "paper", 0.3333, "sim:d0-1", old)
    closed("D0", "paper", 0.3333, "sim:d0-2", lately)
    closed("D0", "paper", -0.0001, "sim:d0-3", lately)
    repo.set_deployment_status(cur, uid, dep["D0"], "stopped", "By you")
    assert repo.delete_strategy(cur, uid, sid["delta"])
    deploy("A1", "alpha", "paper")
    closed("A1", "paper", -0.3325, "sim:a1-1", lately)
    closed("A1", "paper", 0.1105, "sim:a1-2", today)  # a part-sold round trip, now complete
    closed("A1", "paper", 0.1100, "sim:a1-2", today)
    closed("A1", "paper", 0.0450, "sim:a1-3", today)  # a part-sold trade whose rest is still held
    held("A1", "paper", "sim:a1-3", 5, 0.3010)  # $1.5050 at cost, and 5 x 0.301 is 1.50499.. as a float
    closed("A1", "paper", 0.1720, None, today)  # an instant fill: in the book, not in the evidence
    deploy("A2", "alpha", "paper")
    closed("A2", "paper", 0.0050, "sim:a2-1", lately)
    repo.set_deployment_status(cur, uid, dep["A2"], "paused", "By you")
    deploy("B1", "beta", "paper")
    closed("B1", "paper", 0.2025, "sim:b1-1", old)
    closed("B1", "paper", -1.0050, "sim:b1-2", today)
    repo.set_deployment_status(cur, uid, dep["B1"], "paused", "Lost $0.80, more than the $0.50 guard (audit)")
    repo.add_chat(cur, uid, "system", "Paused deployment #%d automatically. Lost $0.80, more than the $0.50 guard "
                                      "(audit)." % dep["B1"])
    # Demo: Alpha's demo copy, reloaded after its first trade.
    deploy("A3", "alpha", "demo")
    closed("A3", "demo", 0.7250, "demo:1", old)
    repo.reload_demo(cur, uid, 750.0)
    closed("A3", "demo", 0.1235, "demo:2", lately)
    closed("A3", "demo", -0.2150, "demo:3", today)
    held("A3", "demo", "demo:4", 7, 0.3005)
    # Live: Gamma removed once (C0, -$0.7450 exactly), then running (C1, +$2.9200): +$2.1750 in all, which
    # the dashboard's float read as $2.17 and the track record's trade-by-trade sum as $2.18.
    deploy("C0", "gamma", "live")
    closed("C0", "live", -0.1315, "live:0", old)
    closed("C0", "live", -0.6135, "live:1", old + timedelta(minutes=1))
    repo.set_deployment_status(cur, uid, dep["C0"], "stopped", "By you")
    deploy("C1", "gamma", "live")
    closed("C1", "live", 0.7334, "live:2", old + timedelta(minutes=2))
    closed("C1", "live", 1.2837, "live:3", lately)
    closed("C1", "live", 0.9029, "live:4", today)
    held("C1", "live", "live:5", 3, 0.3105)
    repo.set_autopilot(cur, uid, True)
    return {"uid": uid, "sid": sid, "dep": dep, "visit": visit, "day": day}


def _c(v) -> float:
    """An exact amount to the cent, half up: what every page must show for it."""
    from trading_core.domain.money import cents

    return cents(v)


def test_every_page_shows_one_number_per_figure(conn, quiet):
    from app import repository as repo
    from app import server
    from app.research import agent

    cur = conn.cursor()
    s = _seed(cur)
    uid, sid, dep, visit, day = s["uid"], s["sid"], s["dep"], s["visit"], s["day"]
    cur.execute("SELECT * FROM app_positions WHERE user_id=%s ORDER BY id", (uid,))
    rows = cur.fetchall()

    def total(pick):
        return sum((Decimal(str(r["pnl"])) for r in rows if r["status"] == "closed" and pick(r)), Decimal(0))

    def of(*names):
        ids = {dep[k] for k in names}
        return lambda r: r["deployment_id"] in ids

    book = {m: total(lambda r, m=m: r["mode"] == m) for m in ("paper", "demo", "live")}
    # The fixture sits on the half cents the pages used to round apart.
    assert book["live"] == Decimal("2.1750") and total(of("C0")) == Decimal("-0.7450") and total(of("C1")) == Decimal("2.9200")
    live_rows = sorted((r for r in rows if r["mode"] == "live" and r["status"] == "closed"), key=lambda r: r["closed_at"])
    assert round(float(book["live"]), 2) != round(sum(float(r["pnl"]) for r in live_rows), 2)  # the old cent apart
    assert total(of("A1")) == Decimal("0.1050") and total(of("A2")) == Decimal("0.0050")

    server._TRACK_RECORD.pop(uid, None)
    server._BACKTEST_CHECKS.clear()
    user = repo.get_user(cur, uid)

    def ctx(*params, **query):
        return server.Ctx(conn, user, tuple(str(p) for p in params), {k: str(v) for k, v in query.items()}, {}, None)

    dash = server.dashboard(ctx(since=int(visit.replace(tzinfo=timezone.utc).timestamp())))
    funds = server.funds(ctx())
    board = server.list_deployments(ctx())
    record = server.get_track_record(ctx())["modes"]
    cards = {c["id"]: c for c in server.list_strategies(ctx())["strategies"]}
    pages = {k: server.get_strategy(ctx(sid[k])) for k in ("alpha", "beta", "gamma")}
    ap = server.autopilot_status(ctx())
    chat = server.get_chat(ctx())["messages"]
    brief = agent._copilot_context(cur, user)
    fb = {"paper": funds["paper"], "demo": funds["demo"], "live": funds["kalshi"]}
    rows_of = lambda listed: {r["id"]: r for r in listed}  # noqa: E731
    dash_rows, board_rows = rows_of(dash["deployments"]), rows_of(board["deployments"])

    # -- realized all time, each book: dashboard, Funds, Deploy (listed + removed), track record ---------------
    for m in ("paper", "live"):
        assert dash[m]["realized_pnl"] == fb[m]["realized_pnl"] == board["realized_by_book"][m]["all"] == _c(book[m]), m
    assert dash["live"]["realized_pnl"] == record["live"]["net_pnl"] == 2.18  # live has no exclusion
    # Live's deployments and its removed one, each rounded once from its own exact sum.
    assert board["realized_by_book"]["live"]["removed"] == -0.75 and board["realized_by_book"]["live"]["listed"] == 2.92
    # Demo: shown since its reload on the dashboard and Funds; its deployment row, the strategies list and
    # page, and the track record all count every demo trade.
    base = total(lambda r: r["mode"] == "demo" and r["closed_at"] < repo.now_utc() - timedelta(days=2))
    assert dash["demo"]["realized_pnl"] == fb["demo"]["realized"] == _c(book["demo"] - base)
    assert (dash_rows[dep["A3"]]["realized_pnl"] == board_rows[dep["A3"]]["realized_pnl"]
            == cards[sid["alpha"]]["real"]["demo"]["pnl"] == pages["alpha"]["book_totals"]["demo"]["pnl"]
            == record["demo"]["net_pnl"] == _c(book["demo"]))

    # -- closed and open counts, open money: dashboard, Funds, Deploy, autopilot panel ----------------------------
    for m in ("paper", "demo", "live"):
        closed_n = sum(1 for r in rows if r["mode"] == m and r["status"] == "closed")
        held = [r for r in rows if r["mode"] == m and r["status"] == "open"]
        cost = _c(sum(Decimal(r["qty"]) * r["entry_price"] for r in held))
        assert dash[m]["closed_trades"] == fb[m]["closed_trades"] == closed_n, m
        assert dash[m]["open_positions"] == fb[m]["open_positions"] == len(held) == 1, m
        assert sum(1 for p in board["open_positions"] if p["mode"] == m) == 1, m
        assert dash[m]["open_at_cost"] == fb[m]["open_at_cost"] == record[m]["open_at_cost"] == cost, m
        # Each open row carries its own cost, rounded as the book's figure is (the pages multiplied it out).
        for listed in (dash["open_positions"], board["open_positions"]):
            [p] = [p for p in listed if p["mode"] == m]
            assert p["at_cost"] == cost and p["cost"] == _c(p["qty"] * p["entry_price"] + p["entry_fee"]), m
        # Cost with its fee: the one basis every page names an open position's cost on. The dashboard and Funds said
        # "$1.51 at cost" for the position Deploy and the strategy page showed at "Cost + fee $1.54". Their book
        # figure is now that same number, rounded once from the exact sum.
        with_fees = _c(sum(Decimal(r["qty"]) * r["entry_price"] + r["entry_fee"] for r in held))
        assert dash[m]["open_cost"] == fb[m]["open_cost"] == with_fees, m
        for listed in (dash["open_positions"], board["open_positions"]):
            assert [p["cost"] for p in listed if p["mode"] == m] == [with_fees], m
        holdings = [h for page in pages.values() for h in page.get("holdings") or [] if h["mode"] == m]
        assert [h["cost"] for h in holdings] == [with_fees], m
    assert (dash["paper"]["open_cost"], dash["paper"]["open_at_cost"]) == (1.54, 1.51)  # 5 x $0.301 + $0.03 fee
    assert dash["paper"]["open_at_cost"] == 1.51 and round(5 * 0.301, 2) == 1.5
    assert ap["paper_open"] == dash["paper"]["open_positions"]
    assert dash["paper"]["equity"] == funds["paper"]["equity"] and dash["paper"]["cash"] == funds["paper"]["cash"]

    # -- today: the dashboard's books and the autopilot panel --------------------------------------------------
    for m in ("paper", "live"):
        assert dash[m]["today_pnl"] == ap["today_%s_pnl" % m] == _c(total(lambda r, m=m: r["mode"] == m and r["closed_at"] >= day))

    # -- since your last visit: each book, and its split by deployment ----------------------------------------
    for m in ("paper", "demo", "live"):
        since = [r for r in rows if r["mode"] == m and r["status"] == "closed" and r["closed_at"] >= visit]
        assert dash["since"]["books"][m] == {"pnl": _c(sum(Decimal(str(r["pnl"])) for r in since)), "trades": len(since)}, m
    split = {r["deployment_id"]: r for r in dash["since"]["by_deployment"]["paper"]}
    assert split[dep["D0"]]["removed"] is True and split[dep["D0"]]["title"] is None  # a deleted strategy
    assert split[dep["A2"]]["pnl"] == dash_rows[dep["A2"]]["realized_pnl"] == 0.01 and "removed" not in split[dep["A2"]]

    # -- each deployment: dashboard, Deploy, its strategy page; a paused one on the autopilot panel and in chat ----
    for name in ("A1", "A2", "B1", "A3", "C1"):
        did = dep[name]
        page = next(r for p in pages.values() for r in p["deployments"] if r["id"] == did)
        assert dash_rows[did]["realized_pnl"] == board_rows[did]["realized_pnl"] == page["realized_pnl"] == _c(total(of(name))), name
        assert dash_rows[did]["closed_trades"] == board_rows[did]["closed_trades"] == page["closed_trades"], name
    [paused] = [p for p in ap["paused_recent"] if p["deployment_id"] == dep["B1"]]
    assert paused["pnl"] == dash_rows[dep["B1"]]["realized_pnl"] == -0.8
    assert any("was paused after 2 paper trades (down $0.80 net of fees and spread)" in line for line in ap["story"])
    [pause_line] = [m["content"] for m in chat if m["content"].startswith("Paused your paper strategy Audit beta")]
    assert "it lost $0.80" in pause_line

    # -- each strategy's book: the strategies list and its page (never the page's own sum of rounded rows) ------
    assert cards[sid["alpha"]]["real"]["pnl"] == pages["alpha"]["book_totals"]["paper"]["pnl"] == _c(total(of("A1", "A2"))) == 0.11
    assert dash_rows[dep["A1"]]["realized_pnl"] + dash_rows[dep["A2"]]["realized_pnl"] == 0.12  # the rows, rounded apart
    assert cards[sid["gamma"]]["real"]["pnl"] == pages["gamma"]["book_totals"]["live"]["pnl"] == 2.92
    assert cards[sid["beta"]]["real"]["pnl"] == pages["beta"]["book_totals"]["paper"]["pnl"] == -0.8
    # Removed deployments: the list's "past", the strategy page's past deployments, and Deploy's removed total.
    for k, name, m in (("alpha", "A0", "paper"), ("gamma", "C0", "live")):
        [past] = pages[k]["past_deployments"]
        assert past["id"] == dep[name] and cards[sid[k]]["past"][m]["pnl"] == past["realized_pnl"] == _c(total(of(name))), k
    assert board["realized_by_book"]["paper"]["removed"] == _c(total(of("A0", "D0")))
    assert board["realized_by_book"]["paper"]["removed_deployments"] == 2  # the deleted strategy's included

    # -- the track record's strategy rows: the strategy's whole book, removed deployments in, deleted named --------
    by = {r["strategy_id"]: r for r in record["live"]["strategies"]}
    assert by[sid["gamma"]]["net_pnl"] == board["realized_by_book"]["live"]["all"] == 2.18
    paper_rows = {r["strategy_id"]: r for r in record["paper"]["strategies"]}
    assert paper_rows[sid["delta"]]["title"] == "Deleted strategy" and paper_rows[sid["delta"]]["removed"] is True
    assert paper_rows[sid["delta"]]["net_pnl"] == _c(total(of("D0")))
    # The autopilot's "furthest on paper" is the strategy's realistic paper record, as the track record's row.
    prog = ap["paper_progress"]
    assert prog["strategy_id"] == sid["alpha"]
    assert (prog["trades"], prog["net_pnl"]) == (paper_rows[sid["alpha"]]["trades"], paper_rows[sid["alpha"]]["net_pnl"])
    # A paper row's backtest line counts that record too, not the row's own trades, and says so beside them.
    a2 = board_rows[dep["A2"]]
    assert a2["backtest_check"]["trades"] == prog["trades"] != a2["closed_trades"]
    assert "so far across all its paper runs, realistic fills only;" in a2["backtest_check"]["line"]

    # -- the agent's context: each book's figure as the dashboard shows it, never one across books ---------------
    money = lambda v: ("-$%.2f" % -v) if v < 0 else "$%.2f" % v  # noqa: E731
    assert ("paper %s over %d closed trades, all time; demo %s since its last reload; live (real money) %s over %d"
            % (money(dash["paper"]["realized_pnl"]), dash["paper"]["closed_trades"], money(dash["demo"]["realized_pnl"]),
               money(dash["live"]["realized_pnl"]), dash["live"]["closed_trades"])) in brief
    assert "paper 1 open, $%.2f entry notional; demo 1 open, $%.2f entry notional; live 1 open, $%.2f entry notional" % (
        dash["paper"]["open_at_cost"], dash["demo"]["open_at_cost"], dash["live"]["open_at_cost"]) in brief
    assert "Aggregate open exposure" not in brief

    # -- live is never in a figure with paper or demo money ----------------------------------------------------
    mixed = {_c(book["live"] + book["paper"]), _c(book["live"] + book["demo"]), _c(book["live"] + book["paper"] + book["demo"])}
    shown = [dash[m][k] for m in ("paper", "demo", "live") for k in ("realized_pnl", "today_pnl")]
    shown += [b.get("all") for b in board["realized_by_book"].values()] + [record[m]["net_pnl"] for m in record]
    shown += [c["real"]["pnl"] for c in cards.values() if c.get("real")]
    assert not mixed & set(shown), (mixed, shown)
    assert not {"$%.2f" % v for v in mixed} & set(re.findall(r"\$\d+\.\d\d", brief))
