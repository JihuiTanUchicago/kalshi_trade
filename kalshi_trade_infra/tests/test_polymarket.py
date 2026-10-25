"""Polymarket BTC binaries: market classification, books, the strike-ladder curve, matching to
Kalshi contracts, the archive -> features_1s path, and the history day files."""
import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from data_pipeline import polymarket as pmk
from trading_core.pricing import binary_curve as bc
from tests.test_tick_features import FakeS3, H, H0, S, STRIKE, TK, _write

pa = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq  # noqa: E402

from data_pipeline import tick_archiver  # noqa: E402
from data_pipeline.tick_store import TickStore  # noqa: E402

NOON_ET_OCT25 = int(datetime(2026, 10, 25, 16, tzinfo=timezone.utc).timestamp())   # 12:00 EDT


def _gm(question, slug="", tokens=("111", "222"), outcomes=("Yes", "No"), **kw):
    m = {"id": kw.pop("id", "m1"), "question": question, "slug": slug, "conditionId": "0xc",
         "clobTokenIds": json.dumps(list(tokens)), "outcomes": json.dumps(list(outcomes)),
         "endDate": kw.pop("endDate", "2026-10-25T16:00:00Z")}
    m.update(kw)
    return m


# --- curve ------------------------------------------------------------------------------------

def test_monotone_survival_pools_violations_and_averages_duplicates():
    c = bc.monotone_survival([(100, 0.9), (110, 0.5), (105, 0.4), (110, 0.7), (120, float("nan"))])
    assert [k for k, _ in c] == [100, 105, 110]
    ps = [p for _, p in c]
    assert all(a >= b for a, b in zip(ps, ps[1:]))
    assert ps[1] == pytest.approx(ps[2]) == pytest.approx((0.4 + 0.6) / 2)


def test_prob_above_interpolates_on_logit_and_refuses_to_extrapolate():
    c = bc.monotone_survival([(100, 0.8), (110, 0.2)])
    assert bc.prob_above(c, 105) == pytest.approx(0.5)          # logit midpoint of 0.8/0.2
    assert bc.prob_above(c, 100) == pytest.approx(0.8)
    assert bc.prob_above(c, 99.9) is None and bc.prob_above(c, 110.1) is None
    assert bc.prob_yes(c, 100, 110) == pytest.approx(0.6)
    assert bc.prob_yes(c, None, 110) == pytest.approx(0.8)
    assert bc.prob_yes(c, None, None) is None


def test_prob_above_refuses_a_gap_the_curve_falls_through():
    # 2026-10-25 15:00Z: Polymarket's $2k ladder at 0.999 / 0.001 put Kalshi's 80,600 at 0.79 (Kalshi 0.47)
    c = bc.monotone_survival([(78000, 0.999), (80000, 0.999), (82000, 0.001), (84000, 0.001)])
    assert bc.prob_above(c, 80600) is None
    assert bc.prob_yes(c, 80500, 80600) is None
    assert bc.prob_above(c, 79999.99) == pytest.approx(0.999)   # on a strike: exact
    assert bc.prob_above(c, 79000) == pytest.approx(0.999)      # flat on one side: fine
    assert bc.prob_above(c, 83000) == pytest.approx(0.001)
    assert bc.prob_above(bc.monotone_survival([(100, 0.9), (110, 0.3)]), 105) is not None   # step 3.0


# --- classification ---------------------------------------------------------------------------

def test_classify_daily_above_uses_the_rule_time_not_end_date():
    m = _gm("Will the price of Bitcoin be above $110,000 on October 25?", "bitcoin-above-110k-on-october-25",
            endDate="2026-10-25T00:00:00Z",
            description="This market resolves Yes if the Binance 1 minute candle for BTC/USDT 12:00 in the ET "
                        "timezone (noon) on October 25 has a final Close price higher than 110,000.")
    pm = pmk.classify(m)
    assert (pm.kind, pm.strike_lo, pm.strike_hi, pm.end_ts) == ("above", 110000.0, None, NOON_ET_OCT25)
    assert (pm.yes_token, pm.no_token, pm.yes_label) == ("111", "222", "Yes")


