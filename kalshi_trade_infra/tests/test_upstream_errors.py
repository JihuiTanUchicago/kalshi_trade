"""A raw upstream error (Stripe's text, the model provider's) never reaches a user. They read what
happened and what to do; the detail goes to the server log. Synthetic inputs only: no Stripe, Bedrock
or database is called."""
import pytest

from app import server
from app.adapters.llm import llm
from app.adapters.stripe import billing
from app.research import agent
from app.server import ApiError
from tests.test_app_agent import RUN, Conn, Store
from tests.test_app_backtest import _dataset

RAW = "No such PaymentMethod: 'pm_synthetic123'; a similar object exists in test mode, but a live mode key was used"


class FakeCur:
    def execute(self, *a):
        pass

    def fetchone(self):
        return {"n": 0}


class FakeConn:
    def cursor(self):
        return FakeCur()


def ctx(body=None):
    return server.Ctx(FakeConn(), {"id": 7, "email": "synthetic@example.invalid"}, (), {}, body or {}, None)


def raises(e):
    def boom(*a, **k):
        raise e
    return boom


@pytest.fixture
def customer(monkeypatch):
    saved = {}
    monkeypatch.setattr(server.billing, "configured", lambda: True)
    monkeypatch.setattr(server.repo, "get_stripe_customer",
                        lambda cur, uid: {"stripe_customer_id": "cus_synthetic", "default_pm_id": "pm_old"})
    monkeypatch.setattr(server.repo, "set_default_pm", lambda cur, uid, pm: saved.setdefault("default", pm))
    return saved


def assert_clean(message):
    for leak in ("pm_synthetic123", "No such", "live mode", "Stripe", "HTTPSConnectionPool", "api.stripe.com", "status:"):
        assert leak not in message, message


def test_card_added_never_shows_stripes_text_and_logs_it(monkeypatch, customer, capsys):
    err = billing.StripeError(RAW, kind="invalid_request_error", code="resource_missing")
    monkeypatch.setattr(server.billing, "set_default_card", raises(err))
    with pytest.raises(ApiError) as e:
        server.billing_card_added(ctx({"payment_method_id": "pm_new"}))
    assert e.value.status == 502
    assert e.value.message == "Your card couldn't be saved just now. Reload the page and add it again."
    log = capsys.readouterr().out
    assert RAW in log and "user 7" in log and "resource_missing" in log  # the detail is kept, server-side


def test_card_added_for_a_new_customer_covers_creating_the_customer_too(monkeypatch, capsys):
    monkeypatch.setattr(server.repo, "get_stripe_customer", lambda cur, uid: None)
    monkeypatch.setattr(server.billing, "get_or_create_customer",
                        raises(billing.StripeError("Could not reach Stripe: HTTPSConnectionPool(host='api.stripe.com')")))
    with pytest.raises(ApiError) as e:
        server.billing_card_added(ctx({"payment_method_id": "pm_new"}))
    assert e.value.status == 502
    assert_clean(e.value.message)
    assert "HTTPSConnectionPool" in capsys.readouterr().out


def test_setup_intent_and_card_removal_failures_say_what_to_do(monkeypatch, customer):
    err = billing.StripeError(RAW, kind="api_error")
    monkeypatch.setattr(server.billing, "create_setup_intent", raises(err))
    with pytest.raises(ApiError) as e:
        server.billing_setup_intent(ctx())
    assert e.value.status == 502 and e.value.message.startswith("The card form couldn't start just now.")
    monkeypatch.setattr(server.billing, "list_cards", raises(err))
    with pytest.raises(ApiError) as e:
        server.billing_remove_card(ctx({"payment_method_id": "pm_old"}))
    assert e.value.message == "Your cards couldn't be loaded just now, so nothing was removed. Try again in a minute."
    monkeypatch.setattr(server.billing, "list_cards", lambda cid: [{"id": "pm_old"}, {"id": "pm_two"}])
    monkeypatch.setattr(server.billing, "detach_card", raises(err))
    with pytest.raises(ApiError) as e:
        server.billing_remove_card(ctx({"payment_method_id": "pm_old"}))
    assert e.value.message == "That card couldn't be removed just now. Try again in a minute."
    assert customer == {}  # nothing removed, so the saved default is untouched


def test_removing_the_default_card_moves_the_default_even_when_stripe_wont(monkeypatch, customer, capsys):
    monkeypatch.setattr(server.billing, "list_cards", lambda cid: [{"id": "pm_old"}, {"id": "pm_two"}])
    monkeypatch.setattr(server.billing, "detach_card", lambda pm: None)
    monkeypatch.setattr(server.billing, "set_default_card", raises(billing.StripeError(RAW)))
    assert server.billing_remove_card(ctx({"payment_method_id": "pm_old"})) == {"ok": True}
    assert customer == {"default": "pm_two"}  # Tau charges this one, never the removed card
    assert RAW in capsys.readouterr().out


