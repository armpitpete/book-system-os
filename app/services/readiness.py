from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.services.job_queue import parse_utc_timestamp, utc_now
from app.utils.atomic_files import atomic_write_json
from app.utils.paths import repo_root

WORKER_HEARTBEAT_VERSION = 1
WORKER_HEARTBEAT_FILENAME = "worker-heartbeat.json"
VALID_WORKER_STATES = {"starting", "idle", "running"}

DEFAULT_WORKER_SERVICE_HEARTBEAT_SECONDS = 2.0
DEFAULT_READINESS_WORKER_MAX_AGE_SECONDS = 15.0
DEFAULT_READINESS_MIN_FREE_BYTES = 512 * 1024 * 1024
DEFAULT_READINESS_QUEUED_WARN_SECONDS = 15 * 60
DEFAULT_READINESS_RUNNING_FAIL_SECONDS = 15 * 60

CHECK_PASS = "pass"
CHECK_WARNING = "warning"
CHECK_FAIL = "fail"


class ReadinessConfigError(RuntimeError):
    """Raised when H-05 readiness configuration is invalid."""


@dataclass(frozen=True)
class ReadinessConfig:
    worker_heartbeat_seconds: float
    worker_max_age_seconds: float
    minimum_free_bytes: int
    queued_warn_seconds: int
    running_fail_seconds: int


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ReadinessConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ReadinessConfigError(f"{name} must be greater than zero")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ReadinessConfigError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ReadinessConfigError(f"{name} must be greater than zero")
    return value


def readiness_config() -> ReadinessConfig:
    heartbeat_seconds = _positive_float(
        "BOOK_WORKER_SERVICE_HEARTBEAT_SECONDS",
        DEFAULT_WORKER_SERVICE_HEARTBEAT_SECONDS,
    )
    worker_max_age_seconds = _positive_float(
        "BOOK_READINESS_WORKER_MAX_AGE_SECONDS",
        DEFAULT_READINESS_WORKER_MAX_AGE_SECONDS,
    )
    if worker_max_age_seconds <= heartbeat_seconds:
        raise ReadinessConfigError(
            "BOOK_READINESS_WORKER_MAX_AGE_SECONDS must exceed "
            "BOOK_WORKER_SERVICE_HEARTBEAT_SECONDS"
        )

    return ReadinessConfig(
        worker_heartbeat_seconds=heartbeat_seconds,
        worker_max_age_seconds=worker_max_age_seconds,
        minimum_free_bytes=_positive_int(
            "BOOK_READINESS_MIN_FREE_BYTES",
            DEFAULT_READINESS_MIN_FREE_BYTES,
        ),
        queued_warn_seconds=_positive_int(
            "BOOK_READINESS_QUEUED_WARN_SECONDS",
            DEFAULT_READINESS_QUEUED_WARN_SECONDS,
        ),
        running_fail_seconds=_positive_int(
            "BOOK_READINESS_RUNNING_FAIL_SECONDS",
            DEFAULT_READINESS_RUNNING_FAIL_SECONDS,
        ),
    )


def jobs_root_path() -> Path:
    return repo_root() / "books" / "jobs"


def worker_heartbeat_path() -> Path:
    return repo_root() / "logs" / WORKER_HEARTBEAT_FILENAME


