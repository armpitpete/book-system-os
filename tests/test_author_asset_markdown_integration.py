from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.input_validation import validate_local_image_files
from app.services.author_assets import canonical_holder_markdown, store_author_asset
from app.services.job_queue import create_job


@pytest.fixture(autouse=True)
def isolated_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")


def image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2400, 1500), (230, 230, 230)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_generated_feature_markdown_round_trips_through_production_parser() -> None:
    asset = store_author_asset(filename="bridge.png", content=image_bytes())
    markup = canonical_holder_markdown(
        asset["asset_id"],
        holder_name="feature",
        alt_text="Bridge [east]",
        caption='He said "look here".',
    )
    manuscript = f"# Book\n\n{markup}\n"

    _, job_dir = create_job(title="Generated holder", markdown=manuscript, state="test")
    validate_local_image_files(manuscript, source_dir=job_dir / "input")
