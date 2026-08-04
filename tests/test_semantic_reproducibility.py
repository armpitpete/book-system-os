from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

import app.pipeline.run_pipeline as pipeline_module
from app.services.publish_plan import PUBLISH_OUTPUTS


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "h08" / "semantic-reproducibility.md"
EXPECTED_OUTPUTS = {output.filename for output in PUBLISH_OUTPUTS}
SENTINELS = (
    "REPRO-BODY-START",
    "REPRO-TABLE-A",
    "REPRO-TABLE-B",
    "Καλημέρα κόσμε",
    "Привет, мир",
    "REPRO-BODY-END",
    "REPRO-FOOTNOTE",
)


def require_export_toolchain() -> None:
    missing = [tool for tool in ("pandoc", "xelatex", "mutool") if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"required reproducibility tools are unavailable: {', '.join(missing)}")


def prepare_job(tmp_path: Path, manuscript: str, name: str) -> Path:
    job_dir = tmp_path / name
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    (job_dir / "input" / "book.md").write_text(manuscript, encoding="utf-8")
    return job_dir


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def semantic_text(value: str) -> str:
    return " ".join(value.split())


def pdf_signature(path: Path) -> dict[str, object]:
    text_result = subprocess.run(
        ["mutool", "draw", "-q", "-F", "txt", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert text_result.returncode == 0, text_result.stderr
    text = semantic_text(text_result.stdout)

    info_result = subprocess.run(
        ["mutool", "info", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert info_result.returncode == 0, info_result.stderr
    page_match = re.search(r"^Pages:\s*(\d+)\s*$", info_result.stdout, flags=re.MULTILINE)
    assert page_match is not None, info_result.stdout

    for sentinel in SENTINELS:
        assert semantic_text(sentinel) in text
    return {
        "pages": int(page_match.group(1)),
        "text_sha256": sha256_bytes(text.encode("utf-8")),
        "text": text,
    }


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalise_epub_member(name: str, data: bytes) -> bytes:
    if not name.lower().endswith(".opf"):
        return data

    root = ElementTree.fromstring(data)
    for node in root.iter():
        if local_name(node.tag) == "identifier":
            node.text = "VOLATILE-PACKAGE-IDENTIFIER"
        elif local_name(node.tag) == "meta" and node.attrib.get("property") == "dcterms:modified":
            node.text = "VOLATILE-MODIFIED-TIMESTAMP"
    return ElementTree.tostring(root, encoding="utf-8")


def normalise_docx_member(name: str, data: bytes) -> bytes:
    if name.lower() != "docprops/core.xml":
        return data

    root = ElementTree.fromstring(data)
    for node in root.iter():
        if local_name(node.tag) in {"created", "modified"}:
            node.text = "VOLATILE-CORE-TIMESTAMP"
    return ElementTree.tostring(root, encoding="utf-8")


def archive_signature(path: Path, normalise) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        return {
            name: normalise(name, archive.read(name))
            for name in sorted(names)
        }


def differing_members(first: dict[str, bytes], second: dict[str, bytes]) -> list[str]:
    names = sorted(set(first) | set(second))
    return [name for name in names if first.get(name) != second.get(name)]


def archive_fingerprint(members: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(members.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def publish_ci_artifacts(
    repository_root: Path,
    first: Path,
    second: Path,
    summary: dict[str, object],
) -> None:
    configured = os.getenv("H08_ARTIFACT_DIR", "").strip()
    if not configured:
        return

    configured_path = Path(configured)
    if not configured_path.is_absolute():
        configured_path = repository_root / configured_path
    artifact_dir = configured_path.resolve().parent / "h08-semantic-reproducibility"
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)

    for label, job_dir in (("build-a", first), ("build-b", second)):
        destination = artifact_dir / label
        destination.mkdir()
        for output in sorted((job_dir / "output").iterdir()):
            if output.is_file():
                shutil.copy2(output, destination / output.name)
        for relative in (
            Path("input/book.md"),
            Path("work/book-clean.md"),
            Path("logs/build.log"),
            Path("logs/error.log"),
            Path("status.json"),
            Path("manifest.json"),
        ):
            source = job_dir / relative
            if source.is_file():
                shutil.copy2(source, destination / source.name)

    (artifact_dir / "semantic-comparison-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


@pytest.mark.integration
def test_repeated_builds_are_semantically_reproducible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_export_toolchain()
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    manuscript = FIXTURE.read_text(encoding="utf-8")
    first = prepare_job(tmp_path, manuscript, "h08-semantic-build-a")
    second = prepare_job(tmp_path, manuscript, "h08-semantic-build-b")

    assert pipeline_module.run_pipeline(first) == 0
    time.sleep(1.1)
    assert pipeline_module.run_pipeline(second) == 0

    first_outputs = {path.name for path in (first / "output").iterdir() if path.is_file()}
    second_outputs = {path.name for path in (second / "output").iterdir() if path.is_file()}
    assert first_outputs == EXPECTED_OUTPUTS
    assert second_outputs == EXPECTED_OUTPUTS

    first_cleaned = (first / "work" / "book-clean.md").read_bytes()
    second_cleaned = (second / "work" / "book-clean.md").read_bytes()
    assert first_cleaned == second_cleaned

    first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    assert first_manifest["provenance_state"] == second_manifest["provenance_state"]
    assert first_manifest["source_identity"] == second_manifest["source_identity"]
    assert first_manifest["cleaned_markdown"] == second_manifest["cleaned_markdown"]
    assert [item["key"] for item in first_manifest["output_evidence"]] == [
        output.key for output in PUBLISH_OUTPUTS
    ]
    assert [item["key"] for item in second_manifest["output_evidence"]] == [
        output.key for output in PUBLISH_OUTPUTS
    ]

    pdf_results: dict[str, dict[str, object]] = {}
    for filename in ("book-standard.pdf", "book-nd.pdf"):
        first_signature = pdf_signature(first / "output" / filename)
        second_signature = pdf_signature(second / "output" / filename)
        assert first_signature["pages"] == second_signature["pages"]
        assert first_signature["text"] == second_signature["text"]
        pdf_results[filename] = {
            "pages": first_signature["pages"],
            "text_sha256": first_signature["text_sha256"],
            "raw_sha256_a": sha256_file(first / "output" / filename),
            "raw_sha256_b": sha256_file(second / "output" / filename),
        }

    epub_a = archive_signature(first / "output" / "book.epub", normalise_epub_member)
    epub_b = archive_signature(second / "output" / "book.epub", normalise_epub_member)
    assert set(epub_a) == set(epub_b)
    assert differing_members(epub_a, epub_b) == []

    docx_a = archive_signature(first / "output" / "book.docx", normalise_docx_member)
    docx_b = archive_signature(second / "output" / "book.docx", normalise_docx_member)
    assert set(docx_a) == set(docx_b)
    assert differing_members(docx_a, docx_b) == []

    summary: dict[str, object] = {
        "fixture": "semantic-reproducibility",
        "build_delay_seconds": 1.1,
        "normalisations": {
            "pdf": ["ZIP or PDF container metadata excluded; page count and extracted text compared"],
            "epub": [
                "ZIP entry timestamps excluded by member-wise reading",
                "OPF identifier text replaced",
                "OPF dcterms:modified text replaced",
            ],
            "docx": [
                "ZIP entry timestamps excluded by member-wise reading",
                "core created timestamp replaced",
                "core modified timestamp replaced",
            ],
        },
        "cleaned_markdown_sha256": sha256_bytes(first_cleaned),
        "pdf": pdf_results,
        "epub": {
            "members": len(epub_a),
            "semantic_sha256": archive_fingerprint(epub_a),
            "raw_sha256_a": sha256_file(first / "output" / "book.epub"),
            "raw_sha256_b": sha256_file(second / "output" / "book.epub"),
        },
        "docx": {
            "members": len(docx_a),
            "semantic_sha256": archive_fingerprint(docx_a),
            "raw_sha256_a": sha256_file(first / "output" / "book.docx"),
            "raw_sha256_b": sha256_file(second / "output" / "book.docx"),
        },
    }
    publish_ci_artifacts(repository_root, first, second, summary)
