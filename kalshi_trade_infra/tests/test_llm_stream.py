"""Bedrock converse_stream plumbing: text deltas reach the sink as they arrive, usage is read
from the metadata event, and a sink that throws mid-stream never aborts generation."""
import sys
import time
import types

import pytest


@pytest.fixture(autouse=True)
def _reset_model_cooldown():
    # The daily-quota cooldown is module-level global state; clear it around every test so a
    # cooldown set by one fallback test doesn't skip a model in the next.
    from app.adapters.llm import llm as _llm
    _llm._MODEL_COOLDOWN.clear()
    yield
    _llm._MODEL_COOLDOWN.clear()

from app.adapters.llm import llm


class _FakeStreamClient:
    def __init__(self, events):
        self._events = events
        self.calls = []

    def converse_stream(self, **kwargs):
        self.calls.append(kwargs)
        return {"stream": self._events}


def test_bedrock_stream_emits_deltas_and_reads_usage():
    got = []
    client = _FakeStreamClient([
        {"contentBlockDelta": {"delta": {"text": "Hello "}}},
        {"contentBlockDelta": {"delta": {"text": "world"}}},
        {"metadata": {"usage": {"inputTokens": 12, "outputTokens": 7}}},
    ])
    text, usage = llm._bedrock_stream(client, {"modelId": "m"}, got.append)
    assert text == "Hello world"
    assert got == ["Hello ", "world"]
    assert usage == {"input_tokens": 12, "output_tokens": 7}
    assert client.calls == [{"modelId": "m"}]


def test_bedrock_stream_survives_a_sink_that_throws():
    # A dropped DB connection mid-stream must not kill the generation call.
    def boom(_chunk):
        raise RuntimeError("db connection dropped")

    client = _FakeStreamClient([{"contentBlockDelta": {"delta": {"text": "x"}}}])
    text, _usage = llm._bedrock_stream(client, {}, boom)
    assert text == "x"


def test_sink_db_desync_is_reraised_not_swallowed():
    # Bug 2b: a sink DB desync (pymysql error) leaves the socket half-read; swallowing it breaks
    # the NEXT query. It must surface, unlike an ordinary cosmetic sink hiccup (test above).
    class _PacketError(Exception):
        pass
    _PacketError.__module__ = "pymysql.err"  # mimic pymysql.err.InternalError ("packet sequence")

    def desync(_chunk):
        raise _PacketError("Packet sequence number wrong")

    assert llm._is_sink_connection_error(_PacketError()) is True
    assert llm._is_sink_connection_error(RuntimeError()) is False
    client = _FakeStreamClient([{"contentBlockDelta": {"delta": {"text": "x"}}}])
    try:
        llm._bedrock_stream(client, {}, desync)
        assert False, "expected the DB desync to surface"
    except _PacketError:
        pass


# -- Bug 3: a streaming read timeout is a ResponseStreamingError, not ReadTimeoutError; retry it --


class _FakeBedrockClient:
    """A Bedrock client whose stream fails `fail_times` with a streaming-timeout error, then
    succeeds; converse() is the non-streaming fallback."""

    def __init__(self, err, fail_times):
        self._err, self._fail = err, fail_times
        self.stream_calls = 0

    def converse_stream(self, **kwargs):
        self.stream_calls += 1
        if self.stream_calls <= self._fail:
            raise self._err("Read timeout on endpoint URL")
        return {"stream": [
            {"contentBlockDelta": {"delta": {"text": "streamed"}}},
            {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1}}},
        ]}

    def converse(self, **kwargs):
        return {"output": {"message": {"content": [{"text": "fallback"}]}},
                "usage": {"inputTokens": 2, "outputTokens": 2}}


def _install_fake_boto3(monkeypatch, client):
    """Inject minimal boto3/botocore so _bedrock runs without the real SDK (absent in CI venv)."""
    exc = types.ModuleType("botocore.exceptions")
    for name in ("ClientError", "ReadTimeoutError", "ConnectTimeoutError",
                 "ResponseStreamingError", "EventStreamError"):
        setattr(exc, name, type(name, (Exception,), {}))
    exc.ClientError.response = {"Error": {"Code": ""}}  # attr _bedrock reads on ClientError
    conf = types.ModuleType("botocore.config")
    conf.Config = lambda **k: None
    botocore = types.ModuleType("botocore")
    botocore.exceptions, botocore.config = exc, conf
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *a, **k: client
    for name, mod in [("boto3", boto3), ("botocore", botocore),
                      ("botocore.exceptions", exc), ("botocore.config", conf)]:
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)  # don't actually back off
    monkeypatch.setattr(llm, "LLM_PROVIDER", "bedrock")
    return exc.ResponseStreamingError


def test_streaming_timeout_retries_then_succeeds(monkeypatch):
    client = _FakeBedrockClient(None, fail_times=2)
    client._err = _install_fake_boto3(monkeypatch, client)  # fail twice with a streaming timeout
    got = []
    text, _ = llm._bedrock("sys", [{"role": "user", "content": "hi"}], on_delta=got.append)
    assert text == "streamed"          # retried past the transient streaming timeouts
    assert client.stream_calls == 3    # 2 failures + 1 success
    assert got == ["streamed"]


