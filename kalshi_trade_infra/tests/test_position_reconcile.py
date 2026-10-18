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
    monkeypatch.setattr(la, "api_get_auth", lambda path: {"market_positions": kalshi})
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
    def boom(path):
        raise RuntimeError("403 attestation expired")

    monkeypatch.setattr(la, "api_get_auth", boom)
    out = la.position_mismatches(Cur([]))
    assert len(out) == 1 and "could not read Kalshi positions" in out[0]
