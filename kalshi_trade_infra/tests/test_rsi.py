"""Research scoreboard: the funnel, spend and death reasons the self-improving loop measures."""
import json

from app import rsi

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
        if "FROM app_agent_runs" in sql:
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


def test_scoreboard_endpoint_is_scoped_to_the_user_and_clamps_days(monkeypatch):
    from types import SimpleNamespace
    from app import server
    from app import rsi_playbook
    cur = _Cur()
    monkeypatch.setattr(rsi_playbook, "summary", lambda c, uid: [{"family": "weather-high", "version": 1}])
    ctx = SimpleNamespace(cur=cur, uid=2, query={"days": "999"})
    board = server.research_scoreboard(ctx)
    assert board["days_back"] == 60 and board["total"]["runs"] == 1
    assert board["playbooks"] == [{"family": "weather-high", "version": 1}]
    assert cur.sql[0][1] == [60, 2]
    assert any(r[0] == "GET" and r[1].pattern == "^/api/research/scoreboard$" and r[3] for r in server.ROUTES)


def _paper_setup(monkeypatch, deps, progress, assignments, ready_ids=()):
    from app import agent
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


def _dep(sid, market, mode="paper", pnl=10.0, trades=10):
    return {"strategy_id": sid, "market": market, "mode": mode,
            "result": {"out_of_sample": {"pnl": pnl, "trades": trades}}}


def test_paper_outcomes_score_families_and_playbooks_on_realistic_fills(monkeypatch):
    deps = [_dep(1, "high_ny"), _dep(1, "high_ny"), _dep(2, "high_ny", pnl=20.0), _dep(3, "btc15m"),
            _dep(4, "high_ny", mode="live")]
    # 1: 40 trips, +$8 (backtest says $1/trade -> 20% realized); 2: 10 trips, -$5; 3: never traded.
    cur = _paper_setup(monkeypatch, deps, {1: (40, 8.0), 2: (10, -5.0)}, {1: 7, 2: 7, 3: 9}, ready_ids={1})
    out = rsi.paper_outcomes(cur, 2)
    high = out["families"]["weather-high"]
    assert high == {"strategies": 2, "trading": 2, "round_trips": 50, "net_pnl": 3.0,
                    "realization": round(3.0 / (40 * 1.0 + 10 * 2.0), 3), "live_ready": 1}
    assert out["families"]["crypto"]["trading"] == 0 and out["families"]["crypto"]["realization"] is None
    assert out["by_playbook"][7]["round_trips"] == 50 and out["by_playbook"][9]["strategies"] == 1
    assert out["total"]["strategies"] == 3  # the live deployment is not paper evidence
    assert "app_rsi_assignments" in cur.sql[0][0] and cur.sql[0][1] == [1, 2, 3]
    lines = rsi.paper_outcomes_lines(out)
    assert lines[0].startswith("- crypto: 1 on paper, 0 trading") and "never fire" in lines[0]
    assert "paper earns 5% of backtest per trade, 1 live-ready" in lines[1]


def test_paper_outcomes_skip_the_bootstrap_until_there_are_enough_trips(monkeypatch):
    from app import agent
    cur = _paper_setup(monkeypatch, [_dep(5, "high_ny")], {5: (3, 1.0)}, {})
    monkeypatch.setattr(agent, "paper_evidence", lambda *a: (_ for _ in ()).throw(AssertionError("too early")))
    out = rsi.paper_outcomes(cur, 2)
    assert out["total"]["live_ready"] == 0 and out["by_playbook"] == {}


def test_paper_outcomes_with_nothing_on_paper_is_empty(monkeypatch):
    cur = _paper_setup(monkeypatch, [], {}, {})
    out = rsi.paper_outcomes(cur, 2)
    assert out["total"]["strategies"] == 0 and out["families"] == {} and cur.sql == []
    assert rsi.paper_outcomes_lines(out) == []
