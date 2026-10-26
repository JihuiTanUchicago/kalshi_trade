import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app import server
from app.web.routes import dashboard as dashboard_routes
from app.web.routes import research as research_routes
from app.web.routes import explore as explore_routes
from app.web.routes import strategies as strategy_routes
from app.web import auth
from app.web.routes import admin as admin_routes
from app.web.routes import auth as auth_routes
from app.adapters.kalshi import kalshi_account


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
    monkeypatch.setattr(server.agent, "_proven_on_paper", lambda cur, uid, sid: (True, ""))
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
    monkeypatch.setattr(server.agent, "_proven_on_paper", lambda cur, uid, sid: (True, ""))
    with pytest.raises(server.ApiError, match="deployment candidate"):
        server.create_deployment(ctx({"strategy_id": 5, "mode": "live", "confirm": "LIVE"}))
    # Cleared -> the original gates take over (here: confirmation), proving the gate is additive.
    monkeypatch.setattr(server.agent, "_is_deployment_candidate", lambda cur, sid: True)
    assert server.create_deployment(ctx({"strategy_id": 5, "mode": "live", "confirm": "LIVE"})) == {"id": 11}


def test_live_refuses_a_strategy_not_proven_on_paper(monkeypatch):
    # The manual live path needs the same paper record as the autopilot's deploy_live, even for a
    # gatekeeper deployment candidate with every other live gate green.
    strat = {"id": 5, "status": "passed", "market": "btc15m", "title": "T", "spec": {"side": "yes"}}
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: dict(strat))
    monkeypatch.setattr(server.repo, "list_deployments", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "create_deployment", lambda *a, **k: 11)
    monkeypatch.setattr(server.repo, "add_chat", lambda *a, **k: 1)
    monkeypatch.setattr(server.engine, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: {"key_id": "k"})
    monkeypatch.setattr(server.agent, "_is_deployment_candidate", lambda cur, sid: True)
    monkeypatch.setattr(server.agent, "_proven_on_paper",
                        lambda cur, uid, sid: (False, "it needs 30+ closed paper trades on realistic fills first (has 3)"))
    with pytest.raises(server.ApiError, match="proven itself on paper.*has 3") as e:
        server.create_deployment(ctx({"strategy_id": 5, "mode": "live", "confirm": "LIVE"}))
    assert e.value.status == 409
    # Paper stays open: the paper record is what this gate waits for.
    assert server.create_deployment(ctx({"strategy_id": 5, "mode": "paper"})) == {"id": 11}


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
    assert live == {"closed_trades": 0, "open_at_cost": 1.2, "open_positions": 1, "running": 1, "realized_pnl": 7.0, "today_pnl": 7.0}
    assert demo["open_positions"] == 2 and demo["open_at_cost"] == 3.5 and demo["running"] == 1
    assert paper["open_positions"] == 1 and paper["running"] == 0  # a stopped deployment isn't "running"
    # Every open position lands in exactly one bucket — the three never overlap.
    assert live["open_positions"] + demo["open_positions"] + paper["open_positions"] == len(open_pos)


def test_dashboard_paper_book_carries_its_reset_so_all_time_labels_stay_true(monkeypatch):
    # total_pnl is equity minus deposits, and a reset wipes the ledger, so the client labels it
    # "since reset" when reset_at is set. The money math itself is unchanged.
    from datetime import datetime
    at = datetime(2026, 10, 20, 9, 0)
    for name, fn in {
        "user_positions": lambda *a, **k: [], "list_deployments_for_display": lambda *a, **k: [], "deployment_curves": lambda *a, **k: {},
        "paper_ledger_summary": lambda cur, uid: {"balance": 480.0, "deposited": 500.0, "reset_at": at},
        "paper_ledger_version": lambda cur, uid: (2, 9),  # the ledger's rows and highest id (book_memo keeps the sum)
        "closed_book_totals": lambda cur, uid, since, visit=None: ({m: (0.0, 0.0) for m in ("paper", "demo", "live")}, {"demo": 3},
                                                                     {m: (0.0, 0) for m in ("paper", "demo", "live")}),
        "daily_pnl": lambda *a, **k: [],
        "activity_since": lambda cur, uid, since: {"autopilot": {}, "runs": {}},
        "passed_since": lambda cur, uid, since: {"n": 0, "items": []},
        "demo_equity": lambda cur, uid, realized=None: {"capital": 500.0, "equity": 512.0, "realized": 12.0, "roi": .024, "before_reload": 40.0},
        "get_kalshi_key": lambda cur, uid: None, "open_reconcile_rows": lambda cur, uid: [],
        "active_run_counts": lambda cur, uid, **kw: {},
    }.items():
        monkeypatch.setattr(server.repo, name, fn)
    monkeypatch.setattr(dashboard_routes, "_freshness", lambda cur: {})
    monkeypatch.setattr(server.book_memo, "_LEDGER", {})
    out = server.dashboard(ctx())
    paper, demo = out["paper"], out["demo"]
    assert paper["reset_at"] == at and paper["total_pnl"] == -20.0 and paper["equity"] == 480.0
    # Demo P&L is since the last reload; before_reload lets the label say so (track record counts it all).
    assert demo["realized_pnl"] == 12.0 and demo["before_reload"] == 40.0 and demo["equity"] == 512.0
    # Each bucket says how many closed trades it has, so the page offers that mode's download only.
    assert (paper["closed_trades"], demo["closed_trades"], out["live"]["closed_trades"]) == (0, 3, 0)


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



def test_key_errors_say_plainly_what_is_wrong_and_never_echo_the_key(monkeypatch):
    """A bad key gets a reason a new user can act on (which box, which site), in fixed text only."""
    secret = "MIIEsecretBODY"
    for bad in ("hello " + secret, "-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----" % secret,
                "-----BEGIN RSA PRIVATE KEY-----\n" + secret):
        with pytest.raises(kalshi_account.KalshiKeyError) as e:
            kalshi_account.parse_private_key(bad)
        assert str(e.value) == kalshi_account.PRIVATE_KEY_FORMAT and secret not in str(e.value)
        assert "-----BEGIN line to its -----END line" in str(e.value)
    with pytest.raises(kalshi_account.KalshiKeyError, match="Key ID from the API keys page on kalshi.com"):
        kalshi_account.verify("", "x")
    pem = _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    monkeypatch.setattr(kalshi_account, "balance", lambda creds: None)  # Kalshi says no (or can't be reached)
    with pytest.raises(kalshi_account.KalshiKeyError) as e:
        kalshi_account.verify("a952bcbe-ec3b-4b5b-b8f9-11dae589608c", pem)
    msg = str(e.value)
    assert "couldn't be reached just now" in msg and "demo.kalshi.co is a demo key" in msg and pem not in msg
    # The demo box points a live key back to the live box.
    monkeypatch.setattr(server.kalshi_dev_exec, "demo_fills", lambda creds: (_ for _ in ()).throw(RuntimeError("401")))
    with pytest.raises(server.ApiError) as e:
        server.save_kalshi_dev_key(ctx({"key_id": "DEV-1", "private_key": pem}))
    assert "a key from kalshi.com is a live key and goes in the Kalshi account box" in str(e.value)
    assert pem not in str(e.value)


