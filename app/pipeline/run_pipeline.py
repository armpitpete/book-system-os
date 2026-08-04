from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any

from app.pipeline.exporters import ExportTimeoutError, pandoc_export
from app.pipeline.structural import structural_cleanup
from app.services.job_queue import append_job_event, read_status, utc_now, write_status
from app.services.provenance import (
    DERIVATION_MANIFEST_SCHEMA_VERSION,
    STRUCTURAL_TRANSFORMATION_ID,
    STRUCTURAL_TRANSFORMATION_VERSION,
    ProvenanceError,
    sha256_file,
    source_identity_bytes,
    verify_job_source,
)
from app.services.publish_plan import PUBLISH_OUTPUTS
from app.services.resource_limits import (
    FINAL_RECORD_OVERHEAD_BYTES,
    ResourceLimitError,
    enforce_job_storage_limits,
)
from app.utils.atomic_files import atomic_write_json


def _failure_step(exc: Exception) -> str:
    if isinstance(exc, ProvenanceError):
        return "source-integrity"
    if isinstance(exc, ExportTimeoutError):
        return "export-timeout"
    if isinstance(exc, ResourceLimitError):
        return "resource-limit"
    return "error"


def _failure_extra(exc: Exception) -> dict[str, object] | None:
    if isinstance(exc, ProvenanceError):
        return {"failure_code": exc.code}
    if isinstance(exc, ResourceLimitError):
        return {
            "limit_code": exc.code,
            "limit": exc.limit,
            "actual": exc.actual,
        }
    return None


def _output_evidence(outputs: dict[str, str], output_dir: Path) -> list[dict[str, Any]]:
    expected = {output.key: output.filename for output in PUBLISH_OUTPUTS}
    if outputs != expected:
        raise RuntimeError("Exporter output declarations differ from PUBLISH_OUTPUTS")

    evidence: list[dict[str, Any]] = []
    for output in PUBLISH_OUTPUTS:
        path = output_dir / output.filename
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Declared output is missing or empty: {output.filename}")
        evidence.append(
            {
                "key": output.key,
                "filename": output.filename,
                "media_type": output.media_type,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return evidence


def _derivation_manifest(
    *,
    provenance: dict[str, Any],
    cleaned_bytes: bytes,
    outputs: dict[str, str],
    output_dir: Path,
    final_status: dict[str, Any],
) -> dict[str, Any]:
    cleaned_identity = source_identity_bytes(cleaned_bytes)
    return {
        "schema_version": DERIVATION_MANIFEST_SCHEMA_VERSION,
        "completed_at": utc_now(),
        "outputs": outputs,
        "status": final_status,
        "provenance_state": provenance["state"],
        "source_identity": provenance.get("source_identity"),
        "cleaned_markdown": {
            "bytes": cleaned_identity["source_bytes"],
            "sha256": cleaned_identity["source_sha256"],
        },
        "transformation": {
            "identifier": STRUCTURAL_TRANSFORMATION_ID,
            "version": STRUCTURAL_TRANSFORMATION_VERSION,
        },
        "output_evidence": _output_evidence(outputs, output_dir),
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
        provenance = verify_job_source(job_dir)
        enforce_job_storage_limits(job_dir)

        write_status(
            job_dir,
            status="running",
            step="structural-cleanup",
            message="Cleaning Markdown",
        )
        raw_bytes = input_file.read_bytes()
        raw = raw_bytes.decode("utf-8")
        cleaned = structural_cleanup(raw)
        cleaned_bytes = cleaned.encode("utf-8")
        cleaned_file = work_dir / "book-clean.md"
        cleaned_file.write_bytes(cleaned_bytes)
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
        manifest = _derivation_manifest(
            provenance=provenance,
            cleaned_bytes=cleaned_bytes,
            outputs=outputs,
            output_dir=output_dir,
            final_status=final_status,
        )
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
        if isinstance(exc, ProvenanceError):
            append_job_event(
                job_dir,
                "source-integrity-failed",
                str(exc),
                failure_code=exc.code,
                operation="pipeline",
            )
        return 1


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m app.pipeline.run_pipeline /path/to/job")
        return 2
    return run_pipeline(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
