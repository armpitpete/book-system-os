from __future__ import annotations

import shutil
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

import app.pipeline.run_pipeline as pipeline_module
from app.services.publish_plan import PUBLISH_OUTPUTS


NFC_NFD_PAIRS = (
    ("caf\u00e9", "cafe\u0301"),
    ("ma\u00f1ana", "man\u0303ana"),
    ("\u00c5ngstr\u00f6m", "A\u030angstro\u0308m"),
)
DOUBLE_COMBINING = "a\u0304\u0301"
EXPECTED_OUTPUTS = {output.filename for output in PUBLISH_OUTPUTS}


def require_export_toolchain() -> None:
    if shutil.which("pandoc") is None or shutil.which("xelatex") is None:
        pytest.skip("pandoc and xelatex are required for the real export integration test")


def combining_manuscript() -> str:
    lines = [
        "---",
        'title: "Unicode combining regression"',
        "lang: en-GB",
        "---",
        "",
        "# Unicode combining regression",
        "",
        "Each pair below must remain semantically equivalent after export.",
        "",
    ]
    for precomposed, decomposed in NFC_NFD_PAIRS:
        lines.extend(
            (
                f"- Precomposed: {precomposed}",
                f"- Decomposed: {decomposed}",
            )
        )
    lines.extend(
        (
            f"- Two combining marks: {DOUBLE_COMBINING}",
            "",
            "The fixture is intentionally small and deterministic.",
            "",
        )
    )
    return "\n".join(lines)


def prepare_job(tmp_path: Path, manuscript: str) -> Path:
    job_dir = tmp_path / "unicode-combining-export"
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    (job_dir / "input" / "book.md").write_text(manuscript, encoding="utf-8")
    return job_dir


def assert_pdf(path: Path) -> None:
    data = path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"%%EOF" in data[-4096:]


def archive_xml_text(path: Path, names: list[str]) -> str:
    fragments: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            fragments.append("".join(root.itertext()))
    return "\n".join(fragments)


def epub_text(path: Path) -> str:
    assert zipfile.is_zipfile(path)
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html"))
        )
    assert names
    return archive_xml_text(path, names)


def docx_text(path: Path) -> str:
    assert zipfile.is_zipfile(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    assert "word/document.xml" in names
    return archive_xml_text(path, ["word/document.xml"])


def assert_normalised_reader_text(text: str) -> None:
    normalised = unicodedata.normalize("NFC", text)
    for precomposed, decomposed in NFC_NFD_PAIRS:
        assert precomposed != decomposed
        assert unicodedata.normalize("NFC", decomposed) == precomposed
        assert normalised.count(precomposed) >= 2
    assert unicodedata.normalize("NFC", DOUBLE_COMBINING) in normalised


@pytest.mark.integration
def test_unicode_combining_sequences_survive_real_four_format_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_export_toolchain()
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    manuscript = combining_manuscript()
    for precomposed, decomposed in NFC_NFD_PAIRS:
        assert precomposed in manuscript
        assert decomposed in manuscript
        assert tuple(map(ord, precomposed)) != tuple(map(ord, decomposed))
    assert DOUBLE_COMBINING in manuscript
    assert len(tuple(map(ord, DOUBLE_COMBINING))) == 3

    job_dir = prepare_job(tmp_path, manuscript)
    result = pipeline_module.run_pipeline(job_dir)

    diagnostics = "\n\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (
            job_dir / "status.json",
            job_dir / "logs" / "build.log",
            job_dir / "logs" / "error.log",
        )
        if path.is_file()
    )
    assert result == 0, diagnostics or "No failure diagnostics were written."

    outputs = {
        path.name
        for path in (job_dir / "output").iterdir()
        if path.is_file()
    }
    assert outputs == EXPECTED_OUTPUTS
    for filename in EXPECTED_OUTPUTS:
        assert (job_dir / "output" / filename).stat().st_size > 1000

    assert_pdf(job_dir / "output" / "book-standard.pdf")
    assert_pdf(job_dir / "output" / "book-nd.pdf")
    assert_normalised_reader_text(epub_text(job_dir / "output" / "book.epub"))
    assert_normalised_reader_text(docx_text(job_dir / "output" / "book.docx"))

    build_log = (job_dir / "logs" / "build.log").read_text(
        encoding="utf-8",
        errors="replace",
    )
    assert "missing character" not in build_log.lower()
