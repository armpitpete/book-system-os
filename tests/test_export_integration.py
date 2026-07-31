from __future__ import annotations

import json
import os
import shutil
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

import app.pipeline.run_pipeline as pipeline_module
from app.services.publish_plan import PUBLISH_OUTPUTS


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "h08"
EXPECTED_MANIFEST_OUTPUTS = {output.key: output.filename for output in PUBLISH_OUTPUTS}
EXPECTED_OUTPUTS = set(EXPECTED_MANIFEST_OUTPUTS.values())
REQUIRED_COVERAGE = {
    "long-chapters",
    "unicode-and-punctuation",
    "image",
    "table",
    "footnote",
    "nested-lists",
    "page-break",
    "yaml-metadata",
    "unusual-heading-structure",
    "large-but-accepted",
    "format-specific-raw-html",
}


def require_export_toolchain() -> None:
    if shutil.which("pandoc") is None or shutil.which("xelatex") is None:
        pytest.skip("pandoc and xelatex are required for the real export integration test")


def prepare_job(tmp_path: Path, name: str, manuscript: str) -> Path:
    job_dir = tmp_path / name
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    (job_dir / "input" / "book.md").write_text(manuscript, encoding="utf-8")
    return job_dir


def png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def write_deterministic_png(path: Path) -> None:
    width = 48
    height = 24
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(
                (
                    (x * 5) % 256,
                    (y * 11) % 256,
                    ((x + y) * 7) % 256,
                )
            )
        rows.append(bytes(row))

    payload = b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
            ),
            png_chunk(b"IDAT", zlib.compress(b"".join(rows), level=9)),
            png_chunk(b"IEND", b""),
        )
    )
    path.write_bytes(payload)


def long_chapters(*, chapter_count: int = 20, paragraphs_per_chapter: int = 7) -> str:
    chapters = []
    for chapter in range(1, chapter_count + 1):
        paragraphs = []
        for paragraph in range(1, paragraphs_per_chapter + 1):
            paragraphs.append(
                " ".join(
                    (
                        f"Deterministic long-chapter paragraph {chapter}.{paragraph}.",
                        "It contains enough ordinary prose to exercise pagination, wrapping,",
                        "table-of-contents growth and multi-format export without adding random data.",
                        "The sentence remains deliberately plain, reproducible and suitable for",
                        "the existing accepted manuscript-size boundary.",
                    )
                )
            )
        chapters.append(
            f"# Long chapter {chapter}\n\n" + "\n\n".join(paragraphs)
        )
    return "\n\n".join(chapters)


def representative_manuscript(image_path: Path) -> str:
    template = (FIXTURE_DIR / "representative.md").read_text(encoding="utf-8")
    rendered = template.replace("{{H08_IMAGE_PATH}}", image_path.resolve().as_posix())
    rendered = rendered.replace("{{H08_LONG_CHAPTERS}}", long_chapters())
    assert "{{H08_" not in rendered
    size = len(rendered.encode("utf-8"))
    assert 30_000 < size < 1_000_000
    return rendered


def assert_pdf(path: Path) -> None:
    data = path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-4096:]


