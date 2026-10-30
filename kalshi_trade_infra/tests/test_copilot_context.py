"""`_copilot_context` is what the autonomous autopilot KNOWS each review. These pin the three
memory/awareness blocks added so a review stops repeating dead ends, double-launching research, or
spending blind to its budget — and that a context-read hiccup degrades gracefully instead of failing
the whole review (every block is best-effort)."""
from app.research import agent


def _wire(monkeypatch, **over):
    r = agent.repo
    monkeypatch.setattr(r, "list_deployments", lambda cur, uid, **k: over.get("deps", []))
    # list_strategies is called for passed (spare), failed and rejected — branch on the status kwarg.
    strat = over.get("strat", {})
    monkeypatch.setattr(r, "list_strategies", lambda cur, uid, status=None, **k: strat.get(status, []))
    monkeypatch.setattr(r, "user_risk_config", lambda cur, uid: {})
    monkeypatch.setattr(r, "user_execution_config", lambda cur, uid: {})
    monkeypatch.setattr(r, "list_runs", over.get("list_runs", lambda cur, uid, limit=6: over.get("runs", [])))
    monkeypatch.setattr(r, "paper_balance", over.get("paper_balance", lambda cur, uid: 1000.0))
    monkeypatch.setattr(r, "demo_equity", lambda cur, uid: {"equity": 500.0})
    monkeypatch.setattr(r, "credit_balance", lambda cur, uid: 42.0)
    monkeypatch.setattr(r, "get_kalshi_dev_key", lambda cur, uid: over.get("dev_key"))


USER = {"id": 7}


def test_context_surfaces_recent_runs_dead_ends_and_budget(monkeypatch):
    _wire(monkeypatch,
          runs=[{"id": 11, "market": "btc15m", "status": "failed", "hypotheses_tried": 8,
                 "strategies_passed": 0, "prompt": "fade the longshot tails"}],
          strat={"failed": [{"title": "Tail fade v1", "market": "btc15m", "status": "failed"}],
                 "rejected": [{"title": "Momentum chase", "market": "ethdaily", "status": "rejected"}]})
    ctx = agent._copilot_context(None, USER)
    assert "run #11 on btc15m" in ctx and "fade the longshot tails" in ctx
    assert "Tail fade v1" in ctx and "Momentum chase" in ctx       # dead ends it must not re-propose
    assert "research credits $42.00 left" in ctx                   # budget awareness
    assert "paper cash $1000.00" in ctx


def test_context_degrades_when_a_memory_read_fails(monkeypatch):
    # A DB hiccup on the optional blocks must never fail the whole review — the core context still builds.
    def boom(*a, **k):
        raise RuntimeError("db dropped")
    _wire(monkeypatch, list_runs=boom, paper_balance=boom)
    ctx = agent._copilot_context(None, USER)
    assert "Autopilot is OFF." in ctx          # core block rendered
    assert "Markets you can research" in ctx    # trailing block rendered
    assert "Recent research lines" not in ctx   # failed block omitted, no crash
    assert "Account & budget" not in ctx


def test_finished_runs_say_whether_anything_passed(monkeypatch):
    # "succeeded" only means the run finished; reviews read it as "found an edge" and called two
    # empty runs "proven strategies ready for paper". The context spells out the outcome.
    _wire(monkeypatch, runs=[
        {"id": 21, "market": "high_ny", "status": "succeeded", "hypotheses_tried": 8, "strategies_passed": 0, "prompt": "a"},
        {"id": 22, "market": "nhl_game", "status": "succeeded", "hypotheses_tried": 5, "strategies_passed": 1, "prompt": "b"},
        {"id": 23, "market": "btc15m", "status": "running", "hypotheses_tried": 2, "strategies_passed": 0, "prompt": "c"}])
    ctx = agent._copilot_context(None, USER)
    assert "run #21 on high_ny [finished, NOTHING passed, no new strategy]" in ctx
    assert "run #22 on nhl_game [finished, 1 strategy passed]" in ctx
    assert "run #23 on btc15m [running]" in ctx
    assert "[succeeded]" not in ctx


