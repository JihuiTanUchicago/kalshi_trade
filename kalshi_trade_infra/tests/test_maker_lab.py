"""Market-making research loop: research-only feedback, one finalist, the held-out gate and its ledger."""
import json
from datetime import datetime, timedelta, timezone

from app.adapters.llm.llm import Usage
from app.services import maker_lab as lab

H0 = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)


def _rows(hours, per_hour, fills=40, fee=0.0):
    return [{"hour": int(h.timestamp()), "fills": fills, "qty": 1000.0, "reward": 0.2, "m10": 0.0,
             "m60": per_hour(i), "fees": 0.0, "fee_stress": fee} for i, h in enumerate(hours)]


def test_split_holds_out_the_newest_hours():
    research, holdout = lab.split(H0 + timedelta(hours=10, minutes=20), 6, 4)
    assert research[0] == H0 and research[-1] == H0 + timedelta(hours=5)
    assert holdout == [H0 + timedelta(hours=k) for k in range(6, 10)]


def test_gate_needs_power_significance_and_survives_the_fee_stress():
    hours = [H0 + timedelta(hours=k) for k in range(20)]
    steady = _rows(hours, lambda i: 5.0 + (i % 3))
    v = lab.judge(steady, 0.05)
    assert v["passed"] and v["p_value"] <= 0.05 and v["mean"] > 0
    assert not lab.judge(steady[:8], 0.05)["passed"]                          # 8 hours: underpowered
    assert "underpowered" in lab.judge(steady[:8], 0.05)["reason"]
    noisy = _rows(hours, lambda i: 40.0 if i % 2 else -38.0)
    assert "not significant" in lab.judge(noisy, 0.05)["reason"]
    fee = _rows(hours, lambda i: 5.0 + (i % 3), fee=9.0)
    assert "fee" in lab.judge(fee, 0.05)["reason"]


def test_lab_shows_research_only_judges_one_finalist_and_splits_alpha_on_reruns():
    research = [H0 + timedelta(hours=k) for k in range(24)]
    holdout = [H0 + timedelta(hours=k) for k in range(24, 40)]
    seen_hours = []

    def evaluate(policy, hours, workers=1):
        seen_hours.append(list(hours))
        good = policy.get("min_edge", 0) >= 0.02
        return _rows(hours, (lambda i: 6.0 + (i % 4)) if good else (lambda i: -20.0 + (i % 3)))

    prompts = []

    def model(system, messages, on_delta=None):
        prompts.append(messages[-1]["content"])
        pols = [{"name": "wide", "why": "x", "fair_source": "spot", "min_edge": 0.03, "back_off": True},
                {"name": "bad", "why": "y", "quote_size": 50}]
        return json.dumps({"policies": pols}), {"input_tokens": 10, "output_tokens": 5}

    ledger = lab.MemoryLedger()
    out = lab.run_lab("KXBTCD", research, holdout, model, Usage(), ledger, evaluate, rounds=1, per_round=2,
                      log=lambda m: None)
    assert out["finalist"] in ("spot_fair_2c", "spot_fair_2c_pull", "r1.1 wide")
    assert out["verdict"]["passed"] and out["verdict"]["alpha"] == 0.05
    assert all(h < holdout[0] for hs in seen_hours[:-1] for h in hs)          # research rounds never see holdout
    assert seen_hours[-1] == holdout and "join_touch" in prompts[0]
    assert len(ledger.entries) == 1
    again = lab.run_lab("KXBTCD", research, holdout, model, Usage(), ledger, evaluate, rounds=1, per_round=2,
                        log=lambda m: None)
    assert again["verdict"]["alpha"] == 0.025                                  # second look at the same window


def test_no_finalist_when_nothing_makes_money_in_research():
    research = [H0 + timedelta(hours=k) for k in range(12)]
    holdout = [H0 + timedelta(hours=k) for k in range(12, 16)]

    def model(system, messages, on_delta=None):
        return json.dumps({"policies": [{"name": "a", "quote_size": 10}]}), {}

    out = lab.run_lab("KXBTC15M", research, holdout, model, Usage(), lab.MemoryLedger(),
                      lambda p, h, workers=1: _rows(h, lambda i: -3.0), rounds=1, per_round=1, log=lambda m: None)
    assert out["finalist"] is None and out["verdict"] is None


def test_each_run_sees_the_summary_of_earlier_runs():
    research = [H0 + timedelta(hours=k) for k in range(12)]
    holdout = [H0 + timedelta(hours=k) for k in range(12, 24)]
    prompts = []

    def model(system, messages, on_delta=None):
        prompts.append(messages[-1]["content"])
        return json.dumps({"policies": [{"name": "a", "fair_source": "spot", "min_edge": 0.04}]}), {}

    first = lab.run_lab("KXBTCD", research, holdout, model, Usage(), lab.MemoryLedger(),
                        lambda p, h, workers=1: _rows(h, lambda i: 4.0 + i % 2), rounds=1, per_round=1,
                        log=lambda m: None)
    lines = lab.summary_lines(json.loads(json.dumps(first)))
    assert lines[0].startswith("- run held out from 2026-10-25 12:00Z") and "finalist" in lines[-1]
    lab.run_lab("KXBTCD", research, holdout, model, Usage(), lab.MemoryLedger(),
                lambda p, h, workers=1: _rows(h, lambda i: 4.0), rounds=1, per_round=1, log=lambda m: None,
                prior=lines)
    assert "Earlier lab runs" not in prompts[0] and "Earlier lab runs" in prompts[1] and lines[-1] in prompts[1]


