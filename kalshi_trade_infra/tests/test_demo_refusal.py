"""Which exchange errors are a definite refusal (no order created), and what the engine does with
one: a refused demo order's intent settles 'unfilled' with the refusal stored; everything else, and
every live order, is left exactly as before. No network, no DB."""
import pytest

from app.trading import engine
from app.execution.refusal import OrderRefused, definite_refusal
from app.services import demo_record

INSUFFICIENT = '{"error":{"code":"insufficient_balance","message":"insufficient balance","service":"exchange"}}'


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_these_4xx_answers_are_definite_refusals(status):
    r = definite_refusal(status, INSUFFICIENT, "c-1")
    assert r == {"http_status": status, "code": "insufficient_balance", "message": "insufficient balance",
                 "client_order_id": "c-1"}


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503, 504])
def test_other_statuses_are_never_definite(status):
    assert definite_refusal(status, INSUFFICIENT, "c-1") is None


@pytest.mark.parametrize("body", [
    '{"error":{"code":"order_already_exists"}}',
    '{"error":{"code":"invalid","message":"duplicate client_order_id"}}',
    '{"error":{"code":"conflict"}}',
])
def test_a_body_about_an_order_that_may_exist_is_never_definite(body):
    assert definite_refusal(400, body, "c-1") is None


def test_a_body_that_is_not_json_still_counts_and_keeps_its_text():
    assert definite_refusal(400, "bad request", None) == {
        "http_status": 400, "code": None, "message": "bad request", "client_order_id": None}


class _Kernel:
    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def execute(self, intent):
        self.calls += 1
        if self.error:
            raise self.error
        return "report"


def _refused(coid):
    return OrderRefused("demo POST /portfolio/events/orders failed 400: " + INSUFFICIENT,
                        definite_refusal(400, INSUFFICIENT, coid))


@pytest.fixture
def marks(monkeypatch):
    out = []
    monkeypatch.setattr(engine.repo, "mark_order_intent",
                        lambda cur, iid, status, *a, **k: out.append((iid, status, k.get("raw_json"))))
    return out


def _trade(mode, kernel, coid="i-1"):
    return engine._live_trade(None, {"id": 1, "user_id": 9, "mode": mode}, kernel, "buy", "yes", "T", 1, 0.4,
                              client_order_id_base=coid)


def test_a_refused_first_demo_order_settles_its_intent_and_the_error_still_propagates(marks):
    err = _refused("i-1")
    with pytest.raises(OrderRefused) as got:
        _trade("demo", _Kernel(err))
    assert got.value is err
    assert marks == [("i-1", "unfilled", {"status": "refused", "refused": err.refusal})]


def test_a_refused_retry_child_leaves_the_intent_sent(marks):
    """A later child may follow one that filled; recovery must still sum the children."""
    with pytest.raises(OrderRefused):
        _trade("demo", _Kernel(_refused("i-1-1")))
    assert marks == []


def test_a_failed_mark_never_hides_the_refusal(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db blip")
    monkeypatch.setattr(engine.repo, "mark_order_intent", boom)
    err = _refused("i-1")
    with pytest.raises(OrderRefused) as got:
        _trade("demo", _Kernel(err))
    assert got.value is err


def test_live_orders_are_never_settled_on_an_error(marks):
    """Live's path is the plain kernel call it always was: no error, refusal-shaped or not, touches
    the intent, and the result comes back untouched."""
    for err in (_refused("i-1"), RuntimeError("POST x failed 400: " + INSUFFICIENT)):
        with pytest.raises(type(err)) as got:
            _trade("live", _Kernel(err))
        assert got.value is err
    assert marks == []
    assert _trade("live", _Kernel()) == "report"


def test_a_demo_error_that_is_not_a_refusal_leaves_the_intent_sent(marks):
    with pytest.raises(RuntimeError):
        _trade("demo", _Kernel(RuntimeError("demo POST /portfolio/events/orders failed 500: oops")))
    assert marks == []


def _outcomes(monkeypatch, **o):
    base = {"resolved": 0, "unresolved": 0, "first_at": None, "booked": 0, "refused": 0, "last_refusal": None}
    base.update(o)
    monkeypatch.setattr(demo_record.repo, "demo_order_outcomes", lambda cur, uid, sid, stale: base)
    monkeypatch.setattr(demo_record.repo, "demo_sweeps_since", lambda cur, uid, t: [])


def test_demo_that_never_traded_names_the_refusal(monkeypatch):
    _outcomes(monkeypatch, refused=1, last_refusal={"http_status": 400, "code": "insufficient_balance"})
    ev = demo_record.demo_evidence(None, 1, 7)
    assert ev["why"] == ("it couldn't trade on the demo exchange yet: Kalshi refused its 1 demo order (the "
                         "Kalshi demo account doesn't have enough balance; add demo funds on Kalshi's demo site)")


def test_refusals_after_real_fills_are_named_but_not_counted(monkeypatch):
    _outcomes(monkeypatch, resolved=5, booked=4, refused=2,
              last_refusal={"http_status": 400, "code": "market_closed", "message": "market is closed"})
    ev = demo_record.demo_evidence(None, 1, 7)
    assert not ev["ok"] and ev["orders"] == 5
    assert ev["why"].endswith("(has 5); 2 more were refused by Kalshi (Kalshi said: market is closed)")


@pytest.mark.parametrize("refusal,phrase", [
    ({"http_status": 401}, "didn't accept the demo key"),
    ({"http_status": 404, "code": "market_not_found"}, "Kalshi said: market_not_found"),
    (None, "no reason given"),
])
def test_refusal_reasons_read_plainly(refusal, phrase):
    assert phrase in demo_record.refusal_reason(refusal)
