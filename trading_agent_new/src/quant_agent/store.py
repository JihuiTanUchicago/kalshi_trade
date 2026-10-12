"""Append-only, content-addressed evidence and resumable SQLite state."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any
import json
import sqlite3
import uuid
import shutil

from .common import GateError, canonical, digest, utcnow
from .contracts import STATES


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "state.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS artifacts(hash TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, goal TEXT NOT NULL, state TEXT NOT NULL,
            spec TEXT, strategy TEXT, result TEXT, challenge TEXT, decision TEXT, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT,
            kind TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS budgets(campaign TEXT PRIMARY KEY, cap REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY, campaign TEXT NOT NULL,
            amount REAL NOT NULL, actual REAL, status TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS memory(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
            status TEXT NOT NULL, superseded_by TEXT, created TEXT NOT NULL);
          CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, text);
          CREATE TABLE IF NOT EXISTS qualifications(dataset TEXT PRIMARY KEY, receipt TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY, payload TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
            broker_id INTEGER, perm_id INTEGER, filled INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY, intent_id TEXT NOT NULL, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS controls(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def close(self):
        self.db.close()

    def backup(self,destination: str | Path) -> dict:
        destination = Path(destination).resolve()
        if destination==self.root or destination.is_relative_to(self.root) or destination.exists():
            raise GateError("Backup needs a new directory outside the running store")
        destination.mkdir(parents=True)
        (destination/"artifacts").mkdir()
        backup_db = sqlite3.connect(destination/"state.sqlite3")
        try:
            self.db.backup(backup_db)
            keys = [r[0] for r in backup_db.execute("SELECT hash FROM artifacts")]
            for key in keys:
                self.get(key)
                target = destination/"artifacts"/f"{key}.json"
                shutil.copyfile(self.artifacts/f"{key}.json",target)
                target.chmod(0o444)
        finally: backup_db.close()
        return {"directory":str(destination),"artifacts":len(keys),"sqlite_consistent_backup":True,
                "external_licensed_inputs":"Back up separately under their data rights"}

    def put(self, kind: str, payload: Any) -> str:
        envelope = {"kind": kind, "payload": payload}
        key = digest(envelope)
        path = self.artifacts / f"{key}.json"
        if path.exists():
            if path.read_text() != canonical(envelope):
                raise GateError("Immutable artifact has been modified")
        else:
            # Exclusive creation prevents overwriting even on interrupted concurrent writes.
            try:
                with path.open("x") as stream:
                    stream.write(canonical(envelope))
            except FileExistsError:
                return self.put(kind, payload)
            path.chmod(0o444)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?)", (key, kind, utcnow()))
        return key

    def get(self, key: str, kind: str | None = None) -> Any:
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise GateError("Invalid evidence hash")
        path = self.artifacts / f"{key}.json"
        if not path.exists():
            raise GateError(f"Missing evidence: {key}")
        envelope = json.loads(path.read_text())
        if digest(envelope) != key or (kind is not None and envelope["kind"] != kind):
            raise GateError("Evidence hash/type verification failed")
        return envelope["payload"]

    def event(self, run_id: str | None, kind: str, payload: Any):
        with self.db:
            self.db.execute("INSERT INTO events(run_id,kind,payload,created) VALUES(?,?,?,?)",
                            (run_id, kind, canonical(payload), utcnow()))

    def new_run(self, goal: str) -> str:
        key = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO runs(id,goal,state,created) VALUES(?,?,?,?)",
                            (key, goal, "requested", utcnow()))
        self.event(key, "requested", {"goal": goal})
        return key

    def run(self, key: str) -> dict:
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (key,)).fetchone()
        if row is None:
            raise GateError("Unknown research run")
        return dict(row)

    def advance(self, key: str, expected: str, new_state: str, column: str | None = None, value: str | None = None):
        if expected not in STATES or STATES.index(new_state) != STATES.index(expected) + 1:
            raise GateError("Illegal workflow transition")
        if column not in {None, "spec", "strategy", "result", "challenge", "decision"}:
            raise GateError("Invalid workflow evidence column")
        with self.transaction():
            sql = "UPDATE runs SET state=?" + (f",{column}=?" if column else "") + " WHERE id=? AND state=?"
            args = [new_state] + ([value] if column else []) + [key, expected]
            if self.db.execute(sql, args).rowcount != 1:
                raise GateError("Run was already advanced or is in another state")
            self.db.execute("INSERT INTO events(run_id,kind,payload,created) VALUES(?,?,?,?)",
                            (key, new_state, canonical({"evidence": value}), utcnow()))

    def control(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM controls WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_control(self, key: str, value: Any):
        with self.db:
            self.db.execute("INSERT INTO controls VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, canonical(value)))