def test_classify_below_range_touch_and_non_price_markets():
    desc = {"description": "Resolves at 12:00 PM ET on the date."}
    assert pmk.classify(_gm("Will the price of Bitcoin be less than $100k on October 25?", **desc)).strike_hi == 100000.0
    r = pmk.classify(_gm("Will the price of Bitcoin be between $108,000 and $110,000 on October 25?", **desc))
    assert (r.kind, r.strike_lo, r.strike_hi) == ("range", 108000.0, 110000.0)
    assert pmk.classify(_gm("Will Bitcoin reach $130,000 in October?")).kind == "touch_up"
    assert pmk.classify(_gm("Will Bitcoin dip to $95,000 in October?")).kind == "touch_down"
    assert pmk.classify(_gm("Will Bitcoin dominance be above 60% on October 25?")) is None
    assert pmk.classify(_gm("Will Ethereum be above $4,000 on October 25?")) is None
    assert pmk.classify(_gm("Will the price of Bitcoin be above $110,000?", tokens=("1",))) is None


def test_classify_updown_from_slug_and_from_question():
    t0 = int(datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc).timestamp())       # 4:00 AM EDT
    a = pmk.classify(_gm("Bitcoin Up or Down - October 25, 4:00AM-4:15AM ET", f"btc-updown-15m-{t0}",
                         outcomes=("Up", "Down"), tokens=("u", "d")))
    assert (a.kind, a.start_ts, a.end_ts, a.yes_token, a.yes_label) == ("updown", t0, t0 + 900, "u", "Up")
    # outcome order on the wire does not decide which token is YES
    b = pmk.classify(_gm("Bitcoin Up or Down - October 25, 4:00AM-4:15AM ET", "x", outcomes=("Down", "Up"),
                         tokens=("d", "u"), endDate="2026-10-25T08:15:00Z"))
    assert (b.start_ts, b.end_ts, b.yes_token) == (t0, t0 + 900, "u")
    h = pmk.classify(_gm("Bitcoin Up or Down - October 25, 4AM ET", "bitcoin-up-or-down-october-25-4am-et",
                         outcomes=("Up", "Down"), endDate="2026-10-25T09:00:00Z"))
    assert (h.start_ts, h.end_ts) == (t0, t0 + 3600)


def test_discovery_slugs_follow_the_series_formats():
    now = int(datetime(2026, 10, 25, 8, 7, tzinfo=timezone.utc).timestamp())
    slugs = pmk.discovery_slugs(now)
    t0 = int(datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc).timestamp())
    assert f"btc-updown-15m-{t0}" in slugs and f"btc-updown-15m-{t0 + 900}" in slugs
    assert "bitcoin-up-or-down-october-25-2026-4am-et" in slugs and "bitcoin-up-or-down-october-25-4am-et" in slugs
    assert "bitcoin-above-on-october-25-2026" in slugs and "bitcoin-price-on-october-27-2026" in slugs


def test_wants_book_limits_polling_to_near_windows_and_daily_ladders():
    now = NOON_ET_OCT25 - 3600
    up = pmk.PmMarket("1", "", "", "", "", "y", "n", "Up", "updown", None, None, now, now + 900)
    far = pmk.PmMarket("2", "", "", "", "", "y", "n", "Up", "updown", None, None, now + 86400, now + 86400 + 900)
    five = pmk.PmMarket("3", "", "", "", "", "y", "n", "Up", "updown", None, None, now, now + 300)
    day = pmk.PmMarket("4", "", "", "", "", "y", "n", "Yes", "above", 1e5, None, None, NOON_ET_OCT25)
    touch = pmk.PmMarket("5", "", "", "", "", "y", "n", "Yes", "touch_up", 1e5, None, None, NOON_ET_OCT25)
    assert [pmk.wants_book(m, now) for m in (up, far, five, day, touch)] == [True, False, False, True, False]


# --- books ------------------------------------------------------------------------------------

