"""Paper tournament: Thompson allocation of a virtual book across paper entrants (with a cash arm),
statistical retirement, forward-only book curve, the wider probation funnel, and paper-only caps."""
from datetime import datetime, timedelta

from app import agent, engine, tournament

NOW = datetime(2026, 10, 25, 12, 0, 0)
SPEC = {"side": "yes", "sizing": {"stake": 5.0, "max_positions": 20}}


def _entry(sid, returns, created=NOW - timedelta(days=1), **kw):
    return dict({"id": 100 + sid, "strategy_id": sid, "returns": list(returns), "created_at": created,
                 "title": "S%d" % sid, "market": "sol15m", "status": "running", "mode": "paper",
                 "spec": SPEC, "trips": [{"pnl": 5.0 * r} for r in returns]}, **kw)


def test_posterior_shrinks_a_lucky_start_toward_zero():
    mu, sd = tournament.posterior([1.0, 1.0, 1.0], pooled_sd=1.0)
    assert 0 < mu < 0.3 and sd > 0.2        # 3 wins at +100% of stake read as ~+23%, with wide doubt
    mu0, _ = tournament.posterior([], pooled_sd=1.0)
    assert mu0 == 0.0


def test_cash_holds_the_book_when_nothing_beats_zero():
    arms = tournament.allocate([_entry(1, [-0.3] * 40), _entry(2, [-0.2] * 40)], seed="t")
    cash = arms[-1]
    assert cash["strategy_id"] == 0 and cash["p_best"] > 0.95
    assert abs(sum(a["weight"] for a in arms) - 1.0) < 1e-9
    assert all(a["weight"] > 0 for a in arms)  # the exploration floor keeps every arm alive


def test_a_clear_winner_takes_most_of_the_book():
    arms = tournament.allocate([_entry(1, [0.25, 0.35] * 30), _entry(2, [0.3, -0.3] * 30), _entry(3, [])], seed="t")
    by = {a["strategy_id"]: a for a in arms}
    assert by[1]["weight"] > 0.6 and by[1]["p_positive"] > 0.99
    assert by[1]["weight"] > by[2]["weight"] and by[1]["weight"] > by[0]["weight"]
    assert tournament.allocate([_entry(1, [0.1, -0.1])], seed="x") == tournament.allocate([_entry(1, [0.1, -0.1])], seed="x")


def test_verdicts_need_enough_trips_or_a_week_of_silence():
    loser = _entry(1, [-0.4, -0.2, -0.3] * 12)
    arm = tournament.allocate([loser], seed="t")[0]
    assert "losing money" in tournament.verdict(loser, arm, NOW)
    early = _entry(2, [-0.4] * 10)
    assert tournament.verdict(early, tournament.allocate([early], seed="t")[0], NOW) is None
    quiet = _entry(3, [], created=NOW - timedelta(days=8))
    assert "never fires" in tournament.verdict(quiet, tournament.allocate([quiet], seed="t")[0], NOW)
    fresh = _entry(4, [], created=NOW - timedelta(days=2))
    assert tournament.verdict(fresh, tournament.allocate([fresh], seed="t")[0], NOW) is None
    # A paused entrant isn't trading, so it can't be dormant (prod 2026-10-25: a drawdown-paused
    # deployment from 10-15 was retired as "never fires"); a resumed one gets a fresh week.
    paused = _entry(5, [], created=NOW - timedelta(days=10), status="paused")
    assert tournament.verdict(paused, tournament.allocate([paused], seed="t")[0], NOW) is None
    resumed = _entry(6, [], created=NOW - timedelta(days=10), updated_at=NOW - timedelta(days=1))
    assert tournament.verdict(resumed, tournament.allocate([resumed], seed="t")[0], NOW) is None


