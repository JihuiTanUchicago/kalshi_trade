"""Passive market making: the filed LIP scoring rule, the quoting policy, the queue-aware replay
venue, and one end-to-end replay over a synthetic tick archive."""
from datetime import datetime, timedelta, timezone

import pytest

from trading_core.domain import BinaryTerms, Instrument, InstrumentId, InstrumentKind, Portfolio, Quote, Side
from trading_core.domain.orders import RestingOrder
from trading_core.engine.quoting import DesiredQuote, MakerConfig, QuotingLoop, maker_quotes, net_yes, reconcile
from trading_core.ports import QuotingVenue
from trading_core.pricing.depth_rewards import DepthRewardTerms, side_share, snapshot_reward

YES = InstrumentId("kalshi", "KXCRYPTOLEAD15M-26OCT251200-BTC", "yes")
NO = InstrumentId("kalshi", "KXCRYPTOLEAD15M-26OCT251200-BTC", "no")
EXP = datetime(2026, 10, 25, 16, tzinfo=timezone.utc)


def _inst(tick=0.01):
    return Instrument(YES, InstrumentKind.BINARY, tick_size=tick, series="KXCRYPTOLEAD15M", terms=BinaryTerms(expiry=EXP))


def _terms(target=1000.0, pool=20.0):
    return DepthRewardTerms(pool=pool, start=0.0, end=900.0, target_size=target)


# --- scoring rule ------------------------------------------------------------------------------

def test_touch_alone_meeting_the_target_scores_only_the_touch():
    levels = [(0.40, 1500.0), (0.39, 5000.0)]
    assert side_share(levels, {0.40: 300.0}, _terms()) == pytest.approx(300 / 1500)
    assert side_share(levels, {0.39: 300.0}, _terms()) == 0.0      # below the qualifying levels


def test_deeper_levels_are_discounted_per_tick_below_the_reference():
    # 100 at the touch < 1/5 of 1000, so the reference is 0.39 (cumulative 400 >= 200); the 0.40
    # bid sits above it (N=0), 0.39 is N=0, 0.38 is N=1 at half weight; target reached at 0.38.
    levels = [(0.40, 100.0), (0.39, 300.0), (0.38, 800.0)]
    share = side_share(levels, {0.38: 200.0}, _terms())
    assert share == pytest.approx(0.5 * 200 / (100 + 300 + 0.5 * 800))


def test_a_side_short_of_the_target_excludes_the_snapshot():
    assert side_share([(0.40, 500.0)], {0.40: 100.0}, _terms()) is None
    yes, no = [(0.40, 2000.0)], [(0.55, 400.0)]
    assert snapshot_reward(yes, no, {0.40: 1000.0}, {}, _terms()) == 0.0


def test_snapshot_pays_pool_per_second_times_mean_side_share():
    t = _terms(pool=90.0)                       # $0.10 a second over 900s
    yes, no = [(0.40, 2000.0)], [(0.55, 1000.0)]
    r = snapshot_reward(yes, no, {0.40: 500.0}, {0.55: 1000.0}, t)
    assert r == pytest.approx(0.10 * (0.25 + 1.0) / 2)


# --- quoting policy ----------------------------------------------------------------------------

def test_joins_both_sides_of_the_touch_and_respects_inventory():
    q = Quote(YES, 0.0, 0.40, 0.43, 500, 500)
    out = maker_quotes(_inst(), q, None, inventory=0.0, secs_to_close=600, cfg=MakerConfig(quote_size=100))
    assert out == [DesiredQuote(YES, 0.40, 100.0), DesiredQuote(NO, 0.57, 100.0)]
    long_ = maker_quotes(_inst(), q, None, inventory=500.0, secs_to_close=600, cfg=MakerConfig(max_inventory=500))
    assert [d.instrument for d in long_] == [NO]                      # full of YES: only sell it
    part = maker_quotes(_inst(), q, None, inventory=-450.0, secs_to_close=600, cfg=MakerConfig(max_inventory=500))
    assert part[0] == DesiredQuote(YES, 0.40, 100.0) and part[1].qty == pytest.approx(50.0)


