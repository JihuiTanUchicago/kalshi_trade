"""Read-only readiness checks. Missing credentials are unavailable, not zero cost."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess


def readiness(config: dict | None = None) -> dict:
    docker = shutil.which("docker")
    reachable = False
    if docker:
        try:
            reachable = subprocess.run([docker,"info","--format","{{.ServerVersion}}"],capture_output=True,timeout=5).returncode==0
        except (OSError,subprocess.TimeoutExpired): pass
    models = []
    for model in (config or {}).get("models",[config] if config and "adapter" in config else []):
        models.append({"adapter":model.get("adapter"),"model":model.get("model"),
                       "credential_present":bool(os.environ.get(model.get("api_key_env",""))),
                       "prices_configured":model.get("input_per_million",0)>0 and model.get("output_per_million",0)>0})
    sdk_version = None
    if importlib.util.find_spec("ibapi") is not None:
        import ibapi
        sdk_version = ibapi.get_version_string()
    return {"offline_core":True,"container_runtime":{"installed":bool(docker),"daemon_available":reachable},
            "ibkr_sdk_available":importlib.util.find_spec("ibapi") is not None,
            "ibkr_sdk_version":sdk_version,
            "model_routes":models,"paid_calls_made_by_doctor":0,"broker_connection_attempted":False,
            "remaining_gates":["Qualified licensed imports and independent source review","Pinned sandbox image and execution isolation tests",
                               "Two real adapter smoke tests and reserved-task memory comparison","Configured paper Gateway/account and five-session broker acceptance"]}
