"""The deployments' sparkline curves read faster and say exactly what they said, against a real MySQL.
Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).

repo.deployment_curves (the Deploy board polls it every 10s, the dashboard every 15s) used to bring
each kept point back as its own row; it now brings one JSON array per deployment and sorts it by trade
number in Python. The curves (same keys in the same order, same points, same int and float values) and
the two pages' JSON must match the old read byte for byte, on books holding every awkward case: more
trades than the cap, exactly the cap and one over it, one trade, many trades closed in the same second
with the same cumulative P&L (the ties the cut breaks by trade number), large and negative 4-place
amounts, and another account's book beside it.
"""
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

# The read deployment_curves made before: one row per kept point, in order.
OLD_CURVES_SQL = """SELECT deployment_id, TIMESTAMPDIFF(SECOND, '1970-01-01 00:00:00', closed_at) AS ts, cum FROM (
             SELECT deployment_id, closed_at, cum, rn,
                    ROW_NUMBER() OVER (PARTITION BY deployment_id, b ORDER BY cum, rn) AS lo,
                    ROW_NUMBER() OVER (PARTITION BY deployment_id, b ORDER BY cum DESC, rn) AS hi
             FROM (
               SELECT deployment_id, closed_at, cum, rn,
                      CASE WHEN n <= %s THEN rn WHEN rn = 1 THEN -1 WHEN rn = n THEN %s
                           ELSE FLOOR((rn - 2) * %s / (n - 2)) END AS b
               FROM (
                 SELECT deployment_id, closed_at,
                        SUM(pnl) OVER (PARTITION BY deployment_id ORDER BY closed_at, id ROWS UNBOUNDED PRECEDING) AS cum,
                        CAST(ROW_NUMBER() OVER (PARTITION BY deployment_id ORDER BY closed_at, id) AS SIGNED) AS rn,
                        COUNT(*) OVER (PARTITION BY deployment_id) AS n
                 FROM app_positions WHERE {where}
               ) ordered
             ) bucketed
           ) ranked
           WHERE lo = 1 OR hi = 1
           ORDER BY deployment_id, rn"""


