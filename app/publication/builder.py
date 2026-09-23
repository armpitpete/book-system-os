from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from app.publication.feasibility import (
    FeasibilityResult,
    FeasibilityStatus,
    assess_feasibility,
)
from app.publication.markdown_contract import MarkdownFinding, inspect_markdown
from app.publication.model import (
    Asset,
    BookPublication,
    ContentUnit,
    PublicationIntent,
    PublicationMetadata,
    PublicationType,
)


@dataclass(frozen=True)
class PublicationFinding:
    code: str
    severity: str
    message: str
    location: str | None = None


@dataclass(frozen=True)
class PublicationAssessment:
    publication: BookPublication | None
    findings: tuple[PublicationFinding, ...]
    feasibility: FeasibilityResult | None

    @property
    def accepted(self) -> bool:
        return (
            self.publication is not None
            and not any(item.severity == "error" for item in self.findings)
            and self.feasibility is not None
            and self.feasibility.status != FeasibilityStatus.REJECT
        )


class PublicationRejected(ValueError):
    def __init__(self, assessment: PublicationAssessment) -> None:
        super().__init__("Publication input did not pass Publication Model v0.1 validation")
        self.assessment = assessment


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _finding_from_markdown(
    finding: MarkdownFinding,
    *,
    unit_id: str,
) -> PublicationFinding:
    location = f"content_units.{unit_id}"
    if finding.line is not None:
        location += f":{finding.line}"
    return PublicationFinding(
        code=finding.code,
        severity=finding.severity,
        message=finding.message,
        location=location,
    )


def _validation_error_code(error: Mapping[str, Any]) -> str:
    message = str(error.get("msg", "publication-schema-invalid"))
    if "Value error, " in message:
        return message.split("Value error, ", 1)[1].split(":", 1)[0]
    return "publication-schema-invalid"


def _safe_asset_path(root: Path, source_path: str) -> Path | None:
    root_resolved = root.resolve()
    try:
        candidate = (root_resolved / source_path).resolve()
        candidate.relative_to(root_resolved)
    except (OSError, ValueError):
        return None
    return candidate


def assess_book(
    *,
    publication_id: str,
    metadata: Mapping[str, Any],
    content_units: Sequence[Mapping[str, Any]],
    assets: Sequence[Mapping[str, Any]] = (),
    intent: Mapping[str, Any],
    asset_root: Path | None = None,
) -> PublicationAssessment:
    findings: list[PublicationFinding] = []
    prepared_units: list[dict[str, Any]] = []

    for raw_unit in content_units:
        unit_id = str(raw_unit.get("id", "<unknown>"))
        markdown = raw_unit.get("markdown", "")
        if not isinstance(markdown, str):
            findings.append(
                PublicationFinding(
                    "markdown-not-text",
                    "error",
                    "Content-unit Markdown must be text.",
                    f"content_units.{unit_id}",
                )
            )
            markdown = ""

        inspection = inspect_markdown(markdown)
        findings.extend(
            _finding_from_markdown(item, unit_id=unit_id)
            for item in inspection.findings
        )
        source_path = str(raw_unit.get("source_path", f"{unit_id}.md"))
        prepared_units.append(
            {
                "id": raw_unit.get("id"),
                "role": raw_unit.get("role"),
                "matter": raw_unit.get("matter"),
                "title": raw_unit.get("title"),
                "parent_id": raw_unit.get("parent_id"),
                "markdown": inspection.canonical_markdown,
                "provenance": {
                    "source_path": source_path,
                    "source_sha256": _sha256(markdown),
                    "canonical_sha256": _sha256(inspection.canonical_markdown),
                    "line_start": raw_unit.get("line_start"),
                    "line_end": raw_unit.get("line_end"),
                },
                "asset_ids": inspection.inspection.asset_ids,
            }
        )

    prepared_assets: list[Asset] = []
    for raw_asset in assets:
        asset_id = str(raw_asset.get("id", "<unknown>"))
        try:
            asset = Asset.model_validate(raw_asset)
        except ValidationError as exc:
            for error in exc.errors():
                findings.append(
                    PublicationFinding(
                        _validation_error_code(error),
                        "error",
                        str(error.get("msg", "Asset metadata is invalid.")),
                        f"assets.{asset_id}",
                    )
                )
            continue

        if asset_root is not None:
            path = _safe_asset_path(asset_root, asset.source_path)
            if path is None:
                findings.append(
                    PublicationFinding(
                        "asset-path-outside-root",
                        "error",
                        "Asset path must remain inside the declared asset root.",
                        f"assets.{asset.id}",
                    )
                )
            elif not path.is_file():
                findings.append(
                    PublicationFinding(
                        "asset-file-missing",
                        "error",
                        "Declared asset file does not exist.",
                        f"assets.{asset.id}",
                    )
                )
        prepared_assets.append(asset)

    publication: BookPublication | None = None
    try:
        publication = BookPublication(
            id=publication_id,
            publication_type=PublicationType.BOOK,
            metadata=PublicationMetadata.model_validate(metadata),
            content_units=tuple(
                ContentUnit.model_validate(item) for item in prepared_units
            ),
            assets=tuple(prepared_assets),
            intent=PublicationIntent.model_validate(intent),
        )
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(item) for item in error.get("loc", ())) or None
            findings.append(
                PublicationFinding(
                    _validation_error_code(error),
                    "error",
                    str(error.get("msg", "Publication schema is invalid.")),
                    location,
                )
            )

    feasibility: FeasibilityResult | None = None
    if publication is not None:
        feasibility = assess_feasibility(publication)
        findings.extend(
            PublicationFinding(
                code=item.code,
                severity="error" if item.level == "reject" else item.level,
                message=item.message,
                location="intent",
            )
            for item in feasibility.findings
        )

    return PublicationAssessment(
        publication=publication,
        findings=tuple(findings),
        feasibility=feasibility,
    )


def build_book_or_raise(**kwargs: Any) -> BookPublication:
    assessment = assess_book(**kwargs)
    if not assessment.accepted or assessment.publication is None:
        raise PublicationRejected(assessment)
    return assessment.publication
