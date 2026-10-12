"""Read-only action/calendar/identity capture and independent public corroboration.

Run in the isolated Alpaca environment. Every successful response is retained;
retrieval timestamps do not assert original historical availability or data rights.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import requests

from fetch_alpaca import NY, ROOT, SetupError, load_config

SUPPORTED = {"SPY", "QQQ", "IWM"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_json(session, url, params):
    """No redirects, response bodies in exceptions, or credential-bearing URLs."""
    try:
        with session.get(url, params=params, timeout=(10, 30),
                         allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise SetupError(f"Enrichment HTTP status {response.status_code}; response body omitted.")
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) > 4_000_000:
                    raise SetupError("Enrichment response exceeds the declared size limit.")
            return json.loads(body)
    except (requests.RequestException, ValueError):
        raise SetupError("Enrichment transport/JSON failure; raw error omitted.") from None


def download(config, snapshot, output, independent=True):
    source = json.loads((snapshot / "manifest.json").read_text())
    symbols = sorted(source["coverage"])
    if not symbols or not set(symbols) <= SUPPORTED:
        raise SetupError("V1 enrichment supports only the explicitly selected SPY/QQQ/IWM ETF basket.")
    for name in ("daily_raw.csv", "provider_bars.json"):
        if sha(snapshot / name) != source["files"][name]:
            raise SetupError("Source snapshot checksum mismatch.")
    first = min(source["coverage"][s]["first_session"] for s in symbols)
    last = max(source["coverage"][s]["last_session"] for s in symbols)
    if date.fromisoformat(first) < date(2016, 1, 1):
        raise SetupError("This integration uses 2016 or later observations.")
    output.mkdir(parents=True, exist_ok=False)
    files, calls = {}, []
    manifest = {"schema_version": 1, "provider": "Alpaca plus optional Yahoo public corroboration",
                "quality": "proxy", "availability_basis": "retrieval_time_only",
                "source_snapshot_manifest_sha256": sha(snapshot / "manifest.json"),
                "source_snapshot": str(snapshot.resolve()), "symbols": symbols,
                "first_session": first, "last_session": last,
                "commercial_rights_reviewed": False, "files": files, "requests": calls}

    def capture(name, session, url, params):
        raw = fetch_json(session, url, params)
        path = output / name
        path.write_text(json.dumps(raw, indent=2, allow_nan=False) + "\n")
        files[name] = {"path": name, "sha256": sha(path)}
        calls.append({"url": url, "params": params,
                      "retrieved_at": datetime.now(timezone.utc).isoformat(),
                      "file": name, "http_status": 200})
        return raw

    try:
        with requests.Session() as private:
            private.headers.update({"APCA-API-KEY-ID": config.key,
                                    "APCA-API-SECRET-KEY": config.secret})
            # The API filters process_date, which can be the future payment date.
            # Request a fixed six-month extension, then filter by ex-date at import.
            params = {"symbols": ",".join(symbols), "start": first,
                      "end": (date.fromisoformat(last) + timedelta(days=180)).isoformat(),
                      "limit": 1000, "sort": "asc", "data_quality": "all"}
            tokens = set()
            for page in range(100):
                raw = capture(f"actions_{page:03d}.json", private,
                              config.endpoint + "/v1/corporate-actions", params)
                if not isinstance(raw.get("corporate_actions"), dict):
                    raise SetupError("Unexpected corporate-action response.")
                token = raw.get("next_page_token")
                if not token:
                    break
                if not isinstance(token, str) or token in tokens:
                    raise SetupError("Corporate-action pagination repeated/invalid token.")
                tokens.add(token)
                params = {**params, "page_token": token}
            else:
                raise SetupError("Corporate-action page budget exhausted.")
            capture("calendar.json", private, "https://paper-api.alpaca.markets/v2/calendar",
                    {"start": first, "end": last})
            for symbol in symbols:
                capture(f"asset_{symbol}.json", private,
                        "https://paper-api.alpaca.markets/v2/assets/" + symbol, {})
        if independent:
            # Separate session: no Alpaca authentication headers reach this host.
            beginning = datetime.combine(date.fromisoformat(first), time.min, tzinfo=NY)
            end = datetime.combine(date.fromisoformat(last) + timedelta(days=1), time.min, tzinfo=NY)
            with requests.Session() as public:
                public.headers.update({"User-Agent": "Mozilla/5.0"})
                for symbol in symbols:
                    capture(f"independent_{symbol}.json", public,
                            "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol,
                            {"period1": int(beginning.timestamp()), "period2": int(end.timestamp()),
                             "interval": "1d", "events": "div,splits", "includeAdjustedClose": "false"})
        manifest["status"] = "captured"
    except (SetupError, KeyError, TypeError, ValueError) as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error) if isinstance(error, SetupError) else "Invalid response schema; raw error omitted."
        raise SetupError(manifest["error"]) from None
    finally:
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"output": str(output.resolve()), "responses": len(files), "symbols": symbols,
            "status": manifest["status"], "quality": "proxy", "orders_submitted": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--without-independent", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = download(load_config(args.env_file), args.snapshot.resolve(), args.output.resolve(),
                          not args.without_independent)
        print(json.dumps(result, indent=2))
        return 0
    except (SetupError, OSError, KeyError, TypeError, ValueError) as error:
        message = str(error) if isinstance(error, SetupError) else "Enrichment configuration/files failed; raw error omitted."
        print(json.dumps({"status": "failed", "error": message}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
