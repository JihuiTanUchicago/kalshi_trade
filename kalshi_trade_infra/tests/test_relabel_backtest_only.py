"""The one-time legacy relabel (app/relabel_backtest_only.py) must flip ONLY un-validated
'passed' rows — never a genuinely gatekeeper-linked one — and be idempotent. FakeCursor, no DB.
"""
from app.relabel_backtest_only import relabel_legacy_passed


class FakeCursor:
    """Models just the one UPDATE ... NOT EXISTS the relabel issues, over two in-memory tables."""

    def __init__(self, strategies, experiments):
        self.app_strategies = strategies          # list of {id, status, experiment_id}
        self.app_experiments = experiments        # list of {strategy_id}
        self.rowcount = 0

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        assert s.startswith("UPDATE app_strategies s SET s.status='backtest-only'")
        legacy_linked = {e["strategy_id"] for e in self.app_experiments}
        n = 0
        for row in self.app_strategies:
            if (row["status"] == "passed" and row.get("experiment_id") is None
                    and row["id"] not in legacy_linked):
                row["status"] = "backtest-only"
                n += 1
        self.rowcount = n


def test_relabels_only_unvalidated_passed_rows():
    strategies = [
        {"id": 1, "status": "passed", "experiment_id": None},   # loose/legacy: relabel
        {"id": 2, "status": "passed", "experiment_id": 7},      # stored link: keep
        {"id": 3, "status": "passed", "experiment_id": None},   # legacy strategy_id link: keep
        {"id": 4, "status": "rejected", "experiment_id": None},  # not passed: keep
        {"id": 5, "status": "backtest-only", "experiment_id": None},  # already relabelled: keep
    ]
    experiments = [{"strategy_id": 3}]
    cur = FakeCursor(strategies, experiments)

    n = relabel_legacy_passed(cur)

    assert n == 1
    by_id = {r["id"]: r["status"] for r in strategies}
    assert by_id == {1: "backtest-only", 2: "passed", 3: "passed", 4: "rejected", 5: "backtest-only"}

    # Idempotent: a second run finds nothing left to change.
    assert relabel_legacy_passed(cur) == 0
