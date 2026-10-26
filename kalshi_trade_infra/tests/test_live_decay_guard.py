"""Live decay guard: a live deployment that loses money on average over its first
LIVE_DECAY_MIN_TRADES closed trades is paused (flatten-on-pause then closes it). Only ever pauses."""
from app.trading import engine


class _Cur:
    def __init__(self, realized, n, total):
        self.realized, self.n, self.total = realized, n, total
        self._last = None

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT COALESCE(SUM(pnl),0) AS p FROM app_positions"):
            self._last = {"p": self.realized}
        elif s.startswith("SELECT COUNT(*) AS n, COALESCE(SUM(pnl),0) AS p FROM app_positions"):
            self._last = {"n": self.n, "p": self.total}
        else:
            raise AssertionError("unexpected SQL: %s" % s[:80])

    def fetchone(self):
        return self._last


def _dep(mode):
    return {"id": 3, "user_id": 1, "market": "btc15m", "mode": mode,
            "result": {"capital": 100.0, "out_of_sample": {"max_drawdown": 20.0}},
            "spec": {"sizing": {"stake": 5.0, "max_positions": 20}}}


def _wire(monkeypatch):
    rec = {}
    monkeypatch.setattr(engine.repo, "set_deployment_status",
                        lambda cur, uid, dep_id, status, why: rec.update(status=status, why=why) or True)
    monkeypatch.setattr(engine.repo, "add_chat", lambda *a, **k: None)
    monkeypatch.setattr(engine.repo, "create_run", lambda *a, **k: 1)
    return rec


def test_live_losing_on_average_after_enough_trades_is_paused(monkeypatch):
    rec = _wire(monkeypatch)
    n = engine.LIVE_DECAY_MIN_TRADES
    assert engine.loss_guard(_Cur(-3.0, n, -3.0), _dep("live")) is True
    assert rec["status"] == "paused" and "did not survive real execution" in rec["why"]


def test_live_with_too_few_trades_is_left_alone(monkeypatch):
    rec = _wire(monkeypatch)
    assert engine.loss_guard(_Cur(-3.0, engine.LIVE_DECAY_MIN_TRADES - 1, -3.0), _dep("live")) is False
    assert rec == {}


def test_live_making_money_is_left_alone(monkeypatch):
    rec = _wire(monkeypatch)
    assert engine.loss_guard(_Cur(4.0, 50, 4.0), _dep("live")) is False
    assert rec == {}


def test_paper_is_not_decay_guarded(monkeypatch):
    # Paper losing a little is evidence for the gate, not something to pause; the loss guard still applies.
    rec = _wire(monkeypatch)
    assert engine.loss_guard(_Cur(-3.0, 50, -3.0), _dep("paper")) is False
    assert rec == {}


def test_the_loss_guard_still_fires_first(monkeypatch):
    rec = _wire(monkeypatch)
    assert engine.loss_guard(_Cur(-60.0, 2, -60.0), _dep("live")) is True
    assert "guard" in rec["why"] and "2x its worst" in rec["why"]
