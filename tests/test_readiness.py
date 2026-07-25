from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.services import readiness as readiness_module
from app.services.job_queue import create_job, write_status
from app.services.readiness import (
    WorkerServiceHeartbeat,
    readiness_report,
    worker_heartbeat_path,
)

NOW = datetime(2026, 7, 25, 20, 0, 0, tzinfo=timezone.utc)


def write_worker_heartbeat(
    *,
    heartbeat_at: datetime | None = None,
    state: str = "idle",
) -> Path:
    heartbeat_at = heartbeat_at or datetime.now(timezone.utc)
    path = worker_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "worker_id": "test-worker",
                "started_at": (heartbeat_at - timedelta(minutes=1)).isoformat(
                    timespec="seconds"
                ),
                "heartbeat_at": heartbeat_at.isoformat(timespec="seconds"),
                "state": state,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def ready_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.setenv("BOOK_WORKER_SERVICE_HEARTBEAT_SECONDS", "1")
    monkeypatch.setenv("BOOK_READINESS_WORKER_MAX_AGE_SECONDS", "10")
    monkeypatch.setenv("BOOK_READINESS_MIN_FREE_BYTES", "100")
    monkeypatch.setenv("BOOK_READINESS_QUEUED_WARN_SECONDS", "10")
    monkeypatch.setenv("BOOK_READINESS_RUNNING_FAIL_SECONDS", "10")

    (tmp_path / "books" / "jobs").mkdir(parents=True)
    (tmp_path / "logs").mkdir(parents=True)

    monkeypatch.setattr(
        readiness_module.shutil,
        "which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        readiness_module.os,
        "access",
        lambda _path, _mode: True,
    )
    monkeypatch.setattr(
        readiness_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=1_000_000,
            used=100_000,
            free=900_000,
        ),
    )

    write_worker_heartbeat()
    return tmp_path


def test_all_dependencies_report_ready(ready_root: Path) -> None:
    report = readiness_report(now=NOW)

    assert report["ready"] is True
    assert report["status"] == "ready"
    assert {
        name: check["status"]
        for name, check in report["checks"].items()
    } == {
        "configuration": "pass",
        "job_storage": "pass",
        "worker": "pass",
        "pandoc": "pass",
        "xelatex": "pass",
        "disk_space": "pass",
        "active_work": "pass",
    }


def test_liveness_remains_ok_when_readiness_fails(
    ready_root: Path,
) -> None:
    worker_heartbeat_path().unlink()
    client = TestClient(app)

    health = client.get("/health")
    ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json()["ready"] is False
    assert ready.json()["checks"]["worker"]["status"] == "fail"


def test_ready_endpoint_returns_200_for_ready_service(
    ready_root: Path,
) -> None:
    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["ready"] is True


def test_missing_or_unwritable_job_storage_fails(
    ready_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = ready_root / "books" / "jobs"

    monkeypatch.setattr(
        readiness_module.os,
        "access",
        lambda path, _mode: Path(path) != jobs,
    )

    report = readiness_report(now=NOW)

    assert report["ready"] is False
    assert report["checks"]["job_storage"]["status"] == "fail"
    assert str(ready_root) not in json.dumps(report)


def test_stale_worker_heartbeat_fails(ready_root: Path) -> None:
    write_worker_heartbeat(
        heartbeat_at=NOW - timedelta(seconds=11),
    )

    report = readiness_report(now=NOW)
    worker = report["checks"]["worker"]

    assert report["ready"] is False
    assert worker["status"] == "fail"
    assert worker["message"] == "Worker heartbeat is stale"
    assert worker["age_seconds"] == 11.0
    assert worker["max_age_seconds"] == 10.0


@pytest.mark.parametrize("missing", ["pandoc", "xelatex"])
def test_each_missing_toolchain_dependency_fails(
    ready_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    monkeypatch.setattr(
        readiness_module.shutil,
        "which",
        lambda name: None if name == missing else f"/usr/bin/{name}",
    )

    report = readiness_report(now=NOW)

    assert report["ready"] is False
    assert report["checks"][missing]["status"] == "fail"


def test_low_free_space_fails(
    ready_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=1_000,
            used=950,
            free=50,
        ),
    )

    report = readiness_report(now=NOW)
    disk = report["checks"]["disk_space"]

    assert report["ready"] is False
    assert disk["status"] == "fail"
    assert disk["free_bytes"] == 50
    assert disk["minimum_free_bytes"] == 100


def set_status_age(
    job_dir: Path,
    *,
    status: str,
    age_seconds: int,
) -> None:
    write_status(
        job_dir,
        status=status,
        step="acceptance",
        message="Age test",
    )
    status_path = job_dir / "status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    payload["updated_at"] = (
        NOW - timedelta(seconds=age_seconds)
    ).isoformat(timespec="seconds")
    status_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_old_queued_work_reports_degraded_warning(
    ready_root: Path,
) -> None:
    _, job_dir = create_job(
        title="Old queued",
        markdown="# Old queued",
        state="test",
    )
    set_status_age(job_dir, status="queued", age_seconds=11)

    report = readiness_report(now=NOW)
    active = report["checks"]["active_work"]

    assert report["ready"] is False
    assert report["status"] == "degraded"
    assert active["status"] == "warning"
    assert active["old_queued_count"] == 1
    assert active["old_running_count"] == 0


