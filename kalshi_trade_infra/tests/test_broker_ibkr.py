"""Offline vendor OAuth tests; keys/tokens are generated synthetic fixtures."""
import base64
import json
from urllib.parse import parse_qs, unquote_plus, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import dh, padding, rsa
import pytest
import requests

from app.adapters.brokers import broker_ibkr as broker

# RFC3526 group 14, used only as public fixture parameters (not an IBKR claim).
PRIME = int("""
FFFFFFFF FFFFFFFF C90FDAA2 2168C234 C4C6628B 80DC1CD1
29024E08 8A67CC74 020BBEA6 3B139B22 514A0879 8E3404DD
EF9519B3 CD3A431B 302B0A6D F25F1437 4FE1356D 6D51C245
E485B576 625E7EC6 F44C42E9 A637ED6B 0BFF5CB6 F406B7ED
EE386BFB 5A899FA5 AE9F2411 7C4B1FE6 49286651 ECE45B3D
C2007CB8 A163BF05 98DA4836 1C55D39A 69163FA8 FD24CF5F
83655D23 DCA3AD96 1C62F356 208552BB 9ED52907 7096966D
670C354E 4ABC9804 F1746C08 CA18217C 32905E46 2E36CE3B
E39E772C 180E8603 9B2783A2 EC07A28F B5C55DF0 6F4C52C9
DE2BCBF6 95581718 3995497C EA956AE5 15D22618 98FA0510
15728E5A 8AACAA68 FFFFFFFF FFFFFFFF
""".replace(" ", "").replace("\n", ""), 16)


@pytest.fixture(scope="module")
def keys():
    return (rsa.generate_private_key(public_exponent=65537, key_size=2048),
            rsa.generate_private_key(public_exponent=65537, key_size=2048))


@pytest.fixture
def configured(monkeypatch, tmp_path, keys):
    monkeypatch.setenv("IBKR_OAUTH_APPROVED", "1")
    monkeypatch.setenv("IBKR_OAUTH_CONSUMER_KEY", "synthetic-consumer")
    for variable, name, key in [("IBKR_OAUTH_SIGNING_KEY_PATH", "signing.pem", keys[0]),
                                ("IBKR_OAUTH_ENCRYPTION_KEY_PATH", "encryption.pem", keys[1])]:
        path = tmp_path / name
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        path.chmod(0o600)
        monkeypatch.setenv(variable, str(path))
    path = tmp_path / "dh.pem"
    path.write_bytes(dh.DHParameterNumbers(PRIME, 2).parameters().parameter_bytes(
        serialization.Encoding.PEM, serialization.ParameterFormat.PKCS3))
    monkeypatch.setenv("IBKR_OAUTH_DH_PARAMS_PATH", str(path))
    return keys


class Response:
    def __init__(self, payload, status=200):
        self.status_code = status
        self.payload = payload
        self.content = json.dumps(payload).encode()
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


def transport(monkeypatch, responses):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(broker.requests, "post", post)
    return calls


def test_configuration_requires_approval_distinct_rsa_keys_and_local_dh(configured, monkeypatch):
    assert broker.status()["configured"] is True
    monkeypatch.setenv("IBKR_OAUTH_ENCRYPTION_KEY_PATH", broker.os.environ["IBKR_OAUTH_SIGNING_KEY_PATH"])
    assert broker.status()["configured"] is False
    monkeypatch.setenv("IBKR_OAUTH_APPROVED", "0")
    assert "approved" in broker.status()["reason"]


def test_missing_material_does_not_leak_paths(configured, monkeypatch):
    path = "/private/synthetic-secret-signing-location.pem"
    monkeypatch.setenv("IBKR_OAUTH_SIGNING_KEY_PATH", path)
    status = broker.status()
    assert status["configured"] is False
    assert path not in status["reason"]


