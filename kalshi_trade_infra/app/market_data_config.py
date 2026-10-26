"""Market-data routing and secret-free, network-free production preflight.

Run ``python -m app.market_data_config check`` in the worker environment.
This validates local settings, not provider subscriptions or live service health.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from app.adapters.data.alpaca_data import Config as AlpacaConfig, symbols_checked
from app.adapters.data.databento_data import Config as DatabentoConfig, dataset_checked
from app.adapters.data.market_data_common import MarketDataError
from app.adapters.data.massive_data import Config as MassiveConfig, pairs_checked

DEFAULT_EQUITIES = "SPY,QQQ,IWM,TLT,GLD,USO"
DEFAULT_FX = "EURUSD,USDJPY,GBPUSD"
# Materialize these for a standalone overlay: absent fields must not inherit a
# different enabled provider/feed from the service's older base environment.
ENV_DEFAULTS = {
    "TAU_MARKET_DATA_PRIMARY": "alpaca", "TAU_DATABENTO_DEFAULT_DATASET": "",
    "TAU_DATABENTO_ENABLED": "0", "DATABENTO_API_KEY": "", "TAU_DATABENTO_DATASETS": "",
    "TAU_DATABENTO_MAX_COST_USD": "0", "TAU_ALPACA_ENABLED": "0",
    "APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": "", "TAU_ALPACA_FEED": "iex",
    "TAU_ALPACA_SYMBOLS": DEFAULT_EQUITIES, "ALPACA_DATA_ENDPOINT": "https://data.alpaca.markets",
    "TAU_MASSIVE_ENABLED": "0", "MASSIVE_API_KEY": "", "TAU_MASSIVE_FX_FEED": "end_of_day",
    "TAU_MASSIVE_FX_SYMBOLS": DEFAULT_FX,
    "TAU_MASSIVE_DATASETS": "fx,treasury_yields,funding_conditions,options",
}


@dataclass(frozen=True)
class Routing:
    primary: str = "alpaca"
    databento_default_dataset: Optional[str] = None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Routing":
        env = os.environ if env is None else env
        primary = env.get("TAU_MARKET_DATA_PRIMARY", "alpaca").strip()
        if primary not in {"alpaca", "databento"}:
            raise MarketDataError("invalid_configuration", "TAU_MARKET_DATA_PRIMARY must be alpaca or databento.")
        dataset = env.get("TAU_DATABENTO_DEFAULT_DATASET", "").strip() or None
        if dataset is not None:
            dataset_checked(dataset)
            allowed = tuple(s.strip() for s in env.get("TAU_DATABENTO_DATASETS", "").split(",") if s.strip())
            if dataset not in allowed:
                raise MarketDataError("invalid_configuration", "TAU_DATABENTO_DEFAULT_DATASET must be in TAU_DATABENTO_DATASETS.")
        if primary == "databento" and dataset is None:
            raise MarketDataError("invalid_configuration", "Set TAU_DATABENTO_DEFAULT_DATASET for the primary historical-bar route.")
        return cls(primary, dataset)

    def resolve(self, request: Dict) -> Dict:
        """Resolve the omitted bar provider once; preserve every explicit choice."""
        if not isinstance(request, dict):
            raise ValueError("Market-data requests must be objects.")
        result = dict(request)
        if "provider" not in result:
            result["provider"] = self.primary if result.get("kind") == "bars" else "alpaca"
            if result["provider"] == "databento":
                result.setdefault("dataset", self.databento_default_dataset)
        return result

    def describe(self) -> Dict:
        return {"primary_bar_provider": self.primary,
                "default_bar_dataset": self.databento_default_dataset if self.primary == "databento" else None,
                "snapshots_provider": "alpaca", "fx_macro_options_provider": "massive",
                "automatic_fallback": False}


def check_configuration(env: Optional[Mapping[str, str]] = None) -> Dict:
    """Validate enabled adapters; never return a credential or contact a provider."""
    env = {**ENV_DEFAULTS, **(os.environ if env is None else env)}
    errors, warnings, providers = [], [], {}
    routing = None
    try:
        routing = Routing.from_env(env)
    except MarketDataError as exc:
        errors.append({"field": "routing", "code": exc.code, "message": str(exc)})
    for name, config_type in (("alpaca", AlpacaConfig), ("massive", MassiveConfig), ("databento", DatabentoConfig)):
        flag = "TAU_%s_ENABLED" % name.upper()
        value = env.get(flag, "0")
        enabled = value == "1"
        item = {"enabled": enabled, "configured": False}
        providers[name] = item
        if value not in {"0", "1"}:
            errors.append({"field": flag, "code": "invalid_configuration", "message": "Activation flags must be exactly 0 or 1."})
        if not enabled:
            continue
        try:
            config = config_type.from_env(env)
            if name == "alpaca":
                symbols_checked([s.strip() for s in env.get("TAU_ALPACA_SYMBOLS", DEFAULT_EQUITIES).split(",")])
                item.update(feed=config.feed, capabilities=["historical_bars", "current_snapshots"])
                if config.feed == "iex":
                    warnings.append("Alpaca IEX is a single-exchange feed, not consolidated SIP.")
            elif name == "massive":
                if "fx" in config.datasets:
                    pairs_checked([s.strip() for s in env.get("TAU_MASSIVE_FX_SYMBOLS", DEFAULT_FX).split(",")])
                item.update(fx_feed=config.fx_feed, datasets=list(config.datasets))
                warnings.append("Massive current FX and options require the matching entitlements; daily rates are not intraday or point-in-time vintages.")
            else:
                item.update(datasets=list(config.datasets), historical_only=True,
                            max_estimated_cost_usd=str(config.max_cost_usd))
                if not config.datasets:
                    raise MarketDataError("invalid_configuration", "Set a nonempty TAU_DATABENTO_DATASETS allowlist.")
                if config.max_cost_usd == 0:
                    raise MarketDataError("cost_limit", "Set a positive TAU_DATABENTO_MAX_COST_USD; zero blocks all positive-cost downloads.")
                warnings.append("Tau's Databento adapter supports historical bars only; no live stream, spot FX, published rates or options-chain/Greeks adapter is implemented.")
                warnings.append("Databento estimates are limited per agent-data context, not durably across workers or against the vendor invoice.")
            item["configured"] = True
        except MarketDataError as exc:
            errors.append({"field": name, "code": exc.code, "message": str(exc)})
    if routing and not providers[routing.primary]["enabled"]:
        errors.append({"field": "TAU_%s_ENABLED" % routing.primary.upper(), "code": "provider_disabled",
                       "message": "The selected primary bar provider must be explicitly enabled; no fallback is used."})
    ready = not errors
    return {"ready": ready, "status": "ready" if ready else "invalid",
            "routing": routing.describe() if routing else None, "providers": providers,
            "errors": errors, "warnings": warnings,
            "provider_validation": "not_performed", "network_requests": 0,
            "note": "Local configuration only. Licensing, provider reads and a real queued worker/model canary still require acceptance."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.parse_args(argv)
    report = check_configuration()
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
