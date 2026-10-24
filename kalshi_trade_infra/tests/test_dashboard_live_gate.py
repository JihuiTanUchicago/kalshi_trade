"""The live-trading gate in front of every real-money dashboard control.

It used to fall back to a password committed in this repo whenever the env var
was unset (and it was unset in production), compare with ==, and accept a
cookie whose value was the literal "ok". These pin the replacement: unset means
locked, and the cookie is only valid if derived from the real password.
"""
from urllib.parse import urlparse

import data_pipeline.dashboard_server as ds


def handler(cookie=None, command="POST"):
    h = object.__new__(ds.Handler)
    h.headers = {"Cookie": cookie} if cookie else {}
    h.command = command
    return h


def test_no_password_configured_locks_everything(monkeypatch):
    monkeypatch.setattr(ds, "LIVE_TRADING_PASSWORD", "")
    monkeypatch.setattr(ds, "MONITOR_TOKEN", None)
    assert not handler()._live_authorized(urlparse("/live_settings"))
    assert not handler()._live_authorized(urlparse("/live_settings?live_password="))
    assert not handler(cookie="live_gate=ok")._live_authorized(urlparse("/live_settings"))
    assert not ds.live_password_ok("")


def test_the_old_committed_default_is_gone(monkeypatch):
    monkeypatch.setattr(ds, "MONITOR_TOKEN", None)
    monkeypatch.delenv("LIVE_TRADING_PASSWORD", raising=False)
    import importlib

    fresh = importlib.reload(ds)
    try:
        assert fresh.LIVE_TRADING_PASSWORD == ""
        assert not fresh.live_password_ok("iwanttoberich")
    finally:
        importlib.reload(ds)


def test_correct_query_password_unlocks(monkeypatch):
    monkeypatch.setattr(ds, "LIVE_TRADING_PASSWORD", "s3cret-pass")
    assert handler()._live_authorized(urlparse("/live_settings?live_password=s3cret-pass"))
    assert not handler()._live_authorized(urlparse("/live_settings?live_password=wrong"))


def test_static_ok_cookie_no_longer_unlocks(monkeypatch):
    monkeypatch.setattr(ds, "LIVE_TRADING_PASSWORD", "s3cret-pass")
    monkeypatch.setattr(ds, "MONITOR_TOKEN", None)
    assert not handler(cookie="live_gate=ok")._live_authorized(urlparse("/live_settings"))


def test_derived_cookie_unlocks_and_dies_with_a_password_change(monkeypatch):
    monkeypatch.setattr(ds, "LIVE_TRADING_PASSWORD", "s3cret-pass")
    token = ds.live_cookie_token("s3cret-pass")
    assert handler(cookie="live_gate=" + token)._live_authorized(urlparse("/live_settings"))
    monkeypatch.setattr(ds, "LIVE_TRADING_PASSWORD", "rotated-pass")
    assert not handler(cookie="live_gate=" + token)._live_authorized(urlparse("/live_settings"))


class _Capture:
    def __init__(self):
        self.status = None
        self.headers = []
        self.body = b""


def _unlock(monkeypatch, query):
    h = handler(command="GET")
    cap = _Capture()
    h.path = "/live_unlock?" + query
    h.send_response = lambda code: setattr(cap, "status", code)
    h.send_header = lambda k, v: cap.headers.append((k, v))
    h.end_headers = lambda: None
    h._send = lambda body, code=200, extra_headers=None: setattr(cap, "status", code)
    monkeypatch.setattr(ds.Handler, "_authorized", lambda self: True)
    h.do_GET()
    return cap


def test_unlock_refuses_when_no_password_is_configured(monkeypatch):
    monkeypatch.setattr(ds, "LIVE_TRADING_PASSWORD", "")
    assert _unlock(monkeypatch, "password=").status == 403
    assert _unlock(monkeypatch, "password=iwanttoberich").status == 403


def test_unlock_sets_a_derived_httponly_cookie(monkeypatch):
    monkeypatch.setattr(ds, "LIVE_TRADING_PASSWORD", "s3cret-pass")
    cap = _unlock(monkeypatch, "password=s3cret-pass")
    assert cap.status == 302
    cookie = dict(cap.headers)["Set-Cookie"]
    assert cookie.startswith("live_gate=" + ds.live_cookie_token("s3cret-pass") + ";")
    assert "HttpOnly" in cookie
    assert _unlock(monkeypatch, "password=wrong").status == 403
