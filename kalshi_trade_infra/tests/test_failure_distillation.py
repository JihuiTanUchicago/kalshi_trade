"""Leak-safe distillation of FAILED strategies (learn-from-failure).

A small in-memory cursor backs repository.strategy_memory (reusing its real SQL),
then repository.distill_failures collapses the failed rows into one compact signal
the generator consumes via agent._memory_block. The whole point is Leak 2: only
classification LABELS + the hypotheses' own specs feed back — never a held-out number.
"""
import json

from app import agent, repository as repo


class StrategyCursor:
    """Handles only the one SELECT strategy_memory issues, DictCursor-style."""

    def __init__(self):
        self.rows = []  # app_strategies rows, newest-first by insert order reversed
        self._last = None

    def add(self, status, side=None, drift_beta=0.0, vol_scale=1.0, direction=None,
            min_price=0.05, max_price=0.95, classification=None, in_pnl=0.0, in_trades=0):
        spec = {"side": side, "model": {"drift_beta": drift_beta, "vol_scale": vol_scale},
                "entry": {"min_price": min_price, "max_price": max_price}}
        result = {"in_sample": {"pnl": in_pnl, "trades": in_trades}, "classification": classification}
        self.rows.append({"title": "s%d" % (len(self.rows) + 1), "direction": direction,
                          "spec_json": json.dumps(spec), "status": status,
                          "result_json": json.dumps(result)})

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        assert s.startswith("SELECT title, direction, spec_json, status, result_json FROM app_strategies")
        self._last = [dict(r) for r in reversed(self.rows)]  # ORDER BY id DESC

    def fetchall(self):
        return self._last or []


def test_distillation_summarizes_recurring_failures():
    cur = StrategyCursor()
    # A clear dead region: three mean-reversion NO strategies in the same price band keep failing,
    # plus one unrelated passed winner that must stay raw (not distilled, not dropped).
    cur.add("rejected", side="no", drift_beta=-2.0, classification="not_finalist", in_pnl=-3, in_trades=9)
    cur.add("rejected", side="no", drift_beta=-1.0, classification="rejected", in_pnl=-1, in_trades=12)
    cur.add("failed", side="no", drift_beta=-0.5, classification="inconclusive", in_pnl=2, in_trades=20)
    cur.add("passed", side="yes", drift_beta=1.0, classification="statistically_supported", in_pnl=40, in_trades=30)

    memory = repo.strategy_memory(cur, user_id=1, market="btc15m", limit=40)
    d = repo.distill_failures(memory)
    assert d["n_failed"] == 3
    assert d["classifications"] == {"not_finalist": 1, "rejected": 1, "inconclusive": 1}
    pats = dict(d["patterns"])
    assert pats["side=no"] == 3                 # recurring side
    assert pats["mechanism=mean-reversion"] == 3  # recurring mechanism
    assert pats["price-band=0.05-0.95"] == 3    # recurring region
    assert "side=yes" not in pats               # the passed winner is NOT counted as a failure

    # Leak safety: the distilled signal is pure labels + spec regions — no held-out number anywhere.
    blob = json.dumps(d)
    for banned in ("sharpe", "psr", "dsr", "p_value", "holdout", "validation", "out_of_sample"):
        assert banned not in blob.lower()

    # The generator-facing block keeps the passed winner raw and appends the distilled steer.
    block = agent._memory_block(memory)
    assert "[passed] s4" in block
    assert "repeatedly FAILED" in block and "side=no (3×)" in block
    assert "[rejected]" not in block  # raw rejected rows no longer dumped to the generator


def test_no_failures_is_a_no_op():
    cur = StrategyCursor()
    cur.add("passed", side="yes", classification="statistically_supported", in_pnl=40, in_trades=30)
    memory = repo.strategy_memory(cur, user_id=1, market="btc15m", limit=40)
    assert repo.distill_failures(memory) is None
    # Empty memory also yields None and leaves the loop's prompt untouched.
    assert repo.distill_failures([]) is None
    block = agent._memory_block(memory)
    assert "repeatedly FAILED" not in block  # nothing failed → no steer injected
    assert "[passed] s1" in block
