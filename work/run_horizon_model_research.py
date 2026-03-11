from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client_api import KalshiDataClient
from work.horizon_models import (
    DEFAULT_BASE_URL,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    ResearchConfig,
    run_research,
    write_artifacts,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-minute expiry-resolution model research.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--take-profit-buffer", type=float, default=0.05)
    parser.add_argument("--min-time-to-expiry-sec", type=int, default=120)
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()

    client = KalshiDataClient(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
    )
    config = ResearchConfig(
        take_profit_buffer_dollars=float(args.take_profit_buffer),
        min_time_to_expiry_sec=int(args.min_time_to_expiry_sec),
    )
    results = run_research(client, config, start=args.start, end=args.end)
    json_path, report_path = write_artifacts(results, Path(args.output_dir))

    print(
        json.dumps(
            {
                "ok": True,
                "results_json": str(json_path),
                "report_markdown": str(report_path),
                "selected_models": results["selected_models"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
