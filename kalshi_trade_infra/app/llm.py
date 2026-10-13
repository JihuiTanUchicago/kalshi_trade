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
from typing import Any, Callable, Dict, List

import requests

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = os.getenv("APP_AGENT_MODEL", "claude-sonnet-5-5")
MAX_TOKENS = int(os.getenv("APP_AGENT_MAX_TOKENS", "6000"))
TIMEOUT_SECONDS = 180


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


def claude(system: str, messages: List[Dict[str, str]]) -> "tuple[str, Dict]":
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
