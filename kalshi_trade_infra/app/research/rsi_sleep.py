"""Research RSI, part 3: a "sleep" step that consolidates what research has learned into durable,
compact memory, after the SLEEP framework (Behrouz et al. 2026, "Language Models Need Sleep",
arXiv 2606.03979): fast memory (context) is periodically consolidated into slow memory, and the slow
memory grows by expansion instead of being overwritten, so old knowledge isn't forgotten.

Our proposer is prompted, not fine-tuned, so the two memories are prompt text:

    fast  ── the recent-drops lists and rationing in agent.py (_dropped_block, _own_dead_block): the
             last ~10 runs per market, so a mechanism killed 20 times comes back once its drops age out
             (prod 2026-10-27 16:00Z to 10-28 03:00Z, BTC: 30% of drops were such re-kills, 16% fresh)
    slow  ── this module, one row per (user, family) and version:
             ledger   deterministic, never ages out: per market x mechanism, ideas tested, reached the
                      gate, passed, death tags, first/last day. Updated even when the model call fails.
             lessons  frozen once learned, like the paper's old weights: the model keeps each standing
                      lesson word for word, merges near-duplicates, or retires it with a stated
                      contradiction; new evidence goes into NEW lessons (check_merge). One run can't
                      rewrite what thirty taught (the playbook's failure mode).

    sleep()  after a run, once SLEEP_MIN_NEW new ideas have accumulated since the last consolidation
    prompt_block()  what the proposer reads: the ledger for its market, what is exhausted, what was never
                    tried, and the lessons

Leak-safe like the playbook: drop reasons are research-fold, and of a gated idea only its label
(reached / passed) is read; no validation or holdout number ever enters.
Kill switch: TAU_RSI_SLEEP=0 (no consolidation, no prompt block).
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

_LOG = logging.getLogger(__name__)

SLEEP_MIN_NEW = 40       # ideas since the last consolidation before the next one (~5 runs)
BOOTSTRAP_RUNS = 200     # the first sleep of a family reads this many recent runs
MAX_LESSONS = 16
LESSON_CHARS = 300
EXHAUSTED_MIN = 10       # tested this often on a market with nothing reaching the gate: exhausted
EVIDENCE_LINES = 80      # drop reasons shown to the consolidating model
_BY_DAY_KEEP = 30
# Run ids are global and two runs can be in flight at once, so a run that finishes after a newer one
# was consolidated sits below the cursor: each sleep re-reads this many ids below it and skips the
# ones already folded (ledger["seen"], the last _SEEN_KEEP run ids).
_REREAD_IDS = 60
_SEEN_KEEP = 400
BLOCK_CHARS = 8000   # ~2k tokens: 16 lessons x 300 chars + the folded ledger
KINDS = ("dead_end", "data_fact", "signal", "open_question")

DDL = [
    """
    CREATE TABLE IF NOT EXISTS app_rsi_knowledge (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      user_id BIGINT NOT NULL,
      family VARCHAR(48) NOT NULL,
      version INT NOT NULL,
      through_run_id BIGINT NOT NULL,       -- the newest research run consolidated into this version
      runs INT NOT NULL DEFAULT 0,          -- all runs consolidated so far (cumulative)
      ideas INT NOT NULL DEFAULT 0,
      ledger_json MEDIUMTEXT NOT NULL,
      lessons_json MEDIUMTEXT NOT NULL,
      changes TEXT NULL,
      created_at DATETIME NOT NULL,
      UNIQUE KEY uq_knowledge_version (user_id, family, version)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def enabled() -> bool:
    return os.getenv("TAU_RSI_SLEEP", "1").strip().lower() not in ("", "0", "false", "off", "no")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# -- the ledger (pure) ------------------------------------------------------------------------------

def outcome(ev: Dict) -> Optional[str]:
    """'dropped' | 'gated' | 'passed' | 'developed' for one idea's verdict event, None for anything
    else (holdout / forward / screen rows, which are not ideas). Labels only."""
    d = ev.get("data") or {}
    msg = ev.get("message") or ""
    if d.get("phase") in ("holdout", "forward", "screen", "leads"):
        return None
    if d.get("status") == "abandoned":
        return "dropped"
    if d.get("classification"):
        return "passed" if d.get("status") == "passed" else "gated"
    if "power" in d or msg.startswith("REJECTED (challenger)") or "not a finalist" in msg:
        return "developed"
    return None


def _title(ev: Dict) -> str:
    return str((ev.get("data") or {}).get("title") or "")


def fold(ledger: Dict, events: List[Dict]) -> Dict:
    """Add verdict events ({run_id, market, day, message, data}) to a ledger and return it.
    ledger = {"runs": n, "ideas": n, "since": day, "markets": {market: {mechanism: cell}}} with
    cell = {"tested", "gated", "passed", "tags": {tag: n}, "first", "last", "example", "by_day"}."""
    from app.research.rsi import classify_drop, mechanism
    led = json.loads(json.dumps(ledger or {}))   # never mutate the caller's copy
    led.setdefault("runs", 0)
    led.setdefault("ideas", 0)
    markets = led.setdefault("markets", {})
    runs = set()
    for ev in events:
        kind = outcome(ev)
        if kind is None:
            continue
        runs.add(ev.get("run_id"))
        day = ev.get("day") or ""
        mech = mechanism(_title(ev)) or "unbucketed"
        cell = markets.setdefault(ev.get("market") or "?", {}).setdefault(
            mech, {"tested": 0, "gated": 0, "passed": 0, "tags": {}, "first": day, "last": day, "example": "",
                   "by_day": {}})
        cell["tested"] += 1
        cell["gated"] += kind in ("gated", "passed")
        cell["passed"] += kind == "passed"
        if kind == "dropped":
            tag = classify_drop((ev.get("data") or {}).get("why") or ev.get("message"))[0]
            cell["tags"][tag] = cell["tags"].get(tag, 0) + 1
        cell["first"] = min(cell["first"] or day, day)
        cell["last"] = max(cell["last"] or day, day)
        cell["example"] = _title(ev)[:120] or cell["example"]
        cell["by_day"][day] = cell["by_day"].get(day, 0) + 1
        cell["by_day"] = dict(sorted(cell["by_day"].items())[-_BY_DAY_KEEP:])
        led["ideas"] += 1
        led["since"] = min(led.get("since") or day, day)
    led["runs"] += len(runs)
    led["seen"] = sorted(set(led.get("seen") or []) | {r for r in runs if r is not None})[-_SEEN_KEEP:]
    return led


def _cells(ledger: Dict, market: str) -> List[tuple]:
    cells = (ledger.get("markets") or {}).get(market) or {}
    return sorted(cells.items(), key=lambda kv: (-kv[1]["tested"], kv[0]))


def _tags(cell: Dict, n: int = 3) -> str:
    return ", ".join("%s %d" % kv for kv in sorted(cell["tags"].items(), key=lambda kv: -kv[1])[:n])


def ledger_lines(ledger: Dict, market: str) -> List[str]:
    """One line per mechanism tested on `market`, most tested first."""
    out = []
    for mech, c in _cells(ledger, market):
        out.append("- %s: %d tested, %d reached the gate%s, %s to %s%s" % (
            mech, c["tested"], c["gated"], (", %d passed" % c["passed"]) if c["passed"] else "",
            c["first"], c["last"], ("; died of " + _tags(c)) if c["tags"] else ""))
    return out


def exhausted(ledger: Dict, market: str, min_tested: int = EXHAUSTED_MIN) -> List[str]:
    """Named mechanisms tested at least min_tested times on `market` with nothing reaching the gate."""
    return [m for m, c in _cells(ledger, market)
            if m != "unbucketed" and c["tested"] >= min_tested and not c["gated"]]


def open_buckets(ledger: Dict, market: str, min_tested: int = EXHAUSTED_MIN) -> Optional[List[str]]:
    """None while `market` is live: something reached the gate there, or fewer than half the named
    mechanisms are exhausted. Otherwise the named mechanisms still tested under min_tested times,
    least tested first ([] = every one exhausted). Prod 2026-10-30: btc15m had 14 of 18 exhausted;
    the 4 left (contract age, moneyness band, settlement nowcast, tick rounding) had under 10 tests,
    because they came late to MECHANISMS and an idea lands in the first bucket its title matches."""
    from app.research.rsi import MECHANISMS
    names = list(dict.fromkeys(name for name, _ in MECHANISMS))
    cells = (ledger.get("markets") or {}).get(market) or {}
    if any(c.get("gated") for c in cells.values()):
        return None
    dead = set(exhausted(ledger, market, min_tested))
    if len(dead) * 2 < len(names):
        return None
    left = [n for n in names if n not in dead]
    return sorted(left, key=lambda n: ((cells.get(n) or {}).get("tested", 0), names.index(n)))


def market_exhausted(ledger: Dict, market: str, min_tested: int = EXHAUSTED_MIN) -> bool:
    """Every named mechanism tested at least min_tested times on `market`, none reaching the gate."""
    return open_buckets(ledger, market, min_tested) == []


def untried(ledger: Dict, market: str) -> List[tuple]:
    """(mechanism, times tested on sibling markets) for named mechanisms never tested on `market`."""
    from app.research.rsi import MECHANISMS
    here = (ledger.get("markets") or {}).get(market) or {}
    elsewhere: Dict[str, int] = defaultdict(int)
    for mk, cells in (ledger.get("markets") or {}).items():
        if mk != market:
            for mech, c in cells.items():
                elsewhere[mech] += c["tested"]
    return [(name, elsewhere.get(name, 0)) for name, _ in MECHANISMS if name not in here]


# -- the lessons (model-merged, append-or-retire) ----------------------------------------------------

CONSOLIDATE_SYSTEM = """You are the SLEEP step of an automated research loop on Kalshi prediction markets.
While awake, the loop proposes trading ideas and kills most of them on research data. Now you consolidate
what it learned into LONG-TERM LESSONS that every future proposal will read. Your job is retention: a
lesson learned from thirty runs must not be lost because the latest run didn't mention it.

You get the standing lessons (ids L1, L2, ...), the all-time ledger, and the reasons recent ideas died.
Standing lessons are FROZEN: you cannot reword one. For each standing lesson choose exactly one of:
- "keep": it stays word for word (you may raise its evidence count from the ledger);
- "merged": fold two or more near-duplicate standing lessons into one new lesson (list all their ids);
- "retired": the new evidence contradicts it; say what contradicts it. Never retire a lesson because it
  is old or unmentioned.
Everything the new evidence teaches goes into "new" lessons. At most %d lessons in total, each under %d
characters; when over the cap, merge the most closely related standing ones, never drop one.
- A lesson generalises across many ideas: WHY a class of ideas dies here (who is on the other side, what
  the data shows), what the data really contains, or what showed real signal. Not one idea's title.
- kind is one of: dead_end, data_fact, signal, open_question. "evidence" is about how many ideas back it
  (use the ledger counts; never invent numbers).
- A dead end can come back to life when NEW data exists (a feature or source added after the ideas died):
  say which data would reopen it when you know.
- An idea dropped because the proposer BELIEVED a feature was missing is a data_fact, not a dead end.
  [spec_invalid] drops are system bugs: ignore them.
- You see only research-window reasons and gate labels. Never invent validation or holdout numbers.
Reply with ONE JSON object: {"keep": [{"id": "L1", "evidence": N}], "merged": [{"from": ["L2", "L3"],
"text": "...", "kind": "...", "evidence": N}], "new": [{"text": "...", "kind": "...", "evidence": N}],
"retired": [{"id": "L4", "why": "..."}], "changes": "<one sentence: what changed>"}""" % (MAX_LESSONS, LESSON_CHARS)


def _ids(lessons: List[Dict]) -> List[str]:
    return ["L%d" % (i + 1) for i in range(len(lessons))]


def _lesson(item, where: str) -> Dict:
    if not isinstance(item, dict) or not str(item.get("text") or "").strip():
        raise ValueError("%s needs a non-empty 'text'" % where)
    kind = str(item.get("kind") or "dead_end")
    return {"text": " ".join(str(item["text"]).split())[:LESSON_CHARS], "kind": kind if kind in KINDS else "dead_end",
            "evidence": max(0, int(item.get("evidence") or 0))}


def check_merge(old: List[Dict]):
    """The ask_json check for a consolidation reply. Like SLEEP's parameter expansion (old weights frozen,
    new knowledge goes into new parameters): a standing lesson is kept word for word, merged with at least
    one other, or retired with a stated contradiction; it is never reworded or dropped silently."""
    by_id = dict(zip(_ids(old), old))

    def check(obj: Dict) -> Dict:
        seen: List[str] = []
        kept = []
        for k in obj.get("keep") or []:
            lid = str(k.get("id") if isinstance(k, dict) else k)
            if lid not in by_id:
                raise ValueError("keep names %s, which is not a standing lesson" % lid)
            seen.append(lid)
            ev = int(k.get("evidence") or 0) if isinstance(k, dict) else 0
            kept.append(dict(by_id[lid], evidence=max(int(by_id[lid].get("evidence") or 0), ev)))
        merged = []
        for i, m in enumerate(obj.get("merged") or []):
            src = [str(x) for x in ((m or {}).get("from") or []) if str(x)]
            if len(set(src)) < 2 or not set(src) <= set(by_id):
                raise ValueError("merged[%d] must fold two or more standing lessons (ids in 'from'); a standing "
                                 "lesson cannot be reworded alone: keep it, or add a new lesson" % i)
            seen += src
            merged.append(dict(_lesson(m, "merged[%d]" % i), since=min(int(by_id[x].get("since") or 0) for x in src)))
        new = [_lesson(n, "new[%d]" % i) for i, n in enumerate(obj.get("new") or [])]
        retired = []
        for r in obj.get("retired") or []:
            if isinstance(r, dict) and r.get("id") and str(r.get("why") or "").strip():
                seen.append(str(r["id"]))
                retired.append({"id": str(r["id"]), "why": str(r["why"])[:300]})
        missing = sorted(set(by_id) - set(seen), key=lambda s: int(s[1:]))
        if missing:
            raise ValueError("standing lessons %s are missing: keep, merge or retire (with the evidence that "
                             "contradicts it) each one" % ", ".join(missing))
        twice = sorted({x for x in seen if seen.count(x) > 1}, key=lambda s: int(s[1:]))
        if twice:
            raise ValueError("standing lessons %s are used more than once: each goes in exactly one of keep, "
                             "merged or retired" % ", ".join(twice))
        lessons = kept + merged + new
        if not lessons:
            raise ValueError("no lessons: keep the standing ones or add new ones")
        if len(lessons) > MAX_LESSONS:
            raise ValueError("%d lessons, at most %d: merge related standing lessons" % (len(lessons), MAX_LESSONS))
        return {"lessons": lessons, "new": len(new), "retired": retired,
                "changes": str(obj.get("changes") or "")[:500]}
    return check


def evidence_lines(events: List[Dict], limit: int = EVIDENCE_LINES) -> List[str]:
    """Newest drop reasons, at most 4 per (market, mechanism) so one bucket can't fill the list, plus
    every idea that reached the gate (label only)."""
    from app.research.rsi import classify_drop, mechanism
    out, per = [], defaultdict(int)
    for ev in reversed(events):
        kind = outcome(ev)
        d = ev.get("data") or {}
        if kind in ("gated", "passed"):
            out.append("- [%s] REACHED THE GATE (%s): %s" % (ev.get("market"), kind, _title(ev)[:120]))
        elif kind == "dropped":
            mech = mechanism(_title(ev)) or "unbucketed"
            key = (ev.get("market"), mech)
            if per[key] >= 4:
                continue
            per[key] += 1
            why = " ".join(str(d.get("why") or ev.get("message") or "").split())
            out.append("- [%s] [%s] %s: %s" % (ev.get("market"), classify_drop(why)[0], _title(ev)[:100], why[:260]))
        if len(out) >= limit:
            break
    return out


def _render_ledger(ledger: Dict) -> str:
    parts = []
    for market in sorted(ledger.get("markets") or {}):
        parts.append("%s:\n%s" % (market, "\n".join(ledger_lines(ledger, market))))
    return "\n".join(parts) or "(empty)"


def consolidate(model, usage, family: str, lessons: List[Dict], ledger: Dict, evidence: List[str]) -> Dict:
    """One sleep: the model merges the new evidence into the standing lessons. Returns check_merge's dict."""
    from app.adapters.llm.llm import ask_json
    standing = "\n".join("%s [%s, ~%d ideas] %s" % (i, l["kind"], l.get("evidence") or 0, l["text"])
                         for i, l in zip(_ids(lessons), lessons)) or "(none yet: this is the first sleep)"
    msg = ("Family: %s. All-time: %d runs, %d ideas since %s.\n\nSTANDING LESSONS:\n%s\n\nALL-TIME LEDGER "
           "(per market, per mechanism bucket of the idea's title):\n%s\n\nWHY RECENT IDEAS DIED (newest "
           "first, research data only):\n%s"
           % (family, ledger.get("runs", 0), ledger.get("ideas", 0), ledger.get("since") or "?", standing,
              _render_ledger(ledger)[:9000], "\n".join(evidence) or "(none)"))
    return ask_json(model, CONSOLIDATE_SYSTEM, [{"role": "user", "content": msg}], check_merge(lessons), usage)


# -- storage --------------------------------------------------------------------------------------

_COLS = "id, user_id, family, version, through_run_id, runs, ideas, ledger_json, lessons_json, changes, created_at"


def latest(cur, user_id: int, family: str) -> Optional[Dict]:
    cur.execute("SELECT %s FROM app_rsi_knowledge WHERE user_id=%%s AND family=%%s ORDER BY version DESC LIMIT 1"
                % _COLS, (user_id, family))
    row = cur.fetchone()
    if not row:
        return None
    row = dict(row)
    row["ledger"] = json.loads(row.pop("ledger_json") or "{}")
    row["lessons"] = json.loads(row.pop("lessons_json") or "[]")
    return row


def _save(cur, user_id: int, family: str, version: int, through: int, ledger: Dict, lessons: List[Dict],
          changes: str) -> None:
    cur.execute("INSERT INTO app_rsi_knowledge (user_id, family, version, through_run_id, runs, ideas, ledger_json, "
                "lessons_json, changes, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (user_id, family, version, through, int(ledger.get("runs") or 0), int(ledger.get("ideas") or 0),
                 json.dumps(ledger, separators=(",", ":")), json.dumps(lessons, separators=(",", ":")),
                 changes[:1000], _now()))


