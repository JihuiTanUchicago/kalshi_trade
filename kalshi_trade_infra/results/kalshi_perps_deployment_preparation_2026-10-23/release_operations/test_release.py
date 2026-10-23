"""Offline state/lock/rollback/transport contracts. No production or provider I/O."""
import base64
import copy
import io
import json
from pathlib import Path
import socket
import subprocess
import stat
import tarfile
import tempfile
import time
import unittest
from unittest.mock import Mock, mock_open, patch
import zlib

import release_database as db
import release_schema as schema
import remote
import runner
import collect


HERE = Path(__file__).resolve().parent
ZERO = {"queued": 0, "running": 0, "paused": 0}


def projection(**changes):
    return {"job_counts": dict(ZERO), "tables_present": dict.fromkeys(db.TABLES, True),
            "proposal_kind_width": 32, "enabled_policy_count": 0, "native_order_count": 0, **changes}


class Cursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, sql, args=None):
        self.conn.sql.append((sql, args))
        if self.conn.closed and "CONNECTION_ID()" in sql:
            raise RuntimeError("synthetic disconnected session")
        if sql.startswith("LOCK TABLES"):
            if self.conn.deny:
                raise RuntimeError("private permissions text")
            self.conn.locked = True
        elif sql == "UNLOCK TABLES":
            self.conn.locked = False
        elif "CONNECTION_ID()" in sql:
            self.rows = [{"id": self.conn.identifier}]
        elif "GROUP BY status" in sql:
            self.rows = [{"status": k, "n": v} for k, v in self.conn.counts.items()]
        elif "COUNT(*) AS n FROM app_kalshi" in sql:
            self.rows = [{"n": self.conn.native_rows}]
        else:
            self.rows = []
    def fetchall(self):
        return self.rows
    def fetchone(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, *, counts=None, native_rows=0, deny=False):
        self.counts, self.native_rows, self.deny = dict(ZERO if counts is None else counts), native_rows, deny
        self.sql, self.locked, self.closed, self.identifier, self.pings = [], False, False, 123, []
    def cursor(self):
        return Cursor(self)
    def ping(self, *, reconnect):
        self.pings.append(reconnect)
        if self.closed:
            raise RuntimeError("private connection text")
    def close(self):
        self.closed, self.locked = True, False


class DatabaseTests(unittest.TestCase):
    def test_all_kind_aggregates_have_no_research_filter_or_row_details(self):
        conn = Connection(counts={"queued": 3, "running": 2, "paused": 1})
        self.assertEqual(db.counts(conn), conn.counts)
        statement = conn.sql[0][0]
        self.assertNotIn("kind", statement)
        self.assertNotIn("user_id", statement)
        self.assertNotIn("prompt", statement)

    def test_lock_acquires_all_three_tables_before_fresh_count_and_never_reconnects(self):
        conn, clock = Connection(), [1.0]
        lock = db.AdmissionLock(conn, clock=lambda: clock[0])
        self.assertEqual(lock.acquire(), ZERO)
        sql = [q for q, args in conn.sql]
        acquisition = next(q for q in sql if q.startswith("LOCK TABLES"))
        self.assertEqual(acquisition, "LOCK TABLES app_agent_runs WRITE, app_kalshi_perps_settings WRITE, app_kalshi_perps_orders WRITE")
        self.assertLess(sql.index("SET autocommit=0"), sql.index(acquisition))
        self.assertLess(sql.index(acquisition), next(i for i, q in enumerate(sql) if "GROUP BY status" in q))
        lock.check()
        self.assertEqual(conn.pings, [False])
        self.assertFalse(any(q.startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "GRANT", "START TRANSACTION")) for q in sql))
        lock.close()
        self.assertTrue(conn.closed)
        self.assertEqual(conn.sql[-1][0], "UNLOCK TABLES")

    def test_busy_race_under_lock_releases_without_any_service_or_job_change(self):
        for status in ZERO:
            with self.subTest(status=status):
                conn = Connection(counts={**ZERO, status: 1})
                lock = db.AdmissionLock(conn)
                self.assertEqual(lock.acquire()[status], 1)
                self.assertFalse(conn.locked)
                lock.close()

    def test_native_policy_or_order_rows_block_initial_activation(self):
        for size in (1, -1, "1"):
            with self.subTest(size=size):
                conn = Connection(native_rows=size)
                lock = db.AdmissionLock(conn)
                with self.assertRaisesRegex(db.DatabaseError, "native_state_requires_review"):
                    lock.acquire()
                self.assertFalse(conn.locked)
                lock.close()

    def test_missing_privilege_does_not_grant_or_fallback(self):
        conn = Connection(deny=True)
        lock = db.AdmissionLock(conn)
        with self.assertRaises(RuntimeError):
            lock.acquire()
        lock.close()
        self.assertTrue(conn.closed)
        self.assertFalse(any("GRANT" in q or "UNLOCK" in q for q, args in conn.sql))

    def test_changed_connection_lost_connection_or_deadline_cannot_pass(self):
        for failure in ("changed", "lost", "deadline"):
            with self.subTest(failure=failure):
                conn, now = Connection(), [1.0]
                lock = db.AdmissionLock(conn, seconds=10, clock=lambda: now[0])
                lock.acquire()
                if failure == "changed":
                    conn.identifier += 1
                elif failure == "lost":
                    conn.closed = True
                else:
                    now[0] = 12
                with self.assertRaises((db.DatabaseError, RuntimeError)):
                    lock.check()
                self.assertTrue(all(value is False for value in conn.pings))
                lock.close()

    def test_query_that_returns_after_deadline_cannot_authorize_a_mutation(self):
        conn, now = Connection(), [1.0]
        lock = db.AdmissionLock(conn, seconds=10, clock=lambda: now[0])
        lock.acquire()
        execute = Cursor.execute
        def delayed(cursor, sql, args=None):
            execute(cursor, sql, args)
            if "CONNECTION_ID()" in sql:
                now[0] = 12.0
        with patch.object(Cursor, "execute", delayed):
            with self.assertRaisesRegex(db.DatabaseError, "admission_deadline_or_lock_unavailable"):
                lock.check()
        self.assertTrue(conn.locked)
        lock.close()

    def test_admission_socket_bounds_match_the_recovery_proof_budget(self):
        factory = Mock(return_value=object())
        env = dict.fromkeys(("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"), "synthetic")
        db.connect(env, factory, admission=True)
        self.assertEqual(factory.call_args.kwargs["read_timeout"], 0.5)
        self.assertEqual(factory.call_args.kwargs["write_timeout"], 0.5)
        self.assertTrue(factory.call_args.kwargs["autocommit"])

    def test_full_schema_requires_native_tables_wide_proposals_and_no_existing_live_state(self):
        db.require_schema(projection())
        invalid = [projection(proposal_kind_width=12), projection(proposal_kind_width=None),
                   projection(proposal_kind_width="32"), projection(enabled_policy_count=1), projection(native_order_count=1)]
        for name in db.TABLES:
            invalid.append(projection(tables_present={**dict.fromkeys(db.TABLES, True), name: False}))
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaisesRegex(db.DatabaseError, "full_schema_not_converged"):
                    db.require_schema(value)


