"""Translate between Kalshi's order types (data_pipeline.architecture.contracts) and the domain's.

Kalshi speaks (action buy/sell, side yes/no, ticker); the domain speaks (Side, InstrumentId with
outcome). A Kalshi binary is long-only per outcome (position_guard forbids a sell past flat), so a
SELL is always an exit and maps to ``reduce_only=True``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from data_pipeline.architecture.contracts import ExecutionReport as KalshiReport
from data_pipeline.architecture.contracts import TradeIntent
from trading_core.domain import ExecutionReport, Fill, InstrumentId, OrderIntent, Side

VENUE = "kalshi"

# Kernel statuses that mean "nothing was sent or nothing could fill" map to rejected; the rest 1:1.
_STATUS = {"filled": "filled", "partially_filled": "partial", "unfilled": "unfilled"}


def instrument_id(ticker: str, side: str) -> InstrumentId:
    side = str(side).lower()
    if side not in ("yes", "no"):
        raise ValueError("Kalshi side must be yes or no, got %r" % side)
    return InstrumentId(VENUE, ticker, side)


def kalshi_order(instrument: InstrumentId) -> tuple:
    """(ticker, side) for a Kalshi binary instrument; refuses anything else."""
    if instrument.venue != VENUE or instrument.outcome not in ("yes", "no"):
        raise ValueError("not a Kalshi binary instrument: %s" % instrument)
    return instrument.symbol, instrument.outcome


def from_trade_intent(ti: TradeIntent) -> OrderIntent:
    meta = dict(ti.metadata or {})
    fair = meta.get("fair")
    return OrderIntent(
        instrument=instrument_id(ti.ticker, ti.side),
        side=Side(str(ti.action).lower()),
        qty=int(ti.qty_contracts),
        limit_price=float(ti.limit_price_dollars),
        reduce_only=str(ti.action).lower() == "sell",
        strategy_id=str(ti.model_name or ""),
        fair_value=float(fair) if fair is not None else None,
        meta=meta,
    )


def to_trade_intent(intent: OrderIntent, limit_price: float, now_ts: Optional[datetime] = None) -> TradeIntent:
    ticker, side = kalshi_order(intent.instrument)
    meta = dict(intent.meta)
    if intent.fair_value is not None:
        meta.setdefault("fair", intent.fair_value)
    return TradeIntent(action=intent.side.value, side=side, ticker=ticker, qty_contracts=int(intent.qty),
                       limit_price_dollars=float(limit_price), model_name=intent.strategy_id, now_ts=now_ts,
                       metadata=meta)


def to_domain_report(report: KalshiReport, intent: OrderIntent, ts: float = 0.0) -> ExecutionReport:
    """A kernel report (own-side price, as MarketableLimitKernel returns it) as a domain report."""
    status = _STATUS.get(report.status, "rejected")
    fills = []
    if report.fill_qty_contracts > 0:
        fills.append(Fill(intent.instrument, intent.side, float(report.fill_qty_contracts),
                          float(report.fill_price_dollars), fee=float(report.fee_dollars), ts=ts,
                          order_id=report.external_order_id))
    order_ids = [report.external_order_id] if report.external_order_id else []
    return ExecutionReport(intent, status, fills, order_ids, message=report.status)
