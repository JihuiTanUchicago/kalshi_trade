"""The autopilot card's research credits are the two research figures Billing shows, to the cent.

Billing's week split read "autopilot research $59.07 · your research sessions $40.94" while the
autopilot card rounded the research total once and said $100.00: a cent apart. The card's research is
now the sum of Billing's two parts as Billing rounds them, and its check-ins are Billing's part.

Billing's parts add up to the week it shows (credit_split, largest remainder): rounded half up each on
its own they read $38.85 + $0.18 + $0.18 under $39.22, and a part under half a cent was dropped. It is
now named, and the page says "under $0.01". A lone charge still reads the same on every surface
(test_spend_visibility). Synthetic inputs; nothing stored or charged changes.
"""
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from app import server
from app.web.routes import billing as billing_routes
from app.web.routes import chat as chat_routes
from app.web.views import credit_split, credit_usd

# A heavy week as the ledger holds it (the billing walk's numbers, to six places).
WEEK = {'research': 40.936666, 'autopilot_research': 59.066899, 'autopilot_review': 0.0882, 'chat': 0.074, 'other': 0.0}


def _c(v):
    return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def test_the_autopilot_cards_research_is_billings_two_research_parts():
    credits = {'research': WEEK['research'] + WEEK['autopilot_research'], 'by_source': dict(WEEK)}
    billing_split = credit_split(WEEK, sum(WEEK.values()))  # billing_state's spent_7d_by
    assert (billing_split['research'], billing_split['autopilot_research']) == (40.94, 59.07)
    assert credit_usd(credits['research']) == 100.0  # rounded once: the card's old figure
    assert chat_routes._research_cents(credits) == 100.01
    assert _c(chat_routes._research_cents(credits)) == _c(billing_split['research']) + _c(billing_split['autopilot_research'])
    # A seeded example that ever debited is left out of research: then the research total to the cent.
    assert chat_routes._research_cents({'research': 99.0, 'by_source': dict(WEEK)}) == 99.0


def test_the_card_check_ins_and_research_add_up_with_billings_chat_line_to_the_week(monkeypatch):
    monkeypatch.setattr(chat_routes.billing, 'configured', lambda: True)
    monkeypatch.setattr(chat_routes.repo, 'autopilot_paper_week', lambda *a: {'started': 0, 'pnl': 0.0, 'trades': 0})
    reads = SimpleNamespace(customer=lambda: None, balance=lambda: 25.707012)
    credits = {'research': WEEK['research'] + WEEK['autopilot_research'], 'by_source': dict(WEEK)}
    research = {'cost_7d': chat_routes._research_cents(credits), 'tested_7d': 3, 'passed_7d': 0}
    week = chat_routes._autopilot_week(object(), 7, research, reads, credits, None)
    assert week['research_credits'] == 100.01 and week['checkin_credits'] == 0.09
    # $100.01 + $0.09 + Billing's $0.07 of chat is Billing's $100.17 week.
    assert _c(week['research_credits']) + _c(week['checkin_credits']) + _c(WEEK['chat']) == _c(sum(WEEK.values())) == Decimal('100.17')
    # Credits stay apart from paper: the card's P&L figure is the paper book's, never these.
    assert week['paper_pnl'] == 0.0


def test_the_week_says_whether_a_card_was_ever_charged_only_when_the_credit_read_says(monkeypatch):
    """The card's "free credits so far" beside the week's spend rides the panel's credit read; without it
    the page keeps "real money" (None), never a guess."""
    monkeypatch.setattr(chat_routes.billing, 'configured', lambda: True)
    monkeypatch.setattr(chat_routes.repo, 'autopilot_paper_week', lambda *a: {'started': 0, 'pnl': 0.0, 'trades': 0})
    monkeypatch.setattr(chat_routes.repo, 'usage_by_source', lambda *a: dict(WEEK))
    reads = SimpleNamespace(customer=lambda: None, balance=lambda: 19.16)
    for charged in (False, True):
        credits = {'research': 0.84, 'by_source': dict(WEEK), 'card_charged': charged}
        assert chat_routes._autopilot_week(object(), 7, {}, reads, credits, None)['card_charged'] is charged
    assert chat_routes._autopilot_week(object(), 7, {}, reads, None, None)['card_charged'] is None


# A week Billing showed as $38.85 + $0.18 + $0.18 under $39.22, each part rounded half up on its own, with
# $0.0004 of other agent calls dropped (under half a cent).
SHORT = {'research': 0.0, 'autopilot_research': 38.854, 'autopilot_review': 0.1849, 'chat': 0.1849, 'other': 0.0004}


