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
    # §E.5 gatekeeper gate is now required for live too; default it True here so this test still
    # exercises the ORIGINAL live gates (switch + key + confirm). The gate itself is tested below.
    monkeypatch.setattr(server.agent, "_is_deployment_candidate", lambda cur, sid: True)
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


def test_code_strategy_refused_by_create_deployment(monkeypatch):
    # Code strategies are research-only: the manual deploy endpoint must reject them in EVERY mode,
    # matching agent.act's deploy/deploy_live guard, so arbitrary code never reaches the engine.
    strat = {"id": 5, "status": "passed", "market": "btc15m", "title": "T",
             "spec": {"market": "btc15m", "sizing": {"stake": 5, "max_positions": 1},
                      "code": "def signals(w): return []"}}
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: dict(strat))
    monkeypatch.setattr(server.repo, "create_deployment", lambda *a, **k: 11)
    for mode in ("paper", "demo", "live"):
        with pytest.raises(server.ApiError, match="research-only") as e:
            server.create_deployment(ctx({"strategy_id": 5, "mode": mode, "confirm": "LIVE"}))
        assert e.value.status == 409


def test_live_refuses_non_deployment_candidate(monkeypatch):
    # §E.5: the manual live path must ALSO clear the gatekeeper's DEPLOYMENT_CANDIDATE gate, matching
    # the autopilot path. Every other live gate is green, but the gate is not cleared -> refused.
    strat = {"id": 5, "status": "passed", "market": "btc15m", "title": "T", "spec": {"side": "yes"}}
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: dict(strat))
    monkeypatch.setattr(server.repo, "list_deployments", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "create_deployment", lambda *a, **k: 11)
    monkeypatch.setattr(server.repo, "add_chat", lambda *a, **k: 1)
    monkeypatch.setattr(server.engine, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: {"key_id": "k"})
    monkeypatch.setattr(server.agent, "_is_deployment_candidate", lambda cur, sid: False)
    with pytest.raises(server.ApiError, match="deployment candidate"):
        server.create_deployment(ctx({"strategy_id": 5, "mode": "live", "confirm": "LIVE"}))
    # Cleared -> the original gates take over (here: confirmation), proving the gate is additive.
    monkeypatch.setattr(server.agent, "_is_deployment_candidate", lambda cur, sid: True)
    assert server.create_deployment(ctx({"strategy_id": 5, "mode": "live", "confirm": "LIVE"})) == {"id": 11}


def test_dashboard_mode_buckets_do_not_double_count(monkeypatch):
    # Three money buckets (live / demo / paper), each from its own positions + deployments only.
    open_pos = [
        {"mode": "paper", "qty": 10, "entry_price": 0.4},
        {"mode": "demo", "qty": 5, "entry_price": 0.5},
        {"mode": "live", "qty": 2, "entry_price": 0.6},
        {"mode": "demo", "qty": 4, "entry_price": 0.25},
    ]
    deps = [
        {"mode": "live", "status": "running"}, {"mode": "demo", "status": "running"},
        {"mode": "demo", "status": "paused"}, {"mode": "paper", "status": "stopped"},
    ]
    monkeypatch.setattr(server.repo, "realized_pnl",
                        lambda cur, uid, mode, since=None: {"paper": 3.0, "demo": -1.0, "live": 7.0}[mode])
    live = server._mode_bucket(None, 1, "live", open_pos, deps, object())
    demo = server._mode_bucket(None, 1, "demo", open_pos, deps, object())
    paper = server._mode_bucket(None, 1, "paper", open_pos, deps, object())
    assert live == {"open_at_cost": 1.2, "open_positions": 1, "running": 1, "realized_pnl": 7.0, "today_pnl": 7.0}
    assert demo["open_positions"] == 2 and demo["open_at_cost"] == 3.5 and demo["running"] == 1
    assert paper["open_positions"] == 1 and paper["running"] == 0  # a stopped deployment isn't "running"
    # Every open position lands in exactly one bucket — the three never overlap.
    assert live["open_positions"] + demo["open_positions"] + paper["open_positions"] == len(open_pos)


