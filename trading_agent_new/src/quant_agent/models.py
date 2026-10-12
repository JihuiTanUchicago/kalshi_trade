"""LLM adapters and durable, conservative API-spend accounting.

The harness exchanges text plus usage. Provider tool-calling formats and SDKs
never enter workflow code. Each failed/ambiguous call retains its reservation.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Protocol
from urllib.error import HTTPError, URLError
from http.client import HTTPException
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import json
import os
import uuid

from .common import AgentError, GateError, canonical, finite, integer, utcnow
from .contracts import ModelRequest, ModelResponse
from .store import Store


class Model(Protocol):
    name: str

    def generate(self, request: ModelRequest) -> ModelResponse: ...


class ProviderError(AgentError):
    def __init__(self, code: str, retryable: bool = False):
        super().__init__(f"Model request failed ({code}); no raw response logged")
        self.retryable = retryable


class ReplayModel:
    """A deterministic integration fixture, never evidence of model intelligence."""
    name = "scripted-replay"

    def __init__(self, actions: list[dict]):
        self.actions = iter(actions)

    def generate(self, request: ModelRequest) -> ModelResponse:
        try:
            content = canonical(next(self.actions))
        except StopIteration as exc:
            raise ProviderError("replay_exhausted") from exc
        return ModelResponse(content, 0, 0, {"provider": self.name, "fixture": True})


class HTTPModel:
    def __init__(self, config: dict, transport=None):
        allowed = {"adapter","model","endpoint","api_key_env","input_per_million","output_per_million",
                   "token_limit_field","supports_temperature","local_no_auth"}
        if set(config)-allowed: raise GateError("Unknown model configuration fields; credentials must use named environment variables")
        self.config = config
        self.name = config["model"]
        self.style = config["adapter"]
        if self.style not in {"chat_completions", "anthropic_messages"}:
            raise GateError("Unsupported model adapter")
        self.url = config["endpoint"]
        parsed = urlparse(self.url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            raise GateError("Model endpoints require HTTPS (or a local test server)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise GateError("Do not place credentials in endpoint URLs")
        if config.get("local_no_auth",False) and parsed.hostname not in {"localhost","127.0.0.1"}:
            raise GateError("Zero-cost/no-auth model routes must use a local endpoint")
        self.transport = transport or self._send

    def _send(self, url, body, headers):
        try:
            with urlopen(Request(url, data=canonical(body).encode(), headers=headers, method="POST"), timeout=60) as r:
                raw = r.read(2_000_001)
        except HTTPError as exc:
            raise ProviderError(f"HTTP_{exc.code}", exc.code in {408, 429, 500, 502, 503, 504}) from None
        except (OSError, HTTPException):
            raise ProviderError("network_or_timeout", True) from None
        if len(raw) > 2_000_000:
            raise ProviderError("response_too_large")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProviderError("invalid_json") from None

    def generate(self, request: ModelRequest) -> ModelResponse:
        api_key = os.environ.get(self.config.get("api_key_env", ""), "")
        if not api_key and not self.config.get("local_no_auth", False):
            raise GateError("Configured model credential is missing")
        headers = {"Content-Type": "application/json"}
        if self.style == "chat_completions":
            headers["Authorization"] = f"Bearer {api_key}"
            token_field = self.config.get("token_limit_field","max_tokens")
            if token_field not in {"max_tokens","max_completion_tokens"}: raise GateError("Unsupported completion token limit field")
            body = {"model": self.name, "messages": request.messages,token_field:request.max_output_tokens}
            if self.config.get("supports_temperature",True): body["temperature"] = request.temperature
        else:
            headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
            body = {"model": self.name, "system": "\n".join(m["content"] for m in request.messages if m["role"] == "system"),
                    "messages": [m for m in request.messages if m["role"] != "system"],
                    "max_tokens": request.max_output_tokens, "temperature": request.temperature}
        raw = self.transport(self.url, body, headers)
        try:
            if self.style == "chat_completions":
                content = raw["choices"][0]["message"]["content"]
                used = raw["usage"]
                incoming, outgoing = used["prompt_tokens"], used["completion_tokens"]
            else:
                content = "".join(c["text"] for c in raw["content"] if c.get("type") == "text")
                used = raw["usage"]
                incoming, outgoing = used["input_tokens"], used["output_tokens"]
            incoming, outgoing = integer(incoming, "input tokens"), integer(outgoing, "output tokens")
            if not isinstance(content, str) or not content:
                raise ValueError()
        except (KeyError, TypeError, ValueError, IndexError, GateError):
            raise ProviderError("unsupported_response_or_usage") from None
        # No reasoning fields, auth, raw headers or hidden traces are persisted.
        return ModelResponse(content, incoming, outgoing,
                             {"provider": self.style, "model": self.name, "request_id": raw.get("id", ""),
                              "served_model":raw.get("model", ""),"system_fingerprint":raw.get("system_fingerprint", "")})


class Budget:
    def __init__(self, store: Store, campaign: str, cap: float):
        self.store, self.campaign = store, campaign
        cap = finite(cap, "campaign cap")
        if not 0 <= cap <= 50:
            raise GateError("V1 API validation campaigns must be capped at $50 or less")
        with store.transaction():
            existing = store.db.execute("SELECT cap FROM budgets WHERE campaign=?", (campaign,)).fetchone()
            if existing and cap > existing[0]:
                raise GateError("An existing campaign cap cannot be raised")
            store.db.execute("INSERT INTO budgets VALUES(?,?) ON CONFLICT(campaign) DO UPDATE SET cap=excluded.cap",
                             (campaign, cap))
            if self.used() > cap + 1e-10:
                raise GateError("Cap cannot be reduced below recorded expenditure/reservations")

    def used(self) -> float:
        row = self.store.db.execute("SELECT COALESCE(SUM(COALESCE(actual,amount)),0) FROM reservations WHERE campaign=?",
                                    (self.campaign,)).fetchone()
        return row[0]

    def reserve(self, amount: float) -> str:
        amount = finite(amount, "request reservation")
        if amount < 0:
            raise GateError("Negative request reservation")
        key = uuid.uuid4().hex
        with self.store.transaction():
            cap = self.store.db.execute("SELECT cap FROM budgets WHERE campaign=?", (self.campaign,)).fetchone()[0]
            if self.used() + amount > cap + 1e-10:
                raise GateError("API budget exhausted before sending a request")
            total = self.store.db.execute("SELECT COALESCE(SUM(COALESCE(actual,amount)),0) FROM reservations").fetchone()[0]
            if total + amount > 50 + 1e-10:
                raise GateError("Total V1 API validation budget exhausted across all campaigns")
            self.store.db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?)",
                                  (key, self.campaign, amount, None, "reserved", utcnow()))
        return key

    def finish(self, key: str, actual: float | None):
        with self.store.transaction():
            row = self.store.db.execute("SELECT * FROM reservations WHERE id=? AND campaign=?", (key, self.campaign)).fetchone()
            if row is None or row["status"] != "reserved":
                raise GateError("Unknown or already settled request reservation")
            if actual is not None:
                actual = finite(actual, "actual request cost")
                if actual < 0:
                    raise GateError("Negative billed cost")
            self.store.db.execute("UPDATE reservations SET actual=?,status=? WHERE id=?",
                                  (actual, "settled" if actual is not None else "unknown", key))


class MeteredModel:
    def __init__(self, model: Model, budget: Budget, input_per_million: float, output_per_million: float,
                 max_decisions: int = 20, max_input_tokens: int = 64_000, max_output_tokens: int = 8000, episode_id: str | None = None):
        self.model, self.budget, self.name = model, budget, model.name
        self.input_price = finite(input_per_million, "input token price")
        self.output_price = finite(output_per_million, "output token price")
        if min(self.input_price, self.output_price) < 0:
            raise GateError("Prices cannot be negative")
        self.max_decisions, self.max_in, self.max_out = max_decisions, max_input_tokens, max_output_tokens
        self.episode_id = episode_id
        counters = budget.store.control(f"model_episode:{episode_id}",{}) if episode_id else {}
        self.calls,self.tokens_in,self.tokens_out = (counters.get(k,0) for k in ("calls","input","output"))

    def _persist(self):
        if self.episode_id:
            self.budget.store.set_control(f"model_episode:{self.episode_id}",{"calls":self.calls,"input":self.tokens_in,"output":self.tokens_out})

    def generate(self, request: ModelRequest) -> ModelResponse:
        # UTF-8 byte count plus explicit chat overhead is conservative for the
        # supported text interfaces. Pin endpoint/token pricing per campaign.
        ceiling_in = len(canonical(request.messages).encode()) + 2048
        if self.calls >= self.max_decisions or self.tokens_in + ceiling_in > self.max_in or self.tokens_out + request.max_output_tokens > self.max_out:
            raise GateError("Episode decision/token budget exhausted")
        estimate = (ceiling_in * self.input_price + request.max_output_tokens * self.output_price) / 1_000_000
        key = self.budget.reserve(estimate)
        self.calls += 1
        self.tokens_in += ceiling_in
        self.tokens_out += request.max_output_tokens
        # Persist the worst case before network IO, so process death during a
        # request cannot reset the episode budget on resume.
        self._persist()
        try:
            response = self.model.generate(request)
        except BaseException:
            self.budget.finish(key, None)
            # Uncertain requests consume the reserved token allowance too.
            raise
        actual = (response.input_tokens * self.input_price + response.output_tokens * self.output_price) / 1_000_000
        self.budget.finish(key, actual)
        self.tokens_in += response.input_tokens-ceiling_in
        self.tokens_out += response.output_tokens-request.max_output_tokens
        self._persist()
        if response.input_tokens > ceiling_in or response.output_tokens > request.max_output_tokens:
            raise GateError("Provider exceeded the declared usage bound; campaign stopped")
        self.budget.store.event(None, "model_usage", {"campaign": self.budget.campaign, "model": self.name,
                               "input_tokens": response.input_tokens, "output_tokens": response.output_tokens, "cost": actual,
                               "served_model":str(response.metadata.get("served_model", ""))[:200],
                               "system_fingerprint":str(response.metadata.get("system_fingerprint", ""))[:200]})
        return response