def test_funds_reads_the_demo_balance_and_a_new_key_is_never_shown_an_old_balance(monkeypatch):
    """Funds says "Connected ✓ (balance $X)" for both keys from the existing cached reads; saving a key
    replaces what those caches hold, so the line never shows the previous key's cash."""
    from contextlib import nullcontext

    from app.trading import demo_twins

    keys = {"live": None, "dev": {"key_id": "DEVKEY-1234"}}
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: keys["live"])
    monkeypatch.setattr(server.repo, "get_kalshi_dev_key", lambda cur, uid: keys["dev"])
    monkeypatch.setattr(server.repo, "demo_equity", lambda cur, uid, realized=None: {"capital": 1000, "equity": 1000, "realized": 0, "before_reload": False})
    monkeypatch.setattr(server.repo, "paper_balance", lambda cur, uid: 1000)
    monkeypatch.setattr(server.repo, "ledger_rows", lambda cur, uid: [])
    monkeypatch.setattr(server.repo, "user_positions", lambda cur, uid, status: [])
    from app.services import book_memo  # Funds' realized P&L read, answered without a database
    monkeypatch.setattr(book_memo, "closed_book_totals",
                        lambda memo, day, visit=None: ({m: (0.0, 0.0) for m in ("paper", "demo", "live")}, {}, {}))
    reads = []
    monkeypatch.setattr(demo_twins, "_read_balance", lambda cur, uid, timeout=15: reads.append(uid) or 25000.0)
    demo_twins._BALANCE_CACHE.clear()
    monkeypatch.setattr(demo_twins, "DEMO_TWINS", True)
    out = server.funds(ctx())
    at = out["kalshi_dev"].pop("balance_at")  # when that memo was filled, like the Kalshi cash line
    # copies_from: the demo cash the autopilot's demo copies wait for, so Funds can say why a small balance starts none.
    assert out["kalshi_dev"] == {"connected": True, "key_id": "DEVK…1234", "balance": 25000.0,
                                 "copies_from": demo_twins.DEMO_TWIN_MIN_BALANCE}
    assert at is not None and at.tzinfo is None
    assert reads == [1]
    monkeypatch.setattr(demo_twins, "DEMO_TWINS", False)  # copies off (APP_DEMO_TWINS=0): no threshold to name
    assert server.funds(ctx())["kalshi_dev"]["copies_from"] is None
    keys["dev"] = None
    assert server.funds(ctx())["kalshi_dev"] == {"connected": False}  # no key, no read
    # Saving a demo key drops the memo, so the next Funds read uses the new key.
    pem = _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    monkeypatch.setattr(server.repo, "transaction", lambda conn: nullcontext(FakeCur()))
    monkeypatch.setattr(server.kalshi_perps_trading, "guard_key_change", lambda *args: None)
    monkeypatch.setattr(server.kalshi_dev_exec, "demo_fills", lambda creds: {"fills": []})
    monkeypatch.setattr(server.kalshi_account, "encrypt_private_key", lambda uid, p: b"ENC")
    monkeypatch.setattr(server.repo, "set_kalshi_dev_key", lambda cur, uid, kid, blob: None)
    assert 1 in demo_twins._BALANCE_CACHE
    server.save_kalshi_dev_key(ctx({"key_id": "DEV-1", "private_key": pem}))
    assert 1 not in demo_twins._BALANCE_CACHE
    # Saving a live key seeds the memo with the balance Kalshi just returned while verifying it.
    kalshi_account._BALANCE_CACHE[1] = (0.0, 5.0)  # what the previous key held
    monkeypatch.setattr(kalshi_account, "balance", lambda creds: 1234.5)
    monkeypatch.setattr(server.repo, "save_kalshi_key", lambda cur, uid, kid, blob: None)
    monkeypatch.setattr(server.repo, "list_deployments", lambda cur, uid: [])
    assert server.save_kalshi_key(ctx({"key_id": "a952bcbe", "private_key": pem})) == {"ok": True, "balance": 1234.5}
    monkeypatch.setattr(kalshi_account, "balance", lambda creds: (_ for _ in ()).throw(AssertionError("no re-read")))
    assert kalshi_account.balance_cached(1, None) == 1234.5
    kalshi_account._BALANCE_CACHE.pop(1, None)


def test_replacing_the_live_key_is_refused_while_live_deployments_run(monkeypatch):
    """Their open positions sit on the account the current key trades; a new key would send their
    exits to another account. Same rule as disconnecting; a first key, or none running, saves."""
    from contextlib import nullcontext

    pem = _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    saved = []
    deps = [{"mode": "live", "status": "running"}, {"mode": "paper", "status": "running"}]
    monkeypatch.setattr(server.repo, "transaction", lambda conn: nullcontext(FakeCur()))
    monkeypatch.setattr(server.repo, "list_deployments", lambda cur, uid: deps)
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda cur, uid: {"key_id": "OLD-KEY-1"})
    monkeypatch.setattr(server.repo, "save_kalshi_key", lambda cur, uid, kid, blob: saved.append(kid))
    monkeypatch.setattr(server.kalshi_perps_trading, "guard_key_change", lambda *args: None)
    monkeypatch.setattr(server.kalshi_account, "encrypt_private_key", lambda uid, p: b"ENC")
    monkeypatch.setattr(kalshi_account, "balance", lambda creds: 10.0)
    with pytest.raises(server.ApiError) as e:
        server.save_kalshi_key(ctx({"key_id": "NEW-KEY-2", "private_key": pem}))
    assert e.value.status == 409 and "replacing your Kalshi key" in str(e.value) and saved == []
    deps[0]["status"] = "paused"
    assert server.save_kalshi_key(ctx({"key_id": "NEW-KEY-2", "private_key": pem}))["ok"] is True
    assert saved == ["NEW-KEY-2"]
    kalshi_account._BALANCE_CACHE.pop(1, None)

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
    assert counts == {"passed": 600, "failed": 500, "rejected": 133, "total": 1233, "deployed": 0, "examples": {}}
    cur = StratCur([{"status": "passed", "n": 6, "dep": 4}, {"status": "rejected", "n": 2, "dep": None}])
    assert server.repo.count_strategies(cur, 1) == {"passed": 6, "rejected": 2, "total": 8, "deployed": 4, "examples": {}}


