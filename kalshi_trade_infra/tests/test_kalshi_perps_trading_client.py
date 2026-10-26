"""Offline native transport tests: synthetic JSON and ephemeral RSA keys only."""
import base64
import copy
import json
from decimal import Decimal

import pytest
import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.adapters.kalshi_perps import kalshi_perps_trading_client as trading

NOW = 1792719180.125
TICKER = "SYNTHBTC"
CID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("This test must never use a real network transport")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


def market_row(**changes):
    return {"ticker": TICKER, "title": "Bitcoin", "asset_class": "crypto",
            "status": "active", "contract_size": "1.000000", "underlying_multiplier": "0.0001",
            "tick_size": "0.0001", "fractional_trading_enabled": False, "schedule": None,
            "exchange_index": 1, "market_version": 1, "funding_deadband": "0.0001",
            "funding_cap": "0.02", "funding_limit_unit": "percentage",
            "funding_invalid_premium_handling": "dampen", **changes}


def order_body(**changes):
    return {"client_order_id": CID, "ticker": TICKER, "side": "bid", "count": "1.00",
            "price": "7.1000", "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross", "post_only": False,
            "cancel_order_on_pause": True, "reduce_only": False, "subaccount": 0,
            "market_version": 1, **changes}


def acknowledgement(**changes):
    return {"order_id": "native-order-1", "client_order_id": CID, "fill_count": "1.00",
            "remaining_count": "0.00", "average_fill_price": "7.1000", "average_fee_paid": "0.00071", **changes}


def order_row(**changes):
    return {"order_id": "native-order-1", "client_order_id": CID, "ticker": TICKER,
            "side": "bid", "price": "7.1000", "fill_count": "1.00", "remaining_count": "0.00", **changes}


def fill_row(**changes):
    return {"fill_id": "native-fill-1", "order_id": "native-order-1", "ticker": TICKER,
            "side": "bid", "price": "7.1000", "count": "1.00", "fees": "0.00071",
            "realized_pnl": "-0.00071", "created_time": "2026-10-23T01:33:00Z", **changes}


def balance_payload(**changes):
    row = {"subaccount": 0, "position_value": "0.0000", "account_equity": "1000.0000",
           "maintenance_margin": "0.0000", "initial_margin": "0.0000",
           "resting_orders_margin": "0.0000", "available_balance": "1000.0000", **changes}
    return {"subaccount_balances": [row], "settled_funds": "1000.0000"}


class Response:
    def __init__(self, payload=None, status=200, *, raw=None, chunks=None):
        self.status_code = status
        self.raw = json.dumps(payload).encode() if raw is None else raw
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size=65536):
        if self.chunks is not None:
            yield from self.chunks
        else:
            for n in range(0, len(self.raw), chunk_size):
                yield self.raw[n:n + chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


def client(rsa_key, *responses, environment="production", proxy_url=None, **kwargs):
    transport = Session(*responses)
    obj = trading.Client(("per-user-key", rsa_key), environment, proxy_url, session=transport,
                         clock=lambda: NOW, monotonic=kwargs.pop("monotonic", lambda: 0), **kwargs)
    return obj, transport


def ready_client(rsa_key, *responses, metadata=None):
    obj, transport = client(rsa_key, Response({"market": metadata or market_row()}), *responses)
    obj.market(TICKER)
    return obj, transport


def test_signing_uses_correct_full_path_without_query_and_digest_salt(rsa_key):
    obj, transport = client(rsa_key, Response(balance_payload()))
    result = obj.balance()
    method, url, options = transport.calls[0]
    headers = options["headers"]
    assert method == "GET" and url == "https://external-api.kalshi.com/trade-api/v2/margin/balance"
    assert options["params"] == {"compute_available_balance": "true"}
    message = (headers["KALSHI-ACCESS-TIMESTAMP"] + "GET/trade-api/v2/margin/balance").encode()
    rsa_key.public_key().verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]), message,
                                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
    assert headers["KALSHI-ACCESS-KEY"] == "per-user-key"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1792719180125"
    assert result["available_balance_computed"] is True


