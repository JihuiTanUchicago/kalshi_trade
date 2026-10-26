"""Claude over plain HTTPS, plus the JSON discipline every agent call uses.

The agent's only outputs are JSON objects that host code validates; model text
is data, never instructions. `ask_json` gives the model exactly one chance to
repair a reply that does not parse or does not validate, then fails loudly.
"""
from __future__ import annotations

import json
import os
import queue
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = os.getenv("APP_AGENT_MODEL", "claude-sonnet-5-5")
# 6000 truncated the proposer's multi-hypothesis JSON mid-structure (8 rich hypotheses with
# mechanism/falsification/negative-control/spec run ~10-15k output tokens), producing an
# unparseable reply that failed the run. 16000 fits a full batch; modern Claude models allow far
# more, and billing is per token GENERATED, not per cap, so a higher ceiling costs nothing unless
# the model actually uses it. Env-overridable so the box can tune without a redeploy.
MAX_TOKENS = int(os.getenv("APP_AGENT_MAX_TOKENS", "16000"))
TIMEOUT_SECONDS = 180
# Inter-token stall guard for a STREAMING model call: if no delta arrives for this long the call is
# aborted with an LLMError the research loop handles, instead of hanging on a silent socket until the
# run-level watchdog reaps the whole run. A healthy stream emits tokens continuously (sub-second
# gaps), so a multi-minute gap is a genuine stall, never slow-but-working generation. Env-tunable.
STREAM_STALL_SECONDS = float(os.getenv("TAU_STREAM_STALL_SECONDS", "120"))

# "bedrock" bills Claude through AWS (uses AWS credits, no Anthropic key, auth
# via the instance role); anything else uses the Anthropic API directly.
LLM_PROVIDER = os.getenv("APP_LLM_PROVIDER", "anthropic").lower()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
# A Bedrock model id or cross-region inference-profile id. Must be enabled in
# the account's Bedrock "Model access" for AWS_REGION.
BEDROCK_MODEL = os.getenv("APP_BEDROCK_MODEL", "us.anthropic.claude-opus-4-6-v1")

# Bedrock transient-error retries. Throttling is the #1 cause of failed research runs when the
# autopilot runs many Opus calls concurrently across users; a throttled call must back off and
# retry, not kill the whole run. Bounded so the worst-case total backoff stays well under the
# research stall watchdog (agent.RUN_STALL_SECONDS, 150s) — the main thread is blocked in the sleep
# and can't mark progress, so a longer wait would false-trip the watchdog. The durable fix for
# SUSTAINED over-quota is a lighter/higher-quota model (the autopilot model picker) or a Bedrock
# quota increase; these retries absorb the bursts.
_THROTTLE_CODES = ("ThrottlingException", "ModelTimeoutException", "ServiceUnavailableException")
_BEDROCK_RETRIES = max(1, int(os.getenv("TAU_BEDROCK_RETRIES", "5")))
_BEDROCK_BACKOFF_CAP = max(2.0, float(os.getenv("TAU_BEDROCK_BACKOFF_CAP", "16")))


def _retry_sleep(attempt: int) -> None:
    """Exponential backoff (capped) with full jitter. The jitter de-syncs concurrent runs that all
    throttled at once (several autopilot users sharing one Bedrock quota) so they don't retry in
    lockstep and immediately re-throttle each other."""
    base = min(_BEDROCK_BACKOFF_CAP, 2.0 ** (attempt + 1))
    time.sleep(base + random.uniform(0.0, base * 0.5))


class LLMError(RuntimeError):
    """A model call that failed. str() is the detail for logs and for the code that reads it (the
    daily-quota and repair checks). ``public`` is what a user may read when that detail is the
    provider's own (a Bedrock or API error that names models, regions, ARNs or request ids); None
    when the message was written for users. Read it through public_message()."""

    def __init__(self, *args, public: Optional[str] = None):
        super().__init__(*args)
        self.public = public


# What a research session's failure reads as when the cause is the model provider. Model ids, regions
# and the provider's error text stay in the worker log.
UNREACHABLE_COPY = "The research model couldn't be reached just now, so the session stopped. Start it again in a few minutes."
CAPACITY_COPY = "The research models are at capacity right now, so the session stopped. Start it again in a little while."
STALLED_COPY = "The research model stopped responding, so the session stopped. Start it again."
UNUSABLE_COPY = "The research agent's replies couldn't be used, so the session stopped. Start it again."


