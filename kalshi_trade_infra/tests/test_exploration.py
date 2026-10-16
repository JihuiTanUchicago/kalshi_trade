"""The DefaultPolicy reproduces the pipeline's historical exploration behavior:
constant batch width capped by the remaining budget, and the top few profitable
in-sample candidates (min trade count) as finalists."""
from app import exploration
from app.exploration import DefaultPolicy, PolicyState


def _widths(budget):
    """Replay the chunk loop: ask next_batch, 'propose' that many, repeat until 0."""
    pol, proposed, out, rnd = DefaultPolicy(), 0, [], 0
    while True:
        rnd += 1
        w = pol.next_batch(PolicyState(proposed=proposed, budget=budget, round=rnd)).width
        if w <= 0:
            break
        out.append(w)
        proposed += w
    return out


def test_batching_is_4_4_2_for_budget_10():
    # Preserves the exact historical behavior (budget 10, BATCH 4 -> 4, 4, 2).
    assert _widths(10) == [4, 4, 2]
    assert _widths(8) == [4, 4]
    assert _widths(3) == [3]
    assert _widths(1) == [1]


def _cand(pnl, trades, score):
    return {"in_sample": {"pnl": pnl, "trades": trades}, "score": score}


def test_finalists_are_top_profitable_with_enough_trades():
    pol = DefaultPolicy()
    chunk = [
        _cand(100, 10, 9.0),   # best, qualifies
        _cand(50, 6, 8.0),     # qualifies
        _cand(-5, 20, 7.0),    # loses in-sample -> out
        _cand(80, 3, 6.0),     # too few trades -> out
    ]
    picked = pol.select_finalists(chunk, PolicyState(0, 0, 0))
    assert [t["score"] for t in picked] == [9.0, 8.0]  # ranked by score, filtered


def test_finalists_capped_and_min_three():
    pol = DefaultPolicy()
    # 40 strong candidates -> min(max(3, 40//10), 8) = 4
    many = [_cand(100, 10, float(i)) for i in range(40)]
    assert len(pol.select_finalists(many, PolicyState(0, 0, 0))) == 4
    # 5 candidates -> min(max(3, 0), 8) = 3
    few = [_cand(100, 10, float(i)) for i in range(5)]
    assert len(pol.select_finalists(few, PolicyState(0, 0, 0))) == 3
    # 200 candidates -> capped at MAX_FINALISTS (8)
    lots = [_cand(100, 10, float(i)) for i in range(200)]
    assert len(pol.select_finalists(lots, PolicyState(0, 0, 0))) == exploration.MAX_FINALISTS