def test_rsa_header_matches_literal_documented_signature_base(configured, monkeypatch):
    signing = configured[0]
    params = {"oauth_callback": "oob", "oauth_consumer_key": "synthetic-consumer",
              "oauth_nonce": "01234567", "oauth_signature_method": "RSA-SHA256",
              "oauth_timestamp": "1700000000"}
    header = broker._signed_header(broker.BASE + "/oauth/request_token", params,
                                   "synthetic-consumer", signing)
    fields = dict(item.strip().split("=", 1) for item in header.removeprefix("OAuth ").split(","))
    signature = base64.b64decode(unquote_plus(fields["oauth_signature"].strip('"')))
    # Literal expected wire signature base, independent of the normalization
    # helper: catches extra escaping, slash handling and realm accidentally signed.
    expected = ("POST&https%3A%2F%2Fapi.ibkr.com%2Fv1%2Fapi%2Foauth%2Frequest_token&"
                "oauth_callback%3Doob%26oauth_consumer_key%3Dsynthetic-consumer%26"
                "oauth_nonce%3D01234567%26oauth_signature_method%3DRSA-SHA256%26"
                "oauth_timestamp%3D1700000000")
    signing.public_key().verify(signature, expected.encode(), padding.PKCS1v15(), hashes.SHA256())
    assert fields["realm"] == '"limited_poa"'


def test_begin_uses_request_token_then_registered_redirect_with_bound_state(configured, monkeypatch):
    response = Response({"oauth_token": "synthetic-request-token"})
    calls = transport(monkeypatch, [response])
    result = broker.begin("https://tau.example/auth/brokers/ibkr/callback", "one-use-state", "live")
    query = parse_qs(urlsplit(result["authorization_url"]).query)
    callback = urlsplit(query["redirect_uri"][0])
    assert query["oauth_token"] == ["synthetic-request-token"]
    assert parse_qs(callback.query)["state"] == ["one-use-state"]
    assert callback.path == "/auth/brokers/ibkr/callback"
    assert result["private"]["request_token"] == "synthetic-request-token"
    assert 'oauth_callback="oob"' in calls[0][1]["headers"]["Authorization"]
    assert calls[0][0] == broker.BASE + "/oauth/request_token"
    assert calls[0][1]["allow_redirects"] is False
    assert "data" not in calls[0][1] and "json" not in calls[0][1]
    assert response.closed


@pytest.mark.parametrize("query", [{"oauth_token": "wrong-token", "oauth_verifier": "verifier", "state": "pending"},
                                   {"oauth_token": "request-token", "oauth_verifier": "verifier", "state": "wrong"},
                                   {"oauth_token": "request-token", "oauth_verifier": "verifier", "state": "非ASCII"},
                                   {"oauth_token": "request-token", "oauth_verifier": "inject\r\nheader", "state": "pending"},
                                   {"denied": "request-token"}])
def test_wrong_or_injected_callback_cannot_exchange(configured, monkeypatch, query):
    calls = transport(monkeypatch, [])
    with pytest.raises(broker.Error):
        broker.exchange(query, {"request_token": "request-token", "state": "pending",
                                "consumer_key": "synthetic-consumer"}, "https://tau.example/callback", "live")
    assert calls == []


