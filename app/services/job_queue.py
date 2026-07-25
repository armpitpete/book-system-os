from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services.resource_limits import check_job_admission
from app.utils.atomic_files import atomic_write_json
from app.utils.paths import jobs_dir

SAFE_TITLE_RE = re.compile(r"[^a-zA-Z0-9._ -]+")

JOB_STATES = {"test", "production", "archived"}
DEFAULT_JOB_STATE = "production"
ARCHIVABLE_JOB_STATUSES = {"done", "failed", "cancelled"}


def normalise_job_state(value: str | None) -> str:
    raw = (value or DEFAULT_JOB_STATE).strip().lower()
    return raw if raw in JOB_STATES else DEFAULT_JOB_STATE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify_title(title: str) -> str:
    title = SAFE_TITLE_RE.sub("", title).strip().lower()
    title = re.sub(r"\s+", "-", title)
    return title[:80] or "untitled"


def status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def events_path(job_dir: Path) -> Path:
    return job_dir / "events.jsonl"


def safe_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def append_job_event(job_dir: Path, event: str, message: str = "", **fields: Any) -> None:
    payload = {
        "created_at": utc_now(),
        "event": event,
        "message": message,
        **fields,
    }
    with events_path(job_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def read_job_events(job_dir: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    path = events_path(job_dir)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)

    return events[-limit:]


def write_status(
    job_dir: Path,
    *,
    status: str,
    step: str,
    message: str = "",
    state: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    old: dict[str, Any] = {}
    path = status_path(job_dir)
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}

    data = {
        **old,
        "state": normalise_job_state(state or old.get("state")),
        "status": status,
        "step": step,
        "message": message,
        "updated_at": utc_now(),
    }
    if extra:
        data.update(extra)
    atomic_write_json(path, data)


def set_job_state(job_dir: Path, state: str) -> None:
    path = status_path(job_dir)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except json.JSONDecodeError:
            data = {}

    data["state"] = normalise_job_state(state)
    data["updated_at"] = utc_now()
    atomic_write_json(path, data)


def parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def job_created_at(job_dir: Path, status: dict[str, Any]) -> datetime | None:
    metadata_file = job_dir / "metadata.json"
    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}
        if isinstance(metadata, dict):
            created_at = parse_utc_timestamp(metadata.get("created_at"))
            if created_at is not None:
                return created_at

    return parse_utc_timestamp(status.get("updated_at"))


def cleanup_old_test_jobs(*, older_than_days: int = 7, dry_run: bool = True) -> dict[str, Any]:
    days = max(1, int(older_than_days))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    candidates: list[dict[str, Any]] = []
    archived_count = 0

    for job in list_jobs():
        status = read_status(job)
        job_state = status.get("state")
        job_status = status.get("status")

        if job_state != "test":
            continue
        if job_status in {"queued", "running"}:
            continue
        if job_status not in ARCHIVABLE_JOB_STATUSES:
            continue

        created_at = job_created_at(job, status)
        if created_at is None or created_at > cutoff:
            continue

        candidate = {
            "job_id": job.name,
            "status": job_status,
            "created_at": created_at.isoformat(timespec="seconds"),
            "age_days": max(0, (now - created_at).days),
        }
        candidates.append(candidate)

        if dry_run:
            continue

        archived_at = utc_now()
        status["state"] = "archived"
        status["archived_at"] = archived_at
        status["archive_reason"] = f"Archived by cleanup helper; older than {days} days"
        status["updated_at"] = archived_at
        atomic_write_json(status_path(job), status)
        append_job_event(
            job,
            "archived",
            f"Archived by cleanup helper; older than {days} days",
            older_than_days=days,
        )
        archived_count += 1

    return {
        "dry_run": dry_run,
        "older_than_days": days,
        "eligible_count": len(candidates),
        "archived_count": archived_count,
        "jobs": candidates,
    }


def retry_job(job_dir: Path) -> None:
    status = read_status(job_dir)
    if status.get("status") != "failed":
        raise ValueError("Only failed jobs can be retried")

    input_file = job_dir / "input" / "book.md"
    metadata_file = job_dir / "metadata.json"
    if not input_file.is_file():
        raise FileNotFoundError("Cannot retry job because input/book.md is missing")
    if not metadata_file.is_file():
        raise FileNotFoundError("Cannot retry job because metadata.json is missing")

    retry_count = safe_int(status.get("retry_count")) + 1
    retry_at = utc_now()

    for name in ("work", "output", "logs"):
        path = job_dir / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    lock = job_dir / ".lock"
    if lock.exists():
        lock.unlink()

    write_status(
        job_dir,
        status="queued",
        step="retry",
        message="Job queued for retry",
        extra={"retry_count": retry_count, "last_retry_at": retry_at},
    )
    append_job_event(
        job_dir,
        "retry",
        "Job queued for retry",
        retry_count=retry_count,
    )


def read_status(job_dir: Path) -> dict[str, Any]:
    path = status_path(job_dir)
    if not path.exists():
        return {
            "state": DEFAULT_JOB_STATE,
            "status": "unknown",
            "step": "missing-status",
            "message": "No status file",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "state": DEFAULT_JOB_STATE,
            "status": "broken",
            "step": "bad-status-json",
            "message": "Status file is invalid JSON",
        }

    if not isinstance(data, dict):
        return {
            "state": DEFAULT_JOB_STATE,
            "status": "broken",
            "step": "bad-status-json",
            "message": "Status file is not a JSON object",
        }

    data["state"] = normalise_job_state(data.get("state"))
    return data


def create_job(*, title: str, markdown: str, state: str = DEFAULT_JOB_STATE) -> tuple[str, Path]:
    check_job_admission(markdown)

    job_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    job_dir = jobs_dir() / job_id
    (job_dir / "input").mkdir(parents=True, exist_ok=False)
    (job_dir / "work").mkdir(parents=True, exist_ok=True)
    (job_dir / "output").mkdir(parents=True, exist_ok=True)
    (job_dir / "logs").mkdir(parents=True, exist_ok=True)

    meta = {
        "job_id": job_id,
        "title": title.strip() or "Untitled",
        "slug": slugify_title(title),
        "created_at": utc_now(),
    }
    atomic_write_json(job_dir / "metadata.json", meta)
    (job_dir / "input" / "book.md").write_text(markdown, encoding="utf-8")
    write_status(job_dir, status="queued", step="waiting", message="Job queued", state=state)
    append_job_event(
        job_dir,
        "created",
        "Job queued",
        state=normalise_job_state(state),
        status="queued",
    )
    return job_id, job_dir


def list_jobs() -> list[Path]:
    base = jobs_dir()
    return sorted([p for p in base.iterdir() if p.is_dir()], reverse=True)


def get_job(job_id: str) -> Path | None:
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        return None
    path = jobs_dir() / job_id
    return path if path.exists() and path.is_dir() else None


def queued_jobs() -> list[Path]:
    jobs = []
    for job in reversed(list_jobs()):
        status = read_status(job)
        if status.get("status") == "queued":
            jobs.append(job)
    return jobs
