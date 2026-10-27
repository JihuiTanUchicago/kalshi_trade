"""What the autopilot chat says about a proposal before and after the user decides, and what a turn
costs (walked 2026-10-26 on a phone and a desktop, in both themes, with the model stubbed):

- A risk or execution proposal named the settings by their keys ("drawdown_limit_pct=20.0,
  max_open_notional=200.0") over Approve. It now says them in words, and an older line reads so too.
- "You approved the proposal." named neither the proposal nor the change. The decision line now says
  which proposal it answers and what is true now (paused and selling, running again, the new limits),
  or that nothing changed.
- A paper strategy a few minutes old was "on paper for only 0.0 hours".
- The chat read carries what the newest answered message cost (turn_cost), read on the first load and
  when an answer arrives, not on every poll in between, and only while payments are on.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.research import agent
from app.services import customer_text
from app.web.routes import chat as chat_routes

NOW = datetime(2026, 10, 26, 21, 0, 0)
KEYS = ("drawdown_limit_pct", "max_open_positions", "max_open_notional", "exec_max_book_fraction",
        "exec_max_entry_spread", "exec_max_order_notional")


def test_control_changes_read_in_words_never_as_setting_keys():
    risk = customer_text.control_changes({"drawdown_limit_pct": 20.0, "max_open_positions": 1, "max_open_notional": 200.0})
    assert risk == ("a strategy stops once it is down 20% of its capital, at most 1 open position, "
                    "at most $200.00 in open positions")
    ex = customer_text.control_changes({"exec_max_book_fraction": 0.1, "exec_max_entry_spread": 0.05,
                                        "exec_max_order_notional": 50})
    assert ex == ("each order takes at most 10% of the contracts on offer, no entry when the spread is wider "
                  "than 5¢, at most $50.00 per order")
    assert not any(k in risk + ex for k in KEYS)


def test_an_older_chat_line_with_setting_keys_reads_in_words_and_other_lines_are_untouched():
    rows = customer_text.chat_rows([
        {"role": "system", "content": "Proposed a risk-control change (within safe bounds): drawdown_limit_pct=15, max_open_notional=150.0."},
        {"role": "system", "content": "Autopilot adjusted your execution controls (within safe bounds): exec_max_entry_spread=0.04."},
        {"role": "agent", "content": "I'd set max_open_positions=3 if I were you."},  # the agent's own words stay
        {"role": "system", "content": "Market focus set to btc."},
    ])
    assert rows[0]["content"] == ("Proposed a risk-control change (within safe bounds): a strategy stops once it is "
                                  "down 15% of its capital, at most $150.00 in open positions.")
    assert rows[1]["content"].endswith("no entry when the spread is wider than 4¢.")
    assert rows[2]["content"] == "I'd set max_open_positions=3 if I were you."
    assert rows[3]["content"] == "Market focus set to btc."


@pytest.mark.parametrize("kind,changes,line", [
    ("set_risk", {"drawdown_limit_pct": 15, "max_open_notional": 150},
     "Proposed a risk-control change (within safe bounds): a strategy stops once it is down 15% of its capital, "
     "at most $150.00 in open positions."),
    ("set_exec", {"exec_max_order_notional": 40},
     "Proposed an execution-control change (within safe bounds): at most $40.00 per order."),
])
def test_a_risk_or_execution_proposal_says_its_change_in_words(monkeypatch, kind, changes, line):
    made = []
    monkeypatch.setattr(agent.repo, "create_proposal", lambda cur, uid, k, reason, d, s, status, payload=None:
                        made.append((k, status, payload)) or 7)
    text, pid = agent.act(None, {"id": 1}, {"type": kind, "changes": changes, "reason": "Losses cluster."}, False)
    assert (text, pid) == (line, 7)
    assert made[0][:2] == (kind, "pending") and made[0][2] == changes  # what it would apply is unchanged


@pytest.mark.parametrize("age,words", [(timedelta(seconds=20), "1 minute"), (timedelta(minutes=11), "11 minutes"),
                                       (timedelta(minutes=89), "89 minutes"), (timedelta(hours=3, minutes=12), "3.2 hours")])
def test_a_young_paper_strategy_the_autopilot_keeps_says_how_long_it_has_run(monkeypatch, age, words):
    monkeypatch.setattr(agent.repo, "now_utc", lambda: NOW)
    dep = {"id": 4, "title": "Fade the late spike", "status": "running", "mode": "paper", "market": "btc15m",
           "spec": {}, "created_at": NOW - age}
    monkeypatch.setattr(agent.repo, "get_deployment", lambda cur, uid, did: dict(dep))
    text, pid = agent.act(None, {"id": 1}, {"type": "pause", "deployment_id": 4}, True)
    assert pid is None
    assert text.startswith("I left Fade the late spike running: it has been on paper for only %s, and paper " % words)
    assert "0.0 hours" not in text


class _Tx:
    def __enter__(self):
        return "tx"

    def __exit__(self, *a):
        return False


def _decide(monkeypatch, proposal, decision, dep=None, strategy=None):
    lines = []
    monkeypatch.setattr(chat_routes.repo, "get_proposal", lambda cur, uid, pid: dict(proposal))
    monkeypatch.setattr(chat_routes.repo, "transaction", lambda conn: _Tx())
    monkeypatch.setattr(chat_routes.repo, "decide_proposal", lambda cur, pid, status: True)
    monkeypatch.setattr(chat_routes.repo, "get_deployment", lambda cur, uid, did: dep)
    monkeypatch.setattr(chat_routes.repo, "get_strategy", lambda cur, uid, sid: strategy)
    monkeypatch.setattr(chat_routes.repo, "add_chat", lambda cur, uid, role, text, pid=None: lines.append((role, text)))
    monkeypatch.setattr(chat_routes.agent, "apply_proposal", lambda cur, uid, p: None)
    monkeypatch.setattr(chat_routes, "_forget_own_change", lambda uid: None)
    ctx = SimpleNamespace(params=("5", decision), conn=None, cur=None, uid=1)
    assert chat_routes.decide_proposal(ctx) == {"ok": True}
    assert len(lines) == 1 and lines[0][0] == "system"
    return lines[0][1]


@pytest.mark.parametrize("proposal,decision,dep,strategy,line", [
    ({"kind": "pause", "deployment_id": 3}, "approve", {"title": "BTC fade", "mode": "paper"}, None,
     "You approved the proposal to pause BTC fade. It is paused, and anything it holds is sold."),
    ({"kind": "pause", "deployment_id": 3}, "approve", {"title": "BTC fade", "mode": "live"}, None,
     "You approved the proposal to pause BTC fade. It is paused, and anything it holds in your Kalshi account is sold."),
    ({"kind": "pause", "deployment_id": 3}, "reject", {"title": "BTC fade", "mode": "paper"}, None,
     "You declined the proposal to pause BTC fade. Nothing changed."),
    ({"kind": "resume", "deployment_id": 3}, "approve", {"title": "BTC fade", "mode": "demo"}, None,
     "You approved the proposal to resume BTC fade. It is running again, on demo, Kalshi’s sandbox."),
    ({"kind": "adjust", "deployment_id": 3, "strategy_id": 8}, "approve", {"title": "BTC fade v2", "mode": "paper"}, None,
     "You approved the proposal to tune BTC fade v2. It now trades the tuned version, on paper, with practice money."),
    ({"kind": "deploy", "strategy_id": 8}, "approve", None, {"title": "ETH drift"},
     "You approved the proposal to put ETH drift on paper. It is on paper now. Nothing trades real money."),
    ({"kind": "set_risk", "payload": {"drawdown_limit_pct": 15.0, "max_open_positions": 4}}, "approve", None, None,
     "You approved the proposal to change your risk limits. Now: a strategy stops once it is down 15% of its capital, "
     "at most 4 open positions. These apply to every strategy you run."),
    ({"kind": "set_exec", "payload": {"exec_max_order_notional": 40}}, "reject", None, None,
     "You declined the proposal to change your execution limits. Nothing changed."),
    # A deployment gone since: the plain line, never a blank name.
    ({"kind": "pause", "deployment_id": 3}, "approve", None, None, "You approved the proposal."),
])
def test_the_decision_line_names_the_proposal_and_what_changed(monkeypatch, proposal, decision, dep, strategy, line):
    monkeypatch.setattr(chat_routes.engine, "LIVE_TRADING_ENABLED", True)  # the server's live switch open
    text = _decide(monkeypatch, dict(proposal, id=5, status="pending"), decision, dep, strategy)
    assert text == line
    assert text.startswith("You %s the proposal" % ("approved" if decision == "approve" else "declined"))  # heads "Your decision"
    assert "utopilot" not in text  # the user's decision is never read back as the autopilot's last move


@pytest.mark.parametrize("kind,line", [
    ("pause", "You approved the proposal to pause BTC fade. It is paused. Live trading isn’t open yet, so Tau can’t sell "
              "what it holds in your Kalshi account; that stays open until its market settles."),
    ("resume", "You approved the proposal to resume BTC fade. It is set to run again on live, but live trading isn’t "
               "open yet, so it places no orders."),
    ("adjust", "You approved the proposal to tune BTC fade. It now runs the tuned version on live, but live trading "
               "isn’t open yet, so it places no orders."),
])
def test_a_live_deployments_decision_line_says_it_waits_while_live_trading_is_closed(monkeypatch, kind, line):
    # The server's live switch is closed: a live deployment places no orders and can't sell what it holds,
    # so the line never says it runs "LIVE, with real money" or that its holdings are sold.
    monkeypatch.setattr(chat_routes.engine, "LIVE_TRADING_ENABLED", False)
    text = _decide(monkeypatch, {"kind": kind, "deployment_id": 3, "strategy_id": 8, "id": 5, "status": "pending"},
                   "approve", {"title": "BTC fade", "mode": "live"})
    assert text == line
    assert "real money" not in text and "is sold" not in text
    # A paper one reads as before.
    paper = _decide(monkeypatch, {"kind": kind, "deployment_id": 3, "strategy_id": 8, "id": 5, "status": "pending"},
                    "approve", {"title": "BTC fade", "mode": "paper"})
    assert "live trading" not in paper


def _chat(monkeypatch, msgs, after, configured=True, cost=0.153):
    reads = []
    monkeypatch.setattr(chat_routes.repo, "chat_messages", lambda cur, uid, a: [dict(m) for m in msgs])
    monkeypatch.setattr(chat_routes.repo, "active_agent_run", lambda cur, uid, kind=None: None)
    monkeypatch.setattr(chat_routes.repo, "last_chat_turn_cost", lambda cur, uid: reads.append(uid) or cost)
    monkeypatch.setattr(chat_routes.billing, "configured", lambda: configured)
    out = chat_routes.get_chat(SimpleNamespace(query={"after": str(after)} if after else {}, cur=None, uid=1))
    return out, reads


def test_the_chat_read_says_what_the_last_answered_message_cost_without_a_read_on_every_poll(monkeypatch):
    at = NOW.isoformat()
    you = {"id": 9, "role": "user", "content": "How is it going?", "created_at": at}
    reply = {"id": 10, "role": "agent", "content": "Fine.", "created_at": at}
    failed = {"id": 11, "role": "system", "content": "The agent hit an error and didn't answer. Send your message again, or try in a minute.", "created_at": at}
    out, reads = _chat(monkeypatch, [], 0)  # the first load
    assert out["turn_cost"] == 0.153 and reads == [1]
    out, reads = _chat(monkeypatch, [you], 8)  # your own line only: nothing new to price
    assert "turn_cost" not in out and reads == []
    out, reads = _chat(monkeypatch, [], 10)  # a quiet poll
    assert "turn_cost" not in out and reads == []
    for line in (reply, failed):  # an answer, or the note that there was none
        out, reads = _chat(monkeypatch, [line], 9)
        assert out["turn_cost"] == 0.153 and reads == [1]
    out, _ = _chat(monkeypatch, [], 0, cost=None)  # no finished turn yet
    assert out["turn_cost"] is None
    out, reads = _chat(monkeypatch, [reply], 0, configured=False)  # payments off: nothing is billed
    assert "turn_cost" not in out and reads == []
