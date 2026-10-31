"""Research scoreboard: the funnel, spend and death reasons the self-improving loop measures."""
import json

from app.research import rsi

# Drop reasons as the proposer actually wrote them (run 2613, high_ny, 2026-10-24), shortened.
REAL_2613 = [
    ("The research fold disproves the core mechanism. Trades 94% in longshots <15c with 5% win rate "
     "and -87c/trade", "edge"),
    ("The thesis requires conditioning on obs_high_f ... but obs_high_f is not available as a strategy "
     "feature for this market.", "pipeline"),
    ("0 trades on research fold indicates the bias-corrected forecast never diverges meaningfully from "
     "market mid", "spec"),
    ("The mechanism requires real-time temperature observation data (obs_high_f). I cannot confirm this "
     "feature is available in the research fold.", "pipeline"),
    ("it loses $25.86 on 59 trades in-sample with an 18.6% win rate (worse than random)", "edge"),
    ("The thesis hinges on fcst_high_f, which is either unavailable or unpopulated on high_ny", "pipeline"),
]


def test_drop_reasons_split_pipeline_failures_from_market_verdicts():
    assert [rsi.classify_drop(why)[1] for why, _ in REAL_2613] == [k for _, k in REAL_2613]
    assert rsi.classify_drop("no settled contracts for kxncaafspread") == ("no_data", "pipeline")
    assert rsi.classify_drop("a 2c edge is below the fee floor here") == ("fee_floor", "edge")
    assert rsi.classify_drop("the challenger thought it was boring") == ("other", "other")
    assert rsi.classify_drop(None) == ("other", "other")


def test_btc_drop_reasons_that_cite_the_playbook_or_the_research_fold_stats_are_classified():
    # Prod 2026-10-27/28: ~20% of BTC drops were "other"; these are shortened real reasons.
    for why, tag in (
            ("Vol-mispricing is a documented dead end on this market (22+ prior failures, t-stats -0.82 to -7.86)",
             "known_dead"),
            ("This thesis occupies an exhaustively-mined region (side=yes, price 0.90-0.98)", "known_dead"),
            ("t=0.34 with 86% of profit in 3 events shows no repeatable edge", "no_signal"),
            ("Research t=0.62 is far below the ~3 threshold needed", "no_signal"),
            ("With 462 updates/sec and 4ms median book_age, MMs reprice faster than any detectable window",
             "no_signal"),
            ("The thesis lacks a sound economic mechanism: vol_60m is publicly observable", "wrong_fit"),
            ("The cross-strike mechanism requires multiple strikes, but this market has median 1 contract per event",
             "wrong_fit"),
            ("The spec doesn't actually test the divergence thesis (it only checks ETH>0)", "wrong_fit")):
        assert rsi.classify_drop(why)[0] == tag, why


def test_families_group_cities_and_categories():
    assert rsi.family("high_ny") == "weather-high"
    assert rsi.family("btc15m") == "crypto"
    assert rsi.family("nope") == "unknown"


def _ev(message, **data):
    return {"kind": "verdict", "message": message, "data": data}


EVENTS = [
    {"kind": "step", "message": "Loading", "data": {}},
    _ev('DROPPED "A" (no candidate) - x', status="abandoned", why=REAL_2613[1][0]),
    _ev('DROPPED "B" (no candidate) - x', status="abandoned", why=REAL_2613[4][0]),
    _ev("REJECTED (challenger) - C: no mechanism", status="rejected", strategy_id=3),
    _ev("NOT TESTED - D: underpowered. No validation budget spent.", status="rejected", strategy_id=4, power=0.1),
    _ev("REJECTED - E: not a finalist, so never tested on unseen data", status="rejected", strategy_id=5),
    _ev("REJECTED - F: validation verdict", status="rejected", classification="inconclusive", strategy_id=6),
    _ev("PASSED - G: validation verdict", status="passed", classification="statistically_supported", strategy_id=7),
    _ev("G: one-time holdout", phase="holdout", classification="forward_validated"),
    _ev("G: diversification gate PASSED", phase="forward", classification="deployment_candidate"),
]
RUN = {"id": 9, "user_id": 2, "market": "high_ny", "status": "succeeded", "model": None,
       "hypotheses_tried": 7, "input_tokens": 1_000_000, "output_tokens": 100_000,
       "created_at": "2026-10-24 18:00:00"}


