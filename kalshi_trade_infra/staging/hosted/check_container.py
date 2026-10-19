"""Disposable Actions-only hosted-profile check with synthetic configuration.

No actual OAuth, billing, model, market-data or order request is issued. This
cannot establish a persistent hosted site or actual provider acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
RECEIPT = Path("hosted-container-check.json")
ORIGIN = "https://d000000stage.cloudfront.net"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]


class CheckError(RuntimeError):
    pass


def require(ok: bool, code: str):
    if not ok:
        raise CheckError(code)


def run(arguments, env=None, timeout=180):
    result = subprocess.run(arguments, capture_output=True, timeout=timeout, env=env)
    require(result.returncode == 0, "container_check_command_failed")
    return result.stdout


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def request(path, method="GET", headers=None):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(urllib.request.Request("http://127.0.0.1:18091" + path,
                               headers=headers or {}, method=method,
                               data=b"{}" if method == "POST" else None), timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, response.read(4 * 1024 * 1024), dict(response.headers)


def check() -> dict:
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and bool(re.fullmatch(r"[0-9]+", os.environ.get("GITHUB_RUN_ID", "")))
            and not os.environ.get("DOCKER_HOST"), "actions_fixture_context_required")
    project = "tau-hosted-check-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    require(bool(re.fullmatch(r"tau-hosted-check-[0-9]+-[0-9]+", project)), "invalid_fixture_project")
    receipt = {"status": "failed", "mode": "synthetic_configuration_real_hosted_containers",
               "real_provider_calls": 0, "production_changed": False, "persistent_hosted_site": False,
               "real_oauth_or_paper_order_accepted": False, "cleanup_passed": False}
    invocation = DOCKER + ["compose", "--project-name", project, "--file", str(HERE / "compose.yml")]
    with tempfile.TemporaryDirectory(prefix="tau-hosted-check-") as temporary:
        state = Path(temporary) / "state"
        environment = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8",
                       "TAU_HOSTED_STATE_DIR": str(state)}
        try:
            receipt["phase"] = "fixture_configuration"
            run(["python3", "-I", str(HERE / "setup.py"), "--state-dir", str(state)], env=environment)
            values = {"APP_PUBLIC_URL": ORIGIN, "GOOGLE_CLIENT_ID": "12345678-hostedfixture.apps.googleusercontent.com",
                      "GOOGLE_CLIENT_SECRET": "fixture_" + secrets.token_urlsafe(24),
                      "ALPACA_OAUTH_CLIENT_ID": "fixture_" + secrets.token_urlsafe(24),
                      "ALPACA_OAUTH_CLIENT_SECRET": "fixture_" + secrets.token_urlsafe(24),
                      "STRIPE_SECRET_KEY": "sk_test_" + secrets.token_hex(24),
                      "STRIPE_PUBLISHABLE_KEY": "pk_test_" + secrets.token_hex(24),
                      "STRIPE_WEBHOOK_SECRET": "whsec_" + secrets.token_hex(24),
                      "TAU_ADMIN_EMAIL": "ci-operator@tau.test"}
            (state / "hosted_runtime.json").write_text(json.dumps(values))
            before = {name: hashlib.sha256((state / name).read_bytes()).hexdigest()
                      for name in ("mysql_root_password", "mysql_password", "app_secret_key")}
            run(["python3", "-I", str(HERE / "setup.py"), "--state-dir", str(state), "--check"], env=environment)
            receipt["phase"] = "image_build"
            run(invocation + ["build"], env=environment, timeout=1200)
            receipt["phase"] = "database_schema_and_startup"
            run(invocation + ["up", "--detach", "--wait", "gateway"], env=environment, timeout=300)
            receipt["phase"] = "runtime_network_and_uid"
            ids = run(invocation + ["ps", "--all", "--quiet"], env=environment).decode().split()
            inspected = json.loads(run(DOCKER + ["inspect", *ids], env=environment))
            by_service = {row["Config"]["Labels"]["com.docker.compose.service"]: row for row in inspected}
            require(set(by_service) == {"db", "schema", "web", "gateway"}, "unexpected_hosted_fixture_service")
            for name in ("db", "schema", "web"):
                require(not by_service[name]["HostConfig"].get("PortBindings"), "backend_port_published")
            require(by_service["gateway"]["HostConfig"]["PortBindings"] ==
                    {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18091"}]}, "gateway_not_loopback_only")
            require(by_service["schema"]["State"]["ExitCode"] == 0, "full_schema_failed")
            networks = json.loads(run(DOCKER + ["network", "inspect", project + "_private", project + "_egress"], env=environment))
            require([row["Internal"] for row in networks] == [True, False], "hosted_network_isolation_failed")
            pid = run(invocation + ["exec", "-T", "web", "cat", "/proc/1/status"], env=environment).decode()
            uid = next(line for line in pid.splitlines() if line.startswith("Uid:"))
            caps = next(line for line in pid.splitlines() if line.startswith("CapEff:"))
            require(uid.split()[1:] == ["10001"] * 4 and int(caps.split()[1], 16) == 0, "hosted_uid_or_capabilities_failed")
            statuses = {}
            receipt["phase"] = "http_auth_and_source_checks"
            for path in ("/", "/research", "/healthz", "/api/version", "/api/me", "/auth/dev"):
                statuses[path] = request(path)[0]
            require(all(statuses[path] == 200 for path in ("/", "/research", "/healthz", "/api/version"))
                    and statuses["/api/me"] == 401 and statuses["/auth/dev"] in (403, 404), "hosted_http_contract_failed")
            require(request("/healthz", "HEAD")[0] == 200, "hosted_head_failed")
            require(request("/api/runs", "POST")[0] == 403
                    and request("/api/runs", "POST", {"X-Recursive": "1", "Content-Type": "application/json"})[0] == 401,
                    "hosted_authentication_or_csrf_bypassed")
            status, _, headers = request("/auth/google")
            redirect = urllib.parse.urlsplit(headers.get("Location", ""))
            query = urllib.parse.parse_qs(redirect.query)
            require(status == 302 and redirect.netloc == "accounts.google.com"
                    and query.get("redirect_uri") == [ORIGIN + "/auth/google/callback"], "google_redirect_not_preserved")
            for asset in ("app.js", "app.meridian.js", "alpaca-paper.js"):
                status, raw, _ = request("/static/" + asset)
                require(status == 200 and hashlib.sha256(raw).digest() ==
                        hashlib.sha256((HERE.parents[1] / "app/static" / asset).read_bytes()).digest(), "served_source_mismatch")
            run(["python3", "-I", str(HERE / "setup.py"), "--state-dir", str(state)], env=environment)
            require(all(hashlib.sha256((state / name).read_bytes()).hexdigest() == digest for name, digest in before.items()),
                    "staging_database_or_vault_secret_regenerated")
            receipt.update(status="passed", http_statuses=statuses, full_schema_passed=True,
                           database_unpublished=True, loopback_gateway_only=True, normal_auth_and_csrf=True,
                           google_redirect_only_checked=True, app_uid=10001, app_capabilities=0,
                           served_assets_match=True, secrets_persist=True)
            receipt["phase"] = "accepted_synthetic_profile"
        finally:
            cleanup = subprocess.run(invocation + ["down", "--volumes", "--remove-orphans"],
                                     capture_output=True, timeout=120, env=environment)
            receipt["cleanup_passed"] = cleanup.returncode == 0
            if not receipt["cleanup_passed"]:
                receipt["status"] = "cleanup_requires_inspection"
            RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    try:
        result = check()
    except Exception as error:
        result = json.loads(RECEIPT.read_text()) if RECEIPT.is_file() else {
            "status": "failed", "mode": "synthetic_configuration_real_hosted_containers",
            "production_changed": False, "real_provider_calls": 0, "persistent_hosted_site": False}
        result["error_code"] = str(error) if isinstance(error, CheckError) else "hosted_container_check_failed"
        RECEIPT.write_text(json.dumps(result, indent=2) + "\n")
    print("TAU_HOSTED_CONTAINER_CHECK=" + json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "passed" and result.get("cleanup_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