def test_demo_origin_and_key_are_explicit_not_inherited(rsa_key, monkeypatch):
    monkeypatch.setenv("PROD_KALSHI_KEY_ID", "must-never-be-used")
    monkeypatch.setenv("HTTPS_PROXY", "https://ambient:secret@example.invalid")
    obj, transport = client(rsa_key, Response({"enabled": True}), environment="demo")
    result = obj.enabled_status()
    assert transport.calls[0][1].startswith("https://external-api.demo.kalshi.co/trade-api/v2/margin/")
    assert transport.calls[0][2]["headers"]["KALSHI-ACCESS-KEY"] == "per-user-key"
    assert transport.calls[0][2]["proxies"] == {} and obj._session.trust_env is False
    assert result["environment"] == "demo" and result["enabled"] is True
    assert "must-never-be-used" not in str(transport.calls)


@pytest.mark.parametrize("proxy", ["http://user:secret@proxy.invalid", "https://proxy.invalid/x", "file:///x", "http://proxy.invalid?key=private"])
def test_proxy_credentials_and_arbitrary_routing_are_rejected(rsa_key, proxy):
    with pytest.raises(trading.Error) as error:
        client(rsa_key, proxy_url=proxy)
    assert error.value.code == "invalid_configuration" and error.value.rejected
    assert proxy not in str(error.value)


def test_explicit_credential_free_proxy_is_used_for_fixed_tls_host(rsa_key):
    obj, transport = client(rsa_key, Response({"enabled": False}), proxy_url="http://127.0.0.1:7897")
    assert obj.enabled_status()["enabled"] is False
    options = transport.calls[0][2]
    assert options["proxies"] == {"https": "http://127.0.0.1:7897"}
    assert options["verify"] is True and options["allow_redirects"] is False
    assert options["auth"] == () and options["cookies"] == {}


def test_requests_session_is_sanitized_and_retry_adapters_replaced(rsa_key, monkeypatch):
    session = requests.Session()
    session.auth = ("private", "secret")
    session.headers["Authorization"] = "secret"
    session.params["api_key"] = "secret"
    session.cookies["session"] = "secret"
    session.proxies["https"] = "https://private:secret@proxy.invalid"
    session.verify = False
    session.cert = "private.pem"
    session.hooks["response"].append(lambda _: pytest.fail("inherited hook"))
    session.mount("https://external-api.kalshi.com", requests.adapters.HTTPAdapter(max_retries=3))
    obj = trading.Client(("per-user-key", rsa_key), session=session, clock=lambda: NOW)
    assert not session.headers and not session.cookies and not session.params and not session.proxies
    assert session.auth is None and session.cert is None and session.verify is True and session.trust_env is False
    assert session.hooks == {"response": []}
    assert len(session.adapters) == 1 and session.get_adapter("https://external-api.kalshi.com").max_retries.total == 0
    obj.close()


@pytest.mark.parametrize("credentials,environment", [(None, "production"), (("key", "PEM-secret"), "production"), (("bad\nheader", None), "production"), (("key", None), "staging")])
def test_bad_credentials_are_not_in_errors(credentials, environment):
    with pytest.raises(trading.Error) as error:
        trading.Client(credentials, environment, session=Session())
    assert error.value.rejected and not error.value.uncertain
    assert "PEM-secret" not in str(error.value) and "bad\nheader" not in str(error.value)


def test_context_manager_closes_and_releases_credentials(rsa_key):
    obj, transport = client(rsa_key)
    with obj as handle:
        assert handle is obj and "per-user-key" not in repr(obj)
    assert transport.closed and obj._key is None and obj._key_id is None
    with pytest.raises(trading.Error) as error:
        obj.enabled_status()
    assert error.value.code == "closed" and transport.calls == []


