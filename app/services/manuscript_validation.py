from __future__ import annotations

import json
import subprocess
from typing import Any, Iterator

from app.pipeline.structural import structural_cleanup
from app.services.resource_limits import (
    ResourceLimitError,
    export_command_timeout_seconds,
    max_manuscript_bytes,
)

CONTRACT_VERSION = "0.2"
MAX_VALIDATION_SECONDS = 30.0


class ValidationServiceError(RuntimeError):
    """Controlled failure when manuscript validation cannot be performed."""

    def __init__(self, message: str, *, code: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code

    def payload(self) -> dict[str, object]:
        return {"detail": str(self), "code": self.code}


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    location: dict[str, int] | None = None,
) -> dict[str, object]:
    finding: dict[str, object] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if location is not None:
        finding["location"] = location
    return finding


def _walk_nodes(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("t"), str):
            yield value
        for child in value.values():
            yield from _walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_nodes(child)


def _header_level(node: dict[str, Any]) -> int | None:
    content = node.get("c")
    if not isinstance(content, list) or not content:
        return None
    level = content[0]
    return level if isinstance(level, int) else None


def _raw_format(node: dict[str, Any]) -> str | None:
    content = node.get("c")
    if not isinstance(content, list) or not content:
        return None
    value = content[0]
    return value if isinstance(value, str) else None


