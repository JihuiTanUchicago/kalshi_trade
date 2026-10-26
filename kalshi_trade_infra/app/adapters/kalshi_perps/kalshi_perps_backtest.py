"""Causal, research-only Bitcoin perpetual replay, with explicit scenario costs.

This is a linear USD PnL model with one position and at most 1x gross notional
of available research capital. It is not a margin, liquidation, broker, or
execution simulator. Costs are uncalibrated assumptions, not observed fills.
Bars are end-labelled. A decision consumes a completed bar before filling at
the following bar's open; publication-before-open is an explicit bar assumption.
Funding is paid before fills at a shared timestamp: entry < payment <= exit.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BAR_SECONDS = 60
MAX_HOLDING_SECONDS = 24 * 60 * 60
MAX_LOOKBACK_MINUTES = 1440
DEFAULT_ASSUMPTIONS = {
    "signal": "momentum", "lookback_minutes": 60, "threshold": 0.001,
    "side": "both", "max_holding_minutes": 1440, "leverage": 1,
    "taker_fee_bps": 12, "slippage_bps": 5,
}
LIMITATIONS = [
    "Research only; no live or paper broker and no margin/liquidation model.",
    "One position, at most 1x available capital; short losses may exceed capital.",
    "Uncalibrated scenario: taker fees 12bps/fill and adverse slippage 5bps/fill.",
    "Next-open fills assume prior completed-bar publication before the open.",
    "Funding precedes fills at equal timestamps; entry < payment <= exit.",
]


class PerpetualDataError(ValueError):
    """The source cannot support the requested financial calculation."""


def _decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise PerpetualDataError("%s must be a finite decimal" % name)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise PerpetualDataError("%s must be a finite decimal" % name) from None
    if not number.is_finite() or (positive and number <= 0):
        raise PerpetualDataError("%s must be %s" % (name, "positive" if positive else "finite"))
    return number


def _timestamp(value: Any, name: str) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise PerpetualDataError("%s needs a timezone" % name)
        return int(value.timestamp())
    number = _decimal(value, name)
    if number != number.to_integral_value():
        raise PerpetualDataError("%s must be an integer timestamp" % name)
    return int(number)


def normalize_assumptions(raw: Optional[Dict] = None) -> Dict:
    """Freeze the supported rule and costs; costs cannot be optimized away."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("perpetual must be an object")
    extra = set(raw) - set(DEFAULT_ASSUMPTIONS)
    if extra:
        raise ValueError("unknown perpetual field(s): %s" % ", ".join(sorted(extra)))
    out = dict(DEFAULT_ASSUMPTIONS, **raw)
    if out["signal"] not in ("momentum", "mean_reversion", "funding"):
        raise ValueError("perpetual.signal must be momentum, mean_reversion or funding")
    if out["side"] not in ("both", "long", "short"):
        raise ValueError("perpetual.side must be both, long or short")
    lookback = out["lookback_minutes"]
    if isinstance(lookback, bool) or not isinstance(lookback, int) or not 1 <= lookback <= MAX_LOOKBACK_MINUTES:
        raise ValueError("perpetual.lookback_minutes must be an integer in 1..1440")
    threshold = _decimal(out["threshold"], "perpetual.threshold")
    if not 0 <= threshold <= 1:
        raise ValueError("perpetual.threshold must be in 0..1")
    out["threshold"] = float(threshold)
    for key in ("max_holding_minutes", "leverage", "taker_fee_bps", "slippage_bps"):
        if _decimal(out[key], "perpetual.%s" % key) != Decimal(str(DEFAULT_ASSUMPTIONS[key])):
            raise ValueError("perpetual.%s is fixed at %s for this research phase" %
                             (key, DEFAULT_ASSUMPTIONS[key]))
        out[key] = DEFAULT_ASSUMPTIONS[key]
    return out


@dataclass(frozen=True)
class _Bar:
    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    available_at: int

    @property
    def open_ts(self) -> int:
        return self.ts - BAR_SECONDS


@dataclass(frozen=True)
class _Funding:
    ts: int
    rate: Decimal
    mark_price: Decimal


