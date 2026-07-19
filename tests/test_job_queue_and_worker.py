from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pipeline.structural import structural_cleanup
from app.services.job_queue import (
    cleanup_old_test_jobs,
    create_job,
    read_job_events,
    read_status,
    retry_job,
    write_status,
)
from app.services.worker import acquire_lock, release_lock


@pytest.fixture
def jobs_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    return tmp_path


def set_old_creation_time(job_dir: Path) -> None:
    metadata_path = job_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["created_at"] = "2020-01-01T00:00:00+00:00"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def test_structural_cleanup_is_conservative_and_deterministic() -> None:
    raw = "# Title  \r\n\r\n\r\n\r\n\r\nParagraph   \r\n"
    assert structural_cleanup(raw) == "# Title\n\n\nParagraph\n"


def test_retry_preserves_source_and_records_history(jobs_root: Path) -> None:
    _, job_dir = create_job(title="Retry", markdown="# Retry\n", state="test")
    source_before = (job_dir / "input" / "book.md").read_text(encoding="utf-8")
    write_status(job_dir, status="failed", step="export", message="Temporary failure")
    (job_dir / "work" / "stale.txt").write_text("stale", encoding="utf-8")
    (job_dir / "output" / "stale.pdf").write_text("stale", encoding="utf-8")
    (job_dir / "logs" / "stale.log").write_text("stale", encoding="utf-8")

    retry_job(job_dir)

    status = read_status(job_dir)
    assert status["state"] == "test"
    assert status["status"] == "queued"
    assert status["step"] == "retry"
    assert status["retry_count"] == 1
    assert (job_dir / "input" / "book.md").read_text(encoding="utf-8") == source_before
    assert list((job_dir / "work").iterdir()) == []
    assert list((job_dir / "output").iterdir()) == []
    assert list((job_dir / "logs").iterdir()) == []
    assert [event["event"] for event in read_job_events(job_dir)] == ["created", "retry"]


def test_cleanup_archives_only_old_finished_test_jobs(jobs_root: Path) -> None:
    _, eligible = create_job(title="Eligible", markdown="# Eligible", state="test")
    _, production = create_job(title="Production", markdown="# Production", state="production")
    _, queued = create_job(title="Queued", markdown="# Queued", state="test")

    for job_dir in (eligible, production, queued):
        set_old_creation_time(job_dir)

    write_status(eligible, status="done", step="complete", message="Done")
    write_status(production, status="done", step="complete", message="Done")

    preview = cleanup_old_test_jobs(older_than_days=7, dry_run=True)
    assert preview["eligible_count"] == 1
    assert preview["archived_count"] == 0
    assert preview["jobs"][0]["job_id"] == eligible.name
    assert read_status(eligible)["state"] == "test"

    result = cleanup_old_test_jobs(older_than_days=7, dry_run=False)
    assert result["eligible_count"] == 1
    assert result["archived_count"] == 1
    assert read_status(eligible)["state"] == "archived"
    assert read_status(production)["state"] == "production"
    assert read_status(queued)["state"] == "test"
    assert read_status(queued)["status"] == "queued"


def test_worker_lock_is_exclusive_and_releasable(tmp_path: Path) -> None:
    job_dir = tmp_path / "job"
    job_dir.mkdir()

    assert acquire_lock(job_dir) is True
    assert acquire_lock(job_dir) is False
    release_lock(job_dir)
    assert acquire_lock(job_dir) is True
    release_lock(job_dir)
