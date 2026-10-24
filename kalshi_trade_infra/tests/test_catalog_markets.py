"""Catalog-driven outcome-settled universe (app/markets.py + app/catalog_repository.py).

Proves generation turns enriched `kalshi_series` rows into valid deployable, book-only Markets
(the nba_game model: underlying=None, binary, YES/NO settlement), excludes the series classes that
don't fit (scalar / one-off / illiquid / curated / crypto / financials / multi-leg), builds a real
backtest surface, and falls back to the curated 19 when the catalog is empty - never crashing."""
import collections
from datetime import datetime, timezone

from app import backtest
from app import spec as specmod
from app import markets as mk
from app.markets import CURATED, MARKETS, market_from_series


def _row(series_ticker="KXHIGHMIA", title="Highest temperature in Miami", category="Climate and Weather",
         frequency="daily", open_markets=12, **extra):
    r = {"series_ticker": series_ticker, "title": title, "category": category,
         "frequency": frequency, "open_markets": open_markets}
    r.update(extra)
    return r


# -- generation (pure, market_from_series) -------------------------------------

def test_generates_valid_deployable_outcome_settled_market():
    m = market_from_series(_row())
    assert m is not None
    assert m.key == "kxhighmia" and m.series == "KXHIGHMIA"
    assert m.underlying is None          # outcome-settled: book-only, no spot
    assert m.kind == "binary"
    assert m.deployable is True          # ELIGIBLE (every per-deployment gate still runs)
    assert m.category == "Climate and Weather"
    assert m.close_hour_et is None       # no daily-ladder close-hour filter
    assert m.candle_minutes == 60 and m.history_days == 365  # daily cadence, a year of weather
    # label is carried from the Kalshi title
    assert m.label == "Highest temperature in Miami"


def test_candle_cadence_tracks_frequency():
    assert market_from_series(_row(frequency="custom", series_ticker="KXUFCBOUT")).candle_minutes == 1
    assert market_from_series(_row(frequency="hourly", series_ticker="KXHIGHCHI")).candle_minutes == 1
    assert market_from_series(_row(frequency="weekly", series_ticker="KXMBAAPPS")).candle_minutes == 60


def test_excludes_one_off_and_annual_and_sparse_frequencies():
    for freq in ("one_off", "annual", "monthly", "quarterly", "", None):
        assert market_from_series(_row(frequency=freq)) is None


def test_excludes_illiquid_series():
    assert market_from_series(_row(open_markets=1)) is None          # below CATALOG_MIN_OPEN (2)
    assert market_from_series(_row(open_markets=0)) is None
    assert market_from_series(_row(open_markets=None)) is None


def test_excludes_crypto_financials_and_other_disallowed_categories():
    for cat in ("Crypto", "Financials", "Elections", "Politics", "Entertainment", "Economics", "Commodities", "", None):
        assert market_from_series(_row(category=cat)) is None


def test_excludes_scalar_market_type():
    assert market_from_series(_row(market_type="scalar")) is None
    assert market_from_series(_row(market_type="binary")) is not None


def test_excludes_multileg_and_curated_series():
    assert market_from_series(_row(series_ticker="KXMVECROSSCATEGORY")) is None   # multi-leg parlay
    # A curated series must never be shadowed by a generated duplicate.
    assert market_from_series(_row(series_ticker="KXNBAGAME", category="Sports", frequency="custom")) is None


def test_generated_key_is_spec_valid():
    m = market_from_series(_row(series_ticker="KX-HIGH.NY"))
    assert m is not None and m.key == "kx_high_ny"   # punctuation collapsed to spec-safe key


# -- DB filter (catalog_repository.deployable_series) --------------------------

class _StubCursor:
    """Captures the SQL + params and returns canned rows - enough to prove the filter builds a
    bounded, curated-excluding, category/frequency-parameterized query."""
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params=()):
        self.sql = " ".join(sql.split())
        self.params = params

    def fetchall(self):
        return self.rows


