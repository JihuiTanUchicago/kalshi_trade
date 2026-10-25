"""Live-ready notice: once per strategy, the user is told (chat + email) when a running paper
strategy first clears every paper -> live check. It never deploys, promotes or changes a gate."""
from app import agent, notify

READY = {"ready": True, "why": "", "trades": 31, "trades_needed": 30, "net_pnl": 4.2, "span_hours": 50.0,
         "p_value": 0.05, "realization": None}


def _patch(monkeypatch, deps, ready=READY, already=(), candidate=True):
    chats, mails = [], []
    bells = []
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: candidate)
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid: list(deps))
    monkeypatch.setattr(agent.repo, "chat_contains", lambda cur, uid, role, needle: needle in already)
    monkeypatch.setattr(agent.repo, "add_chat", lambda cur, uid, role, text, pid=None: chats.append((role, text)))
    monkeypatch.setattr(agent.repo, "add_notification", lambda cur, uid, kind, body, link=None: bells.append((uid, kind, body, link)))
    monkeypatch.setattr(agent, "paper_evidence", lambda cur, uid, sid: dict(ready, ready=ready["ready"]))
    monkeypatch.setattr(notify, "live_ready_notice", lambda *a: mails.append(a) or True)
    return chats, mails, bells


USER = {"id": 2, "email": "t@example.invalid", "name": "T"}
DEP = {"strategy_id": 7, "mode": "paper", "status": "running", "title": "Edge"}


def test_a_newly_ready_paper_strategy_is_announced_once(monkeypatch):
    chats, mails, bells = _patch(monkeypatch, [DEP, dict(DEP)])
    lines = agent.live_ready_notices(None, USER)
    assert len(lines) == 1 and "[live-ready #7]" in lines[0] and "Going live is your call" in lines[0]
    assert chats == [("system", lines[0])]
    assert len(mails) == 1 and mails[0][0] == "t@example.invalid" and mails[0][4].endswith("/strategies/7")
    assert bells == [(2, "live_ready", "“Edge” is ready for live trading. Going live is your call.", "/strategies/7")]


def test_already_announced_is_not_repeated(monkeypatch):
    chats, mails, bells = _patch(monkeypatch, [DEP], already=("[live-ready #7]",))
    assert agent.live_ready_notices(None, USER) == [] and chats == [] and mails == [] and bells == []


def test_not_ready_or_not_paper_is_silent(monkeypatch):
    chats, mails, bells = _patch(monkeypatch, [DEP], ready=dict(READY, ready=False))
    assert agent.live_ready_notices(None, USER) == []
    chats, mails, bells = _patch(monkeypatch, [dict(DEP, mode="live"), dict(DEP, status="paused")])
    assert agent.live_ready_notices(None, USER) == [] and mails == []


def test_chat_contains_query_is_scoped_to_user_and_role():
    from app import repository as repo

    class Rec:
        def execute(self, sql, params=()):
            self.sql, self.params = sql, params

        def fetchone(self):
            return None

    cur = Rec()
    assert repo.chat_contains(cur, 2, "system", "[live-ready #7]") is False
    assert "user_id=%s AND role=%s AND content LIKE %s" in cur.sql
    assert cur.params == (2, "system", "%[live-ready #7]%")


def test_sports_market_notice_says_to_reverify_location(monkeypatch):
    chats, mails, bells = _patch(monkeypatch, [dict(DEP, market="nhl_game")])
    lines = agent.live_ready_notices(None, USER)
    assert "re-verify your location in the Kalshi mobile app" in lines[0]
    assert "Sports" in mails[0][5]


def test_crypto_or_unknown_market_notice_has_no_location_note(monkeypatch):
    chats, mails, bells = _patch(monkeypatch, [dict(DEP, market="btc15m"), dict(DEP, strategy_id=8, market="nope")])
    lines = agent.live_ready_notices(None, USER)
    assert len(lines) == 2 and not any("location" in l for l in lines)
    assert [m[5] for m in mails] == ["", ""]


def test_email_body_carries_the_note(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "_send", lambda to, subj, body: sent.append(body) or True)
    notify.live_ready_notice("t@example.invalid", "T", "Edge", "31 trades", "https://x/strategies/7", "Re-verify.")
    notify.live_ready_notice("t@example.invalid", "T", "Edge", "31 trades", "https://x/strategies/7")
    assert "Re-verify.\n\n  https://x/strategies/7" in sent[0] and "Re-verify" not in sent[1]


def test_a_ready_probation_strategy_gets_a_standout_line_not_a_promote_invite(monkeypatch):
    chats, mails, bells = _patch(monkeypatch, [DEP], candidate=False)
    lines = agent.live_ready_notices(None, USER)
    assert len(lines) == 1 and "[paper-standout #7]" in lines[0] and "can't go live" in lines[0]
    assert "[live-ready" not in lines[0] and mails == []
    chats, mails, bells = _patch(monkeypatch, [DEP], candidate=False, already=("[paper-standout #7]",))
    assert agent.live_ready_notices(None, USER) == []
