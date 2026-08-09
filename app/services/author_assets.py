from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from PIL import Image, UnidentifiedImageError

from app.pipeline.image_holders import (
    ALLOWED_RASTER_FORMATS,
    HOLDERS,
    ImageHolderError,
    validate_image_holder,
)
from app.services.resource_limits import (
    ResourceLimitError,
    max_job_bytes,
    max_total_storage_bytes,
    path_size_bytes,
)
from app.utils.atomic_files import atomic_write_json
from app.utils.paths import author_assets_dir, jobs_dir

ASSET_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ASSET_REFERENCE_RE = re.compile(
    r"assets/([0-9a-f]{32})/(source\.(?:jpg|png|webp))",
    re.IGNORECASE,
)
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class AuthorAssetError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code

    def payload(self) -> dict[str, Any]:
        return {"detail": str(self), "code": self.code}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_upload_name(filename: str | None) -> str:
    value = (filename or "").strip()
    if not value or value in {".", ".."}:
        raise AuthorAssetError(
            "Image filename is required.", code="invalid-asset-filename"
        )
    if "/" in value or "\\" in value or Path(value).name != value:
        raise AuthorAssetError(
            "Image filename must not contain a path.", code="invalid-asset-filename"
        )
    return value


def _inspect_image(path: Path) -> dict[str, Any]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                image_format = (image.format or "").upper()
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise AuthorAssetError(
            "Image exceeds safe pixel limits.", code="image-too-large", status_code=413
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AuthorAssetError(
            "Image file cannot be decoded safely.", code="invalid-image-file"
        ) from exc

    if image_format not in ALLOWED_RASTER_FORMATS:
        allowed = ", ".join(sorted(ALLOWED_RASTER_FORMATS))
        raise AuthorAssetError(
            f"Unsupported image format '{image_format or 'unknown'}'. Allowed: {allowed}",
            code="unsupported-image-format",
        )
    if width <= 0 or height <= 0:
        raise AuthorAssetError(
            "Image has invalid pixel dimensions.", code="invalid-image-dimensions"
        )

    return {
        "format": image_format,
        "width": int(width),
        "height": int(height),
        "aspect_ratio": width / height,
    }


def check_asset_storage_admission(asset_bytes: int) -> None:
    size = int(asset_bytes)
    if size <= 0:
        raise AuthorAssetError("Image upload is empty.", code="empty-image-file")

    per_job_limit = max_job_bytes()
    if size > per_job_limit:
        raise ResourceLimitError(
            "Image is larger than the configured per-job storage limit",
            code="asset-storage-limit-exceeded",
            status_code=413,
            limit=per_job_limit,
            actual=size,
        )

    retained = path_size_bytes(jobs_dir()) + path_size_bytes(author_assets_dir())
    total_limit = max_total_storage_bytes()
    projected = retained + size
    if projected > total_limit:
        raise ResourceLimitError(
            "Retained jobs and author assets cannot admit this image safely",
            code="total-storage-capacity-reached",
            status_code=507,
            limit=total_limit,
            actual=projected,
        )


def store_author_asset(*, filename: str | None, content: bytes) -> dict[str, Any]:
    original_name = _safe_upload_name(filename)
    check_asset_storage_admission(len(content))

    root = author_assets_dir()
    asset_id = uuid.uuid4().hex
    temp_path = root / f".{asset_id}.upload"
    asset_dir = root / asset_id
    temp_path.write_bytes(content)

    try:
        info = _inspect_image(temp_path)
        extension = FORMAT_EXTENSIONS[info["format"]]
        stored_filename = f"source{extension}"
        asset_dir.mkdir(mode=0o700)
        source_path = asset_dir / stored_filename
        os.replace(temp_path, source_path)
        record = {
            "asset_id": asset_id,
            "original_filename": original_name,
            "stored_filename": stored_filename,
            "relative_path": f"assets/{asset_id}/{stored_filename}",
            "uploaded_at": utc_now(),
            "bytes": len(content),
            "sha256": sha256_bytes(content),
            **info,
        }
        atomic_write_json(asset_dir / "metadata.json", record)
        return record
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        if asset_dir.exists():
            shutil.rmtree(asset_dir)
        raise


def _asset_dir(asset_id: str) -> Path:
    if not ASSET_ID_RE.fullmatch(asset_id):
        raise AuthorAssetError("Invalid asset identifier.", code="invalid-asset-id")
    root = author_assets_dir().resolve()
    candidate = root / asset_id
    if candidate.is_symlink() or not candidate.is_dir():
        raise AuthorAssetError(
            "Author asset was not found.", code="asset-not-found", status_code=404
        )
    return candidate


def load_author_asset(asset_id: str, *, verify_hash: bool = False) -> dict[str, Any]:
    directory = _asset_dir(asset_id)
    metadata_path = directory / "metadata.json"
    if metadata_path.is_symlink() or not metadata_path.is_file():
        raise AuthorAssetError(
            "Author asset metadata is unavailable.",
            code="asset-metadata-unavailable",
            status_code=500,
        )
    try:
        record = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorAssetError(
            "Author asset metadata is invalid.",
            code="asset-metadata-invalid",
            status_code=500,
        ) from exc
    if not isinstance(record, dict) or record.get("asset_id") != asset_id:
        raise AuthorAssetError(
            "Author asset metadata does not match its identifier.",
            code="asset-metadata-invalid",
            status_code=500,
        )

    stored_filename = str(record.get("stored_filename", ""))
    if not re.fullmatch(r"source\.(?:jpg|png|webp)", stored_filename):
        raise AuthorAssetError(
            "Author asset stored filename is invalid.",
            code="asset-metadata-invalid",
            status_code=500,
        )
    source_path = directory / stored_filename
    if source_path.is_symlink() or not source_path.is_file():
        raise AuthorAssetError(
            "Author asset image is unavailable.", code="asset-file-unavailable", status_code=500
        )
    if verify_hash and sha256_file(source_path) != str(record.get("sha256", "")):
        raise AuthorAssetError(
            "Author asset content no longer matches its recorded identity.",
            code="asset-integrity-failed",
            status_code=409,
        )
    return record


def author_asset_path(asset_id: str) -> Path:
    record = load_author_asset(asset_id)
    return _asset_dir(asset_id) / str(record["stored_filename"])


def list_author_assets(*, limit: int = 30) -> list[dict[str, Any]]:
    root = author_assets_dir()
    records: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), reverse=True):
        if len(records) >= max(1, int(limit)):
            break
        if path.name.startswith(".") or path.is_symlink() or not path.is_dir():
            continue
        if not ASSET_ID_RE.fullmatch(path.name):
            continue
        try:
            records.append(load_author_asset(path.name))
        except AuthorAssetError:
            continue
    records.sort(key=lambda item: str(item.get("uploaded_at", "")), reverse=True)
    return records[: max(1, int(limit))]


