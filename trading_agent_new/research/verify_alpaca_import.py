"""Independent source-to-import checks; never execute or import the converter."""
import argparse
from collections import defaultdict
import csv
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_agent.common import GateError, file_hash
from quant_agent.data import Dataset

NY = ZoneInfo("America/New_York")


def verify(snapshot, enrichment, imported, root):
    dataset = Dataset(imported)
    source = json.loads((snapshot / "manifest.json").read_text())
    extra = json.loads((enrichment / "manifest.json").read_text())
    checks = {}
    checks["snapshot_binding_and_hashes"] = (
        extra["source_snapshot_manifest_sha256"] == file_hash(snapshot / "manifest.json")
        and all(file_hash(snapshot / name) == value for name, value in source["files"].items()))
    payload = {}
    for name, item in extra["files"].items():
        path = (enrichment / item["path"]).resolve()
        if not path.is_relative_to(enrichment.resolve()) or file_hash(path) != item["sha256"]:
            raise GateError("Enrichment source checksum/path failed")
        payload[name] = json.loads(path.read_text())
    checks["enrichment_hashes_and_binding"] = (extra["status"] == "captured"
        and dataset.manifest["provenance"]["enrichment_manifest_sha256"] == file_hash(enrichment / "manifest.json"))
    with (snapshot / "daily_raw.csv").open(newline="") as stream:
        bars = list(csv.DictReader(stream))
    raw = {(row["session"], row["symbol"]): row for row in bars}
    symbols = {value["symbol"]: key for key, value in dataset.assets.items()}
    checks["raw_prices_and_keys_preserved"] = (len(raw) == len(bars) == len(dataset.bars)
        and all((day, symbol) in raw and all(float(raw[day, symbol][field]) == dataset.bars[day, identity][field]
                for field in ("open", "high", "low", "close", "volume"))
                for symbol, identity in symbols.items() for day in dataset.days))
    calendar = {row["date"]: row for row in payload["calendar.json"]}
    checks["calendar_hours_and_settlement_preserved"] = all(
        dataset.sessions[day]["open_at"] == datetime.combine(date.fromisoformat(day), time.fromisoformat(calendar[day]["open"]), NY).isoformat()
        and dataset.sessions[day]["close_at"] == datetime.combine(date.fromisoformat(day), time.fromisoformat(calendar[day]["close"]), NY).isoformat()
        and dataset.sessions[day]["settlement_date"] == calendar[day]["settlement_date"] for day in dataset.days)
    checks["current_uuid_and_fixed_etf_scope"] = all(
        identity == "ALPACA:" + payload[f"asset_{symbol}.json"]["id"]
        and dataset.assets[identity]["kind"] == "etf" for symbol, identity in symbols.items())

    primary, secondary = defaultdict(list), {}
    for name, page in payload.items():
        if not name.startswith("actions_"):
            continue
        for kind, records in page["corporate_actions"].items():
            for event in records:
                day = event["ex_date"]
                if day in dataset.sessions and event["symbol"] in symbols:
                    tag = "dividend" if kind == "cash_dividends" else "split"
                    amount = float(event["rate"]) if tag == "dividend" else float(event["new_rate"]) / float(event["old_rate"])
                    primary[event["symbol"], day, tag].append({"value": amount, "pay_date": event.get("payable_date")})
    differences = []
    for symbol in symbols:
        item = payload[f"independent_{symbol}.json"]["chart"]["result"][0]
        for kind, records in item.get("events", {}).items():
            for event in records.values():
                day = datetime.fromtimestamp(event["date"], timezone.utc).astimezone(NY).date().isoformat()
                if day in dataset.sessions:
                    tag = "dividend" if kind == "dividends" else "split"
                    secondary[symbol, day, tag] = float(event["amount"]) if tag == "dividend" else float(event["numerator"]) / float(event["denominator"])
        prices = item["indicators"]["quote"][0]["close"]
        for stamp, independent_close in zip(item["timestamp"], prices):
            day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(NY).date().isoformat()
            if (day, symbol) in raw and independent_close is not None:
                value = float(raw[day, symbol]["close"])
                relative = abs(value - independent_close) / value
                if relative > 0.0005:
                    differences.append({"symbol": symbol, "session": day, "alpaca_close": value,
                                        "independent_close": independent_close, "relative_difference": relative})
    actual = {(dataset.assets[a["asset_id"]]["symbol"], day, a["kind"]): a
              for day, events in dataset.actions.items() for a in events}
    action_match = set(actual) == set(primary) | set(secondary)
    assumed = 0
    for key, event in actual.items():
        candidates = primary.get(key, [])
        expected_value = candidates[0]["value"] if candidates else secondary[key]
        action_match &= event["value"] == expected_value
        if key[2] == "dividend":
            original_pay = candidates[0]["pay_date"] if len(candidates) == 1 else None
            expected_pay = original_pay or (date.fromisoformat(key[1]) + timedelta(days=30)).isoformat()
            action_match &= event["pay_date"] == expected_pay
            assumed += not bool(original_pay)
    provenance = dataset.manifest["action_provenance"]
    checks["action_entitlements_and_declared_payment_policy"] = (action_match
        and assumed == dataset.manifest["qualification_gaps"]["assumed_dividend_pay_dates"]
        and file_hash(imported / provenance["path"]) == provenance["sha256"])
    checks["source_disagreements_preserved"] = all(
        dataset.manifest["qualification_gaps"]["independent_price_checks"][symbol]["within_fixed_5bp_tolerance"]
        == (not any(row["symbol"] == symbol for row in differences)) for symbol in symbols)
    checks["assumptions_cannot_be_source_qualification"] = (
        dataset.quality == "proxy" and dataset.manifest["availability_basis"].startswith("assumed_")
        and dataset.manifest["data_constraints"]["paper_eligible"] is False
        and dataset.manifest["qualification_gaps"]["commercial_rights_reviewed"] is False
        and not dataset.borrow and all(row["reference_rate"] == row["credit_rate"] == row["debit_rate"] == 0 for row in dataset.financing.values()))
    contexts = [dataset.context(index, 63, False) for index in (63, len(dataset.days) // 2, len(dataset.days) - 1)]
    checks["assumed_asof_context_excludes_future_rows"] = all(
        len(context["history"]) == len(symbols) and all(len(rows) == 63 and all(
            row["session"] <= context["session"] and datetime.fromisoformat(row["available_at"]) <= datetime.fromisoformat(context["asof"])
            for row in rows) for rows in context["history"].values()) for context in contexts)
    baseline = json.loads((root / "results/agent_v1/legacy_baseline.json").read_text())
    checks["legacy_files_preserved"] = all(file_hash(root / name) == value for name, value in baseline.items())
    return {"status": "passed" if all(checks.values()) else "failed", "checks": checks,
            "checks_passed": sum(checks.values()), "checks_total": len(checks), "dataset_id": dataset.id,
            "counts": dataset.audit()["counts"], "assumed_payment_dates": assumed,
            "independent_close_disagreements_over_5bp": len(differences),
            "largest_close_disagreements": sorted(differences, key=lambda r: r["relative_difference"], reverse=True)[:12],
            "data_qualified": False, "source_corroboration_passed": not bool(differences),
            "performance_measured": False, "legacy_files_checked": len(baseline)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "enrichment", "imported", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.snapshot.resolve(), args.enrichment.resolve(), args.imported.resolve(), Path(__file__).resolve().parents[1])
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "largest_close_disagreements"}, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
