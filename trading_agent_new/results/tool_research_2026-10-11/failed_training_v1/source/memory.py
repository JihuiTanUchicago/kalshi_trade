"""Evidence-checked findings plus approved procedures, not self-certified prose."""
from __future__ import annotations

import json
import re
import uuid

from .common import GateError, canonical, digest, pointer, utcnow
from .store import Store


PROCEDURES = {
    "cost_attribution":"Compare matched cost-free controls before attributing gains to signal quality.",
    "notional_turnover":"Measure notional turnover separately from order counts.",
    "timing":"Use actual availability timestamps and challenge prefix/future invariance.",
    "retain_rejections":"Keep failed hypotheses and the complete preregistered trial register.",
    "borrow_costs":"Require historical borrow availability/fees and stress both transaction and borrow costs.",
    "exposure_control":"Compare exposures and a risky benchmark under identical accounting assumptions.",
    "operational_attribution":"Separate model errors, strategy failures, data failures, and execution discrepancies.",
    "uncertainty":"Report paired uncertainty and instability before advancing a candidate.",
}
TRUSTED_KINDS = {"experiment_result","challenge","decision","legacy_observation","operational_check","error_receipt"}


class Memory:
    def __init__(self, store: Store): self.store = store

    def add(self, evidence_hash: str, claims: list[dict], procedure: str, scope: dict,
            supersedes: str | None = None) -> str:
        if procedure not in PROCEDURES or not claims:
            raise GateError("Verified memory requires an approved procedure and evidence-backed facts")
        row = self.store.db.execute("SELECT kind FROM artifacts WHERE hash=?",(evidence_hash,)).fetchone()
        if not row or row[0] not in TRUSTED_KINDS:
            raise GateError("Memory evidence was not produced by a protected verifier")
        document = self.store.get(evidence_hash,row[0])
        if row[0] == "experiment_result" and not all(v["passed"] for v in document["verification"].values()):
            raise GateError("Unverified experiment metrics cannot enter verified memory")
        if row[0] in {"challenge","operational_check"} and document.get("passed") is not True:
            raise GateError("Failed verification supports error facts only")
        if scope.get("frequency") != "daily" or scope.get("market") != "US":
            raise GateError("Memory needs the explicit US/daily scope")
        quality = scope.get("quality")
        if quality not in {"synthetic","proxy","qualified","licensed_unqualified","operational"}:
            raise GateError("Memory must preserve source qualification")
        source = self.store.get(document["result"],"experiment_result") if row[0] == "decision" else document
        source_quality = source.get("qualification",{}).get("quality",source.get("quality"))
        if source_quality and source_quality != quality:
            raise GateError("Memory cannot upgrade the source's qualification")
        observations = []
        for claim in claims:
            if set(claim) != {"pointer","equals"}:
                raise GateError("V1 memory facts require exact JSON-pointer equality")
            actual = pointer(document,claim["pointer"])
            if canonical(actual) != canonical(claim["equals"]):
                raise GateError("Proposed memory fact is not supported by its evidence")
            if isinstance(actual,(list,dict)) or len(canonical(actual)) > 1000:
                raise GateError("Cite a specific scalar observation")
            observations.append(f"{claim['pointer']} = {canonical(actual)}")
        key = digest({"evidence":evidence_hash,"claims":claims,"procedure":procedure,"scope":scope})
        if self.store.db.execute("SELECT 1 FROM memory WHERE id=?",(key,)).fetchone(): return key
        payload = {"id":key,"evidence":evidence_hash,"claims":claims,"procedure":procedure,
                   "procedure_text":PROCEDURES[procedure],"observations":observations,"scope":scope,
                   "uncertainty":"An observation supports the scoped finding, not universal profitability.","created":utcnow()}
        with self.store.transaction():
            if supersedes:
                previous = self.store.db.execute("SELECT * FROM memory WHERE id=?",(supersedes,)).fetchone()
                if not previous or previous["status"] != "verified": raise GateError("Cannot supersede unknown/stale memory")
                previous_payload = json.loads(previous["payload"])
                if previous_payload["scope"] != scope or previous_payload["procedure"] != procedure:
                    raise GateError("Supersession requires identical scope/procedure")
                self.store.db.execute("UPDATE memory SET status='superseded',superseded_by=? WHERE id=?",(key,supersedes))
            self.store.db.execute("INSERT INTO memory VALUES(?,?,?,?,?)",(key,canonical(payload),"verified",None,utcnow()))
            self.store.db.execute("INSERT INTO memory_fts VALUES(?,?)",(key," ".join(observations)+" "+PROCEDURES[procedure]+" "+procedure))
        return key

    def retrieve(self, query: str, market="US", frequency="daily", limit=5, evidence_hashes=None) -> list[dict]:
        tokens = re.findall(r"[a-zA-Z0-9_]+",query)[:20]
        if not tokens: return []
        term = " OR ".join('"'+t+'"' for t in tokens)
        if evidence_hashes is not None:
            # Bound an explicit evidence scope before ranking, so older lessons
            # cannot crowd out the episode under a transfer check.
            candidates = []
            for row in self.store.db.execute("SELECT id,payload FROM memory WHERE status='verified'"):
                if json.loads(row["payload"])["evidence"] in evidence_hashes:
                    candidates.append(row["id"])
            if not candidates:return []
            placeholders = ",".join("?" for _ in candidates)
            query = "SELECT m.payload FROM memory_fts f JOIN memory m ON m.id=f.id WHERE memory_fts MATCH ? AND m.id IN ("+placeholders+") AND m.status='verified' ORDER BY bm25(memory_fts) LIMIT 50"
            rows = self.store.db.execute(query,(term,*candidates)).fetchall()
        else:
            rows = self.store.db.execute("""SELECT m.payload FROM memory_fts f JOIN memory m ON m.id=f.id
                  WHERE memory_fts MATCH ? AND m.status='verified' ORDER BY bm25(memory_fts) LIMIT 50""",(term,)).fetchall()
        result = []
        for row in rows:
            record = json.loads(row[0])
            if record["scope"]["market"] != market or record["scope"]["frequency"] != frequency: continue
            self.store.get(record["evidence"])
            # Contradictions are retained; retrieval carries the evidence/scope of
            # each finding instead of choosing the newest assertion as truth.
            record["conflicts"] = self.conflicts(record)
            result.append(record)
            if len(result) >= limit: break
        return result

    def conflicts(self, record: dict) -> list[str]:
        result = []
        for row in self.store.db.execute("SELECT payload FROM memory WHERE status='verified' AND id<>?",(record["id"],)):
            other = json.loads(row[0])
            if other["scope"] == record["scope"] and other["procedure"] == record["procedure"]:
                for a in record["claims"]:
                    for b in other["claims"]:
                        if a["pointer"] == b["pointer"] and canonical(a["equals"]) != canonical(b["equals"]):
                            result.append(other["id"])
        return sorted(set(result))

    def task_context(self, query, procedures=(), dataset_id=None, max_bytes=4000):
        from .memory_selection import checked_record, select_records
        records = [checked_record(self.store,json.loads(row[0])) for row in
                   self.store.db.execute("SELECT payload FROM memory WHERE status='verified' ORDER BY id")]
        return select_records(records,query,procedures,dataset_id,max_bytes)