def test_count_strategies_leaves_the_seeded_example_out():
    # A new account read "Rejected (2)" from the example session the app seeded, not research it ran.
    cur = StratCur([{"status": "rejected", "n": 2, "dep": 0, "ex": 2}])
    counts = server.repo.count_strategies(cur, 1)
    assert counts == {"rejected": 0, "total": 0, "deployed": 0, "examples": {"rejected": 2}}
    assert "s.direction=%s" in cur.sql and cur.params[0] == server.repo.DEMO_DIRECTION and cur.params[1] == 1
    cur = StratCur([{"status": "passed", "n": 3, "dep": 1, "ex": 0}, {"status": "rejected", "n": 7, "dep": 0, "ex": 2}])
    assert server.repo.count_strategies(cur, 1) == {"passed": 3, "rejected": 5, "total": 8, "deployed": 1, "examples": {"rejected": 2}}


def test_strategies_list_still_shows_the_example_rows_and_marks_them(monkeypatch):
    counts = {"rejected": 0, "total": 0, "deployed": 0, "examples": {"rejected": 2}}
    monkeypatch.setattr(server.repo, "count_strategies", lambda *a, **k: dict(counts))
    rows = [{"id": 1, "direction": "random_walk"}, {"id": 2, "direction": "random_walk"}]
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: rows)
    monkeypatch.setattr(strategy_routes, "_strategy_card", lambda s: {**s, "example": s["direction"] == server.repo.DEMO_DIRECTION})
    # The default (Kept) view hides rejected rows, examples included; the Rejected chip lists them.
    assert server.list_strategies(ctx(query={}))["matched"] == 0
    out = server.list_strategies(ctx(query={"status": "rejected"}))
    assert out["matched"] == 2 and out["pages"] == 1 and out["counts"]["rejected"] == 0
    assert all(c["example"] for c in out["strategies"])


def test_strategy_detail_marks_a_seeded_example_strategy(monkeypatch):
    # The detail page shows the same Example tag and note as the lists, so its payload carries the flag.
    row = {"id": 4, "run_id": 1, "parent_id": None, "market": "btc15m", "title": "Walk", "thesis": "t", "status": "rejected",
           "created_at": None, "result": {}, "spec": {"sizing": {"stake": 5}, "side": "yes"}, "experiment_id": None}
    monkeypatch.setattr(server.specmod, "describe", lambda spec: [])
    monkeypatch.setattr(strategy_routes, "_experiment_block", lambda *a: None)
    monkeypatch.setattr(server.repo, "list_deployments_for_display", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "positions_for_strategy", lambda *a: [])
    for direction, example in ((server.repo.DEMO_DIRECTION, True), ("momentum", False)):
        monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid, d=direction: {**row, "direction": d})
        assert server.get_strategy(ctx(params=("4",)))["example"] is example


def test_strategy_detail_answers_on_a_stored_spec_with_no_model_or_sizing(monkeypatch):
    # A seeded row's spec had no `model` and the page answered 500; one with no sizing broke the cards too.
    # tests/test_old_rows_fuzz_db.py walks every stored key against a real MySQL.
    row = {"id": 4, "run_id": 1, "parent_id": None, "market": "btc15m", "title": "Seeded", "thesis": "t",
           "status": "passed", "created_at": None, "result": {}, "direction": "momentum", "experiment_id": None,
           "spec": {"side": "yes", "entry": {"min_edge": 0.05}}}
    monkeypatch.setattr(strategy_routes, "_experiment_block", lambda *a: None)
    monkeypatch.setattr(strategy_routes, "_demo_health", lambda *a, **k: None)
    monkeypatch.setattr(server.repo, "list_deployments_for_display", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "positions_for_strategy", lambda *a: [])
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: dict(row))
    out = server.get_strategy(ctx(params=("4",)))
    assert out["rules"] == ["Buys YES contracts when its fair value beats the price by at least 5¢."]
    assert out["stake"] is None and out["side"] == "yes"


def test_list_strategies_applies_limit_and_offset():
    cur = StratCur()
    server.repo.list_strategies(cur, 1, limit=50, offset=100)
    assert "LIMIT %s OFFSET %s" in cur.sql and cur.params[-2:] == [50, 100]


def test_strategies_figures_come_from_count_not_the_page(monkeypatch):
    # Counts far exceed the 50-row page, proving the figures aren't len(page).
    monkeypatch.setattr(server.repo, "count_strategies",
                        lambda cur, uid, d, m, *a, **k: {"passed": 600, "failed": 400, "rejected": 233, "total": 1233})
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [{"id": i} for i in range(50)])
    monkeypatch.setattr(strategy_routes, "_strategy_card", lambda s: s)
    out = server.list_strategies(ctx(query={}))
    assert out["counts"]["total"] == 1233 and len(out["strategies"]) == 50
    # Default "Kept" view hides rejected/void, so matched = total - (failed + rejected) = 600.
    assert out["matched"] == 600 and out["pages"] == 12 and out["page"] == 0
    # A status filter narrows "matched" to that status's true count.
    out = server.list_strategies(ctx(query={"status": "passed"}))
    assert out["matched"] == 600 and out["pages"] == 12


def test_strategies_list_attaches_real_record_to_deployed_cards(monkeypatch):
    monkeypatch.setattr(server.repo, "count_strategies", lambda *a, **k: {"passed": 3, "total": 3})
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [
        {"id": 1, "deployed": True}, {"id": 2, "deployed": False}, {"id": 3, "deployed": True}])
    monkeypatch.setattr(strategy_routes, "_strategy_card", lambda s: dict(s))
    deps = [{"strategy_id": 1, "mode": "paper", "realized_pnl": 1.004, "closed_trades": 3, "open_positions": 1},
            {"strategy_id": 1, "mode": "demo", "realized_pnl": "-0.5", "closed_trades": 2, "open_positions": 0},
            {"strategy_id": 2, "mode": "paper", "realized_pnl": 9, "closed_trades": 9, "open_positions": 0}]
    monkeypatch.setattr(server.repo, "list_deployments_for_display", lambda cur, uid, **k: deps)
    cards = {c["id"]: c for c in server.list_strategies(ctx(query={}))["strategies"]}
    # Paper is the book shown; the demo (sandbox) book rides beside it, never added in (1.004 - 0.5).
    assert cards[1]["real"] == {"pnl": 1.0, "trades": 3, "open": 1, "live": False, "paused": False, "mode": "paper",
                                "demo": {"pnl": -0.5, "trades": 2, "open": 0}}
    assert "real" not in cards[2] and "real" not in cards[3]  # not deployed / no active deployment rows
    # A live deployment reports live money only; the paper dollars are never added in.
    deps.append({"strategy_id": 1, "mode": "live", "realized_pnl": 0.25, "closed_trades": 1, "open_positions": 0})
    cards = {c["id"]: c for c in server.list_strategies(ctx(query={}))["strategies"]}
    assert cards[1]["real"] == {"pnl": 0.25, "trades": 1, "open": 0, "live": True, "paused": False, "mode": "live"}
    # An auto-paused deployment flags its book, so the list can say it stopped.
    deps[-1]["status"] = "paused"
    cards = {c["id"]: c for c in server.list_strategies(ctx(query={}))["strategies"]}
    assert cards[1]["real"]["paused"] is True
    # A demo-only strategy reports its demo book, marked as demo.
    deps[:] = [{"strategy_id": 1, "mode": "demo", "realized_pnl": 2, "closed_trades": 1, "open_positions": 0}]
    cards = {c["id"]: c for c in server.list_strategies(ctx(query={}))["strategies"]}
    assert cards[1]["real"] == {"pnl": 2.0, "trades": 1, "open": 0, "live": False, "paused": False, "mode": "demo"}


