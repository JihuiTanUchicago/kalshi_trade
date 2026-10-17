"""Bedrock converse_stream plumbing: text deltas reach the sink as they arrive, usage is read
from the metadata event, and a sink that throws mid-stream never aborts generation."""
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


def test_claude_without_on_delta_is_unchanged(monkeypatch):
    # The ordinary (system, messages) path must not stream — on_delta stays None.
    seen = {}
    monkeypatch.setattr(llm, "LLM_PROVIDER", "bedrock")
    monkeypatch.setattr(llm, "_bedrock", lambda s, m, model=None, on_delta=None: (seen.setdefault("on_delta", on_delta), ("ok", {}))[1])
    text, _ = llm.claude("sys", [{"role": "user", "content": "hi"}])
    assert text == "ok" and seen["on_delta"] is None