def test_book_only_counts_trips_opened_after_a_weight_was_set():
    trips = [
        {"strategy_id": 1, "pnl": 10.0, "capital": 100.0, "opened_at": NOW - timedelta(hours=5), "closed_at": NOW - timedelta(hours=4)},
        {"strategy_id": 1, "pnl": 10.0, "capital": 100.0, "opened_at": NOW - timedelta(hours=2), "closed_at": NOW - timedelta(hours=1)},
        {"strategy_id": 2, "pnl": -4.0, "capital": 100.0, "opened_at": NOW - timedelta(hours=2), "closed_at": NOW - timedelta(minutes=30)},
    ]
    history = {1: [(NOW - timedelta(hours=3), 0.5)], 2: [(NOW - timedelta(hours=3), 0.25)]}
    b = tournament.book(trips, history)
    # trip 1 predates any weight: left out. $10 on a $100 entrant at 50% of $10k = +$500; -$4 at 25% = -$100.
    assert b["trips"] == 2 and b["pnl"] == 400.0 and b["max_drawdown"] == 100.0
    assert b["return_pct"] == 4.0
    assert b["daily"] == [(NOW.date().isoformat(), 400.0)]


def test_pooled_sample_reports_pace_and_eta(monkeypatch):
    monkeypatch.setattr(tournament, "_now", lambda: NOW)
    trips = [{"ret": 0.1 if i % 3 else -0.1, "pnl": 0.5, "closed_at": NOW - timedelta(hours=i)} for i in range(60)]
    p = tournament.pooled(trips)
    assert p["trips"] == 60 and p["per_day"] == 20.0 and p["days_to_target"] == 17.0
    assert 0 < p["mean_return"] < 0.1 and p["p_value"] < 0.05
    assert tournament.pooled([])["mean_return"] is None


class _Repo:
    def __init__(self, deps):
        self.deps, self.status = deps, []

    def list_deployments(self, cur, uid, include_stopped=False):
        return [d for d in self.deps if include_stopped or d["status"] != "stopped"]

    def set_deployment_status(self, cur, uid, did, status, why=None):
        self.status.append((did, status, why))
        return True

    def paper_round_trips(self, cur, uid, sid):
        d = next(d for d in self.deps if d["strategy_id"] == sid)
        return [{"pnl": 5.0 * r, "opened_at": NOW, "closed_at": NOW} for r in d["rets"]]

    def now_utc(self):
        return NOW


def _rebalance_patch(monkeypatch, deps, last=None, candidates=()):
    from app import repository
    fake = _Repo(deps)
    for name in ("list_deployments", "set_deployment_status", "paper_round_trips"):
        monkeypatch.setattr(repository, name, getattr(fake, name))
    monkeypatch.setattr(tournament, "_now", lambda: NOW)
    monkeypatch.setattr(tournament, "last_snapshot_ts", lambda cur, uid: last)
    saved = []
    monkeypatch.setattr(tournament, "save_snapshot", lambda cur, uid, ts, rows: saved.append(rows))
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: sid in candidates)
    return fake, saved


def _dep(sid, rets, status="running", reason=None, updated=NOW - timedelta(hours=2), mode="paper"):
    return {"id": 100 + sid, "strategy_id": sid, "title": "S%d" % sid, "market": "sol15m", "mode": mode,
            "status": status, "status_reason": reason, "updated_at": updated, "created_at": NOW - timedelta(days=2),
            "spec": SPEC, "rets": rets}


def test_rebalance_retires_losing_probation_entrants_but_never_candidates(monkeypatch):
    deps = [_dep(1, [-0.4, -0.2, -0.3] * 12), _dep(2, [-0.4, -0.2, -0.3] * 12), _dep(3, [0.2, 0.1] * 5)]
    fake, saved = _rebalance_patch(monkeypatch, deps, candidates=(2,))
    lines = tournament.rebalance(None, {"id": 1, "autopilot": True})
    assert [(d, s) for d, s, _ in fake.status] == [(101, "stopped")]
    assert "Retired paper entrant “S1”" in lines[0]
    rows = saved[0]
    assert {r["strategy_id"] for r in rows} == {2, 3, 0} and abs(sum(r["weight"] for r in rows) - 1) < 1e-9


def test_retiring_a_pooled_entrant_stops_every_leg(monkeypatch):
    legs = [dict(_dep(1, [-0.4, -0.2, -0.3] * 12), id=100 + i, market=m)
            for i, m in enumerate(("btc15m", "eth15m", "sol15m"))]
    legs[2]["rets"] = []  # the entrant's trips are read once per strategy
    fake, _ = _rebalance_patch(monkeypatch, legs)
    tournament.rebalance(None, {"id": 1, "autopilot": True})
    assert sorted(d for d, s, _ in fake.status if s == "stopped") == [100, 101, 102]


