"""Collector tests use synthetic log text and isolated directories only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import collect


class CollectorTests(unittest.TestCase):
    def test_omits_all_raw_logs_and_keeps_only_named_marker_json(self):
        raw = 'step PRIVATE RAW LOG\nstep TAU_MERIDIAN_INVENTORY={"status":"ready","read_only":true}\nstep TAU_FUNDS_RESULTS={"old":true}\nstep END PRIVATE\n'
        result = collect.records(raw)
        self.assertEqual(result, [{'type': 'INVENTORY', 'receipt': {'status': 'ready', 'read_only': True}}])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_wrong_operation_head_is_rejected_before_logs_are_requested(self):
        with patch.object(collect, 'command', return_value=json.dumps({'headSha': 'a' * 40, 'status': 'completed'})) as command:
            with self.assertRaisesRegex(RuntimeError, '^OperationHeadMismatch$'):
                collect.collect('123', 'b' * 40, Path('/never-written'))
        self.assertEqual(command.call_count, 1)

    def test_saved_file_contains_only_sanitized_records_and_metadata(self):
        meta = {'headSha': 'a' * 40, 'status': 'completed', 'conclusion': 'success', 'databaseId': 123}
        with tempfile.TemporaryDirectory() as directory, patch.object(collect, 'command', side_effect=[json.dumps(meta), 'PRIVATE\nstep TAU_MERIDIAN_RESULTS={"status":"deployed"}\n']):
            result = collect.collect('123', 'a' * 40, Path(directory))
            saved = (Path(directory) / 'DEPLOYMENT_123.json').read_text()
            self.assertNotIn('PRIVATE', saved)
            self.assertEqual(json.loads(saved), result)


if __name__ == '__main__':
    unittest.main()
