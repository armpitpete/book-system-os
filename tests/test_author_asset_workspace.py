from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.app import app
from app.services.author_assets import (
    AuthorAssetError,
    canonical_holder_markdown,
    holder_assessments,
    load_author_asset,
    store_author_asset,
)
from app.services.job_queue import create_job
from app.services.resource_limits import ResourceLimitError, new_job_reservation_bytes


@pytest.fixture(autouse=True)
def isolated_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    for name in (
        "BOOK_MAX_REQUEST_BYTES",
        "BOOK_MAX_MANUSCRIPT_BYTES",
        "BOOK_MAX_ACTIVE_JOBS",
        "BOOK_MAX_JOB_BYTES",
        "BOOK_MAX_TOTAL_STORAGE_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)


def image_bytes(*, width: int = 2200, height: int = 1400, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(buffer, format=fmt)
    return buffer.getvalue()


def test_workspace_upload_preview_and_feature_markdown(tmp_path: Path) -> None:
    client = TestClient(app)
    landing = client.get("/assets")
    assert landing.status_code == 200
    assert "Author Asset Workspace" in landing.text
    assert "not a freeform DTP canvas" in landing.text

    response = client.post(
        "/assets",
        files={"image": ("bridge.png", image_bytes(), "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/assets/")
    asset_id = location.rsplit("/", 1)[-1]

    detail = client.get(location)
    assert detail.status_code == 200
    assert "2200 × 1400 px" in detail.text
    for label in ("inline", "feature", "portrait", "full-page", "ornament"):
        assert label in detail.text

    preview = client.get(f"/assets/{asset_id}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")

    configured = client.post(
        f"/assets/{asset_id}/configure",
        data={
            "holder": "feature",
            "alt_text": "A stone bridge",
            "caption": "The eastern bridge after restoration.",
        },
    )
    assert configured.status_code == 200
    assert "Canonical holder Markdown" in configured.text
    assert f"assets/{asset_id}/source.png" in configured.text
    assert "holder=feature" in configured.text
    assert "The eastern bridge after restoration." in configured.text

    record = load_author_asset(asset_id, verify_hash=True)
    assert record["original_filename"] == "bridge.png"
    assert record["width"] == 2200
    assert record["height"] == 1400
    assert record["format"] == "PNG"
    assert (tmp_path / "books" / "assets" / asset_id / "source.png").is_file()


def test_holder_assessment_uses_existing_validator_for_low_resolution() -> None:
    record = store_author_asset(
        filename="small.png",
        content=image_bytes(width=400, height=400),
    )
    assessments = {item["holder"]: item for item in holder_assessments(record["asset_id"])}
    assert assessments["full-page"]["compatible"] is False
    assert assessments["full-page"]["code"] == "image-resolution-too-low"
    assert "effective DPI" in assessments["full-page"]["explanation"]


def test_canonical_markdown_escapes_author_text() -> None:
    record = store_author_asset(
        filename="wide.png",
        content=image_bytes(width=2200, height=1400),
    )
    markup = canonical_holder_markdown(
        record["asset_id"],
        holder_name="feature",
        alt_text="Bridge [east]",
        caption='He said "look here".',
    )
    assert r"Bridge \[east\]" in markup
    assert r'caption="He said \"look here\"."' in markup


def test_ornament_requires_decorative_true() -> None:
    record = store_author_asset(
        filename="ornament.png",
        content=image_bytes(width=900, height=300),
    )
    with pytest.raises(AuthorAssetError) as exc_info:
        canonical_holder_markdown(
            record["asset_id"],
            holder_name="ornament",
            alt_text="",
            decorative=False,
        )
    assert exc_info.value.code == "ornament-not-decorative"

    markup = canonical_holder_markdown(
        record["asset_id"],
        holder_name="ornament",
        alt_text="",
        decorative=True,
    )
    assert "holder=ornament" in markup
    assert "decorative=true" in markup


def test_invalid_upload_and_path_like_filename_fail_closed(tmp_path: Path) -> None:
    client = TestClient(app)
    bad = client.post(
        "/assets",
        files={"image": ("bad.txt", b"not an image", "text/plain")},
    )
    assert bad.status_code == 400
    assert "cannot be decoded safely" in bad.text

    with pytest.raises(AuthorAssetError, match="must not contain a path"):
        store_author_asset(filename="../escape.png", content=image_bytes())

    asset_root = tmp_path / "books" / "assets"
    if asset_root.exists():
        assert not any(path.name == "escape.png" for path in asset_root.rglob("*"))


def test_generated_workspace_reference_is_copied_into_job_with_provenance() -> None:
    record = store_author_asset(
        filename="bridge.png",
        content=image_bytes(width=2200, height=1400),
    )
    markup = canonical_holder_markdown(
        record["asset_id"],
        holder_name="inline",
        alt_text="A stone bridge",
    )
    manuscript = f"# Book\n\n{markup}\n"

    _, job_dir = create_job(title="Asset book", markdown=manuscript, state="test")
    copied = job_dir / "input" / "assets" / record["asset_id"] / "source.png"
    original = job_dir.parents[1] / "assets" / record["asset_id"] / "source.png"
    assert copied.read_bytes() == original.read_bytes()

    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert len(metadata["author_assets"]) == 1
    assert metadata["author_assets"][0]["asset_id"] == record["asset_id"]
    assert metadata["author_assets"][0]["sha256"] == record["sha256"]


def test_job_admission_counts_referenced_workspace_asset_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = store_author_asset(
        filename="bridge.png",
        content=image_bytes(width=2200, height=1400),
    )
    markup = canonical_holder_markdown(
        record["asset_id"],
        holder_name="inline",
        alt_text="A stone bridge",
    )
    manuscript = f"# Book\n\n{markup}\n"
    base_reservation = new_job_reservation_bytes(manuscript)
    monkeypatch.setenv("BOOK_MAX_JOB_BYTES", str(base_reservation))

    with pytest.raises(ResourceLimitError) as exc_info:
        create_job(title="Asset book", markdown=manuscript, state="test")
    assert exc_info.value.code == "job-storage-reservation-exceeded"
    assert exc_info.value.actual == base_reservation + int(record["bytes"])
