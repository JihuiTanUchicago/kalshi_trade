"""Offline boundary checks; no real credentials, market data or network calls."""

import contextlib
import csv
import hashlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

import fetch_alpaca as fetch


NOW = datetime(2026, 10, 10, 14, tzinfo=timezone.utc)
KEY, SECRET = "offline-fixture-key", "offline-fixture-secret-${LITERAL}"


def bar(day):
    return {"t": day + "T04:00:00Z", "o": 100.0, "h": 102.0,
            "l": 99.0, "c": 101.0, "v": 1000, "n": 10, "vw": 100.5}


class AlpacaSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / "fixture.env"
        self.write_env()

    def write_env(self, endpoint=fetch.DATA_ENDPOINT, key=KEY, secret=SECRET):
        self.env.write_text(f"ALPACA_DATA_ENDPOINT={endpoint}\nAPCA_API_KEY_ID={key}\n"
                            f"APCA_API_SECRET_KEY={secret}\n", encoding="utf-8")

    def test_private_file_preserves_literal_credentials_without_authentication(self):
        config = fetch.load_config(self.env)
        self.assertEqual(config.secret, SECRET)
        output = io.StringIO()
        with patch.object(fetch, "StockHistoricalDataClient") as client, contextlib.redirect_stdout(output):
            code = fetch.main(["--env-file", str(self.env), "--check-config"])
        self.assertEqual(code, 0)
        client.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["authenticated"])
        self.assertNotIn(KEY, output.getvalue())
        self.assertNotIn(SECRET, output.getvalue())

    def test_missing_keys_and_wrong_destinations_stop_before_client_creation(self):
        cases = [(fetch.DATA_ENDPOINT, "", ""),
                 ("https://paper-api.alpaca.markets", KEY, SECRET),
                 ("http://data.alpaca.markets", KEY, SECRET),
                 ("https://data.alpaca.markets.untrusted.invalid", KEY, SECRET)]
        for endpoint, key, secret in cases:
            with self.subTest(endpoint=endpoint):
                self.write_env(endpoint, key, secret)
                output = io.StringIO()
                with patch.object(fetch, "StockHistoricalDataClient") as client, contextlib.redirect_stdout(output):
                    code = fetch.main(["--env-file", str(self.env)])
                self.assertEqual(code, 2)
                client.assert_not_called()
                self.assertNotIn(KEY, output.getvalue())
                self.assertNotIn(SECRET, output.getvalue())

    def test_actual_sdk_pagination_headers_timeout_and_snapshot_provenance(self):
        pages = [{"bars": {"SPY": [bar("2026-10-08")]}, "next_page_token": "second-page"},
                 {"bars": {"QQQ": [bar("2026-10-09")]}, "next_page_token": None}]
        calls = []

        def transport(method, url, **kwargs):
            calls.append((method, url, deepcopy(kwargs)))
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(pages.pop(0)).encode("utf-8")
            return response

        target = self.root / "snapshot"
        with patch("requests.Session.request", side_effect=transport):
            receipt = fetch.download(fetch.load_config(self.env), ["SPY", "QQQ"],
                                     date(2016, 1, 1), NOW, target)
        self.assertEqual(len(calls), 2)
        for method, url, kwargs in calls:
            self.assertEqual(method, "GET")
            self.assertEqual(url, fetch.DATA_ENDPOINT + "/v2/stocks/bars")
            self.assertEqual(kwargs["headers"]["APCA-API-KEY-ID"], KEY)
            self.assertEqual(kwargs["headers"]["APCA-API-SECRET-KEY"], SECRET)
            self.assertEqual(kwargs["timeout"], 30)
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(kwargs["params"]["feed"], "sip")
            self.assertEqual(kwargs["params"]["adjustment"], "raw")
        self.assertEqual(calls[1][2]["params"]["page_token"], "second-page")
        with (target / "daily_raw.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([(row["symbol"], row["session"]) for row in rows],
                         [("QQQ", "2026-10-09"), ("SPY", "2026-10-08")])
        manifest = json.loads((target / "manifest.json").read_text())
        self.assertEqual(manifest["quality"], "proxy")
        self.assertFalse(manifest["agent_import_ready"])
        for name, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), digest)
        for path in target.iterdir():
            self.assertNotIn(KEY, path.read_text())
            self.assertNotIn(SECRET, path.read_text())
        output = io.StringIO()
        with patch.object(fetch, "StockHistoricalDataClient") as client, contextlib.redirect_stdout(output):
            code = fetch.main(["--env-file", str(self.env), "--output", str(target)])
        self.assertEqual(code, 2)
        client.assert_not_called()
        self.assertEqual(receipt["coverage"]["QQQ"]["rows"], 1)

    def test_cutoff_excludes_current_day_even_near_new_york_midnight(self):
        for now in (NOW, datetime(2026, 10, 10, 4, 5, tzinfo=timezone.utc)):
            beginning, end = fetch.request_window(date(2016, 1, 1), now)
            self.assertLess(end.astimezone(fetch.NY).date(), now.astimezone(fetch.NY).date())
            self.assertLessEqual(end, now - timedelta(minutes=20))
            with self.assertRaises(fetch.SetupError):
                fetch.normalize({"SPY": [bar("2026-10-10")]}, ["SPY"], beginning, end)

    def test_invalid_ohlcv_and_duplicate_sessions_are_rejected(self):
        beginning, end = fetch.request_window(date(2016, 1, 1), NOW)
        bad_sets = [[bar("2026-10-09"), bar("2026-10-09")],
                    [dict(bar("2026-10-09"), c=float("nan"))],
                    [dict(bar("2026-10-09"), v=-1)],
                    [dict(bar("2026-10-09"), h=90)]]
        for bars in bad_sets:
            with self.assertRaises(fetch.SetupError):
                fetch.normalize({"SPY": bars}, ["SPY"], beginning, end)

    def test_server_error_cannot_echo_credentials_into_console(self):
        response = requests.Response()
        response.status_code = 401
        error = fetch.APIError("server-echo " + KEY + " " + SECRET,
                               requests.HTTPError(response=response))
        output = io.StringIO()
        with patch.object(fetch, "download", side_effect=error), contextlib.redirect_stdout(output):
            code = fetch.main(["--env-file", str(self.env)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["http_status"], 401)
        self.assertNotIn(KEY, output.getvalue())
        self.assertNotIn(SECRET, output.getvalue())


if __name__ == "__main__":
    unittest.main()