@pytest.mark.parametrize("decline, said", [
    ("insufficient_funds", "Your card was declined for insufficient funds. Try another card."),
    ("expired_card", "That card has expired. Add a current card and try again."),
    ("do_not_honor", billing.CARD_DECLINED),
])
def test_a_declined_top_up_says_why_in_tau_words(monkeypatch, customer, decline, said):
    err = billing.StripeError("Your card has insufficient funds.", kind="card_error", code="card_declined",
                              decline_code=decline)
    monkeypatch.setattr(server.billing, "charge", raises(err))
    with pytest.raises(ApiError) as e:
        server.billing_topup(ctx({"amount": 10}))
    assert e.value.status == 402 and e.value.message == said


def test_a_top_up_that_drops_mid_charge_never_says_nothing_was_charged(monkeypatch, customer):
    monkeypatch.setattr(server.billing, "charge",
                        raises(billing.StripeError("Could not reach Stripe: Read timed out. (read timeout=25)")))
    with pytest.raises(ApiError) as e:
        server.billing_topup(ctx({"amount": 10}))
    assert e.value.status == 402
    assert_clean(e.value.message)
    assert "check your balance before you try again" in e.value.message and "weren't charged" not in e.value.message


def test_a_top_up_left_pending_does_not_echo_stripes_status(monkeypatch, customer, capsys):
    monkeypatch.setattr(server.billing, "charge", lambda *a, **k: {"status": "requires_action", "id": "pi_synthetic"})
    with pytest.raises(ApiError) as e:
        server.billing_topup(ctx({"amount": 10}))
    assert "requires_action" not in e.value.message and "status" not in e.value.message
    assert "requires_action" in capsys.readouterr().out


class _Resp:
    def __init__(self, status, body, text=""):
        self.status_code, self._body, self.content, self.text = status, body, b"x", text

    def json(self):
        return self._body


def test_stripe_errors_carry_their_type_and_codes_for_the_mapping(monkeypatch):
    monkeypatch.setattr(billing, "STRIPE_SECRET_KEY", "synthetic-only")
    body = {"error": {"type": "card_error", "code": "card_declined", "decline_code": "insufficient_funds",
                      "message": "Your card has insufficient funds."}}
    monkeypatch.setattr(billing.requests, "post", lambda *a, **k: _Resp(402, body))
    with pytest.raises(billing.StripeError) as e:
        billing.charge("cus_synthetic", "pm_synthetic", 1000, off_session=False, idem="synthetic")
    assert (e.value.kind, e.value.code, e.value.decline_code) == ("card_error", "card_declined", "insufficient_funds")
    assert str(e.value) == "Your card has insufficient funds."  # kept whole for the log
    assert billing.customer_message(e.value, "fallback") == "Your card was declined for insufficient funds. Try another card."
    assert billing.customer_message(billing.StripeError(RAW, kind="invalid_request_error"), "fallback") == "fallback"


# -- the model provider ---------------------------------------------------------------------------

def test_provider_failures_keep_their_detail_but_read_plainly(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-only")
    monkeypatch.setattr(llm.requests, "post",
                        lambda *a, **k: _Resp(400, {}, '{"error": {"message": "model: claude-internal-id-20991231 not found"}}'))
    with pytest.raises(llm.LLMError) as e:
        llm._anthropic_direct("sys", [{"role": "user", "content": "hi"}])
    assert "claude-internal-id" in str(e.value)  # the log and the code still see it
    assert llm.public_message(e.value) == llm.UNREACHABLE_COPY
    # A message written for users is left as it is.
    assert llm.public_message(llm.LLMError("The data store was busy; please start the session again.")) \
        == "The data store was busy; please start the session again."
    # The daily-quota check still reads the provider's text through str().
    throttled = llm.LLMThrottled("ThrottlingException on 'm': Too many tokens per day", public=llm.CAPACITY_COPY)
    assert llm._is_daily_quota(throttled) and llm.public_message(throttled) == llm.CAPACITY_COPY


def test_a_research_session_that_loses_the_model_says_so_without_the_providers_text(monkeypatch):
    store = Store(monkeypatch)
    detail = ("ThrottlingException on 'us.synthetic.model-v9:0': An error occurred (ThrottlingException) when "
              "calling the Converse operation (arn:aws:bedrock:us-east-1:000000000000)")

    def model(system, messages):
        raise llm.LLMThrottled(detail, public=llm.CAPACITY_COPY)

    agent.run_research(Conn(), RUN, model=model, dataset_fn=lambda m, h=None: _dataset(n_contracts=60))
    status, error, _, _ = store.finished
    assert status == "failed" and error == llm.CAPACITY_COPY
    shown = " ".join(msg for _, msg, _ in store.events)
    for leak in ("ThrottlingException", "arn:aws", "us.synthetic", "Converse"):
        assert leak not in shown, shown
