"""Synthetic deployment control-path checks: no cloud, provider, DB or systemd.

Only this test's temporary directories are mutated. Child startup is intercepted;
the real broker service, interpreter path and production files are never invoked.
"""
import copy
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name("paper_release_remote.py")
spec = importlib.util.spec_from_file_location("paper_release_remote_under_test", SOURCE)
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)

CREDENTIALS = {"ALPACA_OAUTH_CLIENT_ID": "synthetic-client-1234",
               "ALPACA_OAUTH_CLIENT_SECRET": "synthetic-secret-5678"}


def job_report(*, queued=0, running=0, paused=0, tail=120):
    return {"status": "available", "transaction": "read_only", "queued": queued,
            "running": running, "paused": paused, "seconds_since_latest_finished": tail}


class PureControls(unittest.TestCase):
    def test_each_active_state_blocks_idle(self):
        self.assertTrue(remote.idle(job_report()))
        for name in ("queued", "running", "paused"):
            with self.subTest(name=name):
                self.assertFalse(remote.idle(job_report(**{name: 1})))

    def test_exact_manifest_rejects_extra_changed_missing_and_symlink_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for package in ("app", "data_pipeline"):
                (root / package).mkdir()
                (root / package / "__init__.py").write_text("# synthetic\n")
            manifest = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in root.rglob("*.py")}
            self.assertTrue(remote.source_check(manifest, root))
            cache = root / "app/__pycache__"
            cache.mkdir()
            (cache / "synthetic.pyc").write_bytes(b"cache")
            self.assertTrue(remote.source_check(manifest, root))
            extra = root / "app/operator_added.py"
            extra.write_text("# extra source\n")
            self.assertFalse(remote.source_check(manifest, root))
            extra.unlink()
            original = root / "app/__init__.py"
            original.write_text("# changed\n")
            self.assertFalse(remote.source_check(manifest, root))
            original.unlink()
            self.assertFalse(remote.source_check(manifest, root))
            original.symlink_to(root / "data_pipeline/__init__.py")
            with self.assertRaises(remote.ReleaseError):
                remote.source_check(manifest, root)

    def test_quiet_window_requires_three_idle_samples_and_old_completion(self):
        for reports, accepted in (([job_report()] * 3, True),
                                   ([job_report(tail=29)] * 3, False),
                                   ([job_report(), job_report(queued=1)], False),
                                   ([job_report(), job_report(), job_report(paused=1)], False)):
            with self.subTest(reports=reports), patch.object(remote, "jobs", side_effect=reports), \
                    patch.object(remote.time, "sleep") as sleep:
                self.assertEqual(remote.quiet_window({})[0], accepted)
                self.assertLessEqual(sleep.call_count, 2)

    def test_private_literal_parser_rejects_expansion_and_nonliteral_assignments(self):
        class PrivateText:
            def __init__(self, content): self.content = content
            def lstat(self):
                return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_size=len(self.content))
            def read_text(self): return self.content
        self.assertEqual(remote.safe_literal(PrivateText("export EXA_API_KEY='synthetic-value'\n")),
                         {"EXA_API_KEY": "synthetic-value"})
        for content in ("EXA_API_KEY=$(id)\n", 'EXA_API_KEY="$(id)"\n',
                        "EXA_API_KEY=`id`\n", "EXA_API_KEY=${OTHER}\n",
                        "EXA_API_KEY=one;id\n", "EXA_API_KEY=one\nEXA_API_KEY=two\n"):
            with self.subTest(content=content), self.assertRaises((remote.ReleaseError, ValueError)):
                remote.safe_literal(PrivateText(content))

    def test_protected_environment_covers_auth_billing_database_and_live_controls(self):
        before = {"APP_SECRET_KEY": "synthetic-persistent-key", "AWS_PROFILE": "old-profile"}
        managed = {"TAU_ALPACA_PAPER_ENABLED": "1"}
        remote.verify_environment(before, {**before, **managed}, managed)
        for name in ("APP_SECRET_KEY", "MYSQL_PASSWORD", "STRIPE_SECRET_KEY", "GOOGLE_CLIENT_SECRET",
                     "LIVE_ENABLED", "TAU_ALLOW_LIVE", "AWS_SECRET_ACCESS_KEY", "IBKR_CLIENT_SECRET"):
            with self.subTest(name=name), self.assertRaises(remote.ReleaseError):
                remote.verify_environment(before, {**before, **managed, name: "unexpected-change"}, managed)

    def test_planned_child_sources_real_plan_but_never_launches_worker(self):
        body = ("set -a; . /opt/kalshi/.env.aws; . /opt/kalshi/.env.app; "
                ". /etc/tau/alpaca-paper/paper.env || exit $?; set +a; unset AWS_PROFILE; "
                "exec /opt/kalshi/.venv313/bin/python -u -m app.worker agents >> /tmp/synthetic.log 2>&1")
        expected = {"APP_SECRET_KEY": "synthetic-key", "TAU_ALPACA_PAPER_ENABLED": "1"}
        with patch.object(remote, "command", return_value=b'{"protected_environment_matches":true}') as command:
            remote.planned_startup({"body": body}, expected, expected)
        args, kwargs = command.call_args
        shell = args[0][2]
        self.assertIn(". /opt/kalshi/.env.aws", shell)
        self.assertIn(". /etc/tau/alpaca-paper/paper.env", shell)
        self.assertNotIn("-m app.worker", shell)
        self.assertNotIn("synthetic-key", shell)
        self.assertEqual(json.loads(kwargs["stdin"])["environment"], expected)
        with patch.object(remote, "command", return_value=b'{"protected_environment_matches":false}'):
            with self.assertRaises(remote.ReleaseError):
                remote.planned_startup({"body": body}, expected, expected)

    def test_candidate_overlay_uses_inherited_descriptor_without_secret_in_shell_arguments(self):
        body=('set -a; . /opt/kalshi/.env.aws; . /opt/kalshi/.env.app; '
              '. /etc/tau/alpaca-paper/paper.env || exit $?; set +a; unset AWS_PROFILE; '
              'exec /opt/kalshi/.venv313/bin/python -u -m app.server >> /tmp/synthetic.log 2>&1')
        expected={'APP_SECRET_KEY':'synthetic-private-key'}
        with tempfile.TemporaryFile() as overlay,patch.object(remote,'command',return_value=b'{"protected_environment_matches":true}') as command:
            overlay.write(b'ALPACA_OAUTH_CLIENT_SECRET=synthetic-oauth-secret\n');overlay.seek(0)
            remote.planned_startup({'body':body},expected,expected,cwd=Path('/synthetic/stage'),overlay_fd=overlay.fileno())
            args,kwargs=command.call_args
            self.assertIn('. /proc/self/fd/'+str(overlay.fileno()),args[0][2])
            self.assertEqual(kwargs['pass_fds'],(overlay.fileno(),))
            self.assertEqual(kwargs['cwd'],Path('/synthetic/stage'))
            self.assertNotIn('synthetic-oauth-secret',str(args))
            self.assertNotIn('synthetic-private-key',str(args))


