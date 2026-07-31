from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline import exporters
from app.services.publish_plan import PUBLISH_OUTPUTS


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PACKAGES = (
    "graphicx",
    "float",
    "longtable",
    "booktabs",
    "array",
    "calc",
)


def test_both_pdf_templates_load_required_feature_packages() -> None:
    for relative_path in (
        "templates/book-template-standard.tex",
        "templates/book-template-nd.tex",
    ):
        template = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        for package in REQUIRED_PACKAGES:
            assert rf"\usepackage{{{package}}}" in template, (
                relative_path,
                package,
            )
        assert r"\floatplacement{figure}{H}" in template, relative_path


def test_pdf_exports_use_book_chapters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def capture(
        cmd: list[str],
        *,
        job_dir: Path,
        log_file: Path,
    ) -> None:
        assert job_dir == tmp_path
        assert log_file == tmp_path / "build.log"
        commands.append(cmd)

    monkeypatch.setattr(exporters, "_run_export_command", capture)

    markdown = tmp_path / "book.md"
    markdown.write_text("# Chapter\n", encoding="utf-8")
    outputs = exporters.pandoc_export(
        markdown,
        tmp_path / "output",
        tmp_path / "build.log",
    )

    assert set(outputs) == {output.key for output in PUBLISH_OUTPUTS}
    assert len(commands) == 4
    for command in commands[:2]:
        assert "--top-level-division=chapter" in command
    for command in commands[2:]:
        assert "--top-level-division=chapter" not in command
