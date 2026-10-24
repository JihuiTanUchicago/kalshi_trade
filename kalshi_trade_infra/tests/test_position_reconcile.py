"""The alerter must notice when our book and Kalshi disagree about holdings.

Nothing asked Kalshi what we held on 2026-09-27, so four phantom positions and
the unintended shorts they produced went unnoticed for hours.

Tau-aware: "ours" is now the SIGNED net of the old live_positions table AND the
per-user live app_positions (YES +, NO -), mirroring the exchange's signed
position. A legitimately held NO (negative on the exchange) must reconcile
clean, not look like a short.
"""
import data_pipeline.live_alerter as la


class Cur:
    """Answers the two queries position_mismatches issues: the old live_positions
    rows and the aggregated live app_positions rows."""

    def __init__(self, live_rows, app_rows=None):
        self._live = live_rows
        self._app = app_rows or []
        self._last = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT model_name, market_ticker, qty_contracts FROM live_positions"):
            self._last = self._live
        elif s.startswith("SELECT ticker, side, COALESCE(SUM(qty),0) AS qty FROM app_positions"):
            self._last = self._app
        else:
            raise AssertionError("unexpected SQL: " + s[:80])

    def fetchall(self):
        return self._last


def run(kalshi, live_rows, monkeypatch, app_rows=None):
    monkeypatch.setattr(la, "api_get_auth", lambda path, params=None: {"market_positions": kalshi})
    return la.position_mismatches(Cur(live_rows, app_rows))


def row(ticker, qty, model="random_forest_high_conviction"):
    return {"model_name": model, "market_ticker": ticker, "qty_contracts": qty}


def app_row(ticker, side, qty):
    return {"ticker": ticker, "side": side, "qty": qty}


def test_agreement_is_silent(monkeypatch):
    assert run([{"ticker": "T1", "position_fp": "27.00"}], [row("T1", 27)], monkeypatch) == []


def test_a_held_no_position_reconciles_clean(monkeypatch):
    """A NO position is a short-YES on the exchange (-12). With a matching live
    app_positions NO row it must be silent, NOT flagged as a short."""
    out = run([{"ticker": "T1", "position_fp": "-12.00"}], [], monkeypatch,
              app_rows=[app_row("T1", "no", 12)])
    assert out == []


def test_an_untracked_no_is_reported_as_untracked(monkeypatch):
    """A naked negative with nothing in our book is untracked NO exposure now,
    not an automatic short."""
    out = run([{"ticker": "T1", "position_fp": "-21.00"}], [], monkeypatch)
    assert len(out) == 1 and "does not know about" in out[0] and "NO" in out[0] and "21" in out[0]


def test_an_opposite_direction_net_is_a_short(monkeypatch):
    """Book expects YES, exchange holds NO (opposite signs) — a genuine short."""
    out = run([{"ticker": "T1", "position_fp": "-5.00"}], [row("T1", 5)], monkeypatch)
    assert len(out) == 1 and "SHORT" in out[0]


def test_phantom_in_our_book_is_reported(monkeypatch):
    out = run([], [row("T1", 21)], monkeypatch)
    assert out == ["our book holds 21 x T1 that Kalshi does not"]


def test_holding_we_never_recorded_is_reported(monkeypatch):
    out = run([{"ticker": "T1", "position_fp": "18.00"}], [], monkeypatch)
    assert "does not know about" in out[0] and "YES" in out[0]


def test_size_mismatch_is_reported(monkeypatch):
    out = run([{"ticker": "T1", "position_fp": "18.00"}], [row("T1", 27)], monkeypatch)
    assert out == ["size mismatch on T1: Kalshi 18, our book 27"]


def test_app_positions_count_toward_our_book(monkeypatch):
    """A Tau live YES position tracked only in app_positions is not 'untracked'."""
    out = run([{"ticker": "T1", "position_fp": "12.00"}], [], monkeypatch,
              app_rows=[app_row("T1", "yes", 12)])
    assert out == []


def test_two_models_on_one_ticker_sum_before_comparing(monkeypatch):
    kalshi = [{"ticker": "T1", "position_fp": "30.00"}]
    live = [row("T1", 10, "a"), row("T1", 20, "b")]
    assert run(kalshi, live, monkeypatch) == []