@pytest.mark.parametrize("method,path,private", [("GET", "/portfolio/balance", True), ("POST", "/portfolio/orders", True), ("DELETE", "/margin/orders", True), ("DELETE", "/margin/orders/..%2F..%2Fportfolio%2Forders", True), ("POST", "/margin/orders", False), ("GET", "https://evil.invalid/margin/enabled", True)])
def test_non_native_and_broad_mutation_paths_are_denied(rsa_key, method, path, private):
    obj, transport = client(rsa_key)
    with pytest.raises(trading.Error) as error:
        obj._request(method, path, private=private)
    assert error.value.rejected and transport.calls == []


def test_public_discovery_and_depth_never_receive_auth_headers(rsa_key):
    obj, transport = client(rsa_key, Response({"markets": [market_row()]}),
                            Response({"orderbook": {"bids": [["7.1000", "4.00"]], "asks": [["7.2000", "3.00"]]}}))
    instrument = obj.market()
    book = obj.orderbook(TICKER)
    assert instrument["contract_multiplier"] == "0.0001000000"
    assert instrument["price_basis"] == "per_contract"
    assert book["orderbook"]["asks"][0][0] == "7.2000"
    for _, _, options in transport.calls:
        assert options["headers"] == {"Accept": "application/json"}
    assert transport.calls[1][2]["params"] == {"depth": 100}


@pytest.mark.parametrize("rows", [[], [market_row(), market_row(ticker="OTHERBTC")], [market_row(title="Ethereum")]])
def test_discovery_never_invents_a_ticker(rsa_key, rows):
    obj, transport = client(rsa_key, Response({"markets": rows}))
    with pytest.raises(trading.Error):
        obj.market()
    assert len(transport.calls) == 1


@pytest.mark.parametrize("metadata", [market_row(ticker="OTHERBTC"), market_row(title="Ethereum"), market_row(contract_size=None), market_row(tick_size="NaN")])
def test_explicit_ticker_still_needs_verified_matching_metadata(rsa_key, metadata):
    obj, _ = client(rsa_key, Response({"market": metadata}))
    with pytest.raises(trading.Error) as error:
        obj.market(TICKER)
    assert error.value.code == "invalid_market"


@pytest.mark.parametrize("book", [{"bids": [["8", "1"]], "asks": [["7", "1"]]}, {"bids": [["7", "1"], ["7.00", "1"]], "asks": []}, {"bids": [["7", "NaN"]], "asks": []}, {"yes": [["0.5", "1"]], "no": []}])
def test_invalid_depth_is_not_binary_converted_or_silently_filled(rsa_key, book):
    obj, _ = ready_client(rsa_key, Response({"orderbook": book}))
    with pytest.raises(trading.Error):
        obj.orderbook(TICKER)


def test_submit_preserves_approved_strings_and_uses_native_units(rsa_key):
    obj, transport = ready_client(rsa_key, Response(acknowledgement(), 201))
    frozen = order_body()
    before = copy.deepcopy(frozen)
    result = obj.submit_order(frozen)
    method, url, options = transport.calls[-1]
    assert method == "POST" and url.endswith("/trade-api/v2/margin/orders")
    assert json.loads(options["data"]) == before and frozen == before
    assert result["acknowledged_fee_total"] == "0.0007100"
    assert Decimal(result["fill_count"]) * Decimal(result["average_fill_price"]) == Decimal("7.100000")
    assert result["average_fill_price"] == "7.1000"
    assert sum(call[0] == "POST" for call in transport.calls) == 1


def test_submit_freezes_body_before_metadata_io_yields(rsa_key):
    body = order_body()
    approved = copy.deepcopy(body)
    obj, transport = client(rsa_key, Response({"market": market_row()}), Response(acknowledgement(), 201))
    original = transport.request
    def mutate_after_metadata(method, url, **kwargs):
        value = original(method, url, **kwargs)
        if method == "GET":
            body["price"], body["side"], body["count"] = "9.0000", "ask", "2.00"
        return value
    transport.request = mutate_after_metadata
    obj.submit_order(body)
    assert json.loads(transport.calls[-1][2]["data"]) == approved