def public_message(e: LLMError) -> str:
    """The words a user reads for this failure: never the provider's raw error."""
    return e.public or str(e)


class LLMThrottled(LLMError):
    """A Bedrock throttle that retries couldn't clear (incl. a daily token-quota exhaustion). Its own
    subclass so the model-fallback wrapper can tell 'this model is out of capacity, try the next one'
    apart from an ordinary LLMError (a real failure that every model would hit)."""
    pass


class LLMStalled(LLMError):
    """A streaming call that went silent mid-generation (no token for STREAM_STALL_SECONDS) — a
    model-side stall, not a prompt error. Its own subclass so the fallback wrapper fails it OVER to
    the next model (a fresh stream on a different model usually won't stall) instead of killing the run."""
    pass


def _is_daily_quota(e) -> bool:
    """A DAILY token-quota throttle ('Too many tokens per day') — it won't clear within a run's
    retry budget (it resets ~daily), so there's no point backing off; fall over to another model now."""
    return "per day" in str(e).lower()


# A model that hit its DAILY quota is skipped (not even attempted) for this long, so a sustained
# per-day exhaustion stops costing a wasted throttled round-trip on every single call. It auto-
# expires, so the preferred model is retried once the cooldown lapses (and re-cooled if still out).
_MODEL_COOLDOWN: Dict[str, float] = {}
_DAILY_COOLDOWN_SEC = max(60, int(os.getenv("TAU_DAILY_QUOTA_COOLDOWN_SEC", "1800")))


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: Dict) -> None:
        self.input_tokens += int(other.get("input_tokens") or 0)
        self.output_tokens += int(other.get("output_tokens") or 0)


# (system, messages) -> (text, usage dict). Swappable so tests never hit the network.
ModelFn = Callable[[str, List[Dict[str, str]]], "tuple[str, Dict]"]


def current_model() -> str:
    """The model id actually in use, for usage pricing."""
    return BEDROCK_MODEL if LLM_PROVIDER == "bedrock" else MODEL


def claude(system: str, messages: List[Dict[str, str]], model: "Optional[str]" = None,
           on_delta: "Optional[Callable[[str], None]]" = None) -> "tuple[str, Dict]":
    """Route to Bedrock or the Anthropic API based on APP_LLM_PROVIDER. `model` is
    the invokable Bedrock modelId the user chose (defaults to BEDROCK_MODEL). When `on_delta`
    is given, the Bedrock path STREAMS, calling on_delta(text) as each token arrives (the live
    research feed uses this); the Anthropic-direct path ignores it and returns in one shot."""
    return (_bedrock(system, messages, model, on_delta) if LLM_PROVIDER == "bedrock"
            else _anthropic_direct(system, messages))


def _is_sink_connection_error(exc: BaseException) -> bool:
    """A think-aloud sink failure that left a DB socket half-read (pymysql's
    'Packet sequence number wrong' / connection errors). Swallowing it would hand the
    NEXT query a desynced connection and fail cryptically, so it must surface to the
    caller's infra-error handler. Detected by top-level module so llm.py stays DB-agnostic."""
    return (type(exc).__module__ or "").split(".", 1)[0] == "pymysql"


def _safe_close_stream(resp) -> None:
    """Best-effort close of a converse_stream response so a pump thread blocked on its socket read
    unblocks. botocore's EventStream has no public close(), so this reaches the underlying raw
    stream if present and otherwise no-ops — the orphaned daemon then just dies on its own read
    timeout. ponytail: a lingering daemon socket for <=read_timeout is a bounded, rare cost (only on
    a genuine stall); a cleaner cancel would need botocore's private stream API."""
    try:
        stream = resp.get("stream") if isinstance(resp, dict) else None
        for obj in (stream, getattr(stream, "_raw_stream", None), getattr(stream, "_event_stream", None)):
            close = getattr(obj, "close", None)
            if callable(close):
                close()
                return
    except Exception:
        pass