def test_books_best_first_and_yes_quote_folds_in_the_no_book():
    raw = {"asset_id": "111", "market": "0xc", "timestamp": "1761400000123",
           "bids": [{"price": "0.40", "size": "10"}, {"price": "0.55", "size": "5"}, {"price": "0.52", "size": "0"}],
           "asks": [{"price": "0.70", "size": "3"}, {"price": "0.58", "size": "4"}, {"price": "0.60", "size": "6"}]}
    t = pmk.trim_book(raw, levels=2)
    assert t["bids"] == [[0.55, 5.0], [0.40, 10.0]] and t["asks"] == [[0.58, 4.0], [0.60, 6.0]]
    top = pmk.top_of_book(raw)
    assert (top["bid"], top["ask"], top["ask_depth"], top["n_bids"]) == (0.55, 0.58, 10.0, 2)
    no = pmk.top_of_book({"bids": [{"price": "0.43", "size": "1"}], "asks": [{"price": "0.44", "size": "1"}]})
    assert pmk.yes_quote(top, no) == (pytest.approx(0.56), pytest.approx(0.57))
    assert pmk.yes_quote(pmk.top_of_book({}), no) == (pytest.approx(0.56), pytest.approx(0.57))


# --- matching ---------------------------------------------------------------------------------

def _q(kind, lo=None, hi=None, mid=0.5, spread=0.02, end=NOON_ET_OCT25, start=None, ts=100, mid_id=None):
    m = pmk.PmMarket(mid_id or f"{kind}{lo}{hi}{start}", "", "", "", "", "y", "n", "Yes", kind, lo, hi, start, end)
    return pmk.PmQuote(m, mid - spread / 2, mid + spread / 2, ts)


def test_prob_for_contract_reads_the_ladder_at_kalshi_strikes():
    ladder = [_q("above", 108000, mid=0.8), _q("above", 110000, mid=0.5), _q("below", hi=112000, mid=0.85),
              _q("above", 109000, mid=0.6, end=NOON_ET_OCT25 + 3600)]      # another settlement time
    f = pmk.prob_for_contract(ladder, 109000.0, None, NOON_ET_OCT25)
    exp = bc.prob_above(bc.monotone_survival([(108000, 0.8), (110000, 0.5), (112000, 0.15)]), 109000)
    assert f["pm_p_yes"] == pytest.approx(exp) and f["pm_n"] == 3
    rng = pmk.prob_for_contract(ladder, 109000.0, 111000.0, NOON_ET_OCT25)
    assert 0 < rng["pm_p_yes"] < f["pm_p_yes"]
    assert pmk.prob_for_contract(ladder, 120000.0, None, NOON_ET_OCT25) is None     # off the ladder
    assert pmk.prob_for_contract(ladder, 109000.0, None, NOON_ET_OCT25 + 7200) is None
    wide = [_q("above", 108000, spread=0.5), _q("above", 110000, spread=0.5)]
    assert pmk.prob_for_contract(wide, 109000.0, None, NOON_ET_OCT25) is None       # no usable mids


def test_updown_matches_only_contracts_whose_strike_is_the_open():
    o, c = NOON_ET_OCT25 - 900, NOON_ET_OCT25
    quotes = [_q("updown", start=o, end=c, mid=0.62)]
    assert pmk.prob_for_contract(quotes, 111000.0, None, c, open_ts=o)["pm_p_yes"] == pytest.approx(0.62)
    assert pmk.prob_for_contract(quotes, 111000.0, None, c) is None                 # a fixed-strike contract
    assert pmk.prob_for_contract(quotes, 111000.0, None, c, open_ts=o - 2700) is None


def test_pm_series_uses_the_newest_poll_within_max_age():
    s = pmk.PmSeries([_q("above", 108000, mid=0.8, ts=100), _q("above", 110000, mid=0.4, ts=100),
                      _q("above", 108000, mid=0.9, ts=160), _q("above", 110000, mid=0.6, ts=160),
                      _q("touch_up", 130000, ts=160)])
    assert len(s) == 2
    assert s.at(108000.0, None, NOON_ET_OCT25, None, 99, 30) is None
    a = s.at(108000.0, None, NOON_ET_OCT25, None, 120, 30)
    assert a["pm_p_yes"] == pytest.approx(0.8) and a["pm_age_s"] == 20
    assert s.at(108000.0, None, NOON_ET_OCT25, None, 140, 30) is None              # 100 is too old
    assert s.at(108000.0, None, NOON_ET_OCT25, None, 170, 30)["pm_p_yes"] == pytest.approx(0.9)


