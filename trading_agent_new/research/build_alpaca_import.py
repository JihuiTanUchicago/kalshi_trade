"""Build a seven-table ETF proxy import, with explicit row-level assumptions.

Default refuses missing dividend payment dates/source disagreements. The explicit
--exploratory option uses a fixed, disclosed 30-calendar-day payment assumption
and a union of corroborating dividend events. It can never qualify data for paper.
Run in .agent-venv; no provider SDK or credentials are needed for this conversion.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID
from zoneinfo import ZoneInfo

from quant_agent.common import GateError, file_hash
from quant_agent.data import Dataset, TABLES

NY = ZoneInfo("America/New_York")
SUPPORTED = {"SPY", "QQQ", "IWM"}
PAY_DELAY_DAYS = 30


def checked_json(root, descriptor):
    path = (root / descriptor["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or file_hash(path) != descriptor["sha256"]:
        raise GateError("Enrichment path/checksum mismatch")
    return json.loads(path.read_text())


def prepare(snapshot: Path, enrichment: Path, exploratory=False):
    snapshot, enrichment = snapshot.resolve(), enrichment.resolve()
    original = json.loads((snapshot / "manifest.json").read_text())
    source = json.loads((enrichment / "manifest.json").read_text())
    if source.get("status") != "captured" or source.get("source_snapshot_manifest_sha256") != file_hash(snapshot / "manifest.json"):
        raise GateError("Enrichment must be a successful capture bound to this exact price snapshot")
    symbols = sorted(original["coverage"])
    if not symbols or not set(symbols) <= SUPPORTED or source["symbols"] != symbols:
        raise GateError("Only the declared SPY/QQQ/IWM ETF basket is supported")
    if original.get("adjustment") != "raw" or original.get("feed") != "sip":
        raise GateError("The import requires explicit raw SIP prices")
    for name in ("daily_raw.csv", "provider_bars.json"):
        if file_hash(snapshot / name) != original["files"][name]:
            raise GateError("Source price snapshot was modified")
    payloads = {name: checked_json(enrichment, value) for name, value in source["files"].items()}
    with (snapshot / "daily_raw.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    raw_bars = {(row["session"], row["symbol"]): row for row in rows}
    if len(raw_bars) != len(rows):
        raise GateError("Duplicate source price observations")
    days = sorted({r["session"] for r in rows})
    if not days or days[0] < "2016-01-01":
        raise GateError("Source price coverage must start in 2016 or later")
    calendar = {}
    for item in payloads["calendar.json"]:
        day = item["date"]
        if day in calendar:
            raise GateError("Duplicate calendar session")
        if days[0] <= day <= days[-1]:
            calendar[day] = item
    if sorted(calendar) != days or any((day, symbol) not in raw_bars for day in days for symbol in symbols):
        raise GateError("Calendar/bar coverage mismatch; missing observations cannot be imputed")
    tables = {name: [] for name in TABLES}
    ids = {}
    for symbol in symbols:
        master = payloads[f"asset_{symbol}.json"]
        if master.get("symbol") != symbol or master.get("class") != "us_equity" or master.get("status") != "active":
            raise GateError("Unexpected current security identity")
        ids[symbol] = "ALPACA:" + str(UUID(master["id"]))
        tables["assets"].append({"asset_id": ids[symbol], "symbol": symbol, "kind": "etf",
                                 "currency": "USD", "leverage_factor": 1, "inverse": 0})
    for day in days:
        item = calendar[day]
        opened = datetime.combine(date.fromisoformat(day), time.fromisoformat(item["open"]), NY)
        closed = datetime.combine(date.fromisoformat(day), time.fromisoformat(item["close"]), NY)
        settlement = date.fromisoformat(item["settlement_date"])
        if closed <= opened or settlement < date.fromisoformat(day):
            raise GateError("Invalid source calendar/settlement record")
        tables["sessions"].append({"session": day, "open_at": opened.isoformat(),
                                   "close_at": closed.isoformat(), "settlement_date": settlement.isoformat()})
        # These are simulation assumptions, never original availability evidence.
        availability = (closed + timedelta(minutes=15)).isoformat()
        for symbol in symbols:
            raw = raw_bars[(day, symbol)]
            stamp = datetime.fromisoformat(raw["timestamp"])
            if stamp.tzinfo is None or stamp.astimezone(NY).date().isoformat() != day:
                raise GateError("Source timestamp/session mismatch")
            tables["bars"].append({"session": day, "asset_id": ids[symbol],
                                   **{k: raw[k] for k in ("open", "high", "low", "close", "volume")},
                                   "available_at": availability})
            tables["membership"].append({"session": day, "asset_id": ids[symbol], "eligible": 1,
                                         "available_at": opened.isoformat()})
        # Fixed account policy: zero yield/credit, no margin borrowing or shorts.
        # A hypothetical zero-yield account is not a historical market-rate series.
        tables["financing"].append({"session": day, "credit_rate": 0, "debit_rate": 0,
                                    "reference_rate": 0, "available_at": opened.isoformat()})

    primary, independent, action_receipts, duplicates = {}, {}, [], []
    for name, groups in payloads.items():
        if not name.startswith("actions_"):
            continue
        for kind, events in groups["corporate_actions"].items():
            for event in events:
                symbol = event.get("symbol")
                exdate = event.get("ex_date")
                if symbol not in ids or not exdate:
                    raise GateError("Unresolved corporate action identity/ex-date")
                if not days[0] <= exdate <= days[-1]:
                    continue
                if kind not in {"cash_dividends", "forward_splits", "reverse_splits"}:
                    raise GateError("Unsupported corporate action affects this study; operator resolution required")
                tag = "dividend" if kind == "cash_dividends" else "split"
                key = (symbol, exdate, tag)
                if tag == "dividend":
                    value = float(event["rate"])
                else:
                    value = float(event["new_rate"]) / float(event["old_rate"])
                if key in primary:
                    # A duplicate amount with conflicting payment dates is not
                    # two cash entitlements. Proxy-only de-duplication requires
                    # an independently matching single event below, and replaces
                    # the disputed payment date with the disclosed assumption.
                    previous = primary[key]
                    if not exploratory or tag != "dividend" or previous["value"] != value:
                        raise GateError("Multiple same-day actions require explicit resolution, not silent aggregation")
                    duplicates.append({"key": key, "first": dict(previous), "additional": event,
                                       "proxy_policy": "one independently corroborated amount; payment date assumed"})
                    previous["pay_date"] = None
                    previous["basis"] = "Alpaca conflicting same-day records; one proxy entitlement with assumed payment date"
                    continue
                primary[key] = {"value": value, "pay_date": event.get("payable_date"),
                                "source_file": name, "provider_id": event.get("id"), "basis": "Alpaca current-vintage"}

    corroboration = {}
    for symbol in symbols:
        name = f"independent_{symbol}.json"
        if name not in payloads:
            corroboration[symbol] = {"present": False}
            continue
        chart = payloads[name]["chart"]
        if chart.get("error") or len(chart.get("result") or []) != 1:
            raise GateError("Independent response contains no usable chart")
        item = chart["result"][0]
        if item["meta"]["symbol"] != symbol or item["meta"]["currency"] != "USD":
            raise GateError("Independent symbol/currency mismatch")
        quote = item["indicators"]["quote"][0]
        max_close_diff, matched = 0.0, 0
        for index, stamp in enumerate(item["timestamp"]):
            day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(NY).date().isoformat()
            raw = raw_bars.get((day, symbol))
            if raw is not None and quote["close"][index] is not None:
                max_close_diff = max(max_close_diff, abs(float(raw["close"]) - quote["close"][index]) / float(raw["close"]))
                matched += 1
        corroboration[symbol] = {"present": True, "matched_closes": matched,
                                  "maximum_relative_close_difference": max_close_diff,
                                  "within_fixed_5bp_tolerance": max_close_diff <= 0.0005}
        for kind, events in item.get("events", {}).items():
            if kind not in {"dividends", "splits"}:
                if events:
                    raise GateError("Unsupported independent action requires review")
                continue
            for event in events.values():
                day = datetime.fromtimestamp(event["date"], timezone.utc).astimezone(NY).date().isoformat()
                if not days[0] <= day <= days[-1]:
                    continue
                tag = "dividend" if kind == "dividends" else "split"
                value = float(event["amount"]) if tag == "dividend" else float(event["numerator"]) / float(event["denominator"])
                key = (symbol, day, tag)
                if key in independent:
                    raise GateError("Duplicate independent corporate action")
                independent[key] = {"value": value, "pay_date": None, "source_file": name,
                                    "basis": "Yahoo public current-vintage; payment date unavailable"}

    missing_primary = sorted(set(independent) - set(primary))
    missing_independent = sorted(set(primary) - set(independent))
    differences = [{"key": key, "primary": primary[key]["value"], "independent": independent[key]["value"]}
                   for key in sorted(set(primary) & set(independent))
                   if abs(primary[key]["value"] - independent[key]["value"]) > 0.001]
    if any(tuple(row["key"]) not in independent or abs(independent[tuple(row["key"])]["value"] - primary[tuple(row["key"])]["value"]) > 0.001 for row in duplicates):
        raise GateError("Ambiguous duplicate action has no matching independent single entitlement")
    actions = {**independent, **primary}  # Explicit fixed precedence, retained in receipts.
    missing_pay = [key for key, value in actions.items() if key[2] == "dividend" and not value["pay_date"]]
    if not exploratory and (missing_pay or missing_primary or missing_independent or differences):
        raise GateError("Corporate-action/pay-date review incomplete; use explicit --exploratory for the documented proxy assumptions")
    for (symbol, day, kind), event in sorted(actions.items()):
        if day not in calendar:
            raise GateError("Corporate action ex-date is not a captured trading session")
        pay = event["pay_date"] or ((date.fromisoformat(day) + timedelta(days=PAY_DELAY_DAYS)).isoformat() if kind == "dividend" else "")
        assumed = kind == "dividend" and not event["pay_date"]
        tables["actions"].append({"session": day, "asset_id": ids[symbol], "kind": kind,
                                  "value": event["value"], "pay_date": pay,
                                  "available_at": tables["sessions"][days.index(day)]["open_at"]})
        action_receipts.append({"symbol": symbol, "session": day, "kind": kind, **event,
                                "import_pay_date": pay, "pay_date_assumed": assumed,
                                "historical_availability_proven": False})
    issues = {
        "commercial_rights_reviewed": False, "original_availability_proven": False,
        "survivorship_free_universe": False, "current_security_master_is_historical": False,
        "missing_primary_actions": missing_primary, "missing_independent_actions": missing_independent,
        "action_amount_disagreements": differences, "assumed_dividend_pay_dates": len(missing_pay),
        "ambiguous_same_day_primary_actions": duplicates,
        "independent_price_checks": corroboration,
    }
    return tables, {"quality": "proxy", "availability_basis": "assumed_close_plus_15_minutes",
                    "corporate_action_coverage": "proxy_union_current_vintages",
                    "universe_coverage": "fixed_current_etf_basket", "borrow_basis": "excluded_etf_shorts",
                    "financing_basis": "fixed_zero_yield_long_only_account_assumption",
                    "data_constraints": {"exploratory_only": True, "allow_short": False,
                                         "maximum_scored_end": days[-1], "paper_eligible": False,
                                         "pay_date_policy": "provider date, otherwise ex-date + 30 calendar days",
                                         "historical_availability": "assumed; not evidence of original publication",
                                         "price_precedence": "raw Alpaca SIP; independent prices never replace bars"},
                    "qualification_gaps": issues,
                    "provenance": {"price_manifest_sha256": file_hash(snapshot / "manifest.json"),
                                   "enrichment_manifest_sha256": file_hash(enrichment / "manifest.json"),
                                   "source_retrievals": source["requests"]}}, action_receipts


def build(snapshot, enrichment, output, exploratory=False):
    if output.exists():
        raise GateError("Import output already exists; choose a fresh directory")
    tables, metadata, actions = prepare(snapshot, enrichment, exploratory)
    output.mkdir(parents=True, exist_ok=False)
    files = {}
    for name, columns in TABLES.items():
        path = output / (name + ".csv")
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted(columns))
            writer.writeheader()
            writer.writerows(tables[name])
        files[name] = {"path": path.name, "sha256": file_hash(path)}
    action_path = output / "action_provenance.json"
    action_path.write_text(json.dumps(actions, indent=2) + "\n")
    manifest = {"schema_version": 1, **metadata, "files": files,
                "action_provenance": {"path": action_path.name, "sha256": file_hash(action_path)}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    dataset = Dataset(output)
    audit = {**dataset.audit(), "qualification_gaps": metadata["qualification_gaps"],
             "source_kind": "genuine observations; explicitly assumed timing/account/pay dates",
             "paper_eligible": False, "commercially_qualified": False}
    (output / "IMPORT_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n")
    return {"import": str(output.resolve()), "dataset_id": dataset.id,
            "counts": audit["counts"], "first_session": dataset.days[0], "last_session": dataset.days[-1],
            "quality": "proxy", "assumed_dividend_pay_dates": metadata["qualification_gaps"]["assumed_dividend_pay_dates"],
            "paper_eligible": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--enrichment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exploratory", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.snapshot, args.enrichment, args.output, args.exploratory), indent=2))
        return 0
    except (GateError, OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as error:
        print(json.dumps({"status": "blocked", "message": str(error) if isinstance(error, GateError) else "Invalid source schema/files; details omitted."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