def test_rebalance_never_retires_a_paused_entrant(monkeypatch):
    deps = [_dep(1, [-0.4, -0.2, -0.3] * 12, status="paused", reason="By you"),
            dict(_dep(2, [], status="paused", reason="force-closed: drawdown 28.6% >= limit 25.0%"),
                 created_at=NOW - timedelta(days=10))]
    fake, saved = _rebalance_patch(monkeypatch, deps)
    assert tournament.rebalance(None, {"id": 1, "autopilot": True}) == [] and fake.status == []
    assert len(saved) == 1


def test_rebalance_resumes_a_position_stop_pause_but_not_a_drawdown_pause(monkeypatch):
    deps = [_dep(1, [-0.6], status="paused", reason="force-closed: position down 64.0% >= stop 40.0% of cost"),
            _dep(2, [-0.6], status="paused", reason="force-closed: drawdown 28.6% >= limit 25.0%"),
            _dep(3, [-0.6], status="paused", reason="force-closed: position down 50.0% >= stop 40.0% of cost",
                 updated=NOW - timedelta(minutes=10)),
            _dep(4, [-0.6], status="paused", reason="By you")]
    fake, _ = _rebalance_patch(monkeypatch, deps)
    lines = tournament.rebalance(None, {"id": 1, "autopilot": True})
    assert [(d, s) for d, s, _ in fake.status] == [(101, "running")]
    assert "Resumed paper entrant “S1”" in lines[0]


def test_rebalance_is_hourly_and_autopilot_only(monkeypatch):
    fake, saved = _rebalance_patch(monkeypatch, [_dep(1, [])], last=NOW - timedelta(minutes=20))
    assert tournament.rebalance(None, {"id": 1, "autopilot": True}) == [] and saved == []
    assert tournament.rebalance(None, {"id": 1, "autopilot": False}, force=True) == [] and saved == []
    tournament.rebalance(None, {"id": 1, "autopilot": True}, force=True)
    assert len(saved) == 1


def test_context_lines_tell_the_review_not_to_pause_entrants():
    st = {"entrants": [dict(strategy_id=1, title="S1", market="kxrain", weight=0.6, trips=12, net_pnl=3.5,
                            p_positive=0.8, verdict=None),
                       dict(strategy_id=0, title="Cash", market=None, weight=0.4, trips=0, net_pnl=0, p_positive=None)],
          "pooled": {"trips": 12, "target": 400, "mean_return": 0.05, "p_value": 0.2, "per_day": 4.0, "days_to_target": 97.0},
          "book": {"capital": 10000.0, "pnl": 120.0, "return_pct": 1.2, "max_drawdown": 30.0, "trips": 10}}
    text = "\n".join(tournament.context_lines(st))
    assert "do not pause entrants" in text and "60% of the book" in text and "cash: 40%" in text
    assert "12 of 400 independent events" in text and "~97 days" in text
    assert tournament.context_lines({"entrants": [st["entrants"][1]], "pooled": dict(st["pooled"], trips=0),
                                     "book": st["book"]}) == []