class DeploymentControls(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = self.folder / "root"
        self.root.mkdir()
        self.release_root = self.folder / "releases"
        self.overlay = self.folder / "config/paper.env"
        self.units = self.folder / "units"
        self.units.mkdir()
        for package in ("app", "data_pipeline"):
            (self.root / package).mkdir()
            (self.root / package / "marker.py").write_text("VALUE = 'old'\n")
        for name in (".env.aws", ".env.app"):
            (self.root / name).write_text("# synthetic base\n")
        self.baseline = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in self.root.rglob("*.py")}
        self.release = {name: hashlib.sha256(b"VALUE = 'new'\n").hexdigest() for name in self.baseline}
        self.calls = []
        self.config = {}
        self.states = {name: "active" for name in remote.TARGETS}
        self.env = {"APP_SECRET_KEY": "synthetic-persistent-key", "LIVE_ENABLED": "0"}
        self.provider = {"TAU_EXA_ENABLED": "1", "EXA_API_KEY": "synthetic-exa-key"}
        self.paper = {**CREDENTIALS, "TAU_ALPACA_PAPER_ENABLED": "1", "TAU_ALPACA_PAPER_MAX_ORDER_USD": "500",
                      "APP_PUBLIC_URL": "https://tau-trading.com"}
        self.job_results = [job_report()] * 4
        self.failure = None
        self.write_failure = None
        self.partial_rename = None
        self.new_started = False
        self.original_open = os.open
        self.original_rename = os.rename
        self.lock_fds = []
        self.addCleanup(self.close_locks)

        def path(value):
            if str(value) == "/opt/tau-releases": return self.release_root
            if str(value) == "/etc/tau/alpaca-paper/paper.env": return self.overlay
            return Path(value)

        def opened(value, *args, **kwargs):
            if str(value) == "/run/lock/tau-paper-release.lock":
                result = self.original_open(self.folder / "release.lock", *args, **kwargs)
                self.lock_fds.append(result)
                return result
            return self.original_open(value, *args, **kwargs)

        def rename(source, target):
            source, target = Path(source), Path(target)
            if (self.partial_rename == source.name and source.parent.parent == self.release_root
                    and target.parent == self.root):
                self.partial_rename = None
                raise OSError("synthetic rename failure")
            return self.original_rename(source, target)

        def props(service):
            return {"MainPID": str(200 + remote.TARGETS.index(service) if self.new_started else
                                   100 + remote.TARGETS.index(service)) if service in remote.TARGETS else "900",
                    "ActiveState": self.states.get(service, "active"),
                    **{name: "1" for name in remote.RESOURCES}}

        def process(service):
            values = props(service)
            env = dict(self.env)
            if self.new_started:
                env.update(self.paper)
                if service == "recursive-agents": env.update(self.provider)
            return values, int(values["MainPID"]), env

        def plan(service, helper):
            fragment = self.units / (service + ".service")
            if not fragment.exists(): fragment.write_bytes(b"synthetic original unit")
            return ({"drop_path": self.units / (service + ".99.conf"),
                     "drop_bytes": (service + " paper startup").encode(), "body": "synthetic"},
                    {fragment: fragment.read_bytes()}, props(service))

        def extract(bundle, staging):
            for package in ("app", "data_pipeline"):
                (staging / package).mkdir()
                (staging / package / "marker.py").write_text("VALUE = 'new'\n")

        def snapshot(path): return copy.deepcopy(self.config.get(path))
        def write(path, raw, expected):
            self.assertEqual(self.config.get(path), expected)
            self.config[path] = {"raw": raw}
            self.calls.append(("write", str(path)))
            if self.write_failure == "after_replace":
                self.write_failure = None
                raise OSError("synthetic fsync failure")
            if self.write_failure == "operator_change":
                self.write_failure = None
                self.config[path] = {"raw": b"operator-changed"}
                raise OSError("synthetic post-replace race")
            return snapshot(path)
        def restore(path, original, installed):
            self.assertEqual(self.config.get(path), installed)
            if original is None: self.config.pop(path, None)
            else: self.config[path] = copy.deepcopy(original)
            self.calls.append(("restore", str(path)))
        helper = {"build_overlay": lambda credentials: b"synthetic private overlay", "prepare_directories": lambda: None,
                  "snapshot": snapshot, "atomic_write": write, "restore": restore}

        def command(args, **kwargs):
            self.calls.append(tuple(args))
            if args[:2] == ["systemctl", "stop"]:
                if self.failure == "partial_stop":
                    self.states["recursive-web"] = "inactive"
                    raise remote.ReleaseError("synthetic_partial_stop")
                for name in args[2:]: self.states[name] = "inactive"
            elif args[:2] == ["systemctl", "start"]:
                for name in args[2:]: self.states[name] = "active"
                self.new_started = (self.root / "app/marker.py").read_text() == "VALUE = 'new'\n"
                if self.failure == "partial_start":
                    raise remote.ReleaseError("synthetic_partial_start")
            elif "app.schema" in args and self.failure == "schema":
                raise remote.ReleaseError("synthetic_schema_failure")
            return b""

        real_source_check, real_hash = remote.source_check, remote.file_hash
        patches = {"ROOT": self.root, "Path": path, "RELEASE_SHA": "a" * 40,
                   "BASELINE_MANIFEST": self.baseline, "RELEASE_MANIFEST": self.release,
                   "config_module": lambda: helper, "process": process, "props": props,
                   "unit_plan": plan, "provider_configuration": lambda: dict(self.provider),
                   "UNIT_CAPTURE_MANIFEST": {},
                   "unit_guard": lambda: {"check_before": lambda *a: {}, "check_after_reload": lambda *a: None, "check_after_start": lambda *a: None, "recovery_dependencies_unchanged": lambda *a: True},
                   "extract_bundle": extract, "offline": lambda *a, **kw: {"ready": True},
                   "planned_startup": lambda *a, **kw: self.calls.append(("planned_startup",)),
                   "source_check": lambda manifest, root=None, **kw: real_source_check(manifest, root or self.root, **kw),
                   "file_hash": lambda p: "synthetic-provider-digest" if str(p) in remote.PROVIDER_FILES else real_hash(p),
                   "jobs": lambda env: self.job_results.pop(0), "quiet_window": lambda env: (True, job_report()),
                   "command": command}
        for name, value in patches.items():
            self.stack.enter_context(patch.object(remote, name, value, create=True))
        self.stack.enter_context(patch.object(remote.os, "open", opened))
        self.stack.enter_context(patch.object(remote.os, "rename", rename))
        self.stack.enter_context(patch.object(remote.time, "sleep", lambda value: None))
        self.stack.enter_context(patch.object(remote.urllib.request, "urlopen", side_effect=
            AssertionError("Unexpected real HTTP attempt in synthetic test")))

    def close_locks(self):
        for descriptor in self.lock_fds:
            try: os.close(descriptor)
            except OSError: pass
        self.lock_fds.clear()

    def run_release(self): return remote.activate(dict(CREDENTIALS), b"synthetic bundle")

    def test_real_startup_secret_drift_fails_before_any_service_stop(self):
        with patch.object(remote,'planned_startup',side_effect=remote.ReleaseError('planned_startup_environment_conflict')):
            with self.assertRaises(remote.ReleaseError):self.run_release()
        self.assert_original()
        self.assertFalse(any(call[:2]==('systemctl','stop') for call in self.calls))

    def test_concurrent_base_environment_edit_is_never_overwritten_or_started(self):
        original=remote.command
        def changed_schema(args,**kwargs):
            if 'app.schema' in args:
                (self.root/'.env.app').write_text('# concurrent operator update\n')
                raise remote.ReleaseError('synthetic_schema_error')
            return original(args,**kwargs)
        with patch.object(remote,'command',side_effect=changed_schema):result=self.run_release()
        self.assertEqual(result['status'],'operator_dependency_change_requires_inspection')
        self.assertEqual((self.root/'.env.app').read_text(),'# concurrent operator update\n')
        self.assertFalse(any(call[:2]==('systemctl','start') for call in self.calls))

    def test_success_preserves_utility_and_archives_backups_without_deploying_backup_code(self):
        utility='data_pipeline/research_fee_sensitivity.py';backup_name='data_pipeline/dashboard_server.py.bak'
        (self.root/utility).write_bytes(b'synthetic retained utility');(self.root/utility).chmod(0o750)
        (self.root/backup_name).write_bytes(b'synthetic old backup');(self.root/backup_name).chmod(0o644)
        frozen={utility:hashlib.sha256((self.root/utility).read_bytes()).hexdigest()}
        archived={backup_name:{'bytes':(self.root/backup_name).stat().st_size,'mode':'0644'}}
        preserve=remote.preserve_utilities
        class Origin:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
        with patch.dict(remote.__dict__,{'PRESERVED_ON_HOST':frozen,'ARCHIVE_ONLY_ON_HOST':archived}),\
             patch.object(remote,'preserve_utilities',side_effect=lambda folder:preserve(folder,self.root)),\
             patch.object(remote.urllib.request,'urlopen',side_effect=lambda *a,**kw:Origin()):
            result=self.run_release()
        self.assertEqual(result['status'],'deployed',result)
        self.assertEqual((self.root/utility).read_bytes(),b'synthetic retained utility')
        self.assertEqual(stat.S_IMODE((self.root/utility).stat().st_mode),0o750)
        self.assertFalse((self.root/backup_name).exists())
        previous=Path(result['backup_directory'])
        self.assertEqual((previous/backup_name).read_bytes(),b'synthetic old backup')
        self.assertEqual(result['on_host_utilities_preserved'],1)
        self.assertEqual(result['on_host_old_backups_archived'],1)
        self.assertTrue(result['app_secret_unchanged'])
        self.assertEqual(sum('app.schema' in call for call in self.calls),1)
        service_calls=[call for call in self.calls if call[:2] in (('systemctl','start'),('systemctl','stop'))]
        self.assertEqual(service_calls,[('systemctl','stop',*remote.TARGETS),('systemctl','start',*remote.TARGETS)])
    def test_explicit_interruption_deploys_with_busy_jobs_without_changing_job_records(self):
        self.job_results = [job_report(running=2, queued=4)] * 4
        class Origin:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
        with patch.dict(remote.__dict__, {'RESEARCH_INTERRUPTION_AUTHORIZED': True}), \
             patch.object(remote, 'quiet_window', side_effect=AssertionError('Explicit restart must not wait')), \
             patch.object(remote.urllib.request, 'urlopen', side_effect=lambda *a, **kw: Origin()):
            result = self.run_release()
        self.assertEqual(result['status'], 'deployed', result)
        self.assertTrue(result['research_interruption_authorized'])
        self.assertEqual(result['jobs']['running'], 2)
        self.assertEqual(result['jobs']['queued'], 4)
        self.assertEqual(sum('app.schema' in call for call in self.calls), 1)
        self.assertTrue(result['app_secret_unchanged'])

    def assert_original(self):
        self.assertTrue(remote.source_check(self.baseline))
        self.assertFalse(self.config)

    def test_initial_busy_never_stages_writes_stops_migrates_or_calls_provider(self):
        for key in ("running", "queued", "paused"):
            self.job_results = [job_report(**{key: 1})]
            result = self.run_release()
            self.assertEqual(result["status"], "waiting_for_idle")
            self.assertFalse(self.release_root.exists())
            self.assertFalse(self.calls)
            self.assert_original()
            self.close_locks()

    def test_final_busy_check_never_stops_or_installs(self):
        self.job_results = [job_report(), job_report(queued=1)]
        result = self.run_release()
        self.assertEqual(result["status"], "waiting_for_idle")
        self.assertFalse(any(call[:2] == ("systemctl", "stop") for call in self.calls))
        self.assert_original()

    def test_quiet_window_loses_idle_and_never_mutates_runtime(self):
        with patch.object(remote, "quiet_window", return_value=(False, job_report(paused=1))):
            result = self.run_release()
        self.assertEqual(result["status"], "waiting_for_idle")
        self.assertFalse(any(call[0] in ("systemctl", "write") for call in self.calls))
        self.assert_original()

    def test_new_queue_after_stop_restores_old_services_without_source_change(self):
        self.job_results = [job_report(), job_report(), job_report(queued=1)]
        result = self.run_release()
        self.assertEqual(result["status"], "failed_before_new_worker_start")
        self.assert_original()
        self.assertTrue(all(state == "active" for state in self.states.values()))

    def test_partial_stop_failure_recovers_web_without_restarting_active_agent(self):
        self.failure = "partial_stop"
        result = self.run_release()
        self.assertEqual(result["status"], "failed_before_new_worker_start")
        self.assert_original()
        self.assertIn(("systemctl", "start", "recursive-web"), self.calls)
        self.assertNotIn(("systemctl", "start", "recursive-agents"), self.calls)

    def test_each_partial_source_rename_rolls_back_completed_moves(self):
        # Separate instances are used so every execution starts from a clean baseline.
        self.partial_rename = "app"
        result = self.run_release()
        self.assertEqual(result["status"], "failed_before_new_worker_start")
        self.assert_original()
        self.assertTrue(all(state == "active" for state in self.states.values()))

    def test_second_package_partial_rename_preserves_both_old_packages(self):
        self.partial_rename = "data_pipeline"
        result = self.run_release()
        self.assertEqual(result["status"], "failed_before_new_worker_start")
        self.assert_original()

    def test_schema_failure_restores_source_but_never_reverses_database_history(self):
        self.failure = "schema"
        result = self.run_release()
        self.assertEqual(result["status"], "failed_before_new_worker_start")
        self.assert_original()
        self.assertEqual(sum("app.schema" in call for call in self.calls), 1)
        self.assertFalse(any("DROP" in str(call) for call in self.calls))

    def test_config_replace_then_fsync_failure_is_recovered_as_known_own_write(self):
        self.write_failure = "after_replace"
        result = self.run_release()
        self.assertEqual(result["status"], "failed_before_new_worker_start")
        self.assert_original()
        self.assertTrue(any(call[0] == "restore" for call in self.calls))

    def test_operator_changed_config_is_preserved_for_inspection_without_start(self):
        self.write_failure = "operator_change"
        result = self.run_release()
        self.assertEqual(result["status"], "private_config_recovery_requires_inspection")
        self.assertFalse(result["rollback_performed"])
        self.assertEqual(self.config[self.overlay]["raw"], b"operator-changed")
        self.assertTrue(all(state == "inactive" for state in self.states.values()))
        self.assertFalse(any(call[:2] == ("systemctl", "start") for call in self.calls))

    def test_any_new_start_attempt_prevents_blind_rollback_or_repeat_restart(self):
        self.failure = "partial_start"
        result = self.run_release()
        self.assertEqual(result["status"], "deployment_requires_inspection")
        self.assertFalse(result["rollback_performed"])
        self.assertTrue(remote.source_check(self.release))
        self.assertTrue(self.config)
        self.assertEqual(sum(call[:2] == ("systemctl", "start") for call in self.calls), 1)
        self.assertFalse(any(call[0] == "restore" for call in self.calls))
        start = next(i for i, call in enumerate(self.calls) if call[:2] == ("systemctl", "start"))
        self.assertEqual(sum(call[0] == "planned_startup" for call in self.calls[:start]), 4)


