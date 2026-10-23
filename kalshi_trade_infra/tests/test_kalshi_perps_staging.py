"""Offline staging guards and synthetic native fixtures; no MySQL/provider calls."""
import ast
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


smoke = load("tau_perps_staging_smoke", ROOT / "scripts/kalshi_perps_staging_smoke.py")
entry = load("tau_perps_staging_entry", ROOT / "staging/entrypoint.py")


def environment():
    return {**smoke.guards.FIXED_FLAGS, **smoke.FIXED_FLAGS,
            "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3306", "MYSQL_DATABASE": smoke.guards.DATABASE,
            "MYSQL_USER": smoke.guards.DATABASE_USER, "MYSQL_PASSWORD": "synthetic-disposable-password",
            "APP_PUBLIC_URL": "http://127.0.0.1:8091",
            "APP_SECRET_KEY": base64.urlsafe_b64encode(bytes(range(32))).decode(),
            "AWS_EC2_METADATA_DISABLED": "true", "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "AWS_CONFIG_FILE": "/dev/null"}


def check(env):
    smoke.validate_environment(env, Path("/synthetic-checkout/kalshi_trade_infra"), path_exists=lambda path: False)


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline staging tests cannot open a connection")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def test_clean_environment_accepts_no_application_import_or_network():
    before = {name for name in sys.modules if name == "app" or name.startswith("app.")}
    check(environment())
    assert before == {name for name in sys.modules if name == "app" or name.startswith("app.")}


@pytest.mark.parametrize("name", list(smoke.FIXED_FLAGS))
@pytest.mark.parametrize("bad", [None, "", "unexpected"])
def test_every_perps_flag_must_match_the_isolated_process(name, bad):
    env = environment()
    if bad is None:
        env.pop(name)
    else:
        env[name] = bad
    with pytest.raises(smoke.SmokeError, match="perps_isolation_flags_invalid"):
        check(env)


@pytest.mark.parametrize("name", list(smoke.FORBIDDEN_KEYS))
def test_credentials_proxies_native_hosts_and_import_overrides_are_rejected(name):
    with pytest.raises(smoke.SmokeError, match="perps_external_configuration_forbidden") as caught:
        check({**environment(), name: "synthetic-sensitive-sentinel"})
    assert "synthetic-sensitive-sentinel" not in str(caught.value)


@pytest.mark.parametrize("field,value", [("MYSQL_DATABASE", "production"), ("MYSQL_USER", "root"),
    ("MYSQL_HOST", "example.com"), ("APP_DEV_LOGIN", "0"), ("APP_LIVE_TRADING_ENABLED", "1"),
    ("TAU_EXA_ENABLED", "1"), ("PROD_KEYID", "private"), ("AWS_PROFILE", "production"),
    ("APP_PUBLIC_URL", "https://kalshi.com"), ("AWS_CONFIG_FILE", "/private/config")])
def test_existing_database_provider_auth_and_network_guards_still_apply(field, value):
    with pytest.raises(smoke.SmokeError):
        check({**environment(), field: value})


def test_entrypoint_only_enables_perps_for_the_unpublished_verifier():
    values = {"mysql_password": "synthetic-staging-password-" + "a" * 24,
              "app_secret_key": base64.urlsafe_b64encode(bytes(range(32))).decode()}
    with patch.dict("os.environ", {"PROD_KEYID": "private", "TAU_KALSHI_PERPS_LIVE_ENABLED": "1",
                                  "TAU_KALSHI_PERPS_PROXY_URL": "https://private.example"}):
        for mode in entry.MODES:
            env = entry.child_environment(mode, values)
            assert env["TAU_KALSHI_PERPS_ENABLED"] == "0"
            assert env["TAU_KALSHI_PERPS_LIVE_ENABLED"] == ("1" if mode == "verify-perps" else "0")
            assert env["APP_LIVE_TRADING_ENABLED"] == env["APP_NO_SIDE_LIVE_ENABLED"] == "0"
            assert "PROD_KEYID" not in env and "TAU_KALSHI_PERPS_PROXY_URL" not in env
            if mode == "verify-perps":
                assert env["APP_HOST"] == "127.0.0.1" and env["APP_DEV_LOGIN"] == "1"
                smoke.validate_environment(env, Path("/synthetic-checkout/kalshi_trade_infra"), path_exists=lambda path: False)
            if mode == "web":
                assert env["APP_HOST"] == "0.0.0.0" and env["APP_DEV_LOGIN"] == "0"
    invocation = entry.command("verify-perps")
    assert invocation[:5] == [entry.PYTHON, "-I", "-B", "-u", "-c"]
    assert "scripts/kalshi_perps_staging_smoke.py" in invocation[-1]
    assert "scripts/paper_staging_smoke.py" in entry.command("verify")[-1]


def test_existing_compose_service_is_reused_without_a_new_public_service_or_port():
    compose = json.loads((ROOT / "staging/compose.yml").read_text())
    assert set(compose["services"]) == {"db", "schema", "web", "gateway", "verify"}
    verify = compose["services"]["verify"]
    assert "ports" not in verify and verify["networks"] == ["isolated"]
    assert verify["command"] == ["verify"]
    assert verify["environment"] == {"TAU_STAGING_CONTAINER": "isolated-compose-v1"}


def test_image_copies_only_the_explicit_new_script_and_the_full_candidate_schema_contains_orders():
    image = (ROOT / "staging/Dockerfile").read_text()
    ignored = (ROOT / "staging/Dockerfile.dockerignore").read_text()
    assert "COPY scripts/kalshi_perps_staging_smoke.py scripts/kalshi_perps_staging_smoke.py" in image
    assert "!scripts/kalshi_perps_staging_smoke.py" in ignored
    assert "COPY app/ app/" in image and "COPY data_pipeline/ data_pipeline/" in image
    assert "app.schema" in entry.command("schema")[-1]
    schema = (ROOT / "app/schema.py").read_text()
    assert "DDL.extend(kalshi_perps_orders_repository.DDL)" in schema


def test_workflow_runs_both_verifiers_in_order_with_separate_sanitized_receipts():
    workflow = (ROOT.parent / ".github/workflows/paper-staging.yml").read_text()
    old = "run --rm --no-deps -T verify | tee"
    new = "run --rm --no-deps -T verify verify-perps | tee"
    assert old in workflow and new in workflow and workflow.index(old) < workflow.index(new)
    for text in ("tau-perps-acceptance.json", "synthetic_kalshi_perps_real_mysql_http", "real_kalshi_keys_used",
                 "real_order_acceptance_tested", "independent_committed_claims", "public_perps_live_enabled",
                 "TAU_KALSHI_PERPS_LIVE_ENABLED')==b'0'", "kalshi-perps-live.js", "kalshi-perps-live.css"):
        assert text in workflow
    assert "staging/.state" not in workflow and "actions/upload-artifact" in workflow
    assert "down --volumes --remove-orphans" in workflow


def test_all_workflow_python_blocks_compile_and_receipt_uses_current_check_count():
    workflow = (ROOT.parent / ".github/workflows/paper-staging.yml").read_text()
    chunks = workflow.split("python3 - <<'PY'\n")[1:]
    assert len(chunks) == 2
    for chunk in chunks:
        body = chunk.split("\n          PY", 1)[0]
        code = "\n".join(line[10:] for line in body.splitlines())
        compile(code, "paper-staging-workflow", "exec")
    tree = ast.parse((ROOT / "scripts/kalshi_perps_staging_smoke.py").read_text())
    checks = [node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Name) and node.func.id == "passed"]
    assert len(checks) == len(set(checks)) == 19
    assert "len(perps['checks'])>=19" in workflow


