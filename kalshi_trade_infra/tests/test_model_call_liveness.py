"""A model call in flight counts as run progress: a non-streaming fallback call is silent for minutes
while healthy, and the stall beater used to let the watchdog reap it mid-call."""
import time

from app import agent


def test_a_call_in_flight_holds_progress_for_the_grace_then_releases(monkeypatch):
    monkeypatch.setattr(agent, "RUN_STALL_SECONDS", 150)
    monkeypatch.setattr(agent, "MODEL_CALL_GRACE_SECONDS", 900)
    progress = [0.0]
    seen = {}

    def model(system, messages):
        seen["slack"] = progress[0] - time.monotonic()
        return "ok", {}

    m = agent._alive_during_calls(model, progress)
    assert m("s", []) == ("ok", {})
    # During the call the beater (now - progress > STALL -> stop) keeps beating for ~GRACE seconds.
    assert 740 < seen["slack"] <= 750
    assert abs(progress[0] - time.monotonic()) < 1  # back to a normal stamp once it returns


def test_the_wrapper_keeps_the_streaming_signature():
    plain = agent._alive_during_calls(lambda system, messages: ("a", {}), [0.0])
    streaming = agent._alive_during_calls(lambda system, messages, on_delta=None: ("b", {}), [0.0])
    assert not agent._can_stream(plain)
    assert agent._can_stream(streaming)
    got = []

    def model(system, messages, on_delta=None):
        on_delta("x")
        return "c", {}

    assert agent._alive_during_calls(model, [0.0])("s", [], got.append) == ("c", {})
    assert got == ["x"]  # the live-feed sink still reaches the model


def test_a_raising_call_still_releases_progress():
    progress = [0.0]

    def boom(system, messages):
        raise RuntimeError("x")

    m = agent._alive_during_calls(boom, progress)
    try:
        m("s", [])
    except RuntimeError:
        pass
    assert abs(progress[0] - time.monotonic()) < 1