def test_history_quotes_land_in_one_minute_poll_and_never_early():
    rows = [{"t": 1000, "market_id": "a", "kind": "above", "strike_lo": 1e5, "end_ts": NOON_ET_OCT25, "p": 0.7},
            {"t": 1021, "market_id": "b", "kind": "above", "strike_lo": 1.1e5, "end_ts": NOON_ET_OCT25, "p": 0.3}]
    q = pmk.quotes_from_history(rows)
    assert [x.ts for x in q] == [1020, 1080]
    assert all(x.ts >= r["t"] for x, r in zip(q, rows))


def test_quotes_from_snapshot_round_trip():
    pm = pmk.classify(_gm("Will the price of Bitcoin be above $110,000 on October 25?",
                          description="12:00 PM ET"))
    rows = [dict(pm.row(), bid=0.4, ask=0.44, ts=123)]
    (q,) = pmk.quotes_from_snapshot(rows)
    assert q.market == pm and q.mid() == pytest.approx(0.42) and q.ts == 123


# --- archive -> features_1s -------------------------------------------------------------------

def _poly_lines():
    o = H0 - 900          # 17:45Z = 1:45 PM EDT, the synthetic KXBTC15M contract's open; close 18:15Z
    cat = {"type": "catalog", "markets": [
        pmk.compact(_gm("Bitcoin Up or Down - October 24, 1:45PM-2:15PM ET", "bitcoin-up-or-down-test",
                        outcomes=("Up", "Down"), tokens=("UP", "DN"), endDate="2026-10-24T18:15:00Z", id="pm1",
                        active=True, bestBid=0.5, bestAsk=0.52)),
        pmk.compact(_gm("Will Bitcoin reach $200,000 in October?", tokens=("T1", "T2"), id="pm2")),
    ]}
    assert pmk.classify(cat["markets"][0]).start_ts == o
    b1 = {"type": "books", "books": [
        {"asset_id": "UP", "market": "0xc", "timestamp": str((H0 + 5) * 1000), "bids": [[0.55, 5]], "asks": [[0.57, 5]]},
        {"asset_id": "DN", "market": "0xc", "bids": [[0.42, 1]], "asks": [[0.44, 2]]}]}
    b2 = {"type": "books", "books": [{"asset_id": "UP", "bids": [[0.60, 1]], "asks": [[0.62, 1]]},
                                     {"asset_id": "DN", "bids": [], "asks": []}]}
    return [json.dumps({"rt": H0 * S + 7, "m": cat}),
            json.dumps({"rt": (H0 + 5) * S + 100, "m": b1}),
            json.dumps({"rt": (H0 + 12) * S + 100, "m": b2}),
            json.dumps({"rt": (H0 + 13) * S, "meta": "http_error", "status": 403, "body": "blocked"})]


def test_archive_and_features_1s_carry_polymarket(tmp_path, monkeypatch):
    root = tmp_path / "ticks"
    _write(root)
    d = root / "polymarket" / "20261024"
    d.mkdir(parents=True)
    (d / "18.ndjson").write_text("\n".join(_poly_lines()) + "\n")
    lake = tmp_path / "lake"
    s3 = FakeS3(str(lake))
    monkeypatch.setattr(tick_archiver, "write_manifest_row", lambda m, conn=None: None)
    mans = {}
    for path, source, hour in tick_archiver.closed_hour_files(str(root), H + timedelta(hours=2)):
        mans[source] = tick_archiver.archive_file(path, source, hour, s3=s3)
    assert mans["polymarket"]["tables"] == {"polymarket_markets": 2, "polymarket_top": 4, "polymarket_meta": 1}
    assert mans["polymarket"]["bad_lines"] == 0
    top = pq.read_table(lake / "ticks/v1/polymarket_top/date=2026-10-24/hour=18/part.parquet").to_pylist()
    assert top[0]["exch_ms"] == (H0 + 5) * 1000 and top[0]["bid"] == 0.55
    monkeypatch.setattr(tick_archiver, "FEATURE_STATE", str(tmp_path / "built.json"))
    store = TickStore(local_root=str(lake))
    assert tick_archiver.build_features(s3=s3, store=store, now=H + timedelta(hours=1, minutes=5)) == 1
    t = pq.read_table(lake / "ticks/v1/features_1s/date=2026-10-24/hour=18/series=KXBTC15M/part.parquet",
                      partitioning=None).to_pylist()
    by = {r["sec"]: r for r in t if r["ticker"] == TK}
    assert by[H0 + 5]["pm_p_yes"] is None or math.isnan(by[H0 + 5]["pm_p_yes"])     # received during second 5
    assert by[H0 + 6]["pm_p_yes"] == pytest.approx(0.565, abs=1e-6)                   # NO book folded in
    assert by[H0 + 12]["pm_p_yes"] == pytest.approx(0.565, abs=1e-6)
    assert by[H0 + 13]["pm_p_yes"] == pytest.approx(0.61, abs=1e-6)
    assert by[H0 + 13]["pm_age_s"] == pytest.approx(1.0) and by[H0 + 13]["pm_spread"] == pytest.approx(0.02)
    assert by[H0 + 42]["pm_p_yes"] == pytest.approx(0.61, abs=1e-6)
    assert math.isnan(by[H0 + 43]["pm_p_yes"])                                         # older than 30s


