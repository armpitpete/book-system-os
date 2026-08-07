from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from app.services import artifact_readiness as ar
from app.services.job_queue import create_job
from app.services.publish_plan import PUBLISH_OUTPUTS

S2 = "2" * 64

REQ = {
    "schema_version": "1",
    "story_validation": {"profile_id": "story/full", "profile_version": "1"},
    "production_validation": {
        "production-valid": {"profile_id": "bos/base", "profile_version": "1"},
        "digital-publication-ready": {"profile_id": "bos/digital", "profile_version": "1"},
        "print-ready": {"profile_id": "bos/print", "profile_version": "1"},
    },
    "human_acceptance": {
        "digital-publication-ready": {
            "profile_id": "accept/digital",
            "profile_version": "1",
        },
        "print-ready": {"profile_id": "accept/print", "profile_version": "1"},
    },
}


def spec_for(key: str):
    return next(output for output in PUBLISH_OUTPUTS if output.key == key)


def prepare_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    artifact_type: str = "pdf_standard",
    markdown: str = "# Book\n",
    artifact_bytes: bytes = b"artifact-v1",
) -> tuple[Path, Path]:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "test")
    _, job_dir = create_job(title="Readiness", markdown=markdown, state="test")
    spec = spec_for(artifact_type)
    artifact = job_dir / "output" / spec.filename
    artifact.write_bytes(artifact_bytes)
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    write_manifest(job_dir, artifact_type, artifact_bytes, metadata["source_identity"])
    return job_dir, artifact


def write_manifest(
    job_dir: Path,
    artifact_type: str,
    artifact_bytes: bytes,
    source_identity: dict | None = None,
) -> None:
    spec = spec_for(artifact_type)
    if source_identity is None:
        metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
        source_identity = metadata["source_identity"]
    manifest = {
        "schema_version": "2",
        "outputs": {artifact_type: spec.filename},
        "source_identity": source_identity,
        "output_evidence": [
            {
                "key": artifact_type,
                "filename": spec.filename,
                "media_type": spec.media_type,
                "bytes": len(artifact_bytes),
                "sha256": sha256(artifact_bytes).hexdigest(),
            }
        ],
    }
    (job_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )


def story(context: dict, *, source: str | None = None, state: str = "pass") -> dict:
    return {
        "schema_version": "1",
        "profile_id": "story/full",
        "profile_version": "1",
        "source_sha256": source or context["source_sha256"],
        "state": state,
        "decided_at": "2026-08-07T17:00:00Z",
        "evidence_id": "story-1",
    }


def production(kind: str, context: dict, *, state: str = "pass") -> dict:
    profile = {
        "production-valid": "bos/base",
        "digital-publication-ready": "bos/digital",
        "print-ready": "bos/print",
    }[kind]
    return {
        "schema_version": "1",
        "readiness_class": kind,
        "artifact_type": context["artifact_type"],
        "source_sha256": context["source_sha256"],
        "artifact_sha256": context["artifact_sha256"],
        "production_config_sha256": context["production_config_sha256"],
        "assets_sha256": context["assets_sha256"],
        "profile_id": profile,
        "profile_version": "1",
        "state": state,
        "evidence_id": f"production-{kind}",
    }


def acceptance(kind: str, context: dict, *, state: str = "accepted") -> dict:
    profile = {
        "digital-publication-ready": "accept/digital",
        "print-ready": "accept/print",
    }[kind]
    return {
        "schema_version": "1",
        "readiness_class": kind,
        "artifact_type": context["artifact_type"],
        "artifact_sha256": context["artifact_sha256"],
        "profile_id": profile,
        "profile_version": "1",
        "state": state,
        "decided_at": "2026-08-07T17:10:00Z",
        "evidence_id": f"acceptance-{kind}",
    }


def bundle(
    context: dict,
    *,
    stories: list[dict] | None = None,
    productions: list[dict] | None = None,
    acceptances: list[dict] | None = None,
) -> dict:
    artifact_type = context["artifact_type"]
    supported = {
        readiness_class
        for readiness_class, artifact_types in ar.READINESS_ARTIFACT_MATRIX.items()
        if artifact_type in artifact_types
    }
    default_productions = [production("production-valid", context)]
    default_acceptances: list[dict] = []
    for readiness_class in ar.PUBLICATION_CLASSES:
        if readiness_class in supported:
            default_productions.append(production(readiness_class, context))
            default_acceptances.append(acceptance(readiness_class, context))
    return {
        "schema_version": "1",
        "story_validation": [story(context)] if stories is None else stories,
        "production_validation": (
            default_productions if productions is None else productions
        ),
        "human_acceptance": (
            default_acceptances if acceptances is None else acceptances
        ),
    }