def test_open_exposure_and_realized_pnl_come_book_by_book_never_summed(monkeypatch):
    # The engine applies the caps to one book at a time (user_open_exposure per mode), and the line summed
    # all three books: a reply could quote real and practice money as one figure. The realized figures are
    # the dashboard's (closed_book_totals), removed deployments and deleted strategies included.
    _wire(monkeypatch)
    expo = {"paper": {"n": 2, "notional": 3.0050}, "demo": {"n": 1, "notional": 2.1}, "live": {"n": 3, "notional": 0.9}}
    monkeypatch.setattr(agent.repo, "user_open_exposure", lambda cur, uid, mode=None: expo[mode])
    monkeypatch.setattr(agent.repo, "closed_book_totals", lambda cur, uid, day: (
        {"paper": (-0.745, 0.0), "demo": (0.6335, 0.0), "live": (1.5225, 0.0)}, {"paper": 12, "demo": 3, "live": 3}, {}))
    monkeypatch.setattr(agent.repo, "demo_equity", lambda cur, uid, realized=None: {"equity": 749.91, "realized": -0.09,
                                                                                  "before_reload": 0.73})
    ctx = agent._copilot_context(None, USER)
    assert "Aggregate open exposure" not in ctx
    assert "paper 2 open, $3.01 entry notional; demo 1 open, $2.10 entry notional; live 3 open, $0.90 entry notional" in ctx
    assert "paper -$0.75 over 12 closed trades, all time; demo -$0.09 since its last reload; live (real money) $1.52 over 3" in ctx
    assert "$6.01" not in ctx and "6 open" not in ctx  # no open figure across books


def test_context_counts_running_deployments_up_front(monkeypatch):
    dep = {"id": 75, "strategy_id": 5, "title": "t", "market": "sol_daily", "mode": "paper", "status": "running", "closed_trades": 0,
           "wins": 0, "realized_pnl": 0, "open_positions": 0, "spec": {}, "result": {}}
    _wire(monkeypatch, deps=[dep, dict(dep, id=74, status="paused")])
    ctx = agent._copilot_context(None, USER)
    assert "DEPLOYMENTS RUNNING RIGHT NOW: 1 on paper (#75), 0 live." in ctx
    _wire(monkeypatch)
    assert "DEPLOYMENTS RUNNING RIGHT NOW: 0 on paper, 0 live." in agent._copilot_context(None, USER)


# Prod 2026-10-26: user 1's plan said "Live: #83 ... trading real money" while #83 was paper.
PLAN_83 = {"deployments": "Live: #83 btc15m ($31.37 net, 4/6 wins) trading real money correctly. Paper: #90/89/88 "
                          "pooled z-score 5/5 wins, watching for decay before considering live promotion.",
           "posture": "Live autopilot ON; #83 promoted to real money and working. Toward live: 12/30 trades."}


def _dep(i, mode="paper", status="running"):
    return {"id": i, "strategy_id": i, "title": "t", "market": "btc15m", "mode": mode, "status": status,
            "closed_trades": 0, "wins": 0, "realized_pnl": 0, "open_positions": 0, "spec": {}, "result": {}}


def test_live_claim_ids_reads_claims_not_plans():
    assert agent.live_claim_ids(" ".join(PLAN_83.values())) == [83]
    assert agent.live_claim_ids("Live: #83, #84 and #85 working") == [83, 84, 85]
    assert agent.live_claim_ids("#91 is live now") == [91]
    assert agent.live_claim_ids("#90 needs 3 more trips before live promotion; #88 live gate: 2 checks left") == []
    assert agent.live_claim_ids("Live: none. Toward live: 12/30 trades") == []


def test_false_live_line_names_only_the_wrong_ids():
    deps = [_dep(83), _dep(90), _dep(12)]
    assert agent.false_live_line(" ".join(PLAN_83.values()), deps) == (
        "Correction: #83 trades paper, not real money. Live deployments right now: none.")
    assert agent.false_live_line("Live: #83", [_dep(83, mode="live")]) is None
    assert agent.false_live_line("Live: #999", deps) is None  # an id it doesn't own: nothing to correct
    two = agent.false_live_line("Live: #83 and #90", deps + [_dep(7, mode="live")])
    assert two == "Correction: #83, #90 trade paper, not real money. Live deployments right now: #7."


def test_context_fact_checks_a_plan_that_calls_paper_live(monkeypatch):
    _wire(monkeypatch, deps=[_dep(83), _dep(90)])
    monkeypatch.setattr(agent.repo, "autopilot_plan", lambda cur, uid: PLAN_83)
    ctx = agent._copilot_context(None, USER)
    assert "- FACT CHECK on this plan: Correction: #83 trades paper, not real money." in ctx
    monkeypatch.setattr(agent.repo, "autopilot_plan", lambda cur, uid: {"deployments": "Paper: #83 holding."})
    assert "FACT CHECK" not in agent._copilot_context(None, USER)