def test_streaming_timeout_exhausted_falls_back_to_converse(monkeypatch):
    client = _FakeBedrockClient(None, fail_times=99)
    client._err = _install_fake_boto3(monkeypatch, client)  # streaming never recovers
    text, _ = llm._bedrock("sys", [{"role": "user", "content": "hi"}], on_delta=lambda _t: None)
    assert text == "fallback"          # degrades to non-streaming instead of surfacing raw
    assert client.stream_calls == llm._BEDROCK_RETRIES + 1  # bounded attempts, then converse fallback


class _ThrottleStreamClient:
    """Its stream raises a Bedrock ThrottlingException `fail_times`, then succeeds. converse() is
    the non-streaming fallback, used only if the stream never recovers."""

    def __init__(self, fail_times):
        self._fail = fail_times
        self.stream_calls = 0
        self.ClientError = Exception  # set to the fake botocore ClientError after install

    def converse_stream(self, **kwargs):
        self.stream_calls += 1
        if self.stream_calls <= self._fail:
            e = self.ClientError("throttled")
            e.response = {"Error": {"Code": "ThrottlingException"}}
            raise e
        return {"stream": [
            {"contentBlockDelta": {"delta": {"text": "ok"}}},
            {"metadata": {"usage": {"inputTokens": 1, "outputTokens": 1}}},
        ]}

    def converse(self, **kwargs):
        return {"output": {"message": {"content": [{"text": "fallback"}]}},
                "usage": {"inputTokens": 1, "outputTokens": 1}}


def test_streaming_throttle_retries_instead_of_failing(monkeypatch):
    # A throttled stream used to fall straight through to converse (which re-throttled). It must
    # now back off and retry the stream so a transient throttle doesn't cost the whole run.
    client = _ThrottleStreamClient(fail_times=2)
    _install_fake_boto3(monkeypatch, client)
    import botocore.exceptions as be
    client.ClientError = be.ClientError
    text, _ = llm._bedrock("sys", [{"role": "user", "content": "hi"}], on_delta=lambda _t: None)
    assert text == "ok"                 # recovered on the stream, never fell back
    assert client.stream_calls == 3     # 2 throttles + 1 success


def test_claude_without_on_delta_is_unchanged(monkeypatch):
    # The ordinary (system, messages) path must not stream — on_delta stays None.
    seen = {}
    monkeypatch.setattr(llm, "LLM_PROVIDER", "bedrock")
    monkeypatch.setattr(llm, "_bedrock", lambda s, m, model=None, on_delta=None: (seen.setdefault("on_delta", on_delta), ("ok", {}))[1])
    text, _ = llm.claude("sys", [{"role": "user", "content": "hi"}])
    assert text == "ok" and seen["on_delta"] is None


# -- FIX 3: model-stall guard — a stream that goes silent mid-generation aborts fast ---------------


class _StallingStream:
    """A converse_stream result that yields a few tokens, then STALLS (blocks longer than the stall
    window) — the silent-socket failure the guard must catch without hanging."""
    def __init__(self, stall_for):
        self._stall = stall_for

    def __iter__(self):
        yield {"contentBlockDelta": {"delta": {"text": "thinking "}}}
        yield {"contentBlockDelta": {"delta": {"text": "out loud "}}}
        time.sleep(self._stall)   # model went quiet — no more tokens
        yield {"contentBlockDelta": {"delta": {"text": "too late"}}}


def test_stall_guard_aborts_a_stalled_stream_fast():
    # No token for `stall_seconds` -> LLMError quickly, NOT a hang until the stream un-stalls.
    client = _FakeStreamClient(_StallingStream(stall_for=10))
    got = []
    t0 = time.monotonic()
    try:
        llm._bedrock_stream(client, {}, got.append, stall_seconds=0.3)
        assert False, "expected the stall guard to raise"
    except llm.LLMError as e:
        assert "stalled" in str(e)
    elapsed = time.monotonic() - t0
    assert elapsed < 5, "must abort near the stall window (%.2fs), not wait out the 10s stall" % elapsed
    assert got == ["thinking ", "out loud "]  # the tokens that DID arrive were delivered first


def test_stall_guard_lets_a_healthy_stream_through():
    # A stream that keeps producing within the window completes normally (guard never fires).
    client = _FakeStreamClient([
        {"contentBlockDelta": {"delta": {"text": "a"}}},
        {"contentBlockDelta": {"delta": {"text": "b"}}},
        {"metadata": {"usage": {"inputTokens": 3, "outputTokens": 2}}},
    ])
    text, usage = llm._bedrock_stream(client, {}, lambda _t: None, stall_seconds=0.5)
    assert text == "ab" and usage == {"input_tokens": 3, "output_tokens": 2}


# -- Automatic model fallback on quota exhaustion -------------------------------------------------

