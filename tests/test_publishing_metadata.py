from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pipeline.exporters import _pandoc_command
from app.services.job_queue import create_job
from app.services.publish_plan import PUBLISH_OUTPUTS, build_publish_dry_run
from app.services.publishing_metadata import (
    PublishingMetadataError,
    build_publishing_metadata,
    load_job_publishing_metadata,
)


def test_publishing_metadata_is_canonical_and_bounded() -> None:
    assert build_publishing_metadata(
        title="  A Book  ", language=" en-GB "
    ) == {
        "schema_version": "1",
        "title": "A Book",
        "language": "en-GB",
    }
    assert build_publishing_metadata(title=" ", language="") == {
        "schema_version": "1",
        "title": None,
        "language": None,
    }

    with pytest.raises(PublishingMetadataError) as exc:
        build_publishing_metadata(language="not a language tag!")
    assert exc.value.code == "publishing-language-invalid"

    with pytest.raises(PublishingMetadataError) as exc:
        build_publishing_metadata(title="bad\x00title")
    assert exc.value.code == "publishing-title-invalid"


def test_job_persists_only_explicit_publishing_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    job_id, job_dir = create_job(
        title="  Exact title  ",
        language=" en-GB ",
        markdown="# Book\n",
        state="test",
    )
    assert job_id == job_dir.name
    assert load_job_publishing_metadata(job_dir) == {
        "schema_version": "1",
        "title": "Exact title",
        "language": "en-GB",
    }
    metadata = json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["title"] == "Exact title"
    assert metadata["publishing_metadata"]["language"] == "en-GB"


def test_invalid_publishing_metadata_has_no_job_side_effect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    with pytest.raises(PublishingMetadataError):
        create_job(
            title="Book",
            language="bad language!",
            markdown="# Book\n",
            state="test",
        )
    jobs = tmp_path / "books" / "jobs"
    assert not jobs.exists() or list(jobs.iterdir()) == []


def test_pandoc_command_applies_only_explicit_publishing_metadata() -> None:
    spec = next(output for output in PUBLISH_OUTPUTS if output.key == "epub")
    plain = _pandoc_command(Path("book.md"), spec)
    explicit = _pandoc_command(
        Path("book.md"),
        spec,
        publishing_metadata={
            "schema_version": "1",
            "title": "Exact title",
            "language": "en-GB",
        },
    )
    assert "title=Exact title" not in plain
    assert "lang=en-GB" not in plain
    assert [
        explicit[index + 1]
        for index, argument in enumerate(explicit[:-1])
        if argument == "--metadata"
    ] == ["title=Exact title", "lang=en-GB"]


def test_request_language_satisfies_dry_run_without_changing_source_identity() -> None:
    markdown = "# Book\n\nText.\n"
    result = build_publish_dry_run(
        title="Book", language="en-GB", markdown=markdown
    )
    assert result["publishable"] is True
    assert result["publishing_metadata"] == {
        "schema_version": "1",
        "title": "Book",
        "language": "en-GB",
    }
    assert "language-metadata-missing" not in {
        finding["code"] for finding in result["validation"]["warnings"]
    }
    assert result["validation"]["summary"]["request_language"] == "en-GB"