# --- history ----------------------------------------------------------------------------------

def test_backfill_writes_versioned_day_files(tmp_path, monkeypatch):
    day = datetime(2026, 10, 24, tzinfo=timezone.utc)
    t0 = int(day.timestamp()) + 3600

    def events(session=None, **params):
        slug = params.get("slug")
        if slug == f"btc-updown-15m-{t0}":
            return [{"slug": slug, "markets": [dict(_gm("Bitcoin Up or Down - x", slug, tokens=("U", "D"),
                                                         outcomes=("Up", "Down"), id="u1"),
                                                     closed=True, outcomePrices='["1", "0"]')]}]
        if slug == "bitcoin-above-on-october-24-2026":
            return [{"slug": slug, "markets": [_gm("Will the price of Bitcoin be above $110,000 on October 24?",
                                                   id="a1", description="12:00 PM ET")]}]
        return []

    monkeypatch.setattr(pmk, "gamma_events", events)
    monkeypatch.setattr(pmk, "fetch_price_history", lambda tok, a, b, session=None: [(a + 60, 0.4), (a + 120, 0.45)])
    s3 = FakeS3(str(tmp_path))
    n = pmk.backfill(days=1, s3=s3, now=day + timedelta(days=1, hours=2))
    assert n == 1
    p = tmp_path / f"ticks/v1/polymarket_history_day/v={pmk.HIST_VERSION}/date=2026-10-24/part.parquet"
    rows = pq.read_table(p).to_pylist()
    assert {r["market_id"] for r in rows} == {"u1", "a1"}
    u = [r for r in rows if r["market_id"] == "u1"]
    assert u[0]["resolved"] == 1.0 and u[0]["end_ts"] == t0 + 900 and u[0]["kind"] == "updown"
    stats = json.loads((tmp_path / "ticks/manifest/polymarket_history/date=2026-10-24.json").read_text())
    assert stats["markets"] == 2 and stats["rows"] == 4
    assert pmk.backfill(days=1, s3=s3, now=day + timedelta(days=1, hours=2)) == 0      # already there


# --- app adapter: books, feature provider, feed, research store, engine/backtest wiring ----------

from types import SimpleNamespace  # noqa: E402

from app import backtest, engine  # noqa: E402
from app.adapters.polymarket import features as pmf  # noqa: E402
from app.adapters.polymarket import store as pms  # noqa: E402
from app.adapters.polymarket.feed import SnapshotFeed  # noqa: E402
from app.adapters.polymarket.instruments import instrument  # noqa: E402
from app.markets import FEATURES, MARKETS  # noqa: E402
from trading_core.domain.instruments import BinaryTerms, Instrument, InstrumentId, InstrumentKind  # noqa: E402
from trading_core.ports import FeatureProvider, MarketDataFeed  # noqa: E402


