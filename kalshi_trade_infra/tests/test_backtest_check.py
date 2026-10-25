"""Each book against its backtest (app/services/backtest_check.py): per-trade P&L and win rate, an
honest band, "too early" under 10 trades, books never added up. Display only; no DB."""
import math

import pytest

from app.services import backtest_check as bc

OOS = {"out_of_sample": {"trades": 40, "pnl": 6.0, "win_rate": 0.61}, "in_sample": {"trades": 90, "pnl": 30.0, "win_rate": 0.7}}


def _stats(pnls, cost_each=4.6):
    return {"trades": len(pnls), "pnl": sum(pnls), "pnl_sq": sum(p * p for p in pnls),
            "wins": sum(1 for p in pnls if p > 0), "cost": cost_each * len(pnls)}


def _alternating(n, mean, swing):
    """n trades averaging `mean`, alternating mean+swing and mean-swing (n even)."""
    return [mean + swing if i % 2 == 0 else mean - swing for i in range(n)]


def test_within_the_usual_range_reads_plainly():
    c = bc.book_check("paper", _stats(_alternating(34, 0.12, 0.5)), bc.backtest_figures(OOS, 5.0))
    assert c["verdict"] == "within" and c["trades"] == 34
    assert c["line"] == ("On paper: 34 trades, +$0.12/trade vs backtest +$0.15/trade; won 50% vs 61%. "
                         "Within the backtest's usual range.")


def test_the_band_is_two_standard_errors_of_the_books_own_spread():
    pnls = _alternating(34, 0.12, 0.5)
    c = bc.book_check("paper", _stats(pnls), bc.backtest_figures(OOS, 5.0))
    mean = sum(pnls) / len(pnls)
    sd = math.sqrt(sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1))
    se = sd / math.sqrt(len(pnls))
    assert c["low"] == pytest.approx(0.15 - 2 * se, abs=1e-4) and c["high"] == pytest.approx(0.15 + 2 * se, abs=1e-4)


def test_behind_and_ahead_say_so_with_the_range():
    bt = bc.backtest_figures(OOS, 5.0)
    behind = bc.book_check("live", _stats(_alternating(40, -0.10, 0.2)), bt)
    assert behind["verdict"] == "behind"
    assert behind["line"].startswith("Behind its backtest on live: 40 trades, −$0.10/trade vs backtest +$0.15/trade;")
    assert "Below the usual range for 40 trades (+$0.09 to +$0.21)." in behind["line"]
    ahead = bc.book_check("demo", _stats(_alternating(40, 0.40, 0.2)), bt)
    assert ahead["verdict"] == "ahead" and ahead["line"].startswith("Ahead of its backtest on demo: 40 trades, +$0.40/trade")


@pytest.mark.parametrize("n", [1, 9])
def test_under_ten_trades_is_too_early_to_tell(n):
    c = bc.book_check("live", _stats([5.0] * n), bc.backtest_figures(OOS, 5.0))
    assert c["verdict"] == "early" and c["low"] is None
    assert c["line"] == ("On live: %d completed trade%s so far, too early to tell against the backtest (it takes about 10)."
                         % (n, "" if n == 1 else "s"))
    assert bc.book_check("live", _stats([0.1] * 10), bc.backtest_figures(OOS, 5.0))["verdict"] != "early"


def test_out_of_sample_figures_first_then_the_tested_data():
    assert bc.backtest_figures(OOS, 5.0)["source"] == "out_of_sample"
    ins_only = {"out_of_sample": {"trades": 0, "pnl": 0}, "in_sample": {"trades": 50, "pnl": 10.0, "win_rate": 0.55}}
    bt = bc.backtest_figures(ins_only, 5.0)
    assert bt["source"] == "in_sample" and bt["per_trade"] == pytest.approx(0.2)
    c = bc.book_check("paper", _stats(_alternating(20, 0.2, 0.3)), bt)
    assert "vs in-sample backtest +$0.20/trade" in c["line"]
    assert bc.backtest_figures({"in_sample": {"trades": 0}}, 5.0) is None
    assert bc.backtest_figures(None, 5.0) is None


def test_much_smaller_trades_scale_the_backtest_to_the_books_size():
    """A live size ramp trades a fraction of the stake: compare like with like, and say so."""
    bt = bc.backtest_figures(OOS, 5.0)
    small = bc.book_check("live", _stats(_alternating(20, 0.03, 0.1), cost_each=1.25), bt)
    assert small["scaled"] and small["backtest_per_trade"] == pytest.approx(0.15 * 0.25)
    assert "vs backtest +$0.04/trade at this book's trade size" in small["line"]
    # Contract rounding alone (a trade costing a little under the stake) is the same size.
    same = bc.book_check("live", _stats(_alternating(20, 0.15, 0.1), cost_each=4.1), bt)
    assert not same["scaled"] and same["backtest_per_trade"] == pytest.approx(0.15)


def test_one_line_per_book_live_first_and_never_summed():
    stats = {"paper": _stats(_alternating(34, 0.12, 0.5)), "live": _stats([1.0, -1.0, 2.0]), "demo": _stats([])}
    out = bc.checks(stats, OOS, 5.0)
    assert [c["mode"] for c in out] == ["live", "paper"]  # demo has no completed trade: no line
    assert out[0]["trades"] == 3 and out[1]["trades"] == 34
    assert out[0]["per_trade"] == pytest.approx(2.0 / 3, abs=1e-4) and out[1]["per_trade"] == pytest.approx(0.12)
    assert bc.checks(stats, {}, 5.0) == []  # nothing to compare with