def test_no_added_tau_notional_or_leverage_cap(rsa_key):
    huge_count = "1000000000.00"
    obj, transport = ready_client(rsa_key, Response(acknowledgement(fill_count="0", average_fill_price=None, average_fee_paid=None), 201))
    result = obj.submit_order(order_body(count=huge_count))
    assert result["fill_count"] == "0"
    assert json.loads(transport.calls[-1][2]["data"])["count"] == huge_count


def test_decimal_precision_is_preserved_without_float_roundtrip(rsa_key):
    price = "7.123456789012345678"
    fee = "0.000000000000000001"
    obj, transport = ready_client(rsa_key, Response(acknowledgement(average_fill_price=price, average_fee_paid=fee), 201),
                                  metadata=market_row(tick_size="0.000000000000000001"))
    result = obj.submit_order(order_body(price=price))
    assert json.loads(transport.calls[-1][2]["data"])["price"] == price
    assert result["average_fill_price"] == price and Decimal(result["acknowledged_fee_total"]) == Decimal(fee)


@pytest.mark.parametrize("changes", [{"side": "yes"}, {"time_in_force": "DAY"}, {"time_in_force": "good_till_canceled"}, {"self_trade_prevention_type": "maker"}, {"post_only": True}, {"cancel_order_on_pause": False}, {"reduce_only": 1}, {"subaccount": 1}, {"subaccount": False}, {"market_version": 0}, {"market_version": True}, {"client_order_id": "not-a-server-uuid"}, {"count": "0"}, {"count": "1.25"}, {"count": "1e2"}, {"count": 1}, {"price": "NaN"}, {"price": "0"}, {"price": 7.1}, {"type": "limit"}, {"action": "buy"}, {"leverage": 100}])
def test_invalid_or_binary_order_fields_do_not_reach_http(rsa_key, changes):
    obj, transport = client(rsa_key)
    with pytest.raises(trading.Error) as error:
        obj.submit_order(order_body(**changes))
    assert error.value.rejected and not error.value.uncertain and transport.calls == []


@pytest.mark.parametrize("changes", [{"market_version": 2}, {"price": "7.10005"}])
def test_native_version_or_tick_mismatch_has_no_post(rsa_key, changes):
    obj, transport = ready_client(rsa_key)
    with pytest.raises(trading.Error) as error:
        obj.submit_order(order_body(**changes))
    assert error.value.code == "stale_market" and error.value.rejected
    assert not any(call[0] == "POST" for call in transport.calls)


@pytest.mark.parametrize("side,reduce_only", [("bid", True), ("ask", True), ("ask", False)])
def test_bid_ask_and_reduce_only_are_explicit_and_unchanged(rsa_key, side, reduce_only):
    obj, transport = ready_client(rsa_key, Response(acknowledgement(), 201))
    obj.submit_order(order_body(side=side, reduce_only=reduce_only))
    sent = json.loads(transport.calls[-1][2]["data"])
    assert sent["side"] == side and sent["reduce_only"] is reduce_only


@pytest.mark.parametrize("reply", [requests.ConnectTimeout("PEM-private"), requests.ReadTimeout("private-key-id"), requests.exceptions.SSLError("private"), requests.ConnectionError("private"), Response({}, 429), Response({}, 500), Response({}, 503), Response({}, 302), Response(raw=b'not JSON', status=201), Response({"order_id": "native-order-1"}, 201), Response(acknowledgement(remaining_count="1"), 201), Response(acknowledgement(client_order_id="wrong"), 201), Response(acknowledgement(fill_count="2"), 201)])
def test_ambiguous_post_is_uncertain_never_retried_or_leaked(rsa_key, reply):
    obj, transport = ready_client(rsa_key, reply)
    with pytest.raises(trading.Error) as error:
        obj.submit_order(order_body())
    assert error.value.uncertain and not error.value.rejected
    assert sum(call[0] == "POST" for call in transport.calls) == 1
    assert "private" not in str(error.value)
    if isinstance(reply, Response):
        assert reply.closed


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_definite_order_rejection_is_distinct_from_uncertain_transport(rsa_key, status):
    obj, transport = ready_client(rsa_key, Response({"message": "private raw provider details"}, status))
    with pytest.raises(trading.Error) as error:
        obj.submit_order(order_body())
    assert error.value.rejected and not error.value.uncertain and error.value.status == status
    assert "private raw" not in str(error.value) and len(transport.calls) == 2