def _bedrock_stream(client, kwargs: Dict[str, Any], on_delta: "Callable[[str], None]",
                    stall_seconds: float = STREAM_STALL_SECONDS) -> "tuple[str, Dict]":
    """converse_stream: push text deltas to on_delta as they arrive, return (full text, usage).
    A sink hiccup (a dropped render feed) must never kill generation, so on_delta is isolated —
    EXCEPT a DB connection desync, which is re-raised so the caller can reconnect rather than
    reuse a broken socket. ponytail: no in-function retry; a stream timeout is retried by _bedrock,
    creation/other errors fall back to the non-streaming converse path there.

    STALL GUARD: the blocking event read runs in a daemon pump thread that enqueues events; we
    consume them here with a per-token timeout, so a silently stalled stream aborts with an LLMError
    after `stall_seconds` instead of hanging until the run-level watchdog. on_delta and usage are
    handled HERE (the consumer thread), so the sink's DB writes stay on the caller's thread exactly
    as before — the pump thread only moves bytes, never touches the DB."""
    resp = client.converse_stream(**kwargs)
    q: "queue.Queue" = queue.Queue()
    _END = object()

    def _pump() -> None:
        try:
            for event in resp.get("stream", []):
                q.put(("ev", event))
        except BaseException as e:  # botocore stream/timeout error: hand it to the consumer to raise
            q.put(("err", e))
            return
        q.put(("done", _END))

    threading.Thread(target=_pump, name="bedrock-stream-pump", daemon=True).start()
    parts: List[str] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    while True:
        try:
            kind, payload = q.get(timeout=stall_seconds)
        except queue.Empty:
            _safe_close_stream(resp)
            raise LLMStalled("the model stalled mid-stream: no token for %ds. Aborting the call so the "
                             "run can recover instead of hanging." % int(stall_seconds), public=STALLED_COPY)
        if kind == "done":
            break
        if kind == "err":
            raise payload  # a real botocore error — _bedrock's retry/fallback decides what to do
        event = payload
        if "contentBlockDelta" in event:
            text = (event["contentBlockDelta"].get("delta") or {}).get("text", "")
            if text:
                parts.append(text)
                try:
                    on_delta(text)
                except Exception as e:
                    if _is_sink_connection_error(e):
                        raise  # DB desync — don't bury it, the connection is now unusable
                    # otherwise a cosmetic feed hiccup: keep generating
        elif "metadata" in event:
            u = event["metadata"].get("usage") or {}
            usage = {"input_tokens": u.get("inputTokens") or 0, "output_tokens": u.get("outputTokens") or 0}
    return "".join(parts), usage


def _bedrock(system: str, messages: List[Dict[str, str]], model: "Optional[str]" = None,
             on_delta: "Optional[Callable[[str], None]]" = None) -> "tuple[str, Dict]":
    """Call Bedrock with automatic model fallback: start at the requested model and, if its quota is
    exhausted (LLMThrottled, e.g. the daily token cap), drop to the next-best model in the catalog's
    FALLBACK_ORDER and retry. The chain is rebuilt every call, so once the preferred model's quota
    frees up it is used again automatically. A non-throttle failure propagates unchanged."""
    from app.adapters.llm import models_catalog as _catalog  # lazy: avoid an import cycle
    full = _catalog.fallback_chain_from(model or BEDROCK_MODEL)
    # Skip models still in a DAILY-quota cooldown: a per-day cap won't clear for hours, so once a
    # model trips it we stop paying a wasted round-trip on EVERY later call and go straight to the
    # next model. If ALL are cooling down, try the full chain anyway (better to attempt than refuse).
    now = time.monotonic()
    chain = [m for m in full if _MODEL_COOLDOWN.get(m, 0.0) <= now] or full
    last: "Optional[LLMError]" = None
    for i, mid in enumerate(chain):
        try:
            return _bedrock_once(system, messages, mid, on_delta)
        except (LLMThrottled, LLMStalled) as e:
            # Both mean "this model didn't produce a result" — quota exhaustion or a mid-stream
            # stall — so fail OVER to the next model instead of killing the run. Only a daily-quota
            # throttle gets a cooldown (a stall is transient, the model isn't out of capacity).
            last = e
            if isinstance(e, LLMThrottled) and _is_daily_quota(e):
                _MODEL_COOLDOWN[mid] = time.monotonic() + _DAILY_COOLDOWN_SEC  # auto-expires -> retried later
            if i + 1 < len(chain):
                why = "quota exhausted" if isinstance(e, LLMThrottled) else "stalled mid-stream"
                print("[llm] %s %s (%s); falling back to %s" % (mid, why, e, chain[i + 1]), flush=True)
                continue
            raise
    raise last if last else LLMError("no model to call", public=UNREACHABLE_COPY)  # unreachable: chain is never empty