def test_pulls_near_close_without_a_reward_or_against_the_fair_value():
    q = Quote(YES, 0.0, 0.40, 0.43, 500, 500)
    cfg = MakerConfig(pull_before_close_s=60)
    assert maker_quotes(_inst(), q, None, 0.0, 30, cfg) == []
    assert maker_quotes(_inst(), q, None, 0.0, 600, cfg, rewarded=False) == []
    assert len(maker_quotes(_inst(), q, None, 0.0, 600, MakerConfig(rewarded_only=False), rewarded=False)) == 2
    rich = maker_quotes(_inst(), q, 0.405, 0.0, 600, MakerConfig(min_edge=0.01))
    assert [d.instrument for d in rich] == [NO]                       # YES bid at .40 is too close to fair .405


def test_improves_one_tick_only_inside_a_wide_spread():
    cfg = MakerConfig(improve_min_spread_ticks=3)
    assert maker_quotes(_inst(), Quote(YES, 0, 0.40, 0.45, 1, 1), None, 0, 600, cfg)[0].price == 0.41
    assert maker_quotes(_inst(), Quote(YES, 0, 0.40, 0.42, 1, 1), None, 0, 600, cfg)[0].price == 0.40


def test_reconcile_keeps_queue_place_tops_up_and_cancels_the_rest():
    resting = [RestingOrder("a", YES, Side.BUY, 0.40, 60.0), RestingOrder("b", NO, Side.BUY, 0.56, 100.0),
               RestingOrder("c", YES, Side.BUY, 0.40, 80.0)]
    cancels, posts = reconcile([DesiredQuote(YES, 0.40, 100.0), DesiredQuote(NO, 0.57, 100.0)], resting)
    assert cancels == ["b"]                                           # c tops a up to 140 >= 100: kept
    assert posts == [DesiredQuote(NO, 0.57, 100.0)]
    cancels, posts = reconcile([DesiredQuote(YES, 0.40, 100.0)], resting[:1])
    assert cancels == [] and posts == [DesiredQuote(YES, 0.40, 40.0)]


def test_net_yes_nets_no_against_yes():
    pf = Portfolio()
    pf.position(YES).qty = 300.0
    pf.position(NO).qty = 120.0
    assert net_yes(pf.positions, YES) == 180.0


# --- queue-aware replay venue ------------------------------------------------------------------

def _venue():
    from app.adapters.sim.queue_replay import QueueReplayVenue
    inst = _inst()
    v = QueueReplayVenue(instruments={YES: inst, NO: inst.complement()})
    v.reset_book(YES.symbol)
    v.set_level(YES.symbol, "yes", 0.40, 500.0)
    v.set_level(YES.symbol, "no", 0.57, 300.0)
    return v


def test_replay_venue_is_a_quoting_venue_and_rejects_crossing_posts():
    v = _venue()
    assert isinstance(v, QuotingVenue)
    v.post(YES, Side.BUY, 0.43, 10, "x")                              # 0.43 + 0.57 = 1: would cross
    assert v.open_orders() == []


def test_prints_eat_the_queue_ahead_before_filling_us():
    v = _venue()
    v.post(YES, Side.BUY, 0.40, 100, "x")                             # behind 500
    v.on_trade(1_000, YES.symbol, "no", 0.40, 450)                   # taker sells YES into the bids
    assert v.take_fills() == []
    v.on_trade(2_000, YES.symbol, "no", 0.40, 80)
    fills = v.take_fills()
    assert [(f.instrument, f.qty, f.price) for f in fills] == [(YES, 30.0, 0.40)]
    assert v.open_orders()[0].qty == pytest.approx(70.0)
    v.on_trade(3_000, YES.symbol, "no", 0.39, 5)                      # through our price: all of us
    assert v.take_fills()[0].qty == pytest.approx(70.0) and v.open_orders() == []


def test_cancels_move_us_up_pro_rata_but_a_traded_delta_is_not_counted_twice():
    v = _venue()
    v.post(YES, Side.BUY, 0.40, 100, "x")
    v.on_delta(10_000_000_000, YES.symbol, "yes", 0.40, -250.0)       # no print near it: a cancel
    assert v._orders["r1"].ahead == pytest.approx(250.0)
    v.set_trade_index({(YES.symbol, "yes", 0.40): [20_000_000_100]})
    v.on_delta(20_000_000_000, YES.symbol, "yes", 0.40, -100.0)       # lands 100ns before its print
    v.on_trade(20_000_000_100, YES.symbol, "no", 0.40, 100)
    assert v._orders["r1"].ahead == pytest.approx(150.0)              # moved once, by the print


