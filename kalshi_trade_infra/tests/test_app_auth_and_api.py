import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app import auth, kalshi_account, server


# -- Google ID token claims -------------------------------------------------------


@pytest.fixture
def client_id(monkeypatch):
    monkeypatch.setattr(auth, "CLIENT_ID", "cid.apps.googleusercontent.com")
    return auth.CLIENT_ID


def _claims(**over):
    c = {"iss": "https://accounts.google.com", "aud": "cid.apps.googleusercontent.com", "exp": 2_000_000_000,
         "nonce": "n1", "sub": "123", "email": "j@example.com", "email_verified": True, "name": "J"}
    c.update(over)
    return c


def test_valid_claims(client_id):
    assert auth.check_claims(_claims(), "n1", now=1_900_000_000)["sub"] == "123"


@pytest.mark.parametrize("over,why", [
    ({"iss": "https://evil.example"}, "issued"),
    ({"aud": "someone-else"}, "different app"),
    ({"exp": 1}, "expired"),
    ({"nonce": "other"}, "nonce"),
    ({"email_verified": False}, "not verified"),
])
def test_bad_claims_are_refused(client_id, over, why):
    with pytest.raises(auth.AuthError, match=why):
        auth.check_claims(_claims(**over), "n1", now=1_900_000_000)


def test_pkce_challenge_is_unpadded_base64url_sha256():
    import hashlib

    v = auth.new_login()["verifier"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    assert auth._challenge(v) == expected and len(expected) == 43 and 43 <= len(v) <= 128


def test_session_tokens_are_stored_hashed():
    token = auth.new_session_token()
    assert len(token) >= 40 and auth.hash_token(token) != token and len(auth.hash_token(token)) == 64


# -- Kalshi key storage -------------------------------------------------------------


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())


def _pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption()).decode()


def test_private_key_round_trip_is_bound_to_the_user(secret):
    pem = _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    blob = kalshi_account.encrypt_private_key(7, pem)
    assert pem.encode() not in blob
    assert kalshi_account.decrypt_private_key(7, blob) == pem
    with pytest.raises(Exception):
        kalshi_account.decrypt_private_key(8, blob)  # another user's row cannot be swapped in


def test_missing_secret_refuses_to_store(monkeypatch):
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        kalshi_account.encrypt_private_key(1, "x")


def test_non_rsa_or_garbage_keys_are_rejected():
    with pytest.raises(kalshi_account.KalshiKeyError):
        kalshi_account.parse_private_key("not a key")
    ec_pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    with pytest.raises(kalshi_account.KalshiKeyError, match="RSA"):
        kalshi_account.parse_private_key(ec_pem)


# -- API handlers -----------------------------------------------------------------


class FakeCur:
    lastrowid = 1
    rowcount = 1

    def execute(self, *a):
        pass

    def fetchone(self):
        return {"n": 0}


class FakeConn:
    def cursor(self):
        return FakeCur()


def ctx(body=None, params=(), query=None):
    return server.Ctx(FakeConn(), {"id": 1, "autopilot": 0}, params, query or {}, body or {}, None)


def test_create_run_happy_path(monkeypatch):
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(server.repo, "create_run", lambda cur, uid, kind, market, direction, prompt, **kw: 42)
    assert server.create_run(ctx({"market": "btc_daily", "prompt": "Sell overpriced tails before the close"})) == {"id": 42}


@pytest.mark.parametrize("body,status", [
    ({"market": "spx", "prompt": "a decent idea here"}, 400),           # bad market
    ({"market": "btc15m", "prompt": "too short"}, 400),                 # idea < 8 chars? no - this is >=8
    ({"market": "btc15m"}, 400),                                        # no idea
])
def test_create_run_validates(body, status, monkeypatch):
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(server.repo, "create_run", lambda *a, **k: 1)
    if body == {"market": "btc15m", "prompt": "too short"}:
        assert server.create_run(ctx(body)) == {"id": 1}  # valid: 9 chars
        return
    with pytest.raises(server.ApiError) as e:
        server.create_run(ctx(body))
    assert e.value.status == status


def test_create_run_is_rate_limited(monkeypatch):
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 99)
    with pytest.raises(server.ApiError) as e:
        server.create_run(ctx({"market": "btc15m", "prompt": "a reasonable research idea"}))
    assert e.value.status == 429


