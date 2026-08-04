from __future__ import annotations

import html
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

import app.pipeline.run_pipeline as pipeline_module
from app.services.publish_plan import PUBLISH_OUTPUTS


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "h08" / "large-footnotes.md"
EXPECTED_OUTPUTS = {output.filename for output in PUBLISH_OUTPUTS}
SENTINELS = [f"FOOTNOTE-{number:02d}" for number in range(1, 65)]
REFERENCE_PATTERN = re.compile(r"\[\^fn\d{2}\]")
DEFINITION_PATTERN = re.compile(r"^\[\^fn\d{2}\]:", flags=re.MULTILINE)


def require_export_toolchain() -> None:
    if shutil.which("pandoc") is None or shutil.which("xelatex") is None:
        pytest.skip("pandoc and xelatex are required for the large-footnote export test")


def prepare_job(tmp_path: Path, manuscript: str) -> Path:
    job_dir = tmp_path / "h08-large-footnotes-export"
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    (job_dir / "input" / "book.md").write_text(manuscript, encoding="utf-8")
    return job_dir


def assert_source_contract(manuscript: str) -> None:
    definitions = DEFINITION_PATTERN.findall(manuscript)
    reference_lines = [
        line for line in manuscript.splitlines() if not line.startswith("[^fn")
    ]
    references = REFERENCE_PATTERN.findall("\n".join(reference_lines))
    assert len(definitions) == 64
    assert len(references) == 64
    for sentinel in SENTINELS:
        assert manuscript.count(sentinel) == 1


def assert_pdf(path: Path) -> None:
    data = path.read_bytes()
    assert len(data) > 1000
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-4096:]


def epub_footnotes(path: Path) -> tuple[str, int]:
    with zipfile.ZipFile(path) as archive:
        documents = [
            archive.read(name).decode("utf-8", errors="strict")
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html"))
        ]
    xhtml = "\n".join(documents)
    text = html.unescape(re.sub(r"<[^>]+>", " ", xhtml))
    footnote_ids = re.findall(r'id=["\']fn\d+["\']', xhtml, flags=re.IGNORECASE)
    return text, len(footnote_ids)


def docx_footnotes(path: Path) -> tuple[str, int]:
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/footnotes.xml"))
    text = " ".join(node.text or "" for node in root.findall(".//w:t", namespaces))
    content_notes = []
    for node in root.findall(".//w:footnote", namespaces):
        raw_id = node.attrib.get(f"{{{namespaces['w']}}}id", "")
        try:
            footnote_id = int(raw_id)
        except ValueError:
            continue
        if footnote_id > 0:
            content_notes.append(node)
    return text, len(content_notes)


def publish_ci_artifacts(repository_root: Path, job_dir: Path, manuscript: str) -> None:
    configured = os.getenv("H08_ARTIFACT_DIR", "").strip()
    if not configured:
        return

    configured_path = Path(configured)
    if not configured_path.is_absolute():
        configured_path = repository_root / configured_path
    artifact_dir = configured_path.resolve().parent / "h08-large-footnotes"

    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    for output in sorted((job_dir / "output").iterdir()):
        if output.is_file():
            shutil.copy2(output, artifact_dir / output.name)

    (artifact_dir / "large-footnotes-source.md").write_text(manuscript, encoding="utf-8")
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

    summary = {
        "fixture": "large-footnotes",
        "references": 64,
        "definitions": 64,
        "outputs": {
            output.name: {"bytes": output.stat().st_size}
            for output in sorted((job_dir / "output").iterdir())
            if output.is_file()
        },
    }
    (artifact_dir / "large-footnotes-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def failure_diagnostics(job_dir: Path) -> str:
    sections = []
    for relative in (Path("status.json"), Path("logs/build.log"), Path("logs/error.log")):
        path = job_dir / relative
        if path.is_file():
            sections.append(
                f"===== {relative.as_posix()} =====\n"
                + path.read_text(encoding="utf-8", errors="replace")
            )
    return "\n\n".join(sections) or "No failure diagnostics were written."


@pytest.mark.integration
def test_large_footnote_set_survives_all_four_exports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_export_toolchain()
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    manuscript = FIXTURE.read_text(encoding="utf-8")
    assert_source_contract(manuscript)
    job_dir = prepare_job(tmp_path, manuscript)

    result = pipeline_module.run_pipeline(job_dir)
    publish_ci_artifacts(repository_root, job_dir, manuscript)
    assert result == 0, failure_diagnostics(job_dir)

    outputs = {path.name for path in (job_dir / "output").iterdir() if path.is_file()}
    assert outputs == EXPECTED_OUTPUTS
    assert_pdf(job_dir / "output" / "book-standard.pdf")
    assert_pdf(job_dir / "output" / "book-nd.pdf")

    epub_text, epub_count = epub_footnotes(job_dir / "output" / "book.epub")
    assert epub_count == 64
    for sentinel in SENTINELS:
        assert sentinel in epub_text

    docx_text, docx_count = docx_footnotes(job_dir / "output" / "book.docx")
    assert docx_count == 64
    for sentinel in SENTINELS:
        assert sentinel in docx_text

    cleaned = (job_dir / "work" / "book-clean.md").read_text(encoding="utf-8")
    assert_source_contract(cleaned)

    build_log = (job_dir / "logs" / "build.log").read_text(
        encoding="utf-8", errors="replace"
    ).lower()
    for fatal_marker in (
        "fatal error occurred",
        "emergency stop",
        "undefined control sequence",
        "dimension too large",
    ):
        assert fatal_marker not in build_log

    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    assert status["status"] == "done"
    assert manifest["status"]["status"] == "done"
    assert [item["key"] for item in manifest["output_evidence"]] == [
        output.key for output in PUBLISH_OUTPUTS
    ]