def test_strategies_list_skips_deployment_query_without_deployed_cards(monkeypatch):
    monkeypatch.setattr(server.repo, "count_strategies", lambda *a, **k: {"passed": 1, "total": 1})
    monkeypatch.setattr(server.repo, "list_strategies", lambda *a, **k: [{"id": 1, "deployed": False}])
    monkeypatch.setattr(strategy_routes, "_strategy_card", lambda s: dict(s))
    monkeypatch.setattr(server.repo, "list_deployments_for_display", lambda *a, **k: pytest.fail("no deployed card, no query"))
    assert "real" not in server.list_strategies(ctx(query={}))["strategies"][0]


def test_strategies_page_param_maps_to_offset(monkeypatch):
    seen = {}
    monkeypatch.setattr(server.repo, "count_strategies", lambda *a, **k: {"passed": 10, "total": 120})

    def fake_list(cur, uid, direction=None, status=None, market=None, run_id=None, limit=500, offset=0, q=None, deployed=False, hide_noise=False):
        seen.update(limit=limit, offset=offset)
        return []

    monkeypatch.setattr(server.repo, "list_strategies", fake_list)
    monkeypatch.setattr(strategy_routes, "_strategy_card", lambda s: s)
    out = server.list_strategies(ctx(query={"page": "2"}))
    assert seen == {"limit": 50, "offset": 100}
    assert out["page"] == 2 and out["per"] == 50 and out["pages"] == 3


def test_strategies_search_and_deployed_thread_to_repo(monkeypatch):
    seen = {}
    monkeypatch.setattr(server.repo, "count_strategies",
                        lambda cur, uid, d, m, q=None, deployed=False: seen.update(cq=q, cdep=deployed) or {"total": 0})
    monkeypatch.setattr(server.repo, "list_strategies",
                        lambda *a, q=None, deployed=False, **k: seen.update(lq=q, ldep=deployed) or [])
    monkeypatch.setattr(strategy_routes, "_strategy_card", lambda s: s)
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
    monkeypatch.setattr(strategy_routes, "_strategy_card", lambda s: s)
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


def test_a_reply_that_mentions_the_author_is_one_bell_line_opening_that_post(monkeypatch):
    from app.web.routes import community as community_routes
    bells = []
    monkeypatch.setattr(community_routes.repo, "add_comment", lambda *a, **k: 1)
    monkeypatch.setattr(community_routes.repo, "get_user", lambda cur, uid: {"id": uid, "name": "Bob"})
    monkeypatch.setattr(community_routes.notify, "comment_notice", lambda *a, **k: True)
    monkeypatch.setattr(community_routes.notify, "mention_notice", lambda *a, **k: True)
    monkeypatch.setattr(community_routes.repo, "post_author", lambda cur, pid: {"user_id": 2, "email": None, "name": "Alice"})
    monkeypatch.setattr(community_routes.repo, "users_by_usernames",
                        lambda cur, names: [{"id": 2, "email": None}, {"id": 3, "email": None}])
    monkeypatch.setattr(community_routes.repo, "add_notification",
                        lambda cur, uid, kind, body, link: bells.append((uid, kind, link)))
    server.create_comment(ctx({"body": "@alice @cat look"}, params=("7",)))
    # Alice (the author) gets the reply line only; Cat, mentioned, gets hers; both open post 7.
    assert sorted(bells) == [(2, "comment", "/community#post-7"), (3, "mention", "/community#post-7")]


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
    monkeypatch.setattr(admin_routes, "_require_admin", lambda ctx: None)
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
    monkeypatch.setattr(strategy_routes, "_owned_strategy", lambda c: {"id": 5, "status": "passed"})
    monkeypatch.setattr(server.repo, "delete_strategy", lambda cur, uid, sid: True)
    # deployed -> refused
    monkeypatch.setattr(server.repo, "list_deployments", lambda cur, uid, include_stopped=False: [{"strategy_id": 5}])
    with pytest.raises(server.ApiError):
        server.delete_strategy(ctx({}))
    # stopped, but its deployments still hold open positions -> refused, counted by mode
    monkeypatch.setattr(server.repo, "list_deployments", lambda cur, uid, include_stopped=False: [])
    held = [{"mode": "live"}, {"mode": "paper"}, {"mode": "paper"}]
    monkeypatch.setattr(server.repo, "positions_for_strategy", lambda cur, uid, sid, status="open": list(held))
    with pytest.raises(server.ApiError) as e:
        server.delete_strategy(ctx({}))
    assert e.value.status == 409 and e.value.message == (
        "This strategy still holds 3 open positions (paper: 2, live: 1). They'll close at settlement; delete it after that.")
    # not deployed, nothing open -> deleted
    held.clear()
    assert server.delete_strategy(ctx({})) == {"ok": True}


def test_the_delete_block_names_each_mode_in_ladder_order():
    assert server._delete_block([]) is None
    assert server._delete_block([{"mode": "demo"}]) == (
        "This strategy still holds 1 open position (demo: 1). They'll close at settlement; delete it after that.")
    assert server._delete_block([{"mode": m} for m in ("live", "demo", "paper", "demo")]) == (
        "This strategy still holds 4 open positions (paper: 1, demo: 2, live: 1). They'll close at settlement; "
        "delete it after that.")


