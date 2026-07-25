from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from scripts.normalise_tracked_permissions import normalise_tracked_permissions


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_normalises_only_tracked_files_and_parent_directories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    source_dir = root / "app" / "services"
    script_dir = root / "scripts"
    config_dir = root / "config"

    source_dir.mkdir(parents=True)
    script_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    source = source_dir / "worker.py"
    executable = script_dir / "deploy.sh"
    tracked_config = config_dir / "env.example"
    secret = config_dir / "env"

    source.write_text("VALUE = 1\n", encoding="utf-8")
    executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    tracked_config.write_text("KEY=example\n", encoding="utf-8")
    secret.write_text("KEY=real-secret\n", encoding="utf-8")

    _git(root, "init")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "add", "app/services/worker.py", "scripts/deploy.sh", "config/env.example")
    _git(root, "update-index", "--chmod=+x", "scripts/deploy.sh")
    _git(root, "commit", "-m", "fixture")

    source.chmod(0o600)
    executable.chmod(0o600)
    tracked_config.chmod(0o600)
    secret.chmod(0o600)
    source_dir.chmod(0o700)
    script_dir.chmod(0o700)
    config_dir.chmod(0o700)
    (root / "app").chmod(0o700)

    summary = normalise_tracked_permissions(root)

    assert _mode(source) == 0o644
    assert _mode(executable) == 0o755
    assert _mode(tracked_config) == 0o644
    assert _mode(secret) == 0o600
    assert _mode(source_dir) == 0o755
    assert _mode(script_dir) == 0o755
    assert _mode(config_dir) == 0o755
    assert _mode(root / "app") == 0o755
    assert summary["files"] == 3
    assert summary["executables"] == 1
    assert summary["directories"] == 4


def test_preserves_untracked_file_under_restrictive_umask(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    tracked_dir = root / "app"
    tracked_dir.mkdir(parents=True)

    tracked = tracked_dir / "module.py"
    untracked = root / "runtime-secret"

    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    untracked.write_text("secret\n", encoding="utf-8")

    _git(root, "init")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "add", "app/module.py")
    _git(root, "commit", "-m", "fixture")

    previous_umask = os.umask(0o077)
    try:
        tracked.chmod(0o600)
        tracked_dir.chmod(0o700)
        untracked.chmod(0o600)
        normalise_tracked_permissions(root)
    finally:
        os.umask(previous_umask)

    assert _mode(tracked) == 0o644
    assert _mode(tracked_dir) == 0o755
    assert _mode(untracked) == 0o600
