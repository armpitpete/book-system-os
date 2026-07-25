from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.job_queue import (
    append_job_event,
    list_jobs,
    parse_utc_timestamp,
    read_status,
    safe_int,
    utc_now,
    write_status,
)
from app.utils.atomic_files import atomic_write_json

LOCK_VERSION = 1
LOCK_FILENAME = ".lock"
RECOVERY_TARGETS = {"queued", "failed"}


class RecoveryError(RuntimeError):
    """Raised when a job cannot be recovered safely."""


def lock_path(job_dir: Path) -> Path:
    return job_dir / LOCK_FILENAME


def _boot_id() -> str | None:
    path = Path("/proc/sys/kernel/random/boot_id")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _process_start_ticks(pid: int) -> str | None:
    path = Path(f"/proc/{pid}/stat")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    closing_parenthesis = raw.rfind(")")
    if closing_parenthesis < 0:
        return None

    fields = raw[closing_parenthesis + 2 :].split()
    if len(fields) <= 19:
        return None

    return fields[19]


def _current_hostname() -> str:
    return socket.gethostname()


def build_lock_record(*, pid: int | None = None) -> dict[str, Any]:
    owner_pid = os.getpid() if pid is None else int(pid)
    now = utc_now()
    return {
        "version": LOCK_VERSION,
        "worker_id": uuid.uuid4().hex,
        "pid": owner_pid,
        "hostname": _current_hostname(),
        "boot_id": _boot_id(),
        "process_start_ticks": _process_start_ticks(owner_pid),
        "acquired_at": now,
        "heartbeat_at": now,
    }


def acquire_job_lock(job_dir: Path) -> dict[str, Any] | None:
    path = lock_path(job_dir)
    record = build_lock_record()
    encoded = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")

    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise

    return record