def test_hosted_agent_proposal_exercises_real_action_envelope_even_on_autopilot():
    source = (ROOT / "scripts/kalshi_perps_staging_smoke.py").read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "agent" and node.func.attr == "act"]
    assert len(calls) == 1
    assert any(arg.arg == "autopilot" and arg.value.value is True for arg in calls[0].keywords)
    assert '"type": "kalshi_perps_order"' in source
    assert '"agent_proposal_submitted"' in source


def test_failure_receipt_drops_private_exception_bodies_and_keeps_safe_classification():
    smoke.guards._CHECKS.clear()
    smoke.guards._HTTP_FAILURE.clear()
    smoke.guards.stage("authentication_required")
    result = smoke.failure_result(RuntimeError("private-key or raw provider body"))
    assert result["mode"] == smoke.MODE and result["error_code"] == "unexpected_acceptance_failure"
    assert "private-key" not in json.dumps(result)
    assert smoke.failure_result(smoke.SmokeError("submission_claim_not_committed"))["error_code"] == "submission_claim_not_committed"
    assert smoke.failure_result(smoke.SmokeError("sensitive\nvalue"))["error_code"] == "unexpected_acceptance_failure"


def test_main_stops_before_application_import_on_unsafe_environment(monkeypatch):
    run = Mock(side_effect=AssertionError("must not import/run application"))
    monkeypatch.setattr(smoke, "run_acceptance", run)
    output = io.StringIO()
    with patch.dict("os.environ", {}, clear=True), contextlib.redirect_stdout(output):
        assert smoke.main() == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "failed" and result["stage"] == "isolation_environment"
    run.assert_not_called()


@pytest.fixture(scope="module")
def key_pair():
    return (rsa.generate_private_key(public_exponent=65537, key_size=2048),
            rsa.generate_private_key(public_exponent=65537, key_size=2048))


def fixture_client(key_pair):
    broker = smoke.SyntheticBroker()
    broker.add_account("synthetic-perps-owner-0", key_pair[0])
    broker.add_account("synthetic-perps-owner-1", key_pair[1])
    return broker, broker.client(("synthetic-perps-owner-0", key_pair[0]))


def body():
    return {"ticker": smoke.TICKER, "side": "bid", "count": "1000.00", "price": "8.01",
            "client_order_id": "00000000-0000-4000-8000-000000000001"}


