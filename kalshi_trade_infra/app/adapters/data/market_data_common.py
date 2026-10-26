"""Small shared primitives for read-only, credential-safe market-data clients."""
from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Sequence

import requests

TIMEFRAMES = {"1Min": 60, "5Min": 300, "15Min": 900, "1Hour": 3600, "1Day": 86400}


class MarketDataError(RuntimeError):
    """Safe for agent prompts/logs: no response bodies, request URLs or secrets."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError()
        return dt.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise MarketDataError("invalid_data", "Market-data timestamps must be timezone-aware ISO dates.") from None


def iso(dt: datetime) -> str:
    return timestamp(dt).isoformat().replace("+00:00", "Z")


def number(value, *, positive: bool = False, signed: bool = False) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError()
        n = float(value)
        if not math.isfinite(n) or (positive and n <= 0) or (not signed and n < 0):
            raise ValueError()
        return n
    except (TypeError, ValueError, OverflowError):
        raise MarketDataError("invalid_data", "The provider returned invalid numeric market data.") from None


def equity_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(symbols, (list, tuple)) or not 1 <= len(symbols) <= 8:
        raise MarketDataError("invalid_request", "Request between 1 and 8 stock symbols.")
    out = []
    for symbol in symbols:
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,14}", symbol):
            raise MarketDataError("invalid_request", "Invalid stock symbol.")
        symbol = symbol.upper()
        if symbol not in out:
            out.append(symbol)
    return tuple(out)


def get_json(session, url: str, *, headers: Dict, params: Dict, provider: str,
             sleep: Callable = time.sleep, checkpoint: Callable = lambda: None) -> Dict:
    """Three bounded attempts. Callers validate the fixed host/path before calling."""
    for attempt in range(3):
        checkpoint()
        response = None
        delay = min(2 ** attempt, 2)
        try:
            response = session.get(url, headers=headers, params=params,
                                   timeout=(3.05, 8), allow_redirects=False)
            status = response.status_code
            if status == 200:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError()
                return payload
            if status == 401:
                raise MarketDataError("authentication", "%s rejected the market-data credentials." % provider)
            if status == 403:
                raise MarketDataError("entitlement", "%s denied this dataset/feed. Check the subscription; no fallback was used." % provider)
            if status != 429 and not 500 <= status <= 599:
                raise MarketDataError("provider_request", "%s rejected the market-data request (HTTP %d)." % (provider, status))
            if attempt == 2:
                code = "rate_limit" if status == 429 else "provider_unavailable"
                raise MarketDataError(code, "%s market data is temporarily unavailable (HTTP %d)." % (provider, status))
            try:
                delay = max(0, min(float(response.headers.get("Retry-After", delay)), 3))
            except (TypeError, ValueError):
                pass
        except (ValueError, TypeError):
            raise MarketDataError("invalid_data", "%s returned an invalid JSON market-data response." % provider) from None
        except requests.RequestException:
            if attempt == 2:
                raise MarketDataError("provider_unavailable", "Could not reach %s market data after three attempts." % provider) from None
        finally:
            if response is not None:
                response.close()
        sleep(delay)
    raise AssertionError("unreachable")