class WorkerServiceHeartbeat:
    """Publish an atomic service-level heartbeat while the worker is alive."""

    def __init__(self, *, interval_seconds: float | None = None) -> None:
        config = readiness_config()
        self.interval_seconds = (
            config.worker_heartbeat_seconds
            if interval_seconds is None
            else float(interval_seconds)
        )
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")

        self.worker_id = uuid.uuid4().hex
        self.started_at = utc_now()
        self._state = "starting"
        self._state_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _payload(self) -> dict[str, Any]:
        with self._state_lock:
            state = self._state

        return {
            "version": WORKER_HEARTBEAT_VERSION,
            "worker_id": self.worker_id,
            "started_at": self.started_at,
            "heartbeat_at": utc_now(),
            "state": state,
        }

    def write_now(self) -> None:
        with self._write_lock:
            atomic_write_json(
                worker_heartbeat_path(),
                self._payload(),
                sort_keys=True,
            )

    def set_state(self, state: str) -> None:
        if state not in VALID_WORKER_STATES:
            raise ValueError(f"Invalid worker heartbeat state: {state}")
        with self._state_lock:
            self._state = state
        self.write_now()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.write_now()
            except Exception as exc:
                print(
                    f"Worker service heartbeat write failed: {type(exc).__name__}",
                    flush=True,
                )

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Worker service heartbeat is already started")
        self.write_now()
        self._thread = threading.Thread(
            target=self._run,
            name="book-worker-service-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds + 1.0)


def _check(
    function: Callable[[], dict[str, Any]],
    *,
    fallback_message: str,
) -> dict[str, Any]:
    try:
        return function()
    except Exception:
        return {
            "status": CHECK_FAIL,
            "message": fallback_message,
        }


def _job_storage_check() -> dict[str, Any]:
    path = jobs_root_path()
    available = path.is_dir() and os.access(path, os.W_OK | os.X_OK)
    return {
        "status": CHECK_PASS if available else CHECK_FAIL,
        "message": (
            "Job storage is writable"
            if available
            else "Job storage is unavailable or not writable"
        ),
    }


def _worker_heartbeat_check(
    config: ReadinessConfig,
    *,
    now: datetime,
) -> dict[str, Any]:
    path = worker_heartbeat_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "status": CHECK_FAIL,
            "message": "Worker heartbeat is missing",
            "max_age_seconds": config.worker_max_age_seconds,
        }
    except (OSError, json.JSONDecodeError):
        return {
            "status": CHECK_FAIL,
            "message": "Worker heartbeat is unreadable",
            "max_age_seconds": config.worker_max_age_seconds,
        }

    if not isinstance(payload, dict):
        return {
            "status": CHECK_FAIL,
            "message": "Worker heartbeat is invalid",
            "max_age_seconds": config.worker_max_age_seconds,
        }

    if payload.get("version") != WORKER_HEARTBEAT_VERSION:
        return {
            "status": CHECK_FAIL,
            "message": "Worker heartbeat version is unsupported",
            "max_age_seconds": config.worker_max_age_seconds,
        }

    heartbeat_at = parse_utc_timestamp(payload.get("heartbeat_at"))
    state = payload.get("state")

    if heartbeat_at is None or state not in VALID_WORKER_STATES:
        return {
            "status": CHECK_FAIL,
            "message": "Worker heartbeat is invalid",
            "max_age_seconds": config.worker_max_age_seconds,
        }

    age_seconds = max(0.0, (now - heartbeat_at).total_seconds())
    fresh = age_seconds <= config.worker_max_age_seconds

    return {
        "status": CHECK_PASS if fresh else CHECK_FAIL,
        "message": (
            "Worker heartbeat is fresh"
            if fresh
            else "Worker heartbeat is stale"
        ),
        "age_seconds": round(age_seconds, 3),
        "max_age_seconds": config.worker_max_age_seconds,
        "worker_state": state,
    }


def _tool_check(name: str) -> dict[str, Any]:
    executable = shutil.which(name)
    available = bool(executable and os.access(executable, os.X_OK))
    return {
        "status": CHECK_PASS if available else CHECK_FAIL,
        "message": (
            f"{name} is available"
            if available
            else f"{name} is unavailable"
        ),
    }


def _disk_space_check(config: ReadinessConfig) -> dict[str, Any]:
    path = jobs_root_path()
    if not path.is_dir():
        return {
            "status": CHECK_FAIL,
            "message": "Free disk space cannot be measured",
            "minimum_free_bytes": config.minimum_free_bytes,
        }

    free_bytes = int(shutil.disk_usage(path).free)
    enough = free_bytes >= config.minimum_free_bytes
    return {
        "status": CHECK_PASS if enough else CHECK_FAIL,
        "message": (
            "Minimum free disk space is available"
            if enough
            else "Free disk space is below the configured minimum"
        ),
        "free_bytes": free_bytes,
        "minimum_free_bytes": config.minimum_free_bytes,
    }