def holder_assessments(asset_id: str) -> list[dict[str, Any]]:
    record = load_author_asset(asset_id)
    path = author_asset_path(asset_id)
    width = int(record["width"])
    ratio = float(record["aspect_ratio"])
    results: list[dict[str, Any]] = []

    for name, holder in HOLDERS.items():
        attributes: dict[str, str] = {}
        if holder.caption_required:
            attributes["caption"] = "Compatibility preview"
        if holder.decorative_only:
            attributes["decorative"] = "true"
        alt_text = "" if holder.decorative_only else "Compatibility preview"
        effective_dpi = width / holder.target_width_inches
        try:
            validate_image_holder(
                path,
                holder=holder,
                alt_text=alt_text,
                attributes=attributes,
            )
        except ImageHolderError as exc:
            compatible = False
            code = exc.code
            explanation = str(exc)
        else:
            compatible = True
            code = "compatible"
            explanation = (
                f"Source ratio {ratio:.2f}:1 fits this holder and provides "
                f"{effective_dpi:.0f} effective DPI (minimum {holder.minimum_dpi})."
            )

        results.append(
            {
                "holder": name,
                "compatible": compatible,
                "code": code,
                "explanation": explanation,
                "target_width_inches": holder.target_width_inches,
                "minimum_dpi": holder.minimum_dpi,
                "effective_dpi": effective_dpi,
                "caption_required": holder.caption_required,
                "decorative_only": holder.decorative_only,
            }
        )
    return results


