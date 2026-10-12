"""Download exploratory raw daily SIP bars using private local .env credentials."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import partial
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from dotenv import dotenv_values
from requests.exceptions import RequestException


ROOT = Path(__file__).resolve().parents[1]
DATA_ENDPOINT = "https://data.alpaca.markets"
NY = ZoneInfo("America/New_York")
CSV_FIELDS = ["symbol", "timestamp", "session", "open", "high", "low", "close", "volume"]


class SetupError(Exception):
    """An error message containing no configuration values or server response."""


@dataclass(repr=False)
class Config:
    endpoint: str
    key: str
    secret: str


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise SetupError("Private .env file is missing.")
    # Read this file directly: stale shell variables cannot override the user's edit.
    # Disable expansion so a dollar sign in a credential remains literal.
    values = dotenv_values(path, interpolate=False)
    endpoint = (values.get("ALPACA_DATA_ENDPOINT") or "").strip().rstrip("/")
    if endpoint != DATA_ENDPOINT:
        raise SetupError("ALPACA_DATA_ENDPOINT must be https://data.alpaca.markets (base URL only).")
    missing = [name for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
               if not (values.get(name) or "").strip()]
    if missing:
        raise SetupError("Fill the private .env values: " + ", ".join(missing) + ".")
    return Config(endpoint, values["APCA_API_KEY_ID"].strip(), values["APCA_API_SECRET_KEY"].strip())


def request_window(start: date, now: datetime) -> tuple[datetime, datetime]:
    if start < date(2016, 1, 1):
        raise SetupError("This Alpaca study starts in 2016 or later.")
    beginning = datetime.combine(start, time.min, tzinfo=NY)
    midnight = datetime.combine(now.astimezone(NY).date(), time.min, tzinfo=NY)
    # End is inclusive. Exclude today's midnight bar and the newest 20 minutes,
    # including calls made shortly after New York midnight.
    end = min(midnight - timedelta(microseconds=1), now - timedelta(minutes=20))
    if beginning > end:
        raise SetupError("The start date has no completed prior-day observations.")
    return beginning, end


def normalize(raw: dict, symbols: list[str], start: datetime, end: datetime) -> list[dict]:
    if not isinstance(raw, dict) or set(raw) - set(symbols):
        raise SetupError("Unexpected historical-bar response structure.")
    rows, seen = [], set()
    for symbol in symbols:
        bars = raw.get(symbol, [])
        if not isinstance(bars, list) or not bars:
            raise SetupError("No completed historical bars for " + symbol + ".")
        for bar in bars:
            try:
                timestamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                if timestamp.tzinfo is None or not start <= timestamp <= end:
                    raise ValueError("timing")
                prices = {name: float(bar[field]) for name, field in
                          (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))}
                volume = float(bar["v"])
                if not all(math.isfinite(value) and value > 0 for value in prices.values()):
                    raise ValueError("prices")
                if not math.isfinite(volume) or volume < 0 or not volume.is_integer():
                    raise ValueError("volume")
                if not (prices["low"] <= min(prices["open"], prices["close"])
                        <= max(prices["open"], prices["close"]) <= prices["high"]):
                    raise ValueError("OHLC")
                session = timestamp.astimezone(NY).date().isoformat()
                if (symbol, session) in seen:
                    raise ValueError("duplicate")
                seen.add((symbol, session))
                rows.append({"symbol": symbol, "timestamp": timestamp.isoformat(),
                             "session": session, **prices, "volume": int(volume)})
            except (KeyError, TypeError, ValueError, OverflowError):
                raise SetupError("Historical response failed timestamp/OHLCV/duplicate checks.") from None
    return sorted(rows, key=lambda row: (row["symbol"], row["session"]))


def download(config: Config, symbols: list[str], start: date, now: datetime,
             output: Path | None = None) -> dict:
    beginning, end = request_window(start, now)
    request = StockBarsRequest(
        symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
        start=beginning, end=end, feed=DataFeed.SIP, adjustment=Adjustment.RAW,
        asof=now.astimezone(NY).date().isoformat(),
    )
    client = StockHistoricalDataClient(config.key, config.secret, raw_data=True,
                                       url_override=config.endpoint)
    # alpaca-py 0.44.0 has no public HTTP timeout argument. Bound its session
    # requests without changing any global requests behavior.
    client._session.request = partial(client._session.request, timeout=30)
    try:
        # No total limit: the pinned official SDK follows every next_page_token.
        raw = client.get_stock_bars(request)
    finally:
        client._session.close()
    retrieved = datetime.now(timezone.utc)
    rows = normalize(raw, symbols, beginning, end)
    target = output or ROOT / "data" / "alpaca_snapshots" / retrieved.strftime("%Y%m%dT%H%M%S.%fZ")
    target.mkdir(parents=True, exist_ok=False)
    raw_path, csv_path = target / "provider_bars.json", target / "daily_raw.csv"
    # SDK-combined provider objects; these are not the original HTTP envelopes.
    raw_path.write_text(json.dumps(raw, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    coverage = {symbol: {"first_session": min(row["session"] for row in rows if row["symbol"] == symbol),
                         "last_session": max(row["session"] for row in rows if row["symbol"] == symbol),
                         "rows": sum(row["symbol"] == symbol for row in rows)} for symbol in symbols}
    manifest = {
        "status": "downloaded", "provider": "Alpaca", "quality": "proxy",
        "endpoint": config.endpoint + "/v2/stocks/bars", "feed": "sip", "adjustment": "raw",
        "timeframe": "1Day", "symbols": symbols, "start": beginning.isoformat(),
        "end": end.isoformat(), "symbol_mapping_asof": request.asof,
        "retrieved_at": retrieved.isoformat(), "availability_basis": "retrieval_time_only",
        "agent_import_ready": False, "commercial_rights_reviewed": False,
        "provider_payload": "SDK-combined bar objects; original HTTP envelopes not retained",
        "dependencies": {name: version(name) for name in ("alpaca-py", "python-dotenv")},
        "coverage": coverage, "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                         for path in (raw_path, csv_path)},
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"status": "downloaded", "snapshot": str(target), "coverage": coverage,
            "feed": "sip", "adjustment": "raw", "quality": "proxy"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--check-config", action="store_true", help="Validate local configuration without any API call")
    parser.add_argument("--start", default="2016-01-01", help="First requested New York session date")
    parser.add_argument("--symbols", nargs="+", default=["SPY", "QQQ", "IWM"])
    parser.add_argument("--output", type=Path, help="New snapshot directory; existing directories are refused")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.env_file)
        if args.check_config:
            print(json.dumps({"status": "ready", "endpoint": config.endpoint,
                              "credentials_present": True, "authenticated": False}))
            return 0
        symbols = list(dict.fromkeys(symbol.upper() for symbol in args.symbols))
        if any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) for symbol in symbols):
            raise SetupError("Use valid stock/ETF ticker symbols.")
        try:
            start = date.fromisoformat(args.start)
        except ValueError:
            raise SetupError("Start date must use YYYY-MM-DD.") from None
        if args.output is not None and args.output.exists():
            raise SetupError("Output directory already exists; choose a new snapshot directory.")
        receipt = download(config, symbols, start, datetime.now(timezone.utc), args.output)
        print(json.dumps(receipt, indent=2))
        return 0
    except SetupError as error:
        print(json.dumps({"status": "not_ready", "message": str(error)}))
        return 2
    except APIError as error:
        # Never print the response body, request object or credential-bearing config.
        status = error.status_code
        messages = {401: "Check the local API key/secret pair.",
                    403: "Check the local key pair and historical SIP entitlement.",
                    422: "Check historical SIP entitlement and the request cutoff.",
                    429: "Historical API rate limit reached; retry later."}
        print(json.dumps({"status": "api_error", "http_status": status,
                          "message": messages.get(status, "Historical API request failed; response body omitted.")}))
        return 1
    except (RequestException, OSError, ValueError, TypeError):
        print(json.dumps({"status": "failed", "message": "Network, file or response error; private details omitted."}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
