from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.pipeline.run_pipeline import run_pipeline


@pytest.mark.integration
def test_real_pipeline_builds_all_formats_and_final_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if shutil.which("pandoc") is None or shutil.which("xelatex") is None:
        pytest.skip("pandoc and xelatex are required for the real export integration test")

    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))

    job_dir = tmp_path / "real-export-job"
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)

    manuscript = """---
title: Stable Core Test Book
---

# First chapter

This is a real Book System OS export test.

## Required formats

The worker must produce:

- standard PDF;
- ND-readable PDF;
- EPUB;
- DOCX.

The four output files must be non-empty.
"""
    (job_dir / "input" / "book.md").write_text(manuscript, encoding="utf-8")

    assert run_pipeline(job_dir) == 0

    expected_outputs = {
        "book-standard.pdf",
        "book-nd.pdf",
        "book.epub",
        "book.docx",
    }
    for filename in expected_outputs:
        output = job_dir / "output" / filename
        assert output.is_file(), filename
        assert output.stat().st_size > 0, filename

    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))

    assert status["status"] == "done"
    assert status["step"] == "complete"
    assert manifest["status"]["status"] == "done"
    assert manifest["status"]["step"] == "complete"
    assert set(manifest["outputs"].values()) == expected_outputs