def test_fixture_requires_exact_ephemeral_per_user_key_environment_and_no_proxy(key_pair):
    broker, client = fixture_client(key_pair)
    assert client.enabled_status()["enabled"] is True
    for credentials, env, proxy in [(("PROD", key_pair[0]), "production", None),
        (("synthetic-perps-owner-0", key_pair[1]), "production", None),
        (("synthetic-perps-owner-0", key_pair[0]), "demo", None),
        (("synthetic-perps-owner-0", key_pair[0]), "production", "http://proxy.example")]:
        with pytest.raises(smoke.SmokeError):
            broker.client(credentials, env, proxy)


def test_fixture_requires_committed_claim_callback_before_any_synthetic_post(key_pair):
    broker, client = fixture_client(key_pair)
    with pytest.raises(smoke.SmokeError, match="commit_assertion_missing"):
        client.submit_order(body())
    assert broker.posts == broker.committed_claims == 0
    def fail(*args):
        raise smoke.SmokeError("submission_claim_not_committed")
    broker.on_submit = fail
    with pytest.raises(smoke.SmokeError, match="submission_claim_not_committed"):
        client.submit_order(body())
    assert broker.posts == broker.committed_claims == 0


def test_synthetic_native_ledger_uses_usd_per_contract_and_other_owner_cannot_read_it(key_pair):
    broker, client = fixture_client(key_pair)
    observed = []
    broker.on_submit = lambda key, submitted: observed.append((key, copy_dict(submitted)))
    ack = client.submit_order(body())
    assert observed[0][0] == "synthetic-perps-owner-0" and observed[0][1] == body()
    assert broker.posts == broker.committed_claims == 1 and ack["fill_count"] == "1000.00"
    fills = client.fills(0)
    assert fills["complete"] is True and fills["fills"][0]["fees"] == "1.60200000"
    assert client.orders()["orders"][0]["price"] == "8.01"
    other = broker.client(("synthetic-perps-owner-1", key_pair[1]))
    assert other.orders()["orders"] == [] and other.fills(0)["fills"] == []
    assert other.positions()["positions"][0]["position"] == "0"


def copy_dict(value):
    return json.loads(json.dumps(value))


def test_synthetic_accepted_timeout_retains_get_reconciliation_data_without_retry(key_pair):
    class Uncertain(Exception):
        def __init__(self, code, message, *, uncertain):
            self.code, self.uncertain = code, uncertain
    broker, client = fixture_client(key_pair)
    broker.error_type = Uncertain
    broker.on_submit = lambda key, submitted: None
    broker.uncertain_next = True
    with pytest.raises(Uncertain) as caught:
        client.submit_order(body())
    assert caught.value.uncertain and broker.posts == 1
    listing = client.orders(smoke.TICKER, min_ts=0)
    assert listing["complete"] and len(listing["orders"]) == 1
    assert client.order(listing["orders"][0]["order_id"])["order"]["client_order_id"] == body()["client_order_id"]
    assert len(client.fills(0)["fills"]) == 1 and broker.posts == 1


def test_synthetic_preflight_can_be_stale_or_ineligible_without_any_post(key_pair):
    broker, client = fixture_client(key_pair)
    broker.stale_quote, broker.eligible = True, False
    assert client.enabled_status()["enabled"] is False
    assert client.orderbook(smoke.TICKER)["retrieved_at"] < smoke.stamp()["retrieved_at"]
    metadata = client.market()
    assert metadata["contract_multiplier"] == "0.0001" and metadata["price_basis"] == "per_contract"
    assert broker.posts == 0


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, *args):
        pass
    def fetchone(self):
        return self.rows.pop(0)


def observation(**changes):
    return {"user_id": 1, "status": "claimed", "approved_by_user_id": 1, "approved_at": "present",
            "claimed_at": "present", "request_json": json.dumps(body()), "proposal_id": None, **changes}


def test_independent_database_observer_accepts_only_committed_exact_owner_claim():
    conn = SimpleNamespace(cursor=lambda: Cursor([observation()]))
    smoke.StagingRepository.assert_committed_claim(conn, "owner", body(), {"owner": 1})


@pytest.mark.parametrize("changes", [{"status": "draft"}, {"approved_at": None}, {"claimed_at": None},
    {"user_id": 2}, {"approved_by_user_id": 2}, {"request_json": json.dumps({**body(), "price": "7"})}])
def test_independent_database_observer_rejects_unapproved_or_changed_claim(changes):
    conn = SimpleNamespace(cursor=lambda: Cursor([observation(**changes)]))
    with pytest.raises(smoke.SmokeError):
        smoke.StagingRepository.assert_committed_claim(conn, "owner", body(), {"owner": 1})


def test_proposal_application_must_be_visible_in_same_committed_claim():
    conn = SimpleNamespace(cursor=lambda: Cursor([observation(proposal_id=3), {"status": "applied"}]))
    smoke.StagingRepository.assert_committed_claim(conn, "owner", body(), {"owner": 1})
    conn = SimpleNamespace(cursor=lambda: Cursor([observation(proposal_id=3), {"status": "pending"}]))
    with pytest.raises(smoke.SmokeError, match="proposal_claim_not_committed"):
        smoke.StagingRepository.assert_committed_claim(conn, "owner", body(), {"owner": 1})
