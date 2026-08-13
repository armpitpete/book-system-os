from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.pipeline import run_pipeline as pipeline_module
from app.services.job_queue import (
    create_job,
    read_job_events,
    read_status,
    retry_job,
    write_status,
)
from app.services.provenance import (
    PROVENANCE_UNAVAILABLE,
    ProvenanceError,
    assess_manifest_staleness,
    inspect_job_provenance,
    source_identity_text,
)
from app.services.publish_plan import PUBLISH_OUTPUTS


def control_record(markdown: str) -> dict[str, object]:
    identity = source_identity_text(markdown)
    return {
        "schema_version": "1",
        "canonical_path": "manuscript/book.md",
        "source_sha256": identity["source_sha256"],
        "source_bytes": identity["source_bytes"],
        "source_commit": "0123456789abcdef",
        "source_blob": None,
        "control_file_version": "authority-v1",
        "review_state": "approved",
        "publication_state": "ready",
    }


@pytest.fixture(autouse=True)
def isolated_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    for name in (
        "BOOK_MAX_MANUSCRIPT_BYTES",
        "BOOK_MAX_ACTIVE_JOBS",
        "BOOK_MAX_JOB_BYTES",
        "BOOK_MAX_TOTAL_STORAGE_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)


def install_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    def export(
        _cleaned: Path, output_dir: Path, _log: Path, **_kwargs: object
    ) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, str] = {}
        for index, spec in enumerate(PUBLISH_OUTPUTS, start=1):
            payload = f"{spec.key}:{index}\n".encode("utf-8")
            (output_dir / spec.filename).write_bytes(payload)
            outputs[spec.key] = spec.filename
        return outputs

    monkeypatch.setattr(pipeline_module, "pandoc_export", export)


def test_uncontrolled_job_records_exact_local_source_identity() -> None:
    markdown = "# Café\r\n"
    _, job_dir = create_job(title="Exact", markdown=markdown, state="test")
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    source = markdown.encode("utf-8")

    assert (job_dir / "input" / "book.md").read_bytes() == source
    assert metadata["source_identity"] == {
        "schema_version": "1",
        "source_bytes": len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "controlled": False,
        "control_record_sha256": None,
        "control_record": None,
    }


def test_matching_control_record_creates_deterministic_identity() -> None:
    markdown = "# Controlled\n"
    record = control_record(markdown)
    _, first = create_job(title="First", markdown=markdown, control_record=record)
    _, second = create_job(
        title="Second",
        markdown=markdown,
        control_record=dict(reversed(list(record.items()))),
    )

    first_identity = json.loads((first / "metadata.json").read_text(encoding="utf-8"))[
        "source_identity"
    ]
    second_identity = json.loads((second / "metadata.json").read_text(encoding="utf-8"))[
        "source_identity"
    ]
    assert first_identity == second_identity
    assert first_identity["controlled"] is True
    assert first_identity["control_record"] == record


def test_controlled_mismatches_and_invalid_records_have_no_filesystem_side_effects(
    tmp_path: Path,
) -> None:
    markdown = "# Exact\n"
    record = control_record(markdown)
    jobs_root = tmp_path / "books" / "jobs"

    failures = (
        ({**record, "source_bytes": record["source_bytes"] + 1}, "source-bytes-mismatch"),
        ({**record, "source_sha256": "0" * 64}, "source-sha256-mismatch"),
        ({**record, "source_bytes": str(record["source_bytes"])}, "control-record-invalid"),
        ({**record, "source_commit": "x" * 201}, "control-record-invalid"),
        ({**record, "unexpected": "field"}, "control-record-invalid"),
    )

    for supplied, expected_code in failures:
        before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
        with pytest.raises(ProvenanceError) as exc:
            create_job(title="Rejected", markdown=markdown, control_record=supplied)
        assert exc.value.code == expected_code
        assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before
        assert not jobs_root.exists()


def test_modified_input_fails_before_cleanup_or_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markdown = "# Exact\n"
    _, job_dir = create_job(
        title="Tamper",
        markdown=markdown,
        control_record=control_record(markdown),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        pipeline_module,
        "structural_cleanup",
        lambda _raw: calls.append("cleanup") or "",
    )
    monkeypatch.setattr(
        pipeline_module,
        "pandoc_export",
        lambda *_args: calls.append("export") or {},
    )
    (job_dir / "input" / "book.md").write_bytes(b"tampered")

    assert pipeline_module.run_pipeline(job_dir) == 1
    assert calls == []
    assert list((job_dir / "work").iterdir()) == []
    assert list((job_dir / "output").iterdir()) == []
    status = read_status(job_dir)
    assert status["status"] == "failed"
    assert status["step"] == "source-integrity"
    assert status["failure_code"] in {
        "source-bytes-mismatch",
        "source-sha256-mismatch",
    }
    assert read_job_events(job_dir)[-1]["event"] == "source-integrity-failed"