def test_conflict_is_reconciled_rather_than_assumed_not_submitted(rsa_key):
    obj, _ = ready_client(rsa_key, Response({"code": "duplicate_client_order_id"}, 409))
    with pytest.raises(trading.Error) as error:
        obj.submit_order(order_body())
    assert error.value.uncertain and error.value.code == "conflict"


def test_partial_and_zero_fill_are_native_terminal_acknowledgements(rsa_key):
    obj, _ = ready_client(rsa_key, Response(acknowledgement(), 201),
                          Response(acknowledgement(client_order_id="00000000-0000-4000-8000-000000000002",
                                                   fill_count="0", average_fill_price=None, average_fee_paid=None), 201))
    assert obj.submit_order(order_body(count="2.00"))["fill_count"] == "1.00"
    empty = obj.submit_order(order_body(client_order_id="00000000-0000-4000-8000-000000000002"))
    assert empty["fill_count"] == "0" and empty["remaining_count"] == "0.00"


def test_no_fill_does_not_invent_missing_price_or_fees(rsa_key):
    obj, _ = ready_client(rsa_key, Response(acknowledgement(fill_count="0", average_fill_price=None, average_fee_paid=None), 201))
    result = obj.submit_order(order_body())
    assert result["fill_count"] == "0" and result["average_fill_price"] is None
    assert "acknowledged_fee_total" not in result


def test_positive_fill_missing_economics_remains_unknown(rsa_key):
    obj, _ = ready_client(rsa_key, Response(acknowledgement(average_fee_paid=None), 201))
    with pytest.raises(trading.Error) as error:
        obj.submit_order(order_body())
    assert error.value.uncertain


@pytest.mark.parametrize("side,changes", [("bid", {"average_fill_price": "7.1001"}),
                                          ("ask", {"average_fill_price": "7.0999"}),
                                          ("bid", {"fill_count": "0.5"})])
def test_fill_outside_limit_or_native_quantity_step_is_unknown(rsa_key, side, changes):
    obj, transport = ready_client(rsa_key, Response(acknowledgement(**changes), 201))
    with pytest.raises(trading.Error) as error:
        obj.submit_order(order_body(side=side))
    assert error.value.uncertain and sum(c[0] == "POST" for c in transport.calls) == 1


def test_fractional_native_partial_fill_is_valid_for_whole_order_when_enabled(rsa_key):
    obj, _ = ready_client(rsa_key, Response(acknowledgement(fill_count="0.50"), 201),
                          metadata=market_row(fractional_trading_enabled=True))
    assert obj.submit_order(order_body())["fill_count"] == "0.50"


def test_orders_exhaust_native_pagination_without_guessed_status(rsa_key):
    obj, transport = client(rsa_key, Response({"orders": [order_row()], "cursor": "page-2"}),
                             Response({"orders": [order_row(order_id="native-order-2")], "cursor": ""}))
    result = obj.orders(min_ts=12)
    assert result["complete"] is True and len(result["orders"]) == 2
    assert transport.calls[0][2]["params"] == {"subaccount": 0, "limit": 1000, "min_ts": 12}
    assert transport.calls[1][2]["params"]["cursor"] == "page-2"
    assert "status" not in transport.calls[0][2]["params"]


def test_fills_use_only_supported_filters_and_preserve_signed_decimal_ledger(rsa_key):
    obj, transport = client(rsa_key, Response({"fills": [fill_row(fees="-0.00001")], "cursor": ""}))
    result = obj.fills(100)
    assert transport.calls[0][2]["params"] == {"subaccount": 0, "min_ts": 100, "limit": 1000}
    assert result["fills"][0]["fees"] == "-0.00001" and result["complete"] is True


