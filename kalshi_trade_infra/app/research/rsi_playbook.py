"""Research RSI, part 2: a playbook per market family that the loop rewrites from its own results,
and keeps only when the rewrite measurably helps.

    run starts ──► choose(): Thompson draw between the ACTIVE playbook and the CANDIDATE (if any)
                   └► the proposer and the develop turn read the drawn playbook
    run ends ───► score_run(): the run's ideas and how many reached the gate count for that playbook
              ├─► decide(): promote the candidate when P(candidate beats active) >= 0.9, retire it
              │            at <= 0.1 or after MAX_IDEAS without a verdict; a promotion is held while
              │            the candidate's passes lose money on paper and the incumbent's don't
              └─► reflect(): with no candidate pending, the model rewrites the active playbook from
                             this run's verdicts into the next candidate

The yardstick is the share of ideas that REACH THE GATE (survive the research fold, the challenger and
the power pre-screen). It is measured on research data only, so no held-out number ever shapes a
playbook, and every run scores, including those whose ideas all die (a death moves the rate too).
Version 0 is the empty playbook (the pipeline as it was), so the first rewrite has to beat no
playbook at all before it is used for every run.

Per user (the owner's RSI decision: per-user private memory), per family (rsi.family: lessons on NYC
highs carry to Chicago highs; weather lessons don't carry to crypto).
"""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional


_LOG = logging.getLogger(__name__)

PROMOTE_P = 0.9
RETIRE_P = 0.1
MIN_IDEAS = 16      # a candidate needs this many scored ideas before any verdict
MAX_IDEAS = 64      # undecided after this many: retire it and try a fresh rewrite
MAX_CHARS = 2400
_SAMPLES = 4000