def test_dig_deeper_seeds_a_research_run_from_a_passed_strategy(monkeypatch):
    parent = {"id": 55, "status": "passed", "market": "btc15m", "direction": "volatility",
              "title": "Tail fade", "thesis": "Cheap OTM YES is overpriced.", "spec": {"side": "yes", "market": "btc15m"}}
    seen = {}
    monkeypatch.setattr(research_routes, "_owned_strategy", lambda c: dict(parent))
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 0)
    monkeypatch.setattr(server.repo, "create_run",
                        lambda cur, uid, kind, market, direction, prompt, **kw:
                        (seen.update(kind=kind, market=market, seed=kw.get("seed_strategy_id"), prompt=prompt), 77)[1])
    assert server.dig_deeper(ctx({}, params=("55",))) == {"id": 77}
    assert seen["kind"] == "research" and seen["market"] == "btc15m" and seen["seed"] == 55
    assert "Dig deeper" in seen["prompt"]            # the passed strategy's thesis/spec seeds the run


def test_dig_deeper_refuses_a_strategy_that_did_not_pass(monkeypatch):
    monkeypatch.setattr(research_routes, "_owned_strategy", lambda c: {"id": 55, "status": "failed", "market": "btc15m"})
    monkeypatch.setattr(server.repo, "create_run", lambda *a, **k: pytest.fail("must not seed research from an unpassed strategy"))
    with pytest.raises(server.ApiError) as e:
        server.dig_deeper(ctx({}, params=("55",)))
    assert e.value.status == 409


def test_dig_deeper_is_rate_limited(monkeypatch):
    monkeypatch.setattr(research_routes, "_owned_strategy", lambda c: {"id": 55, "status": "passed", "market": "btc15m", "direction": None, "title": "T", "thesis": "x", "spec": {}})
    monkeypatch.setattr(server.repo, "count_runs", lambda *a, **k: 99)
    with pytest.raises(server.ApiError) as e:
        server.dig_deeper(ctx({}, params=("55",)))
    assert e.value.status == 429


def test_share_strategy_copies_and_notifies(monkeypatch):
    calls = {}
    monkeypatch.setattr(strategy_routes, "_owned_strategy", lambda c: {"id": 5, "title": "Tail fade"})
    monkeypatch.setattr(server.repo, "user_by_email", lambda cur, e: {"id": 2, "name": "Bob", "email": e})
    monkeypatch.setattr(server.repo, "share_strategy", lambda cur, src, frm, to: (calls.__setitem__("share", (src, frm, to)), 99)[1])
    monkeypatch.setattr(server.repo, "get_user", lambda cur, uid: {"name": "Alice"})
    monkeypatch.setattr(server.repo, "add_notification", lambda cur, uid, kind, body, link: calls.setdefault("notif", (uid, kind, link)))
    out = server.share_strategy(ctx({"email": "Bob@X.com"}))
    assert out["ok"] and calls["share"] == (5, 1, 2)  # src 5, from uid 1, to uid 2
    assert calls["notif"] == (2, "share", "/strategies/99")


def test_share_strategy_rejects_unknown_self_and_bad_email(monkeypatch):
    monkeypatch.setattr(strategy_routes, "_owned_strategy", lambda c: {"id": 5, "title": "X"})
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
    monkeypatch.setattr(strategy_routes, "_owned_strategy", lambda c: {"id": 5, "title": "X"})
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


def test_shared_pnl_keeps_each_book_apart_with_its_trade_count(monkeypatch):
    sums = {"paper": 120.504, "live": -0.6, "demo": 999.0}
    monkeypatch.setattr(server.repo, "realized_pnl", lambda cur, uid, mode: sums[mode])
    monkeypatch.setattr(server.repo, "closed_trade_counts", lambda cur, uid: {"paper": 12, "demo": 40})
    snap = server._post_snapshot(None, 1, "pnl", 0)
    assert snap == {"kind": "pnl", "paper_pnl": 120.5, "live_pnl": -0.6, "paper_trades": 12, "live_trades": 0}


def test_shared_strategy_and_deployment_say_over_what_span(monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "title": "Fade", "market": "btc15m", "status": "passed",
        "result": {"out_of_sample": {"pnl": 4.2, "trades": 23, "win_rate": .61, "days": 9.4}}})
    assert server._post_snapshot(None, 1, "strategy", 5)["days"] == 9.4
    monkeypatch.setattr(server.repo, "get_deployment", lambda cur, uid, did: {
        "id": did, "title": "Fade", "market": "btc15m", "mode": "demo", "realized_pnl": 7.2, "closed_trades": 4,
        "created_at": datetime(2026, 10, 3, 12, 0, 0)})
    snap = server._post_snapshot(None, 1, "deployment", 9)
    assert (snap["mode"], snap["since"]) == ("demo", "2026-10-03T12:00:00Z")
    monkeypatch.setattr(server.repo, "get_deployment", lambda cur, uid, did: None)
    with pytest.raises(server.ApiError, match="isn't yours"):
        server._post_snapshot(None, 1, "deployment", 9)


def test_unsubscribe_token_is_bound_to_user():
    from app.adapters.ses import notify
    t = notify.unsubscribe_token(42)
    assert notify.unsubscribe_token_valid(42, t)
    assert not notify.unsubscribe_token_valid(42, "bad")
    assert not notify.unsubscribe_token_valid(43, t)  # a token for one user can't unsubscribe another


def test_unsubscribe_endpoint_opts_out_on_valid_token(monkeypatch):
    from app.adapters.ses import notify
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
    monkeypatch.setattr(auth_routes, "_start_session", lambda ctx, uid: None)

    class Ctx:
        cur = None
        set_cookies = []
        query = {"code": "c", "state": "st"}

    monkeypatch.setattr(auth_routes, "OPEN_SIGNUP", False)   # invite-only (default)
    server.google_callback(Ctx())
    assert captured["allow_new"] is False               # a random email is waitlisted, not admitted

    monkeypatch.setattr(auth_routes, "OPEN_SIGNUP", True)     # open signup
    server.google_callback(Ctx())
    assert captured["allow_new"] is True                # the same random email is now admitted


@pytest.mark.parametrize("was_on,body,kicks", [
    (0, {"autopilot": True}, 1),    # switched on: the first review starts now
    (1, {"autopilot": True}, 0),    # already on: no extra review
    (0, {"autopilot": False}, 0),   # off: nothing to start
])
def test_switching_autopilot_on_kicks_off_its_first_review(monkeypatch, was_on, body, kicks):
    calls = []
    monkeypatch.setattr(server.repo, "set_autopilot", lambda *a: None)
    monkeypatch.setattr(server.repo, "set_autopilot_live", lambda *a: None)
    monkeypatch.setattr(server.repo, "add_chat", lambda *a, **k: 1)
    monkeypatch.setattr(server.worker, "enqueue_review_on_switch_on", lambda cur, uid: calls.append(uid))
    c = server.Ctx(FakeConn(), {"id": 1, "autopilot": was_on}, (), {}, body, None)
    assert server.settings(c) == {"ok": True}
    assert len(calls) == kicks


