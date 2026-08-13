from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

SOURCE_IDENTITY_SCHEMA_VERSION = "1"
DERIVATION_MANIFEST_SCHEMA_VERSION = "3"
STRUCTURAL_TRANSFORMATION_ID = "structural-cleanup"
STRUCTURAL_TRANSFORMATION_VERSION = "2"
PROVENANCE_UNAVAILABLE = "provenance_unavailable"


class ProvenanceError(ValueError):
    """Stable coded provenance or retained-source failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _contains_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _validate_assertion_string(value: str) -> str:
    if not value.strip():
        raise ValueError("value must contain non-whitespace characters")
    if _contains_control_characters(value):
        raise ValueError("control characters are not allowed")
    return value


class ControlledSourceRecord(BaseModel):
    """Producer-supplied provenance assertions for one exact Markdown source."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: StrictStr
    canonical_path: StrictStr = Field(min_length=1, max_length=512)
    source_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    source_bytes: StrictInt = Field(ge=0)
    source_commit: StrictStr = Field(min_length=1, max_length=200)
    source_blob: StrictStr | None = Field(default=None, min_length=1, max_length=200)
    control_file_version: StrictStr = Field(min_length=1, max_length=200)
    review_state: StrictStr = Field(min_length=1, max_length=100)
    publication_state: StrictStr = Field(min_length=1, max_length=100)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SOURCE_IDENTITY_SCHEMA_VERSION:
            raise ValueError('schema_version must be exactly "1"')
        return value

    @field_validator("canonical_path")
    @classmethod
    def validate_canonical_path(cls, value: str) -> str:
        if "\\" in value or value.startswith("/"):
            raise ValueError("canonical_path must be a relative POSIX path")
        if _contains_control_characters(value):
            raise ValueError("canonical_path contains a control character")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("canonical_path contains an unsafe path segment")
        return value

    @field_validator(
        "source_commit",
        "source_blob",
        "control_file_version",
        "review_state",
        "publication_state",
    )
    @classmethod
    def validate_assertion_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_assertion_string(value)