DDL = [
    """
    CREATE TABLE IF NOT EXISTS app_rsi_playbooks (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      family VARCHAR(48) NOT NULL,
      version INT NOT NULL,
      parent_id BIGINT NULL,
      status VARCHAR(12) NOT NULL,          -- active|candidate|retired
      text MEDIUMTEXT NOT NULL,
      changes TEXT NULL,                    -- the reflector's one-line account of the rewrite
      source_run_id BIGINT NULL,            -- the run whose verdicts produced this version
      runs INT NOT NULL DEFAULT 0,
      ideas INT NOT NULL DEFAULT 0,
      reached INT NOT NULL DEFAULT 0,       -- ideas that reached the gate
      passed INT NOT NULL DEFAULT 0,
      cost_usd DECIMAL(12,4) NOT NULL DEFAULT 0,
      created_at DATETIME NOT NULL,
      decided_at DATETIME NULL,
      UNIQUE KEY uq_pb_version (user_id, family, version),
      INDEX idx_pb_family (user_id, family, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS app_rsi_assignments (
      run_id BIGINT PRIMARY KEY,
      playbook_id BIGINT NOT NULL,
      scored TINYINT(1) NOT NULL DEFAULT 0,
      created_at DATETIME NOT NULL,
      INDEX idx_rsi_assign_pb (playbook_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

_COLS = ("id, user_id, family, version, parent_id, status, text, changes, source_run_id, runs, ideas, "
         "reached, passed, cost_usd, created_at, decided_at")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _row(cur, where: str, args) -> Optional[Dict]:
    cur.execute("SELECT %s FROM app_rsi_playbooks WHERE %s ORDER BY version DESC LIMIT 1" % (_COLS, where), args)
    return cur.fetchone()


def active(cur, user_id: int, family: str) -> Dict:
    """The family's active playbook, creating the empty version 0 on first use."""
    row = _row(cur, "user_id=%s AND family=%s AND status='active'", (user_id, family))
    if row:
        return row
    cur.execute("INSERT IGNORE INTO app_rsi_playbooks (user_id, family, version, status, text, created_at) "
                "VALUES (%s, %s, 0, 'active', '', %s)", (user_id, family, _now()))
    return _row(cur, "user_id=%s AND family=%s AND status='active'", (user_id, family))


def candidate(cur, user_id: int, family: str) -> Optional[Dict]:
    return _row(cur, "user_id=%s AND family=%s AND status='candidate'", (user_id, family))


def _beta_draw(rng: random.Random, pb: Dict) -> float:
    ideas, reached = int(pb.get("ideas") or 0), int(pb.get("reached") or 0)
    return rng.betavariate(1 + reached, 1 + max(ideas - reached, 0))


def p_better(cand: Dict, act: Dict, seed: int = 0) -> float:
    """P(candidate's gate-reach rate > active's) under Beta(1,1) priors, by seeded Monte Carlo."""
    rng = random.Random(seed)
    wins = sum(_beta_draw(rng, cand) > _beta_draw(rng, act) for _ in range(_SAMPLES))
    return wins / _SAMPLES


def choose(cur, user_id: int, family: str, run_id: int, rng: Optional[random.Random] = None) -> Dict:
    """The playbook this run uses. A resumed run keeps its first draw."""
    cur.execute("SELECT playbook_id FROM app_rsi_assignments WHERE run_id=%s", (run_id,))
    got = cur.fetchone()
    if got:
        row = _row(cur, "id=%s", (got["playbook_id"],))
        if row:
            return row
    act = active(cur, user_id, family)
    cand = candidate(cur, user_id, family)
    pick = act
    if cand:
        rng = rng or random.Random()
        pick = cand if _beta_draw(rng, cand) > _beta_draw(rng, act) else act
    cur.execute("INSERT IGNORE INTO app_rsi_assignments (run_id, playbook_id, created_at) VALUES (%s, %s, %s)",
                (run_id, pick["id"], _now()))
    return pick


def score_run(cur, run_id: int, card: Dict) -> Optional[int]:
    """Credit the run's ideas to the playbook it drew (once). Returns that playbook's id."""
    cur.execute("SELECT playbook_id, scored FROM app_rsi_assignments WHERE run_id=%s", (run_id,))
    got = cur.fetchone()
    if not got or got["scored"]:
        return None
    cur.execute("UPDATE app_rsi_playbooks SET runs=runs+1, ideas=ideas+%s, reached=reached+%s, passed=passed+%s, "
                "cost_usd=cost_usd+%s WHERE id=%s",
                (int(card["explored"]), int(card["gated"]), int(card["passed"]), float(card["cost_usd"]),
                 got["playbook_id"]))
    cur.execute("UPDATE app_rsi_assignments SET scored=1 WHERE run_id=%s", (run_id,))
    return got["playbook_id"]


PAPER_MIN_TRIPS = 30   # realistic paper round trips before a playbook's paper record can veto it


def _paper_loses(rec: Optional[Dict]) -> Optional[bool]:
    """True/False once a playbook's passes have PAPER_MIN_TRIPS realistic round trips, else None."""
    if not rec or int(rec.get("round_trips") or 0) < PAPER_MIN_TRIPS:
        return None
    return float(rec.get("net_pnl") or 0) < 0


def decide(cur, user_id: int, family: str,
           paper_of: Optional[Callable[[], Dict]] = None) -> Optional[str]:
    """Promote, retire or keep testing the family's candidate. Returns what happened, if anything.

    paper_of, when given, returns rsi.paper_outcomes(...)["by_playbook"]. It is read only when a
    promotion is due: a candidate whose gate passes lose money on paper (PAPER_MIN_TRIPS+ realistic
    trips) is held while the incumbent's do not, since reaching the gate more often is worth nothing
    if what passes bleeds against the live book."""
    cand = candidate(cur, user_id, family)
    if not cand or int(cand["ideas"] or 0) < MIN_IDEAS:
        return None
    act = active(cur, user_id, family)
    p = p_better(cand, act)
    now = _now()
    if p >= PROMOTE_P:
        if paper_of is not None:
            try:
                paper = paper_of() or {}
            except Exception:  # noqa: BLE001 - paper evidence is advisory; the gate evidence stands
                paper = {}
            pick = lambda pid: paper.get(pid) or paper.get(str(pid))  # noqa: E731 - JSON keys may be str
            if _paper_loses(pick(cand["id"])) and not _paper_loses(pick(act["id"])):
                return None if int(cand["ideas"]) < MAX_IDEAS else _retire(cur, cand, act, p, now, " its passes lose on paper")
        cur.execute("UPDATE app_rsi_playbooks SET status='retired', decided_at=%s WHERE id=%s", (now, act["id"]))
        cur.execute("UPDATE app_rsi_playbooks SET status='active', decided_at=%s WHERE id=%s", (now, cand["id"]))
        return "promoted v%d over v%d (P(better)=%.2f)" % (cand["version"], act["version"], p)
    if p <= RETIRE_P or int(cand["ideas"]) >= MAX_IDEAS:
        return _retire(cur, cand, act, p, now)
    return None


def _retire(cur, cand: Dict, act: Dict, p: float, now, why: str = "") -> str:
    cur.execute("UPDATE app_rsi_playbooks SET status='retired', decided_at=%s WHERE id=%s", (now, cand["id"]))
    return "retired v%d, v%d stays (P(better)=%.2f%s)" % (cand["version"], act["version"], p,
                                                          (";" + why) if why else "")


REFLECT_SYSTEM = """You maintain the research PLAYBOOK for one family of Kalshi prediction markets: the
standing lessons an automated research loop has learned there. The hypothesis proposer reads it before
every new round, so it decides what gets tried next.

Rewrite the playbook given the latest run. Rules:
- At most %d characters. Plain bullets under these headings, in this order:
  DEAD ENDS (mechanisms the data has killed, and why)
  WHERE THE INFORMATION IS (features, time bands, conditions that showed real signal)
  PIPELINE FACTS (what the data really contains: features that ARE populated, quirks to respect)
  NEXT ANGLES (the 2-4 most promising untried directions, each with its mechanism)
- Keep a lesson only if the evidence supports it; merge duplicates; drop lessons the new run contradicts.
- An idea dropped because the proposer BELIEVED a feature was missing is a pipeline lesson, not a dead
  end: check the feature list you are given and record the truth under PIPELINE FACTS.
- A drop tagged [wrong_fit] or [missing_context] died on the market's STRUCTURE (no game state, no team
  ids, no continuous underlying), not on its prices: record that limit under PIPELINE FACTS so the
  proposer stops spending ideas on it. [spec_invalid] is a system bug: ignore it.
- A code strategy sees the full ascending frame sequence, so lagged and derived features (previous
  mid, changes, crossings, rolling stats, ratios) always exist. Never record "snapshot-only", "no
  history" or "only raw features" as a fact, and delete any such line already in the playbook.
- A code window gives every contract its "strike" and its "event" (one game / day / window) beside the
  features; the measured facts below say how many are nonzero. Never record that strikes, thresholds,
  event / game ids or ladder grouping are missing, and delete any such line already in the playbook
  (live game state such as the score IS missing; that limit stays).
- PIPELINE FACTS must be facts about the data you were shown (feature coverage, measured numbers),
  never beliefs about how a contract works. Every Kalshi contract is a YES/NO binary whose price is
  the probability of YES, including spread, total and prop strikes: never record otherwise, and
  delete any such line already in the playbook.
- Lessons must hold across the family, not one city or one game, unless you say so.
- You see only research-window evidence and gate labels (reached / passed / failed). Never invent
  validation or holdout numbers.
Reply with ONE JSON object: {"playbook": "<the full new playbook>", "changes": "<one sentence: what
changed and why>"}""" % MAX_CHARS


def _check(obj: Dict) -> Dict:
    text = str(obj.get("playbook") or "").strip()
    if len(text) < 40:
        raise ValueError("playbook must be the full rewritten text")
    return {"playbook": text[:MAX_CHARS], "changes": str(obj.get("changes") or "")[:500]}


def idea_lines(events: List[Dict], limit: int = 40) -> List[str]:
    """One line per idea the run judged: title, outcome label and the stated reason (labels only).
    A drop carries its scoreboard tag (rsi.classify_drop), so structural misses stand out."""
    from app.research.rsi import classify_drop
    out = []
    for ev in events:
        if ev.get("kind") != "verdict":
            continue
        d = ev.get("data") or {}
        if d.get("phase") in ("holdout", "forward"):
            continue
        title = (d.get("title") or "")[:120]
        if d.get("status") == "abandoned":
            why = d.get("why") or ""
            out.append("- DROPPED on research data [%s]: %s. Why: %s" % (classify_drop(why)[0], title, why[:300]))
        elif d.get("classification"):
            out.append("- REACHED THE GATE: %s -> %s" % (title, "passed" if d.get("status") == "passed"
                                                         else "did not pass"))
        elif d.get("status") == "rejected":
            out.append("- NOT GATED: %s. %s" % (title, (ev.get("message") or "")[:240]))
    return out[-limit:]


def reflect(model, usage, family: str, market_label: str, current: Dict, card: Dict,
            ideas: List[str], facts: str) -> Dict:
    """Ask the model for the next candidate playbook. Returns {"playbook", "changes"}."""
    from app.adapters.llm.llm import ask_json
    msg = ("Family: %s (this run: %s).\n\nCURRENT PLAYBOOK (v%s):\n%s\n\nTHIS RUN: %d ideas explored, %d dropped "
           "on research data (%s), %d reached the gate, %d passed.\n\nIDEAS AND VERDICTS:\n%s\n\n"
           "FEATURES AND MEASURED FACTS ON THIS MARKET'S RESEARCH WINDOW:\n%s"
           % (family, market_label, current.get("version", 0), current.get("text") or "(empty: no lessons yet)",
              card["explored"], card["dropped"],
              ", ".join("%s %d" % kv for kv in sorted(card["death_kinds"].items())) or "none",
              card["gated"], card["passed"], "\n".join(ideas) or "(none)", facts or "(none)"))
    return ask_json(model, REFLECT_SYSTEM, [{"role": "user", "content": msg}], _check, usage)


def add_candidate(cur, user_id: int, family: str, parent: Dict, text: str, changes: str,
                  run_id: Optional[int]) -> int:
    cur.execute("SELECT COALESCE(MAX(version), 0) AS v FROM app_rsi_playbooks WHERE user_id=%s AND family=%s",
                (user_id, family))
    version = int(cur.fetchone()["v"]) + 1
    cur.execute("INSERT INTO app_rsi_playbooks (user_id, family, version, parent_id, status, text, changes, "
                "source_run_id, created_at) VALUES (%s, %s, %s, %s, 'candidate', %s, %s, %s, %s)",
                (user_id, family, version, parent["id"], text, changes, run_id, _now()))
    return version


# A playbook line claiming the window lacks strikes or event grouping is false (the code window has
# both since #149); runs 2761/2772/2775 dropped sports ladder theses citing such a line. Strip it from
# what the proposer reads until the reflection rule above rewrites it away.
_FALSE_FACT = re.compile(
    r"\b(no|without|lacks?|missing|unavailable|absent)\b((?:\W+\w+){0,3}?)\W+"
    r"(strikes?|thresholds?|event context|event ids?|event identifiers?|game ids?|game identifiers?|team ids?)\b",
    re.I)
_NOT_A_DATA_CLAIM = re.compile(r"\b(edge|signal|bias|mispricing|value at|pattern)\b", re.I)


def _scrub(text: str) -> str:
    def false_fact(line: str) -> bool:
        return any(not _NOT_A_DATA_CLAIM.search(m.group(2)) for m in _FALSE_FACT.finditer(line))
    return "\n".join(line for line in text.splitlines() if not false_fact(line))


def prompt_block(pb: Optional[Dict], family: str) -> str:
    """The playbook as the proposer reads it ("" for the empty version 0)."""
    if not pb or not (pb.get("text") or "").strip():
        return ""
    pb = dict(pb, text=_scrub(pb["text"]))
    return ("RESEARCH PLAYBOOK v%s for %s markets: lessons this research loop learned from its own earlier "
            "runs on this family. Treat DEAD ENDS as settled unless you name what is different now, trust "
            "PIPELINE FACTS over your assumptions about the data, and prefer NEXT ANGLES. Where a line "
            "contradicts the Market profile, the profile is right:\n%s"
            % (pb["version"], family, pb["text"].strip()))


def summary(cur, user_id: int) -> List[Dict]:
    """Every family's active and candidate playbook with its record, for the scoreboard. A candidate
    carries p_better: the chance its gate-reach rate beats the incumbent's on the evidence so far."""
    cur.execute("SELECT %s FROM app_rsi_playbooks WHERE user_id=%%s AND status IN ('active','candidate') "
                "ORDER BY family, status" % _COLS, (user_id,))
    rows = list(cur.fetchall())
    for r in rows:
        ideas = int(r.get("ideas") or 0)
        r["reach_rate"] = round(int(r.get("reached") or 0) / ideas, 3) if ideas else None
        r["cost_usd"] = float(r.get("cost_usd") or 0)
    active_by_family = {r["family"]: r for r in rows if r["status"] == "active"}
    for r in rows:
        inc = active_by_family.get(r["family"])
        r["p_better"] = (round(p_better(r, inc), 2) if r["status"] == "candidate" and inc else None)
    return rows