@dataclass
class PerpetualDataset:
    market: Any
    frames: List[Tuple[int, Dict]]
    results: Dict[str, str]
    start_ts: int
    end_ts: int
    contracts: int
    ticker: str
    environment: str
    instrument: Dict
    coverage: Dict
    data_fingerprint: str
    bars: Tuple[_Bar, ...] = field(repr=False)
    funding: Tuple[_Funding, ...] = field(repr=False)
    funding_schedule: Dict = field(repr=False)
    quantity_step: Decimal = field(repr=False)
    contract_multiplier: Decimal = field(repr=False)
    source_version: str = ""
    last_rejection: str = ""

    @property
    def cutoff_ts(self) -> int:
        return int(self.start_ts + (self.end_ts - self.start_ts) * 0.7)

    def summary(self) -> Dict:
        return {
            "market": self.market.key, "label": self.market.label, "kind": "perpetual",
            "start": _iso(self.start_ts), "end": _iso(self.end_ts),
            "out_of_sample_from": _iso(self.cutoff_ts), "decision_points": len(self.frames),
            "contracts": self.contracts, "ticker": self.ticker, "environment": self.environment,
            "data_fingerprint": self.data_fingerprint, "coverage": copy.deepcopy(self.coverage),
            "source_version": self.source_version,
            "assumptions": dict(DEFAULT_ASSUMPTIONS), "limitations": list(LIMITATIONS),
            "rejection_reason": self.last_rejection,
        }


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _observation_features(observations: List[Dict], timestamps: List[int]) -> Dict[int, Dict]:
    """As-of features only; the payment ledger never enters this function."""
    rows = []
    for row in observations:
        if not isinstance(row, dict) or row.get("kind") != "funding_estimate":
            continue
        ts = _timestamp(row.get("ts"), "observation.ts")
        available = _timestamp(row.get("available_at"), "observation.available_at")
        rate = _decimal(row.get("funding_rate"), "observation.funding_rate")
        rows.append((max(ts, available), ts, rate))
    rows.sort(key=lambda item: (item[0], item[1]))
    result, cursor, latest = {}, 0, None
    for ts in timestamps:
        while cursor < len(rows) and rows[cursor][0] <= ts:
            row = rows[cursor]
            if latest is None or (row[1], row[0]) >= (latest[1], latest[0]):
                latest = row
            cursor += 1
        result[ts] = ({"funding_rate_estimate": float(latest[2]),
                       "funding_estimate_ts": latest[1], "funding_estimate_available_at": latest[0]}
                      if latest is not None else {})
    return result


def build_dataset(market: Any, history: Dict) -> PerpetualDataset:
    """Build a normalized USD-per-contract dataset, refusing unknown unit semantics.

    ``price_basis=per_underlying`` is converted once with contract_multiplier;
    native ``per_contract`` prices must not be multiplied a second time.
    Historical OHLC availability defaults to the completed bar's end, distinct
    from archive retrieval time. Explicit delayed available_at is respected.
    """
    if getattr(market, "kind", None) != "perpetual" or getattr(market, "deployable", True):
        raise PerpetualDataError("perpetual datasets require a research-only perpetual market")
    instrument = copy.deepcopy(history.get("instrument") or {})
    if instrument.get("verified_bitcoin") is not True:
        raise PerpetualDataError("verified Bitcoin instrument metadata is required")
    if instrument.get("price_unit") != "USD" or instrument.get("funding_rate_unit") != "decimal":
        raise PerpetualDataError("known USD price and decimal funding-rate units are required")
    multiplier = _decimal(instrument.get("contract_multiplier"), "contract_multiplier", positive=True)
    quantity_step = _decimal(instrument.get("quantity_step"), "quantity_step", positive=True)
    basis = instrument.get("price_basis")
    if basis not in ("per_contract", "per_underlying"):
        raise PerpetualDataError("known per_contract or per_underlying price_basis is required")
    scale = multiplier if basis == "per_underlying" else Decimal(1)
    ticker = history.get("ticker") or instrument.get("ticker")
    environment = history.get("environment") or instrument.get("environment")
    if not isinstance(ticker, str) or not ticker or environment not in ("production", "demo"):
        raise PerpetualDataError("ticker and production/demo environment are required")
    if instrument.get("ticker", ticker) != ticker or instrument.get("environment", environment) != environment:
        raise PerpetualDataError("instrument/history identity mismatch")
    bars_by_ts = {}
    for row in history.get("candles") or []:
        ts = _timestamp(row.get("ts"), "candle.ts")
        if ts % BAR_SECONDS:
            raise PerpetualDataError("candles must be aligned completed one-minute bars")
        prices = [_decimal(row.get(key), "candle.%s" % key, positive=True) * scale
                  for key in ("open", "high", "low", "close")]
        op, high, low, close = prices
        if not low <= min(op, close) <= max(op, close) <= high:
            raise PerpetualDataError("candle OHLC range is inconsistent")
        bid, ask = [None if row.get(key) is None else _decimal(row[key], "candle.%s" % key, positive=True) * scale
                    for key in ("bid", "ask")]
        if bid is not None and ask is not None and bid > ask:
            raise PerpetualDataError("candle quotes are crossed")
        bar = _Bar(ts, op, high, low, close, bid, ask,
                   max(ts, _timestamp(row.get("available_at", ts), "candle.available_at")))
        if ts in bars_by_ts and bars_by_ts[ts] != bar:
            raise PerpetualDataError("conflicting duplicate candle")
        bars_by_ts[ts] = bar
    bars = tuple(bars_by_ts[ts] for ts in sorted(bars_by_ts))
    features = _observation_features(history.get("observations") or [], [bar.ts for bar in bars])
    frames = [(bar.ts, {
        "open": float(bar.open), "high": float(bar.high), "low": float(bar.low),
        "close": float(bar.close), "bid": float(bar.bid) if bar.bid is not None else None,
        "ask": float(bar.ask) if bar.ask is not None else None, "available_at": bar.available_at,
        "features": features[bar.ts],
    }) for bar in bars]
    funding_by_ts = {}
    for row in history.get("funding") or []:
        event = _Funding(_timestamp(row.get("ts"), "funding.ts"),
                         _decimal(row.get("rate"), "funding.rate"),
                         _decimal(row.get("mark_price"), "funding.mark_price", positive=True) * scale)
        if event.ts in funding_by_ts and funding_by_ts[event.ts] != event:
            raise PerpetualDataError("conflicting duplicate funding payment")
        funding_by_ts[event.ts] = event
    return PerpetualDataset(
        market, frames, {}, bars[0].ts if bars else 0, bars[-1].ts if bars else 0,
        1 if bars else 0, ticker, environment, instrument, copy.deepcopy(history.get("coverage") or {}),
        str(history.get("data_fingerprint") or ""), bars,
        tuple(funding_by_ts[ts] for ts in sorted(funding_by_ts)),
        copy.deepcopy(instrument.get("funding_schedule") or history.get("funding_schedule") or {}),
        quantity_step, multiplier,
        str(history.get("source_version") or history.get("data_fingerprint") or ""),
    )


