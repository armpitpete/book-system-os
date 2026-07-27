from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import app as app_module
from app.services import readiness as readiness_module
from app.services import readiness_guard
from app.services import worker as worker_module
from app.services.readiness import worker_heartbeat_path

NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)


def write_heartbeat(*, state: str, heartbeat_at: datetime = NOW) -> None:
    path = worker_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "worker_id": "private-worker-identity",
                "started_at": (heartbeat_at - timedelta(seconds=1)).isoformat(
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

    write_heartbeat(state="idle")
    return tmp_path


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


def test_application_uses_crash_loop_readiness_guard() -> None:
    source = inspect.getsource(app_module)
    assert "app.services.readiness_guard import readiness_report" in source


def test_fresh_starting_heartbeat_is_not_ready(ready_root: Path) -> None:
    write_heartbeat(state="starting")

    report = readiness_guard.readiness_report(now=NOW)
    worker = report["checks"]["worker"]

    assert report["ready"] is False
    assert report["status"] == "not-ready"
    assert worker["status"] == "fail"
    assert worker["worker_state"] == "starting"
    assert worker["message"] == "Worker startup checks have not completed"
    assert "private-worker-identity" not in json.dumps(report)


def test_successful_idle_heartbeat_remains_ready(ready_root: Path) -> None:
    report = readiness_guard.readiness_report(now=NOW)

    assert report["ready"] is True
    assert report["status"] == "ready"
    assert report["checks"]["worker"]["status"] == "pass"
    assert report["checks"]["active_work"]["unreadable_job_record_count"] == 0


def test_unreadable_retained_job_fails_without_identity_or_path(
    ready_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_job_id = "private-unreadable-job"
    job_dir = ready_root / "books" / "jobs" / private_job_id
    job_dir.mkdir()
    status_path = job_dir / "status.json"
    status_path.write_text(
        json.dumps(
            {
                "state": "test",
                "status": "done",
                "step": "complete",
                "updated_at": NOW.isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args, **kwargs):
        if path == status_path:
            raise PermissionError("private path must not be exposed")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    before = snapshot_files(ready_root)

    report = readiness_guard.readiness_report(now=NOW)

    after = snapshot_files(ready_root)
    active = report["checks"]["active_work"]
    encoded = json.dumps(report, sort_keys=True)

    assert report["ready"] is False
    assert report["status"] == "not-ready"
    assert active["status"] == "fail"
    assert active["message"] == "Unreadable retained job records were detected"
    assert active["unreadable_job_record_count"] == 1
    assert private_job_id not in encoded
    assert str(ready_root) not in encoded
    assert before == after


class StopLoop(RuntimeError):
    pass


class FakeHeartbeat:
    instances: list["FakeHeartbeat"] = []

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.states: list[str] = []
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def set_state(self, state: str) -> None:
        self.states.append(state)

    def stop(self) -> None:
        self.stopped = True


def test_worker_keeps_starting_state_when_initial_queue_scan_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeHeartbeat.instances.clear()
    monkeypatch.setattr(worker_module, "WorkerServiceHeartbeat", FakeHeartbeat)
    monkeypatch.setattr(
        worker_module,
        "process_next_jobs",
        lambda _heartbeat: (_ for _ in ()).throw(PermissionError("unreadable")),
    )
    monkeypatch.setattr(
        worker_module.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(StopLoop()),
    )

    with pytest.raises(StopLoop):
        worker_module.run_forever()

    heartbeat = FakeHeartbeat.instances[-1]
    assert heartbeat.started is True
    assert heartbeat.states == ["starting"]
    assert heartbeat.stopped is True


def test_worker_publishes_idle_only_after_successful_queue_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeHeartbeat.instances.clear()
    monkeypatch.setattr(worker_module, "WorkerServiceHeartbeat", FakeHeartbeat)
    monkeypatch.setattr(worker_module, "process_next_jobs", lambda _heartbeat: 0)
    monkeypatch.setattr(
        worker_module.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(StopLoop()),
    )

    with pytest.raises(StopLoop):
        worker_module.run_forever()

    heartbeat = FakeHeartbeat.instances[-1]
    assert heartbeat.started is True
    assert heartbeat.states == ["idle"]
    assert heartbeat.stopped is True
