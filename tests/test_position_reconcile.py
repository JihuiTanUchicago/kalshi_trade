"""The alerter must notice when our book and Kalshi disagree about holdings.

Nothing asked Kalshi what we held on 2026-09-27, so four phantom positions and
the unintended shorts they produced went unnoticed for hours.
"""
import data_pipeline.live_alerter as la


class Cur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=()):
        pass

    def fetchall(self):
        return self._rows


def run(kalshi, ours, monkeypatch):
    monkeypatch.setattr(la, "api_get_auth", lambda path: {"market_positions": kalshi})
    return la.position_mismatches(Cur(ours))


def row(ticker, qty, model="random_forest_high_conviction"):
    return {"model_name": model, "market_ticker": ticker, "qty_contracts": qty}


def test_agreement_is_silent(monkeypatch):
    assert run([{"ticker": "T1", "position_fp": "27.00"}], [row("T1", 27)], monkeypatch) == []


def test_a_short_is_always_a_bug(monkeypatch):
    """We only ever buy YES, so a negative position cannot be intended."""
    out = run([{"ticker": "T1", "position_fp": "-21.00"}], [], monkeypatch)
    assert len(out) == 1 and "SHORT" in out[0] and "-21" in out[0]


def test_phantom_in_our_book_is_reported(monkeypatch):
    out = run([], [row("T1", 21)], monkeypatch)
    assert out == ["our book holds 21 x T1 that Kalshi does not"]


def test_holding_we_never_recorded_is_reported(monkeypatch):
    out = run([{"ticker": "T1", "position_fp": "18.00"}], [], monkeypatch)
    assert "does not know about" in out[0]


def test_size_mismatch_is_reported(monkeypatch):
    out = run([{"ticker": "T1", "position_fp": "18.00"}], [row("T1", 27)], monkeypatch)
    assert out == ["size mismatch on T1: Kalshi 18, our book 27"]


def test_two_models_on_one_ticker_sum_before_comparing(monkeypatch):
    kalshi = [{"ticker": "T1", "position_fp": "30.00"}]
    ours = [row("T1", 10, "a"), row("T1", 20, "b")]
    assert run(kalshi, ours, monkeypatch) == []


def test_zero_positions_are_not_holdings(monkeypatch):
    assert run([{"ticker": "T1", "position_fp": "0.00"}], [], monkeypatch) == []


def test_an_unreadable_account_is_itself_reported(monkeypatch):
    def boom(path):
        raise RuntimeError("403 attestation expired")

    monkeypatch.setattr(la, "api_get_auth", boom)
    out = la.position_mismatches(Cur([]))
    assert len(out) == 1 and "could not read Kalshi positions" in out[0]
