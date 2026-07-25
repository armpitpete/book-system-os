from __future__ import annotations

import sys
import traceback
from pathlib import Path

from app.pipeline.exporters import ExportTimeoutError, pandoc_export
from app.pipeline.structural import structural_cleanup
from app.services.job_queue import read_status, utc_now, write_status
from app.services.resource_limits import (
    FINAL_RECORD_OVERHEAD_BYTES,
    ResourceLimitError,
    enforce_job_storage_limits,
)
from app.utils.atomic_files import atomic_write_json


def _failure_step(exc: Exception) -> str:
    if isinstance(exc, ExportTimeoutError):
        return "export-timeout"
    if isinstance(exc, ResourceLimitError):
        return "resource-limit"
    return "error"


def _failure_extra(exc: Exception) -> dict[str, object] | None:
    if not isinstance(exc, ResourceLimitError):
        return None
    return {
        "limit_code": exc.code,
        "limit": exc.limit,
        "actual": exc.actual,
    }


def run_pipeline(job_dir: Path) -> int:
    input_file = job_dir / "input" / "book.md"
    work_dir = job_dir / "work"
    output_dir = job_dir / "output"
    log_file = job_dir / "logs" / "build.log"

    if not input_file.exists():
        write_status(job_dir, status="failed", step="input", message="Missing input/book.md")
        return 2

    try:
        enforce_job_storage_limits(job_dir)

        write_status(
            job_dir,
            status="running",
            step="structural-cleanup",
            message="Cleaning Markdown",
        )
        raw = input_file.read_text(encoding="utf-8")
        cleaned = structural_cleanup(raw)
        cleaned_file = work_dir / "book-clean.md"
        cleaned_file.write_text(cleaned, encoding="utf-8")
        enforce_job_storage_limits(job_dir)

        write_status(
            job_dir,
            status="running",
            step="pandoc-export",
            message="Building PDF/EPUB/DOCX outputs",
        )
        outputs = pandoc_export(cleaned_file, output_dir, log_file)

        enforce_job_storage_limits(
            job_dir,
            reserve_bytes=FINAL_RECORD_OVERHEAD_BYTES,
        )
        write_status(job_dir, status="done", step="complete", message="Build complete")
        final_status = read_status(job_dir)
        manifest = {
            "completed_at": utc_now(),
            "outputs": outputs,
            "status": final_status,
        }
        atomic_write_json(job_dir / "manifest.json", manifest)
        return 0
    except Exception as exc:
        (job_dir / "logs" / "error.log").write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
        write_status(
            job_dir,
            status="failed",
            step=_failure_step(exc),
            message=str(exc),
            extra=_failure_extra(exc),
        )
        return 1


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m app.pipeline.run_pipeline /path/to/job")
        return 2
    return run_pipeline(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