class FakeBarrier:
    def __init__(self, backend):
        self.backend, self.lost = backend, False
    def acquire(self):
        self.backend.events.append("lock")
        self.deadline = time.monotonic() + remote.LOCK_SECONDS
        return self.backend.lock_counts
    def check(self):
        if self.lost:
            raise db.DatabaseError("admission_connection_changed")
    def close(self):
        self.backend.events.append("unlock")


class FakeBackend:
    def __init__(self, pins, root):
        self.pins, self.events, self.fail = pins, [], None
        self.state = copy.deepcopy(pins["installed"])
        self.current = copy.deepcopy(remote.source_files(self.state))
        self.planned = {}
        for name, row in pins["candidate_files"].items():
            prior = self.current.get(name, {"uid": 0, "gid": 0})
            self.planned[name] = {**row, "uid": prior["uid"], "gid": prior["gid"]}
        for name in pins["preserved_extra_paths"]:
            self.planned[name] = self.current[name]
        self.candidate_source = copy.deepcopy(self.planned)
        self.lock_counts, self.active_counts, self.schema_ok = dict(ZERO), dict(ZERO), True
        self.live, self.started, self.loss_after_start = False, False, False
        self.barrier = FakeBarrier(self)
        self.private = {name: {"APP_SECRET_KEY": "synthetic-private-secret", "APP_LIVE_TRADING_ENABLED": "0",
                              "TAU_KALSHI_PERPS_ENABLED": "0"} for name in remote.SERVICES}
        self.root = root
        self.guard = type("Guard", (), {"read_regular": staticmethod(self.read_regular)})()

    def read_regular(self, path, *args, **kwargs):
        if Path(path).name == "prepared.json":
            return Path(path).read_bytes(), {"uid": 0, "gid": 0, "mode": "0600"}
        return remote.ENV_CONTENT, {"uid": 0, "gid": 0, "mode": "0600"}

    def snapshot(self):
        result, private = copy.deepcopy(self.state), copy.deepcopy(self.private)
        result["source"]["files"] = copy.deepcopy(self.current)
        if self.live:
            for path in remote.DROPINS:
                result["controls"]["unit_files"][str(path)] = {"sha256": remote.digest(remote.DROPIN_CONTENT), "uid": 0, "gid": 0, "mode": "0600"}
        if self.started:
            for name in remote.SERVICES:
                result["controls"]["units"][name]["pid"] += 1000
                if self.live:
                    private[name].update(TAU_KALSHI_PERPS_LIVE_ENABLED="1", TAU_KALSHI_PERPS_LIVE_ENVIRONMENT="production")
        return result, private

    def inspect(self, env):
        return projection(job_counts=self.active_counts, proposal_kind_width=32 if self.schema_ok else 12)

    def stage(self, release_id, raw, state):
        self.events.append("stage")
        path = remote.directory(release_id) / "candidate"
        path.mkdir(mode=0o700, parents=True)
        return path, self.planned

    def validate(self, candidate, env):
        self.events.append("compile-imports")

    def migrate(self, candidate, env):
        self.events.append("full-schema")

    def scan_candidate(self, candidate):
        return copy.deepcopy(self.current if candidate == remote.ROOT else self.candidate_source)

    def lock(self, env):
        return self.barrier

    def stop(self):
        self.events.append("stop-web-agents")
        self.started = False
        if self.fail == "stop":
            self.fail = None
            raise remote.ReleaseError("service_operation_failed")

    def start(self):
        self.events.append("start-web-agents")
        self.started = True
        if self.loss_after_start:
            self.barrier.lost = True
        if self.fail == "start":
            self.fail = None
            raise remote.ReleaseError("service_operation_failed")

    def swap(self, candidate, packages):
        for package in packages:
            self.events.append("swap-" + package)
            if self.fail == "swap-" + package:
                self.fail = None
                raise remote.ReleaseError("atomic_exchange_failed")
            prefix = package + "/"
            old = {p: v for p, v in self.current.items() if p.startswith(prefix)}
            new = {p: v for p, v in self.candidate_source.items() if p.startswith(prefix)}
            self.current = {p: v for p, v in self.current.items() if not p.startswith(prefix)}
            self.current.update(new)
            self.candidate_source = {p: v for p, v in self.candidate_source.items() if not p.startswith(prefix)}
            self.candidate_source.update(old)

    def flags(self, created, *, check):
        self.events.append("new-flags-only")
        self.live = True
        created.append("synthetic-created-directory")
        if self.fail == "flags":
            self.fail = None
            raise remote.ReleaseError("synthetic_flag_failure")

    def remove_flags(self, created, *, check):
        self.events.append("remove-new-flags")
        self.live = False

    def original_controls(self, state):
        self.events.append("check-original-controls")
        if self.fail == "control-drift":
            raise remote.ReleaseError("protected_control_changed_before_rollback")

    def verify(self, pins, release_id, check):
        self.events.append("local-public-hashes-and-401")
        check()
        if self.fail in ("verify", "control-drift"):
            if self.fail == "verify":
                self.fail = None
            raise remote.ReleaseError("http_asset_hash_mismatch")


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = []
        for target, value in [("RELEASES", self.root), ("ENV_PATH", self.root / "new-env"),
                              ("DROPINS", (self.root / "web.conf", self.root / "agents.conf"))]:
            item = patch.object(remote, target, value); item.start(); self.stack.append(item)
        item = patch.object(remote, "safe_directory", lambda *a, **kw: None); item.start(); self.stack.append(item)
        item = patch.object(remote, "fixed_file", lambda path, raw, **kw: path.write_bytes(raw)); item.start(); self.stack.append(item)
        item = patch.object(remote, "http_read", lambda *a, **kw: b'{}'); item.start(); self.stack.append(item)
        item = patch.object(remote, "worker_health", lambda: {"status": "synthetic"}); item.start(); self.stack.append(item)
        item = patch.object(remote, "memory_pressure", lambda: {"status": "synthetic"}); item.start(); self.stack.append(item)
        self.pins = runner.pins()
        self.pins["candidate_ready"] = True  # Synthetic backend; no production acceptance is exercised.
        self.backend = FakeBackend(self.pins, self.root)
        self.release_id = "a" * 32

    def tearDown(self):
        for item in reversed(self.stack):
            item.stop()
        self.temp.cleanup()

    def prepare(self):
        return remote.prepare(self.backend, self.pins, self.release_id, b"synthetic", sleep=lambda seconds: self.backend.events.append("idle-30s"))

    def test_every_busy_status_and_every_control_source_conflict_is_inventory_only(self):
        for status in ZERO:
            with self.subTest(status=status):
                self.backend.active_counts = {**ZERO, status: 1}
                self.assertEqual(self.prepare()["status"], "waiting")
                self.assertEqual(self.backend.events, [])
        self.backend.active_counts = dict(ZERO)
        for kind in ("units", "unit_files", "processes", "protected_config"):
            original = copy.deepcopy(self.backend.state)
            self.backend.state["controls"][kind]["unexpected"] = {}
            self.assertEqual(self.prepare()["status"], "waiting")
            self.assertEqual(self.backend.events, [])
            self.backend.state = original
        self.backend.current["app/agent.py"]["sha256"] = "0" * 64
        self.assertEqual(self.prepare()["status"], "waiting")
        self.assertEqual(self.backend.events, [])

    def test_work_arriving_during_quiescence_prevents_stage_and_schema(self):
        def arrive(seconds):
            self.backend.active_counts["queued"] = 1
        report = remote.prepare(self.backend, self.pins, self.release_id, b"synthetic", sleep=arrive)
        self.assertEqual(report["status"], "waiting")
        self.assertEqual(self.backend.events, [])

    def test_inventory_reports_only_safe_unit_and_process_projection_for_drift_review(self):
        self.backend.active_counts = {**ZERO, "running": 1}
        report, state, private = remote.inventory(self.backend, self.pins)
        self.assertEqual(report["observed_units"], state["controls"]["units"])
        self.assertEqual(report["observed_processes"], state["controls"]["processes"])
        self.assertEqual(report["status"], "waiting")
        self.assertNotIn("synthetic-private-secret", json.dumps(report))
        self.assertNotIn("APP_SECRET_KEY", json.dumps(report))
        self.assertNotIn("protected_config", report)
        self.assertEqual(self.backend.events, [])

    def test_schema_and_compilation_precede_lock_and_any_service_operation(self):
        self.assertEqual(self.prepare()["status"], "prepared")
        result = remote.apply(self.backend, self.pins, self.release_id)
        self.assertEqual(result["status"], "installed_verified")
        self.assertTrue(result["admission_released"])
        events = self.backend.events
        self.assertLess(events.index("idle-30s"), events.index("stage"))
        self.assertLess(events.index("full-schema"), events.index("lock"))
        self.assertLess(events.index("lock"), events.index("stop-web-agents"))
        self.assertLess(events.index("local-public-hashes-and-401"), events.index("unlock"))
        self.assertEqual(self.backend.current, self.backend.planned)
        self.assertNotIn("engine", " ".join(events))
        self.assertNotIn("synthetic-private-secret", json.dumps(result))

    def test_busy_race_at_final_locked_count_never_stops_or_installs(self):
        self.prepare()
        self.backend.lock_counts["running"] = 1
        result = remote.apply(self.backend, self.pins, self.release_id)
        self.assertEqual(result["status"], "waiting")
        self.assertNotIn("stop-web-agents", self.backend.events)
        self.assertEqual(self.backend.events[-1], "unlock")

    def test_every_partial_stage_failure_rolls_back_while_admission_is_still_held(self):
        for index, failure in enumerate(("stop", "swap-app", "swap-data_pipeline", "flags", "start", "verify")):
            with self.subTest(failure=failure):
                identity = format(index, "032x")
                self.release_id = identity
                self.backend = FakeBackend(self.pins, self.root)
                self.prepare()
                self.backend.fail = failure
                result = remote.apply(self.backend, self.pins, self.release_id)
                self.assertEqual(result["status"], "rolled_back", result)
                self.assertTrue(result["rollback_performed"])
                self.assertFalse(result["schema_rolled_back"])
                self.assertEqual(self.backend.current, remote.source_files(self.pins["installed"]))
                self.assertFalse(self.backend.live)
                self.assertEqual(self.backend.events[-1], "unlock")
                import shutil
                shutil.rmtree(remote.directory(self.release_id))

    def test_lock_loss_does_not_restart_or_reconnect_or_claim_accepted_release(self):
        self.prepare()
        self.backend.loss_after_start = True
        report = remote.apply(self.backend, self.pins, self.release_id)
        self.assertEqual(report["status"], "recovery_requires_inspection")
        self.assertFalse(report["automatic_recovery_safe"])
        self.assertEqual(self.backend.events.count("start-web-agents"), 1)
        self.assertEqual(self.backend.events.count("stop-web-agents"), 1)
        self.assertTrue(report["backup_retained"])

    def test_control_drift_before_rollback_preserves_both_versions_and_stops_recovery(self):
        self.prepare()
        self.backend.fail = "control-drift"
        report = remote.apply(self.backend, self.pins, self.release_id)
        self.assertEqual(report["status"], "recovery_requires_inspection")
        self.assertFalse(report["rollback_performed"])
        self.assertEqual(self.backend.current, self.backend.planned)
        self.assertEqual(self.backend.events[-1], "unlock")

    def test_width_failure_or_existing_native_state_prevents_any_stop(self):
        self.backend.schema_ok = False
        with self.assertRaisesRegex(db.DatabaseError, "full_schema_not_converged"):
            self.prepare()
        self.assertNotIn("stop-web-agents", self.backend.events)

    def test_post_lock_inventory_time_reduces_forward_budget_before_any_stop(self):
        self.prepare()
        now = [0.0]
        original = self.backend.barrier.acquire
        def delayed_acquisition():
            value = original()
            now[0] += remote.LOCK_SECONDS - sum(remote.RECOVERY_BUDGET.values()) - remote.FORWARD_IO_OVERRUN - 5
            return value
        with patch.object(remote.time, "monotonic", lambda: now[0]), \
                patch.object(self.backend.barrier, "acquire", delayed_acquisition):
            result = remote.apply(self.backend, self.pins, self.release_id)
        self.assertEqual(result["status"], "failed_before_service_change")
        self.assertEqual(result["error_code"], "apply_deadline_exceeded")
        self.assertNotIn("stop-web-agents", self.backend.events)
        self.assertEqual(self.backend.events[-1], "unlock")

    def test_loss_after_each_recovery_boundary_stops_before_another_mutation(self):
        for index, boundary in enumerate(("stop", "original_controls", "remove_flags", "swap", "start", "snapshot", "health")):
            with self.subTest(boundary=boundary):
                self.release_id = format(index + 100, "032x")
                self.backend = FakeBackend(self.pins, self.root)
                self.prepare()
                self.backend.fail = "verify"
                calls, at_loss = [0], []
                target = "http_read" if boundary == "health" else boundary
                owner = remote if boundary == "health" else self.backend
                original = getattr(owner, target)
                occurrence = {"stop": 2, "swap": 3, "start": 2, "snapshot": 4}.get(boundary, 1)
                def lose_after(*args, **kwargs):
                    value = original(*args, **kwargs)
                    calls[0] += 1
                    if calls[0] == occurrence:
                        self.backend.barrier.lost = True
                        at_loss[:] = self.backend.events
                    return value
                with patch.object(owner, target, side_effect=lose_after):
                    result = remote.apply(self.backend, self.pins, self.release_id)
                self.assertTrue(at_loss, boundary)
                self.assertEqual(result["status"], "recovery_requires_inspection")
                self.assertFalse(result["rollback_performed"])
                self.assertEqual(self.backend.events[len(at_loss):], ["unlock"])