def evaluate(job_dir: Path, artifact_type: str, evidence: dict) -> dict:
    return ar.evaluate_readiness(
        evidence,
        requirements=REQ,
        job_dir=job_dir,
        artifact_type=artifact_type,
    )["states"]


def test_exact_real_artifact_binding_passes_all_pdf_states(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    result = evaluate(job_dir, "pdf_standard", bundle(context))
    assert all(result[name]["ready"] for name in ar.READINESS_CLASSES)


def test_story_validation_for_different_manuscript_digest_fails(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(context, stories=[story(context, source=S2)])
    result = evaluate(job_dir, "pdf_standard", evidence)
    assert result["story-ready"]["reasons"] == [
        "story-validation-source-sha256-mismatch"
    ]


def test_physical_manuscript_change_after_validation_fails_closed(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(context)
    (job_dir / "input" / "book.md").write_text("# Changed book\n", encoding="utf-8")
    result = evaluate(job_dir, "pdf_standard", evidence)
    assert all(not state["ready"] for state in result.values())
    assert all(state["reasons"][0].startswith("source-") for state in result.values())


def test_physical_artifact_change_after_production_validation_fails_closed(
    monkeypatch, tmp_path
):
    job_dir, artifact = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(context)
    artifact.write_bytes(b"artifact-mutated-after-validation")
    result = evaluate(job_dir, "pdf_standard", evidence)
    assert result["story-ready"]["ready"] is True
    assert result["production-valid"]["reasons"] == [
        "readiness-artifact-integrity-mismatch"
    ]
    assert result["digital-publication-ready"]["ready"] is False
    assert result["print-ready"]["ready"] is False


def test_real_regeneration_invalidates_previous_human_acceptance(monkeypatch, tmp_path):
    job_dir, artifact = prepare_job(monkeypatch, tmp_path)
    old_context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    old_acceptances = [
        acceptance("digital-publication-ready", old_context),
        acceptance("print-ready", old_context),
    ]

    regenerated = b"artifact-v2-regenerated"
    artifact.write_bytes(regenerated)
    write_manifest(job_dir, "pdf_standard", regenerated)
    new_context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(new_context, acceptances=old_acceptances)
    result = evaluate(job_dir, "pdf_standard", evidence)

    assert result["production-valid"]["ready"] is True
    assert "human-acceptance-artifact-sha256-mismatch" in result[
        "digital-publication-ready"
    ]["reasons"]
    assert result["print-ready"]["ready"] is False


def test_missing_story_validation_fails_closed(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    assert evaluate(job_dir, "pdf_standard", bundle(context, stories=[]))[
        "story-ready"
    ]["reasons"] == ["story-validation-missing"]


def test_missing_production_validation_fails_closed(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    assert evaluate(job_dir, "pdf_standard", bundle(context, productions=[]))[
        "production-valid"
    ]["reasons"] == ["production-validation-missing"]


def test_missing_human_acceptance_fails_closed(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    result = evaluate(job_dir, "pdf_standard", bundle(context, acceptances=[]))
    assert "human-acceptance-missing" in result["digital-publication-ready"]["reasons"]


def test_digital_readiness_does_not_imply_print(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(
        context,
        productions=[
            production("production-valid", context),
            production("digital-publication-ready", context),
        ],
        acceptances=[acceptance("digital-publication-ready", context)],
    )
    result = evaluate(job_dir, "pdf_standard", evidence)
    assert result["digital-publication-ready"]["ready"] is True
    assert result["print-ready"]["ready"] is False


def test_print_readiness_does_not_imply_digital(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(
        context,
        productions=[
            production("production-valid", context),
            production("print-ready", context),
        ],
        acceptances=[acceptance("print-ready", context)],
    )
    result = evaluate(job_dir, "pdf_standard", evidence)
    assert result["print-ready"]["ready"] is True
    assert result["digital-publication-ready"]["ready"] is False


def test_unknown_schema_and_profile_fail_closed(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    bad = bundle(context)
    bad["schema_version"] = "2"
    assert all(not x["ready"] for x in evaluate(job_dir, "pdf_standard", bad).values())

    mismatch_story = {**story(context), "profile_id": "story/future"}
    mismatch = bundle(context, stories=[mismatch_story])
    assert evaluate(job_dir, "pdf_standard", mismatch)["story-ready"]["reasons"] == [
        "story-validation-profile-mismatch"
    ]


def test_actual_template_change_invalidates_production_configuration(monkeypatch, tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir(parents=True)
    template = templates / "book-template-standard.tex"
    template.write_text("template-v1", encoding="utf-8")
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(context)

    template.write_text("template-v2", encoding="utf-8")
    result = evaluate(job_dir, "pdf_standard", evidence)
    assert result["production-valid"]["reasons"] == [
        "production-validation-config-sha256-mismatch"
    ]


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is required")
def test_actual_referenced_asset_change_invalidates_production(monkeypatch, tmp_path):
    markdown = "# Book\n\n![Cover](cover.png)\n"
    job_dir, _ = prepare_job(monkeypatch, tmp_path, markdown=markdown)
    asset = job_dir / "input" / "cover.png"
    asset.write_bytes(b"cover-v1")
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(context)

    asset.write_bytes(b"cover-v2")
    result = evaluate(job_dir, "pdf_standard", evidence)
    assert result["production-valid"]["reasons"] == [
        "production-validation-assets-sha256-mismatch"
    ]


def test_epub_can_never_be_print_ready_even_with_matching_synthetic_evidence(
    monkeypatch, tmp_path
):
    job_dir, _ = prepare_job(monkeypatch, tmp_path, artifact_type="epub")
    context = ar.authoritative_artifact_context(job_dir, "epub")
    evidence = bundle(context)
    evidence["production_validation"].append(production("print-ready", context))
    evidence["human_acceptance"].append(acceptance("print-ready", context))
    result = evaluate(job_dir, "epub", evidence)

    assert result["production-valid"]["ready"] is True
    assert result["digital-publication-ready"]["ready"] is True
    assert result["print-ready"]["ready"] is False
    assert "artifact-readiness-class-unsupported" in result["print-ready"]["reasons"]


def test_persistence_rejects_unsupported_artifact_readiness_combination(
    monkeypatch, tmp_path
):
    job_dir, _ = prepare_job(monkeypatch, tmp_path, artifact_type="epub")
    context = ar.authoritative_artifact_context(job_dir, "epub")
    evidence = bundle(context)
    evidence["production_validation"].append(production("print-ready", context))
    with pytest.raises(ar.ArtifactReadinessError) as exc:
        ar.persist_readiness_evidence(job_dir, evidence)
    assert exc.value.code == "artifact-readiness-class-unsupported"


def test_unknown_artifact_type_fails_closed(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    result = evaluate(job_dir, "unknown-format", bundle(context))
    assert result["story-ready"]["ready"] is True
    assert result["production-valid"]["reasons"] == [
        "readiness-artifact-type-unsupported"
    ]
    assert result["digital-publication-ready"]["ready"] is False
    assert result["print-ready"]["ready"] is False


def test_persisted_evidence_is_real_state_bound_and_tamper_evident(monkeypatch, tmp_path):
    job_dir, artifact = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(context)
    ar.persist_readiness_evidence(job_dir, evidence)
    path = ar.readiness_evidence_path(job_dir)
    assert ar.load_readiness_evidence(job_dir)["schema_version"] == "1"

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["evidence"]["story_validation"][0]["evidence_id"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ar.ArtifactReadinessError) as exc:
        ar.load_readiness_evidence(job_dir)
    assert exc.value.code == "readiness-evidence-integrity-mismatch"

    ar.persist_readiness_evidence(job_dir, evidence)
    artifact.write_bytes(b"changed-after-persistence")
    with pytest.raises(ar.ArtifactReadinessError) as exc:
        ar.load_readiness_evidence(job_dir)
    assert exc.value.code == "readiness-artifact-integrity-mismatch"


def test_persistence_rejects_evidence_for_another_manuscript(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    evidence = bundle(context, stories=[story(context, source=S2)])
    with pytest.raises(ar.ArtifactReadinessError) as exc:
        ar.persist_readiness_evidence(job_dir, evidence)
    assert exc.value.code == "readiness-source-sha256-mismatch"


def test_v02_dry_run_never_claims_bos_readiness(monkeypatch):
    from app.services import publish_plan

    monkeypatch.setattr(publish_plan, "validate_manuscript", lambda **_: {"valid": True})
    result = publish_plan.build_publish_dry_run(title="Dry", markdown="# Dry\n")
    assert result["publishable"] is True
    assert result["readiness"]["evaluated"] is False
    assert result["readiness"]["artifact_contract_version"] == "1"
    assert all(not x["ready"] for x in result["readiness"]["states"].values())
    assert all(
        x["reasons"] == ["dry-run-structural-validation-only"]
        for x in result["readiness"]["states"].values()
    )


def test_conflicting_duplicate_evidence_fails_closed(monkeypatch, tmp_path):
    job_dir, _ = prepare_job(monkeypatch, tmp_path)
    context = ar.authoritative_artifact_context(job_dir, "pdf_standard")
    duplicate = story(context)
    conflicting = {**duplicate, "state": "fail", "evidence_id": "story-conflict"}
    result = evaluate(
        job_dir,
        "pdf_standard",
        bundle(context, stories=[duplicate, conflicting]),
    )
    assert all(not state["ready"] for state in result.values())
    assert all(
        state["reasons"] == ["readiness-evidence-invalid"]
        for state in result.values()
    )
