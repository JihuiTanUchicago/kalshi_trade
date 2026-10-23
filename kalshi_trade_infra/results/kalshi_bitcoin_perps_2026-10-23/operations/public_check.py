"""One temporary, anonymous production collection; no DB or persistence imports."""
from __future__ import annotations

import json
import os
import time

import requests

from app.kalshi_perps_collector import collect, summary
from app.kalshi_perps_data import Config, KalshiPerpsDataClient
from app.market_data_common import MarketDataError


class CheckedSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.events = []

    def get(self, url, **kwargs):
        if len(self.events) >= 15:
            raise MarketDataError("request_limit", "Diagnostic request limit reached.")
        kind = ("candles" if url.endswith("/candlesticks") else
                "historical_funding" if url.endswith("/funding_rates/historical") else
                "funding_estimate" if url.endswith("/funding_rates/estimate") else "public_metadata")
        event = {"endpoint": kind}
        self.events.append(event)
        try:
            response = super().get(url, **kwargs)
            event["http_status"] = int(response.status_code)
            return response
        except requests.RequestException:
            event["error_code"] = "network_request_failed"
            raise


def run() -> dict:
    proxy = os.environ.get("TAU_KALSHI_PERPS_PROXY_URL") or None
    session = CheckedSession()
    result = {"environment": "production", "window_hours": 48,
              "actual_candidate_client_and_collector": True,
              "route": "worker_explicit_proxy" if proxy else "direct",
              "persisted": False, "replay_accepted": False,
              "private_provider_credentials_loaded": False}
    try:
        # Diagnostic-only Config object. Actual service env/flags are never changed.
        end = int(time.time()) // 60 * 60 - 60
        with KalshiPerpsDataClient(Config(True, "production", proxy_url=proxy), session=session) as client:
            batch = collect(client, end - 48 * 3600, end)
        result.update(summary(batch))
        candles = batch["coverage"]["candles"]
        result.update(status="checked", candle_coverage_complete=candles["complete"],
                      missing_candle_count=candles["missing_count"],
                      partial_candle_warning=not candles["complete"],
                      funding_coverage_complete=batch["coverage"]["funding"]["complete"],
                      observations_status=batch["coverage"]["observations"]["status"],
                      readable_history_and_funding=bool(batch["candles"] and batch["funding"]
                                                       and batch["coverage"]["funding"]["retrieval_complete"]))
    except MarketDataError as exc:
        result.update(status="unavailable", error_code=exc.code)
    except Exception:
        result.update(status="unavailable", error_code="public_check_failed")
    finally:
        session.close()
    result["http_events"] = session.events
    return result


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
