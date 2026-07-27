from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = REPOSITORY_ROOT / "docs" / "PRODUCTION_HARDENING_STATUS.json"
MATRIX_PATH = REPOSITORY_ROOT / "docs" / "PRODUCTION_HARDENING_GATE_MATRIX.md"
ROLLBACK_DOC = REPOSITORY_ROOT / "docs" / "DEPLOYMENT_ROLLBACK.md"
RUNNER_DOC = REPOSITORY_ROOT / "docs" / "PROTECTED_REHEARSAL_RUNNER.md"
RUNNER_SCRIPT = REPOSITORY_ROOT / "scripts" / "run_protected_rehearsal.sh"


def test_machine_readable_hardening_status_is_internally_consistent() -> None:
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))

    assert status["version"] == 1
    assert status["programme"] == "Book System OS v0.1 Production Hardening"
    assert status["governing_issue"] == 31
    assert status["total_gates"] == 9
    assert status["completed_count"] == len(status["completed_gates"]) == 8
    assert set(status["completed_gates"]) == {
        "H-01",
        "H-02",
        "H-03",
        "H-04",
        "H-05",
        "H-06",
        "H-07",
        "H-08",
    }
    assert status["active_gate"] == "H-09"
    assert status["active_issue"] == 42
    assert status["state"] == "in-progress"
    assert "create immutable annotated v0.1.8-hardened tag" in status[
        "completion_requires"
    ]


def test_hardening_matrix_matches_machine_readable_status() -> None:
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    matrix = MATRIX_PATH.read_text(encoding="utf-8")

    assert "docs/PRODUCTION_HARDENING_STATUS.json" in matrix
    assert (
        f"v0.1 Production Hardening: {status['completed_count']}/"
        f"{status['total_gates']} gates complete"
    ) in matrix

    for gate in status["completed_gates"]:
        rows = [line for line in matrix.splitlines() if line.startswith(f"| {gate} ")]
        assert len(rows) == 1, gate
        assert "| Complete — #" in rows[0], gate

    active_rows = [
        line
        for line in matrix.splitlines()
        if line.startswith(f"| {status['active_gate']} ")
    ]
    assert len(active_rows) == 1
    assert f"| Next — #{status['active_issue']} |" in active_rows[0]
    assert "A mismatch blocks completion" in matrix


def test_rollback_document_separates_proof_return_deployment_and_tag() -> None:
    document = ROLLBACK_DOC.read_text(encoding="utf-8")

    for required in (
        "## Rehearsal runner standard",
        "## Separate return to the current accepted release",
        "H-09 is not complete while production remains on the older H-08 target",
        "## Final immutable hardening tag",
        "v0.1.8-hardened",
        "never move, delete or replace it",
    ):
        assert required in document

    assert document.index("## Separate return to the current accepted release") < document.index(
        "## Final immutable hardening tag"
    )


def test_protected_rehearsal_runner_has_required_controls() -> None:
    script = RUNNER_SCRIPT.read_text(encoding="utf-8")
    documentation = RUNNER_DOC.read_text(encoding="utf-8")

    for required in (
        "set -Eeuo pipefail",
        "umask 077",
        "nohup env",
        "trap on_exit EXIT",
        "trap 'on_signal HUP 129' HUP",
        "trap 'on_signal INT 130' INT",
        "trap 'on_signal TERM 143' TERM",
        "sha256sum \"$0\" \"$SCRIPT\"",
        "rehearsal-runner-result=$result",
        "chmod 0600 \"$PID_FILE\"",
        "mv \"$temporary\" \"$RESULT_FILE\"",
    ):
        assert required in script

    for forbidden in (
        "eval ",
        "git clean",
        "git reset",
        "rm -rf",
        "shred",
    ):
        assert forbidden not in script.lower()

    assert "scripts/run_protected_rehearsal.sh" in documentation
    assert "scripts/rollback_server.sh" in documentation
    assert "A runner `PASS` means only" in documentation


def test_protected_rehearsal_runner_has_valid_bash_syntax() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")

    result = subprocess.run(
        [bash, "-n", str(RUNNER_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_protected_rehearsal_runner_help_is_available() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")

    result = subprocess.run(
        [bash, str(RUNNER_SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Protected" not in result.stderr
    assert "--launch-log" in result.stdout
    assert "--pid-file" in result.stdout