def test_demo_deploy_requires_dev_key(monkeypatch):
    # Demo = sandbox; it needs the user's demo key on file, nothing else money-gated.
    strat = {"id": 6, "status": "passed", "market": "btc15m", "title": "D", "spec": {"side": "yes"}}
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: dict(strat))
    monkeypatch.setattr(server.repo, "list_deployments", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "create_deployment", lambda cur, uid, sid, market, mode: 21)
    monkeypatch.setattr(server.repo, "add_chat", lambda *a, **k: 1)
    monkeypatch.setattr(server.repo, "get_kalshi_dev_key", lambda cur, uid: None)
    with pytest.raises(server.ApiError, match="demo .*sandbox. key"):
        server.create_deployment(ctx({"strategy_id": 6, "mode": "demo"}))
    # With a demo key on file it deploys — no LIVE switch, no confirmation, no gatekeeper gate.
    monkeypatch.setattr(server.repo, "get_kalshi_dev_key", lambda cur, uid: {"key_id": "DEV-k"})
    assert server.create_deployment(ctx({"strategy_id": 6, "mode": "demo"})) == {"id": 21}


def test_save_kalshi_dev_key_encrypts_and_never_echoes_raw(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                            serialization.NoEncryption()).decode()
    stored = {}
    from contextlib import nullcontext
    monkeypatch.setattr(server.repo, "transaction", lambda conn: nullcontext(FakeCur()))
    monkeypatch.setattr(server.kalshi_perps_trading, "guard_key_change", lambda *args: None)
    monkeypatch.setattr(server.kalshi_dev_exec, "demo_fills", lambda creds: {"fills": []})  # sandbox auth OK
    monkeypatch.setattr(server.kalshi_account, "encrypt_private_key", lambda uid, p: b"ENC(" + p.encode() + b")")
    monkeypatch.setattr(server.repo, "set_kalshi_dev_key",
                        lambda cur, uid, kid, blob: stored.update(uid=uid, key_id=kid, blob=blob))
    out = server.save_kalshi_dev_key(ctx({"key_id": "DEV-1", "private_key": pem}))
    assert out == {"ok": True}  # the raw key is never returned
    assert stored["key_id"] == "DEV-1" and stored["blob"].startswith(b"ENC(")  # encrypted, not plaintext
    assert pem not in repr(out)
    # A bad PEM is rejected at the trust boundary, before any store.
    stored.clear()
    with pytest.raises(server.ApiError, match="private key"):
        server.save_kalshi_dev_key(ctx({"key_id": "DEV-1", "private_key": "not a key"}))
    assert stored == {}


# -- Strategies listing: pagination + true COUNT(*) figures --------------------------


class StratCur:
    """Captures the last SQL/params and replays canned GROUP BY rows."""

    def __init__(self, group_rows=()):
        self.group_rows = list(group_rows)
        self.sql = None
        self.params = None

    def execute(self, sql, params=()):
        self.sql = " ".join(sql.split())
        self.params = list(params)

    def fetchall(self):
        return self.group_rows if "GROUP BY" in (self.sql or "") else []


def test_count_strategies_uses_count_star_grouped():
    cur = StratCur([{"status": "passed", "n": 600}, {"status": "failed", "n": 500}, {"status": "rejected", "n": 133}])
    counts = server.repo.count_strategies(cur, 1)
    assert "COUNT(*)" in cur.sql and "GROUP BY s.status" in cur.sql
    assert counts == {"passed": 600, "failed": 500, "rejected": 133, "total": 1233}


def test_list_strategies_applies_limit_and_offset():
    cur = StratCur()
    server.repo.list_strategies(cur, 1, limit=50, offset=100)
    assert "LIMIT %s OFFSET %s" in cur.sql and cur.params[-2:] == [50, 100]


def test_strategies_figures_come_from_count_not_the_page(monkeypatch):
    # Counts far exceed the 50-row page, proving the figures aren't len(page).
    monkeypatch.setattr(server.repo, "count_strategies",
                        lambda cur, uid, d, m, *a, **k: {"passed": 600, "failed": 400, "rejected": 233, "total": 1233})
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [{"id": i} for i in range(50)])
    monkeypatch.setattr(server, "_strategy_card", lambda s: s)
    out = server.list_strategies(ctx(query={}))
    assert out["counts"]["total"] == 1233 and len(out["strategies"]) == 50
    # Default "Kept" view hides rejected/void, so matched = total - (failed + rejected) = 600.
    assert out["matched"] == 600 and out["pages"] == 12 and out["page"] == 0
    # A status filter narrows "matched" to that status's true count.
    out = server.list_strategies(ctx(query={"status": "passed"}))
    assert out["matched"] == 600 and out["pages"] == 12


def test_strategies_page_param_maps_to_offset(monkeypatch):
    seen = {}
    monkeypatch.setattr(server.repo, "count_strategies", lambda *a, **k: {"passed": 10, "total": 120})

    def fake_list(cur, uid, direction=None, status=None, market=None, run_id=None, limit=500, offset=0, q=None, deployed=False, hide_noise=False):
        seen.update(limit=limit, offset=offset)
        return []

    monkeypatch.setattr(server.repo, "list_strategies", fake_list)
    monkeypatch.setattr(server, "_strategy_card", lambda s: s)
    out = server.list_strategies(ctx(query={"page": "2"}))
    assert seen == {"limit": 50, "offset": 100}
    assert out["page"] == 2 and out["per"] == 50 and out["pages"] == 3