from app.adapters.llm import models_catalog as _cat
# The default chain (llm.BEDROCK_MODEL defaults to the catalog default): _OPUS is the preferred
# model and _SONNET stands for "the next model down", whatever the catalog's FALLBACK_ORDER says.
_CHAIN = _cat.fallback_chain_from(llm.BEDROCK_MODEL)
_OPUS, _SONNET = _CHAIN[0], _CHAIN[1]


class _PerModelThrottleClient:
    """converse throttles for model ids in `bad`, succeeds otherwise. `daily=True` makes it a daily
    token-quota throttle (message contains 'per day'), which must fail over without wasting retries."""

    def __init__(self, bad, daily=True):
        self.bad = set(bad)
        self.daily = daily
        self.ClientError = Exception
        self.calls = []

    def _maybe(self, kwargs):
        mid = kwargs.get("modelId")
        self.calls.append(mid)
        if mid in self.bad:
            tail = "Too many tokens per day, please wait" if self.daily else "slow down"
            e = self.ClientError("An error occurred (ThrottlingException): " + tail)
            e.response = {"Error": {"Code": "ThrottlingException", "Message": tail}}
            raise e

    def converse(self, **kwargs):
        self._maybe(kwargs)
        return {"output": {"message": {"content": [{"text": "ok"}]}},
                "usage": {"inputTokens": 1, "outputTokens": 1}}


def _wire(monkeypatch, client):
    client.ClientError = _install_fake_boto3(monkeypatch, client) and None  # install first
    import botocore.exceptions as be
    client.ClientError = be.ClientError


def test_fallback_to_next_model_when_preferred_is_quota_exhausted(monkeypatch):
    client = _PerModelThrottleClient(bad=[_OPUS], daily=True)   # Opus out of daily quota
    _wire(monkeypatch, client)
    text, _ = llm._bedrock("sys", [{"role": "user", "content": "hi"}])  # starts at Opus (BEDROCK_MODEL)
    assert text == "ok"
    assert client.calls == [_OPUS, _SONNET]   # tried Opus once, fell straight over to Sonnet


def test_all_models_exhausted_raises_throttled(monkeypatch):
    client = _PerModelThrottleClient(bad=_CHAIN, daily=True)
    _wire(monkeypatch, client)
    with pytest.raises(llm.LLMThrottled):
        llm._bedrock("sys", [{"role": "user", "content": "hi"}])
    assert client.calls == _CHAIN   # walked the whole chain before giving up


def test_daily_quota_does_not_waste_retries(monkeypatch):
    # A daily-quota throttle must fail over immediately — exactly one call to the exhausted model.
    client = _PerModelThrottleClient(bad=[_OPUS], daily=True)
    _wire(monkeypatch, client)
    llm._bedrock("sys", [{"role": "user", "content": "hi"}])
    assert client.calls.count(_OPUS) == 1


def test_daily_quota_cooldown_skips_exhausted_model_on_next_call(monkeypatch):
    # After Opus hits its DAILY quota, the next call should NOT re-attempt Opus (it's cooling down)
    # — it goes straight to Sonnet, saving the wasted throttled round-trip on every later call.
    monkeypatch.setattr(llm, "_MODEL_COOLDOWN", {})  # isolate module state
    client = _PerModelThrottleClient(bad=[_OPUS], daily=True)
    _wire(monkeypatch, client)
    llm._bedrock("sys", [{"role": "user", "content": "hi"}])   # 1st: Opus throttles -> Sonnet
    assert client.calls == [_OPUS, _SONNET]
    client.calls.clear()
    llm._bedrock("sys", [{"role": "user", "content": "hi"}])   # 2nd: Opus skipped (cooling) -> Sonnet
    assert client.calls == [_SONNET]


def test_stall_falls_over_to_next_model(monkeypatch):
    # A mid-stream stall on the preferred model should fail OVER to the next model, not kill the run.
    calls = []
    def fake_once(system, messages, mid, on_delta=None):
        calls.append(mid)
        if mid == _OPUS:
            raise llm.LLMStalled("stalled mid-stream")
        return ("ok", {"input_tokens": 1, "output_tokens": 1})
    monkeypatch.setattr(llm, "_bedrock_once", fake_once)
    monkeypatch.setattr(llm, "LLM_PROVIDER", "bedrock")
    text, _ = llm._bedrock("sys", [{"role": "user", "content": "hi"}])
    assert text == "ok"
    assert calls == [_OPUS, _SONNET]          # stalled on Opus -> recovered on Sonnet


def test_stall_does_not_set_a_cooldown(monkeypatch):
    # A stall is transient (the model isn't out of capacity) -> no cooldown, unlike a daily quota.
    monkeypatch.setattr(llm, "_bedrock_once",
                        lambda s, m, mid, on_delta=None: (_ for _ in ()).throw(llm.LLMStalled("x"))
                        if mid == _OPUS else ("ok", {"input_tokens": 1, "output_tokens": 1}))
    monkeypatch.setattr(llm, "LLM_PROVIDER", "bedrock")
    llm._bedrock("sys", [{"role": "user", "content": "hi"}])
    assert _OPUS not in llm._MODEL_COOLDOWN   # stall left no cooldown (throttle would have)
