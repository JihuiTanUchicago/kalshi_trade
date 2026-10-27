"""A session's passed strategy whose one-time locked holdout then failed carries `later_missed`: the
checks its strategy page lists (gate_explain.for_strategy on the gatekeeper's record). Its status stays
"passed" (validation), and the session page said "Passed: ... Open it to deploy it on paper"."""
from app.web.routes import research


def _strategy(sid, **o):
    s = {"id": sid, "run_id": 5, "status": "passed", "market": "btc15m", "direction": "custom",
         "spec": {"side": "no"}, "result": {"classification": "statistically_supported"}, "experiment_id": 900 + sid}
    s.update(o)
    return s


def _exp(holdout_cls, holdout=None):
    return {"classification": holdout_cls, "min_sample": 120,
            "validation": {"classification": "statistically_supported", "n_trades": 150, "p_value": 0.02,
                           "mean_net_return": 0.026, "ci_lo": 0.004, "ci_hi": 0.05},
            "holdout": dict({"classification": holdout_cls, "n_trades": 71, "p_value": 0.48, "mean_net_return": -0.003,
                             "ci_lo": -0.03, "ci_hi": 0.025, "consumed": True}, **(holdout or {})) if holdout_cls else None}


def test_a_failed_holdout_is_named_and_a_clean_pass_is_not(monkeypatch):
    exps = {42: _exp("rejected"), 43: _exp("forward_validated", {"p_value": 0.03, "mean_net_return": 0.02, "ci_lo": 0.002}),
            44: _exp(None), 45: _exp("rejected")}
    seen = []
    monkeypatch.setattr(research, "_experiment_block", lambda cur, sid, eid=None: seen.append((sid, eid)) or exps[sid])
    rows = [_strategy(42), _strategy(43), _strategy(44), _strategy(45, status="rejected"), _strategy(46, direction=research.repo.DEMO_DIRECTION)]
    out = research._later_missed(None, rows)
    assert set(out) == {42}
    labels = [line["label"] for line in out[42]]
    assert "The edge could be luck on the locked holdout" in labels
    assert all("measured" in line and "next" in line for line in out[42])
    # Only passed strategies are read, by the experiment the strategy row links to; the example is skipped.
    assert seen == [(42, 942), (43, 943), (44, 944)]


def test_an_unreadable_record_never_fails_the_page(monkeypatch):
    monkeypatch.setattr(research, "_experiment_block", lambda cur, sid, eid=None: {"holdout": {"classification": "rejected", "n_trades": "x"}})
    assert research._later_missed(None, [_strategy(42)]) == {}