def test_run_card_reads_the_whole_funnel():
    c = rsi.run_card(RUN, EVENTS)
    assert (c["explored"], c["developed"], c["dropped"]) == (7, 5, 2)
    assert (c["challenger_rejected"], c["underpowered"], c["not_finalist"]) == (1, 1, 1)
    assert (c["gated"], c["passed"], c["holdout_passed"], c["deploy_candidates"]) == (2, 1, 1, 1)
    assert c["deaths"] == {"feature_unavailable": 1, "loses": 1}
    assert c["death_kinds"] == {"pipeline": 1, "edge": 1}
    assert c["family"] == "weather-high" and c["cost_usd"] > 0


def test_scoreboard_rolls_up_efficiency_per_family_and_day():
    a = rsi.run_card(RUN, EVENTS)
    b = rsi.run_card(dict(RUN, id=10, market="btc15m", hypotheses_tried=0, created_at="2026-10-25 01:00:00"),
                     [_ev("DROPPED", status="abandoned", why="0 trades")] * 4)
    board = rsi.scoreboard([a, b])
    t = board["total"]
    assert t["runs"] == 2 and t["explored"] == 11 and t["gated"] == 2 and t["passed"] == 1
    assert t["gate_reach_rate"] == round(2 / 11, 3)
    assert t["pipeline_death_share"] == round(1 / 6, 3)
    assert t["passed_per_100usd"] == round(100.0 / t["cost_usd"], 2)
    assert set(board["families"]) == {"weather-high", "crypto"}
    assert [d["day"] for d in board["days"]] == ["2026-10-24", "2026-10-25"]
    assert rsi.scoreboard([])["total"]["pass_rate"] is None
    fixes = board["fix_list"]
    assert fixes == [{"tag": "feature_unavailable", "market": "high_ny", "family": "weather-high", "count": 1,
                      "latest_run": 9, "example": REAL_2613[1][0], "title": ""}]


class _Cur:
    def __init__(self):
        self.sql = []
        self._rows = []

    def execute(self, sql, args=None):
        self.sql.append((sql, args))
        if "FROM app_credit_ledger" in sql:  # repo.runs_spent: what run 9's usage rows debited
            self._rows = [{"run_id": 9, "s": 3.124999}]
        elif "FROM app_agent_runs" in sql:
            self._rows = [dict(RUN)]
        else:
            self._rows = [{"run_id": 9, "kind": e["kind"], "message": e["message"],
                           "data_json": json.dumps(e["data"])} for e in EVENTS if e["kind"] == "verdict"]

    def fetchall(self):
        return self._rows


def test_load_scoreboard_reads_runs_then_their_verdicts():
    cur = _Cur()
    board = rsi.load_scoreboard(cur, days=3, user_id=2)
    assert board["total"]["passed"] == 1 and board["cards"][0]["run_id"] == 9
    assert cur.sql[0][1] == [3, 2] and "kind='verdict'" in cur.sql[1][0]


def test_the_boards_spend_is_the_ledger_of_its_sessions_not_their_tokens_repriced(monkeypatch):
    # The Research page's "Is research getting better?" card read Spend $0.00 ($0.00 per idea) over five
    # sessions whose rows read $12.35, $45.68, $8.77, $20.00 and under $0.01 (walk 2026-10-31): rsi re-prices
    # the runs' stored tokens. The card's figure is their ledger debits, summed exactly, then to the cent.
    from app import server
    from app.web.routes import research as research_routes
    board = {"total": {"runs": 5, "cost_usd": 0.0, "explored": 23},
             "cards": [{"run_id": i, "cost_usd": 0.0} for i in (2, 4, 5, 7, 8)]}
    asked = []

    def runs_spent(cur, uid, ids):
        asked.append((uid, list(ids)))
        return {2: 12.345678, 4: 45.678912, 5: 0.004213, 7: 8.765432, 8: 20.000004}
    monkeypatch.setattr(server.repo, "runs_spent", runs_spent)
    research_routes._board_ledger_spend(object(), 7, board)
    assert board["total"]["cost_usd"] == 86.79 and asked == [(7, [2, 4, 5, 7, 8])]
    assert [c["cost_usd"] for c in board["cards"]] == [0.0] * 5  # the cards themselves are rsi's, untouched
    empty = {"total": {"runs": 0, "cost_usd": 0.0}, "cards": []}
    research_routes._board_ledger_spend(object(), 7, empty)  # no sessions: nothing read
    assert empty["total"]["cost_usd"] == 0.0 and len(asked) == 1


