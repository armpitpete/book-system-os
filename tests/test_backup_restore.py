from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup_job_store.sh"
VALIDATOR = REPO_ROOT / "scripts" / "validate_backup.py"
API_SECRET = "api-secret-value-123456789"
ADMIN_SECRET = "admin-secret-value-123456789"


def run_command(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
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
    (root / "logs" / "service.log").write_text("service started\n", encoding="utf-8")
    return root


def make_job(
    root: Path,
    job_id: str,
    *,
    state: str = "test",
    status_name: str = "done",
    created_at: str = "2026-07-24T20:00:00+00:00",
    with_events: bool = True,
) -> Path:
    job = root / "books" / "jobs" / job_id
    for directory in ("input", "work", "output", "logs"):
        (job / directory).mkdir(parents=True)

    metadata = {
        "job_id": job_id,
        "title": f"Backup fixture {job_id}",
        "slug": f"backup-fixture-{job_id}",
        "created_at": created_at,
    }
    status = {
        "state": state,
        "status": status_name,
        "step": "complete" if status_name == "done" else "waiting",
        "message": "Build complete" if status_name == "done" else "Job queued",
        "updated_at": "2026-07-24T20:01:00+00:00",
    }
    (job / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (job / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    (job / "input" / "book.md").write_text(
        "# Backup fixture\n\nUnicode: café — “quotes”.\n", encoding="utf-8"
    )
    (job / "work" / "book-clean.md").write_text("# Backup fixture\n", encoding="utf-8")
    (job / "logs" / "build.log").write_text("build complete\n", encoding="utf-8")

    if with_events:
        events = (
            {"created_at": created_at, "event": "created", "message": "Job queued"},
            {
                "created_at": "2026-07-24T20:01:00+00:00",
                "event": status_name,
                "message": status["message"],
            },
        )
        (job / "events.jsonl").write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
            encoding="utf-8",
        )

    if status_name == "done":
        outputs = {
            "pdf_standard": "book-standard.pdf",
            "pdf_nd": "book-nd.pdf",
            "epub": "book.epub",
            "docx": "book.docx",
        }
        for filename in outputs.values():
            (job / "output" / filename).write_bytes(f"fixture:{job_id}:{filename}".encode("utf-8"))
        manifest = {
            "completed_at": "2026-07-24T20:01:00+00:00",
            "outputs": outputs,
            "status": status,
        }
        (job / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return job


def create_backup(root: Path, archive: Path) -> subprocess.CompletedProcess[str]:
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


def rewrite_archive_without(source: Path, destination: Path, omitted_name: str) -> None:
    with tarfile.open(source, "r:gz") as incoming, tarfile.open(destination, "w:gz") as outgoing:
        for member in incoming.getmembers():
            if member.name.rstrip("/") == omitted_name:
                continue
            if member.isfile():
                handle = incoming.extractfile(member)
                assert handle is not None
                outgoing.addfile(member, io.BytesIO(handle.read()))
            else:
                outgoing.addfile(member)


def test_backup_validates_and_restores_complete_store(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    test_job = make_job(root, "20260724-200000-test0001", state="test")
    production_job = make_job(root, "20260724-200001-prod0001", state="production")
    archive = tmp_path / "book-system.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode == 0, result.stderr
    assert "backup-secret-scan=pass" in result.stdout
    assert "backup-validation=pass" in result.stdout
    assert "backup=pass" in result.stdout
    assert archive.is_file() and archive.stat().st_size > 0

    with tarfile.open(archive, "r:gz") as backup:
        names = {member.name.rstrip("/") for member in backup.getmembers()}
        assert "book-system-backup/config/env" not in names
        assert "book-system-backup/config/env.keys" in names
        assert not any(name.endswith("/.lock") for name in names)

        combined = bytearray()
        for member in backup.getmembers():
            if not member.isfile():
                continue
            handle = backup.extractfile(member)
            assert handle is not None
            combined.extend(handle.read())
        assert API_SECRET.encode("utf-8") not in combined
        assert ADMIN_SECRET.encode("utf-8") not in combined

    restore_root = tmp_path / "restored"
    restore = run_command(
        sys.executable,
        str(VALIDATOR),
        str(archive),
        "--restore-root",
        str(restore_root),
    )

    assert restore.returncode == 0, restore.stderr
    assert "backup-validation=pass" in restore.stdout
    assert "backup-restore=pass" in restore.stdout
    assert '"legacy_jobs_without_events": 0' in restore.stdout
    assert not (restore_root / "config" / "env").exists()

    env_keys = (restore_root / "config" / "env.keys").read_text(encoding="utf-8")
    assert "BOOK_API_KEY" in env_keys
    assert "BOOK_ADMIN_PASSWORD" in env_keys
    assert API_SECRET not in env_keys
    assert ADMIN_SECRET not in env_keys
    assert "=" not in "\n".join(
        line for line in env_keys.splitlines() if line and not line.startswith("#")
    )

    for source_job in (test_job, production_job):
        restored_job = restore_root / "books" / "jobs" / source_job.name
        for relative in (
            "input/book.md",
            "metadata.json",
            "status.json",
            "work/book-clean.md",
            "logs/build.log",
            "manifest.json",
            "events.jsonl",
            "output/book-standard.pdf",
            "output/book-nd.pdf",
            "output/book.epub",
            "output/book.docx",
        ):
            assert (restored_job / relative).read_bytes() == (source_job / relative).read_bytes()


def test_backup_preserves_legacy_job_without_event_history(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    legacy_job = make_job(
        root,
        "20260620-162235-legacy01",
        state="production",
        created_at="2026-06-20T16:22:35+00:00",
        with_events=False,
    )
    modern_job = make_job(root, "20260724-200000-modern01", state="test")
    archive = tmp_path / "legacy-compatible.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode == 0, result.stderr
    assert '"legacy_jobs_without_events": 1' in result.stdout
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
    assert '"legacy_jobs_without_events": 1' in restore.stdout
    assert not (legacy_job / "events.jsonl").exists()
    assert not (restore_root / "books" / "jobs" / legacy_job.name / "events.jsonl").exists()
    assert (
        restore_root / "books" / "jobs" / modern_job.name / "events.jsonl"
    ).read_bytes() == (modern_job / "events.jsonl").read_bytes()


def test_validator_rejects_modern_job_without_event_history(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    job = make_job(root, "20260724-200000-modern01")
    valid = tmp_path / "modern-valid.tar.gz"
    assert create_backup(root, valid).returncode == 0

    broken = tmp_path / "modern-missing-events.tar.gz"
    rewrite_archive_without(
        valid,
        broken,
        f"book-system-backup/books/jobs/{job.name}/events.jsonl",
    )

    result = run_command(sys.executable, str(VALIDATOR), str(broken))

    assert result.returncode != 0
    assert "Modern job is missing required event history" in result.stderr
    assert job.name in result.stderr


def test_validator_rejects_malformed_present_event_history(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    job = make_job(root, "20260724-200000-bad-events")
    (job / "events.jsonl").write_text("{not-json}\n", encoding="utf-8")
    archive = tmp_path / "bad-events.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode != 0
    assert "Invalid event JSON" in result.stderr
    assert not archive.exists()


def test_backup_refuses_active_or_locked_jobs(tmp_path: Path) -> None:
    running_root = make_root(tmp_path / "running")
    make_job(running_root, "running-job", status_name="running")
    running_archive = tmp_path / "running.tar.gz"

    running = create_backup(running_root, running_archive)

    assert running.returncode != 0
    assert "job store is not quiescent" in running.stderr
    assert not running_archive.exists()

    locked_root = make_root(tmp_path / "locked")
    locked_job = make_job(locked_root, "locked-job")
    (locked_job / ".lock").write_text("", encoding="utf-8")
    locked_archive = tmp_path / "locked.tar.gz"

    locked = create_backup(locked_root, locked_archive)

    assert locked.returncode != 0
    assert "job store is not quiescent" in locked.stderr
    assert not locked_archive.exists()


def test_backup_refuses_configured_secret_in_staged_data(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    make_job(root, "secret-job")
    crossing_payload = b"x" * (1024 * 1024 - 3) + API_SECRET.encode("utf-8") + b"\n"
    (root / "logs" / "service.log").write_bytes(crossing_payload)
    archive = tmp_path / "secret.tar.gz"

    result = create_backup(root, archive)

    assert result.returncode != 0
    assert "configured secret value for BOOK_API_KEY appears" in result.stderr
    assert not archive.exists()


def test_validator_rejects_missing_completed_manifest(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    job = make_job(root, "job-with-manifest")
    valid = tmp_path / "valid.tar.gz"
    assert create_backup(root, valid).returncode == 0

    broken = tmp_path / "missing-manifest.tar.gz"
    rewrite_archive_without(
        valid,
        broken,
        f"book-system-backup/books/jobs/{job.name}/manifest.json",
    )

    result = run_command(sys.executable, str(VALIDATOR), str(broken))

    assert result.returncode != 0
    assert "Required backup file is missing" in result.stderr
    assert "manifest.json" in result.stderr


def test_validator_rejects_unsafe_members_and_nonempty_restore(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe.tar.gz"
    with tarfile.open(unsafe, "w:gz") as archive:
        info = tarfile.TarInfo("book-system-backup/../../escape")
        payload = b"escape"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    unsafe_result = run_command(sys.executable, str(VALIDATOR), str(unsafe))

    assert unsafe_result.returncode != 0
    assert "Unsafe archive member path" in unsafe_result.stderr

    root = make_root(tmp_path / "valid-root")
    make_job(root, "restore-job")
    valid = tmp_path / "restore.tar.gz"
    assert create_backup(root, valid).returncode == 0

    destination = tmp_path / "not-empty"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("do not overwrite\n", encoding="utf-8")

    restore_result = run_command(
        sys.executable,
        str(VALIDATOR),
        str(valid),
        "--restore-root",
        str(destination),
    )

    assert restore_result.returncode != 0
    assert "Restore destination is not empty" in restore_result.stderr
    assert marker.read_text(encoding="utf-8") == "do not overwrite\n"
