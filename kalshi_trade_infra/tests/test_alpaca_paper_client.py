"""Synthetic HTTP contracts only: no Alpaca credentials or network calls."""
import json
from decimal import Decimal

import pytest
import requests

from app import alpaca_paper_client as alpaca

TOKEN = "synthetic-private-bearer-only"
CLIENT_ID = "tau-paper-" + "a" * 32
ORDER_ID = "12345678-1234-1234-1234-123456789abc"


def credentials(**changes):
    return {"access_token": TOKEN, "token_type": "Bearer", "scope": "data trading", **changes}


def order(**changes):
    return {
        "symbol": "SPY", "qty": "2", "side": "buy", "type": "limit",
        "limit_price": "10.23", "time_in_force": "day", "extended_hours": False,
        "client_order_id": CLIENT_ID, **changes,
    }


def acknowledgement(**changes):
    return {"id": ORDER_ID, **order(), "status": "accepted", **changes}


class Response:
    def __init__(self, data=None, status=200, *, raw=None, headers=None, stream_error=None):
        self.status_code = status
        self.raw = json.dumps(data).encode() if raw is None else raw
        self.headers = headers or {}
        self.stream_error = stream_error
        self.closed = False

    def iter_content(self, chunk_size):
        if self.stream_error:
            raise self.stream_error
        for index in range(0, len(self.raw), chunk_size):
            yield self.raw[index:index + chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert self.responses, "Unexpected extra HTTP attempt"
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def test_paper_host_bearer_and_tls_are_pinned_despite_environment_overrides(monkeypatch):
    for name in ("APCA_API_BASE_URL", "ALPACA_BASE_URL", "ALPACA_TRADING_ENDPOINT", "ALPACA_DATA_ENDPOINT"):
        monkeypatch.setenv(name, "https://api.alpaca.markets")
    monkeypatch.setenv("APCA_API_KEY_ID", "synthetic-shared-data-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "synthetic-shared-data-secret")
    response = Response({"id": "synthetic-account"})
    session = Session(response)
    with alpaca.Client(credentials(endpoint="https://untrusted.example"), session=session) as client:
        assert client.account() == {"id": "synthetic-account"}
    method, url, request = session.calls[0]
    assert method == "GET" and url == "https://paper-api.alpaca.markets/v2/account"
    assert request["headers"] == {"Authorization": "Bearer " + TOKEN, "Accept": "application/json"}
    assert request["allow_redirects"] is False and request["stream"] is True and request["verify"] is True
    assert request["timeout"] == (5, 15)
    assert "synthetic-shared" not in repr(session.calls)
    assert response.closed and not session.closed  # Caller owns an injected session.


def test_real_session_disables_retries_netrc_proxies_and_other_authorization():
    session = requests.Session()
    session.headers.update({"APCA-API-KEY-ID": "synthetic-key", "APCA-API-SECRET-KEY": "synthetic-secret"})
    session.params = {"apiKey": "synthetic-query-key"}
    session.auth = ("synthetic-user", "synthetic-password")
    session.proxies = {"https": "https://untrusted.example"}
    session.cookies.set("synthetic", "cookie")
    client = alpaca.Client(credentials(), session=session)
    assert session.trust_env is False and session.auth is None
    assert not session.headers and not session.params and not session.proxies and not session.cookies
    assert session.get_adapter(alpaca.PAPER_BASE_URL).max_retries.total == 0
    client.close()
    session.close()


@pytest.mark.parametrize("environment", ["live", "https://api.alpaca.markets", "", None, [], {}])
def test_live_or_arbitrary_environment_is_refused_without_http(environment):
    session = Session()
    with pytest.raises(alpaca.Error) as exc:
        alpaca.Client(credentials(), environment=environment, session=session)
    assert exc.value.status == 400 and not exc.value.ambiguous and not exc.value.rejected
    assert not session.calls


@pytest.mark.parametrize("grant", [
    None, [], {}, {"APCA_API_KEY_ID": "shared-key", "APCA_API_SECRET_KEY": "shared-secret"},
    credentials(access_token=""), credentials(access_token=TOKEN + "\r\ninjected"),
    credentials(access_token=TOKEN + " space"), credentials(access_token=TOKEN + "é"),
    credentials(access_token=True), credentials(access_token="x" * 16385),
    credentials(token_type="apikey"), credentials(token_type=None), credentials(scope=[]),
    credentials(scope="trading\n"), credentials(scope="x" * 201),
    credentials(expires_at=0), credentials(expires_at=True), credentials(expires_at="future"),
    credentials(expires_at=float("nan")), credentials(expires_at=float("inf")),
])
def test_invalid_credentials_and_expiry_are_rejected_without_leaking(grant):
    session = Session()
    with pytest.raises(alpaca.Error) as exc:
        alpaca.Client(grant, session=session)
    assert exc.value.status == 401
    assert TOKEN not in str(exc.value) and "shared-secret" not in str(exc.value)
    assert not session.calls


def test_expiry_is_rechecked_before_each_request(monkeypatch):
    clock = [1000]
    monkeypatch.setattr(alpaca.time, "time", lambda: clock[0])
    session = Session(Response({"id": "synthetic-account"}))
    client = alpaca.Client(credentials(expires_at=1001), session=session)
    client.account()
    clock[0] = 1001
    with pytest.raises(alpaca.Error) as exc:
        client.account()
    assert exc.value.status == 401 and len(session.calls) == 1


def test_read_only_scope_can_inspect_but_never_mutate():
    session = Session(Response({"id": "synthetic-account"}), Response([]))
    with alpaca.Client(credentials(scope="data"), session=session) as client:
        client.account()
        assert client.positions() == []
        for mutate in (lambda: client.submit_order(order()), lambda: client.cancel_order(ORDER_ID)):
            with pytest.raises(alpaca.Error) as exc:
                mutate()
            assert exc.value.status == 403 and not exc.value.rejected and not exc.value.ambiguous
    assert len(session.calls) == 2


def test_read_routes_and_client_id_lookup_have_fixed_paths():
    session = Session(
        Response([]), Response([{"id": ORDER_ID}]), Response({"symbol": "BRK.B"}),
        Response(acknowledgement()), Response({"private": "not retained"}, 404),
    )
    with alpaca.Client(credentials(), session=session) as client:
        assert client.positions() == []
        assert client.orders(status="all", limit=1) == [{"id": ORDER_ID}]
        assert client.asset(" brk.b ") == {"symbol": "BRK.B"}
        assert client.get_order(CLIENT_ID)["id"] == ORDER_ID
        assert client.get_order(CLIENT_ID) is None
    assert [call[1] for call in session.calls] == [
        alpaca.PAPER_BASE_URL + suffix for suffix in (
            "/positions", "/orders", "/assets/BRK.B", "/orders:by_client_order_id", "/orders:by_client_order_id")
    ]
    assert session.calls[1][2]["params"] == {"status": "all", "limit": 1, "direction": "desc", "nested": False}
    assert session.calls[3][2]["params"] == {"client_order_id": CLIENT_ID}
    assert all(call[0] == "GET" for call in session.calls)


@pytest.mark.parametrize("identifier", ["../account", "SPY?redirect=live", "SPY/", "SPY%2f..", "BTC/USD", "", None, [], "A" * 16])
def test_asset_path_identifiers_are_validated_before_http(identifier):
    session = Session()
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error):
            client.asset(identifier)
    assert not session.calls


@pytest.mark.parametrize("identifier", ["../account", CLIENT_ID + "?x=y", "tau-paper-" + "A" * 32, "", None, []])
def test_client_order_identifiers_are_validated_before_http(identifier):
    session = Session()
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error):
            client.get_order(identifier)
    assert not session.calls


