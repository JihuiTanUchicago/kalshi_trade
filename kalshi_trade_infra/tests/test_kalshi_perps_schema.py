"""Native proposal kinds fit new and existing full-schema installations."""
import re

import pytest

from app import kalshi_perps_trading, schema


class Cursor:
    def __init__(self, row):
        self.row, self.calls = row, []

    def execute(self, *args):
        self.calls.append(args)

    def fetchone(self):
        return self.row


@pytest.mark.parametrize("width", [12, 16, 17, 31, 32, 48, 128])
def test_existing_proposal_kind_is_widened_only_when_needed(width):
    cur = Cursor({"data_type": "varchar", "max_length": width, "nullable": "NO"})
    schema._ensure_proposal_kind_width(cur)
    assert cur.calls[0][1] == ("app_proposals", "kind")
    alterations = [call[0] for call in cur.calls if call[0].startswith("ALTER")]
    assert alterations == (["ALTER TABLE app_proposals MODIFY COLUMN kind VARCHAR(32) NOT NULL"] if width < 32 else [])


@pytest.mark.parametrize("row", [None, {"data_type": "enum", "max_length": 12, "nullable": "NO"},
    {"data_type": "varchar", "max_length": None, "nullable": "NO"},
    {"data_type": "varchar", "max_length": 12, "nullable": "YES"}])
def test_unexpected_schema_cannot_be_silently_replaced(row):
    cur = Cursor(row)
    with pytest.raises(RuntimeError, match="requires review"):
        schema._ensure_proposal_kind_width(cur)
    assert len(cur.calls) == 1


def test_new_schema_admits_the_actual_native_proposal_name():
    ddl = next(value for value in schema.DDL if "CREATE TABLE IF NOT EXISTS app_proposals" in value)
    width = int(re.search(r"kind VARCHAR\((\d+)\)", ddl)[1])
    assert width >= len(kalshi_perps_trading.PROPOSAL_KIND)
