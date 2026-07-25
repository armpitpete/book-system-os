from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi.responses import JSONResponse

from app.utils.paths import jobs_dir

DEFAULT_MAX_REQUEST_BYTES = 6 * 1024 * 1024
DEFAULT_MAX_MANUSCRIPT_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_ACTIVE_JOBS = 20
DEFAULT_EXPORT_COMMAND_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_JOB_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_TOTAL_STORAGE_BYTES = 10 * 1024 * 1024 * 1024

NEW_JOB_OVERHEAD_BYTES = 64 * 1024
FINAL_RECORD_OVERHEAD_BYTES = 64 * 1024
ACTIVE_STATUSES = {"queued", "running"}
BODY_METHODS = {"POST", "PUT", "PATCH"}


class ResourceLimitError(RuntimeError):
    """Controlled refusal or runtime failure caused by a configured resource limit."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
        limit: int | float | None = None,
        actual: int | float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.limit = limit
        self.actual = actual

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "detail": str(self),
            "code": self.code,
        }
        if self.limit is not None:
            payload["limit"] = self.limit
        if self.actual is not None:
            payload["actual"] = self.actual
        return payload


class RequestBodyTooLarge(ResourceLimitError):
    pass


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ResourceLimitError(
            f"{name} must be a positive integer",
            code="invalid-resource-limit-config",
            status_code=503,
        ) from exc
    if value <= 0:
        raise ResourceLimitError(
            f"{name} must be greater than zero",
            code="invalid-resource-limit-config",
            status_code=503,
        )
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ResourceLimitError(
            f"{name} must be a positive number",
            code="invalid-resource-limit-config",
            status_code=503,
        ) from exc
    if value <= 0:
        raise ResourceLimitError(
            f"{name} must be greater than zero",
            code="invalid-resource-limit-config",
            status_code=503,
        )
    return value


def max_request_bytes() -> int:
    return _positive_int("BOOK_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES)


def max_manuscript_bytes() -> int:
    return _positive_int("BOOK_MAX_MANUSCRIPT_BYTES", DEFAULT_MAX_MANUSCRIPT_BYTES)


def max_active_jobs() -> int:
    return _positive_int("BOOK_MAX_ACTIVE_JOBS", DEFAULT_MAX_ACTIVE_JOBS)


def export_command_timeout_seconds() -> float:
    return _positive_float(
        "BOOK_EXPORT_COMMAND_TIMEOUT_SECONDS",
        DEFAULT_EXPORT_COMMAND_TIMEOUT_SECONDS,
    )


def max_job_bytes() -> int:
    return _positive_int("BOOK_MAX_JOB_BYTES", DEFAULT_MAX_JOB_BYTES)


def max_total_storage_bytes() -> int:
    return _positive_int(
        "BOOK_MAX_TOTAL_STORAGE_BYTES",
        DEFAULT_MAX_TOTAL_STORAGE_BYTES,
    )


def path_size_bytes(path: Path) -> int:
    target = Path(path)
    if not target.exists():
        return 0
    if target.is_file() or target.is_symlink():
        return target.stat(follow_symlinks=False).st_size

    total = 0
    stack = [target]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except FileNotFoundError:
            continue

        for entry in entries:
            try:
                if entry.is_symlink():
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
            except FileNotFoundError:
                continue
    return total


def active_job_count() -> int:
    base = jobs_dir()
    count = 0
    for job_dir in base.iterdir():
        if not job_dir.is_dir():
            continue
        status_path = job_dir / "status.json"
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("status") in ACTIVE_STATUSES:
            count += 1
    return count


def new_job_reservation_bytes(markdown: str) -> int:
    return len(markdown.encode("utf-8")) + NEW_JOB_OVERHEAD_BYTES


def check_job_admission(markdown: str) -> None:
    manuscript_size = len(markdown.encode("utf-8"))
    manuscript_limit = max_manuscript_bytes()
    if manuscript_size > manuscript_limit:
        raise ResourceLimitError(
            "Markdown manuscript exceeds the configured size limit",
            code="manuscript-too-large",
            status_code=413,
            limit=manuscript_limit,
            actual=manuscript_size,
        )

    active = active_job_count()
    active_limit = max_active_jobs()
    if active >= active_limit:
        raise ResourceLimitError(
            "The publishing queue is at configured capacity",
            code="queue-capacity-reached",
            status_code=503,
            limit=active_limit,
            actual=active,
        )

    reservation = new_job_reservation_bytes(markdown)
    job_limit = max_job_bytes()
    if reservation > job_limit:
        raise ResourceLimitError(
            "The manuscript plus required job-record reserve exceeds the per-job limit",
            code="job-storage-reservation-exceeded",
            status_code=413,
            limit=job_limit,
            actual=reservation,
        )

    retained = path_size_bytes(jobs_dir())
    total_limit = max_total_storage_bytes()
    projected = retained + reservation
    if projected > total_limit:
        raise ResourceLimitError(
            "Retained job storage cannot admit another job safely",
            code="total-storage-capacity-reached",
            status_code=507,
            limit=total_limit,
            actual=projected,
        )


def enforce_job_storage_limits(
    job_dir: Path,
    *,
    reserve_bytes: int = 0,
) -> dict[str, int]:
    reserve = max(0, int(reserve_bytes))
    job_size = path_size_bytes(job_dir)
    job_limit = max_job_bytes()
    projected_job = job_size + reserve
    if projected_job > job_limit:
        raise ResourceLimitError(
            "Job storage exceeds the configured per-job limit",
            code="job-storage-limit-exceeded",
            status_code=507,
            limit=job_limit,
            actual=projected_job,
        )

    total_size = path_size_bytes(jobs_dir())
    total_limit = max_total_storage_bytes()
    projected_total = total_size + reserve
    if projected_total > total_limit:
        raise ResourceLimitError(
            "Retained job storage exceeds the configured total limit",
            code="total-storage-limit-exceeded",
            status_code=507,
            limit=total_limit,
            actual=projected_total,
        )

    return {
        "job_bytes": job_size,
        "total_storage_bytes": total_size,
        "reserve_bytes": reserve,
    }


class RequestBodyLimitMiddleware:
    """Bound request bodies before FastAPI parses JSON or form data."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http" or scope.get("method") not in BODY_METHODS:
            await self.app(scope, receive, send)
            return

        try:
            limit = max_request_bytes()
        except ResourceLimitError as exc:
            response = JSONResponse(status_code=exc.status_code, content=exc.payload())
            await response(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared = int(raw_length.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                response = JSONResponse(
                    status_code=400,
                    content={
                        "detail": "Invalid Content-Length header",
                        "code": "invalid-content-length",
                    },
                )
                await response(scope, receive, send)
                return
            if declared > limit:
                exc = RequestBodyTooLarge(
                    "Request body exceeds the configured size limit",
                    code="request-too-large",
                    status_code=413,
                    limit=limit,
                    actual=declared,
                )
                response = JSONResponse(status_code=exc.status_code, content=exc.payload())
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestBodyTooLarge(
                        "Request body exceeds the configured size limit",
                        code="request-too-large",
                        status_code=413,
                        limit=limit,
                        actual=received,
                    )
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge as exc:
            response = JSONResponse(status_code=exc.status_code, content=exc.payload())
            await response(scope, receive, send)