def test_successful_pipeline_records_raw_cleaned_and_ordered_output_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markdown = "# Café\r\n"
    _, job_dir = create_job(
        title="Manifest",
        markdown=markdown,
        control_record=control_record(markdown),
    )
    install_exporter(monkeypatch)

    assert pipeline_module.run_pipeline(job_dir) == 0

    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    cleaned = (job_dir / "work" / "book-clean.md").read_bytes()
    assert manifest["schema_version"] == "3"
    assert manifest["provenance_state"] == "available"
    assert manifest["source_identity"] == metadata["source_identity"]
    assert manifest["cleaned_markdown"] == {
        "bytes": len(cleaned),
        "sha256": hashlib.sha256(cleaned).hexdigest(),
    }
    assert manifest["publishing_metadata"] == {
        "schema_version": "1",
        "title": "Manifest",
        "language": None,
    }
    assert manifest["transformation"] == {
        "identifier": "structural-cleanup",
        "version": "2",
    }
    assert manifest["outputs"] == {
        output.key: output.filename for output in PUBLISH_OUTPUTS
    }
    assert [item["key"] for item in manifest["output_evidence"]] == [
        output.key for output in PUBLISH_OUTPUTS
    ]
    assert [item["filename"] for item in manifest["output_evidence"]] == [
        output.filename for output in PUBLISH_OUTPUTS
    ]
    assert [item["media_type"] for item in manifest["output_evidence"]] == [
        output.media_type for output in PUBLISH_OUTPUTS
    ]
    for evidence in manifest["output_evidence"]:
        output_path = job_dir / "output" / evidence["filename"]
        assert evidence["bytes"] == output_path.stat().st_size
        assert evidence["sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()


def test_retry_preserves_identity_and_rejects_tamper_before_cleanup() -> None:
    markdown = "# Retry\n"
    _, job_dir = create_job(
        title="Retry",
        markdown=markdown,
        control_record=control_record(markdown),
    )
    write_status(job_dir, status="failed", step="export", message="Failed")
    metadata_before = (job_dir / "metadata.json").read_bytes()
    source_before = (job_dir / "input" / "book.md").read_bytes()
    for name in ("work", "output", "logs"):
        (job_dir / name / "stale.txt").write_text("stale", encoding="utf-8")

    retry_job(job_dir)
    assert (job_dir / "metadata.json").read_bytes() == metadata_before
    assert (job_dir / "input" / "book.md").read_bytes() == source_before
    assert all(list((job_dir / name).iterdir()) == [] for name in ("work", "output", "logs"))

    write_status(job_dir, status="failed", step="export", message="Failed again")
    for name in ("work", "output", "logs"):
        (job_dir / name / "keep.txt").write_text("keep", encoding="utf-8")
    (job_dir / "input" / "book.md").write_bytes(b"tampered")

    with pytest.raises(ProvenanceError):
        retry_job(job_dir)
    assert all((job_dir / name / "keep.txt").is_file() for name in ("work", "output", "logs"))
    assert read_status(job_dir)["step"] == "source-integrity"


def test_staleness_and_legacy_provenance_are_deterministic(tmp_path: Path) -> None:
    markdown = "# Current\n"
    record = control_record(markdown)
    _, job_dir = create_job(title="Current", markdown=markdown, control_record=record)
    identity = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))[
        "source_identity"
    ]
    manifest = {"source_identity": identity}

    assert assess_manifest_staleness(manifest, record) == {
        "current": True,
        "reasons": [],
    }
    changed = {
        **record,
        "canonical_path": "manuscript/revised.md",
        "review_state": "needs-review",
        "source_sha256": "f" * 64,
    }
    assert assess_manifest_staleness(manifest, changed) == {
        "current": False,
        "reasons": [
            "canonical-path-changed",
            "review-state-changed",
            "source-sha256-changed",
        ],
    }

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "metadata.json").write_text(
        json.dumps({"job_id": "legacy"}),
        encoding="utf-8",
    )
    assert inspect_job_provenance(legacy) == {"state": PROVENANCE_UNAVAILABLE}
    assert assess_manifest_staleness({}, record) == {
        "current": False,
        "reasons": ["provenance-unavailable"],
    }