@pytest.mark.parametrize("identifier", ["../account", ORDER_ID + "?x=y", CLIENT_ID, "", None, []])
def test_cancel_identifiers_are_validated_before_http(identifier):
    session = Session()
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error):
            client.cancel_order(identifier)
    assert not session.calls


@pytest.mark.parametrize("status,limit", [("anything", 1), ("open", 0), ("open", 501), ("open", True), ("open", "1"), ([], 1)])
def test_order_query_is_bounded(status, limit):
    session = Session()
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error):
            client.orders(status=status, limit=limit)
    assert not session.calls


def test_normalize_order_is_exact_and_does_not_round_money():
    raw = order(symbol=" spy ", qty="0002.000", limit_price=Decimal("0010.23000"))
    result = alpaca.normalize_order(raw)
    assert result == order()
    assert raw["symbol"] == " spy " and raw["qty"] == "0002.000"
    assert alpaca.normalize_order(order(qty=2.0, limit_price=0.0001))["limit_price"] == "0.0001"
    assert alpaca.normalize_order(order(limit_price="0.9999"))["limit_price"] == "0.9999"
    assert alpaca.normalize_order(order(limit_price="1.00"))["limit_price"] == "1"


@pytest.mark.parametrize("body", [
    None, [], {}, {key: value for key, value in order().items() if key != "extended_hours"},
    order(type="market"), order(time_in_force="gtc"), order(extended_hours=True), order(extended_hours=0),
    order(side="short"), order(side=[]), order(symbol="BTC/USD"),
    order(qty="0"), order(qty="-1"), order(qty="1.5"), order(qty=True), order(qty="Infinity"),
    order(qty=float("nan")), order(qty="1000000001"), order(qty="1e1"),
    order(limit_price="0"), order(limit_price="-1"), order(limit_price=True), order(limit_price="NaN"),
    order(limit_price=float("inf")), order(limit_price="1.001"), order(limit_price="0.12345"),
    order(limit_price="1.00000000000000000000000000000000000001"),
    order(client_order_id="externally-generated-id"),
    order(notional="100"), order(order_class="simple"), order(legs=[]),
])
def test_unsupported_order_shapes_and_precision_are_refused_before_post(body):
    session = Session()
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.submit_order(body)
    assert not exc.value.ambiguous and not exc.value.rejected
    assert not session.calls


