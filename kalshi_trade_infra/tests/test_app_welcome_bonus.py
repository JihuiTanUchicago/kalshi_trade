"""The welcome bonus must be granted exactly once per user, and self-heal if missed."""
from app import repository as repo


class _Cur:
    def __init__(self, has_bonus):
        self._has = has_bonus

    def execute(self, sql, params=None):
        self._last = (sql, params)

    def fetchone(self):
        return {"1": 1} if self._has else None


def test_ensure_welcome_bonus_skips_when_already_granted(monkeypatch):
    calls = []
    monkeypatch.setattr(repo, "add_credit", lambda *a, **k: calls.append((a, k)) or True)
    assert repo.ensure_welcome_bonus(_Cur(has_bonus=True), 7) is False
    assert calls == []  # no double-grant


def test_ensure_welcome_bonus_grants_when_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(repo, "add_credit", lambda *a, **k: calls.append((a, k)) or True)
    assert repo.ensure_welcome_bonus(_Cur(has_bonus=False), 7) is True
    (a, k) = calls[0]
    assert a[1] == 7 and a[2] == "bonus"            # granted to the user, as a bonus
    assert k.get("stripe_ref") == "welcome-7"       # per-user idempotency ref (race-safe)
