from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.image_holders import (
    HOLDERS,
    ImageHolderError,
    holder_from_attributes,
    validate_image_holder,
)


def make_image(path: Path, size: tuple[int, int]) -> None:
    Image.new("RGB", size, "white").save(path, format="PNG")


def test_known_holder_is_resolved() -> None:
    assert holder_from_attributes({"holder": "feature"}) == HOLDERS["feature"]


def test_unknown_holder_is_rejected() -> None:
    with pytest.raises(ImageHolderError, match="Unknown image holder") as exc:
        holder_from_attributes({"holder": "floating-chaos"})
    assert exc.value.code == "unknown-image-holder"


def test_feature_requires_caption(tmp_path: Path) -> None:
    image = tmp_path / "feature.png"
    make_image(image, (2400, 1600))
    with pytest.raises(ImageHolderError) as exc:
        validate_image_holder(image, holder=HOLDERS["feature"], alt_text="A useful photograph", attributes={})
    assert exc.value.code == "missing-image-caption"


def test_portrait_rejects_excessive_crop(tmp_path: Path) -> None:
    image = tmp_path / "wide.png"
    make_image(image, (2400, 800))
    with pytest.raises(ImageHolderError) as exc:
        validate_image_holder(image, holder=HOLDERS["portrait"], alt_text="A wide photograph", attributes={})
    assert exc.value.code == "image-crop-loss-too-high"


def test_low_resolution_is_rejected(tmp_path: Path) -> None:
    image = tmp_path / "small.png"
    make_image(image, (600, 400))
    with pytest.raises(ImageHolderError) as exc:
        validate_image_holder(image, holder=HOLDERS["inline"], alt_text="A small photograph", attributes={})
    assert exc.value.code == "image-resolution-too-low"


def test_ornament_must_be_decorative(tmp_path: Path) -> None:
    image = tmp_path / "ornament.png"
    make_image(image, (1200, 1200))
    with pytest.raises(ImageHolderError) as exc:
        validate_image_holder(image, holder=HOLDERS["ornament"], alt_text="", attributes={})
    assert exc.value.code == "ornament-not-decorative"


def test_valid_feature_passes(tmp_path: Path) -> None:
    image = tmp_path / "feature.png"
    make_image(image, (2400, 1600))
    validate_image_holder(
        image,
        holder=HOLDERS["feature"],
        alt_text="A useful photograph",
        attributes={"caption": "The useful photograph."},
    )