def test_no_side_orders_fill_on_yes_buyers():
    v = _venue()
    v.post(NO, Side.BUY, 0.57, 50, "y")                               # behind 300 NO bids = YES offer at .43
    v.on_trade(1_000, YES.symbol, "yes", 0.43, 330)                   # taker buys YES at .43
    f = v.take_fills()
    assert [(x.instrument, x.qty, x.price) for x in f] == [(NO, 30.0, 0.57)]


def test_quoting_loop_books_fills_and_requotes():
    v = _venue()
    inst = _inst()
    instruments = {YES: inst, NO: inst.complement()}
    loop = QuotingLoop(v, instruments, MakerConfig(quote_size=100, rewarded_only=False))
    q = {YES: Quote(YES, 0.0, 0.40, 0.43, 500, 300)}
    step = loop.step(0.0, q, secs_to_close={YES: 600})
    assert sorted((p.instrument.outcome, p.price) for p in step.posts) == [("no", 0.57), ("yes", 0.40)]
    v.on_trade(1_000, YES.symbol, "no", 0.39, 10)                     # sweep through our YES bid
    step = loop.step(1.0, q, secs_to_close={YES: 599})
    assert step.fills and loop.book.positions[YES].qty == 100.0
    assert [p.instrument for p in step.posts] == [YES]                # YES bid re-posted, NO bid kept
    assert loop.step(2.0, q, secs_to_close={YES: 30}).cancels         # pulled near close


# --- end to end over a synthetic archive -------------------------------------------------------

class _Store:
    """TickStore stand-in: three tables for one hour, as pyarrow tables."""

    def __init__(self, tables):
        self.tables = tables

    def read(self, table, start, end, tickers=None, columns=None, pad_hours_before=0):
        return self.tables.get(table)


def test_replay_scores_rewards_and_pnl():
    pa = pytest.importorskip("pyarrow")
    from app.adapters.sim.maker_replay import MakerReplay
    h = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    t0 = int(h.timestamp())
    tk = YES.symbol
    ns = 1_000_000_000
    book = pa.table({"rt": [t0 * ns, t0 * ns, t0 * ns], "ticker": [tk] * 3, "kind": [3, 3, 3],
                     "side": [None, "yes", "no"], "price": [None, 0.40, 0.57], "qty": [None, 1500.0, 1200.0]})
    trades = pa.table({"rt": [(t0 + 100) * ns], "ticker": [tk], "yes_price": [0.39], "count": [10.0],
                       "taker_side": ["no"]})
    markets = pa.table({"ticker": [tk], "close_ts": [t0 + 900]})
    prog = {"id": "p1", "market_ticker": tk, "start_date": "2026-10-25T12:00:00Z", "end_date": "2026-10-25T12:15:00Z",
            "period_reward": 200_000, "target_size_fp": "1000.00", "discount_factor_bps": 5000}
    rep = MakerReplay(["KXCRYPTOLEAD15M"], MakerConfig(quote_size=500, max_inventory=500, pull_before_close_s=60),
                      [prog]).run(_Store({"kalshi_book": book, "kalshi_trades": trades, "kalshi_markets": markets}),
                                  h, h.replace(minute=20))
    # Quoting 500 on each side from second 1 to 60s before close (840 snapshots): YES share
    # 500/2000, NO 500/1700. The 10-lot sweep at .39 fills all 500 YES at .40, after which the YES
    # side is full (max inventory) and only the NO bid rests: share 0 on YES from then on.
    assert rep["fills"] == 1 and rep["filled_qty"] == 500.0
    assert 0 < rep["rewards"] < 20.0
    assert rep["trading_pnl"] == pytest.approx(500 * (0.415 - 0.40))   # marked at the last mid