def test_scoreboard_leaves_out_the_seeded_example_session():
    # A brand-new account's only session is the example it was seeded with: the board counted it as
    # research the user ran ("2 ideas tried, 1 session, $0.00 spent").
    from app.adapters.db.strategy_repository import DEMO_DIRECTION
    cur = _Cur()
    rsi.recent_runs(cur, days=14, user_id=2)
    sql = cur.sql[0][0]
    assert "(direction IS NULL OR direction <> '%s')" % DEMO_DIRECTION in sql


def test_scoreboard_endpoint_is_scoped_to_the_user_and_clamps_days(monkeypatch):
    from types import SimpleNamespace
    from app import server
    from app.research import rsi_playbook
    cur = _Cur()
    monkeypatch.setattr(rsi_playbook, "summary", lambda c, uid: [{"family": "weather-high", "version": 1}])
    from app.web import caches
    monkeypatch.setattr(caches, "_SHARED", {})
    ctx = SimpleNamespace(cur=cur, uid=2, query={"days": "999"})
    board = server.research_scoreboard(ctx)
    assert board["days_back"] == 60 and board["total"]["runs"] == 1
    # Its Spend is what those sessions took from credits (their ledger rows, as each session's Cost), to the
    # cent: not their stored tokens re-priced.
    assert board["total"]["cost_usd"] == 3.12
    assert any("FROM app_credit_ledger" in q and "run_id IN" in q and a[-1] == 2 for q, a in cur.sql)
    assert board["playbooks"] == [{"family": "weather-high", "version": 1}]
    assert cur.sql[0][1] == [60, 2]
    # memoized per (user, days): a second request inside the TTL reads nothing (prod p50 was 4.4s)
    n = len(cur.sql)
    assert server.research_scoreboard(ctx) is board and len(cur.sql) == n
    other = _Cur()
    server.research_scoreboard(SimpleNamespace(cur=other, uid=3, query={"days": "60"}))
    assert other.sql and other.sql[0][1] == [60, 3]          # another user is never served user 2's board
    assert any(r[0] == "GET" and r[1].pattern == "^/api/research/scoreboard$" and r[3] for r in server.ROUTES)


def _paper_setup(monkeypatch, deps, progress, assignments, ready_ids=()):
    from app.research import agent
    from app import repository as repo
    monkeypatch.setattr(repo, "list_deployments", lambda cur, uid, include_stopped=False: deps)
    monkeypatch.setattr(repo, "paper_progress", lambda cur, uid, ids: {k: v for k, v in progress.items() if k in ids})
    monkeypatch.setattr(agent, "paper_evidence", lambda cur, uid, sid: {"ready": sid in ready_ids})

    class Cur:
        def __init__(self):
            self.sql = []

        def execute(self, sql, args=None):
            self.sql.append((sql, args))
            self._rows = [{"strategy_id": s, "playbook_id": p} for s, p in assignments.items() if s in args]

        def fetchall(self):
            return self._rows
    return Cur()


def _dep(sid, market, mode="paper", pnl=10.0, trades=10, stuck=None):
    return {"strategy_id": sid, "market": market, "mode": mode, "scan": {"blocked_at": stuck} if stuck else None,
            "result": {"out_of_sample": {"pnl": pnl, "trades": trades}}}


