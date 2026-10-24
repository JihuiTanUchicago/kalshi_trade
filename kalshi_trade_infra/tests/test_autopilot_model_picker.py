"""The autopilot model picker: the user chooses the model their autopilot's own runs use, so they
can route off a throttled model. The setter validates against the catalog; unknown keys are refused."""
import pytest

from app import models_catalog as catalog
from app import repository as repo, server
from app.server import ApiError


class _RecCursor:
    def __init__(self):
        self.last = None

    def execute(self, sql, params=()):
        self.last = (sql, params)


class _Ctx:
    def __init__(self, body):
        self.body = body
        self.cur = _RecCursor()
        self.uid = 1


def test_set_autopilot_model_writes_key():
    cur = _RecCursor()
    repo.set_autopilot_model(cur, 1, "claude-sonnet-5-5")
    assert cur.last[1] == ("claude-sonnet-5-5", 1)


def test_set_autopilot_model_clears_to_default_on_empty():
    cur = _RecCursor()
    repo.set_autopilot_model(cur, 1, "")
    assert cur.last[1] == (None, 1)   # empty -> NULL -> catalog default


def test_handler_accepts_a_known_model():
    key = catalog.DEFAULT_KEY
    out = server.autopilot_model(_Ctx({"model": key}))
    assert out["ok"] and out["model"] == key


def test_handler_rejects_an_unknown_model():
    with pytest.raises(ApiError):
        server.autopilot_model(_Ctx({"model": "totally-made-up"}))


def test_handler_empty_clears_to_default():
    out = server.autopilot_model(_Ctx({"model": ""}))
    assert out["model"] == catalog.DEFAULT_KEY   # cleared -> reported as the default
