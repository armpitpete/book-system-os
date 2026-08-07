from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from app.services.provenance import (
    PROVENANCE_UNAVAILABLE,
    ProvenanceError,
    verify_job_source,
)
from app.utils.atomic_files import atomic_write_json

CONTRACT = "BOS-RDY-001"
SCHEMA_VERSION = "1"
EVIDENCE_FILENAME = "bos-rdy-001.json"
READINESS_CLASSES = (
    "story-ready",
    "production-valid",
    "digital-publication-ready",
    "print-ready",
)
ARTIFACT_CLASSES = READINESS_CLASSES[1:]
PUBLICATION_CLASSES = READINESS_CLASSES[2:]


class ArtifactReadinessError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(
        ord(c) < 32 or ord(c) == 127 for c in value
    )


def _exact_keys(value: Any, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _profile(value: Any) -> bool:
    return (
        _exact_keys(value, {"profile_id", "profile_version"})
        and _text(value["profile_id"])
        and _text(value["profile_version"])
    )


def _story(value: Any) -> bool:
    keys = {
        "schema_version", "profile_id", "profile_version", "source_sha256",
        "state", "decided_at", "evidence_id",
    }
    return (
        _exact_keys(value, keys)
        and value["schema_version"] == SCHEMA_VERSION
        and _text(value["profile_id"])
        and _text(value["profile_version"])
        and _sha(value["source_sha256"])
        and value["state"] in {"pass", "fail"}
        and _text(value["decided_at"])
        and _text(value["evidence_id"])
    )


def _production(value: Any) -> bool:
    keys = {
        "schema_version", "readiness_class", "artifact_type", "source_sha256",
        "artifact_sha256", "production_config_sha256", "assets_sha256",
        "profile_id", "profile_version", "state", "evidence_id",
    }
    return (
        _exact_keys(value, keys)
        and value["schema_version"] == SCHEMA_VERSION
        and value["readiness_class"] in ARTIFACT_CLASSES
        and _text(value["artifact_type"])
        and _sha(value["source_sha256"])
        and _sha(value["artifact_sha256"])
        and _sha(value["production_config_sha256"])
        and _sha(value["assets_sha256"])
        and _text(value["profile_id"])
        and _text(value["profile_version"])
        and value["state"] in {"pass", "fail"}
        and _text(value["evidence_id"])
    )


def _acceptance(value: Any) -> bool:
    keys = {
        "schema_version", "readiness_class", "artifact_type", "artifact_sha256",
        "profile_id", "profile_version", "state", "decided_at", "evidence_id",
    }
    return (
        _exact_keys(value, keys)
        and value["schema_version"] == SCHEMA_VERSION
        and value["readiness_class"] in PUBLICATION_CLASSES
        and _text(value["artifact_type"])
        and _sha(value["artifact_sha256"])
        and _text(value["profile_id"])
        and _text(value["profile_version"])
        and value["state"] in {"accepted", "rejected"}
        and _text(value["decided_at"])
        and _text(value["evidence_id"])
    )


def _parse_evidence(value: Any) -> dict[str, Any]:
    if not _exact_keys(
        value,
        {"schema_version", "story_validation", "production_validation", "human_acceptance"},
    ):
        raise ValueError("invalid evidence bundle")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported evidence schema")
    groups = (
        ("story_validation", _story),
        ("production_validation", _production),
        ("human_acceptance", _acceptance),
    )
    for name, validator in groups:
        if not isinstance(value[name], list) or not all(validator(x) for x in value[name]):
            raise ValueError(f"invalid {name}")

    uniqueness = {
        "story_validation": lambda x: (
            x["profile_id"], x["profile_version"], x["source_sha256"]
        ),
        "production_validation": lambda x: (
            x["readiness_class"], x["artifact_type"], x["profile_id"],
            x["profile_version"], x["source_sha256"], x["artifact_sha256"],
            x["production_config_sha256"], x["assets_sha256"],
        ),
        "human_acceptance": lambda x: (
            x["readiness_class"], x["artifact_type"], x["profile_id"],
            x["profile_version"], x["artifact_sha256"],
        ),
    }
    for name, identity in uniqueness.items():
        identities = [identity(item) for item in value[name]]
        if len(identities) != len(set(identities)):
            raise ValueError(f"ambiguous duplicate {name}")
    return value


def _parse_requirements(value: Any) -> dict[str, Any]:
    if not _exact_keys(
        value,
        {"schema_version", "story_validation", "production_validation", "human_acceptance"},
    ):
        raise ValueError("invalid requirements")
    if value["schema_version"] != SCHEMA_VERSION or not _profile(value["story_validation"]):
        raise ValueError("invalid requirements")
    for name, allowed in (
        ("production_validation", set(ARTIFACT_CLASSES)),
        ("human_acceptance", set(PUBLICATION_CLASSES)),
    ):
        group = value[name]
        if not isinstance(group, dict) or not set(group).issubset(allowed):
            raise ValueError("invalid requirements")
        if not all(_profile(profile) for profile in group.values()):
            raise ValueError("invalid requirements")
    return value


def _parse_context(value: Any) -> dict[str, Any]:
    keys = {
        "schema_version", "source_sha256", "artifact_type", "artifact_sha256",
        "production_config_sha256", "assets_sha256",
    }
    if not _exact_keys(value, keys) or value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("invalid context")
    if not _sha(value["source_sha256"]):
        raise ValueError("invalid source digest")
    if value["artifact_type"] is not None and not _text(value["artifact_type"]):
        raise ValueError("invalid artifact type")
    for key in ("artifact_sha256", "production_config_sha256", "assets_sha256"):
        if value[key] is not None and not _sha(value[key]):
            raise ValueError("invalid context digest")
    return value


def _state(ready: bool, reasons: list[str]) -> dict[str, Any]:
    return {"ready": ready, "reasons": [] if ready else reasons}


def _all_failed(reason: str) -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "states": {name: _state(False, [reason]) for name in READINESS_CLASSES},
    }