def test_paper_outcomes_score_families_and_playbooks_on_realistic_fills(monkeypatch):
    deps = [_dep(1, "high_ny"), _dep(1, "high_ny"), _dep(2, "high_ny", pnl=20.0), _dep(3, "btc15m", stuck="ret_5m > 0"),
            _dep(4, "high_ny", mode="live")]
    # 1: 40 trips, +$8 (backtest says $1/trade -> 20% realized); 2: 10 trips, -$5; 3: never traded.
    cur = _paper_setup(monkeypatch, deps, {1: (40, 8.0), 2: (10, -5.0)}, {1: 7, 2: 7, 3: 9}, ready_ids={1})
    out = rsi.paper_outcomes(cur, 2)
    high = out["families"]["weather-high"]
    assert high == {"strategies": 2, "trading": 2, "round_trips": 50, "net_pnl": 3.0,
                    "realization": round(3.0 / (40 * 1.0 + 10 * 2.0), 3), "live_ready": 1, "stuck_on": {},
                    "behind_pace": []}
    assert out["families"]["crypto"]["stuck_on"] == {"ret_5m > 0": 1}
    assert out["families"]["crypto"]["trading"] == 0 and out["families"]["crypto"]["realization"] is None
    assert out["by_playbook"][7]["round_trips"] == 50 and out["by_playbook"][9]["strategies"] == 1
    assert out["total"]["strategies"] == 3  # the live deployment is not paper evidence
    assert "app_rsi_assignments" in cur.sql[0][0] and cur.sql[0][1] == [1, 2, 3]
    lines = rsi.paper_outcomes_lines(out)
    assert lines[0].startswith("- crypto: 1 on paper, 0 trading") and "never fire" in lines[0]
    assert lines[0].endswith("untraded ones last stopped at: ret_5m > 0 (1)")
    assert "paper earns 5% of backtest per trade, 1 live-ready" in lines[1]


def test_paper_outcomes_skip_the_bootstrap_until_there_are_enough_trips(monkeypatch):
    from app.research import agent
    cur = _paper_setup(monkeypatch, [_dep(5, "high_ny")], {5: (3, 1.0)}, {})
    monkeypatch.setattr(agent, "paper_evidence", lambda *a: (_ for _ in ()).throw(AssertionError("too early")))
    out = rsi.paper_outcomes(cur, 2)
    assert out["total"]["live_ready"] == 0 and out["by_playbook"] == {}


def test_paper_outcomes_skip_the_live_check_for_a_strategy_down_on_paper(monkeypatch):
    """The scoreboard's live-ready count: a strategy down on its realistic trips fails paper_evidence's
    net check whatever else it reads, so its five reads and its bootstrap are skipped (20 paper
    strategies were 100 of the board's 118 statements and 11s of its cold read, measured 2026-10-26).
    Flat (exactly $0) and up still run the check: only a strict loss is certain to fail it."""
    from app.research import agent
    deps = [_dep(1, "high_ny"), _dep(2, "high_ny"), _dep(3, "high_ny")]
    cur = _paper_setup(monkeypatch, deps, {1: (40, -0.0001), 2: (40, 0.0), 3: (40, 6.0)}, {}, ready_ids={3})
    asked = []
    monkeypatch.setattr(agent, "paper_evidence", lambda c, uid, sid: asked.append(sid) or {"ready": sid == 3})
    out = rsi.paper_outcomes(cur, 2)
    assert asked == [2, 3] and out["total"]["live_ready"] == 1


def test_paper_pace_flags_a_running_strategy_far_below_its_research_rate(monkeypatch):
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 25, 18, 0)

    def dep(sid, per_day, hours, status="running"):
        return dict(_dep(sid, "kxnfl1hspread"), status=status, created_at=now - timedelta(hours=hours),
                    result={"in_sample": {"trades_per_day": per_day}})
    # 16.7/day for 12h predicts ~8 trips: 0 is p~0.0002 (behind); 6 is ordinary.
    assert rsi.paper_pace(dep(1, 16.7, 12), 0, now) == {"expected": 8.3, "hours": 12.0, "p": 0.0002, "behind": True}
    assert rsi.paper_pace(dep(1, 16.7, 12), 6, now)["behind"] is False
    # Too early to tell (expects ~0.8), paused, or no research pace: never flagged.
    assert rsi.paper_pace(dep(2, 4.24, 4.6), 0, now)["behind"] is False
    assert rsi.paper_pace(dep(3, 16.7, 12, status="paused"), 0, now)["behind"] is False
    assert rsi.paper_pace(_dep(4, "btc15m"), 0, now) is None

    monkeypatch.setattr(rsi, "paper_pace", lambda d, trips, now=None: {"expected": 8.3, "behind": not trips})
    cur = _paper_setup(monkeypatch, [_dep(81, "kxnfl1hspread"), _dep(82, "kxnfl1hspread")], {82: (9, 1.0)}, {})
    out = rsi.paper_outcomes(cur, 1)
    assert out["total"]["behind_pace"] == [(81, 0, 8.3)]
    assert rsi.paper_outcomes_lines(out)[0].endswith(
        "FAR BELOW RESEARCH PACE (check the live book shows what research saw): #81 0 trips vs ~8 expected")


