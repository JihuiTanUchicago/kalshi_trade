"""Boundary tests for free read-only enrichment; all HTTP responses are fixtures."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

import fetch_alpaca_enrichment as enrich
from fetch_alpaca import Config, SetupError


def response(payload, status=200):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(payload).encode()
    r._content_consumed = True
    return r


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "snapshot"
        self.snapshot.mkdir()
        files = {}
        for name in ("daily_raw.csv", "provider_bars.json"):
            path = self.snapshot / name
            path.write_text("fixture")
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest = {"files": files, "coverage": {"SPY": {"first_session": "2016-01-04", "last_session": "2026-10-09"}}}
        self.save_manifest()
        self.config = Config("https://data.alpaca.markets", "fixture-key", "fixture-secret")

    def save_manifest(self):
        (self.snapshot / "manifest.json").write_text(json.dumps(self.manifest))

    def test_paginated_capture_and_authentication_host_separation(self):
        calls = []
        pages = [{"corporate_actions": {"cash_dividends": []}, "next_page_token": "second"},
                 {"corporate_actions": {"cash_dividends": []}, "next_page_token": None}]

        def get(session, url, **kwargs):
            calls.append((url, deepcopy(kwargs), dict(session.headers)))
            if url.endswith("corporate-actions"):
                return response(pages.pop(0))
            return response([] if url.endswith("calendar") else {})

        output = self.root / "enriched"
        with patch.object(requests.Session, "get", get):
            result = enrich.download(self.config, self.snapshot, output)
        self.assertEqual(result["responses"], 5)
        self.assertEqual(calls[1][1]["params"]["page_token"], "second")
        # Include currently announced events with a future process/payment date.
        self.assertEqual(calls[0][1]["params"]["end"], "2027-04-07")
        for url, kwargs, headers in calls:
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["timeout"], (10, 30))
            if "yahoo.com" in url:
                self.assertNotIn("APCA-API-KEY-ID", headers)
                self.assertNotIn("APCA-API-SECRET-KEY", headers)
            else:
                self.assertEqual(headers["APCA-API-KEY-ID"], self.config.key)
                self.assertNotIn("/orders", url)
        manifest = json.loads((output / "manifest.json").read_text())
        for descriptor in manifest["files"].values():
            self.assertEqual(enrich.sha(output / descriptor["path"]), descriptor["sha256"])
        self.assertNotIn(self.config.secret, (output / "manifest.json").read_text())

    def test_source_mutation_or_unsupported_universe_stops_before_network(self):
        (self.snapshot / "daily_raw.csv").write_text("changed")
        with patch.object(requests.Session, "get") as get, self.assertRaises(SetupError):
            enrich.download(self.config, self.snapshot, self.root / "a")
        get.assert_not_called()
        self.manifest["coverage"] = {"AAPL": {"first_session": "2016-01-04", "last_session": "2026-10-09"}}
        self.save_manifest()
        with patch.object(requests.Session, "get") as get, self.assertRaises(SetupError):
            enrich.download(self.config, self.snapshot, self.root / "b")
        get.assert_not_called()

    def test_error_body_not_persisted_and_failed_receipt_retained(self):
        output = self.root / "failed"
        with patch.object(requests.Session, "get", return_value=response({"message": self.config.secret}, 403)):
            with self.assertRaisesRegex(SetupError, "HTTP status 403"):
                enrich.download(self.config, self.snapshot, output)
        record = json.loads((output / "manifest.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["files"], {})
        self.assertNotIn(self.config.secret, json.dumps(record))

    def test_pagination_loop_and_output_overwrite_are_rejected(self):
        output = self.root / "loop"
        with patch.object(requests.Session, "get", return_value=response({"corporate_actions": {}, "next_page_token": "same"})):
            with self.assertRaisesRegex(SetupError, "repeated/invalid"):
                enrich.download(self.config, self.snapshot, output, False)
        with patch.object(requests.Session, "get") as get, self.assertRaises(FileExistsError):
            enrich.download(self.config, self.snapshot, output, False)
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