class StoredSourceIdentity(BaseModel):
    """Immutable locally verified source identity retained in job metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: StrictStr
    source_bytes: StrictInt = Field(ge=0)
    source_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    controlled: StrictBool
    control_record_sha256: StrictStr | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    control_record: ControlledSourceRecord | None = None

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SOURCE_IDENTITY_SCHEMA_VERSION:
            raise ValueError('schema_version must be exactly "1"')
        return value

    @model_validator(mode="after")
    def validate_controlled_consistency(self) -> "StoredSourceIdentity":
        if self.controlled:
            if self.control_record is None or self.control_record_sha256 is None:
                raise ValueError("controlled source identity requires a control record")
            record = self.control_record.model_dump(mode="json")
            if self.control_record_sha256 != control_record_identity(record):
                raise ValueError("control record identity does not match retained record")
            if self.source_bytes != self.control_record.source_bytes:
                raise ValueError("retained source byte count does not match control record")
            if self.source_sha256 != self.control_record.source_sha256:
                raise ValueError("retained source digest does not match control record")
        elif self.control_record is not None or self.control_record_sha256 is not None:
            raise ValueError("uncontrolled source identity cannot retain a control record")
        return self


def source_identity_bytes(payload: bytes) -> dict[str, int | str]:
    return {
        "source_bytes": len(payload),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
    }


def source_identity_text(markdown: str) -> dict[str, int | str]:
    return source_identity_bytes(markdown.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalise_control_record(
    value: Mapping[str, Any] | ControlledSourceRecord,
) -> dict[str, Any]:
    try:
        if isinstance(value, ControlledSourceRecord):
            model = value
        else:
            model = ControlledSourceRecord.model_validate(value, strict=True)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ProvenanceError(
            "control-record-invalid",
            "Controlled source record is invalid",
        ) from exc
    return model.model_dump(mode="json")


def control_record_identity(record: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_source_identity(
    markdown: str,
    control_record: Mapping[str, Any] | ControlledSourceRecord | None = None,
) -> dict[str, Any]:
    local = source_identity_text(markdown)
    if control_record is None:
        return {
            "schema_version": SOURCE_IDENTITY_SCHEMA_VERSION,
            **local,
            "controlled": False,
            "control_record_sha256": None,
            "control_record": None,
        }

    normalised = normalise_control_record(control_record)
    if normalised["source_bytes"] != local["source_bytes"]:
        raise ProvenanceError(
            "source-bytes-mismatch",
            "Submitted Markdown byte count does not match the controlled source record",
        )
    if normalised["source_sha256"] != local["source_sha256"]:
        raise ProvenanceError(
            "source-sha256-mismatch",
            "Submitted Markdown SHA-256 does not match the controlled source record",
        )

    return {
        "schema_version": SOURCE_IDENTITY_SCHEMA_VERSION,
        **local,
        "controlled": True,
        "control_record_sha256": control_record_identity(normalised),
        "control_record": normalised,
    }


def parse_stored_source_identity(value: Any) -> StoredSourceIdentity:
    try:
        return StoredSourceIdentity.model_validate(value, strict=True)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ProvenanceError(
            "source-identity-invalid",
            "Retained source identity is invalid",
        ) from exc


def inspect_job_provenance(job_dir: Path) -> dict[str, Any]:
    metadata_path = Path(job_dir) / "metadata.json"
    if not metadata_path.is_file():
        return {"state": PROVENANCE_UNAVAILABLE}

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError(
            "source-identity-invalid",
            "Job metadata is unavailable or invalid",
        ) from exc
    if not isinstance(metadata, dict):
        raise ProvenanceError(
            "source-identity-invalid",
            "Job metadata is not a JSON object",
        )

    if "source_identity" not in metadata:
        return {"state": PROVENANCE_UNAVAILABLE}

    identity = parse_stored_source_identity(metadata["source_identity"])
    return {
        "state": "available",
        "source_identity": identity.model_dump(mode="json"),
    }


def verify_job_source(job_dir: Path) -> dict[str, Any]:
    provenance = inspect_job_provenance(job_dir)
    if provenance["state"] == PROVENANCE_UNAVAILABLE:
        return provenance

    input_path = Path(job_dir) / "input" / "book.md"
    if not input_path.is_file():
        raise ProvenanceError(
            "source-input-missing",
            "Retained source input/book.md is missing",
        )

    payload = input_path.read_bytes()
    actual = source_identity_bytes(payload)
    expected = provenance["source_identity"]
    if actual["source_bytes"] != expected["source_bytes"]:
        raise ProvenanceError(
            "source-bytes-mismatch",
            "Retained source byte count differs from immutable job metadata",
        )
    if actual["source_sha256"] != expected["source_sha256"]:
        raise ProvenanceError(
            "source-sha256-mismatch",
            "Retained source SHA-256 differs from immutable job metadata",
        )
    return provenance


_STALENESS_FIELDS: tuple[tuple[str, str], ...] = (
    ("canonical_path", "canonical-path-changed"),
    ("source_commit", "source-commit-changed"),
    ("source_blob", "source-blob-changed"),
    ("control_file_version", "control-file-version-changed"),
    ("review_state", "review-state-changed"),
    ("publication_state", "publication-state-changed"),
    ("source_bytes", "source-bytes-changed"),
    ("source_sha256", "source-sha256-changed"),
)


def assess_manifest_staleness(
    manifest: Mapping[str, Any],
    current_control_record: Mapping[str, Any] | ControlledSourceRecord,
) -> dict[str, Any]:
    """Compare supplied current authority with retained evidence only."""

    current = normalise_control_record(current_control_record)
    retained_raw = manifest.get("source_identity")
    if retained_raw is None:
        return {"current": False, "reasons": ["provenance-unavailable"]}

    retained = parse_stored_source_identity(retained_raw)
    if not retained.controlled or retained.control_record is None:
        return {"current": False, "reasons": ["provenance-unavailable"]}

    previous = retained.control_record.model_dump(mode="json")
    reasons = [
        reason
        for field, reason in _STALENESS_FIELDS
        if previous.get(field) != current.get(field)
    ]
    return {"current": not reasons, "reasons": reasons}