def test_zero_positions_are_not_holdings(monkeypatch):
    assert run([{"ticker": "T1", "position_fp": "0.00"}], [], monkeypatch) == []


def test_an_unreadable_account_is_itself_reported(monkeypatch):
    def boom(path, params=None):
        raise RuntimeError("403 attestation expired")

    monkeypatch.setattr(la, "api_get_auth", boom)
    out = la.position_mismatches(Cur([]))
    assert len(out) == 1 and "could not read Kalshi positions" in out[0]


def test_positions_past_the_first_page_are_counted(monkeypatch):
    """A holding on page two must not make our book look like a phantom."""
    pages = {
        None: {"market_positions": [{"ticker": "T1", "position_fp": "5.00"}], "cursor": "p2"},
        "p2": {"market_positions": [{"ticker": "T2", "position_fp": "7.00"}], "cursor": ""},
    }
    seen = []

    def api(path, params=None):
        seen.append(dict(params or {}))
        return pages[(params or {}).get("cursor")]

    monkeypatch.setattr(la, "api_get_auth", api)
    assert la.position_mismatches(Cur([row("T1", 5), row("T2", 7)])) == []
    assert [p.get("cursor") for p in seen] == [None, "p2"]


def test_endless_paging_is_reported_not_looped(monkeypatch):
    monkeypatch.setattr(la, "api_get_auth",
                        lambda path, params=None: {"market_positions": [], "cursor": "again"})
    out = la.position_mismatches(Cur([]))
    assert len(out) == 1 and "could not read Kalshi positions" in out[0]


# --- persistence through build_alerts: one run is noise, two is an alert ---

def _now():
    return {"enabled": {}, "paused": {}, "positions": [], "last_trade_id": 0, "daily": {},
            "cash": 100.0, "cash_source": "kalshi_api", "writers": {}}


def tick(prev, kalshi, live_rows, monkeypatch, app_rows=None):
    """One alerter run against the given exchange and book. Returns
    (urgent, normal, state-to-carry-forward)."""
    monkeypatch.setattr(la, "api_get_auth", lambda path, params=None: {"market_positions": kalshi})
    monkeypatch.setattr(la, "engine_errors_since", lambda offset: (offset, []))
    monkeypatch.setattr(la, "attestation_days_left", lambda: 30.0)
    now = _now()
    urgent, normal = la.build_alerts(now, prev, Cur(live_rows, app_rows))
    mismatch = [ln for ln in urgent + normal if "Kalshi" in ln]
    return [u for u in urgent if u in mismatch], [n for n in normal if n in mismatch], now


SHORT_EXCH = [{"ticker": "T1", "position_fp": "-5.00"}]
PRIMED = {"cash": 100.0, "cash_source": "kalshi_api"}  # a non-empty prev: not the first run