def test_strategies_search_and_deployed_thread_to_repo(monkeypatch):
    seen = {}
    monkeypatch.setattr(server.repo, "count_strategies",
                        lambda cur, uid, d, m, q=None, deployed=False: seen.update(cq=q, cdep=deployed) or {"total": 0})
    monkeypatch.setattr(server.repo, "list_strategies",
                        lambda *a, q=None, deployed=False, **k: seen.update(lq=q, ldep=deployed) or [])
    monkeypatch.setattr(server, "_strategy_card", lambda s: s)
    server.list_strategies(ctx(query={"q": "  tails  ", "deployed": "1"}))
    assert seen["lq"] == "tails" and seen["cq"] == "tails"  # trimmed
    assert seen["ldep"] is True and seen["cdep"] is True
    # Absent/false by default.
    server.list_strategies(ctx(query={}))
    assert seen["lq"] is None and seen["ldep"] is False


def test_mark_fields_unrealized_pnl():
    # YES: bought 10 @ 0.40 (cost 4.00 + 0.05 fee), now bid 0.55 -> value 5.50, unreal +1.45.
    y = server._mark_fields({"qty": 10, "side": "yes", "entry_price": 0.40, "entry_fee": 0.05, "mark_price": 0.55})
    assert y["value"] == 5.50 and y["unrealized"] == 1.45
    # NO: value estimated as 1-bid. Bought 10 @ 0.30 (cost 3.00), bid 0.55 -> NO value 4.50, unreal +1.50.
    n = server._mark_fields({"qty": 10, "side": "no", "entry_price": 0.30, "entry_fee": 0.0, "mark_price": 0.55})
    assert n["value"] == 4.50 and n["unrealized"] == 1.50
    # Not yet marked -> all None (UI shows a dash, never a wrong number).
    u = server._mark_fields({"qty": 10, "side": "yes", "entry_price": 0.40, "entry_fee": 0.0, "mark_price": None})
    assert u["unrealized"] is None and u["value"] is None


def test_strategies_bad_page_defaults_to_zero(monkeypatch):
    monkeypatch.setattr(server.repo, "count_strategies", lambda *a, **k: {"total": 0})
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [])
    monkeypatch.setattr(server, "_strategy_card", lambda s: s)
    out = server.list_strategies(ctx(query={"page": "not-a-number"}))
    assert out["page"] == 0 and out["matched"] == 0 and out["pages"] == 0 and out["strategies"] == []


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


def test_new_signin_is_blocked_unless_approved(monkeypatch):
    from app import repository as repo
    seen = {}

    class Cur:
        def execute(self, sql, params=()):
            pass
        def fetchone(self):
            return None  # no existing account for this google_sub

    monkeypatch.setattr(repo, "add_waitlist", lambda cur, email, note: seen.update(waitlisted=email) or True)
    # A brand-new, non-approved sign-in creates NO account and is waitlisted instead.
    assert repo.upsert_google_user(Cur(), "newsub", "new@x.com", "New", None, allow_new=False) is None
    assert seen["waitlisted"] == "new@x.com"


def test_admin_waitlist_approve_and_errors(monkeypatch):
    monkeypatch.setattr(server, "_require_admin", lambda ctx: None)
    calls = {}
    monkeypatch.setattr(server.repo, "set_waitlist_status", lambda cur, e, s: calls.update(approve=(e, s)) or True)
    monkeypatch.setattr(server.repo, "remove_waitlist", lambda cur, e: calls.update(remove=e) or True)
    # happy path: approve
    assert server.admin_waitlist(ctx({"email": "a@b.com", "action": "approve"}))["ok"] is True
    assert calls["approve"] == ("a@b.com", "approved")
    # error path: unknown action
    with pytest.raises(server.ApiError):
        server.admin_waitlist(ctx({"email": "a@b.com", "action": "nope"}))
    # error path: email not on the waitlist
    monkeypatch.setattr(server.repo, "remove_waitlist", lambda cur, e: False)
    with pytest.raises(server.ApiError):
        server.admin_waitlist(ctx({"email": "x@y.com", "action": "remove"}))


