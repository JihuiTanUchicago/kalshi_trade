from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class TradeIntent:
    action: str
    side: str
    ticker: str
    qty_contracts: int
    limit_price_dollars: float
    model_name: str
    now_ts: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionReport:
    accepted: bool
    status: str
    # What Kalshi actually filled, never what we asked for. A fully unfilled
    # order reports fill_qty_contracts=0 and fill_price_dollars=0.0.
    fill_price_dollars: float
    fill_qty_contracts: int
    external_order_id: Optional[str]
    client_order_id: Optional[str]
    fee_dollars: float = 0.0
    raw_json: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskContext:
    cfg: Dict[str, Any]
    risk_state: str
    risk_meta: Dict[str, Any]
    ticker: str
    signal: bool
    prob: float
    edge: float
    near_expiry: bool


@dataclass
class RiskDecision:
    allowed: bool
    state: str
    reasons: List[str] = field(default_factory=list)
