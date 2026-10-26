"""Manual anonymous provider check; never loads DB/keys or persists raw prices.

From kalshi_trade_infra with the project on PYTHONPATH:
    python results/kalshi_bitcoin_perps_2026-10-23/public_feed_check.py --system-proxy

--system-proxy explicitly routes through a configured credential-free OS proxy.
Without it only TAU_KALSHI_PERPS_PROXY_URL is used; direct is the default.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import getproxies

import requests

from app.adapters.kalshi_perps.kalshi_perps_collector import collect, summary
from app.adapters.kalshi_perps.kalshi_perps_data import Config, KalshiPerpsDataClient
from app.adapters.data.market_data_common import MarketDataError


class CheckedSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.events = []

    def get(self, url, **kwargs):
        category = ("candles" if url.endswith("/candlesticks") else
                    "historical_funding" if url.endswith("/funding_rates/historical") else
                    "funding_estimate" if url.endswith("/funding_rates/estimate") else "public_metadata")
        event = {"endpoint": category}
        self.events.append(event)
        started = time.monotonic()
        try:
            response = super().get(url, **kwargs)
            event["http_status"] = response.status_code
            return response
        except requests.RequestException as exc:
            event["error_class"] = type(exc).__name__
            raise
        finally:
            event["header_elapsed_seconds"] = round(time.monotonic() - started, 3)


def check(environment, proxy_url, hours):
    session = CheckedSession()
    result = {"environment": environment, "actual_client_and_collector": True}
    try:
        end = int(time.time()) // 60 * 60 - 60
        with KalshiPerpsDataClient(Config(True, environment, proxy_url=proxy_url), session=session) as client:
            batch = collect(client, end - hours * 3600, end)
        result.update(summary(batch))
        result["candle_coverage_complete"] = batch["coverage"]["candles"]["complete"]
        result["funding_coverage_complete"] = batch["coverage"]["funding"]["complete"]
        result["continuous_replay_ready"] = bool(result["candle_coverage_complete"]
                                                 and result["funding_coverage_complete"])
        result["observation_kinds"] = sorted({row["kind"] for row in batch["observations"]})
        result["observations_status"] = batch["coverage"]["observations"]["status"]
        result["readable_history_and_funding"] = bool(batch["candles"] and batch["funding"]
                                                      and result["funding_retrieval_complete"])
        result["status"] = "checked"
    except MarketDataError as exc:
        result.update(status="unavailable", error_code=exc.code, message=str(exc))
    except Exception as exc:
        result.update(status="failed", error_class=type(exc).__name__)
    result["http_events"] = session.events
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-proxy", action="store_true")
    parser.add_argument("--environment", choices=("production", "demo", "both"), default="both")
    parser.add_argument("--hours", type=int, choices=range(8, 73), default=48)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    proxy = getproxies().get("https") if args.system_proxy else os.environ.get("TAU_KALSHI_PERPS_PROXY_URL") or None
    if args.system_proxy and not proxy:
        parser.error("No system HTTPS proxy is configured.")
    environments = ("production", "demo") if args.environment == "both" else (args.environment,)
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(lambda env: check(env, proxy, args.hours), environments))
    result = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "route": "explicit_system_proxy" if args.system_proxy else "explicit_proxy" if proxy else "direct",
              "checks": checks, "private_credentials_loaded": False, "raw_prices_or_account_bodies_saved": False,
              "database_or_service_or_order_changes": False, "actual_server_environment_checked": False}
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0 if all(row.get("readable_history_and_funding") for row in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
