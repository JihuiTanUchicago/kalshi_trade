"""A tune (adjust) proposal, Approve and Decline, end to end through the app's own routes, against a
real MySQL. Opt in as for test_app_engine_db.py (APP_TEST_MYSQL=1).

The user asks in the autopilot chat (POST /api/chat) with autopilot off, so the agent can only
propose. The worker's chat turn runs agent.run_copilot with the model stubbed in-process (it asks to
tighten one deployment's entry; the backtest is stubbed to pass) and outbound sockets refused. The
panel reads the proposal (GET /api/chat), then:

- Approve (POST /api/proposals/<id>/approve) re-points the deployment at the tuned strategy, and the
  feed's decision line says which proposal it answers and what is true now.
- Decline (POST /api/proposals/<id>/reject) on a second proposal changes nothing: the deployment, the
  user's strategies and limits stay as they were, and the line says "Nothing changed."
- A proposal already decided is not decided again (409), and the decision lines are never read back
  as the autopilot's last move.
"""
import http.client
import json
import os
import socket
import uuid
from datetime import timedelta
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

pytestmark = pytest.mark.skipif(os.getenv("APP_TEST_MYSQL") != "1", reason="needs APP_TEST_MYSQL=1 and a MySQL")

TITLE = "Fade tails — v2"


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
def offline(monkeypatch):
    """No call leaves this machine: a socket may reach this host only (the database and the app)."""
    real = socket.socket.connect

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "localhost", "::1") and not host.startswith("/"):
            raise OSError("outbound connection refused in this test: %r" % (address,))
        return real(self, address)
    monkeypatch.setattr(socket.socket, "connect", connect)
    from app.adapters.stripe import billing
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "")  # payments off: nothing is billed, no Stripe