def test_paper_eta_uses_its_own_pace_once_it_trades_and_never_beats_the_span():
    from datetime import datetime, timedelta
    now = datetime(2026, 10, 25, 18, 0)

    def dep(per_day, hours):
        return {"created_at": now - timedelta(hours=hours), "result": {"in_sample": {"trades_per_day": per_day}}}
    # Research pace until 3 trips: 4.24/day, 30 to go -> 7.1 days.
    assert rsi.paper_eta_days(dep(4.24, 5), 0, now) == 7.1
    # Own pace: 11 trips in 17.7h is ~14.9/day -> 19 to go in 1.3 days.
    assert rsi.paper_eta_days(dep(12.8, 17.7), 11, now) == 1.3
    # Enough trips already, but the record must also span 48h: 48 - 30 = 18h more.
    assert rsi.paper_eta_days(dep(50, 30), 40, now) == 0.8
    # Events bind once it trades: 11 trips but 2 events in 17.7h is 2.7 events/day -> 18 more in 6.6 days.
    assert rsi.paper_eta_days(dep(12.8, 17.7), 11, now, events=2) == 6.6
    assert rsi.paper_eta_days({"created_at": now}, 0, now) is None
    assert rsi.paper_eta_days({}, 5, now) is None


def test_paper_outcomes_with_nothing_on_paper_is_empty(monkeypatch):
    cur = _paper_setup(monkeypatch, [], {}, {})
    out = rsi.paper_outcomes(cur, 2)
    assert out["total"]["strategies"] == 0 and out["families"] == {} and cur.sql == []
    assert rsi.paper_outcomes_lines(out) == []

def test_trend_compares_the_newer_half_of_ideas_with_the_older_half():
    def card(i, explored, gated):
        return rsi.run_card(dict(RUN, id=i, hypotheses_tried=explored, created_at="2026-10-2%d 00:00:00" % i),
                            [_ev("PASSED", status="passed", classification="x", strategy_id=j) for j in range(gated)])
    assert rsi.trend([card(1, 5, 0), card(2, 5, 1)]) is None          # too few ideas to compare
    t = rsi.trend([card(1, 10, 0), card(2, 6, 1), card(3, 10, 3), card(4, 6, 2)])
    assert (t["before"]["explored"], t["after"]["explored"]) == (16, 16)
    assert (t["before"]["gate_reach_rate"], t["after"]["gate_reach_rate"], t["better"]) == (0.062, 0.312, True)
    assert rsi.scoreboard([card(1, 10, 0), card(2, 10, 2)])["trend"]["better"] is True


def test_the_old_other_bucket_splits_into_reasons_the_loop_can_act_on():
    # Real drop reasons from 2026-10-22..24 that used to land in "other".
    cases = {
        "The GBM model architecture is fundamentally incompatible with NFL outcome markets": ("wrong_fit", "fit"),
        "The core model architecture is circular: a logistic classifier fit on [mid, tte_min]": ("wrong_fit", "fit"),
        "The thesis requires detecting game state (trailing vs. leading, score differential)":
            ("missing_context", "pipeline"),
        "but no live game-state features are available in this system": ("missing_context", "pipeline"),
        "this market has too few extreme-price settled contracts in the research window": ("thin_sample", "spec"),
        "the research data shows all snapshots have tte_min >= 215 minutes": ("thin_sample", "spec"),
        "The research-fold result shows zero predictive power: 206 trades with 0.5% win rate": ("no_signal", "edge"),
        "Research fold shows 0/8 wins across all price and side regimes": ("no_signal", "edge"),
    }
    for why, want in cases.items():
        assert rsi.classify_drop(why) == want, why
    # the original tags still win where they matched before
    assert rsi.classify_drop("taker_yes_vol_60s is not populated, so it is fundamentally untestable")[0] == \
        "feature_unavailable"
    assert rsi.classify_drop("the spec took 0 trades: too few rows")[0] == "zero_trades"
    assert "fit" in rsi.KINDS
