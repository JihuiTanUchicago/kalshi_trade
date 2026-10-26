"""Explicit public-data routing preserves credential and TLS isolation."""
from urllib.parse import urlsplit

import pytest
import requests

from app.kalshi_perps_data import BASE_URLS, Config, KalshiPerpsDataClient
from app.adapters.data.market_data_common import MarketDataError
from tests.test_kalshi_perps_data import Response, Session


@pytest.mark.parametrize("proxy", ["http://127.0.0.1:7890", "https://proxy.example.invalid:8443/",
                                  "http://[::1]:3128"])
def test_explicit_proxy_is_configuration_not_a_provider_host_override(proxy):
    config = Config.from_env({"TAU_KALSHI_PERPS_ENABLED": "1", "TAU_KALSHI_PERPS_PROXY_URL": proxy})
    session = Session(Response({"markets": []}))
    api = KalshiPerpsDataClient(config, session=session)
    assert api.discover_bitcoin() == []
    url, options = session.calls[0]
    assert url == BASE_URLS["production"] + "/margin/markets"
    assert options["proxies"] == {"https": proxy}
    assert options["auth"] == () and options["cookies"] == {} and options["allow_redirects"] is False
    assert session.trust_env is False


@pytest.mark.parametrize("proxy", [
    "http://private:secret@proxy.example.invalid", "http://private@proxy.example.invalid",
    "socks5://proxy.example.invalid:1080", "file:///private/config", "http://",
    "http://proxy.example.invalid/path", "http://proxy.example.invalid?token=private",
    "http://proxy.example.invalid#private", "http://proxy.example.invalid:0",
    "http://proxy.example.invalid:65536", "http://proxy.example.invalid:bad",
    "http://proxy.example.invalid\nprivate", "http://[broken",
])
def test_unsafe_proxy_configuration_is_rejected_without_echoing_it(proxy):
    with pytest.raises(MarketDataError) as error:
        Config(True, proxy_url=proxy)
    assert error.value.code == "invalid_configuration"
    assert proxy not in str(error.value)
    assert "private" not in str(error.value) and "secret" not in str(error.value)


def test_ambient_proxies_are_not_enabled_and_default_off_still_makes_no_request(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://private:secret@proxy.example.invalid")
    config = Config.from_env({})
    session = Session()
    api = KalshiPerpsDataClient(config, session=session)
    with pytest.raises(MarketDataError) as error:
        api.discover_bitcoin()
    assert error.value.code == "disabled" and session.calls == [] and config.proxy_url is None


def test_real_request_preparation_keeps_netrc_auth_headers_cookies_and_params_out(monkeypatch):
    session = requests.Session()
    proxy = "http://127.0.0.1:7890"
    api = KalshiPerpsDataClient(Config(True, proxy_url=proxy), session=session)
    # Also clear pollution added after construction, immediately before sending.
    session.auth = ("private", "secret")
    session.headers["Authorization"] = "private"
    session.cookies["session"] = "private"
    session.params["api_key"] = "private"
    session.proxies["https"] = "http://private:secret@ambient.example.invalid"
    session.verify = False
    session.cert = "/private/identity.pem"
    monkeypatch.setenv("HTTPS_PROXY", "http://private:secret@ambient.example.invalid")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/private/unverified.pem")
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", lambda *_a, **_k: pytest.fail("netrc read"))
    captured = []

    def send(prepared, **options):
        captured.append((prepared, options))
        return Response({"markets": []})

    monkeypatch.setattr(session, "send", send)
    assert api.discover_bitcoin() == []
    prepared, options = captured[0]
    assert urlsplit(prepared.url).hostname == "external-api.kalshi.com"
    assert "private" not in prepared.url and not prepared.body
    assert dict(prepared.headers) == {"Accept": "application/json"}
    assert options["verify"] is True and options["cert"] is None
    assert options["proxies"] == {"https": proxy} and options["allow_redirects"] is False


@pytest.mark.parametrize("failure,category", [
    (requests.ConnectTimeout, "connection timeout"), (requests.ReadTimeout, "read timeout"),
    (requests.exceptions.SSLError, "TLS verification failure"),
    (requests.exceptions.ProxyError, "proxy connection failure"),
    (requests.ConnectionError, "network connection failure"),
])
@pytest.mark.parametrize("proxy", [None, "http://127.0.0.1:7890"])
def test_final_transport_error_is_actionable_bounded_and_sanitized(failure, category, proxy):
    session = Session(*(failure("private request URL and response") for _ in range(3)))
    delays = []
    api = KalshiPerpsDataClient(Config(True, proxy_url=proxy), session=session, sleep=delays.append)
    with pytest.raises(MarketDataError) as error:
        api.discover_bitcoin()
    assert error.value.code == "provider_unavailable" and category in str(error.value)
    assert "private" not in str(error.value) and "127.0.0.1" not in str(error.value)
    assert ("TAU_KALSHI_PERPS_PROXY_URL" in str(error.value)) == (proxy is None)
    assert len(session.calls) == 3 and len(delays) == 2
