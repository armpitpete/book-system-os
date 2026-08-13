from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from app.services.publishing_metadata import (
    PublishingMetadataError,
    empty_publishing_metadata,
    load_job_publishing_metadata,
    parse_publishing_metadata,
)
from app.services.provenance import (
    PROVENANCE_UNAVAILABLE,
    STRUCTURAL_TRANSFORMATION_ID,
    STRUCTURAL_TRANSFORMATION_VERSION,
    ProvenanceError,
    sha256_file,
    verify_job_source,
)
from app.utils.atomic_files import atomic_write_json

CONTRACT = "BOS-RDY-001"
SCHEMA_VERSION = "1"
ARTIFACT_CONTRACT_VERSION = "1"
EVIDENCE_FILENAME = "bos-rdy-001.json"
READINESS_CLASSES = (
    "story-ready", "production-valid", "digital-publication-ready", "print-ready"
)
ARTIFACT_CLASSES = READINESS_CLASSES[1:]
PUBLICATION_CLASSES = READINESS_CLASSES[2:]
SUPPORTED_ARTIFACT_TYPES = ("pdf_standard", "pdf_nd", "epub", "docx")
READINESS_ARTIFACT_MATRIX = {
    "production-valid": frozenset(SUPPORTED_ARTIFACT_TYPES),
    "digital-publication-ready": frozenset({"pdf_standard", "pdf_nd", "epub"}),
    "print-ready": frozenset({"pdf_standard", "pdf_nd"}),
}


class ArtifactReadinessError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(
        ord(c) < 32 or ord(c) == 127 for c in value
    )


def _exact(value: Any, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _profile(value: Any) -> bool:
    return _exact(value, {"profile_id", "profile_version"}) and all(
        _text(value[key]) for key in ("profile_id", "profile_version")
    )


def _story(value: Any) -> bool:
    keys = {
        "schema_version", "profile_id", "profile_version", "source_sha256",
        "state", "decided_at", "evidence_id",
    }
    return (
        _exact(value, keys)
        and value["schema_version"] == SCHEMA_VERSION
        and all(_text(value[key]) for key in ("profile_id", "profile_version", "decided_at", "evidence_id"))
        and _sha(value["source_sha256"])
        and value["state"] in {"pass", "fail"}
    )


def _production(value: Any) -> bool:
    keys = {
        "schema_version", "readiness_class", "artifact_type", "source_sha256",
        "artifact_sha256", "production_config_sha256", "assets_sha256",
        "profile_id", "profile_version", "state", "evidence_id",
    }
    return (
        _exact(value, keys)
        and value["schema_version"] == SCHEMA_VERSION
        and value["readiness_class"] in ARTIFACT_CLASSES
        and value["artifact_type"] in SUPPORTED_ARTIFACT_TYPES
        and all(_sha(value[key]) for key in (
            "source_sha256", "artifact_sha256", "production_config_sha256", "assets_sha256"
        ))
        and all(_text(value[key]) for key in ("profile_id", "profile_version", "evidence_id"))
        and value["state"] in {"pass", "fail"}
    )


def _acceptance(value: Any) -> bool:
    keys = {
        "schema_version", "readiness_class", "artifact_type", "artifact_sha256",
        "profile_id", "profile_version", "state", "decided_at", "evidence_id",
    }
    return (
        _exact(value, keys)
        and value["schema_version"] == SCHEMA_VERSION
        and value["readiness_class"] in PUBLICATION_CLASSES
        and value["artifact_type"] in SUPPORTED_ARTIFACT_TYPES
        and _sha(value["artifact_sha256"])
        and all(_text(value[key]) for key in (
            "profile_id", "profile_version", "decided_at", "evidence_id"
        ))
        and value["state"] in {"accepted", "rejected"}
    )


def _parse_evidence(value: Any) -> dict[str, Any]:
    keys = {"schema_version", "story_validation", "production_validation", "human_acceptance"}
    if not _exact(value, keys) or value["schema_version"] != SCHEMA_VERSION:
        raise ValueError("invalid evidence bundle")
    validators = {
        "story_validation": _story,
        "production_validation": _production,
        "human_acceptance": _acceptance,
    }
    for name, validator in validators.items():
        if not isinstance(value[name], list) or not all(validator(item) for item in value[name]):
            raise ValueError(f"invalid {name}")
    identities = {
        "story_validation": lambda x: (x["profile_id"], x["profile_version"], x["source_sha256"]),
        "production_validation": lambda x: (
            x["readiness_class"], x["artifact_type"], x["profile_id"], x["profile_version"],
            x["source_sha256"], x["artifact_sha256"], x["production_config_sha256"], x["assets_sha256"],
        ),
        "human_acceptance": lambda x: (
            x["readiness_class"], x["artifact_type"], x["profile_id"], x["profile_version"], x["artifact_sha256"],
        ),
    }
    for name, identity in identities.items():
        values = [identity(item) for item in value[name]]
        if len(values) != len(set(values)):
            raise ValueError(f"ambiguous duplicate {name}")
    return value


def _parse_requirements(value: Any) -> dict[str, Any]:
    keys = {"schema_version", "story_validation", "production_validation", "human_acceptance"}
    if not _exact(value, keys) or value["schema_version"] != SCHEMA_VERSION or not _profile(value["story_validation"]):
        raise ValueError("invalid requirements")
    for name, allowed in (
        ("production_validation", set(ARTIFACT_CLASSES)),
        ("human_acceptance", set(PUBLICATION_CLASSES)),
    ):
        group = value[name]
        if not isinstance(group, dict) or not set(group).issubset(allowed) or not all(
            _profile(profile) for profile in group.values()
        ):
            raise ValueError("invalid requirements")
    return value


def _state(ready: bool, reasons: list[str]) -> dict[str, Any]:
    return {"ready": ready, "reasons": [] if ready else reasons}


def _all_failed(reason: str) -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "states": {name: _state(False, [reason]) for name in READINESS_CLASSES},
    }