def test_the_timer_rotates_series_so_each_holdout_window_is_used_once():
    from app.maker_lab_run import auto_series
    picks = [auto_series(H0 + timedelta(hours=h)) for h in range(0, 24, 4)]
    assert picks == ["KXBTCD", "KXBTC15M", "KXBTC"] * 2


def test_a_worker_killed_out_of_memory_finishes_the_hours_in_process(monkeypatch):
    from concurrent.futures.process import BrokenProcessPool
    from app.adapters.sim import maker_eval

    class Dies:
        def __init__(self, max_workers):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def map(self, fn, jobs):
            raise BrokenProcessPool("a child process terminated abruptly")

    monkeypatch.setattr(maker_eval, "ProcessPoolExecutor", Dies)
    monkeypatch.setattr(maker_eval, "_eval_args", lambda j: {"hour": j[1]})
    hours = [H0 + timedelta(hours=k) for k in range(3)]
    monkeypatch.setattr(maker_eval, "FALLBACKS", [])
    rows = maker_eval.evaluate({"series": "KXBTCD"}, hours, workers=2)
    assert [r["hour"] for r in rows] == [int(h.timestamp()) for h in hours]
    assert maker_eval.FALLBACKS == [3]                                  # the run's status file reports it


def test_the_fast_series_search_wider_inside_the_slot():
    from app.maker_lab_run import search_size
    assert search_size("KXBTCD") == (3, 4)                        # ~2h20m already; stays
    assert search_size("KXBTC") == (5, 6) and search_size("KXBTC15M") == (4, 5)
    assert search_size("KXBTC", rounds=1, per_round=2) == (1, 2)   # the CLI still overrides


def _run(series, name, p, stressed, hold_end, h="abc"):
    return {"series": series, "finalist": name, "holdout_hours": [hold_end - 3600 * 11, hold_end],
            "results": {name: {"hash": h, "policy": {"series": series, "min_edge": 0.02}}},
            "verdict": {"p_value": p, "fee_stressed_mean": stressed}}


def test_near_miss_finalists_are_judged_once_on_the_24_hours_after_their_holdout():
    """Todd 2026-10-31: one holdout pass in ~10 judged finalists is about chance, so qualifying
    finalists get ONE frozen judgment on the hours after their holdout, in their own ledger."""
    end = int((H0 + timedelta(hours=11)).timestamp())
    runs = [_run("KXBTC15M", "r4.3", 0.0165, 24.7, end, "p1"),
            _run("KXBTC15M", "r4.2", 0.195, 14.8, end + 12 * 3600, "p2"),   # window not archived yet
            _run("KXBTC", "r3.3", 0.56, -4.8, end, "p3"),                  # not a near miss
            _run("KXBTC", "r2.2", 0.10, -1.0, end, "p4"),                  # loses under the fee stress
            {"series": "KXBTCD", "finalist": None, "verdict": None}]
    book = lab.ForwardBook()
    archived_to = H0 + timedelta(hours=12 + 24)                            # 24 hours after r4.3's holdout
    due = lab.forward_due(runs, book, archived_to, limit=5)
    assert [c["name"] for c in due] == ["r4.3"]
    c = due[0]
    assert c["start"] == end + 3600 and c["end"] - c["start"] == 24 * 3600 and c["policy"]["min_edge"] == 0.02

    seen = []

    def evaluate(policy, hours, workers=1):
        seen.append(list(hours))
        return _rows(hours, lambda i: 6.0 + (i % 4))

    e = lab.judge_forward(c, book, evaluate, log=lambda m: None)
    assert e["passed"] and e["holdout_p"] == 0.0165 and e["hours"] == 24
    assert seen[0][0].timestamp() == end + 3600 and len(seen[0]) == 24
    assert lab.forward_due(runs, book, archived_to + timedelta(hours=48), limit=5) == [
        lab.forward_candidate(runs[1])]                                     # r4.3 never again; r4.2 now due
    ledger = lab.MemoryLedger()
    assert ledger.overlapping("KXBTC15M", c["start"], c["end"]) == 0        # holdout alpha untouched


def test_a_clone_of_a_policy_already_judged_forward_is_not_judged_again():
    end = int((H0 + timedelta(hours=11)).timestamp())
    runs = [_run("KXBTC", "a", 0.05, 3.0, end, "same"), _run("KXBTC", "b", 0.08, 2.0, end + 3600, "same")]
    book = lab.ForwardBook()
    assert [c["name"] for c in lab.forward_due(runs, book, H0 + timedelta(days=5), limit=5)] == ["a"]
    book.record({"series": "KXBTC", "hash": "same"})
    assert lab.forward_due(runs, book, H0 + timedelta(days=5), limit=5) == []