def holder_semantics(holder_name: str) -> str:
    semantics = {
        "inline": "Stays in ordinary text/block flow at the controlled inline width.",
        "feature": "A standalone feature figure with a required visible caption.",
        "portrait": "A narrow controlled portrait image or figure.",
        "full-page": "A standalone figure with deterministic page breaks before and after; not bleed or cover layout.",
        "ornament": "A decorative separator with presentation-only semantics and no visible caption.",
    }
    try:
        return semantics[holder_name]
    except KeyError as exc:
        raise AuthorAssetError("Unknown image holder.", code="unknown-image-holder") from exc


def _escape_markdown_alt(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ").replace("\r", " ")


def _escape_attribute(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


def canonical_holder_markdown(
    asset_id: str,
    *,
    holder_name: str,
    alt_text: str,
    caption: str = "",
    decorative: bool = False,
) -> str:
    record = load_author_asset(asset_id, verify_hash=True)
    try:
        holder = HOLDERS[holder_name]
    except KeyError as exc:
        raise AuthorAssetError("Unknown image holder.", code="unknown-image-holder") from exc

    attributes: dict[str, str] = {"holder": holder_name}
    if caption.strip():
        attributes["caption"] = caption.strip()
    if decorative:
        attributes["decorative"] = "true"

    path = author_asset_path(asset_id)
    try:
        validate_image_holder(
            path,
            holder=holder,
            alt_text=alt_text,
            attributes=attributes,
        )
    except ImageHolderError as exc:
        raise AuthorAssetError(str(exc), code=exc.code) from exc

    rendered_attributes = [f"holder={holder_name}"]
    if caption.strip():
        rendered_attributes.append(f'caption="{_escape_attribute(caption.strip())}"')
    if decorative:
        rendered_attributes.append("decorative=true")

    safe_alt = _escape_markdown_alt(alt_text.strip())
    target = str(record["relative_path"])
    return f"![{safe_alt}]({target}){{{' '.join(rendered_attributes)}}}"


def referenced_author_assets(markdown: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in ASSET_REFERENCE_RE.finditer(markdown):
        asset_id = match.group(1).lower()
        filename = match.group(2).lower()
        if asset_id in seen:
            continue
        record = load_author_asset(asset_id, verify_hash=True)
        if str(record["stored_filename"]).lower() != filename:
            raise AuthorAssetError(
                "Author asset reference does not match its stored filename.",
                code="asset-reference-mismatch",
            )
        found.append(record)
        seen.add(asset_id)
    return found


def referenced_author_asset_bytes(records: list[dict[str, Any]]) -> int:
    return sum(int(record.get("bytes", 0)) for record in records)


def copy_author_assets_to_input(
    records: list[dict[str, Any]],
    *,
    input_dir: Path,
) -> list[dict[str, Any]]:
    provenance: list[dict[str, Any]] = []
    for record in records:
        asset_id = str(record["asset_id"])
        source = author_asset_path(asset_id)
        destination_dir = input_dir / "assets" / asset_id
        destination_dir.mkdir(parents=True, exist_ok=False)
        destination = destination_dir / str(record["stored_filename"])
        shutil.copy2(source, destination)
        copied_hash = sha256_file(destination)
        if copied_hash != str(record["sha256"]):
            raise AuthorAssetError(
                "Copied author asset failed identity verification.",
                code="asset-copy-integrity-failed",
                status_code=500,
            )
        provenance.append(
            {
                "asset_id": asset_id,
                "relative_path": str(record["relative_path"]),
                "original_filename": str(record["original_filename"]),
                "stored_filename": str(record["stored_filename"]),
                "bytes": int(record["bytes"]),
                "sha256": str(record["sha256"]),
                "width": int(record["width"]),
                "height": int(record["height"]),
                "format": str(record["format"]),
            }
        )
    return provenance
