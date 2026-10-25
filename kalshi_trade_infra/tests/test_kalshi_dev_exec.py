"""Foundation tests for the authenticated Kalshi DEMO execution client.

No network: requests.post is monkeypatched. Covers (1) a demo order POSTs to the
demo base signed with the dev key, (2) the client REFUSES a non-demo/production
host, and (3) the dev-key round-trips through the repository layer.
"""
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import kalshi_dev_exec as dx
from app import repository as repo

DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"
PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _creds():
    """A real RSA key so kalshi_auth_headers can actually sign."""
    return ("DEV-KEY-ID", rsa.generate_private_key(public_exponent=65537, key_size=2048))


class _FakeResp:
    status_code = 200

    def json(self):
        # Minimal v2 create-order response: one contract filled at 50c.
        return {"order_id": "demo-order-1", "fill_count": "1.00", "average_fill_price": "0.5000"}


def test_demo_order_posts_to_demo_host_with_dev_key(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return _FakeResp()

    monkeypatch.setattr(dx.requests, "post", fake_post)

    out = dx.demo_place_limit_order("BTC-T", "buy", "yes", 1, 0.50, credentials=_creds())

    assert captured["url"].startswith(DEMO_BASE)
    assert captured["url"].endswith("/portfolio/events/orders")
    # Signed as the DEV key, not the house key.
    assert captured["headers"]["KALSHI-ACCESS-KEY"] == "DEV-KEY-ID"
    assert captured["headers"]["KALSHI-ACCESS-SIGNATURE"]
    assert captured["body"]["side"] == "bid"  # buy YES -> bid
    assert out["resp"]["order_id"] == "demo-order-1"


def test_refuses_production_host(monkeypatch):
    # If the guard ever failed, this would catch an attempted real-exchange POST.
    def boom(*a, **k):
        raise AssertionError("must not reach the network for a non-demo host")

    monkeypatch.setattr(dx.requests, "post", boom)

    with pytest.raises(dx.DemoHostError):
        dx.demo_place_limit_order("BTC-T", "buy", "yes", 1, 0.50, credentials=_creds(), base_url=PROD_BASE)
    with pytest.raises(dx.DemoHostError):
        dx.demo_cancel_order("x", credentials=_creds(), base_url=PROD_BASE)
    with pytest.raises(dx.DemoHostError):
        dx.demo_fills(credentials=_creds(), base_url=PROD_BASE)
    # A plausible-but-not-demo host is refused too.
    with pytest.raises(dx.DemoHostError):
        dx.demo_place_limit_order("BTC-T", "buy", "yes", 1, 0.50, credentials=_creds(),
                                  base_url="https://evil.example.com/trade-api/v2")


def test_requires_dev_key_no_house_fallback(monkeypatch):
    monkeypatch.setattr(dx.requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no net")))
    with pytest.raises(dx.DemoHostError):
        dx.demo_place_limit_order("BTC-T", "buy", "yes", 1, 0.50, credentials=None)


class _DevKeyCursor:
    """Tiny fake cursor for the app_kalshi_dev_keys table, in the conftest style."""

    def __init__(self):
        self.rows = {}  # user_id -> row dict
        self._last = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self._last = None
        if s.startswith("INSERT INTO app_kalshi_dev_keys"):
            user_id, key_id, enc, created = params
            self.rows[user_id] = {"key_id": key_id, "private_key_enc": enc, "created_at": created}
        elif s.startswith("SELECT key_id, private_key_enc, created_at FROM app_kalshi_dev_keys"):
            row = self.rows.get(params[0])
            self._last = [row] if row else []
        elif s.startswith("DELETE FROM app_kalshi_dev_keys"):
            self.rows.pop(params[0], None)
        else:
            raise NotImplementedError(s[:80])

    def fetchone(self):
        return self._last[0] if self._last else None


def test_dev_key_repository_round_trip():
    cur = _DevKeyCursor()
    assert repo.get_kalshi_dev_key(cur, 7) is None
    repo.set_kalshi_dev_key(cur, 7, "DEV-7", b"ciphertext")
    row = repo.get_kalshi_dev_key(cur, 7)
    assert row["key_id"] == "DEV-7" and row["private_key_enc"] == b"ciphertext"
    repo.delete_kalshi_dev_key(cur, 7)
    assert repo.get_kalshi_dev_key(cur, 7) is None


# -- engine demo mode: execution routes to the DEMO kernel, never the live one ----------
from datetime import datetime, timezone  # noqa: E402

from app import engine  # noqa: E402
from app.markets import Contract  # noqa: E402


class _Report:
    fill_qty_contracts = 1
    fill_price_dollars = 0.41
    fee_dollars = 0.01
    external_order_id = "demo-order-1"


class _Kernel:
    def __init__(self, name):
        self.name = name
        self.intents = []

    def execute(self, intent):
        self.intents.append(intent)
        return _Report()


class _LossGuardCur:
    """Just enough for loss_guard's SELECT SUM(pnl)."""

    def execute(self, sql, params=()):
        pass

    def fetchone(self):
        return {"p": 0.0}


class _Conn:
    def cursor(self):
        return _LossGuardCur()


class _Entry:
    def __init__(self, ticker):
        self.side = "yes"
        self.price = 0.41
        close = datetime.now(timezone.utc)
        self.snapshot = type("Snap", (), {"contract": Contract(ticker, 98.0, close)})()


def _demo_dep():
    return {"id": 1, "user_id": 1, "mode": "demo", "market": "btc15m", "result": {},
            "spec": {"side": "yes", "sizing": {"stake": 10.0, "max_positions": 3}}}


def test_demo_decide_executes_via_demo_kernel_not_live(monkeypatch):
    from tests.conftest import patch_intent_passthrough
    patch_intent_passthrough(monkeypatch)  # P0-1 intent log transparent for this routing test
    inserted = {}
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [])
    monkeypatch.setattr(engine.specmod, "entries", lambda spec, snaps: [_Entry("BTC-DEMO")])
    monkeypatch.setattr(engine.specmod, "contracts_for", lambda stake, price: 1)
    monkeypatch.setattr(engine.repo, "insert_position",
                        lambda cur, dep_id, uid, mode, *a, **k: inserted.update(mode=mode) or 1)
    monkeypatch.setattr(engine.repo, "user_risk_config",
                        lambda cur, uid: {"drawdown_limit_pct": 25.0, "max_open_positions": 20, "max_open_notional": 1000.0})
    monkeypatch.setattr(engine.repo, "user_open_exposure", lambda cur, uid, mode=None: {"n": 0, "notional": 0.0})

    demo_k, live_k = _Kernel("demo"), _Kernel("live")
    sources = engine.Sources(demo_kernel=lambda uid: demo_k,
                             live_kernel=lambda uid: live_k)  # must never be called for demo
    out = engine.decide(_Conn(), _demo_dep(), [], {}, sources)

    assert out["entries"] == 1
    assert inserted["mode"] == "demo"                 # position booked as demo, not live
    assert len(demo_k.intents) == 1 and demo_k.intents[0].action == "buy"
    assert live_k.intents == []                       # the live kernel was never touched


def test_demo_decide_pauses_without_dev_key(monkeypatch):
    paused = {}
    monkeypatch.setattr(engine.repo, "open_positions", lambda cur, dep_id: [])
    monkeypatch.setattr(engine.repo, "set_deployment_status",
                        lambda cur, uid, dep_id, status, reason: paused.update(status=status, reason=reason) or True)
    boom = _Kernel("live")

    # No dev key on file -> demo_kernel(uid) returns None -> deployment is paused, nothing executes.
    sources = engine.Sources(demo_kernel=lambda uid: None, live_kernel=lambda uid: boom)
    out = engine.decide(_Conn(), _demo_dep(), [], {}, sources)

    assert out == {"paused": "demo disabled"}
    assert paused["status"] == "paused" and "demo" in paused["reason"].lower()
    assert boom.intents == []