def test_old_running_work_reports_not_ready_failure(
    ready_root: Path,
) -> None:
    _, job_dir = create_job(
        title="Old running",
        markdown="# Old running",
        state="test",
    )
    set_status_age(job_dir, status="running", age_seconds=11)

    report = readiness_report(now=NOW)
    active = report["checks"]["active_work"]

    assert report["ready"] is False
    assert report["status"] == "not-ready"
    assert active["status"] == "fail"
    assert active["old_running_count"] == 1


def test_invalid_readiness_configuration_fails_closed(
    ready_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_READINESS_WORKER_MAX_AGE_SECONDS", "1")

    report = readiness_report(now=NOW)

    assert report["ready"] is False
    assert report["status"] == "not-ready"
    assert report["checks"]["configuration"]["status"] == "fail"
    assert "must exceed" in report["checks"]["configuration"]["message"]


def test_diagnostics_do_not_expose_secrets_paths_or_manuscript(
    ready_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_API_KEY", "do-not-expose-this-key")
    manuscript = "PRIVATE-MANUSCRIPT-CONTENT"
    create_job(
        title="Private",
        markdown=manuscript,
        state="test",
    )

    report = readiness_report(now=NOW)
    encoded = json.dumps(report, sort_keys=True)

    assert "do-not-expose-this-key" not in encoded
    assert manuscript not in encoded
    assert str(ready_root) not in encoded
    assert "worker_id" not in encoded


def snapshot_files(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            payload = path.read_bytes()
            snapshot[str(path.relative_to(root))] = (
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
    return snapshot


def test_readiness_checks_are_non_mutating(ready_root: Path) -> None:
    create_job(
        title="Finished",
        markdown="# Finished",
        state="test",
    )
    before = snapshot_files(ready_root)

    readiness_report(now=NOW)

    after = snapshot_files(ready_root)
    assert after == before


def test_worker_service_heartbeat_is_atomic_and_records_state(
    ready_root: Path,
) -> None:
    path = worker_heartbeat_path()
    path.unlink()

    heartbeat = WorkerServiceHeartbeat(interval_seconds=0.05)
    heartbeat.start()
    heartbeat.set_state("running")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["state"] == "running"
    assert payload["worker_id"] == heartbeat.worker_id
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))

    heartbeat.stop()


def test_worker_service_heartbeat_refreshes_in_background(
    ready_root: Path,
) -> None:
    path = worker_heartbeat_path()
    path.unlink()

    heartbeat = WorkerServiceHeartbeat(interval_seconds=0.05)
    heartbeat.start()
    first_mtime = path.stat().st_mtime_ns

    for _ in range(100):
        if path.stat().st_mtime_ns > first_mtime:
            break
        time.sleep(0.01)
    else:
        pytest.fail("worker service heartbeat did not refresh")

    heartbeat.stop()