def _snap_rows(ts=NOON_ET_OCT25 - 600):
    o = NOON_ET_OCT25 - 900
    up = pmk.PmMarket("u", "btc-updown-15m-x", "", "", "0xu", "U", "D", "Up", "updown", None, None, o, NOON_ET_OCT25)
    a1 = pmk.PmMarket("a1", "", "", "", "0xa1", "Y1", "N1", "Yes", "above", 108000.0, None, None, NOON_ET_OCT25)
    a2 = pmk.PmMarket("a2", "", "", "", "0xa2", "Y2", "N2", "Yes", "above", 110000.0, None, None, NOON_ET_OCT25)
    return [dict(up.row(), bid=0.60, ask=0.62, bid_size=10.0, ask_size=20.0, ts=ts),
            dict(a1.row(), bid=0.79, ask=0.81, ts=ts), dict(a2.row(), bid=0.49, ask=0.51, ts=ts)]


def test_book_prices_kxbtc15m_from_the_window_and_kxbtcd_from_the_ladder():
    book = pmf.book_from_snapshot(_snap_rows())
    ts = NOON_ET_OCT25 - 560
    f = book.features("KXBTC15M-25OCT251200-00", 111111.0, ts, 0.55, 0.57, None, close_ts=NOON_ET_OCT25)
    assert f["pm_p_yes"] == pytest.approx(0.61) and f["pm_edge"] == pytest.approx(0.05) and f["pm_age_s"] == 40
    d = book.features("KXBTCD-25OCT2512-T108999.99", 108999.99, ts, 0.6, 0.7, None, close_ts=NOON_ET_OCT25)
    assert 0.5 < d["pm_p_yes"] < 0.8 and "pm_edge" in d
    assert book.features("KXBTCD-25OCT2512-T120000", 120000.0, ts, 0.1, 0.2, None, close_ts=NOON_ET_OCT25) == {}
    assert book.features("KXBTCD-X", 109000.0, ts + 3600, 0.1, 0.2, None, close_ts=NOON_ET_OCT25) == {}  # stale
    assert pmf.book_from_snapshot([]) is None
    assert set(pmf.FEATURE_NAMES) <= set(FEATURES)


def test_feature_provider_and_feed_satisfy_the_ports():
    book = pmf.book_from_snapshot(_snap_rows())
    prov = pmf.PolymarketFeatures(lambda as_of: book)
    assert isinstance(prov, FeatureProvider)
    exp = datetime.fromtimestamp(NOON_ET_OCT25, tz=timezone.utc)
    yes = Instrument(InstrumentId("kalshi", "KXBTCD-X", "yes"), InstrumentKind.BINARY, series="KXBTCD",
                     terms=BinaryTerms(expiry=exp, strike=109000.0))
    out = prov.features([yes, yes.complement()], NOON_ET_OCT25 - 560)
    assert out[yes.id]["pm_p_yes"] + out[yes.complement().id]["pm_p_yes"] == pytest.approx(1.0)
    feed = SnapshotFeed(_snap_rows())
    assert isinstance(feed, MarketDataFeed)
    up = instrument(pmk.quotes_from_snapshot(_snap_rows())[0].market)
    assert up.kind is InstrumentKind.BINARY and up.id == InstrumentId("polymarket", "0xu", "yes")
    q, qn = feed.quote(up.id), feed.quote(up.complement().id)
    assert (q.bid, q.ask, q.bid_size) == (0.60, 0.62, 10.0)
    assert (qn.bid, qn.ask, qn.bid_size) == (pytest.approx(0.38), pytest.approx(0.40), 20.0)


def test_latest_snapshot_reads_the_heartbeat_and_drops_the_future():
    rows = _snap_rows()

    class Cur:
        def execute(self, sql, args=None):
            assert args == (pmk.HEARTBEAT_KEY,)

        def fetchone(self):
            return {"state_value": json.dumps({"snapshot": rows})}

    assert len(pms.latest_snapshot(Cur(), NOON_ET_OCT25)) == 3
    assert pms.latest_snapshot(Cur(), NOON_ET_OCT25 - 601) is None


