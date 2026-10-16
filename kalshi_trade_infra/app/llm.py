"""Claude over plain HTTPS, plus the JSON discipline every agent call uses.

The agent's only outputs are JSON objects that host code validates; model text
is data, never instructions. `ask_json` gives the model exactly one chance to
repair a reply that does not parse or does not validate, then fails loudly.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = os.getenv("APP_AGENT_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = int(os.getenv("APP_AGENT_MAX_TOKENS", "6000"))
TIMEOUT_SECONDS = 180

# "bedrock" bills Claude through AWS (uses AWS credits, no Anthropic key, auth
# via the instance role); anything else uses the Anthropic API directly.
LLM_PROVIDER = os.getenv("APP_LLM_PROVIDER", "anthropic").lower()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
# A Bedrock model id or cross-region inference-profile id. Must be enabled in
# the account's Bedrock "Model access" for AWS_REGION.
BEDROCK_MODEL = os.getenv("APP_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")


class LLMError(RuntimeError):
    pass


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


def claude(system: str, messages: List[Dict[str, str]], model: "Optional[str]" = None) -> "tuple[str, Dict]":
    """Route to Bedrock or the Anthropic API based on APP_LLM_PROVIDER. `model` is
    the invokable Bedrock modelId the user chose (defaults to BEDROCK_MODEL)."""
    return _bedrock(system, messages, model) if LLM_PROVIDER == "bedrock" else _anthropic_direct(system, messages)


def _bedrock(system: str, messages: List[Dict[str, str]], model: "Optional[str]" = None) -> "tuple[str, Dict]":
    """One code path for every provider on Bedrock via the Converse API, which is
    unified across Claude/Nova/Llama/… and returns text + token usage the same way."""
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        raise LLMError("boto3 is required for Bedrock but is not installed.")
    model_id = model or BEDROCK_MODEL
    conv = [{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages]
    kwargs: Dict[str, Any] = {"modelId": model_id, "messages": conv, "inferenceConfig": {"maxTokens": MAX_TOKENS}}
    if system:
        kwargs["system"] = [{"text": system}]
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    for attempt in range(4):
        try:
            resp = client.converse(**kwargs)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ThrottlingException", "ModelTimeoutException", "ServiceUnavailableException") and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise LLMError("Bedrock call failed (%s). Model '%s' may need access enabled in the Bedrock console for %s."
                           % (code or e, model_id, AWS_REGION))
        except Exception as e:
            raise LLMError("Bedrock call failed: %s" % e)
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
    raise LLMError("Bedrock call failed after retries.")


def _anthropic_direct(system: str, messages: List[Dict[str, str]]) -> "tuple[str, Dict]":
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set on the worker.")
    body = {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system, "messages": messages}
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    for attempt in range(4):
        try:
            resp = requests.post(ANTHROPIC_URL, json=body, headers=headers, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            if attempt == 3:
                raise LLMError("Could not reach the model: %s" % e)
            time.sleep(2 ** attempt)
            continue
        if resp.status_code in (429, 500, 502, 503, 529) and attempt < 3:
            time.sleep(float(resp.headers.get("retry-after") or 2 ** (attempt + 1)))
            continue
        if resp.status_code >= 400:
            raise LLMError("Model call failed (%s): %s" % (resp.status_code, resp.text[:300]))
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        return text, data.get("usage") or {}
    raise LLMError("Model call failed after retries.")


_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


def extract_json(text: str) -> Dict[str, Any]:
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    if not candidate:
        raise ValueError("no JSON object in the reply")
    value = json.loads(candidate)
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
    for attempt in range(2):
        text, u = model(system, convo)
        usage.add(u)
        try:
            return check(extract_json(text))
        except (ValueError, KeyError, TypeError) as e:
            last_error = str(e)[:1500]
            convo = convo + [
                {"role": "assistant", "content": text[:8000]},
                {
                    "role": "user",
                    "content": "That reply was rejected: %s\nReply again with one corrected JSON object only." % last_error,
                },
            ]
    raise LLMError("The agent's reply could not be used: %s" % last_error)