def _analyse_document(
    document: dict[str, Any],
    *,
    request_title: str,
    source_bytes: int,
    normalised_bytes: int,
    normalisation_changed: bool,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    warnings: list[dict[str, object]] = []
    metadata = document.get("meta")
    if not isinstance(metadata, dict):
        metadata = {}
    blocks = document.get("blocks")
    if not isinstance(blocks, list):
        raise ValidationServiceError(
            "Pandoc returned an invalid document structure",
            code="validation-tool-invalid-response",
        )

    nodes = list(_walk_nodes(blocks))
    heading_levels = [
        level
        for node in nodes
        if node.get("t") == "Header"
        for level in [_header_level(node)]
        if level is not None
    ]
    heading_jumps = sum(
        1
        for previous, current in zip(heading_levels, heading_levels[1:])
        if current > previous + 1
    )
    raw_formats = [
        raw_format
        for node in nodes
        if node.get("t") in {"RawBlock", "RawInline"}
        for raw_format in [_raw_format(node)]
        if raw_format is not None
    ]

    if not heading_levels:
        warnings.append(
            _finding(
                "no-headings",
                "warning",
                "The manuscript has no Markdown headings.",
            )
        )
    elif heading_levels[0] > 1:
        warnings.append(
            _finding(
                "starts-below-level-one",
                "warning",
                "The first manuscript heading is below level one.",
                location={"heading_index": 1},
            )
        )

    if heading_jumps:
        warnings.append(
            _finding(
                "heading-level-jump",
                "warning",
                f"The manuscript contains {heading_jumps} heading-level jump(s).",
            )
        )

    if raw_formats:
        warnings.append(
            _finding(
                "raw-format-content",
                "warning",
                "The manuscript contains raw format-specific content that may not appear in every output format.",
            )
        )

    if "title" not in metadata and request_title.strip() in {"", "Untitled"}:
        warnings.append(
            _finding(
                "title-metadata-missing",
                "warning",
                "No explicit manuscript title was supplied in metadata or the request.",
            )
        )

    if "lang" not in metadata:
        warnings.append(
            _finding(
                "language-metadata-missing",
                "warning",
                "The manuscript metadata does not declare a language.",
            )
        )

    summary: dict[str, object] = {
        "request_title": request_title.strip() or "Untitled",
        "source_bytes": source_bytes,
        "normalised_bytes": normalised_bytes,
        "normalisation_changed": normalisation_changed,
        "metadata_fields": sorted(str(key) for key in metadata),
        "block_count": len(blocks),
        "heading_count": len(heading_levels),
        "level_one_heading_count": sum(level == 1 for level in heading_levels),
        "maximum_heading_level": max(heading_levels, default=0),
        "image_count": sum(node.get("t") == "Image" for node in nodes),
        "table_count": sum(node.get("t") == "Table" for node in nodes),
        "footnote_count": sum(node.get("t") == "Note" for node in nodes),
        "list_count": sum(
            node.get("t") in {"BulletList", "OrderedList"} for node in nodes
        ),
        "raw_content_count": len(raw_formats),
    }
    return warnings, summary


def _parse_with_pandoc(markdown: str) -> tuple[dict[str, Any] | None, bool]:
    timeout = min(export_command_timeout_seconds(), MAX_VALIDATION_SECONDS)
    command = [
        "pandoc",
        "--sandbox",
        "--from=markdown+yaml_metadata_block",
        "--to=json",
    ]
    try:
        completed = subprocess.run(
            command,
            input=markdown,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValidationServiceError(
            "Pandoc is unavailable for manuscript validation",
            code="validation-tool-unavailable",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationServiceError(
            "Manuscript validation exceeded the bounded runtime",
            code="validation-timeout",
        ) from exc
    except OSError as exc:
        raise ValidationServiceError(
            "Manuscript validation could not start",
            code="validation-tool-unavailable",
        ) from exc

    if completed.returncode != 0:
        return None, False

    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationServiceError(
            "Pandoc returned unreadable validation data",
            code="validation-tool-invalid-response",
        ) from exc
    if not isinstance(document, dict):
        raise ValidationServiceError(
            "Pandoc returned an invalid validation document",
            code="validation-tool-invalid-response",
        )
    return document, bool(completed.stderr.strip())


def validate_manuscript(*, title: str, markdown: str) -> dict[str, object]:
    source_bytes = len(markdown.encode("utf-8"))
    manuscript_limit = max_manuscript_bytes()
    if source_bytes > manuscript_limit:
        raise ResourceLimitError(
            "Markdown manuscript exceeds the configured size limit",
            code="manuscript-too-large",
            status_code=413,
            limit=manuscript_limit,
            actual=source_bytes,
        )

    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []

    if not markdown.strip():
        errors.append(
            _finding(
                "empty-manuscript",
                "error",
                "The manuscript contains no non-whitespace text.",
            )
        )
        return {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "request_title": title.strip() or "Untitled",
                "source_bytes": source_bytes,
                "normalised_bytes": 0,
                "normalisation_changed": bool(markdown),
                "metadata_fields": [],
                "block_count": 0,
                "heading_count": 0,
                "level_one_heading_count": 0,
                "maximum_heading_level": 0,
                "image_count": 0,
                "table_count": 0,
                "footnote_count": 0,
                "list_count": 0,
                "raw_content_count": 0,
            },
            "contract_version": CONTRACT_VERSION,
        }

    cleaned = structural_cleanup(markdown)
    document, parser_warning = _parse_with_pandoc(cleaned)
    if document is None:
        errors.append(
            _finding(
                "manuscript-parse-error",
                "error",
                "Pandoc could not parse the manuscript metadata or Markdown.",
            )
        )
        summary = {
            "request_title": title.strip() or "Untitled",
            "source_bytes": source_bytes,
            "normalised_bytes": len(cleaned.encode("utf-8")),
            "normalisation_changed": cleaned != markdown,
            "metadata_fields": [],
            "block_count": 0,
            "heading_count": 0,
            "level_one_heading_count": 0,
            "maximum_heading_level": 0,
            "image_count": 0,
            "table_count": 0,
            "footnote_count": 0,
            "list_count": 0,
            "raw_content_count": 0,
        }
    else:
        analysed_warnings, summary = _analyse_document(
            document,
            request_title=title,
            source_bytes=source_bytes,
            normalised_bytes=len(cleaned.encode("utf-8")),
            normalisation_changed=cleaned != markdown,
        )
        warnings.extend(analysed_warnings)

    if parser_warning:
        warnings.append(
            _finding(
                "pandoc-parser-warning",
                "warning",
                "Pandoc reported a non-fatal parser warning.",
            )
        )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "contract_version": CONTRACT_VERSION,
    }