def assert_epub(path: Path) -> None:
    assert zipfile.is_zipfile(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in names
        assert any(name.lower().endswith(".png") for name in names)
        xhtml = b"\n".join(
            archive.read(name)
            for name in names
            if name.lower().endswith((".xhtml", ".html"))
        ).decode("utf-8", errors="replace")
        assert "café" in xhtml
        assert "<table" in xhtml
        assert "deterministic footnote" in xhtml.lower()


def assert_docx(path: Path) -> None:
    assert zipfile.is_zipfile(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert "[Content_Types].xml" in names
        assert "word/document.xml" in names
        assert "word/footnotes.xml" in names
        assert any(name.startswith("word/media/") for name in names)
        document = archive.read("word/document.xml").decode(
            "utf-8",
            errors="replace",
        )
        assert "café" in document
        assert "<w:tbl" in document


def publish_ci_artifacts(repository_root: Path, job_dir: Path) -> None:
    configured = os.getenv("H08_ARTIFACT_DIR", "").strip()
    if not configured:
        return

    artifact_dir = Path(configured)
    if not artifact_dir.is_absolute():
        artifact_dir = repository_root / artifact_dir
    artifact_dir = artifact_dir.resolve()

    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    for output in sorted((job_dir / "output").iterdir()):
        if output.is_file():
            shutil.copy2(output, artifact_dir / output.name)

    for relative in (
        Path("work/book-clean.md"),
        Path("logs/build.log"),
        Path("logs/error.log"),
        Path("status.json"),
        Path("manifest.json"),
    ):
        source = job_dir / relative
        if source.is_file():
            shutil.copy2(source, artifact_dir / source.name)

    status_path = job_dir / "status.json"
    status = (
        json.loads(status_path.read_text(encoding="utf-8"))
        if status_path.is_file()
        else {}
    )
    summary = {
        "fixture": "representative",
        "outputs": sorted(path.name for path in (job_dir / "output").iterdir()),
        "source_bytes": (job_dir / "input" / "book.md").stat().st_size,
        "status": status,
    }
    (artifact_dir / "h08-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def job_failure_diagnostics(job_dir: Path) -> str:
    sections = []
    for relative in (
        Path("status.json"),
        Path("logs/build.log"),
        Path("logs/error.log"),
    ):
        path = job_dir / relative
        if path.is_file():
            sections.append(
                f"===== {relative.as_posix()} =====\n"
                + path.read_text(encoding="utf-8", errors="replace")
            )
    return "\n\n".join(sections) or "No failure diagnostics were written."


def test_corpus_manifest_has_required_coverage_and_failure_categories() -> None:
    corpus = json.loads((FIXTURE_DIR / "corpus.json").read_text(encoding="utf-8"))
    fixtures = corpus["fixtures"]

    assert corpus["version"] == 1
    assert set(fixtures["representative"]["coverage"]) == REQUIRED_COVERAGE
    assert fixtures["representative"]["expected"] == "success"
    assert fixtures["malformed-yaml"]["expected"] == "invalid-input"
    assert fixtures["injected-exporter-failure"]["expected"] == "export-tool-failure"
    assert long_chapters() == long_chapters()


@pytest.mark.integration
def test_representative_corpus_builds_valid_four_format_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_export_toolchain()
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    image_path = tmp_path / "h08-image.png"
    write_deterministic_png(image_path)
    job_dir = prepare_job(
        tmp_path,
        "h08-representative-export",
        representative_manuscript(image_path),
    )

    result = pipeline_module.run_pipeline(job_dir)
    publish_ci_artifacts(repository_root, job_dir)
    assert result == 0, job_failure_diagnostics(job_dir)

    outputs = {path.name for path in (job_dir / "output").iterdir() if path.is_file()}
    assert outputs == EXPECTED_OUTPUTS

    for filename in EXPECTED_OUTPUTS:
        output = job_dir / "output" / filename
        assert output.stat().st_size > 1000, filename

    assert_pdf(job_dir / "output" / "book-standard.pdf")
    assert_pdf(job_dir / "output" / "book-nd.pdf")
    assert_epub(job_dir / "output" / "book.epub")
    assert_docx(job_dir / "output" / "book.docx")

    cleaned = (job_dir / "work" / "book-clean.md").read_text(encoding="utf-8")
    for marker in (
        "café",
        "| Feature | Expected treatment | Evidence |",
        "[^h08-note]",
        "Numbered third level",
        "\\newpage",
        "#### Deliberately unusual heading depth",
        "# Long chapter 20",
        "h08-unsupported-format-probe",
    ):
        assert marker in cleaned

    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    assert status["status"] == "done"
    assert status["step"] == "complete"
    assert manifest["status"]["status"] == "done"
    assert manifest["status"]["step"] == "complete"
    assert manifest["outputs"] == EXPECTED_MANIFEST_OUTPUTS
    assert set(manifest["outputs"].values()) == EXPECTED_OUTPUTS


@pytest.mark.integration
def test_malformed_yaml_fails_as_controlled_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_export_toolchain()
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    manuscript = (FIXTURE_DIR / "malformed-yaml.md").read_text(encoding="utf-8")
    job_dir = prepare_job(tmp_path, "h08-malformed-yaml", manuscript)

    assert pipeline_module.run_pipeline(job_dir) == 1

    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["step"] == "error"
    assert status["message"].startswith("Command failed: pandoc")

    build_log = (job_dir / "logs" / "build.log").read_text(
        encoding="utf-8",
        errors="replace",
    ).lower()
    assert "yaml" in build_log
    assert (job_dir / "logs" / "error.log").is_file()
    assert not any((job_dir / "output").iterdir())


def test_export_tool_failure_remains_distinct_from_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))
    job_dir = prepare_job(
        tmp_path,
        "h08-injected-exporter-failure",
        "---\ntitle: Valid fixture\n---\n\n# Valid Markdown\n",
    )

    def fail_export(*_args, **_kwargs):
        raise RuntimeError("Injected H-08 export-tool failure")

    monkeypatch.setattr(pipeline_module, "pandoc_export", fail_export)

    assert pipeline_module.run_pipeline(job_dir) == 1
    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["step"] == "error"
    assert status["message"] == "Injected H-08 export-tool failure"

    error_log = (job_dir / "logs" / "error.log").read_text(encoding="utf-8")
    assert "Injected H-08 export-tool failure" in error_log
    assert "YAML parse" not in error_log
