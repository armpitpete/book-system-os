from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.utils.paths import jobs_dir

SAFE_TITLE_RE = re.compile(r"[^a-zA-Z0-9._ -]+")

JOB_STATES = {"test", "production", "archived"}
DEFAULT_JOB_STATE = "production"


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


def write_status(job_dir: Path, *, status: str, step: str, message: str = "", state: str | None = None) -> None:
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
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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

    for name in ("work", "output", "logs"):
        path = job_dir / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    lock = job_dir / ".lock"
    if lock.exists():
        lock.unlink()

    write_status(job_dir, status="queued", step="retry", message="Job queued for retry")


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
    (job_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (job_dir / "input" / "book.md").write_text(markdown, encoding="utf-8")
    write_status(job_dir, status="queued", step="waiting", message="Job queued", state=state)
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
