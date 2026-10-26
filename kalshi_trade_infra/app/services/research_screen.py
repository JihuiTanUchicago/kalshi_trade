"""Tiered research models: a cheaper model proposes and screens, the run's model develops survivors.

Most research spend goes to ideas that die on the research fold (about 95% of them). On a run in
the SCREEN arm, the cheaper model writes the proposals and walks each thesis's develop loop on its
own. The run's model (the developer) takes over only when the screen wants to commit a thesis, or
runs out of screen steps while still refining, and always keeps DEVELOPER_MIN_STEPS steps of its
own to refine, commit or abandon. A thesis the screen abandons is gone, except for a deterministic
AUDIT_SHARE sample that the developer re-judges from the same prompt: that measures how often the
screen kills an idea the developer would have kept, and a rescued idea goes on with the developer.

Runs split by run id into the screen arm (SCREEN_SHARE of runs) and the control arm (one model for
every step, as before), so ideas tested per dollar and the gate-reach rate compare like for like.
Each run logs one `screen` verdict with its arm, the screen model's tokens (billed and priced at
that model's rate) and the screen's tallies; rsi.run_card reads it.

Knobs (env): APP_SCREEN_MODEL ("auto" = one tier down from the run's model, "off", or a catalog
key), APP_SCREEN_SHARE (0..1 of runs in the screen arm), APP_SCREEN_AUDIT (0..1 of screen
abandons the developer re-judges).
"""
from __future__ import annotations

import os
import zlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Optional

from app.adapters.llm import models_catalog as catalog
from app.adapters.llm.llm import ModelFn, Usage

SCREEN_MODEL = os.getenv("APP_SCREEN_MODEL", "auto").strip().lower()
# 0, not 0.5: stopped 2026-10-25 08:50Z. Over ~58 screen-arm ideas the screen developed none and
# handed none over (control developed ~9%, P(0 of 41+) < 0.03), and the developer rescued ~25% of the
# audited screen drops. It saved ~30% per idea, but research is judged on passes, not spend.
SCREEN_SHARE = min(1.0, max(0.0, float(os.getenv("APP_SCREEN_SHARE", "0"))))
AUDIT_SHARE = min(1.0, max(0.0, float(os.getenv("APP_SCREEN_AUDIT", "0.25"))))
DEVELOPER_MIN_STEPS = 3

# One tier down from the developer. A model with no entry (Haiku, non-Claude) runs unscreened.
_TIER_DOWN = {"opus-4-6": "sonnet-4-6", "opus-4-5": "sonnet-4-6",
              "sonnet-4-6": "haiku-4-5", "sonnet-4-5": "haiku-4-5"}


def _bucket(*parts) -> float:
    """A stable uniform draw in [0, 1) from the parts, the same on every worker and every resume."""
    return (zlib.crc32("|".join(str(p) for p in parts).encode()) % 10000) / 10000.0


def in_screen_arm(run_id: int) -> bool:
    return _bucket("arm", run_id) < SCREEN_SHARE


def screen_choice(run_id: int, developer_key: Optional[str]) -> Optional[catalog.ModelChoice]:
    """The model that screens this run, or None for a control-arm (or unscreenable) run."""
    if SCREEN_MODEL == "off" or not in_screen_arm(run_id):
        return None
    dev = catalog.resolve(developer_key)
    choice = catalog.get(_TIER_DOWN.get(dev.key) if SCREEN_MODEL == "auto" else SCREEN_MODEL)
    if choice is None or choice.key == dev.key:
        return None
    if choice.price_in + choice.price_out >= dev.price_in + dev.price_out:
        return None  # screening with a model that costs as much buys nothing
    return choice


@dataclass
class Screen:
    """One run's screening state. `model` is None on a control-arm run: every caller then uses the
    developer, exactly as before this existed."""
    run_id: int
    choice: Optional[catalog.ModelChoice] = None
    model: Optional[ModelFn] = None
    usage: Usage = field(default_factory=Usage)
    tally: Counter = field(default_factory=Counter)
    billed_in: int = 0
    billed_out: int = 0

    @property
    def on(self) -> bool:
        return self.model is not None

    def audit(self, title: str) -> bool:
        """Whether the developer re-judges this screen abandon (a stable sample of AUDIT_SHARE)."""
        return _bucket("audit", self.run_id, title) < AUDIT_SHARE

    def drain(self) -> Dict[str, int]:
        """The screen tokens spent since the last drain (then reset), for billing at its price."""
        spent = {"input_tokens": self.usage.input_tokens, "output_tokens": self.usage.output_tokens}
        self.billed_in += spent["input_tokens"]
        self.billed_out += spent["output_tokens"]
        self.usage.input_tokens = self.usage.output_tokens = 0
        return spent

    def summary(self) -> Dict:
        """The run's `screen` verdict payload (rsi.run_card prices the screen tokens from it)."""
        t = self.tally
        return {"phase": "screen", "arm": "screen" if self.on else "control",
                "screen_model": self.choice.key if self.choice else None,
                "screen_model_id": self.choice.model_id if self.choice else None,
                "screen_in": self.billed_in, "screen_out": self.billed_out,
                "screened_out": t["screened_out"], "handed_over": t["handed_over"],
                "audits": t["audits"], "rescued": t["rescued"]}

    def message(self) -> str:
        if not self.on:
            return "Model tiering: control arm, one model for every step."
        t = self.tally
        return ("Model tiering: %s proposed and screened. %d idea(s) dropped by the screen, %d handed to "
                "the developer; the developer re-judged %d screen drop(s) and rescued %d."
                % (self.choice.label, t["screened_out"], t["handed_over"], t["audits"], t["rescued"]))


def screen_cost_split(run_model_id: str, input_tokens: int, output_tokens: int,
                      summary: Optional[Dict]) -> list:
    """[(model_id, in, out), ...] for pricing a run whose totals include screen tokens."""
    if not summary or not summary.get("screen_model_id"):
        return [(run_model_id, input_tokens, output_tokens)]
    s_in = min(int(summary.get("screen_in") or 0), input_tokens)
    s_out = min(int(summary.get("screen_out") or 0), output_tokens)
    return [(run_model_id, input_tokens - s_in, output_tokens - s_out),
            (summary["screen_model_id"], s_in, s_out)]