class SchemaAndTransportTests(unittest.TestCase):
    def test_admission_and_transport_budgets_leave_bounded_recovery_and_cleanup_time(self):
        self.assertEqual((remote.LOCK_SECONDS, remote.FORWARD_SECONDS), (120, 30))
        self.assertGreaterEqual(remote.RECOVERY_BUDGET["sql_proofs"], 28)
        self.assertLessEqual(remote.FORWARD_SECONDS + remote.FORWARD_IO_OVERRUN + sum(remote.RECOVERY_BUDGET.values()), remote.LOCK_SECONDS)
        source = (HERE / "runner.py").read_text()
        self.assertIn('"480" if phase == "prepare" else "420" if phase == "apply" else "180"', source)
        self.assertIn('540 if phase == "prepare" else 480 if phase == "apply" else 240', source)
        workflow = (runner.REPO / ".github/workflows/deploy.yml").read_text()
        self.assertIn("timeout-minutes: 30", workflow)
        self.assertLessEqual(540 + 480 + 2 * 180 + 360, 30 * 60)

    def test_full_candidate_schema_child_is_fixed_quiet_and_uses_candidate_cwd(self):
        for migrate in (False, True):
            code = schema.program(Path("/synthetic/candidate"), migrate=migrate)
            compile(code, "schema-child", "exec")
            self.assertIn("os.dup2(quiet,1);os.dup2(quiet,2)", code)
            self.assertIn("schema.main()", code)
            self.assertIn("lock_wait_timeout=3, innodb_lock_wait_timeout=3", code)
            self.assertIn('kw.update(connect_timeout=3,read_timeout=30,write_timeout=30', code)
            self.assertIn("WrongSchemaSource", code)
            output = {"ok": True, "stage": "full_schema" if migrate else "imports", "exception_class": None, "mysql_code": None}
            fake = subprocess.CompletedProcess([], 0, json.dumps(output).encode(), b"private raw body")
            with patch.object(schema.subprocess, "run", return_value=fake) as call:
                env = {"MYSQL_HOST": "synthetic", "MYSQL_PASSWORD": "private", "APP_SECRET_KEY": "private-key",
                       "PROD_KEYID": "must-not-inherit", "AWS_SECRET_ACCESS_KEY": "must-not-inherit"}
                self.assertTrue(schema.run("/python", Path("/synthetic/candidate"), env, migrate=migrate)["ok"])
                kwargs = call.call_args.kwargs
                self.assertEqual(kwargs["cwd"], Path("/synthetic/candidate"))
                self.assertNotIn("PROD_KEYID", kwargs["env"])
                self.assertNotIn("AWS_SECRET_ACCESS_KEY", kwargs["env"])
                self.assertEqual(call.call_args.args[0][1:3], ["-I", "-B"])

    def test_schema_errors_preserve_only_class_and_numeric_code(self):
        report = {"ok": False, "stage": "full_schema", "exception_class": "DataError", "mysql_code": 1406}
        fake = subprocess.CompletedProcess([], 1, json.dumps(report).encode(), b"private account/key body")
        with patch.object(schema.subprocess, "run", return_value=fake):
            with self.assertRaises(schema.SchemaError) as caught:
                schema.run("/python", Path("/candidate"), {}, migrate=True)
        self.assertEqual(caught.exception.details, report)
        self.assertNotIn("private", repr(caught.exception.details))
        fake.stdout = b"private unstructured exception"
        with patch.object(schema.subprocess, "run", return_value=fake):
            with self.assertRaisesRegex(schema.SchemaError, "schema_or_validation_failed"):
                schema.run("/python", Path("/candidate"), {}, migrate=True)

    def test_new_flag_file_and_dropins_contain_only_the_two_authorized_native_values(self):
        self.assertEqual(remote.ENV_CONTENT, b"TAU_KALSHI_PERPS_LIVE_ENABLED=1\nTAU_KALSHI_PERPS_LIVE_ENVIRONMENT=production\n")
        self.assertEqual(remote.DROPIN_CONTENT, b"[Service]\nEnvironmentFile=/etc/tau/kalshi-perps-live/live.env\n")
        self.assertEqual(remote.SERVICES, ("recursive-web", "recursive-agents"))
        for forbidden in (b"APP_LIVE_TRADING_ENABLED", b"APP_SECRET_KEY", b"TAU_KALSHI_PERPS_ENABLED", b"MemoryMax"):
            self.assertNotIn(forbidden, remote.ENV_CONTENT + remote.DROPIN_CONTENT)

    def test_real_candidate_archive_is_complete_pinned_and_keeps_three_installed_extras(self):
        pins = runner.pins()
        raw = runner.bundle(pins)
        value = json.loads(raw)
        archive = base64.b64decode(value["archive"])
        files = remote.archive_files(archive, pins)
        self.assertEqual(len(files), len(pins["candidate_files"]))
        self.assertEqual(len(pins["preserved_extra_paths"]), 3)
        self.assertTrue(all(name.startswith("data_pipeline/research_") for name in pins["preserved_extra_paths"]))
        self.assertIs(type(pins["candidate_ready"]), bool)

    def test_unaccepted_candidate_refuses_apply_before_aws_or_upload(self):
        rejected = runner.pins()
        rejected["candidate_ready"] = False
        with patch.object(runner, "aws") as aws, patch.object(runner, "pins", return_value=rejected):
            with self.assertRaisesRegex(runner.RunnerError, "candidate_acceptance_gate_closed"):
                runner.run("apply", "0" * 40, "0" * 64)
            aws.assert_not_called()

    def test_candidate_tree_and_reviewed_main_ref_cannot_silently_change(self):
        value = runner.pins()
        wrong_tree = copy.deepcopy(value)
        wrong_tree["acceptance"]["source_tree"] = "0" * 40
        with self.assertRaisesRegex(runner.RunnerError, "candidate_tree_mismatch"):
            runner.bundle(wrong_tree)
        actual_git = runner.git
        def changed_main(*args):
            return b"0" * 40 if args == ("rev-parse", "refs/remotes/origin/main") else actual_git(*args)
        with patch.object(runner, "git", side_effect=changed_main), patch.object(runner, "aws") as aws:
            with self.assertRaisesRegex(runner.RunnerError, "reviewed_main_reference_changed"):
                runner.run("apply", value["candidate"], value["installed_fingerprint"])
        aws.assert_not_called()

    def test_remote_program_uses_fixed_transport_quiet_fds_and_no_shell_env_loading(self):
        artifact = {"bucket": runner.BUCKET, "key": "bundle/manual-perps-" + "a" * 40 + "-" + "b" * 32 + ".json", "sha256": "c" * 64}
        code = runner.program(artifact, "inventory", "d" * 32)
        self.assertIn(" -I -B -c ", code)
        self.assertIn("os.dup2(quiet,1);os.dup2(quiet,2)", code)
        self.assertNotIn("source /", code)
        self.assertNotIn(".env.aws", code)
        with self.assertRaises(runner.RunnerError):
            runner.program({**artifact, "bucket": "other"}, "apply", "d" * 32)

    def test_compressed_receipts_reject_bad_hash_and_raw_log_text(self):
        raw = b'{"status":"waiting","job_counts":{"running":1}}'
        envelope = {"encoding": "zlib+base64", "sha256": remote.digest(raw), "payload": base64.b64encode(zlib.compress(raw)).decode()}
        self.assertEqual(runner.decode(json.dumps(envelope))["status"], "waiting")
        with self.assertRaises(runner.RunnerError):
            runner.decode(json.dumps({**envelope, "sha256": "0" * 64}))
        with self.assertRaises(Exception):
            runner.decode("private raw stdout")

    def test_collector_discards_unmarked_raw_logs(self):
        records = collect.records('private key body\n2026-10-23 TAU_PERPS_RELEASE_APPLY={"status":"waiting"}\nprivate env\n')
        self.assertEqual(records, [{"type": "APPLY", "receipt": {"status": "waiting"}}])
        self.assertNotIn("private", json.dumps(records))

    def test_public_checks_use_only_fixed_unauthenticated_hosts_and_get(self):
        with self.assertRaisesRegex(remote.ReleaseError, "http_host_not_fixed"):
            remote.http_read("https://api.elections.kalshi.com", "/portfolio")
        source = (HERE / "remote.py").read_text()
        self.assertNotIn('"POST"', source)
        self.assertNotIn("/margin/", source)
        self.assertNotIn("submit_order", source)
        self.assertNotIn("place_limit_order", source)
        self.assertNotIn("systemctl\", \"restart", source)

    def test_post_unlock_public_failure_never_sends_another_remote_operation(self):
        value = runner.pins()
        emitted, phases = [], []
        def aws(*args):
            if args[:2] == ("s3api", "head-object"):
                return {"ContentLength": 0, "ServerSideEncryption": "AES256"}
            return {}
        def request(artifact, phase, release_id):
            phases.append(phase)
            return ({"status": "prepared", "backup_retained": True} if phase == "prepare" else
                    {"status": "installed_verified", "admission_released": True})
        with patch.object(runner, "bundle", return_value=b"synthetic public code"), patch.object(runner, "aws", side_effect=aws), \
                patch.object(runner, "request", side_effect=request), patch.object(runner, "invalidate", return_value={"completed": True}), \
                patch.object(runner.remote, "verify_http", side_effect=RuntimeError("private transport detail")), \
                patch.object(runner, "emit", side_effect=lambda kind, report: emitted.append((kind, report))):
            report = runner.run("apply", value["candidate"], value["installed_fingerprint"])
        self.assertEqual(phases, ["prepare", "apply"])
        self.assertEqual(report["status"], "partial_acceptance_requires_inspection")
        self.assertFalse(report["automatic_rollback_attempted"])
        self.assertEqual(emitted[-1][0], "CLEANUP")
        self.assertTrue(emitted[-1][1]["current_transport_object_cleared"])
        self.assertNotIn("private transport detail", json.dumps(emitted))

    def test_cleanup_failure_is_reported_without_restarting_committed_services(self):
        value, phases, emitted = runner.pins(), [], []
        def request(artifact, phase, release_id):
            phases.append(phase)
            return {"status": "prepared"} if phase == "prepare" else {"status": "installed_verified", "admission_released": True}
        with patch.object(runner, "bundle", return_value=b"synthetic public code"), patch.object(runner, "aws", return_value={}), \
                patch.object(runner, "request", side_effect=request), patch.object(runner, "invalidate", return_value={"completed": True}), \
                patch.object(runner.remote, "verify_http"), patch.object(runner, "emit", side_effect=lambda k, v: emitted.append((k, v))):
            with self.assertRaisesRegex(runner.RunnerError, "transport_cleanup_requires_inspection"):
                runner.run("apply", value["candidate"], value["installed_fingerprint"])
        self.assertEqual(phases, ["prepare", "apply"])
        self.assertFalse(emitted[-1][1]["current_transport_object_cleared"])
        self.assertTrue(emitted[-1][1]["release_committed"])