def read_lock_record(job_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = lock_path(job_dir)
    if not path.exists():
        return None, None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Lock file is not valid JSON: {exc}"

    if not isinstance(payload, dict):
        return None, "Lock file is not a JSON object"

    required = {
        "version",
        "worker_id",
        "pid",
        "hostname",
        "acquired_at",
        "heartbeat_at",
    }
    missing = sorted(required.difference(payload))
    if missing:
        return None, f"Lock file is missing required fields: {', '.join(missing)}"

    if payload.get("version") != LOCK_VERSION:
        return None, f"Unsupported lock version: {payload.get('version')!r}"

    if not isinstance(payload.get("worker_id"), str) or not payload["worker_id"].strip():
        return None, "Lock worker_id is invalid"

    try:
        pid = int(payload.get("pid"))
    except (TypeError, ValueError):
        return None, "Lock pid is invalid"
    if pid <= 0:
        return None, "Lock pid is invalid"
    payload["pid"] = pid

    if not isinstance(payload.get("hostname"), str) or not payload["hostname"].strip():
        return None, "Lock hostname is invalid"

    if parse_utc_timestamp(payload.get("acquired_at")) is None:
        return None, "Lock acquired_at is invalid"
    if parse_utc_timestamp(payload.get("heartbeat_at")) is None:
        return None, "Lock heartbeat_at is invalid"

    return payload, None


def _owner_state(record: dict[str, Any]) -> tuple[str, str]:
    hostname = str(record["hostname"])
    if hostname != _current_hostname():
        return "unknown", f"Lock belongs to remote host {hostname}"

    recorded_boot = record.get("boot_id")
    current_boot = _boot_id()
    if recorded_boot and current_boot and recorded_boot != current_boot:
        return "dead", "Recorded worker belongs to a previous system boot"

    pid = int(record["pid"])
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "dead", f"Worker process {pid} does not exist"
    except PermissionError:
        return "active", f"Worker process {pid} exists but is owned by another user"
    except OSError as exc:
        return "unknown", f"Could not verify worker process {pid}: {exc}"

    recorded_start = record.get("process_start_ticks")
    current_start = _process_start_ticks(pid)
    if recorded_start and current_start and str(recorded_start) != str(current_start):
        return "dead", f"PID {pid} has been reused by a different process"

    return "active", f"Worker process {pid} still owns the lock"


def refresh_job_lock(job_dir: Path) -> bool:
    record, error = read_lock_record(job_dir)
    if record is None:
        if error:
            raise RecoveryError(error)
        return False

    if record.get("hostname") != _current_hostname() or record.get("pid") != os.getpid():
        raise RecoveryError("Current process does not own the job lock")

    recorded_start = record.get("process_start_ticks")
    current_start = _process_start_ticks(os.getpid())
    if recorded_start and current_start and str(recorded_start) != str(current_start):
        raise RecoveryError("Current PID no longer matches the lock owner identity")

    record["heartbeat_at"] = utc_now()
    atomic_write_json(lock_path(job_dir), record)
    return True


def release_job_lock(job_dir: Path) -> bool:
    path = lock_path(job_dir)
    record, error = read_lock_record(job_dir)
    if record is None:
        if error:
            return False
        return True

    if record.get("hostname") != _current_hostname() or record.get("pid") != os.getpid():
        return False

    recorded_start = record.get("process_start_ticks")
    current_start = _process_start_ticks(os.getpid())
    if recorded_start and current_start and str(recorded_start) != str(current_start):
        return False

    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


def _heartbeat_age_seconds(record: dict[str, Any]) -> int | None:
    heartbeat = parse_utc_timestamp(record.get("heartbeat_at"))
    if heartbeat is None:
        return None
    age = datetime.now(timezone.utc) - heartbeat
    return max(0, int(age.total_seconds()))


def inspect_job_recovery(job_dir: Path) -> dict[str, Any]:
    status = read_status(job_dir)
    current_status = str(status.get("status", "unknown"))
    current_step = str(status.get("step", "unknown"))
    record, lock_error = read_lock_record(job_dir)

    result: dict[str, Any] = {
        "job_id": job_dir.name,
        "state": status.get("state"),
        "status": current_status,
        "step": current_step,
        "lock_present": lock_path(job_dir).exists(),
        "classification": "not-recoverable",
        "reason": "Job is not running and has no stale lock evidence",
        "recoverable_actions": [],
    }

    if record is None:
        if lock_error:
            result.update(
                classification="uncertain",
                reason=lock_error,
            )
        elif current_status == "running":
            result.update(
                classification="abandoned",
                reason="Job is running but has no lock owner",
                recoverable_actions=["queued", "failed"],
            )
        return result

    owner_state, owner_reason = _owner_state(record)
    result["lock"] = {
        "worker_id": record.get("worker_id"),
        "pid": record.get("pid"),
        "hostname": record.get("hostname"),
        "boot_id": record.get("boot_id"),
        "acquired_at": record.get("acquired_at"),
        "heartbeat_at": record.get("heartbeat_at"),
        "heartbeat_age_seconds": _heartbeat_age_seconds(record),
        "owner_state": owner_state,
    }

    if owner_state == "active":
        result.update(
            classification="active" if current_status == "running" else "owned-lock",
            reason=owner_reason,
        )
        return result

    if owner_state == "unknown":
        result.update(
            classification="uncertain",
            reason=owner_reason,
        )
        return result

    if current_status == "running":
        result.update(
            classification="abandoned",
            reason=owner_reason,
            recoverable_actions=["queued", "failed"],
        )
    elif current_status == "queued":
        result.update(
            classification="stale-lock",
            reason=owner_reason,
            recoverable_actions=["queued"],
        )
    else:
        result.update(
            classification="stale-lock",
            reason=(
                f"{owner_reason}; terminal or unknown status must be inspected "
                "without changing its state"
            ),
        )

    return result


def list_recovery_previews() -> list[dict[str, Any]]:
    previews = [inspect_job_recovery(job) for job in list_jobs()]
    return [item for item in previews if item["classification"] != "not-recoverable"]


def _same_lock_owner(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = ("worker_id", "pid", "hostname", "boot_id", "process_start_ticks", "acquired_at")
    return all(before.get(key) == after.get(key) for key in keys)


def recover_job(
    job_dir: Path,
    *,
    target: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    target_state = target.strip().lower()
    operator_name = operator.strip()
    recovery_reason = reason.strip()

    if target_state not in RECOVERY_TARGETS:
        raise RecoveryError("Recovery target must be queued or failed")
    if not operator_name:
        raise RecoveryError("Operator identity is required")
    if not recovery_reason:
        raise RecoveryError("Recovery reason is required")

    preview = inspect_job_recovery(job_dir)
    allowed = set(preview.get("recoverable_actions", []))
    if target_state not in allowed:
        raise RecoveryError(
            f"Job {job_dir.name} is {preview['classification']}: {preview['reason']}"
        )

    input_file = job_dir / "input" / "book.md"
    metadata_file = job_dir / "metadata.json"
    if not input_file.is_file():
        raise RecoveryError("Cannot recover job because input/book.md is missing")
    if not metadata_file.is_file():
        raise RecoveryError("Cannot recover job because metadata.json is missing")

    existing_record, lock_error = read_lock_record(job_dir)
    temporary_guard = False

    if preview["lock_present"]:
        if existing_record is None:
            raise RecoveryError(lock_error or "Lock ownership changed during recovery")
        preview_lock = preview.get("lock") or {}
        if existing_record.get("worker_id") != preview_lock.get("worker_id"):
            raise RecoveryError("Lock ownership changed during recovery")
    else:
        guard = acquire_job_lock(job_dir)
        if guard is None:
            raise RecoveryError("A worker acquired the job while recovery was being prepared")
        existing_record = guard
        temporary_guard = True

    status_before = read_status(job_dir)
    previous_status = str(status_before.get("status", "unknown"))
    previous_step = str(status_before.get("step", "unknown"))
    recovery_count = safe_int(status_before.get("recovery_count")) + 1
    recovered_at = utc_now()

    append_job_event(
        job_dir,
        "recovery-authorised",
        f"Operator authorised recovery to {target_state}",
        target=target_state,
        operator=operator_name,
        reason=recovery_reason,
        previous_status=previous_status,
        previous_step=previous_step,
        recovery_count=recovery_count,
    )

    if target_state == "queued":
        status_step = "recovered"
        status_message = "Interrupted job recovered and queued by operator"
    else:
        status_step = "recovered-interruption"
        status_message = "Interrupted job marked failed by operator"

    write_status(
        job_dir,
        status=target_state,
        step=status_step,
        message=status_message,
        extra={
            "recovery_count": recovery_count,
            "last_recovered_at": recovered_at,
            "last_recovered_by": operator_name,
            "last_recovery_reason": recovery_reason,
            "recovered_from_status": previous_status,
            "recovered_from_step": previous_step,
        },
    )

    append_job_event(
        job_dir,
        "recovered",
        status_message,
        target=target_state,
        operator=operator_name,
        reason=recovery_reason,
        previous_status=previous_status,
        previous_step=previous_step,
        recovery_count=recovery_count,
    )

    current_record, current_error = read_lock_record(job_dir)
    if current_record is None:
        if current_error:
            raise RecoveryError(current_error)
    elif existing_record is not None and not _same_lock_owner(existing_record, current_record):
        raise RecoveryError("Lock ownership changed before recovery could release it")
    else:
        try:
            lock_path(job_dir).unlink()
        except FileNotFoundError:
            pass

    if temporary_guard and lock_path(job_dir).exists():
        raise RecoveryError("Temporary recovery guard could not be released")

    return inspect_job_recovery(job_dir) | {
        "recovered": True,
        "target": target_state,
        "operator": operator_name,
        "recovery_count": recovery_count,
    }
