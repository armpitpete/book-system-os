from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

import app.pipeline.run_pipeline as pipeline_module
from app.services.publish_plan import PUBLISH_OUTPUTS


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "h08" / "greek-cyrillic.md"
EXPECTED_OUTPUTS = {output.filename for output in PUBLISH_OUTPUTS}
GREEK = "Καλημέρα κόσμε. Η γλώσσα παραμένει ορατή."
CYRILLIC = "Привет, мир. Текст остаётся видимым."
MIXED = "Before Ελληνικά middle Кириллица after."
SENTINELS = (GREEK, CYRILLIC, MIXED, "SCRIPT-BODY-END")


def require_export_toolchain() -> None:
    missing = [tool for tool in ("pandoc", "xelatex", "mutool") if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"required script export tools are unavailable: {', '.join(missing)}")


def prepare_job(tmp_path: Path, manuscript: str) -> Path:
    job_dir = tmp_path / "h08-greek-cyrillic-export"
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    (job_dir / "input" / "book.md").write_text(manuscript, encoding="utf-8")
    return job_dir


def semantic_text(value: str) -> str:
    return " ".join(html.unescape(value).split())


def archive_text(path: Path, suffixes: tuple[str, ...]) -> str:
    with zipfile.ZipFile(path) as archive:
        documents = [
            archive.read(name).decode("utf-8", errors="strict")
            for name in archive.namelist()
            if name.lower().endswith(suffixes)
        ]
    assert documents
    return semantic_text(re.sub(r"<[^>]+>", " ", "\n".join(documents)))


def docx_text(path: Path) -> str:
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return semantic_text(" ".join(node.text or "" for node in root.findall(".//w:t", namespaces)))


def pdf_text(path: Path) -> str:
    completed = subprocess.run(
        ["mutool", "draw", "-q", "-F", "txt", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return semantic_text(completed.stdout)


def publish_ci_artifacts(repository_root: Path, job_dir: Path, manuscript: str) -> None:
    configured = os.getenv("H08_ARTIFACT_DIR", "").strip()
    if not configured:
        return
    configured_path = Path(configured)
    if not configured_path.is_absolute():
        configured_path = repository_root / configured_path
    artifact_dir = configured_path.resolve().parent / "h08-greek-cyrillic"
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)
    for output in sorted((job_dir / "output").iterdir()):
        if output.is_file():
            shutil.copy2(output, artifact_dir / output.name)
    (artifact_dir / "greek-cyrillic-source.md").write_text(manuscript, encoding="utf-8")
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
    (artifact_dir / "greek-cyrillic-summary.json").write_text(
        json.dumps(
            {
                "fixture": "greek-cyrillic",
                "scripts": ["Greek", "Cyrillic"],
                "outputs": {
                    output.name: {"bytes": output.stat().st_size}
                    for output in sorted((job_dir / "output").iterdir())
                    if output.is_file()
                },
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.integration
def test_greek_and_cyrillic_survive_all_four_exports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_export_toolchain()
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    manuscript = FIXTURE.read_text(encoding="utf-8")
    for sentinel in SENTINELS:
        assert sentinel in manuscript
    job_dir = prepare_job(tmp_path, manuscript)

    result = pipeline_module.run_pipeline(job_dir)
    publish_ci_artifacts(repository_root, job_dir, manuscript)
    error_log = job_dir / "logs" / "error.log"
    assert result == 0, error_log.read_text(encoding="utf-8", errors="replace") if error_log.exists() else "No error log"

    outputs = {path.name for path in (job_dir / "output").iterdir() if path.is_file()}
    assert outputs == EXPECTED_OUTPUTS

    readers = (
        archive_text(job_dir / "output" / "book.epub", (".xhtml", ".html")),
        docx_text(job_dir / "output" / "book.docx"),
        pdf_text(job_dir / "output" / "book-standard.pdf"),
        pdf_text(job_dir / "output" / "book-nd.pdf"),
    )
    for reader in readers:
        for sentinel in SENTINELS:
            assert semantic_text(sentinel) in reader

    cleaned = (job_dir / "work" / "book-clean.md").read_text(encoding="utf-8")
    for sentinel in SENTINELS:
        assert sentinel in cleaned

    build_log = (job_dir / "logs" / "build.log").read_text(
        encoding="utf-8", errors="replace"
    ).lower()
    assert "missing character" not in build_log
    assert "fontspec error" not in build_log
    assert "fatal error occurred" not in build_log

    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    assert status["status"] == "done"
    assert manifest["status"]["status"] == "done"
