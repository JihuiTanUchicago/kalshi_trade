"""The LLM models a user can pick to run their research - the single source of
truth for the dropdown, server validation, the agent's Bedrock call, and
billing. Add or remove a model here and every one of those follows.

Each entry carries its exact per-token price so billing charges the model the
user actually ran. Prices are USD per 1,000,000 tokens (input, output) - the
same unit as billing.PRICES - so metering stays consistent.

Price sources (verified 2026-10-15):
  - Claude models: Anthropic published list price (what we bill; our Bedrock
    cost is covered by AWS credits - that gap is margin, same as the rest of
    billing.PRICES). https://www.anthropic.com/pricing
  - Nova / Llama models: AWS Bedrock on-demand base price via the AWS Pricing
    API (`aws pricing get-products --service-code AmazonBedrock`,
    us-east-1, base Input/Output token usagetype - not batch/cache/custom).
Every modelId below was confirmed ACTIVE and invokable via the Bedrock
Converse API in us-east-1 on 2026-10-15.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ModelChoice:
    key: str            # stable id stored on the run and sent by the dropdown
    label: str          # what the user sees
    provider: str       # eyebrow / grouping
    model_id: str       # invokable Bedrock (inference-profile) modelId
    price_in: Decimal   # USD per 1,000,000 input tokens
    price_out: Decimal  # USD per 1,000,000 output tokens


# The default must stay the current Sonnet (matches llm.BEDROCK_MODEL), so an
# existing run with no model chosen bills and behaves exactly as before.
DEFAULT_KEY = "sonnet-4-5"

MODELS: Dict[str, ModelChoice] = {
    m.key: m
    for m in [
        # -- Anthropic (Anthropic list price, 2026-10-15) ---------------------
        ModelChoice("sonnet-4-5", "Claude Sonnet 4.5", "Anthropic",
                    "us.anthropic.claude-sonnet-4-5-20250929-v1:0", Decimal("3"), Decimal("15")),
        ModelChoice("opus-4-5", "Claude Opus 4.5", "Anthropic",
                    "us.anthropic.claude-opus-4-5-20251101-v1:0", Decimal("5"), Decimal("25")),
        ModelChoice("haiku-4-5", "Claude Haiku 4.5", "Anthropic",
                    "us.anthropic.claude-haiku-4-5-20251001-v1:0", Decimal("1"), Decimal("5")),
        # -- Amazon Nova (AWS Pricing API, 2026-10-15) ------------------------
        ModelChoice("nova-pro", "Amazon Nova Pro", "Amazon",
                    "us.amazon.nova-pro-v1:0", Decimal("0.8"), Decimal("3.2")),
        ModelChoice("nova-lite", "Amazon Nova Lite", "Amazon",
                    "us.amazon.nova-lite-v1:0", Decimal("0.06"), Decimal("0.24")),
        ModelChoice("nova-micro", "Amazon Nova Micro", "Amazon",
                    "us.amazon.nova-micro-v1:0", Decimal("0.035"), Decimal("0.14")),
        # -- Meta Llama (AWS Pricing API, 2026-10-15) -------------------------
        ModelChoice("llama-3-3-70b", "Llama 3.3 70B", "Meta",
                    "us.meta.llama3-3-70b-instruct-v1:0", Decimal("0.72"), Decimal("0.72")),
        ModelChoice("llama-4-maverick", "Llama 4 Maverick", "Meta",
                    "us.meta.llama4-maverick-17b-instruct-v1:0", Decimal("0.24"), Decimal("0.97")),
    ]
}

# modelId -> price, for billing to resolve a run's chosen model exactly.
_PRICE_BY_MODEL_ID: Dict[str, Tuple[Decimal, Decimal]] = {
    m.model_id: (m.price_in, m.price_out) for m in MODELS.values()
}


def default() -> ModelChoice:
    return MODELS[DEFAULT_KEY]


def get(key: Optional[str]) -> Optional[ModelChoice]:
    """The chosen model, or None for an unknown/absent key (caller uses the default)."""
    return MODELS.get(key) if key else None


def resolve(key: Optional[str]) -> ModelChoice:
    """The chosen model, falling back to the default (NULL model = default Sonnet)."""
    return get(key) or default()


def price_for_model_id(model_id: Optional[str]) -> Optional[Tuple[Decimal, Decimal]]:
    """Exact per-1M (input, output) price for an invokable modelId, or None."""
    return _PRICE_BY_MODEL_ID.get(model_id or "")


def catalog_json() -> List[Dict]:
    """The registry for the research-form dropdown (GET /api/models)."""
    return [{"key": m.key, "label": m.label, "provider": m.provider,
             "default": m.key == DEFAULT_KEY} for m in MODELS.values()]