def test_autopilot_cannot_pause_a_tournament_entrant_before_its_verdict(monkeypatch):
    statuses = []
    dep = {"id": 77, "strategy_id": 15964, "title": "Rain", "mode": "paper", "status": "running",
           "market": "kxrain", "spec": SPEC, "created_at": NOW - timedelta(days=3)}
    monkeypatch.setattr(agent.repo, "get_deployment", lambda cur, uid, did: dict(dep))
    monkeypatch.setattr(agent.repo, "create_proposal", lambda *a: 1)
    monkeypatch.setattr(agent.repo, "set_deployment_status", lambda cur, uid, did, st, why=None: statuses.append(st))
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: False)
    trips = lambda n, pnl: [{"pnl": pnl, "ticker": "KXRAIN-%d-T1" % i} for i in range(n)]  # noqa: E731
    monkeypatch.setattr(agent.repo, "paper_round_trips", lambda cur, uid, sid: trips(4, -0.5))
    text, pid = agent.act(None, {"id": 1, "autopilot": True}, {"type": "pause", "deployment_id": 77}, autopilot=True)
    assert pid is None and statuses == [] and "4 of 30 independent events" in text
    monkeypatch.setattr(agent.repo, "paper_round_trips", lambda cur, uid, sid: trips(31, -0.3))
    agent.act(None, {"id": 1, "autopilot": True}, {"type": "pause", "deployment_id": 77}, autopilot=True)
    assert statuses == ["paused"]
    statuses.clear()  # a gatekeeper candidate on paper is not held
    monkeypatch.setattr(agent.repo, "paper_round_trips", lambda cur, uid, sid: trips(4, -0.5))
    monkeypatch.setattr(agent, "_is_deployment_candidate", lambda cur, sid: True)
    agent.act(None, {"id": 1, "autopilot": True}, {"type": "pause", "deployment_id": 77}, autopilot=True)
    assert statuses == ["paused"]


def test_underpowered_verdicts_enter_only_with_a_positive_backtest(monkeypatch):
    made = []
    monkeypatch.setattr(agent, "PAPER_PROBATION", True)
    monkeypatch.setattr(agent.rr, "probation_candidates", lambda cur, uid, p, n: [])
    monkeypatch.setattr(agent.rr, "underpowered_candidates", lambda cur, uid, n: [
        {"strategy_id": s, "market": "sol_daily", "p_value": None, "net_pnl": None, "n_trades": 15} for s in (1, 2)])
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid, include_stopped=False: [])
    pnl = {1: 3.0, 2: -1.0}
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "market": "sol_daily", "title": "S%d" % sid, "spec": dict(SPEC), "status": "rejected",
        "result": {"out_of_sample": {"trades": 25, "pnl": pnl[sid]}}})
    monkeypatch.setattr(agent.repo, "create_deployment", lambda cur, uid, sid, m, mode: made.append((sid, mode)) or 1)
    monkeypatch.setattr(agent.repo, "create_proposal", lambda *a: 1)
    monkeypatch.setattr(engine, "cross_deploy_block", lambda spec, mode: "")
    lines = agent.auto_paper_probation(None, {"id": 1, "autopilot": True})
    assert made == [(1, "paper")] and "too few validation trades" in lines[0]
    assert agent.PROBATION_MAX_ACTIVE >= 20


def test_a_research_saved_underpowered_strategy_enters_on_its_research_fold(monkeypatch):
    """Research saves only `in_sample` (the purged walk-forward research fold, see _result_block),
    so 16140 (run 3002, n=56 < 150) was skipped forever while the check read `out_of_sample` only."""
    made = []
    monkeypatch.setattr(agent, "PAPER_PROBATION", True)
    monkeypatch.setattr(agent.rr, "probation_candidates", lambda cur, uid, p, n: [])
    monkeypatch.setattr(agent.rr, "underpowered_candidates", lambda cur, uid, n: [
        {"strategy_id": s, "market": "sol_daily", "p_value": None, "net_pnl": None, "n_trades": 56} for s in (1, 2, 3)])
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid, include_stopped=False: [])
    fold = {1: {"trades": 40, "pnl": 2.5}, 2: {"trades": 40, "pnl": -0.5}, 3: {"trades": 4, "pnl": 9.0}}
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "market": "sol_daily", "title": "S%d" % sid, "spec": dict(SPEC), "status": "rejected",
        "result": {"capital": 100, "in_sample": fold[sid], "classification": "inconclusive"}})
    monkeypatch.setattr(agent.repo, "create_deployment", lambda cur, uid, sid, m, mode: made.append((sid, mode)) or 1)
    monkeypatch.setattr(agent.repo, "create_proposal", lambda *a: 1)
    monkeypatch.setattr(engine, "cross_deploy_block", lambda spec, mode: "")
    agent.auto_paper_probation(None, {"id": 1, "autopilot": True})
    assert made == [(1, "paper")]