def test_a_reply_that_calls_paper_live_gets_a_correction(monkeypatch):
    from tests.test_app_agent import Conn, Store
    Store(monkeypatch)
    saved = []
    _wire(monkeypatch, deps=[_dep(83)])
    monkeypatch.setattr(agent.billing, "charge_usage", lambda *a: None)
    monkeypatch.setattr(agent.repo, "get_user", lambda cur, uid: {"id": uid})
    monkeypatch.setattr(agent.repo, "chat_messages", lambda *a, **k: [{"role": "user", "content": "how is it going?"}])
    monkeypatch.setattr(agent.repo, "add_chat", lambda *a: saved.append(a))
    reply = '{"reply":"**Live Trading:** #83 btc15m earning steadily on real money.","actions":[]}'
    agent.run_copilot(Conn(), {"id": 1, "user_id": 7, "kind": "chat"}, model=lambda s, m, on_delta=None: (reply, {"input_tokens": 10, "output_tokens": 5}))
    assert [a[2] for a in saved] == ["agent", "system"]
    # The chat line names the deployment by its title, never its row number (the review's context keeps the id).
    assert saved[1][3] == "Correction: “t” trades paper, not real money. Live deployments right now: none."


def test_the_customer_correction_names_titles_and_says_a_live_one_waits_while_live_trading_is_closed(monkeypatch):
    deps = [dict(_dep(83), title="Fade tails"), dict(_dep(90), title="Fade tails"), dict(_dep(7, mode="live"), title="Daily drift")]
    monkeypatch.setattr(agent, "_live_switch_open", lambda: False)
    said = agent.false_live_line("Live: #83 and #90", deps, customer=True)
    assert said == ("Correction: “Fade tails” trade paper, not real money. Live deployments right now: “Daily drift” "
                    "(waiting: live trading isn’t open yet).")
    assert "#" not in said
    monkeypatch.setattr(agent, "_live_switch_open", lambda: True)
    assert agent.false_live_line("Live: #83", deps, customer=True).endswith("Live deployments right now: “Daily drift”.")
    # The review's own fact check keeps the ids it acts on.
    assert agent.false_live_line("Live: #83", deps) == ("Correction: #83 trades paper, not real money. "
                                                         "Live deployments right now: #7.")


def test_budget_line_says_there_is_no_demo_key_instead_of_a_demo_figure(monkeypatch):
    # Tau's demo book starts at a capital Tau sets ($1,000 for a new account), so a review of an account with no
    # demo key read "demo equity $1000" and offered demo as if it were funded. Without a key nothing trades there.
    _wire(monkeypatch, paper_balance=lambda cur, uid: 250.0)
    monkeypatch.setattr(agent.repo, "demo_equity", lambda cur, uid: {"equity": 1000.0})
    ctx = agent._copilot_context(None, USER)
    assert "no Kalshi demo key connected, so demo can't trade until the user adds one on Funds" in ctx
    assert "demo equity" not in ctx and "$1000" not in ctx and "demo book" not in ctx
    assert "paper cash $250.00" in ctx and "research credits $42.00 left" in ctx  # the rest of the line stands
    # With a key the figure is named for what it is: Tau's own book, not cash at Kalshi.
    _wire(monkeypatch, dev_key={"key_id": "DEVK-1"})
    ctx = agent._copilot_context(None, USER)
    assert "Tau's demo book $500.00 (Tau's own figure, not the Kalshi demo account's cash)" in ctx
    assert "no Kalshi demo key" not in ctx and "demo equity" not in ctx


# -- the chat's figures are the pages' (money trust audit, 2026-10-30) ---------------------------------------


def test_each_deployment_line_says_deploys_figure_rounded_once_with_the_sign_before_the_dollar(monkeypatch):
    # "realized $%.2f" rounded the binary float: a demo deployment's exact $3.5250 read $3.52 beside Deploy's
    # $3.53 (money.cents), and a loss read "$-12.76" where every page says -$12.76.
    deps = [dict(_dep(5, mode="demo"), title="XRP trend rider", realized_pnl=3.5250,
                 result={"out_of_sample": {"pnl": -1.005, "trades": 40, "max_drawdown": 4.1}}),
            dict(_dep(6, status="paused"), title="ETH grind", realized_pnl=-12.7575)]
    _wire(monkeypatch, deps=deps)
    ctx = agent._copilot_context(None, USER)
    assert "demo record: 0 closed trades, 0 wins, realized $3.53, 0 open;" in ctx
    assert "realized -$12.76, 0 open;" in ctx and "$-" not in ctx
    assert "backtest unseen-data: pnl -$1.01 over 40 trades, max drawdown $4.10;" in ctx
    assert "backtest unseen-data: pnl n/a over None trades, max drawdown n/a;" in ctx  # no figure: never "$None"