class WorkerHealthTests(unittest.TestCase):
    counters = b"NRestarts=7\nResult=success\nExecMainCode=0\nExecMainStatus=0\nMemoryCurrent=1234\nMemoryPeak=4321\n"

    def test_only_fixed_counters_and_manager_event_counts_leave_the_reader(self):
        journal = b'{"MESSAGE":"A process was killed by the OOM killer; private account key"}\n{"MESSAGE":"Main process exited, private licensed text"}\n{"MESSAGE":"Scheduled restart job"}\n'
        with patch.object(remote, "command", side_effect=[self.counters, journal]) as call:
            report = remote.worker_health()
        self.assertEqual(report["status"], "observed")
        self.assertEqual(report["systemd_counters"]["NRestarts"], 7)
        self.assertEqual(report["manager_events_last_30m"], {"oom_kill": 1, "process_exit": 1, "scheduled_restart": 1})
        self.assertNotIn("private", json.dumps(report))
        self.assertIn("_PID=1", call.call_args_list[1].args[0])
        self.assertEqual(call.call_count, 2)

    def test_missing_optional_memory_peak_does_not_hide_restart_evidence(self):
        with patch.object(remote, "command", side_effect=[self.counters.replace(b"MemoryPeak=4321\n", b""), b""]):
            report = remote.worker_health()
        self.assertEqual(report["systemd_counters"]["MemoryPeak"], None)
        self.assertEqual(report["systemd_counters"]["NRestarts"], 7)

    def test_unknown_values_and_malformed_journal_never_expose_raw_messages(self):
        for counters, journal in ((self.counters.replace(b"success", b"private account"), b""), (self.counters, b"private raw log")):
            with patch.object(remote, "command", side_effect=[counters, journal]):
                self.assertEqual(remote.worker_health(), {"status": "unavailable", "error_code": "worker_health_projection_failed"})

    def test_unavailable_systemd_has_only_a_fixed_error_code(self):
        with patch.object(remote, "command", side_effect=RuntimeError("private raw error")):
            self.assertEqual(remote.worker_health(), {"status": "unavailable", "error_code": "worker_health_projection_failed"})


