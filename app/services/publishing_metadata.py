from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "1"
_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


class PublishingMetadataError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _clean_text(value: str | None, *, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise PublishingMetadataError(
            f"publishing-{field}-invalid", f"Publishing {field} is too long"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise PublishingMetadataError(
            f"publishing-{field}-invalid",
            f"Publishing {field} contains a control character",
        )
    return cleaned


def build_publishing_metadata(
    *,
    title: str | None = None,
    language: str | None = None,
) -> dict[str, str | None]:
    clean_title = _clean_text(title, field="title", max_length=200)
    clean_language = _clean_text(language, field="language", max_length=35)
    if clean_language is not None and _LANGUAGE_TAG_RE.fullmatch(clean_language) is None:
        raise PublishingMetadataError(
            "publishing-language-invalid",
            "Publishing language must be a simple language tag such as en-GB",
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "title": clean_title,
        "language": clean_language,
    }


def parse_publishing_metadata(value: Any) -> dict[str, str | None]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "title",
        "language",
    }:
        raise PublishingMetadataError(
            "publishing-metadata-invalid", "Publishing metadata is invalid"
        )
    if value.get("schema_version") != SCHEMA_VERSION:
        raise PublishingMetadataError(
            "publishing-metadata-invalid", "Publishing metadata schema is unsupported"
        )
    parsed = build_publishing_metadata(
        title=value.get("title"), language=value.get("language")
    )
    if parsed != dict(value):
        raise PublishingMetadataError(
            "publishing-metadata-invalid", "Publishing metadata is not canonical"
        )
    return parsed


def empty_publishing_metadata() -> dict[str, str | None]:
    return build_publishing_metadata()


def load_job_publishing_metadata(job_dir: Path) -> dict[str, str | None]:
    metadata_path = Path(job_dir) / "metadata.json"
    if not metadata_path.exists():
        return empty_publishing_metadata()
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishingMetadataError(
            "publishing-metadata-invalid", "Job metadata is unavailable or invalid"
        ) from exc
    if not isinstance(raw, dict):
        raise PublishingMetadataError(
            "publishing-metadata-invalid", "Job metadata is not a JSON object"
        )
    if "publishing_metadata" not in raw:
        return empty_publishing_metadata()
    return parse_publishing_metadata(raw["publishing_metadata"])