def test_the_budget_line_rounds_paper_cash_and_credits_as_their_pages_do(monkeypatch):
    # Paper cash as the dashboard and Funds round it (money.cents); credits as Billing does (the ledger's six
    # places, then half up). "%.2f" of the floats said $994.64 and $1.00 beside the pages' $994.65 and $1.01.
    _wire(monkeypatch, paper_balance=lambda cur, uid: 994.645)
    monkeypatch.setattr(agent.repo, "credit_balance", lambda cur, uid: 1.005)
    ctx = agent._copilot_context(None, USER)
    assert "paper cash $994.65," in ctx and "research credits $1.01 left" in ctx


def test_the_realized_line_carries_each_books_day_as_the_dashboard_labels_it(monkeypatch):
    # The dashboard's books say "realized today (UTC)"; the context had only the all-time figures, so a reply
    # asked "what did I make today?" had nothing of the page's to quote. Each book apart, never summed.
    _wire(monkeypatch)
    monkeypatch.setattr(agent.repo, "user_open_exposure", lambda cur, uid, mode=None: {"n": 0, "notional": 0})
    monkeypatch.setattr(agent.repo, "closed_book_totals", lambda cur, uid, day: (
        {"paper": (5.2125, 10.0), "demo": (3.525, 3.435), "live": (2.0360, -7.3575)},
        {"paper": 11, "demo": 3, "live": 11}, {}))
    monkeypatch.setattr(agent.repo, "demo_equity", lambda cur, uid, realized=None: {"equity": 1003.53, "realized": 3.53,
                                                                                  "before_reload": 0.0})
    ctx = agent._copilot_context(None, USER)
    assert "Realized today (UTC, since 00:00 UTC): paper $10.00; demo $3.44; live (real money) -$7.36." in ctx
    assert "$2.64" not in ctx and "$6.08" not in ctx  # live + paper, live + paper + demo: never one figure


def test_a_running_live_deployment_waits_while_live_trading_is_closed_as_deploy_says(monkeypatch):
    # The dashboard counts a running live deployment as "placing no orders" while the server's live switch is
    # closed, and Deploy says it waits; the context said "1 live (#1)" and "status=running", so a reply asked
    # "how is my live strategy doing?" could say it trades real money.
    _wire(monkeypatch, deps=[_dep(1, mode="live"), _dep(4)])
    monkeypatch.setattr(agent, "_live_switch_open", lambda: False)
    ctx = agent._copilot_context(None, USER)
    assert ("DEPLOYMENTS RUNNING RIGHT NOW: 1 on paper (#4), 1 live (#1). Live trading isn’t open yet on this server, "
            "so the live ones place no orders: they are waiting, never trading real money.") in ctx
    assert "mode=live status=running (waiting: live trading isn’t open yet, so it places no orders) live record:" in ctx
    assert "mode=paper status=running paper record:" in ctx
    monkeypatch.setattr(agent, "_live_switch_open", lambda: True)
    ctx = agent._copilot_context(None, USER)
    assert "DEPLOYMENTS RUNNING RIGHT NOW: 1 on paper (#4), 1 live (#1).\n" in ctx
    assert "waiting" not in ctx and "mode=live status=running live record:" in ctx


def test_a_paused_deployment_says_why_so_a_reply_can_answer_why_it_paused(monkeypatch):
    # Deploy's row says why each one is paused; the context said only "status=paused", so "why did autopilot
    # pause it?" had an answer only while the engine's chat line was still in the transcript's last 20 lines.
    deps = [dict(_dep(6, status="paused"), status_reason="Lost $12.76, more than the $8.20 guard (2x its worst "
                                                             "backtest drawdown)."),
            dict(_dep(2, mode="live", status="paused"), status_reason="Kill switch"),
            dict(_dep(3, status="paused"), status_reason="Autopilot daily loss limit hit"),
            dict(_dep(7, status="paused"), status_reason="Traceback (most recent call last): boom"),
            dict(_dep(8, status="stopped"), status_reason="Tournament: retired, no trade in 9 days on paper: its "
                                                              "entry rule never fires on the live book")]
    _wire(monkeypatch, deps=deps)
    ctx = agent._copilot_context(None, USER)
    assert ("status=paused (why: Lost $12.76, more than the $8.20 guard (2x its worst backtest drawdown)) paper "
            "record:") in ctx
    assert "mode=live status=paused (why: the user pressed Kill) live record:" in ctx
    assert "status=paused (why: Autopilot daily loss limit hit) paper record:" in ctx
    assert 'deployment_id=7 "t" market=btc15m mode=paper status=paused paper record:' in ctx  # a raw error: no why
    assert "Traceback" not in ctx
    assert "status=stopped (why: The paper tournament removed it: no trade in 9 days, as its entry rule" in ctx
