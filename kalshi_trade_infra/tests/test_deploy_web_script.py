"""Exercise archive validation without AWS credentials or remote commands."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import shlex
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_web.sh"


def _dry_run(tmp_path: Path, *, missing: str = "", large: bool = False):
    repo = tmp_path / "repo"
    package = repo / "kalshi_trade_infra"
    (package / "app").mkdir(parents=True)
    for filename in ("app/server.py", "app/schema.py"):
        target = filename + ".backup" if missing == filename else filename
        (package / target).write_text("pass\n")
    if missing == "data_pipeline/":
        # A file with this name is not the required package directory.
        (package / "data_pipeline").write_text("not a package directory\n")
    else:
        (package / "data_pipeline").mkdir()
        (package / "data_pipeline" / "__init__.py").write_text("")
    if large:
        assets = package / "app" / "static"
        assets.mkdir()
        # Exceed pipe buffers so an early grep exit reliably breaks tar's writer.
        for index in range(1200):
            (assets / (f"asset-{index:04d}-" + "x" * 180 + ".js")).write_text("// fixture\n")
    script = package / "scripts" / "deploy_web.sh"
    script.parent.mkdir()
    shutil.copyfile(SCRIPT, script)
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
           "-c", "user.name=Tau Test", "-c", "user.email=tau-test@example.invalid"]
    for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "fixture"]):
        subprocess.run(git + args, cwd=repo, check=True, capture_output=True, text=True)
    tools = tmp_path / "bin"
    tools.mkdir()
    if large:
        # BSD tar can ignore EPIPE. Forward its real listing through a writer that
        # propagates SIGPIPE, matching GNU tar on the GitHub Actions Linux runner.
        tar = tools / "tar"
        tar.write_text('#!/bin/bash\nset -o pipefail\n' +
                       shlex.quote(shutil.which("tar")) + ' "$@" | cat\n')
        tar.chmod(0o755)
    marker = tmp_path / "aws-called"
    aws = tools / "aws"
    aws.write_text('#!/bin/sh\nprintf called > "$TAU_TEST_AWS_MARKER"\nexit 99\n')
    aws.chmod(0o755)
    env = os.environ.copy()
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        env.pop(name, None)
    env.update(PATH=str(tools) + os.pathsep + env.get("PATH", ""),
               AWS_PROFILE="", TAU_TEST_AWS_MARKER=str(marker))
    result = subprocess.run(["bash", str(script), "--ref", "HEAD", "--dry-run"],
                            cwd=repo, env=env, capture_output=True, text=True, timeout=30)
    assert not marker.exists(), "archive verification must never contact AWS"
    return result


def test_large_valid_bundle_passes_without_contacting_aws(tmp_path):
    result = _dry_run(tmp_path, large=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bundle ok" in result.stdout
    assert "DRY RUN" in result.stdout


@pytest.mark.parametrize("missing", ["app/server.py", "app/schema.py", "data_pipeline/"])
def test_missing_required_entry_rejects_prefix_decoys(tmp_path, missing):
    result = _dry_run(tmp_path, missing=missing)
    assert result.returncode != 0, result.stdout + result.stderr
    assert f"bundle missing {missing}" in result.stdout
    assert "DRY RUN" not in result.stdout