def sleep(cur, model, usage, user_id: int, family: str, markets: List[str], run_id: int,
          min_new: int = SLEEP_MIN_NEW) -> Optional[str]:
    """Consolidate this family's runs since the last sleep, once min_new new ideas have piled up.
    Returns a one-line account of what happened, or None when it isn't time yet. The ledger part is
    saved even when the model call fails (the lessons then carry over unchanged)."""
    from app import repository as repo
    prev = latest(cur, user_id, family)
    after = max(int(prev["through_run_id"]) - _REREAD_IDS, 0) if prev else 0
    seen = set((prev or {}).get("ledger", {}).get("seen") or [])
    events = [ev for ev in repo.research_verdicts_after(cur, user_id, markets, after, include_run_id=run_id,
                                                        max_runs=BOOTSTRAP_RUNS)
              if ev["run_id"] not in seen]
    ideas = [ev for ev in events if outcome(ev)]
    if not ideas or (prev and len(ideas) < min_new):
        return None
    ledger = fold(prev["ledger"] if prev else {}, events)
    lessons = list(prev["lessons"]) if prev else []
    through = max([int(ev["run_id"]) for ev in events] + [int(prev["through_run_id"]) if prev else 0])
    version = (int(prev["version"]) + 1) if prev else 1
    try:
        merged = consolidate(model, usage, family, lessons, ledger, evidence_lines(events))
        lessons, changes = [dict(l, since=l.get("since", version)) for l in merged["lessons"]], merged["changes"]
        if merged["retired"]:
            changes += " Retired: " + "; ".join("%s (%s)" % (r["id"], r["why"]) for r in merged["retired"])
    except Exception as e:  # noqa: BLE001 - the ledger alone is worth keeping; lessons carry over
        _LOG.warning("rsi sleep: lesson merge failed for %s/%s: %s", user_id, family, e)
        changes = "ledger only (lesson merge failed: %s)" % str(e)[:200]
    _save(cur, user_id, family, version, through, ledger, lessons, changes)
    return "memory v%d: %d new ideas from %d runs consolidated (%d all-time), %d lessons. %s" % (
        version, len(ideas), len({ev["run_id"] for ev in ideas}), ledger["ideas"], len(lessons), changes)