def test_deploy_any_status_on_paper_live_gated_globally(monkeypatch):
    strat = {"id": 5, "status": "rejected", "market": "btc15m", "title": "T", "spec": {"side": "yes"}}
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: dict(strat))
    monkeypatch.setattr(server.repo, "list_deployments", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "create_deployment", lambda cur, uid, sid, market, mode: 11)
    monkeypatch.setattr(server.repo, "add_chat", lambda *a, **k: 1)
    # any backtested status deploys on paper — the user decides
    for st in ("rejected", "failed", "passed"):
        strat["status"] = st
        assert server.create_deployment(ctx({"strategy_id": 5, "mode": "paper"})) == {"id": 11}
    # live is gated by the global switch + confirmation, not by status
    monkeypatch.setattr(server.engine, "LIVE_TRADING_ENABLED", False)
    with pytest.raises(server.ApiError, match="isn't open"):
        server.create_deployment(ctx({"strategy_id": 5, "mode": "live", "confirm": "LIVE"}))
    monkeypatch.setattr(server.engine, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: {"key_id": "k"})
    with pytest.raises(server.ApiError, match="Type LIVE"):
        server.create_deployment(ctx({"strategy_id": 5, "mode": "live", "confirm": "live"}))
    # a void strategy CAN go live once the user confirms (global switch on)
    strat["status"] = "failed"
    assert server.create_deployment(ctx({"strategy_id": 5, "mode": "live", "confirm": "LIVE"})) == {"id": 11}


def test_reply_emails_the_author_but_not_yourself(monkeypatch):
    sent = []
    monkeypatch.setattr(server.repo, "add_comment", lambda *a, **k: 1)
    monkeypatch.setattr(server.repo, "get_user", lambda cur, uid: {"id": uid, "name": "Bob"})
    monkeypatch.setattr(server.notify, "comment_notice", lambda *a, **k: sent.append(a))
    # ctx() is user id=1. Author is a different user -> one email.
    monkeypatch.setattr(server.repo, "post_author",
                        lambda cur, pid: {"user_id": 2, "email": "alice@example.com", "name": "Alice", "preview": "my post"})
    server.create_comment(ctx({"body": "nice one"}, params=("7",)))
    assert len(sent) == 1 and sent[0][0] == "alice@example.com"
    # Author replying to their own post -> no email.
    sent.clear()
    monkeypatch.setattr(server.repo, "post_author",
                        lambda cur, pid: {"user_id": 1, "email": "me@example.com", "name": "Me", "preview": "x"})
    server.create_comment(ctx({"body": "self reply"}, params=("7",)))
    assert sent == []


def test_numbers_must_be_numbers():
    with pytest.raises(server.ApiError):
        server._num({"amount": "100"}, "amount", 1, 10)
    with pytest.raises(server.ApiError):
        server._num({"amount": True}, "amount", 1, 10)
    with pytest.raises(server.ApiError):
        server._num({"amount": 11}, "amount", 1, 10)


def test_json_encoding_of_db_types():
    from datetime import datetime
    from decimal import Decimal

    out = json.dumps({"t": datetime(2026, 1, 1), "d": Decimal("1.50")}, default=server._json_default)
    assert '"2026-01-01T00:00:00+00:00"' in out and "1.5" in out


def test_spa_routes():
    for path in ("/", "/research/12", "/strategies", "/strategies/3", "/deploy", "/funds", "/signin"):
        assert server.SPA_ROUTES.match(path)
    assert not server.SPA_ROUTES.match("/static/../etc/passwd")


@pytest.mark.parametrize("status", ["queued", "running", "succeeded", "failed", "cancelled"])
def test_completed_session_reads_its_own_candidates(monkeypatch, status):
    calls = []
    monkeypatch.setattr(server.repo, "get_run", lambda cur, uid, rid: {
        "id": rid, "kind": "research", "status": status,
    })
    monkeypatch.setattr(server.repo, "list_strategies", lambda cur, uid, **query: calls.append((uid, query)) or [])
    monkeypatch.setattr(server.repo, "run_events", lambda *args: [])
    result = server.get_run(ctx(params=("7",)))
    assert result["strategies"] == []
    assert calls == [(1, {"run_id": 7})]


def test_unknown_session_does_not_read_other_candidates(monkeypatch):
    monkeypatch.setattr(server.repo, "get_run", lambda *args: None)
    monkeypatch.setattr(server.repo, "list_strategies", lambda *args, **kwargs: pytest.fail("unexpected candidate read"))
    with pytest.raises(server.ApiError) as error:
        server.get_run(ctx(params=("7",)))
    assert error.value.status == 404


def test_strategy_query_keeps_owner_and_session_filters():
    class ReadCursor(FakeCur):
        def execute(self, sql, params):
            self.sql, self.params = sql, params

        def fetchall(self):
            return []

    cur = ReadCursor()
    assert server.repo.list_strategies(cur, 9, run_id=7) == []
    assert "s.user_id=%s" in cur.sql and "s.run_id=%s" in cur.sql
    assert cur.params == [9, 7, 500]


def test_frontend_entrypoint_renders_current_assets_without_template_tokens():
    import io

    handler = object.__new__(server.Handler)
    handler.wfile = io.BytesIO()
    handler._headers = lambda *args: None
    handler._send_static("/strategies")
    html = handler.wfile.getvalue().decode()
    assert "{{" not in html
    assert "/static/app.css?v=" in html
    assert "/static/app.js?v=" in html
    assert html.index("/static/session-data.js?v=") < html.index("/static/session-chat.js?v=")
    assert html.index("/static/session-chat.js?v=") < html.index("/static/research-artifacts.js?v=") < html.index("/static/app.js?v=")