def test_delete_strategy_blocks_when_deployed(monkeypatch):
    monkeypatch.setattr(server, "_owned_strategy", lambda c: {"id": 5, "status": "passed"})
    monkeypatch.setattr(server.repo, "delete_strategy", lambda cur, uid, sid: True)
    # deployed -> refused
    monkeypatch.setattr(server.repo, "list_deployments", lambda cur, uid, include_stopped=False: [{"strategy_id": 5}])
    with pytest.raises(server.ApiError):
        server.delete_strategy(ctx({}))
    # not deployed -> deleted
    monkeypatch.setattr(server.repo, "list_deployments", lambda cur, uid, include_stopped=False: [])
    assert server.delete_strategy(ctx({})) == {"ok": True}


def test_dig_deeper_seeds_a_research_run_from_a_passed_strategy(monkeypatch):
    parent = {"id": 55, "status": "passed", "market": "btc15m", "direction": "volatility",
              "title": "Tail fade", "thesis": "Cheap OTM YES is overpriced.", "spec": {"side": "yes", "market": "btc15m"}}
    seen = {}
    monkeypatch.setattr(server, "_owned_strategy", lambda c: dict(parent))
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(server.repo, "create_run",
                        lambda cur, uid, kind, market, direction, prompt, **kw:
                        (seen.update(kind=kind, market=market, seed=kw.get("seed_strategy_id"), prompt=prompt), 77)[1])
    assert server.dig_deeper(ctx({}, params=("55",))) == {"id": 77}
    assert seen["kind"] == "research" and seen["market"] == "btc15m" and seen["seed"] == 55
    assert "Dig deeper" in seen["prompt"]            # the passed strategy's thesis/spec seeds the run


def test_dig_deeper_refuses_a_strategy_that_did_not_pass(monkeypatch):
    monkeypatch.setattr(server, "_owned_strategy", lambda c: {"id": 55, "status": "failed", "market": "btc15m"})
    monkeypatch.setattr(server.repo, "create_run", lambda *a, **k: pytest.fail("must not seed research from an unpassed strategy"))
    with pytest.raises(server.ApiError) as e:
        server.dig_deeper(ctx({}, params=("55",)))
    assert e.value.status == 409


def test_dig_deeper_is_rate_limited(monkeypatch):
    monkeypatch.setattr(server, "_owned_strategy", lambda c: {"id": 55, "status": "passed", "market": "btc15m", "direction": None, "title": "T", "thesis": "x", "spec": {}})
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 99)
    with pytest.raises(server.ApiError) as e:
        server.dig_deeper(ctx({}, params=("55",)))
    assert e.value.status == 429


def test_share_strategy_copies_and_notifies(monkeypatch):
    calls = {}
    monkeypatch.setattr(server, "_owned_strategy", lambda c: {"id": 5, "title": "Tail fade"})
    monkeypatch.setattr(server.repo, "user_by_email", lambda cur, e: {"id": 2, "name": "Bob", "email": e})
    monkeypatch.setattr(server.repo, "share_strategy", lambda cur, src, frm, to: (calls.__setitem__("share", (src, frm, to)), 99)[1])
    monkeypatch.setattr(server.repo, "get_user", lambda cur, uid: {"name": "Alice"})
    monkeypatch.setattr(server.repo, "add_notification", lambda cur, uid, kind, body, link: calls.setdefault("notif", (uid, kind, link)))
    out = server.share_strategy(ctx({"email": "Bob@X.com"}))
    assert out["ok"] and calls["share"] == (5, 1, 2)  # src 5, from uid 1, to uid 2
    assert calls["notif"] == (2, "share", "/strategies/99")


def test_share_strategy_rejects_unknown_self_and_bad_email(monkeypatch):
    monkeypatch.setattr(server, "_owned_strategy", lambda c: {"id": 5, "title": "X"})
    with pytest.raises(server.ApiError, match="email your friend"):
        server.share_strategy(ctx({"email": "notanemail"}))
    monkeypatch.setattr(server.repo, "user_by_email", lambda cur, e: None)
    with pytest.raises(server.ApiError, match="No Tau account"):
        server.share_strategy(ctx({"email": "ghost@x.com"}))
    monkeypatch.setattr(server.repo, "user_by_email", lambda cur, e: {"id": 1, "name": "Me"})  # uid 1 == self
    with pytest.raises(server.ApiError, match="your own account"):
        server.share_strategy(ctx({"email": "me@x.com"}))


def test_share_strategy_idempotent(monkeypatch):
    notified = []
    monkeypatch.setattr(server, "_owned_strategy", lambda c: {"id": 5, "title": "X"})
    monkeypatch.setattr(server.repo, "user_by_email", lambda cur, e: {"id": 2, "name": "Bob"})
    monkeypatch.setattr(server.repo, "share_strategy", lambda *a: None)  # recipient already has it
    monkeypatch.setattr(server.repo, "add_notification", lambda *a, **k: notified.append(1))
    out = server.share_strategy(ctx({"email": "bob@x.com"}))
    assert out.get("already") and not notified  # no duplicate copy or notification