def test_a_contract_is_benched_once_fills_cost_more_than_its_rewards():
    v = _venue()
    inst = _inst()
    loop = QuotingLoop(v, {YES: inst, NO: inst.complement()},
                       MakerConfig(quote_size=100, rewarded_only=False, contract_loss_limit=2.0))
    loop.step(0.0, {YES: Quote(YES, 0.0, 0.40, 0.43, 500, 300)}, secs_to_close={YES: 600})
    v.on_trade(1_000, YES.symbol, "no", 0.39, 10)                     # our 100 YES fill at .40
    dropped = {YES: Quote(YES, 1.0, 0.36, 0.38, 500, 300)}            # mid .37: -3.00 marked
    step = loop.step(1.0, dropped, secs_to_close={YES: 599}, earned={YES: 0.5})
    assert YES in loop.stopped
    assert [(d.instrument.outcome, d.qty) for d in step.posts] == [("no", 100.0)]   # unwind the 100 YES only
    assert all(o.instrument.outcome == "no" for o in v.open_orders())
    v2 = _venue()
    loop2 = QuotingLoop(v2, {YES: inst, NO: inst.complement()},
                        MakerConfig(quote_size=100, rewarded_only=False, contract_loss_limit=2.0))
    loop2.step(0.0, {YES: Quote(YES, 0.0, 0.40, 0.43, 500, 300)}, secs_to_close={YES: 600})
    v2.on_trade(1_000, YES.symbol, "no", 0.39, 10)
    loop2.step(1.0, dropped, secs_to_close={YES: 599}, earned={YES: 1.5})   # rewards cover it
    assert not loop2.stopped


def test_max_touch_size_skips_the_side_with_a_deep_queue():
    cfg = MakerConfig(quote_size=100, rewarded_only=False, max_touch_size=1000)
    q = Quote(YES, 0.0, 0.40, 0.43, 5000, 300)                        # 5,000 on the YES bid
    out = maker_quotes(_inst(), q, None, 0.0, 600, cfg)
    assert [d.instrument.outcome for d in out] == ["no"]
    wide = MakerConfig(quote_size=100, rewarded_only=False, max_touch_size=1000, improve_min_spread_ticks=2)
    assert len(maker_quotes(_inst(), q, None, 0.0, 600, wide)) == 2    # stepping inside starts a new level


def _replay_inputs():
    pa = pytest.importorskip("pyarrow")
    h = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    t0 = int(h.timestamp())
    tk = YES.symbol
    ns = 1_000_000_000
    book = pa.table({"rt": [t0 * ns, t0 * ns, t0 * ns], "ticker": [tk] * 3, "kind": [3, 3, 3],
                     "side": [None, "yes", "no"], "price": [None, 0.40, 0.57], "qty": [None, 1500.0, 1200.0]})
    trades = pa.table({"rt": [(t0 + 100) * ns], "ticker": [tk], "yes_price": [0.39], "count": [10.0],
                       "taker_side": ["no"]})
    markets = pa.table({"ticker": [tk], "close_ts": [t0 + 900]})
    prog = {"id": "p1", "market_ticker": tk, "start_date": "2026-10-25T12:00:00Z", "end_date": "2026-10-25T12:15:00Z",
            "period_reward": 200_000, "target_size_fp": "1000.00", "discount_factor_bps": 5000}
    return h, tk, {"kalshi_book": book, "kalshi_trades": trades, "kalshi_markets": markets}, prog


def test_settled_contracts_are_marked_at_their_result():
    from app.adapters.sim.maker_replay import MakerReplay, fetch_results
    h, tk, tables, prog = _replay_inputs()
    rep = MakerReplay(["KXCRYPTOLEAD15M"], MakerConfig(quote_size=500, max_inventory=500), [prog],
                      tickers_from_markets=True)
    rep.run(_Store(tables), h, h.replace(minute=20))
    res = fetch_results([tk, "KXCRYPTOLEAD15M-X"], get=lambda p: {"market": {"result": "no" if tk in p else ""}})
    assert res == {tk: 0.0}
    out = rep.report(res)
    assert out["trading_pnl"] == pytest.approx(-500 * 0.40) and out["settled_marks"] == 1


