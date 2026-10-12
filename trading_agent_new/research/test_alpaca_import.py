"""Accounting/timing/source-boundary tests for the real-data import adapter."""
import csv
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from quant_agent.common import GateError, file_hash
from quant_agent.data import Dataset, qualify
from quant_agent.store import Store

import build_alpaca_import as adapter


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot, self.enrichment = self.root / "snapshot", self.root / "enrichment"
        self.snapshot.mkdir(); self.enrichment.mkdir()
        self.days = ["2026-10-07", "2026-10-08", "2026-10-09"]
        self.bar_rows = [{"symbol": "SPY", "session": day, "timestamp": day + "T04:00:00+00:00",
                          "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000} for day in self.days]
        with (self.snapshot / "daily_raw.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.bar_rows[0]));writer.writeheader();writer.writerows(self.bar_rows)
        (self.snapshot / "provider_bars.json").write_text("{}")
        original = {"feed": "sip", "adjustment": "raw", "coverage": {"SPY": {"first_session": self.days[0], "last_session": self.days[-1]}},
                    "files": {p.name: file_hash(p) for p in self.snapshot.iterdir()}}
        (self.snapshot / "manifest.json").write_text(json.dumps(original))
        timestamps = [int(datetime.fromisoformat(d + "T13:30:00+00:00").timestamp()) for d in self.days]
        self.payloads = {
            "calendar.json": [{"date": day, "open": "09:30", "close": "16:00", "settlement_date": "2026-10-13"} for day in self.days],
            "asset_SPY.json": {"id": "b28f4066-5c6d-479b-a2af-85dc1a8f16fb", "symbol": "SPY", "class": "us_equity", "status": "active"},
            "actions_000.json": {"corporate_actions": {"cash_dividends": [{"symbol": "SPY", "ex_date": self.days[1], "rate": 1.5}]}},
            "independent_SPY.json": {"chart": {"error": None, "result": [{"meta": {"symbol": "SPY", "currency": "USD"},
                "timestamp": timestamps, "indicators": {"quote": [{"close": [101, 101, 101]}]},
                "events": {"dividends": {"fixture": {"date": timestamps[1], "amount": 1.5}}}}]}}
        }
        self.save()

    def save(self):
        for name, payload in self.payloads.items():
            (self.enrichment / name).write_text(json.dumps(payload))
        manifest = {"status": "captured", "symbols": ["SPY"], "requests": [],
                    "source_snapshot_manifest_sha256": file_hash(self.snapshot / "manifest.json"),
                    "files": {name: {"path": name, "sha256": file_hash(self.enrichment / name)} for name in self.payloads}}
        (self.enrichment / "manifest.json").write_text(json.dumps(manifest))

    def build(self, exploratory=True):
        return adapter.build(self.snapshot, self.enrichment, self.root / "import", exploratory)

    def test_missing_pay_date_refused_until_explicit_proxy_policy(self):
        with self.assertRaisesRegex(GateError, "pay-date review incomplete"):
            self.build(False)
        self.assertFalse((self.root / "import").exists())
        result = self.build()
        self.assertEqual(result["assumed_dividend_pay_dates"], 1)
        data = Dataset(self.root / "import")
        self.assertEqual(data.actions[self.days[1]][0]["pay_date"], "2026-11-07")
        receipt = json.loads((self.root / "import/action_provenance.json").read_text())[0]
        self.assertTrue(receipt["pay_date_assumed"])
        self.assertIsNone(receipt["pay_date"])
        self.assertFalse(result["paper_eligible"])

    def test_provider_pay_date_raw_prices_calendar_and_stable_id_preserved(self):
        self.payloads["actions_000.json"]["corporate_actions"]["cash_dividends"][0]["payable_date"] = "2026-10-30"
        self.payloads["calendar.json"][0]["close"] = "13:00"
        self.save()
        result = self.build(False)
        data = Dataset(self.root / "import")
        self.assertEqual(result["assumed_dividend_pay_dates"], 0)
        self.assertEqual(data.actions[self.days[1]][0]["pay_date"], "2026-10-30")
        self.assertEqual(data.sessions[self.days[-1]]["settlement_date"], "2026-10-13")
        self.assertEqual(data.sessions[self.days[0]]["close_at"], "2026-10-07T13:00:00-04:00")
        identity = next(iter(data.assets))
        self.assertEqual(identity, "ALPACA:b28f4066-5c6d-479b-a2af-85dc1a8f16fb")
        self.assertEqual(data.bars[self.days[0], identity]["close"], 101)
        self.assertEqual(data.bars[self.days[0], identity]["available_at"], "2026-10-07T13:15:00-04:00")
        self.assertEqual(data.borrow, {})
        self.assertEqual(data.financing[self.days[0]]["credit_rate"], 0)
        self.assertIn("assumed", data.manifest["availability_basis"])

    def test_source_mutation_missing_bars_calendar_and_unknown_actions_block(self):
        for mutation in ("checksum", "calendar", "unsupported"):
            with self.subTest(mutation=mutation):
                original = deepcopy(self.payloads)
                if mutation == "checksum":
                    (self.enrichment / "calendar.json").write_text("[]")
                elif mutation == "calendar":
                    self.payloads["calendar.json"].pop();self.save()
                else:
                    self.payloads["actions_000.json"]["corporate_actions"]["spin_offs"] = [{"symbol": "SPY", "ex_date": self.days[1]}];self.save()
                with self.assertRaises(GateError):
                    self.build()
                self.assertFalse((self.root / "import").exists())
                self.payloads = original;self.save()

    def test_independent_only_events_and_amount_conflicts_are_visible(self):
        self.payloads["actions_000.json"]["corporate_actions"]["cash_dividends"][0]["rate"] = 1.6
        events = self.payloads["independent_SPY.json"]["chart"]["result"][0]["events"]["dividends"]
        events["second"] = {"date": int(datetime.fromisoformat(self.days[2] + "T13:30:00+00:00").timestamp()), "amount": 0.3}
        self.save()
        with self.assertRaises(GateError):self.build(False)
        self.build()
        data = Dataset(self.root / "import")
        gaps = data.manifest["qualification_gaps"]
        self.assertEqual(len(gaps["missing_primary_actions"]), 1)
        self.assertEqual(len(gaps["action_amount_disagreements"]), 1)
        self.assertEqual(data.actions[self.days[1]][0]["value"], 1.6)
        self.assertEqual(data.actions[self.days[2]][0]["value"], 0.3)

    def test_current_proxy_cannot_be_qualified_or_overwritten(self):
        self.build()
        data = Dataset(self.root / "import")
        store = Store(self.root / "state")
        try:
            self.assertFalse(data.qualification(store)["qualified"])
            with self.assertRaisesRegex(GateError, "cannot be promoted"):
                qualify(store, data, {}, {})
            with self.assertRaisesRegex(GateError, "already exists"):
                self.build()
        finally:store.close()

    def test_duplicate_payment_dates_do_not_double_count_and_require_corroboration(self):
        actions = self.payloads["actions_000.json"]["corporate_actions"]["cash_dividends"]
        actions[0]["payable_date"] = "2026-10-10"
        actions.append({**actions[0], "payable_date": "2026-10-30"})
        self.save()
        with self.assertRaisesRegex(GateError, "Multiple same-day"):
            self.build(False)
        self.build()
        data = Dataset(self.root / "import")
        self.assertEqual(len(data.actions[self.days[1]]), 1)
        self.assertEqual(data.actions[self.days[1]][0]["value"], 1.5)
        self.assertEqual(data.actions[self.days[1]][0]["pay_date"], "2026-11-07")
        self.assertEqual(len(data.manifest["qualification_gaps"]["ambiguous_same_day_primary_actions"]), 1)
        # A different amount cannot be silently merged under this proxy policy.
        actions[1]["rate"] = 2;self.save()
        with self.assertRaisesRegex(GateError, "Multiple same-day"):
            adapter.prepare(self.snapshot, self.enrichment, True)


if __name__ == "__main__":
    unittest.main()