def test_deployable_series_builds_bounded_filter():
    from app import catalog_repository
    rows = [_row()]
    cur = _StubCursor(rows)
    out = catalog_repository.deployable_series(
        cur, {"KXBTCD", "KXNBAGAME"}, min_open=2, cap=150,
        allowed_categories=["Sports", "Economics"], recurring_freqs=["daily", "custom"])
    assert out == rows
    assert "open_markets >= %s" in cur.sql
    assert "category IN (%s,%s)" in cur.sql
    assert "frequency IN (%s,%s)" in cur.sql
    assert "NOT LIKE '%%MVE%%'" in cur.sql
    assert "series_ticker NOT IN" in cur.sql
    assert "ORDER BY open_markets DESC" in cur.sql and "LIMIT %s" in cur.sql
    # params: min_open, categories..., freqs..., curated..., cap
    assert cur.params[0] == 2 and cur.params[-1] == 150


def test_deployable_series_empty_when_no_categories():
    from app import catalog_repository
    cur = _StubCursor([])
    assert catalog_repository.deployable_series(cur, set(), 2, 150, [], ["daily"]) == []


# -- dynamic MARKETS + empty-catalog fallback ----------------------------------

def test_empty_catalog_falls_back_to_curated(monkeypatch):
    # No DB (get_db_conn raises) must yield {} and never crash.
    import data_pipeline.common as common
    def _boom():
        raise RuntimeError("no db in tests")
    monkeypatch.setattr(common, "get_db_conn", _boom)
    assert mk.load_catalog_markets() == {}


def test_markets_contains_all_curated():
    # However the catalog loaded, the 19 curated markets are always present and unshadowed.
    for key, m in CURATED.items():
        assert MARKETS[key] is m


def test_catalog_disabled_env(monkeypatch):
    monkeypatch.setattr(mk, "CATALOG_DISABLED", True)
    assert mk.load_catalog_markets() == {}


class _DummyConn:
    def cursor(self):
        class _C:
            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
        return _C()

    def close(self):
        pass


def test_load_catalog_markets_caps_global_and_per_category(monkeypatch):
    # The ceilings still work as a throttle when set low: 60 Sports + 60 Weather rows,
    # global cap 150, per-category 40 -> 40 of each kept. (Caps pinned here so the test proves
    # the MECHANISM regardless of the generous production defaults.)
    from app import catalog_repository
    import data_pipeline.common as common
    rows = ([_row(series_ticker="KXSPORT%d" % i, category="Sports", frequency="custom", open_markets=50 - i % 10)
             for i in range(60)] +
            [_row(series_ticker="KXHIGHX%d" % i, category="Climate and Weather", frequency="daily", open_markets=30)
             for i in range(60)])
    monkeypatch.setattr(mk, "CATALOG_DISABLED", False)
    monkeypatch.setattr(mk, "CATALOG_MAX_MARKETS", 150)
    monkeypatch.setattr(mk, "CATALOG_MAX_PER_CATEGORY", 40)
    monkeypatch.setattr(common, "get_db_conn", lambda: _DummyConn())
    monkeypatch.setattr(catalog_repository, "deployable_series", lambda *a, **k: rows)
    gen = mk.load_catalog_markets()
    cats = collections.Counter(m.category for m in gen.values())
    assert cats["Sports"] == 40 and cats["Climate and Weather"] == 40     # per-category ceiling
    assert len(gen) == 80 <= mk.CATALOG_MAX_MARKETS             # under global cap
    assert all(m.underlying is None and m.deployable for m in gen.values())