class MemoryPressureTests(unittest.TestCase):
    host = b"MemTotal: 2097152 kB\nMemAvailable: 1048576 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\nPrivateUnused: hidden text\n"

    def test_capacity_and_exact_worker_kernel_classification_only(self):
        rows = [
            "oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/system.slice/recursive-agents.service,private account",
            "oom-kill:constraint=CONSTRAINT_NONE,global_oom,task_memcg=/system.slice/recursive-agents.service,private key",
            "oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/system.slice/recursive-agents.service-other,licensed text",
            "oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/system.slice/recursive-web.service,private text",
        ]
        journal = ("\n".join(json.dumps({"MESSAGE": row}) for row in rows)).encode()
        with patch.object(remote.Path, "open", mock_open(read_data=self.host)) as files, patch.object(remote, "command", return_value=journal) as cmd:
            report = remote.memory_pressure()
        self.assertEqual(report["host_bytes"]["MemTotal"], 2147483648)
        self.assertEqual(report["kernel_events_last_30m"], {"cgroup_constraint": 1, "global_constraint": 1,
                                                         "worker_limit": 1, "ancestor_limit": 0, "unclassified_memcg": 0})
        self.assertNotIn("private", json.dumps(report))
        files.assert_called_once_with("rb")
        self.assertIn("--dmesg", cmd.call_args.args[0])
        self.assertEqual(cmd.call_args.kwargs["timeout"], 3)

    def test_malformed_host_does_not_hide_kernel_evidence_or_echo_private_data(self):
        invalid = (b"private host contents", self.host + b"MemTotal: 1 kB\n", self.host.replace(b"2097152", b"0"), b"x" * 65537)
        for raw in invalid:
            with patch.object(remote.Path, "open", mock_open(read_data=raw)), patch.object(remote, "command", return_value=b""):
                report = remote.memory_pressure()
            self.assertEqual(report, {"host_error_code": "host_memory_projection_failed", "kernel_events_last_30m": {
                "cgroup_constraint": 0, "global_constraint": 0, "worker_limit": 0,
                "ancestor_limit": 0, "unclassified_memcg": 0}})

    def test_ancestor_and_missing_scopes_cannot_implicate_the_worker_limit(self):
        messages = [
            "oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/system.slice,task_memcg=/system.slice/recursive-agents.service,private",
            "oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/,task_memcg=/system.slice/recursive-agents.service,private",
            "oom-kill:constraint=CONSTRAINT_MEMCG,task_memcg=/system.slice/recursive-agents.service,private",
        ]
        raw = ("\n".join(json.dumps({"MESSAGE": message}) for message in messages)).encode()
        with patch.object(remote.Path, "open", mock_open(read_data=self.host)), patch.object(remote, "command", return_value=raw):
            report = remote.memory_pressure()
        self.assertEqual(report["kernel_events_last_30m"], {"cgroup_constraint": 3, "global_constraint": 0,
                                                         "worker_limit": 0, "ancestor_limit": 2, "unclassified_memcg": 1})
        self.assertNotIn("private", json.dumps(report))

    def test_kernel_error_preserves_capacity_and_redacts_messages(self):
        for raw in (b"private invalid json", b'{"MESSAGE":["private"]}'):
            with patch.object(remote.Path, "open", mock_open(read_data=self.host)), patch.object(remote, "command", return_value=raw):
                report = remote.memory_pressure()
            self.assertEqual(report["kernel_error_code"], "kernel_memory_projection_failed")
            self.assertEqual(report["host_bytes"]["MemTotal"], 2147483648)
            self.assertNotIn("private", json.dumps(report))

    def test_unavailable_readers_have_only_fixed_error_codes(self):
        with patch.object(remote.Path, "open", side_effect=RuntimeError("private read")), patch.object(remote, "command", side_effect=RuntimeError("private journal")):
            self.assertEqual(remote.memory_pressure(), {"host_error_code": "host_memory_projection_failed", "kernel_error_code": "kernel_memory_projection_failed"})