def test_research_store_reads_the_history_day_files(tmp_path, monkeypatch):
    day = datetime(2026, 10, 23, tzinfo=timezone.utc)
    o = int(day.timestamp()) + 3600
    rows = [{"t": o - 60, "market_id": "u", "slug": "", "kind": "updown", "strike_lo": None, "strike_hi": None,
             "start_ts": o, "end_ts": o + 900, "p": 0.5, "resolved": 1.0},
            {"t": o + 60, "market_id": "u", "slug": "", "kind": "updown", "strike_lo": None, "strike_hi": None,
             "start_ts": o, "end_ts": o + 900, "p": 0.55, "resolved": 1.0},
            {"t": o + 60, "market_id": "a", "slug": "", "kind": "above", "strike_lo": 1e5, "strike_hi": None,
             "start_ts": None, "end_ts": o + 900, "p": 0.3, "resolved": None}]
    p = tmp_path / pmk.day_key(day)
    p.parent.mkdir(parents=True)
    pmk.write_day(rows, str(p))
    store = TickStore(local_root=str(tmp_path))
    qs = pms.load_quotes(day, day + timedelta(days=1), store, kinds=("updown",))
    assert [(q.market.market_id, q.ts, q.bid) for q in qs] == [("u", o + 60, 0.55)]   # pre-open point dropped
    book = pmf.load_book("KXBTC15M", day, day + timedelta(days=1), store)
    f = book.features("KXBTC15M-X", 1.0, o + 90, None, None, None, close_ts=o + 900)
    assert f["pm_p_yes"] == pytest.approx(0.55) and "pm_edge" not in f
    lad = pmf.load_book("KXBTCD", day, day + timedelta(days=1), store)
    assert lad.features("KXBTCD-X", 1e5, o + 90, None, None, None, close_ts=o + 900) == {}   # one ladder point


def test_engine_and_backtest_merge_options_and_polymarket(monkeypatch):
    market = MARKETS["btc15m"]

    class Opt:
        def __len__(self):
            return 1

        def features(self, *a, **k):
            return {"opt_p_yes": 0.5}

    monkeypatch.setattr(engine.options_fair, "book_from_rows", lambda rows: Opt())
    src = SimpleNamespace(options=lambda ts: [{}], polymarket=lambda ts: _snap_rows())
    book = engine._btc_fair_books(market, src, NOON_ET_OCT25 - 560)
    f = book.features("KXBTC15M-X", 1.0, NOON_ET_OCT25 - 560, 0.5, 0.52, None, close_ts=NOON_ET_OCT25)
    assert f["opt_p_yes"] == 0.5 and f["pm_p_yes"] == pytest.approx(0.61)

    def boom(ts):
        raise RuntimeError("db down")

    only_pm = engine._btc_fair_books(market, SimpleNamespace(options=boom, polymarket=lambda ts: _snap_rows()),
                                     NOON_ET_OCT25 - 560)
    assert isinstance(only_pm, pmf.PolymarketBook)
    assert engine._btc_fair_books(market, SimpleNamespace(options=None, polymarket=None), 0) is None

    monkeypatch.setattr(backtest.options_fair, "load_book", lambda since: None)
    monkeypatch.setattr(pmf, "load_book", lambda series, since: pmf.book_from_snapshot(_snap_rows()))
    assert isinstance(backtest.forecast_book(market, datetime(2026, 10, 1, tzinfo=timezone.utc)), pmf.PolymarketBook)


def test_research_store_skips_days_with_no_files(tmp_path):
    """A 90-day window with one archived day probes only that day (prod paid a 404 per missing hour)."""
    day = datetime(2026, 10, 23, tzinfo=timezone.utc)
    p = tmp_path / pmk.day_key(day)
    p.parent.mkdir(parents=True)
    o = int(day.timestamp()) + 3600
    pmk.write_day([{"t": o + 60, "market_id": "u", "slug": "", "kind": "updown", "strike_lo": None,
                    "strike_hi": None, "start_ts": o, "end_ts": o + 900, "p": 0.55, "resolved": 1.0}], str(p))
    store = TickStore(local_root=str(tmp_path))
    fetched = []
    real = store._fetch
    store._fetch = lambda key: fetched.append(key) or real(key)
    qs = pms.load_quotes(day - timedelta(days=89), day + timedelta(days=1), store, kinds=("updown",))
    assert [q.bid for q in qs] == [0.55]
    assert fetched == [pmk.day_key(day)]
    assert store.dates("v1/polymarket_top") == set()