def _active_work_check(
    config: ReadinessConfig,
    *,
    now: datetime,
) -> dict[str, Any]:
    path = jobs_root_path()
    if not path.is_dir():
        return {
            "status": CHECK_FAIL,
            "message": "Active work cannot be inspected",
        }

    old_queued = 0
    old_running = 0
    invalid_active_records = 0
    oldest_queued_age = 0.0
    oldest_running_age = 0.0

    for job_dir in path.iterdir():
        if not job_dir.is_dir():
            continue

        try:
            status = json.loads(
                (job_dir / "status.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(status, dict):
            continue

        current = status.get("status")
        if current not in {"queued", "running"}:
            continue

        updated_at = parse_utc_timestamp(status.get("updated_at"))
        if updated_at is None:
            invalid_active_records += 1
            continue

        age_seconds = max(0.0, (now - updated_at).total_seconds())

        if current == "queued":
            oldest_queued_age = max(oldest_queued_age, age_seconds)
            if age_seconds > config.queued_warn_seconds:
                old_queued += 1
        else:
            oldest_running_age = max(oldest_running_age, age_seconds)
            if age_seconds > config.running_fail_seconds:
                old_running += 1

    if invalid_active_records or old_running:
        status_value = CHECK_FAIL
        message = "Suspicious running or invalid active work was detected"
    elif old_queued:
        status_value = CHECK_WARNING
        message = "Suspiciously old queued work was detected"
    else:
        status_value = CHECK_PASS
        message = "No suspiciously old active work was detected"

    return {
        "status": status_value,
        "message": message,
        "old_queued_count": old_queued,
        "old_running_count": old_running,
        "invalid_active_record_count": invalid_active_records,
        "oldest_queued_age_seconds": round(oldest_queued_age, 3),
        "oldest_running_age_seconds": round(oldest_running_age, 3),
        "queued_warn_seconds": config.queued_warn_seconds,
        "running_fail_seconds": config.running_fail_seconds,
    }


def readiness_report(*, now: datetime | None = None) -> dict[str, Any]:
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    else:
        checked_at = checked_at.astimezone(timezone.utc)

    try:
        config = readiness_config()
    except ReadinessConfigError as exc:
        return {
            "ready": False,
            "status": "not-ready",
            "checked_at": checked_at.isoformat(timespec="seconds"),
            "checks": {
                "configuration": {
                    "status": CHECK_FAIL,
                    "message": str(exc),
                }
            },
        }

    checks = {
        "configuration": {
            "status": CHECK_PASS,
            "message": "Readiness configuration is valid",
        },
        "job_storage": _check(
            _job_storage_check,
            fallback_message="Job storage check failed",
        ),
        "worker": _check(
            lambda: _worker_heartbeat_check(config, now=checked_at),
            fallback_message="Worker heartbeat check failed",
        ),
        "pandoc": _check(
            lambda: _tool_check("pandoc"),
            fallback_message="Pandoc availability check failed",
        ),
        "xelatex": _check(
            lambda: _tool_check("xelatex"),
            fallback_message="XeLaTeX availability check failed",
        ),
        "disk_space": _check(
            lambda: _disk_space_check(config),
            fallback_message="Free disk space check failed",
        ),
        "active_work": _check(
            lambda: _active_work_check(config, now=checked_at),
            fallback_message="Active work age check failed",
        ),
    }

    statuses = {value["status"] for value in checks.values()}
    if CHECK_FAIL in statuses:
        overall_status = "not-ready"
        ready = False
    elif CHECK_WARNING in statuses:
        overall_status = "degraded"
        ready = False
    else:
        overall_status = "ready"
        ready = True

    return {
        "ready": ready,
        "status": overall_status,
        "checked_at": checked_at.isoformat(timespec="seconds"),
        "checks": checks,
    }
