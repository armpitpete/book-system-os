from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.services.artifact_readiness import (
    ARTIFACT_CLASSES,
    PUBLICATION_CLASSES,
    READINESS_ARTIFACT_MATRIX,
    SUPPORTED_ARTIFACT_TYPES,
    ArtifactReadinessError,
    authoritative_artifact_context,
    evaluate_readiness,
    load_readiness_evidence,
    persist_readiness_evidence,
)
from app.services.job_queue import append_job_event, utc_now
from app.services.provenance import PROVENANCE_UNAVAILABLE, ProvenanceError, verify_job_source

READINESS_REQUIREMENTS_V1: dict[str, Any] = {
    "schema_version": "1",
    "story_validation": {
        "profile_id": "story-validation/external",
        "profile_version": "1",
    },
    "production_validation": {
        "production-valid": {
            "profile_id": "book-system-os/production-valid",
            "profile_version": "1",
        },
        "digital-publication-ready": {
            "profile_id": "book-system-os/digital-publication",
            "profile_version": "1",
        },
        "print-ready": {
            "profile_id": "book-system-os/print",
            "profile_version": "1",
        },
    },
    "human_acceptance": {
        "digital-publication-ready": {
            "profile_id": "human/digital-artifact",
            "profile_version": "1",
        },
        "print-ready": {
            "profile_id": "human/print-artifact",
            "profile_version": "1",
        },
    },
}


def empty_evidence() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "story_validation": [],
        "production_validation": [],
        "human_acceptance": [],
    }


def readiness_requirements() -> dict[str, Any]:
    return deepcopy(READINESS_REQUIREMENTS_V1)


def _current_source_sha256(job_dir: Path) -> str:
    try:
        provenance = verify_job_source(Path(job_dir))
    except ProvenanceError as exc:
        raise ArtifactReadinessError(exc.code, str(exc)) from exc
    if provenance.get("state") == PROVENANCE_UNAVAILABLE:
        raise ArtifactReadinessError(
            "provenance-unavailable",
            "Exact retained manuscript provenance is required",
        )
    source = provenance.get("source_identity", {}).get("source_sha256")
    if not isinstance(source, str) or len(source) != 64:
        raise ArtifactReadinessError(
            "source-identity-invalid",
            "Retained manuscript source identity is invalid",
        )
    return source


def load_or_empty_evidence(job_dir: Path) -> dict[str, Any]:
    try:
        return load_readiness_evidence(Path(job_dir))
    except ArtifactReadinessError as exc:
        if exc.code == "readiness-evidence-missing":
            return empty_evidence()
        raise


