"""HTTP-fixture checks for the read-only BTC feed and CLI."""
from base64 import b64encode
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import json
import os
import unittest

from quant_agent.cli import main
from quant_agent.common import GateError
from quant_agent.configuration import load_environment
from quant_agent.market_data import MarketDataReader


NOW = datetime(2026, 10, 13, 5, 0, 0, tzinfo=timezone.utc)
PASSWORD = "fixture-private-canary"
AUTH = "Basic " + b64encode(f"fixture-user:{PASSWORD}".encode()).decode()


def quote(identity=1, age=20, ticker="KXBTC15M-26OCT131300-00", **changes):
    observed = NOW - timedelta(seconds=age)
    result = {"id": identity, "snapshot_time_utc": observed.strftime("%Y-%m-%d %H:%M:%S"),
              "market_ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0],
              "yes_bid_dollars": "0.5400", "yes_ask_dollars": "0.5500",
              "no_bid_dollars": "0.4500", "no_ask_dollars": "0.4600",
              "yes_bid_size_fp": "100.00", "yes_ask_size_fp": "90.00",
              "volume_fp": "300.00", "open_interest_fp": "250.00", "status": "active",
              "raw_json": json.dumps({"market_ticker": ticker, "ts_ms": int(observed.timestamp() * 1000)})}
    return result | changes