class SourceDiagnosticTests(unittest.TestCase):
    def test_old_backups_are_baseline_only_with_exact_names_sizes_modes_and_no_hardlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'app/static').mkdir(parents=True);(root/'data_pipeline').mkdir()
            name='data_pipeline/dashboard_server.py.bak';path=root/name;path.write_text('backup fixture');path.chmod(0o644)
            archive={name:{'bytes':path.stat().st_size,'mode':'0644'}}
            with patch.dict(remote.__dict__,{'ARCHIVE_ONLY_ON_HOST':archive}):
                self.assertTrue(remote.source_check({},root,allow_archives=True))
                self.assertFalse(remote.source_check({},root))
                path.chmod(0o600);self.assertFalse(remote.source_check({},root,allow_archives=True))
                path.chmod(0o644);path.write_text('changed size');self.assertFalse(remote.source_check({},root,allow_archives=True))
            with patch.dict(remote.__dict__,{'ARCHIVE_ONLY_ON_HOST':{'app/agent.py':{'bytes':1,'mode':'0644'}}}):
                with self.assertRaises(remote.ReleaseError):remote.source_check({},root,allow_archives=True)

    def test_verified_metadata_can_be_excluded_but_fake_metadata_and_loose_bytecode_cannot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'app').mkdir();(root/'data_pipeline').mkdir()
            metadata=root/'app/._a.py';metadata.write_bytes(b'\x00\x05\x16\x07\x00\x02\x00\x00fixture')
            self.assertTrue(remote.source_check({},root))
            metadata.write_text('ordinary code cannot be hidden as metadata')
            self.assertFalse(remote.source_check({},root));metadata.unlink()
            (root/'app/loose.pyc').write_bytes(b'not a normal __pycache__ file')
            self.assertFalse(remote.source_check({},root))

    def test_frozen_utilities_keep_bytes_modes_and_reject_changed_or_symlinked_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'live';stage=Path(directory)/'stage'
            for parent in (root,stage):
                (parent/'app').mkdir(parents=True);(parent/'data_pipeline').mkdir()
            name='data_pipeline/research_fee_sensitivity.py';source=root/name
            source.write_text('synthetic utility');source.chmod(0o750)
            frozen={name:hashlib.sha256(source.read_bytes()).hexdigest()}
            with patch.dict(remote.__dict__,{'PRESERVED_ON_HOST':frozen}):
                self.assertTrue(remote.source_check({},root))
                remote.preserve_utilities(stage,root)
                self.assertTrue(remote.source_check({},stage))
                self.assertEqual(stat.S_IMODE((stage/name).stat().st_mode),0o750)
                (stage/name).unlink();source.write_text('changed utility')
                self.assertFalse(remote.source_check({},root))
                with self.assertRaises(remote.ReleaseError):remote.preserve_utilities(stage,root)
                source.unlink();source.symlink_to(stage/'app')
                with self.assertRaises(remote.ReleaseError):remote.preserve_utilities(stage,root)

    def test_preservation_manifest_cannot_override_a_git_file_or_adopt_arbitrary_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'app').mkdir();(root/'data_pipeline').mkdir()
            with patch.dict(remote.__dict__,{'PRESERVED_ON_HOST':{'app/agent.py':'0'*64}}):
                with self.assertRaises(remote.ReleaseError):remote.source_check({},root)
            utility='data_pipeline/research_fee_sensitivity.py'
            with patch.dict(remote.__dict__,{'PRESERVED_ON_HOST':{utility:'0'*64}}):
                with self.assertRaises(remote.ReleaseError):remote.source_check({utility:'0'*64},root)

    def test_only_real_metadata_headers_are_classified_and_utility_is_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'app').mkdir();(root/'data_pipeline').mkdir()
            (root/'app/._a.py').write_bytes(b'\x00\x05\x16\x07\x00\x02\x00\x00fixture')
            (root/'app/.DS_Store').write_bytes(b'\x00\x00\x00\x01Bud1fixture')
            (root/'app/._unexpected.py').write_text('not metadata')
            utility='data_pipeline/research_fee_sensitivity.py'
            (root/utility).write_text('synthetic utility')
            report=remote.source_diagnostics({},root)
            self.assertEqual(len(report['verified_metadata_artifacts']),2)
            self.assertEqual(report['research_utility_sha256'][utility],hashlib.sha256(b'synthetic utility').hexdigest())
            self.assertEqual(report['unclassified_extra_count'],1)

    def test_diagnostics_report_names_without_reading_or_exposing_private_extra_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'app').mkdir();(root/'data_pipeline').mkdir()
            (root/'app/a.py').write_text('changed')
            (root/'app/old.css').write_text('obsolete fixture')
            (root/'app/.env').write_text('synthetic-private-do-not-output')
            report=remote.source_diagnostics({'app/a.py':'wrong','app/missing.py':'missing'},root)
            self.assertEqual(report['changed_known_source'],['app/a.py'])
            self.assertEqual(report['missing_known_source'],['app/missing.py'])
            self.assertEqual(report['extra_source_paths'],['app/old.css'])
            self.assertEqual(report['withheld_extra_path_count'],1)
            self.assertNotIn('synthetic-private-do-not-output',str(report))

if __name__ == "__main__":
    unittest.main()
