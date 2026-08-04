from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit

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


def _image_target(node: dict[str, Any]) -> str | None:
    if node.get("t") != "Image":
        return None
    content = node.get("c")
    if not isinstance(content, list) or len(content) < 3:
        return None
    target = content[2]
    if not isinstance(target, list) or not target:
        return None
    value = target[0]
    return value if isinstance(value, str) and value else None


def _parse_document(markdown: str) -> dict[str, Any]:
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
    """Reject missing local Markdown image files before export.

    Pandoc's AST is used so inline and reference-style Markdown images share one
    interpretation. Data images and HTTP(S) targets are outside this local-file
    case and are not fetched.
    """

    if "![" not in markdown:
        return

    document = _parse_document(markdown)
    blocks = document.get("blocks")
    if not isinstance(blocks, list):
        raise RuntimeError("Pandoc returned an invalid manuscript document")

    for node in _walk_nodes(blocks):
        target = _image_target(node)
        if target is None:
            continue
        path = _local_image_path(target, source_dir)
        if path is None:
            continue
        if not path.is_file():
            raise ManuscriptInputError(
                f"Referenced local image file is missing: {target}",
                code="missing-image-file",
            )
