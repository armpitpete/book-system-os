from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.pipeline import run_pipeline as pipeline_module
from app.pipeline.exporters import ExportTimeoutError, run_command
from app.services.job_queue import create_job, read_status
from app.services.resource_limits import (
    ResourceLimitError,
    check_job_admission,
    enforce_job_storage_limits,
    new_job_reservation_bytes,
    path_size_bytes,
)

LIMIT_ENV = (
    "BOOK_MAX_REQUEST_BYTES",
    "BOOK_MAX_MANUSCRIPT_BYTES",
    "BOOK_MAX_ACTIVE_JOBS",
    "BOOK_EXPORT_COMMAND_TIMEOUT_SECONDS",
    "BOOK_MAX_JOB_BYTES",
    "BOOK_MAX_TOTAL_STORAGE_BYTES",
)


@pytest.fixture(autouse=True)
def isolated_limits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    for name in LIMIT_ENV:
        monkeypatch.delenv(name, raising=False)


def job_dirs(root: Path) -> list[Path]:
    base = root / "books" / "jobs"
    if not base.exists():
        return []
    return sorted(path for path in base.iterdir() if path.is_dir())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_request_body_limit_accepts_exact_boundary_and_rejects_one_more(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = b'{"title":"A","content":"# A"}'
    monkeypatch.setenv("BOOK_MAX_REQUEST_BYTES", str(len(payload)))
    client = TestClient(app)

    accepted = client.post(
        "/api/submit",
        content=payload,
        headers={"content-type": "application/json"},
    )
    assert accepted.status_code == 200

    rejected = client.post(
        "/api/submit",
        content=payload + b" ",
        headers={"content-type": "application/json"},
    )
    assert rejected.status_code == 413
    assert rejected.json()["code"] == "request-too-large"
    assert rejected.json()["limit"] == len(payload)
    assert rejected.json()["actual"] == len(payload) + 1
    assert len(job_dirs(tmp_path)) == 1


def test_manuscript_limit_uses_utf8_bytes_at_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_MAX_MANUSCRIPT_BYTES", "4")

    _, job_dir = create_job(title="Exact", markdown="éé", state="test")
    assert (job_dir / "input" / "book.md").read_text(encoding="utf-8") == "éé"

    with pytest.raises(ResourceLimitError) as exc_info:
        create_job(title="Too large", markdown="ééx", state="test")

    assert exc_info.value.code == "manuscript-too-large"
    assert exc_info.value.limit == 4
    assert exc_info.value.actual == 5


def test_api_reports_manuscript_limit_without_creating_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BOOK_MAX_MANUSCRIPT_BYTES", "3")
    client = TestClient(app)

    response = client.post(
        "/api/submit",
        json={"title": "Large", "content": "1234"},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "manuscript-too-large"
    assert job_dirs(tmp_path) == []


def test_queue_capacity_rejects_at_boundary_and_preserves_existing_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BOOK_MAX_ACTIVE_JOBS", "1")
    _, first = create_job(title="First", markdown="# First", state="production")
    source = first / "input" / "book.md"
    source_hash = sha256(source)

    with pytest.raises(ResourceLimitError) as exc_info:
        create_job(title="Second", markdown="# Second", state="production")

    assert exc_info.value.code == "queue-capacity-reached"
    assert exc_info.value.limit == 1
    assert exc_info.value.actual == 1
    assert job_dirs(tmp_path) == [first]
    assert sha256(source) == source_hash


def test_api_reports_queue_saturation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BOOK_MAX_ACTIVE_JOBS", "1")
    create_job(title="Existing", markdown="# Existing", state="test")
    client = TestClient(app)

    response = client.post(
        "/api/submit",
        json={"title": "Blocked", "content": "# Blocked"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "queue-capacity-reached"
    assert len(job_dirs(tmp_path)) == 1


def test_new_job_storage_reservations_accept_exact_and_reject_over(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manuscript = "x"
    reservation = new_job_reservation_bytes(manuscript)
    monkeypatch.setenv("BOOK_MAX_JOB_BYTES", str(reservation))
    monkeypatch.setenv("BOOK_MAX_TOTAL_STORAGE_BYTES", str(reservation))

    _, accepted = create_job(title="Exact", markdown=manuscript, state="test")
    assert accepted.exists()

    second_root = tmp_path / "below-total"
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(second_root))
    monkeypatch.setenv("BOOK_MAX_JOB_BYTES", str(reservation))
    monkeypatch.setenv("BOOK_MAX_TOTAL_STORAGE_BYTES", str(reservation - 1))

    with pytest.raises(ResourceLimitError) as total_error:
        check_job_admission(manuscript)
    assert total_error.value.code == "total-storage-capacity-reached"

    third_root = tmp_path / "below-job"
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(third_root))
    monkeypatch.setenv("BOOK_MAX_JOB_BYTES", str(reservation - 1))
    monkeypatch.setenv("BOOK_MAX_TOTAL_STORAGE_BYTES", str(reservation * 2))

    with pytest.raises(ResourceLimitError) as job_error:
        check_job_admission(manuscript)
    assert job_error.value.code == "job-storage-reservation-exceeded"


def test_per_job_runtime_limit_accepts_exact_and_preserves_data_on_excess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_dir = tmp_path / "books" / "jobs" / "job"
    job_dir.mkdir(parents=True)
    payload = job_dir / "payload.bin"
    payload.write_bytes(b"1" * 10)
    monkeypatch.setenv("BOOK_MAX_JOB_BYTES", "10")
    monkeypatch.setenv("BOOK_MAX_TOTAL_STORAGE_BYTES", "100")

    evidence = enforce_job_storage_limits(job_dir)
    assert evidence["job_bytes"] == 10

    payload.write_bytes(b"1" * 11)
    before = sha256(payload)

    with pytest.raises(ResourceLimitError) as exc_info:
        enforce_job_storage_limits(job_dir)

    assert exc_info.value.code == "job-storage-limit-exceeded"
    assert sha256(payload) == before


def test_total_runtime_storage_limit_preserves_all_existing_jobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    jobs = tmp_path / "books" / "jobs"
    first = jobs / "first"
    second = jobs / "second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    first_file = first / "one.bin"
    second_file = second / "two.bin"
    first_file.write_bytes(b"a" * 10)
    second_file.write_bytes(b"b" * 10)
    hashes = (sha256(first_file), sha256(second_file))

    monkeypatch.setenv("BOOK_MAX_JOB_BYTES", "100")
    monkeypatch.setenv("BOOK_MAX_TOTAL_STORAGE_BYTES", "19")

    with pytest.raises(ResourceLimitError) as exc_info:
        enforce_job_storage_limits(first)

    assert exc_info.value.code == "total-storage-limit-exceeded"
    assert (sha256(first_file), sha256(second_file)) == hashes


def test_invalid_limit_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_MAX_ACTIVE_JOBS", "0")

    with pytest.raises(ResourceLimitError) as exc_info:
        check_job_admission("# Book")

    assert exc_info.value.code == "invalid-resource-limit-config"
    assert exc_info.value.status_code == 503


@pytest.mark.skipif(os.name != "posix", reason="process-group proof requires POSIX")
def test_export_timeout_terminates_descendant_process_group(tmp_path: Path) -> None:
    child_pid_file = tmp_path / "child.pid"
    script = tmp_path / "stall.py"
    script.write_text(
        """
import subprocess
import sys
import time
from pathlib import Path

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
time.sleep(60)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    log_file = tmp_path / "build.log"

    started = time.monotonic()
    with pytest.raises(ExportTimeoutError):
        run_command(
            [sys.executable, str(script), str(child_pid_file)],
            log_file,
            timeout_seconds=0.5,
        )
    assert time.monotonic() - started < 5
    assert "Command timed out after 0.5 seconds" in log_file.read_text(encoding="utf-8")
    assert child_pid_file.exists()

    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    for _ in range(100):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"descendant process remained alive: {child_pid}")


def test_pipeline_records_runtime_storage_failure_without_corrupting_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, job_dir = create_job(title="Storage", markdown="# Storage", state="test")
    input_file = job_dir / "input" / "book.md"
    input_hash = sha256(input_file)
    oversized = job_dir / "work" / "oversized.bin"
    oversized.write_bytes(b"x" * 32)
    current_size = path_size_bytes(job_dir)

    monkeypatch.setenv("BOOK_MAX_JOB_BYTES", str(current_size - 1))
    monkeypatch.setenv("BOOK_MAX_TOTAL_STORAGE_BYTES", str(current_size * 10))

    assert pipeline_module.run_pipeline(job_dir) == 1

    status = read_status(job_dir)
    assert status["status"] == "failed"
    assert status["step"] == "resource-limit"
    assert status["limit_code"] == "job-storage-limit-exceeded"
    assert "per-job limit" in status["message"]
    assert (job_dir / "logs" / "error.log").is_file()
    assert not (job_dir / "manifest.json").exists()
    assert sha256(input_file) == input_hash


def test_pipeline_records_export_timeout_as_controlled_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, job_dir = create_job(title="Timeout", markdown="# Timeout", state="test")
    input_file = job_dir / "input" / "book.md"
    input_hash = sha256(input_file)

    def stalled_export(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise ExportTimeoutError("Command timed out after 1 seconds: pandoc")

    monkeypatch.setattr(pipeline_module, "pandoc_export", stalled_export)

    assert pipeline_module.run_pipeline(job_dir) == 1

    status = read_status(job_dir)
    assert status["status"] == "failed"
    assert status["step"] == "export-timeout"
    assert "timed out" in status["message"]
    assert (job_dir / "logs" / "error.log").is_file()
    assert sha256(input_file) == input_hash
