from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.services import artifact_readiness as ar
from app.services import real_book_acceptance as rba
from app.services.job_queue import create_job, read_job_events
from app.services.publish_plan import PUBLISH_OUTPUTS


def prepare_complete_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "test")
    _, job_dir = create_job(
        title="Real Book",
        markdown="# Real Book\n\nA substantial manuscript.\n",
        state="production",
    )

    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    outputs = {}
    output_evidence = []
    for index, output in enumerate(PUBLISH_OUTPUTS, start=1):
        data = f"artifact-{index}-{output.key}".encode("utf-8")
        path = job_dir / "output" / output.filename
        path.write_bytes(data)
        outputs[output.key] = output.filename
        output_evidence.append(
            {
                "key": output.key,
                "filename": output.filename,
                "media_type": output.media_type,
                "bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            }
        )

    (job_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "3",
                "outputs": outputs,
                "publishing_metadata": metadata["publishing_metadata"],
                "source_identity": metadata["source_identity"],
                "output_evidence": output_evidence,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ar,
        "_production_config_sha256",
        lambda _kind, _metadata=None: "a" * 64,
    )
    monkeypatch.setattr(ar, "_assets_sha256", lambda _job: "b" * 64)
    return job_dir


def test_real_book_acceptance_records_exact_bound_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_dir = prepare_complete_job(monkeypatch, tmp_path)

    story = rba.record_story_validation(
        job_dir,
        state="pass",
        evidence_id="candidate-editorial-proof:400a0fbe",
        decided_at="2026-08-13T10:00:00+00:00",
    )
    assert story["record"]["source_sha256"] == json.loads(
        (job_dir / "metadata.json").read_text(encoding="utf-8")
    )["source_identity"]["source_sha256"]

    rba.record_production_validation(
        job_dir,
        artifact_type="pdf_standard",
        readiness_class="production-valid",
        state="pass",
        evidence_id="production-check:pdf-standard",
    )
    rba.record_production_validation(
        job_dir,
        artifact_type="pdf_standard",
        readiness_class="digital-publication-ready",
        state="pass",
        evidence_id="digital-check:pdf-standard",
    )
    rba.record_human_acceptance(
        job_dir,
        artifact_type="pdf_standard",
        readiness_class="digital-publication-ready",
        state="accepted",
        evidence_id="human-review:pdf-standard",
        decided_at="2026-08-13T10:30:00+00:00",
    )

    report = rba.evaluate_job_readiness(job_dir)
    states = report["artifacts"]["pdf_standard"]["states"]
    assert states["story-ready"]["ready"] is True
    assert states["production-valid"]["ready"] is True
    assert states["digital-publication-ready"]["ready"] is True
    assert states["print-ready"]["ready"] is False

    events = [event["event"] for event in read_job_events(job_dir)]
    assert "story-validation-recorded" in events
    assert "production-validation-recorded" in events
    assert "human-acceptance-recorded" in events


def test_re_recording_same_binding_replaces_instead_of_creating_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_dir = prepare_complete_job(monkeypatch, tmp_path)

    rba.record_story_validation(
        job_dir,
        state="fail",
        evidence_id="story-first",
    )
    rba.record_story_validation(
        job_dir,
        state="pass",
        evidence_id="story-corrected",
    )

    evidence = rba.load_or_empty_evidence(job_dir)
    assert len(evidence["story_validation"]) == 1
    assert evidence["story_validation"][0]["state"] == "pass"
    assert evidence["story_validation"][0]["evidence_id"] == "story-corrected"


def test_acceptance_cannot_be_recorded_for_unsupported_artifact_class(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_dir = prepare_complete_job(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="does not support"):
        rba.record_human_acceptance(
            job_dir,
            artifact_type="epub",
            readiness_class="print-ready",
            state="accepted",
            evidence_id="invalid-print-acceptance",
        )


def test_evidence_stays_bound_to_current_artifact_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_dir = prepare_complete_job(monkeypatch, tmp_path)
    rba.record_production_validation(
        job_dir,
        artifact_type="pdf_standard",
        readiness_class="production-valid",
        state="pass",
        evidence_id="production-check",
    )

    (job_dir / "output" / "book-standard.pdf").write_bytes(b"changed-after-validation")

    with pytest.raises(ar.ArtifactReadinessError, match="differ from the derivation manifest"):
        rba.load_or_empty_evidence(job_dir)
