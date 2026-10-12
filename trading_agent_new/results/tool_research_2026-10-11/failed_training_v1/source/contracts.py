"""Provider-independent contracts and preregistration validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .common import GateError, finite, integer


STATES = ("requested", "specified", "implemented", "evaluated", "challenged", "decided", "learned", "finished")


@dataclass(frozen=True)
class Limits:
    capital: float = 100_000.0
    gross: float = 1.0
    position: float = 0.25
    cash_buffer: float = 0.05
    short_collateral: float = 1.5
    participation: float = 0.001
    daily_loss: float = 0.02
    drawdown: float = 0.10

    def __post_init__(self):
        for key, value in asdict(self).items():
            finite(value, key)
        if self.capital <= 0 or not 0 < self.gross <= 1 or not 0 < self.position <= self.gross:
            raise GateError("Capital/position/gross limits are invalid")
        if not 0 <= self.cash_buffer < 1 or self.short_collateral < 1.5:
            raise GateError("Invalid cash buffer or conservative short collateral")
        if not 0 < self.participation <= 0.01 or not 0 < self.daily_loss < 1 or not 0 < self.drawdown < 1:
            raise GateError("Invalid participation or protective pause limits")


@dataclass(frozen=True)
class ResearchSpec:
    hypothesis: str
    dataset_id: str
    baseline: str
    start: str
    end: str
    lookback: int = 20
    decision_delay_minutes: int = 30
    allow_short: bool = True
    transaction_bps: float = 5.0
    commission_per_share: float = 0.005
    minimum_commission: float = 1.0
    buffer: float = 0.02
    minimum_sharpe_gain: float = 0.10
    maximum_drawdown_deterioration: float = 0.02
    bootstrap_samples: int = 2000
    block_length: int = 21
    seed: int = 20261009
    sources: list[str] = field(default_factory=list)
    prospective: bool = False
    limits: dict[str, Any] = field(default_factory=lambda: asdict(Limits()))

    def __post_init__(self):
        from datetime import date
        if not self.hypothesis.strip() or len(self.hypothesis) > 4000:
            raise GateError("A concise, falsifiable hypothesis is required")
        if self.baseline not in {"equal_weight", "trend", "long_short_trend"}:
            raise GateError("Choose a fixed baseline before running experiments")
        if not isinstance(self.allow_short, bool) or not isinstance(self.prospective, bool):
            raise GateError("Shorting/prospective flags must be booleans")
        try:
            first, last = date.fromisoformat(self.start), date.fromisoformat(self.end)
        except ValueError as exc:
            raise GateError("Scoring dates must be YYYY-MM-DD") from exc
        if first < date(2016, 1, 1) or first > last:
            raise GateError("Score from 2016 onward; earlier observations are warmup only")
        integer(self.lookback, "lookback", 2)
        if integer(self.decision_delay_minutes,"decision delay") > 120:
            raise GateError("Decision delay must be within two hours of the preceding close")
        integer(self.bootstrap_samples, "bootstrap_samples", 100)
        integer(self.block_length, "block_length", 1)
        integer(self.seed, "seed")
        for key in ("transaction_bps", "commission_per_share", "minimum_commission", "buffer",
                    "minimum_sharpe_gain", "maximum_drawdown_deterioration"):
            if finite(getattr(self, key), key) < 0:
                raise GateError(f"{key} cannot be negative")
        if self.buffer > 0.25 or self.transaction_bps > 1000:
            raise GateError("Invalid buffer/cost assumption")
        Limits(**self.limits)


@dataclass(frozen=True)
class ModelRequest:
    messages: list[dict[str, str]]
    max_output_tokens: int = 1500
    temperature: float = 0.0


@dataclass(frozen=True)
class ModelResponse:
    content: str
    input_tokens: int
    output_tokens: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Action:
    tool: str
    arguments: dict[str, Any]

    @classmethod
    def parse(cls, value: Any) -> "Action":
        if not isinstance(value, dict) or set(value) != {"tool", "arguments"}:
            raise GateError("Return exactly {tool: string, arguments: object}")
        if not isinstance(value["tool"], str) or not isinstance(value["arguments"], dict):
            raise GateError("Invalid action types")
        return cls(**value)


@dataclass(frozen=True)
class StrategyArtifact:
    kind: str
    name: str
    lookback: int
    buffer: float = 0.0
    code: str = ""
    api_version: str = "1"
    target_shares: int = 0

    def __post_init__(self):
        if self.kind not in {"builtin", "python", "control"} or self.api_version != "1":
            raise GateError("Unsupported strategy kind/API version")
        if self.kind=="control":
            if isinstance(self.target_shares,bool) or self.target_shares not in {-1,0,1} or not self.name:
                raise GateError("Engineering control permits exactly -1, 0 or 1 shares of a named security")
        elif self.target_shares!=0:
            raise GateError("Share-count control is reserved for operator engineering tests")
        integer(self.lookback, "strategy lookback", 2)
        if not 0 <= finite(self.buffer, "buffer") <= 0.25:
            raise GateError("Invalid strategy buffer")
        if self.kind == "builtin" and self.name not in {"equal_weight", "trend", "long_short_trend"}:
            raise GateError("Unknown reference strategy")
        if self.kind == "python" and (not self.code.strip() or len(self.code.encode()) > 100_000):
            raise GateError("Generated strategies require Python source <=100 KB")