def unevaluated_readiness_report(
    reason: str = "readiness-evidence-not-evaluated",
) -> dict[str, Any]:
    report = _all_failed(reason)
    report["evaluated"] = False
    return report


def _match_profile(item: Mapping[str, Any], profile: Mapping[str, Any]) -> bool:
    return (
        item["profile_id"] == profile["profile_id"]
        and item["profile_version"] == profile["profile_version"]
    )


def _story_state(evidence: dict[str, Any], req: dict[str, Any], ctx: dict[str, Any]):
    items = evidence["story_validation"]
    profile = [x for x in items if _match_profile(x, req["story_validation"])]
    if not profile:
        return _state(False, [
            "story-validation-missing" if not items else "story-validation-profile-mismatch"
        ])
    exact = [x for x in profile if x["source_sha256"] == ctx["source_sha256"]]
    if not exact:
        return _state(False, ["story-validation-source-sha256-mismatch"])
    return _state(exact[0]["state"] == "pass", ["story-validation-not-passed"])


def _artifact_context(ctx: dict[str, Any]) -> bool:
    return all(ctx[x] is not None for x in (
        "artifact_type", "artifact_sha256", "production_config_sha256", "assets_sha256"
    ))


def _production_state(
    readiness_class: str,
    evidence: dict[str, Any],
    req: dict[str, Any],
    ctx: dict[str, Any],
):
    if not _artifact_context(ctx):
        return _state(False, ["artifact-context-missing"])
    expected = req["production_validation"].get(readiness_class)
    if expected is None:
        return _state(False, ["production-validation-profile-unsupported"])
    items = [
        x for x in evidence["production_validation"]
        if x["readiness_class"] == readiness_class and x["artifact_type"] == ctx["artifact_type"]
    ]
    if not items:
        return _state(False, ["production-validation-missing"])
    checks = (
        (lambda x: _match_profile(x, expected), "production-validation-profile-mismatch"),
        (lambda x: x["source_sha256"] == ctx["source_sha256"],
         "production-validation-source-sha256-mismatch"),
        (lambda x: x["artifact_sha256"] == ctx["artifact_sha256"],
         "production-validation-artifact-sha256-mismatch"),
        (lambda x: x["production_config_sha256"] == ctx["production_config_sha256"],
         "production-validation-config-sha256-mismatch"),
        (lambda x: x["assets_sha256"] == ctx["assets_sha256"],
         "production-validation-assets-sha256-mismatch"),
    )
    for predicate, reason in checks:
        items = [x for x in items if predicate(x)]
        if not items:
            return _state(False, [reason])
    return _state(items[0]["state"] == "pass", ["production-validation-not-passed"])


def _acceptance_state(
    readiness_class: str,
    evidence: dict[str, Any],
    req: dict[str, Any],
    ctx: dict[str, Any],
):
    if ctx["artifact_type"] is None or ctx["artifact_sha256"] is None:
        return _state(False, ["artifact-context-missing"])
    expected = req["human_acceptance"].get(readiness_class)
    if expected is None:
        return _state(False, ["human-acceptance-profile-unsupported"])
    items = [
        x for x in evidence["human_acceptance"]
        if x["readiness_class"] == readiness_class and x["artifact_type"] == ctx["artifact_type"]
    ]
    if not items:
        return _state(False, ["human-acceptance-missing"])
    items = [x for x in items if _match_profile(x, expected)]
    if not items:
        return _state(False, ["human-acceptance-profile-mismatch"])
    items = [x for x in items if x["artifact_sha256"] == ctx["artifact_sha256"]]
    if not items:
        return _state(False, ["human-acceptance-artifact-sha256-mismatch"])
    return _state(items[0]["state"] == "accepted", ["human-acceptance-not-accepted"])


