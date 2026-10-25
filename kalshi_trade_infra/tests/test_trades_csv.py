"""GET /api/trades.csv: one mode's closed trades, for the signed-in user only, safe to open in a spreadsheet."""
import csv
import http.client
import io
import os
import uuid
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from app import server


def _row(i, **over):
    r = {"id": i, "mode": "paper", "ticker": "KXBTCD-26OCT2517-T98000", "side": "yes", "qty": 5,
         "entry_price": 0.4, "entry_fee": 0.07, "exit_price": 1.0, "exit_fee": 0.0, "pnl": 2.93,
         "close_reason": "settled", "opened_at": datetime(2026, 10, 25, 12, 0, i), "closed_at": datetime(2026, 10, 25, 13, 0, i),
         "strategy_id": 42, "title": "Fade late spikes"}
    r.update(over)
    return r


def _ctx(query):
    return server.Ctx(SimpleNamespace(cursor=lambda: None), {"id": 7}, (), query, {}, None)


def _parse(result):
    kind, fname, ctype, data = result
    assert kind == "download" and ctype.startswith("text/csv")
    return fname, list(csv.reader(io.StringIO(data)))


def test_the_file_has_a_header_row_and_one_row_per_closed_trade_oldest_first(monkeypatch):
    seen = []
    monkeypatch.setattr(server.repo, "closed_trades_for_export",
                        lambda cur, uid, mode, limit: seen.append((uid, mode, limit)) or [_row(2, pnl=-1.5), _row(1)])
    fname, rows = _parse(server.trades_csv(_ctx({"mode": "paper"})))
    assert seen == [(7, "paper", server.TRADES_CSV_MAX_ROWS + 1)]
    assert fname.startswith("tau-trades-paper-") and fname.endswith(".csv")
    assert rows[0] == ["closed_at_utc", "opened_at_utc", "mode", "strategy", "strategy_title", "ticker", "side",
                       "contracts", "entry_price", "exit_price", "entry_fee", "exit_fee", "realized_pnl",
                       "close_reason", "position_id"]
    assert rows[1] == ["2026-10-25T13:00:01Z", "2026-10-25T12:00:01Z", "paper", "No. 00042", "Fade late spikes",
                       "KXBTCD-26OCT2517-T98000", "yes", "5", "0.4000", "1.0000", "0.0700", "0.0000", "2.9300",
                       "settled", "1"]
    assert rows[2][12] == "-1.5000"  # a loss stays a number, not text
    assert len(rows) == 3


@pytest.mark.parametrize("mode", [None, "", "all", "paper,live", "LIVE'"])
def test_an_unknown_mode_is_refused(monkeypatch, mode):
    monkeypatch.setattr(server.repo, "closed_trades_for_export", lambda *a: pytest.fail("no read for a bad mode"))
    with pytest.raises(server.ApiError) as e:
        server.trades_csv(_ctx({} if mode is None else {"mode": mode}))
    assert e.value.status == 400


def test_cells_that_a_spreadsheet_would_run_as_formulas_are_made_text(monkeypatch):
    evil = ['=HYPERLINK("http://x.example","click")', "+1+cmd|' /C calc'!A0", "-2+3", "@SUM(A1:A9)", "\t=1"]
    monkeypatch.setattr(server.repo, "closed_trades_for_export",
                        lambda cur, uid, mode, limit: [_row(i + 1, title=t, ticker=t) for i, t in enumerate(evil)])
    _, rows = _parse(server.trades_csv(_ctx({"mode": "live"})))
    for row, t in zip(reversed(rows[1:]), evil):
        assert row[4] == "'" + t and row[5] == "'" + t
    for value in ("-1.5", "+2", "-0.25", ".5"):
        assert server._csv_safe(value) == value
    assert server._csv_safe(-3.25) == "-3.25" and server._csv_safe(None) == ""


def test_a_capped_file_says_it_is_cut(monkeypatch):
    monkeypatch.setattr(server, "TRADES_CSV_MAX_ROWS", 2)
    monkeypatch.setattr(server.repo, "closed_trades_for_export", lambda cur, uid, mode, limit: [_row(3), _row(2), _row(1)])
    _, rows = _parse(server.trades_csv(_ctx({"mode": "demo"})))
    assert [r[14] for r in rows[1:3]] == ["2", "3"]  # the newest two, oldest first
    assert rows[3][0].startswith("# Only the newest 2 trades")


@pytest.fixture
def web(monkeypatch):
    connection = SimpleNamespace(cursor=lambda: None, close=lambda: None)
    monkeypatch.setattr(server, "get_db_conn", lambda: connection)
    users = {"tok-a": {"id": 1}}
    monkeypatch.setattr(server.repo, "session_user", lambda cur, token: next(
        (u for t, u in users.items() if server.auth.hash_token(t) == token), None))
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield http.server_port
    http.shutdown()
    http.server_close()
    thread.join(timeout=2)


