from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup_job_store.sh"
VALIDATOR = REPO_ROOT / "scripts" / "validate_backup.py"


def run_command(
    *args: str,
    env: dict[str, str] | None = None,
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
                "BOOK_API_KEY=archived-test-fixture-api-key",
                "BOOK_ADMIN_USERNAME=operator",
                "BOOK_ADMIN_PASSWORD=archived-test-fixture-password",
                "BOOK_BIND_HOST=127.0.0.1",
                "BOOK_BIND_PORT=8080",
                "BOOK_WORKER_POLL_SECONDS=2",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "logs" / "service.log").write_text(
        "service started\n",
        encoding="utf-8",
    )
    return root


def make_completed_job(
    root: Path,
    job_id: str,
    *,
    state: str = "test",
    legacy_manifest: bool = True,
) -> Path:
    job = root / "books" / "jobs" / job_id

    for directory in ("input", "work", "output", "logs"):
        (job / directory).mkdir(parents=True)

    created_at = "2026-07-01T12:00:00+00:00"
    completed_at = "2026-07-01T12:01:00+00:00"

    metadata = {
        "job_id": job_id,
        "title": f"Archived fixture {job_id}",
        "slug": f"archived-fixture-{job_id}",
        "created_at": created_at,
    }
    final_status = {
        "state": state,
        "status": "done",
        "step": "complete",
        "message": "Build complete",
        "updated_at": completed_at,
    }

    embedded_status = dict(final_status)

    if legacy_manifest:
        embedded_status.update(
            {
                "status": "running",
                "step": "pandoc-export",
                "message": "Building PDF/EPUB/DOCX outputs",
            }
        )

    outputs = {
        "pdf_standard": "book-standard.pdf",
        "pdf_nd": "book-nd.pdf",
        "epub": "book.epub",
        "docx": "book.docx",
    }

    (job / "metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    (job / "status.json").write_text(
        json.dumps(final_status, indent=2),
        encoding="utf-8",
    )
    (job / "input" / "book.md").write_text(
        "# Archived fixture\n",
        encoding="utf-8",
    )
    (job / "work" / "book-clean.md").write_text(
        "# Archived fixture\n",
        encoding="utf-8",
    )
    (job / "logs" / "build.log").write_text(
        "build complete\n",
        encoding="utf-8",
    )

    events = (
        {
            "created_at": created_at,
            "event": "created",
            "message": "Job queued",
            "state": state,
            "status": "queued",
        },
        {
            "created_at": completed_at,
            "event": "done",
            "message": "Build complete",
        },
    )
    (job / "events.jsonl").write_text(
        "".join(
            json.dumps(event, sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )

    for filename in outputs.values():
        (job / "output" / filename).write_bytes(
            f"fixture:{job_id}:{filename}".encode("utf-8")
        )

    manifest = {
        "completed_at": completed_at,
        "outputs": outputs,
        "status": embedded_status,
    }
    (job / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return job


def archive_job(
    job: Path,
    *,
    older_than_days: int = 7,
    include_event: bool = True,
) -> None:
    archived_at = "2026-07-25T12:00:00+00:00"
    reason = (
        "Archived by cleanup helper; older than "
        f"{older_than_days} days"
    )

    status_path = job / "status.json"
    status = json.loads(
        status_path.read_text(encoding="utf-8")
    )
    status.update(
        {
            "state": "archived",
            "archived_at": archived_at,
            "archive_reason": reason,
            "updated_at": archived_at,
        }
    )
    status_path.write_text(
        json.dumps(status, indent=2),
        encoding="utf-8",
    )

    if include_event:
        with (job / "events.jsonl").open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    {
                        "created_at": archived_at,
                        "event": "archived",
                        "message": reason,
                        "older_than_days": older_than_days,
                    },
                    sort_keys=True,
                )
                + "\n"
            )


def create_backup(
    root: Path,
    archive: Path,
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


def test_backup_preserves_archived_test_with_legacy_manifest(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    job = make_completed_job(
        root,
        "20260701-120000-archived-legacy",
    )
    archive_job(job)
    archive = tmp_path / "archived-legacy.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode == 0, result.stderr
    assert "backup-validation=pass" in result.stdout
    assert archive.is_file()

    restore_root = tmp_path / "restored"
    restore = run_command(
        sys.executable,
        str(VALIDATOR),
        str(archive),
        "--restore-root",
        str(restore_root),
    )

    assert restore.returncode == 0, restore.stderr
    restored_job = (
        restore_root / "books" / "jobs" / job.name
    )

    for filename in (
        "status.json",
        "manifest.json",
        "events.jsonl",
    ):
        assert (
            restored_job / filename
        ).read_bytes() == (job / filename).read_bytes()


def test_backup_preserves_archived_test_with_current_manifest(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    job = make_completed_job(
        root,
        "20260724-120000-archived-current",
        legacy_manifest=False,
    )
    archive_job(job)
    archive = tmp_path / "archived-current.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode == 0, result.stderr
    assert "backup-validation=pass" in result.stdout


def test_validator_rejects_archived_state_without_cleanup_event(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    job = make_completed_job(
        root,
        "20260701-120000-unexplained-archive",
    )
    archive_job(job, include_event=False)
    archive = tmp_path / "unexplained-archive.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode != 0
    assert (
        "Manifest state does not match final status"
        in result.stderr
    )
    assert not archive.exists()


def test_validator_rejects_production_to_archived_mismatch(
    tmp_path: Path,
) -> None:
    root = make_root(tmp_path)
    job = make_completed_job(
        root,
        "20260701-120000-production-archive",
        state="production",
    )
    archive_job(job)
    archive = tmp_path / "production-archive.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode != 0
    assert (
        "Manifest state does not match final status"
        in result.stderr
    )
    assert not archive.exists()
