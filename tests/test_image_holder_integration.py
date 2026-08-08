from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.input_validation import (
    ManuscriptInputError,
    _image_parts,
    _image_target,
    _parse_document,
    _walk_nodes,
    validate_local_image_files,
)
from app.services.artifact_readiness import _assets_sha256


def require_pandoc() -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is required for image-holder integration validation")


def make_image(path: Path, *, colour: str = "white") -> None:
    Image.new("RGB", (2400, 1600), colour).save(path, format="PNG")


def test_holder_validation_is_applied_through_manuscript_input(tmp_path: Path) -> None:
    require_pandoc()
    image = tmp_path / "feature.png"
    make_image(image)

    with pytest.raises(ManuscriptInputError) as exc:
        validate_local_image_files(
            "# Book\n\n![A useful photograph](feature.png){holder=feature}\n",
            source_dir=tmp_path,
        )

    assert exc.value.code == "missing-image-caption"


def test_unknown_holder_fails_through_manuscript_input(tmp_path: Path) -> None:
    require_pandoc()
    image = tmp_path / "feature.png"
    make_image(image)

    with pytest.raises(ManuscriptInputError) as exc:
        validate_local_image_files(
            "# Book\n\n![A useful photograph](feature.png){holder=unknown}\n",
            source_dir=tmp_path,
        )

    assert exc.value.code == "unknown-image-holder"


def test_plain_existing_image_keeps_existence_only_compatibility(tmp_path: Path) -> None:
    require_pandoc()
    image = tmp_path / "legacy.png"
    image.write_bytes(b"legacy source is not decoded without a holder")

    validate_local_image_files(
        "# Book\n\n![Legacy image](legacy.png)\n",
        source_dir=tmp_path,
    )


def test_image_target_helper_still_discovers_holder_image() -> None:
    require_pandoc()
    document = _parse_document(
        '# Book\n\n![A bridge](assets/bridge.png){holder=feature caption="Bridge"}\n'
    )
    images = [node for node in _walk_nodes(document["blocks"]) if node.get("t") == "Image"]

    assert len(images) == 1
    assert _image_target(images[0]) == "assets/bridge.png"
    assert _image_parts(images[0]) == (
        "assets/bridge.png",
        "A bridge",
        {"holder": "feature", "caption": "Bridge"},
    )


def test_bos_readiness_asset_hash_tracks_external_holder_image_bytes(tmp_path: Path) -> None:
    require_pandoc()
    job_dir = tmp_path / "job"
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True)
    external_image = tmp_path / "external.png"
    make_image(external_image, colour="white")
    (input_dir / "book.md").write_text(
        '# Book\n\n![External feature](../../external.png){holder=feature caption="Feature"}\n',
        encoding="utf-8",
    )

    before = _assets_sha256(job_dir)
    make_image(external_image, colour="black")
    after = _assets_sha256(job_dir)

    assert before != after
