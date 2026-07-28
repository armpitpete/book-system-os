from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from app.services.pandoc_capability import (
    PANDOC_DOCUMENTED_MINIMUM_VERSION,
    PandocSandboxCapability,
    probe_pandoc_sandbox,
)
from app.services.readiness import (
    CHECK_FAIL,
    CHECK_PASS,
    CHECK_WARNING,
    jobs_root_path,
    readiness_report as base_readiness_report,
)

PANDOC_READINESS_CACHE_SECONDS = 60.0
_pandoc_capability_lock = threading.Lock()
_pandoc_capability_cached: PandocSandboxCapability | None = None
_pandoc_capability_expires_at = 0.0


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


def _reset_pandoc_readiness_cache() -> None:
    """Clear process-local capability evidence for focused tests."""

    global _pandoc_capability_cached, _pandoc_capability_expires_at
    with _pandoc_capability_lock:
        _pandoc_capability_cached = None
        _pandoc_capability_expires_at = 0.0


def _pandoc_capability_for_readiness() -> PandocSandboxCapability:
    """Return bounded process-local capability evidence.

    The lock is intentionally held while the probe runs. Concurrent public
    readiness requests therefore share one in-flight Pandoc process instead of
    launching duplicate probes.
    """

    global _pandoc_capability_cached, _pandoc_capability_expires_at

    with _pandoc_capability_lock:
        current = time.monotonic()
        if (
            _pandoc_capability_cached is not None
            and current < _pandoc_capability_expires_at
        ):
            return _pandoc_capability_cached

        try:
            capability = probe_pandoc_sandbox()
        except Exception:
            capability = PandocSandboxCapability(
                compatible=False,
                code="pandoc-sandbox-probe-failed",
                message="Pandoc sandbox capability probe failed",
            )

        _pandoc_capability_cached = capability
        _pandoc_capability_expires_at = (
            time.monotonic() + PANDOC_READINESS_CACHE_SECONDS
        )
        return capability


def _apply_pandoc_sandbox_guard(report: dict[str, Any]) -> None:
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return

    capability = _pandoc_capability_for_readiness()
    checks["pandoc"] = {
        "status": CHECK_PASS if capability.compatible else CHECK_FAIL,
        "message": capability.message,
        "capability_code": capability.code,
        "documented_minimum_version": PANDOC_DOCUMENTED_MINIMUM_VERSION,
        "refresh_interval_seconds": PANDOC_READINESS_CACHE_SECONDS,
    }


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
    """Strengthen readiness against crash-loop and toolchain false positives."""

    report = base_readiness_report(now=now)
    _apply_worker_startup_guard(report)
    _apply_unreadable_job_guard(report)
    _apply_pandoc_sandbox_guard(report)
    _recompute_overall_status(report)
    return report