def test_research_totals_are_all_time_and_cached(monkeypatch):
    # The Research headline summed its 50 newest runs; the server now totals every research run.
    calls = []
    monkeypatch.setattr(server.repo, "research_week", lambda cur, uid, since, include_demo=False: calls.append((since, include_demo)) or [{"tried": 900}, {"tried": "340"}])
    monkeypatch.setattr(server.repo, "strategies_passed_since", lambda cur, uid, since: 4)
    server._RUN_TOTALS.clear()
    assert server._research_totals(None, 77) == {"tried": 1240, "passed": 4}
    assert server._research_totals(None, 77) == {"tried": 1240, "passed": 4} and len(calls) == 1  # cached
    assert calls[0][0] < server.repo.now_utc() - server.timedelta(days=365 * 10)
    assert calls[0][1] is False  # the seeded example session is the app's, not the user's research
    server._RUN_TOTALS.clear()


def test_runs_list_marks_the_seeded_example_session(monkeypatch):
    # The example is listed, flagged so the page can say the app ran it for free, and out of the headline.
    monkeypatch.setattr(server.repo, "get_policy", lambda cur, uid: None)
    monkeypatch.setattr(server.repo, "list_runs", lambda cur, uid: [{"id": 2, "direction": "momentum"}, {"id": 1, "direction": "random_walk"}])
    monkeypatch.setattr(server.repo, "runs_spent", lambda cur, uid, ids: {})
    monkeypatch.setattr(server.repo, "active_run_counts", lambda cur, uid, **kw: {})
    monkeypatch.setattr(server.repo, "list_runs_version", lambda cur, uid: [{"id": 2}, {"id": 1}])
    monkeypatch.setattr(research_routes, "_research_totals", lambda cur, uid: {"tried": 0, "passed": 0})
    runs = {r["id"]: r for r in server.list_runs(ctx())["runs"]}
    assert runs[1]["example"] is True and runs[2]["example"] is False


def test_explore_market_errors_never_show_the_raw_exception(monkeypatch, capsys):
    import data_pipeline.common as common
    c = server.Ctx(FakeConn(), {"id": 1}, (), {"ticker": "KXNBAGAME-26OCT25TORMIN-MIN"}, {}, None)

    def proxy_down(path, params=None):
        raise OSError("HTTPSConnectionPool(host='api.elections.kalshi.com'): Tunnel connection failed: 403 Forbidden")
    monkeypatch.setattr(common, "api_get", proxy_down)
    monkeypatch.setattr(explore_routes, "_explore_feed", lambda: {"markets": []})  # not in the feed either
    with pytest.raises(server.ApiError) as err:
        server.explore_market(c)
    assert err.value.status == 502 and "Try again in a minute" in str(err.value)
    assert "HTTPSConnectionPool" not in str(err.value) and "HTTPSConnectionPool" in capsys.readouterr().out

    def missing(path, params=None):
        raise RuntimeError("GET https://api.elections.kalshi.com/trade-api/v2/markets/X failed 404: {}")
    monkeypatch.setattr(common, "api_get", missing)
    with pytest.raises(server.ApiError) as err:
        server.explore_market(c)
    assert err.value.status == 404 and "no market KXNBAGAME-26OCT25TORMIN-MIN" in str(err.value)


def test_explore_market_shows_the_market_when_only_its_history_failed(monkeypatch, capsys):
    import data_pipeline.common as common
    c = server.Ctx(FakeConn(), {"id": 1}, (), {"ticker": "KXNBAGAME-26OCT25TORMIN-MIN"}, {}, None)
    feed = {"markets": [{"t": "KXNBAGAME-26OCT25TORMIN-MIN", "s": "KXNBAGAME", "ti": "Minnesota wins", "su": "Minnesota",
                         "bid": "0.50", "ask": "0.51", "last": "0.50", "v24": "195732", "oi": "201649", "st": "active"}]}
    monkeypatch.setattr(explore_routes, "_explore_feed", lambda: feed)

    def down(path, params=None):
        raise OSError("Tunnel connection failed: 403 Forbidden")
    monkeypatch.setattr(common, "api_get", down)
    d = server.explore_market(c)  # Kalshi unreachable: the Explore feed's snapshot stands in
    assert d["history_unavailable"] is True and d["points"] == [] and d["title"] == "Minnesota wins"
    assert d["yes_bid"] == "0.50" and d["open_interest"] == "201649" and d["series"] == "KXNBAGAME"

    def candles_down(path, params=None):
        if "/candlesticks" in path:
            raise OSError("read timed out")
        return {"market": {"title": "Minnesota wins (Kalshi)", "yes_bid_dollars": "0.52", "close_time": "2026-10-26T03:00:00Z"}}
    monkeypatch.setattr(common, "api_get", candles_down)
    d = server.explore_market(c)  # the market call got through: its fresher record wins over the feed
    assert d["history_unavailable"] is True and d["title"] == "Minnesota wins (Kalshi)" and d["yes_bid"] == "0.52"
    assert d["close_time"] == "2026-10-26T03:00:00Z"


def test_explore_market_says_how_it_settles_and_lists_the_readers_positions(monkeypatch):
    # The market page answers: how does it settle, when were the figures read, and what do my strategies hold here.
    import data_pipeline.common as common
    c = server.Ctx(FakeConn(), {"id": 7}, (), {"ticker": "KXBTCD-26OCT2617-T113499.99"}, {}, None)

    def kalshi(path, params=None):
        if "/candlesticks" in path:
            return {"candlesticks": [{"end_period_ts": 1793012460, "price": {"close_dollars": "0.56"}, "volume_fp": "3"}]}
        return {"market": {"title": "Bitcoin at 5pm?", "yes_bid_dollars": "0.55", "yes_ask_dollars": "0.57", "status": "active",
                           "open_time": "2026-10-25T21:00:00Z", "close_time": "2026-10-26T21:00:00Z",
                           "expected_expiration_time": "2026-10-26T21:05:00Z", "rules_primary": "If the BRTI is above 113499.99, Yes.",
                           "rules_secondary": "Not eligible if the index is unavailable."}}
    monkeypatch.setattr(common, "api_get", kalshi)
    seen = []
    row = {"id": 1, "mode": "live", "side": "yes", "qty": 2, "entry_price": 0.52, "entry_fee": 0.02, "status": "open", "title": "Drift",
           "strategy_id": 4, "market_close_time": None, "opened_at": None, "mark_price": 0.55, "mark_ts": None,
           "order_ref": "kalshi-order", "user_id": 7}
    closed = {**row, "id": 2, "mode": "paper", "status": "closed", "exit_price": 0.75, "pnl": 0.44, "close_reason": "take_profit", "mark_price": None}
    monkeypatch.setattr(server.repo, "user_positions_in_ticker",
                        lambda cur, uid, ticker, since: seen.append((uid, ticker, since)) or {"open": [dict(row)], "closed": [dict(closed)]})
    d = server.explore_market(c)
    assert d["rules"] == "If the BRTI is above 113499.99, Yes." and d["rules_more"] == "Not eligible if the index is unavailable."
    assert d["settles_at"] == "2026-10-26T21:05:00Z" and d["result"] == ""
    assert server.re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", d["as_of"]) and "snapshot" not in d
    # Closed rows are read only from the contract's open time on (none can settle earlier).
    assert seen == [(7, "KXBTCD-26OCT2617-T113499.99", server.datetime(2026, 10, 25, 21, 0))]
    (o,), (x,) = d["mine"]["open"], d["mine"]["closed"]
    assert o["mode"] == "live" and o["cost"] == 1.06 and o["unrealized"] == 0.04 and o["strategy_id"] == 4
    assert x["mode"] == "paper" and x["pnl"] == 0.44 and "unrealized" not in x
    assert "order_ref" not in o and "user_id" not in o  # only what the page shows


