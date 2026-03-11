from dataclasses import dataclass, field
from typing import Any, Dict, Protocol


@dataclass
class StrategySignal:
    model_name: str
    prob_yes: float
    signal_yes: bool
    edge_est: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class StrategyModel(Protocol):
    def fit(self, rows) -> None:
        ...

    def predict(self, row) -> StrategySignal:
        ...