def tick(identity=1, age=20, **changes):
    result = {"id": identity, "snapshot_time_utc": (NOW - timedelta(seconds=age)).isoformat(),
              "product_id": "BTC-USD", "price": "60000.1200", "bid": "60000.1000",
              "ask": "60000.2000", "volume_24h": "1200.123456", "status": "ok",
              "raw_json": json.dumps({"time": (NOW - timedelta(minutes=30)).isoformat()})}
    return result | changes


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        name = params.get("name", [""])[0]
        self.server.requests.append({"path": parsed.path, "method": self.command, "params": params,
                                     "authorization": self.headers.get("Authorization")})
        code = self.server.errors.get(name, 200)
        if self.headers.get("Authorization") != AUTH:
            code = 401
        self.send_response(code)
        if 300 <= code < 400:
            self.send_header("Location", self.server.base_url + "/credential-leak")
        self.end_headers()
        if code != 200:
            self.wfile.write(json.dumps({"error": PASSWORD}).encode())
            return
        if name in self.server.overrides:
            payload = self.server.overrides[name]
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        else:
            start = datetime.fromisoformat(params["start"][0]).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(params["end"][0]).replace(tzinfo=timezone.utc)
            rows = []
            for row in self.server.rows[name]:
                try:
                    observed = datetime.fromisoformat(row["snapshot_time_utc"])
                    if observed.tzinfo is None:
                        observed = observed.replace(tzinfo=timezone.utc)
                    if not start <= observed <= end:
                        continue
                except (KeyError, ValueError, TypeError):
                    pass
                rows.append(row)
            rows.sort(key=lambda row: row["id"])
            offset = int(params["offset"][0])
            batch = rows[offset:offset + self.server.page_size]
            body = json.dumps({"rows": batch, "done": offset + len(batch) >= len(rows),
                               "next_offset": offset + len(batch)}).encode()
        self.wfile.write(body)


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.server.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.server.requests = []
        self.server.rows = {"forward_quotes": [quote()], "coinbase_ticks": [tick()]}
        self.server.errors = {}
        self.server.overrides = {}
        self.server.page_size = 2
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.environment = patch.dict(os.environ, {"DASHBOARD_USER": "fixture-user", "DASHBOARD_PASSWORD": PASSWORD})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.clock = patch("quant_agent.market_data.utcnow", return_value=NOW.isoformat())
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.config = {"base_url": self.server.base_url}
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(self.config))
        self.reader = MarketDataReader(self.config)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_snapshot_preserves_decimals_and_separates_last_trade_time(self):
        result = self.reader.snapshot()
        kalshi = result["feeds"]["kalshi"]["updates"][0]
        coinbase = result["feeds"]["coinbase"]["updates"][0]
        self.assertEqual(kalshi["yes_bid_dollars"], "0.5400")
        self.assertEqual(coinbase["price"], "60000.1200")
        self.assertEqual(coinbase["volume_24h"], "1200.123456")
        self.assertEqual(kalshi["source_time_utc"], (NOW - timedelta(seconds=20)).isoformat())
        self.assertEqual(coinbase["last_trade_time_utc"], (NOW - timedelta(minutes=30)).isoformat())
        self.assertEqual(coinbase["health"]["status"], "ok")
        self.assertEqual(coinbase["health"]["freshness_basis"], "collection")
        self.assertNotIn("raw_json", kalshi)
        self.assertNotIn(PASSWORD, json.dumps(result))
        self.assertNotIn(AUTH, json.dumps(result))
        self.assertEqual({request["method"] for request in self.server.requests}, {"GET"})
        self.assertEqual({request["path"] for request in self.server.requests}, {"/api/table"})

    def test_pagination_fixed_window_deduplication_and_chronological_updates(self):
        self.server.rows["forward_quotes"] = [quote(1, 240), quote(2, 130), quote(2, 130), quote(3, 70), quote(4, 10)]
        self.server.rows["coinbase_ticks"] = [tick(1, 90), tick(2, 30)]
        events = list(self.reader.iter_updates(iterations=1))
        rows = [event for event in events if event["kind"] == "market_data"]
        self.assertEqual([row["update_id"] for row in rows], ["kalshi:2", "coinbase:1", "kalshi:3", "coinbase:2", "kalshi:4"])
        self.assertEqual([int(request["params"]["offset"][0]) for request in self.server.requests
                          if request["params"]["name"] == ["forward_quotes"]], [0, 2])
        self.assertEqual({request["params"]["start"][0] for request in self.server.requests}, {"2026-10-13 04:57:00"})
        self.assertEqual({request["params"]["end"][0] for request in self.server.requests}, {"2026-10-13 05:00:00"})

    def test_snapshot_contract_rotation_keeps_only_the_current_batch(self):
        old = quote(1, 40)
        new = quote(2, 20, ticker="KXBTC15M-26OCT131315-00")
        self.server.rows["forward_quotes"] = [old, new]
        result = self.reader.snapshot()
        self.assertEqual([row["market_ticker"] for row in result["feeds"]["kalshi"]["updates"]], [new["market_ticker"]])
        events = list(self.reader.iter_updates(iterations=1))
        self.assertEqual([event["market_ticker"] for event in events if event.get("source") == "kalshi"
                          and event["kind"] == "market_data"], [old["market_ticker"], new["market_ticker"]])

    def test_cached_quote_does_not_become_fresh_with_a_new_collection_row(self):
        self.server.rows["forward_quotes"] = [quote(raw_json={"ts_ms": int((NOW - timedelta(seconds=120)).timestamp() * 1000)})]
        result = self.reader.snapshot()
        health = result["feeds"]["kalshi"]["health"]
        self.assertEqual((health["status"], health["reason"]), ("stale", "source_age"))
        self.assertEqual(health["collection_age_seconds"], 20)
        self.assertEqual(health["source_age_seconds"], 120)
        self.assertEqual(result["feeds"]["coinbase"]["health"]["status"], "ok")

    def test_rest_without_source_timestamp_exposes_collection_freshness_only(self):
        self.server.rows["forward_quotes"] = [quote(raw_json={"ticker": quote()["market_ticker"]}, volume_fp="0.00")]
        row = self.reader.snapshot()["feeds"]["kalshi"]["updates"][0]
        self.assertIsNone(row["source_time_utc"])
        self.assertIsNone(row["health"]["source_age_seconds"])
        self.assertEqual(row["health"]["freshness_basis"], "collection")
        self.assertEqual(row["health"]["status"], "ok")

    def test_legacy_seconds_and_aware_iso_source_timestamps(self):
        observed = NOW - timedelta(seconds=20)
        for raw in ({"ts": int(observed.timestamp())}, {"time": observed.isoformat()}):
            with self.subTest(raw=raw):
                self.server.rows["forward_quotes"] = [quote(raw_json=raw)]
                row = self.reader.snapshot()["feeds"]["kalshi"]["updates"][0]
                self.assertEqual(row["source_time_utc"], observed.isoformat())

    def test_invalid_numbers_and_timestamps_fail_only_the_affected_feed(self):
        cases = [{"yes_bid_dollars": "NaN"}, {"yes_ask_dollars": "1.0001"},
                 {"yes_bid_size_fp": "-1"}, {"yes_bid_dollars": True},
                 {"yes_bid_dollars": "0.5600"}, {"raw_json": "not-json"}, {"raw_json": []},
                 {"raw_json": {"time": "not-a-time"}}, {"raw_json": {"time": "2026-10-13 04:59:00"}},
                 {"raw_json": {"ts": int((NOW + timedelta(seconds=10)).timestamp())}},
                 {"id": True}, {"snapshot_time_utc": "invalid"}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.server.rows["forward_quotes"] = [quote(**changes)]
                result = self.reader.snapshot()
                self.assertEqual(result["feeds"]["kalshi"]["health"]["reason"], "invalid_data")
                self.assertEqual(result["feeds"]["coinbase"]["health"]["status"], "ok")

    def test_unavailable_stale_and_missing_quote_are_explicit(self):
        for rows, expected in (([], ("unavailable", "no_rows")),
                               ([quote(age=75)], ("stale", "collection_age")),
                               ([quote(yes_bid_dollars=None)], ("unavailable", "missing_quote")),
                               ([quote(status="closed")], ("unavailable", "collector_status"))):
            with self.subTest(expected=expected):
                self.server.rows["forward_quotes"] = rows
                health = self.reader.snapshot()["feeds"]["kalshi"]["health"]
                self.assertEqual((health["status"], health["reason"]), expected)

    def test_new_collector_error_does_not_resurrect_an_older_quote(self):
        self.server.rows["forward_quotes"] = [quote(1, 40), quote(2, 20, ticker="N/A", status="N/A_MARKETS_API_ERROR")]
        self.server.rows["coinbase_ticks"] = [tick(status="api_error", price=None, bid=None, ask=None,
                                                   raw_json={"error": PASSWORD})]
        result = self.reader.snapshot()
        self.assertEqual(result["feeds"]["kalshi"]["updates"][0]["market_ticker"], "N/A")
        self.assertTrue(all(feed["health"]["reason"] == "collector_status" for feed in result["feeds"].values()))
        self.assertNotIn(PASSWORD, json.dumps(result))

    def test_out_of_scope_products_and_series_are_filtered(self):
        self.server.rows["forward_quotes"] = [quote(ticker="OTHER-MARKET")]
        self.server.rows["coinbase_ticks"] = [tick(product_id="ETH-USD")]
        self.assertTrue(all(feed["health"]["reason"] == "no_rows" for feed in self.reader.snapshot()["feeds"].values()))

    def test_transient_failure_recovers_without_repeating_other_feed_rows(self):
        self.server.errors["forward_quotes"] = 503
        def recover(_):
            self.server.errors.clear()
        with patch("quant_agent.market_data.time.sleep", side_effect=recover) as sleep:
            events = list(self.reader.iter_updates(iterations=2))
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual([event["update_id"] for event in events if event["kind"] == "market_data"], ["coinbase:1", "kalshi:1"])
        kalshi_health = [event["health"]["status"] for event in events
                        if event["kind"] == "feed_health" and event["source"] == "kalshi"]
        self.assertEqual(kalshi_health, ["unavailable", "ok"])

    def test_rate_limit_and_transport_failures_are_redacted(self):
        self.server.errors["forward_quotes"] = 429
        result = self.reader.snapshot()
        self.assertEqual(result["feeds"]["kalshi"]["health"]["reason"], "http_429")
        self.assertNotIn(PASSWORD, json.dumps(result))
        with patch.object(self.reader._opener, "open", side_effect=TimeoutError(PASSWORD)):
            result = self.reader.snapshot()
        self.assertTrue(all(feed["health"]["reason"] == "transport_error" for feed in result["feeds"].values()))
        self.assertNotIn(PASSWORD, json.dumps(result))

    def test_auth_and_configuration_http_failures_stop_without_body_or_redirect(self):
        for code in (401, 403, 404, 302):
            with self.subTest(code=code):
                self.server.errors["forward_quotes"] = code
                self.server.requests.clear()
                with self.assertRaises(GateError) as error:
                    self.reader.snapshot()
                self.assertNotIn(PASSWORD, str(error.exception))
                self.assertEqual(len(self.server.requests), 1)
                self.assertEqual(self.server.requests[0]["path"], "/api/table")

    def test_malformed_or_stalled_pages_do_not_loop_or_hide_the_other_feed(self):
        for payload in (b"not-json", {"rows": [], "done": False, "next_offset": 0},
                        {"rows": [quote()], "done": False, "next_offset": 0},
                        {"rows": [], "done": "true"}, {"rows": [None], "done": True}):
            with self.subTest(payload=payload):
                self.server.overrides["forward_quotes"] = payload
                result = self.reader.snapshot()
                self.assertEqual(result["feeds"]["kalshi"]["health"]["reason"], "invalid_data")
                self.assertEqual(result["feeds"]["coinbase"]["health"]["status"], "ok")

    def test_response_and_window_limits_fail_explicitly(self):
        self.server.overrides["forward_quotes"] = b" " * 1025
        with patch("quant_agent.market_data.MAX_RESPONSE_BYTES", 1024):
            self.assertEqual(self.reader.snapshot()["feeds"]["kalshi"]["health"]["reason"], "invalid_data")
        self.server.overrides.clear()
        self.server.rows["forward_quotes"] = [quote(1, 40), quote(2, 20)]
        with patch("quant_agent.market_data.MAX_ROWS", 1):
            self.assertEqual(self.reader.snapshot()["feeds"]["kalshi"]["health"]["reason"], "invalid_data")

    def test_health_can_become_stale_without_reemitting_an_existing_row(self):
        advanced = NOW
        def advance(_):
            nonlocal advanced
            advanced += timedelta(seconds=80)
        with patch("quant_agent.market_data.utcnow", side_effect=lambda: advanced.isoformat()), \
                patch("quant_agent.market_data.time.sleep", side_effect=advance):
            events = list(self.reader.iter_updates(iterations=2))
        self.assertEqual(len([event for event in events if event["kind"] == "market_data"]), 2)
        self.assertEqual([event["health"]["status"] for event in events if event["kind"] == "feed_health"
                          and event["source"] == "kalshi"], ["ok", "stale"])

    def test_credentials_are_required_and_unsafe_urls_are_rejected(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": ""}):
            with self.assertRaises(GateError):
                MarketDataReader(self.config)
        for config in ({"base_url": "http://example.com"}, {"base_url": f"https://user:{PASSWORD}@example.com"},
                       {"base_url": "https://example.com?token=value"}, self.config | {"password": PASSWORD}):
            with self.subTest(config=config):
                with self.assertRaises(GateError) as error:
                    MarketDataReader(config)
                self.assertNotIn(PASSWORD, str(error.exception))
        self.assertEqual(self.server.requests, [])

    def test_literal_env_loading_is_scoped_and_atomic(self):
        path = self.root / "private.env"
        literal = "literal-${OPTION}-$(command)-`command`"
        path.write_text(f"DASHBOARD_USER=fixture-user\nDASHBOARD_PASSWORD='{literal}'\nUNRELATED_OPTION=changed\n")
        with patch.dict(os.environ, {"UNRELATED_OPTION": "original"}):
            self.assertTrue(load_environment(path, ["DASHBOARD_USER", "DASHBOARD_PASSWORD"]))
            self.assertEqual(os.environ["DASHBOARD_PASSWORD"], literal)
            self.assertEqual(os.environ["UNRELATED_OPTION"], "original")
            before = {name: os.environ[name] for name in ("DASHBOARD_USER", "DASHBOARD_PASSWORD")}
            path.write_text("DASHBOARD_USER=changed\nDASHBOARD_PASSWORD=one\nDASHBOARD_PASSWORD=two\n")
            with self.assertRaises(GateError):
                load_environment(path, ["DASHBOARD_USER", "DASHBOARD_PASSWORD"])
            self.assertEqual({name: os.environ[name] for name in before}, before)

    def test_cli_snapshot_bypasses_research_store(self):
        output = StringIO()
        with redirect_stdout(output), patch("quant_agent.cli.Store") as store, patch("quant_agent.cli.HTTPModel") as model:
            status = main(["--store", str(self.root / "unused-store"), "market-data", "snapshot",
                           "--config", str(self.config_path)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["feeds"]["coinbase"]["health"]["status"], "ok")
        store.assert_not_called()
        model.assert_not_called()
        self.assertFalse((self.root / "unused-store").exists())

    def test_cli_watch_loads_only_dashboard_credentials_and_outputs_json_lines(self):
        env_file = self.root / "private.env"
        env_file.write_text(f"DASHBOARD_USER=fixture-user\nDASHBOARD_PASSWORD={PASSWORD}\nXAI_API_KEY=unrelated\n")
        output = StringIO()
        with redirect_stdout(output), patch("quant_agent.cli.Store") as store, \
                patch("quant_agent.market_data.time.sleep") as sleep, patch.dict(os.environ, {"XAI_API_KEY": "original"}):
            status = main(["market-data", "watch", "--config", str(self.config_path),
                           "--data-env", str(env_file), "--iterations", "1"])
            self.assertEqual(os.environ["XAI_API_KEY"], "original")
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(status, 0)
        self.assertEqual(len([event for event in events if event["kind"] == "market_data"]), 2)
        self.assertNotIn(PASSWORD, output.getvalue())
        store.assert_not_called()
        sleep.assert_not_called()

    def test_cli_watch_interrupt_and_terminal_error_are_json_lines(self):
        args = ["market-data", "watch", "--config", str(self.config_path), "--iterations", "1"]
        output = StringIO()
        with redirect_stdout(output), patch.object(MarketDataReader, "iter_updates", side_effect=KeyboardInterrupt):
            self.assertEqual(main(args), 130)
        self.assertEqual(json.loads(output.getvalue()), {"kind": "stopped", "reason": "interrupted"})
        self.server.errors["forward_quotes"] = 403
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(args), 2)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked_or_failed")
        self.assertNotIn(PASSWORD, output.getvalue())

    def test_unhealthy_snapshot_exit_status_and_invalid_iterations(self):
        self.server.rows["forward_quotes"] = []
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["market-data", "snapshot", "--config", str(self.config_path)]), 2)
        self.server.requests.clear()
        with self.assertRaises(GateError):
            list(self.reader.iter_updates(iterations=-1))
        self.assertEqual(self.server.requests, [])


if __name__ == "__main__":
    unittest.main()