def test_live_session_known_vector_includes_java_positive_integer_padding(configured, monkeypatch):
    # Small public test group isolates the byte-encoding edge case: B^a mod257
    # is128, which must be encoded 00 80, not80. Production config requires2048bits.
    config = ("synthetic-consumer", configured[0], configured[1], 257, 2)
    monkeypatch.setattr(broker, "_config", lambda: config)
    monkeypatch.setattr(broker.secrets, "randbits", lambda bits: 7)
    monkeypatch.setattr(broker.time, "time", lambda: 1700000000)
    secret = base64.b64encode(configured[1].public_key().encrypt(b"known-secret", padding.PKCS1v15())).decode()
    calls = transport(monkeypatch, [
        Response({"oauth_token": "synthetic-access-token", "oauth_token_secret": secret}),
        Response({"diffie_hellman_response": "02",
                  "live_session_token_signature": "f7cb6a917030f9e0fab75905ecfba97f603198be",
                  "live_session_token_expiration": 1700086400000}),
    ])
    result = broker.exchange({"oauth_token": "request-token", "oauth_verifier": "verifier", "state": "pending"},
                             {"request_token": "request-token", "state": "pending",
                              "consumer_key": "synthetic-consumer"}, "https://tau.example/callback", "live")
    assert result["live_session_token"] == "eXDynk2piwzZJuq9od6kVcyUzuU="
    assert result["expires_at"] == 1700086400
    assert result["session_initialized"] is False
    assert [url for url, _ in calls] == [broker.BASE + "/oauth/access_token", broker.BASE + "/oauth/live_session_token"]
    assert not any("ssodh" in url or "orders" in url for url, _ in calls)
    info = broker.inspect(result, "live")
    assert info["verification"] == "live_session_token_verified"
    assert info["account_verified"] is False and info["expires_at"] == 1700086400
    assert info["scopes"] == ["broker_authorization"]
    assert "oauth_token" not in info and "live_session_token" not in info
    # Provider's LST request signature includes the decrypted secret prepend.
    header = calls[1][1]["headers"]["Authorization"]
    fields = dict(item.strip().split("=", 1) for item in header.removeprefix("OAuth ").split(","))
    signature = base64.b64decode(unquote_plus(fields["oauth_signature"].strip('"')))
    params = {key: value.strip('"') for key, value in fields.items() if key not in {"realm", "oauth_signature"}}
    assert params["diffie_hellman_challenge"] == "80"
    assert params["oauth_token"] == "synthetic-access-token"
    # The nonce is fixed only for this independently verified signature vector.
    # Preserve its actual emitted value and assert the rest as a literal wire base.
    expected = ("6b6e6f776e2d736563726574POST&https%3A%2F%2Fapi.ibkr.com%2Fv1%2Fapi%2Foauth%2Flive_session_token&"
                "diffie_hellman_challenge%3D80%26oauth_consumer_key%3Dsynthetic-consumer%26"
                "oauth_nonce%3D" + params["oauth_nonce"] + "%26oauth_signature_method%3DRSA-SHA256%26"
                "oauth_timestamp%3D1700000000%26oauth_token%3Dsynthetic-access-token")
    configured[0].public_key().verify(signature, expected.encode(), padding.PKCS1v15(), hashes.SHA256())


@pytest.mark.parametrize("server_public,proof", [("02", "0" * 40), ("01", "f7cb6a917030f9e0fab75905ecfba97f603198be"),
                                                ("101", "f7cb6a917030f9e0fab75905ecfba97f603198be")])
def test_unverified_lst_is_never_accepted(configured, monkeypatch, server_public, proof):
    config = ("synthetic-consumer", configured[0], configured[1], 257, 2)
    monkeypatch.setattr(broker.secrets, "randbits", lambda bits: 7)
    monkeypatch.setattr(broker.time, "time", lambda: 1700000000)
    secret = base64.b64encode(configured[1].public_key().encrypt(b"known-secret", padding.PKCS1v15())).decode()
    transport(monkeypatch, [Response({"diffie_hellman_response": server_public,
                                     "live_session_token_signature": proof,
                                     "live_session_token_expiration": 1700086400000})])
    with pytest.raises(broker.Error, match="verification failed"):
        broker._derive_session({"oauth_token": "synthetic-access", "oauth_token_secret": secret}, config)


def test_network_failures_redirects_and_raw_errors_are_private(configured, monkeypatch):
    for response in [requests.Timeout("sensitive-url"), Response({"secret": "never-log-this"}, 302),
                     Response({"secret": "never-log-this"}, 401)]:
        transport(monkeypatch, [response])
        with pytest.raises(broker.Error) as error:
            broker.begin("https://tau.example/callback", "state", "live")
        assert "never-log-this" not in str(error.value)
        assert "sensitive-url" not in str(error.value)


def test_paper_environment_fails_without_network(configured, monkeypatch):
    calls = transport(monkeypatch, [])
    with pytest.raises(broker.Error):
        broker.begin("https://tau.example/callback", "state", "paper")
    assert calls == []
