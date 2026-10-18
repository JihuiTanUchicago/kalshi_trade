"""Bedrock converse_stream plumbing: text deltas reach the sink as they arrive, usage is read
from the metadata event, and a sink that throws mid-stream never aborts generation."""
import sys
import types

from app import llm


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
    assert client.stream_calls == 4    # 4 streaming attempts, then the converse fallback


def test_claude_without_on_delta_is_unchanged(monkeypatch):
    # The ordinary (system, messages) path must not stream — on_delta stays None.
    seen = {}
    monkeypatch.setattr(llm, "LLM_PROVIDER", "bedrock")
    monkeypatch.setattr(llm, "_bedrock", lambda s, m, model=None, on_delta=None: (seen.setdefault("on_delta", on_delta), ("ok", {}))[1])
    text, _ = llm.claude("sys", [{"role": "user", "content": "hi"}])
    assert text == "ok" and seen["on_delta"] is None