def _replace_bound_record(
    records: list[dict[str, Any]],
    item: dict[str, Any],
    *,
    identity_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    identity = tuple(item[field] for field in identity_fields)
    kept = [
        record
        for record in records
        if tuple(record.get(field) for field in identity_fields) != identity
    ]
    kept.append(item)
    return kept


def _persist(job_dir: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    return persist_readiness_evidence(Path(job_dir), evidence)


def record_story_validation(
    job_dir: Path,
    *,
    state: str,
    evidence_id: str,
    decided_at: str | None = None,
) -> dict[str, Any]:
    if state not in {"pass", "fail"}:
        raise ValueError("Story Validation state must be pass or fail")
    if not evidence_id.strip():
        raise ValueError("Story Validation evidence_id is required")

    job_dir = Path(job_dir)
    source_sha256 = _current_source_sha256(job_dir)
    profile = READINESS_REQUIREMENTS_V1["story_validation"]
    item = {
        "schema_version": "1",
        "profile_id": profile["profile_id"],
        "profile_version": profile["profile_version"],
        "source_sha256": source_sha256,
        "state": state,
        "decided_at": decided_at or utc_now(),
        "evidence_id": evidence_id.strip(),
    }
    evidence = load_or_empty_evidence(job_dir)
    evidence["story_validation"] = _replace_bound_record(
        evidence["story_validation"],
        item,
        identity_fields=("profile_id", "profile_version", "source_sha256"),
    )
    persisted = _persist(job_dir, evidence)
    append_job_event(
        job_dir,
        "story-validation-recorded",
        "External Story Validation evidence recorded for exact retained source",
        state=state,
        evidence_id=item["evidence_id"],
        source_sha256=source_sha256,
    )
    return {"record": item, **persisted}


def record_production_validation(
    job_dir: Path,
    *,
    artifact_type: str,
    readiness_class: str,
    state: str,
    evidence_id: str,
) -> dict[str, Any]:
    if artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise ValueError("Unsupported artifact type")
    if readiness_class not in ARTIFACT_CLASSES:
        raise ValueError("Unsupported production readiness class")
    if artifact_type not in READINESS_ARTIFACT_MATRIX[readiness_class]:
        raise ValueError("Artifact type does not support that readiness class")
    if state not in {"pass", "fail"}:
        raise ValueError("Production validation state must be pass or fail")
    if not evidence_id.strip():
        raise ValueError("Production validation evidence_id is required")

    job_dir = Path(job_dir)
    context = authoritative_artifact_context(job_dir, artifact_type)
    profile = READINESS_REQUIREMENTS_V1["production_validation"][readiness_class]
    item = {
        "schema_version": "1",
        "readiness_class": readiness_class,
        "artifact_type": artifact_type,
        "source_sha256": context["source_sha256"],
        "artifact_sha256": context["artifact_sha256"],
        "production_config_sha256": context["production_config_sha256"],
        "assets_sha256": context["assets_sha256"],
        "profile_id": profile["profile_id"],
        "profile_version": profile["profile_version"],
        "state": state,
        "evidence_id": evidence_id.strip(),
    }
    evidence = load_or_empty_evidence(job_dir)
    evidence["production_validation"] = _replace_bound_record(
        evidence["production_validation"],
        item,
        identity_fields=(
            "readiness_class",
            "artifact_type",
            "profile_id",
            "profile_version",
            "source_sha256",
            "artifact_sha256",
            "production_config_sha256",
            "assets_sha256",
        ),
    )
    persisted = _persist(job_dir, evidence)
    append_job_event(
        job_dir,
        "production-validation-recorded",
        "Production validation evidence recorded for exact retained artifact",
        readiness_class=readiness_class,
        artifact_type=artifact_type,
        state=state,
        evidence_id=item["evidence_id"],
        artifact_sha256=context["artifact_sha256"],
    )
    return {"record": item, **persisted}


def record_human_acceptance(
    job_dir: Path,
    *,
    artifact_type: str,
    readiness_class: str,
    state: str,
    evidence_id: str,
    decided_at: str | None = None,
) -> dict[str, Any]:
    if artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise ValueError("Unsupported artifact type")
    if readiness_class not in PUBLICATION_CLASSES:
        raise ValueError("Human acceptance applies only to publication readiness classes")
    if artifact_type not in READINESS_ARTIFACT_MATRIX[readiness_class]:
        raise ValueError("Artifact type does not support that readiness class")
    if state not in {"accepted", "rejected"}:
        raise ValueError("Human acceptance state must be accepted or rejected")
    if not evidence_id.strip():
        raise ValueError("Human acceptance evidence_id is required")

    job_dir = Path(job_dir)
    context = authoritative_artifact_context(job_dir, artifact_type)
    profile = READINESS_REQUIREMENTS_V1["human_acceptance"][readiness_class]
    item = {
        "schema_version": "1",
        "readiness_class": readiness_class,
        "artifact_type": artifact_type,
        "artifact_sha256": context["artifact_sha256"],
        "profile_id": profile["profile_id"],
        "profile_version": profile["profile_version"],
        "state": state,
        "decided_at": decided_at or utc_now(),
        "evidence_id": evidence_id.strip(),
    }
    evidence = load_or_empty_evidence(job_dir)
    evidence["human_acceptance"] = _replace_bound_record(
        evidence["human_acceptance"],
        item,
        identity_fields=(
            "readiness_class",
            "artifact_type",
            "profile_id",
            "profile_version",
            "artifact_sha256",
        ),
    )
    persisted = _persist(job_dir, evidence)
    append_job_event(
        job_dir,
        "human-acceptance-recorded",
        "Human decision recorded for exact retained artifact",
        readiness_class=readiness_class,
        artifact_type=artifact_type,
        state=state,
        evidence_id=item["evidence_id"],
        artifact_sha256=context["artifact_sha256"],
    )
    return {"record": item, **persisted}


def evaluate_job_readiness(job_dir: Path) -> dict[str, Any]:
    job_dir = Path(job_dir)
    evidence = load_or_empty_evidence(job_dir)
    requirements = readiness_requirements()
    reports = {}
    for artifact_type in SUPPORTED_ARTIFACT_TYPES:
        reports[artifact_type] = evaluate_readiness(
            evidence,
            requirements=requirements,
            job_dir=job_dir,
            artifact_type=artifact_type,
        )
    return {
        "requirements": requirements,
        "evidence": evidence,
        "artifacts": reports,
    }
