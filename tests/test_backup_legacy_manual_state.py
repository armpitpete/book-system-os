from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup_job_store.sh"
VALIDATOR = REPO_ROOT / "scripts" / "validate_backup.py"
API_SECRET = "legacy-test-api-secret-123456789"
ADMIN_SECRET = "legacy-test-admin-secret-123456789"
JOB_ID = "20260621-104142-retry-test"


def run_command(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "book-system"
    (root / "books" / "jobs").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "config").mkdir()
    (root / "config" / "env").write_text(
        "\n".join(
            (
                "BOOK_SYSTEM_ROOT=/opt/book-system",
                "BOOK_SYSTEM_ENV=production",
                f"BOOK_API_KEY={API_SECRET}",
                "BOOK_ADMIN_USERNAME=operator",
                f"BOOK_ADMIN_PASSWORD={ADMIN_SECRET}",
                "BOOK_BIND_HOST=127.0.0.1",
                "BOOK_BIND_PORT=8080",
                "BOOK_WORKER_POLL_SECONDS=2",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "logs" / "service.log").write_text(
        "service started\n", encoding="utf-8"
    )
    return root


def make_legacy_manual_archived_job(root: Path) -> Path:
    job = root / "books" / "jobs" / JOB_ID
    for directory in ("input", "work", "output", "logs"):
        (job / directory).mkdir(parents=True)

    metadata = {
        "job_id": JOB_ID,
        "title": "Legacy retry test",
        "slug": "legacy-retry-test",
        "created_at": "2026-06-21T10:41:42+00:00",
    }
    status = {
        "state": "archived",
        "status": "done",
        "step": "complete",
        "message": "Build complete",
        "updated_at": "2026-06-21T10:44:27+00:00",
        "retry_count": 1,
        "last_retry_at": "2026-06-21T10:42:54+00:00",
    }
    events = (
        {
            "created_at": "2026-06-21T10:42:54+00:00",
            "event": "retry",
            "message": "Job queued for retry",
            "retry_count": 1,
        },
    )
    outputs = {
        "pdf_standard": "book-standard.pdf",
        "pdf_nd": "book-nd.pdf",
        "epub": "book.epub",
        "docx": "book.docx",
    }
    manifest = {
        "completed_at": "2026-06-21T10:42:58+00:00",
        "outputs": outputs,
        "status": {
            "state": "test",
            "status": "running",
            "step": "pandoc-export",
            "message": "Building PDF/EPUB/DOCX outputs",
            "updated_at": "2026-06-21T10:42:55+00:00",
            "retry_count": 1,
            "last_retry_at": "2026-06-21T10:42:54+00:00",
        },
    }

    (job / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    (job / "status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8"
    )
    (job / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    (job / "events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    (job / "input" / "book.md").write_text(
        "# Legacy retry test\n", encoding="utf-8"
    )
    (job / "work" / "book-clean.md").write_text(
        "# Legacy retry test\n", encoding="utf-8"
    )
    (job / "logs" / "build.log").write_text(
        "build complete\n", encoding="utf-8"
    )
    for filename in outputs.values():
        (job / "output" / filename).write_bytes(
            f"fixture:{JOB_ID}:{filename}".encode("utf-8")
        )

    return job


def create_backup(
    root: Path, archive: Path
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["BOOK_SYSTEM_ROOT"] = str(root)
    return run_command(
        "bash",
        str(BACKUP_SCRIPT),
        "--root",
        str(root),
        str(archive),
        env=env,
    )


def test_backup_accepts_exact_legacy_manual_archive_and_restores_bytes(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    job = make_legacy_manual_archived_job(root)
    archive = tmp_path / "legacy-manual-archive.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode == 0, result.stderr
    assert '"legacy_manual_archived_state_transitions": 1' in result.stdout
    assert '"legacy_manifests_without_final_status": 1' in result.stdout
    assert "backup=pass" in result.stdout

    restore_root = tmp_path / "restored"
    restore = run_command(
        sys.executable,
        str(VALIDATOR),
        str(archive),
        "--restore-root",
        str(restore_root),
    )

    assert restore.returncode == 0, restore.stderr
    assert '"legacy_manual_archived_state_transitions": 1' in restore.stdout
    assert "backup-restore=pass" in restore.stdout

    restored_job = restore_root / "books" / "jobs" / JOB_ID
    for relative in (
        "metadata.json",
        "status.json",
        "manifest.json",
        "events.jsonl",
        "input/book.md",
        "work/book-clean.md",
        "logs/build.log",
        "output/book-standard.pdf",
        "output/book-nd.pdf",
        "output/book.epub",
        "output/book.docx",
    ):
        assert (restored_job / relative).read_bytes() == (
            job / relative
        ).read_bytes()


@pytest.mark.parametrize(
    "mutation",
    (
        "outside-window",
        "missing-retry-event",
        "retry-count-mismatch",
        "production-origin",
        "archive-field-present",
        "too-late-after-completion",
    ),
)
def test_backup_rejects_inexact_legacy_manual_archive_shape(
    tmp_path: Path, mutation: str
) -> None:
    root = make_root(tmp_path)
    job = make_legacy_manual_archived_job(root)

    status_path = job / "status.json"
    manifest_path = job / "manifest.json"
    events_path = job / "events.jsonl"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "outside-window":
        status["updated_at"] = "2026-06-21T13:52:38+00:00"
    elif mutation == "missing-retry-event":
        events_path.write_text(
            json.dumps(
                {
                    "created_at": "2026-06-21T10:42:54+00:00",
                    "event": "created",
                    "message": "Job queued",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    elif mutation == "retry-count-mismatch":
        status["retry_count"] = 2
    elif mutation == "production-origin":
        manifest["status"]["state"] = "production"
    elif mutation == "archive-field-present":
        status["archived_at"] = status["updated_at"]
    elif mutation == "too-late-after-completion":
        status["updated_at"] = "2026-06-21T10:48:00+00:00"
    else:
        raise AssertionError(f"Unknown mutation: {mutation}")

    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = tmp_path / f"invalid-{mutation}.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode != 0
    assert "Manifest state does not match final status" in result.stderr
    assert JOB_ID in result.stderr
    assert not archive.exists()
