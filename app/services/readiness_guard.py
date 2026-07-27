from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.readiness import (
    CHECK_FAIL,
    CHECK_WARNING,
    jobs_root_path,
    readiness_report as base_readiness_report,
)


def _unreadable_job_record_count() -> int:
    jobs_root = jobs_root_path()
    if not jobs_root.is_dir():
        return 0

    try:
        entries = list(jobs_root.iterdir())
    except OSError:
        return 1

    unreadable = 0
    for job_dir in entries:
        try:
            if not job_dir.is_dir():
                continue
        except OSError:
            unreadable += 1
            continue

        try:
            (job_dir / "status.json").read_text(encoding="utf-8")
        except OSError:
            unreadable += 1

    return unreadable


def _apply_worker_startup_guard(report: dict[str, Any]) -> None:
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return

    worker = checks.get("worker")
    if not isinstance(worker, dict):
        return

    if worker.get("worker_state") != "starting":
        return

    worker["status"] = CHECK_FAIL
    worker["message"] = "Worker startup checks have not completed"


def _apply_unreadable_job_guard(report: dict[str, Any]) -> None:
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return

    active_work = checks.get("active_work")
    if not isinstance(active_work, dict):
        return

    unreadable = _unreadable_job_record_count()
    active_work["unreadable_job_record_count"] = unreadable

    if unreadable:
        active_work["status"] = CHECK_FAIL
        active_work["message"] = "Unreadable retained job records were detected"


def _recompute_overall_status(report: dict[str, Any]) -> None:
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return

    statuses = {
        check.get("status")
        for check in checks.values()
        if isinstance(check, dict)
    }

    if CHECK_FAIL in statuses:
        report["ready"] = False
        report["status"] = "not-ready"
    elif CHECK_WARNING in statuses:
        report["ready"] = False
        report["status"] = "degraded"
    else:
        report["ready"] = True
        report["status"] = "ready"


def readiness_report(*, now: datetime | None = None) -> dict[str, Any]:
    """Strengthen H-05 readiness against crash-loop false positives."""

    report = base_readiness_report(now=now)
    _apply_worker_startup_guard(report)
    _apply_unreadable_job_guard(report)
    _recompute_overall_status(report)
    return report