class _S3:
    def __init__(self):
        self.objs = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objs:
            raise KeyError(Key)

    def put_object(self, Bucket, Key, Body, **kw):
        self.objs[Key] = Body

    def get_object(self, Bucket, Key):
        import io
        return {"Body": io.BytesIO(self.objs[Key])}

    def get_paginator(self, name):
        objs = self.objs

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(objs) if k.startswith(Prefix)]}
        return P()


def test_paper_job_scores_each_archived_hour_once_and_sums_them(monkeypatch):
    import gzip
    import json
    from app.adapters.sim import maker_paper as mp
    h, tk, tables, prog = _replay_inputs()

    class Store(_Store):
        cache_dir, local_root = "/nonexistent", "/nonexistent"

        def table_key(self, table, hour):
            return "ticks/v1/%s/date=%s/hour=%s/part.parquet" % (table, hour.strftime("%Y-%m-%d"), hour.strftime("%H"))

    s3 = _S3()
    s3.objs["ticks/v1/kalshi_book/date=2026-10-25/hour=12/part.parquet"] = b""
    s3.objs["ticks/v1/lip_programs/date=2026-10-25/1200.json.gz"] = gzip.compress(
        json.dumps({"programs": {"active": [prog]}}).encode())
    monkeypatch.setattr(mp, "SERIES", ["KXCRYPTOLEAD15M"])
    now = h + timedelta(hours=1, minutes=20)
    get = lambda p: {"market": {"result": "yes"}}
    keys = mp.hourly(Store(tables), s3, "b", "ticks", now, lookback=3, get=get)
    assert keys == ["ticks/v1/lip_maker_paper/date=2026-10-25/hour=12.json.gz"]   # 10 and 11 not archived
    assert mp.hourly(Store(tables), s3, "b", "ticks", now, lookback=3, get=get) == []   # already scored
    monkeypatch.setattr(mp, "CONFIGS", dict(mp.CONFIGS, q50=MakerConfig(quote_size=50)))
    assert mp.hourly(Store(tables), s3, "b", "ticks", now, lookback=3, get=get) == keys  # new config: rescored
    doc = json.loads(gzip.decompress(s3.objs[keys[0]]))
    assert set(doc["configs"]) == set(mp.CONFIGS) and doc["configs"]["q1000"]["settled_marks"] == 1
    q = doc["configs"]["q1000"]
    assert q["by_series"]["KXCRYPTOLEAD15M"]["reward"] == pytest.approx(q["rewards"], abs=0.02)
    assert doc["maker_fee_series"] == []                        # no fee snapshot: nobody charged
    assert doc["results"] == {tk: 1.0}
    summ = mp.summary(s3, "b", "ticks", now, days=1)
    assert summ["hours"] == 1 and summ["configs"]["q1000"]["total"] == q["total"]
    assert summ["configs"]["q1000"]["by_series"]["KXCRYPTOLEAD15M"]["total"] == pytest.approx(q["total"], abs=0.02)


def test_maker_fee_series_come_from_the_fee_snapshot(monkeypatch):
    import gzip
    import json
    from app.adapters.sim import maker_paper as mp
    s3 = _S3()
    s3.objs["ticks/lip_programs/latest.json.gz"] = gzip.compress(json.dumps({"series_fees": {
        "KXBRENT15M": {"fee_type": "quadratic_with_maker_fees"}, "KXCRYPTOLEAD15M": {"fee_type": "quadratic"}}}).encode())
    monkeypatch.setattr(mp, "MAKER_FEE_SERIES", [])
    monkeypatch.setattr(mp, "load_latest", lambda c: json.loads(gzip.decompress(c.objs["ticks/lip_programs/latest.json.gz"])))
    assert mp.maker_fee_series(s3) == ["KXBRENT15M"]


def test_reward_series_cover_crypto_lead_and_the_fx_commodity_15m_books():
    from data_pipeline import lip_programs, tick_recorder
    assert {"KXCRYPTOLEAD15M", "KXEURUSD15M", "KXBRENT15M", "KXCOPPER15M"} <= set(lip_programs.REWARD_SERIES)
    assert set(lip_programs.REWARD_SERIES) <= set(lip_programs.FEE_SERIES)
    assert tick_recorder.LIP_SERIES == lip_programs.REWARD_SERIES
