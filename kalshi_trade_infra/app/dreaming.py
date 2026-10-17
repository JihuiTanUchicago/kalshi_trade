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
N_CANDIDATES = 5       # revised policies to dream up per round (cheap; more shots, better hit rate)
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
    "state has keys: proposed (int, proposed so far this run), budget (int, max this run), "
    "round (int, 1-based). That is ALL next_batch can see — it CANNOT see any hypothesis's score "
    "or outcome, so it cannot know whether a good strategy has appeared yet.\n"
    "  select_finalists(candidates, state) -> list: the subset of this run's candidates to test on "
    "UNSEEN data. Each candidate is a dict with keys score (float, in-sample rank, higher=better) "
    "and in_sample ({pnl, trades}). Return a sublist of `candidates` (the same dict objects).\n"
    "\nHOW YOU ARE SCORED. We replay your policy over the user's recorded history MANY times, each "
    "time in a DIFFERENT random order, and AVERAGE the objective\n"
    "  V = best_unseen_pnl - 0.1*hypotheses_generated - 0.1*finalists_tested.\n"
    "best_unseen_pnl is the best out-of-sample P&L among the finalists you selected that were "
    "actually gated. Two consequences you MUST reason from:\n"
    "  1. STOPPING EARLY DOES NOT HELP. Because the order is reshuffled every time, a strong strategy "
    "is equally likely to appear last as first, and next_batch is blind to outcomes. Cutting "
    "generations short mostly throws away the winner (a few dollars of compute saved against hundreds "
    "or thousands of lost P&L). Reveal the budget; do not gamble on winners being early.\n"
    "  2. THE REAL LEVER IS select_finalists — PRECISION vs RECALL. Select too few and you miss the "
    "out-of-sample winner (zero credit). Select too many and you pay 0.1 each AND, in real research, "
    "you manufacture false edges (the best of fifty tests is weak evidence). The default ranks by "
    "in-sample score and tests the top ~8; that MISSES winners when in-sample rank predicts "
    "out-of-sample poorly. Improve WHICH candidates earn a test: condition on in_sample pnl and "
    "trades (e.g. require enough trades for the P&L to be trustworthy, prefer sturdier edges), widen "
    "or tighten the set thoughtfully — catch the real winner with as FEW finalists as possible.\n"
    "Return improved, correct, safe policies — each with a one-line plain-English `change` that "
    "a non-coder can read, saying WHAT you altered and WHY (e.g. 'Require >=7 trades before testing "
    "a finalist, so a lucky 2-trade spike can't earn a slot')."
)


def _check(reply: Dict) -> List[Dict]:
    pols = reply.get("policies")
    if not isinstance(pols, list) or not pols:
        raise ValueError("expected a non-empty 'policies' list")
    out: List[Dict] = []
    for p in pols:
        if isinstance(p, str) and p.strip():
            out.append({"code": p, "change": ""})
        elif isinstance(p, dict) and isinstance(p.get("code"), str) and p["code"].strip():
            out.append({"code": p["code"], "change": str(p.get("change") or "")[:300]})
    out = out[:N_CANDIDATES]
    if not out:
        raise ValueError("no usable policy code")
    return out


def _tree_summary(tree: List[replay.Node], base: replay.ReplayResult, base_v: float) -> str:
    tested = sum(1 for n in tree if n.tested)
    passed = sum(1 for n in tree if n.passed)
    best = max((n.oos_pnl for n in tree if n.tested), default=0.0)
    # The selection gap: did the current policy's finalists actually catch the best
    # out-of-sample strategy this history holds? If not, better selection is the win.
    gap = ("It CAUGHT that best strategy (best achievable)."
           if base.best_quality >= best - 1e-6 else
           "It MISSED it — its finalists' best unseen P&L is only $%.2f, so a better "
           "selection rule is the clear improvement." % base.best_quality)
    return ("History: %d hypotheses recorded, %d gated on unseen data, %d passed; the best unseen P&L "
            "anywhere in this history is $%.2f. Your current policy selects %d finalists and scores "
            "mean V=%.3f across orderings (one ordering: %d generations over %d rounds). %s"
            % (len(tree), tested, passed, best, base.finalists, base_v, base.generations, base.rounds, gap))


