"""Dreaming — the self-evolving exploration policy (Tau-RSI P4).

After a research run, the policy-development agent reviews the user's recorded
discovery tree and their current exploration policy and proposes revised policies
(pure-function code). Each candidate is validated in the SANDBOX and scored on the
REPLAY simulator over the user's own history — no new LLM proposals, no new
backtests. The best candidate whose replay score beats the current policy becomes
the user's new policy. The current policy is always in the running, so a user's
policy can never get worse (the paper's monotonic-improvement guarantee).

This is the loop that closes Dream-RSI for our pipeline: online research produces
the tree (P1), the replay simulator scores policies over it cheaply (P2), the
sandbox makes an LLM-authored policy safe to run (P3), and here (P4) the agent
"dreams" up better policies and we keep the best.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from app import replay, sandbox
from app import repository as repo
from app.exploration import DefaultPolicy
from app.llm import Usage, ask_json

MIN_TREE = 12          # need some history before evolving is meaningful
N_CANDIDATES = 3       # revised policies to dream up per round
_EPS = 1e-6

# The policy the agent starts from / improves on, shown to it verbatim.
DEFAULT_POLICY_SRC = """\
def next_batch(state):
    # Propose up to 4 hypotheses per round, capped by the remaining budget.
    return min(4, state["budget"] - state["proposed"])

def select_finalists(candidates, state):
    # The top few profitable in-sample ideas (>= 5 trades) earn an unseen-data test.
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    n = min(max(3, len(candidates) // 10), 8)
    out = []
    for c in ranked[:n]:
        ins = c["in_sample"]
        if ins["pnl"] > 0 and ins["trades"] >= 5:
            out.append(c)
    return out
"""

DREAM_SYSTEM = (
    "You improve a trading-research EXPLORATION POLICY: pure Python that decides how to "
    "allocate search over hypotheses. It defines exactly two functions and does NOTHING "
    "else — no imports, no I/O, no dunder (__...__) names or attributes, only basic builtins "
    "(min, max, sorted, sum, len, range, list, dict, abs, round, enumerate, zip, any, all).\n"
    "  next_batch(state) -> int: how many NEW hypotheses to propose this round (0 = stop). "
    "state has keys: proposed (int, how many proposed so far this run), budget (int, max this run), "
    "round (int, 1-based).\n"
    "  select_finalists(candidates, state) -> list: the subset of this run's candidates to test on "
    "UNSEEN data (keep it small — testing everything out-of-sample manufactures false edges). Each "
    "candidate is a dict with keys score (float, in-sample rank) and in_sample ({pnl, trades}). Return "
    "a sublist of `candidates` (the same dict objects).\n"
    "You are scored by replaying your policy over the user's recorded history with the objective "
    "V = best_unseen_pnl - 0.1*hypotheses_generated + 0.1*avg_batch_width: reach the best strategies "
    "with FEWER generations and sensible batching. Return improved, correct, safe policies."
)


def _check(reply: Dict) -> List[str]:
    pols = reply.get("policies")
    if not isinstance(pols, list) or not pols:
        raise ValueError("expected a non-empty 'policies' list")
    out = [p for p in pols if isinstance(p, str) and p.strip()][:N_CANDIDATES]
    if not out:
        raise ValueError("no usable policy code")
    return out


def _tree_summary(tree: List[replay.Node], base: replay.ReplayResult) -> str:
    tested = sum(1 for n in tree if n.tested)
    passed = sum(1 for n in tree if n.passed)
    best = max((n.oos_pnl for n in tree if n.tested), default=0.0)
    return ("History: %d hypotheses recorded, %d gated on unseen data, %d passed; best unseen P&L $%.2f. "
            "Your current policy replays to V=%.3f using %d generations (avg batch %.1f over %d rounds)."
            % (len(tree), tested, passed, best, base.value, base.generations, base.parallelism, base.rounds))


def evolve_policy(conn, user_id: int, market: str, model: Callable, usage: Usage,
                  log: Callable, n: int = N_CANDIDATES) -> bool:
    """Dream up revised policies, keep the best replay-validated one. Returns True if
    the user's policy improved. Never makes it worse (the current policy competes)."""
    cur = conn.cursor()
    tree = replay.build_tree(cur, user_id, market)
    if len(tree) < MIN_TREE:
        return False
    budget = len(tree)

    row = repo.get_policy(cur, user_id)
    current_code = row["code"] if row else DEFAULT_POLICY_SRC
    current = sandbox.safe_policy(current_code)  # safe: falls back to default if somehow invalid
    base = replay.replay(current, tree, budget)
    best_code, best_v = (row["code"] if row else None), base.value

    prompt = ("Current exploration policy:\n```python\n%s\n```\n%s\n\nPropose %d improved policies that "
              "score higher on replay. Reply JSON: {\"policies\": [\"<full python>\", ...]}."
              % (current_code, _tree_summary(tree, base), n))
    try:
        candidates = ask_json(model, DREAM_SYSTEM, [{"role": "user", "content": prompt}], _check, usage)
    except Exception as e:
        log("step", "Dreaming skipped: %s" % e)
        return False

    for code in candidates:
        try:
            cand = sandbox.load_policy(code)
        except sandbox.PolicyError:
            continue
        try:
            r = replay.replay(cand, tree, budget)
        except Exception:
            continue
        if r.value > best_v + _EPS:
            best_code, best_v = code, r.value

    improved = best_code is not None and best_code != (row["code"] if row else None)
    if improved:
        repo.set_policy(cur, user_id, best_code, best_v)
        log("step", "Research policy evolved: replay score %.3f -> %.3f. Future runs explore smarter."
            % (base.value, best_v))
    return improved


def current_policy(cur, user_id: int):
    """The user's active exploration policy (sandboxed), or the default."""
    row = repo.get_policy(cur, user_id)
    return sandbox.safe_policy(row["code"]) if row else DefaultPolicy()
