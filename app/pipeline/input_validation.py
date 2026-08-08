from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit

from app.pipeline.image_holders import (
    ImageHolderError,
    holder_from_attributes,
    validate_image_holder,
)
from app.services.resource_limits import export_command_timeout_seconds


class ManuscriptInputError(RuntimeError):
    """A deterministic manuscript-input failure found before export."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _walk_nodes(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("t"), str):
            yield value
        for child in value.values():
            yield from _walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_nodes(child)


def _inline_text(value: object) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        if value.get("t") == "Str" and isinstance(value.get("c"), str):
            parts.append(value["c"])
        elif value.get("t") in {"Space", "SoftBreak", "LineBreak"}:
            parts.append(" ")
        else:
            for child in value.values():
                parts.append(_inline_text(child))
    elif isinstance(value, list):
        for child in value:
            parts.append(_inline_text(child))
    return "".join(parts).strip()


def _image_parts(node: dict[str, Any]) -> tuple[str, str, dict[str, str]] | None:
    if node.get("t") != "Image":
        return None
    content = node.get("c")
    if not isinstance(content, list) or len(content) < 3:
        return None

    attr = content[0]
    alt = content[1]
    target = content[2]
    if not isinstance(target, list) or not target or not isinstance(target[0], str):
        return None

    attributes: dict[str, str] = {}
    if isinstance(attr, list) and len(attr) >= 3 and isinstance(attr[2], list):
        for pair in attr[2]:
            if (
                isinstance(pair, list)
                and len(pair) == 2
                and isinstance(pair[0], str)
                and isinstance(pair[1], str)
            ):
                attributes[pair[0]] = pair[1]

    return target[0], _inline_text(alt), attributes


def _image_target(node: dict[str, Any]) -> str | None:
    """Return an image target while preserving the BOS-RDY-001 helper contract."""

    parts = _image_parts(node)
    return parts[0] if parts is not None else None


def _parse_document(markdown: str) -> dict[str, Any]:
    command = [
        "pandoc",
        "--sandbox",
        "--from=markdown+yaml_metadata_block+link_attributes",
        "--to=json",
    ]
    try:
        completed = subprocess.run(
            command,
            input=markdown,
            capture_output=True,
            text=True,
            timeout=min(export_command_timeout_seconds(), 30.0),
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Pandoc is unavailable for manuscript input validation") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Manuscript input validation exceeded the bounded runtime") from exc
    except OSError as exc:
        raise RuntimeError("Manuscript input validation could not start") from exc

    if completed.returncode != 0:
        raise RuntimeError("Pandoc could not inspect manuscript image references")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Pandoc returned unreadable image-reference data") from exc
    if not isinstance(document, dict):
        raise RuntimeError("Pandoc returned invalid image-reference data")
    return document


def _local_image_path(target: str, source_dir: Path) -> Path | None:
    parsed = urlsplit(target)
    scheme = parsed.scheme.lower()
    if scheme in {"data", "http", "https"}:
        return None
    if scheme and scheme != "file":
        return None

    raw_path = parsed.path if scheme == "file" else target
    candidate = Path(unquote(raw_path))
    if not candidate.is_absolute():
        candidate = source_dir / candidate
    return candidate.resolve(strict=False)


def validate_local_image_files(markdown: str, *, source_dir: Path) -> None:
    """Reject invalid local Markdown images before export.

    Plain Markdown images retain the existing compatibility behaviour and are
    checked for existence only. Images with a ``holder`` or ``image-holder``
    attribute opt into the controlled-holder contract and must therefore resolve
    to a local file that can receive deterministic geometry, format,
    accessibility and print-resolution validation.

    Data images and non-local URL targets without a holder are not fetched by
    this validator.
    """

    if "![" not in markdown:
        return

    document = _parse_document(markdown)
    blocks = document.get("blocks")
    if not isinstance(blocks, list):
        raise RuntimeError("Pandoc returned an invalid manuscript document")

    for node in _walk_nodes(blocks):
        parts = _image_parts(node)
        if parts is None:
            continue
        target, alt_text, attributes = parts

        try:
            holder = holder_from_attributes(attributes)
        except ImageHolderError as exc:
            raise ManuscriptInputError(str(exc), code=exc.code) from exc

        path = _local_image_path(target, source_dir)
        if path is None:
            if holder is not None:
                raise ManuscriptInputError(
                    f"Image holder '{holder.name}' requires a local image file: {target}",
                    code="image-holder-requires-local-file",
                )
            continue
        if not path.is_file():
            raise ManuscriptInputError(
                f"Referenced local image file is missing: {target}",
                code="missing-image-file",
            )

        if holder is None:
            continue
        try:
            validate_image_holder(
                path,
                holder=holder,
                alt_text=alt_text,
                attributes=attributes,
            )
        except ImageHolderError as exc:
            raise ManuscriptInputError(str(exc), code=exc.code) from exc
