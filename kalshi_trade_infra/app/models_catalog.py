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
Converse API in us-east-1 on 2026-10-15 (Opus 4.6 / Sonnet 4.6 on 2026-10-24).

PENDING holds newer Claude models whose inference profiles are ACTIVE in us-east-1
but which this AWS account can't invoke yet (Converse returns AccessDenied "not
available for this account", checked 2026-10-24). They show in the dropdown as
disabled "access pending" options and are NOT in MODELS, so the server rejects
them. Once Bedrock grants access, move an entry from PENDING into MODELS.
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
    available: bool = True  # False = listed in the dropdown but not selectable yet


# Default research model (matches llm.BEDROCK_MODEL). A run with no model chosen
# resolves to this for both the call and billing.
DEFAULT_KEY = "opus-4-6"

MODELS: Dict[str, ModelChoice] = {
    m.key: m
    for m in [
        # -- Anthropic (Anthropic list price, 2026-10-15; 4.6 added 2026-10-24) -
        ModelChoice("opus-4-6", "Claude Opus 4.6", "Anthropic",
                    "us.anthropic.claude-opus-4-6-v1", Decimal("5"), Decimal("25")),
        ModelChoice("sonnet-4-6", "Claude Sonnet 4.6", "Anthropic",
                    "us.anthropic.claude-sonnet-4-6", Decimal("3"), Decimal("15")),
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
        # -- Writer (Bedrock agreement rate card, 2026-10-15) ----------------
        ModelChoice("palmyra-x5", "Writer Palmyra X5", "Writer",
                    "us.writer.palmyra-x5-v1:0", Decimal("0.6"), Decimal("6")),
        # -- DeepSeek (Bedrock US inference profile, 2026-10-15) --------------
        # Reasoning model: Converse returns only reasoningContent; llm._bedrock falls back to it.
        ModelChoice("deepseek-r1", "DeepSeek R1", "DeepSeek",
                    "us.deepseek.r1-v1:0", Decimal("1.35"), Decimal("5.4")),
    ]
}

# Newer Claude models awaiting Bedrock access for this account (see the module docstring).
# Anthropic list price, 2026-10-24. Haiku 5.5's price is for prompts up to 100K tokens.
PENDING: List[ModelChoice] = [
    ModelChoice("opus-5-5", "Claude Opus 5.5", "Anthropic",
                "us.anthropic.claude-opus-5-5", Decimal("4"), Decimal("20"), available=False),
    ModelChoice("sonnet-5-5", "Claude Sonnet 5.5", "Anthropic",
                "us.anthropic.claude-sonnet-5-5", Decimal("2"), Decimal("10"), available=False),
    ModelChoice("haiku-5-5", "Claude Haiku 5.5", "Anthropic",
                "us.anthropic.claude-haiku-5-5", Decimal("0.1"), Decimal("0.5"), available=False),
    ModelChoice("fable-5-1", "Claude Fable 5.1", "Anthropic",
                "us.anthropic.claude-fable-5-1", Decimal("10"), Decimal("50"), available=False),
]

def global_twin(model_id: str) -> Optional[str]:
    """The global cross-region inference profile of a us.* profile, which draws on its own, larger
    daily token quota (2026-10-25: us Opus 4.6 was out for the day while global served it)."""
    return "global." + model_id[len("us."):] if model_id.startswith("us.anthropic.") else None


# modelId -> price, for billing to resolve a run's chosen model exactly. A global twin bills at its
# us profile's price (Bedrock's global profiles cost the same or less).
_PRICE_BY_MODEL_ID: Dict[str, Tuple[Decimal, Decimal]] = {
    mid: (m.price_in, m.price_out) for m in MODELS.values()
    for mid in (m.model_id, global_twin(m.model_id)) if mid
}


def default() -> ModelChoice:
    return MODELS[DEFAULT_KEY]


def get(key: Optional[str]) -> Optional[ModelChoice]:
    """The chosen model, or None for an unknown/absent key (caller uses the default)."""
    return MODELS.get(key) if key else None


def resolve(key: Optional[str]) -> ModelChoice:
    """The chosen model, falling back to the default (NULL model = DEFAULT_KEY)."""
    return get(key) or default()


def price_for_model_id(model_id: Optional[str]) -> Optional[Tuple[Decimal, Decimal]]:
    """Exact per-1M (input, output) price for an invokable modelId, or None."""
    return _PRICE_BY_MODEL_ID.get(model_id or "")


def catalog_json() -> List[Dict]:
    """The registry for the research-form dropdown (GET /api/models). Pending models come first,
    flagged available=False, so the UI can show them as disabled "access pending" options."""
    return [{"key": m.key, "label": m.label, "provider": m.provider,
             "default": m.key == DEFAULT_KEY, "available": m.available}
            for m in PENDING + list(MODELS.values())]


# Capability-ordered fallback chain (best -> most-available). When a model's Bedrock quota is
# exhausted (esp. the daily token cap), the LLM layer drops to the next model here and retries,
# then naturally recovers to the preferred one once it's free again (the chain is rebuilt per call).
# Kept to the Claude family: the research/agent prompts and their strict JSON replies are tuned for
# Claude, so a non-Claude fallback would trade one failure mode (throttle) for another (bad output).
# Every us profile has a DAILY token cap (Opus 4.6 ran out on 2026-10-25 despite looking uncapped on
# 2026-10-24; Opus 4.5 is 6.75M/day on us, 13.5M on global). Opus 4.5 comes next at
# the same price, so a per-minute throttle or a stall on 4.6 stays on Opus before dropping to Sonnet.
FALLBACK_ORDER: List[str] = ["opus-4-6", "opus-4-5", "sonnet-4-6", "sonnet-4-5", "haiku-4-5"]


def fallback_chain_from(model_id: str) -> List[str]:
    """The invokable modelIds to try in order, starting at `model_id`: itself, then each lower-tier
    model in FALLBACK_ORDER, each followed by its global twin so an exhausted us quota overflows to
    the same model before dropping a tier. A model_id outside the chain yields just [model_id]."""
    key = next((m.key for m in MODELS.values() if m.model_id == model_id), None)
    if key not in FALLBACK_ORDER:
        return [model_id]
    return [mid for k in FALLBACK_ORDER[FALLBACK_ORDER.index(key):]
            for mid in (MODELS[k].model_id, global_twin(MODELS[k].model_id)) if mid]
