from __future__ import annotations

import html
import json
import shutil
import zipfile
from pathlib import Path

import pytest

import app.pipeline.run_pipeline as pipeline_module
from app.services.publish_plan import PUBLISH_OUTPUTS


# Corpus case #87: format-native metadata preservation and deterministic rejection.
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "h08" / "unusual-metadata.md"
EXPECTED_OUTPUTS = {output.filename for output in PUBLISH_OUTPUTS}
TITLE = "Café ‘North’ — Αθήνα"
AUTHOR = "Zoë O'Connor"
SUBJECT = "A folded subject about naïve metadata, coöperation, and Αθήνα."
KEYWORDS = ("façade", "résumé", "Αθήνα")
SOURCE_SENTINELS = (TITLE, AUTHOR, "naïve metadata", "coöperation", *KEYWORDS)
BODY_SENTINEL = "BODY-METADATA-UTF8-OK"


def require_export_toolchain() -> None:
    if shutil.which("pandoc") is None or shutil.which("xelatex") is None:
        pytest.skip("pandoc and xelatex are required for the metadata export test")


def prepare_job(tmp_path: Path, manuscript: bytes, name: str) -> Path:
    job_dir = tmp_path / name
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    (job_dir / "input" / "book.md").write_bytes(manuscript)
    return job_dir


def assert_pdf(path: Path) -> None:
    data = path.read_bytes()
    assert len(data) > 1000
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-4096:]


def archive_member_text(path: Path, predicate) -> str:
    with zipfile.ZipFile(path) as archive:
        members = [
            archive.read(name).decode("utf-8", errors="strict")
            for name in archive.namelist()
            if predicate(name)
        ]
    assert members
    return html.unescape("\n".join(members))


def semantic_text(value: str) -> str:
    return " ".join(
        html.unescape(value)
        .replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .split()
    )


@pytest.mark.integration
def test_unusual_utf8_metadata_survives_all_four_exports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_export_toolchain()
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    manuscript = FIXTURE.read_bytes()
    decoded = manuscript.decode("utf-8")
    for sentinel in (*SOURCE_SENTINELS, BODY_SENTINEL):
        assert sentinel in decoded

    job_dir = prepare_job(tmp_path, manuscript, "h08-unusual-metadata")
    result = pipeline_module.run_pipeline(job_dir)
    assert result == 0, (job_dir / "logs" / "error.log").read_text(
        encoding="utf-8", errors="replace"
    ) if (job_dir / "logs" / "error.log").is_file() else "No error log"

    outputs = {path.name for path in (job_dir / "output").iterdir() if path.is_file()}
    assert outputs == EXPECTED_OUTPUTS
    assert_pdf(job_dir / "output" / "book-standard.pdf")
    assert_pdf(job_dir / "output" / "book-nd.pdf")

    cleaned = (job_dir / "work" / "book-clean.md").read_text(encoding="utf-8")
    for sentinel in (*SOURCE_SENTINELS, BODY_SENTINEL):
        assert sentinel in cleaned

    epub_metadata = semantic_text(
        archive_member_text(
            job_dir / "output" / "book.epub",
            lambda name: name.lower().endswith(".opf"),
        )
    )
    docx_metadata = semantic_text(
        archive_member_text(
            job_dir / "output" / "book.docx",
            lambda name: name.lower() == "docprops/core.xml",
        )
    )

    # EPUB OPF natively carries title, creator, language and subject. Pandoc does
    # not map the separate Markdown keywords field into OPF package metadata.
    for sentinel in (TITLE, AUTHOR, SUBJECT, "en-GB"):
        assert semantic_text(sentinel) in epub_metadata

    # DOCX core properties additionally expose the source keywords field.
    for sentinel in (TITLE, AUTHOR, SUBJECT, "en-GB", *KEYWORDS):
        assert semantic_text(sentinel) in docx_metadata

    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    assert status["status"] == "done"
    assert manifest["status"]["status"] == "done"


def test_invalid_utf8_bytes_fail_before_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    invalid = b"---\ntitle: Invalid metadata \xff\n---\n\n# Body\n"
    job_dir = prepare_job(tmp_path, invalid, "h08-invalid-utf8")

    result = pipeline_module.run_pipeline(job_dir)
    assert result == 1

    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["step"] == "error"
    assert "utf-8" in status["message"].lower()
    assert not any((job_dir / "output").iterdir())
    assert not (job_dir / "manifest.json").exists()

    error_log = (job_dir / "logs" / "error.log").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "UnicodeDecodeError" in error_log
    assert "pandoc" not in error_log.lower()
