"""The collector-box deploy ships data_pipeline/ (+ the app-free trading_core/) and never starts the stopped live engine."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_collector.sh"


def test_dry_run_builds_a_data_pipeline_bundle_and_rolls_back_on_a_down_unit():
    out = subprocess.run(
        ["bash", str(SCRIPT), "--ref", "HEAD", "--dry-run"],
        capture_output=True, text=True, env={"AWS_PROFILE": "", "PATH": "/usr/bin:/bin"}, check=True,
    ).stdout
    assert "bundle ok" in out and "py_compile data_pipeline/*.py trading_core/*.py" in out
    assert "mkdir -p trading_core" in out and "mv trading_core.bak." in out
    assert out.index("systemctl restart") < out.index("HEALTH FAILED") and "rollback" in out
    assert "kalshi-live-engine" not in out  # stopped on purpose; a deploy must not bring it back


def test_the_ci_deploy_user_may_reach_the_collector_box():
    doc = (ROOT / "scripts" / "DEPLOY_WORKFLOW_SETUP.md").read_text()
    assert "instance/i-0bd0683cc7e86243d" in doc