def _billing_week(monkeypatch, by, spent):
    """billing_state over a week that spent `by`, payments off, every read synthetic."""
    monkeypatch.setattr(billing_routes.billing, 'configured', lambda: False)
    monkeypatch.setattr(billing_routes.repo, 'get_stripe_customer', lambda *a: None)
    monkeypatch.setattr(billing_routes.repo, 'credit_totals', lambda *a: {
        'bonus': {'all': 60.0, 'n': 1, 'since': 60.0, 'n_since': 1},
        'usage': {'all': -spent, 'n': 9, 'since': -spent, 'n_since': 9}})
    monkeypatch.setattr(billing_routes.repo, 'credit_spent_total', lambda *a: spent)
    monkeypatch.setattr(billing_routes.repo, 'credit_statement', lambda *a: [])
    monkeypatch.setattr(billing_routes.repo, 'usage_by_source', lambda *a: dict(by))
    ctx = server.Ctx(SimpleNamespace(cursor=lambda: object()), {'id': 7, 'email': 'trader@example.invalid', 'autopilot': 1},
                     (), {}, {}, SimpleNamespace())
    return server.billing_state(ctx)


def test_billings_week_split_adds_up_to_the_week_it_shows_and_names_a_part_under_a_cent(monkeypatch):
    state = _billing_week(monkeypatch, SHORT, sum(SHORT.values()))
    assert state['spent_7d'] == 39.22
    by = state['spent_7d_by']
    assert sum(_c(v) for v in by.values()) == _c(state['spent_7d'])  # the parts shown are the week shown
    assert by == {'research': 0.0, 'autopilot_research': 38.85, 'autopilot_review': 0.19, 'chat': 0.18, 'other': 0.0}
    # Every part within a cent of its exact amount; one that spent nothing stays $0 and isn't named.
    assert all(abs(_c(by[k]) - Decimal(str(v))) < Decimal('0.01') for k, v in SHORT.items())
    assert state['spent_7d_under_cent'] == ['other']
    # The heavy week rounds as before: the card's pinned $40.94 and $59.07.
    heavy = _billing_week(monkeypatch, WEEK, sum(WEEK.values()))
    assert (heavy['spent_7d_by']['research'], heavy['spent_7d_by']['autopilot_research']) == (40.94, 59.07)
    assert heavy['spent_7d_under_cent'] == []


def test_the_cards_research_and_check_ins_are_billings_parts_when_rounding_each_alone_would_not_add_up(monkeypatch):
    # $10.004 + $10.004 of research and $0.004 of check-ins is $20.01 for the week: half up each, Billing read
    # $10.00 + $10.00 under it and the card said $20.00 of research.
    week = {'research': 10.004, 'autopilot_research': 10.004, 'autopilot_review': 0.004, 'chat': 0.0, 'other': 0.0}
    state = _billing_week(monkeypatch, week, sum(week.values()))
    by = state['spent_7d_by']
    assert state['spent_7d'] == 20.01 and sum(_c(v) for v in by.values()) == Decimal('20.01')
    assert state['spent_7d_under_cent'] == ['autopilot_review']
    credits = {'research': week['research'] + week['autopilot_research'], 'by_source': dict(week)}
    assert chat_routes._research_cents(credits) == 20.01
    assert _c(chat_routes._research_cents(credits)) == _c(by['research']) + _c(by['autopilot_research'])
    monkeypatch.setattr(chat_routes.billing, 'configured', lambda: True)
    monkeypatch.setattr(chat_routes.repo, 'autopilot_paper_week', lambda *a: {'started': 0, 'pnl': 0.0, 'trades': 0})
    reads = SimpleNamespace(customer=lambda: None, balance=lambda: 39.99)
    card = chat_routes._autopilot_week(object(), 7, {'cost_7d': chat_routes._research_cents(credits)}, reads, credits, None)
    assert card['checkin_credits'] == by['autopilot_review'] == 0.0
    assert _c(card['research_credits']) + _c(card['checkin_credits']) == _c(state['spent_7d'])