class RootMetadata:
    def __init__(self, original):
        self.original = original
    def __getattr__(self, name):
        return 0 if name in ("st_uid", "st_gid") else getattr(self.original, name)


class RealFlagFilesystemTests(unittest.TestCase):
    """Exercise real O_EXCL/write/fsync/unlink behavior without root/systemd."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_lstat, self.original_fstat, self.original_fdopen = Path.lstat, remote.os.fstat, remote.os.fdopen
        self.original_fsync, self.original_chmod = remote.os.fsync, remote.os.chmod
        self.private = self.root / "existing-private.env"
        self.private.write_bytes(b"synthetic-existing-private-config")
        self.context = __import__("contextlib").ExitStack()
        self.context.enter_context(patch.object(remote, "ENV_PATH", self.root / "live" / "live.env"))
        self.context.enter_context(patch.object(remote, "DROPINS", (self.root / "web" / "live.conf", self.root / "agents" / "live.conf")))
        self.context.enter_context(patch.object(remote.Path, "lstat", lambda path, *a, **kw: RootMetadata(self.original_lstat(path, *a, **kw))))
        self.context.enter_context(patch.object(remote.os, "fstat", lambda fd: RootMetadata(self.original_fstat(fd))))
        self.context.enter_context(patch.object(remote.os, "chown", lambda *a, **kw: None))
        self.command = self.context.enter_context(patch.object(remote, "command", return_value=b""))
        guard = type("Guard", (), {"read_regular": staticmethod(lambda path, *a, **kw:
                    (Path(path).read_bytes(), {"uid": 0, "gid": 0, "mode": "0600"}))})()
        self.backend = remote.Backend(guard, {})

    def tearDown(self):
        self.context.close()
        self.temp.cleanup()

    def test_partial_write_fsync_ownership_and_mode_faults_clean_only_own_inodes(self):
        for operation in ("write", "fsync", "chown", "chmod"):
            for failing_file in (1, 2, 3):
                with self.subTest(operation=operation, failing_file=failing_file):
                    calls, created = [0], []
                    self.backend.flag_journal.clear()
                    def fault(*args, **kwargs):
                        calls[0] += 1
                        if calls[0] == failing_file:
                            raise OSError("synthetic injected private detail")
                        if operation == "fsync":
                            return self.original_fsync(*args, **kwargs)
                        if operation == "chmod":
                            return self.original_chmod(*args, **kwargs)
                    class Writer:
                        def __init__(inner, fd):
                            inner.stream = self.original_fdopen(fd, "wb")
                        def __enter__(inner):
                            return inner
                        def __exit__(inner, *args):
                            inner.stream.close()
                        def write(inner, raw):
                            calls[0] += 1
                            if calls[0] == failing_file:
                                inner.stream.write(raw[:10])
                                raise OSError("synthetic partial write")
                            return inner.stream.write(raw)
                        def flush(inner):
                            return inner.stream.flush()
                        def fileno(inner):
                            return inner.stream.fileno()
                    method = "fdopen" if operation == "write" else operation
                    injected = (lambda fd, mode: Writer(fd)) if operation == "write" else fault
                    with patch.object(remote.os, method, side_effect=injected):
                        with self.assertRaises(OSError):
                            self.backend.flags(created, check=lambda: None)
                    self.backend.remove_flags(created, check=lambda: None)
                    self.assertTrue(all(not path.exists() for path in (remote.ENV_PATH, *remote.DROPINS)))
                    self.assertEqual(self.private.read_bytes(), b"synthetic-existing-private-config")

    def test_daemon_reload_fault_cleans_published_files_using_the_journal(self):
        created = []
        self.command.side_effect = remote.ReleaseError("service_operation_failed")
        with self.assertRaises(remote.ReleaseError):
            self.backend.flags(created, check=lambda: None)
        self.assertEqual(len(self.backend.flag_journal), 6)
        self.command.side_effect = None
        self.backend.remove_flags(created, check=lambda: None)
        self.assertTrue(all(not path.exists() for path in (remote.ENV_PATH, *remote.DROPINS)))

    def test_atomic_link_or_temporary_unlink_failure_cleans_only_this_attempt(self):
        original_link, original_unlink = remote.os.link, Path.unlink
        for operation in ("link", "unlink"):
            for failing_file in (1, 2, 3):
                with self.subTest(operation=operation, failing_file=failing_file):
                    calls, created = [0], []
                    self.backend.flag_journal.clear()
                    def link(*args, **kwargs):
                        calls[0] += 1
                        if calls[0] == failing_file:
                            raise OSError("synthetic publication failure")
                        return original_link(*args, **kwargs)
                    def unlink(path, *args, **kwargs):
                        if ".tau-perps-" in path.name and path.name.endswith(".tmp"):
                            calls[0] += 1
                            if calls[0] == failing_file:
                                raise OSError("synthetic temporary unlink failure")
                        return original_unlink(path, *args, **kwargs)
                    owner, method, injected = ((remote.os, "link", link) if operation == "link" else (Path, "unlink", unlink))
                    with patch.object(owner, method, injected):
                        with self.assertRaises(OSError):
                            self.backend.flags(created, check=lambda: None)
                    self.backend.remove_flags(created, check=lambda: None)
                    self.assertTrue(all(not path.exists() for path in (remote.ENV_PATH, *remote.DROPINS)))
                    self.assertFalse(list(self.root.rglob("*.tmp")))
                    self.assertEqual(self.private.read_bytes(), b"synthetic-existing-private-config")

    def test_publication_exposes_only_complete_private_files_and_never_overwrites(self):
        original_link = remote.os.link
        published, created = [], []
        def checked(source, destination, **kwargs):
            self.assertFalse(destination.exists())
            self.assertEqual(stat.S_IMODE(self.original_lstat(source).st_mode), 0o600)
            self.assertIn(source.read_bytes(), (remote.ENV_CONTENT, remote.DROPIN_CONTENT))
            published.append(destination)
            return original_link(source, destination, **kwargs)
        with patch.object(remote.os, "link", checked):
            self.backend.flags(created, check=lambda: None)
        self.assertEqual(published, [remote.ENV_PATH, *remote.DROPINS])
        self.backend.remove_flags(created, check=lambda: None)

    def test_foreign_replacement_with_matching_bytes_is_preserved(self):
        created = []
        self.backend.flags(created, check=lambda: None)
        held = self.root / "owned-inode-held"
        remote.ENV_PATH.rename(held)
        remote.ENV_PATH.write_bytes(remote.ENV_CONTENT)
        with self.assertRaisesRegex(remote.ReleaseError, "new_environment_changed_before_rollback"):
            self.backend.remove_flags(created, check=lambda: None)
        self.assertEqual(remote.ENV_PATH.read_bytes(), remote.ENV_CONTENT)

    def test_lost_admission_proof_stops_before_next_unlink_or_reload(self):
        created = []
        self.backend.flags(created, check=lambda: None)
        calls = [0]
        def lost():
            calls[0] += 1
            if calls[0] == 2:
                raise db.DatabaseError("admission_connection_changed")
        before = self.command.call_count
        with self.assertRaises(db.DatabaseError):
            self.backend.remove_flags(created, check=lost)
        self.assertTrue(remote.ENV_PATH.exists())
        self.assertTrue(all(path.exists() for path in remote.DROPINS))
        self.assertEqual(self.command.call_count, before)


if __name__ == "__main__":
    unittest.main()