def test_underpowered_verdicts_use_the_validation_pnl_the_gatekeeper_recorded(monkeypatch):
    """Research strategies carry no out_of_sample block (held-out numbers stay away from the
    generator), so the recorded validation P&L decides: up enters paper, down or flat does not."""
    made = []
    monkeypatch.setattr(agent, "PAPER_PROBATION", True)
    monkeypatch.setattr(agent.rr, "probation_candidates", lambda cur, uid, p, n: [])
    monkeypatch.setattr(agent.rr, "underpowered_candidates", lambda cur, uid, n: [
        {"strategy_id": s, "market": "btc15m+sol_daily", "p_value": None, "net_pnl": v, "n_trades": 56}
        for s, v in ((1, 4.5), (2, -2.0), (3, 0.0))])
    monkeypatch.setattr(agent.repo, "list_deployments", lambda cur, uid, include_stopped=False: [])
    monkeypatch.setattr(agent.repo, "get_strategy", lambda cur, uid, sid: {
        "id": sid, "market": "sol_daily", "title": "S%d" % sid, "spec": dict(SPEC), "status": "rejected",
        "result": {"in_sample": {"trades": 300, "pnl": 50.0}, "classification": "inconclusive"}})
    monkeypatch.setattr(agent.repo, "create_deployment", lambda cur, uid, sid, m, mode: made.append((sid, mode)) or 1)
    monkeypatch.setattr(agent.repo, "create_proposal", lambda *a: 1)
    monkeypatch.setattr(engine, "cross_deploy_block", lambda spec, mode: "")
    lines = agent.auto_paper_probation(None, {"id": 1, "autopilot": True})
    assert made == [(1, "paper"), (1, "paper")]  # one deployment per leg of the pooled stream
    assert "too few validation trades to score (56), and they were up $4.50" in lines[0]


def test_each_mode_counts_only_its_own_positions_and_paper_gets_10x(monkeypatch):
    """Todd 2026-10-25 chose separate books: live limits count only live positions (same numbers),
    paper gets 10x in fake money, so a full paper tournament never blocks a live entry."""
    seen = []
    monkeypatch.setattr(engine.repo, "user_open_exposure",
                        lambda cur, uid, mode=None: seen.append(mode) or {"n": 5, "notional": 50.0})
    risk = {"max_open_positions": 20, "max_open_notional": 1000.0}
    assert engine.PAPER_CAP_MULTIPLE == 10.0
    assert engine._entry_caps(None, {"user_id": 1, "mode": "paper"}, risk) == (5, 50.0, 200, 10000.0)
    assert engine._entry_caps(None, {"user_id": 1, "mode": "live"}, risk) == (5, 50.0, 20, 1000.0)
    assert engine._entry_caps(None, {"user_id": 1, "mode": "demo"}, risk) == (5, 50.0, 20, 1000.0)
    assert seen == ["paper", "live", "demo"]
    monkeypatch.setattr(engine, "PAPER_CAP_MULTIPLE", 1.0)
    assert engine._entry_caps(None, {"user_id": 1, "mode": "paper"}, risk) == (5, 50.0, 20, 1000.0)



def test_panel_line_summarizes_the_tournament_in_one_sentence(monkeypatch):
    from app import server
    rows = [{"strategy_id": 7, "weight": 0.5, "trips": 12}, {"strategy_id": 8, "weight": 0.2, "trips": 3},
            {"strategy_id": 0, "weight": 0.3, "trips": 0}]
    monkeypatch.setattr(tournament, "latest_snapshot", lambda cur, uid: rows)
    t = tournament.panel_summary(None, 1, {7: "Rain NYC"})
    line = server._tournament_line(t)
    assert line == ("The paper tournament runs 2 strategies at once, with 15 of the 400 independent bets the research gate "
                    "needs so far; it has 50% of its $10,000 practice book on Rain NYC.")
    monkeypatch.setattr(tournament, "latest_snapshot", lambda cur, uid: [dict(rows[0], weight=0.2), dict(rows[2], weight=0.8)])
    assert "in cash until an entrant proves it beats zero" in server._tournament_line(tournament.panel_summary(None, 1, {}))
    monkeypatch.setattr(tournament, "latest_snapshot", lambda cur, uid: [])
    assert tournament.panel_summary(None, 1, {}) is None and server._tournament_line(None) == ""