def test_the_card_names_a_figure_under_a_cent_as_billing_does(monkeypatch):
    """Billing's split said "autopilot check-ins under $0.01" (spent_7d_under_cent) while the card dropped the
    check-ins at $0.00, and research of a fraction of a cent read $0.00 there. The card's week now names the
    same parts, and its figures stay Billing's."""
    reads = SimpleNamespace(customer=lambda: None, balance=lambda: 19.99)

    def both(week):
        state = _billing_week(monkeypatch, week, sum(week.values()))
        monkeypatch.setattr(chat_routes.billing, 'configured', lambda: True)
        monkeypatch.setattr(chat_routes.repo, 'autopilot_paper_week', lambda *a: {'started': 0, 'pnl': 0.0, 'trades': 0})
        credits = {'research': week['research'] + week['autopilot_research'], 'by_source': dict(week)}
        card = chat_routes._autopilot_week(object(), 7, {'cost_7d': chat_routes._research_cents(credits)}, reads, credits, None)
        return state, card

    state, card = both({'research': 10.004, 'autopilot_research': 10.004, 'autopilot_review': 0.004, 'chat': 0.0, 'other': 0.0})
    assert state['spent_7d_under_cent'] == ['autopilot_review']
    assert card['checkin_credits'] == 0.0 and card['checkin_under_cent'] is True
    assert card['research_credits'] == 20.01 and card['research_under_cent'] is False

    state, card = both({'research': 0.0, 'autopilot_research': 0.003, 'autopilot_review': 0.25, 'chat': 0.0, 'other': 0.0})
    assert state['spent_7d_under_cent'] == ['autopilot_research']
    assert card['research_credits'] == 0.0 and card['research_under_cent'] is True
    assert card['checkin_credits'] == state['spent_7d_by']['autopilot_review'] == 0.25 and card['checkin_under_cent'] is False

    # Nothing spent is not "under $0.01": a part at $0 stays unnamed, on both.
    state, card = both(dict.fromkeys(WEEK, 0.0))
    assert state['spent_7d_under_cent'] == []
    assert card['research_under_cent'] is False and card['checkin_under_cent'] is False
    # The heavy week: nothing under a cent, the pinned figures unchanged.
    state, card = both(dict(WEEK))
    assert (card['research_credits'], card['checkin_credits']) == (100.01, 0.09)
    assert card['research_under_cent'] is False and card['checkin_under_cent'] is False


def _quiet_research(monkeypatch, spent_usd):
    """The research week's reads stubbed (test_paper_realistic_fills' set): no runs, `spent_usd` debited."""
    from tests.autopilot_status_parts import stub_merged_reads

    stub_merged_reads(monkeypatch)
    monkeypatch.setattr(server.repo, "list_runs", lambda cur, uid, limit=50: [])
    monkeypatch.setattr(server.repo, "research_week", lambda cur, uid, since: [
        {"model": None, "runs": 1, "tried": 3, "passed": 0, "input_tokens": 0, "output_tokens": 0}])
    monkeypatch.setattr(server.repo, "strategies_passed_since", lambda cur, uid, since: 0)
    monkeypatch.setattr(server.repo, "passed_strategies", lambda cur, uid, **k: [])
    monkeypatch.setattr(server.repo, "research_spent_since", lambda cur, uid, since: spent_usd)


def test_research_under_half_a_cent_says_under_a_cent_on_the_autopilot_panel(monkeypatch):
    """The panel's Research line and story left a week's research spend out when it rounded to $0.00, as if
    research had cost nothing; Billing names such a part "under $0.01" (spent_7d_under_cent)."""
    for exact, cost, under in ((0.003, 0.0, True), (0.0, 0.0, False), (0.12, 0.12, False), (0.005, 0.01, False)):
        _quiet_research(monkeypatch, exact)
        out = server._research_activity(None, 7)
        assert (out["cost_7d"], out["cost_7d_under_cent"]) == (cost, under), exact
    # The status passes the card's rounded figure (Billing's split) and the week's exact debit beside it.
    _quiet_research(monkeypatch, 0.0)
    assert server._research_activity(None, 7, None, 0.0, 0.004)["cost_7d_under_cent"] is True
    assert server._research_activity(None, 7, None, 0.0, 0.0)["cost_7d_under_cent"] is False
    assert server._research_activity(None, 7, None, 0.12, 0.1203)["cost_7d_under_cent"] is False
    story = server._autopilot_story({"autopilot": True, "research": {"active": [], "tested_7d": 3, "passed_7d": 0,
                                                                      "cost_7d": 0.0, "cost_7d_under_cent": True}})
    assert story[1].startswith("This week your sessions and the autopilot’s tested 3 ideas for under $0.01 and none has passed")
    plain = server._autopilot_story({"autopilot": True, "research": {"active": [], "tested_7d": 3, "passed_7d": 0, "cost_7d": 0.0}})
    assert plain[1].startswith("This week your sessions and the autopilot’s tested 3 ideas and none has passed")
