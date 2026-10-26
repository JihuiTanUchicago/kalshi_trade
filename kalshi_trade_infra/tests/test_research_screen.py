"""Model tiering (services.research_screen): the cheaper model screens, the run's model develops."""
from app.research import agent as A
from app.research import rsi
from app.adapters.llm.llm import Usage
from app.research_watch import screen_ab
from app.services import research_screen as rs

DS = type("DS", (), {"start_ts": 0, "cutoff_ts": 1, "frames": []})()
BASE = {"title": "H", "thesis": "t", "spec": {"market": "m", "side": "yes"}}
SCREEN_FN = object()  # identities: which model each develop turn was asked on
DEV_FN = object()


def _fake_test(h, *a, **k):
    return dict(h, in_sample={"trades": 40, "win_rate": 0.5, "pnl": 1.0, "fees": 0.1,
                              "profit_factor": 1.2, "max_drawdown": 0.5}, capital=100.0,
                attribution=None, diagnosis="")


class MD:
    """Scripted develop replies per model; records which model each turn went to."""

    def __init__(self, screen_replies, dev_replies):
        self.replies = {id(SCREEN_FN): list(screen_replies), id(DEV_FN): list(dev_replies)}
        self.seen = []

    def ask(self, model, system, messages, check, usage):
        self.seen.append("screen" if model is SCREEN_FN else "dev")
        return self.replies[id(model)].pop(0)


def _screen(audit=0.0, monkeypatch=None):
    monkeypatch.setattr(rs, "AUDIT_SHARE", audit)
    s = rs.Screen(run_id=7, choice=rs.catalog.get("sonnet-4-6"), model=lambda *a, **k: None)
    return s


def _develop(md, screen, monkeypatch, steps=20):
    monkeypatch.setattr(A, "THESIS_MAX_STEPS", steps)
    monkeypatch.setattr(A, "_test_in_sample", _fake_test)
    events = []
    out = A._develop_thesis(dict(BASE), {"market": "m"}, DS, {}, [], DEV_FN, md, Usage(),
                            lambda kind, msg, data=None: events.append((kind, msg, data or {})),
                            lambda: None, 1, cur=None, user_id=1, screen=screen, screener=SCREEN_FN)
    return out, events


def test_the_developer_judges_every_thesis_the_screen_would_commit(monkeypatch):
    s = _screen(monkeypatch=monkeypatch)
    md = MD([{"decision": "refine", "spec": {"market": "m", "side": "no"}, "change": "flip"},
             {"decision": "commit", "why": "ready"}],
            [{"decision": "commit", "why": "agree"}])
    out, _ = _develop(md, s, monkeypatch)
    assert out["spec"]["side"] == "no"
    assert md.seen == ["screen", "screen", "dev"]
    assert s.tally["handed_over"] == 1


def test_a_screen_abandon_is_final_without_an_audit(monkeypatch):
    s = _screen(audit=0.0, monkeypatch=monkeypatch)
    md = MD([{"decision": "abandon", "why": "no counterparty"}], [])
    out, events = _develop(md, s, monkeypatch)
    assert out is None and md.seen == ["screen"]
    assert s.tally["screened_out"] == 1
    assert events[-1][2].get("screened") is True


def test_an_audited_screen_abandon_can_be_rescued_by_the_developer(monkeypatch):
    s = _screen(audit=1.0, monkeypatch=monkeypatch)
    md = MD([{"decision": "abandon", "why": "looks dead"}],
            [{"decision": "refine", "spec": {"market": "m", "side": "no"}, "change": "real angle"},
             {"decision": "commit", "why": "ready"}])
    out, events = _develop(md, s, monkeypatch)
    assert out is not None and out["spec"]["side"] == "no"
    assert md.seen == ["screen", "dev", "dev"]
    assert s.tally["audits"] == 1 and s.tally["rescued"] == 1
    assert any(d.get("phase") == "screen_audit" and d["developer"] == "refine" for _, _, d in events)


def test_an_audit_that_agrees_confirms_the_drop(monkeypatch):
    s = _screen(audit=1.0, monkeypatch=monkeypatch)
    md = MD([{"decision": "abandon", "why": "looks dead"}], [{"decision": "abandon", "why": "dead"}])
    out, _ = _develop(md, s, monkeypatch)
    assert out is None and s.tally["audits"] == 1 and s.tally["rescued"] == 0


def test_the_developer_keeps_its_own_steps_when_the_screen_keeps_refining(monkeypatch):
    s = _screen(monkeypatch=monkeypatch)
    refine = {"decision": "refine", "spec": {"market": "m", "side": "no"}, "change": "x"}
    md = MD([refine] * 10, [refine, refine, {"decision": "commit", "why": "ok"}])
    out, _ = _develop(md, s, monkeypatch, steps=8)  # 7 turns: screen 4, developer 3
    assert out is not None
    assert md.seen == ["screen"] * 4 + ["dev"] * 3


def test_an_unscreened_run_never_touches_the_screen(monkeypatch):
    md = MD([], [{"decision": "commit", "why": "ok"}])
    out, _ = _develop(md, rs.Screen(run_id=7), monkeypatch)
    assert out is not None and md.seen == ["dev"]


def test_arms_split_by_run_and_the_screen_is_one_tier_cheaper(monkeypatch):
    monkeypatch.setattr(rs, "SCREEN_MODEL", "auto")
    monkeypatch.setattr(rs, "SCREEN_SHARE", 0.5)
    arms = [rs.screen_choice(i, "opus-4-6") for i in range(1, 401)]
    on = [a for a in arms if a is not None]
    assert 140 < len(on) < 260  # about half, stable per run id
    assert {a.key for a in on} == {"sonnet-4-6"}
    assert [rs.screen_choice(i, "opus-4-6") for i in range(1, 401)] == arms
    sonnet_run = next(i for i in range(1, 400) if rs.in_screen_arm(i))
    assert rs.screen_choice(sonnet_run, "sonnet-4-5").key == "haiku-4-5"
    assert rs.screen_choice(sonnet_run, "haiku-4-5") is None  # nothing cheaper in the tier map
    monkeypatch.setattr(rs, "SCREEN_MODEL", "off")
    assert rs.screen_choice(sonnet_run, "opus-4-6") is None


def test_the_run_card_prices_screen_tokens_at_the_screen_rate_and_the_watch_splits_arms():
    run = {"id": 1, "model": "opus-4-6", "status": "succeeded", "input_tokens": 1_000_000,
           "output_tokens": 100_000, "hypotheses_tried": 8}
    full = rsi.run_card(run, [])["cost_usd"]
    s = rs.Screen(run_id=1, choice=rs.catalog.get("sonnet-4-6"), model=lambda *a: None)
    s.usage.add({"input_tokens": 800_000, "output_tokens": 80_000})
    s.drain()
    s.tally.update(screened_out=6, handed_over=2, audits=2, rescued=1)
    ev = [{"kind": "verdict", "message": s.message(), "data": s.summary()}]
    card = rsi.run_card(run, ev)
    assert card["arm"] == "screen" and card["screen"]["rescued"] == 1
    assert card["cost_usd"] < full * 0.75  # 80% of the tokens at Sonnet's 60% of Opus's price
    control = rsi.run_card(dict(run, id=2), [{"kind": "verdict", "message": "",
                                               "data": rs.Screen(run_id=2).summary()}])
    assert control["cost_usd"] == full and control["arm"] == "control"
    ab = screen_ab([card, control])
    assert ab["screen"]["ideas_per_usd"] > ab["control"]["ideas_per_usd"]
    assert ab["screen"]["rescued"] == 1 and "rescued" not in ab["control"]