def test_submit_is_one_canonical_post_and_cancel_is_one_delete():
    responses = [Response(acknowledgement()), Response(status=204)]
    session = Session(*responses)
    with alpaca.Client(credentials(), session=session) as client:
        result = client.submit_order(order(symbol="spy", qty=2, limit_price="10.2300"))
        assert result["id"] == ORDER_ID
        assert client.cancel_order(ORDER_ID) is None
    assert len(session.calls) == 2
    assert session.calls[0][0:2] == ("POST", alpaca.PAPER_BASE_URL + "/orders")
    assert session.calls[0][2]["json"] == order()
    assert session.calls[1][0:2] == ("DELETE", alpaca.PAPER_BASE_URL + "/orders/" + ORDER_ID)
    assert all(response.closed for response in responses)


@pytest.mark.parametrize("status", [302, 307, 408, 409, 500, 502, 503, 504])
def test_ambiguous_mutation_responses_are_not_retried_or_leaked(status):
    response = Response({"error": TOKEN + " private provider diagnostic"}, status)
    session = Session(response)
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.submit_order(order())
    assert exc.value.ambiguous and not exc.value.rejected
    assert TOKEN not in str(exc.value) and "diagnostic" not in str(exc.value)
    assert len(session.calls) == 1 and response.closed
    assert session.calls[0][2]["allow_redirects"] is False


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429])
def test_only_actual_definitive_post_rejections_have_rejected_marker(status):
    session = Session(Response({"private_error": TOKEN}, status))
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.submit_order(order())
    assert exc.value.rejected and not exc.value.ambiguous
    assert len(session.calls) == 1 and TOKEN not in str(exc.value)


