"""The autopilot panel's story says a paper figure to the cent every other page shows (money.cents).

It formatted the furthest-along strategy's realistic paper net with "%.2f", which rounds the float: an exact
$0.7450 net read "up $0.74" while the strategy page's Road to live, the Deploy row and the track record read
$0.75, and a net a fraction of a cent down read "down $0.00". The story rounds once, half up, as they do.
Display only: the figure itself (agent.paper_evidence) is unchanged.
"""
from app.services import customer_text
from app.web.routes import chat
from trading_core.domain.money import cents


def _story(net):
    d = {"autopilot": True, "paper_running": 1, "live_running": 0,
         "paper_progress": {"trades": 12, "trades_needed": 30, "net_pnl": net},
         "research": {"active": [], "tested_7d": 0, "passed_7d": 0}}
    return next(line for line in chat._autopilot_story(d) if "realistic paper trades live needs" in line)


def test_the_story_rounds_a_half_cent_as_every_page_does():
    # 0.745 as a float is 0.74499999…: "%.2f" said 0.74; cents() says 0.75, as the pages do.
    assert "%.2f" % 0.745 == "0.74" and cents(0.745) == 0.75
    assert "is up $0.75 on them %s" % customer_text.PAPER_NET_SHORT in _story(0.745)
    assert "is down $0.75 on them" in _story(-0.745)


def test_a_fraction_of_a_cent_down_is_not_down_zero():
    for net in (-0.004, -0.0001, 0.0):
        line = _story(net)
        assert "down $0.00" not in line
        assert "is up $0.00 on them" in line


def test_paused_lines_say_the_same_cents():
    p = [{"title": "Fade", "trades": 2, "pnl": -0.004, "why": "its loss guard fired"}]
    assert chat._paused_lines(p) == ["Fade was paused after 2 paper trades (up $0.00 %s): its loss guard fired."
                                     % customer_text.PAPER_NET_SHORT]
    assert chat._money(-1.005) == "down $1.01"  # half up, away from zero, as money.cents