def _bedrock_once(system: str, messages: List[Dict[str, str]], model: "Optional[str]" = None,
                  on_delta: "Optional[Callable[[str], None]]" = None) -> "tuple[str, Dict]":
    """One Bedrock Converse call for a SINGLE model (Claude/Nova/Llama/…), with the throttle/timeout
    retries. Raises LLMThrottled when a throttle outlives the retries so the fallback wrapper can
    switch models; other failures raise LLMError."""
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError
    except ImportError:
        raise LLMError("boto3 is required for Bedrock but is not installed.", public=UNREACHABLE_COPY)
    model_id = model or BEDROCK_MODEL
    conv = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages]
    kwargs: Dict[str, Any] = {"modelId": model_id, "messages": conv, "inferenceConfig": {"maxTokens": MAX_TOKENS}}
    if system:
        kwargs["system"] = [{"text": system}]
    # A large hypothesis-generation response takes minutes; botocore's default 60s read timeout
    # was failing whole research runs. Give it room, and let a transient timeout retry below.
    # (Streaming resets the read timer on each delta, so this mainly guards the non-streaming path.)
    cfg = Config(read_timeout=600, connect_timeout=15, retries={"max_attempts": 0})
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION, config=cfg)
    if on_delta is not None:
        # Live-feed streaming. Needs bedrock:InvokeModelWithResponseStream on the worker role; if
        # that's missing (AccessDenied) or streaming throttles/errors at setup, fall through to the
        # non-streaming converse below so research keeps working (just without live tokens).
        # A read timeout raised DURING event-stream iteration is a ResponseStreamingError/
        # EventStreamError, NOT a plain ReadTimeoutError, so it used to skip every retry and fail
        # the session raw ("Bedrock call failed: Read timeout"). Retry those here before falling
        # back. (A retry may re-emit already-streamed tokens into the live feed — cosmetic, and far
        # better than killing the run.)
        stream_timeouts = [ReadTimeoutError]
        for name in ("ResponseStreamingError", "EventStreamError"):
            try:
                stream_timeouts.append(getattr(__import__("botocore.exceptions", fromlist=[name]), name))
            except (ImportError, AttributeError):
                pass
        stream_timeouts = tuple(stream_timeouts)
        for attempt in range(_BEDROCK_RETRIES + 1):
            try:
                text, usage = _bedrock_stream(client, kwargs, on_delta)
                if text.strip():
                    return text, usage
                break  # empty stream -> let the non-streaming converse produce the reply
            except LLMError:
                # A mid-stream STALL (the stall guard fired). Falling back to the non-streaming
                # converse would just stall again on its own long read timeout, so abort the call
                # and let the research loop handle the LLMError — fast, clean, not a 10-min hang.
                raise
            except stream_timeouts:
                if attempt < _BEDROCK_RETRIES:
                    _retry_sleep(attempt)
                    continue
                break  # exhausted retries -> fall back to non-streaming converse
            except ClientError as e:
                # A throttle on the stream used to fall straight through to converse, which then
                # throttled too — wasting the whole call. Back off and retry the stream first (but
                # not for a daily-quota throttle, which won't clear — drop to converse, which raises
                # LLMThrottled so the wrapper switches models).
                code = e.response.get("Error", {}).get("Code", "")
                if code in _THROTTLE_CODES and not _is_daily_quota(e) and attempt < _BEDROCK_RETRIES:
                    _retry_sleep(attempt)
                    continue
                break  # non-throttle, daily-quota, or exhausted -> fall back to non-streaming converse
            except Exception as e:
                if _is_sink_connection_error(e):
                    raise  # DB desync from the sink — surface it; never hide it in the fallback
                break
    for attempt in range(_BEDROCK_RETRIES + 1):
        try:
            resp = client.converse(**kwargs)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in _THROTTLE_CODES:
                # A DAILY token-quota throttle won't clear within a run, so don't burn the backoff —
                # raise LLMThrottled now and let the wrapper switch models. A transient throttle
                # retries with backoff first, then becomes LLMThrottled once the budget is spent.
                if not _is_daily_quota(e) and attempt < _BEDROCK_RETRIES:
                    _retry_sleep(attempt)
                    continue
                raise LLMThrottled("%s on '%s': %s" % (code, model_id, e), public=CAPACITY_COPY)
            raise LLMError("Bedrock call failed (%s). Model '%s' may need access enabled in the Bedrock console for %s."
                           % (code or e, model_id, AWS_REGION), public=UNREACHABLE_COPY)
        except (ReadTimeoutError, ConnectTimeoutError) as e:
            if attempt < _BEDROCK_RETRIES:
                _retry_sleep(attempt)
                continue
            raise LLMError("Bedrock call timed out after retries: %s" % e, public=UNREACHABLE_COPY)
        except Exception as e:
            raise LLMError("Bedrock call failed: %s" % e, public=UNREACHABLE_COPY)
        msg = (resp.get("output") or {}).get("message") or {}
        content = msg.get("content") or []
        text = "".join(b.get("text", "") for b in content if "text" in b)
        if not text.strip():
            # Reasoning models (e.g. DeepSeek R1) can emit only reasoningContent blocks; the
            # answer — and the JSON extract_json looks for — lives in the reasoning text.
            text = "".join((b.get("reasoningContent", {}).get("reasoningText", {}) or {}).get("text", "")
                           for b in content if "reasoningContent" in b)
        u = resp.get("usage") or {}
        return text, {"input_tokens": u.get("inputTokens") or 0, "output_tokens": u.get("outputTokens") or 0}
    raise LLMError("Bedrock call failed after retries.", public=UNREACHABLE_COPY)


