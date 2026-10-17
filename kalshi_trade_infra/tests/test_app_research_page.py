"""Tests for the research-paper strategy detail page's thin API addition
(RESEARCH_PIPELINE_DESIGN.md §D). The frontend consumes `get_strategy`'s new
`experiment` block; here we test the shaping helper `server._experiment_block`
against a FakeCursor in the conftest style (no live DB), covering:
  - happy path: ledger rows exist -> a fully-populated §D block;
  - error path: no ledger row (every strategy created before the pipeline) ->
    experiment is None, with no error, so old strategies never regress.
"""
import json

from app import dreaming, server
from app.repository import now_utc


class FakeResearchCursor:
    """Minimal in-memory stand-in for the two read queries
    research_repository.experiments_for_strategy issues. Follows the conftest
    FakeCursor pattern: match the exact query shapes, not a general SQL engine."""

    def __init__(self, experiments=None, results=None):
        # experiments: list of app_experiments rows; results: list of
        # app_experiment_results rows (DictCursor-style dicts).
        self.experiments = experiments or []
        self.results = results or []
        self._last = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        self._last = []
        if s.startswith("SELECT * FROM app_experiments WHERE strategy_id=%s"):
            sid = params[0]
            rows = [dict(e) for e in self.experiments if e["strategy_id"] == sid]
            rows.sort(key=lambda r: r["id"], reverse=True)
            self._last = rows[:1]
        elif s.startswith("SELECT * FROM app_experiment_results WHERE experiment_id=%s AND phase=%s"):
            exp_id, phase = params
            self._last = [dict(r) for r in self.results if r["experiment_id"] == exp_id and r["phase"] == phase]
            self._last.sort(key=lambda r: r["id"])
        elif s.startswith("SELECT * FROM app_experiment_results WHERE experiment_id=%s"):
            exp_id = params[0]
            self._last = [dict(r) for r in self.results if r["experiment_id"] == exp_id]
            self._last.sort(key=lambda r: r["id"])
        else:
            raise AssertionError("unexpected query: " + s)

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last)


def _experiment_row(exp_id=1, strategy_id=42, **overrides):
    row = {
        "id": exp_id,
        "user_id": 7,
        "run_id": 3,
        "strategy_id": strategy_id,
        "market": "btc15m",
        "hypothesis_hash": "a" * 64,
        "spec_json": json.dumps({"side": "yes", "sizing": {"stake": 10}}),
        "economic_rationale": json.dumps({
            "mechanism": {
                "who_pays": "Late momentum chasers buying the last 2 minutes.",
                "why_not_arbitraged": "Sub-$50 size caps keep pros out.",
                "when": "The final 3 minutes before settlement.",
                "why_persists": "Structural retail flow, not a dislocation.",
            },
            "negative_control": "A random entry on the same minutes earns nothing.",
            "competing_explanations": "Could be a fee artifact; ruled out by the net-of-fee test.",
            "folds": [
                {"from": 1_700_000_000, "to": 1_700_600_000, "mean_net_return": 0.012, "n_trades": 40},
                {"from": 1_700_600_000, "to": 1_701_200_000, "mean_net_return": 0.008, "n_trades": 38},
            ],
        }),
        "primary_metric": "mean_net_return_per_trade",
        "null_hypothesis": "Expected net edge <= 0.",
        "alt_hypothesis": "Expected net edge > 0.",
        "planned_test": "stationary_bootstrap one-sided, alpha from LORD++",
        "falsification_criteria": "A non-positive lower CI bound on the validation window disproves it.",
        "min_sample": 30,
        "cost_assumptions_json": json.dumps({"fee": "kalshi_taker", "slippage_cents": 1, "fill": "ask"}),
        "research_partition_id": 5,
        "planned_n_tests": 12,
        "correction_method": "LORD++",
        "registered_at": now_utc(),
    }
    row.update(overrides)
    return row


def _result_row(exp_id=1, phase="validation", rid=1, **overrides):
    row = {
        "id": rid,
        "experiment_id": exp_id,
        "phase": phase,
        "classification": "statistically_supported",
        "n_trades": 78,
        "net_pnl": 9.5,
        "mean_net_return": 0.011,
        "sharpe": 1.4,
        "psr": 0.97,
        "dsr": 0.96,
        "p_value": 0.012,
        "ci_lo": 0.003,
        "ci_hi": 0.019,
        "fdr_alpha_i": 0.0083,
        "fdr_reject": 1,
        "bh_reject": 1,
        "placebo_p": 0.61,
        "n_trials_audited": 12,
        "holdout_consumed": 0,
        "equity_curve_json": json.dumps([[1_700_000_000, 0.0], [1_700_300_000, 0.4], [1_700_600_000, 0.9]]),
        "verdict_at": now_utc(),
    }
    row.update(overrides)
    return row


# ---- happy path -------------------------------------------------------------