def test_explore_market_still_shows_when_the_positions_read_fails(monkeypatch, capsys):
    import data_pipeline.common as common
    c = server.Ctx(FakeConn(), {"id": 7}, (), {"ticker": "KXNBAGAME-26OCT25TORMIN-MIN"}, {}, None)
    feed = {"at": "2026-10-26T10:55:00Z", "markets": [{"t": "KXNBAGAME-26OCT25TORMIN-MIN", "ti": "Minnesota wins", "bid": "0.50", "ask": "0.51"}]}
    monkeypatch.setattr(explore_routes, "_explore_feed", lambda: feed)

    def down(path, params=None):
        raise OSError("Tunnel connection failed: 403 Forbidden")
    monkeypatch.setattr(common, "api_get", down)

    def broken(*a, **k):
        raise RuntimeError("Lost connection to MySQL server")
    monkeypatch.setattr(server.repo, "user_positions_in_ticker", broken)
    d = server.explore_market(c)
    # The page says its positions didn't load (None, not an empty book); the snapshot says it is one, and when.
    assert d["mine"] is None and d["snapshot"] is True and d["as_of"] == "2026-10-26T10:55:00Z" and d["yes_bid"] == "0.50"
    assert "Lost connection" in capsys.readouterr().out


@pytest.mark.parametrize("nxt,ok", [
    ("/strategies/16", True), ("/explore?m=KXBTC-26OCT2507-T0", True), ("/research/6", True),
    (None, False), ("", False), ("strategies/16", False), ("//evil.example/x", False),
    ("https://evil.example/", False), ("/\\evil.example", False), ("/api/me", False),
    ("/strategies/16#x", False), ("/research\r\nSet-Cookie: x=1", False), ("/" + "a" * 400, False),
])
def test_sign_in_destination_is_only_ever_an_app_page(nxt, ok):
    assert (server._safe_next(nxt) is not None) is ok
    if ok:
        assert server._safe_next(nxt) == nxt


def test_google_sign_in_returns_to_the_page_the_visitor_came_from(monkeypatch):
    monkeypatch.setattr(server.auth, "google_configured", lambda: True)
    monkeypatch.setattr(server.auth, "new_login", lambda: {"state": "s", "nonce": "n", "verifier": "v"})
    monkeypatch.setattr(server.auth, "authorize_url", lambda login: "https://accounts.google.com/o")
    monkeypatch.setattr(server.repo, "save_oauth_state", lambda *a: None)

    class Start:
        cur = None
        query = {"next": "/strategies/16"}
        set_cookies = []
    assert server.google_start(Start()) == ("redirect", "https://accounts.google.com/o")
    assert len(Start.set_cookies) == 1 and Start.set_cookies[0].startswith("tau_next=%2Fstrategies%2F16; Path=/auth; HttpOnly")

    Start.query, Start.set_cookies = {"next": "//evil.example"}, []
    server.google_start(Start())
    assert Start.set_cookies == []  # an off-site destination is never remembered

    monkeypatch.setattr(server.repo, "pop_oauth_state", lambda cur, s: {"code_verifier": "v", "nonce": "n"})
    monkeypatch.setattr(server.auth, "exchange_code", lambda *a: {"email": "a@x.com", "sub": "s", "name": "A", "picture": None})
    monkeypatch.setattr(server.repo, "is_waitlist_approved", lambda *a: True)
    monkeypatch.setattr(server.repo, "upsert_google_user", lambda *a, **k: {"id": 7})
    monkeypatch.setattr(auth_routes, "_start_session", lambda ctx, uid: None)

    def callback(cookie):
        class Cb:
            cur = None
            query = {"code": "c", "state": "s"}
            set_cookies = []
            handler = type("H", (), {"cookies": lambda self: cookie})()
        return server.google_callback(Cb()), Cb.set_cookies
    where, cookies = callback({"tau_next": "%2Fstrategies%2F16"})
    assert where == ("redirect", "/strategies/16") and cookies[0].startswith("tau_next=; Path=/auth")
    assert callback({"tau_next": "https%3A%2F%2Fevil.example"})[0] == ("redirect", "/")
    assert callback({})[0] == ("redirect", "/")


def test_since_your_last_visit_reads_the_cookies_time_clamped_to_a_week(monkeypatch):
    # The page keeps the last visit in a cookie and sends it as ?since= (epoch seconds). Missing or
    # unreadable: the last 24 hours, marked first. Older than a week: a week. In the future: now.
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 25, 12, 0)
    monkeypatch.setattr(server.repo, "now_utc", lambda: now)
    epoch = lambda dt: str(int(dt.replace(tzinfo=timezone.utc).timestamp()))
    assert server._visit_since(None) == (now - timedelta(hours=24), True)
    assert server._visit_since("yesterday") == (now - timedelta(hours=24), True)
    assert server._visit_since(epoch(now - timedelta(hours=9))) == (now - timedelta(hours=9), False)
    assert server._visit_since(epoch(now - timedelta(days=30))) == (now - timedelta(days=7), False)
    assert server._visit_since(epoch(now + timedelta(days=1))) == (now, False)
    # The strip's block: the books' since-visit sums as read (never added up), passes, autopilot and runs.
    monkeypatch.setattr(server.repo, "activity_since", lambda cur, uid, since: {"autopilot": {"deploy": 1}, "runs": {"failed": 1}, "own_sessions": True})
    monkeypatch.setattr(server.repo, "passed_since", lambda cur, uid, since: {"n": 1, "items": [{"id": 3, "title": "A"}]})
    out = server._since_visit(None, 1, now, False, {"paper": (2.4249, 3), "demo": (-1.0, 1), "live": (0.0, 0)})
    assert out == {"at": now, "first": False, "books": {"paper": {"pnl": 2.42, "trades": 3}, "demo": {"pnl": -1.0, "trades": 1},
                                                         "live": {"pnl": 0.0, "trades": 0}},
                   "passed": {"n": 1, "items": [{"id": 3, "title": "A"}]}, "autopilot": {"deploy": 1}, "runs": {"failed": 1},
                   "own_sessions": True, "spent": None, "milestones": {"passed": [], "live_ready": []}}