def test_default_caps_do_not_starve_the_collected_universe(monkeypatch):
    # The owner's bar: every collected, tradeable series becomes deployable, not a curated subset.
    # 300 eligible series (far above the OLD 150/40 caps) must ALL generate under the defaults.
    from app import catalog_repository
    import data_pipeline.common as common
    rows = [_row(series_ticker="KXSPORT%d" % i, category="Sports", frequency="custom",
                 open_markets=100 - i % 20) for i in range(300)]
    monkeypatch.setattr(mk, "CATALOG_DISABLED", False)
    monkeypatch.setattr(common, "get_db_conn", lambda: _DummyConn())
    monkeypatch.setattr(catalog_repository, "deployable_series", lambda *a, **k: rows)
    gen = mk.load_catalog_markets()
    assert len(gen) == 300          # nothing starved by the (now generous) ceilings
    assert all(m.deployable for m in gen.values())


def test_high_volume_spread_series_is_deployable():
    # KXNCAAFSPREAD (the owner's concrete example: Sports point-spread, Sports/custom, liquid) must
    # generate as a deployable book-only market once the catalog is enriched with category+frequency.
    m = market_from_series(_row(series_ticker="KXNCAAFSPREAD", title="NCAAF point spread",
                                category="Sports", frequency="custom", open_markets=40))
    assert m is not None
    assert m.key == "kxncaafspread" and m.deployable is True
    assert m.underlying is None and m.kind == "binary"   # outcome-settled YES/NO, book-only


# -- backtest surface on a generated market ------------------------------------

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def test_generated_market_builds_backtest_and_settles(monkeypatch):
    """A generated outcome-settled market must build a book-only dataset and settle YES/NO -
    the same shape nba_game proves, but on a market produced by the generator."""
    m = market_from_series(_row(series_ticker="KXHIGHMIA", frequency="hourly"))  # candle_minutes=1
    assert m is not None and m.candle_minutes == 1
    markets, candles = [], []
    for k in range(8):
        open_ts = T0 + k * 3600
        close = datetime.fromtimestamp(open_ts + 45 * 60, tz=timezone.utc)
        ticker = "%s-E%d-T" % (m.series, k)
        markets.append({"ticker": ticker, "strike": 0.0, "close_time": close, "result": "yes"})
        for j in range(1, 3):  # two 15-minute candles before close
            candles.append({"ticker": ticker, "end_period_ts": open_ts + j * 15 * 60,
                            "yes_bid_close": 0.55, "yes_ask_close": 0.57})
    ds = backtest.build_dataset(m, markets, candles, btc=[])
    assert ds.contracts == 8 and len(ds.frames) > 0
    snap = ds.frames[0][1][0]
    for feat in ("yes_bid", "yes_ask", "spread", "mid", "tte_min", "hour_et"):
        assert feat in snap.features
    for absent in ("spot", "moneyness", "z_score"):       # no underlying -> no strike-vs-spot features
        assert absent not in snap.features
    assert set(ds.results.values()) == {"yes"}

    # A simple YES rule settles on the outcome (DSL degrades cleanly on a strikeless market).
    code = ("def signals(window):\n"
            "    return [[{'ticker': c['ticker'], 'side': 'yes'} for c in fr['contracts']]\n"
            "            for fr in window['frames']]\n")
    from app import sandbox
    if sandbox.os_sandbox_available():
        monkeypatch.setitem(MARKETS, m.key, m)   # register the generated market so spec.validate accepts it
        s = specmod.validate({"market": m.key, "code": code,
                              "sizing": {"stake": 10.0, "max_positions": 1}})
        trades = backtest.simulate(s, ds, ds.start_ts, ds.end_ts + 1)
        assert len(trades) == 8
        assert trades[0].exit_price == 1.0 and trades[0].reason == "settled"


def test_generated_categories_stay_inside_the_traded_set():
    from data_pipeline.common import TRADED_CATEGORIES
    assert mk.ALLOWED_CATEGORIES <= TRADED_CATEGORIES
    assert {"Sports", "Climate and Weather"} <= mk.ALLOWED_CATEGORIES
    assert {m.category for m in mk.CURATED.values()} <= {"Crypto", "Crypto perpetuals", "Sports", "Weather", "Bittensor"}
