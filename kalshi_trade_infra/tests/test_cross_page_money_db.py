"""The cross-page money audit (2026-10-31): one customer's mixed book, every page that claims the same quantity,
held to one figure, against a real MySQL.

The account, walked as a customer in both themes at 390px and 1366px: a paper strategy running with two open
positions of $1.005 each with fee (one marked, one not) and closed trades on three days, one minutes after 00:00 UTC;
a paper deployment removed and its strategy deleted after it traded; a demo copy reloaded between trades with one
open position; a live strategy running with an open position and a second live one paused after a loss stop;
credits bought, a welcome bonus and research and check-in spend with fractions of a cent.

Each quantity is read the way the app reads it on every page that shows it (the dashboard, Funds, Deploy, the
Strategies list, the strategy page, the autopilot panel, Billing and /api/me) and must be one figure:
  - realized P&L per book; closed trades and open positions per book; today's realized P&L (UTC);
  - each book's open cost with fees, the strategy page's included: its holdings line added its rows' rounded costs
    and read $2.02 beside the dashboard's and Funds' $2.01 for the same two positions (holdings_books now);
  - each deployment's unrealized P&L (its marked positions, as each page lists them);
  - "since deploying" per strategy and book (the Strategies list and the strategy page);
  - the credits balance and the week's spend (Billing, /api/me, the dashboard strip and the autopilot panel).
Live money is never in a figure with paper or demo money, and credits are never in a P&L figure.
The pages' own rounding of these figures is pinned by tests/money_audit_frontend_cases.mjs.
Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).
"""
import os
import uuid
from datetime import timedelta, timezone
from decimal import Decimal

import pytest

from trading_core.domain.money import cents

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
def pages(monkeypatch):
    """Payments on in-process with every Stripe call refused (no card is read), live trading closed, no freshness
    read, the display memos cleared."""
    from app.adapters.stripe import billing
    from app.services import book_memo
    from app.trading import engine
    from app.web.routes import dashboard as dashboard_routes

    def no_network(*a, **k):
        raise billing.StripeError("no network in tests")

    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "sk_test_cross_page_money")
    monkeypatch.setattr(billing, "FREE_BONUS", Decimal("20"))
    monkeypatch.setattr(billing, "_stripe", no_network)
    monkeypatch.setattr(billing, "list_cards", lambda customer_id: [])
    monkeypatch.setattr(engine, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(dashboard_routes, "_freshness", lambda c: {})
    book_memo.clear()
    yield
    book_memo.clear()


def _seed(cur):
    from app import repository as repo
    from app.trading import spec as specmod

    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "crosspage@example.invalid", "Riley", None)["id"]
    now = repo.now_utc()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = max(day + timedelta(minutes=1), now - timedelta(minutes=30))
    spec = specmod.validate({"side": "no", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}})
    sid = {k: repo.insert_strategy(cur, uid, None, None, "btc15m", "custom", "Cross " + k, "t", spec, "passed", dict(RESULT))
           for k in ("fade", "drift", "live", "spike")}
    tag = uuid.uuid4().hex[:6].upper()
    n = [0]
    dep = {}

    def deploy(name, strat, mode):
        dep[name] = repo.create_deployment(cur, uid, sid[strat], "btc15m", mode)

    def closed(name, mode, pnl, at):
        n[0] += 1
        repo.insert_closed_position(cur, dep[name], uid, mode, "KXBTCCP%s-26OCT31-C%d" % (tag, n[0]), "no", 3, 0.40, 0.05,
                                    0.45, 0.05, pnl, "settled", at, order_ref="%s:cp%d" % ("sim" if mode == "paper" else mode, n[0]),
                                    opened_at=at - timedelta(minutes=12), closed_at=at)

    def held(name, mode, qty, price, fee, mark=None):
        n[0] += 1
        pid = repo.insert_position(cur, dep[name], uid, mode, "KXBTCCP%s-26NOV01-H%d" % (tag, n[0]), "no", qty, price, fee,
                                   now + timedelta(hours=6), order_ref="%s:cp%d" % ("sim" if mode == "paper" else mode, n[0]))
        if mark is not None:
            cur.execute("UPDATE app_positions SET mark_price=%s, mark_ts=%s WHERE id=%s", (mark, now - timedelta(seconds=30), pid))

    # Paper: a removed deployment whose strategy was then deleted; the running one, two open positions of $1.005.
    deploy("R", "drift", "paper")
    closed("R", "paper", 0.3000, now - timedelta(days=4))
    repo.set_deployment_status(cur, uid, dep["R"], "stopped", "By you")
    assert repo.delete_strategy(cur, uid, sid["drift"])
    deploy("P", "fade", "paper")
    closed("P", "paper", -0.1315, now - timedelta(days=2))
    closed("P", "paper", -0.6135, now - timedelta(days=1))
    closed("P", "paper", 0.2225, today)
    held("P", "paper", 3, 0.315, 0.06, mark=0.60)
    held("P", "paper", 3, 0.315, 0.06)  # not marked yet
    # Demo: the same strategy's demo copy, reloaded between its trades, one open.
    deploy("D", "fade", "demo")
    closed("D", "demo", 0.7250, now - timedelta(days=3))
    repo.reload_demo(cur, uid, 250.0)
    closed("D", "demo", -0.2150, today)
    held("D", "demo", 3, 0.405, 0.0525, mark=0.47)
    # Live: one running with an open position, one paused after a loss stop (today's loss).
    deploy("L", "live", "live")
    closed("L", "live", 1.0875, now - timedelta(days=3))
    closed("L", "live", 0.9465, today)
    held("L", "live", 2, 0.4805, 0.0335, mark=0.395)
    deploy("S", "spike", "live")
    closed("S", "live", -0.4325, now - timedelta(days=1))
    closed("S", "live", -0.5865, today)
    repo.set_deployment_status(cur, uid, dep["S"], "paused", "Lost $1.02 today, more than its $1.00 daily loss limit.")
    # Credits: the welcome bonus, a top-up and spend with fractions of a cent.
    repo.ensure_welcome_bonus(cur, uid)
    repo.add_credit(cur, uid, "topup", 25, "Added credits", stripe_ref="pi_cross_%s" % tag)
    for usd in (1.335, 0.905):
        rid = repo.create_run(cur, uid, "research", "btc15m", None, "Fade late YES", max_hypotheses=6)
        repo.add_credit(cur, uid, "usage", -usd, "Agent usage", run_id=rid)
    for _ in range(3):
        rid = repo.create_run(cur, uid, "review", prompt="scheduled autopilot review")
        repo.add_credit(cur, uid, "usage", -0.0625, "Agent usage", run_id=rid)
    repo.set_autopilot(cur, uid, True)
    return {"uid": uid, "sid": sid, "dep": dep, "day": day}