def evaluate_readiness(
    evidence: Mapping[str, Any],
    *,
    requirements: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        ev = _parse_evidence(dict(evidence))
    except (TypeError, ValueError):
        return _all_failed("readiness-evidence-invalid")
    try:
        req = _parse_requirements(dict(requirements))
    except (TypeError, ValueError):
        return _all_failed("readiness-requirements-invalid")
    try:
        ctx = _parse_context(dict(context))
    except (TypeError, ValueError):
        return _all_failed("readiness-context-invalid")

    story = _story_state(ev, req, ctx)
    states = {
        "story-ready": story,
        "production-valid": _production_state("production-valid", ev, req, ctx),
    }
    for name in PUBLICATION_CLASSES:
        prod = _production_state(name, ev, req, ctx)
        accept = _acceptance_state(name, ev, req, ctx)
        reasons: list[str] = []
        if not story["ready"]:
            reasons += ["story-not-ready", *story["reasons"]]
        if not prod["ready"]:
            reasons += ["production-not-valid", *prod["reasons"]]
        if not accept["ready"]:
            reasons += ["human-acceptance-not-valid", *accept["reasons"]]
        states[name] = _state(not reasons, reasons)
    return {"contract": CONTRACT, "states": states}


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def readiness_evidence_path(job_dir: Path) -> Path:
    return Path(job_dir) / "evidence" / EVIDENCE_FILENAME


def persist_readiness_evidence(job_dir: Path, evidence: Mapping[str, Any]) -> dict[str, Any]:
    try:
        ev = _parse_evidence(dict(evidence))
    except (TypeError, ValueError) as exc:
        raise ArtifactReadinessError(
            "readiness-evidence-invalid", "BOS-RDY-001 evidence is invalid"
        ) from exc
    try:
        provenance = verify_job_source(Path(job_dir))
    except ProvenanceError as exc:
        raise ArtifactReadinessError(exc.code, str(exc)) from exc
    if provenance.get("state") == PROVENANCE_UNAVAILABLE:
        raise ArtifactReadinessError(
            "provenance-unavailable", "Exact retained manuscript provenance is required"
        )
    source = provenance["source_identity"]["source_sha256"]
    bound = {x["source_sha256"] for x in ev["story_validation"]}
    bound |= {x["source_sha256"] for x in ev["production_validation"]}
    if any(x != source for x in bound):
        raise ArtifactReadinessError(
            "readiness-source-sha256-mismatch",
            "Readiness evidence is not bound to the retained manuscript",
        )
    digest = _canonical_sha256(ev)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT,
        "evidence_sha256": digest,
        "evidence": ev,
    }
    atomic_write_json(
        readiness_evidence_path(Path(job_dir)),
        envelope,
        sort_keys=True,
        ensure_ascii=False,
    )
    return {"contract": CONTRACT, "evidence_sha256": digest}


def load_readiness_evidence(job_dir: Path) -> dict[str, Any]:
    path = readiness_evidence_path(Path(job_dir))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArtifactReadinessError(
            "readiness-evidence-missing", "BOS-RDY-001 evidence is missing"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactReadinessError(
            "readiness-evidence-invalid", "BOS-RDY-001 evidence is unreadable"
        ) from exc
    if not _exact_keys(raw, {"schema_version", "contract", "evidence_sha256", "evidence"}):
        raise ArtifactReadinessError(
            "readiness-evidence-invalid", "BOS-RDY-001 evidence envelope is invalid"
        )
    if raw["schema_version"] != SCHEMA_VERSION or raw["contract"] != CONTRACT:
        raise ArtifactReadinessError(
            "readiness-evidence-invalid", "BOS-RDY-001 evidence schema is unsupported"
        )
    try:
        ev = _parse_evidence(raw["evidence"])
    except ValueError as exc:
        raise ArtifactReadinessError(
            "readiness-evidence-invalid", "BOS-RDY-001 evidence is invalid"
        ) from exc
    if not _sha(raw["evidence_sha256"]) or raw["evidence_sha256"] != _canonical_sha256(ev):
        raise ArtifactReadinessError(
            "readiness-evidence-integrity-mismatch",
            "BOS-RDY-001 evidence digest does not match its payload",
        )
    try:
        provenance = verify_job_source(Path(job_dir))
    except ProvenanceError as exc:
        raise ArtifactReadinessError(exc.code, str(exc)) from exc
    if provenance.get("state") == PROVENANCE_UNAVAILABLE:
        raise ArtifactReadinessError(
            "provenance-unavailable", "Exact retained manuscript provenance is required"
        )
    source = provenance["source_identity"]["source_sha256"]
    bound = {x["source_sha256"] for x in ev["story_validation"]}
    bound |= {x["source_sha256"] for x in ev["production_validation"]}
    if any(x != source for x in bound):
        raise ArtifactReadinessError(
            "readiness-source-sha256-mismatch",
            "Persisted readiness evidence is stale for the retained manuscript",
        )
    return ev
