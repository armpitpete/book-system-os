from __future__ import annotations

import json
import socket
import time
from multiprocessing import Process
from pathlib import Path

import pytest

import app.services.job_recovery as recovery
from app.services.job_queue import (
    create_job,
    read_job_events,
    read_status,
    write_status,
)
from app.services.job_recovery import (
    RecoveryError,
    acquire_job_lock,
    inspect_job_recovery,
    recover_job,
    refresh_job_lock,
    release_job_lock,
)


@pytest.fixture
def jobs_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    return tmp_path


def _hold_job_lock(job_dir: str) -> None:
    job = Path(job_dir)
    if acquire_job_lock(job) is None:
        raise SystemExit(2)
    while True:
        time.sleep(1)


def _wait_for_classification(
    job_dir: Path,
    expected: str,
    *,
    timeout: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        latest = inspect_job_recovery(job_dir)
        if latest.get("classification") == expected:
            return latest
        time.sleep(0.05)
    raise AssertionError(f"Expected {expected}, last preview was {latest}")


def _dead_lock_record() -> dict[str, object]:
    return {
        "version": 1,
        "worker_id": "dead-worker",
        "pid": 999_999_999,
        "hostname": socket.gethostname(),
        "boot_id": None,
        "process_start_ticks": None,
        "acquired_at": "2026-01-01T00:00:00+00:00",
        "heartbeat_at": "2026-01-01T00:00:05+00:00",
    }


def test_active_worker_is_visible_and_cannot_be_recovered(jobs_root: Path) -> None:
    _, job_dir = create_job(title="Active", markdown="# Active\n", state="test")
    write_status(job_dir, status="running", step="pandoc-export", message="Building")

    assert acquire_job_lock(job_dir) is not None
    try:
        preview = inspect_job_recovery(job_dir)
        assert preview["classification"] == "active"
        assert preview["recoverable_actions"] == []
        assert preview["lock"]["owner_state"] == "active"

        with pytest.raises(RecoveryError, match="active"):
            recover_job(
                job_dir,
                target="queued",
                operator="test-operator",
                reason="must be refused",
            )
    finally:
        assert release_job_lock(job_dir) is True


def test_heartbeat_refresh_keeps_same_owner_record(
    jobs_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, job_dir = create_job(title="Heartbeat", markdown="# Heartbeat\n", state="test")
    record = acquire_job_lock(job_dir)
    assert record is not None

    monkeypatch.setattr(recovery, "utc_now", lambda: "2030-01-02T03:04:05+00:00")
    assert refresh_job_lock(job_dir) is True

    updated = json.loads((job_dir / ".lock").read_text(encoding="utf-8"))
    assert updated["worker_id"] == record["worker_id"]
    assert updated["pid"] == record["pid"]
    assert updated["acquired_at"] == record["acquired_at"]
    assert updated["heartbeat_at"] == "2030-01-02T03:04:05+00:00"
    assert release_job_lock(job_dir) is True


def test_terminated_worker_becomes_abandoned_and_can_be_requeued(
    jobs_root: Path,
) -> None:
    _, job_dir = create_job(title="Interrupted", markdown="# Interrupted\n", state="test")
    write_status(job_dir, status="running", step="pandoc-export", message="Building")

    source_before = (job_dir / "input" / "book.md").read_bytes()
    metadata_before = (job_dir / "metadata.json").read_bytes()
    events_before = read_job_events(job_dir)
    (job_dir / "work" / "partial.txt").write_text("partial work", encoding="utf-8")
    (job_dir / "output" / "partial.pdf").write_text("partial output", encoding="utf-8")
    (job_dir / "logs" / "build.log").write_text("partial log", encoding="utf-8")

    process = Process(target=_hold_job_lock, args=(str(job_dir),))
    process.start()
    try:
        active = _wait_for_classification(job_dir, "active")
        assert active["recoverable_actions"] == []

        process.terminate()
        process.join(timeout=5)
        assert not process.is_alive()

        abandoned = _wait_for_classification(job_dir, "abandoned")
        assert abandoned["recoverable_actions"] == ["queued", "failed"]

        result = recover_job(
            job_dir,
            target="queued",
            operator="test-operator",
            reason="controlled worker termination",
        )
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    status = read_status(job_dir)
    assert result["recovered"] is True
    assert result["target"] == "queued"
    assert status["status"] == "queued"
    assert status["step"] == "recovered"
    assert status["recovery_count"] == 1
    assert status["last_recovered_by"] == "test-operator"
    assert status["last_recovery_reason"] == "controlled worker termination"
    assert not (job_dir / ".lock").exists()

    assert (job_dir / "input" / "book.md").read_bytes() == source_before
    assert (job_dir / "metadata.json").read_bytes() == metadata_before
    assert (job_dir / "work" / "partial.txt").read_text(encoding="utf-8") == "partial work"
    assert (job_dir / "output" / "partial.pdf").read_text(encoding="utf-8") == "partial output"
    assert (job_dir / "logs" / "build.log").read_text(encoding="utf-8") == "partial log"

    events_after = read_job_events(job_dir)
    assert events_after[: len(events_before)] == events_before
    assert [event["event"] for event in events_after[-2:]] == [
        "recovery-authorised",
        "recovered",
    ]


def test_dead_lock_on_queued_job_is_previewed_and_cleared(jobs_root: Path) -> None:
    _, job_dir = create_job(title="Stale", markdown="# Stale\n", state="production")
    (job_dir / ".lock").write_text(
        json.dumps(_dead_lock_record()),
        encoding="utf-8",
    )

    preview = inspect_job_recovery(job_dir)
    assert preview["classification"] == "stale-lock"
    assert preview["recoverable_actions"] == ["queued"]

    recover_job(
        job_dir,
        target="queued",
        operator="test-operator",
        reason="dead lock owner",
    )

    status = read_status(job_dir)
    assert status["state"] == "production"
    assert status["status"] == "queued"
    assert status["step"] == "recovered"
    assert not (job_dir / ".lock").exists()


def test_running_job_without_lock_can_be_marked_failed(jobs_root: Path) -> None:
    _, job_dir = create_job(title="Unowned", markdown="# Unowned\n", state="test")
    write_status(job_dir, status="running", step="worker", message="Started")

    preview = inspect_job_recovery(job_dir)
    assert preview["classification"] == "abandoned"
    assert preview["reason"] == "Job is running but has no lock owner"

    result = recover_job(
        job_dir,
        target="failed",
        operator="test-operator",
        reason="worker exited before lock persisted",
    )

    status = read_status(job_dir)
    assert result["target"] == "failed"
    assert status["status"] == "failed"
    assert status["step"] == "recovered-interruption"
    assert not (job_dir / ".lock").exists()


def test_malformed_lock_is_uncertain_and_recovery_is_refused(jobs_root: Path) -> None:
    _, job_dir = create_job(title="Uncertain", markdown="# Uncertain\n", state="test")
    write_status(job_dir, status="running", step="worker", message="Started")
    (job_dir / ".lock").write_text("not-json", encoding="utf-8")

    preview = inspect_job_recovery(job_dir)
    assert preview["classification"] == "uncertain"
    assert preview["recoverable_actions"] == []

    with pytest.raises(RecoveryError, match="uncertain"):
        recover_job(
            job_dir,
            target="failed",
            operator="test-operator",
            reason="must not guess",
        )