def old_curves(cur, user_id, max_points=None, deployment_ids=None):
    from app import repository as repo

    max_points = max_points or repo.CURVE_MAX_POINTS
    buckets = max(1, (max_points - 2) // 2)
    ids, where = (), "user_id=%s AND status='closed'"
    if deployment_ids is not None:
        ids = tuple(sorted({int(i) for i in deployment_ids}))
        if not ids:
            return {}
        where = "deployment_id IN (" + ",".join(["%s"] * len(ids)) + ") AND " + where
    cur.execute(OLD_CURVES_SQL.format(where=where), (max_points, buckets, buckets, *ids, user_id))
    out = {}
    for r in cur.fetchall():
        out.setdefault(r["deployment_id"], []).append([int(r["ts"]), round(float(r["cum"]), 4)])
    return out


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


def _account(conn, rng, label):
    """Deployments whose closed trades cover each awkward case; one more is stopped (off the board)."""
    from app import repository as repo
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, label + "@example.invalid", label, None)["id"]
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}})
    sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", "Curve " + label, "t", spec, "passed",
                               {"capital": 20.0, "out_of_sample": {"trades": 40, "pnl": 6.0, "win_rate": 0.6}})
    cap = repo.CURVE_MAX_POINTS
    start = datetime(2026, 8, 1, 3, 0, 7)
    rows = []
    books = [("paper", 900, "mixed"), ("paper", cap, "mixed"), ("paper", cap + 1, "mixed"), ("demo", 1, "mixed"),
             ("paper", 600, "ties"), ("demo", 300, "large"), ("paper", 250, "mixed")]
    deps = []
    for i, (mode, n, kind) in enumerate(books):
        did = repo.create_deployment(cur, uid, sid, "btc15m", mode)
        deps.append(did)
        for k in range(n):
            if kind == "ties":  # whole stretches closed in one second, the running total revisiting each value
                closed, pnl = start + timedelta(seconds=k // 40), Decimal((-1, 1)[k % 2])
            elif kind == "large":
                closed, pnl = start + timedelta(minutes=k), Decimal(rng.randint(-99999999, 99999999)) / 10000
            else:
                closed, pnl = start + timedelta(minutes=k), Decimal(rng.randint(-25000, 26000)) / 10000
            rows.append((did, uid, mode, "KXBTC15M-26AUG%04d-T98" % k, "yes", 3, Decimal("0.4100"), Decimal("0.0700"),
                         closed, closed - timedelta(minutes=9), "closed", Decimal("1.0000"), Decimal("0.0000"), pnl,
                         "%s:%s-%d-%d" % ("sim" if mode == "paper" else mode, label, i, k), closed))
    cur.executemany(
        """INSERT INTO app_positions (deployment_id, user_id, mode, ticker, side, qty, entry_price, entry_fee,
             market_close_time, opened_at, status, exit_price, exit_fee, pnl, order_ref, closed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
    repo.insert_position(cur, deps[0], uid, "paper", "KXBTC15M-OPEN", "yes", 2, 0.4, 0.07, datetime(2026, 12, 1))
    assert repo.set_deployment_status(cur, uid, deps[-1], "stopped")
    return repo.get_user(cur, uid), deps


def _payload(value):
    from app import server

    return json.dumps(value, default=server._json_default, separators=(",", ":"))


def test_the_curves_and_the_pages_that_draw_them_say_what_they_said(conn, monkeypatch):
    from app import repository as repo
    from app import server

    rng = random.Random(20261026)
    user, deps = _account(conn, rng, "curves")
    _account(conn, rng, "beside")
    cur = conn.cursor()
    uid = user["id"]
    listed = [d["id"] for d in repo.list_deployments_for_display(cur, uid)]
    assert deps[-1] not in listed and set(deps[:-1]) <= set(listed)

    for ids in (None, listed, deps[:1], [deps[4]], [deps[1], deps[2]], []):
        new, old = repo.deployment_curves(cur, uid, deployment_ids=ids), old_curves(cur, uid, deployment_ids=ids)
        assert repr(new) == repr(old), ids  # keys in order, every point, every int and float
    for points in (4, 9, 60):
        assert repr(repo.deployment_curves(cur, uid, max_points=points)) == repr(old_curves(cur, uid, max_points=points))
    every = repo.deployment_curves(cur, uid)
    cap = repo.CURVE_MAX_POINTS
    assert len(every[deps[0]]) <= cap and len(every[deps[1]]) == cap and len(every[deps[2]]) <= cap
    assert len(every[deps[3]]) == 1 and deps[-1] in every and len(every) == len(deps)
    assert any(abs(v) > 100000 for _, v in every[deps[5]])  # the large amounts made it through as themselves

    # The two pages: byte for byte the same JSON with the old read in place of the new one.
    ctx = server.Ctx(conn, dict(user, autopilot=0), (), {}, {}, None)
    # "Since your last visit" starts from now(); pin it so two reads a second apart compare equal.
    visit = server._visit_since(None)
    monkeypatch.setattr(server, "_visit_since", lambda raw: visit)
    server._BACKTEST_CHECKS.clear()
    new_pages = [_payload(server.list_deployments(ctx)), _payload(server.dashboard(ctx))]
    monkeypatch.setattr(server.repo, "deployment_curves",
                        lambda c, u, max_points=None, deployment_ids=None: old_curves(c, u, max_points, deployment_ids))
    server._BACKTEST_CHECKS.clear()
    old_pages = [_payload(server.list_deployments(ctx)), _payload(server.dashboard(ctx))]
    assert new_pages == old_pages
    assert '"curve":[[' in new_pages[0] and '"curve":[[' in new_pages[1]