@pytest.mark.parametrize("failure", [requests.Timeout(TOKEN), requests.ConnectionError(TOKEN)])
@pytest.mark.parametrize("mutation", ["submit", "cancel"])
def test_mutating_transport_failures_require_reconciliation_without_resend(failure, mutation):
    session = Session(failure)
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.submit_order(order()) if mutation == "submit" else client.cancel_order(ORDER_ID)
    assert exc.value.ambiguous and not exc.value.rejected
    assert exc.value.status == 502 and len(session.calls) == 1
    assert TOKEN not in str(exc.value) and exc.value.__cause__ is None


def test_transport_failure_after_post_response_is_also_ambiguous():
    response = Response(stream_error=requests.ConnectionError(TOKEN))
    session = Session(response)
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.submit_order(order())
    assert exc.value.ambiguous and not exc.value.rejected and response.closed
    assert len(session.calls) == 1 and TOKEN not in str(exc.value)


@pytest.mark.parametrize("response", [
    Response([]), Response({}), Response({"id": ORDER_ID}),
    Response(acknowledgement(client_order_id="tau-paper-" + "b" * 32)),
    Response(acknowledgement(id="not-an-order-id")),
    Response(raw=("invalid JSON " + TOKEN).encode()),
    Response(raw=b'{"id":"one","id":"two"}'),
    Response({"secret": "a" * 16385}),
    Response({"nested": [[[[[[[[[[["too deep"]]]]]]]]]]]}),
    Response({"number": float("nan")}),
    Response(acknowledgement(), headers={"Content-Length": str(alpaca.MAX_RESPONSE_BYTES + 1)}),
    Response(acknowledgement(), headers={"Content-Length": "invalid"}),
    Response(raw=b" " * (alpaca.MAX_RESPONSE_BYTES + 1)),
])
def test_malformed_or_unbounded_success_is_ambiguous_and_never_repeated(response):
    session = Session(response)
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.submit_order(order())
    assert exc.value.ambiguous and not exc.value.rejected and exc.value.status == 502
    assert len(session.calls) == 1 and response.closed and TOKEN not in str(exc.value)


@pytest.mark.parametrize("response", [Response([], 200), Response({}, 200), Response({}, 302), Response({}, 500)])
def test_read_failures_have_no_mutation_flags(response):
    session = Session(response)
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.account()
    assert not exc.value.ambiguous and not exc.value.rejected and response.closed


def test_order_lookup_does_not_accept_another_client_id():
    session = Session(Response(acknowledgement(client_order_id="tau-paper-" + "b" * 32)))
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.get_order(CLIENT_ID)
    assert exc.value.status == 502 and not exc.value.ambiguous


@pytest.mark.parametrize("data", [[{"id": ORDER_ID}] * 2, [1], [None], [{}]])
def test_collection_shape_and_requested_size_are_enforced(data):
    session = Session(Response(data))
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error) as exc:
            client.orders(limit=1)
    assert not exc.value.ambiguous and exc.value.status == 502


def test_context_closes_owned_session_and_closed_client_cannot_send(monkeypatch):
    session = Session(Response({"id": "synthetic-account"}))
    monkeypatch.setattr(alpaca.requests, "Session", lambda: session)
    with alpaca.Client(credentials()) as client:
        client.account()
    assert session.closed
    with pytest.raises(alpaca.Error) as exc:
        client.submit_order(order())
    assert len(session.calls) == 1 and exc.value.status == 503


def test_no_provider_or_token_output(capsys):
    session = Session(Response({"private_error": TOKEN}, 500))
    with alpaca.Client(credentials(), session=session) as client:
        with pytest.raises(alpaca.Error):
            client.submit_order(order())
    assert capsys.readouterr() == ("", "")