def strategy_window(ds: PerpetualDataset, start_ts: int, end_ts: int) -> Dict:
    """Research-clipped public rule/fit data, with no realized funding ledger."""
    return {
        "market": ds.market.key, "kind": "perpetual", "ticker": ds.ticker,
        "price_unit": "USD", "price_basis": "per_contract",
        "contract_multiplier": str(ds.contract_multiplier),
        "frames": [{"ts": ts, **copy.deepcopy(frame)} for ts, frame in ds.frames
                   if start_ts <= ts < end_ts and frame["available_at"] <= ts],
        "limitations": list(LIMITATIONS),
    }


def _expected_funding(schedule: Dict, start_ts: int, end_ts: int) -> List[int]:
    if schedule.get("timezone") != "America/New_York" or schedule.get("hours") != [0, 8, 16]:
        raise PerpetualDataError("verified Bitcoin funding settlement schedule is required")
    try:
        zone = ZoneInfo(schedule["timezone"])
    except ZoneInfoNotFoundError:
        raise PerpetualDataError("funding timezone data unavailable") from None
    day = datetime.fromtimestamp(start_ts, zone).date()
    last = datetime.fromtimestamp(end_ts, zone).date()
    expected = []
    while day <= last:
        for hour in schedule["hours"]:
            ts = int(datetime(day.year, day.month, day.day, hour, tzinfo=zone).timestamp())
            if start_ts < ts <= end_ts:
                expected.append(ts)
        day += timedelta(days=1)
    return expected