def evolve_policy(conn, user_id: int, market: str, model: Callable, usage: Usage,
                  log: Callable, n: int = N_CANDIDATES) -> bool:
    """Dream up revised policies, keep the best replay-validated one. Returns True if
    the user's policy improved. Never makes it worse (the current policy competes)."""
    cur = conn.cursor()
    tree = replay.build_tree(cur, user_id, market)
    # Hard guard (Leak 5): the policy optimizer is scored on VALIDATION outcomes only — it
    # chooses WHICH finalists to send; the gatekeeper alone decides whether each clears the FDR
    # budget. It must NEVER see a locked-holdout outcome, or we would be optimizing a second
    # search straight at the holdout. A future build_tree change that leaked holdout pnl sets
    # Node.holdout=True and trips this assert here, loudly, instead of silently corrupting the
    # FDR accounting downstream.
    # ponytail: tripwire, not a type system — dreaming stays subordinate to the gatekeeper by
    # construction (build_tree reads phase='validation'); upgrade to a phase enum only if the
    # tree ever needs to carry more than one phase.
    assert not any(n.holdout for n in tree), \
        "dreaming must never score policies on locked-holdout outcomes (RESEARCH_PIPELINE_DESIGN Leak 5)"
    if len(tree) < MIN_TREE:
        return False
    budget = len(tree)

    row = repo.get_policy(cur, user_id)
    current_code = row["code"] if row else DEFAULT_POLICY_SRC
    current = sandbox.safe_policy(current_code)  # safe: falls back to default if somehow invalid
    base = replay.replay(current, tree, budget)          # one ordering, for the human-readable summary
    base_v = replay.replay_generalization(current, tree, budget)  # the score we actually gate on
    best_code, best_v = (row["code"] if row else None), base_v

    prompt = ("Current exploration policy:\n```python\n%s\n```\n%s\n\nPropose %d improved policies that "
              "score higher. Reply JSON: {\"policies\": [{\"code\": \"<full python>\", \"change\": \"<one line>\"}, ...]}."
              % (current_code, _tree_summary(tree, base, base_v), n))
    try:
        candidates = ask_json(model, DREAM_SYSTEM, [{"role": "user", "content": prompt}], _check, usage)
    except Exception as e:
        log("step", "Dreaming skipped: %s" % e)
        return False

    best_change = ""
    for cand_obj in candidates:
        code = cand_obj["code"]
        try:
            cand = sandbox.load_policy(code)
        except sandbox.PolicyError:
            continue
        try:
            # A research policy must actually research: propose hypotheses AND gate some.
            # Without this, the penalties make a do-nothing policy (V=0) look like an
            # "improvement" over a current one whose selected finalists lose money
            # out-of-sample (V<0) — adopting it would halt the user's research.
            probe = replay.replay(cand, tree, budget)
            if probe.generations <= 0 or probe.finalists <= 0:
                continue
            v = replay.replay_generalization(cand, tree, budget)
        except Exception:
            continue
        if v > best_v + _EPS:
            best_code, best_v, best_change = code, v, cand_obj["change"]

    improved = best_code is not None and best_code != (row["code"] if row else None)
    if improved:
        repo.set_policy(cur, user_id, best_code, best_v, summary=best_change, base_score=base_v)
        log("step", "Research policy evolved: dreamed over %d hypotheses, tried %d candidate policies, "
                    "generalization score %.3f → %.3f. %sFuture runs explore smarter."
            % (len(tree), len(candidates), base_v, best_v, (best_change + " " if best_change else "")))
    else:
        # Always leave a trace so the self-improvement loop is observable, even when the
        # strong default/current policy already wins (monotonic: we only adopt a better one).
        log("step", "Dreaming: tested %d candidate policies over %d hypotheses; best generalization score "
                    "%.3f vs current %.3f — kept your current policy (none beat it yet)."
            % (len(candidates), len(tree), best_v, base_v))
    return improved


def current_policy(cur, user_id: int):
    """The user's active exploration policy (sandboxed), or the default."""
    row = repo.get_policy(cur, user_id)
    return sandbox.safe_policy(row["code"]) if row else DefaultPolicy()