def test_strikes_of_one_event_count_as_one_bet(monkeypatch):
    """Five strikes of one 15m event are one bet (#169): the posterior, verdicts and pooled sample
    all run on per-event returns, so correlated trips can't fake confidence."""
    from app import repository
    trips = [{"pnl": -1.0, "ticker": "KXBTC15M-26OCT241515-%d" % k, "opened_at": NOW, "closed_at": NOW}
             for k in range(5)] + [{"pnl": 2.0, "ticker": "KXBTC15M-26OCT241530-1", "opened_at": NOW, "closed_at": NOW}]
    monkeypatch.setattr(repository, "list_deployments", lambda cur, uid, include_stopped=False: [
        {"id": 9, "strategy_id": 1, "mode": "paper", "status": "running", "spec": SPEC, "result": {}}])
    monkeypatch.setattr(repository, "paper_round_trips", lambda cur, uid, sid: trips)
    [e] = tournament.entrants(None, 1)
    assert e["returns"] == [-1.0, 0.4]  # two events: -$5 and +$2 on a $5 stake
    monkeypatch.setattr(tournament, "_now", lambda: NOW)
    p = tournament.pooled(tournament.all_paper_trips(None, 1))
    assert p["trips"] == 2 and p["net_pnl"] == -3.0


def test_standings_read_the_deployments_once_and_every_strategys_trips_at_once(monkeypatch):
    """The scoreboard's tournament: the entrants and the book used to read the deployments twice and
    each paper strategy's trips twice, one strategy at a time (2 + 2x strategies statements; 24 of the
    board's 118 for a 22-deployment account, measured 2026-10-26). Now two reads, and the same standings
    as the per-strategy reads give."""
    from app import repository
    deps = [{"id": 10 + k, "strategy_id": sid, "mode": mode, "status": status, "spec": SPEC, "result": {},
             "title": "S%d" % sid, "market": "btc15m", "created_at": NOW - timedelta(days=3), "updated_at": NOW}
            for k, (sid, mode, status) in enumerate([(4, "paper", "running"), (3, "paper", "stopped"),
                                                     (2, "demo", "running"), (1, "paper", "paused")])]
    trips = {sid: [{"pnl": (-1.0) ** k * sid, "ticker": "KXBTC15M-26OCT2415%02d-%d" % (k, k),
                    "opened_at": NOW - timedelta(hours=40 - k + sid), "closed_at": NOW - timedelta(hours=39 - k + sid)}
                   for k in range(6)] for sid in (1, 3, 4)}
    reads = []

    def list_deployments(cur, uid, include_stopped=False):
        reads.append(("deployments", include_stopped))
        return [d for d in deps if include_stopped or d["status"] != "stopped"]

    def by_strategy(cur, uid, sids):
        reads.append(("trips", tuple(sids)))
        return {s: trips[s] for s in sids if s in trips}

    def one(cur, uid, sid):
        reads.append(("trips", sid))
        return trips.get(sid, [])

    monkeypatch.setattr(repository, "list_deployments", list_deployments)
    monkeypatch.setattr(repository, "paper_round_trips_by_strategy", by_strategy)
    monkeypatch.setattr(repository, "paper_round_trips", one)
    monkeypatch.setattr(tournament, "weight_history", lambda cur, uid: {})
    monkeypatch.setattr(tournament, "_now", lambda: NOW)
    out = tournament.standings(None, 7)
    assert reads == [("deployments", True), ("trips", (1, 3, 4))]
    # The per-strategy reads (rebalance still makes them) give the same entrants, pooled sample and book.
    reads.clear()
    ents = tournament.entrants(None, 7)
    every = tournament.all_paper_trips(None, 7)
    assert [e["strategy_id"] for e in ents] == [4, 1] and len(reads) == 7
    arms = tournament.allocate(ents, seed="7:%s" % NOW.strftime("%Y%m%d%H"))
    assert [(r["strategy_id"], r["weight"]) for r in out["entrants"]] == [(a["strategy_id"], a["weight"]) for a in arms]
    assert out["entrants"][0]["net_pnl"] == round(sum(t["pnl"] for t in trips[4]), 4)
    assert out["pooled"] == tournament.pooled(every) and out["book"] == tournament.book(every, {})
