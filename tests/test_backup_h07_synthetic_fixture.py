from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup_job_store.sh"
VALIDATOR = REPO_ROOT / "scripts" / "validate_backup.py"
H07_FIXTURE_ID = "20260727-123343-2331e0af"
ARCHIVE_REASON = "Archived by cleanup helper; older than 7 days"
ARCHIVED_AT = "2026-07-27T12:34:00+00:00"


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "book-system"
    (root / "books" / "jobs").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "config").mkdir()
    (root / "config" / "env").write_text(
        "BOOK_SYSTEM_ENV=test\n"
        "BOOK_API_KEY=replace-with-test-api-key\n"
        "BOOK_ADMIN_PASSWORD=replace-with-test-password\n",
        encoding="utf-8",
    )
    (root / "logs" / "service.log").write_text("synthetic fixture test\n", encoding="utf-8")
    return root


def _make_cleanup_fixture(root: Path, job_id: str = H07_FIXTURE_ID) -> Path:
    job = root / "books" / "jobs" / job_id
    for directory in ("input", "work", "output", "logs"):
        (job / directory).mkdir(parents=True)

    metadata = {
        "job_id": job_id,
        "title": "H07 controlled cleanup fixture",
        "slug": "h07-controlled-cleanup-fixture",
        "created_at": "2026-07-27T12:33:43+00:00",
    }
    status = {
        "state": "archived",
        "status": "done",
        "step": "complete",
        "message": "Build complete",
        "updated_at": ARCHIVED_AT,
        "archived_at": ARCHIVED_AT,
        "archive_reason": ARCHIVE_REASON,
    }
    events = (
        {
            "created_at": "2026-07-27T12:33:43+00:00",
            "event": "created",
            "message": "Synthetic lifecycle fixture created",
        },
        {
            "created_at": ARCHIVED_AT,
            "event": "archived",
            "message": ARCHIVE_REASON,
            "older_than_days": 7,
        },
    )

    (job / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (job / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    (job / "events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    (job / "input" / "book.md").write_text("# Synthetic cleanup fixture\n", encoding="utf-8")
    (job / "logs" / "acceptance.log").write_text("cleanup fixture retained\n", encoding="utf-8")
    return job


def _create_backup(root: Path, archive: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["BOOK_SYSTEM_ROOT"] = str(root)
    return _run(
        "bash",
        str(BACKUP_SCRIPT),
        "--root",
        str(root),
        str(archive),
        env=env,
    )


def test_exact_documented_h07_cleanup_fixture_without_manifest_round_trips(
    tmp_path: Path,
) -> None:
    root = _make_root(tmp_path)
    source_job = _make_cleanup_fixture(root)
    archive = tmp_path / "h07-fixture.tar.gz"

    backup = _create_backup(root, archive)

    assert backup.returncode == 0, backup.stdout + backup.stderr
    assert '"historical_synthetic_fixtures_without_manifest": 1' in backup.stdout
    assert "backup-validation=pass" in backup.stdout
    assert "backup=pass" in backup.stdout
    assert not (source_job / "manifest.json").exists()

    restore_root = tmp_path / "restored"
    restore = _run(
        sys.executable,
        str(VALIDATOR),
        str(archive),
        "--restore-root",
        str(restore_root),
    )

    assert restore.returncode == 0, restore.stdout + restore.stderr
    assert '"historical_synthetic_fixtures_without_manifest": 1' in restore.stdout
    assert "backup-restore=pass" in restore.stdout

    restored_job = restore_root / "books" / "jobs" / H07_FIXTURE_ID
    assert not (restored_job / "manifest.json").exists()
    for relative in (
        "metadata.json",
        "status.json",
        "events.jsonl",
        "input/book.md",
        "logs/acceptance.log",
    ):
        assert (restored_job / relative).read_bytes() == (source_job / relative).read_bytes()


def test_other_modern_done_job_without_manifest_still_fails(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    job_id = "20260727-123343-nearmiss0"
    _make_cleanup_fixture(root, job_id=job_id)
    archive = tmp_path / "near-miss.tar.gz"

    backup = _create_backup(root, archive)

    assert backup.returncode != 0
    assert f"books/jobs/{job_id}/manifest.json" in backup.stderr
    assert not archive.exists()


def test_exact_h07_id_without_matching_archive_event_still_fails(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    job = _make_cleanup_fixture(root)
    (job / "events.jsonl").write_text(
        json.dumps(
            {
                "created_at": "2026-07-27T12:33:43+00:00",
                "event": "created",
                "message": "Synthetic lifecycle fixture created",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    archive = tmp_path / "missing-archive-evidence.tar.gz"

    backup = _create_backup(root, archive)

    assert backup.returncode != 0
    assert f"books/jobs/{H07_FIXTURE_ID}/manifest.json" in backup.stderr
    assert not archive.exists()


def test_exact_h07_id_with_malformed_archive_event_fails_closed(tmp_path: Path) -> None:
    root = _make_root(tmp_path)
    job = _make_cleanup_fixture(root)
    (job / "events.jsonl").write_text("{not-json}\n", encoding="utf-8")
    archive = tmp_path / "malformed-events.tar.gz"

    backup = _create_backup(root, archive)

    assert backup.returncode != 0
    assert "Invalid event JSON" in backup.stderr
    assert not archive.exists()