# -- what the proposer reads -------------------------------------------------------------------------

def render(know: Optional[Dict], market: str, family: str) -> str:
    """The proposer's LONG-TERM MEMORY block ("" before the first sleep). Exhausted mechanisms fold into
    one line so the lessons, the part a count can't say, always fit."""
    if not know or not know.get("ledger", {}).get("ideas"):
        return ""
    led = know["ledger"]
    cells = _cells(led, market)
    dead = exhausted(led, market)
    out = ["LONG-TERM RESEARCH MEMORY for %s markets (memory v%s, consolidated from %d runs and %d ideas since %s; "
           "unlike the recent lists above it never ages out). Research-data outcomes and gate labels only."
           % (family, know.get("version"), led.get("runs", 0), led.get("ideas", 0), led.get("since") or "?")]
    if cells:
        out.append("On %s: %d ideas tested, %d reached the gate." % (
            market, sum(c["tested"] for _, c in cells), sum(c["gated"] for _, c in cells)))
        out += ["- %s: %d tested, %d reached the gate%s, last %s%s" % (
                    m, c["tested"], c["gated"], (", %d passed" % c["passed"]) if c["passed"] else "", c["last"],
                    ("; died of " + _tags(c, 2)) if c["tags"] else "")
                for m, c in cells if m not in dead]
    if dead:
        by = dict(cells)
        out.append("EXHAUSTED on %s (%d+ ideas each, none reached the gate): %s. Do not propose these again unless "
                   "you name new data (a feature or source added after its last test) or a structurally different "
                   "trade, and say which." % (market, EXHAUSTED_MIN, "; ".join(
                       "%s (%d, last %s)" % (m, by[m]["tested"], by[m]["last"]) for m in dead)))
    fresh = untried(led, market)
    if fresh:
        out.append("NEVER TESTED on %s: %s." % (market, "; ".join(
            "%s (%s)" % (m, ("tested %d times on sibling markets" % n) if n else "untested anywhere") for m, n in fresh)))
    elif cells:
        out.append("Every named mechanism bucket has been tested on %s. The unexplored ground is ideas that fit "
                   "none of them: say what is new about yours." % market)
    lessons = know.get("lessons") or []
    if lessons:
        out.append("Lessons consolidated across runs (trust these over a single run's impression):")
        out += ["- [%s, ~%d ideas] %s" % (l.get("kind"), l.get("evidence") or 0, l.get("text")) for l in lessons]
    text = "\n".join(out)
    return text if len(text) <= BLOCK_CHARS else text[:BLOCK_CHARS].rsplit("\n", 1)[0]


def prompt_block(cur, user_id: int, family: str, market: str) -> str:
    if not enabled():
        return ""
    return render(latest(cur, user_id, family), market, family)
