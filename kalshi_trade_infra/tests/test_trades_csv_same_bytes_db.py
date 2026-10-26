"""GET /api/trades.csv reads faster and writes exactly the file it wrote, against a real MySQL. Opt in
as for test_app_engine_db.py (APP_TEST_MYSQL=1).

repo.closed_trades_for_export used to join every closed position to its deployment and strategy and
hand back DATETIMEs and DECIMALs, which pymysql parsed in Python. It now brings the times and amounts
back as the file's own text, packed into one column, and reads each deployment's strategy once. The
file built from the new rows must be byte for byte the file built from the old read, for every mode,
on a book holding every awkward case: still-open trades (left out), a part-sold trade (its sold slice
in, its remainder out), settled, take-profit and instant fills, NULL amounts, reason and close time,
a deleted strategy, a deployment row that is gone, a title that needs quoting or would run as a
formula, negative and zero P&L, a large book and another account beside it.
"""
import os
import random
import uuid
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

TODAY = datetime(2026, 10, 26, 9, 0)
# The read the export made before (position_repository.closed_trades_for_export).
OLD_EXPORT_SQL = """
    SELECT p.id, p.mode, p.ticker, p.side, p.qty, p.entry_price, p.entry_fee, p.exit_price, p.exit_fee,
           p.pnl, p.close_reason, p.opened_at, p.closed_at, d.strategy_id, s.title
    FROM app_positions p
    LEFT JOIN app_deployments d ON d.id=p.deployment_id
    LEFT JOIN app_strategies s ON s.id=d.strategy_id
    WHERE p.user_id=%s AND p.mode=%s AND p.status='closed'
    ORDER BY p.closed_at DESC, p.id DESC LIMIT %s"""
TITLES = ["Fade late spikes", 'Says "hi", then, sells', "=HYPERLINK(\"http://x.example\",\"x\")", "-2+3 momentum",
          "Rain\nmaker", "Ünïcode ✓ titles"]


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


INSERT = """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
              market_close_time, opened_at, status, exit_price, exit_fee, pnl, close_reason, order_ref, closed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""


def _book(conn, rng, label, n_trades):
    """One account with deployments in every mode and a book of closed and open trades."""
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, label + "@example.invalid", label, None)["id"]
    deps = []
    for i, title in enumerate(TITLES):
        spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}})
        sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", title, "t", spec, "passed", {})
        for mode in ("paper", "demo", "live"):
            did = repo.create_deployment(cur, uid, sid, "btc15m", mode)
            cur.execute("UPDATE app_deployments SET status='stopped' WHERE id=%s", (did,))
            deps.append((did, mode))
    start = datetime(2026, 1, 1)
    rows = []
    for i in range(n_trades):
        did, mode = rng.choice(deps)
        opened = start + timedelta(seconds=rng.randint(0, 25_000_000))
        qty, price = rng.randint(1, 400), round(rng.uniform(0.01, 0.99), 4)
        if rng.random() < 0.05:  # still open: never in the file
            rows.append((did, uid, mode, "KX-%d" % i, "yes", qty, price, 0.07, opened, opened, "open",
                         None, None, None, None, "%s:%d" % (mode, i), None))
            continue
        exit_price = rng.choice([0.0, 1.0, round(rng.uniform(0.01, 0.99), 4)])
        pnl = round(qty * (exit_price - price) - rng.uniform(0, 3), 4)
        closed = opened + timedelta(seconds=rng.choice([0, 1, rng.randint(2, 90000)]))  # 0: an instant fill
        rows.append((did, uid, mode, "KXBTC15M-26OCT%04d-T%d" % (i % 700, rng.randint(90000, 120000)),
                     rng.choice(["yes", "no"]), qty, price, round(rng.uniform(0, 3), 4), opened, opened, "closed",
                     exit_price, rng.choice([0.0, 0.07, 1.2345]), pnl,
                     rng.choice(["settled", "take_profit", "stop_loss", "time_exit"]), "%s:%d" % (mode, i), closed))
    cur.executemany(INSERT, rows)
    return uid, deps


def _old_rows(cur, uid, mode, limit):
    cur.execute(OLD_EXPORT_SQL, (uid, mode, int(limit)))
    return cur.fetchall()


def _file(monkeypatch, conn, uid, mode, rows=None):
    """The file trades_csv writes for `mode`: from the repository's read, or from `rows` given."""
    from app import server

    with monkeypatch.context() as m:
        if rows is not None:
            m.setattr(server.repo, "closed_trades_for_export", lambda cur, u, md, limit: rows)
        kind, fname, ctype, data = server.trades_csv(server.Ctx(conn, {"id": uid}, (), {"mode": mode}, {}, None))
    assert kind == "download" and ctype.startswith("text/csv")
    return fname, data.encode("utf-8")


