"""Liquidity incentive program snapshots: pagination, centi-cent rewards, per-series summary, S3 keys."""
import gzip
import json
from datetime import datetime, timezone

from data_pipeline import lip_programs as lp


def _prog(i, ticker, reward_cc, start="2026-10-28T00:00:00Z", end="2026-10-30T00:00:00Z", target="500.00", df=5000):
    return {"id": f"p{i}", "market_id": f"m{i}", "market_ticker": ticker, "incentive_type": "liquidity",
            "incentive_description": "", "start_date": start, "end_date": end, "period_reward": reward_cc,
            "paid_out": False, "target_size_fp": target, "discount_factor_bps": df}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise Exception("NoSuchKey")
        import io
        return {"Body": io.BytesIO(self.objects[Key])}


def test_fetch_follows_the_cursor_and_asks_for_liquidity_programs():
    calls = []
    pages = {None: {"incentive_programs": [_prog(1, "KXBTCD-26OCT2817-T80000", 1)], "next_cursor": "c2"},
             "c2": {"incentive_programs": [_prog(2, "KXBTCD-26OCT2817-T81000", 1)], "next_cursor": ""}}

    def get(path, params):
        calls.append((path, dict(params)))
        return pages[params.get("cursor")]

    out = lp.fetch_programs("active", get=get)
    assert [p["id"] for p in out] == ["p1", "p2"]
    assert calls[0] == ("/incentive_programs", {"status": "active", "type": "liquidity", "limit": lp.PAGE})
    assert calls[1][1]["cursor"] == "c2"


def test_reward_is_centi_cents_spread_over_the_period():
    p = _prog(1, "KXBTC15M-26OCT281200-00", 20_000_000)   # $2,000 over 2 days
    assert lp.reward_usd(p) == 2000.0
    assert lp.reward_per_day_usd(p) == 1000.0


def test_summary_groups_by_series_largest_pool_first():
    progs = [_prog(1, "KXBTCD-26OCT2817-T80000", 10_000_000), _prog(2, "KXBTCD-26OCT2817-T81000", 30_000_000),
             _prog(3, "KXHIGHNY-26OCT28-B60", 100_000_000, target="250.00")]
    rows = lp.summarize(progs)
    assert [r["series"] for r in rows] == ["KXHIGHNY", "KXBTCD"]
    btc = rows[1]
    assert btc["markets"] == 2 and btc["usd_per_day"] == 2000.0 and btc["top_usd_per_day"] == 1500.0
    assert btc["target_sizes"] == [500.0] and btc["discount_bps"] == [5000]


def test_snapshot_writes_a_dated_copy_and_latest():
    s3 = FakeS3()
    now = datetime(2026, 10, 25, 9, 7, tzinfo=timezone.utc)

    def get(path, params):
        return {"incentive_programs": [_prog(1, "KXBTCD-26OCT2817-T80000", 1)] if params["status"] == "active" else []}

    lp.snapshot(s3=s3, get=get, now=now)
    assert set(s3.objects) == {"ticks/v1/lip_programs/date=2026-10-25/0907.json.gz", lp.LATEST_KEY}
    doc = json.loads(gzip.decompress(s3.objects[lp.LATEST_KEY]))
    assert len(doc["programs"]["active"]) == 1 and doc["programs"]["upcoming"] == []
    assert lp.load_latest(s3=s3)["fetched_at"] == now.isoformat()


def test_load_latest_is_none_before_the_first_snapshot():
    assert lp.load_latest(s3=FakeS3()) is None
