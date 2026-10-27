"""The autopilot card's research credits are the two research figures Billing shows, to the cent.

Billing's week split read "autopilot research $59.07 · your research sessions $40.94" while the
autopilot card rounded the research total once and said $100.00: a cent apart. The card's research is
now the sum of Billing's two parts, each rounded half up first, and its check-ins are Billing's part.
Each part keeps its own half-up rounding, so one charge still reads the same on every surface
(test_spend_visibility). Synthetic inputs; nothing stored or charged changes.
"""
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from app.web.routes import chat as chat_routes
from app.web.views import credit_usd

# A heavy week as the ledger holds it (the billing walk's numbers, to six places).
WEEK = {'research': 40.936666, 'autopilot_research': 59.066899, 'autopilot_review': 0.0882, 'chat': 0.074, 'other': 0.0}


def _c(v):
    return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def test_the_autopilot_cards_research_is_billings_two_research_parts():
    credits = {'research': WEEK['research'] + WEEK['autopilot_research'], 'by_source': dict(WEEK)}
    billing_split = {k: credit_usd(v) for k, v in WEEK.items()}  # billing_state's spent_7d_by
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