def _anthropic_direct(system: str, messages: List[Dict[str, str]]) -> "tuple[str, Dict]":
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set on the worker.", public=UNREACHABLE_COPY)
    body = {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system, "messages": messages}
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    for attempt in range(4):
        try:
            resp = requests.post(ANTHROPIC_URL, json=body, headers=headers, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            if attempt == 3:
                raise LLMError("Could not reach the model: %s" % e, public=UNREACHABLE_COPY)
            time.sleep(2 ** attempt)
            continue
        if resp.status_code in (429, 500, 502, 503, 529) and attempt < 3:
            time.sleep(float(resp.headers.get("retry-after") or 2 ** (attempt + 1)))
            continue
        if resp.status_code >= 400:
            raise LLMError("Model call failed (%s): %s" % (resp.status_code, resp.text[:300]), public=UNREACHABLE_COPY)
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        return text, data.get("usage") or {}
    raise LLMError("Model call failed after retries.", public=UNREACHABLE_COPY)


_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


_LIST_KEY = re.compile(r'^\s*\{\s*"([A-Za-z_]+)"\s*:\s*\[')


def _salvage_list(candidate: str) -> Optional[Dict[str, Any]]:
    """A broken `{"key": [item, item, ...` reply (a stray quote or a clipped tail in item k, prod run
    2830): keep the complete items before the break instead of re-generating the whole batch. Only
    for a reply whose FIRST key holds a list; the caller's check still validates every kept item."""
    m = _LIST_KEY.match(candidate)
    if not m:
        return None
    dec, pos, items = json.JSONDecoder(), m.end(), []
    while True:
        while pos < len(candidate) and candidate[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(candidate) or candidate[pos] == "]":
            break
        try:
            item, pos = dec.raw_decode(candidate, pos)
        except ValueError:
            break
        items.append(item)
    return {m.group(1): items} if items else None


def extract_json(text: str) -> Dict[str, Any]:
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    if not candidate:
        raise ValueError("no JSON object in the reply")
    try:
        value = json.loads(candidate)
    except ValueError:
        value = _salvage_list(candidate)
        if value is None:
            raise
    if not isinstance(value, dict):
        raise ValueError("reply JSON must be an object")
    return value


def ask_json(
    model: ModelFn,
    system: str,
    messages: List[Dict[str, str]],
    check: Callable[[Dict[str, Any]], Any],
    usage: Usage,
) -> Any:
    """Call the model, parse a JSON object, run `check` (which validates and
    returns the cleaned value or raises ValueError). One repair round."""
    convo = list(messages)
    last_error = ""
    # Three tries: large structured JSON (the proposer's hypothesis batch) occasionally comes back
    # malformed or clipped, and one repair isn't always enough. Echo a generous slice of the broken
    # reply (not 8k — the error is often past there, e.g. a clipped tail at ~15k) so the model can
    # actually see and fix what was wrong.
    for attempt in range(3):
        text, u = model(system, convo)
        usage.add(u)
        try:
            return check(extract_json(text))
        except (ValueError, KeyError, TypeError) as e:
            last_error = str(e)[:1500]
            convo = convo + [
                {"role": "assistant", "content": text[:24000]},
                {
                    "role": "user",
                    "content": "That reply was rejected: %s\nReturn ONE valid, complete JSON object only "
                               "(no prose, no markdown fence). If it was cut off, make it shorter so it "
                               "fits — fewer items is fine." % last_error,
                },
            ]
    raise LLMError("The agent's reply could not be used: %s" % last_error, public=UNUSABLE_COPY)