def test_experiment_block_populated_when_ledger_rows_exist():
    exp = _experiment_row(exp_id=1, strategy_id=42)
    val = _result_row(exp_id=1, phase="validation", rid=1)
    hold = _result_row(exp_id=1, phase="holdout", rid=2,
                       classification="forward_validated", mean_net_return=0.009,
                       holdout_consumed=1, n_trades=20)
    cur = FakeResearchCursor(experiments=[exp], results=[val, hold])

    block = server._experiment_block(cur, 42)

    assert block is not None
    # Immutable pre-registration fields come straight off app_experiments.
    assert block["classification"] == "forward_validated"  # latest result wins
    assert block["null_hypothesis"] == "Expected net edge <= 0."
    assert block["planned_test"] == "stationary_bootstrap one-sided, alpha from LORD++"
    assert block["correction_method"] == "LORD++"
    assert block["planned_n_tests"] == 12
    assert block["min_sample"] == 30
    assert block["cost_assumptions"] == {"fee": "kalshi_taker", "slippage_cents": 1, "fill": "ask"}
    assert block["registered_at"] == exp["registered_at"]
    # Structured economic_rationale JSON is split into the §D fields.
    assert block["mechanism"]["who_pays"].startswith("Late momentum")
    assert "random entry" in block["negative_control"]
    assert "fee artifact" in block["competing_explanations"]
    assert len(block["folds"]) == 2 and block["folds"][0]["n_trades"] == 40
    # Validation verdict block, numeric fields coerced out of DECIMAL.
    v = block["validation"]
    assert v["n_trades"] == 78
    assert v["mean_net_return"] == 0.011
    assert v["ci_lo"] == 0.003 and v["ci_hi"] == 0.019
    assert v["p_value"] == 0.012 and v["psr"] == 0.97 and v["dsr"] == 0.96
    assert v["fdr_reject"] is True and v["bh_reject"] is True
    assert v["placebo_p"] == 0.61
    assert v["equity_curve"] == [[1_700_000_000, 0.0], [1_700_300_000, 0.4], [1_700_600_000, 0.9]]
    assert block["n_trials_audited"] == 12
    # Holdout verdict block + consumed latch.
    h = block["holdout"]
    assert h["n_trades"] == 20 and h["mean_net_return"] == 0.009
    assert h["consumed"] is True


def test_experiment_block_plaintext_rationale_falls_back_to_mechanism_string():
    exp = _experiment_row(economic_rationale="Plain-English thesis, not JSON.")
    val = _result_row()
    cur = FakeResearchCursor(experiments=[exp], results=[val])

    block = server._experiment_block(cur, 42)

    assert block["mechanism"] == "Plain-English thesis, not JSON."
    assert block["negative_control"] is None
    assert block["competing_explanations"] is None
    assert block["folds"] == []


def test_experiment_block_handles_missing_holdout_phase():
    # Validation recorded, holdout not yet spent: holdout is None, no error.
    exp = _experiment_row()
    cur = FakeResearchCursor(experiments=[exp], results=[_result_row(phase="validation")])

    block = server._experiment_block(cur, 42)

    assert block["validation"] is not None
    assert block["holdout"] is None


# ---- error path -------------------------------------------------------------


def test_experiment_block_is_none_for_pre_pipeline_strategy():
    # No ledger row at all (every strategy created before this pipeline):
    # the block must be None, never an exception — additive, never a regression.
    cur = FakeResearchCursor(experiments=[], results=[])

    assert server._experiment_block(cur, 999) is None


def test_experiment_block_is_none_when_strategy_id_does_not_match():
    exp = _experiment_row(strategy_id=42)
    cur = FakeResearchCursor(experiments=[exp], results=[_result_row()])

    assert server._experiment_block(cur, 1234) is None


# ---- Tau-RSI exploration-policy panel (_rsi_block) --------------------------


def test_rsi_block_exposes_full_evolved_policy_and_lineage():
    # Happy path: an evolved policy is on file -> the panel carries its full source,
    # lineage (prior -> new score, adopted-at), summary, and the latest dream line.
    pol = {
        "code": "def next_batch(state):\n    return 2\n",
        "score": 1.2345,
        "base_score": 0.9876,
        "summary": "Require >=7 trades before testing a finalist.",
        "updated_at": now_utc(),
    }
    dream = {"message": "Research policy evolved: ...", "created_at": now_utc()}

    block = server._rsi_block(pol, dream)

    assert block["evolved"] is True
    assert block["code"] == pol["code"]                 # the actual decision rules, verbatim
    assert block["score"] == 1.23 and block["base_score"] == 0.99  # rounded lineage
    assert block["summary"] == pol["summary"]
    assert block["evolved_at"] == pol["updated_at"]
    assert block["last_dream"] == dream["message"]


def test_rsi_block_falls_back_to_default_policy_source():
    # Error/empty path: no policy row yet -> there is still something to inspect
    # (the default policy's source), and no scores/summary are fabricated.
    block = server._rsi_block(None, None)

    assert block["evolved"] is False
    assert block["code"] == dreaming.DEFAULT_POLICY_SRC
    assert block["score"] is None and block["base_score"] is None
    assert block["summary"] is None and block["last_dream"] is None