def test_notifications_endpoint_shape(monkeypatch):
    monkeypatch.setattr(server.repo, "list_notifications", lambda cur, uid, **k: [
        {"id": 3, "kind": "share", "body": "X shared Y", "link": "/strategies/9", "created_at": "t", "read_at": None}])
    monkeypatch.setattr(server.repo, "count_unread_notifications", lambda cur, uid: 1)
    out = server.notifications(ctx())
    assert out["unread"] == 1 and out["items"][0]["read"] is False and out["items"][0]["link"] == "/strategies/9"


def test_slug_and_mention_regex():
    from app import repository as r
    assert r._slug_username("Jihui.Tan+x") == "jihuitanx"
    assert r._slug_username("!!!") == "trader"  # empty slug falls back
    assert r.MENTION_RE.findall("hi @tanjihui, email foo@bar.com and @a_b2") == ["tanjihui", "a_b2"]


def test_notify_mentions_excludes_author(monkeypatch):
    notes = []
    monkeypatch.setattr(server.repo, "users_by_usernames", lambda cur, hs: [
        {"id": 2, "username": "bob", "name": "Bob", "email": "b@x.com"},
        {"id": 1, "username": "me", "name": "Me", "email": "m@x.com"}])
    monkeypatch.setattr(server.repo, "add_notification", lambda cur, uid, kind, body, link: notes.append((uid, kind)))
    monkeypatch.setattr(server.notify, "mention_notice", lambda *a, **k: True)
    server._notify_mentions(None, 1, "Me", "hey @bob and @me", "/community")
    assert notes == [(2, "mention")]  # author (uid 1) is not notified about their own mention


def test_unsubscribe_token_is_bound_to_user():
    from app import notify
    t = notify.unsubscribe_token(42)
    assert notify.unsubscribe_token_valid(42, t)
    assert not notify.unsubscribe_token_valid(42, "bad")
    assert not notify.unsubscribe_token_valid(43, t)  # a token for one user can't unsubscribe another


def test_unsubscribe_endpoint_opts_out_on_valid_token(monkeypatch):
    from app import notify
    flips = {}
    monkeypatch.setattr(server.repo, "set_email_opt_out", lambda cur, uid, val: (flips.__setitem__(uid, val), True)[1])
    kind, html = server.unsubscribe(ctx(query={"u": "7", "t": notify.unsubscribe_token(7)}))
    assert kind == "html" and "unsubscribed" in html and flips == {7: True}
    flips.clear()
    kind, html = server.unsubscribe(ctx(query={"u": "7", "t": "forged"}))
    assert "isn't valid" in html and not flips  # forged token changes nothing


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
    for path in ("/", "/research/12", "/strategies", "/strategies/3", "/deploy", "/funds", "/signin",
                 "/terms", "/privacy"):
        assert server.SPA_ROUTES.match(path)
    assert not server.SPA_ROUTES.match("/static/../etc/passwd")


def test_open_signup_flag_controls_new_account_creation(monkeypatch):
    # The APP_OPEN_SIGNUP flag decides whether a brand-new, non-approved Google email can create an
    # account. The value passed as allow_new to upsert_google_user is the gate.
    captured = {}
    monkeypatch.setattr(server.repo, "pop_oauth_state", lambda cur, s: {"code_verifier": "v", "nonce": "n"})
    monkeypatch.setattr(server.auth, "exchange_code",
                        lambda code, v, n: {"email": "rando@x.com", "sub": "s1", "name": "R", "picture": None})
    monkeypatch.setattr(server.repo, "is_waitlist_approved", lambda cur, e: False)
    monkeypatch.setattr(server.repo, "upsert_google_user",
                        lambda cur, sub, email, name, pic, allow_new: captured.update(allow_new=allow_new) or {"id": 42})
    monkeypatch.setattr(server, "_start_session", lambda ctx, uid: None)

    class Ctx:
        cur = None
        set_cookies = []
        query = {"code": "c", "state": "st"}

    monkeypatch.setattr(server, "OPEN_SIGNUP", False)   # invite-only (default)
    server.google_callback(Ctx())
    assert captured["allow_new"] is False               # a random email is waitlisted, not admitted

    monkeypatch.setattr(server, "OPEN_SIGNUP", True)     # open signup
    server.google_callback(Ctx())
    assert captured["allow_new"] is True                # the same random email is now admitted
