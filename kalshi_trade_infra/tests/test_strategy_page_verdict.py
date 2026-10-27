"""A strategy's page never says it passed when it didn't clear every check.

A validation pass keeps the status "passed" when the diversification check after the one-time holdout
then holds it back (no 'forward' deployment-candidate row): its why_failed now names that check, and
the strategy it repeats by title, never by experiment id. A pass the autopilot puts on paper itself is
marked autopilot_paper, judged as if the switch were on so the page can follow a flip. Display only."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from app import server
from app.research import agent, gatekeeper
from app.services import gate_explain as ge
from app.web.routes import strategies as strategy_routes

REASON = "max |corr| 0.93 to deployed experiment 77 exceeds %.2f" % gatekeeper.CORR_MAX
FV = gatekeeper.Classification.FORWARD_VALIDATED.value


def test_a_held_back_line_names_the_strategy_it_repeats_and_never_its_id():
    assert ge.corr_peer(REASON) == 77 and ge.corr_peer("no validation return series recorded") is None
    [ln] = ge.held_back(REASON, "BTC <fade>")
    assert ln["gate"] == "diversification" and ln["label"] == "Too similar to “BTC <fade>”"
    assert ln["measured"] == "a 0.93 correlation of daily results with “BTC <fade>”" and ln["needed"] == "0.80 or less"
    # No title found: the gate's own words. No reason recorded: said so, never a guessed figure.
    assert ge.held_back(REASON)[0]["label"] == "Too similar to a strategy you already run"
    [blind] = ge.held_back(None)
    assert blind["gate"] == "diversification" and blind["measured"].startswith("not recorded")
    assert ge.held_back("no validation return series recorded for this experiment")[0]["measured"].startswith("not recorded")
    assert not any("77" in v or "experiment" in v for ln in ge.held_back(REASON, "X") + ge.held_back(None) for v in ln.values())


def _ctx(user=None):
    return server.Ctx(SimpleNamespace(cursor=lambda: object()), user or {"id": 7, "autopilot": 0}, ("4",), {}, {}, SimpleNamespace())


def _row(**o):
    row = {"id": 4, "run_id": 1, "parent_id": None, "market": "btc15m", "title": "Fade, tighter", "thesis": "t", "status": "passed",
           "created_at": None, "result": {"classification": "statistically_supported"}, "spec": {"sizing": {"stake": 5}, "side": "yes"},
           "experiment_id": 3, "direction": "custom"}
    row.update(o)
    return row


def _exp(holdout_cls, promoted):
    return {"classification": "deployment_candidate" if promoted else holdout_cls, "min_sample": 60, "promoted": promoted, "folds": [],
            "validation": {"classification": "statistically_supported", "n_trades": 150, "p_value": 0.01, "mean_net_return": 0.026,
                           "ci_lo": 0.004, "ci_hi": 0.05, "dsr": 0.8, "placebo_p": 0.01, "fdr_alpha_i": 0.05},
            "holdout": {"classification": holdout_cls, "n_trades": 64, "p_value": 0.01 if holdout_cls == FV else 0.48,
                        "mean_net_return": 0.024 if holdout_cls == FV else -0.003, "ci_lo": 0.003 if holdout_cls == FV else -0.03,
                        "ci_hi": 0.045, "consumed": True}}


def _page(monkeypatch, row, exp, event=None, deps=(), candidate=True, chat=()):
    reads = []
    strategies = {4: row, 8: _row(id=8, title="Fade", status="passed")}
    titles = {77: "Fade"}
    monkeypatch.setattr(server.specmod, "describe", lambda spec: [])
    monkeypatch.setattr(strategy_routes, "_experiment_block", lambda *a: exp)
    monkeypatch.setattr(server.repo, "list_deployments_for_display", lambda *a, **k: list(deps))
    monkeypatch.setattr(server.repo, "list_deployments", lambda *a, **k: list(deps))
    monkeypatch.setattr(server.repo, "positions_for_strategy", lambda *a: [])
    monkeypatch.setattr(server.repo, "removed_deployments", lambda *a, **k: [])
    monkeypatch.setattr(server.repo, "get_strategy", lambda cur, uid, sid: dict(strategies[sid]) if sid in strategies else None)
    monkeypatch.setattr(server.repo, "forward_verdicts", lambda cur, run_id: reads.append(run_id) or ({event["title"]: event} if event else {}))
    monkeypatch.setattr(server.repo, "chat_lines_like", lambda cur, uid, role, like, limit=50: reads.append(("chat", role)) or list(chat))
    monkeypatch.setattr(strategy_routes.research_repo, "strategy_titles", lambda cur, uid, eids: {e: titles[e] for e in eids if e in titles})
    monkeypatch.setattr(strategy_routes, "_demo_health", lambda *a, **k: None)
    for name in ("_demo_key_back", "_paper_books"):
        monkeypatch.setattr(strategy_routes, name, lambda *a, **k: None)
    monkeypatch.setattr(strategy_routes, "_deployment_out", lambda d, *a, **k: d)
    monkeypatch.setattr(strategy_routes, "_book_totals", lambda deps: {})
    monkeypatch.setattr(strategy_routes, "_backtest_checks", lambda *a, **k: {})
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: candidate)
    return server.get_strategy(_ctx()), reads


def test_a_holdout_pass_the_diversification_check_held_back_says_so_by_name(monkeypatch):
    ev = {"title": "Fade, tighter", "phase": "forward", "marginal_ok": False, "reason": REASON}
    out, reads = _page(monkeypatch, _row(), _exp(FV, promoted=False), event=ev, candidate=False)
    assert reads == [1] and out["verdict"] == "held_back"
    assert [(ln["gate"], ln["label"]) for ln in out["why_failed"]] == [("diversification", "Too similar to “Fade”")]
    assert "77" not in str(out["why_failed"]) and out["autopilot_paper"] is False
    # Its run logged nothing (an older run): the line still says it was held back, without a figure.
    out, _ = _page(monkeypatch, _row(), _exp(FV, promoted=False), event=None, candidate=False)
    assert out["why_failed"][0]["label"] == "Too similar to a strategy you already run"
    assert out["why_failed"][0]["measured"].startswith("not recorded")


def test_a_promoted_pass_a_missed_holdout_and_a_shared_copy_read_their_own_record(monkeypatch):
    out, reads = _page(monkeypatch, _row(), _exp(FV, promoted=True))
    assert out["why_failed"] == [] and reads == []
    # A missed holdout keeps the holdout's own lines (gate_explain.for_strategy); no event is read.
    out, reads = _page(monkeypatch, _row(), _exp("rejected", promoted=False), candidate=False)
    assert out["why_failed"][0]["label"] == "The edge could be luck on the locked holdout" and reads == []
    assert out["verdict"] == "missed_final"
    # A shared copy's run is someone else's: held back, but no event read and no title of theirs.
    out, reads = _page(monkeypatch, _row(shared_from_user_id=9), _exp(FV, promoted=False), candidate=False)
    assert reads == [] and out["why_failed"][0]["gate"] == "diversification"
    # A rejected strategy is unchanged.
    out, reads = _page(monkeypatch, _row(status="rejected"), _exp(FV, promoted=False), candidate=False)
    assert reads == [] and all(ln["gate"] != "diversification" for ln in out["why_failed"]) and "verdict" not in out


def test_a_pass_the_autopilot_puts_on_paper_is_marked_whatever_the_switch(monkeypatch):
    # Off now: still marked, judged as if on, so the page can show it the moment the switch flips.
    out, _ = _page(monkeypatch, _row(), _exp(FV, promoted=True))
    assert out["autopilot_paper"] is True
    # On paper already, or ran on paper before (stopping it was a decision): not marked.
    for dep in ({"id": 1, "strategy_id": 4, "mode": "paper", "status": "running"}, {"id": 1, "strategy_id": 4, "mode": "paper", "status": "stopped"}):
        out, _ = _page(monkeypatch, _row(), _exp(FV, promoted=True), deps=[dep])
        assert out["autopilot_paper"] is False
    out, _ = _page(monkeypatch, _row(), _exp(FV, promoted=False), candidate=False)
    assert out["autopilot_paper"] is False


AT = datetime(2026, 10, 26, 4, 0, 0)


def _probation(paper_cls):
    """A validation near miss (too few trades) that went on paper probation and had its one paper judgment."""
    exp = _exp(FV, promoted=False)
    exp.update(classification=paper_cls, holdout=None,
               validation={"classification": "inconclusive", "n_trades": 18, "p_value": None, "net_pnl": 4.1},
               paper={"classification": paper_cls, "n_trades": 60, "p_value": 0.01, "mean_net_return": 0.021,
                      "ci_lo": 0.002, "ci_hi": 0.04, "verdict_at": AT})
    return exp


def _held_line(title, reason):
    return ("Paper forward gate: %s passed on paper (60 paper trades, p=0.010, +2.1%% per trade) but stays off the "
            "candidate list: %s." % (title, reason))


def test_a_probation_strategy_held_back_after_passing_on_paper_says_so_not_its_validation_miss(monkeypatch):
    # The autopilot chat is the one record of the reason: the first line for it at or after its paper
    # judgment, not an older line of a strategy with the same title nor another strategy's line.
    chat = [{"content": _held_line("Fade, tighter", REASON), "created_at": AT + timedelta(seconds=1)},
            {"content": _held_line("Other idea", "max |corr| 0.99 to deployed experiment 5 exceeds 0.80"), "created_at": AT},
            {"content": _held_line("Fade, tighter", "no validation return series recorded"), "created_at": AT - timedelta(days=3)}]
    out, reads = _page(monkeypatch, _row(status="failed"), _probation(FV), candidate=False, chat=chat)
    assert out["verdict"] == "held_back" and reads == [("chat", "system")]
    assert [(ln["gate"], ln["label"]) for ln in out["why_failed"]] == [("diversification", "Too similar to “Fade”")]
    assert out["why_failed"][0]["measured"] == "a 0.93 correlation of daily results with “Fade”"
    assert "77" not in str(out["why_failed"]) and out["experiment"]["paper"]["classification"] == FV
    # No line recorded: still held back after passing on paper, the reason said to be unrecorded.
    out, _ = _page(monkeypatch, _row(status="failed"), _probation(FV), candidate=False)
    assert out["why_failed"][0]["measured"].startswith("not recorded, but it passed its one judgment on paper")
    # A paper judgment it missed, or a promotion, leaves the page as it was: its validation miss, no verdict.
    out, reads = _page(monkeypatch, _row(status="failed"), _probation("rejected"), candidate=False)
    assert "verdict" not in out and reads == [] and out["why_failed"][0]["gate"] == "sample_size"
    out, reads = _page(monkeypatch, _row(), dict(_probation(FV), promoted=True))
    assert "verdict" not in out and reads == [] and out["why_failed"] == []