@pytest.mark.parametrize("pages", [[{"orders": [], "cursor": "repeat"}, {"orders": [], "cursor": "repeat"}], [{"orders": [order_row()], "cursor": "next"}, {"orders": [order_row()], "cursor": ""}], [{"orders": []}], [{"orders": [], "cursor": "", "next_cursor": "hidden"}], [{"orders": [order_row(subaccount_number=1)], "cursor": ""}]])
def test_incomplete_or_wrong_account_pagination_never_returns_empty_success(rsa_key, pages):
    obj, _ = client(rsa_key, *(Response(page) for page in pages))
    with pytest.raises(trading.Error) as error:
        obj.orders()
    assert error.value.code == "incomplete_state"


def test_page_limit_and_row_limit_fail_closed(rsa_key, monkeypatch):
    monkeypatch.setattr(trading, "MAX_PAGES", 1)
    obj, transport = client(rsa_key, Response({"orders": [], "cursor": "more"}))
    with pytest.raises(trading.Error, match="page limit"):
        obj.orders()
    assert len(transport.calls) == 1
    monkeypatch.setattr(trading, "MAX_ROWS", 1)
    obj, _ = client(rsa_key, Response({"orders": [order_row(), order_row(order_id="two")], "cursor": ""}))
    with pytest.raises(trading.Error, match="complete account read"):
        obj.orders()


def test_primary_positions_and_wrong_ticker_are_validated(rsa_key):
    obj, _ = client(rsa_key, Response({"positions": [{"subaccount": 0, "market_ticker": TICKER, "position": "-2.00", "entry_price": "7.1000"}]}))
    assert obj.positions()["positions"][0]["position"] == "-2.00"
    obj, _ = client(rsa_key, Response({"positions": [{"subaccount": 1, "market_ticker": TICKER, "position": "1"}]}))
    with pytest.raises(trading.Error):
        obj.positions()


@pytest.mark.parametrize("payload", [{"enabled": "true"}, {"subaccount_balances": [], "settled_funds": "0"}, balance_payload(subaccount=1), balance_payload(account_equity="NaN")])
def test_entitlement_and_margin_unknown_are_not_assumed_true_or_zero(rsa_key, payload):
    obj, _ = client(rsa_key, Response(payload))
    with pytest.raises(trading.Error):
        obj.enabled_status() if "enabled" in payload else obj.balance()


def test_effective_fee_rates_and_limits_have_native_units(rsa_key):
    obj, transport = client(rsa_key, Response(raw=b'{"maker_fee_rates":{"SYNTHBTC":-0.00001},"taker_fee_rates":{"SYNTHBTC":0.000123456789012345678}}'),
                             Response({"usage_tier": "basic", "read": {"refill_rate": 400, "bucket_capacity": 400}, "write": {"refill_rate": 100, "bucket_capacity": 100}}))
    rates = obj.fee_tiers()
    assert rates["taker_fee_rates"][TICKER] == "0.000123456789012345678"
    assert rates["maker_fee_rates"][TICKER] == "-0.00001"
    assert obj.api_limits()["read"]["refill_rate"] == 400
    assert transport.calls[-1][1].endswith("/trade-api/v2/account/limits/perps")


def test_broker_risk_is_returned_without_tau_leverage_inference(rsa_key):
    obj, _ = client(rsa_key, Response({"account_leverage": "25.5", "total_position_notional": "25000", "total_maintenance_margin": "200", "positions": []}),
                     Response({"default_notional_value_risk_limit": "1000000", "total_current_usage": "25000", "notional_value_risk_limits_by_market_ticker": {TICKER: "1000000"}, "current_usage_by_market_ticker": {TICKER: "25000"}, "member_notional_value_risk_limit": None, "effective_account_notional_value_risk_limit": "1000000"}))
    assert obj.risk()["account_leverage"] == "25.5"
    assert obj.notional_risk_limit()["effective_account_notional_value_risk_limit"] == "1000000"