def test_a_single_disagreement_is_not_reported(monkeypatch):
    urgent, normal, _ = tick(PRIMED, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    assert urgent == [] and normal == []


def test_a_short_that_persists_is_urgent(monkeypatch):
    _, _, s1 = tick(PRIMED, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    urgent, normal, _ = tick(s1, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    assert len(urgent) == 1 and "SHORT" in urgent[0] and normal == []


def test_a_persisting_untracked_holding_is_urgent(monkeypatch):
    """The 2026-09-27 shape: the engine closed what it never held, so the book
    is flat and Kalshi is short. Since NO-side shipped that reads as untracked
    NO, and it must still interrupt someone."""
    kalshi = [{"ticker": "T1", "position_fp": "-21.00"}]
    _, _, s1 = tick(PRIMED, kalshi, [], monkeypatch)
    urgent, _, _ = tick(s1, kalshi, [], monkeypatch)
    assert len(urgent) == 1 and "does not know about" in urgent[0]


def test_a_persisting_size_mismatch_is_normal(monkeypatch):
    kalshi = [{"ticker": "T1", "position_fp": "18.00"}]
    _, _, s1 = tick(PRIMED, kalshi, [row("T1", 27)], monkeypatch)
    urgent, normal, _ = tick(s1, kalshi, [row("T1", 27)], monkeypatch)
    assert urgent == [] and normal == ["book disagrees with Kalshi: size mismatch on T1: Kalshi 18, our book 27"]


def test_a_persisting_phantom_in_our_book_is_normal(monkeypatch):
    _, _, s1 = tick(PRIMED, [], [row("T1", 21)], monkeypatch)
    urgent, normal, _ = tick(s1, [], [row("T1", 21)], monkeypatch)
    assert urgent == [] and len(normal) == 1 and "Kalshi does not" in normal[0]


def test_a_mismatch_that_clears_by_the_next_run_never_fires(monkeypatch):
    _, _, s1 = tick(PRIMED, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    urgent, normal, _ = tick(s1, [{"ticker": "T1", "position_fp": "5.00"}], [row("T1", 5)], monkeypatch)
    assert urgent == [] and normal == []


def test_a_size_that_drifts_between_runs_still_fires(monkeypatch):
    """Keyed on ticker and kind, not the message text, so a standing mismatch
    whose numbers move every run is not hidden forever."""
    _, _, s1 = tick(PRIMED, [{"ticker": "T1", "position_fp": "18.00"}], [row("T1", 27)], monkeypatch)
    _, normal, _ = tick(s1, [{"ticker": "T1", "position_fp": "17.00"}], [row("T1", 27)], monkeypatch)
    assert len(normal) == 1 and "Kalshi 17" in normal[0]


def test_a_standing_mismatch_is_announced_once_then_its_recovery(monkeypatch):
    _, _, s1 = tick(PRIMED, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    urgent, _, s2 = tick(s1, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    assert len(urgent) == 1
    urgent, normal, s3 = tick(s2, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    assert urgent == [] and normal == []
    urgent, normal, _ = tick(s3, [{"ticker": "T1", "position_fp": "5.00"}], [row("T1", 5)], monkeypatch)
    assert urgent == [] and normal == ["Resolved: book agrees with Kalshi again on T1"]


def test_a_mismatch_changing_kind_is_announced_again(monkeypatch):
    kalshi = [{"ticker": "T1", "position_fp": "3.00"}]
    _, _, s1 = tick(PRIMED, kalshi, [row("T1", 5)], monkeypatch)
    _, normal, s2 = tick(s1, kalshi, [row("T1", 5)], monkeypatch)
    assert len(normal) == 1 and "size mismatch" in normal[0]
    _, _, s3 = tick(s2, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    urgent, _, _ = tick(s3, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    assert len(urgent) == 1 and "SHORT" in urgent[0]


def test_state_written_before_this_fix_still_loads(monkeypatch):
    """Old state stored message strings; they simply do not match a key, so the
    first run after deploy is a quiet observation, not a crash or a false alert."""
    prev = dict(PRIMED, position_mismatch=["SHORT/direction mismatch on T1: Kalshi -5, our book 5"])
    urgent, normal, now = tick(prev, SHORT_EXCH, [row("T1", 5)], monkeypatch)
    assert urgent == [] and normal == [] and now["position_mismatch"] == ["T1|short"]


# --- the legacy engine's heartbeat matters only while a legacy model can trade ---

def _stale_lines(enabled, monkeypatch):
    monkeypatch.setattr(la, "api_get_auth", lambda path, params=None: {"market_positions": []})
    monkeypatch.setattr(la, "engine_errors_since", lambda offset: (offset, []))
    monkeypatch.setattr(la, "attestation_days_left", lambda: 30.0)
    now = _now()
    now["enabled"] = enabled
    now["writers"] = {"live_engine": 9999.0, "forward_quotes": 9999.0}
    urgent, _normal = la.build_alerts(now, dict(PRIMED, enabled=enabled), Cur([], None))
    return [u for u in urgent if u.startswith("STALE")]


def test_stopped_legacy_engine_is_not_stale_while_every_model_is_off(monkeypatch):
    lines = _stale_lines({"random_forest": False, "binary_theory_edge": False}, monkeypatch)
    assert not any("live_engine" in ln for ln in lines)
    assert any("forward_quotes" in ln for ln in lines), "other writers are still watched"


def test_legacy_engine_heartbeat_returns_once_a_model_is_enabled(monkeypatch):
    lines = _stale_lines({"random_forest": True, "binary_theory_edge": False}, monkeypatch)
    assert any("live_engine" in ln for ln in lines)
