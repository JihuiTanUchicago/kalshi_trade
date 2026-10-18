import pymysql
import pytest

from data_pipeline import forward_collector


class _RaiseCursor:
    """A cursor whose execute always raises a given OperationalError errno."""

    def __init__(self, errno: int):
        self.errno = errno

    def execute(self, *a, **k):
        raise pymysql.err.OperationalError(self.errno, "boom")


def test_upsert_catalog_skips_on_lock_wait_timeout():
    # A stuck txn elsewhere -> lock wait timeout (1205). Catalog is skipped, feed survives.
    assert forward_collector.upsert_catalog(_RaiseCursor(1205), [{"ticker": "X"}]) is False


def test_upsert_catalog_skips_on_deadlock():
    assert forward_collector.upsert_catalog(_RaiseCursor(1213), [{"ticker": "X"}]) is False


def test_upsert_catalog_reraises_connection_loss():
    # A dropped connection (2013) must NOT be swallowed — the caller reconnects.
    with pytest.raises(pymysql.err.OperationalError):
        forward_collector.upsert_catalog(_RaiseCursor(2013), [{"ticker": "X"}])