def test_every_page_shows_one_figure_per_quantity(conn, pages):
    from app import repository as repo
    from app import server

    cur = conn.cursor()
    s = _seed(cur)
    uid, sid, dep, day = s["uid"], s["sid"], s["dep"], s["day"]
    cur.execute("SELECT * FROM app_positions WHERE user_id=%s ORDER BY id", (uid,))
    rows = cur.fetchall()
    server._TRACK_RECORD.pop(uid, None)
    user = repo.get_user(cur, uid)

    def ctx(*params, **query):
        return server.Ctx(conn, user, tuple(str(p) for p in params), {k: str(v) for k, v in query.items()}, {}, None)

    def exact(pick):
        return sum((Decimal(str(r["pnl"])) for r in rows if r["status"] == "closed" and pick(r)), Decimal(0))

    dash = server.dashboard(ctx())
    funds = server.funds(ctx())
    board = server.list_deployments(ctx())
    cards = {c["id"]: c for c in server.list_strategies(ctx())["strategies"]}
    page = {k: server.get_strategy(ctx(sid[k])) for k in ("fade", "live", "spike")}
    ap = server.autopilot_status(ctx())
    bill = server.billing_state(ctx())
    me = server.me(ctx())
    record = server.get_track_record(ctx())["modes"]
    fb = {"paper": funds["paper"], "demo": funds["demo"], "live": funds["kalshi"]}

    # -- realized all time, per book: the dashboard, Funds and Deploy (live and paper; demo shows since its reload) --
    for m in ("paper", "live"):
        assert dash[m]["realized_pnl"] == fb[m]["realized_pnl"] == board["realized_by_book"][m]["all"] == cents(exact(
            lambda r, m=m: r["mode"] == m)), m
    assert dash["paper"]["realized_pnl"] == -0.22  # -$0.2225 exactly, the removed deployment's +$0.30 in it
    assert dash["demo"]["realized_pnl"] == fb["demo"]["realized"] == -0.22  # since its reload

    # -- closed trades and open positions, per book --------------------------------------------------------------
    for m in ("paper", "demo", "live"):
        closed_n = sum(1 for r in rows if r["mode"] == m and r["status"] == "closed")
        open_n = sum(1 for r in rows if r["mode"] == m and r["status"] == "open")
        assert dash[m]["closed_trades"] == fb[m]["closed_trades"] == closed_n, m
        assert dash[m]["open_positions"] == fb[m]["open_positions"] == open_n, m
        assert sum(1 for p in board["open_positions"] if p["mode"] == m) == open_n, m
    assert ap["paper_open"] == dash["paper"]["open_positions"] == 2

    # -- each book's open cost with fees: the dashboard, Funds, the track record and the strategy page ------------
    holds = {"paper": page["fade"], "demo": page["fade"], "live": page["live"]}  # each strategy holds its book's all
    for m in ("paper", "demo", "live"):
        books = holds[m]["holdings_books"]
        assert dash[m]["open_cost"] == fb[m]["open_cost"] == record[m]["open_cost"] == books[m]["open_cost"], m
        assert dash[m]["open_at_cost"] == fb[m]["open_at_cost"] == books[m]["open_at_cost"], m
        assert books[m]["open_positions"] == dash[m]["open_positions"], m
    # The half cents the strategy page used to add apart: rows of $1.01 each, the book $2.01.
    paper_rows = [h["cost"] for h in page["fade"]["holdings"] if h["mode"] == "paper"]
    assert paper_rows == [1.01, 1.01] and page["fade"]["holdings_books"]["paper"]["open_cost"] == 2.01
    # Books are never added together: no book is in another strategy's holdings, and live is its own figure.
    assert set(page["fade"]["holdings_books"]) == {"paper", "demo"} and set(page["live"]["holdings_books"]) == {"live"}
    assert page["spike"]["holdings_books"] == {}

    # -- each deployment's unrealized P&L: its marked positions as the dashboard, Deploy and the strategy page list them
    for name, strat in (("P", "fade"), ("D", "fade"), ("L", "live")):
        did = dep[name]
        for listed in (dash["open_positions"], board["open_positions"]):
            marked = [p["unrealized"] for p in listed if p["deployment_id"] == did and p["unrealized"] is not None]
            assert len(marked) == 1, name
            [row] = [d for d in dash["deployments"] if d["id"] == did]
            assert row["unrealized_pnl"] == marked[0], name
        mode = {"P": "paper", "D": "demo", "L": "live"}[name]
        assert [h["unrealized"] for h in page[strat]["holdings"] if h["mode"] == mode and h["unrealized"] is not None] == marked, name

    # -- today's realized P&L (UTC): the dashboard and the autopilot panel ----------------------------------------
    for m in ("paper", "live"):
        assert dash[m]["today_pnl"] == ap["today_%s_pnl" % m] == cents(exact(
            lambda r, m=m: r["mode"] == m and r["closed_at"] >= day.replace(tzinfo=None))), m
    assert dash["live"]["today_pnl"] == 0.36

    # -- since deploying, per strategy and book: the Strategies list, the strategy page and the deployment rows ----
    board_rows = {r["id"]: r for r in board["deployments"]}
    for strat, m, name in (("fade", "paper", "P"), ("live", "live", "L"), ("spike", "live", "S")):
        figure = cents(exact(lambda r, d=dep[name]: r["deployment_id"] == d))
        assert cards[sid[strat]]["real"]["pnl"] == page[strat]["book_totals"][m]["pnl"] == board_rows[dep[name]]["realized_pnl"] == figure
    assert cards[sid["fade"]]["real"]["demo"]["pnl"] == page["fade"]["book_totals"]["demo"]["pnl"] == 0.51  # every demo trade
    [paused] = [r for r in dash["deployments"] if r["id"] == dep["S"]]
    assert paused["status"] == "paused" and paused["realized_pnl"] == -1.02

    # -- credits: Billing, /api/me, the dashboard strip and the autopilot panel, one balance and one week ------------
    cur.execute("SELECT COALESCE(SUM(amount_usd),0) AS b FROM app_credit_ledger WHERE user_id=%s", (uid,))
    ledger = Decimal(str(cur.fetchone()["b"]))
    balance = cents(ledger)
    # Whatever the signup granted, plus $25, less $1.335 + $0.905 + 3 x $0.0625: kept exact, rounded once where shown.
    assert Decimal(str(bill["balance"])).quantize(Decimal("0.0001")) == ledger.quantize(Decimal("0.0001"))
    assert cents(bill["balance"]) == cents(me["credit_balance"]) == ap["week"]["credits_left"] == balance
    spent = Decimal("1.335") + Decimal("0.905") + 3 * Decimal("0.0625")
    assert bill["spent_7d"] == dash["since"]["spent"]["week"] == cents(spent) == 2.43
    assert ap["week"]["research_credits"] == bill["spent_7d_by"]["research"] == 2.24
    assert ap["week"]["checkin_credits"] == bill["spent_7d_by"]["autopilot_review"] == 0.19

    # -- never one figure across books, never credits in a P&L ----------------------------------------------------
    book = {m: exact(lambda r, m=m: r["mode"] == m) for m in ("paper", "demo", "live")}
    shown = [dash[m][k] for m in ("paper", "demo", "live") for k in ("realized_pnl", "today_pnl", "open_cost")]
    shown += [b.get("all") for b in board["realized_by_book"].values()] + [c["real"]["pnl"] for c in cards.values() if c.get("real")]
    shown += [v["open_cost"] for p in page.values() for v in p["holdings_books"].values()]
    mixed = {cents(book["live"] + book["paper"]), cents(book["live"] + book["demo"]), cents(sum(book.values())),
             cents(Decimal(str(dash["live"]["open_cost"])) + Decimal(str(dash["paper"]["open_cost"])))}
    assert not mixed & set(shown), (mixed, shown)
    with_credits = {cents(book[m] + Decimal(str(balance))) for m in book} | {cents(book[m] - spent) for m in book}
    assert not with_credits & set(shown), (with_credits, shown)