def test_every_modes_file_is_byte_for_byte_the_file_the_old_read_wrote(conn, monkeypatch):
    from app import repository as repo
    from app import server

    monkeypatch.setattr(server.repo, "now_utc", lambda: TODAY)
    rng = random.Random(20261026)
    uid, deps = _book(conn, rng, "heavy", 2400)
    beside, _ = _book(conn, rng, "beside", 300)
    cur = conn.cursor()
    paper = [d for d, m in deps if m == "paper"]

    # A part-sold trade: the sold slice is a closed row of its own, the remainder stays open.
    pid = repo.insert_position(cur, paper[0], uid, "paper", "KX-PART", "yes", 10, 0.42, 0.1, TODAY, order_ref="sim:part")
    cur.execute("SELECT * FROM app_positions WHERE id=%s", (pid,))
    assert repo.book_partial_exit(cur, cur.fetchone(), 4, 0.61, 0.02, 0.69, "take_profit")
    # A closed row with every nullable field NULL; a zero, a negative-zero and a large P&L.
    cur.execute(INSERT, (paper[1], uid, "paper", "KX-NULLS", "no", 3, 0.5, 0.0, TODAY, datetime(2026, 3, 1),
                         "closed", None, None, None, None, None, None))
    for pnl in (0.0, -0.0, 9876543210.1234, -12345.6789):
        repo.insert_closed_position(cur, paper[2], uid, "paper", "KX-PNL", "yes", 999999, 0.9999, 999.9999, 1.0,
                                    0.0, pnl, "settled", TODAY, order_ref="sim:pnl", opened_at=datetime(2026, 4, 1),
                                    closed_at=datetime(2026, 4, 1, 0, 15))
    # Ties on closed_at (ordered by id), a deleted strategy and a deployment row that is gone.
    for k in range(3):
        repo.insert_closed_position(cur, paper[3], uid, "paper", "KX-TIE", "yes", 1, 0.5, 0.07, 1.0, 0.0, 0.43,
                                    "settled", TODAY, opened_at=datetime(2026, 5, 1), closed_at=datetime(2026, 5, 1, 1))
    cur.execute("SELECT strategy_id FROM app_deployments WHERE id=%s", (paper[4],))
    cur.execute("DELETE FROM app_strategies WHERE id=%s", (cur.fetchone()["strategy_id"],))
    gone = [d for d, m in deps if m == "live"][0]
    repo.insert_closed_position(cur, gone, uid, "live", "KX-GONE", "yes", 2, 0.3, 0.05, 0.0, 0.0, -0.65, "settled",
                                TODAY, opened_at=datetime(2026, 6, 1), closed_at=datetime(2026, 6, 1, 0, 1))
    cur.execute("DELETE FROM app_deployments WHERE id=%s", (gone,))

    limit = server.TRADES_CSV_MAX_ROWS + 1
    for mode in server.TRADE_MODES:
        old = _old_rows(cur, uid, mode, limit)
        new = repo.closed_trades_for_export(cur, uid, mode, limit)
        assert [r["id"] for r in new] == [r["id"] for r in old] and len(new) > 400, mode
        assert [(r["strategy_id"], r["title"], r["qty"]) for r in new] == [
            (r["strategy_id"], r["title"], r["qty"]) for r in old], mode
        old_file, new_file = _file(monkeypatch, conn, uid, mode, old), _file(monkeypatch, conn, uid, mode)
        assert new_file == old_file, mode
        assert new_file[1].startswith(b"closed_at_utc,") and new_file[0] == "tau-trades-%s-20261026.csv" % mode

    old = _old_rows(cur, uid, "paper", limit)
    assert any(r["title"] is None and r["strategy_id"] is not None for r in old)  # the deleted strategy
    assert any(r["pnl"] is None and r["closed_at"] is None for r in old)  # the all-NULL row
    assert [r["qty"] for r in old if r["ticker"] == "KX-PART"] == [4]  # the open remainder stays out
    assert any(r["strategy_id"] is None for r in _old_rows(cur, uid, "live", limit))  # the gone deployment
    text = _file(monkeypatch, conn, uid, "paper")[1].decode()
    assert ",9876543210.1234," in text and ",-12345.6789," in text
    # Another account's trades never ride along; a mode with none is a header alone.
    assert {r["id"] for r in repo.closed_trades_for_export(cur, beside, "paper", limit)}.isdisjoint(
        {r["id"] for r in old})
    nobody = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "none@example.invalid", "N", None)["id"]
    assert repo.closed_trades_for_export(cur, nobody, "live", limit) == []
    assert _file(monkeypatch, conn, nobody, "live") == _file(monkeypatch, conn, nobody, "live", [])


def test_a_capped_file_cuts_at_the_same_trade(conn, monkeypatch):
    from app import repository as repo
    from app import server
    from app.web.routes import billing as billing_routes

    monkeypatch.setattr(server.repo, "now_utc", lambda: TODAY)
    monkeypatch.setattr(billing_routes, "TRADES_CSV_MAX_ROWS", 37)
    uid, _ = _book(conn, random.Random(7), "capped", 200)
    cur = conn.cursor()
    old = _old_rows(cur, uid, "paper", 38)
    assert len(old) == 38
    assert _file(monkeypatch, conn, uid, "paper") == _file(monkeypatch, conn, uid, "paper", old)
    assert b"# Only the newest 37 trades" in _file(monkeypatch, conn, uid, "paper")[1]
    assert len(repo.closed_trades_for_export(cur, uid, "paper", 38)) == 38
