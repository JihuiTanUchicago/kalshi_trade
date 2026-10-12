"""Provider-neutral file imports and a strictly time-filtered strategy view.

CSV is the dependency-free V1 interchange. Source manifests/receipts are immutable.
Data rights and availability evidence require an operator review outside agent tools.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import csv
import json

from .common import GateError, canonical, digest, file_hash, finite, integer, timestamp, utcnow
from .store import Store


TABLES = {
    "sessions": {"session", "open_at", "close_at", "settlement_date"},
    "assets": {"asset_id", "symbol", "kind", "currency", "leverage_factor", "inverse"},
    "bars": {"session", "asset_id", "open", "high", "low", "close", "volume", "available_at"},
    "membership": {"session", "asset_id", "eligible", "available_at"},
    "actions": {"session", "asset_id", "kind", "value", "pay_date", "available_at"},
    "borrow": {"session", "asset_id", "shares", "fee_rate", "available_at"},
    "financing": {"session", "credit_rate", "debit_rate", "reference_rate", "available_at"},
}
QUALIFICATION_CHECKS = {"rights", "independent_source", "availability_vintages", "universe_survivorship",
                        "corporate_actions_pay_dates", "settlement_calendar", "historical_borrow_financing"}


class Dataset:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        manifest_path = self.directory / "manifest.json"
        if not manifest_path.is_file():
            raise GateError("A licensed import needs manifest.json and the documented CSV tables")
        self.manifest = json.loads(manifest_path.read_text())
        if self.manifest.get("schema_version") != 1:
            raise GateError("Unsupported data schema")
        if self.manifest.get("quality") not in {"synthetic", "proxy", "licensed_unqualified"}:
            raise GateError("Imports cannot self-declare qualified data")
        self.id = digest(self.manifest)
        self.quality = self.manifest["quality"]
        self.tables = {}
        files = self.manifest.get("files", {})
        if set(files) != set(TABLES):
            raise GateError("All seven data tables must be declared, including empty action/borrow tables")
        for name, columns in TABLES.items():
            descriptor = files[name]
            path = (self.directory / descriptor["path"]).resolve()
            if not path.is_relative_to(self.directory) or path.suffix != ".csv":
                raise GateError("Import paths must be CSV files inside the import directory")
            if file_hash(path) != descriptor.get("sha256"):
                raise GateError(f"Import checksum failed: {name}")
            with path.open(newline="") as stream:
                reader = csv.DictReader(stream)
                if set(reader.fieldnames or []) != columns:
                    raise GateError(f"Wrong columns for {name}: expected {sorted(columns)}")
                self.tables[name] = list(reader)
        self._validate()

    def _validate(self):
        self.sessions = {}
        for row in self.tables["sessions"]:
            day = row["session"]
            if day in self.sessions or date.fromisoformat(row["settlement_date"]) < date.fromisoformat(day):
                raise GateError("Duplicate session or invalid settlement date")
            if timestamp(row["open_at"]) >= timestamp(row["close_at"]):
                raise GateError("Session open must precede close")
            if timestamp(row["open_at"]).date().isoformat() != day:
                raise GateError("Session timestamps do not match session date")
            self.sessions[day] = row
        if not self.sessions or list(self.sessions) != sorted(self.sessions):
            raise GateError("Sessions must be nonempty and chronological")
        self.days = list(self.sessions)
        self.assets = {}
        for row in self.tables["assets"]:
            if row["asset_id"] in self.assets or row["kind"] not in {"common_stock", "etf"} or row["currency"] != "USD":
                raise GateError("Unique stable IDs and USD common stocks/unleveraged ETFs are required")
            if not row["asset_id"] or not row["symbol"]:
                raise GateError("Missing security identity")
            if finite(row["leverage_factor"],"security leverage factor") != 1 or row["inverse"] != "0":
                raise GateError("V1 excludes leveraged and inverse ETFs")
            self.assets[row["asset_id"]] = row
        self.bars, self.membership, self.borrow, self.financing = {}, {}, {}, {}
        for name in ("bars", "membership", "borrow", "financing"):
            target = getattr(self, name)
            for row in self.tables[name]:
                day = row["session"]
                asset = row.get("asset_id")
                if day not in self.sessions or (asset and asset not in self.assets):
                    raise GateError(f"Unknown session/security in {name}")
                key = (day, asset) if asset else day
                if key in target:
                    raise GateError(f"Duplicate {name} key; resolve vintages explicitly before import")
                timestamp(row["available_at"])
                if name == "bars":
                    for field in ("open", "high", "low", "close", "volume"):
                        row[field] = finite(row[field], field)
                    if min(row[k] for k in ("open", "high", "low", "close")) <= 0 or row["volume"] < 0:
                        raise GateError("Prices must be positive and volume nonnegative")
                    if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]) or row["low"] > row["high"]:
                        raise GateError("OHLC inconsistency")
                    if timestamp(row["available_at"]) < timestamp(self.sessions[day]["close_at"]):
                        raise GateError("A completed daily bar cannot be available before the session close")
                elif name == "membership":
                    if row["eligible"] not in {"0", "1"}:
                        raise GateError("Membership eligibility must be 0 or 1")
                    row["eligible"] = row["eligible"] == "1"
                elif name == "borrow":
                    if self.assets[asset]["kind"] != "common_stock":
                        raise GateError("V1 supports shorting common stocks only")
                    row["shares"] = integer(row["shares"], "borrow shares")
                    row["fee_rate"] = finite(row["fee_rate"], "annual borrow fee")
                    if row["fee_rate"] < 0:
                        raise GateError("Negative borrow fee")
                else:
                    for field in ("credit_rate", "debit_rate", "reference_rate"):
                        row[field] = finite(row[field], field)
                        if not -0.1 <= row[field] <= 5:
                            raise GateError("Invalid financing/reference rate")
                target[key] = row
        for day in self.days:
            if day not in self.financing:
                raise GateError("Financing must cover every session; missing rates cannot be imputed")
            for asset in self.assets:
                member = self.membership.get((day, asset))
                if not member:
                    raise GateError("Dated eligibility must be explicit for every security/session")
                if member["eligible"] and (day, asset) not in self.bars:
                    raise GateError("Eligible-security bar is missing")
        self.actions = {}
        seen = set()
        for row in self.tables["actions"]:
            key = (row["session"], row["asset_id"], row["kind"])
            if key in seen or row["session"] not in self.sessions or row["asset_id"] not in self.assets:
                raise GateError("Duplicate or unknown corporate action")
            seen.add(key)
            timestamp(row["available_at"])
            row["value"] = finite(row["value"], "corporate-action value")
            if row["kind"] not in {"split", "dividend", "delist_cash"}:
                raise GateError("Unsupported action must be resolved, never silently dropped")
            if row["kind"] == "split" and row["value"] <= 0 or row["kind"] != "split" and row["value"] < 0:
                raise GateError("Invalid corporate-action value")
            if row["kind"] == "dividend":
                if not row["pay_date"] or date.fromisoformat(row["pay_date"]) < date.fromisoformat(row["session"]):
                    raise GateError("Dividend needs its actual payable date")
            self.actions.setdefault(row["session"], []).append(row)

    def verify_unchanged(self):
        for descriptor in self.manifest["files"].values():
            if file_hash(self.directory / descriptor["path"]) != descriptor["sha256"]:
                raise GateError("Dataset changed after import")
        if digest(json.loads((self.directory / "manifest.json").read_text())) != self.id:
            raise GateError("Dataset manifest changed after import")

    def qualification(self, store: Store) -> dict:
        row = store.db.execute("SELECT receipt FROM qualifications WHERE dataset=?", (self.id,)).fetchone()
        if row:
            receipt = store.get(row[0], "data_qualification")
            if receipt["dataset_id"] == self.id and self.quality == "licensed_unqualified":
                return {"qualified": True, "quality": "qualified", "receipt": row[0]}
        return {"qualified": False, "quality": self.quality, "receipt": None}

    def context(self, index: int, lookback: int, include_short: bool, delay_minutes: int = 30) -> dict:
        """Only this prefix is sent to generated code; no future identity/files."""
        day = self.days[index]
        asof = timestamp(self.sessions[day]["close_at"])+timedelta(minutes=delay_minutes)
        universe, histories, borrow = [], {}, {}
        for asset, master in self.assets.items():
            member = self.membership[(day, asset)]
            if not member["eligible"] or timestamp(member["available_at"]) > asof:
                continue
            rows = []
            for past in self.days[max(0, index-lookback+1):index+1]:
                bar = self.bars.get((past, asset))
                historical_member = self.membership[(past, asset)]
                if bar and historical_member["eligible"] and timestamp(bar["available_at"]) <= asof:
                    split, dividend = 1.0, 0.0
                    for action in self.actions.get(past, []):
                        if action["asset_id"] == asset and timestamp(action["available_at"]) <= asof:
                            if action["kind"] == "split": split *= action["value"]
                            if action["kind"] == "dividend": dividend += action["value"]
                    rows.append({**bar, "split": split, "dividend": dividend})
            if len(rows) != lookback:
                continue
            universe.append({"asset_id": asset, "kind": master["kind"]})
            histories[asset] = rows
            b = self.borrow.get((day, asset))
            if include_short and master["kind"] == "common_stock" and b and timestamp(b["available_at"]) <= asof:
                borrow[asset] = b
        f = self.financing[day]
        if timestamp(f["available_at"]) > asof:
            raise GateError("As-of financing/reference rate is unavailable")
        return {"api_version": "1", "asof": asof.isoformat(), "session": day,
                "universe": universe, "history": histories, "borrow": borrow, "financing": f}

    def audit(self) -> dict:
        counts = {name: len(rows) for name, rows in self.tables.items()}
        returns = []
        for asset in self.assets:
            previous = None
            for day in self.days:
                bar = self.bars.get((day, asset))
                if bar and previous:
                    split = 1.0; dividend = 0.0
                    for a in self.actions.get(day, []):
                        if a["asset_id"] == asset:
                            if a["kind"] == "split": split *= a["value"]
                            if a["kind"] == "dividend": dividend += a["value"]
                    returns.append((bar["close"] + dividend) * split / previous - 1)
                previous = bar["close"] if bar else None
        import statistics
        return {"dataset_id": self.id, "quality": self.quality, "counts": counts,
                "first_session": self.days[0], "last_session": self.days[-1], "returns_count": len(returns),
                "return_mean": statistics.mean(returns) if returns else None,
                "return_min": min(returns) if returns else None, "return_max": max(returns) if returns else None,
                "extreme_returns_retained": sum(abs(r) > 0.20 for r in returns),
                "checks": {"hashes": True, "missing_eligible_bars": 0, "duplicate_keys": 0, "ohlc": True},
                "qualification": "Source rights, independence and actual availability require a separate review."}


def qualify(store: Store, dataset: Dataset, attestation: dict, documents: dict[str, Path]) -> str:
    """Operator-only; never included among the agent's available tools."""
    if dataset.quality != "licensed_unqualified":
        raise GateError("Synthetic/proxy data cannot be promoted to qualified")
    requirements = {"availability_basis":"historical_asof","corporate_action_coverage":"complete",
                    "universe_coverage":"survivorship_free","borrow_basis":"historical"}
    if any(dataset.manifest.get(k)!=v for k,v in requirements.items()):
        raise GateError("Licensed files still need historical vintages, complete actions/universe and historical borrow evidence")
    for (day,asset),member in dataset.membership.items():
        if member["eligible"] and dataset.assets[asset]["kind"]=="common_stock" and (day,asset) not in dataset.borrow:
            raise GateError("Qualified short-capable data requires explicit borrow/fee rows for every eligible stock/session")
    if set(attestation.get("checks", {})) != QUALIFICATION_CHECKS or set(documents) != QUALIFICATION_CHECKS:
        raise GateError("Every data-qualification check needs a review and supporting file")
    if not attestation.get("reviewer", "").strip() or attestation.get("dataset_id") != dataset.id:
        raise GateError("Named reviewer and exact dataset hash are required")
    evidence = {}
    for name in QUALIFICATION_CHECKS:
        check = attestation["checks"][name]
        if check.get("passed") is not True or not check.get("notes", "").strip():
            raise GateError(f"Unresolved qualification check: {name}")
        file = Path(documents[name])
        if not file.is_file() or file.stat().st_size == 0:
            raise GateError(f"Missing review evidence: {name}")
        evidence[name] = store.put("qualification_document", {"name": name, "sha256": file_hash(file),
                                                              "text": file.read_text()[:200_000]})
    dataset.verify_unchanged()
    key = store.put("data_qualification", {**attestation, "documents": evidence, "reviewed_at": utcnow()})
    with store.db:
        store.db.execute("INSERT INTO qualifications VALUES(?,?) ON CONFLICT(dataset) DO UPDATE SET receipt=excluded.receipt",
                          (dataset.id, key))
    return key