def _get(port, path, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path, headers={"Cookie": cookie} if cookie else {})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r, body


def test_the_download_needs_a_session_and_is_an_uncached_attachment(web, monkeypatch):
    monkeypatch.setattr(server.repo, "closed_trades_for_export", lambda cur, uid, mode, limit: [_row(1)] if uid == 1 else [])
    r, _ = _get(web, "/api/trades.csv?mode=paper")
    assert r.status == 401
    r, _ = _get(web, "/api/trades.csv?mode=paper", "rsid=forged")
    assert r.status == 401
    r, body = _get(web, "/api/trades.csv?mode=paper", "rsid=tok-a")
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/csv")
    assert r.getheader("Content-Disposition").startswith('attachment; filename="tau-trades-paper-')
    assert r.getheader("Cache-Control") == "no-store"
    assert body.decode().splitlines()[0].startswith("closed_at_utc,")
    r, _ = _get(web, "/api/trades.csv?mode=everything", "rsid=tok-a")
    assert r.status == 400
    r, _ = _get(web, "/api/tradesXcsv?mode=paper", "rsid=tok-a")  # the dot is literal
    assert r.status == 404


# -- the real SQL: scoping, modes and the dashboard's own realized figure ---------------------------

db = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")


@pytest.fixture(scope="module")
def conn():
    from app import schema
    from data_pipeline.common import get_db_conn

    schema.main()
    c = get_db_conn()
    yield c
    c.close()


def _book(conn, uid, mode, trades):
    from app import repository as repo
    from app import spec as specmod

    cur = conn.cursor()
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.1}})
    sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "volatility", "=1+1 " + mode, "t", spec, "passed", {})
    did = repo.create_deployment(cur, uid, sid, "btc15m", mode)
    cur.execute("UPDATE app_deployments SET status='stopped' WHERE id=%s", (did,))
    close = datetime(2026, 10, 25, 12, 0)
    ids = [repo.insert_closed_position(cur, did, uid, mode, "TEST-" + uuid.uuid4().hex[:8], "yes", 3, 0.4, 0.05,
                                       1.0 if pnl > 0 else 0.0, 0.0, pnl, "settled", close) for pnl in trades]
    repo.insert_position(cur, did, uid, mode, "TEST-OPEN", "yes", 2, 0.5, 0.03, close + timedelta(days=1))
    return sid, ids


@db
def test_each_mode_file_holds_only_that_users_trades_in_that_mode_and_adds_up(conn):
    from app import repository as repo

    cur = conn.cursor()
    a = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "a@example.com", "A", None)["id"]
    b = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "b@example.com", "B", None)["id"]
    _, paper_ids = _book(conn, a, "paper", [1.75, -1.25, 0.5])
    _, demo_ids = _book(conn, a, "demo", [-0.8])
    _, other_ids = _book(conn, b, "paper", [9.0])
    files = {}
    for mode in server.TRADE_MODES:
        ctx = server.Ctx(conn, {"id": a}, (), {"mode": mode}, {}, None)
        _, rows = _parse(server.trades_csv(ctx))
        files[mode] = rows[1:]
        assert {r[2] for r in files[mode]} <= {mode}  # never mixes modes
        # The file adds up to the dashboard's realized figure for that mode.
        assert sum(float(r[12]) for r in files[mode]) == pytest.approx(repo.realized_pnl(cur, a, mode))
    ids = {m: sorted(int(r[14]) for r in rows) for m, rows in files.items()}
    assert ids == {"paper": sorted(paper_ids), "demo": sorted(demo_ids), "live": []}
    assert not set(other_ids) & set(ids["paper"])  # another user's trades never appear
    assert all(r[4].startswith("'=1+1") for r in files["paper"])  # the guard holds on stored titles too
    assert repo.closed_trade_counts(cur, a) == {"paper": 3, "demo": 1}


@db
def test_a_trade_whose_strategy_was_deleted_stays_in_the_file(conn):
    from app import repository as repo

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "c@example.com", "C", None)["id"]
    sid, ids = _book(conn, uid, "paper", [2.0])
    assert repo.delete_strategy(cur, uid, sid)
    rows = repo.closed_trades_for_export(cur, uid, "paper", 10)
    assert [r["id"] for r in rows] == ids and rows[0]["title"] is None



@db
def test_the_export_reads_a_user_index(conn):
    # No new index on app_positions (the order path writes it): the export rides idx_pos_user.
    cur = conn.cursor()
    cur.execute("EXPLAIN SELECT p.id FROM app_positions p WHERE p.user_id=1 AND p.mode='live' AND p.status='closed' "
                "ORDER BY p.closed_at DESC, p.id DESC LIMIT 10")
    plan = cur.fetchall()
    assert any("idx_pos_user" in (r.get("possible_keys") or "") for r in plan), plan