@pytest.fixture
def web(offline):
    from app import server

    http_server = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = Thread(target=http_server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield http_server.server_port
    http_server.shutdown()
    http_server.server_close()
    thread.join(timeout=2)


def _call(port, method, path, token, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Cookie": "rsid=" + token, "X-Recursive": "1", "Content-Type": "application/json"}
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, json.loads(data or b"null")


def _account(conn):
    """A signed-in user, autopilot off, with one paper deployment."""
    from app import repository as repo
    from app.web import auth
    from app.trading import spec as specmod

    cur = conn.cursor()
    uid = repo.upsert_google_user(cur, "test:" + uuid.uuid4().hex, "tune@example.invalid", "Tune", None)["id"]
    token = auth.new_session_token()
    repo.create_session(cur, uid, auth.hash_token(token), timedelta(hours=1))
    spec = specmod.validate({"side": "yes", "entry": {"min_edge": 0.05}, "sizing": {"stake": 5.0, "max_positions": 4}})
    result = {"capital": 20.0, "in_sample": {"trades": 80, "pnl": 9.0}, "out_of_sample": {"trades": 30, "pnl": 3.0, "max_drawdown": 2.0}}
    sid = repo.insert_strategy(cur, uid, None, None, "btc15m", "momentum", TITLE, "t", spec, "passed", result)
    did = repo.create_deployment(cur, uid, sid, "btc15m", "paper")
    return uid, token, did, sid


def _turn(conn, monkeypatch, port, token, uid, did, edge):
    """The user asks; the worker runs the chat turn with the model stubbed; the panel reads the feed.
    Returns the proposal's chat line."""
    from app import repository as repo
    from app.research import agent
    from app.trading import backtest

    status, out = _call(port, "POST", "/api/chat", token, {"content": "Tighten the entry on %s." % TITLE})
    assert status == 200, out
    calls = []

    def model(system, messages, on_delta=None):
        calls.append(messages)
        return json.dumps({"reply": "Its entries fire on thin edges; I'd ask for a wider one.", "actions": [
            {"type": "adjust", "deployment_id": did, "changes": {"entry": {"min_edge": edge}},
             "reason": "Entries fire on edges too thin to pay the fees."}]}), {"input_tokens": 0, "output_tokens": 0}

    monkeypatch.setattr(backtest, "evaluate", lambda spec, ds, *a, **k: {  # patched where agent.act reads it
        "passed": True, "gates": [], "capital": 20.0, "in_sample": {"trades": 70, "pnl": 8.0},
        "out_of_sample": {"trades": 28, "pnl": 3.5, "max_drawdown": 1.5}})
    cur = conn.cursor()
    cur.execute("SELECT * FROM app_agent_runs WHERE user_id=%s AND kind='chat' AND status='queued' ORDER BY id LIMIT 1", (uid,))
    run = cur.fetchone()
    cur.execute("UPDATE app_agent_runs SET status='running', started_at=%s WHERE id=%s", (repo.now_utc(), run["id"]))
    agent.run_copilot(conn, dict(run, status="running"), model=model, dataset_fn=lambda market: None)
    assert calls and repo.get_run(cur, uid, run["id"])["status"] == "succeeded"
    status, feed = _call(port, "GET", "/api/chat?after=0", token)
    assert status == 200
    asks = [m for m in feed["messages"] if m.get("proposal_kind") == "adjust" and m.get("proposal_status") == "pending"]
    assert len(asks) == 1, feed["messages"]
    return asks[0]


def _book(conn, uid):
    """Everything a decision could touch, as stored."""
    cur = conn.cursor()
    cur.execute("SELECT id, strategy_id, market, mode, status, status_reason FROM app_deployments WHERE user_id=%s ORDER BY id", (uid,))
    deps = cur.fetchall()
    cur.execute("SELECT id, status, title, spec_json FROM app_strategies WHERE user_id=%s ORDER BY id", (uid,))
    strategies = cur.fetchall()
    cur.execute("SELECT * FROM app_users WHERE id=%s", (uid,))
    user = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS n FROM app_positions WHERE user_id=%s", (uid,))
    return {"deployments": deps, "strategies": strategies, "user": user, "positions": cur.fetchone()["n"]}


def _proposal(conn, pid):
    cur = conn.cursor()
    cur.execute("SELECT id, kind, status, deployment_id, strategy_id FROM app_proposals WHERE id=%s", (pid,))
    return cur.fetchone()


def test_a_tune_proposal_approved_then_another_declined_through_the_routes(conn, web, monkeypatch):
    from app import repository as repo

    uid, token, did, original = _account(conn)

    # -- Approve ---------------------------------------------------------------------------------
    ask = _turn(conn, monkeypatch, web, token, uid, did, 0.08)
    assert ask["content"] == "Proposed adjustment to %s. It passed the backtest gates." % TITLE
    assert ask["deployment_mode"] == "paper"
    tuned = _proposal(conn, ask["proposal_id"])["strategy_id"]
    assert tuned != original and repo.get_deployment(conn.cursor(), uid, did)["strategy_id"] == original  # nothing yet

    status, out = _call(web, "POST", "/api/proposals/%d/approve" % ask["proposal_id"], token, {})
    assert (status, out) == (200, {"ok": True})
    assert repo.get_deployment(conn.cursor(), uid, did)["strategy_id"] == tuned  # it trades the tuned version
    assert _proposal(conn, ask["proposal_id"])["status"] == "applied"
    status, feed = _call(web, "GET", "/api/chat?after=%d" % ask["id"], token)
    lines = [m for m in feed["messages"] if m["role"] == "system"]
    assert [m["content"] for m in lines] == [
        "You approved the proposal to tune %s (adjusted). It now trades the tuned version, on paper, with practice money." % TITLE]
    status, again = _call(web, "POST", "/api/proposals/%d/reject" % ask["proposal_id"], token, {})
    assert status == 409 and again["error"] == "This proposal was already decided."
    assert repo.get_deployment(conn.cursor(), uid, did)["strategy_id"] == tuned

    # -- Decline ---------------------------------------------------------------------------------
    ask2 = _turn(conn, monkeypatch, web, token, uid, did, 0.12)
    before = _book(conn, uid)
    status, out = _call(web, "POST", "/api/proposals/%d/reject" % ask2["proposal_id"], token, {})
    assert (status, out) == (200, {"ok": True})
    assert _book(conn, uid) == before  # declining changed nothing
    assert repo.get_deployment(conn.cursor(), uid, did)["strategy_id"] == tuned
    assert _proposal(conn, ask2["proposal_id"])["status"] == "rejected"
    status, feed = _call(web, "GET", "/api/chat?after=%d" % ask2["id"], token)
    assert [m["content"] for m in feed["messages"] if m["role"] == "system"] == [
        "You declined the proposal to tune %s (adjusted). Nothing changed." % TITLE]
    status, again = _call(web, "POST", "/api/proposals/%d/approve" % ask2["proposal_id"], token, {})
    assert status == 409 and _book(conn, uid) == before

    # The feed shows each proposal as decided, and the user's decisions are not the autopilot's moves.
    status, feed = _call(web, "GET", "/api/chat?after=0", token)
    decided = {m["proposal_id"]: m["proposal_status"] for m in feed["messages"] if m.get("proposal_id")}
    assert decided == {ask["proposal_id"]: "applied", ask2["proposal_id"]: "rejected"}
    last = repo.last_autopilot_action(conn.cursor(), uid)
    assert last is None or not last["text"].startswith("You ")