def unevaluated_readiness_report(reason: str = "readiness-evidence-not-evaluated") -> dict[str, Any]:
    report = _all_failed(reason)
    report["evaluated"] = False
    return report


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _output_specs() -> dict[str, Any]:
    from app.services.publish_plan import PUBLISH_OUTPUTS

    specs = {output.key: output for output in PUBLISH_OUTPUTS}
    if set(specs) != set(SUPPORTED_ARTIFACT_TYPES):
        raise ArtifactReadinessError(
            "readiness-artifact-contract-drift",
            "BOS-RDY-001 artifact types differ from the publish output contract",
        )
    return specs


def _production_config_sha256(
    artifact_type: str, publishing_metadata: Mapping[str, str | None] | None = None
) -> str:
    try:
        spec = _output_specs()[artifact_type]
    except KeyError as exc:
        raise ArtifactReadinessError(
            "readiness-artifact-type-unsupported",
            "Artifact type is not supported by BOS-RDY-001",
        ) from exc

    from app.pipeline.exporters import _pandoc_command

    metadata = dict(publishing_metadata or empty_publishing_metadata())
    command = _pandoc_command(
        Path("__BOOK__.md"), spec, publishing_metadata=metadata
    )
    template = None
    normalised = []
    for argument in command:
        if not argument.startswith("--template="):
            normalised.append(argument)
            continue
        path = Path(argument.split("=", 1)[1])
        if not path.is_file():
            raise ArtifactReadinessError(
                "readiness-production-config-unavailable",
                "Configured export template is unavailable",
            )
        template = {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        normalised.append(f"--template={path.name}")
    return _canonical_sha256(
        {
            "schema_version": "2",
            "artifact_type": artifact_type,
            "output": {"filename": spec.filename, "media_type": spec.media_type},
            "pandoc_command": normalised,
            "publishing_metadata": metadata,
            "template": template,
            "structural_transformation": {
                "identifier": STRUCTURAL_TRANSFORMATION_ID,
                "version": STRUCTURAL_TRANSFORMATION_VERSION,
            },
        }
    )


def _asset_records(job_dir: Path) -> list[dict[str, Any]]:
    input_dir = job_dir / "input"
    input_file = input_dir / "book.md"
    if not input_file.is_file():
        raise ArtifactReadinessError("source-input-missing", "Retained source input/book.md is missing")

    records: dict[str, dict[str, Any]] = {}
    for path in sorted(input_dir.rglob("*")):
        if path.is_file() and path != input_file:
            relative = path.relative_to(input_dir).as_posix()
            records[f"input:{relative}"] = {
                "kind": "retained-input", "identity": relative,
                "bytes": path.stat().st_size, "sha256": sha256_file(path),
            }

    markdown = input_file.read_text(encoding="utf-8")
    if "![" not in markdown:
        return sorted(records.values(), key=lambda item: (item["kind"], item["identity"]))

    from app.pipeline.input_validation import _image_target, _local_image_path, _parse_document, _walk_nodes

    try:
        document = _parse_document(markdown)
    except RuntimeError as exc:
        raise ArtifactReadinessError(
            "readiness-assets-unverifiable", "Manuscript image references could not be inspected"
        ) from exc
    blocks = document.get("blocks")
    if not isinstance(blocks, list):
        raise ArtifactReadinessError(
            "readiness-assets-unverifiable", "Manuscript image references could not be inspected"
        )
    for node in _walk_nodes(blocks):
        target = _image_target(node)
        if target is None:
            continue
        path = _local_image_path(target, input_dir)
        if path is None:
            if urlsplit(target).scheme.lower() == "data":
                digest = hashlib.sha256(target.encode("utf-8")).hexdigest()
                records[f"embedded:{digest}"] = {
                    "kind": "embedded-data", "identity": digest,
                    "bytes": len(target.encode("utf-8")), "sha256": digest,
                }
                continue
            raise ArtifactReadinessError(
                "readiness-assets-unverifiable",
                "Non-retained external image assets cannot support BOS-RDY-001 readiness",
            )
        if not path.is_file():
            raise ArtifactReadinessError("readiness-asset-missing", "A referenced local image asset is missing")
        try:
            relative = path.relative_to(input_dir).as_posix()
            key, kind, identity = f"input:{relative}", "retained-input", relative
        except ValueError:
            key, kind, identity = f"external-local:{target}", "external-local", target
        records[key] = {
            "kind": kind, "identity": identity,
            "bytes": path.stat().st_size, "sha256": sha256_file(path),
        }
    return sorted(records.values(), key=lambda item: (item["kind"], item["identity"]))


def _assets_sha256(job_dir: Path) -> str:
    return _canonical_sha256({"schema_version": "1", "assets": _asset_records(job_dir)})


def _source_sha256(job_dir: Path) -> str:
    try:
        provenance = verify_job_source(job_dir)
    except ProvenanceError as exc:
        raise ArtifactReadinessError(exc.code, str(exc)) from exc
    if provenance.get("state") == PROVENANCE_UNAVAILABLE:
        raise ArtifactReadinessError("provenance-unavailable", "Exact retained manuscript provenance is required")
    return provenance["source_identity"]["source_sha256"]


def _manifest(job_dir: Path) -> dict[str, Any]:
    try:
        value = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArtifactReadinessError("readiness-artifact-manifest-missing", "Artifact derivation manifest is missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactReadinessError("readiness-artifact-manifest-invalid", "Artifact derivation manifest is unreadable") from exc
    if not isinstance(value, dict):
        raise ArtifactReadinessError("readiness-artifact-manifest-invalid", "Artifact derivation manifest is invalid")
    return value


def _bound_publishing_metadata(job_dir: Path, manifest: Mapping[str, Any]) -> dict[str, str | None]:
    try:
        current = load_job_publishing_metadata(job_dir)
    except PublishingMetadataError as exc:
        raise ArtifactReadinessError(exc.code, str(exc)) from exc

    if "publishing_metadata" not in manifest:
        if current != empty_publishing_metadata():
            raise ArtifactReadinessError(
                "readiness-artifact-manifest-config-mismatch",
                "Artifact manifest does not retain the job publishing metadata",
            )
        return current

    try:
        recorded = parse_publishing_metadata(manifest["publishing_metadata"])
    except PublishingMetadataError as exc:
        raise ArtifactReadinessError(
            "readiness-artifact-manifest-invalid",
            "Artifact manifest publishing metadata is invalid",
        ) from exc
    if recorded != current:
        raise ArtifactReadinessError(
            "readiness-artifact-manifest-config-mismatch",
            "Artifact manifest publishing metadata differs from the retained job configuration",
        )
    return current


def authoritative_artifact_context(job_dir: Path, artifact_type: str) -> dict[str, Any]:
    job_dir = Path(job_dir)
    if artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise ArtifactReadinessError(
            "readiness-artifact-type-unsupported", "Artifact type is not supported by BOS-RDY-001"
        )
    spec = _output_specs()[artifact_type]
    source = _source_sha256(job_dir)
    manifest = _manifest(job_dir)
    publishing_metadata = _bound_publishing_metadata(job_dir, manifest)
    manifest_source = manifest.get("source_identity")
    if not isinstance(manifest_source, dict) or manifest_source.get("source_sha256") != source:
        raise ArtifactReadinessError(
            "readiness-artifact-manifest-source-mismatch", "Artifact manifest is not bound to the retained manuscript"
        )
    if not isinstance(manifest.get("outputs"), dict) or manifest["outputs"].get(artifact_type) != spec.filename:
        raise ArtifactReadinessError(
            "readiness-artifact-manifest-invalid", "Artifact manifest does not declare the requested output"
        )
    output_evidence = manifest.get("output_evidence")
    if not isinstance(output_evidence, list):
        raise ArtifactReadinessError("readiness-artifact-manifest-invalid", "Artifact manifest output evidence is invalid")
    matching = [item for item in output_evidence if isinstance(item, dict) and item.get("key") == artifact_type]
    if len(matching) != 1:
        raise ArtifactReadinessError(
            "readiness-artifact-manifest-invalid", "Artifact manifest must contain one exact output evidence record"
        )
    recorded = matching[0]
    if (
        recorded.get("filename") != spec.filename
        or recorded.get("media_type") != spec.media_type
        or not isinstance(recorded.get("bytes"), int)
        or recorded["bytes"] <= 0
        or not _sha(recorded.get("sha256"))
    ):
        raise ArtifactReadinessError("readiness-artifact-manifest-invalid", "Artifact manifest output evidence is invalid")

    path = job_dir / "output" / spec.filename
    if path.is_symlink() or not path.is_file():
        raise ArtifactReadinessError(
            "readiness-artifact-missing", "Exact generated artifact is missing or is not a retained file"
        )
    actual_bytes, actual_sha = path.stat().st_size, sha256_file(path)
    if actual_bytes != recorded["bytes"] or actual_sha != recorded["sha256"]:
        raise ArtifactReadinessError(
            "readiness-artifact-integrity-mismatch", "Generated artifact bytes differ from the derivation manifest"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "source_sha256": source,
        "artifact_type": artifact_type,
        "artifact_sha256": actual_sha,
        "production_config_sha256": _production_config_sha256(
            artifact_type, publishing_metadata
        ),
        "assets_sha256": _assets_sha256(job_dir),
    }


def _match_profile(item: Mapping[str, Any], profile: Mapping[str, Any]) -> bool:
    return item["profile_id"] == profile["profile_id"] and item["profile_version"] == profile["profile_version"]


def _story_state(evidence: dict[str, Any], req: dict[str, Any], source: str) -> dict[str, Any]:
    items = [item for item in evidence["story_validation"] if _match_profile(item, req["story_validation"])]
    if not items:
        return _state(False, [
            "story-validation-missing" if not evidence["story_validation"] else "story-validation-profile-mismatch"
        ])
    items = [item for item in items if item["source_sha256"] == source]
    if not items:
        return _state(False, ["story-validation-source-sha256-mismatch"])
    return _state(items[0]["state"] == "pass", ["story-validation-not-passed"])


def _production_state(name: str, evidence: dict[str, Any], req: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    artifact_type = ctx["artifact_type"]
    if artifact_type not in READINESS_ARTIFACT_MATRIX[name]:
        return _state(False, ["artifact-readiness-class-unsupported"])
    expected = req["production_validation"].get(name)
    if expected is None:
        return _state(False, ["production-validation-profile-unsupported"])
    items = [item for item in evidence["production_validation"] if item["readiness_class"] == name and item["artifact_type"] == artifact_type]
    if not items:
        return _state(False, ["production-validation-missing"])
    checks = (
        (lambda x: _match_profile(x, expected), "production-validation-profile-mismatch"),
        (lambda x: x["source_sha256"] == ctx["source_sha256"], "production-validation-source-sha256-mismatch"),
        (lambda x: x["artifact_sha256"] == ctx["artifact_sha256"], "production-validation-artifact-sha256-mismatch"),
        (lambda x: x["production_config_sha256"] == ctx["production_config_sha256"], "production-validation-config-sha256-mismatch"),
        (lambda x: x["assets_sha256"] == ctx["assets_sha256"], "production-validation-assets-sha256-mismatch"),
    )
    for predicate, reason in checks:
        items = [item for item in items if predicate(item)]
        if not items:
            return _state(False, [reason])
    return _state(items[0]["state"] == "pass", ["production-validation-not-passed"])


def _acceptance_state(name: str, evidence: dict[str, Any], req: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    artifact_type = ctx["artifact_type"]
    if artifact_type not in READINESS_ARTIFACT_MATRIX[name]:
        return _state(False, ["artifact-readiness-class-unsupported"])
    expected = req["human_acceptance"].get(name)
    if expected is None:
        return _state(False, ["human-acceptance-profile-unsupported"])
    items = [item for item in evidence["human_acceptance"] if item["readiness_class"] == name and item["artifact_type"] == artifact_type]
    if not items:
        return _state(False, ["human-acceptance-missing"])
    items = [item for item in items if _match_profile(item, expected)]
    if not items:
        return _state(False, ["human-acceptance-profile-mismatch"])
    items = [item for item in items if item["artifact_sha256"] == ctx["artifact_sha256"]]
    if not items:
        return _state(False, ["human-acceptance-artifact-sha256-mismatch"])
    return _state(items[0]["state"] == "accepted", ["human-acceptance-not-accepted"])


def _evaluate(evidence: dict[str, Any], req: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    story = _story_state(evidence, req, ctx["source_sha256"])
    states = {
        "story-ready": story,
        "production-valid": _production_state("production-valid", evidence, req, ctx),
    }
    for name in PUBLICATION_CLASSES:
        production = _production_state(name, evidence, req, ctx)
        acceptance = _acceptance_state(name, evidence, req, ctx)
        reasons = []
        if not story["ready"]:
            reasons += ["story-not-ready", *story["reasons"]]
        if not production["ready"]:
            reasons += ["production-not-valid", *production["reasons"]]
        if not acceptance["ready"]:
            reasons += ["human-acceptance-not-valid", *acceptance["reasons"]]
        states[name] = _state(not reasons, reasons)
    return {
        "contract": CONTRACT,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "artifact_type": ctx["artifact_type"],
        "states": states,
    }


def evaluate_readiness(
    evidence: Mapping[str, Any], *, requirements: Mapping[str, Any], job_dir: Path, artifact_type: str
) -> dict[str, Any]:
    """Evaluate real retained state; caller-supplied current-state hashes are not accepted."""
    try:
        ev = _parse_evidence(dict(evidence))
    except (TypeError, ValueError):
        return _all_failed("readiness-evidence-invalid")
    try:
        req = _parse_requirements(dict(requirements))
    except (TypeError, ValueError):
        return _all_failed("readiness-requirements-invalid")
    try:
        source = _source_sha256(Path(job_dir))
    except ArtifactReadinessError as exc:
        return _all_failed(exc.code)
    story = _story_state(ev, req, source)
    try:
        ctx = authoritative_artifact_context(Path(job_dir), artifact_type)
    except ArtifactReadinessError as exc:
        states = {"story-ready": story, "production-valid": _state(False, [exc.code])}
        for name in PUBLICATION_CLASSES:
            reasons = ([] if story["ready"] else ["story-not-ready", *story["reasons"]])
            reasons += ["production-not-valid", exc.code, "human-acceptance-not-valid", exc.code]
            states[name] = _state(False, reasons)
        return {
            "contract": CONTRACT,
            "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
            "artifact_type": artifact_type,
            "states": states,
        }
    return _evaluate(ev, req, ctx)


def readiness_evidence_path(job_dir: Path) -> Path:
    return Path(job_dir) / "evidence" / EVIDENCE_FILENAME


def _verify_evidence_bindings(job_dir: Path, evidence: dict[str, Any]) -> None:
    source = _source_sha256(job_dir)
    if any(item["source_sha256"] != source for item in evidence["story_validation"]):
        raise ArtifactReadinessError(
            "readiness-source-sha256-mismatch", "Story Validation evidence is not bound to the retained manuscript"
        )
    contexts: dict[str, dict[str, Any]] = {}

    def context(artifact_type: str) -> dict[str, Any]:
        if artifact_type not in contexts:
            contexts[artifact_type] = authoritative_artifact_context(job_dir, artifact_type)
        return contexts[artifact_type]

    for item in evidence["production_validation"]:
        if item["artifact_type"] not in READINESS_ARTIFACT_MATRIX[item["readiness_class"]]:
            raise ArtifactReadinessError(
                "artifact-readiness-class-unsupported", "Production evidence uses an unsupported artifact/readiness combination"
            )
        current = context(item["artifact_type"])
        for field, code in (
            ("source_sha256", "readiness-source-sha256-mismatch"),
            ("artifact_sha256", "readiness-artifact-sha256-mismatch"),
            ("production_config_sha256", "readiness-production-config-sha256-mismatch"),
            ("assets_sha256", "readiness-assets-sha256-mismatch"),
        ):
            if item[field] != current[field]:
                raise ArtifactReadinessError(code, "Production validation evidence is stale for the retained artifact")
    for item in evidence["human_acceptance"]:
        if item["artifact_type"] not in READINESS_ARTIFACT_MATRIX[item["readiness_class"]]:
            raise ArtifactReadinessError(
                "artifact-readiness-class-unsupported", "Human acceptance uses an unsupported artifact/readiness combination"
            )
        if item["artifact_sha256"] != context(item["artifact_type"])["artifact_sha256"]:
            raise ArtifactReadinessError(
                "readiness-artifact-sha256-mismatch", "Human acceptance is stale for the retained artifact"
            )


def persist_readiness_evidence(job_dir: Path, evidence: Mapping[str, Any]) -> dict[str, Any]:
    try:
        ev = _parse_evidence(dict(evidence))
    except (TypeError, ValueError) as exc:
        raise ArtifactReadinessError("readiness-evidence-invalid", "BOS-RDY-001 evidence is invalid") from exc
    _verify_evidence_bindings(Path(job_dir), ev)
    digest = _canonical_sha256(ev)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "evidence_sha256": digest,
        "evidence": ev,
    }
    atomic_write_json(readiness_evidence_path(Path(job_dir)), envelope, sort_keys=True, ensure_ascii=False)
    return {"contract": CONTRACT, "evidence_sha256": digest}


def load_readiness_evidence(job_dir: Path) -> dict[str, Any]:
    path = readiness_evidence_path(Path(job_dir))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArtifactReadinessError("readiness-evidence-missing", "BOS-RDY-001 evidence is missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactReadinessError("readiness-evidence-invalid", "BOS-RDY-001 evidence is unreadable") from exc
    keys = {"schema_version", "contract", "artifact_contract_version", "evidence_sha256", "evidence"}
    if not _exact(raw, keys) or (
        raw["schema_version"] != SCHEMA_VERSION
        or raw["contract"] != CONTRACT
        or raw["artifact_contract_version"] != ARTIFACT_CONTRACT_VERSION
    ):
        raise ArtifactReadinessError("readiness-evidence-invalid", "BOS-RDY-001 evidence envelope is invalid")
    try:
        ev = _parse_evidence(raw["evidence"])
    except ValueError as exc:
        raise ArtifactReadinessError("readiness-evidence-invalid", "BOS-RDY-001 evidence is invalid") from exc
    if not _sha(raw["evidence_sha256"]) or raw["evidence_sha256"] != _canonical_sha256(ev):
        raise ArtifactReadinessError(
            "readiness-evidence-integrity-mismatch", "BOS-RDY-001 evidence digest does not match its payload"
        )
    _verify_evidence_bindings(Path(job_dir), ev)
    return ev