def test_since_your_last_visit_says_what_it_cost_only_while_payments_are_on(monkeypatch):
    # Credits spent are real money: the strip shows them on their own row, never added to a book, and
    # with payments off nothing is billed, so there is no cost to show. Forward-gate passes and
    # live-ready strategies (from the bell) ride along as strategy ids.
    from datetime import datetime
    now = datetime(2026, 10, 25, 12, 0)
    act = {"autopilot": {}, "runs": {}, "own_sessions": True, "spent": {"since": 27.45, "week": 27.45},
           "milestones": {"passed": [232], "live_ready": [232]}}
    monkeypatch.setattr(server.repo, "activity_since", lambda cur, uid, since: act)
    monkeypatch.setattr(server.repo, "passed_since", lambda cur, uid, since: {"n": 0, "items": []})
    monkeypatch.setattr(server.billing, "configured", lambda: True)
    out = server._since_visit(None, 1, now, False, {"paper": (12.65, 36)})
    assert out["spent"] == {"since": 27.45, "week": 27.45}
    assert out["books"] == {"paper": {"pnl": 12.65, "trades": 36}}  # the books never carry the credits
    assert out["milestones"] == {"passed": [232], "live_ready": [232]}
    monkeypatch.setattr(server.billing, "configured", lambda: False)
    assert server._since_visit(None, 1, now, False, {"paper": (12.65, 36)})["spent"] is None


def _capacity_ctx():
    from types import SimpleNamespace
    return server.Ctx(SimpleNamespace(cursor=lambda: object()), {"id": 7}, (), {}, {}, SimpleNamespace())


def _active_runs(monkeypatch, n):
    monkeypatch.setattr(research_routes, "_require_billing_ready", lambda *_a: None)
    monkeypatch.setattr(server.billing, "configured", lambda: False)
    monkeypatch.setattr(server.repo, "count_runs", lambda *_a, **kw: n if kw.get("active_only") else 0)


def test_full_research_slots_say_to_cancel_one_not_to_wait(monkeypatch):
    # Sessions run until stopped by default, so "wait for one to finish" never came true.
    _active_runs(monkeypatch, server.MAX_ACTIVE_RESEARCH)
    with pytest.raises(server.ApiError) as error:
        server._require_research_capacity(_capacity_ctx())
    assert error.value.status == 429
    assert "paused ones count" in error.value.message and "cancel one from its session page" in error.value.message
    assert "finish" not in error.value.message


def test_a_free_research_slot_lets_the_session_start(monkeypatch):
    _active_runs(monkeypatch, server.MAX_ACTIVE_RESEARCH - 1)
    assert server._require_research_capacity(_capacity_ctx()) is None


def test_live_autopilot_before_autopilot_says_plainly_why_it_waits(monkeypatch):
    # "Live autopilot builds on it" was jargon: say it needs autopilot (paper) on first, and why.
    from types import SimpleNamespace
    monkeypatch.setattr(server.engine, "LIVE_TRADING_ENABLED", True)
    monkeypatch.setattr(server.repo, "get_kalshi_key", lambda *_a: {"key_id": "k"})
    monkeypatch.setattr(server.repo, "set_autopilot_live", lambda *_a: pytest.fail("must not arm"))
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: object()), {"id": 7, "autopilot": False}, (),
                     {}, {"on": True, "confirm": "LIVE AUTOPILOT"}, SimpleNamespace())
    with pytest.raises(server.ApiError) as error:
        server.autopilot_live(ctx)
    assert error.value.status == 400
    assert "only be turned on after autopilot (paper) is on" in error.value.message
    assert "proven itself on paper" in error.value.message and "builds on it" not in error.value.message


def test_a_demo_deployment_of_a_strategy_on_paper_is_marked_its_demo_copy():
    """The Deploy board and dashboard say a demo row copies its paper run when the strategy also runs
    (or is paused) on paper; a stopped paper run, or none, leaves it a plain demo deployment."""
    def dep(i, sid, mode, status="running"):
        return {"id": i, "strategy_id": sid, "title": "S", "direction": None, "market": "btc15m", "mode": mode,
                "status": status, "status_reason": None, "realized_pnl": 0, "closed_trades": 0, "wins": 0,
                "open_positions": 0, "created_at": None, "spec": {"sizing": {"stake": 5, "max_positions": 2}}, "result": {}}
    deps = [dep(1, 7, "paper"), dep(2, 7, "demo"), dep(3, 8, "paper", "stopped"), dep(4, 8, "demo"),
            dep(5, 9, "paper", "paused"), dep(6, 9, "demo"), dep(7, 10, "demo"), dep(8, 10, "live")]
    sids = server._paper_strategy_ids(deps)
    assert sids == {7, 9}
    assert [server._deployment_out(d, [], paper_sids=sids)["demo_copy"] for d in deps] == [
        False, True, False, False, False, True, False, False]
    assert server._deployment_out(deps[1], [])["demo_copy"] is False  # no paper set given: never guessed


def test_saving_auto_reload_returns_what_one_reload_charges(monkeypatch):
    # The Billing page copies the save onto the autopilot card's line, charge included, without a re-read.
    saved = []
    monkeypatch.setattr(server.repo, "get_stripe_customer", lambda cur, uid: {"default_pm_id": "pm_1"})
    monkeypatch.setattr(server.repo, "set_auto_reload",
                        lambda cur, uid, on, amount=None, threshold=None: saved.append((on, amount, threshold)))
    out = server.billing_autoreload(ctx({"on": True, "amount": 50, "threshold": 8}))
    assert out == {"ok": True, "autoreload_charge": server.billing.topup_charge_cents(saved[0][1]) / 100}
    assert out["autoreload_charge"] > 50  # the credits plus the purchase fee
    assert server.billing_autoreload(ctx({"on": False})) == {"ok": True, "autoreload_charge": None}
