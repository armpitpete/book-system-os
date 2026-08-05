from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from PIL import Image, UnidentifiedImageError


@dataclass(frozen=True)
class ImageHolder:
    name: str
    min_ratio: float
    max_ratio: float
    target_width_inches: float
    minimum_dpi: int
    crop_allowed: bool
    max_crop_loss_percent: int
    caption_required: bool = False
    decorative_only: bool = False


HOLDERS: Mapping[str, ImageHolder] = {
    "inline": ImageHolder("inline", 0.50, 2.00, 5.5, 200, True, 20),
    "feature": ImageHolder("feature", 1.25, 1.90, 6.25, 250, True, 20, True),
    "portrait": ImageHolder("portrait", 0.55, 0.85, 3.5, 250, True, 15),
    "full-page": ImageHolder("full-page", 0.62, 1.55, 6.25, 300, True, 15, True),
    "ornament": ImageHolder(
        "ornament", 0.25, 4.00, 1.0, 300, False, 0, False, True
    ),
}

ALLOWED_RASTER_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageHolderError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def holder_from_attributes(attributes: Mapping[str, str]) -> ImageHolder | None:
    name = attributes.get("holder") or attributes.get("image-holder")
    if not name:
        return None
    try:
        return HOLDERS[name]
    except KeyError as exc:
        allowed = ", ".join(sorted(HOLDERS))
        raise ImageHolderError(
            f"Unknown image holder '{name}'. Allowed holders: {allowed}",
            code="unknown-image-holder",
        ) from exc


def _crop_loss_percent(source_ratio: float, holder: ImageHolder) -> float:
    if holder.min_ratio <= source_ratio <= holder.max_ratio:
        return 0.0
    target_ratio = holder.min_ratio if source_ratio < holder.min_ratio else holder.max_ratio
    if source_ratio < target_ratio:
        return (1.0 - source_ratio / target_ratio) * 100.0
    return (1.0 - target_ratio / source_ratio) * 100.0


def validate_image_holder(
    path: Path,
    *,
    holder: ImageHolder,
    alt_text: str,
    attributes: Mapping[str, str],
) -> None:
    decorative = attributes.get("decorative", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    caption = attributes.get("caption", "").strip()

    if holder.decorative_only and not decorative:
        raise ImageHolderError(
            "The ornament holder requires decorative=true.",
            code="ornament-not-decorative",
        )
    if not decorative and not alt_text.strip():
        raise ImageHolderError(
            f"Image in holder '{holder.name}' requires alt text.",
            code="missing-image-alt-text",
        )
    if holder.caption_required and not caption:
        raise ImageHolderError(
            f"Image holder '{holder.name}' requires a caption attribute.",
            code="missing-image-caption",
        )

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageHolderError(
            f"Image file cannot be decoded safely: {path.name}",
            code="invalid-image-file",
        ) from exc

    if image_format not in ALLOWED_RASTER_FORMATS:
        allowed = ", ".join(sorted(ALLOWED_RASTER_FORMATS))
        raise ImageHolderError(
            f"Unsupported image format '{image_format or 'unknown'}'. Allowed: {allowed}",
            code="unsupported-image-format",
        )
    if width <= 0 or height <= 0:
        raise ImageHolderError(
            f"Image has invalid pixel dimensions: {path.name}",
            code="invalid-image-dimensions",
        )

    ratio = width / height
    crop_loss = _crop_loss_percent(ratio, holder)
    if crop_loss:
        if not holder.crop_allowed:
            raise ImageHolderError(
                f"Image ratio {ratio:.2f}:1 does not fit holder '{holder.name}'.",
                code="image-ratio-not-allowed",
            )
        if crop_loss > holder.max_crop_loss_percent:
            raise ImageHolderError(
                f"Image ratio {ratio:.2f}:1 would lose {crop_loss:.1f}% when cropped "
                f"for holder '{holder.name}' (maximum {holder.max_crop_loss_percent}%).",
                code="image-crop-loss-too-high",
            )

    effective_dpi = width / holder.target_width_inches
    if effective_dpi < holder.minimum_dpi:
        raise ImageHolderError(
            f"Image provides {effective_dpi:.0f} effective DPI in holder '{holder.name}'; "
            f"minimum is {holder.minimum_dpi} DPI.",
            code="image-resolution-too-low",
        )
