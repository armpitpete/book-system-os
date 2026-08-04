from __future__ import annotations

import subprocess
from pathlib import Path


def test_release_launcher_has_valid_shell_syntax_and_protected_contract() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    launcher = repository_root / "scripts" / "production_corpus_runtime_release.sh"

    completed = subprocess.run(
        ["bash", "-n", str(launcher)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    text = launcher.read_text(encoding="utf-8")
    required = (
        "set -Eeuo pipefail",
        "umask 077",
        "--expected-before",
        "--target-commit",
        'DEPLOY $TARGET_COMMIT',
        'bash "$CANDIDATE_ROOT/scripts/production_v2_01_acceptance.sh"',
        "corpus_runtime_live_acceptance.py",
        "storage-before.json",
        "storage-after.json",
        "config-before.json",
        "config-after.json",
        "systemd-before.json",
        "systemd-after.json",
        "git_value \"$REPO_ROOT\" merge-base --is-ancestor",
        "Running launcher does not match the exact target commit",
        "Persistent job storage changed during deployment or acceptance",
        "book-system-api.service",
        "book-system-worker.service",
        "CORPUS RUNTIME RELEASE — PASS",
    )
    for marker in required:
        assert marker in text

    assert '\n"$CANDIDATE_ROOT/scripts/production_v2_01_acceptance.sh" \\\n' not in text
    assert "book-api.service" not in text
    assert "book-worker.service" not in text
    assert "git reset --hard" not in text
    assert "git clean" not in text
    assert "rollback" not in text.lower()
    assert "BOOK_API_KEY" not in text


def test_release_launcher_help_is_non_destructive() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    launcher = repository_root / "scripts" / "production_corpus_runtime_release.sh"

    completed = subprocess.run(
        ["bash", str(launcher), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "--expected-before" in completed.stdout
    assert "--target-commit" in completed.stdout
    assert "--confirm" in completed.stdout