def test_native_get_and_cancel_keep_partial_fill_semantics_separate(rsa_key):
    obj, transport = client(rsa_key, Response({"order": order_row(fill_count="1", remaining_count="2")}),
                             Response({"order_id": "native-order-1", "reduced_by": "2", "client_order_id": CID}))
    assert obj.order("native-order-1")["order"]["fill_count"] == "1"
    cancelled = obj.cancel_order("native-order-1")
    assert cancelled["reduced_by"] == "2" and "fill_count" not in cancelled
    assert transport.calls[-1][0] == "DELETE" and transport.calls[-1][2]["params"] == {"subaccount": 0}


def test_wrong_subaccount_in_single_order_is_not_adopted(rsa_key):
    obj, _ = client(rsa_key, Response({"order": order_row(subaccount_number=1)}))
    with pytest.raises(trading.Error):
        obj.order("native-order-1")


@pytest.mark.parametrize("reply", [Response({}, 404), Response({}, 500), requests.ReadTimeout("private"), Response({"order_id": "wrong", "reduced_by": "0"})])
def test_unknown_cancel_never_certifies_no_fill(rsa_key, reply):
    obj, transport = client(rsa_key, reply)
    with pytest.raises(trading.Error) as error:
        obj.cancel_order("native-order-1")
    assert error.value.uncertain and len(transport.calls) == 1


@pytest.mark.parametrize("order_id", ["../portfolio/orders", ".", "abc?secret=x", "abc#fragment", "abc%2fprivate", "bad\nheader"])
def test_order_ids_cannot_escape_the_margin_namespace(rsa_key, order_id):
    obj, transport = client(rsa_key)
    with pytest.raises(trading.Error) as error:
        obj.cancel_order(order_id)
    assert error.value.rejected and transport.calls == []


@pytest.mark.parametrize("raw", [b'{"enabled":true,"enabled":false}', b'{"enabled":NaN}', b'[]', b'invalid'])
def test_malformed_private_read_is_sanitized_and_not_retried(rsa_key, raw):
    response = Response(raw=raw)
    obj, transport = client(rsa_key, response)
    with pytest.raises(trading.Error) as error:
        obj.enabled_status()
    assert not error.value.uncertain and not error.value.rejected and len(transport.calls) == 1 and response.closed


def test_response_size_and_page_total_are_bounded(rsa_key, monkeypatch):
    monkeypatch.setattr(trading, "MAX_RESPONSE_BYTES", 5)
    response = Response({"enabled": True})
    obj, _ = client(rsa_key, response)
    with pytest.raises(trading.Error):
        obj.enabled_status()
    assert response.closed
    monkeypatch.setattr(trading, "MAX_RESPONSE_BYTES", 4 * 1024 * 1024)
    monkeypatch.setattr(trading, "MAX_PAGE_BYTES", 5)
    obj, _ = client(rsa_key, Response({"orders": [], "cursor": ""}))
    with pytest.raises(trading.Error) as error:
        obj.orders()
    assert error.value.code == "incomplete_state"


def test_stream_time_budget_leaves_mutation_uncertain(rsa_key, monkeypatch):
    obj, transport = ready_client(rsa_key, Response(acknowledgement(), 201))
    counter = iter([0, 0, trading.MAX_REQUEST_SECONDS + 1])
    obj._monotonic = lambda: next(counter)
    with pytest.raises(trading.Error) as error:
        obj.submit_order(order_body())
    assert error.value.uncertain and sum(c[0] == "POST" for c in transport.calls) == 1


def test_cleanup_transport_error_does_not_erase_valid_ack_or_leak(rsa_key):
    response = Response(acknowledgement(), 201)
    def bad_close():
        raise requests.ConnectionError("private cleanup information")
    response.close = bad_close
    obj, transport = ready_client(rsa_key, response)
    assert obj.submit_order(order_body())["order_id"] == "native-order-1"
    assert sum(c[0] == "POST" for c in transport.calls) == 1