def _coverage_reason(ds: PerpetualDataset, start_ts: int, end_ts: int, bars: List[_Bar]) -> str:
    if len(bars) < 3:
        return "not enough contiguous bars for next-open entry and exit"
    first_boundary = ((start_ts + BAR_SECONDS - 1) // BAR_SECONDS) * BAR_SECONDS
    last_boundary = (end_ts // BAR_SECONDS) * BAR_SECONDS
    if bars[0].ts > first_boundary or bars[-1].ts < last_boundary:
        return "candle coverage is missing a replay boundary"
    if any(right.ts - left.ts != BAR_SECONDS for left, right in zip(bars, bars[1:])):
        return "candle gap within replay window"
    # Common callers use last_bar_end+1 as an exclusive bound. Funding must
    # cover all possible open positions, through the predetermined final open;
    # the extra second after the final completed bar has no execution in it.
    executions = [bar for bar in bars if start_ts <= bar.open_ts < end_ts]
    if len(executions) < 2:
        return "not enough in-window next opens"
    funding_start, funding_end = executions[0].open_ts, executions[-1].open_ts
    coverage = ds.coverage.get("funding") or {}
    if coverage.get("complete") is not True or coverage.get("missing_timestamps"):
        return "funding coverage is incomplete or unknown"
    try:
        lo = _timestamp(coverage.get("start_ts"), "funding coverage.start_ts")
        hi = _timestamp(coverage.get("end_ts"), "funding coverage.end_ts")
        if lo > funding_start or hi < funding_end:
            return "funding coverage does not cover the complete replay window"
        expected = _expected_funding(ds.funding_schedule, funding_start, funding_end)
    except PerpetualDataError as exc:
        return str(exc)
    present = {event.ts for event in ds.funding}
    if any(ts not in present for ts in expected):
        return "scheduled funding payment is missing"
    return ""


def target_at(ds: PerpetualDataset, assumptions: Dict, decision_ts: int,
              start_ts: Optional[int] = None) -> Optional[str]:
    """Evaluate only point-in-time known features; no future bar/funding reads."""
    rules = normalize_assumptions(assumptions)
    start = ds.start_ts if start_ts is None else max(start_ts, ds.start_ts)
    if decision_ts < start:
        return None
    with localcontext() as context:
        context.prec = 50
        return _target_from_maps(rules, decision_ts, start, dict(ds.frames),
                                 {bar.ts: bar for bar in ds.bars})


@dataclass(frozen=True)
class PerpetualTrade:
    ticker: str
    side: str
    exact_quantity: Decimal
    entry_ts: int
    entry_price_decimal: Decimal
    exit_ts: int
    exit_price_decimal: Decimal
    fees_decimal: Decimal
    funding_pnl_decimal: Decimal
    capital_decimal: Decimal
    contract_multiplier: Decimal
    reason: str
    signal_ts: int
    edge: float = 0.0

    @property
    def qty(self) -> float:
        return float(self.exact_quantity)

    @property
    def entry_price(self) -> float:
        return float(self.entry_price_decimal)

    @property
    def exit_price(self) -> float:
        return float(self.exit_price_decimal)

    @property
    def fees(self) -> float:
        return float(self.fees_decimal)

    @property
    def gross_pnl_decimal(self) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            sign = 1 if self.side == "long" else -1
            return sign * self.exact_quantity * (self.exit_price_decimal - self.entry_price_decimal)

    @property
    def pnl_decimal(self) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            return self.gross_pnl_decimal + self.funding_pnl_decimal - self.fees_decimal

    @property
    def pnl(self) -> float:
        return float(self.pnl_decimal)

    @property
    def funding_pnl(self) -> float:
        return float(self.funding_pnl_decimal)

    @property
    def capital_at_risk(self) -> float:
        return float(self.capital_decimal)

    @property
    def net_return(self) -> float:
        with localcontext() as context:
            context.prec = 50
            return float(self.pnl_decimal / self.capital_decimal)

    @property
    def underlying_quantity(self) -> Decimal:
        return self.exact_quantity * self.contract_multiplier


def simulate(spec: Dict, ds: PerpetualDataset, start_ts: int, end_ts: int,
             what_if: Optional[Any] = None) -> List[PerpetualTrade]:
    """Replay entries and next-open exits entirely inside the supplied time cut.

    The last eligible open is reserved for a predetermined window-end exit;
    later prices cannot alter this close. Realized PnL changes available capital
    before any subsequent allocation. No loss is clipped, including short loss
    greater than initial capital. Missing coverage yields no trades and a reason.
    """
    if spec.get("code") or spec.get("cross"):
        raise ValueError("perpetual research currently supports causal declarative rules only")
    if spec.get("market") != ds.market.key:
        raise ValueError("spec and perpetual dataset market differ")
    rules = normalize_assumptions(spec.get("perpetual"))
    sizing = spec.get("sizing") or {}
    if _decimal(sizing.get("max_positions", 1), "max_positions") != 1:
        raise ValueError("perpetual research supports exactly one position")
    capital = _decimal(sizing.get("stake"), "stake", positive=True)
    fee_multiplier = _decimal(getattr(what_if, "fee_multiplier", 1), "fee_multiplier")
    extra_slippage = _decimal(getattr(what_if, "slippage_cents", 0), "slippage_cents") / 100
    if fee_multiplier < 1 or extra_slippage < 0:
        raise ValueError("perpetual cost scenarios may only worsen frozen costs")
    if what_if is not None and getattr(what_if, "stake", None) is not None:
        capital = _decimal(what_if.stake, "scenario stake", positive=True)
    rate = _decimal(rules["taker_fee_bps"], "taker fee") * fee_multiplier / 10000
    slip = _decimal(rules["slippage_bps"], "slippage") / 10000
    bars = [bar for bar in ds.bars if start_ts <= bar.ts <= end_ts]
    ds.last_rejection = _coverage_reason(ds, start_ts, end_ts, bars)
    if ds.last_rejection:
        logging.getLogger(__name__).warning("perpetual replay rejected: %s", ds.last_rejection)
        return []
    execution_bars = [bar for bar in bars if start_ts <= bar.open_ts < end_ts]
    if len(execution_bars) < 2:
        ds.last_rejection = "not enough in-window next opens"
        return []
    final_open = execution_bars[-1].open_ts
    trades: List[PerpetualTrade] = []
    position = None

    def fill(bar: _Bar, side: str, entering: bool) -> Decimal:
        buying = (side == "long") == entering
        return bar.open * (1 + slip if buying else 1 - slip) + (extra_slippage if buying else -extra_slippage)

    with localcontext() as context:
        context.prec = 50
        # Precompute lookup maps once; target_at exposes an equivalent public
        # single-decision contract without giving untrusted code a future window.
        frame_by_ts = dict(ds.frames)
        bar_by_ts = {bar.ts: bar for bar in ds.bars}
        for bar in execution_bars:
            ts = bar.open_ts
            target = _target_from_maps(rules, ts, max(start_ts, ds.start_ts), frame_by_ts, bar_by_ts)
            timed_out = position is not None and ts - position["entry_ts"] >= MAX_HOLDING_SECONDS
            reason = "window_end" if ts == final_open else "max_holding" if timed_out else "exit"
            if position is not None and (ts == final_open or timed_out or target != position["side"]):
                price = fill(bar, position["side"], False)
                if price <= 0:
                    ds.last_rejection = "scenario slippage produces a non-positive exit price"
                    return []
                direction = Decimal(1 if position["side"] == "long" else -1)
                funding = sum((-direction * position["qty"] * event.mark_price * event.rate
                               for event in ds.funding if position["entry_ts"] < event.ts <= ts), Decimal(0))
                trade = PerpetualTrade(ds.ticker, position["side"], position["qty"],
                                       position["entry_ts"], position["price"], ts, price,
                                       position["fee"] + position["qty"] * price * rate,
                                       funding, position["capital"], ds.contract_multiplier,
                                       reason, position["signal_ts"])
                trades.append(trade)
                capital += trade.pnl_decimal
                position = None
            if position is not None or target is None or ts == final_open or capital <= 0 or timed_out:
                continue
            price = fill(bar, target, True)
            if price <= 0:
                ds.last_rejection = "scenario slippage produces a non-positive entry price"
                return []
            qty = (capital / (price * (1 + rate)) / ds.quantity_step).to_integral_value(rounding=ROUND_FLOOR) * ds.quantity_step
            if qty <= 0:
                continue
            position = {"side": target, "qty": qty, "entry_ts": ts, "price": price,
                        "fee": qty * price * rate, "capital": capital, "signal_ts": ts}
    return trades


def _target_from_maps(rules: Dict, decision_ts: int, start_ts: int,
                      frames: Dict[int, Dict], bars: Dict[int, _Bar]) -> Optional[str]:
    """Trusted constant-time causal rule evaluator shared by the replay."""
    current = frames.get(decision_ts)
    if current is None or current["available_at"] > decision_ts:
        return None
    lookback = rules["lookback_minutes"] * BAR_SECONDS
    if rules["signal"] == "funding":
        features = current.get("features") or {}
        observed = features.get("funding_estimate_ts")
        if (observed is None or observed < start_ts or decision_ts - observed > lookback
                or features.get("funding_estimate_available_at", decision_ts + 1) > decision_ts):
            return None
        value = _decimal(features.get("funding_rate_estimate"), "funding estimate")
        invert = True
    else:
        previous_ts = decision_ts - lookback
        previous = frames.get(previous_ts)
        if previous_ts < start_ts or previous is None or previous["available_at"] > decision_ts:
            return None
        value = bars[decision_ts].close / bars[previous_ts].close - 1
        invert = rules["signal"] == "mean_reversion"
    if value == 0 or abs(value) < _decimal(rules["threshold"], "threshold"):
        return None
    side = "long" if value > 0 else "short"
    if invert:
        side = "short" if side == "long" else "long"
    return side if rules["side"] in ("both", side) else None
